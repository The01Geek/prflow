#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Changed-file lint layer for `preflight.py lint-changed` / `lint-full` (issue #1389).

Follow-up to #1276: the declarative lint manifest (`.prflow/lint-manifest.json`,
parsed by `scripts/lint_manifest.py`) describes the bounded lint toolchain; this
module turns that validated manifest plus the current checkout's changed-file set
into a bounded set of advisory lint invocations, and records an atomic receipt per
invocation. It is trusted code that assembles argv from typed fields only — never
from manifest-supplied executable text.

Design invariants this module enforces (each is the wrong outcome it prevents):

* NUL-safe raw bytes. Every git enumeration reads bytes and splits on ``b"\\x00"``;
  a path is carried as raw bytes end to end, so a path with invalid UTF-8, a tab,
  or a newline is neither corrupted nor able to smuggle a second field. The
  canonical identity of a path is unpadded base64url of those raw bytes; a
  display-only text field never participates in identity, dedupe, hashing, or
  selection.
* Three distinct population outcomes. ``established-nonempty``, ``established-empty``,
  and ``unestablished`` are separate — a missing base ref, a shallow-history
  merge-base failure, a diff failure, a malformed ``--raw`` record, and a HEAD that
  moved mid-enumeration each return *unestablished*, never a clean empty set.
* Final-state eligibility. Over the closed record vocabulary
  add/modify/delete/rename/copy/mode/type/symlink/submodule, a deleted path and a
  rename/copy source are examined but not run; an eligible destination runs once;
  a symlink or submodule is never executed and carries a typed reason.
* ``--`` before the first path. Assembled argv always places an end-of-options
  ``--`` before the first manifest-selected path, so a file named like a
  value-taking option (``--exclude=x.py``) reaches the tool as a path.
* Atomic receipts. Each invocation writes exactly one receipt under
  ``.prflow/tmp/lint/<run-id>/<attempt>/<op>-<seq>.json`` behind a locked monotonic
  sequence; a duplicate operation/sequence or a pre-existing path is a named
  non-success, never a silent overwrite.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Running under preflight.py already puts scripts/ on sys.path, but a test that
# loads this module via importlib.util.spec_from_file_location does not — so the
# `import lint_manifest` in `_manifest_provenance` needs this entry too.
sys.path.insert(0, str(Path(__file__).resolve().parent))

RECEIPT_SCHEMA = "prflow-lint-receipt/1"
HELPER_NAME = "lint_changed.py"

# The closed record vocabulary (issue #1389 AC2). A record kind outside this set is
# a bug in the classifier, never a value a caller may invent.
RECORD_KINDS = frozenset(
    {"add", "modify", "delete", "rename", "copy", "mode", "type", "symlink", "submodule"}
)

# language → the tool that lints it. The manifest selector carries the language;
# this trusted mapping — not manifest text — names the executable.
_LANGUAGE_TOOL = {"shell": "shellcheck", "python": "ruff"}

# Broad-invocation base flags per tool, in trusted code (the manifest selector
# carries globs + language, not flags). A special_invocation carries its own
# complete `extra_flags` from the manifest and does not use these. Kept aligned
# with the repository's documented lint commands.
_BROAD_FLAGS = {
    "shellcheck": ["--severity=warning", "-e", "SC1091"],
    "ruff": ["check"],
}

# git mode bits for the file shapes the eligibility rules distinguish.
_MODE_SYMLINK = "120000"
_MODE_GITLINK = "160000"  # a submodule


