#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# scaffold-config.sh — PRFlow's single config-scaffolding implementation.
#
# Drops the PRFlow config files into a repo's .prflow/ directory:
#   - config.json     scaffolded from config.example.json when absent; when it
#                     already exists it's kept (your IDs/secrets stay) and only
#                     newly-introduced keys are backfilled from the example —
#                     existing values always win, your arrays are left as-is.
#   - config.schema.json  refreshed every run (editor autocomplete/validation).
#
# This is the ONE scaffolder. Both entry points call it so the behaviour can
# never drift between them:
#   - install.sh           (cloud tier — runs from a fresh clone, $SRC)
#   - the /devflow:init skill (local tier — runs from the plugin cache)
# Because both call here, the two coexist safely: whichever runs first creates
# config.json; the other preserves it (no-clobber) and only refreshes the schema.
#
# Templates are resolved RELATIVE TO THIS SCRIPT (../.prflow), so the script is
# self-locating wherever it ships (marketplace cache, vendored plugin, or a
# clone). The caller never has to tell us where the templates are.
#
# Usage: scaffold-config.sh [TARGET_REPO_ROOT] [SCAN_ROOT]
#   TARGET_REPO_ROOT  where to write .prflow/ (default: git toplevel, else cwd)
#   SCAN_ROOT         the tree language auto-detection scans for marker files
#                     (default, and on an empty value: TARGET_REPO_ROOT). Only
#                     install.sh's dry-run preview passes a different one — it writes
#                     into a sandbox but must detect against the real repository, or
#                     the preview understates what --apply merges into config.json.
#
# Exit codes:
#   0  config.json scaffolded or kept; schema refreshed
#   2  bad arguments, or the template files are missing next to the script
set -euo pipefail

