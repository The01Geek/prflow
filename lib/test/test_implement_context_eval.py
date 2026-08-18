#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Focused unit tests for scripts/implement-context-eval.py (issue #1209).

Every acceptance criterion of issue #1209 that the eval or its committed fixtures can
witness maps to at least one assertion here. The written-record ACs (AC5/AC6/AC7) are
discharged by docs/internal/implement-context.md, not by a suite test.

The fixture-derived expected figures are RE-DERIVED from the committed fixtures
(AC4/T1) rather than hard-coded: `_expected_from_fixture` re-computes each expected
value straight from the raw JSONL, so changing a fixture updates the assertion.

Driven serially from lib/test/run.sh.
"""

import datetime
import io
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
_EVAL_PATH = os.path.join(_REPO, "scripts", "implement-context-eval.py")
_FIX = os.path.join(_HERE, "fixtures", "implement-eval")


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ICE = _load_module("ice", _EVAL_PATH)


def _write(dirpath, name, lines):
    os.makedirs(dirpath, exist_ok=True)
    with open(os.path.join(dirpath, name), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# ── Independent re-derivation of the expected figures from the raw fixtures (AC4) ──

def _expected_from_fixture(session_paths, corpus_root):
    """Re-derive the eval's per-run figures straight from raw JSONL session files.

    This reimplements the *measurement logic* (context sum, main-thread filtering,
    phase-file basename match, tool-call bucketing, inter-turn gaps) independently of the
    eval — including an independent timestamp parse (`strptime` rather than the eval's
    `fromisoformat` path) — so an assertion is checked against the fixtures' own encoded
    content rather than a copied constant.

    It shares the eval's declared CONSTANTS: `PHASE_FILES`, `PHASE_READ_LABELS`,
    `TOOL_CATEGORY_BY_NAME`, `TOOL_CATEGORY_LABELS`, `OTHER_TOOL_CATEGORY`,
    `ATTRIBUTION`, `GAP_DECIMALS`, `UNESTABLISHED`. A re-derivation that restated a table
    could not witness a wrong one, so the two tables that decide an attribution carry
    their own coupling checks: `PHASE_FILES`/`PHASE_READ_LABELS` against the on-disk
    phase directory (`PhaseFileSetCouplingTest`) and `TOOL_CATEGORY_BY_NAME` against
    literal expectations (`ToolCategoryTableTest`, which also reconciles
    `TOOL_CATEGORY_LABELS`). `ATTRIBUTION` is derived at import from
    `lib/plugin_identity.py` and its degraded arms are driven by
    `AttributionFallbackTest`; only `GAP_DECIMALS` and `UNESTABLISHED` are scalars with
    no independent source to reconcile against.
    """
    runs = []
    for path in sorted(session_paths):
        peaks, phase = [], {label: 0 for label in ICE.PHASE_READ_LABELS}
        tools = {label: 0 for label in ICE.TOOL_CATEGORY_LABELS}
        times = []
        attributed = False
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("type") != "assistant":
                    continue
                if rec.get("isSidechain") is True:
                    continue
                if rec.get("attributionSkill") not in ICE.ATTRIBUTION:
                    continue
                attributed = True
                usage = rec["message"].get("usage")
                if isinstance(usage, dict):
                    peaks.append(
                        (usage.get("input_tokens") or 0)
                        + (usage.get("cache_read_input_tokens") or 0)
                        + (usage.get("cache_creation_input_tokens") or 0))
                saw_tool = False
                for block in rec["message"].get("content") or []:
                    if block.get("type") != "tool_use":
                        continue
                    saw_tool = True
                    tools[ICE.TOOL_CATEGORY_BY_NAME.get(
                        block.get("name"), ICE.OTHER_TOOL_CATEGORY)] += 1
                    if block.get("name") == "Read":
                        fp = block.get("input", {}).get("file_path", "")
                        base = os.path.basename(fp)
                        label = ICE.PHASE_FILES.get(base)
                        # Independently mirror the gated-sweep-reference rule (issue #1739):
                        # a sweep-*.md basename counts toward phase2 (shared constants, own
                        # logic — not a call into _phase_label_for_read).
                        if (label is None
                                and base.startswith(ICE.SWEEP_REFERENCE_PREFIX)
                                and base.endswith(ICE.SWEEP_REFERENCE_SUFFIX)):
                            label = ICE.SWEEP_REFERENCE_PHASE
                        if label is not None:
                            phase[label] += 1
                if saw_tool and rec.get("timestamp"):
                    # Independent stamp parse: the fixtures are all UTC `...Z` stamps.
                    times.append(datetime.datetime.strptime(
                        rec["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(
                            tzinfo=datetime.timezone.utc).timestamp())
        if attributed:
            ordered = sorted(times)
            gaps = [round(b - a, ICE.GAP_DECIMALS)
                    for a, b in zip(ordered, ordered[1:])]
            runs.append({
                "source": os.path.relpath(path, corpus_root).replace(os.sep, "/"),
                "peak_context": max(peaks) if peaks else ICE.UNESTABLISHED,
                "phase_reads": phase,
                "total_phase_reads": sum(phase.values()),
                "tool_calls": tools,
                "total_tool_calls": sum(tools.values()),
                "gaps": gaps,
            })
    return runs


class FixtureDerivedTest(unittest.TestCase):
    """T1: the eval's figures match what the committed fixtures encode, re-derived."""

    def _corpus_sessions(self, corpus):
        root = os.path.join(_FIX, corpus)
        return [os.path.join(dp, f)
                for dp, _d, files in os.walk(root)  # tree-walk-ok: rooted at the fixed committed implement-eval fixtures subdir, not the repo root
                for f in files if f.endswith(".jsonl")]

    def _expected(self, corpus):
        root = os.path.join(_FIX, corpus)
        return _expected_from_fixture(self._corpus_sessions(corpus), root)

    def test_corpus_matches_independent_rederivation(self):
        runs, skipped = ICE.eval_corpus(os.path.join(_FIX, "corpus"))
        expected = self._expected("corpus")
        self.assertEqual(sum(skipped.values()), 0)
        got = {r["source"]: r for r in runs}
        exp = {r["source"]: r for r in expected}
        self.assertEqual(set(got), set(exp))
        for src in exp:
            self.assertEqual(got[src]["peak_context"], exp[src]["peak_context"], src)
            self.assertEqual(got[src]["phase_reads"], exp[src]["phase_reads"], src)
            self.assertEqual(
                got[src]["total_phase_reads"], exp[src]["total_phase_reads"], src)

    def test_tool_call_buckets_match_independent_rederivation(self):
        # AC10: per-run tool calls bucketed by category, re-derived from the fixtures.
        runs, _ = ICE.eval_corpus(os.path.join(_FIX, "corpus"))
        exp = {r["source"]: r for r in self._expected("corpus")}
        got = {r["source"]: r for r in runs}
        self.assertEqual(set(got), set(exp))
        for src in exp:
            self.assertEqual(got[src]["tool_calls"], exp[src]["tool_calls"], src)
            self.assertEqual(
                got[src]["total_tool_calls"], exp[src]["total_tool_calls"], src)
            # The buckets partition the population: they sum to the reported total.
            self.assertEqual(sum(got[src]["tool_calls"].values()),
                             got[src]["total_tool_calls"], src)
        # The corpus must exercise more than one category, or the bucketing is untested.
        exercised = {label for r in runs for label, n in r["tool_calls"].items() if n}
        self.assertGreater(len(exercised), 1, "fixtures exercise only one tool category")

    def test_tool_call_gaps_match_independent_rederivation(self):
        # AC11: median, max AND total of the inter-tool-call wall-clock gaps.
        runs, _ = ICE.eval_corpus(os.path.join(_FIX, "corpus"))
        exp = {r["source"]: r for r in self._expected("corpus")}
        for r in runs:
            gaps = exp[r["source"]]["gaps"]
            got = r["tool_call_gaps"]
            self.assertEqual(got["count"], len(gaps), r["source"])
            self.assertEqual(got["median_seconds"], ICE._median(gaps), r["source"])
            self.assertEqual(got["max_seconds"], max(gaps), r["source"])
            self.assertEqual(got["total_seconds"],
                             round(sum(gaps), ICE.GAP_DECIMALS), r["source"])
        # A mean alone would hide the tail, so the fixture must carry an uneven
        # distribution for the median/max distinction to be witnessed at all.
        self.assertNotEqual(runs[0]["tool_call_gaps"]["median_seconds"],
                            runs[0]["tool_call_gaps"]["max_seconds"])

    def test_aggregate_median_and_max_are_rederivable(self):
        # AC3: median AND max are reported so tail behaviour is visible.
        runs, _ = ICE.eval_corpus(os.path.join(_FIX, "corpus"))
        summary = ICE.aggregate(runs)
        expected = self._expected("corpus")
        peaks = sorted(r["peak_context"] for r in expected)
        self.assertEqual(summary["run_count"], len(expected))
        self.assertEqual(summary["median_peak_context"], ICE._median(peaks))
        self.assertEqual(summary["max_peak_context"], max(peaks))
        for label in ICE.PHASE_READ_LABELS:
            counts = sorted(r["phase_reads"][label] for r in expected)
            self.assertEqual(summary["median_{}_reads".format(label)], ICE._median(counts))
            self.assertEqual(summary["max_{}_reads".format(label)], max(counts))
            self.assertEqual(summary["total_{}_reads".format(label)], sum(counts))

    def test_tool_call_and_gap_axes_are_aggregated_too(self):
        # AC12: both new axes are aggregated across the corpus on the peak's footing.
        runs, _ = ICE.eval_corpus(os.path.join(_FIX, "corpus"))
        summary = ICE.aggregate(runs)
        expected = self._expected("corpus")
        for label in ICE.TOOL_CATEGORY_LABELS:
            counts = sorted(r["tool_calls"][label] for r in expected)
            self.assertEqual(summary["median_{}_calls".format(label)], ICE._median(counts))
            self.assertEqual(summary["max_{}_calls".format(label)], max(counts))
            self.assertEqual(summary["total_{}_calls".format(label)], sum(counts))
        totals = [r["total_tool_calls"] for r in expected]
        self.assertEqual(summary["median_total_tool_calls"], ICE._median(totals))
        self.assertEqual(summary["max_total_tool_calls"], max(totals))
        run_maxima = [max(r["gaps"]) for r in expected if r["gaps"]]
        run_totals = [round(sum(r["gaps"]), ICE.GAP_DECIMALS)
                      for r in expected if r["gaps"]]
        self.assertEqual(summary["median_run_max_gap_seconds"], ICE._median(run_maxima))
        self.assertEqual(summary["max_run_max_gap_seconds"], max(run_maxima))
        self.assertEqual(summary["median_run_total_gap_seconds"], ICE._median(run_totals))
        self.assertEqual(summary["max_run_total_gap_seconds"], max(run_totals))
        self.assertEqual(summary["corpus_total_gap_seconds"],
                         round(sum(run_totals), ICE.GAP_DECIMALS))


