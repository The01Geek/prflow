#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# retro-helper.sh <subcommand> — fixed-file CLI dispatcher wrapping the 13 cloud-used
# retrospective helper functions (issue #101).
#
# Invoked as a bare granted path with a fixed LITERAL subcommand token; it reads inputs
# from fixed .prflow/** files (mostly .prflow/tmp/**, plus .prflow/learnings/overrides.json
# for the open-filed counts), calls the owning library function with all shell work done
# internally, writes the function's stdout bytes to a fixed output file (except
# audit-dispatch-ok, a pure predicate whose caller reads only the exit status), and
# propagates the function's exact exit status.
#
# The owning library is sourced by dirname resolution and the target function is
# `declare -F`-verified before dispatch (fail-closed). source_lib restores `set +e`
# after sourcing (render-report.sh and, transitively, telemetry-branch.sh set
# `set -euo pipefail`), so the function's stdout is redirected STRAIGHT to the fixed
# output file — `fn … > "$OUT"; rc=$?` — preserving its exact bytes (trailing newline
# included) and capturing its rc. A command-substitution capture (`out="$(fn)"`) would
# strip the trailing newline, breaking output-file byte-identity with the function.
#
# The base directory anchoring the fixed .prflow/** paths defaults to the CWD (the working
# tree — NOT the script's own location, which on the vendored cloud invocation differs from
# it); DEVFLOW_RETRO_HELPER_ROOT overrides it (test isolation only — the cloud call sets
# nothing, so the paths are fixed).

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# DEVFLOW_RETRO_HELPER_LIB_DIR overrides the library directory for test isolation only
# (so a test can point the dispatcher at a stub library to exercise the fail-closed arms).
LIB_DIR="${DEVFLOW_RETRO_HELPER_LIB_DIR:-$HERE/../lib}"
# Anchor the fixed .prflow/** DATA paths to the CWD (the working tree), matching the skill's
# CWD-relative fences and pass-through file args: a $HERE/.. anchor points at the vendored
# subtree on the cloud invocation and would read/write a different .prflow/tmp than the skill.
BASE="${DEVFLOW_RETRO_HELPER_ROOT:-$(pwd)}"

# jq for the wrapper's own object-field extraction (best-effort resolver; the sourced
# libraries resolve it again for their own use).
# shellcheck source=../lib/resolve-jq.sh
. "$LIB_DIR/resolve-jq.sh" \
  || { echo "::warning::retro-helper: resolve-jq.sh could not be sourced — using bare 'jq'" >&2; : "${DEVFLOW_JQ:=jq}"; }

TMP_DIR="$BASE/.prflow/tmp"
SCRATCH="$TMP_DIR/retro-helper"
# SCRATCH is a child of TMP_DIR, so this one mkdir -p creates both.
mkdir -p "$SCRATCH" 2>/dev/null || true

SUB="${1:-}"

die2() {  # a wiring fault (missing/unparseable input) — exit 2, distinct from the
          # underlying function's data-condition exits. Empty a stale $OUT first so a
          # caller that does not gate on the exit never reads a prior call's output.
  [ -n "${OUT:-}" ] && : > "$OUT" 2>/dev/null || true
  echo "::error::retro-helper: $1" >&2
  exit 2
}

require_file() {  # $1 = path, $2 = human label
  [ -f "$1" ] || die2 "the ${2} input file '$1' is missing — this is a wiring fault (exit 2), not a data condition"
}

read_file() {  # print a file's contents via a bash builtin redirection (no PATH tool)
  printf '%s' "$(<"$1")"
}

jqf() {  # extract one $_obj field, defaulting to "" (require_json_obj proved $_obj is a
         # JSON object first, so `// ""` means only "field absent", never "whole object corrupt").
  "$DEVFLOW_JQ" -r ".$1 // \"\"" <<<"$_obj" 2>/dev/null || echo ""
}

require_json_obj() {  # $1 = label; gate on object-ness, not mere parseability — a valid
                      # non-object ([]/5/0) parses yet collapses every jqf to "" (a silent
                      # fail-open), so treat it as a wiring fault (exit 2), not a data condition.
  printf '%s' "$_obj" | "$DEVFLOW_JQ" -e 'type=="object"' >/dev/null 2>&1 \
    || die2 "the ${1} input is not a JSON object — a wiring fault (exit 2), not a data condition"
}

