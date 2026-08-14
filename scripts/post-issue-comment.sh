#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# post-issue-comment.sh <issue-number> <body-file> — best-effort post a comment
# on an issue via the repo-scoped REST endpoint.
#
# Posts through
#   POST /repos/{owner}/{repo}/issues/{number}/comments
# via `gh api`, whose {owner}/{repo} placeholders gh fills from the git remote
# on BOTH tiers, WITHOUT the org-scoped GraphQL resolution that
# `gh issue comment` porcelain triggers — so a repo-scoped token (GitHub App
# installation token, or a fine-grained repo-only PAT) posts successfully. Mirrors
# ensure-label.sh / apply-labels.sh: it ALWAYS exits 0 (best-effort) and leaves a
# specific stderr breadcrumb naming the outcome, so a comment hiccup can never
# flip the caller's pass/fail decision. The cloud stall backstop (issue #266)
# uses it for its audit / fail-loud / diagnostic comments.
#
# The body is read from a FILE (never a positional arg) so arbitrary comment text
# — newlines, backticks, status glyphs — never traverses shell quoting.
set -uo pipefail

# gh binary: resolved once via the single-source resolver (execution-verified);
# an explicit DEVFLOW_GH still wins, so test stubs are untouched.
# shellcheck source=../lib/resolve-gh.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/resolve-gh.sh"
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"

NUMBER="${1-}"
BODY_FILE="${2-}"

# Best-effort input validation: a bad number or missing file gets a specific
# breadcrumb and a clean exit 0 (never an abort, never a masked success).
if [ -z "$NUMBER" ]; then
  echo "devflow: warning: post-issue-comment.sh missing issue-number argument (caller argument slip; best-effort, no comment posted)" >&2
  exit 0
fi
if [ -z "$BODY_FILE" ]; then
  echo "devflow: warning: post-issue-comment.sh missing body-file argument (caller argument slip; best-effort, no comment posted on #$NUMBER)" >&2
  exit 0
fi
if ! [[ "$NUMBER" =~ ^[0-9]+$ ]]; then
  echo "devflow: warning: post-issue-comment.sh got a non-numeric issue number '$NUMBER' (best-effort, no comment posted)" >&2
  exit 0
fi
if [ ! -f "$BODY_FILE" ]; then
  echo "devflow: warning: post-issue-comment.sh body file not found: '$BODY_FILE' (best-effort, no comment posted on #$NUMBER)" >&2
  exit 0
fi

# Discard stdout (the created-comment JSON) and keep only stderr, so a
# permissions / rate-limit / network failure is distinguishable from success in
# the breadcrumb — same capture discipline as apply-labels.sh.
ERR_OUT="$("$DEVFLOW_GH" api --method POST "repos/{owner}/{repo}/issues/${NUMBER}/comments" -F "body=@${BODY_FILE}" 2>&1 >/dev/null)"
RC=$?
if [ "$RC" -eq 0 ]; then
  echo "devflow: posted comment on #$NUMBER" >&2
else
  echo "devflow: warning: could not post comment on #$NUMBER (best-effort, continuing): ${ERR_OUT}" >&2
fi

exit 0
