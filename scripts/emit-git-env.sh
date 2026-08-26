#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
#
# Resolve the two default-off git-env pin flags and emit the `$GITHUB_ENV`
# assignment lines for the ones that are enabled (issue #645).
#
# Background. PR #643 (issue #602) set step-scoped GIT_DIR and GIT_WORK_TREE
# unconditionally on the `Run Claude Code` step of the three shipped cloud
# workflows, so claude-code-action's `configureGitAuth` startup would resolve the
# repository on a self-hosted Windows runner. GIT_WORK_TREE also reaches the
# Claude Code CLI subprocess that installs plugins, where it makes `git clone`
# refuse an existing working tree — so EVERY cloud run died at plugin install
# with `fatal: working tree '<path>' already exists.`, before the agent did any
# work, producing no verdict at all. The two variables serve different
# populations and carry different costs, so they are decoupled here into two
# INDEPENDENT opt-in keys, both defaulting to FALSE. With both off this helper
# emits nothing and the tiers behave exactly as they did before #643 — the
# default configuration is the one that works everywhere.
#
# Usage:
#   emit-git-env.sh --workspace PATH [--config-file PATH] [--tier TIER]
#
#   --workspace PATH    the repository workspace (GitHub's ${{ github.workspace }}).
#                       Required when either key is enabled; GIT_DIR is emitted as
#                       "<workspace>/.git" and GIT_WORK_TREE as "<workspace>".
#   --config-file PATH  config JSON to read. Defaults to the repo-root
#                       .prflow/config.json via the shared resolver (issue #295).
#                       Callers on the cloud tiers pass the TRUSTED tree's config
#                       (the trigger-time `config` job's checkout, or the review
#                       tier's base-ref-materialized copy) — never the PR head.
#   --tier TIER         review | command | implement. Default: review.
#                       On `implement` the GIT_DIR key is IGNORED (see below).
#
# Config keys (both under `setup`, both default false):
#   setup.git_dir_pin         → GIT_DIR=<workspace>/.git
#   setup.git_work_tree_pin   → GIT_WORK_TREE=<workspace>
#
# A key is ENABLED only when its JSON leaf is the boolean `true` or the string
# "true" — the two shapes the platform gate accepts, since the existing workflow
# extractions stringify values and a string "true" reads as enabled. Every other
# shape resolves to disabled: absent, JSON null, an explicit `false`, a number, an
# array, an object, a non-object `setup` container, an unreadable or malformed
# config file. That is deliberate and is the whole safety property: a
# hand-corrupted config yields the WORKING DEFAULT (neither variable set) rather
# than a partially-set environment that reproduces the outage.
#
# Why this reads the JSON directly instead of delegating to scripts/config-get.sh.
# The shared resolver reproduces Node's `String()`/`Array.join()` coercion
# byte-for-byte, so a single-element ARRAY `[true]` joins to the string "true" —
# indistinguishable, at the resolver's output, from the boolean `true` it must NOT
# be treated as. A wrapper cannot recover the leaf's type from that output, and
# accepting `[true]` would enable a pin from a shape the schema rejects. So the
# leaf's TYPE is what decides here, read with python3 — the same stdlib `json`
# module and the same hard preflight prerequisite config-get.sh itself uses, not a
# new dependency or a hand-rolled parser. Everything else about the read matches
# the resolver's contract: the dot-path walk aborts on any non-object container,
# and every failure resolves to disabled.
#
# The implement-tier GIT_DIR exclusion. The implement tier stages and pushes
# commits, and ambient GIT_DIR makes a `git add` issued from a NON-ROOT working
# directory record deletions across the rest of the tree (measured: with GIT_DIR
# alone and cwd inside a subdirectory, `git rev-parse --show-toplevel` returns THE
# SUBDIRECTORY and `git status --porcelain` reports every tracked file outside it
# as deleted). So the key is honored on the review and command tiers only; on
# `implement` this helper emits no GIT_DIR assignment and prints a breadcrumb
# naming that it was ignored.
#
# The GIT_DIR silent-miss warning. Ambient GIT_DIR also breaks the #295 repo-root
# config contract: config-get.sh, workpad.py, load-prompt-extension.sh (on its
# FALLBACK branch only — issue #874 made it anchor on DEVFLOW_PROMPT_EXTENSION_ROOT
# whenever that variable is set and non-empty, which is how the cloud review tier
# reaches its trusted base-ref closure),
# match-deferrals.py and match-lint-adjudications.py all anchor `.prflow/` via
# `git rev-parse --show-toplevel`, so under ambient GIT_DIR from a non-root
# working directory they resolve a `.prflow/` that does not exist. The documented
# failure is a SILENT MISS, not an error — the reader falls back to its default and
# nothing says so. This helper therefore emits a loud stderr warning on every run
# that emits a GIT_DIR assignment, so the tiers where the key stays enabled carry
# one visible signal for a failure mode that is otherwise undetectable.
#
# Contract: ALWAYS exits 0, with stderr breadcrumbs — the repo's best-effort
# helper convention (ensure-label.sh / apply-labels.sh). The consuming workflow
# step appends this stdout to "$GITHUB_ENV", so a non-zero exit would fail the job
# over a configuration read; failing OPEN to the working default is correct here,
# because the default IS the safe state. The decisive values are derived with bash
# builtins (case/parameter expansion), never a non-preflight PATH tool such as
# tr/sed/cut, so a missing tool cannot fail this open into a PARTIALLY-set
# environment (CLAUDE.md's "a value that decides a SELECTION or an EMITTED result").
#
# An ABSENT helper is likewise safe: the workflow step guards on the file existing
# and emits nothing when it is missing. The workflow reaches consumers through
# install.sh's file-copy while this helper reaches them through the prflow_version
# vendor fetch, so a consumer can carry the step before it carries the helper —
# that skew must not reproduce the outage this helper ends.

