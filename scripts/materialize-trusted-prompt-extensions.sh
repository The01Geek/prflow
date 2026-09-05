#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# materialize-trusted-prompt-extensions.sh — populate the review tier's trusted
# prompt-extension closure from the base ref (issue #874).
#
# Why a helper rather than inline workflow shell: this script IS the branch
# selection and the ::warning:: composition, and a silently mis-selected arm
# misattributes a security-relevant diagnosis while the review job still "works".
# Inline shell inside YAML cannot be unit-tested; here lib/test/run.sh drives every
# arm directly. Same rationale, and the same all-bash-builtin selection discipline,
# as scripts/describe-denial-count.sh.
#
# CONTRACT WITH THE CALLER. The caller fetches the base ref and invokes this ONLY
# from inside that fetch's success branch, because FETCH_HEAD elsewhere (e.g. left
# by actions/checkout) can point at the PR HEAD — the same trust rule every sibling
# closure in .github/workflows/devflow-runner.yml carries. This script performs no
# fetch of its own and resolves no ref but FETCH_HEAD.
#
# Usage: materialize-trusted-prompt-extensions.sh --base-ref REF --target DIR NAME...
#   --base-ref REF  the base ref the caller fetched. An EMPTY value means the base
#                   ref's content was never established; no FETCH_HEAD path is read
#                   and the not-attempted notice is emitted instead.
#   --target DIR    the closure directory to populate. The caller creates it
#                   unconditionally, so this script never creates it: an absent or
#                   unwritable target is a reportable failure, not something to
#                   self-heal.
#   NAME...         the protected skill names, passed explicitly by the caller so the
#                   protected set has a single declaration site the drift guard in
#                   lib/test/run.sh can compare against.
#
# STDOUT carries the fully-formed workflow-command lines (`::warning::` / `::notice::`)
# and nothing else, so the caller re-emits nothing and selects nothing — the branch
# selection this helper exists to own cannot leak back into the YAML. STDERR carries
# only the usage errors below, which exit 2; no runtime arm writes an intentional
# diagnostic to it. One residual: a per-name redirect that cannot be opened at all
# (a directory at $dest) is reported by the shell on the real stderr before the
# read's own `2>/dev/null` applies — that is the shell's message, not this helper's.
#
# Exit codes:
#   0  every runtime condition — the four per-name arms of the branch table below and
#      the not-attempted arm alike. Populating is the only thing this script does, so
#      its failures degrade to an EMPTY closure, which is already the safe state the
#      caller established unconditionally — there is no fail-open direction a non-zero
#      exit would need to escalate against.
#   2  a usage error (a missing or unrecognized flag, no --target, no names). That is
#      a caller defect, not a runtime condition, so it is refused loudly.
#
# THE BYTE-IDENTITY RULE — do not "clean this up" into the sibling pattern. Every
# read is a DIRECT REDIRECT. The `_floor_raw=$(git show …)` + `printf '%s\n' "$VAR"`
# shape used by every other trusted-closure materialization in devflow-runner.yml
# strips all trailing newlines and re-adds exactly one, which would silently corrupt
# an extension carrying no trailing newline. lib/test/run.sh `cmp`s the materialized
# file against the base-ref source over a no-trailing-newline fixture and a UTF-8-BOM
# fixture, so a regression to that shape turns the suite RED rather than shipping.
# (Those arms compare source-to-materialized, not the two write shapes against each
# other — the protection is that the sibling shape cannot satisfy them.)
#
# THE ABSENCE RULE — `git show` exits 128 for a path absent at the ref AND for a
# corrupt object, an unresolvable FETCH_HEAD, and a dubious-ownership refusal, so
# exit 128 alone cannot license silence. Absence is established POSITIVELY: the ref
# must resolve AND `git cat-file -e` must report the object missing. Anything else is
# a read failure and gets a reason-naming warning, because "the consumer committed no
# extension" is the ordinary shape and warning on it would put a ::warning:: on every
# review run in every repository that never opted in.