# jq binary: resolved once via the resolver sourced from the sibling lib/ directory (issue #247);
# best-effort — a copied/vendored deployment without lib/ falls back to bare
# `jq` with a breadcrumb rather than aborting under set -e.
# shellcheck source=../lib/resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/resolve-jq.sh" \
  || { echo "devflow: resolve-jq.sh could not be sourced from ../lib relative to ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }

log() { printf 'devflow-scaffold: %s\n' "$1"; }
die() { printf 'devflow-scaffold: %s\n' "$1" >&2; exit 2; }

# Atomically replace a config file with a candidate temp IFF their canonical
# (jq --sort-keys) forms differ — the shared "rewrite only on a real change"
# guard for both the backfill and the Haiku effort-cleanup passes below.
#   $1 config path   $2 candidate temp file
#   $3 log line on a successful rewrite
#   $4 log line when the comparison itself cannot be trusted
# Each side is normalized into a captured variable rather than compared via
# `diff -q <(jq …) <(jq …)`: process substitution hides the inner jq's exit
# status, so a left-hand normalization failure would read as "configs differ"
# and fire a phantom rewrite. Capturing lets us detect a jq failure explicitly
# and skip. The `mv` is guarded so a write failure (read-only FS, ENOSPC, an
# immutable file) logs-and-continues — surfacing the underlying cause — instead
# of aborting the whole best-effort scaffold under `set -euo pipefail`.
rewrite_config_if_changed() {
  local cfg="$1" cand="$2" changed_msg="$3" cmpfail_msg="$4"
  local cfg_norm cand_norm mv_err
  if ! cfg_norm="$("$DEVFLOW_JQ" --sort-keys . "$cfg" 2>/dev/null)" \
     || ! cand_norm="$("$DEVFLOW_JQ" --sort-keys . "$cand" 2>/dev/null)"; then
    log "$cmpfail_msg"
    return 0
  fi
  if [ "$cfg_norm" != "$cand_norm" ]; then
    if mv_err="$(mv "$cand" "$cfg" 2>&1)"; then
      log "$changed_msg"
    else
      log "could not write $cfg from a generated update${mv_err:+ ($mv_err)}; leaving it unchanged."
    fi
  fi
}

# Testability hook: sourcing this script with DEVFLOW_SCAFFOLD_LIB_ONLY set loads
# the helpers above (log/die/rewrite_config_if_changed) for unit tests WITHOUT
# running the scaffold. The variable is never set in normal CLI/install/init
# invocations, so this is a no-op there.
if [ -n "${DEVFLOW_SCAFFOLD_LIB_ONLY:-}" ]; then
  return 0 2>/dev/null || exit 0
fi

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# TPL_DIR is the PLUGIN'S OWN template directory, not a consumer's state directory:
# it always carries the current name, so it takes no transitional fallback.
TPL_DIR="$SELF_DIR/../.prflow"
EXAMPLE="$TPL_DIR/config.example.json"
SCHEMA="$TPL_DIR/config.schema.json"
RENAME_MAP="$SELF_DIR/../lib/rename-map.json"

[ -f "$EXAMPLE" ] || die "template not found: $EXAMPLE (is the plugin install complete?)"
[ -f "$SCHEMA" ]  || die "template not found: $SCHEMA (is the plugin install complete?)"

TARGET_ROOT="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
# The tree the language auto-detection step SCANS (issue #971). It is threaded straight
# through to detect-project-tools.sh and is used for NOTHING else here: DEST (the state
# directory this scaffolder writes) and the workflow-freshness gate it reads stay
# anchored on TARGET_ROOT. An empty or omitted value selects TARGET_ROOT — what the
# /prflow:init skill and install.sh's apply path both pass. Only install.sh's dry-run
# preview passes a different one: it writes into a sandbox holding only the installer's
# own subtrees, where detection would otherwise find no language markers and preview a
# no-op the apply does not perform.
SCAN_ROOT="${2:-}"
[ -n "$SCAN_ROOT" ] || SCAN_ROOT="$TARGET_ROOT"
# The CONSUMER'S state directory, resolved through the shared contract (issue
# #1002): canonical .prflow/, falling back LOUDLY to a superseded .devflow/ when
# only that one is present. Scaffolding a fresh .prflow/ beside an un-migrated
# .devflow/ would be the worst outcome available here — the consumer's real values
# would sit in one directory while every reader resolved a template-default config
# in the other — so this scaffolder deliberately keeps working IN PLACE on whichever
# directory the repo actually has. Relocating it is scripts/migrate-consumer-tier1.sh's
# job, and it runs before this one.
# shellcheck source=../lib/resolve-state-dir.sh
if [ -f "$SELF_DIR/../lib/resolve-state-dir.sh" ] \
   && . "$SELF_DIR/../lib/resolve-state-dir.sh" \
   && type prflow_state_dir >/dev/null 2>&1; then
  :
else
  log "resolve-state-dir.sh could not be sourced from ../lib — using the canonical .prflow/ with no transitional fallback."
  prflow_state_dir() { printf '%s' "${1:-}/.prflow"; }
fi
DEST="$(prflow_state_dir "$TARGET_ROOT")"
CONFIG="$DEST/config.json"

mkdir -p "$DEST"

# Schema is generated, never hand-edited — safe to overwrite every run so
# editors always validate against the current field set.
cp "$SCHEMA" "$DEST/config.schema.json"

if [ -f "$CONFIG" ]; then
  log "keeping existing $CONFIG"
else
  cp "$EXAMPLE" "$CONFIG"
  log "scaffolded $CONFIG — every value has a working default; edit it only to customize"
fi

# Ignore ONLY the ephemeral scratch dir (.prflow/tmp/), never the rest of
# .prflow/: config.json must be committed for the cloud tier to read it, and
# learnings/ (retrospectives) and the schema/example are tracked too. A scoped
# .prflow/.gitignore keeps this self-contained — no mutation of the repo-root
# .gitignore. Created only when absent so an adopter's edits survive re-runs.
GITIGNORE="$DEST/.gitignore"
if [ ! -f "$GITIGNORE" ]; then
  # The body names $DEST rather than a fixed '.prflow/': on an un-migrated consumer
  # this file is written INSIDE the superseded directory, and prose naming the other
  # one would describe a directory the reader cannot see.
  printf '%s\n' \
    '# PRFlow ephemeral scratch (review caches, weekly-loop temp files, issue' \
    '# drafts). Safe to delete; never commit. Everything else under this' \
    '# directory (config.json, learnings/, the schema/example) is intentionally' \
    '# tracked.' \
    '/tmp/' > "$GITIGNORE"
  log "wrote $GITIGNORE (ignores ephemeral .prflow/tmp/ scratch)"
fi

# Consumer-owned prompt-extensions directory (issue #84, extended in issue #95).
# Skills load .prflow/prompt-extensions/<skill-name>.md verbatim when present, so a
# repo can append repo-specific instructions to any skill with no plugin edit.
# Scaffold one COMMENTED, INERT <skill>.md.example PER SKILL so adopters discover
# that EVERY skill is extensible, not just create-issue. The `.example` suffix keeps
# each file from matching `<skill-name>.md`, so it never injects itself into a real
# run until a consumer deliberately renames it; and the whole body is an HTML
# comment, so even a misrename that drops `.example` injects no actionable
# instruction. mkdir -p is idempotent; the absence guard is PER FILE (not on the
# directory), so an adopter who scaffolded before issue #95 — and so has only
# create-issue.md.example — gets the remaining examples backfilled on re-run, while
# any file they created or edited (an .example OR a live <skill>.md) is never
# touched. The directory is intentionally NOT gitignored (the scoped
# .prflow/.gitignore ignores only tmp/), so a team commits and shares its
# extensions.
#
# The skill list below is authoritative and is kept in sync with skills/ by a drift
# guard in lib/test/run.sh (it derives the expected set from skills/*/ and fails if
# the scaffolder forgets one). Each row is <skill-name>|<one-line hint>. Keep both
# fields apostrophe-free ASCII: a hint reaches a printf arg below, and an ASCII
# apostrophe in a single-quoted bash string would terminate it (shellcheck
# SC1073/SC1011) while a curly apostrophe would trip SC1112 (see CLAUDE.md).
EXTENSIONS_DIR="$DEST/prompt-extensions"
# Guard the directory create like every other write in this file: a failure
# (read-only .prflow, ENOSPC, perms) logs-and-skips the prompt-extension scaffolding
# rather than aborting the whole best-effort scaffold under `set -euo pipefail` (the
# documented contract at the top of this file). `mkdir -p` on an already-present
# directory is a success no-op, so this is idempotent.
if ! pe_mkdir_err="$(mkdir -p "$EXTENSIONS_DIR" 2>&1)"; then
  log "could not create $EXTENSIONS_DIR${pe_mkdir_err:+ ($pe_mkdir_err)}; skipping prompt-extension example scaffolding (scaffold continues)."
else
  pe_created=0
  while IFS='|' read -r pe_skill pe_hint; do
    [ -n "$pe_skill" ] || continue
    pe_target="$EXTENSIONS_DIR/$pe_skill.md.example"
    pe_live="$EXTENSIONS_DIR/$pe_skill.md"
    # Per-file backfill, two skip conditions in one guard (issue #118): skip when the
    # .example already exists (an adopter's edited example — never clobber it), OR when a
    # LIVE <skill>.md already exists (the adopter activated this extension, so dropping a
    # redundant <skill>.md.example beside it is just confusing clutter). Both are `[ -e ]`
    # tests inside the `if` condition (exempt from `set -e`) leading to a single rc-0
    # `continue`, so the guard cannot abort the loop under `set -euo pipefail`; the live
    # <skill>.md is read-only here (never created, modified, or deleted), and only absent
    # .example files for un-activated skills are created.
    if [ -e "$pe_target" ] || [ -e "$pe_live" ]; then
      continue
    fi
    # The body is itself one Markdown comment block: the first line opens `<!--`, the
    # last closes `-->`. printf '%s\n' prints each argument on its own line, so the
    # static lines (single-quoted, apostrophe-free ASCII) and the two interpolated
    # lines ($pe_skill / $pe_hint, double-quoted) compose in a single call.
    #
    # Write to a temp then `mv` into place ATOMICALLY — the same write-candidate-then-mv
    # idiom rewrite_config_if_changed uses above. This is the log-and-continue contract
    # (a per-file failure must not abort the whole scaffold under `set -e`: the `if`
    # condition exempts the failure, and the breadcrumb names the file) PLUS atomicity:
    # the final `<skill>.md.example` only ever appears complete, so a failed/partial
    # write (read-only dir, ENOSPC mid-write) can never leave a truncated file at the
    # guarded path that the `[ -e ]` guard above would then treat as present and never
    # retry. On failure only the temp is removed; the guarded path is untouched.
    pe_tmp="$pe_target.tmp"
    # The body is written in three grouped printf calls so the create-issue example can
    # carry INERT `## Audit dimensions` (Step 3.6 audit forwarding) and `## Evidence axes`
    # (Step 2 evidence-bundle forwarding, issue #548) samples between the boilerplate and the
    # closing `-->`. The samples stay
    # INSIDE the comment block, so the whole body is still a single HTML comment (the
    # scaffold-pe AC3 single-comment-block invariant holds) and a misrename injects nothing.
    # No bash array is used (`"${arr[@]}"` on an empty array errors under macOS bash 3.2 +
    # `set -u`); a per-skill `if` branch keeps it portable.
    # Chain the three printf calls with `&&` so an intermediate write failure propagates
    # as the brace group's exit status (a group's status is otherwise its LAST command —
    # the tiny closing `-->` printf — which could clear after an earlier printf failed and
    # promote a truncated file). This restores the pre-refactor single-printf "any write
    # error fails closed" contract that the atomic-mv comment below relies on.
    if {
         printf '%s\n' \
           '<!--' \
           "DevFlow prompt-extension example for the $pe_skill skill." \
           '' \
           'This directory holds consumer-owned prompt extensions for DevFlow skills.' \
           'Drop a file named <skill-name>.md here (no .example suffix) and its contents' \
           'are appended VERBATIM to the end of that skill prompt every time it runs. It' \
           'is an upgrade-safe way to add repo-specific instructions without forking the' \
           'plugin. Marketplace updates never touch this directory. When no file exists' \
           'for a skill, that skill behaves exactly as it does today (the no-op path).' \
           '' \
           "Useful extension for $pe_skill: $pe_hint" \
           '' \
           'To activate, copy this file to the same name without the .example suffix' \
           '(for example create-issue.md.example becomes create-issue.md) and replace' \
           'this comment with your own instructions.' &&
         { [ "$pe_skill" != "create-issue" ] || printf '%s\n' \
             '' \
             'Step 3.6 (the fresh-context audit) reads an optional "## Audit dimensions"' \
             'section from this extension and forwards it to the audit subagent. Example' \
             'section (inert until you activate this file):' \
             '' \
             '## Audit dimensions' \
             '- A repo-specific invariant every issue must respect, named with what would falsify it.' \
             '' \
             'Step 2 (the independent-derivation evidence-bundle sub-pass) reads an optional' \
             '"## Evidence axes" section and appends it to the generic evidence-axis floor.' \
             'Example section (inert until you activate this file):' \
             '' \
             '## Evidence axes' \
             '- A repo-specific evidence axis every issue must record, named with what to check.'; } &&
         printf '%s\n' '-->'
       } > "$pe_tmp" && mv "$pe_tmp" "$pe_target"; then
      pe_created=$((pe_created + 1))
    else
      # Remove only the temp candidate — never a partial $pe_target (mv is atomic, so
      # the guarded path was never partially written). A lingering temp is harmless: it
      # ends in .tmp (not .md.example), so it matches neither the loader nor the
      # backfill `[ -e "$pe_target" ]` guard, and a later re-run truncates it anew.
      rm -f "$pe_tmp"
      log "could not write $pe_target; skipping this prompt-extension example (scaffold continues)."
    fi
  done <<'PE_SKILLS'
create-issue|extend the generated issue body with links to your house tracker or test-case system
docs|point the docs pass at extra documentation roots specific to your repo
docs-bootstrap-external|describe your public docs-site structure so the external bootstrap matches it
docs-bootstrap-internal|name the internal doc conventions and directory layout your team follows
docs-release-notes|match your release-notes house style, audience, and changelog format
docs-sync-external|list which internal sections are confidential and must never reach external docs
docs-sync-internal|flag the code areas whose internal docs your team keeps especially current
docs-verify|name the topics whose internal docs your team treats as load-bearing
implement|add repo-specific implementation constraints the orchestrator must honor
init|add post-scaffold setup steps unique to your repo
pr-description|enforce your PR-description template sections and required labels
receiving-code-review|add house rules for how review feedback is evaluated, verified, and pushed back on
requesting-code-review|tune what the internalized final-pass reviewer prioritizes for your codebase
retrospective|add house criteria for what counts as a clean PR in the retrospective
retrospective-audit|name the intervention patterns your team prioritizes when auditing
retrospective-weekly|tune which authors and time window the weekly loop scans
review|add house review rules the reviewer must enforce
review-and-fix|add house review rules and fix-loop guardrails specific to your repo
PE_SKILLS
  if [ "$pe_created" -gt 0 ]; then
    log "created/backfilled $pe_created prompt-extension example(s) in $EXTENSIONS_DIR/ (rename <skill>.md.example to <skill>.md to activate)"
  fi
fi

# ── Superseded config-key migration, and the gate that guards it ─────────────
# (issues #988 and #1002.) The seven brand-named top-level keys are renamed in
# place, carrying the consumer values across. This lives HERE, beside the backfill
# it has to coordinate with, because this file is the ONE scaffolder both entry
# points call — siting it anywhere else would let install.sh and /prflow:init drift.
#
# ORDER IS LOAD-BEARING: gate, then migrate, then backfill. Migrating first means
# the new keys already hold the consumer values when the deep merge runs, so the
# merge finds nothing absent to graft. The backfill guard further down is the belt
# to that braces: it covers the refusal path and the two paths where the migration
# was skipped for want of its own inputs — an absent rename map, or no working
# python3. It does NOT cover an unusable jq, because that skips the whole backfill
# below and there is then no graft to guard against (restated at the guard itself).
#
# The gate reads the two workflow files install.sh SHIPS and can therefore refresh.
# Its permissive answer is "no superseded reads found", which is exactly what a
# missing or failing scanner also produces, so it fails CLOSED: only a scan that
# ran AND came back empty allows the migration. The three retained withheld-tier
# files are deliberately OUT of the gate (install.sh cannot refresh them, so
# blocking forever on one would be worse than reporting it) — they are reported by
# name instead, further down.
PRFLOW_WORKFLOW_SCAN_PY='
import re, sys

# A superseded read is either a brand-named config key or the superseded vendored
# path / state directory. Both mean the file predates the rename and would read a
# config this run is about to move out from under it.
# Issue #1041 renamed the two `workflows.*` sub-keys (workflows.devflow ->
# workflows.prflow, workflows.devflow-review -> workflows.prflow-review), so a
# shipped workflow still reading `.workflows.devflow` now DOES count as staleness:
# the enable read would resolve absent -> false and silently disable the workflow
# the migrated config just re-keyed. There is therefore no `workflows` lookbehind
# any more -- a fresh shipped workflow reads `.workflows.prflow` and carries no
# `.devflow` at all, so it still passes clean.
KEY = re.compile(r"\.devflow(?![A-Za-z])")
BARE = re.compile(r"\bdevflow_(version|implement|runner|review_and_fix|review|retrospective)(?![A-Za-z0-9_])")

stale = []
for path in sys.argv[1:]:
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        # Absent is not stale: a consumer who never installed that workflow has
        # nothing that could read the config out of date.
        continue
    except Exception as exc:
        sys.stderr.write("could not read " + path + ": " + str(exc) + "\n")
        sys.exit(2)
    if KEY.search(text) or BARE.search(text):
        stale.append(path)
if stale:
    sys.stdout.write("\n".join(stale))
    sys.exit(1)
sys.exit(0)
'

# The migration itself. Plans and applies in one pass over a copy, printing one
# report line per key it changed and per conflict it refused to resolve.
#   exit 0  a usable result was written to $2 (which may be byte-identical)
#   exit 2  the config or the rename map could not be read/parsed -- write nothing
PRFLOW_MIGRATE_PY='
import json, sys

cfg_path, out_path, map_path, example_path = sys.argv[1:5]
try:
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    with open(map_path, encoding="utf-8") as fh:
        full_map = json.load(fh)
        renames = full_map["config_keys"]
        # Issue #1041: the two workflows.* sub-keys migrate behind THIS same gate.
        # An older rename map without the section leaves the nested pass a no-op.
        wf_renames = full_map.get("workflows_config_keys") or {}
    with open(example_path, encoding="utf-8") as fh:
        example = json.load(fh)
except Exception as exc:
    sys.stderr.write(str(exc) + "\n")
    sys.exit(2)
if not isinstance(cfg, dict) or not isinstance(renames, dict) or not isinstance(wf_renames, dict):
    sys.stderr.write("config or rename map is not an object\n")
    sys.exit(2)

changed = []
conflicts = []


def migrate_keys(source, renames_map, ex, prefix):
    # Rename each superseded key to its current spelling IN PLACE, carrying the
    # value across verbatim (so a valid-falsy false/0/"" keeps its meaning --
    # issue #312). Returns the rebuilt block. Every key the map does not name is
    # written back exactly as read. prefix is the report display prefix.
    result = {}
    for key, value in source.items():
        new = renames_map.get(key)
        if new is None:
            result[key] = value
            continue
        if new not in source:
            result[new] = value
            changed.append(prefix + key + " -> " + prefix + new)
            continue
        # Both present: the new key either still holds the shipped example default
        # (grafted by a deep merge, not authored) or it differs (a deliberate edit
        # a rename must not discard).
        if new in ex and source[new] == ex[new]:
            changed.append(
                prefix + key + " -> " + prefix + new + " (the existing " + prefix + new
                + " block still held the shipped example default and was replaced)")
            continue
        conflicts.append((prefix + key, prefix + new))
        result[key] = value
    # Second pass for the both-present-and-example-valued case: the superseded
    # value wins, written at the position the new key already occupies.
    for old, new in renames_map.items():
        if old in source and new in source and new in ex and source[new] == ex[new]:
            result[new] = source[old]
    return result


out = migrate_keys(cfg, renames, example if isinstance(example, dict) else {}, "")

# Nested workflows.* sub-key migration (issue #1041), under the SAME freshness gate
# the caller already cleared. Only when the block is an object -- a scalar/array/
# null workflows value carries through structurally, untouched.
wf = out.get("workflows")
if isinstance(wf, dict) and wf_renames:
    ex_wf = example.get("workflows") if isinstance(example, dict) else None
    if not isinstance(ex_wf, dict):
        ex_wf = {}
    out["workflows"] = migrate_keys(wf, wf_renames, ex_wf, "workflows.")

with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=2)
    fh.write("\n")

