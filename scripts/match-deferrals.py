#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""PRFlow deferred-findings matcher for /devflow:review's Phase 4.0.

Reads the Scope-Acknowledged Findings block from a PR body (between the
DEVFLOW_DEFERRED_FINDINGS_START/END markers), validates each deferral
against four guards (guard 4 replaces guard 2 for a `settled-by-disclosure`
foreclosure entry, so any one deferral is validated against three), and matches
the survivors against the current run's Phase 3 findings. Emits a JSON report of
the matched and rejected deferrals.

Guards (any failing guard rejects the deferral):
    1. Trusted filer:     the PR author passes one arm (see _filer_trust):
                          a non-wildcard `prflow.allowed_bots` entry; a bot on a
                          same-repository head when `allowed_bots` holds `*`;
                          or a human passing the trigger gate's user rule
                          (`prflow.allowed_users` plus write, maintain or admin
                          permission, through scripts/authorize-actor.sh).
    2. Mutual cross-link: follow-up issue exists, is open, and its body
                          contains the substring "PR #<N>" (where N is the
                          current PR number). Applies to ordinary deferrals
                          only; for a `settled-by-disclosure` foreclosure
                          entry this guard is replaced by guard 4 below.
    3. Widens surface:    PR's current diff does not overlap the deferral's
                          file within ±10 lines of its line_range.
    4. Disclosure verify (foreclosure entries only, `reason.category ==
                          "settled-by-disclosure"`): the PR's cached diff was
                          read and parsed to at least one hunk; the entry's
                          `disclosure.path` is a repo-relative path resolving
                          to a file under the checked-out tree's repo root;
                          `disclosure.phrase` is found in that file under
                          whitespace-normalized comparison; and `disclosure.path`
                          is not the file of any hunk in the PR's own diff (a
                          PR-authored disclosure never self-forecloses). Fails
                          closed with reason `disclosure-unverified` and a
                          `detail` naming the failed arm — this REPLACES guard 2
                          for foreclosure entries; guards 1 and 3 still apply.

An entry that is not a mapping, or whose `reason`, `reason.category`, `finding`,
`finding.file`, `finding.line_range` or `follow_up` holds a present value of the
wrong type, or whose `finding.line_range` starts after it ends, fails before guards
2-4 with reason `malformed-entry` and a `detail` naming the field; its siblings are
still matched. Other fields are left to the guards. A findings element that is not
an object, or whose non-null `line_range` is not two ints with start <= end, matches
no deferral; once any deferral survives the guards, it gets one stderr line naming
its index.

Matching rule (v1, conservative): a current finding matches a surviving
deferral iff same file AND same kind AND line_range overlaps within ±25
lines. Summary similarity is not used — file+kind+line_range is strong
enough to prevent false positives, and a more permissive rule would risk
matching genuinely new findings that share vague terminology.

Usage:
    match-deferrals.py --pr N --diff PATH --findings (PATH | -) [--config PATH]
                       [--threshold SEVERITY]

Pass `--findings -` to read the findings JSON from stdin.

Output (JSON to stdout, always exit 0 when the helper itself ran):
    {
      "block_present": true | false,
      "pr_author_trusted": true | false | null,
      "trust_failure": null | "permission-lookup-failed" | "allowed-bots-unreadable" |
                       "allowed-users-unreadable" | "pr-fields-malformed",
      "honored": [
        {"finding_index": 0, "deferral_id": "dfr-...",
         "follow_up_issue": 47, "category": "out-of-scope"}
      ],
      "rejected_deferrals": [
        {"deferral_id": "dfr-...", "reason": "<one of: ...>"}
      ],
      "stats": {
        "total_deferrals": 3, "valid_after_guards": 2,
        "honored": 2, "unmatched": 0
      }
    }

`trust_failure` is non-null only when no arm trusted the author and at least one arm
could not be decided; `pr_author_trusted` is then false.

`--threshold` (the verdict severity threshold) adds `deferrals_section`: the report's
`## Deferrals` markdown, or "" when `block_present` is false. Each matched finding's filed
`severity` is placed against the threshold (an unrecognized severity reads as critical); the
verdict's own cap and demotions are the report's, not this section's. The ladder is the sibling
verdict_report.py's `SEVERITIES`, imported only under this flag: when that import fails the
helper names the fault on stderr and exits 2, before it reads the PR.

Exit codes:
    0  Helper ran successfully (regardless of match results).
    2  Bad arguments / unrecoverable input error.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path, PurePosixPath

