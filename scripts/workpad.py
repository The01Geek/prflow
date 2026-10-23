#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""PRFlow's stateless workpad CLI for /implement.

Reads live GitHub state through gh and the repo-root .prflow/config.json.
One marker-tagged comment is canonical per issue; concurrent create races remain.
Use --help and update --help for the CLI surface.

Update re-fetches before mutation. Structural failures prevent PATCH; volatile
tick misses still persist other mutations and echo the body for re-resolution.
The final stderr outcome pairs observed persistence with a safe retry remedy."""

import argparse
import base64
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path
from typing import NamedTuple

if sys.version_info < (3, 11):  # fail fast, before any PEP 604 annotation is evaluated below
    sys.stderr.write(
        "prflow: Python 3.11+ required (found {}.{}.{}). This helper requires"
        " features of Python 3.11+. Install Python 3.11+; on Windows/Git-Bash"
        " run scripts/provision-python3-shim.sh --apply.\n".format(*sys.version_info[:3])
    )
    sys.exit(1)

# Resolve .prflow/ through the sibling lib; standalone copies keep canonical defaults.
try:
    # `__file__` is absent when this module is read and exec'd rather than imported
    # (the #343 gate exercise does exactly that), so the path insert degrades with the
    # import instead of raising ahead of a gate that must fail fast.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
    # Nested-repository detection (issue #12): a resolved root with no .prflow/ under
    # an ancestor that has one reads built-in defaults while looking configured.
    from ancestor_config import warn_ancestor_config as _warn_ancestor_config
    from state_dir import resolve_state_dir as _resolve_state_dir
except Exception:  # pragma: no cover - partial-copy / exec'd-source arm
    def _resolve_state_dir(repo_root, stream=None):
        return str(Path(repo_root) / ".prflow")

    def _warn_ancestor_config(repo_root, reader, remedy="", stream=None):
        return None

# Share AC parsing with parse-acs.py, in-process for Windows.
# Keep imports below the Python-version gate and optional: standalone Stop-hook
# copies need status/id/update without this sibling. AC operations fail through
# _require_section_parse when it is absent. Explicit sys.path also supports importlib.
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
except ImportError as _e:      # standalone deployment
    _SECTION_PARSE_IMPORT_ERROR = str(_e)

# Refreshed-token env for gh calls on native Windows (see gh_fresh_env.py).
# Optional for standalone deployments; without it, gh inherits the ambient token.
try:
    from gh_fresh_env import fresh_gh_env
except ImportError:
    def fresh_gh_env(env=None, os_name=None):
        return env


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
    """Set CLI streams to UTF-8/LF without mutating an importer's streams.
    Tolerate streams without reconfigure; native Windows defaults are unsuitable."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", newline="\n")
        except (AttributeError, TypeError, ValueError, OSError):
            pass


def _run(cmd, *, stdout=subprocess.PIPE, stdin=None):
    # `encoding="utf-8"` pins both directions of the gh pipe: DECODING gh's
    # output (issue/comment bodies, titles — routinely non-ASCII) and ENCODING
    # any stdin, so neither raises under a non-UTF-8 ambient codec. Implies text
    # mode, so `text=True` is dropped (passing both is redundant/conflicting).
    return subprocess.run(
        cmd, check=True, stdin=stdin, stdout=stdout,
        stderr=subprocess.PIPE, encoding="utf-8", env=fresh_gh_env(),
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
    """Emit the mapped outcome/remedy as the last stderr line.
    Unknown outcomes raise rather than inventing a retry remedy."""
    global _UPDATE_OUTCOME_EMITTED
    _UPDATE_OUTCOME_EMITTED = True
    sys.stderr.write(
        f"workpad.py update: outcome={outcome} "
        f"remedy={_UPDATE_REMEDY_BY_OUTCOME[outcome]}\n"
    )


def _update_fallback_outcome(exit_code=None):
    """Resolve from observed persistence: a post-PATCH failure must not invite replay."""
    if exit_code in _UPDATE_UNSELECTED_OUTCOME:
        return _UPDATE_UNSELECTED_OUTCOME[exit_code]
    return 'landed-status-unverified' if _UPDATE_PATCH_LANDED else 'not-persisted'


def cmd_update(args):
    """Emit an outcome even for post-PATCH exceptions, then preserve the original exit."""
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
    # Callers use code=3 to distinguish read/auth failures from unusable content.
    # _gh_error_detail handles missing, bytes and string stderr consistently.
    sys.stderr.write(f"workpad.py {prefix}: {_gh_error_detail(exc)}\n")
    sys.exit(code)


def _gh_error_detail(e) -> str:
    """The most specific text a failed gh call carries: its stderr when the
    subprocess left one, else the exception's own message."""
    detail = getattr(e, 'stderr', None) if isinstance(
        e, subprocess.CalledProcessError) else None
    if isinstance(detail, bytes):
        detail = detail.decode('utf-8', 'replace')
    return (detail.strip() if isinstance(detail, str) else '') or str(e)


def _repo_root():
    # Anchor default config to the nearest git root, falling back to cwd.
    try:
        r = _run(['git', 'rev-parse', '--show-toplevel'])
    except (subprocess.CalledProcessError, OSError):
        return None
    root = r.stdout.strip()
    return root or None


def _git_root_error_suffix():
    # Report git's actual failure: unresolved root does not prove "outside a repo".
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

# Read prflow/devflow namespaces per record: one live body may carry both.
# Keep the legacy alternative until lib/rename-map.json's retirement criterion
# is met; renaming the product does not rewrite existing GitHub comments.
_MARKER_NS_CURRENT = '<!-- prflow:'
_MARKER_NS_SUPERSEDED = '<!-- devflow:'
# The regex-source form of the same alternation, for the record grammars below.
_MARKER_NS_RE = r'<!-- (?:pr|dev)flow:'


def _marker_variants(marker: str) -> tuple[str, ...]:
    """Return both namespace spellings for built-in markers, or a custom marker alone."""
    if marker.startswith(_MARKER_NS_CURRENT):
        return (marker, _MARKER_NS_SUPERSEDED + marker[len(_MARKER_NS_CURRENT):])
    if marker.startswith(_MARKER_NS_SUPERSEDED):
        return (marker, _MARKER_NS_CURRENT + marker[len(_MARKER_NS_SUPERSEDED):])
    return (marker,)


def _workpad_marker(explicit=None):
    # Precedence: CLI marker, environment, config, default.
    # Prefer --marker: the cloud matcher requires the script path as command prefix.
    override = (explicit or '').strip() or os.environ.get('DEVFLOW_WORKPAD_MARKER', '').strip()
    if override:
        return override
    # Read config in-process for Windows, anchored like scripts/config-get.sh.
    # Missing root config is normal; ancestor_config warns about a nested repo
    # whose nearest git root hides an ancestor's configuration.
    _root = _repo_root()
    if _root is not None:
        _warn_ancestor_config(_root, 'workpad.py',
                              'pass --marker or set DEVFLOW_WORKPAD_MARKER')
        config_file = Path(_resolve_state_dir(_root)) / 'config.json'
    else:
        cwd = Path.cwd()
        config_file = Path(_resolve_state_dir(str(cwd))) / 'config.json'
        # Warn only when neither git root nor .prflow/ resolves; include git's stderr.
        # A root without config is the normal, silent unconfigured case.
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
        # ValueError includes malformed JSON and invalid UTF-8 (e.g. PowerShell UTF-16).
        # Warn when a present config is unreadable before falling back to the default.
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


_CRLF_RUN_RE = re.compile(r'\r+\n')


def _canonicalize_body(text):
    """Collapse every run of one or more '\\r' immediately before a '\\n' to that
    '\\n' — the one canonical form of a workpad body (issue #349). A lone '\\r' not
    before a '\\n' is left unchanged. Applied at every inbound seam so an accumulated
    native-Windows CR run never reaches a parser or re-enters the next write."""
    return _CRLF_RUN_RE.sub('\n', text)


def _stage_body_bytes(text, into_dir=None):
    """Stage UTF-8 bytes in a temp file; the caller unlinks it.
    Binary writes avoid Windows newline expansion. Set into_dir to the destination
    directory when the caller needs a same-filesystem atomic rename."""
    # Encode BEFORE creating the temp file: a UnicodeEncodeError (a lone surrogate) must
    # raise before the delete=False file exists, or it would leak that file uncaught.
    data = text.encode('utf-8')
    tf = tempfile.NamedTemporaryFile('wb', suffix='.md', delete=False, dir=into_dir)
    staged = Path(tf.name)
    try:
        with tf:
            tf.write(data)
    except OSError:
        staged.unlink(missing_ok=True)
        raise
    return staged


def _find_workpad_comment(cmd, repo, issue, marker, api_fail_code=1,
                          collect_all=False):
    """Scan paginated comments for the first marker match, or None on clean absence.
    With collect_all, return every match for duplicate/overflow detection.
    API, parse, and page-shape failures exit with api_fail_code; they are not absence."""
    page = 1
    matches = []
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
        # Wrong-shaped rc-0 JSON (including error envelopes) is an API failure, not absence.
        if not isinstance(items, list):
            _fail(
                cmd,
                f"gh comments response was not a JSON array "
                f"(got {type(items).__name__}): {str(items)[:200]}",
                code=api_fail_code,
            )
        for c in items:
            # Canonicalize before the marker test AND before returning, so every
            # consumer of the returned comment reads an LF-only body (issue #349).
            c['body'] = _canonicalize_body(c.get('body') or '')
            if c['body'].startswith(_marker_variants(marker)):
                if not collect_all:
                    return c
                matches.append(c)
        if len(items) < 100:
            return matches if collect_all else None
        page += 1


def cmd_id(args):
    marker = _workpad_marker(args.marker)
    c = _find_workpad_comment('id', _repo_full(), args.issue, marker)
    if c is not None:
        print(c['id'])
        return
    # Clean absence is exit 2 with empty stderr; failed scans must not invite create.
    sys.exit(2)


def _comment_body(repo, comment_id):
    """The live body of one comment. Raises; each caller picks its own arm."""
    return _run([
        GH, 'api',
        f'/repos/{repo}/issues/comments/{comment_id}',
        '--jq', '.body',
    ]).stdout


def _comment_body_established(repo, comment_id):
    """Return (body, established) from the raw comment object.
    Require a string body key: --jq .body conflates a missing key with literal "null".
    Transport failures raise; invalid object/body shapes return established=False."""
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
    return _canonicalize_body(obj['body']), True


def cmd_body(args):
    issue = args.issue
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
        marker = _workpad_marker(args.marker)
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


# Intake snapshots use a fixed scratch home and mirror preflight's symlink model.

def _snapshot_scratch_dir(root):
    return os.path.join(root, ".prflow", "tmp")


def _snapshot_issue_folder(root, issue):
    return os.path.join(_snapshot_scratch_dir(root), "implement", issue)


def _snapshot_symlink_offender(root, folder):
    """The first symlinked intermediate directory between .prflow/tmp and `folder`'s
    own components, or None — a symlinked component would let the write land OUTSIDE
    the .prflow/tmp scope. Mirrors preflight.py's `_scratch_symlink_offender`; the
    trusted .prflow/tmp boundary itself is not checked."""
    boundary = _snapshot_scratch_dir(root)
    parts = [p for p in os.path.relpath(folder, boundary).split(os.sep)
             if p not in ("", os.curdir)]
    prefix = boundary
    for part in parts:
        prefix = os.path.join(prefix, part)
        if os.path.islink(prefix):
            return prefix
    return None


def _snapshot_place(staged, dest):
    """Atomically move the staged temp file onto `dest` (same-filesystem rename, so a
    killed process never leaves a partial file under the destination name). A seam so
    a test can inject a placement failure."""
    os.replace(staged, dest)


def _snapshot_read_back(dest):
    """Read the persisted bytes back for the equality check. A seam so a test can
    simulate an on-disk / read divergence from the bytes just written."""
    return Path(dest).read_bytes()


def _snapshot_fail(msg, code):
    # Delegate to the shared module-level exit helper so the two stderr-breadcrumb
    # surfaces of workpad.py cannot drift in format; _fail renders a plain-string
    # `msg` as `workpad.py export-snapshot: <msg>` and exits `code` identically.
    _fail('export-snapshot', msg, code)


def cmd_export_snapshot(args):
    """Export and verify canonical workpad bytes, then print a JSON receipt.
    Exit 2: absent source; 3: read failure; 4: destination/write refusal;
    5: identity mismatch; 6: read-back mismatch. No failure emits a receipt."""
    issue = str(args.issue)
    marker = _workpad_marker(args.marker)
    repo = _repo_full(api_fail_code=3)
    # Same marker scan `body --issue` runs; a gh/parse failure exits 3 from inside,
    # and the returned body is already `_canonicalize_body`-normalized.
    c = _find_workpad_comment('export-snapshot', repo, issue, marker, api_fail_code=3)
    if c is None:
        _snapshot_fail(
            f"no workpad comment on issue #{issue} (marker scan clean-absent); "
            f"nothing to snapshot", 2)
    if 'id' not in c:
        # Both the identity guard and the receipt read c['id']; a matched comment
        # object with no 'id' is a malformed comments response, so refuse via the
        # documented read-failure code rather than let KeyError escape as the
        # undocumented exit-1 traceback the "any non-zero exit == unavailable
        # snapshot" contract forbids.
        _snapshot_fail(
            f"workpad comment on issue #{issue} carries no id field (malformed "
            f"comments response); cannot snapshot", 3)
    # Identity guard BEFORE any write: refuse a comment the caller did not adopt.
    if (args.expect_comment_id is not None
            and str(c['id']) != str(args.expect_comment_id)):
        _snapshot_fail(
            f"resolved workpad comment id {c['id']} does not match "
            f"--expect-comment-id {args.expect_comment_id}; refusing to snapshot a "
            f"different comment", 5)
    # Destination validation BEFORE any write.
    root = _repo_root()
    if not root:
        _snapshot_fail("repository root unavailable; cannot bind the snapshot "
                       "destination to the current checkout", 4)
    dest = os.path.abspath(args.out)
    candidates = (
        os.path.normpath(os.path.join(
            _snapshot_scratch_dir(root), f"intake-workpad-{issue}.md")),
        os.path.normpath(os.path.join(
            _snapshot_issue_folder(root, issue), f"intake-workpad-{issue}.md")),
    )
    if dest not in candidates:  # dest is os.path.abspath'd, already normalized
        _snapshot_fail(
            f"--out {args.out!r} is not the issue-owned intake-workpad-{issue}.md "
            f"under the scratch home (.prflow/tmp/ or "
            f".prflow/tmp/implement/{issue}/); refusing", 4)
    offender = _snapshot_symlink_offender(root, os.path.dirname(dest))
    if offender is not None:
        _snapshot_fail(
            f"refusing a symlinked scratch component {offender}; not writing outside "
            f"the .prflow/tmp scope", 4)
    dest_dir = os.path.dirname(dest)
    if not os.path.isdir(dest_dir):
        _snapshot_fail(
            f"destination directory {dest_dir} does not exist; the caller owns scratch "
            f"creation, export does not mkdir", 4)
    # Stage beside the destination for atomic rename; encoding/write failures exit 4.
    try:
        staged = _stage_body_bytes(c['body'], into_dir=dest_dir)
    except (UnicodeError, OSError) as e:
        _snapshot_fail(
            f"could not stage the workpad snapshot for {dest}: {e}", 4)
    try:
        _snapshot_place(staged, dest)
    except OSError as e:
        Path(staged).unlink(missing_ok=True)
        _snapshot_fail(f"could not place the staged snapshot at {dest}: {e}", 4)
    # Remove the placed file on either read-back failure so a non-zero exit never
    # leaves an unverified snapshot the caller could mistake for a verified one
    # (the no-receipt-means-no-file invariant the write-failure arm already keeps).
    try:
        saved = _snapshot_read_back(dest)
    except OSError as e:
        Path(dest).unlink(missing_ok=True)
        _snapshot_fail(
            f"could not read the snapshot back from {dest} for verification: {e}", 6)
    if saved != c['body'].encode('utf-8'):
        Path(dest).unlink(missing_ok=True)
        _snapshot_fail(
            f"read-back verification failed: the persisted bytes at {dest} differ "
            f"from the canonical workpad body; not reporting a snapshot", 6)
    # Only after read-back equality: emit the compact receipt. `bytes`/`sha256`
    # attest to the bytes actually on disk (read back), not the pre-write buffer.
    receipt = {
        "repo": repo,
        "issue": args.issue,
        "comment_id": c['id'],
        "updated_at": c.get('updated_at'),
        "path": dest,
        "bytes": len(saved),
        "sha256": hashlib.sha256(saved).hexdigest(),
    }
    sys.stdout.write(json.dumps(receipt) + "\n")


def _is_recognized_status_word(word: str) -> bool:
    """Recognize exact phase/terminal words, not _status_glyph's write-time prefixes."""
    s = word.strip().lower()
    return s in _STATUS_TO_PROGRESS_PHASE or s in ('blocked', 'failed', 'cancelled')


def cmd_status(args):
    """Print CLASS GLYPH WORD using the shared status vocabulary.
    Exit 0: printed; 1: present but unreadable status; 2: clean workpad absence;
    3: repository/API/transport/parse failure. A failed read is not corrupt content."""
    marker = _workpad_marker(args.marker)
    c = _find_workpad_comment(
        'status', _repo_full(api_fail_code=3), args.issue, marker,
        api_fail_code=3,
    )
    if c is None:
        # Scanned every page, no workpad — same benign exit 2 as `id`.
        sys.exit(2)
    word = _recognized_status_word_or_exit1(c.get('body') or '', 'status')
    glyph = _status_glyph(word)
    cls = _status_class(glyph)
    print(f"{cls} {glyph} {word}")


def _recognized_status_word_or_exit1(body, cmd):
    """Read the recognized Status word or exit 1 for unusable content, not transport."""
    if not _STATUS_VALUE_RE.search(body):
        sys.stderr.write(
            f"workpad.py {cmd}: workpad found but no Status line in it\n"
        )
        sys.exit(1)
    word = _status_word_from_body(body)
    if not word:
        sys.stderr.write(
            f"workpad.py {cmd}: workpad Status line has no value\n"
        )
        sys.exit(1)
    if not _is_recognized_status_word(word):
        recognized = '/'.join(
            [w.capitalize() for w in _STATUS_TO_PROGRESS_PHASE]
            + ['Blocked', 'Failed', 'Cancelled']
        )
        sys.stderr.write(
            f"workpad.py {cmd}: workpad Status word {word!r} is not a "
            f"recognized status (expected one of {recognized}) — "
            "present-but-unreadable\n"
        )
        sys.exit(1)
    return word


def cmd_intake_triage(args):
    """Read intake state through one repo resolution and one complete marker scan.
    On exit 0, emit comment_id, status_class, status_word, canonical body, prior_status.
    Exit 1: malformed/duplicated workpad state; 2: clean absence; 3: API/read failure.
    Never emit a partial object or reuse this snapshot for an update's live re-fetch."""
    marker = _workpad_marker(args.marker)
    issue = args.issue
    matches = _find_workpad_comment(
        'intake-triage', _repo_full(api_fail_code=3), issue, marker,
        api_fail_code=3, collect_all=True,
    )
    if not matches:
        sys.stderr.write(
            f"workpad.py intake-triage: no workpad comment carrying {marker!r} on "
            f"issue #{issue}; nothing to triage\n"
        )
        sys.exit(2)
    if len(matches) > 1:
        sys.stderr.write(
            f"workpad.py intake-triage: found {len(matches)} comments carrying "
            f"{marker!r} on issue #{issue} (expected exactly 1); refusing to pick "
            "one\n"
        )
        sys.exit(1)
    c = matches[0]
    comment_id = c.get('id')
    # bool is an int subclass, so screen it out explicitly; a malformed comments
    # response must not become a plausible `comment_id`.
    if isinstance(comment_id, bool) or not isinstance(comment_id, int) or comment_id <= 0:
        sys.stderr.write(
            f"workpad.py intake-triage: the workpad comment on issue #{issue} "
            f"carries no positive integer id (got {comment_id!r}); malformed "
            "comments response\n"
        )
        sys.exit(1)
    body = c.get('body') or ''
    word = _recognized_status_word_or_exit1(body, 'intake-triage')
    # A garbled marker matches no payload and reads as absent (null) — the same
    # answer the caller's live-Status fallback already handles. A DUPLICATED set
    # is refused instead: emitting one of two conflicting words, or null beside
    # them, would be exactly the plausible partial state this command forbids.
    progress = _progress_content_or_none(body)
    words = _prior_status_marker_payloads(progress) if progress is not None else []
    if len(words) > 1:
        sys.stderr.write(
            f"workpad.py intake-triage: found {len(words)} prior-status markers "
            "(expected at most 1); the prior status cannot be established\n"
        )
        sys.exit(1)
    sys.stdout.write(json.dumps({
        'comment_id': comment_id,
        'status_class': _status_class(_status_glyph(word)),
        'status_word': word,
        'body': body,
        'prior_status': words[0] if words else None,
    }, ensure_ascii=False) + '\n')


# Acceptance criteria: read both issue and workpad, bind decisions to the PR,
# and report divergence. These commands use workpad.py's existing review grant.

# Keep source tokens distinct: absence, failed reads and unmirrored state differ.
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
# AC gate sources distinguish clean absence, fallback after read failure, and
# both sources unavailable. Degraded sources cannot establish tick completion.
_ACS_SOURCE_WORKPAD_ABSENT = 'workpad-absent'
_ACS_SOURCE_UNESTABLISHED = 'unestablished'

_ACS_SECTION = 'Acceptance Criteria'


def _acs_render(items: list[dict], *, neutralize_boxes: bool) -> str:
    """Render every parsed criterion back to a checkbox line."""
    return '\n'.join(render_line(it, neutralize_box=neutralize_boxes) for it in items)


def _acs_filtered(items: list[dict]) -> list[dict]:
    """Exclude stored post-merge tags; never re-derive tags from trigger phrases."""
    return [it for it in items if not is_post_merge_tagged(it['text'])]


_CRITERIA_OUT_CRUMB = 'workpad.py acs-resolve: criteria-out:'
_COMPLIANCE_OUT_CRUMB = 'workpad.py acs-resolve: compliance-out:'
_COMPLIANCE_FILE = 'issue-compliance.md'
# The acs-resolve divergence kinds and their Issue Compliance labels; a kind carries a new text
# only when it is CHANGED.
_DIV_DROP, _DIV_DEFERRED, _DIV_CHANGED = 'DROP', 'DEFERRED', 'CHANGED'
_DIVERGENCE_LABELS = {_DIV_DROP: 'In the issue body, not in the workpad (no recorded decision)',
                      _DIV_DEFERRED: 'Deferred by this run', _DIV_CHANGED: 'Rewritten by this run'}


def _confined_out_path(path: str) -> str | None:
    """The refusal cause for an `acs-resolve` output path, or None when it is usable: the
    leaf must not be a symlink and its resolved parent must sit beneath contiguous
    `.prflow/tmp/review` segments."""
    parts = os.path.realpath(os.path.dirname(os.path.abspath(path))).replace('\\', '/').split('/')
    if not any(parts[i:i + 3] == ['.prflow', 'tmp', 'review'] for i in range(len(parts) - 2)):
        return 'it does not resolve beneath a .prflow/tmp/review/ tree'
    if os.path.islink(path):
        return 'the leaf is a symlink'
    return None


def _acs_clear_out(path: str | None, crumb: str, beside: str | None = None) -> bool:
    """Clear a usable output path before reading; refuse it if its companion is refused.
    Return success/absence. Failures print one breadcrumb without aborting resolution."""
    if path is None:
        return False
    cause = _confined_out_path(path)
    if not cause and beside is not None and _confined_out_path(beside):
        cause = f'{beside!r} beside it is refused'
    if cause:
        print(f'{crumb} refused {path!r}: {cause}; nothing written', file=sys.stderr)
        return False
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        print(f'{crumb} could not remove the earlier file {path!r} '
              f'({type(e).__name__}: {e}); not writing', file=sys.stderr)
        return False
    return True


def _acs_write_out(path: str, text: str, crumb: str, verify=None) -> None:
    """Publish `text` at `path` through a fresh temp and `os.replace`; `verify(fh)` must
    hold on the temp read back. The caller already cleared `path` via `_acs_clear_out`;
    a failure is one `crumb` stderr line and leaves no file."""
    tmp = path + '.tmp'
    try:
        if os.path.lexists(tmp):
            os.unlink(tmp)
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644),
                  'w', encoding='utf-8', newline='\n') as fh:
            fh.write(text)
        if verify is not None:
            with open(tmp, encoding='utf-8') as fh:
                if not verify(fh):
                    raise ValueError('read-back differs from the value written')
        os.replace(tmp, path)
    except (OSError, ValueError) as e:
        print(f'{crumb} write failed for {path!r} ({type(e).__name__}: {e}); nothing written',
              file=sys.stderr)
        try:
            os.remove(tmp)
        except OSError:
            pass  # the temp may never have been created; the breadcrumb above already fired


def _acs_write_criteria(path: str, items: list[dict]) -> None:
    """Write `items` as the criteria file when non-empty, publishing only bytes that
    read back equal."""
    if not items:
        return
    value = [{'criterion': n, 'text': it['text']} for n, it in enumerate(items, 1)]
    _acs_write_out(path, json.dumps(value, indent=2, ensure_ascii=False) + '\n',
                   _CRITERIA_OUT_CRUMB, verify=lambda fh: json.load(fh) == value)


def _acs_divergence_line(entry: tuple[str, str, str | None]) -> str:
    """One `divergence:` stdout line for an `_acs_diverge` entry."""
    kind, text, new = entry
    return f'{kind}: {text}' if new is None else f'{kind}: {text} -> {new}'


def _acs_follow_up(divergence: list[tuple[str, str, str | None]] | None) -> list[str]:
    """The follow-up prompt, as the last line of the `divergence:` block and of the compliance
    text, when the run deferred or rewrote a criterion; else no line."""
    if any(kind in (_DIV_DEFERRED, _DIV_CHANGED) for kind, _, _ in divergence or ()):
        return ['Confirm the narrowed work was filed as a follow-up issue before merging.']
    return []


def _acs_compliance(issue: str, source: str, count: int,
                    divergence: list[tuple[str, str, str | None]] | None) -> str:
    """The text Phase 4 reports for this resolution: `## Issue Compliance` with its
    explanation, or, for a clean resolution, the one headline line it puts in Run details.
    `divergence` is None when `not-applicable`, empty when `none`."""
    if source == _ACS_SOURCE_NONE:
        return ('## Issue Compliance\n'
                f'Issue #{issue} resolved, but neither the workpad nor the issue body carried any '
                'acceptance criteria — requirement compliance not checked.')
    if source == _ACS_SOURCE_RESOLVER_UNAVAILABLE:
        return ('## Issue Compliance\n'
                'The acceptance-criteria resolver could not be invoked (issue argument is not '
                'numeric); neither the workpad nor the issue body was examined, so this PR was '
                'reviewed WITHOUT a resolved specification.')
    kinds = [kind for kind, _, _ in divergence or ()]
    deferred, rewritten = kinds.count(_DIV_DEFERRED), kinds.count(_DIV_CHANGED)
    if divergence is None:
        scope = 'not-established'
    elif not divergence:
        scope = 'unchanged'
    else:
        scope = (f"narrowed: {deferred} deferred, {rewritten} rewritten, "
                 f"{kinds.count(_DIV_DROP)} not in the workpad")
    surface = 'the workpad' if source == _ACS_SOURCE_WORKPAD else 'the issue body'
    # A workpad fallback that found no issue-body criteria either resolved nothing.
    unresolved = not count and source in (_ACS_SOURCE_WORKPAD_UNMIRRORED, _ACS_SOURCE_WORKPAD_READ_FAILED)
    origin = 'no criteria resolved' if unresolved else f'criteria from {surface}'
    headline = f'Reviewed against issue #{issue} — {origin}; scope {scope}.'
    if count and ((source == _ACS_SOURCE_WORKPAD and divergence == [])
                  or (source == _ACS_SOURCE_ISSUE_BODY and divergence is None)):
        return headline
    supplied = "so the issue body's `## Acceptance Criteria` section supplied them"
    sentence = {
        _ACS_SOURCE_WORKPAD: ("Criteria came from the `/prflow:implement` workpad comment — this "
                              "run's authoritative set, possibly narrowed from the issue."),
        _ACS_SOURCE_ISSUE_BODY: f'This PR has no workpad criteria to use, {supplied}.',
        _ACS_SOURCE_WORKPAD_UNMIRRORED: (
            "A workpad exists but its criteria were never mirrored from the issue — a PRFlow "
            "run's mirroring silently failed and the section still holds the seeded pending "
            f"placeholder — {supplied}."),
        _ACS_SOURCE_WORKPAD_READ_FAILED: (
            f"The workpad read failed (a `gh` transport blip), {supplied} and the workpad's own "
            "criteria were never seen this run."),
        _ACS_SOURCE_PR_IDENTITY_MISMATCH: (
            "The workpad lacks issue criteria no recorded decision explains — the issue's "
            "criteria changed after the run mirrored them, or another run on the issue "
            f"overwrote that section — {supplied}. After an issue amendment, run "
            f"`workpad.py acs-remirror {issue}` and re-review."),
    }[source]
    if unresolved and source == _ACS_SOURCE_WORKPAD_UNMIRRORED:
        sentence = ("A workpad exists but its criteria were never mirrored from the issue, and "
                    "the issue body carries no `## Acceptance Criteria` section either — so no "
                    "specification was resolved.")
    elif unresolved:
        sentence = ("The workpad read failed (a `gh` transport blip) and the issue body carries "
                    "no `## Acceptance Criteria` section, so no specification was resolved — the "
                    "workpad's own criteria were never seen this run, so whether criteria exist "
                    "is unknown, not zero.")
    lines = ['## Issue Compliance',
             headline if unresolved else (
                 f'{headline} Requirement-based checklist items are listed under `## Code Review '
                 'Findings` and `## Run details`.' if count
                 else f'{headline} No criterion is left for this review to check.'),
             sentence]
    if divergence == []:
        lines.append("No divergence between the workpad's criteria and the issue body's.")
    for kind, text, new in divergence or ():
        lines.append(f'- {_DIVERGENCE_LABELS[kind]}: {text}' + ('' if new is None else f' → {new}'))
    return '\n'.join(lines + _acs_follow_up(divergence))


def _acs_publish(issue: str, source: str, items: list[dict],
                 divergence: list[tuple[str, str, str | None]] | None,
                 criteria_out: str | None, compliance_out: str | None) -> None:
    """Write the criteria file, print the stdout blocks Phase 0.4 parses, then write the
    compliance file: a fault while building its text is one `compliance-out:` stderr line.
    The `divergence:` block carries `_acs_follow_up`'s line too, so the lines Phase 0.4 stores
    hold the prompt when no compliance file is written."""
    if criteria_out:
        _acs_write_criteria(criteria_out, items)
    print(f'source: {source}')
    print('criteria:')
    rendered = _acs_render(items, neutralize_boxes=True)
    if rendered:
        print(rendered)
    print(f'criteria-count: {len(items)}')
    print('divergence:')
    if divergence is None:
        print('not-applicable')
    else:
        for line in ([_acs_divergence_line(e) for e in divergence] or ['none']) + _acs_follow_up(divergence):
            print(line)
    if compliance_out:
        try:
            text = _acs_compliance(issue, source, len(items), divergence) + '\n'
        except Exception as e:  # the blocks above are already out; the file is secondary
            print(f'{_COMPLIANCE_OUT_CRUMB} could not build the text for {compliance_out!r} '
                  f'({type(e).__name__}: {e}); nothing written', file=sys.stderr)
            return
        _acs_write_out(compliance_out, text, _COMPLIANCE_OUT_CRUMB)


