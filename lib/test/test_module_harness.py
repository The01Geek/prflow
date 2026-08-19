#!/usr/bin/env python3
"""Focused tests for the full-suite source boundary around test modules."""

# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Literal, TypeAlias
import unittest


ROOT = Path(__file__).resolve().parents[2]
RUN_SH = ROOT / "lib/test/run.sh"
SUMMARY_SH = ROOT / "lib/test/summary.sh"
HARNESS = ROOT / "lib/test/module-harness.sh"
RUNNER = ROOT / "lib/test/run-module.sh"
CREATE_ISSUE_MODULE = ROOT / "lib/test/modules/create-issue-contract.sh"

SignalBoundary: TypeAlias = Literal["focused", "full-suite"]
SignalName: TypeAlias = Literal["SIGHUP", "SIGINT", "SIGTERM"]
SignalScope: TypeAlias = Literal["parent-only", "module-only", "process-group"]
POSIX_SIGNAL_MATRIX_AVAILABLE = os.name == "posix" and all(
    hasattr(signal, name) for name in ("SIGHUP", "SIGINT", "SIGTERM")
) and hasattr(os, "killpg")


def signal_matrix_capability_skip_reason(available: bool) -> str | None:
    if available:
        return None
    return "POSIX signals and process groups are required"


@dataclass(frozen=True, kw_only=True)
class SignalRowState:
    process: subprocess.Popen[str]
    boundary: SignalBoundary
    controlled_tmp: Path
    runner_pid_file: Path
    module_pid_file: Path
    worker_pid_file: Path
    helper_pid_file: Path
    module_state_file: Path
    generic_scratch_file: Path
    runner_cleanup_marker: Path
    module_cleanup_marker: Path
    caller_exit_marker: Path
    results_file: Path
    failures_file: Path
    launch_window_file: Path


