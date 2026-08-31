#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# provision-local-settings.sh — provision a consumer repo's PROJECT
# .claude/settings.json with PRFlow's local/interactive-tier conveniences.
#
# Invoked ONLY from the /prflow:init skill flow — never from scaffold-config.sh
# or install.sh. The cloud (CI) tier runs under claude-code-action with its own
# deterministic allowlist profile and consumes neither a local marketplace
# install nor a local permission mode, so a settings file there is pointless;
# keeping this out of the shared scaffolder is what guarantees a cloud-only
# install.sh run writes no .claude/settings.json (issue #88, AC 7).
#
# It deep-merges the PRFlow marketplace registration into the project settings,
# additively and WITHOUT clobbering any value the user already set:
#   - extraKnownMarketplaces["devflow-marketplace"]  (a github source for
#       The01Geek/prflow + autoUpdate:true) and
#       enabledPlugins["prflow@devflow-marketplace"]=true, so Claude Code keeps
#       the PRFlow plugin updated.
#
# NOTE — this provisioner writes no permission-gating env var. Claude Code honors
# those only from user scope (~/.claude/settings.json) or managed settings, so
# writing one into the project .claude/settings.json is a silent no-op.
#
# Mirrors scaffold-config.sh's contract: deterministic, idempotent, never
# clobbers user values, prints a stable `devflow-settings:` breadcrumb per
# outcome, and is safe to re-run. The merge is `$defaults * $existing` (jq deep
# merge with the user's value winning at every depth), so a key the user already
# set is preserved and only the absent keys are filled.
#
# Usage: provision-local-settings.sh [TARGET_REPO_ROOT]
#   TARGET_REPO_ROOT  repo root to provision (default: git toplevel, else cwd)
#
# Exit codes:
#   0  settings provisioned, or already complete (a quiet "nothing changed").
#   2  any precondition or I/O failure — the existing .claude/settings.json is
#      a directory (not a regular file), unreadable, could not be read into a
#      variable, contains a NUL byte, is not valid JSON, or is valid JSON of the
#      wrong shape (a non-object root, or a PRFlow object-valued path present as
#      a non-object); or jq is missing; or the settings dir / temp file could not
#      be created or the merged file could not be written. In every exit-2 case the
#      existing file is left BYTE-FOR-BYTE UNCHANGED and a specific `devflow-settings:`
#      breadcrumb names the cause.
set -euo pipefail

