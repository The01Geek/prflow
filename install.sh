#!/usr/bin/env bash
# ============================================================================
# PRFlow cloud-tier installer / updater
# ============================================================================
# Installs (or updates) the PRFlow GitHub Actions "cloud tier" into the CURRENT
# repository. Idempotent — re-run any time to pull the latest from the primary
# repo. It writes:
#   - .claude-plugin/marketplace.json local marketplace pointing at the plugin
#   - .github/workflows/*.yml         devflow.yml / devflow-implement.yml
#                                     (superseded claude*.yml are removed on upgrade,
#                                     Anthropic's left)
#   - .github/actions/*               the composite actions they use
#   - .prflow/install-manifest.json  the provenance digests the upgrade path reads
#                                     to tell an untouched artifact from a hand-edited
#                                     one (see UPGRADING below)
#   - .prflow/config.json            scaffolded from the template ONLY if absent;
#                                     prflow_version pinned to the installed commit
#                                     (unless already hand-pinned to a non-SHA value)
#   - .prflow/config.schema.json     refreshed every run (editor autocomplete)
#   - .prflow/.gitignore             scoped ignore for ephemeral tmp/ scratch
#                                     (created if absent; keeps config.json +
#                                     learnings/ committed). A thin install also
#                                     adds /vendor/ so the runtime-vendored tree
#                                     is never committed; DEVFLOW_VENDOR=1 removes
#                                     that line (it commits the tree on purpose).
#   - .prflow/vendor/prflow/        the plugin tree — ONLY with DEVFLOW_VENDOR=1
#                                     (thin install otherwise; see below)
#   - .gitignore                      one appended block ignoring the preserved-artifact
#                                     sidecars the upgrade path writes (see UPGRADING);
#                                     your own content is never rewritten
#
# Thin by default: the workflows materialize the plugin into the workspace at
# RUNTIME via the vendor-plugin composite action (it clones the pinned
# prflow_version), so the tree no longer has to be committed. The plugin SCRIPTS
# still end up at the literal workspace path the claude-code-action runner needs
# (its bash sandbox can't reach ~/.claude / CLAUDE_SKILL_DIR) — just produced by a
# step instead of a commit. Updating then means bumping prflow_version (or
# re-running this installer, now a small diff). Set DEVFLOW_VENDOR=1 to commit the
# plugin tree instead — self-hosting with no runtime fetch, fully auditable in
# your repo. (Local editor use is different again: add the github marketplace with
# autoUpdate — see docs/internal/cloud-setup.md.)
#
# UPGRADING an existing installation (issue: consumer upgrade path)
# ----------------------------------------------------------------
# A repository that already carries a PRFlow installation is an UPGRADE, and an
# upgrade is DRY-RUN BY DEFAULT: the installer prints the full plan and a unified
# diff of every byte it would change, and writes nothing until you re-run it with
# `--apply`. This mirrors the consent-gated provisioners (`provision-auto-mode.sh`,
# `provision-python3-shim.sh`): those two print and stop until told to write.
# (`scripts/provision-local-settings.sh` is deliberately NOT in that list — it is
# ungated and writes the project `.claude/settings.json` immediately when
# `/prflow:init` invokes it; that write is diff-visible in a committed file, and the
# script's breadcrumb ends "Review the change before committing.") This installer
# itself writes nothing without an explicit opt-in. A FIRST-TIME install (nothing of PRFlow's present)
# still applies immediately, so the documented one-liner below is unchanged.
#
# Local modifications are never silently overwritten. Each artifact the installer
# owns is recorded in `.prflow/install-manifest.json` with the sha256 of the bytes
# the installer wrote. On the next run:
#   - byte-identical to the recorded digest -> unmodified -> updated in place;
#   - different from the recorded digest    -> locally MODIFIED -> PRESERVED, and the
#                                              new version is written beside it as
#                                              `<file>.prflow-new` for you to merge;
#   - no recorded digest (an installation predating the manifest, or a skipped-version
#     jump) -> provenance UNVERIFIED -> preserved the same way, unless the bytes already
#     equal the new version, in which case nothing changes and the digest is recorded;
#   - your file's CURRENT bytes cannot be digested -> provenance UNESTABLISHED ->
#     preserved the same way. TWO different situations reach this, and only the first
#     one is global:
#       * no working python3 at all (stock Windows / Git-Bash before the shim
#         provisioner): NOTHING can be digested, so every artifact is preserved and the
#         manifest is not written;
#       * a read error on one path with a working python3 (an unreadable file, one
#         unreadable file inside a composite-action directory): only THAT artifact is
#         preserved. Every other artifact is classified and written normally, and the
#         manifest IS written — the preserved one simply keeps its previous entry
#         instead of being re-recorded.
#     Reported distinctly from UNVERIFIED
#     because the remedy differs: resolve python3, then re-run for a real comparison;
#   - absent (you deleted it) -> recreated. Whether a path EXISTS is decided by a bash
#     builtin test, upstream of python3, so a missing interpreter can never make a file
#     you have look absent — the defect this ordering exists to prevent.
# `.prflow/config.json` is never rewritten by this mechanism at all — the shared
# scaffolder only backfills keys the example gained.
#
# A sidecar is UNTRACKED and lands inside your own `.github/` (or `.claude-plugin/`),
# which `.prflow/.gitignore` cannot reach — its patterns are relative to `.prflow/`.
# So a later `git add -A` would commit it, and the installer appends a
# standing ignore rule for the sidecar suffix to the repository-root `.gitignore`
# (issue #970). It has to be standing rather than a cleanup: keeping your own version
# means leaving the sidecar in place indefinitely.
#
# Usage, from the root of your repo. Download-read-run is the documented form:
# fetch this file at a PINNED ref — a release tag (vN.N.N), or a commit
# SHA; never mutable main — read it, then run the copy you read. docs/internal/install.md
# carries the current pinned one-liner; docs/internal/cloud-setup.md the full guide.
#   curl -fsSL https://raw.githubusercontent.com/The01Geek/prflow/<ref>/install.sh -o devflow-install.sh
#   DEVFLOW_REF=<ref> bash devflow-install.sh
#   # point at a fork (DEVFLOW_REF defaults to main, so pin it too):
#   DEVFLOW_REF=<ref> DEVFLOW_REPO=<owner>/<repo> bash devflow-install.sh
#   # commit the plugin tree instead of fetching it at runtime:
#   DEVFLOW_VENDOR=1 bash devflow-install.sh
#   # upgrade an existing installation: preview first, then apply
#   DEVFLOW_REF=<ref> bash devflow-install.sh            # dry run, writes nothing
#   DEVFLOW_REF=<ref> bash devflow-install.sh --apply
#
# Flags (also settable as env vars, for a `curl | bash` invocation that cannot pass
# arguments):
#   --dry-run   / DEVFLOW_DRY_RUN=1  force the preview even on a first-time install
#   --apply     / DEVFLOW_APPLY=1    write the changes (required to upgrade)
#   --remove-withheld-review-tier / DEVFLOW_REMOVE_WITHHELD_REVIEW_TIER=1
#               opt in to removing the withheld automatic-review tier this repository
#               installed before it was withheld (see the report the installer prints)
# ============================================================================
set -euo pipefail

REPO="${DEVFLOW_REPO:-The01Geek/prflow}"
REF="${DEVFLOW_REF:-main}"

# Argument parsing lives in the installer BODY (below the DEVFLOW_SELFTEST return),
# never here: this file is also SOURCED by the test harness, where `"$@"` would be
# the sourcing script's own positional parameters and an unrecognized one would abort
# the harness instead of the installer.

# The accepted plugin/marketplace identifiers, compiled from lib/plugin-identity.json +
# .claude-plugin/plugin.json. BAKED (not read at runtime) on purpose: this script is
# curl-pipeable with no repository present, and the tree it inspects below is a
# FOREIGN one. Plain assignments, never `${DEVFLOW_PLUGIN_NAME_ERE:-…}` — an
# inherited environment value must not be able to widen or narrow the prune check.
#
# The ERE is the stale-tree discriminator. The CANONICAL pair is what this installer
# writes into the local marketplace manifest, so the manifest carries no hand-spelled
# name. The SUPERSEDED lists are every accepted identifier that is not canonical —
# what a declared alias means — and drive the identifier-migration report below.
# Adding an alias to lib/plugin-identity.json and regenerating is therefore the ONLY
# edit a rename needs here.
# devflow-plugin-identity:begin identity_version=2 sha256=912f043a3462b0fb8c75645849a5a305588c1997e6e498687462edb968ec1809 (generated by lib/generate-plugin-identity.py -- do not hand-edit; source: lib/plugin-identity.json + .claude-plugin/plugin.json)
DEVFLOW_PLUGIN_NAME_ERE='"name"[[:space:]]*:[[:space:]]*"(prflow|devflow)"'
DEVFLOW_PLUGIN_CANONICAL='prflow'
DEVFLOW_MARKETPLACE_CANONICAL='devflow-marketplace'
DEVFLOW_SUPERSEDED_MARKETPLACES=''
DEVFLOW_SUPERSEDED_PLUGIN_SPECS='devflow@devflow-marketplace'
# devflow-plugin-identity:end

log() { printf 'devflow-install: %s\n' "$1"; }
die() { printf 'devflow-install: %s\n' "$1" >&2; exit 1; }

