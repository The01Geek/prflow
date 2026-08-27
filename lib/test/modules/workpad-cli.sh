# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# shellcheck shell=bash
# Sourceable workpad-cli contract module (issue #1934).
# Contract: the caller sets LIB and RESULTS_FILE, defines assert_eq, and sources
# lib/test/module-harness.sh first. The module owns its private fixture root and
# cleanup; it never invokes the runner or the full-suite boundary. Modules may not
# self-skip. The inventory in workpad-cli.inventory.md maps the extracted coverage to its
# former lib/test/run.sh locations.
# Coverage (extracted from lib/test/run.sh, issue #1934):
#   scripts/workpad.py CLI contract: the #338 --rewrite-ac (post-merge) retag-requires-note structural-abort guard, driven as a real CLI subprocess against a gh stub.
#
# The trap below relies on the sourcing contract: both callers (module-harness.sh and
# run-module.sh) source this module inside a ( ... ) subshell, so the EXIT trap fires
# at subshell exit and cannot clobber the runner's own EXIT handling.
_m1934_root="$(mktemp -d "${TMPDIR:-/tmp}/devflow-workpad-cli.XXXXXX")" || {
  printf 'could not allocate workpad-cli fixture root\n' >&2
  return 1
}
_m1934_cleanup() { rm -rf "$_m1934_root"; }
trap _m1934_cleanup EXIT
# Redirect every `mktemp`/`mktemp -d` the extracted blocks allocate under the module's
# owned root, so all block fixtures are cleaned by the single trap above.
TMPDIR="$_m1934_root"
export TMPDIR
WP_PY="$LIB/../scripts/workpad.py"

# trailing (post-merge) tag (NEW ends with it after rstrip; neither OLD nor the row
# the pair resolves to already does) and which carries no non-empty --note aborts
# STRUCTURALLY — _UpdateError, exit 1, stderr naming the offending pair, NO PATCH
# issued (all-or-nothing preserved). The same call with a non-empty --note succeeds.
# A pair targeting a row that already ends with the tag, or that removes it, needs no
# note. Exercised as a real CLI subprocess against a gh stub, mirroring the #258
# fixture pattern. T1/T4/T5 go RED against the pre-guard workpad.py (the laundered
# tag PATCHed with no rationale); T2/T3/T3c/T5b are pass controls.
S338="$(mktemp -d)"
cat > "$S338/gh" <<'STUB'
#!/usr/bin/env bash
# Minimal gh stub for workpad.py update (issue #2042 unified resolution): the
# comments-list scan AND the single-comment verify fetch both return the full
# workpad object (body + issue_url), so the scan resolves id AND body together —
# no separate `--jq .body` body fetch, no `gh repo view`. PATCH records that a
# PATCH happened + echoes the patched body.
j="$*"
if [[ "$j" == *"-X PATCH"* ]]; then
  echo p >> "$WP_PATCHLOG"
  for a in "$@"; do case "$a" in body=@*) cat "${a#body=@}";; esac; done
  exit 0
fi
if [[ "$j" == *"issues/comments/7"* ]]; then
  printf '{"id":7,"body":%s,"issue_url":"https://api.github.com/repos/owner/repo/issues/999"}' "$(jq -Rs . < "$WP_BODY")"; exit 0
fi
if [[ "$j" == *"issues/999/comments"* ]]; then
  printf '[{"id":7,"body":%s,"issue_url":"https://api.github.com/repos/owner/repo/issues/999"}]' "$(jq -Rs . < "$WP_BODY")"; exit 0
fi
echo '[]'
STUB
chmod +x "$S338/gh"
# Issue #2042: clear the repo-root resolved-id cache so this block exercises the
# scan path first (the verify fetch self-heals a stale id, but a clean start keeps
# the fixtures deterministic across suite runs).
rm -rf "$LIB/../.prflow/tmp/workpad-id-cache"

cat > "$S338/base.md" <<'WPMD'
<!-- devflow:workpad -->
# DevFlow Workpad — Issue #999

**Status:** 🚀 Reviewing
**Last updated:** 2026-05-15T00:00:00Z

## Progress
- [ ] **Review**

## Plan
- [x] Plan step one

## Acceptance Criteria
- [ ] AC one
- [ ] AC two
WPMD
# A fixture whose AC two already carries the (post-merge) tag (for the OLD-already-tagged case).
sed 's/- \[ \] AC two/- [ ] AC two (post-merge)/' "$S338/base.md" > "$S338/base-tagged.md"
# A fixture carrying a `## Devflow Reflection` section, so a --reflection is a VALID
# mutation on it. Without that section --reflection aborts on 'section not found', and a
# test asserting "a reflection does not satisfy the --note" would pass for that unrelated
# reason — staying green against a mutant that lets a reflection satisfy the guard (T4d).
cp "$S338/base.md" "$S338/base-refl.md"
printf '\n## Devflow Reflection\n- existing bullet\n' >> "$S338/base-refl.md"
# A fixture whose AC two is already TICKED (`- [x]`). The retag guards must treat a
# ticked row's tag exactly like an unticked one: `- [x]` rows are outside the Phase 3.4
# terminal gate's population, but a `(post-merge)` tag landing on one is still a net-added
# tagged row, and SKILL.md/DEVFLOW_SYSTEM_OVERVIEW both promise a crafted multi-pair
# sequence that net-adds such a row is caught.
sed 's/- \[ \] AC two/- [x] AC two/' "$S338/base.md" > "$S338/base-ticked.md"
# ...and one whose ticked AC two is already tagged (for the tag-preserving no-false-fire control).
sed 's/- \[ \] AC two/- [x] AC two (post-merge)/' "$S338/base.md" > "$S338/base-ticked-tagged.md"

