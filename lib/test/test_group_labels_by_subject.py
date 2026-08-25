#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Focused unit tests for lib/test/group_labels_by_subject.py (issue #1928).

Drives the subject-grouping helper against a synthetic ``lib/test/run.sh`` fixture holding
labels whose assertions name known paths, and asserts the grouping data structures, the
per-group label counts, the handling of a label whose assertions name no repository path at
all, and the ``main()`` CLI emission (the literal "print" clauses of AC1) over a throwaway git
fixture tree. The pure-function cases read no live tree; the ``main()`` cases build their own.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parent / "group_labels_by_subject.py"
_spec = importlib.util.spec_from_file_location("group_labels_by_subject", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
g = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g)


# A synthetic run.sh: each labelled assertion, then the lines that belong to it (its nearest
# preceding assertion label), name known repository paths. #404 names no path anywhere.
FIXTURE = """\
# a leading comment mentioning scripts/workpad.py in a comment line
assert_eq "#101 workpad new-body seeds the plan row" "x" "y"
grep -n scripts/workpad.py "$LIB/some-fixture"
assert_eq "#101 second workpad claim" "1" "1"
assert_eq "#202 review engine bundle claim" "checks skills/review/phases/phase-3-agents.md"
check "#202 second review claim" skills/review/SKILL.md
assert_eq "#303 mixed claim naming scripts/config-get.sh once" "a" "b"
grep scripts/workpad.py "$LIB/x"
grep scripts/workpad.py "$LIB/y"
assert_eq "#404 a claim naming no repository path at all" "x" "y"
"""


class SubjectReduction(unittest.TestCase):
    def test_directory_subject_takes_first_two_components(self):
        self.assertEqual(g._subject("skills/review/phases/phase-3-agents.md"), "skills/review")

    def test_two_component_file_is_its_own_subject(self):
        self.assertEqual(g._subject("scripts/workpad.py"), "scripts/workpad.py")

    def test_lib_test_is_the_meta_subject(self):
        self.assertEqual(g._subject("lib/test/run.sh"), "lib/test")


class Grouping(unittest.TestCase):
    def test_labels_group_by_dominant_path(self):
        groups = g.group_labels(FIXTURE)
        # #101's lines name scripts/workpad.py; #303 names workpad.py twice vs config-get.sh
        # once, so workpad.py dominates.
        self.assertEqual(groups["scripts/workpad.py"], ["101", "303"])
        self.assertEqual(groups["skills/review"], ["202"])

    def test_label_naming_no_path_groups_under_sentinel(self):
        groups = g.group_labels(FIXTURE)
        self.assertEqual(groups[g.NO_PATH_KEY], ["404"])

    def test_group_label_counts(self):
        groups = g.group_labels(FIXTURE)
        self.assertEqual(len(groups["scripts/workpad.py"]), 2)
        self.assertEqual(len(groups["skills/review"]), 1)
        self.assertEqual(len(groups[g.NO_PATH_KEY]), 1)

    def test_restrict_limits_to_the_given_labels(self):
        groups = g.group_labels(FIXTURE, restrict={"101"})
        self.assertEqual(groups, {"scripts/workpad.py": ["101"]})

    def test_sorted_groups_order_by_count_then_subject(self):
        ordered = g._sorted_groups(g.group_labels(FIXTURE))
        subjects = [subject for subject, _ in ordered]
        self.assertEqual(subjects[0], "scripts/workpad.py")  # count 2 leads
        # the two singletons tie on count, broken by subject ascending:
        self.assertEqual(subjects[1:], [g.NO_PATH_KEY, "skills/review"])


class DominantSubject(unittest.TestCase):
    def test_most_named_subject_wins(self):
        lines = [
            "names scripts/workpad.py here",
            "and scripts/workpad.py again",
            "but scripts/config-get.sh only once",
        ]
        self.assertEqual(g.dominant_subject(lines), "scripts/workpad.py")

    def test_no_path_returns_sentinel(self):
        self.assertEqual(g.dominant_subject(["nothing path-like here"]), g.NO_PATH_KEY)

    def test_tie_broken_lexicographically(self):
        lines = ["scripts/workpad.py once", "agents/branch-setup.md once"]
        self.assertEqual(g.dominant_subject(lines), "agents/branch-setup.md")

    def test_basename_index_resolves_bare_mentions(self):
        index = {"workpad.py": "scripts/workpad.py"}
        self.assertEqual(
            g.dominant_subject(["the workpad.py new-body seed"], basename_index=index),
            "scripts/workpad.py",
        )

    def test_basename_not_matched_as_substring(self):
        # 'notworkpad.pyish' must not match the 'workpad.py' basename token.
        index = {"workpad.py": "scripts/workpad.py"}
        self.assertEqual(
            g.dominant_subject(["a notworkpad.pyish token"], basename_index=index),
            g.NO_PATH_KEY,
        )


