#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Reconcile the brand-cased ``DevFlow`` occurrences in the tracked tree against a
recorded bucket classification (issue #1745).

Some ``DevFlow`` occurrences are FROZEN (a superseded provenance-label value a selector
still matches, append-only record byte-contents, historical CHANGELOG entries) and some
are ORDINARY PROSE still owed a rename to ``PRFlow``. This lint records which is which as
data and reconciles the RENAMEABLE (``pending``) bucket against the tree by per-file
PRESENCE in both directions:

- a currently-clean file (no ``pending_sweep_baseline`` entry) that gains renameable
  ``DevFlow`` turns the suite RED — the AC3 new-occurrence guard;
- a stale entry (a ``pending_sweep_baseline`` file fully swept or deleted, or a
  frozen-provenance entry that matches nothing) turns the suite RED.

Reconciliation is per-file PRESENCE, deliberately NOT per-file count. An exact count of a
high-churn file (``run.sh`` is mutated by nearly every PR) drifts on a clean-textual
concurrent merge — two PRs each adding a ``DevFlow`` line pass individually while their
post-merge union reddens the required check on ``main``, the shared-hot-spot anti-pattern
CLAUDE.md warns of. So a file already in the grandfathered pending set is known sweep-debt
the follow-up drains; only a currently-clean file introducing brand prose re-reds.

The FROZEN buckets are likewise not count-bounded: a frozen file or a frozen-provenance
value may legitimately grow (CHANGELOG entries, learnings/logs, new selectors), and AC3
scopes the new-occurrence guard to occurrences *outside* a frozen/permanent bucket, so a
new ``DevFlow`` in a frozen bucket is allowed by design and is not flagged.

An unreadable tracked file (a genuine I/O failure on a git-tracked path) is breadcrumbed
to stderr; in the default (reconcile) mode a non-empty skip set FAILS THE RUN CLOSED,
because its occurrences could not be classified and a new renameable ``DevFlow`` there
would otherwise escape the forward-direction guard. ``--update-baseline`` /
``--print-population`` breadcrumb and continue (they do not gate).

Buckets, in the ``classify()`` first-match order:

- ``transient``         — a file under a recorded transient prefix (a consumed changeset
  ``version-consolidate`` deletes on merge), excluded from reconciliation so a baseline
  entry cannot fire a false RED on main after the file is deleted; a recorded exception
  (``.changeset/README.md``) is permanent and stays ``pending``.
- ``frozen-record``     — a path under a recorded record prefix (append-only history /
  frozen census snapshots whose bytes are never rewritten).
- ``frozen-historical`` — a recorded historical file (CHANGELOG.md); past-time entries.
- ``frozen-tooling``    — this feature's own lint/data files, whose ``DevFlow`` literals
  are the machinery that matches the brand, not prose to sweep.
- ``frozen-provenance`` — a quoted ``"DevFlow"`` / ``'DevFlow'`` VALUE inside a recorded
  provenance-selector file (the superseded label the scan/classify/fetch path matches).
- ``frozen-occurrence`` — a single frozen ``DevFlow`` occurrence inside a file that also
  carries renameable occurrences elsewhere (issue #2003). Each ``frozen.occurrences`` entry
  names a ``file`` and a ``context`` substring; every ``DevFlow`` on a line of that file
  containing the ``context`` is frozen and subtracted from the file's renameable remainder,
  so a mixed file can be swept of its ordinary occurrences while a two-spelling explainer,
  a superseded-spelling reference, or a pinned user-facing string on a specific line stays
  frozen without moving the whole file into a whole-file bucket. A stale entry (its
  ``context`` matches no brand-bearing line) fails the run closed, like the provenance
  reverse check.
- ``pending``           — everything else: ordinary renameable prose not yet swept,
  recorded per file in ``pending_sweep_baseline`` and drained by the follow-up sweep.

Population enumeration is via index-reading ``git ls-files`` (never a root-anchored
recursive walk, issue #711), so sibling worktrees under ``.claude/worktrees/`` are not
counted.

Modes: the default (no flag) reconciles and exits non-zero on any finding;
``--update-baseline`` reseeds ``pending_sweep_baseline`` from the tree (used to seed the
record and by the deferred sweep follow-up as it drains the bucket);
``--print-population`` prints one or more ``bucket<TAB>path<TAB>count`` lines per file
with a brand occurrence (a provenance file with both a value and a pending remainder
emits a ``pending`` line and a ``frozen-provenance`` line) for an independent
reconciliation.
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
    # Not a silent default (the #295 repo-root contract): a wrong root feeds the read
    # loop straight, so the cwd fallback is announced rather than assumed.
    print("lint-brand-devflow-sweep: git toplevel unresolved; auditing the cwd", file=sys.stderr)
    return Path.cwd()


def prov_file_set(frozen: dict) -> set[str]:
    return {e["file"] for e in frozen.get("provenance", [])}


def occ_file_map(frozen: dict) -> dict[str, list[str]]:
    """Map each occurrence-frozen file to its list of frozen `context` substrings."""
    m: dict[str, list[str]] = {}
    for e in frozen.get("occurrences", []):
        m.setdefault(e["file"], []).append(e["context"])
    return m


def occurrence_frozen_count(blob: bytes, contexts: list[str],
                            exclude: re.Pattern[bytes] | None = None) -> int:
    """Count brand occurrences on lines that contain any listed `context` substring — the
    per-occurrence freeze (issue #2003), subtracted from the file's renameable remainder.

    `exclude` (a compiled bytes pattern) subtracts, per line, the brand occurrences already
    counted by another frozen mechanism — the provenance branch passes ``PROVENANCE_VALUE`` so
    a context matching the quoted-value line is not counted in BOTH ``value`` and ``occ`` (a
    double-subtract that would mask a renameable occurrence behind the caller's max(...,0))."""
    if not contexts:
        return 0
    ctx_bytes = [c.encode("utf-8") for c in contexts]
    n = 0
    for line in blob.splitlines():
        if BRAND in line and any(cb in line for cb in ctx_bytes):
            c = line.count(BRAND)
            if exclude is not None:
                c -= len(exclude.findall(line))
            n += max(c, 0)
    return n


def iter_blobs(root: Path, skipped: list[str] | None = None):
    """Yield (rel, blob) for each tracked file; an unreadable one is breadcrumbed and its path
    appended to `skipped` (when given) so the caller can fail closed rather than let its
    occurrences escape classification."""
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],  # -z: NUL-delimited, core.quotePath-immune
        capture_output=True, check=True,
    ).stdout
    for raw in out.split(b"\x00"):
        if not raw:
            continue
        rel = raw.decode("utf-8", "surrogateescape")
        try:
            yield rel, (root / rel).read_bytes()  # raw bytes: exact b"DevFlow" count
        except OSError as exc:
            print(f"lint-brand-devflow-sweep: skipping unreadable tracked file {rel}: {exc}", file=sys.stderr)
            if skipped is not None:
                skipped.append(rel)


def load_buckets(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def record_shape_error(buckets) -> str | None:
    """Return a specific error string when the record's shape is wrong, else None — so the
    reader fails closed with a breadcrumb rather than raising KeyError/TypeError downstream."""
    if not isinstance(buckets, dict):
        return "top-level value is not a JSON object"
    frozen = buckets.get("frozen")
    if not isinstance(frozen, dict):
        return "missing the 'frozen' object"
    # The list-valued frozen keys are iterated by classify() (startswith / membership). A JSON
    # string there would iterate CHARACTERS and silently misclassify rather than fail closed, so
    # reject a non-list-of-strings here (the adversarial-parser six-shape discipline).
    for key in ("transient_prefixes", "transient_exceptions", "record_prefixes",
                "historical_files", "tooling_files"):
        val = frozen.get(key, [])
        if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
            return f"frozen.{key} must be a list of strings"
    prov = frozen.get("provenance", [])
    if not isinstance(prov, list):
        return "frozen.provenance must be a list"
    for i, entry in enumerate(prov):
        if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
            return f"frozen.provenance[{i}] lacks a string 'file'"
    # frozen.occurrences (issue #2003) is optional; when present each row needs a string
    # 'file' and 'context', else the occurrence-freeze counter would iterate a non-string.
    occ = frozen.get("occurrences", [])
    if not isinstance(occ, list):
        return "frozen.occurrences must be a list"
    for i, entry in enumerate(occ):
        if (not isinstance(entry, dict) or not isinstance(entry.get("file"), str)
                or not isinstance(entry.get("context"), str)):
            return f"frozen.occurrences[{i}] lacks a string 'file' or 'context'"
    pending_rows = buckets.get("pending_sweep_baseline", [])
    if not isinstance(pending_rows, list):
        return "pending_sweep_baseline must be a list"
    for i, row in enumerate(pending_rows):
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            return f"pending_sweep_baseline[{i}] lacks a string 'path'"
    return None


def classify(rel: str, blob: bytes, frozen: dict, prov_files: set[str],
             occ_by_file: dict[str, list[str]]) -> tuple[str, int, int]:
    """Return (bucket, frozen_count, pending_count) of brand occurrences in one file.

    bucket is the frozen bucket name ("" when there are no frozen occurrences);
    frozen_count aggregates the frozen buckets and pending_count is the renameable
    remainder recorded in the baseline. The whole-file buckets are first-match-wins; the
    occurrence-freeze (issue #2003) then subtracts from the remainder of a file that reached
    the provenance or plain-file branch, so a mixed file can be partially frozen.
    """
    total = blob.count(BRAND)
    if total == 0:
        return ("", 0, 0)
    # Transient (a consumed changeset version-consolidate deletes on merge): excluded, never
    # baselined — a baseline entry would fire the reverse stale check on main once the file is
    # deleted, a false RED (see the docstring's presence-not-count rationale).
    if (any(rel.startswith(pfx) for pfx in frozen.get("transient_prefixes", []))
            and rel not in frozen.get("transient_exceptions", [])):
        return ("transient", total, 0)
    if any(rel.startswith(pfx) for pfx in frozen.get("record_prefixes", [])):
        return ("frozen-record", total, 0)
    if rel in frozen.get("historical_files", []):
        return ("frozen-historical", total, 0)
    if rel in frozen.get("tooling_files", []):
        return ("frozen-tooling", total, 0)
    contexts = occ_by_file.get(rel, [])
    if rel in prov_files:
        value = len(PROVENANCE_VALUE.findall(blob))
        # Exclude the quoted-value brand from occ so a context that also matches the value
        # line is not counted in both value and occ (over-subtracting, masking a renameable
        # occurrence); disjoint counts mean value + occ never exceeds total.
        occ = occurrence_frozen_count(blob, contexts, exclude=PROVENANCE_VALUE)
        return ("frozen-provenance", value + occ, max(total - value - occ, 0))
    occ = occurrence_frozen_count(blob, contexts)
    if occ:
        return ("frozen-occurrence", occ, max(total - occ, 0))
    return ("", 0, total)


def scan(root: Path, buckets: dict, skipped: list[str] | None = None) -> tuple[dict[str, int], dict[str, int], int]:
    """Return (pending_by_file, frozen_provenance_by_file, files_audited); append any
    unreadable file's path to `skipped` when given."""
    frozen = buckets["frozen"]
    prov_files = prov_file_set(frozen)
    occ_by_file = occ_file_map(frozen)
    pending: dict[str, int] = {}
    frozen_prov: dict[str, int] = {}
    audited = 0
    for rel, blob in iter_blobs(root, skipped):
        audited += 1
        _bucket, _fcount, pcount = classify(rel, blob, frozen, prov_files, occ_by_file)
        if pcount:
            pending[rel] = pcount
        if rel in prov_files:
            # Count the quoted value INDEPENDENTLY of classify()'s first-match short-circuit: a
            # provenance file also matching an earlier frozen bucket would otherwise store that
            # bucket's total, leaving the reverse stale-provenance guard fail-open.
            frozen_prov[rel] = len(PROVENANCE_VALUE.findall(blob))
    return pending, frozen_prov, audited


def cmd_check(root: Path, buckets: dict) -> int:
    skipped: list[str] = []
    pending, frozen_prov, audited = scan(root, buckets, skipped)
    baseline = {row["path"] for row in buckets.get("pending_sweep_baseline", [])}
    findings: list[str] = []

    # Fail closed on an unreadable tracked file: its occurrences could not be classified, so
    # a new renameable DevFlow there would escape the forward-direction guard silently.
    for rel in skipped:
        findings.append(
            f"{rel}: unreadable tracked file — its brand-cased 'DevFlow' occurrences could not "
            f"be classified, so the reconciliation is incomplete; make the file readable and re-run"
        )

    # Forward (AC3): reconcile by per-file PRESENCE, not count (the docstring's rationale) —
    # a currently-clean file gaining renameable DevFlow is a new, unbaselined pending file and
    # REDs; a file already in the grandfathered set is known sweep-debt and does not re-red.
    for rel in sorted(pending):
        if rel not in baseline:
            findings.append(
                f"{rel}: brand-cased 'DevFlow' in a file with no pending_sweep_baseline entry — "
                f"classify the file (a frozen bucket) or record it in "
                f"lib/test/brand-devflow-buckets.json (run --update-baseline)"
            )

    # Reverse (AC1 stale): a baseline file fully swept (or deleted) carries no pending
    # occurrence any more — remove the entry.
    for rel in sorted(baseline):
        if rel not in pending:
            findings.append(
                f"{rel}: stale pending_sweep_baseline entry — the file carries no pending "
                f"brand-cased 'DevFlow' occurrence any more; remove the entry (run --update-baseline)"
            )

    # Reverse direction: a frozen-provenance entry matching zero quoted values is stale.
    for entry in buckets["frozen"].get("provenance", []):
        rel = entry["file"]
        if frozen_prov.get(rel, 0) == 0:
            findings.append(
                f"{rel}: stale frozen-provenance entry — no quoted \"DevFlow\"/'DevFlow' value "
                f"matched; the superseded label value moved or was removed"
            )

    # Reverse direction (issue #2003): a frozen-occurrence entry whose context no longer matches
    # any brand-bearing line is stale — the frozen occurrence moved or was already swept, so the
    # entry must be removed or its context updated. Checked per entry (not aggregated per file) so
    # one stale context among several on the same file is still caught.
    for entry in buckets["frozen"].get("occurrences", []):
        rel = entry["file"]
        ctx = entry["context"]
        try:
            blob = (root / rel).read_bytes()
        except OSError:
            findings.append(
                f"{rel}: frozen-occurrence entry references an unreadable or absent file — "
                f"remove the entry or make the file readable"
            )
            continue
        if occurrence_frozen_count(blob, [ctx]) == 0:
            findings.append(
                f"{rel}: stale frozen-occurrence entry — context {ctx!r} matches no brand-cased "
                f"'DevFlow' line any more; update the context or remove the entry"
            )

    print(f"lint-brand-devflow-sweep: audited {audited} of {audited} files")
    for f in findings:
        print(f"  {f}")
    return 1 if findings else 0


def cmd_update_baseline(root: Path, buckets: dict, buckets_path: Path) -> int:
    pending, _frozen_prov, _audited = scan(root, buckets)
    # Presence set (paths only, no counts): the reconciliation gates on file presence, so a
    # count here would be un-checked churn that rots.
    buckets["pending_sweep_baseline"] = [{"path": rel} for rel in sorted(pending)]
    buckets_path.write_text(json.dumps(buckets, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"lint-brand-devflow-sweep: reseeded pending_sweep_baseline with {len(pending)} file(s)")
    return 0


def cmd_print_population(root: Path, buckets: dict) -> int:
    frozen = buckets["frozen"]
    prov_files = prov_file_set(frozen)
    occ_by_file = occ_file_map(frozen)
    for rel, blob in iter_blobs(root):
        bucket, fcount, pcount = classify(rel, blob, frozen, prov_files, occ_by_file)
        if pcount:
            print(f"pending\t{rel}\t{pcount}")
        if fcount:
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
                    help="print one or more 'bucket<TAB>path<TAB>count' lines per file with a brand "
                         "occurrence (a provenance file emits both a pending and a frozen line)")
    args = ap.parse_args(argv)

    root = repo_root(args.root)
    buckets_path = Path(args.buckets) if args.buckets else root / BUCKETS_DEFAULT
    try:
        buckets = load_buckets(buckets_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"lint-brand-devflow-sweep: cannot read bucket record {buckets_path}: {exc}", file=sys.stderr)
        return 2
    # Fail closed with a specific breadcrumb on a structurally-valid-JSON record whose shape is
    # wrong, rather than an uncaught KeyError/TypeError downstream (adversarial-parser convention).
    shape_error = record_shape_error(buckets)
    if shape_error is not None:
        print(f"lint-brand-devflow-sweep: bucket record {buckets_path}: {shape_error}", file=sys.stderr)
        return 2

    if args.update_baseline:
        return cmd_update_baseline(root, buckets, buckets_path)
    if args.print_population:
        return cmd_print_population(root, buckets)
    return cmd_check(root, buckets)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
