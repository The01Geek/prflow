#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# Render a consumer prompt extension for injection into a SKILL.md at render time.
#
# Usage: render-prompt-extension.sh SKILL_NAME
#
# This is the command behind a `!`…`` render-time placeholder in a SKILL.md body.
# No SKILL.md carries such a placeholder today — PRs #1471 and #1473 removed every
# one — so nothing currently reaches this script; the description below is of the
# mechanism it was built for, not of a live call path.
# Claude Code executes such a placeholder BEFORE the model sees the skill and
# substitutes this script's stdout in its place, so the extension arrives as prompt
# text rather than as a command the agent must choose to run (issue #1264: the load
# reached the agent in only 8 of 18 sampled review runs and 1 of 4 implement runs,
# and both failure modes were silent).
#
# WHY A WRAPPER, AND WHY IT MUST NEVER FAIL
# -----------------------------------------
# A non-zero exit from an injected command aborts the entire skill invocation at
# zero turns: the headless run then exits `is_error: false` with an empty result,
# indistinguishable in CI from a successful run. `load-prompt-extension.sh` exits 2
# on every present-but-undeliverable shape, which is an ordinary thing for a
# consumer tree to contain. Wired naively into a placeholder that turns a benign
# no-op into a silent no-verdict run — the exact failure class issues #363 / #401 /
# #484 / #1064 exist to fight, introduced at the merge gate. So this script
# ALWAYS exits 0 and ALWAYS prints a status line: the rendered skill body carries a
# positive statement of what happened rather than an absence to be inferred from.
#
# Note the header is `set -u` only — deliberately NOT `set -e` and NOT `pipefail`.
# The whole contract is that no inner failure propagates; an `-e` here would
# reintroduce the abort this script exists to prevent.
#
# THE STATUS VOCABULARY
# ---------------------
# Generalized from the `EXTENSION-STATUS:` three-token contract that
# skills/review/phases/phase-3-agents.md already imposes on the DISPATCHED reviewer
# subagent. This script gives the orchestrator's own load the counterpart it lacked.
#
#   PROMPT-EXTENSION-STATUS: content-present
#       ...followed by a blank line and the extension's content. Stated precisely,
#       because the stronger claim would be false: the content is captured with `$(…)`
#       and re-emitted with a single terminating newline, so it is byte-exact EXCEPT at
#       the very end — trailing blank lines collapse to one newline, and an extension
#       consisting only of blank lines therefore renders `present-empty`. Nothing between
#       the first and last non-blank byte is altered. The whole-file byte-exact path is
#       load-prompt-extension.sh's, not this wrapper's; prompt text does not depend on
#       trailing whitespace, which is why the capture is not reworked to preserve it.
#   PROMPT-EXTENSION-STATUS: present-empty
#       The loader's single no-op class: the extension file is ABSENT, or present
#       and empty. Both mean "this consumer configured no instructions", which the
#       calling skill reads as "proceed unchanged". These two shapes are deliberately
#       NOT re-distinguished here: the loader owns extension-directory resolution
#       (two branches, see its header) and re-deriving the path to tell them apart
#       would duplicate that resolution in a second place, free to drift from it.
#   PROMPT-EXTENSION-STATUS: unestablished (<reason>)
#       The extension's state could not be established. NEVER collapsed onto
#       present-empty — that collapse is the `unknown is not zero` trap this
#       repository refuses everywhere else, and here it would let a policy-free run
#       read as a clean policy pass.
#
# `unestablished` covers: the loader refused the input or found the extension
# undeliverable (its exit 2 — unreadable, broken symlink, non-regular file, bad
# arguments); an ABSENT TRUSTED CLOSURE (DEVFLOW_PROMPT_EXTENSION_ROOT names a
# directory that does not exist, which the loader alone would report as an ordinary
# absent file — an empty-looking answer for a closure that failed to materialize);
# a missing skill-name argument; a loader this script cannot locate or execute; and
# any exit status outside {0, 2}, which is by construction a shape neither this
# script nor the loader anticipated.
#
# READING THE ENVIRONMENT IS THIS SCRIPT'S JOB, NOT THE PLACEHOLDER'S
# ------------------------------------------------------------------
# The injected command must be statically analyzable: a `${VAR:-default}` inside the
# placeholder text is refused with `Contains expansion` (measured, run 31058109064).
# So DEVFLOW_PROMPT_EXTENSION_ROOT is read HERE, in this script's own body, never at a
# call site. Do not move this read into a placeholder.
#
# Stated precisely, because the narrower claim is the true one: the placeholder carries
# the bare `${CLAUDE_SKILL_DIR}` anchor and NO OTHER expansion. It is not
# expansion-free. The two are believed to differ in kind — Claude Code substitutes
# `${CLAUDE_SKILL_DIR}` in skill markdown before the command is analyzed, so the
# analyzer should never see `${…}` there, whereas `DEVFLOW_PROMPT_EXTENSION_ROOT` is not
# a Claude Code template variable and survives as literal text to be refused. That
# distinction is INFERRED, not measured: the dispatched probe used a bare literal path,
# so no run has exercised an anchor-bearing placeholder. Do not read this comment as
# evidence the `Contains expansion` hazard was designed out; it was narrowed to one
# expansion whose handling is assumed. docs/internal/cloud-allowlist.md records the
# residual, and issue #1264's two live-run acceptance criteria are what settle it.
#
# The variable is the loader's top-precedence branch and is exported by
# .github/workflows/devflow.yml's "Establish the trusted prompt-extension closure"
# step through $GITHUB_ENV, so an injected command inherits it from the CLI's process
# environment (measured, run 31058740794). That is what makes this mechanism read the
# base-ref closure #874/#1075 already materialize rather than the PR's working tree —
# the trusted-ref property is INHERITED here, not rebuilt.
#
# Exit codes:
#   0  always, on every input shape. There is no other exit status by design.

