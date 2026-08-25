# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# shellcheck shell=bash
# Sourceable installer / workflow-wiring contract module (issue #695 extraction).
# Contract: the caller sets LIB and RESULTS_FILE, defines assert_eq, and sources
# lib/test/module-harness.sh before this module.
# The `trap _iw_cleanup EXIT` below relies on a sourcing contract: both callers
# (module-harness.sh's full-suite boundary and run-module.sh) source this module
# inside a ( ... ) subshell, so the trap fires at subshell exit and cannot clobber
# the runner's own EXIT handling. Do not source this module directly in a runner's
# top-level shell without restoring the trap.

# The workflows directory is re-derived from the harness-provided LIB rather than
# inherited from lib/test/run.sh's own `WF` global: both runner paths execute a module
# body under `set -u`, so a verbatim extraction that read the monolith's WF would abort
# on the first statement with `WF: unbound variable` before any assertion ran.
# lib/test/run.sh keeps its own WF assignment for the coverage that stays behind.
WF="$LIB/../.github/workflows"

_iw_tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/devflow-installer-wiring.XXXXXX")" || {
  printf 'could not allocate installer-wiring fixture root\n' >&2
  return 1
}
_iw_cleanup() {
  rm -rf "$_iw_tmp_root"
}
trap _iw_cleanup EXIT

# ────────────────────────────────────────────────────────────────────────────
echo "#487/#491/#533/#544/#599/#690 installer + workflow wiring (extracted to installer-wiring module)"
# ────────────────────────────────────────────────────────────────────────────
for _wf487 in devflow-implement devflow; do
  _WFF487="$WF/$_wf487.yml"
  assert_eq "#487 wiring: $_wf487.yml starts the credential refresher" "1" \
    "$(grep -cF 'name: Start credential refresher (optional)' "$_WFF487")"
  assert_eq "#487 wiring: $_wf487.yml installs the fresh-gh wrapper" "1" \
    "$(grep -cF 'name: Install fresh-gh wrapper (optional)' "$_WFF487")"
  assert_eq "#487 wiring: $_wf487.yml retires the refresher (pidfile-kill, if: always())" "1" \
    "$(grep -cF 'name: Stop credential refresher (optional)' "$_WFF487")"
  # The Stop step delegates its branch/message logic to the extracted helper
  # (inline-shell-extraction convention) rather than carrying it inline.
  assert_eq "#487 wiring: $_wf487.yml Stop step invokes the vendored stop-refresher.sh helper" "1" \
    "$(grep -cF '.prflow/vendor/prflow/scripts/stop-refresher.sh' "$_WFF487")"
  assert_eq "#487 wiring: $_wf487.yml invokes the vendored refresher via nohup (detached, not background:)" "1" \
    "$(grep -cF 'nohup bash .prflow/vendor/prflow/scripts/refresh-app-credentials.sh loop' "$_WFF487")"
  # ── /proc/<pid>/environ mitigation (PR #491). The Start step exports the PEM as a
  # step-level env var (to pipe it to the refresher's stdin); that var is inherited
  # into the detached refresher's exec-time environment, where the concurrent same-uid
  # claude step could read the raw PEM via /proc/<pid>/environ (which snapshots the
  # environment at execve and is NOT cleared by an in-process `unset` — proc(5)). The
  # ACTUAL mitigation is launching the refresher with `env -u DEVFLOW_APP_PRIVATE_KEY`,
  # so the long-lived process's environ never holds the PEM. Removal reopens the leak.
  _startblk487="$(mint_blk 'Start credential refresher (optional)' "$_WFF487")"
  _envu_ln="$(printf '%s\n' "$_startblk487" | grep -nF 'env -u DEVFLOW_APP_PRIVATE_KEY' | head -1 | cut -d: -f1)"
  _nohup_ln="$(printf '%s\n' "$_startblk487" | grep -nF 'nohup bash .prflow/vendor/prflow/scripts/refresh-app-credentials.sh loop' | head -1 | cut -d: -f1)"
  assert_eq "#487 wiring: $_wf487.yml launches the refresher with env -u DEVFLOW_APP_PRIVATE_KEY BEFORE nohup (closes the /proc PEM leak)" "yes" \
    "$([ -n "$_envu_ln" ] && [ -n "$_nohup_ln" ] && [ "$_envu_ln" -lt "$_nohup_ln" ] && echo yes || echo no)"
  # No `background:` step key anywhere (would break actionlint).
  assert_eq "#487 wiring: $_wf487.yml uses no 'background:' step key (actionlint-safe)" "0" \
    "$(grep -cE '^[[:space:]]*background:[[:space:]]*true' "$_WFF487")"
  # The refresher/install steps are gated on DEVFLOW_APP_ID (unconfigured no-op).
  assert_eq "#487 wiring: $_wf487.yml refresher start is gated on vars.DEVFLOW_APP_ID" "1" \
    "$(printf '%s\n' "$(mint_blk 'Start credential refresher (optional)' "$_WFF487")" | grep -cF "vars.DEVFLOW_APP_ID != ''")"
  # The install step delegates its whole body to the checked-in seven-output
  # installer (issue #533) — the fingerprint write and GITHUB_PATH prepend now
  # live in scripts/install-gh-wrapper.sh, pinned below outside this loop.
  assert_eq "#533 wiring: $_wf487.yml install step invokes the vendored install-gh-wrapper.sh" "1" \
    "$(printf '%s\n' "$(mint_blk 'Install fresh-gh wrapper (optional)' "$_WFF487")" | grep -cF '.prflow/vendor/prflow/scripts/install-gh-wrapper.sh')"
  # AC10 (issue #533): the install step must NOT export a process-global DEVFLOW_GH —
  # GITHUB_ENV values persist into every later job step, where a non-empty DEVFLOW_GH
  # outranks fixture PATH stubs by resolver design. Wrapper selection is PATH-scoped.
  assert_eq "#533 AC10: $_wf487.yml install step no longer exports DEVFLOW_GH to GITHUB_ENV" "0" \
    "$(printf '%s\n' "$(mint_blk 'Install fresh-gh wrapper (optional)' "$_WFF487")" | grep -cF 'DEVFLOW_GH=')"
  # ── Step ORDERING (PR #491 Suggestion 2): load-bearing but previously unpinned.
  # (a) The refresher and the wrapper install must both precede the claude step, so the
  # agent's >60-min run is already push-/gh-fresh from the start; a reordering that put
  # either after the agent step would leave the run unprotected yet still pass the
  # presence pins above. Compare 1-indexed line numbers within the workflow file.
  _claude_ln="$(grep -nF 'name: Run Claude Code' "$_WFF487" | head -1 | cut -d: -f1)"
  _start_ln="$(grep -nF 'name: Start credential refresher (optional)' "$_WFF487" | head -1 | cut -d: -f1)"
  _inst_ln="$(grep -nF 'name: Install fresh-gh wrapper (optional)' "$_WFF487" | head -1 | cut -d: -f1)"
  assert_eq "#487 wiring: $_wf487.yml starts the refresher BEFORE the claude step" "yes" \
    "$([ -n "$_start_ln" ] && [ -n "$_claude_ln" ] && [ "$_start_ln" -lt "$_claude_ln" ] && echo yes || echo no)"
  assert_eq "#487 wiring: $_wf487.yml installs the fresh-gh wrapper BEFORE the claude step" "yes" \
    "$([ -n "$_inst_ln" ] && [ -n "$_claude_ln" ] && [ "$_inst_ln" -lt "$_claude_ln" ] && echo yes || echo no)"
  # (a2) The refresher must also start AFTER checkout (PR #491 IMP-4): the refresher
  # rewrites the checkout-PERSISTED http.*/.extraheader credential, so that credential
  # must already exist when the first cycle fires. A reorder that put Start above the
  # checkout would leave the first cycle with nothing to rewrite yet still pass the
  # before-claude pins above. Pin `checkout < start`.
  _checkout_ln="$(grep -nF 'name: Checkout repository' "$_WFF487" | head -1 | cut -d: -f1)"
  assert_eq "#491 wiring: $_wf487.yml starts the refresher AFTER checkout (the persisted extraheader must exist to rewrite)" "yes" \
    "$([ -n "$_checkout_ln" ] && [ -n "$_start_ln" ] && [ "$_checkout_ln" -lt "$_start_ln" ] && echo yes || echo no)"
