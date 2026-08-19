#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""DevFlow deferred-findings matcher for /devflow:review's Phase 4.0.

Reads the Scope-Acknowledged Findings block from a PR body (between the
DEVFLOW_DEFERRED_FINDINGS_START/END markers), validates each deferral
against four guards (guard 4 replaces guard 2 for a `settled-by-disclosure`
foreclosure entry, so any one deferral is validated against three), and matches the survivors against the current run's
Phase 3 findings. Emits a JSON demotion map the verdict engine consumes
to demote matched findings to Informational.

Guards (any failing guard rejects the deferral — finding flows through as
normal):
    1. Trusted filer:     PR author is in `prflow.allowed_bots` from
                          .prflow/config.json.
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

Matching rule (v1, conservative): a current finding matches a surviving
deferral iff same file AND same kind AND line_range overlaps within ±25
lines. Summary similarity is not used — file+kind+line_range is strong
enough to prevent false positives, and a more permissive rule would risk
demoting genuinely new findings that share vague terminology.

Usage:
    match-deferrals.py --pr N --diff PATH --findings (PATH | -) [--config PATH]

Pass `--findings -` to read the findings JSON from stdin. The stdin form is
required when the caller cannot write a temp file (e.g., /devflow:review
under devflow.yml's runner `review` profile, which is intentionally
read-only and does not have the Write tool).