# These cases turn on whether the call carries a non-empty --note, and issue #1214's
# replay FOLDS a buffered note into `args.note` — so a replay buffer left over for the
# comment id this block's stub answers with (7) would satisfy the very guard T1 asserts
# fires. The producing block reclaims its own buffer; clear it here too so this block's
# precondition is stated where it is relied on rather than 700 lines away.
rm -f "$LIB/../.prflow/tmp/workpad-buffer/7.json"

# run338 <body-file> <args...> → prints the exit code; leaves out/err/patchlog on disk.
run338() {
  local body="$1"; shift
  : > "$S338/patchlog"
  WP_BODY="$body" WP_PATCHLOG="$S338/patchlog" DEVFLOW_GH="$S338/gh" \
    python3 "$WP_PY" update 999 --print-body "$@" >"$S338/out" 2>"$S338/err"
  echo $?
}

# T1 (refusal — reproduces the defect): appending pair, no --note → abort, NO PATCH.
_c="$(run338 "$S338/base.md" --rewrite-ac "AC two" "AC two (post-merge)")"
assert_eq "#338(T1): appending (post-merge) retag with no --note aborts non-zero" "no" \
  "$([ "$_c" = "0" ] && echo yes || echo no)"
assert_eq "#338(T1): the refusal made NO PATCH (all-or-nothing)" "yes" \
  "$([ -s "$S338/patchlog" ] && echo no || echo yes)"
assert_eq "#338(T1): the refusal names the offending pair on stderr" "yes" \
  "$(grep -q 'AC two' "$S338/err" && grep -q 'post-merge' "$S338/err" && echo yes || echo no)"

# T2 (pass with note): identical call + non-empty --note → exit 0, row rewritten.
_c="$(run338 "$S338/base.md" --rewrite-ac "AC two" "AC two (post-merge)" \
  --note "retro-tagged as post-merge (genuinely-live): live deploy target")"
assert_eq "#338(T2): the same retag WITH a non-empty --note succeeds (exit 0)" "0" "$_c"
assert_eq "#338(T2): the with-note retag PATCHed the row with the (post-merge) tag" "yes" \
  "$([ -s "$S338/patchlog" ] && grep -q '\- \[ \] AC two (post-merge)' "$S338/out" && echo yes || echo no)"

# T2b (note scope is the CALL, not the pair): the guard's documented contract is that ANY
# one non-empty --note in the same update call satisfies it, whether or not the note is
# *about* the retag — the note is appended to ## Progress, never bound to the rewritten
# row, so the guard enforces that a rationale EXISTS for the retrospective auditor to
# read, not that it is true or on-topic. This batched call carries a note describing the
# OTHER pair (the plain AC one rewrite) and never mentions the tag or the retagged row,
# and must still pass. Without this pin a refactor that bound the note to the specific
# appending pair would tighten the contract past what workpad.py's guard comment,
# SKILL.md, and docs/internal/implement-skill.md all promise, while every other S338 test — whose
# notes all happen to describe the retag itself — stayed green. Compare T5: the same
# batched shape with NO note is refused.
_c="$(run338 "$S338/base.md" --rewrite-ac "AC one" "AC one edited" \
  --rewrite-ac "AC two" "AC two (post-merge)" \
  --note "reworded the first criterion for clarity")"
assert_eq "#338(T2b): an appending retag is satisfied by any non-empty --note in the call, even one about an unrelated pair (exit 0)" "0" "$_c"
assert_eq "#338(T2b): the call-scoped-note retag PATCHed the (post-merge) row" "yes" \
  "$([ -s "$S338/patchlog" ] && grep -q '\- \[ \] AC two (post-merge)' "$S338/out" && echo yes || echo no)"
assert_eq "#338(T2b): the unrelated pair in the same call applied too" "yes" \
  "$(grep -q '\- \[ \] AC one edited' "$S338/out" && echo yes || echo no)"

# T3 (no false fire): OLD already ends with the tag → a text tweak needs no note.
_c="$(run338 "$S338/base-tagged.md" --rewrite-ac "AC two (post-merge)" "AC two reworded (post-merge)")"
assert_eq "#338(T3): a rewrite whose OLD already ends with (post-merge) passes with no note (exit 0)" "0" "$_c"
assert_eq "#338(T3): the tag-preserving rewrite PATCHed" "yes" \
  "$([ -s "$S338/patchlog" ] && echo yes || echo no)"

# T4 (empty note): --note "" with an appending pair is a MISSING rationale → refused.
_c="$(run338 "$S338/base.md" --rewrite-ac "AC two" "AC two (post-merge)" --note "")"
assert_eq "#338(T4): an empty-string --note is treated as missing → refused (non-zero)" "no" \
  "$([ "$_c" = "0" ] && echo yes || echo no)"
assert_eq "#338(T4): the empty-note refusal made NO PATCH" "yes" \
  "$([ -s "$S338/patchlog" ] && echo no || echo yes)"

# T5 (all-or-nothing): a mixed repeatable call (one appending pair among a plain
# rewrite), no note, is refused BEFORE any PATCH — no partial application.
_c="$(run338 "$S338/base.md" --rewrite-ac "AC one" "AC one edited" \
  --rewrite-ac "AC two" "AC two (post-merge)")"
assert_eq "#338(T5): a mixed call with one appending pair, no note, aborts non-zero" "no" \
  "$([ "$_c" = "0" ] && echo yes || echo no)"
assert_eq "#338(T5): the mixed-call refusal made NO PATCH (the plain rewrite did not partially apply)" "yes" \
  "$([ -s "$S338/patchlog" ] && echo no || echo yes)"

# T5b (guard + backstop no FALSE FIRE): an ordinary batched multi-pair rewrite that never
# touches the (post-merge) tag needs no note and must apply in full. Pins the innocent
# path both guards share: a regression that miscounted a plain row as post-merge-terminal
# (or classified a plain pair as an append) would abort an honest batch, and no other
# S338 test would notice — every one of them either carries a note or expects a refusal.
_c="$(run338 "$S338/base.md" --rewrite-ac "AC one" "AC one edited" \
  --rewrite-ac "AC two" "AC two edited")"
