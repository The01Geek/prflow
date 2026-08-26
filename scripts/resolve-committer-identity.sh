#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
#
# Resolve the triggering user to a git commit identity and emit the four
# GIT_AUTHOR_*/GIT_COMMITTER_* assignment lines, gated by a default-off config
# flag (issue #682). This is the sibling of scripts/emit-git-env.sh (#645):
# same trusted-config leaf-check, same always-exit-0 fail-open contract, same
# $GITHUB_ENV-append consumption at the workflow call site.
#
# Background. In a cloud-tier writer run (/devflow:implement's `claude` job,
# /devflow:review-and-fix's `command` job) the git commits the agent produces
# are authored by whatever git resolves from an unconfigured .git/config on the
# runner — NOT the human who triggered the run. Consumers whose reviewers/auditors
# read `git blame` to see which human owns a change lose that provenance on every
# cloud run. When the opt-in key is enabled, this helper resolves the triggering
# login to a GitHub commit identity and emits the four GIT_* variables so the
# agent's commits carry the triggering human as both author and committer. The
# commit author/committer is git metadata, INDEPENDENT of the push token (which
# stays the App/github-actions[bot] identity), so no new credential is needed.
#
# Usage:
#   resolve-committer-identity.sh --login LOGIN [--config-file PATH]
#
#   --login LOGIN       the triggering user (GitHub's github.event.sender.login).
#                       Empty/absent → emit nothing, warn, exit 0.
#   --config-file PATH  config JSON to read. Defaults to the repo-root
#                       .prflow/config.json via the shared resolver (issue #295).
#                       The cloud callers pass the TRUSTED trigger-time config
#                       (the `config` job's default-branch checkout) — never the
#                       PR head, which is what makes the flag POST-MERGE-ONLY.
#
# Config key (under `devflow`, default false):
#   prflow.attribute_commits_to_triggerer → resolve + emit the four GIT_* vars
#
# ENABLED semantics are kept in LOCKSTEP with emit-git-env.sh: the key is enabled
# only when its JSON leaf is the boolean `true` or the string "true". Every other
# shape — absent, JSON null, an explicit false, a number, a single-element array
# [true], an object, a non-object `devflow` container, an unreadable/malformed
# config — resolves to DISABLED (emit nothing). The leaf's TYPE is what decides,
# read with python3 (the same stdlib json module config-get.sh uses), because the
# shared resolver's String()/Array.join() coercion makes [true] indistinguishable
# from the boolean true at its output — and [true] is a shape the schema rejects.
#
# HUMANS ONLY, fail-safe. The identity is emitted only for a confirmed human:
# `.type == "User"` AND the login does not carry the GitHub-App `*[bot]` suffix.
# A non-"User" type, a `*[bot]` login, or a `.type` that cannot be established
# (the API responded but carried no usable type) emits NO GIT_* variable and logs
# a ::warning:: — the run falls back to current authorship. This is deliberately
# conservative: mis-attributing a bot's commit to a human is worse than leaving a
# human run un-attributed.
#
# gh-call FAILURE is different from a non-"User" type. When the `gh api users/…`
# call itself fails (network/auth/rate-limit/non-zero exit) for a login NOT already
# classified non-human (i.e. not a `*[bot]`), the helper preserves human attribution
# with a LOGIN-ONLY fallback: email `<login>@users.noreply.github.com`, name = login,
# all four variables still emitted, with a ::warning:: naming the fallback. A transport
# failure must not silently drop attribution to whatever git resolves locally.
#
# Contract: ALWAYS exits 0, with ::warning::/::notice:: breadcrumbs — the repo's
# best-effort helper convention (ensure-label.sh / emit-git-env.sh). The consuming
# workflow step appends this stdout to "$GITHUB_ENV", so a non-zero exit would fail
# the job over an advisory attribution read; commit attribution is advisory and
# NEVER gates the run. The decisive values are derived with bash builtins and
# python3 (a preflight prerequisite), never a non-preflight PATH tool such as
# tr/sed/cut, so a missing tool cannot fail this open into a partially-emitted block.
#
# $GITHUB_ENV newline safety. Each GIT_* line is emitted in GitHub's newline-safe
# multiline (heredoc) form with a per-run unique delimiter — the same form the
# workflows' genv() helper uses — so a display name carrying an unexpected character
# can never split or forge a further $GITHUB_ENV line (the adversarial-input case).
#
# An ABSENT helper is likewise safe: the workflow step guards on the file existing
# and emits nothing when it is missing. The workflow reaches consumers through
# install.sh's file-copy while this helper reaches them through the prflow_version
# vendor fetch, so a consumer can carry the step before it carries the helper —
# that skew must degrade to current authorship, never fail the run.