set -u

# Self-anchor, so the sibling loader is found wherever this script is invoked from —
# the local checkout, a vendored consumer install, or a plugin cache. `dirname` is not
# a tool lib/preflight.sh guarantees, so this uses the dirname-free spelling of the
# anchor that load-prompt-extension.sh itself uses. `cd`/`pwd` are bash builtins.
# BASH_SOURCE is defaulted to `$0`: `set -u` is in force above, and an invocation shape
# that leaves BASH_SOURCE unset would abort before the first status line — the one thing
# this script promises never to do. When neither names a directory the `cd` fails, the
# anchor is empty, and the locate guard below reports `unestablished`: fail closed, with
# a status line, which is the contract.
_RPE_SELF="${BASH_SOURCE[0]:-$0}"
_RPE_SELF_DIR="$(cd "${_RPE_SELF%/*}" 2>/dev/null && pwd)" || _RPE_SELF_DIR=""
_RPE_LOADER="${_RPE_SELF_DIR}/load-prompt-extension.sh"

# Emit an `unestablished` line and leave. Every reason reaches stdout through here, so
# the one-line shape cannot drift between call sites. Backticks and newlines are
# stripped from the reason with parameter expansion (never `tr`/`sed`, which
# lib/preflight.sh does not guarantee and whose absence would silently empty the
# value that decides what is emitted): the reason carries a filesystem path and a
# loader diagnostic, and this text lands inside a rendered prompt, so it must not be
# able to open a code fence or break the single-line contract.
_rpe_unestablished() {
    _rpe_reason="$1"
    _rpe_reason="${_rpe_reason//\`/\'}"
    _rpe_reason="${_rpe_reason//$'\n'/ }"
    _rpe_reason="${_rpe_reason//$'\r'/ }"
    printf 'PROMPT-EXTENSION-STATUS: unestablished (%s)\n' "$_rpe_reason"
    exit 0
}

_rpe_skill="${1:-}"

if [ -z "$_rpe_skill" ]; then
    _rpe_unestablished "no skill name was given to render-prompt-extension.sh"
fi

if [ -z "$_RPE_SELF_DIR" ] || [ ! -f "$_RPE_LOADER" ]; then
    _rpe_unestablished "could not locate load-prompt-extension.sh beside render-prompt-extension.sh (looked in '${_RPE_SELF_DIR:-<unresolved>}')"
fi

# An absent trusted closure is UNESTABLISHED, not empty. When the variable is set and
# non-empty the loader composes "<root>/<skill>.md" directly; if that root does not
# exist the loader finds no file and takes its ordinary absent-file no-op, which would
# reach this script as exit 0 with empty stdout and render as `present-empty`. That
# reading is wrong in the one case it matters most: on the cloud review tier a missing
# closure means the trusted materialization step did not produce what the run assumed,
# and reporting it as "this consumer configured no instructions" would hand a
# merge-gating review a clean-looking policy pass it never had.
if [ -n "${DEVFLOW_PROMPT_EXTENSION_ROOT:-}" ] && [ ! -d "${DEVFLOW_PROMPT_EXTENSION_ROOT}" ]; then
    _rpe_unestablished "DEVFLOW_PROMPT_EXTENSION_ROOT names '${DEVFLOW_PROMPT_EXTENSION_ROOT}', which is not a directory; the trusted prompt-extension closure was not established"
fi

# Redirect stderr to a scratch file so a diagnostic can be quoted into the status line
# without contaminating the extension bytes. The redirect TARGET is parameterized rather
# than the whole invocation being branched: when mktemp is unavailable the target falls
# back to /dev/null, which loses the diagnostic detail but never the render — one call
# site, so a future change to how the loader is invoked cannot be made in one arm only.
_rpe_err_file="$(mktemp 2>/dev/null)" || _rpe_err_file=""
_rpe_out="$("$_RPE_LOADER" "$_rpe_skill" 2>"${_rpe_err_file:-/dev/null}")"
_rpe_rc=$?
_rpe_err=""
if [ -n "$_rpe_err_file" ]; then
    # `$(<file)` is a bash builtin read — no `cat` process, and this runs at skill-render
    # time, on the critical path before the model sees a single token.
    _rpe_err="$(<"$_rpe_err_file")"
    rm -f "$_rpe_err_file" 2>/dev/null
fi

# The loader writes a breadcrumb to stderr on its DEVFLOW_PROMPT_EXTENSION_ROOT branch
# even on the success path, so stderr being non-empty is not itself a failure signal —
# only the exit status is. Keep the two apart. Every non-zero status takes one arm: the
# loader's documented exit 2 and any status outside {0, 2} are both "the extension's
# state could not be established", and naming the code in the reason serves both.
if [ "$_rpe_rc" -ne 0 ]; then
    _rpe_unestablished "load-prompt-extension.sh exited ${_rpe_rc}${_rpe_err:+: ${_rpe_err}}"
fi

# Exit 0. Empty stdout is the loader's documented no-op class (absent or empty file).
if [ -z "$_rpe_out" ]; then
    printf 'PROMPT-EXTENSION-STATUS: present-empty\n'
    exit 0
fi

printf 'PROMPT-EXTENSION-STATUS: content-present\n\n'
printf '%s\n' "$_rpe_out"
exit 0
