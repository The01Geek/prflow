#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Deterministic review-and-fix loop helpers: setup, PR-head branch-sync, and the engine entry's
close half and prior-iteration inputs.

Reached through `review-dirty-tree.sh loop-setup|branch-sync|entry-close|entry-open`, the granted
head, so one invocation replaces the run of one-value loop-entry turns
`references/loop-control.md` costs — the run key, three `config-get.sh` reads each with an inline
clamp, the telemetry flag, the run directory — and the four by-eye Step 0.5 comparand reads. It
mirrors the engine's `review-dirty-tree.sh engine-setup` one-call shape (issue #894).

Subcommands:
    loop-setup   the bash host runs `compose-run-key.sh` and the four `config-get.sh`
                 reads and hands their values and exit codes in; this producer applies
                 the loop's clamps and breadcrumbs, checks the run key with the same
                 component rule `review-engine-io.py` uses, resolves the repository root
                 and slug (the same rule, so both helpers resolve ONE run directory),
                 creates the run directory, persists `loop-setup.json` there, and prints
                 one JSON line. It runs no `gh` command.
    branch-sync  run `git branch --show-current`, `git rev-parse HEAD` and the two
                 `gh pr view` reads, compute `status` (ok/mismatch/unresolved; `ok` when the
                 branch names match and the PR head commit is HEAD or an ancestor of it) and print
                 one JSON line with the four comparands; a `mismatch` adds `reason`
                 (`head-unestablished: <git failure>`, `branch-unestablished: <git failure>`,
                 `detached`, `branch-differs` (names differ), `not-ancestor`, or
                 `ancestry-unestablished: <git failure>`, the PR head commit absent locally
                 included; `<git failure>` is `exit <code>: <first stderr line>`). Nothing is persisted; no checkout
                 and no git-state change.
    shadow-open  `--run-root DIR`, remove the sibling shadow directory before entry-open's cleanup;
                 success is silent, failure emits status error naming the path.
    entry-close  `--contract 3 --run-root DIR --entry step1|shadow --iteration N --branch B`,
                 reached through `review-dirty-tree.sh entry-close`: the fix loop's
                 after-return half of one engine entry. Branch guard first
                 (`git rev-parse --abbrev-ref HEAD` vs B: `branch-mismatch` /
                 `branch-unestablished`, nothing else runs). Tree restoration excludes
                 paths under `.prflow/tmp/`. With a usable content record (`entry-open`'s
                 working-tree and index trees) it returns every other tracked path whose
                 index entry or working-tree content changed since then to that state,
                 deleting no file. Without a usable status snapshot it takes a staged new file
                 missing from disk (`AD`, `RD`) as holding its staged content. It cannot see a moved
                 submodule checkout, an edit to an assume-unchanged or skip-worktree file, or
                 one that a clean filter or line-ending conversion normalizes away. Without
                 a usable content record, `dirty_detail` says so and the status snapshot
                 alone decides: each tracked path that became dirty since it is reset to
                 HEAD, one the index added only unstaged; a path the snapshot already lists
                 is reset only when it went from untracked to staged, one whose status
                 changed otherwise named in `dirty_detail`. Either way it lists in `dirtied`
                 each untracked path `git status` then shows that the snapshot did not
                 (every one when the snapshot cannot be used) and in `restored` each path it
                 reset that is not at or under a `dirtied` path.
                 Before the first reset, `dirty_detail` names a recovery save of the content
                 about to be overwritten, or says it is unavailable. `dirty_check` is
                 `unestablished` when a reset may not hold: `git status` or the content
                 compare failed, a path still differs after its reset, or (status snapshot
                 alone) the snapshot or its object ID cannot be read or verified while some
                 tracked file differs from HEAD (with none, it is `ok` and `dirty_detail`
                 names the cause). A shadow entry then migrates its sibling write directory
                 into the run root, replacing files and merging directories without rewriting
                 bytes, except that its source views replace the run root's whole; an absent
                 sibling is a no-op. A failed migration emits status error with the
                 restoration fields, so an unestablished reset still stops the loop.
                 It retains the entry's evidence (`_retain` names where)
                 and relays
                 `loop-verdict-marker.py check-evidence --contract 2 --iteration N` over
                 `evidence-<entry>/iter-N/` as `evidence: {token, exit, line}`.
                 `engine_return` grades the entry's `engine-return-<entry>-iter-N.json`:
                 `ok`, `unavailable`, `missing` or `malformed`, each but `ok` with a `reason`;
                 a shadow entry's `ok` adds `coverage` (`full` only when engine-setup.json
                 holds both gating flags as booleans, every always-on, flag-selected and
                 expected reviewer was dispatched, and no agent failed, inside the roster or
                 out). On the shadow a non-string
                 `phase3_failed_agents` element is a failed reviewer, not a malformed return.
    prior        `--run-root DIR --iteration N`, run by `entry-open` for a step1 entry at
                 N >= 2: iter-<N-1>.json's `diff_produced_at_head` and
                 `prior-findings-iter-N.json` (iter-<N-1>'s findings plus each earlier
                 record's unapplied ones, tagged `iter`).

Output is one JSON object whose `status` is `ok`/`mismatch`/`unresolved` (branch-sync), `ok`
(loop-setup) or `ok`/`branch-mismatch`/`branch-unestablished` (entry-close), and `error` when any
subcommand stops; shadow-open prints nothing on success, `prior` prints its record with no `status`
and only its own usage error carries one, and argparse's own usage error or a crash prints none.
An error raised through `Stop` carries a `step` in LOOP_STOP_STEPS, and the one pre-main
deployment-broken arm below (a failed sibling import) emits `step` `sibling-import` without `Stop`. Exit codes: 0 ok, 1 error,
2 usage — as for the `engine-*` arms.

The run-id component check, slug rule, repo-root read, git runner, JSON emitter and UTF-8
stream setup are imported from the sibling `review-engine-io.py` (both ship together under
`scripts/`), so the "same rule" the criteria require is single-sourced, not copied. The severity
words `fix_severity_threshold` accepts are the sibling `verdict_report.py`'s `SEVERITIES`.
"""

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

# The sibling ships as `review-engine-io.py` (hyphens), which no plain `import` can name, so
# load it by path — the same importlib idiom the lints use for their shared modules. Both
# files ship together under `scripts/`; a partial deployment that dropped one fails closed.
_SIBLING = Path(__file__).resolve().parent / 'review-engine-io.py'
try:
    _spec = importlib.util.spec_from_file_location('review_engine_io', _SIBLING)
    _reio = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_reio)
    EngineStop = _reio.Stop
    _emit = _reio._emit
    _force_utf8_streams = _reio._force_utf8_streams
    _git = _reio._git
    _repo_root = _reio._repo_root
    _slug = _reio._slug
    SAFE_COMPONENT_RE = _reio.SAFE_COMPONENT_RE
    # The severity ladder's one home; loading the sibling above put scripts/ on sys.path.
    from verdict_report import SEVERITIES
except Exception as _exc:  # a broken/partial deployment: a sibling missing or raising on import
    sys.stdout.write(json.dumps({
        'status': 'error', 'step': 'sibling-import',
        'reason': 'review-loop-io.py could not load a sibling (review-engine-io.py, '
                  f'verdict_report.py): {_exc}',
    }, separators=(',', ':')) + '\n')
    sys.exit(1)

# The gh binary to shell out to, resolved exactly as workpad.py resolves it: `DEVFLOW_GH`
# when set and non-empty, else bare `gh`; wrapped in the refreshed-token env when the
# sibling imports (optional for a standalone deployment, as in workpad.py).
GH = os.environ.get('DEVFLOW_GH') or 'gh'
try:
    from gh_fresh_env import fresh_gh_env
except ImportError:
    def fresh_gh_env(env=None, os_name=None):
        return env


# The loop's own stop vocabulary. `repo-root` surfaces from the imported engine helpers
# (raised as their EngineStop, same step string); `run-key`/`run-dir` and the `arguments`
# branch-sync stop are this producer's own. `slug` is loop-setup's own arg/slug-resolution
# stop: cmd_loop_setup remaps _slug's engine `arguments`/`slug` EngineStop onto it, so
# loop-setup never emits `arguments` (AC7). `sibling-import`
# is the deployment-broken pre-main arm above, emitted without Stop.
LOOP_STOP_STEPS = frozenset(('arguments', 'repo-root', 'slug', 'run-key', 'run-dir'))
_INT_RE = re.compile(r'^-?[0-9]+$')


class Stop(Exception):
    """A fail-closed stop: `step` names where, `reason` quotes the observed evidence."""

    def __init__(self, step, reason):
        if step not in LOOP_STOP_STEPS:
            raise ValueError(f'unregistered stop step {step!r}')
        super().__init__(reason)
        self.step = step
        self.reason = reason


def _cfg_fallback_warning(value, rc, key, default_shown):
    """The resolver-failure / absent-key preamble the three `_resolve_*` share. Returns the
    fallback warning (rc 2 is a resolver failure; a non-zero rc or empty value is an absent
    key — distinct warnings, AC4), or `None` when a present value should be validated."""
    if rc == 2:
        return f'{key}: config-get.sh resolver failure (rc=2); using default {default_shown}'
    if rc != 0 or value == '':
        return f'{key}: not configured; using default {default_shown}'
    return None


def _resolve_int(value, rc, key, default, floor):
    """(resolved, warning|None). A present non-integer falls back; a value below the floor
    clamps to the floor when the floor is 1 (max_iterations, no upper bound) and falls back to
    the default when the floor is 0 (a negative fix window)."""
    warning = _cfg_fallback_warning(value, rc, key, default)
    if warning is not None:
        return default, warning
    if not _INT_RE.match(value):
        return default, f'{key}: value {value!r} is not an integer; using default {default}'
    n = int(value)
    if n < floor:
        if floor == 1:
            return 1, f'{key}: value {n} is below 1; clamped to 1'
        return default, f'{key}: value {n} is negative; using default {default}'
    return n, None


def _resolve_enum(value, rc, key, default, choices):
    warning = _cfg_fallback_warning(value, rc, key, default)
    if warning is not None:
        return default, warning
    if value in choices:
        return value, None
    return default, (f'{key}: value {value!r} is not one of {"/".join(choices)}; '
                     f'using default {default}')


def _resolve_bool(value, rc, key):
    """`true` exactly when the value is the string `true` (config-get.sh already coerces the
    JSON boolean `true` and the JSON string "true" to the same bash string); `false`
    otherwise (AC4). A resolver failure, an absent key, or an unrecognized value is a
    fallback to `false` with a breadcrumb; a configured `false` is not a fallback."""
    warning = _cfg_fallback_warning(value, rc, key, 'false')
    if warning is not None:
        return False, warning
    if value == 'true':
        return True, None
    if value == 'false':
        return False, None
    return False, f'{key}: value {value!r} is not a boolean true/false; using default false'


def _persist(path, text):
    """Atomic write of the loop-setup record; a write failure is a `run-dir` stop."""
    tmp = path.with_name(path.name + '.tmp')
    try:
        tmp.write_text(text, encoding='utf-8')
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise Stop('run-dir', f'could not write {path}: {exc}') from exc


def cmd_loop_setup(args):
    root = _repo_root()
    run_key = args.run_key  # argparse default '' — never None
    # The composer's stdout is passed through verbatim; validate it here with the same
    # component rule the engine's run-id uses, and attribute a failure to `run-key` with the
    # observed value (AC2) — the composer's own tests keep asserting it emits the value.
    if not SAFE_COMPONENT_RE.match(run_key) or '..' in run_key:
        raise Stop('run-key', f'run key {run_key!r} is empty or not a safe path component')
    # `_slug` attributes a bad `--pr`/`--slug` to the engine's `arguments` step, but loop-setup's
    # own error vocabulary (AC7) has no `arguments` — an argument-shaped slug failure surfaces as
    # `slug`. Remap so loop-setup never emits a step outside its declared set.
    try:
        slug = _slug(args, root)
    except EngineStop as exc:
        raise Stop('slug', exc.reason) from exc
    run_dir = root / '.prflow' / 'tmp' / 'review' / slug / run_key
    warnings = []
    max_iterations, w = _resolve_int(
        args.cfg_max_iterations, args.cfg_max_iterations_rc,
        '.prflow_review_and_fix.max_iterations', 5, 1)
    if w:
        warnings.append(w)
    fix_severity_threshold, w = _resolve_enum(
        args.cfg_fix_severity_threshold, args.cfg_fix_severity_threshold_rc,
        '.prflow_review_and_fix.fix_severity_threshold', 'important', SEVERITIES)
    if w:
        warnings.append(w)
    fix_below_threshold_iterations, w = _resolve_int(
        args.cfg_fix_below_threshold_iterations, args.cfg_fix_below_threshold_iterations_rc,
        '.prflow_review_and_fix.fix_below_threshold_iterations', 1, 0)
    if w:
        warnings.append(w)
    efficiency_telemetry_enabled, w = _resolve_bool(
        args.cfg_efficiency_telemetry_enabled, args.cfg_efficiency_telemetry_enabled_rc,
        '.prflow_review_and_fix.efficiency_telemetry_enabled')
    if w:
        warnings.append(w)
    rel = run_dir.relative_to(root).as_posix()
    result = {
        'status': 'ok', 'run_id': run_key, 'slug': slug, 'run_dir': rel,
        'max_iterations': max_iterations,
        'fix_severity_threshold': fix_severity_threshold,
        'fix_below_threshold_iterations': fix_below_threshold_iterations,
        'efficiency_telemetry_enabled': efficiency_telemetry_enabled,
        'warnings': warnings,
    }
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise Stop('run-dir', f'could not create run directory {rel}: {exc}') from exc
    _persist(run_dir / 'loop-setup.json', json.dumps(result) + '\n')
    _emit(result)
    return 0


def _gh_read(pr, json_field, jq_expr, root):
    """(observed, resolved). `resolved` is False on a non-zero exit, an empty read, or a
    literal `null`; the observed comparand is recorded as `""` on every such arm (AC6)."""
    try:
        proc = subprocess.run(
            [GH, 'pr', 'view', pr, '--json', json_field, '--jq', jq_expr],
            cwd=root, capture_output=True, text=True, encoding='utf-8', check=False,
            stdin=subprocess.DEVNULL,
            env=fresh_gh_env({**os.environ, 'GIT_TERMINAL_PROMPT': '0'}))
    except OSError:
        return '', False
    out = (proc.stdout or '').strip()
    if proc.returncode != 0 or out == '' or out == 'null':
        return '', False
    return out, True


def cmd_branch_sync(args):
    root = _repo_root()
    pr = args.pr  # argparse default '' — never None
    if not pr:
        raise Stop('arguments', '--pr is required (the PR number to check the head against)')
    if not pr.isdigit():
        raise Stop('arguments', f'--pr {pr!r} is not numeric')
    bproc = _git(['branch', '--show-current'], root)
    branch = bproc.stdout.decode('utf-8', 'replace').strip() if bproc.returncode == 0 else ''
    hproc = _git(['rev-parse', 'HEAD'], root)
    head = hproc.stdout.decode('utf-8', 'replace').strip() if hproc.returncode == 0 else ''
    head_ref, ref_ok = _gh_read(pr, 'headRefName', '.headRefName', root)
    head_oid, oid_ok = _gh_read(pr, 'headRefOid', '.headRefOid', root)
    reason = None
    if not (ref_ok and oid_ok):
        status = 'unresolved'
    elif hproc.returncode != 0 or not head:
        status, reason = 'mismatch', 'head-unestablished: ' + _git_failure(hproc)
    elif bproc.returncode != 0:
        status, reason = 'mismatch', 'branch-unestablished: ' + _git_failure(bproc)
    elif not branch:
        status, reason = 'mismatch', 'detached'
    elif head_ref != branch:
        status, reason = 'mismatch', 'branch-differs'
    else:
        aproc = _git(['merge-base', '--is-ancestor', head_oid, head], root)
        if aproc.returncode == 0:
            status = 'ok'
        elif aproc.returncode == 1:
            status, reason = 'mismatch', 'not-ancestor'
        else:
            status, reason = 'mismatch', 'ancestry-unestablished: ' + _git_failure(aproc)
    result = {'status': status, 'head_ref': head_ref, 'head_oid': head_oid,
              'branch': branch, 'head': head}
    if reason:
        result['reason'] = reason
    _emit(result)
    return 0


# The entry bracket's grade runs the sibling marker script; the LOOP_VERDICT_MARKER env seam is
# retained INTERNALLY so the suite can point it at a stub; the emitted skill command never names it.
_MARKER = os.environ.get('LOOP_VERDICT_MARKER') or str(
    Path(__file__).resolve().parent / 'loop-verdict-marker.py')
_ENTRY_TAGS = {'step1': 's1', 'shadow': 'shadow'}


def _porcelain_records(raw):
    """Split `git status --porcelain -z` bytes into (status, path, orig) triples; a rename or
    copy (R/C in either column) carries its original path as the next NUL record. Paths decode
    losslessly (`surrogateescape`), so two non-UTF-8 names never collapse into one."""
    parts = raw.split(b'\0')
    if parts and parts[-1] == b'':
        parts.pop()
    out, i = [], 0
    while i < len(parts):
        rec = parts[i].decode('utf-8', 'surrogateescape')
        i += 1
        if len(rec) < 4:
            raise ValueError(f'unparseable status record {rec!r}')
        orig = None
        if rec[0] in 'RC' or rec[1] in 'RC':
            if i >= len(parts):
                raise ValueError(f'rename record {rec!r} has no original path')
            orig = parts[i].decode('utf-8', 'surrogateescape')
            i += 1
        out.append((rec[:2], rec[3:], orig))
    return out


def _scratch(path):
    return path == '.prflow/tmp' or path.startswith('.prflow/tmp/')


def _shown(text):
    """A losslessly decoded path made printable: an undecodable byte becomes U+FFFD."""
    return text.encode('utf-8', 'surrogateescape').decode('utf-8', 'replace')


def _by_path(recs):
    """{path: sorted statuses}, a rename's original path under its record's status;
    `.prflow/tmp/**` excluded."""
    out = {}
    for status, path, orig in recs:
        for p in (path, orig):
            if p is not None and not _scratch(p):
                out.setdefault(p, []).append(status)
    return {p: sorted(s) for p, s in out.items()}


def _status(root):
    try:
        proc = _git(['status', '--porcelain', '-z'], root)
    except OSError as exc:
        raise ValueError(f'git status could not start: {exc}') from exc
    if proc.returncode != 0:
        raise ValueError('git status failed after the engine returned')
    return _porcelain_records(proc.stdout)


def _engine_records(before_recs, after_recs):
    """{path: (status, in_head)} for each path the engine changed since the snapshot: absent
    from it, or untracked there and staged now; a rename or copy's original path counts on its
    own. `.prflow/tmp/**` excluded. `in_head` is False for an untracked path and for a path the
    index adds (an `A`, the new side of an `R`/`C` in either column, an intent-to-add). A path
    listed both tracked and untracked (a staged deletion whose file is still on disk) keeps its
    tracked record.
    A rename is reversed in the index (original reset, new name left untracked), deliberately
    unlike `review-dirty-tree.sh` `cmd_compare_and_restore`, which leaves it for a human."""
    before_paths = {p for _, p, o in before_recs} | {o for _, _, o in before_recs if o}
    before_untracked = {p for s, p, _ in before_recs if s == '??'}
    out = {}
    for status, path, orig in after_recs:
        for p, in_head in ((path, status != '??' and status[0] not in 'ARC'
                            and status[1] not in 'ARC'),
                           (orig, True)):
            if p is None or _scratch(p) or (status == '??' and p in out):
                continue
            if p not in before_paths or (status[0] == 'A' and p in before_untracked):
                out[p] = (status, in_head)
    return out


class _Restored(NamedTuple):
    check: str      # `unestablished` when a reset may not hold
    detail: str
    restored: list  # the paths reset
    dirtied: list   # untracked paths the fix commit must not stage


_OID_RE = re.compile(r'[0-9a-f]{40}(?:[0-9a-f]{24})?')


def _git_failure(proc):
    err = proc.stderr.decode('utf-8', 'replace').strip()
    return f'exit {proc.returncode}: ' + (err.splitlines()[0] if err else 'no stderr')


def _content_record(path, root):
    """((working-tree tree, index tree), '') from entry-open's content record, or (None, cause)."""
    shown = path.as_posix()
    try:
        if path.is_symlink():
            return None, f'{shown} is a symlink'
        ids = path.read_bytes().decode('utf-8').split()
    except OSError as exc:
        return None, f'{shown} unreadable ({exc.strerror or exc})'
    except UnicodeDecodeError:
        return None, f'{shown} is not UTF-8'
    if not ids:
        err, said = path.with_name(f'{path.stem}-err.txt'), b''  # entry-open's cause
        try:
            if err.is_file() and not err.is_symlink():
                with err.open('rb') as fh:
                    said = fh.readline(4096)
        except OSError:
            pass
        said = said.decode('utf-8', 'replace').strip()
        return None, f'{shown} is empty (entry-open recorded no content{": " + said if said else ""})'
    if len(ids) != 2 or not all(_OID_RE.fullmatch(i) for i in ids):
        return None, f'{shown} does not hold two object IDs'
    for oid in ids:
        try:
            proc = _git(['cat-file', '-t', oid], root)
        except OSError as exc:
            return None, f'git could not start: {exc}'
        if proc.returncode != 0:
            return None, f'{shown} names {oid}, which git cannot read as an object ({_git_failure(proc)})'
        if proc.stdout.strip() != b'tree':
            return None, f'{shown} names {oid}, not a tree object'
    return (ids[0], ids[1]), ''


def _differing(trees, root):
    """(working-tree paths, index paths) differing from the recorded trees, `.prflow/tmp/**`
    excluded. Porcelain `git diff`: plumbing `diff-index` lists every path whose file differs
    from its index entry, a stat change alone included, so an untouched file dirty at entry-open
    would read as changed. A submodule's checkout is ignored in the working-tree compare — a
    reset cannot move it — while the index compare sees a staged gitlink whatever the repo's
    submodule ignore settings. A working-tree path neither the index tree nor the index holds
    (one `git rm --cached` left on disk) is untracked content, never compared."""
    def names(argv):
        try:
            proc = _git(argv, root)
        except OSError as exc:
            raise ValueError(f'git {argv[0]} could not start: {exc}') from exc
        if proc.returncode != 0:
            raise ValueError(f'git {argv[0]} for the content compare failed ({_git_failure(proc)})')
        return {p for p in (raw.decode('utf-8', 'surrogateescape')
                            for raw in proc.stdout.split(b'\0') if raw) if not _scratch(p)}
    diff = ['diff', '--name-only', '-z', '--no-renames', '--no-ext-diff', '--no-color']
    wt = names([*diff, '--ignore-submodules=all', trees[0]])
    idx = names([*diff, '--cached', '--ignore-submodules=none', trees[1]])
    loose = wt - idx
    if loose:
        wt -= loose - names(['ls-files', '-z'])
    return wt, idx


def _save(root):
    """`git stash create` of the content about to be overwritten (HEAD when it prints nothing),
    as the `dirty_detail` clause naming it or saying it is unavailable."""
    step = 'git stash create'
    try:
        proc = _git(['stash', 'create'], root)
        oid = proc.stdout.decode('utf-8', 'replace').strip()
        if proc.returncode == 0 and not oid:
            step = 'git rev-parse HEAD'
            proc = _git(['rev-parse', '--verify', '-q', 'HEAD'], root)
            oid = proc.stdout.decode('utf-8', 'replace').strip()
    except OSError as exc:
        return f'recovery save unavailable (git could not start: {exc})'
    if proc.returncode != 0 or not _OID_RE.fullmatch(oid):
        return f'recovery save unavailable ({step}, {_git_failure(proc)})'
    return f'recovery save: {oid}'


def _dirtied(before_recs, recs):
    """Untracked paths the fix commit must not stage: those new since the snapshot, or every one
    when the snapshot cannot be used."""
    if before_recs is None:
        return sorted({p for s, p, _ in recs if s == '??' and not _scratch(p)})
    return sorted(p for p, (s, _) in _engine_records(before_recs, recs).items() if s == '??')


def _restore_content(trees, before_recs, problem, root):
    """Returns each tracked path differing from the content record to it: the working-tree
    copy from the working-tree tree (skipped when that tree lacks the path, so no file is
    deleted), then the index entry from the index tree. A differing file that was missing from
    disk at entry-open (the snapshot shows it deleted, or the working-tree tree lacks it and HEAD
    holds it) is never checked out and is stuck while on disk; only the snapshot shows a staged
    new one (`AD`, `RD`), which `git stash create` records with its staged content."""
    detail = [problem] if problem else []
    missing = {p for s, p, _ in before_recs or () if s[1] == 'D' and not _scratch(p)}

    def compare():
        """A missing file differs exactly when it is on disk now; a directory there is a
        submodule checkout, which the working-tree compare ignores."""
        wt, idx = _differing(trees, root)
        back = {p for p in missing if os.path.islink(os.path.join(root, p))
                or os.path.isfile(os.path.join(root, p))}
        return (wt - missing) | back, idx
    try:
        wt, idx = compare()
    except ValueError as exc:
        return _Restored('unestablished', '; '.join([*detail, str(exc)]), [], [])
    changed = sorted(wt | idx)
    why, gone = {}, set()
    if changed:
        detail.append(_save(root))
    for p in changed:
        steps = [('reset', '-q', trees[1])]
        if p in wt:
            try:
                proc = None if p in missing else _git(['cat-file', '-e', f'{trees[0]}:{p}'], root)
                if proc is None or (proc.returncode != 0 and _git(
                        ['cat-file', '-e', f'HEAD:{p}'], root).returncode == 0):
                    gone.add(p)
                    why[p] = 'missing from disk at entry-open and on disk now; file kept'
                elif proc.returncode != 0:
                    why[p] = 'file kept; ' + _git_failure(proc)
            except OSError as exc:
                why[p] = f'git could not start: {exc}'
                continue
            if p not in why:
                steps.insert(0, ('checkout', trees[0]))
        for step in steps:
            try:
                proc = _git(['--literal-pathspecs', *step, '--', p], root)
            except OSError as exc:
                why[p] = f'git could not start: {exc}'
                break
            if proc.returncode != 0:
                why[p] = _git_failure(proc)
                break

    def listed(skip, dirtied):
        dirs = tuple(d for d in dirtied if d.endswith('/'))
        return [p for p in changed if p not in skip and p not in dirtied
                and not f'{p}/'.startswith(dirs)]
    final = None
    try:
        final = _status(root)
        left = set().union(*compare())
    except ValueError as exc:
        dirtied = [] if final is None else _dirtied(before_recs, final)
        return _Restored('unestablished', '; '.join([*detail, str(exc)]), listed(why, dirtied),
                         dirtied)
    dirtied = _dirtied(before_recs, final)
    stuck = sorted(left | {p for p in gone if os.path.lexists(os.path.join(root, p))})
    if stuck:
        detail.append('could not restore: ' + ', '.join(
            f'{p} ({why[p]})' if p in why else p for p in stuck))
    return _Restored('unestablished' if stuck else 'ok', '; '.join(detail),
                     listed(stuck, dirtied), dirtied)


def _restore(tag, iteration, root):
    """Restores each tracked path the engine changed since entry-open: through the content
    record when it is usable (`_restore_content`), else from the status snapshot alone — each
    path `_engine_records` finds reset to HEAD (overwriting what the engine left there, an
    untracked file at a staged deletion's or rename's original path included), a path the index
    added unstaged, its file kept. A path absent from HEAD is never deleted."""
    base = Path('.prflow/tmp/review') / f'dt-{tag}-{iteration}'
    oid_file, before = Path(f'{base}-oid.txt'), Path(f'{base}-before')
    try:
        after_recs = _status(root)
    except ValueError as exc:
        return _Restored('unestablished', str(exc), [], [])
    before_recs, problem = None, None
    try:
        if oid_file.is_symlink() or before.is_symlink():
            problem = 'the snapshot or its object ID file is a symlink'
        else:
            oid = oid_file.read_text(encoding='utf-8').strip()
            if not oid:
                problem = f'{oid_file.as_posix()} is empty (entry-open took no snapshot)'
            else:
                raw_before = before.read_bytes()
                try:
                    proc = _git(['hash-object', '--', str(before)], root)
                except OSError as exc:
                    problem = f'git could not start for git hash-object ({exc})'
                else:
                    if proc.returncode != 0:
                        problem = ('git hash-object on the before snapshot failed '
                                   f'({_git_failure(proc)})')
                    elif proc.stdout.decode('utf-8', 'replace').strip() != oid:
                        problem = 'the before snapshot no longer matches its object ID'
                    else:
                        before_recs = _porcelain_records(raw_before)
    except OSError as exc:
        problem = f'entry-open snapshot unreadable ({exc.strerror or exc})'
    except ValueError as exc:
        problem = f'entry-open snapshot malformed ({exc})'
    trees, cause = _content_record(Path(f'{base}-content.txt'), root)
    if trees is not None:
        return _restore_content(trees, before_recs, problem, root)
    unavailable = f'content record unavailable ({cause}); status snapshot alone'
    if problem is not None:
        # The engine's edits cannot be told from earlier ones; with no tracked file differing
        # from HEAD there is none to leak, otherwise one may remain.
        tracked = any(s != '??' and not _scratch(p) for s, p, _ in after_recs)
        return _Restored('unestablished' if tracked else 'ok', f'{unavailable}; {problem}', [],
                         _dirtied(None, after_recs))
    changed = _engine_records(before_recs, after_recs)
    why = {}
    detail = [unavailable]
    if any(s != '??' for s, _ in changed.values()):
        detail.append(_save(root))
    for p, (status, in_head) in sorted(changed.items()):
        if status == '??':
            continue
        try:
            proc = _git(['--literal-pathspecs', *(('checkout', 'HEAD') if in_head else
                                                  ('rm', '--cached', '-f', '-q')), '--', p], root)
        except OSError as exc:
            why[p] = f'git could not start: {exc}'
            continue
        if proc.returncode != 0:
            why[p] = _git_failure(proc)
    try:
        final = _status(root)
    except ValueError as exc:
        return _Restored('unestablished', '; '.join([*detail, str(exc)]), sorted(
            p for p, (s, _) in changed.items() if s != '??' and p not in why), [])
    left = _engine_records(before_recs, final)
    stuck = sorted(p for p, (s, _) in left.items() if s != '??')
    dirtied = sorted(p for p, (s, _) in left.items() if s == '??')
    dirs = tuple(d for d in dirtied if d.endswith('/'))
    restored = sorted(p for p, (s, _) in changed.items() if s != '??' and p not in stuck
                      and p not in dirtied and not f'{p}/'.startswith(dirs))
    was, now = _by_path(before_recs), _by_path(final)
    touched = sorted(p for p in was if was[p] != now.get(p) and p not in left)
    if stuck:
        detail.append('could not reset to HEAD: ' + ', '.join(
            f'{p} ({why[p]})' if p in why else p for p in stuck))
    if touched:
        detail.append(f'already-dirty path changed, not reset: {", ".join(touched)}')
    return _Restored('unestablished' if stuck else 'ok', '; '.join(detail), restored, dirtied)


def _remove(path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


_SOURCE_VIEWS = ('view-head', 'view-base')


def _run_dir_stop(what, shown, exc, partial=False):
    """A `run-dir` Stop naming `shown`, the plain path: never the `_fs_path` form an
    OSError's own text would carry. `partial` says the run root may already be changed."""
    return Stop('run-dir', f'could not {what} {_shown(str(shown))}: '
                           f'{exc.strerror or str(exc) or type(exc).__name__}'
                           + ('; the run root may hold a partial migration' if partial else ''))


def cmd_shadow_open(args):
    """Remove only the sibling shadow write directory; success prints nothing."""
    plain = Path(str(Path(args.run_root)) + '-shadow')
    try:
        _remove(_reio._fs_path(plain))
    except OSError as exc:
        raise _run_dir_stop('remove shadow directory', plain, exc) from exc
    return 0


def _merge_shadow(src, dst, shown, partial=True):
    """Move `src` onto `dst`, merging directories without deleting unrelated destination
    children; `shown` is `src`'s plain path, `partial` whether a failure may leave `dst` changed."""
    try:
        if src.is_dir() and not src.is_symlink():
            dst.mkdir(exist_ok=True)
            for child in src.iterdir():
                _merge_shadow(child, dst / child.name, shown / child.name)
                partial = True
            src.rmdir()
        else:
            os.replace(src, dst)
    except OSError as exc:
        raise _run_dir_stop('migrate shadow path', shown, exc, partial) from exc


def _migrate_shadow(run_root):
    """Merge `<run_root>-shadow` into `run_root` and remove it; absent, a no-op. A source
    view the shadow wrote first removes the run root's: views are whole-commit snapshots."""
    plain = Path(str(run_root) + '-shadow')
    shown, partial = plain, False
    try:
        shadow, root = _reio._fs_path(plain), _reio._fs_path(run_root)
        if not (shadow.exists() or shadow.is_symlink()):
            return
        # A linked sibling cannot be moved onto the run root, so it removes no view first.
        for name in () if shadow.is_symlink() else _SOURCE_VIEWS:
            shown = plain / name
            if (shadow / name).is_dir() and not (shadow / name).is_symlink():
                shown, partial = run_root / name, True
                _remove(root / name)
    except OSError as exc:
        raise _run_dir_stop('migrate shadow path', shown, exc, partial) from exc
    _merge_shadow(shadow, root, plain, partial)


def _replace(src, dst):
    """Make `dst` a copy of file or directory `src`, or remove it when `src` is absent."""
    _remove(dst)
    if src.is_dir():
        shutil.copytree(src, dst)
    elif src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)


def _retain(run_root, entry, n):
    """Copy the entry's evidence where a later entry's deletions cannot reach it: the pair to
    the entry-scoped names Phase 1.0's carry and the shadow's `checklist match` read, and into
    `evidence-<entry>/iter-<n>/`, the root the grade reads, the pair, verifier files, item files
    (a spent delivery's record), phase log and diff plus every earlier iteration's own retained
    verifier files, which a reused item points back to. A source the entry did not write leaves no copy. Returns the first error,
    or ''."""
    base = run_root / f'evidence-{entry}'
    ev = base / f'iter-{n}'
    pair = (f'checklist-iter-{n}.json', f'verification-iter-{n}.json')
    try:
        for name in pair:
            _replace(run_root / name, run_root / name.replace('-iter-', f'-{entry}-iter-'))
        _remove(ev)
        for name in (*pair, 'diff.patch', 'phase-log', f'verdicts/iter-{n}', f'checklist-iter-{n}.items'):
            _replace(run_root / name, ev / name)
        for k in range(1, n):
            own = base / f'iter-{k}' / 'verdicts' / f'iter-{k}'
            if own.is_dir():
                _replace(own, ev / 'verdicts' / f'iter-{k}')
    except OSError as exc:
        return f'could not retain the evidence: {exc}'
    return ''


def _grade(run_root, iteration):
    try:
        proc = subprocess.run(
            [sys.executable, _MARKER, 'check-evidence', '--contract', '2',
             '--run-root', run_root.as_posix(), '--iteration', str(iteration)],
            capture_output=True, text=True, encoding='utf-8', errors='replace', check=False,
            stdin=subprocess.DEVNULL)
    except OSError as exc:
        return {'token': '', 'exit': 127, 'line': f'check-evidence could not start: {exc}'}
    line = ((proc.stdout or '').splitlines() or [''])[0]
    token = line.split(' ', 1)[0] if line.strip() else ''
    if not line.strip():
        line = ((proc.stderr or '').strip().splitlines() or [''])[-1]
    return {'token': token, 'exit': proc.returncode, 'line': line}


def _usage(step, reason):
    """entry-close's usage refusal: one error line, exit 2 (the caller's can't-serve arm)."""
    _emit({'status': 'error', 'step': step, 'reason': reason})
    return 2


ALWAYS_ON = ('prflow:code-reviewer', 'prflow:silent-failure-hunter', 'prflow:comment-analyzer',
             'prflow:requesting-code-review')
# Phase 3.1's flag-selected reviewers: (engine-setup.json `flags` key, agent).
GATED = (('has_new_types', 'prflow:type-design-analyzer'), ('test_relevant', 'prflow:pr-test-analyzer'))
HEX40_RE = re.compile(r'\A[0-9a-fA-F]{40}\Z')
_PRIOR_KEYS = ('agent', 'severity', 'description', 'defect_signature', 'fix_decision')


def _json_object(path):
    """(dict, None) or (None, why) for a JSON object file."""
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None, 'missing'
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as exc:
        return None, f'unreadable ({type(exc).__name__})'
    if not isinstance(value, dict):
        return None, f'a JSON {type(value).__name__}, not an object'
    return value, None


def _strings(value):
    """(strings, count of other elements) of a list field; (None, 0) when not a list."""
    if not isinstance(value, list):
        return None, 0
    strings = [v for v in value if isinstance(v, str)]
    return strings, len(value) - len(strings)


def _unknown_key_warnings(record, name):
    """One warning per top-level key of `record` outside the iteration-record schema's
    properties, from loop-verdict-marker.py's _unknown_top_keys; a sibling that cannot load or
    check is one warning,
    because these readers warn rather than refuse."""
    step = 'load'
    try:
        spec = importlib.util.spec_from_file_location(
            'review_loop_io_lvm', Path(__file__).resolve().parent / 'loop-verdict-marker.py')
        lvm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lvm)
        unknown_top_keys = lvm._unknown_top_keys
        step = 'check'
        unknown, why = unknown_top_keys(record)
    except (Exception, SystemExit) as exc:
        unknown, why = [], (f'loop-verdict-marker.py could not {step} ({type(exc).__name__}: {exc}); '
                            'unknown top-level keys not checked')
    if why:
        return [f'{name}: {why}']
    return [f'{name} top-level key {key} is outside the iteration-record schema' for key in unknown]