class PhaseReadCountTest(unittest.TestCase):
    """AC2 + T2: per-phase read count is reported, separate from peak, and counts every
    re-entry rather than the phase once."""

    def test_peak_and_phase_reads_are_distinct_reported_axes(self):
        runs, _ = ICE.eval_corpus(os.path.join(_FIX, "corpus"))
        for r in runs:
            self.assertIn("peak_context", r)
            self.assertIn("phase_reads", r)
            self.assertEqual(set(r["phase_reads"]), set(ICE.PHASE_READ_LABELS))

    def test_phase3_reentry_counts_every_reentry(self):
        # T2: a run that re-enters Phase 3 several times; the phase-3 count reflects
        # every re-entry, not the phase once. Re-derived from the fixture, so the
        # assertion tracks the fixture rather than a transcribed count.
        root = os.path.join(_FIX, "phase3-reentry")
        runs, _ = ICE.eval_corpus(root)
        self.assertEqual(len(runs), 1)
        expected = _expected_from_fixture(
            [os.path.join(root, "session-phase3-reentry.jsonl")], root)
        self.assertEqual(runs[0]["phase_reads"]["phase3"],
                         expected[0]["phase_reads"]["phase3"])
        self.assertGreater(runs[0]["phase_reads"]["phase3"], 1,
                           "the fixture must exercise more than one phase-3 re-entry")


class _SingleSessionMixin:
    def _run_one(self, lines):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "s.jsonl", lines)
            return ICE.eval_corpus(d)


