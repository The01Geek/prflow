#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# provision-auto-mode.sh — make the `auto` permission mode SELECTABLE in the
# Shift+Tab cycle by provisioning env.CLAUDE_CODE_ENABLE_AUTO_MODE="1" into the
# USER-scope ~/.claude/settings.json. The deferred-from-#88 half of the settings
# provisioning split (PR #89 shipped the project-scope marketplace half; this is
# issue #105).
#
# Selectable, NEVER on. It writes only the env var — never permissions.defaultMode —
# so plan/model/admin gates still apply and `auto` is a mode the user must actively
# select; nothing here turns it on.
#
# Why USER scope (not project): CLAUDE_CODE_ENABLE_AUTO_MODE is a permission-gating
# env var, and Claude Code filters those out of PROJECT scope — it is honored only
# from user scope (~/.claude/settings.json) or managed settings. Writing it into a
# repo's .claude/settings.json is a silent no-op, which is exactly why the project
# provisioner (scripts/provision-local-settings.sh) deliberately omits it.
#
# CONSENT: ~/.claude/settings.json affects ALL of the user's projects, not just this
# repo, so this helper never edits it without explicit consent. The DEFAULT (no
# --apply) prints the exact one-line setting for the user to add themselves and
# writes NOTHING. --apply performs the write, and /prflow:init passes it only after
# the user explicitly opts in.
#
# Merge discipline mirrors provision-local-settings.sh: additive, non-clobbering
# (the user's value wins at every depth — a deliberately-disabled "0" is PRESERVED,
# never flipped to "1"), idempotent, atomic (mktemp + same-dir mv), fail-closed (a
# malformed / wrong-shape existing file is left byte-for-byte unchanged with a
# specific breadcrumb and a non-zero exit, never partially overwritten).
#
# Usage: provision-auto-mode.sh [--apply] [TARGET_SETTINGS_FILE]
#   --apply               perform the user-scope write (the caller's confirmed
#                         consent). Without it, print the copy-paste line, exit 0,
#                         touch nothing.
#   TARGET_SETTINGS_FILE  settings.json to provision (default:
#                         ~/.claude/settings.json). The override exists for tests;
#                         production always targets user scope.
#
# Exit codes:
#   0  printed the copy-paste line (no --apply); or provisioned / already-complete
#      (--apply).
#   2  a malformed invocation, independent of --apply: an unknown option, or more than
#      one positional target. OR --apply but a precondition / I-O failure: the existing
#      file is a directory (not a regular file), unreadable, could not be read into a
#      variable, contains a NUL byte, is not valid JSON, or is valid JSON of the wrong
#      shape (a non-object root, or `env` present as a non-object); or jq is missing; or
#      HOME is unset with no explicit target; or the settings dir / temp file / merged file
#      could not be created or written. In every exit-2 case the existing file is left
#      BYTE-FOR-BYTE UNCHANGED and a specific `devflow-automode:` breadcrumb names
#      the cause.
set -euo pipefail

# jq binary: resolved once via the resolver sourced from the sibling lib/ directory (issue #247);
# best-effort — a copied/vendored deployment without lib/ falls back to bare
# `jq` with a breadcrumb rather than aborting under set -e.
# shellcheck source=../lib/resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/resolve-jq.sh" \
  || { echo "devflow: resolve-jq.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }

log()  { printf 'devflow-automode: %s\n' "$1"; }
warn() { printf 'devflow-automode: %s\n' "$1" >&2; }

# ── Provider detection (issue #130). ────────────────────────────────────────
# CLAUDE_CODE_ENABLE_AUTO_MODE has NO effect on the Anthropic API — `auto` mode is already
# available there by default. The var only does anything on the third-party providers
# (Amazon Bedrock, Google Vertex AI, Microsoft Foundry). So provisioning it on
# Anthropic-direct is a pointless user-global settings write; the --apply gate below skips it.
# Detection reads only the documented Claude Code provider env vars (never .prflow/config.json
# — provider is an environment concern). A var counts as third-party only when set to a truthy
# value: Claude Code's docs enable these vars with `1`, and we additionally accept `true`
# (case-insensitive) defensively; empty, `0`, and any other value are treated as OFF, so a
# deliberately-disabled provider var never trips the gate.
is_truthy() {
  case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
    1|true) return 0 ;;
    *)      return 1 ;;
  esac
}
provider_is_third_party() {
  is_truthy "${CLAUDE_CODE_USE_BEDROCK:-}" && return 0
  is_truthy "${CLAUDE_CODE_USE_VERTEX:-}"  && return 0
  is_truthy "${CLAUDE_CODE_USE_FOUNDRY:-}" && return 0
  return 1
}