# Pin .prflow/config.json's prflow_version to the ref we installed, so the
# runtime fetch (vendor-plugin) never tracks mutable main. Adds or updates the
# single key without clobbering the rest of the config — using the FIRST
# USABLE of jq or python3 (both are JSON-safe), each writing to a temp file
# and renaming so a failure can never truncate the config in place. This is
# tool SELECTION, not a retry cascade: the jq/python3 arms are `if`/`elif`
# conditions, so once a tool is selected the other arm is skipped — a
# selected-but-failing tool does NOT fall through to the next one. That is
# fine: the realistic failure (a malformed config.json, a read-only .prflow/)
# would defeat python3 too. Selection is execution-verified (issue #247): a
# present-but-unrunnable Windows `jq` shim must not win this selection over a
# working python3, so the jq arm requires `--version` to actually run. (python3 is a hard PRFlow prerequisite;
# `node` was dropped from this cascade — it is no longer required anywhere in
# PRFlow's config path.)
# NEVER aborts the install: a missing tool OR a present-but-failing tool (e.g. a
# pre-existing config.json that isn't valid JSON, a read-only .prflow/) both
# degrade to a warning telling the user to set the key by hand. The success-path
# `return 0`s live inside the `if` conditions so `set -e` can't fire on a tool
# failure.
#
# Only re-stamps when the EXISTING prflow_version is absent/empty or already
# looks like a commit SHA (7-40 lowercase hex). This is a SHAPE heuristic, not
# true provenance detection: it cannot distinguish a SHA this function itself
# previously wrote from a SHA the user hand-set to pin to one specific commit,
# so a hand-pinned exact SHA is not guaranteed to survive a re-run. A value
# that does NOT match that pattern (a branch name like "main", a tag like
# "v1.2.0") was set by hand, so it IS guaranteed to be treated as a deliberate
# pin/tracking choice and left untouched — re-running the installer must never
# silently convert "track main" into "pinned to a SHA".
set_config_version() {
  local cfg="$1" version="$2" tmp
  [ -f "$cfg" ] || return 0
  tmp="$(mktemp)" || { log "warning: mktemp failed; add \"prflow_version\": \"$version\" to $cfg by hand."; return 0; }
  # jq resolution (#247): adapted from lib/resolve-bin.sh's contract —
  # install.sh must run standalone (curl-piped, before any checkout exists), so
  # it cannot source the shared resolver. An explicit DEVFLOW_JQ wins the
  # SELECTION (no candidate probing happens); deliberately unlike the shared
  # resolver, the selection gate below then re-probes whatever was selected,
  # so a broken override routes to the python3 arm instead of failing the
  # step. Otherwise the first of jq/jq.exe whose `--version` runs is selected.
  local jqbin
  jqbin="${DEVFLOW_JQ:-}"
  if [ -z "$jqbin" ]; then
    if jq --version >/dev/null 2>&1; then jqbin=jq
    elif jq.exe --version >/dev/null 2>&1; then jqbin=jq.exe
    fi
  fi
  # Surface a broken explicit override at the earliest, cheapest point: the
  # runtime helpers honor DEVFLOW_JQ verbatim (never probed), so without this
  # breadcrumb the misconfiguration first detonates far from its cause.
  if [ -n "${DEVFLOW_JQ:-}" ] && ! "$jqbin" --version >/dev/null 2>&1; then
    log "warning: DEVFLOW_JQ is set to '$jqbin' but it does not execute; falling back for this step — fix DEVFLOW_JQ before running PRFlow."
  fi
  if [ -n "$jqbin" ] && "$jqbin" --version >/dev/null 2>&1; then
    if "$jqbin" -e '(.prflow_version // "") as $cur | ($cur == "" or ($cur | test("^[0-9a-f]{7,40}$")))' \
        "$cfg" >/dev/null 2>&1; then
      if "$jqbin" --arg v "$version" '.prflow_version = $v' "$cfg" > "$tmp" 2>/dev/null; then
        if mv "$tmp" "$cfg"; then
          log "pinned prflow_version=$version in $cfg"; return 0
        fi
      fi
    else
      local rc=$?
      if [ "$rc" -eq 1 ]; then
        rm -f "$tmp"
        log "kept existing prflow_version in $cfg (looks like a deliberate pin, not a previous SHA stamp) — not overwriting."
        return 0
      fi
      # rc > 1: jq itself errored on the eligibility check (not a genuine false/null
      # result) — fall through to the generic warning rather than misreport it as a
      # deliberate pin.
    fi
  elif command -v python3 >/dev/null 2>&1; then
    if DEVFLOW_CFG="$cfg" DEVFLOW_VER="$version" DEVFLOW_OUT="$tmp" python3 -c 'import json,os,re,sys
c=json.load(open(os.environ["DEVFLOW_CFG"]))
cur=c.get("prflow_version")
# Only null/false count as "absent", mirroring jq'"'"'s `// ""` exactly (jq'"'"'s // only
# substitutes on false/null, never on other falsy JSON values like 0/[]/{}). A
# non-string, non-null/false value (e.g. 0) then fails the re.match below with an
# uncaught TypeError -> exit 1 -> the generic warning, matching jq'"'"'s test/1 runtime
# error on the same input (rc>1) rather than python silently coercing it to "".
if cur is None or cur is False:
    cur=""
if cur == "" or re.match(r"^[0-9a-f]{7,40}$", cur):
    c["prflow_version"]=os.environ["DEVFLOW_VER"]
    open(os.environ["DEVFLOW_OUT"],"w").write(json.dumps(c,indent=2)+"\n")
    sys.exit(0)
sys.exit(3)' 2>/dev/null; then
      if mv "$tmp" "$cfg"; then
        log "pinned prflow_version=$version in $cfg"; return 0
      fi
    else
      local rc=$?
      rm -f "$tmp"
      if [ "$rc" -eq 3 ]; then
        log "kept existing prflow_version in $cfg (looks like a deliberate pin, not a previous SHA stamp) — not overwriting."
        return 0
      fi
    fi
  fi
  rm -f "$tmp"
  log "warning: could not set prflow_version=$version automatically — add \"prflow_version\": \"$version\" to $cfg by hand so the runtime fetch is pinned."
  return 0
}

# Remove PRFlow's OWN superseded workflow files on upgrade. Left behind, the
# old claude.yml keeps listening for @claude and double-fires alongside the new
# devflow.yml. claude-runner.yml / claude-implement.yml are PRFlow-specific
# names (Anthropic never generates them), so removing them is safe. claude.yml,
# however, is SHARED with Anthropic's Claude GitHub App — so remove it ONLY when
# it carries a PRFlow signature (the review_dedupe job / the old header line);
# otherwise it is Anthropic's and must be left untouched.
prune_stale_devflow_workflows() {
  local wf=.github/workflows f
  for f in claude-runner claude-implement; do
    if [ -f "$wf/$f.yml" ]; then
      rm -f "$wf/$f.yml"
      log "removed superseded $f.yml (logic now in devflow.yml / devflow-implement.yml)"
    fi
  done
  if [ -f "$wf/claude.yml" ]; then
    if grep -qE 'review_dedupe:|Light @claude-mention listener for non-implementing' "$wf/claude.yml"; then
      rm -f "$wf/claude.yml"
      log "removed PRFlow's old claude.yml (logic now in devflow.yml)"
    else
      log "left existing claude.yml untouched — it is not PRFlow's (likely Anthropic's Claude GitHub App)."
    fi
  fi
}

# Remove a stale committed plugin tree at the OLD vendored location
# (.claude/plugins/devflow) left by a pre-relocation DEVFLOW_VENDOR=1 install.
# The plugin now lives at .prflow/vendor/prflow because claude-code-action's
# restore-from-base deletes .claude/ on PRs (it is a SENSITIVE_PATH), which wiped
# a tree vendored there. Signature-guarded — only ever removes a directory that
# is actually PRFlow's plugin (carries a devflow plugin.json) so an unrelated
# .claude/plugins/devflow is never touched. Prunes now-empty parents best-effort,
# never the user's wider .claude/ (which holds settings/skills/hooks).
prune_stale_vendored_plugin() {
  local old=.claude/plugins/devflow
  [ -d "$old" ] || return 0   # common case: no old tree → silent no-op.
  # The non-empty precondition is not decoration: `grep -Eq ""` matches ANY
  # file, so an emptied discriminator would turn this identity check into an
  # unconditional `rm -rf`. Fail closed on an unestablished set.
  if [ -n "$DEVFLOW_PLUGIN_NAME_ERE" ] \
     && [ -f "$old/.claude-plugin/plugin.json" ] \
     && grep -Eq "$DEVFLOW_PLUGIN_NAME_ERE" "$old/.claude-plugin/plugin.json"; then
    rm -rf "$old"
    rmdir .claude/plugins .claude 2>/dev/null || true
    log "removed stale committed plugin at $old (relocated to .prflow/vendor/prflow)"
  else
    # The directory exists but is not a recognizable PRFlow plugin (no devflow
    # plugin.json — e.g. a partial/interrupted older install, or an unrelated
    # tree). Don't rm it blindly; warn so a genuinely-stale tree isn't left to be
    # silently wiped by claude-code-action's .claude/ restore on the next cloud PR.
    log "warning: $old exists but carries no devflow plugin.json; leaving it untouched — if it is a stale pre-relocation vendored tree, remove it by hand (.claude/ is wiped on cloud PRs)."
  fi
}

# Keep the runtime-vendored tree out of consumer commits — but only for thin
# installs. A thin consumer materializes .prflow/vendor/prflow at RUNTIME (in
# cloud CI); now that it survives the restore-from-base (the whole point of the
# relocation), an implement/review-fix run's `git add -A` would otherwise stage
# the bulky tree into the consumer's PR. So a thin install adds `/vendor/` to
# .prflow/.gitignore (patterns there are relative to .prflow/, matching the
# existing `/tmp/` entry). A DEVFLOW_VENDOR=1 install commits the tree on
# purpose, so the ignore line must be ABSENT there — handle the thin→vendor
# upgrade by removing a previously-added line. Idempotent; no-op when the
# scaffolded .gitignore is missing.
manage_vendor_gitignore() {
  local gi=.prflow/.gitignore
  [ -f "$gi" ] || return 0
  if [ "${DEVFLOW_VENDOR:-}" = "1" ]; then
    if grep -qxF '/vendor/' "$gi"; then
      # Portable in-place delete — NOT `sed -i` (GNU-only; BSD/macOS sed needs a
      # backup-suffix arg, and this is a `curl | bash` installer that must run on
      # macOS — see CONTRIBUTING.md). Filter to a temp, then swap only on a clean
      # filter. grep exit 0 = lines kept, 1 = none kept (/vendor/ was the only
      # line → empty result is correct), 2 = real error: distinguish so a
      # mid-write failure (e.g. ENOSPC) never `mv`s a truncated temp over the
      # tracked .gitignore and silently drops /tmp/.
      local _rc=0
      grep -vxF '/vendor/' "$gi" > "$gi.tmp" || _rc=$?
      if [ "$_rc" -le 1 ]; then
        mv "$gi.tmp" "$gi"
        log "un-ignored .prflow/vendor/ (DEVFLOW_VENDOR=1 commits the plugin tree)"
      else
        rm -f "$gi.tmp"
        log "warning: could not rewrite $gi (grep exit $_rc); left /vendor/ in place — remove it by hand so the committed tree is tracked."
      fi
    fi
  elif ! grep -qxF '/vendor/' "$gi"; then
    printf '/vendor/\n' >> "$gi"
    log "ignored .prflow/vendor/ (runtime-vendored plugin must not be committed by a thin install)"
  fi
}

# Keep the preserved-artifact sidecars out of consumer commits (issue #970).
#
# When the upgrade path preserves a `modified` / `unverified` / `unreadable` artifact it
# writes PRFlow's version beside it as `<path>.prflow-new` (see install_managed below).
# That sidecar is UNTRACKED and sits inside the consumer's own `.github/` or
# `.claude-plugin/`, which the one ignore file this installer used to manage
# (`.prflow/.gitignore`) cannot reach — so a later `git add -A`, including one inside a
# /prflow:implement run, sweeps a whole shipped workflow into an unrelated PR.
# The rule has to be a STANDING ignore rather than a cleanup: a consumer who deliberately
# keeps their own version leaves the sidecar in place indefinitely, which is exactly the
# case a "resolve it, then we tidy up" design would never reach.
#
# It cannot live in .prflow/.gitignore. Patterns there are relative to .prflow/ (see
# manage_vendor_gitignore above) and a sidecar never lands under that directory, so that
# file is precedent for the installer managing an ignore rule at all — not a place this
# rule could work. The repository-root .gitignore is, and the pattern is an UNANCHORED
# basename glob: git matches it at any depth, and against a DIRECTORY as well as a file,
# which the composite-action case needs (a preserved `.github/actions/vendor-plugin` is
# copied with `cp -R` to a whole `vendor-plugin.prflow-new/` tree).
#
# The superseded `*.devflow-new` spelling is ignored alongside it. Sidecars written before
# the .devflow -> .prflow rename are precisely the artifacts observed sitting untracked in
# a real consumer repository, and nothing rewrites a file already on disk.
DEVFLOW_SIDECAR_IGNORE_HEADER='# PRFlow install.sh: preserved-artifact sidecars (never commit these)'

# Whether $1 already carries $2 as a whole line. Deliberately NOT `grep -qxF`: this
# comparison DECIDES whether a line is appended, and grep is not one of the tools
# lib/preflight.sh guarantees (CLAUDE.md's non-preflight-PATH-tool guard) — a host
# without it would make every run append the block again. Pure bash instead. `read`
# returns non-zero on a final line carrying no trailing newline but still assigns it,
# so the `|| [ -n "$line" ]` arm keeps that last line inside the scan.
devflow_gitignore_carries() {
  local line
  [ -f "$1" ] || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    if [ "$line" = "$2" ]; then return 0; fi
  done < "$1"
  return 1
}

