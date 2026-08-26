#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# efficiency-trace.sh — render the /devflow:review-and-fix per-run subagent
# effectiveness trace (Markdown) or the per-run JSON record from a run's
# per-iteration workpads, AND deterministically persist those artifacts. All
# derivation lives in lib/efficiency-trace.jq; this wrapper validates inputs,
# reads the gating config, and dispatches jq.
#
# Usage:
#   bash lib/efficiency-trace.sh --workpad-dir DIR --slug SLUG --mode {trace|record}
#   bash lib/efficiency-trace.sh --self-check --workpad-dir DIR --slug SLUG
#   bash lib/efficiency-trace.sh --persist [--workpad-dir DIR --slug SLUG]
#
# Args:
#   --workpad-dir DIR   directory holding the run's iter-<N>.json workpads
#                       (e.g. .prflow/tmp/review/<slug>/<run-id>/).
#   --slug SLUG         the run slug (pr-<N> or sanitized branch name).
#   --mode trace        emit the rendered Markdown trace to stdout.
#   --mode record       emit the per-run JSON record to stdout.
#   --self-check        Layer 2 backstop: warn (never write, never fail) when a
#                       converged writable run left no iter-*.json workpad or no
#                       persisted effectiveness record. Run-id is the basename of
#                       --workpad-dir. Silent when telemetry is disabled.
#   --persist           Layer 3 backstop: derive the per-run record + the durable
#                       workpad copy from whatever iter-*.json workpads exist on
#                       disk, and persist them to the dedicated telemetry branch
#                       (`telemetry.branch`, default prflow-telemetry) via git
#                       plumbing — it does NOT commit to the current branch and
#                       never touches HEAD or the tracked working tree (#441).
#                       Idempotent: once a run's record is already on the branch,
#                       the tree is unchanged and no new branch commit is made.
#                       With --workpad-dir/--slug it persists just that run;
#                       without them it DISCOVERS every run under
#                       .prflow/tmp/review/<slug>/<run-id>/ and persists each.
#
# Gating: when prflow_review_and_fix.efficiency_telemetry_enabled is false,
# --mode and --self-check emit NOTHING and exit 0, and --persist derives no
# record AND synthesizes no workpad (a synthesized workpad exists only to feed
# the record — issue #381); the durable copy of REAL workpads is not
# telemetry-gated — it runs on every writable run, mirroring the review-and-fix
# Loop Exit (references/loop-exit.md) split.
#
# Best-effort: a missing dir, zero readable workpads, or an unreadable workpad
# never aborts — every mode degrades gracefully and --persist/--self-check
# always exit 0. The caller (the review-and-fix Loop Exit in references/loop-exit.md,
# the Stop hook, the cloud wrapper) must itself stay non-fatal.
#
# Environment:
#   DEVFLOW_CONFIG_FILE  override the config path (used by tests).

set -euo pipefail

# jq binary: resolved once via the sourced sibling resolver (issue #247);
# best-effort — a copied/vendored deployment without lib/ falls back to bare
# `jq` with a breadcrumb rather than aborting under set -e.
# shellcheck source=resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/resolve-jq.sh" \
  || { echo "devflow: resolve-jq.sh could not be sourced beside ${BASH_SOURCE[0]} — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }

HERE="$(cd "$(dirname "$0")" && pwd)"

# shellcheck source=lib/config-source.sh
. "$HERE/config-source.sh"

# Detached telemetry-branch persistence (issue #441). Sourced beside this script.
# On a copied/vendored deployment missing lib/, sourcing fails; rather than leave
# the devflow_telemetry_* functions UNDEFINED (a later unguarded `$(devflow_telemetry_branch)`
# would then trip `set -e` — the exact abort the best-effort contract forbids), define
# no-op stubs so EVERY consumer degrades uniformly at the source boundary: the branch
# reads return "absent" and the write is a no-op, telemetry is simply not persisted this
# run, and nothing aborts. This is the SOURCE-time signal; do_persist emits a second,
# PERSIST-time breadcrumb (gated on the _DEVFLOW_TELEMETRY_BRANCH_SOURCED sentinel) that
# names the staging root whose artifacts are discarded — the two are complementary, not
# duplicates, and the persist-time one is what tells the operator what was lost.
# shellcheck source=lib/telemetry-branch.sh
. "$HERE/telemetry-branch.sh" || {
  echo "devflow: telemetry-branch.sh could not be sourced beside ${BASH_SOURCE[0]} — --persist cannot reach the telemetry branch this run; using no-op stubs so backstop reads degrade cleanly (best-effort exit-0 preserved)" >&2
  devflow_telemetry_branch()       { printf 'prflow-telemetry\n'; }
  devflow_telemetry_ref()          { printf 'refs/heads/prflow-telemetry\n'; }
  devflow_telemetry_blob_exists()  { return 1; }
  devflow_telemetry_list_blobs()   { return 0; }
  devflow_telemetry_show_blob()    { return 1; }
  devflow_telemetry_persist_tree() { return 0; }
  # verify_store MUST be stubbed too (#469 review): do_persist's fetch-before-exclusion
  # block calls devflow_telemetry_verify_store DIRECTLY and BEFORE the
  # _DEVFLOW_TELEMETRY_BRANCH_SOURCED gate, so on a source failure an un-stubbed call would
  # be `command not found` (rc 127). Both the un-stubbed 127 and this stub's `return 1` land
  # in the fetch block's `[ -n "$_rtip" ] && devflow_telemetry_verify_store …` (a condition
  # context — set -e does not abort — whose false result takes the UNESTABLISHED else arm), so
  # the stub does NOT change that arm's outcome; its effect is to suppress the spurious
  # `command not found` on stderr and to honor this block's stated "no-op stubs so EVERY
  # consumer degrades uniformly" contract, which currently misses this one call. Fail CLOSED.
  devflow_telemetry_verify_store() { return 1; }
}

WORKPAD_DIR=""
SLUG=""
MODE=""
ACTION=""   # "" → use --mode (trace|record); "persist"; "self-check"

while [ $# -gt 0 ]; do
  case "$1" in
    --workpad-dir) WORKPAD_DIR="$2"; shift 2 ;;
    --slug)        SLUG="$2";        shift 2 ;;
    --mode)        MODE="$2";        shift 2 ;;
    --persist)     ACTION="persist";    shift ;;
    --self-check)  ACTION="self-check"; shift ;;
    *) echo "efficiency-trace.sh: unknown argument '$1'" >&2; exit 2 ;;
  esac
done

# Unsubstituted-placeholder guard, argv half: the phase-3.3 backstop fence
# carries literal `<slug>`/`<run-id>` placeholders the executing agent must
# substitute; run verbatim, they would fabricate a
# `.prflow/tmp/review/<slug>/<run-id>` identity, synthesize the branch's real
# fix commits under it, and the sha exclusion would then lock the
# misattribution in while the new files suppressed the gap reflection — a
# silent, durable corruption. No legitimate slug/run-id/path carries `<` or
# `>`, so refuse them loudly (best-effort exit 0 preserved). This covers the
# ARGV route only; the basename-derived route — a literal `<slug>/<run-id>`
# DIRECTORY reaching discovery mode — is refused by persist_one's twin guard.
# Accepted limitation: a repo checked out under a path that itself contains
# `<`/`>` refuses every targeted invocation here (and discovery refuses each
# dir via persist_one's twin guard) — loudly, exit 0; fail-closed in the safe
# direction for a vanishingly rare layout. Accepted residual: a
# CALLER-side shell redirect (e.g. a verbatim Loop Exit `--mode record >
# "$RECORD"` fence) touches its placeholder-NAMED file before this script
# runs — the guard keeps the file EMPTY (no fabricated content), but cannot
# undo the caller's touch.
case "${WORKPAD_DIR}${SLUG}" in
  *'<'*|*'>'*)
    echo "::warning::efficiency-trace.sh: --workpad-dir/--slug contains an unsubstituted '<placeholder>' (got --workpad-dir '${WORKPAD_DIR}' --slug '${SLUG}'); refusing to run under a placeholder identity — substitute the run's real slug/run-id and rerun" >&2
    exit 0 ;;
esac

# ── Gating flag (on by default). ─────────────────────────────────────────────
ENABLED="$(devflow_conf '.prflow_review_and_fix.efficiency_telemetry_enabled' 'true')"

THRESHOLD="$(devflow_conf '.prflow_review_and_fix.efficiency_cut_candidate_min_dispatch' 3)"
# Guard: a non-numeric / empty operator-supplied value must not make --argjson
# abort jq (and the script under set -e) — fall back to the documented default.
# Also clamp values below the schema's `minimum: 1` (e.g. 0) to the default, so
# the persisted record never carries a value config.schema.json forbids.
case "$THRESHOLD" in
  ''|*[!0-9]*) THRESHOLD=3 ;;
esac
[ "$THRESHOLD" -lt 1 ] && THRESHOLD=3

# ── Derivation helpers (shared by --mode and --persist) ──────────────────────

# Populate the VALID_FILES global with the readable iter-*.json OBJECTS in $1.
# Skips unreadable / non-object files (best-effort), logging a ::warning:: each.
collect_valid_files() {
  local dir="$1" f
  VALID_FILES=()
  if [ -n "$dir" ] && [ -d "$dir" ]; then
    for f in "$dir"/iter-*.json; do
      [ -e "$f" ] || continue                       # no glob match → skip
      # Require a JSON OBJECT, not merely well-formed JSON: the filter indexes the
      # workpad as an object (.phase3_findings etc.), so a valid-but-non-object
      # file (stray array/number/string from a partial write) would crash jq and
      # abort the wrapper under set -e. Skip it instead, honoring best-effort.
      if "$DEVFLOW_JQ" -e 'type == "object"' "$f" >/dev/null 2>&1; then
        VALID_FILES+=("$f")
      else
        echo "::warning::efficiency-trace.sh: skipping unreadable/malformed workpad '$f'" >&2
      fi
    done
  fi
}

# Warn (don't fail) if the collected workpads carry mixed run-level `source`
# values — a run should be single-source (see the long rationale this mirrors).
warn_on_mixed_source() {
  [ "${#VALID_FILES[@]}" -gt 1 ] || return 0
  # No `2>/dev/null`: VALID_FILES already passed the `type == "object"` gate, so
  # this jq cannot fail on malformed input — suppressing its stderr would only hide
  # a genuine jq malfunction. Only a STRING `.source` is a real label; a non-string
  # (array/number/bool from a malformed write) is bucketed as the default, mirroring
  # verdict_for's `== "review"` gate — otherwise its JSON rendering would inflate the
  # distinct count into a false-positive "mixed source" warning.
  if [ "$("$DEVFLOW_JQ" -r 'if (.source | type) == "string" then .source else "review-and-fix" end' "${VALID_FILES[@]}" | sort -u | wc -l)" -gt 1 ]; then
    echo "::warning::efficiency-trace.sh: workpads carry mixed 'source' values; record collapses to the first non-null (a run should be single-source)" >&2
  fi
}

# Compute the config fingerprint (issue #431): a sha256 over the canonicalized
# prflow_review + prflow_review_and_fix config blocks, plus a small map of
# salient key values carried VERBATIM, so a cross-run/experiment analysis can
# attribute each record to the config variant that produced it. Emits a compact
# JSON object `{sha256, partial, salient}` — `partial:true` when only one of the
# two blocks exists (the hash covers what exists) — or the literal `null` when
# python3 or the config is unavailable / neither block exists. Best-effort: it
# NEVER aborts the wrapper (a null fingerprint just means the #431 assembler
# falls back to `git show <merge_sha>:.prflow/config.json` and marks the source).
# Adds NO new command head: python3 is a hard preflight prerequisite and
# config-source.sh (already sourced above) shells to it on every config read. This
# claim is load-bearing, so the body below must stay free of any non-preflight PATH
# tool (`mktemp`, `head`, `tr`, `sed`, …). An earlier revision reached for `mktemp`
# (to capture stderr) and `head` (to truncate it), which both broke that claim AND
# regressed the failure path: on a host without `mktemp` — e.g. the cloud runner,
# where CLAUDE.md records that mktemp writes are blocked — it fell back to the very
# `2>/dev/null` swallow this function exists to avoid, turning a genuine helper
# defect into an invisible null fingerprint on exactly the tier that has it (#431).
compute_config_fingerprint() {
  local cfg="$1" out rc
  # Delegate to the shared scripts/config_fingerprint.py — the SINGLE source of
  # truth this producer and the #431 assembler-reader both use, so their
  # fingerprints are byte-identical by construction (not a hand-kept mirror).
  #
  # config_fingerprint.py fails SOFT (prints `null`, exit 0) for the degradations it can
  # actually SEE — no config file, an unreadable/malformed config, neither block present.
  # It cannot soft-fail a MISSING INTERPRETER: with no python3 the script never executes,
  # so it prints nothing and rc is 127. That is why the two arms below are distinguished
  # rather than both reported as "crashed" — telling an operator whose PATH lacks python3
  # that the *helper* crashed sends them to read a script that never ran (#431 shadow).
  # Either way we degrade to `null` rather than aborting the wrapper under `set -e`
  # (best-effort contract), and the helper's own stderr flows straight to ours — no temp
  # file, no truncation, nothing to clean up — so the real reason lands in the run log.
  if out="$(python3 "$HERE/../scripts/config_fingerprint.py" "$cfg")"; then
    printf '%s\n' "$out"
  else
    rc=$?
    # 127 = not found; 126 = found but NOT EXECUTABLE (a broken Windows/WSL shim, a
    # `noexec` mount, a permissions blip). Both mean the script never ran, so both must
    # take the interpreter arm — routing 126 to the "crashed" arm would send the operator
    # to read a script that never executed, the exact mis-steer this discrimination exists
    # to eliminate, one errno over (#431 delta review).
    case "$rc" in
      126|127)
        printf 'compute_config_fingerprint: python3 not found or not executable (rc=%s) — it is a hard preflight prerequisite (see lib/preflight.sh); degrading to null\n' \
          "$rc" >&2 ;;
      *)
        printf 'compute_config_fingerprint: config_fingerprint.py crashed (rc=%s; its stderr is above) — degrading to null\n' \
          "$rc" >&2 ;;
    esac
    printf 'null\n'
  fi
}

# Run the jq derivation over VALID_FILES for $1 mode ("trace"|"record") and the
# slug $2, to stdout. A fresh GENERATED_AT is stamped per call.
emit_jq() {
  local mode="$1" slug="$2" generated_at config_fingerprint
  generated_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  # Fingerprint the config that produced this run (issue #431). Guard the empty
  # case to a JSON null so --argjson never aborts jq (and the wrapper under set -e).
  config_fingerprint="$(compute_config_fingerprint "$_DEVFLOW_CONFIG")"
  [ -n "$config_fingerprint" ] || config_fingerprint="null"
  # jq -s over zero files yields null, not []; feed an explicit empty array so the
  # filter (which expects an array) degrades to an empty trace / empty record.
  if [ "${#VALID_FILES[@]}" -eq 0 ]; then
    printf '[]\n' | "$DEVFLOW_JQ" --raw-output -f "$HERE/efficiency-trace.jq" \
      --arg mode "$mode" --arg slug "$slug" \
      --arg generated_at "$generated_at" \
      --argjson cut_candidate_min_dispatch "$THRESHOLD" \
      --argjson config_fingerprint "$config_fingerprint"
  else
    "$DEVFLOW_JQ" --raw-output --slurp -f "$HERE/efficiency-trace.jq" \
      --arg mode "$mode" --arg slug "$slug" \
      --arg generated_at "$generated_at" \
      --argjson cut_candidate_min_dispatch "$THRESHOLD" \
      --argjson config_fingerprint "$config_fingerprint" \
      "${VALID_FILES[@]}"
  fi
}

# Repo root (for the .prflow/logs/ destinations and the commit) comes from the
# already-sourced config-source.sh via devflow_repo_root — it caches
# `git rev-parse --show-toplevel || pwd` once, so a non-repo tree falls back to
# cwd and a non-repo commit simply fails best-effort with a breadcrumb.

# Single source of truth for the iter-<N>.json expected field set (issue #170).
# Kept in sync with the iter-<N>.json schema block in skills/review-and-fix/SKILL.md;
# a lib/test/run.sh assertion FAILs if the two diverge. The CONDITIONAL schema
# fields are intentionally excluded — `shadow` (Step 2.6 appends it later, so it is
# legitimately absent on iters that ran no shadow pass) and `reference_reads` (issue
# #541: Step 3.5's fix-delta gate appends it, so it is legitimately absent on iters
# where that gate did not run). `sweep_defs_read`/`sweep_evidence` are NOT conditional:
# fixing.md item 7 mandates them on every iteration (a no-fix iteration writes the
# explicit `[]` / `not-run` pair rather than omitting them), which is why they belong
# in this unconditional set. `dispatched_effort` (issue #609) is likewise unconditional:
# fixing.md item 7 mandates it on every iteration Phase 1+2 ran. `expected_reviewers`
# (issue #1904) is likewise unconditional: the engine records its own Phase 3.1 gate
# decisions on every iteration alongside `phase3_dispatched`, and the Step 1
# roster-coverage check reads it. `phase3_failed_agents` (issue #1849) is likewise
# unconditional: the engine records the dispatched agents that returned no usable result
# on every iteration (explicit `[]` when none failed), and the trace reads it to assign a
# `failed` per-agent disposition. --self-check warns
# (best-effort) when any of these is missing from a persisted iter workpad. Plain
# (non-readonly) single-line assignment so the run.sh divergence guard can grep
# `^ITER_EXPECTED_FIELDS=` to extract it.
ITER_EXPECTED_FIELDS="iter started_at fix_commit_sha fix_files loop_role sweep_defs_read sweep_evidence checklist phase3_dispatched phase3_failed_agents expected_reviewers dispatched_effort diff_profile phase3_findings fix_decisions convergence_inputs cap_drops telemetry"
# The synthesized-record minimal field set (issue #381): what synthesize_iter_workpads
# writes, and what --self-check validates a synthesized:true record against (a
# synthesized record is a recognized degraded class, exempt from the full set above
# but NOT from its own — a truncated synthesized record must still warn).
# The run-scoped evidence fields (issue #541) are members because the synthesizer writes an
# explicit unrecoverable-provenance object for each: absent evidence is recorded AS
# absent, never serialized as a real `[]` / `not-run` / omitted value. Their presence
# here is the producer<->consumer coupling — this set catches a DROPPED field, while
# the evidence-provenance shape check in do_self_check catches the sibling regression
# this set structurally cannot see: a field still present but carrying a real-looking
# `[]` / `not-run` value. Both are warn-only (do_self_check never fails); the
# lib/test/run.sh #541 assertions are what turn either regression RED at the desk.
ITER_SYNTH_EXPECTED_FIELDS="iter fix_commit_sha fix_files loop_role synthesized sweep_defs_read sweep_evidence reference_reads"
# The synthesized SHADOW-marker minimal field set (issue #426): what
# synthesize_shadow_markers writes into an iter's `shadow` block when provenance
# establishes that a shadow ran (or leaves that fact unestablished for a legacy
# record), and what --self-check validates a
# `shadow_synthesized: true` block against (a recognized degraded class, exempt
# from a real shadow block's full shape but NOT from its own minimal set — a
# truncated synthesized shadow marker must still warn). Plain single-line
# assignment so a run.sh guard can grep `^SHADOW_SYNTH_EXPECTED_FIELDS=`.
SHADOW_SYNTH_EXPECTED_FIELDS="shadow_synthesized promoted_to_iter_next"