for line in changed:
    sys.stdout.write("CHANGED\t" + line + "\n")
for old_disp, new_disp in conflicts:
    sys.stdout.write("CONFLICT\t" + old_disp + "\t" + new_disp + "\n")
'

if [ ! -f "$RENAME_MAP" ]; then
  log "rename map not found at $RENAME_MAP; skipping the superseded config-key migration (is the plugin install complete?)."
elif ! command -v python3 >/dev/null 2>&1; then
  log "no working python3; skipping the superseded config-key migration and leaving $CONFIG unchanged (the backfill guard below still refuses to graft a new-name key beside a superseded one)."
else
  # The gate. Exactly the two filenames install.sh ships.
  gate_out=""
  gate_rc=0
  gate_out="$(python3 -c "$PRFLOW_WORKFLOW_SCAN_PY" \
      "$TARGET_ROOT/.github/workflows/devflow.yml" \
      "$TARGET_ROOT/.github/workflows/devflow-implement.yml" 2>&1)" || gate_rc=$?
  if [ "$gate_rc" -eq 1 ]; then
    log "NOT migrating superseded config keys: these shipped workflow files still read the superseded names and would be left reading a config that moved out from under them — $(printf '%s' "$gate_out" | tr '\n' ' '). Run install.sh --apply to refresh them, then re-run."
  elif [ "$gate_rc" -ne 0 ]; then
    log "NOT migrating superseded config keys: the shipped-workflow freshness scan could not be performed${gate_out:+ ($gate_out)}. Refusing rather than reading a failed scan as a clean one."
  else
    MIGRATE_TMP="$(mktemp)"; MIGRATE_ERR="$(mktemp)"
    trap 'rm -f "$MIGRATE_TMP" "$MIGRATE_ERR"' EXIT
    mig_rc=0
    mig_out="$(python3 -c "$PRFLOW_MIGRATE_PY" "$CONFIG" "$MIGRATE_TMP" "$RENAME_MAP" "$EXAMPLE" 2>"$MIGRATE_ERR")" || mig_rc=$?
    if [ "$mig_rc" -ne 0 ]; then
      mig_err="$(cat "$MIGRATE_ERR")"
      log "superseded config-key migration could not read $CONFIG${mig_err:+ ($mig_err)}; leaving it unchanged."
    else
      # Report BEFORE the swap, so the lines are emitted even when the rewrite
      # guard decides the canonical forms match and writes nothing.
      while IFS="$(printf '\t')" read -r kind detail extra; do
        [ -n "$kind" ] || continue
        case "$kind" in
          CHANGED)
            log "migrated superseded config key in $CONFIG: $detail" ;;
          CONFLICT)
            log "NOT migrating $detail in $CONFIG: both it and $extra are present and $extra differs from the shipped example, so it is a deliberate edit this migration must not discard. Resolve it by hand — delete the $detail block to keep your $extra value, or delete the $extra block to have $detail migrated on the next run." ;;
        esac
      done <<PRFLOW_MIG_REPORT
