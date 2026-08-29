#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# repo-identity.sh — sourceable; the single owner of repository identity for the
# retrospective record stores.
#
# Every record in .prflow/learnings/{retrospectives,experiment-records}.jsonl and
# every meta-issue entry in overrides.json stores a bare GitHub number. A number
# is only meaningful beside the repository it was issued in: once PRFlow
# development moves to a second repository, that repository's #7 and the previous
# one's #7 are different work. This helper owns the three answers that keeps
# them apart:
#
#   devflow_resolve_repo             the repository the current run acts on
#   devflow_record_repo              a record's OWN repository (strict)
#   devflow_apply_legacy_record_repo the one-time compatibility rule
#   devflow_pr_key                   the canonical "<owner>/<name>#<number>" key
#
# The canonical record shape is the `repo` field beside the existing bare number,
# with `pr_key` as the derived comparison key. Numbers are kept for compatibility;
# nothing compares on a number alone.
#
# This file is SOURCED into the caller's shell and therefore deliberately sets no
# shell options: a `set -euo pipefail` here would leak into a caller that sources
# it. Every function validates its own operands and returns a status.

# jq binary: resolved once via the sourced sibling resolver (issue #247).
# shellcheck source=resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/resolve-jq.sh" \
  || { echo "devflow: resolve-jq.sh could not be sourced beside ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }

# gh binary: resolved once via the single-source resolver (execution-verified);
# an explicit DEVFLOW_GH still wins, so test stubs are untouched.
# shellcheck source=resolve-gh.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/resolve-gh.sh"
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"

DEVFLOW_REPO_IDENTITY_FILE="${DEVFLOW_REPO_IDENTITY_FILE:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/repo-identity.json}"

# devflow_repo_slug_ok <value> — true when <value> is a bare `owner/name` slug.
# Builtin-only: this decides whether a value may be handed to `gh --repo`, and a
# missing non-preflight PATH tool would silently accept anything (guard-class 2).
devflow_repo_slug_ok() {
    local v="${1:-}"
    case "$v" in
        ''|*/*/*|/*|*/) return 1 ;;
        */*) : ;;
        *) return 1 ;;
    esac
    case "$v" in *[!A-Za-z0-9._/-]*) return 1 ;; esac
    return 0
}

# devflow_legacy_record_repo — print the repository every pre-qualification record
# belongs to. Fails CLOSED: an unreadable identity file must not silently degrade
# into an empty legacy repo, which would let every repo-less record bind to "".
devflow_legacy_record_repo() {
    local v
    v="$("$DEVFLOW_JQ" -r '.legacy_record_repo // ""' "$DEVFLOW_REPO_IDENTITY_FILE" 2>/dev/null)" || v=""
    if ! devflow_repo_slug_ok "$v"; then
        echo "::error::repo-identity: ${DEVFLOW_REPO_IDENTITY_FILE} yielded no usable legacy_record_repo (got '${v}') — refusing to bind repo-less records to an empty repository" >&2
        return 1
    fi
    printf '%s\n' "$v"
}

# devflow_resolve_repo [explicit-slug] — print the `owner/name` this run acts on.
#
# Rungs, in order: the optional explicit argument (a caller's own `--repo`), then
# GITHUB_REPOSITORY (set by Actions), then `gh repo view`. Every rung's value must
# be a well-formed slug.
#
# The explicit override is an ARGUMENT, never an environment variable. DEVFLOW_REPO
# already means "the repository to fetch the PLUGIN from" (vendor-slice.sh,
# install.sh), so reading it here would let a consumer who vendors from a fork
# silently stamp that fork as their own repository identity — the exact wrong-repo
# binding this file exists to prevent.
#
# An unresolvable repository is a BLOCKER, not an empty string: a caller that
# received "" would build `repos//issues/...` paths, an empty processed-history key
# set, or a `--repo ''` that gh resolves from the ambient git remote — each of which
# reads a DIFFERENT repository than the one the run believes it is acting on.
devflow_resolve_repo() {
    local v="" explicit="${1:-}"
    if [ -n "$explicit" ]; then
        if ! devflow_repo_slug_ok "$explicit"; then
            echo "::error::repo-identity: the explicit repository '${explicit}' is not an <owner>/<name> slug — refusing to act on an unestablished repository" >&2
            return 1
        fi
        printf '%s\n' "$explicit"; return 0
    fi
    if [ -n "${GITHUB_REPOSITORY:-}" ]; then
        v="$GITHUB_REPOSITORY"
    else
        v="$("$DEVFLOW_GH" repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)" || v=""
        v="${v//[$' \t\r\n']/}"
    fi
    if ! devflow_repo_slug_ok "$v"; then
        echo "::error::repo-identity: could not resolve the current repository (got '${v}'); pass an explicit repository, set GITHUB_REPOSITORY, or authenticate gh. Refusing to continue: an unresolved repository would silently read and write a different repository's numbers." >&2
        return 1
    fi
    printf '%s\n' "$v"
}

# devflow_record_repo <stored-repo> — print a record's OWN repository.
#
# STRICT by design: a record that names no repository is UNESTABLISHED, and this
# function refuses rather than substituting the current repository. Binding a
# repo-less record to whichever repository happens to be current is exactly the
# cross-repository collision this shape exists to prevent. The one permitted
# substitution is devflow_apply_legacy_record_repo below, which callers reach
# deliberately.
devflow_record_repo() {
    local v="${1:-}"
    [ "$v" = "null" ] && v=""
    if ! devflow_repo_slug_ok "$v"; then
        echo "::error::repo-identity: this record names no usable repository (got '${v}') — refusing to bind it to the current repository; run scripts/migrate-record-repo.py to stamp the legacy corpus" >&2
        return 1
    fi
    printf '%s\n' "$v"
}

# devflow_apply_legacy_record_repo <stored-repo> — the ONE-TIME compatibility rule.
#
# Prints <stored-repo> when the record names one, else the legacy record repository
# from lib/repo-identity.json. This is the ONLY sanctioned way a repo-less record
# acquires a repository, and it never consults the current repository.
devflow_apply_legacy_record_repo() {
    local v="${1:-}"
    [ "$v" = "null" ] && v=""
    if devflow_repo_slug_ok "$v"; then
        printf '%s\n' "$v"; return 0
    fi
    devflow_legacy_record_repo
}

# devflow_pr_key <repo> <number> — the canonical comparison key.
# Fails CLOSED on either operand: a malformed key silently matches nothing, which
# a processed-history filter reads as "never retrospected" and re-queues.
devflow_pr_key() {
    local repo="${1:-}" num="${2:-}"
    if ! devflow_repo_slug_ok "$repo"; then
        echo "::error::repo-identity: devflow_pr_key received a non-slug repository ('${repo}')" >&2
        return 1
    fi
    case "$num" in
        ''|*[!0-9]*)
            echo "::error::repo-identity: devflow_pr_key received a non-numeric number ('${num}')" >&2
            return 1 ;;
    esac
    printf '%s#%s\n' "$repo" "$num"
}