assert_eq "#338(T5b): an ordinary batched no-note rewrite that never touches the tag succeeds (exit 0)" "0" "$_c"
assert_eq "#338(T5b): both pairs of the innocent batch applied" "yes" \
  "$([ -s "$S338/patchlog" ] && grep -q '\- \[ \] AC one edited' "$S338/out" \
     && grep -q '\- \[ \] AC two edited' "$S338/out" && echo yes || echo no)"

# T3b (removal pair — documented no-note case, unpinned until now): NEW lacks the tag
# and OLD ends with it (de-tagging an already-post-merge row) needs no note. Pins the
# predicate's first-conjunct-False path (no current test drives it: T1/T2/T3 all have NEW
# ending in the marker), so a refactor that fired on any tag *movement* would go RED here.
_c="$(run338 "$S338/base-tagged.md" --rewrite-ac "AC two (post-merge)" "AC two")"
assert_eq "#338(T3b): a rewrite that REMOVES the (post-merge) tag passes with no note (exit 0)" "0" "$_c"
assert_eq "#338(T3b): the tag-removing rewrite PATCHed" "yes" \
  "$([ -s "$S338/patchlog" ] && echo yes || echo no)"

# T3c (no false REFUSAL — the guard reasons over the RESOLVED ROW, not the OLD string):
# a text tweak on a row that ALREADY ends with the tag creates no new deferral, so it
# needs no note — even when the OLD substring does not itself span the tag. The
# argument-string-only predicate classified this as an append and demanded a --note,
# contradicting the exemption workpad.py's docstring, SKILL.md and docs/internal/implement-skill.md
# all publish. Fails CLOSED (an extra-note demand, never a laundered deferral), but the
# published contract must match the code. RED against the OLD-string-only predicate.
_c="$(run338 "$S338/base-tagged.md" --rewrite-ac "AC two" "AC two clarified (post-merge)")"
assert_eq "#338(T3c): a tweak on an already-(post-merge) row needs no note even when OLD omits the tag (exit 0)" "0" "$_c"
assert_eq "#338(T3c): the already-tagged-row tweak PATCHed the reworded row" "yes" \
  "$([ -s "$S338/patchlog" ] && grep -q '\- \[ \] AC two clarified (post-merge)' "$S338/out" && echo yes || echo no)"
# Control: the SAME shape onto an UNTAGGED row is still refused — the exemption is bound
# to the target row's existing tag, not to the OLD substring being a prefix.
_c="$(run338 "$S338/base-tagged.md" --rewrite-ac "AC one" "AC one clarified (post-merge)")"
assert_eq "#338(T3c): the same shape onto an UNTAGGED row is still refused (non-zero)" "no" \
  "$([ "$_c" = "0" ] && echo yes || echo no)"
assert_eq "#338(T3c): the untagged-row refusal made NO PATCH" "yes" \
  "$([ -s "$S338/patchlog" ] && echo no || echo yes)"

# T4b (trailing-whitespace anti-evasion — the reason the predicate rstrips): an appending
# pair whose NEW ends with the tag plus trailing spaces is still an append and is refused
# with no note. Pins the rstrip; a bare endswith (no rstrip) would let this evasion through
# while every other S338 test stayed green.
_c="$(run338 "$S338/base.md" --rewrite-ac "AC two" "AC two (post-merge)   ")"
assert_eq "#338(T4b): an appending pair with trailing whitespace after the tag is refused (non-zero)" "no" \
  "$([ "$_c" = "0" ] && echo yes || echo no)"
assert_eq "#338(T4b): the trailing-whitespace-append refusal made NO PATCH" "yes" \
  "$([ -s "$S338/patchlog" ] && echo no || echo yes)"

# T4c (note-side anti-evasion — the discriminating input that actually pins `.strip()`):
# T4's `--note ""` does NOT pin it — `any([""])` is already falsy, so T4 stays GREEN
# against a mutant `has_note = any(n for n in args.note)`. A whitespace-only note is the
# input that separates them: truthy as a bare string, falsy after `.strip()`. Mutation-
# checked — dropping `.strip()` turns THIS assertion RED while T4 stays GREEN.
_c="$(run338 "$S338/base.md" --rewrite-ac "AC two" "AC two (post-merge)" --note "   ")"
assert_eq "#338(T4c): a whitespace-only --note is treated as missing → refused (non-zero)" "no" \
  "$([ "$_c" = "0" ] && echo yes || echo no)"
assert_eq "#338(T4c): the whitespace-note refusal made NO PATCH" "yes" \
  "$([ -s "$S338/patchlog" ] && echo no || echo yes)"

# T4d (only --note satisfies the rationale): a --reflection is a different channel
# (## Devflow Reflection) and never stands in for the retag rationale. Without this pin a
# refactor broadening has_note to accept a reflection would loosen the contract while
# every other S338 test stayed green. Runs against base-refl.md — the fixture that HAS a
# ## Devflow Reflection section — so the reflection is a valid mutation and the refusal is
# attributable to the guard; on a section-less fixture this test would pass vacuously via
# 'section not found'. The stderr assertion pins that attribution (cf. T7's 'net-adds').
_c="$(run338 "$S338/base-refl.md" --rewrite-ac "AC two" "AC two (post-merge)" \
  --reflection "retro-tagged as post-merge (genuinely-live): live deploy target")"
assert_eq "#338(T4d): a --reflection does not satisfy the --note rationale → refused (non-zero)" "no" \
  "$([ "$_c" = "0" ] && echo yes || echo no)"
assert_eq "#338(T4d): the reflection-only refusal made NO PATCH" "yes" \
  "$([ -s "$S338/patchlog" ] && echo no || echo yes)"
assert_eq "#338(T4d): the refusal is the rationale guard's, not an incidental section abort" "yes" \
  "$(grep -q 'no non-empty --note rationale' "$S338/err" && echo yes || echo no)"