manage_sidecar_gitignore() {
  local gi=.gitignore pat block="" append_err
  # Refuse a symlink outright, and a non-regular path after it. The symlink arm is FIRST and
  # unconditional because `>>` follows the link and writes to its TARGET, which can sit
  # anywhere on the filesystem — outside this repository entirely. All three link shapes
  # are unsafe and none is detectable by a `-e`/`-f` pair, because both of those tests
  # follow the link too:
  #   * a LIVE link to a regular file  -> `-e` true,  `-f` TRUE  -> appends to the target;
  #   * a DANGLING link                -> `-e` false, `-f` false -> CREATES the target;
  #   * a link to a directory          -> `-e` true,  `-f` false.
  # An earlier form of this guard tested `{ -e && ! -f } || { -L && ! -e }` and so caught
  # only the last two — the live link, the commonest shape, walked straight through it and
  # wrote outside the repository. `[ -L ]` is the only test that does not dereference, so
  # it is the only one that can answer this question.
  #
  # The second arm then covers the non-link non-regular shapes (a real directory). A
  # regular file, or an absent path, is what the append below requires.
  #
  # Refusing a symlinked .gitignore is deliberately conservative — a link pointing INSIDE
  # the repository would have been safe to append to — but the breadcrumb hands the
  # consumer the exact two patterns, and no reachable input can make this function write
  # outside the tree it was pointed at. Best-effort as ever: report and carry on.
  if [ -L "$gi" ] || { [ -e "$gi" ] && [ ! -f "$gi" ]; }; then
    log "warning: $gi is a symlink or is not a regular file, so the preserved-artifact sidecar ignore rules were not added (appending through a symlink can write outside this repository). Add '*.prflow-new' and '*.devflow-new' to your ignore rules by hand so an upgrade's sidecars are never committed."
    return 0
  fi
  for pat in '*.prflow-new' '*.devflow-new'; do
    if ! devflow_gitignore_carries "$gi" "$pat"; then
      block="$block$pat"$'\n'
    fi
  done
  [ -n "$block" ] || return 0
  # A leading blank line does double duty: it separates the block from the consumer's own
  # content, and it REPAIRS a .gitignore whose last line carries no trailing newline —
  # appending straight onto that would silently rewrite their last pattern into
  # `<their-pattern>*.prflow-new`. `[ -s ]` is a bash builtin, so the empty/absent case
  # needs no external tool either.
  if [ -s "$gi" ]; then
    block=$'\n'"$DEVFLOW_SIDECAR_IGNORE_HEADER"$'\n'"$block"
  else
    block="$DEVFLOW_SIDECAR_IGNORE_HEADER"$'\n'"$block"
  fi
  # stderr is captured (`2>&1` BEFORE the append, so fd 2 is the substitution's pipe when
  # the append redirection is attempted) and surfaced in the warning, the same way
  # scaffold-config.sh's rewrite_config_if_changed reports a failed `mv`: a read-only
  # filesystem, ENOSPC and an immutable file are different remedies, and a bare "could
  # not append" names none of them. The failure never aborts this best-effort scaffold.
  if append_err="$(printf '%s' "$block" 2>&1 >> "$gi")"; then
    log "ignored preserved-artifact sidecars in $gi (an upgrade writes <path>.prflow-new beside a file it preserves, and an untracked sidecar is one 'git add -A' away from an unrelated commit)"
  else
    log "warning: could not append the preserved-artifact sidecar ignore rules to $gi${append_err:+ ($append_err)}. Add '*.prflow-new' and '*.devflow-new' to your ignore rules by hand so an upgrade's sidecars are never committed."
  fi
}

# On a host with no `python3` on PATH (a stock Windows / Git-Bash install, where Python is
# reachable only as `python` / `py -3`), surface PRFlow's consent-gated Python shim
# provisioner so `install.sh` users hit it regardless of install method. It DELEGATES to the
# one provisioner (scripts/provision-python3-shim.sh in the cloned source) — install.sh never
# re-implements interpreter detection — and is a no-op when `python3` already resolves (native
# marketplace installs that bypass install.sh remain covered by the preflight pointer, which
# /devflow:init relays). Best-effort: a missing provisioner or a refusal never aborts the install.
offer_python3_shim() {
  local src="$1" prov rc
  # Probe RUNNABILITY, not mere presence — mirror lib/preflight.sh's happy-path gate. A
  # `python3` that is on PATH but does not execute (dangling symlink, corrupt install,
  # missing runtime DLL — the broken-Windows-interpreter class this provisioner targets)
  # must NOT short-circuit the offer here; it falls through so the resolver/provisioner can
  # surface the remedy. A bare `command -v python3` would skip the offer on exactly that case.
  if command -v python3 >/dev/null 2>&1 && python3 -c 'pass' >/dev/null 2>&1; then
    return 0   # a WORKING python3 is present → nothing to offer here (preflight still enforces the >=3.11 check).
  fi
  prov="$src/scripts/provision-python3-shim.sh"
  if [ ! -f "$prov" ]; then
    log "no working 'python3' on PATH and the shim provisioner is unavailable in the source tree; see docs/internal/install.md to resolve a Python 3 interpreter."
    return 0
  fi
  log "no working 'python3' on PATH — surfacing PRFlow's consent-gated Python interpreter resolver:"
  # Default (no --apply) prints the plan + manual instructions and writes nothing; the user
  # opts into the write by re-running the provisioner with --apply. ANY non-zero exit — the
  # designed plan-mode refusals (rc 2: no >=3.11 interpreter / too-old) and genuine provisioner
  # breakage (a missing lib/resolve-python.sh source, a syntax error, an unexpected set -e
  # abort) alike — is surfaced with the rc rather than swallowed, and never aborts the install.
  # The single breadcrumb covers both cases (this is intentional — one unconditional log, not a
  # branch): for a benign rc-2 refusal the provisioner's own `devflow-python:` breadcrumb on
  # stderr already names the specific cause; for genuine breakage the rc here makes it
  # diagnosable rather than laundered into apparent success.
  bash "$prov" || { rc=$?; log "the Python interpreter resolver exited non-zero (rc $rc); install continues — re-run 'bash $prov' to see its diagnostics."; }
}

# ============================================================================
# Upgrade machinery: provenance, non-clobbering installs, and the dry-run preview
# ============================================================================
#
# Every artifact this installer OWNS is recorded in .prflow/install-manifest.json
# as a sha256 of the bytes the installer wrote. That digest is the only thing that
# can distinguish "the consumer never touched this" from "the consumer hand-edited
# this", and consumers DO hand-edit their workflows. Without it an upgrade is a
# `cp` that silently destroys local work; with it, an artifact whose current bytes
# do not match its recorded digest is preserved and the new version is written
# beside it for a human merge.
#
# The digests are computed with python3 (hashlib) — a hard PRFlow prerequisite,
# and the same choice scripts/install-gh-wrapper.sh makes — never sha256sum/shasum,
# which lib/preflight.sh does not guarantee: a value that decides whether a file is
# overwritten must not be derived through a non-preflight PATH tool.
#
# The fail-safe has TWO triggers, with deliberately different blast radii — conflating
# them is how this file's own prose has been wrong before:
#   GLOBAL — no working python3. Nothing can be digested, so every present artifact
#     reports `unreadable` and is preserved with the new version beside it, and the
#     manifest is not written at all.
#   PER-ARTIFACT — a read error on one path while python3 works. Only that path
#     reports `unreadable`. Every other artifact is classified and written exactly as
#     usual, and devflow_write_manifest still runs: the preserved path is simply left
#     out of the update list, so it keeps whatever digest it already had rather than
#     being re-blessed against bytes nobody could read.
# What both share — and all that both share — is the invariant that matters: an
# unestablished digest never licenses a destructive write.
# `unknown` is collapsed onto NOTHING — not onto `unmodified`, and not (the far worse
# reading, because it destroys) onto `create`. Whether an artifact EXISTS is settled
# by a bash builtin test in devflow_artifact_action, upstream of python3 entirely, so
# the absence that licenses a write can never be an artifact of a missing interpreter.
DEVFLOW_PY=""
devflow_resolve_python() {
  if [ -n "$DEVFLOW_PY" ]; then return 0; fi
  if command -v python3 >/dev/null 2>&1 && python3 -c 'pass' >/dev/null 2>&1; then
    DEVFLOW_PY=python3
  fi
  [ -n "$DEVFLOW_PY" ]
}

