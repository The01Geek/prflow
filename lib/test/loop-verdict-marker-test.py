#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Unit tests for scripts/loop-verdict-marker.py (issue #1212).

Drives the SHIPPED helper as a subprocess over the compose + read matrix and
every AC5 safe-direction branch. Exit 0 == all green; exit 1 with a diff on the
first failure, matching the lib/test/normalize-verdicts-test.py idiom (run.sh
drives it with a single assert_eq). Stdlib-only; no gh/network/git.

Coverage:
  * compose: each of the six results -> its token; the exact full-coverage phrase
    -> coverage=full and every other phrase -> not-verified; an unmappable result
    exits 3 with NO marker line.
  * read: reads LINE 1 ONLY (a marker on line 3 is NO-MARKER); each valid marker
    routes to its closed-vocabulary token; and every AC5 fail-closed branch
    (no marker, malformed grammar, unknown result token, unknown coverage token,
    empty input) never yields CLEAN-FULL.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

HELPER = str(Path(__file__).resolve().parent.parent.parent / "scripts" / "loop-verdict-marker.py")

_failures: list[str] = []


def _run(args: list[str], stdin: str | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, HELPER, *args],
        input=stdin,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def check(name: str, expected, actual) -> None:
    if expected != actual:
        _failures.append(f"{name}\n  expected: {expected!r}\n  actual:   {actual!r}")


# ── compose ──────────────────────────────────────────────────────────────────
FULL = "shadow agreed, full coverage"
NV = "shadow agreement not verified (attestation not recorded)"

_compose_result_cases = [
    ("APPROVE", "approve"),
    ("APPROVE with notes", "approve-with-notes"),
    ("APPROVE WITH CAVEAT", "approve-with-caveat"),
    ("APPROVE WITH ADVISORY NOTES", "approve-with-advisory-notes"),
    ("APPROVE WITH UNRESOLVED SHADOW FINDINGS", "approve-unresolved-shadow-findings"),
    ("REJECT", "reject"),
]
for human, token in _compose_result_cases:
    rc, out, _ = _run(["compose", "--result", human, "--coverage", FULL])
    check(f"compose result {human!r} -> token", 0, rc)
    check(
        f"compose result {human!r} marker",
        f"<!-- prflow:loop-verdict result={token} coverage=full -->\n",
        out,
    )

# coverage normalization: only the exact phrase yields full.
rc, out, _ = _run(["compose", "--result", "APPROVE", "--coverage", NV])
check("compose not-verified coverage", "<!-- prflow:loop-verdict result=approve coverage=not-verified -->\n", out)
rc, out, _ = _run(["compose", "--result", "APPROVE", "--coverage", ""])
check("compose empty coverage -> not-verified", "<!-- prflow:loop-verdict result=approve coverage=not-verified -->\n", out)
rc, out, _ = _run(["compose", "--result", "APPROVE", "--coverage", "shadow agreed, full coverage but actually not"])
check("compose near-miss coverage phrase -> not-verified", "<!-- prflow:loop-verdict result=approve coverage=not-verified -->\n", out)

# unmappable result: exit 3, NO marker on stdout.
rc, out, err = _run(["compose", "--result", "MAYBE", "--coverage", FULL])
check("compose unmappable result exit", 3, rc)
check("compose unmappable result emits no marker", "", out)

# ── read ─────────────────────────────────────────────────────────────────────
def _marker(result: str, coverage: str) -> str:
    return f"<!-- prflow:loop-verdict result={result} coverage={coverage} -->"


_read_ok_cases = [
    (_marker("approve", "full") + "\nReview passed...\n", 0, "CLEAN-FULL approve\n"),
    (_marker("approve-with-advisory-notes", "not-verified") + "\n", 0, "CLEAN-NOT-VERIFIED approve-with-advisory-notes\n"),
    (_marker("approve-with-caveat", "full") + "\n", 0, "CLEAN-FULL approve-with-caveat\n"),
    (_marker("approve-unresolved-shadow-findings", "full") + "\n", 0, "AWUSF full\n"),
    (_marker("approve-unresolved-shadow-findings", "not-verified") + "\n", 0, "AWUSF not-verified\n"),
    (_marker("reject", "not-verified") + "\n", 0, "REJECT\n"),
]
for body, rc_exp, out_exp in _read_ok_cases:
    rc, out, _ = _run(["read"], stdin=body)
    check(f"read {out_exp.strip()!r} rc", rc_exp, rc)
    check(f"read {out_exp.strip()!r} out", out_exp, out)