# Control: the same call on the same fixture WITH a --note succeeds — proving base-refl.md
# is not itself the reason T4d is refused (the reflection applies cleanly alongside).
_c="$(run338 "$S338/base-refl.md" --rewrite-ac "AC two" "AC two (post-merge)" \
  --reflection "context bullet" --note "genuinely-live: live deploy target")"
assert_eq "#338(T4d): the same reflection call WITH a --note succeeds (exit 0)" "0" "$_c"

# T4e (the --note-file channel satisfies the rationale, issue #1813): a refactor dropping
# the `note_file` clause from `has_note` would refuse every worktree-isolated run's retag
# while every other S338 test stayed green. T4e is also T4f/T4g's positive control.
printf 'retro-tagged (genuinely-live): the `deploy` target is live\n' > "$S338/note-ok.txt"
_c="$(run338 "$S338/base.md" --rewrite-ac "AC two" "AC two (post-merge)" \
  --note-file "$S338/note-ok.txt")"
assert_eq "#338(T4e): a --note-file rationale satisfies the retag guard (exit 0)" "0" "$_c"
assert_eq "#338(T4e): the --note-file retag PATCHed the (post-merge) row" "yes" \
  "$([ -s "$S338/patchlog" ] && grep -q '\- \[ \] AC two (post-merge)' "$S338/out" && echo yes || echo no)"
assert_eq "#338(T4e): the file payload landed as the ## Progress rationale, backticks intact" "yes" \
  "$(grep -q 'the `deploy` target is live' "$S338/out" && echo yes || echo no)"

# T4f: `has_note` tests the flag's PRESENCE, not its payload, so this call reaches the guard
# with has_note true and only the payload reader refuses it. An rc-only assertion would stay
# green against a mutant that dropped the empty-payload guard — pin the attribution.
: > "$S338/note-empty.txt"
_c="$(run338 "$S338/base.md" --rewrite-ac "AC two" "AC two (post-merge)" \
  --note-file "$S338/note-empty.txt")"
assert_eq "#338(T4f): an empty --note-file payload does not permit the retag (non-zero)" "no" \
  "$([ "$_c" = "0" ] && echo yes || echo no)"
assert_eq "#338(T4f): the empty-payload refusal made NO PATCH" "yes" \
  "$([ -s "$S338/patchlog" ] && echo no || echo yes)"
assert_eq "#338(T4f): the refusal is the --note-file payload reader's, not an incidental abort" "yes" \
  "$(grep -q 'empty or whitespace-only' "$S338/err" && grep -q '\-\-note-file' "$S338/err" && echo yes || echo no)"
assert_eq "#338(T4f): the payload reader — not the rationale guard — refused (stderr has no 'rationale')" "yes" \
  "$(grep -q 'rationale was supplied' "$S338/err" && echo no || echo yes)"

# T4g (whitespace-only — the discriminating input for the reader's `.strip()`): a mutant
# dropping that strip would launder a blank rationale through the presence check while
# T4f, whose payload is empty as bytes too, stayed green.
printf '   \n\t\n' > "$S338/note-ws.txt"
_c="$(run338 "$S338/base.md" --rewrite-ac "AC two" "AC two (post-merge)" \
  --note-file "$S338/note-ws.txt")"
assert_eq "#338(T4g): a whitespace-only --note-file payload does not permit the retag (non-zero)" "no" \
  "$([ "$_c" = "0" ] && echo yes || echo no)"
assert_eq "#338(T4g): the whitespace-payload refusal made NO PATCH" "yes" \
  "$([ -s "$S338/patchlog" ] && echo no || echo yes)"

# --- issue #2076: --note-file / --reflection-file are repeatable, as a real CLI
# subprocess against the same gh stub — the exit codes and stderr a caller sees. ---
# S2076-1: two --note-file payloads render TWO ## Progress bullets (subprocess-level
# reproduction of the drop). Against the pre-fix `store` this PATCHed one bullet.
printf 'first file note\n' > "$S338/nf-a.txt"
printf 'second file note\n' > "$S338/nf-b.txt"
_c="$(run338 "$S338/base.md" --note-file "$S338/nf-a.txt" --note-file "$S338/nf-b.txt")"
assert_eq "#2076(S1): two --note-file payloads succeed (exit 0)" "0" "$_c"
assert_eq "#2076(S1): both --note-file payloads render as bullets" "yes" \
  "$(grep -q 'first file note' "$S338/out" && grep -q 'second file note' "$S338/out" && echo yes || echo no)"

# S2076-2: passing the stdin form '-' more than once for one flag is refused
# non-zero, makes NO PATCH, and the stderr names the flag and the at-most-once rule.
_c="$(run338 "$S338/base.md" --note-file - --note-file -)"
assert_eq "#2076(S2): repeated --note-file '-' aborts non-zero" "no" \
  "$([ "$_c" = "0" ] && echo yes || echo no)"
assert_eq "#2076(S2): the repeated-'-' refusal made NO PATCH" "yes" \
  "$([ -s "$S338/patchlog" ] && echo no || echo yes)"
assert_eq "#2076(S2): the refusal names --note-file and the at-most-once rule" "yes" \
  "$(grep -q '\-\-note-file' "$S338/err" && grep -q 'at most once' "$S338/err" && echo yes || echo no)"

# S2076-3 (AC9): `update --help` states, for each of the two flags, that it may be
# passed more than once and that the stdin form may be used at most once per flag.
_h2076="$(python3 "$WP_PY" update --help 2>&1 | tr -s '[:space:]' ' ')"
assert_eq "#2076(S3): --help states --note-file/--reflection-file may be passed more than once" "yes" \
  "$([ "$(printf '%s' "$_h2076" | grep -io 'may be passed more than once' | wc -l)" -ge 2 ] && echo yes || echo no)"
