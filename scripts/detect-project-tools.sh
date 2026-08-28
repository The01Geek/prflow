#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# detect-project-tools.sh — language-aware tool/runtime auto-population.
#
# Scans a repo for language marker files (package.json, go.mod, Cargo.toml, …),
# looks each match up in .prflow/tool-presets.json, and MERGES the union of the
# matching presets into the repo's .prflow/config.json:
#
#   - the build/test/lint tool patterns are added to two execution paths'
#     allowlists: prflow.allowed_tools (command) and prflow_implement.allowed_tools
#     (implement);
#   - the shared `setup` block gets node_version (only when currently empty — a
#     pinned version is never overridden) and a lockfile-appropriate install
#     line so the runtime the tools need actually exists before Claude runs;
#     when the Node lockfile lives in a subdirectory (monorepo / co-located JS
#     bundle) it also sets node_working_directory and scopes the install line
#     into that directory with a subshell `cd`.
#
# Idempotent UNION: existing entries are preserved (order kept, no duplicates),
# so re-running after adding a language picks up only the new tools — this is
# what makes the "run /devflow:init again after a plugin update" flow safe.
#
# This is called by scripts/scaffold-config.sh (the one shared scaffolder), so
# BOTH `/devflow:init` and install.sh get detection with no drift. Best-effort:
# a missing jq / presets file / config logs a notice and exits 0 — never blocks
# the scaffold.
#
# SECURITY: the prflow / prflow_implement allowlists written here run a PR
# author's code in their respective workflows. Keep presets to mainstream
# toolchains and review the config.json before commit.
#
# Usage: detect-project-tools.sh [TARGET_REPO_ROOT] [SCAN_ROOT]
#   TARGET_REPO_ROOT  repo whose .prflow/config.json is updated — the only tree this
#                     script WRITES to (default: git toplevel, else cwd)
#   SCAN_ROOT         tree searched for the language marker files and lockfiles
#                     (default, and on an empty value: TARGET_REPO_ROOT). Read-only.
#                     The two differ only for install.sh's dry-run preview, which
#                     writes into a sandbox copy of the consumer subtrees but must
#                     detect against the real repository — the sandbox carries no
#                     package.json / composer.json / docker-compose*, so a preview
#                     scanning it would report "no known language markers detected"
#                     and understate what --apply merges into config.json (issue #971).
#
# Exit codes: always 0 (best-effort). Non-fatal conditions log and skip.
set -euo pipefail