# AC5 fail-closed branches — none may yield CLEAN-FULL.
_read_fail_cases = [
    ("prose line 1\n" + _marker("approve", "full") + "\n", 2, "NO-MARKER\n", "prose line 1"),
    ("intro\n\n" + _marker("approve", "full") + "\n", 2, "NO-MARKER\n", "marker on line 3 (fixed position is line 1)"),
    (_marker("maybe", "full") + "\n", 3, "MALFORMED unknown-result-token=maybe\n", "unknown result token"),
    (_marker("approve", "partial") + "\n", 3, "MALFORMED unknown-coverage-token=partial\n", "unknown coverage token"),
    ("<!-- prflow:loop-verdict result=approve -->\n", 3, "MALFORMED marker-shaped-line-1-does-not-match-the-marker-grammar\n", "missing coverage field"),
    ("", 2, "NO-MARKER\n", "empty input"),
]
for body, rc_exp, out_exp, label in _read_fail_cases:
    rc, out, _ = _run(["read"], stdin=body)
    check(f"read fail-closed [{label}] rc", rc_exp, rc)
    check(f"read fail-closed [{label}] out", out_exp, out)
    check(f"read fail-closed [{label}] not CLEAN-FULL", False, out.startswith("CLEAN-FULL"))

# A nonexistent file path is an AC5 safe-direction branch: it must route to the prose
# fallback (NO-MARKER / rc 2), never to a clean verdict.
rc, out, _ = _run(["read", "/no/such/loop-verdict-file-1212"])
check("read nonexistent file rc", 2, rc)
check("read nonexistent file out", "NO-MARKER\n", out)
check("read nonexistent file not CLEAN-FULL", False, out.startswith("CLEAN-FULL"))

# ── issue #1230: a clean APPROVE is unreachable on a not-verified shadow block ──
# The elective path is closed: `coverage: "not_verified"` is a consequence of a shadow
# shortfall, never a budget choice. What that decision must never do is weaken the
# coverage gate itself, so this drives the compose -> read ROUND TRIP (the checks above
# drive each subcommand alone) over the helper's clean-approve token set paired with the
# not-verified phrase shapes enumerated from loop-exit.md's shadow-status render rules.
# A CLEAN-FULL out of any of these would mean a run reported as not independently audited
# had reached the clean-completion path.
#
# The `prompt addenda` / `attestation not recorded` phrases are the #497 attestation half
# of loop-exit.md's TWO-operand clean-agreement conjunction (`coverage == "full"` AND
# `prompt_addenda == "none"`): on those arms coverage IS full while the rendered phrase is
# not the clean one, so they are what proves the addenda half is still load-bearing here.
_NOT_VERIFIED_PHRASES = [
    ("bare", "shadow agreement not verified"),
    ("reason", "shadow agreement not verified (roster short: 3 of 5 reviewers returned)"),
    ("addenda-array", 'shadow agreement not verified (prompt addenda: ["topic-priming"])'),
    ("attestation-absent", "shadow agreement not verified (attestation not recorded)"),
    ("attestation-invalid", "shadow agreement not verified"),
]
_CLEAN_APPROVE_RESULTS = [
    ("APPROVE", "approve"),
    ("APPROVE with notes", "approve-with-notes"),
    ("APPROVE WITH CAVEAT", "approve-with-caveat"),
    ("APPROVE WITH ADVISORY NOTES", "approve-with-advisory-notes"),
]
for _label, _phrase in _NOT_VERIFIED_PHRASES:
    for _human, _token in _CLEAN_APPROVE_RESULTS:
        rc, marker, _ = _run(["compose", "--result", _human, "--coverage", _phrase])
        check(f"#1230 compose [{_label}/{_token}] rc", 0, rc)
        rc, out, _ = _run(["read"], stdin=marker)
        check(f"#1230 round trip [{_label}/{_token}] out", f"CLEAN-NOT-VERIFIED {_token}\n", out)
        check(f"#1230 round trip [{_label}/{_token}] not CLEAN-FULL", False, out.startswith("CLEAN-FULL"))

# The converse direction, so the guard above cannot be satisfied by a normalizer that
# calls everything not-verified: the exact clean-agreement phrase still round-trips to
# CLEAN-FULL. A run that narrowed the phrase would silently strip every clean completion.
rc, marker, _ = _run(["compose", "--result", "APPROVE", "--coverage", FULL])
rc, out, _ = _run(["read"], stdin=marker)
check("#1230 round trip [full/approve] out", "CLEAN-FULL approve\n", out)

# A file argument path is exercised too (round-trips through compose).
with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
    fh.write(_marker("reject", "not-verified") + "\nsome report body\n")
    _path = fh.name
rc, out, _ = _run(["read", _path])
check("read from file argument", "REJECT\n", out)
Path(_path).unlink()


if _failures:
    print(f"loop-verdict-marker-test: {len(_failures)} failure(s):", file=sys.stderr)
    for f in _failures:
        print(f, file=sys.stderr)
    sys.exit(1)
print("loop-verdict-marker-test: all checks passed")