# ── Synthesis backstop (Layer 3+): reconstruct a minimal iteration record from
# the branch's fix commits when a run left ZERO iter-*.json (issue #381) ───────
#
# SHARED FIX-COMMIT SUBJECT CONTRACT (coupled two-site invariant — issue #381):
# the fix-commit subject template `fix: address review findings (iteration {N})`
# is WRITTEN by skills/review-and-fix/references/fixing.md Step 3 item 6 and PARSED here to
# reconstruct the per-iteration records when the workpads were dropped. Both
# sites must carry the identical literal; lib/test/run.sh pins both and a
# targeted edit to either turns the suite RED. Changing the subject? Edit item 6
# and this selector in the SAME commit.
FIX_COMMIT_SUBJECT_PREFIX="fix: address review findings (iteration"

# Resolve the ref the fix-commit range diffs against. Prefer origin/<base> over
# the local ref: in this repo's linked-worktree flow the local base branch is
# routinely BEHIND origin (nobody pulls it in a worktree), and a stale local base
# widens base..HEAD to sweep already-merged history — misattributing an old merged
# PR's fix commits to this run. Falls back to the local ref (fixtures and offline
# clones with no origin). Echoes the resolved ref, or returns non-zero when neither
# resolves (fail-closed).
#
# SINGLE-PRODUCER CONTRACT (issue #532): the base BRANCH NAME has exactly one
# producer in this file — do_persist resolves `.base_branch` ONCE into the
# dynamically-scoped `_DEVFLOW_BASE_BRANCH` (with its empty-value fallback to
# `main`) before it forks, and BOTH the pre-synthesis base-ref refresh in do_persist
# AND this resolver consume that single resolution. This function therefore reads
# `_DEVFLOW_BASE_BRANCH` and NEVER re-reads `.base_branch` via devflow_conf: a second
# derivation would be a coupled site that fails OPEN if the two ever diverged (the
# refresh certifies `origin/<base>` fresh while selection ran against a different,
# unrefreshed ref). The `:-main` here is only a defensive fallback for a
# hypothetical caller that reaches this function without do_persist having seeded
# the local — in production the sole call path (do_persist → persist_one →
# synthesize_iter_workpads) always seeds it.
synth_base_ref() {
  local root="$1" base ref
  base="${_DEVFLOW_BASE_BRANCH:-main}"
  for ref in "origin/$base" "$base"; do
    if git -C "$root" rev-parse --verify --quiet "${ref}^{commit}" >/dev/null 2>&1; then
      printf '%s\n' "$ref"; return 0
    fi
  done
  # Name the tried value on the failure path — "which base was tried" is the
  # one actionable operand, and a present-but-unresolvable value (a typo'd
  # branch, a wrong-type config coerced to a string like "false") must not be
  # misreported as the key being absent.
  echo "::warning::efficiency-trace.sh: neither 'origin/${base}' nor '${base}' resolves to a commit (.base_branch resolved to '${base}' — absent key, typo, wrong-type value, or missing ref)" >&2
  return 1
}

# Validate + emit a fix_commit_sha token (lowercase-hex charset — length
# deliberately unchecked, which is sufficient here: the check exists to keep a
# corrupt string value ("aaa bbb <realsha>", an embedded newline) from smuggling
# whitespace-bearing tokens into the space-delimited exclusion set; space/newline
# both fail the charset class. The producer contract is `git rev-parse HEAD`, so a
# wrong-LENGTH hex token can only weaken the exclusion for an already-corrupt
# workpad, never cause a wrong exclusion of a full-sha match). $1 is the sha,
# $2 the source label used in the not-sha-shaped breadcrumb.
_emit_fix_sha() {
  case "$1" in
    ''|*[!0-9a-f]*) [ -n "$1" ] && echo "::warning::efficiency-trace.sh --persist: fix_commit_sha in ${2} is not sha-shaped; not added to the exclusion set" >&2 ;;
    *) printf '%s\n' "$1" ;;
  esac
}

# Emit every fix_commit_sha already recorded by ANY other run's iter-*.json,
# UNIONED across three sources so a run persisted to the telemetry branch (issue
# #441) stays in the exclusion set and its fix commits are never re-attributed
# (AC12): (1) the live tmp scratch tree, (2) the telemetry branch's durable
# iter-*.json blobs (read via git ls-tree/git show — the branch is where durable
# copies now live), and (3) any legacy tracked working-tree .prflow/logs/review/
# (retained so a consumer's pre-#441 in-tree archive is not dropped). $2 is the
# target run dir's TMP path, excluded from source (1) only — its durable mirror on
# the branch, if a prior persist wrote one, is deliberately NOT excluded (a run
# whose workpads were already persisted reads as already-recorded, which is
# correct). Best-effort: an unreadable/malformed workpad is skipped with a
# breadcrumb (a contained fail-open the breadcrumb makes loud), never truncating
# the rest of the scan.
recorded_fix_shas() {
  local root="$1" skip_dir="$2" f sha_out ref blob_path
  # (1) tmp scratch + (3) legacy tracked working-tree copies.
  for f in "$root"/.prflow/tmp/review/*/*/iter-*.json "$root"/.prflow/logs/review/*/*/iter-*.json; do
    [ -e "$f" ] || continue
    case "$f" in "$skip_dir"/*) continue ;; esac
    if ! sha_out="$("$DEVFLOW_JQ" -r 'if (.fix_commit_sha | type) == "string" then .fix_commit_sha else empty end' "$f" 2>/dev/null)"; then
      echo "::warning::efficiency-trace.sh --persist: could not read fix_commit_sha from ${f} (unreadable or malformed workpad); its sha (if any) cannot be excluded from synthesis" >&2
      continue
    fi
    _emit_fix_sha "$sha_out" "$f"
  done
  # (2) telemetry-branch durable iter-*.json blobs. No `command -v` guard here:
  # the source boundary (top of file) defines no-op stubs when the lib is absent,
  # so devflow_telemetry_* are always callable and list_blobs then yields nothing.
  ref="$(devflow_telemetry_ref)"
  while IFS= read -r blob_path; do
    case "$blob_path" in */iter-*.json) ;; *) continue ;; esac
    if ! sha_out="$(devflow_telemetry_show_blob "$root" "$ref" "$blob_path" | "$DEVFLOW_JQ" -r 'if (.fix_commit_sha | type) == "string" then .fix_commit_sha else empty end' 2>/dev/null)"; then
      echo "::warning::efficiency-trace.sh --persist: could not read fix_commit_sha from ${ref}:${blob_path} (unreadable or malformed telemetry blob); its sha (if any) cannot be excluded from synthesis" >&2
      continue
    fi
    _emit_fix_sha "$sha_out" "${ref}:${blob_path}"
  done < <(devflow_telemetry_list_blobs "$root" "$ref" ".prflow/logs/review/")
  return 0
}

# Reads `sha<TAB>subject` lines (oldest-first) on STDIN — the caller captures
# `git log` output first so a failed log is routed to the rc-3 "never
# established" arm instead of reading as an empty commit list — and emits
# `N<TAB>sha` lines for subjects matching the fix-commit contract, excluding any
# sha in $1 (space-separated already-recorded set). Deterministic, network-free.
# Adversarial subjects each emit an exit-0 stderr breadcrumb and are skipped:
# prefix present but the iteration clause never closed with `)`, a non-numeric
# iteration token, an already-recorded sha, or a duplicate N (first unexcluded
# occurrence wins). Two accepted leniences: `(iteration1)` (missing space) parses
# as iteration 1 — the strip drops at most one optional space — and trailing text
# after the closing `)` is ignored (issue #1946). The subject is authored per run
# rather than emitted by a template, so a trailing summary is the common shape in
# practice, and an ends-with match skipped every such commit.
# Known limitation:
# iteration numbers restart at 1 per review loop, so a branch carrying TWO
# unrecorded loops keeps only the first loop's commit for each N (duplicate-N
# breadcrumbs name the rest) — acceptable for a minimal floor. Always exits 0.
select_fix_commits() {
  local excl="$1" base_subject sha subj n tab seen_ns=" "
  tab="$(printf '\t')"
  # The fix-loop subject family, derived from the coupled prefix constant (the
  # strip pattern necessarily repeats the constant's ` (iteration` tail — keep
  # the two in lockstep if the subject template is ever reworded): a commit in
  # this family but WITHOUT the `(iteration N)` suffix is breadcrumbed, not
  # silently dropped (issue #381 AC4).
  base_subject="${FIX_COMMIT_SUBJECT_PREFIX% (iteration}"
  # --reverse → oldest-first so a duplicate N keeps the EARLIEST commit.
  while IFS="$tab" read -r sha subj; do
    [ -n "$sha" ] || continue
    case "$subj" in
      "$FIX_COMMIT_SUBJECT_PREFIX"*) ;;          # has the "(iteration" suffix — parse N below
      "$base_subject"*)                           # fix-loop family but no "(iteration N)" suffix
        echo "::warning::efficiency-trace.sh --persist: fix-commit ${sha} is in the fix-loop subject family but has no '(iteration N)' suffix; skipping" >&2; continue ;;
      *) continue ;;                              # unrelated commit — silently skip
    esac
    # Already recorded by another run's workpad (real or previously synthesized,
    # tmp or durable copy) — never re-attribute it to this run (the double-count
    # guard; checked BEFORE duplicate-N dedupe so an excluded commit does not
    # consume its iteration number and shadow this run's own commit with that N).
    case " $excl " in
      *" $sha "*) echo "::warning::efficiency-trace.sh --persist: fix-commit ${sha} is already recorded by another run's iter-*.json workpad; skipping so it is not double-counted" >&2; continue ;;
    esac
    n="${subj#"$FIX_COMMIT_SUBJECT_PREFIX"}"      # -> " N)"
    n="${n# }"                                    # drop one leading space
    # Read the token up to the FIRST ')' — do not require the subject to END there
    # (issue #1946), or every fix commit carrying a trailing summary is skipped and
    # synthesis recovers nothing from it.
    case "$n" in
      *")"*) n="${n%%)*}" ;;
      *) echo "::warning::efficiency-trace.sh --persist: fix-commit ${sha} matches the fix-subject prefix but its '(iteration N)' clause has no closing ')'; skipping" >&2; continue ;;
    esac
    case "$n" in
      ''|*[!0-9]*) echo "::warning::efficiency-trace.sh --persist: fix-commit ${sha} has a non-numeric iteration token '${n}'; skipping" >&2; continue ;;
    esac
    # Normalize leading zeros (pure bash — a selection-deciding value must not
    # route through a non-preflight PATH tool): "01" and "1" are the same
    # iteration, so they must collide in the duplicate-N dedupe, and a leading-
    # zero token must never reach `--argjson` (jq builds disagree on leading-zero
    # JSON numbers — acceptance is version-dependent, rejection would be
    # misattributed as a disk write failure).
    while [ "${n#0}" != "$n" ] && [ -n "${n#0}" ]; do n="${n#0}"; done
    case "$seen_ns" in
      *" $n "*) echo "::warning::efficiency-trace.sh --persist: duplicate iteration ${n} (fix-commit ${sha}); keeping the first occurrence, skipping this one" >&2; continue ;;
    esac
    seen_ns="${seen_ns}${n} "
    printf '%s\t%s\n' "$n" "$sha"
  done
  return 0
}

# Synthesize minimal iter-<N>.json workpads into $1 from the branch's fix
# commits (issue #381). Each record carries exactly the ITER_SYNTH_EXPECTED_FIELDS
# set — the effectiveness fields, plus the run-scoped evidence fields stamped with
# explicit unrecoverable provenance (issue #541) — a distinct recognized degraded
# class the jq filter and --self-check both ride. The rc is a FOUR-way outcome (0/2/3/4,
# enumerated below) so the caller's breadcrumb never collapses an unestablished measurement
# onto "found none" (the repo's unknown-is-not-zero gotcha): returns 0 iff ≥1 record was
# written; 2 when selection RAN and found no unrecorded matching commit; 3 when
# the search could not run at all (an uncreatable target dir, a base ref left
# UNESTABLISHED by a failed pre-synthesis origin/<base> refresh (issue #532), no
# base ref resolvable, OR the git log enumeration itself failed — either way,
# whether matching commits could be synthesized was never established; the
# arm-specific warning names which); 4 when commits WERE selected but every record write
# failed (per-commit warnings already emitted).
synthesize_iter_workpads() {
  local dir="$1" root="$2" n sha files files_ok base excl log_out jq_err tab attempted=0 wrote=0
  tab="$(printf '\t')"
  # The target dir can be absent on the one shape this floor exists for — a
  # fully-degraded run that never created its tmp dir, reached via the
  # phase-3.3 targeted retry / the breadcrumb-named --workpad-dir escape hatch.
  # Without this, every write below fails ENOENT and the rc-4 arm misreads a
  # missing directory as a disk/write failure.
  if ! mkdir -p "$dir" 2>/dev/null; then
    echo "::warning::efficiency-trace.sh --persist: could not create workpad dir ${dir} (permissions/read-only fs, or on the cloud tier the sandbox's write denial into .prflow/tmp?); cannot synthesize into it" >&2
    return 3
  fi
  # Base-ref freshness guard (issue #532): do_persist's pre-synthesis refresh sets
  # _DEVFLOW_BASE_REF_STATUS. When it is `unestablished` (origin configured but the
  # refresh did not succeed), the remote-tracking base ref may be arbitrarily stale,
  # so `${base}..HEAD` could widen into already-merged foreign history and attribute
  # another PR's fix commits to this run — the exact corruption #532 closes. Decline:
  # write no record and take the "search never ran" outcome (rc 3), joining the
  # existing rc-3 class alongside the unresolvable-base-ref and failed-git-log arms.
  # This `::warning::` is textually distinct from BOTH the unresolvable-base-ref
  # warning below (which fires when NEITHER origin/<base> nor <base> resolves) and
  # the found-none breadcrumb persist_one emits for rc 2 — the breadcrumb is the only
  # channel that discriminates decline from found-none, since both write no file and
  # both exit 0. Default `established` when the var is unset guards a hypothetical
  # caller that reaches synthesis without do_persist having seeded it (the sole
  # production path always seeds it); it is never `established`-by-accident here.
  if [ "${_DEVFLOW_BASE_REF_STATUS:-established}" = unestablished ]; then
    echo "::warning::efficiency-trace.sh --persist: the base ref 'origin/${_DEVFLOW_BASE_BRANCH:-main}' is UNESTABLISHED (its pre-synthesis refresh did not succeed — see the refresh warning above); commit selection is skipped, so no synthesized iter-*.json is written this run" >&2
    return 3
  fi
  # Telemetry-fetch freshness guard (issue #916): do_persist's pre-synthesis
  # telemetry-branch fetch sets _DEVFLOW_TELEMETRY_FETCH_STATUS (`ok`/`failed`/
  # `unattempted`). recorded_fix_shas reads the LOCAL telemetry ref to build the
  # fix-commit exclusion set; when the fetch did NOT succeed (`failed`/
  # `unattempted`) that ref may be absent or stale, so the exclusion set is
  # silently incomplete and synthesis can re-attribute a commit an earlier run
  # already recorded (the cross-PR double-booking #916 closes). This mirrors the
  # base-ref guard above (decline → rc 3), adapted to a three-valued status: where
  # the base-ref sentinel declines on the single value `unestablished`, this one
  # declines on any status other than `ok` (`failed`/`unattempted`) — write no
  # record, take the "search never ran" outcome (rc 3), joining the same rc-3
  # class. Without it list_blobs/recorded_fix_shas only emit a `::warning::` while
  # synthesis proceeds against the incomplete set. The `::warning::` is textually
  # distinct from the base-ref, unresolvable-base-ref, and found-none breadcrumbs
  # (the breadcrumb is the only channel that discriminates decline from found-none,
  # since both write no file and both exit 0). Default `ok` when the var is unset
  # guards a hypothetical caller reaching synthesis without do_persist having
  # seeded it (the sole production path always seeds it); it is never
  # `failed`-by-accident here.
  if [ "${_DEVFLOW_TELEMETRY_FETCH_STATUS:-ok}" != ok ]; then
    echo "::warning::efficiency-trace.sh --persist: the telemetry-branch fetch is UNESTABLISHED (_DEVFLOW_TELEMETRY_FETCH_STATUS='${_DEVFLOW_TELEMETRY_FETCH_STATUS:-ok}' — its pre-synthesis fetch did not succeed; see the fetch warning above); the fix-commit exclusion set may be incomplete, so commit selection is skipped and no synthesized iter-*.json is written this run" >&2
    return 3
  fi
  if ! base="$(synth_base_ref "$root")"; then
    echo "::warning::efficiency-trace.sh --persist: could not resolve a base branch ref (the warning above names the tried value); cannot select fix commits for synthesis" >&2
    return 3
  fi
  # Capture the log BEFORE parsing, checking its own exit status: a failed
  # `git log` (unborn HEAD, index-lock race, corrupt object store) is "the
  # enumeration never ran" — rc 3, never collapsed onto rc 2's "found none"
  # (the unknown-is-not-zero gotcha, applied to the search itself).
  # Data purity: stderr is discarded, never REDIRECTED into the capture — do
  # not change this to `2>&1`, which would inject a succeeding git advisory
  # (unreadable ~/.config/git, ref warnings) into the parsed commit stream.
  if ! log_out="$(git -C "$root" log --reverse --format="%H${tab}%s" "${base}..HEAD" 2>/dev/null)"; then
    echo "::warning::efficiency-trace.sh --persist: git log ${base}..HEAD failed (rc-checked; its stderr is suppressed to keep the data stream pure — rerun the command manually for detail); whether matching fix commits exist was never established" >&2
    return 3
  fi
  # Join the exclusion set with bash builtins only — it DECIDES which commits are
  # selected, so it must not be derived through a non-preflight PATH tool (the
  # repo's guard-class 2: a missing tool would silently empty the set and re-open
  # the double-count this guard exists to close).
  excl=""
  while IFS= read -r sha; do
    [ -n "$sha" ] && excl="${excl}${sha} "
  done < <(recorded_fix_shas "$root" "$dir")
  while IFS="$tab" read -r n sha; do
    [ -n "$n" ] && [ -n "$sha" ] || continue
    attempted=$((attempted + 1))
    # Guard the fix_files derivation: a failed diff-tree must record
    # fix_files: null (unestablished — distinguishable from a genuine
    # empty/--allow-empty commit's []) with a breadcrumb, never a silent
    # fabricated "this commit touched no files".
    files_ok=1
    if ! files="$(git -C "$root" diff-tree --no-commit-id --name-only -r "$sha" 2>/dev/null)"; then
      echo "::warning::efficiency-trace.sh --persist: could not derive fix_files for ${sha} (git diff-tree failed; stderr suppressed to keep the data stream pure); recording fix_files as null (unestablished)" >&2
      files_ok=0
      files=""
    fi
    # stdout goes to the record file, so stderr is free to capture — unlike the
    # git log/diff-tree data streams above, keeping the failure CAUSE
    # (ENOENT/EACCES/ENOSPC/argjson rejection) costs no data purity here.
    # Run-scoped evidence provenance (issue #541). `sweep_defs_read: []` and
    # `sweep_evidence: {"status":"not-run",...}` are the LEGITIMATE values of a real
    # no-fix iteration, so emitting either here would be a positive claim about an
    # iteration this fix-commit-only floor never observed. The `unrec` emitter below
    # single-sources the shared framing so the three stamps cannot drift apart; each
    # call supplies only what it specifically could not establish. See the
    # ITER_SYNTH_EXPECTED_FIELDS comment for why --self-check enforces their presence.
    #
    # `reference_reads` is stamped INSIDE its `fix_delta` member, not at the top level:
    # the field is a registry keyed by the producing reference (fixing.md item 7), so a
    # top-level stamp would leave the documented `.reference_reads.fix_delta` read
    # returning null — indistinguishable from the legitimate "Step 3.5 did not run"
    # absence, collapsing the very distinction this provenance exists to preserve.
    #
    # The reason says "no iteration record was FOUND for this run", never "was never
    # persisted": this floor establishes only that the run dir held no iter-*.json. A
    # record can exist yet be unreachable here — the telemetry blob listing degrades to a
    # no-op stub when its lib is unsourceable, and an unreadable sibling workpad is
    # skipped without its sha being excluded — so the stronger claim would assert a state
    # the code never observed (the all-output-channels honesty rule).
    if jq_err="$("$DEVFLOW_JQ" -n --argjson iter "$n" --arg sha "$sha" --arg files "$files" --arg files_ok "$files_ok" \
         'def unrec($what): {status: "unrecoverable",
            reason: ("fix-commit-only synthesis: no iteration record was found for this run, and a fix commit carries no trace of " + $what)};
          {iter: $iter, fix_commit_sha: $sha,
           fix_files: (if $files_ok == "1" then ($files | split("\n") | map(select(length > 0))) else null end),
           loop_role: "fix", synthesized: true,
           sweep_defs_read: unrec("which sweep definitions were read"),
           sweep_evidence: unrec("the sweep outcomes"),
           reference_reads: {fix_delta: unrec("whether the Step 3.5 fix-delta gate ran")}}' 2>&1 > "$dir/iter-$n.json")"; then
      wrote=$((wrote + 1))
    else
      echo "::warning::efficiency-trace.sh --persist: failed to write synthesized iter-${n}.json for ${sha} (${jq_err:-no error text}); skipping" >&2
      rm -f "$dir/iter-$n.json" 2>/dev/null
    fi
  done < <(printf '%s\n' "$log_out" | select_fix_commits "$excl")
  # (printf-pipe, not a heredoc: bash <5.1 heredocs — and over-pipe-buffer ones
  # on newer bash — materialize a temp file, so a denied-TMPDIR host could
  # collapse an already-captured commit list onto the rc-2 "found none" arm —
  # the builtin pipe has no such failure channel.)
  [ "$wrote" -gt 0 ] && return 0
  [ "$attempted" -gt 0 ] && return 4
  return 2
}

