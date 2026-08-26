#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# resolve-gh.sh — PRFlow's GitHub-CLI (`gh`) selection contract, sourced by
# lib/preflight.sh and every gh-calling shell helper. Since issue #247 the
# generic detect-and-verify mechanics live in lib/resolve-bin.sh (the shared
# execution-verified resolver, extracted from this file); devflow_resolve_gh is
# a thin delegation kept as its own file because every gh-calling helper and
# ~15 tests source resolve-gh.sh by name.
#
# The contract is unchanged from #245: an explicit, non-empty DEVFLOW_GH wins
# outright WITHOUT any probe (DEVFLOW_GH is exactly the override name
# devflow_resolve_bin derives for "gh", so the test suite's stubbing contract
# is preserved); otherwise the first of the candidates gh, gh.exe that both
# resolves (`command -v`) AND actually executes (`gh --version` — network- and
# auth-free) is echoed, rejecting a present-but-unrunnable shim; if neither
# runs, bare `gh` is echoed with a stderr breadcrumb naming the DEVFLOW_GH
# remedy. Candidates are referenced by name only — no absolute or
# owner-specific install path is ever hardcoded. Always returns rc 0.
#
# Defines a function only; it deliberately does NOT set -e/-u so it is safe to
# source into a caller with its own shell options (preflight runs `set -u`, the
# helpers run `set -euo pipefail` / `set -uo pipefail`, and
# scripts/authorize-actor.sh — sourced itself — sets no options at all).

# Pure-bash DIRECTORY DERIVATION (no `dirname`): sourcing this file must
# succeed in a degenerate environment with only bash on PATH (the resolver
# family's degenerate-path tests). For gh (and every known tool) the
# override-variable derivation in resolve-bin.sh is pure bash too; only an
# UNKNOWN future tool's derivation consults `tr`, and that arm degrades with
# a breadcrumb rather than requiring it.
case "${BASH_SOURCE[0]}" in
  */*) _RESOLVE_GH_DIR="$(cd "${BASH_SOURCE[0]%/*}" && pwd)" ;;
  *)   _RESOLVE_GH_DIR="$(pwd)" ;;
esac
# Guarded source (matches lib/resolve-jq.sh's partial-copy posture): a
# deployment carrying this file without its sibling resolve-bin.sh degrades to
# DEVFLOW_GH-or-bare-gh with a breadcrumb instead of aborting every set -e
# gh-caller at source time.
# shellcheck source=resolve-bin.sh
if [ -f "$_RESOLVE_GH_DIR/resolve-bin.sh" ] \
   && . "$_RESOLVE_GH_DIR/resolve-bin.sh" \
   && type devflow_resolve_bin >/dev/null 2>&1; then
  # devflow_resolve_gh — echo the `gh` invocation PRFlow should use. See
  # lib/resolve-bin.sh for the full override/probe/fallback contract.
  devflow_resolve_gh() {
    devflow_resolve_bin gh
  }
else
  echo "devflow: resolve-bin.sh not found or not sourceable beside resolve-gh.sh — gh resolution degraded to DEVFLOW_GH-or-bare-gh" >&2
  devflow_resolve_gh() {
    printf '%s\n' "${DEVFLOW_GH:-gh}"
  }
fi
