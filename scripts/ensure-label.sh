#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# ensure-label.sh <name> — idempotently ensure a GitHub label exists.
#
# Creates the label (with a description) when it is absent; treats an
# "already exists" outcome as success. This is a best-effort provenance step:
# it ALWAYS exits 0 — whether it created the label, the label already existed,
# or the underlying `gh` call failed (no auth, offline, rate-limited) — so a
# label hiccup can never abort the caller (create-issue / implement / Stage B /
# init). It still leaves a specific stderr breadcrumb naming which of the three
# happened, so a real failure is visible rather than silently swallowed.
#
# Creation goes through the REST endpoint
#   POST /repos/{owner}/{repo}/labels
# via `gh api`, whose `{owner}`/`{repo}` placeholders `gh` fills from the git
# remote on BOTH tiers, WITHOUT the org-scoped GraphQL
# resolution `gh label create` triggers — so a repo-scoped token (GitHub App
# installation token, or a fine-grained `repo`-only PAT, neither carrying
# `read:org`) creates labels successfully.
set -uo pipefail

# gh binary: resolved once via the single-source resolver (execution-verified);
# an explicit DEVFLOW_GH still wins, so test stubs are untouched.
# shellcheck source=../lib/resolve-gh.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/resolve-gh.sh"
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"
# `${1:-}`, NOT `${1:?}` — the same reasoning apply-labels.sh carries, and it binds here for the
# same reason (the #480 review): a `${1:?}` aborts with a raw bash usage line and rc 1, which
# breaks this helper's own "ALWAYS exits 0" contract AND emits an outcome that matches none of the
# three its callers route on (`created` / `already exists` / `warning: …`) — nor the "no output at
# all ⇒ the harness refused it" arm. It fires on a set-but-EMPTY argument too, which is exactly the
# shape the label call sites can emit (`ensure-label.sh ""` when a configured label list normalizes
# to a blank). Name the arg-slip and exit 0, so a refusal stays the ONLY silent outcome.
NAME="${1:-}"
if [ -z "$NAME" ]; then
    echo "devflow: warning: ensure-label.sh got an empty label name (args: $*); no label ensured. This is NOT a harness denial — it is a caller arg-slip (an empty label literal, or a variable that did not survive into this command)." >&2
    exit 0
fi

# Capture both streams so we can distinguish "already exists" (benign) from a
# genuine failure (no auth / network / API error) and emit the right breadcrumb.
# An existing label comes back as an HTTP 422 whose response body carries the
# specific error code `already_exists`, rather than `gh label create`'s plain-text
# message — so the REST-era benign-outcome signal is that `already_exists` token. The
# match below keeps the two legacy plain-text phrases (`already exists` / `already
# been taken`) as defense-in-depth, but `already_exists` is the load-bearing one for
# the REST body. It deliberately does NOT match a bare `HTTP 422`: a 422 for a
# *different* validation reason (e.g. a malformed label name) must route to the
# failure breadcrumb, not be silently swallowed as "already exists". The match is a
# bash `case` (no `grep`): `grep` is not a preflight-guaranteed tool, so a grep-less
# host must not misreport a benign already-exists as a failure.
ERR_OUT="$("$DEVFLOW_GH" api --method POST "repos/{owner}/{repo}/labels" -f "name=$NAME" -f "description=Created by PRFlow automation" 2>&1)"
RC=$?

if [ "$RC" -eq 0 ]; then
    echo "devflow: created label '$NAME'" >&2
else
    case "$ERR_OUT" in
        *already_exists*|*"already exists"*|*"already been taken"*)
            echo "devflow: label '$NAME' already exists" >&2 ;;
        *)
            echo "devflow: warning: could not ensure label '$NAME' (best-effort, continuing): ${ERR_OUT}" >&2 ;;
    esac
fi

exit 0