done
# (b) Intra-step ordering, relocated to the installer (issue #533): the real gh's
# ABSOLUTE path must be resolved BEFORE the wrapper dir is appended to GITHUB_PATH —
# otherwise a later name-based `gh` lookup recurses into the wrapper. The install
# step body now lives once in scripts/install-gh-wrapper.sh, so pin the order there.
INSTALL533="$LIB/../scripts/install-gh-wrapper.sh"
_cap_ln533="$(grep -nF 'REAL_GH="$(command -v gh' "$INSTALL533" 2>/dev/null | head -1 | cut -d: -f1)"
_path_ln533="$(grep -nF '>> "$GITHUB_PATH"' "$INSTALL533" 2>/dev/null | head -1 | cut -d: -f1)"
assert_eq "#487 wiring: install-gh-wrapper.sh resolves the real gh before prepending the wrapper to GITHUB_PATH" "yes" \
  "$([ -n "$_cap_ln533" ] && [ -n "$_path_ln533" ] && [ "$_cap_ln533" -lt "$_path_ln533" ] && echo yes || echo no)"
# devflow.yml's gate additionally excludes /devflow:review (read-only, never pushes).
assert_eq "#487 wiring: devflow.yml refresher start excludes /devflow:review commands" "1" \
  "$(printf '%s\n' "$(mint_blk 'Start credential refresher (optional)' "$WF/devflow.yml")" | grep -cF "!startsWith(needs.gate.outputs.command, '/prflow:review ')")"
# The Stop step's review-exclusion ASYMMETRY keeps the Stop gate symmetric with Start:
# devflow.yml's Stop step MUST carry the /devflow:review negation (on the review path the
# refresher was never started, so the step would be a pointless no-op; a false defeat
# warning there is prevented by the DEVFLOW_REFRESH_STARTED=skipped guard — arm17 — not
# by this exclusion), while devflow-implement.yml's Stop step must NOT carry it (it
# always starts the refresher). Pin both directions so a dropped or mis-copied gate goes RED.
assert_eq "#487 wiring: devflow.yml Stop step carries the /devflow:review exclusion" "1" \
  "$(printf '%s\n' "$(mint_blk 'Stop credential refresher (optional)' "$WF/devflow.yml")" | grep -cF "!startsWith(needs.gate.outputs.command, '/prflow:review ')")"
assert_eq "#487 wiring: devflow-implement.yml Stop step does NOT carry a /devflow:review exclusion" "0" \
  "$(printf '%s\n' "$(mint_blk 'Stop credential refresher (optional)' "$WF/devflow-implement.yml")" | grep -cF "/devflow:review")"
# Both Stop steps pass the Start step's outcome so stop-refresher.sh can tell a genuine
# never-started defeat from an upstream early-abort (absent pidfile is expected there).
assert_eq "#487 wiring: devflow.yml Stop step passes steps.refresher.outcome as DEVFLOW_REFRESH_STARTED" "1" \
  "$(printf '%s\n' "$(mint_blk 'Stop credential refresher (optional)' "$WF/devflow.yml")" | grep -cF 'DEVFLOW_REFRESH_STARTED: ${{ steps.refresher.outcome }}')"
assert_eq "#487 wiring: devflow-implement.yml Stop step passes steps.refresher.outcome as DEVFLOW_REFRESH_STARTED" "1" \
  "$(printf '%s\n' "$(mint_blk 'Stop credential refresher (optional)' "$WF/devflow-implement.yml")" | grep -cF 'DEVFLOW_REFRESH_STARTED: ${{ steps.refresher.outcome }}')"
# Coupled literal: the refresher EMITS `cycle OK` and stop-refresher.sh MATCHES it to tell
# a recovered transient from a sustained failure — a reworded producer breadcrumb would
# silently break the consumer's discrimination. Pin the shared marker in both files.
assert_eq "#487 coupled-literal: refresh-app-credentials.sh emits the 'cycle OK' success marker" "1" \
  "$(grep -cF "printf 'refresh-app-credentials: cycle OK" "$LIB/../scripts/refresh-app-credentials.sh")"
assert_eq "#487 coupled-literal: stop-refresher.sh matches the 'cycle OK' marker in its operative case arm" "1" \
  "$(grep -cF '*"cycle OK"*)' "$LIB/../scripts/stop-refresher.sh")"

# ── #491 coupled production-DEFAULT paths (shadow Finding A). Each credential surface is
# written by one file and read by another, and the workflows pass NO override — production
# works ONLY because two independently-defaulted RUNNER_TEMP/<basename> literals agree. Every
# test arm injects matching DEVFLOW_* overrides on both sides, so a one-sided rename of a
# DEFAULT ships green (gh-fresh reads no token / never matches the fingerprint, stop-refresher
# false-fires a defeat). Pin the default BASENAMES agree across writer<->reader — the same
# coupled-literal hazard as the 'cycle OK' marker above, one level down in the wiring.
# Extract-and-compare (not substring grep) so a suffix-append rename is caught too.
_dfbn() { grep -E "$2" "$1" 2>/dev/null | grep -oE 'devflow-[a-zA-Z0-9._-]+' | head -1; }
_w_tok491="$(_dfbn "$LIB/../scripts/refresh-app-credentials.sh" '^TOKEN_FILE=')"
_r_tok491="$(_dfbn "$LIB/../scripts/gh-fresh.sh" '^TOKEN_FILE=')"
assert_eq "#491 coupled-default: token-file default basename agrees (refresh-app-credentials.sh writer <-> gh-fresh.sh reader) [$_w_tok491]" "yes" \
  "$([ -n "$_w_tok491" ] && [ "$_w_tok491" = "$_r_tok491" ] && echo yes || echo no)"
_w_pid491="$(_dfbn "$LIB/../scripts/refresh-app-credentials.sh" '^PIDFILE=')"
_r_pid491="$(_dfbn "$LIB/../scripts/stop-refresher.sh" '^PIDFILE=')"
assert_eq "#491 coupled-default: pidfile default basename agrees (refresh-app-credentials.sh writer <-> stop-refresher.sh reader) [$_w_pid491]" "yes" \
  "$([ -n "$_w_pid491" ] && [ "$_w_pid491" = "$_r_pid491" ] && echo yes || echo no)"
# fingerprint + log defaults are written by the WORKFLOWS (redirect / install-step write) and
# read by gh-fresh.sh / stop-refresher.sh. Assert each reader's default basename appears as an
# exact RUNNER_TEMP/<basename> token the workflow writes (space-bounded, so a suffix-append on
# either side breaks the match), in BOTH workflows.
_r_fp491="$(_dfbn "$LIB/../scripts/gh-fresh.sh" '^FINGERPRINT_FILE=')"
# The fingerprint WRITER moved from the two workflow YAML bodies into the single
# checked-in installer (issue #533) — compare the writer/reader DEFAULTS directly,
# the same extract-and-compare shape as the token-file/pidfile pins above.
_w_fp533="$(_dfbn "$INSTALL533" '^FINGERPRINT_FILE=')"
assert_eq "#491 coupled-default: fingerprint default basename agrees (install-gh-wrapper.sh writer <-> gh-fresh.sh reader) [$_w_fp533]" "yes" \
  "$([ -n "$_w_fp533" ] && [ "$_w_fp533" = "$_r_fp491" ] && echo yes || echo no)"
# The log path is now job-scoped and passed EXPLICITLY from the Start step to the
# teardown via GITHUB_ENV (issue #1882) — its producer is the workflow redirect and
# its consumer is stop-refresher.sh's DEVFLOW_REFRESH_LOG default, two separately-
# upgrading artifacts, so a basename-agreement pin no longer applies. Pin the
# explicit-passing contract instead: the Start step publishes DEVFLOW_REFRESH_LOG.
for _wf491 in devflow-implement devflow; do
  assert_eq "#1882 explicit-log: $_wf491.yml Start step publishes DEVFLOW_REFRESH_LOG to GITHUB_ENV (job-scoped log passed to the teardown, not inferred)" "1" \
    "$(printf '%s\n' "$(mint_blk 'Start credential refresher (optional)' "$WF/$_wf491.yml")" | grep -cF 'DEVFLOW_REFRESH_LOG=')"
done

# ── #1882 pre-launch self-test wiring. Each writer workflow's Start step runs the
# refresher self-test (signer helper) with the key on stdin BEFORE the detached
# launch; a signing fault fails the job at the gate. Pin the wiring in
# devflow-implement.yml and devflow.yml.
for _wf1882 in devflow-implement devflow; do
  _WFF1882="$WF/$_wf1882.yml"
  _startblk1882="$(mint_blk 'Start credential refresher (optional)' "$_WFF1882")"
  assert_eq "#1882 self-test: $_wf1882.yml Start step invokes the vendored refresher-selftest.sh" "1" \
    "$(printf '%s\n' "$_startblk1882" | grep -cF '.prflow/vendor/prflow/scripts/refresher-selftest.sh')"
  # The self-test runs BEFORE the detached loop launch, so a host that cannot sign
  # is loud before the agent starts rather than after the token's hour.
  _selftest_ln1882="$(printf '%s\n' "$_startblk1882" | grep -nF 'refresher-selftest.sh' | head -1 | cut -d: -f1)"
  _nohup_ln1882="$(printf '%s\n' "$_startblk1882" | grep -nF 'nohup bash .prflow/vendor/prflow/scripts/refresh-app-credentials.sh loop' | head -1 | cut -d: -f1)"
  assert_eq "#1882 self-test: $_wf1882.yml runs the self-test BEFORE the detached launch" "yes" \
    "$([ -n "$_selftest_ln1882" ] && [ -n "$_nohup_ln1882" ] && [ "$_selftest_ln1882" -lt "$_nohup_ln1882" ] && echo yes || echo no)"
  # Job-scoped token file + pidfile are published to GITHUB_ENV so a later job on the
  # same runner never reads or retires this job's token file / pidfile / log.
  assert_eq "#1882 job-scope: $_wf1882.yml Start step publishes a job-scoped DEVFLOW_GH_TOKEN_FILE to GITHUB_ENV" "1" \
    "$(printf '%s\n' "$_startblk1882" | grep -cF 'DEVFLOW_GH_TOKEN_FILE=$TOK')"
  assert_eq "#1882 job-scope: $_wf1882.yml Start step publishes a job-scoped DEVFLOW_REFRESH_PIDFILE to GITHUB_ENV" "1" \
    "$(printf '%s\n' "$_startblk1882" | grep -cF 'DEVFLOW_REFRESH_PIDFILE=$PID')"
  # The loop is launched with the job pointer so it can retire itself once its job is
  # no longer the runner's current one.
  assert_eq "#1882 job-scope: $_wf1882.yml launches the loop with DEVFLOW_REFRESH_JOB_ID + DEVFLOW_REFRESH_JOB_POINTER" "1 1" \
    "$(printf '%s\n' "$_startblk1882" | grep -cF 'DEVFLOW_REFRESH_JOB_ID=') $(printf '%s\n' "$_startblk1882" | grep -cF 'DEVFLOW_REFRESH_JOB_POINTER=$PTR')"
done

# Fail-fast prose rule (surface-presence class, per the issue's Testing Strategy): the
# two-strikes bad-credential rule is present in both skill files. Pinned via
# devflow_module_pin_unique (the sanctioned unique-literal guard, not a raw echo-driven grep).
devflow_module_pin_unique "#487 fail-fast prose: skills/implement/SKILL.md carries the expired-credential two-strikes rule" \
  'Expired-credential fail-fast (two strikes' "$LIB/../skills/implement/SKILL.md"
devflow_module_pin_unique "#487 fail-fast prose: review-and-fix loop-control reference carries the expired-credential two-strikes rule" \
  'Expired-credential fail-fast (two strikes' "$LIB/../skills/review-and-fix/references/loop-control.md"
# The compaction-immune sibling signal (the wrapper diagnostic literal) is named in the prose.
devflow_module_pin_unique "#487 fail-fast prose: implement rule names the gh-fresh.sh diagnostic sibling" \
  'devflow-gh-fresh' "$LIB/../skills/implement/SKILL.md"

# (2) Refresh/cleanup steps — the detached credential refresher (issue #487) is
# retired on EVERY exit path. The existing #487 wiring pin asserts the Stop step
# EXISTS; this pins the always() guard that makes cleanup run even when the claude
# step failed/cancelled. Dropping always() leaks the background refresher.
_ac21_stopblk="$(mint_blk 'Stop credential refresher (optional)' "$WF/devflow-implement.yml")"
assert_eq "#599 AC21(2) refresh/cleanup steps: devflow-implement.yml Stop step is always()-guarded (retires the refresher on every exit path)" "1" \
  "$(printf '%s\n' "$_ac21_stopblk" | grep -cF 'if: ${{ always() && ')"

# Precise checkout-step extraction (NOT mint_blk, which exits only on the next
# `- name:` step and would over-span the runner's `- id:`-only follow-on steps):
# print from the checkout step name until the next 6-space step boundary.
_ac21_coblk="$(awk '
    index($0, "- name: Checkout repository"){f=1; print; next}
    f && /^      - /{exit}
    f{print}' "$WF/devflow-runner.yml")"
# Fail CLOSED: require the checkout step to be FOUND (carries actions/checkout@) AND
# to carry no reviewer-token. If the step is ever renamed the extraction goes empty,
# which must read as RED (a missed check), not a vacuous pass on a zero count.
assert_eq "#599 AC21(5b) direct-review identity split: devflow-runner.yml checkout step is present and never consumes the read-only reviewer token (it is not a write/checkout credential)" "yes" \
  "$(printf '%s\n' "$_ac21_coblk" | grep -qF 'actions/checkout@' && ! printf '%s\n' "$_ac21_coblk" | grep -qF 'reviewer-token' && echo yes || echo no)"

# ── issue #533: workflow CLI scoping — single validated installer, PATH-scoped
# wrapper selection, no process-global DEVFLOW_GH, harness isolation ──────────

# AC14 — the checked-in installer exists and fingerprints via python3 hashlib
# (preflight-guaranteed), never sha256sum/shasum/awk (not PATH-guaranteed on the
# runner; a silent absence would ship an empty fingerprint — guard-class 2).
assert_eq "#533 AC14: scripts/install-gh-wrapper.sh exists" "yes" \
  "$([ -f "$INSTALL533" ] && echo yes || echo no)"
assert_eq "#533 AC14: installer fingerprints via python3 hashlib and never invokes sha256sum/shasum/awk" "yes" \
  "$(grep -vE '^[[:space:]]*#' "$INSTALL533" 2>/dev/null | grep -qF 'hashlib' && ! grep -vE '^[[:space:]]*#' "$INSTALL533" | grep -qE 'sha256sum|shasum|awk' && echo yes || echo no)"
# The AC10 guard's counting recipe lives in ONE function so the AC22 mutation
# proof below exercises the same recipe the guard runs — never a hand copy that
# could drift green while the real guard's pattern rots.
# The `2>/dev/null` below hides grep's own missing-file error, and BOTH counters feed
# assertions whose expected value is `0` — so an absent or renamed target would read as
# "the file is clean" rather than "the file was never read". Guard readability first and
# emit a non-numeric sentinel, so the assert_eq goes RED naming the cause (issue #695
# review): unknown is not zero.
_ac10_count533() { [ -r "$1" ] || { printf 'UNREADABLE:%s\n' "$1"; return; }; grep -cF 'DEVFLOW_GH=' "$1" 2>/dev/null; }
# Whole-workflow sibling: counts process-global DEVFLOW_GH assignments anywhere
# in a file — shell '=' or YAML env ':' form — with whole-line comments stripped.
_ac10_wf_count533() { [ -r "$1" ] || { printf 'UNREADABLE:%s\n' "$1"; return; }; grep -vE '^[[:space:]]*#' "$1" 2>/dev/null | grep -cE 'DEVFLOW_GH[=:]'; }
# The AC9 (#1925) counter: the self-test marker path must not be PUBLISHED job-wide into $GITHUB_ENV
# (the fixture-stub-outranking hazard the DEVFLOW_GH check guards). Both job-wide publication forms
# stay counted — the shell `echo "NAME=` redirect AND a YAML `env:` `NAME:` entry: matching only the
# shell form would leave a re-introduced job-level env: block green, recreating the hazard. Comments
# stripped; the Stop step's in-body `export NAME=` is not a publication and is not matched.
_ac1925_pub_count() { [ -r "$1" ] || { printf 'UNREADABLE:%s\n' "$1"; return; }; grep -vE '^[[:space:]]*#' "$1" 2>/dev/null | grep -cE '(echo "DEVFLOW_REFRESH_SELFTEST_FAILED=|^[[:space:]]*DEVFLOW_REFRESH_SELFTEST_FAILED:)'; }
assert_eq "#533 AC10: install-gh-wrapper.sh writes no bare DEVFLOW_GH= (only DEVFLOW_GH_REAL=)" "0" \
  "$(_ac10_count533 "$INSTALL533")"

# AC17 — the install step stays gated on DEVFLOW_APP_ID in both writer workflows
# (zero-App jobs never install the wrapper; bare-gh/token behavior is untouched).
for _wf533 in devflow-implement devflow; do
  assert_eq "#533 AC17: $_wf533.yml install step is gated on vars.DEVFLOW_APP_ID" "1" \
    "$(printf '%s\n' "$(mint_blk 'Install fresh-gh wrapper (optional)' "$WF/$_wf533.yml")" | grep -cF "vars.DEVFLOW_APP_ID != ''")"
  # AC10 whole-workflow guard: no process-global DEVFLOW_GH assignment ANYWHERE
  # in the file — shell '=' or YAML env ':' form alike (a re-introduction in the
  # claude step's env: block would re-break fixture PATH stubs exactly like the
  # original defect, and the install-step-scoped guard above cannot see it).
  # DEVFLOW_GH_REAL / DEVFLOW_GH_WRAPDIR carry an underscore after GH, so the
  # [=:] delimiter regex skips them; whole-line comments are stripped so prose
  # mentioning the retired export cannot false-fire. The recipe lives in ONE
  # function so the positive controls below exercise the same recipe the guard
  # runs (a hand-copied grep could drift green while the guard's pattern rots).
  assert_eq "#533 AC10: $_wf533.yml carries no process-global DEVFLOW_GH assignment anywhere (= or : form, comments stripped)" "0" \
    "$(_ac10_wf_count533 "$WF/$_wf533.yml")"
  # The installer reads the token from the APP_TOKEN env value — the step must
  # keep passing it in its env: block, or output 5 fails on every App-enabled run.
  assert_eq "#533 AC14: $_wf533.yml install step passes APP_TOKEN in its env: block" "1" \
    "$(printf '%s\n' "$(mint_blk 'Install fresh-gh wrapper (optional)' "$WF/$_wf533.yml")" | grep -cF 'APP_TOKEN: ${{ steps.app-token.outputs.token }}')"
  # AC9 (#1925): the self-test marker path is no longer published job-wide anywhere in the
  # file (the fixture-stub-outranking hazard the DEVFLOW_GH check guards).
  assert_eq "#1925 AC9: $_wf533.yml publishes no DEVFLOW_REFRESH_SELFTEST_FAILED to \$GITHUB_ENV (count 0)" "0" \
    "$(_ac1925_pub_count "$WF/$_wf533.yml")"
  # AC10 (#1925): the Stop step derives the marker path in its OWN body, from the same HANDLE
  # the Start step uses, replacing the retired job-wide publication.
  # structural-pin-ok: cross-file-phase-contract -- the Stop step's self-derivation is the cross-step contract that replaced the retired job-wide publication; it pins a machine-consumed boundary (the env var stop-refresher.sh reads), not prose.
  assert_eq "#1925 AC10: $_wf533.yml Stop step derives DEVFLOW_REFRESH_SELFTEST_FAILED from HANDLE in its own body" "1" \
    "$(printf '%s\n' "$(mint_blk 'Stop credential refresher (optional)' "$WF/$_wf533.yml")" | grep -cF 'export DEVFLOW_REFRESH_SELFTEST_FAILED="$RUNNER_TEMP/devflow-refresh-$HANDLE.selftest-failed"')"
  # AC10 (#1925): the Stop step now re-derives HANDLE independently, so its marker path diverges
  # from the Start step's — silently breaking the #1882 signing-fault attribution — if a one-sided
  # edit changes one HANDLE formula and not the other. Require the identical formula in both steps.
  # structural-pin-ok: cross-file-phase-contract -- Start<->Stop HANDLE equality is the cross-step contract the retired job-wide publication used to guarantee; a machine-consumed boundary (the derived marker path), not prose.
  assert_eq "#1925 AC10: $_wf533.yml Start and Stop steps both derive HANDLE with the identical formula" "1 1" \
    "$(printf '%s\n' "$(mint_blk 'Start credential refresher (optional)' "$WF/$_wf533.yml")" | grep -cF 'HANDLE="${GITHUB_RUN_ID:-0}-${GITHUB_RUN_ATTEMPT:-0}-${GITHUB_JOB:-job}"') $(printf '%s\n' "$(mint_blk 'Stop credential refresher (optional)' "$WF/$_wf533.yml")" | grep -cF 'HANDLE="${GITHUB_RUN_ID:-0}-${GITHUB_RUN_ATTEMPT:-0}-${GITHUB_JOB:-job}"')"
done
# Positive controls for the whole-file recipe: a regex typo must not leave the
# guard green forever. Plant each re-introduction shape in a scratch fixture and
# assert the SAME recipe fires (1), and that a comment-only mention stays 0.
_t533k="$(probe_tmp '#533 AC10 whole-file guard positive control setup')"
printf 'jobs:\n  claude:\n    env:\n      DEVFLOW_GH: leaked\n' > "$_t533k"
assert_eq "#533 AC22: the whole-file AC10 recipe fires on a planted YAML env DEVFLOW_GH: entry" "1" "$(_ac10_wf_count533 "$_t533k")"
printf '          echo "DEVFLOW_GH=$WRAPDIR/gh" >> "$GITHUB_ENV"\n' > "$_t533k"
assert_eq "#533 AC22: the whole-file AC10 recipe fires on a planted shell DEVFLOW_GH= export (the original defect form)" "1" "$(_ac10_wf_count533 "$_t533k")"
printf '      # prose mentioning DEVFLOW_GH=old-export never fires the guard\n' > "$_t533k"
assert_eq "#533 AC22: the whole-file AC10 recipe stays 0 on a whole-line comment mention" "0" "$(_ac10_wf_count533 "$_t533k")"
rm -f "$_t533k"
# Positive controls for the #1925 publication recipe: a planted publication fires (1), a
# whole-line comment mention stays 0 — so a quoting/regex typo cannot leave the guard green.
_t1925k="$(probe_tmp '#1925 AC9 self-test-marker publication guard positive control setup')"
printf '          {\n            echo "DEVFLOW_REFRESH_SELFTEST_FAILED=$STMARK"\n          } >> "$GITHUB_ENV"\n' > "$_t1925k"
assert_eq "#1925 AC9: the publication recipe fires on a planted DEVFLOW_REFRESH_SELFTEST_FAILED publication" "1" "$(_ac1925_pub_count "$_t1925k")"
printf 'jobs:\n  claude:\n    env:\n      DEVFLOW_REFRESH_SELFTEST_FAILED: /tmp/leaked\n' > "$_t1925k"
assert_eq "#1925 AC9: the publication recipe fires on a planted YAML env DEVFLOW_REFRESH_SELFTEST_FAILED: entry" "1" "$(_ac1925_pub_count "$_t1925k")"
printf '          export DEVFLOW_REFRESH_SELFTEST_FAILED="$RUNNER_TEMP/devflow-refresh-$HANDLE.selftest-failed"\n' > "$_t1925k"
assert_eq "#1925 AC9: the publication recipe stays 0 on the Stop step in-body export (self-derivation is not publication)" "0" "$(_ac1925_pub_count "$_t1925k")"
printf '          # echo "DEVFLOW_REFRESH_SELFTEST_FAILED=$STMARK" (retired publication, mentioned only in prose)\n' > "$_t1925k"
assert_eq "#1925 AC9: the publication recipe stays 0 on a whole-line comment mention" "0" "$(_ac1925_pub_count "$_t1925k")"
rm -f "$_t1925k"

# AC14 — the seven validated outputs: each induced failure exits 1 with a
# diagnostic naming that output; the full-success arm lands all seven.
D533="$(mktemp -d "$_iw_tmp_root/d533.XXXXXX")" || {
  echo FAIL >> "$RESULTS_FILE"
  record_fail "#533 AC14 fixture root — mktemp -d failed"
  printf '  FAIL  #533 AC14 fixture root — mktemp -d failed; the installer arms cannot run\n' >&2
  D533=/dev/null/unallocated-d533
}
# The real-gh capture is steered through a PATH stub — the same seam production
# uses — never a bypass branch in the installer itself.
mkdir -p "$D533/bin" "$D533/rtmp" "$D533/emptybin"
printf '#!/usr/bin/env bash\necho "REALGH_CALLED $*"\n' > "$D533/bin/gh"; chmod +x "$D533/bin/gh"
: > "$D533/ghenv"; : > "$D533/ghpath"
# The success fixture env, held in ONE place so every runner below (_i533 and the
# #690 stderr-only sibling _i690) shares it. A new installer env seam is added
# here once, rather than in two blocks ~120 lines apart where the second would
# silently keep running against a stale environment and still pass.
_ENV533=(PATH="$D533/bin:$PATH" DEVFLOW_GH_SOURCE_SH="$LIB/../scripts/gh-fresh.sh"
         APP_TOKEN=FIXTURE_TOKEN_533 RUNNER_TEMP="$D533/rtmp" GITHUB_ENV="$D533/ghenv" GITHUB_PATH="$D533/ghpath"
         DEVFLOW_GH_WRAPDIR="$D533/wrapdir" DEVFLOW_GH_FINGERPRINT_FILE="$D533/rtmp/devflow-gh-fingerprint")
_i533() {  # run the installer with the success fixture env, overriding via "$@"
  env "${_ENV533[@]}" "$@" bash "$INSTALL533" 2>&1
}
# output 1: no executable real gh (gh-less PATH).
_o533_1="$(env APP_TOKEN=t GITHUB_ENV="$D533/ghenv" GITHUB_PATH="$D533/ghpath" \
  RUNNER_TEMP="$D533/rtmp" PATH="$D533/emptybin" "$BASH" "$INSTALL533" 2>&1)"; _rc533_1=$?
assert_eq "#533 AC14 output 1: missing real gh fails rc 1 naming real-gh-resolve" "1 yes" \
  "$_rc533_1 $(printf '%s' "$_o533_1" | grep -qF 'output 1/7 FAILED' && printf '%s' "$_o533_1" | grep -qF '(real-gh-resolve)' && echo yes || echo no)"
# output 2: unreadable wrapper source.
_o533_2="$(_i533 DEVFLOW_GH_SOURCE_SH="$D533/missing-src")"; _rc533_2=$?
assert_eq "#533 AC14 output 2: unreadable wrapper source fails rc 1 naming wrapper-source-read" "1 yes" \
  "$_rc533_2 $(printf '%s' "$_o533_2" | grep -qF 'output 2/7 FAILED' && printf '%s' "$_o533_2" | grep -qF '(wrapper-source-read)' && echo yes || echo no)"
# output 3: wrapper dir blocked by a regular file on its parent path.
: > "$D533/blockfile"
_o533_3="$(_i533 DEVFLOW_GH_WRAPDIR="$D533/blockfile/sub")"; _rc533_3=$?
assert_eq "#533 AC14 output 3: uncreatable wrapper dir fails rc 1 naming wrapdir-create" "1 yes" \
  "$_rc533_3 $(printf '%s' "$_o533_3" | grep -qF 'output 3/7 FAILED' && printf '%s' "$_o533_3" | grep -qF '(wrapdir-create)' && echo yes || echo no)"
# output 4: copy target occupied by a directory named gh.
mkdir -p "$D533/wd4/gh"
_o533_4="$(_i533 DEVFLOW_GH_WRAPDIR="$D533/wd4")"; _rc533_4=$?
assert_eq "#533 AC14 output 4: failed wrapper copy fails rc 1 naming wrapper-copy-exec" "1 yes" \
  "$_rc533_4 $(printf '%s' "$_o533_4" | grep -qF 'output 4/7 FAILED' && printf '%s' "$_o533_4" | grep -qF '(wrapper-copy-exec)' && echo yes || echo no)"
# output 5a: empty APP_TOKEN (nothing to fingerprint).
_o533_5a="$(_i533 APP_TOKEN=)"; _rc533_5a=$?
assert_eq "#533 AC14 output 5: empty APP_TOKEN fails rc 1 naming fingerprint-compute" "1 yes" \
  "$_rc533_5a $(printf '%s' "$_o533_5a" | grep -qF 'output 5/7 FAILED' && printf '%s' "$_o533_5a" | grep -qF '(fingerprint-compute)' && echo yes || echo no)"
# output 5b: python3 itself failing (shadowed by a failing stub).
mkdir -p "$D533/badpy"
printf '#!/usr/bin/env bash\nexit 1\n' > "$D533/badpy/python3"; chmod +x "$D533/badpy/python3"
_o533_5b="$(_i533 PATH="$D533/badpy:$D533/bin:$PATH")"; _rc533_5b=$?
assert_eq "#533 AC14 output 5: a failing python3 fails rc 1 naming fingerprint-compute" "1 yes" \
  "$_rc533_5b $(printf '%s' "$_o533_5b" | grep -qF 'output 5/7 FAILED' && printf '%s' "$_o533_5b" | grep -qF '(fingerprint-compute)' && echo yes || echo no)"
# output 5c: python3 runs, exits 0, but writes NOTHING — the [ -s ] non-empty
# guard is what catches it (fingerprint-nonempty), distinct from a crash (5b).
mkdir -p "$D533/emptypy"
printf '#!/usr/bin/env bash\nexit 0\n' > "$D533/emptypy/python3"; chmod +x "$D533/emptypy/python3"
rm -f "$D533/rtmp/devflow-gh-fingerprint"
_o533_5c="$(_i533 PATH="$D533/emptypy:$D533/bin:$PATH")"; _rc533_5c=$?
assert_eq "#533 AC14 output 5: a python3 that succeeds writing nothing fails rc 1 naming fingerprint-nonempty" "1 yes" \
  "$_rc533_5c $(printf '%s' "$_o533_5c" | grep -qF 'output 5/7 FAILED' && printf '%s' "$_o533_5c" | grep -qF '(fingerprint-nonempty)' && echo yes || echo no)"
# outputs 3 & 5, RUNNER_TEMP-unset fail-closed branches: with no RUNNER_TEMP and
# no matching override the guard must fire the NAMED diagnostic, never a bash
# unbound-variable abort (the set -u escape the fail-closed contract forbids).
_o533_3b="$(env -u RUNNER_TEMP PATH="$D533/bin:$PATH" DEVFLOW_GH_SOURCE_SH="$LIB/../scripts/gh-fresh.sh" \
  APP_TOKEN=t GITHUB_ENV="$D533/ghenv" GITHUB_PATH="$D533/ghpath" bash "$INSTALL533" 2>&1)"; _rc533_3b=$?
assert_eq "#533 AC14 output 3: RUNNER_TEMP unset with no WRAPDIR override fails rc 1 naming wrapdir-create (no set -u abort)" "1 yes" \
  "$_rc533_3b $(printf '%s' "$_o533_3b" | grep -qF 'output 3/7 FAILED' && printf '%s' "$_o533_3b" | grep -qF '(wrapdir-create)' && echo yes || echo no)"
_o533_5d="$(env -u RUNNER_TEMP PATH="$D533/bin:$PATH" DEVFLOW_GH_SOURCE_SH="$LIB/../scripts/gh-fresh.sh" \
  APP_TOKEN=t GITHUB_ENV="$D533/ghenv" GITHUB_PATH="$D533/ghpath" DEVFLOW_GH_WRAPDIR="$D533/wrapdir-rt" bash "$INSTALL533" 2>&1)"; _rc533_5d=$?
assert_eq "#533 AC14 output 5: RUNNER_TEMP unset with no FINGERPRINT override fails rc 1 naming fingerprint-compute (no set -u abort)" "1 yes" \
  "$_rc533_5d $(printf '%s' "$_o533_5d" | grep -qF 'output 5/7 FAILED' && printf '%s' "$_o533_5d" | grep -qF '(fingerprint-compute)' && echo yes || echo no)"
# output 2 via the PRODUCTION default chain: from a tree root carrying NEITHER a
# vendored nor a repo-relative gh-fresh.sh, the default source lookup fails
# closed with the named diagnostic (the override-driven arm above cannot see a
# broken default chain).
mkdir -p "$D533/tree0"
_o533_2b="$( cd "$D533/tree0" && env PATH="$D533/bin:$PATH" APP_TOKEN=t RUNNER_TEMP="$D533/rtmp" \
  GITHUB_ENV="$D533/ghenv" GITHUB_PATH="$D533/ghpath" DEVFLOW_GH_WRAPDIR="$D533/wrapdir-t0" bash "$INSTALL533" 2>&1 )"; _rc533_2b=$?
assert_eq "#533 AC14 output 2: the production default source chain fails rc 1 naming wrapper-source-read when neither copy exists" "1 yes" \
  "$_rc533_2b $(printf '%s' "$_o533_2b" | grep -qF 'output 2/7 FAILED' && printf '%s' "$_o533_2b" | grep -qF '(wrapper-source-read)' && echo yes || echo no)"
# output 6: GITHUB_ENV pointing into a nonexistent directory.
_o533_6="$(_i533 GITHUB_ENV="$D533/no-such-dir/ghenv")"; _rc533_6=$?
assert_eq "#533 AC14 output 6: unwritable GITHUB_ENV fails rc 1 naming github-env-write" "1 yes" \
  "$_rc533_6 $(printf '%s' "$_o533_6" | grep -qF 'output 6/7 FAILED' && printf '%s' "$_o533_6" | grep -qF '(github-env-write)' && echo yes || echo no)"
# output 7: GITHUB_PATH pointing into a nonexistent directory.
_o533_7="$(_i533 GITHUB_PATH="$D533/no-such-dir/ghpath")"; _rc533_7=$?
assert_eq "#533 AC14 output 7: unwritable GITHUB_PATH fails rc 1 naming github-path-write" "1 yes" \
  "$_rc533_7 $(printf '%s' "$_o533_7" | grep -qF 'output 7/7 FAILED' && printf '%s' "$_o533_7" | grep -qF '(github-path-write)' && echo yes || echo no)"
# Full success — additionally on a PATH whose sha256sum/shasum/awk all FAIL, proving
# the installer's no-GNU-hash-tools contract behaviorally, not just by grep.
mkdir -p "$D533/noshabin"
for _t533 in sha256sum shasum awk; do
  printf '#!/usr/bin/env bash\nexit 127\n' > "$D533/noshabin/$_t533"; chmod +x "$D533/noshabin/$_t533"
done
: > "$D533/ghenv"; : > "$D533/ghpath"
_o533_ok="$(_i533 PATH="$D533/noshabin:$D533/bin:$PATH")"; _rc533_ok=$?
assert_eq "#533 AC14 success: all seven outputs land (rc 0) on a PATH without working sha256sum/shasum/awk" "0" "$_rc533_ok"
assert_eq "#533 AC10: on success GITHUB_ENV carries DEVFLOW_GH_REAL and no bare DEVFLOW_GH" "1 0" \
  "$(grep -cF "DEVFLOW_GH_REAL=$D533/bin/gh" "$D533/ghenv") $(grep -cF 'DEVFLOW_GH=' "$D533/ghenv")"
assert_eq "#533 AC10: on success GITHUB_PATH carries the wrapper dir" "1" "$(grep -cF "$D533/wrapdir" "$D533/ghpath")"
assert_eq "#533 AC14: installed wrapper is executable" "yes" "$([ -x "$D533/wrapdir/gh" ] && echo yes || echo no)"
_fp533_want="$(printf '%s' FIXTURE_TOKEN_533 | python3 -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')"
assert_eq "#533 AC14: fingerprint content is the python3-hashlib sha256 of APP_TOKEN" "$_fp533_want" \
  "$(cat "$D533/rtmp/devflow-gh-fingerprint")"
assert_eq "#533 AC14: fingerprint file is mode 0600" "600" \
  "$(python3 -c 'import os,sys; print(oct(os.stat(sys.argv[1]).st_mode & 0o777)[2:])' "$D533/rtmp/devflow-gh-fingerprint")"

# --- #690: output 5/7's fingerprint-mode gate is platform-aware --------------
# The shipped gate compared the mode to the literal 600 unconditionally, which a
# native-Windows python3 can never satisfy (st_mode's permission bits are
# synthesized from FILE_ATTRIBUTE_READONLY alone), so every Windows writer-tier
# run aborted at output 5/7 before the agent started. These assertions extend
# the #533 block and reuse its $D533 fixture rather than standing up a parallel
# one for the same script and the same output.
#
# The breadcrumb assertions run through _i690, a STDERR-ONLY capture sibling of
# _i533: _i533 ends 2>&1 and merges stderr into stdout, so through it an
# implementer emitting the breadcrumb to stdout would ship green, leaving the
# stream half of the criterion unasserted.
_py690="$(command -v python3)"
mkdir -p "$D533/py690"
_stub690() {  # $1 = the exact line the stubbed python3 prints for the os.name+mode probe
  printf '#!/usr/bin/env bash\ncase "$2" in *os.name*) printf "%%s\\n" "%s"; exit 0;; esac\nexec %s "$@"\n' \
    "$1" "$_py690" > "$D533/py690/python3"
  chmod +x "$D533/py690/python3"
}
_i690() {  # stdout discarded, stderr captured; $1 (optional) overrides the installer path
  rm -f "$D533/rtmp/devflow-gh-fingerprint"; : > "$D533/ghenv"; : > "$D533/ghpath"
  # Reuses _ENV533 (the shared fixture env), prepending the stubbed python3 to
  # PATH and giving these cases their own wrapper dir. It cannot simply call
  # _i533: that helper ends `2>&1`, merging stderr into stdout INSIDE the
  # function, so no outer redirection could recover a stderr-only capture.
  # SC2069: brace-group so stdout is discarded INSIDE the group and only the
  # installer's stderr survives on the group's stdout. Reordering to a trailing
  # `2>&1` would capture the OTHER stream and silently change every assertion
  # this stderr-only capture feeds.
  { env "${_ENV533[@]}" PATH="$D533/py690:$D533/bin:$PATH" DEVFLOW_GH_WRAPDIR="$D533/wrapdir690" \
      bash "${1:-$INSTALL533}" 1>/dev/null; } 2>&1
}
# Passing cases. posix+600 is the unchanged POSIX behavior; nt+666 and nt+444 are
# the two reachable Windows values, each additionally asserting the stderr
# breadcrumb and that the installer proceeded to outputs 6 and 7; the
# unrecognized token passes on the mode VALUE alone, never on the token.
_stub690 'posix 600'; _e690_p6="$(_i690)"; _rc690_p6=$?
assert_eq "#690: stubbed 'posix 600' passes output 5/7 (rc 0) and emits NO could-not-establish breadcrumb" "0 no" \
  "$_rc690_p6 $(printf '%s' "$_e690_p6" | grep -qF 'owner-only' && echo yes || echo no)"
_fp690_want="$(printf '%s' FIXTURE_TOKEN_533 | python3 -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')"
for _m690 in 666 444; do
  _stub690 "nt $_m690"; _e690_nt="$(_i690)"; _rc690_nt=$?
  assert_eq "#690: stubbed 'nt $_m690' passes output 5/7 (rc 0) and still writes GITHUB_ENV (output 6) and GITHUB_PATH (output 7)" "0 1 1" \
    "$_rc690_nt $(grep -cF "DEVFLOW_GH_REAL=$D533/bin/gh" "$D533/ghenv") $(grep -cF "$D533/wrapdir690" "$D533/ghpath")"
  # Relaxing the MODE gate must not relax the WRITE: a regression that skipped or
  # short-circuited the fingerprint write on this arm would otherwise stay green
  # on the rc/GITHUB_ENV assertions alone (the #533 AC14 content assertion runs
  # only on the strict posix path, against a different wrapdir).
  assert_eq "#690: stubbed 'nt $_m690' still leaves the correct python3-hashlib sha256 fingerprint on disk" "$_fp690_want" \
    "$(cat "$D533/rtmp/devflow-gh-fingerprint" 2>/dev/null)"
  # The breadcrumb: install-gh-wrapper:-prefixed, on STDERR, naming the observed
  # mode value and stating that access is left to the filesystem's ACLs, which
  # this script neither sets nor verifies.
  assert_eq "#690: stubbed 'nt $_m690' writes the install-gh-wrapper: could-not-establish breadcrumb to STDERR, naming mode $_m690 and the ACL caveat" "yes" \
    "$(printf '%s' "$_e690_nt" | grep -qF 'install-gh-wrapper: the owner-only (0600) mode guarantee could not be established' \
       && printf '%s' "$_e690_nt" | grep -qF "observed (platform-synthesized) mode $_m690" \
       && printf '%s' "$_e690_nt" | grep -qF 'which this script neither sets nor verifies' \
       && echo yes || echo no)"
  # A plain stderr line gets no Actions run-summary annotation, and an unestablished
  # security guarantee is exactly what a reader must not have to grep the raw log for.
  # Under GITHUB_ACTIONS the arm emits an additional ::warning:: annotation; off
  # Actions it emits ONLY the bare-prefixed detail line, so a local run stays clean.
  #
  # BOTH operands set GITHUB_ACTIONS explicitly — the negative one by UNSETTING it in
  # a subshell, never by reusing an ambient-env capture like $_e690_nt. `_i690` runs
  # `env "${_ENV533[@]}"`, which inherits the ambient environment, and the required
  # `lib + python tests` CI job runs with GITHUB_ACTIONS=true: an ambient-env capture
  # would take the annotation branch there and turn this row RED on CI alone, while
  # passing at a desk where the variable is unset. Pinning both states makes the row
  # environment-independent.
  assert_eq "#690: the relaxed arm emits a ::warning:: annotation under GITHUB_ACTIONS, and none when it is unset" "yes no" \
    "$(printf '%s' "$(GITHUB_ACTIONS=true _i690)" | grep -qF '::warning::install-gh-wrapper:' && echo yes || echo no) $(printf '%s' "$(unset GITHUB_ACTIONS; _i690)" | grep -qF '::warning::' && echo yes || echo no)"
done
# The `nt` token with a real 600 must take the FIRST arm (mode value) and emit no
# breadcrumb. Without this row nothing pins the arm ORDER: reordering the `if` so
# the nt test precedes the `600` equality would make an nt host that genuinely
# produced 600 emit a false could-not-be-established line, and every other row
# would stay green.
_stub690 'nt 600'; _e690_n6="$(_i690)"; _rc690_n6=$?
assert_eq "#690: stubbed 'nt 600' passes on the mode value via the FIRST arm (rc 0), emitting no could-not-establish breadcrumb (pins arm order)" "0 no" \
  "$_rc690_n6 $(printf '%s' "$_e690_n6" | grep -qF 'owner-only' && echo yes || echo no)"
_stub690 'zz 600'; _e690_u6="$(_i690)"; _rc690_u6=$?
assert_eq "#690: an unrecognized platform token with mode 600 passes on the mode value alone (rc 0), emitting no breadcrumb" "0 no" \
  "$_rc690_u6 $(printf '%s' "$_e690_u6" | grep -qF 'owner-only' && echo yes || echo no)"
# Failing cases — the closed set, enumerated per platform-token class because the
# nt class has no octal-and-failing member by construction (under nt every octal
# mode passes). Every one exits 1 naming the (fingerprint-mode) slug, so the
# relaxed arm can never be reached by an absent token, an absent mode field, a
# value the producer could not have emitted, or a three-field capture.
for _c690 in 'posix 644' 'posix banana' 'posix' \
             'nt banana' 'nt' 'nt 666 x' \
             'zz 644' 'zz banana' 'zz' \
             ''; do
  _stub690 "$_c690"; _e690_f="$(_i690)"; _rc690_f=$?
  assert_eq "#690: stubbed capture '$_c690' keeps the strict comparison — rc 1 naming (fingerprint-mode)" "1 yes" \
    "$_rc690_f $(printf '%s' "$_e690_f" | grep -qF 'output 5/7 FAILED' && printf '%s' "$_e690_f" | grep -qF '(fingerprint-mode)' && echo yes || echo no)"
done
# Pinned so no execution path can attribute the token and the mode to two
# different interpreters (a second os.stat could observe a different file state).
assert_eq "#690: the platform token and the mode are read by a single python3 invocation from a single os.stat" "1" \
  "$(grep -cF "python3 -c 'import os,sys; print(os.name, oct(os.stat(sys.argv[1]).st_mode & 0o777)[2:])'" "$INSTALL533")"
# The relaxed arm is an ALLOWLIST equality against the literal nt. A negated test
# against posix would admit the empty token an unreadable os.stat leaves behind,
# turning the fail-closed unreadable-mode arm into a silent pass on every platform.
assert_eq "#690: the relaxed arm tests equality against the literal nt, never a negation against posix" "1 0" \
  "$(grep -cF '[ "$_fpos" = "nt" ]' "$INSTALL533") $(grep -cF '[ "$_fpos" != "posix" ]' "$INSTALL533")"
# No mode-setting chmod is introduced anywhere: the umask 077 stays the sole
# producer of the fingerprint file's mode, which is what keeps the AC22 mutation
# proof below meaningful (a chmod would repair the mutated copy and turn that
# proof green). Asserted over EVERY non-comment chmod in the file rather than
# only those naming FINGERPRINT on the same line — a `chmod 600 "$f"` reached
# through an intermediate assignment, or placed on a following line, defeats the
# umask proof just as completely and a FINGERPRINT-on-the-same-line grep cannot
# see it. The installer's only legitimate chmod is the `+x` on the copied
# wrapper (output 4/7), so the mode-setting count must be exactly zero.
assert_eq "#690: install-gh-wrapper.sh contains no mode-setting chmod at all (only the wrapper's chmod +x)" "0" \
  "$(grep -vE '^[[:space:]]*#' "$INSTALL533" | grep 'chmod' | grep -vc 'chmod +x')"
# Behavioral mutation proof (issue #690). This executes the mutated file rather than
# merely re-grepping a literal, so it
# cannot observe a behavioral case change verdict. Mirroring the #533 AC22
# mutated-installer block instead — mutate the nt disjunct out of a copy, RUN it
# under the stubbed-nt fixture, and observe the reported bug reappear.
_t690m="$(probe_tmp '#690 mutated-installer setup')"
sed -E 's/\[ "\$_fpos" = "nt" \]/[ "$_fpos" = "IMPOSSIBLE" ]/' "$INSTALL533" > "$_t690m"
_stub690 'nt 666'; _e690_m="$(_i690 "$_t690m")"; _rc690_m=$?
assert_eq "#690: mutating the nt disjunct out of an installer copy re-introduces the reported bug — rc 1 naming (fingerprint-mode) under a stubbed 'nt 666'" "1 yes" \
  "$_rc690_m $(printf '%s' "$_e690_m" | grep -qF '(fingerprint-mode)' && echo yes || echo no)"
rm -f "$_t690m"
rm -rf "$D533/py690"

# AC14 — the DEFAULT wrapper-source resolution (output 2's vendored-or-repo
# chain) is the branch PRODUCTION takes: neither workflow passes
# DEVFLOW_GH_SOURCE_SH, so a regression in the default chain (inverted
# precedence, a typo'd vendored path) would otherwise ship green while every
# consumer install failed. The chain is cwd-keyed, so each case runs the
# installer from a fixture tree root.
mkdir -p "$D533/tree1/.prflow/vendor/prflow/scripts" "$D533/tree1/scripts" "$D533/tree2/scripts"
printf '#!/usr/bin/env bash\necho vendored-copy\n' > "$D533/tree1/.prflow/vendor/prflow/scripts/gh-fresh.sh"
printf '#!/usr/bin/env bash\necho repo-copy\n' > "$D533/tree1/scripts/gh-fresh.sh"
printf '#!/usr/bin/env bash\necho repo-copy\n' > "$D533/tree2/scripts/gh-fresh.sh"
: > "$D533/ghenv"; : > "$D533/ghpath"
( cd "$D533/tree1" && env PATH="$D533/bin:$PATH" APP_TOKEN=FIXTURE_TOKEN_533 RUNNER_TEMP="$D533/rtmp" \
    GITHUB_ENV="$D533/ghenv" GITHUB_PATH="$D533/ghpath" DEVFLOW_GH_WRAPDIR="$D533/wrapdir-src1" \
    DEVFLOW_GH_FINGERPRINT_FILE="$D533/rtmp/devflow-gh-fingerprint" bash "$INSTALL533" >/dev/null 2>&1 )
assert_eq "#533 AC14 default SRC: the vendored copy is preferred when both copies exist" "yes" \
  "$(grep -qF 'vendored-copy' "$D533/wrapdir-src1/gh" 2>/dev/null && echo yes || echo no)"
: > "$D533/ghenv"; : > "$D533/ghpath"
( cd "$D533/tree2" && env PATH="$D533/bin:$PATH" APP_TOKEN=FIXTURE_TOKEN_533 RUNNER_TEMP="$D533/rtmp" \
    GITHUB_ENV="$D533/ghenv" GITHUB_PATH="$D533/ghpath" DEVFLOW_GH_WRAPDIR="$D533/wrapdir-src2" \
    DEVFLOW_GH_FINGERPRINT_FILE="$D533/rtmp/devflow-gh-fingerprint" bash "$INSTALL533" >/dev/null 2>&1 )
assert_eq "#533 AC14 default SRC: the repo-relative copy is the fallback when no vendored copy exists" "yes" \
  "$(grep -qF 'repo-copy' "$D533/wrapdir-src2/gh" 2>/dev/null && echo yes || echo no)"

# AC11 — the three production caller classes reach the PATH-installed wrapper
# (the wrapper is the real gh-fresh.sh copied by the installer above; with no
# GH_TOKEN and an absent token file it degrades to a plain invocation of
# DEVFLOW_GH_REAL — the fixture stub — whose echoed marker proves the chain).
_c533_1="$(DEVFLOW_GH_REAL="$D533/bin/gh" DEVFLOW_GH_TOKEN_FILE="$D533/absent-token" \
  PATH="$D533/wrapdir:$PATH" gh api one 2>/dev/null)"
assert_eq "#533 AC11: a direct gh call reaches the PATH-installed wrapper" "yes" \
  "$(printf '%s' "$_c533_1" | grep -qF 'REALGH_CALLED api one' && echo yes || echo no)"
_c533_2cmd="$(DEVFLOW_GH_REAL="$D533/bin/gh" PATH="$D533/wrapdir:$PATH" bash -c ". \"$LIB/resolve-gh.sh\"; devflow_resolve_gh")"
_c533_2="$(DEVFLOW_GH_REAL="$D533/bin/gh" DEVFLOW_GH_TOKEN_FILE="$D533/absent-token" \
  PATH="$D533/wrapdir:$PATH" "$_c533_2cmd" api two 2>/dev/null)"
