#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Content-based candidate-identity derivation for receiving-review sessions (issue #668).

An importable, python3 standard-library-only routine. It derives ONE value — the
git tree object ID of the working-tree *content*: tracked files at their
working-tree content plus untracked non-ignored files, with gitignored content
excluded, and with HEAD excluded from the input. The current index is an INPUT,
not an exclusion: for an ordinary path `git add -A` resolves the entry to
worktree content, but for an entry git deliberately does not re-stat — a
skip-worktree (cone-mode sparse) entry, which has no on-disk content to read, or
an `assume-unchanged` (CE_VALID) entry, which does — the INDEX content decides
the value, and an `assume-unchanged` path's worktree edit therefore does not
change the derived identity. Both are the documented consequence of seeding from
the real index (see the seeding paragraph below), which is load-bearing for
sparse checkouts. This is the single machine-checkable session identity the
Reception Preflight records and later consumers re-derive.

Derivation is index-cached plumbing, not a hand-rolled tree walk: a temporary
index is SEEDED from the repository's current index and BACKDATED to a mtime of 1
(the racy floor), `git add -A` stages every working-tree content change (edits, deletions,
renames, and untracked non-ignored files) into that temporary index, and
`git write-tree` prints the resulting tree object ID. The backdate is load-bearing
for content-correctness: the seeded index carries each entry's pre-edit stat data,
so without it `git add -A` trusts a stale-but-clean stat and never re-hashes a
tracked file rewritten to the same size within the mtime tick the index cached — the
tree would then carry the old blob (issue #1117). Backdating the temp index makes
every ordinary entry "racily clean" by git's own rule (cached mtime not strictly
older than the index), which forces git to re-read content independent of stat
timing. The backdate is then read back and verified before anything is staged:
`os.utime` reports only that the syscall succeeded, while the filesystem decides
what it stores, and both a stored 0 (read as "unset") and a stored value later than
the entries' cached mtimes disarm the rule silently — so a stored second other than
the requested one raises `index_backdate_ineffective` instead of deriving an
identity from stat data the backdate never protected. Going through git's racy
machinery rather than around it (e.g. an unqualified
`add --renormalize`) is deliberate: the skip-worktree and `assume-unchanged` entries
git deliberately does not re-stat both bypass the racy re-check, so the INDEX content
still decides their contribution — see the skip-worktree/assume-unchanged paragraph
below. The repository's own index is never modified (the derivation writes to
a private `GIT_INDEX_FILE`; it does add unreferenced blob/tree objects to the
object database, which are GC-collectable and touch no ref), and no repository
history is read. The backdate does raise the cost profile: forcing every ordinary
entry racy makes `git add -A` re-hash the content of every tracked file (not only
the changed ones), so the cost now scales with the number of tracked plus untracked
non-ignored files rather than with the changed-file count — a deliberate tradeoff
accepted for stat-timing-independent correctness (issue #1117). It still reads no
history, so it does not scale with repository depth.

Seeding the temporary index from the current index is load-bearing, not an
optimization: a cone-mode sparse checkout leaves skip-worktree entries off disk,
and only the seeded entries preserve them — a fresh empty index would drop those
paths and yield a tree that omits content the eventual commit still records.

Invariants (mirrors scripts/workpad.py's Windows-safe native-git pattern,
issues #275/#295):
  * git is invoked as a native subprocess with an argv list (never a shell
    string), so filenames containing whitespace or newlines never break parsing —
    git stages the content itself rather than this module enumerating paths.
  * No PyYAML import, no `gh` call, no network call, and no decisive value is
    derived through a non-preflight PATH tool (`tr`/`sed`/`wc`/`cut`/`head`).
  * Every failure mode raises IdentityError with a named reason and yields no
    identity — a caller that prints the identity only on success can never print
    a value read as a derived identity when the derivation failed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

# git is a hard preflight prerequisite; invoked directly like scripts/workpad.py.
# A DEVFLOW_GIT override mirrors the DEVFLOW_GH escape hatch without probing.
GIT = os.environ.get("DEVFLOW_GIT") or "git"

# The whole-second mtime the seeded temporary index is backdated to, and the value
# the post-condition read-back requires the filesystem to have actually stored.
# 1, not 0: git reads a zero index timestamp as "unset" and short-circuits
# `is_racy_stat`, so the epoch second itself would disarm the very rule the
# backdate exists to arm. See derive_candidate_identity.
_INDEX_BACKDATE_SECONDS = 1


class IdentityError(Exception):
    """A candidate-identity derivation that could not complete.

    `.reason` is a named machine-readable breadcrumb (never a bare traceback):
    `git_not_found`, `git_exec_error:<class>`, `git_failed:<subcommand>:<code>`,
    `git_output_not_utf8:<subcommand>`, `temp_index_error:<class>`,
    `index_backdate_ineffective:<stored-second>`, or `empty_tree_output`. The
    caller prints it to stderr and prints no identity.
    """

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _run_git(args: list[str], cwd: str, extra_env: dict | None = None) -> bytes:
    """Run `git <args>` in `cwd`, returning stdout bytes, raising IdentityError.

    Native subprocess with an argv list and no shell. A missing git binary, an
    exec error, and a non-zero exit each become a distinct named IdentityError.
    """
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    try:
        proc = subprocess.run(
            [GIT, *args],
            cwd=cwd,
            env=env,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise IdentityError("git_not_found") from exc
    except OSError as exc:
        raise IdentityError(f"git_exec_error:{exc.__class__.__name__}") from exc
    if proc.returncode != 0:
        # The subcommand plus the exit code names the failure; the raw stderr is
        # not folded into the reason (it is attacker-influenceable and unbounded).
        raise IdentityError(f"git_failed:{args[0]}:{proc.returncode}")
    return proc.stdout


def _run_git_text(args: list[str], cwd: str, extra_env: dict | None = None) -> str:
    """`_run_git` decoded to stripped UTF-8 text, raising IdentityError on bad bytes.

    Decoding lives here rather than at each call site so the module's
    every-failure-mode-is-a-named-IdentityError contract holds by construction.
    A git-dir path (or any git stdout) that is not valid UTF-8 is reachable on
    Linux, where paths are arbitrary bytes; decoding at the call site would raise
    a bare UnicodeDecodeError that the CLI's `except IdentityError` never catches,
    escaping as a raw traceback instead of the `{"ok": false, "reason": ...}`
    record the caller contract promises.
    """
    raw = _run_git(args, cwd, extra_env)
    try:
        return raw.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise IdentityError(f"git_output_not_utf8:{args[0]}") from exc


def derive_candidate_identity(repo_root: str | None = None) -> str:
    """Return the candidate identity — the git tree object ID of working-tree content.

    `repo_root` defaults to the current working directory; git resolves the actual
    repository (including a linked worktree) from there. Raises IdentityError on
    any failure mode, yielding no value.
    """
    cwd = repo_root or os.getcwd()
    # Resolve the real git dir (worktree-aware) so the current index can be seeded.
    git_dir = _run_git_text(["rev-parse", "--absolute-git-dir"], cwd)
    index_path = os.path.join(git_dir, "index")

    try:
        tmp_fd, tmp_index = tempfile.mkstemp(prefix=".reception-index-")
        os.close(tmp_fd)
    except OSError as exc:
        # The temporary index path is unwritable (e.g. a read-only TMPDIR).
        raise IdentityError(f"temp_index_error:{exc.__class__.__name__}") from exc

    try:
        if os.path.exists(index_path):
            # Seed from the current index so skip-worktree (sparse) entries survive.
            shutil.copyfile(index_path, tmp_index)
            # Backdate the seeded index (issue #1117) so git's racy-index rule forces
            # `git add -A` to re-hash every ordinary tracked entry instead of trusting
            # the copied pre-edit stat data — the module docstring's derivation
            # paragraph carries the full rationale and why this preserves the
            # skip-worktree / assume-unchanged bypass. The one detail that is local to
            # this line: a mtime of 0 would NOT arm the mechanism — git reads a zero
            # index timestamp as "unset" and short-circuits `is_racy_stat`, so 1 second
            # past the epoch is the smallest value that makes every real-mtime (>= 1)
            # entry racy.
            os.utime(tmp_index, (_INDEX_BACKDATE_SECONDS, _INDEX_BACKDATE_SECONDS))
            # Verify the backdate rather than assume it: `os.utime` reports the syscall's
            # success, but the FILESYSTEM decides what it stores, and two stored values
            # disarm the racy rule — each of them silently. A 0 (a coarse-granularity or
            # clamping filesystem truncating the epoch second down) is the "unset" value
            # above. A value LATER than the entries' cached mtimes (a filesystem that
            # accepts the call and keeps the creation time) fails `is_racy_stat`'s
            # comparison from the other side. Either one puts `git add -A` straight back
            # on the stale-stat path and yields the pre-edit blob — the issue #1117
            # collision this backdate exists to prevent, with no error and no breadcrumb.
            # Requiring the exact stored second refuses both directions at once; whole
            # seconds are the granularity git's own stat comparison uses, so sub-second
            # noise a filesystem may add is tolerated. A host that cannot store the value
            # gets a named refusal, never an identity the backdate never protected.
            stored_mtime = int(os.stat(tmp_index).st_mtime)
            if stored_mtime != _INDEX_BACKDATE_SECONDS:
                raise IdentityError(f"index_backdate_ineffective:{stored_mtime}")
        else:
            # Absent index: start from an empty index (git creates the file). No
            # seeded stat data exists, so the racy backdate above is unnecessary.
            os.remove(tmp_index)
        env = {"GIT_INDEX_FILE": tmp_index}
        # -A stages every working-tree content change: edits, deletions, renames,
        # and untracked non-ignored files. Gitignored content is excluded by git.
        _run_git(["add", "-A"], cwd, env)
        tree = _run_git_text(["write-tree"], cwd, env)
    except OSError as exc:
        raise IdentityError(f"temp_index_error:{exc.__class__.__name__}") from exc
    finally:
        try:
            if os.path.exists(tmp_index):
                os.remove(tmp_index)
        except OSError:
            pass

    if not tree:
        raise IdentityError("empty_tree_output")
    return tree