$mig_out
PRFLOW_MIG_REPORT
      rewrite_config_if_changed "$CONFIG" "$MIGRATE_TMP" \
        "renamed superseded config keys in $CONFIG (your values carried across unchanged)." \
        "could not compare the migrated config against $CONFIG; leaving it unchanged."
    fi
    rm -f "$MIGRATE_TMP" "$MIGRATE_ERR"
    trap - EXIT
  fi
fi

# ── Superseded VALUE / nested-key migration, and the residual notice (#1028) ─
# The key migration above renames TOP-LEVEL keys and stops there, so a consumer's
# config still spelt the superseded product name in its values and nested keys: the
# `agent_overrides` `devflow:<leaf>` keys, the `workpad_marker` value, and the
# `docs.labels` / `deferred.labels` provenance-label values. lib/migrate-config-values.py
# renames those, so the config reads prflow / PRFlow throughout, and reports what
# deliberately STAYS (the frozen `workflows.*` keys, plus a pointer to the separate
# DEVFLOW_* environment freeze that no config migration can reach).
#
# It takes NO freshness gate, deliberately. The key migration needs one because the
# trigger-time channel reads those key NAMES out of the workflow files, so a config that
# moves ahead of a stale workflow is silently mis-read. These are values and nested keys
# whose readers all dual-accept in both directions, so no such skew exists — including
# resolve-implement-trigger.sh's self-trigger guard, which DERIVES the superseded marker
# from the configured one and so keeps recognising a pre-rename workpad.
#
# ORDER IS LOAD-BEARING, for the same reason the key migration runs before the backfill:
# renaming FIRST means the current-spelled entry already holds the consumer's value when
# the deep merge runs, so the merge finds nothing absent to graft and tops the entry up
# with the example's sibling defaults in that same run. Running this AFTER the backfill
# instead was measured to leave the config unsettled for one extra run — the merge grafts
# the whole example entry, this pass replaces it with the consumer's (narrower) one, and
# the NEXT run's merge re-adds the siblings it dropped. The both-present arm still covers
# a consumer whose config was grafted by an EARLIER run: that graft is on disk before this
# pass starts, so the helper resolves it here rather than reporting a conflict that is not
# one.
#
# Best-effort, like every other pass here: a missing python3, helper or rename map skips
# it with a breadcrumb and leaves the config untouched. Every selection — what to rename,
# what to refuse, what to report — is made inside python3 (a preflight-guaranteed tool),
# never through a non-preflight PATH tool (tr/sed/wc/cut); guard-class 2.
MIGRATE_VALUES="$SELF_DIR/../lib/migrate-config-values.py"
if [ ! -f "$MIGRATE_VALUES" ] || [ ! -f "$RENAME_MAP" ]; then
  log "value-migration helper or rename map not found next to the scaffolder; skipping the superseded config-value migration (is the plugin install complete?)."