assert_eq "#2076(S3): --help states the stdin form may be used at most once per flag" "yes" \
  "$([ "$(printf '%s' "$_h2076" | grep -io 'may be used at most once per flag' | wc -l)" -ge 2 ] && echo yes || echo no)"

# T7 (state-based multi-pair backstop, issue #338 hardening): a crafted two-pair call whose
# pairs each individually dodge the per-pair guard — pair 1 places the marker non-terminally
# (NEW doesn't end in the tag), pair 2 makes it terminal (OLD ends in the tag) — net-adds a
# (post-merge) row. The per-pair guard alone would fail OPEN here; the post-loop count-of-
# post-merge-rows backstop catches it and aborts before any PATCH. RED against the pre-
# backstop code (the laundered tag PATCHes with no note).
_c="$(run338 "$S338/base.md" --rewrite-ac "AC two" "(post-merge) AC two" \
  --rewrite-ac "(post-merge)" "AC two (post-merge)")"
assert_eq "#338(T7): a multi-pair call that net-adds a (post-merge) row with no note is refused (non-zero)" "no" \
  "$([ "$_c" = "0" ] && echo yes || echo no)"
assert_eq "#338(T7): the multi-pair backstop refusal made NO PATCH (all-or-nothing)" "yes" \
  "$([ -s "$S338/patchlog" ] && echo no || echo yes)"
# Assert the refusal came from the STATE BACKSTOP ('net-adds'), not an incidental
# _rewrite_checkbox zero/multi-match abort — so a refactor that made this call fail for
# the wrong reason (while the backstop silently rotted) is caught, not masked by T7b.
assert_eq "#338(T7): the refusal is the state backstop's 'net-adds' abort, not an incidental match failure" "yes" \
  "$(grep -q 'net-adds' "$S338/err" && echo yes || echo no)"
# T7b (backstop no false fire): the identical multi-pair call WITH a non-empty --note succeeds.
_c="$(run338 "$S338/base.md" --rewrite-ac "AC two" "(post-merge) AC two" \
  --rewrite-ac "(post-merge)" "AC two (post-merge)" --note "retro-tagged (genuinely-live): live endpoint")"
assert_eq "#338(T7b): the same multi-pair retag WITH a --note succeeds (exit 0)" "0" "$_c"

# T8 (single-pair append onto an already-TICKED row): the per-pair guard is tick-state
# agnostic — it reasons over the row's LABEL text, which `_CHECKBOX_ROW_RE` exposes
# independently of the `[ ]`/`[x]` state cell — so this is refused with no note. Behavior
# was already correct but unpinned; without this a refactor that skipped `[x]` rows in the
# per-pair guard (to "match" the backstop's old unticked-only population) would go
# unnoticed by every other S338 test, all of which drive `- [ ]` rows.
#
# ATTRIBUTION IS LOAD-BEARING HERE, not decoration. Since the backstop now also counts
# ticked rows, a mutant that skips `[x]` rows in the per-pair guard STILL exits non-zero
# with no PATCH — the backstop catches it one step later. rc/no-PATCH assertions alone
# therefore pass on the very mutant this test exists to kill. Pin the refusal to the
# PER-PAIR guard: its message names the offending pair, and it never says `net-adds` (the
# backstop's word). Both attribution assertions below independently kill that mutant — the
# backstop's message omits the pair AND says `net-adds` — while the rc/no-PATCH assertions
# alone stay GREEN on it. Note the backstop's message also contains the phrase
# `no non-empty --note rationale`, so that substring alone does not discriminate; the
# pair name is what does.
_c="$(run338 "$S338/base-ticked.md" --rewrite-ac "AC two" "AC two (post-merge)")"
assert_eq "#338(T8): a single-pair (post-merge) append onto a TICKED [x] row is refused (non-zero)" "no" \
  "$([ "$_c" = "0" ] && echo yes || echo no)"
assert_eq "#338(T8): the ticked-row single-pair refusal made NO PATCH" "yes" \
  "$([ -s "$S338/patchlog" ] && echo no || echo yes)"
assert_eq "#338(T8): the refusal is the PER-PAIR guard's (names the pair + rationale), not the backstop's" "yes" \
  "$(grep -q 'AC two' "$S338/err" && grep -q 'no non-empty --note rationale' "$S338/err" && echo yes || echo no)"
assert_eq "#338(T8): the per-pair guard — not the state backstop — refused (stderr has no 'net-adds')" "yes" \
  "$(grep -q 'net-adds' "$S338/err" && echo no || echo yes)"

# T8b (the ticked-row SHUTTLE — the fail-open this backstop population closes): the same
# crafted two-pair shuttle as T7, aimed at an already-`[x]` row. Both pairs dodge the
# per-pair guard exactly as in T7; with the backstop counting only UNTICKED rows the
# tagged row landed with NO note and exit 0, silently falsifying SKILL.md's and
# DEVFLOW_SYSTEM_OVERVIEW's promise that "a crafted multi-pair sequence that net-adds a
# (post-merge) row is caught by the same rule". Snapshotting each row's post-merge-terminal
# flag across EVERY tick state (`_post_merge_flags`) closes it. RED against the
# unticked-only population; the 'net-adds' grep pins that the STATE BACKSTOP is what
# refuses it (T8 already covers the per-pair path, so a refusal for the wrong reason would
# otherwise pass here).
_c="$(run338 "$S338/base-ticked.md" --rewrite-ac "AC two" "(post-merge) AC two" \
  --rewrite-ac "(post-merge)" "AC two (post-merge)")"
assert_eq "#338(T8b): a multi-pair shuttle that net-adds (post-merge) onto a TICKED row is refused (non-zero)" "no" \
  "$([ "$_c" = "0" ] && echo yes || echo no)"
assert_eq "#338(T8b): the ticked-row shuttle refusal made NO PATCH (all-or-nothing)" "yes" \
  "$([ -s "$S338/patchlog" ] && echo no || echo yes)"