# Digest one path (file or directory) as this installer defines identity. A
# directory digests as the sha256 over its sorted relative-path + per-file-digest
# pairs, so a renamed, added, or removed file inside a composite action changes the
# digest exactly like an edited one. Prints the empty string for an absent path.
#
# The RETURN CODE is the load-bearing half of this function's contract, and the
# reason it is not just "prints a digest or prints nothing":
#   rc 0  the digest was ESTABLISHED. stdout is the 64-char hex digest, or the
#         empty string when the path does not exist (an established absence).
#   rc 1  the digest is UNESTABLISHED — no working python3, or the interpreter
#         errored (an unreadable file, a permission error, one unreadable file
#         inside a composite-action directory, ENOMEM …).
# Collapsing rc 1 onto "empty stdout" is what made a python3-less --apply read
# every existing artifact as absent and `rm -rf`/`cp` over it: `unknown` became
# `create`, which destroys, and CLAUDE.md's "unknown is not zero" rule exists for
# exactly this. Callers must branch on the rc, never on emptiness alone.
DEVFLOW_DIGEST_PY='
import hashlib, os, sys
p = sys.argv[1]
def filedig(fp):
    h = hashlib.sha256()
    with open(fp, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
if os.path.isdir(p):
    h = hashlib.sha256()
    entries = []
    for root, dirs, files in os.walk(p):
        dirs.sort()
        for f in sorted(files):
            fp = os.path.join(root, f)
            entries.append((os.path.relpath(fp, p).replace(os.sep, "/"), filedig(fp)))
    for rel, d in sorted(entries):
        h.update(rel.encode("utf-8")); h.update(b"\0")
        h.update(d.encode("ascii")); h.update(b"\0")
    sys.stdout.write(h.hexdigest())
elif os.path.exists(p):
    sys.stdout.write(filedig(p))
'
devflow_digest() {
  devflow_resolve_python || return 1
  "$DEVFLOW_PY" -c "$DEVFLOW_DIGEST_PY" "$1" 2>/dev/null || return 1
}

# The recorded digest for one artifact, or the empty string when the manifest is
# absent, unreadable, malformed, or simply has no entry. Every one of those is
# "provenance unestablished", which the caller must treat as unverified — never as
# a match. The manifest is a file a human can hand-corrupt, so every shape defect
# degrades to the empty string rather than aborting the installer.
DEVFLOW_MANIFEST_READ_PY='
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    sys.exit(0)
if not isinstance(data, dict):
    sys.exit(0)
arts = data.get("artifacts")
if not isinstance(arts, dict):
    sys.exit(0)
val = arts.get(sys.argv[2])
if isinstance(val, str):
    sys.stdout.write(val)
'
DEVFLOW_MANIFEST_PATH=".prflow/install-manifest.json"
devflow_recorded_digest() {
  devflow_resolve_python || { printf ''; return 0; }
  [ -f "$DEVFLOW_MANIFEST_PATH" ] || { printf ''; return 0; }
  "$DEVFLOW_PY" -c "$DEVFLOW_MANIFEST_READ_PY" "$DEVFLOW_MANIFEST_PATH" "$1" 2>/dev/null || printf ''
}

# Classify one artifact. Run with the target repo root as the working directory.
#   create      the consumer does not have it (fresh install, or they deleted it)
#   unchanged   already byte-identical to what we would write
#   update      unmodified since we wrote it -> safe to replace
#   modified    hand-edited since we wrote it -> PRESERVE
#   unverified  present, digestible, but no provenance on record -> PRESERVE
#   unreadable  present, but its CURRENT bytes could not be digested -> PRESERVE
#
# `unverified` and `unreadable` are both fail-safe preserves and differ only in what
# they tell the consumer, which is the whole point of splitting them: "no recorded
# digest" is a remedy the consumer can act on (delete the file and re-run to adopt
# PRFlow's copy), while "the digest could not be computed" points at the host —
# usually a missing python3, which is a different fix entirely. Reporting the
# python3-less host as "no recorded digest" would send every Windows/Git-Bash
# consumer to the wrong remedy.
#
# Only `create` and `update` write over the consumer's path, so ABSENCE is the one
# input that can license destruction — and it is therefore decided by a bash
# BUILTIN test, never by an empty digest and never by anything downstream of
# python3. That ordering is the whole fix: `devflow_digest` yields the empty string
# both for a genuinely absent path AND (before the rc contract above) for a digest
# it could not compute, so a classifier that inferred absence from emptiness read
# "no python3 on this host" as "the consumer has none of these files" and clobbered
# every one of them. A present path whose digest cannot be established is
# `unreadable` — preserved, sidecar written, reported — which is what the header's
# fail-safe guarantee has always promised.
#
# `[ -e ]` follows symlinks, so a DANGLING symlink at $rel is not `-e` while it is
# very much present on disk; `-L` catches it and routes it to the preserve arm
# rather than letting `rm -rf`/`cp` replace it.
devflow_artifact_action() {
  local rel="$1" srcp="$2" cur new rec rc=0
  if [ ! -e "$rel" ] && [ ! -L "$rel" ]; then printf 'create'; return 0; fi
  cur="$(devflow_digest "$rel")" || rc=$?
  # rc 1 = unestablished; empty stdout on rc 0 = python3 reports the path absent
  # while the builtin test above says it exists (a dangling symlink, a path that
  # vanished mid-run, a special file). Both are "cannot be established" for a path
  # we know is there, and both fail closed to preserve.
  if [ "$rc" -ne 0 ] || [ -z "$cur" ]; then printf 'unreadable'; return 0; fi
  # A source digest that cannot be established only costs the `unchanged` fast
  # path: the classification then rests on $rec, and the sole outcome it can still
  # reach that writes is `update`, which requires the consumer's bytes to MATCH
  # their recorded digest — i.e. provably untouched. So this arm cannot destroy a
  # local edit, and defaulting it to empty is safe rather than a third collapse.
  new="$(devflow_digest "$srcp")" || new=""
  if [ -n "$new" ] && [ "$cur" = "$new" ]; then printf 'unchanged'; return 0; fi
  rec="$(devflow_recorded_digest "$rel")" || rec=""
  if [ -z "$rec" ]; then printf 'unverified'; return 0; fi
  if [ "$cur" = "$rec" ]; then printf 'update'; else printf 'modified'; fi
}

# Install one owned artifact, honoring the classification above. Never overwrites a
# `modified` / `unverified` / `unreadable` artifact: the new bytes go to
# `<path>.prflow-new` and the consumer is told to merge. Accumulates the artifacts
# whose digest the manifest should record — a preserved one is deliberately NOT
# recorded, so the conflict is reported again on every run until the consumer
# resolves it.
DEVFLOW_RECORD_RELS=""
install_managed() {
  local rel="$1" srcp="$2" act parent rc=0
  [ -e "$srcp" ] || return 0
  act="$(devflow_artifact_action "$rel" "$srcp")" || rc=$?
  # The classifier is total over the six words today, but a `case` with no default
  # arm turns any future gap into a SILENT no-op: neither installed nor preserved
  # nor reported, and a green suite. Route an unexpected (or empty, or non-zero-rc)
  # classification into a preserve arm, which is the only fail-closed answer.
  if [ "$rc" -ne 0 ]; then act=unreadable; fi
  case "$act" in
    create|unchanged|update|modified|unverified|unreadable) ;;
    *)
      log "warning: internal: unrecognized classification '$act' for $rel; treating it as unreadable and preserving what is there."
      act=unreadable
      ;;
  esac
  parent="${rel%/*}"
  case "$act" in
    unchanged)
      log "unchanged: $rel"
      DEVFLOW_RECORD_RELS="$DEVFLOW_RECORD_RELS $rel"
      ;;
    create|update)
      [ "$parent" = "$rel" ] || mkdir -p "$parent"
      # Stage beside the target, then swap — never `rm -rf "$rel"; cp -R` in place. The
      # in-place form leaves a window in which $rel holds a HALF-COPIED tree, and a
      # failure inside that window is not self-healing the way it first looks: the copy
      # aborts the run under `set -e` BEFORE devflow_write_manifest, so the manifest
      # keeps the pre-copy digest, and the next run compares the half-copied bytes
      # against it, classifies `modified`, and PRESERVES the corruption — reporting the
      # consumer's own broken artifact back to them as a local edit, on every later run.
      # Staging keeps the destructive step down to an rm+mv over an already-complete
      # tree, which is the same care `os.replace` gives the manifest write.
      rm -rf "$rel.prflow-stage"
      if [ -d "$srcp" ]; then cp -R "$srcp" "$rel.prflow-stage"; else cp "$srcp" "$rel.prflow-stage"; fi
      rm -rf "$rel"
      mv "$rel.prflow-stage" "$rel"
      log "$act: $rel"
      DEVFLOW_RECORD_RELS="$DEVFLOW_RECORD_RELS $rel"
      ;;
    modified|unverified|unreadable)
      rm -rf "$rel.prflow-new"
      if [ -d "$srcp" ]; then cp -R "$srcp" "$rel.prflow-new"; else cp "$srcp" "$rel.prflow-new"; fi
      case "$act" in
        modified)
          log "PRESERVED (locally modified since DevFlow wrote it): $rel — the new version is at $rel.prflow-new; merge it by hand."
          ;;
        unverified)
          log "PRESERVED (provenance unverified — no recorded digest, so a local edit cannot be ruled out): $rel — the new version is at $rel.prflow-new; merge it by hand, or delete $rel and re-run to take PRFlow's copy."
          ;;
        *)
          # TWO different causes reach `unreadable`, and they have DIFFERENT remedies, so
          # the message must not name one while the other is what happened. Telling a
          # consumer whose python3 works fine to "resolve a working python3" is the same
          # error class as the defect this whole layer exists to prevent: reporting an
          # established fact the code never established. devflow_resolve_python is
          # idempotent (it returns early once DEVFLOW_PY is set), so asking again here is
          # free and reads the real state rather than inferring it.
          if devflow_resolve_python; then
            log "PRESERVED (provenance UNESTABLISHED — this artifact's current bytes could not be digested, so a local edit cannot be ruled out): $rel — the new version is at $rel.prflow-new. This path was not overwritten; other artifacts on this run were classified normally. python3 works here, so this is a read error on this path — check that it and every file inside it are readable, then re-run."
          else
            log "PRESERVED (provenance UNESTABLISHED — this artifact's current bytes could not be digested, so a local edit cannot be ruled out): $rel — the new version is at $rel.prflow-new. This path was not overwritten. There is no working python3 on this host, so NOTHING on this run could be compared: resolve one (see docs/internal/install.md) and re-run to get a real comparison."
          fi
          ;;
      esac
      ;;
  esac
}

# Write the provenance manifest for the artifacts installed on this run. Merges into
# any existing manifest so a preserved artifact keeps its previous digest instead of
# being silently re-blessed. Best-effort: a failure warns and never aborts the install
# (a missing manifest degrades the NEXT run to `unverified`, which is the safe arm).
DEVFLOW_MANIFEST_WRITE_PY='
import hashlib, json, os, sys
path, version, ref = sys.argv[1], sys.argv[2], sys.argv[3]
rels = [r for r in sys.argv[4:] if r]
def filedig(fp):
    h = hashlib.sha256()
    with open(fp, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
def digest(p):
    if os.path.isdir(p):
        h = hashlib.sha256()
        entries = []
        for root, dirs, files in os.walk(p):
            dirs.sort()
            for f in sorted(files):
                fp = os.path.join(root, f)
                entries.append((os.path.relpath(fp, p).replace(os.sep, "/"), filedig(fp)))
        for rel, d in sorted(entries):
            h.update(rel.encode("utf-8")); h.update(b"\0")
            h.update(d.encode("ascii")); h.update(b"\0")
        return h.hexdigest()
    if os.path.exists(p):
        return filedig(p)
    return None
data = {}
try:
    with open(path, encoding="utf-8") as fh:
        loaded = json.load(fh)
    if isinstance(loaded, dict):
        data = loaded
except Exception:
    data = {}
arts = data.get("artifacts")
if not isinstance(arts, dict):
    arts = {}
for rel in rels:
    d = digest(rel)
    if d is not None:
        arts[rel] = d
out = {
    "manifest_version": 1,
    "prflow_version": version,
    "installed_from_ref": ref,
    "artifacts": dict(sorted(arts.items())),
}
os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=2, sort_keys=True)
    fh.write("\n")
os.replace(tmp, path)
'
devflow_write_manifest() {
  local version="$1" ref="$2"
  if ! devflow_resolve_python; then
    log "warning: no working python3 — the install provenance manifest ($DEVFLOW_MANIFEST_PATH) was not written, so the next upgrade cannot tell an untouched artifact from a hand-edited one and will preserve everything it finds."
    return 0
  fi
  # shellcheck disable=SC2086  # DEVFLOW_RECORD_RELS is a space-separated list of
  # repo-relative paths this script itself composed; word splitting is the point.
  if "$DEVFLOW_PY" -c "$DEVFLOW_MANIFEST_WRITE_PY" "$DEVFLOW_MANIFEST_PATH" "$version" "$ref" $DEVFLOW_RECORD_RELS; then
    log "recorded install provenance in $DEVFLOW_MANIFEST_PATH"
  else
    log "warning: could not write $DEVFLOW_MANIFEST_PATH; the next upgrade will preserve every existing artifact rather than update it."
  fi
}

# ── The withheld automatic-review tier ──────────────────────────────────────
# The pull-request-triggered review tier is withheld from this release (issue #936)
# and this installer ships none of its three files. A repository that installed it
# BEFORE the withholding still has them, still runs them, and stays exposed to issues
# #930 and #920 — so an upgrade must SAY SO. It must not delete them silently: that
# tier is a required status check in the repositories that adopted it, and removing
# the workflow while a branch protection rule still requires its context wedges every
# subsequent pull request behind a check nothing will report. Removal is therefore an
# explicit opt-in, and even then step 3 of docs/internal/workflow-triggers.md (the branch
# protection context) stays a human action this installer cannot perform.
DEVFLOW_WITHHELD_TIER="devflow-review devflow-runner telemetry-push"
devflow_withheld_tier_present() {
  local _wt found=""
  # `_wt`, not `w`: `for w in …` is the shape more than one checker parses out of this file
  # to derive the SHIPPED workflow set, and a second loop over that variable name upstream of
  # the copy loop would be the one they found.
  for _wt in $DEVFLOW_WITHHELD_TIER; do
    [ -f ".github/workflows/$_wt.yml" ] && found="$found $_wt"
  done
  printf '%s' "${found# }"
}
# Issue #1004 Tier 3. The DEVFLOW_* variables, secrets and environment overrides live
# OUTSIDE the repository (GitHub settings, a shell profile), so no installer can migrate
# them — and nothing in the plugin reads a PRFLOW_* equivalent, so renaming one deletes the
# setting rather than moving it. Most delete it silently: an unresolvable `vars.X` is
# byte-identical to one deliberately left unset, so every gate takes its not-configured arm
# and the run goes green under a degraded identity.
#
# GATED to an UPGRADE, not emitted on every run. A first-time installer is reading
# docs/internal/cloud-setup.md and setting these names for the first time; a warning not to rename
# what they have not yet created is noise. The population that HAS them configured, and is
# now looking at a renamed product, is exactly the existing-installation population. The
# installer cannot read GitHub variables (it makes no `gh` calls), so this is the closest
# thing to "silent when nothing is actionable" available on this surface. The full
# inventory — per name, with its failure mode — is generated into docs/internal/cloud-setup.md from
# lib/rename-map.json's frozen.env_identifiers block and is deliberately NOT restated here.
devflow_report_env_identifier_freeze() {
  local state="$1"
  [ "$state" = "an existing" ] || return 0
  log "NOTICE: PRFlow's DEVFLOW_* names are unchanged and must stay that way. The repository rename did not touch the GitHub variables and secrets (DEVFLOW_APP_ID, DEVFLOW_RUNNER, ...) or the environment overrides (DEVFLOW_GH, DEVFLOW_REF, ...) — nothing here reads a PRFLOW_* equivalent, so renaming one removes the setting instead of moving it, and most do so SILENTLY (an unresolvable GitHub variable is indistinguishable from one you never set: the run stays green with a degraded identity, or on a runner you did not choose). Do not rename them. The full list, with what each rename actually does, is in docs/internal/cloud-setup.md under 'Why these settings are still called DEVFLOW_*'."
}
devflow_report_withheld_tier() {
  local present="$1"
  [ -n "$present" ] || return 0
  # These two lines run BEFORE the config is read, so neither can know which spelling of
  # the review toggle this consumer carries (issue #1041 renamed it, and an un-migrated
  # config still holds the superseded one). Both are therefore named — asserting one
  # would point half of all readers at a key their config does not contain.
  log "NOTICE: this repository carries the withheld automatic-review tier ($present). It is not shipped any more (issue #936) and this installer leaves it alone by default, but it keeps running and keeps this repository exposed to issues #930 and #920 for as long as the review toggle is true in .prflow/config.json — workflows[\"prflow-review\"], or workflows[\"devflow-review\"] if this repository has not migrated its config keys yet. See docs/internal/workflow-triggers.md."
  if [ "${REMOVE_WITHHELD:-}" = "1" ]; then
    log "  --remove-withheld-review-tier was given: the workflow files will be deleted and that review toggle set to false under whichever spelling your config carries. You must ALSO remove the 'Devflow Review' context from any branch protection rule or ruleset that requires it — otherwise every later pull request wedges against a required check nothing will report. This installer cannot do that for you."
  else
    log "  To remove it, re-run with --remove-withheld-review-tier (and read step 3 of docs/internal/workflow-triggers.md first — the branch protection context is a manual step)."
  fi
}
# Turn off the config key the withheld tier reads. Best-effort and shape-guarded: a
# config that is not a JSON object, or that has a non-object `workflows`, is left
# untouched with a breadcrumb rather than being restructured underneath the consumer.
#
# SPELLING FOLLOWS THE CONFIG, NOT THIS RELEASE (issue #1041). Tier 4 renamed the key
# `workflows.devflow-review` -> `workflows.prflow-review`, and this function runs BEFORE
# scaffold-config.sh's key migration in devflow_apply_all. Writing the current spelling
# unconditionally into a config that still carries the superseded one leaves BOTH keys
# present, and the migration then resolves that both-present case through its example-
# valued graft arm: the new key holds the shipped example default (`false`), so it is
# judged a deep-merge graft, dropped, and the SUPERSEDED value is written through in its
# place. A `devflow-review: true` therefore lands back as `prflow-review: true` in the
# same run that just reported the tier disabled — the run reporting an outcome it did not
# achieve. So: disable EVERY spelling the config actually carries, and only when it
# carries neither fall back to the current one. Every ordering then agrees --
#   superseded only -> that key goes false, and the migration carries the false across;
#   current only    -> that key goes false;
#   both present    -> both go false, so whichever the migration keeps is false;
#   neither         -> the current spelling is created false.
# The keys acted on are written to stdout so the caller can name them; the caller treats
# an empty report on a success rc as unestablished rather than logging a key it cannot
# prove was touched.
DEVFLOW_DISABLE_REVIEW_PY='
import json, os, sys
path = sys.argv[1]
with open(path, encoding="utf-8") as fh:
    data = json.load(fh)