def prior_inputs(run_root, iteration):
    """The N≥2 primary entry's carry-forward from the earlier iteration records: iter-<N-1>'s
    reviewed head and the prior-findings file (iter-<N-1>'s every finding plus each earlier
    record's unapplied ones, tagged with their iteration)."""
    warnings, findings = [], []
    prev, why = _json_object(run_root / f'iter-{iteration - 1}.json')
    if prev is None:
        warnings.append(f'iter-{iteration - 1}.json {why}; nothing carried from it')
    else:
        warnings += _unknown_key_warnings(prev, f'iter-{iteration - 1}.json')
    for k in range(1, iteration):
        rec, rec_why = (prev, why) if k == iteration - 1 else _json_object(run_root / f'iter-{k}.json')
        if rec is None:
            if k < iteration - 1:
                warnings.append(f'iter-{k}.json {rec_why}; not carried')
            continue
        rows = rec.get('phase3_findings')
        if not isinstance(rows, list):
            warnings.append(f'iter-{k}.json phase3_findings is not an array; not carried')
            continue
        if not all(isinstance(row, dict) for row in rows):
            warnings.append(f'iter-{k}.json phase3_findings holds rows that are not objects; '
                            'those rows are not carried')
        for row in rows:
            if not isinstance(row, dict) or (k < iteration - 1 and row.get('fix_decision') == 'applied'):
                continue
            item = {key: row[key] for key in _PRIOR_KEYS if key in row}
            if k < iteration - 1:
                item['iter'] = k
            findings.append(item)
    head = prev.get('diff_produced_at_head') if prev else None
    # A promoted iteration runs no Step 1, so its record carries no reviewed head.
    promoted = prev is not None and prev.get('loop_role') == 'promoted' and head is None
    if prev is not None and not promoted and not (isinstance(head, str) and HEX40_RE.match(head)):
        warnings.append(f'iter-{iteration - 1}.json diff_produced_at_head {head!r} is not a 40-hex '
                        'commit; no reviewed head carried')
        head = None
    path = None
    if findings:
        out = run_root / f'prior-findings-iter-{iteration}.json'
        try:
            _persist(out, json.dumps(findings, indent=1, ensure_ascii=False) + '\n')
            path = out.as_posix()
        except Stop as stop:
            warnings.append(f'prior findings not written: {stop.reason}')
    return {'diff_head': head, 'findings': path,
            'count': len(findings), 'warnings': warnings}