if sys.version_info < (3, 11):  # fail fast, before any PEP 604 annotation is evaluated below
    sys.stderr.write(
        "prflow: Python 3.11+ required (found {}.{}.{}). This helper requires"
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
    # Nested-repository detection (issue #12): a resolved root with no .prflow/ under
    # an ancestor that has one reads built-in defaults while looking configured.
    from ancestor_config import warn_ancestor_config as _warn_ancestor_config
    from state_dir import resolve_state_dir as _resolve_state_dir
except Exception:  # pragma: no cover - partial-copy / exec'd-source arm
    def _resolve_state_dir(repo_root, stream=None):
        return str(Path(repo_root) / ".prflow")

    def _warn_ancestor_config(repo_root, reader, remedy="", stream=None):
        return None

# Refreshed-token env for gh calls on native Windows (see gh_fresh_env.py).
# Guarded like the lib/ imports around it (partial copy / exec'd source): a copy
# without the sibling inherits the ambient token, as before the helper.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from gh_fresh_env import fresh_gh_env
except Exception:  # pragma: no cover - partial-copy / exec'd-source arm
    def fresh_gh_env(env=None, os_name=None):
        return env

# Shared login-normalization rule (issue #157): trust an allowed_bots entry against
# the gh-reported `app/<slug>` author under one normalized comparison. Imported
# through the same guarded lib/ path insert; on an import failure (partial copy /
# exec'd source) it degrades to the pre-#157 exact set-membership test below.
try:
    from login_normalize import login_matches as _login_matches
except Exception as _login_import_err:
    # Breadcrumb the degradation so a partial-copy import failure is legible and not
    # mistaken for an allowlist mismatch — the shell comparators name the same file.
    sys.stderr.write(
        "match-deferrals.py: could not import lib/login_normalize.py "
        f"({_login_import_err}); degrading to the pre-#157 exact match (fail-closed)\n")
    _login_matches = None

# Spells authorize-actor.sh's path for the selected bash (issue #430). Without it the
# authorized-human trust arm cannot run and fails closed with a breadcrumb.
_BL_IMPORT_ERROR = None
try:
    import bash_launch as _bl
    if not callable(getattr(_bl, "command", None)):
        raise ImportError("it has no command()")
except Exception as _bl_err:
    _bl, _BL_IMPORT_ERROR = None, str(_bl_err)

# The gh binary to shell out to. `DEVFLOW_GH` (the documented override the shell
# helpers resolve via lib/resolve-gh.sh) wins when set and non-empty; else `gh`.
GH = os.environ.get("DEVFLOW_GH") or "gh"

LINE_DRIFT_TOLERANCE = 25
WIDENS_SURFACE_TOLERANCE = 10
BLOCK_START = "<!-- DEVFLOW_DEFERRED_FINDINGS_START -->"
BLOCK_END = "<!-- DEVFLOW_DEFERRED_FINDINGS_END -->"
PAYLOAD_START = "<!-- DEVFLOW_DEFERRED_PAYLOAD"
# The default config path is resolved lazily at call time by _default_config_path()
# (anchored to the git repo root; issue #295) — NOT a cwd-relative module constant —
# so a subdirectory invocation reads the consumer's ROOT config. A NON-EMPTY explicit
# --config argument is honored verbatim; an explicit empty --config is passed down to
# config-get.sh, whose own [ -n "${3:-}" ] gate then re-selects the root-anchored
# default (so the empty-string edge matches config-get.sh's behavior, but via its
# fallback rather than a passthrough here).

# Rejection reason codes. `_deferrals_section` renders each as data.
REASON_UNTRUSTED_FILER = "untrusted-filer"
REASON_MISSING_FOLLOW_UP_ISSUE = "missing-follow-up-issue"
REASON_ISSUE_UNREADABLE = "issue-unreadable"
REASON_ISSUE_CLOSED = "issue-closed"
REASON_UNLINKED_FOLLOWUP = "unlinked-followup"
REASON_WIDENS_SURFACE = "widens-surface"
REASON_UNMATCHED = "unmatched"
# issue #621: foreclosure entries (reason.category == "settled-by-disclosure")
# are honored through a disclosure-verification guard that REPLACES the mutual
# cross-link guard for this category only. It fails closed with this reason code
# plus a `detail` naming the failed arm.
REASON_DISCLOSURE_UNVERIFIED = "disclosure-unverified"
# issue #974: an entry with a wrong-typed field; `detail` names the field.
REASON_MALFORMED_ENTRY = "malformed-entry"

# `trust_failure` values (issue #1078): the filer-trust check could not complete.
# `_deferrals_section` renders them as data.
TRUST_FAILURE_PERMISSION_LOOKUP = "permission-lookup-failed"
TRUST_FAILURE_ALLOWED_BOTS = "allowed-bots-unreadable"
TRUST_FAILURE_ALLOWED_USERS = "allowed-users-unreadable"
TRUST_FAILURE_PR_FIELDS = "pr-fields-malformed"
# The stdout verdicts scripts/authorize-actor.sh prints when executed.
_AUTHORIZE_VERDICTS = {"authorized", "denied", "lookup-failed"}

# The per-entry reason.category value that marks a settled-by-disclosure
# foreclosure (issue #621). A foreclosure has no follow-up issue — the
# already-shipped disclosure IS the deliverable — so it cannot ride the
# mutual-cross-link guard; guard 4 (_verify_disclosure) governs it instead.
FORECLOSURE_CATEGORY = "settled-by-disclosure"


def _normalize_ws(text: str) -> str:
    # Whitespace-normalized comparison: collapse every run of whitespace
    # (including newlines) to a single space and strip the ends, so a
    # disclosure phrase matches its file even across line wraps / reflowed
    # indentation. Pure-Python (str.split) — no non-preflight PATH tool decides
    # this selection (CLAUDE.md guard-class 2).
    return " ".join(text.split())


def _verify_disclosure(deferral: dict, hunks: dict, diff_hunk_count: int,
                       repo_root: str | None) -> str | None:
    """Guard 4 (issue #621) — foreclosure disclosure verification.

    Returns None when the disclosure verifies, else a short `detail` string
    naming the failed arm (paired with REASON_DISCLOSURE_UNVERIFIED by the
    caller). Fails CLOSED on every degraded operand: a foreclosure whose
    disclosure cannot be verified against the checked-out tree is rejected.

    A foreclosure is honored only when ALL hold:
      * the PR's cached diff was read and parsed to >= 1 hunk (an absent /
        unreadable / zero-hunk diff fails closed — the not-in-diff test below
        would otherwise be vacuously true over an empty hunk dict);
      * `disclosure.path` is a non-empty repo-relative path (not absolute, no
        `..`) resolving to a file UNDER the checked-out tree's repo root;
      * `disclosure.path` is NOT the file of any hunk in the PR's own diff (a
        PR-authored disclosure never self-forecloses — "already shipped" means
        it predates the PR);
      * the file is readable and contains `disclosure.phrase` under
        whitespace-normalized comparison.
    """
    disc = deferral.get("disclosure")
    if not isinstance(disc, dict):
        return "absent-disclosure-object"
    path = disc.get("path")
    phrase = disc.get("phrase")
    if not isinstance(path, str) or not path.strip():
        return "absent-path"
    if not isinstance(phrase, str) or not phrase.strip():
        return "absent-phrase"
    # Diff must have been read and parsed to at least one hunk — fail closed
    # otherwise, so the not-in-diff check below is never vacuously satisfied.
    if diff_hunk_count < 1:
        return "diff-unavailable"
    if os.path.isabs(path):
        return "absolute-path"
    if ".." in Path(path).parts:
        return "parent-traversal"
    if repo_root is None:
        return "repo-root-unresolved"
    root = Path(repo_root).resolve()
    try:
        target = (root / path).resolve()
    except (OSError, ValueError):  # e.g. a NUL byte in the path
        return "path-unresolvable"
    try:
        target.relative_to(root)
    except ValueError:
        return "path-outside-repo"
    # A disclosure the PR itself authors cannot foreclose that PR's findings —
    # reject when disclosure.path is a file the diff touched (>= 1 hunk).
    diff_files = {f for f, hs in hunks.items() if hs}
    if _norm_path(path) in diff_files:
        return "disclosure-in-diff"
    try:
        is_file = target.is_file()
    except (OSError, ValueError):  # e.g. ENAMETOOLONG, which Python 3.11's is_file raises
        return "path-unresolvable"
    if not is_file:
        return "file-absent"
    try:
        file_text = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "file-unreadable"
    if _normalize_ws(phrase) not in _normalize_ws(file_text):
        return "phrase-not-found"
    return None


def _fail(msg, code=2):
    sys.stderr.write(f"match-deferrals.py: {msg}\n")
    sys.exit(code)


def _run(cmd, *, check=True, bash_line=False):
    # `encoding="utf-8"` pins the gh-output decode: this wrapper reads PR and
    # issue *bodies* (`gh pr view --json body`, `gh issue view --json body`),
    # which are routinely non-ASCII, so decoding through the locale codec would
    # raise UnicodeDecodeError under a non-UTF-8 ambient codec (Windows' cp1252).
    # Implies text mode, so `text=True` is dropped (passing both is redundant).
    # An OSError (ENOEXEC from a non-executable `gh` shim — the host class DEVFLOW_GH
    # exists for — or gh or bash absent) is converted into the same structured
    # surface as a non-zero exit, so callers get a breadcrumb, not a traceback.
    program = cmd[0]
    if bash_line:
        cmd = _bl.command(cmd)
    try:
        return subprocess.run(
            cmd, check=check,
            capture_output=True, encoding="utf-8", env=fresh_gh_env(),
        )
    except OSError as e:
        if check:
            _fail(f"could not execute {program!r}: {e} "
                  f"(set DEVFLOW_GH to a working GitHub CLI)")
        return subprocess.CompletedProcess(cmd, 127, stdout="", stderr=str(e))


def _repo_root():
    # Resolve the git repo root (issue #295), the Python mirror of
    # lib/config-source.sh's `git rev-parse --show-toplevel 2>/dev/null || pwd`.
    # A native `git` subprocess is Windows-safe (like the existing `gh` calls),
    # unlike exec-ing a .sh ([WinError 193], issue #275). Returns the root string,
    # or None when not in a git tree / git cannot run (_run's rc-127 OSError
    # sentinel) — the caller then falls back to cwd.
    r = _run(["git", "rev-parse", "--show-toplevel"], check=False)
    root = r.stdout.strip() if r.returncode == 0 else ""
    return root or None


def _git_root_error_suffix() -> str:
    # Best-effort: capture git's own stderr for the no-root breadcrumb so the real
    # cause (safe.directory refusal, git absent — rc-127 OSError sentinel) surfaces
    # instead of being discarded. Returns a " (git: …)" suffix, or "" when git said
    # nothing / succeeded. _run never raises (OSError → rc 127 with stderr=str(e)).
    r = _run(["git", "rev-parse", "--show-toplevel"], check=False)
    err = (r.stderr or "").strip() if r.returncode != 0 else ""
    return f" (git: {err})" if err else ""


def _default_config_path() -> str:
    # Anchor the default config path to the repo root so a subdirectory invocation
    # reads the consumer's ROOT .prflow/config.json. Its explicit config-path
    # argument passing to config-get.sh would otherwise defeat config-get.sh's own
    # root anchoring — so this reader must root-anchor its default itself (issue #295).
    root = _repo_root()
    if root is not None:
        _warn_ancestor_config(root, "match-deferrals.py", "pass --config <path>")
        return str(Path(_resolve_state_dir(root)) / "config.json")
    cwd = Path.cwd()
    # Breadcrumb only when NEITHER a git root NOR a .prflow/ dir can be located —
    # the silent-drop class this fix closes.
    # git can exit non-zero while genuinely INSIDE a repo (safe.directory /
    # dubious-ownership), or be absent — not only "outside a git tree" — so don't
    # assert "not in a git repo"; report the root could not be resolved and surface
    # git's own stderr instead of discarding it.
    if not (cwd / ".prflow").is_dir() and not (cwd / ".devflow").is_dir():
        sys.stderr.write(
            f"match-deferrals.py: could not resolve a git repo root"
            f"{_git_root_error_suffix()} and no .prflow/ at {str(cwd)!r}; "
            f"falling back to a cwd-anchored default config path\n"
        )
    return str(Path(_resolve_state_dir(str(cwd))) / "config.json")


def _config_read(key: str, default: str, config_path: str | None = None) -> str | None:
    """The value at `key` through config-get.sh; None (with a breadcrumb) when it fails.

    An absent key is a clean read of `default`.
    """
    if config_path is None:
        config_path = _default_config_path()
    helper = Path(__file__).resolve().parent / "config-get.sh"
    # Through bash, never the .sh path itself: Windows cannot exec a .sh ([WinError 193]);
    # `command` keeps Git Bash from glob-expanding a `*` default (issue #1353).
    bash = os.environ.get("DEVFLOW_BASH") or "bash"
    if _bl is None:
        r = subprocess.CompletedProcess(
            [], 127, stdout="", stderr=f"lib/bash_launch.py could not be imported ({_BL_IMPORT_ERROR})")
    else:
        try:
            argument = _bl.script_argument(helper, cwd=Path.cwd(), bash=bash)
        except (ValueError, OSError) as e:  # OSError: cwd deleted or unreadable
            r = subprocess.CompletedProcess([], 127, stdout="", stderr=str(e))
        else:
            if _bl.is_wsl_interpreter(bash):  # WSL cannot open a drive-letter path
                config_path = _bl.convert_absolute(config_path, bash)
            r = _run([bash, argument, key, default, config_path], check=False, bash_line=True)
    if r.returncode != 0:
        cause = ((r.stderr or "").strip().splitlines() or ["no stderr"])[0]
        sys.stderr.write(
            f"match-deferrals.py: could not read {key.lstrip('.')!r} through "
            f"config-get.sh under {bash!r} (rc {r.returncode}: {cause})\n")
        return None
    return r.stdout.strip()


def _extract_block(pr_body: str) -> str | None:
    """The text between the START marker and the first END marker after it, else None."""
    if BLOCK_START not in pr_body:
        return None
    start = pr_body.index(BLOCK_START) + len(BLOCK_START)
    end = pr_body.find(BLOCK_END, start)
    return None if end == -1 else pr_body[start:end]


def _ignored(cause: str) -> str:
    """Breadcrumb why a present block is ignored; returns `cause` for `## Deferrals`."""
    sys.stderr.write(f"match-deferrals.py: {cause}; ignoring the block\n")
    return cause


def _parse_yaml_payload(block: str) -> tuple[dict, str | None]:
    """Parse the YAML payload from the hidden DEVFLOW_DEFERRED_PAYLOAD comment.

    The PR-description renderer shows a human-readable Markdown table inside the
    START/END markers and stores the exact machine payload in a hidden HTML
    comment so it stays invisible in the rendered PR body. The schema is
    unchanged (schema_version + deferrals[]); only the payload's location moved
    out of a visible ```yaml fence into this comment.

    Returns (payload, None), or ({}, why) when the block holds no readable mapping —
    a missing, unterminated, unparseable or empty comment, or a non-mapping payload.
    """
    try:
        import yaml
    except ImportError:
        _fail("PyYAML required to parse deferred-findings block")

    payload_match = re.search(
        re.escape(PAYLOAD_START) + r"\s*\n(.*?)\n-->", block, re.DOTALL
    )
    if not payload_match:
        return {}, _ignored("no parseable DEVFLOW_DEFERRED_PAYLOAD comment")
    try:
        loaded = yaml.safe_load(payload_match.group(1))
    except yaml.YAMLError as e:
        sys.stderr.write(f"match-deferrals.py: YAML parse failed: {e}\n")
        return {}, "payload YAML does not parse"
    if loaded is None:
        return {}, _ignored("DEVFLOW_DEFERRED_PAYLOAD comment is empty")
    if not isinstance(loaded, dict):
        return {}, _ignored("payload is not a mapping")
    return loaded, None


def _get_pr_view(pr_number: int) -> dict:
    """Return gh's `pr view` object; its fields are validated where they are read."""
    r = _run(
        [GH, "pr", "view", str(pr_number),
         "--json", "body,author,isCrossRepository,url"],
        check=False,
    )
    if r.returncode != 0:
        _fail(f"could not read PR #{pr_number}: {r.stderr.strip()}")
    try:
        view = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        _fail(f"could not parse PR #{pr_number}: {e}")
    if not isinstance(view, dict):
        _fail(f"PR #{pr_number} read as {_shape(view)}, not an object")
    return view


_MISSING = object()


def _shape(value) -> str:
    """Name a JSON value's shape for a breadcrumb."""
    if value is _MISSING:
        return "missing"
    if value is None:
        return "null"
    for kind, name in ((bool, "a boolean"), (int, "an integer"), (float, "a number"),
                       (str, "a string"), (list, "an array"), (dict, "an object")):
        if isinstance(value, kind):
            return name
    return f"a {type(value).__name__}"


def _malformed(field: str, value, want: str) -> None:
    sys.stderr.write(
        f"match-deferrals.py: gh's PR view field {field} is {_shape(value)}, not {want}; "
        "the PR author is untrusted as a deferral filer\n")


def _repo_slug(url) -> str | None:
    """`owner/repo` from a pull-request URL (`https://<host>/<owner>/<repo>/pull/<n>`)."""
    if not isinstance(url, str):
        return None
    parts = [p for p in urllib.parse.urlsplit(url).path.split("/") if p]
    if len(parts) < 4 or parts[-2] != "pull":
        return None
    return f"{parts[-4]}/{parts[-3]}"


def _listed_bot(login: str, entries: list[str]) -> bool:
    """Arm 1: the login matches a non-wildcard allowed_bots entry."""
    if _login_matches is not None:
        return _login_matches(login, entries)
    # Import fallback: exact membership, the pre-#157 rule (fail-closed).
    return login in {e.strip() for e in entries if e.strip()}


def _authorized_human(login: str, repo: str | None, config_path: str | None) -> tuple[bool, str | None]:
    """Arm 3: the trigger gate's user rule, run through authorize_actor.

    Returns (trusted, trust_failure). A policy denial is (False, None).
    """
    # A failed read must never reach authorize_actor, which reads an empty
    # ALLOWED_USERS as '*'. An absent, empty or null value reads as the '*' default.
    users = _config_read(".prflow.allowed_users", "*", config_path)
    if users is None:
        sys.stderr.write("match-deferrals.py: prflow.allowed_users could not be read; "
                         "the author is untrusted\n")
        return False, TRUST_FAILURE_ALLOWED_USERS
    if not users:  # Whitespace only, stripped: the trigger gate matches no one.
        sys.stderr.write("match-deferrals.py: prflow.allowed_users is whitespace only and "
                         "matches no one; the author is untrusted\n")
        return False, None
    if repo is None:
        return False, TRUST_FAILURE_PR_FIELDS
    script = Path(__file__).resolve().parent / "authorize-actor.sh"
    # `bash` stays a literal here, not a shared resolver call: cloud_writer_deps.py
    # verifies this file's declared exec edge from a statically resolvable binding.
    bash = os.environ.get("DEVFLOW_BASH") or "bash"
    env = dict(os.environ, ACTOR=login, ALLOWED_BOTS="", ALLOWED_USERS=users, REPO=repo)
    verdict, cause = "", f"lib/bash_launch.py could not be imported ({_BL_IMPORT_ERROR})"
    if _bl is not None:
        try:
            r = subprocess.run(
                [bash, _bl.script_argument(script, cwd=Path.cwd(), bash=bash)],
                capture_output=True, encoding="utf-8", env=fresh_gh_env(env), check=False,
            )
            verdict = r.stdout.strip() if r.returncode == 0 else ""
            last = ((r.stderr or "").strip().splitlines() or ["no stderr"])[-1]
            cause = last if r.returncode == 0 else f"rc {r.returncode}: {last}"
        except (OSError, ValueError) as e:
            cause = f"could not launch {bash!r}: {e}"
    if verdict == "authorized":
        return True, None
    if verdict == "denied":
        sys.stderr.write(f"match-deferrals.py: authorize-actor.sh denied {login!r} ({cause})\n")
        return False, None
    if verdict not in _AUTHORIZE_VERDICTS:
        cause = f"authorize-actor.sh reported no verdict ({cause})"
    sys.stderr.write(
        f"match-deferrals.py: collaborator-permission lookup for {login!r} failed "
        f"({cause}); the author is untrusted\n")
    return False, TRUST_FAILURE_PERMISSION_LOOKUP


def author_trust(login: str, is_bot: bool | None, repo: str | None, config_path: str | None,
                 same_repo_head: bool | None = False) -> tuple[bool, str | None]:
    """Is `login` a trusted author? Returns (trusted, trust_failure).

    Arms, in order, first pass wins: (1) a non-wildcard `prflow.allowed_bots` entry; (2) a
    bot on a same-repository head (`same_repo_head`), when `allowed_bots` holds `*` — gh
    reports every bot's collaborator permission as `none`, so a same-repository head is its
    proof of write access; (3) a human passing the trigger gate's user rule, its permission
    looked up in `repo` (`owner/name`). The PRFlow trigger gate reads a `*` in `allowed_bots`
    as a literal login, not a wildcard. A None `is_bot`, `repo` or `same_repo_head` is a field
    the caller could not read; an arm that needs it returns TRUST_FAILURE_PR_FIELDS.
    checklist_finalize.py's `prior` calls it with the `same_repo_head=False` default, so a `*`
    there admits no comment author.
    """
    bots = _config_read(".prflow.allowed_bots", "", config_path)
    bot_entries = [] if bots is None else bots.split(",")
    if _listed_bot(login, bot_entries):
        return True, None
    if is_bot is None:
        return False, TRUST_FAILURE_PR_FIELDS
    if is_bot:
        if bots is None:
            return False, TRUST_FAILURE_ALLOWED_BOTS
        if not any(e.strip() == "*" for e in bot_entries):
            return False, None
        if same_repo_head is None:
            return False, TRUST_FAILURE_PR_FIELDS
        return same_repo_head, None
    trusted, failure = _authorized_human(login, repo, config_path)
    if not trusted and failure is None and bots is None:  # arm 1 was never decided
        failure = TRUST_FAILURE_ALLOWED_BOTS
    return trusted, failure


def _filer_trust(view: dict, config_path: str | None) -> tuple[bool, str | None]:
    """Guard 1: is the PR author a trusted deferral filer (author_trust)? Returns (trusted,
    trust_failure). The author is the PR's, never the payload's `filed_by`, which the body's
    editors control.
    """
    author = view.get("author", _MISSING)
    if not isinstance(author, dict):
        _malformed("author", author, "an object")
        return False, TRUST_FAILURE_PR_FIELDS
    login = author.get("login", _MISSING)
    if not isinstance(login, str) or not login.strip():
        _malformed("author.login", login, "a non-empty string")
        return False, TRUST_FAILURE_PR_FIELDS
    is_bot = author.get("is_bot", _MISSING)
    cross = view.get("isCrossRepository", _MISSING)
    url = view.get("url", _MISSING)
    trusted, failure = author_trust(
        login, is_bot if isinstance(is_bot, bool) else None, _repo_slug(url), config_path,
        (not cross) if isinstance(cross, bool) else None)
    if failure == TRUST_FAILURE_PR_FIELDS:  # name the field the failing arm read
        if not isinstance(is_bot, bool):
            _malformed("author.is_bot", is_bot, "a boolean")
        elif is_bot:
            _malformed("isCrossRepository", cross, "a boolean")
        else:
            _malformed("url", url, "a pull-request URL")
    return trusted, failure


def _check_issue_cross_link(issue_number: int, pr_number: int) -> str | None:
    """Returns None if valid, else a rejection reason string."""
    r = _run(
        [GH, "issue", "view", str(issue_number),
         "--json", "body,state", "--jq",
         "[.body, .state] | @json"],
        check=False,
    )
    if r.returncode != 0:
        # rc=127 with empty stdout is _run's OSError sentinel (gh could not execute
        # at all — e.g. an unrunnable shim), not a genuine gh/GitHub failure (404,
        # permission, rate limit). An unusable gh invalidates the whole matching
        # run, not just this one deferral, so fail loudly instead of silently
        # misclassifying it as "issue unreadable" and discarding the diagnostic.
        if r.returncode == 127 and not r.stdout:
            _fail(f"could not execute {GH!r} while checking issue #{issue_number}: "
                  f"{r.stderr.strip()} (set DEVFLOW_GH to a working GitHub CLI)")
        sys.stderr.write(
            f"match-deferrals.py: could not read issue #{issue_number} "
            f"({r.stderr.strip()}); treating as unreadable\n"
        )
        return REASON_ISSUE_UNREADABLE
    body, state = json.loads(r.stdout.strip())
    if state.upper() != "OPEN":
        return REASON_ISSUE_CLOSED
    if f"PR #{pr_number}" not in body:
        return REASON_UNLINKED_FOLLOWUP
    return None


def _norm_path(path: str) -> str:
    """Canonical repo-relative comparison basis for a path.

    Both operands of every hunk-key comparison pass through this, so a
    non-canonical spelling (`./docs/x.md`, `docs//x.md`, a backslash form)
    compares equal to the canonical `docs/x.md` diff key. Purely lexical — no
    filesystem access, so it is safe on paths that do not exist. Guard-class 2:
    pure Python (`PurePosixPath`/`str`), never a PATH tool.

    An empty path returns unchanged so the caller's own emptiness checks still
    decide. Lexical normalization does NOT collapse `..`, so the traversal guard
    upstream of every call site keeps its meaning.
    """
    if not path:
        return path
    return PurePosixPath(path.replace("\\", "/")).as_posix()


def _parse_diff_hunks(diff_text: str) -> dict:
    """Returns {file_path: [(start_line, end_line), ...]} for added/modified
    lines on the new side. Conservative — includes both add and context lines
    in the hunk range, which over-approximates the affected region (safe for
    widens-surface — false positives reject deferrals, never honor them
    incorrectly).

    Keys are normalized through `_norm_path` so every consumer
    (`_verify_disclosure`'s self-foreclosure exclusion, `_widens_surface`)
    compares on one canonical basis (issue #660 review).
    """
    hunks: dict[str, list[tuple[int, int]]] = {}
    current_file: str | None = None
    file_re = re.compile(r"^\+\+\+ b/(.+)$")
    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

    for line in diff_text.splitlines():
        m = file_re.match(line)
        if m:
            current_file = _norm_path(m.group(1))
            hunks.setdefault(current_file, [])
            continue
        m = hunk_re.match(line)
        if m and current_file:
            start = int(m.group(1))
            length = int(m.group(2) or "1")
            end = start + max(length - 1, 0)
            hunks[current_file].append((start, end))
    return hunks


def _deferral_id(d) -> str:
    return d.get("id", "(no-id)") if isinstance(d, dict) else "(no-id)"


def _line_range_shape(line_range) -> str | None:
    """Name how a non-null `line_range` is not two ints, start <= end, else None."""
    if not isinstance(line_range, list):
        return f"{_shape(line_range)}, not an array"
    if len(line_range) != 2:
        return f"an array of length {len(line_range)}, not 2"
    for n in line_range:
        if not isinstance(n, int) or isinstance(n, bool):
            return f"an array holding {_shape(n)}, not two integers"
    if line_range[0] > line_range[1]:
        return f"reversed ({line_range[0]} > {line_range[1]})"
    return None


def _finding_shape_error(index: int, finding) -> str | None:
    """Name a malformed findings element's index, field and shape, else None.

    A null or missing `line_range` is not malformed (the reviewer contract allows null).
    """
    if not isinstance(finding, dict):
        return f"findings[{index}] is {_shape(finding)}, not an object"
    line_range = finding.get("line_range")
    shape = None if line_range is None else _line_range_shape(line_range)
    return None if shape is None else f"findings[{index}].line_range is {shape}"


def _entry_shape_error(d) -> str | None:
    """Return the first wrong-typed field of a deferral entry, else None.

    An absent or null `reason`, `reason.category`, `finding.file`,
    `finding.line_range` or `follow_up` is not malformed — the per-entry guards
    in main() decide it. A present `finding` must be a mapping, and a present
    `line_range` a list of exactly two ints, start not greater than end.
    """
    if not isinstance(d, dict):
        return "entry"
    reason = d.get("reason")
    if reason is not None:
        if not isinstance(reason, dict):
            return "reason"
        category = reason.get("category")
        if category is not None and not isinstance(category, str):
            return "reason.category"
    finding = d.get("finding", {})
    if not isinstance(finding, dict):
        return "finding"
    file_path = finding.get("file")
    if file_path is not None and not isinstance(file_path, str):
        return "finding.file"
    line_range = finding.get("line_range")
    if line_range is not None and _line_range_shape(line_range) is not None:
        return "finding.line_range"
    follow_up = d.get("follow_up")
    if follow_up is not None and not isinstance(follow_up, dict):
        return "follow_up"
    return None


def _widens_surface(deferral: dict, hunks: dict) -> bool:
    file_path = deferral.get("finding", {}).get("file")
    line_range = deferral.get("finding", {}).get("line_range") or []
    if not file_path or len(line_range) != 2:
        return False
    start, end = line_range
    file_hunks = hunks.get(_norm_path(file_path), [])
    for h_start, h_end in file_hunks:
        if (h_start - WIDENS_SURFACE_TOLERANCE) <= end and \
           (h_end + WIDENS_SURFACE_TOLERANCE) >= start:
            return True
    return False


def _ranges_overlap(a: list, b: list, tolerance: int) -> bool:
    if len(a) != 2 or len(b) != 2:
        return False
    return (a[0] - tolerance) <= b[1] and (a[1] + tolerance) >= b[0]


def _match_finding_to_deferral(finding: dict, deferral: dict) -> bool:
    df = deferral.get("finding", {})
    if finding.get("file") != df.get("file"):
        return False
    if finding.get("kind") != df.get("kind"):
        return False
    return _ranges_overlap(
        finding.get("line_range") or [],
        df.get("line_range") or [],
        LINE_DRIFT_TOLERANCE,
    )


# A Phase 3 finding's other severity words, lower-cased, to their ladder word. Kept here, not in
# verdict_report._severity: stored checklist rows never carry Major/Minor.
_SEVERITY_ALIASES = {"major": "important", "minor": "suggestion"}
_UNTRUSTED_LINE = ("**Block claimed but not honored — PR author passed none of the three "
                   "deferral-filer trust arms.{} All deferrals rejected.**")


def _one_line(value) -> str:
    # Not verdict_report._one_line: this keeps a value's own spacing and prints null as `None`.
    return _report()._uncomment(str(value).replace("\r", " ").replace("\n", " "))


def _report():
    """The sibling verdict_report.py: its `SEVERITIES` (highest first) are the `--threshold`
    values, and the section uses its `_severity`. An unimportable sibling exits 2, naming the
    fault on stderr."""
    try:
        import verdict_report
        return verdict_report
    except Exception as e:
        _fail("--threshold needs the severity ladder in verdict_report.py beside this file, "
              f"which could not be imported ({type(e).__name__}: {e})")


def _severity(finding: dict) -> str:
    """The finding's ladder word by verdict_report's rule, after the aliases above."""
    severity = finding.get("severity")
    alias = _SEVERITY_ALIASES.get(severity.lower()) if isinstance(severity, str) else None
    return _report()._severity(finding if alias is None else {"severity": alias})


def _location(finding: dict) -> str:
    """`an unknown location` when `file` is not a non-blank string; else `file:start`, or `file`
    alone when line_range[0] is not an int."""
    file_path = finding.get("file")
    if not isinstance(file_path, str) or not file_path.strip():
        return "an unknown location"
    line_range = finding.get("line_range")
    start = line_range[0] if isinstance(line_range, list) and line_range else None
    if isinstance(start, int) and not isinstance(start, bool):
        return f"{_one_line(file_path)}:{start}"
    return _one_line(file_path)


def _deferrals_section(result: dict, findings: list, threshold: str,
                       unreadable: str | None = None) -> str:
    """The report's `## Deferrals` markdown; "" when no block is present. `unreadable` is why a
    present block yielded no deferrals list."""
    if not result["block_present"]:
        return ""
    if unreadable is not None:
        return f"## Deferrals\n- Unreadable block: {_one_line(unreadable)}\n"
    ladder = _report().SEVERITIES
    lines = ["## Deferrals"]
    if result["pr_author_trusted"] is False:
        failure = result["trust_failure"]
        lines.append(_UNTRUSTED_LINE.format(
            "" if failure is None else f" (trust check failed: `{_one_line(failure)}`)"))
    lines += ["A deferral never demotes a finding.",
              f"- Matched: {len(result['honored'])}"]
    floor = ladder.index(threshold)
    for h in result["honored"]:
        finding = findings[h["finding_index"]]
        target = ("disclosure" if h["category"] == FORECLOSURE_CATEGORY
                  else f"#{_one_line(h['follow_up_issue'])}")
        severity = _severity(finding)
        gate = ("filed at or above the verdict threshold" if ladder.index(severity) <= floor
                else "filed below the verdict threshold")
        lines.append(f"  - {_one_line(h['deferral_id'])} → {target} ({_one_line(h['category'])}): "
                     f"matches the {severity.capitalize()} finding at {_location(finding)}; {gate}")
    lines.append(f"- Not applied: {len(result['rejected_deferrals'])}")
    for r in result["rejected_deferrals"]:
        detail = r.get("detail")
        lines.append(f"  - {_one_line(r['deferral_id'])} — {_one_line(r['reason'])}"
                     + ("" if detail is None else f" ({_one_line(detail)})"))
    return "\n".join(lines) + "\n"


def _emit(result: dict, findings: list, threshold: str | None,
          unreadable: str | None = None) -> int:
    if threshold is not None:
        result["deferrals_section"] = _deferrals_section(result, findings, threshold, unreadable)
    print(json.dumps(result, indent=2, default=str))
    return 0


def _force_utf8_streams():
    """Force stdin/stdout/stderr to UTF-8, idempotently and defensively, in the CLI
    entry path only (not at import — so unit-test imports don't mutate the
    importer's global streams). Harmless where this script emits only ASCII, but
    keeps every first-party helper self-defending against a non-UTF-8 ambient
    codec (Windows' cp1252). The guard tolerates a non-`TextIOWrapper` stream."""
    for _stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None):
    _force_utf8_streams()
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--pr", type=int, required=True,
                   help="PR number whose body holds the deferrals block.")
    p.add_argument("--diff", required=True,
                   help="Path to the cached diff (for widens-surface check).")
    p.add_argument("--findings", required=True,
                   help="Path to JSON file with current Phase 3 findings, "
                        "or `-` to read from stdin.")
    p.add_argument("--config", default=None,
                   help="Path to config.json (default: the repo-root "
                        ".prflow/config.json, resolved via git rev-parse "
                        "--show-toplevel with a cwd fallback; issue #295). A "
                        "non-empty explicit value is honored verbatim.")
    p.add_argument("--threshold",
                   help="Verdict severity threshold, one of verdict_report.py's SEVERITIES; adds "
                        "the rendered `deferrals_section`.")
    args = p.parse_args(argv)
    if args.threshold is not None and args.threshold not in _report().SEVERITIES:
        p.error(f"argument --threshold: invalid choice: {args.threshold!r} "
                f"(choose from {', '.join(_report().SEVERITIES)})")

    diff_path = Path(args.diff)
    if args.findings == "-":
        raw_findings = sys.stdin.read()
        if not raw_findings.strip():
            _fail("--findings - was passed but stdin was empty")
    else:
        findings_path = Path(args.findings)
        if not findings_path.is_file():
            _fail(f"findings file not found: {findings_path}")
        raw_findings = findings_path.read_text(encoding="utf-8")
    try:
        findings = json.loads(raw_findings)
    except json.JSONDecodeError as e:
        _fail(f"findings input is not valid JSON: {e}")
    if not isinstance(findings, list):
        _fail("findings input must be a JSON array")

    view = _get_pr_view(args.pr)
    pr_body = view.get("body", _MISSING)
    if not isinstance(pr_body, str):
        sys.stderr.write(f"match-deferrals.py: gh's PR view field body is "
                         f"{_shape(pr_body)}, not a string; reading no deferrals block\n")
        pr_body = ""
    block = _extract_block(pr_body)
    unterminated = block is None and BLOCK_START in pr_body

    result = {
        "block_present": block is not None or unterminated,
        "pr_author_trusted": None,
        "trust_failure": None,
        "honored": [],
        "rejected_deferrals": [],
        "stats": {"total_deferrals": 0, "valid_after_guards": 0,
                  "honored": 0, "unmatched": 0},
    }

    if unterminated:
        return _emit(result, findings, args.threshold,
                     _ignored("no DEVFLOW_DEFERRED_FINDINGS_END marker after the START marker"))
    if block is None:
        return _emit(result, findings, args.threshold)

    payload, unreadable = _parse_yaml_payload(block)
    deferrals = payload.get("deferrals")
    if deferrals is None:
        deferrals = []
    elif not isinstance(deferrals, list):
        deferrals, unreadable = [], _ignored(
            f"deferrals is a {type(deferrals).__name__}, not a list")
    result["stats"]["total_deferrals"] = len(deferrals)

    if not deferrals:
        return _emit(result, findings, args.threshold, unreadable)

    # Only here, past the no-deferrals return, so a PR without deferrals costs no
    # permission lookup.
    pr_author_trusted, result["trust_failure"] = _filer_trust(view, args.config)
    result["pr_author_trusted"] = pr_author_trusted

    if not pr_author_trusted:
        for d in deferrals:
            result["rejected_deferrals"].append({
                "deferral_id": _deferral_id(d),
                "reason": REASON_UNTRUSTED_FILER,
            })
        return _emit(result, findings, args.threshold)

    hunks = {}
    if diff_path.is_file():
        hunks = _parse_diff_hunks(
            diff_path.read_text(encoding="utf-8", errors="replace")
        )
    # Total parsed hunks across all files — the operand the foreclosure guard
    # fails closed on when the cached diff was absent, unreadable, or parsed to
    # zero hunks (issue #621). `_parse_diff_hunks` seeds an empty list per `+++`
    # header, so a non-empty `hunks` dict does not imply any real hunk — count
    # the tuples, not the keys.
    diff_hunk_count = sum(len(v) for v in hunks.values())
    repo_root = _repo_root()

    valid_deferrals: list[dict] = []
    for d in deferrals:
        deferral_id = _deferral_id(d)
        shape_error = _entry_shape_error(d)
        if shape_error is not None:
            result["rejected_deferrals"].append({
                "deferral_id": deferral_id,
                "reason": REASON_MALFORMED_ENTRY,
                "detail": shape_error,
            })
            continue

        # issue #621: a foreclosure entry (reason.category == "settled-by-
        # disclosure") has no follow-up issue by design. It skips the missing-
        # follow-up-issue + mutual-cross-link guards entirely; guards 1
        # (trusted filer, already applied above), 3 (widens surface), and 4
        # (disclosure verification) govern it. The `reason.category` slot is
        # the exact discriminator between old-shape and foreclosure entries.
        category = (d.get("reason") or {}).get("category")
        if category == FORECLOSURE_CATEGORY:
            if _widens_surface(d, hunks):
                result["rejected_deferrals"].append({
                    "deferral_id": deferral_id,
                    "reason": REASON_WIDENS_SURFACE,
                })
                continue
            detail = _verify_disclosure(d, hunks, diff_hunk_count, repo_root)
            if detail is not None:
                result["rejected_deferrals"].append({
                    "deferral_id": deferral_id,
                    "reason": REASON_DISCLOSURE_UNVERIFIED,
                    "detail": detail,
                })
                continue
            valid_deferrals.append(d)
            continue

        follow_up = d.get("follow_up") or {}
        issue_n = follow_up.get("issue")
        if not isinstance(issue_n, int):
            result["rejected_deferrals"].append({
                "deferral_id": deferral_id,
                "reason": REASON_MISSING_FOLLOW_UP_ISSUE,
            })
            continue

        cross_link_reason = _check_issue_cross_link(issue_n, args.pr)
        if cross_link_reason:
            result["rejected_deferrals"].append({
                "deferral_id": deferral_id,
                "reason": cross_link_reason,
            })
            continue

        if _widens_surface(d, hunks):
            result["rejected_deferrals"].append({
                "deferral_id": deferral_id,
                "reason": REASON_WIDENS_SURFACE,
            })
            continue

        valid_deferrals.append(d)

    result["stats"]["valid_after_guards"] = len(valid_deferrals)

    # A malformed finding is seeded as claimed, so no deferral matches it (issue #1554).
    claimed_finding_indices: set[int] = set()
    for i, finding in enumerate(findings if valid_deferrals else []):
        error = _finding_shape_error(i, finding)
        if error is not None:
            sys.stderr.write(f"match-deferrals.py: {error}; it matches no deferral\n")
            claimed_finding_indices.add(i)
    for d in valid_deferrals:
        matched_index = None
        for i, finding in enumerate(findings):
            if i in claimed_finding_indices:
                continue
            if _match_finding_to_deferral(finding, d):
                matched_index = i
                break
        if matched_index is None:
            result["rejected_deferrals"].append({
                "deferral_id": d.get("id", "(no-id)"),
                "reason": REASON_UNMATCHED,
            })
            continue
        claimed_finding_indices.add(matched_index)
        result["honored"].append({
            "finding_index": matched_index,
            "deferral_id": d.get("id", "(no-id)"),
            "follow_up_issue": (d.get("follow_up") or {}).get("issue"),
            "category": (d.get("reason") or {}).get("category", "(unspecified)"),
        })

    result["stats"]["honored"] = len(result["honored"])
    result["stats"]["unmatched"] = sum(
        1 for r in result["rejected_deferrals"] if r["reason"] == REASON_UNMATCHED
    )

    return _emit(result, findings, args.threshold)


if __name__ == "__main__":
    sys.exit(main())