class BoundaryTest(_SingleSessionMixin, unittest.TestCase):
    def test_zero_attributed_turns_emits_no_run(self):
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"other","message":{"usage":{"input_tokens":5}}}',
        ])
        self.assertEqual(runs, [])

    def test_one_turn_run_context_sum(self):
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"prflow:implement",'
            '"message":{"usage":{"input_tokens":10,"cache_read_input_tokens":20,'
            '"cache_creation_input_tokens":5,"output_tokens":3}}}',
        ])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["turn_count"], 1)
        # output_tokens is excluded from the residency axis.
        self.assertEqual(runs[0]["peak_context"], 35)

    def test_null_usage_subfield_treated_as_zero(self):
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"prflow:implement",'
            '"message":{"usage":{"input_tokens":null,"cache_read_input_tokens":7}}}',
        ])
        self.assertEqual(runs[0]["peak_context"], 7)

    def test_sidechain_read_and_context_excluded(self):
        # A sidechain (subagent) record reading a phase file must not count on either
        # axis: the phase files are read by the orchestrator main thread.
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"prflow:implement",'
            '"message":{"usage":{"input_tokens":1}}}',
            '{"type":"assistant","isSidechain":true,"attributionSkill":"prflow:implement",'
            '"message":{"usage":{"input_tokens":999},"content":['
            '{"type":"tool_use","id":"s1","name":"Read",'
            '"input":{"file_path":"skills/implement/phases/phase-3-review.md"}}]}}',
        ])
        self.assertEqual(runs[0]["peak_context"], 1)
        self.assertEqual(runs[0]["phase_reads"]["phase3"], 0)

    def test_devflow_namespace_also_attributed(self):
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"devflow:implement",'
            '"message":{"usage":{"input_tokens":8}}}',
        ])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["peak_context"], 8)

    def test_vendored_path_basename_matches(self):
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"prflow:implement",'
            '"message":{"usage":{"input_tokens":1},"content":['
            '{"type":"tool_use","id":"v1","name":"Read","input":{"file_path":'
            '".prflow/vendor/prflow/skills/implement/phases/phase-1-setup.md"}}]}}',
        ])
        self.assertEqual(runs[0]["phase_reads"]["phase1"], 1)

    def test_non_phase_read_not_counted(self):
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"prflow:implement",'
            '"message":{"usage":{"input_tokens":1},"content":['
            '{"type":"tool_use","id":"n1","name":"Read",'
            '"input":{"file_path":"skills/implement/SKILL.md"}}]}}',
        ])
        self.assertEqual(runs[0]["total_phase_reads"], 0)

    def test_compaction_counted(self):
        runs, _ = self._run_one([
            '{"type":"system","subtype":"compact_boundary"}',
            '{"type":"assistant","attributionSkill":"prflow:implement",'
            '"message":{"usage":{"input_tokens":1}}}',
        ])
        self.assertEqual(runs[0]["compact_boundary_count"], 1)

    def test_usage_absent_turn_is_tallied_not_zeroed(self):
        # An attributed run whose every turn lacks a usage object has NO measured
        # residency: its peak/final read UNESTABLISHED (never a real-looking 0), and the
        # missing turns are tallied — the silent-zero this instrument guards against.
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"prflow:implement","message":{}}',
            '{"type":"assistant","attributionSkill":"prflow:implement","message":{}}',
        ])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["peak_context"], ICE.UNESTABLISHED)
        self.assertEqual(runs[0]["final_context"], ICE.UNESTABLISHED)
        self.assertEqual(runs[0]["usage_missing_turns"], 2)

    def test_partial_usage_missing_keeps_measured_peak(self):
        # A run with one usage-less turn and one usage-bearing turn keeps the measured
        # peak from the turn that HAD usage — the missing one is tallied, not folded in
        # as a 0 that would drag the peak down.
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"prflow:implement","message":{}}',
            '{"type":"assistant","attributionSkill":"prflow:implement",'
            '"message":{"usage":{"input_tokens":50}}}',
        ])
        self.assertEqual(runs[0]["peak_context"], 50)
        self.assertEqual(runs[0]["usage_missing_turns"], 1)

    def test_usage_present_all_null_subfields_is_a_real_zero(self):
        # A usage OBJECT present with all-null sub-fields is a legitimate measured 0 (not
        # a missing measurement): it appends 0 and is NOT tallied as usage-missing.
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"prflow:implement",'
            '"message":{"usage":{"input_tokens":null}}}',
        ])
        self.assertEqual(runs[0]["peak_context"], 0)
        self.assertEqual(runs[0]["usage_missing_turns"], 0)