if not isinstance(data, dict):
    sys.exit(3)
wf = data.get("workflows")
if wf is None:
    wf = {}
if not isinstance(wf, dict):
    sys.exit(3)
# Current spelling first, so a both-present report leads with the current name.
keys = [k for k in ("prflow-review", "devflow-review") if k in wf]
if not keys:
    keys = ["prflow-review"]
if all(wf.get(k) is False for k in keys):
    sys.stdout.write(" ".join(keys))
    sys.exit(4)
for k in keys:
    wf[k] = False
data["workflows"] = wf
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
os.replace(tmp, path)
sys.stdout.write(" ".join(keys))
'
# The per-file signature that identifies a withheld-tier workflow as DEVFLOW'S COPY,
# rather than a consumer file that merely happens to share the name. This has to be a
# specific pattern, not the substring "devflow": `telemetry-push.yml` is a perfectly
# ordinary name for a workflow a consumer owns, and such a file mentioning the string
# anywhere — a `.github/workflows/devflow*.yml` path filter, a comment, a step reading
# the `workflows.prflow` key — would satisfy a substring test and be deleted
# with a reassuring "removed withheld review-tier workflow" line. The opt-in flag is not consent to delete a file PRFlow
# never wrote.
#
# Each arm carries TWO alternatives so a consumer who lightly edited their installed
# copy (renaming the workflow, say) is still recognized by the structural one:
#   devflow-review   its own `name:` header, or the reusable-workflow call that IS the
#                    tier (it is the only caller of devflow-runner.yml)
#   devflow-runner   its own `name:` header, or the reviewer allowlist floor it applies
#   telemetry-push   its own `name:` header, or the workflow_run binding naming the
#                    review workflow it relays for
# Anything unrecognized prints the EMPTY string, and the caller treats an empty pattern
# as "cannot identify" and preserves — never as "matches everything" (the failure mode
# prune_stale_vendored_plugin's own non-empty precondition exists to stop).
devflow_withheld_tier_signature() {
  case "$1" in
    devflow-review)
      printf '%s' '^name: Devflow Review \(auto-trigger\)|uses:[[:space:]]*\./\.github/workflows/devflow-runner\.yml' ;;
    devflow-runner)
      printf '%s' '^name: DevFlow Runner \(reusable\)|filter-runner-tools\.sh' ;;
    telemetry-push)
      printf '%s' '^name: Telemetry push \(trusted relay\)|workflows:[[:space:]]*\["Devflow Review \(auto-trigger\)"\]' ;;
    *) printf '' ;;
  esac
}
# Turn the config key off. Split out of devflow_remove_withheld_tier so the ORDER of the
# two halves is an explicit, drivable decision rather than an accident of layout.
#
# RETURN CODE is load-bearing, and it answers exactly one question: "is the key provably
# NOT left stranded true?"
#   rc 0  the key is off, was already off, or there is no config file that could hold it
#   rc 1  it could not be established as off — no working python3, or a config shape this
#         cannot safely edit
# The caller deletes files only on rc 0. Returning 0 unconditionally (as this did) is what
# let the ordering comment below claim an invariant the code did not enforce: a malformed
# config warned, returned 0, and the files were deleted anyway — landing in precisely the
# stranded state the ordering exists to prevent.
#
# The log names the spelling the edit ACTUALLY touched, which is the whole point of the
# report the helper writes to stdout: on a config that has not migrated yet that is the
# superseded `devflow-review`, and a line naming `prflow-review` there would describe a
# key this run never wrote. Composed with bash builtins only — no `tr`/`sed`, which
# lib/preflight.sh does not guarantee and which would silently empty an EMITTED value.
devflow_review_key_clause() {  # $1 = space-separated key list -> `workflows["a"] and workflows["b"]`
  local _k _out=""
  for _k in $1; do
    [ -z "$_out" ] || _out="$_out and "
    _out="${_out}workflows[\"$_k\"]"
  done
  printf '%s' "$_out"
}
devflow_disable_review_key() {
  local rc keys
  if [ ! -f .prflow/config.json ]; then
    return 0   # nothing to strand
  fi
  if ! devflow_resolve_python; then
    # No edit happened, so no spelling is established — name both rather than assert one.
    log "warning: no working python3 — could not turn the withheld review-tier config key off in .prflow/config.json; set workflows[\"prflow-review\"] false by hand (workflows[\"devflow-review\"] if this repository has not migrated its config keys yet)."
    return 1
  fi
  rc=0
  keys="$("$DEVFLOW_PY" -c "$DEVFLOW_DISABLE_REVIEW_PY" .prflow/config.json 2>/dev/null)" || rc=$?
  # Fail closed on a success rc with no report: the rc says the key is off but nothing
  # names which one, and this function's contract is that its 0 is provable. Returning 1
  # lands in the self-healing interrupted state (key off, files still present) rather
  # than the unrecoverable one, so a re-run finishes the job.
  if [ "$rc" -eq 0 ] || [ "$rc" -eq 4 ]; then
    if [ -z "$keys" ]; then
      log "warning: the withheld review-tier config edit reported success but named no config key, so it cannot be confirmed; check workflows[\"prflow-review\"] in .prflow/config.json by hand."
      return 1
    fi
  fi
  case "$rc" in
    0) log "set $(devflow_review_key_clause "$keys")=false in .prflow/config.json"; return 0 ;;
    4) log "$(devflow_review_key_clause "$keys") is already false in .prflow/config.json"; return 0 ;;
    *) log "warning: could not turn the withheld review-tier config key off in .prflow/config.json (it is missing, malformed, or holds a non-object at that key); set it by hand."; return 1 ;;
  esac
}
# INSTALL-TIME HALF of the #1041 silent-disable skew guard. The trigger-time ::error::
# baked into both shipped workflows is the AUTHORITATIVE signal — it fires on every later
# trigger and needs no installer run to reach the operator. This warns at the moment the
# skew is CREATED, which is the one moment somebody is actually watching output.
#
# Strictly READ-ONLY, and deliberately so. It never edits a workflow, never edits the
# config, and above all never couples the workflow refresh to the config migration: the
# freshness gate can legitimately refuse (that refusal is what keeps a stale workflow from
# reading a migrated config), and forcing shared fate there would trade this loud, bounded
# failure for a worse one.
#
# The whole judgement is made inside python3 — a hard prerequisite — rather than by
# grepping the workflow. A missing PATH tool must not be able to decide an EMITTED
# result, and an unresolvable python3 here simply emits nothing while the trigger-time
# guard still reports the skew.
DEVFLOW_ENABLE_SKEW_PY='
import json, os, sys
try:
    with open(".prflow/config.json", encoding="utf-8") as fh:
        cfg = json.load(fh)
except Exception:
    sys.exit(0)
wf = cfg.get("workflows") if isinstance(cfg, dict) else None
# has-semantics, never truthiness: a deliberate `workflows.devflow: false` is a real
# value, and the skew is about which KEY exists, not what it holds.
if not isinstance(wf, dict) or "prflow" in wf or "devflow" not in wf:
    sys.exit(0)
skewed = []
for name in sys.argv[1:]:
    try:
        with open(os.path.join(".github", "workflows", name), encoding="utf-8") as fh:
            body = fh.read()
    except Exception:
        continue
    if ".workflows.prflow" in body:
        skewed.append(name)
if skewed:
    sys.stdout.write(" ".join(skewed))
'
devflow_warn_enable_key_skew() {
  local skewed
  devflow_resolve_python || return 0
  skewed="$("$DEVFLOW_PY" -c "$DEVFLOW_ENABLE_SKEW_PY" devflow.yml devflow-implement.yml 2>/dev/null)" || return 0
  [ -n "$skewed" ] || return 0
  log "WARNING: PARTIAL UPGRADE — these shipped workflows now read the renamed enable key workflows.prflow, but .prflow/config.json still carries only the superseded workflows.devflow: $skewed. They resolve as DISABLED and every trigger will silently do nothing. The config-key migration was refused because another shipped workflow still reads the superseded key — merge any .github/workflows/*.prflow-new sidecar left beside a hand-edited workflow, then re-run install.sh --apply so the workflow reads and the config key move together."
}
devflow_remove_withheld_tier() {
  local present="$1" _wt _sig _grc
  [ -n "$present" ] || return 0
  [ "${REMOVE_WITHHELD:-}" = "1" ] || return 0
  # CONFIG KEY FIRST, and files only if it succeeded. The two interrupted states are not
  # symmetric, and only one is self-healing:
  #   key off, files still present -> the tier is inert, and a re-run still finds the
  #     files (this function's own `present` gate) and finishes the job.
  #   files gone, key still true   -> `present` is now EMPTY, so every later run returns
  #     at the gate above and the key is never disabled again. Permanently stuck.
  # Ordering alone does not get us the second state's impossibility — the config edit can
  # FAIL (no python3, a malformed config) — so the deletion is gated on the disable having
  # actually established the key as off. An invariant a comment asserts and the code does
  # not enforce is worse than no invariant: it stops the next reader from checking.
  if ! devflow_disable_review_key; then
    log "warning: leaving the withheld review-tier workflow files in place — the review toggle could not be turned off, and removing the files first would strand that key true with nothing left to trigger a retry. Fix the config (or resolve python3) and re-run with --remove-withheld-review-tier."
    return 0
  fi
  for _wt in $present; do
    # Signature-guarded in the same SPIRIT as prune_stale_devflow_workflows — a specific
    # pattern this file's PRFlow copy carries — but with its own per-file patterns rather
    # than that function's claude.yml one. The empty-pattern precondition is not
    # decoration: `grep -Eq ""` matches ANY file, so an unrecognized name (or an emptied
    # arm) must not fall through into an unconditional delete.
    #
    # grep's rc is THREE-valued and the two failure rcs mean different things: 1 = read the
    # file, found no match (a content judgement) and 2 = could not read it at all (a
    # permission error, an I/O fault). Both preserve, but reporting rc 2 as "carries no
    # PRFlow signature" states a conclusion about content nothing ever read — the same
    # unestablished-measurement-presented-as-established error this file's provenance layer
    # exists to avoid. Capture the rc and name the real one.
    _sig="$(devflow_withheld_tier_signature "$_wt")"
    _grc=0
    if [ -n "$_sig" ]; then
      grep -qE "$_sig" ".github/workflows/$_wt.yml" || _grc=$?
    else
      _grc=1   # no pattern for this name: treat as "does not match", never as a read failure
    fi
    case "$_grc" in
      0)
        rm -f ".github/workflows/$_wt.yml"
        log "removed withheld review-tier workflow $_wt.yml (opted in via --remove-withheld-review-tier)"
        ;;
      1)
        log "warning: .github/workflows/$_wt.yml carries no DevFlow signature; left it untouched — it does not look like DevFlow's copy."
        ;;
      *)
        log "warning: could not read .github/workflows/$_wt.yml to check its signature (grep exit $_grc); left it untouched. This is a read failure, NOT a judgement that the file is not DevFlow's — fix its permissions and re-run if you meant to remove it."
        ;;
    esac
  done
}

