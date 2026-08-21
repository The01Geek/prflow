#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Unit tests for scripts/loop-verdict-marker.py (issue #1212).

Drives the SHIPPED helper as a subprocess over the compose + read matrix and
every AC5 safe-direction branch. The helper is additionally imported in-process,
for its result vocabulary only — never to exercise behaviour, which the subprocess
invocations remain the sole surface for. Exit 0 == all green; exit 1 with a diff on the
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
  * #1230 fail-closed direction: every rendered not-verified phrase composes to
    coverage=not-verified and round-trips to CLEAN-NOT-VERIFIED for every clean-approve
    token, never CLEAN-FULL, with the converse full-coverage round trip so a
    normalize-everything-away regression cannot satisfy it.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

HELPER = str(Path(__file__).resolve().parent.parent.parent / "scripts" / "loop-verdict-marker.py")

# Import the helper's own constants, so the clean/non-clean split is the helper's and a
# drifted transcription goes RED below. The subprocess drives remain the behavioural surface;
# this import exists only to read the vocabulary, and the hyphenated filename is why it
# goes through spec_from_file_location (the standard idiom for importing a hyphen-named script).
_spec = importlib.util.spec_from_file_location("loop_verdict_marker", HELPER)
assert _spec and _spec.loader
helper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(helper)

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

# ── issue #1230: the marker's coverage direction is fail-closed end to end ──
# What this block owns is narrow, and saying so is the point: the helper receives an
# already-RENDERED shadow-status phrase, so it can only be held to normalizing every
# non-clean phrase away from `full` and carrying that through `read`. The upstream
# guarantee — that on loop-exit.md's APPROVE-family line a clean phrase is rendered only
# on its two-operand conjunction (`coverage == "full"` AND `prompt_addenda == "none"`) —
# is agent-executed prose this file cannot reach: a green run here is NOT coverage of it.
# The first three rows are the shapes loop-exit.md renders when it does not hold; the
# fourth is a phrase it renders nowhere, standing in for a future variant. The normalizer
# is one equality against the full-coverage phrase, so these document rendered shapes
# rather than distinct branches — every phrase but that one is the same input class.
_NOT_VERIFIED_PHRASES = [
    ("bare", "shadow agreement not verified"),
    ("addenda-array", 'shadow agreement not verified (prompt addenda: ["topic-priming"])'),
    ("attestation-absent", NV),
    ("unrendered", "shadow agreement not verified (roster short: 3 of 5 reviewers returned)"),
]
# Filtered against the helper's own clean-approve set, so a token the helper stops treating
# as clean drops out here with no edit. A NEW helper token is not driven automatically — the
# roster-coverage check below goes RED until it is added to `_compose_result_cases`.
_CLEAN_APPROVE_RESULTS = [
    (human, token) for human, token in _compose_result_cases if token in helper._CLEAN_APPROVE_TOKENS
]
# Compared on tokens, since the helper keys `_RESULT_TO_TOKEN` by its own normalized
# spelling of each result.
check(
    "#1230 compose-case roster covers the helper's result vocabulary",
    set(),
    set(helper._RESULT_TO_TOKEN.values()) - {token for _, token in _compose_result_cases},
)
# An empty roster would run the round-trip loop zero times and pass vacuously.
check("#1230 clean-approve roster is non-empty", True, bool(_CLEAN_APPROVE_RESULTS))

# The clean/non-clean split is what decides whether a result routes as an approval, and
# the helper derives it by SUBTRACTION — so a non-clean token added to `_RESULT_TO_TOKEN`
# and forgotten from the exclusion is silently clean, and the coverage check above would
# ratify it rather than catch it. Pin the resulting set so any change to it goes RED and a
# human confirms the new token's bucket; and pin that every excluded token is a real one,
# so renaming a result without updating the exclusion cannot quietly stop excluding it.
check(
    "#1230 helper clean-approve set matches the reviewed expectation",
    {"approve", "approve-with-notes", "approve-with-caveat", "approve-with-advisory-notes"},
    set(helper._CLEAN_APPROVE_TOKENS),
)
check(
    "#1230 every excluded non-clean token is a real result token",
    set(),
    set(helper._NON_CLEAN_TOKENS) - set(helper._RESULT_TOKENS),
)

# Every non-clean phrase must compose to the SAME not-verified marker, so the load-bearing
# assertion is on the marker bytes — an exit status alone would not catch a normalizer that
# admitted one of these phrases and emitted `coverage=full`.
for _label, _phrase in _NOT_VERIFIED_PHRASES:
    rc, out, _ = _run(["compose", "--result", "APPROVE", "--coverage", _phrase])
    check(f"#1230 compose [{_label}] rc", 0, rc)
    check(
        f"#1230 compose [{_label}] marker",
        "<!-- prflow:loop-verdict result=approve coverage=not-verified -->\n",
        out,
    )

# ...and carrying a not-verified marker through `read` must reach CLEAN-NOT-VERIFIED for
# every clean-approve result, never CLEAN-FULL: a CLEAN-FULL here would route a run
# reported as not independently audited onto the clean-completion path.
for _human, _token in _CLEAN_APPROVE_RESULTS:
    rc, marker, _ = _run(["compose", "--result", _human, "--coverage", NV])
    check(f"#1230 compose [{_token}] rc", 0, rc)
    rc, out, _ = _run(["read"], stdin=marker)
    check(f"#1230 round trip [{_token}] out", f"CLEAN-NOT-VERIFIED {_token}\n", out)
    check(f"#1230 round trip [{_token}] not CLEAN-FULL", False, out.startswith("CLEAN-FULL"))

# The converse direction, so the guard above cannot be satisfied by a normalizer that
# calls everything not-verified: the exact clean-agreement phrase still round-trips to
# CLEAN-FULL. A run that narrowed the phrase would silently strip every clean completion.
rc, marker, _ = _run(["compose", "--result", "APPROVE", "--coverage", FULL])
check("#1230 converse compose rc", 0, rc)
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