class ToolCallAndGapBoundaryTest(_SingleSessionMixin, unittest.TestCase):
    """AC10/AC11 boundary behaviour the committed corpus cannot express."""

    def test_unusable_timestamp_is_tallied_not_a_zero_gap(self):
        # AC11 + the unknown-is-not-zero rule: a tool-bearing turn whose timestamp is
        # unparseable leaves the gap population ACCOUNTED in the skip tally. Folding it
        # in as a 0 would silently shorten every total it appears in.
        runs, skipped = self._run_one([
            '{"type":"assistant","timestamp":"2026-01-01T00:00:00Z",'
            '"attributionSkill":"prflow:implement","message":{"usage":{"input_tokens":1},'
            '"content":[{"type":"tool_use","id":"t1","name":"Bash","input":{}}]}}',
            '{"type":"assistant","timestamp":"not-a-timestamp",'
            '"attributionSkill":"prflow:implement","message":{"usage":{"input_tokens":1},'
            '"content":[{"type":"tool_use","id":"t2","name":"Bash","input":{}}]}}',
            '{"type":"assistant","attributionSkill":"prflow:implement",'
            '"message":{"usage":{"input_tokens":1},'
            '"content":[{"type":"tool_use","id":"t3","name":"Bash","input":{}}]}}',
            '{"type":"assistant","timestamp":"2026-01-01T00:00:20Z",'
            '"attributionSkill":"prflow:implement","message":{"usage":{"input_tokens":1},'
            '"content":[{"type":"tool_use","id":"t4","name":"Bash","input":{}}]}}',
        ])
        self.assertEqual(skipped["unusable_timestamp"], 2)
        # The corpus-wide tally cannot say WHICH run is affected, so the per-run counter
        # and the contamination marker must both carry it.
        self.assertEqual(runs[0]["unusable_timestamp_turns"], 2)
        self.assertTrue(runs[0]["tool_call_gaps"]["spans_dropped_turns"])
        gaps = runs[0]["tool_call_gaps"]
        # Two usable stamps 20s apart -> exactly one gap of 20s. Had the two unusable
        # turns contributed 0-gaps there would be three gaps and a 0 median.
        self.assertEqual(gaps["count"], 1)
        self.assertEqual(gaps["median_seconds"], 20.0)
        self.assertEqual(gaps["total_seconds"], 20.0)
        # All four tool calls still count on the AC10 axis — an unusable timestamp
        # removes the turn from the GAP population only.
        self.assertEqual(runs[0]["tool_calls"]["shell_commands"], 4)

    def test_single_tool_call_run_has_unestablished_gaps_not_zero(self):
        runs, _ = self._run_one([
            '{"type":"assistant","timestamp":"2026-01-01T00:00:00Z",'
            '"attributionSkill":"prflow:implement","message":{"usage":{"input_tokens":1},'
            '"content":[{"type":"tool_use","id":"s1","name":"Read",'
            '"input":{"file_path":"x.md"}}]}}',
        ])
        gaps = runs[0]["tool_call_gaps"]
        self.assertEqual(gaps["count"], 0)
        for field in ("median_seconds", "max_seconds", "total_seconds"):
            self.assertEqual(gaps[field], ICE.UNESTABLISHED, field)

    def test_unmapped_tool_name_lands_in_other_not_dropped(self):
        runs, _ = self._run_one([
            '{"type":"assistant","timestamp":"2026-01-01T00:00:00Z",'
            '"attributionSkill":"prflow:implement","message":{"usage":{"input_tokens":1},'
            '"content":[{"type":"tool_use","id":"u1","name":"SomeFutureTool","input":{}},'
            '{"type":"tool_use","id":"u2","name":"Write","input":{}},'
            '{"type":"tool_use","id":"u3","name":"Bash","input":{}}]}}',
        ])
        self.assertEqual(runs[0]["tool_calls"][ICE.OTHER_TOOL_CATEGORY], 1)
        self.assertEqual(runs[0]["tool_calls"]["file_edits_writes"], 1)
        self.assertEqual(runs[0]["total_tool_calls"], 3)
        # AC10's whole motivation: three calls in ONE turn. A regression that folded the
        # tool-call axis back onto a per-turn count would report 1 here.
        self.assertEqual(runs[0]["turn_count"], 1)

    def test_gaps_are_turn_boundaries_not_per_call(self):
        # The disclosed proxy, pinned: a transcript record carries one timestamp however
        # many tool calls its turn holds, so a 3-call turn followed by a 1-call turn
        # yields ONE gap, not three. If this ever becomes per-call the pin goes RED
        # rather than the documented granularity drifting silently.
        runs, _ = self._run_one([
            '{"type":"assistant","timestamp":"2026-01-01T00:00:00Z",'
            '"attributionSkill":"prflow:implement","message":{"usage":{"input_tokens":1},'
            '"content":[{"type":"tool_use","id":"g1","name":"Bash","input":{}},'
            '{"type":"tool_use","id":"g2","name":"Bash","input":{}},'
            '{"type":"tool_use","id":"g3","name":"Bash","input":{}}]}}',
            '{"type":"assistant","timestamp":"2026-01-01T00:00:12Z",'
            '"attributionSkill":"prflow:implement","message":{"usage":{"input_tokens":1},'
            '"content":[{"type":"tool_use","id":"g4","name":"Bash","input":{}}]}}',
        ])
        self.assertEqual(runs[0]["total_tool_calls"], 4)
        self.assertEqual(runs[0]["tool_call_gaps"]["count"], 1)
        self.assertEqual(runs[0]["tool_call_gaps"]["total_seconds"], 12.0)

    def test_out_of_order_records_never_yield_a_negative_gap(self):
        # `_gap_stats` sorts rather than trusting file order; without the sort this
        # session would report a -30s gap.
        runs, _ = self._run_one([
            '{"type":"assistant","timestamp":"2026-01-01T00:00:30Z",'
            '"attributionSkill":"prflow:implement","message":{"usage":{"input_tokens":1},'
            '"content":[{"type":"tool_use","id":"o1","name":"Bash","input":{}}]}}',
            '{"type":"assistant","timestamp":"2026-01-01T00:00:00Z",'
            '"attributionSkill":"prflow:implement","message":{"usage":{"input_tokens":1},'
            '"content":[{"type":"tool_use","id":"o2","name":"Bash","input":{}}]}}',
        ])
        self.assertEqual(runs[0]["tool_call_gaps"]["total_seconds"], 30.0)
        self.assertEqual(runs[0]["tool_call_gaps"]["max_seconds"], 30.0)

    def test_sidechain_tool_calls_and_gaps_excluded(self):
        # The AC10/AC11 axes are main-thread axes: a subagent's calls must not inflate
        # either one.
        runs, _ = self._run_one([
            '{"type":"assistant","timestamp":"2026-01-01T00:00:00Z",'
            '"attributionSkill":"prflow:implement","message":{"usage":{"input_tokens":1},'
            '"content":[{"type":"tool_use","id":"m1","name":"Bash","input":{}}]}}',
            '{"type":"assistant","timestamp":"2026-01-01T09:00:00Z","isSidechain":true,'
            '"attributionSkill":"prflow:implement","message":{"usage":{"input_tokens":1},'
            '"content":[{"type":"tool_use","id":"sx","name":"Bash","input":{}}]}}',
            '{"type":"assistant","timestamp":"2026-01-01T00:00:10Z",'
            '"attributionSkill":"prflow:implement","message":{"usage":{"input_tokens":1},'
            '"content":[{"type":"tool_use","id":"m2","name":"Bash","input":{}}]}}',
        ])
        self.assertEqual(runs[0]["tool_calls"]["shell_commands"], 2)
        self.assertEqual(runs[0]["tool_call_gaps"]["max_seconds"], 10.0)


class GatedSweepReferenceTest(_SingleSessionMixin, unittest.TestCase):
    """AC1/AC3/AC4 (issue #1739): a read of a gated Phase 2.3 sweep reference
    (skills/implement/references/sweep-*.md) counts toward the phase2 read axis, matched
    by basename. test_gated_sweep_reference_read_counts_toward_phase2 is the
    removal-sensitive assertion: deleting the sweep-recognizer arm turns it RED.
    """

    def test_gated_sweep_reference_read_counts_toward_phase2(self):
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"prflow:implement",'
            '"message":{"usage":{"input_tokens":1},"content":['
            '{"type":"tool_use","id":"s1","name":"Read","input":{"file_path":'
            '"skills/implement/references/sweep-2-3-0-changed-contract.md"}}]}}',
        ])
        self.assertEqual(runs[0]["phase_reads"]["phase2"], 1)
        self.assertEqual(runs[0]["total_phase_reads"], 1)

    def test_vendored_sweep_reference_basename_also_counts(self):
        # The same file resolves at a vendored path on the cloud tier; the basename match
        # is what makes both spellings count (the instrument's deliberate design).
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"prflow:implement",'
            '"message":{"usage":{"input_tokens":1},"content":['
            '{"type":"tool_use","id":"v1","name":"Read","input":{"file_path":'
            '".prflow/vendor/prflow/skills/implement/references/'
            'sweep-2-3-7-collection-cardinality.md"}}]}}',
        ])
        self.assertEqual(runs[0]["phase_reads"]["phase2"], 1)

    def test_a_ninth_gated_sweep_is_counted_with_no_second_edit(self):
        # AC3: the population is derived by basename shape, not a transcribed list, so a
        # sweep-reference name that exists nowhere on disk today still counts.
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"prflow:implement",'
            '"message":{"usage":{"input_tokens":1},"content":['
            '{"type":"tool_use","id":"n9","name":"Read","input":{"file_path":'
            '"skills/implement/references/sweep-9-9-9-hypothetical-ninth.md"}}]}}',
        ])
        self.assertEqual(runs[0]["phase_reads"]["phase2"], 1)

    def test_non_sweep_reference_read_not_counted(self):
        # A non-sweep reference under references/ is not a gated Phase 2.3 sweep and must
        # not count toward the phase2 axis.
        runs, _ = self._run_one([
            '{"type":"assistant","attributionSkill":"prflow:implement",'
            '"message":{"usage":{"input_tokens":1},"content":['
            '{"type":"tool_use","id":"r1","name":"Read","input":{"file_path":'
            '"skills/implement/references/deferred-ac-followups.md"}}]}}',
        ])
        self.assertEqual(runs[0]["total_phase_reads"], 0)


