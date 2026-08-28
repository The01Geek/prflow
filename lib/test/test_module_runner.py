#!/usr/bin/env python3
"""Focused tests for the experimental pre-source test-module runner."""

# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from typing import NamedTuple
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
RUNNER_SOURCE = ROOT / "lib/test/run-module.sh"
HARNESS_SOURCE = ROOT / "lib/test/module-harness.sh"
RUN_SH_SOURCE = ROOT / "lib/test/run.sh"
MODULES_DIR = ROOT / "lib/test/modules"
WORKFLOW_MODULE_SOURCE = ROOT / "lib/test/modules/workflow-flight-recorder.sh"
CREATE_ISSUE_MODULE_SOURCE = ROOT / "lib/test/modules/create-issue-contract.sh"
CAPABILITY_PROFILES_MODULE_SOURCE = ROOT / "lib/test/modules/capability-profiles.sh"

# Do NOT widen this to the full exact-policy set unconditionally and do NOT empty it:
# it is the reduced population used ONLY under the parallel coordinator, where the full
# fan-out oversubscribes a contended host. The modules-* shards enforce `>=` only, so
# dropping the unconditional fan-out here would leave a stale-low floor undetected.
REAL_EXECUTION_MODULES = ("harness-python-guards", "review-trigger-helpers")


def _under_parallel_coordinator() -> bool:
    """True when `lib/test/run-parallel.sh` scheduled this process.

    The coordinator exports DEVFLOW_POOL_WIDTH into the python-pool shard only, so its
    presence distinguishes a contended shared host from CI's dedicated per-shard runner
    (and a direct local run), which execute the full exact-policy population.
    """
    return bool(os.environ.get("DEVFLOW_POOL_WIDTH", "").strip())


def _pool_width() -> int:
    """Worker bound for the module fan-out.

    `lib/test/run-parallel.sh` exports DEVFLOW_POOL_WIDTH (its POOL_RESERVATION) into
    the python-pool shard only. Honouring it keeps this test's real process count inside
    the slot budget the coordinator scheduled against; a value that is PRESENT but
    unparseable or non-positive falls back to a conservative cap rather than to the host
    CPU count, since the export's presence says a coordinator scheduled against a slot
    budget this process can no longer read. An ABSENT export means no coordinator, so
    the host CPU count is the bound — that keeps CI's dedicated python-pool runner at
    full width.
    """
    declared = os.environ.get("DEVFLOW_POOL_WIDTH", "").strip()
    if declared:
        try:
            width = int(declared)
        except ValueError:
            width = 0
        if width >= 1:
            return width
        return min(os.cpu_count() or 2, 2)
    return os.cpu_count() or 2

# An extracted module must reference NO helper that lives only in the monolith
# lib/test/run.sh — it uses only assert_eq, the namespaced devflow_module_* API, the
# shared fixture helpers module-harness.sh defines, and its own private helpers. This
# matches each banned helper as a standalone token, so the namespaced names
# (devflow_module_pin_count, …) whose `pin_count` substring is preceded by `_` never
# trip it. `mint_blk`, `probe_tmp` and `probe_assert` are deliberately ABSENT from this
# list since issue #695 promoted all three out of run.sh into module-harness.sh, where a
# module legitimately obtains them; the guard that keeps them harness-owned is the
# single-definition assertion below, not this ban.
MONOLITH_HELPER_RE = re.compile(
    r"(?:^|[^A-Za-z0-9_])"
    r"(pin_count|grep_present"
    r"|assert_pin_unique|assert_pin_red_on_removal)"
    r"(?:[^A-Za-z0-9_]|$)"
)

# A module may not self-skip: run-module.sh overrides `skip` to a fatal. Since issue #838
# a module may declare a host-capability condition through `module_host_capability_skip`,
# which the boundary validates and folds — but the raw helper stays out of reach, which is
# what this pattern enforces. Match it only in command position (a line whose first token
# is exactly `skip`), so the wrapper's own name, and prose mentioning the word in a
# comment, are not false positives.
MODULE_SKIP_CALL_RE = re.compile(r"^[ \t]*skip(?:[ \t]|$)", re.MULTILINE)

# The fixture helpers promoted from lib/test/run.sh into lib/test/module-harness.sh —
# `mint_blk` / `probe_tmp` / `probe_assert` by issue #695, `git_sandbox` alongside the
# issue-audit-state extraction. Exactly one definition of each must exist tree-wide.
# A promotion that does not extend this tuple leaves its own helper unguarded, which is
# why the tuple is edited in the same change as the promotion.
PROMOTED_HARNESS_HELPERS = ("mint_blk", "probe_tmp", "probe_assert", "git_sandbox")


class ModuleRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.test_dir = self.root / "lib/test"
        self.modules_dir = self.test_dir / "modules"
        self.scripts_dir = self.root / "scripts"
        self.modules_dir.mkdir(parents=True)
        self.scripts_dir.mkdir()

        self.runner = self.test_dir / "run-module.sh"
        if RUNNER_SOURCE.exists():
            shutil.copy2(RUNNER_SOURCE, self.runner)
        if HARNESS_SOURCE.exists():
            shutil.copy2(HARNESS_SOURCE, self.test_dir / "module-harness.sh")

        self.marker = self.root / "module-sourced"
        self._write_module(
            "sample.sh",
            'printf "sourced\\n" > "$SOURCE_MARKER"\n'
            'assert_eq "sample assertion" "expected" "expected"\n',
        )
        self._write_module(
            "empty.sh",
            'printf "sourced\\n" > "$SOURCE_MARKER"\n',
        )
        self._write_module(
            "crash.sh",
            'printf "sourced\\n" > "$SOURCE_MARKER"\nexit 7\n',
        )
        self._write_module(
            "invalid-tally.sh",
            'printf "INVALID\\n" >> "$RESULTS_FILE"\n'
            'assert_eq "valid assertion after invalid record" "expected" "expected"\n',
        )
        # Issue #890: reports the heavy-unit population the runner handed the module body,
        # so --heavy-units can be driven without running a real (expensive) module.
        self._write_module(
            "heavy-units.sh",
            'printf "HEAVY-UNITS=%s\\n" "${MODULE_HEAVY_UNIT_MODE-unset}"\n'
            # A real child PROCESS, not another subshell: this is the only shape that
            # observes the runner's `export -n`, whose whole job is to stop the mode
            # propagating past the module body it is meant for.
            'bash -c \'printf "HEAVY-UNITS-CHILD=%s\\n" "${MODULE_HEAVY_UNIT_MODE-unset}"\'\n'
            'assert_eq "heavy-units assertion" "expected" "expected"\n',
        )
        # Stands in for a module that bounds a heavy unit nobody asked to bound — a
        # literal or defaulted `smoke` in its own driver call. It emits the driver's own
        # bound clause without consulting the mode, which is exactly what such a module
        # would produce.
        self._write_module(
            "unrequested-bound.sh",
            'printf "  x.py: executed 1 test(s) across 1 concurrent worker(s) '
            '(1 enumerated, BOUNDED smoke subset — the full population did NOT run)\\n"\n'
            'assert_eq "unrequested-bound assertion" "expected" "expected"\n',
        )
        self._write_module(
            "blocking.sh",
            'printf "ready\\n" > "$READY_MARKER"\n'
            'sleep 5\n'
            'assert_eq "blocking assertion" "expected" "expected"\n',
        )
        shutil.copy2(
            WORKFLOW_MODULE_SOURCE,
            self.modules_dir / "workflow-flight-recorder.sh",
        )
        self._write_registry(
            {
                "sample": {"path": "lib/test/modules/sample.sh"},
                "empty": {"path": "lib/test/modules/empty.sh"},
                "crash": {"path": "lib/test/modules/crash.sh"},
                "invalid-tally": {"path": "lib/test/modules/invalid-tally.sh"},
                "heavy-units": {"path": "lib/test/modules/heavy-units.sh"},
                "unrequested-bound": {
                    "path": "lib/test/modules/unrequested-bound.sh"
                },
                "blocking": {"path": "lib/test/modules/blocking.sh"},
                "workflow-flight-recorder": {
                    "path": "lib/test/modules/workflow-flight-recorder.sh"
                },
            }
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _write_module(self, name: str, body: str) -> None:
        (self.modules_dir / name).write_text(body, encoding="utf-8")

    def _write_registry(self, modules: object) -> None:
        if isinstance(modules, dict):
            modules = {
                module_id: (
                    {**mapping, "minimum_assertions": mapping.get("minimum_assertions", 1)}
                    if isinstance(mapping, dict)
                    else mapping
                )
                for module_id, mapping in modules.items()
            }
        document = {
            "schema_version": 1,
            "workflows": {"placeholder": {}},
            "test_modules": modules,
        }
        (self.scripts_dir / "workflow-flight-recorder-registry.json").write_text(
            json.dumps(document), encoding="utf-8"
        )

    def _run_args(
        self, *args: str, extra_env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.pop("DEVFLOW_TEST_EXPERIMENT_FORCE_FAILURE", None)
        for name in (
            "DEVFLOW_TEST_RUNNER_PID_FILE",
            "DEVFLOW_TEST_MODULE_PID_FILE",
            "DEVFLOW_TEST_MODULE_WORKER_PID_FILE",
            "DEVFLOW_TEST_HELPER_PID_FILE",
            "DEVFLOW_TEST_RUNNER_CLEANUP_MARKER",
            "DEVFLOW_TEST_MODULE_CLEANUP_MARKER",
            "DEVFLOW_TEST_MODULE_STATE_FILE",
            "DEVFLOW_TEST_GENERIC_SCRATCH_FILE",
            "DEVFLOW_TEST_SIGNAL_RESISTANT_HELPER",
            "DEVFLOW_TEST_LAUNCH_WINDOW_FILE",
        ):
            environment.pop(name, None)
        environment["SOURCE_MARKER"] = str(self.marker)
        if extra_env:
            environment.update(extra_env)
        return subprocess.run(
            ["bash", str(self.runner), *args],
            cwd=self.root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def _run(
        self, module: str, *, extra_env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return self._run_args(module, extra_env=extra_env)

    def _log_path(self, result: subprocess.CompletedProcess[str]) -> Path:
        for line in result.stdout.splitlines():
            if line.startswith("Log: "):
                return Path(line.removeprefix("Log: "))
        self.fail(f"runner output did not name its log:\n{result.stdout}")

    def test_heavy_units_defaults_to_full_and_ignores_an_inherited_value(self) -> None:
        """Issue #890. The bounded heavy-unit population is a real coverage reduction, so
        the thing that must be impossible is ACQUIRING it — a stale export in a CI
        environment silently shrinking what a module shard runs while the shard still goes
        green. The runner therefore assigns the mode unconditionally instead of defaulting
        off the environment, and both halves are asserted here: the default is `full`, and
        a hostile inherited value does not survive into the module body."""
        for extra_env in (None, {"MODULE_HEAVY_UNIT_MODE": "smoke"}):
            with self.subTest(inherited=extra_env):
                result = self._run("heavy-units", extra_env=extra_env)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("HEAVY-UNITS=full", result.stdout)
                # A full run must carry no bounded-run notice: the inverted-guard mutant
                # (which would stamp every CI shard's log as reduced) is caught only here.
                self.assertNotIn("REQUESTED bounded", result.stdout)

    def test_heavy_units_flag_selects_the_bounded_population(self) -> None:
        """The one channel that CAN select the bounded population is the explicit flag,
        which is what makes the choice visible at the call site that made it.

        The further assertions below pin the runner's own reduced-run accounting, both
        halves of which are otherwise deletion-safe — nothing else in the suite observes
        either.

        The notice is the only bounded-run signal the RUNNER itself contributes: the
        summary line above it cannot carry one, because its shape is machine-consumed. (A
        module that actually bounds a unit reports that separately, in its driver's own
        tally line in the same log.)

        The child-process probe pins `export -n`, and the exported `MODULE_HEAVY_UNIT_MODE`
        below is what makes it discriminate: bash preserves the export attribute only for a
        variable that ARRIVED exported, so without that env the runner's plain assignment
        is unexported anyway and the probe would read `unset` with or without the line."""
        result = self._run_args(
            "--heavy-units",
            "smoke",
            "heavy-units",
            extra_env={"MODULE_HEAVY_UNIT_MODE": "smoke"},
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("HEAVY-UNITS=smoke", result.stdout)
        self.assertIn(
            "Module heavy-units: heavy units REQUESTED bounded (--heavy-units smoke)",
            result.stdout,
        )
        self.assertIn("HEAVY-UNITS-CHILD=unset", result.stdout)

    def test_a_bound_nobody_requested_fails_the_module(self) -> None:
        """Issue #890. Every other guard establishes what the run ASKED for — the runner's
        unconditional `full`, the flag, the shard-dispatcher argv probe. None of them can
        see the last link: a module that hard-codes or defaults its own driver call to
        `smoke` bounds its heaviest unit while the tally, the summary and the notice all
        stay clean, which would silently remove that unit's full population from CI.

        So a `full` run whose module log carries a bound is a contradiction and fails,
        named in the recap. The positive control is the same module under an explicitly
        requested `smoke`, where the identical output is the expected outcome — without it
        this test could pass because the fixture is broken rather than because the guard
        fired."""
        unrequested = self._run("unrequested-bound")
        self.assertEqual(unrequested.returncode, 1, unrequested.stdout + unrequested.stderr)
        self.assertIn(
            "Module unrequested-bound: 1 passed, 1 failed", unrequested.stdout.splitlines()
        )
        self.assertIn(
            "  - module bounded a heavy unit that was not requested "
            "(--heavy-units full was in effect)",
            unrequested.stdout.splitlines(),
        )

        requested = self._run_args("--heavy-units", "smoke", "unrequested-bound")
        self.assertEqual(requested.returncode, 0, requested.stdout + requested.stderr)
        self.assertIn(
            "Module unrequested-bound: 1 passed, 0 failed", requested.stdout.splitlines()
        )

    def test_heavy_units_full_is_an_accepted_explicit_value(self) -> None:
        """`full` is documented in the usage string and is the default, but a mutant that
        narrowed the accepted set to `smoke` alone would make an explicit `--heavy-units
        full` a selector error that nothing noticed."""
        result = self._run_args("--heavy-units", "full", "heavy-units")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("HEAVY-UNITS=full", result.stdout)
        self.assertNotIn("REQUESTED bounded", result.stdout)

    def test_heavy_units_refuses_a_repeated_flag_rather_than_taking_the_last(self) -> None:
        """Last-wins would let a caller that pinned `full` be overridden later in its own
        argv with no diagnostic — the silent reduction the flag's whole shape is meant to
        rule out. The refusal fires whichever order the two values appear in."""
        for args in (
            ("--heavy-units", "full", "--heavy-units", "smoke", "heavy-units"),
            ("--heavy-units", "smoke", "--heavy-units", "full", "heavy-units"),
        ):
            with self.subTest(args=args):
                result = self._run_args(*args)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn(
                    "selector error: --heavy-units given more than once", result.stderr
                )
                self.assertNotIn("HEAVY-UNITS=", result.stdout)

    def test_heavy_units_rejects_an_unrecognized_or_missing_value(self) -> None:
        """A misspelled mode must not fall through to either population: to `full` it
        would hide the defect behind a green run, and to `smoke` it would drop coverage.
        The runner refuses at selection time, before any module is sourced.

        The refusing guard's OWN message is pinned per arm, not merely `selector error`:
        a neighbouring rejection in this runner — an unknown option, a missing module id —
        also exits 2 carrying that same substring, so a bare exit-code-plus-substring
        assertion would stay green against a mutant that deleted the guard under test and
        let one of those do the rejecting."""
        for args, expected in (
            (
                ("--heavy-units", "smoak", "heavy-units"),
                "--heavy-units takes full or smoke, not 'smoak'",
            ),
            (
                ("--heavy-units", "Smoke", "heavy-units"),
                "--heavy-units takes full or smoke, not 'Smoke'",
            ),
            (("--heavy-units",), "--heavy-units requires full or smoke"),
        ):
            with self.subTest(args=args):
                result = self._run_args(*args)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn(f"selector error: {expected}", result.stderr)
                self.assertNotIn("HEAVY-UNITS=", result.stdout)
        # Positive control on the same fixture: the module id and the runner are otherwise
        # valid, so each rejection above is attributable to the flag under test rather than
        # to a precondition the fixture itself fails.
        control = self._run_args("--heavy-units", "smoke", "heavy-units")
        self.assertEqual(control.returncode, 0, control.stdout + control.stderr)
        self.assertIn("HEAVY-UNITS=smoke", control.stdout)

    def test_exact_selection_runs_one_module_and_persists_its_log(self) -> None:
        result = self._run("sample")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.marker.is_file())
        log = self._log_path(result)
        self.assertTrue(log.is_file())
        self.assertIn("sample assertion", log.read_text(encoding="utf-8"))
        self.assertIn("Module sample: 1 passed, 0 failed", result.stdout)
        self.assertIn(f"Log: {log}", result.stdout)

    def test_repository_runner_supports_required_direct_invocation(self) -> None:
        self.assertTrue(os.access(RUNNER_SOURCE, os.X_OK))

        result = subprocess.run(
            [str(RUNNER_SOURCE), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Usage:", result.stderr)

    def test_repository_module_runs_green_through_the_real_runner(self) -> None:
        # The focused path the prompt extensions steer agents to: the REAL
        # runner + REAL registry + REAL module, end to end. This is the only
        # execution proving the runner's environment contract (LIB,
        # RESULTS_FILE, assert_eq, sourced harness) satisfies the module's
        # actual needs — the full suite exercises the module only through the
        # harness boundary, not through this runner.
        environment = os.environ.copy()
        environment.pop("DEVFLOW_TEST_EXPERIMENT_FORCE_FAILURE", None)
        with tempfile.TemporaryDirectory() as log_dir:
            result = subprocess.run(
                [
                    "bash",
                    str(RUNNER_SOURCE),
                    "--log-dir",
                    log_dir,
                    "workflow-flight-recorder",
                ],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(
                result.returncode,
                0,
                result.stdout[-4000:] + result.stderr[-4000:],
            )
            self.assertRegex(
                result.stdout,
                r"Module workflow-flight-recorder: [0-9]+ passed, 0 failed",
            )
            self.assertTrue(list(Path(log_dir).iterdir()))

    def test_relative_registry_and_log_dir_resolve_against_repo_root(self) -> None:
        custom_dir = self.root / "custom"
        custom_dir.mkdir()
        (custom_dir / "reg.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "workflows": {"placeholder": {}},
                    "test_modules": {
                        "sample": {
                            "path": "lib/test/modules/sample.sh",
                            "minimum_assertions": 1,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        # Run from a SUBDIRECTORY cwd so REPO_ROOT-anchoring is distinguishable
        # from cwd-anchoring on every platform (with cwd == repo root the two
        # coincide except behind macOS's /var symlink).
        environment = os.environ.copy()
        environment.pop("DEVFLOW_TEST_EXPERIMENT_FORCE_FAILURE", None)
        environment["SOURCE_MARKER"] = str(self.marker)
        result = subprocess.run(
            [
                "bash",
                str(self.runner),
                "--registry",
                "custom/reg.json",
                "--log-dir",
                "custom-logs",
                "sample",
            ],
            cwd=custom_dir,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        log = self._log_path(result)
        # Compare physical paths: the runner resolves REPO_ROOT with pwd -P,
        # while the sandbox root may sit behind a symlink (macOS /var -> /private/var).
        self.assertEqual(log.parent, (self.root / "custom-logs").resolve())
        self.assertFalse((custom_dir / "custom-logs").exists())
        self.assertTrue(log.is_file())

    def test_missing_harness_fails_closed_before_selection(self) -> None:
        # Guard-class 1 (existence-vs-sourceability): a failed top-level source
        # must stop the runner — bash otherwise continues, and with any floor
        # slack the module would run green while the harness helpers silently
        # never execute.
        (self.test_dir / "module-harness.sh").unlink()

        result = self._run("sample")

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("could not source", result.stderr)
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.root / ".prflow/tmp/test-module-logs").exists())

    def test_harness_missing_contract_function_fails_closed(self) -> None:
        # Outcome check, not just source rc: a harness copy that sources
        # cleanly but no longer defines its contract functions must refuse.
        (self.test_dir / "module-harness.sh").write_text(
            "# stub harness with no contract functions\n", encoding="utf-8"
        )

        result = self._run("sample")

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(
            "did not define devflow_run_focused_python_test", result.stderr
        )
        self.assertFalse(self.marker.exists())

    def test_unknown_selector_fails_before_any_module_body_or_log(self) -> None:
        result = self._run("unknown")

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("selector error: unknown test module 'unknown'", result.stderr)
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.root / ".prflow/tmp/test-module-logs").exists())

    def test_help_and_argument_errors_are_explicit(self) -> None:
        help_result = self._run_args("--help")
        no_module = self._run_args()
        two_modules = self._run_args("sample", "empty")
        unknown_option = self._run_args("--unknown")
        missing_registry_value = self._run_args("--registry")
        missing_log_dir_value = self._run_args("--log-dir")

        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("Usage:", help_result.stderr)
        for result in (
            no_module,
            two_modules,
            unknown_option,
            missing_registry_value,
            missing_log_dir_value,
        ):
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("selector error:", result.stderr)
            self.assertFalse(self.marker.exists())

    def test_registry_and_log_dir_options_control_the_selected_run(self) -> None:
        alternate_registry = self.root / "alternate-registry.json"
        alternate_registry.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "workflows": {"placeholder": {}},
                    "test_modules": {
                        "alternate": {
                            "path": "lib/test/modules/sample.sh",
                            "minimum_assertions": 1,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        alternate_logs = self.root / "alternate-logs"

        result = self._run_args(
            "--registry",
            str(alternate_registry),
            "--log-dir",
            str(alternate_logs),
            "alternate",
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self._log_path(result).parent, alternate_logs)

    def test_invalid_module_id_fails_before_source(self) -> None:
        result = self._run("../sample")

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("invalid module id", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_empty_module_mapping_fails_closed_before_source(self) -> None:
        self._write_registry({})

        result = self._run("sample")

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("test_modules must be a non-empty object", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_malformed_registry_fails_closed_before_source(self) -> None:
        (self.scripts_dir / "workflow-flight-recorder-registry.json").write_text(
            "{not-json", encoding="utf-8"
        )

        result = self._run("sample")

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("registry is unreadable or malformed", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_boolean_schema_version_is_not_accepted_as_integer_one(self) -> None:
        document = {
            "schema_version": True,
            "workflows": {"placeholder": {}},
            "test_modules": {"sample": {"path": "lib/test/modules/sample.sh"}},
        }
        (self.scripts_dir / "workflow-flight-recorder-registry.json").write_text(
            json.dumps(document), encoding="utf-8"
        )

        result = self._run("sample")

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("requires integer schema_version 1", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_invalid_sibling_mapping_invalidates_whole_registry(self) -> None:
        self._write_registry(
            {
                "sample": {"path": "lib/test/modules/sample.sh"},
                "broken": True,
            }
        )

        result = self._run("sample")

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("mapping for 'broken' must be an object", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_missing_assertion_floor_invalidates_registry(self) -> None:
        registry = self.scripts_dir / "workflow-flight-recorder-registry.json"
        registry.write_text(
            '{"schema_version":1,"test_modules":{'
            '"sample":{"path":"lib/test/modules/sample.sh"}}}',
            encoding="utf-8",
        )

        result = self._run("sample")

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(
            "minimum_assertions must be an integer from 1 to 1000000",
            result.stderr,
        )
        self.assertFalse(self.marker.exists())

    def test_nonpositive_and_noninteger_assertion_floors_invalidate_registry(self) -> None:
        for floor in (0, -1, "1", True):
            with self.subTest(floor=floor):
                self._write_registry(
                    {
                        "sample": {
                            "path": "lib/test/modules/sample.sh",
                            "minimum_assertions": floor,
                        }
                    }
                )

                result = self._run("sample")

                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn(
                    "minimum_assertions must be an integer from 1 to 1000000",
                    result.stderr,
                )
                self.assertFalse(self.marker.exists())

    def test_invalid_assertion_floor_policy_values_invalidate_registry(self) -> None:
        for policy in (None, 7, [], {}, "estimated"):
            with self.subTest(policy=policy):
                self._write_registry(
                    {
                        "sample": {
                            "path": "lib/test/modules/sample.sh",
                            "minimum_assertions": 1,
                            "assertion_floor_policy": policy,
                        }
                    }
                )

                result = self._run("sample")

                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn(
                    "assertion_floor_policy must be 'exact' when present",
                    result.stderr,
                )
                self.assertFalse(self.marker.exists())

    def test_nonobject_registry_shapes_fail_before_source(self) -> None:
        registry = self.scripts_dir / "workflow-flight-recorder-registry.json"
        for document in ([], {"schema_version": 1, "test_modules": []}):
            with self.subTest(document=document):
                registry.write_text(json.dumps(document), encoding="utf-8")

                result = self._run("sample")

                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertFalse(self.marker.exists())

    def test_oversized_assertion_floor_invalidates_registry(self) -> None:
        self._write_registry(
            {
                "sample": {
                    "path": "lib/test/modules/sample.sh",
                    "minimum_assertions": 10**100,
                }
            }
        )

        result = self._run("sample")

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("minimum_assertions must be an integer from 1 to 1000000", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_invalid_sibling_module_id_invalidates_whole_registry(self) -> None:
        self._write_registry(
            {
                "sample": {"path": "lib/test/modules/sample.sh"},
                "../broken": {"path": "lib/test/modules/empty.sh"},
            }
        )

        result = self._run("sample")

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("registry contains invalid module id '../broken'", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_duplicate_registry_key_invalidates_whole_registry(self) -> None:
        registry = self.scripts_dir / "workflow-flight-recorder-registry.json"
        registry.write_text(
            '{"schema_version":1,"test_modules":{'
            '"sample":{"path":"lib/test/modules/sample.sh"},'
            '"sample":{"path":"lib/test/modules/empty.sh"}}}',
            encoding="utf-8",
        )

        result = self._run("sample")

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("registry is unreadable or malformed", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_escaping_module_path_is_invalid_and_never_sourced(self) -> None:
        escaped = self.root / "escape.sh"
        escaped.write_text('printf "escaped\\n" > "$SOURCE_MARKER"\n', encoding="utf-8")
        self._write_registry({"sample": {"path": "../escape.sh"}})

        result = self._run("sample")

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("module path must match lib/test/modules/<name>.sh", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_missing_regex_valid_module_path_fails_before_source(self) -> None:
        self._write_registry(
            {"missing": {"path": "lib/test/modules/missing.sh"}}
        )

        result = self._run("missing")

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("module path is missing", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_resolved_directory_is_not_accepted_as_readable_module_file(self) -> None:
        (self.modules_dir / "directory.sh").mkdir()
        self._write_registry(
            {"directory": {"path": "lib/test/modules/directory.sh"}}
        )

        result = self._run("directory")

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("module path is not a readable file", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_unreadable_module_file_is_rejected_before_source(self) -> None:
        module = self.modules_dir / "sample.sh"
        module.chmod(0)
        # Probe actual readability instead of euid, and assert the readability
        # gate's correct-for-THIS-host behavior on every host — never a
        # laundered skip (#456: unittest's skipIf reports OK/rc-0, which run.sh
        # records as a clean pass). A euid-keyed skipIf also AttributeErrors at
        # class-definition time on native Windows, where os.geteuid does not
        # exist. Root and permission-less filesystems (native Windows) can read
        # a chmod-0 file: there the `[ -r ]` gate must pass it straight through
        # to normal sourcing; elsewhere it must reject before sourcing.
        host_can_read_unreadable = os.access(module, os.R_OK)
        try:
            result = self._run("sample")
        finally:
            module.chmod(0o600)

        if host_can_read_unreadable:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(self.marker.is_file())
            self.assertIn("Module sample: 1 passed, 0 failed", result.stdout)
        else:
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("module path is not a readable file", result.stderr)
            self.assertFalse(self.marker.exists())

    def test_symlink_escape_is_rejected_by_canonical_path_confinement(self) -> None:
        escaped = self.root / "escaped.sh"
        escaped.write_text('printf "escaped\\n" > "$SOURCE_MARKER"\n', encoding="utf-8")
        (self.modules_dir / "linked.sh").symlink_to(escaped)
        self._write_registry(
            {"linked": {"path": "lib/test/modules/linked.sh"}}
        )

        result = self._run("linked")

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("escapes lib/test/modules", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_symlink_escape_in_sibling_mapping_invalidates_whole_registry(self) -> None:
        escaped = self.root / "escaped.sh"
        escaped.write_text('printf "escaped\\n" > "$SOURCE_MARKER"\n', encoding="utf-8")
        (self.modules_dir / "linked.sh").symlink_to(escaped)
        self._write_registry(
            {
                "sample": {"path": "lib/test/modules/sample.sh"},
                "linked": {"path": "lib/test/modules/linked.sh"},
            }
        )

        result = self._run("sample")

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("mapping for 'linked'", result.stderr)
        self.assertIn("escapes lib/test/modules", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_module_with_zero_assertions_cannot_report_green(self) -> None:
        result = self._run("empty")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue(self.marker.is_file())
        self.assertIn("Module empty: 0 passed, 1 failed", result.stdout)
        self.assertIn("module executed zero assertions", result.stdout)

    def test_nonzero_module_process_gets_a_failure_recap(self) -> None:
        result = self._run("crash")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Module crash: 0 passed, 2 failed", result.stdout)
        self.assertIn("module process exited with status 7", result.stdout)
        self.assertIn("module executed zero assertions", result.stdout)

    def test_invalid_tally_record_is_nonzero_and_recapped(self) -> None:
        result = self._run("invalid-tally")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Module invalid-tally: 1 passed, 1 failed", result.stdout)
        self.assertIn("assertion tally contained 1 invalid record(s)", result.stdout)

    def test_selected_module_below_assertion_floor_cannot_report_green(self) -> None:
        self._write_registry(
            {
                "sample": {
                    "path": "lib/test/modules/sample.sh",
                    "minimum_assertions": 2,
                }
            }
        )

        result = self._run("sample")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Module sample: 1 passed, 1 failed", result.stdout)
        self.assertIn("module executed 1 assertions; minimum is 2", result.stdout)

    def test_rejected_relative_boundary_scratch_is_removed(self) -> None:
        relative_tmp = self.root / "relative-tmp"
        relative_tmp.mkdir()

        result = self._run("sample", extra_env={"TMPDIR": "relative-tmp"})

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(list(relative_tmp.glob("devflow-module-scratch.*")), [])

    def test_preexisting_well_shaped_boundary_scratch_is_never_claimed(self) -> None:
        controlled_tmp = self.root / "controlled-tmp"
        controlled_tmp.mkdir()
        victim = controlled_tmp / "devflow-module-scratch.ABC123"
        victim.mkdir()
        sentinel = victim / "sentinel"
        sentinel.write_text("keep\n", encoding="utf-8")
        fake_bin = self.root / "fake-module-scratch-bin"
        fake_bin.mkdir()
        real_mktemp = shutil.which("mktemp")
        self.assertIsNotNone(real_mktemp)
        fake_mktemp = fake_bin / "mktemp"
        fake_mktemp.write_text(
            "#!/usr/bin/env bash\n"
            'if [ "${1:-}" = "-d" ] && '
            'case "${2:-}" in *devflow-module-scratch.*) true ;; '
            "*) false ;; esac; then\n"
            f'  printf "%s\\n" "{victim}"\n'
            "  exit 0\n"
            "fi\n"
            f'exec "{real_mktemp}" "$@"\n',
            encoding="utf-8",
        )
        fake_mktemp.chmod(0o755)

        result = self._run(
            "sample",
            extra_env={
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "TMPDIR": str(controlled_tmp),
            },
        )

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("could not allocate the module scratch root", result.stderr)
        self.assertTrue(sentinel.is_file(), result.stdout + result.stderr)

    def test_invalid_preexisting_boundary_directory_is_not_discarded(self) -> None:
        controlled_tmp = self.root / "controlled-tmp"
        controlled_tmp.mkdir()
        victim = controlled_tmp / "caller-empty-directory"
        victim.mkdir()
        fake_bin = self.root / "fake-invalid-scratch-bin"
        fake_bin.mkdir()
        real_mktemp = shutil.which("mktemp")
        self.assertIsNotNone(real_mktemp)
        fake_mktemp = fake_bin / "mktemp"
        fake_mktemp.write_text(
            "#!/usr/bin/env bash\n"
            'if [ "${1:-}" = "-d" ] && '
            'case "${2:-}" in *devflow-module-scratch.*) true ;; '
            "*) false ;; esac; then\n"
            f'  printf "%s\\n" "{victim}"\n'
            "  exit 0\n"
            "fi\n"
            f'exec "{real_mktemp}" "$@"\n',
            encoding="utf-8",
        )
        fake_mktemp.chmod(0o755)

        result = self._run(
            "sample",
            extra_env={
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "TMPDIR": str(controlled_tmp),
            },
        )

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertTrue(victim.is_dir(), result.stdout + result.stderr)

    def test_focused_scratch_cleanup_failure_is_not_a_module_exit(self) -> None:
        fake_bin = self.root / "fake-rm-bin"
        fake_bin.mkdir()
        fake_rm = fake_bin / "rm"
        real_rm = shutil.which("rm")
        self.assertIsNotNone(real_rm)
        fake_rm.write_text(
            "#!/usr/bin/env bash\n"
            'if [ "${1:-}" = "-rf" ] && '
            'case "${2:-}" in *devflow-module-scratch.*) true ;; *) false ;; esac; '
            "then exit 1; fi\n"
            f'exec "{real_rm}" "$@"\n',
            encoding="utf-8",
        )
        fake_rm.chmod(0o755)

        result = self._run(
            "sample",
            extra_env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Module sample: 1 passed, 1 failed", result.stdout)
        self.assertIn("module scratch cleanup failed", result.stdout)
        self.assertNotIn("module process exited with status", result.stdout)

    def _run_with_fake_directory_mktemp(
        self, fake_directory_result: str
    ) -> subprocess.CompletedProcess[str]:
        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir(exist_ok=True)
        controlled_tmp = self.root / "fake-tmp"
        controlled_tmp.mkdir(exist_ok=True)
        fake_mktemp = fake_bin / "mktemp"
        real_mktemp = shutil.which("mktemp")
        self.assertIsNotNone(real_mktemp)
        fake_mktemp.write_text(
            "#!/usr/bin/env bash\n"
            'if [ "${1:-}" = "-d" ] && '
            'case "${2:-}" in *devflow-wfr.*) true ;; *) false ;; esac; then '
            + fake_directory_result
            + "; fi\n"
            f'exec "{real_mktemp}" "$@"\n',
            encoding="utf-8",
        )
        fake_mktemp.chmod(0o755)

        return self._run(
            "workflow-flight-recorder",
            extra_env={
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "TMPDIR": str(controlled_tmp),
            },
        )

    def test_module_workspace_allocation_failure_is_explicit(self) -> None:
        result = self._run_with_fake_directory_mktemp("exit 9")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("could not allocate workflow-flight-recorder workspace", result.stdout)
        self.assertNotIn("mkdir: /nested", result.stdout)

    def test_module_workspace_rejects_unsafe_successful_mktemp_output(self) -> None:
        unsafe_results = (
            "printf '/\\n'; exit 0",
            ('candidate="${2%XXXXXX}fixture"; mkdir -p "$candidate"; '
            'printf "%s/..\\n" "$candidate"; exit 0'),
            ('target="${2%XXXXXX}target"; link="${2%XXXXXX}link"; '
            'mkdir -p "$target"; ln -s "$target" "$link"; '
            'printf "%s\\n" "$link"; exit 0'),
        )
        for fake_result in unsafe_results:
            with self.subTest(fake_result=fake_result):
                result = self._run_with_fake_directory_mktemp(fake_result)

                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(
                    "could not allocate workflow-flight-recorder workspace",
                    result.stdout,
                )
                self.assertNotIn("mkdir: /nested", result.stdout)

    def test_abnormal_module_exit_removes_allocated_workspace(self) -> None:
        module = self.modules_dir / "workflow-flight-recorder.sh"
        module_text = module.read_text(encoding="utf-8")
        post_allocation = 'IFR_PROJECTS="$IFR_ROOT/native-projects"\n'
        self.assertEqual(module_text.count(post_allocation), 1)
        module.write_text(
            module_text.replace(post_allocation, "exit 97\n", 1),
            encoding="utf-8",
        )
        controlled_tmp = self.root / "abnormal-exit-tmp"
        controlled_tmp.mkdir()

        result = self._run(
            "workflow-flight-recorder",
            extra_env={"TMPDIR": str(controlled_tmp)},
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("module process exited with status 97", result.stdout)
        self.assertEqual(list(controlled_tmp.glob("devflow-wfr.*")), [])

    def test_controlled_failure_is_nonzero_and_recapped_in_the_persisted_log(self) -> None:
        result = self._run(
            "sample", extra_env={"DEVFLOW_TEST_EXPERIMENT_FORCE_FAILURE": "1"}
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Module sample: 1 passed, 1 failed", result.stdout)
        self.assertIn("controlled experimental failure injection", result.stdout)
        self.assertIn("expected: disabled", result.stdout)
        self.assertIn("actual:   enabled", result.stdout)
        log = self._log_path(result)
        self.assertIn("Failure recap:", log.read_text(encoding="utf-8"))

    def test_concurrent_runs_use_distinct_complete_logs(self) -> None:
        environment = os.environ.copy()
        environment.pop("DEVFLOW_TEST_EXPERIMENT_FORCE_FAILURE", None)
        environment["SOURCE_MARKER"] = str(self.marker)
        command = ["bash", str(self.runner), "sample"]

        first = subprocess.Popen(
            command,
            cwd=self.root,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        second = subprocess.Popen(
            command,
            cwd=self.root,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        first_stdout, first_stderr = first.communicate()
        second_stdout, second_stderr = second.communicate()
        first_result = subprocess.CompletedProcess(command, first.returncode, first_stdout, first_stderr)
        second_result = subprocess.CompletedProcess(command, second.returncode, second_stdout, second_stderr)

        self.assertEqual(first_result.returncode, 0, first_stdout + first_stderr)
        self.assertEqual(second_result.returncode, 0, second_stdout + second_stderr)
        first_log = self._log_path(first_result)
        second_log = self._log_path(second_result)
        self.assertNotEqual(first_log, second_log)
        for log in (first_log, second_log):
            self.assertTrue(log.is_file())
            self.assertIn("Module sample: 1 passed, 0 failed", log.read_text(encoding="utf-8"))

    def test_selector_diagnostic_temp_is_removed_before_module_execution(self) -> None:
        controlled_tmp = self.root / "tmp"
        controlled_tmp.mkdir()
        ready = self.root / "module-ready"
        environment = os.environ.copy()
        environment.pop("DEVFLOW_TEST_EXPERIMENT_FORCE_FAILURE", None)
        environment["SOURCE_MARKER"] = str(self.marker)
        environment["READY_MARKER"] = str(ready)
        environment["TMPDIR"] = str(controlled_tmp)
        process = subprocess.Popen(
            ["bash", str(self.runner), "blocking"],
            cwd=self.root,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            deadline = time.monotonic() + 3
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(ready.exists(), "blocking module did not start")
            entries = list(controlled_tmp.iterdir())
            # results + details + skips + credits + scratch (issue #887 added the skip
            # tally and skip-credit record; the selector diagnostic is already removed).
            self.assertEqual(len(entries), 5)
            self.assertFalse(
                any(path.name.startswith("devflow-module-selector.") for path in entries)
            )
            self.assertEqual(
                sum(
                    path.name.startswith("devflow-module-scratch.")
                    for path in entries
                ),
                1,
            )
        finally:
            # Parent-only TERM is forwarded to the supervised module and must be
            # bounded; retain SIGKILL only as a test-harness leak backstop.
            process.terminate()
            try:
                process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()

    def test_forced_failure_injection_fires_only_when_the_flag_is_present(self) -> None:
        # RED half: the flag deliberately passed through fires the injection.
        # (extra_env is applied after the helper's scrub, so this reaches bash.)
        forced = self._run(
            "sample", extra_env={"DEVFLOW_TEST_EXPERIMENT_FORCE_FAILURE": "1"}
        )
        self.assertNotEqual(forced.returncode, 0, forced.stdout + forced.stderr)
        self.assertIn(
            "controlled experimental failure injection", forced.stdout
        )

        # GREEN half / no-fire control: without the flag the same module is clean.
        unforced = self._run("sample")
        self.assertEqual(unforced.returncode, 0, unforced.stdout + unforced.stderr)
        self.assertIn("Module sample: 1 passed, 0 failed", unforced.stdout)
        self.assertNotIn(
            "controlled experimental failure injection", unforced.stdout
        )

    def test_inherited_launch_hook_is_scrubbed_from_normal_runs(self) -> None:
        inherited_launch = self.root / "inherited-launch-window"
        Path(f"{inherited_launch}.release").touch()

        with mock.patch.dict(
            os.environ,
            {"DEVFLOW_TEST_LAUNCH_WINDOW_FILE": str(inherited_launch)},
        ):
            result = self._run("sample")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(inherited_launch.exists())

    def test_repository_registry_maps_the_extracted_recorder_module(self) -> None:
        registry = json.loads(
            (ROOT / "scripts/workflow-flight-recorder-registry.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertIn("test_modules", registry)
        self.assertEqual(
            registry["test_modules"]["workflow-flight-recorder"]["path"],
            "lib/test/modules/workflow-flight-recorder.sh",
        )
        self.assertEqual(
            registry["test_modules"]["workflow-flight-recorder"][
                "minimum_assertions"
            ],
            68,
        )
        module = ROOT / "lib/test/modules/workflow-flight-recorder.sh"
        self.assertTrue(module.is_file())
        run_text = (ROOT / "lib/test/run.sh").read_text(encoding="utf-8")
        self.assertIn(
            'devflow_run_full_suite_module "$LIB/test/modules/workflow-flight-recorder.sh"',
            run_text,
        )
        floor_match = re.search(
            r'"workflow-flight-recorder" ([0-9]+); then', run_text
        )
        self.assertIsNotNone(floor_match)
        self.assertEqual(
            int(floor_match.group(1)),
            registry["test_modules"]["workflow-flight-recorder"][
                "minimum_assertions"
            ],
        )
        self.assertIn('FAIL="$(devflow_fold_module_failures "$FAIL")"', run_text)
        # The pool triple moved out of run.sh when the pooled Python suites gained their
        # own CI shard: membership now has ONE definition, in module-harness.sh, shared
        # by run.sh and lib/test/run-python-pool.sh. What this claim has always been
        # about is unchanged — these integration tests are driven from OUTSIDE the module
        # whose registration and source boundary they pin, so deleting that boundary
        # cannot delete their execution.
        harness_text = (ROOT / "lib/test/module-harness.sh").read_text(encoding="utf-8")
        self.assertIn(POOL_TRIPLE_LITERAL, harness_text)
        self.assertNotIn('IFR_MANIFEST="$LIB/../scripts/capture-workflow-manifest.py"', run_text)
        module_text = module.read_text(encoding="utf-8")
        self.assertTrue(
            module_text.startswith(
                "# SPDX-FileCopyrightText: 2026 Daniel Radman\n"
                "# SPDX-License-Identifier: MIT\n"
            )
        )

        self.assertNotIn(POOL_TRIPLE_LITERAL, module_text)
        self.assertIn(
            'IFR_MANIFEST="$LIB/../scripts/capture-workflow-manifest.py"',
            module_text,
        )
        self.assertEqual(module_text.count("devflow_run_focused_python_test"), 2)
        ci_text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn("lib/test/modules/workflow-flight-recorder.sh", ci_text)
        self.assertIn(
            "The registry and this full-suite call share the same lower-bound contract",
            run_text,
        )
        overview_text = (ROOT / "docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "a failure recap whenever an assertion or module boundary fails",
            overview_text,
        )
        self.assertIn("trap _suite_cleanup EXIT", run_text)
        for temp_file in (
            "RESULTS_FILE",
            "MODULE_FAILURES_FILE",
            "SKIPS_FILE",
            "IMPL_SKILL_BUNDLE",
            "REVIEW_BUNDLE",
            "MAXI_BUNDLE",
        ):
            self.assertIn(f'_suite_tmp_file "${temp_file}"', run_text)
        for temp_dir in ("E484", "E363", "S363", "D363"):
            self.assertIn(f'_suite_tmp_dir "${temp_dir}"', run_text)
        # Presence of the registry trap is not enough: bash keeps only the LAST
        # `trap … EXIT` handler, so a later installer silently REPLACES
        # `_suite_cleanup` and un-covers every registration made after it — the
        # exact clobber the registry's own header comment bans. Assert the
        # registry trap is the ONLY EXIT-trap installer in run.sh: strip each
        # line before matching (an INDENTED installer inside an if/for body
        # still replaces the global handler at run time) and exclude comments;
        # quoted fixture literals do not start a stripped line with `trap `.
        exit_traps = [
            stripped
            for stripped in (line.strip() for line in run_text.splitlines())
            if not stripped.startswith("#")
            and re.match(r"^trap\s+\S.*\sEXIT$", stripped)
        ]
        self.assertEqual(exit_traps, ["trap _suite_cleanup EXIT"])
        # Behavioral proof the registry actually cleans: register a real temp
        # file+dir in a bash micro-harness using run.sh's own function bodies,
        # exit, and assert both are gone (textual presence of the trap cannot
        # prove the cleanup path executes).
        harness = (
            "_SUITE_TMP_FILES=(); _SUITE_TMP_DIRS=()\n"
            '_suite_tmp_file() { _SUITE_TMP_FILES+=("$1"); }\n'
            '_suite_tmp_dir()  { _SUITE_TMP_DIRS+=("$1"); }\n'
            "_suite_cleanup() {\n"
            '  for _f in "${_SUITE_TMP_FILES[@]}"; do [ -n "$_f" ] && rm -f "$_f"; done\n'
            '  for _d in "${_SUITE_TMP_DIRS[@]}"; do [ -n "$_d" ] && rm -rf "$_d"; done\n'
            "}\n"
            "trap _suite_cleanup EXIT\n"
            'f="$(mktemp)"; d="$(mktemp -d)"\n'
            '_suite_tmp_file "$f"; _suite_tmp_dir "$d"\n'
            'printf "%s\\n%s\\n" "$f" "$d"\n'
        )
        proc = subprocess.run(
            ["bash", "-c", harness],
            capture_output=True,
            text=True,
            check=True,
        )
        registered_file, registered_dir = proc.stdout.splitlines()[:2]
        self.assertFalse(os.path.exists(registered_file))
        self.assertFalse(os.path.exists(registered_dir))

    def test_repository_declares_the_exact_floor_population(self) -> None:
        registry = json.loads(
            (ROOT / "scripts/workflow-flight-recorder-registry.json").read_text(
                encoding="utf-8"
            )
        )
        exact_modules = sorted(
            module_id
            for module_id, mapping in registry["test_modules"].items()
            if mapping.get("assertion_floor_policy") == "exact"
        )

        # Naming the population (rather than counting it) makes an accidental add or
        # removal of an exact-policy module a diff a reviewer reads, not a bare number
        # that two unrelated changes could keep at the same total.
        self.assertEqual(
            exact_modules,
            [
                "capability-profiles",
                "create-issue-contract",
                "efficiency-trace-telemetry",
                "experiment-records",
                "harness-python-guards",
                "implement-contract",
                "installer-wiring",
                "issue-audit-state",
                "prompt-extension-reader",
                "review-and-fix-contract",
                "review-contract",
                "review-dirty-tree",
                "review-evidence-gate",
                "review-stall-backstop",
                "review-trigger-helpers",
                "workpad-cli",
            ],
        )

    def test_every_on_disk_module_is_fully_wired(self) -> None:
        # Issue #757: REVERSE orphan check. Enumerate the modules that exist ON DISK
        # (never the registry) and demand each be wired across ALL FOUR couplings —
        # registered, called from run.sh's full-suite boundary at a floor matching the
        # registry, listed in ci.yml's explicit shellcheck set, and paired with a
        # provenance inventory — plus the module contract. This is fail-closed by
        # construction: a new module file cannot slip in registered-but-uncalled, or
        # (the gap the forward registry-driven check could never catch) present on disk
        # but absent from the registry entirely. #746 was the PR that demonstrated four
        # modules could be extracted at once while the per-module coupling tests were a
        # convention followed by accident; this loop makes the convention mechanical, so
        # the authoring checklist needs no cross-check item and no future module can be
        # forgotten. It subsumes the former forward registry→run.sh floor cross-check and
        # the per-module review-and-fix / create-issue reconciliation tests.
        registry = json.loads(
            (ROOT / "scripts/workflow-flight-recorder-registry.json").read_text(encoding="utf-8")
        )
        modules = registry["test_modules"]
        self.assertIsInstance(modules, dict)
        run_text = (ROOT / "lib/test/run.sh").read_text(encoding="utf-8")
        ci_text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        on_disk = sorted((ROOT / "lib/test/modules").glob("*.sh"))
        self.assertTrue(on_disk, "no module files found on disk")
        for module_path in on_disk:
            module_id = module_path.stem
            with self.subTest(module=module_id):
                expected_path = f"lib/test/modules/{module_id}.sh"
                # (1) registry entry whose path matches
                self.assertIn(
                    module_id,
                    modules,
                    f"{expected_path} exists on disk but is unregistered in "
                    "scripts/workflow-flight-recorder-registry.json",
                )
                mapping = modules[module_id]
                self.assertEqual(mapping["path"], expected_path)
                floor = mapping["minimum_assertions"]
                self.assertIsInstance(floor, int)
                self.assertGreater(floor, 0)
                # (2) run.sh full-suite call + coupled floor literal == registry floor
                self.assertIn(
                    f'devflow_run_full_suite_module "$LIB/test/modules/{module_id}.sh"',
                    run_text,
                    f"{module_id} is on disk but never invoked from run.sh's full-suite boundary",
                )
                floor_match = re.search(rf'"{re.escape(module_id)}" ([0-9]+); then', run_text)
                self.assertIsNotNone(floor_match, f"no run.sh call-site floor for {module_id}")
                self.assertEqual(int(floor_match.group(1)), floor)
                # (3) ci.yml explicit shellcheck listing (lib/test/ is otherwise excluded)
                self.assertIn(
                    expected_path,
                    ci_text,
                    f"{expected_path} is not in ci.yml's explicit shellcheck list",
                )
                # (4) provenance inventory pairing
                self.assertTrue(
                    (ROOT / f"lib/test/modules/{module_id}.inventory.md").is_file(),
                    f"{module_id} has no lib/test/modules/{module_id}.inventory.md",
                )
                # Module contract header, and it never self-invokes the boundary.
                module_text = module_path.read_text(encoding="utf-8")
                self.assertTrue(
                    module_text.startswith(
                        "# SPDX-FileCopyrightText: 2026 Daniel Radman\n"
                        "# SPDX-License-Identifier: MIT\n"
                    )
                )
                self.assertIn("Contract: the caller sets LIB and RESULTS_FILE", module_text)
                self.assertNotIn("devflow_run_full_suite_module", module_text)
                # No monolith-only helper reference, and no self-skip (module contract).
                # Comment-aware: a helper name inside a `#` comment is prose about the
                # helper, never an invocation, so only code lines are scanned.
                module_code = "\n".join(
                    line
                    for line in module_text.split("\n")
                    if not line.lstrip().startswith("#")
                )
                helper_hits = sorted(
                    {match.group(1) for match in MONOLITH_HELPER_RE.finditer(module_code)}
                )
                self.assertEqual(
                    helper_hits,
                    [],
                    f"{module_id} references monolith-only helper(s): {helper_hits}",
                )
                self.assertIsNone(
                    MODULE_SKIP_CALL_RE.search(module_code),
                    f"{module_id} calls skip directly; a module may only declare a "
                    "host-capability condition through module_host_capability_skip",
                )

    def test_the_harness_clears_an_inherited_devflow_gh_before_a_module_body(self) -> None:
        """Issue #695 AC: a focused run started with DEVFLOW_GH exported must produce the
        same assertion outcomes as one started with it unset.

        This is the AC's own observable — a leaked override outranks every fixture-local
        PATH stub with NO error, so an unguarded regression here fails silently. Assert
        the module body observes it empty AND that the clear is disclosed on stderr."""
        environment = os.environ.copy()
        environment.pop("DEVFLOW_TEST_EXPERIMENT_FORCE_FAILURE", None)
        environment["DEVFLOW_GH"] = "/nonexistent/leaked-sentinel"
        probe = Path(self.temporary_directory.name) / "gh-clear-probe.sh"
        probe.write_text(
            '# shellcheck shell=bash\n'
            'assert_eq "inherited DEVFLOW_GH is cleared before the module body"'
            ' "" "${DEVFLOW_GH:-}"\n',
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                "bash",
                "-c",
                ('set -u; RESULTS_FILE="$1"; DETAILS_FILE="$2";'
                ' assert_eq() { if [ "$2" = "$3" ]; then printf "PASS\\n" >> "$RESULTS_FILE";'
                ' else printf "FAIL %s want=[%s] got=[%s]\\n" "$1" "$2" "$3" >> "$RESULTS_FILE"; fi; };'
                ' . "$3"; . "$4"'),
                "bash",
                str(Path(self.temporary_directory.name) / "tally"),
                str(Path(self.temporary_directory.name) / "details"),
                str(ROOT / "lib/test/module-harness.sh"),
                str(probe),
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        tally = (Path(self.temporary_directory.name) / "tally").read_text(encoding="utf-8")
        self.assertEqual(
            tally.strip(),
            "PASS",
            f"module body saw a leaked DEVFLOW_GH: {tally!r}\n{result.stderr[-2000:]}",
        )
        self.assertIn("clearing inherited DEVFLOW_GH", result.stderr)

    def test_promoted_fixture_helpers_are_defined_only_in_the_module_harness(self) -> None:
        # Issue #695: mint_blk / probe_tmp / probe_assert — joined later by git_sandbox —
        # were PROMOTED out of the monolith, not copied; uses stay in lib/test/run.sh
        # (git_sandbox's are its retained #161 AC3 block), so a second
        # copy would be an uncoupled mirror of load-bearing logic (an exact use count is
        # deliberately not stated here: it rots on the next edit to either file). Each
        # must have exactly one definition tree-wide, in
        # lib/test/module-harness.sh, which lib/test/run.sh obtains by sourcing.
        harness_text = (ROOT / "lib/test/module-harness.sh").read_text(encoding="utf-8")
        shell_sources = {
            str(path.relative_to(ROOT)): path.read_text(encoding="utf-8", errors="replace")
            for path in sorted(ROOT.glob("lib/**/*.sh")) + sorted(ROOT.glob("scripts/**/*.sh"))  # tree-walk-ok: both patterns are confined to lib/ and scripts/, which no worktree lives under
        }
        for helper in PROMOTED_HARNESS_HELPERS:
            with self.subTest(helper=helper):
                definition = re.compile(rf"^[ \t]*{helper}\(\)", re.MULTILINE)
                self.assertIsNotNone(
                    definition.search(harness_text),
                    f"{helper} is not defined in lib/test/module-harness.sh",
                )
                definers = [
                    relative_path
                    for relative_path, text in shell_sources.items()
                    if definition.search(text)
                ]
                self.assertEqual(
                    definers,
                    ["lib/test/module-harness.sh"],
                    f"{helper} must be defined exactly once, in the harness; found: {definers}",
                )
        self.assertIn(
            '. "$LIB/test/module-harness.sh"',
            (ROOT / "lib/test/run.sh").read_text(encoding="utf-8"),
            "lib/test/run.sh must obtain the promoted helpers by sourcing the harness",
        )

    def test_capability_profiles_module_references_no_monolith_helper(self) -> None:
        # Issue #591: the seed module uses only assert_eq plus its own private helpers
        # (_cap_fail, _cap_noncomment_hits) — a monolith run.sh helper reference would
        # not exist when the runner or the full-suite boundary source it.
        text = CAPABILITY_PROFILES_MODULE_SOURCE.read_text(encoding="utf-8")
        hits = sorted({match.group(1) for match in MONOLITH_HELPER_RE.finditer(text)})
        self.assertEqual(hits, [], f"capability-profiles module references monolith helper(s): {hits}")

    def test_exact_floor_modules_run_green_through_the_real_runner(self) -> None:
        """Every exact-policy module's run.sh coupling is checked, and each is executed.

        The registry flag is the sole population source for the STATIC half: adding
        another exact module automatically puts its `run.sh` call site and floor literal
        under check here. The EXECUTION half runs that same population, reduced to
        REAL_EXECUTION_MODULES only under the parallel coordinator (see
        `_under_parallel_coordinator`), so CI's dedicated python-pool runner and a direct
        local run keep full equality enforcement over all exact-policy modules, while the
        coordinator's contended shared host keeps the reduced fan-out. Each measured
        tally must equal both the live registry
        floor and its coupled `run.sh` call-site operand. Equality (not `>=`) detects
        assertion loss instead of accepting a stale low watermark.

        HOST ASSUMPTION: equality means the module must execute every assertion, so a
        host that trips a conditional arm inside a module (running as root, where the
        `chmod 000` denial arms do not deny; or a missing PyYAML) yields a lower tally
        and fails here. That is the honest signal for a FOCUSED run, which may not
        self-skip at all: since issue #838 the `chmod 000` arms report through
        `module_host_capability_skip`, so on such a host a focused run dies at the first
        arm with the runner's "modules may not self-skip" message instead of an opaque
        count mismatch. The FULL-SUITE boundary is where those arms are accounted for —
        it folds the declared host-capability skip into the suite tally and credits the
        arm's declared assertions against the floor (see
        HostCapabilitySkipChannelTests), so this equality is a statement about the
        focused runner, not about every tier. The harness guard module retains its
        bounded heavy-unit mode here so the pooled suite does not duplicate the full
        Python corpus already owned by the modules shard.

        WHY THE MODULE SUBPROCESSES RUN CONCURRENTLY (issue #1181). Attribution of the
        `python-pool` shard (a past-time snapshot measured 2026-08 on the cloud implement
        tier, 4 vCPU — motivating figures, not a maintained contract, so nothing enforces
        them) put this single test at ~266s — 60% of test_module_runner.py's whole ~448s
        wall-clock, and the shard's wall-clock is the wall-clock of test_module_runner.py,
        its slower member. The cost is not one hotspot but ~5 subprocess-heavy modules run
        one after another (installer-wiring 67s, issue-audit-state 55s,
        efficiency-trace-telemetry 51s, create-issue-contract 32s, harness-python-guards
        26s, the rest <=15s). Each module runs the real focused runner in its OWN process
        with its OWN log dir and its OWN copied environment, and the heavy modules
        allocate their own mktemp scratch/sandbox roots and only read the shared tree, so
        there is no shared mutable state across iterations
        (test_concurrent_runs_use_distinct_complete_logs pins the narrower guarantee that
        the runner keeps its logs distinct across concurrent runs) — so the loop is
        embarrassingly parallel.
        Running the subprocess fan-out through a bounded thread pool collapses the wall
        of this test from the SUM of the module runtimes to roughly the longest single
        module, without dropping, weakening, or reordering a single assertion: the static
        run.sh call-site checks run first, serially, in the main thread, and every
        per-module verdict below is asserted in the main thread from the collected
        result, still inside `self.subTest(module=...)`. `subprocess.run` and
        `tempfile.TemporaryDirectory` release the GIL / do their own I/O, so a thread
        pool (not a process pool) is the right primitive; the worker performs no unittest
        assertion, only the process launch and the log-dir observation, so the pool never
        touches the non-thread-safe TestResult."""
        registry = json.loads(
            (ROOT / "scripts/workflow-flight-recorder-registry.json").read_text(
                encoding="utf-8"
            )
        )
        run_text = (ROOT / "lib/test/run.sh").read_text(encoding="utf-8")
        exact_modules = {
            module_id: mapping
            for module_id, mapping in registry["test_modules"].items()
            if mapping.get("assertion_floor_policy") == "exact"
        }
        self.assertTrue(exact_modules)
        reduced = _under_parallel_coordinator()

        # Static run.sh call-site checks first, serially, before any subprocess is
        # launched: a floor literal that drifted from the registry must fail here
        # regardless of how the module executions are scheduled. The surviving
        # (module_id, floor) pairs are the fan-out work list.
        work: list[tuple[str, int]] = []
        for module_id, mapping in exact_modules.items():
            # Bind floor OUTSIDE the subTest so the work.append below can never see an
            # unbound name: a subTest swallows an exception in its body, so binding floor
            # inside it would let a (registry-invalid) missing minimum_assertions leave
            # floor unbound and NameError the append with no module attribution.
            floor = mapping["minimum_assertions"]
            with self.subTest(module=module_id, phase="run.sh call-site"):
                self.assertIn(
                    f'devflow_run_full_suite_module "$LIB/test/modules/{module_id}.sh"',
                    run_text,
                )
                floor_match = re.search(rf'"{module_id}" ([0-9]+); then', run_text)
                self.assertIsNotNone(
                    floor_match, f"no run.sh call-site floor literal for {module_id}"
                )
                self.assertEqual(int(floor_match.group(1)), floor)
            if not reduced or module_id in REAL_EXECUTION_MODULES:
                work.append((module_id, floor))

        # Every exact-policy module named above had its static run.sh coupling checked.
        # The executed population is the whole exact-policy set, reduced to
        # REAL_EXECUTION_MODULES only under the parallel coordinator; asserting it
        # against the regime's expected population makes a renamed id or an emptied set
        # a loud failure instead of a silently empty fan-out, in BOTH regimes.
        expected_execution = (
            sorted(REAL_EXECUTION_MODULES) if reduced else sorted(exact_modules)
        )
        self.assertEqual(
            sorted(module_id for module_id, _ in work),
            expected_execution,
            "the executed exact-floor population does not match this regime's expected set",
        )

        class _RunResult(NamedTuple):
            module_id: str
            floor: int
            returncode: int
            stdout: str
            stderr: str
            log_had_files: bool

        def _run_one(item: tuple[str, int]) -> _RunResult:
            module_id, floor = item
            environment = os.environ.copy()
            environment.pop("DEVFLOW_TEST_EXPERIMENT_FORCE_FAILURE", None)
            if temp_root := environment.get("TMPDIR"):
                environment["TMPDIR"] = temp_root.rstrip("/") or "/"
            with tempfile.TemporaryDirectory() as log_dir:
                runner_argv = [
                    "bash",
                    str(RUNNER_SOURCE),
                    "--log-dir",
                    log_dir,
                ]
                if module_id == "harness-python-guards":
                    runner_argv.extend(("--heavy-units", "smoke"))
                runner_argv.append(module_id)
                result = subprocess.run(
                    runner_argv,
                    cwd=ROOT,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                # Observe the log dir INSIDE the context manager, before the temp dir is
                # torn down, and return the boolean — the assertion lives in the main
                # thread below.
                log_had_files = bool(list(Path(log_dir).iterdir()))
            return _RunResult(
                module_id=module_id,
                floor=floor,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                log_had_files=log_had_files,
            )

        # Bound the fan-out. Under the parallel coordinator `run-parallel.sh` the
        # python-pool shard is launched holding POOL_RESERVATION slots, which it exports
        # as DEVFLOW_POOL_WIDTH; honouring it keeps the real process count inside the
        # budget the coordinator scheduled against, instead of oversubscribing the host
        # alongside the sibling shards. Outside the coordinator (CI runs python-pool on
        # its own dedicated runner) there is no such contention, so the host CPU count
        # stays the bound. pool.map preserves input order, so results iterate
        # deterministically.
        max_workers = min(len(work), _pool_width())
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            results = list(pool.map(_run_one, work))

        for module_id, floor, returncode, stdout, stderr, log_had_files in results:
            with self.subTest(module=module_id):
                self.assertEqual(
                    returncode,
                    0,
                    stdout[-4000:] + stderr[-4000:],
                )
                # Membership in the LINE list, not a substring of the whole stdout —
                # a bare substring match would also accept a summary line that grew a
                # trailing clause (a skip tally, say; a skipped assertion is never a
                # clean pass, issue #456), so this pins the runner's exact format.
                self.assertIn(
                    f"Module {module_id}: {floor} passed, 0 failed",
                    stdout.splitlines(),
                )
                if module_id == "harness-python-guards":
                    self.assertRegex(
                        stdout,
                        r"test_pin_corpus_lint\.py: .*BOUNDED smoke subset "
                        r"— the full population did NOT run",
                    )
                self.assertTrue(log_had_files)

    def test_create_issue_self_allocated_root_rejects_unsafe_mktemp_output(self) -> None:
        source = CREATE_ISSUE_MODULE_SOURCE.read_text(encoding="utf-8")
        boundary = 'CI_IMPL_BUNDLE="$_ci_tmp_root/implement-skill-bundle.md"'
        self.assertEqual(source.count(boundary), 1)
        short_module = self.root / "short-create-issue.sh"
        short_module.write_text(
            source.split(boundary, 1)[0]
            + "_ci_cleanup\n"
            + "trap - EXIT HUP INT TERM\n"
            + "return 0\n",
            encoding="utf-8",
        )
        victim = self.root / "devflow-create-issue-contract.ABC123"
        victim.mkdir()
        sentinel = victim / "sentinel"
        sentinel.write_text("keep\n", encoding="utf-8")
        fake_bin = self.root / "unsafe-mktemp-bin"
        fake_bin.mkdir()
        fake_mktemp = fake_bin / "mktemp"
        fake_mktemp.write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s\\n" "{victim}"\n',
            encoding="utf-8",
        )
        fake_mktemp.chmod(0o755)
        driver = self.root / "unsafe-create-issue-driver.sh"
        driver.write_text(
            "#!/usr/bin/env bash\n"
            f'LIB="{ROOT / "lib"}"\n'
            f'RESULTS_FILE="{self.root / "results"}"\n'
            f'. "{HARNESS_SOURCE}"\n'
            'unset DEVFLOW_MODULE_OWNED_SCRATCH_ROOT\n'
            f'export TMPDIR="{self.root}"\n'
            f'export PATH="{fake_bin}:$PATH"\n'
            f'. "{short_module}"\n'
            'printf "SOURCE_RC:%s\\n" "$?"\n',
            encoding="utf-8",
        )

        result = subprocess.run(
            ["bash", str(driver)],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertIn("SOURCE_RC:1", result.stdout)
        self.assertTrue(sentinel.is_file(), result.stdout + result.stderr)

    def test_create_issue_self_root_rejects_traversal_shaped_allocator_output(
        self,
    ) -> None:
        source = CREATE_ISSUE_MODULE_SOURCE.read_text(encoding="utf-8")
        boundary = 'CI_IMPL_BUNDLE="$_ci_tmp_root/implement-skill-bundle.md"'
        self.assertEqual(source.count(boundary), 1)
        short_module = self.root / "short-create-issue-traversal.sh"
        short_module.write_text(
            source.split(boundary, 1)[0]
            + "_ci_cleanup\n"
            + "trap - EXIT HUP INT TERM\n"
            + "return 0\n",
            encoding="utf-8",
        )
        intermediate = self.root / "devflow-create-issue-contract.a"
        intermediate.mkdir()
        victim = self.root / "x"
        victim.mkdir()
        sentinel = victim / "sentinel"
        sentinel.write_text("keep\n", encoding="utf-8")
        traversal = intermediate / ".." / victim.name
        fake_bin = self.root / "traversal-mktemp-bin"
        fake_bin.mkdir()
        fake_mktemp = fake_bin / "mktemp"
        fake_mktemp.write_text(
            "#!/usr/bin/env bash\n"
            f'printf "%s\\n" "{traversal}"\n',
            encoding="utf-8",
        )
        fake_mktemp.chmod(0o755)
        driver = self.root / "traversal-create-issue-driver.sh"
        driver.write_text(
            "#!/usr/bin/env bash\n"
            f'LIB="{ROOT / "lib"}"\n'
            f'RESULTS_FILE="{self.root / "results"}"\n'
            f'. "{HARNESS_SOURCE}"\n'
            'unset DEVFLOW_MODULE_OWNED_SCRATCH_ROOT\n'
            f'export TMPDIR="{self.root}"\n'
            f'export PATH="{fake_bin}:$PATH"\n'
            f'. "{short_module}"\n'
            'printf "SOURCE_RC:%s\\n" "$?"\n',
            encoding="utf-8",
        )

        result = subprocess.run(
            ["bash", str(driver)],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertIn("SOURCE_RC:1", result.stdout)
        self.assertTrue(sentinel.is_file(), result.stdout + result.stderr)

    def test_create_issue_module_references_no_monolith_helper(self) -> None:
        # AC7: the extracted assertions use only assert_eq plus the namespaced module
        # API — a reference to pin_count / probe_tmp / another monolith helper (which
        # would not exist when the runner or the full-suite boundary source the module)
        # must make this contract test fail.
        text = CREATE_ISSUE_MODULE_SOURCE.read_text(encoding="utf-8")
        hits = sorted({match.group(1) for match in MONOLITH_HELPER_RE.finditer(text)})
        self.assertEqual(
            hits, [], f"create-issue module references monolith helper(s): {hits}"
        )

    def test_monolith_helper_contract_check_is_non_vacuous(self) -> None:
        # The check FAILS on a planted monolith-helper reference (so the test above
        # is a real guard, not a vacuous pass) …
        for planted in (
            "x=$(pin_count 'a' \"$F\")\n",
            "g=$(grep_present 'a' \"$F\")\n",
            "assert_pin_unique n l f\n",
            "assert_pin_red_on_removal n l f\n",
        ):
            self.assertIsNotNone(
                MONOLITH_HELPER_RE.search(planted), f"missed planted ref: {planted!r}"
            )
        # … and it does NOT false-positive on the sanctioned namespaced API, whose
        # `pin_count` substring is preceded by `_`.
        for sanctioned in (
            "devflow_module_pin_count 'a' \"$F\"\n",
            "devflow_module_pin_unique n l f\n",
            # Promoted to module-harness.sh by issue #695 — harness API, not monolith.
            "t=$(probe_tmp 'a')\n",
            "b=$(probe_assert devflow_module_pin_unique p l f)\n",
            "blk=$(mint_blk 'Step name' \"$F\")\n",
        ):
            self.assertIsNone(
                MONOLITH_HELPER_RE.search(sanctioned),
                f"false positive on namespaced API: {sanctioned!r}",
            )

    def test_create_issue_bundle_records_fail_on_a_missing_implement_member(self) -> None:
        # The module's implement-bundle build loop restores the fail-LOUD-per-member
        # contract: a missing/empty/unreadable implement bundle member records a FAIL
        # (never the sibling module's silent `cat 2>/dev/null || :`). Pin it with an
        # automated mutation — point CI_ROOT at a scratch tree that symlinks every
        # real surface the module reads (so its genuine pins still pass) but whose
        # implement `phases/` carries one EMPTY member (`[ -s ]` false → FAIL). The
        # emptied member is NOT the one holding the #467 D2 pinned sentence, so only
        # the bundle-member guard fires — isolating this branch.
        with tempfile.TemporaryDirectory() as temporary_directory:
            scratch = Path(temporary_directory) / "root"
            (scratch / "skills").mkdir(parents=True)
            (scratch / "lib/test").mkdir(parents=True)
            # `git init` the scratch so it is a real (empty) work tree: the module's #613 AC10
            # repo-wide sweep runs `git -C "$CI_ROOT" grep`, which exits 128 — its fail-closed
            # sentinel — against a NON-repo root. That would fire a second, unrelated FAIL here
            # and silently break the single-guard isolation this test's comment claims (the
            # returncode/assertIn assertions would still pass, hiding it). An empty repo makes
            # that sweep a clean rc-1 no-match, so only the bundle-member guard fires.
            subprocess.run(
                ["git", "init", "-q", "."],
                cwd=scratch,
                check=True,
                capture_output=True,
            )
            # Symlink every surface the module reads, except implement (partial copy).
            (scratch / "skills/create-issue").symlink_to(ROOT / "skills/create-issue")
            (scratch / "skills/review-and-fix").symlink_to(ROOT / "skills/review-and-fix")
            (scratch / "docs").symlink_to(ROOT / "docs")
            (scratch / ".prflow").symlink_to(ROOT / ".prflow")
            (scratch / "CLAUDE.md").symlink_to(ROOT / "CLAUDE.md")
            (scratch / "lib/test/modules").symlink_to(ROOT / "lib/test/modules")
            # implement: real SKILL.md, real phases EXCEPT one emptied member.
            impl = scratch / "skills/implement"
            (impl / "phases").mkdir(parents=True)
            (impl / "SKILL.md").symlink_to(ROOT / "skills/implement/SKILL.md")
            sentence = "The governed surface is broader than config JSON"  # #467 D2 pin
            emptied = None
            for phase in sorted((ROOT / "skills/implement/phases").glob("*.md")):
                text = phase.read_text(encoding="utf-8")
                if sentence in text or emptied is not None:
                    (impl / "phases" / phase.name).write_text(text, encoding="utf-8")
                else:
                    (impl / "phases" / phase.name).write_text("", encoding="utf-8")
                    emptied = phase.name
            self.assertIsNotNone(emptied, "no non-D2-pin phase to empty")
            # issue #815: the module's bundle now also spans implement's gated
            # references, so the partial copy has to carry them — otherwise the
            # emptied-phase FAIL this fixture proves would be confounded by a
            # second FAIL for an absent reference member.
            (impl / "references").mkdir(parents=True)
            for ref in sorted((ROOT / "skills/implement/references").glob("*.md")):
                (impl / "references" / ref.name).write_text(
                    ref.read_text(encoding="utf-8"), encoding="utf-8")

            environment = os.environ.copy()
            environment.pop("DEVFLOW_TEST_EXPERIMENT_FORCE_FAILURE", None)
            environment["DEVFLOW_CREATE_ISSUE_CONTRACT_ROOT"] = str(scratch)
            with tempfile.TemporaryDirectory() as log_dir:
                result = subprocess.run(
                    [
                        "bash",
                        str(RUNNER_SOURCE),
                        "--log-dir",
                        log_dir,
                        "create-issue-contract",
                    ],
                    cwd=ROOT,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )

        self.assertEqual(result.returncode, 1, result.stdout[-4000:] + result.stderr[-4000:])
        self.assertIn("implement-bundle member usable", result.stdout)
        self.assertIn(emptied, result.stdout)

    def test_create_issue_module_runs_clean_under_nounset_with_legacy_vars_unset(self) -> None:
        # AC9: a clean-environment contract test. Source the module under `set -u`
        # with every legacy monolith variable explicitly unset, supplying only LIB,
        # RESULTS_FILE, assert_eq, and the namespaced harness API. The module must
        # derive every path from LIB and run without an unbound-variable exit.
        with tempfile.TemporaryDirectory() as temporary_directory:
            work = Path(temporary_directory)
            results = work / "results"
            driver = work / "driver.sh"
            driver.write_text(
                "#!/usr/bin/env bash\n"
                "set -u\n"
                "unset CI312_SKILL CI312_TMPL CI443_SKILL CI443_EXT CI522_OVERVIEW \\\n"
                "  CI464_OVERVIEW CI559_SKILL OG_OVERVIEW_DOC IMPL_SKILL_BUNDLE \\\n"
                "  MAXI_SKILL 2>/dev/null || true\n"
                f'LIB="{ROOT}/lib"\n'
                f'RESULTS_FILE="{results}"\n'
                '> "$RESULTS_FILE"\n'
                "assert_eq() {\n"
                '  if [ "$2" = "$3" ]; then printf "PASS\\n" >> "$RESULTS_FILE";\n'
                '  else printf "FAIL\\n" >> "$RESULTS_FILE"; fi\n'
                "}\n"
                f'. "{ROOT}/lib/test/module-harness.sh"\n'
                f'. "{ROOT}/lib/test/modules/create-issue-contract.sh"\n',
                encoding="utf-8",
            )
            result = subprocess.run(
                ["bash", str(driver)],
                cwd=work,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("unbound variable", result.stderr)
            verdicts = results.read_text(encoding="utf-8").split()

        self.assertNotIn("FAIL", verdicts, result.stdout + result.stderr)
        self.assertGreater(len(verdicts), 0)

    def _write_mutant_create_issue_module(self, destination: Path) -> None:
        # A controlled create-issue module mutation: the real module plus one
        # deterministic failing assertion. DEVFLOW_CREATE_ISSUE_CONTRACT_ROOT points
        # the copy at the real repository so its genuine pins all pass and only the
        # planted assertion fails — isolating the mutation's single-FAIL delta.
        text = CREATE_ISSUE_MODULE_SOURCE.read_text(encoding="utf-8")
        text += '\nassert_eq "controlled create-issue mutation" "expected" "mutated"\n'
        destination.write_text(text, encoding="utf-8")

    def test_create_issue_focused_run_fails_closed_on_a_controlled_failure(self) -> None:
        # AC16: a create-issue module run whose assertion fails is caught and recapped
        # by the REAL focused runner (fail-closed, non-zero) — proving the runner's
        # crash/failure handling applies to the create-issue module, not only to the
        # synthetic sample/crash/empty modules exercised above.
        environment = os.environ.copy()
        environment["DEVFLOW_TEST_EXPERIMENT_FORCE_FAILURE"] = "1"
        with tempfile.TemporaryDirectory() as log_dir:
            result = subprocess.run(
                [
                    "bash",
                    str(RUNNER_SOURCE),
                    "--log-dir",
                    log_dir,
                    "create-issue-contract",
                ],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1, result.stdout[-4000:] + result.stderr[-4000:])
        self.assertIn("controlled experimental failure injection", result.stdout)
        self.assertRegex(
            result.stdout, r"Module create-issue-contract: [0-9]+ passed, 1 failed"
        )

    def test_controlled_mutation_fails_on_both_focused_and_full_suite_boundaries(self) -> None:
        # AC17: the focused runner and the complete-suite boundary observe the SAME
        # failing outcome from one controlled create-issue module mutation.
        mutant = self.modules_dir / "create-issue-mutant.sh"
        self._write_mutant_create_issue_module(mutant)
        self._write_registry(
            {
                "create-issue-mutant": {
                    "path": "lib/test/modules/create-issue-mutant.sh",
                    "minimum_assertions": 1,
                }
            }
        )
        base_env = {"DEVFLOW_CREATE_ISSUE_CONTRACT_ROOT": str(ROOT)}

        # Focused runner boundary.
        focused = self._run("create-issue-mutant", extra_env=base_env)
        self.assertEqual(focused.returncode, 1, focused.stdout + focused.stderr)
        self.assertIn("controlled create-issue mutation", focused.stdout)

        # Full-suite module boundary (module-harness.sh's devflow_run_full_suite_module).
        # A failing assertion lands in the shared RESULTS_FILE tally the way run.sh's own
        # FAIL loop counts it (the boundary's MODULE_FAILURES_FILE fold is reserved for
        # crash/floor/tally faults), so the boundary's observed failure is the FAIL record
        # the module appended to RESULTS_FILE — count that.
        with tempfile.TemporaryDirectory() as work_name:
            work = Path(work_name)
            results = work / "results"
            driver = work / "driver.sh"
            driver.write_text(
                "#!/usr/bin/env bash\n"
                f'RESULTS_FILE="{results}"\n'
                f'MODULE_FAILURES_FILE="{work / "module-failures"}"\n'
                '> "$RESULTS_FILE"\n'
                '> "$MODULE_FAILURES_FILE"\n'
                "assert_eq() {\n"
                '  if [ "$2" = "$3" ]; then printf "PASS\\n" >> "$RESULTS_FILE";\n'
                '  else printf "FAIL\\n" >> "$RESULTS_FILE"; fi\n'
                "}\n"
                f'. "{HARNESS_SOURCE}"\n'
                f'devflow_run_full_suite_module "{mutant}" "create-issue-mutant" 1\n',
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment.update(base_env)
            full_suite = subprocess.run(
                ["bash", str(driver)],
                cwd=work,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                full_suite.returncode, 0, full_suite.stdout + full_suite.stderr
            )
            boundary_verdicts = results.read_text(encoding="utf-8").split()

        # Same outcome: the full-suite boundary's tally carries the mutation's FAIL,
        # exactly as the focused runner reported it non-zero above.
        self.assertIn("FAIL", boundary_verdicts, full_suite.stdout + full_suite.stderr)


# ── issue #720: bounded concurrent Python-suite pool membership completeness ──
# Every lib/test/test_*.py on disk is classified into exactly one of three named
# categories. A file that appears in none (a new suite nobody routed) or in more
# than one is a defect this cross-check turns RED — so the pool's membership list
# and the serial/module-driven exclusions can never silently drift from the files.
POOLED_SUITES = (
    "test_module_runner.py",
    "test_python_scripts.py",
    "test_python_scripts_part2.py",
    "test_python_scripts_part3.py",
    "test_python_scripts_part4.py",
)
# One member of the real pool invocation, as it is spelled in module-harness.sh. Held as a
# constant because test_repository_registry_maps_the_extracted_recorder_module asserts
# opposite things about it — present in the harness, absent from the extracted module — and
# a literal typed twice can be corrected in only one of its two places.
POOL_TRIPLE_LITERAL = '"$_pp_dir/test_module_runner.py" single-verdict'
SERIAL_BY_EXCLUSION_SUITES = (
    "test_module_harness.py",
    # The mutation-pin census focused tests run serially on the main shell via
    # run.sh. They are not part of the Python pool or a full-suite module.
    "test_mutation_pin_census.py",
    # issue #767: the create-issue context eval's focused unittest runs serially on
    # the main shell (invoked directly by run.sh, like test_module_harness.py above),
    # not through the pool or a full-suite module.
    "test_create_issue_context_eval.py",
    # issue #1209: the implement context eval's focused unittest runs serially on the
    # main shell (invoked directly by run.sh, like test_create_issue_context_eval.py
    # above), not through the pool or a full-suite module.
    "test_implement_context_eval.py",
    # issue #1852: the review context eval's focused unittest runs serially on the
    # main shell (invoked directly by run.sh, like test_implement_context_eval.py
    # above), not through the pool or a full-suite module.
    "test_review_context_eval.py",
    # issue #1900: the shared context-eval helpers' focused unittest runs serially on
    # the main shell (invoked directly by run.sh, like test_review_context_eval.py
    # above), not through the pool or a full-suite module.
    "test_context_eval_shared.py",
    # The provider-neutral create-issue benchmark runs serially on the main shell
    # because its focused test launches matched local provider subprocesses.
    "test_create_issue_benchmark.py",
    # issue #1928: the subject-grouping helper's focused unittest runs serially on the
    # main shell (invoked directly by run.sh, like the eval blocks above), not through
    # the pool or a full-suite module.
    "test_group_labels_by_subject.py",
)
MODULE_DRIVEN_SUITES = (
    "test_reconcile_module_floors.py",
    "test_render_audit_prompt.py",
    "test_verification_baseline.py",
    "test_verification_flight.py",
    "test_reception_identity.py",
    "test_coverage_map_guard.py",
    "test_coverage_map_merge.py",
    "test_assertion_floor_retention.py",
    "test_pin_corpus_classifier.py",
    "test_pin_corpus_lint.py",
    "test_profile_suite.py",
    "test_red_on_removal_retirement_manifest.py",
    "test_residual_prose_retirement_manifest.py",
    "test_workflow_flight_recorder.py",
    # issue #2006: the implement run evaluation instruments' focused unittests,
    # driven by lib/test/modules/harness-python-guards.sh.
    "test_derive_run_profile.py",
    "test_implement_timeline.py",
    "test_implement_run_report.py",
    "test_implement_benchmark.py",
    "test_workflow_analyzer.py",
)


def discover_test_suites(test_dir):
    """Return the sorted test_*.py basenames directly in test_dir (issue #720).

    Takes a directory argument so the completeness cross-check can be pointed at a
    scratch root in tests — the planted-defect fixture never lands in lib/test/.
    Single-level glob rooted at the given directory, never a repository-root walk.
    """
    return sorted(path.name for path in Path(test_dir).glob("test_*.py"))


def classify_test_suites(
    test_dir,
    pooled=POOLED_SUITES,
    serial=SERIAL_BY_EXCLUSION_SUITES,
    module_driven=MODULE_DRIVEN_SUITES,
):
    """Cross-check discovery in test_dir against the three named categories.

    Returns a list of human-readable violations (empty when every discovered file
    is in exactly one category and every classified file exists on disk).
    """
    classified = list(pooled) + list(serial) + list(module_driven)
    violations = []
    counts = {}
    for name in classified:
        counts[name] = counts.get(name, 0) + 1
    for name in sorted(counts):
        if counts[name] > 1:
            violations.append(f"{name}: appears in more than one category")
    discovered = set(discover_test_suites(test_dir))
    classified_set = set(classified)
    for name in sorted(discovered - classified_set):
        violations.append(f"{name}: on disk but in none of the three categories")
    for name in sorted(classified_set - discovered):
        violations.append(f"{name}: classified but not found on disk in {test_dir}")
    return violations


def invocation_shape(name):
    """Return the literal a driver spells to invoke the suite (issue #867).

    Every driver in this tree anchors the path on $LIB and quotes it; prose does
    not. Matching that shape rather than the bare basename is what keeps a
    comment mentioning lib/test/<name> from either satisfying or violating a
    routing claim — a distinction with live consequences, since
    lib/test/modules/create-issue-contract.sh mentions test_render_audit_prompt.py
    in comments while driving it nowhere.

    Accepted residual: an invocation spelled some other way — unquoted, via
    ${LIB}, or repo-relative `lib/test/<name>` — is not matched, so it would
    neither trip the run.sh claim nor count as an owner. Nothing enforces the
    spelling; the shape is a convention this scan reads rather than a contract it
    guarantees. `scan_routing_violations` states what that costs.
    """
    return f'"$LIB/test/{name}"'


def strip_shell_comments(text):
    """Drop whole-line shell comments so a mention in prose is never a match.

    `invocation_shape` makes a *bare* path in prose inert, but the quoted
    $LIB-anchored form can appear in a comment too — most damagingly a
    commented-out driver, which is the usual way an invocation gets disabled.
    Without this, such a line would satisfy the serial at-least-once claim
    (masking coverage that is in fact gone) and count as a module owner.

    Whole-line only: a trailing comment on a real invocation line must not
    strip the invocation itself, and a `#` inside a quoted string is not a
    comment. Both are handled by taking the line as code whenever its first
    non-whitespace character is anything but `#`.

    Residual: the rule is line-oriented, so a line inside a heredoc or a
    multi-line string that begins with `#` is stripped too. Harmless while no
    such line carries an invocation shape, which is the only content this scan
    reads a line for.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def scan_routing_violations(
    run_sh_path=RUN_SH_SOURCE,
    modules_dir=MODULES_DIR,
    module_harness_path=HARNESS_SOURCE,
    serial=SERIAL_BY_EXCLUSION_SUITES,
    module_driven=MODULE_DRIVEN_SUITES,
    shape_for=invocation_shape,
):
    """Cross-check the routing tuples against where the tree actually drives them.

    Returns a list of human-readable violations, empty when every claim holds.
    A routing violation names the offending suite; a read failure names the
    unreadable path instead, and the two never appear together (see below). The
    routing claims are:

    - no module_driven name's invocation shape is present in run.sh;
    - every module_driven name's invocation shape is present in exactly one
      distinct module file — counting FILES, never occurrences, so a module that
      names the same suite on more than one line still counts once;
    - every serial name's invocation shape is present in run.sh.

    The two reads below route through strip_shell_comments, so neither a bare
    path in prose nor a commented-out driver can satisfy or violate a claim.

    What this does NOT catch: an invocation spelled outside `shape_for`'s literal
    (unquoted, ${LIB}, or repo-relative). That is narrower than a bare-basename
    grep, which is the deliberate trade — a basename match cannot tell a driver
    from a comment. The scan is also blind to a driver reached from anywhere
    outside the paths its parameters name, notably lib/test/run-module.sh.

    POOLED_SUITES is deliberately absent: module-harness.sh's real devflow_pool_open
    triples already pin it by set equality (see
    PoolMembershipCompletenessTests.test_pooled_suites_constant_matches_the_run_sh_pool_invocation),
    which is a stronger guarantee than a name scan.

    The paths this scan reads are run_sh_path, modules_dir and
    module_harness_path, each a parameter defaulting to the real tree, mirroring
    discover_test_suites/classify_test_suites, so a planted-violation fixture can
    point the scan at a scratch copy. The module domain is a single-level,
    suffix-filtered listing of modules_dir plus the standalone
    module_harness_path — never a repository-root-anchored recursive walk.

    Any read failure — run.sh, the modules_dir listing, a module file, or the
    standalone harness alike — returns the read-failure violations ALONE. A
    truncated domain cannot support an ownership claim, so reporting one beside
    the read failure would accuse a correct routing tuple of the I/O error.
    """
    try:
        run_text = strip_shell_comments(
            Path(run_sh_path).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError) as exc:
        # UnicodeDecodeError is a ValueError, not an OSError: a non-UTF-8 body is
        # a read failure under this helper's "any read failure" contract, so it
        # must route here rather than propagate as an uncaught crash.
        # Return here rather than falling through: every later step is discarded
        # by the read-failure-alone rule anyway, so continuing would read the
        # whole module domain only to throw it away.
        return [f"{run_sh_path}: could not be read for the routing scan ({exc})"]
    read_failures = []
    module_texts = {}
    # Deviates from issue #867's prescribed "single-level glob over
    # lib/test/modules/*.sh": glob() swallows FileNotFoundError /
    # NotADirectoryError / PermissionError on the directory itself and yields
    # nothing, so a renamed or unreadable modules_dir would produce an empty
    # domain with no read failure — and every module-driven suite would then be
    # accused of owning zero files, exactly the misattribution the
    # read-failure-alone rule below exists to prevent. iterdir() raises instead.
    # Still single-level and suffix-filtered, so the criterion's actual
    # requirement — a non-recursive enumeration needing no `# tree-walk-ok:`
    # declaration under the issue-#711 convention — is unchanged; see the
    # workpad AC-rewrite note.
    try:
        module_paths = sorted(
            path for path in Path(modules_dir).iterdir() if path.suffix == ".sh"
        )
    except OSError as exc:
        module_paths = []
        read_failures.append(
            f"{modules_dir}: could not be enumerated for the routing scan ({exc})"
        )
    # The harness is read through the same try/except as the module files rather
    # than pre-tested with .exists(): a renamed, unreadable, or unstattable path
    # must be a reported read failure, never a silently truncated scan domain.
    for path in (*module_paths, Path(module_harness_path)):
        try:
            module_texts[path] = strip_shell_comments(
                path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeDecodeError) as exc:
            # Same widening as the run.sh read above: a non-UTF-8 module body is
            # a read failure, not an uncaught UnicodeDecodeError.
            read_failures.append(
                f"{path}: could not be read for the routing scan ({exc})"
            )
    if read_failures:
        return read_failures
    violations = []
    for name in module_driven:
        shape = shape_for(name)
        if shape in run_text:
            violations.append(
                f"{name}: classified MODULE_DRIVEN_SUITES but invoked from "
                f"{run_sh_path} — it would execute twice"
            )
        # Render the full path, not path.name: a module named module-harness.sh
        # would otherwise be indistinguishable from the standalone harness in the
        # violation message.
        owners = sorted(
            str(path) for path, text in module_texts.items() if shape in text
        )
        if len(owners) != 1:
            violations.append(
                f"{name}: classified MODULE_DRIVEN_SUITES but driven by "
                f"{len(owners)} module file(s) {owners}, expected exactly one"
            )
    for name in serial:
        if shape_for(name) not in run_text:
            violations.append(
                f"{name}: classified SERIAL_BY_EXCLUSION_SUITES but never invoked "
                f"from {run_sh_path} — its coverage is silently gone"
            )
    return violations


class HostCapabilitySkipChannelTests(unittest.TestCase):
    """Issue #838: the module-reachable host-capability skip channel.

    A module may not self-skip, so `skip()` is not a raw module surface. The full-suite
    boundary instead binds the module child a PRIVATE skip tally and folds it back, and
    the surface a module calls is `module_host_capability_skip`, which delegates to
    `lib/test/run.sh`'s `skip()` — still the sole `#456` producer. These tests drive the
    real boundary and the real producer, never a stand-in: `skip()` is extracted from
    `run.sh` by its own region markers, so a run.sh that lost the region fails here too.
    """

    SKIP_REGION_BEGIN = "# SKIP_HELPER_REGION_BEGIN"
    SKIP_REGION_END = "# SKIP_HELPER_REGION_END"

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.addCleanup(self.temporary_directory.cleanup)

    def _extracted_skip_helper(self) -> Path:
        """Write run.sh's real `skip()` to a sourceable file, cut at its region markers."""
        text = (ROOT / "lib/test/run.sh").read_text(encoding="utf-8")
        begin = text.find(self.SKIP_REGION_BEGIN)
        end = text.find(self.SKIP_REGION_END)
        self.assertNotEqual(begin, -1, "run.sh lost its skip-helper region begin marker")
        self.assertNotEqual(end, -1, "run.sh lost its skip-helper region end marker")
        self.assertLess(begin, end)
        path = self.root / "skip-helper.sh"
        path.write_text(text[begin : end + len(self.SKIP_REGION_END)], encoding="utf-8")
        return path

    def _drive_boundary(
        self,
        module_body: str,
        minimum_assertions: int,
        *,
        module_name: str = "synthetic",
    ) -> dict[str, object]:
        """Run one synthetic module through the real full-suite boundary.

        Returns the caller-side artifacts the boundary is responsible for producing:
        the shared skip tally, the shared result tally, the boundary-failure record,
        and the process output.
        """
        module = self.root / f"{module_name}.sh"
        module.write_text(module_body, encoding="utf-8")
        results = self.root / "results"
        skips = self.root / "skips"
        failures = self.root / "module-failures"
        driver = self.root / "driver.sh"
        driver.write_text(
            "#!/usr/bin/env bash\n"
            f'RESULTS_FILE="{results}"\n'
            f'SKIPS_FILE="{skips}"\n'
            f'MODULE_FAILURES_FILE="{failures}"\n'
            '> "$RESULTS_FILE"\n'
            '> "$SKIPS_FILE"\n'
            '> "$MODULE_FAILURES_FILE"\n'
            "assert_eq() {\n"
            '  if [ "$2" = "$3" ]; then printf "PASS\\n" >> "$RESULTS_FILE";\n'
            '  else printf "FAIL\\n" >> "$RESULTS_FILE"; fi\n'
            "}\n"
            f'. "{self._extracted_skip_helper()}"\n'
            f'. "{HARNESS_SOURCE}"\n'
            f'devflow_run_full_suite_module "{module}" "{module_name}" '
            f"{minimum_assertions}\n",
            encoding="utf-8",
        )
        completed = subprocess.run(
            ["bash", str(driver)],
            cwd=self.root,
            env=os.environ.copy(),
            text=True,
            capture_output=True,
            check=False,
        )
        names = results.with_name(results.name + ".names")
        return {
            "completed": completed,
            "skips": skips.read_text(encoding="utf-8"),
            "results": results.read_text(encoding="utf-8"),
            # MODULE_FAILURES_FILE carries only the bare `FAIL` verdicts; the boundary
            # failure's identifier lands in the `.names` record (issue #789), which is
            # what a reader of the recap actually sees — so assert against that.
            "failures": names.read_text(encoding="utf-8") if names.exists() else "",
            "failure_verdicts": failures.read_text(encoding="utf-8").split(),
        }

    def test_module_skip_is_folded_into_the_shared_tally_and_rendered(self) -> None:
        """The skip reaches the caller's SKIPS_FILE and summary.sh renders it."""
        observed = self._drive_boundary(
            'assert_eq "synthetic ran" "x" "x"\n'
            'module_host_capability_skip "synthetic arm" "reads not denied here" 2\n',
            1,
        )
        completed = observed["completed"]
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(
            observed["skips"],
            "host-capability\tsynthetic arm\treads not denied here\n",
        )
        # A skip is neither a PASS nor a FAIL in the shared verdict tally.
        self.assertEqual(observed["results"].split(), ["PASS"])
        # And the real renderer reports it as a skip rather than a clean pass.
        render = self.root / "render.sh"
        render.write_text(
            "#!/usr/bin/env bash\n"
            f'. "{ROOT / "lib/test/summary.sh"}"\n'
            f'devflow_render_test_summary 1 0 1 "{self.root / "skips"}"\n',
            encoding="utf-8",
        )
        rendered = subprocess.run(
            ["bash", str(render)], text=True, capture_output=True, check=False
        )
        self.assertIn("1 passed, 0 failed, 1 skipped", rendered.stdout)
        self.assertIn("synthetic arm", rendered.stdout)

    def test_two_module_skips_are_folded_and_rendered_in_the_plural(self) -> None:
        """K > 1 skips: both fold, both itemize, and the clause reads "2 skipped".

        Every other fold test declares exactly one skip, so the loop's second iteration,
        the plural clause, and the multi-line itemization were unexercised.
        """
        observed = self._drive_boundary(
            'assert_eq "synthetic ran" "x" "x"\n'
            'module_host_capability_skip "first arm" "reads not denied here" 2\n'
            'module_host_capability_skip "second arm" "no fifo support here" 3\n',
            1,
        )
        completed = observed["completed"]
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(
            observed["skips"],
            "host-capability\tfirst arm\treads not denied here\n"
            "host-capability\tsecond arm\tno fifo support here\n",
        )
        render = self.root / "render2.sh"
        render.write_text(
            "#!/usr/bin/env bash\n"
            f'. "{ROOT / "lib/test/summary.sh"}"\n'
            f'devflow_render_test_summary 1 0 2 "{self.root / "skips"}"\n',
            encoding="utf-8",
        )
        rendered = subprocess.run(
            ["bash", str(render)], text=True, capture_output=True, check=False
        )
        self.assertIn("1 passed, 0 failed, 2 skipped", rendered.stdout)
        self.assertIn("first arm", rendered.stdout)
        self.assertIn("second arm", rendered.stdout)

    def test_an_overlong_credit_is_rejected_by_the_length_guard(self) -> None:
        """The digit-length arm of the credit validator, not just the non-digit arm.

        Malformed-credit coverage used only a non-numeric token, so the `????????*`
        bound — which exists so the summing arithmetic cannot overflow — was never
        driven. An 8-digit credit is digits-only and must still be rejected, and the
        rejection must not quietly grant the floor relief it declared.
        """
        observed = self._drive_boundary(
            'assert_eq "one" "x" "x"\n'
            'module_host_capability_skip "gated arm" "host cannot deny reads" 12345678\n',
            3,
        )
        self.assertIn("malformed skip-assertion credit", observed["failures"])
        self.assertIn(
            "malformed skip-assertion credit: 12345678", observed["completed"].stderr
        )
        # The rejected credit buys nothing: the floor of 3 still trips on 1 assertion.
        self.assertIn("minimum is", observed["completed"].stderr)

    def test_declared_credit_prevents_a_spurious_floor_trip(self) -> None:
        """A host that cannot express the condition reports a skip, not a floor trip."""
        observed = self._drive_boundary(
            'assert_eq "one" "x" "x"\n'
            'module_host_capability_skip "gated arm" "host cannot deny reads" 2\n',
            3,
        )
        completed = observed["completed"]
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertNotIn("minimum is", completed.stderr)
        self.assertEqual(observed["failures"].strip(), "")

    def test_multiple_skips_accumulate_their_credits_and_all_are_itemized(self) -> None:
        """The credit sum is an aggregation, so drive it with more than one element.

        A single-skip test exercises no accumulation: one credit is already its own
        total. This is the shape `review-stall-backstop.sh` actually produces on a
        cannot-deny-reads host — one skip and one credit per gated arm — so the sum,
        and the fact that every skip is itemized rather than collapsed, are both driven
        here with a multi-element input.
        """
        observed = self._drive_boundary(
            'assert_eq "one" "x" "x"\n'
            'module_host_capability_skip "first arm" "host cannot deny reads" 2\n'
            'module_host_capability_skip "second arm" "host cannot deny reads" 2\n'
            'module_host_capability_skip "third arm" "host cannot deny reads" 2\n',
            7,
        )
        completed = observed["completed"]
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        # 1 executed + 6 credited == the floor of 7: the sum, not just the last credit.
        self.assertNotIn("minimum is", completed.stderr)
        self.assertEqual(observed["failures"], "")
        # Each skip is its own tally line — distinct arms, none collapsed.
        skip_lines = observed["skips"].splitlines()
        self.assertEqual(len(skip_lines), 3, observed["skips"])
        self.assertEqual(
            [line.split("\t")[1] for line in skip_lines],
            ["first arm", "second arm", "third arm"],
        )
        # One short of the sum still trips, proving the 7 above was not a free pass.
        tighter = self._drive_boundary(
            'assert_eq "one" "x" "x"\n'
            'module_host_capability_skip "first arm" "host cannot deny reads" 2\n'
            'module_host_capability_skip "second arm" "host cannot deny reads" 2\n'
            'module_host_capability_skip "third arm" "host cannot deny reads" 2\n',
            8,
            module_name="synthetic-tighter",
        )
        self.assertIn("effective 2 after 6 credited skip assertions", tighter["completed"].stderr)

    def test_under_covering_credit_still_trips_the_floor(self) -> None:
        """The credit reconciles the floor; it never waives it."""
        observed = self._drive_boundary(
            'assert_eq "one" "x" "x"\n'
            'module_host_capability_skip "gated arm" "host cannot deny reads" 1\n',
            5,
        )
        self.assertIn("minimum is", observed["completed"].stderr)
        self.assertIn("executed 1 assertions", observed["completed"].stderr)

    def test_malformed_credit_is_rejected_and_grants_nothing(self) -> None:
        """A non-integer credit fails closed: a boundary failure and zero credit."""
        observed = self._drive_boundary(
            'assert_eq "one" "x" "x"\n'
            'module_host_capability_skip "gated arm" "host cannot deny reads" two\n',
            3,
        )
        self.assertIn("credit", observed["failures"])
        # Zero credit granted, so the floor still trips.
        self.assertIn("minimum is", observed["completed"].stderr)

    def test_credit_reaching_the_floor_is_rejected(self) -> None:
        """A credit that meets or exceeds the floor reverts to the stricter bound."""
        observed = self._drive_boundary(
            'assert_eq "one" "x" "x"\n'
            'module_host_capability_skip "gated arm" "host cannot deny reads" 3\n',
            3,
        )
        self.assertIn("credit", observed["failures"])
        self.assertIn("minimum is 3", observed["completed"].stderr)

    def test_a_non_host_capability_skip_record_is_rejected(self) -> None:
        """Binding the child a real skip channel must not become a laundering vector.

        A module that reaches past the wrapper and records a `blocking-gate` skip is
        rejected at the fold, so the shared tally can never absorb a gate a module
        skipped for itself.
        """
        observed = self._drive_boundary(
            'assert_eq "one" "x" "x"\n'
            'skip "smuggled gate" blocking-gate "a module may not do this"\n',
            1,
        )
        self.assertIn("recorded a non-host-capability skip", observed["failures"])
        self.assertNotIn("smuggled gate", observed["skips"])

    def test_an_unreadable_private_record_is_reported_not_silently_empty(self) -> None:
        """An unreadable record must not read as "nothing was recorded".

        The existence check cannot stand in for the consumption: a non-empty but
        unreadable file makes the fold's redirect fail, the loop body never runs, and
        the skips and their credits vanish with no diagnostic. The module chmods its own
        record after writing it, which is the only way to reach this state from inside
        the child.
        """
        if os.geteuid() == 0:
            self.skipTest("chmod 000 does not deny reads when running as root")
        observed = self._drive_boundary(
            'assert_eq "one" "x" "x"\n'
            'module_host_capability_skip "gated arm" "host cannot deny reads" 2\n'
            'chmod 000 "$SKIPS_FILE"\n',
            3,
        )
        self.assertIn("private skip tally is unreadable", observed["failures"])
        # And the unreadable record never silently buys floor relief.
        self.assertIn("minimum is", observed["completed"].stderr)

    def test_an_unreadable_private_credit_record_is_reported_not_silently_empty(self) -> None:
        """The credit record gets the same treatment as the skip tally.

        A non-empty but unreadable credit record makes the summing loop's redirect fail
        and the credits vanish. That direction is the safe one (no relief is granted),
        but it must still be attributable rather than a silent read of "no credit was
        declared" — the same reason the skip tally's arm exists.
        """
        if os.geteuid() == 0:
            self.skipTest("chmod 000 does not deny reads when running as root")
        observed = self._drive_boundary(
            'assert_eq "one" "x" "x"\n'
            'module_host_capability_skip "gated arm" "host cannot deny reads" 2\n'
            'chmod 000 "$MODULE_SKIP_CREDIT_FILE"\n',
            3,
        )
        self.assertIn("skip-credit record is unreadable", observed["failures"])
        # And the forfeited credit never buys floor relief.
        self.assertIn("minimum is", observed["completed"].stderr)

    def test_a_failed_credit_write_is_fatal_not_silently_dropped(self) -> None:
        """A credit line that cannot be written must abort, not vanish (issue #899).

        The boundary's reject arm zeroes the credit only when the total REACHES the
        floor, so a partial loss is not conservative: it can carry a run from the
        rejected state (strict floor) into the accepted state (lowered floor). An
        unguarded append would drop the line and let the module clear a relaxed floor,
        which is fail-open in a fail-closed path — so the wrapper guards the write and
        terminates the worker, and the boundary reports that as an attributable module
        failure.

        The trigger is a DIRECTORY as the credit target, which raises EISDIR on the
        append for every uid — unlike `chmod 000`, which root ignores and which would
        make this test self-skip on such a host.
        """
        observed = self._drive_boundary(
            'assert_eq "one" "x" "x"\n'
            'MODULE_SKIP_CREDIT_FILE="$(mktemp -d "${TMPDIR:-/tmp}/dfcredit.XXXXXX")"\n'
            'module_host_capability_skip "gated arm" "host cannot deny reads" 2\n'
            # Never reached: the wrapper exits the worker on the failed write.
            'assert_eq "after the failed write" "x" "y"\n',
            1,
        )
        completed = observed["completed"]
        self.assertIn(
            "FATAL: could not record host-capability skip credit", completed.stderr
        )
        # Attributable at the boundary, not a silent continue.
        self.assertIn("exited with status 1", observed["failures"])
        # And the worker really stopped there: the post-write assertion never ran, so
        # no FAIL verdict from it reached the tally.
        self.assertEqual(observed["results"], "PASS\n")

    def test_a_leading_zero_credit_is_summed_as_decimal(self) -> None:
        """A digit-only credit the validator accepts must sum in base 10.

        `08`/`09` are not valid octal and `010` is not 10 in octal, so an unforced
        arithmetic expansion would either abort with "value too great for base" or
        silently mis-sum — neither of which is the attributable rejection the validator
        promises for a shape it declines to accept. The validator accepts these, so the
        sum must honor them at face value.
        """
        observed = self._drive_boundary(
            'assert_eq "one" "x" "x"\n'
            'module_host_capability_skip "gated arm" "host cannot deny reads" 08\n',
            9,
        )
        completed = observed["completed"]
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertNotIn("value too great for base", completed.stderr)
        # 1 executed + 8 credited == the floor of 9: credited as decimal 8, not octal.
        self.assertNotIn("minimum is", completed.stderr)
        self.assertEqual(observed["failures"], "")

    def test_the_fold_reimposes_the_three_field_shape_on_a_hand_written_record(self) -> None:
        """A second writer must not be able to bend the record shape.

        Binding the child a real SKIPS_FILE means `skip()` is no longer its only writer,
        so the "exactly three TAB-separated fields" invariant it maintained by
        construction needs a keeper. lib/test/summary.sh field-splits each line on TAB,
        so an extra TAB would render a skip's fields transposed and a CR would ride into
        the summary line. The fold splits and re-emits, so the shape holds regardless of
        what the writer produced.
        """
        observed = self._drive_boundary(
            'assert_eq "one" "x" "x"\n'
            # Four fields plus a CR — the shape skip() could never produce.
            "printf 'host-capability\\tname\\twith\\textra\\treason\\r\\n' "
            '>> "$SKIPS_FILE"\n',
            1,
        )
        completed = observed["completed"]
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        folded = observed["skips"].splitlines()
        self.assertEqual(len(folded), 1, observed["skips"])
        # Exactly three fields survive, the surplus TABs and the CR collapsed to spaces.
        self.assertEqual(folded[0].count("\t"), 2, repr(folded[0]))
        self.assertNotIn("\r", folded[0])
        self.assertEqual(
            folded[0], "host-capability\tname\twith extra reason ", repr(folded[0])
        )

    # ── Focused-tier skip channel (issue #887) ───────────────────────────────────
    # The full-suite boundary above already folds a host-capability skip. Since #877
    # routes every modules-* shard through lib/test/run-module.sh, the FOCUSED runner is a
    # merge gate too, so it must fold a sanctioned host-capability declaration into a
    # visible skip (with its assertion credit) instead of aborting — while a RAW self-skip
    # stays a fatal contract violation. These tests drive the real run-module.sh.

    def _run_focused(
        self,
        module_body: str,
        *,
        minimum_assertions: int = 1,
        module_name: str = "synthetic",
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        modules_dir = self.root / "lib/test/modules"
        scripts_dir = self.root / "scripts"
        modules_dir.mkdir(parents=True, exist_ok=True)
        scripts_dir.mkdir(parents=True, exist_ok=True)
        (modules_dir / f"{module_name}.sh").write_text(module_body, encoding="utf-8")
        (scripts_dir / "workflow-flight-recorder-registry.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "workflows": {"placeholder": {}},
                    "test_modules": {
                        module_name: {
                            "path": f"lib/test/modules/{module_name}.sh",
                            "minimum_assertions": minimum_assertions,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        shutil.copy2(RUNNER_SOURCE, self.root / "lib/test/run-module.sh")
        shutil.copy2(HARNESS_SOURCE, self.root / "lib/test/module-harness.sh")
        environment = os.environ.copy()
        environment.pop("DEVFLOW_TEST_EXPERIMENT_FORCE_FAILURE", None)
        if extra_env:
            environment.update(extra_env)
        return subprocess.run(
            [
                "bash",
                str(self.root / "lib/test/run-module.sh"),
                "--log-dir",
                str(self.root / "logs"),
                module_name,
            ],
            cwd=self.root,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_focused_runner_folds_a_host_capability_skip_with_its_credit(self) -> None:
        """AC1: a module_host_capability_skip is reported as a skip, not an abort, and its
        declared credit reconciles the floor so the module still satisfies it."""
        completed = self._run_focused(
            'assert_eq "one" "x" "x"\n'
            'module_host_capability_skip "gated arm" "host cannot deny reads" 2\n',
            minimum_assertions=3,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn(
            "Module synthetic: 1 passed, 0 failed, 1 skipped",
            completed.stdout.splitlines(),
        )
        self.assertIn(
            "  SKIP  gated arm [host-capability] — host cannot deny reads",
            completed.stdout,
        )
        # The credit (2) reconciles the floor (3) against the 1 executed assertion — no
        # floor trip.
        self.assertNotIn("minimum is", completed.stdout)

    def test_focused_runner_stays_fatal_for_a_raw_self_skip(self) -> None:
        """AC2: a RAW `skip` a module invokes directly (not through the sanctioned
        wrapper) still fails fatally with the durable contract-violation message. This is
        the executed test that distinguishes the two paths from the folded one above."""
        completed = self._run_focused(
            'assert_eq "one" "x" "x"\nskip "gated arm" host-capability "reason"\n',
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "modules may not self-skip", completed.stdout + completed.stderr
        )

    def test_focused_unreadable_skip_tally_forfeits_credit_and_fails(self) -> None:
        """An unreadable skip tally must not read as "nothing was recorded" on the
        focused tier either (issue #899 review).

        This is the fail-OPEN shape the focused fold's `-s`/`!-r` arms close, and it is
        asymmetric on purpose: only the SKIPS_FILE is denied, so the credit record stays
        readable. Without the arms the skips vanish from the summary (SKIP_COUNT stays 0,
        no `, K skipped` clause, no itemized SKIP line) while the still-readable credit
        keeps lowering EFFECTIVE_MIN — one executed assertion clears a floor of 3 relaxed
        to 1 and the module reports a byte-clean pass on a merge gate. The module chmods
        its own record after writing it, the only way to reach this state from inside the
        child.
        """
        if os.geteuid() == 0:
            self.skipTest("chmod 000 does not deny reads when running as root")
        completed = self._run_focused(
            'assert_eq "one" "x" "x"\n'
            'module_host_capability_skip "gated arm" "host cannot deny reads" 2\n'
            'chmod 000 "$SKIPS_FILE"\n',
            minimum_assertions=3,
        )
        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertIn(
            "  - private skip tally is unreadable; every skip credit was forfeited",
            completed.stdout,
        )
        # The credit is forfeited with the skip it belonged to, so the RAW floor stands
        # (no `effective` clause) and the shortfall is reported rather than credited away.
        self.assertIn(
            "  - module executed 1 assertions; minimum is 3", completed.stdout
        )
        # And the vanished skip never renders as a clean pass.
        self.assertNotIn("1 skipped", completed.stdout)

    def test_focused_unreadable_credit_record_is_reported_not_silently_empty(self) -> None:
        """The credit record gets the same treatment as the skip tally: unreadable is a
        reported failure, never a silent zero-credit read."""
        if os.geteuid() == 0:
            self.skipTest("chmod 000 does not deny reads when running as root")
        completed = self._run_focused(
            'assert_eq "one" "x" "x"\n'
            'module_host_capability_skip "gated arm" "host cannot deny reads" 2\n'
            'chmod 000 "$MODULE_SKIP_CREDIT_FILE"\n',
            minimum_assertions=3,
        )
        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertIn(
            "  - private skip-credit record is unreadable", completed.stdout
        )

    # The three credit guards below (malformed credit, credit at the floor, credit past
    # the floor) exist a SECOND time in lib/test/run-module.sh — the full-suite boundary's
    # copies in module-harness.sh are driven by the `_drive_boundary` tests above, which
    # never execute this file's code. Since #877 made the focused runner a merge gate,
    # these drive the focused copies directly: without them a drift confined to
    # run-module.sh (e.g. its `-ge "$MIN_ASSERTIONS"` reject relaxing to `-gt`) would
    # waive the floor on a credit exactly equal to it while the suite stayed green.

    def test_focused_malformed_credit_is_rejected_and_grants_nothing(self) -> None:
        """A non-integer credit fails closed on the focused tier: an attributable
        failure, zero credit granted, and the floor still trips."""
        completed = self._run_focused(
            'assert_eq "one" "x" "x"\n'
            'module_host_capability_skip "gated arm" "host cannot deny reads" two\n',
            minimum_assertions=3,
        )
        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertIn(
            "  - skip-credit record contained 1 malformed declaration(s)",
            completed.stdout,
        )
        # Zero credit granted, so the RAW floor still trips (no `effective` clause).
        self.assertIn(
            "  - module executed 1 assertions; minimum is 3", completed.stdout
        )

    def test_focused_credit_exactly_at_the_floor_is_rejected(self) -> None:
        """The `-ge` boundary: a credit EQUAL to the floor leaves nothing for the floor
        to assert, so it is rejected and the raw minimum stands. A relaxation to `-gt`
        would accept it, drop the effective floor to zero and waive the gate."""
        completed = self._run_focused(
            'assert_eq "one" "x" "x"\n'
            'module_host_capability_skip "gated arm" "host cannot deny reads" 3\n',
            minimum_assertions=3,
        )
        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertIn(
            "  - skip-assertion credit met or exceeded the assertion floor 3 and was rejected",
            completed.stdout,
        )
        # The raw floor stands: the credit bought no relief at all.
        self.assertIn(
            "  - module executed 1 assertions; minimum is 3", completed.stdout
        )

    def test_focused_credit_past_the_floor_is_rejected(self) -> None:
        """The other side of the same comparison: a credit strictly greater than the
        floor is rejected too, so an over-declaration cannot buy a free pass."""
        completed = self._run_focused(
            'assert_eq "one" "x" "x"\n'
            'module_host_capability_skip "gated arm" "host cannot deny reads" 9\n',
            minimum_assertions=3,
        )
        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertIn(
            "  - skip-assertion credit met or exceeded the assertion floor 3 and was rejected",
            completed.stdout,
        )
        self.assertIn(
            "  - module executed 1 assertions; minimum is 3", completed.stdout
        )

    def test_focused_non_host_capability_skip_record_is_rejected(self) -> None:
        """The focused tier's own `SKIP_MALFORMED_COUNT` arm (Suggestion finding on
        PR #899). The `skip` override never writes a non-host-capability line itself, so
        the only way to reach this guard is a module appending to the inherited private
        tally directly — which is exactly the laundering vector the guard exists to close:
        the record is counted as a failure and never folded into the visible skip tally."""
        completed = self._run_focused(
            'assert_eq "one" "x" "x"\n'
            "printf 'blocking-gate\\tsmuggled gate\\ta module may not do this\\n' "
            '>> "$SKIPS_FILE"\n',
        )
        self.assertNotEqual(completed.returncode, 0, completed.stdout)
        self.assertIn(
            "  - skip tally contained 1 non-host-capability record(s) "
            "(a module may not self-skip)",
            completed.stdout,
        )
        # Never laundered into a visible skip.
        self.assertNotIn("smuggled gate", completed.stdout)
        self.assertNotIn("skipped", completed.stdout)

    def test_focused_no_skip_summary_is_byte_identical(self) -> None:
        """AC4: with no skip the summary line is byte-identical to the pre-#887 shape."""
        completed = self._run_focused('assert_eq "one" "x" "x"\n')
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn(
            "Module synthetic: 1 passed, 0 failed", completed.stdout.splitlines()
        )
        # No trailing skip clause is added when nothing was skipped.
        self.assertNotIn("skipped", completed.stdout)

    def test_focused_skip_reason_cannot_trip_the_unrequested_bound_guard(self) -> None:
        """Injection guard (design decision, from #890): a module-authored skip reason
        containing the literal `BOUNDED smoke subset` must not reach the log the
        unrequested-bound guard scans, so it cannot forge an unrequested-bound failure."""
        completed = self._run_focused(
            'assert_eq "one" "x" "x"\n'
            'module_host_capability_skip "gated arm" '
            '"reads not denied; BOUNDED smoke subset appears in this reason" 2\n',
            minimum_assertions=3,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn(
            "Module synthetic: 1 passed, 0 failed, 1 skipped",
            completed.stdout.splitlines(),
        )
        self.assertNotIn("bounded a heavy unit", completed.stdout)

    def test_focused_skip_flows_through_the_shard_tally_as_a_skip(self) -> None:
        """AC3/AC6: driving the declaration boundary through the shard path, the combined
        aggregate reports a skip rather than a failure."""
        completed = self._run_focused(
            'assert_eq "one" "x" "x"\n'
            'module_host_capability_skip "gated arm" "host cannot deny reads" 2\n',
            minimum_assertions=3,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        log_path = None
        for line in completed.stdout.splitlines():
            if line.startswith("Log: "):
                log_path = line.removeprefix("Log: ")
        self.assertIsNotNone(log_path, completed.stdout)
        out_dir = self.root / "tally"
        extract = subprocess.run(
            [
                "python3",
                str(ROOT / "lib/test/shard-tally.py"),
                "extract",
                "--log",
                str(log_path),
                "--shard",
                "modules-x",
                "--rc",
                "0",
                "--tier",
                "modules",
                "--out",
                str(out_dir),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(extract.returncode, 0, extract.stdout + extract.stderr)
        summary = {
            key: value
            for key, _, value in (
                line.partition("\t")
                for line in (out_dir / "summary")
                .read_text(encoding="utf-8")
                .splitlines()
                if "\t" in line
            )
        }
        self.assertEqual(summary.get("skipped"), "1")
        self.assertEqual(
            (out_dir / "skips").read_text(encoding="utf-8").strip(),
            "gated arm [host-capability] — host cannot deny reads",
        )
        combine = subprocess.run(
            [
                "python3",
                str(ROOT / "lib/test/shard-tally.py"),
                "combine",
                "--expect",
                "1",
                str(out_dir),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(combine.returncode, 0, combine.stdout + combine.stderr)
        self.assertIn("1 passed, 0 failed, 1 skipped", combine.stdout)
        self.assertIn("  SKIP  gated arm [host-capability]", combine.stdout)

    def test_the_three_declaring_modules_run_green_through_the_focused_shard_path(
        self,
    ) -> None:
        """AC6: the three modules that declare a host-capability skip are each driven
        through the real focused runner (the #877 modules-* shard path) and run green.
        This proves they are shard-compatible under the new skip channel; the channel's
        FOLD behavior when an arm fires is driven end-to-end at the declaration boundary by
        `test_focused_skip_flows_through_the_shard_tally_as_a_skip` above. Forcing each
        module's own probe would mean reproducing the host condition (root / a
        mode-ignoring filesystem), which the AC forbids — so the boundary, not the host
        condition, is what the fold test exercises. A command-position raw `skip` in any
        module is separately barred tree-wide by `MODULE_SKIP_CALL_RE` (see the module
        self-skip scan)."""
        for module in (
            "regenerate-artifacts",
            "review-stall-backstop",
            "workflow-flight-recorder",
        ):
            environment = os.environ.copy()
            environment.pop("DEVFLOW_TEST_EXPERIMENT_FORCE_FAILURE", None)
            with tempfile.TemporaryDirectory() as log_dir:
                result = subprocess.run(
                    ["bash", str(RUNNER_SOURCE), "--log-dir", log_dir, module],
                    cwd=ROOT,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    f"{module}:\n" + result.stdout[-4000:] + result.stderr[-4000:],
                )
                self.assertRegex(
                    result.stdout,
                    rf"Module {re.escape(module)}: [0-9]+ passed, 0 failed",
                )


class PoolWidthTests(unittest.TestCase):
    def test_pool_width_honors_a_usable_export_and_caps_a_malformed_one(self) -> None:
        # The width decides how many whole module-runner processes this suite starts at
        # once, so each arm below is a real oversubscription or serialization it must
        # not choose. A PRESENT-but-unusable export takes the conservative cap; only an
        # ABSENT one means no coordinator and returns to the host CPU count.
        host = os.cpu_count() or 2
        cap = min(host, 2)
        cases = (
            # (exported value, expected width)
            (None, host),
            ("1", 1),
            ("2", 2),
            ("99", 99),
            ("  3  ", 3),
            ("0", cap),
            ("-3", cap),
            ("many", cap),
            ("", host),
        )
        for declared, expected in cases:
            with self.subTest(declared=declared):
                env = dict(os.environ)
                env.pop("DEVFLOW_POOL_WIDTH", None)
                if declared is not None:
                    env["DEVFLOW_POOL_WIDTH"] = declared
                with mock.patch.dict(os.environ, env, clear=True):
                    self.assertEqual(_pool_width(), expected)


class PoolMembershipCompletenessTests(unittest.TestCase):
    def test_every_test_py_on_disk_is_classified_exactly_once(self) -> None:
        violations = classify_test_suites(ROOT / "lib/test")
        self.assertEqual(violations, [], violations)

    def test_the_three_membership_lists_are_pairwise_disjoint(self) -> None:
        pooled = set(POOLED_SUITES)
        serial = set(SERIAL_BY_EXCLUSION_SUITES)
        module_driven = set(MODULE_DRIVEN_SUITES)
        self.assertEqual(pooled & serial, set())
        self.assertEqual(pooled & module_driven, set())
        self.assertEqual(serial & module_driven, set())
        # The pool opens exactly these — the membership list by construction.
        self.assertEqual(
            pooled,
            {
                "test_module_runner.py",
                "test_python_scripts.py",
                "test_python_scripts_part2.py",
                "test_python_scripts_part3.py",
                "test_python_scripts_part4.py",
            },
        )

    def test_a_planted_unclassified_suite_is_caught(self) -> None:
        # Positive control for the completeness claim: a throwaway test_*.py created
        # under a scratch directory the discovery function is pointed at (never inside
        # lib/test/) must be reported unclassified, proving the cross-check would fail
        # RED on a newly-added suite nobody routed into a category.
        with tempfile.TemporaryDirectory() as scratch:
            for name in (
                POOLED_SUITES + SERIAL_BY_EXCLUSION_SUITES + MODULE_DRIVEN_SUITES
            ):
                (Path(scratch) / name).write_text("", encoding="utf-8")
            (Path(scratch) / "test_planted_zzz.py").write_text("", encoding="utf-8")
            violations = classify_test_suites(scratch)
            self.assertTrue(
                any("test_planted_zzz.py" in v for v in violations), violations
            )

    def test_module_harness_installs_no_exit_trap(self) -> None:
        # issue #720: the pool lives in lib/test/module-harness.sh, so run.sh's
        # single-EXIT-trap scan (which reads run.sh source only) cannot see a
        # `trap … EXIT` added inside a pool function — and the runtime pool-trap
        # assertion in run.sh deliberately cannot inspect EXIT (bash resets a
        # subshell's inherited EXIT trap on entry). Scan module-harness.sh's own
        # source for any EXIT-trap installer so a future `trap _pool_cleanup EXIT`
        # inside the pool, which would silently displace run.sh's _suite_cleanup at
        # runtime, is caught structurally. Strip+comment-skip mirrors the run.sh scan.
        harness_text = HARNESS_SOURCE.read_text(encoding="utf-8")
        exit_traps = [
            stripped
            for stripped in (line.strip() for line in harness_text.splitlines())
            if not stripped.startswith("#")
            and re.match(r"^trap\s+\S.*\sEXIT$", stripped)
        ]
        self.assertEqual(exit_traps, [], f"module-harness.sh installs an EXIT trap: {exit_traps}")

    def test_pool_registers_live_child_before_clearing_launch_guard(self) -> None:
        # issue #720 launch-window race: in _devflow_pool_launch_suite the pooled child
        # must be entered into the run-wide live-child registry BEFORE the launch-window
        # guard (_DEVFLOW_POOL_LAUNCHING) is cleared, mirroring
        # devflow_run_full_suite_module's register-before-unguard ordering. If the clear
        # precedes the registration, a HUP/INT/TERM delivered in that window sees both
        # launch guards at 0 and the just-forked pid still absent from the registry, so the
        # signal handler terminates the other children and exits while this child is left
        # running orphaned against the checkout. This structurally pins the fixed ordering
        # so a re-inversion goes RED at the desk (the dedicated SIGINT test cannot hit the
        # narrow window deterministically).
        harness_text = HARNESS_SOURCE.read_text(encoding="utf-8")
        match = re.search(
            r"^_devflow_pool_launch_suite\(\) \{(.*?)^\}",
            harness_text,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(
            match, "could not locate _devflow_pool_launch_suite in module-harness.sh"
        )
        body = match.group(1)
        register_at = body.find("_devflow_register_live_child")
        clear_at = body.find("_DEVFLOW_POOL_LAUNCHING=0")
        self.assertNotEqual(
            register_at, -1, "register call missing from _devflow_pool_launch_suite"
        )
        self.assertNotEqual(
            clear_at, -1, "launch-guard clear missing from _devflow_pool_launch_suite"
        )
        self.assertLess(
            register_at,
            clear_at,
            "_devflow_pool_launch_suite clears _DEVFLOW_POOL_LAUNCHING before registering "
            "the live child — reopens the issue #720 launch-window orphan race",
        )

    def test_the_pool_is_invoked_only_from_run_sh(self) -> None:
        # The pool driver lives in module-harness.sh but is opened only by the full
        # suite: run-module.sh (the focused module runner) must never call it, and its
        # module-self-skip refusal stays intact.
        run_module_text = RUNNER_SOURCE.read_text(encoding="utf-8")
        self.assertNotIn("devflow_pool_open", run_module_text)
        self.assertIn(
            "modules may not self-skip (module contract)", run_module_text
        )
        run_text = (ROOT / "lib/test/run.sh").read_text(encoding="utf-8")
        self.assertIn("devflow_pool_open", run_text)
        self.assertIn("devflow_pool_join", run_text)

    def test_pooled_suites_constant_matches_the_run_sh_pool_invocation(self) -> None:
        # issue #720 review: POOLED_SUITES declares the pool's membership, but the
        # membership/disjointness checks above pin it only against the FILESYSTEM. That
        # leaves the removal direction unpinned — dropping a suite from the real
        # devflow_pool_open call while leaving it in POOLED_SUITES would pass cleanly, so
        # a suite could silently stop executing while the completeness guard stayed green.
        # Pin POOLED_SUITES to the ACTUAL wiring and assert set equality, so both drift
        # directions (add-to-the-invocation-only, remove-from-the-invocation-only) go RED.
        #
        # The invocation lives in module-harness.sh's devflow_python_suite_pool_open, not
        # in run.sh: the pooled suites now have their own CI shard, and run.sh and
        # lib/test/run-python-pool.sh both drive that ONE definition. Reading the real
        # definition is what keeps this a wiring pin rather than a prose pin — parsing
        # run.sh would now match nothing and pass vacuously in the direction that matters.
        # The triples are those whose script is a "$_pp_dir/test_*.py" path (the fixture
        # opens in run.sh's #720 test block use "$POOL720_FIX/..." / bare names, and are
        # in another file entirely, so both are excluded).
        harness_text = (ROOT / "lib/test/module-harness.sh").read_text(encoding="utf-8")
        triples = re.findall(
            r'"(test_[A-Za-z0-9_]+\.py)"\s+"\$_pp_dir/test_[A-Za-z0-9_]+\.py"\s+'
            r"(single-verdict|self-tally)",
            harness_text,
        )
        pooled_in_harness = {name for name, _mode in triples}
        self.assertEqual(
            pooled_in_harness,
            set(POOLED_SUITES),
            "POOLED_SUITES does not match devflow_python_suite_pool_open's real "
            f"devflow_pool_open invocation (module-harness.sh pools "
            f"{sorted(pooled_in_harness)}, constant declares {sorted(POOLED_SUITES)})",
        )


class RoutingClassificationAgainstTheTreeTests(unittest.TestCase):
    """issue #867: the three tuples are executable claims about routing.

    The issue-#720 cross-check above proves the classification is total and
    pairwise disjoint — a claim about the tuples and the filesystem, never about
    where a suite is actually driven from. `scan_routing_violations` closes that
    gap for the two tuples run.sh does not already pin (POOLED_SUITES is pinned
    by test_pooled_suites_constant_matches_the_run_sh_pool_invocation above,
    against the parsed devflow_pool_open triples — a stronger, invocation-shaped
    guarantee than a name scan, which is why no POOLED_SUITES assertion is added
    here).
    """

    @staticmethod
    def _scratch_tree(scratch, run_sh_text, module_texts, harness_text=""):
        """Materialize a scratch run.sh + modules dir + module-harness.sh.

        Returns the (run_sh, modules_dir, module_harness) triple to pass through
        to scan_routing_violations, so a planted violation never lands in the
        real lib/test/ tree.
        """
        root = Path(scratch)
        run_sh = root / "run.sh"
        run_sh.write_text(run_sh_text, encoding="utf-8")
        modules_dir = root / "modules"
        modules_dir.mkdir()
        for name, text in module_texts.items():
            (modules_dir / name).write_text(text, encoding="utf-8")
        module_harness = root / "module-harness.sh"
        module_harness.write_text(harness_text, encoding="utf-8")
        return run_sh, modules_dir, module_harness

    def setUp(self) -> None:
        # Every fixture below indexes [0] of both tuples; an emptied tuple would
        # otherwise surface as a bare IndexError with no diagnosis.
        self.assertTrue(MODULE_DRIVEN_SUITES, "MODULE_DRIVEN_SUITES is empty")
        self.assertTrue(
            SERIAL_BY_EXCLUSION_SUITES, "SERIAL_BY_EXCLUSION_SUITES is empty"
        )

    @classmethod
    def _clean_tree(cls, scratch):
        """Build a scratch tree the routing scan reports clean.

        The construction below is what makes it clean: it writes one module file
        per MODULE_DRIVEN_SUITES entry carrying that entry's invocation and
        nothing else, and one run.sh line per SERIAL_BY_EXCLUSION_SUITES entry.
        The planted-violation tests each mutate one of those from this baseline.
        """
        run_sh_text = "".join(
            f'  python3 "$LIB/test/{name}"\n' for name in SERIAL_BY_EXCLUSION_SUITES
        )
        module_texts = {
            f"owner-{index}.sh": f'  python3 "$LIB/test/{name}"\n'
            for index, name in enumerate(MODULE_DRIVEN_SUITES)
        }
        return cls._scratch_tree(scratch, run_sh_text, module_texts)

    def test_the_live_tree_satisfies_every_routing_claim(self) -> None:
        violations = scan_routing_violations()
        self.assertEqual(violations, [], violations)

    def test_a_module_driven_suite_carrying_several_occurrences_in_one_owner_is_clean(
        self,
    ) -> None:
        # The module-side claim counts distinct FILES, never occurrences: a module
        # may name the suite it drives on more than one line — the driver call plus,
        # say, a derived shard or capture path built from the same literal. An
        # occurrence-count assertion would be RED against a correct tree.
        with tempfile.TemporaryDirectory() as scratch:
            run_sh, modules_dir, harness = self._clean_tree(scratch)
            owner = modules_dir / "owner-0.sh"
            owner.write_text(
                owner.read_text(encoding="utf-8") * 3, encoding="utf-8"
            )
            self.assertEqual(
                scan_routing_violations(run_sh, modules_dir, harness), []
            )

    def test_a_planted_module_driven_invocation_in_run_sh_is_caught(self) -> None:
        offender = MODULE_DRIVEN_SUITES[0]
        with tempfile.TemporaryDirectory() as scratch:
            run_sh, modules_dir, harness = self._clean_tree(scratch)
            run_sh.write_text(
                run_sh.read_text(encoding="utf-8")
                + f'  python3 "$LIB/test/{offender}"\n',
                encoding="utf-8",
            )
            violations = scan_routing_violations(run_sh, modules_dir, harness)
            self.assertTrue(
                any(offender in v and "would execute twice" in v for v in violations),
                violations,
            )

    def test_a_planted_second_owning_module_is_caught(self) -> None:
        offender = MODULE_DRIVEN_SUITES[0]
        with tempfile.TemporaryDirectory() as scratch:
            run_sh, modules_dir, harness = self._clean_tree(scratch)
            (modules_dir / "interloper.sh").write_text(
                f'  python3 "$LIB/test/{offender}"\n', encoding="utf-8"
            )
            violations = scan_routing_violations(run_sh, modules_dir, harness)
            self.assertTrue(
                any(
                    offender in v and "driven by 2 module file(s)" in v
                    for v in violations
                ),
                violations,
            )

    def test_a_module_driven_suite_no_module_drives_is_caught(self) -> None:
        # The other half of the exactly-one claim: a suite routed to no module at
        # all is as broken as one routed to two.
        offender = MODULE_DRIVEN_SUITES[0]
        with tempfile.TemporaryDirectory() as scratch:
            run_sh, modules_dir, harness = self._clean_tree(scratch)
            (modules_dir / "owner-0.sh").unlink()
            violations = scan_routing_violations(run_sh, modules_dir, harness)
            self.assertTrue(
                any(
                    offender in v and "driven by 0 module file(s)" in v
                    for v in violations
                ),
                violations,
            )

    def test_a_removed_serial_invocation_is_caught(self) -> None:
        offender = SERIAL_BY_EXCLUSION_SUITES[0]
        with tempfile.TemporaryDirectory() as scratch:
            run_sh, modules_dir, harness = self._clean_tree(scratch)
            run_sh.write_text(
                run_sh.read_text(encoding="utf-8").replace(
                    f'  python3 "$LIB/test/{offender}"\n', ""
                ),
                encoding="utf-8",
            )
            violations = scan_routing_violations(run_sh, modules_dir, harness)
            self.assertTrue(
                any(
                    offender in v and "coverage is silently gone" in v
                    for v in violations
                ),
                violations,
            )

    def test_planted_bare_path_comments_leave_every_assertion_green(self) -> None:
        # The positive control for the matcher's shape. `create-issue-contract.sh`
        # mentions test_render_audit_prompt.py in comments while driving it
        # nowhere, so a basename matcher is RED against a correct tree — and it
        # would also let a comment satisfy the at-least-once direction, hiding a
        # deleted invocation. Comments naming a bare lib/test/<name> path must
        # neither satisfy nor violate any claim.
        module_driven = MODULE_DRIVEN_SUITES[0]
        serial = SERIAL_BY_EXCLUSION_SUITES[0]
        with tempfile.TemporaryDirectory() as scratch:
            run_sh, modules_dir, harness = self._clean_tree(scratch)
            run_sh.write_text(
                run_sh.read_text(encoding="utf-8")
                + f"# see lib/test/{module_driven} for the module-driven case\n",
                encoding="utf-8",
            )
            (modules_dir / "commentary.sh").write_text(
                f"# lib/test/{module_driven} is driven elsewhere\n"
                f"# lib/test/{serial} runs serially from run.sh\n",
                encoding="utf-8",
            )
            self.assertEqual(
                scan_routing_violations(run_sh, modules_dir, harness), []
            )

    def test_a_commented_out_driver_does_not_satisfy_any_claim(self) -> None:
        # Comment-blindness is the direction where a raw substring match fails
        # OPEN: a commented-out driver is the usual way an invocation gets
        # disabled, and if the comment still matched, the serial arm would report
        # coverage that is in fact gone, and a non-owning module would count as an
        # owner. Both halves are planted here in one tree.
        module_driven = MODULE_DRIVEN_SUITES[0]
        serial = SERIAL_BY_EXCLUSION_SUITES[0]
        with tempfile.TemporaryDirectory() as scratch:
            run_sh, modules_dir, harness = self._clean_tree(scratch)
            # Comment out the serial suite's only real invocation.
            run_sh.write_text(
                run_sh.read_text(encoding="utf-8").replace(
                    f'  python3 "$LIB/test/{serial}"\n',
                    f'  # python3 "$LIB/test/{serial}"\n',
                ),
                encoding="utf-8",
            )
            # And add a commented-out driver for a module-driven suite elsewhere,
            # plus one in run.sh — the false-POSITIVE channel, where a documentation
            # edit naming a module-driven suite must not raise "would execute twice".
            (modules_dir / "commented.sh").write_text(
                f'  # python3 "$LIB/test/{module_driven}"\n', encoding="utf-8"
            )
            run_sh.write_text(
                run_sh.read_text(encoding="utf-8")
                + f'  # python3 "$LIB/test/{module_driven}"  (module-driven; see its module)\n',
                encoding="utf-8",
            )
            violations = scan_routing_violations(run_sh, modules_dir, harness)
            self.assertTrue(
                any(
                    serial in v and "coverage is silently gone" in v
                    for v in violations
                ),
                violations,
            )
            self.assertFalse(any(module_driven in v for v in violations), violations)

    def test_a_trailing_comment_does_not_strip_the_invocation_it_follows(
        self,
    ) -> None:
        # strip_shell_comments promises whole-line-only stripping, and the serial
        # arm is where breaking that promise fails silently: weakening the
        # predicate to `"#" in line` would erase a live invocation carrying an
        # end-of-line comment and report its coverage as gone. Every other comment
        # test plants a whole-line comment, so only this one pins the promise.
        serial = SERIAL_BY_EXCLUSION_SUITES[0]
        with tempfile.TemporaryDirectory() as scratch:
            run_sh, modules_dir, harness = self._clean_tree(scratch)
            run_sh.write_text(
                run_sh.read_text(encoding="utf-8").replace(
                    f'  python3 "$LIB/test/{serial}"\n',
                    f'  python3 "$LIB/test/{serial}"  # drives the focused suite\n',
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                scan_routing_violations(run_sh, modules_dir, harness), []
            )

    def test_a_bare_basename_matcher_is_red_where_the_shape_matcher_is_green(
        self,
    ) -> None:
        # Mutation control for the matcher choice itself, run over a scratch tree
        # rather than the live one. A live-tree control would rest on comment
        # prose in an unrelated module surviving unedited, so an ordinary cleanup
        # there would fail this test with a message pointing at the wrong file.
        # Here the witness is planted: a non-owning module names the suite as a
        # bare path in prose, which the shape matcher ignores and a bare-basename
        # matcher counts as a second owner.
        offender = MODULE_DRIVEN_SUITES[0]
        with tempfile.TemporaryDirectory() as scratch:
            run_sh, modules_dir, harness = self._clean_tree(scratch)
            (modules_dir / "commentary.sh").write_text(
                f"  echo 'see lib/test/{offender} for the module-driven case'\n",
                encoding="utf-8",
            )
            self.assertEqual(
                scan_routing_violations(run_sh, modules_dir, harness), []
            )
            bare = scan_routing_violations(
                run_sh, modules_dir, harness, shape_for=lambda name: name
            )
            self.assertTrue(any(offender in v for v in bare), bare)

    def test_an_unreadable_run_sh_is_reported_and_no_claim_is_derived(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            _run_sh, modules_dir, harness = self._clean_tree(scratch)
            missing = Path(scratch) / "absent-run.sh"
            violations = scan_routing_violations(missing, modules_dir, harness)
            self.assertEqual(len(violations), 1, violations)
            self.assertIn("could not be read", violations[0])
            self.assertIn(str(missing), violations[0])

    def test_an_unreadable_module_file_is_reported_without_a_routing_accusation(
        self,
    ) -> None:
        # A truncated domain cannot support an ownership claim: the read failure
        # must be reported alone, never beside a "driven by 0 module file(s)"
        # accusation that would send the reader to edit a correct routing tuple.
        offender = MODULE_DRIVEN_SUITES[0]
        with tempfile.TemporaryDirectory() as scratch:
            run_sh, modules_dir, harness = self._clean_tree(scratch)
            owner = modules_dir / "owner-0.sh"
            owner.chmod(0o000)
            try:
                violations = scan_routing_violations(run_sh, modules_dir, harness)
            finally:
                # Restore inside the `with`, not via addCleanup: the scratch dir is
                # torn down at the end of this block, so a cleanup registered on the
                # test case would fire after the file is already gone.
                owner.chmod(0o600)
            if not violations:  # a privileged runner can read a 0o000 file
                self.skipTest("this host can read a mode-000 file; arm not drivable")
            self.assertTrue(
                all("could not be read" in v for v in violations), violations
            )
            self.assertFalse(
                any("expected exactly one" in v for v in violations), violations
            )
            self.assertTrue(any(str(owner) in v for v in violations), violations)
            self.assertFalse(any(offender in v for v in violations), violations)

    def test_an_unreadable_module_file_is_reported_privilege_independently(
        self,
    ) -> None:
        # The mode-000 arm above self-skips under a privileged runner (root in a
        # container is a common CI shape), which would leave the "read failure
        # reported alone" claim unasserted exactly there. Planting a DIRECTORY at
        # the module file's path raises IsADirectoryError for every user, so this
        # sibling holds the same claim with no privilege dependence.
        offender = MODULE_DRIVEN_SUITES[0]
        with tempfile.TemporaryDirectory() as scratch:
            run_sh, modules_dir, harness = self._clean_tree(scratch)
            owner = modules_dir / "owner-0.sh"
            owner.unlink()
            owner.mkdir()
            violations = scan_routing_violations(run_sh, modules_dir, harness)
            self.assertTrue(
                all("could not be read" in v for v in violations), violations
            )
            self.assertFalse(
                any("expected exactly one" in v for v in violations), violations
            )
            self.assertFalse(any(offender in v for v in violations), violations)

    def test_a_missing_modules_dir_is_reported_not_a_zero_owner_accusation(
        self,
    ) -> None:
        # The directory operand's own fail-closed arm. Path.glob() would have
        # returned an empty iterator here — no exception, no read failure — and
        # every module-driven suite would then be reported as owning zero files,
        # sending the reader to edit a correct routing tuple instead of to the
        # absent directory.
        offender = MODULE_DRIVEN_SUITES[0]
        with tempfile.TemporaryDirectory() as scratch:
            run_sh, _modules_dir, harness = self._clean_tree(scratch)
            absent = Path(scratch) / "absent-modules"
            violations = scan_routing_violations(run_sh, absent, harness)
            self.assertTrue(
                all("could not be enumerated" in v for v in violations), violations
            )
            self.assertTrue(any(str(absent) in v for v in violations), violations)
            self.assertFalse(
                any("expected exactly one" in v for v in violations), violations
            )
            self.assertFalse(any(offender in v for v in violations), violations)

    def test_a_missing_module_harness_is_reported_not_silently_dropped(self) -> None:
        # The harness goes through the same try/except as a module file rather
        # than a .exists() pre-test, so a renamed or unstattable path is a
        # reported read failure instead of a silently truncated scan domain.
        #
        # The fixture moves one suite's ownership onto the harness before
        # removing it, so the read-failure-alone assertion below is drivable: a
        # scan that reported accusations beside the read failure would accuse
        # that suite of owning zero files. Removing an unowning harness would
        # leave nothing for the assertion to catch.
        offender = MODULE_DRIVEN_SUITES[0]
        with tempfile.TemporaryDirectory() as scratch:
            run_sh, modules_dir, harness = self._clean_tree(scratch)
            (modules_dir / "owner-0.sh").unlink()
            harness.write_text(
                f'  python3 "$LIB/test/{offender}"\n', encoding="utf-8"
            )
            harness.unlink()
            violations = scan_routing_violations(run_sh, modules_dir, harness)
            self.assertEqual(len(violations), 1, violations)
            self.assertIn("could not be read", violations[0])
            self.assertIn(str(harness), violations[0])
            # Same read-failure-alone claim its two siblings assert: the truncated
            # domain must not also accuse a correct routing tuple.
            self.assertFalse(
                any("expected exactly one" in v for v in violations), violations
            )
            self.assertFalse(any(offender in v for v in violations), violations)

    def test_the_standalone_harness_counts_as_a_legitimate_single_owner(self) -> None:
        # The harness is part of the ownership domain, not merely read into it:
        # a suite whose only driver is module-harness.sh must satisfy the
        # exactly-one claim with no module file naming it at all.
        offender = MODULE_DRIVEN_SUITES[0]
        with tempfile.TemporaryDirectory() as scratch:
            run_sh, modules_dir, harness = self._clean_tree(scratch)
            (modules_dir / "owner-0.sh").unlink()
            harness.write_text(
                f'  python3 "$LIB/test/{offender}"\n', encoding="utf-8"
            )
            self.assertEqual(
                scan_routing_violations(run_sh, modules_dir, harness), []
            )

    def test_a_non_utf8_module_file_is_reported_as_a_read_failure(self) -> None:
        # read_text(encoding="utf-8") raises UnicodeDecodeError — a ValueError,
        # not an OSError — so an OSError-only handler would let a non-UTF-8 body
        # escape the "any read failure" contract as an uncaught crash.
        offender = MODULE_DRIVEN_SUITES[0]
        with tempfile.TemporaryDirectory() as scratch:
            run_sh, modules_dir, harness = self._clean_tree(scratch)
            owner = modules_dir / "owner-0.sh"
            owner.write_bytes(b'  python3 "$LIB/test/\xff\xfe"\n')
            violations = scan_routing_violations(run_sh, modules_dir, harness)
            self.assertTrue(
                all("could not be read" in v for v in violations), violations
            )
            self.assertTrue(any(str(owner) in v for v in violations), violations)
            self.assertFalse(any(offender in v for v in violations), violations)

    def test_a_non_utf8_run_sh_is_reported_as_a_read_failure(self) -> None:
        # The run.sh read has its own handler, so it needs its own arm.
        with tempfile.TemporaryDirectory() as scratch:
            run_sh, modules_dir, harness = self._clean_tree(scratch)
            run_sh.write_bytes(b'  python3 "$LIB/test/\xff\xfe"\n')
            violations = scan_routing_violations(run_sh, modules_dir, harness)
            self.assertEqual(len(violations), 1, violations)
            self.assertIn("could not be read", violations[0])
            self.assertIn(str(run_sh), violations[0])


if __name__ == "__main__":
    unittest.main()
