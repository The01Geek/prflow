#!/usr/bin/env python3
"""Focused tests for scripts/implement-timeline.py, the execution-transcript timeline parser."""

# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(modname: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


tl = _load("implement_timeline", SCRIPTS / "implement-timeline.py")

UNESTABLISHED = "unestablished"


def _rec(ts, role, content):
    return json.dumps({"timestamp": ts, "message": {"role": role, "content": content}})


def _read(path, tool_id):
    return {"type": "tool_use", "id": tool_id, "name": "Read", "input": {"file_path": path}}


def _tool(name, tool_id, **inp):
    return {"type": "tool_use", "id": tool_id, "name": name, "input": inp}


def _result(tool_id):
    return {"type": "tool_result", "tool_use_id": tool_id, "content": "ok"}


def _jsonl(*lines):
    return "\n".join(lines) + "\n"


# One production-realistic captured transcript: an implement run that reads its phase-1
# reference, runs two Bash calls, moves to phase 2, and reads one review-engine phase
# file (which must NOT re-attribute the phase).
REALISTIC = _jsonl(
    _rec("2026-08-26T10:00:00.000Z", "user", "implement 2006"),
    _rec("2026-08-26T10:00:01.000Z", "assistant",
         [_read("skills/implement/phases/phase-1-setup.md", "t1")]),
    _rec("2026-08-26T10:00:03.000Z", "user", [_result("t1")]),
    _rec("2026-08-26T10:00:04.000Z", "assistant", [_tool("Bash", "t2", command="git status")]),
    _rec("2026-08-26T10:00:09.000Z", "user", [_result("t2")]),
    _rec("2026-08-26T10:00:10.000Z", "assistant", [_tool("Bash", "t3", command="gh issue view")]),
    _rec("2026-08-26T10:00:20.000Z", "user", [_result("t3")]),
    _rec("2026-08-26T10:00:21.000Z", "assistant",
         [_read("skills/implement/phases/phase-2-implement.md", "t4")]),
    _rec("2026-08-26T10:00:23.000Z", "user", [_result("t4")]),
    _rec("2026-08-26T10:00:24.000Z", "assistant",
         [_read("skills/review/phases/phase-3-agents.md", "t5")]),
    _rec("2026-08-26T10:00:30.000Z", "user", [_result("t5")]),
)


class Attribution(unittest.TestCase):
    def test_phase_totals_use_the_full_implement_phase_path(self):
        out = tl.build_timeline(REALISTIC)
        phases = out["phases"]
        self.assertIn("skills/implement/phases/phase-1-setup.md", phases)
        self.assertIn("skills/implement/phases/phase-2-implement.md", phases)

    def test_a_review_engine_phase_read_never_becomes_a_phase(self):
        """A bare phase-number match would attribute skills/review/phases/* to an
        implement phase; the full-path match is what prevents it."""
        out = tl.build_timeline(REALISTIC)
        self.assertNotIn("skills/review/phases/phase-3-agents.md", out["phases"])

    def test_work_before_the_first_phase_read_is_unattributed(self):
        early = _jsonl(
            _rec("2026-08-26T09:59:00.000Z", "assistant", [_tool("Bash", "e1", command="pwd")]),
            _rec("2026-08-26T09:59:03.000Z", "user", [_result("e1")]),
        ) + REALISTIC
        out = tl.build_timeline(early)
        self.assertEqual(out["phases"]["unattributed"], 3_000)

    def test_the_read_that_opens_a_phase_is_charged_to_the_phase_it_opens(self):
        """t4 opens phase 2 (2s) and t5 runs inside it (6s), so phase 2 holds both.
        Charging the opening Read backwards would credit phase 1 with phase 2's entry."""
        out = tl.build_timeline(REALISTIC)
        self.assertEqual(out["phases"]["skills/implement/phases/phase-2-implement.md"], 8_000)
        self.assertEqual(out["phases"]["skills/implement/phases/phase-1-setup.md"], 17_000)

    def test_per_activity_groups_by_tool_name_across_phases(self):
        out = tl.build_timeline(REALISTIC)
        self.assertEqual(out["activities"]["Bash"], 15_000)
        self.assertEqual(out["activities"]["Read"], 10_000)

    def test_per_step_preserves_order_phase_tool_and_duration(self):
        out = tl.build_timeline(REALISTIC)
        steps = out["steps"]
        self.assertEqual([s["tool"] for s in steps], ["Read", "Bash", "Bash", "Read", "Read"])
        self.assertEqual(steps[1]["duration_ms"], 5_000)
        self.assertEqual(steps[0]["phase"], "skills/implement/phases/phase-1-setup.md")
        self.assertEqual(steps[1]["phase"], "skills/implement/phases/phase-1-setup.md")