class ToolCategoryTableTest(unittest.TestCase):
    """`TOOL_CATEGORY_BY_NAME` is a standalone mirror of the harness's tool vocabulary
    with no on-disk source to reconcile against, and `_expected_from_fixture` restates
    it — so a SWAPPED entry (`"Task": "file_reads"`) would keep every other assertion
    green while every AC10 report silently attributed one category's work to another.
    Pin the association as literals: the table IS the contract.
    """

    _EXPECTED = {
        "file_reads": {"Read", "NotebookRead"},
        "file_edits_writes": {"Edit", "MultiEdit", "Write", "NotebookEdit"},
        "shell_commands": {"Bash", "BashOutput", "KillShell"},
        "subagent_dispatches": {"Task", "Agent"},
        "skill_invocations": {"Skill"},
    }

    def test_each_tool_name_maps_to_its_expected_category(self):
        got = {}
        for name, label in ICE.TOOL_CATEGORY_BY_NAME.items():
            got.setdefault(label, set()).add(name)
        self.assertEqual(got, self._EXPECTED)

    def test_labels_cover_the_five_named_categories_plus_the_catch_all(self):
        # AC10 names five categories at minimum; `other` is the catch-all that makes the
        # buckets a partition of the whole tool-call population.
        self.assertEqual(
            set(ICE.TOOL_CATEGORY_LABELS),
            set(self._EXPECTED) | {ICE.OTHER_TOOL_CATEGORY})
        self.assertEqual(ICE._tool_category("NoSuchTool"), ICE.OTHER_TOOL_CATEGORY)
        self.assertEqual(ICE._tool_category(None), ICE.OTHER_TOOL_CATEGORY)


class TimestampParseTest(unittest.TestCase):
    """`_parse_timestamp`'s arms the UTC-`Z` fixtures cannot reach."""

    def test_offset_naive_and_lowercase_forms_agree_on_the_same_instant(self):
        utc = ICE._parse_timestamp("2026-01-01T12:00:00Z")
        self.assertIsNotNone(utc)
        # A naive stamp is read as UTC, so it names the same instant as the `Z` form.
        self.assertEqual(ICE._parse_timestamp("2026-01-01T12:00:00"), utc)
        self.assertEqual(ICE._parse_timestamp("2026-01-01T12:00:00z"), utc)
        # An offset-bearing stamp names the same instant two hours later on the wall
        # clock. Getting this wrong shifts a mixed-offset corpus's gaps by hours.
        self.assertEqual(ICE._parse_timestamp("2026-01-01T14:00:00+02:00"), utc)

    def test_unusable_shapes_return_none_rather_than_a_number(self):
        for bad in ("", "   ", "not-a-timestamp", None, 12345, []):
            self.assertIsNone(ICE._parse_timestamp(bad), repr(bad))


class MedianPrimitiveTest(unittest.TestCase):
    """`_median` is the one place a 0-collapse could re-enter, so drive it directly."""

    def test_even_and_odd_populations(self):
        # The even branch keeps an int when the two central values divide evenly, and
        # yields a float when they do not — that split exists to keep output
        # byte-stable, and nothing else exercises it.
        self.assertEqual(ICE._median([3, 1, 2]), 2)          # odd: the middle value
        self.assertEqual(ICE._median([3, 1]), 2)             # even, sum divides evenly
        self.assertEqual(ICE._median([1, 2, 3, 5]), 2.5)     # even, sum does not
        self.assertEqual(ICE._median([1, 2]), 1.5)
        self.assertEqual(ICE._median([1, 2, 3, 4]), 2.5)
        self.assertIsInstance(ICE._median([3, 1]), int)
        self.assertIsInstance(ICE._median([1, 2]), float)

    def test_empty_population_refuses_rather_than_returning_zero(self):
        with self.assertRaises(ValueError):
            ICE._median([])
        self.assertEqual(ICE._median_or_unestablished([]), ICE.UNESTABLISHED)


class AttributionFallbackTest(unittest.TestCase):
    """`_attribution_ids` exists to prevent a vacuous zero-run measurement; each of its
    degraded arms must produce `_FALLBACK_ATTRIBUTION` (canonical + superseded) rather
    than an empty set, a superseded-only set, or a traceback."""

    def _with_identity_path(self, path):
        saved_path, saved_err = ICE._IDENTITY_PATH, sys.stderr
        ICE._IDENTITY_PATH = path
        sys.stderr = io.StringIO()
        try:
            return ICE._attribution_ids(), sys.stderr.getvalue()
        finally:
            ICE._IDENTITY_PATH, sys.stderr = saved_path, saved_err

    def test_missing_identity_source_falls_back_with_a_breadcrumb(self):
        with tempfile.TemporaryDirectory() as d:
            ids, err = self._with_identity_path(os.path.join(d, "absent.py"))
        self.assertEqual(ids, ICE._FALLBACK_ATTRIBUTION)
        self.assertIn("implement-context-eval", err)

    def test_raising_identity_source_falls_back_instead_of_detonating(self):
        # lib/plugin_identity.py is FAIL-CLOSED and raises when the identifier set
        # cannot be established; without the guard that exception would escape module
        # import and even `--help` would die.
        with tempfile.TemporaryDirectory() as d:
            _write(d, "boom.py", [
                "class IdentityError(Exception):",
                "    pass",
                "def agent_namespaces():",
                "    raise IdentityError('no identity file')",
            ])
            ids, err = self._with_identity_path(os.path.join(d, "boom.py"))
        self.assertEqual(ids, ICE._FALLBACK_ATTRIBUTION)
        self.assertIn("IdentityError", err)

    def test_malformed_namespace_shape_falls_back(self):
        # The success path is the one that always runs. If agent_namespaces() ever
        # stopped returning colon-terminated namespaces, `ids` would be NON-empty (so
        # the emptiness guard never fires), every record would mismatch, and the eval
        # would report zero runs with no error.
        with tempfile.TemporaryDirectory() as d:
            _write(d, "bare.py", ["def agent_namespaces():", "    return ['prflow']"])
            ids, err = self._with_identity_path(os.path.join(d, "bare.py"))
        self.assertEqual(ids, ICE._FALLBACK_ATTRIBUTION)
        self.assertIn("malformed", err)

    def test_empty_namespace_set_falls_back(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "empty.py", ["def agent_namespaces():", "    return []"])
            ids, err = self._with_identity_path(os.path.join(d, "empty.py"))
        self.assertEqual(ids, ICE._FALLBACK_ATTRIBUTION)
        self.assertIn("empty", err)