# ── Parse args: an optional --apply flag and at most one positional target. ──
# The positional is the settings file to provision (SETTINGS); production omits it
# and we default to user scope below.
APPLY=0
SETTINGS=""
TARGET_GIVEN=0   # tracks an EXPLICIT positional, so an empty-string arg ("") is distinguishable
                 # from "no target". Without this, `[ -z "$SETTINGS" ]` below cannot tell
                 # `--apply ""` (empty explicit arg) from `--apply` (no arg) and would silently
                 # fall through to the real $HOME/.claude/settings.json — a mis-target footgun.
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    -*)      warn "unknown option: $arg"; exit 2 ;;
    *)       if [ "$TARGET_GIVEN" -eq 1 ]; then
               warn "unexpected extra argument: $arg"; exit 2
             fi
             # An explicitly-passed empty target is meaningless — fail closed rather than
             # silently retargeting to the user-scope default.
             if [ -z "$arg" ]; then
               warn "empty target path argument; provisioned nothing (pass a real path or omit it for user scope)."
               exit 2
             fi
             TARGET_GIVEN=1
             SETTINGS="$arg" ;;
  esac
done

# Resolve the target. Default is user scope ($HOME/.claude/settings.json). In the
# no-consent path HOME-unset is non-fatal (we only need a label to display); in the
# --apply path it is a hard error (we cannot resolve where to write).
if [ -z "$SETTINGS" ]; then
  if [ -n "${HOME:-}" ]; then
    SETTINGS="$HOME/.claude/settings.json"
  elif [ "$APPLY" -eq 1 ]; then
    warn "cannot resolve ~/.claude/settings.json (HOME is unset); provisioned nothing."
    exit 2
  else
    # shellcheck disable=SC2088  # intentional display-only literal — no file is touched without --apply, so tilde expansion is not wanted
    SETTINGS="~/.claude/settings.json"   # display-only; no file is touched without --apply
  fi
fi

# The exact setting we provision — printed in the no-consent path so the user can add
# it themselves. We print the INNER key (not a full '"env": { … }' block) so pasting it
# into an EXISTING 'env' object can't create a duplicate 'env' key that silently drops
# the user's other env vars — the very clobber the --apply deep-merge avoids.
SETTING_LINE='"CLAUDE_CODE_ENABLE_AUTO_MODE": "1"'

# ── DEFAULT (no consent): surface the copy-paste line and write NOTHING. ──
if [ "$APPLY" -ne 1 ]; then
  log "auto mode is left unchanged. To make 'auto' SELECTABLE in the Shift+Tab"
  log "permission-mode cycle, add this line inside the 'env' object of your user"
  log "settings ($SETTINGS) yourself (create an 'env' object if you have none):"
  printf '    %s\n' "$SETTING_LINE"
  log "(selectable only — it is never turned on for you, and plan/model/admin gates still apply.)"
  log "If you have deliberately set it to \"0\" to disable auto mode, leave that as-is — don't add this line."
  log "Or, to have /prflow:init add it for you, re-run with explicit consent: provision-auto-mode.sh --apply"
  exit 0
fi

# ── --apply (consent confirmed by the caller): perform the user-scope merge. ──
# Provider gate (issue #130): this is the FIRST check on the --apply path — it precedes (and
# therefore never disturbs) the read/parse/shape-validation of the settings file below. On
# Anthropic-direct (no third-party provider env var truthy) the env var we would write is inert,
# so we provision NOTHING, leave any existing file byte-for-byte unchanged, and exit 0 (a
# success — the skip is "nothing to do", never the exit-2 error path) with a specific breadcrumb
# naming the provider as the reason. The no-`--apply` consent-print path above is left unchanged.
if ! provider_is_third_party; then
  log "auto mode is available by default on the Anthropic API; nothing to provision (CLAUDE_CODE_ENABLE_AUTO_MODE only affects the third-party providers Bedrock/Vertex/Foundry, none of which is active — set CLAUDE_CODE_USE_BEDROCK/VERTEX/FOUNDRY truthy to provision). Left $SETTINGS unchanged."
  exit 0
fi

SETTINGS_DIR="$(dirname "$SETTINGS")"

if ! "$DEVFLOW_JQ" --version >/dev/null 2>&1; then
  warn "no usable jq (missing or not executable); cannot provision $SETTINGS (install jq, or set DEVFLOW_JQ to a working jq/jq.exe, then re-run /prflow:init)."
  exit 2