set -uo pipefail

# gh binary: resolved once via the single-source execution-verified resolver
# (issue #247). An explicit DEVFLOW_GH still wins WITHOUT any probe, so the test
# suite's DEVFLOW_GH stub is untouched. NEVER a bare `gh`.
# shellcheck source=../lib/resolve-gh.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/resolve-gh.sh"
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"

_login=''
_cfg=''

while [ $# -gt 0 ]; do
    case "$1" in
        --login)
            _login="${2:-}"
            shift 2 || shift
            ;;
        --config-file)
            _cfg="${2:-}"
            shift 2 || shift
            ;;
        *)
            echo "resolve-committer-identity.sh: ignoring unrecognized argument '$1'" >&2
            shift
            ;;
    esac
done

# Resolve the config path the same way PRFlow's shared resolver does when no
# explicit file is given: anchored to the git repo ROOT (issue #295), falling back
# to the working directory. A non-empty explicit --config-file is honored verbatim.
if [ -z "$_cfg" ]; then
    _root="$(git rev-parse --show-toplevel 2>/dev/null)" || _root=''
    [ -n "$_root" ] || _root="$(pwd)"
    _cfg="${_root}/.prflow/config.json"
fi

# Print `true` iff the leaf at the given dot-path is the JSON boolean true or the
# JSON string "true"; print `false` for every other shape (kept in lockstep with
# emit-git-env.sh's _read_key). Any failure — python3 absent, interpreter error,
# unreadable/malformed file — collapses to `false`, the working default.
_read_key() {
    _rk_out=''
    if command -v python3 >/dev/null 2>&1; then
        _rk_out="$(DEVFLOW_ATTR_KEY="${1#.}" DEVFLOW_ATTR_CFG="$_cfg" python3 -c '
import json, os, sys
try:
    with open(os.environ["DEVFLOW_ATTR_CFG"], encoding="utf-8") as f:
        data = json.load(f)
except Exception:
    sys.stdout.write("false")
    sys.exit(0)
cur = data
for part in os.environ["DEVFLOW_ATTR_KEY"].split("."):
    if not isinstance(cur, dict) or part not in cur:
        sys.stdout.write("false")
        sys.exit(0)
    cur = cur[part]
# isinstance(True, int) is True in Python, so test bool BEFORE any numeric
# interpretation; a bare 1 must never read as enabled.
if cur is True or (isinstance(cur, str) and cur == "true"):
    sys.stdout.write("true")
else:
    sys.stdout.write("false")
' 2>/dev/null)" || _rk_out='false'
    else
        echo "resolve-committer-identity.sh: python3 not found; treating attribute_commits_to_triggerer as disabled (the working default)" >&2
        _rk_out='false'
    fi
    printf '%s' "$_rk_out"
}

_enabled() {
    case "$(_read_key '.prflow.attribute_commits_to_triggerer')" in
        true) return 0 ;;
        *) return 1 ;;
    esac
}

# Disabled (or an unreadable/malformed config that collapses to disabled) → emit
# nothing, exit 0. This is the byte-for-byte-unchanged default path: no warning,
# so a stock consumer's run log is untouched.
if ! _enabled; then
    exit 0
fi

# Enabled but no triggering login → cannot attribute; warn and fall back to
# current authorship.
if [ -z "$_login" ]; then
    echo "::warning::devflow commit attribution: attribute_commits_to_triggerer is enabled but the triggering login is empty/absent; emitting no GIT_* identity — commits use current authorship." >&2
    exit 0
fi

# A `*[bot]` login is a GitHub App identity, never a human — classify non-human
# from the login alone, BEFORE any API call, so a bot never receives the login-only
# fallback that a transport failure grants a human.
case "$_login" in
    *'[bot]')
        echo "::warning::devflow commit attribution: triggering login '$_login' carries the GitHub-App '[bot]' suffix (not a human); emitting no GIT_* identity — commits use current authorship." >&2
        exit 0
        ;;
esac