class AdversarialTest(_SingleSessionMixin, unittest.TestCase):
    def test_malformed_records_degrade_and_are_reported(self):
        runs, skipped = self._run_one([
            'not json at all',
            '["a","list","not","an","object"]',
            '{"no":"type field"}',
            '{"type":"assistant","attributionSkill":"prflow:implement",'
            '"message":{"usage":{"input_tokens":4}}}',
            '{"type":"assistant","attributionSkill":"prflow:implement"',  # truncated
        ])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["turn_count"], 1)
        self.assertEqual(skipped["non_json_line"], 2)
        self.assertEqual(skipped["not_object"], 1)
        self.assertEqual(skipped["no_type"], 1)

    def test_message_wrong_shape_does_not_detonate(self):
        saved = sys.stderr
        sys.stderr = io.StringIO()
        try:
            runs, skipped = self._run_one([
                '{"type":"assistant","attributionSkill":"prflow:implement",'
                '"message":["not","a","dict"]}',
                '{"type":"assistant","attributionSkill":"prflow:implement",'
                '"message":{"usage":{"input_tokens":9}}}',
            ])
        finally:
            sys.stderr = saved
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["turn_count"], 2)
        self.assertEqual(runs[0]["peak_context"], 9)
        self.assertEqual(sum(skipped.values()), 0)

    def test_read_block_input_wrong_shape_does_not_detonate(self):
        saved = sys.stderr
        sys.stderr = io.StringIO()
        try:
            runs, skipped = self._run_one([
                '{"type":"assistant","attributionSkill":"prflow:implement",'
                '"message":{"usage":{"input_tokens":3},"content":['
                '{"type":"tool_use","id":"u1","name":"Read","input":["not","a","dict"]}]}}',
                '{"type":"assistant","attributionSkill":"prflow:implement",'
                '"message":{"usage":{"input_tokens":5}}}',
            ])
        finally:
            sys.stderr = saved
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["turn_count"], 2)
        # A wrong-shape Read `input` is not a malformed RECORD — nothing here is a
        # parse failure. The one expected tally is the timestamp-less tool-bearing turn
        # leaving the gap population (AC11), which is accounting, not degradation.
        self.assertEqual(skipped["malformed_record"], 0)
        self.assertEqual(skipped["non_json_line"], 0)
        self.assertEqual(skipped["unusable_timestamp"], 1)
        # The unusable Read `input` shape leaves the phase-read axis ACCOUNTED, not
        # silently read as "not a phase file" — which would let a renamed
        # `input.file_path` report every phase count as a real-looking 0.
        self.assertEqual(skipped["unresolvable_read_path"], 1)

    def test_defensive_dispatch_tallies_malformed_record(self):
        original = ICE.RunAccumulator.observe_system

        def _boom(self, record):
            if record.get("boom"):
                raise TypeError("synthetic malformed record")
            return original(self, record)

        saved_stderr = sys.stderr
        sys.stderr = io.StringIO()
        ICE.RunAccumulator.observe_system = _boom
        try:
            runs, skipped = self._run_one([
                '{"type":"assistant","attributionSkill":"prflow:implement",'
                '"message":{"usage":{"input_tokens":4}}}',
                '{"type":"system","boom":true}',
                '{"type":"assistant","attributionSkill":"prflow:implement",'
                '"message":{"usage":{"input_tokens":6}}}',
            ])
        finally:
            ICE.RunAccumulator.observe_system = original
            sys.stderr = saved_stderr
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["turn_count"], 2)
        self.assertEqual(skipped["malformed_record"], 1)

    def test_unreadable_session_file_is_tallied(self):
        with tempfile.TemporaryDirectory() as corpus:
            link = os.path.join(corpus, "broken.jsonl")
            try:
                os.symlink(os.path.join(corpus, "missing-target.jsonl"), link)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable on this host")
            err = io.StringIO()
            saved = sys.stderr
            sys.stderr = err
            try:
                runs, skipped = ICE.eval_corpus(corpus)
            finally:
                sys.stderr = saved
            self.assertEqual(runs, [])
            self.assertEqual(skipped["unreadable_file"], 1)
            self.assertIn("broken.jsonl", err.getvalue())

    def test_determinism(self):
        # Byte-identical OUTPUT is the claim, so compare the rendered text and JSON —
        # comparing only the in-process return values would miss a render that relies on
        # an unstable ordering.
        a, sa = ICE.eval_corpus(os.path.join(_FIX, "corpus"))
        b, sb = ICE.eval_corpus(os.path.join(_FIX, "corpus"))
        self.assertEqual(a, b)
        self.assertEqual(sa, sb)
        self.assertEqual(ICE.render_text(a, ICE.aggregate(a), sa),
                         ICE.render_text(b, ICE.aggregate(b), sb))
        self.assertEqual(
            json.dumps({"runs": a, "summary": ICE.aggregate(a), "skipped": sa},
                       indent=2, sort_keys=True),
            json.dumps({"runs": b, "summary": ICE.aggregate(b), "skipped": sb},
                       indent=2, sort_keys=True))

    def test_symlink_escape_is_not_read_and_is_tallied(self):
        # The escaped_path guard is a security control: a symlink whose realpath escapes
        # the corpus root must never be read, and the drop must be tallied +
        # breadcrumbed, not silent.
        with tempfile.TemporaryDirectory() as outside:
            with open(os.path.join(outside, "secret.jsonl"), "w", encoding="utf-8") as fh:
                fh.write('{"type":"assistant","attributionSkill":"prflow:implement",'
                         '"message":{"usage":{"input_tokens":7}}}\n')
            with tempfile.TemporaryDirectory() as corpus:
                link = os.path.join(corpus, "escape.jsonl")
                try:
                    os.symlink(os.path.join(outside, "secret.jsonl"), link)
                except (OSError, NotImplementedError):
                    self.skipTest("symlinks unavailable on this host")
                err = io.StringIO()
                saved = sys.stderr
                sys.stderr = err
                try:
                    runs, skipped = ICE.eval_corpus(corpus)
                finally:
                    sys.stderr = saved
                self.assertEqual(runs, [], "eval read a file outside the corpus root")
                self.assertEqual(skipped["escaped_path"], 1)
                self.assertIn("escape.jsonl", err.getvalue())

    def test_walk_error_is_recorded(self):
        # An os.walk that cannot descend a directory (permission denied) is tallied under
        # walk_error via the onerror callback — default onerror=None would swallow it.
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("running as root: chmod-based permission block is ineffective")
        with tempfile.TemporaryDirectory() as corpus:
            blocked = os.path.join(corpus, "blocked")
            os.makedirs(blocked)
            with open(os.path.join(blocked, "s.jsonl"), "w", encoding="utf-8") as fh:
                fh.write('{"type":"assistant","attributionSkill":"prflow:implement",'
                         '"message":{"usage":{"input_tokens":1}}}\n')
            os.chmod(blocked, 0o000)
            try:
                try:
                    os.listdir(blocked)
                    self.skipTest("host does not enforce dir permission block")
                except OSError:
                    pass
                err = io.StringIO()
                saved = sys.stderr
                sys.stderr = err
                try:
                    _runs, skipped = ICE.eval_corpus(corpus)
                finally:
                    sys.stderr = saved
                self.assertEqual(skipped["walk_error"], 1)
                self.assertIn("blocked", err.getvalue())
            finally:
                os.chmod(blocked, 0o700)