Output (JSON to stdout, always exit 0 when the helper itself ran):
    {
      "block_present": true | false,
      "pr_author_trusted": true | false | null,
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
from pathlib import Path, PurePosixPath

if sys.version_info < (3, 11):  # fail fast, before any PEP 604 annotation is evaluated below
    sys.stderr.write(
        "devflow: Python 3.11+ required (found %s.%s.%s). This helper requires"
        " features of Python 3.11+. Install Python 3.11+; on Windows/Git-Bash"
        " run scripts/provision-python3-shim.sh --apply.\n"
        % sys.version_info[:3]
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

# Rejection reason codes — mirrored verbatim in
# skills/review/phases/phase-4-verdict.md prose (the review engine is a bundle
# since #529; the codes moved out of skills/review/SKILL.md with it).
# Edit both in lockstep.
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
    disclosure cannot be verified against the checked-out tree is rejected and
    the matching finding re-raises at full strength.

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
    target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return "path-outside-repo"
    # A disclosure the PR itself authors cannot foreclose that PR's findings —
    # reject when disclosure.path is a file the diff touched (>= 1 hunk).
    diff_files = {f for f, hs in hunks.items() if hs}
    if _norm_path(path) in diff_files:
        return "disclosure-in-diff"
    if not target.is_file():
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


def _run(cmd, *, check=True):
    # `encoding="utf-8"` pins the gh-output decode: this wrapper reads PR and
    # issue *bodies* (`gh pr view --json body`, `gh issue view --json body`),
    # which are routinely non-ASCII, so decoding through the locale codec would
    # raise UnicodeDecodeError under a non-UTF-8 ambient codec (Windows' cp1252).
    # Implies text mode, so `text=True` is dropped (passing both is redundant).
    # An OSError (ENOEXEC from a non-executable `gh` shim, or gh absent — the
    # host class DEVFLOW_GH exists for) is converted into the same structured
    # surface as a non-zero exit, so callers get a breadcrumb, not a traceback.
    try:
        return subprocess.run(
            cmd, check=check,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
        )
    except OSError as e:
        if check:
            _fail(f"could not execute {cmd[0]!r}: {e} "
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


def _config_get(key: str, default: str = "", config_path: str | None = None) -> str:
    if config_path is None:
        config_path = _default_config_path()
    here = Path(__file__).resolve().parent
    helper = here / "config-get.sh"
    r = _run([str(helper), key, default, config_path], check=False)
    if r.returncode != 0:
        # rc=127 with empty stdout is _run's OSError sentinel (config-get.sh could
        # not execute at all — e.g. it lost its exec bit on a Windows checkout, or
        # a bad shebang) — a genuinely broken helper, not "the key is unset". The
        # two are otherwise indistinguishable to this caller (allowed_bots_raw
        # silently resolving to "" makes pr_author_trusted False, which rejects
        # every deferral as untrusted-filer with no clue the real cause is a
        # broken helper, not policy). Log a breadcrumb so it's diagnosable.
        if r.returncode == 127 and not r.stdout:
            sys.stderr.write(
                f"match-deferrals.py: could not execute {str(helper)!r} "
                f"({r.stderr.strip()}); falling back to default {default!r} for "
                f"{key!r}\n"
            )
        return default
    return r.stdout.strip()


def _extract_block(pr_body: str) -> str | None:
    if BLOCK_START not in pr_body or BLOCK_END not in pr_body:
        return None
    start = pr_body.index(BLOCK_START) + len(BLOCK_START)
    end = pr_body.index(BLOCK_END, start)
    return pr_body[start:end]


def _parse_yaml_payload(block: str) -> dict:
    """Parse the YAML payload from the hidden DEVFLOW_DEFERRED_PAYLOAD comment.

    The PR-description renderer shows a human-readable Markdown table inside the
    START/END markers and stores the exact machine payload in a hidden HTML
    comment so it stays invisible in the rendered PR body. The schema is
    unchanged (schema_version + deferrals[]); only the payload's location moved
    out of a visible ```yaml fence into this comment.
    """
    try:
        import yaml
    except ImportError:
        _fail("PyYAML required to parse deferred-findings block")

    payload_match = re.search(
        re.escape(PAYLOAD_START) + r"\s*\n(.*?)\n-->", block, re.DOTALL
    )
    if not payload_match:
        # The START/END markers exist (we are inside the extracted block), so a
        # payload comment is expected. Its absence means the renderer dropped or
        # malformed it (e.g. an unterminated comment) — warn so a visibly-deferred
        # PR with no machine payload is diagnosable rather than silently honoring
        # nothing. Still degrade gracefully to {} (no run failure).
        sys.stderr.write(
            "match-deferrals.py: deferrals block present but no parseable "
            "DEVFLOW_DEFERRED_PAYLOAD comment found; ignoring the block\n"
        )
        return {}
    try:
        loaded = yaml.safe_load(payload_match.group(1))
    except yaml.YAMLError as e:
        sys.stderr.write(f"match-deferrals.py: YAML parse failed: {e}\n")
        return {}
    if loaded is None:
        # Payload comment present but empty/whitespace-only — same operator-visible
        # outcome as a missing comment (block present, nothing honored), so warn
        # for the same diagnosability reason.
        sys.stderr.write(
            "match-deferrals.py: DEVFLOW_DEFERRED_PAYLOAD comment is empty; "
            "ignoring the block\n"
        )
        return {}
    if not isinstance(loaded, dict):
        sys.stderr.write(
            "match-deferrals.py: payload is not a mapping; ignoring\n"
        )
        return {}
    return loaded


def _get_pr_body_and_author(pr_number: int) -> tuple[str, str]:
    r = _run(
        [GH, "pr", "view", str(pr_number),
         "--json", "body,author", "--jq",
         "[.body, (.author.login // \"\")] | @json"],
        check=False,
    )
    if r.returncode != 0:
        _fail(f"could not read PR #{pr_number}: {r.stderr.strip()}")
    body, author = json.loads(r.stdout.strip())
    return body, author


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


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8, idempotently and defensively, in the CLI
    entry path only (not at import — so unit-test imports don't mutate the
    importer's global streams). Harmless where this script emits only ASCII, but
    keeps every first-party helper self-defending against a non-UTF-8 ambient
    codec (Windows' cp1252). The guard tolerates a non-`TextIOWrapper` stream."""
    for _stream in (sys.stdout, sys.stderr):
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
    args = p.parse_args(argv)

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

    pr_body, pr_author = _get_pr_body_and_author(args.pr)
    block = _extract_block(pr_body)

    result = {
        "block_present": block is not None,
        "pr_author_trusted": None,
        "honored": [],
        "rejected_deferrals": [],
        "stats": {"total_deferrals": 0, "valid_after_guards": 0,
                  "honored": 0, "unmatched": 0},
    }

    if block is None:
        print(json.dumps(result, indent=2))
        return 0

    payload = _parse_yaml_payload(block)
    deferrals = payload.get("deferrals") or []
    result["stats"]["total_deferrals"] = len(deferrals)

    if not deferrals:
        print(json.dumps(result, indent=2))
        return 0

    allowed_bots_raw = _config_get(".prflow.allowed_bots", "", args.config)
    allowed_bots = {b.strip() for b in allowed_bots_raw.split(",") if b.strip()}
    pr_author_trusted = pr_author in allowed_bots if allowed_bots else False
    result["pr_author_trusted"] = pr_author_trusted

    if not pr_author_trusted:
        for d in deferrals:
            result["rejected_deferrals"].append({
                "deferral_id": d.get("id", "(no-id)"),
                "reason": REASON_UNTRUSTED_FILER,
            })
        print(json.dumps(result, indent=2))
        return 0

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
        deferral_id = d.get("id", "(no-id)")

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

    claimed_finding_indices: set[int] = set()
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
            "follow_up_issue": d.get("follow_up", {}).get("issue"),
            "category": d.get("reason", {}).get("category", "(unspecified)"),
        })

    result["stats"]["honored"] = len(result["honored"])
    result["stats"]["unmatched"] = sum(
        1 for r in result["rejected_deferrals"] if r["reason"] == REASON_UNMATCHED
    )

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