# ── base64url canonical path identity ────────────────────────────────────────
def b64url(raw: bytes) -> str:
    """Canonical unpadded base64url of raw path bytes (the same idiom workpad.py
    uses for its tokens). This is the identity a path is deduped, hashed, and
    selected by; passing the display text instead would collapse two distinct
    non-UTF-8 paths onto one identity."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def unb64url(token: str) -> bytes:
    """Inverse of :func:`b64url`. Re-pads before decoding so a round-trip recovers
    the exact original bytes."""
    pad = "=" * (-len(token) % 4)
    return base64.urlsafe_b64decode(token + pad)


def _display(raw: bytes) -> str:
    """A lossy human-readable rendering of a path. NEVER used for identity, dedupe,
    hashing, or selection — those read :func:`b64url` of the raw bytes."""
    return raw.decode("utf-8", "replace")


# ── changed-file population ──────────────────────────────────────────────────
class ChangedRecord:
    """One typed changed-file record. ``run_path`` is the final-state path bytes to
    lint, or None when the record is examined-but-not-run (a delete, a rename/copy
    source, a symlink, or a submodule)."""

    __slots__ = ("kind", "src", "dst", "run_path", "skip_reason")

    def __init__(self, kind, *, src=None, dst=None, run_path=None, skip_reason=None):
        if kind not in RECORD_KINDS:
            raise ValueError(f"unknown record kind {kind!r}")
        # Enforce the module's headline eligibility invariant in the type, not just in
        # producer discipline: a record is either run (run_path set, no skip) or
        # examined-but-not-run (run_path None, a typed skip_reason) — never both and never
        # neither. Without this a malformed record could yield a receipt claiming a symlink
        # ran, or an eligible file that was neither run nor skipped.
        if (run_path is None) == (skip_reason is None):
            raise ValueError(
                f"record {kind!r} must set exactly one of run_path / skip_reason "
                "(run, xor examined-but-not-run)"
            )
        self.kind = kind
        self.src = src
        self.dst = dst
        self.run_path = run_path
        self.skip_reason = skip_reason

    def examined_paths(self) -> list[bytes]:
        """The distinct paths this record touched — both a rename's source and
        destination — for the receipt's examined population. A plain modify has
        src == dst, so dedupe keeps it a single examined entry rather than two."""
        return list(dict.fromkeys(p for p in (self.src, self.dst) if p is not None))


class Population:
    """Typed outcome of a changed-file enumeration: established (nonempty|empty) or
    unestablished with a specific reason. Never a plausible-but-unobserved empty."""

    __slots__ = ("status", "records", "reason")

    def __init__(self, status, *, records=None, reason=None):
        if status not in ("nonempty", "empty", "unestablished"):
            raise ValueError(f"invalid population status {status!r}")
        self.status = status
        self.records = records or []
        self.reason = reason

    @property
    def established(self) -> bool:
        return self.status in ("nonempty", "empty")

    def run_paths(self) -> list[bytes]:
        """Deduped final-state paths to run, first occurrence wins (an eligible
        destination runs once even when it changed in several of the four sources)."""
        seen: set[str] = set()
        out: list[bytes] = []
        for rec in self.records:
            if rec.run_path is None:
                continue
            key = b64url(rec.run_path)
            if key not in seen:
                seen.add(key)
                out.append(rec.run_path)
        return out


def _git_bytes(top: str, args: list[str]) -> subprocess.CompletedProcess:
    """Run a git subcommand capturing raw bytes (never text): decoding here would
    corrupt a non-UTF-8 path and defeat this module's NUL-safety guarantee."""
    return subprocess.run(
        ["git", "-C", top, *args], capture_output=True, check=False
    )