def cmd_prior(args):
    if not re.fullmatch(r'[1-9][0-9]*', args.iteration) or not Path(args.run_root).is_dir():
        return _usage('arguments', '--run-root must be a directory and --iteration a positive integer')
    n = int(args.iteration)
    _emit(prior_inputs(Path(args.run_root), n) if n >= 2 else
          {'diff_head': None, 'findings': None, 'count': 0, 'warnings': []})
    return 0


def _engine_return(run_root, entry, n, tag):
    """The engine return's usability: status ok | unavailable | missing | malformed, with a
    reason; on a shadow entry also its reviewer coverage."""
    ret, why = _json_object(run_root / f'engine-return-{entry}-iter-{n}.json')
    if ret is None:
        return {'status': 'missing' if why == 'missing' else 'malformed', 'reason': why}
    mode = ret.get('dispatch_mode')
    if mode == 'unavailable':
        return {'status': 'unavailable', 'reason': 'the engine held no delegation tool',
                'tools_held': ret.get('tools_held')}
    problems = []
    if mode != 'fanned-out':
        problems.append(f'dispatch_mode {mode!r}')
    if ret.get('root_completeness') != 'established':
        problems.append('root_completeness not established')
    problems += _reio.return_shape_problems(ret, entry)
    head_file = f'.prflow/tmp/review/dt-{tag}-{n}-head.txt'
    try:
        opened = Path(head_file).read_text(encoding='utf-8').strip()
        opened_why = f'{opened!r} is not a 40-hex commit'
    except (OSError, UnicodeDecodeError) as exc:
        opened, opened_why = '', type(exc).__name__
    head = ret.get('diff_produced_at_head')
    if not HEX40_RE.match(opened):
        problems.append(f'the HEAD entry-open recorded is unreadable ({head_file}: {opened_why})')
    else:
        if not (isinstance(head, str) and head.lower() == opened.lower()):
            problems.append(f'diff_produced_at_head {head!r} is not the HEAD at entry-open ({opened})')
        proc = _git(['rev-parse', 'HEAD'], os.getcwd())
        now = proc.stdout.decode('utf-8', 'replace').strip() if proc.returncode == 0 else ''
        if now.lower() != opened.lower():
            problems.append(f'HEAD moved during the entry ({opened} -> {now or "unreadable"})')
    if problems:
        return {'status': 'malformed', 'reason': '; '.join(problems)}
    lists, odd = {}, {}
    for key in _reio.RETURN_ROSTERS:
        lists[key], odd[key] = _strings(ret[key])
    dispatched, expected, failed = (set(lists['phase3_dispatched']), lists['expected_reviewers'],
                                    set(lists['phase3_failed_agents']))
    if entry == 'shadow':
        setup, why = _json_object(run_root / 'engine-setup.json')
        flags = setup.get('flags') if setup else None
        flags = flags if isinstance(flags, dict) else {}
        gated = [a for flag, a in GATED if flags.get(flag) is True]
        unknown = [flag for flag, _ in GATED if not isinstance(flags.get(flag), bool)]
        roster = list(dict.fromkeys([*ALWAYS_ON, *gated, *expected]))
        rows = [{'agent': a, 'returned': a in dispatched and a not in failed} for a in roster]
        short = [a for a in roster if a not in dispatched]
        bad = [r['agent'] for r in rows if not r['returned'] and r['agent'] in dispatched]
        outside = sorted(failed - set(roster))
        unnamed = odd['phase3_failed_agents']
        reason = '; '.join(filter(None, [
            f"engine-setup.json {why or 'flags'} leave(s) {', '.join(unknown)} unestablished"
            if unknown else '',
            f"not dispatched: {', '.join(short)}" if short else '',
            f"returned nothing usable: {', '.join(bad)}" if bad else '',
            f"failed outside the roster: {', '.join(outside)}" if outside else '',
            f'{unnamed} failed agent(s) recorded in a non-string form' if unnamed else '']))
        return {'status': 'ok', 'coverage': {
            'status': 'not_verified' if reason else 'full', 'reason': reason or None,
            'expected_reviewers': roster, 'reviewers_dispatched': sorted(dispatched),
            'per_reviewer_assessment': rows}}
    if not expected:
        eligible = lists['plan_eligible']
        excluded = {x.get('agent') for x in ret['plan_exclusions'] if isinstance(x, dict)
                    and 'first-only' in str(x.get('reason', ''))}
        if n < 2 or not eligible or any(a not in excluded for a in eligible):
            return {'status': 'malformed', 'reason': 'expected_reviewers is empty and no first-only '
                    'plan exclusion accounts for every eligible reviewer'}
    missing = [a for a in expected if a not in dispatched]
    if n == 1:
        missing += [a for a in ALWAYS_ON if a not in expected]
    if missing:
        return {'status': 'malformed', 'reason': f"under-fanned roster: {', '.join(missing)}"}
    return {'status': 'ok'}


