#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# apply-pr-triggerer.sh <pull-request-number> — best-effort, assign a draft PR
# created by /prflow:implement to the run's triggering user (issue #1165).
#
# WHO the triggerer is, by tier (the helper detects the tier from GITHUB_RUN_ID):
#   * Cloud (GITHUB_RUN_ID non-empty) — the run's origin identity the workflow
#     propagates through DEVFLOW_TRIGGERING_USER. FAIL-CLOSED on identity:
#     when that variable is empty the helper skips assignment and NEVER substitutes
#     another account (the token owner, the GitHub App identity, or GITHUB_ACTOR).
#     A missing cloud login is a deployment-skew signal (an older workflow paired
#     with a newer skill), not permission to guess. A `[bot]`-suffixed login is
#     skipped before any API call: a bot is not an assignable user, so requesting
#     one only earns an HTTP 403 (issue #512).
#   * Local (GITHUB_RUN_ID empty) — the authenticated GitHub login from
#     `gh api user --jq .login`, the repository's established local-identity pattern
#     (scripts/file-deferrals.py). An empty or failed lookup skips without guessing.
#
# Assignment goes through the REST Issues endpoint (a PR is an issue):
#   POST /repos/{owner}/{repo}/issues/{number}/assignees
# via `gh api`, whose `{owner}`/`{repo}` placeholders `gh` fills from the git
# remote WITHOUT the org-scoped GraphQL resolution `gh pr edit --add-assignee`
# would trigger — so a repo-scoped token (GitHub App installation token, or a
# fine-grained `repo`-only PAT) assigns successfully.
#
# GitHub can accept the POST and SILENTLY IGNORE an unassignable login (it returns
# 200 with the login absent from the response), so HTTP success alone does NOT mean
# assigned: the helper confirms the requested login is present in the response's
# assignees before reporting `applied`. An unconfirmed login is reported skipped.
#
# `unconfirmed` means UNESTABLISHED, not failed (CLAUDE.md's "unknown is not zero"):
# the POST returned rc 0, so the request succeeded and only the confirmation did not
# — an empty/truncated response body or a degraded $DEVFLOW_JQ lands here just as an
# ignored login does. Callers must record it as "could not confirm assignment", never
# as "unassigned"; every OTHER skip reason does establish that no assignment was made.
#
# OUTCOME CONTRACT (the closed set): the helper prints exactly ONE outcome token to
# STDOUT and exits 0:
#   * `assignment: applied <login>`   — the add-assignee response contains <login>.
#   * `assignment: skipped <reason>`  — every handled path that does NOT report
#     applied (invalid input, no cloud triggerer, empty/failed local identity, API
#     failure, or an unconfirmed response). <reason> is one of: invalid-input,
#     no-triggering-user, bot-login, identity-lookup-failed, empty-identity,
#     api-failure, unconfirmed. Every reason except `unconfirmed` establishes that
#     no assignment was made; `unconfirmed` establishes only that it could not be
#     confirmed.
# It ALWAYS exits 0 (best-effort: an assignment hiccup never aborts the caller) and
# NEVER prints an empty stdout — so the caller reads "no output at all" as a HARNESS
# REFUSAL (a denied command produces nothing), distinct from every handled skip.
# Detailed breadcrumbs go to STDERR; the single stdout line is the machine token.
#
# The ADOPT path (a resumed run whose PR a prior attempt created) does NOT call this
# helper — assignment is a create-time action, so an existing PR's assignees are left
# untouched. That is enforced at the call site (skills/implement/phases/phase-3-review.md),
# not here.
set -uo pipefail

# gh + jq binaries: resolved once via the single-source resolvers
# (execution-verified); an explicit DEVFLOW_GH/DEVFLOW_JQ still wins, so test
# stubs are untouched.
# shellcheck source=../lib/resolve-gh.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/resolve-gh.sh"
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"
# shellcheck source=../lib/resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/resolve-jq.sh"

# Emit the machine outcome token to stdout, a matching breadcrumb to stderr, exit 0.
_applied() { echo "assignment: applied $1"; echo "prflow: assigned PR #${NUMBER} to '$1'" >&2; exit 0; }
_skipped() {
  echo "assignment: skipped $1"
  echo "prflow: PR assignment skipped ($1) for #${NUMBER:-<none>}${2:+: $2} (best-effort, PR preserved)" >&2
  exit 0
}

