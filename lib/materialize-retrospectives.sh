#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# materialize-retrospectives.sh <new-entries-file> <jsonl-path>
#
# Merges new JSONL entries into the retrospectives file idempotently.
# For each new entry: if an existing entry has the same .repo, .pr AND .kind,
# REPLACE it in place; otherwise APPEND at the end. The key is repo-qualified so
# a Radman-LLC#N record does not clobber a same-numbered The01Geek#N record.
# When a new-entries file exists, every object record, stored or new, that names
# no repository first gains the run's repository (devflow_resolve_repo, resolved only
# when such a record exists); an unresolvable repository exits non-zero with the
# store unchanged.
# Writes to a temp file and only replaces $2 after validation passes.
#
# Output: "materialized: appended <N>, replaced <M>"

set -euo pipefail

# jq binary: resolved once via the sourced sibling resolver (issue #247);
# best-effort — a copied/vendored deployment without lib/ falls back to bare
# `jq` with a breadcrumb rather than aborting under set -e.
# shellcheck source=resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/resolve-jq.sh" \
  || { echo "prflow: resolve-jq.sh could not be sourced beside ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }

if [ "$#" -ne 2 ]; then
    echo "Usage: materialize-retrospectives.sh <new-entries-file> <jsonl-path>" >&2
    exit 1
fi

NEW_FILE="$1"
JSONL_PATH="$2"

# Early exit if new-entries file doesn't exist (every analyzed subagent failed).
if [ ! -f "$NEW_FILE" ]; then
    echo "materialized: appended 0, replaced 0"
    exit 0
fi

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
# Populate temp with existing content; an absent store starts empty and is only
# created by the final mv, so a failed merge leaves no store behind.
if [ -f "$JSONL_PATH" ]; then cp "$JSONL_PATH" "$TMP"; fi

APP=0
REP=0

# Redact operator home-directory paths before merge (issue #672), in ONE
# streaming jq pass over the new-entries file. This is the single deterministic
# choke point: it fires on every merged record regardless of which of the three
# producers (clean-entry.jq, the Stage A subagent, the inline skip marker)
# emitted it, so no per-producer instruction is relied on. Every string VALUE is
# rewritten via walk (keys and non-string types are left untouched, so .pr/.kind
# — numeric/enum — survive and the merge key still resolves). CLAUDE.md
# guard-class 2: this transform decides an emitted result, so it is expressed
# through the resolved $DEVFLOW_JQ, never a non-preflight PATH tool (sed/tr/cut/wc)
# that would fail open by writing the unredacted line. The /home/runner(admin)?
# carve-out preserves GitHub-Actions runner paths, which identify no person and
# carry the friction the record exists to describe. A per-file pass (rather than
# a jq fork per record inside the loop) is equivalent because redaction is
# per-record-independent and touches only values.
#
# The fallback FAILS CLOSED, not open. A raw copy on any jq failure would commit
# UNREDACTED operator paths whenever jq errors for a reason OTHER than malformed
# input — a jq build lacking the Oniguruma regex features this filter uses (named
# capture, negative lookahead), or a single gsub-hostile record (e.g. an invalid
# UTF-8 string) poisoning the whole-file pass. The post-merge JSONL validation
# only gates JSON validity, never redaction, so it cannot backstop that leak. So
# on a redaction failure whose input is itself VALID JSONL — the committable case
# — abort rather than write the unredacted corpus (the guard is a privacy
# boundary; guard-class 2). Malformed input exits here too, naming the malformed
# file, because the repository check below would otherwise fail on it with a
# misdirecting message. The jq stderr is surfaced on both arms, never swallowed,
# so the operator sees WHY redaction could not run.
REDACTED="$(mktemp)"
trap 'rm -f "$TMP" "$REDACTED"' EXIT
if ! REDACT_ERR="$("$DEVFLOW_JQ" -c '
        def redact_home:
          gsub("(?<d>^|[^A-Za-z0-9_])/Users/(?!runner(admin)?/)[^/\\s\"]+/"; "\(.d)~/")
          | gsub("(?<d>^|[^A-Za-z0-9_])/home/(?!runner(admin)?/)[^/\\s\"]+/"; "\(.d)~/")
          | gsub("[A-Za-z]:\\\\Users\\\\[^\\\\\\s\"]+\\\\"; "~\\");
        walk(if type == "string" then redact_home else . end)' "$NEW_FILE" 2>&1 1>"$REDACTED")"; then
    if "$DEVFLOW_JQ" -c . "$NEW_FILE" >/dev/null 2>&1; then
        echo "materialize: redaction pass failed on VALID JSONL (jq: ${REDACT_ERR}); refusing to commit an unredacted corpus" >&2
        exit 1
    fi
    echo "materialize: new-entries file is not valid JSONL (jq: ${REDACT_ERR}); store unchanged" >&2
    exit 1
fi

# Stamp the store copy BEFORE the match loop: the merge key includes .repo, so an
# unstamped stored record would never match its re-analysed entry and the PR would
# end up with two records. Unlike _stamped_record in scripts/migrate-record-repo.py, a record that names a
# repository is left as it is (pr_key and schema_version included), and an
# integral JSON number such as 76.0 counts as an integer pr.
STAMP_FILTER='def needs: type == "object" and ((.repo | strings) // "") == "";'
NEED_STORE="$("$DEVFLOW_JQ" -n "$STAMP_FILTER"' [inputs | select(needs)] | length' "$TMP")" \
    || { echo "materialize: the store is not valid JSONL; store unchanged" >&2; exit 1; }
NEED_NEW="$("$DEVFLOW_JQ" -n "$STAMP_FILTER"' [inputs | select(needs)] | length' "$REDACTED")" \
    || { echo "materialize: the redacted new entries are not valid JSONL; store unchanged" >&2; exit 1; }
NEED_STORE="${NEED_STORE//$'\r'/}"
NEED_NEW="${NEED_NEW//$'\r'/}"
if [ "$NEED_STORE" != "0" ] || [ "$NEED_NEW" != "0" ]; then
    # shellcheck source=repo-identity.sh
    . "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/repo-identity.sh" \
        || { echo "materialize: could not resolve the repository: repo-identity.sh could not be sourced; store unchanged" >&2; exit 1; }
    REPO="$(devflow_resolve_repo)" \
        || { echo "materialize: could not resolve the repository to give records that name none; store unchanged" >&2; exit 1; }
    STAMPED="$(mktemp)"
    trap 'rm -f "$TMP" "$REDACTED" "$STAMPED"' EXIT
    for _f in "$TMP" "$REDACTED"; do
        if [ "$_f" = "$TMP" ]; then _label="the store"; else _label="the new entries"; fi
        _out="$("$DEVFLOW_JQ" -c --arg repo "$REPO" "$STAMP_FILTER"'
            if needs
            then .repo = $repo
                 | (if (.pr | type) == "number" and .pr == (.pr | floor)
                    then .pr_key = ($repo + "#" + (.pr | floor | tostring)) else del(.pr_key) end)
                 | .schema_version = 4
            else . end' "$_f")" \
            || { echo "materialize: could not give records in ${_label} the repository '${REPO}'; store unchanged" >&2; exit 1; }
        _out="${_out//$'\r'/}"
        if [ -n "$_out" ]; then printf '%s\n' "$_out" > "$STAMPED"; else : > "$STAMPED"; fi
        cp "$STAMPED" "$_f"
    done
    rm -f "$STAMPED"
    trap 'rm -f "$TMP" "$REDACTED"' EXIT
    if [ "$NEED_STORE" != "0" ]; then
        echo "materialize: gave ${NEED_STORE} stored record(s) that named no repository the repository '${REPO}'" >&2
    fi
fi

# A native Windows jq.exe writes CRLF; JSON escapes a real CR, so any raw CR is that
# translation and is dropped to keep the committed JSONL LF-only (#1050).
while IFS= read -r line; do
    line="${line%$'\r'}"
    [ -z "$line" ] && continue

    # As JSON text, so a string pr reaches --argjson quoted rather than bare.
    pr="$("$DEVFLOW_JQ" -c '.pr' <<<"$line")"
    kind="$("$DEVFLOW_JQ" -r '.kind' <<<"$line")"
    # Repo-qualified match key: a bare pr+kind key lets a Radman-LLC#N record
    # delete the same-numbered The01Geek#N record from another repo.
    repo="$("$DEVFLOW_JQ" -c '.repo' <<<"$line")"

    # Check if an entry with same repo, pr and kind already exists
    # Do NOT suppress jq errors here: a malformed dataset should fail loudly
    # rather than producing a spurious empty $existing and appending a duplicate.
    existing="$("$DEVFLOW_JQ" -c --argjson pr "$pr" --arg kind "$kind" --argjson repo "$repo" \
        'select(type=="object" and .repo==$repo and .pr==$pr and .kind==$kind)' "$TMP")"

    if [ -n "$existing" ]; then
        # Replace in place — run per-line through jq substituting the match
        NEW_TMP="$(mktemp)"
        # shellcheck disable=SC2064
        trap "rm -f '$NEW_TMP' '$TMP' '$REDACTED'" EXIT
        # The first match takes the entry; later matches are dropped, so the PR
        # ends with one record of this kind.
        _replaced="$("$DEVFLOW_JQ" -nc --argjson pr "$pr" --arg kind "$kind" --argjson repo "$repo" --argjson repl "$line" \
            'foreach inputs as $r ({seen: false};
                if ($r|type)=="object" and $r.repo==$repo and $r.pr==$pr and $r.kind==$kind
                then .emit = (.seen | not) | .val = $repl | .seen = true
                else .emit = true | .val = $r end;
                select(.emit) | .val)' "$TMP")"
        printf '%s\n' "${_replaced//$'\r'/}" > "$NEW_TMP"
        mv "$NEW_TMP" "$TMP"
        # Restore trap to only clean $TMP/$REDACTED now that $NEW_TMP is gone (renamed to $TMP)
        trap 'rm -f "$TMP" "$REDACTED"' EXIT
        REP=$((REP + 1))
    else
        printf '%s\n' "$line" >> "$TMP"
        APP=$((APP + 1))
    fi
done < "$REDACTED"

# Validate the merged result
if ! "$DEVFLOW_JQ" -c . "$TMP" > /dev/null 2>&1; then
    echo "materialize: invalid JSONL after merge" >&2
    rm -f "$TMP"
    exit 1
fi

mv "$TMP" "$JSONL_PATH"
echo "materialized: appended $APP, replaced $REP"