class AggregateEmptyPopulationTest(unittest.TestCase):
    def test_empty_corpus_reads_unestablished_except_run_count(self):
        summary = ICE.aggregate([])
        self.assertEqual(summary["run_count"], 0)
        for key, value in summary.items():
            if key == "run_count":
                continue
            self.assertEqual(value, ICE.UNESTABLISHED,
                             "{} must be unestablished on an empty population".format(key))

    def test_usage_less_run_excluded_from_peak_population(self):
        # A run whose peak is UNESTABLISHED (no usage on any turn) is counted in
        # run_count but must not enter the peak median/max as a 0.
        with tempfile.TemporaryDirectory() as d:
            _write(d, "measured.jsonl", [
                '{"type":"assistant","attributionSkill":"prflow:implement",'
                '"message":{"usage":{"input_tokens":300000}}}'])
            _write(d, "usageless.jsonl", [
                '{"type":"assistant","attributionSkill":"prflow:implement","message":{}}'])
            runs, _ = ICE.eval_corpus(d)
            summary = ICE.aggregate(runs)
            self.assertEqual(summary["run_count"], 2)
            # Only the measured run enters the peak stats — not a 0 from the usage-less one.
            self.assertEqual(summary["median_peak_context"], 300000)
            self.assertEqual(summary["max_peak_context"], 300000)
            self.assertEqual(summary["runs_over_200k"], 1)
            self.assertEqual(summary["total_usage_missing_turns"], 1)

    def test_all_runs_usage_less_reads_unestablished_peak_not_zero(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "a.jsonl", [
                '{"type":"assistant","attributionSkill":"prflow:implement","message":{}}'])
            runs, _ = ICE.eval_corpus(d)
            summary = ICE.aggregate(runs)
            self.assertEqual(summary["run_count"], 1)
            self.assertEqual(summary["median_peak_context"], ICE.UNESTABLISHED)
            self.assertEqual(summary["max_peak_context"], ICE.UNESTABLISHED)
            self.assertEqual(summary["runs_over_200k"], ICE.UNESTABLISHED)


class RenderAndCliTest(unittest.TestCase):
    def test_text_render_lists_every_summary_field_with_its_value(self):
        runs, skipped = ICE.eval_corpus(os.path.join(_FIX, "corpus"))
        summary = ICE.aggregate(runs)
        text = ICE.render_text(runs, summary, skipped)
        for key, value in summary.items():
            # Assert the rendered PAIR, not just the key: the key half is true by
            # construction (render_text iterates summary.items()), while the value half
            # catches a unit suffix pasted onto the sentinel ("unestablisheds").
            self.assertIn("- {}: {}".format(key, value), text)

    def test_unestablished_renders_as_the_bare_sentinel(self):
        summary = ICE.aggregate([])
        text = ICE.render_text([], summary, ICE.new_skip_tally())
        self.assertIn("- max_peak_context: unestablished", text)
        self.assertNotIn("unestablisheds", text)

    def test_axis_exclusions_are_not_counted_as_skipped_records(self):
        # Neither exclusion is bad transcript data; folding either into the skipped
        # headline would report a clean corpus as malformed.
        skipped = ICE.new_skip_tally()
        skipped["unusable_timestamp"] = 4
        skipped["unresolvable_read_path"] = 2
        skipped["non_json_line"] = 1
        text = ICE.render_text([], ICE.aggregate([]), skipped)
        self.assertIn("## Skipped records and files: 1", text)
        self.assertIn("unusable timestamp): 4", text)
        self.assertIn("unresolvable path): 2", text)

    def test_missing_corpus_exits_nonzero_naming_path(self):
        err = io.StringIO()
        saved = sys.stderr
        sys.stderr = err
        try:
            rc = ICE.main(["/no/such/corpus/here"])
        finally:
            sys.stderr = saved
        self.assertEqual(rc, 2)
        self.assertIn("/no/such/corpus/here", err.getvalue())

    def test_json_output_is_valid_and_sorted(self):
        out = io.StringIO()
        saved = sys.stdout
        sys.stdout = out
        try:
            rc = ICE.main([os.path.join(_FIX, "corpus"), "--format", "json"])
        finally:
            sys.stdout = saved
        self.assertEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        self.assertIn("summary", parsed)
        # Re-derived from the committed corpus, not transcribed: adding a fixture
        # session updates this expectation rather than turning the test RED. Derived
        # through _expected_from_fixture rather than a raw file count, so a future
        # negative-control session carrying no attributed turn does not turn it RED for
        # the wrong reason.
        root = os.path.join(_FIX, "corpus")
        sessions = [os.path.join(dp, f)
                    for dp, _d, files in os.walk(root)  # tree-walk-ok: rooted at the fixed committed implement-eval fixtures subdir, not the repo root
                    for f in files if f.endswith(".jsonl")]
        self.assertEqual(parsed["summary"]["run_count"],
                         len(_expected_from_fixture(sessions, root)))
        # `sort_keys=True` is what makes the JSON byte-stable; assert it rather than
        # only naming it in the test's title.
        self.assertEqual(out.getvalue(),
                         json.dumps(parsed, indent=2, sort_keys=True) + "\n")


# ── Owner-id / transcript-shape scan over the eval, its findings doc, and the
#    committed fixtures. This is NOT a scan of every file the change touches: the test
#    file itself carries the detector patterns as literals and is deliberately out of
#    scope, as are the registration edits (run.sh, coverage-map, config, matcher-probe,
#    the changeset). ──

_SECRET_PATTERNS = [
    re.compile(r"the01geek"),
    re.compile(r"/Users/"),
    re.compile(r"\.claude-3/jobs"),
    re.compile(r"-Users-[a-z0-9]+-repos"),
]


def _scan_for_secrets(text):
    return [p.pattern for p in _SECRET_PATTERNS if p.search(text)]


