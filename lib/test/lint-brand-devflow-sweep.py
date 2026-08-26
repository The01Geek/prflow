#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Reconcile every brand-cased ``DevFlow`` occurrence in the tracked tree against a
recorded bucket classification, failing closed in both directions (issue #1745).

The consumer-facing ``devflow`` -> ``prflow`` rename (issue #1002) left a large residue
of the brand spelling ``DevFlow`` across prose, comments and fixtures. Some occurrences
are FROZEN (a superseded provenance-label value a selector still matches, append-only
record byte-contents, historical CHANGELOG entries) and some are ORDINARY PROSE still
owed a rename to ``PRFlow``. This lint records which is which as data and enforces it:

- every case-sensitive ``DevFlow`` occurrence is classified into exactly one bucket;
- an occurrence in no bucket (a new file, or a new occurrence in a file beyond its
  recorded pending count) turns the suite RED;
- a stale recorded assignment (a ``pending_sweep_baseline`` row whose file no longer
  carries that many pending occurrences, or a frozen-provenance entry that matches
  nothing) turns the suite RED.

Buckets (first match wins), read from ``lib/test/brand-devflow-buckets.json``:

- ``frozen-record``     — a path under a recorded record prefix (append-only history /
  frozen census snapshots whose bytes are never rewritten).
- ``frozen-historical`` — a recorded historical file (CHANGELOG.md); past-time entries.
- ``frozen-tooling``    — this feature's own lint/data files, whose ``DevFlow`` literals
  are the machinery that matches the brand, not prose to sweep.
- ``frozen-provenance`` — a quoted ``"DevFlow"`` / ``'DevFlow'`` VALUE inside a recorded
  provenance-selector file (the superseded label the scan/classify/fetch path matches).
- ``pending``           — everything else: ordinary renameable prose not yet swept,
  recorded per file in ``pending_sweep_baseline`` and drained by the follow-up sweep.

Population enumeration is via index-reading ``git ls-files`` (never a root-anchored
recursive walk, issue #711), so sibling worktrees under ``.claude/worktrees/`` are not
counted.

Modes: ``--check`` (default) reconciles and exits non-zero on any finding;
``--update-baseline`` reseeds ``pending_sweep_baseline`` from the tree (used to seed the
record and by the deferred sweep follow-up as it drains the bucket);
``--print-population`` prints one ``bucket<TAB>path<TAB>count`` line per file for an
independent reconciliation.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

BRAND = b"DevFlow"
BUCKETS_DEFAULT = "lib/test/brand-devflow-buckets.json"
# A quoted VALUE form, the superseded provenance label as a selector matches it. Prose
# uses a backtick-wrapped `DevFlow`, which this deliberately does not match.
PROVENANCE_VALUE = re.compile(rb"""(["'])DevFlow\1""")


def _run(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=True,
    ).stdout


def repo_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    try:
        top = _run(Path.cwd(), "rev-parse", "--show-toplevel").strip()
        if top:
            return Path(top)
    except (subprocess.CalledProcessError, OSError):
        pass
    return Path.cwd()


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True, check=True,
    ).stdout
    return [p.decode("utf-8", "surrogateescape") for p in out.split(b"\x00") if p]


def load_buckets(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def classify_file(rel: str, data_blob: bytes, frozen: dict) -> tuple[int, int]:
    """Return (frozen_count, pending_count) of brand occurrences in one file.

    frozen_count aggregates the frozen buckets; pending_count is the renameable
    remainder recorded in the baseline.
    """
    total = data_blob.count(BRAND)
    if total == 0:
        return (0, 0)
    if any(rel.startswith(pfx) for pfx in frozen.get("record_prefixes", [])):
        return (total, 0)
    if rel in frozen.get("historical_files", []):
        return (total, 0)
    if rel in frozen.get("tooling_files", []):
        return (total, 0)
    if rel in {e["file"] for e in frozen.get("provenance", [])}:
        value = len(PROVENANCE_VALUE.findall(data_blob))
        return (value, total - value)
    return (0, total)


def scan(root: Path, buckets: dict) -> tuple[dict[str, int], dict[str, int], int]:
    """Return (pending_by_file, frozen_provenance_by_file, files_audited)."""
    frozen = buckets["frozen"]
    prov_files = {e["file"] for e in frozen.get("provenance", [])}
    pending: dict[str, int] = {}
    frozen_prov: dict[str, int] = {}
    audited = 0
    for rel in tracked_files(root):
        p = root / rel
        try:
            blob = p.read_bytes()
        except OSError as exc:
            print(f"lint-brand-devflow-sweep: skipping unreadable tracked file {rel}: {exc}", file=sys.stderr)
            continue
        audited += 1
        fcount, pcount = classify_file(rel, blob, frozen)
        if pcount:
            pending[rel] = pcount
        if rel in prov_files:
            frozen_prov[rel] = fcount
    return pending, frozen_prov, audited


def cmd_check(root: Path, buckets: dict) -> int:
    pending, frozen_prov, audited = scan(root, buckets)
    baseline = {row["path"]: row["count"] for row in buckets.get("pending_sweep_baseline", [])}
    findings: list[str] = []

    # Forward direction: a pending occurrence lacking a baseline row, or drifted from its
    # recorded count, is unclassified.
    for rel, count in sorted(pending.items()):
        recorded = baseline.get(rel)
        if recorded is None:
            findings.append(
                f"{rel}: {count} unclassified brand-cased 'DevFlow' occurrence(s) with no "
                f"pending_sweep_baseline row — classify the file (frozen bucket) or record it "
                f"in lib/test/brand-devflow-buckets.json (run --update-baseline)"
            )
        elif count != recorded:
            findings.append(
                f"{rel}: {count} pending brand-cased 'DevFlow' occurrence(s) but the baseline "
                f"records {recorded} — a new occurrence or a partial sweep; reconcile the count "
                f"(run --update-baseline after a deliberate sweep)"
            )

    # Reverse direction: a baseline row whose file is fully swept is stale.
    for rel in sorted(baseline):
        if rel not in pending:
            findings.append(
                f"{rel}: stale pending_sweep_baseline row — the file carries no pending "
                f"brand-cased 'DevFlow' occurrence any more; remove the row (run --update-baseline)"
            )

    # Reverse direction: a frozen-provenance entry matching zero quoted values is stale.
    for entry in buckets["frozen"].get("provenance", []):
        rel = entry["file"]
        if frozen_prov.get(rel, 0) == 0:
            findings.append(
                f"{rel}: stale frozen-provenance entry — no quoted \"DevFlow\"/'DevFlow' value "
                f"matched; the superseded label value moved or was removed"
            )

    print(f"lint-brand-devflow-sweep: audited {audited} of {audited} files")
    for f in findings:
        print(f"  {f}")
    return 1 if findings else 0


def cmd_update_baseline(root: Path, buckets: dict, buckets_path: Path) -> int:
    pending, _frozen_prov, _audited = scan(root, buckets)
    buckets["pending_sweep_baseline"] = [
        {"path": rel, "count": count} for rel, count in sorted(pending.items())
    ]
    buckets_path.write_text(json.dumps(buckets, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"lint-brand-devflow-sweep: reseeded pending_sweep_baseline with {len(pending)} file(s)")
    return 0


def cmd_print_population(root: Path, buckets: dict) -> int:
    frozen = buckets["frozen"]
    prov_files = {e["file"] for e in frozen.get("provenance", [])}
    for rel in tracked_files(root):
        p = root / rel
        try:
            blob = p.read_bytes()
        except OSError as exc:
            print(f"lint-brand-devflow-sweep: skipping unreadable tracked file {rel}: {exc}", file=sys.stderr)
            continue
        total = blob.count(BRAND)
        if total == 0:
            continue
        fcount, pcount = classify_file(rel, blob, frozen)
        if pcount:
            print(f"pending\t{rel}\t{pcount}")
        if fcount:
            if any(rel.startswith(pfx) for pfx in frozen.get("record_prefixes", [])):
                bucket = "frozen-record"
            elif rel in frozen.get("historical_files", []):
                bucket = "frozen-historical"
            elif rel in frozen.get("tooling_files", []):
                bucket = "frozen-tooling"
            elif rel in prov_files:
                bucket = "frozen-provenance"
            else:
                bucket = "frozen-other"
            print(f"{bucket}\t{rel}\t{fcount}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=None, help="tree root to audit (default: git toplevel)")
    ap.add_argument("--buckets", default=None,
                    help=f"the bucket record (default: <root>/{BUCKETS_DEFAULT})")
    ap.add_argument("--update-baseline", action="store_true",
                    help="reseed pending_sweep_baseline from the tree and rewrite the record")
    ap.add_argument("--print-population", action="store_true",
                    help="print one 'bucket<TAB>path<TAB>count' line per file with a brand occurrence")
    args = ap.parse_args(argv)

    root = repo_root(args.root)
    buckets_path = Path(args.buckets) if args.buckets else root / BUCKETS_DEFAULT
    try:
        buckets = load_buckets(buckets_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"lint-brand-devflow-sweep: cannot read bucket record {buckets_path}: {exc}", file=sys.stderr)
        return 2

    if args.update_baseline:
        return cmd_update_baseline(root, buckets, buckets_path)
    if args.print_population:
        return cmd_print_population(root, buckets)
    return cmd_check(root, buckets)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