def cmd_entry_close(args):
    if args.contract != '3':
        return _usage('arguments', '--contract 3 is required (this helper retired the earlier '
                      'entry-close contracts)')
    for name in ('run_root', 'entry', 'iteration', 'branch'):
        value = getattr(args, name)
        if not value:
            return _usage('arguments', f'--{name.replace("_", "-")} is required')
        if '<' in value or '>' in value:
            return _usage('arguments', 'an operand carries an unsubstituted <placeholder>')
    if args.entry not in _ENTRY_TAGS:
        return _usage('arguments', f'--entry must be step1 or shadow (got {args.entry!r})')
    if not re.fullmatch(r'[1-9][0-9]*', args.iteration):
        return _usage('arguments', f'--iteration must be a positive integer (got {args.iteration!r})')
    run_root = Path(args.run_root)
    if not run_root.is_dir():
        return _usage('run-root', f'run root {args.run_root!r} is not a directory')
    n = int(args.iteration)
    cwd = os.getcwd()
    proc = _git(['rev-parse', '--abbrev-ref', 'HEAD'], cwd)
    branch = proc.stdout.decode('utf-8', 'replace').strip() if proc.returncode == 0 else ''
    if not branch:
        _emit({'status': 'branch-unestablished', 'expected': args.branch})
        return 0
    if branch != args.branch:
        _emit({'status': 'branch-mismatch', 'branch': branch, 'expected': args.branch})
        return 0
    reset = _restore(_ENTRY_TAGS[args.entry], n, cwd)
    result = {'status': 'ok', 'entry': args.entry, 'iteration': n, 'branch': branch,
              'dirty_check': reset.check, 'dirty_detail': _shown(reset.detail),
              'restored': [_shown(p) for p in reset.restored],
              'dirtied': [_shown(p) for p in reset.dirtied]}
    if args.entry == 'shadow':
        try:
            _migrate_shadow(run_root)
        except Stop as stop:
            result.update(status='error', step=stop.step, reason=stop.reason)
            _emit(result)
            return 1
    error = _retain(run_root, args.entry, n)
    evidence = ({'token': '', 'exit': 1, 'line': f'entry-close {error}'} if error
                else _grade(run_root / f'evidence-{args.entry}' / f'iter-{n}', n))
    result.update(engine_return=_engine_return(run_root, args.entry, n, _ENTRY_TAGS[args.entry]),
                  evidence=evidence)
    _emit(result)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog='review-loop-io.py', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    setup = sub.add_parser('loop-setup')
    setup.add_argument('--run-key', default='')
    setup.add_argument('--pr', default='')
    setup.add_argument('--slug', default='')
    setup.add_argument('--cfg-max-iterations', default='')
    setup.add_argument('--cfg-max-iterations-rc', type=int, default=0)
    setup.add_argument('--cfg-fix-severity-threshold', default='')
    setup.add_argument('--cfg-fix-severity-threshold-rc', type=int, default=0)
    setup.add_argument('--cfg-fix-below-threshold-iterations', default='')
    setup.add_argument('--cfg-fix-below-threshold-iterations-rc', type=int, default=0)
    setup.add_argument('--cfg-efficiency-telemetry-enabled', default='')
    setup.add_argument('--cfg-efficiency-telemetry-enabled-rc', type=int, default=0)
    setup.set_defaults(func=cmd_loop_setup)
    sync = sub.add_parser('branch-sync')
    sync.add_argument('--pr', default='')
    sync.set_defaults(func=cmd_branch_sync)
    close = sub.add_parser('entry-close')
    for flag in ('--contract', '--run-root', '--entry', '--iteration', '--branch'):
        close.add_argument(flag, default='')
    close.set_defaults(func=cmd_entry_close)
    shadow_open = sub.add_parser('shadow-open')
    shadow_open.add_argument('--run-root', required=True)
    shadow_open.set_defaults(func=cmd_shadow_open)
    prior = sub.add_parser('prior')
    prior.add_argument('--run-root', default='')
    prior.add_argument('--iteration', default='')
    prior.set_defaults(func=cmd_prior)
    return parser


