#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# refresh-pr-on-resume.sh — on a cloud resume, point the open PR body's [View run] line at
# THIS run and strip any stopped-run note block, so a reviewer arriving via the PR reaches the
# live run and does not see a stale stopped-run banner (issue #2060). The gate job is the
# link's single owner; it calls this once on every adopt (resume) trigger, before the agent
# starts, mirroring its existing workpad Run-line refresh. Best-effort.
#
# A helper, not inline gate YAML, so the suite can drive this selection + read + transform +
# PATCH (CLAUDE.md's extract-inline-shell rule; resolve-existing-pr.sh is the reference). The
# "which PR" selection lives in resolve-issue-pr.py (shared with the workpad.py mirror); the
# note-block transform in pr-note-block.py; the link rewrite in refresh-pr-run-link.py — this
# helper only orchestrates them and does the two gh REST calls.
#
# Usage: refresh-pr-on-resume.sh --issue <n> --run-url <url>
#
# CONTRACT — one token line on stdout with a matching exit code; a stderr breadcrumb too:
#   REFRESHED <n>     exit 0   resolved the open PR and PATCHed its body
#   NOOP <n>          exit 0   resolved the PR but the transform left the body unchanged (no PATCH)
#   NO_PR             exit 2   the query ran cleanly and no open PR closes the issue
#   REFUSED <reason>  exit 3   the PR set, body read, transform, or PATCH could not be done
set -uo pipefail

_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# gh binary: the single-source execution-verified resolver; an explicit DEVFLOW_GH still wins
# with no probe, preserving the test suite's stubbing contract.
# shellcheck source=../lib/resolve-gh.sh
. "$_DIR/../lib/resolve-gh.sh" \
  || echo "prflow: refresh-pr-on-resume.sh could not source ../lib/resolve-gh.sh (a partial deployment carrying scripts/ without lib/?)" >&2
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"

ISSUE=""
RUN_URL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --issue) ISSUE="${2:-}"; shift 2 ;;
    --run-url) RUN_URL="${2:-}"; shift 2 ;;
    *) echo "prflow: refresh-pr-on-resume.sh: unknown argument '$1'" >&2; shift ;;
  esac
done

if [ -z "$ISSUE" ] || [ -z "$RUN_URL" ]; then
  echo "REFUSED missing-args"
  echo "prflow: refresh-pr-on-resume.sh needs --issue and --run-url" >&2
  exit 3
fi

# Resolve the open PR (newest closing the issue) through the shared selection helper. Read its
# own exit code: 0 found, 2 none (clean), 3 unresolvable.
PR_NUMBER="$(python3 "$_DIR/resolve-issue-pr.py" --issue "$ISSUE")"; RC=$?
if [ "$RC" -eq 2 ]; then
  echo "NO_PR"
  echo "prflow: no open PR closes issue #$ISSUE; PR-body run-link refresh + note strip skipped" >&2
  exit 2
fi
if [ "$RC" -ne 0 ] || [ -z "$PR_NUMBER" ]; then
  echo "REFUSED resolve"
  echo "prflow: could not resolve the open PR for issue #$ISSUE; PR-body maintenance skipped" >&2
  exit 3
fi

# Read the PR body via REST gh api ({owner}/{repo} placeholders — never GraphQL porcelain).
if ! PR_BODY="$("$DEVFLOW_GH" api "repos/{owner}/{repo}/pulls/$PR_NUMBER" --jq '.body' 2>/dev/null)"; then
  echo "REFUSED read"
  echo "prflow: could not read PR #$PR_NUMBER body (gh api read failed); PR-body maintenance skipped" >&2
  exit 3
fi
if [ -z "$PR_BODY" ]; then
  echo "REFUSED empty-body"
  echo "prflow: PR #$PR_NUMBER body is empty; refusing to transform an empty body" >&2
  exit 3
fi

# Strip any stopped-run note block, then refresh the Resolves-anchored [View run] line. The
# body is CAPTURED and guarded non-empty before the PATCH so a crashed transform cannot blank
# the description (issue #493 empty-body hardening).
NEW_BODY="$(printf '%s' "$PR_BODY" | python3 "$_DIR/pr-note-block.py" strip | python3 "$_DIR/refresh-pr-run-link.py" "$RUN_URL")" || NEW_BODY=""
if [ -z "$NEW_BODY" ]; then
  echo "REFUSED transform"
  echo "prflow: PR #$PR_NUMBER body transform produced no output; PATCH skipped to avoid blanking the PR body" >&2
  exit 3
fi

# Skip the write when the transform changed nothing (no note block to strip and the [View run]
# line already current) — the common resume case — so an idempotent resume spends no GitHub
# write nor its rate-limit budget.
if [ "$NEW_BODY" = "$PR_BODY" ]; then
  echo "NOOP $PR_NUMBER"
  echo "prflow: PR #$PR_NUMBER body already current (no stopped-run note, [View run] unchanged); no PATCH needed" >&2
  exit 0
fi

if printf '%s' "$NEW_BODY" | "$DEVFLOW_GH" api --method PATCH "repos/{owner}/{repo}/pulls/$PR_NUMBER" -F body=@- >/dev/null 2>&1; then
  echo "REFRESHED $PR_NUMBER"
  exit 0
fi
echo "REFUSED patch"
echo "prflow: PR #$PR_NUMBER body PATCH failed (run-link refresh + note strip); continuing" >&2
exit 3
