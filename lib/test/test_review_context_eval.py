#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Focused unit tests for scripts/review-context-eval.py (issue #1852).

Every acceptance criterion of issue #1852 that the eval or its committed fixtures can
witness maps to at least one assertion here (the parser is a machine-read boundary, so it
is tested at the parser's surface). The fixture-derived expected figures are RE-DERIVED
from the committed fixtures rather than hard-coded: `_expected_from_fixture` re-computes
each expected value straight from the raw JSONL, so changing a fixture updates the
assertion.

Driven serially from lib/test/run.sh.
"""

import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
_EVAL_PATH = os.path.join(_REPO, "scripts", "review-context-eval.py")
_FIX = os.path.join(_HERE, "fixtures", "review-eval")


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RCE = _load_module("rce", _EVAL_PATH)


def _write(dirpath, name, lines):
    os.makedirs(dirpath, exist_ok=True)
    with open(os.path.join(dirpath, name), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# ── Independent re-derivation of the expected figures from the raw fixtures (AC4) ──

def _engine_key_rederived(fp):
    """Mirror the eval's engine-subtree recognizer with independent logic.

    Shares the eval's declared ENGINE_PREFIXES constant (a re-derivation that restated the
    prefixes could not witness a wrong one), but scans for them independently.
    """
    if not isinstance(fp, str) or not fp:
        return None
    norm = fp.replace("\\", "/")
    for prefix in RCE.ENGINE_PREFIXES:
        if norm.startswith(prefix):
            return norm
        marker = "/" + prefix
        idx = norm.find(marker)
        if idx != -1:
            return norm[idx + 1:]
    return None


def _expected_from_fixture(corpus_root):
    """Re-derive the eval's per-context figures straight from the raw JSONL sessions.

    Reimplements the measurement logic — per-context grouping (main-thread by sessionId,
    subagent by agentId), residency peak, and the engine-subtree read match — independently
    of the eval, so an assertion is checked against the fixtures' own encoded content
    rather than a copied constant.
    """
    sessions = [os.path.join(dp, f)
                for dp, _d, files in os.walk(corpus_root)  # tree-walk-ok: rooted at the caller-supplied corpus dir (a fixtures subdir or a tempdir), never the repo root
                for f in sorted(files) if f.endswith(".jsonl")]
    contexts = {}
    for path in sorted(sessions):
        rel = os.path.relpath(path, corpus_root).replace(os.sep, "/")
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if rec.get("type") != "assistant":
                    continue
                if rec.get("isSidechain") is True:
                    key = "sub:" + (rec.get("agentId") or ("file:" + rel))
                    is_sub = True
                else:
                    key = "main:" + (rec.get("sessionId") or ("file:" + rel))
                    is_sub = False
                c = contexts.setdefault(
                    key, {"context": key, "is_subagent": is_sub, "peak": None,
                          "engine_reads": {}})
                usage = rec["message"].get("usage")
                if isinstance(usage, dict):
                    tot = ((usage.get("input_tokens") or 0)
                           + (usage.get("cache_read_input_tokens") or 0)
                           + (usage.get("cache_creation_input_tokens") or 0))
                    c["peak"] = tot if c["peak"] is None else max(c["peak"], tot)
                for block in rec["message"].get("content") or []:
                    if block.get("type") != "tool_use" or block.get("name") != "Read":
                        continue
                    fp = block.get("input", {}).get("file_path", "")
                    ek = _engine_key_rederived(fp)
                    if ek is not None:
                        c["engine_reads"][ek] = c["engine_reads"].get(ek, 0) + 1
    out = []
    for c in contexts.values():
        total = sum(c["engine_reads"].values())
        if total == 0:
            continue
        out.append({
            "context": c["context"],
            "is_subagent": c["is_subagent"],
            "peak_context": c["peak"] if c["peak"] is not None else RCE.UNESTABLISHED,
            "engine_reads": c["engine_reads"],
            "total_engine_reads": total,
        })
    return out


class EngineKeyRecognizerTest(unittest.TestCase):
    """AC1 recognizer: a path under skills/review/ or skills/review-and-fix/ is an engine
    file; matching is by path SUBTREE (not basename), since both subtrees carry a
    SKILL.md, and it normalizes across absolute, repo-relative and vendored spellings."""

    def test_repo_relative_engine_paths_recognized(self):
        self.assertEqual(RCE._engine_file_key("skills/review/SKILL.md"),
                         "skills/review/SKILL.md")
        self.assertEqual(
            RCE._engine_file_key("skills/review-and-fix/references/loop-control.md"),
            "skills/review-and-fix/references/loop-control.md")

    def test_absolute_and_vendored_paths_normalize_to_engine_relative_key(self):
        self.assertEqual(
            RCE._engine_file_key("/home/x/repo/skills/review/phases/phase-0-setup.md"),
            "skills/review/phases/phase-0-setup.md")
        self.assertEqual(
            RCE._engine_file_key(".prflow/vendor/prflow/skills/review/SKILL.md"),
            "skills/review/SKILL.md")

    def test_two_engine_subtrees_share_a_basename_but_not_a_key(self):
        # SKILL.md under each subtree must resolve to DISTINCT keys — a basename match
        # would collapse them into one count.
        self.assertNotEqual(RCE._engine_file_key("skills/review/SKILL.md"),
                            RCE._engine_file_key("skills/review-and-fix/SKILL.md"))

    def test_non_engine_paths_are_not_recognized(self):
        for p in ("skills/implement/SKILL.md", "scripts/review-context-eval.py",
                  "skills/reviewer/SKILL.md", "docs/review.md", "", None, 42):
            self.assertIsNone(RCE._engine_file_key(p), repr(p))

    def test_prefixes_map_to_real_on_disk_subtrees(self):
        # Coupling: every declared engine prefix names a real directory, and every .md
        # under those subtrees is recognized — so a subtree rename goes RED here rather
        # than silently reporting zero engine reads.
        for prefix in RCE.ENGINE_PREFIXES:
            self.assertTrue(os.path.isdir(os.path.join(_REPO, prefix.rstrip("/"))),
                            "engine prefix names no on-disk subtree: {}".format(prefix))
        seen = 0
        for prefix in RCE.ENGINE_PREFIXES:
            root = os.path.join(_REPO, prefix.rstrip("/"))
            for dp, _d, files in os.walk(root):  # tree-walk-ok: rooted at a fixed engine subtree (skills/review, skills/review-and-fix), not the repo root
                for f in files:
                    if not f.endswith(".md"):
                        continue
                    rel = os.path.relpath(os.path.join(dp, f), _REPO).replace(os.sep, "/")
                    self.assertEqual(RCE._engine_file_key(rel), rel, rel)
                    seen += 1
        self.assertGreater(seen, 0, "no engine .md files found on disk")


class FixtureDerivedTest(unittest.TestCase):
    """AC1/AC2/AC3: the eval's per-context figures match the committed fixtures,
    re-derived independently."""

    def test_per_context_reads_and_peak_match_rederivation(self):
        contexts, engine_totals, skipped = RCE.eval_corpus(os.path.join(_FIX, "corpus"))
        self.assertEqual(sum(skipped.values()), 0)
        got = {c["context"]: c for c in contexts}
        exp = {c["context"]: c for c in _expected_from_fixture(
            os.path.join(_FIX, "corpus"))}
        self.assertEqual(set(got), set(exp))
        for k in exp:
            self.assertEqual(got[k]["is_subagent"], exp[k]["is_subagent"], k)
            self.assertEqual(got[k]["peak_context"], exp[k]["peak_context"], k)
            self.assertEqual(got[k]["engine_reads"], exp[k]["engine_reads"], k)
            self.assertEqual(got[k]["total_engine_reads"], exp[k]["total_engine_reads"], k)

    def test_report_distinguishes_main_thread_from_subagent(self):
        # AC2: a main-thread read and a subagent read are distinguishable in the report.
        contexts, engine_totals, _ = RCE.eval_corpus(os.path.join(_FIX, "corpus"))
        kinds = {c["context"]: c["is_subagent"] for c in contexts}
        self.assertIn("main:S1", kinds)
        self.assertIn("sub:AG1", kinds)
        self.assertFalse(kinds["main:S1"])
        self.assertTrue(kinds["sub:AG1"])
        # The same engine file read by two different contexts must NOT collapse: its
        # per-file total is the sum, split by main/subagent.
        skill = engine_totals["skills/review/SKILL.md"]
        self.assertEqual(skill["total"], 3)
        self.assertEqual(skill["main_thread"], 2)
        self.assertEqual(skill["subagent"], 1)

    def test_context_with_no_engine_read_is_excluded(self):
        # AC3 scopes the per-context report to contexts that read an engine file: a
        # subagent that read only non-engine files is not reported.
        contexts, _, _ = RCE.eval_corpus(os.path.join(_FIX, "corpus"))
        self.assertNotIn("sub:AG2", {c["context"] for c in contexts})

    def test_aggregate_matches_rederivation(self):
        contexts, engine_totals, _ = RCE.eval_corpus(os.path.join(_FIX, "corpus"))
        summary = RCE.aggregate(contexts, engine_totals)
        exp = _expected_from_fixture(os.path.join(_FIX, "corpus"))
        peaks = sorted(c["peak_context"] for c in exp
                       if c["peak_context"] != RCE.UNESTABLISHED)
        self.assertEqual(summary["context_count"], len(exp))
        self.assertEqual(summary["main_thread_context_count"],
                         sum(1 for c in exp if not c["is_subagent"]))
        self.assertEqual(summary["subagent_context_count"],
                         sum(1 for c in exp if c["is_subagent"]))
        self.assertEqual(summary["total_engine_reads"],
                         sum(c["total_engine_reads"] for c in exp))
        self.assertEqual(summary["main_thread_engine_reads"],
                         sum(c["total_engine_reads"] for c in exp if not c["is_subagent"]))
        self.assertEqual(summary["subagent_engine_reads"],
                         sum(c["total_engine_reads"] for c in exp if c["is_subagent"]))
        self.assertEqual(summary["median_peak_context"], RCE._median(peaks))
        self.assertEqual(summary["max_peak_context"], max(peaks))
        self.assertEqual(summary["engine_file_count"], len(engine_totals))


class _SingleCorpusMixin:
    def _run(self, files):
        # files: {filename: [lines]}
        with tempfile.TemporaryDirectory() as d:
            for name, lines in files.items():
                _write(d, name, lines)
            return RCE.eval_corpus(d)


class BoundaryTest(_SingleCorpusMixin, unittest.TestCase):
    def test_two_contexts_reading_same_engine_file_do_not_collapse(self):
        # Implementation Notes: two contexts reading the same engine file must be two
        # counts, not one — witnessed across separate files (the real subagent layout).
        contexts, totals, _ = self._run({
            "main.jsonl": [
                '{"type":"assistant","isSidechain":false,"sessionId":"A",'
                '"message":{"usage":{"input_tokens":5},"content":[{"type":"tool_use",'
                '"id":"1","name":"Read","input":{"file_path":"skills/review/SKILL.md"}}]}}'],
            "sub.jsonl": [
                '{"type":"assistant","isSidechain":true,"agentId":"G",'
                '"message":{"usage":{"input_tokens":6},"content":[{"type":"tool_use",'
                '"id":"2","name":"Read","input":{"file_path":"skills/review/SKILL.md"}}]}}'],
        })
        self.assertEqual(len(contexts), 2)
        self.assertEqual(totals["skills/review/SKILL.md"]["total"], 2)
        self.assertEqual(totals["skills/review/SKILL.md"]["main_thread"], 1)
        self.assertEqual(totals["skills/review/SKILL.md"]["subagent"], 1)

    def test_interleaved_sidechain_in_one_file_is_its_own_context(self):
        # The OLD-style transcript layout: a sidechain record interleaved in the main
        # file. isSidechain (not the file) separates the contexts.
        contexts, _, _ = self._run({
            "s.jsonl": [
                '{"type":"assistant","isSidechain":false,"sessionId":"S",'
                '"message":{"usage":{"input_tokens":5},"content":[{"type":"tool_use",'
                '"id":"1","name":"Read","input":{"file_path":"skills/review/SKILL.md"}}]}}',
                '{"type":"assistant","isSidechain":true,"agentId":"G",'
                '"message":{"usage":{"input_tokens":6},"content":[{"type":"tool_use",'
                '"id":"2","name":"Read","input":{"file_path":'
                '"skills/review-and-fix/SKILL.md"}}]}}'],
        })
        kinds = {c["context"]: c["is_subagent"] for c in contexts}
        self.assertEqual(kinds, {"main:S": False, "sub:G": True})

    def test_missing_identity_field_falls_back_to_the_source_path(self):
        # A record whose identifying field is absent keys on its SOURCE file, and the
        # main:/sub: prefix is what keeps the two from colliding on that one shared path.
        # Expected keys are written out here rather than taken from the fixture
        # re-derivation, so a fallback bug mirrored into that oracle cannot pass.
        contexts, totals, _ = self._run({
            "s.jsonl": [
                '{"type":"assistant","isSidechain":false,'
                '"message":{"usage":{"input_tokens":5},"content":[{"type":"tool_use",'
                '"id":"1","name":"Read","input":{"file_path":"skills/review/SKILL.md"}}]}}',
                '{"type":"assistant","isSidechain":true,'
                '"message":{"usage":{"input_tokens":6},"content":[{"type":"tool_use",'
                '"id":"2","name":"Read","input":{"file_path":"skills/review/SKILL.md"}}]}}'],
        })
        self.assertEqual(
            {c["context"]: c["is_subagent"] for c in contexts},
            {"main:file:s.jsonl": False, "sub:file:s.jsonl": True})
        self.assertEqual(totals["skills/review/SKILL.md"],
                         {"total": 2, "main_thread": 1, "subagent": 1})
        self.assertEqual([c["peak_context"] for c in contexts], [5, 6])

    def test_non_string_identity_field_falls_back_to_the_source_path(self):
        # A present-but-unusable agentId is as unidentified as an absent one; without the
        # isinstance guard the key would be built from a non-string and detonate.
        contexts, _, _ = self._run({
            "sub.jsonl": [
                '{"type":"assistant","isSidechain":true,"agentId":17,'
                '"message":{"usage":{"input_tokens":6},"content":[{"type":"tool_use",'
                '"id":"1","name":"Read","input":{"file_path":"skills/review/SKILL.md"}}]}}'],
        })
        self.assertEqual([c["context"] for c in contexts], ["sub:file:sub.jsonl"])

    def test_peak_is_max_per_turn_residency(self):
        contexts, _, _ = self._run({
            "s.jsonl": [
                '{"type":"assistant","isSidechain":false,"sessionId":"S",'
                '"message":{"usage":{"input_tokens":10,"cache_read_input_tokens":20,'
                '"cache_creation_input_tokens":5,"output_tokens":99},"content":['
                '{"type":"tool_use","id":"1","name":"Read",'
                '"input":{"file_path":"skills/review/SKILL.md"}}]}}',
                '{"type":"assistant","isSidechain":false,"sessionId":"S",'
                '"message":{"usage":{"input_tokens":1},"content":[{"type":"tool_use",'
                '"id":"2","name":"Read","input":{"file_path":"skills/review/SKILL.md"}}]}}'],
        })
        # output_tokens excluded; peak is the max turn (35), not the last (1).
        self.assertEqual(contexts[0]["peak_context"], 35)

    def test_engine_reading_context_with_no_usage_reads_unestablished_peak(self):
        # unknown-is-not-zero: a context that read an engine file but carried no usage
        # object reports an UNESTABLISHED peak, never a real-looking 0.
        contexts, _, _ = self._run({
            "s.jsonl": [
                '{"type":"assistant","isSidechain":false,"sessionId":"S",'
                '"message":{"content":[{"type":"tool_use","id":"1","name":"Read",'
                '"input":{"file_path":"skills/review/SKILL.md"}}]}}'],
        })
        self.assertEqual(contexts[0]["peak_context"], RCE.UNESTABLISHED)

    def test_non_engine_read_not_counted(self):
        contexts, totals, _ = self._run({
            "s.jsonl": [
                '{"type":"assistant","isSidechain":false,"sessionId":"S",'
                '"message":{"usage":{"input_tokens":1},"content":[{"type":"tool_use",'
                '"id":"1","name":"Read",'
                '"input":{"file_path":"skills/implement/SKILL.md"}}]}}'],
        })
        self.assertEqual(contexts, [])
        self.assertEqual(totals, {})

    def test_unrecognized_record_type_is_ignored_not_skipped(self):
        # A record whose type the walker does not recognize (queue-operation, user,
        # summary) is not an engine read and not a parse failure.
        contexts, _, skipped = self._run({
            "s.jsonl": [
                '{"type":"queue-operation","operation":"enqueue"}',
                '{"type":"summary","summary":"x"}',
                '{"type":"assistant","isSidechain":false,"sessionId":"S",'
                '"message":{"usage":{"input_tokens":1},"content":[{"type":"tool_use",'
                '"id":"1","name":"Read",'
                '"input":{"file_path":"skills/review/SKILL.md"}}]}}'],
        })
        self.assertEqual(len(contexts), 1)
        self.assertEqual(sum(skipped.values()), 0)

    def test_compaction_counted_per_context(self):
        contexts, _, _ = self._run({
            "s.jsonl": [
                '{"type":"system","subtype":"compact_boundary","sessionId":"S"}',
                '{"type":"assistant","isSidechain":false,"sessionId":"S",'
                '"message":{"usage":{"input_tokens":1},"content":[{"type":"tool_use",'
                '"id":"1","name":"Read",'
                '"input":{"file_path":"skills/review/SKILL.md"}}]}}'],
        })
        self.assertEqual(contexts[0]["compact_boundary_count"], 1)


class NoEngineReadAndEmptyTest(_SingleCorpusMixin, unittest.TestCase):
    """AC6: a directory with no engine-file read produces a report stating that, exit 0."""

    def test_no_engine_read_dir_reports_and_exits_zero(self):
        out = io.StringIO()
        saved = sys.stdout
        sys.stdout = out
        try:
            rc = RCE.main([os.path.join(_FIX, "no-engine-reads")])
        finally:
            sys.stdout = saved
        self.assertEqual(rc, 0)
        self.assertIn("no engine-file read", out.getvalue())

    def test_empty_dir_reports_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as d:
            out = io.StringIO()
            saved = sys.stdout
            sys.stdout = out
            try:
                rc = RCE.main([d])
            finally:
                sys.stdout = saved
        self.assertEqual(rc, 0)
        self.assertIn("no engine-file read", out.getvalue())

    def test_missing_dir_exits_nonzero_naming_path(self):
        err = io.StringIO()
        saved = sys.stderr
        sys.stderr = err
        try:
            rc = RCE.main(["/no/such/corpus/here"])
        finally:
            sys.stderr = saved
        self.assertEqual(rc, 2)
        self.assertIn("/no/such/corpus/here", err.getvalue())


class AdversarialTest(_SingleCorpusMixin, unittest.TestCase):
    def test_malformed_records_degrade_and_are_reported(self):
        # AC5: an unparseable record is a skipped record with a reason; the run still
        # reports on the records it could parse.
        contexts, totals, skipped = self._run({
            "s.jsonl": [
                'not json at all',
                '["a","list"]',
                '{"no":"type"}',
                '{"type":"assistant","isSidechain":false,"sessionId":"S",'
                '"message":{"usage":{"input_tokens":1},"content":[{"type":"tool_use",'
                '"id":"1","name":"Read",'
                '"input":{"file_path":"skills/review/SKILL.md"}}]}}',
                '{"type":"assistant","isSidechain":false',  # truncated
            ],
        })
        self.assertEqual(len(contexts), 1)
        self.assertEqual(skipped["non_json_line"], 2)
        self.assertEqual(skipped["not_object"], 1)
        self.assertEqual(skipped["no_type"], 1)

    def test_missing_token_field_treated_as_zero(self):
        # A usage object with a missing/null sub-field is a real measured value, not a
        # missing measurement.
        contexts, _, _ = self._run({
            "s.jsonl": [
                '{"type":"assistant","isSidechain":false,"sessionId":"S",'
                '"message":{"usage":{"cache_read_input_tokens":7},"content":['
                '{"type":"tool_use","id":"1","name":"Read",'
                '"input":{"file_path":"skills/review/SKILL.md"}}]}}'],
        })
        self.assertEqual(contexts[0]["peak_context"], 7)

    def test_read_block_input_wrong_shape_is_tallied_not_detonating(self):
        saved = sys.stderr
        sys.stderr = io.StringIO()
        try:
            contexts, totals, skipped = self._run({
                "s.jsonl": [
                    '{"type":"assistant","isSidechain":false,"sessionId":"S",'
                    '"message":{"usage":{"input_tokens":1},"content":[{"type":"tool_use",'
                    '"id":"1","name":"Read","input":["not","a","dict"]}]}}',
                    '{"type":"assistant","isSidechain":false,"sessionId":"S",'
                    '"message":{"usage":{"input_tokens":2},"content":[{"type":"tool_use",'
                    '"id":"2","name":"Read",'
                    '"input":{"file_path":"skills/review/SKILL.md"}}]}}',
                    # A context reporting NO engine read still has its dropped Read
                    # accounted: excluding it from the fold would lose the tally.
                    '{"type":"assistant","isSidechain":true,"agentId":"G",'
                    '"message":{"usage":{"input_tokens":3},"content":[{"type":"tool_use",'
                    '"id":"3","name":"Read","input":{"file_path":null}}]}}'],
            })
        finally:
            sys.stderr = saved
        self.assertEqual(skipped["unresolvable_read_path"], 2)
        self.assertEqual(skipped["malformed_record"], 0)
        self.assertEqual(len(contexts), 1)

    def test_non_finite_token_value_degrades_not_detonates(self):
        # json.loads accepts bare Infinity; int(inf) raises OverflowError, which is OUTSIDE
        # eval_corpus's per-record backstop tuple — without the _usage_value guard one such
        # record aborts the whole walk. Assert the run still reports the good record.
        contexts, totals, skipped = self._run({
            "s.jsonl": [
                '{"type":"assistant","isSidechain":false,"sessionId":"S",'
                '"message":{"usage":{"input_tokens":Infinity},"content":[{"type":"tool_use",'
                '"id":"1","name":"Read","input":{"file_path":"skills/review/SKILL.md"}}]}}',
                '{"type":"assistant","isSidechain":false,"sessionId":"S",'
                '"message":{"usage":{"input_tokens":42},"content":[{"type":"tool_use",'
                '"id":"2","name":"Read","input":{"file_path":"skills/review/SKILL.md"}}]}}',
            ],
        })
        self.assertEqual(len(contexts), 1)
        # The non-finite sub-field degrades to 0, so the peak is the finite turn's 42.
        self.assertEqual(contexts[0]["peak_context"], 42)
        self.assertEqual(skipped["malformed_record"], 0)

    def test_usage_value_establishes_only_a_usable_count(self):
        # Every unusable shape reads None (unestablished), never 0 — the peak's whole
        # unknown-is-not-zero discipline rests on this one predicate.
        for bad in (float("inf"), float("nan"), True, False, "7", None, [7]):
            self.assertIsNone(RCE._usage_value({"input_tokens": bad}, "input_tokens"), bad)
        self.assertIsNone(RCE._usage_value({}, "input_tokens"))
        self.assertIsNone(RCE._usage_value("not a dict", "input_tokens"))
        self.assertEqual(RCE._usage_value({"input_tokens": 7.0}, "input_tokens"), 7)
        self.assertEqual(RCE._usage_value({"input_tokens": 0}, "input_tokens"), 0)

    def test_empty_usage_object_reads_unestablished_peak_not_zero(self):
        # A usage object carrying no usable residency field measured nothing; folding its
        # 0 into the peak would report an unmeasured turn as a real value.
        contexts, _, _ = self._run({
            "s.jsonl": [
                '{"type":"assistant","isSidechain":false,"sessionId":"S",'
                '"message":{"usage":{},"content":[{"type":"tool_use","id":"1",'
                '"name":"Read","input":{"file_path":"skills/review/SKILL.md"}}]}}',
                '{"type":"assistant","isSidechain":false,"sessionId":"S",'
                '"message":{"usage":{"output_tokens":80},"content":[{"type":"tool_use",'
                '"id":"2","name":"Read",'
                '"input":{"file_path":"skills/review/SKILL.md"}}]}}'],
        })
        self.assertEqual(contexts[0]["peak_context"], RCE.UNESTABLISHED)
        self.assertEqual(contexts[0]["usage_missing_turns"], 2)

    def test_message_wrong_shape_does_not_detonate(self):
        saved = sys.stderr
        sys.stderr = io.StringIO()
        try:
            contexts, totals, skipped = self._run({
                "s.jsonl": [
                    '{"type":"assistant","isSidechain":false,"sessionId":"S",'
                    '"message":["not","a","dict"]}',
                    '{"type":"assistant","isSidechain":false,"sessionId":"S",'
                    '"message":{"usage":{"input_tokens":9},"content":[{"type":"tool_use",'
                    '"id":"1","name":"Read",'
                    '"input":{"file_path":"skills/review/SKILL.md"}}]}}'],
            })
        finally:
            sys.stderr = saved
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0]["peak_context"], 9)
        self.assertEqual(sum(skipped.values()), 0)

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
                contexts, _totals, skipped = RCE.eval_corpus(corpus)
            finally:
                sys.stderr = saved
            self.assertEqual(contexts, [])
            self.assertEqual(skipped["unreadable_file"], 1)

    def test_symlink_escape_is_not_read_and_is_tallied(self):
        # AC7: a path escaping the supplied directory through a symlink is not read.
        with tempfile.TemporaryDirectory() as outside:
            with open(os.path.join(outside, "secret.jsonl"), "w", encoding="utf-8") as fh:
                fh.write('{"type":"assistant","isSidechain":false,"sessionId":"S",'
                         '"message":{"usage":{"input_tokens":7},"content":['
                         '{"type":"tool_use","id":"1","name":"Read",'
                         '"input":{"file_path":"skills/review/SKILL.md"}}]}}\n')
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
                    contexts, _totals, skipped = RCE.eval_corpus(corpus)
                finally:
                    sys.stderr = saved
                self.assertEqual(contexts, [],
                                 "eval read a file outside the corpus root")
                self.assertEqual(skipped["escaped_path"], 1)
                self.assertIn("escape.jsonl", err.getvalue())

    def test_determinism(self):
        # AC4: byte-identical output over the same unchanged corpus.
        a, ea, sa = RCE.eval_corpus(os.path.join(_FIX, "corpus"))
        b, eb, sb = RCE.eval_corpus(os.path.join(_FIX, "corpus"))
        self.assertEqual(a, b)
        self.assertEqual(ea, eb)
        self.assertEqual(sa, sb)
        self.assertEqual(RCE.render_text(a, ea, RCE.aggregate(a, ea), sa),
                         RCE.render_text(b, eb, RCE.aggregate(b, eb), sb))
        self.assertEqual(
            json.dumps(RCE.build_report(os.path.join(_FIX, "corpus")),
                       indent=2, sort_keys=True),
            json.dumps(RCE.build_report(os.path.join(_FIX, "corpus")),
                       indent=2, sort_keys=True))


class MedianPrimitiveTest(unittest.TestCase):
    def test_even_and_odd_and_empty(self):
        self.assertEqual(RCE._median([3, 1, 2]), 2)
        self.assertEqual(RCE._median([3, 1]), 2)
        self.assertEqual(RCE._median([1, 2, 3, 5]), 2.5)
        with self.assertRaises(ValueError):
            RCE._median([])
        self.assertEqual(RCE._median_or_unestablished([]), RCE.UNESTABLISHED)


class AggregateEmptyPopulationTest(unittest.TestCase):
    def test_empty_reads_unestablished_peak_not_zero(self):
        summary = RCE.aggregate([], {})
        self.assertEqual(summary["context_count"], 0)
        self.assertEqual(summary["median_peak_context"], RCE.UNESTABLISHED)
        self.assertEqual(summary["max_peak_context"], RCE.UNESTABLISHED)


class RenderAndCliTest(unittest.TestCase):
    def test_text_render_lists_every_summary_field(self):
        contexts, totals, skipped = RCE.eval_corpus(os.path.join(_FIX, "corpus"))
        summary = RCE.aggregate(contexts, totals)
        text = RCE.render_text(contexts, totals, summary, skipped)
        for key, value in summary.items():
            self.assertIn("- {}: {}".format(key, value), text)
        # AC1: each engine file appears with its read count.
        self.assertIn("skills/review/SKILL.md", text)

    def test_json_output_is_valid_and_sorted(self):
        out = io.StringIO()
        saved = sys.stdout
        sys.stdout = out
        try:
            rc = RCE.main([os.path.join(_FIX, "corpus"), "--format", "json"])
        finally:
            sys.stdout = saved
        self.assertEqual(rc, 0)
        parsed = json.loads(out.getvalue())
        self.assertIn("summary", parsed)
        self.assertIn("engine_files", parsed)
        self.assertIn("contexts", parsed)
        self.assertEqual(out.getvalue(),
                         json.dumps(parsed, indent=2, sort_keys=True) + "\n")


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
        with open(os.path.join(_FIX, "planted-owner-id.txt"), encoding="utf-8") as fh:
            self.assertTrue(_scan_for_secrets(fh.read()),
                            "planted positive control did not trip the secret detector")

    def test_added_files_are_clean(self):
        named = [_EVAL_PATH,
                 os.path.join(_REPO, "docs", "internal", "review-context.md")]
        for path in named:
            self.assertTrue(os.path.exists(path),
                            "secret-scan target is missing: {}".format(path))
        targets = list(named)
        for dirpath, _dirs, files in os.walk(_FIX):  # tree-walk-ok: rooted at the fixed committed review-eval fixtures subdir, not the repo root
            for f in sorted(files):
                if f == "planted-owner-id.txt":
                    continue
                targets.append(os.path.join(dirpath, f))
        for path in targets:
            with open(path, encoding="utf-8") as fh:
                hits = _scan_for_secrets(fh.read())
            self.assertFalse(hits, "owner-id/transcript shape {} in {}".format(hits, path))


class NoAutoInvocationTest(unittest.TestCase):
    """AC8: no skill, workflow, or suite gate invokes the instrument. Only its own
    focused test and the coverage-map registration may NAME it."""

    _ALLOWED_REFERENCES = frozenset({
        "scripts/review-context-eval.py",
        "lib/test/test_review_context_eval.py",
        "lib/test/modules/coverage-map.json",
        # run.sh names the script in its block comment but INVOKES the test, not the
        # script — a description, not an auto-invocation.
        "lib/test/run.sh",
    })

    def test_nothing_but_the_focused_test_invokes_the_script(self):
        needle = "review-context-eval.py"
        offenders = []
        for sub in ("skills", ".github", "scripts", "lib", ".prflow/prompt-extensions"):
            root = os.path.join(_REPO, sub)
            self.assertTrue(os.path.isdir(root),
                            "no-auto-invocation scan root is missing: {}".format(sub))

            def _walk_error(exc, _sub=sub):
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
                        self.fail("could not read {}: {}".format(rel, exc))
        self.assertEqual(sorted(offenders), [],
                         "unexpected reference(s) to the maintainer-only script: "
                         "{}".format(sorted(offenders)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