elif ! command -v python3 >/dev/null 2>&1; then
  log "no working python3; skipping the superseded config-value migration and leaving $CONFIG unchanged."
else
  VALUES_TMP="$(mktemp)"; VALUES_ERR="$(mktemp)"
  trap 'rm -f "$VALUES_TMP" "$VALUES_ERR"' EXIT
  val_rc=0
  val_out="$(python3 "$MIGRATE_VALUES" "$CONFIG" "$VALUES_TMP" "$RENAME_MAP" "$EXAMPLE" 2>"$VALUES_ERR")" || val_rc=$?
  if [ "$val_rc" -ne 0 ]; then
    val_err="$(cat "$VALUES_ERR")"
    log "superseded config-value migration could not read $CONFIG${val_err:+ ($val_err)}; leaving it unchanged."
  else
    # Piped rather than fed from a heredoc: the report carries backticks and the
    # scaffolder's other heredoc report uses an UNQUOTED delimiter, which would run
    # them as command substitutions. A quoted delimiter cannot expand $val_out at all,
    # so the pipe is the shape that both interpolates the report and treats it as data.
    # The subshell is harmless here — the loop only logs and assigns nothing the caller
    # reads back.
    printf '%s\n' "$val_out" | while IFS="$(printf '\t')" read -r kind detail extra; do
      [ -n "$kind" ] || continue
      case "$kind" in
        CHANGED)
          log "migrated superseded config value in $CONFIG: $detail" ;;
        CONFLICT)
          log "NOT migrating the $detail override key in $CONFIG: both it and $extra are present and $extra is not the shipped example default, so it is a deliberate edit this migration must not discard. Resolve it by hand — delete whichever entry you do not want; both spellings resolve, and $extra is the one the engine resolves first." ;;
        NOTE|ADVISORY)
          log "$detail" ;;
      esac
    done
    rewrite_config_if_changed "$CONFIG" "$VALUES_TMP" \
      "renamed superseded values and nested keys in $CONFIG (every other value carried across unchanged)." \
      "could not compare the value-migrated config against $CONFIG; leaving it unchanged."
  fi
  rm -f "$VALUES_TMP" "$VALUES_ERR"
  trap - EXIT