# `${1:-}`, NOT `${1:?}`: a `${1:?}` aborts with a raw bash usage line and rc 1,
# breaking the always-exit-0 contract AND leaving the invalid-input guard below
# unreachable on the very shapes it exists to catch (mirrors apply-labels.sh #480).
NUMBER="${1:-}"

# Fail CLOSED on the caller arg-slip the skill warns about: a $PR_NUM that did not
# survive into this command. Missing and non-numeric both land here; neither calls
# GitHub. Not a harness denial — the token distinguishes it from the silent refusal.
case "$NUMBER" in
  ''|*[!0-9]*)
    _skipped invalid-input "non-numeric/missing pull-request number '${NUMBER}' (a caller arg-slip, most likely a shell variable that did not survive into this command) — NOT a harness denial" ;;
esac

# Resolve the triggering login by tier. GITHUB_RUN_ID is the cloud-tier signal.
if [ -n "${GITHUB_RUN_ID:-}" ]; then
  # Cloud tier — the propagated authorized sender only; never a fallback account.
  LOGIN="${DEVFLOW_TRIGGERING_USER:-}"
  if [ -z "$LOGIN" ]; then
    _skipped no-triggering-user "cloud run carries no DEVFLOW_TRIGGERING_USER (deployment skew: an older workflow with a newer skill) — refusing to substitute the token owner, App identity, or GITHUB_ACTOR"
  fi
  # A bot login is not an assignable user: GitHub answers the POST with HTTP 403,
  # which would land on the `api-failure` skip and read as a transport problem. It
  # reaches here when an automatic resume carried no readable origin, so name that
  # instead — before any API call (issue #512).
  case "$LOGIN" in
    *'[bot]')
      _skipped bot-login "cloud triggering user '${LOGIN}' is a bot, not an assignable user (a resume chain whose originating human could not be decoded) — no assignment requested" ;;
  esac
else
  # Local tier — the authenticated GitHub login. A failed query and an empty
  # result are distinct skips; neither guesses a login.
  if ! LOGIN="$("$DEVFLOW_GH" api user --jq .login 2>/dev/null)"; then
    _skipped identity-lookup-failed "'gh api user' failed (no auth / offline / API error) — not guessing a login"
  fi
  if [ -z "$LOGIN" ]; then
    _skipped empty-identity "'gh api user --jq .login' returned an empty login — not guessing a login"
  fi
fi

# Add the assignee. Capture the response body so login membership can be confirmed;
# capture stderr separately so a genuine failure names its cause in the breadcrumb.
# mktemp with the repo's fail-open fallback (a denied/failed mktemp must not leave
# an empty redirect target); the rm is guarded against the /dev/null sentinel.
_ERRF="$(mktemp 2>/dev/null || echo /dev/null)"
RESP="$("$DEVFLOW_GH" api --method POST "repos/{owner}/{repo}/issues/${NUMBER}/assignees" -f "assignees[]=${LOGIN}" 2>"$_ERRF")"
RC=$?
ERR_OUT="$(<"$_ERRF")"; [ "$_ERRF" = /dev/null ] || rm -f "$_ERRF"

if [ "$RC" -ne 0 ]; then
  _skipped api-failure "add-assignee POST failed: ${ERR_OUT}"
fi

# CONFIRM the requested login is present in the response's assignees before
# reporting applied — GitHub can 200 while silently ignoring an unassignable login.
# The membership decision is an EMITTED result, so it is derived through jq
# (preflight-guaranteed), never a non-preflight PATH tool (CLAUDE.md guard-class 2).
# The jq program is defensive over every documented-and-adversarial response shape:
# a non-array/absent `assignees` (wrong-type, scalar/array/valid-falsy root) yields
# no match and routes to `unconfirmed` — it NEVER falsely reports applied.
if printf '%s' "$RESP" | "$DEVFLOW_JQ" -e --arg login "$LOGIN" \
    'any(.assignees?[]?; .login? == $login)' \
    >/dev/null 2>&1; then
  _applied "$LOGIN"
fi

_skipped unconfirmed "the add-assignee request succeeded but its response did not confirm '${LOGIN}' among the assignees (GitHub may have silently ignored an unassignable login, or the response was empty/truncated) — assignment is UNCONFIRMED, not known to have failed"
