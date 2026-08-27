#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# Read a value from .prflow/config.json — PRFlow's single config resolver.
#
# Usage: config-get.sh KEY [DEFAULT] [CONFIG_FILE]
#   KEY          dot-path like .docs.internal or .prflow.workpad_marker
#                (leading dot optional). Arbitrary nesting depth supported —
#                the path is split on dots and walked through nested objects.
#   DEFAULT      printed if key is absent or value is empty/null. Pass an
#                empty string ("") to explicitly request empty-on-missing.
#   CONFIG_FILE  when omitted, defaults to the repo-root .prflow/config.json
#                (git rev-parse --show-toplevel, falling back to pwd); a NON-EMPTY
#                explicit value is honored verbatim (an explicit empty string still
#                selects the root-anchored default) (issue #295)
#
# SHARED REPO-ROOT CONFIG CONTRACT (issue #295, supersedes the #275 cwd-relative
# contract): this resolver and scripts/workpad.py's in-process marker read both
# resolve the DEFAULT `.prflow/config.json` anchored to the git repo root
# (`git rev-parse --show-toplevel`, falling back to `pwd`), NOT relative to the
# current working directory — mirroring lib/config-source.sh. So a skill invoked
# from any subdirectory of the repo loads the consumer's root `.prflow/config.json`
# exactly as if invoked from the root; when cwd already IS the root the resolution
# is byte-for-byte unchanged. Keep the two readers in lockstep: they must resolve
# the same file for the same cwd. A NON-EMPTY explicit CONFIG_FILE (3rd arg) is
# honored verbatim — the root anchoring applies only to the default; an explicit
# EMPTY 3rd arg still selects that default (see the [ -n "${3:-}" ] gate below).
# (workpad.py cannot exec
# this .sh on Windows — [WinError 193] — so it re-implements the same repo-root read
# in Python via a native git subprocess; issue #275/#295.)
#
# Known limitation: `git rev-parse --show-toplevel` returns the NEAREST git root, so
# a nested git submodule/inner repo resolves to that inner root, and a monorepo whose
# `.prflow/` is deliberately not at the git root is not covered — consistent with
# config-source.sh; a walk-up-to-nearest-`.prflow/` resolver was declined for this fix.
#
# Parses with python3, which is a hard PRFlow prerequisite (lib/preflight.sh
# requires python3 >= 3.11; the whole scripts/*.py surface depends on it) and so
# is guaranteed on every host where PRFlow runs — including non-Node hosts where
# `node` is absent. Uses only the stdlib `json` module; no PyYAML or yq required
# (config is JSON). This is the ONE config-reading implementation in PRFlow;
# lib/config-source.sh delegates here.
#
# Exit codes:
#   0  value (or default) printed to stdout
#   1  key not found and no default given. NOT reached for one of the five
#      telemetry gates enrolled in the issue-#2035 master switch: when
#      telemetry.enabled is the JSON boolean false, such a key's miss path
#      prints `false` and exits 0 whether or not a default was given.
#   2  bad arguments, missing `python3`, or JSON parse error

set -euo pipefail