fi

# The plugin version pin is REPORTED, never gated on. Its freshness is not
# decidable here: the pin accepts a mutable branch name, the installed plugin tree
# carries no .git to ask about ancestry, and install.sh fetches with --depth 1. A
# gate on it would refuse on every real path and make the migration unreachable,
# so this discloses instead of guessing (issue #988).
if command -v python3 >/dev/null 2>&1 && [ -f "$CONFIG" ]; then
  pin_value="$(PRFLOW_CFG="$CONFIG" python3 -c '
import json, os, sys
try:
    with open(os.environ["PRFLOW_CFG"], encoding="utf-8") as fh:
        data = json.load(fh)
except Exception:
    sys.exit(0)
if not isinstance(data, dict):
    sys.exit(0)
for key in ("prflow_version", "devflow_version"):
    if isinstance(data.get(key), str) and data[key]:
        sys.stdout.write(key + "=" + data[key])
        break
' 2>/dev/null || true)"
  if [ -n "$pin_value" ]; then
    # Stated as a CONDITIONAL, never as a finding about this pin. Whether a given ref
    # predates the rename is not decidable here (it accepts a mutable branch name, the
    # installed plugin tree carries no .git, and the installer fetch is --depth 1), so
    # asserting it would be a guess — and a wrong one on the common path where
    # /prflow:init has just stamped the current plugin version.
    log "plugin version pin is $pin_value (reported, not checked — this helper cannot decide whether a ref predates the rename). IF that ref predates it, cloud runs vendor a plugin that resolves the superseded directory and key names, so those reads resolve to their defaults; advance it to a ref that contains the rename. install.sh --apply re-stamps a SHA-shaped pin automatically, and a deliberate branch or tag pin is preserved and is yours to move."
  fi
fi

# Report, by name, any workflow file present on disk that install.sh does not ship
# and therefore cannot refresh. Reported on EVERY run — not only when the config
# still carries superseded keys — so the warning does not fall silent on the run
# after the one that made those files stale (issue #988).
for _retained in devflow-review.yml devflow-runner.yml telemetry-push.yml; do
  if [ -f "$TARGET_ROOT/.github/workflows/$_retained" ]; then
    log "$_retained is present in .github/workflows/ but is NOT shipped by install.sh, so no installer run can refresh it. If it still names the superseded state directory or vendored path, its helper invocations will not resolve after the migration — update or remove it by hand."
    # #1041: devflow-review.yml is the ONE retained reader of a MIGRATED config
    # sub-key — it reads `.workflows["devflow-review"] // false`. The freshness gate
    # scans only the two SHIPPED workflows (install.sh cannot refresh a withheld file,
    # so gating on it would block the whole config-key migration forever), so the
    # devflow-review -> prflow-review rename is NOT coordinated with this file the way
    # the shipped workflows are. When the migration moves the key, this retained file
    # reads the now-absent old key as `false` and the auto-review tier silently stops.
    # That silent disable is the exact hazard #1041 exists to prevent, so surface it
    # LOUDLY by name rather than letting it pass — the retained file's own review-key
    # rename is the operator's to do by hand (or remove the withheld tier outright).
    if [ "$_retained" = "devflow-review.yml" ]; then
      log "  ALSO: devflow-review.yml reads the workflows.devflow-review config toggle, which #1041 renamed to workflows.prflow-review. The freshness gate cannot refuse on an unshipped file, so once your config migrates to workflows.prflow-review this retained workflow reads the now-absent old key as false and its auto-review silently stops. Update devflow-review.yml to read .workflows[\"prflow-review\"], or remove the withheld tier with install.sh --remove-withheld-review-tier."
    fi
  fi
done

# Backfill newly-introduced keys into an EXISTING config.json. A recursive
# deep-merge ($example * $config) adds any key present in the example but absent
# from the repo's config — at any nesting depth (e.g. prflow_runner.provision_env)
# — so an in-place upgrade (re-run install.sh / /devflow:init) lets adopters
# discover and opt into new features instead of silently drifting behind the
# example. jq's `*` recurses objects with the RIGHT operand winning, so a value
# the user already set is never overwritten and an array they already have
# (e.g. allowed_tools) is kept with its exact contents (arrays are replaced by the
# right operand — the user's — not merged/reordered/deduped). Recursion stops
# wherever the user's value diverges in type from the example (e.g. a scalar where
# the example now nests an object): the user's value still wins wholesale, so
# nested defaults under it are NOT backfilled. A key the user deleted is re-added
# with its documented default; PRFlow doesn't track deletions.
# Best-effort, mirroring detect-project-tools.sh (trap-guarded temp, non-fatal
# logs): a missing jq, a malformed config.json, or a jq merge/compare failure logs
# and skips without aborting the scaffold. Only rewrites when the merge actually
# changes something, so an up-to-date config is a quiet no-op (no mtime churn).
# Runs before detection so the tool/setup union below operates on a config that
# already has the full key set.
if ! "$DEVFLOW_JQ" --version >/dev/null 2>&1; then
  log "no usable jq (missing or not executable); skipping config-key backfill (install jq, or set DEVFLOW_JQ to a working jq/jq.exe, to migrate newly-added keys)."
elif ! "$DEVFLOW_JQ" -e . "$CONFIG" >/dev/null 2>&1; then
  log "existing $CONFIG is not valid JSON; skipping config-key backfill (fix or delete it to re-scaffold)."
