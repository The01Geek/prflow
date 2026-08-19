# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# shellcheck shell=bash
# Sourceable terminal-result-class contract module (issue #1273).
# Contract: the caller sets LIB and RESULTS_FILE, defines assert_eq, and sources
# lib/test/module-harness.sh before this module.
#
# What it proves. scripts/terminal-result-class.sh (bash) and
# lib/terminal-result-table.tsv (generated from lib/generate-terminal-result-table.py's
# independent Python oracle) are two implementations of the same closed terminal-outcome
# spec. This module asserts the bash classifier's live output equals EVERY row of the
# generated table — over the full input cross-product — so a divergence between the two
# turns RED (the table-drift leg), and it re-derives the totality row counts so a shrunk
# vocabulary is a missing row rather than a silent gap. The hand-oracle block below is the
# non-circular behavioral pin for each in-scope acceptance criterion: its expected values
# are written here by hand, not derived from either implementation.
REPO_ROOT="$LIB/.."
TRC_HELPER="$REPO_ROOT/scripts/terminal-result-class.sh"
TRC_TABLE="$REPO_ROOT/lib/terminal-result-table.tsv"

# ────────────────────────────────────────────────────────────────────────────
echo "#1273 terminal-result classifier — generated total table (drift + totality)"
# ────────────────────────────────────────────────────────────────────────────
# Drive the bash classifier over every generated row and assert its class + the
# conclusion mapping match the table. RED pre-change: the helper does not exist
# (`bash <missing>` prints nothing / exits 127), so every row assertion fails.
trc_imp=0
trc_rev=0
while IFS=$'\t' read -r trc_tier trc_a trc_b trc_class trc_concl; do
  case "$trc_tier" in
    '#'* | '') continue ;;
  esac
  [ "$trc_a" = "<empty>" ] && trc_a=""
  [ "$trc_b" = "<empty>" ] && trc_b=""
  case "$trc_tier" in
    implement)
      trc_imp=$((trc_imp + 1))
      assert_eq "#1273 table implement[$trc_a|$trc_b] -> class" \
        "$trc_class" "$(bash "$TRC_HELPER" implement "$trc_a" "$trc_b")"
      assert_eq "#1273 table conclusion($trc_class) for implement[$trc_a|$trc_b]" \
        "$trc_concl" "$(bash "$TRC_HELPER" conclusion "$trc_class")"
      ;;
    review)
      trc_rev=$((trc_rev + 1))
      assert_eq "#1273 table review[$trc_a] -> class" \
        "$trc_class" "$(bash "$TRC_HELPER" review "$trc_a")"
      assert_eq "#1273 table conclusion($trc_class) for review[$trc_a]" \
        "$trc_concl" "$(bash "$TRC_HELPER" conclusion "$trc_class")"
      ;;
    *)
      assert_eq "#1273 table carries only known tiers" "implement|review" "$trc_tier" ;;
  esac
done < "$TRC_TABLE"
# Totality — the row counts equal the declared closed cross-product (10 workpad
# classes x 4 job statuses; 18-entry review vocabulary). A shrunk table fails here.
assert_eq "#1273 totality: implement leg = 10 workpad-classes x 4 job-statuses" "40" "$trc_imp"
assert_eq "#1273 totality: review leg = full outcome vocabulary" "18" "$trc_rev"

# ────────────────────────────────────────────────────────────────────────────
echo "#1273 terminal-result classifier — hand oracle (per acceptance criterion)"
# ────────────────────────────────────────────────────────────────────────────
# AC: each implement terminal class is from the closed set, and ONLY canonical
# complete/blocked produce complete/blocked.
assert_eq "#1273 canonical complete -> complete" "complete" "$(bash "$TRC_HELPER" implement complete success)"
assert_eq "#1273 canonical blocked -> blocked" "blocked" "$(bash "$TRC_HELPER" implement blocked success)"
# AC: workpad failed/cancelled/legacy-terminal/interim/unreadable/auth-failure/empty/
# unknown all -> incomplete.
for trc_tok in failed cancelled terminal interim unreadable auth-failure "" zzz-nonsense; do
  assert_eq "#1273 workpad token '$trc_tok' -> incomplete" \
    "incomplete" "$(bash "$TRC_HELPER" implement "$trc_tok" success)"