assert_eq "#338(T8b): the ticked-row shuttle refusal is the state backstop's 'net-adds' abort" "yes" \
  "$(grep -q 'net-adds' "$S338/err" && echo yes || echo no)"
# T8c (no false fire on the widened population): a tag-PRESERVING tweak on an already-tagged
# TICKED row adds no tagged row, so the wider count must not fire — this is the assertion a
# naive "count every tagged row and abort on any tagged row present" backstop would fail.
_c="$(run338 "$S338/base-ticked-tagged.md" --rewrite-ac "AC two (post-merge)" "AC two reworded (post-merge)")"
assert_eq "#338(T8c): a tag-preserving tweak on a TICKED tagged row still passes with no note (exit 0)" "0" "$_c"
assert_eq "#338(T8c): the ticked tag-preserving rewrite PATCHed" "yes" \
  "$([ -s "$S338/patchlog" ] && echo yes || echo no)"
# T8d (no false fire): REMOVING the tag from a ticked tagged row decreases the count → passes.
_c="$(run338 "$S338/base-ticked-tagged.md" --rewrite-ac "AC two (post-merge)" "AC two")"
assert_eq "#338(T8d): removing the tag from a TICKED row passes with no note (exit 0)" "0" "$_c"

# T9 (net-zero tag-swap — the last laundering shape): remove the tag from one row while
# shuttling it onto ANOTHER, with no note. Every pair dodges the per-pair guard (pair 1
# removes; pair 2's NEW is non-terminal; pair 3's OLD ends with the tag), and the TOTAL
# count of tagged rows is unchanged — so an aggregate-count backstop reads "no net add"
# and PATCHes a silently-deferred criterion. Comparing each row's flag POSITIONALLY
# catches it: AC one transitions untagged -> terminally-tagged. RED against a count-based
# backstop (verified: it exits 0 and PATCHes `- [ ] AC one (post-merge)`).
_c="$(run338 "$S338/base-tagged.md" --rewrite-ac "AC two (post-merge)" "AC two" \
  --rewrite-ac "AC one" "(post-merge) AC one" \
  --rewrite-ac "(post-merge)" "AC one (post-merge)")"
assert_eq "#338(T9): a net-zero tag-swap onto another row is refused (non-zero)" "no" \
  "$([ "$_c" = "0" ] && echo yes || echo no)"
assert_eq "#338(T9): the net-zero tag-swap refusal made NO PATCH (all-or-nothing)" "yes" \
  "$([ -s "$S338/patchlog" ] && echo no || echo yes)"
assert_eq "#338(T9): the net-zero refusal is the state backstop's 'net-adds' abort" "yes" \
  "$(grep -q 'net-adds' "$S338/err" && echo yes || echo no)"
# T9b (no false fire): the identical net-zero swap WITH a --note succeeds.
_c="$(run338 "$S338/base-tagged.md" --rewrite-ac "AC two (post-merge)" "AC two" \
  --rewrite-ac "AC one" "(post-merge) AC one" \
  --rewrite-ac "(post-merge)" "AC one (post-merge)" \
  --note "moved the deferral: AC one needs the live endpoint, AC two was verified")"
assert_eq "#338(T9b): the same net-zero swap WITH a --note succeeds (exit 0)" "0" "$_c"

# T10 (newline in NEW — the premise the positional comparison rests on): `_rewrite_checkbox`
# writes NEW verbatim into ONE line, so an embedded newline splits that checkbox row in two.
# That injects an unreviewed AC row AND breaks the row-index stability `_net_adds_post_merge`
# compares against. It also slips the per-pair guard, whose `NEW ends with the marker` test
# reads the whole string (`X (post-merge)\n- [ ] Y` ends with `Y`). Reject it structurally,
# note or not. RED against the pre-fix code, which exited 0 and PATCHed the injected row.
_c="$(run338 "$S338/base.md" --rewrite-ac "AC two" 'AC two (post-merge)
- [ ] Injected')"
assert_eq "#338(T10): a --rewrite-ac NEW containing a line break is refused (non-zero)" "no" \
  "$([ "$_c" = "0" ] && echo yes || echo no)"
assert_eq "#338(T10): the line-break refusal made NO PATCH (no row injected)" "yes" \
  "$([ -s "$S338/patchlog" ] && echo no || echo yes)"
assert_eq "#338(T10): the refusal names the line boundary, not the missing note" "yes" \
  "$(grep -q 'line boundary in NEW' "$S338/err" && echo yes || echo no)"
# T10a (the full `str.splitlines()` separator set — the superset bug): a `'\n' in s or
# '\r' in s` membership test accepts \v, \f, \x1c-\x1e, NEL, LS and PS, EVERY one of which
# `str.splitlines()` still splits on — so each injected a phantom `- [x]` row (with a
# --note, both post-merge guards are skipped, leaving the row check as the only defense).
# `_is_single_line` shares splitlines' own contract, so the rejected set matches exactly.
# Driven with a --note so a refusal cannot come from a post-merge guard. RED against the
# two-character membership test (all eight exited 0 and PATCHed an injected row).
# Interpreter note: `printf '%b'` must expand `\302\205` (NEL), `\342\200\250` (LS) and
# `\342\200\251` (PS) to their real bytes for the last three cases to drive a separator at
# all. Bash's printf does; zsh's does not — it emits the literal backslash text, which
# carries no separator, so workpad.py would accept the rewrite (exit 0) and these
# assertions would FAIL LOUDLY. They cannot degrade into a silent green. This suite's
# shebang is `#!/usr/bin/env bash`, so the expansion holds. Independently verified: under a
# membership-test mutant all eight — including these three — go RED, which they could not
# if their input carried no separator.
for _sep in '\v' '\f' '\034' '\035' '\036' '\302\205' '\342\200\250' '\342\200\251'; do
  _new="$(printf 'AC two (post-merge)%b- [x] Phantom' "$_sep")"
  _c="$(run338 "$S338/base.md" --rewrite-ac "AC two" "$_new" --note "genuinely-live: endpoint")"
  assert_eq "#338(T10a): NEW split by separator '$_sep' is refused even with a --note" "no" \
    "$([ "$_c" = "0" ] && echo yes || echo no)"
  assert_eq "#338(T10a): separator '$_sep' injected no row (NO PATCH)" "yes" \
    "$([ -s "$S338/patchlog" ] && echo no || echo yes)"