fi

# The PRFlow default as a JSON literal. The merge below is `$defaults * $existing`,
# so the user's value wins at every depth and only keys they have not set are filled.
# permissions.defaultMode is intentionally absent — auto stays selectable, never on.
DEFAULTS='{
  "env": { "CLAUDE_CODE_ENABLE_AUTO_MODE": "1" }
}'

# A DIRECTORY (or a symlink to one) at the settings path is treated as ABSENT by the
# `[ -f "$SETTINGS" ]` test below, so the create path would run and the atomic mv would
# land the temp file INSIDE the directory — reporting success while writing nothing the
# runtime reads (issue #1082). Fail closed with a specific breadcrumb, above the `[ -f ]`.
# Scope is the directory case ONLY: a dangling symlink and a FIFO are deliberately not
# caught here — the mv REPLACES them with a real settings file, which is correct, and a
# broader "non-regular file" guard would newly break a legitimate symlink-into-dotfiles
# setup. Do NOT widen the predicate and lean on a failing read: `$(<dir)` is host-dependent
# (nonzero on bash 3.2, zero on bash 5.3) and a FIFO read blocks forever.
if [ -d "$SETTINGS" ]; then
  warn "existing $SETTINGS is a directory, not a file; left it unchanged and provisioned nothing (remove or move the directory, then re-run /prflow:init)."
  exit 2
fi

# Resolve the existing settings into a JSON value to merge against.
#   - absent file                  -> start from {} (create it)
#   - empty / whitespace-only file -> benign, treat as {} (fill the key)
#   - non-empty, parses as JSON    -> use it verbatim
#   - non-empty, does NOT parse    -> MALFORMED: bail without touching the file
EXISTING='{}'
if [ -f "$SETTINGS" ]; then
  # Distinguish an unreadable file (perms) from invalid JSON so the breadcrumb names
  # the real cause rather than misdirecting the user to "fix the JSON".
  if [ ! -r "$SETTINGS" ]; then
    warn "existing $SETTINGS is not readable (check permissions); left it unchanged and provisioned nothing."
    exit 2
  fi
  # Classify the file's content with BASH BUILTINS ONLY — never a non-preflight
  # PATH tool (was `[ -s ] && grep -q '[^[:space:]]'`, silently defeated when
  # grep does not resolve on PATH: it classified every file blank and let the
  # merge below clobber the user's whole USER-SCOPE settings). CLAUDE.md
  # guard-class 2 — a value that decides a SELECTION or an EMITTED result must
  # not be derived through a non-preflight PATH tool; mirrors
  # scripts/resolve-command-trigger.sh.
  #
  # One builtin read does the whole classification. `read -r -d ''` reads up to
  # the first NUL byte:
  #   - returns 0            → a NUL was found: not JSON text, fail closed
  #     (exit 2). Using a builtin (not a slurp) matters because command
  #     substitution DISCARDS NUL bytes, so a `$(<file)` remedy would read a
  #     NUL-bearing file as blank and clobber it.
  #   - returns non-zero at EOF → a clean read; `settings_content` holds the
  #     whole file. `if`-capturing it (the group status + the `[ ! -r ]` re-test)
  #     keeps a file that became unreadable BETWEEN the `[ -r ]` pre-check and
  #     this read (deleted / replaced / chmod'd in the race) inside the
  #     exit-0-or-2 contract instead of aborting under set -e. (`[ ! -r ]` only
  #     disambiguates an open failure from EOF; a mid-read I/O error on a
  #     still-readable file is not deterministically reachable and is out of
  #     scope, per issue #1081's read-failure criterion.)
  # The group is wrapped `{ …; } 2>/dev/null` so a redirection-open error is
  # suppressed AFTER the group's stderr is redirected (an inline
  # `< "$f" 2>/dev/null` leaks the open error, which fires before 2>/dev/null
  # takes effect) — keeping the breadcrumb the only thing on the error channel.
  # Then a `case` classifies blankness: non-blank parses as JSON; blank /
  # whitespace-only / zero-byte leaves EXISTING at {} and fills the key.
  #
  # HOST-BASH-VARIANCE NOTE (the assumption issue #1081 flagged "confirm before
  # implementing" — confirmed FALSE on this host, bash 5.2.21): the prescribed
  # `settings_content="$(<"$SETTINGS" 2>/dev/null)"` is NOT usable here — a
  # `2>/dev/null` INSIDE a `$(<file)` substitution defeats bash's fast-path read
  # and yields the empty string, which misclassifies every real settings file as
  # blank and clobbers it. The `read` builtin sidesteps both that and the
  # NUL-stripping above.
  settings_content=""
  if { IFS= read -r -d '' settings_content < "$SETTINGS"; } 2>/dev/null; then
    warn "existing $SETTINGS contains a NUL byte (not valid JSON text); left it unchanged and provisioned nothing (fix or remove it, then re-run /prflow:init)."
    exit 2
  elif [ ! -r "$SETTINGS" ]; then
    warn "existing $SETTINGS could not be read into a variable; left it unchanged and provisioned nothing."
    exit 2
  fi
  case "$settings_content" in
    *[![:space:]]*)
      if ! EXISTING="$("$DEVFLOW_JQ" . "$SETTINGS" 2>/dev/null)"; then
        warn "existing $SETTINGS is not valid JSON; left it unchanged and provisioned nothing (fix or remove it, then re-run /prflow:init)."
        exit 2
      fi
      ;;
  esac