# State-directory resolution (issue #1002): canonical .prflow/, with the LOUD
# transitional fallback to a superseded .devflow/ when only that one is present.
# Guarded source (the lib/resolve-jq.sh discipline): a partially-copied deployment
# degrades to the canonical name with a breadcrumb instead of aborting under `set -e`.
# Self-directory anchor. `dirname` is NOT one of the tools lib/preflight.sh
# guarantees, and under `set -e` its failing command substitution aborts the read
# before a caller default is emitted — so this uses the dirname-free spelling of
# the anchor, which is also one of the shapes lib/test/cloud_writer_deps.py can
# prove (a variable assigned by a `case` cannot be resolved by that scanner, so an
# edge built from one reads as a repo-root escape). `cd`/`pwd` are bash builtins.
_DPT_SELF_DIR="$(cd "${BASH_SOURCE[0]%/*}" && pwd)"
# shellcheck source=../lib/resolve-state-dir.sh
if [ -f "$_DPT_SELF_DIR/../lib/resolve-state-dir.sh" ] \
   && . "$_DPT_SELF_DIR/../lib/resolve-state-dir.sh" \
   && type prflow_state_dir >/dev/null 2>&1; then
  :
else
  echo "prflow: resolve-state-dir.sh not found in ../lib relative to ${BASH_SOURCE[0]} — using the canonical .prflow/ with no transitional fallback" >&2
  prflow_state_dir() { printf '%s' "${1:-}/.prflow"; }
fi

# jq binary: resolved once via the resolver sourced from the sibling lib/ directory (issue #247);
# best-effort — a copied/vendored deployment without lib/ falls back to bare
# `jq` with a breadcrumb rather than aborting under set -e.
# shellcheck source=../lib/resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/resolve-jq.sh" \
  || { echo "devflow: resolve-jq.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }

log() { printf 'devflow-detect: %s\n' "$1"; }

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRESETS="$SELF_DIR/../.prflow/tool-presets.json"

TARGET_ROOT="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
# The scan root is a READ-ONLY input: it reaches marker_present, find_node_lockfile and
# the composer.json probe below, and nothing else. CONFIG — the one path this script
# writes — is derived from TARGET_ROOT, so pointing the scan at another tree can never
# move the write (issue #971). An empty value selects TARGET_ROOT, so the single-argument
# form — what scaffold-config.sh passes on the /prflow:init and install.sh --apply paths,
# and what a direct CLI invocation gets — is byte-for-byte unchanged.
SCAN_ROOT="${2:-}"
[ -n "$SCAN_ROOT" ] || SCAN_ROOT="$TARGET_ROOT"
CONFIG="$(prflow_state_dir "$TARGET_ROOT")/config.json"

# Best-effort guards — never abort the surrounding scaffold.
if ! "$DEVFLOW_JQ" --version >/dev/null 2>&1; then
  log "no usable jq (missing or not executable); skipping language auto-detection (install jq, or set DEVFLOW_JQ to a working jq/jq.exe, to enable it)."
  exit 0
fi
if [ ! -f "$PRESETS" ]; then
  log "preset registry not found at $PRESETS; skipping auto-detection."
  exit 0
fi
if [ ! -f "$CONFIG" ]; then
  log "no $CONFIG to update; skipping auto-detection."
  exit 0
fi

# --- 1. Detect which presets apply -----------------------------------------
# A preset matches when any of its marker files exists in the repo. Scan a few
# levels deep (covers monorepo sub-packages) but prune dependency/build dirs so
# a vendored marker (e.g. node_modules/**/package.json) never triggers a false
# positive and the walk stays fast. `-name` accepts globs (e.g. *.csproj).
marker_present() {
  local marker="$1" hit
  hit=$(find "$SCAN_ROOT" -maxdepth 3 \
          \( -name node_modules -o -name .git -o -name vendor -o -name target \
             -o -name dist -o -name build -o -name .venv \) -prune \
          -o -name "$marker" -print -quit 2>/dev/null || true)
  [ -n "$hit" ]
}

# `tr -d '\r'` strips the carriage return the native Windows jq build appends to
# every stdout line (Git Bash / MSYS). Without it, `read` captures keys/markers
# like $'node\r', the later `.presets[$k]` lookup asks for a key that doesn't
# exist, and detection silently finds nothing. The load-bearing invariant is
# narrow: only jq output consumed line-by-line by `read` needs the strip. Every
# other jq call here either writes JSON to a tempfile, feeds jq-as-arg, captures
# output re-parsed as JSON (via --argjson), or is read only for its exit code —
# in all of those a stray CR is harmless. Adding a new `read`-driven jq pipeline
# below? It needs `| tr -d '\r'` too.
ACTIVE=()
while IFS= read -r key; do
  [ -n "$key" ] || continue
  matched=false
  while IFS= read -r marker; do
    [ -n "$marker" ] || continue
    if marker_present "$marker"; then matched=true; break; fi
  done < <("$DEVFLOW_JQ" -r --arg k "$key" '.presets[$k].markers[]?' "$PRESETS" | tr -d '\r')
  $matched && ACTIVE+=("$key")
done < <("$DEVFLOW_JQ" -r '.presets | keys[]' "$PRESETS" | tr -d '\r')

if [ "${#ACTIVE[@]}" -eq 0 ]; then
  log "no known language markers detected; config.json left unchanged."
  exit 0
fi

ACTIVE_JSON=$(printf '%s\n' "${ACTIVE[@]}" | "$DEVFLOW_JQ" -R . | "$DEVFLOW_JQ" -s .)

# --- 2. Resolve pre-build install lines from the present lockfiles ----------
# Node and PHP need an explicit pre-build install line (npm/pnpm/yarn populate
# node_modules; composer populates vendor/) before the build/test/lint tools
# can run; other ecosystems fetch deps on first build. Pick the Node command
# matching the committed lockfile.

