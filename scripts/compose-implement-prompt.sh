#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# compose-implement-prompt.sh — compose the `/prflow:implement <n>` prompt with the
# engine-ground-truth block prepended, and publish it as the `prompt` step output
# (issue #1170).
#
# Why a helper rather than inline shell in devflow-implement.yml's `Compose implement
# grounding block` step: this file makes a three-way SELECTION (renderer absent /
# renderer produced nothing / compose and publish), and inline shell inside YAML cannot
# be unit-tested. A grep-pin on any one of the `::error::` literals is not coverage of
# the selection that chooses between them — a reordered or inverted arm would ship green.
# Extracted here so lib/test/run.sh drives every arm and the arm ORDER directly. Same
# reasoning, and same shape, as scripts/describe-denial-count.sh (issue #363).
#
# Reads from the environment:
#   ALLOWED_TOOLS  the exact resolved --allowed-tools string for this run (the
#                  `Resolve allowed-tools` step output). Forwarded to the renderer,
#                  which fails closed on an empty value (it renders "no commands are
#                  granted to this run" rather than an empty, unrestricted-looking fence).
#   NUMBER         the issue number the `/prflow:implement` command names.
#   GITHUB_OUTPUT  the step-output file. Absent/empty means there is nowhere to publish
#                  the composed prompt, so the run would launch on the bare prompt —
#                  the same end state as a missing renderer, and refused the same way.
#
# The arms, IN ORDER — the order is the contract, not an implementation detail:
#
#   1. renderer absent at BOTH the vendored and the repo-root path
#        -> ::error::, write NO `prompt` output, exit 1
#   2. renderer resolved but produced no block (empty stdout, or a non-zero exit)
#        -> ::error::, write NO `prompt` output, exit 1
#   3. otherwise
#        -> append `prompt<<DELIM … DELIM` to $GITHUB_OUTPUT, exit 0 — and an append
#           that FAILS is refused exactly like arms 1 and 2: ::error::, exit 1
#
# FAIL-LOUD, not best-effort — the deliberate reversal of this helper's original
# always-exit-0 contract. The engine-ground-truth block is the single home of the cloud
# headless-run discipline (never end the turn with a dispatch pending) and of this run's
# permitted-command list, so a run that silently proceeds on the bare prompt is a run
# with neither. Every arm that cannot publish a grounded prompt therefore fails the
# step, and devflow-implement.yml's `Compose implement grounding block` step is written
# to that contract — the two are edited together.
#
# Arms 1 and 2 still write NO `prompt` key at all. devflow-implement.yml keeps its
# `steps.compose.outputs.prompt || format('/prflow:implement {0}', …)` bare-prompt
# default, which a non-zero exit here now pre-empts; publishing an empty `prompt=`
# would be a silent way to ship a block-less prompt should that guard ever be relaxed,
# so both arms exit BEFORE the write.
#
# Renderer resolution is cwd-relative, matching every other bundled-helper call in the
# workflow (the run begins at the actions/checkout workspace root and the working
# directory persists): the vendored copy the `vendor-plugin` step materializes, then the
# repo-root copy so a self-repo checkout still finds one. Verification is of the
# renderer's OUTCOME (a non-empty block), never merely of the file's existence — a
# truncated vendored copy that exits 0 printing nothing must take arm 2, not ship an
# empty block into the prompt.

set -u

# Default the optional inputs once, up front, so every use below is a plain expansion —
# the same shape render-grounding-block.sh uses, and what keeps the renderer call line
# byte-identical to the inline one this helper replaces.
ALLOWED_TOOLS="${ALLOWED_TOOLS:-}"
NUMBER="${NUMBER:-}"
# Run-facts operands (issue #40). The cloud matcher refuses any command that expands a
# $GITHUB_*/$DEVFLOW_APP_ID variable, so the run cannot read these itself — the composer
# reads them here, in the workflow step's own process, and emits them as prompt literals.
# Defaulted up front so every use below is a plain expansion, the same shape as ALLOWED_TOOLS.
RUN_ID="${GITHUB_RUN_ID:-}"
RUN_ATTEMPT="${GITHUB_RUN_ATTEMPT:-}"
DEVFLOW_APP_ID="${DEVFLOW_APP_ID:-}"

