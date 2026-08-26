#!/usr/bin/env python3
"""Focused tests for the occurrence-aware workflow analyzer."""

# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/analyze-workflow-runs.py"


def load_module():
    spec = importlib.util.spec_from_file_location("workflow_analyzer", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load analyzer")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_bundle(
    root: Path,
    session: str,
    *,
    captured: str,
    workflow: str = "review-and-fix",
    mode: str = "nested",
    fingerprint: str | None = "fp-a",
    occurrence_ids: tuple[str, ...] = ("review-and-fix-1",),
    models: tuple[str, ...] = ("claude-opus-4-6",),
    effort: tuple[str, ...] = ("high",),
) -> Path:
    bundle = root / ".prflow/tmp/workflow-runs" / session
    bundle.mkdir(parents=True)
    (bundle / "transcript.jsonl").write_text('{"type":"user"}\n')
    (bundle / "metadata.json").write_text(json.dumps({
        "schema_version": 2, "session_id": session, "captured_at": captured,
    }))
    occurrences = []
    for number, occurrence_id in enumerate(occurrence_ids):
        occurrences.append({
            "occurrence_id": occurrence_id,
            "workflow": workflow,
            "mode": mode,
            "parent_occurrence_id": "implement-1" if mode == "nested" else None,
            "subject": {"kind": "pull_request", "number": 500 + number},
            "invocation_source": "assistant_skill_tool" if mode == "nested" else "user_command",
            "start_event": number,
            "started_at": captured,
            "start_timestamp_source": "transcript_event",
            "boundary_confidence": "unknown",
            "preceding_context_events": number,
            "prompt_fingerprint": fingerprint,
            "observed_models": list(models),
            "observed_effort": list(effort),
            "model_effort_source": "events_within_boundary",
            "model_effort_event_count": 2,
        })
    (bundle / "occurrences.json").write_text(json.dumps(occurrences))
    (bundle / "event-summary.json").write_text(json.dumps({
        "model_effort": {"observed_models": list(models), "observed_effort": list(effort)}
    }))
    (bundle / "prompt-surfaces.json").write_text("{}")
    return bundle


class WorkflowAnalyzerTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_latest_and_filtered_last_three(self):
        for index in range(4):
            write_bundle(
                self.root, f"s{index}", captured=f"2026-07-15T00:0{index}:00Z",
                mode="nested" if index else "top-level",
            )
        selected = self.mod.select_occurrences(
            ["--last", "3", "--workflow", "review-and-fix", "--mode", "nested"], self.root
        )
        self.assertEqual([item.session_id for item in selected], ["s3", "s2", "s1"])
        latest = self.mod.select_occurrences(["latest"], self.root)
        self.assertEqual(latest[0].session_id, "s3")

    def test_latest_and_last_counts_distinct_sessions_but_keeps_matching_occurrences(self):
        write_bundle(
            self.root, "new", captured="2026-07-15T00:03:00Z",
            occurrence_ids=("review-and-fix-1", "review-and-fix-2"),
        )
        write_bundle(self.root, "middle", captured="2026-07-15T00:02:00Z")
        write_bundle(self.root, "old", captured="2026-07-15T00:01:00Z")
        latest = self.mod.select_occurrences(
            ["--workflow", "review-and-fix", "--mode", "nested", "latest"], self.root
        )
        self.assertEqual([item.session_id for item in latest], ["new", "new"])
        selected = self.mod.select_occurrences(
            ["--last", "3", "--workflow", "review-and-fix", "--mode", "nested"], self.root
        )
        self.assertEqual({item.session_id for item in selected}, {"new", "middle", "old"})
        self.assertEqual(len(selected), 4)

    def test_top_level_and_mode_all_selection(self):
        write_bundle(self.root, "nested", captured="2026-07-15T00:02:00Z")
        write_bundle(self.root, "top", captured="2026-07-15T00:01:00Z", mode="top-level")
        top = self.mod.select_occurrences(
            ["--workflow", "review-and-fix", "--mode", "top-level", "top"], self.root
        )
        self.assertEqual([item.mode for item in top], ["top-level"])
        all_modes = self.mod.select_occurrences(
            ["--workflow", "review-and-fix", "--mode", "all", "nested", "top"], self.root
        )
        self.assertEqual({item.mode for item in all_modes}, {"nested", "top-level"})

    def test_same_session_duplicates_do_not_create_recurrence(self):
        write_bundle(
            self.root, "same", captured="2026-07-15T00:00:00Z",
            occurrence_ids=("review-and-fix-1", "review-and-fix-2"),
        )
        selected = self.mod.select_occurrences(
            ["--workflow", "review-and-fix", "--mode", "nested", "same"], self.root
        )
        eligibility = self.mod.recurrence_eligibility(selected)
        self.assertFalse(eligibility["eligible"])
        self.assertEqual(eligibility["supporting_session_ids"], ["same"])

    def test_fingerprint_model_and_effort_confounders(self):
        write_bundle(self.root, "a", captured="2026-07-15T00:00:00Z", fingerprint="fp-a")
        write_bundle(
            self.root, "b", captured="2026-07-15T00:01:00Z", fingerprint="fp-b",
            models=("claude-sonnet-4-5",), effort=("medium",),
        )
        selected = self.mod.select_occurrences(
            ["--workflow", "review-and-fix", "--mode", "nested", "a", "b"], self.root
        )
        eligibility = self.mod.recurrence_eligibility(selected)
        self.assertFalse(eligibility["eligible"])
        self.assertIn("prompt_fingerprint", eligibility["confounders"])
        self.assertIn("model", eligibility["confounders"])
        self.assertIn("effort", eligibility["confounders"])

    def test_cohort_document_supplies_established_model_and_effort_facts(self):
        write_bundle(
            self.root, "a", captured="2026-07-15T00:00:00Z",
            models=("claude-opus-4-6",), effort=("high",),
        )
        selected = self.mod.select_occurrences(["a"], self.root)
        cohort = self.mod._cohort_document(selected, self.mod.recurrence_eligibility(selected))
        facts = cohort["occurrences"][0]["model_effort"]
        self.assertEqual(facts["observed_models"], ["claude-opus-4-6"])
        self.assertEqual(facts["observed_effort"], ["high"])
        self.assertEqual(facts["observed_source"], "events_within_boundary")

    def test_session_summary_fills_empty_occurrence_model_and_effort_facts(self):
        bundle = write_bundle(
            self.root, "a", captured="2026-07-15T00:00:00Z",
            models=("claude-opus-4-6",), effort=("high",),
        )
        occurrences = json.loads((bundle / "occurrences.json").read_text())
        occurrences[0]["observed_models"] = []
        occurrences[0]["observed_effort"] = []
        occurrences[0]["model_effort_source"] = None
        (bundle / "occurrences.json").write_text(json.dumps(occurrences))
        selected = self.mod.select_occurrences(["a"], self.root)
        cohort = self.mod._cohort_document(selected, self.mod.recurrence_eligibility(selected))
        facts = cohort["occurrences"][0]["model_effort"]
        self.assertEqual(facts["observed_models"], ["claude-opus-4-6"])
        self.assertEqual(facts["observed_effort"], ["high"])
        self.assertEqual(facts["observed_source"], "session_summary_fallback")

    def test_recurrence_needs_two_distinct_sessions_exactly_at_the_threshold(self):
        write_bundle(self.root, "one", captured="2026-07-15T00:00:00Z")
        one = self.mod.recurrence_eligibility(self.mod.select_occurrences(["--last", "1"], self.root))
        self.assertFalse(one["eligible"])
        self.assertEqual(one["eligible_groups"], [])

        # A second distinct session matching on workflow, mode, and fingerprint is the
        # exact point the threshold admits recurrence.
        write_bundle(self.root, "two", captured="2026-07-15T00:01:00Z")
        two = self.mod.recurrence_eligibility(self.mod.select_occurrences(["--last", "2"], self.root))
        self.assertTrue(two["eligible"])
        self.assertEqual(two["eligible_groups"], [["one", "two"]])

    def test_absent_and_corrupted_event_summaries_are_reported_distinctly(self):
        absent = write_bundle(self.root, "absent", captured="2026-07-15T00:00:00Z")
        (absent / "event-summary.json").unlink()
        corrupted = write_bundle(self.root, "corrupted", captured="2026-07-15T00:01:00Z")
        (corrupted / "event-summary.json").write_text("{not json")
        present = write_bundle(self.root, "present", captured="2026-07-15T00:02:00Z")
        self.assertTrue((present / "event-summary.json").is_file())

        statuses = {
            bundle.session_id: bundle.event_summary_status for bundle in self.mod._discover(self.root)
        }
        self.assertEqual(
            statuses, {"absent": "absent", "corrupted": "corrupted", "present": "present"}
        )

        selected = self.mod.select_occurrences(["--last", "3"], self.root)
        document = self.mod._cohort_document(selected, self.mod.recurrence_eligibility(selected))
        self.assertEqual(
            {item["session_id"]: item["event_summary_status"] for item in document["occurrences"]},
            {"absent": "absent", "corrupted": "corrupted", "present": "present"},
        )

    def test_unusable_bundle_is_dropped_with_a_breadcrumb_naming_it(self):
        write_bundle(self.root, "usable", captured="2026-07-15T00:00:00Z")
        unusable = write_bundle(self.root, "unusable", captured="2026-07-15T00:01:00Z")
        (unusable / "occurrences.json").write_text("{not json")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            discovered = self.mod._discover(self.root)

        # Dropping the bundle silently would make vanished evidence look like evidence
        # that was never captured, so the drop must name the bundle it discarded.
        self.assertEqual([bundle.session_id for bundle in discovered], ["usable"])
        self.assertIn("skipping unusable bundle", stderr.getvalue())
        self.assertIn("unusable", stderr.getvalue())

    def test_analyst_timeout_default_override_and_malformed_values(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEVFLOW_CLAUDE_TIMEOUT", None)
            self.assertEqual(self.mod._analyst_timeout(), self.mod.DEFAULT_ANALYST_TIMEOUT_SECONDS)
        with mock.patch.dict(os.environ, {"DEVFLOW_CLAUDE_TIMEOUT": "12.5"}):
            self.assertEqual(self.mod._analyst_timeout(), 12.5)
        # A malformed or non-positive override degrades to the default with a breadcrumb
        # rather than disabling the timeout the guard exists to enforce.
        for raw in ("nonsense", "0", "-1", "inf", "nan", " "):
            with self.subTest(raw=raw), mock.patch.dict(os.environ, {"DEVFLOW_CLAUDE_TIMEOUT": raw}):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    self.assertEqual(
                        self.mod._analyst_timeout(), self.mod.DEFAULT_ANALYST_TIMEOUT_SECONDS
                    )
                self.assertIn("DEVFLOW_CLAUDE_TIMEOUT", stderr.getvalue())

    def test_unsafe_session_ids_are_rejected(self):
        with self.assertRaisesRegex(self.mod.AnalysisError, "unsafe session id"):
            self.mod.select_occurrences(["../escape"], self.root)

    def test_strict_delimiters_and_slug_validation(self):
        with self.assertRaisesRegex(self.mod.AnalysisError, "exactly one report"):
            self.mod.parse_output("no report", [], {})
        malformed = """<!-- DEVFLOW_REPORT_BEGIN -->\nok\n<!-- DEVFLOW_REPORT_END -->
<!-- DEVFLOW_ISSUE_BEGIN slug=Bad_Slug runs=a,b -->\nbody\n<!-- DEVFLOW_ISSUE_END -->"""
        with self.assertRaisesRegex(self.mod.AnalysisError, "malformed"):
            self.mod.parse_output(malformed, ["a", "b"], {"eligible": True, "eligible_groups": [["a", "b"]]})

    def test_single_session_can_never_emit_issues(self):
        output = """<!-- DEVFLOW_REPORT_BEGIN -->\nok\n<!-- DEVFLOW_REPORT_END -->
<!-- DEVFLOW_ISSUE_BEGIN slug=slow runs=a,b -->\nbody\n<!-- DEVFLOW_ISSUE_END -->"""
        with self.assertRaisesRegex(self.mod.AnalysisError, "single-session"):
            self.mod.parse_output(output, ["a"], {"eligible": False, "eligible_groups": []})

    def test_legacy_bundle_is_normalized_without_writes(self):
        bundle = self.root / ".prflow/tmp/implement-runs/legacy"
        bundle.mkdir(parents=True)
        (bundle / "transcript.jsonl").write_text('{"type":"user"}\n')
        metadata = {
            "session_id": "legacy", "captured_at": "2026-07-15T00:00:00Z",
            "issue_number": 520, "prompt_fingerprint": "old-fp",
        }
        (bundle / "metadata.json").write_text(json.dumps(metadata))
        before = sorted(path.name for path in bundle.iterdir())
        normalized = self.mod.load_legacy_implement_bundle(bundle)
        self.assertEqual(normalized.occurrences[0]["mode"], "top-level")
        self.assertEqual(normalized.occurrences[0]["subject"]["number"], 520)
        self.assertEqual(normalized.occurrences[0]["prompt_fingerprint"], "old-fp")
        self.assertEqual(before, sorted(path.name for path in bundle.iterdir()))

    def test_fake_claude_receives_only_exact_read_only_flags_and_nonzero_is_diagnostic(self):
        write_bundle(self.root, "a", captured="2026-07-15T00:00:00Z")
        fake = self.root / "fake-claude"
        argv_log = self.root / "argv.json"
        fake.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$ARGV_LOG\"\nexit \"${FAKE_EXIT:-0}\"\n")
        fake.chmod(0o755)
        env = os.environ.copy()
        env.update({"DEVFLOW_CLAUDE_BIN": str(fake), "ARGV_LOG": str(argv_log), "FAKE_EXIT": "7"})
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--acknowledge-provider-access", "--repository-root", str(self.root), "a"],
            env=env, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 1)
        argv = argv_log.read_text().splitlines()
        self.assertEqual(argv[:6], [
            "--safe-mode", "--print", "--permission-mode", "dontAsk",
            "--allowedTools", "Read,Grep,Glob",
        ])
        self.assertFalse(any(forbidden in argv for forbidden in ("Write", "Edit", "Bash", "Web", "MCP")))
        diagnostics = list((self.root / ".prflow/tmp/workflow-analyses").glob("*/model-error.txt"))
        self.assertEqual(len(diagnostics), 1)

    def test_provider_access_requires_explicit_acknowledgement(self):
        write_bundle(self.root, "a", captured="2026-07-15T00:00:00Z")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--repository-root", str(self.root), "a"],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("--acknowledge-provider-access", result.stderr)

    def test_successful_comparable_cohort_writes_report_manifest_and_safe_issue(self):
        write_bundle(self.root, "a", captured="2026-07-15T00:00:00Z")
        write_bundle(self.root, "b", captured="2026-07-15T00:01:00Z")
        fake = self.root / "fake-claude"
        fake.write_text("""#!/bin/sh
printf '%s\n' '<!-- DEVFLOW_REPORT_BEGIN -->' ok '<!-- DEVFLOW_REPORT_END -->' '<!-- DEVFLOW_ISSUE_BEGIN slug=slow-step runs=a,b -->' issue '<!-- DEVFLOW_ISSUE_END -->'
""")
        fake.chmod(0o755)
        env = os.environ.copy()
        env["DEVFLOW_CLAUDE_BIN"] = str(fake)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--acknowledge-provider-access", "--repository-root", str(self.root),
             "--workflow", "review-and-fix", "--mode", "nested", "a", "b"],
            env=env, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = Path(result.stdout.strip())
        self.assertTrue((output / "comparison-report.md").is_file())
        self.assertTrue((output / "cohort.json").is_file())
        self.assertTrue((output / "issue-drafts/slow-step.md").is_file())


if __name__ == "__main__":
    unittest.main()