def _classify_raw(mode1: str, mode2: str, status: str, path1: bytes, path2: bytes | None):
    """Classify one `git diff --raw` record into a :class:`ChangedRecord`.

    The final path is ``path2`` for a rename/copy, else ``path1``; the final mode is
    ``mode2``. A symlink or submodule final shape is never run (a typed skip); a
    delete has no final state; a rename/copy source is examined via ``src`` but only
    the destination runs.
    """
    letter = status[0]
    final_path = path2 if path2 is not None else path1
    if letter == "D":
        return ChangedRecord("delete", src=path1, dst=None, skip_reason="deleted-final-absent")
    if _MODE_GITLINK in (mode1, mode2):
        return ChangedRecord("submodule", src=path1, dst=final_path, skip_reason="submodule-not-executed")
    if mode2 == _MODE_SYMLINK:
        return ChangedRecord("symlink", src=path1, dst=final_path, skip_reason="symlink-not-executed")
    if letter == "R":
        return ChangedRecord("rename", src=path1, dst=path2, run_path=path2)
    if letter == "C":
        return ChangedRecord("copy", src=path1, dst=path2, run_path=path2)
    if letter == "T":
        return ChangedRecord("type", src=path1, dst=final_path, run_path=final_path)
    if letter == "A":
        return ChangedRecord("add", dst=final_path, run_path=final_path)
    if letter == "M":
        if mode1 != mode2:
            return ChangedRecord("mode", src=path1, dst=final_path, run_path=final_path)
        return ChangedRecord("modify", src=path1, dst=final_path, run_path=final_path)
    return None  # unrecognised status letter → caller treats as malformed


def _parse_raw_z(data: bytes) -> list[ChangedRecord] | None:
    """Parse `git diff --raw -z` bytes into records, or None on a malformed stream.

    Each record is a metadata token (``:m1 m2 s1 s2 STATUS``) followed by one path
    (two for rename/copy). A None return signals *unestablished malformed-status*
    to the caller rather than a clean empty parse.
    """
    tokens = data.split(b"\x00")
    records: list[ChangedRecord] = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok == b"":
            i += 1
            continue
        if not tok.startswith(b":"):
            return None
        try:
            meta = tok.decode("ascii")
        except UnicodeDecodeError:
            return None
        parts = meta[1:].split(" ")
        if len(parts) != 5:
            return None
        mode1, mode2, _sha1, _sha2, status = parts
        if not status:
            return None
        letter = status[0]
        two_paths = letter in ("R", "C")
        need = 2 if two_paths else 1
        if i + need >= n:
            return None
        path1 = tokens[i + 1]
        path2 = tokens[i + 2] if two_paths else None
        rec = _classify_raw(mode1, mode2, status, path1, path2)
        if rec is None:
            return None
        records.append(rec)
        i += 1 + need
    return records


def _untracked_records(top: str) -> list[ChangedRecord] | None:
    """Untracked, non-ignored paths as add/symlink/submodule records (NUL-safe)."""
    proc = _git_bytes(top, ["ls-files", "--others", "--exclude-standard", "-z"])
    if proc.returncode != 0:
        return None
    records: list[ChangedRecord] = []
    for raw in proc.stdout.split(b"\x00"):
        if not raw:
            continue
        abspath = os.path.join(os.fsencode(top), raw)
        if os.path.islink(abspath):
            records.append(ChangedRecord("symlink", dst=raw, skip_reason="symlink-not-executed"))
        elif os.path.isdir(abspath) and os.path.isdir(os.path.join(abspath, b".git")):
            records.append(ChangedRecord("submodule", dst=raw, skip_reason="submodule-not-executed"))
        else:
            records.append(ChangedRecord("add", dst=raw, run_path=raw))
    return records


