#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# compose-filing-key.sh — compose a collision-resistant OPAQUE filing key from a
# category argument and a subslug argument (issue #891). The key is what a
# sub-pattern lifecycle record is stored under in overrides.json; the record's
# `category` field (not the key) carries the attribution category, so the key only
# has to be a stable, URL-safe, distinguishing identifier.
#
# Usage:
#   compose-filing-key.sh <category> <subslug>
#
# Contract:
#   - Canonicalizes the category and the subslug SEPARATELY through the shared
#     `slug_kebab` (the un-truncated half of lib/slugify.jq's `slugify`), so this
#     helper carries NO copy of the slugify body.
#   - Prints nothing and exits non-zero when either argument is absent, empty, or
#     canonicalizes to the empty string.
#   - Takes exactly three arms on a pair each non-empty after canonicalization:
#       1. the canonical composition `<cat>-<sub>` fits the 40-char ceiling → it is
#          printed whole (and is slugify-stable by construction);
#       2. it exceeds the ceiling → it is printed truncated with a deterministic
#          digest suffix (see DIGEST_WIDTH below);
#       3. the category's OWN canonical form exceeds the ceiling (>40 chars) → exit
#          non-zero with a named error and no stdout, because no subslug or digest
#          can fit beside it.
#   - The printed key is always <= 40 chars, matches `[a-z0-9-]+`, and is
#     byte-identical to its own `slugify` canonicalization (the final print runs
#     through `slugify`, an idempotent no-op on an already-canonical <=40 key).
#
# DIGEST_WIDTH (stated per the acceptance criterion): the digest suffix is the
# first 8 hex characters of the sha256 of the pre-truncation canonical composition.
# 8 hex chars = 32 bits reduces the collision rate over long inputs without
# eliminating it — two RESIDUAL collision sources remain by construction and are
# documented rather than asserted away: (a) `slug_kebab` is many-to-one over the
# argument grammar, so two argument pairs with equal canonicalized components
# collide before a digest is ever considered; (b) the 40-char output codomain is
# finite while the argument domain is not, so a digest narrows but cannot close the
# collision rate over arbitrarily long inputs.
#
# The digest is produced by `python3` with `hashlib` — never `sha256sum`, `shasum`,
# `md5`, or `cksum`, none of which lib/preflight.sh guarantees and jq offers no hash
# builtin for. The digest decides an EMITTED key, so a missing binary would empty
# the suffix and reinstate the collision this helper exists to reduce; python3 is a
# hard preflight prerequisite.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# jq binary: resolved once via the sourced sibling resolver (issue #247);
# best-effort — a copied/vendored deployment without lib/ falls back to bare
# `jq` with a breadcrumb rather than aborting under set -e.
# shellcheck source=resolve-jq.sh
. "$HERE/resolve-jq.sh" \
  || { echo "devflow: resolve-jq.sh could not be sourced beside ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }

# The composable ceiling and the digest width. Keep the two in step: the truncated
# prefix budget below is CEILING - 1 (the joining dash) - DIGEST_WIDTH.
_CEILING=40
_DIGEST_WIDTH=8

# ── Argument parsing: exactly two positional args, both non-empty ──────────────
if [ "$#" -ne 2 ]; then
    echo "compose-filing-key: expected exactly two arguments <category> <subslug> (got $#)" >&2
    exit 2
fi
CATEGORY="$1"
SUBSLUG="$2"
if [ -z "$CATEGORY" ] || [ -z "$SUBSLUG" ]; then
    echo "compose-filing-key: neither <category> nor <subslug> may be empty" >&2
    exit 2
fi

# ── Canonicalize each component separately (un-truncated), via the shared module.
# TWO separate jq calls, one per argument — deliberately NOT one call printing both
# on two lines: command substitution strips ALL trailing newlines, so a two-line
# emit whose SECOND line is empty (the subslug canonicalizes to "") collapses to a
# single line, and the `${_CANON#*$'\n'}` split then yields the whole (category)
# string for SUB_CANON instead of "", defeating the empty-canonicalization guard
# below and emitting a bogus `<cat>-<cat>` key (fail-open). A per-argument capture
# preserves an empty result as "" (jq -r prints "\n" for an empty string, which the
# substitution strips to ""). Bash-builtin capture only (no tr/cut/head — this value
# decides an EMITTED key).
CAT_CANON="$("$DEVFLOW_JQ" -r -n -L "$HERE" --arg cat "$CATEGORY" 'include "slugify"; $cat | slug_kebab')" \
  || { echo "compose-filing-key: could not canonicalize the category argument (jq exited non-zero)" >&2; exit 1; }
SUB_CANON="$("$DEVFLOW_JQ" -r -n -L "$HERE" --arg sub "$SUBSLUG" 'include "slugify"; $sub | slug_kebab')" \
  || { echo "compose-filing-key: could not canonicalize the subslug argument (jq exited non-zero)" >&2; exit 1; }

# Either canonicalizing to empty is a hard reject (no stdout).
if [ -z "$CAT_CANON" ] || [ -z "$SUB_CANON" ]; then
    echo "compose-filing-key: an argument canonicalized to the empty string (category='${CATEGORY}' → '${CAT_CANON}', subslug='${SUBSLUG}' → '${SUB_CANON}')" >&2
    exit 2
fi

# Arm 3: the category's own canonical form does not fit the ceiling, so no subslug
# or digest can sit beside it — reject rather than emit a key that is just a
# truncated category.
if [ "${#CAT_CANON}" -gt "$_CEILING" ]; then
    echo "compose-filing-key: the category's canonical form '${CAT_CANON}' (${#CAT_CANON} chars) exceeds the ${_CEILING}-char ceiling — cannot compose a distinguishing filing key" >&2
    exit 2
fi

_RAW="${CAT_CANON}-${SUB_CANON}"

# _print_stable <key> — print the key through slugify so the emitted value is
# byte-identical to its own canonicalization (idempotent on an already-canonical
# <=40 key; also the site that lets this helper "resolve slugify from the module").
_print_stable() {
    "$DEVFLOW_JQ" -r -n -L "$HERE" --arg k "$1" 'include "slugify"; $k | slugify'
}

if [ "${#_RAW}" -le "$_CEILING" ]; then
    # Arm 1: fits whole.
    _print_stable "$_RAW" \
      || { echo "compose-filing-key: could not canonicalize the composed key for output (jq exited non-zero)" >&2; exit 1; }
else
    # Arm 2: truncate to leave room for `-<digest>` and append a deterministic
    # digest of the FULL pre-truncation string. python3/hashlib only (see header).
    _DIGEST="$(python3 -c 'import hashlib,sys; sys.stdout.reconfigure(newline="\n"); print(hashlib.sha256(sys.argv[1].encode()).hexdigest()[:int(sys.argv[2])])' "$_RAW" "$_DIGEST_WIDTH")" \
      || { echo "compose-filing-key: could not derive the digest suffix via python3 (hashlib)" >&2; exit 1; }
    _PREFIX_BUDGET=$(( _CEILING - 1 - _DIGEST_WIDTH ))
    _PREFIX="${_RAW:0:$_PREFIX_BUDGET}"
    # Strip a trailing dash the truncation may have exposed so the join is a single
    # `-`, never `--`.
    _PREFIX="${_PREFIX%-}"
    _print_stable "${_PREFIX}-${_DIGEST}" \
      || { echo "compose-filing-key: could not canonicalize the composed key for output (jq exited non-zero)" >&2; exit 1; }
fi