# State-directory resolution (issue #1002): the canonical directory is .prflow/,
# with a LOUD transitional fallback to a superseded .devflow/ when only that one
# is present. Sourced rather than reimplemented so this resolver and every other
# shell reader answer identically; a partially-copied deployment without the
# sibling falls back to the canonical name with a breadcrumb rather than aborting
# under `set -e` (the same guarded-source discipline lib/resolve-jq.sh uses).
# Self-directory anchor. `dirname` is NOT one of the tools lib/preflight.sh
# guarantees, and under `set -e` its failing command substitution aborts the read
# before a caller default is emitted — so this uses the dirname-free spelling of
# the anchor, which is also one of the shapes lib/test/cloud_writer_deps.py can
# prove (a variable assigned by a `case` cannot be resolved by that scanner, so an
# edge built from one reads as a repo-root escape). `cd`/`pwd` are bash builtins.
_CONFIG_GET_DIR="$(cd "${BASH_SOURCE[0]%/*}" && pwd)"
# shellcheck source=../lib/resolve-state-dir.sh
if [ -f "$_CONFIG_GET_DIR/../lib/resolve-state-dir.sh" ] \
   && . "$_CONFIG_GET_DIR/../lib/resolve-state-dir.sh" \
   && type prflow_state_dir >/dev/null 2>&1; then
    :
else
    echo "config-get.sh: resolve-state-dir.sh not found or not sourceable from ../lib — using the canonical .prflow/ with no transitional fallback" >&2
    prflow_state_dir() { printf '%s' "${1:-}/.prflow"; }
fi

key="${1:-}"
has_default=0
if [ $# -ge 2 ]; then
    has_default=1
    default="$2"
fi
# Anchor the DEFAULT config path to the git repo root (issue #295) — mirroring
# lib/config-source.sh (`git rev-parse --show-toplevel 2>/dev/null || pwd`) — so a
# skill invoked from a subdirectory reads the consumer's ROOT .prflow/config.json
# instead of silently missing it. A NON-EMPTY explicit CONFIG_FILE (3rd arg) is
# honored verbatim (an explicit empty 3rd arg still selects the default — see the
# gate below); root anchoring applies only to the default. Each invocation forks
# `git rev-parse` (fast; git is a hard preflight prereq) — unlike config-source.sh,
# this standalone resolver cannot cache the root across its separate subprocesses.
# Gate on a NON-EMPTY 3rd arg (`[ -n "${3:-}" ]`), not merely `$# -ge 3`, so an
# explicitly-passed empty CONFIG_FILE still means "use the default" (the pre-#295
# `${3:-…}` semantics) — root-anchored now — rather than a literal empty path that
# would fail to open.
if [ -n "${3:-}" ]; then
    config_file="$3"
else
    # git rev-parse prints nothing and exits non-zero outside a git tree; the trailing
    # `|| _devflow_root=""` keeps that assignment set -e-safe. Then fall back to cwd, with
    # a breadcrumb only when NEITHER a git root NOR a .prflow/ dir can be located — the
    # silent-drop class this fix closes. (A git root with no .prflow/ is the normal
    # unconfigured local case and stays silent; the caller then applies its own default.)
    _devflow_root="$(git rev-parse --show-toplevel 2>/dev/null)" || _devflow_root=""
    if [ -z "$_devflow_root" ]; then
        _devflow_root="$(pwd)"
        # git can exit non-zero while genuinely INSIDE a repo (safe.directory /
        # dubious-ownership refusal), or be absent from PATH — not only "outside a
        # git tree". So do not assert "not in a git repo": say the root could not be
        # resolved and surface git's own stderr (the one string naming the real
        # cause) instead of discarding it. Re-run on this rare breadcrumb path only;
        # `|| true` keeps it set -e-safe.
        # Probe BOTH names: a consumer who has not run /prflow:init yet has only
        # the superseded directory, and reporting "no .prflow/" at them would name
        # a path they were never told to create. The state-dir resolver decides
        # which one is actually used (and breadcrumbs the superseded one itself).
        if [ ! -d "${_devflow_root}/.prflow" ] && [ ! -d "${_devflow_root}/.devflow" ]; then
            _git_err="$(git rev-parse --show-toplevel 2>&1 >/dev/null)" || true
            echo "config-get.sh: could not resolve a git repo root${_git_err:+ (git: ${_git_err})} and no .prflow/ at '${_devflow_root}'; using cwd fallback and defaults" >&2
        fi
    fi
    config_file="$(prflow_state_dir "$_devflow_root")/config.json"
fi

if [ -z "$key" ]; then
    echo "config-get.sh: usage: config-get.sh KEY [DEFAULT] [CONFIG_FILE]" >&2
    exit 2
fi

# Superseded-key probe (issues #988, #1002). Fires ONLY on the miss path, so the
# hot path forks nothing extra. It answers a question the main read structurally
# cannot: that read collapses {absent, null, present-and-empty} onto one empty
# stdout, and a breadcrumb sited there would fire on a key a consumer has
# deliberately set to "". The probe re-reads the config and distinguishes them,
# emitting only for a genuinely ABSENT new key whose superseded counterpart is
# PRESENT.
#
# It maps the FIRST dot-path segment only, so `.prflow_implement.stall_backstop`
# probes `.devflow_implement.stall_backstop` and no deeper segment is rewritten.  # superseded-key-ok: documents the superseded leaf this migration probe reads (issue #1096)
# The map comes from lib/rename-map.json — the single source — never from a
# literal copy here. Best-effort throughout: an unreadable map or config makes
# the probe a silent no-op, because a diagnostic must never be able to break the
# read it is diagnosing.
probe_superseded_key() {
    local map_file hit
    map_file="$_CONFIG_GET_DIR/../lib/rename-map.json"
    [ -f "$map_file" ] || return 0
    command -v python3 >/dev/null 2>&1 || return 0
    hit="$(PRFLOW_KEY="${key#.}" PRFLOW_CONFIG="$config_file" PRFLOW_MAP="$map_file" python3 -c '
import json, os, sys


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


try:
    data = load(os.environ["PRFLOW_CONFIG"])
    renames = load(os.environ["PRFLOW_MAP"])["config_keys"]
except Exception:
    sys.exit(0)
if not isinstance(data, dict) or not isinstance(renames, dict):
    sys.exit(0)
# current -> superseded, so a requested NEW key can name its OLD counterpart.
superseded_of = {new: old for old, new in renames.items()}
parts = os.environ["PRFLOW_KEY"].split(".")
if not parts or parts[0] not in superseded_of:
    sys.exit(0)


def present(root, path):
    cur = root
    for part in path:
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    return True


# A new key that is PRESENT — including one holding null, "" , false or 0 — is a
# deliberate consumer value, not an un-migrated config. Only a genuinely absent
# one earns the breadcrumb.
if present(data, parts):
    sys.exit(0)
old = [superseded_of[parts[0]]] + parts[1:]
if not present(data, old):
    sys.exit(0)
sys.stdout.write("." + ".".join(old))
' 2>/dev/null)" || return 0
    [ -n "$hit" ] || return 0
    # Worded for BOTH miss paths: this fires above the default-emitting branch and
    # above the exit-1 branch, so it must not promise a default that a no-default
    # call never gets.
    echo "config-get.sh: '.${key#.}' is absent from $config_file but its superseded counterpart '$hit' is present — run /prflow:init to migrate the config keys; until then this read resolves as if the key were unset." >&2
}

# Telemetry master-key inheritance (issue #2035): 0 iff "$1" is one of the five
# enrolled default-true telemetry gates AND telemetry.enabled is the JSON boolean
# false. Best-effort: missing python3 or any read error -> return 1 (telemetry on).
telemetry_master_disables_for() {
    case "$1" in
        prflow_review_and_fix.efficiency_telemetry_enabled|\
        prflow.execution_diagnostics_enabled|\
        prflow.execution_denial_commands_enabled|\
        prflow_review.live_progress_comment_enabled|\
        create_issue.investigation_record_enabled) ;;
        *) return 1 ;;
    esac
    command -v python3 >/dev/null 2>&1 || return 1
    # Inline python3 -c, NOT an exec of a repo .py: config-get.sh is a hardened
    # Stop-hook closure member, so adding a source/exec edge to a new script would
    # break the issue-#458 drift-guard and force a workflow edit. Reads the JSON
    # TYPE (`is False`), so the number 0 and the string "false" never disable.
    PRFLOW_TEL_CFG="$config_file" python3 -c '
import json, os, sys
try:
    with open(os.environ["PRFLOW_TEL_CFG"], encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    sys.exit(1)
tel = data.get("telemetry") if isinstance(data, dict) else None
sys.exit(0 if isinstance(tel, dict) and tel.get("enabled") is False else 1)
' >/dev/null 2>&1
}

emit_default_or_fail() {
    probe_superseded_key
    # Master inheritance runs AFTER probe_superseded_key so the migration
    # breadcrumb still fires for an absent enrolled key, and only for the enrolled
    # set so a non-enrolled miss path stays byte-identical (issue #2035).
    if telemetry_master_disables_for "${key#.}"; then
        printf '%s\n' "false"
        exit 0
    fi
    if [ "$has_default" -eq 1 ]; then
        printf '%s\n' "$default"
        exit 0
    fi
    exit 1
}

if [ ! -f "$config_file" ]; then
    if [ "$has_default" -eq 1 ]; then
        printf '%s\n' "$default"
        exit 0
    fi
    echo "config-get.sh: config file not found: $config_file" >&2
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "config-get.sh: 'python3' is required to read $config_file" >&2
    exit 2
fi

# Walk the dot-path. Missing/null → empty stdout (caller applies default).
# Lists join with ',' (matches prior behavior, e.g. allowed_bots/watched_authors).
# coerce() reproduces the prior Node String()/Array.join semantics byte-for-byte:
# booleans emit lowercase true/false (NOT Python's True/False), null → empty,
# arrays comma-join their coerced elements, an object → "[object Object]".
value=$(DEVFLOW_KEY="${key#.}" DEVFLOW_CONFIG="$config_file" python3 -c '
import json, os, sys
try:
    with open(os.environ["DEVFLOW_CONFIG"], encoding="utf-8") as f:
        data = json.load(f)
except Exception as e:
    sys.stderr.write("config-get.sh: " + str(e) + "\n")
    sys.exit(2)


def coerce(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return ",".join(coerce(x) for x in v)
    if isinstance(v, dict):
        return "[object Object]"
    return str(v)


cur = data
for part in os.environ["DEVFLOW_KEY"].split("."):
    if not isinstance(cur, dict) or part not in cur:
        sys.exit(0)
    cur = cur[part]
if cur is None:
    sys.exit(0)
sys.stdout.write(coerce(cur))
')

if [ -z "$value" ]; then
    emit_default_or_fail
fi

printf '%s\n' "$value"
