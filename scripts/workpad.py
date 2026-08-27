#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""PRFlow workpad helper for the /implement skill.

The /implement orchestrator maintains one canonical marker-tagged comment per
GitHub issue (the workpad); concurrent create races remain a documented residual.
Claude Code's Bash tool spawns a fresh shell per
call, so shell functions and env vars don't survive across phase boundaries.
This script gives the orchestrator a stateless CLI that re-derives everything
from arguments + live GitHub state on each call.

All subcommands shell out to `gh` for GitHub API access (same auth path as
the rest of devflow). The workpad marker is read from the repo-root
`.prflow/config.json` directly in-process (issue #275: no `.sh` exec, so it
works on Windows), anchored to the git repo root via a native `git rev-parse`
subprocess (issue #295: falling back to cwd) so a subdirectory invocation still
reads the consumer's root config, falling back to the built-in default
`<!-- prflow:workpad -->` when the config file or key is absent (so it works
with no config).

Usage:
    workpad.py id        ISSUE [--marker M]
    workpad.py acs       ISSUE [--exclude-post-merge] [--neutralize-boxes]
                               [--emit-source-token]
    workpad.py acs-resolve ISSUE [--pr N]
    workpad.py body      COMMENT_ID
    workpad.py patch     COMMENT_ID BODY_FILE
    workpad.py create    ISSUE BODY_FILE
    workpad.py new-body  ISSUE [--run-link V] [--branch V] [--marker M]
    workpad.py now
    workpad.py update    ISSUE [mutations...] [--print-body] [--marker M]
    workpad.py handoff-state FILE --issue N --run-id ID --run-attempt ATTEMPT

Subcommands that locate the workpad by its marker comment (`id`, `new-body`,
`update`) accept `--marker` to target a non-default marker — /devflow:review
uses it to drive its own `<!-- prflow:review-progress -->` comment. The flag
is preferred over the `DEVFLOW_WORKPAD_MARKER` env var: a leading
env-assignment makes the command un-matchable against the cloud allow-list.

`id` exits 2 with empty stdout when it scanned cleanly but no workpad exists
yet (so callers can detect "first run" via `$?`); exit 1 is reserved for a
real gh-api/parse error, so a transient failure is never mistaken for "first
run" (which would post a duplicate comment).

`update` is the high-level mutation entry point used by /implement at every
phase boundary. It re-fetches the workpad body, applies the requested
mutations, auto-updates `Last updated`, and PATCHes the result. A *structural*
failure (missing section/front-matter line) aborts the call before any PATCH; a
*volatile* per-row tick miss (a `--tick-*`/`--tick-*-n` that does not resolve)
is reported and exits non-zero, but the call's other mutations still PATCH.
`update` writes nothing to stdout by default (issue #814) — the exit code is the
success signal, and a short stderr breadcrumb naming the PATCHed comment id (with
the read-back `Status:` value on a `--status` call) distinguishes a successful call
from one a permission matcher silently refused. `--print-body` restores the body
echo; the volatile-tick-miss path echoes it regardless, because the caller must
re-resolve a section-scoped checkbox index against that row inventory.
Notes (`--note`) are append-only and nest under their lifecycle phase inside
the ## Progress section; Devflow Reflection accumulates bullets; checkbox
sections are mutated in place rather than rewritten. See `workpad.py update
--help` for the available mutation flags.
"""

import argparse
import base64
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

if sys.version_info < (3, 11):  # fail fast, before any PEP 604 annotation is evaluated below
    sys.stderr.write(
        "devflow: Python 3.11+ required (found {}.{}.{}). This helper requires"
        " features of Python 3.11+. Install Python 3.11+; on Windows/Git-Bash"
        " run scripts/provision-python3-shim.sh --apply.\n".format(*sys.version_info[:3])
    )
    sys.exit(1)

# State-directory resolution (issue #1002): canonical .prflow/, with the LOUD
# transitional fallback to a superseded .devflow/ when only that one is present.
# lib/ sits beside scripts/ in both the source repo and a vendored
# .prflow/vendor/prflow/ tree, so this import path holds on every tier. A copy
# missing the sibling degrades to the canonical name with no fallback rather than
# failing the read (the same posture the plugin_identity import takes).
try:
    # `__file__` is absent when this module is read and exec'd rather than imported
    # (the #343 gate exercise does exactly that), so the path insert degrades with the
    # import instead of raising ahead of a gate that must fail fast.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
    from state_dir import resolve_state_dir as _resolve_state_dir
except Exception:  # pragma: no cover - partial-copy / exec'd-source arm
    def _resolve_state_dir(repo_root, stream=None):
        return str(Path(repo_root) / ".prflow")

# Shared section/checkbox parsing rules (issue #781) — the SAME implementation
# `scripts/parse-acs.py` uses to WRITE the workpad's `## Acceptance Criteria`
# section, so the read-back here can never disagree with the mirror about what a
# section or a checkbox is. Imported IN-PROCESS, never through a `.sh`/subprocess
# hop — Windows refuses that with [WinError 193] (issue #275).
#
# Two properties of this block are load-bearing, and both were learned the
# expensive way:
#
# 1. It sits BELOW the Python-version gate above. Placed higher it would run
#    before the gate, so a 3.10 host would die on the import instead of printing
#    the gate's floor/remedy message — defeating the fail-fast the gate exists
#    for.
# 2. The import is OPTIONAL. `workpad.py` is deployed as a standalone file in
#    two places that copy it WITHOUT its siblings — the Stop-hook trusted-copy
#    closure, and the suite's own guard sandboxes — and every subcommand those
#    paths use (`status`, `id`, `update`) needs nothing from this module. A hard
#    import would take all of them down with a `ModuleNotFoundError` for a module
#    only `acs` / `acs-resolve` / the scope-decision flags require. So an absent
#    sibling degrades to a targeted failure ON THOSE SURFACES ONLY, via
#    `_require_section_parse()` below, rather than to a dead script.
#
# The explicit `sys.path` entry is likewise not belt-and-braces: running this
# file as a script puts `scripts/` on the path for free, but a consumer that
# loads it through `importlib.util.spec_from_file_location` — how
# `lib/test/test_python_scripts.py` drives every helper in this directory — does
# not.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from section_parse import (
        extract_section,
        is_post_merge_tagged,
        normalize_criterion,
        parse_checkboxes,
        render_line,
    )
    _SECTION_PARSE_IMPORT_ERROR = None
except ImportError as _e:      # standalone deployment — see (2) above
    _SECTION_PARSE_IMPORT_ERROR = str(_e)


def _require_section_parse(cmd: str) -> None:
    """Fail closed, with a specific breadcrumb, on the surfaces that need the
    shared parsing module when it was not deployed beside this file."""
    if _SECTION_PARSE_IMPORT_ERROR is None:
        return
    sys.stderr.write(
        f"workpad.py {cmd}: the shared parsing module scripts/section_parse.py "
        f"could not be imported ({_SECTION_PARSE_IMPORT_ERROR}); it must be "
        f"deployed alongside workpad.py. Refusing rather than guessing at the "
        f"acceptance-criteria section's shape.\n"
    )
    sys.exit(3)


# The gh binary to shell out to. `DEVFLOW_GH` (the documented override the shell
# helpers resolve via lib/resolve-gh.sh) wins when set and non-empty; otherwise
# bare `gh`. Read once at import so every subprocess call uses the same binary.
GH = os.environ.get("DEVFLOW_GH") or "gh"


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8, idempotently and defensively. Called from
    the CLI entry path only (not at import) so importing this module for unit
    tests never mutates the importer's global streams. Windows' default codec is
    cp1252, so the rocket/em-dash this script emits would otherwise raise
    `UnicodeEncodeError`; reconfigure overrides even a hostile `PYTHONIOENCODING`.
    The guard tolerates a stream replaced with a non-`TextIOWrapper` (e.g. a
    test's `io.StringIO`), which has no `reconfigure`."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def _run(cmd, *, stdout=subprocess.PIPE, stdin=None):
    # `encoding="utf-8"` pins both directions of the gh pipe: DECODING gh's
    # output (issue/comment bodies, titles — routinely non-ASCII) and ENCODING
    # any stdin, so neither raises under a non-UTF-8 ambient codec. Implies text
    # mode, so `text=True` is dropped (passing both is redundant/conflicting).
    return subprocess.run(
        cmd, check=True, stdin=stdin, stdout=stdout,
        stderr=subprocess.PIPE, encoding="utf-8",
    )


_UPDATE_REMEDY_BY_OUTCOME = {
    'landed': 'none',
    'replay': 'none',
    'landed-partial-ticks': 'retick-named-rows',
    'landed-status-unverified': 'reset-status',
    'landed-partial-ticks-status-unverified': 'retick-and-reset-status',
    'not-persisted': 'reissue-call',
    'precondition-mismatch': 're-resolve-state',
}


_UPDATE_OUTCOME_EMITTED = False

# Do not key the fallback outcome on the exit code instead of this flag: an
# unmapped code then reports `not-persisted` over a landed write, and that
# remedy re-sends the call, double-writing the append-only notes.
_UPDATE_PATCH_LANDED = False

# The one exit code that names its own outcome: both precondition guards refuse
# before any mutation. Every other code is resolved from `_UPDATE_PATCH_LANDED`.
_UPDATE_UNSELECTED_OUTCOME = {4: 'precondition-mismatch'}


def _emit_update_outcome(outcome):
    """Write `cmd_update`'s machine-readable terminal outcome line (issue #1562).

    The remedy is derived from the outcome rather than passed in, so a call site
    cannot pair them wrongly; an outcome outside the map raises KeyError rather
    than emitting a bogus remedy. Emit AFTER the path's own prose line, because
    the line's contract is that it is the last line on stderr.
    """
    global _UPDATE_OUTCOME_EMITTED
    _UPDATE_OUTCOME_EMITTED = True
    sys.stderr.write(
        f"workpad.py update: outcome={outcome} "
        f"remedy={_UPDATE_REMEDY_BY_OUTCOME[outcome]}\n"
    )


def _update_fallback_outcome(exit_code=None):
    """Resolve an unselected outcome from observed state, never from a guess.

    Do not shorten this to a code lookup defaulting to `not-persisted`: the
    post-PATCH tail can still raise (a `BrokenPipeError` on the body echo when a
    caller pipes the command), and reporting a landed write as not-persisted
    routes the caller to re-send it, double-writing the append-only notes.
    """
    if exit_code in _UPDATE_UNSELECTED_OUTCOME:
        return _UPDATE_UNSELECTED_OUTCOME[exit_code]
    return 'landed-status-unverified' if _UPDATE_PATCH_LANDED else 'not-persisted'


def cmd_update(args):
    """Emit the terminal outcome line, then re-raise whatever ended the body.

    `BaseException` is caught rather than `SystemExit` alone because the tail
    after a successful PATCH can still raise, and letting that escape emits no
    line over a landed write — which the absent-line rule tells a caller to read
    as not landed. Each handler re-raises, preserving the exit status.
    """
    global _UPDATE_OUTCOME_EMITTED, _UPDATE_PATCH_LANDED
    _UPDATE_OUTCOME_EMITTED = False
    _UPDATE_PATCH_LANDED = False
    try:
        _cmd_update_inner(args)
    except SystemExit as e:
        if not _UPDATE_OUTCOME_EMITTED:
            _emit_update_outcome(_update_fallback_outcome(e.code))
        raise
    except BaseException:
        if not _UPDATE_OUTCOME_EMITTED:
            _emit_update_outcome(_update_fallback_outcome())
        raise
    if not _UPDATE_OUTCOME_EMITTED:
        _emit_update_outcome(_update_fallback_outcome())


def _fail(prefix, exc, code=1):
    # `code` defaults to 1 (the historical contract for every subcommand). The
    # callers that override it to 3 are cmd_status (its gh-api/transport/auth
    # failure paths) and the acs surfaces — `_acs_read_workpad` (which passes
    # api_fail_code=3) and `_acs_fetch_issue_body` (`_fail('acs-resolve', …,
    # code=3)`). In every one of those the point is the same: the cloud stall
    # backstop (and cmd_acs_resolve's SystemExit router) can tell an
    # auth/transport READ failure — the workpad or issue may be perfectly
    # healthy — apart from a genuinely unreadable/absent workpad. Callers that do
    # not override keep exit 1 unchanged.
    # `_run` sets `encoding`, so `.stderr` is normally str — but an exception
    # raised without capture carries None, and one built elsewhere can carry
    # bytes, which would render as a `b'...'` repr. Both are handled the same way
    # `cmd_patch`'s live-body read arm handles them (`getattr(e, 'stderr', None)
    # or e`, then decode-and-strip), so the two error surfaces of one command
    # cannot diverge: an absent or empty stderr falls back to the exception
    # itself rather than printing a breadcrumb that names no failure.
    msg = getattr(exc, 'stderr', None) if isinstance(exc, subprocess.CalledProcessError) else None
    if isinstance(msg, bytes):
        msg = msg.decode('utf-8', 'replace')
    msg = msg.strip() if isinstance(msg, str) else ''
    msg = msg or str(exc)
    sys.stderr.write(f"workpad.py {prefix}: {msg}\n")
    sys.exit(code)


def _repo_root():
    # Resolve the git repo root so config reads anchor there, not to cwd (issue
    # #295) — the Python mirror of lib/config-source.sh's
    # `git rev-parse --show-toplevel 2>/dev/null || pwd`. A native `git` subprocess
    # (like the existing `gh` calls) is Windows-safe — unlike exec-ing a .sh
    # ([WinError 193], issue #275). Returns the root string, or None when not in a
    # git tree (git rev-parse rc!=0) or git cannot run at all (OSError) — the caller
    # then falls back to Path.cwd(), degrading exactly as the pre-#295 code did.
    try:
        r = _run(['git', 'rev-parse', '--show-toplevel'])
    except (subprocess.CalledProcessError, OSError):
        return None
    root = r.stdout.strip()
    return root or None


def _git_root_error_suffix():
    # Best-effort: capture git's own stderr for the no-root breadcrumb so the real
    # cause (safe.directory refusal, or git absent → OSError) surfaces instead of being
    # discarded. Returns a " (git: …)" suffix, or "" when git succeeded or printed
    # nothing to stderr. Gates on a NON-ZERO rc (mirroring the match-deferrals sibling)
    # so a git that succeeds on this second call but printed a benign advisory to stderr
    # is not misattributed as the failure cause. Catches broadly (not just OSError) so a
    # non-UTF-8 decode or any other subprocess error cannot make the breadcrumb path
    # itself raise — it truly never raises.
    try:
        r = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, encoding='utf-8',
        )
        err = (r.stderr or '').strip() if r.returncode != 0 else ''
    except OSError as e:
        err = str(e)
    except Exception:
        err = ''
    return f" (git: {err})" if err else ""


def _repo_full(api_fail_code=1):
    try:
        r = _run([GH, 'repo', 'view', '--json', 'nameWithOwner',
                  '-q', '.nameWithOwner'])
    except (subprocess.CalledProcessError, OSError) as e:
        _fail('repo lookup', e, code=api_fail_code)
    return r.stdout.strip()


_DEFAULT_WORKPAD_MARKER = '<!-- prflow:workpad -->'

# ── The comment-marker namespace, both spellings (issue #1003) ───────────────
# PRFlow WRITES `<!-- prflow:… -->`; every artifact created before the rename
# carries `<!-- devflow:… -->`, and the rename rewrites no existing issue or PR
# body. A single workpad is therefore mutated in place ACROSS the rename
# boundary, so one body can carry BOTH spellings at once — pre-rename records
# beside post-rename ones. Every grammar below accepts either spelling PER
# RECORD, never per artifact: a per-artifact choice would leave a pre-rename
# `deferred-filed` record undischarged and file its follow-up issue a second
# time, and would leave a pre-rename `scope-decision pr=pending` record out of
# the pending->pr substitution so the binding silently no-ops.
#
# END CRITERION for dropping the superseded alternative, mirroring
# lib/rename-map.json's transitional_read_through.end_criterion: it is removed in
# the first release after the maintainer confirms no repository still carries a
# live workpad, progress comment or audit comment written in the superseded
# spelling. It is not removed on a timer.
_MARKER_NS_CURRENT = '<!-- prflow:'
_MARKER_NS_SUPERSEDED = '<!-- devflow:'
# The regex-source form of the same alternation, for the record grammars below.
_MARKER_NS_RE = r'<!-- (?:pr|dev)flow:'


def _marker_variants(marker: str) -> tuple[str, ...]:
    """`marker` plus its other-namespace twin, when it is one of PRFlow's own.

    A marker a consumer customized to something outside the namespace has no
    twin and is returned alone, so this never invents a second literal to match.
    The superseded->current direction is live too: a consumer whose config still
    carries the pre-rename value keeps finding comments written under either.
    """
    if marker.startswith(_MARKER_NS_CURRENT):
        return (marker, _MARKER_NS_SUPERSEDED + marker[len(_MARKER_NS_CURRENT):])
    if marker.startswith(_MARKER_NS_SUPERSEDED):
        return (marker, _MARKER_NS_CURRENT + marker[len(_MARKER_NS_SUPERSEDED):])
    return (marker,)


def _workpad_marker(explicit=None):
    # An explicit override wins: /devflow:review uses this to target its own
    # `<!-- prflow:review-progress -->` comment with the same helper, rather
    # than forking a parallel script. Precedence: the `--marker` CLI flag, then
    # the `DEVFLOW_WORKPAD_MARKER` env var, then config, then the built-in
    # default. The flag is preferred over the env var because a leading
    # env-assignment (`DEVFLOW_WORKPAD_MARKER=… workpad.py …`) makes the command
    # un-matchable against the cloud allow-list rule `Bash(.../workpad.py:*)`
    # (the command no longer *starts with* the script path), so those calls are
    # silently denied on the read-only `review` profile; `--marker` keeps the
    # path as the command prefix. The env var is retained for back-compat.
    override = (explicit or '').strip() or os.environ.get('DEVFLOW_WORKPAD_MARKER', '').strip()
    if override:
        return override
    # Read the marker from .prflow/config.json directly in-process (issue
    # #275): Windows cannot exec a .sh helper ([WinError 193]), so the former
    # config-get.sh subprocess hop silently dropped a configured custom marker
    # back to the built-in default there.
    #
    # SHARED REPO-ROOT CONFIG CONTRACT (issue #295, supersedes the #275 cwd-relative
    # contract): this resolver and scripts/config-get.sh both anchor the DEFAULT
    # `.prflow/config.json` to the git repo root (git rev-parse --show-toplevel,
    # falling back to cwd) — NOT relative to the current working directory — so a run
    # invoked from a repo subdirectory reads the consumer's ROOT config, mirroring
    # lib/config-source.sh. Keep the two readers in lockstep: they resolve the same
    # file for the same cwd. An absent file is the normal unconfigured case — silent
    # fallback so the local tier works with no config at all. (Limitation:
    # --show-toplevel returns the NEAREST git root, so a nested submodule/inner repo
    # or a monorepo whose .prflow/ is not at the git root is not covered.)
    _root = _repo_root()
    if _root is not None:
        config_file = Path(_resolve_state_dir(_root)) / 'config.json'
    else:
        cwd = Path.cwd()
        config_file = Path(_resolve_state_dir(str(cwd))) / 'config.json'
        # Breadcrumb only when NEITHER a git root NOR a .prflow/ dir can be located —
        # the silent-drop class this fix closes. A git root with no .prflow/ is the
        # normal unconfigured case and stays silent (handled by FileNotFoundError below).
        # git can exit non-zero while genuinely INSIDE a repo (safe.directory /
        # dubious-ownership), or be absent — not only "outside a git tree" — so don't
        # assert "not in a git repo"; report the root could not be resolved and surface
        # git's own stderr (re-run on this rare path only).
        if not (cwd / '.prflow').is_dir() and not (cwd / '.devflow').is_dir():
            sys.stderr.write(
                f"workpad.py: could not resolve a git repo root"
                f"{_git_root_error_suffix()} and no .prflow/ at {str(cwd)!r}; "
                f"falling back to default marker\n"
            )
    try:
        with config_file.open(encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        # Absent config (or an absent .prflow/ dir) is the normal
        # unconfigured case — silent, unlike the breadcrumbed failures below.
        return _DEFAULT_WORKPAD_MARKER
    except (OSError, ValueError) as e:
        # ValueError covers json.JSONDecodeError AND UnicodeDecodeError — a
        # config.json written by PowerShell 5.x `>` redirection is UTF-16LE
        # with a BOM (the PowerShell UTF-16LE redirection pitfall), which raises
        # UnicodeDecodeError, not JSONDecodeError, at read time.
        # A present-but-unreadable/malformed config is otherwise
        # indistinguishable from "no marker override configured": both fall
        # back to the built-in default. Leave a breadcrumb naming the file so
        # an operator debugging a "workpad not found" symptom on a repo with
        # `.prflow.workpad_marker` configured can tell the two apart.
        sys.stderr.write(
            f"workpad.py: could not read {str(config_file)!r} ({e}); "
            f"falling back to default marker\n"
        )
        return _DEFAULT_WORKPAD_MARKER
    devflow = data.get('prflow') if isinstance(data, dict) else None
    if not isinstance(devflow, dict) or 'workpad_marker' not in devflow:
        return _DEFAULT_WORKPAD_MARKER
    value = devflow['workpad_marker']
    # A non-string or blank value is "not configured" — never coerce a
    # misconfigured type into a garbage marker stamped into a comment — but a
    # PRESENT-and-invalid key gets a breadcrumb: silently defaulting would be
    # indistinguishable from "nothing configured", the same masked-fallback
    # class the malformed-JSON branch above breadcrumbs.
    if isinstance(value, str) and value.strip():
        return value.strip()
    sys.stderr.write(
        f"workpad.py: ignoring non-string or blank prflow.workpad_marker in "
        f"{str(config_file)!r}; falling back to default marker\n"
    )
    return _DEFAULT_WORKPAD_MARKER


def _find_workpad_comment(cmd, repo, issue, marker, api_fail_code=1):
    """Scan an issue's comments (paginated) and return the first whose body
    starts with `marker`, or None when the scan completed and none matched.

    Single source for the marker-scan that `cmd_id`, `cmd_status` and the acs
    surfaces (`_acs_read_workpad`, and so `cmd_acs`/`cmd_acs_resolve` through
    it) share — the `per_page=100`/`< 100` pagination boundary and the API/parse
    error handling live here once. A `gh api` or JSON-parse failure exits via
    `_fail(cmd, …)` with `api_fail_code` (default 1, so the caller's error prefix
    and historical exit code are preserved; cmd_status and `_acs_read_workpad`
    both pass 3 to distinguish a transport/auth failure from an unreadable
    workpad); a clean scan with no match returns None
    so the caller can apply its own "not found" contract (exit 2)."""
    page = 1
    while True:
        try:
            r = _run([
                GH, 'api',
                (f'/repos/{repo}/issues/{issue}/comments'
                f'?page={page}&per_page=100'),
            ])
        except (subprocess.CalledProcessError, OSError) as e:
            _fail(cmd, e, code=api_fail_code)
        try:
            items = json.loads(r.stdout)
        except json.JSONDecodeError as e:
            _fail(cmd, f"could not parse gh comments response: {e}", code=api_fail_code)
        # A rc-0 gh response that parses but is NOT a JSON array is a transport/API
        # anomaly, not a healthy comment page — most often an error envelope
        # (`{"message":"Bad credentials"}`) some gh/API paths emit at exit 0. Route
        # it through the same api_fail_code as a parse failure (exit 3 for cmd_status,
        # so the exit-3 promise covers a wrong-shape body, not only an unparseable
        # one) rather than iterating a dict's keys into an uncaught AttributeError
        # (which would surface as a bare exit 1, mislabeling an auth error as an
        # unreadable workpad).
        if not isinstance(items, list):
            _fail(
                cmd,
                f"gh comments response was not a JSON array "
                f"(got {type(items).__name__}): {str(items)[:200]}",
                code=api_fail_code,
            )
        for c in items:
            if (c.get('body') or '').startswith(_marker_variants(marker)):
                return c
        if len(items) < 100:
            return None
        page += 1


def cmd_id(args):
    marker = _workpad_marker(args.marker)
    c = _find_workpad_comment('id', _repo_full(), args.issue, marker)
    if c is not None:
        print(c['id'])
        return
    # Exit 2 (distinct from _fail's exit 1) means "scanned successfully, no
    # matching comment" — i.e. first run / not yet seeded. A real `gh api` or
    # parse failure exits 1 via _fail inside the scan. Callers can thus tell a
    # benign "create it" from a transient API error and avoid posting a duplicate
    # workpad comment on a failure they mistook for "not found".
    sys.exit(2)


def _comment_body(repo, comment_id):
    """The live body of one comment. Raises; each caller picks its own arm."""
    return _run([
        GH, 'api',
        f'/repos/{repo}/issues/comments/{comment_id}',
        '--jq', '.body',
    ]).stdout


def _comment_body_established(repo, comment_id):
    """(body, established) for one comment, read WITHOUT `--jq .body`.

    `--jq .body` cannot express presence: jq renders a missing key as the literal
    `null`, so an error envelope carrying no `.body` at exit 0 is indistinguishable
    from a comment whose body is the four characters `null`. Reading the raw object
    and testing `'body' in obj` shares the presence question with the data itself,
    so the accepted set cannot drift. Raises like `_comment_body`; a non-object
    payload, an absent `body` key, or a non-string `body` all return established
    False rather than a value the caller would treat as the live body.
    """
    out = _run([
        GH, 'api',
        f'/repos/{repo}/issues/comments/{comment_id}',
    ]).stdout
    try:
        obj = json.loads(out)
    except ValueError:
        return '', False
    if not isinstance(obj, dict) or not isinstance(obj.get('body'), str):
        return '', False
    return obj['body'], True


def cmd_body(args):
    # getattr defaults: the #814 driver calls cmd_body with only `comment_id`.
    issue = getattr(args, 'issue', None)
    comment_id = args.comment_id
    # Operand validation runs BEFORE any network call and exits 1 from here, so a
    # malformed/missing/ambiguous operand never reaches argparse's usage-error
    # exit 2 (which would be indistinguishable from the absent-workpad exit 2).
    if issue is not None and comment_id is not None:
        sys.stderr.write(
            "workpad.py body: pass either a positional comment id or --issue <n>, "
            "not both\n")
        sys.exit(1)
    if issue is None and comment_id is None:
        sys.stderr.write(
            "workpad.py body: no operand — pass a positional comment id, or "
            "--issue <n> to address the workpad by issue number\n")
        sys.exit(1)
    if issue is not None:
        if not (issue.isascii() and issue.isdigit()):
            sys.stderr.write(
                f"workpad.py body: --issue value must be a non-empty decimal "
                f"issue number (got {issue!r})\n")
            sys.exit(1)
        # Same marker scan `id`/`status` run; the scan result already carries the
        # full body, so no second fetch. Adopt status's exit vocabulary via
        # api_fail_code=3: exit 3 on a read failure, exit 2 on a clean-absent scan.
        marker = _workpad_marker(getattr(args, 'marker', None))
        c = _find_workpad_comment(
            'body', _repo_full(api_fail_code=3), issue, marker, api_fail_code=3)
        if c is None:
            sys.exit(2)
        sys.stdout.write(c.get('body') or '')
        return
    repo = _repo_full()
    try:
        out = _comment_body(repo, comment_id)
    except (subprocess.CalledProcessError, OSError) as e:
        # The positional arm cannot tell a wrong-operand 404 (an issue number in
        # the comment-id slot) from a transport/auth failure on a valid id, so it
        # documents the operand rather than diagnosing — the existing _fail detail
        # still follows (issue #2040/#2006).
        sys.stderr.write(
            "workpad.py body: the positional operand is read as a comment id; to "
            "read a workpad by issue number use: body --issue <n>\n")
        _fail('body', e)
    sys.stdout.write(out)


def _is_recognized_status_word(word: str) -> bool:
    """True if `word` (already glyph-stripped) is a canonical Status word —
    exactly one of `_STATUS_TO_PROGRESS_PHASE`'s keys (every in-progress phase
    word, plus 'complete') or one of the literal terminal words 'blocked' /
    'failed' / 'cancelled' (the words `_STATUS_TO_PROGRESS_PHASE` intentionally
    omits — see `_progress_phase_for_status`). Deliberately exact-match, NOT
    `_status_glyph(word) in ('🎉', '👎', '💥', '🛑')`: that delegates to
    `_status_glyph`'s own `startswith('complete'/'blocked'/'failed'/'cancelled')
    prefix check, which is intentional for its write-path callers but would let
    a corrupted word like
    'Completely wrong' or 'Blockeddependency' pass this recognition check —
    exactly the fail-open this function exists to close. No independent
    hardcoded word list: 'blocked', 'failed', and 'cancelled' are the only
    literals not already sourced from `_STATUS_TO_PROGRESS_PHASE` — all three are
    terminal words that map has no phase for (see `_progress_phase_for_status`);
    'failed' is the workflow-level stall-backstop "died" status (💥, issue #356),
    and 'cancelled' is the workflow-level stall-backstop "cancelled" status (🛑,
    issue #498)."""
    s = word.strip().lower()
    return s in _STATUS_TO_PROGRESS_PHASE or s in ('blocked', 'failed', 'cancelled')


def cmd_status(args):
    """Print the workpad Status as `CLASS GLYPH WORD` (e.g. 'interim 🚀 Reviewing').

    CLASS names the terminal end so a non-`Complete` terminal status is
    distinguishable from a completed one (issue #1025): 'complete' (🎉),
    'blocked' (👎), 'failed' (💥), 'cancelled' (🛑), else 'interim' for an
    in-progress glyph. The glyph comes from `_status_glyph` (the same helper the
    update path uses to render the Status line) and the class from `_status_class`
    (read-path only) — so the glyph vocabulary has one source of truth and no
    caller re-parses it ad hoc. Exit codes let a caller fail
    closed:
      0  status printed
      2  no workpad comment exists for this issue (scanned OK, none matched)
      1  the workpad exists but its Status line is missing/empty, OR the Status
         line has a value that isn't a recognized status word
         (present-but-unreadable — a content-shape failure, distinct from 'no
         workpad'). This is NOT a transport failure — the read succeeded, the
         content is unusable.
      3  a gh api / transport / auth failure (the `gh repo view` repo lookup or
         the `gh api` comment fetch failed — e.g. an expired App token — or that
         fetch returned a body that is unparseable (a dropped/truncated
         connection) or parses but is not a JSON array (an error envelope such as
         `{"message":"Bad credentials"}`)). Distinct from exit 1: the workpad may
         be perfectly healthy; the READ failed, not the content. Kept separate so the cloud stall backstop never mislabels
         an auth failure as an unreadable workpad and never burns a resume
         attempt on a workpad it could not read.
    The cloud stall backstop maps exit 1 and exit 2 alike to the 'unreadable'
    decision class, exit 3 to the distinct 'auth-failure' class (both fail
    closed), while a healthy run prints a class it can act on."""
    marker = _workpad_marker(args.marker)
    c = _find_workpad_comment(
        'status', _repo_full(api_fail_code=3), args.issue, marker,
        api_fail_code=3,
    )
    if c is None:
        # Scanned every page, no workpad — same benign exit 2 as `id`.
        sys.exit(2)
    body = c.get('body') or ''
    if not _STATUS_VALUE_RE.search(body):
        sys.stderr.write(
            "workpad.py status: workpad found but no Status line in it\n"
        )
        sys.exit(1)
    word = _status_word_from_body(body)
    if not word:
        sys.stderr.write(
            "workpad.py status: workpad Status line has no value\n"
        )
        sys.exit(1)
    if not _is_recognized_status_word(word):
        recognized = '/'.join(
            [w.capitalize() for w in _STATUS_TO_PROGRESS_PHASE]
            + ['Blocked', 'Failed', 'Cancelled']
        )
        sys.stderr.write(
            f"workpad.py status: workpad Status word {word!r} is not a "
            f"recognized status (expected one of {recognized}) — "
            "present-but-unreadable\n"
        )
        sys.exit(1)
    glyph = _status_glyph(word)
    cls = _status_class(glyph)
    print(f"{cls} {glyph} {word}")


# ---------------------------------------------------------------------------
# Acceptance-criteria extraction and resolution (issue #781)
# ---------------------------------------------------------------------------
# The review engine sources the requirements it judges a PR against from the
# GitHub issue BODY, while /devflow:implement's authoritative criteria have
# moved to the workpad (Phase 2.2.5 narrows the set, Phase 2.2.6 rewrites text,
# Phase 3.4 retags). `acs` reads the workpad's section back out; `acs-resolve`
# resolves BOTH surfaces, applies the PR-identity guard, selects the
# reviewer-facing value, and reports normalized divergence.
#
# Both live here rather than in `scripts/parse-acs.py` because the read-only
# review profile grants `Bash(.prflow/vendor/prflow/scripts/workpad.py:*)` and
# does NOT grant `parse-acs.py`: riding on workpad.py is what lets the cloud
# auto-review tier reach this at all without widening the review
# security-boundary lock.

# The source token names WHICH surface supplied the reviewer-facing criteria, so
# Phase 4's `## Issue Compliance` can report it. Each value is a state a reader
# must be able to tell apart — collapsing any two of them would make a PRFlow
# run whose workpad read silently failed, or whose mirroring never ran,
# indistinguishable from an ordinary non-implement PR on the very report line
# this mechanism adds.
_ACS_SOURCE_WORKPAD = 'workpad'
_ACS_SOURCE_ISSUE_BODY = 'issue-body'
_ACS_SOURCE_WORKPAD_UNMIRRORED = 'workpad-unmirrored'
_ACS_SOURCE_WORKPAD_READ_FAILED = 'workpad-read-failed'
_ACS_SOURCE_PR_IDENTITY_MISMATCH = 'pr-identity-mismatch'
_ACS_SOURCE_NONE = 'none'
# Routed when the `issue` argument is empty or non-numeric (issue #857). The §0.4
# fence's S1 numeric guard moved INTO this subcommand so the fence is a bare
# single-statement call; a non-numeric argument means no surface can be examined at
# all, exactly what `resolver-unavailable` names — so it reuses that existing token
# rather than widening the `acceptance_criteria_source` vocabulary Phase 4 renders.
_ACS_SOURCE_RESOLVER_UNAVAILABLE = 'resolver-unavailable'
# The /prflow:implement Phase 3.4 gate's defined-degradation read (`acs-gate`,
# issue #1214). `workpad-absent` names a CLEAN absence (no workpad) — kept
# distinct from `workpad-read-failed` (a transport/parse failure) so the gate
# never reroutes a benign first-run absence onto the transport-failure label
# (AC6). `unestablished` names the both-surfaces-down shape: the workpad read
# failed AND the issue-body fallback also failed, so no criteria could be
# resolved and the gate must not pass (AC5).
_ACS_SOURCE_WORKPAD_ABSENT = 'workpad-absent'
_ACS_SOURCE_UNESTABLISHED = 'unestablished'

_ACS_SECTION = 'Acceptance Criteria'


def _acs_render(items: list[dict], *, exclude_post_merge: bool,
                neutralize_boxes: bool) -> str:
    """Render parsed criteria back to checkbox lines.

    `exclude_post_merge` drops every line already carrying the mirror-time
    ` (post-merge)` tag. The tag is READ, never re-derived from
    `parse-acs.py`'s trigger phrases: those criteria are work this PR is not
    delivering, so handing them to the checklist generator unfiltered would mint
    highest-priority items a Phase 2 verifier then FAILs — the exact failure
    this mechanism exists to remove.
    """
    kept = [
        it for it in items
        if not (exclude_post_merge and is_post_merge_tagged(it['text']))
    ]
    return '\n'.join(render_line(it, neutralize_box=neutralize_boxes) for it in kept)


def _acs_workpad_state(section_lines: list[str], items: list[dict]) -> str:
    """Classify the workpad's `## Acceptance Criteria` section.

    Distinguishes the two NON-EMPTY sentinels that both yield zero criteria,
    because they make OPPOSITE claims: `parse-acs.py`'s
    `_(none provided in issue body)_` says the issue authoritatively carries no
    criteria, while `_AC_PENDING_PLACEHOLDER` says Phase 1.2 mirroring never
    ran. Collapsing them would report a run whose mirroring silently failed as a
    run that legitimately had nothing to mirror.
    """
    if items:
        return _ACS_SOURCE_WORKPAD
    if any(_AC_PENDING_PLACEHOLDER in ln for ln in section_lines):
        return _ACS_SOURCE_WORKPAD_UNMIRRORED
    return _ACS_SOURCE_ISSUE_BODY


def _acs_read_workpad(cmd: str, issue: str):
    """Locate the workpad and parse its `## Acceptance Criteria` section.

    Returns `(comment_body, section_lines, items)`. Exits 2 (empty stdout AND
    empty stderr) on a clean absence — the same benign exit `id` and `status`
    already use, so Phase 0.4 can tell it from argparse's own exit 2 by the
    empty stderr. A gh/transport/parse failure exits 3 via `_fail`, which is a
    DIFFERENT non-zero shape so a transport blip is never routed as "this PR has
    no workpad".

    The marker is the DEFAULT implement marker: there is deliberately no
    `--marker` flag on these subcommands, so a caller cannot point this read at
    `/devflow:review`'s own `<!-- prflow:review-progress -->` comment
    per-invocation. That closes the CALLER channel, not every channel —
    `_workpad_marker(None)` still resolves through `DEVFLOW_WORKPAD_MARKER` and
    `.prflow.workpad_marker`. Those are deliberately not closed: they are the
    same value the implement workpad itself is written under, so repointing one
    moves this read and the workpad together rather than desynchronizing them.
    """
    marker = _workpad_marker(None)
    c = _find_workpad_comment(
        cmd, _repo_full(api_fail_code=3), issue, marker, api_fail_code=3,
    )
    if c is None:
        sys.exit(2)
    body = c.get('body') or ''
    section_lines = extract_section(body, _ACS_SECTION)
    return body, section_lines, parse_checkboxes(section_lines)


def cmd_acs(args):
    """Print the workpad's `## Acceptance Criteria` section.

    Unfiltered by default — every criterion carried through with its tick state
    preserved and its ` (post-merge)` tag left as stored — because the
    unfiltered section is the divergence comparand. The two flags produce the
    reviewer-facing value instead.

    Not a byte copy of the stored section: the output is the PARSED checkbox
    items re-rendered, so blank lines between them are dropped and a `* [ ]`
    bullet normalizes to `- [ ]`. What is guaranteed is the content contract
    above — no criterion filtered, no tick state or tag altered — which is what
    the comparand and the reviewer-facing value both depend on.

    A pure read: no PATCH, no timestamp, nothing time-varying in the output, so
    re-running it against an unchanged workpad is byte-identical by
    construction.
    """
    _require_section_parse('acs')
    _, section_lines, items = _acs_read_workpad('acs', args.issue)
    out = []
    if args.emit_source_token:
        out.append(_acs_workpad_state(section_lines, items))
    rendered = _acs_render(
        items,
        exclude_post_merge=args.exclude_post_merge,
        neutralize_boxes=args.neutralize_boxes,
    )
    if rendered:
        out.append(rendered)
    if out:
        print('\n'.join(out))


# Exit codes for the degrading Phase 3.4 acceptance-criteria read (issue #1214).
# Each shape carries a distinct code AND a distinct `source:` token so the gate
# can tell a clean read from a transport-degraded fallback from an unestablished
# measurement — and never read any degraded shape as a passing gate.
_ACS_GATE_OK = 0             # workpad read cleanly; criteria + tick state authoritative
_ACS_GATE_ABSENT = 2         # clean absence — no workpad (the existing benign shape; AC6)
_ACS_GATE_DEGRADED = 3       # workpad read FAILED; criteria recovered from the issue body
_ACS_GATE_UNESTABLISHED = 4  # workpad read FAILED and the issue-body fallback also failed


def _acs_gate_issue_body_criteria(issue: str) -> "str | None":
    """Recover the acceptance criteria from the issue BODY via `parse-acs.py`.

    The issue body is read through a DIFFERENT GitHub endpoint than the workpad
    comment-listing address, so it stays reachable during the one-endpoint outage
    the gate degradation exists to survive. AC3 names `scripts/parse-acs.py` as
    the fallback source, so this shells out to the sibling script (via the current
    interpreter — never a `.sh`/porcelain hop) rather than re-deriving the parse.

    Returns the rendered `md` criteria (an empty string when the issue carries no
    `## Acceptance Criteria` section), or `None` when the issue body itself could
    not be read. That None-on-failure is the recovery-poll discipline (issue
    #1214, and the model `check-completion-evidence.py`'s `_probe_remote` sets): a
    non-zero exit or an exec failure means GitHub was not reached, so the criteria
    are UNKNOWN — never collapsed onto "the issue has no criteria".
    """
    parse_acs = str(Path(__file__).resolve().parent / 'parse-acs.py')
    try:
        r = subprocess.run(
            [sys.executable, parse_acs, '--issue', str(issue), '--format', 'md'],
            capture_output=True, text=True, check=False,
        )
    except OSError:
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip('\n')


def cmd_acs_gate(args):
    """Acceptance-criteria read for the /prflow:implement Phase 3.4 gate, with a
    DEFINED degradation when the workpad cannot be read (issue #1214).

    The gate reads the workpad's `## Acceptance Criteria` section to confirm every
    non-post-merge criterion is ticked. A GitHub fault confined to the
    comment-listing endpoint fails that read while the issue body itself stays
    reachable — so, exactly as `cmd_acs_resolve` already does for the review
    engine, a workpad read failure is ROUTED to a distinct label and the criteria
    are recovered from the issue body via `scripts/parse-acs.py`, NEVER read as a
    passing gate.

    Line 1 of stdout is always `source: <token>`; the rendered criteria follow.
    The (code, token) pairs are:
      0  source: workpad             — clean workpad read; tick state authoritative.
      2  source: workpad-absent      — clean absence, no workpad. The existing
                                        absent-case shape, kept distinct from the
                                        transport-failure label (AC6).
      3  source: workpad-read-failed — the workpad read failed (transport/parse);
                                        criteria recovered from the issue body. The
                                        gate must NOT pass — the tick state could
                                        not be established (AC3/AC4).
      4  source: unestablished       — the workpad read failed AND the issue-body
                                        fallback also failed; no criteria could be
                                        resolved (AC5). The gate must NOT pass.
    """
    _require_section_parse('acs-gate')
    try:
        _, _section_lines, items = _acs_read_workpad('acs-gate', str(args.issue))
    except SystemExit as e:
        if e.code == 2:
            # Clean absence — the existing benign shape. Kept distinct from the
            # transport-failure label (AC6); the exit-2 contract is preserved.
            print(f'source: {_ACS_SOURCE_WORKPAD_ABSENT}')
            sys.exit(_ACS_GATE_ABSENT)
        if e.code == 3:
            # A transport/parse failure reaching the workpad. Fall back to the
            # issue body — the endpoint the outage did not touch.
            body_md = _acs_gate_issue_body_criteria(str(args.issue))
            if body_md is None:
                print(f'source: {_ACS_SOURCE_UNESTABLISHED}')
                sys.exit(_ACS_GATE_UNESTABLISHED)
            print(f'source: {_ACS_SOURCE_WORKPAD_READ_FAILED}')
            if body_md:
                print(body_md)
            sys.exit(_ACS_GATE_DEGRADED)
        # Any other SystemExit is an unexpected shape this handler must not absorb.
        raise
    # Clean workpad read: render the section exactly as `acs` does (unfiltered,
    # tick state and (post-merge) tags preserved), prefixed with the source token.
    print(f'source: {_ACS_SOURCE_WORKPAD}')
    rendered = _acs_render(items, exclude_post_merge=False, neutralize_boxes=False)
    if rendered:
        print(rendered)


def _acs_diverge(issue_items: list[dict], workpad_items: list[dict],
                 decisions: list[dict]) -> list[str]:
    """Compare the two criterion sets and describe how the workpad differs.

    Defined over NORMALIZED sets (` (post-merge)` tag stripped, tick state
    ignored, whitespace collapsed), never raw section text: `parse-acs.py`
    writes the workpad section with post-merge tags the issue body does not
    carry and mirrors the issue's `## Test Plan` items into the same block, and
    tick state moves as the run proceeds — so a raw-text comparison would report
    divergence on every PRFlow PR and carry no signal.

    Reports DROPS, audited DEFERRALS, and TEXT CHANGES only — a criterion the
    workpad no longer carries renders as `DEFERRED:` when a bound record
    explains it and `DROP:` when nothing does, and a `rewritten` record renders
    as `CHANGED:` — but only when that record actually carries a `newtext=`
    payload; a `rewritten` record without one covers nothing and its criterion
    routes to `DROP` like any other unexplained one. A criterion present in the workpad and
    absent from the issue body is never a finding: that is exactly what the
    mirrored `## Test Plan` items look like, and `_render_md` writes them into
    one flat block with no heading, label, or marker, so the section carries no
    discriminator an extractor could use to exclude them.

    An uncovered text change is indistinguishable from a drop — the old text is
    simply missing — so it is reported as `DROP`. That is the honest reading:
    the issue body stays the authority on membership, and only a `rewritten`
    record can license the workpad's text over it.
    """
    issue_norm = [normalize_criterion(it['text']) for it in issue_items]
    workpad_norm = {normalize_criterion(it['text']) for it in workpad_items}
    deferred = {d['text'] for d in decisions if d['kind'] == 'deferred'}
    # A `rewritten` record with no `newtext=` field records nothing about what
    # replaced the criterion, so it licenses no text change: it is excluded here
    # and its criterion falls through to `DEFERRED`/`DROP` like any other
    # uncovered one. Crediting it as an audited `CHANGED:` would report a scope
    # narrowing as reviewed on a record that establishes nothing — the same
    # fail-closed direction `_parse_scope_decisions` takes for an empty payload,
    # and the direction `_acs_pr_identity_ok` already takes for the same shape
    # (its `new_text is not None` conjunct), which this line was asymmetric with.
    rewritten = {d['text']: d['new_text'] for d in decisions
                 if d['kind'] == 'rewritten' and d['new_text']}

    lines = []
    for text in issue_norm:
        if text in workpad_norm:
            continue
        if text in rewritten:
            lines.append(f'CHANGED: {text} -> {rewritten[text]}')
        elif text in deferred:
            lines.append(f'DEFERRED: {text}')
        else:
            lines.append(f'DROP: {text}')
    return lines


def _acs_pr_identity_ok(issue_items: list[dict], workpad_items: list[dict],
                        decisions: list[dict]) -> bool:
    """True when the workpad's criteria are safe to review THIS PR against.

    Not the same as "provably authored by this PR's run", and the difference is
    deliberate. The guard only rejects a workpad whose set is NARROWER than the
    issue body's with nothing on record to explain the narrowing; a foreign
    section that is a superset of the issue body is accepted, because reviewing
    against a superset can only add criteria, never silently drop one — and
    dropping is the failure this guard exists to prevent.

    A workpad is one comment per issue, and Phase 2.2.5 replaces its
    `## Acceptance Criteria` section WHOLESALE — so a second PR's run, or a
    re-triggered /devflow:implement on the same issue, overwrites the criteria
    the first PR was reviewed against.

    Fails CLOSED on an absent comparand, and does so PER CRITERION — never at
    the level of the record set as a whole. Every criterion the issue body
    carries and the workpad does not must be individually explained by a record
    bound to this PR: a `deferred` record naming that criterion, or a
    `rewritten` record naming it whose `new_text` is itself present in the
    workpad (the criterion did not vanish, it was restated). One unexplained
    criterion rejects the workpad, however many records exist — including the
    zero-record shape a pre-change workpad and a failed record write both take.
    An existential `bool(decisions)` test would instead let a single unrelated
    record license dropping every other criterion: the vacuous-coverage shape
    this guard forbids, and the same shape an empty base64 payload takes (which
    is why `_parse_scope_decisions` drops those records outright).
    """
    issue_norm = {normalize_criterion(it['text']) for it in issue_items}
    workpad_norm = {normalize_criterion(it['text']) for it in workpad_items}
    if not issue_norm or not workpad_norm:
        return True
    # Pure short-circuit, NOT a load-bearing guard: on a superset the loop below
    # iterates an empty difference and returns True on its own. Deleting this line
    # is behaviorally inert (mutation-checked green), so no test pins it and none
    # should be added claiming to — a test named for a guard that cannot fail is a
    # vacuous one. The superset ACCEPTANCE behavior itself is covered end-to-end by
    # run.sh's `wp-superset.md` fixture.
    if workpad_norm >= issue_norm:
        return True
    deferred = {d['text'] for d in decisions if d['kind'] == 'deferred'}
    rewritten = {d['text']: d['new_text'] for d in decisions if d['kind'] == 'rewritten'}
    for text in issue_norm - workpad_norm:
        if text in deferred:
            continue
        new_text = rewritten.get(text)
        if new_text is not None and new_text in workpad_norm:
            continue
        return False
    return True


def _acs_fetch_issue_body(issue: str) -> str:
    try:
        r = _run([GH, 'issue', 'view', str(issue), '--json', 'body', '-q', '.body'])
    except (subprocess.CalledProcessError, OSError) as e:
        _fail('acs-resolve', e, code=3)
    return r.stdout


def cmd_acs_resolve(args):
    """Resolve the reviewer-facing acceptance criteria and name their source.

    Resolves BOTH surfaces — never a short-circuit chain — because the
    non-selected set is the divergence comparand, and a fallback that stopped at
    its first hit would leave that report unable to fire on the one population
    it matters for.

    The workpad section is parsed ONCE and that one item list is rendered TWICE,
    for different jobs: unfiltered (the comparand) and post-merge-filtered (the
    reviewer-facing value) — so the two can never disagree about membership,
    only about the post-merge filter. Filtering
    the comparand instead would report every post-merge criterion as a workpad
    drop on every implement PR, because `parse-acs.py` synthesizes that tag at
    mirror time and the issue body carries those same criteria untagged.

    Always exits 0 on a resolvable state: a workpad that is absent or unreadable
    is a ROUTED outcome carrying its own source token, not a run-ending error.
    Exit 3 covers the two ways this command cannot even begin: a failure to read
    the issue body itself (without which there is no comparand and nothing to
    resolve), and the opening `_require_section_parse('acs-resolve')` when
    `scripts/section_parse.py` was not deployed beside workpad.py — a real
    partial-deployment shape this file's import block documents. Both are
    "no basis to resolve", distinct from the ROUTED workpad outcomes above.

    The `none` source is reached ONLY from the clean-absence state, because
    `none` asserts both surfaces were examined and neither carried criteria. A
    routed state whose issue-body fallback also comes up empty keeps its own
    token: collapsing `workpad-read-failed` onto `none` would fabricate a
    measurement of a surface this run never read, and collapsing
    `workpad-unmirrored` onto it would report a silently-failed mirroring as an
    ordinary criteria-less PR.

    A non-numeric (or empty) issue argument is ROUTED, not aborted (issue #857):
    the §0.4 fence's S1 numeric guard moved here so that fence is a bare
    single-statement call the cloud matcher permits. Such an argument means no
    surface can be examined at all, so this prints the `resolver-unavailable`
    source token with exit 0 rather than letting argparse abort with exit 2 —
    preserving the always-exit-0-on-a-resolvable-state contract. (An unreadable
    workpad COMMENT remains routed as `workpad-read-failed`, as before.) The
    `issue` argument for this subcommand is therefore accepted as a string and
    validated here, not by argparse `type=int`.
    """
    # `issue` is a required positional accepted as a string (see the argparse note),
    # so `args.issue` is always present; the ASCII-only digit test is deliberate — it
    # rejects the non-ASCII digits `str.isdigit()`/`isdecimal()` would accept, matching
    # the seed helper's `*[!0-9]*` shell guard.
    issue_arg = args.issue
    if not issue_arg or not all(c in '0123456789' for c in issue_arg):
        # Breadcrumb on stderr so a CALLER bug (a malformed issue argument) is
        # distinguishable from an infrastructure denial: both route to the same
        # `resolver-unavailable` token on stdout, and without this line the two are
        # indistinguishable to whoever reads the run. The old Phase 0.4 fence emitted
        # a `::warning::` naming this cause; folding the guard into the helper must not
        # lose that diagnostic. stdout stays byte-identical (it is the routed contract).
        print(
            f"workpad.py acs-resolve: issue argument {issue_arg!r} is not numeric — "
            f"no surface can be examined; routing as "
            f"{_ACS_SOURCE_RESOLVER_UNAVAILABLE}",
            file=sys.stderr,
        )
        print(f'source: {_ACS_SOURCE_RESOLVER_UNAVAILABLE}')
        print('criteria:')
        print('divergence:')
        print('not-applicable')
        return
    _require_section_parse('acs-resolve')
    issue_body = _acs_fetch_issue_body(args.issue)
    issue_items = parse_checkboxes(extract_section(issue_body, _ACS_SECTION))

    # The workpad read is best-effort: each failure shape becomes a token, so a
    # `gh` transport blip can never present as a normal issue-body resolution.
    workpad_items: list[dict] = []
    comment_body = ''
    try:
        comment_body, section_lines, workpad_items = _acs_read_workpad(
            'acs-resolve', args.issue)
        state = _acs_workpad_state(section_lines, workpad_items)
    except SystemExit as e:
        # Only the TWO exits `_acs_read_workpad` documents are routed here: 2
        # (clean absence) and 3 (`_fail`'s read failure). Any other SystemExit is
        # an unexpected shape this handler must not absorb — swallowing it would
        # report an unrelated abort as a routine issue-body resolution, so it is
        # re-raised.
        if e.code == 2:
            state = _ACS_SOURCE_ISSUE_BODY      # clean absence — no workpad at all
        elif e.code == 3:
            state = _ACS_SOURCE_WORKPAD_READ_FAILED
        else:
            raise

    decisions = _parse_scope_decisions(comment_body, args.pr)

    if state == _ACS_SOURCE_WORKPAD and not _acs_pr_identity_ok(
            issue_items, workpad_items, decisions):
        state = _ACS_SOURCE_PR_IDENTITY_MISMATCH

    if state == _ACS_SOURCE_WORKPAD:
        source = _ACS_SOURCE_WORKPAD
        selected = workpad_items
    else:
        # Every non-workpad state falls back to the issue body; only the TOKEN
        # differs, so Phase 4 reports the reason distinctly while the reviewer
        # still gets a specification whenever one exists anywhere.
        source = state
        selected = issue_items
        # The `none` demotion is gated on the CLEAN-ABSENCE state alone. `none`
        # asserts that both surfaces were examined and neither carried criteria,
        # which is true only when there was no workpad to read (`issue-body`).
        # For every other routed state the workpad's criteria were either never
        # read (`workpad-read-failed` — an unestablished measurement, never
        # collapsed onto the real value `none`), never mirrored
        # (`workpad-unmirrored` — the OPPOSITE claim from a legitimately empty
        # section). Demoting either to `none` because the issue-body FALLBACK came
        # up empty destroys the very signal each token exists to carry. Written as
        # an allow-list of the ONE demoting state rather than a deny-list of the
        # others, so it stays correct as states are added — `pr-identity-mismatch`
        # cannot co-occur with an empty issue body today (`_acs_pr_identity_ok`
        # returns True when there is no issue-side criterion to drop), and a
        # deny-list would have to be revisited if that ever changed.
        if not issue_items and state == _ACS_SOURCE_ISSUE_BODY:
            source = _ACS_SOURCE_NONE

    print(f'source: {source}')
    print('criteria:')
    rendered = _acs_render(selected, exclude_post_merge=True, neutralize_boxes=True)
    if rendered:
        print(rendered)
    print('divergence:')
    if state in (_ACS_SOURCE_WORKPAD, _ACS_SOURCE_PR_IDENTITY_MISMATCH):
        for line in _acs_diverge(issue_items, workpad_items, decisions) or ['none']:
            print(line)
    else:
        print('not-applicable')


# ── Leading-marker preservation across a full-body rewrite (issue #1508) ────
# A comment's identity is its line-1 marker, and a verdict stamp is the line
# after it. A caller that re-authors the whole body from state it holds drops
# whatever it does not retype, and a marker-resolving reader does not error on
# the result: its scan finds nothing and reads "there was no such comment".
#
# The scan stops at two lines because that is the window every reader uses
# (docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md §8) — a marker deeper in a body is
# prose, so hoisting one would invent a stamp the producer never made.
_LEADING_MARKER_SCAN = 2
# Anchored at column 0, because that is where the readers' predicate anchors
# (`_find_workpad_comment`'s `body.startswith(...)`): recognising an INDENTED marker
# would let a composed body claim one no reader can resolve. Trailing whitespace goes
# the other way — the readers accept it, so refusing it here would leave a live marker
# they resolve unpreserved — and is tolerated and stripped off the re-inserted line,
# which also covers the CRLF GitHub returns for a body last edited in the web UI.
_LEADING_MARKER_RE = re.compile(
    r'^' + _MARKER_NS_RE + r'([A-Za-z0-9_.:-]+)[^\n]*-->[ \t\r]*$')


def _leading_markers(body):
    """`(markers, tail)` — the leading PRFlow marker-comment lines, then the rest.

    `markers` is `[(kind, line)]` with each line's trailing whitespace removed, so
    a CRLF live body never injects a stray `\\r` into an LF one. `tail` is every
    remaining line, fully split, so a caller may both rebuild the body and match
    over it line-by-line without re-splitting.
    """
    lines = body.split('\n')
    found = []
    for line in lines[:_LEADING_MARKER_SCAN]:
        m = _LEADING_MARKER_RE.match(line)
        if not m:
            break
        found.append((m.group(1), line.rstrip(' \t\r')))
    return found, lines[len(found):]


def _merge_leading_markers(live_body, new_body):
    """Re-insert into `new_body` any leading marker `live_body` carries.

    Returns `(body, reinserted_kinds)`. When anything is re-inserted the live
    body's ORDER governs the result (the run key stays line 1) and the caller's
    line wins for any kind it supplied — its FIRST line of that kind, so a
    composed body carrying one kind twice inside the scan window keeps the copy
    at the contracted position — so a same-kind re-stamp still lands;
    a kind only the caller supplied is appended once after the live ones, its
    first line winning exactly as a live kind's does. When the
    caller supplied every live kind nothing is re-inserted and its own body —
    and its own order — is returned untouched. The consequence a caller must
    know: this can CHANGE a leading marker of a kind the live body already
    carries, but never REMOVE one it holds, so a deliberate removal, and a
    migration that changes a marker's KIND, go through a different write path.
    A same-kind marker the CALLER placed out of position — behind a blank line
    rather than at line 1 — is dropped rather than duplicated.

    `scripts/post-review-verdict.sh`'s `_prv_stamp_progress` writes the stamp
    this preserves. The two agree only on the POSITIONS — run key line 1, verdict
    line 2 — and their matching and precedence rules differ, so a change to
    either position must be made in both.
    """
    live, _ = _leading_markers(live_body)
    if not live:
        return new_body, []
    supplied, tail = _leading_markers(new_body)
    # Reversed, so the FIRST supplied line of a repeated kind is the one that
    # survives: a plain `dict(supplied)` would let a line-2 copy displace the
    # line-1 one the caller placed at the contracted position.
    by_kind = {kind: line for kind, line in reversed(supplied)}
    reinserted = [kind for kind, _ in live if kind not in by_kind]
    if not reinserted:
        return new_body, []
    live_kinds = {kind for kind, _ in live}
    merged = [by_kind.get(kind, line) for kind, line in live]
    # `by_kind` resolves the first-wins rule only for kinds the LIVE body also
    # carries; a supplied-only kind is appended from `supplied` directly, so
    # filtering on the kind alone would append a caller's duplicate twice.
    # Emitting each supplied-only kind once keeps the rule uniform across both.
    seen_supplied = set()
    for kind, line in supplied:
        if kind in live_kinds or kind in seen_supplied:
            continue
        seen_supplied.add(kind)
        merged.append(line)
    merged_kinds = {kind for kind, _ in live} | {kind for kind, _ in supplied}
    # A composed body whose marker does not begin at line 1 — a blank line or a
    # heading ahead of it — leaves `supplied` empty, so its own copies would ride
    # along in the tail beside the ones just prepended. Drop a marker line of an
    # already-merged kind from the tail's leading run, stopping at the first line
    # that is neither blank nor such a marker so no ordinary content is touched.
    kept_tail, dropping = [], True
    for line in tail:
        if dropping:
            m = _LEADING_MARKER_RE.match(line)
            if m and m.group(1) in merged_kinds:
                continue
            if line.strip() == '':
                kept_tail.append(line)
                continue
            dropping = False
        kept_tail.append(line)
    # A live body carrying two markers of one kind re-inserts that kind twice;
    # the breadcrumb names each kind once.
    return '\n'.join(merged + kept_tail), sorted(set(reinserted))


def _patch_comment_body(repo, comment_id, text=None, *, body_path=None):
    """PATCH a comment's body from `text` or from `body_path`; return the response.

    A `text` payload is staged into a private temp file, never a sibling of the
    caller's path, because that directory may be read-only and a sibling would be
    visible to a `git add` scoped to it. Passing `body_path` PATCHes that file
    directly, so an unchanged body needs no writable temp directory at all.
    """
    staged = None
    if body_path is None:
        if text is None:
            raise ValueError('_patch_comment_body: pass text= or body_path=')
        _check_body_within_limit(_byte_len(text))
        tf = tempfile.NamedTemporaryFile(
            'w', suffix='.md', delete=False, encoding='utf-8')
        staged = Path(tf.name)
        try:
            with tf:
                tf.write(text)
        except OSError:
            staged.unlink(missing_ok=True)
            raise
        body_path = staged
    else:
        # Measure the file `cmd_patch` PATCHes directly (never staged from
        # `text`): checking `text` alone here would let this branch issue an
        # oversize PATCH. st_size is the byte count GitHub receives.
        _check_body_within_limit(Path(body_path).stat().st_size)
    try:
        return _run([
            GH, 'api', '-X', 'PATCH',
            f'/repos/{repo}/issues/comments/{comment_id}',
            '-F', f'body=@{body_path}',
            '--jq', '.body',
        ]).stdout
    finally:
        if staged is not None:
            try:
                staged.unlink()
            except OSError:
                pass


def cmd_patch(args):
    repo = _repo_full()
    body_path = Path(args.body_file)
    if not body_path.is_file():
        sys.stderr.write(
            f"workpad.py patch: body file not found: {body_path}\n"
        )
        sys.exit(1)
    try:
        composed = body_path.read_text(encoding='utf-8')
    except OSError as e:
        sys.stderr.write(f"workpad.py patch: body file unreadable: {e}\n")
        sys.exit(1)
    # A body the read could not establish is UNESTABLISHED, not "this comment has
    # no markers": `gh` can emit an error envelope carrying no `.body` key while
    # exiting 0, and reading that as an empty live body would silently restore
    # the clobber this preservation exists to prevent. Presence is decided by the
    # raw object's key, never by `--jq .body`, whose `null` rendering cannot
    # express it.
    live, live_read_failed = '', None
    try:
        live, established = _comment_body_established(repo, args.comment_id)
        if not established:
            live = ''
            live_read_failed = 'the read returned no body (an error envelope at exit 0?)'
    except (subprocess.CalledProcessError, OSError) as e:
        live_read_failed = getattr(e, 'stderr', None) or e
        if isinstance(live_read_failed, bytes):
            live_read_failed = live_read_failed.decode('utf-8', 'replace')
        if isinstance(live_read_failed, str):
            live_read_failed = live_read_failed.strip()
        live = ''
    if live_read_failed is not None:
        # Whether that unknown costs anything is decidable: a composed body that
        # carries its own leading marker is already safe, so degrade. One that
        # does not would drop a marker the comment may hold, unrecoverably and
        # with nothing downstream able to tell — so refuse instead.
        if _leading_markers(composed)[0]:
            sys.stderr.write(
                'workpad.py patch: could not establish the live body of comment '
                f'{args.comment_id} ({live_read_failed}); patching the composed '
                'body as typed — only the marker(s) it carries are preserved, and '
                'any OTHER leading marker this comment holds is dropped\n'
            )
        else:
            sys.stderr.write(
                'workpad.py patch: could not establish the live body of comment '
                f'{args.comment_id} ({live_read_failed}) and the composed body '
                'carries no leading marker, so a marker this comment may hold '
                'would be dropped unrecoverably; refusing the PATCH. Retry, or '
                're-author the body with its marker as line 1.\n'
            )
            sys.exit(1)
    merged, reinserted = _merge_leading_markers(live, composed)
    if reinserted:
        sys.stderr.write(
            'workpad.py patch: re-inserted leading marker(s) the composed body '
            f'omitted: {", ".join(reinserted)}\n'
        )
    try:
        if reinserted:
            out = _patch_comment_body(repo, args.comment_id, merged)
        else:
            out = _patch_comment_body(repo, args.comment_id, body_path=body_path)
    except _UpdateError as e:
        # A size refusal is pre-PATCH, not a transport error — so it is handled
        # here rather than by the CalledProcessError/OSError arm below.
        sys.stderr.write(f"workpad.py patch: {e}\n")
        sys.exit(1)
    except (subprocess.CalledProcessError, OSError) as e:
        _fail('patch', e)
    sys.stdout.write(out)


_COMMENT_URL_RE = re.compile(r'#issuecomment-(\d+)\s*$')


def cmd_create(args):
    body_path = Path(args.body_file)
    if not body_path.is_file():
        sys.stderr.write(
            f"workpad.py create: body file not found: {body_path}\n"
        )
        sys.exit(1)
    try:
        r = _run([
            GH, 'issue', 'comment', str(args.issue),
            '--body-file', str(body_path),
        ])
    except (subprocess.CalledProcessError, OSError) as e:
        _fail('create', e)
    m = _COMMENT_URL_RE.search(r.stdout)
    if m:
        print(m.group(1))
        return
    # `gh issue comment` is documented to print the new comment URL. If the
    # URL is missing (gh output-format change, transient stderr-only output,
    # ...) the comment may already have been posted on GitHub, so falling
    # back to a fresh marker scan would risk picking up an unrelated workpad
    # and silently masking the failure. Fail loud instead — the caller can
    # re-run after inspecting the issue manually.
    sys.stderr.write(
        "workpad.py create: gh did not print a comment URL; the workpad "
        "may or may not have been posted. Inspect the issue manually before "
        "retrying. Raw stdout:\n"
    )
    sys.stderr.write(r.stdout)
    sys.exit(1)


def cmd_now(_args):
    now = datetime.datetime.now(datetime.timezone.utc)
    print(now.strftime('%Y-%m-%dT%H:%M:%SZ'))


# The un-mirrored `## Acceptance Criteria` placeholder — the SINGLE SOURCE seeded by
# `cmd_new_body`'s template below AND matched by the terminal Complete gate. Keeping
# both the producer and the guard on this one constant means a reword (e.g. the ASCII
# vs em-dash trap) can never silently drift them apart and disarm the gate's warning.
# If it survives to a terminal `--status Complete` write, Phase 1.2/1.3 AC-mirroring
# never ran, so the gate's checkbox scan has nothing to check — the "self-record
# matches reality" guarantee would be vacuously satisfied. The gate warns (non-blocking)
# on this exact placeholder; a genuinely AC-less issue carries the DISTINCT sentinel
# `_(none provided in issue body)_` parse-acs.py emits, so no warning fires there.
_AC_PENDING_PLACEHOLDER = '_(pending — mirrored from the issue when the run begins)_'

# ---------------------------------------------------------------------------
# Scope-decision records (issue #781)
# ---------------------------------------------------------------------------
# A delimited, machine-readable record of every /devflow:implement decision that
# changes the workpad `## Acceptance Criteria` set's MEMBERSHIP or a criterion's
# TEXT. Three writers emit one: Phase 2.2.5's `--replace-acs-file` narrowing
# (`deferred`), Phase 2.2.6's `--rewrite-ac` (`rewritten`), and Phase 3.4's
# retroactive `(post-merge)` retag (`rewritten`). The review engine's Phase 0.4
# reads them to tell an AUDITED narrowing from an unexplained one, and to
# confirm the section belongs to the PR under review.
#
# It is written as an ordinary `## Progress` note, so it rides the existing
# note-append path (no new section machinery) and sits entirely before
# `## Devflow Reflection` — `lib/fetch-pr-context.sh`'s reflection parse
# therefore never sees it.
#
# The criterion text is base64-encoded so a criterion containing `-->`, a
# newline, or any delimiter this grammar uses cannot break the record or forge a
# second one. `pr=` accepts the literal `pending` because Phase 2.2.5/2.2.6 run
# BEFORE Phase 3.1 opens the draft PR: they write `pending` and Phase 3.1 binds
# every pending record to the real number with `--bind-scope-decisions`. A
# record still reading `pending` at review time deliberately covers NOTHING —
# fail closed, so an unbound record can never vacuously satisfy the membership
# check it exists to gate.
_SCOPE_DECISION_KINDS = ('deferred', 'rewritten')
# The one kind whose work was punted rather than reworded — the only kind the
# issue-#815 deferred-presence predicate counts. Named from the tuple rather than
# re-spelled so it cannot survive a rename of the value it selects.
_SCOPE_DECISION_DEFERRED_KIND = _SCOPE_DECISION_KINDS[0]
_SCOPE_DECISION_PENDING_PR = 'pending'
# The kind alternation is BUILT from `_SCOPE_DECISION_KINDS` rather than
# re-spelled, so the constant is the single place a new kind is added — a
# re-spelled alternation would silently keep matching only the old two.
_SCOPE_DECISION_RE = re.compile(
    _MARKER_NS_RE + r'scope-decision pr=(\d+|' + _SCOPE_DECISION_PENDING_PR + r') '
    r'kind=(' + '|'.join(_SCOPE_DECISION_KINDS) + r') '
    r'text=([A-Za-z0-9+/=]*)(?: newtext=([A-Za-z0-9+/=]*))? -->'
)


def _b64(text: str) -> str:
    return base64.b64encode(text.encode('utf-8')).decode('ascii')


def _unb64(blob: str, record: str = 'scope-decision') -> str | None:
    """Decode a record's payload, or None when it is not decodable UTF-8.

    Returns None rather than raising or falling back to the raw blob: a record
    whose payload cannot be read is an UNESTABLISHED comparand, and the caller
    drops it so it covers nothing (the same fail-closed direction the `pending`
    PR value takes). Silently substituting the undecodable bytes would let a
    corrupted record match no criterion while still counting as "a record
    exists", which is exactly the vacuous-coverage shape the guard forbids.
    """
    try:
        return base64.b64decode(blob.encode('ascii'), validate=True).decode('utf-8')
    except (ValueError, UnicodeDecodeError) as e:
        # Breadcrumb naming the specific payload that failed, so a corrupted
        # record reads as a corrupted record rather than as an audited decision
        # that silently stopped covering its criterion.
        sys.stderr.write(
            f"workpad.py: ignoring a {record} record whose payload is not "
            f"decodable UTF-8 base64 ({e}); it covers no criterion\n"
        )
        return None


def _warn_empty_scope_payload(field: str, record: str = 'scope-decision') -> None:
    # Same breadcrumb discipline as `_unb64`'s undecodable path: an empty payload
    # is a corrupted record, and it must read as one rather than as an audited
    # decision that silently stopped covering its criterion.
    sys.stderr.write(
        f"workpad.py: ignoring a {record} record whose {field}= payload is "
        f"empty; it covers no criterion\n"
    )


def _decode_scope_payload(blob: str, field: str, record: str = 'scope-decision') -> str | None:
    """Decode one record payload, or None when it establishes no criterion.

    The single decode step every scope-decision reader shares: undecodable
    base64 and a payload that decodes to the empty string are both records that
    name no criterion and can therefore cover none, and each leaves its own
    breadcrumb. Callers differ only in what they do with the None — drop it
    (`_parse_scope_decisions`) or count it as corrupted
    (`_bound_deferred_records`) — so only that decision is theirs to make.
    """
    text = _unb64(blob, record)
    if text is None:
        return None
    if not text:
        _warn_empty_scope_payload(field, record)
        return None
    return text


def _render_scope_decision(pr: str, kind: str, text: str, new_text: str | None = None) -> str:
    rec = (f'<!-- prflow:scope-decision pr={pr} kind={kind} '
           f'text={_b64(normalize_criterion(text))}')
    if new_text is not None:
        rec += f' newtext={_b64(normalize_criterion(new_text))}'
    return rec + ' -->'


def _parse_scope_decisions(body: str, pr: int | None) -> list[dict]:
    """Return the scope-decision records in `body` that bind to PR `pr`.

    A record whose `pr=` is `pending` (never bound by Phase 3.1) or names a
    DIFFERENT PR is excluded, as is one whose base64 payload does not decode, as
    is one whose payload decodes to the EMPTY string. The regex's payload class
    is `*`-quantified, so a truncated or hand-edited `text=` (or `newtext=`)
    matches and decodes cleanly to `''` — a record that names no criterion and
    can therefore cover none, so it is dropped in the undecodable case's same
    fail-closed direction. All of these establish nothing about this PR, and the
    membership check treats "no covering record" as a finding.

    `pr` is None in current-branch mode, where there is no PR to bind to: no
    record can be confirmed as this run's, so none is returned and the guard
    fails closed rather than crediting a record it cannot attribute.
    """
    out = []
    if pr is None:
        return out
    for m in _SCOPE_DECISION_RE.finditer(body):
        rec_pr, kind, blob, new_blob = m.group(1), m.group(2), m.group(3), m.group(4)
        if rec_pr == _SCOPE_DECISION_PENDING_PR or int(rec_pr) != pr:
            continue
        text = _decode_scope_payload(blob, 'text')
        if text is None:
            continue
        new_text = None
        if new_blob is not None:
            new_text = _decode_scope_payload(new_blob, 'newtext')
            if new_text is None:
                continue
        out.append({'kind': kind, 'text': text, 'new_text': new_text})
    return out


def _bind_scope_decisions(body: str, pr: int) -> str:
    """Rewrite every `pr=pending` scope-decision record to `pr=<pr>`.

    Idempotent WITHIN a run: a record already carrying a numeric PR is left
    untouched, so a re-run (or a resumed run re-entering Phase 3.1) never
    re-binds a record to a different PR.

    KNOWN LIMITATION — that idempotence argument covers re-entry only, NOT
    cross-run contamination. The workpad is one comment per ISSUE and survives
    across runs, so an earlier /devflow:implement attempt that wrote
    §2.2.5/§2.2.6 records and then died before reaching §3.1 leaves `pr=pending`
    records behind; this rewrite is unconditional over the whole body, so the
    NEXT run's §3.1 adopts those foreign records and binds them to ITS PR. The
    record format carries no run stamp to tell them apart, and inventing one is
    a larger design change than this function should make. The residual is made
    OBSERVABLE instead: the number of records bound is written to stderr, so a
    count higher than the run itself recorded is visible in the log rather than
    silent.
    """
    bound = 0

    def _sub(m):
        nonlocal bound
        bound += 1
        return f'{m.group(1)}{pr}{m.group(2)}'

    out = re.sub(
        r'(' + _MARKER_NS_RE + r'scope-decision pr=)pending( kind=)',
        _sub,
        body,
    )
    if bound:
        sys.stderr.write(
            f"workpad.py: bound {bound} pending scope-decision record(s) to pr={pr}; "
            f"a count higher than this run recorded means records left by an "
            f"earlier run on this issue were adopted\n"
        )
    return out


# ---------------------------------------------------------------------------
# Issue #815 — the bounded deferred-AC presence predicate.
#
# Phase 4 gates the LOAD of `skills/implement/references/deferred-ac-followups.md`
# on `deferred-presence`'s exit code, so this reader decides whether a run that
# deferred acceptance criteria ever files a follow-up issue for them. Two
# properties follow from that, and both are load-bearing:
#
#   * It is BOUNDED. A workpad at Phase 4 runs to tens of thousands of
#     characters — larger than the procedure being gated — so the answer is one
#     count line plus, on the outstanding arm, one normalized criterion per
#     outstanding record. The body is never printed.
#   * It is decided in PYTHON, over the module-level `_SCOPE_DECISION_RE` this
#     file already owns. `lib/preflight.sh` guarantees no `grep`/`tr`/`sed`, and
#     a predicate derived through one of those fails OPEN where the tool is
#     absent: the pipeline yields empty, the run reads "nothing was deferred",
#     and the deferred work is stranded with no follow-up and no reflection.
#
# The filed marker is its OWN comment marker, and the scope-decision grammar is
# left byte-untouched. That grammar is closed and load-bearing: its regex
# terminates at a literal ` -->` and its `kind=` alternation is built from
# `_SCOPE_DECISION_KINDS`, so an added `filed=` field stops the record matching
# at all and a `kind=filed` value matches nothing without widening that
# constant — and `_parse_scope_decisions` feeds `acs-resolve`, which the
# MERGE-GATING reviewer reads, so a record that stops parsing turns a deferred
# criterion into an unexplained dropped one in front of the gate that decides
# the merge.
_DEFERRED_FILED_RE = re.compile(
    _MARKER_NS_RE + r'deferred-filed text=([A-Za-z0-9+/=]*) -->')

# A `## Progress` bullet as `_append_progress_note` renders it: `  - HH:MM:SS — <text>`
# nested, or the same flat. The prefix is a module constant so the READERS of this wire
# format share one spelling (`_PROGRESS_BULLET_RE` and `_CLASSIFICATION_NOTE_RE`). The
# writer in `_append_progress_note` still spells the format independently, as an f-string
# it cannot build from a regex — so a change to the separator or the timestamp width must
# be made there too. The capture is the bullet's note text; see
# `_isolated_progress_markers` for why the readers need it isolated.
_PROGRESS_BULLET_PREFIX_RE = r'^[ \t]*[-*][ \t]+\d{2}:\d{2}:\d{2}[ \t]+—[ \t]+'
_PROGRESS_BULLET_RE = re.compile(_PROGRESS_BULLET_PREFIX_RE + r'(.*)$')


def _render_deferred_filed(normalized_text: str) -> str:
    """Render the filed marker for one discharged deferred criterion.

    `normalized_text` MUST be a `criterion:` line `deferred-presence` printed,
    verbatim: that string is already `normalize_criterion`'s output (it came
    back out of the record's own `text=` payload), so re-normalizing here would
    be a second pass over an already-normalized value, and re-typing it by hand
    would key the marker on a string no record carries.
    """
    return f'<!-- prflow:deferred-filed text={_b64(normalized_text)} -->'


def _single_section_content(
    sections: list[tuple[str, str]], name: str
) -> str | None:
    """The content of the ONE section headed `## {name}`, or None when the body
    presents zero or more than one of it.

    The exactly-one rule is the load-bearing half: `_find_section` answers with
    the FIRST match, so a duplicated section would otherwise read as a clean
    single one and a reader built on it would silently speak for only half the
    body. The heading compare matches `_find_section`'s — case-insensitive over
    the whitespace-stripped heading line.
    """
    target = f'## {name}'.lower()
    hits = [c for h, c in sections if h.strip().lower() == target]
    return hits[0] if len(hits) == 1 else None


def _progress_content_or_none(body: str) -> str | None:
    """The single canonical `## Progress` section's content, or None.

    None means the section is absent or duplicated. The workpad is
    agent-mutable markdown, so both shapes are read as *unestablished* by the
    caller rather than as an empty record set: records are written only into
    this section, so a body that does not present exactly one of it is one this
    reader cannot speak for — and answering a confident zero there is the
    stranding failure the three-state contract exists to avoid.
    """
    _, sections = _split_sections(body)
    return _single_section_content(sections, 'Progress')


def _isolated_progress_markers(content: str, pattern: 're.Pattern[str]'):
    """Yield one match of `pattern` per `## Progress` bullet whose note text is
    ENTIRELY that marker.

    `content` is the already-resolved `## Progress` section
    (`_progress_content_or_none`), passed in rather than re-derived so one
    invocation splits the body once instead of once per reader.

    This isolation is **reader-local**, not a property of the record format:
    `_parse_scope_decisions` — the older, merge-gate-facing reader that feeds
    `acs-resolve` — still scans the whole body with `finditer`, deliberately
    unchanged here so this change cannot move what the merge gate sees. So the
    guarantees below describe what THIS reader accepts, not what any reader of
    the grammar accepts.

    Two restrictions, and each closes a distinct half of the same injection
    shape. Records are written only through the note-append path, so they land
    in `## Progress` as their own isolated bullet — which means (a) scoping the
    scan to that section makes a marker-shaped literal in the mirrored
    `## Acceptance Criteria` or in a `## Devflow Reflection` bullet invisible,
    and (b) requiring a `fullmatch` of the bullet's note text makes a marker
    embedded inside free-text note prose invisible too. Those three regions
    store their text unencoded, so they are the reachable injection surface; a
    criterion's own text is not, because the payload is base64-encoded before
    storage.

    Residual, stated rather than silently assumed: a free-text note whose text
    is *nothing but* a byte-identical marker is indistinguishable from a
    writer-produced record. Separating them would need a provenance channel the
    record format does not carry — the same class of known limitation
    `_bind_scope_decisions` documents for cross-run contamination.
    """
    for line in content.split('\n'):
        bullet = _PROGRESS_BULLET_RE.match(line)
        if bullet is None:
            continue
        m = pattern.fullmatch(bullet.group(1).strip())
        if m is not None:
            yield m


def _whole_body_deferred_count(body: str) -> int:
    """Count `kind=deferred` records the WHOLE-BODY reader sees.

    `_parse_scope_decisions` — the merge-gate-facing reader behind `acs-resolve`
    — scans the whole body with `finditer`, while `_bound_deferred_records`
    below reads only isolated `## Progress` bullets. That narrowing is the
    injection defense, but it is also a way for a record to be visible to the
    merge gate and invisible here: a body re-rendered by `patch`, a bullet whose
    timestamp prefix did not survive an edit, a record under a differently-titled
    heading. Without this comparand the difference would come out as a confident
    `not-outstanding: 0` — the stranding direction, and precisely the confident
    zero the three-state contract exists to refuse.
    """
    return sum(1 for m in _SCOPE_DECISION_RE.finditer(body)
               if m.group(2) == _SCOPE_DECISION_DEFERRED_KIND)


def _bound_deferred_records(content: str, pr: int) -> tuple[list[str], int, int]:
    """Return `(bound_texts, unbound_count, corrupted_count)` for `pr`.

    `bound_texts` holds the normalized criterion of every `kind=deferred`
    record bound to `pr` whose payload decoded to non-empty text.
    `unbound_count` counts the `kind=deferred` records that do NOT bind to `pr`
    — `pr=pending` (Phase 3.1's binding step never ran) and a superseded PR
    number alike. `corrupted_count` counts the bound records whose `text=`
    payload is undecodable base64 or decodes to the empty string.

    The two counts exist because a PR-keyed count alone would answer a
    confident ZERO for a workpad whose deferred records are still `pending` or
    are bound to a superseded PR — and a confident zero is not an unavailable
    operand, so the caller's fail-open arm would never fire and the deferred
    work would be stranded with no reflection at all.

    `kind=rewritten` records enter none of the three buckets: they record a
    criterion whose text changed, not one whose work was punted, so no path
    files a follow-up for one.
    """
    bound_texts: list[str] = []
    unbound_count = 0
    corrupted_count = 0
    pr_str = str(pr)
    for m in _isolated_progress_markers(content, _SCOPE_DECISION_RE):
        rec_pr, kind, blob = m.group(1), m.group(2), m.group(3)
        if kind != _SCOPE_DECISION_DEFERRED_KIND:
            continue
        if rec_pr == _SCOPE_DECISION_PENDING_PR or rec_pr != pr_str:
            unbound_count += 1
            continue
        text = _decode_scope_payload(blob, 'text')
        if text is None:
            corrupted_count += 1
            continue
        bound_texts.append(text)
    return bound_texts, unbound_count, corrupted_count


def _filed_criteria(content: str) -> set[str]:
    """Normalized criterion text of every deferred criterion already filed.

    Read under the same section-scoped, whole-bullet-only discipline as
    `_bound_deferred_records`, so an injected filed-marker literal cannot
    discharge a real deferral.
    """
    filed: set[str] = set()
    for m in _isolated_progress_markers(content, _DEFERRED_FILED_RE):
        text = _decode_scope_payload(m.group(1), 'text', 'deferred-filed')
        if text is not None:
            filed.add(text)
    return filed


def _print_unestablished(reason: str, unbound: int = 0, corrupted: int = 0,
                         filed: 'set[str] | None' = None):
    """Print the single `unestablished` count line and exit 2.

    One home for the line's format so no arm that reaches it can drift into a
    different shape of the same contract — the stub literal-matches
    the `reason=` token, so a divergent arm is a routing decision the reader
    cannot make.

    `filed` carries the criteria a `prflow:deferred-filed` marker has already
    discharged, printed one per `filed:` line. Without it the unestablished arm
    would be a duplicate-filing hole: it exits before the outstanding set is
    computed, so a workpad whose records never got bound (Phase 3.1's binding
    PATCH is best-effort) answers `unestablished` on EVERY fresh Phase 4 entry,
    and an agent with no filed operand re-files what a prior entry already
    filed. The arms that could not resolve the `## Progress` section pass None
    and print no `filed:` line — there the operand genuinely does not exist.
    """
    print(f'unestablished: reason={reason} unbound={unbound} corrupted={corrupted}')
    for text in sorted(filed or ()):
        print(f'filed: {text}')
    sys.exit(2)


def cmd_deferred_presence(args):
    """Answer, boundedly, whether this run has unfiled deferred criteria.

    Exit codes follow `grep(1)`'s 0-match / 1-no-match / 2-error idiom rather
    than reusing `id`'s or `status`'s own conventions, which were designed for
    unrelated questions and would read confusingly here:

      0  outstanding      — at least one `kind=deferred` record bound to this
                            run's PR carries no filed marker. Phase 4 reads the
                            reference and files.
      1  not outstanding  — every such record carries one (or there are none).
                            Phase 4 skips the reference.
      2  unestablished    — the answer could not be settled. Phase 4 reads the
                            reference anyway and records a `note` reflection,
                            because reading an unavailable operand as "nothing
                            was deferred" silently strands deferred work while
                            a needless load costs one read the reference's own
                            skip sentence absorbs.

    Exactly one bounded count line goes to stdout — followed, on the arms that
    resolved the `## Progress` section, by one `filed:` line per already-filed
    criterion so an unestablished answer cannot become a duplicate-filing hole —
    and the `unestablished` line names WHICH operand failed — so a run that never resolved its PR number is
    distinguishable from a workpad-read failure in the reflection Phase 4
    records. The workpad body is never printed. (`argparse`'s own usage exit is
    also 2, which routes a malformed invocation to the same fail-closed arm.)
    """
    marker = _workpad_marker(args.marker)
    c = _find_workpad_comment(
        'deferred-presence', _repo_full(api_fail_code=2), args.issue, marker,
        api_fail_code=2,
    )
    if c is None:
        sys.stderr.write(
            f"workpad.py deferred-presence: no workpad comment carrying {marker!r} "
            f"on issue #{args.issue}; whether Phase 2.2.5 deferred any acceptance "
            f"criterion could not be established\n"
        )
        _print_unestablished('workpad-unresolved')
    # Resolve the section ONCE and hand it to both readers: the body runs to tens
    # of thousands of characters at Phase 4, and re-deriving it per reader would
    # re-split the whole thing for an answer that cannot change mid-invocation.
    body = c.get('body') or ''
    content = _progress_content_or_none(body)
    if content is None:
        sys.stderr.write(
            "workpad.py deferred-presence: the workpad does not carry exactly one "
            "'## Progress' section (absent or duplicated); scope-decision records are "
            "written only there, so whether any deferred criterion is outstanding "
            "could not be established\n"
        )
        _print_unestablished('progress-section-unreadable')
    bound, unbound, corrupted = _bound_deferred_records(content, args.pr)
    # The isolated-bullet reader must see every record the whole-body reader does.
    # When it sees fewer, some record is visible to `acs-resolve` and invisible
    # here, and the two readers would disagree in the stranding direction.
    seen = len(bound) + unbound + corrupted
    whole = _whole_body_deferred_count(body)
    if whole > seen:
        sys.stderr.write(
            f"workpad.py deferred-presence: the whole-body scan finds {whole} kind=deferred "
            f"record(s) but only {seen} sit in an isolated '## Progress' bullet; the "
            f"difference is visible to acs-resolve and invisible here, so whether any "
            f"deferred criterion is outstanding could not be established\n"
        )
        _print_unestablished('reader-divergence', unbound, corrupted,
                             _filed_criteria(content))
    if unbound or corrupted:
        # Corrupted is reported first when both are present: a record bound to
        # this PR that cannot be read is the more specific failure, and naming
        # the vaguer one would send a reader to the binding step over a payload
        # problem. Both counts print either way.
        _print_unestablished(
            'corrupted-records' if corrupted else 'unbound-records', unbound, corrupted,
            _filed_criteria(content))
    # A filed marker is keyed on the record's NORMALIZED text, and
    # `normalize_criterion` strips a trailing ` (post-merge)` tag and collapses
    # whitespace — so two genuinely distinct deferred criteria can share one key.
    # Discharging by set membership would then let one marker retire both, filing
    # a follow-up for only one of them. Refuse to answer rather than strand it.
    if len(set(bound)) != len(bound):
        sys.stderr.write(
            "workpad.py deferred-presence: two or more kind=deferred records bound to this "
            "PR share one normalized criterion text, so a filed marker cannot discharge them "
            "individually; whether any deferred criterion is outstanding could not be "
            "established\n"
        )
        _print_unestablished('ambiguous-criteria', unbound, corrupted,
                             _filed_criteria(content))
    filed = _filed_criteria(content)
    outstanding = [t for t in bound if t not in filed]
    if outstanding:
        print(f'outstanding: {len(outstanding)}')
        for text in outstanding:
            print(f'criterion: {text}')
        sys.exit(0)
    print(f'not-outstanding: {len(bound)}')
    sys.exit(1)


def cmd_resume_point(args):
    """Print this run's recorded mid-phase re-anchor resume point (issue #1876).

    A NAVIGATION aid, never evidence: this reader is wired into no verdict/gate, so a
    self-reported resume point can never reach a verification decision (issue #1489).
    Exit codes follow `grep(1)`'s idiom, matching `deferred-presence`:

      0  a resume point is on record — its decoded text is the sole stdout line.
      1  no resume point is recorded (none written, or the marker is malformed and
         reads as absent) — nothing is printed on stdout.
      2  unestablished — the workpad or its single `## Progress` section could not be
         read (stderr names which); the caller re-reads the full phase set rather than
         trusting an unread record. (argparse's own usage exit is also 2.)

    The workpad body itself is never printed."""
    marker = _workpad_marker(args.marker)
    c = _find_workpad_comment(
        'resume-point', _repo_full(api_fail_code=2), args.issue, marker,
        api_fail_code=2,
    )
    if c is None:
        sys.stderr.write(
            f"workpad.py resume-point: no workpad comment carrying {marker!r} on "
            f"issue #{args.issue}; the mid-phase resume point could not be established\n"
        )
        sys.exit(2)
    content = _progress_content_or_none(c.get('body') or '')
    if content is None:
        sys.stderr.write(
            "workpad.py resume-point: the workpad does not carry exactly one "
            "'## Progress' section (absent or duplicated); the mid-phase resume "
            "point could not be established\n"
        )
        sys.exit(2)
    # The producer strips the prior row and appends the new one, so at most one row
    # survives; take the last decodable payload so a replay reads back the later one,
    # and a malformed marker (undecodable) drops to absent rather than raising.
    texts = [t for t in (_decode_resume_point(p)
                         for p in _resume_point_marker_payloads(content)) if t is not None]
    if not texts:
        sys.exit(1)
    print(texts[-1])
    sys.exit(0)


# Issue #1513 — the deferred-REFLECTION backing audit: a `--reflection-kind
# deferred` bullet reads as a tracked deferral but files nothing, so this reader
# and cmd_deferred_reflection_audit make an unbacked one detectable at Phase 4.
# The backing contract and the two-channel rationale are in the function
# docstrings below.
def _deferred_reflection_texts(sections: "list[tuple[str, str]]") -> "list[str] | None":
    """Trailing text of every rendered `deferred` reflection bullet, or None.

    Takes the already-split `sections` (from `_split_sections`) rather than the
    raw body, so the caller resolves both this section and `## Progress` from one
    split — the "resolve the section ONCE" discipline `cmd_deferred_presence`
    follows. None means the body does not present exactly one `## Devflow
    Reflection` section (absent or duplicated) — read as *unestablished* by the
    caller, the fail-closed direction `_progress_content_or_none` also takes,
    never as an empty set. The bullet shape is derived from
    `_REFLECTION_KINDS['deferred']` so this reader cannot drift from
    `_insert_reflection_bullet`'s writer; the exact-prefix match keeps a
    marker-shaped literal quoted inside other prose from counting.
    """
    content = _single_section_content(sections, 'Devflow Reflection')
    if content is None:
        return None
    glyph, label, _sub = _REFLECTION_KINDS['deferred']
    prefix = f'- {glyph} **{label}:** '
    texts: list[str] = []
    for line in content.split('\n'):
        stripped = line.strip()
        if stripped.startswith(prefix):
            texts.append(stripped[len(prefix):])
    return texts


def cmd_deferred_reflection_audit(args):
    """Audit whether every `deferred`-kind reflection this run recorded is backed
    by a scope-decision-deferred record bound to this run's PR (issue #1513).

    grep(1)-style three-state exit (0/1/2), the same shape `cmd_deferred_presence`
    uses — but the polarity is inverted from that sibling: here 0 is the CLEAN
    state (backed) and 1 the problem state (unbacked), whereas there 0 is the
    act-now state (outstanding):

      0  backed        — the deferred-reflection count does not exceed the count
                        of `kind=deferred` scope-decision records bound to this
                        PR (the zero-reflection case included). Phase 4 continues.
      1  unbacked      — more `deferred` reflections than bound records: at least
                        one renders as an actionable deferral no channel filed.
                        Prints `unbacked: <n>` (the excess) then one `text:` line
                        per deferred reflection. Phase 4.0.6 surfaces it.
      2  unestablished — the backing count could not be settled: the fail-closed
                        causes this shares with `deferred-presence` — `workpad-unresolved`,
                        `progress-section-unreadable`, `reader-divergence`, and an
                        `unbound`/`corrupted` record — plus `reflection-section-unreadable`
                        (`ambiguous-criteria` does not apply: a count comparison is
                        indifferent to two records sharing one normalized text). Phase 4
                        records a note; never read as "nothing unbacked".

    The backing comparand is the count of scope-decision records bound to this
    PR. An unbound/corrupted/reader-divergent record makes that count unreliable,
    so those route to *unestablished* — never to a false `unbacked`. Only one
    bounded count line goes to stdout; the body is never printed.

    Known residual: `backed` is a count floor, not a per-reflection identity
    match — a reflection carries no join key to a record's criterion, so N
    reflections beside N records tracking unrelated criteria read as `backed`.
    The routing rule (a `deferred` reflection is used only for a
    scope-decision-backed punt) is the compensating control.

    The scope-decision record is the only channel a `deferred` reflection pairs
    with, so the review-and-fix deferrals manifest (Channel 2) is deliberately
    NOT folded into the backing count: the fix loop records `dropped-failed`,
    never `deferred`, for its punts (phase-3-fix-loop.md), and the routing rule
    does not name the manifest as backing for `deferred` — folding it in without
    re-establishing those invariants would let a future Channel-2 `deferred`
    producer escape this audit.
    """
    marker = _workpad_marker(args.marker)
    c = _find_workpad_comment(
        'deferred-reflection-audit', _repo_full(api_fail_code=2), args.issue, marker,
        api_fail_code=2,
    )
    if c is None:
        sys.stderr.write(
            f"workpad.py deferred-reflection-audit: no workpad comment carrying {marker!r} "
            f"on issue #{args.issue}; whether any deferred reflection is unbacked could not "
            f"be established\n"
        )
        _print_unestablished('workpad-unresolved')
    body = c.get('body') or ''
    # Resolve the body into sections ONCE and read both the reflection section and
    # ## Progress from it, matching cmd_deferred_presence's "resolve the section ONCE"
    # discipline — the body runs to tens of KB at Phase 4, so a per-reader re-split
    # would scan it twice for a result that cannot change mid-invocation.
    _, sections = _split_sections(body)
    reflections = _deferred_reflection_texts(sections)
    if reflections is None:
        sys.stderr.write(
            "workpad.py deferred-reflection-audit: the workpad does not carry exactly one "
            "'## Devflow Reflection' section (absent or duplicated), so whether any deferred "
            "reflection is unbacked could not be established\n"
        )
        _print_unestablished('reflection-section-unreadable')
    if not reflections:
        print('backed: 0')
        sys.exit(0)
    content = _single_section_content(sections, 'Progress')
    if content is None:
        sys.stderr.write(
            "workpad.py deferred-reflection-audit: the workpad does not carry exactly one "
            "'## Progress' section (absent or duplicated), so the backing scope-decision "
            "records could not be read\n"
        )
        _print_unestablished('progress-section-unreadable')
    bound, unbound, corrupted = _bound_deferred_records(content, args.pr)
    seen = len(bound) + unbound + corrupted
    whole = _whole_body_deferred_count(body)
    if whole > seen:
        sys.stderr.write(
            f"workpad.py deferred-reflection-audit: the whole-body scan finds {whole} "
            f"kind=deferred record(s) but only {seen} sit in an isolated '## Progress' "
            f"bullet, so the backing count could not be established\n"
        )
        _print_unestablished('reader-divergence', unbound, corrupted)
    if unbound or corrupted:
        _print_unestablished(
            'corrupted-records' if corrupted else 'unbound-records', unbound, corrupted)
    if len(reflections) > len(bound):
        print(f'unbacked: {len(reflections) - len(bound)}')
        for text in reflections:
            print(f'text: {text}')
        sys.exit(1)
    print(f'backed: {len(reflections)}')
    sys.exit(0)


# The bug-only "reproduction captured" ## Progress sub-row. SINGLE SOURCE for the
# row `cmd_new_body` renders AND the row `_reconcile_reproduction_row` (issue #449)
# adds/removes to match the recorded content classification — so the reconcile can
# never drift from the skeleton the gate/new-body seed. `_REPRODUCTION_ROW_SUBSTR`
# is the substring the reconcile matches an existing row by (tick-state- and
# marker-agnostic), so a future reword of the parenthetical never blinds detection.
_REPRODUCTION_ROW_TEXT = 'reproduction captured (bug issues only)'
_REPRODUCTION_ROW = f'  - [ ] {_REPRODUCTION_ROW_TEXT}'
_REPRODUCTION_ROW_SUBSTR = 'reproduction captured'


# One nested `## Progress` checkbox row per consumer prompt-extension surface an
# implement run consumes through a skill body's own load block (issue #1462).
# SINGLE SOURCE for the rows `cmd_new_body` renders AND the rows
# `_reconcile_extension_rows` repairs into a workpad created before they existed:
# each entry pairs the canonical row text with the stable substring both the tick
# and the reconciliation detect it by, on the `_REPRODUCTION_ROW_TEXT` /
# `_REPRODUCTION_ROW_SUBSTR` model, so a later reword of the text blinds neither.
#
# WORDING IS A HARD CONSTRAINT, not style. `_tick_checkbox` raises when more than
# one unticked row matches, so a row whose text contained a substring a live
# `--tick-progress` call passes would break that EXISTING tick rather than merely
# failing its own — `Documentation` and `review-and-fix` already label rows.
# `requesting-code-review` is deliberately absent: the dispatched final-pass
# reviewer already fetches it unconditionally under its own return contract.
#
# Each entry is `(phase, text, substr)`; `phase` names the top-level `## Progress`
# row the surface is reached under.
_EXTENSION_ROWS = (
    ('Setup', 'prompt extension resolved: implement',
     'extension resolved: implement'),
    ('Review', 'prompt extension resolved: review engine',
     'extension resolved: review engine'),
    ('Review', 'prompt extension resolved: fix loop',
     'extension resolved: fix loop'),
    ('Review', 'prompt extension resolved: code-review reception',
     'extension resolved: code-review reception'),
)


# Review-engine phase boundaries that an implement-driven fix loop records in
# the issue workpad instead of a second live PR comment (issue #1657). The first
# value is rendered text; the second is the stable, unique tick operand.
_REVIEW_PROGRESS_ROWS = (
    ('Classify diff (Phase 0.5)', 'Classify diff'),
    ('Generate verification checklist (Phase 1)',
     'Generate verification checklist'),
    ('Verify checklist (Phase 2)', 'Verify checklist'),
    ('Review agents (Phase 3)', 'Review agents'),
    ('Aggregate & verdict (Phase 4)', 'Aggregate & verdict'),
    ('Run complete — everything this run owed', 'Run complete'),
)


def _managed_progress_rows():
    """Rows hydrated by the existing Phase 1.3 reconciliation pass."""
    yield from _EXTENSION_ROWS
    for text, substr in _REVIEW_PROGRESS_ROWS:
        yield 'Review', text, substr


def _extension_rows_block(phase: str) -> str:
    """The rendered nested rows for one phase, newline-terminated (empty when the
    phase owns none), for splicing into the `cmd_new_body` template."""
    return ''.join(
        f'  - [ ] {text}\n' for row_phase, text, _ in _EXTENSION_ROWS
        if row_phase == phase
    )


def _review_progress_rows_block(phase: str) -> str:
    """The review engine's issue-workpad rows for their owning phase."""
    if phase != 'Review':
        return ''
    return ''.join(f'  - [ ] {text}\n' for text, _ in _REVIEW_PROGRESS_ROWS)


def cmd_new_body(args):
    """Print the lean initial workpad skeleton to stdout, for piping into a file
    and `create`. Deliberately minimal — only what's available before the run
    does any work: status, links, friendly timestamp, and the empty ## Progress
    checklist (with the run-started note nested under Setup). The Plan and
    Acceptance Criteria are placeholders the orchestrator fills once it begins
    (Phase 2.2 / Phase 1.2). Used by the `gate` job to post the acknowledgment
    before runtime provisioning, and by the local-tier fresh-issue path."""
    marker = _workpad_marker(args.marker)
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    last_updated = now_dt.strftime('%Y-%m-%d %H:%M UTC')
    seed_ts = now_dt.strftime('%H:%M:%S')
    branch = f'`{args.branch}`' if args.branch else '_(creating…)_'
    run = args.run_link or '_(local run)_'
    # The reproduction sub-item is bug-only. It renders by default so a
    # deterministic producer that cannot judge content (the `gate` job pre-renders
    # from the `bug` label) never drops it on a lookup failure; the local
    # fresh-issue path (Phase 1.3) passes --no-reproduction when the recorded
    # content classification is non-bug. Either way, Phase 1.3's
    # --reconcile-reproduction is the authoritative correction (issue #449) that
    # reconciles this row to the classification, so the default here is only a
    # starting point, not the final word.
    repro = (
        ''
        if getattr(args, 'no_reproduction', False)
        else _REPRODUCTION_ROW + '\n'
    )
    sys.stdout.write(f"""{marker}
# PRFlow Workpad — Issue #{args.issue}

**Status:** 🚀 Setup
**Branch:** {branch}
**Run:** {run}
**PR:** _not yet created_
**Last updated:** {last_updated}

## Progress
- [ ] **Setup** — branch & workpad
{_extension_rows_block('Setup')}  - {seed_ts} — /prflow:implement run started
- [ ] **Implement**
{repro}  - [ ] code + sweeps
- [ ] **Review**
{_extension_rows_block('Review')}{_review_progress_rows_block('Review')}  - [ ] `/simplify`
  - [ ] `review-and-fix`
  - [ ] acceptance-criteria gate
- [ ] **Documentation**
{_extension_rows_block('Documentation')}- [ ] **PR marked ready**

## Plan
- [ ] _(planning in progress)_

## Acceptance Criteria
{_AC_PENDING_PLACEHOLDER}

## Devflow Reflection
<details>
<summary>Devflow Reflection (click to expand)</summary>

</details>
""")


# ============================================================================
# update: high-level mutation entry point
# ============================================================================
#
# The workpad body is structured markdown. Earlier flows had the orchestrator
# rebuild the entire body string per-mutation, which led to drift (rewriting
# Decisions/Notes from scratch, missing Last updated, splicing into the wrong
# section, etc.). `update` accepts focused mutation flags, edits the live body
# in place, and PATCHes.
#
# Section model: the body has a fixed front-matter (Status / Branch / Last
# updated lines after the H1), then ## sections in a known order. We split the
# body into a header (everything up to and including the first blank line
# after the metadata block) and an ordered list of section blocks. Each
# section block is the heading line plus all lines until the next ## heading.

_STATUS_RE = re.compile(r'^\*\*Status:\*\*\s+.*$', re.MULTILINE)
_STATUS_VALUE_RE = re.compile(r'^\*\*Status:\*\*\s+(.*?)\s*$', re.MULTILINE)
_BRANCH_RE = re.compile(r'^\*\*Branch:\*\*\s+.*$', re.MULTILINE)
_RUN_RE = re.compile(r'^\*\*Run:\*\*\s+.*$', re.MULTILINE)
_PR_RE = re.compile(r'^\*\*PR:\*\*\s+.*$', re.MULTILINE)
_LAST_UPDATED_RE = re.compile(r'^\*\*Last updated:\*\*\s+.*$', re.MULTILINE)
_SECTION_RE = re.compile(r'^(##\s+.+)$', re.MULTILINE)
# Single source for the checkbox-row grammar shared by `_rewrite_checkbox` and
# `_tick_checkbox_by_index` (4 groups: 1=indent+bullet, 2=`[ xX]` state cell,
# 3=gap, 4=text). The state cell (group 2) is *preserved* by `_rewrite_checkbox`
# and *overwritten* with `[x]` by `_tick_checkbox_by_index` — the two writers index
# the same grammar differently, so keep the group order stable if you edit it.
# `_tick_checkbox` keeps its own `[ ]`-only variant because it filters to unticked
# rows. Hoisted to a constant so the row grammar can't drift between call sites.
_CHECKBOX_ROW_RE = re.compile(r'^(\s*[-*]\s+)(\[[ xX]\])(\s+)(.*)$')

# Canonical status glyphs. The Status line always begins with one;
# `_status_glyph` derives it from the status word so the orchestrator passes a
# bare status ("Setup", "Complete", "Blocked", "Failed", "Cancelled") and the
# helper is the single source of truth for the glyph vocabulary. 🚀=running (any
# in-progress phase), 🎉=Complete, 👎=Blocked, 💥=Failed, 🛑=Cancelled. The first
# three are reaction-compatible — they match the triggering-comment reactions
# (rocket / hooray / -1) the implement skill emits. 💥 (the workflow-level
# stall-backstop "died" flip, issue #356) and 🛑 (the workflow-level
# stall-backstop "cancelled" flip, issue #498) are the carve-outs: each is a
# workpad-only terminal glyph with NO triggering-comment reaction equivalent —
# the cloud backstop writes them when a run dead-ends (💥) or is cancelled (🛑),
# but emits no outcome reaction for either.
_STATUS_GLYPHS = ('🚀', '🎉', '👎', '💥', '🛑')


def _strip_status_glyph(status: str) -> str:
    """Drop a leading canonical glyph (and following spaces) from a status value,
    so re-applying `--status` is idempotent and the note sub-heading uses the
    bare phase word, not '🚀 Implementing'."""
    s = status.lstrip()
    for g in _STATUS_GLYPHS:
        if s.startswith(g):
            return s[len(g):].lstrip()
    return s


def _status_value_from_body(body: str) -> str:
    """Return the live Status VALUE from a workpad body **with its glyph intact**,
    trimmed, or '' when there is no Status line. Every reader of the Status *value*
    goes through here: `_status_word_from_body` below delegates to it and strips the
    glyph, and `cmd_update`'s issue-#814 success breadcrumb reports it verbatim (the
    breadcrumb is the caller's read-back that a `--status` PATCH landed, and the glyph
    is what makes '🎉 Complete' recognisable at a glance). `cmd_status`'s separate
    `_STATUS_VALUE_RE` use answers a different question — is a Status LINE present at
    all — and shares the compiled pattern rather than this function."""
    m = _STATUS_VALUE_RE.search(body)
    return m.group(1).strip() if m else ''


def _status_word_from_body(body: str) -> str:
    """Return the live Status word (glyph-stripped, trimmed) from a workpad body,
    or '' when there is no Status line. The single source of the "what is the live
    Status word in this body" rule — `cmd_status`, `_apply_mutations`'s note-phase
    resolution, and `cmd_update`'s `--expect-status` precondition all read it here
    so glyph/whitespace handling can never drift between the reader and the checker."""
    return _strip_status_glyph(_status_value_from_body(body)).strip()


def _status_glyph(status: str) -> str:
    s = _strip_status_glyph(status).strip().lower()
    if s.startswith('complete'):
        return '🎉'
    if s.startswith('blocked'):
        return '👎'
    if s.startswith('failed'):
        return '💥'
    if s.startswith('cancelled'):
        return '🛑'
    return '🚀'


# The status *class* vocabulary emitted by `workpad.py status` (issue #1025).
# Historically every terminal glyph collapsed to the single token 'terminal',
# which made 👎 Blocked indistinguishable from 🎉 Complete to the only code that
# reads the workpad (the cloud stall backstop) — so a blocked run concluded the
# job `success`. The class now names WHICH terminal end it is, so the backstop
# can conclude a non-complete terminal status non-`success` while keeping 🎉
# Complete green and 🛑 Cancelled a cancel. An in-progress glyph is 'interim'.
# `stall-backstop-decide.sh` and `lib/implement-stop-guard.sh` are the coupled
# consumers of these tokens (edited together). Only the four TERMINAL glyphs are
# enumerated — every in-progress glyph (🚀) and any unknown falls to 'interim'
# via the default below.
_TERMINAL_STATUS_CLASS_BY_GLYPH = {
    '🎉': 'complete',
    '👎': 'blocked',
    '💥': 'failed',
    '🛑': 'cancelled',
}


def _status_class(glyph: str) -> str:
    """Map a Status glyph to its `workpad.py status` class token (issue #1025)."""
    return _TERMINAL_STATUS_CLASS_BY_GLYPH.get(glyph, 'interim')


# The canonical ## Progress top-level phase labels, in order — the single
# source of truth that `_STATUS_TO_PROGRESS_PHASE` (below) and the `new-body`
# checklist (cmd_new_body) must both agree with. A note is nested under one of
# these rows by substring match, so renaming a phase here, in the map, or in
# the template without updating the others would misfile notes silently; the
# import-time assert below and the `new-body`-template test guard against that.
_PROGRESS_PHASES = ('Setup', 'Implement', 'Review', 'Documentation', 'PR marked ready')

# Maps a workpad Status word (glyph-stripped, lowercased) to the ## Progress
# top-level phase its notes nest under. Several in-progress statuses share one
# phase (Discovering/Reproducing/Planning/Implementing → Implement). A status
# absent from this map (Blocked) nests under the most recent *ticked* phase —
# see `_progress_phase_for_status`. The lookup degrades gracefully: if the
# mapped phase label isn't present in the checklist (a template rename), it
# falls back the same way, so a note is never dropped.
_STATUS_TO_PROGRESS_PHASE = {
    'setup': 'Setup',
    'discovering': 'Implement',
    'reproducing': 'Implement',
    'planning': 'Implement',
    'implementing': 'Implement',
    'reviewing': 'Review',
    'documenting': 'Documentation',
    'complete': 'PR marked ready',
}

# Fail loudly at import if the map ever names a phase the canonical list doesn't
# — a rename that would otherwise misfile notes with no signal.
assert set(_STATUS_TO_PROGRESS_PHASE.values()) <= set(_PROGRESS_PHASES), (
    'workpad: _STATUS_TO_PROGRESS_PHASE names a phase not in _PROGRESS_PHASES: '
    f'{set(_STATUS_TO_PROGRESS_PHASE.values()) - set(_PROGRESS_PHASES)}'
)

# Guard the managed nested-row declarations: a phase spelling the canonical list
# does not carry would make rendering/reconciliation silently omit that surface.
assert {phase for phase, _text, _substr in _managed_progress_rows()} <= set(_PROGRESS_PHASES), (
    'workpad: managed Progress rows name a phase not in _PROGRESS_PHASES: '
    f'{ {phase for phase, _t, _s in _managed_progress_rows()} - set(_PROGRESS_PHASES)}'
)

# A top-level (column-0, no leading whitespace) ## Progress checkbox — one row
# per lifecycle phase. Nested sub-items (`  - [ ] code + sweeps`) and nested
# note bullets carry leading whitespace and are deliberately not matched.
_TOP_LEVEL_CHECKBOX_RE = re.compile(r'^[-*] \[([ xX])\]\s+(.*)$')


def _progress_phase_for_status(progress_content: str, status: str | None) -> str | None:
    """Return the label text of the ## Progress top-level phase a note for
    `status` nests under, or None when the section has no top-level phases (the
    caller then appends the note flat).

    Mapped statuses nest under their phase; an unmapped status (Blocked/Failed)
    or a mapped phase that isn't present nests under the most recent *ticked*
    (completed) top-level row, else the first phase."""
    rows = []  # (label_text, ticked)
    for line in progress_content.split('\n'):
        m = _TOP_LEVEL_CHECKBOX_RE.match(line)
        if m:
            rows.append((m.group(2), m.group(1).lower() == 'x'))
    if not rows:
        return None
    key = _strip_status_glyph(status or '').strip().lower()
    mapped = _STATUS_TO_PROGRESS_PHASE.get(key)
    if mapped:
        for text, _ in rows:
            if mapped.lower() in text.lower():
                return text
    ticked = [text for text, t in rows if t]
    return ticked[-1] if ticked else rows[0][0]


def _set_or_insert_header(
    body: str, regex: re.Pattern, label: str, value: str, anchors: list[re.Pattern]
) -> str:
    """Replace a `**{label}:** …` front-matter line with `value`, or insert it
    after the first matching `anchors` line when absent (so a legacy workpad
    created before run/PR links existed still accepts `--run-link`/`--pr-link`
    on a resume instead of erroring). `anchors` is tried in priority order to
    preserve the canonical Status/Branch/Run/PR/Last-updated ordering — e.g. PR
    inserts after Run when Run exists, else after Branch — so a freshly-inserted
    line never jumps above an existing one. `value` is substituted via a
    function replacer so regex-special characters in the value (e.g. URL
    `?`/`&`) are literal."""
    new_line = f'**{label}:** {value}'
    body, n = regex.subn(lambda _m: new_line, body, count=1)
    if n:
        return body
    for anchor in anchors:
        body, n = anchor.subn(lambda m: m.group(0) + '\n' + new_line, body, count=1)
        if n:
            return body
    raise _UpdateError(
        f'{label} line absent and no anchor line ({", ".join(a.pattern for a in anchors)}) '
        f'to insert it after'
    )


def _split_sections(body: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (preamble, [(heading_line, content), ...]).

    `preamble` is everything before the first `## ` heading. Each section's
    content includes the trailing blank lines up to (but not including) the
    next heading line.
    """
    matches = list(_SECTION_RE.finditer(body))
    if not matches:
        return body, []
    preamble = body[: matches[0].start()]
    sections = []
    for i, m in enumerate(matches):
        heading = m.group(1)
        start = m.end() + 1  # skip the newline after the heading
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        content = body[start:end]
        sections.append((heading, content))
    return preamble, sections


def _join_sections(preamble: str, sections: list[tuple[str, str]]) -> str:
    out = [preamble.rstrip('\n')] if preamble.strip() else []
    for heading, content in sections:
        block = heading.rstrip() + '\n' + content
        out.append(block.rstrip('\n'))
    return '\n\n'.join(out) + '\n'


def _find_section(sections: list[tuple[str, str]], name: str) -> int | None:
    """Return index of a section by its heading text (case-insensitive), or None."""
    target = f'## {name}'.lower()
    for i, (heading, _) in enumerate(sections):
        if heading.strip().lower() == target:
            return i
    return None


def _tick_top_level_progress_phases(sections: list[tuple[str, str]]) -> None:
    """Tick every still-unticked top-level ## Progress phase row (issue #1337).

    The deterministic backstop for the cooperative per-phase `--tick-progress`
    calls: the terminal `--status Complete` write invokes this so a Complete
    workpad never sits above a `- [ ] **Implement**` / `- [ ] **Review**` row that
    a volatile tick miss left unticked. The row set is sourced from
    `_PROGRESS_PHASES` (the single source of truth, never a transcribed list); rows
    are matched with `_TOP_LEVEL_CHECKBOX_RE`, so only column-0 checkbox rows are
    considered and nested sub-items keep their prior state. Absent (or non-canonical)
    `## Progress` is a structural no-op — the Complete write still succeeds exactly
    as before. Mutates `sections` in place."""
    idx = _find_section(sections, 'Progress')
    if idx is None:
        return
    heading, content = sections[idx]
    out = []
    for line in content.split('\n'):
        m = _TOP_LEVEL_CHECKBOX_RE.match(line)
        if m and m.group(1) == ' ' and any(
            ph.lower() in m.group(2).lower() for ph in _PROGRESS_PHASES
        ):
            line = line.replace('[ ]', '[x]', 1)
        out.append(line)
    sections[idx] = (heading, '\n'.join(out))


def _set_section_content(
    sections: list[tuple[str, str]], name: str, new_content: str
) -> list[tuple[str, str]]:
    """Replace the content of an existing section."""
    idx = _find_section(sections, name)
    if idx is None:
        raise _UpdateError(f"section '## {name}' not found in workpad body")
    heading, _ = sections[idx]
    new_sections = list(sections)
    new_sections[idx] = (heading, new_content.rstrip('\n') + '\n')
    return new_sections


def _insert_section_after(
    sections: list[tuple[str, str]], after_name: str, new_heading: str,
    new_content: str,
) -> list[tuple[str, str]]:
    """Insert a new section immediately after the named one."""
    idx = _find_section(sections, after_name)
    if idx is None:
        raise _UpdateError(f"cannot insert after '## {after_name}' (not found)")
    new_sections = list(sections)
    block = (new_heading, new_content.rstrip('\n') + '\n')
    new_sections.insert(idx + 1, block)
    return new_sections


def _insert_section_at_head(
    sections: list[tuple[str, str]], new_heading: str, new_content: str,
) -> list[tuple[str, str]]:
    """Insert a new section BEFORE every existing one.

    The sibling of `_insert_section_after` for a section that has no anchor to
    follow: `## Progress` is the first section in the canonical skeleton
    (Progress -> Plan -> Acceptance Criteria -> Devflow Reflection), so a repair
    that re-creates it cannot express its position as "after" anything.
    """
    return [(new_heading, new_content.rstrip('\n') + '\n')] + list(sections)


def _join_preserving_newline(new_lines, content: str) -> str:
    """Re-join section lines, preserving whether the original `content` ended in a
    newline. The shared tail of every in-place line-rewrite helper in this file."""
    return '\n'.join(new_lines) + ('\n' if content.endswith('\n') else '')


def _tick_checkbox(content: str, text_substr: str, section_label: str) -> str:
    """Tick exactly one matching unticked `- [ ]`/`* [ ]` checkbox in the section.

    Only `[ ]` rows are considered candidates; already-ticked rows are ignored.
    A duplicate `--tick-plan`/`--tick-ac` value (or a substring that only matches
    an already-ticked row, or that matches nothing, or that matches multiple rows)
    raises `_TickMatchError` — a *volatile* per-row failure that `_apply_mutations`
    collects and `cmd_update` reports without discarding the call's other
    mutations. This is distinct from a structural `_UpdateError` (a missing
    section), which still aborts the whole call before any PATCH."""
    candidates = []
    new_lines = []
    for line in content.splitlines():
        m = re.match(r'^(\s*[-*]\s+)\[ \](\s+)(.*)$', line)
        if m and text_substr.lower() in m.group(3).lower():
            candidates.append((len(new_lines), m))
        new_lines.append(line)
    if not candidates:
        raise _TickMatchError(
            f"no unticked {section_label} checkbox matched substring "
            f"{text_substr!r} (already ticked, or no match)"
        )
    if len(candidates) > 1:
        raise _TickMatchError(
            f"{len(candidates)} {section_label} checkboxes match {text_substr!r}; "
            f"be more specific"
        )
    line_idx, m = candidates[0]
    new_lines[line_idx] = f"{m.group(1)}[x]{m.group(2)}{m.group(3)}"
    return _join_preserving_newline(new_lines, content)


def _tick_checkbox_by_index(content: str, n: int, section_label: str) -> str:
    """Tick the Nth checkbox (1-based) in the section, counting *every*
    `- [ ]`/`* [ ]` and `- [x]`/`* [x]` row in document order.

    Addressing by position avoids the fragile, hand-picked unique-substring
    requirement of `_tick_checkbox` for batched ticks. An out-of-range N, or an N
    that lands on an already-ticked row, is a *volatile* `_TickMatchError` (same
    class the substring path raises) — collected and reported, never a structural
    abort. Mirrors the `_rewrite_checkbox` row-walk (`[ xX]` state class)."""
    rows = []  # (line_idx, match) for every checkbox row, ticked or not
    new_lines = []
    for line in content.splitlines():
        m = _CHECKBOX_ROW_RE.match(line)
        if m:
            rows.append((len(new_lines), m))
        new_lines.append(line)
    if n < 1 or n > len(rows):
        raise _TickMatchError(
            f"index {n} out of range for {section_label} (section has "
            f"{len(rows)} checkbox row(s), valid 1..{len(rows)})"
        )
    line_idx, m = rows[n - 1]
    if m.group(2) != '[ ]':
        raise _TickMatchError(
            f"{section_label} checkbox {n} is already ticked"
        )
    new_lines[line_idx] = f"{m.group(1)}[x]{m.group(3)}{m.group(4)}"
    return _join_preserving_newline(new_lines, content)


def _find_checkbox_row(content: str, old_substr: str, section_label: str):
    """Resolve the ONE checkbox row `old_substr` names, returning
    `(lines, line_idx, match)`. Raises `_UpdateError` when the substring matches
    zero or multiple rows (the exactly-one-match rule).

    Split out of `_rewrite_checkbox` so the `(post-merge)` rationale guard can
    reason over the row's CURRENT text using the very same resolution the rewrite
    will use (issue #338). Sharing the resolution — rather than re-deriving the
    row from the OLD argument string — keeps the guard's view of "which row is
    this pair about" identical to the rewriter's by construction."""
    matched = []
    lines = content.splitlines()
    for i, line in enumerate(lines):
        m = _CHECKBOX_ROW_RE.match(line)
        if m and old_substr.lower() in m.group(4).lower():
            matched.append((i, m))
    if not matched:
        raise _UpdateError(
            f"no {section_label} checkbox matched {old_substr!r} for rewrite"
        )
    if len(matched) > 1:
        raise _UpdateError(
            f"{len(matched)} {section_label} checkboxes match {old_substr!r}; "
            f"be more specific"
        )
    line_idx, m = matched[0]
    return lines, line_idx, m


def _rewrite_checkbox(
    content: str, old_substr: str, new_text: str, section_label: str
) -> str:
    """Find one checkbox matching old_substr; replace its label text with new_text.
    Preserves checkbox state (`[ ]` vs `[x]`) and indentation."""
    new_lines, line_idx, m = _find_checkbox_row(content, old_substr, section_label)
    new_lines[line_idx] = f"{m.group(1)}{m.group(2)}{m.group(3)}{new_text}"
    return _join_preserving_newline(new_lines, content)


def _split_details(content: str) -> tuple[str | None, str, str | None]:
    """If a section's content wraps its body in a `<details>` block, return
    `(head, inner, tail)` where `head` is the opening `<details>`/`<summary>`
    lines (plus the blank line markdown needs to render inside), `inner` is the
    collapsible body, and `tail` is the closing `</details>`. Returns
    `(None, content, None)` when there is no wrapper — so the append helpers
    operate on a legacy (un-wrapped) section unchanged.

    This lets `Devflow Reflection` be collapsed in a `<details>` block while
    `--reflection` still appends *inside* it
    (before `</details>`), never after — which would silently fall outside the
    collapsible region."""
    lines = content.split('\n')
    try:
        o = next(i for i, line in enumerate(lines) if line.strip().startswith('<details'))
        c = next(i for i in range(len(lines) - 1, -1, -1) if lines[i].strip() == '</details>')
    except StopIteration:
        return None, content, None
    if c <= o:
        return None, content, None
    head_end = o + 1
    if head_end < len(lines) and lines[head_end].strip().startswith('<summary'):
        head_end += 1
    if head_end < len(lines) and lines[head_end].strip() == '':
        head_end += 1
    head = '\n'.join(lines[:head_end])
    inner = '\n'.join(lines[head_end:c]).strip('\n')
    tail = '\n'.join(lines[c:])
    return head, inner, tail


def _rewrap_details(head: str, new_inner: str, tail: str) -> str:
    """Reassemble a `<details>` section from its head, freshly-mutated inner
    body, and tail (a blank line after `<summary>` is preserved for markdown)."""
    return head.rstrip('\n') + '\n\n' + new_inner.strip('\n') + '\n' + tail + '\n'


def _append_progress_note(
    content: str, note: str, timestamp: str, phase_label: str | None,
    reserved_marker_ok: bool = False,
) -> str:
    """Insert a `  - {timestamp} — {note}` bullet nested under the ## Progress
    top-level phase whose row text contains `phase_label`.

    Notes live inside the Progress section now (no separate Decisions / Notes
    section): the bullet lands at the end of its phase's block — after that
    phase's sub-checkboxes and any earlier notes, before the next top-level
    phase — so a phase's notes stay grouped and chronological across many
    update calls. `timestamp` is the time-only `HH:MM:SS` string. When
    `phase_label` is None, or no row matches it, the note is appended flat at
    the end of the section so it is never dropped.

    **Reserved-marker guard (issue #1453).** Every caller-supplied text that reaches
    `## Progress` passes through here, so the screen for a reserved review-coverage
    marker lives here rather than at each writing flag: the gate's readers locate
    their marker inside a `## Progress` bullet, so any free-text channel — `--note`,
    a `--checkpoint` TEXT, a `--record-classification` rationale, or a channel added
    later — could otherwise write a record that passed none of the producer
    validation and filed none of the accompanying evidence. The rows the producer
    itself writes carry their marker and reach this function too, so they are
    admitted by an explicit opt-in argument rather than by pattern."""
    if not reserved_marker_ok and _REVIEW_COVERAGE_ANY_MARKER_RE.search(note or ''):
        raise _UpdateError(
            "the note text carries a reserved review-coverage checkpoint marker; "
            "record coverage with `--record-review-coverage` and a gap with "
            "`--review-coverage-disposition`, which validate the record and write "
            "the accompanying evidence. No PATCH was made."
        )
    lines = content.split('\n')
    start = None
    if phase_label:
        for i, line in enumerate(lines):
            m = _TOP_LEVEL_CHECKBOX_RE.match(line)
            if m and phase_label.lower() in m.group(2).lower():
                start = i
                break
    if start is None:
        # No resolvable phase row → flat (un-nested) append at section end.
        stripped = content.rstrip('\n')
        prefix = stripped + '\n' if stripped.strip() else ''
        return prefix + f"- {timestamp} — {note}\n"
    # Block end: the next top-level phase row, else end of section. Nested
    # sub-items carry leading whitespace and never match, so they stay inside
    # the block.
    end = next(
        (j for j in range(start + 1, len(lines))
         if _TOP_LEVEL_CHECKBOX_RE.match(lines[j])),
        len(lines),
    )
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    new_lines = lines[:end] + [f"  - {timestamp} — {note}"] + lines[end:]
    return _join_preserving_newline(new_lines, content)


# ── Reproduce-first classification: row reconcile + note supersede (issue #449) ──
#
# The Phase 2.1.5 reproduce-first gate keys on a recorded *content* classification,
# not the `bug` label. Phase 1.3 records that classification as a superseding
# `classification: ` note and reconciles the bug-only "reproduction captured"
# Progress row to match it — on every entry — so a gate-created skeleton (rendered
# deterministically from the label) always agrees with the classification before
# Phase 2 begins. Both operate on the ## Progress section.
_CLASSIFICATION_VALUES = ('bug-report', 'non-bug')
# The fixed, greppable note prefix. Phase 1.1's two exact forms are
# `classification: bug-report — <rationale>` / `classification: non-bug — <rationale>`.
_CLASSIFICATION_NOTE_PREFIX = 'classification: '
# Matches an existing classification note bullet — the `  - HH:MM:SS — ` prefix
# `_append_progress_note` writes (em-dash separator), then the note prefix — so a
# fresh record can supersede it. Anchored at line start; tick-state-irrelevant
# (notes are plain bullets, not checkboxes).
_CLASSIFICATION_NOTE_RE = re.compile(
    _PROGRESS_BULLET_PREFIX_RE + re.escape(_CLASSIFICATION_NOTE_PREFIX)
)


def _reconcile_reproduction_row(content: str, classification: str) -> str:
    """Idempotently add or remove the bug-only reproduction-captured Progress
    sub-row so the skeleton matches the recorded content classification (#449).

    - `bug-report` → ensure the row is present: when absent, insert
      `_REPRODUCTION_ROW` as the first sub-item of the `**Implement**` phase row
      (the anchor is the `**Implement**` line itself, not any sibling sub-row);
      no-op when a row is already present in ANY tick state. A skeleton with no
      `**Implement**` anchor fails loud (`_UpdateError`) — see below.
    - `non-bug` → remove the row only when present AND unticked; a *ticked* row is
      historical evidence and is preserved; an absent row is a no-op. This arm
      deliberately never fails loud: it needs no anchor (there is nothing to
      insert), so a missing row or missing `**Implement**` line is the desired
      end state, not an error — the asymmetry with bug-report is intentional.

    Never removes a ticked row and never inserts a duplicate — so running it on
    every Phase 1.3 entry is safe. Operates on the ## Progress section content."""
    lines = content.split('\n')
    matches = [
        (i, m) for i, ln in enumerate(lines)
        if (m := _CHECKBOX_ROW_RE.match(ln))
        and _REPRODUCTION_ROW_SUBSTR.lower() in m.group(4).lower()
    ]
    if classification == 'bug-report':
        if matches:
            return content  # already present (ticked or not) → idempotent no-op
        for i, ln in enumerate(lines):
            m = _TOP_LEVEL_CHECKBOX_RE.match(ln)
            if m and 'implement' in m.group(2).lower():
                new_lines = lines[:i + 1] + [_REPRODUCTION_ROW] + lines[i + 1:]
                return _join_preserving_newline(new_lines, content)
        # No **Implement** phase row to anchor under — a malformed/legacy skeleton.
        # Fail structurally (loud) rather than silently drop the row into the wrong
        # place: a bug-classified run must not lose its reproduce-first gate row.
        raise _UpdateError(
            "cannot reconcile reproduction row: no '**Implement**' phase row in "
            "## Progress to anchor it under"
        )
    # non-bug: drop only unticked repro rows; keep ticked ones and no-op when absent.
    drop = {i for i, m in matches if m.group(2) == '[ ]'}
    if not drop:
        return content
    new_lines = [ln for i, ln in enumerate(lines) if i not in drop]
    return _join_preserving_newline(new_lines, content)


def _reconcile_extension_rows(content: str) -> str:
    """Idempotently repair managed nested `## Progress` rows into a workpad
    created before they existed (issues #1462 and #1657), mirroring the shape
    `_reconcile_reproduction_row` uses.

    A row is detected by its stable substring in ANY tick state, so a
    present-and-ticked row is left exactly as it is and never duplicated; a
    missing row is inserted directly under its phase's top-level row. Rows are
    processed in reverse declared order and each insert lands at the anchor, so a
    wholly-unrepaired phase ends up carrying them in declared order.

    A missing `**Review**` anchor is repaired before its required review-engine
    rows are inserted. Other absent phase anchors keep the existing warn-and-skip
    hydration behavior. Operates on the `## Progress` section content."""
    lines = content.split('\n')
    for phase, text, substr in reversed(tuple(_managed_progress_rows())):
        if any(
            (m := _CHECKBOX_ROW_RE.match(ln)) and substr.lower() in m.group(4).lower()
            for ln in lines
        ):
            continue  # present in any tick state → idempotent no-op
        anchor = next(
            (
                i for i, ln in enumerate(lines)
                if (m := _TOP_LEVEL_CHECKBOX_RE.match(ln))
                and phase.lower() in m.group(2).lower()
            ),
            None,
        )
        if anchor is None:
            if phase == 'Review':
                # Review is now a required progress surface. Recreate its top-level
                # row at the canonical phase boundary: immediately before the first
                # later lifecycle phase, or at the section tail when none survives.
                review_pos = _PROGRESS_PHASES.index('Review')
                later_phases = tuple(_PROGRESS_PHASES[review_pos + 1:])
                insert_at = next(
                    (
                        i for i, ln in enumerate(lines)
                        if (m := _TOP_LEVEL_CHECKBOX_RE.match(ln))
                        and any(p.lower() in m.group(2).lower()
                                for p in later_phases)
                    ),
                    len(lines) - 1 if lines and lines[-1] == '' else len(lines),
                )
                lines = lines[:insert_at] + ['- [ ] **Review**'] + lines[insert_at:]
                anchor = insert_at
                sys.stderr.write(
                    "workpad.py update: re-created missing '**Review**' phase row "
                    "in ## Progress before reconciling managed review rows.\n"
                )
            else:
                # Legible fail-open for optional extension-only phases: a skip that
                # emitted nothing would be indistinguishable from a surface that was
                # never in scope.
                sys.stderr.write(
                    f"workpad.py update: WARNING: no '**{phase}**' phase row in "
                    f"## Progress — the '{substr}' managed row was NOT repaired; "
                    f"a later --tick-progress for it will miss.\n"
                )
                continue
        lines = lines[:anchor + 1] + [f'  - [ ] {text}'] + lines[anchor + 1:]
    return _join_preserving_newline(lines, content)


def _remove_classification_notes(content: str) -> str:
    """Drop every existing `classification: ` note bullet from ## Progress content,
    so a fresh record supersedes it — the workpad carries exactly one at all times
    (issue #449). Read-only otherwise; preserves the section's trailing newline."""
    kept = [ln for ln in content.split('\n')
            if not _CLASSIFICATION_NOTE_RE.match(ln)]
    return _join_preserving_newline(kept, content)


# ── Devflow Reflection: kind taxonomy + grouped rendering ───────────────────
#
# Reflection bullets are grouped by KIND into the `### ` sub-sections defined in
# _REFLECTION_SUBSECTIONS inside the `## Devflow Reflection` <details> block, so a
# human scanning a run sees actionable items, improvement proposals, and
# informational notes separated. The helper owns the glyph, bold label (or none),
# and sub-section placement — the caller passes only a bare kind token via
# `--reflection-kind` — the same "helper owns the rendering token" idiom as the
# `--status` glyph and `--note` phase-nesting.
#
# Ordered: kind -> (glyph, bold label, sub-section key). A label of '' renders
# the bullet GLYPH-ONLY (`- {glyph} {text}`) — used when the sub-section heading
# already names the kind, so the bold label would be redundant: `note` under
# `### ℹ️ Notes` and `improvement` under `### 💡 Improvements` (issue #476). The
# three actionable kinds keep their label (they share one `### ⚠️ Action required`
# heading, so the label is what distinguishes them); `issue-accuracy` keeps its
# label because it renders under `### ℹ️ Notes`, which does NOT name it.
_REFLECTION_KINDS = {
    'blocked':        ('⛔', 'Blocked',        'action'),
    'deferred':       ('⏭️', 'Deferred',       'action'),
    'dropped-failed': ('❗', 'Dropped/Failed', 'action'),
    'improvement':    ('💡', '',              'improvements'),
    'issue-accuracy': ('📝', 'Issue accuracy', 'notes'),
    'note':           ('ℹ️', '',              'notes'),
}
_DEFAULT_REFLECTION_KIND = 'note'

# Sub-section headings in canonical render order (Action required → Improvements
# → Notes). Level-3 (`### `) is mandatory: lib/fetch-pr-context.sh terminates the
# reflection parse at the first `## ` heading, so a level-2 sub-heading would
# truncate it — keep these `### `.
_REFLECTION_SUBSECTIONS = (
    ('action',       '### ⚠️ Action required'),
    ('improvements', '### 💡 Improvements'),
    ('notes',        '### ℹ️ Notes'),
)
_SUBSECTION_HEADINGS = dict(_REFLECTION_SUBSECTIONS)            # sub-key -> heading
_SUBSECTION_HEADING_ORDER = [h for _, h in _REFLECTION_SUBSECTIONS]  # canonical order
_SUBSECTION_HEADING_RE = re.compile(r'^###\s')


def _parse_reflection_blocks(inner: str) -> list[list]:
    """Split the reflection <details> inner body into ordered blocks.

    Each block is `[heading_line_or_None, [content_lines...]]`. A leading block
    with heading None holds any pre-heading content (normally empty); every
    `### ` line starts a new block. An empty preamble block is dropped."""
    blocks = []
    current = [None, []]

    def _flush():
        if current[0] is not None or any(ln.strip() for ln in current[1]):
            blocks.append(current)

    for line in inner.split('\n'):
        if _SUBSECTION_HEADING_RE.match(line):
            _flush()
            current = [line.rstrip(), []]
        else:
            current[1].append(line)
    _flush()
    return blocks


def _render_reflection_blocks(blocks: list[list]) -> str:
    """Reassemble blocks into the reflection inner body: each `### ` sub-section
    is its heading followed by its bullets (surrounding blank lines trimmed),
    sub-sections separated by one blank line. A leading heading-None block (legacy
    un-kinded preamble bullets) renders first, before the first `### ` sub-section,
    separated by the same blank line."""
    parts = []
    for heading, lines in blocks:
        body = list(lines)
        while body and not body[-1].strip():
            body.pop()
        if heading is not None:
            while body and not body[0].strip():
                body.pop(0)
            parts.append(heading + ('\n' + '\n'.join(body) if body else ''))
        elif body:
            parts.append('\n'.join(body))
    return '\n\n'.join(parts)


def _insert_reflection_bullet(inner: str, kind: str, text: str) -> str:
    """Insert one reflection bullet of `kind` into the <details> inner body,
    under its canonical `### ` sub-section — creating the heading lazily (in
    Action-required-before-Notes order) when absent, reusing it when present.

    Pre-existing un-kinded (legacy) bullets are retained verbatim as a leading
    heading-None preamble block, *above* the lazily-created sub-sections — they
    are never re-sorted into a sub-section."""
    try:
        glyph, label, sub_key = _REFLECTION_KINDS[kind]
    except KeyError:
        # The argparse `choices=list(_REFLECTION_KINDS)` prevents a bad kind on
        # the CLI path, but a programmatic caller (e.g. a test driving
        # _apply_mutations directly) could pass one — convert it to the file's
        # clean _UpdateError contract (targeted message, no partial PATCH)
        # instead of letting a bare KeyError traceback escape.
        raise _UpdateError(
            f"unknown reflection kind {kind!r}; expected one of "
            f"{', '.join(_REFLECTION_KINDS)}"
        ) from None
    # Reflection bullets are single-line. Collapse any embedded line breaks
    # (`str.splitlines()` handles \n, \r, \v, …) to spaces — e.g. a multi-line
    # gh/jq error captured into a `dropped-failed` breadcrumb — so the whole
    # message stays on one bullet line. The line-based parser in
    # lib/fetch-pr-context.sh captures only a bullet's first line, so a multi-line
    # bullet would silently drop its continuation from reflections[]. (Single-line
    # text round-trips unchanged through splitlines+join.)
    one_line = ' '.join(text.splitlines())
    # Glyph-only render when the kind carries no label (its sub-heading already
    # names it — see _REFLECTION_KINDS); labeled render otherwise. Isolate the one
    # varying segment so the bullet skeleton lives in a single f-string.
    label_part = f'**{label}:** ' if label else ''
    bullet = f'- {glyph} {label_part}{one_line}'
    target_heading = _SUBSECTION_HEADINGS[sub_key]
    blocks = _parse_reflection_blocks(inner)
    for blk in blocks:
        if blk[0] == target_heading:
            while blk[1] and not blk[1][-1].strip():
                blk[1].pop()
            blk[1].append(bullet)
            return _render_reflection_blocks(blocks)
    # No existing sub-section for this kind: insert a new block, preserving the
    # canonical order (a None-heading preamble always stays first; an unknown
    # `### ` heading sorts last so it is never reordered above a known one).
    def _rank(heading):
        return (_SUBSECTION_HEADING_ORDER.index(heading)
                if heading in _SUBSECTION_HEADING_ORDER
                else len(_SUBSECTION_HEADING_ORDER))

    new_rank = _rank(target_heading)
    pos = len(blocks)
    for i, blk in enumerate(blocks):
        if blk[0] is not None and _rank(blk[0]) > new_rank:
            pos = i
            break
    blocks.insert(pos, [target_heading, [bullet]])
    return _render_reflection_blocks(blocks)


def _append_reflection(content: str, kind: str, text: str) -> str:
    """`<details>`-aware: insert a grouped reflection bullet *inside* the block
    (before `</details>`), reusing _split_details/_rewrap_details so the
    collapsible region stays intact. A legacy un-wrapped section (no <details>)
    is grouped in place."""
    head, inner, tail = _split_details(content)
    new_inner = _insert_reflection_bullet(inner, kind, text)
    if head is None:
        return new_inner
    return _rewrap_details(head, new_inner, tail)


def _decode_utf8(raw: bytes, flag: str, path: str) -> str:
    """Decode bytes as UTF-8, converting a `UnicodeDecodeError` (a `ValueError`
    the plain `except OSError` shape would let escape as a raw traceback) into
    the flag's clean `_UpdateError` contract. Single-sourced so the two file
    readers below (`_read_section_file`, `_read_file_payload`) cannot drift
    the decode-failure message shape apart."""
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError as e:
        raise _UpdateError(f"{flag}: {path!r} is not valid UTF-8: {e}")


def _read_section_file(path: str, flag: str) -> str:
    """Read a file passed via one of the --replace-*-file flags. Reads bytes and
    decodes UTF-8 EXPLICITLY (never the ambient locale codec) so non-ASCII
    section content round-trips byte-identical on any host, and converts an
    OS-level error or a decode failure into a clean `_UpdateError` so the
    orchestrator gets a targeted message instead of a Python traceback, and the
    surrounding `cmd_update` aborts before the PATCH (no partial update)."""
    try:
        raw = Path(path).read_bytes()
    except OSError as e:
        raise _UpdateError(f"{flag}: could not read {path!r}: {e}")
    return _decode_utf8(raw, flag, path)


def _read_file_payload(path: str, flag: str, thing: str) -> str:
    """Read a `--*-file` bullet payload for `flag` (e.g. `--reflection-file`,
    `--note-file`), bypassing shell interpolation: bytes are read verbatim from a
    file, or from stdin when `path` is `-`, and decoded via `_decode_utf8`
    (explicit UTF-8, no ambient codec) so backticks, `$`, quotes, an em-dash or an
    emoji round-trip byte-identical on any host. An empty or whitespace-only
    payload is a structural failure — a blank `thing` bullet carries no signal —
    so it aborts before any PATCH. All failure modes raise `_UpdateError`, so
    `_apply_mutations` aborts with no partial workpad write. Shared by both file
    channels so a future fix to the read/decode/empty-guard contract cannot drift
    one behind the other."""
    try:
        if path == '-':
            raw = sys.stdin.buffer.read()
        else:
            raw = Path(path).read_bytes()
    except OSError as e:
        raise _UpdateError(f"{flag}: could not read {path!r}: {e}")
    text = _decode_utf8(raw, flag, path)
    if not text.strip():
        raise _UpdateError(
            f"{flag}: payload is empty or whitespace-only; a "
            f"{thing} bullet must carry text")
    return text


def _reflection_file_payload(args) -> str:
    """Read `--reflection-file`'s payload at most once per invocation, memoized on
    `args`.

    Two consumers need the SAME text: `_apply_mutations`, which renders the bullet,
    and `cmd_update`'s failed-write buffering (issue #1214), which must persist it
    when the PATCH drops it. The `-`/stdin arm can only be read once — a second read
    returns empty and would raise the empty-payload `_UpdateError` against a payload
    that was in fact fine — so the first read is cached and a later caller is served
    from that cache. Failure modes are `_read_file_payload`'s unchanged
    `_UpdateError` contract; only a SUCCESSFUL read is cached, so a caller that
    retries after a failure re-reads rather than seeing a half-populated cache."""
    cached = getattr(args, '_reflection_file_payload_cache', None)
    if cached is None:
        cached = _read_file_payload(args.reflection_file, '--reflection-file', 'reflection')
        args._reflection_file_payload_cache = cached
    return cached


def _note_file_payload(args) -> str:
    """Read `--note-file`'s payload at most once per invocation, memoized on
    `args` — the note twin of `_reflection_file_payload` (both share
    `_read_file_payload`). Two consumers need the SAME text:
    `_cmd_update_inner`'s failed-write buffering (which persists the note when a
    PATCH drops it) and `_apply_mutations`, which renders the bullet. The
    `-`/stdin arm can only be read once, so the first read is cached and a later
    caller is served from that cache; only a SUCCESSFUL read is cached, so a
    caller that retries after a failure re-reads rather than seeing a stale one."""
    cached = getattr(args, '_note_file_payload_cache', None)
    if cached is None:
        cached = _read_file_payload(args.note_file, '--note-file', 'note')
        args._note_file_payload_cache = cached
    return cached


def _deferred_filed_file_values(args) -> list:
    """Read `--mark-deferred-filed-file` as one marker value per line (issue #1446).

    A deferred criterion's normalized text routinely carries backticks and an
    apostrophe, and the cloud matcher denies command substitution — so neither
    single- nor double-quoting `--mark-deferred-filed`'s inline value is
    shell-safe, and a run that cannot write its markers re-files the same
    follow-up on a later Phase 4 entry. This is the interpolation-free arm, the
    per-line twin of `--reflection-file`: bytes come off disk verbatim through
    the shared `_read_file_payload` reader, so a value round-trips byte-identical.

    Blank and whitespace-only lines are dropped (a trailing newline is normal) and
    each surviving line is stripped, since a value the `deferred-presence`
    predicate printed carries no leading or trailing space. An all-blank payload is
    already refused by `_read_file_payload`, so no line survives to be marked.
    Memoized like the other file arms so the `-`/stdin form survives two reads."""
    path = getattr(args, 'mark_deferred_filed_file', None)
    if not path:
        return []
    cached = getattr(args, '_deferred_filed_file_cache', None)
    if cached is None:
        payload = _read_file_payload(
            path, '--mark-deferred-filed-file', 'deferred-filed marker')
        cached = [ln.strip() for ln in payload.splitlines() if ln.strip()]
        args._deferred_filed_file_cache = cached
    return cached


class _UpdateError(Exception):
    """Raised by mutation helpers in `_apply_mutations` to signal a *structural*
    failure — a missing target section, a missing `Status`/`Last updated` line, an
    unreadable `--*-file`. Caught only in `cmd_update`, where it prints the message
    and exits 1 *before* the PATCH call, so a structural failure guarantees no
    partial workpad update. Contrast `_TickMatchError`, a per-row tick miss that is
    collected and reported without aborting the call's other mutations."""


class _TickMatchError(Exception):
    """Raised by the tick helpers (`_tick_checkbox`, `_tick_checkbox_by_index`)
    for a *volatile* per-row failure: a substring matching zero/multiple rows, an
    out-of-range index, or an index landing on an already-ticked row, *inside a
    present section*. Deliberately NOT a subclass of `_UpdateError` so the
    structural `except _UpdateError` in `cmd_update` never captures it. Collected
    per-tick in `_apply_mutations`; the call's other mutations still apply and
    PATCH, and `cmd_update` then exits non-zero naming each failed tick."""


def _report_failed_ticks(failed_ticks, preamble):
    """Write the collected volatile tick misses to stderr under `preamble`.

    The single chokepoint every `cmd_update` exit path routes its `failed_ticks`
    through, so a collected miss is reported on ALL three: the structural-abort
    path, the PATCH-failure path, and the clean-PATCH-but-ticks-missed path. The
    `preamble` states whether a PATCH was persisted, so the caller can tell
    'nothing landed, re-send the whole call' from 'the body PATCHed, re-tick only
    the unresolved row(s)' without re-sending the already-applied status/notes."""
    sys.stderr.write(f"workpad.py update: {preamble}:\n")
    for ft in failed_ticks:
        sys.stderr.write(f"  - {ft}\n")


# ---------------------------------------------------------------------------
# Failed-write buffering and replay (issue #1214, part (c))
# ---------------------------------------------------------------------------
# When a workpad PATCH fails (a GitHub fault confined to the comment endpoint),
# the append-only history the call intended — its `--note` bullets and its
# `## Devflow Reflection` bullets — is otherwise lost, exactly the stranded state
# issue #1214 describes (a run that cannot record its Blocked reflection or its
# completion evidence). So a failed call BUFFERS that append-only content to
# local storage under the gitignored `.prflow/tmp/`, and the next successful
# `update` — which includes every terminal-status transition, since that is
# itself an `update` — REPLAYS the buffered content idempotently: a buffered
# item already RENDERED as its own bullet in the live body is skipped, so a
# replay never duplicates content (AC9). Status and tick mutations are
# deliberately NOT buffered — they are transient state a later call
# re-establishes, whereas a dropped note/reflection is a permanent hole in the
# run's record.

_WORKPAD_BUFFER_DIRNAME = 'workpad-buffer'


def _workpad_buffer_path(comment_id) -> Path:
    """Local buffer file for one workpad comment's failed-write records.

    Anchored under the repo-root `.prflow/tmp/` (gitignored in this repo and in
    every install.sh-scaffolded consumer), so a buffered record never lands as a
    tracked file. Keyed by comment id so two issues' buffers never collide.
    """
    root = _repo_root() or str(Path.cwd())
    return (Path(root) / '.prflow' / 'tmp' / _WORKPAD_BUFFER_DIRNAME
            / f'{comment_id}.json')


def _read_workpad_buffer(comment_id) -> list:
    """Return the list of buffered records for a comment (empty on any degraded
    shape — absent file, unreadable, malformed, or a non-list payload). A read
    failure never raises: buffering is a best-effort safety net."""
    try:
        raw = _workpad_buffer_path(comment_id).read_text(encoding='utf-8')
    except OSError:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        # Loud, not silent: the caller goes on to append to an empty list and
        # overwrite this file, so an undiagnosed malformed buffer is buffered
        # content discarded without a trace. `_write_workpad_buffer` writes
        # atomically, so this shape is not one this helper can produce itself.
        sys.stderr.write(
            f"workpad.py: the workpad buffer for comment {comment_id} is not valid "
            f"JSON ({e}); treating it as empty — any records it held are not "
            f"replayable and the next buffered write replaces it.\n")
        return []
    if not isinstance(data, list):
        sys.stderr.write(
            f"workpad.py: the workpad buffer for comment {comment_id} is a "
            f"{type(data).__name__}, not a list of records; treating it as empty.\n")
        return []
    return data


def _write_workpad_buffer(path: Path, records: list) -> None:
    """Write the buffer file atomically: a temp file in the same directory, then an
    `os.replace`. A plain `write_text` can be interrupted mid-write during the very
    outage this buffer exists for, leaving partial JSON that the next read cannot
    parse — so the durability guarantee would fail exactly when it is needed. The
    rename is atomic on POSIX and on Windows (`os.replace` overwrites), so a reader
    observes the prior contents or the new contents, not a half-written state.
    Raises `OSError` for the caller's existing best-effort handling."""
    tmp = path.with_name(f'{path.name}.tmp')
    tmp.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def _buffer_failed_change(comment_id, notes, reflections, kind) -> "Path | None":
    """Persist the append-only content of a FAILED update so it is not lost (AC7).

    Records only `--note` and `--reflection` bullets (with their kind); status and
    tick mutations are transient and not buffered. Best-effort: returns the buffer
    path on a successful write, or None when there was nothing to buffer or the
    write itself failed — a buffering failure never changes the caller's own
    fail-loud outcome."""
    notes = [n for n in (notes or []) if n]
    reflections = [r for r in (reflections or []) if r]
    if not notes and not reflections:
        return None
    record = {
        'notes': notes,
        'reflections': reflections,
        'reflection_kind': kind or _DEFAULT_REFLECTION_KIND,
    }
    path = _workpad_buffer_path(comment_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = _read_workpad_buffer(comment_id)
        existing.append(record)
        _write_workpad_buffer(path, existing)
    except OSError as e:
        sys.stderr.write(
            f"workpad.py update: could not buffer the failed change: {e}\n")
        return None
    return path


# ── Replay identity: "already applied" is an EXACT rendered-bullet match ────
#
# A buffered item counts as already applied only when the live body carries the
# bullet the RENDERER would have produced for it — never when its text merely
# occurs somewhere in the body. The distinction is the whole safety property of
# this feature: `fully_replayed` authorizes `_clear_workpad_buffer`, so a
# false positive here does not merely skip an append, it DESTROYS the only
# surviving copy of the item. A containment test (`text in body`) false-positives
# on any item whose text is a substring of unrelated content — a terse Blocked
# reflection, a status word, an error code, an AC-label fragment, or the same
# text embedded inside a longer note — which is silent loss of the operator's
# record inside the feature built to prevent exactly that.
#
# Both predicates below are therefore whole-LINE equality against the shapes the
# two append helpers emit, scoped to the one section each writes into:
#
#   * a note      — `_append_progress_note` writes `{indent}- HH:MM:SS — {note}`
#     into `## Progress`; the note text is the ENTIRE remainder of the line, so
#     comparing that captured remainder for equality (plus, for a multi-line
#     note, its continuation lines) cannot be satisfied by a line that merely
#     contains the text.
#   * a reflection — `_insert_reflection_bullet` writes `- {glyph} {label}{text}`
#     into `## Devflow Reflection`, with the text collapsed to one line; the
#     candidate set is built from `_REFLECTION_KINDS` itself, so it is exactly
#     the finite set of renderings that text could have, and a whole-line
#     equality against it cannot be satisfied by containment either.
#
# Both fail toward re-appending: an unresolvable section, a legacy un-kinded
# bullet, or any shape the renderer does not emit reads as NOT-applied, which
# risks a duplicate bullet and never a dropped record. That direction is chosen
# deliberately — a visible duplicate is recoverable, a silent deletion is not.


def _note_already_rendered(progress_content: "str | None", note: str) -> bool:
    """True when `note` is already present in the resolved `## Progress` content
    as a rendered note bullet — `_PROGRESS_BULLET_RE`'s captured text equal to
    the whole note, with a multi-line note's continuation lines matching verbatim
    on the lines that follow. None content (section absent or duplicated) reads
    as not-present."""
    if progress_content is None:
        return False
    want = note.split('\n')
    lines = progress_content.split('\n')
    for i, line in enumerate(lines):
        m = _PROGRESS_BULLET_RE.match(line)
        if m is None or m.group(1) != want[0]:
            continue
        if lines[i + 1:i + len(want)] == want[1:]:
            return True
    return False


def _reflection_already_rendered(
    reflection_content: "str | None", text: str
) -> bool:
    """True when `text` is already present in the resolved `## Devflow Reflection`
    content as a bullet `_insert_reflection_bullet` could have written for it.

    The comparison is whole-line equality against the candidate renderings for
    every kind, because a replayed reflection is filed under the REPLAYING call's
    kind rather than its own — so the glyph/label the original write used is not
    knowable here and all of them must count as the same item."""
    if reflection_content is None:
        return False
    one_line = ' '.join(text.splitlines())
    candidates = {
        f'- {glyph} ' + (f'**{label}:** ' if label else '') + one_line
        for glyph, label, _ in _REFLECTION_KINDS.values()
    }
    return any(ln.strip() in candidates for ln in reflection_content.split('\n'))


def _plan_buffer_replay(comment_id, body, args,
                        pending_notes=None, pending_reflections=None) -> bool:
    """Fold any buffered failed-write content for this comment into `args` so it
    replays on THIS successful update, idempotently (AC8/AC9).

    Idempotency has THREE sources, not one, and all three are needed for the
    "a replay never duplicates content" guarantee to hold. A buffered item is
    skipped when its text is (a) already RENDERED as its own bullet in the live
    `body`'s target section — an exact whole-line identity, never a containment
    test over the body; see the block comment above for why that distinction is
    the difference between skipping an append and destroying the record —
    (b) already carried inline by THIS call (`pending_notes`/`pending_reflections` — the shape a
    retry of the same update takes during an outage), or (c) already queued by an
    earlier buffered record in this same pass (two failed calls carrying the same
    `--note` buffer two records, and deduping against the body alone folds both).
    Anything not yet present is appended to `args.note` / `args.reflection`, but
    ONLY when the target section (`## Progress` for notes, `## Devflow Reflection`
    for reflections) exists in the body — so a replay never turns a valid call
    into a structural abort against a truncated/malformed workpad.

    Returns True ONLY when every buffered item is now accounted for — either
    already present in the live body, or foldable because its section exists.
    Returns False when a buffered item could NOT be folded (its section is absent
    from this body), so the caller must NOT clear the buffer: the content stays
    buffered for a later, healthy body to replay, rather than being silently
    dropped along with the buffer file. A buffered reflection replays under the
    CALL's kind rather than its own: the record's durability matters more than
    its sub-section placement on this degraded path."""
    records = _read_workpad_buffer(comment_id)
    if not records:
        return False
    add_notes = []
    add_reflections = []
    # This call's own inline content. Deduping against it is what keeps the
    # retry-the-same-update shape from rendering the item twice — once from the
    # buffer, once from the flag. Only the BUFFERED copy is ever skipped; a caller
    # that deliberately passes the same `--note` twice in one call still gets both.
    _pending_notes = list(pending_notes or [])
    _pending_reflections = list(pending_reflections or [])
    # Resolve both target sections once, and read "already applied" out of the
    # rendered bullets they hold rather than out of the raw body text.
    _, _sections = _split_sections(body)
    _progress = _single_section_content(_sections, 'Progress')
    _reflections = _single_section_content(_sections, 'Devflow Reflection')
    for rec in records:
        if not isinstance(rec, dict):
            continue
        for n in rec.get('notes') or []:
            if (isinstance(n, str) and n
                    and not _note_already_rendered(_progress, n)
                    and n not in _pending_notes and n not in add_notes):
                add_notes.append(n)
        for rfl in rec.get('reflections') or []:
            if (isinstance(rfl, str) and rfl
                    and not _reflection_already_rendered(_reflections, rfl)
                    and rfl not in _pending_reflections
                    and rfl not in add_reflections):
                add_reflections.append(rfl)
    notes_replayable = '## Progress' in body
    reflections_replayable = '## Devflow Reflection' in body
    if add_notes and notes_replayable:
        args.note = list(args.note or []) + add_notes
    if add_reflections and reflections_replayable:
        args.reflection = list(args.reflection or []) + add_reflections
    # Safe to clear only when nothing was left un-replayed: any not-yet-present
    # item whose target section is absent stays buffered (return False).
    fully_replayed = (
        (not add_notes or notes_replayable)
        and (not add_reflections or reflections_replayable)
    )
    return fully_replayed


def _clear_workpad_buffer(comment_id) -> None:
    """Remove a comment's buffer file after its records have been replayed."""
    try:
        _workpad_buffer_path(comment_id).unlink(missing_ok=True)
    except OSError:
        pass


def _cmd_update_inner(args):
    # Resolve comment ID from the issue. update is stateless for callers.
    # cmd_id prints + sys.exits; we inline the lookup to capture the ID.
    marker = _workpad_marker(args.marker)
    repo = _repo_full()
    comment_id = None
    page = 1
    while True:
        try:
            r = _run([
                GH, 'api',
                (f'/repos/{repo}/issues/{args.issue}/comments'
                f'?page={page}&per_page=100'),
            ])
        except (subprocess.CalledProcessError, OSError) as e:
            _fail('update id-lookup', e)
        try:
            items = json.loads(r.stdout)
        except json.JSONDecodeError as e:
            _fail('update id-lookup', f"could not parse gh comments response: {e}")
        for c in items:
            if (c.get('body') or '').startswith(_marker_variants(marker)):
                comment_id = c['id']
                break
        if comment_id is not None or len(items) < 100:
            break
        page += 1
    if comment_id is None:
        # Deliberately exit 1 (not cmd_id's exit-2 "scanned-clean-absent"): unlike
        # `id`, `update` has no create-fallback to disambiguate toward, so "absent"
        # here is a caller error (update before create), not a benign first-run
        # signal. Callers resolve create-vs-resume via `id` (which DOES split 2/1);
        # `update` only ever runs against an already-resolved workpad, so it does
        # not carry the exit-2 contract.
        sys.stderr.write(
            f"workpad.py update: no workpad found for issue #{args.issue}; "
            f"call `workpad.py create` first\n"
        )
        sys.exit(1)

    # Fetch live body (re-fetch invariant).
    try:
        r = _run([
            GH, 'api',
            f'/repos/{repo}/issues/comments/{comment_id}',
            '--jq', '.body',
        ])
    except (subprocess.CalledProcessError, OSError) as e:
        _fail('update body-fetch', e)
    body = r.stdout

    # Hydration-race preconditions (issue #537, AC24). Phase 1 snapshots the workpad
    # comment ID and the exact stripped Status word BEFORE resetting Status, then
    # passes them here. We re-resolved the marker comment (above) and re-fetched its
    # body — if the LIVE comment ID or Status word no longer matches the snapshot,
    # the workpad was concurrently changed (a terminal backstop flip, a delete +
    # recreate, an operator edit), so ABORT before any mutation/PATCH rather than
    # overwrite the current state with a stale reset. Exit 4 = precondition mismatch
    # (distinct from 1=structural/absent and the tick exit paths). A deleted-and-not-
    # recreated workpad is already caught above (comment_id is None → exit 1).
    if args.expect_comment_id is not None and str(comment_id) != str(args.expect_comment_id):
        sys.stderr.write(
            f"workpad.py update: precondition mismatch — expected comment id "
            f"{args.expect_comment_id} but the live workpad is comment "
            f"{comment_id} (concurrent delete/recreate). No mutation/PATCH made.\n"
        )
        sys.exit(4)
    if args.expect_status is not None:
        _live_word = _status_word_from_body(body)
        if _live_word.lower() != args.expect_status.strip().lower():
            sys.stderr.write(
                f"workpad.py update: precondition mismatch — expected Status "
                f"{args.expect_status!r} but the live workpad Status is "
                f"{_live_word!r} (concurrent status change / terminal backstop "
                f"transition). No mutation/PATCH made.\n"
            )
            sys.exit(4)

    # Failed-write buffering/replay (issue #1214). Capture THIS call's own
    # append-only content first, so a PATCH failure buffers exactly it — never the
    # replayed content `_plan_buffer_replay` is about to fold in. Then fold any
    # previously-buffered content for this comment into `args` so it replays on
    # this (successful) PATCH, idempotently.
    # Kept as raw lists symmetric with `_own_reflections`; `_buffer_failed_change`
    # applies the single empty-string filter for both.
    _own_notes = list(args.note or [])
    _own_reflections = list(args.reflection or [])
    _own_kind = args.reflection_kind or _DEFAULT_REFLECTION_KIND
    if args.reflection_file:
        # A file-sourced reflection is buffered exactly like an inline one. This is
        # the case issue #1214 exists for: the mandated stop-path recipe delivers the
        # Blocked reflection in its OWN `--reflection-file` call carrying no inline
        # --note/--reflection, and that recipe's documented inline fallback covers a
        # *structural* error only — never a PATCH failure — so leaving the payload
        # uncaptured drops the run's terminal reflection on the one path the feature
        # was built to rescue. The read is memoized (see `_reflection_file_payload`),
        # so `_apply_mutations` below reuses this text rather than re-reading, which
        # is also what keeps the `-`/stdin arm single-read. Pulling the read forward
        # of `_apply_mutations` means a bad payload now reports before a
        # co-occurring structural fault rather than after it; both still abort the
        # whole call with exit 1 and no PATCH, which is the contract that matters.
        try:
            _own_reflections.append(_reflection_file_payload(args))
        except _UpdateError as e:
            sys.stderr.write(f"workpad.py update: {e}\n")
            sys.exit(1)
    if getattr(args, 'note_file', None):
        # A file-sourced note is buffered exactly like an inline --note, so a
        # PATCH failure preserves it — the note twin of the --reflection-file
        # rescue above (issue #1813 mirrors #1214). The read is memoized, so
        # `_apply_mutations` renders from the same text without re-reading, which
        # also keeps the `-`/stdin arm single-read.
        try:
            _own_notes.append(_note_file_payload(args))
        except _UpdateError as e:
            sys.stderr.write(f"workpad.py update: {e}\n")
            sys.exit(1)
    # Per-note budget (issue #2024): measured before the replay fold below, so a
    # buffer-replayed note is never re-measured (see _check_note_within_budget) —
    # re-measuring one would wedge the workpad permanently.
    try:
        for _n in _own_notes:
            _check_note_within_budget(_n)
    except _UpdateError as e:
        sys.stderr.write(f"workpad.py update: {e}\n")
        sys.exit(1)
    _buffer_safe_to_clear = _plan_buffer_replay(
        comment_id, body, args, _own_notes, _own_reflections)

    # `failed_ticks` collects *volatile* per-row tick misses (see _TickMatchError):
    # the call still applies and PATCHes every other mutation, then exits non-zero
    # naming the ticks that did not land. A *structural* _UpdateError still aborts
    # before any PATCH.
    failed_ticks = []
    try:
        body = _apply_mutations(body, args, failed_ticks)
    except _NoOpReplay as replay:
        # Pure replay: preserve the live body, skip PATCH, and emit the replay-specific
        # breadcrumb. Combined mutations never reach this arm; the class contract owns
        # the shared no-op semantics.
        if replay.kind == 'review-progress':
            sys.stderr.write(
                "workpad.py update: review boundary replay — every requested "
                "review row is already ticked; no Last updated refresh, no PATCH.\n"
            )
        else:
            sys.stderr.write(
                "workpad.py update: checkpoint replay — all requested checkpoint "
                "key(s) already present; no Last updated refresh, no PATCH.\n"
            )
        # Reclaim the buffer on this arm too. Reaching here means the call carried no
        # effective mutation beyond a supported replay. If the replay above had folded
        # any note or reflection, this arm would not have been taken. A True flag here
        # therefore means every buffered item was already present in the live body:
        # reclaimable, and nothing is being dropped by clearing. Without this the
        # buffer file survives repeated replay calls until a later update collects it.
        if _buffer_safe_to_clear:
            _clear_workpad_buffer(comment_id)
        if args.print_body:
            sys.stdout.write(body)
        _emit_update_outcome('replay')
        return
    except _UpdateError as e:
        sys.stderr.write(f"workpad.py update: {e}\n")
        # A structural failure aborts before any PATCH — but volatile tick misses
        # collected before the abort would otherwise be dropped from this call's
        # output entirely. Echo them too so a combined call (a tick miss + a later
        # structural fault) reports BOTH faults, not just the structural one.
        if failed_ticks:
            _report_failed_ticks(
                failed_ticks,
                f"additionally, {len(failed_ticks)} tick(s) did not resolve before "
                f"the abort (no PATCH was made — re-send the whole call)",
            )
        sys.exit(1)

    # Comment-size limit (issue #2024) — refuse a body over the cap BEFORE the
    # PATCH, and before the failed-write buffer in the PATCH-failure except below,
    # so a size-refused write leaves no buffered content to replay.
    try:
        _check_body_within_limit(_byte_len(body))
    except _UpdateError as e:
        sys.stderr.write(f"workpad.py update: {e}\n")
        sys.exit(1)
    # Write to a temp file and PATCH. The body always carries at least the
    # refreshed `Last updated`, so the PATCH is never a no-op even when every
    # requested tick was volatile. This path needs no leading-marker merge (the
    # one `cmd_patch` applies via `_merge_leading_markers`): `body` is mutated
    # from the live body re-fetched above, so a marker line it carries survives.
    with tempfile.NamedTemporaryFile(
        'w', suffix='.md', delete=False, encoding="utf-8",
    ) as tf:
        tf.write(body)
        tmp_path = tf.name
    global _UPDATE_PATCH_LANDED
    try:
        r = _run([
            GH, 'api', '-X', 'PATCH',
            f'/repos/{repo}/issues/comments/{comment_id}',
            '-F', f'body=@{tmp_path}',
            '--jq', '.body',
        ])
        # Mark the write observed on the statement after the PATCH returns, with
        # no cleanup between: the `finally` unlink below can raise EACCES/EIO,
        # and a flag set after it reports a landed PATCH as not-persisted.
        _UPDATE_PATCH_LANDED = True
    except (subprocess.CalledProcessError, OSError) as e:
        # The PATCH itself failed, so NO workpad change was persisted. Report any
        # volatile tick misses collected before the failure too — otherwise this
        # third exit path silently drops them (the very no-silent-loss invariant
        # this command establishes), leaving the operator unable to tell a clean
        # PATCH failure from one that also had unresolvable ticks.
        if failed_ticks:
            _report_failed_ticks(
                failed_ticks,
                f"the PATCH itself failed, so NO workpad change was persisted; "
                f"these {len(failed_ticks)} tick(s) had also not resolved",
            )
        # Buffer this call's OWN append-only content before failing (issue #1214),
        # so the note/reflection the PATCH dropped survives to be replayed by the
        # next successful call. Any previously-buffered records stay buffered (the
        # buffer is only cleared on a successful PATCH), so no content is lost.
        _buf_path = _buffer_failed_change(
            comment_id, _own_notes, _own_reflections, _own_kind)
        if _buf_path is not None:
            sys.stderr.write(
                f"workpad.py update: buffered this call's note/reflection content "
                f"to {_buf_path} for replay on the next successful update "
                f"(issue #1214).\n"
            )
        _fail('update patch', e)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    # The PATCH succeeded: drop the buffer file ONLY when `_plan_buffer_replay`
    # reported that every buffered item is now accounted for (folded into this
    # body or already present). When a buffered item could not be folded — its
    # target section was absent from this (truncated/malformed) body — the buffer
    # is left intact so a later healthy body replays it, never dropping content
    # along with the file. Idempotency is guaranteed by the presence check, so a
    # retained-and-later-replayed item is replay-and-skip, never a duplicate.
    if _buffer_safe_to_clear:
        _clear_workpad_buffer(comment_id)
    # Issue #814: the patched body is echoed only under `--print-body`, or on the
    # volatile-tick-miss path below. This one statement is reached by BOTH the clean
    # return and the miss exit (the `failed_ticks` branch is evaluated after it), so
    # a flag-only condition here would also silence the miss path — which keeps its
    # echo deliberately, because the failure-isolation contract requires the caller
    # to re-resolve a section-scoped checkbox index before re-ticking and the body is
    # the row inventory that resolution reads.
    if args.print_body or failed_ticks:
        sys.stdout.write(r.stdout)

    # Issue #814: one short success breadcrumb on the exit-0 PATCH path, so a
    # successful call is never byte-identical to one the cloud permission matcher
    # silently refused (a denial prints nothing). It carries the Status value read
    # back from the PATCH response on a `--status` call: that read-back is the one
    # check an exit code cannot discharge, because `gh api -X PATCH` can return
    # success while the comment body is unchanged. Written independently of
    # `--print-body`, and NOT written on the volatile-miss path below — a
    # success-shaped line beside a failing exit code would re-create on stderr the
    # split the exit-code rule exists to prevent.
    # Read the Status back from the PATCH response on ANY `--status` call that
    # PATCHed — including one whose tick missed. Three unobserved states are reported
    # distinctly rather than collapsed onto one token: an EMPTY response (a throttled
    # or oversized write — the comment itself may be perfectly healthy, so pointing
    # the reader at a corrupt body would misdirect them), a non-empty response
    # carrying no Status line, and a resolved value. None renders as a bare empty
    # clause a reader could mistake for "no --status was set". The read goes through
    # the shared value reader, never a second regex site.
    _status_clause = ''
    _live = ''
    _read_back = ''
    if args.status:
        if not r.stdout:
            _read_back = '(empty response)'
        else:
            _live = _status_value_from_body(r.stdout)
            _read_back = _live or '(not found)'
        _status_clause = f"; Status: {_read_back}"
    if not failed_ticks:
        sys.stderr.write(
            f"workpad.py update: PATCHed comment {comment_id}{_status_clause}\n"
        )
    # The read-back is only a guard if something compares it. Leaving the comparison
    # to prose alone lets a reader skim the line for "breadcrumb present, exit 0" and
    # advance over a PATCH that returned 200 with the comment body unchanged, so the
    # mismatch is made machine-observable here. Unlike the success breadcrumb above,
    # this line is written on the volatile-tick-miss path too: it is failure-shaped,
    # so it composes with the miss report instead of re-creating the success/failure
    # split — and that path is where a `--status` write is most likely to ride along
    # with a tick, so suppressing it would fail open exactly where the mismatch is
    # most likely. It is a WARNING, not a failure: the PATCH call itself succeeded and
    # the caller owns the re-issue decision. The comparison reads `_live` — the value
    # the reader above resolved — never a re-parse of the rendered clause, so the
    # guard and the breadcrumb cannot disagree about what was read back, and it
    # reports the same distinct unreadable token the clause carries rather than
    # collapsing the two unobserved states.
    # Derive this once: both PATCH-succeeded tails below pick their outcome token from
    # it, and deriving it twice would let them disagree about the same read-back.
    _status_unverified = False
    if args.status:
        _want = _strip_status_glyph(args.status).strip().lower()
        _got = _strip_status_glyph(_live).strip().lower()
        if _want != _got:
            _status_unverified = True
            sys.stderr.write(
                f"workpad.py update: WARNING: the PATCH response reads Status "
                f"{_got or _read_back!r}, not the requested {_want!r} — the write "
                f"may not have landed; follow up with a --status-only update.\n"
            )

    # Volatile tick failures: the PATCH landed (other mutations applied), but
    # report each unresolved tick to stderr and exit non-zero so the orchestrator
    # sees exactly which tick(s) failed. The body PATCHed, so the caller must
    # re-tick ONLY the named row(s) — NOT re-send the whole call (its --status/
    # --note/--reflection already landed; re-sending would double-write notes).
    if failed_ticks:
        _report_failed_ticks(
            failed_ticks,
            f"PATCHed, but {len(failed_ticks)} tick(s) did not resolve (the call's "
            f"other mutations were applied — re-tick only these row(s), do not "
            f"re-send the call)",
        )
        _emit_update_outcome(
            'landed-partial-ticks-status-unverified' if _status_unverified
            else 'landed-partial-ticks'
        )
        sys.exit(1)

    _emit_update_outcome(
        'landed-status-unverified' if _status_unverified else 'landed'
    )


def _apply_section_ticks(
    sections, section_name, flag_base, substr_texts, index_ns, failed_ticks,
):
    """Tick rows in the named section (`## Progress`/`## Plan`/`## Acceptance
    Criteria`) from the substring and index requests.

    Structural failure (the section is absent while ticks were requested) raises
    `_UpdateError` to abort the whole call. A per-row miss (substring zero/multiple,
    out-of-range/already-ticked index) is *volatile*: it is appended to
    `failed_ticks` as a flag-named descriptor and the remaining ticks still apply.
    Substring ticks are processed before index ticks; index positions count every
    `[ ]`/`[x]` row, so a prior substring tick never shifts an index target — though
    a substring tick that lands on the *same* row a later index targets makes that
    index report a benign "already ticked" volatile miss."""
    if not substr_texts and not index_ns:
        return
    idx = _find_section(sections, section_name)
    if idx is None:
        raise _UpdateError(f"section '## {section_name}' not found")
    heading, content = sections[idx]
    for text in substr_texts:
        try:
            content = _tick_checkbox(content, text, section_name)
        except _TickMatchError as e:
            failed_ticks.append(f"--tick-{flag_base} {text!r} — {e}")
    for n in index_ns:
        try:
            content = _tick_checkbox_by_index(content, n, section_name)
        except _TickMatchError as e:
            failed_ticks.append(f"--tick-{flag_base}-n {n} — {e}")
    sections[idx] = (heading, content)


# The marker parse-acs.py appends to a post-merge criterion, and the byte-for-byte
# token the Phase 3.4 AC gate excludes ("a criterion whose checkbox line ends in
# `(post-merge)`"). The terminal Complete gate reuses the same exclusion so its
# hard-fail set matches the gate's blocking set exactly.
_POST_MERGE_MARKER = '(post-merge)'


def _is_single_line(text: str) -> bool:
    """True when `text` holds no line boundary *as the row parser sees one*.

    Shares the consumer's own operation instead of re-deriving its contract. The
    checkbox-row parsers (`_find_checkbox_row`, `_post_merge_flags`, `_unticked_rows`)
    split with `str.splitlines()`, which breaks on far more than `\\n`/`\\r`: `\\v`,
    `\\f`, `\\x1c`-`\\x1e`, `\\x85` (NEL), `\\u2028` (LINE SEPARATOR) and `\\u2029`
    (PARAGRAPH SEPARATOR). A membership test for `'\\n'`/`'\\r'` accepts a *superset*
    of what `splitlines()` treats as one line, so any of those other separators would
    still split a checkbox row in two — a guard's accepted-input set must be a subset
    of its consumer's, never a guess at it. `''.join(text.splitlines()) == text` holds
    exactly when `splitlines()` finds no boundary (the empty string included, and a
    trailing separator caught too). A few section helpers (`_split_details`,
    `_append_progress_note`) split on `'\\n'` alone — a strict subset of the
    `splitlines()` boundaries — so this guard over-covers them too, never under.
    The same `splitlines()` idiom collapses multi-line `--reflection` text above."""
    return ''.join(text.splitlines()) == text


# Workpad size limits (issue #2024). GitHub's comment cap is 65,536 CHARACTERS;
# enforcing it over UTF-8 BYTES is conservative (byte length >= character count).
_NOTE_BYTE_BUDGET = 2048
_COMMENT_BYTE_LIMIT = 65536


def _byte_len(text: str) -> int:
    """UTF-8 byte length of `text` (issue #2024)."""
    return len(text.encode('utf-8'))


def _check_note_within_budget(note: str) -> None:
    """Refuse a single caller-supplied Progress note over `_NOTE_BYTE_BUDGET`
    UTF-8 bytes, raising `_UpdateError` before any PATCH (issue #2024). Applied
    only to `--note`/`--note-file` text — never a tool-composed Progress row or a
    buffer-replayed note, which the caller cannot shorten — because the caller
    checks it against the pre-replay caller-note list, not at the shared
    renderer."""
    n = _byte_len(note)
    if n > _NOTE_BYTE_BUDGET:
        raise _UpdateError(
            f"a --note/--note-file Progress note is {n} bytes, over the "
            f"{_NOTE_BYTE_BUDGET}-byte per-note budget (measured as UTF-8 bytes); "
            f"shorten it or split it across notes. No PATCH was made."
        )


def _check_body_within_limit(nbytes: int) -> None:
    """Refuse a workpad body over `_COMMENT_BYTE_LIMIT` UTF-8 bytes, raising
    `_UpdateError` before any PATCH (issue #2024). `nbytes` is measured by the
    caller so both PATCH routes — the in-memory update body and the file `cmd_patch`
    hands `_patch_comment_body` — check the SAME limit and neither can issue an
    oversize PATCH."""
    if nbytes > _COMMENT_BYTE_LIMIT:
        raise _UpdateError(
            f"the resulting comment body is {nbytes} bytes, over GitHub's "
            f"{_COMMENT_BYTE_LIMIT}-byte comment limit (the reported count is a "
            f"byte count, measured as UTF-8 bytes); shorten the workpad. No PATCH "
            f"was made."
        )


def _ends_with_post_merge(text: str) -> bool:
    """True when `text` carries the `(post-merge)` marker in TERMINAL position.
    Trailing whitespace is stripped first, so a stray space or newline can't mask
    the comparison (the anti-evasion the retag guard and `_unticked_rows` share)."""
    return text.rstrip().endswith(_POST_MERGE_MARKER)


def _pair_appends_post_merge(old: str, new: str, row_text: str) -> bool:
    """True when a `--rewrite-ac` OLD/NEW pair *appends* the `(post-merge)` tag to
    the row it targets: NEW ends with the marker while NEITHER the OLD argument nor
    `row_text` — the matched row's CURRENT label text, resolved by
    `_find_checkbox_row`, the same resolution the rewrite itself uses — already
    does. This is exactly the mid-run retag channel §3.4 requires a rationale
    `--note` for (issue #338): a pair that tags a previously-untagged criterion.

    Returns False (no rationale needed) when the pair *removes* the tag, or when
    the row it targets is ALREADY terminally tagged — a text tweak on an
    already-post-merge row creates no new deferral. Consulting `row_text` rather
    than the OLD argument alone is what makes that exemption hold for an OLD
    substring that does not itself span the tag (e.g. `--rewrite-ac "AC two"
    "AC two clarified (post-merge)"` against a row already reading
    `AC two (post-merge)`), which the argument-string-only form false-refused.

    The OLD conjunct is retained: a pair whose OLD spans the tag while the row is
    non-terminally tagged is the crafted multi-pair shuttle the state-based
    backstop in `_apply_mutations` exists to catch (it is not caught here, by
    design — see that backstop's comment)."""
    return (_ends_with_post_merge(new)
            and not _ends_with_post_merge(old)
            and not _ends_with_post_merge(row_text))


def _unticked_rows(content: str) -> tuple[list[str], list[str]]:
    """Split a checkbox section's still-unticked `- [ ]` rows into
    (non_post_merge, post_merge) by whether the row text ends in the
    `(post-merge)` marker (the Phase 3.4 exclusion). Non-checkbox lines
    (placeholders, prose) are ignored. Read-only — never mutates a row."""
    non_pm, pm = [], []
    for line in content.splitlines():
        m = _CHECKBOX_ROW_RE.match(line)
        if not m or m.group(2) != '[ ]':
            continue
        text = m.group(4)
        (pm if _ends_with_post_merge(text) else non_pm).append(text)
    return non_pm, pm


def _post_merge_flags(content: str) -> list[bool]:
    """Per-row `(post-merge)`-terminal flags for a checkbox section's rows, in
    document order — one entry per checkbox row, across EVERY tick state (`[ ]` and
    `[x]` alike). Non-checkbox lines (placeholders, prose) contribute nothing.

    This is the retag backstop's population, and it is deliberately WIDER than
    `_unticked_rows`' (which is `[ ]`-only because the Phase 3.4 terminal gate only
    reconciles still-unmet criteria): a marker landing on an already-`[x]` row is
    still a net-added `(post-merge)` row. Read-only — never mutates a row."""
    return [
        _ends_with_post_merge(m.group(4))
        for line in content.splitlines()
        if (m := _CHECKBOX_ROW_RE.match(line))
    ]


def _net_adds_post_merge(pre: list[bool], post: list[bool]) -> bool:
    """True when the `--rewrite-ac` loop tagged a criterion that was not terminally
    `(post-merge)` before it ran — i.e. some row transitioned False -> True.

    Compares POSITIONALLY, not by aggregate count. `_rewrite_checkbox` replaces one
    line in place (never inserts, deletes, or reorders), so a row's index is stable
    across the whole loop and index `i` before is index `i` after. A count-based
    comparison would miss a call that removes the tag from one row while adding it
    to another: the totals net to zero while a criterion was silently deferred.

    Defensive: a differing row count means the positional mapping is meaningless, so
    the comparison cannot answer the question at all. Fail CLOSED — treat it as a
    net-add. `_apply_mutations` rejects a multi-line NEW (`_is_single_line`) before the
    loop runs, so `_rewrite_checkbox` should not be able to change the row count; this
    branch is the backstop for that guard rather than dead code, and it exists so that
    any path which *does* change the count can never silently downgrade this guard to
    an aggregate count (which is blind to a remove-one/add-one swap — exactly the hole
    the positional comparison closes). Do not "simplify" it back to `sum(post) >
    sum(pre)`: that comparison returns False on a shorter-but-newly-tagged post state."""
    if len(pre) != len(post):
        return True
    return any(now and not before for before, now in zip(pre, post))


# ── Completion verification-flight evidence gate (issue #1087) ──────────────────
# The implement engine's terminal `--status Complete` write must be backed by a
# current, machine-readable verification-flight record for the run's final in-env
# verification command. The validated flight key rides on the EXISTING keyed-
# checkpoint marker family (issue #537) — no second marker family is minted — under
# a fixed `completion-verification:<flight-key>` key namespace. The record itself is
# resolved from the repo-root-anchored canonical flight directory and validated by
# the sibling check-completion-evidence module's implement-completion entry point.
_VERIFICATION_FLIGHT_DIRNAME = os.path.join('.prflow', 'tmp', 'verification-flights')
_COMPLETION_MARKER_KEY_PREFIX = 'completion-verification:'
# A flight key is a sha256 hex digest; a non-hex value is a malformed marker.
_COMPLETION_FLIGHT_KEY_RE = re.compile(r'\A[0-9a-f]{16,}\Z')
# Both the current `prflow:` and the superseded `devflow:` checkpoint spellings are
# read per-record (issue #1003 renamed the marker namespace and rewrites no history).
_COMPLETION_MARKER_RE = re.compile(
    r'<!--\s*(?:pr|dev)flow:checkpoint\s+completion-verification:([^\s]+?)\s*-->'
)
_COMPLETION_VALIDATOR_CACHE = None


def _load_completion_validator():
    """Lazily import the sibling `check-completion-evidence.py` module, once.

    Returns the imported module, or None when the sibling is absent beside this
    `workpad.py` copy (the standalone-deployment closure — `lib/implement-stop-guard.sh`
    and the suite's guard sandboxes copy `workpad.py` without its evidence siblings).
    Imported by file path via importlib because the sibling's filename carries a
    hyphen and is not importable as a module name; the result is memoized so a
    combined record+Complete call does not re-exec the sibling twice. Tests exercise
    the standalone-copy arm by monkeypatching this function to return None."""
    global _COMPLETION_VALIDATOR_CACHE
    if _COMPLETION_VALIDATOR_CACHE is not None:
        return _COMPLETION_VALIDATOR_CACHE
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'check-completion-evidence.py')
    if not os.path.exists(path):
        return None
    try:
        spec = importlib.util.spec_from_file_location(
            '_devflow_completion_evidence', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception:
        return None
    _COMPLETION_VALIDATOR_CACHE = mod
    return mod


def _devflow_repo_root(args=None) -> str:
    """The repository root the completion-evidence gate anchors on: an explicit
    `--repo-root`, else the git top-level, else cwd. Reuses the module's #295
    `_repo_root()` helper (the Windows-safe native-git resolver) rather than
    re-spawning `git rev-parse`."""
    explicit = getattr(args, 'repo_root', None) if args is not None else None
    return explicit or _repo_root() or os.getcwd()


def _completion_marker_keys(progress_content: str) -> list[str]:
    """Every flight key carried by a `completion-verification:` checkpoint marker in
    the ## Progress content. A marker outside ## Progress is not found here (the
    caller passes only the Progress section), so it is treated as absent — fail
    closed. Duplicate markers surface as a >1-length list."""
    return _COMPLETION_MARKER_RE.findall(progress_content or '')


def _strip_completion_marker_rows(content: str) -> str:
    """Remove any ## Progress row carrying a `completion-verification:` marker, so a
    later validated key replaces the prior one rather than accumulating."""
    kept = [ln for ln in content.splitlines(keepends=True)
            if not _COMPLETION_MARKER_RE.search(ln)]
    return ''.join(kept)


# ── CI-derived completion-evidence family (issue #1611) ────────────────────────
#
# Issue #1607 made a CI reading this repository's LOCAL/interactive whole-suite
# completion gate, but `_completion_evidence_verdict` could recognise only an
# in-environment verification-flight pass. This is the SECOND accepted family: a
# local run that established a green required check for the commit it pushed records
# that reading here, in a marker family DISTINCT from `completion-verification:`, so
# a reader tells an in-env suite pass from a CI reading without inspecting any command
# string. The payload is a base64url-unpadded JSON object carrying the re-audit fields
# (head SHA, tier, run URL, and a checks list of name/conclusion pairs); it rides the same
# keyed-checkpoint marker family, validated OFFLINE by the sibling module's
# `validate_implement_completion_ci`.
# Both the `prflow:` and superseded `devflow:` spellings are read per record (#1003).
_COMPLETION_CI_MARKER_KEY_PREFIX = 'completion-ci:'
# Composed from `_MARKER_NS_RE` (as the review-coverage grammars are) rather than
# re-spelling the `(?:pr|dev)flow` alternation, so the confirmation-gated retirement
# of the superseded `devflow:` spelling reaches this grammar too. That constant fixes
# the single space `_checkpoint_marker` writes, so this matcher is stricter than the
# older hand-rolled `_COMPLETION_MARKER_RE` — the safe direction, since a marker shape
# this gate cannot read is unestablished (refusing the Complete write, never admitting
# it). Both spellings are still read per record (#1003).
_COMPLETION_CI_MARKER_RE = re.compile(
    _MARKER_NS_RE + r'checkpoint completion-ci:([^\s]+?) -->'
)


def _encode_ci_payload(record: dict) -> str:
    """Encode a CI-evidence record dict as a base64url-unpadded token, so the payload
    is a single whitespace-free `[^\\s]+` the marker grammar and the checkpoint key
    grammar (`[A-Za-z0-9._:-]+`, which includes `-` and `_`) both accept."""
    raw = json.dumps(record, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


def _decode_ci_payload(payload: str) -> object:
    """Decode a CI-evidence marker payload back to its JSON object. Best-effort: a
    payload that is not valid base64url or not valid JSON returns None, which the
    validator treats as a missing-evidence (non-object) record rather than raising."""
    try:
        pad = '=' * (-len(payload) % 4)
        raw = base64.urlsafe_b64decode(payload + pad)
        return json.loads(raw.decode('utf-8'))
    except Exception:
        return None


def _completion_ci_marker_payloads(progress_content: str) -> list[str]:
    """Every payload carried by a `completion-ci:` checkpoint marker in the ##
    Progress content. A marker outside ## Progress is not found here (the caller passes
    only the Progress section), so it is treated as absent — fail closed. Duplicate
    markers surface as a >1-length list."""
    return _COMPLETION_CI_MARKER_RE.findall(progress_content or '')


def _strip_completion_ci_marker_rows(content: str) -> str:
    """Remove any ## Progress row carrying a `completion-ci:` marker, so a later
    validated record replaces the prior one rather than accumulating."""
    kept = [ln for ln in content.splitlines(keepends=True)
            if not _COMPLETION_CI_MARKER_RE.search(ln)]
    return ''.join(kept)


# ── Mid-phase resume-point family (issue #1876) ────────────────────────────────
#
# The Phase 3 mid-phase re-anchor used to re-read EVERY member of the phase's
# reference set to recover the step position after a nested-skill return; this family
# records that step position durably so only the member holding it need be re-read.
# It is a NAVIGATION aid and NEVER evidence: no verdict/gate reads it (its reader is a
# standalone subcommand wired into no `_*_verdict`), which is what keeps a run's
# self-report out of any verification decision (issue #1489). It rides the same
# keyed-checkpoint marker family (issue #537); the payload is a base64url-unpadded
# token of the resume-point text, so it is a single whitespace-free `[^\s]+` the marker
# and checkpoint-key grammars both accept, and it legitimately CHANGES between calls
# (each mid-phase invocation records a fresh point), so the producer strips the prior
# row and appends the new one — the reader returns the sole surviving payload. Both the
# `prflow:` and superseded `devflow:` spellings are read per record (#1003).
_RESUME_POINT_MARKER_KEY_PREFIX = 'resume-point:'
_RESUME_POINT_MARKER_RE = re.compile(
    _MARKER_NS_RE + r'checkpoint resume-point:([^\s]+?) -->'
)


def _encode_resume_point(text: str) -> str:
    """Encode resume-point text as a base64url-unpadded token (whitespace-free), so it
    fits the marker grammar and the checkpoint key grammar (`[A-Za-z0-9._:-]+`)."""
    return base64.urlsafe_b64encode(text.encode('utf-8')).rstrip(b'=').decode('ascii')


def _decode_resume_point(payload: str) -> str | None:
    """Decode a resume-point marker payload back to its text. Best-effort: a payload
    that is not valid base64url or not valid UTF-8 returns None, so a malformed marker
    reads as absent rather than raising."""
    try:
        pad = '=' * (-len(payload) % 4)
        return base64.urlsafe_b64decode(payload + pad).decode('utf-8')
    except Exception:
        return None


def _resume_point_marker_payloads(progress_content: str) -> list[str]:
    """Every payload carried by a `resume-point:` checkpoint marker in the ## Progress
    content. A marker outside ## Progress is not passed here, so it reads as absent."""
    return _RESUME_POINT_MARKER_RE.findall(progress_content or '')


def _strip_resume_point_marker_rows(content: str) -> str:
    """Remove any ## Progress row carrying a `resume-point:` marker, so a later record
    replaces the prior one rather than accumulating."""
    kept = [ln for ln in content.splitlines(keepends=True)
            if not _RESUME_POINT_MARKER_RE.search(ln)]
    return ''.join(kept)


def _validate_ci_evidence(args, payload: str) -> None:
    """Validate a specific CI-derived completion-evidence marker payload.

    Raises a structural `_UpdateError` (no PATCH) on an absent validator sibling, an
    internal validator failure, or a non-pass verdict. Returns None on a clean pass.
    Mirrors `_validate_flight_key`'s failure shape."""
    validator = _load_completion_validator()
    if validator is None or not hasattr(validator, 'validate_implement_completion_ci'):
        # The standalone-copy arm (or an older sibling without the CI entry point):
        # fail closed BEFORE any PATCH with the missing-evidence token.
        raise _UpdateError(
            "completion evidence [missing-evidence]: the completion-evidence "
            "validator module (check-completion-evidence.py) with a CI-derived "
            "entry point is not available beside this workpad.py copy, so a "
            "--status Complete write cannot be backed by CI-derived evidence. "
            "No PATCH was made."
        )
    record = _decode_ci_payload(payload)
    root = _devflow_repo_root(args)
    try:
        token, detail = validator.validate_implement_completion_ci(record, root)
    except Exception as e:
        raise _UpdateError(
            f"completion evidence: the CI validator raised an internal error "
            f"({e.__class__.__name__}); treating as unestablished. No PATCH was made."
        )
    if token != 'pass':
        raise _UpdateError(
            f"completion evidence rejected [{token}]: {detail}. No PATCH was made."
        )


# ── Review-coverage record + disposition (issue #1453) ─────────────────────────
#
# A run's Phase 3 review pass can fall short — a shadow that was not verified, a
# reviewer roster short of the expected set, a skipped checklist step — and before
# this record the only trace was free-text prose in a `## Progress` note, which no
# reader could resolve. These constants give the fact a machine-readable home so the
# terminal `--status Complete` gate can refuse a silent shortfall.
#
# The record rides the EXISTING keyed-checkpoint marker family (issue #537) under a
# fixed `review-coverage:` key namespace carrying a four-axis payload, exactly as
# `completion-verification:` carries a flight key. That family — not the
# `_REQUIRED_ARTIFACTS` literal-key family — is the right precedent: the payload
# legitimately CHANGES between calls, and `--checkpoint`'s replay semantics key on
# the whole key string, so a second call with a different payload would insert a
# SECOND independent row rather than replacing the first, leaving two records of
# different vintage with nothing to say which is authoritative. So the producer
# strips the prior row and appends a fresh one, and the reader refuses on anything
# other than exactly one record.
_REVIEW_COVERAGE_KEY_PREFIX = 'review-coverage:'
_REVIEW_COVERAGE_DISPOSITION_KEY_PREFIX = 'review-coverage-disposition:'
# Both the current `prflow:` and superseded `devflow:` spellings are read per record
# (issue #1003 renamed the marker namespace and rewrote no history). The coverage
# pattern cannot collide with the disposition one: `review-coverage:` requires the
# colon immediately after `review-coverage`, which `review-coverage-disposition:`
# does not have.
# Composed from `_MARKER_NS_RE` rather than re-spelling the alternation, so the
# confirmation-gated retirement of the superseded spelling reaches these grammars
# too. That constant fixes the single space `_checkpoint_marker` writes, making
# these two stricter than the older hand-rolled `_COMPLETION_MARKER_RE` — which is
# the safe direction here: a marker shape this gate cannot read is UNESTABLISHED,
# which refuses the Complete write rather than admitting it.
_REVIEW_COVERAGE_MARKER_RE = re.compile(
    _MARKER_NS_RE + r'checkpoint review-coverage:([^\s]+?) -->'
)
_REVIEW_COVERAGE_DISPOSITION_MARKER_RE = re.compile(
    _MARKER_NS_RE + r'checkpoint review-coverage-disposition:([^\s]+?) -->'
)
# The disposition's REASON lives in the row's visible text rather than the marker
# key, because `_CHECKPOINT_KEY_RE`'s grammar (`[A-Za-z0-9._:-]`) admits neither
# spaces nor any of base64's `+/=`, so an encoded reason could not ride the key at
# all. This literal is therefore a producer/consumer contract: the producer renders
# it and this pattern reads it back off the same line.
def _review_coverage_disposition_reason_re(gap: str):
    """The reason pattern for ONE gap, anchored on that gap's own name.

    Anchoring on the gap the marker reported — rather than accepting any
    `gap=[a-z-]+` — is what stops a row whose marker says one gap and whose visible
    text says another from binding the wrong reason to the wrong gap."""
    return re.compile(
        r'review-coverage disposition — gap=' + re.escape(gap)
        + r'; reason: (.*?)\s*<!--'
    )
# The record's axes, declared ONCE as a member table in the shape
# `_REQUIRED_ARTIFACTS` established, with every view below DERIVED from it — so a
# fifth axis is added in one literal rather than in every derived view below, where
# omitting the `clean` entry would make the axis unconditionally dirty and omitting
# `gap` would raise inside the gap derivation at Complete time. Prose mirrors of
# these vocabularies live in the implement phase files and the review-and-fix
# references and cannot import them, so before changing a vocabulary grep
# `record-review-coverage` and `dispatch=` across `skills/**` and reconcile every
# hit in the same commit.
#   `values` — the axis's CLOSED vocabulary. `unestablished` is a first-class member
#     of every axis because an unresolvable fact must be recordable as unknown;
#     collapsing it onto a clean value is the fail-open this gate exists to close.
#   `clean`  — the value(s) that are not a shortfall. A record is COMPLETE only when
#     every axis holds one of its own.
#   `gap`    — the gap token the axis reports when it is not clean. `coverage` and
#     `dispatch` are two facts about the same shadow pass, so both report
#     `shadow-coverage`, keeping the disposition vocabulary to the three gaps a
#     human actually reasons about.
_REVIEW_COVERAGE_AXIS_SPECS = (
    {
        # `not-applicable` is the REJECT arm: the loop routes a REJECT straight to
        # Loop Exit without a convergence-time shadow trigger, so no shadow was owed
        # and there is no coverage to report. It is CLEAN because reporting a gap
        # here would refuse a pass that skipped nothing — see the `dispatch` axis
        # below, which carries the same value for the same reason.
        'name': 'coverage',
        'values': ('full', 'not-applicable', 'not-verified', 'unestablished'),
        'clean': ('full', 'not-applicable'),
        'gap': 'shadow-coverage',
    },
    {
        # `not-applicable` is CLEAN and `never` is not, because they are different
        # facts: `never` is a shadow the run OWED and did not dispatch (the #1230
        # abuse this gate refuses), while `not-applicable` is a pass whose shadow
        # was never owed — a REJECT verdict, which the loop routes straight to Loop
        # Exit without a convergence-time shadow trigger. Without the distinction the
        # severity-aware soft-proceed, whose whole contract is "do NOT block; the PR
        # is review-ready", could never reach Complete.
        'name': 'dispatch',
        'values': ('attempted', 'not-applicable', 'never', 'unestablished'),
        'clean': ('attempted', 'not-applicable'),
        'gap': 'shadow-coverage',
    },
    {
        # `not-applicable` is CLEAN for the same reason it is on the two axes above,
        # and only ever alongside them: a pass that owed no shadow measured no roster,
        # so `unestablished` would report a gap against a measurement nobody skipped.
        # `_review_coverage_incoherence` refuses it in any other combination, so it
        # cannot launder a short roster on a pass that DID dispatch.
        'name': 'roster',
        'values': ('complete', 'not-applicable', 'short', 'unestablished'),
        'clean': ('complete', 'not-applicable'),
        'gap': 'roster',
    },
    {
        # `skipped-intentional` is the shadow reference's diff-profile-driven
        # checklist skip (small_diff + config_only), which that reference makes
        # explicitly NOT a coverage shortfall — so it is CLEAN, unlike bare `skipped`.
        # `not-applicable` carries the no-shadow-owed meaning it carries on the other
        # three axes, and is likewise legal only when all four hold it.
        'name': 'checklist',
        'values': ('complete', 'not-applicable', 'skipped-intentional', 'skipped',
                   'unestablished'),
        'clean': ('complete', 'not-applicable', 'skipped-intentional'),
        'gap': 'checklist',
    },
)
def _validate_review_coverage_axis_specs(specs) -> None:
    """Enforce the axis table's own invariants at import, so a table edit cannot make
    the gate fail OPEN silently.

    The dangerous edit is adding `unestablished` to an axis's `clean` tuple: that
    turns the one value the whole design exists to refuse into a passing one, and no
    test of the gate's behavior would necessarily notice. A typo in `clean` is the
    mirror-image failure (an axis permanently dirty). The value-shape rule keeps the
    colon-joined payload and the marker grammar round-trippable: a value carrying a
    colon or whitespace would be written by the producer and then read back as a
    malformed record, refusing the run for a reason no message could explain."""
    seen = set()
    for spec in specs:
        if set(spec) != {'name', 'values', 'clean', 'gap'}:
            raise AssertionError(
                f'review-coverage axis spec {spec!r} must declare exactly '
                'name/values/clean/gap')
        name = spec['name']
        if name in seen:
            raise AssertionError(f'duplicate review-coverage axis {name!r}')
        seen.add(name)
        if not spec['gap']:
            raise AssertionError(f'review-coverage axis {name!r} declares no gap')
        if not set(spec['clean']) <= set(spec['values']):
            raise AssertionError(
                f"review-coverage axis {name!r} has clean values outside its "
                'vocabulary')
        if 'unestablished' not in spec['values']:
            raise AssertionError(
                f"review-coverage axis {name!r} must admit 'unestablished'")
        if 'unestablished' in spec['clean']:
            raise AssertionError(
                f"review-coverage axis {name!r} treats 'unestablished' as clean, "
                'which would fail the gate OPEN on an unresolved fact')
        for value in spec['values']:
            if not re.fullmatch(r'[A-Za-z0-9._-]+', value):
                raise AssertionError(
                    f'review-coverage value {value!r} does not round-trip through '
                    'the colon-joined payload and the marker grammar')


_validate_review_coverage_axis_specs(_REVIEW_COVERAGE_AXIS_SPECS)
_REVIEW_COVERAGE_AXES = tuple(s['name'] for s in _REVIEW_COVERAGE_AXIS_SPECS)
_REVIEW_COVERAGE_VOCABULARY = {s['name']: s['values']
                               for s in _REVIEW_COVERAGE_AXIS_SPECS}
_REVIEW_COVERAGE_CLEAN = {s['name']: s['clean'] for s in _REVIEW_COVERAGE_AXIS_SPECS}
_REVIEW_COVERAGE_AXIS_GAP = {s['name']: s['gap'] for s in _REVIEW_COVERAGE_AXIS_SPECS}
# `dict.fromkeys` preserves first-seen order, so the gap vocabulary keeps the axis
# table's own order rather than a hand-maintained second one.
_REVIEW_COVERAGE_GAPS = tuple(
    dict.fromkeys(s['gap'] for s in _REVIEW_COVERAGE_AXIS_SPECS))
# The CLOSED cause-class vocabulary a `--review-coverage-disposition` must name
# (issue #1984). It rides the disposition marker key as `…:<gap>:<cause-class>`, so a
# member must stay colon-free. Admissibility lives in
# `_review_coverage_disposition_cause_rejection`; do not restate it here.
_REVIEW_COVERAGE_CAUSE_CLASSES = ('environment-denial', 'dispatched-but-lost')
if any(':' in c for c in _REVIEW_COVERAGE_CAUSE_CLASSES):
    # An explicit raise (not a bare `assert`, which `python3 -O` strips) pins the
    # marker-key round-trip invariant for this producer/consumer contract.
    raise AssertionError(
        'a cause class must be colon-free to round-trip through the disposition marker key')
# Shadow-review roster membership (issue #1512): the per-member dispatch enumeration
# `_review_roster_incoherence` cross-checks the summary `roster` axis against, so a
# `complete` claim omitting an always-on member is refused rather than self-reported.
_SHADOW_ALWAYS_ON_MEMBERS = (
    'code-reviewer', 'silent-failure-hunter', 'comment-analyzer',
    'requesting-code-review')
_SHADOW_GATED_MEMBERS = ('type-design-analyzer', 'pr-test-analyzer')
_SHADOW_ROSTER_MEMBERS = _SHADOW_ALWAYS_ON_MEMBERS + _SHADOW_GATED_MEMBERS
_ROSTER_MEMBER_STATUSES = ('dispatched', 'gated-off', 'missing')
_REVIEW_ROSTER_KEY_PREFIX = 'review-roster:'
# Composed from `_MARKER_NS_RE` like the coverage grammars, so the confirmation-gated
# retirement of the superseded namespace reaches it too. The capture holds
# `<member>:<status>`; neither token carries a colon, so one split on ':' is unambiguous.
_REVIEW_ROSTER_MARKER_RE = re.compile(
    _MARKER_NS_RE + r'checkpoint review-roster:([^\s]+?) -->'
)
# A member enumerated twice resolves to this sentinel, whose status is unresolvable, so
# `_review_roster_incoherence` refuses it — the fail-closed posture
# `_review_coverage_dispositions` takes for a duplicated gap.
_REVIEW_ROSTER_DUPLICATE = object()
# issue #1510: the record's optional as-of anchor — the trailing `<head>:<asof>` fields
# appended after the axes. Both are colon-free because the payload is re-split on `:`, so a
# colon-bearing ISO time here would be re-read as an axis field and break the record.
_REVIEW_COVERAGE_ANCHOR_FIELDS = 2
_REVIEW_COVERAGE_ANCHOR_UNESTABLISHED = 'unestablished'
_REVIEW_COVERAGE_ANCHOR_HEAD_RE = re.compile(
    r'\A(?:[0-9a-f]{7,40}|' + _REVIEW_COVERAGE_ANCHOR_UNESTABLISHED + r')\Z')
_REVIEW_COVERAGE_ANCHOR_ASOF_RE = re.compile(r'\A[0-9]{8}T[0-9]{6}Z\Z')


def _utc_now_compact() -> str:
    """The current UTC instant in colon-free basic-ISO form (`YYYYMMDDTHHMMSSZ`).

    The review-coverage anchor's write-time (issue #1510) rides the colon-joined
    payload, so it takes this spelling rather than the `:`-bearing ISO form `cmd_now`
    renders."""
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
# A disposition reason must name the specific gap, so a placeholder is refused
# (issue #1453 AC9). This is deliberately NOT a cost/budget word blocklist: shipped
# `shadow-review.md` permits cost as a TRUE cause on a dispatched-and-fell-short
# record, so blocking the word would contradict it (issue #1230 AC8). The only
# predicate that gates the disposition is the recorded dispatch-attempted fact.
_REVIEW_COVERAGE_REASON_MIN_LEN = 20
# Placeholders that clear the length floor above — the set exists to catch the ones
# a floor alone cannot, so every member is deliberately at least that long. Short
# placeholders (`n/a`, `TBD`) are already refused by the floor.
_REVIEW_COVERAGE_BOILERPLATE = frozenset({
    'not applicable to this run',
    'no specific reason recorded',
    'see the notes above for details',
    'see the discussion above for details',
    'this is a placeholder reason',
    'reason to be determined later',
    'nothing further to record here',
})


# Either family's marker, in either namespace — the pattern the free-text guard
# below screens for, so no free-text field can smuggle one into `## Progress`.
_REVIEW_COVERAGE_ANY_MARKER_RE = re.compile(
    _MARKER_NS_RE + r'checkpoint (?:review-coverage(?:-disposition)?|review-roster):'
)


def _review_coverage_marker_rows(progress_content: str, pattern):
    """Yield `pattern`'s capture for each `## Progress` bullet whose note text ENDS
    with that marker — the shape the producer writes (`<text> <marker>`).

    Tail-anchoring to a canonical timestamped bullet is what stops a marker buried
    mid-sentence inside unrelated prose from being read as a record. It is
    defence-in-depth beside the free-text guard in `_apply_mutations`, which refuses
    to write such prose in the first place; either alone would leave the gate
    readable from text no producer validated."""
    for line in (progress_content or '').splitlines():
        bullet = _PROGRESS_BULLET_RE.match(line)
        if not bullet:
            continue
        note = bullet.group(1).rstrip()
        m = pattern.search(note)
        if m and m.end() == len(note):
            yield m.group(1)


def _review_coverage_payloads(progress_content: str) -> list[str]:
    """Every `review-coverage:` payload carried by a checkpoint marker in the
    `## Progress` content. A marker outside `## Progress` is not found here (the
    caller passes only that section), so it reads as absent — fail closed; so is one
    that is not the trailing marker of a canonical bullet. Duplicates surface as a
    >1-length list, which the verdict treats as unestablished rather than picking
    one."""
    return list(_review_coverage_marker_rows(
        progress_content, _REVIEW_COVERAGE_MARKER_RE))


def _parse_review_coverage_payload(payload: str):
    """Split a `<coverage>:<dispatch>:<roster>:<checklist>` payload into an axis dict,
    or return None when it is malformed — the wrong field count, or any field outside
    its axis vocabulary. A malformed payload is unestablished, never a partial read:
    accepting the fields that happened to parse would let a truncated record answer
    for axes it never carried.

    A record written before issue #1510 has exactly len(_REVIEW_COVERAGE_AXES) fields
    and no anchor; an anchored record appends the trailing `<head>:<asof>` fields. Both
    parse to the same axis dict here — the anchor is metadata read by
    `_parse_review_coverage_anchor`, never a fifth axis — so the gate and every existing
    reader are unchanged, and the pre-anchor field count still parses (AC4)."""
    fields = (payload or '').split(':')
    n = len(_REVIEW_COVERAGE_AXES)
    if len(fields) not in (n, n + _REVIEW_COVERAGE_ANCHOR_FIELDS):
        return None
    record = dict(zip(_REVIEW_COVERAGE_AXES, fields[:n]))
    for axis, value in record.items():
        if value not in _REVIEW_COVERAGE_VOCABULARY[axis]:
            return None
    return record


def _parse_review_coverage_anchor(payload: str):
    """The as-of anchor a review-coverage payload carries (issue #1510), or None.

    A pre-#1510 record has exactly len(_REVIEW_COVERAGE_AXES) fields and no anchor, so
    it returns None — absent, never an error (AC4). An anchored record appends
    `<head>:<asof>`: `head` is a lowercase-hex SHA (or the literal `unestablished` when
    the reviewed head could not be derived) and `asof` is a colon-free basic-ISO UTC
    instant. A payload with the anchor field count but a malformed head or asof also
    returns None — an unreadable anchor is absent, not a partial one."""
    fields = (payload or '').split(':')
    n = len(_REVIEW_COVERAGE_AXES)
    if len(fields) != n + _REVIEW_COVERAGE_ANCHOR_FIELDS:
        return None
    head, asof = fields[n:]
    if not _REVIEW_COVERAGE_ANCHOR_HEAD_RE.match(head):
        return None
    if not _REVIEW_COVERAGE_ANCHOR_ASOF_RE.match(asof):
        return None
    return {'head': head, 'asof': asof}


def _render_review_coverage_state(record: dict) -> str:
    """The `axis=value, …` rendering of a coverage record, in axis order.

    One spelling for both readers of it — the producer's visible `## Progress` row
    and the gate's refusal message — so the row a human sees and the state the
    refusal quotes cannot drift apart."""
    return ', '.join(f'{axis}={record[axis]}' for axis in _REVIEW_COVERAGE_AXES)


def _review_coverage_gaps(record: dict) -> list[str]:
    """The distinct gap tokens a coverage record reports, in `_REVIEW_COVERAGE_GAPS`
    order. An empty list means the record is complete. Takes a parsed record: an
    absent, duplicated, or malformed one never reaches here — the verdict refuses it
    as unestablished first."""
    gaps = {
        _REVIEW_COVERAGE_AXIS_GAP[axis]
        for axis in _REVIEW_COVERAGE_AXES
        if record[axis] not in _REVIEW_COVERAGE_CLEAN[axis]
    }
    return [g for g in _REVIEW_COVERAGE_GAPS if g in gaps]


def _review_coverage_incoherence(record: dict) -> str | None:
    """Why a vocabulary-valid coverage record is internally incoherent, or None.

    `not-applicable` is a single fact about the whole pass — no shadow was owed, so
    none of the four axes measured anything — and it is CLEAN on every axis. Held on
    a proper subset it would launder the axes it does NOT cover: a dispatched pass
    could record `full attempted not-applicable not-applicable` and pass the gate with
    its real roster and checklist shortfalls never stated. So it is all-four or none,
    checked identically at write time and at read time."""
    na = [axis for axis in _REVIEW_COVERAGE_AXES
          if record[axis] == 'not-applicable']
    if na and len(na) != len(_REVIEW_COVERAGE_AXES):
        return (
            "'not-applicable' is the no-shadow-owed record and describes the whole "
            f"pass, so it is legal on all {len(_REVIEW_COVERAGE_AXES)} axes or none; "
            f"here it is held only by {', '.join(na)}")
    return None


def _review_roster_members(progress_content: str) -> dict:
    """The enumerated shadow roster as `{member: status}`, read from the `## Progress`
    content — one `review-roster:<member>:<status>` marker row per member. A member with
    more than one row maps to `_REVIEW_ROSTER_DUPLICATE` (separately refused as a duplicate);
    a malformed payload (not `<member>:<status>`) is skipped, so that member reads as absent
    and a `complete` claim that needed it is refused. Read back
    here rather than trusted from the writing call, so an enumeration recorded at the
    Phase 3.3 review exit still reaches the Phase 4.3 finalize call, which repeats no
    coverage flags."""
    out: dict = {}
    for payload in _review_coverage_marker_rows(
            progress_content, _REVIEW_ROSTER_MARKER_RE):
        fields = payload.split(':')
        if len(fields) != 2:
            continue
        member, status = fields
        out[member] = _REVIEW_ROSTER_DUPLICATE if member in out else status
    return out


def _review_roster_incoherence(record: dict, members: dict) -> str | None:
    """Why the roster axis value is incoherent with the enumerated members, or None.

    The `roster` axis alone is a self-report (issue #1512): a narrow shadow that believes
    itself full writes `complete` and nothing downstream sees a roster to contradict it.
    This cross-checks the axis against the per-member enumeration. It is enforced at write
    time (a measured record cannot be stamped without a coherent enumeration) and re-run at
    the read-time `Status: Complete` gate only when an enumeration is present, so a legacy
    rosterless record — one predating this check — finalizes rather than being re-validated
    retroactively:

    - `complete` requires every always-on member `dispatched` and no member `missing`; an
      always-on member absent, `missing`, or `gated-off` refuses it, naming the member.
    - `short` must name at least one `missing` member — a `short` with none is really
      complete, so refusing it keeps the axis honest.
    - an always-on member is never applicability-gated, so recording one `gated-off` on
      any measured roster (`complete` or `short`) is incoherent and refused.
    - `complete`/`short` are measured values and require a non-empty enumeration;
      `not-applicable`/`unestablished` measured no roster and must carry none.
    - An unknown member or status, or a duplicated member row, fails closed.

    It enforces the always-on floor — no always-on member missing or gated-off on a
    `complete` roster — not full expected-roster dispatch: a gated analyzer's own
    dispatch remains self-reported by design (issue #1512 AC3)."""
    roster = record['roster']
    dup = sorted(m for m, s in members.items() if s is _REVIEW_ROSTER_DUPLICATE)
    if dup:
        return (f"the roster enumeration lists member(s) {', '.join(dup)} more than "
                "once, so which dispatch outcome applies is unresolvable")
    for member in sorted(members):
        if member not in _SHADOW_ROSTER_MEMBERS:
            return (f"the roster enumeration names unknown member {member!r}; expected "
                    f"one of {', '.join(_SHADOW_ROSTER_MEMBERS)}")
        if members[member] not in _ROSTER_MEMBER_STATUSES:
            return (f"roster member {member!r} carries unknown status "
                    f"{members[member]!r}; expected one of "
                    f"{', '.join(_ROSTER_MEMBER_STATUSES)}")
    measured = roster in ('complete', 'short')
    if members and not measured:
        return (f"roster={roster} measured no roster, so it must carry no per-member "
                f"enumeration, but {len(members)} review-roster row(s) are present")
    if measured and not members:
        return (f"roster={roster} is a measured value, so it must enumerate the shadow's "
                "per-member dispatch outcomes, but no review-roster row is present")
    if measured:
        ao_gated = [m for m in _SHADOW_ALWAYS_ON_MEMBERS
                    if members.get(m) == 'gated-off']
        if ao_gated:
            return ("an always-on member is never applicability-gated, so it cannot be "
                    f"recorded gated-off: {', '.join(ao_gated)}")
    if roster == 'complete':
        bad = [f'{m}={members.get(m) or "not-enumerated"}'
               for m in _SHADOW_ALWAYS_ON_MEMBERS
               if members.get(m) != 'dispatched']
        bad += [f'{m}=missing' for m in _SHADOW_GATED_MEMBERS
                if members.get(m) == 'missing']
        if bad:
            return ("roster=complete requires every always-on member "
                    f"({', '.join(_SHADOW_ALWAYS_ON_MEMBERS)}) dispatched and no member "
                    f"missing, but {', '.join(bad)}")
    if roster == 'short' and not any(s == 'missing' for s in members.values()):
        return ("roster=short must name at least one missing roster member, but the "
                "enumeration lists none")
    return None


def _review_roster_marker(member: str, status: str) -> str:
    """The hidden marker a review-roster enumeration row carries."""
    return _checkpoint_marker(f'{_REVIEW_ROSTER_KEY_PREFIX}{member}:{status}')


def _render_review_roster_member(member: str, status: str) -> str:
    """The roster-member row's visible text, coupled to `_review_roster_members`'
    read-back."""
    return f'review roster member {member}={status}'


# issue #1509: the diff-profile row that authorizes a `skipped-intentional` checklist
# skip. These constants MIRROR skills/review/phases/phase-0-setup.md §0.5 (`small_diff`,
# `config_only`, `engine_self_modifying`); the divergence test in
# lib/test/test_python_scripts.py reads that file's arms and goes RED if they drift from
# these. The four prose copies of the engine-source path set stay unrefactored — this is
# the recomputation's comparand, not a new single source for them.
_REVIEW_COVERAGE_SMALL_DIFF_LINE_CEILING = 100   # total changed lines strictly below this
_REVIEW_COVERAGE_SMALL_DIFF_FILE_CEILING = 3     # changed-file count at most this
_REVIEW_COVERAGE_CONFIG_ONLY_EXTS = frozenset(
    {'.yml', '.yaml', '.json', '.md', '.toml', '.ini', '.lock', '.txt'})
# engine_self_modifying arm 1 — PRFlow's own source dirs (this repository's own tree).
_REVIEW_COVERAGE_ENGINE_SOURCE_PREFIXES = ('skills/', 'agents/', 'lib/')
# arm 2 — a prompt extension under the PRFlow state directory (any depth), `.md` only.
_REVIEW_COVERAGE_ENGINE_STATE_DIRS = ('.prflow', '.devflow')
# arm 3 — the root agent-instruction file (any depth), by basename.
_REVIEW_COVERAGE_ENGINE_ROOT_AGENT_FILE = 'CLAUDE.md'


def _parse_numstat_counts(numstat: str):
    """(file_count, changed_line_total) from `git diff --numstat` output (issue #1509).

    Sums added+deleted across all rows and counts one file per row: a binary row (`-` in
    both count columns) contributes 0 lines but 1 file. A row lacking the three
    tab-separated fields (a truncated line) or whose count column is neither an integer
    nor `-` is malformed — raise ValueError so the caller routes to an unresolvable
    measurement rather than trusting a wrong count."""
    files = 0
    lines = 0
    for row in numstat.split('\n'):
        if not row:
            continue
        parts = row.split('\t')
        if len(parts) < 3:
            raise ValueError(f'malformed --numstat row {row!r}')
        for col in (parts[0], parts[1]):
            if col != '-':
                lines += int(col)  # ValueError on a non-integer column → unresolvable
        files += 1
    return files, lines


def _recompute_diff_facts(anchor_head, base_ref, repo_root):
    """Recompute the reviewed diff's size and paths from git alone (issue #1509).

    Measures the reviewed head (`anchor_head`, the record's as-of anchor) against the PR
    base (`base_ref`, else the `origin/HEAD` symbolic ref) — the SAME range the Phase 0.5
    classification measured, never the working tree at write time. Returns
    {'resolved': bool, 'reason': str, 'lines': int, 'files': int, 'paths': [str]}.

    resolved is False — never a refusal; the caller records the checklist axis
    `unestablished` — when the reviewed head is unestablished/absent, no base ref can be
    read, no merge base exists (unrelated histories on a depth-limited checkout), or any
    git invocation fails (non-zero exit or OSError) or emits a malformed row. Mirrors
    `_repo_root`'s habit of catching both CalledProcessError and OSError."""
    def _unresolved(reason):
        return {'resolved': False, 'reason': reason,
                'lines': 0, 'files': 0, 'paths': []}

    if not anchor_head or anchor_head == _REVIEW_COVERAGE_ANCHOR_UNESTABLISHED:
        return _unresolved(
            'the reviewed head is unestablished, so the diff it was recorded over '
            'cannot be measured')

    def _git(argv):
        return subprocess.run(
            ['git', *argv], cwd=repo_root, check=True,
            capture_output=True, encoding='utf-8').stdout

    try:
        # `_git` runs check=True, so an unreadable base (origin/HEAD unset) or an
        # unresolvable merge base (unrelated histories on a depth-limited checkout)
        # raises here and is caught below as unresolved — no separate empty-value guard
        # is reachable after it.
        base = base_ref or _git(
            ['symbolic-ref', '--short', 'refs/remotes/origin/HEAD']).strip()
        merge_base = _git(['merge-base', anchor_head, base]).strip()
        files, lines = _parse_numstat_counts(
            _git(['diff', '--numstat', merge_base, anchor_head]))
        paths = [p for p in _git(
            ['diff', '--name-only', '-z', merge_base, anchor_head]).split('\0') if p]
    except (subprocess.CalledProcessError, OSError, ValueError) as e:
        return _unresolved(f'the diff measurement did not resolve ({e})')
    return {'resolved': True, 'reason': '',
            'lines': lines, 'files': files, 'paths': paths}


def _is_engine_own_repo(repo_root) -> bool:
    """Whether `repo_root` is THIS engine's own repository (issue #1509), decided by
    repository identity rather than directory names: its `.claude-plugin/plugin.json`
    names this plugin. A consumer's checkout — whose own `lib/` is unrelated product
    code — returns False, so the engine-source refusal arm never fires undiagnosably
    on it, while the classifier's own use of the arms is unchanged."""
    if not repo_root:
        return False
    try:
        with open(os.path.join(repo_root, '.claude-plugin', 'plugin.json'),
                  encoding='utf-8') as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        return False
    # `prflow` is the frozen canonical plugin name (CLAUDE.md rename Tier 1, single-
    # sourced in lib/rename-map.json and the manifest `name`): do not rename it here in
    # isolation, or this identity check silently stops recognizing the engine's own repo.
    return isinstance(manifest, dict) and manifest.get('name') == 'prflow'


def _review_coverage_engine_source_paths(paths):
    """The subset of `paths` in the engine's own source set — the arms of
    phase-0-setup.md's `engine_self_modifying` (issue #1509)."""
    hits = []
    for p in paths:
        base = p.rsplit('/', 1)[-1]
        first = p.split('/', 1)[0]
        if (p.startswith(_REVIEW_COVERAGE_ENGINE_SOURCE_PREFIXES)
                or (first in _REVIEW_COVERAGE_ENGINE_STATE_DIRS
                    and base.endswith('.md'))
                or base == _REVIEW_COVERAGE_ENGINE_ROOT_AGENT_FILE):
            hits.append(p)
    return hits


def _review_coverage_profile_disproof(facts, repo_root) -> str | None:
    """Why the recomputed diff does NOT satisfy the profile row that authorizes a
    `skipped-intentional` skip, naming each failed condition and its measured value —
    or None when the profile row is confirmed (issue #1509). Assumes facts['resolved'].
    The engine-source arm applies only in this engine's own repository (AC): on any
    other repository it is excluded from the refusal predicate."""
    reasons = []
    if facts['lines'] >= _REVIEW_COVERAGE_SMALL_DIFF_LINE_CEILING:
        reasons.append(
            f"the changed-line total {facts['lines']} is not below the ceiling of "
            f"{_REVIEW_COVERAGE_SMALL_DIFF_LINE_CEILING}")
    if facts['files'] > _REVIEW_COVERAGE_SMALL_DIFF_FILE_CEILING:
        reasons.append(
            f"the changed-file count {facts['files']} exceeds the ceiling of "
            f"{_REVIEW_COVERAGE_SMALL_DIFF_FILE_CEILING}")
    bad_ext = [p for p in facts['paths']
               if os.path.splitext(p)[1] not in _REVIEW_COVERAGE_CONFIG_ONLY_EXTS]
    if bad_ext:
        reasons.append(
            'these changed paths have a non-config-only extension: '
            + ', '.join(sorted(bad_ext)))
    if _is_engine_own_repo(repo_root):
        engine = _review_coverage_engine_source_paths(facts['paths'])
        if engine:
            reasons.append(
                "these changed paths are in the engine's own source set (the "
                'checklist is forced on for them): ' + ', '.join(sorted(engine)))
    return '; '.join(reasons) if reasons else None


def _review_coverage_dispositions(progress_content: str) -> dict:
    """The recorded dispositions as `{gap: (cause_class, reason)}`, read from the
    `## Progress` content. Each is one row carrying a
    `review-coverage-disposition:<gap>:<cause-class>` marker whose visible text holds
    the reason; the reason is re-read here rather than trusted from the writing call,
    so a disposition recorded by an earlier phase still reaches the Phase 4.3 finalize
    call, which repeats no coverage flags. A row whose reason cannot be re-read maps to
    the empty string, which the verdict's boilerplate check then refuses — an
    unreadable reason is not a stated one.

    A legacy TWO-segment marker (`review-coverage-disposition:<gap>` with no cause-class
    segment, the pre-#1984 form) is SKIPPED, so its gap stays absent from the returned
    map and the Complete gate reports it undischarged with `[review-coverage-gap]`
    (issue #1984 AC6) — a disposition with no cause class discharges nothing."""
    out = {}
    for line in (progress_content or '').splitlines():
        bullet = _PROGRESS_BULLET_RE.match(line)
        if not bullet:
            continue
        note = bullet.group(1).rstrip()
        m = _REVIEW_COVERAGE_DISPOSITION_MARKER_RE.search(note)
        if not m or m.end() != len(note):
            continue
        parts = m.group(1).split(':', 1)
        if len(parts) != 2:
            # Legacy two-operand marker (no cause-class): skip it so the gap it names
            # stays undischarged (issue #1984 AC6).
            continue
        gap, cause_class = parts
        if gap in out:
            # Two rows for one gap: which disposition the gate judges would depend on
            # row order, so refuse rather than pick one — the same fail-closed posture
            # `_review_coverage_payloads`' duplicate handling takes for the record.
            # The producer already refuses a repeated gap within a call; this arm
            # covers a row planted by hand or by an older workpad.py.
            out[gap] = _REVIEW_COVERAGE_DUPLICATE_DISPOSITION
            continue
        rm = _review_coverage_disposition_reason_re(gap).search(note)
        out[gap] = (cause_class, rm.group(1).strip() if rm else '')
    return out


# The sentinel a duplicated gap resolves to. It is not a reason, so it can never
# satisfy the reason check; the rejection below names it specifically.
_REVIEW_COVERAGE_DUPLICATE_DISPOSITION = object()


def _review_coverage_reason_rejection(reason):
    """Why a disposition reason is unacceptable, or None when it is acceptable.
    Returns a message fragment so both the write-time validation and the read-time
    verdict refuse identically."""
    if reason is _REVIEW_COVERAGE_DUPLICATE_DISPOSITION:
        return ('two disposition rows name that gap, so which reason applies is '
                'unresolvable; remove the duplicate row')
    stripped = (reason or '').strip()
    if '<!--' in stripped or '-->' in stripped:
        # The reason rides the row's visible text, ahead of the row's own marker, so
        # an embedded comment delimiter would truncate the read-back or swallow the
        # marker. Refuse at write time rather than storing a reason the gate will
        # later fail to resolve.
        return 'it contains an HTML-comment delimiter, which the row cannot carry'
    if stripped.lower() in _REVIEW_COVERAGE_BOILERPLATE:
        return 'it is a generic placeholder'
    if len(stripped) < _REVIEW_COVERAGE_REASON_MIN_LEN:
        return (f'it is shorter than {_REVIEW_COVERAGE_REASON_MIN_LEN} characters '
                'and so cannot name the specific gap')
    return None


def _review_coverage_dispatch_uncorroborated(record: dict, roster_members: dict) -> bool:
    """True when a `dispatch=attempted` record with a measured roster is not
    corroborated by per-member rows covering all four always-on reviewers with at least
    one reading `dispatched` (issue #1984). Shared by the write-time
    `--record-review-coverage` validator and the read-time Complete-gate verdict so the
    corroboration cannot hold at write time yet lapse at finalize over a legacy record.
    A non-measured roster (the lost-write `unestablished` shape) is never uncorroborated
    here — it is exempt and carries no rows."""
    if (record.get('dispatch') != 'attempted'
            or record.get('roster') not in ('complete', 'short')):
        return False
    all_present = all(m in roster_members for m in _SHADOW_ALWAYS_ON_MEMBERS)
    any_dispatched = any(roster_members.get(m) == 'dispatched'
                         for m in _SHADOW_ALWAYS_ON_MEMBERS)
    return not all_present or not any_dispatched


def _review_coverage_disposition_cause_rejection(cause_class, has_missing_roster_row):
    """Why a disposition's cause class is inadmissible, or None (issue #1984).

    The single home of the cause-class rule, shared by the write-time
    `--review-coverage-disposition` validator and the read-time Complete-gate verdict so
    the closed vocabulary and the environment-denial corroboration cannot drift between
    the two enforcement points. Returns a diagnostic tail each caller frames with its
    own prefix; the callers append `[review-coverage-cause-inadmissible]`.

    Corroboration scope is roster-global, not per-gap: `environment-denial` is admitted
    for ANY gap whenever ANY roster row reads `missing`, so the corroborating row need
    not name the capability the disposed gap depended on. That matches issue #1984's
    acceptance wording; it closes the primary hole (a gap with no `missing` row at all)
    and leaves tying corroboration to the specific gap to a follow-up."""
    if cause_class not in _REVIEW_COVERAGE_CAUSE_CLASSES:
        return (f"carries cause class {cause_class!r}, which is not one of "
                f"{', '.join(_REVIEW_COVERAGE_CAUSE_CLASSES)}")
    if cause_class == 'environment-denial' and not has_missing_roster_row:
        return ("carries cause class 'environment-denial' but no roster row records a "
                "member 'missing', so the denied capability is uncorroborated")
    return None


def _review_coverage_marker(payload: str) -> str:
    """The hidden marker a review-coverage record row carries."""
    return _checkpoint_marker(_REVIEW_COVERAGE_KEY_PREFIX + payload)


def _review_coverage_disposition_marker(gap: str, cause_class: str) -> str:
    """The hidden marker a review-coverage disposition row carries (issue #1984 added
    the trailing `:<cause-class>` segment). `gap` is colon-free, so the reader's one
    `split(':', 1)` on the captured payload cleanly separates gap from cause class."""
    return _checkpoint_marker(
        _REVIEW_COVERAGE_DISPOSITION_KEY_PREFIX + gap + ':' + cause_class)


def _render_review_coverage_disposition(gap: str, reason: str) -> str:
    """The disposition row's visible text. Coupled to
    `_review_coverage_disposition_reason_re()`, which builds the per-gap pattern that
    reads the reason back off this exact rendering — change one and the other stops
    resolving."""
    return f'review-coverage disposition — gap={gap}; reason: {reason}'


_REVIEW_COVERAGE_REFLECTION_PREFIX = (
    "review coverage gap in this run's own review pass — gap=")
# The pre-#1510 spelling (issue #1510 reworded the prefix). The strip below reads BOTH, so a
# bullet a prior code version wrote is cleaned when a fresh record supersedes it across an
# upgrade — otherwise a stale friction bullet survives and keeps tripping the retrospective gate.
_REVIEW_COVERAGE_REFLECTION_PREFIX_SUPERSEDED = (
    'review coverage gap carried forward — gap=')


def _strip_review_coverage_reflection_bullets(content: str) -> str:
    """Remove the disposition-filed reflection bullets from `## Devflow Reflection`.

    Runs wherever the rows those bullets accompany are stripped, so a superseded or
    inherited disposition does not leave a permanent `### ⚠️ Action required` bullet
    that keeps tripping the retrospective friction gate after the gap it named is
    gone. Matches on `_REVIEW_COVERAGE_REFLECTION_PREFIX` (the constant the disposition's
    reflection writer in `_apply_mutations` emits, so the two move together) and on its
    superseded spelling, so a bullet a prior code version wrote is cleaned across an upgrade."""
    kept = [ln for ln in content.splitlines(keepends=True)
            if _REVIEW_COVERAGE_REFLECTION_PREFIX not in ln
            and _REVIEW_COVERAGE_REFLECTION_PREFIX_SUPERSEDED not in ln]
    return ''.join(kept)


def _strip_review_coverage_marker_rows(content: str) -> str:
    """Remove the `## Progress` review-coverage record row, EVERY disposition row, and
    EVERY roster-member enumeration row.

    Called both when a fresh record supersedes the previous one — a surviving disposition
    or roster row would answer for a gap or a member the new record may not report — and
    by the Phase 1.3 resume strip, because a coverage record describes *this* attempt and
    a resumed run must not inherit an earlier attempt's answer."""
    kept = [ln for ln in content.splitlines(keepends=True)
            if not _REVIEW_COVERAGE_MARKER_RE.search(ln)
            and not _REVIEW_COVERAGE_DISPOSITION_MARKER_RE.search(ln)
            and not _REVIEW_ROSTER_MARKER_RE.search(ln)]
    return ''.join(kept)


def _strip_review_coverage_disposition_rows(content: str, gaps) -> str:
    """Remove only the named gaps' disposition rows, leaving the coverage record.

    What a dispositions-only write needs: re-stating one gap's reason replaces that
    row rather than leaving two rows for one gap, while the record those dispositions
    explain survives — stripping it would leave the gate reading 'unestablished'."""
    wanted = set(gaps)
    kept = []
    for ln in content.splitlines(keepends=True):
        m = _REVIEW_COVERAGE_DISPOSITION_MARKER_RE.search(ln)
        # The capture is `<gap>[:<cause-class>]` (issue #1984); match on the gap part
        # so a re-stated gap's row is replaced regardless of its cause class.
        if m and m.group(1).split(':', 1)[0] in wanted:
            continue
        kept.append(ln)
    return ''.join(kept)


# The checkpoint key namespaces that belong to a validated marker family, each paired
# with the flag that owns it. `_plan_checkpoints` refuses a generic `--checkpoint` in
# any of them, so a family's validation cannot be bypassed through the generic head.
_RESERVED_CHECKPOINT_KEY_PREFIXES = (
    (_REVIEW_COVERAGE_DISPOSITION_KEY_PREFIX, '`--review-coverage-disposition`'),
    (_REVIEW_ROSTER_KEY_PREFIX, '`--record-roster-member`'),
    (_REVIEW_COVERAGE_KEY_PREFIX, '`--record-review-coverage`'),
    (_COMPLETION_MARKER_KEY_PREFIX, '`--record-completion-evidence`'),
    (_COMPLETION_CI_MARKER_KEY_PREFIX, '`--record-completion-evidence-ci`'),
    (_RESUME_POINT_MARKER_KEY_PREFIX, '`--record-resume-point`'),
)


def _validate_flight_key(args, flight_key: str) -> None:
    """Validate a specific completion flight key against its canonical record.

    Raises a structural `_UpdateError` (no PATCH) on a malformed key, an absent
    validator sibling, an internal validator failure, or a non-pass verdict.
    Returns None on a clean pass."""
    if not isinstance(flight_key, str) or not _COMPLETION_FLIGHT_KEY_RE.match(flight_key):
        raise _UpdateError(
            f"completion evidence: flight key {flight_key!r} is malformed "
            f"(expected a hex verification-flight key). No PATCH was made."
        )
    validator = _load_completion_validator()
    if validator is None:
        # The standalone-copy arm: fail closed BEFORE any PATCH with the validator's
        # own missing-evidence token and a detail naming the absent sibling module.
        raise _UpdateError(
            "completion evidence [missing-evidence]: the completion-evidence "
            "validator module (check-completion-evidence.py) is not available beside "
            "this workpad.py copy, so a --status Complete write cannot be backed by "
            "verification evidence. No PATCH was made."
        )
    root = _devflow_repo_root(args)
    record_path = os.path.join(root, _VERIFICATION_FLIGHT_DIRNAME, flight_key + '.json')
    claim_identity = getattr(args, 'claim_identity', None)
    try:
        token, detail = validator.validate_implement_completion(
            record_path, root, claim_identity)
    except Exception as e:
        raise _UpdateError(
            f"completion evidence: the validator raised an internal error "
            f"({e.__class__.__name__}); treating as unestablished. No PATCH was made."
        )
    if token != 'pass':
        raise _UpdateError(
            f"completion evidence rejected [{token}]: {detail}. No PATCH was made."
        )


def _completion_evidence_verdict(args, progress_content: str) -> None:
    """The terminal-gate half: re-validate the completion evidence carried by the
    workpad's ## Progress marker at Complete time. When no `--claim-identity` is
    pinned (the production path — Phase 4.3 finalizes with a plain `--status
    Complete`), the validator re-derives the candidate identity from the current
    tree, so edits made after the evidence was recorded are caught as `stale`. A
    pinned `--claim-identity` (loop/test override) is honored verbatim instead, so a
    caller that pins it deliberately opts out of the fresh re-derivation.

    Two completion-evidence families are accepted (issue #1611): the in-environment
    verification-flight family (`completion-verification:`) and the CI-derived family
    (`completion-ci:`, a local/interactive tier's reading of a green required check).
    Exactly one marker must be present COUNTED ACROSS BOTH FAMILIES TOGETHER; the
    single marker is then dispatched to the validator its family owns — the flight
    family to `_validate_flight_key` unchanged, the CI family to `_validate_ci_evidence`.

    Raises `_UpdateError` (structural — no PATCH) when no marker of either family is
    present or more than one is (combined), or when the single marker's record fails
    its validator. Returns None on a clean pass."""
    keys = _completion_marker_keys(progress_content)
    ci_payloads = _completion_ci_marker_payloads(progress_content)
    total = len(keys) + len(ci_payloads)
    if total == 0:
        raise _UpdateError(
            "refusing to finalize Status: Complete — no completion-evidence marker "
            "of either family present [missing-evidence]. Record an in-env "
            "verification flight with `workpad.py update <issue> "
            "--record-completion-evidence <flight-key>`, or (local/interactive tier, "
            "issue #1611) a CI reading with `workpad.py update <issue> "
            "--record-completion-evidence-ci <head-sha> <tier> <run-url> "
            "--completion-ci-check <name> <conclusion> ...`, after the run's "
            "verification is established. No PATCH was made."
        )
    if total > 1:
        raise _UpdateError(
            "refusing to finalize Status: Complete — "
            f"{total} completion-evidence markers present (counted across the "
            "verification-flight and CI-derived families); exactly one is required "
            "[missing-evidence]. No PATCH was made."
        )
    if keys:
        _validate_flight_key(args, keys[0])
    else:
        _validate_ci_evidence(args, ci_payloads[0])


def _required_artifact_verdict(progress_content: str) -> None:
    """The required-artifact half of the terminal gate (issue #1348): a terminal
    `--status Complete` must carry a `## Progress` row for every member of
    `_REQUIRED_ARTIFACTS`, so a run cannot reach a published, Complete end state
    having silently skipped the step that produces one (the motivating failure —
    checkpoint 4 skipped, PR published on a stale base).

    Resolve each artifact's keyed marker with the same two-line idiom
    `_plan_checkpoints` uses — `_marker_variants(_checkpoint_marker(key))` counted
    over `progress_content` — so both the `prflow:` and superseded `devflow:`
    spellings count and a workpad mutated across the #1003 rename boundary is not
    falsely refused. A member is satisfied by ANY of its accepting keys (the clean
    key OR #1347's tier-refused variant), so a tier-refused run still completes.

    Structured as a standalone verdict (like `_completion_evidence_verdict`) so it can
    be isolated in tests. It is a PURE READ: it raises a structural `_UpdateError`
    (no PATCH — `cmd_update` aborts before the temp-file/PATCH block) and mutates
    nothing on any path; every repair lives earlier, in the producer, while the run
    can still act on the result. Returns None on a clean pass."""
    for artifact in _REQUIRED_ARTIFACTS:
        present = any(
            progress_content.count(variant) > 0
            for key in artifact['accept_keys']
            for variant in _marker_variants(_checkpoint_marker(key))
        )
        if not present:
            raise _UpdateError(
                "refusing to finalize Status: Complete — the ## Progress section "
                f"carries no row for the required run artifact {artifact['key']!r} "
                "[missing-artifact]. Record it by completing "
                f"{artifact['producer']}. No PATCH was made."
            )


def _review_coverage_verdict(progress_content: str) -> None:
    """The review-coverage half of the terminal gate (issue #1453): a terminal
    `--status Complete` must carry a `## Progress` review-coverage record showing the
    Phase 3 review pass ran in full — or, for each gap it does show, an accepted
    disposition naming that gap and stating a reason.

    Reads ONLY the `## Progress` content, exactly like `_required_artifact_verdict`:
    the Phase 4.3 finalize call is a plain `--status Complete` that repeats no
    coverage flags, so a verdict keyed on `args` would see nothing on every real run.
    Both the record and its dispositions are durable rows, so a disposition written in
    Phase 3.3 still reaches this read — and one passed on the Complete call itself is
    equally visible, because the gate runs over the POST-mutation sections.

    An absent, duplicated, or malformed record is UNESTABLISHED, never complete: the
    fail-open this gate exists to close is precisely a run that shipped Complete with
    no resolvable coverage fact.

    The disposition is gated on the recorded DISPATCH-ATTEMPTED fact, never on a
    reason-string blocklist: a fan-out that was dispatched and fell short may state
    any true cause, cost included (shipped `shadow-review.md`, issue #1230), while a
    run that never dispatched the shadow has no legal way to record a shortfall and
    complete — it stops at a non-terminal or `Blocked` status instead.

    A PURE READ: it raises a structural `_UpdateError` (no PATCH — `cmd_update`
    aborts before the temp-file/PATCH block) and mutates nothing on any path.
    Returns None on a clean pass."""
    payloads = _review_coverage_payloads(progress_content)
    record = (_parse_review_coverage_payload(payloads[0])
              if len(payloads) == 1 else None)
    if record is None:
        if not payloads:
            why = 'no review-coverage record is present'
        elif len(payloads) > 1:
            why = (f'{len(payloads)} review-coverage records are present; exactly '
                   'one is required')
        else:
            why = f'the review-coverage record {payloads[0]!r} is malformed'
        raise _UpdateError(
            "refusing to finalize Status: Complete — "
            f"{why}, so the run's review coverage is UNESTABLISHED "
            "[review-coverage-unestablished]. Record it with `workpad.py update "
            "<issue> --record-review-coverage <coverage> <dispatch> <roster> "
            "<checklist>` at the Phase 3.3 review exit. No PATCH was made."
        )
    incoherent = _review_coverage_incoherence(record)
    if incoherent:
        raise _UpdateError(
            "refusing to finalize Status: Complete — the review-coverage record "
            f"({_render_review_coverage_state(record)}) is internally incoherent: "
            f"{incoherent}, so the run's review coverage is UNESTABLISHED "
            "[review-coverage-unestablished]. Re-stamp it at the Phase 3.3 review "
            "exit. No PATCH was made."
        )
    # The roster cross-check is enforced at WRITE time (a `complete`/`short` record
    # cannot be recorded without a coherent per-member enumeration), so a record that
    # reaches finalize carrying NO enumeration predates issue #1512 — a legacy workpad,
    # which the issue does not re-validate retroactively. Re-run the check here only when
    # an enumeration is present, so a legacy `complete` record still finalizes while a
    # record whose enumeration IS present stays cross-checked as defense-in-depth.
    roster_members = _review_roster_members(progress_content)
    roster_incoherent = (_review_roster_incoherence(record, roster_members)
                         if roster_members else None)
    if roster_incoherent:
        raise _UpdateError(
            "refusing to finalize Status: Complete — the review-coverage record "
            f"({_render_review_coverage_state(record)}) is incoherent with the shadow "
            f"roster enumeration: {roster_incoherent}, so the run's review coverage is "
            "UNESTABLISHED [review-coverage-unestablished]. Enumerate the shadow's "
            "per-member dispatch outcomes with `--record-roster-member <member> "
            "<status>` at the Phase 3.3 review exit. No PATCH was made."
        )
    # #1984: re-run the write-time dispatch-corroboration here, as defense-in-depth for a
    # record persisted by a pre-#1984 writer — only when a roster enumeration is present
    # (a legacy rosterless record stays grandfathered, exactly like the roster
    # cross-check above), and after that cross-check so a `complete` shortfall keeps its
    # existing `[review-coverage-unestablished]` message. This closes the read-time gap
    # where a `short` roster whose rows name no dispatched member could reach Complete.
    if roster_members and _review_coverage_dispatch_uncorroborated(record, roster_members):
        raise _UpdateError(
            "refusing to finalize Status: Complete — the review-coverage record "
            f"({_render_review_coverage_state(record)}) reads dispatch=attempted with a "
            "measured roster, but its per-member enumeration does not cover every "
            "always-on reviewer with at least one dispatched "
            "[review-coverage-dispatch-uncorroborated]. No PATCH was made."
        )
    gaps = _review_coverage_gaps(record)
    if not gaps:
        return
    dispositions = _review_coverage_dispositions(progress_content)
    missing = [g for g in gaps if g not in dispositions]
    if missing:
        raise _UpdateError(
            "refusing to finalize Status: Complete — the recorded review coverage is "
            f"incomplete ({_render_review_coverage_state(record)}) and gap(s) "
            f"{', '.join(missing)} carry no "
            "disposition [review-coverage-gap]. Either complete the review pass, or "
            "record one `--review-coverage-disposition <gap> <cause-class> \"<reason>\"` per gap "
            "naming what was not verified and why. No PATCH was made."
        )
    # #1230: the disposition is an honest-degradation record, never an election
    # channel. It is available only over a fan-out that WAS dispatched — a run that
    # never dispatched (or cannot establish that it did) stops instead of completing.
    if record['dispatch'] != 'attempted':
        raise _UpdateError(
            "refusing to finalize Status: Complete — the review-coverage record reads "
            f"dispatch={record['dispatch']}, so no shadow fan-out is on record as "
            "having been attempted; a disposition cannot carry an undispatched pass "
            "[review-coverage-undispatched]. Stop at a non-terminal or Blocked status "
            "naming the cause instead. No PATCH was made."
        )
    # #1984: `environment-denial` is corroborated by a recorded `missing` roster row
    # (the denied member); `roster_members` was read above for the roster cross-check.
    has_missing_roster_row = any(s == 'missing' for s in roster_members.values())
    for gap in gaps:
        entry = dispositions[gap]
        if entry is _REVIEW_COVERAGE_DUPLICATE_DISPOSITION:
            raise _UpdateError(
                "refusing to finalize Status: Complete — the disposition for gap "
                f"{gap!r} does not state an acceptable reason: "
                f"{_review_coverage_reason_rejection(entry)} "
                "[review-coverage-boilerplate]. Name the specific gap and why it is "
                "being carried forward. No PATCH was made."
            )
        cause_class, reason = entry
        # #1984: cause-class admissibility is defined once, in
        # `_review_coverage_disposition_cause_rejection`; do not restate it here.
        _cause_rej = _review_coverage_disposition_cause_rejection(
            cause_class, has_missing_roster_row)
        if _cause_rej:
            raise _UpdateError(
                "refusing to finalize Status: Complete — the disposition for gap "
                f"{gap!r} {_cause_rej} [review-coverage-cause-inadmissible]. "
                "No PATCH was made."
            )
        rejection = _review_coverage_reason_rejection(reason)
        if rejection:
            raise _UpdateError(
                "refusing to finalize Status: Complete — the disposition for gap "
                f"{gap!r} does not state an acceptable reason: {rejection} "
                "[review-coverage-boilerplate]. Name the specific gap and why it is "
                "being carried forward. No PATCH was made."
            )


def _extension_row_verdict(progress_content: str) -> None:
    """The extension-row half of the terminal gate (issue #1817): a terminal
    `--status Complete` is refused while any `_EXTENSION_ROWS` `prompt extension
    resolved:` row is BOTH unticked AND unaccompanied by that row's sanctioned
    `state not established` note — the same fail-open the unticked-AC hard-fail
    closes, applied to the extension rows so an unticked row on a Complete workpad
    means the deliberate "state not established" record issue #1462 intended rather
    than a silent bookkeeping miss.

    Each row is located in the ## Progress content by its stable substring via
    `_CHECKBOX_ROW_RE` (the same detector `_reconcile_extension_rows` uses). A row
    that is absent entirely is tolerated, not refused: a workpad created before the
    rows existed (pre-#1462, never `--reconcile-extension-rows`'d) carries none of
    them, matching the gate's existing tolerance for older workpads (an absent AC or
    Plan section contributes nothing). A ticked row passes. An unticked row passes
    only when ## Progress carries a note line naming that row's substring together
    with the phrase `state not established` — keyed on the row name plus that phrase,
    not a byte-exact match of the free-prose note.

    A PURE READ, structured like `_required_artifact_verdict`: it raises a structural
    `_UpdateError` (no PATCH — `cmd_update` aborts before the temp-file/PATCH block)
    and mutates nothing on any path. Returns None on a clean pass."""
    lines = progress_content.split('\n')
    offending = []
    for _phase, text, substr in _EXTENSION_ROWS:
        row = next(
            (
                m for ln in lines
                if (m := _CHECKBOX_ROW_RE.match(ln))
                and substr.lower() in m.group(4).lower()
            ),
            None,
        )
        if row is None:
            continue  # wholly-absent row → legacy workpad tolerance, never refused
        if row.group(2) != '[ ]':
            continue  # ticked → satisfied
        note_present = any(
            not _CHECKBOX_ROW_RE.match(ln)
            and substr.lower() in ln.lower()
            and 'state not established' in ln.lower()
            for ln in lines
        )
        if not note_present:
            offending.append(text)
    if offending:
        rows = '\n'.join(f'    - [ ] {t}' for t in offending)
        raise _UpdateError(
            "refusing to finalize Status: Complete — "
            f"{len(offending)} prompt-extension row(s) resolved-but-unrecorded: each "
            "is unticked and carries no `state not established` note (tick it once the "
            "extension's state was observed, or record that note, before finalizing) "
            f"[extension-row-unrecorded]:\n{rows}"
        )


def _terminal_complete_gate(sections, args) -> list[str]:
    """Reconcile the workpad self-record on a terminal `--status Complete` write.

    Hard-fail (a *structural* `_UpdateError`, so `cmd_update` aborts before any
    PATCH and the Status is never flipped) when any NON-post-merge `## Acceptance
    Criteria` row is still `- [ ]`, naming each offending row on stderr. Post-merge
    AC rows are excluded (byte-for-byte the Phase 3.4 exclusion). Returns the
    still-unticked `## Plan` rows for the caller to emit a NON-blocking warning on
    (a genuinely dropped/superseded plan step may honestly stay unticked, so Plan
    is not hard-failed). Also emits a NON-blocking warning when the AC section still
    holds the un-mirrored `new-body` placeholder (mirroring never ran — a vacuously
    satisfied hard-fail), so a Complete over an unpopulated self-record is surfaced.
    NEVER modifies a row; an absent section contributes nothing. Called only for
    `--status Complete`, over the post-mutation sections.

    Also enforces the completion verification-flight evidence gate (issue #1087):
    the ## Progress section must carry exactly one `completion-verification:` marker
    whose canonical record passes the implement-completion validator, re-checked here
    immediately before the PATCH path so edits made after the evidence was recorded
    are caught. A missing/duplicate marker or a non-pass record is a structural
    `_UpdateError` (no PATCH), exactly like the AC hard-fail.

    Also enforces the required-artifact gate (issue #1348): the ## Progress section
    must carry a row for every member of `_REQUIRED_ARTIFACTS` (initially the
    base-update checkpoint-4 record, satisfiable by its clean OR tier-refused
    marker). A missing row is a structural `_UpdateError` (no PATCH) whose message
    names the exact producing command. Like every other check here it is a pure read
    that never mutates a row — every repair lives earlier in the producer.

    Also enforces the review-coverage gate (issue #1453): the ## Progress section must
    carry exactly one resolvable review-coverage record showing the Phase 3 review
    pass ran in full, or a disposition for each gap it records, over a fan-out that
    was actually dispatched. An unestablished record, an undispositioned gap, an
    undispatched pass, or a boilerplate reason is a structural `_UpdateError` (no
    PATCH), like every other member here.

    Also enforces the extension-row gate (issue #1817): every `_EXTENSION_ROWS`
    `prompt extension resolved:` row present in ## Progress must be ticked or carry a
    `state not established` note, so a resolved-but-unrecorded row cannot pass
    silently. A wholly-absent row set (a pre-#1462 workpad) is tolerated. A violation
    is a structural `_UpdateError` (no PATCH), like every other member here."""
    # Completion-evidence gate first: it is the strictest precondition and its
    # failure is the one issue #1087 exists to enforce. `args` is REQUIRED (never
    # defaulted) so the gate can never be silently skipped by an argument omission —
    # a Complete write without the evidence check would fail open on exactly the
    # guarantee this change adds.
    prog_idx = _find_section(sections, 'Progress')
    prog_content = sections[prog_idx][1] if prog_idx is not None else ''
    _completion_evidence_verdict(args, prog_content)
    _required_artifact_verdict(prog_content)
    _review_coverage_verdict(prog_content)
    _extension_row_verdict(prog_content)
    ac_idx = _find_section(sections, 'Acceptance Criteria')
    if ac_idx is not None:
        ac_content = sections[ac_idx][1]
        non_pm, _pm = _unticked_rows(ac_content)
        if non_pm:
            rows = '\n'.join(f'    - [ ] {t}' for t in non_pm)
            raise _UpdateError(
                "refusing to finalize Status: Complete — "
                f"{len(non_pm)} non-post-merge Acceptance Criteria row(s) still "
                "unticked (tick each once its work is real, or route the run to "
                f"Blocked, before finalizing):\n{rows}"
            )
        # Fail-open guard: no unticked rows can mean the section was never mirrored
        # (still the `new-body` placeholder), not that every AC is satisfied. Warn
        # (non-blocking) so a Complete finalize over an un-mirrored self-record is
        # surfaced rather than passing silently. A genuinely AC-less issue carries
        # the DISTINCT `_(none provided in issue body)_` sentinel, so it is unaffected.
        if _AC_PENDING_PLACEHOLDER in ac_content:
            sys.stderr.write(
                "workpad.py update: warning: finalizing Status: Complete but the "
                "## Acceptance Criteria section still holds the un-mirrored placeholder "
                "— the self-record was never populated from the issue; verify the "
                "acceptance criteria were mirrored before relying on this Complete.\n"
            )
    plan_idx = _find_section(sections, 'Plan')
    if plan_idx is None:
        return []
    non_pm, pm = _unticked_rows(sections[plan_idx][1])
    return non_pm + pm  # Plan has no post-merge concept; warn on every unticked row


# ── Idempotent keyed checkpoints + offline handoff record (issue #537) ──────────
#
# Two independent additions that together make the /devflow:implement startup
# lifecycle observable in the workpad:
#
#   * `update --checkpoint KEY TEXT` writes ONE timestamped ## Progress row that
#     carries a hidden `<!-- prflow:checkpoint KEY -->` marker. A second call with
#     the same KEY is an idempotent REPLAY (the marker is already present) and adds
#     no duplicate row; a checkpoint-only replay whose every key already exists is a
#     pure no-op — no `Last updated` refresh, no PATCH (see `_NoOpReplay`). The key
#     grammar and the ## Progress structure are validated BEFORE any PATCH, so an
#     invalid key / multi-line TEXT / duplicate marker / marker-outside-Progress /
#     DUPLICATE ## Progress / empty body is a structural failure that mutates
#     nothing. An ABSENT ## Progress is the one shape that is not a failure: it is
#     repaired (created at the head of the section list) ahead of that validation,
#     because the then-documented `--note` degrade (removed outright by issue #1348)
#     located the same section and raised too, so that shape had no working path at
#     all (issue #1347).
#   * `handoff-state FILE …` validates the workflow-owned gate→claude handoff record
#     OFFLINE (no gh, no network) and prints one of three origin tokens, degrading
#     every malformed/mismatched shape to `unknown` with a targeted breadcrumb.
# `\A…\Z` (not `^…$`): this grammar is the injection boundary for the HTML-comment
# marker `<!-- prflow:checkpoint KEY -->`, and Python's `$` also matches just before a
# single trailing newline — so `^…$` would admit a key like "gha:1:1:stage\n" and inject
# a newline into the marker/Progress bullet. `\Z` matches only at the true end of string,
# keeping the key strictly single-line.
_CHECKPOINT_KEY_RE = re.compile(r'\A[A-Za-z0-9._:-]+\Z')


def _checkpoint_marker(key: str) -> str:
    """The hidden HTML-comment marker a checkpoint row carries so a replay can
    detect the key without changing the visible timestamped-note rendering."""
    return f'<!-- prflow:checkpoint {key} -->'


# The declared required-artifact set (issue #1348): each member is a run artifact
# the terminal `--status Complete` gate requires a recorded `## Progress` row for, so
# a run cannot reach a published, Complete end state having silently skipped the step
# that produces one. A member is identified by its primary marker `key` and satisfied
# by ANY of its `accept_keys` — the clean checkpoint-4 key OR #1347's tier-refused
# variant, so a tier-refused run still completes. `producer` names, verbatim, the
# command a human runs to record the missing row; the gate quotes it in the refusal.
# The set is DATA that the gate iterates, so a second member extends the gate (and,
# via the derived strip set below, the Phase 1.3 resume strip) without touching
# either loop. Initially exactly one member: `base-update-checkpoint-4`.
_REQUIRED_ARTIFACTS = (
    {
        'key': 'base-update-checkpoint-4',
        'accept_keys': (
            'base-update-checkpoint-4',
            'base-update-checkpoint-4-tier-refused',
        ),
        'producer': (
            "the Phase 4.3 base-update checkpoint 4 step "
            "(update-branch-checkpoint.sh, recorded on the workpad with "
            "`workpad.py update <issue> --checkpoint base-update-checkpoint-4 "
            "\"<token>\"`; a tier-refused run instead records "
            "`--checkpoint base-update-checkpoint-4-tier-refused`)"
        ),
    },
)

# The flat required-artifact checkpoint keys (issue #1347's resume strip): keyed rows
# that describe THIS attempt rather than the workpad, so a resumed run must not
# inherit the previous attempt's copy. DERIVED from _REQUIRED_ARTIFACTS (issue #1348)
# so a new member — or a new accepting spelling — extends both the terminal gate and
# this strip by construction, never a hand-transcribed second list. Every member is
# deliberately outside the `gha:` prefix — that prefix is the review-tier cloud/local
# discriminator and checkpoint 4 runs on both tiers — which is also what makes a strip
# scoped to this set unable to reach a `gha:` row.
_REQUIRED_ARTIFACT_CHECKPOINT_KEYS = tuple(
    key for artifact in _REQUIRED_ARTIFACTS for key in artifact['accept_keys']
)


def _repair_missing_progress_section(body: str) -> str:
    """Re-create an absent `## Progress` section at the head of the section list.

    `--checkpoint` writes into `## Progress` and fails structurally when it is
    absent — and the then-documented `--note` degrade (removed outright by issue
    #1348) located the same section, so an otherwise intact workpad missing just that
    one section had no working path to record a checkpoint outcome at all (issue
    #1347). This repairs it mid-update so
    the run self-heals with no human involved.

    Deliberately narrow: an empty/whitespace-only body is returned unchanged, so
    `--checkpoint` still raises on it and no skeleton is ever synthesized (that is
    `new-body`'s job). A body already carrying one or more `## Progress` sections is
    likewise unchanged — the duplicate-section shape keeps failing closed.
    """
    if not body.strip():
        return body
    preamble, sections = _split_sections(body)
    # `_find_section` is the file's canonical (case-insensitive) section locator —
    # the same one `_plan_checkpoints` and every Progress writer use, so "present"
    # cannot mean something different here than it does downstream. It answers with
    # the FIRST match, which is why the duplicate-section shape still reaches
    # `_plan_checkpoints`' own count check and fails closed there.
    if _find_section(sections, 'Progress') is not None:
        return body
    # Deliberately SILENT here — the caller announces it, and only once the rest of
    # `--checkpoint`'s validation has passed. Breadcrumbing from inside the repair
    # would claim a self-heal that a later structural raise (a multi-line text, a
    # duplicate marker) then discards with zero PATCH, telling a maintainer the
    # workpad was rewritten when nothing was written at all.
    return _join_sections(
        preamble, _insert_section_at_head(sections, '## Progress', ''),
    )


def _announce_progress_repair() -> None:
    """Breadcrumb a `## Progress` repair that has cleared validation.

    A repair rewrites a human-visible GitHub artifact, so a maintainer reading the
    workpad later must be able to tell a re-created section from one that was
    always there; every sibling degrade in this file breadcrumbs to stderr for the
    same reason. Emitted by the caller at `_apply_mutations`' successful return —
    after every raising mutation in it, not merely after `_plan_checkpoints` — so
    the breadcrumb tracks a repaired body that survived every structural check and
    is being returned for the PATCH, never one a later guard discarded.
    """
    sys.stderr.write(
        "workpad.py update: '## Progress' was absent; re-created it at the head of "
        "the section list so the checkpoint could be recorded (issue #1347 repair)\n"
    )


# Both marker spellings of every declared key, derived once at import from the key
# set above — never a transcribed literal, so adding a key extends the strip by
# construction. The dual spelling is the #1003 rename read-through: a row written
# before the rename is still this attempt's inheritance.
_REQUIRED_ARTIFACT_MARKER_VARIANTS = tuple(
    v for key in _REQUIRED_ARTIFACT_CHECKPOINT_KEYS
    for v in _marker_variants(_checkpoint_marker(key))
)


def _strip_required_artifact_checkpoint_rows(content: str) -> str:
    """Remove every `## Progress` row carrying a declared required-artifact
    checkpoint marker, in either marker spelling.

    The sibling of `_strip_completion_marker_rows`, and the same idiom: a record
    describing *this* attempt is per-attempt, so the Phase 1.3 resume arm clears an
    inherited copy before the run proceeds rather than letting an earlier attempt's
    row answer for this one. Scoped to `_REQUIRED_ARTIFACT_CHECKPOINT_KEYS`, whose
    members are non-`gha:` by construction, so a `gha:` run-scoped row is never
    reached.
    """
    kept = [ln for ln in content.splitlines(keepends=True)
            if not any(v in ln for v in _REQUIRED_ARTIFACT_MARKER_VARIANTS)]
    return ''.join(kept)


class _NoOpReplay(Exception):
    """Signals a supported pure replay before any mutation occurs.

    `kind` distinguishes the existing keyed-checkpoint replay from an
    implement-driven review-boundary replay, so `cmd_update` can emit an accurate
    breadcrumb while sharing the same success/no-PATCH control path.

    Raised by `_apply_mutations` BEFORE it mutates anything; `cmd_update` catches
    it, echoes the unchanged body only under `--print-body`, and exits 0 without
    refreshing `Last updated` or issuing a PATCH. Deliberately not an
    `_UpdateError`: a replay is success, not a structural failure.
    """

    def __init__(self, kind: str = 'checkpoint'):
        super().__init__(kind)
        self.kind = kind


def _has_non_checkpoint_mutation(args) -> bool:
    """True when the update carries at least one mutation OTHER than `--checkpoint`.

    Drives the AC14 idempotency short-circuit: a checkpoint-only call whose keys are
    all already present and that carries no other mutation is a pure no-op. A
    `--checkpoint` combined with any of these still refreshes `Last updated` and
    PATCHes once (and does not duplicate an existing checkpoint)."""
    return any([
        args.status, args.branch, args.run_link, args.pr_link,
        args.tick_progress, args.tick_plan, args.tick_plan_n,
        args.tick_ac, args.tick_ac_n, args.rewrite_ac,
        args.replace_plan_file, args.replace_acs_file, args.set_reproduction_file,
        args.note, args.reflection, args.reflection_file,
        getattr(args, 'note_file', None),
        args.record_classification, args.reconcile_reproduction,
        args.scope_decision_deferred, args.scope_decision_rewritten,
        args.bind_scope_decisions, args.mark_deferred_filed,
        getattr(args, 'mark_deferred_filed_file', None),
        getattr(args, 'record_completion_evidence', None),
        getattr(args, 'record_completion_evidence_ci', None),
        getattr(args, 'record_review_coverage', None),
        getattr(args, 'review_coverage_disposition', None),
        getattr(args, 'strip_inherited_checkpoints', False),
        getattr(args, 'reconcile_extension_rows', False),
        getattr(args, 'record_resume_point', None),
    ])


def _is_review_progress_replay(body: str, args) -> bool:
    """Return true for a pure replay of already-ticked review-boundary rows.

    Exact operands declared by `_REVIEW_PROGRESS_ROWS` are successful no-ops only
    when every requested row resolves uniquely and is already ticked. Unknown,
    missing, ambiguous, or unticked operands retain ordinary tick/miss behavior.
    """
    requested = list(args.tick_progress or [])
    declared = {substr for _text, substr in _REVIEW_PROGRESS_ROWS}
    if not requested or any(text not in declared for text in requested):
        return False
    if getattr(args, 'checkpoint', None):
        return False
    without_review_ticks = argparse.Namespace(**vars(args))
    without_review_ticks.tick_progress = []
    if _has_non_checkpoint_mutation(without_review_ticks):
        return False

    _preamble, sections = _split_sections(body)
    idx = _find_section(sections, 'Progress')
    if idx is None:
        return False
    _heading, content = sections[idx]
    rows = [m for line in content.splitlines()
            if (m := _CHECKBOX_ROW_RE.match(line))]
    for text in requested:
        matches = [m for m in rows if text.lower() in m.group(4).lower()]
        if len(matches) != 1 or matches[0].group(2).lower() != '[x]':
            return False
    return True


def _require_arity(flag: str, value: object, n: int, labels: tuple[str, ...]) -> None:
    """Validate that a fixed-`nargs` operand is a length-`n` sequence before any
    positional unpack, raising a named `_UpdateError` (structural — no PATCH) on a
    wrong shape. argparse enforces this for every CLI invocation, so the guard exists
    for the programmatic caller (the suite builds `args` directly and can pass a short
    list, a long one, or a bare string). A `str` is rejected explicitly: it is a
    sequence, so a 2-char string like `"k1"` would otherwise unpack silently into
    `('k', '1')` and write a corrupt row rather than raising (issue #1501)."""
    labels_txt = ', '.join(labels)
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise _UpdateError(
            f"{flag} takes exactly {n} values ({labels_txt}); got a non-sequence "
            f"{value!r}. No PATCH was made."
        )
    if len(value) != n:
        raise _UpdateError(
            f"{flag} takes exactly {n} values ({labels_txt}); got {len(value)}. "
            f"No PATCH was made."
        )


def _plan_checkpoints(body: str, checkpoint_reqs) -> list[tuple[str, str]]:
    """Validate `--checkpoint` requests against `body` and return the (key, text)
    pairs that must be INSERTED (their marker is absent). A request whose marker is
    already present exactly once in ## Progress is an idempotent replay and is
    omitted from the returned list. Raises `_UpdateError` (structural — no PATCH)
    on every invalid shape, so validation completes before any mutation:

      * a key not matching `[A-Za-z0-9._:-]+`,
      * a key repeated within a single batch,
      * an empty/whitespace-only body,
      * zero or more-than-one `## Progress` section,
      * a key marker present outside ## Progress,
      * a key marker present more than once inside ## Progress."""
    # 1. Key grammar — checked first so a bad key fails before any body inspection.
    #    A key repeated within one batch is also structural: both copies would see
    #    in_prog==0 (the body is read once, before any insert) and be appended, so
    #    _apply_mutations would write the marker twice — wedging every future replay
    #    of that key on the `in_prog > 1` check below. Reject it up front instead.
    _seen_keys: set[str] = set()
    for _req in checkpoint_reqs:
        # Arity before the positional unpack (issue #1501): a wrong-length element —
        # or a bare string like `"k1"`, which would unpack silently into `key='k',
        # text='1'` and write a corrupt checkpoint row — raises a named refusal here
        # rather than a bare traceback below.
        _require_arity('--checkpoint', _req, 2, ('KEY', 'TEXT'))
        key, _text = _req
        if not _CHECKPOINT_KEY_RE.match(key):
            raise _UpdateError(
                f"--checkpoint key {key!r} is invalid; keys must match "
                f"[A-Za-z0-9._:-]+ . No PATCH was made."
            )
        if key in _seen_keys:
            raise _UpdateError(
                f"--checkpoint key {key!r} appears more than once in a single "
                f"batch; keys must be unique per call. No PATCH was made."
            )
        # Reserved key namespaces (issue #1453). The generic `--checkpoint` head would
        # otherwise write a row in one of the validated marker families, bypassing that
        # family's own validation — for a review-coverage disposition that includes the
        # `dropped-failed` reflection the disposition writer files by construction, so
        # the retrospective routing the dedicated flag guarantees would be defeatable
        # through a different flag. Refuse, naming the flag that owns the namespace.
        for _prefix, _owner in _RESERVED_CHECKPOINT_KEY_PREFIXES:
            if key.startswith(_prefix):
                raise _UpdateError(
                    f"--checkpoint key {key!r} is in the reserved {_prefix!r} "
                    f"namespace; record it with {_owner} instead, the flag that owns "
                    "that namespace. No PATCH was made."
                )
        # A line boundary splits the row across physical lines and leaves the marker
        # on the LAST one — so a line-filtering strip (`--strip-inherited-checkpoints`,
        # `_strip_completion_marker_rows`) removes the marker while orphaning the
        # visible text, leaving the human-readable workpad and the machine-read field
        # asserting opposite things. Reject it before any PATCH, exactly as
        # `--record-classification` rejects a multi-line rationale (issue #1347).
        if not _is_single_line(_text):
            raise _UpdateError(
                f"--checkpoint text for key {key!r} must be a single line (a line "
                f"boundary would split the row and orphan its marker). No PATCH was "
                f"made."
            )
        _seen_keys.add(key)
    # 2. Canonical ## Progress: non-empty body + exactly one Progress heading.
    # Split the body's sections ONCE and both count and locate Progress from that
    # single parse (rather than a separate finditer scan) — the canonical
    # section-locating idiom the rest of the file uses.
    if not body.strip():
        raise _UpdateError(
            "--checkpoint requires a canonical workpad body, but the body is "
            "empty/whitespace-only [empty-body]. Remedy: reconstruct the workpad "
            "with `workpad.py new-body` + `create` (a whitespace-only body has no "
            "front matter, so re-creating one section alone would still fail every "
            "other mutation). No PATCH was made."
        )
    _pre, _sections = _split_sections(body)
    n_prog = sum(1 for h, _c in _sections if h.strip().lower() == '## progress')
    if n_prog != 1:
        raise _UpdateError(
            f"--checkpoint requires exactly one '## Progress' section, but "
            f"{n_prog} are present [duplicate-progress]. Remedy: edit the workpad so "
            f"exactly one '## Progress' section remains (the checkpoint is never "
            f"merged or reordered across duplicates). No PATCH was made."
        )
    _pidx = _find_section(_sections, 'Progress')
    prog_content = _sections[_pidx][1]
    # 3. Per-key marker cardinality: absent (insert), once-in-Progress (replay),
    #    or a structural failure (outside Progress / duplicate).
    inserts: list[tuple[str, str]] = []
    for key, text in checkpoint_reqs:
        # Both spellings, summed: a checkpoint row written before the rename
        # still counts, so a post-rename replay of the same key is a no-op
        # rather than a duplicate row (issue #1003).
        variants = _marker_variants(_checkpoint_marker(key))
        total = sum(body.count(v) for v in variants)
        in_prog = sum(prog_content.count(v) for v in variants)
        if total != in_prog:
            raise _UpdateError(
                f"--checkpoint key {key!r} marker appears outside the "
                f"'## Progress' section [marker-anomaly]. Remedy: move the "
                f"checkpoint row into '## Progress' (its marker is only read there); "
                f"choosing which copy is authoritative cannot be automated. No PATCH "
                f"was made."
            )
        if in_prog > 1:
            raise _UpdateError(
                f"--checkpoint key {key!r} marker appears {in_prog} times in "
                f"'## Progress' (expected 0 or 1) [marker-anomaly]. Remedy: remove "
                f"the duplicate checkpoint row so exactly one remains; choosing which "
                f"copy is authoritative cannot be automated. No PATCH was made."
            )
        if in_prog == 0:
            inserts.append((key, text))
    return inserts


_HANDOFF_ORIGINS = ('created-current-run', 'adopted-existing', 'unknown')


def _handoff_unknown(reason: str):
    """Print `unknown`, write a targeted stderr breadcrumb, and exit 0.

    The single degradation chokepoint for `cmd_handoff_state` — every malformed,
    mismatched, or unreadable record routes here, so provenance always degrades
    VISIBLY to neutral (`unknown`) rather than blocking the run or guessing."""
    sys.stderr.write(
        f"workpad.py handoff-state: {reason}; resolving origin=unknown\n"
    )
    print('unknown')
    sys.exit(0)


def cmd_handoff_state(args):
    """Validate the workflow-owned gate→claude handoff record OFFLINE and print the
    resolved origin token (one of `created-current-run`, `adopted-existing`,
    `unknown`). Always exits 0. No network access — a pure file read.

    The record is a five-field JSON object: `schema_version` (int 1), `issue`
    (int), `run_id` (digit string), `run_attempt` (digit string), and `origin`
    (one of the three tokens). Every degraded shape — missing/unreadable/undecodable
    file, malformed JSON, a non-object (array/scalar/null), an unsupported schema
    version, a wrong field type, an issue/run identity mismatch, or an unrecognized
    origin — resolves to `unknown` with a targeted breadcrumb (see AC4). A record
    that validates cleanly but carries `origin: "unknown"` prints `unknown` with NO
    breadcrumb (the explicit-unknown handoff, AC11), distinct from a degraded shape."""
    p = Path(args.file)
    try:
        raw = p.read_text(encoding='utf-8')
    except FileNotFoundError:
        _handoff_unknown(f"record file not found: {p}")
    except (OSError, UnicodeDecodeError) as e:
        _handoff_unknown(f"record file unreadable/undecodable ({p}): {e}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        _handoff_unknown(f"record is not valid JSON ({p}): {e}")
    if not isinstance(data, dict):
        _handoff_unknown(
            f"record is not a JSON object (got {type(data).__name__})"
        )
    # schema_version — reject bools (isinstance(True, int) is True in Python) and
    # any non-1 / non-int value as an unsupported/wrong-type version.
    sv = data.get('schema_version')
    if isinstance(sv, bool) or not isinstance(sv, int):
        _handoff_unknown(f"schema_version must be integer 1 (got {sv!r})")
    if sv != 1:
        _handoff_unknown(f"unsupported schema_version {sv!r} (expected 1)")
    # issue — int, matching the run's resolved issue.
    iss = data.get('issue')
    if isinstance(iss, bool) or not isinstance(iss, int):
        _handoff_unknown(f"issue must be an integer (got {iss!r})")
    if iss != args.issue:
        _handoff_unknown(
            f"issue mismatch: record {iss!r} != expected {args.issue!r}"
        )
    # run_id / run_attempt — digit strings, matching the current GitHub contexts.
    rid = data.get('run_id')
    if not isinstance(rid, str) or not rid.isdigit():
        _handoff_unknown(f"run_id must be a digit string (got {rid!r})")
    if rid != str(args.run_id):
        _handoff_unknown(
            f"run_id mismatch: record {rid!r} != expected {str(args.run_id)!r}"
        )
    rat = data.get('run_attempt')
    if not isinstance(rat, str) or not rat.isdigit():
        _handoff_unknown(f"run_attempt must be a digit string (got {rat!r})")
    if rat != str(args.run_attempt):
        _handoff_unknown(
            f"run_attempt mismatch: record {rat!r} != "
            f"expected {str(args.run_attempt)!r}"
        )
    # origin — must be one of the three tokens. An unrecognized value degrades to
    # `unknown` (AC4); a valid `unknown` prints through cleanly below (AC11).
    origin = data.get('origin')
    if origin not in _HANDOFF_ORIGINS:
        _handoff_unknown(f"origin {origin!r} not one of {_HANDOFF_ORIGINS}")
    print(origin)
    sys.exit(0)


def _normalize_handoff_origin(gate: str) -> str:
    """Normalize a gate-provided handoff token to exactly one of `_HANDOFF_ORIGINS`.

    Any unrecognized value degrades to `unknown` — including the empty string a
    partially-upgraded consumer emits (its gate job predates the `handoff` job output),
    and any token the gate never wrote. The write-side counterpart to
    `cmd_handoff_state`'s read-side `origin not in _HANDOFF_ORIGINS` degradation, sharing
    the SAME `_HANDOFF_ORIGINS` vocabulary so producer and consumer cannot drift."""
    return gate if gate in _HANDOFF_ORIGINS else 'unknown'


def cmd_write_handoff_record(args):
    """Write the five-field gate->claude handoff record (issue #537), normalizing the
    gate-provided origin to one of `_HANDOFF_ORIGINS` first. Prints nothing.

    The workflow-owned, gitignored, non-secret, advisory record that `cmd_handoff_state`
    reads back offline. `origin` is normalized via `_normalize_handoff_origin` (an empty
    or unrecognized gate token becomes `unknown`). A write/permission failure (or a
    non-integer `issue`) raises — the workflow's `if ! python3 … ; then` wrapper turns
    that into a best-effort ::warning::, and Phase 1 then degrades to unknown provenance
    at read time. The JSON shape is the exact record `cmd_handoff_state` validates:
    schema_version (int 1), issue (int), run_id/run_attempt (strings), origin (token)."""
    origin = _normalize_handoff_origin(args.gate)
    # Resolve the int BEFORE opening (truncating) the target, so a non-integer issue
    # raises and the `if !` wrapper warns without leaving a zero-byte record behind.
    issue = int(args.issue)
    with open(args.file, 'w', encoding='utf-8') as fh:
        json.dump({'schema_version': 1, 'issue': issue,
                   'run_id': args.run_id, 'run_attempt': args.run_attempt,
                   'origin': origin}, fh)


def _validate_scope_decision_pr(raw: str, flag: str) -> str:
    """Accept a decimal PR number or the literal `pending`, else abort.

    Structural (no PATCH) rather than a coerced default: a mistyped PR value
    would produce a record that binds to no PR at all, and a record that covers
    nothing is exactly what makes the Phase 0.4 membership check report a drop
    the run had in fact audited.
    """
    value = raw.strip()
    if value == _SCOPE_DECISION_PENDING_PR or value.isdigit():
        return value
    raise _UpdateError(
        f"{flag}: PR must be a decimal number or the literal "
        f"'{_SCOPE_DECISION_PENDING_PR}', got {raw!r}. No PATCH was made."
    )


def _validate_scope_decision_text(raw: str, flag: str, label: str) -> str:
    """Reject an empty/whitespace-only criterion text.

    A record whose text normalizes to nothing matches every criterion or none
    depending on the comparison, so it is never a usable comparand — fail closed
    here instead of writing a record that silently covers the wrong row.
    """
    if not normalize_criterion(raw):
        raise _UpdateError(
            f"{flag}: {label} text is empty or whitespace-only; a scope-decision "
            f"record must name the criterion it covers. No PATCH was made."
        )
    return raw


def _render_scope_decisions(args) -> list[str]:
    """Validate and render every `--scope-decision-*` request to a record line."""
    notes: list[str] = []
    if getattr(args, 'scope_decision_deferred', None) or getattr(
            args, 'scope_decision_rewritten', None):
        # Normalizing the criterion text is what makes a record comparable to
        # the review engine's normalized sets, so a record written without it
        # would be silently uncomparable rather than merely unformatted.
        _require_section_parse('update --scope-decision-*')
    for _elem in getattr(args, 'scope_decision_deferred', None) or []:
        flag = '--scope-decision-deferred'
        _require_arity(flag, _elem, 2, ('PR', 'TEXT'))  # issue #1501
        pr, text = _elem
        notes.append(_render_scope_decision(
            _validate_scope_decision_pr(pr, flag),
            'deferred',
            _validate_scope_decision_text(text, flag, 'criterion'),
        ))
    for _elem in getattr(args, 'scope_decision_rewritten', None) or []:
        flag = '--scope-decision-rewritten'
        _require_arity(flag, _elem, 3, ('PR', 'OLD', 'NEW'))  # issue #1501
        pr, old, new = _elem
        notes.append(_render_scope_decision(
            _validate_scope_decision_pr(pr, flag),
            'rewritten',
            _validate_scope_decision_text(old, flag, 'OLD criterion'),
            _validate_scope_decision_text(new, flag, 'NEW criterion'),
        ))
    return notes


def _apply_mutations(body: str, args, failed_ticks) -> str:
    """Apply all mutations from args and return the new body.

    Structural failures (missing section / front-matter line / unreadable file)
    raise `_UpdateError` before returning — the caller must not PATCH. Volatile
    per-row tick misses are appended to the caller-provided `failed_ticks` list
    (a flat list of descriptor strings) and do NOT abort: the body returned still
    carries every other mutation, and the caller PATCHes it then reports the
    failed ticks. `failed_ticks` is a required out-parameter (no silent-swallow
    default); `cmd_update` is the production caller and always supplies one."""
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    # Friendly UTC for the human-facing `Last updated` line (the `now`
    # subcommand still prints full ISO-8601 for machine uses like follow-up
    # issue bodies; note bullets keep their time-only HH:MM:SS prefix).
    last_updated = now_dt.strftime('%Y-%m-%d %H:%M UTC')
    now_time = now_dt.strftime('%H:%M:%S')        # time-only for note bullets

    # Idempotent keyed checkpoints (issue #537). Validate + plan them FIRST, before
    # any body mutation, so an invalid key / malformed ## Progress structure is a
    # structural failure that changes nothing (all-or-nothing). `checkpoint_inserts`
    # holds only the keys whose marker is absent (a present marker is a replay and
    # is skipped). A checkpoint-only call whose every key already exists AND that
    # carries no other mutation is a pure no-op: raise `_NoOpReplay` here so
    # `cmd_update` skips the `Last updated` refresh and the PATCH entirely.
    checkpoint_reqs = getattr(args, 'checkpoint', None) or []
    # Arity before ANY positional unpack of a checkpoint request (issue #1501): the
    # --strip-inherited-checkpoints clash set below unpacks `k, _t` before
    # _plan_checkpoints runs, so a wrong-length element on the strip path would raise a
    # bare ValueError there rather than the named refusal. Validate every element here,
    # above that unpack; _plan_checkpoints keeps its own guard for its standalone contract.
    for _req in checkpoint_reqs:
        _require_arity('--checkpoint', _req, 2, ('KEY', 'TEXT'))
    checkpoint_inserts: list[tuple[str, str]] = []
    # Bound here, not inside the `if checkpoint_reqs:` arm below, because the
    # deferred announce at this function's return reads it on EVERY path.
    _did_repair = False
    strip_inherited = bool(getattr(args, 'strip_inherited_checkpoints', False))
    if strip_inherited:
        # AC10 (issue #1347): `_plan_checkpoints` computes its inserts against the
        # PRE-strip body, so a single call that both stripped and inserted the same
        # key would read the inherited row as a replay, skip the insert, then strip
        # the row it just declined to rewrite — silently losing it. Reject the
        # combination structurally (before any PATCH) rather than ordering around
        # it, so the hazard is unreachable rather than merely avoided today.
        _clash = sorted(
            {k for k, _t in checkpoint_reqs}
            & set(_REQUIRED_ARTIFACT_CHECKPOINT_KEYS)
        )
        if _clash:
            raise _UpdateError(
                "--strip-inherited-checkpoints cannot be combined with "
                f"--checkpoint for the same declared key(s): {', '.join(_clash)}. "
                "Strip and record in separate calls. No PATCH was made."
            )
    if checkpoint_reqs:
        # Repair an absent `## Progress` BEFORE the section-shape validation below,
        # so the validation sees the repaired body (issue #1347). The breadcrumb for
        # it is deferred all the way to this function's successful return — see the
        # announce site there for why "after `_plan_checkpoints`" was not far enough.
        _repaired_body = _repair_missing_progress_section(body)
        _did_repair = _repaired_body is not body
        body = _repaired_body
        checkpoint_inserts = _plan_checkpoints(body, checkpoint_reqs)
        if not checkpoint_inserts and not _has_non_checkpoint_mutation(args):
            raise _NoOpReplay()

    # Review re-entry can repeat a boundary whose tuple row is already ticked.
    # Decide that pure replay before Last updated or any other body mutation.
    if _is_review_progress_replay(body, args):
        raise _NoOpReplay('review-progress')

    # Completion verification-flight evidence recording (issue #1087). Validate the
    # record BEFORE any body mutation so a non-pass key is a structural failure that
    # changes nothing (all-or-nothing); the marker row is written below.
    record_flight_key = getattr(args, 'record_completion_evidence', None)
    if record_flight_key:
        _validate_flight_key(args, record_flight_key)

    # CI-derived completion evidence recording (issue #1611). Validate the decoded
    # record BEFORE any body mutation so a non-pass record is a structural failure
    # that changes nothing (all-or-nothing), exactly like the flight key above; the
    # marker row is written below. The four operands are the re-audit fields.
    record_ci = getattr(args, 'record_completion_evidence_ci', None)
    ci_payload = None
    if record_ci:
        _require_arity(
            '--record-completion-evidence-ci', record_ci, 3,
            ('HEAD_SHA', 'TIER', 'RUN_URL'))
        _ci_head, _ci_tier, _ci_url = record_ci
        # Each --completion-ci-check pair becomes a {name, conclusion} check object; the
        # validator refuses a record whose checks do not cover the required set or whose
        # tier is not `local` (issue #1898). argparse's nargs=2 guarantees the pair arity
        # from the CLI, but a programmatic caller can pass a short list, so re-check it.
        ci_check_pairs = getattr(args, 'completion_ci_check', None) or []
        checks = []
        for _pair in ci_check_pairs:
            _require_arity(
                '--completion-ci-check', _pair, 2, ('NAME', 'CONCLUSION'))
            checks.append({'name': _pair[0], 'conclusion': _pair[1]})
        ci_record = {
            'head_sha': _ci_head,
            'tier': _ci_tier,
            'run_url': _ci_url,
            'checks': checks,
        }
        ci_payload = _encode_ci_payload(ci_record)
        _validate_ci_evidence(args, ci_payload)

    # Mid-phase resume-point record (issue #1876). No validation — it is a NAVIGATION
    # aid, never evidence — so unlike the completion families above it needs no
    # before-mutation validation pass; the payload is encoded here and the row written
    # below (replacing any prior resume-point row).
    record_resume_point = getattr(args, 'record_resume_point', None)
    resume_point_payload = (
        _encode_resume_point(record_resume_point) if record_resume_point else None)

    # Review-coverage record + dispositions (issue #1453). Validated here, BEFORE any
    # body mutation, for the same all-or-nothing reason as the flight key above; the
    # rows are written below beside the completion-evidence marker. Read via getattr
    # so a standalone `workpad.py` copy invoked with an older arg shape degrades to
    # "flag absent" rather than raising AttributeError.
    review_coverage = getattr(args, 'record_review_coverage', None)
    review_coverage_payload = None
    review_coverage_auto_notes: list[str] = []
    if review_coverage:
        # Arity is guaranteed by argparse's nargs=4 from the CLI, but a programmatic
        # caller (the suite builds `args` directly) can pass a short list, which `zip`
        # would silently truncate — or a bare str, which `len()` alone would wave
        # through to a character-wise unpack. `_require_arity` rejects the non-sequence
        # explicitly and enforces the count, so the guarantee is local rather than
        # inherited from a distant declaration.
        _require_arity(
            '--record-review-coverage', review_coverage,
            len(_REVIEW_COVERAGE_AXES), _REVIEW_COVERAGE_AXES)
        for axis, value in zip(_REVIEW_COVERAGE_AXES, review_coverage):
            if value not in _REVIEW_COVERAGE_VOCABULARY[axis]:
                raise _UpdateError(
                    f"--record-review-coverage: unknown {axis} value {value!r}; "
                    f"expected one of "
                    f"{', '.join(_REVIEW_COVERAGE_VOCABULARY[axis])}. "
                    "No PATCH was made."
                )
        incoherent = _review_coverage_incoherence(
            dict(zip(_REVIEW_COVERAGE_AXES, review_coverage)))
        if incoherent:
            raise _UpdateError(
                f"--record-review-coverage: {incoherent}. No PATCH was made."
            )
        # issue #1510: stamp the record's as-of anchor — the reviewed head SHA it was
        # derived from (from the caller, else `unestablished`) and the UTC write time.
        # A bad head is a structural refusal here so no half-anchored record is written.
        _anchor_head = (getattr(args, 'record_review_coverage_head', None)
                        or _REVIEW_COVERAGE_ANCHOR_UNESTABLISHED)
        if not _REVIEW_COVERAGE_ANCHOR_HEAD_RE.match(_anchor_head):
            raise _UpdateError(
                f"--record-review-coverage-head: {_anchor_head!r} is not a "
                "lowercase-hex head SHA (or 'unestablished'). No PATCH was made."
            )
        # issue #1509: a `skipped-intentional` checklist claim is accepted only when the
        # diff it was recorded over satisfies the profile row that authorizes the skip
        # (skills/review/phases/phase-0-setup.md §0.5). Recompute the diff from git over
        # the reviewed head (the anchor above) against the PR base: a resolved-and-
        # disproved row is a hard refusal (AC3); an unresolvable measurement downgrades
        # the axis to `unestablished` — never a refusal (AC5); an explicit --override
        # downgrades to bare `skipped` (non-clean, forces a disposition — AC13); a
        # confirmed row keeps the value and writes exactly today's record (AC6).
        # Copy here — after _require_arity above proved it is a real sequence — so the
        # downgrade never mutates the caller's list and a non-sequence still hits the
        # arity refusal rather than this list() (issue #1544).
        review_coverage = list(review_coverage)
        _checklist_idx = _REVIEW_COVERAGE_AXES.index('checklist')
        _rc_override = getattr(args, 'record_review_coverage_override', None)
        if review_coverage[_checklist_idx] == 'skipped-intentional':
            if _rc_override:
                review_coverage[_checklist_idx] = 'skipped'
                review_coverage_auto_notes.append(
                    'review-coverage recomputation overridden — the '
                    'skipped-intentional checklist claim is recorded as bare `skipped` '
                    '(non-clean; a --review-coverage-disposition is required): '
                    + _rc_override)
            else:
                _rc_repo_root = getattr(args, 'repo_root', None) or _repo_root()
                _rc_facts = _recompute_diff_facts(
                    _anchor_head, getattr(args, 'record_review_coverage_base', None),
                    _rc_repo_root)
                if not _rc_facts['resolved']:
                    review_coverage[_checklist_idx] = 'unestablished'
                    review_coverage_auto_notes.append(
                        'review-coverage checklist recorded `unestablished` — the '
                        'skipped-intentional diff could not be recomputed: '
                        + _rc_facts['reason'])
                else:
                    _rc_disproof = _review_coverage_profile_disproof(
                        _rc_facts, _rc_repo_root)
                    if _rc_disproof:
                        raise _UpdateError(
                            "--record-review-coverage: a `skipped-intentional` "
                            "checklist claim is not authorized by the diff (measured "
                            f"{_rc_facts['files']} file(s), {_rc_facts['lines']} "
                            f"line(s)): {_rc_disproof}. No PATCH was made."
                        )
                    # AC4: a confirmed write reports the measured values on success.
                    # The engine-source clause is honest per §2.3.6: it names the arm
                    # as verified only in this engine's own repo, where the arm was
                    # actually evaluated; on any other repo the arm is excluded from the
                    # predicate, so the breadcrumb says so rather than asserting a check
                    # that did not run.
                    _rc_engine_note = (
                        'and non-engine-source: verified'
                        if _is_engine_own_repo(_rc_repo_root)
                        else '(engine-source arm not evaluated: not this engine\'s '
                             'repository)')
                    sys.stderr.write(
                        'workpad.py: review-coverage skipped-intentional confirmed — '
                        f"{_rc_facts['files']} changed file(s), {_rc_facts['lines']} "
                        f'changed line(s), path-set config-only {_rc_engine_note}\n')
        elif _rc_override:
            sys.stderr.write(
                'workpad.py: --record-review-coverage-override is ignored — it applies '
                'only to a skipped-intentional checklist, not '
                f"{review_coverage[_checklist_idx]!r}\n")
        _anchor_asof = _utc_now_compact()
        review_coverage_payload = ':'.join(
            list(review_coverage) + [_anchor_head, _anchor_asof])
    # Shadow-review roster enumeration (issue #1512): validated before any body mutation
    # and cross-checked against the roster axis. Read via getattr so an older arg shape
    # (no --record-roster-member) degrades to "flag absent" rather than raising.
    roster_member_pairs = list(getattr(args, 'record_roster_member', None) or [])
    roster_members: dict = {}
    if roster_member_pairs and not review_coverage_payload:
        raise _UpdateError(
            "--record-roster-member must accompany --record-review-coverage, whose "
            "roster axis it cross-checks. No PATCH was made."
        )
    for _pair in roster_member_pairs:
        _require_arity('--record-roster-member', _pair, 2, ('member', 'status'))
    for member, status in roster_member_pairs:
        if member not in _SHADOW_ROSTER_MEMBERS:
            raise _UpdateError(
                f"--record-roster-member: unknown member {member!r}; expected one of "
                f"{', '.join(_SHADOW_ROSTER_MEMBERS)}. No PATCH was made."
            )
        if status not in _ROSTER_MEMBER_STATUSES:
            raise _UpdateError(
                f"--record-roster-member: unknown status {status!r} for member "
                f"{member!r}; expected one of {', '.join(_ROSTER_MEMBER_STATUSES)}. "
                "No PATCH was made."
            )
        if member in roster_members:
            raise _UpdateError(
                f"--record-roster-member: member {member!r} given more than once; pass "
                "one status per member. No PATCH was made."
            )
        roster_members[member] = status
    if review_coverage_payload:
        # #1984: corroborate a claimed shadow fan-out — a dispatch=attempted record
        # with a measured roster needs per-member rows proving members were dispatched.
        # Runs BEFORE the incoherence cross-check so a `short` roster whose rows name no
        # dispatched member (which incoherence, needing only one `missing`, would admit)
        # is refused here. The same predicate re-runs at the Complete gate.
        if _review_coverage_dispatch_uncorroborated(
                dict(zip(_REVIEW_COVERAGE_AXES, review_coverage)), roster_members):
            raise _UpdateError(
                "--record-review-coverage: dispatch=attempted with a measured roster "
                "must be corroborated by --record-roster-member rows covering every "
                "always-on reviewer ("
                + ', '.join(_SHADOW_ALWAYS_ON_MEMBERS)
                + ") with at least one dispatched, but the enumeration does not "
                "[review-coverage-dispatch-uncorroborated]. No PATCH was made."
            )
        _roster_incoherent = _review_roster_incoherence(
            dict(zip(_REVIEW_COVERAGE_AXES, review_coverage)), roster_members)
        if _roster_incoherent:
            raise _UpdateError(
                f"--record-review-coverage: {_roster_incoherent}. No PATCH was made."
            )
    review_dispositions = list(getattr(args, 'review_coverage_disposition', []) or [])
    _seen_gaps: set[str] = set()
    # #1984: `environment-denial` must be corroborated by a recorded `missing` roster
    # row (the denied member) — read the durable rows already in ## Progress and merge
    # this call's own rows, so a disposition recorded in a later call than the roster
    # enumeration still sees it. Guarded by `review_dispositions` so a note-only or
    # checkpoint update pays no extra section parse.
    _disp_has_missing = False
    if review_dispositions:
        _disp_roster = dict(
            _review_roster_members(_progress_content_or_none(body) or ''))
        _disp_roster.update(roster_members)
        _disp_has_missing = any(s == 'missing' for s in _disp_roster.values())
    for _triple in review_dispositions:
        # Arity is guaranteed by argparse's nargs=3 from the CLI, but a programmatic
        # caller (the suite builds `args` directly) can pass an element of any other
        # length — or a bare str, whose `gap, cause, reason` unpack would silently split
        # it into single characters. `_require_arity` rejects the non-sequence explicitly
        # and enforces the count, for the same reason `--record-review-coverage` uses
        # it above: the guarantee is local rather than inherited from a distant
        # declaration.
        _require_arity('--review-coverage-disposition', _triple, 3,
                       ('gap', 'cause-class', 'reason'))
    for gap, cause_class, reason in review_dispositions:
        if gap not in _REVIEW_COVERAGE_GAPS:
            raise _UpdateError(
                f"--review-coverage-disposition: unknown gap {gap!r}; expected one "
                f"of {', '.join(_REVIEW_COVERAGE_GAPS)}. No PATCH was made."
            )
        if gap in _seen_gaps:
            # A repeated gap would write two rows for one gap, and the reader keeps
            # only the last — so the reason a human sees would not be the reason the
            # gate judged. Reject the ambiguity rather than silently picking one.
            raise _UpdateError(
                f"--review-coverage-disposition: gap {gap!r} given more than once; "
                "pass one disposition per gap. No PATCH was made."
            )
        _seen_gaps.add(gap)
        # #1984: cause-class admissibility is defined once, in
        # `_review_coverage_disposition_cause_rejection`; do not restate it here.
        _cause_rej = _review_coverage_disposition_cause_rejection(
            cause_class, _disp_has_missing)
        if _cause_rej:
            raise _UpdateError(
                f"--review-coverage-disposition: gap {gap!r} {_cause_rej} "
                "[review-coverage-cause-inadmissible]. No PATCH was made."
            )
        if not _is_single_line(reason):
            # A line boundary would split the row and orphan its marker, the same
            # hazard `--checkpoint`'s single-line TEXT rule guards against.
            raise _UpdateError(
                f"--review-coverage-disposition: the reason for gap {gap!r} must be "
                "a single line (a line boundary would split the row and orphan its "
                "marker). No PATCH was made."
            )
        _rejection = _review_coverage_reason_rejection(reason)
        if _rejection:
            raise _UpdateError(
                f"--review-coverage-disposition: the reason for gap {gap!r} is "
                f"unacceptable: {_rejection} [review-coverage-boilerplate]. Name the "
                "specific gap and why it is being carried forward. No PATCH was made."
            )

    # Scope-decision records (issue #781). Validate + render them BEFORE any body
    # mutation, so a malformed PR value or an empty criterion text is a structural
    # failure that changes nothing — the same all-or-nothing contract
    # `--rewrite-ac` and `--checkpoint` hold. `--bind-scope-decisions` is a pure
    # rewrite over the whole body and is idempotent, so it needs no validation
    # beyond argparse's `type=int`.
    scope_decision_notes = _render_scope_decisions(args)
    bind_pr = getattr(args, 'bind_scope_decisions', None)
    if bind_pr is not None:
        body = _bind_scope_decisions(body, bind_pr)

    # Front-matter mutations.
    if args.status:
        clean = _strip_status_glyph(args.status)
        glyph = _status_glyph(clean)
        body, n = _STATUS_RE.subn(f'**Status:** {glyph} {clean}', body, count=1)
        if n == 0:
            raise _UpdateError('Status line not found in workpad')
    if args.branch:
        body, n = _BRANCH_RE.subn(
            lambda _m: f'**Branch:** `{args.branch}`', body, count=1,
        )
        if n == 0:
            raise _UpdateError('Branch line not found in workpad')
    if args.run_link:
        body = _set_or_insert_header(body, _RUN_RE, 'Run', args.run_link, [_BRANCH_RE])
    if args.pr_link:
        # Anchor PR after Run when Run exists (else Branch), so the canonical
        # Run-then-PR order holds whether one or both lines are being inserted.
        body = _set_or_insert_header(
            body, _PR_RE, 'PR', args.pr_link, [_RUN_RE, _BRANCH_RE],
        )

    # Always refresh Last updated.
    body, n = _LAST_UPDATED_RE.subn(f'**Last updated:** {last_updated}', body, count=1)
    if n == 0:
        raise _UpdateError('Last updated line not found in workpad')

    # Notes nest under their lifecycle phase inside ## Progress. Read the
    # post-mutation Status so a combined `--status X --note Y` call files the
    # note under X's phase (the status line was already rewritten above). Strip
    # the leading glyph so the phase lookup keys on the bare word ("Reviewing").
    _live_status = _status_word_from_body(body)
    current_phase = _live_status or None

    # Section-level mutations.
    preamble, sections = _split_sections(body)

    # ROW-SHAPE REPAIRS RUN BEFORE THE TICKS. Both reconcilers only insert or remove
    # ## Progress rows, and Phase 1.3 issues them in the SAME `update` call as a tick
    # — so running them after `_apply_section_ticks` would tick against the
    # un-repaired section, record a volatile miss, and then insert the very row the
    # tick wanted, leaving it unticked. `--reconcile-extension-rows` (issue #1462)
    # repairs the prompt-extension rows into a workpad created before they existed;
    # its `--reconcile-reproduction` sibling (issue #449) reconciles the bug-only row
    # to the recorded classification. Both are idempotent and run on every Phase 1.3
    # entry, and they share one section lookup because they run back to back.
    _reconcile_ext = getattr(args, 'reconcile_extension_rows', False)
    if args.reconcile_reproduction or _reconcile_ext:
        idx = _find_section(sections, 'Progress')
        if idx is None:
            raise _UpdateError("section '## Progress' not found")
        heading, content = sections[idx]
        if args.reconcile_reproduction:
            content = _reconcile_reproduction_row(content, args.reconcile_reproduction)
        if _reconcile_ext:
            content = _reconcile_extension_rows(content)
        sections[idx] = (heading, content)

    # WHOLE-SECTION REPLACEMENTS RUN BEFORE THE TICKS, for the reason the row-shape
    # repairs above do (issue #1389): `--tick-plan-n N` resolves its index against the
    # section body present when the tick runs, so a single call combining
    # `--replace-plan-file` with `--tick-plan-n` used to resolve every index against
    # the PRE-replace Plan — on a seed one-row Plan, each index above 1 recorded a
    # volatile miss ("index out of range") while the replace itself landed, so the
    # ticks were silently lost. Do not move these below `_apply_section_ticks`.
    if args.replace_plan_file:
        new_content = _read_section_file(args.replace_plan_file, '--replace-plan-file')
        sections = _set_section_content(sections, 'Plan', new_content)

    if args.replace_acs_file:
        new_content = _read_section_file(args.replace_acs_file, '--replace-acs-file')
        sections = _set_section_content(
            sections, 'Acceptance Criteria', new_content,
        )

    if args.set_reproduction_file:
        new_content = _read_section_file(
            args.set_reproduction_file, '--set-reproduction-file',
        )
        if _find_section(sections, 'Reproduction') is not None:
            sections = _set_section_content(sections, 'Reproduction', new_content)
        else:
            sections = _insert_section_after(
                sections, 'Acceptance Criteria', '## Reproduction', new_content,
            )

    # Progress has no index form (Progress checkboxes stay substring-addressed);
    # Plan/AC accept both the substring and `-n` index forms in one call.
    _apply_section_ticks(
        sections, 'Progress', 'progress', args.tick_progress, [], failed_ticks,
    )
    # Terminal-Complete backstop (issue #1337): a --status Complete write ticks
    # every still-unticked top-level ## Progress phase row, so a terminal 🎉 Complete
    # workpad never sits above an unticked **Implement** / **Review** parent that a
    # dropped or volatile-missed cooperative --tick-progress left behind. Only
    # Complete ticks — Failed/Cancelled/Blocked and the interim words change no
    # checkbox, keeping the record honest about where a non-complete run stopped.
    # Gate on the SAME derived glyph the terminal-complete self-record gate uses
    # (`_status_glyph(args.status) == '🎉'`, below) rather than an exact-word match,
    # so the two decisions cannot diverge: any status the gate treats as terminal
    # Complete also gets its parent rows ticked.
    if args.status and _status_glyph(args.status) == '🎉':
        _tick_top_level_progress_phases(sections)
    _apply_section_ticks(
        sections, 'Plan', 'plan', args.tick_plan, args.tick_plan_n, failed_ticks,
    )
    _apply_section_ticks(
        sections, 'Acceptance Criteria', 'ac', args.tick_ac, args.tick_ac_n,
        failed_ticks,
    )

    if args.rewrite_ac:
        idx = _find_section(sections, 'Acceptance Criteria')
        if idx is None:
            raise _UpdateError("section '## Acceptance Criteria' not found")
        # Rationale-required guard (issue #338): any pair that *appends* the
        # `(post-merge)` tag (NEW ends with it; neither OLD nor the row the pair
        # resolves to already does) is a mid-run retag —
        # the §3.4 channel used to defer a criterion's verification past merge — and
        # MUST carry a non-empty `--note` recording why the deferral qualifies
        # (genuinely-live), so a silently-laundered self-reconfiguration/tooling-gap
        # deferral becomes a recorded, retrospective-auditable claim rather than a
        # trust-me tag. Fail structurally (raise before any PATCH → all-or-nothing,
        # Status never flips) when no non-empty note accompanies such a pair. The
        # guard cannot judge the rationale's *truth* — it enforces that one exists,
        # and does so at *call* scope: any one non-empty `--note` in the same
        # `update` call satisfies it, whether or not that note is *about* the retag
        # (the note is appended to Progress, not bound to the rewritten row). The
        # retrospective auditor reads the recorded note; the guard only guarantees
        # there is one to read. Only `--note` satisfies it: a `--reflection` is a
        # different channel (## Devflow Reflection) and never stands in for the
        # rationale. The check runs per pair INSIDE the rewrite loop below, against
        # the row each pair actually resolves to, so a text tweak on an
        # already-`(post-merge)` row is exempt even when the OLD substring does not
        # itself span the tag.
        # Scope: this covers the `--rewrite-ac` retag channel only; the Phase 2.2.5
        # `--replace-acs-file` channel can introduce `(post-merge)` rows wholesale —
        # a deliberate, known limitation left open here, not closed by this guard.
        # Arity before the first positional read (issue #1501): the `p[1]` read in the
        # `offending_nl` generator below, and the `for old, new` loop later, both unpack
        # each pair. Guard every pair here — above both — so a short pair (an IndexError
        # on `p[1]`) or a long/non-sequence one raises a named refusal, not a bare
        # traceback. A bare string is rejected too (it would `p[1]`-index a character).
        for _pair in args.rewrite_ac:
            _require_arity('--rewrite-ac', _pair, 2, ('OLD', 'NEW'))
        has_note = any(n.strip() for n in args.note) or bool(getattr(args, 'note_file', None))
        # A multi-line NEW is structurally invalid, and rejecting it here is load-bearing
        # for BOTH guards below (issue #338). `_rewrite_checkbox` writes NEW verbatim into
        # one line, so an embedded line boundary SPLITS that checkbox row in two: it injects
        # an unreviewed AC row, and it breaks the row-index stability `_net_adds_post_merge`
        # compares against. It also slips the per-pair guard, whose `NEW ends with the
        # marker` test reads the whole string — `X (post-merge)<sep>- [ ] Y` ends with `Y`,
        # so the tag reads non-terminal while landing terminal on the split row. Combined
        # with a compensating tag-removal, that laundered a note-less deferral.
        # `_is_single_line` shares the row parser's own `str.splitlines()` contract, so the
        # rejected set matches the splitting set exactly — a `'\n'`/`'\r'` membership test
        # would accept `\v`, `\f`, `\x1c`-`\x1e`, NEL, LS and PS, every one of which still
        # splits the row. Reject unconditionally (a malformed argument, note or not), before
        # any PATCH, so the all-or-nothing contract holds.
        offending_nl = next((p for p in args.rewrite_ac if not _is_single_line(p[1])),
                            None)
        if offending_nl:
            raise _UpdateError(
                f"--rewrite-ac pair {offending_nl[0]!r} -> {offending_nl[1]!r} has a line "
                f"boundary in NEW; an AC row is a single line (it would split into an "
                f"extra, unreviewed row). No PATCH was made."
            )
        # --rewrite-ac is repeatable (issue #308): apply every OLD/NEW pair in
        # argument order against the progressively-rewritten section. Each pair
        # runs the existing exactly-one-match rule, so a pair matching zero or
        # multiple rows raises _UpdateError here — before any PATCH — preserving
        # the structural all-or-nothing contract for the whole call. Thread
        # `content` through a local and write `sections[idx]` once after the
        # loop, so a mid-loop raise leaves the section fully untouched.
        heading, content = sections[idx]
        # State-based backstop (issue #338 hardening): the per-pair guard consults
        # the resolved row's text, but still exempts any pair whose OLD argument
        # itself spans the tag, so a crafted MULTI-pair call whose pairs each
        # individually dodge `_pair_appends_post_merge` — e.g.
        # pair 1 places the marker non-terminally (`X` -> `(post-merge) X`, NEW
        # doesn't end in the tag), pair 2 makes it terminal (`(post-merge)` ->
        # `X (post-merge)`, OLD ends in the tag) — could net-add a post-merge row
        # with no note and slip past. Snapshot each AC row's post-merge-terminal
        # flag before the loop and compare POSITIONALLY after it: any row that went
        # untagged -> terminally-tagged is a laundered deferral regardless of how the
        # pairs were shaped, so abort here (still before any PATCH → all-or-nothing
        # holds). Row indices are stable because `_rewrite_checkbox` replaces a line
        # in place AND the `_is_single_line` rejection above keeps a NEW from splitting
        # a row. The flags span EVERY tick state (`_post_merge_flags`, not
        # `_unticked_rows`): an unticked-only population would miss the same shuttle
        # aimed at an already-`[x]` row, which still net-adds a tagged row. And the
        # comparison is positional, not an aggregate count, so a call that removes
        # the tag from one row while adding it to another — netting to zero — is
        # caught too. This is additive: it never fires on a call the per-pair guard
        # already caught, and it leaves the tag-preserving/tag-removing cases (no
        # False -> True transition) untouched. Scope: like the per-pair guard, this
        # covers the `--rewrite-ac` channel only — the Phase 2.2.5
        # `--replace-acs-file` channel remains a deliberate, documented exception.
        pre_pm = _post_merge_flags(content)
        for old, new in args.rewrite_ac:
            if not has_note:
                # Resolve the row this pair targets with the rewriter's own
                # resolution, then ask whether the pair terminally tags it.
                _row_text = _find_checkbox_row(
                    content, old, 'Acceptance Criteria',
                )[2].group(4)
                if _pair_appends_post_merge(old, new, _row_text):
                    raise _UpdateError(
                        f"--rewrite-ac pair {old!r} -> {new!r} appends the "
                        f"{_POST_MERGE_MARKER} tag but no non-empty --note "
                        f"rationale was supplied; a mid-run {_POST_MERGE_MARKER} "
                        f"retag must record why the deferral is genuinely-live "
                        f"(§3.4). No PATCH was made."
                    )
            content = _rewrite_checkbox(content, old, new, 'Acceptance Criteria')
        if not has_note and _net_adds_post_merge(pre_pm, _post_merge_flags(content)):
            raise _UpdateError(
                f"a --rewrite-ac in this call net-adds a {_POST_MERGE_MARKER} "
                f"criterion but no non-empty --note rationale was supplied; a "
                f"mid-run {_POST_MERGE_MARKER} retag must record why the deferral "
                f"is genuinely-live (§3.4). No PATCH was made."
            )
        sections[idx] = (heading, content)

    # Notes and checkpoint rows are both timestamped ## Progress bullets, so they
    # share one Progress lookup + append loop (a checkpoint row is just a note whose
    # text carries the hidden marker). `checkpoint_inserts` holds only absent keys
    # (replays were dropped during planning), nested under the current phase like any
    # note; args.note bullets append first, then the checkpoint rows.
    # Scope-decision records (issue #781) ride the note-append path: each is one
    # ordinary Progress bullet whose text is the delimited marker. They append
    # AFTER the free-text --note bullets so a 2.2.5/2.2.6 call reads
    # human-narrative-then-machine-record in the rendered workpad.
    # Filed markers (issue #815) ride the same note-append path for the same
    # reason the scope-decision records do, and each is one whole isolated
    # bullet — which is precisely what lets `_isolated_progress_markers` refuse
    # a marker embedded in free-text prose.
    mark_filed = list(getattr(args, 'mark_deferred_filed', None) or [])
    mark_filed.extend(_deferred_filed_file_values(args))
    if mark_filed:
        # Best-effort: a marker whose value matches no deferred record on the body
        # being written discharges nothing, and the writer would not learn that
        # until a duplicate follow-up appeared a phase later. The value must be a
        # `criterion:` line the predicate printed (already normalized); the note's
        # verbatim text is the natural slip. Breadcrumb only — never a mutation
        # failure, since the record set is PR-scoped and this writer is not.
        _filed_targets = {
            m.group(3) for m in _isolated_progress_markers(
                _progress_content_or_none(body) or '', _SCOPE_DECISION_RE)
            if m.group(2) == _SCOPE_DECISION_DEFERRED_KIND
        }
        _filed_texts = {t for t in (_unb64(b, 'scope-decision') for b in _filed_targets) if t}
        for _t in mark_filed:
            if _t not in _filed_texts:
                sys.stderr.write(
                    f"workpad.py: --mark-deferred-filed value {_t!r} matches no kind=deferred "
                    f"record on this workpad; the marker will discharge nothing — pass a "
                    f"`criterion:` line `deferred-presence` printed, verbatim\n"
                )
    deferred_filed_notes = [_render_deferred_filed(t) for t in mark_filed]
    # Same-invocation note/checkpoint de-dup (issue #1337): the Phase 1 cloud
    # hydration fence passes the selected lifecycle event twice in one call — as a
    # --checkpoint text and again as a --note — which rendered the event as two
    # ## Progress rows (a bare note bullet and the marker-carrying checkpoint row).
    # Suppress a --note only when its text will already be RECORDED by a checkpoint
    # row, so the marker-carrying row is the single record and no note is ever
    # dropped without its text appearing somewhere. A text is "covered" when it is
    # being inserted this call (an absent-key checkpoint in `checkpoint_inserts`) OR
    # a byte-equal row already exists in the body under a replayed key (`{text}
    # {marker}` present). This keeps the same-text replay case suppressing the
    # duplicate note (the row is already there) while a differing-text replay — whose
    # new text is recorded nowhere, because a replay keeps the row's existing text —
    # is NOT suppressed, so that text still renders rather than silently vanishing.
    # A --note that differs from every covered text (the local-tier call passes
    # --note with no checkpoint flags) is untouched.
    _checkpoint_covered_texts = {text for _key, text in checkpoint_inserts}
    for _ckey, _ctext in checkpoint_reqs:
        if f'{_ctext} {_checkpoint_marker(_ckey)}' in body:
            _checkpoint_covered_texts.add(_ctext)
    # A --note-file payload (issue #1813) is an ordinary note appended AFTER the
    # inline --note bullets, mirroring the --reflection/--reflection-file order.
    # The read is memoized (see `_note_file_payload`), so this reuses the text
    # `_cmd_update_inner` already read for buffering rather than re-reading it.
    _notes_in = list(args.note)
    if getattr(args, 'note_file', None):
        _notes_in.append(_note_file_payload(args))
    _notes = [n for n in _notes_in if n not in _checkpoint_covered_texts]
    # issue #1509: a review-coverage downgrade/override records its reason as an ordinary
    # ## Progress note alongside the (mutated) record row.
    progress_notes = _notes + review_coverage_auto_notes + scope_decision_notes + deferred_filed_notes + [
        f'{text} {_checkpoint_marker(key)}' for key, text in checkpoint_inserts
    ]
    # Completion-evidence marker (issue #1087): validated above; a later validated key
    # REPLACES the prior one (unlike a plain checkpoint replay), so any existing
    # completion-verification row is stripped before the new marker is appended.
    if record_flight_key:
        _ck = _COMPLETION_MARKER_KEY_PREFIX + record_flight_key
        progress_notes.append(
            f'completion verification recorded (flight {record_flight_key[:12]}…, '
            f'validated) {_checkpoint_marker(_ck)}'
        )
    # CI-derived completion-evidence marker (issue #1611): validated above; a later
    # validated record REPLACES the prior one, so any existing completion-ci row is
    # stripped before this marker is appended (mirroring the flight family). The
    # visible row names the head SHA and conclusion the reading rests on.
    if ci_payload:
        _ci_ck = _COMPLETION_CI_MARKER_KEY_PREFIX + ci_payload
        progress_notes.append(
            f'completion evidence recorded from CI reading '
            f'(head {record_ci[0][:12]}…, {record_ci[2]}, validated) '
            f'{_checkpoint_marker(_ci_ck)}'
        )
    # Mid-phase resume-point marker (issue #1876): a later record REPLACES the prior
    # one, so any existing resume-point row is stripped below before this is appended.
    if resume_point_payload:
        _rp_ck = _RESUME_POINT_MARKER_KEY_PREFIX + resume_point_payload
        progress_notes.append(
            f'mid-phase resume point recorded {_checkpoint_marker(_rp_ck)}'
        )
    # Review-coverage record + dispositions (issue #1453): validated above; the prior
    # rows were stripped just before the append loop, mirroring the completion-evidence
    # marker's replace-rather-than-accumulate semantics.
    _review_coverage_rows: set[str] = set()
    if review_coverage_payload:
        _state = _render_review_coverage_state(
            dict(zip(_REVIEW_COVERAGE_AXES, review_coverage)))
        # issue #1510: surface the as-of anchor in the visible row (from the locals
        # composed above — no re-parse) so a human reader can tell a record that predates
        # a later standalone review from a current one.
        _head_disp = (_anchor_head if _anchor_head == _REVIEW_COVERAGE_ANCHOR_UNESTABLISHED
                      else _anchor_head[:12])
        _review_coverage_rows.add(
            f'review coverage recorded ({_state}; as of head {_head_disp} '
            f'at {_anchor_asof}) '
            f'{_review_coverage_marker(review_coverage_payload)}'
        )
    for _member, _status in roster_members.items():
        _review_coverage_rows.add(
            f'{_render_review_roster_member(_member, _status)} '
            f'{_review_roster_marker(_member, _status)}'
        )
    for _gap, _cause, _reason in review_dispositions:
        _review_coverage_rows.add(
            f'{_render_review_coverage_disposition(_gap, _reason)} '
            f'{_review_coverage_disposition_marker(_gap, _cause)}'
        )
    progress_notes.extend(sorted(_review_coverage_rows))
    # Inherited required-artifact strip (issue #1347). Runs on BOTH resume arms —
    # it rides its own flag rather than the cloud-only `--checkpoint`/`--expect-*`
    # set the local arm drops — and BEFORE the note append below, so a row this
    # call writes is never stripped by the same call. An absent `## Progress` is a
    # no-op: there is nothing to strip, and the strip alone never fails the call.
    if strip_inherited:
        idx = _find_section(sections, 'Progress')
        if idx is not None:
            heading, content = sections[idx]
            # The review-coverage record (issue #1453) is stripped by the same flag
            # and for the same reason: it describes THIS attempt's review pass, so a
            # resumed run must re-establish it rather than inherit an earlier
            # attempt's answer. Its key carries a run-varying payload, so it cannot
            # join the literal `_REQUIRED_ARTIFACT_CHECKPOINT_KEYS` derivation; the
            # non-transcription guarantee comes instead from one regex pair powering
            # the reader, the producer and this strip.
            sections[idx] = (
                heading,
                _strip_review_coverage_marker_rows(
                    _strip_required_artifact_checkpoint_rows(content)),
            )
        # Writer and reader disagree on scope, so never let a survivor pass in
        # silence. This strip rewrites the FIRST `## Progress` section, while the
        # consumer it exists to correct (`lib/fetch-pr-context.sh`'s
        # `base_update_checkpoint4_present`) matches over the WHOLE body — so a
        # declared marker living in a duplicate section, in the preamble, or under a
        # heading `_find_section` does not recognise survives, and the resumed run
        # would then be credited with a reconciliation an earlier attempt performed.
        # Breadcrumb rather than raise: the caller is Phase 1.3's hydration write, and
        # a non-canonical workpad must not be able to wedge a resume at setup.
        # The review-coverage family (issue #1453) is scanned by its own regexes
        # rather than by a variant literal, because its keys carry a run-varying
        # payload; the justification is the same — the strip rewrites the FIRST
        # `## Progress` section, so a record surviving elsewhere must not pass in
        # silence.
        _joined = _join_sections(preamble, sections)
        _rc_survivors = (
            ['review-coverage record']
            if _REVIEW_COVERAGE_MARKER_RE.search(_joined) else []
        ) + (
            ['review-coverage disposition']
            if _REVIEW_COVERAGE_DISPOSITION_MARKER_RE.search(_joined) else []
        ) + (
            ['review-roster enumeration']
            if _REVIEW_ROSTER_MARKER_RE.search(_joined) else []
        )
        _survivors = _rc_survivors + sorted(
            v for v in _REQUIRED_ARTIFACT_MARKER_VARIANTS
            if v in _join_sections(preamble, sections)
        )
        if _survivors:
            sys.stderr.write(
                "workpad.py update: WARNING: --strip-inherited-checkpoints left "
                f"declared marker(s) {', '.join(_survivors)} in the body, outside "
                "the '## Progress' section it rewrites (a duplicate, absent, or "
                "unrecognised section heading). The inherited record was NOT fully "
                "cleared; repair the workpad's section shape.\n"
            )

    if progress_notes:
        idx = _find_section(sections, 'Progress')
        if idx is None:
            raise _UpdateError("section '## Progress' not found")
        heading, content = sections[idx]
        if record_flight_key:
            content = _strip_completion_marker_rows(content)
        if ci_payload:
            content = _strip_completion_ci_marker_rows(content)
        if resume_point_payload:
            content = _strip_resume_point_marker_rows(content)
        if review_coverage_payload:
            # A fresh record REPLACES the prior one (and its now-stale dispositions),
            # so the reader's "exactly one record" contract holds across a re-recorded
            # Phase 3.3 exit.
            content = _strip_review_coverage_marker_rows(content)
        elif review_dispositions:
            content = _strip_review_coverage_disposition_rows(
                content, [g for g, _c, _r in review_dispositions])
        phase_label = _progress_phase_for_status(content, current_phase)
        for text in progress_notes:
            # `_review_coverage_rows` holds exactly the rows the validated producer
            # above composed, so the chokepoint guard admits those and refuses a
            # marker arriving through any caller-supplied text.
            content = _append_progress_note(
                content, text, now_time, phase_label,
                reserved_marker_ok=text in _review_coverage_rows)
        sections[idx] = (heading, content)

    if args.reflection or args.reflection_file:
        idx = _find_section(sections, 'Devflow Reflection')
        if idx is None:
            raise _UpdateError("section '## Devflow Reflection' not found")
        heading, content = sections[idx]
        # Direct attribute access (not getattr-with-default), matching the sibling
        # args.note / args.reflection reads above: argparse always supplies
        # reflection_kind (default=None), so a missing attribute is a wiring
        # regression that should fail loud rather than silently file every bullet
        # as a `note`. The `or _DEFAULT_REFLECTION_KIND` handles only the
        # legitimate flag-omitted None case.
        kind = args.reflection_kind or _DEFAULT_REFLECTION_KIND
        for bullet in args.reflection:
            content = _append_reflection(content, kind, bullet)
        # The --reflection-file bullet appends AFTER the inline --reflection
        # bullets, under the same kind. Its reader raises _UpdateError (unreadable
        # path, undecodable payload, empty/whitespace-only) before the PATCH, so a
        # bad payload aborts the whole call with no partial write. The read goes
        # through the memo so `cmd_update`'s failed-write buffering sees the same
        # text without re-reading (and without re-consuming stdin on the `-` arm).
        if args.reflection_file:
            content = _append_reflection(
                content, kind, _reflection_file_payload(args))
        sections[idx] = (heading, content)

    # Every accepted review-coverage disposition also files its own `dropped-failed`
    # reflection bullet (issue #1453). Synthesized HERE rather than left to a paired
    # `--reflection-kind dropped-failed --reflection …` the caller must remember: the
    # routing this satisfies — `lib/cheap-gate.jq` counts every kind except `note` as
    # friction — must not be defeatable by a caller omission, so a disposition can
    # never be recorded without its friction bullet. The kind is fixed, so a call's
    # own `--reflection-kind` never applies to these bullets. A write that supersedes
    # the prior dispositions strips their bullets first, so a gap that no longer
    # exists stops asserting itself in `### ⚠️ Action required`.
    if review_coverage_payload or review_dispositions or strip_inherited:
        idx = _find_section(sections, 'Devflow Reflection')
        if idx is None:
            if review_dispositions:
                raise _UpdateError(
                    "--review-coverage-disposition: section '## Devflow Reflection' "
                    "not found, so the disposition's friction reflection cannot be "
                    "recorded; refusing to record a disposition that would not route "
                    "to the retrospective. No PATCH was made."
                )
        else:
            heading, content = sections[idx]
            if review_coverage_payload or strip_inherited:
                content = _strip_review_coverage_reflection_bullets(content)
            else:
                # A dispositions-only write replaces only the bullets for the gaps it
                # re-states, mirroring its row-level strip.
                _restated = {
                    f'{_REVIEW_COVERAGE_REFLECTION_PREFIX}{g}:'
                    for g, _c, _r in review_dispositions
                }
                content = ''.join(
                    ln for ln in content.splitlines(keepends=True)
                    if not any(p in ln for p in _restated))
            for _gap, _cause, _reason in review_dispositions:
                content = _append_reflection(
                    content, 'dropped-failed',
                    f'{_REVIEW_COVERAGE_REFLECTION_PREFIX}{_gap}: {_reason}')
            sections[idx] = (heading, content)

    # Record the reproduce-first content classification (issue #449) as a
    # superseding `classification: ` Progress note — exactly one at all times.
    if args.record_classification:
        _require_arity(  # issue #1501
            '--record-classification', args.record_classification, 2,
            ('class', 'rationale'))
        cls, rationale = args.record_classification
        if cls not in _CLASSIFICATION_VALUES:
            raise _UpdateError(
                f"--record-classification: unknown class {cls!r}; expected one of "
                f"{', '.join(_CLASSIFICATION_VALUES)}"
            )
        # Empty-check the STRIPPED value (a whitespace-only rationale is empty), but
        # single-line-check the RAW value so a trailing newline is still rejected
        # rather than silently trimmed into acceptance.
        stripped_rationale = rationale.strip()
        if not stripped_rationale:
            raise _UpdateError(
                "--record-classification: a non-empty rationale is required (the "
                "note form is 'classification: <class> — <rationale>')"
            )
        if not _is_single_line(rationale):
            # A line boundary would split the note bullet (same hazard --rewrite-ac
            # guards against); reject before any PATCH so all-or-nothing holds.
            raise _UpdateError(
                "--record-classification: rationale must be a single line (a line "
                "boundary would split the note bullet). No PATCH was made."
            )
        idx = _find_section(sections, 'Progress')
        if idx is None:
            raise _UpdateError("section '## Progress' not found")
        heading, content = sections[idx]
        content = _remove_classification_notes(content)
        note_text = f'{_CLASSIFICATION_NOTE_PREFIX}{cls} — {stripped_rationale}'
        phase_label = _progress_phase_for_status(content, current_phase)
        content = _append_progress_note(content, note_text, now_time, phase_label)
        sections[idx] = (heading, content)

    # Reconcile the bug-only reproduction Progress row to the classification
    # (issue #449) — idempotent, runs on every Phase 1.3 entry.
    # Terminal self-record gate (issue #258): a `--status Complete` write is the
    # deterministic chokepoint that guarantees the workpad's Plan/AC self-record
    # matches reality. It runs LAST, over the *post-mutation* sections, so a call
    # that ticks the final AC row and flips to Complete in one shot still passes.
    # Detection reuses `_status_glyph` (the single source of truth for the
    # Complete/🎉 vocabulary), so a non-Complete status (Blocked/👎, any in-progress
    # 🚀) and a status-less update are never gated.
    if args.status and _status_glyph(args.status) == '🎉':
        unticked_plan = _terminal_complete_gate(sections, args)  # AC/evidence hard-fail raises here
        if unticked_plan:
            rows = '; '.join(t.strip() for t in unticked_plan)
            sys.stderr.write(
                "workpad.py update: warning: finalizing Status: Complete with "
                f"{len(unticked_plan)} unticked ## Plan row(s) — a genuinely "
                "dropped/superseded step may honestly stay unticked, but verify: "
                f"{rows}\n"
            )

    # Announce a `## Progress` repair LAST — after every raising mutation in this
    # function, not merely after `_plan_checkpoints`. The repair runs early by
    # design (the section-shape validation must see the repaired body), but several
    # later guards abort the whole call with zero PATCH — the unconditional
    # `Last updated` check, the `--status`/`--branch` header raises, the
    # `--rewrite-ac` guards, `_validate_flight_key`. Announcing before those would
    # claim a self-heal the call then discards, which is the very defect this
    # breadcrumb's placement exists to avoid. Emitting here makes the invariant
    # unconditional: the breadcrumb appears only for a repaired body that survived
    # every structural check and is being returned for the PATCH.
    if _did_repair:
        _announce_progress_repair()
    return _join_sections(preamble, sections)


def main():
    _force_utf8_streams()
    p = argparse.ArgumentParser(prog='workpad.py')
    sub = p.add_subparsers(dest='cmd', required=True)

    # Shared marker-override help. Passing the marker as a regular argument
    # (rather than via the DEVFLOW_WORKPAD_MARKER env var, which forced a
    # leading env-assignment onto the command) keeps the helper path as the
    # command prefix so the cloud allow-list rule `Bash(.../workpad.py:*)`
    # still matches — /devflow:review relies on this for its
    # `<!-- prflow:review-progress -->` comment.
    _marker_help = (
        'Marker comment that tags this workpad. Overrides the '
        'DEVFLOW_WORKPAD_MARKER env var and the .prflow/config.json value; '
        "defaults to '<!-- prflow:workpad -->'."
    )

    s = sub.add_parser('id', help='Print workpad comment ID for an issue (exit 2 if absent; exit 1 on API/parse error).')
    s.add_argument('issue', type=int)
    s.add_argument('--marker', default=None, help=_marker_help)
    s.set_defaults(func=cmd_id)

    s = sub.add_parser('body', help='Print a workpad body — by comment id '
                       '(positional), or by issue number with --issue (exit 2 '
                       'if absent, exit 3 on read failure).')
    # Positional is optional so `--issue` can address by issue number instead;
    # cmd_body rejects the both/neither/malformed-value combinations with exit 1
    # BEFORE any network call, so argparse's usage-error exit 2 never collides
    # with the absent-workpad exit 2 (issue #2040). --issue is an untyped string
    # (validated as a decimal in cmd_body), never type=int, for the same reason.
    s.add_argument('comment_id', type=int, nargs='?', default=None)
    s.add_argument('--issue', default=None,
                   help='Address the workpad by ISSUE number instead of a comment '
                        'id (resolves via the same marker scan as `id`/`status`).')
    s.add_argument('--marker', default=None, help=_marker_help)
    s.set_defaults(func=cmd_body)

    s = sub.add_parser(
        'status',
        help='Print the workpad Status as `CLASS GLYPH WORD` (CLASS is one of '
             'complete|blocked|failed|cancelled|interim). Exit 2 if no workpad, '
             'exit 1 if present but the Status is unreadable.',
    )
    s.add_argument('issue', type=int)
    s.add_argument('--marker', default=None, help=_marker_help)
    s.set_defaults(func=cmd_status)

    # No `--marker` on either acs subcommand — deliberately. The review engine
    # drives its own `<!-- prflow:review-progress -->` comment through this same
    # helper, and the acceptance criteria live only on the IMPLEMENT workpad, so
    # omitting the flag denies a CALLER any way to point this read at the wrong
    # comment. The env/config precedence in `_workpad_marker` still applies (see
    # `_acs_read_workpad`'s docstring) — it moves the workpad and this read
    # together, so it is not a desync channel.
    s = sub.add_parser(
        'acs',
        help="Print the workpad's ## Acceptance Criteria section unfiltered "
             '(every criterion carried through, tick state and (post-merge) '
             'tags preserved; the parsed items are re-rendered, so blank lines '
             'are dropped and "* [ ]" normalizes to "- [ ]"). Exit 2 with empty '
             'stdout AND empty stderr when no workpad exists; exit 3 on a gh '
             'read failure or when scripts/section_parse.py was not deployed '
             'beside workpad.py.',
    )
    s.add_argument('issue', type=int)
    s.add_argument('--exclude-post-merge', action='store_true',
                   help='Drop every criterion already tagged " (post-merge)". '
                        'Phase 0.4 passes this for the reviewer-facing value; '
                        'the unfiltered form is the divergence comparand.')
    s.add_argument('--neutralize-boxes', action='store_true',
                   help='Render every criterion unticked. A tick is the code '
                        "author's own assertion that the criterion is "
                        'satisfied, so the merge-gating judge is never handed a '
                        'specification pre-annotated by the party it judges.')
    s.add_argument('--emit-source-token', action='store_true',
                   help='Prefix stdout with one token line naming the workpad '
                        "section's state (workpad | workpad-unmirrored | "
                        'issue-body), so the un-mirrored placeholder is '
                        'distinguishable from a legitimately empty section.')
    s.set_defaults(func=cmd_acs)

    s = sub.add_parser(
        'acs-gate',
        help="Read the workpad's ## Acceptance Criteria for the /prflow:implement "
             'Phase 3.4 gate WITH a defined degradation (issue #1214). Line 1 of '
             'stdout is always "source: <token>". Exit/token pairs: 0 source: '
             'workpad (clean read); 2 source: workpad-absent (clean absence, the '
             'existing benign shape); 3 source: workpad-read-failed (workpad read '
             'failed, criteria recovered from the issue body via parse-acs.py — the '
             'gate must NOT pass); 4 source: unestablished (workpad read failed AND '
             'the issue-body fallback also failed — the gate must NOT pass).',
    )
    s.add_argument('issue', type=int)
    s.set_defaults(func=cmd_acs_gate)

    s = sub.add_parser(
        'acs-resolve',
        help='Resolve the reviewer-facing acceptance criteria from the workpad '
             'and the issue body, name the source, and report normalized '
             'divergence. Used by the review engine Phase 0.4.',
    )
    # NOT type=int (issue #857): the numeric guard is applied INSIDE cmd_acs_resolve
    # so a non-numeric argument is a routed `resolver-unavailable` outcome with exit 0,
    # not an argparse exit 2. This lets the §0.4 fence be a bare single-statement call.
    s.add_argument('issue', type=str)
    s.add_argument('--pr', type=int, default=None,
                   help='The PR under review. Scope-decision records must carry '
                        'this number to count; a record left at pr=pending, or '
                        'naming another PR, covers nothing. Omit it in '
                        'current-branch mode, where there is no PR to bind to: '
                        'no record can then be confirmed as this run\'s, so a '
                        'narrowed workpad fails closed to pr-identity-mismatch '
                        'exactly as it does for an unbound record.')
    s.set_defaults(func=cmd_acs_resolve)

    s = sub.add_parser(
        'deferred-presence',
        help='Bounded three-state check for unfiled deferred criteria bound to '
             "this run's PR. Exits 0 outstanding / 1 not-outstanding / 2 "
             'unestablished (grep-style), prints one count line and, on exit 0, '
             'one criterion: line per outstanding record. Never prints the body. '
             'Phase 4 gates the deferred-AC reference load on it.',
    )
    s.add_argument('issue', type=int)
    s.add_argument('pr', type=int,
                   help="This run's PR number, as a decimal literal. A record "
                        'bound to any other number — or still reading pending — '
                        'answers unestablished rather than a confident zero.')
    s.add_argument('--marker', default=None, help=_marker_help)
    s.set_defaults(func=cmd_deferred_presence)

    s = sub.add_parser(
        'resume-point',
        help="Print this run's recorded mid-phase re-anchor resume point (issue "
             '#1876). Exits 0 with the resume point on stdout / 1 when none is '
             'recorded (grep-style) / 2 unestablished (no workpad, or no single '
             '## Progress section). A navigation aid read by no verdict/gate; never '
             'prints the body.',
    )
    s.add_argument('issue', type=int)
    s.add_argument('--marker', default=None, help=_marker_help)
    s.set_defaults(func=cmd_resume_point)

    s = sub.add_parser(
        'deferred-reflection-audit',
        help="Bounded check that every deferred-kind reflection this run recorded "
             "is backed by a scope-decision-deferred record bound to this run's PR "
             '(issue #1513). Exits 0 backed / 1 unbacked / 2 unestablished '
             '(grep-style), prints one count line and, on exit 1, one text: line '
             'per deferred reflection. Never prints the body. Phase 4.0.6 surfaces '
             'an unbacked reflection.',
    )
    s.add_argument('issue', type=int)
    s.add_argument('pr', type=int,
                   help="This run's PR number, as a decimal literal. A deferred "
                        'reflection with no scope-decision record bound to this PR '
                        'is unbacked.')
    s.add_argument('--marker', default=None, help=_marker_help)
    s.set_defaults(func=cmd_deferred_reflection_audit)

    s = sub.add_parser('patch', help='PATCH a workpad comment from a body file; prints new body.')
    s.add_argument('comment_id', type=int)
    s.add_argument('body_file')
    s.set_defaults(func=cmd_patch)

    s = sub.add_parser('create', help='Create the workpad comment for an issue; prints new ID.')
    s.add_argument('issue', type=int)
    s.add_argument('body_file')
    s.set_defaults(func=cmd_create)

    s = sub.add_parser('now', help='UTC ISO-8601 timestamp.')
    s.set_defaults(func=cmd_now)

    s = sub.add_parser(
        'new-body',
        help='Print the lean initial workpad skeleton to stdout (pipe to a '
             'file, then `create`).',
    )
    s.add_argument('issue', type=int)
    s.add_argument('--run-link', metavar='VALUE', default=None,
                   help='Run front-matter value (markdown ok). Defaults to a '
                        '"_(local run)_" placeholder when omitted.')
    s.add_argument('--branch', metavar='VALUE', default=None,
                   help='Branch name. Defaults to a "_(creating…)_" placeholder.')
    s.add_argument('--no-reproduction', action='store_true',
                   help='Omit the bug-only "reproduction captured" sub-item. '
                        'Pass when the recorded content classification is '
                        'non-bug; the line renders by default so a deterministic '
                        'label-based pre-render never drops it, and Phase 1.3 '
                        'reconciles it to the classification (issue #449).')
    s.add_argument('--marker', default=None, help=_marker_help)
    s.set_defaults(func=cmd_new_body)

    u = sub.add_parser(
        'update',
        help='Apply mutations to the workpad and PATCH. Re-fetches the body '
             'internally; Last updated is refreshed automatically. Structural '
             'failures abort with no PATCH; a per-row tick miss is reported and '
             'exits non-zero but still PATCHes the call\'s other mutations.',
    )
    u.add_argument('issue', type=int)
    u.add_argument('--status', help='Replace the Status line value. A canonical '
                   'glyph (🚀 running / 🎉 Complete / 👎 Blocked / 💥 Failed / '
                   '🛑 Cancelled) is derived from the status word and prepended '
                   'automatically.')
    u.add_argument('--branch', help='Replace the Branch line value.')
    u.add_argument('--run-link', metavar='VALUE',
                   help='Set the Run front-matter line to VALUE (markdown ok). '
                        'Inserted after Branch if the line is absent.')
    u.add_argument('--pr-link', metavar='VALUE',
                   help='Set the PR front-matter line to VALUE (markdown ok). '
                        'Inserted after Branch if the line is absent.')
    u.add_argument('--tick-progress', metavar='TEXT', action='append', default=[],
                   help='Tick one ## Progress checkbox matching TEXT (substring). '
                        'Repeatable. A zero/multiple-match miss is a volatile '
                        'failure: the call PATCHes its other mutations and exits '
                        'non-zero naming the miss (no index form for Progress).')
    u.add_argument('--tick-plan', metavar='TEXT', action='append', default=[],
                   help='Tick one Plan checkbox matching TEXT (substring). '
                        'Repeatable. A zero/multiple-match miss is volatile (see '
                        '--tick-progress).')
    u.add_argument('--tick-plan-n', metavar='N', type=int, action='append',
                   default=[],
                   help='Tick the Nth Plan checkbox (1-based, counting every '
                        '[ ] and [x] row within the ## Plan section, in document '
                        'order; section-scoped, not whole-document). Repeatable; '
                        'combinable with --tick-plan and every other flag. An '
                        'out-of-range or already-ticked N is a volatile failure '
                        '(reported, non-zero exit, other mutations applied).')
    u.add_argument('--tick-ac', metavar='TEXT', action='append', default=[],
                   help='Tick one Acceptance Criteria checkbox matching TEXT '
                        '(substring). Repeatable. A zero/multiple-match miss is '
                        'volatile (see --tick-progress).')
    u.add_argument('--tick-ac-n', metavar='N', type=int, action='append',
                   default=[],
                   help='Tick the Nth Acceptance Criteria checkbox (1-based, '
                        'counting every [ ] and [x] row within the ## Acceptance '
                        'Criteria section, in document order; section-scoped, not '
                        'whole-document). '
                        'Repeatable; combinable with --tick-ac and every other '
                        'flag. An out-of-range or already-ticked N is a volatile '
                        'failure (reported, non-zero exit, other mutations '
                        'applied).')
    u.add_argument('--rewrite-ac', nargs=2, metavar=('OLD', 'NEW'),
                   action='append', default=[],
                   help='Find one AC matching OLD; replace its text with NEW. '
                        'Preserves the checkbox state. For Phase 2.2.6. '
                        'Repeatable: multiple pairs apply in argument order, each '
                        'validated by the exactly-one-match rule; any pair '
                        'matching zero or multiple rows aborts the whole call '
                        'with no PATCH (structural all-or-nothing). NEW must be a '
                        'single line: a line boundary would split the criterion '
                        'into an extra, unreviewed row, so it aborts the call. '
                        'A pair that '
                        'appends the (post-merge) tag (NEW ends with it; neither '
                        'OLD nor the row it targets already does) is a mid-run '
                        'retag and requires a non-empty --note rationale (issue '
                        '#338); without one the call aborts structurally before '
                        'any PATCH. A pair targeting a row that already ends '
                        'with the tag, or that removes it, needs no note. Only '
                        '--note satisfies the rationale; a --reflection does not.')
    u.add_argument('--scope-decision-deferred', nargs=2, metavar=('PR', 'TEXT'),
                   action='append', default=[],
                   help='Record that criterion TEXT was deferred out of the '
                        'workpad Acceptance Criteria set by PR. PR is a number, '
                        "or the literal 'pending' when the draft PR does not "
                        'exist yet (Phase 2.2.5) — Phase 3.1 then binds it with '
                        '--bind-scope-decisions. Repeatable. Written as a '
                        'delimited ## Progress record the review engine reads; '
                        'the free-text --note is never read as the source of '
                        'truth.')
    u.add_argument('--scope-decision-rewritten', nargs=3,
                   metavar=('PR', 'OLD', 'NEW'), action='append', default=[],
                   help='Record that criterion OLD was rewritten to NEW by PR '
                        '(Phase 2.2.6, and Phase 3.4\'s retroactive '
                        '(post-merge) retag). Same PR/pending semantics as '
                        '--scope-decision-deferred. Repeatable.')
    u.add_argument('--bind-scope-decisions', metavar='PR', type=int, default=None,
                   help='Rewrite every scope-decision record still reading '
                        'pr=pending to this PR number. Phase 3.1 runs it right '
                        'after gh pr create, which is the first moment the '
                        'number exists. Idempotent: a record already carrying a '
                        'number is left untouched.')
    u.add_argument('--mark-deferred-filed', metavar='NORMALIZED_TEXT',
                   action='append', default=[],
                   help='Record that a follow-up issue was filed for the '
                        'kind=deferred criterion whose NORMALIZED_TEXT is a '
                        'criterion: line `deferred-presence` printed — pass it '
                        'verbatim, never re-typed. Writes its own '
                        '<!-- prflow:deferred-filed ... --> Progress bullet, a '
                        'grammar distinct from prflow:scope-decision, so '
                        'acs-resolve still reports the criterion DEFERRED. A '
                        'matching record then reads not-outstanding, which is '
                        'what stops a second Phase 4 entry re-filing it. '
                        'Repeatable — one per filed criterion.')
    u.add_argument('--mark-deferred-filed-file', metavar='PATH', default=None,
                   help='The interpolation-free arm of --mark-deferred-filed: '
                        'read one NORMALIZED_TEXT per line from PATH (or stdin '
                        'when PATH is -), bypassing the shell. Use it whenever a '
                        'criterion text carries a backtick, an apostrophe or a '
                        '$ — neither quoting style is safe for those inline, so '
                        'the markers would go unwritten and a later Phase 4 '
                        'entry would re-file the same follow-up. Blank lines are '
                        'ignored; combines with inline --mark-deferred-filed.')
    u.add_argument('--note', metavar='TEXT', action='append', default=[],
                   help='Append a note bullet, prefixed with a time-only '
                        'HH:MM:SS UTC timestamp and nested under the current '
                        'Status\'s phase inside ## Progress. May be passed '
                        'multiple times to append several entries (sharing one '
                        'timestamp) in one atomic update.')
    u.add_argument('--note-file', metavar='PATH', default=None,
                   help='Append a ## Progress note bullet whose text is read '
                        'verbatim as UTF-8 from PATH (or from stdin when PATH is '
                        '"-"), bypassing shell interpolation — use for text '
                        'containing backticks, $, or double quotes. Compose the '
                        'payload file with an editor/Write tool, never a shell '
                        'heredoc or redirect, or the interpolation hazard just '
                        'moves upstream. Combines with --note; the file bullet '
                        'appends after any inline --note bullets. An unreadable '
                        'path, an undecodable (non-UTF-8) payload, or an empty/'
                        'whitespace-only payload aborts the call before any PATCH.')
    u.add_argument('--reflection', metavar='TEXT', action='append', default=[],
                   help='Append a bullet to Devflow Reflection (no timestamp). '
                        'May be passed multiple times to append several bullets '
                        'in one atomic update.')
    u.add_argument('--reflection-file', metavar='PATH', default=None,
                   help='Append a Devflow Reflection bullet whose text is read '
                        'verbatim as UTF-8 from PATH (or from stdin when PATH is '
                        '"-"), bypassing shell interpolation — use for text '
                        'containing backticks, $, or double quotes. The call\'s '
                        '--reflection-kind applies; the file bullet appends after '
                        'any --reflection bullets. An unreadable path, an '
                        'undecodable (non-UTF-8) payload, or an empty/'
                        'whitespace-only payload aborts the call before any PATCH.')
    u.add_argument('--reflection-kind',
                   # Derive choices from the taxonomy dict so the CLI-validated
                   # set and the `_REFLECTION_KINDS[kind]` lookup can never drift
                   # (a kind added to one but not the other would KeyError). The
                   # accepted set and its order are exactly `_REFLECTION_KINDS`'s
                   # keys in insertion order — see that dict for the authoritative
                   # list (not re-enumerated here, which would rot on the next edit).
                   choices=list(_REFLECTION_KINDS),
                   default=None,
                   help="Kind for this update's --reflection / --reflection-file "
                        'bullet(s). blocked/deferred/dropped-failed render '
                        '(labeled) under "### ⚠️ Action required"; improvement '
                        '(glyph-only) under "### 💡 Improvements"; issue-accuracy '
                        '(labeled) and note (the default when omitted, glyph-only) '
                        'under "### ℹ️ Notes". Applies to every bullet in the '
                        'call.')
    u.add_argument('--replace-plan-file', metavar='FILE',
                   help='Replace the Plan section content with FILE contents.')
    u.add_argument('--replace-acs-file', metavar='FILE',
                   help='Replace Acceptance Criteria content with FILE contents. '
                        'For Phase 2.2.5 scope adjustment.')
    u.add_argument('--set-reproduction-file', metavar='FILE',
                   help='Set the Reproduction section to FILE contents. Inserts '
                        'the section after Acceptance Criteria if missing.')
    u.add_argument('--record-classification', nargs=2,
                   metavar=('CLASS', 'RATIONALE'),
                   help='Record the Phase 2.1.5 reproduce-first content '
                        'classification (issue #449) as a superseding '
                        '"classification: <CLASS> — <RATIONALE>" ## Progress note. '
                        'CLASS is bug-report or non-bug; RATIONALE is a non-empty '
                        'single line. Replaces any existing classification note, so '
                        'the workpad carries exactly one at all times.')
    u.add_argument('--reconcile-reproduction', choices=_CLASSIFICATION_VALUES,
                   help='Idempotently reconcile the bug-only "reproduction '
                        'captured" ## Progress row to the classification: '
                        'bug-report adds it when absent, non-bug removes it when '
                        'present and unticked (a ticked row is preserved), and it '
                        'no-ops when the skeleton already matches. Run on every '
                        'Phase 1.3 entry.')
    u.add_argument('--reconcile-extension-rows', action='store_true',
                   help='Idempotently repair the prompt-extension ## Progress '
                        'rows (issue #1462) into a workpad created before they '
                        'existed: a row missing in every tick state is inserted '
                        'under its phase, a present one is left alone. Run on '
                        'every Phase 1.3 entry.')
    u.add_argument('--checkpoint', nargs=2, metavar=('KEY', 'TEXT'),
                   action='append', default=[],
                   help='Write one timestamped ## Progress row carrying a hidden '
                        '"<!-- prflow:checkpoint KEY -->" marker (issue #537). '
                        'Idempotent: a second call with the same KEY is a replay '
                        'that adds no duplicate row. A checkpoint-only replay whose '
                        'keys all exist makes no Last-updated refresh and no PATCH; '
                        'combined with another mutation it applies that mutation '
                        'once and does not duplicate the checkpoint. KEY must match '
                        '[A-Za-z0-9._:-]+ . May be passed multiple times.')
    u.add_argument('--strip-inherited-checkpoints', action='store_true',
                   help='Remove every declared required-artifact checkpoint row '
                        'from ## Progress (issue #1347), so a resumed run does not '
                        'inherit the previous attempt\'s record. Declared keys: '
                        + ', '.join(_REQUIRED_ARTIFACT_CHECKPOINT_KEYS)
                        + '. Scoped to that set, so "gha:"-prefixed run checkpoints '
                          'are untouched. Combining it with --checkpoint for one of '
                          'those same keys is rejected before any PATCH.')
    u.add_argument('--record-completion-evidence', default=None, metavar='FLIGHT_KEY',
                   help='Record a validated completion verification-flight key '
                        '(issue #1087). The canonical record '
                        '.prflow/tmp/verification-flights/<FLIGHT_KEY>.json is '
                        'validated under the implement-completion policy; only on a '
                        'pass is a hidden "<!-- prflow:checkpoint '
                        'completion-verification:<FLIGHT_KEY> -->" ## Progress row '
                        'written (replacing any prior completion-verification row). A '
                        'non-pass record aborts the whole call before any PATCH. This '
                        'marker is what a later "--status Complete" write requires.')
    u.add_argument('--record-completion-evidence-ci', nargs=3, default=None,
                   metavar=('HEAD_SHA', 'TIER', 'RUN_URL'),
                   help='Record a CI-derived completion-evidence reading (issue '
                        '#1611) — the local/interactive tier evidence family for a '
                        'run that established green required checks for the commit it '
                        'pushed (issue #1607). HEAD_SHA is the full 40-lowercase-hex '
                        'head that was read; TIER must be "local" (a cloud run owes an '
                        'in-environment result, so "cloud" is refused, issue #1898); '
                        'RUN_URL the run the conclusions were read from. The checks read '
                        'are supplied as one or more --completion-ci-check NAME '
                        'CONCLUSION pairs, which must cover the required-check set '
                        'declared in .github/workflows/ci.yml. Validated OFFLINE (no '
                        'network, no gh): HEAD_SHA must equal git rev-parse HEAD over a '
                        'clean tree, and every CONCLUSION must be a success. Only on a '
                        'pass is a hidden "<!-- prflow:checkpoint completion-ci:<payload> '
                        '-->" ## Progress row written (replacing any prior completion-ci '
                        'row); a non-pass record aborts the whole call before any PATCH. '
                        'Like the flight marker, this satisfies a later "--status '
                        'Complete" write — the two families are counted together and '
                        'exactly one is required.')
    u.add_argument('--completion-ci-check', nargs=2, action='append', default=None,
                   metavar=('NAME', 'CONCLUSION'),
                   help='A required-check reading for --record-completion-evidence-ci '
                        '(issue #1898). Repeatable: pass one NAME CONCLUSION pair per '
                        'required check read (e.g. "lib + python tests" success). The '
                        'recorded set must cover the required-check set declared in '
                        '.github/workflows/ci.yml, and every CONCLUSION must be a '
                        'success, or the --status Complete write is refused.')
    u.add_argument('--record-resume-point', default=None, metavar='TEXT',
                   help='Record this run\'s mid-phase re-anchor resume point (issue '
                        '#1876) as a hidden "<!-- prflow:checkpoint '
                        'resume-point:<payload> -->" ## Progress row, replacing any '
                        'prior one. TEXT is the step to resume at after a nested-skill '
                        'return (e.g. a phase-file and step). It is a NAVIGATION aid, '
                        'never evidence: no verdict, completion-evidence, or '
                        'review-coverage reader consumes it — read it back with the '
                        '"resume-point" subcommand. Needs no other mutation to PATCH.')
    u.add_argument('--record-review-coverage', nargs=4, default=None,
                   metavar=('COVERAGE', 'DISPATCH', 'ROSTER', 'CHECKLIST'),
                   help='Record this run\'s resolved Phase 3 review-coverage state '
                        '(issue #1453) as a machine-readable "<!-- prflow:checkpoint '
                        'review-coverage:<coverage>:<dispatch>:<roster>:<checklist>'
                        '[:<head>:<asof>] '
                        '-->" ## Progress row, replacing any prior one. The optional '
                        '[:<head>:<asof>] as-of anchor (issue #1510) is stamped from '
                        '--record-review-coverage-head + the UTC write time. COVERAGE: '
                        + '|'.join(_REVIEW_COVERAGE_VOCABULARY['coverage'])
                        + '. DISPATCH (was a shadow fan-out attempted): '
                        + '|'.join(_REVIEW_COVERAGE_VOCABULARY['dispatch'])
                        + '. ROSTER: '
                        + '|'.join(_REVIEW_COVERAGE_VOCABULARY['roster'])
                        + '. CHECKLIST: '
                        + '|'.join(_REVIEW_COVERAGE_VOCABULARY['checklist'])
                        + '. An unresolvable axis is recorded "unestablished", never '
                          'a clean value. A later "--status Complete" write is refused '
                          'unless this record is complete or every gap it reports '
                          'carries a --review-coverage-disposition.')
    u.add_argument('--record-roster-member', nargs=2, action='append', default=None,
                   metavar=('MEMBER', 'STATUS'),
                   help='Enumerate one shadow-review roster member and its dispatch '
                        'outcome (issue #1512), as a "<!-- prflow:checkpoint '
                        'review-roster:<member>:<status> -->" ## Progress row beside the '
                        '--record-review-coverage record. MEMBER: '
                        + '|'.join(_SHADOW_ROSTER_MEMBERS)
                        + '. STATUS: '
                        + '|'.join(_ROSTER_MEMBER_STATUSES)
                        + '. Repeatable — one per member; must accompany '
                          '--record-review-coverage. The roster axis is cross-checked '
                          'against this enumeration: roster=complete is refused unless '
                          'every always-on member ('
                        + '|'.join(_SHADOW_ALWAYS_ON_MEMBERS)
                        + ') is dispatched and no member is missing, while a member its '
                          'applicability gate excluded (gated-off) does not block '
                          'complete; roster=short must name a missing member.')
    u.add_argument('--record-review-coverage-head', default=None, metavar='SHA',
                   help='The reviewed head SHA the review-coverage record is derived '
                        'from (issue #1510), stamped as the record\'s as-of anchor '
                        'beside the UTC write time so a reader can tell a record that '
                        'predates a later standalone review from a current one. A '
                        'lowercase-hex SHA; omit it to record the head as '
                        '"unestablished". Only meaningful with --record-review-coverage.')
    u.add_argument('--record-review-coverage-base', default=None, metavar='REF',
                   help='The pull request base branch the review-coverage '
                        'recomputation measures the reviewed head against (issue '
                        '#1509). A "skipped-intentional" checklist claim is refused '
                        'when the diff between the base and the reviewed head does not '
                        'satisfy the profile row that authorizes the skip (changed '
                        'lines < 100, changed files <= 3, config-only extensions, and '
                        "in this repository no engine-source path). Falls back to the "
                        'origin/HEAD symbolic ref when omitted; when the diff cannot be '
                        'recomputed the checklist axis is recorded "unestablished" '
                        'rather than refused. Only meaningful with '
                        '--record-review-coverage.')
    u.add_argument('--record-review-coverage-override', default=None, metavar='REASON',
                   help='Override the issue-#1509 recomputation for a '
                        '"skipped-intentional" checklist claim: record it as bare '
                        '"skipped" instead (non-clean — it then forces a '
                        '--review-coverage-disposition exactly as bare skipped does) '
                        'and note that the override was used. REASON states why. Never '
                        'yields a clean record.')
    u.add_argument('--review-coverage-disposition', nargs=3, action='append',
                   default=[], metavar=('GAP', 'CAUSE_CLASS', 'REASON'),
                   help='Carry a recorded review-coverage gap forward under a stated '
                        'cause class and reason (issue #1453; the cause class added by '
                        'issue #1984). GAP: '
                        + '|'.join(_REVIEW_COVERAGE_GAPS)
                        + '. CAUSE_CLASS is a CLOSED set with no elective member: '
                        + '|'.join(_REVIEW_COVERAGE_CAUSE_CLASSES)
                        + ' — environment-denial (a capability the runner did not '
                          'expose; must be corroborated by a recorded missing roster '
                          'row) or dispatched-but-lost (a reviewer that was dispatched '
                          'whose result was lost). A budget belief or a partial pass '
                          'judged adequate has no admissible class and stops the run at '
                          'Blocked. Repeatable — one per gap; every gap the record '
                          'reports must be dispositioned. Accepted ONLY over a record '
                          'reading dispatch=attempted: a run that never dispatched the '
                          'shadow has no legal way to complete (issue #1230). REASON '
                          'must name the specific gap — a generic placeholder is '
                          'refused. Each accepted disposition also appends a '
                          'dropped-failed reflection bullet, so an incomplete-coverage '
                          'run always routes to the retrospective.')
    u.add_argument('--repo-root', default=None,
                   help='Repository root for resolving the canonical '
                        'verification-flights directory and re-deriving the '
                        'candidate identity in the completion-evidence gate '
                        '(issue #1087; default: the git top-level, else cwd).')
    u.add_argument('--claim-identity', default=None,
                   help='Pin the current candidate identity the completion-evidence '
                        'gate compares the flight record against (issue #1087), '
                        'mirroring check-completion-evidence.py --claim-identity; '
                        'default re-derives it via scripts/reception_identity.py.')
    u.add_argument('--expect-comment-id', default=None,
                   help='Hydration-race precondition (issue #537, AC24): abort '
                        'before any mutation/PATCH (exit 4) if the live workpad '
                        'comment id differs from this value (concurrent '
                        'delete/recreate).')
    u.add_argument('--expect-status', default=None,
                   help='Hydration-race precondition (issue #537, AC24): abort '
                        'before any mutation/PATCH (exit 4) if the live workpad '
                        'Status word differs from this value (concurrent status '
                        'change / terminal backstop transition).')
    u.add_argument('--print-body', action='store_true',
                   help='Write the patched workpad body to stdout (issue #814). '
                        'Off by default, because the echo costs a caller the whole '
                        'workpad body on every call. The replacement verification '
                        'channel is stderr: the exit code is the success signal, and '
                        'a short breadcrumb naming the PATCHed comment id (plus the '
                        'read-back Status value, and a WARNING when it does not match '
                        'the requested status) confirms the write landed. The '
                        'volatile-tick-miss path echoes the body regardless, because '
                        'the caller must re-resolve a checkbox index against it.')
    u.add_argument('--marker', default=None, help=_marker_help)
    u.set_defaults(func=cmd_update)

    s = sub.add_parser(
        'handoff-state',
        help='Validate the offline gate->claude handoff record (issue #537) and '
             'print one of created-current-run/adopted-existing/unknown. Always '
             'exits 0; every degraded shape prints "unknown" with a breadcrumb. '
             'No network access.',
    )
    s.add_argument('file', help='Path to the handoff JSON record.')
    s.add_argument('--issue', type=int, required=True,
                   help='The run\'s resolved issue number (identity check).')
    s.add_argument('--run-id', required=True,
                   help='The current GITHUB_RUN_ID (identity check).')
    s.add_argument('--run-attempt', required=True,
                   help='The current GITHUB_RUN_ATTEMPT (identity check).')
    s.set_defaults(func=cmd_handoff_state)

    w = sub.add_parser(
        'write-handoff-record',
        help='Write the offline gate->claude handoff record (issue #537), normalizing '
             'the gate origin to one of created-current-run/adopted-existing/unknown '
             '(empty or unrecognized -> unknown). The write-side counterpart to '
             'handoff-state. Prints nothing; no network access.',
    )
    w.add_argument('file', help='Path to write the handoff JSON record.')
    w.add_argument('issue', help="The run's resolved issue number (written as int).")
    w.add_argument('run_id', help='The current GITHUB_RUN_ID (written as a string).')
    w.add_argument('run_attempt',
                   help='The current GITHUB_RUN_ATTEMPT (written as a string).')
    w.add_argument('gate', help='The gate-provided handoff token to normalize.')
    w.set_defaults(func=cmd_write_handoff_record)

    args = p.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