assert_eq "#533 AC11: a shell helper via devflow_resolve_gh reaches the PATH-installed wrapper" "gh yes" \
  "$_c533_2cmd $(printf '%s' "$_c533_2" | grep -qF 'REALGH_CALLED api two' && echo yes || echo no)"
_c533_3="$(DEVFLOW_GH_REAL="$D533/bin/gh" DEVFLOW_GH_TOKEN_FILE="$D533/absent-token" \
  PATH="$D533/wrapdir:$PATH" python3 -c 'import os,subprocess; gh=os.environ.get("DEVFLOW_GH") or "gh"; print(subprocess.run([gh,"api","three"],capture_output=True,text=True).stdout,end="")')"
assert_eq "#533 AC11: a Python helper GH selector reaches the PATH-installed wrapper" "yes" \
  "$(printf '%s' "$_c533_3" | grep -qF 'REALGH_CALLED api three' && echo yes || echo no)"

# AC12 — an explicitly scoped non-empty DEVFLOW_GH still outranks PATH for the
# shell resolver AND a Python caller, even with the wrapper dir first on PATH.
printf '#!/usr/bin/env bash\necho "OVERRIDE_CALLED $*"\n' > "$D533/override-gh"; chmod +x "$D533/override-gh"
_c533_ov="$(DEVFLOW_GH="$D533/override-gh" PATH="$D533/wrapdir:$PATH" bash -c ". \"$LIB/resolve-gh.sh\"; devflow_resolve_gh")"
assert_eq "#533 AC12: shell resolver honors an explicit DEVFLOW_GH over the PATH wrapper" "$D533/override-gh" "$_c533_ov"
_c533_ovp="$(DEVFLOW_GH="$D533/override-gh" PATH="$D533/wrapdir:$PATH" python3 -c 'import os,subprocess; gh=os.environ.get("DEVFLOW_GH") or "gh"; print(subprocess.run([gh,"api","ov"],capture_output=True,text=True).stdout,end="")')"
assert_eq "#533 AC12: a Python caller honors an explicit DEVFLOW_GH over the PATH wrapper" "yes" \
  "$(printf '%s' "$_c533_ovp" | grep -qF 'OVERRIDE_CALLED api ov' && echo yes || echo no)"

# gh-fresh writer/reader hash symmetry (#544): with sha256sum/shasum/awk all
# failing on PATH, the wrapper's call-time fingerprint comparison still matches
# the installer-written (python3-hashlib) fingerprint via its own python3 arm —
# so the ambient job-start token is substituted with the refreshed one instead
# of silently deferring on exactly the host class the installer was hardened for.
mkdir -p "$D533/wrapb"
cp "$LIB/../scripts/gh-fresh.sh" "$D533/wrapb/gh"; chmod +x "$D533/wrapb/gh"
printf '#!/usr/bin/env bash\necho "TOKEN_SEEN=${GH_TOKEN:-none}"\n' > "$D533/realgh2"; chmod +x "$D533/realgh2"
printf '%s' FRESH_TOKEN_544 > "$D533/tokfile544"
printf '%s' AMBIENT_T_544 | python3 -c 'import hashlib,sys; sys.stdout.write(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())' > "$D533/fp544"
_c544="$(env GH_TOKEN=AMBIENT_T_544 DEVFLOW_GH_REAL="$D533/realgh2" DEVFLOW_GH_TOKEN_FILE="$D533/tokfile544" \
  DEVFLOW_GH_FINGERPRINT_FILE="$D533/fp544" PATH="$D533/noshabin:$PATH" bash "$D533/wrapb/gh" api q 2>/dev/null)"
assert_eq "#544 symmetry: fingerprint match works without sha256sum/shasum/awk (python3 arm) — ambient token substituted" "TOKEN_SEEN=FRESH_TOKEN_544" "$_c544"
# AC16 preserved: with EVERY hash method defeated (failing sha256sum/shasum/awk
# AND a failing python3 first on PATH), decide() still takes the disclosed
# could-not-establish defer arm — breadcrumb emitted, ambient token untouched.
_c544b_out="$(env GH_TOKEN=AMBIENT_T_544 DEVFLOW_GH_REAL="$D533/realgh2" DEVFLOW_GH_TOKEN_FILE="$D533/tokfile544" \
  DEVFLOW_GH_FINGERPRINT_FILE="$D533/fp544" PATH="$D533/noshabin:$D533/badpy:$PATH" bash "$D533/wrapb/gh" api q 2>"$D533/c544b.err")"
assert_eq "#544 symmetry: all hash methods defeated still defers on the ambient token with the disclosed breadcrumb" "TOKEN_SEEN=AMBIENT_T_544 yes" \
  "$_c544b_out $(grep -qF 'could not establish the job-start fingerprint comparison' "$D533/c544b.err" && echo yes || echo no)"

# AC13 — launch the suite itself with a failing-sentinel DEVFLOW_GH: the harness
# entry clears it (probe mode exits right after the clear + resolver check), so
# the fixture-local PATH stub — not the sentinel — is what resolves and runs.
# Probe mode deliberately exits 3 (a leaked DEVFLOW_AC13_PROBE in a CI env must
# fail the required check loudly, never pass it green with zero tests run) —
# assert the rc alongside the resolution so the fail-closed exit is pinned.
_ac13="$(DEVFLOW_GH=/nonexistent/failing-sentinel DEVFLOW_AC13_PROBE=1 bash "$LIB/test/run.sh" 2>/dev/null)"; _ac13_rc=$?
assert_eq "#533 AC13: suite launched with a failing-sentinel DEVFLOW_GH resolves gh via the fixture PATH stub (probe exits 3, never a green zero-test suite)" "3 yes" \
  "$_ac13_rc $(printf '%s' "$_ac13" | grep -qF 'resolved=gh output=AC13_PATH_STUB_INVOKED' && echo yes || echo no)"

# AC22 — planted production defects flip the named assertions RED (copy-based;
# the working tree is never mutated).
# (a) Harness defect: remove the entry clear from a run.sh copy (with the resolver
# siblings beside it so the probe still sources) — the inherited sentinel then
# SURVIVES into the probe, i.e. the AC13 assertion above would go RED.
_m533d="$(mktemp -d "$_iw_tmp_root/m533d.XXXXXX")" || {
  echo FAIL >> "$RESULTS_FILE"
  record_fail "#533 AC22 mutated-harness fixture — mktemp -d failed"
  printf '  FAIL  #533 AC22 mutated-harness fixture — mktemp -d failed\n' >&2
  _m533d=/dev/null/unallocated-m533d
}
mkdir -p "$_m533d/test"
sed -E 's/^unset DEVFLOW_GH$/: # planted defect: inherited override no longer cleared/' "$LIB/test/run.sh" > "$_m533d/test/run.sh"
cp "$LIB/resolve-gh.sh" "$LIB/resolve-bin.sh" "$_m533d/"
_ac13m="$(DEVFLOW_GH=/nonexistent/failing-sentinel DEVFLOW_AC13_PROBE=1 bash "$_m533d/test/run.sh" 2>/dev/null || true)"
assert_eq "#533 AC22: a planted removal of the harness clear surfaces the sentinel (AC13 assertion goes RED on the defect)" "yes" \
  "$(printf '%s' "$_ac13m" | grep -qF 'resolved=/nonexistent/failing-sentinel' && echo yes || echo no)"
rm -rf "$_m533d"
# (b) Installer defect: weaken the fingerprint umask on a copy — the installer's
# own output-5 mode validation catches it, rc 1 naming fingerprint-mode.
_t533i="$(probe_tmp '#533 AC22 mutated-installer setup')"
sed -E 's/umask 077/umask 022/' "$INSTALL533" > "$_t533i"
rm -f "$D533/rtmp/devflow-gh-fingerprint"; : > "$D533/ghenv"; : > "$D533/ghpath"
_o533_mut="$(env PATH="$D533/bin:$PATH" DEVFLOW_GH_SOURCE_SH="$LIB/../scripts/gh-fresh.sh" \
  APP_TOKEN=FIXTURE_TOKEN_533 RUNNER_TEMP="$D533/rtmp" GITHUB_ENV="$D533/ghenv" GITHUB_PATH="$D533/ghpath" \
  DEVFLOW_GH_WRAPDIR="$D533/wrapdir-mut" DEVFLOW_GH_FINGERPRINT_FILE="$D533/rtmp/devflow-gh-fingerprint" \
  bash "$_t533i" 2>&1)"; _rc533_mut=$?
assert_eq "#533 AC22: a planted umask defect in a mutated installer copy fails rc 1 naming fingerprint-mode" "1 yes" \
  "$_rc533_mut $(printf '%s' "$_o533_mut" | grep -qF '(fingerprint-mode)' && echo yes || echo no)"
rm -f "$_t533i"
# (c) Installer defect: a re-introduced bare DEVFLOW_GH export on a copy is caught
# by the AC10 guard's OWN counting recipe (_ac10_count533 — the same function the
# real assertion runs, exercised via probe_assert so the intentional RED never
# hits the suite tally; a hand-copied grep here could drift green while the real
# guard's pattern rots).
_t533j="$(probe_tmp '#533 AC22 mutated-installer AC10 setup')"
sed -E 's/DEVFLOW_GH_REAL=\$REAL_GH/DEVFLOW_GH=\$WRAPDIR\/gh/' "$INSTALL533" > "$_t533j"
assert_eq "#533 AC22: a planted bare DEVFLOW_GH export in a mutated installer copy flips the AC10 guard RED" "FAIL" \
  "$(probe_assert assert_eq 'probe-ac10-mutated' "0" "$(_ac10_count533 "$_t533j")")"
rm -f "$_t533j"
rm -rf "$D533"

# ────────────────────────────────────────────────────────────────────────────
echo "install.sh consumer UPGRADE path: provenance, non-clobbering, dry-run, withheld tier, identifier migration"
# ────────────────────────────────────────────────────────────────────────────
# These arms drive the REAL installer end-to-end over REAL fixture consumer
# repositories. A consumer upgrade cannot be verified by reading code: the whole
# defect class is "the installer overwrote something the consumer had edited", and
# only an actual before/after of an actual tree can catch that.
#
# Network-free: DEVFLOW_SRC hands the installer an already-materialized source tree,
# so no clone is attempted, and nothing on this path invokes gh.
IU_INSTALL="$LIB/../install.sh"
IU_REF="0123456789abcdef0123456789abcdef01234567"

# The source tree the fixtures install FROM: the minimum the installer reads, copied
# from the real repo so the arms exercise the shipped scaffolder, the shipped
# workflows and the shipped composite actions rather than stand-ins.
IU_SRC="$_iw_tmp_root/src"
mkdir -p "$IU_SRC/scripts" "$IU_SRC/lib" "$IU_SRC/.prflow" "$IU_SRC/.github/workflows" "$IU_SRC/.github/actions"
cp "$LIB/../scripts/scaffold-config.sh" "$LIB/../scripts/detect-project-tools.sh" \
   "$LIB/../scripts/migrate-consumer-tier1.sh" "$IU_SRC/scripts/"
# rename-map.json and resolve-state-dir.sh are what the issue-#1002 migration and the
# scaffolder's state-directory resolution read. Omitting them left these arms driving
# the degraded no-map / no-resolver path instead of the shipped one — the same class of
# silent fixture gap the tool-presets.json note below records.
cp "$LIB/resolve-jq.sh" "$LIB/resolve-bin.sh" "$LIB/rename-map.json" \
   "$LIB/resolve-state-dir.sh" "$IU_SRC/lib/"
# tool-presets.json lives under .prflow/, which is where detect-project-tools.sh
# resolves it from ($SELF_DIR/../.prflow/tool-presets.json). Copying it to scripts/
# left the fixture source tree missing it, so these arms silently drove the
# presets-absent degraded path instead of the shipped one.
# #1388: lint-manifest.json + install-state.json are now devflow_copy_slice copy-list
# members, so the offline source tree must carry them or a DEVFLOW_VENDOR=1 install's
# slice copy aborts before the vendored tree lands.
cp "$LIB/../.prflow/config.example.json" "$LIB/../.prflow/config.schema.json" \
   "$LIB/../.prflow/tool-presets.json" "$LIB/../.prflow/lint-manifest.json" \
   "$LIB/../.prflow/install-state.json" "$IU_SRC/.prflow/"
assert_eq "installer-upgrade fixture: the offline source tree carries tool-presets.json where detect-project-tools.sh resolves it" "yes" \
  "$([ -f "$IU_SRC/.prflow/tool-presets.json" ] && echo yes || echo no)"
cp "$LIB/../.github/workflows/devflow.yml" "$LIB/../.github/workflows/devflow-implement.yml" "$IU_SRC/.github/workflows/"
for _iu_a in read-project-config setup-project-env vendor-plugin; do
  cp -R "$LIB/../.github/actions/$_iu_a" "$IU_SRC/.github/actions/"
done
assert_eq "installer-upgrade fixture: the offline source tree carries the shipped scaffolder, workflows and vendor-slice" "yes" \
  "$([ -f "$IU_SRC/scripts/scaffold-config.sh" ] && [ -f "$IU_SRC/.github/workflows/devflow.yml" ] \
     && [ -f "$IU_SRC/.github/actions/vendor-plugin/vendor-slice.sh" ] && echo yes || echo no)"
assert_eq "installer-upgrade fixture: the offline source tree carries the #1002 migration helper and its rename map" "yes" \
  "$([ -x "$IU_SRC/scripts/migrate-consumer-tier1.sh" ] && [ -f "$IU_SRC/lib/rename-map.json" ] \
     && [ -f "$IU_SRC/lib/resolve-state-dir.sh" ] && echo yes || echo no)"

_iu_consumer() {  # $1 = fixture id -> prints a fresh consumer repo root
  local d="$_iw_tmp_root/consumer-$1"
  rm -rf "$d"; mkdir -p "$d/.git"
  printf '%s' "$d"
}
_iu_run() {  # $1 = consumer root, rest = installer arguments; prints merged output
  local d="$1"; shift
  ( cd "$d" && env DEVFLOW_SRC="${IU_SRC_OVERRIDE:-$IU_SRC}" DEVFLOW_REF="$IU_REF" \
      DEVFLOW_VENDOR="${IU_VENDOR:-}" \
      PATH="${IU_PATH_PREFIX:+$IU_PATH_PREFIX:}$PATH" \
      bash "${IU_INSTALL_BIN:-$IU_INSTALL}" "$@" 2>&1 )
}
# A stub directory whose `python3` is present on PATH but exits non-zero — the state
# `offer_python3_shim` exists to remedy, and the one the installer's provenance layer
# must fail SAFE on. Deterministic and self-contained: the suite builds the stub, and
# it is prepended to PATH only inside the _iu_run subshell, so the harness's own
# python3 helpers (_iu_snapshot / _iu_digest) are unaffected and nothing depends on
# what the host happens to have installed. Present-but-unrunnable rather than absent
# is the STRONGER shape: it defeats a `command -v python3` presence check too, and
# devflow_resolve_python is execution-verified precisely for it.
IU_NOPY="$_iw_tmp_root/nopython3"
mkdir -p "$IU_NOPY"
printf '#!/bin/sh\nexit 127\n' > "$IU_NOPY/python3"
chmod +x "$IU_NOPY/python3"
assert_eq "installer-upgrade fixture: the python3 stub is on PATH yet does not execute (so it defeats a presence-only check)" "yes no" \
  "$([ -x "$IU_NOPY/python3" ] && echo yes || echo no) $("$IU_NOPY/python3" -c 'pass' >/dev/null 2>&1 && echo yes || echo no)"