def enumerate_population(base: str, top: str) -> Population:
    """The NUL-safe union of committed (merge-base→HEAD), staged, unstaged, and
    untracked changed-file records for the current checkout.

    Fails closed to *unestablished* — never a clean empty set — when the base ref is
    missing, the merge base cannot be found (a shallow clone), any diff fails, a
    ``--raw`` record is malformed, or HEAD moves mid-enumeration.
    """
    base_ref = f"refs/remotes/origin/{base}"
    if _git_bytes(top, ["rev-parse", "--verify", "--quiet", base_ref]).returncode != 0:
        return Population("unestablished", reason="missing-base-ref")

    head_before = _git_bytes(top, ["rev-parse", "HEAD"])
    if head_before.returncode != 0:
        return Population("unestablished", reason="head-unresolved")

    mb = _git_bytes(top, ["merge-base", base_ref, "HEAD"])
    if mb.returncode != 0 or not mb.stdout.strip():
        return Population("unestablished", reason="no-merge-base")
    merge_base = mb.stdout.strip().decode("ascii", "replace")

    diff_specs = [
        ["diff", "--raw", "-z", "--find-renames", "--find-copies", merge_base, "HEAD"],
        ["diff", "--raw", "-z", "--find-renames", "--find-copies", "--cached"],
        ["diff", "--raw", "-z", "--find-renames", "--find-copies"],
    ]
    all_records: list[ChangedRecord] = []
    for spec in diff_specs:
        proc = _git_bytes(top, spec)
        if proc.returncode != 0:
            return Population("unestablished", reason="diff-failed")
        parsed = _parse_raw_z(proc.stdout)
        if parsed is None:
            return Population("unestablished", reason="malformed-status")
        all_records.extend(parsed)

    untracked = _untracked_records(top)
    if untracked is None:
        return Population("unestablished", reason="untracked-failed")
    all_records.extend(untracked)

    head_after = _git_bytes(top, ["rev-parse", "HEAD"])
    if head_after.returncode != 0 or head_after.stdout != head_before.stdout:
        return Population("unestablished", reason="concurrent-mutation")

    status = "nonempty" if all_records else "empty"
    return Population(status, records=all_records)


# ── manifest-driven selection ────────────────────────────────────────────────
def _glob_to_regex(pattern: str) -> re.Pattern:
    """Translate a manifest glob into an anchored regex. ``**/`` matches zero or more
    leading directories, ``**`` matches across ``/``, ``*`` stays within one segment,
    ``?`` matches one non-``/`` char, and ``[...]`` is a character class. Any other
    metacharacter is matched literally."""
    out = ["(?s)\\A"]
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:[^\\x00]*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append("[^\\x00]*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = pattern.find("]", i + 1)
            if j == -1:
                out.append("\\[")
                i += 1
            else:
                out.append("[" + pattern[i + 1 : j] + "]")
                i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    out.append("\\Z")
    return re.compile("".join(out))


_GLOB_CACHE: dict[str, re.Pattern] = {}


def _glob_match(pattern: str, path: str) -> bool:
    rx = _GLOB_CACHE.get(pattern)
    if rx is None:
        rx = _glob_to_regex(pattern)
        _GLOB_CACHE[pattern] = rx
    return rx.match(path) is not None


class Invocation:
    """One assembled lint invocation: a tool, its flags, the selected path bytes, and
    the operation id its receipt is keyed by."""

    __slots__ = ("op_id", "tool", "flags", "paths", "timeout")

    def __init__(self, op_id, tool, flags, paths, timeout):
        # The type is the argv trust boundary, so refuse a self-contradictory invocation
        # at construction rather than emitting a broken command or a zero-timeout run.
        if not tool:
            raise ValueError("Invocation requires a non-empty tool")
        if not isinstance(timeout, int) or timeout <= 0:
            raise ValueError(f"Invocation timeout must be a positive int, got {timeout!r}")
        self.op_id = op_id
        self.tool = tool
        self.flags = flags
        self.paths = paths  # list[bytes]
        self.timeout = timeout

    def argv(self) -> list[str]:
        """The command line, with an end-of-options ``--`` before the first path so a
        file named like a value-taking option is treated as a path, not a flag."""
        return [self.tool, *self.flags, "--", *[os.fsdecode(p) for p in self.paths]]


def _tool_timeout(manifest: dict, tool: str) -> int:
    return int(manifest["tools"][tool]["timeout_seconds"])


def _selector_claims(path: str, sel: dict, exclusions: list) -> bool:
    """One definition of the broad-selector claim rule — an include match, no exclude
    match, and no top-level exclusion — so the changed-file and full paths cannot drift
    a selection-semantics change between two inlined copies."""
    if not any(_glob_match(g, path) for g in sel["include_globs"]):
        return False
    if any(_glob_match(g, path) for g in sel.get("exclude_globs", [])):
        return False
    return not any(_glob_match(g, path) for g in exclusions)


