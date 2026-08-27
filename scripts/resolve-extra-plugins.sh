#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# resolve-extra-plugins.sh — emit the extra plugin/marketplace entries a repo's
# .claude/settings.json declares, for the cloud-tier plugin-parity compose (issue #505).
#
# The three claude-code-action call sites bake a fixed plugin/marketplace baseline.
# This helper appends what the repo's trusted-ref .claude/settings.json additionally
# declares (enabledPlugins=true entries; github-kind extraKnownMarketplaces), so a
# consumer repo's cloud plugin surface matches what its local team already sees —
# "commit the settings file once, every tier honors it."
#
# Usage: resolve-extra-plugins.sh <mode> <settings-path>
#   mode           "plugins" or "marketplaces"
#   settings-path  path to a .claude/settings.json — the default-branch checkout copy
#                  on the write tiers; the trusted base-ref materialized copy on the
#                  review tier (never the PR-head checkout's settings file).
#
# Emits zero or more entries, one per line, on stdout. ALWAYS exits 0: a degraded
# input shape emits a specific stderr breadcrumb naming the defect and emits nothing,
# so the composing step proceeds with the baked baseline. An ABSENT settings file is
# the normal consumer case — empty stdout, exit 0, NO breadcrumb (the compose then
# equals the baked baseline exactly, silently).
#
# Every value that decides what is emitted is derived via python3 (preflight-
# guaranteed — lib/preflight.sh requires python3 >= 3.11), never via tr/sed/wc/cut/head
# (guard-class 2: a value that decides an emitted result must not depend on a non-
# preflight PATH tool). Mirrors scripts/config-get.sh's direct-python3 + stdlib-json
# pattern (no jq, no resolve-python.sh). Data crosses the bash->python boundary via
# env vars (DEVFLOW_MODE/DEVFLOW_SETTINGS), not argv, so a settings path containing
# quotes/backticks/$ never traverses shell quoting.
#
# plugins mode — emits the enabledPlugins keys whose JSON value is the boolean true
#   (json.load maps JSON true -> Python True, so `val is True` is the strict boolean
#   test; a value of 1 or "true" is NOT boolean true). Exclusions, listed in the order
#   the code applies them:
#     - value not boolean true: boolean false is silently skipped (the suppression
#       case); the STRING "true" is not emitted and draws a wrong-type breadcrumb.
#     - key equal to a baked baseline entry (code-review@claude-plugins-official,
#       claude-md-management@claude-plugins-official, prflow@devflow-marketplace):
#       silent skip (already installed by the baseline).
#     - key with no @marketplace suffix: breadcrumb, not emitted.
#     - key whose plugin name (the part before @) is one of PRFlow's own accepted
#       plugin names: silent skip (always installed via the baked baseline spec).
#       That accepted set — and the PRFlow half of the two sets above — is compiled
#       from lib/plugin-identity.json + .claude-plugin/plugin.json into the generated
#       identity region below, never hand-spelled in this helper.
#     - key whose marketplace suffix is outside the known set — the union of
#       claude-plugins-official, devflow-marketplace, and the names of github-kind
#       extraKnownMarketplaces entries in the same file WHOSE repo is a non-empty
#       string: a suffix declared nowhere in the file -> unknown-marketplace
#       breadcrumb; a suffix declared as github-kind but with a missing/empty/non-
#       string repo (so its URL cannot be registered) -> bad-repo breadcrumb; a
#       suffix declared with a non-github source kind -> declared-but-unsupported-kind
#       breadcrumb naming the kind and the scope boundary.
#
# marketplaces mode — emits https://github.com/<repo>.git for each
#   extraKnownMarketplaces entry whose .source.source is the string "github" and whose
#   .source.repo is a non-empty string; entries named claude-plugins-official and
#   devflow-marketplace are silently skipped (both already registered by the baked
#   baseline; re-registering devflow-marketplace from GitHub would collide with the
#   ./ checkout-root registration every /devflow:init-provisioned repo carries). A
#   non-github source kind, or a github entry whose repo is missing/empty/non-string,
#   is skipped with a breadcrumb naming the entry and the cause.
#
# Exit codes:
#   0  entries (possibly none) on stdout; a degraded shape additionally prints a
#      specific stderr breadcrumb. There is no non-zero path — the compose must
#      never break on a corrupt settings file.

set -u

mode="${1:-}"
settings_path="${2:-}"

if [ -z "$mode" ] || [ -z "$settings_path" ]; then
    echo "resolve-extra-plugins: usage: resolve-extra-plugins.sh <plugins|marketplaces> <settings-path>" >&2
    exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "resolve-extra-plugins: 'python3' is required to read $settings_path" >&2
    exit 0
fi

