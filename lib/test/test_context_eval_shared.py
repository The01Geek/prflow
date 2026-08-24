#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Focused tests for scripts/context_eval_shared.py (issue #1900).

The three transcript-walking instruments — scripts/create_issue_eval.py,
scripts/implement-context-eval.py, scripts/review-context-eval.py — previously each
carried a private copy of five helpers. Issue #1900 single-sources them into
scripts/context_eval_shared.py. This suite pins two things:

- the strict post-#1899 behavior of the shared helpers (an unmeasured turn, an empty
  population, and a non-finite number are reported unestablished / raise, never a real 0),
  driven against the shared module directly; and
- that the single definition is the one each instrument reaches — every instrument (and
  the create-issue-context-eval.py importlib shim) re-exports the SAME object, proving the
  copies are gone rather than merely equal.

Driven serially from lib/test/run.sh.
"""

import importlib.util
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
_SCRIPTS = os.path.join(_REPO, "scripts")

# Import the shared module canonically (by name, off the scripts dir), so the objects the
# instruments pull in via `from context_eval_shared import …` are the SAME module object —
# the identity assertions below rest on that.
sys.path.insert(0, _SCRIPTS)
import context_eval_shared as SHARED  # noqa: E402


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The three instruments plus the shim, each loaded by absolute path exactly as their own
# focused tests load them.
CIE = _load_module("cie", os.path.join(_SCRIPTS, "create_issue_eval.py"))
CICE = _load_module("cice", os.path.join(_SCRIPTS, "create-issue-context-eval.py"))
ICE = _load_module("ice", os.path.join(_SCRIPTS, "implement-context-eval.py"))
RCE = _load_module("rce", os.path.join(_SCRIPTS, "review-context-eval.py"))

_SHARED_NAMES = (
    "_iter_session_files",
    "_median",
    "_context_tokens",
    "_usage_value",
    "UNESTABLISHED",
)


class ContextTokensStrictTest(unittest.TestCase):
    """AC2: an empty / unusable usage object is None, never a real-looking 0."""

    def test_empty_and_unmeasured_usage_is_none_never_zero(self):
        for usage in ({}, {"input_tokens": None}, {"input_tokens": True},
                      {"input_tokens": "12"}, "not a dict", None,
                      {"input_tokens": float("inf")}, {"input_tokens": float("nan")}):
            got = SHARED._context_tokens(usage)
            self.assertIsNone(got, repr(usage))
            self.assertNotEqual(got, 0, repr(usage))

    def test_established_subfields_sum(self):
        self.assertEqual(
            SHARED._context_tokens({"input_tokens": None, "cache_read_input_tokens": 7}), 7)
        self.assertEqual(SHARED._context_tokens({"input_tokens": 10}), 10)


class UsageValueStrictTest(unittest.TestCase):
    """AC2: a non-finite / bool / non-numeric field establishes nothing (None), never 0."""

    def test_non_finite_and_invalid_are_none(self):
        for bad in (float("inf"), float("-inf"), float("nan"), True, "7", None):
            got = SHARED._usage_value({"input_tokens": bad}, "input_tokens")
            self.assertIsNone(got, repr(bad))
        self.assertIsNone(SHARED._usage_value({}, "input_tokens"))
        self.assertIsNone(SHARED._usage_value("not a dict", "input_tokens"))

    def test_established_counts_read_through(self):
        self.assertEqual(SHARED._usage_value({"input_tokens": 7.0}, "input_tokens"), 7)
        self.assertEqual(SHARED._usage_value({"input_tokens": 0}, "input_tokens"), 0)


class MedianStrictTest(unittest.TestCase):
    """AC2: an empty population raises rather than collapsing onto 0."""

    def test_empty_population_raises(self):
        with self.assertRaises(ValueError):
            SHARED._median([])

    def test_median_values(self):
        self.assertEqual(SHARED._median([3, 1, 2]), 2)      # odd -> middle
        self.assertEqual(SHARED._median([3, 1]), 2)         # even, divides evenly -> int
        self.assertEqual(SHARED._median([1, 2, 3, 5]), 2.5)  # even, does not -> float
        self.assertIsInstance(SHARED._median([3, 1]), int)
        self.assertIsInstance(SHARED._median([1, 2]), float)


class SingleSourceIdentityTest(unittest.TestCase):
    """AC1: exactly one definition, reached by all three instruments and the shim."""

    def test_every_instrument_reexports_the_shared_objects(self):
        for mod, label in ((CIE, "create_issue_eval"), (CICE, "create-issue-context-eval shim"),
                            (ICE, "implement-context-eval"), (RCE, "review-context-eval")):
            for name in _SHARED_NAMES:
                self.assertTrue(hasattr(mod, name), "{} missing {}".format(label, name))
                self.assertIs(getattr(mod, name), getattr(SHARED, name),
                              "{}.{} is not the shared definition".format(label, name))


class ForceUtf8StaysPerFileTest(unittest.TestCase):
    """AC5: _force_utf8_streams keeps its per-file definitions; it is NOT in the shared module."""

    def test_each_instrument_defines_force_utf8_streams(self):
        for fname in ("create_issue_eval.py", "implement-context-eval.py",
                      "review-context-eval.py"):
            with open(os.path.join(_SCRIPTS, fname), encoding="utf-8") as fh:
                src = fh.read()
            self.assertIn("def _force_utf8_streams", src, fname)

    def test_shared_module_does_not_define_force_utf8_streams(self):
        self.assertFalse(hasattr(SHARED, "_force_utf8_streams"))
        with open(os.path.join(_SCRIPTS, "context_eval_shared.py"), encoding="utf-8") as fh:
            self.assertNotIn("_force_utf8_streams", fh.read())


class CoverageMapTest(unittest.TestCase):
    """AC4: the coverage map names a covering test for the extracted module."""

    def test_coverage_map_row_present(self):
        with open(os.path.join(_REPO, "lib", "test", "modules", "coverage-map.json"),
                  encoding="utf-8") as fh:
            cov = json.load(fh)
        row = cov["files"].get("scripts/context_eval_shared.py")
        self.assertIsNotNone(row, "no coverage-map row for scripts/context_eval_shared.py")
        self.assertEqual(row.get("focused_test"),
                         "lib/test/test_context_eval_shared.py")


if __name__ == "__main__":
    unittest.main()