class MalformedInputs(unittest.TestCase):
    def test_empty_artifact_reports_no_steps_and_does_not_raise(self):
        out = tl.build_timeline("")
        self.assertEqual(out["steps"], [])
        self.assertEqual(out["phases"], {})
        self.assertEqual(out["activities"], {})

    def test_truncated_final_jsonl_record_is_skipped_and_the_rest_survives(self):
        truncated = REALISTIC + '{"timestamp": "2026-08-26T10:00:31.000Z", "mess'
        out = tl.build_timeline(truncated)
        self.assertEqual(len(out["steps"]), 5)
        self.assertIn("skipped 1 unparseable record", " ".join(out["diagnostics"]))

    def test_transcript_with_no_workpad_status_transitions_still_reports(self):
        """No phase Read at all: everything is unattributed rather than absent."""
        plain = _jsonl(
            _rec("2026-08-26T10:00:00.000Z", "assistant", [_tool("Bash", "a", command="ls")]),
            _rec("2026-08-26T10:00:04.000Z", "user", [_result("a")]),
        )
        out = tl.build_timeline(plain)
        self.assertEqual(out["phases"], {"unattributed": 4_000})

    def test_denied_tool_call_with_no_tool_result_is_unestablished_and_excluded(self):
        denied = _jsonl(
            _rec("2026-08-26T10:00:00.000Z", "assistant", [_tool("Bash", "d1", command="rm -rf /")]),
            _rec("2026-08-26T10:00:02.000Z", "assistant", [_tool("Bash", "d2", command="ls")]),
            _rec("2026-08-26T10:00:05.000Z", "user", [_result("d2")]),
        )
        out = tl.build_timeline(denied)
        denied_step = [s for s in out["steps"] if s["tool_use_id"] == "d1"][0]
        self.assertEqual(denied_step["duration_ms"], UNESTABLISHED)
        # d1 contributes nothing to either sum; only d2's 3s does.
        self.assertEqual(out["activities"]["Bash"], 3_000)

    def test_wrong_type_json_record_is_skipped_not_crashed(self):
        mixed = _jsonl("[1, 2, 3]", '"a bare string"', "17") + REALISTIC
        out = tl.build_timeline(mixed)
        self.assertEqual(len(out["steps"]), 5)
        self.assertIn("skipped 3 unparseable record", " ".join(out["diagnostics"]))

    def test_a_different_workflows_transcript_yields_no_implement_phases(self):
        """This tool reads input the repository does not itself produce, so a transcript
        from another workflow must degrade to unattributed rather than inventing phases."""
        other = _jsonl(
            _rec("2026-08-26T10:00:00.000Z", "assistant",
                 [_read("skills/review/phases/phase-0-setup.md", "x1")]),
            _rec("2026-08-26T10:00:06.000Z", "user", [_result("x1")]),
        )
        out = tl.build_timeline(other)
        self.assertEqual(list(out["phases"]), ["unattributed"])

    def test_records_with_no_timestamp_are_unestablished_not_zero(self):
        no_ts = _jsonl(
            json.dumps({"message": {"role": "assistant",
                                    "content": [_tool("Bash", "n1", command="ls")]}}),
            _rec("2026-08-26T10:00:05.000Z", "user", [_result("n1")]),
        )
        out = tl.build_timeline(no_ts)
        self.assertEqual(out["steps"][0]["duration_ms"], UNESTABLISHED)

    def test_a_decreasing_timestamp_pair_is_unestablished_not_negative(self):
        backwards = _jsonl(
            _rec("2026-08-26T10:00:10.000Z", "assistant", [_tool("Bash", "b1", command="ls")]),
            _rec("2026-08-26T10:00:05.000Z", "user", [_result("b1")]),
        )
        out = tl.build_timeline(backwards)
        self.assertEqual(out["steps"][0]["duration_ms"], UNESTABLISHED)


class CliSurface(unittest.TestCase):
    def test_json_flag_writes_the_same_structure_it_prints(self):
        with tempfile.TemporaryDirectory() as td:
            art = Path(td) / "transcript.jsonl"
            art.write_text(REALISTIC, encoding="utf-8")
            out_path = Path(td) / "out.json"
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = tl.main(["--transcript", str(art), "--json", str(out_path)])
            self.assertEqual(rc, 0)
            written = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(written, tl.build_timeline(REALISTIC))
            self.assertIn("Bash", buf.getvalue())

    def test_expired_artifact_prints_a_notice_naming_the_expiry_and_exits_zero(self):
        calls = []

        def fake_download(run_id, dest, repo=None):
            calls.append(run_id)
            raise tl.ArtifactExpired(
                f"no artifact matching claude-execution-transcript-{run_id}")

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = tl.main(["--run-id", "12345"], _download=fake_download)
        self.assertEqual(rc, 0)
        self.assertIn("expired", buf.getvalue().lower())
        self.assertIn("12345", buf.getvalue())
        self.assertEqual(calls, ["12345"])

    def test_run_id_and_transcript_are_mutually_exclusive_required_inputs(self):
        with self.assertRaises(SystemExit):
            tl.main([])


class DownloadFailureClassification(unittest.TestCase):
    """The two failures below are different facts, and the expired notice must not claim
    the one it did not observe. Both strings are the bytes `gh run download` actually
    printed, reproduced against this repository."""

    def test_a_real_run_with_no_matching_artifact_classifies_expired(self):
        self.assertEqual(
            tl._classify_download_failure("no valid artifacts found to download"),
            "expired")

    def test_a_nonexistent_run_id_classifies_run_missing_not_expired(self):
        observed = ("error fetching artifacts: HTTP 404: Not Found "
                    "(https://api.github.com/repos/o/r/actions/runs/99999999/artifacts?per_page=100)")
        self.assertEqual(tl._classify_download_failure(observed), "run-missing")

    def test_an_unrecognized_failure_is_other_not_silently_expired(self):
        self.assertEqual(tl._classify_download_failure("HTTP 500: Internal Server Error"),
                         "other")

    def test_empty_stderr_is_other(self):
        self.assertEqual(tl._classify_download_failure(""), "other")


if __name__ == "__main__":
    unittest.main()
