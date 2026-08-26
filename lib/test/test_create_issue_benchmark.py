#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Focused tests for the provider-neutral create-issue benchmark."""

import contextlib
import importlib.util
import inspect
import io
import json
import socket
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent.parent
MODULE_PATH = REPOSITORY / "scripts/create_issue_benchmark.py"
WRAPPER_PATH = REPOSITORY / "scripts/create-issue-benchmark.py"
FIXTURE = HERE / "fixtures/create-issue-benchmark"
STUB = FIXTURE / "provider_stub.py"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BENCHMARK = load_module("create_issue_benchmark", MODULE_PATH)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def benchmark_spec(candidate_extra=None, repetitions=1):
    literal = "$(touch should-not-exist); * $HOME"
    return {
        "schema_version": 1,
        "root": str(FIXTURE),
        "benchmark_id": "local-stub-benchmark",
        "repetitions": repetitions,
        "configurations": {
            "baseline": {
                "skill_root": "skills/baseline",
                "argv": [sys.executable, str(STUB), "--literal", literal],
            },
            "candidate": {
                "skill_root": "skills/candidate",
                "argv": [
                    sys.executable,
                    str(STUB),
                    "--literal",
                    literal,
                    *(candidate_extra or []),
                ],
            },
        },
        "scenarios": [
            {"scenario_id": "zeta", "prompt": "prompts/zeta.md", "rubric": "rubric.json"},
            {"scenario_id": "alpha", "prompt": "prompts/alpha.md", "rubric": "rubric.json"},
        ],
    }