set -uo pipefail

_ws=''
_cfg=''
_tier='review'

while [ $# -gt 0 ]; do
    case "$1" in
        --workspace)
            _ws="${2:-}"
            shift 2 || shift
            ;;
        --config-file)
            _cfg="${2:-}"
            shift 2 || shift
            ;;
        --tier)
            _tier="${2:-}"
            shift 2 || shift
            ;;
        *)
            echo "emit-git-env.sh: ignoring unrecognized argument '$1'" >&2
            shift
            ;;
    esac
done

case "$_tier" in
    review|command|implement) ;;
    *)
        echo "emit-git-env.sh: unrecognized --tier '$_tier'; treating it as 'implement' (the most restrictive tier — GIT_DIR suppressed)" >&2
        _tier='implement'
        ;;
esac

# Resolve the config path the same way PRFlow's shared resolver does when no
# explicit file is given: anchored to the git repo ROOT (issue #295), falling back
# to the working directory. A non-empty explicit --config-file is honored verbatim.
if [ -z "$_cfg" ]; then
    _root="$(git rev-parse --show-toplevel 2>/dev/null)" || _root=''
    [ -n "$_root" ] || _root="$(pwd)"
    _cfg="${_root}/.prflow/config.json"
fi

# Print `true` iff the leaf at the given dot-path is the JSON boolean true or the
# JSON string "true"; print `false` for every other shape, including a malformed
# or unreadable file, a non-object container anywhere along the path, and a
# single-element array whose element is true. Any failure — python3 absent,
# interpreter error — collapses to `false`, the working default.
_read_key() {
    _rk_out=''
    if command -v python3 >/dev/null 2>&1; then
        _rk_out="$(DEVFLOW_GITENV_KEY="${1#.}" DEVFLOW_GITENV_CFG="$_cfg" python3 -c '
import json, os, sys
try:
    with open(os.environ["DEVFLOW_GITENV_CFG"], encoding="utf-8") as f:
        data = json.load(f)
except Exception:
    sys.stdout.write("false")
    sys.exit(0)
cur = data
for part in os.environ["DEVFLOW_GITENV_KEY"].split("."):
    if not isinstance(cur, dict) or part not in cur:
        sys.stdout.write("false")
        sys.exit(0)
    cur = cur[part]
# isinstance(True, int) is True in Python, so test bool BEFORE any numeric
# interpretation; a bare 1 must never read as enabled.
if cur is True or (isinstance(cur, str) and cur == "true"):
    sys.stdout.write("true")
else:
    sys.stdout.write("false")
' 2>/dev/null)" || _rk_out='false'
    else
        echo "emit-git-env.sh: python3 not found; treating every git-env pin key as disabled (the working default)" >&2
        _rk_out='false'
    fi
    printf '%s' "$_rk_out"
}

# A `case` comparison, not an external tool: this decides an EMITTED result, and a
# missing non-preflight PATH tool must never be able to change it.
_enabled() {
    case "$(_read_key "$1")" in
        true) return 0 ;;
        *) return 1 ;;
    esac
}

_git_dir_on=0
_work_tree_on=0
_enabled '.setup.git_dir_pin' && _git_dir_on=1
_enabled '.setup.git_work_tree_pin' && _work_tree_on=1

# The implement tier ignores GIT_DIR (see the header). Record that it did, so the
# suppression is an observable event and not a silent divergence from the config.
if [ "$_git_dir_on" -eq 1 ] && [ "$_tier" = 'implement' ]; then
    echo "emit-git-env.sh: setup.git_dir_pin is enabled but the implement tier IGNORES it — that tier stages and pushes commits, and ambient GIT_DIR makes a stage issued from a non-root working directory record deletions across the rest of the tree (issue #645). No GIT_DIR assignment emitted." >&2
    _git_dir_on=0
fi

# An enabled key with no workspace cannot produce a usable assignment, and an
# EMPTY value is not an absent one — measured, `GIT_DIR=` yields
# `fatal: not a git repository: ''` and `GIT_WORK_TREE=` yields
# `fatal: The empty string is not a valid path`. So emit a line or emit nothing;
# never emit an empty assignment.
if [ -z "$_ws" ] && { [ "$_git_dir_on" -eq 1 ] || [ "$_work_tree_on" -eq 1 ]; }; then
    echo "emit-git-env.sh: a git-env pin key is enabled but --workspace is empty; emitting nothing (an empty GIT_DIR/GIT_WORK_TREE value is fatal to git, not an 'unset')" >&2
    _git_dir_on=0
    _work_tree_on=0
fi

if [ "$_git_dir_on" -eq 1 ]; then
    echo "emit-git-env.sh: WARNING — setup.git_dir_pin is enabled, so ambient GIT_DIR is in force for the Run Claude Code step and every step after it. Any PRFlow helper that runs from a NON-ROOT working directory will resolve a .prflow/ that does not exist (the issue #295 repo-root readers: config-get.sh, workpad.py, load-prompt-extension.sh — on its fallback branch only, since issue #874 made it anchor on DEVFLOW_PROMPT_EXTENSION_ROOT instead whenever that variable is set and non-empty — match-deferrals.py, match-lint-adjudications.py). That failure is a SILENT MISS, not an error, so this run is not a config-faithful run." >&2
    printf 'GIT_DIR=%s/.git\n' "$_ws"
fi

if [ "$_work_tree_on" -eq 1 ]; then
    printf 'GIT_WORK_TREE=%s\n' "$_ws"
fi

exit 0
