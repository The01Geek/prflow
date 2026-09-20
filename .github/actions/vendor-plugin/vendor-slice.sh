#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# ============================================================================
# vendor-slice.sh — materialize the PRFlow plugin into the workspace
# ============================================================================
# The cloud-tier workflows reference plugin helpers at the literal workspace
# path `.prflow/vendor/prflow/…`. This script puts the plugin there at RUNTIME
# so the tree no longer has to be committed into a consumer repo. It is the ONE
# definition of "which files are the plugin" — install.sh sources it for the
# shared `devflow_copy_slice` function (see DEVFLOW_VENDOR_SOURCE below), and the
# vendor-plugin composite action executes it — so the copied set can never drift.
#
# Executed (the composite action), it follows a single deterministic algorithm,
# committed then fetch:
#   1. committed  — `.prflow/vendor/prflow/scripts` already in the checkout → use it (no-op).
#   2. fetch      — any other checkout → clone DEVFLOW_REF from DEVFLOW_REPO and copy it in.
# The fetch branch refuses to run without a pinned ref, so a thin consumer never
# silently tracks mutable `main`. The former copy-the-checkout branch is gone: the
# source repo itself is fetched too (its config names its own repository), so the
# clone, the ref pin, and the diagnostics are exercised here as in a consumer.
#
# Environment (all optional unless noted):
#   DEVFLOW_REF        git ref to fetch (REQUIRED on the fetch branch); a branch,
#                      tag, or commit SHA. Sourced from .prflow/config.json
#                      `prflow_version` by the workflows.
#   DEVFLOW_REPO       owner/name to fetch from (default The01Geek/prflow); sourced
#                      from .prflow/config.json `prflow_repo` by the workflows.
#   DEVFLOW_TOKEN      credential for the fetch clone. When non-empty the clone runs
#                      with a one-shot git credential helper answering username
#                      x-access-token and this token as the password, so a private or
#                      fork repository can be fetched. Empty → clone with no credential.
#   DEVFLOW_REPO_URL   full clone URL (default https://github.com/$DEVFLOW_REPO.git);
#                      overridable so tests can clone a local fixture offline.
#   DEVFLOW_DEST       destination dir (default .prflow/vendor/prflow); overridable for tests.
#   DEVFLOW_VENDOR_SOURCE=1  define functions and return WITHOUT running — for `source`rs.
# ============================================================================
set -euo pipefail

devflow_vendor_log() { printf 'devflow-vendor: %s\n' "$1"; }
devflow_vendor_die() { printf 'devflow-vendor: %s\n' "$1" >&2; exit 1; }

# Report which branch materialized the plugin: committed | fetch.
# Security consumers key TRUST on this — the deny-list floor in
# devflow-runner.yml executes the vendored filter helper ONLY on `fetch` (a
# fresh clone of the trusted base-ref-config repository at the pinned ref, made
# this run); a `committed` copy comes from the checked-out — possibly PR-head —
# tree and is never trusted as floor code (the PR-#404 REJECT finding). Written to
# $GITHUB_OUTPUT when running under the composite action; log-only otherwise
# (install.sh / tests source this file without GITHUB_OUTPUT).
devflow_vendor_report_source() {
  devflow_vendor_log "vendor source: $1"
  if [ -n "${GITHUB_OUTPUT:-}" ]; then
    echo "vendor_source=$1" >> "$GITHUB_OUTPUT"
  fi
}