done
# T10b: a --note does NOT excuse it — the newline is a malformed argument, not a deferral.
_c="$(run338 "$S338/base.md" --rewrite-ac "AC two" 'AC two (post-merge)
- [ ] Injected' --note "genuinely-live: live endpoint")"
assert_eq "#338(T10b): a line break in NEW is refused even WITH a --note (non-zero)" "no" \
  "$([ "$_c" = "0" ] && echo yes || echo no)"
# T10c (the laundering combo the newline enabled): remove a tag from one row while
# newline-splitting another into a terminally-tagged row. Row counts differ, so an
# aggregate-count fallback reads the sum as flat and passes. Refused now — first by the
# newline check; and were that ever removed, _net_adds_post_merge's length-mismatch branch
# fails CLOSED rather than downgrading to the blind aggregate compare.
_c="$(run338 "$S338/base-tagged.md" --rewrite-ac "AC two (post-merge)" "AC two" \
  --rewrite-ac "AC one" 'AC one (post-merge)
- [ ] Injected')"
assert_eq "#338(T10c): a newline-split net-zero laundering combo is refused (non-zero)" "no" \
  "$([ "$_c" = "0" ] && echo yes || echo no)"
assert_eq "#338(T10c): the laundering combo made NO PATCH" "yes" \
  "$([ -s "$S338/patchlog" ] && echo no || echo yes)"
# T10d (no false fire): a NEW with ordinary internal whitespace (not a line break) is fine.
_c="$(run338 "$S338/base.md" --rewrite-ac "AC two" "AC two   with   spaces")"
assert_eq "#338(T10d): a NEW with internal spaces (no line break) still passes (exit 0)" "0" "$_c"

# Source pin: the length-mismatch branch fails CLOSED (returns True), never degrading to an
# aggregate `sum(post) > sum(pre)` compare that is blind to a remove-one/add-one swap.
assert_eq "#338: _net_adds_post_merge fails closed on a row-count mismatch (no aggregate fallback)" "yes" \
  "$(grep -q 'sum(post) > sum(pre)' "$WP_PY" && echo no || echo yes)"
# Source pin: the newline rejection guards the row-index-stability premise. Pin the SYMBOL,
# not the stderr wording — the message literal is an f-string wrapped across two source
# lines ("...has a line " / "boundary in NEW; ..."), so no single line contains the phrase
# whole and a source grep for it always fails. (That is the same wrapped-literal blind spot
# that let the argparse help text drift; the rendered-surface pins are the ones that catch
# wording, and T10 already asserts this message on real stderr.)
assert_eq "#338: --rewrite-ac structurally rejects a line break in NEW" "yes" \
  "$(grep -q 'offending_nl' "$WP_PY" && echo yes || echo no)"

# Source pin: the backstop's population spans every tick state AND compares positionally.
# A revert to `_unticked_rows(content)[1]` re-opens the T8b ticked-row fail-open; a revert
# to an aggregate count re-opens the T9 net-zero fail-open.
assert_eq "#338: the retag backstop snapshots per-row post-merge flags (not an aggregate count)" "yes" \
  "$(grep -q 'pre_pm = _post_merge_flags(content)' "$WP_PY" && echo yes || echo no)"
assert_eq "#338: the retag backstop compares those flags positionally via _net_adds_post_merge" "yes" \
  "$(grep -q '_net_adds_post_merge(pre_pm, _post_merge_flags(content))' "$WP_PY" && echo yes || echo no)"

# Source pin: the rationale-required guard + its predicate live in workpad.py.
assert_eq "#338: workpad.py carries the (post-merge)-retag rationale guard" "yes" \
  "$(grep -q '_pair_appends_post_merge' "$WP_PY" && echo yes || echo no)"
# Source pin: the guard SHARES the rewriter's row resolution (parse, don't validate)
# rather than re-deriving the target row from the OLD argument string. A revert to the
# two-argument, string-only predicate re-introduces the T3c false refusal.
assert_eq "#338: the retag guard resolves the target row via _find_checkbox_row" "yes" \
  "$(grep -q '_find_checkbox_row' "$WP_PY" && echo yes || echo no)"
# Coupled-invariant pin: SKILL.md publishes the row-scoped --rewrite-ac exemption
# (not the stale OLD-only form). Edited in lockstep with the predicate above.
assert_eq "#338: SKILL.md publishes the row-scoped (post-merge) exemption" "yes" \
  "$(grep -q 'neither OLD nor the row it targets already does' \
       "$LIB/../skills/implement/SKILL.md" && echo yes || echo no)"
# ...and the NEGATIVE half. `grep -q` reports presence, not exhaustiveness, so the positive
# assertion above can stay GREEN across a partial reversion to the stale OLD-only form.
# The positive half also reads only skills/implement/SKILL.md, so a reversion confined to the
# docs mirror is invisible to it. Asserting the stale form is ABSENT catches a reversion in
# either file the loop below covers — and does so without a brittle occurrence-count pin that
# a further legitimate mention would break.
for _f338 in "$LIB/../skills/implement/SKILL.md" "$LIB/../docs/internal/implement-skill.md"; do
  assert_eq "#338: $(basename "$_f338") carries no stale OLD-only (post-merge) contract sentence" "yes" \
    "$(grep -q 'NEW ends with it, OLD does not' "$_f338" && echo no || echo yes)"
