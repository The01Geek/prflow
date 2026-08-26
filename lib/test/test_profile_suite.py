#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Focused tests for the opt-in suite profiler (`lib/test/profile-suite.py`), issue #985.

The profiler's parsing and attribution layer is pure: three regexes over the suite's
own output contract, a deterministic time-attribution model, a label extractor, and a
malformed-row-tolerant TSV reader. #983 shipped it with none of that exercised, on the
one-off grounds that registering a new test file would have moved the assertion tally
that PR's central promise was about. This closes the gap.

What is tested is BEHAVIOR, never the module's wording: the regexes are driven against
the adversarial line shapes they exist to reject, `Profile.feed`/`close` are driven
against a hand-computed attribution ledger, the report's degrade contract is driven
against each malformed `run.json` / TSV shape, and the exit-status translation is
driven end to end through a real child process that dies from a real signal. No test
here reads `lib/test/profile-suite.py` as text and asserts a sentence appears in it —
that would be an undeclared wording-only pin (CLAUDE.md, issues #375/#666/#810).

The helper is hyphenated, so it is loaded via importlib.util.spec_from_file_location,
the same workaround the other hyphenated-script tests in this suite use.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
PROFILER_SOURCE = HERE / "profile-suite.py"

_spec = importlib.util.spec_from_file_location("profile_suite", PROFILER_SOURCE)
profiler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(profiler)


def _write_profile_dir(directory, meta=None, labels=None, sections=None, assertions=None):
    """Materialize a profile directory the `report` subcommand can re-render.

    Every table defaults to one well-formed row so a test that is about ONE table's
    malformed shapes is not silently also testing a missing-file arm elsewhere.
    """
    out = Path(directory)
    base = {
        "command": ["lib/test/run.sh"],
        "exit_code": 0,
        "total_s": 12.5,
        "tail_s": 0.5,
        "passed": 3,
        "failed": 0,
        "noted": 0,
        "sections": 1,
        "labels": 1,
    }
    if meta is not None:
        base.update(meta)
    (out / "run.json").write_text(json.dumps(base, indent=2) + "\n", encoding="utf-8")
    (out / "sections.tsv").write_text(
        "seconds\tshare_pct\tassertions\tsection\n"
        + ("\n".join(sections) + "\n" if sections else "9.000\t72.00\t3\tSECTION ONE\n"),
        encoding="utf-8",
    )
    (out / "labels.tsv").write_text(
        "seconds\tshare_pct\tassertions\tissue_label\n"
        + ("\n".join(labels) + "\n" if labels else "5.000\t40.00\t2\t985\n"),
        encoding="utf-8",
    )
    (out / "assertions.tsv").write_text(
        "seconds\tstatus\tsection\tassertion\n"
        + (
            "\n".join(assertions) + "\n"
            if assertions
            else "3.000\tPASS\tSECTION ONE\tthe slow one #985\n"
        ),
        encoding="utf-8",
    )
    return out


def _render(out, top=5):
    """Run `_report` over a prepared directory; return (rc, stdout, stderr).

    `run_sh=None` on purpose: line resolution is report garnish that would otherwise
    drag the real 40k-line run.sh into every one of these cases.
    """
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        rc = profiler._report(Path(out), top, None)
    return rc, stdout.getvalue(), stderr.getvalue()


class ResultRegexTests(unittest.TestCase):
    """`_RESULT_RE`: the suite's `  STATUS  name` assertion-result contract."""

    def test_each_status_word_parses_into_status_and_name(self):
        for status in ("PASS", "FAIL", "NOTE"):
            with self.subTest(status=status):
                match = profiler._RESULT_RE.match(f"  {status}  #985 some assertion")
                self.assertIsNotNone(match)
                self.assertEqual(match.group(1), status)
                self.assertEqual(match.group(2), "#985 some assertion")

    def test_a_name_containing_two_spaces_keeps_its_whole_tail(self):
        # The name group is greedy to end-of-line, so an assertion whose own name
        # contains the separator is not truncated at the second occurrence.
        match = profiler._RESULT_RE.match("  PASS  a  b  c")
        self.assertEqual(match.group(2), "a  b  c")

    def test_a_quoted_reproduction_is_deliberately_still_parsed(self):
        # Documented over-attribution: a fixture echoing a result-shaped line is
        # charged as if it were an assertion. The cost is a mislabelled row, never a
        # wrong pass/fail — pinning it keeps a later "tightening" an explicit choice.
        self.assertIsNotNone(profiler._RESULT_RE.match("  PASS  reproduced by a fixture"))

    def test_wrong_indent_or_separator_or_status_does_not_parse(self):
        for line in (
            " PASS  one-space indent",
            "    PASS  four-space indent",
            "PASS  no indent",
            "  PASS one-space separator",
            "  SKIP  not a status word",
            "  pass  lowercase",
            "  PASSED  superstring status",
        ):
            with self.subTest(line=line):
                self.assertIsNone(profiler._RESULT_RE.match(line))


class LabelRegexTests(unittest.TestCase):
    """`_LABEL_RE`: the `#NNN` issue label, captured bare."""

    def test_the_capture_group_excludes_the_hash(self):
        self.assertEqual(profiler._LABEL_RE.findall("#985 and #10"), ["985", "10"])

    def test_a_one_digit_label_is_below_the_floor(self):
        self.assertEqual(profiler._LABEL_RE.findall("#1 and #9"), [])

    def test_a_bare_number_without_a_hash_is_not_a_label(self):
        self.assertEqual(profiler._LABEL_RE.findall("985 and 1002"), [])

    def test_a_six_digit_run_is_truncated_at_the_five_digit_ceiling(self):
        # Stated so the ceiling is a known property rather than a surprise: issue
        # numbers are 2..5 digits, and a longer digit run yields its first five.
        self.assertEqual(profiler._LABEL_RE.findall("#123456"), ["12345"])


class BannerRegexTests(unittest.TestCase):
    """`_BANNER_RE`: a run.sh section banner in SOURCE position."""

    def test_a_plain_double_quoted_echo_is_a_banner(self):
        match = profiler._BANNER_RE.match('echo "a real section banner"')
        self.assertEqual(match.group(1), "a real section banner")

    def test_trailing_whitespace_is_tolerated(self):
        self.assertIsNotNone(profiler._BANNER_RE.match('echo "a real section banner"  '))

    def test_the_shapes_a_fixture_uses_are_all_rejected(self):
        for line in (
            "echo '[] single quoted'",              # a fixture's stub-script heredoc
            'echo "stub: $a called" >&2',           # expansion AND a redirect
            'echo "redirected banner text" >&2',    # redirect alone
            'echo "expands $HOME right here"',      # expansion alone
            'echo "short"',                         # 5 chars, below the 8-char floor
            '  echo "indented, not top level"',     # not in source-banner position
            'printf "%s\\n" "not an echo"',
            'echo "has a \\\\ backslash in it"',
        ):
            with self.subTest(line=line):
                self.assertIsNone(profiler._BANNER_RE.match(line))

    def test_the_eight_character_floor_is_exact(self):
        self.assertIsNone(profiler._BANNER_RE.match('echo "1234567"'))
        self.assertIsNotNone(profiler._BANNER_RE.match('echo "12345678"'))


class PreambleSentinelTests(unittest.TestCase):
    """AC5: the initial section sentinel cannot be produced by `_BANNER_RE`."""

    def test_no_echo_line_can_produce_the_sentinel_as_a_banner_name(self):
        sentinel = profiler.Profile(set()).section
        self.assertIsNone(profiler._BANNER_RE.match(f'echo "{sentinel}"'))

    def test_a_run_sh_that_echoes_the_sentinel_does_not_admit_it_to_the_banner_set(self):
        # The collision path end to end: _banner_set derives banners from SOURCE, and
        # a source line echoing the sentinel must not put it in the set — which is
        # what would merge the preamble's own time with that echo's section.
        sentinel = profiler.Profile(set()).section
        with tempfile.TemporaryDirectory() as scratch:
            fake_run_sh = Path(scratch) / "run.sh"
            fake_run_sh.write_text(
                f'echo "{sentinel}"\necho "a genuine section banner"\n', encoding="utf-8"
            )
            banners = profiler._banner_set(fake_run_sh)
        self.assertEqual(banners, {"a genuine section banner"})

    def test_the_preamble_bucket_still_collects_pre_banner_time(self):
        # The immunity must not have been bought by breaking the bucket itself.
        prof = profiler.Profile({"a genuine section banner"})
        prof.feed(1.0, 1.0, "some warm-up output")
        prof.feed(2.0, 1.0, "a genuine section banner")
        self.assertEqual(prof.sections[profiler.Profile(set()).section], 2.0)


class LabelsOfTests(unittest.TestCase):
    """AC2: `_labels_of` emits bare, deduplicated, order-preserving labels."""

    def test_labels_are_emitted_bare(self):
        self.assertEqual(profiler._labels_of("#985 covers #10"), ["985", "10"])

    def test_repeated_labels_are_deduplicated_in_first_appearance_order(self):
        self.assertEqual(
            profiler._labels_of("#20 then #10 then #20 again then #10"), ["20", "10"]
        )

    def test_a_name_with_no_label_yields_nothing(self):
        self.assertEqual(profiler._labels_of("an unlabelled assertion"), [])

    def test_an_emitted_label_cell_is_byte_identical_to_a_coverage_map_block_key(self):
        # The joinability claim, driven against the REAL map rather than a synthetic
        # key: take a live `run_sh_blocks` key, put it in an assertion name, run the
        # whole feed -> _emit path, and require the emitted TSV cell to equal the key
        # with no stripping. A `#`-prefixed cell fails here.
        blocks = json.loads(
            (ROOT / "lib/test/modules/coverage-map.json").read_text(encoding="utf-8")
        )["run_sh_blocks"]
        keys = sorted(key for key in blocks if key.isdigit())
        self.assertTrue(keys, "coverage-map run_sh_blocks carries no numeric key")
        key = keys[0]

        prof = profiler.Profile(set())
        prof.feed(1.0, 1.0, f"  PASS  an assertion labelled #{key}")
        with tempfile.TemporaryDirectory() as out:
            profiler._emit(prof, Path(out), 1.0, ["lib/test/run.sh"], 0)
            rows = [
                line.split("\t")
                for line in (Path(out) / "labels.tsv").read_text(encoding="utf-8").splitlines()
            ]
        self.assertEqual(rows[0][3], "issue_label")
        self.assertEqual([row[3] for row in rows[1:]], [key])


class AttributionTests(unittest.TestCase):
    """`Profile.feed` / `Profile.close`: the documented attribution model."""

    def _ledger(self):
        prof = profiler.Profile({"SECTION ONE", "SECTION TWO"})
        prof.feed(1.0, 1.0, "warm-up chatter")                 # 1.0 -> preamble
        prof.feed(2.0, 1.0, "SECTION ONE")                     # 1.0 -> preamble, opens ONE
        prof.feed(4.0, 2.0, "  PASS  first #10")               # 2.0 -> ONE
        prof.feed(7.0, 3.0, "  FAIL  second #10 #20")          # 3.0 -> ONE
        prof.feed(11.0, 4.0, "SECTION TWO")                    # 4.0 -> ONE, opens TWO
        prof.feed(16.0, 5.0, "  NOTE  third #20")              # 5.0 -> TWO
        prof.close(6.0)                                        # 6.0 -> TWO, as tail
        return prof

    def test_a_banner_charges_its_gap_to_the_outgoing_section(self):
        prof = self._ledger()
        self.assertEqual(
            prof.sections,
            {profiler.Profile(set()).section: 2.0, "SECTION ONE": 9.0, "SECTION TWO": 11.0},
        )

    def test_close_charges_the_tail_to_the_section_that_was_current(self):
        prof = self._ledger()
        self.assertEqual(prof.tail_s, 6.0)
        # 5.0 from the NOTE gap plus the 6.0 tail; the tail is reported separately AND
        # folded into its section, so dropping either half is caught here.
        self.assertEqual(prof.sections["SECTION TWO"], 11.0)

    def test_assertion_counts_are_per_section_and_a_banner_seeds_a_zero(self):
        prof = self._ledger()
        self.assertEqual(prof.section_counts, {"SECTION ONE": 2, "SECTION TWO": 1})
        self.assertEqual(prof.counts, {"PASS": 1, "FAIL": 1, "NOTE": 1})

    def test_every_label_on_an_assertion_is_credited_its_full_gap(self):
        prof = self._ledger()
        self.assertEqual(prof.labels, {"10": 5.0, "20": 8.0})
        self.assertEqual(prof.label_counts, {"10": 2, "20": 2})

    def test_a_line_that_is_neither_banner_nor_result_still_charges_its_gap(self):
        # Otherwise the gap that produced a plain output line would vanish from the
        # totals and every share would be computed against an under-counted section.
        prof = profiler.Profile({"SECTION ONE"})
        prof.feed(1.0, 1.0, "SECTION ONE")
        prof.feed(3.0, 2.0, "plain output from some command")
        self.assertEqual(prof.sections["SECTION ONE"], 2.0)
        self.assertEqual(prof.section_counts["SECTION ONE"], 0)
        self.assertEqual(prof.assertions, [])

    def test_rows_and_events_record_the_section_current_when_the_line_arrived(self):
        prof = self._ledger()
        self.assertEqual(
            prof.assertions,
            [
                (2.0, "SECTION ONE", "PASS", "first #10"),
                (3.0, "SECTION ONE", "FAIL", "second #10 #20"),
                (5.0, "SECTION TWO", "NOTE", "third #20"),
            ],
        )
        self.assertEqual(
            [(event[2], event[3]) for event in prof.events],
            [
                ("SECTION", profiler.Profile(set()).section),
                ("PASS", "SECTION ONE"),
                ("FAIL", "SECTION ONE"),
                ("SECTION", "SECTION ONE"),
                ("NOTE", "SECTION TWO"),
            ],
        )


class ReportMetaDegradeTests(unittest.TestCase):
    """AC3: every `run.json` shape either renders or degrades — never a traceback."""

    def test_a_numeric_string_total_s_renders_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as out:
            _write_profile_dir(out, meta={"total_s": "12.5"})
            rc, stdout, stderr = _render(out)
        self.assertEqual(rc, 0, stderr)
        self.assertIn("total 12.5s", stdout)
        self.assertNotIn("Traceback", stderr)

    def test_a_genuine_zero_total_s_renders_as_zero_not_as_the_epsilon_floor(self):
        # The coercion must not route the header through the `or 1e-9` divide-by-zero
        # floor, which would print 0.0s as 0.0000000001s.
        with tempfile.TemporaryDirectory() as out:
            _write_profile_dir(out, meta={"total_s": 0})
            rc, stdout, stderr = _render(out)
        self.assertEqual(rc, 0, stderr)
        self.assertIn("total 0.0s", stdout)

    def test_every_unusable_total_s_shape_degrades_to_the_breadcrumb_and_rc_two(self):
        for value in ("not-a-number", None, [], {}, "", "12.5s"):
            with self.subTest(total_s=value), tempfile.TemporaryDirectory() as out:
                _write_profile_dir(out, meta={"total_s": value})
                rc, _stdout, stderr = _render(out)
                self.assertEqual(rc, 2)
                self.assertIn("unreadable or malformed", stderr)
                self.assertNotIn("Traceback", stderr)

    def test_a_missing_or_unparseable_run_json_degrades_the_same_way(self):
        with tempfile.TemporaryDirectory() as out:
            rc, _stdout, stderr = _render(out)
            self.assertEqual(rc, 2)
            self.assertIn("no run.json", stderr)

        with tempfile.TemporaryDirectory() as out:
            _write_profile_dir(out)
            (Path(out) / "run.json").write_text('{"total_s": 1.0', encoding="utf-8")
            rc, _stdout, stderr = _render(out)
            self.assertEqual(rc, 2)
            self.assertIn("unreadable or malformed", stderr)
            self.assertNotIn("Traceback", stderr)

    def test_an_absent_integer_key_degrades_rather_than_raising_keyerror(self):
        with tempfile.TemporaryDirectory() as out:
            meta = json.loads(
                (_write_profile_dir(out) / "run.json").read_text(encoding="utf-8")
            )
            del meta["passed"]
            (Path(out) / "run.json").write_text(json.dumps(meta), encoding="utf-8")
            rc, _stdout, stderr = _render(out)
        self.assertEqual(rc, 2)
        self.assertIn("unreadable or malformed", stderr)


class ReportRowSkippingTests(unittest.TestCase):
    """`rows()`: drop what the writer did not finish, render the rest."""

    def test_short_and_non_numeric_rows_are_skipped_while_the_rest_render(self):
        with tempfile.TemporaryDirectory() as out:
            _write_profile_dir(
                out,
                labels=[
                    "5.000\t40.00\t2\t985",       # well-formed
                    "1.000\t8.00",                # truncated mid-write
                    "abc\t8.00\t1\t111",          # seconds not a float
                    "1.000\tNaN%\t1\t222",        # share not a float
                    "1.000\t8.00\tmany\t333",     # count not an int
                    "2.000\t16.00\t1\t444",       # well-formed
                ],
            )
            rc, stdout, stderr = _render(out)
        self.assertEqual(rc, 0, stderr)
        self.assertIn("skipped 4 malformed row(s)", stderr)
        rendered = [line.split()[-1] for line in stdout.splitlines() if line.startswith(" ")]
        self.assertEqual([cell for cell in rendered if cell in {"985", "444"}], ["985", "444"])
        self.assertEqual([cell for cell in rendered if cell in {"111", "222", "333"}], [])

    def test_a_blank_line_is_ignored_rather_than_counted_as_malformed(self):
        with tempfile.TemporaryDirectory() as out:
            _write_profile_dir(out, labels=["5.000\t40.00\t2\t985", "", "   "])
            rc, _stdout, stderr = _render(out)
        self.assertEqual(rc, 0)
        self.assertNotIn("malformed row(s)", stderr)

    def test_the_assertions_table_tolerates_a_non_numeric_share_column(self):
        # Its renderer computes the share from column 0 and never reads column 1, so
        # guarding column 1 there would drop rows the report can render fine. Column 0
        # is still guarded, because the renderer does parse it.
        with tempfile.TemporaryDirectory() as out:
            _write_profile_dir(
                out,
                assertions=[
                    "3.000\tPASS\tSECTION ONE\tkept despite the status column\n",
                    "nope\tPASS\tSECTION ONE\tdropped for an unparseable seconds cell",
                ],
            )
            rc, stdout, stderr = _render(out)
        self.assertEqual(rc, 0, stderr)
        self.assertIn("kept despite the status column", stdout)
        self.assertIn("skipped 1 malformed row(s)", stderr)

    def test_a_missing_table_is_omitted_with_a_breadcrumb_and_the_report_still_renders(self):
        with tempfile.TemporaryDirectory() as out:
            _write_profile_dir(out)
            (Path(out) / "labels.tsv").unlink()
            rc, stdout, stderr = _render(out)
        self.assertEqual(rc, 0, stderr)
        self.assertIn("table omitted", stderr)
        self.assertIn("issue labels", stdout)


class ExitStatusTests(unittest.TestCase):
    """AC4: a profiled run's status is indistinguishable from an unprofiled one's."""

    def test_the_translation_table(self):
        for wait_status, expected in ((0, 0), (1, 1), (7, 7), (-15, 143), (-9, 137), (-2, 130)):
            with self.subTest(wait_status=wait_status):
                self.assertEqual(profiler._exit_status(wait_status), expected)

    def _profile(self, code):
        with tempfile.TemporaryDirectory() as out:
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                return profiler.main(
                    ["run", "--out", out, "--top", "1", "--", sys.executable, "-c", code]
                )

    def test_a_child_killed_by_sigterm_yields_the_shell_s_own_143(self):
        # The comparand is MEASURED, not a constant typed twice: an outer bash reports
        # what a SIGTERM-killed bash exited with, so the claim under test is literally
        # "matches an unprofiled run" rather than "matches the number I wrote down".
        # (`subprocess.run().returncode` cannot serve as that comparand — Python
        # reports the same death as -15, which is the very representation at issue.)
        measured = subprocess.run(
            [
                "bash",
                "-c",
                "bash -c 'kill -TERM $$; sleep 5' >/dev/null 2>&1; printf %s \"$?\"",
            ],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        self.assertEqual(measured, str(128 + signal.SIGTERM))
        self.assertEqual(
            self._profile("import os, signal; os.kill(os.getpid(), signal.SIGTERM)"),
            int(measured),
        )

    def test_a_non_signal_status_passes_through_unchanged(self):
        self.assertEqual(self._profile("import sys; sys.exit(7)"), 7)
        self.assertEqual(self._profile("pass"), 0)

    def test_the_translated_status_is_what_run_json_and_the_report_record(self):
        # One event, one number: a run.json that recorded the raw -15 would make a
        # later `report --out DIR` contradict the status the shell actually saw.
        with tempfile.TemporaryDirectory() as out:
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                rc = profiler.main(
                    [
                        "run",
                        "--out",
                        out,
                        "--top",
                        "1",
                        "--",
                        sys.executable,
                        "-c",
                        "import os, signal; os.kill(os.getpid(), signal.SIGTERM)",
                    ]
                )
            recorded = json.loads(
                (Path(out) / "run.json").read_text(encoding="utf-8")
            )["exit_code"]
        self.assertEqual(rc, 128 + signal.SIGTERM)
        self.assertEqual(recorded, rc)
        self.assertIn(f"rc={rc}", stdout.getvalue())


class OptimizedModeGuardTests(unittest.TestCase):
    """AC6: no runtime guard in this module vanishes under `python3 -O`."""

    def test_the_module_carries_no_assert_statement(self):
        # `python3 -O` strips every `assert` statement, so an `assert` used as a
        # runtime guard is a guard a flag deletes. This is a structural property of
        # the code with a real execution consequence, not a wording pin: it is read
        # from the parsed AST and would still hold if every comment were rewritten.
        tree = ast.parse(PROFILER_SOURCE.read_text(encoding="utf-8"))
        self.assertEqual(
            [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Assert)], []
        )

    def test_the_module_still_profiles_a_child_under_dash_O(self):
        result = subprocess.run(
            [sys.executable, "-O", str(PROFILER_SOURCE), "report", "--out", os.devnull],
            capture_output=True,
            text=True,
            check=False,
        )
        # The `report` path over a non-directory is the cheapest arm that proves the
        # module imports, parses its arguments and reaches its degrade contract with
        # assertions disabled.
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