class SpecValidationTest(unittest.TestCase):
    def test_schema_one_requires_two_argv_configurations_and_positive_repetitions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "spec.json"
            cases = [
                ({**benchmark_spec(), "schema_version": 2}, "unsupported_schema_version"),
                ({**benchmark_spec(), "repetitions": 0}, "invalid_repetitions"),
                ({**benchmark_spec(), "configurations": {}}, "invalid_configurations"),
            ]
            for value, diagnostic in cases:
                with self.subTest(diagnostic=diagnostic):
                    write_json(path, value)
                    with self.assertRaisesRegex(ValueError, diagnostic):
                        BENCHMARK.load_benchmark_spec(path)

    def test_a_non_finite_or_non_positive_timeout_is_refused(self):
        """NaN is the load-bearing row: subprocess.run(timeout=nan) never fires."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "spec.json"
            for label, bad in (
                ("nan", float("nan")),
                ("inf", float("inf")),
                ("zero", 0),
                ("negative", -1),
                ("bool", True),
                ("string", "30"),
                ("object", {}),
                ("array", []),
            ):
                with self.subTest(timeout_seconds=label):
                    value = benchmark_spec()
                    value["configurations"]["candidate"]["timeout_seconds"] = bad
                    write_json(path, value)
                    with self.assertRaisesRegex(ValueError, "invalid_timeout_seconds"):
                        BENCHMARK.load_benchmark_spec(path)
            # Positive controls: a real limit and an omitted one both load.
            for label, good in (("finite", 30), ("float", 1.5), ("absent", None)):
                with self.subTest(timeout_seconds=label):
                    value = benchmark_spec()
                    if good is not None:
                        value["configurations"]["candidate"]["timeout_seconds"] = good
                    write_json(path, value)
                    spec = BENCHMARK.load_benchmark_spec(path)
                    self.assertEqual(
                        spec["configurations"]["candidate"]["timeout_seconds"], good
                    )

    def test_paths_may_not_escape_declared_root_and_argv_must_be_a_string_list(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "spec.json"
            value = benchmark_spec()
            value["scenarios"][0]["prompt"] = "../outside.md"
            write_json(path, value)
            with self.assertRaisesRegex(ValueError, "path_escape"):
                BENCHMARK.load_benchmark_spec(path)
            value = benchmark_spec()
            value["configurations"]["candidate"]["argv"] = "provider --flag"
            write_json(path, value)
            with self.assertRaisesRegex(ValueError, "invalid_argv"):
                BENCHMARK.load_benchmark_spec(path)

    def test_scenario_ids_that_could_reach_outside_their_run_directory_are_refused(self):
        # scenario_id is joined into run/artifact paths, so every rejected shape
        # here is a directory-traversal or collision vector; a widened charset
        # or a dropped duplicate check must fail this, not ship green.
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "spec.json"
            rejected = [".", "..", "a/b", "a\\b", "a\0b", "a b", "~root", "$HOME", ""]
            for scenario_id in rejected:
                with self.subTest(scenario_id=scenario_id):
                    value = benchmark_spec()
                    value["scenarios"][0]["scenario_id"] = scenario_id
                    write_json(path, value)
                    with self.assertRaisesRegex(ValueError, "invalid_scenario"):
                        BENCHMARK.load_benchmark_spec(path)
            value = benchmark_spec()
            value["scenarios"][1]["scenario_id"] = value["scenarios"][0]["scenario_id"]
            write_json(path, value)
            with self.assertRaisesRegex(ValueError, "invalid_scenario"):
                BENCHMARK.load_benchmark_spec(path)
            accepted = benchmark_spec()
            accepted["scenarios"][0]["scenario_id"] = "Alpha_2.beta-3"
            write_json(path, accepted)
            spec = BENCHMARK.load_benchmark_spec(path)
            self.assertEqual(spec["scenarios"][0]["scenario_id"], "Alpha_2.beta-3")


class RunnerTest(unittest.TestCase):
    def test_runs_matched_peers_with_literal_argv_controlled_environment_and_artifacts(self):
        with tempfile.TemporaryDirectory(prefix="benchmark output with spaces ") as temporary:
            root = Path(temporary)
            spec_path = root / "spec with spaces.json"
            output = root / "result with spaces"
            write_json(spec_path, benchmark_spec(repetitions=2))
            ticks = iter(range(0, 16_000_000, 1_000_000))
            # Parent-process only: the provider is a separate interpreter, so this
            # covers the runner's own code, never the stub's network behaviour.
            with unittest.mock.patch.object(
                socket, "create_connection", side_effect=AssertionError("network used")
            ):
                manifest = BENCHMARK.run_benchmark(
                    spec_path, output, monotonic_ns=lambda: next(ticks)
                )

            identities = [
                (item["scenario_id"], item["repetition"], item["configuration"])
                for item in manifest["executions"]
            ]
            self.assertEqual(identities, [
                ("alpha", 1, "baseline"), ("alpha", 1, "candidate"),
                ("alpha", 2, "baseline"), ("alpha", 2, "candidate"),
                ("zeta", 1, "baseline"), ("zeta", 1, "candidate"),
                ("zeta", 2, "baseline"), ("zeta", 2, "candidate"),
            ])
            self.assertEqual([item["duration_ms"] for item in manifest["executions"]], [1] * 8)
            # Assert the shell-injection guard BEFORE the run-count assertion: under
            # shell=True the count assertion aborts first and this one never runs.
            # The provider runs with cwd=spec["root"], so the file would land there.
            self.assertFalse((FIXTURE / "should-not-exist").exists())
            self.assertEqual(len(manifest["runs"]), 8)
            controlled_names = {
                "PRFLOW_BENCHMARK_CONFIGURATION",
                "PRFLOW_BENCHMARK_SCENARIO_ID",
                "PRFLOW_BENCHMARK_REPETITION",
                "PRFLOW_BENCHMARK_PROMPT_PATH",
                "PRFLOW_BENCHMARK_SKILL_ROOT",
                "PRFLOW_BENCHMARK_OUTPUT_DIR",
            }
            for execution in manifest["executions"]:
                self.assertEqual(execution["status"], "succeeded")
                self.assertEqual(execution["exit_code"], 0)
                run_dir = output / Path(execution["output_dir"])
                observation = json.loads(
                    (run_dir / "provider-observation.json").read_text(encoding="utf-8")
                )
                self.assertEqual(set(observation["controlled_environment"]), controlled_names)
                self.assertIn("$(touch should-not-exist); * $HOME", observation["argv"])
                self.assertEqual(
                    "provider stdout\n", (output / execution["stdout"]).read_text()
                )
                self.assertEqual(
                    "provider stderr\n", (output / execution["stderr"]).read_text()
                )
            for name in ("run-manifest.json", "benchmark.json", "benchmark.md", "review.json"):
                self.assertTrue((output / name).is_file(), name)

    def test_nonzero_provider_keeps_exit_error_artifacts_and_discloses_incomplete_pair(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path = root / "spec.json"
            output = root / "output"
            value = benchmark_spec(candidate_extra=["--fail"])
            value["scenarios"] = value["scenarios"][:1]
            write_json(spec_path, value)
            manifest = BENCHMARK.run_benchmark(spec_path, output)
            candidate = next(
                item for item in manifest["executions"]
                if item["configuration"] == "candidate"
            )
            self.assertEqual(candidate["status"], "failed")
            self.assertEqual(candidate["exit_code"], 9)
            self.assertIn("provider_exit_nonzero", (output / candidate["error"]).read_text())
            report = json.loads((output / "benchmark.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "unestablished")
            self.assertEqual(report["diagnostic"], "incomplete_pairs")
            self.assertEqual(report["paired_deltas"], "unestablished")
            self.assertEqual(report["efficiency"]["status"], "withheld")

    def test_successful_provider_manifest_must_be_rooted_in_its_assigned_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path = root / "spec.json"
            output = root / "output"
            value = benchmark_spec(candidate_extra=["--escape-root"])
            value["scenarios"] = value["scenarios"][:1]
            write_json(spec_path, value)
            manifest = BENCHMARK.run_benchmark(spec_path, output)
            candidate = next(
                item for item in manifest["executions"]
                if item["configuration"] == "candidate"
            )
            self.assertEqual(candidate["status"], "failed")
            self.assertIn("provider_root_mismatch", (output / candidate["error"]).read_text())

    def test_zero_exit_without_a_provider_manifest_is_recorded_as_failed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path = root / "spec.json"
            output = root / "output"
            value = benchmark_spec(candidate_extra=["--omit-manifest"])
            value["scenarios"] = value["scenarios"][:1]
            write_json(spec_path, value)
            manifest = BENCHMARK.run_benchmark(spec_path, output)
            candidate = next(
                item for item in manifest["executions"]
                if item["configuration"] == "candidate"
            )
            self.assertEqual(candidate["status"], "failed")
            self.assertIn("invalid_manifest", (output / candidate["error"]).read_text())


class ProviderLaunchFailureTest(unittest.TestCase):
    def test_an_unlaunchable_provider_is_recorded_as_a_failed_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path = root / "spec.json"
            output = root / "result"
            write_json(spec_path, benchmark_spec())
            control = BENCHMARK.run_benchmark(spec_path, output / "control")
            self.assertTrue(control["runs"])
            self.assertEqual(
                {item["status"] for item in control["executions"]}, {"succeeded"}
            )

            # Do not inline this into both the side_effect and the assertion below:
            # a second spelling makes the assertion a source-literal presence pin the
            # issue-810 mutation-routing gate reports, instead of a round-trip check.
            strerror = "Exec format error"
            with unittest.mock.patch.object(
                BENCHMARK.subprocess, "run",
                side_effect=OSError(8, strerror),
            ):
                manifest = BENCHMARK.run_benchmark(spec_path, output / "failed")

            self.assertEqual(manifest["runs"], [])
            self.assertTrue(manifest["executions"])
            for execution in manifest["executions"]:
                self.assertEqual(execution["status"], "failed")
                self.assertIn("error", execution)
                recorded = (output / "failed" / execution["error"]).read_text(
                    encoding="utf-8")
                self.assertIn("provider_launch_error", recorded)
                self.assertIn(strerror, recorded)


class AggregationTest(unittest.TestCase):
    def test_statistics_include_count_mean_median_population_stddev_and_variance(self):
        self.assertEqual(BENCHMARK.describe([1, 3]), {
            "status": "established",
            "count": 2,
            "mean": 2.0,
            "median": 2.0,
            "population_stddev": 1.0,
            "coefficient_of_variation": 0.5,
            "high_variance": True,
        })

    def test_a_zero_mean_population_reports_an_unestablished_coefficient(self):
        self.assertEqual(BENCHMARK.describe([0, 0]), {
            "status": "established",
            "count": 2,
            "mean": 0.0,
            "median": 0.0,
            "population_stddev": 0.0,
            "coefficient_of_variation": 0.0,
            "high_variance": False,
        })
        self.assertEqual(BENCHMARK.describe([-1, 1]), {
            "status": "established",
            "count": 2,
            "mean": 0.0,
            "median": 0.0,
            "population_stddev": 1.0,
            "coefficient_of_variation": BENCHMARK.UNESTABLISHED,
            "high_variance": True,
        })

    def test_a_zero_mean_metric_reaches_the_disclosures_list(self):
        fixture = json.loads(
            (FIXTURE / "historical-4-to-8.json").read_text(encoding="utf-8")
        )
        clean = BENCHMARK.aggregate_benchmark(fixture, fixture["executions"])
        self.assertNotIn(
            "high_variance:paired_delta:finding_count", clean["disclosures"]
        )
        # A mirrored second pair makes the finding_count deltas [+4, -4]: mean exactly 0
        # with a non-zero deviation, so aggregate_benchmark reaches describe()'s
        # zero-mean arm end to end and discloses high variance.
        for run in list(fixture["runs"]):
            mirrored = json.loads(json.dumps(run))
            mirrored["run_id"] = run["run_id"] + "-mirror"
            mirrored["scenario_id"] = "mirror"
            mirrored["finding_count"] = 4 if run["configuration"] == "candidate" else 8
            fixture["runs"].append(mirrored)
            fixture["executions"].append(
                {"run_id": mirrored["run_id"], "duration_ms": 1500, "status": "succeeded"}
            )
        report = BENCHMARK.aggregate_benchmark(fixture, fixture["executions"])
        summary = report["paired_deltas"]["finding_count"]
        self.assertEqual(summary["mean"], 0.0)
        self.assertEqual(summary["coefficient_of_variation"], BENCHMARK.UNESTABLISHED)
        self.assertIn("high_variance:paired_delta:finding_count", report["disclosures"])

    def test_executions_not_covering_every_run_withholds_credit(self):
        """Absent execution evidence must not read as "every run succeeded"."""
        fixture = json.loads(
            (FIXTURE / "historical-4-to-8.json").read_text(encoding="utf-8")
        )
        complete = fixture["executions"]
        for label, executions in (
            ("absent", []),
            ("short", complete[:1]),
            ("unrelated", [{"run_id": "no-such-run", "status": "succeeded"}]),
        ):
            with self.subTest(executions=label):
                report = BENCHMARK.aggregate_benchmark(fixture, executions)
                self.assertEqual(report["status"], BENCHMARK.UNESTABLISHED)
                self.assertEqual(report["diagnostic"], "incomplete_pairs")
                self.assertEqual(report["efficiency"]["status"], "withheld")
        # Positive control: the same fixture with its own complete executions is
        # graded, so the matrix above cannot pass by refusing every input.
        graded = BENCHMARK.aggregate_benchmark(fixture, complete)
        self.assertNotEqual(graded["diagnostic"], "incomplete_pairs")

    def test_a_wrong_typed_executions_field_degrades_rather_than_raising(self):
        """aggregate_benchmark itself never raises on a wrong-typed executions field.

        It returns an unestablished report; the CLI-level refusal is its sibling.
        """
        fixture = json.loads(
            (FIXTURE / "historical-4-to-8.json").read_text(encoding="utf-8")
        )
        for label, executions in (
            ("string", "oops"),
            ("mapping", {"a": {"run_id": "x", "status": "succeeded"}}),
            ("scalar-members", ["oops", 3, None]),
            # A non-iterable is the row that discriminates the isinstance-list
            # normalization; every iterable row survives without it.
            ("non-iterable", 3),
        ):
            with self.subTest(executions=label):
                report = BENCHMARK.aggregate_benchmark(fixture, executions)
                self.assertEqual(report["status"], BENCHMARK.UNESTABLISHED)
                self.assertEqual(report["diagnostic"], "incomplete_pairs")

    def test_a_wrong_typed_executions_field_exits_two_through_the_cli(self):
        """The exit code alone does not attribute: pin the executions diagnostic.

        The historical fixture fails an earlier `root` check, so asserting rc 2 on it
        would pass with this guard deleted.
        """
        for label, value, expected in (
            ("string", "oops", "executions is not a list"),
            ("mapping", {"a": 1}, "executions is not a list"),
            ("scalar-members", ["oops"], "executions contains a non-object member"),
        ):
            with self.subTest(executions=label):
                with tempfile.TemporaryDirectory() as tmp:
                    manifest = Path(tmp) / "manifest.json"
                    manifest.write_text(json.dumps({
                        "schema_version": 1,
                        "benchmark_id": "b",
                        "root": ".",
                        "runs": [],
                        "executions": value,
                    }), encoding="utf-8")
                    err = io.StringIO()
                    with contextlib.redirect_stderr(err):
                        code = BENCHMARK.main(["report", "--manifest", str(manifest)])
                self.assertEqual(code, 2)
                self.assertIn(expected, err.getvalue())
        # Positive control: the same otherwise-valid manifest with a well-formed
        # executions list is not refused, so the matrix cannot pass by refusing all.
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            manifest.write_text(json.dumps({
                "schema_version": 1,
                "benchmark_id": "b",
                "root": ".",
                "runs": [],
                "executions": [],
            }), encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = BENCHMARK.main(["report", "--manifest", str(manifest)])
        self.assertEqual(code, 0)
        self.assertNotIn("executions", err.getvalue())

    def test_historical_four_to_eight_findings_withholds_reduced_token_credit(self):
        fixture = json.loads(
            (FIXTURE / "historical-4-to-8.json").read_text(encoding="utf-8")
        )
        report = BENCHMARK.aggregate_benchmark(
            fixture, fixture["executions"]
        )
        self.assertEqual(report["quality"]["pass_rate"], 0.0)
        self.assertEqual(report["pairs"][0]["delta"]["finding_count"], 4)
        self.assertLess(report["pairs"][0]["delta"]["auditor_tokens"], 0)
        self.assertEqual(report["efficiency"]["status"], "withheld")
        self.assertEqual(report["efficiency"]["credited_paired_deltas"], "unestablished")

    def test_mixed_provenance_refuses_paired_statistics(self):
        fixture = json.loads(
            (FIXTURE / "historical-4-to-8.json").read_text(encoding="utf-8")
        )
        fixture["comparison"] = {
            "status": "unestablished", "diagnostic": "mixed_provenance"
        }
        report = BENCHMARK.aggregate_benchmark(fixture, fixture["executions"])
        self.assertEqual(report["status"], "unestablished")
        self.assertEqual(report["diagnostic"], "mixed_provenance")
        self.assertEqual(report["paired_deltas"], "unestablished")


class ReviewExportTest(unittest.TestCase):
    def test_review_assignments_are_deterministic_anonymized_pointers_without_bodies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path = root / "spec.json"
            output = root / "output"
            value = benchmark_spec()
            value["scenarios"] = value["scenarios"][:1]
            write_json(spec_path, value)
            BENCHMARK.run_benchmark(spec_path, output)
            first = (output / "review.json").read_text(encoding="utf-8")
            BENCHMARK.write_benchmark_outputs(output / "run-manifest.json")
            second = (output / "review.json").read_text(encoding="utf-8")
            self.assertEqual(first, second)
            review = json.loads(first)
            self.assertEqual([entry["repetition"] for entry in review["entries"]], [1])
            serialized = json.dumps(review)
            self.assertNotIn("baseline", serialized)
            self.assertNotIn("candidate", serialized)
            self.assertNotIn("cache invalidation", serialized)
            for label in ("A", "B"):
                self.assertEqual(
                    set(review["entries"][0][label]), {"issue_artifact", "grade_artifact"}
                )
                self.assertTrue((output / review["entries"][0][label]["issue_artifact"]).is_file())
                self.assertTrue((output / review["entries"][0][label]["grade_artifact"]).is_file())


class CliTest(unittest.TestCase):
    def test_report_json_and_text_are_deterministic(self):
        fixture = json.loads(
            (FIXTURE / "historical-4-to-8.json").read_text(encoding="utf-8")
        )
        with unittest.mock.patch.object(
            BENCHMARK, "build_benchmark_report",
            return_value=BENCHMARK.aggregate_benchmark(fixture, fixture["executions"]),
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(BENCHMARK.main([
                    "report", "--manifest", "fixture.json", "--format", "json"
                ]), 0)
            parsed = json.loads(output.getvalue())
            self.assertEqual(next(iter(parsed)), "schema_version")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(BENCHMARK.main([
                    "report", "--manifest", "fixture.json", "--format", "text"
                ]), 0)
            self.assertLess(output.getvalue().index("Quality"), output.getvalue().index("Efficiency"))

    def test_non_object_manifest_exits_two_with_the_contracted_diagnostic(self):
        """A VALID-JSON non-object manifest must take the module's own error exit."""
        for payload in ("[]", '"a string"', "7", "null"):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp:
                manifest = Path(tmp) / "manifest.json"
                manifest.write_text(payload, encoding="utf-8")
                errors = io.StringIO()
                with contextlib.redirect_stderr(errors):
                    rc = BENCHMARK.main(["report", "--manifest", str(manifest)])
                self.assertEqual(rc, 2)
                # Attribute the rejection: the top-level-shape guard, not a parse error
                # and not a missing-file OSError, both of which also exit 2 here.
                self.assertIn("invalid_manifest: top level is not an object",
                              errors.getvalue())

    def test_a_well_formed_manifest_is_not_rejected_by_that_guard(self):
        """Positive control: the same code path succeeds on an object manifest."""
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            write_json(manifest, {"benchmark_id": "b", "executions": []})
            report = BENCHMARK.build_benchmark_report(manifest)
            self.assertEqual(report["benchmark_id"], "b")

    def test_write_benchmark_outputs_guards_the_same_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            manifest.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                BENCHMARK.write_benchmark_outputs(manifest)
            self.assertIn("invalid_manifest: top level is not an object", str(caught.exception))
            # Positive control in the same method: an object manifest still writes.
            write_json(manifest, {"benchmark_id": "b", "executions": []})
            BENCHMARK.write_benchmark_outputs(manifest)
            self.assertTrue((Path(tmp) / "benchmark.json").is_file())