done
# AC: job cancellation -> incomplete even over a STALE canonical complete token.
assert_eq "#1273 job cancellation over stale complete -> incomplete" \
  "incomplete" "$(bash "$TRC_HELPER" implement complete cancelled)"
assert_eq "#1273 job cancellation over blocked -> incomplete" \
  "incomplete" "$(bash "$TRC_HELPER" implement blocked cancelled)"
# AC: is_error:false / exit-zero / progress-comment never satisfy the gate by
# themselves — the classifier has NO such input path, and the workpad status such a
# process-success run leaves (interim) is incomplete.
assert_eq "#1273 a green (is_error:false) run mid-lifecycle leaves interim -> incomplete" \
  "incomplete" "$(bash "$TRC_HELPER" implement interim success)"
# AC: only the six exact POSTED literals -> verdict-posted.
for trc_lit in \
  "POSTED review REQUEST_CHANGES" "POSTED review APPROVE" "POSTED review COMMENT" \
  "POSTED comment REQUEST_CHANGES" "POSTED comment APPROVE" "POSTED comment COMMENT"; do
  assert_eq "#1273 review '$trc_lit' -> verdict-posted" \
    "verdict-posted" "$(bash "$TRC_HELPER" review "$trc_lit")"
done
# AC: every SKIP / FAILED / blank / unknown / NOT-REACHED / UNESTABLISHED, and the
# REACHED-prefixed compatibility wrapper -> incomplete.
for trc_line in \
  "SKIP not-numeric" "FAILED no-durable-channel" "FAILED no-durable-channel boom" \
  "NOT-REACHED" "UNESTABLISHED receipt-empty" "REACHED POSTED review APPROVE" \
  "" "posted review approve" "POSTED reviews APPROVE"; do
  assert_eq "#1273 review '$trc_line' -> incomplete" \
    "incomplete" "$(bash "$TRC_HELPER" review "$trc_line")"
done
# Input normalization contract: a trailing carriage return IS trimmed (a receipt line
# written on one platform and read on another), so a CR-terminated POSTED literal still
# verdict-posts; leading whitespace is deliberately NOT trimmed, so an indented line
# stays outside the vocabulary and falls to incomplete. A regression that dropped the
# trailing-CR trim, or broadened it to strip leading/other whitespace, goes RED here.
assert_eq "#1273 review 'POSTED review APPROVE\\r' (trailing CR trimmed) -> verdict-posted" \
  "verdict-posted" "$(bash "$TRC_HELPER" review "$(printf 'POSTED review APPROVE\r')")"
assert_eq "#1273 review ' POSTED review APPROVE' (leading space NOT trimmed) -> incomplete" \
  "incomplete" "$(bash "$TRC_HELPER" review " POSTED review APPROVE")"
# AC: job-conclusion matrix — complete/verdict-posted succeed; blocked/incomplete and
# any unknown class fail closed to non-success.
assert_eq "#1273 conclusion(complete) -> success" "success" "$(bash "$TRC_HELPER" conclusion complete)"
assert_eq "#1273 conclusion(verdict-posted) -> success" "success" "$(bash "$TRC_HELPER" conclusion verdict-posted)"
assert_eq "#1273 conclusion(blocked) -> non-success" "non-success" "$(bash "$TRC_HELPER" conclusion blocked)"
assert_eq "#1273 conclusion(incomplete) -> non-success" "non-success" "$(bash "$TRC_HELPER" conclusion incomplete)"
assert_eq "#1273 conclusion(unknown class) -> non-success (fail closed)" \
  "non-success" "$(bash "$TRC_HELPER" conclusion zzz-nonsense)"

# ────────────────────────────────────────────────────────────────────────────
echo "#1273 terminal-result classifier — usage / arity guard"
# ────────────────────────────────────────────────────────────────────────────
# A missing operand is a usage error (exit 2), never a silent classification: an
# absent workpad class is not an empty-string workpad class.
bash "$TRC_HELPER" implement complete >/dev/null 2>&1
assert_eq "#1273 implement with one operand -> usage exit 2" "2" "$?"
bash "$TRC_HELPER" review >/dev/null 2>&1
assert_eq "#1273 review with no operand -> usage exit 2" "2" "$?"
bash "$TRC_HELPER" bogus-mode x >/dev/null 2>&1
assert_eq "#1273 unknown mode -> usage exit 2" "2" "$?"