set -uo pipefail

BASE_REF=''
TARGET=''
NAMES=()

while [ "$#" -gt 0 ]; do
    case "$1" in
        --base-ref)
            [ "$#" -ge 2 ] || { echo "materialize-trusted-prompt-extensions.sh: --base-ref requires a value" >&2; exit 2; }
            BASE_REF="$2"; shift 2 ;;
        --target)
            [ "$#" -ge 2 ] || { echo "materialize-trusted-prompt-extensions.sh: --target requires a value" >&2; exit 2; }
            TARGET="$2"; shift 2 ;;
        --*)
            echo "materialize-trusted-prompt-extensions.sh: unrecognized argument '$1'" >&2; exit 2 ;;
        *)
            NAMES+=("$1"); shift ;;
    esac
done

if [ -z "$TARGET" ]; then
    echo "materialize-trusted-prompt-extensions.sh: --target is required" >&2
    exit 2
fi
if [ "${#NAMES[@]}" -eq 0 ]; then
    echo "materialize-trusted-prompt-extensions.sh: at least one protected skill name is required" >&2
    exit 2
fi

# The base ref's content was never established. Read no FETCH_HEAD path and say only
# that — a reason-naming warning here would assert whether an extension exists on a
# ref this run never read.
if [ -z "$BASE_REF" ]; then
    printf '%s\n' "::notice::devflow trusted prompt-extension materialization was not attempted (the base ref is empty, so its content was never established); the reviewing agent runs with no extension text"
    exit 0
fi

# One up-front probe rather than a per-name retry: an unusable target makes every
# name fail for the same reason, and repeating the diagnosis once per name would bury
# it. Probe by WRITING, not by `-w`: a read-only filesystem and a restrictive ACL both
# pass `-w` while the redirect still fails, and the redirect is the operation whose
# outcome this warning stands in for.
if ! ( : > "$TARGET/.prflow-mtpe-probe" ) 2>/dev/null; then
    printf '%s\n' "::warning::devflow trusted prompt-extension closure not populated: the target directory '$TARGET' is not writable; the reviewing agent runs with no extension text"
    exit 0
fi
rm -f "$TARGET/.prflow-mtpe-probe" 2>/dev/null || true

# Does FETCH_HEAD resolve at all? Established once, because it is the operand that
# separates "absent at the base ref" (silent) from "the read failed" (warned), and it
# is a property of the repository rather than of any one name.
FETCH_HEAD_RESOLVES=no
if git rev-parse --verify --quiet 'FETCH_HEAD^{commit}' >/dev/null 2>&1; then
    FETCH_HEAD_RESOLVES=yes
fi