# A content-addressed snapshot of a fixture tree, so "nothing outside the intended
# set changed" is asserted over BYTES, not over a list of paths a partial write
# would still satisfy.
_IU_SNAP_PY='
import hashlib, os, sys
base = sys.argv[1]
out = []
for root, dirs, files in os.walk(base):  # tree-walk-ok: scoped to a fixture consumer repo under the mktemp root this module owns, never to the repository, so it cannot reach a sibling worktree
    dirs.sort()
    if ".git" in dirs:
        dirs.remove(".git")
    for f in sorted(files):
        fp = os.path.join(root, f)
        # A SYMLINK is snapshotted by its target, not by the bytes it resolves to: the
        # #959 arms plant a DANGLING symlink to induce a digest failure, and reading
        # through it would raise and leave this helper printing NOTHING — which would
        # make the "no pre-existing path changed" comparisons pass by comparing two
        # empty strings. Recording the link target also makes "a symlink was replaced
        # by a regular file" a visible change rather than an invisible one.
        if os.path.islink(fp):
            out.append(os.path.relpath(fp, base).replace(os.sep, "/") + " -> " + os.readlink(fp))
            continue
        with open(fp, "rb") as fh:
            d = hashlib.sha256(fh.read()).hexdigest()
        out.append(os.path.relpath(fp, base).replace(os.sep, "/") + " " + d)
sys.stdout.write("\n".join(sorted(out)))
'
_iu_snapshot() { python3 -c "$_IU_SNAP_PY" "$1"; }
_iu_digest() { python3 -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$1"; }
# One raw presence command per logical line — the pin-corpus lint rejects two on the same
# site span, and several arms below compare three yes/no operands at once. Routing them
# through these three helpers also puts the yes/no convention in one place.
_iu_has() {  # $1 = file, $2 = literal -> yes|no
  grep -qF -- "$2" "$1" && echo yes || echo no
}
_iu_out_has() {  # $1 = captured output, $2 = literal -> yes|no
  printf '%s' "$1" | grep -qF -- "$2" && echo yes || echo no
}
_iu_out_matches() {  # $1 = captured output, $2 = ERE -> yes|no
  printf '%s\n' "$1" | grep -qE -- "$2" && echo yes || echo no
}
_iu_has_line() {  # $1 = file, $2 = literal WHOLE line -> yes|no
  # The -x sibling of _iu_has, for the .gitignore arms where a substring match would
  # confuse `/vendor/` with a longer path. Routed through a helper for the same reason
  # the three above are: two raw presence commands on one logical assertion line is what
  # the pin-corpus lint rejects, and several .gitignore arms compare two entries at once.
  grep -qxF -- "$2" "$1" && echo yes || echo no
}

# ── Scenario 1: a first-time install APPLIES, and a pristine re-run is a clean,
# write-free dry run. The documented one-liner must not have become a no-op.
IU_C1="$(_iu_consumer pristine)"
IU_O1="$(_iu_run "$IU_C1")"
assert_eq "installer-upgrade: a first-time install applies without --apply (the documented one-liner is unchanged)" "yes yes yes" \
  "$(_iu_out_has "$IU_O1" 'detected a first-time installation; running in apply mode.') $([ -f "$IU_C1/.github/workflows/devflow.yml" ] && echo yes || echo no) $([ -f "$IU_C1/.prflow/install-manifest.json" ] && echo yes || echo no)"
assert_eq "installer-upgrade: the first install records a provenance digest for every artifact it owns" "yes" \
  "$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
want = {".claude-plugin/marketplace.json", ".github/workflows/devflow.yml",
        ".github/workflows/devflow-implement.yml", ".github/actions/read-project-config",
        ".github/actions/setup-project-env", ".github/actions/vendor-plugin"}
arts = d.get("artifacts", {})
print("yes" if want <= set(arts) and all(isinstance(v, str) and len(v) == 64 for v in arts.values()) else "no")
' "$IU_C1/.prflow/install-manifest.json")"
IU_SNAP1="$(_iu_snapshot "$IU_C1")"
IU_O1B="$(_iu_run "$IU_C1")"
assert_eq "installer-upgrade: re-running over an existing installation is a DRY RUN by default and writes nothing" "yes yes yes" \
  "$(_iu_out_has "$IU_O1B" 'detected an existing installation; running in dry-run mode.') $(_iu_out_has "$IU_O1B" 'nothing in this repository was written') $([ "$IU_SNAP1" = "$(_iu_snapshot "$IU_C1")" ] && echo yes || echo no)"
assert_eq "installer-upgrade: a pristine re-run reports an empty diff (0 files would change)" "1" \
  "$(printf '%s\n' "$IU_O1B" | grep -cF 'devflow-install: 0 file(s) would change.')"

# ── Scenario 2: a hand-modified workflow is PRESERVED, byte-for-byte, and the new
# version is offered beside it. This is the defect the whole provenance layer exists
# to stop, so it is asserted on the APPLY path (a dry run cannot destroy anything).
IU_C2="$(_iu_consumer handedit)"
_iu_run "$IU_C2" >/dev/null
printf '\n# CONSUMER-LOCAL-EDIT-MARKER\n' >> "$IU_C2/.github/workflows/devflow.yml"
IU_WF2_BEFORE="$(_iu_digest "$IU_C2/.github/workflows/devflow.yml")"
IU_O2="$(_iu_run "$IU_C2" --apply)"
assert_eq "installer-upgrade: --apply over a hand-modified workflow leaves it BYTE-FOR-BYTE unchanged and writes the new version to a .prflow-new sidecar" "yes yes yes" \
  "$([ "$IU_WF2_BEFORE" = "$(_iu_digest "$IU_C2/.github/workflows/devflow.yml")" ] && echo yes || echo no) $(_iu_has "$IU_C2/.github/workflows/devflow.yml" 'CONSUMER-LOCAL-EDIT-MARKER') $([ -f "$IU_C2/.github/workflows/devflow.yml.prflow-new" ] && echo yes || echo no)"
assert_eq "installer-upgrade: the preserved artifact is reported as locally modified, naming the sidecar" "yes" \
  "$(_iu_out_has "$IU_O2" 'PRESERVED (locally modified since DevFlow wrote it): .github/workflows/devflow.yml')"
assert_eq "installer-upgrade: the sidecar carries DevFlow's version, not the consumer's edit" "yes no" \
  "$([ "$(_iu_digest "$IU_C2/.github/workflows/devflow.yml.prflow-new")" = "$(_iu_digest "$IU_SRC/.github/workflows/devflow.yml")" ] && echo yes || echo no) $(_iu_has "$IU_C2/.github/workflows/devflow.yml.prflow-new" 'CONSUMER-LOCAL-EDIT-MARKER')"
# The conflict is not silently blessed: the manifest still records the ORIGINAL digest,
# so the next run reports it again instead of adopting the edited bytes as provenance.
assert_eq "installer-upgrade: a preserved conflict is re-reported on the next run (its digest is never re-blessed)" "yes" \
  "$(printf '%s' "$(_iu_run "$IU_C2" --apply)" | grep -qF 'PRESERVED (locally modified' && echo yes || echo no)"
# NEGATIVE CONTROL: the same assertion recipe must be able to say "clobbered". Plant an
# installer copy whose classifier always returns `update` and observe the consumer edit
# disappear — proving the arm above measures preservation, not the absence of any write.
IU_MUT2="$(probe_tmp 'installer-upgrade clobber control setup')"
sed -E 's/if \[ "\$cur" = "\$rec" \]; then printf .update.; else printf .modified.; fi/printf update/' \
  "$IU_INSTALL" > "$IU_MUT2"
IU_C2B="$(_iu_consumer handedit-control)"
_iu_run "$IU_C2B" >/dev/null
printf '\n# CONSUMER-LOCAL-EDIT-MARKER\n' >> "$IU_C2B/.github/workflows/devflow.yml"
IU_INSTALL_BIN="$IU_MUT2" _iu_run "$IU_C2B" --apply >/dev/null 2>&1 || true
assert_eq "installer-upgrade NEGATIVE CONTROL: an installer whose classifier always says update DOES clobber the consumer edit (so the preservation arm above is not vacuous)" "no" \
  "$(_iu_has "$IU_C2B/.github/workflows/devflow.yml" 'CONSUMER-LOCAL-EDIT-MARKER')"
rm -f "$IU_MUT2"

# ── Scenario 3: a hand-edited .prflow/config.json keeps every consumer value. The
# config is never a managed artifact — the shared scaffolder only backfills keys.
IU_C3="$(_iu_consumer configedit)"
_iu_run "$IU_C3" >/dev/null
python3 -c '
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["watched_authors"] = ["consumer-chosen-bot"]
d["prflow"] = d.get("prflow", {})
d["prflow"]["allowed_tools"] = ["Bash(consumer-only-tool:*)"]
json.dump(d, open(p, "w"), indent=2)
' "$IU_C3/.prflow/config.json"
_iu_run "$IU_C3" --apply >/dev/null
assert_eq "installer-upgrade: --apply preserves hand-edited .prflow/config.json values (the scaffolder only backfills)" "consumer-chosen-bot Bash(consumer-only-tool:*)" \
  "$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
print(d["watched_authors"][0], d["prflow"]["allowed_tools"][0])
' "$IU_C3/.prflow/config.json")"

# ── Scenario 4: the withheld automatic-review tier. Reported always; removed only on
# the explicit opt-in; never removed from a file that is not recognizably DevFlow's.
#
# The fixtures reproduce the SIGNATURE each withheld file actually carries — its own
# `name:` header — rather than a stand-in that merely contains the string "devflow".
# That distinction is the whole point of the guard (see the adversarial arm below): a
# fixture that only had to contain "devflow" would keep passing against a substring
# match, which is exactly the over-broad guard this scenario now pins against.
_iu_withheld_file() {  # $1 = withheld-tier id -> DevFlow's own header for that workflow
  case "$1" in
    devflow-review)  printf 'name: Devflow Review (auto-trigger)\non: pull_request\njobs: {}\n' ;;
    devflow-runner)  printf 'name: DevFlow Runner (reusable)\non:\n  workflow_call:\njobs: {}\n' ;;
    telemetry-push)  printf 'name: Telemetry push (trusted relay)\non:\n  workflow_run:\njobs: {}\n' ;;
  esac
}
IU_C4="$(_iu_consumer withheld)"
_iu_run "$IU_C4" >/dev/null
for _iu_w in devflow-review devflow-runner telemetry-push; do
  _iu_withheld_file "$_iu_w" > "$IU_C4/.github/workflows/$_iu_w.yml"
done
# Counted with a glob and a builtin loop, never `ls | grep -c`: the count decides an
# assertion outcome, and a non-preflight PATH tool must not be what derives it.
_iu_count_withheld() {  # $1 = consumer root -> how many withheld-tier workflows survive
  local n=0 w
  for w in devflow-review devflow-runner telemetry-push; do
    [ -f "$1/.github/workflows/$w.yml" ] && n=$((n + 1))
  done
  printf '%s' "$n"
}
IU_O4="$(_iu_run "$IU_C4" --apply)"
assert_eq "installer-upgrade: an installation carrying the withheld review tier is told so, is told it stays exposed, and keeps all three files by default" "yes yes 3" \
  "$(_iu_out_has "$IU_O4" 'carries the withheld automatic-review tier (devflow-review devflow-runner telemetry-push)') $(_iu_out_has "$IU_O4" 'issues #930 and #920') $(_iu_count_withheld "$IU_C4")"
assert_eq "installer-upgrade: the default report names the opt-in flag rather than removing anything" "yes" \
  "$(_iu_out_has "$IU_O4" 're-run with --remove-withheld-review-tier')"
IU_O4B="$(_iu_run "$IU_C4" --apply --remove-withheld-review-tier)"
assert_eq "installer-upgrade: the opt-in deletes the three withheld workflows and turns the review config key off" "0 false" \
  "$(_iu_count_withheld "$IU_C4") $(python3 -c 'import json,sys;print(json.dumps(json.load(open(sys.argv[1])).get("workflows",{}).get("prflow-review")))' "$IU_C4/.prflow/config.json")"
assert_eq "installer-upgrade: the removal states the branch-protection step no installer can perform" "yes" \
  "$(printf '%s' "$IU_O4B" | grep -qF "branch protection rule" && echo yes || echo no)"
# Signature guard: a same-named workflow that is NOT DevFlow's is never deleted.
IU_C4C="$(_iu_consumer withheld-foreign)"
_iu_run "$IU_C4C" >/dev/null
printf 'name: someone elses telemetry push\non: push\n' > "$IU_C4C/.github/workflows/telemetry-push.yml"
IU_O4C="$(_iu_run "$IU_C4C" --apply --remove-withheld-review-tier)"
assert_eq "installer-upgrade: the opt-in removal is signature-guarded — a same-named workflow carrying no DevFlow signature is left in place" "yes yes" \
  "$([ -f "$IU_C4C/.github/workflows/telemetry-push.yml" ] && echo yes || echo no) $(_iu_out_has "$IU_O4C" 'carries no DevFlow signature; left it untouched')"
# ADVERSARIAL (#959 review): the arm above only proves a file with NO mention of DevFlow
# survives, which a bare `grep -qi devflow` would also have satisfied. The case that
# matters is a workflow the CONSUMER owns, under a generic name they are entitled to use,
# that legitimately mentions the string — a path filter on `.prflow/**`, a comment, a
# step that reads the config. Under a substring guard that file is `rm -f`'d on the
# opt-in, with a log line claiming a withheld-tier workflow was removed. Three separate
# mentions, one per accepted spelling, so a guard that merely got case-folding wrong is
# caught too.
IU_C4D="$(_iu_consumer withheld-consumer-owned)"
_iu_run "$IU_C4D" >/dev/null
cat > "$IU_C4D/.github/workflows/telemetry-push.yml" <<'IUTP'
name: Push our metrics
# We re-run this when devflow config changes, since DevFlow owns the tool list.
on:
  push:
    paths:
      - '.prflow/**'
jobs:
  push:
    runs-on: ubuntu-latest
    steps:
      - run: ./scripts/push-metrics.sh
IUTP
IU_TP4D_BEFORE="$(_iu_digest "$IU_C4D/.github/workflows/telemetry-push.yml")"
IU_O4D="$(_iu_run "$IU_C4D" --apply --remove-withheld-review-tier)"
assert_eq "installer-upgrade #959: a CONSUMER-OWNED telemetry-push.yml that merely mentions devflow survives the opt-in removal, byte-for-byte" "yes yes yes" \
  "$([ -f "$IU_C4D/.github/workflows/telemetry-push.yml" ] && echo yes || echo no) $([ "$IU_TP4D_BEFORE" = "$(_iu_digest "$IU_C4D/.github/workflows/telemetry-push.yml")" ] && echo yes || echo no) $(_iu_out_has "$IU_O4D" 'carries no DevFlow signature; left it untouched')"
assert_eq "installer-upgrade #959: and the run never claims to have removed it" "no" \
  "$(_iu_out_has "$IU_O4D" 'removed withheld review-tier workflow telemetry-push.yml')"
# NEGATIVE CONTROL: restore the old substring guard on a copy and require that consumer
# file to be DESTROYED. Without this, the arm above passes on any guard that happens to
# reject this one fixture, including by accident.
IU_MUT4="$(probe_tmp '#959 withheld-tier substring-guard control setup')"
python3 -c '
import sys
src, dst = sys.argv[1], sys.argv[2]
body = open(src, encoding="utf-8").read()
guard = (
    "    _sig=\"$(devflow_withheld_tier_signature \"$_wt\")\"\n"
    "    _grc=0\n"
    "    if [ -n \"$_sig\" ]; then\n"
    "      grep -qE \"$_sig\" \".github/workflows/$_wt.yml\" || _grc=$?\n"
    "    else\n"
)
substring = (
    "    _grc=0\n"
    "    grep -qi \x27devflow\x27 \".github/workflows/$_wt.yml\" || _grc=$?\n"
    "    if false; then\n"
)
if guard not in body:
    sys.exit("mutation target not found: the withheld-tier signature guard")
open(dst, "w", encoding="utf-8").write(body.replace(guard, substring, 1))
' "$IU_INSTALL" "$IU_MUT4" || printf 'devflow-test: #959 withheld-tier control mutation FAILED to apply\n'
assert_eq "installer-upgrade #959 NEGATIVE CONTROL: the control copy really does restore the substring guard" "yes no" \
  "$(_iu_has "$IU_MUT4" "grep -qi 'devflow' \".github/workflows/\$_wt.yml\" || _grc=\$?") $(_iu_has "$IU_MUT4" 'grep -qE "$_sig"')"
IU_C4E="$(_iu_consumer withheld-consumer-owned-control)"
_iu_run "$IU_C4E" >/dev/null
cp "$IU_C4D/.github/workflows/telemetry-push.yml" "$IU_C4E/.github/workflows/telemetry-push.yml" 2>/dev/null || true
IU_INSTALL_BIN="$IU_MUT4" _iu_run "$IU_C4E" --apply --remove-withheld-review-tier >/dev/null 2>&1 || true
assert_eq "installer-upgrade #959 NEGATIVE CONTROL: the substring guard DOES delete that consumer-owned workflow (so the arm above is not vacuous)" "no" \
  "$([ -f "$IU_C4E/.github/workflows/telemetry-push.yml" ] && echo yes || echo no)"
rm -f "$IU_MUT4"

# ── Scenario 5: a SKIPPED-VERSION jump. The consumer's artifact is older than the one
# being installed but is provably untouched (its bytes match the recorded digest), so it
# is updated in place rather than preserved.
IU_C5="$(_iu_consumer skipped-version)"
_iu_run "$IU_C5" >/dev/null
python3 -c '
import hashlib, json, sys
root, rel = sys.argv[1], ".github/workflows/devflow.yml"
p = root + "/" + rel
body = open(p, encoding="utf-8").read() + "\n# BYTES FROM AN OLDER DEVFLOW RELEASE\n"
open(p, "w", encoding="utf-8").write(body)
mp = root + "/.prflow/install-manifest.json"
m = json.load(open(mp))
m["prflow_version"] = "1111111111111111111111111111111111111111"
m["artifacts"][rel] = hashlib.sha256(body.encode("utf-8")).hexdigest()
json.dump(m, open(mp, "w"), indent=2)
' "$IU_C5"
IU_O5="$(_iu_run "$IU_C5" --apply)"
assert_eq "installer-upgrade: a skipped-version jump updates an untouched older artifact in place (no sidecar, no half-state)" "yes yes no" \
  "$(_iu_out_has "$IU_O5" 'update: .github/workflows/devflow.yml') $([ "$(_iu_digest "$IU_C5/.github/workflows/devflow.yml")" = "$(_iu_digest "$IU_SRC/.github/workflows/devflow.yml")" ] && echo yes || echo no) $([ -e "$IU_C5/.github/workflows/devflow.yml.prflow-new" ] && echo yes || echo no)"
assert_eq "installer-upgrade: the skipped-version upgrade re-stamps prflow_version to the installed ref" "$IU_REF" \
  "$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["prflow_version"])' "$IU_C5/.prflow/config.json")"

# ── Scenario 6: an installation that NEVER upgraded — no provenance on record. Unknown
# is not "unmodified": an artifact whose bytes differ is preserved, while one already
# identical to the shipped version is recorded.
#
# The healing is PARTIAL, and saying so is the point (#959 review): without a recorded
# digest there is nothing to compare against, so EVERY differing artifact takes the
# preserve arm — an edited one and a merely-older one alike — and only the already-
# identical ones reach the `unchanged` arm that records. A pre-manifest consumer
# upgrading across a release that changed a workflow therefore does get a sidecar for
# that workflow. The earlier wording here claimed the opposite ("instead of being handed
# a sidecar for every file they never touched"), which is false against this very
# scenario's own second assertion.
IU_C6="$(_iu_consumer no-manifest)"
_iu_run "$IU_C6" >/dev/null
rm -f "$IU_C6/.prflow/install-manifest.json"
printf '\n# PRE-MANIFEST-LOCAL-EDIT\n' >> "$IU_C6/.github/workflows/devflow-implement.yml"
IU_O6="$(_iu_run "$IU_C6" --apply)"
assert_eq "installer-upgrade: with no manifest, a differing artifact is PRESERVED as provenance-unverified rather than assumed pristine" "yes yes" \
  "$(_iu_out_has "$IU_O6" 'PRESERVED (provenance unverified') $(_iu_has "$IU_C6/.github/workflows/devflow-implement.yml" 'PRE-MANIFEST-LOCAL-EDIT')"
assert_eq "installer-upgrade: with no manifest, an already-identical artifact is left alone and its digest recorded (the manifest heals)" "yes yes" \
  "$(_iu_out_has "$IU_O6" 'unchanged: .github/workflows/devflow.yml') $(python3 -c '
import json, sys
a = json.load(open(sys.argv[1]))["artifacts"]
print("yes" if ".github/workflows/devflow.yml" in a and ".github/workflows/devflow-implement.yml" not in a else "no")
' "$IU_C6/.prflow/install-manifest.json")"

# ── Scenario 7: the consumer deleted something the installer expects. It comes back,
# and the run does not abort part-way through.
IU_C7="$(_iu_consumer deleted)"
_iu_run "$IU_C7" >/dev/null
rm -rf "$IU_C7/.github/actions/vendor-plugin" "$IU_C7/.claude-plugin/marketplace.json" "$IU_C7/.prflow/config.json"
IU_O7="$(_iu_run "$IU_C7" --apply)"; IU_RC7=$?
assert_eq "installer-upgrade: artifacts the consumer deleted are recreated and the run still completes" "0 yes yes yes yes" \
  "$IU_RC7 $([ -f "$IU_C7/.github/actions/vendor-plugin/vendor-slice.sh" ] && echo yes || echo no) $([ -f "$IU_C7/.claude-plugin/marketplace.json" ] && echo yes || echo no) $([ -f "$IU_C7/.prflow/config.json" ] && echo yes || echo no) $(_iu_out_has "$IU_O7" 'done (from')"

# ── Scenario 8: the dry run is a real preview — it reports the SAME classifications the
# apply would, and still writes nothing. Two fixtures in the same starting state: one is
# previewed, one is applied; the preview's plan lines must match the apply's.
IU_C8A="$(_iu_consumer preview-a)"; IU_C8B="$(_iu_consumer preview-b)"
for _iu_c in "$IU_C8A" "$IU_C8B"; do
  _iu_run "$_iu_c" >/dev/null
  printf '\n# LOCAL\n' >> "$_iu_c/.github/workflows/devflow.yml"
  rm -f "$_iu_c/.github/workflows/devflow-implement.yml"
done
IU_SNAP8="$(_iu_snapshot "$IU_C8A")"
IU_PLAN8="$(_iu_run "$IU_C8A" --dry-run | grep -E 'devflow-install: (create|update|unchanged|PRESERVED)')"
IU_APPLIED8="$(_iu_run "$IU_C8B" --apply | grep -E 'devflow-install: (create|update|unchanged|PRESERVED)')"
assert_eq "installer-upgrade: the dry run reports exactly the classifications the apply performs (it runs the same code against a sandbox)" "$IU_APPLIED8" "$IU_PLAN8"
assert_eq "installer-upgrade: the dry run leaves the consumer tree byte-for-byte untouched" "yes" \
  "$([ "$IU_SNAP8" = "$(_iu_snapshot "$IU_C8A")" ] && echo yes || echo no)"
IU_DIFF8="$(_iu_run "$IU_C8A" --dry-run)"
assert_eq "installer-upgrade: the dry run names each file it would ADD with its size, without dumping its whole body as a diff" "yes no" \
  "$(_iu_out_matches "$IU_DIFF8" '^ADD +\.github/workflows/devflow-implement\.yml \([0-9]+ lines\)') $(_iu_out_matches "$IU_DIFF8" '^--- a/\.github/workflows/devflow-implement\.yml')"
# A file that exists on BOTH sides gets a real unified diff body, so the maintainer sees
# the exact bytes before consenting. Staged as a provably-untouched older artifact (the
# skipped-version shape), which is the case the upgrade would rewrite.
IU_C8D="$(_iu_consumer preview-modify)"
_iu_run "$IU_C8D" >/dev/null
python3 -c '
import hashlib, json, sys
root, rel = sys.argv[1], ".github/workflows/devflow.yml"
p = root + "/" + rel
body = open(p, encoding="utf-8").read() + "\n# BYTES FROM AN OLDER DEVFLOW RELEASE\n"
open(p, "w", encoding="utf-8").write(body)
mp = root + "/.prflow/install-manifest.json"
m = json.load(open(mp))
m["artifacts"][rel] = hashlib.sha256(body.encode("utf-8")).hexdigest()
json.dump(m, open(mp, "w"), indent=2)
' "$IU_C8D"
IU_DIFF8D="$(_iu_run "$IU_C8D" --dry-run)"
assert_eq "installer-upgrade: the dry run prints a real unified diff body for a file it would rewrite in place" "yes yes yes" \
  "$(_iu_out_matches "$IU_DIFF8D" '^MODIFY \.github/workflows/devflow\.yml$') $(_iu_out_matches "$IU_DIFF8D" '^--- a/\.github/workflows/devflow\.yml$') $(_iu_out_has "$IU_DIFF8D" '-# BYTES FROM AN OLDER DEVFLOW RELEASE')"
# --dry-run is honored on a FIRST-TIME install too, so a maintainer can preview an
# adoption before any file exists.
IU_C8C="$(_iu_consumer preview-fresh)"
IU_SNAP8C="$(_iu_snapshot "$IU_C8C")"
IU_O8C="$(_iu_run "$IU_C8C" --dry-run)"
assert_eq "installer-upgrade: --dry-run forces the preview on a first-time install and writes nothing" "yes yes" \
  "$(_iu_out_has "$IU_O8C" 'nothing in this repository was written') $([ "$IU_SNAP8C" = "$(_iu_snapshot "$IU_C8C")" ] && echo yes || echo no)"

