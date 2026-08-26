#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Per-shard tally extraction and cross-shard recombination for the concurrent CI
job matrix (issue #877).

The required merge-gate check `lib + python tests` used to be a single sequential
job running `bash lib/test/run.sh`. It is now satisfied by several shard jobs
running concurrently, recombined by an aggregator job that keeps that exact name.
This helper is the transport-and-recombine layer:

  extract  — parse ONE shard's captured log (plus its process exit code) into a
             small tally directory: the shard's passed/failed/skipped counts, the
             verbatim skip-detail lines, and the failure-identifier lines. Written
             so the shard can upload it as an artifact.

  combine  — read every shard's tally directory, SUM the counts, and render the
             same `N passed, M failed[, K skipped]` summary the single job printed,
             followed by the skip itemization and a failure recap — one line per
             entry by default, or the first `--detail-cap` entries of each class
             plus an omitted count when a caller asks for compact output. Preserves
             the skip population and its per-check detail exactly (issue #456: a
             skipped check is never laundered into a clean pass). Exits non-zero if
             any shard failed, any shard exited non-zero, any tally is missing or
             malformed, or the announced skip tally disagrees with the itemized skip
             lines in EITHER direction — the aggregator FAILS CLOSED, so a lost shard
             never reads as a green merge gate. `--expect <n>` is REQUIRED: the
             missing-shard guard must not be disable-able by omitting a flag.
             `--require-shards <ids>` (optional) additionally reconciles the
             recombined shards against the true partition BY NAME — a caller's
             `--expect` count alone is never checked against the real shard set,
             so `--expect 1` over one shard looks identical to a complete run;
             naming the partition (from `run-shard.sh --list-shards`) fails closed
             on a missing/unexpected/duplicated shard and states the covered
             population on the trailing line (issue #1289).

  record-fingerprint — write this launch's five-field checkout fingerprint (from
             scripts/checkout-fingerprint.py) into <out>/fingerprint.json, or an
             unestablished record when it cannot be produced. Best-effort: always
             writes, always exits 0, so it never blocks a launch (issue #2008).

  same-tree-eligible — exit 0 (ELIGIBLE) only when a fresh fingerprint equals a
             recorded one on all five fields, else exit 1; fail-closed, so an
             unestablished or absent fingerprint refuses the same-tree failed-
             shard-only relaunch (issue #2008).

Parsing keys on the two stable, unit-tested summary contracts:
  * lib/test/summary.sh   — `N passed, M failed[, K skipped]` + `  SKIP  ...` lines
  * lib/test/run-module.sh — `Module <id>: N passed, M failed`

The counts and the pass/fail DECISION are derived here in python3 (a hard preflight
prerequisite), never through a non-preflight PATH tool (CLAUDE.md guard-class 2).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# The five-field checkout identity a launch records (issue #2008). COUPLED with
# scripts/checkout-fingerprint.py's emitted object and scripts/verification-flight.py's
# `_CHECKOUT_REQUIRED` — the same five names; change them together.
_FINGERPRINT_FIELDS = (
    "checkout_id",
    "head",
    "index_digest",
    "tracked_digest",
    "untracked_digest",
)

# A run.sh final summary line (from lib/test/summary.sh). Anchored to a whole line.
_BARE_SUMMARY = re.compile(r"^(\d+) passed, (\d+) failed(?:, (\d+) skipped)?$")
# A run-module.sh per-module summary line (one per module in a group shard). The optional
# trailing `, K skipped` clause carries a module-tier host-capability skip (issue #887),
# symmetric with `_BARE_SUMMARY`'s own optional skipped group — one skip-accounting shape
# across both tiers. Byte-identical to the pre-#887 pattern when no skip fired.
_MODULE_SUMMARY = re.compile(
    r"^Module (\S+): (\d+) passed, (\d+) failed(?:, (\d+) skipped)?$"
)
# The skip-itemization lines summary.sh prints after the real summary.
_SKIP_LINE = re.compile(r"^  SKIP  (.*)$")
# The failure-recap header both run.sh and run-module.sh print.
_RECAP_HEADER = "Failure recap:"
# A failure-recap bullet (`  - <identifier>`), common to both formats.
_RECAP_BULLET = re.compile(r"^  - (.*)$")

_TALLY_KEYS = ("shard", "passed", "failed", "skipped", "rc")


def _parse_shard_list(raw: str) -> list[str]:
    """Split a `--require-shards` value into an ordered, de-duplicated id list.

    Accepts commas and/or whitespace as separators, so a caller can pass either
    `run-shard.sh --list-shards`'s newline/space output verbatim or a hand-typed
    comma list. Empty fragments are dropped; order-of-first-appearance is kept so
    the self-describing coverage line reads in the caller's stated order.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for token in re.split(r"[,\s]+", raw.strip()):
        if token and token not in seen:
            seen.add(token)
            ordered.append(token)
    return ordered


def _parse_log(
    lines: list[str], tier: str = "auto"
) -> tuple[int, int, int, list[str], list[str], list[str]]:
    """Return (passed, failed, skipped, skip_details, failure_names, warnings).

    `tier` selects which summary contract to read, because run-shard.sh knows
    unambiguously which it dispatched:
      * "monolith" — read only run.sh's own summary (the LAST bare `N passed, M
        failed[, K skipped]` line) and the skip itemization that follows it.
      * "python-pool" — the same summary.sh contract, emitted by
        lib/test/run-python-pool.sh (the pooled Python suites' own shard). Named for
        the shard that produced the log rather than folded into "monolith", so a
        reader of a tally directory can tell which driver wrote it; the parse is
        identical because the rendered contract is identical.
      * "modules"  — read only the summed `Module <id>: N passed, M failed` lines.
      * "auto"     — read both (the pre-tier behavior; kept for direct/manual use).
    Passing the known tier is what stops a monolith log that merely *contains* a
    `Module <id>: …` line (e.g. a failing meta-test dumping a run-module subprocess's
    captured stdout) from summing that line ON TOP of run.sh's real summary and
    inflating the aggregate count — the fail-closed accounting must not be defeatable
    by log-content collision.

    Positional, not global, on purpose: run.sh drives summary.sh over fixtures, so
    its captured output contains many `N passed, M failed` and `  SKIP  ` lines that
    are NOT the real run. The real summary is the LAST bare-format line (the final
    devflow_render_test_summary call runs after every assertion); the real skip
    itemization and failure recap are the lines that follow it.
    """
    passed = failed = skipped = 0
    warnings: list[str] = []

    # Module tier: sum every per-module summary line (a group shard has >= 1). Record each
    # summary line's index so a module's own itemized `  SKIP  ` lines — emitted right after
    # its summary — can be collected below (issue #887), the module-tier analogue of the
    # monolith's post-summary skip itemization.
    saw_module = False
    module_summary_indices: list[int] = []
    if tier in ("modules", "auto"):
        for idx, line in enumerate(lines):
            m = _MODULE_SUMMARY.match(line)
            if m:
                saw_module = True
                passed += int(m.group(2))
                failed += int(m.group(3))
                skipped += int(m.group(4)) if m.group(4) is not None else 0
                module_summary_indices.append(idx)

    # Monolith tier: the LAST bare-format summary line is the real run.sh summary.
    last_summary_idx = -1
    if tier in ("monolith", "python-pool", "auto"):
        for idx, line in enumerate(lines):
            if _BARE_SUMMARY.match(line):
                last_summary_idx = idx
    if last_summary_idx >= 0:
        m = _BARE_SUMMARY.match(lines[last_summary_idx])
        assert m is not None
        passed += int(m.group(1))
        failed += int(m.group(2))
        skipped += int(m.group(3)) if m.group(3) is not None else 0

    # Skip detail: the `  SKIP  ` lines AFTER the real summary, up to the recap
    # header or EOF. Scoping to the tail excludes summary.sh's own self-test
    # fixtures, which emit `  SKIP  ` lines earlier in the capture.
    skip_details: list[str] = []
    if last_summary_idx >= 0:
        for line in lines[last_summary_idx + 1:]:
            if line.strip() == _RECAP_HEADER:
                break
            sm = _SKIP_LINE.match(line)
            if sm:
                skip_details.append(sm.group(1))
    # Module tier: a module's itemized `  SKIP  ` lines immediately follow its summary
    # line, up to the first line that is not a `  SKIP  ` line (issue #887). Each declaring
    # module contributes its own run of skip lines; collecting per-summary keeps them
    # attributed and bounded, and — because run-module.sh emits exactly K skip lines when
    # its summary announces `K skipped` — the combined tally's #456 disagreement check
    # covers the module tier exactly as it does the monolith tier.
    for idx in module_summary_indices:
        for line in lines[idx + 1:]:
            sm = _SKIP_LINE.match(line)
            if sm:
                skip_details.append(sm.group(1))
            else:
                break

    # Failure identifiers: the `  - ` bullets after any `Failure recap:` header
    # (run.sh prints one at the tail; run-module.sh prints one per failing module).
    failure_names: list[str] = []
    in_recap = False
    for line in lines:
        if line.strip() == _RECAP_HEADER:
            in_recap = True
            continue
        if in_recap:
            bm = _RECAP_BULLET.match(line)
            if bm:
                failure_names.append(bm.group(1))
            elif line.startswith("    "):
                # A continuation of a run-module bullet (expected/actual); ignore.
                continue
            else:
                in_recap = False

    if last_summary_idx < 0 and not saw_module:
        warnings.append(
            "no recognizable summary line found in the shard log "
            "(neither run.sh's 'N passed, M failed' nor 'Module <id>: ...')"
        )

    return passed, failed, skipped, skip_details, failure_names, warnings


def _read_tally(dir_path: Path) -> dict[str, str]:
    """Read a tally directory's `summary` file into a dict. Missing keys are absent."""
    summary_path = dir_path / "summary"
    values: dict[str, str] = {}
    text = summary_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "\t" not in line:
            continue
        key, _, val = line.partition("\t")
        values[key] = val
    return values


def _write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("".join(f"{ln}\n" for ln in lines), encoding="utf-8")


def cmd_extract(args: argparse.Namespace) -> int:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        raw = Path(args.log).read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        # A missing/unreadable log is itself a shard failure — record it so combine
        # fails closed rather than silently dropping the shard's contribution.
        warnings = [f"could not read shard log {args.log}: {error}"]
        passed = failed = skipped = 0
        skip_details: list[str] = []
        failure_names: list[str] = []
    else:
        passed, failed, skipped, skip_details, failure_names, warnings = _parse_log(
            raw.splitlines(), args.tier
        )

    rc = args.rc

    # Fail closed: a shard whose process exited non-zero but whose parsed failed
    # count is 0 (e.g. run.sh's fail-closed underivable-tally abort, or a crash
    # before the summary) must still count as a failure, or a red shard would
    # recombine as green. Synthesize one so the count and the recap agree.
    if rc != 0 and failed == 0:
        failed = 1
        failure_names.append(
            f"{args.shard}: shard process exited with status {rc} "
            "but no failed assertion was parsed (fail-closed synthetic failure)"
        )
    # A shard that produced no recognizable summary at all is also a failure.
    if warnings and failed == 0:
        failed = 1
        failure_names.append(f"{args.shard}: {warnings[0]}")

    summary_lines = [
        f"shard\t{args.shard}",
        f"passed\t{passed}",
        f"failed\t{failed}",
        f"skipped\t{skipped}",
        f"rc\t{rc}",
    ]
    _write_lines(out_dir / "summary", summary_lines)
    _write_lines(out_dir / "skips", skip_details)
    _write_lines(out_dir / "names", failure_names)

    for w in warnings:
        print(f"shard-tally extract [{args.shard}]: WARNING: {w}", file=sys.stderr)
    print(
        f"shard-tally extract [{args.shard}]: {passed} passed, {failed} failed, "
        f"{skipped} skipped (rc={rc})"
    )
    return 0 if failed == 0 and rc == 0 else 1


def _render_detail(lines: list[str], prefix: str, cap: int) -> None:
    """Print `lines` under `prefix`, emitting at most `cap` of them.

    A non-positive `cap` (0, the default, or any negative) means uncapped — the
    pre-cap rendering, which is what CI's aggregator job takes, so its output is
    unchanged. A positive cap bounds ONE detail class:
    the caller renders each class through its own call, so the cap is per-class
    rather than a shared budget. The omitted count is printed rather than dropped —
    a truncated tail that announced nothing would read exactly like a short one,
    and the full population is still in the retained per-shard logs.
    """
    shown = lines if cap <= 0 else lines[:cap]
    for entry in shown:
        print(f"{prefix}{entry}")
    omitted = len(lines) - len(shown)
    if omitted > 0:
        print(f"{prefix}({omitted} omitted — the full list is in the retained shard logs)")


def _collect_dirs(args: argparse.Namespace) -> list[Path]:
    dirs: list[Path] = [Path(d) for d in args.dirs]
    if args.scan:
        parent = Path(args.scan)
        if parent.is_dir():
            for child in sorted(parent.iterdir()):
                if (child / "summary").is_file():
                    dirs.append(child)
    return dirs


def cmd_combine(args: argparse.Namespace) -> int:
    dirs = _collect_dirs(args)
    if len(dirs) < args.expect:
        # A shard that never uploaded its tally (crashed/cancelled before the upload
        # step) would otherwise be invisible here — combine would sum the survivors
        # and could report green over an incomplete run. Fail closed on a shortfall.
        print(
            f"shard-tally combine: expected {args.expect} shard tally directories "
            f"but found {len(dirs)} — a shard is missing; refusing to report a "
            "green gate over an incomplete run",
            file=sys.stderr,
        )
        return 1
    if not dirs:
        print(
            "shard-tally combine: no shard tally directories given "
            "(--scan found none, and no positional dirs) — refusing to report a "
            "green gate over zero shards",
            file=sys.stderr,
        )
        return 1

    total_pass = total_fail = total_skip = 0
    all_skips: list[str] = []
    all_names: list[str] = []
    shard_names: list[str] = []
    problems: list[str] = []

    for d in dirs:
        try:
            values = _read_tally(d)
        except OSError as error:
            problems.append(f"{d}: tally unreadable ({error})")
            continue
        missing = [k for k in _TALLY_KEYS if k not in values]
        if missing:
            problems.append(f"{d}: tally missing key(s): {', '.join(missing)}")
            continue
        try:
            p = int(values["passed"])
            f = int(values["failed"])
            k = int(values["skipped"])
            rc = int(values["rc"])
        except ValueError:
            problems.append(f"{d}: non-integer count in tally")
            continue
        shard_names.append(values["shard"])
        total_pass += p
        total_fail += f
        total_skip += k
        if rc != 0:
            # rc-carried failure with no counted failure (belt-and-braces; extract
            # already synthesizes one, but a hand-authored/partial tally might not).
            problems.append(f"{values['shard']}: shard exited non-zero (rc={rc})")
        # Inside the guard: `extract` always writes all three files, but a
        # hand-authored or partially-uploaded tally can carry `summary` without its
        # siblings. Read them unguarded and that shape raises an uncaught traceback
        # instead of routing through `problems`. The exit stays non-zero either way,
        # so this is a diagnostic fix, not a fail-open one — but a `PROBLEM:` line
        # naming the directory is what tells the reader which shard to look at.
        try:
            all_skips.extend((d / "skips").read_text(encoding="utf-8").splitlines())
            all_names.extend((d / "names").read_text(encoding="utf-8").splitlines())
        except OSError as error:
            problems.append(f"{d}: skip/failure detail unreadable ({error})")

    # Reconcile the recombined shards against the true partition BY NAME (issue #1289).
    # `--expect` is only a count floor, and a count a caller supplies is not reconciled
    # against the real shard set: `--expect 1` over one shard is byte-shaped exactly like
    # a complete run. When the caller names the partition it claims to cover, every named
    # shard must actually be present, no unexpected tally may have crept in, and none may
    # appear twice — so a recombination over a subset fails closed NAMING the gap instead
    # of printing a whole-suite-shaped green summary. The sanctioned coordinator and the
    # #1132 decomposition recipe both feed this the authoritative `run-shard.sh
    # --list-shards` population, which is what reconciles the count floor against the true
    # partition. Empty `--require-shards` (the default, and CI's aggregator) skips it, so
    # existing output is unchanged.
    required = _parse_shard_list(args.require_shards)
    partition_covered = False
    if args.require_shards and not required:
        # A non-empty `--require-shards` that parses to nothing (whitespace- or
        # separator-only — e.g. the #1132 recipe pasting an EMPTY `run-shard.sh
        # --list-shards` result) would otherwise silently skip the by-name check,
        # reintroducing the fail-open one layer out. Distinguish it from the
        # sanctioned empty-string opt-out (which is `default=""`, falsy here) and
        # fail closed. `--expect 0` stays the documented explicit opt-out.
        problems.append(
            "--require-shards was given but names no shards (empty/separator-only "
            f"value {args.require_shards!r}) — refusing to silently disable the "
            "by-name partition check; pass the real partition, or --expect 0 to opt out"
        )
    if required:
        read_set = set(shard_names)
        required_set = set(required)
        missing = [s for s in required if s not in read_set]
        unexpected = sorted({s for s in shard_names if s not in required_set})
        duplicates = sorted({s for s in shard_names if shard_names.count(s) > 1})
        if missing:
            problems.append(
                "required shard(s) absent from the recombined tallies: "
                f"{', '.join(missing)} — refusing to report a green gate over a "
                "partial partition"
            )
        for s in unexpected:
            problems.append(
                f"shard '{s}' is present but not in the required partition "
                f"({', '.join(required)})"
            )
        if duplicates:
            problems.append(
                f"shard(s) recombined more than once: {', '.join(duplicates)}"
            )
        partition_covered = not (missing or unexpected or duplicates)

    # Render the combined summary in the single-job format.
    #
    # The plain `N passed, M failed` line — the one that says "nothing was skipped" —
    # is taken ONLY when BOTH the summed tally and the itemized population are empty.
    # Keying it on `total_skip == 0` alone was fail-OPEN in exactly the direction #456
    # exists to close: a well-keyed but garbled tally can carry `skipped=0` beside a
    # NON-empty skips file (extract will pair them when a `  SKIP  `-shaped line trails
    # a no-skip summary — the same content-collision class --tier isolation defends
    # against), and those skip lines were then dropped silently, unguarded, rc 0. The
    # disagreement check is therefore unconditional, below, and reached on both arms.
    skip_disagreement = len(all_skips) != total_skip
    if total_skip == 0 and not all_skips:
        print(f"{total_pass} passed, {total_fail} failed")
    else:
        print(f"{total_pass} passed, {total_fail} failed, {total_skip} skipped")
        # The announced tally above is the FULL count; only the itemization below is
        # capped, so the #456 disagreement check keeps comparing full populations.
        _render_detail(all_skips, "  SKIP  ", args.detail_cap)
    # The announced skip tally and the itemized lines must agree (issue #456).
    if skip_disagreement:
        print(
            f"  SKIP  (skip tally {total_skip} disagrees with "
            f"{len(all_skips)} itemized skip line(s) across shards — the skip "
            "population of this run is unverified)"
        )
        problems.append("skip tally/detail disagreement across shards")

    if total_fail > 0:
        print()
        print("Failure recap:")
        _render_detail(all_names, "  - ", args.detail_cap)

    print()
    print(f"shard-tally combine: {len(shard_names)} shard(s): {', '.join(shard_names)}")
    # State which population this aggregate claims to cover, so a partial recombination
    # cannot be quoted as a whole-suite result on its trailing line alone (issue #1289).
    if required:
        if not partition_covered:
            # A membership failure (missing/unexpected/duplicate shard): name the
            # claimed partition and route the reader to the PROBLEM line(s).
            print(
                "shard-tally combine: required partition NOT covered "
                f"({', '.join(required)}) — see PROBLEM line(s) below",
                file=sys.stderr,
            )
        elif not problems and total_fail == 0:
            # Membership complete AND the aggregate is otherwise clean: only then
            # state coverage affirmatively, so a "covered" line can never be quoted
            # beside a red gate (a shard whose own tally failed still fails the
            # aggregate above and prints its own recap — no partition line needed).
            print(
                f"shard-tally combine: required partition covered "
                f"({len(required)} shard(s)): {', '.join(required)}"
            )

    if problems:
        print()
        for pr in problems:
            print(f"shard-tally combine: PROBLEM: {pr}", file=sys.stderr)

    # Fail closed: any counted failure, any shard problem (missing/malformed tally,
    # non-zero rc), or a skip disagreement fails the aggregate.
    return 0 if total_fail == 0 and not problems else 1


def _fingerprint_helper_cmd() -> list[str]:
    """The command that produces a fresh checkout fingerprint on stdout.

    `DEVFLOW_FINGERPRINT_HELPER` overrides it verbatim (run directly, so a test stub
    or an alternate producer works); otherwise the bundled `scripts/checkout-fingerprint.py`
    is run with this interpreter. checkout-fingerprint.py lives under `scripts/`, i.e.
    `../../scripts/` from this file under `lib/test/`.
    """
    override = os.environ.get("DEVFLOW_FINGERPRINT_HELPER")
    if override:
        return [override]
    default = Path(__file__).resolve().parent.parent.parent / "scripts" / "checkout-fingerprint.py"
    return [sys.executable, str(default)]


def _established_fingerprint(text: str) -> dict | None:
    """Parse `text` as an established five-field fingerprint, else None.

    Every content field must be a non-empty string; equality across the five is the
    whole eligibility contract, so no object-id shape is imposed here.
    """
    try:
        obj = json.loads(text)
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(obj, dict) or obj.get("unestablished"):
        return None
    if all(isinstance(obj.get(k), str) and obj.get(k) for k in _FINGERPRINT_FIELDS):
        return obj
    return None


def _load_fingerprint(path: Path) -> tuple[dict | None, str]:
    """Return (record, "") for an established fingerprint file, else (None, reason).

    Fail-closed: an unreadable file, non-JSON, an unestablished marker, or a missing
    field is a reason — never a match, so an unestablished recorded fingerprint can
    never discharge the same-tree relaunch.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return None, f"unreadable ({error})"
    try:
        obj = json.loads(text)
    except (ValueError, json.JSONDecodeError):
        return None, "is not valid JSON"
    if not isinstance(obj, dict):
        return None, "is not a JSON object"
    if obj.get("unestablished"):
        return None, "is unestablished"
    missing = [k for k in _FINGERPRINT_FIELDS if not (isinstance(obj.get(k), str) and obj.get(k))]
    if missing:
        return None, f"missing field(s): {', '.join(missing)}"
    return obj, ""


def cmd_record_fingerprint(args: argparse.Namespace) -> int:
    """Record this launch's checkout fingerprint into `--out`/fingerprint.json.

    Best-effort by design: it ALWAYS writes the record and ALWAYS exits 0, so a
    fingerprint failure can never block a suite launch. When the fingerprint cannot be
    produced (or is not an established five-field object) the record is written as
    `{"unestablished": true, "reason": ...}` — never omitted, never a partial or
    invented fingerprint (issue #2008).
    """
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / "fingerprint.json"
    reason = ""
    try:
        proc = subprocess.run(
            _fingerprint_helper_cmd(), capture_output=True, text=True, check=False
        )
    except OSError as error:
        reason = f"could not run the checkout-fingerprint helper ({error})"
    else:
        if proc.returncode == 0 and _established_fingerprint(proc.stdout.strip()):
            dest.write_text(proc.stdout.strip() + "\n", encoding="utf-8")
            print(
                f"shard-tally record-fingerprint: recorded established checkout "
                f"fingerprint at {dest}",
                file=sys.stderr,
            )
            return 0
        reason = (
            f"checkout-fingerprint helper exited {proc.returncode} without an "
            f"established five-field fingerprint: {proc.stderr.strip()}"
        )
    dest.write_text(
        json.dumps({"unestablished": True, "reason": reason or "unknown"}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"shard-tally record-fingerprint: recorded UNESTABLISHED checkout fingerprint "
        f"at {dest} ({reason})",
        file=sys.stderr,
    )
    return 0


def cmd_same_tree_eligible(args: argparse.Namespace) -> int:
    """Exit 0 (ELIGIBLE) only when a fresh fingerprint equals the recorded one on all
    five fields; otherwise INELIGIBLE (exit 1). Fail-closed on any unusable input, so an
    unestablished or absent fingerprint on either side refuses the same-tree relaunch."""
    recorded, r_reason = _load_fingerprint(Path(args.recorded))
    if recorded is None:
        print(f"INELIGIBLE: recorded fingerprint {r_reason}", file=sys.stderr)
        return 1
    fresh, f_reason = _load_fingerprint(Path(args.fresh))
    if fresh is None:
        print(f"INELIGIBLE: fresh fingerprint {f_reason}", file=sys.stderr)
        return 1
    for field in _FINGERPRINT_FIELDS:
        if recorded[field] != fresh[field]:
            print(f"INELIGIBLE: fingerprint field '{field}' differs", file=sys.stderr)
            return 1
    print("ELIGIBLE")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    ex = sub.add_parser("extract", help="parse one shard log into a tally directory")
    ex.add_argument("--shard", required=True, help="shard name")
    ex.add_argument("--log", required=True, help="captured shard log path")
    ex.add_argument("--rc", type=int, required=True, help="shard process exit code")
    ex.add_argument(
        "--tier",
        choices=("monolith", "python-pool", "modules", "auto"),
        default="auto",
        help="which summary contract to read (run-shard.sh passes the known tier)",
    )
    ex.add_argument("--out", required=True, help="output tally directory")
    ex.set_defaults(func=cmd_extract)

    co = sub.add_parser("combine", help="recombine shard tallies into one summary")
    co.add_argument("dirs", nargs="*", help="shard tally directories")
    co.add_argument("--scan", help="a parent dir; every child holding a summary file is a shard tally")
    # REQUIRED, not optional: an optional missing-shard guard is one an invocation can
    # silently disable by omission, and the omission looks identical to a green gate.
    # Every caller must state the shard count it expects, so a shard that never uploaded
    # its tally is always visible. (`--expect 0` is the explicit "no floor" opt-out and
    # still routes through the zero-dirs refusal below.)
    co.add_argument(
        "--expect",
        type=int,
        required=True,
        help="fail closed unless at least this many shard tallies are present",
    )
    # Optional, defaulting to uncapped, unlike --expect: omitting it disables no guard.
    # It bounds only how much DETAIL is RENDERED; the counts, the pass/fail decision and
    # the #456 skip-disagreement check all keep reading the full populations, so a caller
    # cannot weaken the gate by capping. `lib/test/run-parallel.sh` passes 20 to keep an
    # agent's final-gate output compact; CI's aggregator omits it and renders everything.
    # Optional, defaulting to off, unlike --expect: omitting it disables only the
    # by-NAME partition reconciliation, not the --expect count floor. When supplied it
    # names the shard partition this recombination must cover (commas and/or whitespace
    # separate ids, so `run-shard.sh --list-shards`'s output pastes in verbatim); a
    # missing, unexpected, or duplicated shard then fails the aggregate NAMING the gap
    # (issue #1289). This is what reconciles the caller's count against the true shard
    # set — the sanctioned coordinator and the #1132 recipe feed it `--list-shards`.
    co.add_argument(
        "--require-shards",
        default="",
        help="the shard partition this recombination must cover (comma/space "
        "separated); a missing/unexpected/duplicated shard fails closed by name",
    )
    co.add_argument(
        "--detail-cap",
        type=int,
        default=0,
        help="render at most N entries per detail class (0 or negative = uncapped)",
    )
    co.set_defaults(func=cmd_combine)

    rf = sub.add_parser(
        "record-fingerprint",
        help="record this launch's checkout fingerprint into <dir>/fingerprint.json",
    )
    rf.add_argument("--out", required=True, help="directory to write fingerprint.json into")
    rf.set_defaults(func=cmd_record_fingerprint)

    el = sub.add_parser(
        "same-tree-eligible",
        help="exit 0 only when a fresh fingerprint equals a recorded one on all five fields",
    )
    el.add_argument("--recorded", required=True, help="the RED run's recorded fingerprint.json")
    el.add_argument("--fresh", required=True, help="a freshly produced fingerprint.json")
    el.set_defaults(func=cmd_same_tree_eligible)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