fi

# Type-guard the shapes the deep-merge relies on. `jq .` above only proves the file
# PARSES; valid-but-corrupt shapes still slip through:
#   - a non-object ROOT (`[...]` or a bare scalar) — `$defaults * $existing` is a jq
#     error (object times array/scalar) that, under `set -euo pipefail`, would abort
#     with a raw jq message and escape the documented 0/2 contract with no breadcrumb;
#   - a non-object at an object-valued path the merge recurses THROUGH — here `env`,
#     where the user holds a non-object value. jq's `*` does not error there; it
#     silently keeps the user's value and drops PRFlow's whole subtree below it (the
#     auto-mode env var never lands), yet still exits 0 with a success breadcrumb.
# Derive the object-valued paths FROM $defaults (just `env` today, but this generalizes
# for free if defaults ever nests deeper — the same sweep provision-local-settings.sh
# uses) and flag any that $root holds as a non-object. A wrong-typed value at a genuine
# LEAF (CLAUDE_CODE_ENABLE_AUTO_MODE itself) is NOT an object-valued path, so it is a
# legitimate user-wins clobber and is never flagged. All flagged shapes are corrupt
# settings, treated exactly like the malformed-JSON case: a specific breadcrumb, exit 2,
# file left byte-for-byte unchanged.
# Capture with `if !` so a failure of the guard's OWN jq fails CLOSED — a bare
# assignment would mask the command-substitution exit status from `set -e` and sail
# past the `[ -n ]` check below as if the shape were validated.
if ! BAD_SHAPE="$(printf '%s' "$EXISTING" | "$DEVFLOW_JQ" -r --argjson defaults "$DEFAULTS" '
  . as $root
  | if ($root | type) != "object" then
      "the file is valid JSON but not a JSON object (\($root | type))"
    else
      ( [ ($defaults | paths) as $p
          | select(($defaults | getpath($p) | type) == "object") | $p ] as $objpaths
        | [ $objpaths[] | . as $p
            # Flag a path the user has PRESENT as a non-object (any type, including
            # null — jq merge treats a right-hand null as a winning value that
            # replaces the whole defaults subtree). Test presence via the parent
            # has() check, not getpath alone: getpath returns null for BOTH an absent
            # path and a present-null one, and an absent path is fine (the merge fills
            # it). A non-object parent is skipped here and flagged by its own
            # (shallower) object-path instead, so each corruption is named once.
            | ($root | try getpath($p[0:-1]) catch null) as $parent
            | select(($parent | type) == "object" and ($parent | has($p[-1]))
                     and (($parent[$p[-1]]) | type) != "object")
            | "the \($p | join(".")) path is present but not a JSON object (\(($parent[$p[-1]]) | type))" ]
        | join("; ") )
    end')"; then
  warn "existing $SETTINGS could not be validated for provisioning (the settings-shape check failed); left it unchanged and provisioned nothing."
  exit 2
fi
if [ -n "$BAD_SHAPE" ]; then
  warn "existing $SETTINGS is malformed for provisioning ($BAD_SHAPE); left it unchanged and provisioned nothing (fix or remove it, then re-run /prflow:init)."
  exit 2
fi

# The merge cannot fail post-guard ($existing is a validated object whose `env` is
# object-or-absent, $defaults is a fixed valid object), but guard it anyway so an
# unanticipated jq failure fails CLOSED with a breadcrumb rather than a raw error.
if ! MERGED="$("$DEVFLOW_JQ" -n --argjson defaults "$DEFAULTS" --argjson existing "$EXISTING" '$defaults * $existing')"; then
  warn "could not compute the provisioned settings for $SETTINGS (merge failed); left it unchanged."
  exit 2
