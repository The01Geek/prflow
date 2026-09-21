#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Deterministic review-and-fix loop setup and PR-head branch-sync.

Reached through `review-dirty-tree.sh loop-setup|branch-sync`, the granted head, so one
invocation replaces the run of one-value loop-entry turns `references/loop-control.md`
costs — the run key, three `config-get.sh` reads each with an inline clamp, the telemetry
flag, the run directory — and the four by-eye Step 0.5 comparand reads. It mirrors the
engine's `review-dirty-tree.sh engine-setup` one-call shape (issue #894).

Subcommands:
    loop-setup   the bash host runs `compose-run-key.sh` and the four `config-get.sh`
                 reads and hands their values and exit codes in; this producer applies
                 the loop's clamps and breadcrumbs, checks the run key with the same
                 component rule `review-engine-io.py` uses, resolves the repository root
                 and slug (the same rule, so both helpers resolve ONE run directory),
                 creates the run directory, persists `loop-setup.json` there, and prints
                 one JSON line. It runs no `gh` command.
    branch-sync  run `git branch --show-current`, `git rev-parse HEAD` and the two
                 `gh pr view` reads, compute `status` (ok/mismatch/unresolved) and print
                 one JSON line with the four comparands. Nothing is persisted; no checkout
                 and no git-state change.

Every result is one JSON object whose `status` is `ok`, `mismatch` or `unresolved`
(branch-sync) or `ok`/`error` (loop-setup); an error raised through `Stop` carries a
`step` in LOOP_STOP_STEPS, and the one pre-main deployment-broken arm below (a failed
sibling import) emits `step` `sibling-import` without `Stop`. Exit codes: 0 ok, 1 error,
2 usage — as for the `engine-*` arms.

The run-id component check, slug rule, repo-root read, git runner, JSON emitter and UTF-8
stream setup are imported from the sibling `review-engine-io.py` (both ship together under
`scripts/`), so the "same rule" the criteria require is single-sourced, not copied.
"""

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

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
except (OSError, ImportError, AttributeError) as _exc:  # a broken/partial deployment
    sys.stdout.write(json.dumps({
        'status': 'error', 'step': 'sibling-import',
        'reason': f'review-loop-io.py could not load its sibling review-engine-io.py: {_exc}',
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
# loop-setup never emits `arguments` (that step is branch-sync's alone — AC7). `sibling-import`
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
        '.prflow_review_and_fix.fix_severity_threshold', 'important',
        ('critical', 'important', 'suggestion'))
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
    if not (ref_ok and oid_ok):
        status = 'unresolved'
    elif head_ref == branch and head_oid == head:
        status = 'ok'
    else:
        status = 'mismatch'
    _emit({'status': status, 'head_ref': head_ref, 'head_oid': head_oid,
           'branch': branch, 'head': head})
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
    return parser


def main(argv=None):
    _force_utf8_streams()
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
        # missing git binary in _repo_root). Attribute it to `repo-root`, valid for both
        # subcommands — never `run-dir`, which is loop-setup-only and wrong on branch-sync (AC7).
        _emit({'status': 'error', 'step': 'repo-root', 'reason': str(exc)})
        return 1


if __name__ == '__main__':
    sys.exit(main())
