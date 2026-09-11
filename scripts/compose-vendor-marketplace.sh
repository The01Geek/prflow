#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# compose-vendor-marketplace.sh — resolve this repository's cloud implement plugin
# root to the VENDORED subtree, so the shipped helper-path shape a consumer emits is
# the shape this repo emits too (issue #1049).
#
# Why this exists. `.claude-plugin/marketplace.json` at the repo root declares the
# `prflow` plugin with `"source": "./"`, so in THIS repo's cloud implement run
# `$CLAUDE_SKILL_DIR` resolves to `<workspace>/skills/<name>` and the portable helper
# anchor lands at `<workspace>/scripts/<helper>` (the repo root). A CONSUMER's
# install.sh instead composes a marketplace whose source is `./.prflow/vendor/prflow`,
# so the consumer resolves to `<workspace>/.prflow/vendor/prflow/skills/<name>` and the
# anchor lands under `.prflow/vendor/prflow/scripts/`. Two different resolutions of the
# same shipped bytes; no run in this repo ever exercises the consumer one. This helper
# closes that gap for the cloud implement tier by composing a JOB-LOCAL marketplace
# rooted at the vendored parent dir and rewriting the composed marketplace list to use
# it in place of the repo-root `./` entry — WITHOUT touching the tracked
# `.claude-plugin/marketplace.json` (constraint from issue #1049: this repo is its own
# marketplace and must keep its `source` at `./`; re-pointing that file at the vendored
# path would diverge the tracked repo-root marketplace from the shape the repo requires,
# so the constraint is enforced by the issue's own authoring rule, not by a suite pin).
#
# It does NOT edit the baked marketplace baseline literal (the three-way #505 AC4 sync
# pin): the workflow computes the combined marketplace list from that untouched baseline
# and hands it here as a file; this helper only swaps the resolved `./` entry for the
# job-local vendored marketplace directory. Adding a job-local entry, never mutating the
# baseline — exactly the shape issue #1049 prescribes.
#
# Usage: compose-vendor-marketplace.sh <marketplaces-file> <vendor-root>
#   marketplaces-file  a file with one marketplace entry per line (the workflow's
#                      COMBINED_MK). Rewritten IN PLACE on the composed arm.
#   vendor-root        the vendored parent dir, e.g. `.prflow/vendor`. The plugin is
#                      expected at `<vendor-root>/prflow`.
#
# Arms (the branch selection lives HERE, driven by lib/test/run.sh — the
# describe-denial-count.sh extraction convention, so no arm is left inline-and-
# unasserted in the workflow YAML):
#   composed  — the vendored plugin is present AND complete
#               (`<vendor-root>/prflow/.claude-plugin/plugin.json` is a regular file).
#               Write `<vendor-root>/.claude-plugin/marketplace.json` (a job-local
#               marketplace named `devflow-marketplace`, `prflow` sourced at `./prflow`),
#               rewrite the marketplaces file so the repo-root `./` entry becomes
#               `./<vendor-root>` (the `./` prefix is REQUIRED — see the normalization
#               note at the swap), emit one `::notice::` audit line. A directory's
#               presence is NOT proof the helper set exists, so completeness is proven by
#               the plugin manifest, not the directory. Some sub-cases warn instead of
#               that notice, so this arm is not unconditionally a `::notice::`: an
#               unwritable `marketplace.json` gates the swap OFF (list left unchanged),
#               an unwritable marketplaces file gates the notice OFF (the list was not
#               repointed, and may be truncated), and a combined list carrying no `./`
#               entry composes the marketplace but splices nothing in. Every write that
#               a later annotation would vouch for is checked before it is claimed, and
#               each sub-case is driven by the suite.
#   degraded  — the vendored tree is absent or partial (the #505-class skew: a pinned
#               prflow_version predating this change, or an incomplete vendor fetch).
#               Leave the marketplaces file UNCHANGED (the run keeps resolving from the
#               repo-root `./` marketplace) and emit one `::warning::` naming
#               prflow_version as the remedy — never a hard failure, never a silent skip.
#   usage     — a missing argument. stderr breadcrumb + `::warning::`; leave any file
#               unchanged. Best-effort: ALWAYS exits 0 so a compose bug can never break
#               the credentialed run.
#
# ALWAYS exits 0. Every annotation goes to STDOUT (where GitHub Actions parses workflow
# commands); the caller does not capture this helper's stdout.