# Deterministic emitted-provenance backfill (issue #534). Route (b): move the
# `synthesized` provenance stamp OFF the agent's decision path. The fix loop's
# per-iteration emit (skills/review-and-fix) is agent-authored prose that carries
# no provenance stamp, while synthesize_iter_workpads above stamps
# `synthesized: true` on every record it reconstructs. Without an affirmative stamp
# on the EMITTED record a later reader cannot positively tell an agent-written
# record (a real emit) from a malformed/legacy one — only "not synthesized:true",
# which conflates the two, so a skipped-then-recovered emit is not cleanly
# distinguishable from a real one. So after synthesis this stamps
# `synthesized: false` onto every valid-object iter-*.json in the run dir that
# carries no `synthesized` key, guaranteeing every persisted record affirmatively
# records its provenance regardless of whether the agent wrote the stamp — the
# emitted/synthesized distinction is then a deterministic JSON boolean
# (`.synthesized == false` vs `== true`), and a lost emit is the absent record.
# Idempotent: a key-present record (a real synthesized:true, or an already-backfilled
# false) is left byte-identical, so a second --persist is a no-op here. Best-effort
# per file: a malformed/non-object record or a failed write breadcrumbs and is left
# untouched (never rewritten, never aborting --persist) — --self-check surfaces a
# bad-shape record. This changes NO synthesized record (they already carry
# synthesized:true), so the issue-#381 synthesis contract and --self-check's
# synthesized-class validation are unaffected.
stamp_emitted_provenance() {
  local dir="$1" f tmp err
  for f in "$dir"/iter-*.json; do
    [ -e "$f" ] || continue
    # Backfill only a valid JSON OBJECT that lacks a `synthesized` key. `jq -e`
    # exits non-zero on a false/empty result AND on a parse/open failure, so a
    # malformed or non-object record falls through untouched.
    "$DEVFLOW_JQ" -e 'type == "object" and (has("synthesized") | not)' "$f" >/dev/null 2>&1 || continue
    tmp="${f}.prov-tmp"
    if ! { err="$("$DEVFLOW_JQ" '.synthesized = false' "$f" 2>&1 > "$tmp")" && mv "$tmp" "$f"; }; then
      rm -f "$tmp" 2>/dev/null || true
      echo "::warning::efficiency-trace.sh --persist: could not backfill emitted provenance (synthesized:false) into '$(basename "$f")' (${err:-write/move failed}); left untouched, best-effort" >&2
    fi
  done
}

# Shadow synthesis floor (Layer 3+, issues #426/#501): a promoted successor's
# `promotion_provenance` establishes whether its predecessor ran a shadow. The
# floor recovers dropped shadow blocks for shadow and post-shadow park promotions,
# suppresses pre-shadow/non-shadow promotions, and preserves legacy ambiguity in
# a `provenance_unestablished` marker. Best-effort, always returns 0 (a floor
# failure never aborts --persist). Two guards keep it faithful: it
# NEVER overwrites an existing `shadow` block (agent-written or already
# synthesized — the read gates on `.shadow` absence), and it writes at most one
# marker per promotion-evidenced iter (no double-count — a second --persist pass
# sees the marker it wrote and declines). STATED LIMITATION: this recovers
# PROMOTED shadows only — a clean outcome-1 shadow whose block dropped leaves no
# promotion evidence to synthesize from; the fused Step 2.6 emit is the primary
# fix and this floor is its backstop, not its equal.
synthesize_shadow_markers() {
  local dir="$1" iter n next has_shadow promoted provenance provenance_value marker_filter warning jq_err mv_err
  for iter in "$dir"/iter-*.json; do
    [ -e "$iter" ] || continue
    # Parse N from the filename with bash builtins only — this DECIDES whether a
    # marker is written, so it must not depend on a non-preflight PATH tool
    # (guard-class 2); a non-numeric stem is skipped, not defaulted.
    n="${iter##*/iter-}"; n="${n%.json}"
    case "$n" in ''|*[!0-9]*) continue ;; esac
    # Never overwrite: synthesize ONLY when `.shadow` is absent (jq `null`); skip
    # any iter that already carries a non-null `shadow` value — an object
    # (agent-written or previously synthesized) OR a malformed partial a truncated
    # write left behind (a string/number). Keying on object-ness alone would
    # clobber such a malformed real block; keying on `== null` fails closed on it
    # while still synthesizing into a genuinely-absent slot. A parse failure is
    # skipped (never clobber an unreadable block) but BREADCRUMBED, not silent —
    # matching recorded_fix_shas' unreadable-workpad breadcrumb and the file's
    # "surfacing failures" convention, so a malformed workpad that dropped a real
    # promoted shadow (the issue-304 drop shape this floor recovers) leaves a signal
    # rather than an unattributed silence.
    if ! has_shadow="$("$DEVFLOW_JQ" -r 'if .shadow == null then "no" else "yes" end' "$iter" 2>/dev/null)"; then
      echo "::warning::efficiency-trace.sh --persist: could not read '.shadow' from $(basename "$iter") (unreadable or malformed workpad); its shadow attribution (if any) cannot be recovered" >&2
      continue
    fi
    [ "$has_shadow" = "no" ] || continue
    # Promotion evidence: the next iter exists AND is a promoted iter. Force base-10
    # on the stem (`10#$n`) so a zero-padded numeric stem (`iter-08.json`) — which the
    # all-digit guard above admits — is not misread by `$(( ))` as invalid octal
    # (`08`/`09` → "value too great for base"); the producer never zero-pads, so this
    # is an adversarial-input guard, consistent with the guard-class-2 discipline.
    next="$dir/iter-$((10#$n + 1)).json"
    [ -e "$next" ] || continue
    if ! promoted="$("$DEVFLOW_JQ" -r 'if .loop_role == "promoted" then "yes" else "no" end' "$next" 2>/dev/null)"; then
      echo "::warning::efficiency-trace.sh --persist: could not read '.loop_role' from $(basename "$next") (unreadable or malformed workpad); cannot confirm promotion evidence for $(basename "$iter")" >&2
      continue
    fi
    [ "$promoted" = "yes" ] || continue
    # Classify the producer-written provenance inside jq and branch only on the
    # resulting token. The two synthesis-licensing literals are a coupled
    # producer/consumer contract pinned by lib/test/run.sh.
    if ! provenance="$("$DEVFLOW_JQ" -r '
      if ((.promotion_provenance | type) != "string") or ((.promotion_provenance | length) == 0) then "unknown"
      elif .promotion_provenance == "shadow" then "shadow"
      elif .promotion_provenance == "park-calibration-post-shadow" then "postshadow"
      elif .promotion_provenance == "park-calibration-pre-shadow" then "preshadow"
      else "nonshadow"
      end' "$next" 2>/dev/null)"; then
      echo "::warning::efficiency-trace.sh --persist: could not read '.promotion_provenance' from $(basename "$next") (unreadable or malformed workpad); cannot classify shadow precedence for $(basename "$iter")" >&2
      continue
    fi
    case "$provenance" in
      shadow)
        marker_filter='.shadow = {shadow_synthesized: true, promoted_to_iter_next: true}'
        warning="::warning::efficiency-trace.sh --persist: synthesized a minimal shadow marker on $(basename "$iter") — its shadow block was dropped but iter-$((10#$n + 1)).json is a promoted iter, so the promotion linkage is recovered (cost figures are unrecoverable after the fact — attribution only, per the floor's promoted-shadows-only limitation)"
        ;;
      postshadow)
        marker_filter='.shadow = {shadow_synthesized: true, promoted_to_iter_next: false}'
        warning="::warning::efficiency-trace.sh --persist: synthesized a shadow marker on $(basename "$iter") — its shadow block was dropped ($(basename "$next") records a park-calibration-post-shadow promotion, so a shadow ran here); promoted_to_iter_next is false because the promotion was park-gate-driven, not shadow-driven (attribution only — cost figures are unrecoverable after the fact)"
        ;;
      preshadow) continue ;;
      nonshadow)
        provenance_value="$("$DEVFLOW_JQ" -r '.promotion_provenance' "$next" 2>/dev/null)" || provenance_value="<unreadable>"
        echo "::warning::efficiency-trace.sh --persist: $(basename "$next") carries unrecognized promotion_provenance value '$provenance_value' — treating it as a non-shadow promotion (no marker synthesized on $(basename "$iter")); an unrecognized value here can hide a genuine drop" >&2
        continue
        ;;
      unknown)
        marker_filter='.shadow = {shadow_synthesized: true, promoted_to_iter_next: true, provenance_unestablished: true}'
        warning="::warning::efficiency-trace.sh --persist: synthesized a minimal shadow marker on $(basename "$iter") — $(basename "$next") is a promoted iter whose promotion provenance is unreadable or absent (a record predating promotion_provenance, or a degraded write), so the shadow block was either dropped or this promotion never ran one; marked provenance_unestablished (attribution only — cost figures are unrecoverable after the fact)"
        ;;
      *)
        echo "::warning::efficiency-trace.sh --persist: internal promotion provenance classifier returned '$provenance' for $(basename "$next"); no marker synthesized on $(basename "$iter")" >&2
        continue
        ;;
    esac
    # Merge the marker in via a temp file + mv (jq cannot edit in place; a direct
    # `> "$iter"` would truncate the source before jq reads it). A failed jq
    # leaves the original untouched with a breadcrumb — never a silent drop.
    if jq_err="$("$DEVFLOW_JQ" "$marker_filter" "$iter" 2>&1 > "$iter.shadowtmp")"; then
      if mv_err="$(mv "$iter.shadowtmp" "$iter" 2>&1)"; then
        echo "$warning" >&2
      else
        # Surface mv's own errno text (read-only mount, ENOSPC, …) rather than
        # discarding it to /dev/null — symmetric with the jq branch's $jq_err, and
        # the difference between a diagnosable failure and an unexplained one.
        echo "::warning::efficiency-trace.sh --persist: could not move the synthesized shadow marker into $(basename "$iter") (mv failed: ${mv_err:-no error text}); leaving it without one" >&2
        rm -f "$iter.shadowtmp" 2>/dev/null
      fi
    else
      echo "::warning::efficiency-trace.sh --persist: could not synthesize a shadow marker on $(basename "$iter") (${jq_err:-no error text}); leaving it without one" >&2
      rm -f "$iter.shadowtmp" 2>/dev/null
    fi
  done
  return 0
}

