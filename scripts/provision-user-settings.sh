#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# provision-user-settings.sh — provision the developer's USER-scope
# ~/.claude/settings.json with PRFlow's opt-in for Claude Code's task-tracking
# tools.
#
# Invoked ONLY from the /prflow:init skill flow, as a sibling of the
# project-scope provision-local-settings.sh — never from scaffold-config.sh or
# install.sh. Since Claude Code v2.1.233 the task tools (TaskCreate/TaskGet/
# TaskUpdate/TaskList/TodoWrite) are off by default on newer models unless the
# user exports CLAUDE_CODE_ENABLE_TODO_TOOLS=1 before launch, so PRFlow's
# task-tracking skills silently fall back to a non-persisted checklist. This
# helper turns the opt-in on for the developer's FUTURE sessions by deep-merging
#   {"env": {"CLAUDE_CODE_ENABLE_TODO_TOOLS": "1"}}
# into ~/.claude/settings.json, the one scope Claude Code honors it from. It is
# the sanctioned init-only, human-invoked exception to CLAUDE.md's
# "widening the allowlist is a human action" rule — a settings write can never
# affect the session that performs it (tool registration already happened at
# that session's start), which is why the success breadcrumb names the
# new-session requirement.
#
# The write targets USER scope, deliberately unlike provision-local-settings.sh's
# project-scope write: the two must stay separate so the project .claude/settings.json
# still gains no env block (the #88 project-scope assertions), and so this env var
# reaches the scope Claude Code actually reads it from.
#
# Mirrors provision-local-settings.sh's contract: deep-merges `$defaults * $existing`
# (the user's value wins at every depth, so only the absent key is filled), stays
# idempotent (no write and no mtime churn once the key is present), prints a stable
# `devflow-settings:` breadcrumb per outcome, and is best-effort so a failure never
# aborts /prflow:init.
#
# Usage: provision-user-settings.sh [TARGET_HOME]
#   TARGET_HOME  home directory to provision (default: $HOME) — the arg exists so the
#                suite can drive the helper against a temp HOME.
#
# Exit codes:
#   0  opt-in written, already present (a quiet "nothing changed"), or already set
#      in the environment.
#   2  any precondition or I/O failure — HOME could not be resolved, the existing
#      ~/.claude/settings.json is a directory, unreadable, could not be read into a
#      variable, contains a NUL byte, is not valid JSON, or is valid JSON of the
#      wrong shape (a non-object root, or a non-object `env`); or jq is missing; or
#      the settings dir / temp file could not be created or the merged file could not
#      be written. In every exit-2 case the existing file is left BYTE-FOR-BYTE
#      UNCHANGED and a specific `devflow-settings:` breadcrumb names the cause.
set -euo pipefail

# jq binary: resolved once via the resolver sourced from the sibling lib/ directory
# (issue #247); best-effort — a copied/vendored deployment without lib/ falls back to
# bare `jq` with a breadcrumb rather than aborting under set -e.
# shellcheck source=../lib/resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/resolve-jq.sh" \
  || { echo "devflow: resolve-jq.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }

log()  { printf 'devflow-settings: %s\n' "$1"; }
warn() { printf 'devflow-settings: %s\n' "$1" >&2; }

# The opt-in this helper writes. A single literal so the env-presence check, the
# defaults, the presence check, and the breadcrumbs cannot drift apart.
TODO_VAR="CLAUDE_CODE_ENABLE_TODO_TOOLS"

# Resolve HOME portably — the arg wins so the suite can point at a temp HOME; else
# $HOME. /prflow:init can run on custom runners including Windows Git Bash, where
# $HOME is set, so no drive-letter parsing is needed. Fail closed on an empty value
# rather than provisioning "/.claude/settings.json".
HOME_DIR="${1:-${HOME:-}}"
if [ -z "$HOME_DIR" ]; then
  warn "cannot resolve a home directory (neither an argument nor \$HOME is set); provisioned no task-tools opt-in."
  exit 2
fi
SETTINGS_DIR="$HOME_DIR/.claude"
SETTINGS="$SETTINGS_DIR/settings.json"

if ! "$DEVFLOW_JQ" --version >/dev/null 2>&1; then
  warn "no usable jq (missing or not executable); cannot provision $SETTINGS (install jq, or set DEVFLOW_JQ to a working jq/jq.exe, then re-run /prflow:init)."
  exit 2
fi

# The environment already sets it → this session already has the tools (or the user
# deliberately controls it), so leave the file alone. Indirect `${!TODO_VAR+set}` keeps
# the checked name sourced from TODO_VAR (never a second hardcoded copy), and `+set` tests
# presence regardless of value, so a set-but-empty value is still honored as "set".
if [ -n "${!TODO_VAR+set}" ]; then
  log "$TODO_VAR is already set in the environment, so this session and any that inherit its environment already opt in; wrote no persisted opt-in and left $SETTINGS unchanged."
  exit 0
fi

# A DIRECTORY (or symlink to one) at the settings path is treated as ABSENT by the
# `[ -f ]` test below, so the create path would land the temp file INSIDE it and
# report success (issue #1082). Fail closed above the `[ -f ]`.
if [ -d "$SETTINGS" ]; then
  warn "existing $SETTINGS is a directory, not a file; left it unchanged and provisioned no task-tools opt-in (remove or move the directory, then re-run /prflow:init)."
  exit 2
fi

# Resolve the existing settings into a JSON value to merge against.
#   - absent file                  -> start from {} (create it)
#   - empty / whitespace-only file -> benign, treat as {} (fill the key)
#   - non-empty, parses as JSON    -> use it verbatim
#   - non-empty, does NOT parse    -> MALFORMED: bail without touching the file
EXISTING='{}'
if [ -f "$SETTINGS" ]; then
  if [ ! -r "$SETTINGS" ]; then
    warn "existing $SETTINGS is not readable (check permissions); left it unchanged and provisioned no task-tools opt-in."
    exit 2
  fi
  # Classify content with BASH BUILTINS ONLY (mirrors provision-local-settings.sh):
  # `read -r -d ''` reads up to the first NUL — returns 0 when a NUL was found (not
  # JSON text, fail closed), non-zero at a clean EOF. Command substitution DISCARDS
  # NUL bytes, so a `$(<file)` remedy would misread a NUL-bearing file as blank.
  settings_content=""
  if { IFS= read -r -d '' settings_content < "$SETTINGS"; } 2>/dev/null; then
    warn "existing $SETTINGS contains a NUL byte (not valid JSON text); left it unchanged and provisioned no task-tools opt-in (fix or remove it, then re-run /prflow:init)."
    exit 2
  elif [ ! -r "$SETTINGS" ]; then
    warn "existing $SETTINGS could not be read into a variable; left it unchanged and provisioned no task-tools opt-in."
    exit 2
  fi
  case "$settings_content" in
    *[![:space:]]*)
      if ! EXISTING="$("$DEVFLOW_JQ" . "$SETTINGS" 2>/dev/null)"; then
        warn "existing $SETTINGS is not valid JSON; left it unchanged and provisioned no task-tools opt-in (fix or remove it, then re-run /prflow:init)."
        exit 2
      fi
      ;;
  esac