set -u

MK_FILE="${1:-}"
VENDOR_ROOT="${2:-}"

if [ -z "$MK_FILE" ] || [ -z "$VENDOR_ROOT" ]; then
    echo "compose-vendor-marketplace: usage: compose-vendor-marketplace.sh <marketplaces-file> <vendor-root>" >&2
    echo "::warning::devflow compose-vendor-marketplace.sh called without both arguments; the prflow plugin resolves from the repo-root marketplace (./)."
    exit 0
fi

PLUGIN_DIR="$VENDOR_ROOT/prflow"
PLUGIN_MANIFEST="$PLUGIN_DIR/.claude-plugin/plugin.json"

# Completeness is proven by the plugin manifest, not the directory's mere presence:
# an incomplete vendor fetch can leave the directory without the plugin.
if [ ! -f "$PLUGIN_MANIFEST" ]; then
    echo "::warning::devflow compose-vendor-marketplace.sh: $PLUGIN_MANIFEST is absent — the vendored plugin is missing or partial (a pinned prflow_version predating issue #1049, or an incomplete vendor fetch); the prflow plugin resolves from the repo-root marketplace (./). Bump prflow_version in .prflow/config.json."
    exit 0
fi

# ── composed arm ────────────────────────────────────────────────────────────────
# Write the job-local marketplace rooted at the vendored PARENT dir. Its `prflow`
# plugin source `./prflow` stays INSIDE the marketplace root (mirroring the repo-root
# marketplace's `"source": "./"` with the plugin at the root), so $CLAUDE_SKILL_DIR
# resolves to `<workspace>/.prflow/vendor/prflow/skills/<name>` — byte-identical to a
# consumer. Named `devflow-marketplace` so the baked `prflow@devflow-marketplace`
# plugin spec resolves against it once the `./` entry is swapped out below. This path
# is under the gitignored `.prflow/` tree (the agent stages only explicit paths, never the whole tree) and
# is distinct from the vendor-slice-pruned `<vendor-root>/prflow/.claude-plugin/
# marketplace.json`, so there is no collision.
MK_DIR="$VENDOR_ROOT/.claude-plugin"
# The script runs under `set -u` but NOT `set -e`, so the write is checked explicitly:
# if the mkdir or the marketplace.json write fails (unwritable dir, full/read-only FS),
# the swap below would repoint the list at $VENDOR_ROOT while the marketplace.json it
# depends on does not exist — a silently-wrong resolution wearing a green ::notice::.
# Gate the swap + success notice on a confirmed write; otherwise warn and leave the list
# on the repo-root `./` (never a non-clean path reported as clean).
# Static JSON (no interpolated values) — printf, so no apostrophe/heredoc hazard.
if ! mkdir -p "$MK_DIR" 2>/dev/null || ! printf '%s\n' \
'{' \
'  "$schema": "https://anthropic.com/claude-code/marketplace.schema.json",' \
'  "name": "devflow-marketplace",' \
'  "owner": { "name": "Daniel Radman" },' \
'  "renames": { "devflow": "prflow" },' \
'  "plugins": [' \
'    { "name": "prflow", "source": "./prflow" }' \
'  ]' \
'}' > "$MK_DIR/marketplace.json"; then
    echo "::warning::devflow compose-vendor-marketplace.sh: could not write $MK_DIR/marketplace.json (unwritable dir or full/read-only FS); the prflow plugin resolves from the repo-root marketplace (./). The composed marketplace list is left unchanged."
    exit 0
fi