class AttributeLines(unittest.TestCase):
    def test_comment_before_any_assertion_belongs_to_no_label(self):
        attributed = g.attribute_lines(FIXTURE)
        line, labels = attributed[0]  # the leading comment naming scripts/workpad.py
        self.assertTrue(line.lstrip().startswith("#"))
        self.assertEqual(labels, frozenset())

    def test_comment_inherits_nearest_preceding_assertion_labels(self):
        text = 'assert_eq "#101 claim" "x" "y"\n# a comment naming scripts/workpad.py'
        attributed = g.attribute_lines(text)
        self.assertEqual(attributed[1][1], frozenset({"101"}))

    def test_unlabelled_assertion_resets_the_running_set(self):
        text = (
            'assert_eq "#101 claim" "x" "y"\n'
            'assert_eq "an unlabelled claim" "x" "y"\n'
            "# a trailing comment"
        )
        attributed = g.attribute_lines(text)
        self.assertEqual(attributed[0][1], frozenset({"101"}))
        self.assertEqual(attributed[1][1], frozenset())
        self.assertEqual(attributed[2][1], frozenset())


class SentinelDisjointness(unittest.TestCase):
    def test_sentinel_cannot_be_a_derived_subject(self):
        # A derived subject always begins with a recognized top dir (a _path_re match
        # starts "<top-dir>/"), and the sentinel does not — expressing the invariant a
        # future _path_re relaxation would otherwise erode silently.
        self.assertFalse(
            any(
                g.NO_PATH_KEY == d or g.NO_PATH_KEY.startswith(d + "/")
                for d in g.DEFAULT_TOP_DIRS
            )
        )
        self.assertIsNone(g._path_re(g.DEFAULT_TOP_DIRS).search(g.NO_PATH_KEY))


class BasenameIndex(unittest.TestCase):
    def test_distinctive_basename_maps_to_subject(self):
        index = g.build_basename_index(["scripts/workpad.py", "skills/review/SKILL.md"])
        self.assertEqual(index["workpad.py"], "scripts/workpad.py")

    def test_vendored_copy_is_excluded_leaving_one_subject(self):
        index = g.build_basename_index(
            ["scripts/workpad.py", ".prflow/vendor/prflow/scripts/workpad.py"]
        )
        self.assertEqual(index["workpad.py"], "scripts/workpad.py")

    def test_ambiguous_basename_is_dropped(self):
        index = g.build_basename_index(["skills/review/SKILL.md", "skills/implement/SKILL.md"])
        self.assertNotIn("SKILL.md", index)


class Unmodularized(unittest.TestCase):
    def test_selects_only_unmodularized_owners(self):
        cmap = {
            "run_sh_blocks": {
                "101": {"owner": "unmodularized"},
                "202": {"owner": "review-contract"},
                "303": {"owner": "unmodularized"},
            }
        }
        self.assertEqual(g.unmodularized_labels(cmap), {"101", "303"})


# A run.sh fixture for the main() CLI cases: #101 and #303 name scripts/workpad.py, #202 names
# skills/review, #404 names no path. The bare basenames are not tracked files in the throwaway
# repo below, so only the full path-regex mentions are tallied — a deterministic grouping.
MAIN_RUN_SH = """\
assert_eq "#101 workpad claim" "x" "y"
grep -n scripts/workpad.py "$LIB/f"
assert_eq "#202 review claim" "checks skills/review/SKILL.md"
assert_eq "#303 mixed claim" "a" "b"
grep scripts/workpad.py "$LIB/g"
assert_eq "#404 a claim naming no repository path at all" "x" "y"
assert_eq "#505 already-modularized claim" "checks skills/review/SKILL.md"
"""

# #505 names a path but its owner is a real module, not "unmodularized", so main()'s restrict
# filter must exclude it from the grouping.
MAIN_COVERAGE_MAP = {
    "run_sh_blocks": {
        "101": {"owner": "unmodularized"},
        "202": {"owner": "unmodularized"},
        "303": {"owner": "unmodularized"},
        "404": {"owner": "unmodularized"},
        "505": {"owner": "review-contract"},
    }
}