source_lib() {  # $1 = lib path, $2 = function name; fail-closed if not defined
  # shellcheck disable=SC1090
  . "$1" || { echo "::error::retro-helper: could not source $1" >&2; exit 1; }
  set +e
  declare -F "$2" >/dev/null 2>&1 \
    || { echo "::error::retro-helper: $2 is undefined after sourcing $1" >&2; exit 1; }
}

case "$SUB" in
  filing-cap-verdict)
    IN="$SCRATCH/cap-verdict-in.json"
    OUT="$SCRATCH/cap-verdict-out.txt"
    require_file "$IN" "cap-verdict object"
    _obj="$(read_file "$IN")"
    require_json_obj "cap-verdict object"
    _status="$(jqf status)"
    _filed="$(jqf filed_this_run)"
    _mpr="$(jqf max_per_run)"
    _pcc="$(jqf per_cat_count)"
    _mpc="$(jqf max_per_cat)"
    _ot="$(jqf open_total)"
    _mo="$(jqf max_open)"
    source_lib "$LIB_DIR/filing-decisions.sh" devflow_filing_cap_verdict
    devflow_filing_cap_verdict "$_status" "$_filed" "$_mpr" "$_pcc" "$_mpc" "$_ot" "$_mo" > "$OUT"; rc=$?
    exit "$rc" ;;

  liveness-warning)
    IN="$TMP_DIR/patterns.stderr"
    OUT="$SCRATCH/liveness-out.txt"
    require_file "$IN" "liveness capture"
    source_lib "$LIB_DIR/filing-decisions.sh" devflow_liveness_warning
    devflow_liveness_warning "$IN" > "$OUT"; rc=$?
    exit "$rc" ;;

  declined-refiled)
    OV="$TMP_DIR/overrides-prefiling.json"
    FILED="$SCRATCH/declined-refiled-filed.json"
    OUT="$SCRATCH/declined-refiled-out.json"
    require_file "$OV" "overrides-prefiling"
    require_file "$FILED" "declined-refiled filed-slugs"
    _filed_json="$(read_file "$FILED")"
    source_lib "$LIB_DIR/filing-decisions.sh" devflow_declined_refiled
    devflow_declined_refiled "$OV" "$_filed_json" > "$OUT"; rc=$?
    exit "$rc" ;;

  annotate-patterns)
    PF="$TMP_DIR/patterns-full.json"
    FILED="$SCRATCH/annotate-filed.json"
    WITHHELD="$SCRATCH/annotate-withheld.json"
    OUT="$SCRATCH/annotate-out.json"
    require_file "$PF" "patterns-full"
    require_file "$FILED" "annotate filed"
    require_file "$WITHHELD" "annotate withheld"
    _filed_json="$(read_file "$FILED")"
    _withheld_json="$(read_file "$WITHHELD")"
    source_lib "$LIB_DIR/filing-decisions.sh" devflow_annotate_patterns
    # On failure the function prints nothing; the redirect truncates the output to empty
    # so the caller's `${VAR:?}` empty-string guard fires (contract).
    devflow_annotate_patterns "$PF" "$_filed_json" "$_withheld_json" > "$OUT"; rc=$?
    exit "$rc" ;;

  open-filed-total)
    OV="$BASE/.prflow/learnings/overrides.json"
    OUT="$SCRATCH/open-filed-total-out.txt"
    require_file "$OV" "learnings overrides"
    source_lib "$LIB_DIR/filing-decisions.sh" devflow_open_filed_total
    # EMPTY output (never `0`) when the function prints nothing — the redirect preserves
    # the caller's emptiness contract.
    devflow_open_filed_total "$OV" > "$OUT"; rc=$?
    exit "$rc" ;;

  open-filed-for-category)
    OV="$BASE/.prflow/learnings/overrides.json"
    CAT="$SCRATCH/category-in.txt"
    OUT="$SCRATCH/open-filed-for-category-out.txt"
    require_file "$OV" "learnings overrides"
    require_file "$CAT" "category"
    _category="$(read_file "$CAT")"
    source_lib "$LIB_DIR/filing-decisions.sh" devflow_open_filed_for_category
    devflow_open_filed_for_category "$OV" "$_category" > "$OUT"; rc=$?
    exit "$rc" ;;

  projection-eligible-findings)
    IN="$SCRATCH/projection-in.json"
    DROPPED="$SCRATCH/projection-dropped.json"
    OUT="$SCRATCH/projection-out.json"
    require_file "$IN" "projection findings"
    source_lib "$LIB_DIR/select-findings.sh" devflow_projection_eligible_findings
    devflow_projection_eligible_findings "$IN" "$DROPPED" > "$OUT"; rc=$?
    exit "$rc" ;;

  select-findings)
    IN="$SCRATCH/select-findings-in.json"
    OUT="$SCRATCH/select-findings-out.json"
    require_file "$IN" "select-findings object"
    _obj="$(read_file "$IN")"
    require_json_obj "select-findings object"
    _category="$(jqf category)"
    _findings="$(jqf findings_file)"
    _overrides="$(jqf overrides)"
    _status="$(jqf status)"
    _filed="$(jqf filed_this_run)"
    _mpr="$(jqf max_per_run)"
    _mpc="$(jqf max_per_cat)"
    _mo="$(jqf max_open)"
    _withheld="$(jqf withheld_file)"
    _dropped="$(jqf dropped_file)"
    source_lib "$LIB_DIR/select-findings.sh" devflow_select_findings
    devflow_select_findings \
        --category "$_category" --findings-file "$_findings" --overrides "$_overrides" \
        --status "$_status" --filed-this-run "$_filed" --max-per-run "$_mpr" \
        --max-per-cat "$_mpc" --max-open "$_mo" \
        --withheld-file "$_withheld" --dropped-file "$_dropped" > "$OUT"; rc=$?
    exit "$rc" ;;

  render-report)
    IN="$SCRATCH/render-report-in.json"
    OUT="$TMP_DIR/report.md"
    require_file "$IN" "render-report summary"
    _summary="$(read_file "$IN")"
    source_lib "$LIB_DIR/render-report.sh" devflow_render_report
    devflow_render_report "$_summary" > "$OUT"; rc=$?
    exit "$rc" ;;

  validate-audit-bundle-cap)
    IN="$SCRATCH/audit-cap-in.txt"
    OUT="$SCRATCH/audit-cap-out.txt"
    require_file "$IN" "audit cap"
    _cap="$(read_file "$IN")"
    source_lib "$LIB_DIR/audit-bundle-selection.sh" devflow_validate_audit_bundle_cap
    devflow_validate_audit_bundle_cap "$_cap" > "$OUT"; rc=$?
    exit "$rc" ;;

  select-audit-bundles)
    CAPF="$SCRATCH/audit-cap-out.txt"
    PATF="$SCRATCH/pattern-in.json"
    OUT="$SCRATCH/select-audit-bundles-out.txt"
    require_file "$CAPF" "validated cap"
    require_file "$PATF" "enriched pattern"
    _cap="$(read_file "$CAPF")"
    _pattern="$(read_file "$PATF")"
    source_lib "$LIB_DIR/audit-bundle-selection.sh" devflow_select_audit_bundles
    # Empty output is legitimate; on failure the function prints nothing — the redirect
    # writes the (empty) bytes either way, so empty-vs-failure stays exit-status discriminated.
    devflow_select_audit_bundles "$_cap" "$_pattern" > "$OUT"; rc=$?
    exit "$rc" ;;

  audit-dispatch-ok)
    IN="$SCRATCH/audit-dispatch-in.txt"
    require_file "$IN" "delivered count"
    _delivered="$(read_file "$IN")"
    source_lib "$LIB_DIR/audit-bundle-selection.sh" devflow_audit_dispatch_ok
    # Pure predicate — no output file; the caller reads the exit status.
    devflow_audit_dispatch_ok "$_delivered"; rc=$?
    exit "$rc" ;;

  telemetry-branch)
    OUT="$SCRATCH/telemetry-branch-out.txt"
    source_lib "$LIB_DIR/telemetry-branch.sh" devflow_telemetry_branch
    devflow_telemetry_branch > "$OUT"; rc=$?
    exit "$rc" ;;

  "")
    echo "::error::retro-helper: no subcommand given" >&2
    exit 2 ;;
  *)
    echo "::error::retro-helper: unknown subcommand '$SUB'" >&2
    exit 2 ;;
esac