# ── Identifier migration ────────────────────────────────────────────────────
# When the published plugin/marketplace identifier changes, the previous id is declared
# as an alias in lib/plugin-identity.json and every accepted-but-not-canonical id becomes
# SUPERSEDED. The artifacts this installer owns are rewritten to the canonical id by the
# ordinary managed-artifact path above (the marketplace manifest is composed from the
# baked canonical pair, so a rename changes its bytes and the upgrade reports it).
#
# The consumer file this installer must NOT write is `.claude/settings.json`: keeping the
# cloud-only installer out of the local-tier settings is a standing invariant (issue #88),
# and `scripts/provision-local-settings.sh` already OWNS that migration — since PR #943 it
# removes every superseded marketplace entry and enabledPlugins spec on the next
# `/devflow:init`. So the installer DETECTS and REPORTS, and routes the consumer to the one
# provisioner rather than growing a second, drifting copy of the same removal.
DEVFLOW_SETTINGS_SCAN_PY='
import json, sys
path = sys.argv[1]
markets = [m for m in sys.argv[2].split() if m]
specs = [s for s in sys.argv[3].split() if s]
try:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    sys.exit(0)
if not isinstance(data, dict):
    sys.exit(0)
hits = []
container = data.get("extraKnownMarketplaces")
if isinstance(container, dict):
    hits += ["extraKnownMarketplaces[" + m + "]" for m in markets if m in container]
container = data.get("enabledPlugins")
if isinstance(container, dict):
    hits += ["enabledPlugins[" + s + "]" for s in specs if s in container]
if hits:
    sys.stdout.write(", ".join(hits))
'
devflow_report_superseded_identifiers() {
  local hits
  # Skip entirely when NOTHING is superseded, so no python3 is spent on a repo that can
  # have no stale registration. Which way this gate falls is decided by the baked lists
  # above, i.e. by lib/plugin-identity.json's alias lists — not by this comment: in the
  # tree that ships this copy DEVFLOW_SUPERSEDED_MARKETPLACES is empty but
  # DEVFLOW_SUPERSEDED_PLUGIN_SPECS is NOT (it carries `devflow@devflow-marketplace`), so
  # the concatenation below is non-empty, the gate PASSES, and the scan runs — the report
  # is live, not a no-op. It short-circuits only in a tree where BOTH lists are empty.
  # Re-read the baked assignments before asserting which.
  [ -n "$DEVFLOW_SUPERSEDED_MARKETPLACES$DEVFLOW_SUPERSEDED_PLUGIN_SPECS" ] || return 0
  [ -f .claude/settings.json ] || return 0
  devflow_resolve_python || {
    log "warning: no working python3 — could not check .claude/settings.json for superseded DevFlow registrations; run /prflow:init to migrate them."
    return 0
  }
  hits="$("$DEVFLOW_PY" -c "$DEVFLOW_SETTINGS_SCAN_PY" .claude/settings.json \
      "$DEVFLOW_SUPERSEDED_MARKETPLACES" "$DEVFLOW_SUPERSEDED_PLUGIN_SPECS" 2>/dev/null || printf '')"
  [ -n "$hits" ] || return 0
  log "NOTICE: .claude/settings.json still registers superseded DevFlow identifiers ($hits). This installer never writes that file — run /prflow:init, whose scripts/provision-local-settings.sh removes the superseded registrations and adds the current one."
}

# The same detect-and-route split, applied to `.prflow/config.json`. The GitHub App that
# authors PRFlow's PRs was renamed `devflow-autopilot` -> `prflow-implementer` (the app id
# behind DEVFLOW_APP_ID is unchanged), so a consumer who added the old slug to
# `prflow.allowed_bots` — or, on a consumer whose Tier-1 migration has not run yet, to
# `devflow.allowed_bots`; the scanner below probes both and reports whichever it found —
# now carries an entry that matches no live identity:
# scripts/authorize-actor.sh compares logins for EQUALITY, so the stale slug authorizes
# nothing and the implement/review stall-backstop resume comment is declined by the very
# gate it re-enters — a green run that never resumes.
#
# NOT part of the generated plugin-identity region above, deliberately: that region is
# compiled from lib/plugin-identity.json, which models plugin/marketplace identity. An App
# slug is a different identity with a different lifecycle, so it is a plain assignment here
# rather than a widening of a generated, sha-stamped region.
#
# The scaffolder is add-only and cannot rename a VALUE, and this installer does not write
# the file for this purpose: `/devflow:init` owns the correction, so the installer DETECTS
# and REPORTS and routes there, exactly as it does for .claude/settings.json above.
#
# Format: whitespace-separated `stale=current` pairs.
DEVFLOW_STALE_BOT_LOGINS='devflow-autopilot=prflow-implementer'
# Best-effort over a file a human hand-edits: EVERY unexpected shape (unreadable, not JSON,
# a non-object root, neither `prflow` nor `devflow` an object, `allowed_bots` of the
# wrong type, a valid-falsy empty
# string) leaves stdout empty and exits 0, so the caller reports nothing and the install
# proceeds. It never writes.
DEVFLOW_CONFIG_SCAN_PY='
import json, sys
path = sys.argv[1]
pairs = [p.split("=", 1) for p in sys.argv[2].split() if "=" in p]
try:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    sys.exit(0)
if not isinstance(data, dict):
    sys.exit(0)
# Look under BOTH block names. Which one a consumer carries depends on whether the
# Tier-1 migration has run, and a scanner that knew only one name would fall silent on
# exactly half the population -- reporting "nothing stale here" about a config it never
# looked at. The current name wins when both are somehow present.
section = None
block = ""
for candidate in ("prflow", "devflow"):
    value = data.get(candidate)
    if isinstance(value, dict):
        section = value
        block = candidate
        break
if section is None:
    sys.exit(0)
raw = section.get("allowed_bots")
# A bool is an int, not a str, so `false` lands here and exits silently like any other
# wrong type; an explicit "" is a str and simply yields no entries.
if not isinstance(raw, str):
    sys.exit(0)
entries = []
for e in raw.split(","):
    e = e.strip()
    if e.endswith("[bot]"):
        e = e[: -len("[bot]")]
    if e:
        entries.append(e)
hits = []
for stale, current in pairs:
    if stale in entries:
        hits.append(block + ".allowed_bots[" + stale + " -> " + current + "]")
if hits:
    sys.stdout.write(", ".join(hits))
'
devflow_report_stale_config_identifiers() {
  local hits
  # Same short-circuit shape as the settings report: with no pair declared there is nothing
  # to find, so no python3 is spent. Re-read the assignment above before asserting which way
  # this falls.
  [ -n "$DEVFLOW_STALE_BOT_LOGINS" ] || return 0
  local cfg
  # Whichever state directory this repository actually has: a consumer whose Tier-1
  # migration refused still keeps its config under the superseded name, and reporting
  # against a path that does not exist would be a silent no-op on the population that
  # most needs the notice.
  if [ -f .prflow/config.json ]; then cfg=.prflow/config.json
  elif [ -f .devflow/config.json ]; then cfg=.devflow/config.json
  else return 0
  fi
  devflow_resolve_python || {
    log "warning: no working python3 — could not check $cfg for superseded PRFlow identifiers; run /prflow:init to correct them."
    return 0
  }
  hits="$("$DEVFLOW_PY" -c "$DEVFLOW_CONFIG_SCAN_PY" "$cfg" \
      "$DEVFLOW_STALE_BOT_LOGINS" 2>/dev/null || printf '')"
  [ -n "$hits" ] || return 0
  log "NOTICE: $cfg still names superseded PRFlow identifiers ($hits). This installer never rewrites that file for this — run /prflow:init, which corrects them in place, preserves your other values, and reports the diff to review before you commit."
}

# ── The dry-run preview ─────────────────────────────────────────────────────
# The preview is not a second implementation of the plan: it runs the REAL apply
# function against a sandbox copy of the consumer's own tree and then diffs the
# sandbox against the tree. Anything --apply would do, the preview did — to a copy.
#
# The diff is rendered with python3 difflib rather than `diff -u`: `diff` is not one
# of the tools lib/preflight.sh guarantees, and a silently-absent one would print an
# empty (i.e. reassuring) preview.
DEVFLOW_DIFF_PY='
import difflib, os, sys
real, prev = sys.argv[1], sys.argv[2]
scopes = sys.argv[3:]
SKIP = (".prflow/vendor",)
def walk(base):
    out = {}
    for scope in scopes:
        root = os.path.join(base, scope)
        if os.path.isfile(root):
            out[scope] = root
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            for name in sorted(filenames):
                fp = os.path.join(dirpath, name)
                rel = os.path.relpath(fp, base).replace(os.sep, "/")
                if any(rel == s or rel.startswith(s + "/") for s in SKIP):
                    continue
                out[rel] = fp
    return out
a, b = walk(real), walk(prev)
def text(fp):
    try:
        with open(fp, encoding="utf-8") as fh:
            return fh.read().splitlines(keepends=True)
    except (UnicodeDecodeError, OSError):
        return None
changed = 0
for rel in sorted(set(a) | set(b)):
    # A file that exists on only ONE side is an add or a delete, and its whole body is
    # not a diff a reader needs: report it as one line with its size. Only a file that
    # exists on BOTH sides gets a unified diff, which is the case where the bytes that
    # changed are the thing to inspect.
    if rel not in b:
        changed += 1
        sys.stdout.write("DELETE " + rel + "\n")
        continue
    if rel not in a:
        body = text(b[rel])
        size = "binary" if body is None else str(len(body)) + " lines"
        changed += 1
        sys.stdout.write("ADD    " + rel + " (" + size + ")\n")
        continue
    left, right = text(a[rel]), text(b[rel])
    if left is None or right is None:
        # A binary artifact on both sides: compare bytes, and never try to diff them.
        with open(a[rel], "rb") as fh1, open(b[rel], "rb") as fh2:
            if fh1.read() != fh2.read():
                changed += 1
                sys.stdout.write("MODIFY " + rel + " (binary)\n")
        continue
    if left == right:
        continue
    changed += 1
    sys.stdout.write("MODIFY " + rel + "\n")
    for line in difflib.unified_diff(left, right, fromfile="a/" + rel, tofile="b/" + rel):
        sys.stdout.write(line if line.endswith("\n") else line + "\n")
sys.stdout.write("devflow-install: " + str(changed) + " file(s) would change.\n")
'
# The subtrees the preview copies and diffs. `.prflow/vendor` is excluded from the
# diff body (a DEVFLOW_VENDOR=1 tree is thousands of files and its churn is reported
# as one line by the apply log instead), and only the two `.claude/` paths this
# installer READS are copied — never the consumer's wider `.claude/`.
#
# `.claude/plugins` is in the DIFF scope, not merely the sandbox copy, because
# prune_stale_vendored_plugin can `rm -rf .claude/plugins/devflow` on a pre-relocation
# DEVFLOW_VENDOR=1 upgrade. devflow_build_preview already copies that subtree so the
# prune runs against the sandbox, but a deletion the renderer does not walk is a
# deletion the preview does not show — and the documented promise is a diff of every
# byte the apply would change. Scoped to `plugins`, never bare `.claude`: the
# consumer's settings/skills/hooks are their own and this installer neither writes nor
# reports them. A scope that does not exist simply contributes nothing.
#
# The repository-root `.gitignore` is in scope because manage_sidecar_gitignore appends to
# it (issue #970). A write the preview does not render is a write the consumer never
# consented to — the same class of gap issue #971 closes on the other side of this
# function, and the reason the header's "every byte it would change" promise can stand.
DEVFLOW_PREVIEW_SCOPES=".claude-plugin .github .prflow .devflow .claude/plugins .gitignore"

