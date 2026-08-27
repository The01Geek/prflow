#!/usr/bin/env python3
"""Focused tests for scripts/derive-run-profile.py, the workpad phase-duration parser."""

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


drp = _load("derive_run_profile", SCRIPTS / "derive-run-profile.py")

UNESTABLISHED = "unestablished"


def _body(last_updated: str, progress: str, status: str = "🎉 Complete") -> str:
    return (
        "<!-- prflow:workpad -->\n"
        "# PRFlow Workpad — Issue #99\n"
        "\n"
        f"**Status:** {status}\n"
        "**Branch:** `feature/x`\n"
        f"**Last updated:** {last_updated}\n"
        "\n"
        "## Progress\n"
        f"{progress}"
        "\n"
        "## Plan\n"
        "- [x] do the thing\n"
    )


class DeriveRunProfile(unittest.TestCase):
    def test_phase_durations_from_first_and_last_note(self):
        progress = (
            "- [x] **Setup** — branch & workpad\n"
            "  - 10:00:00 — run started\n"
            "  - 10:05:30 — workpad hydrated\n"
            "- [x] **Implement**\n"
            "  - 10:06:00 — entered Phase 2\n"
            "  - 10:20:00 — code + sweeps done\n"
        )
        out = drp.derive(_body("2026-08-26 10:30 UTC", progress))
        self.assertEqual(out["phase_durations_ms"]["Setup"], 330_000)
        self.assertEqual(out["phase_durations_ms"]["Implement"], 840_000)

    def test_final_status_word_is_stripped_of_its_glyph(self):
        progress = "- [x] **Setup** — branch & workpad\n  - 10:00:00 — run started\n"
        out = drp.derive(_body("2026-08-26 10:30 UTC", progress))
        self.assertEqual(out["final_status"], "Complete")

    def test_phase_with_a_single_note_has_zero_duration_not_unestablished(self):
        """One timestamped note is an established span of zero, never an unknown."""
        progress = "- [x] **Setup** — branch & workpad\n  - 10:00:00 — run started\n"
        out = drp.derive(_body("2026-08-26 10:30 UTC", progress))
        self.assertEqual(out["phase_durations_ms"]["Setup"], 0)

    def test_phase_with_no_timestamped_note_is_unestablished(self):
        progress = (
            "- [x] **Setup** — branch & workpad\n"
            "  - 10:00:00 — run started\n"
            "- [ ] **Documentation**\n"
        )
        out = drp.derive(_body("2026-08-26 10:30 UTC", progress))
        self.assertEqual(out["phase_durations_ms"]["Documentation"], UNESTABLISHED)

    def test_midnight_crossing_run_infers_the_day_and_never_goes_negative(self):
        """Progress timestamps are time-of-day only; the dated Last updated line
        is the only day source, so a run spanning midnight must not subtract."""
        progress = (
            "- [x] **Implement**\n"
            "  - 23:50:00 — entered Phase 2\n"
            "  - 00:10:00 — code + sweeps done\n"
        )
        out = drp.derive(_body("2026-08-27 00:30 UTC", progress))
        self.assertEqual(out["phase_durations_ms"]["Implement"], 1_200_000)

    def test_missing_last_updated_line_leaves_every_duration_unestablished(self):
        body = (
            "<!-- prflow:workpad -->\n"
            "**Status:** 🚀 Implementing\n"
            "\n"
            "## Progress\n"
            "- [x] **Setup** — branch & workpad\n"
            "  - 10:00:00 — run started\n"
            "  - 10:05:00 — hydrated\n"
        )
        out = drp.derive(body)
        self.assertEqual(out["phase_durations_ms"]["Setup"], UNESTABLISHED)

    def test_absent_progress_section_is_unestablished_not_empty(self):
        body = (
            "<!-- prflow:workpad -->\n"
            "**Status:** 🚀 Implementing\n"
            "**Last updated:** 2026-08-26 10:30 UTC\n"
            "\n"
            "## Plan\n"
            "- [ ] x\n"
        )
        out = drp.derive(body)
        self.assertEqual(out["phase_durations_ms"], UNESTABLISHED)

    def test_absent_status_line_is_unestablished(self):
        body = (
            "<!-- prflow:workpad -->\n"
            "**Last updated:** 2026-08-26 10:30 UTC\n"
            "\n"
            "## Progress\n"
            "- [x] **Setup** — branch & workpad\n"
            "  - 10:00:00 — run started\n"
        )
        self.assertEqual(drp.derive(body)["final_status"], UNESTABLISHED)

    def test_empty_body_is_unestablished_on_both_fields(self):
        out = drp.derive("")
        self.assertEqual(out["phase_durations_ms"], UNESTABLISHED)
        self.assertEqual(out["final_status"], UNESTABLISHED)

    def test_duplicate_progress_section_is_unestablished(self):
        """A duplicated section is a mutable-markdown shape the parser must refuse
        rather than silently pick one of."""
        body = (
            "<!-- prflow:workpad -->\n"
            "**Status:** 🎉 Complete\n"
            "**Last updated:** 2026-08-26 10:30 UTC\n"
            "\n"
            "## Progress\n"
            "- [x] **Setup** — branch & workpad\n"
            "  - 10:00:00 — a\n"
            "\n"
            "## Progress\n"
            "- [x] **Setup** — branch & workpad\n"
            "  - 11:00:00 — b\n"
        )
        self.assertEqual(drp.derive(body)["phase_durations_ms"], UNESTABLISHED)

    def test_malformed_timestamp_is_skipped_not_crashed(self):
        progress = (
            "- [x] **Setup** — branch & workpad\n"
            "  - 99:99:99 — nonsense\n"
            "  - 10:00:00 — real\n"
            "  - 10:02:00 — real\n"
        )
        out = drp.derive(_body("2026-08-26 10:30 UTC", progress))
        self.assertEqual(out["phase_durations_ms"]["Setup"], 120_000)

    def test_unknown_phase_heading_is_ignored(self):
        """The phase vocabulary is fixed; an unrecognized heading contributes nothing."""
        progress = (
            "- [x] **Setup** — branch & workpad\n"
            "  - 10:00:00 — a\n"
            "  - 10:01:00 — b\n"
            "- [x] **Invented**\n"
            "  - 10:02:00 — c\n"
        )
        out = drp.derive(_body("2026-08-26 10:30 UTC", progress))
        self.assertNotIn("Invented", out["phase_durations_ms"])

    def test_scalar_where_a_body_is_expected_is_unestablished(self):
        for shape in (None, 17, [], {}):
            with self.subTest(shape=shape):
                out = drp.derive(shape)
                self.assertEqual(out["phase_durations_ms"], UNESTABLISHED)
                self.assertEqual(out["final_status"], UNESTABLISHED)

    def test_main_writes_json_to_stdout_and_exits_zero(self):
        progress = "- [x] **Setup** — branch & workpad\n  - 10:00:00 — a\n  - 10:01:00 — b\n"
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "workpad.md"
            p.write_text(_body("2026-08-26 10:30 UTC", progress), encoding="utf-8")
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = drp.main(["--body-file", str(p)])
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["phase_durations_ms"]["Setup"], 60_000)
            self.assertEqual(payload["final_status"], "Complete")

    def test_main_on_an_unreadable_body_file_exits_nonzero(self):
        rc = drp.main(["--body-file", "/nonexistent/definitely/not/here.md"])
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