# ── --self-check (Layer 2): warn-only, never writes, never fails ─────────────
do_self_check() {
  # Silent when telemetry is disabled — there is no record to expect, so a
  # missing one is correct, not a gap. (Read-only runs are silent by caller
  # construction: references/loop-exit.md only invokes the self-check on writable runs.)
  [ "$ENABLED" = "true" ] || return 0
  if [ -z "$WORKPAD_DIR" ] || [ -z "$SLUG" ]; then
    echo "::warning::efficiency-trace.sh --self-check requires --workpad-dir and --slug" >&2
    return 0
  fi
  local run_id root record
  run_id="$(basename "$WORKPAD_DIR")"
  root="$(devflow_repo_root)"
  # No iter-*.json workpad at all → per-iteration telemetry was never captured.
  if [ ! -d "$WORKPAD_DIR" ] || ! compgen -G "$WORKPAD_DIR"/iter-*.json >/dev/null 2>&1; then
    echo "::warning::devflow review-and-fix self-check: NO iter-*.json workpad was written for run ${SLUG}/${run_id} — per-iteration effectiveness telemetry was not captured this run; recover a minimal floor with 'lib/efficiency-trace.sh --persist --workpad-dir ${WORKPAD_DIR} --slug ${SLUG}' (the targeted form — bare discovery-mode --persist can decline this dir on a multi-slug or not-latest skip), which synthesizes an iteration record from this branch's unrecorded 'fix: address review findings (iteration N)' commits when any exist." >&2
    return 0
  fi
  # Workpads exist but the effectiveness record was not persisted. Presence is
  # tested ON THE TELEMETRY BRANCH now (issue #441) — the record no longer lives
  # in the working tree — via `git cat-file -e <ref>:<path>`, so a correctly
  # persisted run never draws a false "not persisted" warning and a genuinely
  # dropped one still does (AC15).
  local ref
  ref="$(devflow_telemetry_ref)"
  record=".prflow/logs/efficiency/${SLUG}-${run_id}.json"
  if ! devflow_telemetry_blob_exists "$root" "$ref" "$record"; then
    echo "::warning::devflow review-and-fix self-check: effectiveness record '${record}' was NOT persisted to the telemetry branch '${ref#refs/heads/}' for run ${SLUG}/${run_id} — recover it with 'lib/efficiency-trace.sh --persist'." >&2
  fi
  # Per-iteration field validation (issue #170): warn — best-effort, never writes,
  # never aborts — for each iter-<N>.json missing an expected field, naming the
  # field and the iter file so a silently-dropped inline-persist field becomes a
  # visible warning. One jq per file computes the missing set as a set difference
  # (expected fields − the object's keys). The jq call is guarded by `if !` — NOT a
  # bare `missing=$(...)` assignment, which under `set -e` would abort the whole
  # self-check (non-zero `exit`, not exit 0) the moment jq fails to *parse* or *open*
  # one iter file — mirroring how collect_valid_files and --persist guard their jq.
  #
  # Two wrong-shape cases that must NOT pass silently (this is the exact corruption
  # the self-check exists to surface, and in a STANDALONE --self-check run the
  # --persist/--mode parse paths have not run to breadcrumb the bad file first):
  #   (a) jq fails to *parse* or *open* the file (malformed/unreadable) → non-zero
  #       exit → the `if !` arm WARNS and skips the file (no field validation).
  #   (b) the file is valid JSON but NOT an object (e.g. [], null, "x") → jq emits
  #       the `__non_object__` sentinel (no real field is named that), which WARNS
  #       and skips — otherwise a wrong-shape workpad masquerades as complete.
  # An object yields its missing-field names; field names are bare identifiers, so
  # the `for field in $missing` word-split is safe (and emits one warning line each).
  local iter field missing shadow_missing provenance_state provenance_value evidence_bad
  for iter in "$WORKPAD_DIR"/iter-*.json; do
    [ -e "$iter" ] || continue
    # A synthesized record (issue #381) is a recognized degraded class — it
    # legitimately carries only what the fix-commit floor can establish plus the
    # issue-#541 unrecoverable-provenance stamps, so it is validated against THAT
    # minimal set (ITER_SYNTH_EXPECTED_FIELDS — see its definition for the members),
    # not the full ITER_EXPECTED_FIELDS (a wave of spurious warnings would train
    # operators to ignore the self-check) — and not against nothing, or a
    # truncated/hand-edited synthesized record would validate silently (the
    # writer-controlled flag must not buy a total exemption).
    if ! missing="$("$DEVFLOW_JQ" -r --arg fields "$ITER_EXPECTED_FIELDS" --arg synth_fields "$ITER_SYNTH_EXPECTED_FIELDS" \
                      'if type == "object" then (if (.synthesized == true) then (($synth_fields | split(" ")) - keys)[] else (($fields | split(" ")) - keys)[] end) else "__non_object__" end' \
                      "$iter" 2>/dev/null)"; then
      echo "::warning::devflow review-and-fix self-check: iter workpad '$(basename "$iter")' is unreadable or not valid JSON — cannot validate its fields" >&2
      continue
    fi
    if [ "$missing" = "__non_object__" ]; then
      echo "::warning::devflow review-and-fix self-check: iter workpad '$(basename "$iter")' is valid JSON but not an object — cannot validate its fields" >&2
      continue
    fi
    for field in $missing; do
      echo "::warning::devflow review-and-fix self-check: iter workpad '$(basename "$iter")' is missing expected field '${field}'" >&2
    done
    # Evidence-provenance SHAPE validation (issue #541). ITER_SYNTH_EXPECTED_FIELDS
    # membership above proves only that the KEY is present, while the invariant this
    # issue exists to protect is about the VALUE: a synthesizer that regressed to
    # stamping `[]` / `{"status":"not-run"}` — the LEGITIMATE values of a real no-fix
    # iteration — keeps every key present and so passes a presence-only check in
    # silence, which is the unknown-collapsed-onto-a-real-value defect itself. Scoped
    # to keys that ARE present, so a dropped field warns once (above) rather than
    # twice, and the two conditions stay separately attributable.
    # Every deref is TYPE-GUARDED before it is taken — the same discipline the
    # promotion_provenance arm below applies, whose first predicate is likewise a type
    # check — and the `reason` is required non-empty so the validator demands exactly the
    # shape the producer is tested to write (a one-sided invariant would accept
    # `{"status":"unrecoverable"}` with no reason — "unknown" without saying what is
    # unknown, the same information loss one level down). An untyped `.reference_reads.fix_delta` deref made jq ABORT (rc 5) on
    # an agent-mutable workpad whose `reference_reads` was a string/array, and because
    # the emit is gated on this `if`, the abort discarded the sweep violations jq had
    # ALREADY printed on the same run — the guard failing open on exactly the record it
    # exists to catch. The `else` arm is a DEFENSIVE BACKSTOP, not a reachable path on
    # today's inputs: an unreadable/non-object record is already caught by the missing-
    # field block above (which `continue`s before reaching here), and with every deref
    # type-guarded the filter cannot abort on any valid-JSON object — probing malformed
    # JSON, `[]`, `null`, `"x"`, and an empty file fires it zero times. It is kept so a
    # FUTURE predicate added here that can abort degrades loudly instead of silently
    # reading as clean, which is the failure this arm's absence originally produced.
    # `2>&1` keeps jq's own diagnostic as the breadcrumb text.
    if evidence_bad="$("$DEVFLOW_JQ" -r '
      if (.synthesized != true) then empty
      else
        (["sweep_defs_read", "sweep_evidence"][] as $f
          | select(has($f))
          | select(((.[$f] | type) != "object")
                   or ((.[$f].status // "") != "unrecoverable")
                   or (((.[$f].reason // "") | tostring | length) == 0))
          | $f),
        (select(has("reference_reads"))
          | select(((.reference_reads | type) != "object")
                   or ((.reference_reads.fix_delta | type) != "object")
                   or ((.reference_reads.fix_delta.status // "") != "unrecoverable")
                   or (((.reference_reads.fix_delta.reason // "") | tostring | length) == 0))
          | "reference_reads.fix_delta")
      end' "$iter" 2>&1)"; then
      for field in $evidence_bad; do
        echo "::warning::devflow review-and-fix self-check: synthesized iter workpad '$(basename "$iter")' carries field '${field}' WITHOUT unrecoverable provenance — a fix-commit-only record cannot establish this evidence, so a real-looking value here asserts something the synthesis floor never observed" >&2
      done
    else
      echo "::warning::devflow review-and-fix self-check: iter workpad '$(basename "$iter")' — the evidence-provenance shape check could not run (${evidence_bad:-no error text}); its provenance was NOT validated, so treat this record as unchecked rather than clean" >&2
    fi
    # Producer-drop advisory (issue #501): provenance is conditional, so it does
    # not belong in ITER_EXPECTED_FIELDS. Validate it only on non-synthesized
    # promoted records and stay advisory for legacy data.
    if provenance_state="$("$DEVFLOW_JQ" -r '
      if (.synthesized == true) or (.loop_role != "promoted") then "skip"
      elif ((.promotion_provenance | type) != "string") or ((.promotion_provenance | length) == 0) then "unknown"
      elif (.promotion_provenance as $p | ["shadow", "park-calibration-post-shadow", "park-calibration-pre-shadow"] | index($p)) != null then "known"
      else "unrecognized"
      end' "$iter" 2>/dev/null)"; then
      case "$provenance_state" in
        unknown)
          echo "::warning::devflow review-and-fix self-check: promoted iter workpad '$(basename "$iter")' has unreadable or absent promotion_provenance — legacy data and a producer drop are indistinguishable; verify the promotion handoff" >&2 ;;
        unrecognized)
          provenance_value="$("$DEVFLOW_JQ" -r '.promotion_provenance' "$iter" 2>/dev/null)" || provenance_value="<unreadable>"
          echo "::warning::devflow review-and-fix self-check: promoted iter workpad '$(basename "$iter")' has unrecognized promotion_provenance '$provenance_value' — verify the promotion producer" >&2 ;;
      esac
    fi
    # Synthesized shadow marker validation (issue #426): a `shadow` block carrying
    # `shadow_synthesized: true` is a recognized degraded class — validate it
    # against its own minimal set (SHADOW_SYNTH_EXPECTED_FIELDS), so a truncated
    # synthesized marker still warns while a complete one passes cleanly. A real
    # (agent-written) shadow block has no `shadow_synthesized` key, so this branch
    # never fires on it — the self-check leaves real shadow blocks unvalidated
    # exactly as before. The earlier `if !`/`continue` (the iter-field check above)
    # already warned about and skipped any unreadable/parse-failed file, so this
    # plain `if` only ever runs on a valid JSON object.
    if shadow_missing="$("$DEVFLOW_JQ" -r --arg sfields "$SHADOW_SYNTH_EXPECTED_FIELDS" \
                          'if ((.shadow | type) == "object") and (.shadow.shadow_synthesized == true) then (($sfields | split(" ")) - (.shadow | keys))[] else empty end' \
                          "$iter" 2>/dev/null)"; then
      for field in $shadow_missing; do
        echo "::warning::devflow review-and-fix self-check: iter workpad '$(basename "$iter")' has a synthesized shadow marker missing expected field '${field}'" >&2
      done
    fi
  done
  return 0
}

# ── --persist (Layer 3): derive + durable-copy → telemetry-branch write ──────

# Persist one run dir's artifacts (best-effort). Returns 0 always.
persist_one() {
  local dir="$1" slug="$2" run_id="$3" root="$4" allow_synth="${5:-1}"
  # Basename-derived identities need the same unsubstituted-placeholder refusal
  # as the argv guard above: a literal `<slug>/<run-id>` DIRECTORY (left by a
  # non-substituting agent running a workpad-dir mkdir fence verbatim) reaches
  # discovery mode without ever passing through argv, and synthesizing into it
  # would fabricate the same placeholder identity the argv guard refuses.
  case "${dir}${slug}${run_id}" in
    *'<'*|*'>'*)
      echo "::warning::efficiency-trace.sh --persist: run dir '${dir}' carries an unsubstituted '<placeholder>' identity (a verbatim '<slug>/<run-id>' directory left by a non-substituting run?); refusing to persist or synthesize under it — remove or rename the directory to recover" >&2
      return 0 ;;
  esac
  local durable record out jq_rc cp_err ref rel_iter staged_iter stamp_tmp stamp_err existing_class
  local iters=("$dir"/iter-*.json)
  if [ ! -e "${iters[0]}" ]; then
    # No per-iteration workpad. Layer-3+ synthesis floor (issue #381): reconstruct
    # a minimal record from this branch's fix commits so a fully-dropped run still
    # contributes effectiveness telemetry. Three guards keep a fix commit from
    # being double-counted into (or misattributed across) runs' records: (a)
    # sha-level exclusion — synthesis skips any commit already recorded as a
    # fix_commit_sha by another run's iter-*.json (real or synthesized, tmp tree
    # or committed durable copy), so a workpad-holding sibling run, a later
    # targeted --workpad-dir invocation, and a later discovery pass all decline
    # the same commit; (b) among the workpad-less dirs of one slug, only the
    # lexicographically-latest run-id synthesizes (allow_synth=1) — the rest
    # breadcrumb; and (c) when the workpad-less dirs span MULTIPLE slugs in one
    # discovery pass, ownership of the branch's fix commits is ambiguous offline
    # (a stale slug's leftover empty dir could claim the current branch's
    # commits), so discovery synthesizes into NONE of them (allow_synth=2,
    # breadcrumb naming the targeted escape hatch). The residual window is a run
    # whose EVERY workpad copy (tmp and durable) was deleted after its record
    # was derived — the durable-copy layer exists precisely so that does not
    # happen.
    if [ "$ENABLED" != "true" ]; then
      # Telemetry off: synthesized workpads exist ONLY to feed the (disabled)
      # effectiveness record — unlike REAL workpads, whose flag-off durable copy
      # is a deliberate carve-out — so fabricating them here would commit
      # telemetry artifacts to a repo that switched telemetry off. One gate
      # covers both the targeted and discovery paths.
      echo "::warning::efficiency-trace.sh --persist: run ${slug}/${run_id} has no iter-*.json and efficiency telemetry is disabled; skipping synthesis (a disabled record has no consumer for a synthesized workpad)" >&2
      return 0
    fi
    if [ "$allow_synth" = "2" ]; then
      echo "::warning::efficiency-trace.sh --persist: run ${slug}/${run_id} has no iter-*.json, but workpad-less run dirs span multiple slugs in this discovery pass — the branch's fix commits cannot be attributed to a slug offline, so synthesis is skipped for all of them; to synthesize this run explicitly, rerun with --persist --workpad-dir <dir> --slug ${slug}" >&2
      return 0
    fi
    if [ "$allow_synth" != "1" ]; then
      echo "::warning::efficiency-trace.sh --persist: run ${slug}/${run_id} has no iter-*.json and is not the synthesis target for slug '${slug}' (a later run-id holds it); skipping synthesis so fix commits are not double-counted" >&2
      return 0
    fi
    # Three-way outcome (unknown is never collapsed onto "found none" — the
    # repo's describe-denial-count.sh gotcha): rc 2 = selection ran, nothing
    # unrecorded to synthesize; rc 3 = the search could not run (unresolvable
    # base ref OR a failed git log — whether commits exist was never
    # established); rc 4 = commits were selected but every record write failed.
    local synth_rc=0
    synthesize_iter_workpads "$dir" "$root" || synth_rc=$?
    case "$synth_rc" in
      0) : ;;
      3)
        echo "::warning::efficiency-trace.sh --persist: run ${slug}/${run_id} left no iter-*.json and the fix-commit search could not run (an uncreatable target dir, an unresolvable base ref, a base ref left unestablished by a failed origin refresh, a telemetry-branch fetch left unestablished by a failed/unattempted fetch, or a failed git log enumeration — the warning above names which) — whether matching fix commits exist was never established; telemetry not synthesized" >&2
        return 0 ;;
      4)
        echo "::warning::efficiency-trace.sh --persist: run ${slug}/${run_id} left no iter-*.json; matching fix commits were selected but every synthesized record write failed (see the per-commit warnings above, which carry the actual jq error text — disk/permissions, a malformed jq program, or on the cloud tier the sandbox's redirect-write denial into .prflow/tmp) — telemetry not synthesized" >&2
        return 0 ;;
      2)
        echo "::warning::efficiency-trace.sh --persist: run ${slug}/${run_id} left no iter-*.json and no unrecorded 'fix: address review findings (iteration N)' commits were found — per-iteration effectiveness telemetry was not captured this run; nothing to synthesize" >&2
        return 0 ;;
      *)
        # Unknown is not zero: an rc outside the 0/2/3/4 contract (a signal, a
        # future drift) must not be reported as "no commits were found".
        echo "::warning::efficiency-trace.sh --persist: run ${slug}/${run_id} left no iter-*.json and synthesis exited with unexpected rc=${synth_rc} — whether matching fix commits exist was never established; telemetry not synthesized" >&2
        return 0 ;;
    esac
    iters=("$dir"/iter-*.json)
    if [ ! -e "${iters[0]}" ]; then
      # Defensive: unreachable while synthesize_iter_workpads' rc-0 contract
      # guarantees >=1 surviving write into $dir — but if a future edit
      # desynchronizes that contract, dropping the record with zero signal is
      # exactly the silent hole this file exists to close.
      echo "::warning::efficiency-trace.sh --persist: synthesis reported success but no iter-*.json exists in ${dir}; record not derived for ${slug}/${run_id}" >&2
      return 0
    fi
  fi
  # NOTE (issue #441): the historical `source == "review"` skip is GONE. Both
  # standalone /devflow:review (Phase 4.5) and /devflow:review-and-fix now persist
  # through this SAME code path to the SAME telemetry branch — the record is keyed
  # by (slug, run-id) and its jq derivation branches on the workpad's own `source`
  # field, so a review run yields a review-mode record and a fix-loop run a
  # fix-loop record, both idempotent by branch presence. Unifying the paths is the
  # whole point of #441 (one durable store for every writable run), so a review run
  # discovered here is persisted, not skipped.

  # Shadow synthesis floor (issue #426): recover a dropped-but-promoted shadow
  # block as a minimal marker BEFORE the durable copy below, so a synthesized
  # marker is committed alongside the workpads it annotates. Telemetry-gated like
  # the iter floor above — a synthesized marker is a telemetry artifact, so a
  # telemetry-disabled repo gets none. (Runs on the real-workpad path too: a
  # synthesized-iter run is all `loop_role: "fix"` with no promotion evidence, so
  # the floor is a no-op there and only fires when a real promoted iter exists.)
  [ "$ENABLED" = "true" ] && synthesize_shadow_markers "$dir"

  # ── Everything below STAGES into .prflow/tmp/ (never the tracked tree) so the
  # detached telemetry-branch write (do_persist) picks it up (issue #441). The
  # current branch, HEAD, and the working tree are never touched. _TELEMETRY_STAGE
  # is the shared staging root do_persist created; its subtree mirrors the exact
  # .prflow/logs/… layout the branch commit will carry. ────────────────────────

  # Durable workpad copy — NOT telemetry-gated (runs on every writable run).
  # Copies every *.json in the run dir (iter-*.json + deferrals.json), mirroring
  # the review-and-fix Loop Exit durable-copy (references/loop-exit.md). Content-idempotent: the branch write's
  # tree-equality no-op guard emits no commit when the bytes are unchanged.
  durable="${_TELEMETRY_STAGE}/.prflow/logs/review/${slug}/${run_id}"
  if ! cp_err="$( { mkdir -p "$durable" && cp -p "$dir"/*.json "$durable"/; } 2>&1 )"; then
    echo "::warning::efficiency-trace.sh --persist: durable workpad copy failed (${dir} -> ${durable}): ${cp_err:-unknown}; best-effort, continuing" >&2
  else
    # Emitted-provenance backfill (issue #534): stamp `synthesized: false` onto the
    # DURABLE copy of any agent-written iter record that carries no `synthesized`
    # key, so the persisted artifact a later reader consults affirmatively records
    # its provenance off the agent's decision path (route (b)). Operates on the
    # staged durable copy ONLY — the source run dir stays byte-identical, an
    # existing --persist contract the shadow floor and #499 union logic rely on. A
    # no-op on synthesized records (they already carry synthesized:true) and on a
    # second --persist (the key is present). Placed before the telemetry-stamp loop
    # so the durable bytes carry provenance before that loop's idempotency read.
    stamp_emitted_provenance "$durable"
    ref="$(devflow_telemetry_ref)"
    for staged_iter in "$durable"/iter-*.json; do
      [ -e "$staged_iter" ] || continue
      existing_class=""
      rel_iter="${staged_iter#"${_TELEMETRY_STAGE}/"}"
      if devflow_telemetry_blob_exists "$root" "$ref" "$rel_iter"; then
        # Existing legacy absent/null blobs are exclusively backfill territory.
        # Classify the durable value before deciding whether this staged copy may
        # overlay it. Legacy/non-object history stays backfill-owned; marker and
        # established values may accept information-preserving source updates.
        existing_class="$(devflow_telemetry_show_blob "$root" "$ref" "$rel_iter" \
          | "$DEVFLOW_JQ" -r 'if type != "object" then "other" elif .telemetry == "unavailable" then "marker" elif ((has("telemetry") | not) or .telemetry == null) then "legacy" else "established" end' 2>/dev/null)" || existing_class="other"
        if [ "$existing_class" = legacy ]; then
          # Do not carry an existing legacy blob in this run's overlay at all.
          # Besides keeping history in the backfill's ownership, this prevents a
          # local CAS retry from reapplying stale bytes after a concurrent
          # backfill advanced the telemetry ref with the normalized marker.
          echo "::warning::efficiency-trace.sh --persist: existing durable iter '${rel_iter}' still has unestablished telemetry; leaving the backfill-owned historical blob untouched" >&2
          rm -f "$staged_iter" 2>/dev/null || true
          continue
        fi
        if [ "$existing_class" = other ]; then
          echo "::warning::efficiency-trace.sh --persist: existing durable iter '${rel_iter}' could not be safely classified; leaving the historical blob untouched" >&2
          rm -f "$staged_iter" 2>/dev/null || true
          continue
        fi
      fi
      if ! "$DEVFLOW_JQ" -e 'type == "object"' "$staged_iter" >/dev/null 2>&1; then
        if [ "${existing_class:-}" = established ]; then
          echo "::warning::efficiency-trace.sh --persist: staged iter workpad '${rel_iter}' is malformed JSON or a valid non-object; leaving the established durable blob untouched" >&2
          rm -f "$staged_iter" 2>/dev/null || true
          continue
        fi
        echo "::warning::efficiency-trace.sh --persist: staged iter workpad '${rel_iter}' is malformed JSON or a valid non-object; copied byte-verbatim and telemetry was not fabricated" >&2
        continue
      fi
      if [ "${existing_class:-}" = established ] \
        && ! "$DEVFLOW_JQ" -e 'has("telemetry") and (.telemetry != null)' "$staged_iter" >/dev/null 2>&1; then
        # A retained or rolled-back source must not downgrade established durable
        # telemetry to the unavailable marker. Leave the whole historical blob
        # untouched; a later source carrying established telemetry may still
        # update this path normally.
        echo "::warning::efficiency-trace.sh --persist: staged iter workpad '${rel_iter}' has unestablished telemetry; leaving the established durable blob untouched" >&2
        rm -f "$staged_iter" 2>/dev/null || true
        continue
      fi
      if "$DEVFLOW_JQ" -e 'has("telemetry") and (.telemetry != null)' "$staged_iter" >/dev/null 2>&1; then
        continue
      fi
      stamp_tmp="${staged_iter}.telemetry-tmp"
      stamp_err=""
      if stamp_err="$("$DEVFLOW_JQ" '.telemetry = "unavailable"' "$staged_iter" 2>&1 > "$stamp_tmp")" && mv "$stamp_tmp" "$staged_iter"; then
        :
      else
        rm -f "$stamp_tmp" 2>/dev/null || true
        echo "::warning::efficiency-trace.sh --persist: could not stamp unestablished telemetry in staged iter workpad '${rel_iter}' (${stamp_err:-write/move failed}); staged copy retained best-effort" >&2
      fi
    done
  fi

  # Effectiveness record — telemetry-gated, presence-based idempotency tested ON
  # THE TELEMETRY BRANCH (issue #441 AC14): `git cat-file -e <ref>:<path>`. Never
  # re-derive an existing record — its `generated_at` is stamped at derivation
  # time, so re-deriving would churn the bytes and force a spurious new branch
  # commit, defeating the no-op-on-re-run contract. A record already on the branch
  # (a prior --persist) is not re-DERIVED here: staged for neither derivation nor
  # write BY THIS DISCOVERY PASS. (Issue #475 relaxes the store's strictly-append-
  # only posture: the harness-cost floor's merge arm — apply_harness_floor, run once
  # after this loop in do_persist — reads such a record back and re-stages it with an
  # add-if-absent `harness_cost` key, byte-preserving `generated_at` and every other
  # field. A record already carrying harness_cost is still left untouched, so the
  # backstop re-run remains a tree-equality no-op. This loop's derivation path is
  # unchanged; only the floor mutates an existing path, and it never re-derives.)
  if [ "$ENABLED" = "true" ]; then
    local rel_record
    [ -n "${ref:-}" ] || ref="$(devflow_telemetry_ref)"
    rel_record=".prflow/logs/efficiency/${slug}-${run_id}.json"
    if ! devflow_telemetry_blob_exists "$root" "$ref" "$rel_record"; then
      record="${_TELEMETRY_STAGE}/${rel_record}"
      collect_valid_files "$dir"
      # `if !` guards `set -e` on a failing command-substitution assignment, and
      # captures emit_jq's rc so a jq DERIVATION FAILURE (broken filter, jq missing,
      # --argjson rejected) is distinguished from a benign empty derivation (rc 0,
      # zero readable iterations → emit_jq prints nothing, matching the flag-off
      # contract). The former is a real malfunction that would otherwise drop a
      # recoverable record with no signal — exactly the silent hole this issue
      # closes — so warn.
      jq_rc=0
      out="$(emit_jq record "$slug")" || jq_rc=$?
      if [ "$jq_rc" -ne 0 ]; then
        echo "::warning::efficiency-trace.sh --persist: record derivation (jq) failed (rc=${jq_rc}) for ${slug}/${run_id}; record not written" >&2
      elif [ -n "$out" ]; then
        if mkdir -p "$(dirname "$record")" 2>/dev/null; then
          # Check the redirection itself: a write failure after mkdir (ENOSPC,
          # EROFS, quota, perms) must not stage a truncated/partial record for the
          # branch write.
          if ! printf '%s\n' "$out" > "$record"; then
            echo "::warning::efficiency-trace.sh --persist: staging record ${record} failed (disk/permission); not persisted for ${slug}/${run_id}" >&2
            rm -f "$record" 2>/dev/null
          fi
        else
          echo "::warning::efficiency-trace.sh --persist: could not create $(dirname "$record"); record not written for ${slug}/${run_id}" >&2
        fi
      fi
    fi
  fi
  return 0
}

# ── Harness-side cost floor (Layer 4, issue #475) ────────────────────────────
# Merge the claude-code-action execution_file's cost — normalized by the reader
# (scripts/extract-execution-cost.py) and handed in via DEVFLOW_EXECUTION_COST — into
# THIS run's efficiency record as a distinct top-level `harness_cost` object. This is
# the FIRST floor operand NOT fed by an agent-volunteered value: the execution file is
# written harness-side, so a run that dropped every telemetry emit still contributes a
# cost record. The reader is NEVER exec'd from here — doing so would add a python3 exec
# edge to a Stop-hook trusted-closure entry (the #458 constraint) — so the glue helper
# (scripts/prepare-harness-floor.sh) runs the reader and passes its already-normalized
# JSON in via the environment.
#
# Env inputs (all set by prepare-harness-floor.sh + the backstop step):
#   DEVFLOW_EXECUTION_COST  the reader's normalized JSON; presence GATES the whole
#                           floor (unset/empty → silent no-op, --persist byte-identical
#                           to before — the in-run Loop-Exit persist and the Stop-hook
#                           persist both run with it unset by design, AC3).
#   DEVFLOW_EXECUTION_PR    the run's PR number — the skeleton slug (pr-<N>); empty
#                           skips the skeleton arm (the #431 analysis joins merged PRs).
#   DEVFLOW_COMMAND_CLASS   review|review-and-fix|pr-description|implement — the
#                           harness_cost.command field AND the skeleton gate
#                           (pr-description derives no record by design).
#   GITHUB_RUN_ID / GITHUB_RUN_ATTEMPT  the run-id identity the record is keyed by:
#                           <run-id> == ${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}, the same
#                           value skills/review-and-fix/references/loop-control.md's RUN_ID= line composes.
#   GITHUB_WORKFLOW_REF     the path-pinned workflow identity (harness_cost.workflow).
#
# Telemetry-gated exactly as record derivation is (AC8); best-effort/exit-0 like every
# other --persist arm. Per-phase aggregates never see floor data — harness_cost is a
# distinct TOP-LEVEL key, invisible to _run_cost/_telemetry_complete (AC9).

# Add harness_cost (add-if-absent) to an in-STAGING record file $1, via temp+mv so a
# failed jq leaves the file untouched. $2 is the harness_cost JSON, $3 a display label.
_floor_merge_staged() {
  local file="$1" hc="$2" label="$3" jq_err
  if "$DEVFLOW_JQ" -e 'has("harness_cost")' "$file" >/dev/null 2>&1; then
    echo "devflow: efficiency-trace.sh --persist: harness cost floor: ${label} already carries harness_cost; left untouched" >&2
    return 0
  fi
  if jq_err="$("$DEVFLOW_JQ" --argjson hc "$hc" '.harness_cost = $hc' "$file" 2>&1 > "$file.harnesstmp")"; then
    if mv "$file.harnesstmp" "$file" 2>/dev/null; then
      echo "devflow: efficiency-trace.sh --persist: harness cost floor: attached harness_cost to ${label}" >&2
    else
      echo "::warning::efficiency-trace.sh --persist: harness cost floor: could not move the merged ${label} into place; left without harness_cost" >&2
      rm -f "$file.harnesstmp" 2>/dev/null
    fi
  else
    echo "::warning::efficiency-trace.sh --persist: harness cost floor: could not merge harness_cost into ${label} (${jq_err:-no error text}); left without harness_cost" >&2
    rm -f "$file.harnesstmp" 2>/dev/null
  fi
}

# Consume DEVFLOW_EXECUTION_COST and land it as harness_cost on this run's record
# (merge arm) or a minimal cost skeleton (skeleton arm). $1 root, $2 staging root.
apply_harness_floor() {
  local root="$1" stage="$2"
  # Unset/empty cost → INERT and SILENT: --persist behaves byte-for-byte as before.
  # This guard MUST stay first so the agent-side persist paths emit no breadcrumb (AC3).
  [ -n "${DEVFLOW_EXECUTION_COST:-}" ] || return 0
  # Gated (AC8): sits under efficiency_telemetry_enabled exactly as record derivation
  # does. Set-but-gated-off draws one breadcrumb (the operand WAS supplied) and writes
  # nothing.
  if [ "$ENABLED" != "true" ]; then
    echo "::warning::efficiency-trace.sh --persist: harness cost floor: efficiency telemetry is disabled; DEVFLOW_EXECUTION_COST supplied but not attached this run" >&2
    return 0
  fi
  # Validate the operand is a JSON OBJECT — a malformed value draws one breadcrumb and
  # no floor write (AC3). Never feed an unvalidated env value into a jq --argjson, which
  # would abort the helper under set -e.
  if ! printf '%s' "$DEVFLOW_EXECUTION_COST" | "$DEVFLOW_JQ" -e 'type == "object"' >/dev/null 2>&1; then
    echo "::warning::efficiency-trace.sh --persist: harness cost floor: DEVFLOW_EXECUTION_COST is not a JSON object; no floor write this run" >&2
    return 0
  fi
  # Run-id identity the record is keyed by. On the cloud tier GITHUB_RUN_ID is always
  # set; without it this run cannot be identified, so decline (never attach to an
  # arbitrary record a discovery pass swept — AC3).
  if [ -z "${GITHUB_RUN_ID:-}" ]; then
    echo "::warning::efficiency-trace.sh --persist: harness cost floor: GITHUB_RUN_ID is unset, so this run's record cannot be identified; no floor write" >&2
    return 0
  fi
  local ident="${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT:-1}"
  # engine_version: the .version of plugin.json resolved BESIDE this helper — null with a
  # breadcrumb when unreadable (AC4), never a fabricated value.
  local plugin_json="$HERE/../.claude-plugin/plugin.json" ev=""
  if [ -f "$plugin_json" ] && ev="$("$DEVFLOW_JQ" -r 'if (.version | type) == "string" then .version else empty end' "$plugin_json" 2>/dev/null)" && [ -n "$ev" ]; then
    :
  else
    ev=""
    echo "::warning::efficiency-trace.sh --persist: harness cost floor: could not read .version from ${plugin_json}; engine_version recorded as null" >&2
  fi
  # Build harness_cost (AC4 — EXACTLY these fields): metadata plus the reader's figures
  # spread in. workflow/command are null when their env is empty (unknown-is-not-zero).
  local harness_cost
  if ! harness_cost="$(printf '%s' "$DEVFLOW_EXECUTION_COST" | "$DEVFLOW_JQ" -c \
        --arg ev "$ev" \
        --arg wf "${GITHUB_WORKFLOW_REF:-}" \
        --arg cmd "${DEVFLOW_COMMAND_CLASS:-}" \
        '{cost_source: "execution-file",
          engine_version: (if $ev == "" then null else $ev end),
          workflow: (if $wf == "" then null else $wf end),
          command: (if $cmd == "" then null else $cmd end),
          scope: "whole-job",
          cost_usd: .cost_usd,
          tokens: .tokens,
          model_usage: .model_usage,
          num_turns: .num_turns,
          duration_ms: .duration_ms}' 2>/dev/null)"; then
    echo "::warning::efficiency-trace.sh --persist: harness cost floor: could not assemble the harness_cost object (jq failed); no floor write" >&2
    return 0
  fi

  local eff_dir="${stage}/.prflow/logs/efficiency" f
  # Merge arm (a): a record DERIVED THIS PASS and staged under the run-id identity —
  # `<slug>-<ident>.json`, matched by `*-<ident>.json` so ANY slug (pr-<N>, a branch
  # slug, or a synthesized run) is caught, but ONLY for this run-id (AC3: never a record
  # a discovery pass swept for another run).
  if [ -d "$eff_dir" ]; then
    for f in "$eff_dir"/*-"$ident".json; do
      [ -e "$f" ] || continue
      _floor_merge_staged "$f" "$harness_cost" "staged record $(basename "$f")"
      return 0
    done
  fi
  # Merge arm (b): a record already PERSISTED on the telemetry branch for this run-id (a
  # prior --persist of this run — the in-run Loop-Exit persist landed it without
  # harness_cost, since the execution file does not exist mid-run). Read it back, add
  # harness_cost only when absent, re-stage. A record already carrying harness_cost is
  # left unstaged, so re-running the backstop ends at the tree-equality no-op (AC5).
  local ref rel base blob
  ref="$(devflow_telemetry_ref)"
  while IFS= read -r rel; do
    case "$rel" in *-"$ident".json) ;; *) continue ;; esac
    base="$(basename "$rel")"
    blob="$(devflow_telemetry_show_blob "$root" "$ref" "$rel")" || continue
    [ -n "$blob" ] || continue
    if printf '%s' "$blob" | "$DEVFLOW_JQ" -e 'has("harness_cost")' >/dev/null 2>&1; then
      echo "devflow: efficiency-trace.sh --persist: harness cost floor: record ${rel} already carries harness_cost; leaving it untouched (backstop re-run no-op)" >&2
      return 0
    fi
    mkdir -p "$eff_dir" 2>/dev/null || true
    if printf '%s' "$blob" | "$DEVFLOW_JQ" --argjson hc "$harness_cost" '.harness_cost = $hc' > "${eff_dir}/${base}" 2>/dev/null; then
      echo "devflow: efficiency-trace.sh --persist: harness cost floor: attached harness_cost to already-persisted record ${rel}" >&2
    else
      echo "::warning::efficiency-trace.sh --persist: harness cost floor: could not merge harness_cost into ${rel}; no floor write" >&2
      rm -f "${eff_dir}/${base}" 2>/dev/null
    fi
    return 0
  done < <(devflow_telemetry_list_blobs "$root" "$ref" ".prflow/logs/efficiency/")

  # Skeleton arm (AC6): no record for this run-id anywhere. Only record-DERIVING command
  # classes get a skeleton — pr-description's healthy state is "no record", so it takes a
  # named breadcrumb instead. An empty PR skips (the analysis joins merged PRs only).
  case "${DEVFLOW_COMMAND_CLASS:-}" in
    review|review-and-fix|implement) ;;
    pr-description)
      echo "::warning::efficiency-trace.sh --persist: harness cost floor: no record by design for command class 'pr-description'; no skeleton written" >&2
      return 0 ;;
    *)
      echo "::warning::efficiency-trace.sh --persist: harness cost floor: command class '${DEVFLOW_COMMAND_CLASS:-<unset>}' does not derive records; no skeleton written" >&2
      return 0 ;;
  esac
  if [ -z "${DEVFLOW_EXECUTION_PR:-}" ]; then
    echo "::warning::efficiency-trace.sh --persist: harness cost floor: no record for run-id ${ident} and DEVFLOW_EXECUTION_PR is empty; skeleton skipped (the analysis joins merged PRs only)" >&2
    return 0
  fi
  local slug="pr-${DEVFLOW_EXECUTION_PR}" generated_at skel
  # Skeleton-overwrite guard (issue #475 review): merge-arm-b reaches here by falling through
  # a `while … done < <(devflow_telemetry_list_blobs …)` loop that iterates ZERO times BOTH
  # when the branch genuinely holds no record for this run-id AND when list_blobs swallowed a
  # git failure (it returns empty on a rev-parse/ls-tree error) — an ambiguous signal. If a
  # real, populated record already exists on the branch under the skeleton's OWN filename
  # (`pr-<N>-<ident>.json`, the common review-and-fix collision), writing a contentless
  # skeleton would OVERWRITE it (the union applies a staged path local-wins). So re-check the
  # blob explicitly and decline rather than resting on the empty-list signal: a missed merge
  # (record kept intact, gains harness_cost on a later working re-run) is strictly safer than
  # replacing a real record with an iterations:0 skeleton.
  if [ -n "$ref" ] && devflow_telemetry_blob_exists "$root" "$ref" ".prflow/logs/efficiency/${slug}-${ident}.json" 2>/dev/null; then
    echo "::warning::efficiency-trace.sh --persist: harness cost floor: a record already exists on the telemetry branch at .prflow/logs/efficiency/${slug}-${ident}.json (merge-arm-b's branch listing may have failed silently); declining to overwrite it with a cost skeleton" >&2
    return 0
  fi
  generated_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "$eff_dir" 2>/dev/null || true
  # source:null (no mode's derivation ran — outside both mode segments); synthesized:true
  # + iterations:0 + source:null + harness_cost.cost_source is what distinguishes a
  # cost-only skeleton from a #381 commit-reconstructed record (AC6).
  if skel="$("$DEVFLOW_JQ" -n --arg slug "$slug" --arg ga "$generated_at" --argjson hc "$harness_cost" \
        '{schema_version: 1, slug: $slug, generated_at: $ga, source: null,
          synthesized: true, iterations: 0, per_iteration: [], telemetry: [],
          harness_cost: $hc}' 2>/dev/null)" && printf '%s\n' "$skel" > "${eff_dir}/${slug}-${ident}.json"; then
    echo "devflow: efficiency-trace.sh --persist: harness cost floor: no record for run-id ${ident}; wrote a minimal cost skeleton ${slug}-${ident}.json (source:null, synthesized:true)" >&2
  else
    echo "::warning::efficiency-trace.sh --persist: harness cost floor: could not write the cost skeleton for ${slug}-${ident}; no floor write" >&2
    rm -f "${eff_dir}/${slug}-${ident}.json" 2>/dev/null
  fi
  return 0
}

# ── Permission-denial forensics floor (Layer 4b, issue #1064 D2) ─────────────
# Consume DEVFLOW_DENIAL_RECORD (scripts/build-denial-record.sh's single-line JSON) and
# land it as a distinct top-level `permission_denials` key on this run's efficiency
# record. Mirrors apply_harness_floor exactly (same run-id identity targeting, same
# four arms — staged record / already-persisted branch record / skeleton / decline) so
# the two floors behave identically.
#
# WHY THE SKELETON ARM EXISTS (it replaced an unconditional decline). The decline it
# replaced reasoned that "a denial record with no cost record to key it has no analysis
# join". That reasoning is right about ANALYSIS and wrong about FORENSICS: the cross-run
# cost analysis does want a cost record beside the count, but the denial record's primary
# job is telling an operator, after the fact, what the harness refused on a run that
# produced no verdict. An unjoinable denial record still beats a vanished one — and the
# vanished case was reachable, on exactly the runs that need it most. A run that died
# before yielding usable cost figures leaves scripts/prepare-harness-floor.sh's
# _cost_has_figures refusing to stage an all-null harness_cost, which empties
# DEVFLOW_EXECUTION_COST, which returns apply_harness_floor at its first guard — before
# its own skeleton arm — so no host record exists for the fully-built denial record to
# merge onto, and the record was discarded with only a job-log warning that expires.
# That is the stall / crash / execution-ceiling class.
#
# WHAT THIS DOES AND DOES NOT CLOSE. It closes the all-null-cost drop path. It is NOT an
# unconditional guarantee that every denial reaches durable storage: the skeleton is a
# faithful mirror of apply_harness_floor's, so it inherits that skeleton's two gates, and
# each remains a real drop path:
#   (1) DEVFLOW_COMMAND_CLASS is `pr-description` or does not classify — no record is
#       derived for those classes at all, so there is no keyed store to write into;
#   (2) DEVFLOW_EXECUTION_PR is empty — the record is keyed `<slug>-<run-id>.json` and the
#       slug is `pr-<N>`, so with no PR number there is no identity to file it under.
# Both take a named breadcrumb rather than a silent drop. How often either is reached in
# practice is UNESTABLISHED and cannot be established from this tree — do not read the
# breadcrumbs' absence as evidence of zero.
#
# Add the denial record (add-if-absent) to an in-STAGING record file $1, via temp+mv.
_denial_merge_staged() {
  local file="$1" dr="$2" label="$3" jq_err
  if "$DEVFLOW_JQ" -e 'has("permission_denials")' "$file" >/dev/null 2>&1; then
    echo "devflow: efficiency-trace.sh --persist: denial floor: ${label} already carries permission_denials; left untouched" >&2
    return 0
  fi
  if jq_err="$("$DEVFLOW_JQ" --argjson dr "$dr" '.permission_denials = $dr' "$file" 2>&1 > "$file.denialtmp")"; then
    if mv "$file.denialtmp" "$file" 2>/dev/null; then
      echo "devflow: efficiency-trace.sh --persist: denial floor: attached permission_denials to ${label}" >&2
    else
      echo "::warning::efficiency-trace.sh --persist: denial floor: could not move the merged ${label} into place; left without permission_denials" >&2
      rm -f "$file.denialtmp" 2>/dev/null
    fi
  else
    echo "::warning::efficiency-trace.sh --persist: denial floor: could not merge permission_denials into ${label} (${jq_err:-no error text}); left without permission_denials" >&2
    rm -f "$file.denialtmp" 2>/dev/null
  fi
}

apply_denial_floor() {
  local root="$1" stage="$2"
  # Unset/empty → INERT and SILENT (byte-identical to before). MUST stay first.
  [ -n "${DEVFLOW_DENIAL_RECORD:-}" ] || return 0
  # Gated exactly as record derivation is: set-but-gated-off draws one breadcrumb.
  if [ "$ENABLED" != "true" ]; then
    echo "::warning::efficiency-trace.sh --persist: denial floor: efficiency telemetry is disabled; DEVFLOW_DENIAL_RECORD supplied but not attached this run" >&2
    return 0
  fi
  # Validate the operand is a JSON OBJECT — never feed an unvalidated env value to
  # --argjson (which would abort under set -e). A malformed value → one breadcrumb, no write.
  if ! printf '%s' "$DEVFLOW_DENIAL_RECORD" | "$DEVFLOW_JQ" -e 'type == "object"' >/dev/null 2>&1; then
    echo "::warning::efficiency-trace.sh --persist: denial floor: DEVFLOW_DENIAL_RECORD is not a JSON object; no floor write this run" >&2
    return 0
  fi
  if [ -z "${GITHUB_RUN_ID:-}" ]; then
    echo "::warning::efficiency-trace.sh --persist: denial floor: GITHUB_RUN_ID is unset, so this run's record cannot be identified; no floor write" >&2
    return 0
  fi
  local ident="${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT:-1}"
  local dr="$DEVFLOW_DENIAL_RECORD"
  local eff_dir="${stage}/.prflow/logs/efficiency" f
  # Merge arm (a): a record staged THIS PASS under this run-id identity.
  if [ -d "$eff_dir" ]; then
    for f in "$eff_dir"/*-"$ident".json; do
      [ -e "$f" ] || continue
      _denial_merge_staged "$f" "$dr" "staged record $(basename "$f")"
      return 0
    done
  fi
  # Merge arm (b): a record already PERSISTED on the telemetry branch for this run-id.
  local ref rel base blob
  ref="$(devflow_telemetry_ref)"
  while IFS= read -r rel; do
    case "$rel" in *-"$ident".json) ;; *) continue ;; esac
    base="$(basename "$rel")"
    blob="$(devflow_telemetry_show_blob "$root" "$ref" "$rel")" || continue
    [ -n "$blob" ] || continue
    if printf '%s' "$blob" | "$DEVFLOW_JQ" -e 'has("permission_denials")' >/dev/null 2>&1; then
      echo "devflow: efficiency-trace.sh --persist: denial floor: record ${rel} already carries permission_denials; leaving it untouched (backstop re-run no-op)" >&2
      return 0
    fi
    mkdir -p "$eff_dir" 2>/dev/null || true
    if printf '%s' "$blob" | "$DEVFLOW_JQ" --argjson dr "$dr" '.permission_denials = $dr' > "${eff_dir}/${base}" 2>/dev/null; then
      echo "devflow: efficiency-trace.sh --persist: denial floor: attached permission_denials to already-persisted record ${rel}" >&2
    else
      echo "::warning::efficiency-trace.sh --persist: denial floor: could not merge permission_denials into ${rel}; no floor write" >&2
      rm -f "${eff_dir}/${base}" 2>/dev/null
    fi
    return 0
  done < <(devflow_telemetry_list_blobs "$root" "$ref" ".prflow/logs/efficiency/")

  # Skeleton arm: no efficiency record for this run-id anywhere (staged or on-branch).
  # Mirrors apply_harness_floor's skeleton arm — same class gate, same empty-PR gate,
  # same overwrite guard, same minimal `synthesized: true, source: null` shape — with
  # `permission_denials` in place of `harness_cost`. See the block comment above this
  # function for why a record that cannot join the cost analysis is still written, and
  # for the two residual drop paths the two gates below leave open.
  #
  # Only record-DERIVING command classes get a skeleton: pr-description's healthy state
  # is "no record", so a skeleton there would invent a store entry the analysis is built
  # to not expect.
  case "${DEVFLOW_COMMAND_CLASS:-}" in
    review|review-and-fix|implement) ;;
    pr-description)
      echo "::warning::efficiency-trace.sh --persist: denial floor: no record by design for command class 'pr-description'; no denial skeleton written (residual drop path: the denial record is discarded this run)" >&2
      return 0 ;;
    *)
      echo "::warning::efficiency-trace.sh --persist: denial floor: command class '${DEVFLOW_COMMAND_CLASS:-<unset>}' does not derive records; no denial skeleton written (residual drop path: the denial record is discarded this run)" >&2
      return 0 ;;
  esac
  if [ -z "${DEVFLOW_EXECUTION_PR:-}" ]; then
    echo "::warning::efficiency-trace.sh --persist: denial floor: no record for run-id ${ident} and DEVFLOW_EXECUTION_PR is empty, so the skeleton has no pr-<N> slug to be keyed by; denial skeleton skipped (residual drop path: the denial record is discarded this run)" >&2
    return 0
  fi
  local slug="pr-${DEVFLOW_EXECUTION_PR}" generated_at skel
  # Skeleton-overwrite guard, mirroring apply_harness_floor's: merge arm (b) reaches here
  # by falling through a loop that iterates zero times BOTH when the branch genuinely holds
  # no record for this run-id AND when list_blobs swallowed a git failure (it returns empty
  # on a rev-parse/ls-tree error). Writing a contentless skeleton over a real, populated
  # record under the same filename would destroy it, so re-check the blob explicitly and
  # decline rather than rest on the empty-list signal.
  if [ -n "$ref" ] && devflow_telemetry_blob_exists "$root" "$ref" ".prflow/logs/efficiency/${slug}-${ident}.json" 2>/dev/null; then
    echo "::warning::efficiency-trace.sh --persist: denial floor: a record already exists on the telemetry branch at .prflow/logs/efficiency/${slug}-${ident}.json (merge-arm-b's branch listing may have failed silently); declining to overwrite it with a denial skeleton" >&2
    return 0
  fi
  generated_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "$eff_dir" 2>/dev/null || true
  # Same distinguishing marks as the cost skeleton — source:null (no mode's derivation
  # ran), synthesized:true, iterations:0 — so a reader tells a floor skeleton from a #381
  # commit-reconstructed record; here the carried key is permission_denials, not harness_cost.
  if skel="$("$DEVFLOW_JQ" -n --arg slug "$slug" --arg ga "$generated_at" --argjson dr "$dr" \
        '{schema_version: 1, slug: $slug, generated_at: $ga, source: null,
          synthesized: true, iterations: 0, per_iteration: [], telemetry: [],
          permission_denials: $dr}' 2>/dev/null)" && printf '%s\n' "$skel" > "${eff_dir}/${slug}-${ident}.json"; then
    echo "devflow: efficiency-trace.sh --persist: denial floor: no record for run-id ${ident}; wrote a minimal denial skeleton ${slug}-${ident}.json (source:null, synthesized:true) so the denial record is durable even without cost figures" >&2
  else
    echo "::warning::efficiency-trace.sh --persist: denial floor: could not write the denial skeleton for ${slug}-${ident}; no floor write" >&2
    rm -f "${eff_dir}/${slug}-${ident}.json" 2>/dev/null
  fi
  return 0
}

# ── Run-profile floor (Layer 4c, issue #2006) ────────────────────────────────
# Land this run's `run_profile` — per-phase durations, the workpad's final status word,
# the count of prior implement records for the same issue, and the engine step's own
# outcome — as one top-level key beside `harness_cost` and `permission_denials`. One
# object rather than four top-level keys: `_efficiency_entry` in
# scripts/build-experiment-records.py passes such an object through verbatim in one
# line, and four keys would need four independent add-if-absent guards racing over the
# same file.
#
# Every sub-field whose source could not be established holds the STRING `unestablished`
# and never `0`. A zero here is a real measurement, so collapsing an unknown onto it
# would let an unmeasured run enter an aggregate as a real value.

# Add one top-level KEY (add-if-absent) to an in-STAGING record file $1, via temp+mv so a
# failed jq leaves the file untouched. $2 = key name, $3 = its JSON value, $4 = a display
# label, $5 = the floor name for the breadcrumb. Parameterized on the key because this
# diff would otherwise add a third near-identical copy of _floor_merge_staged. The two
# existing copies are deliberately NOT folded into this one: lib/test/run.sh pins their
# breadcrumb literals, so rewording them would break coupled pins this change does not own.
_floor_merge_key_staged() {
  local file="$1" key="$2" val="$3" label="$4" floor="$5" jq_err
  if "$DEVFLOW_JQ" -e --arg k "$key" 'has($k)' "$file" >/dev/null 2>&1; then
    echo "devflow: efficiency-trace.sh --persist: ${floor}: ${label} already carries ${key}; left untouched" >&2
    return 0
  fi
  if jq_err="$("$DEVFLOW_JQ" --arg k "$key" --argjson v "$val" '.[$k] = $v' "$file" 2>&1 > "$file.keytmp")"; then
    if mv "$file.keytmp" "$file" 2>/dev/null; then
      echo "devflow: efficiency-trace.sh --persist: ${floor}: attached ${key} to ${label}" >&2
    else
      echo "::warning::efficiency-trace.sh --persist: ${floor}: could not move the merged ${label} into place; left without ${key}" >&2
      rm -f "$file.keytmp" 2>/dev/null
    fi
  else
    echo "::warning::efficiency-trace.sh --persist: ${floor}: could not merge ${key} into ${label} (${jq_err:-no error text}); left without ${key}" >&2
    rm -f "$file.keytmp" 2>/dev/null
  fi
}

# Count prior efficiency records on the telemetry branch carrying run_profile.issue_number
# equal to $2, excluding this run's own ident $3. Prints a decimal count, or the string
# `unestablished`.
#
# Probes the ref ITSELF rather than reading devflow_telemetry_list_blobs' output: that
# helper returns 0 and prints nothing on an absent ref, an unestablished ref probe AND an
# unreadable tree alike, so its empty output cannot distinguish a real zero from a failed
# read — the exact fail-open this count must not inherit.
_prior_implement_record_count() {
  local root="$1" issue="$2" ident="$3" ref rel base blob n=0 rc=0 listing
  ref="$(devflow_telemetry_ref)"
  git -C "$root" rev-parse --verify --quiet "$ref" >/dev/null 2>&1 || rc=$?
  if [ "$rc" -eq 1 ]; then
    # Absent ref. An established empty only when the pre-synthesis fetch actually ran:
    # on an ephemeral runner that never fetched, absence says nothing about prior records.
    case "${_DEVFLOW_TELEMETRY_FETCH_STATUS:-unattempted}" in
      ok) printf '0\n'; return 0 ;;
      *)  printf 'unestablished\n'; return 0 ;;
    esac
  fi
  if [ "$rc" -ne 0 ]; then printf 'unestablished\n'; return 0; fi
  if ! listing="$(git -c core.quotePath=false -C "$root" ls-tree -r --name-only "$ref" -- ".prflow/logs/efficiency/" 2>/dev/null)"; then
    printf 'unestablished\n'; return 0
  fi
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    base="$(basename "$rel")"
    case "$base" in *-"$ident".json) continue ;; esac
    blob="$(devflow_telemetry_show_blob "$root" "$ref" "$rel")" || continue
    [ -n "$blob" ] || continue
    if printf '%s' "$blob" | "$DEVFLOW_JQ" -e --argjson i "$issue" \
        '(.run_profile.issue_number? // null) == $i' >/dev/null 2>&1; then
      n=$((n + 1))
    fi
  done <<EOF
$listing
EOF
  printf '%s\n' "$n"
}

# Consume DEVFLOW_RUN_PROFILE (scripts/prepare-run-profile.sh's single-line JSON) and
# DEVFLOW_ENGINE_OUTCOME, and land them as one top-level `run_profile` key. Mirrors
# apply_harness_floor's arms so the two floors behave identically. $1 root, $2 staging root.
apply_run_profile_floor() {
  local root="$1" stage="$2"
  # Unset/empty profile → INERT and SILENT, so the agent-side persist call sites
  # (Loop-Exit, Stop-hook) stay byte-identical to before this floor existed.
  [ -n "${DEVFLOW_RUN_PROFILE:-}" ] || return 0
  if [ "$ENABLED" != "true" ]; then
    echo "::warning::efficiency-trace.sh --persist: run-profile floor: efficiency telemetry is disabled; DEVFLOW_RUN_PROFILE supplied but not attached this run" >&2
    return 0
  fi
  if ! printf '%s' "$DEVFLOW_RUN_PROFILE" | "$DEVFLOW_JQ" -e 'type == "object"' >/dev/null 2>&1; then
    echo "::warning::efficiency-trace.sh --persist: run-profile floor: DEVFLOW_RUN_PROFILE is not a JSON object; no floor write this run" >&2
    return 0
  fi
  if [ -z "${GITHUB_RUN_ID:-}" ]; then
    echo "::warning::efficiency-trace.sh --persist: run-profile floor: GITHUB_RUN_ID is unset, so this run's record cannot be identified; no floor write" >&2
    return 0
  fi
  local ident="${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT:-1}"
  local issue="${DEVFLOW_ISSUE_NUMBER:-}" prior="unestablished" issue_json="null"
  case "$issue" in
    ''|*[!0-9]*) : ;;
    *) issue_json="$issue"; prior="$(_prior_implement_record_count "$root" "$issue" "$ident")" ;;
  esac
  local prior_json="\"unestablished\""
  case "$prior" in
    ''|*[!0-9]*) : ;;
    *) prior_json="$prior" ;;
  esac
  local run_profile
  if ! run_profile="$(printf '%s' "$DEVFLOW_RUN_PROFILE" | "$DEVFLOW_JQ" -c \
        --argjson prior "$prior_json" \
        --argjson issue "$issue_json" \
        --arg outcome "${DEVFLOW_ENGINE_OUTCOME:-}" \
        '{phase_durations_ms: (.phase_durations_ms // "unestablished"),
          final_status: (.final_status // "unestablished"),
          prior_record_count: $prior,
          issue_number: $issue,
          engine_outcome: (if $outcome == "" then "unestablished" else $outcome end)}' 2>/dev/null)"; then
    echo "::warning::efficiency-trace.sh --persist: run-profile floor: could not assemble the run_profile object (jq failed); no floor write" >&2
    return 0
  fi

  local eff_dir="${stage}/.prflow/logs/efficiency" f
  # Merge arm (a): a record staged this pass under this run-id identity. `*-<ident>.json`
  # matches ANY slug, which is what lets the issue-keyed PR-less record be caught here.
  if [ -d "$eff_dir" ]; then
    for f in "$eff_dir"/*-"$ident".json; do
      [ -e "$f" ] || continue
      _floor_merge_key_staged "$f" run_profile "$run_profile" "staged record $(basename "$f")" "run-profile floor"
      return 0
    done
  fi
  # Merge arm (b): a record already persisted on the telemetry branch for this run-id.
  local ref rel base blob
  ref="$(devflow_telemetry_ref)"
  while IFS= read -r rel; do
    case "$rel" in *-"$ident".json) ;; *) continue ;; esac
    base="$(basename "$rel")"
    blob="$(devflow_telemetry_show_blob "$root" "$ref" "$rel")" || continue
    [ -n "$blob" ] || continue
    if printf '%s' "$blob" | "$DEVFLOW_JQ" -e 'has("run_profile")' >/dev/null 2>&1; then
      echo "devflow: efficiency-trace.sh --persist: run-profile floor: record ${rel} already carries run_profile; leaving it untouched (backstop re-run no-op)" >&2
      return 0
    fi
    mkdir -p "$eff_dir" 2>/dev/null || true
    if printf '%s' "$blob" | "$DEVFLOW_JQ" --argjson rp "$run_profile" '.run_profile = $rp' > "${eff_dir}/${base}" 2>/dev/null; then
      echo "devflow: efficiency-trace.sh --persist: run-profile floor: attached run_profile to already-persisted record ${rel}" >&2
    else
      echo "::warning::efficiency-trace.sh --persist: run-profile floor: could not merge run_profile into ${rel}; no floor write" >&2
      rm -f "${eff_dir}/${base}" 2>/dev/null
    fi
    return 0
  done < <(devflow_telemetry_list_blobs "$root" "$ref" ".prflow/logs/efficiency/")

  # Skeleton arm: no record for this run-id anywhere. Only record-deriving classes get one.
  case "${DEVFLOW_COMMAND_CLASS:-}" in
    review|review-and-fix|implement) ;;
    pr-description)
      echo "::warning::efficiency-trace.sh --persist: run-profile floor: no record by design for command class 'pr-description'; no skeleton written" >&2
      return 0 ;;
    *)
      echo "::warning::efficiency-trace.sh --persist: run-profile floor: command class '${DEVFLOW_COMMAND_CLASS:-<unset>}' does not derive records; no skeleton written" >&2
      return 0 ;;
  esac
  if [ -z "${DEVFLOW_EXECUTION_PR:-}" ]; then
    echo "::warning::efficiency-trace.sh --persist: run-profile floor: no record for run-id ${ident} and DEVFLOW_EXECUTION_PR is empty; skeleton skipped (the PR-less floor owns that case)" >&2
    return 0
  fi
  local slug="pr-${DEVFLOW_EXECUTION_PR}" generated_at skel
  if [ -n "$ref" ] && devflow_telemetry_blob_exists "$root" "$ref" ".prflow/logs/efficiency/${slug}-${ident}.json" 2>/dev/null; then
    echo "::warning::efficiency-trace.sh --persist: run-profile floor: a record already exists on the telemetry branch at .prflow/logs/efficiency/${slug}-${ident}.json; declining to overwrite it with a run-profile skeleton" >&2
    return 0
  fi
  generated_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "$eff_dir" 2>/dev/null || true
  if skel="$("$DEVFLOW_JQ" -n --arg slug "$slug" --arg ga "$generated_at" --argjson rp "$run_profile" \
        '{schema_version: 1, slug: $slug, generated_at: $ga, source: null,
          synthesized: true, iterations: 0, per_iteration: [], telemetry: [],
          run_profile: $rp}' 2>/dev/null)" && printf '%s\n' "$skel" > "${eff_dir}/${slug}-${ident}.json"; then
    echo "devflow: efficiency-trace.sh --persist: run-profile floor: no record for run-id ${ident}; wrote a minimal run-profile skeleton ${slug}-${ident}.json" >&2
  else
    echo "::warning::efficiency-trace.sh --persist: run-profile floor: could not write the run-profile skeleton for ${slug}-${ident}; no floor write" >&2
    rm -f "${eff_dir}/${slug}-${ident}.json" 2>/dev/null
  fi
  return 0
}

# ── PR-less implement record floor (issue #2006) ─────────────────────────────
# An implement run whose PR never resolves produced NO record at all: every other floor
# keys its skeleton `pr-<N>-<run-id>.json` and declines when DEVFLOW_EXECUTION_PR is
# empty, so the run's cost, denials and profile were discarded with only a job-log
# warning that expires. This floor writes the missing host record under the distinct
# slug `issue-<N>`, which no PR-keyed name can collide with, carrying the issue number
# and the fixed-vocabulary reason no PR resolved.
#
# It runs BEFORE the other three floors so their `*-<ident>.json` any-slug merge arms
# then attach harness_cost, permission_denials and run_profile onto this same file with
# no change to any of them. $1 root, $2 staging root.
apply_pr_less_issue_floor() {
  local root="$1" stage="$2"
  # Only the implement class: every other class's candidate number is a PR, so there is
  # no issue to key an issue-slugged record by.
  [ "${DEVFLOW_COMMAND_CLASS:-}" = "implement" ] || return 0
  # A resolved PR means the existing PR-keyed floors own this run; this one is inert.
  [ -z "${DEVFLOW_EXECUTION_PR:-}" ] || return 0
  local issue="${DEVFLOW_ISSUE_NUMBER:-}"
  case "$issue" in
    ''|*[!0-9]*)
      echo "::warning::efficiency-trace.sh --persist: PR-less floor: no PR resolved AND DEVFLOW_ISSUE_NUMBER is '${issue:-<unset>}', so this run cannot be keyed by issue either; no record written" >&2
      return 0 ;;
  esac
  if [ "$ENABLED" != "true" ]; then
    echo "::warning::efficiency-trace.sh --persist: PR-less floor: efficiency telemetry is disabled; no PR-less record written this run" >&2
    return 0
  fi
  if [ -z "${GITHUB_RUN_ID:-}" ]; then
    echo "::warning::efficiency-trace.sh --persist: PR-less floor: GITHUB_RUN_ID is unset, so this run's record cannot be identified; no record written" >&2
    return 0
  fi
  local ident="${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT:-1}" slug="issue-${issue}"
  local eff_dir="${stage}/.prflow/logs/efficiency" ref generated_at rec
  # Do not overwrite a record this pass already staged for this run-id, whatever its slug.
  local f
  if [ -d "$eff_dir" ]; then
    for f in "$eff_dir"/*-"$ident".json; do
      [ -e "$f" ] || continue
      echo "devflow: efficiency-trace.sh --persist: PR-less floor: a record for run-id ${ident} is already staged ($(basename "$f")); leaving it as the host record" >&2
      return 0
    done
  fi
  ref="$(devflow_telemetry_ref)"
  if [ -n "$ref" ] && devflow_telemetry_blob_exists "$root" "$ref" ".prflow/logs/efficiency/${slug}-${ident}.json" 2>/dev/null; then
    echo "devflow: efficiency-trace.sh --persist: PR-less floor: .prflow/logs/efficiency/${slug}-${ident}.json is already on the telemetry branch; declining to overwrite it (backstop re-run no-op)" >&2
    return 0
  fi
  generated_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  mkdir -p "$eff_dir" 2>/dev/null || true
  if rec="$("$DEVFLOW_JQ" -n --arg slug "$slug" --arg ga "$generated_at" \
        --argjson issue "$issue" --arg reason "${DEVFLOW_NO_PR_REASON:-}" \
        '{schema_version: 1, slug: $slug, generated_at: $ga, source: null,
          synthesized: true, iterations: 0, per_iteration: [], telemetry: [],
          issue_number: $issue,
          no_pr_reason: (if $reason == "" then "unestablished" else $reason end)}' 2>/dev/null)" \
     && printf '%s\n' "$rec" > "${eff_dir}/${slug}-${ident}.json"; then
    echo "devflow: efficiency-trace.sh --persist: PR-less floor: no PR resolved for issue ${issue}; wrote ${slug}-${ident}.json so the cost, denial and profile floors have a host record" >&2
  else
    echo "::warning::efficiency-trace.sh --persist: PR-less floor: could not write ${slug}-${ident}.json; this run's record is dropped" >&2
    rm -f "${eff_dir}/${slug}-${ident}.json" 2>/dev/null
  fi
  return 0
}

do_persist() {
  local root dir slug run_id _TELEMETRY_STAGE
  root="$(devflow_repo_root)"
  # Resolve the telemetry branch ONCE, here in the parent, before anything forks. The
  # resolution is memoized in _DEVFLOW_TELEMETRY_BRANCH_CACHE, and a subshell inherits the
  # parent's variables — but NOT a sibling's. Without this seed the first call happened
  # inside a subshell, so every later subshell re-resolved from scratch: the config was
  # re-read once per fork and, on an invalid `telemetry.branch`, its breadcrumb was printed
  # once per fork (three times in a single --persist). Seed it in the parent and they all
  # inherit one resolution, and one warning. Redirect stdout ONLY — stderr must stay open or
  # this seed would swallow the very breadcrumb it exists to emit exactly once.
  devflow_telemetry_branch >/dev/null || true
  # Best-effort, non-forced fetch of the telemetry branch BEFORE recorded_fix_shas
  # computes the fix-commit exclusion set (issue #469 AC6). recorded_fix_shas reads
  # the LOCAL ref, which on an ephemeral CI runner is absent — so without this fetch
  # the exclusion set is silently empty and synthesis can re-attribute a commit an
  # earlier run already recorded (a double-counted record with no signal). Populate
  # the local ref from origin so prior records are visible. The fetch below is into
  # the remote-tracking CACHE (refs/remotes/origin/<branch>, forced/`+` — safe because
  # it is a cache, never local history); the LOCAL ref is then advanced only when it
  # fast-forwards (merge-base --is-ancestor), so a diverged local ref is left untouched
  # rather than clobbered. This is a read (contents:read suffices), so even the
  # read-only review tier runs it.
  # Record the OUTCOME in _DEVFLOW_TELEMETRY_FETCH_STATUS so list_blobs' absent-ref
  # arm can tell an ESTABLISHED empty (fetch ok, ref still absent) from an
  # UNESTABLISHED one (fetch failed/unattempted) — AC7, the "unknown is not zero"
  # rule. dynamic-scope-visible to recorded_fix_shas/list_blobs below; not exported.
  local _DEVFLOW_TELEMETRY_FETCH_STATUS=unattempted _tb_branch _tb_ref _remote_line _rtip _ltip
  _tb_branch="$(devflow_telemetry_branch)"
  _tb_ref="$(devflow_telemetry_ref)"
  if git -C "$root" remote get-url origin >/dev/null 2>&1; then
    # Query the remote READ-ONLY first (ls-remote — no object transfer). Its success
    # is what establishes "the remote was consulted", so the exclusion-set absence is
    # keyed on THAT, not on the branch's presence (AC7): a remote with no such branch
    # yet is an ESTABLISHED 'no records' (a fresh adopter, or any repo before the
    # branch's first use) — we skip the fetch and emit NO warning, ref stays absent.
    # When the branch DOES exist remotely, fetch it into the remote-tracking CACHE
    # (`refs/remotes/origin/<branch>`, force-safe — it is a cache, never local
    # history) and VERIFY it is a DevFlow telemetry store before advancing the LOCAL
    # ref. A consumer's same-named NON-telemetry branch is therefore never clobbered
    # into refs/heads/<branch> (which persist_tree trusts) — that case is left for
    # persist_tree's own rejection-arm re-verification, exactly as before. Only a
    # verified store is fast-forwarded onto the local ref (created when absent; a
    # diverged local ref is never overwritten), making prior records visible to
    # recorded_fix_shas. A FAILED query, a FAILED fetch, OR a fetched tip that cannot
    # be verified as a readable telemetry store is UNESTABLISHED (status=failed → the
    # absent-ref arm of list_blobs warns) — unknown is not zero.
    if _remote_line="$(GIT_TERMINAL_PROMPT=0 git -C "$root" ls-remote --heads origin "$_tb_branch" 2>/dev/null)"; then
      if [ -z "$_remote_line" ]; then
        _DEVFLOW_TELEMETRY_FETCH_STATUS=ok           # established: remote has no such branch yet
      elif GIT_TERMINAL_PROMPT=0 git -C "$root" fetch -q --no-tags origin "+${_tb_branch}:refs/remotes/origin/${_tb_branch}" 2>/dev/null; then
        _rtip="$(git -C "$root" rev-parse --verify --quiet "refs/remotes/origin/${_tb_branch}" 2>/dev/null || true)"
        if [ -n "$_rtip" ] && devflow_telemetry_verify_store "$root" "refs/remotes/origin/${_tb_branch}"; then
          # A readable telemetry store was fetched. Fast-forward the LOCAL ref onto the
          # verified tip (created when absent; a diverged local ref is never overwritten).
          _ltip="$(git -C "$root" rev-parse --verify --quiet "$_tb_ref" 2>/dev/null || true)"
          if [ -z "$_ltip" ] || git -C "$root" merge-base --is-ancestor "$_ltip" "$_rtip" 2>/dev/null; then
            git -C "$root" update-ref "$_tb_ref" "$_rtip" 2>/dev/null || true
          fi
          # recorded_fix_shas reads the LOCAL ref, so the exclusion set is ESTABLISHED only
          # when that ref is now PRESENT — either we just advanced it, or it was already
          # present (a diverged ref left untouched; list_blobs then reads it directly, and the
          # remote-only records it cannot see without clobbering are the deliberate
          # don't-overwrite tradeoff). Assert status AFTER establishing it, never before: a
          # swallowed update-ref failure (`|| true`) that leaves the ref ABSENT must NOT stay
          # ok, or list_blobs' absent-ref arm would launder a verified-but-unfetched store
          # into a silent established-empty and re-attribute an already-recorded commit
          # (#469 review — the same assert-after-establish discipline as the verify-fail arm).
          if git -C "$root" rev-parse --verify --quiet "$_tb_ref" >/dev/null 2>&1; then
            _DEVFLOW_TELEMETRY_FETCH_STATUS=ok
          else
            _DEVFLOW_TELEMETRY_FETCH_STATUS=failed
            echo "::warning::efficiency-trace.sh --persist: fetched a verified telemetry store for '${_tb_branch}' but could not advance the local ref onto it (git update-ref failed — a held ref .lock, a read-only .git, or a full disk) — whether prior records exist is UNESTABLISHED, so the fix-commit exclusion set may be incomplete this run; synthesis could re-attribute an already-recorded commit" >&2
          fi
        else
          # Fetch succeeded but the fetched tip could NOT be verified as a readable
          # telemetry store — an unreadable/corrupt tree, or a consumer's same-named
          # non-telemetry branch. We cannot tell "records exist but are unreadable this
          # run" from "genuinely no telemetry records", so — unknown is not zero (AC7) —
          # leave status UNESTABLISHED (do NOT set ok before verify) so the absent-ref arm
          # of list_blobs warns rather than laundering an unreadable store into a silent
          # established-empty and re-attributing an already-recorded commit.
          _DEVFLOW_TELEMETRY_FETCH_STATUS=failed
          echo "::warning::efficiency-trace.sh --persist: the telemetry branch '${_tb_branch}' exists on origin and was fetched, but its tip could not be verified as a readable DevFlow telemetry store — whether prior records exist is UNESTABLISHED, so the fix-commit exclusion set may be incomplete this run; synthesis could re-attribute an already-recorded commit" >&2
        fi
      else
        _DEVFLOW_TELEMETRY_FETCH_STATUS=failed
        echo "::warning::efficiency-trace.sh --persist: the telemetry branch '${_tb_branch}' exists on origin but fetching it failed (offline or auth) — the fix-commit exclusion set may be incomplete this run; synthesis could re-attribute an already-recorded commit" >&2
      fi
    else
      _DEVFLOW_TELEMETRY_FETCH_STATUS=failed
      echo "::warning::efficiency-trace.sh --persist: could not query origin for telemetry branch '${_tb_branch}' (offline or auth) — whether prior records exist is UNESTABLISHED, so the fix-commit exclusion set may be incomplete this run; synthesis could re-attribute an already-recorded commit" >&2
    fi
  else
    # No origin remote: the LOCAL ref is the authoritative and complete source (there is
    # nowhere else records could live), so its absence is a genuine ESTABLISHED empty, not an
    # unestablished one — mark ok so list_blobs does not emit a misleading "synthesis may
    # re-attribute" warning on a local-only repo's first --persist (#469 review).
    _DEVFLOW_TELEMETRY_FETCH_STATUS=ok
  fi

  # ── Base-ref freshness before the synthesis floor selects commits (issue #532) ──
  # synthesize_iter_workpads selects fix commits with `git log ${base}..HEAD`, where
  # `base` prefers `origin/<base_branch>` (synth_base_ref). Remote-tracking refs are
  # SHARED across linked worktrees, so a stale `origin/<base>` — which nothing on this
  # path refreshed — widens the range back into already-merged foreign history and
  # attributes another PR's fix commits to THIS run (the synthesized-record
  # misattribution #532 documents). This block refreshes `origin/<base>` into the remote-tracking cache
  # BEFORE any fork selects a commit, and records a two-valued status the synthesis
  # guard reads. It borrows the MECHANICAL shape of the telemetry-branch block above
  # (detect-remote → consult read-only → fetch into the cache → assert status AFTER
  # establishing it) but NOT its no-origin reasoning: a base ref has no "authoritative
  # and complete local source" analogue (a local base branch is the only AVAILABLE
  # source, never an authoritative one, and refs/heads/<base> is itself shared across
  # worktrees), so the no-origin arm here is unestablished-but-ACCEPTED on the separate
  # ground that declining there would strip the floor from the offline and fixture runs
  # synth_base_ref documents as supported — a recorded residual, not a closed window.
  #
  # `_DEVFLOW_BASE_BRANCH` is the SINGLE producer of the base branch name (issue #532
  # AC2): resolved ONCE here, consumed by BOTH the ls-remote/fetch below AND
  # synth_base_ref — never re-read via devflow_conf. Seed it (and the status) in the
  # PARENT before anything forks, exactly like _DEVFLOW_TELEMETRY_FETCH_STATUS: a value
  # resolved inside a subshell is re-resolved by every later fork, which would re-fetch
  # and re-breadcrumb per run dir. dynamic-scope-visible to synthesize_iter_workpads /
  # synth_base_ref below; not exported.
  local _DEVFLOW_BASE_REF_STATUS=unestablished _DEVFLOW_BASE_BRANCH _base_remote_line
  _DEVFLOW_BASE_BRANCH="$(devflow_conf '.base_branch' 'main')"
  [ -n "$_DEVFLOW_BASE_BRANCH" ] || _DEVFLOW_BASE_BRANCH="main"
  if git -C "$root" remote get-url origin >/dev/null 2>&1; then
    # Query the remote READ-ONLY first (ls-remote — no object transfer), exactly as the
    # telemetry block does. A SUCCEEDING ls-remote with EMPTY output is a positive answer
    # — the remote genuinely carries no such branch (a fresh adopter before its first
    # push, or a base deleted/renamed on origin) — so there is nothing to be stale
    # against: ESTABLISHED, synth_base_ref falls back to the local base exactly as today,
    # and a breadcrumb records it (issue #532). A SUCCEEDING ls-remote with output means
    # the branch exists: refresh it into the remote-tracking CACHE
    # (refs/remotes/origin/<base>, force-safe `+` refspec — a cache, never local history)
    # and NO local ref is advanced (the base ref has no local counterpart to fast-forward,
    # unlike the telemetry block). A fetch success is ESTABLISHED. A FAILED ls-remote query
    # OR a FAILED fetch is UNESTABLISHED — the remote-tracking ref may be arbitrarily
    # stale, which is the state this issue exists to stop trusting. This arm deliberately
    # does NOT distinguish a stale ref from a transient failure (offline, a VPN reconnect,
    # an expired credential, a contended refs/remotes/origin/<base>.lock from a sibling
    # worktree's concurrent --persist): none is distinguishable from the failure alone, and
    # the safe direction for a defect whose entire signature is a plausible-looking WRONG
    # record is to write nothing. --persist fires from the Stop hook on every stop, so a
    # transient failure's next re-attempt is seconds away; both are recorded residuals.
    if _base_remote_line="$(GIT_TERMINAL_PROMPT=0 git -C "$root" ls-remote --heads origin "$_DEVFLOW_BASE_BRANCH" 2>/dev/null)"; then
      if [ -z "$_base_remote_line" ]; then
        # The remote AUTHORITATIVELY carries no such branch, so any lingering
        # refs/remotes/origin/<base> is a stale cache from a prior fetch (the base was
        # deleted or renamed on origin). Prune it so synth_base_ref's `origin/<base>`
        # iteration does NOT resolve to that stale tip and re-widen the range —
        # synth_base_ref tries `origin/<base>` BEFORE the local base, so an un-pruned
        # stale cache would be selected over the local base and sweep already-merged
        # history (the exact #532 corruption). The prune is best-effort at the command
        # level, but its OUTCOME is verified and the status is FAIL-CLOSED on it: if the
        # ref still resolves after the delete attempt (a contended
        # refs/remotes/origin/<base>.lock from a sibling worktree, a read-only .git), the
        # stale cache survives and would be selected, so DECLINE (unestablished) rather
        # than proceed against it — never mark `established` on an unverified prune, and
        # never emit the "accepted the local base" breadcrumb the prune did not earn. A
        # no-op prune when no such cache ref exists (the fresh-adopter case) leaves the
        # ref absent, so the else arm marks established and proceeds — exactly R13.
        git -C "$root" update-ref -d "refs/remotes/origin/${_DEVFLOW_BASE_BRANCH}" 2>/dev/null || true
        if git -C "$root" rev-parse --verify --quiet "refs/remotes/origin/${_DEVFLOW_BASE_BRANCH}" >/dev/null 2>&1; then
          _DEVFLOW_BASE_REF_STATUS=unestablished       # prune FAILED and the stale cache survives — decline, do not select it
          echo "::warning::efficiency-trace.sh --persist: origin carries no branch '${_DEVFLOW_BASE_BRANCH}' but a stale refs/remotes/origin/${_DEVFLOW_BASE_BRANCH} cache could not be pruned (a contended ref lock or a read-only .git) — the base ref is UNESTABLISHED, so commit selection is skipped this run to avoid selecting that stale cache" >&2
        else
          _DEVFLOW_BASE_REF_STATUS=established         # established: remote carries no such branch and no stale cache remains — local base accepted
          echo "efficiency-trace.sh --persist: base-ref refresh skipped — origin carries no branch '${_DEVFLOW_BASE_BRANCH}' (fresh adopter, or a deleted/renamed base); pruned any stale remote-tracking cache and accepted the local base '${_DEVFLOW_BASE_BRANCH}' without a refresh" >&2
        fi
      elif GIT_TERMINAL_PROMPT=0 git -C "$root" fetch -q --no-tags origin "+${_DEVFLOW_BASE_BRANCH}:refs/remotes/origin/${_DEVFLOW_BASE_BRANCH}" 2>/dev/null; then
        _DEVFLOW_BASE_REF_STATUS=established           # established: refreshed origin/<base> into the remote-tracking cache
      else
        _DEVFLOW_BASE_REF_STATUS=unestablished
        echo "::warning::efficiency-trace.sh --persist: could not refresh 'origin/${_DEVFLOW_BASE_BRANCH}' into refs/remotes/origin/${_DEVFLOW_BASE_BRANCH} (offline, auth, or a contended refs/remotes/origin/${_DEVFLOW_BASE_BRANCH} lock) — the base ref is UNESTABLISHED, so commit selection is skipped this run to avoid attributing another PR's fix commits to it" >&2
      fi
    else
      _DEVFLOW_BASE_REF_STATUS=unestablished
      echo "::warning::efficiency-trace.sh --persist: could not query origin for base branch '${_DEVFLOW_BASE_BRANCH}' (offline or auth) — the base ref is UNESTABLISHED, so commit selection is skipped this run to avoid attributing another PR's fix commits to it" >&2
    fi
  else
    # No origin remote: no refresh mechanism exists at all, so — unlike the failed-refresh
    # arm — synthesis PROCEEDS (declining here would break every no-origin et-synth fixture
    # and strip the floor from the offline/fixture runs synth_base_ref supports). The status
    # value is `established` because it is the CONTROL value the two-valued guard reads, not
    # an epistemic claim that the local base is trustworthy: refs/heads/<base> is shared
    # across linked worktrees and can be stale. That gap is a documented residual window,
    # recorded here rather than silently closed.
    _DEVFLOW_BASE_REF_STATUS=established
    echo "efficiency-trace.sh --persist: base-ref refresh skipped — no origin remote configured; accepted the local base '${_DEVFLOW_BASE_BRANCH}' without a refresh (recorded residual: the local base may be stale across linked worktrees)" >&2
  fi
  # Bounded cleanup policy for retained staging roots (issue #469 AC8): a degraded
  # or staging-only persist RETAINS its staging root under .prflow/tmp/ (below), so
  # prune older ones to the newest _DEVFLOW_TELEMETRY_STAGE_KEEP (default 8) here,
  # before creating this run's, so they cannot grow without bound. The timestamp
  # prefix on the name below makes the glob sort chronologically (lexicographic ==
  # oldest-first), so dropping the leading entries drops the oldest. Best-effort;
  # a prune failure never aborts (the whole helper is exit-0/best-effort).
  local _keep="${_DEVFLOW_TELEMETRY_STAGE_KEEP:-8}" _stale=() _s
  # A non-numeric override (e.g. `abc`) would make the `-gt` test below error and the
  # prune go INERT, so retained roots would accumulate unbounded — the opposite of the
  # bound's purpose. Fall back to the default on any non-numeric value so the bound holds.
  case "$_keep" in ''|*[!0-9]*) _keep=8 ;; esac
  # Normalize to base-10 AFTER the all-digit check above (#469 review): an all-digit but
  # leading-zero value (`08`, `09`) passes that check yet is an INVALID OCTAL literal, so the
  # later `$(( ${#_stale[@]} - _keep ))` arithmetic aborts with "value too great for base" —
  # and under this file's `set -euo pipefail` that abort would kill do_persist mid-run and
  # lose the run's telemetry (the exact fail-open the bound exists to prevent). `10#` forces
  # base-10 (safe: the case above guaranteed `$_keep` is all-digits, so `10#` never sees a
  # non-digit). But all-digit does NOT imply within intmax: a value >= 2^63 silently WRAPS
  # (bash integer overflow does not error) to a negative, which would make `_drop` exceed the
  # staged-array length and index past it under `set -u` (aborting the best-effort prune — the
  # same fail-open again). Clamp a negative (overflowed) result back to the default so `_keep`
  # is always non-negative and `_drop = count - _keep <= count` keeps the loop in bounds. A
  # large-but-in-range `_keep` needs no clamp: it just makes `_drop` non-positive → prune nothing.
  _keep=$(( 10#$_keep ))
  [ "$_keep" -ge 0 ] || _keep=8
  for _s in "${root}"/.prflow/tmp/telemetry-stage-*; do
    [ -d "$_s" ] && _stale+=("$_s")
  done
  if [ "${#_stale[@]}" -gt "$_keep" ]; then
    local _drop=$(( ${#_stale[@]} - _keep )) _i
    for ((_i = 0; _i < _drop; _i++)); do rm -rf "${_stale[$_i]}" 2>/dev/null || true; done
  fi
  # Shared staging root under gitignored .prflow/tmp/ (issue #441). Every
  # persist_one call stages its record + durable workpad copy here, mirroring the
  # exact .prflow/logs/… layout; after the loop the detached telemetry-branch
  # write consumes the whole tree and this scratch is removed. Nothing is ever
  # materialized in the tracked working tree, so `git status` stays byte-for-byte
  # unchanged (AC2). Unique name via bash builtins (not mktemp — the cloud sandbox
  # blocks it, AC9).
  # UTC-timestamp prefix so retained roots glob-sort chronologically for the prune
  # above (#469 AC8). `date` is not a preflight-guaranteed tool and this name only
  # orders CLEANUP (never selects an emitted telemetry value — guard-class 2 does
  # not bind), so a missing `date` degrades to a fixed prefix (prune still runs,
  # ordering just falls back to $$/RANDOM); $$-RANDOM-SECONDS keep the name unique.
  _TELEMETRY_STAGE="${root}/.prflow/tmp/telemetry-stage-$(date -u +%Y%m%d%H%M%S 2>/dev/null || printf '00000000000000')-$$-${RANDOM}-${SECONDS}"
  rm -rf "$_TELEMETRY_STAGE" 2>/dev/null || true
  mkdir -p "$_TELEMETRY_STAGE" 2>/dev/null || true
  if [ -n "$WORKPAD_DIR" ]; then
    # Targeted: persist exactly the given run. Slug from --slug, else the parent
    # dir name; run-id is the workpad-dir basename. Derived with bash parameter
    # expansion only — these values DECIDE which run identity receives the
    # record, so they must not depend on PATH tools at all (guard-class 2): a
    # broken/shadowed `basename` on PATH would abort the persist mid-run under
    # set -e (rc 127 — violating the best-effort exit-0 contract and losing the
    # record), and builtins remove that dependency outright. (The script's init
    # line still uses `dirname` to locate itself; a host that broken never gets
    # this far.)
    dir="${WORKPAD_DIR%/}"
    while [ "${dir%/}" != "$dir" ]; do dir="${dir%/}"; done   # collapse any extra trailing slashes
    run_id="${dir##*/}"
    if [ -n "$SLUG" ]; then
      slug="$SLUG"
    else
      slug="${dir%/*}"; slug="${slug##*/}"
    fi
    persist_one "$WORKPAD_DIR" "$slug" "$run_id" "$root" 1
  else
    # Discovery: every .prflow/tmp/review/<slug>/<run-id>/ directory. The trailing
    # slash restricts the glob to directories; an unmatched glob stays literal and
    # the `[ -d ]` guard skips it (no nullglob needed). A dir HOLDING iter-*.json
    # is persisted immediately. A WORKPAD-LESS dir is collected so the issue #381
    # synthesis floor synthesizes into only the lexicographically-latest
    # workpad-less run-id per slug: the glob is sorted, so same-slug dirs are
    # contiguous with run-ids ascending — the LAST workpad-less dir of a slug is
    # its latest, and every earlier one gets allow_synth=0 (breadcrumb). This
    # ordering guard is one of the double-count defenses; the sha-level exclusion
    # inside synthesis (see persist_one) covers the shapes ordering cannot — a
    # workpad-holding sibling run and later passes — and the multi-slug ambiguity
    # guard below covers the shape NEITHER can: workpad-less dirs spanning
    # multiple slugs, where whichever slug sorts first would otherwise claim the
    # current branch's fix commits even when it is a stale leftover from an
    # aborted run of a DIFFERENT branch/PR (misattribution, which the sha
    # exclusion would then lock in). Slug ownership is not derivable offline
    # (a pr-<N> slug cannot be mapped to the checkout without the API), so the
    # ambiguous case fails closed for every candidate, each with a breadcrumb
    # naming the targeted --workpad-dir escape hatch. Known residual for the
    # MISATTRIBUTION direction: a SINGLE stale foreign slug's workpad-less dir,
    # when the current run left no tmp dir at all, is the sole candidate and
    # still claims the branch's fix commits under the wrong slug — guard (c)
    # trips only on multiple slugs, because a lone candidate is
    # indistinguishable offline from the legitimate current run. A sibling
    # residual within one slug: a workpad-less dir sorting EARLIER than a
    # workpad-holding one is that slug's only synthesis candidate, so a stale
    # earlier run-id can receive the record (right slug, wrong run-id; the sha
    # exclusion still prevents any double-count). And a workpad-less dir left by
    # a standalone /devflow:review run is indistinguishable here from a dropped
    # fix loop's — its synthesized record defaults to source "review-and-fix"
    # (a synthesized workpad carries no `source` field, so the probe's else-arm
    # default fires, not the unreadable-file breadcrumb) even though the run
    # that created the dir was a review; content stays correct and the sha
    # exclusion still holds.
    local wl_dirs=() wl_n wl_i next_slug allow d_iters wl_slug_first wl_multi_slug=0
    for dir in "$root"/.prflow/tmp/review/*/*/; do
      [ -d "$dir" ] || continue
      dir="${dir%/}"                                # strip trailing slash
      run_id="${dir##*/}"                           # builtins only (guard-class 2:
      slug="${dir%/*}"; slug="${slug##*/}"          # identity-deciding, no PATH tools)
      d_iters=("$dir"/iter-*.json)
      if [ -e "${d_iters[0]}" ]; then
        persist_one "$dir" "$slug" "$run_id" "$root" 1
      else
        wl_dirs+=("$dir")
      fi
    done
    wl_n=${#wl_dirs[@]}
    wl_slug_first=""
    for ((wl_i = 0; wl_i < wl_n; wl_i++)); do
      slug="${wl_dirs[$wl_i]%/*}"; slug="${slug##*/}"   # builtins only — this
      # comparison DECIDES the multi-slug ambiguity trip, so it must not depend
      # on a PATH tool whose failure would abort or degrade it (guard-class 2).
      if [ -z "$wl_slug_first" ]; then
        wl_slug_first="$slug"
      elif [ "$slug" != "$wl_slug_first" ]; then
        wl_multi_slug=1
      fi
    done
    for ((wl_i = 0; wl_i < wl_n; wl_i++)); do
      dir="${wl_dirs[$wl_i]}"
      run_id="${dir##*/}"
      slug="${dir%/*}"; slug="${slug##*/}"
      if [ "$wl_multi_slug" = "1" ]; then
        allow=2
      else
        next_slug=""
        if [ $((wl_i + 1)) -lt "$wl_n" ]; then
          next_slug="${wl_dirs[$((wl_i + 1))]%/*}"; next_slug="${next_slug##*/}"
        fi
        if [ "$slug" = "$next_slug" ]; then allow=0; else allow=1; fi
      fi
      persist_one "$dir" "$slug" "$run_id" "$root" "$allow"
    done
  fi

  # ── Harness-side cost floor (issue #475): merge the execution file's cost into
  # this run's staged record (or write a minimal cost skeleton) BEFORE the branch
  # write consumes the staging tree. Inert + silent when DEVFLOW_EXECUTION_COST is
  # unset, so the agent-side persist call sites (Loop-Exit, Stop-hook) are byte-
  # identical to before. Best-effort; runs after every run dir has been staged so
  # its run-id targeting sees this pass's staged record if one was derived. ────────
  # ── PR-less implement record floor (issue #2006): an implement run whose PR never
  # resolved has no host record for the three floors below to merge onto, so they each
  # decline and the run's whole measurement is discarded. Write the issue-keyed host
  # record FIRST; the floors' `*-<ident>.json` any-slug merge arms then find it. Inert on
  # every other class and whenever a PR did resolve. ─────────────────────────────────
  apply_pr_less_issue_floor "$root" "$_TELEMETRY_STAGE"

  apply_harness_floor "$root" "$_TELEMETRY_STAGE"

  # ── Permission-denial forensics floor (issue #1064 D2): merge the assembled denial
  # record (scripts/build-denial-record.sh, handed in via DEVFLOW_DENIAL_RECORD) into
  # this run's staged/persisted record as a distinct top-level `permission_denials`
  # key. Inert + silent when DEVFLOW_DENIAL_RECORD is unset, so the agent-side persist
  # call sites are byte-identical to before. Runs after apply_harness_floor so a record
  # this pass derived (or the branch's already-persisted one) is in place to merge onto.
  apply_denial_floor "$root" "$_TELEMETRY_STAGE"

  # ── Run-profile floor (issue #2006): merge this run's phase durations, workpad final
  # status, prior-record count and engine step outcome as a top-level `run_profile` key.
  # Runs after the floors above so the host record they may have written is in place.
  apply_run_profile_floor "$root" "$_TELEMETRY_STAGE"

  # ── Detached write of everything staged above to the telemetry branch ──────
  # (issue #441). Replaces the former current-branch `chore:` commit: the shared
  # lib hashes each staged .prflow/logs/… file into the object store, builds a
  # tree parented on the telemetry ref (orphan root on first use), CAS-advances
  # the ref, and pushes with a fetch/re-parent retry loop — never touching the
  # current branch, HEAD, or the working tree. Best-effort/exit-0: a push that
  # can't happen (offline, read-only token/profile, no remote) still advances the
  # local ref and breadcrumbs. Then remove the staging scratch so `git status`
  # stays byte-for-byte unchanged (AC2). devflow_telemetry_persist_tree is a
  # clean no-op when nothing was staged.
  # Gate on the REAL source sentinel telemetry-branch.sh sets on a successful
  # source (_DEVFLOW_TELEMETRY_BRANCH_SOURCED) — NOT `command -v`, which always finds
  # the no-op stubs the source-failure branch defines, making this persist-time
  # "artifacts discarded" warning unreachable dead code. With the sentinel, a
  # vendored deploy missing lib/ takes the else and emits a specific persist-time
  # breadcrumb naming the discarded staging root, instead of silently no-op'ing.
  # Capture the write's outcome (issue #469 AC8). devflow_telemetry_persist_tree
  # now REPORTS via its return code — 0 = clean (pushed / idempotent no-op / nothing
  # staged / no staging root); 1 = a DEGRADED arm that produced a staging root
  # (worktree-checked-out branch, non-conforming store, unwritable temp index, CAS
  # exhausted, or a push/re-parent failure); 2 = STAGING-ONLY (CI without an
  # affirmative DEVFLOW_TELEMETRY_PUSH — AC5). It still NEVER aborts its caller, so
  # `|| persist_rc=$?` keeps this best-effort under set -e and --persist still exits 0.
  local persist_rc=0
  if [ -n "${_DEVFLOW_TELEMETRY_BRANCH_SOURCED:-}" ]; then
    devflow_telemetry_persist_tree "$root" "$_TELEMETRY_STAGE" || persist_rc=$?
  else
    echo "::warning::efficiency-trace.sh --persist: telemetry-branch.sh was not sourced; cannot persist to the telemetry branch this run — the run's staged artifacts under ${_TELEMETRY_STAGE} are discarded" >&2
  fi
  case "$persist_rc" in
    0) rm -rf "$_TELEMETRY_STAGE" 2>/dev/null || true ;;   # clean (pushed / no-op / nothing staged): delete is gated to rc 0 ONLY so `git status`, HEAD, and the current branch stay byte-for-byte unchanged (#469 AC13, #441 AC2), and no non-clean result can reach it (#469 AC8, fail-closed)
    2)
      # Staging-only (AC5): the operand breadcrumb already fired in telemetry-branch.sh.
      # RETAIN the staged tree (the trusted telemetry-push relay — telemetry-push.yml, issue
      # #489 — uploads+pushes it); do not delete and do not emit a second warning — the
      # intended read-only-review posture, not a degradation.
      : ;;
    *)
      # Degraded (rc 1) OR any other non-clean/unexpected result — including a subshell
      # killed by a signal (128+n via the `|| _persist_subrc=$?` capture in
      # telemetry-branch.sh): the staged records are the run's ONLY copy (nothing is ever
      # written to the tracked tree), so RETAINING them is what makes the failure
      # recoverable instead of a silent deletion (#469 AC8 — this arm fails CLOSED toward
      # retention for every value that is not an explicit clean 0). One ::warning:: names
      # the absolute path; bounded by the newest-N prune at the top of do_persist, so
      # retained roots cannot accumulate without limit. On an ephemeral CI runner the
      # filesystem does not survive teardown, so on-disk retention is moot there — the
      # trusted telemetry-push relay (telemetry-push.yml, issue #489) is the cloud recovery
      # path, pushing the uploaded workflow artifact rather than any on-disk copy (see docs).
      echo "::warning::efficiency-trace.sh --persist: the telemetry-branch write DEGRADED — RETAINING the staged records at '${_TELEMETRY_STAGE}' so they are recoverable (delete once recovered; a bounded newest-${_keep} prune runs each --persist). On an ephemeral CI runner the filesystem does not survive teardown, so recovery there is not on-disk — the trusted telemetry-push relay (telemetry-push.yml, issue #489) pushes the staged records from the uploaded workflow artifact." >&2 ;;
  esac
  return 0
}

# ── Dispatch ─────────────────────────────────────────────────────────────────
case "$ACTION" in
  self-check) do_self_check; exit 0 ;;
  persist)    do_persist;    exit 0 ;;
esac

# Default action: --mode trace|record (unchanged contract).
if [ "$MODE" != "trace" ] && [ "$MODE" != "record" ]; then
  echo "efficiency-trace.sh: --mode must be 'trace' or 'record' (or pass --persist / --self-check)" >&2
  exit 2
fi

# Flag off → emit nothing, exit 0 (so a caller writing the record to a file
# produces no file under .prflow/logs/).
if [ "$ENABLED" != "true" ]; then
  exit 0
fi

collect_valid_files "$WORKPAD_DIR"
warn_on_mixed_source
emit_jq "$MODE" "$SLUG"