def _acs_workpad_state(section_lines: list[str], items: list[dict]) -> str:
    """Distinguish mirrored-empty criteria from the pending, never-mirrored sentinel."""
    if items:
        return _ACS_SOURCE_WORKPAD
    if any(_AC_PENDING_PLACEHOLDER in ln for ln in section_lines):
        return _ACS_SOURCE_WORKPAD_UNMIRRORED
    return _ACS_SOURCE_ISSUE_BODY


def _acs_read_workpad(cmd: str, issue: str):
    """Return (body, section_lines, items) for the configured implement marker.
    Exit 2 with empty stdout/stderr on clean absence; exit 3 on read failure.
    No per-call marker override: environment/config still match the implement writer."""
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
    """Re-render all parsed criteria, preserving ticks and stored post-merge tags.
    This deterministic read normalizes checkbox formatting; it is not a byte copy."""
    _require_section_parse('acs')
    _, section_lines, items = _acs_read_workpad('acs', args.issue)
    out = []
    if args.emit_source_token:
        out.append(_acs_workpad_state(section_lines, items))
    rendered = _acs_render(items, neutralize_boxes=False)
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
    """Recover criteria through parse-acs.py and the independent issue-body endpoint.
    Return rendered criteria (possibly empty), or None when the read is unestablished."""
    parse_acs = str(Path(__file__).resolve().parent / 'parse-acs.py')
    try:
        r = subprocess.run(
            [sys.executable, parse_acs, '--issue', str(issue), '--format', 'md'],
            capture_output=True, text=True, encoding="utf-8", check=False,
        )
    except OSError:
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip('\n')


def cmd_acs_gate(args):
    """Emit source and criteria for the AC gate; degraded reads never establish ticks.
    Exit/source pairs: 0/workpad, 2/workpad-absent, 3/workpad-read-failed
    (issue-body fallback available), 4/unestablished (both reads failed)."""
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
    rendered = _acs_render(items, neutralize_boxes=False)
    if rendered:
        print(rendered)


def _acs_diverge(issue_items: list[dict], workpad_items: list[dict],
                 decisions: list[dict]) -> list[tuple[str, str, str | None]]:
    """Return (kind, issue_text, rewrite_target) for normalized issue criteria missing
    from the workpad. Ignore ticks, whitespace and post-merge tags; workpad additions
    may be mirrored Test Plan items and are not findings.
    Follow PR-bound rewrites/deferrals. Unexplained criteria remain DROP, or CHANGED
    when their own rewrite record names a target; that display alone grants no coverage."""
    issue_norm = [normalize_criterion(it['text']) for it in issue_items]
    workpad_norm = {normalize_criterion(it['text']) for it in workpad_items}
    # A `rewritten` record with no `newtext=` field records nothing about what
    # replaced the criterion, so it licenses no text change: it is excluded here
    # and, unless the walk explains its criterion, that criterion routes to `DROP`.
    # Crediting it as an audited `CHANGED:` would report a scope narrowing as
    # reviewed on a record that establishes nothing.
    rewritten = {d['text']: d['new_text'] for d in decisions
                 if d['kind'] == 'rewritten' and d['new_text']}

    lines = []
    for text in issue_norm:
        if text in workpad_norm:
            continue
        reached = _acs_rewrite_walk(text, workpad_norm, decisions)
        if reached is not None:
            kind, target = reached
            lines.append((_DIV_CHANGED, text, target) if kind == 'workpad'
                         else (_DIV_DEFERRED, text, None))
        elif text in rewritten:
            lines.append((_DIV_CHANGED, text, rewritten[text]))
        else:
            lines.append((_DIV_DROP, text, None))
    return lines


def _acs_pr_identity_ok(issue_items: list[dict], workpad_items: list[dict],
                        decisions: list[dict]) -> bool:
    """Accept a superset, or explain every missing issue criterion with a PR-bound
    rewrite chain reaching the workpad or a deferral. Unrelated records grant nothing.
    This prevents unexplained narrowing, not proof of which run authored the workpad;
    an amended issue can cause the same mismatch as a foreign run."""
    issue_norm = {normalize_criterion(it['text']) for it in issue_items}
    workpad_norm = {normalize_criterion(it['text']) for it in workpad_items}
    if not issue_norm or not workpad_norm:
        return True
    # A superset needs no narrowing explanation.
    if workpad_norm >= issue_norm:
        return True
    return all(_acs_rewrite_walk(text, workpad_norm, decisions) is not None
               for text in issue_norm - workpad_norm)


def _acs_rewrite_walk(text: str, workpad_norm: set[str],
                      decisions: list[dict]) -> tuple[str, str] | None:
    """Breadth-first walk PR-bound rewrite edges in record order, visiting each text once.
    Return the first reachable workpad text, else first deferred text, else None.
    A rewritten record without newtext is no edge; callers must bind records first."""
    deferred = {d['text'] for d in decisions if d['kind'] == 'deferred'}
    edges = [(d['text'], d['new_text']) for d in decisions
             if d['kind'] == 'rewritten' and d['new_text']]
    order, seen = [text], {text}
    for cur in order:
        for old, new in edges:
            if old == cur and new not in seen:
                seen.add(new)
                order.append(new)
    hit = next((t for t in order if t in workpad_norm), None)
    if hit is not None:
        return 'workpad', hit
    hit = next((t for t in order if t in deferred), None)
    return None if hit is None else ('deferred', hit)


def _acs_fetch_issue_body(issue: str, cmd: str = 'acs-resolve') -> str:
    try:
        r = _run([GH, 'issue', 'view', str(issue), '--json', 'body', '-q', '.body'])
    except (subprocess.CalledProcessError, OSError) as e:
        _fail(cmd, e, code=3)
    return r.stdout


def cmd_acs_resolve(args):
    """Resolve both criteria sources and report divergence from the unfiltered sets.
    Render the selected workpad set separately with post-merge criteria excluded.
    Routed workpad failures exit 0; unreadable issue body/missing parser exits 3.
    Only clean workpad absence plus empty issue criteria becomes source=none;
    unmirrored/unreadable workpads retain their distinct tokens. Invalid issue input
    routes to resolver-unavailable with a stderr diagnostic.
    With criteria-out, clear both prior outputs and write issue-compliance.md beside
    the criteria; refused or failed compliance output gets its own breadcrumb."""
    # `issue` is a required positional accepted as a string (see the argparse note),
    # so `args.issue` is always present; the ASCII-only digit test is deliberate — it
    # rejects the non-ASCII digits `str.isdigit()`/`isdecimal()` would accept, matching
    # the seed helper's `*[!0-9]*` shell guard.
    issue_arg = args.issue
    criteria_out = args.criteria_out if _acs_clear_out(args.criteria_out, _CRITERIA_OUT_CRUMB) else None
    compliance_out = None
    if args.criteria_out is not None:
        compliance_out = os.path.join(os.path.dirname(args.criteria_out), _COMPLIANCE_FILE)
        if not _acs_clear_out(compliance_out, _COMPLIANCE_OUT_CRUMB, beside=args.criteria_out):
            compliance_out = None
    if not issue_arg or not all(c in '0123456789' for c in issue_arg):
        # Distinguish malformed caller input on stderr; stdout keeps the routed token.
        print(
            f"workpad.py acs-resolve: issue argument {issue_arg!r} is not numeric — "
            f"no surface can be examined; routing as "
            f"{_ACS_SOURCE_RESOLVER_UNAVAILABLE}",
            file=sys.stderr,
        )
        _acs_publish(issue_arg, _ACS_SOURCE_RESOLVER_UNAVAILABLE, [], None,
                     criteria_out, compliance_out)
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
        # Only clean absence can become none. Empty fallbacks cannot establish that an
        # unreadable or unmirrored workpad has no criteria.
        if not issue_items and state == _ACS_SOURCE_ISSUE_BODY:
            source = _ACS_SOURCE_NONE

    divergence = (_acs_diverge(issue_items, workpad_items, decisions)
                  if state in (_ACS_SOURCE_WORKPAD, _ACS_SOURCE_PR_IDENTITY_MISMATCH) else None)
    _acs_publish(args.issue, source, _acs_filtered(selected), divergence,
                 criteria_out, compliance_out)


def cmd_acs_remirror(args):
    """Mirror live issue-body criteria into a Complete workpad in one noted PATCH.
    Exit 3: missing parser/unreadable body; 1: no criteria, parse failure, or unusable
    workpad; 4: status precondition mismatch. No caller-supplied criteria can land."""
    _require_section_parse('acs-remirror')
    body = _acs_fetch_issue_body(args.issue, 'acs-remirror')
    if not parse_checkboxes(extract_section(body, _ACS_SECTION)):
        sys.stderr.write(
            f"workpad.py acs-remirror: issue #{args.issue} has no checkbox criterion "
            f"under '## {_ACS_SECTION}'; nothing re-mirrored\n")
        sys.exit(1)
    staged = []
    try:
        staged.append(_stage_body_bytes(body))
        parse_acs = str(Path(__file__).resolve().parent / 'parse-acs.py')
        try:
            r = subprocess.run(
                [sys.executable, parse_acs, '--body-file', str(staged[0])],
                capture_output=True, text=True, encoding='utf-8', check=False,
            )
            cause = f'exited {r.returncode}: {r.stderr.strip()}' if r.returncode else ''
        except OSError as e:
            cause = f'could not run: {e}'
        if cause:
            sys.stderr.write(
                f"workpad.py acs-remirror: parse-acs.py {cause}; nothing re-mirrored\n")
            sys.exit(1)
        sys.stderr.write(r.stderr)
        staged.append(_stage_body_bytes(r.stdout))
        update_args = _build_parser().parse_args([
            'update', str(args.issue), '--replace-acs-file', str(staged[1]),
            '--expect-status', 'Complete',
            '--note', ("Re-mirrored `## Acceptance Criteria` from the issue body "
                       "(`workpad.py acs-remirror`)"),
        ])
        # The note claims the replacement, which a failed PATCH does not buffer.
        update_args.unbuffered_notes = True
        cmd_update(update_args)
    finally:
        for p in staged:
            p.unlink(missing_ok=True)


# Preserve the leading run key and verdict stamp; deeper markers are prose.
_LEADING_MARKER_SCAN = 2
# Match the readers' column-zero anchor; tolerate and trim trailing whitespace.
_LEADING_MARKER_RE = re.compile(
    r'^' + _MARKER_NS_RE + r'([A-Za-z0-9_.:-]+)[^\n]*-->[ \t\r]*$')


def _leading_markers(body):
    """Return ([(kind, trimmed_line)], remaining_lines) for the leading marker window."""
    lines = body.split('\n')
    found = []
    for line in lines[:_LEADING_MARKER_SCAN]:
        m = _LEADING_MARKER_RE.match(line)
        if not m:
            break
        found.append((m.group(1), line.rstrip(' \t\r')))
    return found, lines[len(found):]


def _merge_leading_markers(live_body, new_body, drop=()):
    """Restore missing leading markers; return (body, reinserted_kinds).
    On restoration, live order wins and the caller's first line wins per kind.
    If none are missing, return the caller's body untouched. Removal requires drop;
    mispositioned same-kind caller markers are discarded instead of duplicated.
    Keep run-key/verdict positions aligned with post-review-verdict.sh."""
    live = [(k, l) for k, l in _leading_markers(live_body)[0] if k not in drop]
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
    """PATCH text via a private temp file, or body_path directly; return the response.
    Never stage beside the caller's file, which may be read-only or in the git tree."""
    staged = None
    if body_path is None:
        if text is None:
            raise ValueError('_patch_comment_body: pass text= or body_path=')
        _check_body_within_limit(_byte_len(text))
        staged = _stage_body_bytes(text)
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


def _read_canonical_body(body_path, cmd):
    """Return (decoded UTF-8, LF-canonical) bytes from a body file; exit 1 on failure.
    Avoid universal-newline reads: they would turn Windows CRCRLF into two newlines."""
    try:
        raw = body_path.read_bytes()
    except OSError as e:
        sys.stderr.write(f"workpad.py {cmd}: body file unreadable: {e}\n")
        sys.exit(1)
    try:
        decoded = _decode_utf8(raw, cmd, str(body_path))
    except _UpdateError as e:
        sys.stderr.write(f"workpad.py {cmd}: {e}\n")
        sys.exit(1)
    return decoded, _canonicalize_body(decoded)


def cmd_patch(args):
    repo = _repo_full()
    body_path = Path(args.body_file)
    if not body_path.is_file():
        sys.stderr.write(
            f"workpad.py patch: body file not found: {body_path}\n"
        )
        sys.exit(1)
    decoded, composed = _read_canonical_body(body_path, 'patch')
    # Missing/non-string body is unestablished, never an empty marker inventory.
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
    merged, reinserted = _merge_leading_markers(
        live, composed, drop=set(getattr(args, 'drop_leading_marker', None) or ()))
    if reinserted:
        sys.stderr.write(
            'workpad.py patch: re-inserted leading marker(s) the composed body '
            f'omitted: {", ".join(reinserted)}\n'
        )
    try:
        if reinserted:
            _patch_comment_body(repo, args.comment_id, merged)
        elif decoded == composed:
            # The file is already canonical (canonicalization changed nothing): PATCH
            # it directly with no temp staged, keeping the read-only-directory property
            # (issue #349, #1508).
            _patch_comment_body(repo, args.comment_id, body_path=body_path)
        else:
            _patch_comment_body(repo, args.comment_id, composed)
    except _UpdateError as e:
        # A size refusal is pre-PATCH, not a transport error — so it is handled
        # here rather than by the CalledProcessError/OSError arm below.
        sys.stderr.write(f"workpad.py patch: {e}\n")
        sys.exit(1)
    except (subprocess.CalledProcessError, OSError) as e:
        _fail('patch', e)


class _ProgressStructureError(Exception):
    """The fetched review progress-comment body lacks structure a boundary write
    requires (no ## Blueprint, no **Last updated:**, or — for an append — no
    ## Findings (live) section). Distinct from
    _TickMatchError (a per-row tick miss) and _UpdateError (the size refusal)."""


_REVIEW_FINDINGS_PLACEHOLDER = '_(Phase-3 findings appear here as each agent returns.)_'
_REVIEW_FINDINGS_SECTION = 'Findings (live)'
_REVIEW_BLUEPRINT_SECTION = 'Blueprint'


def _insert_into_findings(section_content: str, payload: str) -> str:
    """Append `payload` as the last line(s) of the ## Findings (live) section body,
    replacing the placeholder on the first insert and demoting a payload line that
    opens `## ` to `### ` so an inserted block never opens a new section."""
    # Demote any line `_SECTION_RE` would treat as a section opener (`##` + ANY
    # whitespace, tab included); a bare `startswith('## ')` check misses `##\t`,
    # letting an appended block open a new section on the next `_split_sections` read.
    demoted = [
        ('### ' + ln[3:]) if re.match(r'^##\s', ln) else ln
        for ln in payload.split('\n')
    ]
    existing = section_content.split('\n')
    while existing and existing[-1].strip() == '':
        existing.pop()
    if all(ln.strip() in ('', _REVIEW_FINDINGS_PLACEHOLDER) for ln in existing):
        existing = []
    return '\n'.join(existing + demoted) + '\n'


def _progress_apply(live: str, tick, append_text) -> str:
    """Return the mutated review-comment body for a boundary update. Raises
    _ProgressStructureError when the Phase 0.5 template did not land, and
    _TickMatchError on a per-row tick miss. Issues no PATCH — every raise here
    precedes cmd_progress's PATCH call, so a structural refusal never writes."""
    if not _LAST_UPDATED_RE.search(live):
        raise _ProgressStructureError(
            'no **Last updated:** line found; the Phase 0.5 template write did not '
            'land — no PATCH was made')
    preamble, sections = _split_sections(live)
    bp_idx = _find_section(sections, _REVIEW_BLUEPRINT_SECTION)
    if bp_idx is None:
        raise _ProgressStructureError(
            'no ## Blueprint section found; the Phase 0.5 template write did not '
            'land — no PATCH was made')
    if tick:
        heading, bp_content = sections[bp_idx]
        # Unlike `update`, an already-ticked row is refused here: a replay must
        # not PATCH a second `Last updated` over a landed boundary.
        bp_content, _ticked_now = _tick_checkbox(
            bp_content, tick, _REVIEW_BLUEPRINT_SECTION)
        if not _ticked_now:
            raise _TickMatchError(
                f"the {_REVIEW_BLUEPRINT_SECTION} checkbox matching {tick!r} is "
                f"already ticked — no PATCH was made")
        sections[bp_idx] = (heading, bp_content)
    if append_text is not None:
        fi_idx = _find_section(sections, _REVIEW_FINDINGS_SECTION)
        if fi_idx is None:
            raise _ProgressStructureError(
                'no ## Findings (live) section found; the Phase 0.5 template write '
                'did not land — no PATCH was made')
        heading, fi_content = sections[fi_idx]
        sections[fi_idx] = (heading, _insert_into_findings(fi_content, append_text))
    body = _join_sections(preamble, sections)
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    body, _ = _LAST_UPDATED_RE.subn(f'**Last updated:** {now}', body, count=1)
    return body


def cmd_progress(args):
    """Boundary-update a review progress comment BY COMMENT ID: tick one
    ## Blueprint row and/or append to ## Findings (live), refresh Last updated,
    PATCH once — no issue lookup and no marker lookup (distinct from cmd_update,
    whose id cache/marker scan/note budget assume the issue-workpad shape)."""
    append_text = args.append
    if args.append_file is not None:
        # Route through the shared read/decode/canonicalize helper (issue #349) so
        # this seam cannot drift from cmd_patch/cmd_create and an invalid-UTF-8 file
        # gets the helper's targeted breadcrumb, not a raw UnicodeDecodeError.
        _, append_text = _read_canonical_body(Path(args.append_file), 'progress')
    repo = _repo_full()
    try:
        live, established = _comment_body_established(repo, args.comment_id)
    except (subprocess.CalledProcessError, OSError) as e:
        _fail('progress', e)
    if not established:
        sys.stderr.write(
            'workpad.py progress: could not establish the live body of comment '
            f'{args.comment_id}; no PATCH was made\n')
        sys.exit(1)
    try:
        content = _progress_apply(live, args.tick, append_text)
    except (_TickMatchError, _ProgressStructureError) as e:
        sys.stderr.write(f"workpad.py progress: {e}\n")
        sys.exit(1)
    try:
        _patch_comment_body(repo, args.comment_id, content)
    except _UpdateError as e:
        sys.stderr.write(f"workpad.py progress: {e}\n")
        sys.exit(1)
    except (subprocess.CalledProcessError, OSError) as e:
        _fail('progress', e)
    sys.stderr.write(f"workpad.py progress: PATCHed comment {args.comment_id}\n")


_COMMENT_URL_RE = re.compile(r'#issuecomment-(\d+)\s*$')


def _post_issue_comment(cmd, issue, composed, api_fail_code=1):
    """Post `composed` as a new comment on `issue` and return gh's raw stdout (which
    carries the new comment's URL). The ONE comment-creation seam: `create` posts the
    workpad through it and `compact` posts the overflow comment (issue #755), so both
    stage their body as BYTES (issue #349 — a text-mode write would re-inflate it with
    CR) and both report a transport failure the same way."""
    staged = _stage_body_bytes(composed)
    try:
        r = _run([
            GH, 'issue', 'comment', str(issue),
            '--body-file', str(staged),
        ])
    except (subprocess.CalledProcessError, OSError) as e:
        _fail(cmd, e, code=api_fail_code)
    finally:
        staged.unlink(missing_ok=True)
    return r.stdout


def cmd_create(args):
    body_path = Path(args.body_file)
    if not body_path.is_file():
        sys.stderr.write(
            f"workpad.py create: body file not found: {body_path}\n"
        )
        sys.exit(1)
    # Bytes, then canonicalize (issue #349): post LF-only bytes so a body file a
    # native-Windows new-body wrote as CRLF is stored canonical, not re-inflated.
    _, composed = _read_canonical_body(body_path, 'create')
    out = _post_issue_comment('create', args.issue, composed)
    m = _COMMENT_URL_RE.search(out)
    if m:
        print(m.group(1))
        return
    # A missing URL may follow a successful post; re-scanning could select another
    # comment and hide the failure. Refuse instead of guessing its identity.
    sys.stderr.write(
        "workpad.py create: gh did not print a comment URL; the workpad "
        "may or may not have been posted. Inspect the issue manually before "
        "retrying. Raw stdout:\n"
    )
    sys.stderr.write(out)
    sys.exit(1)


def cmd_now(_args):
    now = datetime.datetime.now(datetime.timezone.utc)
    print(now.strftime('%Y-%m-%dT%H:%M:%SZ'))


# Share the pending AC sentinel between skeleton and terminal gate.
# It means mirroring did not run, unlike parse-acs.py's mirrored-empty sentinel.
_AC_PENDING_PLACEHOLDER = '_(pending — mirrored from the issue when the run begins)_'

# Scope decisions explain criterion membership/text changes to the reviewer.
# They live in Progress, before Reflections. Base64 protects criterion delimiters.
# Pre-PR records use pending, which covers nothing until bind-scope-decisions.
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
    """Decode UTF-8 or return None; unreadable payloads cannot cover a criterion."""
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
    """Decode a nonempty criterion or return None with a cause-specific breadcrumb."""
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
    """Return decoded nonempty records bound to pr.
    Exclude pending/foreign/unreadable records; pr=None establishes no ownership."""
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
    """Bind all pending records to pr, leaving numeric bindings unchanged.
    Residual: records have no run stamp, so a later run also binds an earlier run's
    abandoned pending records. Report the bound count to make that visible."""
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


# Deferred presence uses bounded Python reads, never a body dump or PATH parser.
# Filed markers have their own grammar; extending the closed scope-decision
# grammar would also change the merge gate's acs-resolve reader.
_DEFERRED_FILED_RE = re.compile(
    _MARKER_NS_RE + r'deferred-filed text=([A-Za-z0-9+/=]*) -->')

# Progress bullet wire format shared by readers. Keep timestamp/separator
# changes aligned with _append_progress_note's independent f-string writer.
_PROGRESS_BULLET_PREFIX_RE = r'^[ \t]*[-*][ \t]+\d{2}:\d{2}:\d{2}[ \t]+—[ \t]+'
_PROGRESS_BULLET_RE = re.compile(_PROGRESS_BULLET_PREFIX_RE + r'(.*)$')


def _render_deferred_filed(normalized_text: str) -> str:
    """Render a filed marker from deferred-presence's exact normalized criterion.
    Do not normalize again or retype it: the marker must match the stored record key."""
    return f'<!-- prflow:deferred-filed text={_b64(normalized_text)} -->'


def _single_section_content(
    sections: list[tuple[str, str]], name: str
) -> str | None:
    """Return the sole case-insensitive section's content, or None if absent/duplicated."""
    target = f'## {name}'.lower()
    hits = [c for h, c in sections if h.strip().lower() == target]
    return hits[0] if len(hits) == 1 else None


# The reflection-section heading: current spelling first, superseded second.
# Renaming either literal breaks the dual read-through, so a legacy workpad would
# lose its reflections (see docs/internal/naming.md for the read-through policy).
_REFLECTION_HEADING = 'PRFlow Reflections'
_REFLECTION_HEADING_SUPERSEDED = 'Devflow Reflection'


def _find_reflection_section(sections: list[tuple[str, str]]) -> int | None:
    """Find the current reflection heading first, falling back to the legacy spelling."""
    idx = _find_section(sections, _REFLECTION_HEADING)
    if idx is None:
        idx = _find_section(sections, _REFLECTION_HEADING_SUPERSEDED)
    return idx


def _single_reflection_content(sections: list[tuple[str, str]]) -> str | None:
    """Content of the one reflection section under either spelling (current first)."""
    content = _single_section_content(sections, _REFLECTION_HEADING)
    if content is None:
        content = _single_section_content(sections, _REFLECTION_HEADING_SUPERSEDED)
    return content


def _progress_content_or_none(body: str) -> str | None:
    """Return the sole Progress section; absence/duplication is unknown, not empty."""
    _, sections = _split_sections(body)
    return _single_section_content(sections, 'Progress')


def _isolated_progress_markers(content: str, pattern: 're.Pattern[str]'):
    """Yield full-marker matches from isolated bullets in the resolved Progress content.
    Other sections and markers embedded in prose are excluded. This is narrower than
    _parse_scope_decisions's whole-body scan. A free-text note consisting solely of
    a valid marker remains indistinguishable from a writer-produced record."""
    for line in content.split('\n'):
        bullet = _PROGRESS_BULLET_RE.match(line)
        if bullet is None:
            continue
        m = pattern.fullmatch(bullet.group(1).strip())
        if m is not None:
            yield m


def _whole_body_deferred_count(body: str) -> int:
    """Count deferred records visible to the merge gate's whole-body reader.
    Compare with isolated Progress records so reader disagreement cannot look empty."""
    return sum(1 for m in _SCOPE_DECISION_RE.finditer(body)
               if m.group(2) == _SCOPE_DECISION_DEFERRED_KIND)


def _bound_deferred_records(content: str, pr: int) -> tuple[list[str], int, int]:
    """Return (normalized_bound_texts, unbound_count, corrupted_count).
    Count pending/foreign deferrals as unbound and bad bound payloads as corrupted;
    neither can establish zero outstanding work. Rewritten records enter no bucket."""
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
    """Read filed criterion keys from isolated Progress bullets, like deferred records."""
    filed: set[str] = set()
    for m in _isolated_progress_markers(content, _DEFERRED_FILED_RE):
        text = _decode_scope_payload(m.group(1), 'text', 'deferred-filed')
        if text is not None:
            filed.add(text)
    return filed


def _print_unestablished(reason: str, unbound: int = 0, corrupted: int = 0,
                         filed: 'set[str] | None' = None):
    """Print the unestablished count/cause and exit 2.
    Include known filed criteria so retrying an unestablished read cannot re-file them."""
    print(f'unestablished: reason={reason} unbound={unbound} corrupted={corrupted}')
    for text in sorted(filed or ()):
        print(f'filed: {text}')
    sys.exit(2)


def cmd_deferred_presence(args):
    """Report unfiled PR-bound deferrals without printing the workpad.
    Exit 0: outstanding; 1: none outstanding; 2: unestablished, so callers still inspect.
    Print one count/cause line, outstanding criteria, and any known filed criteria;
    unestablished reads must not strand work or re-file known discharged criteria."""
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
    """Print a navigation hint, never verification evidence.
    Exit 0: decoded hint; 1: absent/malformed; 2: unreadable workpad/Progress section.
    Only the hint reaches stdout; on unreadable state callers re-read the phases."""
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
    """Read exact-prefix deferred reflection texts from already-split sections.
    Return None for an absent/duplicated reflection section, never a confident empty set."""
    content = _single_reflection_content(sections)
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
    """Compare deferred-reflection count with PR-bound scope-decision deferrals.
    Exit 0: backed; 1: excess reflections (print excess and all texts); 2: unestablished
    section/record/read state. This polarity differs from deferred-presence.
    Backing is a count floor, not an identity match: reflections have no join key.
    Fix-loop manifest deferrals use dropped-failed and do not count as backing."""
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
            "reflection section (absent or duplicated), so whether any deferred "
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


# Share the reproduction row between skeleton and reconciliation.
# Detect by the stable substring so wording/tick/marker changes do not hide it.
_REPRODUCTION_ROW_TEXT = 'Reproduction captured (bug issues only)'
_REPRODUCTION_ROW = f'  - [ ] {_REPRODUCTION_ROW_TEXT}'
_REPRODUCTION_ROW_SUBSTR = 'Reproduction captured'