for name in "${NAMES[@]}"; do
    # Refuse a traversal-shaped name rather than trusting the caller: the composed
    # path would otherwise leave the closure entirely. The workflow passes literals,
    # so this can only fire on a caller defect — which is exactly when a silent
    # escape would be least visible.
    case "$name" in
        */* | *..* | '')
            printf '%s\n' "::warning::devflow trusted prompt-extension materialization refused an invalid protected extension name '$name' (a name must not be empty or contain '/' or '..'); no file was materialized for it"
            continue
            ;;
    esac

    # TRANSITIONAL DIRECTORY-RENAME READ-THROUGH (issue #170): resolve the canonical
    # .prflow/skill-extensions/ path at the TRUSTED BASE REF, falling back to superseded
    # prompt-extensions/ only when the canonical one is not a blob there — bytes from the
    # base ref, never the PR head. END CRITERION (confirmation-gated): removed with the
    # loader read-through once no consumer carries a .prflow/prompt-extensions/ directory.
    src=".prflow/skill-extensions/${name}.md"
    _src_old=".prflow/prompt-extensions/${name}.md"
    # Both sides are blob-typed so a TREE at the canonical leaf path (a directory literally
    # named "<name>.md") does not suppress the fallback to a valid old-path blob — matching
    # the old-path test's own `= blob` check and the "not a blob there" comment above.
    if [ "$FETCH_HEAD_RESOLVES" = yes ] \
        && [ "$(git cat-file -t "FETCH_HEAD:$src" 2>/dev/null || printf 'unknown')" != blob ] \
        && [ "$(git cat-file -t "FETCH_HEAD:$_src_old" 2>/dev/null || printf 'unknown')" = blob ]; then
        src="$_src_old"
    fi
    dest="$TARGET/${name}.md"

    # A TREE at this path is not an extension. `git show` exits 0 on one and prints a
    # tree listing, which would land non-extension text in the closure for the loader
    # to `cat` into the reviewing agent's prompt — the loader's own non-regular-file
    # guard covers this shape on the filesystem side, and this is its object-side
    # counterpart. Gated on the object POSITIVELY EXISTING at a resolvable ref, so an
    # absent object and an unresolvable ref still fall through to the read/absence
    # discrimination below rather than being misreported as a wrong-type object.
    if [ "$FETCH_HEAD_RESOLVES" = yes ] && git cat-file -e "FETCH_HEAD:$src" 2>/dev/null \
        && [ "$(git cat-file -t "FETCH_HEAD:$src" 2>/dev/null || printf 'unknown')" != blob ]; then
        printf '%s\n' "::warning::devflow trusted prompt-extension '$name' exists on the trusted base ref '$BASE_REF' but is not a regular file (blob); nothing was materialized for it and the reviewing agent runs with no extension text for it"
        continue
    fi

    # Direct redirect — see THE BYTE-IDENTITY RULE above.
    if git show "FETCH_HEAD:$src" > "$dest" 2>/dev/null; then
        continue
    fi

    # The redirect created the target before the read ran, so a failed read leaves a
    # zero-length file. Remove it: an empty file in the closure is indistinguishable
    # from an extension the consumer deliberately committed empty.
    rm -f "$dest" 2>/dev/null || true

    if [ "$FETCH_HEAD_RESOLVES" = yes ] && ! git cat-file -e "FETCH_HEAD:$src" 2>/dev/null; then
        # Absence established positively: the ref resolves and the object is missing.
        # The ordinary extension-less consumer — silent by design.
        continue
    fi

    printf '%s\n' "::warning::devflow trusted prompt-extension '$name' could not be read from the trusted base ref '$BASE_REF' for a reason other than the object being absent; the reviewing agent runs with no extension text for it"
done

# TRANSITIONAL SKILL-RENAME WARNING (issue #152). When the trusted base ref still
# carries the superseded receiving-code-review.md extension, the loader's read-through
# serves it for the renamed `fix` skill — warn the consumer to rename it. Fires only
# when the old path exists as a BLOB at the base ref (a tree there is not an extension,
# so no warning), matching the read-through's own deliverability. Removed together with
# the loader read-through once no consumer still carries a receiving-code-review.md.
# Check the receiving-code-review.md under BOTH the canonical skill-extensions/ and the
# superseded prompt-extensions/ directory (issue #170), since a consumer may have migrated
# the directory but not the file (or vice versa). The FIRST that is a blob at the base ref
# is warned about; the fix.md target is named under the same directory the old file sits in.
for _mtpe_dir in .prflow/skill-extensions .prflow/prompt-extensions; do
    _mtpe_old_ext="${_mtpe_dir}/receiving-code-review.md"
    if [ "$FETCH_HEAD_RESOLVES" = yes ] \
        && [ "$(git cat-file -t "FETCH_HEAD:$_mtpe_old_ext" 2>/dev/null || printf 'unknown')" = blob ]; then
        printf '%s\n' "::warning::devflow: the trusted base ref '$BASE_REF' still carries the superseded prompt extension '$_mtpe_old_ext'; the receiving-code-review skill was renamed to fix, so rename it to ${_mtpe_dir}/fix.md (the loader reads it through transitionally)"
        break
    fi
done

exit 0