# The marketplace entry emitted below is validated by `claude-code-action` before it ever
# reaches Claude Code: `base-action/src/install-plugins.ts` treats an input as a LOCAL
# PATH only when it starts with `./`, `../`, `/`, or a Windows drive prefix — anything
# else must match its `^https://….git$` marketplace-URL regex. A bare relative
# `.prflow/vendor` carries none of those prefixes, so it fell through to the regex and the
# action aborted EVERY cloud implement run in this repo with
# `Invalid marketplace URL format: .prflow/vendor` (PR #1137, reverted by #1144).
# `./.prflow/vendor` satisfies `startsWith("./")`, which the action accepts at any depth
# and passes verbatim to `claude plugin marketplace add`.
#
# Normalize HERE — at the single point that emits the entry — rather than requiring the
# caller to pass an already-prefixed path: the caller's argument also names filesystem
# paths (the manifest probe, the marketplace.json write), so a prefix obligation split
# across the boundary is exactly the shape that was missed once already. Derived with a
# bash `case` (guard-class 2: a value that decides the EMITTED result must not come from
# a non-preflight PATH tool). The Windows drive form is deliberately NOT an arm — the
# cloud implement runner is Linux (issue #1049's environment steelman), and `./`-prefixing
# a drive-lettered path would be wrong rather than merely unnecessary.
case "$VENDOR_ROOT" in
    ./*|../*|/*) MK_ENTRY="$VENDOR_ROOT" ;;
    *)           MK_ENTRY="./$VENDOR_ROOT" ;;
esac

# Rewrite the marketplaces file: swap the repo-root `./` entry for the vendored
# marketplace root. Bash builtins only (while-read + case) — guard-class 2: a value
# that decides the EMITTED marketplace list must not be derived through a non-preflight
# PATH tool (tr/sed/wc/cut/head).
SWAPPED=0
OUT=""
while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
        "./")
            OUT="${OUT:+$OUT$'\n'}$MK_ENTRY"
            SWAPPED=1
            ;;
        *)
            OUT="${OUT:+$OUT$'\n'}$line"
            ;;
    esac
done < "$MK_FILE"
# Same gate as the marketplace.json write above, for the same reason: this rewrite is the
# step that actually repoints the list at the vendored root, so an UNCHECKED write lets
# the success notice below affirm a resolution that never took effect (a `./` list wearing
# a green ::notice::). Two distinct failure shapes reach here — the open fails outright
# (unwritable path: the list keeps its previous contents, so the run resolves from the
# repo-root `./`), or the open succeeds and the write is truncated part-way (full FS: the
# list is left incomplete or empty). The annotation names both rather than promising the
# clean fallback, which only the first shape actually delivers.
if ! printf '%s\n' "$OUT" > "$MK_FILE"; then
    echo "::warning::devflow compose-vendor-marketplace.sh: could not rewrite $MK_FILE (unwritable path or full/read-only FS); the job-local marketplace was composed but the marketplace list was NOT repointed at it, so the prflow plugin does not resolve from the vendored subtree. If the write was truncated part-way the list may also be incomplete."
    exit 0
fi

if [ "$SWAPPED" -eq 1 ]; then
    # The emitted entry is named in the notice so a live run shows the exact spelling the
    # action will validate — the diagnostic that was missing when the un-prefixed form
    # shipped (PR #1137).
    echo "::notice::devflow: composed a job-local marketplace at $MK_DIR/marketplace.json and emitted the marketplace entry '$MK_ENTRY'; the prflow plugin now resolves from the vendored subtree ($PLUGIN_DIR), matching a consumer's resolution (issue #1049)."
else
    # The baseline `./` entry was not found in the combined list — the marketplace.json
    # was written but nothing consumes it. Surface it rather than resolving silently.
    echo "::warning::devflow compose-vendor-marketplace.sh: the repo-root './' marketplace entry was not present in the combined list, so the vendored marketplace was composed but not spliced in; the prflow plugin still resolves from whatever marketplace the baked baseline registered."
fi
exit 0
