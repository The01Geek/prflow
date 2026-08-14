#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Focused tests for the provider-neutral create-issue benchmark."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
import unittest.mock


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


class RunnerTest(unittest.TestCase):
    def test_runs_matched_peers_with_literal_argv_controlled_environment_and_artifacts(self):
        with tempfile.TemporaryDirectory(prefix="benchmark output with spaces ") as temporary:
            root = Path(temporary)
            spec_path = root / "spec with spaces.json"
            output = root / "result with spaces"
            write_json(spec_path, benchmark_spec(repetitions=2))
            ticks = iter(range(0, 16_000_000, 1_000_000))
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
                # structural-pin-ok: machine-sentinel-provenance -- the provider's fixed
                # stdout/stderr sentinels prove each captured stream maps to its named artifact
                self.assertIn("provider stdout", (output / execution["stdout"]).read_text())
                self.assertIn("provider stderr", (output / execution["stderr"]).read_text())
            self.assertFalse((Path.cwd() / "should-not-exist").exists())
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


if __name__ == "__main__":
    unittest.main()
