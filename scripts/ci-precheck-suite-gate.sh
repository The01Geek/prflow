#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# ci-precheck-suite-gate.sh — decide whether ci.yml's expensive suite jobs
# (shard/test/lint/lint-manifest) run for this event, or are suppressed as
# redundant, and emit the decision as `key=value` lines the `precheck` job
# appends to $GITHUB_OUTPUT.
#
# SOLE IN-REPO CALLER: the `precheck` job in .github/workflows/ci.yml. That
# workflow is REPO-INTERNAL (install.sh ships no ci.yml to consumers), so this
# helper is not vendored.
#
# WHY A HELPER, NOT INLINE YAML: this is a branch selection over a user-visible,
# merge-affecting outcome — exactly the class this repo keeps in a scripts/*.sh
# helper the suite can drive arm by arm (the describe-denial-count.sh /
# post-ci-review-trigger.sh precedent), rather than in an untestable `if:`.
#
# The two suppression cases, and why each is safe:
#   R1  a cloud-implement bot mid-run push (`synchronize` by the implement App):
#       the PR is a draft for the whole run, so no merge gate is in play; the
#       suite runs once at the end when `gh pr ready` fires `ready_for_review`.
#       R1 emits NO success status, so a draft's head never looks "already green"
#       and the ready toggle always runs the real suite.
#   R2  a `ready_for_review` toggle whose head SHA ALREADY has a real green run of
#       both required checks: re-running an identical suite on the same tree is
#       waste, so the test/lint jobs re-affirm the prior success instead. R2 is
#       set ONLY when both required checks were resolved `success` on this exact
#       head by a prior run — a real run, since R1 never produces success.
#
# FAIL SAFE TOWARD RUNNING. Every path that cannot ESTABLISH a suppression
# emits run_suite=true / reaffirm=false. A `gh`/`jq` failure, an in-progress or
# absent prior run, or one green check beside a non-green one all fall through to
# running the suite. The asymmetry is deliberate: a redundant run wastes minutes,
# a wrongly-skipped required check un-gates a merge. Always exits 0 so the job
# never fails-with-no-outputs (which would leave downstream comparands empty).
#
# Outputs (one per line): run_suite, reaffirm, already_green — each `true`/`false`.

set -uo pipefail

# The implement App's bot login. COUPLED to the actor guard's rationale in
# ci.yml and pinned by lib/test/test_python_scripts_part4.py: a rename of the GitHub
# App silently stops R1 suppression, so the pin reddens the suite on drift.
IMPLEMENT_BOT_LOGIN='prflow-implementer[bot]'

# The exact ci.yml required-check job names (the `# prflow:required-check`
# markers). COUPLED to those job `name:` values; the test module pins the pair.
REQUIRED_CHECK_TEST='lib + python tests'
REQUIRED_CHECK_LINT='lint (shellcheck + actionlint + ruff)'

EVENT_NAME="${EVENT_NAME:-}"
EVENT_ACTION="${EVENT_ACTION:-}"
ACTOR="${ACTOR:-}"
HEAD_SHA="${HEAD_SHA:-}"
REPO="${REPO:-}"

emit() {
  printf 'run_suite=%s\n' "$1"
  printf 'reaffirm=%s\n' "$2"
  printf 'already_green=%s\n' "$3"
}

# Non-PR events (push to main, workflow_dispatch) always run the suite.
if [ "$EVENT_NAME" != "pull_request" ]; then
  emit true false false
  exit 0
fi

# R1 — the implement bot's mid-run push. Pure GitHub-context decision, no query.
if [ "$EVENT_ACTION" = "synchronize" ] && [ "$ACTOR" = "$IMPLEMENT_BOT_LOGIN" ]; then
  echo "ci-precheck: R1 — implement-bot mid-run push ($ACTOR), suite suppressed (PR is a draft; the ready toggle runs it)" >&2
  emit false false false
  exit 0
fi

# R2 — a ready toggle whose head already has a real green run. Only this event
# consults the check-runs API; every other event runs the suite unconditionally.
if [ "$EVENT_ACTION" = "ready_for_review" ]; then
  gh="$(
    if [ -f "${BASH_SOURCE[0]%/*}/../lib/resolve-gh.sh" ]; then
      # shellcheck source=/dev/null
      . "${BASH_SOURCE[0]%/*}/../lib/resolve-gh.sh" && devflow_resolve_gh
    else
      printf '%s\n' "${DEVFLOW_GH:-gh}"
    fi
  )"

  # Fail closed toward running: a missing head SHA, or an unusable query, cannot
  # establish "already green".
  if [ -z "$HEAD_SHA" ] || [ -z "$REPO" ]; then
    echo "ci-precheck: ready_for_review with no head SHA/repo to query — running the suite" >&2
    emit true false false
    exit 0
  fi

  # Collect the set of check-run NAMES that concluded `success` on this head.
  # jq is preflight-guaranteed, so it may derive this selection value.
  green_names="$(
    $gh api --paginate "repos/${REPO}/commits/${HEAD_SHA}/check-runs" \
      --jq '.check_runs[] | select(.conclusion == "success") | .name' 2>/dev/null
  )" || green_names=""

  has_test=false
  has_lint=false
  while IFS= read -r name; do
    [ "$name" = "$REQUIRED_CHECK_TEST" ] && has_test=true
    [ "$name" = "$REQUIRED_CHECK_LINT" ] && has_lint=true
  done <<EOF
$green_names
EOF

  if [ "$has_test" = true ] && [ "$has_lint" = true ]; then
    echo "ci-precheck: R2 — head $HEAD_SHA already green on both required checks; re-affirming instead of re-running" >&2
    emit false true true
    exit 0
  fi

  echo "ci-precheck: ready_for_review head $HEAD_SHA not established green (test=$has_test lint=$has_lint) — running the suite" >&2
  emit true false false
  exit 0
fi

# opened / reopened / a human synchronize — always run.
emit true false false
exit 0