devflow_render_preview() {
  local real="$1" prev="$2"
  if ! devflow_resolve_python; then
    log "warning: no working python3 — cannot render the dry-run diff. The plan lines above are the whole preview."
    return 0
  fi
  # shellcheck disable=SC2086  # DEVFLOW_PREVIEW_SCOPES is a fixed, space-separated
  # literal this script owns; word splitting into separate arguments is intended.
  "$DEVFLOW_PY" -c "$DEVFLOW_DIFF_PY" "$real" "$prev" $DEVFLOW_PREVIEW_SCOPES
}

# Materialize the sandbox: a copy of the consumer subtrees the apply path reads or
# writes. Missing subtrees are simply absent in the copy, which is exactly what the
# apply path would see. `.prflow/vendor` is skipped — the apply path recreates it
# from $SRC when DEVFLOW_VENDOR=1 and never reads the existing one.
devflow_build_preview() {
  local real="$1" prev="$2" d
  mkdir -p "$prev"
  for d in .claude-plugin .github; do
    [ -e "$real/$d" ] && cp -R "$real/$d" "$prev/$d"
  done
  # BOTH state-directory names: an un-migrated consumer carries only the superseded
  # one, and a preview that skipped it would render an empty (i.e. reassuring) diff
  # for the one change with the largest blast radius.
  for _sd in .prflow .devflow; do
    if [ -d "$real/$_sd" ]; then
      mkdir -p "$prev/$_sd"
      for d in "$real"/"$_sd"/*; do
        [ -e "$d" ] || continue
        case "${d##*/}" in vendor) continue ;; esac
        cp -R "$d" "$prev/$_sd/"
      done
      [ -f "$real/$_sd/.gitignore" ] && cp "$real/$_sd/.gitignore" "$prev/$_sd/.gitignore"
    fi
  done
  if [ -e "$real/.claude/plugins" ]; then
    mkdir -p "$prev/.claude"
    cp -R "$real/.claude/plugins" "$prev/.claude/plugins"
  fi
  if [ -f "$real/.claude/settings.json" ]; then
    mkdir -p "$prev/.claude"
    cp "$real/.claude/settings.json" "$prev/.claude/settings.json"
  fi
  # The repository-root .gitignore: manage_sidecar_gitignore appends to it, so the sandbox
  # needs the consumer's real bytes for the diff to show what the append would do to THEIR
  # file (an absent one is simply absent here, which is what the apply path would see).
  #
  # The SHAPE is mirrored, not just the bytes, because that function refuses a .gitignore
  # that is not a plain regular file. Copy a regular file (or a symlink AS a symlink, with
  # `-P`, so a link stays a link) and reproduce a directory as an empty directory —
  # otherwise the sandbox would have no .gitignore at all, the sandbox apply would create
  # one, and the preview would report an `ADD .gitignore` the real apply then declines.
  # A preview that OVERstates is the mirror image of the defect issue #971 fixes.
  #
  # `-P` does mean an ABSOLUTE-target link is reproduced pointing at the same real file
  # outside the sandbox. That is inert, and the reason is the refusal above, not this copy:
  # manage_sidecar_gitignore declines EVERY symlink, so the sandbox run reaches no write
  # through it — and it declines for the same reason on both sides, which is exactly the
  # preview/apply agreement this mirroring exists to produce. Dereferencing into a regular
  # file here would break that agreement in the dangerous direction: the sandbox copy would
  # be writable, so the preview would advertise a MODIFY the real apply refuses to perform.
  if [ -d "$real/.gitignore" ] && [ ! -L "$real/.gitignore" ]; then
    mkdir -p "$prev/.gitignore"
  elif [ -e "$real/.gitignore" ] || [ -L "$real/.gitignore" ]; then
    cp -P "$real/.gitignore" "$prev/.gitignore"
  fi
}

# ── The one apply path ──────────────────────────────────────────────────────
# Every write this installer performs happens here, and the dry run performs it too —
# against a sandbox. A SUBSHELL function, so the `cd` cannot move the resolution base
# of anything outside it and every path below stays the repo-relative literal it has
# always been.
#
# $4 is the tree to SCAN for language markers, and it exists only because the sandbox is
# not the repository (issue #971). The sandbox carries the installer's own subtrees, so
# detection run against it finds no
# package.json / composer.json / docker-compose* and reports "no known language markers
# detected", while the same step under `--apply` sees the real tree and merges that
# project's toolchain into config.json — a dry run that UNDERSTATES what the apply writes.
# Empty (the apply path) means "the tree being written", which is the historical
# behaviour; the dry run passes the real repository root. Only the SCAN moves: every write
# still lands under $1, which is what keeps a preview a preview.
devflow_apply_all() (
  cd "$1" || die "could not enter $1"
  local pin="$2" ref="$3" scan="${4:-}" withheld tier1_rc=0

  # 0. The ATOMIC Tier-1 migration (issue #1002), before anything else writes.
  #    A consumer whose tree is still the superseded layout must be relocated
  #    WHOLE — state directory, workflow contents, marketplace source, version pin —
  #    before the copy loop refreshes workflows or the scaffolder touches the config,
  #    because either of those against a half-moved tree is the silently-denied state
  #    the migration exists to prevent. The helper is a strict no-op on a tree that
  #    is already migrated or has nothing to migrate, so this costs a fresh install
  #    nothing. Same helper /prflow:init calls, so the two entry points cannot drift.
  if [ -x "$SRC/scripts/migrate-consumer-tier1.sh" ]; then
    "$SRC/scripts/migrate-consumer-tier1.sh" --apply --pin "$pin" "$PWD" || tier1_rc=$?
  elif [ -d .devflow ]; then
    # Only a tree that ACTUALLY carries the superseded layout is stranded by a missing
    # helper. Failing closed here for a repository with nothing to migrate would strand
    # every first-time install behind a file it never needed.
    tier1_rc=2
    log "warning: scripts/migrate-consumer-tier1.sh is missing from the source tree, and this repository still carries a superseded .devflow/ state directory; the Tier 1 migration could not run."
  else
    log "no superseded .devflow/ state directory here; the Tier 1 migration has nothing to do."
  fi

  # 1. Plugin tree. Thin by default — the vendor-plugin composite action puts it
  #    in the workspace at runtime, so it need not be committed. DEVFLOW_VENDOR=1
  #    commits it instead (self-hosting). Both paths copy through the ONE shared
  #    slice definition, so the file set can never drift between installer and CI.
  if [ "${DEVFLOW_VENDOR:-}" = "1" ]; then
    log "vendoring plugin → .prflow/vendor/prflow/ (DEVFLOW_VENDOR=1)"
    devflow_copy_slice "$SRC" ".prflow/vendor/prflow"
  else
    log "thin install: the plugin is fetched at runtime (set DEVFLOW_VENDOR=1 to commit it instead)"
  fi

  # Upgrade migration: remove a stale committed tree at the old .claude/plugins/devflow
  # location (relocated to .prflow/vendor/prflow). Runs for both install modes.
  prune_stale_vendored_plugin

  # 2. Root marketplace manifest so `plugin_marketplaces: ./` resolves the vendored
  #    plugin. Composed from the BAKED canonical identifiers, never hand-spelled, so a
  #    declared rename reaches it without this heredoc being re-edited. Rendered to a
  #    temp file and installed through the managed-artifact path, so a consumer who
  #    added their own plugin entry to it is not silently overwritten.
  log "composing .claude-plugin/marketplace.json"
  cat > "$TMP/marketplace.json" <<JSON
{
  "\$schema": "https://anthropic.com/claude-code/marketplace.schema.json",
  "name": "$DEVFLOW_MARKETPLACE_CANONICAL",
  "description": "Local marketplace for the vendored PRFlow plugin (.prflow/vendor/prflow). Installed by prflow/install.sh.",
  "owner": { "name": "Daniel Radman", "email": "daniel@radman.ai" },
  "allowCrossMarketplaceDependenciesOn": [],
  "plugins": [
    {
      "name": "$DEVFLOW_PLUGIN_CANONICAL",
      "source": "./.prflow/vendor/prflow",
      "description": "End-to-end dev workflow: /prflow:implement, /prflow:review + /prflow:review-and-fix, the /prflow:docs suite, /prflow:create-issue, plus the retrospective loop.",
      "author": { "name": "Daniel Radman", "email": "daniel@radman.ai" },
      "homepage": "https://github.com/The01Geek/prflow",
      "category": "development"
    }
  ]
}
JSON
  mkdir -p .claude-plugin
  install_managed ".claude-plugin/marketplace.json" "$TMP/marketplace.json"

  # 2b. Prompt-extension directory. Created empty so a maintainer who wants to extend a
  # skill has somewhere to commit the file without hand-creating the path, and so the
  # review job's unconditional truncation step (issue #874) has a directory to write
  # into on a fresh consumer. That step creates the directory itself as well — this is
  # a convenience for the human, not the workflow's guarantee, which cannot depend on
  # install.sh having run.
  log "creating .prflow/prompt-extensions"
  mkdir -p .prflow/prompt-extensions

  # 3. Workflows (only those the primary repo actually ships).
  #
  # The automatic pull-request-triggered review tier is WITHHELD from this release
  # (issue #936) and is therefore not installed: none of devflow-review.yml,
  # devflow-runner.yml or telemetry-push.yml is copied. That tier triggered on
  # pull-request events, called a reusable workflow with `secrets: inherit`, checked
  # out the pull-request head, and carried no actor-authorization gate; issues #930
  # and #920 describe the open defects. The always-available review path is a
  # repository collaborator commenting `/devflow:review` on a pull request, which
  # devflow.yml authorizes through scripts/authorize-actor.sh; a consumer can
  # additionally opt into an automatic CI-green request with the documented snippet
  # in docs/internal/workflow-triggers.md (issue #990).
  #
  # A repository that already installed those three files KEEPS them —
  # prune_stale_devflow_workflows() is deliberately not extended to remove them, so
  # an existing installation's auto-review keeps working (and stays exposed to #930
  # and #920 while its `workflows["prflow-review"]` config key is true). The upgrade
  # path SURFACES that exposure (devflow_report_withheld_tier) and removes the tier
  # only on the explicit --remove-withheld-review-tier opt-in; docs/internal/workflow-triggers.md
  # gives the full procedure, including the branch-protection step no installer can do.
  log "installing workflows + composite actions"
  mkdir -p .github/workflows .github/actions
  # SHARED FATE with the Tier-1 migration above (issues #988, #1002). Ordering alone
  # does not help: the copy loop would happily refresh both workflows and leave them
  # reading a state directory the refused migration never moved — exactly the split
  # the migration is all-or-nothing to prevent. So the write is CONDITIONAL on the
  # migration having succeeded, and the skip says why.
  if [ "$tier1_rc" -ne 0 ]; then
    log "NOT refreshing the shipped workflow files: the Tier 1 migration did not complete (see its refusal above), and installing workflows that name the migrated layout against an un-migrated tree would leave every bundled-helper invocation unresolvable. Resolve the refusal and re-run."
  else
  for w in devflow devflow-implement; do
    [ -f "$SRC/.github/workflows/$w.yml" ] && install_managed ".github/workflows/$w.yml" "$SRC/.github/workflows/$w.yml"
  done
  fi
  # Drop PRFlow's superseded claude*.yml on upgrade (signature-guarded so an
  # Anthropic-owned claude.yml is never touched).
  prune_stale_devflow_workflows
  # The withheld auto-review tier: reported always, removed only on the opt-in.
  withheld="$(devflow_withheld_tier_present)"
  devflow_report_withheld_tier "$withheld"
  devflow_remove_withheld_tier "$withheld"
  # The out-of-repo DEVFLOW_* freeze (issue #1004). Reads the install-state global rather
  # than re-probing, so the preview and the apply report identically.
  devflow_report_env_identifier_freeze "${DEVFLOW_INSTALL_STATE:-}"

  # 4. Composite actions. vendor-plugin is REQUIRED even for a thin install — the
  #    workflows reference `./.github/actions/vendor-plugin` to materialize the
  #    plugin at runtime, so it (unlike the plugin tree) must always be committed.
  for a in read-project-config setup-project-env vendor-plugin; do
    if [ -d "$SRC/.github/actions/$a" ]; then
      install_managed ".github/actions/$a" "$SRC/.github/actions/$a"
    fi
  done

  # 4b. Lint provisioning (issue #1388). Publish the compatibility marker LAST, only
  #     after the staged manifest validates — reordering breaks the fail-closed tuple
  #     gate. Digest the TARGET root: install_managed preserves a locally modified
  #     artifact and the tier1_rc arm skips the workflow copy, so binding either to
  #     source bytes it never received refuses provisioning forever. --digest-root is
  #     the exception: the vendor-fetched readers are absent from this tree yet.
  if [ -f "$SRC/.prflow/lint-manifest.json" ] && [ -f "$SRC/scripts/install_state.py" ]; then
    install_managed ".prflow/lint-manifest.json" "$SRC/.prflow/lint-manifest.json"
    if python3 "$SRC/scripts/lint_manifest.py" "$SRC/.prflow/lint-manifest.json" >/dev/null 2>&1; then
      if lint_state_err="$(python3 "$SRC/scripts/install_state.py" build \
          --out ".prflow/install-state.json" \
          --installer-version "$pin" \
          --repo-root "$PWD" \
          --component "manifest=.prflow/lint-manifest.json" \
          --component "manifest-reader=scripts/lint_manifest.py" \
          --component "lint-provision=scripts/lint_provision.py" \
          --component "install-state-reader=scripts/install_state.py" \
          --component "setup-action=.github/actions/setup-project-env/action.yml" \
          --component "provision-helper=.github/actions/setup-project-env/provision-lint-tools.sh" \
          --component "implement-workflow=.github/workflows/devflow-implement.yml" \
          --digest-root "manifest-reader=$SRC" \
          --digest-root "lint-provision=$SRC" \
          --digest-root "install-state-reader=$SRC" \
          --record-path "manifest-reader=.prflow/vendor/prflow/scripts/lint_manifest.py" \
          --record-path "lint-provision=.prflow/vendor/prflow/scripts/lint_provision.py" \
          --record-path "install-state-reader=.prflow/vendor/prflow/scripts/install_state.py" \
          2>&1 >/dev/null)"; then
        log "published .prflow/install-state.json (lint provisioning compatibility marker)"
      else
        log "warning: could not publish .prflow/install-state.json (${lint_state_err:-no diagnostic}); lint provisioning will fail closed (setup refuses provisioning without the marker) until the installer is re-run."
      fi
    else
      log "warning: .prflow/lint-manifest.json did not validate; NOT publishing the install-state marker (fail-closed: setup will refuse lint provisioning)."
    fi
  else
    log "warning: this source tree carries no .prflow/lint-manifest.json or scripts/install_state.py; NOT publishing the install-state marker (fail-closed: setup will refuse lint provisioning)."
  fi

  # 5. config scaffold — delegated to the ONE shared scaffolder so the cloud tier
  #    and the /devflow:init skill can never drift. It never overwrites a value the
  #    user has set (it only backfills keys newly added to the example) and always
  #    refreshes config.schema.json. Templates resolve relative to the script
  #    ($SRC/.prflow), and we target the current repo root.
  #
  #    The second argument is the language-detection SCAN root (issue #971). An empty
  #    value selects the target root, so the apply path is byte-for-byte what it was;
  #    the dry run hands over the real repository so its preview of the detection step
  #    matches what the apply would write.
  bash "$SRC/scripts/scaffold-config.sh" "$PWD" "$scan"

  # 5b. Gitignore the runtime-vendored tree for thin installs (and un-ignore it for
  #     DEVFLOW_VENDOR=1, which commits it). Runs after scaffold so .prflow/.gitignore exists.
  manage_vendor_gitignore

  # 5c. Ignore the preserved-artifact sidecars an upgrade writes, so an untracked
  #     `<path>.prflow-new` can never be swept into a consumer commit (issue #970).
  #     Independent of install mode — a sidecar is written on both.
  manage_sidecar_gitignore

  # 6. Pin prflow_version to the exact commit we installed from, so the runtime
  #    fetch is reproducible and never tracks mutable main. Re-running the
  #    installer re-stamps it when eligible (see set_config_version above for the
  #    empty/SHA-shape rule — a hand-set non-SHA value is preserved, not
  #    re-stamped); a maintainer can also bump it by hand to any tag, branch, or
  #    SHA.
  set_config_version ".prflow/config.json" "$pin"

  # 7. Record what we installed, so the NEXT upgrade can tell an untouched artifact
  #    from a hand-edited one instead of clobbering both alike.
  devflow_write_manifest "$pin" "$ref"

  # 8. Report (never rewrite) a consumer settings file still carrying a superseded
  #    plugin/marketplace identifier.
  devflow_report_superseded_identifiers

  # 9. Same detect-and-route split for .prflow/config.json: report (never rewrite) a
  #    superseded identifier the add-only scaffolder above cannot correct, and route the
  #    consumer to /devflow:init, which owns that correction.
  devflow_report_stale_config_identifiers

  # 10. Report (never repair) a workflow-read/config-key skew the per-file refresh above
  #     can create when a hand-edited shipped workflow is preserved (issue #1041). Runs
  #     LAST, so it reads the workflows and the config in their final post-run state.
  devflow_warn_enable_key_skew
)