# ── Scenario 9: nothing outside the intended set changes. Compare the whole-tree
# snapshot across an upgrade and require the delta to be exactly the paths the plan
# named — a partial write or a stray temp file left behind shows up here.
IU_C9="$(_iu_consumer scope)"
_iu_run "$IU_C9" >/dev/null
mkdir -p "$IU_C9/src"
printf 'untouched consumer source\n' > "$IU_C9/src/app.txt"
printf 'consumer CI\n' > "$IU_C9/.github/workflows/consumer-ci.yml"
printf '\n# LOCAL\n' >> "$IU_C9/.github/workflows/devflow.yml"
IU_SNAP9="$(_iu_snapshot "$IU_C9")"
_iu_run "$IU_C9" --apply >/dev/null
assert_eq "installer-upgrade: an upgrade touches only the artifacts it named — the consumer's own files and unrelated workflows are bit-identical afterwards" \
  ".github/workflows/devflow.yml.prflow-new" \
  "$(python3 -c '
import sys
before = dict(l.split(" ", 1) for l in sys.argv[1].splitlines() if l)
after = dict(l.split(" ", 1) for l in sys.argv[2].splitlines() if l)
changed = set(before) ^ set(after)
changed |= {k for k in set(before) & set(after) if before[k] != after[k]}
print("\n".join(sorted(changed)))
' "$IU_SNAP9" "$(_iu_snapshot "$IU_C9")")"

# ── Scenario 10: argument handling. A typo must never select the writing mode.
IU_C10="$(_iu_consumer args)"
_iu_run "$IU_C10" >/dev/null
IU_O10="$(_iu_run "$IU_C10" --dryrun)" && IU_RC10=0 || IU_RC10=$?
assert_eq "installer-upgrade: an unrecognized flag exits 2 naming the accepted set, rather than falling through to a write" "2 yes" \
  "$IU_RC10 $(_iu_out_has "$IU_O10" 'unknown argument --dryrun (accepted: --dry-run, --apply, --remove-withheld-review-tier)')"
assert_eq "installer-upgrade: DEVFLOW_APPLY=1 selects the writing mode for a curl-piped invocation that cannot pass a flag" "yes" \
  "$(printf '%s' "$( cd "$IU_C10" && env DEVFLOW_SRC="$IU_SRC" DEVFLOW_REF="$IU_REF" DEVFLOW_APPLY=1 bash "$IU_INSTALL" 2>&1 )" | grep -qF 'running in apply mode.' && echo yes || echo no)"

# ── Scenario 11: identifier migration stays NAME-AGNOSTIC. The installer spells no
# identifier: it reads the canonical pair and the superseded set out of its generated
# identity region, so declaring an alias in lib/plugin-identity.json is the ONLY edit a
# rename needs. Driven over a temp plugin root whose manifest is renamed and whose
# previous name is declared as an alias, with the region regenerated by the real
# generator — never by patching the installer text.
IU_P11="$(mktemp -d "$_iw_tmp_root/p11.XXXXXX")"
mkdir -p "$IU_P11/lib" "$IU_P11/.claude-plugin" "$IU_P11/.github/actions/vendor-plugin" \
         "$IU_P11/.github/workflows" "$IU_P11/scripts"
cp "$LIB/plugin_identity.py" "$LIB/generate-plugin-identity.py" "$LIB/plugin-identity.json" "$IU_P11/lib/"
cp "$LIB/../.claude-plugin/plugin.json" "$IU_P11/.claude-plugin/"
cp "$IU_INSTALL" "$IU_P11/install.sh"
# The generator rewrites every region it knows about, so give it the other three files
# too; only install.sh is read back.
cp "$LIB/../.github/actions/vendor-plugin/vendor-slice.sh" "$IU_P11/.github/actions/vendor-plugin/"
cp "$LIB/../.github/workflows/devflow-runner.yml" "$IU_P11/.github/workflows/"
cp "$LIB/../scripts/resolve-extra-plugins.sh" "$IU_P11/scripts/"
# Fixture identifiers, deliberately neutral: this arm proves the MECHANISM, and the
# names it uses must not read as a proposed product name.
python3 -c '
import json, sys
root = sys.argv[1]
mp = root + "/.claude-plugin/plugin.json"
m = json.load(open(mp))
previous = m["name"]
m["name"] = "fixture-plugin-two"
json.dump(m, open(mp, "w"), indent=2)
ip = root + "/lib/plugin-identity.json"
i = json.load(open(ip))
i["plugin_aliases"] = [previous] + [a for a in i.get("plugin_aliases", []) if a != previous]
i["marketplace_aliases"] = [i["marketplace_canonical"]]
i["marketplace_canonical"] = "fixture-market-two"
json.dump(i, open(ip, "w"), indent=2)
' "$IU_P11"
python3 "$IU_P11/lib/generate-plugin-identity.py" >/dev/null 2>&1
assert_eq "installer-upgrade identity: regenerating after a declared rename bakes the NEW canonical pair and the superseded ids into install.sh, with no literal hand-edited" "yes yes yes" \
  "$(_iu_has "$IU_P11/install.sh" "DEVFLOW_PLUGIN_CANONICAL='fixture-plugin-two'") $(_iu_has "$IU_P11/install.sh" "DEVFLOW_MARKETPLACE_CANONICAL='fixture-market-two'") $(_iu_out_matches "$(cat "$IU_P11/install.sh")" "^DEVFLOW_SUPERSEDED_PLUGIN_SPECS='[^']+'")"
# A consumer previously installed under the OLD identifiers, upgrading with the renamed
# installer: the marketplace manifest it owns is rewritten to the canonical pair, and the
# settings file it does NOT own is reported, never written.
IU_C11="$(_iu_consumer rename)"
_iu_run "$IU_C11" >/dev/null                     # install under today's identifiers
mkdir -p "$IU_C11/.claude"
python3 -c '
import json, sys
p = sys.argv[1] + "/.claude/settings.json"
json.dump({"extraKnownMarketplaces": {"devflow-marketplace": {"source": {"source": "github", "repo": "The01Geek/prflow"}, "autoUpdate": True},
                                      "unrelated-market": {"source": {"source": "github", "repo": "someone/else"}}},
           "enabledPlugins": {"devflow@devflow-marketplace": True, "other@unrelated-market": True}},
          open(p, "w"), indent=2)
' "$IU_C11"
IU_SET11_BEFORE="$(_iu_digest "$IU_C11/.claude/settings.json")"
IU_O11="$(IU_INSTALL_BIN="$IU_P11/install.sh" _iu_run "$IU_C11" --apply)"
assert_eq "installer-upgrade identity: a superseded registration in .claude/settings.json is REPORTED and the file left byte-for-byte unchanged (install.sh never writes it)" "yes yes yes" \
  "$(_iu_out_has "$IU_O11" 'still registers superseded DevFlow identifiers') $(_iu_out_has "$IU_O11" 'enabledPlugins[devflow@devflow-marketplace]') $([ "$IU_SET11_BEFORE" = "$(_iu_digest "$IU_C11/.claude/settings.json")" ] && echo yes || echo no)"
assert_eq "installer-upgrade identity: the report routes the consumer to the ONE owner of that migration rather than duplicating it" "yes" \
  "$(_iu_out_has "$IU_O11" 'run /prflow:init, whose scripts/provision-local-settings.sh removes the superseded registrations')"
assert_eq "installer-upgrade identity: the marketplace manifest the installer OWNS is migrated to the new canonical pair" "fixture-market-two fixture-plugin-two" \
  "$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
print(d["name"], d["plugins"][0]["name"])
' "$IU_C11/.claude-plugin/marketplace.json")"
assert_eq "installer-upgrade identity: an unrelated marketplace/plugin registration is never named as superseded" "no no" \
  "$(_iu_out_has "$IU_O11" 'unrelated-market') $(_iu_out_has "$IU_O11" 'other@unrelated-market')"
# The SHIPPED installer's own declared alias set is not registered in this consumer's
# settings, so the migration report stays silent: the report is driven by an INTERSECTION
# of the declared superseded ids with what the consumer actually registered, not by the
# mere existence of a declared alias.
# Driven over its OWN consumer, registering only identifiers the shipped installer does
# not declare superseded. Reusing the scenario-11 consumer would silently stop testing
# this the moment the shipped identity declares a real alias: that consumer registers
# `devflow@devflow-marketplace` precisely so the arm above can see it reported, so the
# intersection would be non-empty and the "reports nothing" premise false.
IU_C11B="$(_iu_consumer nosuperseded)"
_iu_run "$IU_C11B" >/dev/null
mkdir -p "$IU_C11B/.claude"
python3 -c '
import json, sys
p = sys.argv[1] + "/.claude/settings.json"
json.dump({"extraKnownMarketplaces": {"unrelated-market": {"source": {"source": "github", "repo": "someone/else"}}},
           "enabledPlugins": {"other@unrelated-market": True}},
          open(p, "w"), indent=2)
' "$IU_C11B"
assert_eq "installer-upgrade identity: the shipped installer reports nothing superseded when none of its declared superseded ids is registered" "no" \
  "$(printf '%s' "$(_iu_run "$IU_C11B" --apply)" | grep -qF 'superseded DevFlow identifiers' && echo yes || echo no)"
# Non-vacuity control: the shipped installer really does declare a superseded id, so the
# silence above is an empty INTERSECTION and not an empty declared set.
assert_eq "installer-upgrade identity: the shipped installer declares a non-empty superseded plugin-spec set" "yes" \
  "$(_iu_out_matches "$(cat "$IU_INSTALL")" "^DEVFLOW_SUPERSEDED_PLUGIN_SPECS='[^']+'")"

rm -rf "$IU_P11"

# ── Scenario 11c: the SAME detect-and-route split, applied to .prflow/config.json.
# The PR-authoring App was renamed, and the config scaffolder is add-only — it can backfill
# a key but never rename a VALUE — so a consumer's `devflow.allowed_bots` keeps naming an
# App slug that authorizes nothing. The installer must REPORT that and route to
# /prflow:init, and must not write the file itself.
#
# Driven end to end over a real fixture consumer first (the routing + the never-writes
# invariant can only be established by an actual before/after), then at the FUNCTION level
# for the adversarial shape matrix: this is a best-effort parser over a file a human
# hand-edits, and a full installer run per row would obscure which shape produced which
# answer.
IU_C11C="$(_iu_consumer stale-config)"
_iu_run "$IU_C11C" >/dev/null                     # scaffold a config the normal way
python3 -c '
import json, sys
p = sys.argv[1] + "/.prflow/config.json"
d = json.load(open(p))
# Written under the CURRENT block name: this scenario is about a stale App-slug VALUE
# (issue #987), not a stale key. Writing it under the superseded block would additionally
# make the fixture a both-blocks-present migration case, and the non-vacuity control
# below would then read the scaffolded default out of the other block.
d.setdefault("prflow", {})["allowed_bots"] = "claude,devflow-autopilot,dependabot"
json.dump(d, open(p, "w"), indent=2)
' "$IU_C11C"
_iu_allowed_bots() {  # $1 = consumer root -> the allowed_bots VALUE, or RC
  # Reads whichever top-level block the config actually carries. The issue-#1002 key
  # migration moves this value from `devflow` to `prflow` without changing a byte of it,
  # and the invariant these call sites assert is that the installer never rewrites the
  # VALUE — so a reader hardcoded to one block name would report RC after a migration
  # and fail an assertion about something that did not happen.
  python3 -c '
import json, sys
try:
    d = json.load(open(sys.argv[1] + "/.prflow/config.json"))
    for block in ("prflow", "devflow"):
        section = d.get(block)
        if isinstance(section, dict) and "allowed_bots" in section:
            print(section["allowed_bots"])
            break
    else:
        print("RC")
except Exception:
    print("RC")
' "$1"
}
IU_CFG11C_BEFORE="$(_iu_allowed_bots "$IU_C11C")"
IU_O11C="$(_iu_run "$IU_C11C" --apply)"
# The unchanged-ness asserted is the VALUE the notice is about, not the whole file: an
# --apply upgrade legitimately re-stamps prflow_version (step 6) on the same file, so a
# whole-file digest would assert something the installer never promised and would go green
# for the wrong reason if it stopped re-stamping.
assert_eq "installer-upgrade stale-config: a superseded App slug in allowed_bots is REPORTED under the block the config actually carries, names the replacement, and the value itself is left untouched" "yes yes claude,devflow-autopilot,dependabot" \
  "$(_iu_out_has "$IU_O11C" 'still names superseded PRFlow identifiers') $(_iu_out_has "$IU_O11C" 'prflow.allowed_bots[devflow-autopilot -> prflow-implementer]') $(_iu_allowed_bots "$IU_C11C")"
assert_eq "installer-upgrade stale-config: the fixture really did carry the stale slug before the run (the invariant above is not comparing two absent values)" "claude,devflow-autopilot,dependabot" \
  "$IU_CFG11C_BEFORE"
assert_eq "installer-upgrade stale-config: the report routes to the ONE owner of the correction rather than growing a second copy of it" "yes" \
  "$(_iu_out_has "$IU_O11C" 'run /prflow:init, which corrects them in place')"
# MISS arm over its own consumer: the scaffolded default names no superseded slug, so the
# report stays silent. Reusing the consumer above would make this vacuous.
IU_C11D="$(_iu_consumer clean-config)"
IU_O11D="$(_iu_run "$IU_C11D" --apply)"
assert_eq "installer-upgrade stale-config: a config naming no superseded identifier is reported silently (the notice is an intersection, not a declared-set existence check)" "no" \
  "$(_iu_out_has "$IU_O11D" 'still names superseded PRFlow identifiers')"
# Non-vacuity control: the shipped installer really does declare a stale pair, so the
# silence above is an empty intersection and not an empty declared set.
assert_eq "installer-upgrade stale-config: the shipped installer declares a non-empty stale-bot-login set" "yes" \
  "$(_iu_out_matches "$(cat "$IU_INSTALL")" "^DEVFLOW_STALE_BOT_LOGINS='[^']+'")"

# The adversarial input-shape matrix. Every row must exit 0 and print NOTHING but the
# genuine hit rows — a shape that detonates the scan, or one that is read as a hit, is the
# bug class here. Root x {object, array, scalar}; `devflow` x {object, array, scalar,
# missing}; `allowed_bots` x {string, array, object, valid-falsy, missing, wrong-type}.
_iu_cfg_shape() {  # $1 = literal config bytes -> the scan's stdout (empty = no hit)
  printf '%s' "$1" > "$IU_C11C/.prflow/config.json"
  # shellcheck disable=SC1090  # sources install.sh at runtime under DEVFLOW_SELFTEST
  ( cd "$IU_C11C" && DEVFLOW_SELFTEST=1 . "$IU_INSTALL" \
      && "${DEVFLOW_PY:-python3}" -c "$DEVFLOW_CONFIG_SCAN_PY" .prflow/config.json \
           "$DEVFLOW_STALE_BOT_LOGINS" ) 2>/dev/null
}
# Post-#1002 the scan names the block the config carries at scan time; an --apply run
# migrates the seven top-level keys before the report, so that block is `prflow`.
IU_CFG_HIT='prflow.allowed_bots[devflow-autopilot -> prflow-implementer]'
assert_eq "installer stale-config matrix: the plain hit shape is detected (the matrix below is not vacuously silent)" "$IU_CFG_HIT" \
  "$(_iu_cfg_shape '{"prflow": {"allowed_bots": "claude,devflow-autopilot"}}')"
assert_eq "installer stale-config matrix: a [bot]-suffixed entry with surrounding whitespace is the same login" "$IU_CFG_HIT" \
  "$(_iu_cfg_shape '{"prflow": {"allowed_bots": "claude,  devflow-autopilot[bot] , x"}}')"
assert_eq "installer stale-config matrix: the stale entry is reported even when the replacement is ALREADY listed (a dead entry is still dead)" "$IU_CFG_HIT" \
  "$(_iu_cfg_shape '{"prflow": {"allowed_bots": "prflow-implementer,devflow-autopilot"}}')"
assert_eq "installer stale-config matrix: a login that merely CONTAINS the stale slug is not a hit (entries compare whole, never by substring)" "" \
  "$(_iu_cfg_shape '{"prflow": {"allowed_bots": "not-devflow-autopilot-either"}}')"
assert_eq "installer stale-config matrix: malformed JSON degrades silently rather than detonating the scan" "" \
  "$(_iu_cfg_shape '{"prflow": {"allowed_bots": ')"
assert_eq "installer stale-config matrix: an empty file degrades" "" "$(_iu_cfg_shape '')"
assert_eq "installer stale-config matrix: a top-level ARRAY is not indexed as a mapping" "" \
  "$(_iu_cfg_shape '[{"prflow": {"allowed_bots": "devflow-autopilot"}}]')"
assert_eq "installer stale-config matrix: a top-level scalar degrades" "" "$(_iu_cfg_shape '42')"
assert_eq "installer stale-config matrix: a devflow ARRAY is not indexed as a mapping" "" \
  "$(_iu_cfg_shape '{"prflow": ["allowed_bots", "devflow-autopilot"]}')"
assert_eq "installer stale-config matrix: a devflow scalar degrades" "" \
  "$(_iu_cfg_shape '{"prflow": "devflow-autopilot"}')"
assert_eq "installer stale-config matrix: an absent devflow section degrades" "" \
  "$(_iu_cfg_shape '{"base_branch": "main"}')"
assert_eq "installer stale-config matrix: an absent allowed_bots key degrades" "" \
  "$(_iu_cfg_shape '{"prflow": {"effort": "high"}}')"
assert_eq "installer stale-config matrix: an allowed_bots ARRAY is not read as a comma string" "" \
  "$(_iu_cfg_shape '{"prflow": {"allowed_bots": ["devflow-autopilot"]}}')"
assert_eq "installer stale-config matrix: an allowed_bots OBJECT degrades" "" \
  "$(_iu_cfg_shape '{"prflow": {"allowed_bots": {"devflow-autopilot": true}}}')"
# The valid-falsy row. An explicit "" / false / 0 is a real config state, not a missing
# key, and none of them may be coerced into a shape the scan reads as a hit.
assert_eq "installer stale-config matrix: a valid-falsy empty-string allowed_bots yields no hit" "" \
  "$(_iu_cfg_shape '{"prflow": {"allowed_bots": ""}}')"
assert_eq "installer stale-config matrix: a valid-falsy false allowed_bots is a wrong TYPE, not an empty string (a bool is an int in Python, never a str)" "" \
  "$(_iu_cfg_shape '{"prflow": {"allowed_bots": false}}')"
assert_eq "installer stale-config matrix: a valid-falsy 0 allowed_bots degrades" "" \
  "$(_iu_cfg_shape '{"prflow": {"allowed_bots": 0}}')"
assert_eq "installer stale-config matrix: a whitespace-and-comma-only allowed_bots yields no entries and no hit" "" \
  "$(_iu_cfg_shape '{"prflow": {"allowed_bots": " , ,  "}}')"

# The absent-file arm, at the function level: no .prflow/config.json at all must be a
# strict no-op, not a warning about a file the consumer never had.
IU_C11E="$(_iu_consumer no-config)"
# shellcheck disable=SC1090  # sources install.sh at runtime under DEVFLOW_SELFTEST
IU_O11E="$( cd "$IU_C11E" && DEVFLOW_SELFTEST=1 . "$IU_INSTALL" \
    && devflow_report_stale_config_identifiers 2>&1 )"
assert_eq "installer stale-config: an absent .prflow/config.json is a strict no-op" "" "$IU_O11E"
# And the documented python3-absent degradation: a warning that names the remedy, never a
# silent skip that would read as "nothing stale here".
printf '{"prflow": {"allowed_bots": "devflow-autopilot"}}' > "$IU_C11C/.prflow/config.json"
# PATH is exported as its OWN statement inside the subshell, never as a prefix on the
# `.` builtin: a `VAR=x . file` prefix scopes to the sourcing alone, so the function call
# after it would run with the real python3 back on PATH and this arm would silently test
# the happy path instead.
# shellcheck disable=SC1090  # sources install.sh at runtime under DEVFLOW_SELFTEST
IU_O11F="$( cd "$IU_C11C" && export PATH="$IU_NOPY:$PATH" && DEVFLOW_SELFTEST=1 . "$IU_INSTALL" \
    && devflow_report_stale_config_identifiers 2>&1 )"
assert_eq "installer stale-config: with no working python3 the check says it could not run and names the remedy, rather than passing silently" "yes yes" \
  "$(_iu_out_has "$IU_O11F" 'could not check .prflow/config.json for superseded PRFlow identifiers') $(_iu_out_has "$IU_O11F" 'run /prflow:init to correct them')"

# ── Scenario 12 (#959): the documented python3-absent FAIL-SAFE, driven end to end.
# This is the arm the original 11 scenarios could not reach, because every one of them
# ran with a working python3 — which is exactly why the installer shipped doing the
# OPPOSITE of its own header for a whole supported host class. devflow_digest() printed
# the empty string when python3 was unavailable, the classifier read an empty current
# digest as "file absent -> create", and the create arm is `rm -rf` + `cp`. So a stock
# Windows / Git-Bash consumer's hand-edits were destroyed, silently, on upgrade.
#
# The contract asserted here is the header's, verbatim: nothing existing is overwritten,
# every present artifact is reported preserved, and the manifest is not written.
IU_C12="$(_iu_consumer nopython3)"
_iu_run "$IU_C12" >/dev/null                        # install while python3 still works
printf '\n# CONSUMER-LOCAL-EDIT-MARKER\n' >> "$IU_C12/.github/workflows/devflow.yml"
IU_WF12_BEFORE="$(_iu_digest "$IU_C12/.github/workflows/devflow.yml")"
IU_MANI12_BEFORE="$(_iu_digest "$IU_C12/.prflow/install-manifest.json")"
IU_SNAP12_BEFORE="$(_iu_snapshot "$IU_C12")"
IU_O12="$(IU_PATH_PREFIX="$IU_NOPY" _iu_run "$IU_C12" --apply)" && IU_RC12=0 || IU_RC12=$?
assert_eq "installer-upgrade #959: an --apply upgrade on a host with no working python3 leaves a hand-edited workflow BYTE-FOR-BYTE intact" "yes yes" \
  "$([ "$IU_WF12_BEFORE" = "$(_iu_digest "$IU_C12/.github/workflows/devflow.yml")" ] && echo yes || echo no) $(_iu_has "$IU_C12/.github/workflows/devflow.yml" 'CONSUMER-LOCAL-EDIT-MARKER')"
# The precise wrong classification: `create` on a path that is right there on disk.
# Asserting its ABSENCE is what makes this arm a regression test for the defect rather
# than for its symptom — a future collapse of unknown onto any writing classification
# has to reintroduce one of these two words.
assert_eq "installer-upgrade #959: no existing artifact is classified create or update when the digest cannot be established" "no no" \
  "$(_iu_out_matches "$IU_O12" '^devflow-install: create: ') $(_iu_out_matches "$IU_O12" '^devflow-install: update: ')"
assert_eq "installer-upgrade #959: each present artifact is reported PRESERVED with provenance UNESTABLISHED, naming the sidecar and the python3 remedy" "yes yes yes" \
  "$(_iu_out_has "$IU_O12" 'PRESERVED (provenance UNESTABLISHED') $(_iu_out_has "$IU_O12" '.github/workflows/devflow.yml — the new version is at .github/workflows/devflow.yml.prflow-new') $(_iu_out_has "$IU_O12" 'There is no working python3 on this host, so NOTHING on this run could be compared')"
# `unverified` ("no recorded digest") is a DIFFERENT diagnosis with a different remedy;
# reporting a python3-less host that way would send the consumer to delete their files.
assert_eq "installer-upgrade #959: the unestablished-digest preserve is not misreported as the no-recorded-digest one" "no" \
  "$(_iu_out_has "$IU_O12" 'PRESERVED (provenance unverified')"
assert_eq "installer-upgrade #959: the run still exits 0 and offers DevFlow's sidecar copy of the artifact it preserved" "0 yes yes" \
  "$IU_RC12 $([ -f "$IU_C12/.github/workflows/devflow.yml.prflow-new" ] && echo yes || echo no) $([ "$(_iu_digest "$IU_C12/.github/workflows/devflow.yml.prflow-new")" = "$(_iu_digest "$IU_SRC/.github/workflows/devflow.yml")" ] && echo yes || echo no)"
assert_eq "installer-upgrade #959: the manifest is left byte-for-byte alone (an unestablishable digest must never be recorded as provenance) and the run says so" "yes yes" \
  "$([ "$IU_MANI12_BEFORE" = "$(_iu_digest "$IU_C12/.prflow/install-manifest.json")" ] && echo yes || echo no) $(_iu_out_has "$IU_O12" 'the install provenance manifest (.prflow/install-manifest.json) was not written')"
# The whole-tree form of "nothing existing is overwritten": every path present before
# the upgrade is bit-identical after it, so the only delta is additions. Asserted over
# BYTES across the entire fixture, not over the handful of paths the arms above name.
assert_eq "installer-upgrade #959: across the whole tree, not one pre-existing path changed its bytes — the delta is additions only (over a snapshot proven non-empty)" "ok:" \
  "$(python3 -c '