# jq binary: resolved once via the resolver sourced from the sibling lib/ directory (issue #247);
# best-effort — a copied/vendored deployment without lib/ falls back to bare
# `jq` with a breadcrumb rather than aborting under set -e.
# shellcheck source=../lib/resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/resolve-jq.sh" \
  || { echo "devflow: resolve-jq.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }

log()  { printf 'devflow-settings: %s\n' "$1"; }
warn() { printf 'devflow-settings: %s\n' "$1" >&2; }

TARGET_ROOT="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
SETTINGS_DIR="$TARGET_ROOT/.claude"
SETTINGS="$SETTINGS_DIR/settings.json"

if ! "$DEVFLOW_JQ" --version >/dev/null 2>&1; then
  warn "no usable jq (missing or not executable); cannot provision $SETTINGS (install jq, or set DEVFLOW_JQ to a working jq/jq.exe, then re-run /prflow:init)."
  exit 2
fi

# The identifiers this script writes are DERIVED from the single identity source
# (lib/plugin-identity.json + .claude-plugin/plugin.json) through lib/plugin_identity.py
# — the one reader — never spelled as literals here, so a change to the declared
# identifier set reaches this provisioner without it being re-edited. python3 is a
# hard PRFlow prerequisite (lib/preflight.sh), so this is a preflight-guaranteed
# derivation, not a non-preflight PATH tool deciding what gets written.
# FAILS CLOSED: an unestablished identifier set writes nothing (exit 2) rather than
# guessing a key name and provisioning a marketplace registration that never resolves.
DEVFLOW_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib"
if ! IDENTITY_JSON="$(python3 "$DEVFLOW_LIB_DIR/plugin_identity.py" --json 2>/dev/null)" \
   || [ -z "$IDENTITY_JSON" ]; then
  warn "the accepted plugin/marketplace identifier set could not be established from lib/plugin-identity.json + .claude-plugin/plugin.json (run 'python3 $DEVFLOW_LIB_DIR/plugin_identity.py --json' to see why); left $SETTINGS unchanged and provisioned nothing."
  exit 2
fi

# The PRFlow defaults, composed from the derived canonical identifiers. The merge
# below is `$defaults * $existing`, so the user's value wins at every depth and only
# keys they have not set are filled. permissions.defaultMode is intentionally absent,
# and no env var is written — see the NOTE in the header.
# `if !` so a jq failure here fails CLOSED instead of leaving DEFAULTS empty and
# feeding `--argjson defaults ""` into the guard below.
if ! DEFAULTS="$(printf '%s' "$IDENTITY_JSON" | "$DEVFLOW_JQ" '
  {
    extraKnownMarketplaces: {
      (.marketplace_canonical): {
        source: { source: "github", repo: "The01Geek/prflow" },
        autoUpdate: true
      }
    },
    enabledPlugins: { (.canonical_plugin_spec): true }
  }')" || [ -z "$DEFAULTS" ]; then
  warn "could not compose the PRFlow settings defaults from the resolved plugin identity; left $SETTINGS unchanged and provisioned nothing."
  exit 2
fi

# SUPERSEDED identifiers — every accepted identifier that is not the canonical one.
# A rename declares the previous id as an alias, and a repo provisioned under that
# previous id would otherwise keep BOTH registrations forever: Claude Code would
# install the plugin twice under two ids. So provisioning also MIGRATES, removing the
# superseded marketplace entry and the superseded enabledPlugins specs. Empty while no
# alias is declared, which makes this a strict no-op today.
if ! SUPERSEDED="$(printf '%s' "$IDENTITY_JSON" | "$DEVFLOW_JQ" -c '
  . as $i
  | { markets: $i.marketplace_names[1:],
      specs:   [ $i.plugin_specs[] | select(. != $i.canonical_plugin_spec) ] }')" \
   || [ -z "$SUPERSEDED" ]; then
  warn "could not derive the superseded plugin/marketplace identifiers from the resolved plugin identity; left $SETTINGS unchanged and provisioned nothing."
  exit 2
fi

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
#   - empty / whitespace-only file -> benign, treat as {} (fill the keys)
#   - non-empty, parses as JSON    -> use it verbatim
#   - non-empty, does NOT parse    -> MALFORMED: bail without touching the file
EXISTING='{}'
if [ -f "$SETTINGS" ]; then
  # Distinguish an unreadable file (perms) from invalid JSON so the breadcrumb
  # names the real cause rather than misdirecting the user to "fix the JSON".
  if [ ! -r "$SETTINGS" ]; then
    warn "existing $SETTINGS is not readable (check permissions); left it unchanged and provisioned nothing."
    exit 2
  fi
  # Classify the file's content with BASH BUILTINS ONLY — never a non-preflight
  # PATH tool (was `[ -s ] && grep -q '[^[:space:]]'`, silently defeated when
  # grep does not resolve on PATH: it classified every file blank and let the
  # merge below clobber the user's whole settings). CLAUDE.md guard-class 2 — a
  # value that decides a SELECTION or an EMITTED result must not be derived
  # through a non-preflight PATH tool; mirrors scripts/resolve-command-trigger.sh.
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
  # whitespace-only / zero-byte leaves EXISTING at {} and fills the keys.
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

# Type-guard the shapes the deep-merge relies on. `jq .` above only proves the
# file PARSES; valid-but-corrupt shapes still slip through:
#   - a non-object ROOT (`[...]` or a bare scalar) — `$defaults * $existing` is a
#     jq error (object times array/scalar) that, under `set -euo pipefail`, aborts
#     the script with a raw jq message and exit 5, escaping the documented 0/2
#     contract with no breadcrumb;
#   - a non-object at any path the merge must recurse THROUGH — every object-valued
#     path in $defaults (extraKnownMarketplaces, its devflow-marketplace entry, that
#     entry's source object, enabledPlugins) — where the user holds a non-object
#     value. jq's `*` does not error there; it silently keeps the user's value and
#     drops PRFlow's whole subtree below it (e.g. a string at devflow-marketplace
#     drops the marketplace source + autoUpdate, so the plugin never auto-updates),
#     yet still exits 0 with a success breadcrumb.
# To catch EVERY level in one sweep (rather than enumerating them by hand and
# rediscovering the next level each review), derive the object-valued paths FROM
# $defaults and flag any that $root holds as a non-object. A wrong-typed value at a
# genuine LEAF (autoUpdate, the enable flag, source.repo) is NOT an
# object-valued path, so it is a legitimate user-wins clobber and is never flagged.
# All flagged shapes are corrupt settings, treated exactly like the malformed-JSON
# case above: a specific breadcrumb, exit 2, file left byte-for-byte unchanged
# (nothing written yet). Mirrors scaffold-config.sh, which type-checks a container
# is an object before recursing.
# Capture with `if !` so a failure of the guard's OWN jq fails CLOSED. A bare
# `BAD_SHAPE="$(…)"` assignment masks the command-substitution exit status from
# `set -e`, so a jq error inside the probe would leave BAD_SHAPE empty and sail
# past the `[ -n ]` check below as if the shape were validated — silently
# defeating the very guard meant to prevent a bad merge. Treat a probe failure as
# corrupt input (exit 2, file untouched).
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
            # replaces the whole defaults subtree, so a present null silently drops
            # the PRFlow setting just like a string would). Test presence via the
            # parent has() check, not getpath alone: getpath returns null for BOTH an
            # absent path and a present-null one, and an absent path is fine (the
            # merge fills it). A non-object parent is skipped here and flagged by its
            # own (shallower) object-path instead, so each corruption is named once.
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

# MIGRATION — drop any SUPERSEDED registration before merging, so a repo provisioned
# under a previously-declared identifier is not left with two live registrations of the
# same plugin. Only the two PRFlow-owned containers are touched, and only for keys in
# the derived superseded set: a user's unrelated marketplace/plugin entry is never
# removed. Both containers are object-or-absent by the type-guard above; the `type`
# tests keep this correct if that guard is ever relaxed. `$EXISTING_ORIG` keeps the
# pre-migration value so the "nothing changed" comparison and the delta labels below
# still describe the real EXISTING->written delta (a pure removal must count as a
# change). No-op while no alias is declared.
EXISTING_ORIG="$EXISTING"
if ! EXISTING="$(printf '%s' "$EXISTING" | "$DEVFLOW_JQ" --argjson sup "$SUPERSEDED" '
  (if (.extraKnownMarketplaces | type) == "object"
     then .extraKnownMarketplaces |= with_entries(.key as $k | select(($sup.markets | index($k)) == null))
     else . end)
  | (if (.enabledPlugins | type) == "object"
       then .enabledPlugins |= with_entries(.key as $k | select(($sup.specs | index($k)) == null))
       else . end)')"; then
  warn "could not remove the superseded PRFlow registrations from $SETTINGS (migration probe failed); left it unchanged and provisioned nothing."
  exit 2
fi

# The merge cannot fail post-guard ($existing is a validated object whose every
# PRFlow object-path is object-or-absent, $defaults is a fixed valid object, so
# `*` always succeeds), but guard it anyway so an unanticipated jq failure
# (OOM, a broken build) fails CLOSED with a breadcrumb rather than a raw error.
if ! MERGED="$("$DEVFLOW_JQ" -n --argjson defaults "$DEFAULTS" --argjson existing "$EXISTING" '$defaults * $existing')"; then
  warn "could not compute the provisioned settings for $SETTINGS (merge failed); left it unchanged."
  exit 2
fi

# Only write on a real change (idempotent — no mtime churn on a re-run). Compare
# canonical (sorted) forms so formatting differences never read as a change.
if [ "$(printf '%s' "$EXISTING_ORIG" | "$DEVFLOW_JQ" -S .)" = "$(printf '%s' "$MERGED" | "$DEVFLOW_JQ" -S .)" ]; then
  log ".claude/settings.json already has the PRFlow keys; nothing changed."
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
# Guard the write so a failure (read-only FS, ENOSPC, an immutable/owned file)
# leaves a devflow-settings: breadcrumb + exit 2 rather than a raw shell/mv error
# that escapes the documented 0/2 contract. $SETTINGS is untouched until the mv
# (an atomic same-dir rename), so a failed write leaves the original intact.
if ! { printf '%s\n' "$MERGED" > "$TMP" && mv "$TMP" "$SETTINGS"; }; then
  warn "could not write $SETTINGS (check permissions and free space); left it unchanged."
  exit 2
fi
trap - EXIT

# Friendly labels for the PRFlow marker keys the merge actually landed, derived
# from the EXISTING->MERGED delta (a leaf differs) so the breadcrumb can never
# claim a key the merge did not write. The top-level containers are guaranteed
# object-or-absent by the type-guard above, so these two-level getpath probes
# never index a non-object. We reach here only past the "nothing changed"
# early-exit, so at least one leaf differs.
# Capture the delta with `if !` so a failure of this jq fails CLOSED: it runs via
# command substitution (not the old `done < <(jq …)` process substitution, whose
# exit status `set -e` cannot observe), so a jq hiccup here degrades to the generic
# success message with a warning rather than silently. The write already succeeded
# (atomic mv above), so a delta-probe failure cannot corrupt provisioning.
# The probed marker keys are the DERIVED canonical ones plus every superseded id the
# migration may have removed, so the breadcrumb names a removal as accurately as an
# addition.
added_raw=""
if ! added_raw="$("$DEVFLOW_JQ" -nr --argjson e "$EXISTING_ORIG" --argjson m "$MERGED" \
  --argjson id "$IDENTITY_JSON" --argjson sup "$SUPERSEDED" '
  ( [ ["extraKnownMarketplaces", $id.marketplace_canonical],
      ["enabledPlugins", $id.canonical_plugin_spec] ]
    + [ $sup.markets[] | ["extraKnownMarketplaces", .] ]
    + [ $sup.specs[]   | ["enabledPlugins", .] ] )
  | map(. as $p | select(($e | getpath($p)) != ($m | getpath($p))) | ($p[0] + "[" + $p[1] + "]"))
  | .[]')"; then
  warn "provisioned $SETTINGS but could not summarize which keys changed (delta probe failed)."
  added_raw=""
fi
added=()
while IFS= read -r label; do
  [ -n "$label" ] && added+=("$label")
done <<< "$added_raw"

if [ "${#added[@]}" -gt 0 ]; then
  joined="$(printf '%s, ' "${added[@]}")"; joined="${joined%, }"
  log "provisioned $SETTINGS (added: $joined): the PRFlow marketplace is now registered and auto-updating. Review the change before committing."
else
  log "provisioned $SETTINGS: the PRFlow marketplace is now registered and auto-updating. Review the change before committing."
fi