RGB=.prflow/vendor/prflow/scripts/render-grounding-block.sh
[ -f "$RGB" ] || RGB=scripts/render-grounding-block.sh
if [ ! -f "$RGB" ]; then
  echo "::error::devflow: render-grounding-block.sh not found at either the vendored or repo path — the implement prompt would carry no engine-ground-truth block, this run's only statement of the headless-run discipline and of the commands it may execute. Repair the vendored .prflow/vendor/prflow tree, or check the vendor-plugin fetch (prflow_version). Refusing to run." >&2
  exit 1
fi

GROUNDING=$(MODE=implement ALLOWED_TOOLS="$ALLOWED_TOOLS" bash "$RGB") || GROUNDING=""
if [ -z "$GROUNDING" ]; then
  echo "::error::devflow: render-grounding-block.sh produced no output — the implement prompt would carry no engine-ground-truth block (the engine would rediscover its tool boundary by trial and denial, with no headless-run discipline at all). The renderer resolved at '$RGB' but printed nothing or exited non-zero: repair that copy, or check the vendor-plugin fetch (prflow_version). Refusing to run." >&2
  exit 1
fi

# An unset/empty GITHUB_OUTPUT is an environment fault rather than a broken vendor tree,
# and it is refused all the same: the end state is identical — an agent launched on the
# bare prompt, with no engine-ground-truth block — and this helper runs only from a
# GitHub Actions `run:` step, where the runner always supplies the file. The diagnostic
# names the environment as the cause so the operator is not sent to the vendor tree.
if [ -z "${GITHUB_OUTPUT:-}" ]; then
  echo "::error::devflow: GITHUB_OUTPUT is unset or empty — the composed implement prompt cannot be published, so the run would launch on the bare prompt with no engine-ground-truth block. This is a runner/environment fault, not a vendor-tree one (a GitHub Actions run: step always sets it). Refusing to run." >&2
  exit 1
fi

# Run-facts block (issue #40) — placed AFTER the grounding block and BEFORE the command
# line. It is informational: a missing operand renders `unestablished`/`absent` and never
# takes an ::error:: arm, so the composer still publishes the prompt and exits 0. A run id
# or run attempt that is unset or empty renders the literal `unestablished`; DEVFLOW_APP_ID
# renders `present` when non-empty (matching the workflow's `!= ''` gate) and `absent`
# otherwise — the value itself is never emitted, only its presence.
# `:-` yields the fallback for an unset OR empty operand (RUN_ID/RUN_ATTEMPT are
# pre-defaulted to the possibly-empty GITHUB_* values), so no separate emptiness guard.
run_id_line="${RUN_ID:-unestablished}"
run_attempt_line="${RUN_ATTEMPT:-unestablished}"
if [ -n "$DEVFLOW_APP_ID" ]; then app_id_line="present"; else app_id_line="absent"; fi
RUN_FACTS="Run facts (literals for this run — copy them into commands; never expand \$GITHUB_* or \$DEVFLOW_APP_ID in a command, the matcher refuses the expansion):
tier: cloud
run id: ${run_id_line}
run attempt: ${run_attempt_line}
DEVFLOW_APP_ID: ${app_id_line}"

PROMPT="${GROUNDING}

${RUN_FACTS}

/prflow:implement ${NUMBER}"
# Randomized heredoc delimiter, not `prompt=<value>`: the block is multi-line, and a
# `key=value` append would truncate it at the first newline. `date` is not a preflight
# prerequisite, but it decides nothing here — a missing one only shortens the delimiter,
# which stays unique through `$$`.
delim="PROMPT_EOF_$(date +%s%N)_$$"
# Capture the append's status; never `if ! { …; } >> "$f"`. Bash does not propagate a
# failed redirection ON A COMPOUND COMMAND through `!` (measured on bash 3.2 and 5.3:
# the group alone reports 1, the negated form reads 0), which left this arm unreachable —
# an unwritable GITHUB_OUTPUT exited 0 having published nothing.
append_rc=0
{ printf 'prompt<<%s\n' "$delim"; printf '%s\n' "$PROMPT"; printf '%s\n' "$delim"; } >> "$GITHUB_OUTPUT" || append_rc=$?
if [ "$append_rc" -ne 0 ]; then
  echo "::error::devflow: could not append the composed implement prompt to GITHUB_OUTPUT ('$GITHUB_OUTPUT') — the run would launch on the bare prompt with no engine-ground-truth block. Refusing to run." >&2
  exit 1
fi
exit 0