class FullSuiteModuleHarnessTests(unittest.TestCase):
    def _run_support_driver(self, driver_body: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            driver = root / "driver.sh"
            driver.write_text(
                "#!/usr/bin/env bash\n"
                f"RESULTS_FILE={root / 'results'}\n"
                f"MODULE_FAILURES_FILE={root / 'module-failures'}\n"
                f"SKIPS_FILE={root / 'skips'}\n"
                '> "$RESULTS_FILE"\n'
                '> "$MODULE_FAILURES_FILE"\n'
                '> "$SKIPS_FILE"\n'
                "assert_eq() {\n"
                '  if [ "$2" = "$3" ]; then printf "PASS\\n" >> "$RESULTS_FILE";\n'
                '  else printf "FAIL\\n" >> "$RESULTS_FILE"; fi\n'
                "}\n"
                f'. "{HARNESS}"\n'
                + driver_body,
                encoding="utf-8",
            )
            return subprocess.run(
                ["bash", str(driver)],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )

    def _run(
        self,
        module_body: str | None,
        *,
        initial_results: str = "",
        module_failures_are_directory: bool = False,
        minimum_assertions: int | str = 1,
        report_boundary_rc: bool = False,
        report_marker: bool = False,
        results_are_directory: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            module = root / "module.sh"
            if module_body is not None:
                module.write_text(module_body, encoding="utf-8")
            driver = root / "driver.sh"
            results_setup = (
                f"mkdir {root / 'results'}\n"
                if results_are_directory
                else f"printf '%b' {initial_results!r} > {str(root / 'results')!r}\n"
            )
            module_failures_setup = (
                'mkdir "$MODULE_FAILURES_FILE"\n'
                if module_failures_are_directory
                else '> "$MODULE_FAILURES_FILE"\n'
            )
            driver_text = (
                "#!/usr/bin/env bash\n"
                f"RESULTS_FILE={root / 'results'}\n"
                f"MODULE_FAILURES_FILE={root / 'module-failures'}\n"
                f"MODULE_MARKER={root / 'module-marker'}\n"
                + results_setup
                + module_failures_setup
                + f'. "{HARNESS}"\n'
                + f'if devflow_run_full_suite_module "{module}" "sample" {minimum_assertions}; '
                + "then BOUNDARY_RC=0; else BOUNDARY_RC=$?; fi\n"
                + ('echo "BOUNDARY_RC:$BOUNDARY_RC"\n' if report_boundary_rc else "")
                + (
                    'if [ -e "$MODULE_MARKER" ]; then echo MODULE_SOURCED; '
                    "else echo MODULE_NOT_SOURCED; fi\n"
                    if report_marker
                    else ""
                )
                + 'if [ -f "$RESULTS_FILE" ]; then cat "$RESULTS_FILE"; fi\n'
                + 'if [ -f "$MODULE_FAILURES_FILE" ]; then '
                + 'sed "s/^/BOUNDARY:/" "$MODULE_FAILURES_FILE"; fi\n'
            )
            driver.write_text(driver_text, encoding="utf-8")
            return subprocess.run(
                ["bash", str(driver)],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )

    def test_module_with_assertion_contributes_result_without_boundary_failure(self) -> None:
        result = self._run('printf "PASS\\n" >> "$RESULTS_FILE"\n')

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["PASS"])

    def test_full_suite_boundary_pins_the_heavy_unit_population_to_full(self) -> None:
        """Issue #890. devflow_run_full_suite_module assigns MODULE_HEAVY_UNIT_MODE=full
        unconditionally, and that assignment is the only thing standing between an
        inherited `smoke` and a silently reduced complete-suite run.

        It needs its own test because its failure mode is entirely invisible: the sharded
        driver folds either population into exactly one assert_eq, and `minimum_assertions`
        is a floor, so a dropped assignment moves neither the module tally nor the suite
        summary. Both halves are asserted — the default, and a hostile exported value —
        mirroring the coverage the focused runner's own unconditional assignment has in
        lib/test/test_module_runner.py's
        test_heavy_units_defaults_to_full_and_ignores_an_inherited_value."""
        for exported in (None, "smoke"):
            with self.subTest(exported=exported):
                environment = os.environ.copy()
                if exported is None:
                    environment.pop("MODULE_HEAVY_UNIT_MODE", None)
                else:
                    environment["MODULE_HEAVY_UNIT_MODE"] = exported
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    module = root / "module.sh"
                    module.write_text(
                        'printf "HEAVY-UNITS=%s\\n" "${MODULE_HEAVY_UNIT_MODE-unset}"\n'
                        'printf "PASS\\n" >> "$RESULTS_FILE"\n',
                        encoding="utf-8",
                    )
                    driver = root / "driver.sh"
                    driver.write_text(
                        "#!/usr/bin/env bash\n"
                        f'RESULTS_FILE="{root / "results"}"\n'
                        f'MODULE_FAILURES_FILE="{root / "failures"}"\n'
                        '> "$RESULTS_FILE"\n'
                        '> "$MODULE_FAILURES_FILE"\n'
                        "assert_eq() { :; }\n"
                        f'. "{HARNESS}"\n'
                        f'devflow_run_full_suite_module "{module}" "sample" 1\n',
                        encoding="utf-8",
                    )
                    result = subprocess.run(
                        ["bash", str(driver)],
                        cwd=root,
                        env=environment,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("HEAVY-UNITS=full", result.stdout, result.stdout + result.stderr)

    def test_rejected_relative_scratch_allocation_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            relative_tmp = root / "relative-tmp"
            relative_tmp.mkdir()
            module = root / "module.sh"
            module.write_text('printf "PASS\\n" >> "$RESULTS_FILE"\n', encoding="utf-8")
            driver = root / "driver.sh"
            driver.write_text(
                "#!/usr/bin/env bash\n"
                'export TMPDIR="relative-tmp"\n'
                'RESULTS_FILE="results"\n'
                'MODULE_FAILURES_FILE="failures"\n'
                '> "$RESULTS_FILE"\n'
                '> "$MODULE_FAILURES_FILE"\n'
                "assert_eq() { :; }\n"
                f'. "{HARNESS}"\n'
                f'devflow_run_full_suite_module "{module}" "sample" 1\n',
                encoding="utf-8",
            )
            result = subprocess.run(
                ["bash", str(driver)],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            leftovers = list(relative_tmp.glob("devflow-module-scratch.*"))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(leftovers, [])

    def test_preexisting_well_shaped_scratch_is_never_claimed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            controlled_tmp = root / "tmp"
            controlled_tmp.mkdir()
            victim = controlled_tmp / "devflow-module-scratch.ABC123"
            victim.mkdir()
            sentinel = victim / "sentinel"
            sentinel.write_text("keep\n", encoding="utf-8")
            fake_bin = root / "fake-bin"
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
            module = root / "module.sh"
            marker = root / "module-sourced"
            module.write_text(
                f'printf "sourced\\n" > "{marker}"\n'
                'printf "PASS\\n" >> "$RESULTS_FILE"\n',
                encoding="utf-8",
            )
            driver = root / "driver.sh"
            driver.write_text(
                "#!/usr/bin/env bash\n"
                f'export TMPDIR="{controlled_tmp}"\n'
                f'export PATH="{fake_bin}:$PATH"\n'
                f'RESULTS_FILE="{root / "results"}"\n'
                f'MODULE_FAILURES_FILE="{root / "failures"}"\n'
                '> "$RESULTS_FILE"\n'
                '> "$MODULE_FAILURES_FILE"\n'
                "assert_eq() { :; }\n"
                f'. "{HARNESS}"\n'
                f'devflow_run_full_suite_module "{module}" "sample" 1\n',
                encoding="utf-8",
            )

            result = subprocess.run(
                ["bash", str(driver)],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            sentinel_survived = sentinel.is_file()
            module_was_sourced = marker.exists()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("could not allocate private scratch root", result.stderr)
        self.assertTrue(sentinel_survived, result.stdout + result.stderr)
        self.assertFalse(module_was_sourced, result.stdout + result.stderr)

    def test_module_cannot_rewrite_prior_suite_verdicts(self) -> None:
        result = self._run(
            'printf "PASS\\n" > "$RESULTS_FILE"\n', initial_results="FAIL\n"
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["FAIL", "PASS"])

    def _run_bundle_driver(self, driver_body: str) -> subprocess.CompletedProcess[str]:
        """Like _run_support_driver, but the assert_eq stub records each assertion's
        LABEL. devflow_module_build_bundle's whole reason for existing over the
        monolith's _build_skill_bundle is that a bad member lands as a *named* RED
        assertion instead of an anonymous raw RESULTS_FILE write — a PASS/FAIL-only
        stub cannot tell those apart, so it could not bind that property."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            driver = root / "driver.sh"
            driver.write_text(
                "#!/usr/bin/env bash\n"
                f"RESULTS_FILE={root / 'results'}\n"
                '> "$RESULTS_FILE"\n'
                "assert_eq() {\n"
                '  if [ "$2" = "$3" ]; then printf "PASS|%s\\n" "$1" >> "$RESULTS_FILE";\n'
                '  else printf "FAIL|%s\\n" "$1" >> "$RESULTS_FILE"; fi\n'
                "}\n"
                f'. "{HARNESS}"\n'
                + driver_body
                + 'cat "$RESULTS_FILE"\n',
                encoding="utf-8",
            )
            return subprocess.run(
                ["bash", str(driver)],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )

    def test_build_bundle_concatenates_usable_members_without_asserting(self) -> None:
        """Issue #746: the clean path adds NO assertion — a module's registry floor is an
        equality check, so a builder that emitted a per-member PASS would inflate every
        bundle-building module's tally by its member count."""
        result = self._run_bundle_driver(
            'printf "alpha\\n" > a.md\n'
            'printf "beta\\n" > b.md\n'
            'devflow_module_build_bundle "fx" out.txt a.md b.md; echo "RC:$?"\n'
            'printf "BUNDLE:"; tr "\\n" "," < out.txt; printf "\\n"\n'
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RC:0", result.stdout)
        self.assertIn("BUNDLE:alpha,,beta,,", result.stdout)
        self.assertEqual(
            [line for line in result.stdout.splitlines() if "|" in line],
            [],
            "the clean path must add no assertion",
        )

    def test_build_bundle_reports_each_bad_member_by_name_and_keeps_going(self) -> None:
        """Issue #746: the failure channel is the reason this helper exists. Every
        unusable member must produce its OWN named RED — so one missing reference cannot
        mask the next — and the return must be non-zero. The unmatched-glob case arrives
        as the glob's own literal and is reported the same way, which is what makes an
        emptied phases/ directory a diagnosis rather than a silently thinner bundle."""
        result = self._run_bundle_driver(
            'printf "alpha\\n" > a.md\n'
            'printf "" > empty.md\n'
            'printf "omega\\n" > omega.md\n'
            'devflow_module_build_bundle "fx" out.txt a.md missing.md empty.md '
            'nomatch-*.md omega.md; echo "RC:$?"\n'
            'printf "BUNDLE:"; tr "\\n" "," < out.txt; printf "\\n"\n'
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RC:1", result.stdout)
        failures = [
            line for line in result.stdout.splitlines() if line.startswith("FAIL|")
        ]
        # Three distinct bad members, three distinct named REDs — not one aggregate.
        self.assertEqual(len(failures), 3, result.stdout)
        self.assertIn("FAIL|fx member usable: missing.md", failures)
        self.assertIn("FAIL|fx member usable: empty.md", failures)
        self.assertIn("FAIL|fx member usable: nomatch-*.md", failures)
        # A good member placed AFTER every bad one still lands, so the whole ordered
        # bundle is "alpha,,omega,,". This is what proves the loop runs to completion —
        # rc=1 plus three named REDs alone cannot tell "kept going and appended a later
        # good member" from "aborted after the last failure"; only a good member sitting
        # downstream of the failures can.
        self.assertIn("BUNDLE:alpha,,omega,,", result.stdout)

    def test_build_bundle_reports_unreadable_present_member_distinctly(self) -> None:
        """Issue #746: the `[ -r "$member" ]`-false-but-present case (a chmod 000 file)
        is its OWN arm of the member guard, distinct from missing/empty. Exercise it on
        its own so a regression dropping the readability check — while missing/empty still
        rejected — cannot ship green. Root bypasses the permission bits (`[ -r ]` stays
        true), so the file is readable there and this arm cannot fire; skip under root
        rather than assert a rejection that will not happen, mirroring the module-side
        locked-file arms."""
        if os.geteuid() == 0:
            self.skipTest("chmod 000 does not deny reads under root")
        result = self._run_bundle_driver(
            'printf "alpha\\n" > a.md\n'
            'printf "locked\\n" > locked.md\n'
            'chmod 000 locked.md\n'
            'devflow_module_build_bundle "fx" out.txt a.md locked.md; echo "RC:$?"\n'
            'chmod 644 locked.md\n'
            'printf "BUNDLE:"; tr "\\n" "," < out.txt; printf "\\n"\n'
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RC:1", result.stdout)
        failures = [
            line for line in result.stdout.splitlines() if line.startswith("FAIL|")
        ]
        # Present-but-unreadable is reported by name like any other unusable member —
        # and only that member, so the readability arm is exercised in isolation.
        self.assertEqual(failures, ["FAIL|fx member usable: locked.md"], result.stdout)
        # The bundle is exactly the good member: the unreadable file's content never
        # leaked in, and the earlier good member still landed.
        bundle_line = next(
            line for line in result.stdout.splitlines() if line.startswith("BUNDLE:")
        )
        self.assertEqual(bundle_line, "BUNDLE:alpha,,", result.stdout)

    def test_build_bundle_reports_unwritable_output_file(self) -> None:
        """Issue #746: the output-file-not-writable branch (`: > "$out"` fails) has its
        own named assertion and an early `return 1` before the member loop. Pin both: a
        directory can never be truncated as a file — not even by root — so this fixture is
        permission-bit-independent and needs no root skip. A regression dropping the
        `return 1` (letting the loop run against an unwritable target) or mislabeling the
        assertion would otherwise ship green."""
        result = self._run_bundle_driver(
            'printf "alpha\\n" > a.md\n'
            'mkdir out.dir\n'
            'devflow_module_build_bundle "fx" out.dir a.md; echo "RC:$?"\n'
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RC:1", result.stdout)
        failures = [
            line for line in result.stdout.splitlines() if line.startswith("FAIL|")
        ]
        # Exactly the writability assertion fires, and nothing else: the early return
        # means the member loop never runs, so there is no per-member assertion.
        self.assertEqual(failures, ["FAIL|fx output file writable"], result.stdout)

    def test_boundary_failure_is_folded_into_terminal_failure_count(self) -> None:
        result = self._run_support_driver(
            'MODULE="$RESULTS_FILE.missing"\n'
            'devflow_run_full_suite_module "$MODULE" "missing" 1\n'
            'FAIL="$(devflow_fold_module_failures 0)" || exit 3\n'
            'printf "terminal failures: %s\\n" "$FAIL"\n'
            '[ "$FAIL" -eq 0 ]\n'
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("terminal failures: 1", result.stdout)

    def test_module_failure_fold_fails_closed_when_tally_is_unreadable(self) -> None:
        result = self._run_support_driver(
            'rm -f "$MODULE_FAILURES_FILE"\n'
            'mkdir "$MODULE_FAILURES_FILE"\n'
            'if devflow_fold_module_failures 0; then echo FOLD_OPEN; else echo FOLD_CLOSED; fi\n'
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("FOLD_CLOSED", result.stdout.splitlines())

    def test_module_failure_fold_rejects_malformed_records(self) -> None:
        result = self._run_support_driver(
            'printf "PASS\\n" > "$MODULE_FAILURES_FILE"\n'
            'if devflow_fold_module_failures 0; then echo FOLD_OPEN; else echo FOLD_CLOSED; fi\n'
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("FOLD_CLOSED", result.stdout.splitlines())

    def test_module_failure_fold_rejects_a_non_numeric_operand(self) -> None:
        result = self._run_support_driver(
            'if devflow_fold_module_failures "abc"; then echo FOLD_OPEN; else echo FOLD_CLOSED; fi\n'
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("FOLD_CLOSED", result.stdout.splitlines())

    def test_focused_python_failure_prints_captured_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            failing_test = root / "failing.py"
            captured = root / "captured.out"
            failing_test.write_text(
                'raise RuntimeError("diagnostic sentinel")\n', encoding="utf-8"
            )
            result = self._run_support_driver(
                f'devflow_run_focused_python_test "focused fixture" "{failing_test}" '
                f'"{captured}"\n'
                'cat "$RESULTS_FILE"\n'
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RuntimeError: diagnostic sentinel", result.stdout)
        self.assertIn("FAIL", result.stdout.splitlines())

    def test_missing_module_records_failure_and_keeps_driver_alive(self) -> None:
        result = self._run(None)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BOUNDARY:FAIL", result.stdout.splitlines())
        self.assertIn("missing or unreadable", result.stderr)

    def test_module_exit_records_failure_and_keeps_driver_alive(self) -> None:
        result = self._run("exit 7\n")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BOUNDARY:FAIL", result.stdout.splitlines())
        self.assertIn("exited with status 7", result.stderr)

    def test_zero_assertion_module_records_failure(self) -> None:
        result = self._run(":\n")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BOUNDARY:FAIL", result.stdout.splitlines())
        self.assertIn("executed zero assertions", result.stderr)

    def test_module_below_assertion_floor_records_boundary_failure(self) -> None:
        result = self._run(
            'printf "PASS\\n" >> "$RESULTS_FILE"\n', minimum_assertions=2
        )

        self.assertIn("BOUNDARY:FAIL", result.stdout.splitlines())
        self.assertIn("executed 1 assertions; minimum is 2", result.stderr)

    def test_oversized_assertion_floor_fails_closed_without_arithmetic(self) -> None:
        result = self._run(
            'printf "PASS\\n" >> "$RESULTS_FILE"\n',
            minimum_assertions=10**100,
        )

        self.assertIn("BOUNDARY:FAIL", result.stdout.splitlines())
        self.assertIn("invalid minimum assertion count", result.stderr)

    def test_numeric_assertion_floor_bounds_fail_closed(self) -> None:
        for floor in (0, 1_000_001):
            with self.subTest(floor=floor):
                result = self._run(
                    'printf "PASS\\n" >> "$RESULTS_FILE"\n',
                    minimum_assertions=floor,
                )

                self.assertIn("BOUNDARY:FAIL", result.stdout.splitlines())
                self.assertIn("invalid minimum assertion count", result.stderr)

    def test_padded_zero_assertion_floor_fails_closed(self) -> None:
        result = self._run(
            'printf "PASS\\n" >> "$RESULTS_FILE"\n', minimum_assertions="00"
        )

        self.assertIn("BOUNDARY:FAIL", result.stdout.splitlines())
        self.assertIn("invalid minimum assertion count: 00", result.stderr)

    def test_module_cannot_sabotage_private_boundary_failure_channel(self) -> None:
        result = self._run(
            'if [ -n "${MODULE_FAILURES_FILE+x}" ]; then '
            'rm -f "$MODULE_FAILURES_FILE"; mkdir "$MODULE_FAILURES_FILE"; fi\n'
            'printf "PASS\\n" >> "$RESULTS_FILE"\nexit 7\n'
        )

        self.assertIn("BOUNDARY:FAIL", result.stdout.splitlines())
        self.assertIn("exited with status 7", result.stderr)

    def test_unavailable_boundary_failure_channel_returns_nonzero(self) -> None:
        result = self._run(
            "exit 7\n",
            module_failures_are_directory=True,
            report_boundary_rc=True,
        )

        self.assertIn("BOUNDARY_RC:1", result.stdout.splitlines())
        self.assertIn("could not record boundary failure", result.stderr)

    def test_unbound_variable_records_process_failure_even_for_permissive_caller(self) -> None:
        result = self._run('printf "%s\\n" "$UNBOUND_MODULE_VALUE"\n')

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("BOUNDARY:FAIL", result.stdout.splitlines())
        self.assertIn("exited with status", result.stderr)

    def test_unreadable_tally_before_module_execution_fails_closed(self) -> None:
        result = self._run(
            'printf "sourced\\n" > "$MODULE_MARKER"\n'
            'printf "PASS\\n" >> "$RESULTS_FILE"\n',
            report_marker=True,
            results_are_directory=True,
        )

        self.assertIn("result tally unreadable before module execution", result.stderr)
        self.assertIn("MODULE_NOT_SOURCED", result.stdout.splitlines())

    def test_unreadable_tally_after_module_execution_fails_closed(self) -> None:
        result = self._run(
            'printf "sourced\\n" > "$MODULE_MARKER"\n'
            'rm -f "$RESULTS_FILE"\nmkdir "$RESULTS_FILE"\n'
            'printf "PASS\\n" > "$RESULTS_FILE/record"\n',
            report_marker=True,
        )

        self.assertIn("result tally unreadable after module execution", result.stderr)
        self.assertIn("MODULE_SOURCED", result.stdout.splitlines())
        self.assertIn("BOUNDARY:FAIL", result.stdout.splitlines())

    def test_invalid_tally_before_module_execution_fails_closed(self) -> None:
        result = self._run(
            'printf "sourced\\n" > "$MODULE_MARKER"\n'
            'printf "PASS\\n" >> "$RESULTS_FILE"\n',
            initial_results="INVALID\n",
            report_marker=True,
        )

        self.assertIn("result tally unreadable before module execution", result.stderr)
        self.assertIn("MODULE_NOT_SOURCED", result.stdout.splitlines())

    def test_invalid_tally_after_module_execution_fails_closed(self) -> None:
        result = self._run(
            'printf "sourced\\n" > "$MODULE_MARKER"\n'
            'printf "INVALID\\n" >> "$RESULTS_FILE"\n',
            report_marker=True,
        )

        self.assertIn("result tally unreadable after module execution", result.stderr)
        self.assertIn("MODULE_SOURCED", result.stdout.splitlines())


class SignalCapabilityReportingTests(unittest.TestCase):
    def test_unavailable_matrix_has_a_host_capability_reason(self) -> None:
        self.assertIsNone(signal_matrix_capability_skip_reason(True))
        self.assertEqual(
            signal_matrix_capability_skip_reason(False),
            "POSIX signals and process groups are required",
        )


@unittest.skipUnless(
    POSIX_SIGNAL_MATRIX_AVAILABLE,
    "host-capability: POSIX signals and process groups are required",
)
class SignalCleanupMatrixTests(unittest.TestCase):
    """Signal cleanup is symmetric across focused and complete-suite boundaries."""

    signal_names: tuple[SignalName, ...] = ("SIGHUP", "SIGINT", "SIGTERM")
    scopes: tuple[SignalScope, ...] = (
        "parent-only",
        "module-only",
        "process-group",
    )
    boundaries: tuple[SignalBoundary, ...] = ("focused", "full-suite")

    @staticmethod
    def _pid_exists(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True

    def _wait_for_signal_state(
        self, process: subprocess.Popen[str], required: tuple[Path, ...]
    ) -> None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if all(path.is_file() and path.stat().st_size > 0 for path in required):
                return
            if process.poll() is not None:
                break
            time.sleep(0.02)
        missing = [
            str(path)
            for path in required
            if not path.is_file() or path.stat().st_size == 0
        ]
        self.fail(
            "signal fixture did not publish its PID/state files; "
            f"missing={missing}, rc={process.poll()}"
        )

    def _build_signal_fixture(self, row: Path) -> tuple[Path, Path, Path, Path]:
        repo = row / "repo"
        test_dir = repo / "lib/test"
        modules_dir = test_dir / "modules"
        scripts_dir = repo / "scripts"
        fake_bin = row / "fake-bin"
        modules_dir.mkdir(parents=True)
        scripts_dir.mkdir()
        fake_bin.mkdir()
        shutil.copy2(RUNNER, test_dir / "run-module.sh")
        shutil.copy2(HARNESS, test_dir / "module-harness.sh")

        sed_helper = fake_bin / "sed"
        sed_helper.write_text(
            "#!/usr/bin/env bash\n"
            '_generic_scratch="$(mktemp -d "${TMPDIR:-/tmp}/devflow-generic-module.XXXXXX")" '
            "|| exit 1\n"
            'printf "%s\\n" "$_generic_scratch" '
            '> "$DEVFLOW_TEST_GENERIC_SCRATCH_FILE"\n'
            'printf "%s\\n" "$DEVFLOW_MODULE_SCRATCH_ROOT" '
            '> "$DEVFLOW_TEST_MODULE_STATE_FILE"\n'
            'printf "%s\\n" "$$" > "$DEVFLOW_TEST_HELPER_PID_FILE"\n'
            'if [ "${DEVFLOW_TEST_SIGNAL_RESISTANT_HELPER:-0}" = "1" ]; then\n'
            "  trap '' HUP INT TERM\n"
            "fi\n"
            "while :; do sleep 1; done\n",
            encoding="utf-8",
        )
        sed_helper.chmod(0o755)

        module = modules_dir / "signal-create-issue.sh"
        module_text = CREATE_ISSUE_MODULE.read_text(encoding="utf-8")
        # Anchor on the implement-bundle assignment (a stable code line after _ci_tmp_root is
        # set), not its comment prose — the #1759 sweep reworded the old comment anchor.
        insertion_point = 'CI_IMPL_BUNDLE="$_ci_tmp_root/implement-skill-bundle.md"'
        signal_pause = (
            "# Test-only signal fixture: exercise a real foreground helper process.\n"
            'trap -p INT > "$DEVFLOW_TEST_MODULE_STATE_FILE.trap"\n'
            'DEVFLOW_MODULE_SCRATCH_ROOT="$_ci_tmp_root"\n'
            "export DEVFLOW_MODULE_SCRATCH_ROOT\n"
            '_ci_signal_fixture="$_ci_tmp_root/signal-source"\n'
            'printf \'operative\\n\' > "$_ci_signal_fixture"\n'
            'sed -E "s/operative//" "$_ci_signal_fixture" '
            '> "$_ci_signal_fixture.mutated"\n\n'
        )
        self.assertIn(insertion_point, module_text)
        module.write_text(
            module_text.replace(insertion_point, signal_pause + insertion_point, 1),
            encoding="utf-8",
        )
        registry = {
            "schema_version": 1,
            "workflows": {"placeholder": {}},
            "test_modules": {
                "signal-create-issue": {
                    "path": "lib/test/modules/signal-create-issue.sh",
                    "description": "signal cleanup fixture",
                    "minimum_assertions": 1,
                }
            },
        }
        registry_path = scripts_dir / "workflow-flight-recorder-registry.json"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")
        return repo, module, registry_path, fake_bin

    def _start_row(
        self,
        boundary: SignalBoundary,
        row: Path,
        *,
        resistant_helper: bool = False,
        launch_window: bool = False,
    ) -> SignalRowState:
        repo, module, registry, fake_bin = self._build_signal_fixture(row)
        controlled_tmp = row / "tmp"
        controlled_tmp.mkdir()
        runner_pid_file = row / "runner.pid"
        module_pid_file = row / "module.pid"
        worker_pid_file = row / "worker.pid"
        helper_pid_file = row / "helper.pid"
        module_state_file = row / "module.state"
        generic_scratch_file = row / "generic-scratch.state"
        runner_cleanup_marker = row / "runner-cleanup.marker"
        module_cleanup_marker = row / "module-cleanup.marker"
        caller_exit_marker = row / "caller-exit.marker"
        results_file = row / "suite-results"
        failures_file = row / "module-failures"
        launch_window_file = row / "launch-window"
        environment = os.environ.copy()
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
        environment.update(
            {
                "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
                "TMPDIR": str(controlled_tmp),
                "DEVFLOW_CREATE_ISSUE_CONTRACT_ROOT": str(ROOT),
                "DEVFLOW_TEST_RUNNER_PID_FILE": str(runner_pid_file),
                "DEVFLOW_TEST_MODULE_PID_FILE": str(module_pid_file),
                "DEVFLOW_TEST_MODULE_WORKER_PID_FILE": str(worker_pid_file),
                "DEVFLOW_TEST_HELPER_PID_FILE": str(helper_pid_file),
                "DEVFLOW_TEST_RUNNER_CLEANUP_MARKER": str(runner_cleanup_marker),
                "DEVFLOW_TEST_MODULE_CLEANUP_MARKER": str(module_cleanup_marker),
                "DEVFLOW_TEST_MODULE_STATE_FILE": str(module_state_file),
                "DEVFLOW_TEST_GENERIC_SCRATCH_FILE": str(generic_scratch_file),
                "DEVFLOW_TEST_SIGNAL_RESISTANT_HELPER": (
                    "1" if resistant_helper else "0"
                ),
            }
        )
        if launch_window:
            environment["DEVFLOW_TEST_LAUNCH_WINDOW_FILE"] = str(launch_window_file)

        if boundary == "focused":
            command = [
                "bash",
                str(repo / "lib/test/run-module.sh"),
                "--registry",
                str(registry),
                "--log-dir",
                str(row / "logs"),
                "signal-create-issue",
            ]
            cwd = repo
        elif boundary == "full-suite":
            driver = row / "full-suite-driver.sh"
            driver.write_text(
                "#!/usr/bin/env bash\n"
                "set -u\n"
                f'LIB="{ROOT / "lib"}"\n'
                f'RESULTS_FILE="{results_file}"\n'
                f'MODULE_FAILURES_FILE="{failures_file}"\n'
                f'CALLER_EXIT_MARKER="{caller_exit_marker}"\n'
                '> "$RESULTS_FILE"\n'
                '> "$MODULE_FAILURES_FILE"\n'
                'trap \'printf "caller-exit\\n" >> "$CALLER_EXIT_MARKER"\' EXIT\n'
                "assert_eq() {\n"
                '  if [ "$2" = "$3" ]; then printf "PASS\\n" >> "$RESULTS_FILE";\n'
                '  else printf "FAIL\\n" >> "$RESULTS_FILE"; fi\n'
                "}\n"
                f'. "{repo / "lib/test/module-harness.sh"}"\n'
                f'devflow_run_full_suite_module "{module}" "signal-create-issue" 1\n',
                encoding="utf-8",
            )
            command = ["bash", str(driver)]
            cwd = row
        else:
            self.fail(f"unsupported boundary: {boundary}")

        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        return SignalRowState(
            process=process,
            boundary=boundary,
            controlled_tmp=controlled_tmp,
            runner_pid_file=runner_pid_file,
            module_pid_file=module_pid_file,
            worker_pid_file=worker_pid_file,
            helper_pid_file=helper_pid_file,
            module_state_file=module_state_file,
            generic_scratch_file=generic_scratch_file,
            runner_cleanup_marker=runner_cleanup_marker,
            module_cleanup_marker=module_cleanup_marker,
            caller_exit_marker=caller_exit_marker,
            results_file=results_file,
            failures_file=failures_file,
            launch_window_file=launch_window_file,
        )

    @staticmethod
    def _read_pid(path: Path) -> int | None:
        if not path.is_file():
            return None
        value = path.read_text(encoding="utf-8").strip()
        return int(value) if value.isdigit() else None

    def _terminate_state(self, state: SignalRowState) -> None:
        for path in (state.worker_pid_file, state.module_pid_file):
            pid = self._read_pid(path)
            if pid is None:
                continue
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if state.process.poll() is None:
            try:
                os.killpg(state.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _assert_no_signal_leaks(self, state: SignalRowState) -> None:
        leftovers = sorted(path.name for path in state.controlled_tmp.iterdir())
        leaked = [
            name
            for name in leftovers
            if name.startswith(
                (
                    "devflow-module-results.",
                    "devflow-module-details.",
                    "devflow-module-tally.",
                    "devflow-module-scratch.",
                    "devflow-create-issue-contract.",
                    "devflow-module-mut.",
                )
            )
        ]
        self.assertEqual(leaked, [], f"cleanup artifacts survived: {leaked}")

    def _exercise_row(
        self,
        boundary: SignalBoundary,
        signal_name: SignalName,
        scope: SignalScope,
        *,
        resistant_helper: bool = False,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            row = Path(temporary_directory)
            state = self._start_row(
                boundary, row, resistant_helper=resistant_helper
            )
            process = state.process
            stdout = ""
            stderr = ""
            try:
                module_int_trap_file = Path(f"{state.module_state_file}.trap")
                self._wait_for_signal_state(
                    process,
                    (
                        state.runner_pid_file,
                        state.module_pid_file,
                        state.worker_pid_file,
                        state.helper_pid_file,
                        state.module_state_file,
                        state.generic_scratch_file,
                        module_int_trap_file,
                    ),
                )
                runner_pid = int(
                    state.runner_pid_file.read_text(encoding="utf-8").strip()
                )
                module_pid = int(
                    state.module_pid_file.read_text(encoding="utf-8").strip()
                )
                worker_pid = int(
                    state.worker_pid_file.read_text(encoding="utf-8").strip()
                )
                helper_pid = int(
                    state.helper_pid_file.read_text(encoding="utf-8").strip()
                )
                module_root = Path(
                    state.module_state_file.read_text(encoding="utf-8").strip()
                )
                generic_scratch = Path(
                    state.generic_scratch_file.read_text(encoding="utf-8").strip()
                )
                self.assertEqual(runner_pid, process.pid)
                self.assertNotEqual(module_pid, runner_pid)
                self.assertNotEqual(worker_pid, module_pid)
                self.assertNotIn(helper_pid, (runner_pid, module_pid, worker_pid))
                self.assertEqual(os.getpgid(module_pid), module_pid)
                self.assertEqual(os.getpgid(worker_pid), module_pid)
                self.assertEqual(os.getpgid(helper_pid), module_pid)
                module_int_trap = module_int_trap_file.read_text(encoding="utf-8")
                self.assertIn("SIGINT", module_int_trap)
                self.assertNotIn("trap -- '' SIGINT", module_int_trap)
                self.assertTrue(module_root.is_dir())
                self.assertTrue(generic_scratch.is_dir())

                signal_number = getattr(signal, signal_name)
                if scope == "parent-only":
                    os.kill(runner_pid, signal_number)
                elif scope == "module-only":
                    os.kill(module_pid, signal_number)
                elif scope == "process-group":
                    os.killpg(module_pid, signal_number)
                else:
                    self.fail(f"unsupported signal scope: {scope}")

                started = time.monotonic()
                bounded = True
                try:
                    stdout, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    bounded = False
                elapsed = time.monotonic() - started
                if not bounded:
                    self._terminate_state(state)
                    stdout, stderr = process.communicate(timeout=2)
                self.assertTrue(
                    bounded,
                    f"row exceeded cleanup bound: {boundary}/{signal_name}/{scope}\n"
                    f"stdout={stdout[-2000:]}\nstderr={stderr[-2000:]}",
                )
                self.assertLess(elapsed, 5)

                expected_rc = 1 if boundary == "focused" or scope == "parent-only" else 0
                self.assertEqual(
                    process.returncode,
                    expected_rc,
                    f"stdout={stdout[-2000:]}\nstderr={stderr[-2000:]}",
                )
                if boundary == "full-suite" and scope != "parent-only":
                    failure_records = state.failures_file.read_text(
                        encoding="utf-8"
                    ).splitlines()
                    self.assertGreaterEqual(len(failure_records), 1)
                    self.assertEqual(set(failure_records), {"FAIL"})

                deadline = time.monotonic() + 2
                supervised_pids = (module_pid, worker_pid, helper_pid)
                while any(self._pid_exists(pid) for pid in supervised_pids) and (
                    time.monotonic() < deadline
                ):
                    time.sleep(0.02)
                for pid in supervised_pids:
                    self.assertFalse(self._pid_exists(pid), f"subprocess survived: {pid}")
                self.assertFalse(module_root.exists(), "module scratch root survived")
                self.assertFalse(generic_scratch.exists(), "generic module scratch survived")
                self._assert_no_signal_leaks(state)
                self.assertEqual(
                    state.runner_cleanup_marker.read_text(
                        encoding="utf-8"
                    ).splitlines(),
                    ["runner-cleanup"],
                )
                self.assertEqual(
                    state.module_cleanup_marker.read_text(
                        encoding="utf-8"
                    ).splitlines(),
                    ["module-cleanup"],
                )
                if boundary == "full-suite":
                    self.assertEqual(
                        state.caller_exit_marker.read_text(
                            encoding="utf-8"
                        ).splitlines(),
                        ["caller-exit"],
                    )
            finally:
                self._terminate_state(state)
                if process.poll() is None:
                    process.communicate(timeout=2)

    def test_signal_cleanup_matrix(self) -> None:
        rows = [
            (boundary, signal_name, scope)
            for boundary in self.boundaries
            for signal_name in self.signal_names
            for scope in self.scopes
        ]
        self.assertEqual(len(rows), 18)
        for boundary, signal_name, scope in rows:
            with self.subTest(
                boundary=boundary,
                signal=signal_name,
                scope=scope,
            ):
                self._exercise_row(boundary, signal_name, scope)

    def test_signal_resistant_foreground_helper_is_escalated(self) -> None:
        for boundary, scope in (
            ("focused", "module-only"),
            ("focused", "parent-only"),
            ("full-suite", "parent-only"),
        ):
            with self.subTest(boundary=boundary, scope=scope):
                self._exercise_row(
                    boundary, "SIGTERM", scope, resistant_helper=True
                )

    def test_signal_during_launch_window_is_not_lost(self) -> None:
        for boundary in self.boundaries:
            with self.subTest(boundary=boundary):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    state = self._start_row(
                        boundary,
                        Path(temporary_directory),
                        launch_window=True,
                    )
                    try:
                        self._wait_for_signal_state(
                            state.process,
                            (state.runner_pid_file, state.launch_window_file),
                        )
                        runner_pid = int(
                            state.runner_pid_file.read_text(encoding="utf-8").strip()
                        )
                        os.kill(runner_pid, signal.SIGTERM)
                        stdout, stderr = state.process.communicate(timeout=5)
                        self.assertEqual(
                            state.process.returncode,
                            1,
                            f"stdout={stdout[-2000:]}\nstderr={stderr[-2000:]}",
                        )
                        self._assert_no_signal_leaks(state)
                        self.assertEqual(
                            state.runner_cleanup_marker.read_text(
                                encoding="utf-8"
                            ).splitlines(),
                            ["runner-cleanup"],
                        )
                        self.assertEqual(
                            state.module_cleanup_marker.read_text(
                                encoding="utf-8"
                            ).splitlines(),
                            ["module-cleanup"],
                        )
                    finally:
                        self._terminate_state(state)
                        if state.process.poll() is None:
                            state.process.communicate(timeout=2)

    def test_worker_stays_in_supervisor_group_with_a_controlling_tty(self) -> None:
        import pty

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            supervisor_pid_file = root / "supervisor.pid"
            worker_pid_file = root / "worker.pid"
            release = root / "release"
            driver = root / "driver.sh"
            driver.write_text(
                "#!/usr/bin/env bash\n"
                "set -m\n"
                f'. "{HARNESS}"\n'
                f'RELEASE="{release}"\n'
                'body() { while [ ! -e "$RELEASE" ]; do sleep 0.01; done; }\n'
                f'printf "%s\\n" "$BASHPID" > "{supervisor_pid_file}"\n'
                f'_devflow_supervise_module body "{supervisor_pid_file}" '
                f'"{worker_pid_file}"\n',
                encoding="utf-8",
            )
            child_pid, master_fd = pty.fork()
            if child_pid == 0:
                os.execvp("bash", ["bash", str(driver)])
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if (
                        supervisor_pid_file.is_file()
                        and worker_pid_file.is_file()
                        and worker_pid_file.stat().st_size > 0
                    ):
                        break
                    time.sleep(0.02)
                self.assertTrue(worker_pid_file.is_file(), "worker PID was not published")
                supervisor_pid = int(
                    supervisor_pid_file.read_text(encoding="utf-8").strip()
                )
                worker_pid = int(worker_pid_file.read_text(encoding="utf-8").strip())
                self.assertEqual(os.getpgid(supervisor_pid), supervisor_pid)
                self.assertEqual(os.getpgid(worker_pid), supervisor_pid)
            finally:
                release.touch()
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    waited, _ = os.waitpid(child_pid, os.WNOHANG)
                    if waited == child_pid:
                        break
                    time.sleep(0.02)
                else:
                    try:
                        os.killpg(child_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    os.waitpid(child_pid, 0)
                os.close(master_fd)

    def test_sigint_terminates_every_pooled_child(self) -> None:
        # issue #720: a SIGINT delivered to the suite's foreground process group must
        # terminate EVERY pooled python3 child — each launched into its own supervisor
        # process group — leaving nothing running against the checkout. This exercises
        # the generalized run-wide live-child registry: the single scalar module_pid
        # slot could terminate one group, so with three pooled children a single-slot
        # handler would orphan two. The handler forwards to every registered child.
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fixtures = root / "fix"
            ready = root / "ready"
            controlled_tmp = root / "tmp"
            for directory in (fixtures, ready, controlled_tmp):
                directory.mkdir()
            sleeper = fixtures / "sleeper.py"
            sleeper.write_text(
                "import os, time\n"
                f'open(os.path.join(r"{ready}", str(os.getpid())), "w").close()\n'
                "time.sleep(60)\n",
                encoding="utf-8",
            )
            driver = root / "pool-driver.sh"
            driver.write_text(
                "#!/usr/bin/env bash\n"
                "set -u\n"
                f'RESULTS_FILE="{root / "results"}"\n'
                f'MODULE_FAILURES_FILE="{root / "failures"}"\n'
                f'SKIPS_FILE="{root / "skips"}"\n'
                '> "$RESULTS_FILE"; > "$MODULE_FAILURES_FILE"; > "$SKIPS_FILE"\n'
                'assert_eq() { if [ "$2" = "$3" ]; then printf "PASS\\n" >> "$RESULTS_FILE"; '
                'else printf "FAIL\\n" >> "$RESULTS_FILE"; fi; }\n'
                f'. "{HARNESS}"\n'
                "DEVFLOW_POOL_WIDTH=3 devflow_pool_open \\\n"
                f'  s1 "{sleeper}" single-verdict \\\n'
                f'  s2 "{sleeper}" single-verdict \\\n'
                f'  s3 "{sleeper}" single-verdict\n'
                "devflow_pool_join\n",
                encoding="utf-8",
            )
            environment = os.environ.copy()
            environment["TMPDIR"] = str(controlled_tmp)
            process = subprocess.Popen(
                ["bash", str(driver)],
                cwd=root,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if len(list(ready.iterdir())) >= 3 or process.poll() is not None:
                        break
                    time.sleep(0.05)
                child_pids = sorted(
                    int(path.name) for path in ready.iterdir() if path.name.isdigit()
                )
                self.assertEqual(
                    len(child_pids),
                    3,
                    f"pooled children did not all start; pids={child_pids}, "
                    f"rc={process.poll()}",
                )
                for pid in child_pids:
                    self.assertTrue(
                        self._pid_exists(pid), f"child {pid} not running pre-signal"
                    )
                # Deliver SIGINT to the driver's foreground process group. The pooled
                # children sit in SEPARATE supervisor groups, so only the driver's
                # handler forwarding can reach them — which is the property under test.
                os.killpg(process.pid, signal.SIGINT)
                stdout, stderr = process.communicate(timeout=30)
                self.assertNotEqual(
                    process.returncode,
                    0,
                    f"stdout={stdout[-2000:]}\nstderr={stderr[-2000:]}",
                )
                grace = time.monotonic() + 8
                while time.monotonic() < grace and any(
                    self._pid_exists(pid) for pid in child_pids
                ):
                    time.sleep(0.05)
                survivors = [pid for pid in child_pids if self._pid_exists(pid)]
                self.assertEqual(
                    survivors, [], f"pooled children survived SIGINT: {survivors}"
                )
            finally:
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.communicate(timeout=3)
                for path in ready.iterdir():
                    if path.name.isdigit():
                        try:
                            os.kill(int(path.name), signal.SIGKILL)
                        except ProcessLookupError:
                            pass

    def test_full_suite_cleanup_failures_record_boundary_failure(self) -> None:
        for target, pattern in (
            ("scratch", "*devflow-module-scratch.*"),
            ("tally", "*devflow-module-tally.*"),
        ):
            with self.subTest(target=target):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    module = root / "module.sh"
                    module.write_text(
                        'printf "PASS\\n" >> "$RESULTS_FILE"\n', encoding="utf-8"
                    )
                    results = root / "results"
                    failures = root / "failures"
                    driver = root / "driver.sh"
                    driver.write_text(
                        "#!/usr/bin/env bash\n"
                        f'RESULTS_FILE="{results}"\n'
                        f'MODULE_FAILURES_FILE="{failures}"\n'
                        '> "$RESULTS_FILE"\n'
                        '> "$MODULE_FAILURES_FILE"\n'
                        "assert_eq() { :; }\n"
                        "rm() {\n"
                        f'  case "$*" in {pattern}) return 1 ;; esac\n'
                        '  command rm "$@"\n'
                        "}\n"
                        f'. "{HARNESS}"\n'
                        f'devflow_run_full_suite_module "{module}" "sample" 1\n',
                        encoding="utf-8",
                    )
                    process = subprocess.run(
                        ["bash", str(driver)],
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(process.returncode, 0)
                    self.assertEqual(
                        failures.read_text(encoding="utf-8").splitlines(), ["FAIL"]
                    )
                    self.assertIn("could not remove private", process.stderr)

    def test_missing_supervisor_pid_rendezvous_fails_boundedly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            driver = root / "driver.sh"
            driver.write_text(
                "#!/usr/bin/env bash\n"
                "body() { :; }\n"
                f'. "{HARNESS}"\n'
                f'_devflow_supervise_module body "{root / "missing.pid"}" '
                f'"{root / "worker.pid"}"\n',
                encoding="utf-8",
            )
            started = time.monotonic()
            process = subprocess.run(
                ["bash", str(driver)],
                text=True,
                capture_output=True,
                check=False,
                timeout=15,
            )
            elapsed = time.monotonic() - started

        self.assertEqual(process.returncode, 1)
        # The rendezvous is wall-clock bounded (module-harness.sh's
        # rendezvous_deadline_seconds=3, fired via SECONDS). Two guards, chosen so
        # neither is load-sensitive:
        #   * the LOWER bound catches a deadline collapsing to ~0 (e.g. SECONDS=0
        #     dropped, or -ge flipped) that would still exit rc 1 with the same
        #     message. It cannot flake under load, which only makes the run
        #     slower. 1.5 (not ~3) because SECONDS' integer granularity makes the
        #     real fire time [deadline-1, deadline), i.e. as low as ~2s + startup.
        #   * the subprocess TIMEOUT is the upper bound: it catches an unbounded
        #     rendezvous or a reintroduced fork-cost-sensitive bound (the #641
        #     regression class) by raising TimeoutExpired.
        # A tight upper assertion (the former `assertLess(elapsed, 4)` under
        # `timeout=5`) was deliberately removed: with only ~1s of slack above the
        # 3s deadline it failed on macOS under pool saturation, where process
        # spawn plus sourcing the harness eats that slack — a defect in the
        # assertion's budget, not in the bound under test, and the harness itself
        # already treats a pooled rendezvous timeout as transient (see
        # _devflow_pool_run_serial, issue #720). The residual accepted gap is a
        # modest deadline inflation (say 3s -> 10s), which no longer trips a
        # failure; the severe unbounded/fork-scaling forms still do.
        self.assertGreater(elapsed, 1.5)
        self.assertIn("supervisor PID rendezvous timed out", process.stderr)

    def test_full_suite_boundary_restores_caller_signal_traps(self) -> None:
        for initial_monitor in ("off", "on"):
            with self.subTest(initial_monitor=initial_monitor):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    root = Path(temporary_directory)
                    module = root / "module.sh"
                    marker = root / "marker"
                    monitor = root / "monitor"
                    module.write_text(
                        'printf "PASS\\n" >> "$RESULTS_FILE"\n', encoding="utf-8"
                    )
                    driver = root / "driver.sh"
                    driver.write_text(
                        "#!/usr/bin/env bash\n"
                        f'RESULTS_FILE="{root / "results"}"\n'
                        f'MODULE_FAILURES_FILE="{root / "failures"}"\n'
                        '> "$RESULTS_FILE"\n'
                        '> "$MODULE_FAILURES_FILE"\n'
                        f'MARKER="{marker}"\n'
                        f'MONITOR="{monitor}"\n'
                        + ("set -m\n" if initial_monitor == "on" else "set +m\n")
                        + 'case "$-" in *m*) printf "on\\n" ;; *) printf "off\\n" ;; esac > "$MONITOR"\n'
                        'trap \'printf "caller-exit\\n" >> "$MARKER"\' EXIT\n'
                        'trap \'printf "caller-hup\\n" >> "$MARKER"\' HUP\n'
                        'trap \'printf "caller-int\\n" >> "$MARKER"\' INT\n'
                        'trap \'printf "caller-term\\n" >> "$MARKER"\' TERM\n'
                        "assert_eq() { :; }\n"
                        f'. "{HARNESS}"\n'
                        f'devflow_run_full_suite_module "{module}" "sample" 1\n'
                        'case "$-" in *m*) printf "on\\n" ;; *) printf "off\\n" ;; esac >> "$MONITOR"\n'
                        'kill -s HUP "$$"\n'
                        'kill -s INT "$$"\n'
                        'kill -s TERM "$$"\n',
                        encoding="utf-8",
                    )
                    process = subprocess.run(
                        ["bash", str(driver)],
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    records = marker.read_text(encoding="utf-8").splitlines()
                    monitor_records = monitor.read_text(encoding="utf-8").splitlines()

                self.assertEqual(
                    process.returncode, 0, process.stdout + process.stderr
                )
                self.assertEqual(
                    records,
                    ["caller-hup", "caller-int", "caller-term", "caller-exit"],
                )
                self.assertEqual(monitor_records, [initial_monitor, initial_monitor])


class NamespacedModulePinHelperTests(unittest.TestCase):
    """AC11/AC12: the shared devflow_module_* pin/count/mutation helpers."""

    def _drive(self, body: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        # Runs BODY with RESULTS_FILE + a minimal assert_eq + the sourced harness,
        # under a controlled TMPDIR. Returns the process and the RESULTS_FILE
        # verdicts. (Tests that must inspect the TMPDIR after the run keep their own
        # driver open — a helper cannot outlive its TemporaryDirectory.)
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            controlled_tmp = root / "tmp"
            controlled_tmp.mkdir()
            results = root / "results"
            driver = root / "driver.sh"
            driver.write_text(
                "#!/usr/bin/env bash\n"
                f'RESULTS_FILE="{results}"\n'
                f'export TMPDIR="{controlled_tmp}"\n'
                '> "$RESULTS_FILE"\n'
                "assert_eq() {\n"
                '  if [ "$2" = "$3" ]; then printf "PASS\\n" >> "$RESULTS_FILE";\n'
                '  else printf "FAIL\\n" >> "$RESULTS_FILE"; fi\n'
                "}\n"
                f'. "{HARNESS}"\n'
                + body,
                encoding="utf-8",
            )
            process = subprocess.run(
                ["bash", str(driver)],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            verdicts = (
                results.read_text(encoding="utf-8").split()
                if results.exists()
                else []
            )
            return process, verdicts

    def test_pin_count_counts_fixed_string_occurrences(self) -> None:
        process, _ = self._drive(
            'F="$(mktemp)"; printf "alpha beta alpha\\nalpha\\n" > "$F"\n'
            'C="$(devflow_module_pin_count "alpha" "$F")"; RC=$?\n'
            'echo "COUNT:$C RC:$RC"\n'
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn("COUNT:3 RC:0", process.stdout)

    def test_pin_count_readable_zero_is_distinct_from_unestablished(self) -> None:
        # A readable file with zero matches returns "0" (rc 0); unreadable input
        # returns "unestablished" (rc 1), never "0" — so a zero-expected assertion
        # PASSES on the readable-zero and turns RED on the unestablished input.
        process, verdicts = self._drive(
            'F="$(mktemp)"; printf "nothing to see\\n" > "$F"\n'
            'Z="$(devflow_module_pin_count "absent" "$F")"; ZRC=$?\n'
            'echo "ZERO:$Z ZRC:$ZRC"\n'
            'assert_eq "readable zero-match" "0" "$Z"\n'
            'U="$(devflow_module_pin_count "absent" "/no/such/file")"; URC=$?\n'
            'echo "UNREAD:$U URC:$URC"\n'
            'assert_eq "unreadable is zero-RED" "0" "$U"\n'
        )
        self.assertIn("ZERO:0 ZRC:0", process.stdout)
        self.assertIn("UNREAD:unestablished URC:1", process.stdout)
        self.assertIn("unreadable file", process.stderr)
        # readable-zero PASSes the zero-expected assertion; unreadable turns it RED.
        self.assertEqual(verdicts, ["PASS", "FAIL"], process.stdout + process.stderr)

    def _drive_with_fake_python3(self, python3_body: str, expect_stderr: str) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            fake_bin = root / "fake-bin"
            fake_bin.mkdir()
            fake = fake_bin / "python3"
            fake.write_text("#!/usr/bin/env bash\n" + python3_body, encoding="utf-8")
            fake.chmod(0o755)
            results = root / "results"
            fixture = root / "fixture"
            fixture.write_text("literal literal\n", encoding="utf-8")
            driver = root / "driver.sh"
            driver.write_text(
                "#!/usr/bin/env bash\n"
                f'RESULTS_FILE="{results}"\n'
                f'export PATH="{fake_bin}:$PATH"\n'
                '> "$RESULTS_FILE"\n'
                "assert_eq() {\n"
                '  if [ "$2" = "$3" ]; then printf "PASS\\n" >> "$RESULTS_FILE";\n'
                '  else printf "FAIL\\n" >> "$RESULTS_FILE"; fi\n'
                "}\n"
                f'. "{HARNESS}"\n'
                f'C="$(devflow_module_pin_count "literal" "{fixture}")"; RC=$?\n'
                'echo "COUNT:$C RC:$RC"\n'
                'assert_eq "zero-expected under fake python3" "0" "$C"\n',
                encoding="utf-8",
            )
            process = subprocess.run(
                ["bash", str(driver)],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            verdicts = results.read_text(encoding="utf-8").split()
        # Every unestablished-count row: the count is "unestablished" (never 0), the
        # breadcrumb names the kind, and the zero-expected assertion turns RED.
        self.assertIn("COUNT:unestablished RC:1", process.stdout)
        self.assertIn(expect_stderr, process.stderr)
        self.assertEqual(verdicts, ["FAIL"], process.stdout + process.stderr)

    def test_pin_count_missing_or_failed_python3_is_unestablished(self) -> None:
        # "missing Python" (command-not-found rc) and an interpreter fault both
        # surface as a non-zero interpreter exit → unestablished, never 0.
        self._drive_with_fake_python3("exit 127\n", "python3 counter failed")
        self._drive_with_fake_python3("exit 1\n", "python3 counter failed")

    def test_pin_count_malformed_output_is_unestablished(self) -> None:
        self._drive_with_fake_python3(
            'printf "not-a-number\\n"\nexit 0\n', "malformed counter output"
        )

    def test_pin_unique_passes_on_exactly_one_and_reds_otherwise(self) -> None:
        process, verdicts = self._drive(
            'ONE="$(mktemp)"; printf "the marker line\\nother\\n" > "$ONE"\n'
            'devflow_module_pin_unique "unique present" "the marker line" "$ONE"\n'
            'TWO="$(mktemp)"; printf "dup\\ndup\\n" > "$TWO"\n'
            'devflow_module_pin_unique "duplicated -> RED" "dup" "$TWO"\n'
            'devflow_module_pin_unique "unreadable -> RED" "x" "/no/such/file"\n'
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(verdicts, ["PASS", "FAIL", "FAIL"], process.stdout + process.stderr)

    def test_pin_present_passes_on_one_or_more_and_reds_on_zero_or_unestablished(self) -> None:
        process, verdicts = self._drive(
            'F="$(mktemp)"; printf "recurs\\nrecurs\\nother\\n" > "$F"\n'
            'devflow_module_pin_present "recurring value present" "recurs" "$F"\n'
            'devflow_module_pin_present "single present" "other" "$F"\n'
            'devflow_module_pin_present "absent -> RED" "nope" "$F"\n'
            'devflow_module_pin_present "unreadable -> RED" "x" "/no/such/file"\n'
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(
            verdicts, ["PASS", "PASS", "FAIL", "FAIL"], process.stdout + process.stderr
        )

# ── Failure recap (issue #789) ────────────────────────────────────────────────
# The recap is `devflow_render_failure_recap` in lib/test/summary.sh and `record_fail` in
# lib/test/module-harness.sh — both real, sourceable shell functions, so these tests SOURCE
# the shipped files and call them, exactly as the issue-#456 tests drive
# devflow_render_test_summary. No source slicing, no extraction layer that a reformat could
# silently invalidate.
# The two spellings the shipped producers use to write the suite tally. Assembled from parts
# rather than written whole so this file's own source can never be mistaken for a producer by
# a future scanner over the corpus.
_TALLY_WRITE_ECHO = 'echo FAIL >> "$' + 'RESULTS_FILE"'
_TALLY_WRITE_PRINTF = "printf 'FAIL" + chr(92) + 'n' + "' >> \"$" + 'RESULTS_FILE"'
# The pooled worker's tally is a DIFFERENT target variable, so a scan keyed only on
# RESULTS_FILE is blind to the parent-written verdicts there.
_TALLY_WRITE_POOL = "printf 'FAIL" + chr(92) + 'n' + "' >> \"$" + 'tally"'
_TALLY_WRITES = (_TALLY_WRITE_ECHO, _TALLY_WRITE_PRINTF, _TALLY_WRITE_POOL)


class FailureRecapTests(unittest.TestCase):
    """AC6/AC7: the recap re-lists every FAIL identifier, on both streams, without
    disturbing a clean run's summary bytes or the suite's exit status."""

    def _drive(self, seed: str):
        """Run record_fail + the recap renderer over SEED, returning (rc, stdout, stderr)."""
        script = f"""
set -u
RESULTS_FILE="$(mktemp)"
SKIPS_FILE="$(mktemp)"
. "{SUMMARY_SH}"
# module-harness.sh defines record_fail; source only that function so the harness's own
# fixture-isolation preamble does not run in this micro-driver.
eval "$(sed -n '/^record_fail() {{/,/^}}/p' "{HARNESS}")"
# Fail loudly if the slice did not define the function: without this the zero-failure case
# would pass off a fixture that was never established (a missing sed, a reindented body).
type record_fail >/dev/null 2>&1 || {{ echo "record_fail was not defined by the slice" >&2; exit 99; }}
{seed}
PASS=$(grep -c '^PASS$' "$RESULTS_FILE" || true)
FAIL=$(grep -c '^FAIL$' "$RESULTS_FILE" || true)
SKIP=$(grep -c . "$SKIPS_FILE" || true)
echo
devflow_render_test_summary "$PASS" "$FAIL" "$SKIP" "$SKIPS_FILE"
devflow_render_failure_recap "$FAIL" "$RESULTS_FILE.names"
rm -f "$RESULTS_FILE" "$RESULTS_FILE.names" "$SKIPS_FILE"
[ "$FAIL" -eq 0 ]
"""
        proc = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, cwd=str(ROOT)
        )
        return proc.returncode, proc.stdout, proc.stderr

    @staticmethod
    def _recap_bullets(out: str) -> "list[str]":
        """The recap's bullet lines, VERBATIM (leading indent included).

        The indent is part of the asserted shape — it is what run-module.sh's recap uses and
        what makes the bullets read as a nested list under the header — so the lines are
        compared unstripped; only surrounding blank lines are dropped."""
        body = out.split("Failure recap:", 1)[1]
        return [line for line in body.split("\n") if line.strip()]

    @staticmethod
    def _fail(name: str, *, stderr: bool = False) -> str:
        detail = (
            f"printf '  FAIL  {name}\\n' >&2\n" if stderr else f"printf '  FAIL  {name}\\n'\n"
        )
        return f'echo FAIL >> "$RESULTS_FILE"\n{detail}record_fail "{name}"\n'

    def test_zero_failures_prints_no_recap_and_the_pre_change_summary(self):
        rc, out, _ = self._drive(":")
        self.assertEqual(rc, 0)
        self.assertNotIn("Failure recap", out)
        # Byte-identical to the pre-#789 terminal output for a clean run: the blank line the
        # caller echoes, then devflow_render_test_summary's own single summary line.
        self.assertEqual(out, "\n0 passed, 0 failed\n")

    def test_one_failure_is_listed_by_its_identifier(self):
        rc, out, _ = self._drive(self._fail("alpha assertion"))
        self.assertEqual(rc, 1)
        self.assertIn("Failure recap:", out)
        self.assertIn("  - alpha assertion\n", out)

    def test_many_failures_are_all_listed_in_order(self):
        seed = "".join(self._fail(n) for n in ("alpha", "beta", "gamma"))
        rc, out, _ = self._drive(seed)
        self.assertEqual(rc, 1)
        self.assertEqual(
            self._recap_bullets(out), ["  - alpha", "  - beta", "  - gamma"]
        )

    def test_a_stderr_only_failure_is_still_recapped_on_stdout(self):
        # The bi-stream case AC6 names: most of run.sh's FAIL sites print their detail to
        # stderr. The identifier record is stream-independent, so the recap must list a
        # stderr failure exactly like a stdout one.
        rc, out, err = self._drive(self._fail("stderr-only assertion", stderr=True))
        self.assertEqual(rc, 1)
        self.assertIn("  FAIL  stderr-only assertion", err)
        self.assertNotIn("  FAIL  stderr-only assertion", out)
        self.assertIn("  - stderr-only assertion\n", out)

    def test_a_failing_run_still_exits_nonzero_through_the_recap(self):
        # #528's verification-flight handle reads the suite's EXIT STATUS to record the
        # terminal state, so a recap that masked it would record `passed` for a RED suite.
        rc, out, _ = self._drive(self._fail("alpha"))
        self.assertIn("Failure recap:", out)
        self.assertNotEqual(rc, 0)

    def test_delimiter_bearing_identifier_stays_one_line(self):
        seed = (
            'echo FAIL >> "$RESULTS_FILE"\n'
            "record_fail \"$(printf 'tab\\there\\nand newline')\"\n"
        )
        rc, out, _ = self._drive(seed)
        self.assertEqual(rc, 1)
        self.assertEqual(self._recap_bullets(out), ["  - tab here and newline"])

    def test_empty_identifier_degrades_to_the_named_placeholder(self):
        rc, out, _ = self._drive('echo FAIL >> "$RESULTS_FILE"\nrecord_fail ""\n')
        self.assertEqual(rc, 1)
        self.assertIn("  - (unnamed check)\n", out)

    def test_a_tallied_failure_with_no_identifier_is_reported_as_incomplete(self):
        # The reconciliation the SKIP half already performs, applied to failures: a FAIL site
        # that tallied but recorded no identifier must not yield a short list that reads
        # complete. This is the shape that would otherwise hide exactly the failure a reader
        # is chasing.
        seed = self._fail("alpha") + 'echo FAIL >> "$RESULTS_FILE"\n'
        rc, out, _ = self._drive(seed)
        self.assertEqual(rc, 1)
        self.assertIn("  - alpha", out)
        self.assertIn("recorded no identifier", out)
        self.assertIn("the recap is INCOMPLETE", out)

    def test_an_absent_identifier_record_is_quantified_not_called_unavailable(self):
        # "Absent" and "unreadable" are different causes with different remedies, and a bare
        # "unavailable" would send the reader to debug the recap machinery while hiding how
        # much of the failure population went unnamed. Both arms state the count.
        seed = 'echo FAIL >> "$RESULTS_FILE"\nrm -f "$RESULTS_FILE.names"\n'
        rc, out, _ = self._drive(seed)
        self.assertEqual(rc, 1)
        self.assertIn("Failure recap:", out)
        self.assertIn("0 of 1 failure(s) recorded an identifier", out)
        self.assertIn("no record was written", out)

    def test_an_unreadable_identifier_record_names_that_distinct_cause(self):
        seed = (
            'echo FAIL >> "$RESULTS_FILE"\n'
            'record_fail "alpha"\n'
            'chmod 000 "$RESULTS_FILE.names"\n'
        )
        rc, out, _ = self._drive(seed)
        self.assertEqual(rc, 1)
        if "could be named" not in out:
            # A root-running environment can read a 000 file, so the arm is unreachable there
            # — assert the reachable half rather than encoding a false expectation.
            self.assertIn("  - alpha", out)
            return
        self.assertIn("0 of 1 failure(s) could be named", out)
        self.assertIn("exists but is unreadable", out)

    def test_every_tallied_fail_site_records_an_identifier(self):
        """A FAIL site that increments the tally but records no identifier makes the recap
        under-report — it would look complete while omitting the very failure the reader is
        chasing. The scanned population is every SHELL producer that can reach the suite
        tally, not just the two obvious files: `lib/test/modules/*.sh` write to the tally
        directly (their private tally is folded), and the harness writes a parent verdict to
        a pooled worker's `$tally`. Scanning one file for one spelling is precisely how the
        harness's own sites were missed in the first place, so the set is widened rather than
        the invariant narrowed. (`lib/test/test_python_scripts.py` is the one producer NOT
        scanned here: it is Python, cannot call the shell `record_fail`, and writes its own
        `.names` sibling — `test_python_pool_producer_records_identifiers` covers it.)"""
        sources = [RUN_SH, HARNESS] + sorted((ROOT / "lib/test/modules").glob("*.sh"))
        missing = []
        for source in sources:
            lines = source.read_text(encoding="utf-8").split("\n")
            for index, line in enumerate(lines):
                writes_tally = any(spelling in line for spelling in _TALLY_WRITES)
                if not writes_tally or line.lstrip().startswith("#"):
                    continue
                # The invariant is "a tally write is PAIRED with an identifier write", not
                # "calls record_fail": a site whose tally is a pooled worker's `$tally`
                # writes the sibling directly, because record_fail derives its path from
                # RESULTS_FILE and would put the name in the wrong file.
                window = lines[index : index + 3]
                paired = any(
                    "record_fail" in candidate or ".names" in candidate
                    for candidate in window
                )
                if not paired:
                    rel = source.relative_to(ROOT)
                    missing.append(f"{rel}:{index + 1}: {line.strip()}")
        self.assertEqual(missing, [], "tally writes with no identifier record")

    def test_python_pool_producer_records_identifiers(self):
        # test_python_scripts.py is the suite's LARGEST failure population and tallies from
        # Python, so it cannot call the shell record_fail. It writes the same `.names`
        # sibling directly; without that, ~1800 assertions would be counted and none named.
        source = (ROOT / "lib/test/test_python_scripts.py").read_text(encoding="utf-8")
        self.assertIn('_POOL_TALLY_FILE + ".names"', source)
        unnamed = [
            f"lib/test/test_python_scripts.py:{i + 1}: {line.strip()}"
            for i, line in enumerate(source.split("\n"))
            if '_pool_tally("FAIL"' in line and '_pool_tally("FAIL", ' not in line
        ]
        self.assertEqual(unnamed, [], "FAIL tally writes that pass no identifier")

    def test_a_module_failure_identifier_reaches_the_parent_recap(self):
        """End-to-end over the fold: a module's private tally is written under a REBOUND
        RESULTS_FILE, so its identifiers land in that private tally's sibling. Only the fold
        puts them in front of the reader — delete it and every module failure is counted and
        unnamed, which is the state this whole surface exists to remove."""
        with tempfile.TemporaryDirectory() as tmp:
            module = Path(tmp) / "sample.sh"
            module.write_text(
                'echo FAIL >> "$RESULTS_FILE"\n'
                'record_fail "inner module assertion alpha"\n'
                'echo FAIL >> "$RESULTS_FILE"\n'
                'record_fail "inner module assertion beta"\n'
                'echo PASS >> "$RESULTS_FILE"\n',
                encoding="utf-8",
            )
            script = f"""
set -u
RESULTS_FILE="$(mktemp)"
MODULE_FAILURES_FILE="$(mktemp)"
SKIPS_FILE="$(mktemp)"
. "{SUMMARY_SH}"
. "{HARNESS}"
devflow_run_full_suite_module "{module}" "sample" 1 >/dev/null 2>&1 || true
FAIL=$(grep -c '^FAIL$' "$RESULTS_FILE" || true)
devflow_render_failure_recap "$FAIL" "$RESULTS_FILE.names"
rm -f "$RESULTS_FILE" "$RESULTS_FILE.names" "$MODULE_FAILURES_FILE" "$SKIPS_FILE"
"""
            proc = subprocess.run(
                ["bash", "-c", script], capture_output=True, text=True, cwd=str(ROOT)
            )
            self.assertIn("  - inner module assertion alpha", proc.stdout, proc.stderr)
            # Two failures, so the fold's APPEND (not overwrite) semantics are exercised.
            self.assertIn("  - inner module assertion beta", proc.stdout, proc.stderr)
            self.assertNotIn("recorded no identifier", proc.stdout)

    def test_a_clean_module_produces_no_sibling_and_no_spurious_boundary_failure(self):
        # The fold is guarded on a non-empty sibling; an unguarded `cat` of a missing file
        # would make every CLEAN module emit a boundary FAIL.
        with tempfile.TemporaryDirectory() as tmp:
            module = Path(tmp) / "clean.sh"
            module.write_text('echo PASS >> "$RESULTS_FILE"\n', encoding="utf-8")
            script = f"""
set -u
RESULTS_FILE="$(mktemp)"
MODULE_FAILURES_FILE="$(mktemp)"
SKIPS_FILE="$(mktemp)"
. "{SUMMARY_SH}"
. "{HARNESS}"
devflow_run_full_suite_module "{module}" "clean" 1 >/dev/null 2>&1 || true
printf 'tally:%s names:%s boundary:%s\\n' \
  "$(grep -c '^FAIL$' "$RESULTS_FILE" || true)" \
  "$( [ -e "$RESULTS_FILE.names" ] && echo present || echo absent )" \
  "$(grep -c '^FAIL$' "$MODULE_FAILURES_FILE" || true)"
rm -f "$RESULTS_FILE" "$RESULTS_FILE.names" "$MODULE_FAILURES_FILE" "$SKIPS_FILE"
"""
            proc = subprocess.run(
                ["bash", "-c", script], capture_output=True, text=True, cwd=str(ROOT)
            )
            self.assertIn("tally:0", proc.stdout, proc.stderr)
            self.assertIn("boundary:0", proc.stdout, proc.stderr)


# ── Sharded focused-Python driver (issue #870) ────────────────────────────────
# devflow_run_sharded_python_test partitions ONE python3 unittest file across a bounded
# pool of concurrent selector processes and folds every shard into a SINGLE assert_eq, so
# the module's emitted tally is independent of the shard count (the coupled
# registry/run.sh-operand/tally triple needs no edit). These tests SOURCE the shipped
# module-harness.sh and drive the real function against synthetic unittest files, exactly
# as FailureRecapTests drives record_fail — no extraction layer to go stale.


class ShardedPythonTestDriverTests(unittest.TestCase):
    """AC1-AC5: one aggregate verdict whose count is width-independent, and every
    unit-level failure mode fails CLOSED."""

    @staticmethod
    def _suite_source(*, alpha: int, beta: int, fail_in: str | None = None) -> str:
        """A synthetic unittest file with two classes.

        `fail_in` names a test method that raises, so a planted failure can be steered
        into a specific class.
        """

        def methods(prefix: str, count: int) -> str:
            out = []
            for index in range(count):
                name = f"{prefix}_{index}"
                body = (
                    "        raise AssertionError('planted')\n"
                    if fail_in == name
                    else "        pass\n"
                )
                out.append(f"    def test_{name}(self):\n{body}")
            return "".join(out)

        return (
            "import unittest\n\n\n"
            "class AlphaTests(unittest.TestCase):\n"
            f"{methods('alpha', alpha)}\n\n"
            "class BetaTests(unittest.TestCase):\n"
            f"{methods('beta', beta)}\n\n"
            'if __name__ == "__main__":\n'
            "    unittest.main()\n"
        )

    def _drive(
        self,
        script_path: Path,
        *,
        width: str = "3",
        env_extra: str = "",
        mode: "str | None" = None,
    ) -> "tuple[str, str]":
        """Run the driver over SCRIPT_PATH, returning (VERDICT line, combined output).

        `mode` is the driver's optional fourth positional argument (issue #890). None
        omits it entirely, which is the shape every pre-#890 call site uses and must keep
        meaning `full`.
        """
        mode_argument = "" if mode is None else f' "{mode}"'
        shell = f"""
set -u
RESULTS_FILE="$(mktemp)"
MODULE_FAILURES_FILE="$(mktemp)"
SKIPS_FILE="$(mktemp)"
CAPTURE_DIR="$(mktemp -d)"
export DEVFLOW_POOL_WIDTH={width}
{env_extra}
assert_eq() {{
  if [ "$2" = "$3" ]; then printf "PASS\\n" >> "$RESULTS_FILE";
  else printf "FAIL\\n" >> "$RESULTS_FILE"; record_fail "$1"; fi
}}
. "{SUMMARY_SH}"
. "{HARNESS}"
devflow_run_sharded_python_test "sharded" "{script_path}" "$CAPTURE_DIR"{mode_argument}
printf 'VERDICT pass:%s fail:%s\\n' \
  "$(grep -c '^PASS$' "$RESULTS_FILE" || true)" \
  "$(grep -c '^FAIL$' "$RESULTS_FILE" || true)"
rm -rf "$CAPTURE_DIR"
rm -f "$RESULTS_FILE" "$RESULTS_FILE.names" "$MODULE_FAILURES_FILE" "$SKIPS_FILE"
"""
        proc = subprocess.run(
            ["bash", "-c", shell], capture_output=True, text=True, cwd=str(ROOT)
        )
        output = proc.stdout + proc.stderr
        self.assertIn("VERDICT ", proc.stdout, output)
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("VERDICT ")][-1]
        return line, output

    def _write_suite(self, tmp: str, *, source: "str | None" = None, **kwargs) -> Path:
        path = Path(tmp) / "synthetic_suite.py"
        path.write_text(
            source if source is not None else self._suite_source(**kwargs),
            encoding="utf-8",
        )
        return path

    def test_a_green_file_yields_exactly_one_pass_regardless_of_width(self):
        # AC1 (green half) + AC5: the tally must not scale with the concurrency width, or
        # the module's assertion floor moves and the coupled triple breaks. The executed
        # count is asserted here too, so the count check has an observed passing arm and
        # is not RED-only.
        with tempfile.TemporaryDirectory() as tmp:
            suite = self._write_suite(tmp, alpha=5, beta=4)
            for width in ("1", "3", "9"):
                with self.subTest(width=width):
                    verdict, output = self._drive(suite, width=width)
                    self.assertEqual(verdict, "VERDICT pass:1 fail:0", output)
                    self.assertIn("executed 9 test(s)", output)

    def test_smoke_mode_runs_one_test_per_class_and_says_so(self):
        # Issue #890. The bounded population is what removes the monolith shard's second
        # execution of the pin-corpus block, so three things are asserted together: the
        # enumeration collapses to one selector per CLASS (not to a fixed count, and not
        # to one selector overall — every class is still entered), the aggregate verdict
        # is still exactly one PASS so the module's assertion tally does not move, and the
        # tally line carries the bound. That last one is what a caller keys on to prove it
        # got the bounded path rather than a silent fallback to the full population.
        with tempfile.TemporaryDirectory() as tmp:
            suite = self._write_suite(tmp, alpha=5, beta=4)
            verdict, output = self._drive(suite, mode="smoke")
            self.assertEqual(verdict, "VERDICT pass:1 fail:0", output)
            self.assertIn("executed 2 test(s)", output)
            self.assertIn("(2 enumerated,", output)
            self.assertIn(
                "BOUNDED smoke subset — the full population did NOT run", output
            )

    def test_smoke_mode_still_fails_closed_on_a_failure_inside_the_bounded_subset(self):
        # A bounded run is not a weaker verdict for what it does run. Without this,
        # "bounded" could quietly mean "unfailable".
        #
        # The two planted failures are what make the per-CLASS property observable, and
        # the second one is load-bearing: the count assertions in the test above are
        # satisfied by "the first two selectors overall" just as well as by "the first of
        # each class", so a regression to a flat head-N bound would keep them green while
        # silently never entering the later classes. `beta_0` is the first test of the
        # SECOND class — a test a head-2 bound would never reach — so a run that goes RED
        # on it can only have entered BetaTests.
        for planted in ("alpha_0", "beta_0"):
            with self.subTest(planted=planted):
                with tempfile.TemporaryDirectory() as tmp:
                    suite = self._write_suite(tmp, alpha=5, beta=4, fail_in=planted)
                    verdict, output = self._drive(suite, mode="smoke")
                    self.assertEqual(verdict, "VERDICT pass:0 fail:1", output)
                    self.assertIn("planted", output)

    def test_an_absent_or_empty_mode_runs_the_full_population(self):
        # The default direction is the safe one: a caller that names no mode, or names an
        # empty one (an unset variable forwarded into the argument list — the shape the
        # shipped call site uses), gets EVERY test and no bound clause. A two-per-class
        # population is enough to separate `full` from `smoke` here; the full-population
        # count at several widths is already covered by the green-file test above.
        with tempfile.TemporaryDirectory() as tmp:
            suite = self._write_suite(tmp, alpha=2, beta=2)
            for mode in (None, "", "full"):
                with self.subTest(mode=mode):
                    verdict, output = self._drive(suite, mode=mode)
                    self.assertEqual(verdict, "VERDICT pass:1 fail:0", output)
                    self.assertIn("executed 4 test(s)", output)
                    self.assertNotIn("BOUNDED", output)

    def test_an_unrecognized_mode_fails_closed_without_running_anything(self):
        # The failure mode that matters is a MISSPELLED bound — `smoak`, `Smoke`, a stale
        # spelling from an older call site. It must not fall through to either population:
        # falling through to full would hide the defect behind a green run, and falling
        # through to bounded would silently drop coverage. It refuses instead, naming the
        # value, and executes nothing at all (asserted by the absence of any tally line,
        # not merely by the verdict).
        with tempfile.TemporaryDirectory() as tmp:
            suite = self._write_suite(tmp, alpha=5, beta=4)
            for mode in ("smoak", "Smoke", "1"):
                with self.subTest(mode=mode):
                    verdict, output = self._drive(suite, mode=mode)
                    self.assertEqual(verdict, "VERDICT pass:0 fail:1", output)
                    self.assertIn(
                        "devflow shard driver: unrecognized population mode "
                        f"{mode} (expected full or smoke)",
                        output,
                    )
                    self.assertNotIn("executed ", output)

    def test_a_single_failing_test_turns_the_aggregate_red_and_echoes_its_capture(self):
        # AC1 (red half) + AC2: a nonzero unit exit is not swallowed by the aggregation,
        # and the failing unit's captured traceback reaches the reader the way
        # devflow_run_focused_python_test's own indented echo does.
        with tempfile.TemporaryDirectory() as tmp:
            suite = self._write_suite(tmp, alpha=5, beta=4, fail_in="beta_2")
            verdict, output = self._drive(suite)
            self.assertEqual(verdict, "VERDICT pass:0 fail:1", output)
            self.assertIn("planted", output)

    def test_an_unstartable_unit_is_a_failure_not_a_passing_unit(self):
        # AC4: a unit process that cannot start must fail CLOSED. Only the UNIT
        # interpreter is steered to a name that does not exist — the enumeration still
        # runs under the real python3, so this arm proves the spawn failure itself is
        # caught rather than being masked by an unestablished test count.
        with tempfile.TemporaryDirectory() as tmp:
            suite = self._write_suite(tmp, alpha=3, beta=3)
            verdict, output = self._drive(
                suite,
                env_extra=(
                    "export DEVFLOW_TEST_SHARD_PYTHON="
                    "/nonexistent/devflow-870-no-such-interpreter\n"
                ),
            )
            self.assertEqual(verdict, "VERDICT pass:0 fail:1", output)

    def test_a_killed_unit_is_a_failure(self):
        # AC4: a unit killed mid-flight exits 128+signal with no `Ran N tests` line; it
        # must not be read as a unit that simply had nothing to run.
        with tempfile.TemporaryDirectory() as tmp:
            suite = self._write_suite(
                tmp,
                source=(
                    "import os\nimport signal\nimport unittest\n\n\n"
                    "class AlphaTests(unittest.TestCase):\n"
                    "    def test_suicide(self):\n"
                    "        os.kill(os.getpid(), signal.SIGKILL)\n\n"
                    "    def test_ok(self):\n        pass\n\n"
                    'if __name__ == "__main__":\n    unittest.main()\n'
                ),
            )
            verdict, output = self._drive(suite, width="1")
            self.assertEqual(verdict, "VERDICT pass:0 fail:1", output)

    def test_an_unestablished_test_count_fails_closed(self):
        # AC3 (fail-closed half): a file the enumerator cannot load yields no trustworthy
        # total, so the driver must report FAIL rather than a vacuous green.
        with tempfile.TemporaryDirectory() as tmp:
            suite = self._write_suite(
                tmp, source="import nonexistent_module_for_870\n"
            )
            verdict, output = self._drive(suite)
            self.assertEqual(verdict, "VERDICT pass:0 fail:1", output)

    def test_a_file_with_no_tests_fails_closed(self):
        # A zero-test enumeration is indistinguishable from a schedule that dropped
        # everything, so it is never a green pass. Which arm catches it is asserted by
        # breadcrumb rather than left to inference: the ENUMERATOR refuses an empty
        # selector list with a nonzero exit, so the driver's own `reported zero tests`
        # backstop is shadowed and is documented at its site as covering only the
        # residual exit-0-with-nothing-readable shape.
        with tempfile.TemporaryDirectory() as tmp:
            suite = self._write_suite(tmp, source="import unittest\n")
            verdict, output = self._drive(suite)
            self.assertEqual(verdict, "VERDICT pass:0 fail:1", output)
            self.assertIn("no tests were enumerated in", output)
            self.assertIn("the unsharded test count could not be established", output)

    def test_a_collection_time_load_error_fails_closed(self):
        # The enumerator's `loader.errors` branch. `loadTestsFromModule` swallows a
        # raising `load_tests` into an error entry plus a placeholder test rather than
        # propagating, so the module imports cleanly and only this branch stands between
        # a collection failure and a total that silently omits the unloadable tests.
        with tempfile.TemporaryDirectory() as tmp:
            suite = self._write_suite(
                tmp,
                source=(
                    "import unittest\n\n\n"
                    "class AlphaTests(unittest.TestCase):\n"
                    "    def test_ok(self):\n        pass\n\n\n"
                    "def load_tests(loader, tests, pattern):\n"
                    "    raise RuntimeError('devflow-870 collection boom')\n\n"
                    'if __name__ == "__main__":\n    unittest.main()\n'
                ),
            )
            verdict, output = self._drive(suite)
            self.assertEqual(verdict, "VERDICT pass:0 fail:1", output)
            self.assertIn("devflow-870 collection boom", output)
            self.assertIn("the unsharded test count could not be established", output)

    def test_a_unit_dropped_from_dispatch_only_is_a_failure(self):
        # AC4/AC3 boundary. DROP_ONE elides one unit from DISPATCH while the collection
        # loop still visits it, so the shortfall surfaces as a unit that recorded no exit
        # status — NOT as the count comparison, which is `[ -z "$failure" ]`-guarded and
        # therefore never reached here. The breadcrumb is asserted so this test cannot
        # silently drift onto a different arm.
        with tempfile.TemporaryDirectory() as tmp:
            suite = self._write_suite(tmp, alpha=5, beta=4)
            verdict, output = self._drive(
                suite, env_extra="export DEVFLOW_TEST_SHARD_DROP_ONE=1\n"
            )
            self.assertEqual(verdict, "VERDICT pass:0 fail:1", output)
            self.assertIn("recorded no exit status", output)

    def test_a_schedule_that_drops_work_turns_the_aggregate_red(self):
        # AC3 (count-check half), the arm DROP_ONE cannot reach — the classic sharding
        # regression: the scheduler silently omits work and the suite goes green having
        # tested less. SKIP_ONE elides one unit from BOTH loops, so every VISITED unit
        # exits 0 and reports exactly 1, `failure` is still empty, and the
        # dispatched/executed-vs-enumerated comparison is the ONLY thing standing between
        # this run and a vacuous pass. Asserting its distinct breadcrumb is what makes a
        # regression that breaks only that comparison observable.
        with tempfile.TemporaryDirectory() as tmp:
            suite = self._write_suite(tmp, alpha=5, beta=4)
            verdict, output = self._drive(
                suite, env_extra="export DEVFLOW_TEST_SHARD_SKIP_ONE=1\n"
            )
            self.assertEqual(verdict, "VERDICT pass:0 fail:1", output)
            self.assertIn(
                "the schedule dropped work — dispatched 8 and executed 8 of 9 "
                "enumerated tests",
                output,
            )
            self.assertNotIn("recorded no exit status", output)

    def test_a_unit_whose_worker_dies_without_recording_a_status_is_a_failure(self):
        # AC4, the arm the killed-python test cannot reach: killing the PYTHON process
        # still lets its subshell write the .rc, so the rc arm catches it. Killing the
        # SUBSHELL leaves no .rc at all — a unit that was skipped outright. Before this
        # was a per-unit failure it was a silent `continue` whose only backstop was the
        # aggregate sum, which another unit over-reporting could compensate for.
        with tempfile.TemporaryDirectory() as tmp:
            suite = self._write_suite(
                tmp,
                source=(
                    "import os\nimport signal\nimport unittest\n\n\n"
                    "class AlphaTests(unittest.TestCase):\n"
                    "    def test_orphan(self):\n"
                    "        os.kill(os.getppid(), signal.SIGKILL)\n\n"
                    "    def test_ok(self):\n        pass\n\n"
                    'if __name__ == "__main__":\n    unittest.main()\n'
                ),
            )
            verdict, output = self._drive(suite, width="1")
            self.assertEqual(verdict, "VERDICT pass:0 fail:1", output)
            self.assertIn("recorded no exit status", output)

    def test_a_unit_cannot_inflate_the_executed_count_from_its_own_stdout(self):
        # The count is parsed from the unit's STDERR only. A unit's stdout is
        # block-buffered to a file and flushed at interpreter exit — after unittest's
        # unbuffered stderr summary — so a merged capture would let this printed line
        # win the last-match parse and inflate `executed` in the one direction the
        # aggregate comparison cannot catch.
        with tempfile.TemporaryDirectory() as tmp:
            suite = self._write_suite(
                tmp,
                source=(
                    "import unittest\n\n\n"
                    "class AlphaTests(unittest.TestCase):\n"
                    "    def test_liar(self):\n"
                    "        print('Ran 99 tests in 0.001s')\n\n"
                    "    def test_ok(self):\n        pass\n\n"
                    'if __name__ == "__main__":\n    unittest.main()\n'
                ),
            )
            verdict, output = self._drive(suite, width="2")
            self.assertEqual(verdict, "VERDICT pass:1 fail:0", output)
            self.assertIn("executed 2 test(s)", output)

    def test_a_unit_exiting_zero_with_no_parseable_count_is_a_failure(self):
        # The `unit_ran` arm in isolation: every other failure-mode test drives a unit
        # with a NONZERO rc, so the rc arm fires first and this arm is never the sole
        # guard. A stub interpreter that exits 0 silently isolates it.
        with tempfile.TemporaryDirectory() as tmp:
            suite = self._write_suite(tmp, alpha=2, beta=1)
            stub = Path(tmp) / "silent-python"
            stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            stub.chmod(0o755)
            verdict, output = self._drive(
                suite, env_extra=f'export DEVFLOW_TEST_SHARD_PYTHON="{stub}"\n'
            )
            self.assertEqual(verdict, "VERDICT pass:0 fail:1", output)
            self.assertIn("expected exactly 1", output)

    @staticmethod
    def _concurrency_suite(count: int, *, failing: bool) -> str:
        """A synthetic suite whose units RENDEZVOUS rather than sleep a fixed window.

        Each unit records its arrival, then polls until it has observed that at least two
        units have ever started (or a generous deadline elapses) before recording its
        departure. The overlap the test asserts is therefore *observed*, not raced against
        a fixed sleep — the load-sensitive slack-budget shape CLAUDE.md names as a defect
        rather than a tolerated flake. The bound stays cheap: once two units have started,
        every later unit satisfies the predicate immediately.
        """
        body = (
            "        with open(MARK, 'a') as fh:\n"
            "            fh.write('+\\n')\n"
            "        deadline = time.monotonic() + 30.0\n"
            "        while time.monotonic() < deadline:\n"
            "            with open(MARK) as fh:\n"
            "                if fh.read().count('+') >= 2:\n"
            "                    break\n"
            "            time.sleep(0.01)\n"
            "        with open(MARK, 'a') as fh:\n"
            "            fh.write('-\\n')\n"
        )
        if failing:
            body += "        raise AssertionError('planted')\n"
        return (
            "import os\nimport time\nimport unittest\n\n\n"
            "MARK = os.environ['DEVFLOW_870_MARK']\n\n\n"
            "class AlphaTests(unittest.TestCase):\n"
            + "".join(f"    def test_m{i}(self):\n{body}\n" for i in range(count))
            + '\nif __name__ == "__main__":\n    unittest.main()\n'
        )

    def _peak_inflight(self, mark: Path) -> int:
        peak = inflight = 0
        for token in mark.read_text().split():
            inflight += 1 if token == "+" else -1
            peak = max(peak, inflight)
        return peak

    def test_the_pre_bash_4_3_serial_reap_path_is_correct(self):
        # `wait -n` arrived in bash 4.3, so on CI and at the desk the specific-pid
        # fallback never executes — yet it holds the driver's only index arithmetic
        # (pids[dispatched] / reaped), where a stale subscript would either desync the
        # in-flight count or abort under `set -u`. The hook forces that arm on a modern
        # shell so it is driven rather than hand-proved.
        with tempfile.TemporaryDirectory() as tmp:
            suite = self._write_suite(
                tmp, source=self._concurrency_suite(8, failing=False)
            )
            mark = Path(tmp) / "marks.txt"
            mark.write_text("", encoding="utf-8")
            verdict, output = self._drive(
                suite,
                width="2",
                env_extra=(
                    "export DEVFLOW_TEST_SHARD_FORCE_SERIAL_REAP=1\n"
                    f'export DEVFLOW_870_MARK="{mark}"\n'
                ),
            )
            self.assertEqual(verdict, "VERDICT pass:1 fail:0", output)
            self.assertIn("executed 8 test(s)", output)
            peak = self._peak_inflight(mark)
            self.assertLessEqual(peak, 2, f"peak in-flight {peak} exceeded width 2")

    def test_concurrency_never_exceeds_the_resolved_width(self):
        # The work queue's bound is the whole reason it is safe to run inside the suite's
        # already-open pool: no more than $width units may be in flight at once.
        with tempfile.TemporaryDirectory() as tmp:
            suite = self._write_suite(
                tmp, source=self._concurrency_suite(8, failing=False)
            )
            mark = Path(tmp) / "marks.txt"
            mark.write_text("", encoding="utf-8")
            verdict, output = self._drive(
                suite, width="2", env_extra=f'export DEVFLOW_870_MARK="{mark}"\n'
            )
            self.assertEqual(verdict, "VERDICT pass:1 fail:0", output)
            peak = self._peak_inflight(mark)
            self.assertLessEqual(peak, 2, f"peak in-flight {peak} exceeded width 2")
            self.assertGreater(peak, 1, "the queue never ran two units concurrently")

    def test_concurrency_survives_a_failing_unit(self):
        # The all-green test above cannot see this: a `wait -n`-based gate returns the
        # reaped unit's exit status, so one FAILING unit drained the whole pool and the
        # rolling queue degraded into batched waves — on exactly the runs that fail.
        with tempfile.TemporaryDirectory() as tmp:
            suite = self._write_suite(
                tmp, source=self._concurrency_suite(6, failing=True)
            )
            mark = Path(tmp) / "marks.txt"
            mark.write_text("", encoding="utf-8")
            verdict, output = self._drive(
                suite, width="2", env_extra=f'export DEVFLOW_870_MARK="{mark}"\n'
            )
            self.assertEqual(verdict, "VERDICT pass:0 fail:1", output)
            peak = self._peak_inflight(mark)
            self.assertLessEqual(peak, 2, f"peak in-flight {peak} exceeded width 2")
            self.assertGreater(
                peak, 1, "a failing unit collapsed the pool to serial execution"
            )


# ── issue #1216: default-signal spawn helpers and the ignored-signal diagnostic ──
SIGNAL_SPAWN_SHIM = ROOT / "lib/test/exec-with-default-signals.py"
DETACHED_LAUNCHER = ROOT / "lib/test/launch-detached.py"
WARN_IGNORED_SIGNALS = ROOT / "lib/test/warn-ignored-signals.sh"


@unittest.skipUnless(
    POSIX_SIGNAL_MATRIX_AVAILABLE,
    "host-capability: POSIX signals and process groups are required",
)
class DefaultSignalSpawnHelperTests(unittest.TestCase):
    """AC3: `exec-with-default-signals.py` hands its target a default SIGINT even
    when the spawning shell has job control off and SIGINT already ignored, and its
    `exec` preserves the spawned process's identity so `$!` still names it."""

    def _run_parent(self, tmp: Path, *, use_shim: bool) -> tuple[str, str]:
        # A bash parent with job control OFF that first ignores SIGINT (the
        # affected-host condition a job-control-off `&` manufactures), then
        # backgrounds a coordinator-style child and captures both the child's
        # inherited SIGINT disposition and the child's own PID. `$!` is written to
        # PIDCAP; the child prints `SELFPID=<pid>` so identity can be compared.
        out = tmp / "child-out"
        pidcap = tmp / "pidcap"
        inner = "trap -p INT; echo \"SELFPID=$$\""
        if use_shim:
            spawn = f'exec python3 "{SIGNAL_SPAWN_SHIM}" bash -c \'{inner}\''
        else:
            spawn = f"exec bash -c '{inner}'"
        script = tmp / "parent.sh"
        script.write_text(
            "#!/usr/bin/env bash\n"
            "set +m\n"          # job control off, as the module worker runs
            "trap '' INT\n"      # SIGINT inherited-ignored, like the affected host
            f'( {spawn} > "{out}" 2>&1 ) &\n'
            "child=$!\n"
            f'printf "%s" "$child" > "{pidcap}"\n'
            "wait \"$child\"\n",
            encoding="utf-8",
        )
        subprocess.run(["bash", str(script)], check=True)
        return out.read_text(encoding="utf-8"), pidcap.read_text(encoding="utf-8")

    def test_control_without_shim_inherits_ignored_sigint(self) -> None:
        # Baseline: without the shim, the coordinator-style child inherits the
        # ignored SIGINT and cannot trap it — the failure this issue fixes.
        with tempfile.TemporaryDirectory() as t:
            child_out, _ = self._run_parent(Path(t), use_shim=False)
            self.assertIn("'' SIGINT", child_out, child_out)

    def test_shim_restores_default_sigint(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            child_out, _ = self._run_parent(Path(t), use_shim=True)
            self.assertNotIn("'' SIGINT", child_out, child_out)

    def test_shim_preserves_process_identity(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            child_out, pidcap = self._run_parent(Path(t), use_shim=True)
            self.assertRegex(child_out, r"SELFPID=\d+", child_out)
            self_pid = child_out.split("SELFPID=", 1)[1].strip().splitlines()[0]
            self.assertEqual(
                self_pid, pidcap.strip(),
                f"$! ({pidcap.strip()}) must name the exec'd coordinator ({self_pid})",
            )

    def test_shim_restores_all_four_default_signals(self) -> None:
        # The shim routes through restore_default_signals, which covers HUP/INT/QUIT/
        # TERM. With the parent ignoring all four, the shimmed child must see every one
        # default. SIGQUIT is the interesting sibling of SIGINT — the other signal a
        # job-control-off `&` forces to ignore, which bash also cannot un-ignore.
        report = 'for s in HUP INT QUIT TERM; do d="$(trap -p "$s")"; [ -z "$d" ] && echo "SIG$s DFL" || echo "SIG$s IGN"; done'
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "child-out"
            script = Path(t) / "parent.sh"
            script.write_text(
                "#!/usr/bin/env bash\n"
                "set +m\n"
                "trap '' HUP INT QUIT TERM\n"
                f'( exec python3 "{SIGNAL_SPAWN_SHIM}" bash -c \'{report}\' > "{out}" 2>&1 ) &\n'
                "wait \"$!\"\n",
                encoding="utf-8",
            )
            subprocess.run(["bash", str(script)], check=True)
            child_out = out.read_text(encoding="utf-8")
        for name in ("SIGHUP", "SIGINT", "SIGQUIT", "SIGTERM"):
            self.assertIn(f"{name} DFL", child_out, child_out)


@unittest.skipUnless(
    POSIX_SIGNAL_MATRIX_AVAILABLE,
    "host-capability: POSIX signals and process groups are required",
)
class DetachedLauncherTests(unittest.TestCase):
    """AC6: `launch-detached.py` runs a command with HUP/INT/QUIT/TERM restored to
    their default disposition in the child (in a new session) and reports the
    child's real exit status rather than its own."""

    # A bash child reflects the TRUE inherited disposition via `trap -p`: an
    # inherited SIG_IGN prints `trap -- '' SIG<N>`, a default prints nothing. A
    # Python child is unusable here because CPython reinstalls its own SIGINT
    # (KeyboardInterrupt) handler at startup even when it inherits SIG_DFL.
    _REPORT = (
        'for s in HUP INT QUIT TERM; do '
        'd="$(trap -p "$s")"; '
        '[ -z "$d" ] && echo "SIG$s DFL" || echo "SIG$s NOTDFL: $d"; '
        "done"
    )

    @staticmethod
    def _ignore_all_four() -> None:
        for name in ("SIGHUP", "SIGINT", "SIGQUIT", "SIGTERM"):
            signal.signal(getattr(signal, name), signal.SIG_IGN)

    def test_child_sees_default_dispositions_for_all_four(self) -> None:
        # The outer process ignores all four; the launcher must restore each to
        # default in the child, so pass-through would fail this test.
        r = subprocess.run(
            ["python3", str(DETACHED_LAUNCHER), "bash", "-c", self._REPORT],
            capture_output=True, text=True, preexec_fn=self._ignore_all_four,
        )
        for name in ("SIGHUP", "SIGINT", "SIGQUIT", "SIGTERM"):
            self.assertIn(f"{name} DFL", r.stdout, r.stdout + r.stderr)

    def test_reports_child_nonzero_exit_status(self) -> None:
        r = subprocess.run(
            ["python3", str(DETACHED_LAUNCHER), "bash", "-c", "exit 7"],
            capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 7, r.stderr)

    def test_reports_child_signal_death_as_128_plus_n(self) -> None:
        r = subprocess.run(
            ["python3", str(DETACHED_LAUNCHER), "bash", "-c", "kill -TERM $$"],
            capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 128 + int(signal.SIGTERM), r.stderr)

    def test_child_is_placed_in_a_new_session(self) -> None:
        # The launcher's second promise: the child is in its own session, so a
        # signal to the launcher's process group does not tear it down mid-run.
        # A child in a new session is its own session leader, so os.getsid(0)
        # equals its own pid. Pass-through (no start_new_session) would leave the
        # child in the launcher's session, failing this.
        r = subprocess.run(
            ["python3", str(DETACHED_LAUNCHER), "python3", "-c",
             "import os; print(os.getpid(), os.getsid(0))"],
            capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        pid, sid = r.stdout.split()
        self.assertEqual(pid, sid, f"child ({pid}) is not its own session leader (sid {sid})")
        self.assertNotEqual(
            sid, str(os.getsid(0)),
            "child shares this process's session — start_new_session did not take effect",
        )


@unittest.skipUnless(
    os.name == "posix",
    "host-capability: POSIX exec-failure status semantics (126/127) are required",
)
class SpawnFailureFidelityTests(unittest.TestCase):
    """Both entry points report a target they could not exec with the shell's own
    status — 127 not found, 126 present but not executable — rather than collapsing
    it onto a generic 1, which a target that actually ran could itself have
    produced. The two statuses are the only thing that tells a caller the command
    never started."""

    MISSING = "/nonexistent-dir-1216/no-such-command"

    @staticmethod
    def _non_executable(tmp: str) -> str:
        target = Path(tmp) / "present-but-not-executable"
        target.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        target.chmod(0o644)
        return str(target)

    @staticmethod
    def _run(launcher: Path, target: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(launcher), target], capture_output=True, text=True
        )

    def _assert_spawn_failure(self, launcher: Path, target: str, expected: int) -> None:
        r = self._run(launcher, target)
        self.assertEqual(r.returncode, expected, r.stderr)
        # A raw traceback is the other half of the defect: the diagnostic has to be
        # the one-line form the empty-argv arm already emits, naming the target.
        self.assertNotIn("Traceback", r.stderr, r.stderr)
        self.assertIn(target, r.stderr, r.stderr)

    def test_shim_reports_missing_target_as_127(self) -> None:
        self._assert_spawn_failure(SIGNAL_SPAWN_SHIM, self.MISSING, 127)

    def test_shim_reports_non_executable_target_as_126(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            self._assert_spawn_failure(SIGNAL_SPAWN_SHIM, self._non_executable(t), 126)

    def test_launcher_reports_missing_target_as_127(self) -> None:
        self._assert_spawn_failure(DETACHED_LAUNCHER, self.MISSING, 127)

    def test_launcher_reports_non_executable_target_as_126(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            self._assert_spawn_failure(DETACHED_LAUNCHER, self._non_executable(t), 126)

    def test_a_real_exit_1_stays_distinguishable_from_a_spawn_failure(self) -> None:
        # The control for the collision above: exit 1 from a command that DID run
        # must still arrive as 1, so 127/126 are a real discrimination and not a
        # blanket remap of every failure.
        r = subprocess.run(
            ["python3", str(DETACHED_LAUNCHER), "bash", "-c", "exit 1"],
            capture_output=True, text=True,
        )
        self.assertEqual(r.returncode, 1, r.stderr)


@unittest.skipUnless(
    POSIX_SIGNAL_MATRIX_AVAILABLE,
    "host-capability: POSIX signals and process groups are required",
)
class IgnoredSignalDiagnosticTests(unittest.TestCase):
    """AC4/AC5: the startup diagnostic is loud when SIGINT/SIGQUIT arrived ignored
    and silent otherwise, and it is advisory — identical exit code and (empty) skip
    tally on both arms."""

    def _run(self, *, ignore=()) -> subprocess.CompletedProcess[str]:
        # `ignore` is a tuple of signal.Signals to set SIG_IGN in the child before it
        # runs the diagnostic (simulating the affected-host inherited-ignore state).
        preexec = None
        if ignore:
            preexec = lambda: [signal.signal(s, signal.SIG_IGN) for s in ignore]  # noqa: E731
        return subprocess.run(
            ["bash", str(WARN_IGNORED_SIGNALS)],
            capture_output=True, text=True, preexec_fn=preexec,
        )

    def test_default_arm_is_silent(self) -> None:
        r = self._run()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "", r.stdout)
        self.assertEqual(r.stderr, "", r.stderr)

    def test_ignored_sigint_arm_is_loud_and_advisory(self) -> None:
        r = self._run(ignore=(signal.SIGINT,))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("SIGINT", r.stderr, r.stderr)
        # advisory: nothing on stdout, so it cannot contribute a PASS/FAIL/skip line
        # to a caller folding its stdout into a tally.
        self.assertEqual(r.stdout, "", r.stdout)

    def test_ignored_sigquit_arm_is_loud(self) -> None:
        # The QUIT arm is independent of the INT arm; a regression dropping the
        # `_devflow_warn_ignored_signal QUIT` line would pass every INT-only test.
        r = self._run(ignore=(signal.SIGQUIT,))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("SIGQUIT", r.stderr, r.stderr)
        self.assertEqual(r.stdout, "", r.stdout)

    def test_exit_code_and_skip_tally_identical_across_arms(self) -> None:
        default = self._run()
        ignored = self._run(ignore=(signal.SIGINT,))
        self.assertEqual(default.returncode, ignored.returncode)
        # The diagnostic registers no skip: it writes to no SKIPS_FILE and emits
        # nothing on stdout in either arm, so the skip tally is zero in both.
        self.assertEqual(default.stdout, "")
        self.assertEqual(ignored.stdout, "")


if __name__ == "__main__":
    if sys.argv[1:] == ["--signal-matrix-capability"]:
        capability_reason = signal_matrix_capability_skip_reason(
            POSIX_SIGNAL_MATRIX_AVAILABLE
        )
        if capability_reason is not None:
            print(capability_reason)
            raise SystemExit(1)
        raise SystemExit(0)
    unittest.main()
