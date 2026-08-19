#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Produce the five-field checkout fingerprint the verification-flight ledger keys on.

`scripts/verification-flight.py` derives its per-checkout flight key from a `checkout`
object of exactly five fields (its `_CHECKOUT_REQUIRED` tuple), but nothing in the tree
produced those fields — callers invented them per run and `_validate_checkout` accepted any
non-empty string, so a stale flight over a moved tree could still read as a pass (issue #1243).
This helper is that missing producer: the ONE place each field's derivation is defined, so a
reader never has to reconstruct what a field means from ad-hoc caller code.

It emits a single JSON object `{checkout_id, head, index_digest, tracked_digest,
untracked_digest}` (sorted keys, compact) to stdout. The four content fields are git object
ids (40-hex SHA-1, or 64-hex SHA-256), which is exactly the shape `_validate_checkout` now
requires — so a fingerprint this helper emits is declaration-valid and the junk strings the
old callers invented ("v", "clean", "clean-no-untracked", …) are not.

Field derivations (each stated here exactly once — this header is the single source of truth):

  checkout_id      `git rev-parse --absolute-git-dir` — the absolute path of THIS checkout's
                   git directory. Worktree-unique (each linked worktree has its own git dir),
                   so it distinguishes flights taken in different checkouts of the same repo.
                   It is an opaque identity, NOT a tree-content signal — the four fields below
                   carry the content, and only they are shape-checked as object ids.
  head             `git rev-parse HEAD` — the checked-out commit. Forty zeros on an unborn
                   HEAD (a repo with no commits). Changes on commit / merge / rebase / checkout.
  index_digest     `git write-tree` — the tree object of the current index (STAGED content).
  tracked_digest   `git write-tree` over a scratch index seeded from the real index, backdated
                   to arm git's racy-stat rule (issue #1117), and then `git add -u`'d — the
                   working-tree content of TRACKED files, capturing unstaged edits the index
                   does not. Changes on any edit to a tracked file.
  untracked_digest `git write-tree` over a fresh EMPTY scratch index into which the untracked,
                   non-ignored files are added — the empty-tree id when there are none.
                   Changes when an untracked (non-ignored) file is added, edited, or removed.

Fail-closed: any git failure that prevents establishing a field exits non-zero with a stderr
breadcrumb and prints NO object, so a caller never embeds a partial or invented fingerprint.
It runs git (unlike verification-flight.py, which by contract runs nothing); it makes no
network call.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

_ZERO_SHA1 = "0" * 40
# The object-id shape the four content fields must satisfy — 40-hex (SHA-1) or
# 64-hex (SHA-256). COUPLED with scripts/verification-flight.py's `_OBJECT_ID_RE`
# (its `_validate_checkout` rejects anything else): this producer self-checks its
# own output against the same shape below so it can never emit a fingerprint the
# consumer would reject, keeping the two sides of the five-field contract in step.
_OBJECT_ID_RE = re.compile(r"\A(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_OBJECT_ID_FIELDS = ("head", "index_digest", "tracked_digest", "untracked_digest")
# Honor the DEVFLOW_GIT override without probing, mirroring the DEVFLOW_GH escape
# hatch and scripts/reception_identity.py's sibling GIT resolution.
_GIT = os.environ.get("DEVFLOW_GIT") or "git"
# The whole-second mtime the seeded scratch index is backdated to (issue #1117). 1,
# not 0: git reads a zero index timestamp as "unset" and short-circuits its racy-stat
# rule, so 1 is the smallest value that arms it. See _tracked_digest.
_INDEX_BACKDATE_SECONDS = 1


class _GitError(Exception):
    """A git invocation that failed — a fingerprint field could not be established."""


def _git(args: list[str], cwd: str, env: dict | None = None, check: bool = True) -> str:
    proc = subprocess.run(
        [_GIT, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise _GitError(f"git {' '.join(args)} failed (rc={proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


def _toplevel() -> str:
    proc = subprocess.run(
        [_GIT, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise _GitError(f"not a git checkout: {proc.stderr.strip()}")
    top = proc.stdout.strip()
    if not top:
        raise _GitError("git rev-parse --show-toplevel produced no path")
    return top


def _head(top: str) -> str:
    # A committed HEAD resolves directly.
    proc = subprocess.run(
        [_GIT, "rev-parse", "--verify", "HEAD"],
        cwd=top,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0:
        return proc.stdout.strip() or _ZERO_SHA1
    # A non-zero result is NOT blanket-treated as "unborn": that would let a corrupt
    # ref store, an unreadable HEAD, or a broken DEVFLOW_GIT binary emit a shape-valid
    # but factually wrong all-zero head while the other fields succeed, breaking the
    # module's "any git failure prints no object and exits non-zero" contract. A
    # genuinely unborn HEAD is a symbolic ref that resolves to no object; only that is
    # the zero sentinel. Any other failure fails closed.
    symref = subprocess.run(
        [_GIT, "symbolic-ref", "-q", "HEAD"],
        cwd=top,
        capture_output=True,
        text=True,
        check=False,
    )
    if symref.returncode == 0 and symref.stdout.strip():
        return _ZERO_SHA1
    raise _GitError(f"could not resolve HEAD: {proc.stderr.strip()}")


def _write_tree(top: str, env: dict | None = None) -> str:
    tree = _git(["write-tree"], cwd=top, env=env).strip()
    if not tree:
        raise _GitError("git write-tree produced no tree id")
    return tree


def _tracked_digest(top: str) -> str:
    """Working-tree content of tracked files (staged + unstaged), via a scratch index."""
    real_index = _git(["rev-parse", "--git-path", "index"], cwd=top).strip()
    if not real_index:
        # git always names the index path; an empty result is an attributable failure,
        # not a signal to copy the toplevel directory into the scratch index.
        raise _GitError("git rev-parse --git-path index produced no path")
    src = real_index if os.path.isabs(real_index) else os.path.join(top, real_index)
    with tempfile.TemporaryDirectory() as td:
        scratch = os.path.join(td, "index")
        # Seed the scratch index from the real one when it exists (an unborn/empty
        # checkout may have none — then start from an empty index).
        if real_index and os.path.exists(src):
            shutil.copyfile(src, scratch)
            # Backdate the seeded index so git's racy-index rule forces `git add -u`
            # to re-hash every tracked entry instead of trusting the copied pre-edit
            # stat data — otherwise a tracked file rewritten to the SAME size within
            # the mtime tick the index cached reads as clean and the tree carries the
            # stale blob (issue #1117). This mirrors scripts/reception_identity.py's
            # hardened derivation, whose docstring carries the full rationale. The
            # stored value is verified because os.utime reports only that the syscall
            # succeeded while the filesystem decides what it keeps; a filesystem that
            # stores 0 ("unset") or a later value silently disarms the rule, so a
            # mismatch fails closed rather than fingerprinting from unprotected stat data.
            os.utime(scratch, (_INDEX_BACKDATE_SECONDS, _INDEX_BACKDATE_SECONDS))
            stored = int(os.stat(scratch).st_mtime)
            if stored != _INDEX_BACKDATE_SECONDS:
                raise _GitError(
                    f"index backdate ineffective (stored mtime {stored}); tracked_digest "
                    "could carry a stale blob on this filesystem (issue #1117)"
                )
        env = {**os.environ, "GIT_INDEX_FILE": scratch}
        # add -u updates ONLY already-tracked entries to their working-tree content;
        # it never introduces untracked files, keeping this field tracked-only.
        _git(["add", "-u"], cwd=top, env=env)
        return _write_tree(top, env)


def _untracked_digest(top: str) -> str:
    """Content of untracked, non-ignored files, via a fresh empty scratch index."""
    listing = _git(["ls-files", "-o", "--exclude-standard", "-z"], cwd=top)
    paths = [p for p in listing.split("\0") if p]
    with tempfile.TemporaryDirectory() as td:
        scratch = os.path.join(td, "index")
        env = {**os.environ, "GIT_INDEX_FILE": scratch}
        _git(["read-tree", "--empty"], cwd=top, env=env)
        if paths:
            # `add --` treats every remaining token as a literal pathspec, so a path
            # with spaces / unicode / a leading dash is added correctly.
            _git(["add", "--", *paths], cwd=top, env=env)
        return _write_tree(top, env)


def build_fingerprint() -> dict:
    top = _toplevel()
    fp = {
        "checkout_id": _git(["rev-parse", "--absolute-git-dir"], cwd=top).strip(),
        "head": _head(top),
        "index_digest": _write_tree(top),
        "tracked_digest": _tracked_digest(top),
        "untracked_digest": _untracked_digest(top),
    }
    # Self-check against the consumer's object-id contract (coupled _OBJECT_ID_RE):
    # fail closed rather than emit a fingerprint verification-flight.py would reject,
    # so a future derivation bug surfaces here at the producer rather than as an
    # opaque `checkout_field_bad_shape` on the read side.
    for key in _OBJECT_ID_FIELDS:
        if not _OBJECT_ID_RE.match(fp[key]):
            raise _GitError(f"derived {key} is not a git object id: {fp[key]!r}")
    return fp


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8 on the CLI entry path only (not at import, so a
    unit-test import never mutates the importer's streams). A no-op where the ambient
    codec is already UTF-8; self-defends against a non-UTF-8 default codec such as
    Windows cp1252. Tolerates a non-TextIOWrapper stream (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_streams()
    try:
        fp = build_fingerprint()
    except _GitError as exc:
        print(f"checkout-fingerprint: {exc}", file=sys.stderr)
        return 1
    if not fp.get("checkout_id"):
        print("checkout-fingerprint: could not establish checkout_id", file=sys.stderr)
        return 1
    sys.stdout.write(json.dumps(fp, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