class SecretDetectorTest(unittest.TestCase):
    def test_detector_fires_on_planted_control(self):
        planted = os.path.join(_FIX, "planted-owner-id.txt")
        with open(planted, encoding="utf-8") as fh:
            hits = _scan_for_secrets(fh.read())
        self.assertTrue(hits, "planted positive control did not trip the secret detector")

    def test_added_files_are_clean(self):
        # The two named targets MUST exist. A `continue` past a missing one would make
        # the scan silently stop covering a renamed or relocated file while staying
        # green — a scan reporting "clean" about a file it never read.
        named = [_EVAL_PATH, os.path.join(_REPO, "docs", "internal", "implement-context.md")]
        for path in named:
            self.assertTrue(os.path.exists(path),
                            "secret-scan target is missing (renamed or moved?): "
                            "{}".format(path))
        targets = list(named)
        for dirpath, _dirs, files in os.walk(_FIX):  # tree-walk-ok: rooted at the fixed committed implement-eval fixtures subdir, not the repo root
            for f in sorted(files):
                if f == "planted-owner-id.txt":
                    continue
                targets.append(os.path.join(dirpath, f))
        for path in targets:
            with open(path, encoding="utf-8") as fh:
                hits = _scan_for_secrets(fh.read())
            self.assertFalse(hits, "owner-id/transcript shape {} found in {}".format(hits, path))


class PhaseFileSetCouplingTest(unittest.TestCase):
    """PHASE_FILES is a standalone mirror of the four implement phase files (the eval
    imports nothing from the skill). Reconcile it against the on-disk phases/ directory
    so a phase-file rename/add/remove goes RED here rather than silently under-reporting
    that phase's read count as 0 — the same silent-zero failure mode the derived
    ATTRIBUTION set is built to avoid.
    """

    def test_phase_files_match_the_on_disk_phase_dir(self):
        phase_dir = os.path.join(_REPO, "skills", "implement", "phases")
        on_disk = {f for f in os.listdir(phase_dir) if f.endswith(".md")}
        self.assertEqual(
            set(ICE.PHASE_FILES), on_disk,
            "PHASE_FILES must exactly mirror skills/implement/phases/*.md; a phase "
            "rename/add/remove was not mirrored into scripts/implement-context-eval.py")

    def test_phase_read_labels_are_unique_and_cover_every_phase_file(self):
        # Do not restore a 1:1 basename-to-label assertion: members of one phase share a label
        # by design, so it would fail on the correct mapping. One label per phase number binds.
        phase_numbers = {re.match(r"phase-(\d+)-", b).group(1) for b in ICE.PHASE_FILES}
        self.assertEqual(len(set(ICE.PHASE_FILES.values())), len(phase_numbers))
        self.assertEqual(set(ICE.PHASE_READ_LABELS), set(ICE.PHASE_FILES.values()))

    def test_each_basename_maps_to_its_own_phase_number(self):
        # The set-level checks above survive a SWAPPED mapping (phase-3-review.md ->
        # "phase2"): the key set is intact and the labels stay unique, while every
        # report silently attributes one phase's re-read count to another. Derive the
        # expected label from the basename itself so the association is checked, not
        # restated.
        for basename, label in sorted(ICE.PHASE_FILES.items()):
            m = re.match(r"phase-(\d+)-", basename)
            self.assertIsNotNone(
                m, "phase file {} does not carry a phase number".format(basename))
            self.assertEqual(label, "phase{}".format(m.group(1)),
                             "{} is reported under the wrong phase label".format(basename))


class NoAutoInvocationTest(unittest.TestCase):
    """AC1 + T3: nothing invokes the script automatically; only its own test does."""

    # References that NAME the script but do not INVOKE it are allowed: the script's own
    # file (its Usage docstring names itself), its own focused test, and the coverage-map
    # registration (a data file mapping the script to its focused test). Everything else
    # matching the basename would be an auto-invoker and fails the invariant.
    _ALLOWED_REFERENCES = frozenset({
        "scripts/implement-context-eval.py",
        "lib/test/test_implement_context_eval.py",
        "lib/test/modules/coverage-map.json",
        # run.sh names the script in its block comment but INVOKES the test, not the
        # script — a description, not an auto-invocation.
        "lib/test/run.sh",
    })

    def test_nothing_but_the_focused_test_invokes_the_script(self):
        # AC1/T3: search the trees an auto-invoker could live in — skills/,
        # .github/ (workflows AND composite actions), scripts/, and lib/ (which includes
        # lib/test/, where T3 expects the test + registration to be the only hits) — and
        # confirm the only files naming the script are the allowed registration/self set.
        # `.prflow/prompt-extensions` is in scope because a consumer prompt extension's
        # bytes are appended verbatim to the implementing agent's prompt, so a line there
        # telling a run to invoke the eval IS the auto-invocation this test forbids.
        # `.prflow/logs` and `.prflow/learnings` are machine-appended corpora that quote
        # arbitrary run text, so they are not part of the runtime path.
        needle = "implement-context-eval.py"
        offenders = []
        for sub in ("skills", ".github", "scripts", "lib", ".prflow/prompt-extensions"):
            root = os.path.join(_REPO, sub)
            # Assert rather than `continue`: a renamed or relocated subtree would
            # otherwise drop out of the scan silently and the invariant would report as
            # holding over a tree never walked. Same reason test_added_files_are_clean
            # asserts its named targets exist.
            self.assertTrue(os.path.isdir(root),
                            "no-auto-invocation scan root is missing (renamed or "
                            "moved?): {}".format(sub))

            def _walk_error(exc, _sub=sub):
                # os.walk's default onerror=None DISCARDS a scandir failure, so an
                # undescendable directory would yield zero entries and read as clean.
                self.fail("could not walk {} while checking the no-auto-invocation "
                          "invariant: {}".format(_sub, exc))

            for dirpath, dirs, files in os.walk(root, onerror=_walk_error):  # tree-walk-ok: rooted at fixed subtrees (skills/.github/scripts/lib/.prflow/prompt-extensions), not the repo root
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for f in files:
                    p = os.path.join(dirpath, f)
                    rel = os.path.relpath(p, _REPO)
                    if rel in self._ALLOWED_REFERENCES:
                        continue
                    try:
                        with open(p, encoding="utf-8", errors="replace") as fh:
                            if needle in fh.read():
                                offenders.append(rel)
                    except OSError as exc:
                        # A file the scan could not open is UNKNOWN, not clean: skipping
                        # it would report the invariant as holding over a file never
                        # checked.
                        self.fail("could not read {} while checking the "
                                  "no-auto-invocation invariant: {}".format(rel, exc))
        self.assertEqual(sorted(offenders), [],
                         "unexpected reference(s) to the maintainer-only script: "
                         "{}".format(sorted(offenders)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