# The single shared "what is the plugin" definition. Mirrors the file set
# install.sh has always vendored. SRC = a checkout/clone root; DEST = where the
# plugin lands. Stages into a sibling temp dir and swaps in with one atomic `mv`
# at the very end: $dest is only ever touched once the full slice copied cleanly,
# so a partial copy (a removed/renamed slice dir aborting cp under set -e, disk
# full) never lands at $dest — where the committed-branch check would otherwise
# mask it as a valid plugin on the next run.
devflow_copy_slice() {
  local src="$1" dest="$2" stage
  stage="${dest}.vendor-stage.$$"
  rm -rf "$stage"
  mkdir -p "$stage"
  cp -R "$src/.claude-plugin" "$src/agents" "$src/docs" "$src/lib" "$src/scripts" "$src/skills" "$src/LICENSES" "$stage/"
  # Only the committed templates/registry — not the whole .prflow/ tree (which
  # would drag in learnings/ and a possibly-dirty config.json).
  mkdir -p "$stage/.prflow"
  # The lint manifest and its digest-bound compatibility marker ship (issue #1388):
  # the setup action's provisioning phase reads .prflow/lint-manifest.json and gates
  # on .prflow/install-state.json, so a consumer that lacks them cannot provision.
  cp "$src/.prflow/config.example.json" "$src/.prflow/config.schema.json" \
     "$src/.prflow/tool-presets.json" "$src/.prflow/lint-manifest.json" \
     "$src/.prflow/install-state.json" \
     "$stage/.prflow/"
  # The vendored copy is a plugin, not a marketplace — keep only plugin.json.
  rm -f "$stage/.claude-plugin/marketplace.json"
  find "$stage" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
  # Prune subtrees no consumer run reaches (issue #677): the published GitHub
  # Pages HTML under docs/site and the Mintlify source under docs/external (both
  # standalone published sites), all of PRFlow's maintainer documentation under
  # docs/internal (issue #1188 — #1190 removed the last shipped skill-body link
  # into this same maintainer tree while it still lived directly under docs/, so
  # nothing a consumer executes references it; pruning it here stops
  # that reference tree shipping into every consumer and, because
  # lint-shipped-pruned-path.py derives its forbidden set from these rm arguments,
  # arms that lint against reintroduction), and PRFlow's own test suite
  # under lib/test (it asserts against install.sh and
  # .github/, which the slice does not copy, so it could only fail loudly in a
  # consumer tree). Placed after cp -R and before the sanity floor so the floor
  # evaluates the tree that actually ships; the whole $stage is rm -rf'd on any
  # floor failure, so this can never leave a partially-pruned tree at $dest (a
  # $stage orphan is still possible if this rm itself aborts — install.sh's sourced
  # copy has no $stage trap — but that never lands at $dest). Like the marketplace.json/
  # __pycache__ prunes above, rm -rf is a no-op on an absent path. It is left
  # unguarded, so an unexpected rm error aborts loudly under set -e — the preferred
  # fail direction here; the __pycache__ prune instead suppresses all errors
  # (2>/dev/null || true) to stay best-effort, while marketplace.json's rm -f is
  # likewise unguarded against an unexpected error, differing only in that -f
  # ignores a missing file.
  rm -rf "$stage/docs/site" "$stage/docs/external" "$stage/docs/internal" "$stage/lib/test"
  # No documentation is part of the runtime plugin slice after issue #1188. Remove
  # the staging root itself so an ignored/private or newly-added docs subtree cannot
  # silently start shipping merely because it was outside the explicit policy prunes
  # above. Keep those rm arguments explicit: lint-shipped-pruned-path.py derives its
  # forbidden set from them. `find -depth -delete` is supported by both BSD/macOS and
  # GNU find; unlike a best-effort rmdir, any traversal/deletion error remains non-zero
  # and aborts under set -e before the atomic swap.
  find "$stage/docs" -depth -delete
  # Sanity floor before the swap: the load-bearing members must have landed.
  if [ ! -d "$stage/scripts" ] || [ ! -f "$stage/.claude-plugin/plugin.json" ] \
     || [ ! -f "$stage/.prflow/config.schema.json" ] || [ ! -d "$stage/LICENSES" ]; then
    rm -rf "$stage"
    devflow_vendor_die "incomplete plugin slice copied from $src (missing scripts/, plugin.json, .prflow templates, or LICENSES/) — refusing to install a partial copy."
  fi
  rm -rf "$dest"
  mkdir -p "$(dirname "$dest")"
  mv "$stage" "$dest"
}

# Run the fetch clones. The empty `-c credential.helper=` reset MUST precede the
# snippet, or the runner image's own helper (osxkeychain / Git Credential Manager)
# answers first; the snippet names $DEVFLOW_TOKEN, so the token reaches no argument or log.
devflow_vendor_git() {
  if [ -n "${DEVFLOW_TOKEN:-}" ]; then
    git -c credential.helper= \
        -c 'credential.helper=!f() { echo username=x-access-token; echo "password=$DEVFLOW_TOKEN"; }; f' \
        "$@"
  else
    git "$@"
  fi
}