fi

# The defaults this helper merges in. The merge below is `$defaults * $existing`, so
# the user's value wins at every depth and only the absent key is filled.
DEFAULTS="$("$DEVFLOW_JQ" -n --arg k "$TODO_VAR" '{ env: { ($k): "1" } }')"

# Type-guard every object-valued path the merge recurses THROUGH (the root and `env`),
# derived FROM $defaults so a wrong-typed value there is caught rather than crashing the
# merge (object * array/scalar) or silently dropping the opt-in. A genuine LEAF is a
# user-wins clobber and is not flagged. Capture with `if !` so the guard's OWN jq fails
# CLOSED. Mirrors provision-local-settings.sh's sweep.
if ! BAD_SHAPE="$(printf '%s' "$EXISTING" | "$DEVFLOW_JQ" -r --argjson defaults "$DEFAULTS" '
  . as $root
  | if ($root | type) != "object" then
      "the file is valid JSON but not a JSON object (\($root | type))"
    else
      ( [ ($defaults | paths) as $p
          | select(($defaults | getpath($p) | type) == "object") | $p ] as $objpaths
        | [ $objpaths[] | . as $p
            | ($root | try getpath($p[0:-1]) catch null) as $parent
            | select(($parent | type) == "object" and ($parent | has($p[-1]))
                     and (($parent[$p[-1]]) | type) != "object")
            | "the \($p | join(".")) path is present but not a JSON object (\(($parent[$p[-1]]) | type))" ]
        | join("; ") )
    end')"; then
  warn "existing $SETTINGS could not be validated for provisioning (the settings-shape check failed); left it unchanged and provisioned no task-tools opt-in."
  exit 2
fi
if [ -n "$BAD_SHAPE" ]; then
  warn "existing $SETTINGS is malformed for provisioning ($BAD_SHAPE); left it unchanged and provisioned no task-tools opt-in (fix or remove it, then re-run /prflow:init)."
  exit 2
fi

# Already present in the file (any value, present-null included) → idempotent no-op with
# its own breadcrumb, file left byte-identical. `has` on the guaranteed-object-or-absent
# `env` distinguishes an absent key (fill it) from a present one (leave it).
if printf '%s' "$EXISTING" | "$DEVFLOW_JQ" -e --arg k "$TODO_VAR" '(.env // {}) | has($k)' >/dev/null 2>&1; then
  log "$SETTINGS already sets env.$TODO_VAR (the task-tools opt-in); left it unchanged."
  exit 0
fi

if ! MERGED="$("$DEVFLOW_JQ" -n --argjson defaults "$DEFAULTS" --argjson existing "$EXISTING" '$defaults * $existing')"; then
  warn "could not compute the provisioned settings for $SETTINGS (merge failed); left it unchanged."
  exit 2
fi

mkdir -p "$SETTINGS_DIR" || {
  warn "could not create $SETTINGS_DIR; left $SETTINGS unchanged."
  exit 2
}
TMP="$(mktemp "$SETTINGS_DIR/.settings.json.XXXXXX")" || {
  warn "could not create a temp file in $SETTINGS_DIR; left $SETTINGS unchanged."
  exit 2
}
trap 'rm -f "$TMP"' EXIT
# $SETTINGS is untouched until the mv (an atomic same-dir rename), so a failed write
# leaves the original intact.
if ! { printf '%s\n' "$MERGED" > "$TMP" && mv "$TMP" "$SETTINGS"; }; then
  warn "could not write $SETTINGS (check permissions and free space); left it unchanged."
  exit 2
fi
trap - EXIT

log "enabled the Claude Code task tools by adding env.$TODO_VAR=1 to $SETTINGS. This takes effect only in a newly launched Claude Code session — start one by running 'claude', or launch one-shot with '$TODO_VAR=1 claude'."
