#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# apply-labels.sh <number> <label…>
# apply-labels.sh <number> --config-key <key> --config-fallback <value>
#
# Best-effort apply one or more labels to a GitHub issue or PR (a PR is an issue,
# so the same REST endpoint serves both). Labels come either as positional args
# (separate, comma-separated, or a mix) or — with `--config-key`/`--config-fallback`
# — resolved by the helper itself from `.prflow/config.json` (the caller names the
# key and its fallback; the helper reads config through scripts/config-get.sh, which
# probes for a superseded key and exits 2 on a missing python3). Either way the list
# is normalized with the same split-on-commas / trim / drop-empties idiom, each label
# is created if absent through the sibling ensure-label.sh, and the set is applied via
#   POST /repos/{owner}/{repo}/issues/{number}/labels
# through `gh api`, whose `{owner}`/`{repo}` placeholders `gh` fills from the git
# remote on BOTH tiers, WITHOUT the org-scoped GraphQL resolution that
# `gh issue edit`/`gh pr edit --add-label` trigger — so a repo-scoped token (GitHub
# App installation token, or a fine-grained `repo`-only PAT) applies labels
# successfully. It never falls back to porcelain: a failed REST call is logged and
# tolerated, not retried via `gh issue edit`/`gh pr edit`.
#
# OUTCOME CONTRACT (the closed set): the helper ALWAYS exits 0 (a label hiccup can
# never abort the caller) and prints exactly ONE outcome token to STDOUT on every
# path it runs, so the caller routes on that token instead of matching English
# stderr sentences:
#   * applied           — the labels were POSTed.
#   * nothing-to-apply  — the label set was empty/whitespace-only (no POST made).
#   * arg-slip          — a missing/non-numeric issue/PR number (a caller arg-slip).
#   * api-failure       — the apply POST failed (no auth, offline, rate-limited).
#   * config-unreadable — `--config-key` mode and config-get exited non-zero.
# NONE of these values contains the text "already exists" (that is ensure-label.sh's
# stderr breadcrumb, never a token). Detailed breadcrumbs still go to STDERR — every
# message ensure-label.sh and this helper emit is preserved byte-for-byte, so a human
# reading a log sees exactly what they see today.
#
# STDOUT carries ONLY the token; the API call's stdout and the internal ensure calls'
# stdout both go to /dev/null. A harness refusal produces NO output at all — the only
# outcome that yields no token — so the caller reads empty output as a refusal, not as
# a label result.
set -uo pipefail

# gh binary: resolved once via the single-source resolver (execution-verified);
# an explicit DEVFLOW_GH still wins, so test stubs are untouched.
_APPLY_LABELS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/resolve-gh.sh
. "$_APPLY_LABELS_DIR/../lib/resolve-gh.sh"
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"
# `${1:-}`, NOT `${1:?}`: a `${1:?}` aborts with a bash usage line and rc 1, which breaks the
# "ALWAYS exits 0" best-effort contract above and — worse — leaves the arg-slip guard below
# unreachable on the very shapes it exists to catch (the #480 review).
NUMBER="${1:-}"
[ "$#" -gt 0 ] && shift

# The number must be digits. This is a fail-CLOSED guard on the one caller mistake the skills
# explicitly warn about: a `$PR_NUM` that did not survive into a later command. Both spellings
# of that slip land here, and neither may be silent:
#   * UNQUOTED (`apply-labels.sh $PR_NUM PRFlow`) — the empty expansion word-splits away, so
#     `NUMBER` swallows the LABEL (`apply-labels.sh PRFlow`) and the label set comes out empty.
#   * QUOTED (`apply-labels.sh "$PR_NUM" PRFlow`) — no word-splitting: `NUMBER` is set-but-null
#     and the label survives. (This is why the number is read with `${1:-}` above: `${1:?}` would
#     have aborted here with rc 1 and a raw bash usage line instead of the breadcrumb below.)
# Callers read "no output at all" as a harness refusal, so a silent exit on either shape would
# produce a durable reflection blaming a permission denial that never happened — steering the
# reader away from the real cause (CLAUDE.md's "unknown is not zero"). No label is ever applied
# to issue "" — the helper refuses first. Emit the arg-slip token, breadcrumb loudly, exit 0.
case "$NUMBER" in
    ''|*[!0-9]*)
        echo "arg-slip"
        echo "devflow: warning: apply-labels.sh got a non-numeric issue/PR number '${NUMBER}' (args: $*); no labels applied. This is NOT a harness denial — it is a caller arg-slip, most likely a shell variable that did not survive into this command." >&2
        exit 0 ;;
esac

# Split the remaining args into flags (config-driven mode) and positional labels.
_CONFIG_KEY=""
_CONFIG_FALLBACK=""
_CONFIG_MODE=0
_POSITIONAL=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --config-key)      _CONFIG_MODE=1; _CONFIG_KEY="${2:-}";      shift; [ "$#" -gt 0 ] && shift ;;
        --config-fallback) _CONFIG_MODE=1; _CONFIG_FALLBACK="${2:-}"; shift; [ "$#" -gt 0 ] && shift ;;
        *)                 _POSITIONAL+=("$1"); shift ;;
    esac
done