def main(argv=None):
    _force_utf8_streams()
    try:
        sys.stdout.reconfigure(newline='\n')  # one LF-terminated line on every host
    except (AttributeError, ValueError, OSError):
        pass
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (Stop, EngineStop) as stop:
        # A local Stop is already vocabulary-checked by its constructor. Funnel an imported
        # EngineStop through the same guard so a future engine step outside LOOP_STOP_STEPS
        # fails closed here (a loud ValueError, no JSON — the loop's no-JSON fallback then
        # takes over) rather than emitting an out-of-vocabulary step that would silently break
        # loop-control.md's routing.
        if stop.step not in LOOP_STOP_STEPS:
            raise ValueError(f'stop step {stop.step!r} is outside LOOP_STOP_STEPS') from stop
        _emit({'status': 'error', 'step': stop.step, 'reason': stop.reason})
        return 1
    except OSError as exc:
        # loop-setup's own run-directory writes are already wrapped as Stop('run-dir') above,
        # so an OSError reaching here is git/gh/environment unavailability during a read (e.g. a
        # missing git binary in _repo_root). Attribute it to `repo-root`, valid for every
        # subcommand; wrap filesystem writes at their site as run-dir stops instead.
        _emit({'status': 'error', 'step': 'repo-root', 'reason': str(exc)})
        return 1


if __name__ == '__main__':
    sys.exit(main())