# Extension rows: (phase, text, stable substring), shared by skeleton and repair.
# Avoid substrings used by other tick-progress calls: ambiguous matches raise.
# The backticked review-and-fix row keeps its reach separate from extension names.
_EXTENSION_ROWS = (
    ('Setup', 'Skill extension resolved: implement.md',
     'extension resolved: implement.md'),
    ('Review', 'Skill extension resolved: review-and-fix.md',
     'extension resolved: review-and-fix.md'),
    ('Review', 'Skill extension resolved: fix.md',
     'extension resolved: fix.md'),
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


# Rendered Review rows pair with live tick operands; keep their wording coupled.
# The loop suffix distinguishes the fix-loop row from its extension row.
_REVIEW_AND_FIX_ROW = ('Review-and-fix loop', 'Review-and-fix loop')
_AC_GATE_ROW = ('Acceptance-criteria gate', 'Acceptance-criteria gate')

# The whole **Review** block declared ONCE in tick order — SINGLE SOURCE for both the
# skeleton and the repair. Built by REFERENCE only: this ordered view must never become
# `_REVIEW_PROGRESS_ROWS`' or `_EXTENSION_ROWS`' definition (each stays authoritative).
_REVIEW_BLOCK_ROWS = (
    *_REVIEW_PROGRESS_ROWS,
    _REVIEW_AND_FIX_ROW,
    *((text, substr) for phase, text, substr in _EXTENSION_ROWS
      if phase == 'Review'),
    _AC_GATE_ROW,
)


def _managed_progress_rows():
    """Rows the Phase 1.3 reconciliation pass repairs into a workpad created
    before they existed, in the order the run ticks them: the non-Review extension
    rows (the Setup `implement` row) followed by the whole **Review** block
    declared in `_REVIEW_BLOCK_ROWS` (its literal rows, the engine rows and the
    Review extension rows)."""
    for phase, text, substr in _EXTENSION_ROWS:
        if phase != 'Review':
            yield phase, text, substr
    for text, substr in _REVIEW_BLOCK_ROWS:
        yield 'Review', text, substr


def _extension_rows_block(phase: str) -> str:
    """The rendered nested rows for one phase, newline-terminated (empty when the
    phase owns none), for splicing into the `cmd_new_body` template."""
    return ''.join(
        f'  - [ ] {text}\n' for row_phase, text, _ in _EXTENSION_ROWS
        if row_phase == phase
    )


def _review_block_block() -> str:
    """The whole rendered **Review** block for the `cmd_new_body` skeleton, in
    `_REVIEW_BLOCK_ROWS` (tick) order, newline-terminated for splicing."""
    return ''.join(f'  - [ ] {text}\n' for text, _ in _REVIEW_BLOCK_ROWS)


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
    # Default to a reproduction row when deterministic classification is unknown.
    # Phase 1's recorded content classification and reconciliation decide the final row.
    repro = (
        ''
        if getattr(args, 'no_reproduction', False)
        else _REPRODUCTION_ROW + '\n'
    )
    sys.stdout.write(f"""{marker}
# PRFlow Workpad

**Status:** 🚀 Setup
**Branch:** {branch}
**Run:** {run}
**PR:** _not yet created_
**Last updated:** {last_updated}

## Progress
- [ ] **Setup**
  - {seed_ts} — /prflow:implement run started
{_extension_rows_block('Setup')}- [ ] **Implement**
{repro}  - [ ] Code + sweeps
- [ ] **Review**
{_review_block_block()}- [ ] **Documentation**
{_extension_rows_block('Documentation')}- [ ] **PR marked ready**

## Plan
- [ ] _(planning in progress)_

## Acceptance Criteria
{_AC_PENDING_PLACEHOLDER}

## PRFlow Reflections
""")


# Update edits live structured Markdown: metadata header plus ordered ## sections.

_STATUS_RE = re.compile(r'^\*\*Status:\*\*\s+.*$', re.MULTILINE)
_STATUS_VALUE_RE = re.compile(r'^\*\*Status:\*\*\s+(.*?)\s*$', re.MULTILINE)
_BRANCH_RE = re.compile(r'^\*\*Branch:\*\*\s+.*$', re.MULTILINE)
_RUN_RE = re.compile(r'^\*\*Run:\*\*\s+.*$', re.MULTILINE)
_PR_RE = re.compile(r'^\*\*PR:\*\*\s+.*$', re.MULTILINE)
_LAST_UPDATED_RE = re.compile(r'^\*\*Last updated:\*\*\s+.*$', re.MULTILINE)
_SECTION_RE = re.compile(r'^(##\s+.+)$', re.MULTILINE)
# Single source for the checkbox-row grammar shared by `_rewrite_checkbox` and
# its tick/carry-forward writers (4 groups: 1=indent+bullet, 2=`[ xX]` state
# cell, 3=gap, 4=text). `_rewrite_checkbox` *preserves* group 2 and the tick
# writers *overwrite* it with `[x]`, so keep the group order stable if you edit it.
# `_tick_checkbox` reads the same grammar: since issue #635 it must see ticked rows
# too, to tell a satisfied replay from a miss. Hoisted to a constant so the row
# grammar can't drift between call sites.
_CHECKBOX_ROW_RE = re.compile(r'^(\s*[-*]\s+)(\[[ xX]\])(\s+)(.*)$')

# Canonical status glyphs; Failed and Cancelled have no triggering-comment reaction.
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
    """Return the trimmed Status value, glyph intact, or empty if no line exists.
    Readers needing line presence rather than its value use _STATUS_VALUE_RE."""
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


# Status class tokens distinguish terminal outcomes for stall-backstop-decide.sh.
# Running and unknown glyphs default to interim.
_TERMINAL_STATUS_CLASS_BY_GLYPH = {
    '🎉': 'complete',
    '👎': 'blocked',
    '💥': 'failed',
    '🛑': 'cancelled',
}


def _status_class(glyph: str) -> str:
    """Map a Status glyph to its `workpad.py status` class token (issue #1025)."""
    return _TERMINAL_STATUS_CLASS_BY_GLYPH.get(glyph, 'interim')


# Managed status-mirror labels (issue #2117). Match by EXACT membership, never
# the `PRFlow` prefix (lib/scan.sh's provenance label, a prefix of all three) —
# a prefix match strips it and breaks the retrospective's candidate selection.
_STATUS_LABEL_IMPLEMENTING = 'PRFlow:Implementing'
_STATUS_LABEL_STUCK = 'PRFlow:Stuck'
_STATUS_LABEL_COMPLETE = 'PRFlow:Complete'
# Status CLASS → managed label. `interim` covers every in-progress word (all
# seven, via `_status_class`'s default arm) — not visible from the map below.
_STATUS_CLASS_TO_LABEL = {
    'interim': _STATUS_LABEL_IMPLEMENTING,
    'blocked': _STATUS_LABEL_STUCK,
    'failed': _STATUS_LABEL_STUCK,
    'cancelled': _STATUS_LABEL_STUCK,
    'complete': _STATUS_LABEL_COMPLETE,
}
_MANAGED_STATUS_LABELS = frozenset(_STATUS_CLASS_TO_LABEL.values())
# Fixed brand color per managed status label, added to the create POST (issue
# #72), keyed on the exact hardcoded name — create-only, so never add a
# PATCH/recolor path.
_MANAGED_LABEL_COLORS = {
    _STATUS_LABEL_IMPLEMENTING: '211108',
    _STATUS_LABEL_STUCK: 'c8201c',
    _STATUS_LABEL_COMPLETE: '0e8c31',
}


# The canonical ## Progress top-level phase labels, in order — the single
# source of truth that `_STATUS_TO_PROGRESS_PHASE` (below) and the `new-body`
# checklist (cmd_new_body) must both agree with. A note is nested under one of
# these rows by substring match, so renaming a phase here, in the map, or in
# the template without updating the others would misfile notes silently; the
# import-time assert below and the `new-body`-template test guard against that.
_PROGRESS_PHASES = ('Setup', 'Implement', 'Review', 'Documentation', 'PR marked ready')

# The `_PROGRESS_PHASES` rows the terminal-Complete backstop never ticks (issue
# #635). `PR marked ready` records an OUTCOME the Complete write cannot vouch for:
# a run whose `implement_pr_state` is `draft`, or whose publish failed, ends
# Complete with the PR still a draft, and Phase 4.3 ticks the row only on the
# published outcome. The row stays in `_PROGRESS_PHASES` — the note-filing map and
# `derive-run-profile.py` still read it there.
_BACKSTOP_EXCLUDED_PHASES = ('PR marked ready',)
_BACKSTOP_PROGRESS_PHASES = tuple(
    ph for ph in _PROGRESS_PHASES if ph not in _BACKSTOP_EXCLUDED_PHASES
)

# Fail loudly at import if the exclusion ever names a row the canonical list does
# not carry — a rename there would otherwise silently restore the backstop tick.
# An explicit raise, not a bare `assert`, which `python3 -O` strips.
if not set(_BACKSTOP_EXCLUDED_PHASES) <= set(_PROGRESS_PHASES):
    raise AssertionError(
        'workpad: _BACKSTOP_EXCLUDED_PHASES names a phase not in _PROGRESS_PHASES: '
        f'{set(_BACKSTOP_EXCLUDED_PHASES) - set(_PROGRESS_PHASES)}')

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
    """Set a header literally, or insert after the first available priority anchor.
    Anchor order preserves canonical header order when hydrating legacy workpads."""
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
    """Tick canonical top-level backstop phases in place, excluding outcome-only rows.
    Leave nested rows unchanged; missing/noncanonical Progress is a no-op."""
    idx = _find_section(sections, 'Progress')
    if idx is None:
        return
    heading, content = sections[idx]
    out = []
    for line in content.split('\n'):
        m = _TOP_LEVEL_CHECKBOX_RE.match(line)
        if m and m.group(1) == ' ' and any(
            ph.lower() in m.group(2).lower() for ph in _BACKSTOP_PROGRESS_PHASES
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
    (Progress -> Plan -> Acceptance Criteria -> PRFlow Reflections), so a repair
    that re-creates it cannot express its position as "after" anything.
    """
    return [(new_heading, new_content.rstrip('\n') + '\n')] + list(sections)


def _join_preserving_newline(new_lines, content: str) -> str:
    """Re-join section lines, preserving whether the original `content` ended in a
    newline. The shared tail of every in-place line-rewrite helper in this file."""
    return '\n'.join(new_lines) + ('\n' if content.endswith('\n') else '')


def _tick_checkbox(
    content: str, text_substr: str, section_label: str
) -> tuple[str, bool]:
    """Return (content, ticked_now) for a unique matching row.
    Prefer one unticked match, else accept one ticked match as an unchanged replay.
    No match or ambiguity in either set raises volatile _TickMatchError; other
    mutations may still land, unlike a missing section's structural _UpdateError."""
    candidates = []  # unticked matches: (line_idx, match)
    ticked = 0       # already-ticked matches
    new_lines = []
    for line in content.splitlines():
        m = _CHECKBOX_ROW_RE.match(line)
        if m and text_substr.lower() in m.group(4).lower():
            if m.group(2) == '[ ]':
                candidates.append((len(new_lines), m))
            else:
                ticked += 1
        new_lines.append(line)
    if len(candidates) > 1:
        raise _TickMatchError(
            f"{len(candidates)} {section_label} checkboxes match {text_substr!r} "
            f"(ambiguous match); be more specific"
        )
    if not candidates:
        if ticked == 1:
            return content, False
        if ticked > 1:
            raise _TickMatchError(
                f"{ticked} already-ticked {section_label} checkboxes match "
                f"{text_substr!r} (ambiguous match); be more specific"
            )
        raise _TickMatchError(
            f"no {section_label} checkbox matched substring "
            f"{text_substr!r} (no match)"
        )
    line_idx, m = candidates[0]
    new_lines[line_idx] = f"{m.group(1)}[x]{m.group(3)}{m.group(4)}"
    return _join_preserving_newline(new_lines, content), True


def _tick_checkbox_by_index(
    content: str, n: int, section_label: str
) -> tuple[str, bool]:
    """Tick the 1-based checkbox position across all tick states.
    Return (content, ticked_now); an already-ticked target is satisfied.
    Only an out-of-range index raises volatile _TickMatchError."""
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
        return content, False
    new_lines[line_idx] = f"{m.group(1)}[x]{m.group(3)}{m.group(4)}"
    return _join_preserving_newline(new_lines, content), True


def _carried_tick_key(text: str) -> str:
    """The identity a `--replace-plan-file` tick is carried forward by: the row's
    text with every run of whitespace collapsed to one space and the ends
    stripped. Case-SENSITIVE — a reworded or re-cased step is a different step, so
    only a pure whitespace/indentation change keeps its tick (issue #635)."""
    return ' '.join(text.split())


def _carry_forward_ticks(old_content: str, new_content: str) -> str:
    """Carry old ticks to matching new row text, one-for-one.
    Ignore indentation; already-ticked new rows consume no carry budget."""
    budget: dict[str, int] = {}
    for line in old_content.splitlines():
        m = _CHECKBOX_ROW_RE.match(line)
        if m and m.group(2) != '[ ]':
            key = _carried_tick_key(m.group(4))
            budget[key] = budget.get(key, 0) + 1
    if not budget:
        return new_content
    out = []
    for line in new_content.splitlines():
        m = _CHECKBOX_ROW_RE.match(line)
        if m and m.group(2) == '[ ]':
            key = _carried_tick_key(m.group(4))
            if budget.get(key, 0) > 0:
                budget[key] -= 1
                line = f"{m.group(1)}[x]{m.group(3)}{m.group(4)}"
        out.append(line)
    return _join_preserving_newline(out, new_content)


def _find_checkbox_row(content: str, old_substr: str, section_label: str):
    """Resolve exactly one substring-matched checkbox or raise _UpdateError.
    The rewrite and rationale guard share this resolution of the current row text."""
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
    """Split a legacy details wrapper into (head, inner, tail).
    Without a wrapper return (None, content, None); append inside legacy wrappers."""
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


def _render_note(note: str, leading_ws: str) -> tuple[str, list[str]]:
    """Return bullet text and content-column continuations, dropping blank lines.
    Rendering and replay matching share this form."""
    parts = [ln for ln in note.splitlines() if ln.strip()]
    if not parts:
        parts = ['']
    return parts[0], [f"{leading_ws}  {ln}" for ln in parts[1:]]


def _append_progress_note(
    content: str, note: str, timestamp: str, phase_label: str | None,
    reserved_marker_ok: bool = False,
) -> str:
    """Append a timestamped note at the end of its Progress phase block.
    Use a flat trailing bullet if the phase is missing; _render_note handles continuations.
    The template's Setup seed is separate and precedes its extension checkbox.
    Screen all caller text for reserved markers. Only validated producer rows opt out;
    embedded caller operands must be screened before those rows are composed."""
    if not reserved_marker_ok:
        _owner = _reserved_checkpoint_marker_owner(note)
        if _owner:
            raise _reserved_marker_error("the note text", _owner)
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
        bullet_text, cont = _render_note(note, '')
        body = [f"- {timestamp} — {bullet_text}"] + cont
        return prefix + '\n'.join(body) + '\n'
    # Block end: the next top-level phase row, else end of section. Indented
    # sub-items and indented note continuation lines never match, so a column-0
    # checkbox-shaped note line no longer splits the block.
    end = next(
        (j for j in range(start + 1, len(lines))
         if _TOP_LEVEL_CHECKBOX_RE.match(lines[j])),
        len(lines),
    )
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    bullet_text, cont = _render_note(note, '  ')
    new_lines = (
        lines[:end] + [f"  - {timestamp} — {bullet_text}"] + cont + lines[end:]
    )
    return _join_preserving_newline(new_lines, content)


# Reproduction follows recorded content classification, not the initial bug label.
# Reconcile its row and supersede its classification note before Phase 2.
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
    """Reconcile the bug-only row without duplicating or deleting ticked evidence.
    For bugs, insert under Implement or raise if its anchor is missing.
    For non-bugs, remove only an unticked row; no anchor is needed."""
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
    """Insert missing managed rows after their nearest declared predecessor in-phase,
    or directly under the phase anchor. Existing rows never move or duplicate;
    warn when one is outside its phase. Notes cannot anchor inserts.
    Repair a missing Review anchor; warn/skip other absent phase anchors."""
    lines = content.split('\n')
    managed = tuple(_managed_progress_rows())
    for idx, (phase, text, substr) in enumerate(managed):
        anchor = next(
            (
                i for i, ln in enumerate(lines)
                if (m := _TOP_LEVEL_CHECKBOX_RE.match(ln))
                and phase.lower() in m.group(2).lower()
            ),
            None,
        )
        # The phase block spans from just after the anchor to the next top-level row.
        block_end = next(
            (j for j in range(anchor + 1, len(lines))
             if _TOP_LEVEL_CHECKBOX_RE.match(lines[j])),
            len(lines),
        ) if anchor is not None else None
        row_matches = [
            li for li, ln in enumerate(lines)
            if (m := _CHECKBOX_ROW_RE.match(ln)) and substr.lower() in m.group(4).lower()
        ]
        if anchor is not None and any(anchor < li < block_end for li in row_matches):
            continue  # present in its own block, any tick state → idempotent no-op
        if row_matches:
            # The row is present but stranded outside its phase block (issue #22's
            # no-move contract leaves it there); surface it, or a maintainer cannot
            # tell the deliberate no-move from a repair that silently failed.
            sys.stderr.write(
                f"workpad.py update: NOTE: managed '{substr}' row found outside its "
                f"'**{phase}**' block — left in place (no-move contract), not "
                f"repaired into **{phase}**.\n")
            continue
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
        # The phase block spans from just after the anchor to the next top-level
        # row, so a predecessor search never reaches another phase's rows.
        block_end = next(
            (j for j in range(anchor + 1, len(lines))
             if _TOP_LEVEL_CHECKBOX_RE.match(lines[j])),
            len(lines),
        )
        # Land after the nearest present declared predecessor inside this block
        # (first occurrence in section order), else directly under the anchor.
        # Scan predecessors nearest-declared first, so the first present one wins.
        insert_at = anchor + 1
        for pphase, _ptext, psubstr in reversed(managed[:idx]):
            if pphase != phase:
                continue
            pos = next(
                (li for li in range(anchor + 1, block_end)
                 if (m := _CHECKBOX_ROW_RE.match(lines[li]))
                 and psubstr.lower() in m.group(4).lower()),
                None,
            )
            if pos is not None:
                insert_at = pos + 1
                break
        lines = lines[:insert_at] + [f'  - [ ] {text}'] + lines[insert_at:]
    return _join_preserving_newline(lines, content)


def _remove_classification_notes(content: str) -> str:
    """Drop every existing `classification: ` note bullet from ## Progress content,
    so a fresh record supersedes it — the workpad carries exactly one at all times
    (issue #449). Read-only otherwise; preserves the section's trailing newline."""
    kept = [ln for ln in content.split('\n')
            if not _CLASSIFICATION_NOTE_RE.match(ln)]
    return _join_preserving_newline(kept, content)


# Reflection kind -> (glyph, label, subsection). The helper owns rendering.
# Empty labels avoid repeating a heading that already identifies the kind.
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
    """Split the reflection-section body into ordered blocks (the `<details>` inner
    body on a legacy workpad, the un-wrapped section body on a new one).

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


def _place_bullet_in_blocks(blocks: list[list], target_heading: str,
                            bullet: str) -> None:
    """Append `bullet` (a fully-rendered `- …` line) under the `target_heading`
    sub-section of `blocks`, mutating `blocks` in place. Reuses the existing
    sub-section when present; otherwise inserts a new one in canonical order (a
    None-heading preamble always stays first; an unknown `### ` heading sorts last,
    so it is never reordered above a known one). Shared by `_insert_reflection_bullet`
    (which composes the bullet from a kind) and `_resolve_doc_reflection` (which moves
    an already-rendered bullet, glyph intact), so both place bullets identically."""
    for blk in blocks:
        if blk[0] == target_heading:
            while blk[1] and not blk[1][-1].strip():
                blk[1].pop()
            blk[1].append(bullet)
            return

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


def _insert_reflection_bullet(inner: str, kind: str, text: str) -> str:
    """Append under the kind's canonical heading, creating it in declared order.
    Preserve legacy unkinded bullets as an untouched leading preamble."""
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
    _place_bullet_in_blocks(blocks, target_heading, bullet)
    return _render_reflection_blocks(blocks)


def _append_reflection(content: str, kind: str, text: str) -> str:
    """Insert a grouped reflection bullet into the section. New workpads write the
    section un-wrapped, so the bullet is grouped in place. A legacy workpad created
    before the rename still carries the old `<details>` collapse, so this stays
    `<details>`-aware: it reuses _split_details/_rewrap_details to insert *inside*
    that block (before `</details>`), keeping the collapsible region intact."""
    head, inner, tail = _split_details(content)
    new_inner = _insert_reflection_bullet(inner, kind, text)
    if head is None:
        return new_inner
    return _rewrap_details(head, new_inner, tail)


# issue #508 — the append boundary the idempotent-replay check reads a resolved
# bullet's evidence back from: change it and the replay no-op stops recognizing an
# already-resolved bullet and re-resolves (or duplicates) it. The move and
# glyph-retention contract lives on `_resolve_doc_reflection` below.
_DOC_RESOLUTION_MARKER = ' — ✅ resolved: '


def _resolve_doc_reflection(content: str, target: str, evidence: str) -> str:
    """Move the unique actionable target to Notes with evidence, retaining its glyph.
    Matching resolved evidence is a replay. Invalid operands, ambiguous/non-actionable
    targets or conflicting evidence raise _UpdateError before any PATCH."""
    target = target.strip()
    evidence = evidence.strip()
    if not target:
        raise _UpdateError(
            "--resolve-doc-reflection: a non-empty target is required. No PATCH was made.")
    if not evidence:
        raise _UpdateError(
            "--resolve-doc-reflection: a non-empty completion evidence is required (an "
            "obligation with no checked completion evidence stays actionable). No PATCH "
            "was made.")
    if not _is_single_line(target) or not _is_single_line(evidence):
        raise _UpdateError(
            "--resolve-doc-reflection: target and evidence must each be a single line (a "
            "line boundary would split the bullet). No PATCH was made.")
    head, inner, tail = _split_details(content)
    blocks = _parse_reflection_blocks(inner)
    action_heading = _SUBSECTION_HEADINGS['action']
    notes_heading = _SUBSECTION_HEADINGS['notes']
    matches = [(bi, li)
               for bi, (_heading, lines) in enumerate(blocks)
               for li, ln in enumerate(lines)
               if ln.lstrip().startswith(('- ', '* ')) and target in ln]
    if len(matches) == 0:
        raise _UpdateError(
            f"--resolve-doc-reflection: no reflection bullet matched target {target!r}; no "
            "resolution applied and no other reflection changed. No PATCH was made.")
    if len(matches) > 1:
        raise _UpdateError(
            f"--resolve-doc-reflection: target {target!r} matched {len(matches)} reflection "
            "bullets; refusing an ambiguous resolution rather than changing the wrong one. "
            "No PATCH was made.")
    bi, li = matches[0]
    bullet = blocks[bi][1][li]
    if _DOC_RESOLUTION_MARKER in bullet:
        _base, _sep, existing = bullet.partition(_DOC_RESOLUTION_MARKER)
        if existing == evidence and blocks[bi][0] == notes_heading:
            return content  # idempotent replay of the same resolution
        raise _UpdateError(
            f"--resolve-doc-reflection: the bullet matching {target!r} already carries a "
            "resolution marker; refusing to overwrite resolution history. No PATCH was "
            "made.")
    if blocks[bi][0] != action_heading:
        raise _UpdateError(
            f"--resolve-doc-reflection: the bullet matching {target!r} is not an actionable "
            f"reflection under {action_heading!r}; only an unresolved obligation there can be "
            "resolved. No PATCH was made.")
    resolved = bullet + _DOC_RESOLUTION_MARKER + evidence
    del blocks[bi][1][li]
    if (blocks[bi][0] in _SUBSECTION_HEADING_ORDER
            and not any(ln.strip() for ln in blocks[bi][1])):
        del blocks[bi]
    _place_bullet_in_blocks(blocks, notes_heading, resolved)
    new_inner = _render_reflection_blocks(blocks)
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
    """Read a replacement as UTF-8 bytes and normalize LF.
    Read/decode failures raise structural _UpdateError before any PATCH."""
    try:
        raw = Path(path).read_bytes()
    except OSError as e:
        raise _UpdateError(f"{flag}: could not read {path!r}: {e}")
    return _canonicalize_body(_decode_utf8(raw, flag, path))


def _read_file_payload(path: str, flag: str, thing: str) -> str:
    """Read file/stdin bytes as UTF-8/LF without shell interpolation.
    Read/decode failures or blank payloads raise _UpdateError before any PATCH."""
    try:
        if path == '-':
            raw = sys.stdin.buffer.read()
        else:
            raw = Path(path).read_bytes()
    except OSError as e:
        raise _UpdateError(f"{flag}: could not read {path!r}: {e}")
    text = _canonicalize_body(_decode_utf8(raw, flag, path))
    if not text.strip():
        raise _UpdateError(
            f"{flag}: payload is empty or whitespace-only; a "
            f"{thing} bullet must carry text")
    return text


def _multi_file_payloads(args, attr, cache_attr, flag, thing) -> list:
    """Read repeated file payloads in argument order, caching only a successful list.
    Mutation and buffering share the cache; reject repeated stdin before consuming it."""
    paths = getattr(args, attr, None)
    if not paths:
        return []
    cached = getattr(args, cache_attr, None)
    if cached is None:
        stdin_count = paths.count('-')
        if stdin_count > 1:
            raise _UpdateError(
                f"{flag}: the stdin form '-' may be passed at most once per flag "
                f"(stdin can only be read once); it was passed {stdin_count} times")
        cached = [_read_file_payload(p, flag, thing) for p in paths]
        setattr(args, cache_attr, cached)
    return cached


def _reflection_file_payloads(args) -> list:
    """`--reflection-file`'s payloads, one per path (issue #2076). See
    `_multi_file_payloads` for the memoization and single-use-`-` contract."""
    return _multi_file_payloads(
        args, 'reflection_file', '_reflection_file_payload_cache',
        '--reflection-file', 'reflection')


def _note_file_payloads(args) -> list:
    """`--note-file`'s payloads, one per path (issue #2076) — the note twin of
    `_reflection_file_payloads`. See `_multi_file_payloads` for the contract."""
    return _multi_file_payloads(
        args, 'note_file', '_note_file_payload_cache', '--note-file', 'note')


def _deferred_filed_file_values(args) -> list:
    """Read literal filed-marker values from a file/stdin, one stripped nonblank line
    each. Memoize so replay/buffering can reuse stdin without shell interpolation."""
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
    """A volatile row-resolution miss inside a present section.
    Separate from _UpdateError: collect misses, persist other mutations, then fail."""


def _report_failed_ticks(failed_ticks, preamble):
    """Report all tick misses with a persistence-specific preamble.
    Callers must distinguish whole-call retries from reticking after a landed PATCH."""
    sys.stderr.write(f"workpad.py update: {preamble}:\n")
    for ft in failed_ticks:
        sys.stderr.write(f"  - {ft}\n")


# Buffer failed writes' append-only notes/reflections under ignored .prflow/tmp.
# Replay on the next update; do not buffer transient Status or tick mutations.

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


# Replay identity is exact rendered-bullet equality in the writer's section.
# Containment would falsely authorize buffer deletion and lose the sole copy.
# Notes include their rendered continuations; reflections use taxonomy renderings.
# Unknown/legacy shapes favor re-append: a visible duplicate is recoverable.


def _note_already_rendered(progress_content: "str | None", note: str) -> bool:
    """True when `note` is already present in the resolved `## Progress` content
    as a rendered note bullet — `_PROGRESS_BULLET_RE`'s captured text equal to the
    note's first non-blank line, with a multi-line note's continuation lines
    matching the rendered form (`_render_note`) under the matched bullet's own
    leading whitespace, whether the bullet sits nested under a phase or flat at
    the section end. None content (section absent or duplicated) reads as
    not-present."""
    if progress_content is None:
        return False
    lines = progress_content.split('\n')
    for i, line in enumerate(lines):
        m = _PROGRESS_BULLET_RE.match(line)
        if m is None:
            continue
        leading_ws = line[:len(line) - len(line.lstrip())]
        bullet_text, cont = _render_note(note, leading_ws)
        if m.group(1) != bullet_text:
            continue
        if lines[i + 1:i + 1 + len(cont)] == cont:
            return True
    return False


def _reflection_already_rendered(
    reflection_content: "str | None", text: str
) -> bool:
    """True when `text` is already present in the resolved reflection-section
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
    """Fold buffered content into args, deduplicating against exact live bullets,
    this call's inline content, and earlier buffered items in the same pass.
    Fold only into existing target sections. Return True only when every item is
    accounted for; otherwise retain the buffer for a later healthy body.
    Reflections replay under the current call's kind to preserve their text."""
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
    _reflections = _single_reflection_content(_sections)
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
    reflections_replayable = (
        f'## {_REFLECTION_HEADING}' in body
        or f'## {_REFLECTION_HEADING_SUPERSEDED}' in body
    )
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


_WORKPAD_ID_CACHE_DIRNAME = 'workpad-id-cache'


def _workpad_id_cache_path(issue, marker) -> Path:
    """Return the ignored repo-root cache path keyed by issue and effective marker."""
    root = _repo_root() or str(Path.cwd())
    key = f'{issue}-{hashlib.sha1(marker.encode("utf-8")).hexdigest()[:16]}'
    return (Path(root) / '.prflow' / 'tmp' / _WORKPAD_ID_CACHE_DIRNAME
            / f'{key}.json')


def _read_workpad_id_cache(issue, marker):
    """Return the cached comment id for (issue, marker), or None on any degraded
    shape — absent/empty/truncated/non-JSON/wrong-typed. Best-effort: a read
    failure never raises and never changes the update's outcome (AC: cache trouble
    never changes an update's outcome), so the caller falls back to a full scan."""
    try:
        raw = _workpad_id_cache_path(issue, marker).read_text(encoding='utf-8')
    # ValueError covers UnicodeDecodeError from an invalid-UTF-8 cache file; without
    # it a corrupted cache crashes `update` instead of missing to a scan.
    except (OSError, ValueError):
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    cid = data.get('comment_id')
    # Accept only an int (or an int-valued string) comment id; anything else is a
    # wrong-typed cache and misses to a scan.
    if isinstance(cid, bool):
        return None
    if isinstance(cid, int):
        return cid
    if isinstance(cid, str) and cid.strip().isdigit():
        return int(cid.strip())
    return None


def _write_workpad_id_cache(issue, marker, comment_id, repo) -> None:
    """Record the resolved comment id for (issue, marker), atomically. Best-effort:
    a write failure is swallowed and never changes the update's exit code — the id
    is re-derived by scanning next time. `repo` (from the resolved comment's
    issue_url) is stored for diagnostics only; read-side scoping is done by the
    verification fetch, never by this value."""
    path = _workpad_id_cache_path(issue, marker)
    record = {'comment_id': comment_id, 'issue': issue,
              'marker': marker, 'repo': repo}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f'{path.name}.tmp')
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
        os.replace(tmp, path)
    except OSError:
        pass


def _comment_body_channel(comment) -> str:
    """Read the exact stored body through one scan/cache seam.
    Avoid --jq .body's appended newline so repeated PATCHes cannot grow the body."""
    return comment.get('body') or ''


def _issue_url_names_issue(issue_url, issue) -> bool:
    """True when `issue_url`'s trailing path segment is exactly `issue`. Fails
    closed on a non-string / absent / null / wrong-typed value, so only a real
    match trusts a cached id."""
    if not isinstance(issue_url, str):
        return False
    return issue_url.rstrip('/').rsplit('/', 1)[-1] == str(issue)


def _verify_cached_comment(comment_id, issue, marker):
    """Return a direct-fetch object only when its marker and issue_url match.
    Any failed read or invalid shape is a cache miss; the caller then scans.
    Use gh's repository placeholders without a separate repo lookup."""
    try:
        r = _run([
            GH, 'api',
            f'repos/{{owner}}/{{repo}}/issues/comments/{comment_id}',
        ])
    except (subprocess.CalledProcessError, OSError):
        return None
    try:
        comment = json.loads(r.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(comment, dict):
        return None
    # Canonicalize before the marker test AND before returning, so the caller reads
    # an LF-only body (issue #349).
    comment['body'] = _canonicalize_body(comment.get('body') or '')
    if not comment['body'].startswith(_marker_variants(marker)):
        return None
    if not _issue_url_names_issue(comment.get('issue_url'), issue):
        return None
    return comment


def _repo_from_issue_url(issue_url):
    """The `owner/repo` slug parsed from a comment's issue_url, for cache
    diagnostics only; None when it cannot be parsed."""
    if not isinstance(issue_url, str):
        return None
    m = re.search(r'/repos/([^/]+/[^/]+)/issues/', issue_url)
    return m.group(1) if m else None


# Stopped-run note block markers (issue #2060) — a pinned COUPLED copy of scripts/pr-note-block.py's
# markers+transform: workpad.py must NOT import that helper (its import edges are locked to
# section_parse.py for the Stop-hook closure, #458/#583), and lib/test/run.sh pins these byte-identical.
_STOPPED_NOTE_START = "<!-- prflow:stopped-run-note-start -->"
_STOPPED_NOTE_END = "<!-- prflow:stopped-run-note-end -->"


def _strip_stopped_note_block(body):
    """Return *body* with every stopped-run note block removed (twin of pr-note-block.py's)."""
    lines = body.split("\n")
    out = []
    i = 0
    n = len(lines)
    while i < n:
        if lines[i] == _STOPPED_NOTE_START:
            j = i + 1
            while j < n and lines[j] != _STOPPED_NOTE_END:
                j += 1
            if j < n:
                i = j + 1
                if i < n and lines[i] == "":
                    i += 1
                continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def _add_stopped_note_block(body, note):
    """Prepend a fresh stopped-run note block carrying *note*, replacing any already present."""
    stripped = _strip_stopped_note_block(body)
    safe = note.replace("-->", "--&gt;")
    block = f"{_STOPPED_NOTE_START}\n{safe}\n{_STOPPED_NOTE_END}"
    return block + "\n\n" + stripped if stripped else block


def _resolve_open_pr_for_issue(issue):
    """Return the newest OPEN PR number closing *issue*, or None (issue #2060).

    A pinned parallel copy of scripts/resolve-issue-pr.py's selection (which workpad.py cannot
    import, per the note above); both pick the newest open PR whose closingIssuesReferences
    contains the issue, never a workpad Branch-line parse."""
    try:
        r = _run([GH, 'pr', 'list', '--search', f'{issue} in:body', '--state', 'open',
                  '--limit', '100', '--json', 'number,closingIssuesReferences,createdAt'])
    except (subprocess.CalledProcessError, OSError):
        return None
    try:
        prs = json.loads(r.stdout or "[]")
    except json.JSONDecodeError:
        return None
    if not isinstance(prs, list):
        return None
    try:
        want = int(issue)
    except (TypeError, ValueError):
        return None
    closing = [p for p in prs if isinstance(p, dict)
               and any(isinstance(c, dict) and c.get("number") == want
                       for c in (p.get("closingIssuesReferences") or []))]
    if not closing:
        return None
    closing.sort(key=lambda p: p.get("createdAt") or "")
    return closing[-1].get("number")


_PR_LINK_URL_RE = re.compile(r'/pull/(\d+)')
_PR_LINK_HASH_RE = re.compile(r'#(\d+)')


def _pr_number_from_link(value):
    """Return the PR number a `--pr-link` value names, or None (issue #252).

    The `/pull/<digits>` URL segment is the PR's own identity, so it wins over a
    `#<digits>` in the link text; None (neither present) makes the caller fall
    back to `_resolve_open_pr_for_issue`."""
    if not value:
        return None
    m = _PR_LINK_URL_RE.search(value)
    if m is None:
        m = _PR_LINK_HASH_RE.search(value)
    return int(m.group(1)) if m else None


# ── The workpad `**PR:**` line fallback (issue #626) ─────────────────────────
# A pinned parallel copy of scripts/resolve-issue-pr.py's same-named pieces (this module
# cannot import it, per `_resolve_open_pr_for_issue`'s note); both read the PR line the
# same way and both accept its number only after a REST read shows the PR open.
_PR_LINE_VALUE_RE = re.compile(r'^\*\*PR:\*\*[^\S\n]*(.*)$', re.MULTILINE)


def _pr_number_from_workpad_body(body):
    """Return (number, cause) for the PR the workpad's `**PR:**` line names."""
    m = _PR_LINE_VALUE_RE.search(body or '')
    if m is None:
        return None, 'the workpad carries no **PR:** line'
    num = _pr_number_from_link(m.group(1))
    if num is None:
        return None, 'the workpad **PR:** line names no PR number'
    return num, ''


def _resolve_pr_for_mirror(issue, body):
    """Prefer a PR closing the issue, else the open PR named by the workpad.
    Return (number, cause), with one miss cause for the caller's breadcrumb."""
    pr = _resolve_open_pr_for_issue(issue)
    if pr:
        return pr, ''
    pr, cause = _pr_number_from_workpad_body(body)
    if pr is None:
        return None, cause
    try:
        r = _run([GH, 'api', f'repos/{{owner}}/{{repo}}/pulls/{pr}', '--jq', '.state'])
    except (subprocess.CalledProcessError, OSError):
        return None, f'the workpad-line PR #{pr} could not be read'
    state = (r.stdout or '').strip().lower()
    # An unreadable state is a failed read, never a not-open claim this code did not observe.
    if not state:
        return None, f'the workpad-line PR #{pr} could not be read'
    if state != 'open':
        return None, f'the workpad-line PR #{pr} is not open'
    return pr, ''


def _mirror_stopped_note_to_pr(issue, note_text, body=None):
    """Best-effort: add a stopped-run note block to the issue's open PR body (issue #2060).

    A deliberate best-effort absorber: it runs AFTER the workpad PATCH has landed and must
    never change that update's own outcome, so every failure — no PR resolved, a gh read/
    PATCH error — is swallowed with a specific breadcrumb rather than propagated. `body` is
    the patched workpad body the caller already holds; it feeds the `**PR:**` line fallback
    (issue #626) and costs no extra read."""
    try:
        pr, _cause = _resolve_pr_for_mirror(issue, body)
        if not pr:
            sys.stderr.write(
                f"workpad.py update: no open PR resolved for issue #{issue} "
                f"({_cause}); stopped-run note not mirrored to a PR\n")
            return
        read = _run([GH, 'api', f'repos/{{owner}}/{{repo}}/pulls/{pr}', '--jq', '.body'])
        body = read.stdout
        if not body:
            sys.stderr.write(
                f"workpad.py update: PR #{pr} body empty/unreadable; "
                f"stopped-run note not mirrored\n")
            return
        new_body = _add_stopped_note_block(body, note_text)
        tmp = _stage_body_bytes(new_body)
        try:
            _run([GH, 'api', '-X', 'PATCH',
                  f'repos/{{owner}}/{{repo}}/pulls/{pr}',
                  '-F', f'body=@{tmp}', '--jq', '.number'])
        finally:
            Path(tmp).unlink(missing_ok=True)
    except Exception as exc:  # intentional best-effort absorber (see docstring)
        sys.stderr.write(
            f"workpad.py update: best-effort stopped-run note mirror to the PR failed "
            f"({exc.__class__.__name__}); the workpad update itself is unaffected\n")


def _stopped_note_text_for_mirror(args, own_notes, own_reflections):
    """Return the note text to mirror onto the PR for a terminal stop, else None (issue #2060).

    Exactly three terminal-stop signals write the block: a ``--status Failed`` and a ``--status
    Cancelled`` update (the stall backstop's run-died ``--note``), and a ``--reflection-kind
    blocked`` write (the Blocked reflection text — a reflection kind, not a status). A
    ``Complete`` terminal — and every other status/kind, or an empty payload — writes none."""
    if args.status and _strip_status_glyph(args.status).strip().lower() in ("failed", "cancelled"):
        text = "\n".join(n for n in own_notes if n).strip()
        return text or None
    if (args.reflection_kind or "").strip().lower() == "blocked":
        text = "\n".join(r for r in own_reflections if r).strip()
        return text or None
    return None


def _status_labels_enabled():
    """Read the in-process config: only boolean false or string "false" disables.
    Missing, unreadable or other-shaped values preserve the enabled default."""
    _root = _repo_root()
    base = _root if _root is not None else str(Path.cwd())
    config_file = Path(_resolve_state_dir(base)) / 'config.json'
    try:
        with config_file.open(encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return True
    except (OSError, ValueError):
        # Unreadable/malformed config is indistinguishable from "not configured";
        # both leave the feature enabled (the documented default direction).
        return True
    section = data.get('status_labels') if isinstance(data, dict) else None
    if not isinstance(section, dict):
        return True
    value = section.get('enabled', True)
    # `value is False` matches only the actual JSON boolean false — never a
    # number 0 (0 is not False), so a `0` correctly leaves the feature enabled.
    return not (value is False or value == 'false')


def _list_issue_labels(number):
    """Return the label-name strings currently on issue/PR `number` (issue #2117).

    Parses the labels-endpoint response in Python so a malformed shape degrades
    to an empty list rather than a bad managed-label decision: a non-array
    response, an entry with no string `name`, all resolve to "" contributing
    nothing. Raises on a gh/JSON failure — the caller absorbs it best-effort."""
    r = _run([GH, 'api', f'repos/{{owner}}/{{repo}}/issues/{number}/labels'])
    data = json.loads(r.stdout or '[]')
    if not isinstance(data, list):
        return []
    names = []
    for item in data:
        if isinstance(item, dict):
            name = item.get('name')
            if isinstance(name, str) and name:
                names.append(name)
    return names


def _add_managed_label(number, target, label_defined):
    """Add `target` to issue/PR `number`, creating its repo definition first when
    the add is refused because the label is undefined (issue #2117).

    Returns the updated `label_defined` flag so a caller reconciling both the
    issue and its PR makes at most ONE creation request across them. Each request
    is isolated: a failure breadcrumbs and returns rather than propagating."""
    def _post_add():
        _run([GH, 'api', '-X', 'POST',
              f'repos/{{owner}}/{{repo}}/issues/{number}/labels',
              '-f', f'labels[]={target}'])
    try:
        _post_add()
        return label_defined
    except Exception:
        # Adding a label the repo does not define is refused. Create the label
        # definition (once per run) and retry the add exactly once. A repo that
        # already defines the label never reaches here — the add above succeeds.
        if not label_defined:
            try:
                create_cmd = [GH, 'api', '-X', 'POST', 'repos/{owner}/{repo}/labels',
                              '-f', f'name={target}',
                              '-f', 'description=PRFlow run status (issue #2117)']
                color = _MANAGED_LABEL_COLORS.get(target)
                if color:
                    create_cmd += ['-f', f'color={color}']
                _run(create_cmd)
            except Exception as exc:
                # An "already exists" race or a genuine create failure: retry the
                # add regardless — the definition may now exist.
                sys.stderr.write(
                    f"workpad.py update: could not create managed label "
                    f"{target!r} ({exc.__class__.__name__}); retrying the add\n")
            label_defined = True
        try:
            _post_add()
        except Exception as exc:
            sys.stderr.write(
                f"workpad.py update: could not add managed label {target!r} to "
                f"#{number} ({exc.__class__.__name__}); status label not applied\n")
        return label_defined


def _reconcile_managed_label(number, target, label_defined):
    """Reconcile issue/PR `number`'s managed labels to exactly `target` (issue
    #2117). Removes every managed label that is not the target, then adds the
    target when missing. Best-effort PER REQUEST — a 404 removing a label that is
    not applied (the ordinary case for two of the three managed labels) must not
    abort the add that follows, so each call is caught on its own, never one
    catch around the whole reconciliation. Returns the updated `label_defined`."""
    try:
        current = _list_issue_labels(number)
    except Exception as exc:
        sys.stderr.write(
            f"workpad.py update: could not list labels on #{number} "
            f"({exc.__class__.__name__}); status label not reconciled there\n")
        return label_defined
    managed = [n for n in current if n in _MANAGED_STATUS_LABELS]
    # Already correct — the target present and nothing else managed: no write.
    if managed == [target]:
        return label_defined
    for lbl in managed:
        if lbl != target:
            try:
                _run([GH, 'api', '-X', 'DELETE',
                      f'repos/{{owner}}/{{repo}}/issues/{number}/labels/{lbl}'])
            except Exception as exc:
                # Per-request isolation: a removal failure (a 404 when the label
                # is not applied, or any transient error) must NOT abort the add
                # that follows. Breadcrumb it — a stale managed label left behind
                # is the only degradation, never a changed update outcome.
                sys.stderr.write(
                    f"workpad.py update: could not remove managed label {lbl!r} "
                    f"from #{number} ({exc.__class__.__name__}); continuing\n")
    if target not in current:
        label_defined = _add_managed_label(number, target, label_defined)
    return label_defined


def _mirror_status_labels(issue, status, *, pr_link=None, body=None):
    """Best-effort mirror after PATCH; failures never change the update outcome.
    No API requests when disabled. Status writes use the operand; PR-link-only
    writes read patched Status. Resolve PR from link, closing refs, then body."""
    try:
        if not _status_labels_enabled():
            return
        # An empty word (a --pr-link write on a body with no Status line) must NOT
        # reach the class map, which defaults an unknown word to 'interim' and
        # would mislabel the PR: skip and breadcrumb instead.
        word = status or _status_word_from_body(body or '')
        if not word:
            sys.stderr.write(
                f"workpad.py update: no Status word read from the workpad body "
                f"for issue #{issue}; status label not mirrored\n")
            return
        # Every class `_status_class` produces is a key here (it defaults to
        # 'interim'), so this subscript never misses in practice; a future
        # unmapped class raises KeyError into the absorber below rather than
        # silently mirroring no label.
        target = _STATUS_CLASS_TO_LABEL[_status_class(_status_glyph(word))]
        label_defined = _reconcile_managed_label(issue, target, False)
        # A link-named PR wins over the lookup: GitHub's closing-issue data can lag
        # right after PR creation, so `_resolve_open_pr_for_issue` can miss the PR
        # this write just linked.
        pr = _pr_number_from_link(pr_link)
        cause = ''
        if pr is None:
            pr, cause = _resolve_pr_for_mirror(issue, body)
        if not pr:
            sys.stderr.write(
                f"workpad.py update: no open PR resolved for issue #{issue} "
                f"({cause}); status label not mirrored to a PR\n")
            return
        _reconcile_managed_label(pr, target, label_defined)
    except Exception as exc:  # intentional best-effort absorber (see docstring)
        sys.stderr.write(
            f"workpad.py update: best-effort status-label mirror failed "
            f"({exc.__class__.__name__}); the workpad update itself is unaffected\n")


def _cmd_update_inner(args):
    # Resolve the workpad comment id AND its live body together. A cached id is
    # trusted only after a direct fetch verifies it; every miss falls back to the
    # shared paginated scan. Repository resolution rides `gh api`'s {owner}/{repo}
    # placeholders (gh fills them from the checkout at no API cost), so no
    # `gh repo view` call is made — and the scan reuses `_find_workpad_comment`,
    # which returns the whole comment object, so the id and body arrive in one
    # request and carry that helper's not-a-JSON-array guard.
    marker = _workpad_marker(args.marker)
    comment = None
    cached_id = _read_workpad_id_cache(args.issue, marker)
    if cached_id is not None:
        comment = _verify_cached_comment(cached_id, args.issue, marker)
    if comment is None:
        comment = _find_workpad_comment(
            'update id-lookup', '{owner}/{repo}', args.issue, marker)
    if comment is None:
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
    comment_id = comment['id']
    body = _comment_body_channel(comment)
    # Record the resolved id so the next call for this (issue, marker) can fetch it
    # directly. Best-effort: a cache-write failure never changes this call's outcome.
    # Skip the write on a verified cache hit (the id is unchanged) so this hot path —
    # called dozens of times per run — does not re-mkdir/re-write a byte-identical file.
    if cached_id is None or comment_id != cached_id:
        _write_workpad_id_cache(
            args.issue, marker, comment_id, _repo_from_issue_url(comment.get('issue_url')))

    # Compare live identity/Status with the hydration snapshot before mutation.
    # Exit 4 on mismatch; stale resets must not overwrite concurrent changes.
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
        # Capture every file payload for failure buffering, including file-only calls.
        # Memoized reads let mutation reuse stdin; invalid payloads still prevent PATCH.
        try:
            _own_reflections.extend(_reflection_file_payloads(args))
        except _UpdateError as e:
            sys.stderr.write(f"workpad.py update: {e}\n")
            sys.exit(1)
    if getattr(args, 'note_file', None):
        # A file-sourced note is buffered like an inline --note, and a repeated flag
        # preserves its payloads through a PATCH failure (issue #2076) — the twin of
        # the --reflection-file rescue above (issue #1813 mirrors #1214). The reads
        # are memoized, so `_apply_mutations` renders from the same text without
        # re-reading, which also keeps the `-`/stdin arm single-read.
        try:
            _own_notes.extend(_note_file_payloads(args))
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
        if replay.kind == 'satisfied-ticks':
            sys.stderr.write(
                "workpad.py update: tick replay — every requested row is "
                "already ticked; no Last updated refresh, no PATCH.\n"
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
    tmp_path = _stage_body_bytes(body)
    global _UPDATE_PATCH_LANDED
    try:
        r = _run([
            GH, 'api', '-X', 'PATCH',
            f'repos/{{owner}}/{{repo}}/issues/comments/{comment_id}',
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
        # `acs-remirror` sets `unbuffered_notes`: its note claims the criteria
        # replacement, which is not buffered, so a replay would claim it.
        _buf_path = _buffer_failed_change(
            comment_id, [] if getattr(args, 'unbuffered_notes', False) else _own_notes,
            _own_reflections, _own_kind)
        if _buf_path is not None:
            sys.stderr.write(
                f"workpad.py update: buffered this call's note/reflection content "
                f"to {_buf_path} for replay on the next successful update "
                f"(issue #1214).\n"
            )
        _fail('update patch', e)
    finally:
        tmp_path.unlink(missing_ok=True)
    # Headroom reading for the body this call PATCHed (issue #755). Written here —
    # after the `finally`, before anything else — so it reports on EVERY landed
    # PATCH including the volatile-tick-miss exit, and so a stderr write can never
    # raise inside the try above and mislabel a landed PATCH as a failed one. A call
    # that issued no PATCH (a replay, a refusal) reaches no line at all, so the line's
    # presence means a write landed.
    sys.stderr.write(_update_headroom_line(_byte_len(body)))
    # The PATCH succeeded: drop the buffer file ONLY when `_plan_buffer_replay`
    # reported that every buffered item is now accounted for (folded into this
    # body or already present). When a buffered item could not be folded — its
    # target section was absent from this (truncated/malformed) body — the buffer
    # is left intact so a later healthy body replays it, never dropping content
    # along with the file. Idempotency is guaranteed by the presence check, so a
    # retained-and-later-replayed item is replay-and-skip, never a duplicate.
    if _buffer_safe_to_clear:
        _clear_workpad_buffer(comment_id)
    # Best-effort mirror of a terminal stop to the issue's open PR (issue #2060). Placed
    # after the workpad PATCH has landed so a mirror failure cannot change this update's
    # own outcome; the helper swallows every failure internally.
    _mirror_text = _stopped_note_text_for_mirror(args, _own_notes, _own_reflections)
    if _mirror_text:
        _mirror_stopped_note_to_pr(args.issue, _mirror_text, body=body)
    # Mirror Status onto managed labels after the PATCH (issue #2117; --pr-link
    # trigger #252) so a label failure can't alter this update's outcome. Every
    # trigger passes the patched body: a --status-only write needs it for the
    # workpad `**PR:**` line fallback (issue #626), which is the only way the mirror
    # reaches a PR whose closing references do not list the issue.
    if args.status or args.pr_link:
        _mirror_status_labels(
            args.issue, args.status, pr_link=args.pr_link, body=body)
    # Issue #814: the patched body is echoed only under `--print-body`, or on the
    # volatile-tick-miss path below. This one statement is reached by BOTH the clean
    # return and the miss exit (the `failed_ticks` branch is evaluated after it), so
    # a flag-only condition here would also silence the miss path — which keeps its
    # echo deliberately, because the failure-isolation contract requires the caller
    # to re-resolve a section-scoped checkbox index before re-ticking and the body is
    # the row inventory that resolution reads.
    if args.print_body or failed_ticks:
        sys.stdout.write(r.stdout)

    # On successful PATCH, read Status from the response through the shared reader.
    # Distinguish empty response, missing Status and resolved value. Only exit-0
    # paths emit a success breadcrumb; tick-miss paths still need the read-back.
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
    # Compare the read-back once for both outcome paths. Warn on mismatch even
    # when ticks missed; the caller owns remediation after a successful PATCH.
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
    """Apply substring ticks before 1-based index ticks across all tick states.
    Absent requested sections raise _UpdateError; row misses accumulate in failed_ticks
    while remaining ticks apply. Reticking the same row is a satisfied replay."""
    if not substr_texts and not index_ns:
        return
    idx = _find_section(sections, section_name)
    if idx is None:
        raise _UpdateError(f"section '## {section_name}' not found")
    heading, content = sections[idx]
    for text in substr_texts:
        try:
            content, _ticked_now = _tick_checkbox(content, text, section_name)
        except _TickMatchError as e:
            failed_ticks.append(f"--tick-{flag_base} {text!r} — {e}")
    for n in index_ns:
        try:
            content, _ticked_now = _tick_checkbox_by_index(content, n, section_name)
        except _TickMatchError as e:
            failed_ticks.append(f"--tick-{flag_base}-n {n} — {e}")
    sections[idx] = (heading, content)


# The marker parse-acs.py appends to a post-merge criterion, and the byte-for-byte
# token the Phase 3.4 AC gate excludes ("a criterion whose checkbox line ends in
# `(post-merge)`"). The terminal Complete gate reuses the same exclusion so its
# hard-fail set matches the gate's blocking set exactly.
_POST_MERGE_MARKER = '(post-merge)'


def _is_single_line(text: str) -> bool:
    """Accept exactly text with no str.splitlines boundary, including trailing ones.
    Use the row parser's operation: checking only CR/LF misses other Unicode separators."""
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
            f"byte count, measured as UTF-8 bytes); shorten the workpad, or run "
            f"`workpad.py compact <issue>` to move its oldest unprotected bullets "
            f"into an overflow comment. No PATCH was made."
        )


# ── Compaction (issue #755) ──────────────────────────────────────────────────
# A workpad at the cap has no recovery inside `update`: the write is refused and
# its content is not buffered, so the run improvises — and the one run that did
# cut the tails off over-length bullets, unregistering the review-coverage record
# that lives in a bullet TAIL and blocking its own terminal gate. `compact` is
# that recovery. It is EXPLICIT, never automatic, and it moves WHOLE bullets: a
# partial line is precisely the failure being fixed.
_COMPACT_TARGET_BYTES = _COMMENT_BYTE_LIMIT - 8192

# What one compaction moves bullets down to; raising it toward the target makes every
# later write compact again.
_COMPACT_LOW_WATER_BYTES = _COMMENT_BYTE_LIMIT - 24576

# Held back from both the low watermark and the target for the accounting row
# appended AFTER the selection is fixed (its URL is unknown until the comment is
# written). The row is fixed prose, two integers and one comment URL, so no moved
# content can spend the reserve; it only makes the selection — and so the refusal —
# marginally conservative.
_COMPACT_ACCOUNTING_RESERVE = 512

# Overflow line 1 identifies overflow; line 2's workpad marker prevents triggers
# without matching the starts-with workpad reader. Line 3 copies live Status for
# fetch-pr-context's substring reader, which may select an old overflow after
# workpad recreation. Omit Reflections headings to avoid misattributed friction.
_COMPACT_OVERFLOW_MARKER = '<!-- prflow:workpad-overflow -->'

# A `### ℹ️ Notes` reflection bullet: any list item, since the reflection writer
# renders a kind glyph rather than the Progress timestamp prefix.
_COMPACT_BULLET_RE = re.compile(r'^[ \t]*[-*][ \t]+')
# A checkbox row (a Plan row, an acceptance-criteria row, a phase row). Never a
# candidate, and never absorbed into one as a continuation line.
_COMPACT_CHECKBOX_RE = re.compile(r'^[ \t]*[-*][ \t]+\[[ xX]\]')


def _compact_indent(line: str) -> int:
    """Leading-whitespace width of `line`, a tab counting as one column. Only ever
    compared against another line's, never rendered."""
    return len(line) - len(line.lstrip(' \t'))


def _compact_section_bounds(lines, start):
    """`(start, stop)` — `start` through the line before the next `## ` heading."""
    for j in range(start, len(lines)):
        if lines[j].startswith('## '):
            return start, j
    return start, len(lines)


def _compact_heading_hits(lines, name):
    """Indices of the `## {name}` headings, matched exactly as `_find_section`
    matches (case-insensitively over the stripped heading line)."""
    target = f'## {name}'.lower()
    return [i for i, ln in enumerate(lines)
            if _SECTION_RE.match(ln) and ln.strip().lower() == target]


def _compact_progress_region(lines):
    """`(start, stop)` bounding the ONE `## Progress` section's content, or None.

    Exactly-one, the rule `_single_section_content` states: `_find_section` answers
    with the FIRST match, so a duplicated section would let this reader speak for
    half the body — and this reader DELETES lines and appends the accounting row."""
    hits = _compact_heading_hits(lines, 'Progress')
    if len(hits) != 1:
        return None
    return _compact_section_bounds(lines, hits[0] + 1)


def _compact_notes_region(lines):
    """Locate the sole Notes region in the sole reflection section, or None.
    Action/Improvement bullets feed retrospective friction and must not move.
    A legacy details closing tag ends the region."""
    section = None
    for name in (_REFLECTION_HEADING, _REFLECTION_HEADING_SUPERSEDED):
        hits = _compact_heading_hits(lines, name)
        if len(hits) == 1:
            section = _compact_section_bounds(lines, hits[0] + 1)
            break
        if hits:
            return None
    if section is None:
        return None
    heading = _SUBSECTION_HEADINGS['notes']
    hits = [i for i in range(*section) if lines[i].strip() == heading]
    if len(hits) != 1:
        return None
    start = hits[0] + 1
    for j in range(start, section[1]):
        if _SUBSECTION_HEADING_RE.match(lines[j]) or lines[j].strip() == '</details>':
            return start, j
    return start, section[1]


def _compact_bullets_in(lines, region, bullet_re):
    """Return whole (start, stop, text) bullets with their deeper nonblank continuations.
    Indentation, not a dash prefix, separates siblings from nested content."""
    out = []
    if region is None:
        return out
    start, stop = region
    i = start
    while i < stop:
        if bullet_re.match(lines[i]) is None or _COMPACT_CHECKBOX_RE.match(lines[i]):
            i += 1
            continue
        indent = _compact_indent(lines[i])
        j = i + 1
        while (j < stop
               and lines[j].strip()
               and _compact_indent(lines[j]) > indent
               and not lines[j].lstrip().startswith('#')):
            j += 1
        out.append((i, j, '\n'.join(lines[i:j])))
        i = j
    return out


def _compact_is_protected(text: str) -> bool:
    """True when a bullet carries a PRFlow marker anywhere in its text.

    Every machine-read workpad record is a marker inside a `## Progress` bullet and
    several are recognized only as that bullet's TAIL, so moving one unregisters the
    record. Both namespaces are protected: a legacy workpad's records carry the
    superseded spelling, and the readers still resolve it."""
    return _MARKER_NS_CURRENT in text or _MARKER_NS_SUPERSEDED in text


def _compact_status_line(body: str):
    """The workpad's EARLIEST `**Status:**` line, verbatim, or None.

    Matched with `_STATUS_VALUE_RE`, the pattern every Status reader shares, and
    earliest-first because `lib/fetch-pr-context.sh` — the reader the copy exists
    for — also takes the earliest one."""
    for line in body.split('\n'):
        if _STATUS_VALUE_RE.match(line):
            return line
    return None


def _compact_ceiling(nbytes, target=_COMPACT_TARGET_BYTES,
                     reserve=_COMPACT_ACCOUNTING_RESERVE):
    """The most a body of `nbytes` may be left holding, before its accounting row,
    when every movable bullet moves."""
    return min(nbytes, target) - reserve


def _compact_plan(body, target=_COMPACT_TARGET_BYTES, low=_COMPACT_LOW_WATER_BYTES,
                  reserve=_COMPACT_ACCOUNTING_RESERVE):
    """Select the fewest oldest unprotected bullets to reach low with accounting reserve.
    If candidates run out, accept all only below min(original size, target) minus reserve.
    Return (None, projected_bytes) when unreachable, or an empty selection if none move.
    Pure planning: no request or mutation."""
    lines = body.split('\n')
    candidates = (
        _compact_bullets_in(lines, _compact_progress_region(lines),
                            _PROGRESS_BULLET_RE)
        + _compact_bullets_in(lines, _compact_notes_region(lines),
                              _COMPACT_BULLET_RE))
    candidates.sort(key=lambda b: b[0])
    left = _byte_len(body)
    budget = _compact_ceiling(left, target, reserve)
    selected = []
    for first, stop, text in candidates:
        if left <= low - reserve:
            break
        if _compact_is_protected(text):
            continue
        selected.append((first, stop, text))
        # '\n'.join means each removed line costs its own bytes plus one separator,
        # exactly — so this arithmetic needs no re-encode of the whole body.
        left -= sum(_byte_len(lines[i]) + 1 for i in range(first, stop))
    if selected and left > budget:
        return None, left
    return selected, left


def _compose_overflow_comment(marker, status_line, selected):
    """The overflow comment body: the three fixed opening lines (see
    `_COMPACT_OVERFLOW_MARKER`), a blank line so markdown renders the list, then
    every moved bullet byte-for-byte with no substitution. `marker` is the RESOLVED
    workpad marker, so a consumer's custom marker is what the listeners decline."""
    parts = [_COMPACT_OVERFLOW_MARKER, marker, status_line, '']
    parts.extend(text for _, _, text in selected)
    return '\n'.join(parts) + '\n'


def _compose_overflow_append(comments, marker, status_line, selected):
    """`(comment, body)` — the newest overflow comment (highest integer `id`) and its
    body with line 3 refreshed to `status_line` and the moved bullets appended after
    its existing ones, or None when no comment has an integer `id` or the newest fails
    any reuse check below. Only the newest is considered: an older one stays
    byte-identical."""
    ids = [c for c in comments
           if isinstance(c.get('id'), int) and not isinstance(c.get('id'), bool)]
    if not ids:
        return None
    newest = max(ids, key=lambda c: c['id'])
    if not isinstance(newest.get('body'), str):
        return None
    lines = newest['body'].split('\n')
    if (not isinstance(newest.get('html_url'), str) or not newest['html_url']
            or len(lines) < 3 or lines[1] not in _marker_variants(marker)
            or not _STATUS_VALUE_RE.match(lines[2])):
        return None
    lines[2] = status_line
    head = '\n'.join(lines)
    if not head.endswith('\n'):
        head += '\n'
    body = head + '\n'.join(text for _, _, text in selected) + '\n'
    if _byte_len(body) > _COMMENT_BYTE_LIMIT:
        return None
    return newest, body


def _compact_accounting_note(moved, moved_bytes, url):
    """The one Progress row a compaction appends. Single line, so it renders as one
    bullet and a later compaction can move it like any other unprotected bullet."""
    return (f"Workpad compacted: moved {moved} bullet(s), {moved_bytes} UTF-8 "
            f"bytes, to overflow comment {url}")


def _update_headroom_line(nbytes: int) -> str:
    """The `workpad-bytes: <n>/65536` stderr line for a landed `update` PATCH.

    Past `_COMPACT_TARGET_BYTES` it carries a `WARNING: ` prefix and names the
    remedy; at or below it carries neither, so a run well short of the limit reads
    one plain measurement and nothing else."""
    if nbytes > _COMPACT_TARGET_BYTES:
        return (f"workpad.py update: WARNING: workpad-bytes: {nbytes}/"
                f"{_COMMENT_BYTE_LIMIT} — over the {_COMPACT_TARGET_BYTES}-byte "
                f"compaction target; run `workpad.py compact <issue>` to move the "
                f"oldest unprotected bullets into an overflow comment.\n")
    return f"workpad.py update: workpad-bytes: {nbytes}/{_COMMENT_BYTE_LIMIT}\n"


def cmd_compact(args):
    """Move oldest unprotected bullets to the newest usable overflow, else a new comment.
    Write overflow before PATCH so failures duplicate text rather than lose it.
    Exit 0: compacted or already low; 1: structural refusal; 2: clean absence;
    3: API/read/PATCH failure; 5: unreachable compaction. A post-overflow failure
    names the comment retaining the moved text."""
    marker = _workpad_marker(args.marker)
    repo = _repo_full(api_fail_code=3)
    c = _find_workpad_comment('compact', repo, args.issue, marker, api_fail_code=3)
    if c is None:
        sys.stderr.write(
            f"workpad.py compact: no workpad comment on issue #{args.issue} "
            f"(marker scan clean-absent); nothing to compact\n")
        sys.exit(2)
    if 'id' not in c:
        _fail('compact',
              f"workpad comment on issue #{args.issue} carries no id field "
              f"(malformed comments response); cannot compact", code=3)
    body = _comment_body_channel(c)
    nbytes = _byte_len(body)
    if nbytes <= _COMPACT_LOW_WATER_BYTES:
        sys.stdout.write(
            f"workpad-bytes: {nbytes}/{_COMMENT_BYTE_LIMIT}; at or below the "
            f"{_COMPACT_LOW_WATER_BYTES}-byte compaction low watermark — no comment "
            f"posted, no PATCH made\n")
        return
    # Everything that can refuse is decided BEFORE the comment is written, so a
    # refusal costs no comment and a written comment is always followed by a PATCH
    # attempt.
    status_line = _compact_status_line(body)
    if status_line is None:
        sys.stderr.write(
            "workpad.py compact: the workpad carries no `**Status:**` line to copy "
            "onto the overflow comment, which is what keeps a mis-selected read "
            "parseable; refusing. No comment posted, no PATCH made.\n")
        sys.exit(1)
    lines = body.split('\n')
    if _compact_progress_region(lines) is None:
        sys.stderr.write(
            "workpad.py compact: the workpad does not present exactly one "
            "`## Progress` section, so the accounting row has no home; refusing. "
            "No comment posted, no PATCH made.\n")
        sys.exit(1)
    selected, projected = _compact_plan(body)
    if selected == []:
        sys.stderr.write(
            f"workpad.py compact: cannot compact the {nbytes}-byte workpad — no "
            f"bullet is movable: every bullet carries a marker, is a checkbox row, "
            f"or sits outside `## Progress` and `{_SUBSECTION_HEADINGS['notes']}`. "
            f"No comment posted, no PATCH made.\n")
        sys.exit(5)
    if selected is None:
        sys.stderr.write(
            f"workpad.py compact: cannot compact — moving every movable bullet "
            f"still leaves {projected} bytes, over the "
            f"{_compact_ceiling(nbytes)}-byte ceiling (the smaller of the body's "
            f"{nbytes} bytes and {_COMPACT_TARGET_BYTES}, less the "
            f"{_COMPACT_ACCOUNTING_RESERVE}-byte accounting reserve). No comment "
            f"posted, no PATCH made.\n")
        sys.exit(5)
    overflow = _compose_overflow_comment(marker, status_line, selected)
    if _byte_len(overflow) > _COMMENT_BYTE_LIMIT:
        sys.stderr.write(
            f"workpad.py compact: cannot compact — the assembled overflow comment "
            f"would be {_byte_len(overflow)} "
            f"bytes, over GitHub's {_COMMENT_BYTE_LIMIT}-byte limit, and one "
            f"compaction posts one comment. No comment posted, no PATCH made.\n")
        sys.exit(5)
    dropped = {i for first, stop, _ in selected for i in range(first, stop)}
    kept = [ln for i, ln in enumerate(lines) if i not in dropped]
    kept_region = _compact_progress_region(kept)
    if kept_region is None:  # defensive: removing bullets cannot remove a heading
        sys.stderr.write(
            "workpad.py compact: the post-removal body no longer presents one "
            "`## Progress` section; refusing. No comment posted, no PATCH made.\n")
        sys.exit(1)
    moved_bytes = sum(_byte_len(text) for _, _, text in selected)

    reuse = _compose_overflow_append(
        _find_workpad_comment('compact', repo, args.issue, _COMPACT_OVERFLOW_MARKER,
                              api_fail_code=3, collect_all=True),
        marker, status_line, selected)
    url = None
    if reuse is not None:
        try:
            _patch_comment_body(repo, reuse[0]['id'], reuse[1])
            url = reuse[0]['html_url']
        except (_UpdateError, subprocess.CalledProcessError, OSError) as e:
            sys.stderr.write(
                f"workpad.py compact: appending to the overflow comment "
                f"{reuse[0]['html_url']} failed or may not have landed "
                f"({_gh_error_detail(e)}); posting a new overflow comment instead. "
                f"Check that comment for duplicated bullets.\n")
    if url is None:
        posted = _post_issue_comment('compact', args.issue, overflow, api_fail_code=3)
        url = next((ln.strip() for ln in reversed(posted.split('\n'))
                    if _COMMENT_URL_RE.search(ln.strip())), None)
        if url is None:
            # `gh issue comment` is documented to print the new comment's URL. Without
            # it the comment may already exist on the issue, so the workpad is left
            # byte-identical rather than PATCHed against a comment we cannot cite.
            sys.stderr.write(
                "workpad.py compact: gh printed no comment URL, so the overflow comment "
                "may or may not have been posted; the workpad is left byte-identical. "
                "Inspect the issue before retrying. Raw stdout:\n")
            sys.stderr.write(posted)
            sys.exit(3)

    first, stop = kept_region
    content = _append_progress_note(
        '\n'.join(kept[first:stop]),
        _compact_accounting_note(len(selected), moved_bytes, url),
        datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M:%S'),
        None)
    new_body = '\n'.join(kept[:first] + content.split('\n') + kept[stop:])
    try:
        _patch_comment_body(repo, c['id'], new_body)
    except (_UpdateError, subprocess.CalledProcessError, OSError) as e:
        sys.stderr.write(
            f"workpad.py compact: the overflow comment WAS written at {url}, but the "
            f"workpad PATCH failed or may not have landed ({_gh_error_detail(e)}); "
            f"every moved bullet is in that comment, so nothing is lost. Inspect the "
            f"workpad: if it is unchanged, re-run compact once the failure is "
            f"resolved, or remove the moved bullets from that comment.\n")
        sys.exit(3)
    sys.stdout.write(json.dumps({
        "issue": args.issue,
        "comment_id": c['id'],
        "overflow_comment": url,
        "moved_bullets": len(selected),
        "moved_bytes": moved_bytes,
        "bytes_before": nbytes,
        "bytes_after": _byte_len(new_body),
        "target": _COMPACT_LOW_WATER_BYTES,
    }) + "\n")


def _ends_with_post_merge(text: str) -> bool:
    """True when `text` carries the `(post-merge)` marker in TERMINAL position.
    Trailing whitespace is stripped first, so a stray space or newline can't mask
    the comparison (the anti-evasion the retag guard and `_unticked_rows` share)."""
    return text.rstrip().endswith(_POST_MERGE_MARKER)


def _pair_appends_post_merge(old: str, new: str, row_text: str) -> bool:
    """Detect NEW's terminal tag when neither OLD nor the resolved current row has it.
    Current-row inspection exempts text edits on already-tagged rows even when OLD
    omits the tag. The state backstop catches multi-pair shuttles this guard cannot."""
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
    """Return terminal-tag flags for every checkbox, including ticked rows.
    Retag accounting is wider than the terminal gate's unticked-only population."""
    return [
        _ends_with_post_merge(m.group(4))
        for line in content.splitlines()
        if (m := _CHECKBOX_ROW_RE.match(line))
    ]


def _net_adds_post_merge(pre: list[bool], post: list[bool]) -> bool:
    """Detect any row's False-to-True tag transition by stable checkbox position.
    Aggregate counts miss remove-one/add-one swaps. A changed row count is unknown
    and fails closed as a net add; multiline replacements are rejected upstream."""
    if len(pre) != len(post):
        return True
    return any(now and not before for before, now in zip(pre, post))


# Flight completion keys reference canonical repo-root records validated by
# the sibling check-completion-evidence module.
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
    """Lazily cache the sibling validator import; return None for standalone copies."""
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


# Local CI evidence uses a distinct completion-ci key with encoded JSON
# (head, tier, run URL, checks), validated offline by the sibling validator.
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


def _encode_ci_payload(record: dict, compress: bool = False) -> str:
    """Encode a CI-evidence record dict as a base64url-unpadded token, so the payload
    is a single whitespace-free `[^\\s]+` the marker grammar and the checkpoint key
    grammar (`[A-Za-z0-9._:-]+`, which includes `-` and `_`) both accept. `compress`
    zlib-compresses the JSON first; only the cloud-CI writer passes it, because
    `scripts/sweep-evidence.py`'s decoder mirror reads the plain form alone."""
    raw = json.dumps(record, sort_keys=True, separators=(',', ':')).encode('utf-8')
    if compress:
        raw = zlib.compress(raw, 9)
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode('ascii')


# Largest inflated CI-evidence payload `_decode_ci_payload` accepts: a whole comment.
_CI_PAYLOAD_INFLATE_LIMIT = _COMMENT_BYTE_LIMIT


def _decode_ci_payload(payload: str) -> object:
    """Decode a CI-evidence marker payload back to its JSON object — a zlib stream
    (first decoded byte 0x78, which no `json.dumps` output starts with) inflated first,
    plain JSON as retained workpads carry it read directly. Best-effort: a payload that
    is not valid base64url, a stream that is corrupt, truncated, trailed by other bytes
    or inflates past `_CI_PAYLOAD_INFLATE_LIMIT`, or bytes that are not UTF-8 JSON
    return None, which the validator treats as a missing-evidence (non-object) record
    rather than raising."""
    try:
        raw = base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4))
    except (TypeError, ValueError):
        return None
    if raw[:1] == b'\x78':
        inflater = zlib.decompressobj()
        try:
            raw = inflater.decompress(raw, _CI_PAYLOAD_INFLATE_LIMIT + 1)
        except zlib.error:
            return None
        if (len(raw) > _CI_PAYLOAD_INFLATE_LIMIT or not inflater.eof
                or inflater.unconsumed_tail or inflater.unused_data):
            return None
    try:
        return json.loads(raw.decode('utf-8'))
    except (ValueError, RecursionError):
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


# Cloud CI evidence has its own completion-cloud-ci family and offline validator.
# Reuse the compressed base64url JSON codec for its richer checks/shards record.
_COMPLETION_CLOUD_CI_MARKER_KEY_PREFIX = 'completion-cloud-ci:'
_COMPLETION_CLOUD_CI_MARKER_RE = re.compile(
    _MARKER_NS_RE + r'checkpoint completion-cloud-ci:([^\s]+?) -->'
)


def _completion_cloud_ci_marker_payloads(progress_content: str) -> list[str]:
    """Every payload carried by a `completion-cloud-ci:` checkpoint marker in the
    ## Progress content. A marker outside ## Progress is not found here, so it is
    treated as absent — fail closed. Duplicates surface as a >1-length list."""
    return _COMPLETION_CLOUD_CI_MARKER_RE.findall(progress_content or '')


def _strip_completion_cloud_ci_marker_rows(content: str) -> str:
    """Remove any ## Progress row carrying a `completion-cloud-ci:` marker, so a later
    validated record replaces the prior one rather than accumulating."""
    kept = [ln for ln in content.splitlines(keepends=True)
            if not _COMPLETION_CLOUD_CI_MARKER_RE.search(ln)]
    return ''.join(kept)


def _strip_all_completion_marker_rows(content: str) -> str:
    """Remove every ## Progress row carrying ANY completion-evidence marker family —
    flight, CI-derived, or cloud-CI (issue #403). Recording one family, or an explicit
    `--invalidate-completion-evidence`, clears the others so exactly one marker survives
    (the terminal gate counts across all three families combined) and stale evidence from
    another family can never block Complete or be read as current."""
    content = _strip_completion_marker_rows(content)
    content = _strip_completion_ci_marker_rows(content)
    content = _strip_completion_cloud_ci_marker_rows(content)
    return content


# Sweep evidence replaces only the same run identity's record; other runs coexist.
# Protected from compaction/caller-note limits, its payload has _NOTE_BYTE_BUDGET.
# Keep this marker grammar coupled to scripts/sweep-evidence.py's reader.
_SWEEP_EVIDENCE_KEY_PREFIX = 'sweep-evidence:'
_SWEEP_EVIDENCE_MARKER_RE = re.compile(
    _MARKER_NS_RE + r'checkpoint sweep-evidence:([^:\s]+):([^\s]+?) -->'
)
_SWEEP_EVIDENCE_VALIDATOR_CACHE = None


def _strip_sweep_evidence_marker_rows_for_run(content, run_identity):
    """Remove any ## Progress row carrying THIS run identity's sweep-evidence marker,
    so a later validated record replaces the prior one for the same run rather than
    accumulating — while another run's rows are left untouched (per-run, not global)."""
    kept = []
    for ln in content.splitlines(keepends=True):
        m = _SWEEP_EVIDENCE_MARKER_RE.search(ln)
        if m and m.group(1) == run_identity:
            continue
        kept.append(ln)
    return ''.join(kept)


def _load_sweep_evidence_validator():
    """Lazily import the sibling `sweep-evidence.py` module, once. Returns the module,
    or None when the sibling is absent OR present-but-unimportable beside this
    workpad.py copy (the standalone-deployment closure) — the caller's diagnostic names
    both causes. Imported by file path because the filename carries a hyphen; the result
    is memoized. Tests exercise the standalone-copy arm by monkeypatching this function
    to return None."""
    global _SWEEP_EVIDENCE_VALIDATOR_CACHE
    if _SWEEP_EVIDENCE_VALIDATOR_CACHE is not None:
        return _SWEEP_EVIDENCE_VALIDATOR_CACHE
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sweep-evidence.py')
    if not os.path.exists(path):
        return None
    try:
        spec = importlib.util.spec_from_file_location('_devflow_sweep_evidence', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception:
        return None
    _SWEEP_EVIDENCE_VALIDATOR_CACHE = mod
    return mod


def _validate_sweep_evidence(record):
    """Validate a decoded sweep-evidence record through the sibling validator.

    Raises a structural `_UpdateError` (no PATCH) on an absent validator sibling, an
    internal validator failure, or a non-`ok` verdict. Returns None on a clean pass.
    Mirrors `_validate_cloud_ci_evidence`'s three-way failure shape."""
    validator = _load_sweep_evidence_validator()
    if validator is None or not hasattr(validator, 'validate_sweep_evidence'):
        # `_load_sweep_evidence_validator` returns None for BOTH an absent sibling and a
        # present-but-unimportable one, so the diagnostic names both causes rather than
        # asserting absence — a present-but-broken sweep-evidence.py must not read as
        # missing to an operator debugging the standalone-copy closure.
        raise _UpdateError(
            "sweep evidence [missing-validator]: the sweep-evidence validator module "
            "(sweep-evidence.py) is not available or not importable beside this "
            "workpad.py copy, so a --record-sweep-evidence write cannot be validated. "
            "No PATCH was made."
        )
    try:
        token, detail = validator.validate_sweep_evidence(record)
    except Exception as e:
        raise _UpdateError(
            f"sweep evidence: the validator raised an internal error "
            f"({e.__class__.__name__}); treating as unestablished. No PATCH was made."
        )
    if token != 'ok':
        raise _UpdateError(
            f"sweep evidence rejected [{token}]: {detail}. No PATCH was made."
        )


# ── Verification-evidence record (issue #2131) ─────────────────────────────────
# Each launch APPENDS one note-kind row: never replace a prior row, and never let a row
# span lines — lib/fetch-pr-context.sh reads the workpad one line at a time.
_VERIFICATION_EVIDENCE_PREFIX = 'Verification evidence:'
_VERIFICATION_EVIDENCE_HEAD_UNESTABLISHED = 'unestablished'
# The coordinator prints these only on a real launch (`run-parallel: aggregate CLEAN`
# / `run-parallel: aggregate FAILED …`), so an aggregate outcome recorded with
# run-root=none is a contradiction the validator refuses.
_VERIFICATION_EVIDENCE_AGGREGATE_TOKENS = ('aggregate CLEAN', 'aggregate FAILED')


def _git_head_or_unestablished(root: str) -> str:
    """The full 40-lowercase-hex HEAD via `git rev-parse HEAD` in `root`, or the
    literal `unestablished` when git cannot answer (not a git tree, git absent, or a
    branch with no commit). Never raises: the record stamps the head as unestablished
    rather than aborting."""
    try:
        r = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root,
                            capture_output=True, encoding='utf-8')
    except Exception as e:
        # Not only OSError: a non-UTF-8 git output raises UnicodeDecodeError, and the
        # docstring promises this never raises (parity with _git_root_error_suffix).
        sys.stderr.write(
            "workpad.py: verification-evidence head unestablished — git gave no "
            f"usable answer ({e!r}); recording head=unestablished\n")
        return _VERIFICATION_EVIDENCE_HEAD_UNESTABLISHED
    sha = (r.stdout or '').strip()
    if r.returncode != 0 or not re.fullmatch(r'[0-9a-f]{40}', sha):
        # Distinct from the could-not-run arm above: git ran but answered nothing usable
        # (no commit yet, not a git tree, malformed output).
        sys.stderr.write(
            "workpad.py: verification-evidence head unestablished — `git rev-parse "
            f"HEAD` in {root!r} gave rc={r.returncode} (no commit / not a git tree); "
            "recording head=unestablished\n")
        return _VERIFICATION_EVIDENCE_HEAD_UNESTABLISHED
    return sha


def _validate_verification_evidence(command, outcome, run_roots) -> None:
    """Structural refusal (no PATCH) for a `--record-verification-evidence` call: a
    missing required field, or an aggregate outcome recorded with run-root=none.
    Mirrors the CI block's validate-before-mutation order."""
    missing = [flag for flag, val in
               (('--command', command), ('--outcome', outcome))
               if not (val or '').strip()]
    if not run_roots:
        missing.append('--run-root')
    if missing:
        raise _UpdateError(
            "--record-verification-evidence requires " + ', '.join(missing)
            + ". No PATCH was made."
        )
    if 'none' in run_roots and any(
            tok in outcome for tok in _VERIFICATION_EVIDENCE_AGGREGATE_TOKENS):
        raise _UpdateError(
            "--record-verification-evidence: an outcome naming an aggregate result "
            f"({' / '.join(_VERIFICATION_EVIDENCE_AGGREGATE_TOKENS)}) cannot be "
            "recorded with run-root=none — a coordinator that printed an aggregate "
            "line ran, so it left a retained-log root. No PATCH was made."
        )


def _verification_evidence_row(command, outcome, run_roots, tallies, elapsed,
                               started_at, recorded_at, head) -> str:
    """Compose the single-line `Verification evidence:` note text from validated
    operands as `key=value` pairs; `run-root` repeats once per root, the optional
    tallies/elapsed/started-at appear only when supplied, and recorded-at/head are
    the tool-stamped fields."""
    parts = [f'command={command}', f'outcome={outcome}']
    parts += [f'run-root={r}' for r in run_roots]
    for _key, _val in (('tallies', tallies), ('elapsed', elapsed),
                       ('started-at', started_at)):
        if _val is not None:
            parts.append(f'{_key}={_val}')
    parts.append(f'recorded-at={recorded_at}')
    parts.append(f'head={head}')
    return _VERIFICATION_EVIDENCE_PREFIX + ' ' + ' '.join(parts)


# Resume points are navigation hints, never verdict evidence.
# Each write replaces the prior row with encoded whitespace-free text.
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


# ── Resume prior-status family (issue #137) ────────────────────────────────────
# The reset runs BEFORE Phase 1.3 classifies the resume, so Phase 1.3 can no longer
# read a terminal LIVE Status to tell a terminal re-trigger from a mid-flight resume:
# the reset must record the prior terminal word into this durable ## Progress marker,
# which Phase 1.3 reads (falling back to the live Status when absent) and consumes.
# Payload is the whitespace-free Status word, so it needs no base64 encoding; both
# prflow:/devflow: spellings read (#1003).
_PRIOR_STATUS_MARKER_KEY_PREFIX = 'prior-status:'
_PRIOR_STATUS_MARKER_RE = re.compile(
    _MARKER_NS_RE + r'checkpoint prior-status:([^\s]+?) -->'
)


def _prior_status_marker_payloads(progress_content: str) -> list[str]:
    """Every prior-status word carried by a `prior-status:` marker in the ## Progress
    content. A marker outside ## Progress is not passed here, so it reads as absent."""
    return _PRIOR_STATUS_MARKER_RE.findall(progress_content or '')


def _strip_prior_status_marker_rows(content: str) -> str:
    """Remove any ## Progress row carrying a `prior-status:` marker, so Phase 1.3's
    hydration consumes it after reading it. No marker present is a no-op."""
    kept = [ln for ln in content.splitlines(keepends=True)
            if not _PRIOR_STATUS_MARKER_RE.search(ln)]
    return ''.join(kept)


def _reset_resume_status_inner(args, marker: str) -> str:
    """The shared resume reset's core, wrapped best-effort by cmd_reset_resume_status.

    Idempotent: only a TERMINAL live Status is reset. On a terminal Status it records
    the prior word into the prior-status marker (never overwriting an existing one),
    rewrites Status to `Setup`, PATCHes the body, then fires the existing
    status→label mirror. Returns an outcome token; a resolve/read/write fault raises
    into the caller's absorber."""
    repo = _repo_full(api_fail_code=3)
    c = _find_workpad_comment(
        'reset-resume-status', repo, args.issue, marker, api_fail_code=3)
    if c is None:
        return 'NO_WORKPAD'
    comment_id = c['id']
    body = c.get('body') or ''
    word = _status_word_from_body(body)
    glyph = _status_glyph(word) if word else ''
    # Idempotence: an interim word (or no Status line) is already the live state, so
    # a second invocation after a first reset writes nothing and leaves the recorded
    # marker untouched — it never reaches the terminal path below.
    if glyph not in _TERMINAL_STATUS_CLASS_BY_GLYPH:
        return f'NOOP {word or "(none)"}'
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    # Rewrite the Status and Last-updated lines (both in the front matter) first.
    new_body, n = _STATUS_RE.subn(
        f'**Status:** {_status_glyph("Setup")} Setup', body, count=1)
    if n == 0:
        # A terminal glyph was read from a Status line, so this cannot miss in
        # practice; fail closed into the absorber rather than PATCH an unchanged body.
        raise RuntimeError('Status line not found while resetting')
    new_body, _ = _LAST_UPDATED_RE.subn(
        f"**Last updated:** {now_dt.strftime('%Y-%m-%d %H:%M UTC')}", new_body, count=1)
    preamble, sections = _split_sections(new_body)
    idx = _find_section(sections, 'Progress')
    # Without a ## Progress section the prior word cannot be carried forward, so
    # resetting Status now would make Phase 1.3 misclassify the terminal re-trigger
    # as mid-flight. Leave the workpad untouched (no PATCH) rather than reset unsafely.
    if idx is None:
        sys.stderr.write(
            "workpad.py reset-resume-status: workpad carries no '## Progress' section, "
            "so the prior status cannot be recorded; status not reset (run unaffected)\n")
        return 'UNAVAILABLE no-progress-section'
    heading, content = sections[idx]
    if not _prior_status_marker_payloads(content):
        note = (f'resume reset: prior status {word} '
                f'{_checkpoint_marker(_PRIOR_STATUS_MARKER_KEY_PREFIX + word)}')
        # The tool composes this prior-status marker itself, so it is admitted by the
        # explicit opt-in rather than refused by the widened note-text guard (issue #321).
        content = _append_progress_note(
            content, note, now_dt.strftime('%H:%M:%S'), 'Setup',
            reserved_marker_ok=True)
        sections[idx] = (heading, content)
    new_body = _join_sections(preamble, sections)
    # gh api -X PATCH can return success over an unchanged body, so verify the reset
    # landed from the echoed response before claiming RESET or firing the mirror —
    # else the label could read Implementing while the body still reads terminal.
    resp = _patch_comment_body(repo, comment_id, new_body)
    reset_word = _status_word_from_body(resp or '')
    if not reset_word or _status_glyph(reset_word) in _TERMINAL_STATUS_CLASS_BY_GLYPH:
        sys.stderr.write(
            "workpad.py reset-resume-status: the reset PATCH did not land (response "
            "still reads terminal or was empty); status not reset and label mirror not "
            "fired (run unaffected)\n")
        return 'UNAVAILABLE patch-unverified'
    # Mirror the label only after the reset is confirmed; the Status word is reset
    # above even when the status_labels feature is disabled and the mirror no-ops.
    _mirror_status_labels(args.issue, 'Setup', body=new_body)
    return f'RESET {word}'


def cmd_reset_resume_status(args):
    """Best-effort terminal-to-interim reset with prior-status record and label mirror.
    Print RESET <word>, NOOP <word>, NO_WORKPAD, or UNAVAILABLE <reason>; always exit 0."""
    marker = _workpad_marker(args.marker)
    try:
        outcome = _reset_resume_status_inner(args, marker)
    except SystemExit as e:
        # _repo_full / _find_workpad_comment exit via _fail on a transport/auth
        # failure; convert that to the best-effort warn-and-continue contract.
        if e.code in (None, 0):
            raise
        sys.stderr.write(
            "workpad.py reset-resume-status: best-effort workpad resolve/read failed "
            f"(exit {e.code}); the workpad status was not reset (run unaffected)\n")
        print('UNAVAILABLE resolve-or-read-failed')
        return
    except Exception as exc:  # intentional best-effort absorber (see docstring)
        sys.stderr.write(
            "workpad.py reset-resume-status: best-effort reset failed "
            f"({exc.__class__.__name__}); the workpad status was not reset "
            "(run unaffected)\n")
        print(f'UNAVAILABLE {exc.__class__.__name__}')
        return
    print(outcome)


def cmd_prior_status(args):
    """Print one prior terminal word without the body.
    Exit 0: one valid marker; 1: absent/garbled/duplicated marker;
    2: missing workpad or sole Progress section; 3: transient read/repo failure.
    Keep transient failure distinct so callers do not misclassify a reset run."""
    marker = _workpad_marker(args.marker)
    c = _find_workpad_comment(
        'prior-status', _repo_full(api_fail_code=3), args.issue, marker,
        api_fail_code=3,
    )
    if c is None:
        sys.stderr.write(
            f"workpad.py prior-status: no workpad comment carrying {marker!r} on "
            f"issue #{args.issue}; the prior status could not be established\n"
        )
        sys.exit(2)
    content = _progress_content_or_none(c.get('body') or '')
    if content is None:
        sys.stderr.write(
            "workpad.py prior-status: the workpad does not carry exactly one "
            "'## Progress' section (absent or duplicated); the prior status could "
            "not be established\n"
        )
        sys.exit(2)
    # A duplicated or garbled marker set (len != 1) reads as absent, so a resume
    # classification falls back to the live Status rather than trusting a bad marker.
    words = _prior_status_marker_payloads(content)
    if len(words) != 1:
        sys.stderr.write(
            f"workpad.py prior-status: found {len(words)} prior-status markers "
            f"(expected exactly 1); the caller falls back to the live Status\n"
        )
        sys.exit(1)
    print(words[0])
    sys.exit(0)


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


def _validate_cloud_ci_evidence(args, payload: str) -> None:
    """Validate a specific cloud-CI completion-evidence marker payload (issue #403).

    Raises a structural `_UpdateError` (no PATCH) on an absent validator sibling (or one
    without the cloud-CI entry point), an internal validator failure, or a non-pass
    verdict. Returns None on a clean pass. Mirrors `_validate_ci_evidence`'s shape."""
    validator = _load_completion_validator()
    if validator is None or not hasattr(
            validator, 'validate_implement_completion_cloud_ci'):
        raise _UpdateError(
            "completion evidence [missing-evidence]: the completion-evidence "
            "validator module (check-completion-evidence.py) with a cloud-CI entry "
            "point is not available beside this workpad.py copy, so a --status "
            "Complete write cannot be backed by cloud-CI evidence. No PATCH was made."
        )
    record = _decode_ci_payload(payload)
    root = _devflow_repo_root(args)
    try:
        token, detail = validator.validate_implement_completion_cloud_ci(record, root)
    except Exception as e:
        raise _UpdateError(
            f"completion evidence: the cloud-CI validator raised an internal error "
            f"({e.__class__.__name__}); treating as unestablished. No PATCH was made."
        )
    if token != 'pass':
        raise _UpdateError(
            f"completion evidence rejected [{token}]: {detail}. No PATCH was made."
        )


# Review coverage is one replaceable four-axis record, with gap dispositions.
# Strip before rewriting: generic keyed replay would accumulate changing payloads.
# Readers require exactly one record.
_REVIEW_COVERAGE_KEY_PREFIX = 'review-coverage:'
_REVIEW_COVERAGE_DISPOSITION_KEY_PREFIX = 'review-coverage-disposition:'
# Use the shared per-record namespace grammar; coverage and disposition keys differ.
# Unreadable marker shapes remain unestablished at the Complete gate.
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
# Axis table: values is closed vocabulary, clean defines passing values, gap
# names the shortfall. Coverage/dispatch share shadow-coverage.
# Views derive from this table; reconcile shipped prose found by
# record-review-coverage and dispatch= searches when changing vocabulary.
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
    """Validate the axis table at import: clean values must be valid and established,
    and payload values must round-trip without colon/whitespace ambiguity."""
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
# Issue #345: strip exactly one leading `prflow:` from a --record-roster-member operand
# BEFORE validating/storing/dedup (never at read-back), so a prefixed spelling stores the
# same short row while `prflow:x:y` / a foreign prefix / an empty name still fail unknown-member.
_ROSTER_MEMBER_PREFIX = 'prflow:'


def _normalize_roster_member(member: str) -> str:
    if member.startswith(_ROSTER_MEMBER_PREFIX):
        return member[len(_ROSTER_MEMBER_PREFIX):]
    return member


_REVIEW_ROSTER_KEY_PREFIX = 'review-roster:'
# Composed from `_MARKER_NS_RE` like the coverage grammars, so the confirmation-gated
# retirement of the superseded namespace reaches it too. The capture holds the combined
# `_encode_reuse_roster` payload (`<member>.<status>` pairs joined by '_'), decoded by
# `_decode_roster_payload`.
_REVIEW_ROSTER_MARKER_RE = re.compile(
    _MARKER_NS_RE + r'checkpoint review-roster:([^\s]+?) -->'
)
# A member enumerated twice resolves to this sentinel, whose status is unresolvable, so
# `_review_roster_incoherence` refuses it — the fail-closed posture
# `_review_coverage_dispositions` takes for a duplicated gap.
_REVIEW_ROSTER_DUPLICATE = object()
# A `review-roster:` row is present but its payload does not decode — a truncated or
# garbled payload, or the superseded per-member `<member>:<status>` shape. Distinct from
# the empty map (no row at all): the map is grandfathered, this state is refused as
# UNESTABLISHED, so a damaged record stops a run instead of finalizing it.
_REVIEW_ROSTER_UNDECODABLE = object()
# The shared refusal tail both undecodable-roster sites raise (the Complete gate and a
# --review-coverage-disposition write) — one source so the breadcrumb, token and re-stamp
# remedy cannot drift between them; each site prepends only its own leading clause.
_REVIEW_ROSTER_UNDECODABLE_TAIL = (
    "a review-roster enumeration row is present but its payload does not decode "
    "(truncated, garbled, or the superseded per-member shape), so the run's review "
    "coverage is UNESTABLISHED [review-coverage-unestablished]. Re-stamp "
    "`--record-review-coverage` with `--record-roster-member` at the Phase 3.3 review "
    "exit, which strips the bad row. No PATCH was made."
)
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


def _review_coverage_marker_rows(progress_content: str, pattern):
    """Yield captures only from markers ending canonical timestamped Progress bullets.
    Together with the free-text writer guard, this excludes embedded prose markers."""
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
    """Parse all coverage axes or return None; partial records establish nothing.
    Accept legacy axis-only and anchored payloads. Head/asof metadata is not an axis."""
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
    """Read a valid head/asof anchor or return None for legacy/malformed payloads.
    Head may be unestablished; asof uses colon-free basic-ISO UTC."""
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
    """Require not-applicable on all axes or none: it describes the whole pass."""
    na = [axis for axis in _REVIEW_COVERAGE_AXES
          if record[axis] == 'not-applicable']
    if na and len(na) != len(_REVIEW_COVERAGE_AXES):
        return (
            "'not-applicable' is the no-shadow-owed record and describes the whole "
            f"pass, so it is legal on all {len(_REVIEW_COVERAGE_AXES)} axes or none; "
            f"here it is held only by {', '.join(na)}")
    return None


def _review_roster_members(progress_content: str):
    """Read combined roster markers as {member: status}.
    No row yields {}; duplicate members get _REVIEW_ROSTER_DUPLICATE.
    Any unreadable payload yields _REVIEW_ROSTER_UNDECODABLE, never legacy absence."""
    payloads = list(_review_coverage_marker_rows(
        progress_content, _REVIEW_ROSTER_MARKER_RE))
    if not payloads:
        return {}
    out: dict = {}
    for payload in payloads:
        pairs = _decode_roster_payload(payload)
        if pairs is None:
            return _REVIEW_ROSTER_UNDECODABLE
        for member, status in pairs:
            out[member] = _REVIEW_ROSTER_DUPLICATE if member in out else status
    return out


def _review_roster_incoherence(record: dict, members: dict) -> str | None:
    """Cross-check roster vocabulary and enumeration.
    Measured complete/short require members; unestablished/not-applicable require none.
    Complete needs every always-on member dispatched and no missing member;
    short needs a missing member. Always-on members cannot be gated-off.
    Unknown/duplicate members fail. This enforces the always-on floor; gated analyzers
    remain self-reported. Read-time callers grandfather legacy rosterless records."""
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
                f"enumeration, but the review-roster row enumerates {len(members)} member(s)")
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


def _review_roster_marker(members: dict) -> str:
    """The hidden marker the single combined review-roster enumeration row carries — one
    `_encode_reuse_roster` payload over the whole map, decoded back by
    `_review_roster_members`."""
    return _checkpoint_marker(
        f'{_REVIEW_ROSTER_KEY_PREFIX}{_encode_reuse_roster(members)}')


def _render_review_roster(members: dict) -> str:
    """The combined roster row's visible text: the count of `dispatched` members, then
    each `gated-off` and each `missing` member by name — e.g. `review roster: 5
    dispatched, gated-off: type-design-analyzer`."""
    dispatched = sum(1 for s in members.values() if s == 'dispatched')
    parts = [f'review roster: {dispatched} dispatched']
    gated = sorted(m for m, s in members.items() if s == 'gated-off')
    missing = sorted(m for m, s in members.items() if s == 'missing')
    if gated:
        parts.append(f'gated-off: {", ".join(gated)}')
    if missing:
        parts.append(f'missing: {", ".join(missing)}')
    return ', '.join(parts)


# issue #1509: the diff-profile row that authorizes a `skipped-intentional` checklist
# skip. These constants MIRROR scripts/review-engine-io.py's `small_diff` ceilings and
# `config_only` extension set; the workpad_compaction divergence test goes RED if they drift.
_REVIEW_COVERAGE_SMALL_DIFF_LINE_CEILING = 100   # total changed lines strictly below this
_REVIEW_COVERAGE_SMALL_DIFF_FILE_CEILING = 3     # changed-file count at most this
_REVIEW_COVERAGE_CONFIG_ONLY_EXTS = frozenset(
    {'.yml', '.yaml', '.json', '.md', '.toml', '.ini', '.lock', '.txt'})


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
    """Measure the anchored head against base_ref (else origin/HEAD) using git.
    Return resolved/reason/lines/files/paths. Missing head/base, shallow/unrelated
    history, failed git calls or malformed rows make the result unestablished."""
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
        # A SHALLOW repository has no trustworthy merge base (issue #802): a graft makes
        # the base tip look parentless, so `git merge-base` does not fail — it answers
        # with a far older ancestor reached around the boundary, and the diff below then
        # counts every commit merged into the base since. Refuse to measure rather than
        # publish that number; anything but a literal `false` (an unparseable answer, an
        # older git without the flag exits non-zero into the handler) is not a proof of
        # full history.
        if _git(['rev-parse', '--is-shallow-repository']).strip() != 'false':
            return _unresolved(
                'the repository is a shallow clone, so the merge base with the '
                'reviewed head cannot be trusted (deepen it with git fetch '
                '--unshallow, or check out with fetch-depth: 0)')
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


def _review_coverage_base_ref(repo_root):
    """Return (origin/configured-base, None) or (None, diagnostic).
    Read config in-process at repo_root. Missing/null/empty base defaults to main;
    wrong types, non-object config and unreadable content remain unestablished."""
    base = repo_root if repo_root is not None else str(Path.cwd())
    config_file = Path(_resolve_state_dir(base)) / 'config.json'
    try:
        with config_file.open(encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return 'origin/main', None
    except (OSError, ValueError) as e:
        # ValueError covers json.JSONDecodeError AND the UTF-16LE-BOM
        # UnicodeDecodeError (the PowerShell 5.x `>` redirection shape).
        return None, f"could not read {str(config_file)!r} ({e})"
    if not isinstance(data, dict):
        return None, (
            f"the top level of {str(config_file)!r} is not a JSON object")
    if 'base_branch' not in data:
        return 'origin/main', None
    value = data['base_branch']
    if value is None or value == '':
        return 'origin/main', None
    if not isinstance(value, str):
        return None, (
            f"base_branch in {str(config_file)!r} is "
            f"{type(value).__name__}, not a string")
    return f'origin/{value}', None


def _review_coverage_profile_disproof(facts) -> str | None:
    """Why the recomputed diff does NOT satisfy the profile row that authorizes a
    `skipped-intentional` skip, naming each failed condition and its measured value —
    or None when the profile row is confirmed (issue #1509). Assumes facts['resolved'].
    Checks the two ceilings and the config-only extension set only, in every repository:
    the profile row is repository-independent, so the reviewed diff's size and file types
    are the whole predicate."""
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
    return '; '.join(reasons) if reasons else None


def _review_coverage_dispositions(progress_content: str) -> dict:
    """Read {gap: (cause_class, reason)} from Progress disposition rows.
    Unreadable reasons become empty and fail validation; legacy markers without
    a cause class discharge nothing."""
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
    corroborated by the combined roster row's per-member entries covering all four
    always-on reviewers with at least one reading `dispatched` (issue #1984). Shared by the write-time
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


def _review_coverage_roster_facts(roster_members: dict) -> tuple[bool, bool]:
    """`(has_missing, has_dispatched)` over the roster rows, shared by both cause-class
    enforcement points."""
    has_missing = any(s == 'missing' for s in roster_members.values())
    has_dispatched = any(
        roster_members.get(m) == 'dispatched' for m in _SHADOW_ALWAYS_ON_MEMBERS)
    return has_missing, has_dispatched


def _review_coverage_disposition_cause_rejection(
        cause_class, *, has_missing_roster_row, has_dispatched_roster_row):
    """Validate cause vocabulary and roster corroboration for both writer and gate.
    Corroboration is roster-global: environment-denial needs any missing member;
    dispatched-but-lost needs a dispatched always-on member. The corroborating
    member need not correspond to the disposed gap."""
    if cause_class not in _REVIEW_COVERAGE_CAUSE_CLASSES:
        return (f"carries cause class {cause_class!r}, which is not one of "
                f"{', '.join(_REVIEW_COVERAGE_CAUSE_CLASSES)}")
    if cause_class == 'environment-denial' and not has_missing_roster_row:
        return ("carries cause class 'environment-denial' but no roster row records a "
                "member 'missing', so the denied capability is uncorroborated")
    if cause_class == 'dispatched-but-lost' and not has_dispatched_roster_row:
        return ("carries cause class 'dispatched-but-lost' but no always-on reviewer's "
                "roster row records 'dispatched', so no dispatch is on record")
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
    """Remove reflections paired with stripped dispositions using current/legacy prefixes.
    Superseded evidence must not leave permanent retrospective friction."""
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


# Issue #2026: the human review-waiver disclosure's checkpoint key, reserved so no
# `## Progress` free-text channel can plant the marker a genuine waiver writes.
_REVIEW_WAIVED_KEY_PREFIX = 'review-waived:'
_REVIEW_WAIVED_KEY = _REVIEW_WAIVED_KEY_PREFIX + 'human'


# Reuse records survive inherited-checkpoint stripping because they bind inputs.
# Resolve the live issue digest and git identities before crediting a match;
# unreadable inputs remain unestablished.
_PLAN_INPUTS_KEY_PREFIX = 'plan-inputs:'
_PLAN_INPUTS_MARKER_RE = re.compile(
    _MARKER_NS_RE + r'checkpoint plan-inputs:([^\s]+?) -->'
)
_REUSABLE_REVIEW_KEY_PREFIX = 'reusable-review:'
_REUSABLE_REVIEW_MARKER_RE = re.compile(
    _MARKER_NS_RE + r'checkpoint reusable-review:([^\s]+?) -->'
)
# Mirrors the clean approve tokens `loop-verdict-marker.py` prints after
# `CLEAN-FULL`; the suite fails when the two sets diverge.
_REUSABLE_REVIEW_VERDICTS = (
    'approve', 'approve-with-notes', 'approve-with-caveat',
    'approve-with-advisory-notes')
_REUSABLE_REVIEW_CHECKLISTS = ('complete', 'skipped-intentional')
_SHA40_RE = re.compile(r'\A[0-9a-f]{40}\Z')
_SHA256_HEX_RE = re.compile(r'\A[0-9a-f]{64}\Z')


def _reuse_issue_digest(issue):
    """(sha256-hex, None) of the live issue body, or (None, reason).

    Line endings are canonicalized and trailing newlines dropped, so a Windows
    runner and gh's `-q` trailing newline cannot turn one body into two digests."""
    try:
        r = _run([GH, 'issue', 'view', str(issue), '--json', 'body', '-q', '.body'])
    except (subprocess.CalledProcessError, OSError) as e:
        return None, f'the issue body could not be read ({e})'
    text = (r.stdout or '').replace('\r\n', '\n').rstrip('\n')
    return hashlib.sha256(text.encode('utf-8')).hexdigest(), None


def _reuse_candidate(head, repo_root):
    """({'head', 'merge_base'}, None) for `head` against the configured base, or
    (None, reason). Both SHAs are full 40-hex values resolved by git."""
    base_ref, err = _review_coverage_base_ref(repo_root)
    if err is not None:
        return None, f'the base branch could not be resolved ({err})'

    def _git(argv):
        return subprocess.run(
            ['git', *argv], cwd=repo_root, check=True,
            capture_output=True, encoding='utf-8').stdout.strip()

    try:
        full_head = _git(['rev-parse', '--verify', f'{head}^{{commit}}'])
        merge_base = _git(['merge-base', full_head, base_ref])
    except (subprocess.CalledProcessError, OSError) as e:
        return None, f'the reviewed head or its merge-base did not resolve ({e})'
    if not (_SHA40_RE.match(full_head) and _SHA40_RE.match(merge_base)):
        return None, 'git printed a head or merge-base that is not a 40-hex SHA'
    return {'head': full_head, 'merge_base': merge_base}, None


def _encode_reuse_roster(members: dict) -> str:
    return '_'.join(f'{m}.{members[m]}' for m in sorted(members))


def _decode_roster_payload(payload: str):
    """The ordered `(member, status)` pairs a `_encode_reuse_roster` payload encodes, or
    None when any pair is malformed — no `.` separator, an unknown member, or an unknown
    status. Duplicate members are NOT judged here (the pairs are returned as-is); each
    caller decides — the reusable-review record refuses a duplicate, the roster row maps
    it to `_REVIEW_ROSTER_DUPLICATE`. The inverse of `_encode_reuse_roster`, and nothing
    more."""
    pairs = []
    for pair in payload.split('_') if payload else []:
        member, sep, status = pair.partition('.')
        if (not sep or member not in _SHADOW_ROSTER_MEMBERS
                or status not in _ROSTER_MEMBER_STATUSES):
            return None
        pairs.append((member, status))
    return pairs


def _parse_reusable_review_payload(payload: str):
    """The stored record as a dict, or None when any field is malformed."""
    fields = (payload or '').split(':')
    if len(fields) != 6:
        return None
    head, merge_base, digest, verdict, checklist, roster = fields
    if not (_SHA40_RE.match(head) and _SHA40_RE.match(merge_base)
            and _SHA256_HEX_RE.match(digest)):
        return None
    if verdict not in _REUSABLE_REVIEW_VERDICTS:
        return None
    if checklist not in _REUSABLE_REVIEW_CHECKLISTS:
        return None
    pairs = _decode_roster_payload(roster)
    if pairs is None:
        return None
    members: dict = {}
    for member, status in pairs:
        if member in members:
            return None
        members[member] = status
    if (any(members.get(m) != 'dispatched' for m in _SHADOW_ALWAYS_ON_MEMBERS)
            or 'missing' in members.values()):
        return None
    return {'head': head, 'merge_base': merge_base, 'digest': digest,
            'verdict': verdict, 'checklist': checklist, 'roster': members}


def _reuse_record(progress_content: str, kind: str):
    """('ok', record) | ('absent'|'duplicate'|'malformed', None) for one family.

    Only tail-anchored producer rows count, as for the review-coverage family."""
    pattern = (_PLAN_INPUTS_MARKER_RE if kind == 'plan'
               else _REUSABLE_REVIEW_MARKER_RE)
    payloads = list(_review_coverage_marker_rows(progress_content, pattern))
    if not payloads:
        return 'absent', None
    if len(payloads) > 1:
        return 'duplicate', None
    if kind == 'plan':
        if not _SHA256_HEX_RE.match(payloads[0]):
            return 'malformed', None
        return 'ok', {'digest': payloads[0]}
    record = _parse_reusable_review_payload(payloads[0])
    return ('ok', record) if record else ('malformed', None)


def _reuse_evaluate(progress_content: str, kind: str, issue, repo_root):
    """Return (result, detail, record) for current-input reuse.
    Results distinguish match, absent, duplicate, malformed, incomplete, mismatch
    and unestablished; an unreadable input is no match."""
    state, record = _reuse_record(progress_content, kind)
    if state != 'ok':
        return state, '', None
    if kind == 'review':
        unticked = _unticked_review_rows(progress_content)
        if unticked:
            return 'incomplete', ','.join(unticked), None
    digest, err = _reuse_issue_digest(issue)
    if err is not None:
        return 'unestablished', err, None
    if kind == 'review':
        candidate, err = _reuse_candidate('HEAD', repo_root)
        if err is not None:
            return 'unestablished', err, None
        if candidate['head'] != record['head']:
            return 'mismatch', 'head', record
        if candidate['merge_base'] != record['merge_base']:
            return 'mismatch', 'merge-base', record
    if digest != record['digest']:
        return 'mismatch', 'issue-body', record
    return 'match', '', record


def _unticked_review_rows(progress_content: str) -> list[str]:
    """The Review-block rows (all but the later AC gate) with no ticked row.

    Adoption skips the review worker that ticks them, so the completed attempt
    must already have ticked every one."""
    ticked = [m.group(4).lower() for line in (progress_content or '').splitlines()
              if (m := _CHECKBOX_ROW_RE.match(line)) and m.group(2) != '[ ]']
    return [substr for _text, substr in _REVIEW_BLOCK_ROWS
            if (_text, substr) != _AC_GATE_ROW
            and not any(substr.lower() in row for row in ticked)]


def _strip_marker_rows(content: str, pattern) -> str:
    return ''.join(ln for ln in content.splitlines(keepends=True)
                   if not pattern.search(ln))


def cmd_reuse_check(args):
    """Answer whether a recorded plan or review is reusable now (issue #616).

    Exit 0 on a match, 1 when there is nothing reusable (absent, duplicate,
    malformed, incomplete, mismatch), 2 when the answer is unestablished: the workpad or
    issue body is unreadable, or, for `review`, the base-branch config or git is.
    Prints one `reuse-check:` line, except that a failed GitHub repository or
    comment lookup exits 2 with only a stderr error; never prints the body."""
    marker = _workpad_marker(args.marker)
    c = _find_workpad_comment(
        'reuse-check', _repo_full(api_fail_code=2), args.issue, marker,
        api_fail_code=2,
    )
    content = _progress_content_or_none(c.get('body') or '') if c else None
    if content is None:
        print(f'reuse-check: kind={args.kind} result=unestablished '
              'reason=workpad-unreadable')
        sys.exit(2)
    result, detail, record = _reuse_evaluate(
        content, args.kind, args.issue, _repo_root())
    line = f'reuse-check: kind={args.kind} result={result}'
    if result == 'mismatch':
        line += f' field={detail}'
    elif result == 'incomplete':
        line += f' unticked={detail.replace(" ", "-")}'
    elif result == 'unestablished':
        line += ' reason=input-unresolved'
        sys.stderr.write(f'workpad.py reuse-check: {detail}\n')
    elif result == 'match' and args.kind == 'review':
        line += (f" verdict={record['verdict']} checklist={record['checklist']}"
                 f" head={record['head']}")
    print(line)
    sys.exit(0 if result == 'match' else 2 if result == 'unestablished' else 1)


# The checkpoint key namespaces that belong to a validated marker family, each paired
# with the flag that owns it. `_plan_checkpoints` refuses a generic `--checkpoint` in
# any of them, so a family's validation cannot be bypassed through the generic head.
_RESERVED_CHECKPOINT_KEY_PREFIXES = (
    (_REVIEW_COVERAGE_DISPOSITION_KEY_PREFIX, '`--review-coverage-disposition`'),
    (_REVIEW_ROSTER_KEY_PREFIX, '`--record-roster-member`'),
    (_REVIEW_COVERAGE_KEY_PREFIX, '`--record-review-coverage`'),
    (_COMPLETION_MARKER_KEY_PREFIX, '`--record-completion-evidence`'),
    (_COMPLETION_CI_MARKER_KEY_PREFIX, '`--record-completion-evidence-ci`'),
    (_COMPLETION_CLOUD_CI_MARKER_KEY_PREFIX,
     '`--record-completion-evidence-cloud-ci`'),
    (_SWEEP_EVIDENCE_KEY_PREFIX, '`--record-sweep-evidence`'),
    (_RESUME_POINT_MARKER_KEY_PREFIX, '`--record-resume-point`'),
    (_PLAN_INPUTS_KEY_PREFIX, '`--record-plan-inputs`'),
    (_REUSABLE_REVIEW_KEY_PREFIX, '`--record-reusable-review`'),
    (_REVIEW_WAIVED_KEY_PREFIX, '`--review-waived-by`'),
    (_PRIOR_STATUS_MARKER_KEY_PREFIX, '`reset-resume-status` (issue #137)'),
)


# The free-text guard's per-family screens (issue #321): derived from
# `_RESERVED_CHECKPOINT_KEY_PREFIXES` and `_MARKER_NS_RE` so both marker namespaces are
# covered and a family added to that list is screened with no edit here. Each prefix ends
# in `:`, so a family whose name is a prefix of another (`review-coverage:` vs.
# `review-coverage-disposition:`) cannot cross-match — the colon is a boundary.
_RESERVED_CHECKPOINT_MARKER_SCREENS = tuple(
    (re.compile(_MARKER_NS_RE + 'checkpoint ' + re.escape(_prefix)), _owner)
    for _prefix, _owner in _RESERVED_CHECKPOINT_KEY_PREFIXES
)


def _reserved_checkpoint_marker_owner(text: str | None) -> str | None:
    """Return the owning flag of the first reserved checkpoint family whose marker
    appears anywhere in `text` (either marker namespace), else None. The note-text
    guard and the two exempted-producer operand screens all read this, so one list —
    `_RESERVED_CHECKPOINT_KEY_PREFIXES` — drives both the key guard and the note-text
    guard."""
    for _screen, _owner in _RESERVED_CHECKPOINT_MARKER_SCREENS:
        if _screen.search(text or ''):
            return _owner
    return None


def _reserved_marker_error(source: str, owner: str) -> _UpdateError:
    """The shared refusal a caller-supplied channel raises when its text carries a
    reserved checkpoint marker (issue #321). `source` names the channel; `owner` is the
    owning flag from `_RESERVED_CHECKPOINT_KEY_PREFIXES` the guard resolved."""
    return _UpdateError(
        f"{source} carries a reserved checkpoint marker; record it with {owner} "
        "instead, the flag that owns that family. No PATCH was made.")


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
    """Validate exactly one marker across flight, local-CI and cloud-CI families.
    Re-derive current candidate identity unless claim-identity explicitly pins it.
    Dispatch to the family validator; missing/duplicate/stale/nonpassing evidence
    raises structural _UpdateError before PATCH."""
    keys = _completion_marker_keys(progress_content)
    ci_payloads = _completion_ci_marker_payloads(progress_content)
    cloud_ci_payloads = _completion_cloud_ci_marker_payloads(progress_content)
    total = len(keys) + len(ci_payloads) + len(cloud_ci_payloads)
    if total == 0:
        raise _UpdateError(
            "refusing to finalize Status: Complete — no completion-evidence marker "
            "of any family present [missing-evidence]. Record an in-env "
            "verification flight with `workpad.py update <issue> "
            "--record-completion-evidence <flight-key>`, or (local/interactive tier, "
            "issue #1611) a CI reading with `workpad.py update <issue> "
            "--record-completion-evidence-ci <head-sha> <tier> <run-url> "
            "--completion-ci-check <name> <conclusion> ...`, or (cloud CI mode, issue "
            "#403) `workpad.py update <issue> --record-completion-evidence-cloud-ci "
            "<record.json>`, after the run's verification is established. No PATCH was made."
        )
    if total > 1:
        raise _UpdateError(
            "refusing to finalize Status: Complete — "
            f"{total} completion-evidence markers present (counted across the "
            "verification-flight, CI-derived, and cloud-CI families); exactly one is "
            "required [missing-evidence]. No PATCH was made."
        )
    if keys:
        _validate_flight_key(args, keys[0])
    elif ci_payloads:
        _validate_ci_evidence(args, ci_payloads[0])
    else:
        _validate_cloud_ci_evidence(args, cloud_ci_payloads[0])


def _required_artifact_verdict(progress_content: str) -> None:
    """Require a Progress marker for each declared artifact, using either namespace
    and any accepting clean/tier-refused key. Pure validation: raise _UpdateError
    before PATCH; repairs belong to producers."""
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
    """Validate durable post-mutation Progress coverage or accepted gap dispositions.
    Absent/duplicate/malformed coverage is unestablished. Dispositions require
    attempted dispatch; a never-dispatched pass cannot explain its way to completion.
    Pure read: violations raise _UpdateError before PATCH."""
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
    if roster_members is _REVIEW_ROSTER_UNDECODABLE:
        raise _UpdateError(
            "refusing to finalize Status: Complete — "
            + _REVIEW_ROSTER_UNDECODABLE_TAIL)
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
    # `roster_members` was read above for the roster cross-check.
    has_missing_roster_row, has_dispatched_roster_row = _review_coverage_roster_facts(
        roster_members)
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
            cause_class, has_missing_roster_row=has_missing_roster_row,
            has_dispatched_roster_row=has_dispatched_roster_row)
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
    """Require each present extension row ticked or named in a state-not-established note.
    Absent legacy rows are tolerated. Pure read; violations raise _UpdateError."""
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
            offending.append((text, substr))
    if offending:
        rows = '\n'.join(
            f'    - [ ] {t}\n      accepted note: '
            f'{s[0].upper()}{s[1:]} — state not established (<cause>)'
            for t, s in offending
        )
        raise _UpdateError(
            "refusing to finalize Status: Complete — "
            f"{len(offending)} prompt-extension row(s) resolved-but-unrecorded: each "
            "is unticked and has no note line holding both its row name and the phrase "
            "`state not established` (tick it once the extension's state was observed, "
            "or record its accepted note, before finalizing) "
            f"[extension-row-unrecorded]:\n{rows}"
        )


def _terminal_complete_gate(sections, args) -> list[str]:
    """Validate the post-mutation self-record before a Complete PATCH; never modify rows.
    Unticked non-post-merge ACs fail. Pending AC mirroring and unticked Plan rows warn.
    Require current completion evidence, required artifacts, extension records,
    and review coverage unless explicitly human-waived. Absent AC/Plan sections
    contribute nothing; each delegated gate owns its other missing-state rules."""
    # Completion-evidence gate first: it is the strictest precondition and its
    # failure is the one issue #1087 exists to enforce. `args` is REQUIRED (never
    # defaulted) so the gate can never be silently skipped by an argument omission —
    # a Complete write without the evidence check would fail open on exactly the
    # guarantee this change adds.
    prog_idx = _find_section(sections, 'Progress')
    prog_content = sections[prog_idx][1] if prog_idx is not None else ''
    _completion_evidence_verdict(args, prog_content)
    _required_artifact_verdict(prog_content)
    if getattr(args, 'review_waived_by', None) is None:
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


# Keyed checkpoints replay without PATCH/timestamp changes.
# Validate structure before mutation; repair absent Progress in nonempty bodies.
# Use strict end anchoring: Python's $ also accepts a trailing newline, which
# would break the single-line marker. Handoff records are validated offline.
_CHECKPOINT_KEY_RE = re.compile(r'\A[A-Za-z0-9._:-]+\Z')


def _checkpoint_marker(key: str) -> str:
    """The hidden HTML-comment marker a checkpoint row carries so a replay can
    detect the key without changing the visible timestamped-note rendering."""
    return f'<!-- prflow:checkpoint {key} -->'


# Required artifacts pair accepting keys with the command quoted on refusal.
# The table drives both terminal validation and resume stripping.
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

# Attempt-scoped strip keys derive from artifact accept_keys.
# They exclude gha keys, so this strip cannot erase run-scoped cloud records.
_REQUIRED_ARTIFACT_CHECKPOINT_KEYS = tuple(
    key for artifact in _REQUIRED_ARTIFACTS for key in artifact['accept_keys']
)


def _repair_missing_progress_section(body: str) -> str:
    """Restore an absent Progress section in a nonempty workpad.
    Empty bodies and existing/duplicate Progress sections remain unchanged."""
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
    """Report repair only after all mutation validation succeeds, before returning for PATCH."""
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


# Attempt-scoped checkpoints (issue #1947): a checkpoint key under this prefix
# records something THIS run did, so `--strip-inherited-checkpoints` clears such rows
# from the `## Progress` section it rewrites (a survivor elsewhere draws its warning).
_ATTEMPT_CHECKPOINT_KEY_PREFIX = 'attempt:'
_ATTEMPT_CHECKPOINT_MARKER_RE = re.compile(
    _MARKER_NS_RE + 'checkpoint ' + re.escape(_ATTEMPT_CHECKPOINT_KEY_PREFIX))


def _strip_required_artifact_checkpoint_rows(content: str) -> str:
    """Strip inherited required-artifact keys in either namespace.
    The declared keys exclude gha run-scoped rows, which remain untouched."""
    kept = [ln for ln in content.splitlines(keepends=True)
            if not any(v in ln for v in _REQUIRED_ARTIFACT_MARKER_VARIANTS)]
    return ''.join(kept)


class _NoOpReplay(Exception):
    """Successful checkpoint/tick replay, raised before mutation.
    The caller may echo the unchanged body but neither timestamps nor PATCHes it."""

    def __init__(self, kind: str = 'checkpoint'):
        super().__init__(kind)
        self.kind = kind


def _has_non_checkpoint_mutation(args) -> bool:
    """True when the update carries at least one mutation OTHER than `--checkpoint`/`--replace-checkpoint`.

    Drives the AC14 idempotency short-circuit: a checkpoint-only call whose keys are
    all already present and that carries no other mutation is a pure no-op. A
    `--checkpoint` combined with any of these still refreshes `Last updated` and
    PATCHes once (and does not duplicate an existing checkpoint)."""
    return any([
        args.status, args.branch, getattr(args, 'branch_from_head', False),
        args.run_link, args.pr_link,
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
        getattr(args, 'record_completion_evidence_cloud_ci', None),
        getattr(args, 'invalidate_completion_evidence', False),
        getattr(args, 'record_review_coverage', None),
        getattr(args, 'review_coverage_disposition', None),
        getattr(args, 'strip_inherited_checkpoints', False),
        getattr(args, 'reconcile_extension_rows', False),
        getattr(args, 'record_resume_point', None),
        getattr(args, 'record_verification_evidence', False),
        getattr(args, 'record_plan_inputs', False),
        getattr(args, 'record_reusable_review', None),
        getattr(args, 'adopt_reusable_review', False),
        getattr(args, 'resolve_doc_reflection', None),
        getattr(args, 'strip_prior_status_marker', False),
    ])


# `update` operands that select or guard the call rather than mutate the body.
_REPLAY_CONTEXT_ARGS = frozenset({
    'issue', 'marker', 'repo_root', 'claim_identity', 'expect_comment_id',
    'expect_status', 'print_body', 'func', 'cmd',
})
_TICK_ARGS = frozenset({
    'tick_progress', 'tick_plan', 'tick_plan_n', 'tick_ac', 'tick_ac_n',
})


def _is_satisfied_tick_replay(body: str, args) -> bool:
    """Recognize calls containing only already-satisfied ticks through the real resolvers.
    Misses, new ticks and any other mutation keep ordinary validation. All operands
    outside _REPLAY_CONTEXT_ARGS count, so new flags cannot silently disappear."""
    tick_reqs = (
        ('Progress', list(args.tick_progress or []), []),
        ('Plan', list(args.tick_plan or []), list(args.tick_plan_n or [])),
        ('Acceptance Criteria', list(args.tick_ac or []),
         list(args.tick_ac_n or [])),
    )
    if not any(substrs or ns for _section, substrs, ns in tick_reqs):
        return False
    if any(value for name, value in vars(args).items()
           if name not in _REPLAY_CONTEXT_ARGS and name not in _TICK_ARGS):
        return False

    _preamble, sections = _split_sections(body)
    for section_name, substrs, ns in tick_reqs:
        if not substrs and not ns:
            continue
        idx = _find_section(sections, section_name)
        if idx is None:
            return False
        _heading, content = sections[idx]
        for text in substrs:
            try:
                content, ticked_now = _tick_checkbox(content, text, section_name)
            except _TickMatchError:
                return False
            if ticked_now:
                return False
        for n in ns:
            try:
                content, ticked_now = _tick_checkbox_by_index(
                    content, n, section_name)
            except _TickMatchError:
                return False
            if ticked_now:
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


def _plan_checkpoints(body: str, checkpoint_reqs,
                      flag: str = '--checkpoint') -> list[tuple[str, str]]:
    """Validate all checkpoint requests before returning absent (key, text) pairs.
    Exactly one in-Progress marker is replay. Reject invalid/repeated keys, empty
    body, missing/duplicate Progress, and outside/duplicate markers.
    Replace-checkpoint reuses validation; flag names the caller in diagnostics."""
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
        _require_arity(flag, _req, 2, ('KEY', 'TEXT'))
        key, _text = _req
        if not _CHECKPOINT_KEY_RE.match(key):
            raise _UpdateError(
                f"{flag} key {key!r} is invalid; keys must match "
                f"[A-Za-z0-9._:-]+ . No PATCH was made."
            )
        if key in _seen_keys:
            raise _UpdateError(
                f"{flag} key {key!r} appears more than once in a single "
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
                    f"{flag} key {key!r} is in the reserved {_prefix!r} "
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
                f"{flag} text for key {key!r} must be a single line (a line "
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
            f"{flag} requires a canonical workpad body, but the body is "
            "empty/whitespace-only [empty-body]. Remedy: reconstruct the workpad "
            "with `workpad.py new-body` + `create` (a whitespace-only body has no "
            "front matter, so re-creating one section alone would still fail every "
            "other mutation). No PATCH was made."
        )
    _pre, _sections = _split_sections(body)
    n_prog = sum(1 for h, _c in _sections if h.strip().lower() == '## progress')
    if n_prog != 1:
        raise _UpdateError(
            f"{flag} requires exactly one '## Progress' section, but "
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
                f"{flag} key {key!r} marker appears outside the "
                f"'## Progress' section [marker-anomaly]. Remedy: move the "
                f"checkpoint row into '## Progress' (its marker is only read there); "
                f"choosing which copy is authoritative cannot be automated. No PATCH "
                f"was made."
            )
        if in_prog > 1:
            raise _UpdateError(
                f"{flag} key {key!r} marker appears {in_prog} times in "
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
    """Validate the offline five-field handoff against schema and issue/run identity.
    Always exit 0 with created-current-run, adopted-existing or unknown.
    Invalid/unreadable state prints a diagnostic; explicit valid unknown does not."""
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
    """Write the five-field advisory handoff, normalizing unknown origin tokens.
    Print nothing. Write/issue-conversion errors raise for the workflow to warn;
    the reader then degrades absent or invalid provenance to unknown."""
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


def _check_rewrites_match_records(rows, records) -> None:
    """When records accompany rewrites, require a one-to-one normalized OLD/NEW match
    with actual before/after row text. Without records retain the ordinary behavior.
    Refuse before PATCH so a partial replacement cannot claim a full-text rewrite."""
    if not records:
        return
    pool = {}
    for _pr, o, n in records:
        pool.setdefault((normalize_criterion(o), normalize_criterion(n)), []).append((o, n))
    for before, after in rows:
        key = (normalize_criterion(before), normalize_criterion(after))
        if pool.get(key):
            pool[key].pop()
            continue
        # State both sides rather than guess which operand is wrong: the fragment
        # may have picked the wrong row, or either record text may be the error.
        unused = [pair for pairs in pool.values() for pair in pairs]
        raise _UpdateError(
            f"--rewrite-ac rewrote the Acceptance Criteria row reading {before!r} to "
            f"{after!r}, and no unmatched --scope-decision-rewritten record in this "
            f"call reads OLD {before!r} and NEW {after!r} (unmatched records: "
            f"{', '.join(f'{o!r} -> {n!r}' for o, n in unused) or 'none'}). "
            f"--rewrite-ac replaces the whole row: correct its OLD fragment, its NEW "
            f"(the complete new criterion) or the record, one record per rewritten "
            f"row. No PATCH was made."
        )
    leftover = next((pair for pairs in pool.values() for pair in pairs), None)
    if leftover:
        raise _UpdateError(
            f"--scope-decision-rewritten record {leftover[0]!r} -> {leftover[1]!r} "
            f"matches no row this call's --rewrite-ac rewrites; each record must "
            f"describe one rewrite in the same call. No PATCH was made."
        )


def _resolve_head_branch() -> str:
    """The current checkout's branch name via `git branch --show-current`, for
    `--branch-from-head`. Resolved in-process so the caller emits no command
    substitution the cloud matcher refuses (issue #38; denied on runs 33289765650,
    33289731060). Fails closed: a non-zero git exit, a subprocess failure (git absent
    via OSError, or the 5s timeout via subprocess.SubprocessError), and a detached HEAD
    (empty output) raise `_UpdateError` with a named breadcrumb; the caller then makes
    no PATCH, leaving the Branch line unchanged."""
    try:
        proc = subprocess.run(
            ['git', 'branch', '--show-current'],
            capture_output=True, text=True, encoding="utf-8", timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _UpdateError(
            f'--branch-from-head: could not run git branch --show-current ({exc})'
        )
    if proc.returncode != 0:
        raise _UpdateError(
            '--branch-from-head: git branch --show-current exited '
            f'{proc.returncode}: {(proc.stderr or "").strip()}'
        )
    name = proc.stdout.strip()
    if not name:
        raise _UpdateError(
            '--branch-from-head: git branch --show-current returned no branch name '
            '(detached HEAD) — refusing to write an empty Branch line'
        )
    return name


class _CompletionEvidencePlan(NamedTuple):
    progress_rows: tuple[str, ...]
    strip_all: bool
    verification_row: str | None


def _plan_completion_evidence(args, recorded_at: datetime.datetime) -> _CompletionEvidencePlan:
    """Validate completion recording and compose its rows without inspecting the workpad."""
    rows: list[str] = []
    verification_row = None
    flight_key = getattr(args, 'record_completion_evidence', None)
    if flight_key:
        _validate_flight_key(args, flight_key)
        marker = _checkpoint_marker(_COMPLETION_MARKER_KEY_PREFIX + flight_key)
        rows.append(
            f'Completion verification recorded (flight {flight_key[:12]}…, '
            f'validated) {marker}')

    record_ci = getattr(args, 'record_completion_evidence_ci', None)
    if record_ci:
        _require_arity('--record-completion-evidence-ci', record_ci, 3,
                       ('HEAD_SHA', 'TIER', 'RUN_URL'))
        head, tier, url = record_ci
        owner = _reserved_checkpoint_marker_owner(url)
        if owner:
            raise _reserved_marker_error('the --record-completion-evidence-ci run URL', owner)
        checks = []
        for pair in getattr(args, 'completion_ci_check', None) or []:
            _require_arity('--completion-ci-check', pair, 2, ('NAME', 'CONCLUSION'))
            checks.append({'name': pair[0], 'conclusion': pair[1]})
        payload = _encode_ci_payload({
            'head_sha': head, 'tier': tier, 'run_url': url, 'checks': checks,
        })
        _validate_ci_evidence(args, payload)
        verification_row = _verification_evidence_row(
            command='gh pr checks',
            outcome=', '.join(f"{c['name']}={c['conclusion']}" for c in checks),
            run_roots=[url], tallies=None, elapsed=None, started_at=None,
            recorded_at=recorded_at.strftime('%Y-%m-%dT%H:%M:%SZ'), head=head)
        marker = _checkpoint_marker(_COMPLETION_CI_MARKER_KEY_PREFIX + payload)
        rows.append(
            f'completion evidence recorded from CI reading '
            f'(head {head[:12]}…, {url}, validated) {marker}')

    cloud_file = getattr(args, 'record_completion_evidence_cloud_ci', None)
    if cloud_file:
        try:
            with open(cloud_file, encoding='utf-8') as stream:
                record = json.load(stream)
        except (OSError, ValueError) as error:
            raise _UpdateError(
                f"--record-completion-evidence-cloud-ci: could not read a JSON record "
                f"from {cloud_file!r} ({error.__class__.__name__}). No PATCH was made."
            )
        payload = _encode_ci_payload(record, compress=True)
        _validate_cloud_ci_evidence(args, payload)
        # Validation establishes the record shape before any field is read.
        url = str(record.get('run_url', ''))
        owner = _reserved_checkpoint_marker_owner(url)
        if owner:
            raise _reserved_marker_error('the --record-completion-evidence-cloud-ci run_url', owner)
        head = str(record.get('head_sha', ''))[:12]
        marker = _checkpoint_marker(_COMPLETION_CLOUD_CI_MARKER_KEY_PREFIX + payload)
        rows.append(
            f'completion evidence recorded from cloud CI '
            f'(head {head}…, {url}, validated) {marker}')

    return _CompletionEvidencePlan(
        tuple(rows), bool(rows or getattr(args, 'invalidate_completion_evidence', False)),
        verification_row)


def _apply_mutations(body: str, args, failed_ticks) -> str:
    """Return the mutated body or raise _UpdateError for structural failure; never PATCH here.
    Collect volatile row misses in required failed_ticks while retaining other mutations.
    The caller persists the body, then reports those misses."""
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    # Friendly UTC for the human-facing `Last updated` line (the `now`
    # subcommand still prints full ISO-8601 for machine uses like follow-up
    # issue bodies; note bullets keep their time-only HH:MM:SS prefix).
    last_updated = now_dt.strftime('%Y-%m-%d %H:%M UTC')
    now_time = now_dt.strftime('%H:%M:%S')        # time-only for note bullets

    # Plan checkpoints before mutation; an all-replayed checkpoint-only call skips PATCH.
    checkpoint_reqs = getattr(args, 'checkpoint', None) or []
    # Arity before ANY positional unpack of a checkpoint request (issue #1501): the
    # --strip-inherited-checkpoints clash set below unpacks `k, _t` before
    # _plan_checkpoints runs, so a wrong-length element on the strip path would raise a
    # bare ValueError there rather than the named refusal. Validate every element here,
    # above that unpack; _plan_checkpoints keeps its own guard for its standalone contract.
    for _req in checkpoint_reqs:
        _require_arity('--checkpoint', _req, 2, ('KEY', 'TEXT'))
    # `--replace-checkpoint` (issue #1947): the upsert sibling of `--checkpoint`. A
    # key absent from ## Progress is inserted, a present row is replaced; a row with the
    # current marker and the same text is a replay. One key under both flags is ambiguous.
    replace_reqs = getattr(args, 'replace_checkpoint', None) or []
    for _req in replace_reqs:
        _require_arity('--replace-checkpoint', _req, 2, ('KEY', 'TEXT'))
    _both = sorted({k for k, _t in checkpoint_reqs} & {k for k, _t in replace_reqs})
    if _both:
        raise _UpdateError(
            "--checkpoint and --replace-checkpoint name the same key(s): "
            f"{', '.join(_both)}. Pass each key to one flag. No PATCH was made.")
    replace_writes: list[tuple[str, str]] = []
    checkpoint_inserts: list[tuple[str, str]] = []
    # Bound here, not inside the `if checkpoint_reqs:` arm below, because the
    # deferred announce at this function's return reads it on EVERY path.
    _did_repair = False
    strip_inherited = bool(getattr(args, 'strip_inherited_checkpoints', False))
    if strip_inherited:
        # Reject strip+insert for the same key: planning sees the pre-strip row as replay,
        # so stripping it afterward would silently lose the record.
        _clash = sorted(
            k for k, _t in [*checkpoint_reqs, *replace_reqs]
            if k in _REQUIRED_ARTIFACT_CHECKPOINT_KEYS
            or k.startswith(_ATTEMPT_CHECKPOINT_KEY_PREFIX)
        )
        if _clash:
            raise _UpdateError(
                "--strip-inherited-checkpoints cannot be combined with "
                f"--checkpoint or --replace-checkpoint for the same stripped key(s): "
                f"{', '.join(_clash)}. "
                "Strip and record in separate calls. No PATCH was made."
            )
    if checkpoint_reqs or replace_reqs:
        # Repair an absent `## Progress` BEFORE the section-shape validation below,
        # so the validation sees the repaired body (issue #1347). The breadcrumb for
        # it is deferred all the way to this function's successful return — see the
        # announce site there for why "after `_plan_checkpoints`" was not far enough.
        _repaired_body = _repair_missing_progress_section(body)
        _did_repair = _repaired_body is not body
        body = _repaired_body
        if checkpoint_reqs:
            checkpoint_inserts = _plan_checkpoints(body, checkpoint_reqs)
        if replace_reqs:
            _plan_checkpoints(body, replace_reqs, '--replace-checkpoint')
            # A whole rendered row, never a substring: a stored `A — B` is not `B`.
            _progress = _progress_content_or_none(body)
            replace_writes = [
                (k, t) for k, t in replace_reqs
                if not _note_already_rendered(_progress, f'{t} {_checkpoint_marker(k)}')]
        if (not checkpoint_inserts and not replace_writes
                and not _has_non_checkpoint_mutation(args)):
            raise _NoOpReplay()

    # A resumed run can repeat a tick whose row an earlier call already ticked.
    # Decide that pure replay before Last updated or any other body mutation.
    if _is_satisfied_tick_replay(body, args):
        raise _NoOpReplay('satisfied-ticks')

    completion_plan = _plan_completion_evidence(args, now_dt)
    verification_evidence_rows = (
        [completion_plan.verification_row] if completion_plan.verification_row is not None else [])
    _ve_recorded_at = now_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    # Phase 2 sweep-evidence recording (issue #438). Read from a FILE (a JSON object
    # too large for a CLI operand), validated and size-checked BEFORE any body
    # mutation — a refused record changes nothing (all-or-nothing). The per-run strip +
    # append (below) replaces this run's prior row.
    record_sweep_evidence_file = getattr(args, 'record_sweep_evidence', None)
    sweep_evidence_payload = None
    sweep_evidence_run_identity = None
    sweep_evidence_record = None
    if record_sweep_evidence_file:
        try:
            with open(record_sweep_evidence_file, encoding='utf-8') as _fh:
                sweep_evidence_record = json.load(_fh)
        except (OSError, ValueError) as e:
            raise _UpdateError(
                f"--record-sweep-evidence: could not read a JSON record from "
                f"{record_sweep_evidence_file!r} ({e.__class__.__name__}). No PATCH "
                f"was made."
            )
        sweep_evidence_run_identity = (
            sweep_evidence_record.get('run_identity')
            if isinstance(sweep_evidence_record, dict) else None)
        _validate_sweep_evidence(sweep_evidence_record)
        sweep_evidence_payload = _encode_ci_payload(sweep_evidence_record)
        if len(sweep_evidence_payload) > _NOTE_BYTE_BUDGET:
            raise _UpdateError(
                f"sweep evidence rejected [payload-over-budget]: the encoded record is "
                f"{len(sweep_evidence_payload)} bytes, over the {_NOTE_BYTE_BUDGET}-byte "
                f"budget; shorten its evidence references. No PATCH was made."
            )

    # Validate BEFORE any body mutation (no PATCH on refusal). The head is stamped here,
    # never caller-supplied: a passed-in head could name a commit the suite never ran on.
    if getattr(args, 'record_verification_evidence', False):
        _ve_command = getattr(args, 'command', None)
        _ve_outcome = getattr(args, 'outcome', None)
        _ve_run_roots = list(getattr(args, 'run_root', None) or [])
        _validate_verification_evidence(_ve_command, _ve_outcome, _ve_run_roots)
        verification_evidence_rows.append(_verification_evidence_row(
            _ve_command, _ve_outcome, _ve_run_roots,
            getattr(args, 'tallies', None), getattr(args, 'elapsed', None),
            getattr(args, 'started_at', None), _ve_recorded_at,
            _git_head_or_unestablished(_devflow_repo_root(args))))

    # Mid-phase resume-point record (issue #1876). No validation — it is a NAVIGATION
    # aid, never evidence — so unlike the completion families above it needs no
    # before-mutation validation pass; the payload is encoded here and the row written
    # below (replacing any prior resume-point row).
    record_resume_point = getattr(args, 'record_resume_point', None)
    resume_point_payload = (
        _encode_resume_point(record_resume_point) if record_resume_point else None)

    # Issue #2026: a human review waiver is caller authorization, never review
    # evidence — so it writes no review record.
    review_waived_by = getattr(args, 'review_waived_by', None)
    _wv_note = None
    if review_waived_by is not None:
        if not (args.status and _status_glyph(args.status) == '🎉'):
            raise _UpdateError(
                "--review-waived-by is accepted only with --status Complete. "
                "No PATCH was made.")
        if not review_waived_by.strip():
            raise _UpdateError(
                "--review-waived-by: SOURCE must be a non-empty reference to the human "
                "instruction that waived review. No PATCH was made.")
        if not _is_single_line(review_waived_by):
            raise _UpdateError(
                "--review-waived-by: SOURCE must be a single line. No PATCH was made.")
        _wv_note = (
            f'Review waived by human instruction ({review_waived_by.strip()}) — the '
            'review-coverage prerequisite was not applied; this change remains '
            # The marker keeps `compact` from relocating the disclosure.
            'unverified by review ' + _checkpoint_marker(_REVIEW_WAIVED_KEY))
        if _byte_len(_wv_note) > _NOTE_BYTE_BUDGET:
            raise _UpdateError(
                f"--review-waived-by: its disclosure note is over the {_NOTE_BYTE_BUDGET}-"
                "byte per-note budget (measured as UTF-8 bytes); shorten SOURCE. "
                "No PATCH was made.")
        if any(getattr(args, _f, None) for _f in (
                'record_review_coverage', 'record_roster_member', 'record_reusable_review',
                'adopt_reusable_review', 'review_coverage_disposition')):
            raise _UpdateError(
                "--review-waived-by cannot be combined with --record-review-coverage, "
                "--record-roster-member, --record-reusable-review, --adopt-reusable-review "
                "or --review-coverage-disposition: a waiver is not review evidence. "
                "No PATCH was made.")
        _wv_owner = _reserved_checkpoint_marker_owner(review_waived_by)
        if _wv_owner:
            raise _reserved_marker_error("the --review-waived-by source", _wv_owner)
    # Validate coverage before mutation. Reuse adoption follows the same validators
    # as fresh measurements; getattr permits older programmatic argument shapes.
    adopt_review = bool(getattr(args, 'adopt_reusable_review', False))
    adopted_review = None
    if adopt_review:
        if (getattr(args, 'record_review_coverage', None)
                or getattr(args, 'record_roster_member', None)
                or getattr(args, 'record_reusable_review', None)):
            raise _UpdateError(
                "--adopt-reusable-review cannot be combined with "
                "--record-review-coverage, --record-roster-member or "
                "--record-reusable-review. No PATCH was made."
            )
        _ar_content = _progress_content_or_none(body)
        if _ar_content is None:
            raise _UpdateError(
                "--adopt-reusable-review: the workpad does not carry exactly one "
                "'## Progress' section. No PATCH was made."
            )
        _ar_result, _ar_detail, adopted_review = _reuse_evaluate(
            _ar_content, 'review', args.issue,
            getattr(args, 'repo_root', None) or _repo_root())
        if _ar_result != 'match':
            raise _UpdateError(
                f"--adopt-reusable-review: the reusable-review record is not "
                f"reusable (result={_ar_result}"
                + (f", {_ar_detail}" if _ar_detail else '')
                + "). No PATCH was made."
            )
        args = argparse.Namespace(**vars(args))
        args.record_review_coverage = [
            'full', 'attempted', 'complete', adopted_review['checklist']]
        args.record_review_coverage_head = adopted_review['head']
        args.record_roster_member = [
            [m, st] for m, st in sorted(adopted_review['roster'].items())]
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
        # issue #42: normalize the `all` alias to `complete` on ROSTER/CHECKLIST only, and
        # keep it ABOVE the vocabulary loop — below it, `all` on roster/checklist reaches the
        # check unnormalized and is refused, breaking the alias.
        review_coverage = [
            'complete' if axis in ('roster', 'checklist') and value == 'all' else value
            for axis, value in zip(_REVIEW_COVERAGE_AXES, review_coverage)
        ]
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
        # Recompute intentional-skip eligibility at the reviewed head/base.
        # Disproved claims fail; unknown measurements become unestablished; override
        # becomes non-clean skipped. Copy only after arity validation.
        review_coverage = list(review_coverage)
        _checklist_idx = _REVIEW_COVERAGE_AXES.index('checklist')
        if review_coverage[_checklist_idx] == 'skipped-intentional':
            _rc_repo_root = getattr(args, 'repo_root', None) or _repo_root()
            # issue #359: measure against the CONFIGURED base (origin/<base_branch>,
            # origin/main when unset) — never origin/HEAD, which is the repo default
            # branch locally and is absent on a cloud checkout. Malformed config → unestablished.
            _rc_base, _rc_base_err = _review_coverage_base_ref(_rc_repo_root)
            if _rc_base_err is not None:
                sys.stderr.write(
                    'workpad.py: review-coverage base branch could not be '
                    f'resolved — {_rc_base_err}\n')
                _rc_facts = {'resolved': False, 'reason': _rc_base_err}
            else:
                _rc_facts = _recompute_diff_facts(
                    _anchor_head, _rc_base, _rc_repo_root)
            if not _rc_facts['resolved']:
                review_coverage[_checklist_idx] = 'unestablished'
                review_coverage_auto_notes.append(
                    'review-coverage checklist recorded `unestablished` — the '
                    'skipped-intentional diff could not be recomputed: '
                    + _rc_facts['reason'])
            else:
                _rc_disproof = _review_coverage_profile_disproof(_rc_facts)
                if _rc_disproof:
                    raise _UpdateError(
                        "--record-review-coverage: a `skipped-intentional` "
                        "checklist claim is not authorized by the diff (measured "
                        f"{_rc_facts['files']} file(s), {_rc_facts['lines']} "
                        f"line(s)): {_rc_disproof}. No PATCH was made."
                    )
                # AC4: a confirmed write reports the measured values on success.
                sys.stderr.write(
                    'workpad.py: review-coverage skipped-intentional confirmed — '
                    f"{_rc_facts['files']} changed file(s), {_rc_facts['lines']} "
                    f'changed line(s), path-set config-only\n')
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
        member = _normalize_roster_member(member)
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
        # with a measured roster needs the combined roster row's per-member entries
        # proving members were dispatched.
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
    # Reusable-review record (issue #616): written only beside a clean full-coverage
    # record. A caller pairing it with any other record is refused; an input this
    # call cannot resolve skips the record with a note, so the coverage record still
    # lands and a later attempt simply finds nothing to reuse.
    reusable_review_payload = None
    reuse_skip_notes: list[str] = []
    _rr_verdict = getattr(args, 'record_reusable_review', None)
    if _rr_verdict is not None:
        if _rr_verdict not in _REUSABLE_REVIEW_VERDICTS:
            raise _UpdateError(
                f"--record-reusable-review: unknown verdict {_rr_verdict!r}; expected "
                f"one of {', '.join(_REUSABLE_REVIEW_VERDICTS)}. No PATCH was made."
            )
        if not review_coverage_payload:
            raise _UpdateError(
                "--record-reusable-review must accompany --record-review-coverage. "
                "No PATCH was made."
            )
        _rr_axes = dict(zip(_REVIEW_COVERAGE_AXES, review_coverage))
        _rr_downgraded = (_rr_axes['checklist'] == 'unestablished'
                          and bool(review_coverage_auto_notes))
        if ((_rr_axes['coverage'], _rr_axes['dispatch'], _rr_axes['roster'])
                != ('full', 'attempted', 'complete')
                or (_rr_axes['checklist'] not in _REUSABLE_REVIEW_CHECKLISTS
                    and not _rr_downgraded)):
            raise _UpdateError(
                "--record-reusable-review requires a clean full-coverage record "
                "(full attempted complete complete|skipped-intentional). "
                "No PATCH was made."
            )
        if _anchor_head == _REVIEW_COVERAGE_ANCHOR_UNESTABLISHED:
            raise _UpdateError(
                "--record-reusable-review requires --record-review-coverage-head. "
                "No PATCH was made."
            )
        if _rr_downgraded:
            reuse_skip_notes.append(
                'reusable-review record not written — the checklist axis was '
                'recorded unestablished')
        else:
            _rr_candidate, _rr_err = _reuse_candidate(
                _anchor_head, getattr(args, 'repo_root', None) or _repo_root())
            _rr_digest = None
            if _rr_err is None:
                _rr_digest, _rr_err = _reuse_issue_digest(args.issue)
            if _rr_err is not None:
                sys.stderr.write(
                    f'workpad.py: reusable-review record not written — {_rr_err}\n')
                reuse_skip_notes.append(
                    'reusable-review record not written — its inputs did not resolve')
            else:
                reusable_review_payload = ':'.join((
                    _rr_candidate['head'], _rr_candidate['merge_base'], _rr_digest,
                    _rr_verdict, _rr_axes['checklist'],
                    _encode_reuse_roster(roster_members)))
    # Plan-inputs record (issue #616): an unreadable issue body removes the old
    # record without writing a new one, so a replaced Plan is never vouched for by
    # a record written for an earlier Plan.
    record_plan_inputs = bool(getattr(args, 'record_plan_inputs', False))
    plan_inputs_digest = None
    if record_plan_inputs:
        plan_inputs_digest, _pi_err = _reuse_issue_digest(args.issue)
        if _pi_err is not None:
            sys.stderr.write(
                f'workpad.py: plan-inputs record not written — {_pi_err}\n')
            reuse_skip_notes.append(
                'plan-inputs record not written — the issue body did not resolve')
    review_dispositions = list(getattr(args, 'review_coverage_disposition', []) or [])
    _seen_gaps: set[str] = set()
    # #1984: `environment-denial` must be corroborated by a recorded `missing` roster
    # row (the denied member) — read the durable rows already in ## Progress and merge
    # this call's own rows, so a disposition recorded in a later call than the roster
    # enumeration still sees it. Guarded by `review_dispositions` so a note-only or
    # checkpoint update pays no extra section parse.
    _disp_has_missing = _disp_has_dispatched = False
    if review_dispositions:
        if review_coverage_payload:
            # This call re-stamps coverage, which strips the prior roster rows before the
            # append below, so the durable state is exactly this call's own enumeration;
            # reading the pre-strip body (which may not decode) would refuse the re-stamp
            # that fixes it.
            _disp_roster = dict(roster_members)
        else:
            _disp_existing = _review_roster_members(
                _progress_content_or_none(body) or '')
            if _disp_existing is _REVIEW_ROSTER_UNDECODABLE:
                raise _UpdateError(
                    "--review-coverage-disposition: "
                    + _REVIEW_ROSTER_UNDECODABLE_TAIL)
            _disp_roster = dict(_disp_existing)
            _disp_roster.update(roster_members)
        _disp_has_missing, _disp_has_dispatched = _review_coverage_roster_facts(
            _disp_roster)
    for _triple in review_dispositions:
        # Validate programmatic arguments too: argparse's nargs does not protect those callers.
        _require_arity('--review-coverage-disposition', _triple, 3,
                       ('gap', 'cause-class', 'reason'))
    for gap, cause_class, reason in review_dispositions:
        # The reason is caller-supplied and embedded verbatim in the exempted producer
        # row, so screen it for a reserved marker before that row is composed (issue #321).
        _disp_owner = _reserved_checkpoint_marker_owner(reason)
        if _disp_owner:
            raise _reserved_marker_error(
                "the --review-coverage-disposition reason", _disp_owner)
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
            cause_class, has_missing_roster_row=_disp_has_missing,
            has_dispatched_roster_row=_disp_has_dispatched)
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
    branch_value = args.branch
    if getattr(args, 'branch_from_head', False):
        if args.branch is not None:
            raise _UpdateError(
                '--branch and --branch-from-head are mutually exclusive; pass '
                'exactly one'
            )
        branch_value = _resolve_head_branch()
    if branch_value:
        body, n = _BRANCH_RE.subn(
            lambda _m: f'**Branch:** `{branch_value}`', body, count=1,
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

    # Repair row shapes before ticks so a same-call tick can find its inserted row.
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

    # Replace whole sections before ticks so indices address the new rows.
    if args.replace_plan_file:
        new_content = _read_section_file(args.replace_plan_file, '--replace-plan-file')
        # Carry each old ticked row's tick onto the new row with the same text
        # (issue #635) so a re-plan no longer unticks the steps that already
        # landed. Same in-memory mutation as the replacement, so both ride one PATCH.
        _plan_idx = _find_section(sections, 'Plan')
        if _plan_idx is not None:
            new_content = _carry_forward_ticks(
                sections[_plan_idx][1], new_content)
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
    # Only Complete backfills parent-phase ticks. Use the same glyph predicate as
    # the terminal gate so their Complete classifications cannot diverge.
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
        # Retagging a previously untagged row needs a nonempty Progress note.
        # This proves a note exists, not its truth or connection to that row.
        # Only rewrite-ac is covered; replace-acs-file remains outside this guard.
        # Validate pair arity before indexing/unpacking programmatic arguments.
        for _pair in args.rewrite_ac:
            _require_arity('--rewrite-ac', _pair, 2, ('OLD', 'NEW'))
        has_note = any(n.strip() for n in args.note) or bool(getattr(args, 'note_file', None))
        # Reject every splitlines boundary in NEW before rewriting.
        # Injected rows would bypass terminal-tag checks and destroy stable row positions.
        offending_nl = next((p for p in args.rewrite_ac if not _is_single_line(p[1])),
                            None)
        if offending_nl:
            raise _UpdateError(
                f"--rewrite-ac pair {offending_nl[0]!r} -> {offending_nl[1]!r} has a line "
                f"boundary in NEW; an AC row is a single line (it would split into an "
                f"extra, unreviewed row). No PATCH was made."
            )
        # Apply repeated rewrites in order to local content; any ambiguous/missing row
        # aborts before the section is assigned or PATCHed.
        heading, content = sections[idx]
        # Compare tag flags positionally to catch multi-pair nonterminal-to-terminal
        # shuttles and remove-one/add-one swaps. Include ticked rows.
        # Single-line replacement preserves positions; replace-acs-file remains out of scope.
        pre_pm = _post_merge_flags(content)
        # Row index -> [text before this call, text after it], for the record
        # cross-check below. Indices are stable for the reason given above.
        rewritten_rows: dict[int, list[str]] = {}
        for old, new in args.rewrite_ac:
            # Resolve the row this pair targets with the rewriter's own resolution.
            _, _row_idx, _row_m = _find_checkbox_row(content, old, 'Acceptance Criteria')
            _row_text = _row_m.group(4)
            rewritten_rows.setdefault(_row_idx, [_row_text, new])[1] = new
            # Without a note, ask whether the pair terminally tags the row it targets.
            if not has_note and _pair_appends_post_merge(old, new, _row_text):
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
        _check_rewrites_match_records(
            rewritten_rows.values(), getattr(args, 'scope_decision_rewritten', None) or [])
        sections[idx] = (heading, content)

    # Append notes before checkpoint/scope/filed records through one Progress path.
    # Keep machine records isolated so their readers can reject prose-embedded markers.
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
    # Suppress a note only when identical text is recorded by an inserted or existing
    # checkpoint row. A replayed key with different text does not cover the new note.
    _checkpoint_covered_texts = {text for _key, text in checkpoint_inserts + replace_writes}
    for _ckey, _ctext in checkpoint_reqs + replace_reqs:
        if f'{_ctext} {_checkpoint_marker(_ckey)}' in body:
            _checkpoint_covered_texts.add(_ctext)
    # --note-file payloads (issues #1813/#2076) are ordinary notes appended AFTER
    # the inline --note bullets, one per path in command-line order, mirroring the
    # --reflection/--reflection-file order. The reads are memoized (see
    # `_note_file_payloads`), so this reuses the text `_cmd_update_inner` already
    # read for buffering rather than re-reading it.
    _notes_in = list(args.note)
    if getattr(args, 'note_file', None):
        _notes_in.extend(_note_file_payloads(args))
    _notes = [n for n in _notes_in if n not in _checkpoint_covered_texts]
    # issue #1509: a review-coverage downgrade/override records its reason as an ordinary
    # ## Progress note alongside the (mutated) record row.
    progress_notes = _notes + review_coverage_auto_notes + scope_decision_notes + deferred_filed_notes + [
        f'{text} {_checkpoint_marker(key)}'
        for key, text in checkpoint_inserts + replace_writes
    ]
    progress_notes.extend(completion_plan.progress_rows)
    _producer_reserved_rows = set(completion_plan.progress_rows)
    # Mid-phase resume-point marker (issue #1876): a later record REPLACES the prior
    # one, so any existing resume-point row is stripped below before this is appended.
    if resume_point_payload:
        _rp_ck = _RESUME_POINT_MARKER_KEY_PREFIX + resume_point_payload
        _rp_row = f'mid-phase resume point recorded {_checkpoint_marker(_rp_ck)}'
        progress_notes.append(_rp_row)
        _producer_reserved_rows.add(_rp_row)
    # Sweep-evidence record (issue #438): REPLACES this run's prior row (the per-run
    # strip below), so the reader sees exactly one record per run identity.
    if sweep_evidence_payload:
        _se_ck = (_SWEEP_EVIDENCE_KEY_PREFIX + sweep_evidence_run_identity
                  + ':' + sweep_evidence_payload)
        _se_row = (
            f'sweep evidence recorded (run {sweep_evidence_run_identity}: '
            f'{len(sweep_evidence_record["selected_sweeps"])} sweeps, '
            f'{len(sweep_evidence_record["catches"])} catches) '
            f'{_checkpoint_marker(_se_ck)}')
        progress_notes.append(_se_row)
        _producer_reserved_rows.add(_se_row)
    # Resume-reuse records (issue #616): validated above; the prior row of each
    # family is stripped just before the append loop.
    if plan_inputs_digest:
        _pi_row = (f'Plan-inputs recorded (issue body {plan_inputs_digest[:12]}…) '
                   f'{_checkpoint_marker(_PLAN_INPUTS_KEY_PREFIX + plan_inputs_digest)}')
        progress_notes.append(_pi_row)
        _producer_reserved_rows.add(_pi_row)
    if reusable_review_payload:
        _rr_origin = ':'.join(filter(None, (
            os.environ.get('GITHUB_RUN_ID'),
            os.environ.get('GITHUB_RUN_ATTEMPT')))) or 'local'
        _rr_row = (
            f'reusable review recorded ({_rr_verdict}; head '
            f'{_rr_candidate["head"][:12]}, merge-base '
            f'{_rr_candidate["merge_base"][:12]}; origin {_rr_origin}) '
            + _checkpoint_marker(_REUSABLE_REVIEW_KEY_PREFIX + reusable_review_payload))
        progress_notes.append(_rr_row)
        _producer_reserved_rows.add(_rr_row)
    if adopted_review:
        progress_notes.append(
            'review reused from the reusable-review record '
            f"({adopted_review['verdict']}; head {adopted_review['head'][:12]}); "
            'head, merge-base and issue body match')
    progress_notes.extend(reuse_skip_notes)
    # One disclosure per distinct source: a Complete follow-up repeating a source whose
    # exact note `## Progress` already renders adds none.
    if _wv_note is not None:
        _wv_idx = _find_section(sections, 'Progress')
        if not _note_already_rendered(
                sections[_wv_idx][1] if _wv_idx is not None else None, _wv_note):
            progress_notes.append(_wv_note)
            _producer_reserved_rows.add(_wv_note)
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
    if roster_members:
        _review_coverage_rows.add(
            f'{_render_review_roster(roster_members)} '
            f'{_review_roster_marker(roster_members)}'
        )
    for _gap, _cause, _reason in review_dispositions:
        _review_coverage_rows.add(
            f'{_render_review_coverage_disposition(_gap, _reason)} '
            f'{_review_coverage_disposition_marker(_gap, _cause)}'
        )
    progress_notes.extend(sorted(_review_coverage_rows))
    _producer_reserved_rows |= _review_coverage_rows
    # Inherited required-artifact strip (issue #1347). Runs on BOTH resume arms —
    # it rides its own flag rather than the cloud-only `--checkpoint`/`--expect-*`
    # set the local arm drops — and BEFORE the note append below, so a row this
    # call writes is never stripped by the same call. An absent `## Progress` is a
    # no-op: there is nothing to strip, and the strip alone never fails the call.
    if strip_inherited:
        idx = _find_section(sections, 'Progress')
        if idx is not None:
            heading, content = sections[idx]
            # Strip inherited review coverage by its shared regex; variable payloads cannot
            # join the literal required-artifact key set.
            sections[idx] = (
                heading,
                _strip_marker_rows(
                    _strip_review_coverage_marker_rows(
                        _strip_required_artifact_checkpoint_rows(content)),
                    _ATTEMPT_CHECKPOINT_MARKER_RE),
            )
        # Warn about markers surviving outside the first Progress section: whole-body
        # readers could still credit them. Do not block resume hydration on that shape.
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
        ) + (
            ['attempt-scoped checkpoint']
            if _ATTEMPT_CHECKPOINT_MARKER_RE.search(_joined) else []
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

    # Consume the resume prior-status marker (issue #137) on its own flag, before the
    # note append below (so a row this call writes is never stripped) and independently
    # of `progress_notes` (so a note-less hydration still consumes it).
    if getattr(args, 'strip_prior_status_marker', False):
        idx = _find_section(sections, 'Progress')
        if idx is not None:
            heading, content = sections[idx]
            sections[idx] = (heading, _strip_prior_status_marker_rows(content))

    # Keep the strip outside the append guard so invalidation-only calls still clear old rows.
    if completion_plan.strip_all:
        idx = _find_section(sections, 'Progress')
        if idx is not None:
            heading, content = sections[idx]
            sections[idx] = (heading, _strip_all_completion_marker_rows(content))

    # Per-run sweep-evidence strip (issue #438): only THIS run's prior row goes (another
    # run's rows are untouched); the incoming row is appended after this strip.
    if sweep_evidence_payload:
        idx = _find_section(sections, 'Progress')
        if idx is not None:
            heading, content = sections[idx]
            sections[idx] = (heading, _strip_sweep_evidence_marker_rows_for_run(
                content, sweep_evidence_run_identity))

    if progress_notes:
        idx = _find_section(sections, 'Progress')
        if idx is None:
            raise _UpdateError("section '## Progress' not found")
        heading, content = sections[idx]
        if replace_writes:
            _replaced = [v for k, _t in replace_writes
                         for v in _marker_variants(_checkpoint_marker(k))]
            content = ''.join(ln for ln in content.splitlines(keepends=True)
                              if not any(v in ln for v in _replaced))
        if resume_point_payload:
            content = _strip_resume_point_marker_rows(content)
        if record_plan_inputs:
            content = _strip_marker_rows(content, _PLAN_INPUTS_MARKER_RE)
        # A new review-coverage record supersedes an older reusable review, except
        # the adoption that re-stamps coverage from that very record.
        if review_coverage_payload and not adopt_review:
            content = _strip_marker_rows(content, _REUSABLE_REVIEW_MARKER_RE)
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
            # `_producer_reserved_rows` holds exactly the rows the validated producers
            # above composed, so the chokepoint guard admits those and refuses a
            # marker arriving through any caller-supplied text (issue #321).
            content = _append_progress_note(
                content, text, now_time, phase_label,
                reserved_marker_ok=text in _producer_reserved_rows)
        sections[idx] = (heading, content)

    if args.reflection or args.reflection_file:
        idx = _find_reflection_section(sections)
        if idx is None:
            raise _UpdateError(f"section '## {_REFLECTION_HEADING}' not found")
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
        # Append memoized file reflections after inline ones, in path order and same kind.
        # Read failures abort before PATCH; buffering reuses the exact payloads/stdin read.
        for bullet in _reflection_file_payloads(args):
            content = _append_reflection(content, kind, bullet)
        sections[idx] = (heading, content)

    # Resolve a fulfilled documentation obligation (issue #508).
    if getattr(args, 'resolve_doc_reflection', None):
        idx = _find_reflection_section(sections)
        if idx is None:
            raise _UpdateError(
                f"--resolve-doc-reflection: section '## {_REFLECTION_HEADING}' not found. "
                "No PATCH was made.")
        heading, content = sections[idx]
        for pair in args.resolve_doc_reflection:
            _require_arity('--resolve-doc-reflection', pair, 2, ('target', 'evidence'))
            target, evidence = pair
            content = _resolve_doc_reflection(content, target, evidence)
        sections[idx] = (heading, content)

    # Verification-evidence rows (issue #2131) are appended, never replacing a prior row.
    if verification_evidence_rows:
        idx = _find_reflection_section(sections)
        if idx is None:
            # An explicit call refuses (no PATCH); the CI rider's row only degrades to a
            # breadcrumb because --record-completion-evidence-ci's own contract does not
            # require the section — do not promote that degrade to a refusal.
            if getattr(args, 'record_verification_evidence', False):
                raise _UpdateError(
                    f"--record-verification-evidence: section '## {_REFLECTION_HEADING}' "
                    "not found, so the Verification evidence row cannot be recorded. "
                    "No PATCH was made."
                )
            sys.stderr.write(
                f"workpad.py: no '## {_REFLECTION_HEADING}' section — the CI reading's "
                "Verification evidence row was not appended (the completion-ci marker "
                "still recorded)\n"
            )
        else:
            heading, content = sections[idx]
            for row in verification_evidence_rows:
                content = _append_reflection(content, 'note', row)
            sections[idx] = (heading, content)

    # Every disposition emits fixed-kind dropped-failed friction, regardless of caller
    # reflection flags. Strip superseded dispositions' bullets before replacing them.
    if review_coverage_payload or review_dispositions or strip_inherited:
        idx = _find_reflection_section(sections)
        if idx is None:
            if review_dispositions:
                raise _UpdateError(
                    f"--review-coverage-disposition: section '## {_REFLECTION_HEADING}' "
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

    # Gate Complete last against post-mutation sections, allowing same-call final ticks.
    # Use the shared glyph predicate; other statuses are ungated.
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

    # Announce Progress repair only after every raising validation has passed.
    if _did_repair:
        _announce_progress_repair()
    return _join_sections(preamble, sections)


def main():
    _force_utf8_streams()
    args = _build_parser().parse_args()
    args.func(args)


def _build_parser():
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
        'export-snapshot',
        help='Write the canonical workpad body to the fixed intake-scratch '
             'intake-workpad-<issue>.md, verify the persisted bytes, and print a '
             'compact JSON receipt (exit 2 if no workpad, 3 on read failure, 4 on '
             'destination/write refusal, 5 on --expect-comment-id mismatch, 6 on '
             'read-back failure). Replaces intake\'s model-authored snapshot copy.')
    s.add_argument('issue', type=int)
    s.add_argument('--out', required=True,
                   help='Destination path; must resolve to the issue-owned '
                        'intake-workpad-<issue>.md under .prflow/tmp/ or '
                        '.prflow/tmp/implement/<issue>/ in this checkout.')
    s.add_argument('--expect-comment-id', default=None,
                   help='When set, the resolved workpad comment id must equal this '
                        'value or the export refuses (exit 5) before any write.')
    s.add_argument('--marker', default=None, help=_marker_help)
    s.set_defaults(func=cmd_export_snapshot)

    s = sub.add_parser(
        'compact',
        help='Shrink a workpad over the 40960-byte low watermark to that watermark '
             'by moving its oldest whole progress-note and "### ℹ️ Notes" bullets — '
             'never one carrying a <!-- prflow: marker, never a partial line — '
             'byte-for-byte into ONE overflow comment written BEFORE the workpad '
             'PATCH: appended to the newest overflow comment when it keeps its '
             'header lines and stays within 65536 bytes, else — or when that '
             'append fails — posted new. When the watermark is out of reach every '
             'movable bullet moves, provided the body is then at or below the '
             'smaller of its own size and 57344, less the 512-byte accounting '
             'reserve. Prints a JSON receipt. Exit 0 (compacted, '
             'or already at the watermark: no comment, no PATCH), 1 structural '
             'refusal, 2 no workpad, 3 gh failure (the workpad is left unchanged, '
             'except that a failed workpad PATCH may have landed and names the '
             'written comment), 5 unreachable '
             '(nothing movable, over the ceiling, or comment over the cap).')
    s.add_argument('issue', type=int)
    s.add_argument('--marker', default=None, help=_marker_help)
    s.set_defaults(func=cmd_compact)

    s = sub.add_parser(
        'status',
        help='Print the workpad Status as `CLASS GLYPH WORD` (CLASS is one of '
             'complete|blocked|failed|cancelled|interim). Exit 2 if no workpad, '
             'exit 1 if present but the Status is unreadable.',
    )
    s.add_argument('issue', type=int)
    s.add_argument('--marker', default=None, help=_marker_help)
    s.set_defaults(func=cmd_status)

    s = sub.add_parser(
        'intake-triage',
        help='Print implement intake\'s whole read-only workpad triage state as '
             'one JSON object — {comment_id, status_class, status_word, body, '
             'prior_status} — from one repo resolution and one marker scan, '
             'replacing the separate id/status/body/prior-status reads. Exit 1 '
             'present-but-unreadable (duplicated workpad, unreadable Status, '
             'duplicated prior-status marker), 2 cleanly absent (empty stdout), '
             '3 gh read failure. Read-only; never reuse its body for a write.',
    )
    s.add_argument('issue', type=int)
    s.add_argument('--marker', default=None, help=_marker_help)
    s.set_defaults(func=cmd_intake_triage)

    # AC commands use the implement marker, with no per-call --marker override.
    # Environment/config still move the implement writer and its reader together.
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
    s.add_argument('--criteria-out', default=None, metavar='PATH',
                   help='Also write the reviewer-facing criteria as a JSON array of '
                        '{"criterion": N, "text": T} (N from 1) for `checklist finalize`. '
                        'The path must resolve beneath a .prflow/tmp/review/ tree and its '
                        'leaf must not be a symlink. Any earlier file there is removed '
                        'first; nothing is written when the criteria set is empty. A '
                        'refused path is left untouched; it or a failed write is named '
                        'on stderr and still exits 0. On every route that prints the '
                        'stdout blocks, issue-compliance.md beside it, cleared and confined '
                        'the same way, receives the Issue Compliance text Phase 4 reports, '
                        'or a compliance-out: stderr line says why not.')
    s.set_defaults(func=cmd_acs_resolve)

    s = sub.add_parser(
        'acs-remirror',
        help="Replace the workpad's ## Acceptance Criteria with a fresh mirror of the "
             "issue body's (the implement mirror, run after amending the issue), "
             'restoring criteria the run deferred or rewrote. Takes no criteria '
             'operand. Refuses with no write: exit 3 when section_parse.py is missing '
             'or the issue body is unreadable; exit 1 when the body has no checkbox '
             'criterion or parse-acs.py fails. update then applies its own refusals, '
             'including exit 1 for an absent, unreadable or section-less workpad and '
             'exit 4 for a Status other than Complete.',
    )
    s.add_argument('issue', type=int)
    s.set_defaults(func=cmd_acs_remirror)

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
        'reuse-check',
        help='Decide whether a recorded Plan (plan) or review (review) is reusable '
             'now (issue #616): the plan-inputs or reusable-review row must be the '
             'only one, well formed, and match the live issue body (and, for review, '
             'HEAD and its merge-base with the configured base branch, with every '
             'Review row before the AC gate ticked). '
             'Prints one "reuse-check:" line unless the GitHub repository or '
             'comment lookup fails. '
             'Exits 0 match / 1 nothing reusable (absent, duplicate, malformed, '
             'incomplete, mismatch) / 2 unestablished. Never prints the body.',
    )
    s.add_argument('issue', type=int)
    s.add_argument('kind', choices=('plan', 'review'))
    s.add_argument('--marker', default=None, help=_marker_help)
    s.set_defaults(func=cmd_reuse_check)

    s = sub.add_parser(
        'reset-resume-status',
        help='Reset a terminal workpad Status to an interim word at the earliest '
             'resume hook (issue #137), firing the status→label mirror so '
             'PRFlow:Stuck becomes PRFlow:Implementing before a live resume looks '
             'dead. Best-effort + idempotent (only a terminal Status is reset); '
             'always exits 0 and prints one outcome token (RESET/NOOP/NO_WORKPAD/'
             'UNAVAILABLE). The prior word is recorded for `prior-status` to read.',
    )
    s.add_argument('issue', type=int)
    s.add_argument('--marker', default=None, help=_marker_help)
    s.set_defaults(func=cmd_reset_resume_status)

    s = sub.add_parser(
        'prior-status',
        help="Print the prior terminal Status word recorded by `reset-resume-status` "
             '(issue #137). Exits 0 with the word / 1 when none is recorded or the '
             'marker set is duplicated-or-garbled (grep-style, so the caller falls '
             'back to the live Status) / 2 unestablished. Never prints the body.',
    )
    s.add_argument('issue', type=int)
    s.add_argument('--marker', default=None, help=_marker_help)
    s.set_defaults(func=cmd_prior_status)

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

    s = sub.add_parser('patch', help='PATCH a workpad comment from a body file.')
    s.add_argument('comment_id', type=int)
    s.add_argument('body_file')
    s.add_argument('--drop-leading-marker', action='append', default=[], metavar='KIND',
                   help='Do not re-insert a live leading marker of this kind '
                        '(e.g. review-verdict) the body file omits. Repeatable.')
    s.set_defaults(func=cmd_patch)

    s = sub.add_parser(
        'progress',
        help='Boundary-update a review progress comment by id: tick one '
             '## Blueprint row and/or append to ## Findings (live) in one PATCH. '
             'No issue lookup, no marker lookup.')
    s.add_argument('comment_id', type=int)
    s.add_argument('--tick', default=None,
                   help='Substring naming the unticked ## Blueprint row to tick.')
    g = s.add_mutually_exclusive_group()
    g.add_argument('--append', default=None,
                   help='Text to insert as the last line(s) of ## Findings (live).')
    g.add_argument('--append-file', default=None,
                   help='Path whose content is inserted the same way as --append.')
    s.set_defaults(func=cmd_progress)

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
    # Accepted but unrendered: the skeleton's H1 no longer names the issue (the
    # workpad is a comment ON that issue), and a vendored workflow still passes it.
    s.add_argument('issue', type=int)
    s.add_argument('--run-link', metavar='VALUE', default=None,
                   help='Run front-matter value (markdown ok). Defaults to a '
                        '"_(local run)_" placeholder when omitted.')
    s.add_argument('--branch', metavar='VALUE', default=None,
                   help='Branch name. Defaults to a "_(creating…)_" placeholder.')
    s.add_argument('--no-reproduction', action='store_true',
                   help='Omit the bug-only "Reproduction captured" sub-item. '
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
        epilog='Every mutation flag combines with every other in one call (one '
               'PATCH), so a caller batches an entire moment into a single '
               'invocation. The combination constraints are: '
               '--strip-inherited-checkpoints cannot be combined with a '
               '--checkpoint or --replace-checkpoint for a key it strips (a '
               'declared or attempt: key; strip and record in separate calls); '
               'one key cannot go to both --checkpoint and --replace-checkpoint; '
               '--branch and --branch-from-head are mutually '
               'exclusive (pass one); each --record-* flag requires its own '
               'companion flags (e.g. --record-completion-evidence-ci requires '
               '--completion-ci-check; --record-verification-evidence requires '
               'its evidence operands); a --rewrite-ac pair that appends '
               'the (post-merge) tag requires a non-empty --note rationale; and '
               '--rewrite-ac rows and any --scope-decision-rewritten records in '
               'the same call must pair one-to-one.',
    )
    u.add_argument('issue', type=int)
    u.add_argument('--status', help='Replace the Status line value. A canonical '
                   'glyph (🚀 running / 🎉 Complete / 👎 Blocked / 💥 Failed / '
                   '🛑 Cancelled) is derived from the status word and prepended '
                   'automatically.')
    u.add_argument('--branch', help='Replace the Branch line value.')
    u.add_argument('--branch-from-head', action='store_true',
                   help='Replace the Branch line with the current branch name, '
                        'resolved in-process via git branch --show-current so the '
                        'caller emits no command substitution. Mutually exclusive '
                        'with --branch; fails closed (non-zero, no write) on a '
                        'detached HEAD or a git failure.')
    u.add_argument('--run-link', metavar='VALUE',
                   help='Set the Run front-matter line to VALUE (markdown ok). '
                        'Inserted after Branch if the line is absent.')
    u.add_argument('--pr-link', metavar='VALUE',
                   help='Set the PR front-matter line to VALUE (markdown ok). '
                        'Inserted after Branch if the line is absent.')
    u.add_argument('--tick-progress', metavar='TEXT', action='append', default=[],
                   help='Tick one ## Progress checkbox matching TEXT (substring). '
                        'Repeatable. A unique already-ticked match is satisfied; '
                        'no match or an ambiguous one is a volatile failure: the '
                        'call PATCHes its other mutations and exits non-zero '
                        'naming the miss (no index form for Progress).')
    u.add_argument('--tick-plan', metavar='TEXT', action='append', default=[],
                   help='Tick one Plan checkbox matching TEXT (substring). '
                        'Repeatable. Matching as --tick-progress.')
    u.add_argument('--tick-plan-n', metavar='N', type=int, action='append',
                   default=[],
                   help='Tick the Nth Plan checkbox (1-based, counting every '
                        '[ ] and [x] row within the ## Plan section, in document '
                        'order; section-scoped, not whole-document). Repeatable; '
                        'combinable with --tick-plan and every other flag. An '
                        'already-ticked N is satisfied; an out-of-range N is a '
                        'volatile failure (reported, non-zero exit, other '
                        'mutations applied).')
    u.add_argument('--tick-ac', metavar='TEXT', action='append', default=[],
                   help='Tick one Acceptance Criteria checkbox matching TEXT '
                        '(substring). Repeatable. Matching as --tick-progress.')
    u.add_argument('--tick-ac-n', metavar='N', type=int, action='append',
                   default=[],
                   help='Tick the Nth Acceptance Criteria checkbox (1-based, '
                        'counting every [ ] and [x] row within the ## Acceptance '
                        'Criteria section, in document order; section-scoped, not '
                        'whole-document). '
                        'Repeatable; combinable with --tick-ac and every other '
                        'flag. An already-ticked N is satisfied; an out-of-range N '
                        'is a volatile failure (reported, non-zero exit, other '
                        'mutations applied).')
    u.add_argument('--rewrite-ac', nargs=2, metavar=('OLD', 'NEW'),
                   action='append', default=[],
                   help='Find the one AC row whose text contains OLD (any '
                        'distinguishing fragment); replace the whole row text with '
                        'NEW, so NEW is the complete new criterion. Preserves the '
                        'checkbox state. For Phase 2.2.6. With '
                        '--scope-decision-rewritten in the same call, rewritten '
                        'rows and records must pair one-to-one (each row\'s text '
                        'before and after the call, normalized, equal to its '
                        'record\'s OLD and NEW), or the call aborts with no PATCH. '
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
                        'Status\'s phase inside ## Progress. A note carrying line '
                        'breaks renders as one bullet with its continuation lines '
                        'indented under it and its blank lines dropped. May be '
                        'passed multiple times to append several entries (sharing '
                        'one timestamp) in one atomic update.')
    u.add_argument('--note-file', metavar='PATH', action='append', default=[],
                   help='Append a ## Progress note bullet whose text is read '
                        'verbatim as UTF-8 from PATH (or from stdin when PATH is '
                        '"-"), bypassing shell interpolation — use for text '
                        'containing backticks, $, or double quotes. Compose the '
                        'payload file with an editor/Write tool, never a shell '
                        'heredoc or redirect, or the interpolation hazard just '
                        'moves upstream. May be passed more than once to append '
                        'one bullet per payload, in order, each measured on its '
                        'own against the per-note byte budget. A payload carrying '
                        'line breaks renders as one bullet with its continuation '
                        'lines indented under it and its blank lines dropped; the '
                        'stdin form "-" '
                        'may be used at most once per flag. Combines with --note; '
                        'the file bullets append after any inline --note bullets. '
                        'An unreadable path, an undecodable (non-UTF-8) payload, or '
                        'an empty/whitespace-only payload aborts the call before '
                        'any PATCH.')
    u.add_argument('--reflection', metavar='TEXT', action='append', default=[],
                   help='Append a bullet to PRFlow Reflections (no timestamp). '
                        'May be passed multiple times to append several bullets '
                        'in one atomic update.')
    u.add_argument('--reflection-file', metavar='PATH', action='append', default=[],
                   help='Append a PRFlow Reflections bullet whose text is read '
                        'verbatim as UTF-8 from PATH (or from stdin when PATH is '
                        '"-"), bypassing shell interpolation — use for text '
                        'containing backticks, $, or double quotes. May be passed '
                        'more than once to append one bullet per payload, in '
                        'order; the stdin form "-" may be used at most once per '
                        'flag. The call\'s --reflection-kind applies to every file '
                        'bullet; the file bullets append after any --reflection '
                        'bullets. An unreadable path, an undecodable (non-UTF-8) '
                        'payload, or an empty/whitespace-only payload aborts the '
                        'call before any PATCH.')
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
    u.add_argument('--resolve-doc-reflection', nargs=2, action='append', default=None,
                   metavar=('TARGET', 'EVIDENCE'),
                   help='Resolve a fulfilled documentation obligation (issue #508): '
                        'move the single actionable PRFlow Reflections bullet '
                        'containing TARGET out of "### ⚠️ Action required" into '
                        '"### ℹ️ Notes", keeping its original glyph/kind and appending '
                        'EVIDENCE (the checked completion evidence). The moved bullet '
                        'keeps its non-note glyph, so it still counts as retrospective '
                        'friction. Idempotent: replaying the same TARGET/EVIDENCE is a '
                        'no-op. An absent or ambiguous TARGET, a non-actionable match, '
                        'an empty/multiline operand, or an already-resolved bullet with '
                        'different evidence aborts the call before any PATCH, changing '
                        'no other reflection. May be passed more than once.')
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
    u.add_argument('--replace-checkpoint', nargs=2, metavar=('KEY', 'TEXT'),
                   action='append', default=[],
                   help='Like --checkpoint, but an existing row for KEY is replaced '
                        'by a fresh row carrying TEXT (issue #1947); a row with the '
                        'current marker and the same text is a replay. A key may not also be passed to '
                        '--checkpoint. May be passed multiple times.')
    u.add_argument('--strip-inherited-checkpoints', action='store_true',
                   help='Remove every declared required-artifact checkpoint row '
                        'from ## Progress (issue #1347), so a resumed run does not '
                        'inherit the previous attempt\'s record. Declared keys: '
                        + ', '.join(_REQUIRED_ARTIFACT_CHECKPOINT_KEYS)
                        + '. Also removes every row carrying an "attempt:"-prefixed '
                          'key (issue #1947). Combining it with --checkpoint or '
                          '--replace-checkpoint for one of those same keys is '
                          'rejected before any PATCH.')
    u.add_argument('--record-sweep-evidence', default=None, metavar='FILE',
                   help='Record one Phase 2 sweep-evidence JSON record (issue #438): '
                        'the selected sweep set, each sweep\'s terminal outcome '
                        '(completed/degraded/unrunnable), and the distinct catches each '
                        'sweep owned. FILE is validated by sweep-evidence.py before any '
                        'PATCH; on a pass a hidden "<!-- prflow:checkpoint '
                        'sweep-evidence:<run_identity>:<payload> -->" ## Progress row is '
                        'written, replacing only THIS run identity\'s prior row (other '
                        'runs\' records coexist for the summarizer). A non-ok record, or '
                        'one whose encoded payload exceeds 2048 bytes, aborts the whole '
                        'call before any PATCH.')
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
                        'Complete" write — the completion-evidence families are counted '
                        'together and exactly one is required.')
    u.add_argument('--completion-ci-check', nargs=2, action='append', default=None,
                   metavar=('NAME', 'CONCLUSION'),
                   help='A required-check reading for --record-completion-evidence-ci '
                        '(issue #1898). Repeatable: pass one NAME CONCLUSION pair per '
                        'required check read (e.g. "lib + python tests" success). The '
                        'recorded set must cover the required-check set declared in '
                        '.github/workflows/ci.yml, and every CONCLUSION must be a '
                        'success, or the --status Complete write is refused.')
    u.add_argument('--record-completion-evidence-cloud-ci', default=None, metavar='FILE',
                   help='Record cloud-CI completion evidence (issue #403) read from '
                        'FILE, a JSON `cloud_ci_evidence` record (kind + schema_version '
                        '+ per-shard tallies + required checks + head_sha/run identity). '
                        'The record is validated offline against this tree and the '
                        'declared .github/workflows/ci.yml contract before any PATCH; a '
                        'non-pass record is refused with no write. Recorded in its own '
                        'completion family (the run is never labelled local) and '
                        'replaces any prior evidence of any family.')
    u.add_argument('--invalidate-completion-evidence', action='store_true',
                   help='Strip every recorded completion-evidence marker (all families) '
                        'from ## Progress without recording a new one (issue #403). Use '
                        'after a final edit, a base update that changes the candidate, or '
                        'a repair, so stale evidence cannot survive to Complete.')
    u.add_argument('--record-verification-evidence', action='store_true',
                   help='Record one `Verification evidence:` note-kind reflection row '
                        'for a whole-suite launch (issue #2131) — this option OWNS the '
                        "record's field set. Required: --command, --outcome, and "
                        '--run-root (repeatable for the two-root recombination case; the '
                        'literal `none` is the accepted value for a tier-denied or '
                        'ceiling-terminated launch, recorded verbatim as run-root=none). '
                        'Optional: --tallies, --elapsed, --started-at (a denied or '
                        'terminated launch has none). The tool stamps recorded-at (UTC) '
                        'and head (the full 40-char `git rev-parse HEAD`, `unestablished` '
                        'when git cannot answer). Refused before any PATCH: a call '
                        'missing a required field, or one whose --outcome names an '
                        'aggregate result (aggregate CLEAN / aggregate FAILED) while '
                        '--run-root is `none`. The row is appended (never replacing a '
                        'prior one), so two launches leave two rows.')
    u.add_argument('--command', default=None, metavar='C',
                   help='The suite command invoked, for --record-verification-evidence.')
    u.add_argument('--outcome', default=None, metavar='O',
                   help='The outcome as the coordinator reported it (its aggregate '
                        'line), for --record-verification-evidence.')
    u.add_argument('--run-root', action='append', default=None, metavar='R',
                   help='The retained-log root, for --record-verification-evidence. '
                        'Repeatable (the same-tree recombination names both roots); the '
                        'literal `none` records a denied/terminated launch verbatim.')
    u.add_argument('--tallies', default=None, metavar='T',
                   help='The pass/fail/skip tallies, for --record-verification-evidence '
                        '(optional).')
    u.add_argument('--elapsed', default=None, metavar='E',
                   help='The elapsed wall-clock time, for '
                        '--record-verification-evidence (optional).')
    u.add_argument('--started-at', default=None, metavar='S',
                   help="The launch's own start time, for "
                        '--record-verification-evidence (optional).')
    u.add_argument('--record-resume-point', default=None, metavar='TEXT',
                   help='Record this run\'s mid-phase re-anchor resume point (issue '
                        '#1876) as a hidden "<!-- prflow:checkpoint '
                        'resume-point:<payload> -->" ## Progress row, replacing any '
                        'prior one. TEXT is the step to resume at after a nested-skill '
                        'return (e.g. a phase-file and step). It is a NAVIGATION aid, '
                        'never evidence: no verdict, completion-evidence, or '
                        'review-coverage reader consumes it — read it back with the '
                        '"resume-point" subcommand. Needs no other mutation to PATCH.')
    u.add_argument('--strip-prior-status-marker', action='store_true',
                   help='Consume the resume prior-status marker (issue #137) by '
                        'removing its "<!-- prflow:checkpoint prior-status:<word> -->" '
                        '## Progress row, after Phase 1.3 has read it with the '
                        '"prior-status" subcommand to classify the resume. No marker '
                        'present is a no-op.')
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
                        + ' (`all` is accepted as an alias for `complete`). CHECKLIST: '
                        + '|'.join(_REVIEW_COVERAGE_VOCABULARY['checklist'])
                        + ' (`all` is accepted as an alias for `complete`). An '
                          'unresolvable axis is recorded "unestablished", never '
                          'a clean value. A later "--status Complete" write is refused '
                          'unless this record is complete or every gap it reports '
                          'carries a --review-coverage-disposition.')
    u.add_argument('--record-roster-member', nargs=2, action='append', default=None,
                   metavar=('MEMBER', 'STATUS'),
                   help='Enumerate one shadow-review roster member and its dispatch '
                        'outcome (issue #1512). All members recorded in one call are '
                        'written as a single combined "<!-- prflow:checkpoint '
                        'review-roster:<encoded-roster> -->" ## Progress row beside the '
                        '--record-review-coverage record. MEMBER is the bare name or its '
                        '`prflow:`-prefixed spelling (issue #345: the shadow record spells '
                        'reviewers prflow:<name>; one leading prflow: is stripped to the '
                        'stored bare name), one of: '
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
    u.add_argument('--record-reusable-review', default=None, metavar='VERDICT',
                   choices=_REUSABLE_REVIEW_VERDICTS,
                   help='Beside a clean full-coverage --record-review-coverage record '
                        '(with --record-review-coverage-head and its roster rows), also '
                        'record a "reusable-review" row binding the reviewed head, its '
                        'merge-base with the configured base branch, a digest of the '
                        'live issue body, VERDICT, the checklist state and the roster '
                        '(issue #616). It survives --strip-inherited-checkpoints; any '
                        'later coverage record removes it. An input that does not '
                        'resolve skips the row with a note. VERDICT: '
                        + '|'.join(_REUSABLE_REVIEW_VERDICTS) + '.')
    u.add_argument('--adopt-reusable-review', action='store_true',
                   help='Re-stamp the review-coverage record, head anchor and roster '
                        'rows from the reusable-review row when HEAD, its merge-base '
                        'and the live issue body still match it (issue #616); refused '
                        'with no PATCH otherwise. Not combinable with the coverage, '
                        'roster or reusable-review record flags.')
    u.add_argument('--record-plan-inputs', action='store_true',
                   help='Record a "plan-inputs" row carrying a digest of the live issue '
                        'body the Plan was written from, replacing any prior one '
                        '(issue #616). It survives --strip-inherited-checkpoints. An '
                        'unreadable issue body removes the old row and writes a note '
                        'instead.')
    u.add_argument('--record-review-coverage-head', default=None, metavar='SHA',
                   help='The reviewed head SHA the review-coverage record is derived '
                        'from (issue #1510), stamped as the record\'s as-of anchor '
                        'beside the UTC write time so a reader can tell a record that '
                        'predates a later standalone review from a current one. A '
                        'lowercase-hex SHA; omit it to record the head as '
                        '"unestablished". Only meaningful with --record-review-coverage.')
    u.add_argument('--review-waived-by', default=None, metavar='SOURCE',
                   help='Only with --status Complete: an explicit human instruction '
                        'waived review (issue #2026). Skips the review-coverage gate '
                        'alone and appends a note disclosing the waiver, SOURCE (the '
                        'instruction\'s URL or locator) and that review is unverified, '
                        'once per distinct SOURCE. Writes no review record. Every other '
                        'Complete gate still applies.')
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
                          'whose result was lost, or a shadow run inline after a refused, '
                          'dead or malformed engine dispatch). A budget belief or a partial pass '
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
                        'gate compares the flight record against (issue #1087); '
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
    return p


if __name__ == '__main__':
    main()