# PRFlow's own accepted plugin/marketplace identifiers, compiled from
# lib/plugin-identity.json + .claude-plugin/plugin.json. BAKED rather than read at
# runtime because the review tier materializes THIS FILE ALONE from the trusted base ref
# into a flat $RUNNER_TEMP directory: there is no sibling lib/ there, so a runtime read
# would resolve to nothing on exactly the tier that matters most. Plain assignments, and
# they are re-assigned unconditionally so an inherited environment value cannot change
# what this helper treats as its own baseline. Passed to python3 via env (like
# DEVFLOW_MODE/DEVFLOW_SETTINGS) so no value traverses shell quoting.
# devflow-plugin-identity:begin identity_version=2 sha256=3e6849a85e075e7ebb27ebf17b3fe2faa1246c54ed6a5acbcf839144dc751e25 (generated by lib/generate-plugin-identity.py -- do not hand-edit; source: lib/plugin-identity.json + .claude-plugin/plugin.json)
DEVFLOW_PLUGIN_NAMES='prflow devflow'
DEVFLOW_MARKETPLACE_NAMES='devflow-marketplace'
# devflow-plugin-identity:end

DEVFLOW_MODE="$mode" DEVFLOW_SETTINGS="$settings_path" \
DEVFLOW_PLUGIN_NAMES="$DEVFLOW_PLUGIN_NAMES" DEVFLOW_MARKETPLACE_NAMES="$DEVFLOW_MARKETPLACE_NAMES" \
python3 -c '
import json, os, sys

mode = os.environ.get("DEVFLOW_MODE", "")
settings_path = os.environ.get("DEVFLOW_SETTINGS", "")


def warn(msg):
    sys.stderr.write("resolve-extra-plugins: " + msg + "\n")


if mode not in ("plugins", "marketplaces"):
    warn("unknown mode " + repr(mode) + " (expected: plugins | marketplaces); emitting nothing")
    sys.exit(0)

if not os.path.exists(settings_path):
    # Absent file is the normal consumer case: empty stdout, exit 0, no breadcrumb.
    sys.exit(0)

try:
    with open(settings_path, encoding="utf-8") as f:
        data = json.load(f)
except json.JSONDecodeError as exc:
    # A parse failure: the file read, but is not valid JSON.
    warn(settings_path + " is not valid JSON (" + str(exc) + "); emitting nothing")
    sys.exit(0)
except Exception as exc:
    # Any other failure (a read/permission/encoding error) is NOT a JSON defect —
    # name it accurately so a consumer is not misdirected to "fix the JSON syntax".
    warn(settings_path + " could not be read (" + str(exc) + "); emitting nothing")
    sys.exit(0)

if not isinstance(data, dict):
    warn(settings_path + " is valid JSON but not an object (" + type(data).__name__ + "); emitting nothing")
    sys.exit(0)

# Pre-compute the marketplace index once (used by both modes): the names declared in
# extraKnownMarketplaces, the github-kind subset (the only kind the compose maps to a
# URL, and a known-marketplace suffix for plugins mode), and a per-entry string source
# kind (for the declared-but-unsupported-kind breadcrumb — built here so the breadcrumb
# does not re-derive extra[name].source.source a second time).
extra = data.get("extraKnownMarketplaces")
if isinstance(extra, dict):
    declared_market_names = set(extra.keys())
    github_market_names = set()
    github_market_bad_repo = set()
    market_kinds = {}
    for nm, val in extra.items():
        if isinstance(val, dict):
            src = val.get("source")
            if isinstance(src, dict):
                k = src.get("source")
                if isinstance(k, str):
                    market_kinds[nm] = k
                if k == "github":
                    # Only a github market whose repo is a non-empty string maps to a
                    # registrable URL (marketplaces mode requires the same), so only such
                    # a market may join the plugins-mode KNOWN set. A github market with a
                    # missing/empty/non-string repo is NOT known — its URL is never
                    # registered, so a plugin against it must not be emitted-and-audited as
                    # "composed" while its marketplace goes unregistered. Tracked separately
                    # so the plugins-mode breadcrumb names this cause accurately (not the
                    # non-github-kind message, whose kind here IS github).
                    repo = src.get("repo")
                    if isinstance(repo, str) and repo != "":
                        github_market_names.add(nm)
                    else:
                        github_market_bad_repo.add(nm)
else:
    declared_market_names = set()
    github_market_names = set()
    github_market_bad_repo = set()
    market_kinds = {}


# PRFlow own-identity sets, read from the BAKED lists in the shell preamble (see
# there for why they are baked). An empty set is unestablished, not "PRFlow owns
# nothing": that would make this helper emit PRFlow own entries back to the compose
# step as third-party plugins. This helper is best-effort by contract, so it names the
# defect and emits nothing, leaving the composing step with exactly the baked baseline.
DEVFLOW_PLUGIN_NAMES = frozenset(os.environ.get("DEVFLOW_PLUGIN_NAMES", "").split())
DEVFLOW_MARKETPLACES = frozenset(os.environ.get("DEVFLOW_MARKETPLACE_NAMES", "").split())
if not DEVFLOW_PLUGIN_NAMES or not DEVFLOW_MARKETPLACES:
    warn("the accepted DevFlow plugin/marketplace identifier set is empty or unset"
         " (the generated identity region in this helper is missing or was not"
         " regenerated); emitting nothing")
    sys.exit(0)