def select_invocations(run_paths: list[bytes], manifest: dict) -> list[Invocation]:
    """Map deduped final-state run paths through the manifest's closed selector and
    special-invocation rules into assembled invocations.

    A path matching a special invocation uses that invocation alone and is absent
    from every broad selector invocation (issue #1389 AC5). Otherwise the first
    selector whose include matches, whose excludes do not, and which no top-level
    exclusion covers, claims the path for its broad invocation.
    """
    specials = manifest.get("special_invocations", [])
    selectors = manifest["selectors"]
    exclusions = manifest.get("exclusions", [])

    # Preserve manifest order for deterministic op ids, batching paths per op.
    special_batches: dict[str, list[bytes]] = {}
    selector_batches: dict[str, list[bytes]] = {}

    for raw in run_paths:
        path = os.fsdecode(raw)
        claimed = None
        for si in specials:
            if _glob_match(si["path"], path):
                claimed = si["id"]
                break
        if claimed is not None:
            special_batches.setdefault(claimed, []).append(raw)
            continue
        for sel in selectors:
            if _selector_claims(path, sel, exclusions):
                selector_batches.setdefault(sel["id"], []).append(raw)
                break

    invocations: list[Invocation] = []
    for si in specials:
        paths = special_batches.get(si["id"])
        if not paths:
            continue
        tool = si["tool"]
        invocations.append(
            Invocation(si["id"], tool, list(si["extra_flags"]), paths, _tool_timeout(manifest, tool))
        )
    for sel in selectors:
        paths = selector_batches.get(sel["id"])
        if not paths:
            continue
        tool = _LANGUAGE_TOOL[sel["language"]]
        invocations.append(
            Invocation(sel["id"], tool, list(_BROAD_FLAGS[tool]), paths, _tool_timeout(manifest, tool))
        )
    return invocations


def select_full_invocations(top: str, manifest: dict) -> list[Invocation]:
    """Repository-wide invocations for `lint-full`: one per full_profile over its
    selector's manifest-matched tracked files, plus each special invocation over its
    own path when that file is tracked."""
    tracked = _git_bytes(top, ["ls-files", "-z"])
    tracked_raw = [p for p in tracked.stdout.split(b"\x00") if p] if tracked.returncode == 0 else []
    # Decode the (repo-sized) tracked set once and reuse across every special and profile,
    # rather than re-decoding each path once per manifest rule.
    tracked_paths = [(raw, os.fsdecode(raw)) for raw in tracked_raw]
    exclusions = manifest.get("exclusions", [])
    selectors = {s["id"]: s for s in manifest["selectors"]}

    invocations: list[Invocation] = []
    # A path a special invocation claims is linted by that invocation alone and is absent
    # from every broad profile — the same exclusivity select_invocations enforces on the
    # changed-file path. Without this, a future special whose file a broad selector also
    # includes would be double-linted here (for a run.sh-shaped file, the ShellCheck OOM the
    # special exists to avoid).
    special_claimed: set[str] = set()
    for si in manifest.get("special_invocations", []):
        matched = [raw for raw, path in tracked_paths if _glob_match(si["path"], path)]
        if matched:
            special_claimed.update(b64url(raw) for raw in matched)
            tool = si["tool"]
            invocations.append(
                Invocation(si["id"], tool, list(si["extra_flags"]), matched, _tool_timeout(manifest, tool))
            )
    for prof in manifest["full_profiles"]:
        sel = selectors[prof["selector"]]
        paths = [
            raw for raw, path in tracked_paths
            if _selector_claims(path, sel, exclusions) and b64url(raw) not in special_claimed
        ]
        if not paths:
            continue
        # Single-source the tool from the selector's language (the changed-file path does the
        # same), so a manifest whose full_profile.tool disagreed with its selector's language
        # cannot silently lint a language with the wrong tool here.
        tool = _LANGUAGE_TOOL[sel["language"]]
        invocations.append(
            Invocation(prof["id"], tool, list(_BROAD_FLAGS[tool]), paths, _tool_timeout(manifest, tool))
        )
    return invocations