# Emit the four GIT_* assignments in GitHub's newline-safe heredoc form (the genv()
# shape). A per-invocation unique delimiter guarantees a value carrying an unexpected
# character cannot split or forge a further $GITHUB_ENV line.
_emit_identity() {
    _ei_name="$1"
    _ei_email="$2"
    _ei_delim="DEVFLOW_ATTR_EOF_$(date +%s%N 2>/dev/null)_$$"
    # One loop over the four "var value" pairs — the name pair then the email pair.
    for _ei_pair in "GIT_AUTHOR_NAME $_ei_name" "GIT_COMMITTER_NAME $_ei_name" \
                    "GIT_AUTHOR_EMAIL $_ei_email" "GIT_COMMITTER_EMAIL $_ei_email"; do
        printf '%s<<%s\n%s\n%s\n' "${_ei_pair%% *}" "$_ei_delim" "${_ei_pair#* }" "$_ei_delim"
    done
}

# Resolve the identity via the REST Users endpoint through the resolved gh.
_user_json="$("$DEVFLOW_GH" api "users/$_login" 2>/dev/null)"
_gh_rc=$?

if [ "$_gh_rc" -ne 0 ]; then
    # Transport/auth/rate-limit failure for a login not classified non-human:
    # preserve HUMAN attribution with the login-only (non-canonical email) fallback.
    echo "::warning::devflow commit attribution: 'gh api users/$_login' failed (network/auth/rate-limit, exit $_gh_rc); falling back to login-only identity (name='$_login', email='$_login@users.noreply.github.com')." >&2
    _emit_identity "$_login" "$_login@users.noreply.github.com"
    exit 0
fi

# Parse .type, .id, .name from the API response with python3 (never jq — keep the
# parse on the preflight-guaranteed interpreter). Emit a tab-separated
# "type<TAB>id<TAB>name", with empty fields for a missing/null value. An
# unparseable body or a non-object body emits an EMPTY type, which the
# `!= "User"` gate below treats identically to any non-human type — the sole
# consumer never distinguishes "anomalous body" from "empty .type", so no
# sentinel is needed.
_parsed="$(DEVFLOW_ATTR_USERJSON="$_user_json" python3 -c '
import json, os, sys
raw = os.environ.get("DEVFLOW_ATTR_USERJSON", "")
try:
    d = json.loads(raw)
except Exception:
    d = None
if not isinstance(d, dict):
    sys.stdout.write("\t\t")
    sys.exit(0)
t = d.get("type")
i = d.get("id")
n = d.get("name")
t = t if isinstance(t, str) else ""
i = str(i) if isinstance(i, int) else ""
n = n if isinstance(n, str) else ""
# A name is a single logical line by construction of GITHUB display names, but a
# stray newline would break the tab framing below — collapse any to spaces so the
# framing stays intact (cosmetic; the heredoc emit is the real newline guard).
n = n.replace("\r", " ").replace("\n", " ")
sys.stdout.write("%s\t%s\t%s" % (t, i, n))
' 2>/dev/null)" || _parsed=''

# Split the tab-separated fields with bash builtins (no cut).
_utype="${_parsed%%$'\t'*}"
_rest="${_parsed#*$'\t'}"
_uid="${_rest%%$'\t'*}"
_uname="${_rest#*$'\t'}"

if [ "$_utype" != "User" ]; then
    # An empty _utype (an unparseable/non-object API body, or a .type that could
    # not be established) and any Bot/Organization/other type all land here: emit
    # nothing, warn.
    echo "::warning::devflow commit attribution: users/$_login resolved with type='$_utype' (not the human 'User' type, or the type could not be established); emitting no GIT_* identity — commits use current authorship." >&2
    exit 0
fi

# Confirmed human. Name = .name when non-empty, else the login. Email = the
# canonical <id>+<login>@users.noreply.github.com when the id resolved to an
# integer; if the id could not be established, degrade to the login-only email
# rather than emit a malformed `+login@…` — human attribution is still preserved.
_name="$_login"
[ -n "$_uname" ] && _name="$_uname"
if [ -n "$_uid" ]; then
    _email="${_uid}+${_login}@users.noreply.github.com"
else
    echo "::warning::devflow commit attribution: users/$_login is a User but its numeric id could not be established; using the login-only email '$_login@users.noreply.github.com'." >&2
    _email="$_login@users.noreply.github.com"
fi

_emit_identity "$_name" "$_email"
exit 0