import sys
before = dict(l.split(" ", 1) for l in sys.argv[1].splitlines() if l)
after = dict(l.split(" ", 1) for l in sys.argv[2].splitlines() if l)
bad = [k for k in before if k not in after or after[k] != before[k]]
sys.stdout.write(("ok:" if len(before) > 5 else "EMPTY-SNAPSHOT:") + " ".join(sorted(bad)))
' "$IU_SNAP12_BEFORE" "$(_iu_snapshot "$IU_C12")")"
# NEGATIVE CONTROL for the whole of Scenario 12. Reintroduce the exact collapse the fix
# removed — infer absence from an empty digest instead of testing the path — on a copy,
# and require the consumer edit to DISAPPEAR. Without this the arms above could pass on
# an installer that simply never writes anything, and the 11 pre-#959 scenarios are the
# standing proof that a suite can be green while this branch is broken.
IU_MUT12="$(probe_tmp '#959 python3-absent clobber control setup')"
python3 -c '
import sys
src, dst = sys.argv[1], sys.argv[2]
body = open(src, encoding="utf-8").read()
guard = "  if [ ! -e \"$rel\" ] && [ ! -L \"$rel\" ]; then printf \x27create\x27; return 0; fi\n"
collapse = "  cur=\"$(devflow_digest \"$rel\")\" || cur=\"\"\n  [ -n \"$cur\" ] || { printf \x27create\x27; return 0; }\n"
if guard not in body:
    sys.exit("mutation target not found: the existence guard in devflow_artifact_action")
open(dst, "w", encoding="utf-8").write(body.replace(guard, collapse, 1))
' "$IU_INSTALL" "$IU_MUT12" || printf 'devflow-test: #959 control mutation FAILED to apply\n'
# The mutation must be PROVEN to have landed: a rotted pattern would leave the control
# running the fixed installer and silently reporting "preserved" as a pass.
assert_eq "installer-upgrade #959 NEGATIVE CONTROL: the control copy really does reintroduce the empty-digest-means-absent collapse" "yes no" \
  "$(_iu_has "$IU_MUT12" '[ -n "$cur" ] || { printf '"'"'create'"'"'; return 0; }') $(_iu_has "$IU_MUT12" 'if [ ! -e "$rel" ] && [ ! -L "$rel" ]; then')"
IU_C12B="$(_iu_consumer nopython3-control)"
_iu_run "$IU_C12B" >/dev/null
printf '\n# CONSUMER-LOCAL-EDIT-MARKER\n' >> "$IU_C12B/.github/workflows/devflow.yml"
IU_O12B="$(IU_INSTALL_BIN="$IU_MUT12" IU_PATH_PREFIX="$IU_NOPY" _iu_run "$IU_C12B" --apply)" || true
assert_eq "installer-upgrade #959 NEGATIVE CONTROL: the collapsed classifier DOES destroy the consumer edit and calls the existing file create (so Scenario 12 is not vacuous)" "no yes" \
  "$(_iu_has "$IU_C12B/.github/workflows/devflow.yml" 'CONSUMER-LOCAL-EDIT-MARKER') $(_iu_out_matches "$IU_O12B" '^devflow-install: create: \.github/workflows/devflow\.yml$')"
rm -f "$IU_MUT12"

# ── Scenario 13 (#959, same root): a digest ERROR on a PRESENT artifact, with a fully
# working python3. The second reachable form of the same defect — `2>/dev/null || printf
# ''` mapped every interpreter failure onto "absent", so a read error on an existing
# artifact wiped and replaced it while masking the real cause as "this doesn't exist yet".
#
# Both arms are induced with a DANGLING SYMLINK rather than a chmod, deliberately: a
# permission-based unreadable file is not reproducible for a run that happens to be root
# (some CI containers are), and a check whose condition the host can dissolve is a check
# that quietly stops testing anything.
IU_C13="$(_iu_consumer digest-error)"
_iu_run "$IU_C13" >/dev/null
# 13a: a FILE artifact that exists as a dangling symlink. `[ -L ]` sees it, `[ -e ]` does
# not, and python3 reports it absent — an established-absence answer about a path the
# builtin test says is there. That disagreement is itself "unestablished".
rm -f "$IU_C13/.github/workflows/devflow.yml"
ln -s ./no-such-target.yml "$IU_C13/.github/workflows/devflow.yml"
# 13b: a DIRECTORY artifact whose os.walk digest cannot complete, because one entry
# inside it cannot be opened. This is the composite-action shape the review called the
# most likely to fail, and it is also the first coverage of directory-artifact behavior
# at all: every earlier preservation arm edited a single-file workflow.
printf '# INNER-DIRECTORY-MARKER\n' >> "$IU_C13/.github/actions/vendor-plugin/vendor-slice.sh"
ln -s ./no-such-inner-file "$IU_C13/.github/actions/vendor-plugin/dangling"
IU_SNAP13_BEFORE="$(_iu_snapshot "$IU_C13")"
IU_O13="$(_iu_run "$IU_C13" --apply)" && IU_RC13=0 || IU_RC13=$?
assert_eq "installer-upgrade #959: a present FILE artifact whose digest cannot be established is preserved as-is — still a symlink, never replaced by a copy" "0 yes yes" \
  "$IU_RC13 $([ -L "$IU_C13/.github/workflows/devflow.yml" ] && echo yes || echo no) $([ -f "$IU_C13/.github/workflows/devflow.yml.prflow-new" ] && echo yes || echo no)"
assert_eq "installer-upgrade #959: a DIRECTORY artifact whose walk digest errors is preserved with its inner contents intact, and its replacement offered beside it" "yes yes yes" \
  "$(_iu_has "$IU_C13/.github/actions/vendor-plugin/vendor-slice.sh" 'INNER-DIRECTORY-MARKER') $([ -L "$IU_C13/.github/actions/vendor-plugin/dangling" ] && echo yes || echo no) $([ -d "$IU_C13/.github/actions/vendor-plugin.prflow-new" ] && echo yes || echo no)"
assert_eq "installer-upgrade #959: the digest error is reported as an unestablished provenance, not masked as a fresh create" "yes no no" \
  "$(_iu_out_has "$IU_O13" 'PRESERVED (provenance UNESTABLISHED') $(_iu_out_matches "$IU_O13" '^devflow-install: create: \.github/workflows/devflow\.yml$') $(_iu_out_matches "$IU_O13" '^devflow-install: create: \.github/actions/vendor-plugin$')"
# The `ok:` prefix is the anti-vacuity half: a snapshot helper that failed on the planted
# dangling symlink would print nothing, and comparing two empty snapshots would satisfy an
# emptiness assertion while measuring absolutely nothing.
assert_eq "installer-upgrade #959: a digest error touches no pre-existing bytes anywhere in the tree (over a snapshot proven non-empty)" "ok:" \
  "$(python3 -c '
import sys
before = dict(l.split(" ", 1) for l in sys.argv[1].splitlines() if l)
after = dict(l.split(" ", 1) for l in sys.argv[2].splitlines() if l)
bad = [k for k in before if k not in after or after[k] != before[k]]
sys.stdout.write(("ok:" if len(before) > 5 else "EMPTY-SNAPSHOT:") + " ".join(sorted(bad)))
' "$IU_SNAP13_BEFORE" "$(_iu_snapshot "$IU_C13")")"

# ── Scenario 13b (#959 review round 3): the two fail-safe TRIGGERS have different blast
# radii, and every prose surface describing them got that wrong three review rounds
# running. Pin the distinction executably so the next reader can check it instead of
# reasoning it out again:
#   GLOBAL (no python3)  -> nothing digestible: EVERY artifact preserved, NO manifest.
#   PER-ARTIFACT (read error, python3 fine) -> only that path preserved; everything else
#                           written normally, and the manifest IS still written.
# Scenario 12 already covers the global arm's tally; this is the per-artifact contrast,
# which is the half the prose kept over-generalizing from.
IU_C13B="$(_iu_consumer digest-error-radius)"
_iu_run "$IU_C13B" >/dev/null
# Exactly ONE artifact made undigestable, with a fully working python3.
rm -f "$IU_C13B/.github/workflows/devflow.yml"
ln -s ./no-such-target.yml "$IU_C13B/.github/workflows/devflow.yml"
# Give another artifact genuinely new bytes to prove it is still WRITTEN on this run.
printf '\n# BYTES FROM AN OLDER DEVFLOW RELEASE\n' >> "$IU_C13B/.github/workflows/devflow-implement.yml"
python3 -c '
import hashlib, json, sys
root, rel = sys.argv[1], ".github/workflows/devflow-implement.yml"
m = json.load(open(root + "/.prflow/install-manifest.json"))
m["artifacts"][rel] = hashlib.sha256(open(root + "/" + rel, "rb").read()).hexdigest()
json.dump(m, open(root + "/.prflow/install-manifest.json", "w"), indent=2)
' "$IU_C13B"
IU_O13B="$(_iu_run "$IU_C13B" --apply)"
assert_eq "installer-upgrade #959: a per-artifact read error preserves ONLY that artifact — the others are still classified and written" "yes yes" \
  "$(_iu_out_has "$IU_O13B" 'PRESERVED (provenance UNESTABLISHED') $(_iu_out_matches "$IU_O13B" '^devflow-install: update: \.github/workflows/devflow-implement\.yml$')"
# Asserted over the manifest's CONTENT, not its byte-identity: the written-back digest for
# the updated artifact happens to equal what the first install recorded (the update restores
# the shipped bytes), so a whole-file comparison would read "unchanged" on a manifest that
# was genuinely rewritten. What matters is which entries it now holds — the updated artifact
# re-recorded against the shipped bytes, and the erroring one keeping its EARLIER digest
# rather than being re-blessed against bytes nothing could read.
assert_eq "installer-upgrade #959: and the manifest IS still written on a per-artifact read error (unlike the no-python3 trigger, which writes none)" "yes recorded-source kept-earlier" \
  "$(_iu_out_has "$IU_O13B" 'recorded install provenance in .prflow/install-manifest.json') $(python3 -c '
import hashlib, json, sys
root, src = sys.argv[1], sys.argv[2]
arts = json.load(open(root + "/.prflow/install-manifest.json"))["artifacts"]
impl = ".github/workflows/devflow-implement.yml"
want = hashlib.sha256(open(src + "/" + impl, "rb").read()).hexdigest()
wf = ".github/workflows/devflow.yml"
# The erroring artifact keeps a real 64-hex digest from before the error - never dropped,
# and never recomputed from the unreadable path.
kept = isinstance(arts.get(wf), str) and len(arts.get(wf, "")) == 64
sys.stdout.write(("recorded-source" if arts.get(impl) == want else "NOT-RECORDED")
                 + " " + ("kept-earlier" if kept else "LOST"))
' "$IU_C13B" "$IU_SRC")"
# The remedy the message names must match the cause. Telling a consumer whose python3
# works to "resolve a working python3" is the same class of error as the original Critical:
# reporting a fact the code never established.
assert_eq "installer-upgrade #959: the per-artifact message names a READ error on that path, and never the no-python3 remedy" "yes no" \
  "$(_iu_out_has "$IU_O13B" 'python3 works here, so this is a read error on this path') $(_iu_out_has "$IU_O13B" 'There is no working python3 on this host')"
# …and the converse, so neither message can drift into the other's trigger.
assert_eq "installer-upgrade #959: the no-python3 message never claims a per-path read error" "no" \
  "$(_iu_out_has "$IU_O12" 'python3 works here, so this is a read error on this path')"

# ── Scenario 14 (#959): POSITIVE CONTROL. The fix must be "preserve what is there", not
# "never write". A genuinely absent path still has to be created — including on the very
# host that triggered the defect, where no digest is available to prove absence with. If
# this arm ever fails, the fail-safe has turned into a fail-shut and a python3-less
# consumer can no longer install at all.
IU_C14="$(_iu_consumer nopython3-create)"
_iu_run "$IU_C14" >/dev/null
rm -f "$IU_C14/.github/workflows/devflow-implement.yml"
rm -rf "$IU_C14/.github/actions/setup-project-env"
IU_O14="$(IU_PATH_PREFIX="$IU_NOPY" _iu_run "$IU_C14" --apply)"
assert_eq "installer-upgrade #959 POSITIVE CONTROL: with no working python3, a genuinely absent file and directory are still created, and reported as create" "yes yes yes yes" \
  "$([ -f "$IU_C14/.github/workflows/devflow-implement.yml" ] && echo yes || echo no) $([ -d "$IU_C14/.github/actions/setup-project-env" ] && echo yes || echo no) $(_iu_out_matches "$IU_O14" '^devflow-install: create: \.github/workflows/devflow-implement\.yml$') $(_iu_out_matches "$IU_O14" '^devflow-install: create: \.github/actions/setup-project-env$')"
# …and the green-field case: a first-time install on a python3-less host must land the
# whole artifact set, because absence is now decided without the interpreter.
IU_C14B="$(_iu_consumer nopython3-fresh)"
IU_O14B="$(IU_PATH_PREFIX="$IU_NOPY" _iu_run "$IU_C14B")"
assert_eq "installer-upgrade #959 POSITIVE CONTROL: a first-time install on a python3-less host still installs every owned artifact" "yes yes yes yes" \
  "$(_iu_out_has "$IU_O14B" 'detected a first-time installation; running in apply mode.') $([ -f "$IU_C14B/.github/workflows/devflow.yml" ] && echo yes || echo no) $([ -f "$IU_C14B/.claude-plugin/marketplace.json" ] && echo yes || echo no) $([ -d "$IU_C14B/.github/actions/vendor-plugin" ] && echo yes || echo no)"

# ── Scenario 15 (#959): the manifest is a best-effort parser over a file a human can
# hand-corrupt, so it gets the adversarial input-shape matrix CLAUDE.md requires rather
# than only the "deleted it" row Scenario 6 covers. Every malformed shape must degrade to
# an empty recorded digest — never to a spurious match, which would classify a
# hand-edited artifact as `update` and clobber it.
#
# Driven by sourcing the installer under DEVFLOW_SELFTEST=1 and calling the two functions
# directly: the classification is the thing under test, and a full installer run per row
# would obscure which shape produced which answer.
IU_C15="$(_iu_consumer manifest-shapes)"
_iu_run "$IU_C15" >/dev/null
printf '\n# SHAPE-MATRIX-LOCAL-EDIT\n' >> "$IU_C15/.github/workflows/devflow.yml"
_iu_manifest_shape() {  # $1 = literal manifest bytes -> "<recorded> <classification>"
  printf '%s' "$1" > "$IU_C15/.prflow/install-manifest.json"
  # shellcheck disable=SC1090  # sources install.sh at runtime under DEVFLOW_SELFTEST
  ( cd "$IU_C15" && DEVFLOW_SELFTEST=1 . "$IU_INSTALL" \
      && printf '%s %s' \
           "$(devflow_recorded_digest '.github/workflows/devflow.yml' || printf 'RC')" \
           "$(devflow_artifact_action '.github/workflows/devflow.yml' "$IU_SRC/.github/workflows/devflow.yml")" ) 2>/dev/null
}
assert_eq "installer-upgrade #959 manifest matrix: truncated JSON yields no recorded digest and preserves the edited artifact" " unverified" \
  "$(_iu_manifest_shape '{"artifacts": {"a": ')"
assert_eq "installer-upgrade #959 manifest matrix: a non-JSON manifest degrades rather than aborting the installer" " unverified" \
  "$(_iu_manifest_shape 'this is not json at all')"
assert_eq "installer-upgrade #959 manifest matrix: an empty manifest file degrades" " unverified" \
  "$(_iu_manifest_shape '')"
assert_eq "installer-upgrade #959 manifest matrix: a top-level ARRAY is not indexed as a mapping" " unverified" \
  "$(_iu_manifest_shape '[{"artifacts": {}}]')"
assert_eq "installer-upgrade #959 manifest matrix: a top-level scalar degrades" " unverified" \
  "$(_iu_manifest_shape '42')"
assert_eq "installer-upgrade #959 manifest matrix: an artifacts ARRAY is not indexed as a mapping" " unverified" \
  "$(_iu_manifest_shape '{"artifacts": [".github/workflows/devflow.yml"]}')"
assert_eq "installer-upgrade #959 manifest matrix: an artifacts SCALAR degrades" " unverified" \
  "$(_iu_manifest_shape '{"artifacts": "everything"}')"
assert_eq "installer-upgrade #959 manifest matrix: a missing artifacts key degrades" " unverified" \
  "$(_iu_manifest_shape '{"manifest_version": 1}')"
assert_eq "installer-upgrade #959 manifest matrix: a NON-STRING entry is not compared against the digest" " unverified" \
  "$(_iu_manifest_shape '{"artifacts": {".github/workflows/devflow.yml": {"sha256": "x"}}}')"
assert_eq "installer-upgrade #959 manifest matrix: a null entry degrades" " unverified" \
  "$(_iu_manifest_shape '{"artifacts": {".github/workflows/devflow.yml": null}}')"