else
  BACKFILL_TMP="$(mktemp)"; BACKFILL_ERR="$(mktemp)"
  trap 'rm -f "$BACKFILL_TMP" "$BACKFILL_ERR"' EXIT
  if ! "$DEVFLOW_JQ" -n --slurpfile ex "$EXAMPLE" --slurpfile cfg "$CONFIG" \
        --slurpfile ren "$RENAME_MAP" \
        --argjson have_map "$([ -f "$RENAME_MAP" ] && echo true || echo false)" '
        ($cfg[0].prflow_review.agent_overrides? // {}) as $userao
        | ($cfg[0]) as $orig
        | (if $have_map then ($ren[0].config_keys // {}) else {} end) as $renames
        | (if $have_map then ($ren[0].workflows_config_keys // {}) else {} end) as $wfrenames
        | ($ex[0] * $cfg[0])
        # SUPERSEDED-KEY ANTI-GRAFT GUARD (issues #988, #1002). The deep merge adds
        # any key the example has and the config lacks, so once the example carries
        # the new names it would create every new block holding EXAMPLE DEFAULTS
        # beside the consumers untouched superseded blocks -- readers would then
        # resolve the new key and get defaults instead of the values that are right
        # there. Drop any new-name key the merge grafted while its superseded
        # counterpart is still present in the ORIGINAL config. Keying on $orig (not
        # on the merged result) is what makes this hold on every path: the migration
        # path (nothing left to guard), the refusal path, and the path where the
        # migration was skipped. When jq itself is unusable the whole backfill is
        # skipped, so no graft is possible there either.
        | reduce ($renames | to_entries[]) as $pair (.;
            if ($orig | has($pair.key)) and (($orig | has($pair.value)) | not)
            then del(.[$pair.value]) else . end)
        # NESTED workflows.* anti-graft (issue #1041). Same shape as the top-level
        # guard, scoped to the workflows block: drop a grafted workflows.<new> the
        # merge added while the ORIGINAL config still carries workflows.<old>, so a
        # deliberate valid-falsy workflows.devflow:false is never shadowed by a
        # grafted workflows.prflow:true (issue #312). Guards $orig.workflows being a
        # non-object.
        | if (.workflows | type) == "object" then
            .workflows = (reduce ($wfrenames | to_entries[]) as $pair (.workflows;
              if (($orig.workflows | type) == "object")
                 and ($orig.workflows | has($pair.key))
                 and (($orig.workflows | has($pair.value)) | not)
              then del(.[$pair.value]) else . end))
          else . end
        | if (.prflow_review | type) == "object" and (.prflow_review.agent_overrides | type) == "object" then
            .prflow_review.agent_overrides |= with_entries(
              # Do NOT let the deep-merge GRAFT an effort from the example onto a
              # Haiku-pinned entry the user left effort-less. The shipped example
              # pins the deduper to Sonnet 5 WITH effort; merged onto a config that
              # re-pins that key to a Haiku id, the merge would add the effort from
              # the example (Claude Haiku rejects effort with HTTP 400) and re-graft
              # it on every re-scaffold, fighting the cleanup below forever. Strip
              # ONLY a grafted effort (Haiku model + effort present + the user
              # supplied none); a user-set stale effort is preserved here and
              # repaired by the dedicated Haiku effort-cleanup below, so that the
              # migration first-run behavior is unchanged. (NOTE: this comment lives
              # inside a single-quoted jq program — keep it apostrophe-free.)
              .key as $k
              | if (.value | type) == "object"
                   and (((.value.model | strings) // "") | (. == "haiku" or startswith("claude-haiku-")))
                   and (.value | has("effort"))
                   and (($userao[$k] // {}) | (type == "object" and has("effort")) | not)
                then .value |= del(.effort) else . end)
          else . end' \
        > "$BACKFILL_TMP" 2>"$BACKFILL_ERR"; then
    # A genuine merge failure (odd jq build, OOM, corrupt template) is logged and
    # skipped — never masked as a silent no-op, and never aborts the scaffold. The
    # captured jq stderr is surfaced so the failure mode is actionable rather than
    # a fixed, ambiguous "(jq error)".
    bf_err="$(cat "$BACKFILL_ERR")"
    log "config-key backfill merge failed (jq error)${bf_err:+: $bf_err}; leaving $CONFIG unchanged."
  else
    # Rewrite only when the merge actually changed something; a jq normalization
    # failure leaves the config untouched (fail-safe) rather than overwriting
    # from a comparison we can't trust. See rewrite_config_if_changed.
    rewrite_config_if_changed "$CONFIG" "$BACKFILL_TMP" \
      "backfilled newly-added keys into $CONFIG from the example (your values and arrays kept)." \
      "could not compare the merged config against $CONFIG; leaving it unchanged."
  fi
  rm -f "$BACKFILL_TMP" "$BACKFILL_ERR"
  trap - EXIT
fi

# Repair model/effort combinations the model API rejects but the no-clobber
# backfill above structurally cannot fix. The shipped example once pinned the
# checklist-deduper to a Haiku id and carried an `effort` key on it; the example
# now defaults that override to Sonnet 5, but a key *removal* never propagates
# through the backfill — it only ADDS keys, never deletes (see the
# deletion-tracking note above). So an adopter who scaffolded earlier silently
# keeps `effort` on a Haiku override (their own deduper pin, or any other agent
# they pinned to Haiku), which the model API rejects (see the graft-guard above
# for the Haiku-rejects-effort / HTTP-400 rationale). This data-driven cleanup
# drops `effort` from any agent_overrides entry whose `model` is a Haiku id —
# narrow (only that combination), idempotent, and best-effort with the same
# mtime-churn guard as the backfill: an already-clean config is a quiet no-op.
# Lives here, not in the backfill, because it removes a key rather than adding
# one. (The backfill separately refuses to GRAFT the example's Sonnet-deduper
# effort onto a Haiku-pinned entry, so the two passes never churn against each
# other on a re-scaffold.)
if "$DEVFLOW_JQ" --version >/dev/null 2>&1 && "$DEVFLOW_JQ" -e . "$CONFIG" >/dev/null 2>&1; then
  # Anti-silent-failure breadcrumb: if agent_overrides exists but is not an
  # object (hand-corrupted to an array/string/scalar), the cleanup filter below
  # still RUNS but no-ops via its `else .` arm (leaving the malformed value as-is).
  # Surface that we saw it, so the no-op is not an ambiguous "nothing to do" — and
  # word it as a no-op, NOT a "skip", so nobody mistakes it for the genuine
  # jq-missing skip below and adds a real `continue` that would strand the EXIT
  # trap set just after this probe. Capture the probe's exit status
  # (via `|| ao_rc=$?`, which keeps the failing assignment off `set -e`) instead
  # of folding a jq error into "null" with `|| printf 'null'`: when `prflow_review`
  # ITSELF is a non-object (e.g. a string), `.agent_overrides` indexing errors
  # (rc≠0) rather than yielding "null", and the old fold suppressed this very
  # breadcrumb — leaving only the generic "cleanup failed (jq error)" line below
  # to (mis)explain a corrupt config. Distinguish probe-error from genuinely-absent.
  ao_rc=0
  ao_type="$("$DEVFLOW_JQ" -r '.prflow_review.agent_overrides | type' "$CONFIG" 2>/dev/null)" || ao_rc=$?
  if [ "$ao_rc" -ne 0 ]; then
    log "could not inspect .prflow_review.agent_overrides in $CONFIG (jq error — is prflow_review itself a non-object?); the Haiku effort-cleanup below will no-op."
  elif [ "$ao_type" != "object" ] && [ "$ao_type" != "null" ]; then
    log "agent_overrides is present but not an object ($ao_type); the Haiku effort-cleanup below will no-op (the non-object value is left untouched)."
  fi
  # issue #1646: rewrite each agent_overrides `model` to its accepted alias BEFORE the
  # Haiku effort-strip (so a rewritten Haiku id hits that strip's alias arm); keep these
  # family arms in sync with VALID_MODELS (resolve-review-overrides.py) and the schema enum.
  MODELALIAS_TMP="$(mktemp)"; MODELALIAS_ERR="$(mktemp)"
  trap 'rm -f "$MODELALIAS_TMP" "$MODELALIAS_ERR"' EXIT
  if ! "$DEVFLOW_JQ" '
        if (.prflow_review | type) == "object" and (.prflow_review.agent_overrides | type) == "object" then
          .prflow_review.agent_overrides |= with_entries(
            if (.value | type) == "object" and ((.value.model | type) == "string")
            then .value.model |= (
              if startswith("claude-sonnet-") then "sonnet"
              elif startswith("claude-opus-") then "opus"
              elif startswith("claude-haiku-") then "haiku"
              elif startswith("claude-fable-") then "fable"
              else . end)
            else . end)
        else . end' "$CONFIG" > "$MODELALIAS_TMP" 2>"$MODELALIAS_ERR"; then
    ma_err="$(cat "$MODELALIAS_ERR")"
    log "agent_overrides model-alias rewrite failed (jq error)${ma_err:+: $ma_err}; leaving $CONFIG unchanged."
  else
    rewrite_config_if_changed "$CONFIG" "$MODELALIAS_TMP" \
      "rewrote agent_overrides model values to their accepted aliases (sonnet/opus/haiku/fable) in $CONFIG." \
      "could not compare the model-alias rewrite against $CONFIG; leaving it unchanged."
  fi
  rm -f "$MODELALIAS_TMP" "$MODELALIAS_ERR"
  trap - EXIT
  CLEANUP_TMP="$(mktemp)"; CLEANUP_ERR="$(mktemp)"
  trap 'rm -f "$CLEANUP_TMP" "$CLEANUP_ERR"' EXIT
  if ! "$DEVFLOW_JQ" '
        if (.prflow_review | type) == "object" and (.prflow_review.agent_overrides | type) == "object" then
          .prflow_review.agent_overrides |= with_entries(
            if (.value | type) == "object"
               and (((.value.model | strings) // "") | (. == "haiku" or startswith("claude-haiku-")))
               and (.value | has("effort"))
            then .value |= del(.effort) else . end)
        else . end' "$CONFIG" > "$CLEANUP_TMP" 2>"$CLEANUP_ERR"; then
    # Surface the captured jq stderr so a genuine execution failure is actionable
    # rather than a fixed, ambiguous "(jq error)".
    cu_err="$(cat "$CLEANUP_ERR")"
    log "Haiku effort-cleanup failed (jq error)${cu_err:+: $cu_err}; leaving $CONFIG unchanged."
  else
    rewrite_config_if_changed "$CONFIG" "$CLEANUP_TMP" \
      "removed unsupported 'effort' from Haiku-pinned agent_overrides in $CONFIG (Claude Haiku rejects effort with HTTP 400)." \
      "could not compare the Haiku effort-cleanup against $CONFIG; leaving it unchanged."
  fi
  rm -f "$CLEANUP_TMP" "$CLEANUP_ERR"
  trap - EXIT
else
  # The backfill block above already logs the specific reason for the SAME guard
  # (jq missing / invalid JSON); cross-reference it here so this line reads as one
  # resolved cause rather than a second, distinct problem — while still emitting
  # its own breadcrumb so the model-alias rewrite and Haiku migration are never
  # silently dependent on the backfill block for their skip notice.
  log "skipping Haiku effort-cleanup and the agent_overrides model-alias rewrite for the same reason as the backfill skip above (jq missing or $CONFIG not valid JSON)."
fi

# Language-aware tool/runtime auto-population. Scans the target repo and merges
# the matching per-language presets into config.json (idempotent union — safe
# whether config.json was just scaffolded or kept). Lives in its own script so
# the dumb file-copy above stays inspection-free; best-effort, so a missing jq
# never blocks the scaffold. Both entry points (install.sh + /devflow:init)
# reach it through here, so detection can't drift between them.
DETECT="$SELF_DIR/detect-project-tools.sh"
if [ -x "$DETECT" ]; then
  # SCAN_ROOT is already resolved to a non-empty value above, so the detector's own
  # default is never the thing that decides here — one resolution site, not two.
  bash "$DETECT" "$TARGET_ROOT" "$SCAN_ROOT" || log "auto-detection step failed (non-fatal); config left as-is."
else
  log "detect-project-tools.sh not found next to the scaffolder; skipping language auto-detection."
fi