# Resolve the label source. Config mode reads the list through config-get.sh (a preflight
# tool: python3), so a hard config read failure (corrupt config.json, missing python3 →
# config-get rc≠0) emits its own token rather than being misread as "no labels". A configured
# EMPTY string resolves to the caller's fallback inside config-get; a configured
# whitespace/separator-only value comes back verbatim and normalizes to nothing below.
if [ "$_CONFIG_MODE" -eq 1 ]; then
    if _CFG_RAW="$("$_APPLY_LABELS_DIR/config-get.sh" "$_CONFIG_KEY" "$_CONFIG_FALLBACK")"; then
        # Wrong-type guard (the six-shape config matrix's object/array row): config-get.sh
        # coerces a JSON OBJECT to the sentinel "[object Object]" and exits 0 — applied verbatim
        # that becomes a garbage label reported `applied`, a silent misconfiguration. coerce() is
        # element-wise inside a list, so a mixed array like ["Documented",{…}] resolves to
        # "Documented,[object Object]", not the bare sentinel; match the sentinel as a SUBSTRING
        # (not exact equality) so a non-scalar array element is caught too. A label list is a
        # string or an all-scalar array (config-get comma-joins it), never one containing an object.
        case "$_CFG_RAW" in
            *'[object Object]'*)
                echo "config-unreadable"
                echo "devflow: warning: apply-labels.sh: config key '${_CONFIG_KEY}' resolves to (or contains) a JSON object, not a label string/list; no labels applied. This is NOT a harness denial — fix the config value's shape." >&2
                exit 0 ;;
        esac
        set -- "$_CFG_RAW"
    else
        echo "config-unreadable"
        echo "devflow: warning: apply-labels.sh could not read config key '${_CONFIG_KEY}' (config-get exited non-zero — corrupt config.json or missing python3); no labels applied. This is NOT a harness denial." >&2
        exit 0
    fi
elif [ "${#_POSITIONAL[@]}" -gt 0 ]; then
    set -- "${_POSITIONAL[@]}"
else
    set --
fi

# Normalize the label source into a clean label list — split on commas, trim, drop empties.
# Accepts `PRFlow Retrospective` (separate args), `"PRFlow,Deferred"` (one
# comma-separated arg), or a mix.
#
# BASH BUILTINS ONLY — deliberately not a `tr | sed | grep` pipeline. This derivation decides
# BOTH which labels get POSTed (a selection) AND which token is emitted (a result), and
# CLAUDE.md's guard-class 2 is explicit: such a value must not be derived through a non-preflight
# PATH tool. `lib/preflight.sh` guarantees git/gh/jq/python3 — NOT tr/sed/grep. With the pipeline,
# a host missing `tr` silently yields an EMPTY label set and the wrong thing is selected.
LABELS=()
for _raw in "$@"; do
    _rest="$_raw"
    while [ -n "$_rest" ]; do
        case "$_rest" in
            *,*) _part="${_rest%%,*}"; _rest="${_rest#*,}" ;;
            *)   _part="$_rest";       _rest="" ;;
        esac
        # Trim leading/trailing whitespace with parameter expansion (no external tool).
        _part="${_part#"${_part%%[![:space:]]*}"}"
        _part="${_part%"${_part##*[![:space:]]}"}"
        [ -n "$_part" ] && LABELS+=("$_part")
    done
done

# Empty label set → apply nothing (no POST), exit 0, but NEVER silently (the #480 review): emit
# the nothing-to-apply token and the arg-slip-shaped breadcrumb. A silent exit here would be
# byte-identical to a harness refusal, and a caller that substitutes an empty label literal
# (`apply-labels.sh 42 ""`) or whose configured list normalized to blank would fabricate a
# denial that never happened. The set can be empty only when no label content survived: the
# derivation above is BUILTIN-ONLY, so a missing PATH tool can no longer empty it.
if [ "${#LABELS[@]}" -eq 0 ]; then
    echo "nothing-to-apply"
    echo "devflow: warning: apply-labels.sh got no label content for #${NUMBER} (args: $*); nothing applied. This is NOT a harness denial — the caller passed an empty/whitespace-only label list." >&2
    exit 0
fi

# Create each label if it is missing, through the existing creation path (ensure-label.sh),
# so a config call site needs no separate ensure-label.sh call. Best-effort: ensure-label.sh
# always exits 0 and breadcrumbs to stderr; its stdout is suppressed so this helper's own
# stdout carries only the outcome token.
for _lbl in "${LABELS[@]}"; do
    "$_APPLY_LABELS_DIR/ensure-label.sh" "$_lbl" >/dev/null
done

# Build the REST field list — one `labels[]=<name>` field per label, which gh api
# assembles into a JSON `{"labels":[…]}` array body. The field value is passed
# literally (no shell expansion of the label text).
FIELDS=()
for _lbl in "${LABELS[@]}"; do
    FIELDS+=(-f "labels[]=${_lbl}")
done

# Capture stderr only (stdout → /dev/null) so a genuine failure names its cause in
# the breadcrumb without the success-body output polluting it. The `2>&1 >/dev/null`
# order redirects stderr to the captured stream first, then stdout to /dev/null.
ERR_OUT="$("$DEVFLOW_GH" api --method POST "repos/{owner}/{repo}/issues/${NUMBER}/labels" "${FIELDS[@]}" 2>&1 >/dev/null)"
RC=$?

_joined="$(IFS=,; echo "${LABELS[*]}")"
if [ "$RC" -ne 0 ]; then
    # Best-effort: log the specific target + labels + cause, then still exit 0.
    echo "api-failure"
    echo "devflow: warning: could not apply label(s) '${_joined}' to #${NUMBER} (best-effort, continuing): ${ERR_OUT}" >&2
else
    # SUCCESS breadcrumb — load-bearing, not chatter (issue #455). With the stdout token
    # above, the caller no longer needs it to tell applied from refused, but it is kept
    # byte-identical because assertions elsewhere match it by fixed string.
    echo "applied"
    echo "devflow: applied label(s) '${_joined}' to #${NUMBER}" >&2
fi

exit 0