# When sourced by the test harness (DEVFLOW_SELFTEST=1), define the functions
# above and stop — the installer body below (which clones + writes files) does
# not run. `return` only executes on the sourced path; `|| true` keeps `set -e`
# happy on the unlikely executed-with-the-flag path.
if [ "${DEVFLOW_SELFTEST:-}" = "1" ]; then return 0 2>/dev/null || true; fi

# ── Installer body ──────────────────────────────────────────────────────────
# Argument parsing lives HERE, below the DEVFLOW_SELFTEST return: sourced by the test
# harness, `"$@"` would be the sourcing script's own positional parameters.
DEVFLOW_MODE_REQUEST=""            # "", dry-run, or apply
REMOVE_WITHHELD="${DEVFLOW_REMOVE_WITHHELD_REVIEW_TIER:-}"
[ "${DEVFLOW_DRY_RUN:-}" = "1" ] && DEVFLOW_MODE_REQUEST=dry-run
[ "${DEVFLOW_APPLY:-}" = "1" ] && DEVFLOW_MODE_REQUEST=apply
for _arg in "$@"; do
  case "$_arg" in
    --dry-run) DEVFLOW_MODE_REQUEST=dry-run ;;
    --apply) DEVFLOW_MODE_REQUEST=apply ;;
    --remove-withheld-review-tier) REMOVE_WITHHELD=1 ;;
    *)
      # A typo must not silently select the writing mode. `--dryrun` is not `--dry-run`.
      printf 'devflow-install: unknown argument %s (accepted: --dry-run, --apply, --remove-withheld-review-tier)\n' "$_arg" >&2
      exit 2
      ;;
  esac
done

command -v git >/dev/null 2>&1 || die "git is required."
[ -d .git ] || die "run this from the root of a git repository."

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# The source tree. DEVFLOW_SRC points at an already-materialized plugin tree and skips
# the clone entirely — the offline seam the test suite (network-free, gh-stubbed) drives
# real end-to-end upgrades through, and the same escape hatch for an air-gapped install.
if [ -n "${DEVFLOW_SRC:-}" ]; then
  [ -d "$DEVFLOW_SRC" ] || die "DEVFLOW_SRC is set to '$DEVFLOW_SRC' but that is not a directory."
  SRC="$DEVFLOW_SRC"
  log "using the pre-materialized source tree at $SRC (DEVFLOW_SRC; no clone)"
else
  log "fetching ${REPO}@${REF} …"
  # Fast path: shallow clone of a branch/tag. Fallback: full clone + checkout,
  # which is what resolves a commit SHA (--branch rejects SHAs). Without the
  # fallback's checkout, a SHA ref would silently land on the default branch and
  # we'd pin prflow_version to the wrong commit. rm -rf before the fallback so a
  # cleaned-up-or-not partial first attempt never blocks the reclone. stderr is
  # suppressed ONLY on the --branch attempt (a SHA legitimately fails it, and that
  # expected failure must stay quiet); the fallback clone and checkout each
  # capture their stderr so a genuine failure reports its real cause, and a failed
  # checkout after a successful clone is distinguishable from a total clone failure.
  CLONE_URL="https://github.com/${REPO}.git"
  if ! git clone --quiet --depth 1 --branch "$REF" "$CLONE_URL" "$TMP/src" 2>/dev/null; then
    rm -rf "$TMP/src"
    if ! CLONE_ERR="$(git clone --quiet "$CLONE_URL" "$TMP/src" 2>&1)"; then
      die "could not clone $CLONE_URL (ref: ${REF}) — clone failed: $CLONE_ERR"
    fi
    if ! CHECKOUT_ERR="$(git -C "$TMP/src" checkout --quiet "$REF" 2>&1)"; then
      die "could not clone $CLONE_URL (ref: ${REF}) — clone succeeded but checkout failed: $CHECKOUT_ERR"
    fi
  fi
  SRC="$TMP/src"
fi

# The ONE shared slice definition, sourced so the installer and CI can never disagree
# about which files are the plugin.
# shellcheck source=.github/actions/vendor-plugin/vendor-slice.sh
DEVFLOW_VENDOR_SOURCE=1 . "$SRC/.github/actions/vendor-plugin/vendor-slice.sh"

# Pin prflow_version to the exact commit we installed from, so the runtime fetch is
# reproducible and never tracks mutable main. The clone+checkout above gives $SRC a
# resolvable HEAD, so this essentially always yields a SHA; only a broken clone (or a
# DEVFLOW_SRC tree that is not a git repository) falls back to $REF — warn there, since
# $REF may be a mutable branch (the very thing the pin exists to avoid).
if PIN="$(git -C "$SRC" rev-parse HEAD 2>/dev/null)"; then :; else
  PIN="$REF"
  log "warning: could not resolve the installed commit SHA; pinning prflow_version=$PIN (if that is a mutable branch, set it to a tag or SHA by hand to freeze the runtime fetch)."
fi

# ── First install vs UPGRADE, and therefore apply vs dry-run ────────────────
# An UPGRADE is any repository already carrying something this installer owns. The
# predicate is deliberately a union over the artifacts, not a manifest lookup: an
# installation that predates the manifest, or one whose manifest a consumer deleted,
# is still an upgrade and must not be treated as a green field.
#
# A first install APPLIES (the documented one-liner is unchanged and there is nothing to
# destroy). An upgrade is DRY-RUN BY DEFAULT and needs --apply, because there is.
DEVFLOW_INSTALL_STATE="a first-time"
for _probe in .prflow/config.json .devflow/config.json .claude-plugin/marketplace.json \
              .github/workflows/devflow.yml .github/workflows/devflow-implement.yml \
              "$DEVFLOW_MANIFEST_PATH"; do
  if [ -e "$_probe" ]; then DEVFLOW_INSTALL_STATE="an existing"; break; fi
done
case "$DEVFLOW_INSTALL_STATE:$DEVFLOW_MODE_REQUEST" in
  *:apply)            MODE=apply ;;
  *:dry-run)          MODE=dry-run ;;
  "a first-time:")    MODE=apply ;;
  *)                  MODE=dry-run ;;
esac
log "detected ${DEVFLOW_INSTALL_STATE} installation; running in ${MODE} mode."

if [ "$MODE" = dry-run ]; then
  # The preview runs the REAL apply path against a sandbox copy of this repository, then
  # diffs the sandbox against it. There is no second implementation of the plan to drift.
  PREVIEW="$TMP/preview"
  devflow_build_preview "$PWD" "$PREVIEW"
  log "───── dry run: the plan ─────"
  # The 4th argument is the language-detection scan root (issue #971): the sandbox carries
  # only the installer's own subtrees, so detection must read the REAL repository to
  # preview what --apply would merge into config.json. It is a read; every write the call
  # makes still goes to $PREVIEW.
  devflow_apply_all "$PREVIEW" "$PIN" "$REF" "$PWD"
  log "───── dry run: the diff ─────"
  devflow_render_preview "$PWD" "$PREVIEW"
  log "DRY RUN — nothing in this repository was written. Re-run with --apply to make the changes above."
  exit 0
fi

devflow_apply_all "$PWD" "$PIN" "$REF"

# On a host with no `python3` (stock Windows / Git-Bash), offer the consent-gated shim
# provisioner so the toolchain can resolve a Python 3 interpreter. No-op where python3
# works, and never run under a dry run (it is an interactive offer, not a plan step).
offer_python3_shim "$SRC"

log "done (from ${REPO}@${REF}). Review with 'git status' / 'git diff' and commit."