class WrapperTest(unittest.TestCase):
    """The hyphenated compatibility entry point is a real, exercised surface.

    Loading only the underscore module leaves the wrapper's re-export loop and its
    `main` delegation untested, so a broken wrapper would ship green.
    """

    def setUp(self):
        self.wrapper = load_module("create_issue_benchmark_wrapper", WRAPPER_PATH)

    def test_the_wrapper_re_exports_the_implementation_names(self):
        for name in ("main", "run_benchmark", "build_benchmark_report", "SCHEMA_VERSION"):
            self.assertTrue(hasattr(self.wrapper, name), name)
        # The wrapper execs its own copy of the implementation, so identity does not
        # hold; assert behavioral equivalence rather than a name, which any same-named
        # callable would satisfy.
        self.assertEqual(inspect.signature(self.wrapper.build_benchmark_report),
                         inspect.signature(BENCHMARK.build_benchmark_report))
        self.assertEqual(self.wrapper.SCHEMA_VERSION, BENCHMARK.SCHEMA_VERSION)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            write_json(manifest, {"benchmark_id": "b", "executions": []})
            self.assertEqual(self.wrapper.build_benchmark_report(manifest),
                             BENCHMARK.build_benchmark_report(manifest))

    def test_the_wrapper_runs_as_a_script(self):
        """`load_module` never executes `__main__`, so the process entry point needs this."""
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            manifest.write_text("[]", encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(WRAPPER_PATH), "report", "--manifest", str(manifest)],
                capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 2, completed.stderr)
            self.assertIn("invalid_manifest", completed.stderr)

    def test_wrapper_main_dispatches_to_the_implementation(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            manifest.write_text("[]", encoding="utf-8")
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                rc = self.wrapper.main(["report", "--manifest", str(manifest)])
            self.assertEqual(rc, 2)
            self.assertIn("invalid_manifest", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