# Committed-branch advisory only: compare the committed copy's plugin.json version
# against the configured DEVFLOW_REF (prflow_version) and surface drift as a GitHub
# Actions annotation. Log-only — never gates vendor_source, execution, or exit code.
# Every failure mode of the guarded python3 read collapses to ONE ::notice:: carrying
# `unreadable`; a mismatch against a v<d>.<d>.<d>-shaped ref is a ::warning::; every
# other comparable ref (a branch, a SHA, empty) is a ::notice::. Called ONLY from the
# committed branch — the fetch branch already selected DEVFLOW_REF, so comparing there
# would be vacuous (AC8). Under the file-top `set -euo pipefail` the python3 read is
# caught with `|| ver=''` so a read failure never aborts the committed branch before
# devflow_vendor_report_source runs. The comparison uses only bash builtins
# (parameter expansion, `[[ =~ ]]`, string equality) — no jq/sed/cut decides the
# emitted annotation (CLAUDE.md's non-preflight-PATH-tool rule).
devflow_vendor_report_version_drift() {
  local dest="$1" ref="${DEVFLOW_REF:-}" ver ref_bare
  if ! command -v python3 >/dev/null 2>&1; then
    printf '::notice::devflow-vendor: committed plugin.json version is unreadable (no python3 on PATH); skipping the vendor-version drift check.\n'
    return 0
  fi
  ver="$(DEVFLOW_VENDOR_PLUGIN_JSON="$dest/.claude-plugin/plugin.json" python3 -c '
import json, os, sys
sys.stdout.reconfigure(newline="\n")
try:
    with open(os.environ["DEVFLOW_VENDOR_PLUGIN_JSON"], encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    sys.exit(1)
if not isinstance(data, dict):
    sys.exit(1)
v = data.get("version")
if not isinstance(v, str) or v == "":
    sys.exit(1)
sys.stdout.write(v)
' 2>/dev/null)" || ver=''
  if [ -z "$ver" ]; then
    printf '::notice::devflow-vendor: committed plugin.json version is unreadable (missing file, malformed JSON, non-string version, or python3 failed); skipping the vendor-version drift check.\n'
    return 0
  fi
  ref_bare="${ref#v}"
  if [ "$ref_bare" = "$ver" ]; then
    return 0
  fi
  if [[ "$ref_bare" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    printf '::warning::devflow-vendor: the committed plugin copy is version %s, but prflow_version (DEVFLOW_REF) is pinned to %s — the committed copy is used, not %s.\n' \
      "$ver" "$ref" "$ref"
  else
    local shown="$ref"
    [ -n "$shown" ] || shown='(empty)'
    printf '::notice::devflow-vendor: using the committed plugin copy version %s; DEVFLOW_REF is %s and is not consulted while a committed copy exists.\n' \
      "$ver" "$shown"
  fi
}

devflow_vendor_main() {
  local dest="${DEVFLOW_DEST:-.prflow/vendor/prflow}"

  # 1. committed branch — a consumer that committed the plugin (self-hosting).
  if [ -d "$dest/scripts" ]; then
    devflow_vendor_log "plugin already present at $dest — using the committed copy."
    devflow_vendor_report_version_drift "$dest"
    devflow_vendor_report_source committed
    return 0
  fi

  # 2. fetch branch — every other checkout (thin consumer AND the source repo);
  #    clone the pinned ref from the configured repository and copy it in.
  [ -n "${DEVFLOW_REF:-}" ] || devflow_vendor_die \
    "no plugin in the checkout and DEVFLOW_REF (config prflow_version) is unset — refusing to track mutable main. Set .prflow/config.json prflow_version to a tag, branch, or commit SHA."
  local repo url tmp
  repo="${DEVFLOW_REPO:-The01Geek/prflow}"
  # Validate the repository BEFORE any git command — a malformed prflow_repo must
  # fail with a named diagnostic, never reach git as a bad clone URL.
  if [[ ! "$repo" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
    devflow_vendor_die "prflow_repo value '$repo' is not owner/name (must match ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\$) — refusing to clone."
  fi
  url="${DEVFLOW_REPO_URL:-https://github.com/${repo}.git}"
  tmp="$(mktemp -d)"
  # shellcheck disable=SC2064
  trap "rm -rf '$tmp'" EXIT
  devflow_vendor_log "fetch: cloning $url @ $DEVFLOW_REF"
  # Fast path: shallow clone of a branch/tag. Fallback: full clone + checkout,
  # which also resolves a commit SHA (which --branch cannot take). Mirrors the
  # clone fallback install.sh uses. stderr is suppressed ONLY on the --branch
  # attempt — a SHA legitimately fails it, and that expected failure must stay
  # quiet. The fallback clone and checkout each capture their stderr so a
  # genuine fetch failure reports its real cause (auth, network, not-found,
  # rate-limit) instead of a generic message, and a failed checkout after a
  # successful clone is distinguishable from a total clone failure. Both clones
  # carry the credential helper (via devflow_vendor_git); the checkout is local.
  local clone_err checkout_err token_state
  if ! devflow_vendor_git clone --quiet --depth 1 --branch "$DEVFLOW_REF" "$url" "$tmp/src" 2>/dev/null; then
    rm -rf "$tmp/src"
    if ! clone_err="$(devflow_vendor_git clone --quiet "$url" "$tmp/src" 2>&1)"; then
      # An authentication failure (GitHub answers a private repo the token cannot
      # read with "Repository not found") is reported as a credential problem
      # naming prflow_repo and the token input, not a generic clone failure.
      case "$clone_err" in
        *"could not read Username"*|*"Authentication failed"*|*"Repository not found"*)
          token_state="$( [ -n "${DEVFLOW_TOKEN:-}" ] && echo 'non-empty' || echo 'empty' )"
          devflow_vendor_die "could not fetch prflow_repo '$repo' @ $DEVFLOW_REF — authentication failed (the token input was $token_state; a private repository needs a token that can read it, supplied as the PRFLOW_REPO_TOKEN secret). git reported: $clone_err" ;;
      esac
      devflow_vendor_die "could not fetch $url @ $DEVFLOW_REF — clone failed: $clone_err"
    fi
    if ! checkout_err="$(git -C "$tmp/src" checkout --quiet "$DEVFLOW_REF" 2>&1)"; then
      devflow_vendor_die "could not fetch $url @ $DEVFLOW_REF — clone succeeded but checkout failed: $checkout_err"
    fi
  fi
  devflow_copy_slice "$tmp/src" "$dest"
  devflow_vendor_report_source fetch
}

# Sourced (install.sh, tests) → expose the functions and stop. Executed (the
# composite action) → run the algorithm.
if [ "${DEVFLOW_VENDOR_SOURCE:-}" = "1" ]; then return 0 2>/dev/null || true; fi
devflow_vendor_main "$@"