# The matrix must be able to say something OTHER than `unverified`, or every row above is
# satisfied by a function that returns the same word unconditionally. A well-formed
# manifest recording the artifact's PREVIOUS digest classifies the same edited file
# `modified` — a different word, from a real comparison.
assert_eq "installer-upgrade #959 manifest matrix CONTROL: a well-formed manifest yields a real digest and a real comparison" "yes modified" \
  "$(printf '%s' "$(_iu_manifest_shape "$(python3 -c '
import hashlib, json, sys
src = sys.argv[1]
body = open(src, "rb").read()
print(json.dumps({"manifest_version": 1, "artifacts": {".github/workflows/devflow.yml": hashlib.sha256(body).hexdigest()}}))
' "$IU_SRC/.github/workflows/devflow.yml")")" | python3 -c '
import re, sys
rec, _, act = sys.stdin.read().strip().partition(" ")
print(("yes" if re.fullmatch(r"[0-9a-f]{64}", rec) else "no"), act)
')"

# ── Scenario 16 (#959): a DIRECTORY artifact whose inner file was hand-edited is
# preserved, with a working python3. The directory digest walks the tree, so an inner
# edit has to move it — a claim the shipped code made only in a comment until now.
IU_C16="$(_iu_consumer dir-handedit)"
_iu_run "$IU_C16" >/dev/null
printf '\n# COMPOSITE-ACTION-LOCAL-EDIT\n' >> "$IU_C16/.github/actions/vendor-plugin/vendor-slice.sh"
IU_O16="$(_iu_run "$IU_C16" --apply)"
assert_eq "installer-upgrade #959: an inner-file edit inside a composite action marks the whole directory modified and preserves it" "yes yes yes" \
  "$(_iu_out_has "$IU_O16" 'PRESERVED (locally modified since DevFlow wrote it): .github/actions/vendor-plugin') $(_iu_has "$IU_C16/.github/actions/vendor-plugin/vendor-slice.sh" 'COMPOSITE-ACTION-LOCAL-EDIT') $([ -d "$IU_C16/.github/actions/vendor-plugin.prflow-new" ] && echo yes || echo no)"
assert_eq "installer-upgrade #959: the directory sidecar carries DevFlow's copy, not the consumer's edited one" "no" \
  "$(_iu_has "$IU_C16/.github/actions/vendor-plugin.prflow-new/vendor-slice.sh" 'COMPOSITE-ACTION-LOCAL-EDIT')"
# A file ADDED inside the directory moves the digest too (the walk is over the whole set,
# not over the files DevFlow shipped), so a consumer's extra file is not silently wiped
# by the `rm -rf`+`cp -R` the update arm performs.
IU_C16B="$(_iu_consumer dir-addfile)"
_iu_run "$IU_C16B" >/dev/null
printf 'consumer addition\n' > "$IU_C16B/.github/actions/vendor-plugin/consumer-extra.sh"
_iu_run "$IU_C16B" --apply >/dev/null
assert_eq "installer-upgrade #959: a file the consumer ADDED inside a composite action survives the upgrade" "yes" \
  "$([ -f "$IU_C16B/.github/actions/vendor-plugin/consumer-extra.sh" ] && echo yes || echo no)"

# ── Scenario 17 (#959): the withheld-tier config disabler is a best-effort parser too.
# Scenario 4 covers only its success arm; these are the two non-happy exits — a config
# that is not a JSON object (rc 3) and one where the key is already false (rc 4) — which
# must produce their own distinct breadcrumbs and never restructure the consumer's config.
IU_C17="$(_iu_consumer withheld-shapes)"
_iu_run "$IU_C17" >/dev/null
_iu_withheld_file devflow-review > "$IU_C17/.github/workflows/devflow-review.yml"
printf '[1, 2, 3]\n' > "$IU_C17/.prflow/config.json"
IU_CFG17_BEFORE="$(_iu_digest "$IU_C17/.prflow/config.json")"
IU_O17="$(_iu_run "$IU_C17" --apply --remove-withheld-review-tier)"
assert_eq "installer-upgrade #959: a non-object .prflow/config.json is reported and left byte-for-byte alone, never restructured" "yes yes" \
  "$(_iu_out_has "$IU_O17" 'it is missing, malformed, or holds a non-object at that key') $([ "$IU_CFG17_BEFORE" = "$(_iu_digest "$IU_C17/.prflow/config.json")" ] && echo yes || echo no)"
IU_C17B="$(_iu_consumer withheld-already-false)"
_iu_run "$IU_C17B" >/dev/null
_iu_withheld_file devflow-review > "$IU_C17B/.github/workflows/devflow-review.yml"
python3 -c '
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["workflows"] = dict(d.get("workflows") or {}, **{"prflow-review": False})
json.dump(d, open(p, "w"), indent=2)
' "$IU_C17B/.prflow/config.json"
IU_O17B="$(_iu_run "$IU_C17B" --apply --remove-withheld-review-tier)"
assert_eq "installer-upgrade #959: an already-false review key is reported as already-false, distinctly from a failure" "yes no" \
  "$(_iu_out_has "$IU_O17B" 'is already false in .prflow/config.json') $(_iu_out_has "$IU_O17B" 'could not set workflows')"
# A non-object `workflows` value takes the same rc-3 arm — the config is not rewritten
# underneath the consumer just because one key holds the wrong type.
IU_C17C="$(_iu_consumer withheld-nonobject-workflows)"
_iu_run "$IU_C17C" >/dev/null
_iu_withheld_file devflow-review > "$IU_C17C/.github/workflows/devflow-review.yml"
python3 -c '
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["workflows"] = "all of them"
json.dump(d, open(p, "w"), indent=2)
' "$IU_C17C/.prflow/config.json"
IU_O17C="$(_iu_run "$IU_C17C" --apply --remove-withheld-review-tier)"
assert_eq "installer-upgrade #959: a non-object workflows value is reported and the config left with that value intact" "yes all of them" \
  "$(_iu_out_has "$IU_O17C" 'it is missing, malformed, or holds a non-object at that key') $(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["workflows"])' "$IU_C17C/.prflow/config.json")"

# ── Scenario 18 (#959 review, suggestion 1): the dry run must SHOW the one deletion it
# performs outside .github. prune_stale_vendored_plugin removes a pre-relocation
# .claude/plugins/devflow tree; devflow_build_preview already copies that subtree into
# the sandbox so the prune runs there, but until .claude/plugins entered the DIFF scope
# the renderer never walked it — so the promised "unified diff of every byte it would
# change" silently omitted a recursive delete. Same class as this round's Critical: a
# promise the code did not keep.
IU_C18="$(_iu_consumer preview-prune)"
_iu_run "$IU_C18" >/dev/null
mkdir -p "$IU_C18/.claude/plugins/devflow/.claude-plugin"
printf '{\n  "name": "devflow",\n  "version": "0.0.1"\n}\n' > "$IU_C18/.claude/plugins/devflow/.claude-plugin/plugin.json"
printf 'stale vendored payload\n' > "$IU_C18/.claude/plugins/devflow/marker.txt"
IU_SNAP18="$(_iu_snapshot "$IU_C18")"
IU_O18="$(_iu_run "$IU_C18" --dry-run)"
assert_eq "installer-upgrade #959: the dry run shows the stale-plugin deletion in its diff, not only in the plan log" "yes yes" \
  "$(_iu_out_has "$IU_O18" 'removed stale committed plugin at .claude/plugins/devflow') $(_iu_out_matches "$IU_O18" '^DELETE \.claude/plugins/devflow/marker\.txt$')"
assert_eq "installer-upgrade #959: and that dry run still writes nothing at all" "yes" \
  "$([ "$IU_SNAP18" = "$(_iu_snapshot "$IU_C18")" ] && echo yes || echo no)"
# The consumer's wider .claude/ is NOT diffed: only `plugins` is in scope, so a settings
# file the installer never writes never appears in the preview.
mkdir -p "$IU_C18/.claude"
printf '{"consumerOnly": true}\n' > "$IU_C18/.claude/settings.json"
assert_eq "installer-upgrade #959: the preview scope stays narrowed to .claude/plugins — the consumer's own .claude files are never diffed" "no" \
  "$(_iu_out_has "$(_iu_run "$IU_C18" --dry-run)" '.claude/settings.json')"
# The apply performs exactly what the preview showed.
_iu_run "$IU_C18" --apply >/dev/null
assert_eq "installer-upgrade #959: the apply really does remove the stale tree the preview named" "no" \
  "$([ -e "$IU_C18/.claude/plugins/devflow" ] && echo yes || echo no)"

# ── Scenario 19 (#959 review, suggestion 2): the withheld-tier opt-in disables the config
# key BEFORE deleting the workflow files. The two interrupted states are not symmetric —
# "files gone, key still true" is unrecoverable, because devflow_remove_withheld_tier
# returns at its own `present` gate on every later run and never reaches the config edit
# again. Asserted through the ORDER of the emitted lines, which is the only externally
# visible evidence of the sequence.
IU_C19="$(_iu_consumer withheld-order)"
_iu_run "$IU_C19" >/dev/null
for _iu_w in devflow-review devflow-runner telemetry-push; do
  _iu_withheld_file "$_iu_w" > "$IU_C19/.github/workflows/$_iu_w.yml"
done
# A repository that still RUNS the withheld tier has the key true — the shipped example
# already ships it false, so without this the rc-4 "already false" arm fires and the
# ordering would be asserted over the wrong branch.
python3 -c '
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["workflows"] = dict(d.get("workflows") or {}, **{"prflow-review": True})
json.dump(d, open(p, "w"), indent=2)
' "$IU_C19/.prflow/config.json"
IU_O19="$(_iu_run "$IU_C19" --apply --remove-withheld-review-tier)"
assert_eq "installer-upgrade #959: the opt-in really does flip a true review key to false" "False" \
  "$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["workflows"]["prflow-review"])' "$IU_C19/.prflow/config.json")"
assert_eq "installer-upgrade #959: the config key is turned off BEFORE the workflow files are deleted (the only self-healing order)" "config-first" \
  "$(printf '%s\n' "$IU_O19" | python3 -c '
import sys
# Either config-half emission counts — the rc-0 flip or the rc-4 already-false report.
# The arm under test is the ORDER of the two halves, not which branch the config edit took.
CONFIG = ("prflow-review\"]=false", "prflow-review\"] is already false")
key = files = None
for i, line in enumerate(sys.stdin):
    if key is None and any(c in line for c in CONFIG):
        key = i
    if files is None and "removed withheld review-tier workflow" in line:
        files = i
if key is None or files is None:
    print("MISSING key=%s files=%s" % (key, files))
else:
    print("config-first" if key < files else "files-first")
')"
# The recovery property the order buys: with the key already false and the files still
# present (the interrupted state the safe order produces), a re-run completes the removal.
IU_C19B="$(_iu_consumer withheld-order-resume)"
_iu_run "$IU_C19B" >/dev/null
for _iu_w in devflow-review devflow-runner telemetry-push; do
  _iu_withheld_file "$_iu_w" > "$IU_C19B/.github/workflows/$_iu_w.yml"
done
python3 -c '
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["workflows"] = dict(d.get("workflows") or {}, **{"prflow-review": False})
json.dump(d, open(p, "w"), indent=2)
' "$IU_C19B/.prflow/config.json"
_iu_run "$IU_C19B" --apply --remove-withheld-review-tier >/dev/null
assert_eq "installer-upgrade #959: an interrupted removal that already flipped the key still completes on the next run" "0" \
  "$(_iu_count_withheld "$IU_C19B")"
# ── (#959 review round 3, finding 4) Ordering alone does not make the stranded state
# impossible — the config edit can FAIL. When it does, the files must NOT be deleted:
# doing so lands in exactly the "files gone, key still true" state the ordering exists to
# prevent, and with `present` then empty no later run can retry. The invariant the comment
# asserts is now the invariant the code enforces.
IU_C19C="$(_iu_consumer withheld-order-disable-fails)"
_iu_run "$IU_C19C" >/dev/null
for _iu_w in devflow-review devflow-runner telemetry-push; do
  _iu_withheld_file "$_iu_w" > "$IU_C19C/.github/workflows/$_iu_w.yml"
done
printf '[1, 2, 3]\n' > "$IU_C19C/.prflow/config.json"   # a shape the disabler refuses to edit
IU_O19C="$(_iu_run "$IU_C19C" --apply --remove-withheld-review-tier)"
assert_eq "installer-upgrade #959: when the config key cannot be turned off, the workflow files are KEPT rather than stranding the key true" "3 yes yes" \
  "$(_iu_count_withheld "$IU_C19C") $(_iu_out_has "$IU_O19C" 'leaving the withheld review-tier workflow files in place') $(_iu_out_has "$IU_O19C" 'removing the files first would strand that key true')"
assert_eq "installer-upgrade #959: and it never reports having removed one" "no" \
  "$(_iu_out_has "$IU_O19C" 'removed withheld review-tier workflow')"
# A repo with NO config file at all has no key to strand, so removal proceeds — the gate
# is "is the key provably not left true", not "does a config exist".
IU_C19D="$(_iu_consumer withheld-order-no-config)"
_iu_run "$IU_C19D" >/dev/null
for _iu_w in devflow-review devflow-runner telemetry-push; do
  _iu_withheld_file "$_iu_w" > "$IU_C19D/.github/workflows/$_iu_w.yml"
done
rm -f "$IU_C19D/.prflow/config.json"
_iu_run "$IU_C19D" --apply --remove-withheld-review-tier >/dev/null
assert_eq "installer-upgrade #959: with no config file there is no key to strand, so the removal still proceeds" "0" \
  "$(_iu_count_withheld "$IU_C19D")"
# ── (#959 review round 3, finding 5) grep's rc is three-valued, and rc 2 (could not read
# the file) is not rc 1 (read it, no match). Folding them together reports a content
# judgement the code never made.
#
# Driven at the FUNCTION level, because the whole-installer path cannot reach this arm:
# devflow_withheld_tier_present gates on `[ -f ]`, so anything unreadable-by-being-absent
# never enters `present`. Handing the function a `present` entry whose file is gone models
# the real case — the file vanished between the presence scan and the removal — and makes
# grep return a genuine rc 2 deterministically, without a chmod that dissolves under root.
IU_C19E="$(_iu_consumer withheld-unreadable)"
_iu_run "$IU_C19E" >/dev/null
_iu_withheld_file devflow-review > "$IU_C19E/.github/workflows/devflow-review.yml"
# shellcheck disable=SC1090  # sources install.sh at runtime under DEVFLOW_SELFTEST
IU_O19E="$( cd "$IU_C19E" && DEVFLOW_SELFTEST=1 . "$IU_INSTALL" \
    && REMOVE_WITHHELD=1 devflow_remove_withheld_tier 'devflow-review telemetry-push' 2>&1 )"
assert_eq "installer-upgrade #959: an UNREADABLE withheld-tier path is reported as a read failure, explicitly not as a judgement that it is not DevFlow's" "yes yes" \
  "$(_iu_out_has "$IU_O19E" 'could not read .github/workflows/telemetry-push.yml to check its signature') $(_iu_out_has "$IU_O19E" 'This is a read failure, NOT a judgement')"
assert_eq "installer-upgrade #959: the unreadable path is not folded into the no-signature message, while a genuinely matching sibling IS still removed" "no no" \
  "$(_iu_out_has "$IU_O19E" 'telemetry-push.yml carries no DevFlow signature') $([ -f "$IU_C19E/.github/workflows/devflow-review.yml" ] && echo yes || echo no)"
# Control: the rc-1 arm still reports the content judgement, so the two are genuinely
# distinguished rather than the rc-2 wording having simply replaced both.
printf 'name: someone elses telemetry push\non: push\n' > "$IU_C19E/.github/workflows/telemetry-push.yml"
# shellcheck disable=SC1090  # sources install.sh at runtime under DEVFLOW_SELFTEST
IU_O19F="$( cd "$IU_C19E" && DEVFLOW_SELFTEST=1 . "$IU_INSTALL" \
    && REMOVE_WITHHELD=1 devflow_remove_withheld_tier 'telemetry-push' 2>&1 )"
assert_eq "installer-upgrade #959 CONTROL: a readable non-matching file still reports the no-signature judgement, not the read failure" "yes no yes" \
  "$(_iu_out_has "$IU_O19F" 'telemetry-push.yml carries no DevFlow signature') $(_iu_out_has "$IU_O19F" 'This is a read failure') $([ -f "$IU_C19E/.github/workflows/telemetry-push.yml" ] && echo yes || echo no)"

# ── Scenario 19g (#1041): the review toggle is disabled under WHICHEVER SPELLING the
# config carries, and the END STATE is asserted — not just the log line.
#
# The defect this locks out is a run reporting an outcome it did not achieve.
# devflow_disable_review_key runs BEFORE scaffold-config.sh's key migration in
# devflow_apply_all, so on a consumer that has not migrated yet, writing the CURRENT
# spelling unconditionally leaves both keys present. The migration then resolves that
# both-present case through its example-valued graft arm — the new key holds the shipped
# example default `false`, so it is judged a deep-merge graft, dropped, and the superseded
# value written through in its place. A `devflow-review: true` lands back as
# `prflow-review: true` in the very run that logged the tier disabled, and
# devflow_report_withheld_tier then tells the operator exposure persists for as long as
# that key is true. Asserting the LOG alone cannot see this: the log said false.
#
# Driven end to end through the real installer, over both orderings the rename creates.
_iu_review_toggle() {  # $1 = consumer root -> the surviving review toggle, both spellings
  python3 -c '
import json, sys
wf = json.load(open(sys.argv[1])).get("workflows") or {}
print("prflow-review=%s devflow-review=%s"
      % (json.dumps(wf.get("prflow-review")), json.dumps(wf.get("devflow-review"))))
' "$1/.prflow/config.json"
}
# (a) A config still on the SUPERSEDED spelling, with the toggle genuinely on.
IU_C19G="$(_iu_consumer withheld-superseded-spelling)"
_iu_run "$IU_C19G" >/dev/null
for _iu_w in devflow-review devflow-runner telemetry-push; do
  _iu_withheld_file "$_iu_w" > "$IU_C19G/.github/workflows/$_iu_w.yml"
done
python3 -c '
import json, sys
p = sys.argv[1]
d = json.load(open(p))
# An un-migrated consumer: the whole workflows block is on the superseded spelling, and
# the review tier is ON. Both sub-keys move together in a real config, so both are set.
d["workflows"] = {"devflow": True, "devflow-review": True}
json.dump(d, open(p, "w"), indent=2)
' "$IU_C19G/.prflow/config.json"
IU_O19G="$(_iu_run "$IU_C19G" --apply --remove-withheld-review-tier)"
assert_eq "installer-upgrade #1041: an un-migrated config ends with the review toggle actually OFF — the run's report matches the config it left behind" "prflow-review=false devflow-review=null" \
  "$(_iu_review_toggle "$IU_C19G")"
assert_eq "installer-upgrade #1041: and the log names the SUPERSEDED spelling it really wrote, never a key this run never touched" "yes no" \
  "$(_iu_out_has "$IU_O19G" 'set workflows["devflow-review"]=false') $(_iu_out_has "$IU_O19G" 'set workflows["prflow-review"]=false')"
assert_eq "installer-upgrade #1041: the three withheld workflow files are still removed on that path" "0" \
  "$(_iu_count_withheld "$IU_C19G")"
# (b) A config already on the CURRENT spelling takes the same path under its own name —
# so (a) is a spelling-follows-config rule, not a blanket switch to the superseded name.
IU_C19H="$(_iu_consumer withheld-current-spelling)"
_iu_run "$IU_C19H" >/dev/null
for _iu_w in devflow-review devflow-runner telemetry-push; do
  _iu_withheld_file "$_iu_w" > "$IU_C19H/.github/workflows/$_iu_w.yml"
done
python3 -c '
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["workflows"] = {"prflow": True, "prflow-review": True}
json.dump(d, open(p, "w"), indent=2)
' "$IU_C19H/.prflow/config.json"
IU_O19H="$(_iu_run "$IU_C19H" --apply --remove-withheld-review-tier)"
assert_eq "installer-upgrade #1041: a migrated config also ends with the toggle actually OFF" "prflow-review=false devflow-review=null" \
  "$(_iu_review_toggle "$IU_C19H")"
assert_eq "installer-upgrade #1041: and names the CURRENT spelling there" "yes no" \
  "$(_iu_out_has "$IU_O19H" 'set workflows["prflow-review"]=false') $(_iu_out_has "$IU_O19H" 'set workflows["devflow-review"]=false')"
# (c) BOTH spellings present — the self-heal state a consumer who already ran the broken
# build is sitting in. Disabling only one leaves the other to win the graft arm, so both
# are turned off and the surviving key is false whichever one the migration keeps.
IU_C19I="$(_iu_consumer withheld-both-spellings)"
_iu_run "$IU_C19I" >/dev/null
for _iu_w in devflow-review devflow-runner telemetry-push; do
  _iu_withheld_file "$_iu_w" > "$IU_C19I/.github/workflows/$_iu_w.yml"
done
python3 -c '
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["workflows"] = {"devflow": True, "devflow-review": True, "prflow-review": False}
json.dump(d, open(p, "w"), indent=2)
' "$IU_C19I/.prflow/config.json"
IU_O19I="$(_iu_run "$IU_C19I" --apply --remove-withheld-review-tier)"
assert_eq "installer-upgrade #1041: a config carrying BOTH spellings ends with the surviving toggle off, not the superseded true value grafted back over it" "prflow-review=false devflow-review=null" \
  "$(_iu_review_toggle "$IU_C19I")"
assert_eq "installer-upgrade #1041: and the log names both keys it wrote" "yes" \
  "$(_iu_out_has "$IU_O19I" 'set workflows["prflow-review"] and workflows["devflow-review"]=false')"

# ── Scenario 19j (#1041): the PARTIAL-UPGRADE skew that silently disables the tier.
#
# The workflow copy loop is PER FILE, and install_managed deliberately PRESERVES a
# hand-edited workflow (writing a .prflow-new sidecar beside it) — an explicitly designed-
# for case, not an edge case. So one shipped workflow can be refreshed onto the renamed
# enable key while the other stays hand-edited on the superseded one. scaffold-config.sh's
# freshness gate then refuses the config migration — correctly, since a stale reader is
# present — and the REFRESHED file is left reading workflows.prflow against a config that
# still carries workflows.devflow. Its enable read resolves absent -> false and every
# trigger silently does nothing.
#
# Before Tier 4 this was impossible: the enable key was frozen, so a refreshed workflow and
# the config key could never skew. The freeze was doing load-bearing work.
#
# Driven end to end through the real installer over a fixture consumer, asserting the
# resulting TREE — which workflow reads which key, and that the loud signal fired.
IU_C19J="$(_iu_consumer enable-key-skew)"
_iu_run "$IU_C19J" >/dev/null
python3 -c '
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
# The consumer hand-edits devflow.yml back onto the superseded enable key. That both
# models a pre-rename installation carrying a local edit AND breaks the manifest digest,
# so the next run PRESERVES this file. devflow-implement.yml is left byte-identical to
# what the installer wrote, so its digest still matches and it IS refreshed — the exact
# asymmetry the per-file loop produces.
p = root / ".github/workflows/devflow.yml"
body = p.read_text(encoding="utf-8")
if ".workflows.prflow" not in body:
    sys.exit("fixture precondition failed: devflow.yml does not read the renamed key")
p.write_text(body.replace(".workflows.prflow", ".workflows.devflow")
             + "\n# consumer hand-edit\n", encoding="utf-8")
cfg = root / ".prflow/config.json"
d = json.loads(cfg.read_text(encoding="utf-8"))
d["workflows"] = {"devflow": True, "devflow-review": False}
cfg.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
' "$IU_C19J"
IU_O19J="$(_iu_run "$IU_C19J" --apply)"
_iu_enable_read() {  # $1 = consumer root, $2 = workflow id -> the enable key it reads
  python3 -c '
import re, sys
body = open(sys.argv[1], encoding="utf-8").read()
found = re.search(r"ENABLED=\$\(echo \"\$CONFIG_JSON\" \| jq -r .\.workflows\.([a-z-]+)", body)
print(found.group(1) if found else "UNREADABLE")
' "$1/.github/workflows/$2.yml"
}
assert_eq "installer-upgrade #1041: the per-file refresh really does produce the skew — hand-edited workflow preserved on the superseded key, untouched one refreshed onto the renamed key" "devflow prflow" \
  "$(_iu_enable_read "$IU_C19J" devflow) $(_iu_enable_read "$IU_C19J" devflow-implement)"
assert_eq "installer-upgrade #1041: and the freshness gate correctly refuses the config migration, leaving the config on the superseded key" "true null" \
  "$(python3 -c '
import json, sys
wf = json.load(open(sys.argv[1])).get("workflows") or {}
print("%s %s" % (json.dumps(wf.get("devflow")), json.dumps(wf.get("prflow"))))
' "$IU_C19J/.prflow/config.json")"
# THE ASSERTION THIS SCENARIO EXISTS FOR: the skew is announced, by name, at the moment it
# is created. Without it the run is silent and the consumer learns only when a trigger
# does nothing.
assert_eq "installer-upgrade #1041: the run warns LOUDLY about the partial upgrade and names the refreshed workflow" "yes yes" \
  "$(_iu_out_has "$IU_O19J" 'PARTIAL UPGRADE') $(_iu_out_has "$IU_O19J" 'workflows.prflow, but .prflow/config.json still carries only the superseded workflows.devflow: devflow-implement.yml')"
assert_eq "installer-upgrade #1041: the warning states the consequence and a remedy, and never claims to have repaired anything" "yes yes no" \
  "$(_iu_out_has "$IU_O19J" 'silently do nothing') $(_iu_out_has "$IU_O19J" 're-run install.sh --apply so the workflow reads and the config key move together') $(_iu_out_has "$IU_O19J" 'migrated superseded config key in')"
# The install-time warning is a convenience; the SHIPPED workflow's own trigger-time guard
# is the authoritative signal. Join the two: feed the config this run actually produced
# into the guard program read out of the refreshed workflow, and confirm it selects the
# error arm. This is what proves the two halves agree about the same tree.
assert_eq "installer-upgrade #1041: the refreshed workflow's own trigger-time guard selects the ERROR arm over the config this run left behind" "true" \
  "$(python3 -c '
import re, sys
for line in open(sys.argv[1], encoding="utf-8"):
    if "SUPERSEDED_ENABLE=" in line and "jq -r " in line:
        found = re.search(r"jq -r .(.*).\)\s*$", line.strip())
        if found:
            sys.stdout.write(found.group(1))
        break
' "$IU_C19J/.github/workflows/devflow-implement.yml" | {
      read -r _iu_prog
      jq -r "$_iu_prog" < "$IU_C19J/.prflow/config.json" 2>/dev/null
    })"
# NEGATIVE CONTROL: an ordinary upgrade with no hand-edited workflow migrates cleanly and
# must draw no warning — otherwise the arm above would fire on every consumer and mean
# nothing.
IU_C19K="$(_iu_consumer enable-key-no-skew)"
_iu_run "$IU_C19K" >/dev/null
python3 -c '
import json, pathlib, sys
cfg = pathlib.Path(sys.argv[1]) / ".prflow/config.json"
d = json.loads(cfg.read_text(encoding="utf-8"))
d["workflows"] = {"devflow": True, "devflow-review": False}
cfg.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")
' "$IU_C19K"
IU_O19K="$(_iu_run "$IU_C19K" --apply)"
assert_eq "installer-upgrade #1041 NEGATIVE CONTROL: with both workflows refreshed the config migrates and NO skew warning is emitted" "no true" \
  "$(_iu_out_has "$IU_O19K" 'PARTIAL UPGRADE') $(python3 -c '
import json, sys
print(json.dumps((json.load(open(sys.argv[1])).get("workflows") or {}).get("prflow")))
' "$IU_C19K/.prflow/config.json")"

# ── Scenario 20 (#959 review, suggestion 3): fail-safe/warning arms that are consumer-
# facing documented behavior but had no coverage. None of these is in the clobber-
# prevention core; they are the branches a consumer actually SEES when something is wrong.
# (a) the dry-run diff renderer with no working python3 — the documented "the plan lines
#     above are the whole preview" degradation.
IU_C20="$(_iu_consumer render-nopython3)"
_iu_run "$IU_C20" >/dev/null
IU_O20="$(IU_PATH_PREFIX="$IU_NOPY" _iu_run "$IU_C20" --dry-run)"
assert_eq "installer-upgrade #959: a dry run with no working python3 says the diff cannot be rendered and names the plan lines as the whole preview" "yes yes" \
  "$(_iu_out_has "$IU_O20" 'cannot render the dry-run diff. The plan lines above are the whole preview') $(_iu_out_has "$IU_O20" 'nothing in this repository was written')"
# (b) a DRY RUN of the destructive opt-in previews the removal and deletes nothing.
IU_C20B="$(_iu_consumer withheld-dryrun)"
_iu_run "$IU_C20B" >/dev/null
for _iu_w in devflow-review devflow-runner telemetry-push; do
  _iu_withheld_file "$_iu_w" > "$IU_C20B/.github/workflows/$_iu_w.yml"
done
IU_SNAP20B="$(_iu_snapshot "$IU_C20B")"
IU_O20B="$(_iu_run "$IU_C20B" --dry-run --remove-withheld-review-tier)"
assert_eq "installer-upgrade #959: a dry run of --remove-withheld-review-tier previews all three deletions and removes none of them" "yes 3 yes" \
  "$(_iu_out_has "$IU_O20B" 'removed withheld review-tier workflow devflow-review.yml') $(_iu_count_withheld "$IU_C20B") $([ "$IU_SNAP20B" = "$(_iu_snapshot "$IU_C20B")" ] && echo yes || echo no)"
# (c) devflow_write_manifest's python3-PRESENT write-failure arm. Induced by making the
#     manifest path a DIRECTORY, so os.replace fails — deterministic and root-immune,
#     unlike a chmod. The install must still complete and warn about the consequence.
IU_C20C="$(_iu_consumer manifest-write-fail)"
_iu_run "$IU_C20C" >/dev/null
rm -f "$IU_C20C/.prflow/install-manifest.json"
mkdir -p "$IU_C20C/.prflow/install-manifest.json"
IU_O20C="$(_iu_run "$IU_C20C" --apply)" && IU_RC20C=0 || IU_RC20C=$?
assert_eq "installer-upgrade #959: an unwritable manifest warns that the next upgrade will preserve everything, and never aborts the install" "0 yes yes" \
  "$IU_RC20C $(_iu_out_has "$IU_O20C" 'could not write .prflow/install-manifest.json; the next upgrade will preserve every existing artifact rather than update it') $(_iu_out_has "$IU_O20C" 'done (from')"

# ── Scenario 21 (#959 review round 3, advisory): the DEVFLOW_VENDOR=1 path, including
# its ONE documented preview exclusion. The review flagged this path as entirely
# untested and noted that a regression dropping the `.prflow/vendor` SKIP tuple from
# the diff renderer would pass the suite green — the exclusion is asserted nowhere, and
# it is the single carve-out in the "diff of the bytes it would change" promise.
#
# Reachable after all: devflow_copy_slice needs a source tree carrying .claude-plugin/
# plugin.json, agents/, docs/, lib/, scripts/, skills/ and LICENSES/, which are cheap to
# stub. The offline fixture source is extended into a second tree rather than the shared
# one, so the other twenty scenarios keep exercising the minimal shape they were
# written against.
IU_VSRC="$_iw_tmp_root/src-vendor"
rm -rf "$IU_VSRC"
cp -R "$IU_SRC" "$IU_VSRC"
mkdir -p "$IU_VSRC/.claude-plugin" "$IU_VSRC/agents" "$IU_VSRC/docs" "$IU_VSRC/skills" "$IU_VSRC/LICENSES"
cp "$LIB/../.claude-plugin/plugin.json" "$IU_VSRC/.claude-plugin/"
printf 'fixture agent\n'   > "$IU_VSRC/agents/fixture-agent.md"
printf 'fixture doc\n'     > "$IU_VSRC/docs/fixture-doc.md"
printf 'fixture skill\n'   > "$IU_VSRC/skills/fixture-skill.md"
printf 'fixture license\n' > "$IU_VSRC/LICENSES/FIXTURE-LICENSE"
assert_eq "installer-upgrade #959: the vendor fixture source carries every member devflow_copy_slice requires" "yes" \
  "$([ -f "$IU_VSRC/.claude-plugin/plugin.json" ] && [ -d "$IU_VSRC/agents" ] && [ -d "$IU_VSRC/docs" ] \
     && [ -d "$IU_VSRC/skills" ] && [ -d "$IU_VSRC/LICENSES" ] && echo yes || echo no)"

IU_C21="$(_iu_consumer vendor)"
IU_O21="$(IU_SRC_OVERRIDE="$IU_VSRC" IU_VENDOR=1 _iu_run "$IU_C21")"
assert_eq "installer-upgrade #959: a DEVFLOW_VENDOR=1 install commits the plugin tree at .prflow/vendor/prflow and says so" "yes yes yes" \
  "$(_iu_out_has "$IU_O21" 'vendoring plugin → .prflow/vendor/prflow/ (DEVFLOW_VENDOR=1)') $([ -d "$IU_C21/.prflow/vendor/prflow/scripts" ] && echo yes || echo no) $([ -f "$IU_C21/.prflow/vendor/prflow/.claude-plugin/plugin.json" ] && echo yes || echo no)"