done
# Coupled-invariant pin on the RENDERED CLI surface. workpad.py's --rewrite-ac argparse
# help is a third mirror of the guard contract, and it is the one a plain source grep for
# the contract sentence MISSES: argparse help is assembled from adjacent string literals,
# so the phrase wraps across lines ('... OLD does ' 'not)') and no line contains it whole.
# Pin what the user actually reads — `update --help` — so a stale OLD-only help text turns
# the suite RED. Asserts the row-scoped phrasing is present AND the stale form is gone.
_h338="$(python3 "$WP_PY" update --help 2>&1)"
assert_eq "#338: workpad.py --rewrite-ac help publishes the row-scoped exemption" "yes" \
  "$(printf '%s' "$_h338" | tr -s '[:space:]' ' ' \
     | grep -q 'neither OLD nor the row it targets already does' && echo yes || echo no)"
assert_eq "#338: workpad.py --rewrite-ac help no longer carries the stale OLD-only form" "yes" \
  "$(printf '%s' "$_h338" | tr -s '[:space:]' ' ' \
     | grep -q 'NEW ends with it, OLD does not' && echo no || echo yes)"
assert_eq "#338: workpad.py --rewrite-ac help states a --reflection does not satisfy the note" "yes" \
  "$(printf '%s' "$_h338" | tr -s '[:space:]' ' ' \
     | grep -q 'Only --note satisfies the rationale; a --reflection does not' && echo yes || echo no)"
assert_eq "#338: workpad.py --rewrite-ac help states NEW must be a single line" "yes" \
  "$(printf '%s' "$_h338" | tr -s '[:space:]' ' ' \
     | grep -q 'NEW must be a single line' && echo yes || echo no)"

# T6: exact-one check for the operative third forbidden case in phase-3-review.md §3.4;
# deletion or duplication fails.
P3REVIEW="$LIB/../skills/implement/phases/phase-3-ac-gate.md"
devflow_module_pin_unique "#338(T6): §3.4 pins the operative sentence of the self-reconfiguration forbidden case" \
  'is runnable on this host and is never `(post-merge)`' "$P3REVIEW"  # structural-pin-ok: lifecycle-state-transition -- the self-reconfiguration forbidden case bounds the (post-merge) deferral

# --- issue #2024: workpad size limits (per-note budget + comment cap), driven as
# a real CLI subprocess against the same gh stub. ---
rm -f "$LIB/../.prflow/tmp/workpad-buffer/7.json"
# S1: a single --note over 2,048 bytes aborts non-zero, makes NO PATCH, and the
# stderr names the measured byte count and the 2,048-byte budget.
_s2024_big="$(printf '%*s' 2049 '' | tr ' ' x)"
_c="$(run338 "$S338/base.md" --note "$_s2024_big")"
assert_eq "#2024(S1): an oversize --note aborts non-zero" "no" \
  "$([ "$_c" = "0" ] && echo yes || echo no)"
assert_eq "#2024(S1): the oversize --note made NO PATCH" "yes" \
  "$([ -s "$S338/patchlog" ] && echo no || echo yes)"
assert_eq "#2024(S1): the refusal names the byte count and the 2048-byte budget" "yes" \
  "$(grep -q '2049 bytes' "$S338/err" && grep -q '2048-byte' "$S338/err" && echo yes || echo no)"
# S2: a within-budget --note is accepted and PATCHes.
_c="$(run338 "$S338/base.md" --note "an ordinary short note")"
assert_eq "#2024(S2): a within-budget --note succeeds (exit 0)" "0" "$_c"
assert_eq "#2024(S2): the within-budget --note PATCHed" "yes" \
  "$([ -s "$S338/patchlog" ] && echo yes || echo no)"
# S3: an update whose resulting comment body exceeds 65,536 bytes aborts non-zero,
# makes NO PATCH, and the stderr names the 65,536 limit and that it is a byte count.
_s2024_pad="$(printf '%*s' 66000 '' | tr ' ' x)"
cp "$S338/base.md" "$S338/base-big.md"
printf -- '- [ ] %s\n' "$_s2024_pad" >> "$S338/base-big.md"
_c="$(run338 "$S338/base-big.md" --note "tiny")"
assert_eq "#2024(S3): an over-cap comment body aborts non-zero" "no" \
  "$([ "$_c" = "0" ] && echo yes || echo no)"
assert_eq "#2024(S3): the over-cap comment body made NO PATCH" "yes" \
  "$([ -s "$S338/patchlog" ] && echo no || echo yes)"
assert_eq "#2024(S3): the refusal names the 65536 limit and that it is a byte count" "yes" \
  "$(grep -q '65536' "$S338/err" && grep -q 'byte count' "$S338/err" && echo yes || echo no)"
# S4: the `patch` route enforces the comment cap too — covering the cmd_patch
# except-arm (and _patch_comment_body's body_path branch) that AC10 bypasses.
# The marker on line 1 degrades the live-body check so it reaches the size guard.
_s2024_patchbig="$S338/patch-big.md"
printf '<!-- devflow:workpad -->\n' > "$_s2024_patchbig"
printf '%*s\n' 66000 '' | tr ' ' x >> "$_s2024_patchbig"
: > "$S338/patchlog"
WP_BODY="$S338/base.md" WP_PATCHLOG="$S338/patchlog" DEVFLOW_GH="$S338/gh" \
  python3 "$WP_PY" patch 7 "$_s2024_patchbig" >"$S338/out" 2>"$S338/err"
_c=$?
assert_eq "#2024(S4): the patch route refuses an over-cap body (non-zero)" "no" \
  "$([ "$_c" = "0" ] && echo yes || echo no)"
assert_eq "#2024(S4): the patch-route refusal made NO PATCH" "yes" \
  "$([ -s "$S338/patchlog" ] && echo no || echo yes)"
assert_eq "#2024(S4): the patch-route refusal names the 65536 limit" "yes" \
  "$(grep -q '65536' "$S338/err" && echo yes || echo no)"

rm -rf "$S338"