DEVFLOW_PLUGIN_SPECS = frozenset(
    p + "@" + m for p in DEVFLOW_PLUGIN_NAMES for m in DEVFLOW_MARKETPLACES
)

# The non-PRFlow half of the baked baseline stays a literal: those are third-party
# plugin ids this project does not own and no rename of ours can move.
FOREIGN_BAKED_PLUGINS = frozenset((
    "code-review@claude-plugins-official",
    "claude-md-management@claude-plugins-official",
))
FOREIGN_BASE_MARKETPLACES = frozenset(("claude-plugins-official",))

BAKED_PLUGINS = FOREIGN_BAKED_PLUGINS | DEVFLOW_PLUGIN_SPECS
# The baked-baseline marketplace names — used both as the plugins-mode known set and the
# marketplaces-mode silent-skip set; the two concepts are the same baseline names.
BASE_MARKETPLACES = FOREIGN_BASE_MARKETPLACES | DEVFLOW_MARKETPLACES

if mode == "plugins":
    ep = data.get("enabledPlugins")
    if ep is None:
        # Absent key: empty stdout, exit 0, no breadcrumb (baseline-only compose).
        sys.exit(0)
    if not isinstance(ep, dict):
        warn("enabledPlugins is not an object (" + type(ep).__name__ + "); emitting nothing")
        sys.exit(0)
    known = BASE_MARKETPLACES | github_market_names
    for key, val in ep.items():
        # Strict boolean-true test: json.load maps JSON true -> Python True (the
        # singleton), so `val is True` accepts only a real boolean true. A string
        # "true", the number 1, or boolean false are NOT emitted.
        if val is True:
            pass
        elif isinstance(val, str) and val == "true":
            warn("enabledPlugins entry " + repr(key) + " has string value \"true\" (not boolean true); not emitted")
            continue
        else:
            # boolean false (the suppression case), null, numbers: silent skip.
            continue
        if key in BAKED_PLUGINS:
            continue
        if "@" not in key:
            warn("enabledPlugins entry " + repr(key) + " has no @marketplace suffix; not emitted")
            continue
        plugin_name, _, market = key.partition("@")
        if plugin_name in DEVFLOW_PLUGIN_NAMES:
            continue
        if market not in known:
            if market in github_market_bad_repo:
                warn("enabledPlugins entry " + repr(key) + " marketplace " + repr(market)
                     + " is github-kind in extraKnownMarketplaces but its repo is missing, empty, or"
                     + " non-string, so its marketplace URL cannot be registered; not emitted")
            elif market in declared_market_names:
                # dict.get with a default (not `get(...) or`): an EMPTY-STRING source
                # kind is a real observed value the breadcrumb must report as '' —
                # the `or` idiom would mislabel it "missing" (it is present, just
                # empty). "missing" is only for an absent or non-string kind (the
                # non-string case matches the marketplaces-mode sibling below).
                kstr = market_kinds.get(market, "missing")
                warn("enabledPlugins entry " + repr(key) + " marketplace " + repr(market)
                     + " is declared in extraKnownMarketplaces but with non-github source kind "
                     + repr(kstr) + " (scope boundary: only github-kind marketplaces are mapped); not emitted")
            else:
                warn("enabledPlugins entry " + repr(key) + " marketplace " + repr(market)
                     + " is not declared anywhere in the settings file; not emitted")
            continue
        sys.stdout.write(key + "\n")
    sys.exit(0)

if mode == "marketplaces":
    if extra is None:
        sys.exit(0)
    if not isinstance(extra, dict):
        warn("extraKnownMarketplaces is not an object (" + type(extra).__name__ + "); emitting nothing")
        sys.exit(0)
    for name, val in extra.items():
        if name in BASE_MARKETPLACES:
            continue
        if not isinstance(val, dict):
            warn("extraKnownMarketplaces entry " + repr(name) + " is not an object (" + type(val).__name__ + "); not emitted")
            continue
        src = val.get("source")
        if not isinstance(src, dict):
            warn("extraKnownMarketplaces entry " + repr(name) + " has no source object; not emitted")
            continue
        kind = src.get("source")
        if kind == "github":
            repo = src.get("repo")
            if isinstance(repo, str) and repo != "":
                sys.stdout.write("https://github.com/" + repo + ".git\n")
            else:
                warn("extraKnownMarketplaces entry " + repr(name) + " is github-kind but repo is missing, empty, or non-string; not emitted")
        else:
            kstr = kind if isinstance(kind, str) else "missing"
            warn("extraKnownMarketplaces entry " + repr(name) + " has source kind " + repr(kstr)
                 + " (only github is mapped to a URL); not emitted")
    sys.exit(0)
'
# Make the "ALWAYS exits 0" header literally true: every MODELED python path calls
# sys.exit(0), but an unmodeled interpreter crash would otherwise propagate a non-zero
# status. This trailing exit 0 pins the script's own exit status to 0 regardless, so the
# compose step never breaks on it even if the interpreter dies unexpectedly.
exit 0