# The committed tree must NOT be gitignored — that is the whole point of DEVFLOW_VENDOR=1,
# and the thin install's `/vendor/` line would silently keep it out of the consumer's commit.
assert_eq "installer-upgrade #959: a vendored install leaves /vendor/ OUT of .prflow/.gitignore (a thin install puts it in)" "no yes" \
  "$(_iu_has_line "$IU_C21/.prflow/.gitignore" '/vendor/') $(_iu_has_line "$IU_C21/.prflow/.gitignore" '/tmp/')"

# THE EXCLUSION. Upgrade the vendored consumer under a dry run: the apply log reports the
# vendoring as one line, and the DIFF BODY must not enumerate the vendored tree's files.
# Asserted two ways — no vendored path appears, AND a control path outside the exclusion
# still does — so a renderer that simply produced no diff at all cannot satisfy it.
printf '\n# newer release\n' >> "$IU_VSRC/.github/workflows/devflow.yml"
IU_SNAP21="$(_iu_snapshot "$IU_C21")"
IU_O21B="$(IU_SRC_OVERRIDE="$IU_VSRC" IU_VENDOR=1 _iu_run "$IU_C21" --dry-run)"
assert_eq "installer-upgrade #959: the dry-run diff EXCLUDES the vendored tree body (the documented .prflow/vendor SKIP) while still diffing everything else" "no yes" \
  "$(_iu_out_matches "$IU_O21B" '^(ADD|MODIFY|DELETE) +\.prflow/vendor/') $(_iu_out_matches "$IU_O21B" '^MODIFY \.github/workflows/devflow\.yml$')"
assert_eq "installer-upgrade #959: and that vendored dry run still writes nothing" "yes" \
  "$([ "$IU_SNAP21" = "$(_iu_snapshot "$IU_C21")" ] && echo yes || echo no)"
# The thin→vendor transition removes a previously-added ignore line, so a consumer who
# switches modes does not silently keep the tree out of their commit.
IU_C21B="$(_iu_consumer vendor-transition)"
_iu_run "$IU_C21B" >/dev/null                       # thin install first: adds /vendor/
assert_eq "installer-upgrade #959: the thin install added the /vendor/ ignore line (precondition for the transition arm)" "yes" \
  "$(_iu_has_line "$IU_C21B/.prflow/.gitignore" '/vendor/')"
IU_O21C="$(IU_SRC_OVERRIDE="$IU_VSRC" IU_VENDOR=1 _iu_run "$IU_C21B" --apply)"
assert_eq "installer-upgrade #959: upgrading thin→vendored un-ignores .prflow/vendor and keeps the other ignore entries" "no yes yes" \
  "$(_iu_has_line "$IU_C21B/.prflow/.gitignore" '/vendor/') $(_iu_has_line "$IU_C21B/.prflow/.gitignore" '/tmp/') $(_iu_out_has "$IU_O21C" 'un-ignored .prflow/vendor/')"
rm -rf "$IU_VSRC"

# ── Scenario 22 (#970): the preserved-artifact sidecars must not be committable.
#
# The upgrade path's whole preservation mechanism writes DevFlow's version beside a file
# it keeps, as `<path>.prflow-new`. That sidecar is UNTRACKED and lands inside the
# consumer's own `.github/`, which `.prflow/.gitignore` — the one ignore file the
# installer used to manage — cannot reach, so the next `git add -A`, including one inside
# a /prflow:implement run, swept a 1400-line workflow into an unrelated PR. Observed on a
# real consumer's first upgrade.
#
# The defect is about GIT's view of the tree, so these arms are driven over fixture
# consumers with a REAL repository rather than the `.git`-shaped directory the other
# scenarios use, and the load-bearing assertion runs the actual `git add -A` and reads
# the resulting index. A grep for the pattern in `.gitignore` would prove only that a
# line was written, not that git honours it against a DIRECTORY sidecar.
_iu_git_consumer() {  # $1 = fixture id -> a fresh consumer repo with a real .git
  local d="$_iw_tmp_root/consumer-$1"
  rm -rf "$d"; mkdir -p "$d"
  git -c init.defaultBranch=main -C "$d" init -q >/dev/null 2>&1
  printf '%s' "$d"
}
_iu_staged_sidecars() {  # $1 = repo -> the sidecar paths a `git add -A` would commit
  git -C "$1" add -A >/dev/null 2>&1
  git -C "$1" ls-files --cached 2>/dev/null | grep -F -- '.prflow-new' || true
}

IU_C22="$(_iu_consumer sidecar-ignore)"
IU_O22="$(_iu_run "$IU_C22")"
assert_eq "installer-upgrade #970: an install writes the preserved-artifact sidecar ignore rules into the repository-root .gitignore, and says so" "yes yes yes" \
  "$(_iu_has_line "$IU_C22/.gitignore" '*.prflow-new') $(_iu_has_line "$IU_C22/.gitignore" '*.devflow-new') $(_iu_out_has "$IU_O22" 'ignored preserved-artifact sidecars in .gitignore')"

# THE DEFECT. A file sidecar and a DIRECTORY sidecar (a preserved composite action is
# copied with `cp -R` to a whole tree), then the exact operation that committed them.
IU_C22B="$(_iu_git_consumer sidecar-git)"
_iu_run "$IU_C22B" >/dev/null
printf '\n# CONSUMER-LOCAL-EDIT-MARKER\n' >> "$IU_C22B/.github/workflows/devflow.yml"
printf '\n# COMPOSITE-ACTION-LOCAL-EDIT\n' >> "$IU_C22B/.github/actions/vendor-plugin/vendor-slice.sh"
_iu_run "$IU_C22B" --apply >/dev/null
assert_eq "installer-upgrade #970: the upgrade really did leave both sidecar shapes behind (precondition — a file and a whole directory)" "yes yes" \
  "$([ -f "$IU_C22B/.github/workflows/devflow.yml.prflow-new" ] && echo yes || echo no) $([ -d "$IU_C22B/.github/actions/vendor-plugin.prflow-new" ] && echo yes || echo no)"
assert_eq "installer-upgrade #970: a subsequent 'git add -A' stages NEITHER sidecar — not the file, and not one path inside the directory" "" \
  "$(_iu_staged_sidecars "$IU_C22B")"

# NEGATIVE CONTROL: strip the managed block and the same recipe must stage them, so the
# arm above measures the ignore rule rather than the absence of any sidecar.
IU_C22C="$(_iu_git_consumer sidecar-git-control)"
_iu_run "$IU_C22C" >/dev/null
printf '\n# CONSUMER-LOCAL-EDIT-MARKER\n' >> "$IU_C22C/.github/workflows/devflow.yml"
printf '\n# COMPOSITE-ACTION-LOCAL-EDIT\n' >> "$IU_C22C/.github/actions/vendor-plugin/vendor-slice.sh"
_iu_run "$IU_C22C" --apply >/dev/null
python3 -c '
import sys
p = sys.argv[1]
keep = [l for l in open(p, encoding="utf-8").read().splitlines(keepends=True)
        if "prflow-new" not in l and "devflow-new" not in l]
open(p, "w", encoding="utf-8").writelines(keep)
' "$IU_C22C/.gitignore"
IU_STAGED22C="$(_iu_staged_sidecars "$IU_C22C")"
assert_eq "installer-upgrade #970 NEGATIVE CONTROL: with the ignore rules removed the SAME 'git add -A' does stage both sidecars (so the arm above is not vacuous)" "yes yes" \
  "$(_iu_out_has "$IU_STAGED22C" '.github/workflows/devflow.yml.prflow-new') $(_iu_out_has "$IU_STAGED22C" '.github/actions/vendor-plugin.prflow-new/')"

# A consumer .gitignore whose last line carries no trailing newline: appending straight
# onto it would silently rewrite that pattern into `dist*.prflow-new`.
IU_C22D="$(_iu_consumer sidecar-no-newline)"
printf 'node_modules/\ndist' > "$IU_C22D/.gitignore"
_iu_run "$IU_C22D" >/dev/null
assert_eq "installer-upgrade #970: a .gitignore whose last line has no trailing newline keeps that pattern intact and still gains the rules" "yes yes yes" \
  "$(_iu_has_line "$IU_C22D/.gitignore" 'dist') $(_iu_has_line "$IU_C22D/.gitignore" 'node_modules/') $(_iu_has_line "$IU_C22D/.gitignore" '*.prflow-new')"

# Idempotent: a consumer who never resolves a sidecar re-runs the installer for years.
IU_C22E="$(_iu_consumer sidecar-idempotent)"
_iu_run "$IU_C22E" >/dev/null
IU_GI22E="$(_iu_digest "$IU_C22E/.gitignore")"
_iu_run "$IU_C22E" --apply >/dev/null
assert_eq "installer-upgrade #970: re-applying leaves .gitignore byte-identical, with exactly one copy of each rule" "yes 1 1" \
  "$([ "$IU_GI22E" = "$(_iu_digest "$IU_C22E/.gitignore")" ] && echo yes || echo no) $(grep -cxF '*.prflow-new' "$IU_C22E/.gitignore") $(grep -cxF '*.devflow-new' "$IU_C22E/.gitignore")"

# A consumer who already ignores the current suffix keeps their own line — only the
# missing rule is appended, and their pattern is not duplicated.
IU_C22F="$(_iu_consumer sidecar-consumer-rule)"
printf '*.prflow-new\n' > "$IU_C22F/.gitignore"
_iu_run "$IU_C22F" >/dev/null
assert_eq "installer-upgrade #970: a rule the consumer already carries is not duplicated, and only the missing one is appended" "1 1" \
  "$(grep -cxF '*.prflow-new' "$IU_C22F/.gitignore") $(grep -cxF '*.devflow-new' "$IU_C22F/.gitignore")"
# The same claim, in the ONE shape whose detection depends on devflow_gitignore_carries'
# final-line arm (`|| [ -n "$line" ]`): the rule is the LAST line AND carries no trailing
# newline. `read` returns non-zero on such a line while still assigning it, so without that
# arm the loop body never sees it, the rule reads as absent, and the block is appended a
# second time. The fixture above cannot show this — its rule is newline-terminated — and
# the no-trailing-newline fixture above cannot either, because its unterminated last line
# is not a sidecar pattern. Both are needed; only this one is discriminating.
IU_C22M="$(_iu_consumer sidecar-unterminated-rule)"
printf 'node_modules/\n*.prflow-new' > "$IU_C22M/.gitignore"
_iu_run "$IU_C22M" >/dev/null
assert_eq "installer-upgrade #970: a rule the consumer carries as an UNTERMINATED last line is still seen, so it is never appended a second time" "1 1 yes" \
  "$(grep -cxF '*.prflow-new' "$IU_C22M/.gitignore") $(grep -cxF '*.devflow-new' "$IU_C22M/.gitignore") $(_iu_has_line "$IU_C22M/.gitignore" 'node_modules/')"

# A .gitignore that is not a regular file is the consumer's business: report the rule
# they need and carry on, never abort and never write into whatever it is.
IU_C22G="$(_iu_consumer sidecar-gitignore-dir)"
mkdir -p "$IU_C22G/.gitignore"
IU_O22G="$(_iu_run "$IU_C22G")" && IU_RC22G=0 || IU_RC22G=$?
assert_eq "installer-upgrade #970: a .gitignore that is a DIRECTORY warns naming the rule, leaves it a directory, and never aborts the install" "0 yes yes yes" \
  "$IU_RC22G $(_iu_out_has "$IU_O22G" 'is a symlink or is not a regular file') $([ -d "$IU_C22G/.gitignore" ] && echo yes || echo no) $(_iu_out_has "$IU_O22G" 'done (from')"
# The shape a plain `[ -f ]` refusal MISSES. A dangling symlink is neither `-e` nor `-f`,
# so an unguarded append would CREATE the link's target — a file the consumer never asked
# for, at a path that need not be inside the repository. The link target is planted
# outside the consumer tree precisely so a regression is visible as a stray file there.
IU_C22I="$(_iu_consumer sidecar-gitignore-dangling)"
IU_T22I="$_iw_tmp_root/sidecar-dangling-target"
rm -f "$IU_T22I"
ln -s "$IU_T22I" "$IU_C22I/.gitignore"
IU_O22I="$(_iu_run "$IU_C22I")" && IU_RC22I=0 || IU_RC22I=$?
assert_eq "installer-upgrade #970: a .gitignore that is a DANGLING SYMLINK is refused too, and the link's target is never created" "0 yes no yes" \
  "$IU_RC22I $(_iu_out_has "$IU_O22I" 'is a symlink or is not a regular file') $([ -e "$IU_T22I" ] && echo yes || echo no) $(_iu_out_has "$IU_O22I" 'done (from')"
# ── The LIVE symlink: the shape an `-e`/`-f` pair structurally CANNOT see, because both
# of those tests follow the link. For a link to a regular file `-e` is true AND `-f` is
# true, so a guard built from them alone lets the commonest link shape through and the
# append writes to the link's TARGET — which an absolute link puts outside the repository
# entirely. Only `[ -L ]` answers this, and it now runs first and unconditionally.
# Planted with an ABSOLUTE target holding known bytes, so "did not write outside the tree"
# is asserted as a byte comparison on that outside file rather than inferred from a log.
IU_C22K="$(_iu_consumer sidecar-gitignore-live-symlink)"
IU_T22K="$_iw_tmp_root/sidecar-live-target"
printf 'A CONSUMER FILE THAT LIVES OUTSIDE THE REPOSITORY\n' > "$IU_T22K"
IU_D22K="$(_iu_digest "$IU_T22K")"
ln -s "$IU_T22K" "$IU_C22K/.gitignore"
IU_O22K="$(_iu_run "$IU_C22K")" && IU_RC22K=0 || IU_RC22K=$?
assert_eq "installer-upgrade #970: a LIVE symlink .gitignore is refused, and the file it points at OUTSIDE the repository is byte-identical afterwards" "0 yes yes yes" \
  "$IU_RC22K $(_iu_out_has "$IU_O22K" 'is a symlink or is not a regular file') $([ "$IU_D22K" = "$(_iu_digest "$IU_T22K")" ] && echo yes || echo no) $(_iu_out_has "$IU_O22K" 'done (from')"
# The PREVIEW half of that same shape, which is why it is worse than a local mishap: the
# sandbox copy is made with `cp -P`, so an absolute-target link resolves to the SAME real
# file, a sandbox write would mutate it, and the renderer would show NO diff at all because
# both sides read one file — a silent breach of "the preview writes only into the throwaway
# copy". Assert the outside file survives a dry run untouched, and that the run reports the
# refusal rather than any phantom .gitignore change.
IU_O22L="$(_iu_run "$IU_C22K" --dry-run)"
assert_eq "installer-upgrade #970: a dry run over that same live symlink also leaves the outside file byte-identical, and renders no phantom .gitignore change" "yes yes no" \
  "$([ "$IU_D22K" = "$(_iu_digest "$IU_T22K")" ] && echo yes || echo no) $(_iu_out_has "$IU_O22L" 'is a symlink or is not a regular file') $(_iu_out_matches "$IU_O22L" '^(ADD|MODIFY|DELETE) +\.gitignore')"
# Preview/apply agreement for the refused shapes: the sandbox mirrors the SHAPE, so the
# dry run does not advertise an `ADD .gitignore` the apply would decline. Overstating is
# the mirror image of the understated preview #971 fixes.
IU_C22J="$(_iu_consumer sidecar-preview-nonregular)"
mkdir -p "$IU_C22J/.gitignore"
IU_O22J="$(_iu_run "$IU_C22J" --dry-run)"
assert_eq "installer-upgrade #970: the dry run over a non-regular .gitignore reports the same refusal and advertises no ADD it could not perform" "yes no" \
  "$(_iu_out_has "$IU_O22J" 'is a symlink or is not a regular file') $(_iu_out_matches "$IU_O22J" '^ADD +\.gitignore ')"

# The append is a write, so the dry run has to SHOW it and still perform none of it.
IU_C22H="$(_iu_consumer sidecar-preview)"
printf 'node_modules/\n' > "$IU_C22H/.gitignore"
IU_SNAP22H="$(_iu_snapshot "$IU_C22H")"
IU_O22H="$(_iu_run "$IU_C22H" --dry-run)"
assert_eq "installer-upgrade #970: the dry run renders the .gitignore append as a diff and still writes nothing" "yes yes yes" \
  "$(_iu_out_matches "$IU_O22H" '^MODIFY \.gitignore$') $(_iu_out_has "$IU_O22H" '+*.prflow-new') $([ "$IU_SNAP22H" = "$(_iu_snapshot "$IU_C22H")" ] && echo yes || echo no)"

# ── The append-FAILURE branch. Every fixture above has a writable .gitignore, so only the
# success `log` ever ran: the branch selection, the captured-cause interpolation and the
# by-hand breadcrumb all shipped untested, and an inverted branch or a broken capture would
# have stayed green.
#
# Induced by calling the function with a working directory that no longer exists, so the
# relative `>>` fails with ENOENT. Deterministic and ROOT-IMMUNE — the same requirement the
# manifest-write-failure arm above satisfies by making its target a directory, and a chmod
# would not (root writes through it, turning this arm red on a root host rather than
# proving anything). A directory is not available as the inducer here, because the guard
# now refuses one before the append is ever reached; hence the function-level drive.
IU_C22N="$_iw_tmp_root/sidecar-append-fail"
rm -rf "$IU_C22N"; mkdir -p "$IU_C22N/gone"
# shellcheck disable=SC1090  # sources install.sh at runtime under DEVFLOW_SELFTEST
IU_O22N="$( cd "$IU_C22N/gone" && rmdir "$IU_C22N/gone" \
  && DEVFLOW_SELFTEST=1 . "$IU_INSTALL" && manage_sidecar_gitignore 2>&1 )" && IU_RC22N=0 || IU_RC22N=$?
assert_eq "installer-upgrade #970: an append that FAILS takes the warning branch instead of reporting success, and still returns 0 (best-effort, never aborts the install)" "0 yes no" \
  "$IU_RC22N $(_iu_out_has "$IU_O22N" 'could not append the preserved-artifact sidecar ignore rules') $(_iu_out_has "$IU_O22N" 'ignored preserved-artifact sidecars in')"
assert_eq "installer-upgrade #970: and that warning carries the captured CAUSE plus the by-hand remedy, rather than a bare could-not-append" "yes yes" \
  "$(_iu_out_matches "$IU_O22N" 'could not append the preserved-artifact sidecar ignore rules to \.gitignore \(.+\)') $(_iu_out_has "$IU_O22N" "Add '*.prflow-new' and '*.devflow-new' to your ignore rules by hand")"

# ── Scenario 23 (#971): the preview must not UNDERSTATE what --apply writes.
#
# The dry run copies the installer's own subtrees into its sandbox and then runs the real
# apply against that. Language auto-detection scanned that sandbox, so it saw no
# package.json / composer.json / docker-compose* and
# reported "no known language markers detected", while the same step under --apply saw
# the real tree and merged that project's toolchain into config.json. Observed on a real
# consumer, where both outcomes happened to be no-ops only because its config already
# covered its languages.
#
# The fix hands detection a separate READ-ONLY scan root, so these arms assert the two
# runs agree AND that the preview still wrote nothing — a preview that mutated the real
# tree would be a worse defect than the one being fixed.
_iu_plant_markers() {  # $1 = repo root -> the three markers the real consumer carried
  printf '{ "name": "fixture" }\n' > "$1/package.json"
  printf '{ "name": "vendor/fixture" }\n' > "$1/composer.json"
  printf 'services: {}\n' > "$1/docker-compose.yml"
}
_iu_detect_line() {  # $1 = captured installer output -> its language-detection verdict
  printf '%s\n' "$1" | grep -E 'devflow-detect: (detected: [a-z ]+ —|no known language markers)' | head -1
}

IU_C23A="$(_iu_consumer detect-preview)"; IU_C23B="$(_iu_consumer detect-apply)"
for _iu_c23 in "$IU_C23A" "$IU_C23B"; do
  _iu_run "$_iu_c23" >/dev/null          # install first, while the tree has no markers
  _iu_plant_markers "$_iu_c23"           # then the project gains its languages
done
IU_SNAP23="$(_iu_snapshot "$IU_C23A")"
IU_O23A="$(_iu_run "$IU_C23A" --dry-run)"
IU_O23B="$(_iu_run "$IU_C23B" --apply)"
assert_eq "installer-upgrade #971: the dry run reports the SAME language detection the apply performs, rather than an understated no-op" \
  "$(_iu_detect_line "$IU_O23B")" "$(_iu_detect_line "$IU_O23A")"
assert_eq "installer-upgrade #971: and that shared verdict actually names the detected languages, so the arm above cannot be satisfied by two empty reports" "yes no" \
  "$(_iu_out_matches "$IU_O23A" 'devflow-detect: detected: docker node php —') $(_iu_out_has "$IU_O23A" 'no known language markers detected')"
assert_eq "installer-upgrade #971: the config.json the detection would rewrite appears in the dry-run diff, with the merged tool entries in its body" "yes yes" \
  "$(_iu_out_matches "$IU_O23A" '^MODIFY \.prflow/config\.json$') $(_iu_out_matches "$IU_O23A" '^\+.*Bash\(npm:\*\)')"
assert_eq "installer-upgrade #971: the dry run that scanned the real tree still wrote nothing to it" "yes" \
  "$([ "$IU_SNAP23" = "$(_iu_snapshot "$IU_C23A")" ] && echo yes || echo no)"

# NEGATIVE CONTROL: an installer copy whose preview call drops the scan-root argument
# reproduces the understated report, so the arms above measure that plumbing.
IU_MUT23="$(probe_tmp 'installer-upgrade #971 scan-root control setup')"
python3 -c '
import sys
src, dst = sys.argv[1], sys.argv[2]
body = open(src, encoding="utf-8").read()
call = "devflow_apply_all \"$PREVIEW\" \"$PIN\" \"$REF\" \"$PWD\""
if call not in body:
    sys.exit("mutation target not found: the preview scan-root argument")
open(dst, "w", encoding="utf-8").write(
    body.replace(call, "devflow_apply_all \"$PREVIEW\" \"$PIN\" \"$REF\"", 1))
' "$IU_INSTALL" "$IU_MUT23" || printf 'devflow-test: #971 scan-root control mutation FAILED to apply\n'
assert_eq "installer-upgrade #971 NEGATIVE CONTROL: the control copy really does drop the preview's scan-root argument" "no" \
  "$(_iu_has "$IU_MUT23" 'devflow_apply_all "$PREVIEW" "$PIN" "$REF" "$PWD"')"
IU_O23E="$(IU_INSTALL_BIN="$IU_MUT23" _iu_run "$IU_C23A" --dry-run)"
assert_eq "installer-upgrade #971 NEGATIVE CONTROL: without the scan root the preview reports no language markers at all (the understated preview the fix removes)" "yes no" \
  "$(_iu_out_has "$IU_O23E" 'no known language markers detected') $(_iu_out_matches "$IU_O23E" 'devflow-detect: detected: docker node php —')"
rm -f "$IU_MUT23"

# The scan root is READ-ONLY, asserted at the detector's own executable surface: pointing
# it at another tree moves the search and nothing else — every write still lands in the
# target repo's config.
IU_C23F="$(_iu_consumer detect-target)"
_iu_run "$IU_C23F" >/dev/null
IU_S23F="$_iw_tmp_root/detect-scan-only"
rm -rf "$IU_S23F"; mkdir -p "$IU_S23F"
printf '{ "name": "fixture" }\n' > "$IU_S23F/package.json"
IU_SNAP23F="$(_iu_snapshot "$IU_S23F")"
IU_O23F="$(bash "$LIB/../scripts/detect-project-tools.sh" "$IU_C23F" "$IU_S23F" 2>&1)"
assert_eq "installer-upgrade #971: detect-project-tools.sh with a separate scan root merges the SCANNED tree's toolchain into the TARGET repo's config" "yes yes" \
  "$(_iu_out_matches "$IU_O23F" 'devflow-detect: detected: node —') $(_iu_has "$IU_C23F/.prflow/config.json" 'Bash(npm:*)')"
assert_eq "installer-upgrade #971: and it writes nothing whatsoever into the scanned tree (no config, no state directory, no byte)" "yes" \
  "$([ "$IU_SNAP23F" = "$(_iu_snapshot "$IU_S23F")" ] && echo yes || echo no)"

# Back-compat: the single-argument form still scans the tree it writes to, so the
# /prflow:init path and a direct --apply are byte-for-byte what they were.
IU_C23G="$(_iu_consumer detect-single-arg)"
_iu_run "$IU_C23G" >/dev/null
printf '{ "name": "fixture" }\n' > "$IU_C23G/package.json"
IU_O23G="$(bash "$LIB/../scripts/detect-project-tools.sh" "$IU_C23G" 2>&1)"
assert_eq "installer-upgrade #971: the single-argument form still scans the repo it updates (the /prflow:init path is unchanged)" "yes yes" \
  "$(_iu_out_matches "$IU_O23G" 'devflow-detect: detected: node —') $(_iu_has "$IU_C23G/.prflow/config.json" 'Bash(npm:*)')"