# Locate the Node lockfile, preferring the repo root (back-compat) and falling
# back to the first subdirectory lockfile (monorepo / co-located JS bundle under
# e.g. jsx/, resources/js/, frontend/). Same prune set as marker_present so a
# vendored node_modules lockfile never matches. Precedence pnpm → yarn → npm
# (package-lock) → npm (shrinkwrap) mirrors resolve-node-cache.sh and action.yml.
# When several subdirectories match the same manager, `-print -quit` returns
# whichever the filesystem yields first — the feature targets a single co-located
# bundle, so this is deterministic per checkout but not "nearest to root". Prints
# the path relative to SCAN_ROOT — the tree it searches — or nothing when no lockfile
# exists. The result is a RELATIVE path that becomes setup.node_working_directory, so it
# stays meaningful in the target repo even when the scan root is a different tree.
find_node_lockfile() {
  local lf hit
  for lf in pnpm-lock.yaml yarn.lock package-lock.json npm-shrinkwrap.json; do
    [ -f "$SCAN_ROOT/$lf" ] && { printf '%s' "$lf"; return; }
  done
  for lf in pnpm-lock.yaml yarn.lock package-lock.json npm-shrinkwrap.json; do
    hit=$(find "$SCAN_ROOT" -maxdepth 3 \
            \( -name node_modules -o -name .git -o -name vendor -o -name target \
               -o -name dist -o -name build -o -name .venv \) -prune \
            -o -name "$lf" -print -quit 2>/dev/null || true)
    [ -n "$hit" ] && { printf '%s' "${hit#"$SCAN_ROOT"/}"; return; }
  done
  # No lockfile anywhere: return success with empty output (the bare-npm-install
  # case). Without this, the loop's final failed `[ -n "$hit" ]` would make the
  # function exit 1 and abort the script under `set -e`.
  return 0
}

EXTRA_INSTALL_JSON='[]'
NODE_WD=""   # empty = repo root; only set when the build lives in a subdirectory
if printf '%s\n' "${ACTIVE[@]}" | grep -qx node; then
  NODE_LOCKFILE="$(find_node_lockfile)"
  case "${NODE_LOCKFILE##*/}" in
    pnpm-lock.yaml)      NODE_CMD="pnpm install --frozen-lockfile" ;;
    yarn.lock)           NODE_CMD="yarn install --frozen-lockfile" ;;
    package-lock.json)   NODE_CMD="npm ci" ;;
    npm-shrinkwrap.json) NODE_CMD="npm ci" ;;   # npm ci honors npm-shrinkwrap.json
    *)                   NODE_CMD="npm install" ;;   # no lockfile found
  esac
  # dirname is "." for a root lockfile and for the no-lockfile case (empty
  # string), so both keep today's root-level install line and empty NODE_WD. A
  # subdirectory lockfile yields a subshell `cd` so a later root-level install
  # line in the same setup.install array is unaffected by the directory change.
  # The directory is single-quoted in the generated line so a path with a space
  # (e.g. a "resources/js" sibling) doesn't word-split when the install array is
  # exec'd via `bash -c` in the action.
  NODE_LOCKDIR="$(dirname "$NODE_LOCKFILE")"
  if [ -n "$NODE_LOCKFILE" ] && [ "$NODE_LOCKDIR" != "." ]; then
    NODE_WD="$NODE_LOCKDIR"
    NODE_INSTALL="(cd '$NODE_WD' && $NODE_CMD)"
  else
    NODE_INSTALL="$NODE_CMD"
  fi
  EXTRA_INSTALL_JSON=$("$DEVFLOW_JQ" -n --arg c "$NODE_INSTALL" '[$c]')
fi
# composer install populates vendor/ so phpunit/phpstan/php-cs-fixer can run.
if printf '%s\n' "${ACTIVE[@]}" | grep -qx php && [ -f "$SCAN_ROOT/composer.json" ]; then
  EXTRA_INSTALL_JSON=$(printf '%s' "$EXTRA_INSTALL_JSON" \
    | "$DEVFLOW_JQ" -c '. + ["composer install --no-interaction --prefer-dist --no-progress"]')
fi

# --- 3. Merge into config.json (ordered union) ------------------------------
# `odedupe` appends only not-yet-present items, preserving existing order — so a
# maintainer's hand-tuned ordering (and install-line ordering, which matters)
# survives. `unique` is deliberately NOT used: it would alphabetically reorder
# install lines and break dependency-ordering assumptions.
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