fi

# Only write on a real change (idempotent — no mtime churn on a re-run, and the
# no-clobber "0"/disabled case lands here: the merge keeps the user's existing value, so
# MERGED == EXISTING and we report "nothing changed" without a write). Compare canonical
# (sorted) forms so formatting differences never read as a change.
if [ "$(printf '%s' "$EXISTING" | "$DEVFLOW_JQ" -S .)" = "$(printf '%s' "$MERGED" | "$DEVFLOW_JQ" -S .)" ]; then
  # Distinguish the two no-change cases so the breadcrumb never implies "selectable"
  # when the user's preserved value actually DISABLES it: the STRING "1" → already
  # selectable; anything else (a deliberate "0", a non-"1" string, OR a non-string leaf)
  # → preserved but NOT selectable. (We are in this branch only because
  # env.CLAUDE_CODE_ENABLE_AUTO_MODE is already present — an absent key would have made
  # MERGED differ — so the read is always populated; the `|| PRESERVED_RAW=""` fallback
  # keeps a defensive jq hiccup from aborting under `set -e` rather than masking a real
  # failure, since this is a cosmetic-breadcrumb read on already-validated JSON.)
  #
  # Read the RAW JSON form (`jq -c`), NOT `jq -r`: Claude Code honors only the STRING
  # "1" from settings; a numeric `1` (or `true`, or an object) is a legal-JSON but
  # non-honored leaf the merge preserves as a user-wins clobber. `jq -r` would stringify
  # a numeric `1` to the same `1` as the string and FALSELY report "already selectable"
  # over a value Claude Code ignores — a silent misreport. Comparing the canonical raw
  # form (`"1"` with quotes) means only the real string "1" reads as selectable.
  # No `// empty` here: jq's `//` treats a JSON `false` AND `null` as empty (not just an
  # absent key), which would blank the preserved value in the breadcrumb for those two legal
  # leaf shapes ("…AUTO_MODE= (your value is preserved)…"). This branch is reachable only when
  # env.CLAUDE_CODE_ENABLE_AUTO_MODE is PRESENT (an absent key makes MERGED differ from
  # EXISTING), so the raw read is always populated and needs no absent-key fallback — the read
  # yields the literal `false`/`null`/`1`/`"0"`, so every preserved value renders honestly on
  # this (the only reachable) path. The `|| PRESERVED_RAW=""` is a last-resort defensive set-e
  # guard against a jq hiccup; it cannot fire on the already-validated, key-present JSON here,
  # and if it somehow did the breadcrumb would render a blank value — strictly worse than the
  # literal, but unreachable, so it is the safe fail-soft for a cosmetic read.
  PRESERVED_RAW="$(printf '%s' "$EXISTING" | "$DEVFLOW_JQ" -c '.env.CLAUDE_CODE_ENABLE_AUTO_MODE')" || PRESERVED_RAW=""
  if [ "$PRESERVED_RAW" = '"1"' ]; then
    log "$SETTINGS already sets CLAUDE_CODE_ENABLE_AUTO_MODE=\"1\" — 'auto' is already selectable; nothing changed."
  else
    log "$SETTINGS already sets CLAUDE_CODE_ENABLE_AUTO_MODE=$PRESERVED_RAW (your value is preserved) — 'auto' is NOT selectable while this is not the string \"1\" (settings env values must be JSON strings); nothing changed."
  fi
  exit 0
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
# Guard the write so a failure (read-only FS, ENOSPC, an immutable/owned file) leaves a
# devflow-automode: breadcrumb + exit 2 rather than a raw shell/mv error. $SETTINGS is
# untouched until the mv (an atomic same-dir rename), so a failed write leaves the
# original intact.
if ! { printf '%s\n' "$MERGED" > "$TMP" && mv "$TMP" "$SETTINGS"; }; then
  warn "could not write $SETTINGS (check permissions and free space); left it unchanged."
  exit 2
fi
trap - EXIT

log "provisioned $SETTINGS: 'auto' is now SELECTABLE in the Shift+Tab permission-mode cycle (CLAUDE_CODE_ENABLE_AUTO_MODE=\"1\"). It is not turned on — select it yourself, and plan/model/admin gates still apply. Review the change before committing if this file is tracked."
exit 0
