#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Regression tests for the opaque legacy mutation-pin census."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
SCRIPT = HERE / "mutation-pin-census.py"
HISTORICAL_ADJUDICATIONS = HERE / "mutation-pin-corpus-adjudications.tsv"
CURRENT_INVENTORY = (
    REPO_ROOT / ".prflow/logs/mutation-pin-corpus-inventory.tsv"
)
HARNESS_INVENTORY = HERE / "modules/harness-python-guards.inventory.md"
SPEC = importlib.util.spec_from_file_location("mutation_pin_census", SCRIPT)
assert SPEC and SPEC.loader
CENSUS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CENSUS
SPEC.loader.exec_module(CENSUS)

AUDITED = (
    "lib/test/run.sh",
    "lib/test/modules/workflow-flight-recorder.sh",
    "lib/test/modules/review-and-fix-contract.sh",
    "lib/test/modules/create-issue-contract.sh",
    "lib/test/modules/capability-profiles.sh",
    "lib/test/modules/regenerate-artifacts.sh",
    "lib/test/modules/installer-wiring.sh",
    "lib/test/modules/harness-python-guards.sh",
    "lib/test/modules/prompt-extension-reader.sh",
    "lib/test/modules/review-trigger-helpers.sh",
    "lib/test/modules/review-stall-backstop.sh",
    "lib/test/modules/retrospective-lifecycle.sh",
    "lib/test/modules/experiment-records.sh",
    "lib/test/modules/efficiency-trace-telemetry.sh",
    "lib/test/modules/issue-audit-state.sh",
    "lib/test/modules/tier1-rename-migration.sh",
    "lib/test/modules/parallel-suite-runner.sh",
    "lib/test/modules/phase2-durability-checkpoint.sh",
    "lib/test/modules/review-contract.sh",
    "lib/test/modules/workpad-cli.sh",
    "lib/test/modules/implement-contract.sh",
)
DEFINITIONS = ""


class FixtureRepo:
    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for source in AUDITED:
            path = self.root / source
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        linter = self.root / "lib/test/pin-corpus-lint.py"
        values = ",\n        ".join(repr(path) for path in AUDITED)
        linter.write_text(
            "AUDITED_PIN_SOURCES = frozenset(\n"
            "    {\n"
            f"        {values},\n"
            "    }\n"
            ")\n",
            encoding="utf-8",
        )
        harness = self.root / "lib/test/module-harness.sh"
        harness.write_text(DEFINITIONS, encoding="utf-8")
        subprocess.run(
            ["git", "init", "-q"],
            cwd=self.root,
            check=True,
        )
        subprocess.run(
            ["git", "add", "."],
            cwd=self.root,
            check=True,
        )

    def close(self) -> None:
        self._tmp.cleanup()

    def write(self, relative: str, text: str) -> None:
        (self.root / relative).write_text(text, encoding="utf-8")

    def track(self, relative: str) -> None:
        subprocess.run(
            ["git", "add", "--", relative],
            cwd=self.root,
            check=True,
        )

    def census(self):
        return CENSUS.build_census(self.root)


class MutationPinCensusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = FixtureRepo()

    def tearDown(self) -> None:
        self.repo.close()

    def test_real_tree_census_is_deterministic_and_nonvacuous(self) -> None:
        first = CENSUS.build_census(REPO_ROOT)
        second = CENSUS.build_census(REPO_ROOT)
        self.assertEqual(first, second)
        self.assertEqual(tuple(first.sources), tuple(sorted(AUDITED)))
        self.assertEqual(len(first.rows), 0)
        self.assertEqual(
            {helper: first.helper_count(helper) for helper in CENSUS.HELPERS},
            {
                "assert_pin_red_under": 0,
                "devflow_module_pin_red_under": 0,
                "assert_count_red_under": 0,
                "_ra_conflict_red_under": 0,
            },
        )
        self.assertRegex(first.master_sha256, r"^[0-9a-f]{64}$")
        self.assertEqual(
            first.master_sha256,
            hashlib.sha256(first.identity_bytes()).hexdigest(),
        )
        dispositions = [
            CENSUS.adjudicate(row).disposition for row in first.rows
        ]
        self.assertEqual(
            dispositions.count("retire_presence_equivalent"),
            0,
        )
        self.assertEqual(
            dispositions.count("retain_helper_infrastructure_boundary"),
            0,
        )
        self.assertEqual(
            dispositions.count("retain_executable_boundary"),
            0,
        )
        retained = {
            CENSUS._identity_sha256(row)
            for row in first.rows
            if CENSUS.adjudicate(row).disposition.startswith("retain_")
        }
        self.assertEqual(retained, set())

    def test_historical_disposition_summary_is_derived_and_current_inventory_is_empty(
        self,
    ) -> None:
        lines = HISTORICAL_ADJUDICATIONS.read_text(encoding="utf-8").splitlines()
        rows = list(
            csv.DictReader(
                io.StringIO(
                    "\n".join(line for line in lines if not line.startswith("#"))
                ),
                delimiter="\t",
            )
        )
        self.assertEqual(650, len(rows))
        derived = {
            disposition: sum(
                row["disposition"] == disposition for row in rows
            )
            for disposition in (
                "retire_presence_equivalent",
                "retain_helper_infrastructure_boundary",
                "retain_executable_boundary",
            )
        }
        self.assertEqual(
            {
                "retire_presence_equivalent": 635,
                "retain_helper_infrastructure_boundary": 7,
                "retain_executable_boundary": 8,
            },
            derived,
        )

        summary = HARNESS_INVENTORY.read_text(encoding="utf-8")
        match = re.search(
            r"mutation census: historical=(\d+), "
            r"retire_presence_equivalent=(\d+), "
            r"retain_helper_infrastructure_boundary=(\d+), "
            r"retain_executable_boundary=(\d+), current=(\d+)",
            summary,
        )
        self.assertIsNotNone(match)
        historical, retired, helper_boundaries, executable_boundaries, current = (
            int(value) for value in match.groups()
        )
        self.assertEqual(len(rows), historical)
        self.assertEqual(
            (
                derived["retire_presence_equivalent"],
                derived["retain_helper_infrastructure_boundary"],
                derived["retain_executable_boundary"],
            ),
            (retired, helper_boundaries, executable_boundaries),
        )
        self.assertEqual(historical, retired + helper_boundaries + executable_boundaries)

        current_rows = [
            line
            for line in CURRENT_INVENTORY.read_text(
                encoding="utf-8"
            ).splitlines()
            if line and not line.startswith("#")
        ]
        self.assertEqual(
            "path\thelper\tlogical_call\tline_start\tline_end\t"
            "identity_sha256\tdisposition\trationale",
            current_rows[0],
        )
        self.assertEqual(current, len(current_rows) - 1)
        self.assertEqual(0, current)

    def test_unrecognized_mutation_helpers_are_rejected_not_auto_retained(self) -> None:
        source = AUDITED[0]
        for helper in ("assert_count_red_under", "_ra_conflict_red_under"):
            with self.subTest(helper=helper):
                row = CENSUS.CensusRow(
                    path=source,
                    helper=helper,
                    logical_call=f"{helper} new unreviewed mutation site",
                    line_start=1,
                    line_end=1,
                )
                self.assertEqual(
                    CENSUS.adjudicate(row).disposition,
                    "reject_unadjudicated_mutation_site",
                )

    def test_identity_uses_path_helper_and_exact_physical_call_not_locator(self) -> None:
        source = AUDITED[1]
        self.repo.write(
            source,
            "devflow_module_pin_red_under 'name' \\\n"
            "  'literal' \\\n"
            "  's/x/y/' target\n",
        )
        result = self.repo.census()
        row = result.rows[0]
        self.assertEqual(row.path, source)
        self.assertEqual(row.helper, "devflow_module_pin_red_under")
        self.assertEqual(
            row.logical_call,
            "devflow_module_pin_red_under 'name' \\\n"
            "  'literal' \\\n"
            "  's/x/y/' target",
        )
        self.assertEqual((row.line_start, row.line_end), (1, 3))
        moved = CENSUS.CensusRow(
            path=row.path,
            helper=row.helper,
            logical_call=row.logical_call,
            line_start=40,
            line_end=42,
        )
        self.assertEqual(row.identity, moved.identity)
        reformatted = CENSUS.CensusRow(
            path=row.path,
            helper=row.helper,
            logical_call=(
                "devflow_module_pin_red_under 'name' 'literal' "
                "'s/x/y/' target"
            ),
            line_start=row.line_start,
            line_end=row.line_end,
        )
        self.assertNotEqual(row.identity, reformatted.identity)

    def test_reindent_and_environment_prefix_change_invocation_identity(self) -> None:
        source = AUDITED[1]
        call = "devflow_module_pin_red_under n l m f"
        self.repo.write(source, call + "\n")
        plain = self.repo.census().rows[0]

        self.repo.write(source, "  " + call + "\n")
        indented = self.repo.census().rows[0]
        self.assertEqual(indented.logical_call, "  " + call)
        self.assertNotEqual(plain.identity, indented.identity)

        self.repo.write(source, "FLAG=1 " + call + "\n")
        prefixed = self.repo.census().rows[0]
        self.assertEqual(prefixed.logical_call, "FLAG=1 " + call)
        self.assertNotEqual(plain.identity, prefixed.identity)

    def test_sorted_jsonl_and_tsv_are_deterministic(self) -> None:
        self.repo.write(
            AUDITED[2],
            "devflow_module_pin_red_under z z z z\n"
            "devflow_module_pin_red_under a a a a\n",
        )
        result = self.repo.census()
        jsonl = CENSUS.render_jsonl(result)
        tsv = CENSUS.render_tsv(result)
        self.assertEqual(jsonl, CENSUS.render_jsonl(self.repo.census()))
        self.assertEqual(tsv, CENSUS.render_tsv(self.repo.census()))
        objects = [json.loads(line) for line in jsonl.splitlines()]
        self.assertEqual(objects[-1], {"master_sha256": result.master_sha256})
        self.assertEqual(tsv.splitlines()[-1], f"# master_sha256\t{result.master_sha256}")
        self.assertLess(objects[0]["logical_call"], objects[1]["logical_call"])
        revision = "c" * 40
        self.assertEqual(
            CENSUS.render_tsv(result, revision).splitlines()[0],
            f"# source_revision\t{revision}",
        )

    def test_adjudication_tsv_names_inventory_free_source_revision(self) -> None:
        self.repo.write(
            AUDITED[2],
            "devflow_module_pin_red_under n l m f\n",
        )
        result = self.repo.census()
        revision = "a" * 40
        output = CENSUS.render_adjudication_tsv(result, revision)
        self.assertEqual(
            output.splitlines()[0],
            f"# source_revision\t{revision}",
        )
        self.assertIn("\treject_unadjudicated_mutation_site\t", output)
        self.assertNotIn("source_revision\tself", output)

    def test_missing_source_fails_closed(self) -> None:
        (self.repo.root / AUDITED[-1]).unlink()
        with self.assertRaisesRegex(CENSUS.CensusError, "missing audited source"):
            self.repo.census()

    def test_missing_or_duplicate_audited_population_entry_fails_closed(self) -> None:
        linter = self.repo.root / "lib/test/pin-corpus-lint.py"
        for population, message in (
            (AUDITED[:-1], "count disagreement"),
            ((*AUDITED, AUDITED[0]), "duplicate audited population entry"),
        ):
            values = ",\n        ".join(repr(path) for path in population)
            linter.write_text(
                "AUDITED_PIN_SOURCES = frozenset(\n"
                "    {\n"
                f"        {values},\n"
                "    }\n"
                ")\n",
                encoding="utf-8",
            )
            with self.subTest(message=message):
                with self.assertRaisesRegex(CENSUS.CensusError, message):
                    self.repo.census()

    def test_malformed_utf8_fails_closed(self) -> None:
        (self.repo.root / AUDITED[-1]).write_bytes(b"\xff")
        with self.assertRaisesRegex(CENSUS.CensusError, "UTF-8"):
            self.repo.census()

    def test_duplicate_identity_fails_closed(self) -> None:
        call = "devflow_module_pin_red_under n l m f\n"
        self.repo.write(AUDITED[2], call + call)
        with self.assertRaisesRegex(CENSUS.CensusError, "duplicate identity"):
            self.repo.census()

    def test_multiple_supported_calls_on_logical_line_fail_closed(self) -> None:
        self.repo.write(
            AUDITED[2],
            "devflow_module_pin_red_under a b c d; "
            "devflow_module_pin_red_under e f g h\n",
        )
        with self.assertRaisesRegex(CENSUS.CensusError, "multiple supported calls"):
            self.repo.census()

    def test_prefixed_helper_tokens_fail_closed(self) -> None:
        calls = (
            "command devflow_module_pin_red_under a b c d",
            "if devflow_module_pin_red_under a b c d; then :; fi",
            "! devflow_module_pin_red_under a b c d",
            "while devflow_module_pin_red_under a b c d; do :; done",
            "env FLAG=1 devflow_module_pin_red_under a b c d",
            "{ devflow_module_pin_red_under a b c d; }",
            "( devflow_module_pin_red_under a b c d )",
            "if true; then devflow_module_pin_red_under a b c d; fi",
            "case x in x) devflow_module_pin_red_under a b c d ;; esac",
            "printf x devflow_module_pin_red_under",
        )
        for call in calls:
            with self.subTest(call=call):
                self.repo.write(AUDITED[2], call + "\n")
                with self.assertRaisesRegex(
                    CENSUS.CensusError,
                    "lexical/extracted",
                ):
                    self.repo.census()

    def test_quoted_and_commented_helper_names_are_not_lexical_calls(self) -> None:
        self.repo.write(
            AUDITED[2],
            "printf '%s\\n' 'devflow_module_pin_red_under'\n"
            'printf "%s\\n" "assert_count_red_under"\n'
            "printf '%s\\n' value # _ra_conflict_red_under is commentary\n",
        )
        self.assertEqual((), self.repo.census().rows)

    def test_unexpected_and_duplicate_helper_definitions_fail_closed(self) -> None:
        (self.repo.root / "lib/test/module-harness.sh").unlink()
        with self.assertRaisesRegex(CENSUS.CensusError, "test shell source"):
            self.repo.census()
        (self.repo.root / "lib/test/module-harness.sh").write_text(
            DEFINITIONS + "devflow_module_pin_red_under() { :; }\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CENSUS.CensusError, "helper definition count"):
            self.repo.census()

    def test_helper_definitions_are_enumerated_from_tracked_files_only(self) -> None:
        relative = "lib/test/untracked-definition.sh"
        (self.repo.root / relative).write_text(
            "devflow_module_pin_red_under() { :; }\n",
            encoding="utf-8",
        )
        self.repo.census()
        self.repo.track(relative)
        with self.assertRaisesRegex(CENSUS.CensusError, "helper definition count"):
            self.repo.census()

    def test_alternate_and_nested_helper_definitions_fail_closed(self) -> None:
        harness = self.repo.root / "lib/test/module-harness.sh"
        harness.write_text(
            DEFINITIONS
            + "function assert_pin_red_under { :; }\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CENSUS.CensusError, "helper definition count"):
            self.repo.census()

        harness.write_text(
            DEFINITIONS.replace(
                "",
                "assert_pin_red_under() { "
                "assert_count_red_under n a b c; :; }",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CENSUS.CensusError, "definition segment"):
            self.repo.census()

    def test_split_line_helper_definitions_are_counted_and_bodies_fail_closed(
        self,
    ) -> None:
        harness = self.repo.root / "lib/test/module-harness.sh"
        for definition in (
            "assert_pin_red_under()\n{\n  :\n}\n",
            "function assert_pin_red_under\n{\n  :\n}\n",
            "function assert_pin_red_under()\n# comment\n\n{\n  :\n}\n",
        ):
            with self.subTest(definition=definition):
                harness.write_text(
                    DEFINITIONS + definition,
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    CENSUS.CensusError, "helper definition count"
                ):
                    self.repo.census()

        harness.write_text(
            DEFINITIONS.replace(
                "",
                "assert_pin_red_under()\n"
                "{\n"
                "  assert_count_red_under n a b c\n"
                "}\n",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            CENSUS.CensusError, "unclassified supported helper token"
        ):
            self.repo.census()

    def test_invalid_utf8_tracked_shell_definition_source_fails_closed(self) -> None:
        relative = "lib/test/invalid-definition.sh"
        (self.repo.root / relative).write_bytes(b"\xff")
        self.repo.track(relative)
        with self.assertRaisesRegex(CENSUS.CensusError, "not valid UTF-8"):
            self.repo.census()

    def test_known_non_utf8_fixture_is_exact_and_helper_free(self) -> None:
        relative = next(iter(CENSUS.NON_UTF8_SHELL_FIXTURES))
        path = self.repo.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture\xffbytes")
        self.repo.track(relative)
        self.repo.census()

        path.write_bytes(b"fixture\xffassert_pin_red_under")
        with self.assertRaisesRegex(CENSUS.CensusError, "not valid UTF-8"):
            self.repo.census()

    def test_tracked_definition_enumeration_failure_fails_closed(self) -> None:
        real_run = subprocess.run

        def fail_ls_files(args, **kwargs):
            if args[:2] == ["git", "ls-files"]:
                return subprocess.CompletedProcess(args, 1, "", "injected")
            return real_run(args, **kwargs)

        with mock.patch.object(subprocess, "run", side_effect=fail_ls_files):
            with self.assertRaisesRegex(CENSUS.CensusError, "tracked"):
                self.repo.census()

    def test_unterminated_continuation_fails_closed(self) -> None:
        self.repo.write(AUDITED[3], "assert_pin_red_under a b c d \\")
        with self.assertRaisesRegex(CENSUS.CensusError, "continuation"):
            self.repo.census()

    def test_all_eight_pr819_synthetic_calls_are_opaque_rows(self) -> None:
        calls = [
            f"devflow_module_pin_red_under '819-{index}' 'literal-{index}' "
            f"'s/old-{index}/new-{index}/' target-{index}"
            for index in range(1, 9)
        ]
        self.repo.write(AUDITED[3], "\n".join(calls) + "\n")
        result = self.repo.census()
        self.assertEqual(len(result.rows), 8)
        self.assertEqual(
            {row.logical_call for row in result.rows},
            set(calls),
        )

    def test_census_does_not_spawn_or_interpret_mutation_tools(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("sed ", source)
        self.assertNotIn("grep ", source)
        self.repo.write(
            AUDITED[4],
            "devflow_module_pin_red_under n l 'arbitrary opaque bytes' f\n",
        )
        real_run = subprocess.run

        def git_only(args, **kwargs):
            self.assertEqual(args[:2], ["git", "ls-files"])
            return real_run(args, **kwargs)

        with mock.patch.object(subprocess, "run", side_effect=git_only):
            self.assertEqual(len(self.repo.census().rows), 1)

    def test_cli_outputs_jsonl_and_tsv_with_master_digest(self) -> None:
        self.repo.write(AUDITED[5], "devflow_module_pin_red_under n l m f\n")
        for fmt in ("jsonl", "tsv"):
            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--repo-root",
                    str(self.repo.root),
                    "--format",
                    fmt,
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("master_sha256", proc.stdout)

        adjudication = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--repo-root",
                str(self.repo.root),
                "--format",
                "adjudication-tsv",
                "--source-revision",
                "b" * 40,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(adjudication.returncode, 0, adjudication.stderr)
        self.assertIn(f"# source_revision\t{'b' * 40}", adjudication.stdout)


if __name__ == "__main__":
    unittest.main()