def _build_repo(tmp: Path, *, coverage_map: "dict | None", run_sh: "str | None") -> None:
    """Write the two files main() reads under a fresh git repo, and stage them.

    _git_tracked runs `git ls-files`, so the tree must be a git repo with the files staged
    for the basename index to see them. A None argument omits that file entirely (to drive the
    unreadable-file / missing-key error paths).
    """
    (tmp / "lib" / "test" / "modules").mkdir(parents=True, exist_ok=True)
    if coverage_map is not None:
        (tmp / "lib" / "test" / "modules" / "coverage-map.json").write_text(
            json.dumps(coverage_map), encoding="utf-8"
        )
    if run_sh is not None:
        (tmp / "lib" / "test" / "run.sh").write_text(run_sh, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(tmp), "add", "-A"], check=True)


class MainCli(unittest.TestCase):
    def test_prints_grouped_lines_with_counts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _build_repo(root, coverage_map=MAIN_COVERAGE_MAP, run_sh=MAIN_RUN_SH)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = g.main([str(root)])
            self.assertEqual(rc, 0)
            lines = out.getvalue().splitlines()
            # count-desc ordering puts the 2-label group first, and each line carries the count
            # and the #-prefixed labels — the literal AC1 (b)+(c) "print" surface.
            self.assertEqual(lines[0], "scripts/workpad.py (2 labels): #101 #303")
            self.assertIn("skills/review (1 labels): #202", lines)
            self.assertIn(f"{g.NO_PATH_KEY} (1 labels): #404", lines)

    def test_json_branch_emits_the_grouping(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _build_repo(root, coverage_map=MAIN_COVERAGE_MAP, run_sh=MAIN_RUN_SH)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = g.main([str(root), "--json"])
            self.assertEqual(rc, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["scripts/workpad.py"], ["101", "303"])
            # #505 is a non-unmodularized owner, so main()'s restrict filter drops it and
            # skills/review stays a singleton — pinning the "marks unmodularized" clause of AC1
            # at the main() integration level, not only in unmodularized_labels() in isolation.
            self.assertEqual(payload["skills/review"], ["202"])
            self.assertEqual(payload[g.NO_PATH_KEY], ["404"])

    def test_non_unmodularized_label_excluded_by_main(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _build_repo(root, coverage_map=MAIN_COVERAGE_MAP, run_sh=MAIN_RUN_SH)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = g.main([str(root), "--json"])
            self.assertEqual(rc, 0)
            all_labels = [lbl for labels in json.loads(out.getvalue()).values() for lbl in labels]
            self.assertNotIn("505", all_labels)

    def test_missing_run_sh_blocks_key_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _build_repo(root, coverage_map={"files": {}}, run_sh=MAIN_RUN_SH)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = g.main([str(root)])
            self.assertEqual(rc, 2)
            self.assertIn("run_sh_blocks", err.getvalue())

    def test_non_dict_run_sh_blocks_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _build_repo(root, coverage_map={"run_sh_blocks": []}, run_sh=MAIN_RUN_SH)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = g.main([str(root)])
            self.assertEqual(rc, 2)
            self.assertIn("run_sh_blocks", err.getvalue())

    def test_missing_run_sh_returns_2(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _build_repo(root, coverage_map=MAIN_COVERAGE_MAP, run_sh=None)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = g.main([str(root)])
            self.assertEqual(rc, 2)
            # attribute the rejection to the run.sh arm, not the coverage-map arm the
            # same fixture would hit were the map also absent
            self.assertIn(f"cannot read {g.RUN_SH_REL}", err.getvalue())

    def test_git_enumeration_failure_returns_2(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _build_repo(root, coverage_map=MAIN_COVERAGE_MAP, run_sh=MAIN_RUN_SH)
            # Break the repo after both file reads would succeed: a .git FILE naming a
            # nonexistent gitdir makes `git ls-files` fail deterministically, whatever
            # repository (if any) encloses the temp dir.
            shutil.rmtree(root / ".git")
            (root / ".git").write_text("gitdir: /nonexistent\n", encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = g.main([str(root)])
            self.assertEqual(rc, 2)
            self.assertIn("cannot enumerate tracked files", err.getvalue())

    def test_unreadable_coverage_map_returns_2(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)  # empty dir: coverage-map.json absent
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = g.main([str(root)])
            self.assertEqual(rc, 2)
            self.assertIn("cannot read", err.getvalue())


if __name__ == "__main__":
    unittest.main()