# ── atomic receipts ──────────────────────────────────────────────────────────
class ReceiptError(Exception):
    """A named receipt non-success (a duplicate path, or a sequence-lock failure)."""


class ReceiptWriter:
    """Writes one atomic receipt per invocation under
    ``.prflow/tmp/lint/<run-id>/<attempt>/<op>-<seq>.json`` behind a locked monotonic
    sequence. A pre-existing target path or a duplicate ``<op>-<seq>`` is refused as a
    named non-success, never a silent overwrite."""

    def __init__(self, top: str, run_id: str, attempt: str):
        self.dir = Path(top) / ".prflow" / "tmp" / "lint" / _safe(run_id) / _safe(attempt)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock_path = self.dir / ".seq.lock"
        self._seq_path = self.dir / ".seq"

    def _next_seq(self) -> int:
        """Read-increment-write the monotonic sequence under an exclusive file lock, so
        two concurrent writers in the same run directory cannot mint the same seq."""
        with open(self._lock_path, "w", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                try:
                    current = int(self._seq_path.read_text(encoding="utf-8"))
                except (FileNotFoundError, ValueError):
                    current = 0
                self._seq_path.write_text(str(current + 1), encoding="utf-8")
                return current
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def write(self, op: str, fields: dict) -> tuple[str, int]:
        seq = self._next_seq()
        target = self.dir / f"{op}-{seq}.json"
        payload = dict(fields)
        payload["sequence"] = seq
        payload["operation"] = op
        blob = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        try:
            fd = os.open(str(target), os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o644)
        except FileExistsError as exc:
            raise ReceiptError(f"duplicate-receipt-path: {target.name} already exists") from exc
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(blob)
        except OSError as exc:  # pragma: no cover - filesystem failure
            raise ReceiptError(f"receipt-write-failed: {exc}") from exc
        return (str(target), seq)


def _safe(component: str) -> str:
    """A filesystem-safe run/attempt directory component; empties degrade to a
    named placeholder so a receipt path is always well-formed."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", component or "")
    return cleaned or "unknown"


# ── receipt field assembly + invocation execution ───────────────────────────
def _tool_version(tool_bin: str) -> str | None:
    try:
        proc = subprocess.run(
            [tool_bin, "--version"], capture_output=True, text=True,
            errors="replace", timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = (proc.stdout or proc.stderr or "").strip().splitlines()
    return out[0] if out else None


def _path_entry(raw: bytes) -> dict:
    return {"canonical": b64url(raw), "display": _display(raw)}


def _examined_population(pop: Population) -> list[dict]:
    entries: list[dict] = []
    for rec in pop.records:
        for raw in rec.examined_paths():
            entry = _path_entry(raw)
            entry["kind"] = rec.kind
            entry["run"] = rec.run_path is not None and raw == rec.run_path
            if rec.skip_reason:
                entry["skip_reason"] = rec.skip_reason
            entries.append(entry)
    return entries


def _run_invocation(inv: Invocation, top: str, tool_cache: dict) -> dict:
    """Execute one invocation advisorily and return its receipt outcome fields. A tool
    absent from PATH is a named non-success (``tool-absent``), never an install. The
    tool binary and its ``--version`` are resolved once per tool via ``tool_cache``, so
    a run with several invocations of the same tool spawns no redundant probes."""
    if inv.tool not in tool_cache:
        _bin = shutil.which(inv.tool)
        tool_cache[inv.tool] = (_bin, _tool_version(_bin) if _bin else None)
    tool_bin, tool_version = tool_cache[inv.tool]
    result = {
        "tool": inv.tool,
        "argv": inv.argv(),
        "timeout_seconds": inv.timeout,
        "selected": [_path_entry(p) for p in inv.paths],
    }
    if tool_bin is None:
        result.update(exit=None, duration_ms=0, outcome="tool-absent", tool_version=None)
        return result
    result["tool_version"] = tool_version
    # Reuse Invocation.argv()'s shape (tool, flags, --, paths) with the resolved binary
    # in argv[0], so the executed command and the receipt's recorded argv cannot drift.
    argv = [tool_bin, *inv.argv()[1:]]
    started = time.monotonic()
    try:
        proc = subprocess.run(
            argv, cwd=top, capture_output=True, text=True,
            errors="replace", timeout=inv.timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        result.update(exit=None, duration_ms=int((time.monotonic() - started) * 1000), outcome="timeout")
        return result
    except OSError as exc:
        result.update(exit=None, duration_ms=0, outcome=f"error: {exc.__class__.__name__}")
        return result
    result.update(
        exit=proc.returncode,
        duration_ms=int((time.monotonic() - started) * 1000),
        outcome="ran",
        findings=(proc.stdout or "") + (proc.stderr or ""),
    )
    return result


# ── subcommand entrypoints (driven by preflight.py's argparse) ───────────────
# Exit-code contract, shared by both subcommands:
#   0  established, invocations ran (advisory — lint FINDINGS never fail the run)
#   2  population or manifest unestablished (an unknown set is not a clean empty one)
#   3  no repository root, or a named receipt non-success
LINT_OK = 0
LINT_UNESTABLISHED = 2
LINT_ERROR = 3


def _repo_toplevel(cwd: str | None = None) -> str | None:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False, cwd=cwd
    )
    top = proc.stdout.strip()
    return top if proc.returncode == 0 and top else None


def _config_base(top: str) -> str:
    """Read `.base_branch` from `.prflow/config.json` in-process (never a PATH tool),
    defaulting to `main`; a missing or malformed config never fails the read."""
    try:
        data = json.loads((Path(top) / ".prflow" / "config.json").read_text(encoding="utf-8"))
        value = data.get("base_branch")
        if isinstance(value, str) and value:
            return value
    except FileNotFoundError:
        # No config is the ordinary "base is main" case, not a corruption — stay silent.
        pass
    except (OSError, ValueError, AttributeError) as exc:
        # A present-but-malformed config (bad JSON, a non-object top level, a non-string
        # base) is distinct from an absent one: emit a breadcrumb so a corrupt config that
        # silently reshapes the changed population against origin/main is visible, rather
        # than reading identically to "no config". The read still never fails (returns main).
        print(
            f"LINT config-base fallback: malformed .prflow/config.json "
            f"({exc.__class__.__name__}); defaulting base=main",
            file=sys.stderr,
        )
    return "main"


def _manifest_provenance(manifest_path: Path):
    """Load and validate the manifest, returning (result, provenance-dict). The
    provenance digest is over the exact bytes read, so a receipt records which
    manifest it selected against."""
    import lint_manifest  # sibling module; resolved via preflight.py's sys.path entry

    try:
        raw = manifest_path.read_bytes()
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    except OSError:
        digest = None
    result = lint_manifest.load_manifest(manifest_path)
    provenance = {
        "path": str(manifest_path),
        "status": result.status,
        "reason": result.reason,
        "digest": digest,
    }
    return result, provenance


def _resolve_manifest_path(args, top: str) -> Path:
    explicit = getattr(args, "manifest", None) or os.environ.get("DEVFLOW_LINT_MANIFEST")
    if explicit:
        p = Path(explicit)
        return p if p.is_absolute() else Path(top) / p
    return Path(top) / ".prflow" / "lint-manifest.json"


def _run_id_attempt(args) -> tuple[str, str]:
    run_id = getattr(args, "run_id", None) or os.environ.get("GITHUB_RUN_ID") or "local"
    attempt = getattr(args, "run_attempt", None) or os.environ.get("GITHUB_RUN_ATTEMPT") or "1"
    return run_id, attempt


def _base_receipt_fields(subcommand, run_id, attempt, provenance) -> dict:
    return {
        "schema": RECEIPT_SCHEMA,
        "subcommand": subcommand,
        "run_id": run_id,
        "attempt": attempt,
        "manifest_provenance": provenance,
        "helper_provenance": {"helper": HELPER_NAME, "receipt_schema": RECEIPT_SCHEMA},
    }


def _emit_invocations(invocations, pop, top, writer, base_fields, examined) -> int:
    """Run each invocation, write its receipt, and return the receipt count. A named
    receipt non-success raises `ReceiptError` to the caller."""
    written = 0
    tool_cache: dict = {}
    for inv in invocations:
        outcome = _run_invocation(inv, top, tool_cache)
        fields = dict(base_fields)
        fields.update(outcome)
        if examined is not None:
            fields["examined"] = examined
        fields["skips"] = _skip_entries(pop) if pop is not None else []
        writer.write(inv.op_id, fields)
        written += 1
    return written


def _skip_entries(pop: Population) -> list[dict]:
    entries = []
    for rec in pop.records:
        if rec.skip_reason:
            raw = rec.dst if rec.dst is not None else rec.src
            if raw is not None:
                entry = _path_entry(raw)
                entry["reason"] = rec.skip_reason
                entries.append(entry)
    return entries


def cmd_lint_changed(args) -> int:
    top = _repo_toplevel()
    if top is None:
        print("LINT-CHANGED error no-repository-root", file=sys.stderr)
        return LINT_ERROR
    manifest_path = _resolve_manifest_path(args, top)
    result, provenance = _manifest_provenance(manifest_path)
    if not result.established:
        print(f"LINT-CHANGED unestablished-manifest {result.reason}")
        return LINT_UNESTABLISHED
    base = getattr(args, "base", None) or _config_base(top)
    pop = enumerate_population(base, top)
    if not pop.established:
        print(f"LINT-CHANGED unestablished {pop.reason}")
        return LINT_UNESTABLISHED

    run_id, attempt = _run_id_attempt(args)
    invocations = select_invocations(pop.run_paths(), result.manifest)
    base_fields = _base_receipt_fields("lint-changed", run_id, attempt, provenance)
    examined = _examined_population(pop)
    writer = ReceiptWriter(top, run_id, attempt)
    try:
        written = _emit_invocations(invocations, pop, top, writer, base_fields, examined)
    except ReceiptError as exc:
        print(f"LINT-CHANGED receipt-non-success {exc}", file=sys.stderr)
        return LINT_ERROR
    print(
        f"LINT-CHANGED established-{pop.status} population={len(pop.records)} "
        f"run={len(pop.run_paths())} invocations={len(invocations)} receipts={written}"
    )
    return LINT_OK


def cmd_lint_full(args) -> int:
    top = _repo_toplevel()
    if top is None:
        print("LINT-FULL error no-repository-root", file=sys.stderr)
        return LINT_ERROR
    manifest_path = _resolve_manifest_path(args, top)
    result, provenance = _manifest_provenance(manifest_path)
    if not result.established:
        print(f"LINT-FULL unestablished-manifest {result.reason}")
        return LINT_UNESTABLISHED

    run_id, attempt = _run_id_attempt(args)
    invocations = select_full_invocations(top, result.manifest)
    base_fields = _base_receipt_fields("lint-full", run_id, attempt, provenance)
    writer = ReceiptWriter(top, run_id, attempt)
    try:
        written = _emit_invocations(invocations, None, top, writer, base_fields, None)
    except ReceiptError as exc:
        print(f"LINT-FULL receipt-non-success {exc}", file=sys.stderr)
        return LINT_ERROR
    print(f"LINT-FULL profiles={len(invocations)} receipts={written}")
    return LINT_OK