"$DEVFLOW_JQ" -n \
  --slurpfile cfg "$CONFIG" \
  --slurpfile pre "$PRESETS" \
  --argjson keys "$ACTIVE_JSON" \
  --argjson extra_install "$EXTRA_INSTALL_JSON" \
  --arg nodewd "$NODE_WD" '
  def odedupe: reduce .[] as $x ([]; if any(.[]; . == $x) then . else . + [$x] end);
  ($cfg[0]) as $c |
  ($pre[0].presets) as $p |
  ([ $keys[] as $k | $p[$k].allowed_tools[]? ]) as $tools |
  ([ $keys[] as $k | $p[$k].setup.install[]? ] + $extra_install) as $inst |
  ([ $keys[] as $k | $p[$k].setup.node_version? // empty ] | .[0]) as $nodever |
  $c
  | .prflow           = (.prflow           // {})
  | .prflow_implement  = (.prflow_implement  // {})
  | .setup             = (.setup             // {})
  | .prflow.allowed_tools           = ((.prflow.allowed_tools           // []) + $tools | odedupe)
  | .prflow_implement.allowed_tools = ((.prflow_implement.allowed_tools // []) + $tools | odedupe)
  | .setup.install                  = ((.setup.install                  // []) + $inst  | odedupe)
  | (if ($nodever != null) and ((.setup.node_version // "") == "")
       then .setup.node_version = $nodever else . end)
  | (if ($nodewd != "") and ((.setup.node_working_directory // "") == "")
       then .setup.node_working_directory = $nodewd else . end)
  ' > "$TMP"

# --- 4. Best-effort shape guard before committing the merge -----------------
# The merge above can only PARSE-check its output. A malformed pre-existing
# config (e.g. a numeric node_version, or a managed allowlist that isn't an
# array of strings) is carried through and yields valid-but-wrong-shaped JSON,
# which an upgrade-time re-run would then overwrite the user's file with. A real
# JSON-schema validator would add a dependency this jq-only, never-block
# scaffolder deliberately avoids, so we instead assert — with the jq we already
# require — the shape of just the fields THIS script manages against the schema's
# types (see .prflow/config.schema.json). On a mismatch we keep the existing
# config untouched and warn rather than write a drifted one. jq's `and`
# short-circuits, so the object checks gate the indexing checks: a non-object
# managed key fails fast instead of erroring on the `.key.subkey` access.
config_shape_ok() {
  "$DEVFLOW_JQ" -e '
    def str_array: type == "array" and all(.[]; type == "string");
    (.prflow            // {} | type == "object")
    and (.prflow_implement // {} | type == "object")
    and (.setup             // {} | type == "object")
    and (.prflow.allowed_tools           // [] | str_array)
    and (.prflow_implement.allowed_tools // [] | str_array)
    and (.setup.install                   // [] | str_array)
    and (.setup.node_version              // "" | type == "string")
    and (.setup.node_working_directory    // "" | type == "string")
  ' "$1" >/dev/null 2>&1
}

# Only rewrite when the merge actually changed something (keeps re-runs quiet
# and avoids touching the file's mtime for no reason) AND the merged result
# still has the expected shape (so a drifted upgrade keeps the old config).
if "$DEVFLOW_JQ" --sort-keys . "$CONFIG" >/dev/null 2>&1 && ! diff -q \
     <("$DEVFLOW_JQ" --sort-keys . "$CONFIG") <("$DEVFLOW_JQ" --sort-keys . "$TMP") >/dev/null 2>&1; then
  if config_shape_ok "$TMP"; then
    mv "$TMP" "$CONFIG"
    trap - EXIT
    log "detected: ${ACTIVE[*]} — merged build/test tools into config.json (prflow / prflow_implement) + setup."
    log "review the additions before committing; the prflow / prflow_implement entries run PR code in their respective workflows."
  else
    log "detected: ${ACTIVE[*]} — the merged config.json failed a best-effort shape check (a prflow/setup field has an unexpected type); your existing config.json is left unchanged. Fix the field types (see .prflow/config.schema.json) and re-run, or add the tool entries by hand."
  fi
else
  log "detected: ${ACTIVE[*]} — config.json already covers them; no changes."
fi
