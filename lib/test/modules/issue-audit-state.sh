# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# shellcheck shell=bash
# Sourceable issue-audit-state contract module.
#
# It carries the `scripts/issue-audit-state.py` audit-lifecycle drivers — the state
# owner behind `/devflow:create-issue` Step 3.6 — so a change scoped to that CLI is
# verifiable in seconds with `lib/test/run-module.sh issue-audit-state` instead of the
# complete suite.
#
# Contract: the caller sets LIB and RESULTS_FILE, defines assert_eq, and sources
# lib/test/module-harness.sh first. This module uses assert_eq (caller-provided, per that
# contract — both run.sh and run-module.sh define it) plus the harness helpers
# lib/test/module-harness.sh defines — `git_sandbox` (every fixture below allocates its
# own throwaway git repo through it) and `record_fail` — and references NO helper that
# lives ONLY in lib/test/run.sh. It carries one private helper, `ias_instructions`,
# whose only call sites are in this file. Every fixture root is allocated by
# `git_sandbox` under $TMPDIR and removed by its own block's trailing `rm -rf`; the
# module writes nothing into the repository working tree. It never invokes the runner
# or the full-suite boundary, carries no pin helper, and may not self-skip (a
# host-capability condition would have to route through `module_host_capability_skip`;
# none applies here). The inventory in issue-audit-state.inventory.md maps the extracted
# coverage to its former run.sh location and records the deliberate exclusions.

# ────────────────────────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────────────────────────
echo "issue #546: issue-audit-state.py — the create-issue audit-lifecycle state owner"

IAS="$LIB/../scripts/issue-audit-state.py"
# issue #709: the canonical dispatch-instruction generator the state owner regenerates
# from. Fixtures below whose subject is NOT steering still have to ESTABLISH it, because
# the clean eligibility ground now requires it — so they generate the instruction file,
# record it as the round's closed inputs, and quote the auditor's two return values.
IAS_RAP="$LIB/../scripts/render-audit-prompt.py"

# The generate-then-hash half of that recipe, hoisted so no fixture hand-inlines it: a
# missed or mistyped site does NOT fail loudly — the round degrades to unestablished and
# the fixture silently starts measuring the steering gate instead of its own subject.
# Writes <sandbox>/instr-<slug>.md (per-slug because the out-of-bounds paths the
# instructions carry embed the slug, so cross-slug reuse would legitimately mismatch) and
# prints the object ID the auditor would quote. The optional 4th argument overrides PATH
# for the generation itself (the restricted-PATH fixtures use it, which additionally
# proves the generator derives nothing through a non-preflight PATH tool).
ias_instructions() {  # <sandbox-root> <slug> <draft-path> [PATH-override]
  local root="$1" slug="$2" draft="$3"
  local PATH="${4:-$PATH}"
  # The draft may live outside the sandbox root (the draft-binding fixture audits a file
  # under its bound root), so an absolute path is taken verbatim.
  case "$draft" in /*) ;; *) draft="$root/$draft" ;; esac
  # Check the generation before hashing. The redirect truncates the target BEFORE the
  # generator runs, so on any failure (a RenderError, a title-less fixture draft, a
  # python3 absent from the restricted PATH the 4th argument installs) the file is left
  # empty and `git hash-object` prints the empty-blob ID — a valid-looking hash that
  # silently degrades every caller's round to unestablished, which is exactly the
  # failure class the comment above says this helper exists to prevent.
  if ! python3 "$IAS_RAP" dispatch-instructions --slug "$slug" \
      --draft-path "$draft" --instructions-path "$root/instr-$slug.md" \
      > "$root/instr-$slug.md" || [ ! -s "$root/instr-$slug.md" ]; then
    # Record the failure through the suite's OWN tally file, not a shell variable: every
    # call site invokes this helper inside a command substitution, so the subshell's
    # `FAIL=$((FAIL+1))` died with the subshell, and the authoritative count is recomputed
    # at the end as `grep -c '^FAIL$' "$RESULTS_FILE"` anyway. The first version of this
    # guard printed a FAIL-shaped line and still exited 0 — red on screen, green in the
    # summary. The RESULTS_FILE append is the guard that actually fires; the stdout
    # sentinel is a belt-and-braces poison value so a downstream digest comparison cannot
    # match by accident (no call site asserts on it directly). The diagnostic goes to
    # STDERR, not stdout: every call site is `X="$(ias_instructions …)"`, so a stdout
    # message is captured into the variable and never reaches the operator.
    echo FAIL >> "$RESULTS_FILE"
    record_fail "ias_instructions($slug): dispatch-instruction generator produced no bytes"
    printf '  FAIL  ias_instructions(%s): the dispatch-instruction generator failed or wrote no bytes; every fixture using this slug would silently measure the steering gate instead of its own subject\n' "$slug" >&2
    echo 'GENERATOR-FAILED'
    return 1
  fi
  git hash-object --stdin --no-filters < "$root/instr-$slug.md"
}

# issue #1104: a FRESH file-arm `record-dispatch` refuses draft bytes that are not
# recoverable from the run's recorded byte history. That is a PRECONDITION of a file-arm
# fixture below, in the same class as the `init` each one already runs — the guarantee is
# not any of their subjects, so this helper carries the recipe once and a fixture calls it
# instead of re-inlining it. The artifact is content-addressed — the digest inside the
# `.staged.md` suffix, the property `record-staged-write` and the byte-history reader key
# on, NOT the `issue-draft-<slug>.<nonce>.<digest>.staged.md` shape `resolve_staged_path`
# produces — and it is left on disk: the guard re-reads it, so a helper that removed it
# here would refuse the very dispatch it was called to enable.
#
# It never aborts the module — a fixture whose dispatch is EXPECTED to fail must fail on
# its own subject's guard, not on this helper's exit status — but it never fails SILENTLY
# either: a failure arm breadcrumbs to stderr naming the slug, so an environment-induced
# staging breakage reads as one attributable line rather than as a crowd of unrelated
# fixtures failing on `file-arm-requires-staged-write`. It is also INERT at a site whose
# dispatch is refused by an earlier guard (a retry, an out-of-order or still-open round, a
# write-path refusal); calling it there costs a staging round-trip and changes nothing.
#
# Retention has a consequence the Python harness deliberately avoids by unlinking: with the
# artifact on disk a later round's `select_round_kind` can reconstruct these bytes and
# answer `targeted`, which `_cross_check_kind` then refuses against a hardcoded
# `--kind discovery`. Adding a `record-revision` to a retained-artifact fixture will flip
# the tool-selected kind — it fails loudly, but not on that fixture's own subject.
ias_stage() {  # <slug> <nonce> <draft-file>
  local dig art
  if ! dig="$(git hash-object --stdin --no-filters < "$3")"; then
    printf '  ias-stage %s: could not digest %s; the byte-history precondition was NOT established\n' "$1" "$3" >&2
    return 0
  fi
  art="$(pwd)/staged-$1.$dig.staged.md"
  if ! cp "$3" "$art"; then
    printf '  ias-stage %s: could not copy %s to the staging artifact; the byte-history precondition was NOT established\n' "$1" "$3" >&2
    return 0
  fi
  # Only stdout is discarded: the tool's OWN named refusal (staged-digest-mismatch,
  # staged-path-not-absolute, staged-artifact-unreadable, a foreign nonce) rides out on
  # stderr beside the helper's line, so the breadcrumb names the cause and not just the fault.
  python3 "$IAS" record-staged-write "$1" --nonce "$2" --path "$art" --digest "$dig" \
    > /dev/null \
    || printf '  ias-stage %s: record-staged-write exited non-zero; the byte-history precondition was NOT established\n' "$1" >&2
}

# help_surface_pin — pinned against the RENDERED --help output, whitespace-normalized.
# Never a source grep on the argparse help= strings: those are concatenated across
# adjacent literals, so a source pin would live on no single line (#375).
# NO_COLOR/PYTHON_COLORS: argparse colorizes its help on python >= 3.14 when the
# rendering path allows it, and the ANSI escapes would land INSIDE a pinned phrase and
# fail the match on exactly the newer interpreters this repo supports.
IAS_HELP_546="$(NO_COLOR=1 PYTHON_COLORS=0 python3 "$IAS" --help 2>&1 | tr -s '[:space:]' ' ')"
assert_eq "#546 help_surface_pin: --help states the query exit-0 contract (rendered)" \
  "1" "$(printf '%s' "$IAS_HELP_546" | grep -oF -- 'Queries always exit 0 once the arguments parse and print a decided answer line' | grep -c .)"
# issue #795 + #1803: do not let the rendered description understate what the tool prints —
# mid-run callers consult it for the three-part output contract and the block's field subset.
assert_eq "#1803 help_surface_pin: --help states the summary-block line between the decided line and the final next_call= line (rendered)" \
  "1" "$(printf '%s' "$IAS_HELP_546" | grep -oF -- 'they print a summary-block line carrying a compact fixed subset of the query-summary fields' | grep -c .)"
assert_eq "#1803 help_surface_pin: --help enumerates the summary-block subset (rendered)" \
  "1" "$(printf '%s' "$IAS_HELP_546" | grep -oF -- 'state, findings_count, revisions_applied, verdict, rounds_run' | grep -c .)"
assert_eq "#546 help_surface_pin: --help states the mutation breadcrumb contract (rendered)" \
  "1" "$(printf '%s' "$IAS_HELP_546" | grep -oF -- 'mutations exit non-zero with a named breadcrumb' | grep -c .)"
# The subcommand roster renders in the PARENT help (a subparser's own --help does not
# repeat its help= string), so the mode enumeration is pinned there.
assert_eq "#546 help_surface_pin: the eligibility query renders both decided modes" \
  "1" "$(printf '%s' "$IAS_HELP_546" | grep -oF -- 'Presentation eligibility in approve or iterate mode' | grep -c .)"
assert_eq "#546 help_surface_pin: the gated emitter renders its refusal contract" \
  "1" "$(printf '%s' "$IAS_HELP_546" | grep -oF -- 'refuses with empty stdout when not eligible' | grep -c .)"
# issue #1695: record-dispatch --help states the two `--write-path` layers so the CLI help
# AGREES with the live create-issue caller contract (optional at the CLI boundary, required
# of the bound live caller). Pinned against the RENDERED subparser help, never a source grep.
IAS_HELP_1695="$(NO_COLOR=1 PYTHON_COLORS=0 python3 "$IAS" record-dispatch --help 2>&1 | tr -s '[:space:]' ' ')"
assert_eq "#1695 help_surface_pin: --write-path renders optional-at-CLI-boundary" \
  "1" "$(printf '%s' "$IAS_HELP_1695" | grep -oF -- 'Optional at THIS CLI boundary' | grep -c .)"
assert_eq "#1695 help_surface_pin: --write-path renders the required-live-caller layer" \
  "1" "$(printf '%s' "$IAS_HELP_1695" | grep -oF -- 'the live create-issue file-arm caller is required to forward the bound canonical path' | grep -c .)"

# cli_roundtrip_restricted_path — the full lifecycle end-to-end under a PATH holding only
# git and python3, proving no value that decides a selection or an emitted result is derived
# through a non-preflight PATH tool (guard-class 2). Also asserts the run creates no file
# besides the state JSON.
IAS_SB="$(git_sandbox '#546 cli_roundtrip_restricted_path')"
if [ -d "$IAS_SB" ]; then
  (
    cd "$IAS_SB" || exit 1
    git init -q . 2>/dev/null
    mkdir -p .prflow/tmp
    printf '# Draft title\n\nBody line one.\nBody line two.\n' > draft.md

    # A genuinely restricted PATH: a scratch bin dir holding symlinks to ONLY git and
    # python3. Adding the DIRECTORIES those binaries live in would not restrict anything
    # — git ships in /usr/bin, which also carries tr/sed/awk/wc AND (on macOS) an older
    # system python3 that would shadow the real interpreter and silently answer the
    # version guard instead of running the tool.
    mkdir -p restricted-bin
    ln -sf "$(command -v git)" restricted-bin/git
    ln -sf "$(command -v python3)" restricted-bin/python3
    RESTRICTED="$IAS_SB/restricted-bin"

    # issue #795: `init` now prints a trailing `next_call=` line after its decided
    # `nonce=` line, so the mint reads the FIRST line only. `sed -n '1s///p'` prints just
    # that line, substituted; without the line address the second line would ride into
    # $NONCE and every later --nonce would be a foreign-nonce mismatch.
    NONCE="$(PATH="$RESTRICTED" python3 "$IAS" init rt | sed -n '1s/nonce=//p')"
    printf 'nonce=%s\n' "$NONCE" > .rt-nonce

    PATH="$RESTRICTED" python3 "$IAS" query-arm rt --nonce "$NONCE" \
      --write-landed yes --draft-file draft.md > .rt-arm
    # issue #709: this fixture's subject is the restricted-PATH lifecycle, not steering, so
    # it ESTABLISHES steering-absence the way a real run does — generate the canonical
    # dispatch instructions, record them as the round's closed inputs, and quote the two
    # auditor return values. Without this the clean ground below is withheld and every
    # eligibility/emit row here would be asserting the steering gate instead of its own
    # subject. The generator runs under the SAME restricted PATH, which additionally
    # proves it derives nothing through a non-preflight PATH tool.
    IOID="$(ias_instructions "$IAS_SB" rt draft.md "$RESTRICTED")"
    ias_stage rt "$NONCE" draft.md
    # issue #1751: round 1 is no longer free-funded — the user elects it before it opens.
    PATH="$RESTRICTED" python3 "$IAS" record-offer rt --nonce "$NONCE" --accepted > /dev/null
    PATH="$RESTRICTED" python3 "$IAS" record-dispatch --kind discovery rt --nonce "$NONCE" \
      --round 1 --arm file --draft-file draft.md \
      --instructions-file "$IAS_SB/instr-rt.md" \
      --instructions-draft-path "$IAS_SB/draft.md" > .rt-dispatch
    OID="$(PATH="$RESTRICTED" git hash-object --stdin --no-filters < draft.md)"
    PATH="$RESTRICTED" python3 "$IAS" record-return rt --nonce "$NONCE" --round 1 \
      --verdict REVISE --findings-count 2 --carriage-object-id "$OID" \
      --instructions-object-id "$IOID" --extra-dispatch-content no > .rt-return
    PATH="$RESTRICTED" python3 "$IAS" query-next-action rt --nonce "$NONCE" --round 1 > .rt-next
    # #548: adjudicate the REVISE round (2 unresolved must-revise) — T1 now consumes the
    # post-adjudication unresolved count, so it holds only after this record, not on the raw
    # REVISE token. Also capture the pre-adjudication convergence (unadjudicated) beforehand.
    PATH="$RESTRICTED" python3 "$IAS" query-convergence rt --nonce "$NONCE" > .rt-conv-preadj
    # #603: a REVISE adjudication with a settled count now REQUIRES the per-finding
    # ledger on stdin. The QUOTED-delimiter heredoc is the decided transport — the second
    # summary carries `$(…)` and a backtick precisely so this row proves the shell
    # performs no expansion on auditor-derived text (query-findings re-emits it verbatim
    # below).
    PATH="$RESTRICTED" python3 "$IAS" record-adjudication rt --nonce "$NONCE" --round 1 \
      --verdict REVISE --must-revise 2 --advisory 0 --invalid 0 --unresolved-must-revise 2 \
      --ledger-stdin > .rt-adj <<'LEDGER-EOF'
unresolved@12: first finding
unresolved: second finding $(not expanded) `nor this`
LEDGER-EOF
    # issue #889: the first ledger line carries the OPTIONAL `@<n>` draft-line
    # coordinate — the draft line the auditor quoted as the line it attacks. Every
    # later query below re-loads the state and runs `_validate_ledger` over this
    # entry, so the flow proves ingest + persistence + the read-boundary validation
    # of the new field; assert the recorded value directly from the state file (the
    # second, coordinate-less line proves the field stays absent when not supplied).
    IAS889_RC=0
    PATH="$RESTRICTED" python3 -c 'import json,sys; d=json.load(open(".prflow/tmp/issue-audit-state-rt.json")); f=[r for r in d["rounds"] if r["round"]==1][0]["findings"]; sys.exit(0 if f[0].get("quoted_draft_line")==12 and "quoted_draft_line" not in f[1] else 1)' || IAS889_RC=$?
    assert_eq "issue #889: ledger records the per-finding quoted_draft_line coordinate" "0" "$IAS889_RC"
    # issue #889: the PRODUCER round-trip. Every committed states/ fixture is
    # hand-authored, so a field rename on the writer side would leave the eval's own
    # unit tests green while `read_state` silently returned None/empty on every real
    # file — the unverified-assumption class. This drives the state file the state owner
    # itself just wrote through the eval's reader and asserts the joint field names
    # (`rounds[].round` / `.kind` / `.findings[].status` / `.quoted_draft_line`) resolve.
    IAS889RT_RC=0
    PATH="$RESTRICTED" python3 -c '
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location("cice", os.path.join(sys.argv[1], "scripts", "create-issue-context-eval.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
st = m.read_state(".prflow/tmp/issue-audit-state-rt.json")
if st is None: sys.exit(2)                                   # the reader rejected a real producer file
if st[1]["kind"] != "discovery": sys.exit(3)                 # round->kind labelling resolved
f = st[1]["findings"]
if len(f) != 2: sys.exit(4)                                  # the ledger resolved
if m._finding_draft_line(f[0]) != 12: sys.exit(5)            # the draft-line coordinate resolved
if m._finding_draft_line(f[1]) is not None: sys.exit(6)      # absent stays unattributable
if not m._is_outstanding_must_revise(f[0]): sys.exit(7)      # the status field resolved
if m._finding_count(st) != 2: sys.exit(8)                    # never the UNESTABLISHED sentinel
' "$LIB/.." || IAS889RT_RC=$?
    assert_eq "issue #889: the eval's read_state resolves a state file the state owner really wrote" "0" "$IAS889RT_RC"
    PATH="$RESTRICTED" python3 "$IAS" query-triggers rt --nonce "$NONCE" > .rt-trig
    PATH="$RESTRICTED" python3 "$IAS" query-convergence rt --nonce "$NONCE" > .rt-conv-revise

    # Revise the draft, record it, then assert approve mode refuses the unaudited bytes.
    printf '# Draft title\n\nBody line one (revised).\nBody line two.\n' > draft.md
    # issue #705: the round dispatched on the file arm, so record-revision now requires the
    # intended-bytes digest — pipe the revised draft to --stdin-digest.
    PATH="$RESTRICTED" python3 "$IAS" record-revision rt --nonce "$NONCE" --after-round 1 \
      --stdin-digest < draft.md > .rt-rev
    PATH="$RESTRICTED" python3 "$IAS" query-eligibility rt --nonce "$NONCE" \
      --mode approve --draft-file draft.md > .rt-elig-bad
    PATH="$RESTRICTED" python3 "$IAS" query-eligibility rt --nonce "$NONCE" \
      --mode iterate --draft-file draft.md > .rt-elig-iter
    # #603: the durable reconciliation read-back, then a post-revision resolution that
    # clears the round the findings were raised on, then the convergence answer that now
    # rests on a self-verified resolution basis rather than on an auditor FILE verdict.
    PATH="$RESTRICTED" python3 "$IAS" query-findings rt --nonce "$NONCE" > .rt-findings
    PATH="$RESTRICTED" python3 "$IAS" record-resolution rt --nonce "$NONCE" \
      --round 1 --revision-ordinal 1 --resolved-ids 1,2 > .rt-resolution
    PATH="$RESTRICTED" python3 "$IAS" query-convergence rt --nonce "$NONCE" > .rt-conv-resolved

    # issue #1105: round 1's findings were all RESOLVED above, yet the tool now selects a
    # TARGETED re-check rather than the pre-#1105 empty-claim-set discovery — a scoped round
    # re-audits the drafter's own resolutions. Drive the targeted round end to end, then the
    # CONFIRMING whole-draft round it schedules (which carries the clean-round narrative this
    # fixture asserts). The scope file is written OUTSIDE .prflow/tmp so the "creates no file
    # besides the state JSON" artifact assertion below still holds.
    PATH="$RESTRICTED" python3 "$IAS" query-round-kind rt --nonce "$NONCE" \
      --draft-file "$IAS_SB/draft.md" > .rt-roundkind
    PATH="$RESTRICTED" python3 "$IAS" write-dispatch-scope rt --nonce "$NONCE" \
      --draft-file draft.md --path "$IAS_SB/scope-rt.md" > .rt-scope
    # #1104: a fresh file-arm dispatch (targeted included) requires the exact draft bytes
    # recoverable from the byte history — stage the revised bytes before dispatching.
    ias_stage rt "$NONCE" draft.md
    # issue #1751: the automatic re-audit is abolished, so round 2 (a targeted round after a
    # REVISE discovery round) is user-elected too. Round 3 below is the CONFIRMING round,
    # funded from its own counter, and takes no offer.
    PATH="$RESTRICTED" python3 "$IAS" record-offer rt --nonce "$NONCE" --accepted > /dev/null
    PATH="$RESTRICTED" python3 "$IAS" record-dispatch --kind targeted rt --nonce "$NONCE" \
      --round 2 --arm file --draft-file draft.md --scope-file "$IAS_SB/scope-rt.md" > .rt-tdispatch
    DIG2T="$(PATH="$RESTRICTED" git hash-object --stdin --no-filters < draft.md)"
    PATH="$RESTRICTED" python3 "$IAS" record-return rt --nonce "$NONCE" --round 2 \
      --verdict FILE --findings-count 0 --carriage-object-id "$DIG2T" \
      --claim-verdicts "1.1 addressed
1.2 addressed" > .rt-treturn
    PATH="$RESTRICTED" python3 "$IAS" query-next-action rt --nonce "$NONCE" --round 2 > .rt-tnext
    # issue #1105: the targeted round froze a draft_lines span on its scope (the #889
    # scope-escape proxy's comparand). Assert the recorded shape directly from the state
    # file: a two-element ordered non-bool int list.
    IAS1105_RC=0
    PATH="$RESTRICTED" python3 -c 'import json,sys; d=json.load(open(".prflow/tmp/issue-audit-state-rt.json")); s=[r for r in d["rounds"] if r["round"]==2][0]["scope"]["draft_lines"]; sys.exit(0 if isinstance(s,list) and len(s)==2 and all(isinstance(x,int) and not isinstance(x,bool) for x in s) and s[0]<=s[1] else 1)' || IAS1105_RC=$?
    assert_eq "issue #1105: a targeted dispatch freezes a two-element ordered draft_lines span on its scope" "0" "$IAS1105_RC"

    # The CONFIRMING whole-draft round (round 3), funded from its own counter. It carries the
    # clean-round advisory/adjudication/eligibility narrative. Regenerate the instructions
    # AFTER the revision: the generator reads the title from the draft file, so a round must
    # be established against the bytes it actually audits.
    IOID2="$(ias_instructions "$IAS_SB" rt draft.md "$RESTRICTED")"
    ias_stage rt "$NONCE" draft.md
    PATH="$RESTRICTED" python3 "$IAS" record-dispatch --kind discovery rt --nonce "$NONCE" \
      --round 3 --arm file --draft-file draft.md \
      --instructions-file "$IAS_SB/instr-rt.md" \
      --instructions-draft-path "$IAS_SB/draft.md" > /dev/null
    OID2="$(PATH="$RESTRICTED" git hash-object --stdin --no-filters < draft.md)"
    PATH="$RESTRICTED" python3 "$IAS" record-return rt --nonce "$NONCE" --round 3 \
      --verdict FILE --findings-count 0 --carriage-object-id "$OID2" \
      --instructions-object-id "$IOID2" --extra-dispatch-content no > /dev/null
    # #548: adjudicate the clean round (FILE, 0 unresolved must-revise) — the run now converges.
    # #743: a non-zero --advisory now REQUIRES a matching per-finding records file (the
    # deterministic recording floor). The Write-tool JSON transport is a plain file, so the
    # restricted-PATH lifecycle authors it with printf (a bash builtin, PATH-independent).
    printf '%s' '[{"summary":"a nit","rationale":"cosmetic","impact_class":"clearly-optional","evidence":"none needed","auditor_block":"Quoted: x\nSeverity: low"}]' > adv-rt.json
    PATH="$RESTRICTED" python3 "$IAS" record-adjudication rt --nonce "$NONCE" --round 3 \
      --verdict FILE --must-revise 0 --advisory 1 --invalid 0 --unresolved-must-revise 0 \
      --advisory-records-file adv-rt.json > /dev/null
    # #743: read back the round-3 advisory record and the calibration axis under the SAME
    # restricted PATH (git + python3 only), proving the new read-back + calibration + render
    # commands derive nothing through a non-preflight PATH tool. Round 3 recorded one
    # clearly-optional, evidenced advisory (adv-rt.json) → calibration-clear, but its render is
    # unreported until reported, so the disclosure trigger holds on the render tooth alone.
    PATH="$RESTRICTED" python3 "$IAS" query-adjudication-records rt --nonce "$NONCE" --round 3 > .rt-adjrec
    PATH="$RESTRICTED" python3 "$IAS" query-calibration rt --nonce "$NONCE" > .rt-calib
    PATH="$RESTRICTED" python3 "$IAS" record-adjudication-render rt --nonce "$NONCE" --round 3 --landed yes > .rt-render
    PATH="$RESTRICTED" python3 "$IAS" query-calibration rt --nonce "$NONCE" > .rt-calib2
    PATH="$RESTRICTED" python3 "$IAS" query-convergence rt --nonce "$NONCE" > .rt-conv-file
    # #548: query-convergence must fail closed on a FOREIGN nonce over this SAME converged
    # state — a foreign caller must never read a converged verdict off another run. Every
    # sibling query class already has a foreign-nonce row; convergence was the one omitted.
    # The `.rt-conv-file` assertion (correct nonce, converged=yes) is the positive control on
    # the identical fixture, so this refusal cannot be an unrelated precondition firing.
    PATH="$RESTRICTED" python3 "$IAS" query-convergence rt --nonce badnonce > .rt-conv-fn 2>/dev/null
    PATH="$RESTRICTED" python3 "$IAS" query-eligibility rt --nonce "$NONCE" \
      --mode approve --draft-file draft.md > .rt-elig-ok
    PATH="$RESTRICTED" python3 "$IAS" query-summary rt --nonce "$NONCE" \
      --draft-file draft.md > .rt-summary
    PATH="$RESTRICTED" python3 "$IAS" emit-body rt --nonce "$NONCE" --draft-file draft.md > .rt-body
    printf '%s\n' "$(ls .prflow/tmp)" > .rt-files
  )

  assert_eq "#546 cli_roundtrip_restricted_path: query-arm routes a landed write to the file arm" \
    "arm=file marker=none" "$(sed -n 1p "$IAS_SB/.rt-arm" 2>/dev/null)"
  assert_eq "#546 cli_roundtrip_restricted_path: a REVISE return classifies accept-revise" \
    "classification=accept-revise outcome=REVISE steering=established steering_reason=canonical-match" \
    "$(sed -n 1p "$IAS_SB/.rt-return" 2>/dev/null)"
  assert_eq "#1751 cli_roundtrip_restricted_path: a REVISE round falls through to the user-chosen-offer evaluation (the automatic re-audit is abolished)" \
    "action=revise-then-evaluate-offer" "$(sed -n 1p "$IAS_SB/.rt-next" 2>/dev/null)"
  assert_eq "#548 cli_roundtrip_restricted_path: T1 holds after a REVISE round is ADJUDICATED (not on the raw token)" \
    "1" "$(grep -c 't1=hold' "$IAS_SB/.rt-trig" 2>/dev/null)"
  assert_eq "#548 cli_roundtrip_restricted_path: an un-adjudicated REVISE round is not converged" \
    "converged=no reason=unadjudicated basis=none unledgered_revise=none" "$(sed -n 1p "$IAS_SB/.rt-conv-preadj" 2>/dev/null)"
  assert_eq "#548 cli_roundtrip_restricted_path: an adjudicated REVISE with unresolved must-revise is not converged" \
    "converged=no reason=unresolved-must-revise-remain basis=none unledgered_revise=none" "$(sed -n 1p "$IAS_SB/.rt-conv-revise" 2>/dev/null)"
  assert_eq "#548 cli_roundtrip_restricted_path: adjudicated FILE with 0 unresolved converges" \
    "converged=yes reason= basis=adjudicated unledgered_revise=none" "$(sed -n 1p "$IAS_SB/.rt-conv-file" 2>/dev/null)"
  assert_eq "#548 cli_roundtrip_restricted_path: query-convergence fails closed on a foreign nonce (never reads a converged verdict off another run)" \
    "converged=no reason=foreign-nonce basis=none unledgered_revise=none" "$(sed -n 1p "$IAS_SB/.rt-conv-fn" 2>/dev/null)"
  assert_eq "#1105 cli_roundtrip_restricted_path: an all-resolved run selects a TARGETED re-check (was pre-#1105 empty-claim-set discovery)" \
    "1" "$(grep -c 'kind=targeted reason=targeted-eligible' "$IAS_SB/.rt-roundkind" 2>/dev/null)"
  assert_eq "#1105 cli_roundtrip_restricted_path: the targeted return records its per-claim sweep over the resolved claims" \
    "1" "$(grep -c 'addressed=2 not_addressed=0' "$IAS_SB/.rt-treturn" 2>/dev/null)"
  assert_eq "#1105 cli_roundtrip_restricted_path: an all-addressed targeted round schedules the confirming whole-draft round" \
    "1" "$(grep -c 'confirm-whole-draft' "$IAS_SB/.rt-tnext" 2>/dev/null)"
  assert_eq "#548 cli_roundtrip_restricted_path: query-summary RENDERS the latest round's adjudicated tokens at the CLI (round 3: FILE, 0 unresolved)" \
    "1" "$(grep -v '^summary-block ' "$IAS_SB/.rt-summary" 2>/dev/null | grep -c 'adjudicated_verdict=FILE must_revise=0 advisory=1 invalid=0 unresolved_must_revise=0')"
  assert_eq "#548 cli_roundtrip_restricted_path: record-adjudication echoes the adjudicated payload" \
    "adjudicated=REVISE unresolved=2 must_revise=2 advisory=0 invalid=0 superseded=0" "$(sed -n 1p "$IAS_SB/.rt-adj" 2>/dev/null)"
  assert_eq "#743 cli_roundtrip_restricted_path: query-adjudication-records reads back the round-3 advisory record" \
    "1" "$(grep -c 'record_class=advisory round=3 id=1 impact_class=clearly-optional impact_bearing=no evidence_state=recorded' "$IAS_SB/.rt-adjrec" 2>/dev/null)"
  assert_eq "#743 cli_roundtrip_restricted_path: an evidenced clearly-optional advisory is calibration-clear, but the unreported render holds the disclosure trigger" \
    "1" "$(grep -c 'calibration_backing=clear adjudication_render=unreported calibration_trigger=yes' "$IAS_SB/.rt-calib" 2>/dev/null)"
  assert_eq "#743 cli_roundtrip_restricted_path: record-adjudication-render reports the rendering" \
    "adjudication_render=reported round=3" "$(sed -n 1p "$IAS_SB/.rt-render" 2>/dev/null)"
  assert_eq "#743 cli_roundtrip_restricted_path: after a reported render on an all-clear round the calibration trigger clears" \
    "1" "$(grep -c 'calibration_trigger=no' "$IAS_SB/.rt-calib2" 2>/dev/null)"
  assert_eq "#603 cli_roundtrip_restricted_path: query-findings re-emits an auditor summary byte-verbatim (the quoted-delimiter heredoc performed no expansion)" \
    "round=1 id=2 status=unresolved summary=second finding \$(not expanded) \`nor this\`" \
    "$(sed -n 2p "$IAS_SB/.rt-findings" 2>/dev/null)"
  assert_eq "#603 cli_roundtrip_restricted_path: record-resolution derives the run-wide remaining count (no caller-supplied tally)" \
    "round=1 revision_ordinal=1 frozen=2 remaining=0" "$(sed -n 1p "$IAS_SB/.rt-resolution" 2>/dev/null)"
  assert_eq "#603 cli_roundtrip_restricted_path: a REVISE-latest run cleared by resolution converges on the resolution basis" \
    "converged=yes reason= basis=resolution unledgered_revise=none" "$(sed -n 1p "$IAS_SB/.rt-conv-resolved" 2>/dev/null)"
  assert_eq "#546 cli_roundtrip_restricted_path: approve mode refuses just-revised, not-yet-re-audited bytes" \
    "eligible=no reason=unaudited-revision" "$(sed -n 1p "$IAS_SB/.rt-elig-bad" 2>/dev/null)"
  assert_eq "#546 cli_roundtrip_restricted_path: iterate mode answers ok for the same bytes" \
    "iterate=ok ordinal=1" "$(sed -n 1p "$IAS_SB/.rt-elig-iter" 2>/dev/null)"
  assert_eq "#546 cli_roundtrip_restricted_path: a clean round on the revised bytes grounds eligible" \
    "1" "$(grep -c 'eligible=yes ground=file-identity' "$IAS_SB/.rt-elig-ok" 2>/dev/null)"
  assert_eq "#546 cli_roundtrip_restricted_path: the summary carries the same token the eligibility answer issued" \
    "$(sed -nE 's/.* token=([^ ]+).*/\1/p' "$IAS_SB/.rt-elig-ok" 2>/dev/null)" \
    "$(sed -nE 's/.* token=([^ ]+) .*/\1/p' "$IAS_SB/.rt-summary" 2>/dev/null)"
  # Positive control for the exact-compare above: an empty extraction on BOTH sides would
  # pass vacuously (empty == empty), so pin the issued token non-empty independently.
  assert_eq "#546 cli_roundtrip_restricted_path: the issued eligibility token is non-empty" \
    "1" "$(sed -nE 's/.* token=([^ ]+).*/\1/p' "$IAS_SB/.rt-elig-ok" 2>/dev/null | grep -c .)"
  assert_eq "#546 cli_roundtrip_restricted_path: emit-body emits the body below the title heading" \
    "Body line one (revised).
Body line two." "$(cat "$IAS_SB/.rt-body" 2>/dev/null)"
  # emit-body is in _NEXT_CALL_EXCLUDED but is NOT routed through _emit_next_call at all, so
  # the query-findings row alone leaves this path uncovered: a block appended here would forge
  # extra bytes into a body a caller pipes straight to `gh issue create`.
  assert_eq "#1803 summary_block: a SUCCESSFUL emit-body prints neither a summary-block nor a next_call= line" \
    "0:0" "$(grep -c '^summary-block ' "$IAS_SB/.rt-body" 2>/dev/null):$(grep -c '^next_call=' "$IAS_SB/.rt-body" 2>/dev/null)"
  assert_eq "#1803 summary_block: ... positive control — that emit-body did produce output (not a vacuous empty file)" \
    "1" "$([ -s "$IAS_SB/.rt-body" ] && echo 1 || echo 0)"
  # The tool's own artifact population is exactly one file: the state JSON.
  assert_eq "#546 cli_roundtrip_restricted_path: the run creates no file besides the state JSON" \
    "issue-audit-state-rt.json" "$(cat "$IAS_SB/.rt-files" 2>/dev/null)"
  rm -rf "$IAS_SB"
fi

# digest_filter_mode_rows — the content-filter fixtures. The tool hashes via
# `git hash-object --stdin --no-filters` at EVERY compare site; the path-mode form applies
# clean/CRLF filters and would return a different object ID for the same bytes under
# `core.autocrlf=true` (and under `* text=auto`), so a dispatch digest and an eligibility
# digest taken on an untouched CRLF draft would disagree and refuse a clean draft. Each row
# asserts the dispatch digest, the digest the amended auditor instruction produces
# (`git hash-object --no-filters`), and the eligibility digest agree byte-for-byte.
for FILTER_MODE in autocrlf textauto; do
  CRLF_SB="$(git_sandbox "#546 digest_filter_mode_rows ($FILTER_MODE)")"
  [ -d "$CRLF_SB" ] || continue
  (
    cd "$CRLF_SB" || exit 1
    git init -q .
    mkdir -p .prflow/tmp
    if [ "$FILTER_MODE" = autocrlf ]; then
      git config core.autocrlf true
    else
      printf '* text=auto\n' > .gitattributes
    fi
    printf '# T\r\n\r\nCRLF body line.\r\n' > draft.md
    NONCE="$(python3 "$IAS" init crlf | sed -n '1s/nonce=//p')"
    # The dispatch digest, as the tool records it.
    # issue #709: establish steering so the eligibility rows below still measure the
    # DIGEST agreement they are about. The instruction file is deliberately generated
    # under the same filter config, which additionally proves the instruction-file hash
    # is filter-immune for the same reason the draft digest is.
    IOID="$(ias_instructions "$CRLF_SB" crlf draft.md)"
    ias_stage crlf "$NONCE" draft.md
    python3 "$IAS" record-offer crlf --nonce "$NONCE" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery crlf --nonce "$NONCE" --round 1 --arm file \
      --draft-file draft.md --instructions-file "$CRLF_SB/instr-crlf.md" \
      --instructions-draft-path "$CRLF_SB/draft.md" \
      | sed -n -E '1s/.*digest=([0-9a-f]+) body_digest.*/\1/p' > .crlf-dispatch
    # The digest the AMENDED auditor instruction produces.
    git hash-object --no-filters draft.md > .crlf-auditor
    # The eligibility digest (the tool re-reads the file's bytes in binary and re-hashes).
    OID="$(git hash-object --stdin --no-filters < draft.md)"
    python3 "$IAS" record-return crlf --nonce "$NONCE" --round 1 --verdict FILE \
      --findings-count 0 --carriage-object-id "$OID" \
      --instructions-object-id "$IOID" --extra-dispatch-content no > /dev/null
    python3 "$IAS" query-eligibility crlf --nonce "$NONCE" --mode approve \
      --draft-file draft.md | sed -n -E '1s/.*key=([0-9a-f]+).*/\1/p' > .crlf-elig
    # The path-mode form, recorded ONLY to show the divergence this rule exists to avoid.
    git hash-object draft.md > .crlf-pathmode
  )
  assert_eq "#546 digest_filter_mode_rows ($FILTER_MODE): the dispatch digest and the amended auditor instruction agree" \
    "$(cat "$CRLF_SB/.crlf-auditor" 2>/dev/null)" "$(cat "$CRLF_SB/.crlf-dispatch" 2>/dev/null)"
  assert_eq "#546 digest_filter_mode_rows ($FILTER_MODE): the eligibility digest agrees with the dispatch digest" \
    "$(cat "$CRLF_SB/.crlf-dispatch" 2>/dev/null)" "$(cat "$CRLF_SB/.crlf-elig" 2>/dev/null)"
  assert_eq "#546 digest_filter_mode_rows ($FILTER_MODE): a clean CRLF draft grounds eligible (no filter-induced false mismatch)" \
    "$(cat "$CRLF_SB/.crlf-auditor" 2>/dev/null)" "$(cat "$CRLF_SB/.crlf-elig" 2>/dev/null)"
  rm -rf "$CRLF_SB"
done

# The stale pre-cutover markdown event log is INERT: a leftover .md beside an absent JSON
# reads as unestablished and is never parsed.
MD_SB="$(git_sandbox '#546 stale pre-cutover .md event log is inert')"
if [ -d "$MD_SB" ]; then
  (
    cd "$MD_SB" || exit 1
    git init -q .
    mkdir -p .prflow/tmp
    printf 'round 1 dispatched (file arm), digest abc123\nrevised after round 1\n' \
      > .prflow/tmp/issue-audit-state-legacy.md
    python3 "$IAS" query-eligibility legacy --nonce whatever --mode approve > .md-elig 2>/dev/null
    python3 "$IAS" query-triggers legacy --nonce whatever > .md-trig 2>/dev/null
  )
  assert_eq "#546 malformed-state matrix: a stale pre-cutover .md leftover is never read — state is unestablished" \
    "eligible=no reason=state-unestablished" "$(sed -n 1p "$MD_SB/.md-elig" 2>/dev/null)"
  assert_eq "#546 malformed-state matrix: ... and T2 holds on unestablished state (unknown is not zero)" \
    "1" "$(grep -c 't2=hold coverage=not-hold calibration=not-hold reason=state-unestablished' "$MD_SB/.md-trig" 2>/dev/null)"
  rm -rf "$MD_SB"
fi

# query_exit_contract_matrix — every query class against a malformed state file: exit 0 with
# a fail-closed token, never a crash presented as a value. Mutations exit non-zero.
QM_SB="$(git_sandbox '#546 query_exit_contract_matrix')"
if [ -d "$QM_SB" ]; then
  # `missing` is the AC-named row the matrix previously omitted: a genuinely ABSENT state
  # file (load_state's FileNotFoundError branch) must answer every query class fail-closed
  # at exit 0, exactly like the corrupt shapes — the `rm -f` arm guarantees no prior shape's
  # file lingers in the reused sandbox.
  for SHAPE in missing empty malformed array scalar; do
    (
      cd "$QM_SB" || exit 1
      # git init is load-bearing, not boilerplate: state_path() anchors to the git root, so
      # an un-init'd sandbox nested inside an outer repo resolves to the OUTER repo's path —
      # the malformed file written here is then never read, and every row passes vacuously
      # while exercising nothing.
      git init -q . 2>/dev/null
      mkdir -p .prflow/tmp
      case "$SHAPE" in
        missing)   rm -f .prflow/tmp/issue-audit-state-m.json ;;
        empty)     : > .prflow/tmp/issue-audit-state-m.json ;;
        malformed) printf '{not json' > .prflow/tmp/issue-audit-state-m.json ;;
        array)     printf '[]' > .prflow/tmp/issue-audit-state-m.json ;;
        scalar)    printf '"nope"' > .prflow/tmp/issue-audit-state-m.json ;;
      esac
      printf '# T\n\nB\n' > d.md
      for Q in "query-eligibility m --nonce n --mode approve --draft-file d.md" \
               "query-triggers m --nonce n" \
               "query-next-action m --nonce n --round 1" \
               "query-summary m --nonce n" \
               "query-nonce m"; do
        # shellcheck disable=SC2086
        python3 "$IAS" $Q > /dev/null 2>&1 || printf '%s\n' "NONZERO: $Q" >> ".qm-$SHAPE"
      done
      python3 "$IAS" record-revision m --nonce n --after-round 1 > /dev/null 2>&1 \
        && printf 'MUTATION-EXITED-ZERO\n' >> ".qm-mut-$SHAPE"
    )
    assert_eq "#546 query_exit_contract_matrix ($SHAPE): every query class exits 0 with a fail-closed answer" \
      "" "$(cat "$QM_SB/.qm-$SHAPE" 2>/dev/null)"
    assert_eq "#546 query_exit_contract_matrix ($SHAPE): a mutation against untrustworthy state exits non-zero" \
      "" "$(cat "$QM_SB/.qm-mut-$SHAPE" 2>/dev/null)"
  done
  rm -rf "$QM_SB"
fi

# reinit_force_rows — a same-run re-init over recorded rounds is illegal without --force;
# forced is recorded and surfaces as reinit_forced; a cold start (no nonce) is the ported
# delete-first wipe and raises no alarm.
RI_SB="$(git_sandbox '#546 reinit_force_rows')"
if [ -d "$RI_SB" ]; then
  (
    cd "$RI_SB" || exit 1
    git init -q .
    mkdir -p .prflow/tmp
    printf '# T\n\nB\n' > d.md
    N="$(python3 "$IAS" init ri | sed -n '1s/nonce=//p')"
    ias_stage ri "$N" d.md
    python3 "$IAS" record-offer ri --nonce "$N" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery ri --nonce "$N" --round 1 --arm file --draft-file d.md > /dev/null
    python3 "$IAS" init ri --nonce "$N" > .ri-unforced 2>&1 && printf 'EXITED-ZERO\n' >> .ri-unforced
    python3 "$IAS" init ri --nonce "$N" --force > /dev/null 2>&1
    python3 "$IAS" query-summary ri --nonce "$N" > .ri-forced
    # Sticky: the --force above wiped the rounds, so a LATER same-nonce re-init (no --force)
    # is legal via the no-rounds echo path and must PRESERVE reinit_forced=yes — otherwise
    # the budget-reset disclosure is launderable in two legal calls (issue #552 review I4).
    python3 "$IAS" init ri --nonce "$N" > /dev/null 2>&1
    python3 "$IAS" query-summary ri --nonce "$N" > .ri-sticky
    # Cold start over the same slug: the ported delete-first wipe, no alarm, new nonce.
    N2="$(python3 "$IAS" init ri | sed -n '1s/nonce=//p')"
    [ "$N2" != "$N" ] && printf 'new-nonce\n' > .ri-cold
    # A's now-foreign nonce is rejected after B's cold-start re-init.
    python3 "$IAS" record-revision ri --nonce "$N" --after-round 1 > /dev/null 2>&1 \
      || printf 'rejected\n' > .ri-foreign
  )
  assert_eq "#546 reinit_force_rows: a same-run re-init over recorded rounds is refused without --force" \
    "0" "$(grep -c 'EXITED-ZERO' "$RI_SB/.ri-unforced" 2>/dev/null)"
  assert_eq "#546 reinit_force_rows: ... and the refusal names the force requirement" \
    "1" "$(grep -c 'illegal transition without --force' "$RI_SB/.ri-unforced" 2>/dev/null)"
  assert_eq "#546 reinit_force_rows: a forced same-run re-init surfaces as reinit_forced=yes" \
    "1" "$(grep -c 'reinit_forced=yes' "$RI_SB/.ri-forced" 2>/dev/null)"
  assert_eq "#546 reinit_force_rows: a later same-nonce echo re-init PRESERVES reinit_forced=yes (not launderable)" \
    "1" "$(grep -c 'reinit_forced=yes' "$RI_SB/.ri-sticky" 2>/dev/null)"
  assert_eq "#546 reinit_force_rows: a cold-start re-init (no nonce) wipes and mints a new nonce, no alarm" \
    "new-nonce" "$(cat "$RI_SB/.ri-cold" 2>/dev/null)"
  assert_eq "#546 reinit_force_rows: after a foreign cold start, the prior run's nonce is rejected" \
    "rejected" "$(cat "$RI_SB/.ri-foreign" 2>/dev/null)"
  rm -rf "$RI_SB"
fi

# init_foreign_nonce_rows — the ('init','foreign-nonce',False) row, driven behaviorally at the
# CLI. Its two sibling branches (no-file, over-rounds-unforced) are CLI-driven above; before
# this block, foreign-nonce was covered only by the table/registry metadata lockstep, which
# asserts the ROW exists, never that cmd_init's guard actually refuses. The risk it pins is a
# silent budget reset for a foreign run that happens to share a slug.
#
# The fixture carries ZERO recorded rounds ON PURPOSE, and the block ATTRIBUTES the rejection:
#  * zero rounds means the over-rounds-unforced guard CANNOT be what rejects (it is gated on
#    `existing['rounds']`), so a green assert here cannot be that sibling guard firing;
#  * the state file exists and is readable, so the no-file branch cannot be it either;
#  * the assert pins the foreign-nonce guard's OWN breadcrumb, not a bare non-zero exit — a
#    bare exit-code assert would stay green against a mutant that disabled this very guard;
#  * a POSITIVE CONTROL on the same fixture (same slug, same file, CORRECT nonce) exits 0,
#    proving the fixture is otherwise valid and would succeed but for the foreign nonce.
FN_SB="$(git_sandbox '#546 init_foreign_nonce_rows')"
if [ -d "$FN_SB" ]; then
  (
    cd "$FN_SB" || exit 1
    git init -q .
    mkdir -p .prflow/tmp
    N="$(python3 "$IAS" init fn < /dev/null | sed -n '1s/nonce=//p')"
    printf '%s\n' "$N" > .fn-nonce
    # The refusal, attributed by its own breadcrumb.
    python3 "$IAS" init fn --nonce "foreign-$N" < /dev/null > .fn-foreign 2>&1 \
      && printf 'EXITED-ZERO\n' >> .fn-foreign
    # The budget-reset risk: the refusal must leave the incumbent run's nonce untouched.
    python3 "$IAS" query-nonce fn < /dev/null > .fn-after 2>&1
    # POSITIVE CONTROL on the same fixture: the correct nonce is accepted.
    python3 "$IAS" init fn --nonce "$N" < /dev/null > .fn-control 2>&1 \
      || printf 'CONTROL-REJECTED\n' >> .fn-control
  )
  assert_eq "#546 init_foreign_nonce_rows: a foreign nonce over an existing readable state is refused" \
    "0" "$(grep -c 'EXITED-ZERO' "$FN_SB/.fn-foreign" 2>/dev/null)"
  assert_eq "#546 init_foreign_nonce_rows: ... and the refusal is attributed to the foreign-run guard by its own breadcrumb" \
    "1" "$(grep -c 'refusing to re-init a foreign run' "$FN_SB/.fn-foreign" 2>/dev/null)"
  assert_eq "#546 init_foreign_nonce_rows: ... and the incumbent run's nonce survives the refusal (no silent budget reset)" \
    "nonce=$(sed -n 1p "$FN_SB/.fn-nonce" 2>/dev/null)" "$(sed -n 1p "$FN_SB/.fn-after" 2>/dev/null)"
  assert_eq "#546 init_foreign_nonce_rows: positive control — the SAME fixture accepts its own nonce, so the refusal above is not an unrelated precondition" \
    "0" "$(grep -c 'CONTROL-REJECTED' "$FN_SB/.fn-control" 2>/dev/null)"
  rm -rf "$FN_SB"
fi

# embed_arm_emit_rows — the embed-arm weaker-identity emit, driven end-to-end. The file-arm
# emit round-trips through creation_binding_rows above, but the embed arm — where the module
# header discloses the gate "cannot byte-bind what it emits" — had no end-to-end drive at all.
# This block pins that DISCLOSED residual as observed behavior, so a future claim that the
# embed arm byte-binds has a live counter-example, and so the residual cannot silently widen.
EA_SB="$(git_sandbox '#546 embed_arm_emit_rows')"
if [ -d "$EA_SB" ]; then
  (
    cd "$EA_SB" || exit 1
    git init -q .
    mkdir -p .prflow/tmp
    printf '# T\n\nEmbed body.\n' > d.md
    N="$(python3 "$IAS" init ea < /dev/null | sed -n '1s/nonce=//p')"
    # The embed arm takes the draft bytes on stdin (there is no trustworthy file to point at).
    python3 "$IAS" record-offer ea --nonce "$N" --accepted > /dev/null
    D="$(python3 "$IAS" record-dispatch --kind discovery ea --nonce "$N" --round 1 --arm embed \
           --marker digest-unrecorded < d.md)"
    # Carriage on this arm is the sentinel pair, not an object ID.
    SO="$(printf '%s' "$D" | tr ' ' '\n' | sed -n 's/^sentinel_open=//p')"
    SC="$(printf '%s' "$D" | tr ' ' '\n' | sed -n 's/^sentinel_close=//p')"
    python3 "$IAS" record-return ea --nonce "$N" --round 1 --verdict FILE --findings-count 0 \
      --carriage-sentinel-open "$SO" --carriage-sentinel-close "$SC" < /dev/null > /dev/null
    # issue #709: the embed arm has no writable canonical instruction file — it is entered
    # BECAUSE the draft-file write failed — so steering-absence is unestablished by
    # construction and the coverage-backed clean ground is withheld here. Capture that
    # designed consequence first (it is the AC6 statement, made observable), then reach
    # this block's actual subject through the documented Step 4 override election, which
    # is exactly how a real run files on this arm. Filing is not blocked; the clean
    # GROUNDING is what was withheld.
    python3 "$IAS" query-eligibility ea --nonce "$N" --mode approve --draft-file d.md \
      < /dev/null > .ea-elig-preoverride 2>&1
    python3 "$IAS" record-override ea --nonce "$N" --kind user-decline \
      --surface step4-offer < /dev/null > /dev/null
    python3 "$IAS" record-creation-epoch ea --nonce "$N" --round 1 < /dev/null > /dev/null
    python3 "$IAS" emit-body ea --nonce "$N" --draft-file d.md < /dev/null > .ea-body 2>&1
    python3 "$IAS" query-eligibility ea --nonce "$N" --mode approve --draft-file d.md \
      < /dev/null > .ea-elig 2>&1
    # The disclosed residual, made observable: swapping the draft's bytes does NOT refuse the
    # emit on this arm (the ground is event ordering, not byte identity) — which is exactly
    # why the post-hoc creation attestation is the detection surface for it. The attestation
    # below is the other half: it MUST catch the swap the emit could not.
    printf '# T\n\nSWAPPED body.\n' > d.md
    python3 "$IAS" emit-body ea --nonce "$N" --draft-file d.md < /dev/null > .ea-swapped 2>&1
    printf 'SWAPPED body.\n' | python3 "$IAS" record-creation-attestation ea --nonce "$N" \
      > .ea-att 2>&1
  )
  assert_eq "#546 embed_arm_emit_rows: an embed-arm epoch emits the audited body" \
    "Embed body." "$(sed -n 1p "$EA_SB/.ea-body" 2>/dev/null)"
  assert_eq "#709 embed_arm_emit_rows: the clean ground is withheld here BY CONSTRUCTION (no hashable instruction file)" \
    "eligible=no reason=steering-unestablished" "$(sed -n 1p "$EA_SB/.ea-elig-preoverride" 2>/dev/null)"
  assert_eq "#546/#709 embed_arm_emit_rows: ... and the user's override still grounds the emit, keyed by the revision ordinal (NOT a digest)" \
    "1" "$(grep -c 'eligible=yes ground=override .*key=0' "$EA_SB/.ea-elig" 2>/dev/null)"
  assert_eq "#546 embed_arm_emit_rows: the disclosed residual — swapped draft bytes still emit, because this arm cannot byte-bind" \
    "SWAPPED body." "$(sed -n 1p "$EA_SB/.ea-swapped" 2>/dev/null)"
  assert_eq "#546 embed_arm_emit_rows: ... and the post-hoc attestation is the detection surface that catches that swap" \
    "attestation=mismatch" "$(sed -n 1p "$EA_SB/.ea-att" 2>/dev/null)"
  rm -rf "$EA_SB"
fi

# creation_binding_rows — the attestation is honest: match, mismatch, and a failed fetch
# reported as attestation-unavailable, never as a pass.
CB_SB="$(git_sandbox '#546 creation_binding_rows')"
if [ -d "$CB_SB" ]; then
  (
    cd "$CB_SB" || exit 1
    git init -q .
    mkdir -p .prflow/tmp
    printf '# T\n\nThe body.\n' > d.md
    N="$(python3 "$IAS" init cb | sed -n '1s/nonce=//p')"
    # issue #709: establish steering so these attestation rows keep measuring the
    # attestation, not the new gate. One generated instruction file serves every epoch
    # here — they all audit the same d.md bytes, and the generator is deterministic.
    IOID="$(ias_instructions "$CB_SB" cb d.md)"
    ias_stage cb "$N" d.md
    python3 "$IAS" record-offer cb --nonce "$N" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery cb --nonce "$N" --round 1 --arm file --draft-file d.md \
      --instructions-file "$CB_SB/instr-cb.md" --instructions-draft-path "$CB_SB/d.md" > /dev/null
    OID="$(git hash-object --stdin --no-filters < d.md)"
    python3 "$IAS" record-return cb --nonce "$N" --round 1 --verdict FILE \
      --findings-count 0 --carriage-object-id "$OID" \
      --instructions-object-id "$IOID" --extra-dispatch-content no > /dev/null
    python3 "$IAS" record-creation-epoch cb --nonce "$N" --round 1 > /dev/null
    # The gated body emitter's bytes hash to the recorded body-only digest (round-trip).
    python3 "$IAS" emit-body cb --nonce "$N" --draft-file d.md \
      | python3 "$IAS" record-creation-attestation cb --nonce "$N" > .cb-match
    # The attestation is forward-only (round-3 hardening): the mismatch and
    # fetch-failure arms each get their OWN epoch on a fresh slug.
    for CASE in mm uv; do
      NC="$(python3 "$IAS" init "cb$CASE" | sed -n '1s/nonce=//p')"
      # The instructions are per-SLUG: regenerate for this epoch's slug so its recorded
      # digest is the one the tool will reproduce (a cross-slug reuse would legitimately
      # mismatch — the out-of-bounds paths carry the slug).
      IOIDC="$(ias_instructions "$CB_SB" "cb$CASE" d.md)"
      ias_stage "cb$CASE" "$NC" d.md
      python3 "$IAS" record-offer "cb$CASE" --nonce "$NC" --accepted > /dev/null
      python3 "$IAS" record-dispatch --kind discovery "cb$CASE" --nonce "$NC" --round 1 --arm file --draft-file d.md \
        --instructions-file "$CB_SB/instr-cb$CASE.md" --instructions-draft-path "$CB_SB/d.md" > /dev/null
      python3 "$IAS" record-return "cb$CASE" --nonce "$NC" --round 1 --verdict FILE \
        --findings-count 0 --carriage-object-id "$OID" \
        --instructions-object-id "$IOIDC" --extra-dispatch-content no > /dev/null
      python3 "$IAS" record-creation-epoch "cb$CASE" --nonce "$NC" --round 1 > /dev/null
      printf '%s\n' "$NC" > ".cb-nonce-$CASE"
    done
    printf 'a different body entirely\n' \
      | python3 "$IAS" record-creation-attestation cbmm --nonce "$(cat .cb-nonce-mm)" > .cb-mismatch
    python3 "$IAS" record-creation-attestation cbuv --nonce "$(cat .cb-nonce-uv)" --attestation-unavailable > .cb-unavail
  )
  assert_eq "#546 creation_binding_rows: the emitted body attests clean against the recorded body-only digest" \
    "attestation=match" "$(sed -n 1p "$CB_SB/.cb-match" 2>/dev/null)"
  assert_eq "#546 creation_binding_rows: a divergent created body is surfaced as a mismatch" \
    "attestation=mismatch" "$(sed -n 1p "$CB_SB/.cb-mismatch" 2>/dev/null)"
  assert_eq "#546 creation_binding_rows: a failed fetch reports attestation-unavailable, never a pass" \
    "attestation=attestation-unavailable" "$(sed -n 1p "$CB_SB/.cb-unavail" 2>/dev/null)"
  rm -rf "$CB_SB"
fi

# override_attestation_rows — a file-arm "file anyway" override over a REVISE verdict (PR #552
# review, Important #1). The user revises the draft AFTER the audited round returned REVISE and
# elects to file the revised bytes without another round. emit-body posts the CURRENT file
# (D2); the creation epoch must bind the digest of THOSE posted bytes, not the audited round's
# older bytes (D1) — otherwise the post-hoc attestation is a structurally-guaranteed `mismatch`
# on a legitimate override filing that GitHub stored faithfully (a false tamper signal). The fix:
# record-creation-epoch --draft-file binds the posted-file body digest. This block drives both
# arms of the fix on the SAME scenario: WITH --draft-file attests `match` (correct), and WITHOUT
# it reproduces the old false `mismatch` — so the assertion is a live positive control that the
# --draft-file binding is what removes the false signal, not a tautology.
OA_SB="$(git_sandbox '#546 override_attestation_rows')"
if [ -d "$OA_SB" ]; then
  (
    cd "$OA_SB" || exit 1
    git init -q .
    mkdir -p .prflow/tmp
    for SLUG in oafix oaold; do
      printf '# T\n\nBody one.\n' > "d-$SLUG.md"
      NS="$(python3 "$IAS" init "$SLUG" | sed -n '1s/nonce=//p')"
      ias_stage "$SLUG" "$NS" "d-$SLUG.md"
      python3 "$IAS" record-offer "$SLUG" --nonce "$NS" --accepted > /dev/null
      python3 "$IAS" record-dispatch --kind discovery "$SLUG" --nonce "$NS" --round 1 --arm file \
        --draft-file "d-$SLUG.md" > /dev/null
      OID1="$(git hash-object --stdin --no-filters < "d-$SLUG.md")"
      # The audited round returns REVISE (not clean) on the original bytes.
      python3 "$IAS" record-return "$SLUG" --nonce "$NS" --round 1 --verdict REVISE \
        --findings-count 1 --carriage-object-id "$OID1" > /dev/null
      # The user revises the draft file to new bytes (D2), then elects to file anyway.
      printf '# T\n\nBody two, revised.\n' > "d-$SLUG.md"
      # issue #705: file-arm round -> record-revision requires --stdin-digest.
      python3 "$IAS" record-revision "$SLUG" --nonce "$NS" --after-round 1 \
        --stdin-digest < "d-$SLUG.md" > /dev/null
      python3 "$IAS" record-override "$SLUG" --nonce "$NS" --kind user-decline \
        --surface step4-approval-after-exhausted-offer --draft-file "d-$SLUG.md" > /dev/null
      printf '%s' "$NS" > ".oa-nonce-$SLUG"
    done
    # eligibility grounds on the still-current override for the revised bytes.
    python3 "$IAS" query-eligibility oafix --nonce "$(cat .oa-nonce-oafix)" --mode approve \
      --draft-file d-oafix.md > .oa-elig 2>&1
    # FIX arm: bind the epoch to the posted (revised) file, then attest the emitted body.
    python3 "$IAS" record-creation-epoch oafix --nonce "$(cat .oa-nonce-oafix)" --round 1 \
      --draft-file d-oafix.md > /dev/null
    python3 "$IAS" emit-body oafix --nonce "$(cat .oa-nonce-oafix)" --draft-file d-oafix.md \
      | python3 "$IAS" record-creation-attestation oafix --nonce "$(cat .oa-nonce-oafix)" > .oa-fix
    # OLD arm (same scenario, no --draft-file): the epoch binds the audited round's older
    # body, so the identical faithful post attests as a false mismatch.
    python3 "$IAS" record-creation-epoch oaold --nonce "$(cat .oa-nonce-oaold)" --round 1 \
      > /dev/null
    python3 "$IAS" emit-body oaold --nonce "$(cat .oa-nonce-oaold)" --draft-file d-oaold.md \
      | python3 "$IAS" record-creation-attestation oaold --nonce "$(cat .oa-nonce-oaold)" > .oa-old
  )
  assert_eq "#546 override_attestation_rows: a file-arm 'file anyway' override grounds eligibility on the revised bytes" \
    "1" "$(grep -c 'eligible=yes ground=override' "$OA_SB/.oa-elig" 2>/dev/null)"
  assert_eq "#546 override_attestation_rows: --draft-file binds the POSTED body, so a faithful override filing attests match (no false tamper signal)" \
    "attestation=match" "$(sed -n 1p "$OA_SB/.oa-fix" 2>/dev/null)"
  assert_eq "#546 override_attestation_rows: positive control — WITHOUT --draft-file the epoch binds the audited round's older body, reproducing the old false mismatch" \
    "attestation=mismatch" "$(sed -n 1p "$OA_SB/.oa-old" 2>/dev/null)"
  rm -rf "$OA_SB"
fi

# emit-body is the gated emitter: it refuses with EMPTY stdout so a caller that pipes it
# into `gh issue create --body-file -` without pipefail cannot post an unaudited body.
EB_SB="$(git_sandbox '#546 emit-body is gated')"
if [ -d "$EB_SB" ]; then
  (
    cd "$EB_SB" || exit 1
    git init -q .
    mkdir -p .prflow/tmp
    printf '# T\n\nB\n' > d.md
    N="$(python3 "$IAS" init eb | sed -n '1s/nonce=//p')"
    ias_stage eb "$N" d.md
    python3 "$IAS" record-offer eb --nonce "$N" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery eb --nonce "$N" --round 1 --arm file --draft-file d.md > /dev/null
    OID="$(git hash-object --stdin --no-filters < d.md)"
    python3 "$IAS" record-return eb --nonce "$N" --round 1 --verdict REVISE \
      --findings-count 1 --carriage-object-id "$OID" > /dev/null
    python3 "$IAS" emit-body eb --nonce "$N" --draft-file d.md > .eb-out 2> .eb-err
    printf 'rc=%s\n' "$?" > .eb-rc
  )
  assert_eq "#546 emit-body is gated: an unaudited draft is refused with a non-zero exit" \
    "rc=1" "$(cat "$EB_SB/.eb-rc" 2>/dev/null)"
  assert_eq "#546 emit-body is gated: ... and stdout is EMPTY, so an unguarded pipe cannot post an unaudited body" \
    "" "$(cat "$EB_SB/.eb-out" 2>/dev/null)"
  assert_eq "#546 emit-body is gated: ... and the refusal names the eligibility reason" \
    "1" "$(grep -c 'refusing to emit an unaudited body' "$EB_SB/.eb-err" 2>/dev/null)"
  rm -rf "$EB_SB"
fi

# next_action_budget_rows — the retry/budget arms of `query-next-action`, driven end-to-end
# through the CLI. Added by the #546 pin reconciliation: these carry the guarantees the deleted
# #522 prose pins used to assert — "file-arm DRAFT-UNREADABLE re-dispatches exactly once on the
# embed arm", "an embed-arm DRAFT-UNREADABLE never triggers a second file-arm re-dispatch", and
# the automatic-budget arm. classify_return is unit-driven in test_python_scripts.py; what is
# driven HERE is next_action's answer, which no python row covered.
#
# Seven of the tool's eight answer tokens are driven here; the eighth,
# round-open-awaiting-return, is driven by illegal_transition_rows and
# shadow_round_rows below. Two of the driven arms were dead code when
# the cutover's pin reconciliation first drove this surface, and the rows below are the
# regression guard for both — each was a real defect the deleted #522 prose pin had been the
# only thing nominally protecting, so a cutover that deleted the pin without driving the arm
# would have shipped the guarantee enforced NOWHERE (not in prose, not in the tool):
#   1. `revise-then-evaluate-offer` was unreachable: `_MAX_AUTOMATIC_REAUDITS` was compared
#      against `automatic_reaudits_used`, but nothing ever incremented that counter, so the
#      automatic re-audit loop was unbounded (four consecutive REVISE rounds all answered
#      `revise-and-reaudit`). The counter was later spent where the round actually opens, and
#      issue #1751 then zeroed `_MAX_AUTOMATIC_REAUDITS` outright: `revise-and-reaudit` is now
#      unreachable and every REVISE round answers `revise-then-evaluate-offer`.
#   2. `dispatch-retry-same-arm` was unreachable: `record-return` set `no_parseable_retry_used`
#      and read it in the same branch, so the FIRST no-parseable-verdict return already looked
#      like the second and skipped the same-arm retry. The flag is now read before it is set.
NA_SB="$(git_sandbox '#546 next_action_budget_rows')"
if [ -d "$NA_SB" ]; then
  (
    cd "$NA_SB" || exit 1
    git init -q .
    mkdir -p .prflow/tmp
    printf '# T\n\nB\n' > d.md
    OID="$(git hash-object --stdin --no-filters < d.md)"

    # A clean FILE round proceeds.
    NF="$(python3 "$IAS" init nf | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-offer nf --nonce "$NF" --accepted > /dev/null
    ias_stage nf "$NF" d.md
    python3 "$IAS" record-dispatch --kind discovery nf --nonce "$NF" --round 1 --arm file --draft-file d.md > /dev/null
    python3 "$IAS" record-return nf --nonce "$NF" --round 1 --verdict FILE \
      --findings-count 0 --carriage-object-id "$OID" > /dev/null
    python3 "$IAS" query-next-action nf --nonce "$NF" --round 1 > .na-file

    # The DRAFT-UNREADABLE chain, in one round: the file arm's unreadable draft re-dispatches
    # ONCE on the embed arm; the embed arm's own DRAFT-UNREADABLE (an illegal verdict on that
    # arm) must NOT re-dispatch to the file arm again — it routes to the inline degraded arm,
    # which terminates the chain.
    NU="$(python3 "$IAS" init nu | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-offer nu --nonce "$NU" --accepted > /dev/null
    ias_stage nu "$NU" d.md
    python3 "$IAS" record-dispatch --kind discovery nu --nonce "$NU" --round 1 --arm file --draft-file d.md > /dev/null
    python3 "$IAS" record-return nu --nonce "$NU" --round 1 --verdict DRAFT-UNREADABLE \
      --carriage-object-id "$OID" > /dev/null
    python3 "$IAS" query-next-action nu --nonce "$NU" --round 1 > .na-unreadable-1
    # The re-dispatch reuses the SAME round — no second round record.
    python3 "$IAS" record-dispatch --kind discovery nu --nonce "$NU" --round 1 --arm embed \
      --marker file-unreadable < d.md > /dev/null
    python3 "$IAS" record-return nu --nonce "$NU" --round 1 --verdict DRAFT-UNREADABLE > /dev/null
    python3 "$IAS" query-next-action nu --nonce "$NU" --round 1 > .na-unreadable-2
    python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['rounds']))" \
      .prflow/tmp/issue-audit-state-nu.json > .na-rounds

    # The inline arm past both defined retries closes the round verdict-less rather than
    # looping — the termination invariant.
    NT="$(python3 "$IAS" init nt | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-offer nt --nonce "$NT" --accepted > /dev/null
    ias_stage nt "$NT" d.md
    python3 "$IAS" record-dispatch --kind discovery nt --nonce "$NT" --round 1 --arm file --draft-file d.md > /dev/null
    python3 "$IAS" record-return nt --nonce "$NT" --round 1 --carriage-object-id "$OID" > /dev/null
    # first no-parseable -> retry the SAME arm; a second -> the inline degraded arm
    # (the retry-arm binding refuses a shortcut straight to inline)
    ias_stage nt "$NT" d.md
    python3 "$IAS" record-dispatch --kind discovery nt --nonce "$NT" --round 1 --arm file --draft-file d.md > /dev/null
    python3 "$IAS" record-return nt --nonce "$NT" --round 1 --carriage-object-id "$OID" > /dev/null
    python3 "$IAS" record-dispatch --kind discovery nt --nonce "$NT" --round 1 --arm inline < d.md > /dev/null
    python3 "$IAS" record-return nt --nonce "$NT" --round 1 > /dev/null
    python3 "$IAS" query-next-action nt --nonce "$NT" --round 1 > .na-terminal

    # issue #1751: the automatic re-audit is abolished (_MAX_AUTOMATIC_REAUDITS = 0), so
    # EVERY discovery round is user-elected. Three consecutive REVISE rounds all fall through
    # to the user-chosen-offer evaluation, and each round must be FUNDED by an accepted offer
    # first (the round-funding gate refuses an unfunded open — the free first round is gone).
    NB="$(python3 "$IAS" init nb | sed -n '1s/nonce=//p')"
    for R in 1 2 3; do
      python3 "$IAS" record-offer nb --nonce "$NB" --accepted > /dev/null
      ias_stage nb "$NB" d.md
      python3 "$IAS" record-dispatch --kind discovery nb --nonce "$NB" --round "$R" --arm file \
        --draft-file d.md > /dev/null
      python3 "$IAS" record-return nb --nonce "$NB" --round "$R" --verdict REVISE \
        --findings-count 1 --carriage-object-id "$OID" > /dev/null
      # Accumulate the DECIDED line only: this file is a per-round sequence, and every
      # emitting subcommand now trails a `next_call=` line (issue #795) that would
      # interleave with the actions the assertion below reads.
      python3 "$IAS" query-next-action nb --nonce "$NB" --round "$R" \
        | sed -n 1p >> .na-budget
    done

    # The NO-PARSEABLE-VERDICT retry precedence: the FIRST such completion retries on the
    # same arm; only the SECOND routes to the inline degraded arm. Regression guard: the
    # retry flag was once set and read in one branch, so the first completion skipped the
    # same-arm retry entirely.
    NP="$(python3 "$IAS" init np | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-offer np --nonce "$NP" --accepted > /dev/null
    ias_stage np "$NP" d.md
    python3 "$IAS" record-dispatch --kind discovery np --nonce "$NP" --round 1 --arm file --draft-file d.md > /dev/null
    python3 "$IAS" record-return np --nonce "$NP" --round 1 --carriage-object-id "$OID" > /dev/null
    python3 "$IAS" query-next-action np --nonce "$NP" --round 1 > .na-npv-1
    python3 "$IAS" record-return np --nonce "$NP" --round 1 --carriage-object-id "$OID" > /dev/null
    python3 "$IAS" query-next-action np --nonce "$NP" --round 1 > .na-npv-2
  )
  assert_eq "#546 next_action_budget_rows: a clean FILE round proceeds" \
    "action=proceed" "$(sed -n 1p "$NA_SB/.na-file" 2>/dev/null)"
  assert_eq "#546 next_action_budget_rows: a file-arm DRAFT-UNREADABLE re-dispatches on the embed arm" \
    "action=dispatch-embed-retry" "$(sed -n 1p "$NA_SB/.na-unreadable-1" 2>/dev/null)"
  # DRAFT-UNREADABLE is illegal on the embed arm (the auditor was handed the bytes inline, so
  # it cannot truthfully report the draft unreadable), and is classified as that round's first
  # no-parseable-verdict completion — which retries on the same arm. The guarantee this row
  # carries is the one the deleted #522 pin protected: whatever it routes to, it is never a
  # second file-arm re-dispatch, and the unreadable re-dispatch is spent (once per round).
  assert_eq "#546 next_action_budget_rows: an embed-arm DRAFT-UNREADABLE never re-dispatches to the file arm" \
    "action=dispatch-retry-same-arm" "$(sed -n 1p "$NA_SB/.na-unreadable-2" 2>/dev/null)"
  assert_eq "#546 next_action_budget_rows: the unreadable re-dispatch reuses the round — no second round record" \
    "1" "$(sed -n 1p "$NA_SB/.na-rounds" 2>/dev/null)"
  assert_eq "#546 next_action_budget_rows: the inline arm past both defined retries closes the round verdict-less" \
    "action=round-closed-no-verdict" "$(sed -n 1p "$NA_SB/.na-terminal" 2>/dev/null)"
  # issue #1751: with the automatic re-audit abolished, every REVISE round falls through to
  # the user-chosen-offer evaluation — there is no automatic `revise-and-reaudit` answer.
  assert_eq "#1751 next_action_budget_rows: every REVISE round falls through to the offer evaluation (no automatic re-audit)" \
    "action=revise-then-evaluate-offer
action=revise-then-evaluate-offer
action=revise-then-evaluate-offer" "$(cat "$NA_SB/.na-budget" 2>/dev/null)"
  assert_eq "#546 next_action_budget_rows: the FIRST no-parseable-verdict completion retries on the same arm" \
    "action=dispatch-retry-same-arm" "$(sed -n 1p "$NA_SB/.na-npv-1" 2>/dev/null)"
  assert_eq "#546 next_action_budget_rows: only the SECOND no-parseable-verdict completion routes to the inline degraded arm" \
    "action=dispatch-inline-degraded" "$(sed -n 1p "$NA_SB/.na-npv-2" 2>/dev/null)"
  rm -rf "$NA_SB"
fi

# user_round_cap_rows — the per-run user-chosen-round ceiling. Added by the #546 pin
# reconciliation: this carries the guarantee the deleted #522 "User-chosen rounds are capped at
# 3 per run" prose pin used to assert. The skill delegates the count outright ("the tool owns
# the per-run ceiling … never count rounds yourself", pinned in the #522 block), so the ceiling
# must actually refuse — an accepted offer past it exits NON-ZERO with a named breadcrumb, the
# mutation contract, never a silent clamp an orchestrator could read as success.
# The expected count is derived from the module's OWN constant, never transcribed by hand: a
# literal 3 here would keep passing while the tool's cap drifted underneath it.
UC_SB="$(git_sandbox '#546 user_round_cap_rows')"
if [ -d "$UC_SB" ]; then
  UC_CAP="$(python3 -c "import importlib.util,sys
spec = importlib.util.spec_from_file_location('ias', sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m._USER_ROUND_CAP)" "$IAS" 2>/dev/null)"
  (
    cd "$UC_SB" || exit 1
    git init -q .
    mkdir -p .prflow/tmp
    N="$(python3 "$IAS" init uc | sed -n '1s/nonce=//p')"
    # Accept exactly cap offers, then one more: the ceiling+1th must be refused.
    I=0
    while [ "$I" -lt "${UC_CAP:-3}" ]; do
      python3 "$IAS" record-offer uc --nonce "$N" --accepted > /dev/null 2>&1 \
        || printf 'REFUSED-EARLY at %s\n' "$I" >> .uc-early
      I=$((I + 1))
    done
    python3 "$IAS" record-offer uc --nonce "$N" --accepted > .uc-over-out 2> .uc-over-err \
      && printf 'EXITED-ZERO\n' >> .uc-over-out
    # A DECLINED offer past the ceiling is not a round and is never refused — the cap governs
    # accepted rounds only, so a decline can always be recorded (it is how the run proceeds).
    python3 "$IAS" record-offer uc --nonce "$N" > /dev/null 2>&1 || printf 'DECLINE-REFUSED\n' > .uc-decline
    python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['user_rounds_used'])" \
      .prflow/tmp/issue-audit-state-uc.json > .uc-used
  )
  assert_eq "#546 user_round_cap_rows: the module exposes a per-run user-round cap" \
    "1" "$([ -n "$UC_CAP" ] && echo 1 || echo 0)"
  assert_eq "#546 user_round_cap_rows: every offer up to the ceiling is accepted" \
    "" "$(sed -n 1p "$UC_SB/.uc-early" 2>/dev/null)"
  assert_eq "#546 user_round_cap_rows: an accepted offer past the ceiling exits non-zero, never a silent clamp" \
    "" "$(cat "$UC_SB/.uc-over-out" 2>/dev/null)"
  assert_eq "#546 user_round_cap_rows: ... and the refusal breadcrumb names the ceiling" \
    "1" "$(grep -c "capped at ${UC_CAP:-3} per run" "$UC_SB/.uc-over-err" 2>/dev/null)"
  assert_eq "#546 user_round_cap_rows: a DECLINED offer past the ceiling is never refused (the cap governs accepted rounds)" \
    "" "$(sed -n 1p "$UC_SB/.uc-decline" 2>/dev/null)"
  # The refusal is not merely a non-zero exit: the refused offer must not have been counted
  # either, or a retried offer would walk the counter past the ceiling one refusal at a time.
  assert_eq "#546 user_round_cap_rows: a refused offer is not counted — the recorded state stops AT the ceiling" \
    "${UC_CAP:-3}" "$(sed -n 1p "$UC_SB/.uc-used" 2>/dev/null)"
  rm -rf "$UC_SB"
fi

# illegal_transition_rows (#546, PR #552 review) — behavioral drives for the mutation-path
# illegal-transition guards. The python-side _TRANSITION_ROWS lockstep is metadata-only
# (it counts and content-matches the table); THESE rows prove each guard actually refuses
# at the CLI, non-zero, with its own named breadcrumb — so a refactor that drops a guard
# (e.g. the duplicate-return check, letting a second verdict overwrite a round's outcome)
# goes RED here instead of shipping. Also drives the open-round fail-closed next-action
# answer (round-open-awaiting-return, never `proceed`).
IT_SB="$(git_sandbox '#546 illegal_transition_rows')"
if [ -d "$IT_SB" ]; then
  (
    cd "$IT_SB" || exit 1
    git init -q . 2>/dev/null
    mkdir -p .prflow/tmp
    printf '# T\n\nbody\n' > draft.md
    N="$(python3 "$IAS" init it | sed -n '1s/nonce=//p')"

    # return before any dispatch
    python3 "$IAS" record-return it --nonce "$N" --round 1 --verdict FILE \
      > .it-r1-out 2> .it-r1-err; printf '%s' "$?" > .it-r1-rc

    ias_stage it "$N" draft.md
    python3 "$IAS" record-offer it --nonce "$N" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery it --nonce "$N" --round 1 --arm file \
      --draft-file draft.md > .it-disp 2>&1

    # open round: next-action answers the fail-closed awaiting token, never proceed
    python3 "$IAS" query-next-action it --nonce "$N" --round 1 > .it-open-na 2>/dev/null

    # a second round cannot open while round 1 is still open
    ias_stage it "$N" draft.md
    python3 "$IAS" record-offer it --nonce "$N" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery it --nonce "$N" --round 2 --arm file \
      --draft-file draft.md > /dev/null 2> .it-open-err; printf '%s' "$?" > .it-open-rc

    # issue #1751: a revision with zero rounds is now LEGAL — the Step 4 iterate loop on a
    # run that elected no audit round revises its draft, bumping the ordinal. --after-round
    # must name the only plausible value on a zero-round state: 0. Drive it on a fresh slug.
    N2="$(python3 "$IAS" init it2 | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-revision it2 --nonce "$N2" --after-round 0 \
      > .it-rev-out 2> .it-rev-err; printf '%s' "$?" > .it-rev-rc

    # creation-epoch with no such round / attestation with no epoch (fresh slug it2)
    python3 "$IAS" record-creation-epoch it2 --nonce "$N2" --round 1 \
      > /dev/null 2> .it-epoch-err; printf '%s' "$?" > .it-epoch-rc
    printf 'x' | python3 "$IAS" record-creation-attestation it2 --nonce "$N2" \
      > /dev/null 2> .it-att-err; printf '%s' "$?" > .it-att-rc

    # close round 1 cleanly, then: duplicate return / dispatch reopening a closed round /
    # out-of-order round number
    OID="$(git hash-object --stdin --no-filters < draft.md)"
    python3 "$IAS" record-return it --nonce "$N" --round 1 --verdict FILE \
      --carriage-object-id "$OID" > /dev/null 2>&1
    python3 "$IAS" record-return it --nonce "$N" --round 1 --verdict REVISE \
      --carriage-object-id "$OID" > /dev/null 2> .it-dup-err; printf '%s' "$?" > .it-dup-rc
    ias_stage it "$N" draft.md
    python3 "$IAS" record-dispatch --kind discovery it --nonce "$N" --round 1 --arm file \
      --draft-file draft.md > /dev/null 2> .it-reopen-err; printf '%s' "$?" > .it-reopen-rc
    ias_stage it "$N" draft.md
    python3 "$IAS" record-offer it --nonce "$N" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery it --nonce "$N" --round 0 --arm file \
      --draft-file draft.md > /dev/null 2> .it-ooo-err; printf '%s' "$?" > .it-ooo-rc

    # attestation-in-summary: with no creation epoch the summary reads attestation=none
    python3 "$IAS" query-summary it --nonce "$N" > .it-summary 2>/dev/null

    # end-to-end attestation surfacing: bind creation to round 1, attest with WRONG
    # bytes, and the summary's trailing field must read the bare token (never a dict
    # repr — the PR #552 fix-delta gate's Critical)
    python3 "$IAS" record-creation-epoch it --nonce "$N" --round 1 > /dev/null 2>&1
    printf 'entirely different bytes\n' | python3 "$IAS" record-creation-attestation it \
      --nonce "$N" > .it-att-out 2>/dev/null
    python3 "$IAS" query-summary it --nonce "$N" > .it-summary2 2>/dev/null

    # findings-count gate: a REFUSED completion (absent carriage on the file arm)
    # carrying --findings-count must NOT record the tally; a later clean retry that
    # omits its own count leaves the summary at none, never the unproven 5
    N3="$(python3 "$IAS" init it3 | sed -n '1s/nonce=//p')"
    ias_stage it3 "$N3" draft.md
    python3 "$IAS" record-offer it3 --nonce "$N3" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery it3 --nonce "$N3" --round 1 --arm file \
      --draft-file draft.md > /dev/null 2>&1
    python3 "$IAS" record-return it3 --nonce "$N3" --round 1 --verdict FILE \
      --findings-count 5 > /dev/null 2>&1   # no carriage id: refused, feeds retry accounting
    # then CLOSE the round cleanly, omitting --findings-count: pre-fix behavior would
    # surface the refused return's unproven 5 in the summary (the vacuity the fix-delta
    # re-gate caught — an open round's count never reaches the summary either way)
    OID3="$(git hash-object --stdin --no-filters < draft.md)"
    python3 "$IAS" record-return it3 --nonce "$N3" --round 1 --verdict FILE \
      --carriage-object-id "$OID3" > /dev/null 2>&1
    python3 "$IAS" query-summary it3 --nonce "$N3" > .it-fc-summary 2>/dev/null

    # draft-undigestible CLI seam: an unreadable --draft-file refuses with the distinct
    # reason on stdout AND the named stderr breadcrumb (never unaudited-revision)
    python3 "$IAS" query-eligibility it --nonce "$N" --mode approve \
      --draft-file no-such-draft.md > .it-undig-out 2> .it-undig-err; printf '%s' "$?" > .it-undig-rc
  )
  assert_eq "#546 illegal_transition_rows: a return before any dispatch refuses non-zero" \
    "1" "$(cat "$IT_SB/.it-r1-rc" 2>/dev/null)"
  assert_eq "#546 illegal_transition_rows: ... naming the verdict-precedes-dispatch guard" \
    "1" "$(grep -c 'cannot precede its dispatch' "$IT_SB/.it-r1-err" 2>/dev/null)"
  assert_eq "#546 illegal_transition_rows: an open unreturned round answers round-open-awaiting-return, never proceed" \
    "1" "$(grep -c 'round-open-awaiting-return' "$IT_SB/.it-open-na" 2>/dev/null)"
  assert_eq "#546 illegal_transition_rows: a dispatch while an earlier round is open refuses non-zero" \
    "1" "$(cat "$IT_SB/.it-open-rc" 2>/dev/null)"
  assert_eq "#546 illegal_transition_rows: ... naming the still-open guard" \
    "1" "$(grep -c 'is still open' "$IT_SB/.it-open-err" 2>/dev/null)"
  assert_eq "#1751 illegal_transition_rows: a revision with zero rounds now SUCCEEDS (the Step 4 iterate loop on a run that elected no audit round)" \
    "0" "$(cat "$IT_SB/.it-rev-rc" 2>/dev/null)"
  assert_eq "#1751 illegal_transition_rows: ... and records the first revision ordinal" \
    "1" "$(grep -c 'ordinal=1' "$IT_SB/.it-rev-out" 2>/dev/null)"
  assert_eq "#546 illegal_transition_rows: a creation epoch with no such round refuses non-zero" \
    "1" "$(cat "$IT_SB/.it-epoch-rc" 2>/dev/null)"
  assert_eq "#546 illegal_transition_rows: ... naming the no-round-to-bind guard" \
    "1" "$(grep -c 'is recorded to bind' "$IT_SB/.it-epoch-err" 2>/dev/null)"
  assert_eq "#546 illegal_transition_rows: an attestation with no epoch refuses non-zero" \
    "1" "$(cat "$IT_SB/.it-att-rc" 2>/dev/null)"
  assert_eq "#546 illegal_transition_rows: ... naming the nothing-to-attest guard" \
    "1" "$(grep -c 'nothing to attest against' "$IT_SB/.it-att-err" 2>/dev/null)"
  assert_eq "#546 illegal_transition_rows: a duplicate return refuses non-zero" \
    "1" "$(cat "$IT_SB/.it-dup-rc" 2>/dev/null)"
  assert_eq "#546 illegal_transition_rows: ... naming the duplicate-return guard" \
    "1" "$(grep -c 'duplicate return is illegal' "$IT_SB/.it-dup-err" 2>/dev/null)"
  assert_eq "#546 illegal_transition_rows: a dispatch cannot reopen a closed round" \
    "1" "$(cat "$IT_SB/.it-reopen-rc" 2>/dev/null)"
  assert_eq "#546 illegal_transition_rows: ... naming the already-closed guard" \
    "1" "$(grep -c 'cannot reopen it' "$IT_SB/.it-reopen-err" 2>/dev/null)"
  assert_eq "#546 illegal_transition_rows: an out-of-order round number refuses non-zero" \
    "1" "$(cat "$IT_SB/.it-ooo-rc" 2>/dev/null)"
  assert_eq "#546 illegal_transition_rows: ... naming the out-of-order guard" \
    "1" "$(grep -c 'is out of order' "$IT_SB/.it-ooo-err" 2>/dev/null)"
  # attestation-in-summary: the status field is part of the rendered summary line
  assert_eq "#546 illegal_transition_rows: query-summary surfaces the attestation field (none when no epoch)" \
    "1" "$(grep -v '^summary-block ' "$IT_SB/.it-summary" 2>/dev/null | grep -c 'attestation=none')"
  assert_eq "#546 illegal_transition_rows: a mismatching attestation is surfaced end-to-end as the bare token" \
    "1" "$(grep -v '^summary-block ' "$IT_SB/.it-summary2" 2>/dev/null | grep -c 'attestation=mismatch$')"
  assert_eq "#546 illegal_transition_rows: record-creation-attestation reports the mismatch on its own output too" \
    "attestation=mismatch" "$(sed -n 1p "$IT_SB/.it-att-out" 2>/dev/null)"
  assert_eq "#546 illegal_transition_rows: a refused completion's --findings-count is never recorded (clean close omitting its own count reads none, not the unproven 5)" \
    "1" "$(grep -v '^summary-block ' "$IT_SB/.it-fc-summary" 2>/dev/null | grep -c 'findings_count=none')"
  assert_eq "#546 illegal_transition_rows: an unreadable draft file refuses draft-undigestible at exit 0" \
    "eligible=no reason=draft-undigestible:0" \
    "$(sed -n 1p "$IT_SB/.it-undig-out" 2>/dev/null):$(sed -n 1p "$IT_SB/.it-undig-rc" 2>/dev/null)"
  assert_eq "#546 illegal_transition_rows: ... with the named stderr breadcrumb" \
    "1" "$(grep -c 'could not hash draft file' "$IT_SB/.it-undig-err" 2>/dev/null)"
  rm -rf "$IT_SB"
fi

# shadow_round_rows (#546, PR #552 shadow review) — producer-side CLI drives for the
# seams the blinded shadow pass showed were only covered against hand-built records: the embed-arm sentinel
# carriage round-trip with the TOOL-generated sentinels, the record-override producer vs
# the eligibility consumer, the per-query foreign-nonce fail-closed answers, query-arm's
# recorded-fact read-back (without passing --prior-unreadable), record-degraded reaching the
# summary, and the pending-cleared-at-dispatch next-action answer.
SR_SB="$(git_sandbox '#546 shadow_round_rows')"
if [ -d "$SR_SB" ]; then
  (
    cd "$SR_SB" || exit 1
    git init -q . 2>/dev/null
    mkdir -p .prflow/tmp
    printf '# T\n\nbody\n' > draft.md

    # embed-arm sentinel round-trip: dispatch on stdin, capture the tool-generated pair
    N="$(python3 "$IAS" init es | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-offer es --nonce "$N" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery es --nonce "$N" --round 1 --arm embed \
      --marker write-failed < draft.md > .sr-disp 2>&1
    SO="$(sed -nE 's/.* sentinel_open=([^ ]+).*/\1/p' .sr-disp)"
    SC="$(sed -nE 's/.* sentinel_close=([^ ]+).*/\1/p' .sr-disp)"
    # mismatched sentinel first: refused (no outcome; retry accounting)
    python3 "$IAS" record-return es --nonce "$N" --round 1 --verdict FILE \
      --carriage-sentinel-open "WRONG" --carriage-sentinel-close "$SC" > .sr-bad 2>&1
    # then the genuine pair: accepted, round closes FILE
    python3 "$IAS" record-return es --nonce "$N" --round 1 --verdict FILE \
      --carriage-sentinel-open "$SO" --carriage-sentinel-close "$SC" > .sr-good 2>&1
    python3 "$IAS" query-triggers es --nonce "$N" > .sr-trig 2>/dev/null

    # record-override producer -> eligibility consumer round-trip (file-arm epoch)
    N2="$(python3 "$IAS" init ov | sed -n '1s/nonce=//p')"
    ias_stage ov "$N2" draft.md
    python3 "$IAS" record-offer ov --nonce "$N2" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery ov --nonce "$N2" --round 1 --arm file \
      --draft-file draft.md > /dev/null 2>&1
    OID="$(git hash-object --stdin --no-filters < draft.md)"
    python3 "$IAS" record-return ov --nonce "$N2" --round 1 --verdict REVISE \
      --carriage-object-id "$OID" > /dev/null 2>&1
    python3 "$IAS" record-override ov --nonce "$N2" --kind user-decline \
      --surface t1t2-boundary --draft-file draft.md > /dev/null 2>&1
    python3 "$IAS" query-eligibility ov --nonce "$N2" --mode approve \
      --draft-file draft.md > .sr-ov-elig 2>/dev/null
    # issue #705: file-arm round -> record-revision requires --stdin-digest.
    python3 "$IAS" record-revision ov --nonce "$N2" --after-round 1 \
      --stdin-digest < draft.md > /dev/null 2>&1
    python3 "$IAS" query-eligibility ov --nonce "$N2" --mode approve \
      --draft-file draft.md > .sr-ov-stale 2>/dev/null

    # foreign-nonce fail-closed answers, one per query class
    python3 "$IAS" query-arm ov --nonce badnonce --write-landed yes \
      --draft-file draft.md > .sr-fn-arm 2>/dev/null
    python3 "$IAS" query-next-action ov --nonce badnonce --round 1 > .sr-fn-na 2>/dev/null
    python3 "$IAS" query-eligibility ov --nonce badnonce --mode approve \
      --draft-file draft.md > .sr-fn-elig 2>/dev/null

    # recorded-fact read-back: a file-arm DRAFT-UNREADABLE return, then query-arm
    # WITHOUT --prior-unreadable still routes embed/file-unreadable from state alone
    N3="$(python3 "$IAS" init rb | sed -n '1s/nonce=//p')"
    ias_stage rb "$N3" draft.md
    python3 "$IAS" record-offer rb --nonce "$N3" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery rb --nonce "$N3" --round 1 --arm file \
      --draft-file draft.md > /dev/null 2>&1
    python3 "$IAS" record-return rb --nonce "$N3" --round 1 --verdict DRAFT-UNREADABLE \
      > /dev/null 2>&1
    python3 "$IAS" query-arm rb --nonce "$N3" --write-landed yes \
      --draft-file draft.md > .sr-rb-arm 2>/dev/null
    # pending-cleared-at-dispatch: record the embed retry dispatch, then next-action
    # answers the awaiting token, never the already-spent retry action
    python3 "$IAS" record-dispatch --kind discovery rb --nonce "$N3" --round 1 --arm embed \
      --marker file-unreadable < draft.md > /dev/null 2>&1
    python3 "$IAS" query-next-action rb --nonce "$N3" --round 1 > .sr-rb-na 2>/dev/null

    # record-degraded reaches the summary
    python3 "$IAS" record-degraded rb --nonce "$N3" --round 1 \
      --reason no-subagent-tool > .sr-deg 2>&1
    python3 "$IAS" query-summary rb --nonce "$N3" > .sr-deg-summary 2>/dev/null
  )
  assert_eq "#546 shadow_round_rows: a mismatched embed sentinel refuses the completion" \
    "1" "$(grep -c 'classification=no-parseable-verdict' "$SR_SB/.sr-bad" 2>/dev/null)"
  assert_eq "#546 shadow_round_rows: the tool-generated sentinel pair round-trips to an accepted FILE close" \
    "1" "$(grep -c 'outcome=FILE' "$SR_SB/.sr-good" 2>/dev/null)"
  # issue #1694: this embed-arm round closes FILE with no per-dimension coverage recorded,
  # so the coverage ground now co-holds beside T2's steering hold (both feed the single
  # boundary offer). T1/calibration stay not-hold; the reason field still names steering.
  assert_eq "#546/#709/#1694 shadow_round_rows: ... closed with no FINDINGS trigger; T2's embed-arm steering state fires, with the coverage ground co-holding on the unrecorded coverage" \
    "1" "$(grep -c 't1=not-hold t2=hold coverage=hold calibration=not-hold reason=steering-unestablished' "$SR_SB/.sr-trig" 2>/dev/null)"
  assert_eq "#546 shadow_round_rows: a CLI-recorded override grounds eligibility (producer/consumer agree)" \
    "1" "$(grep -c 'eligible=yes ground=override' "$SR_SB/.sr-ov-elig" 2>/dev/null)"
  assert_eq "#546 shadow_round_rows: a later revision stales the CLI-recorded override" \
    "eligible=no reason=stale-override" "$(sed -n 1p "$SR_SB/.sr-ov-stale" 2>/dev/null)"
  assert_eq "#546 shadow_round_rows: query-arm fails closed on a foreign nonce" \
    "arm=embed marker=digest-unrecorded reason=foreign-nonce" "$(sed -n 1p "$SR_SB/.sr-fn-arm" 2>/dev/null)"
  assert_eq "#546 shadow_round_rows: query-next-action fails closed on a foreign nonce" \
    "action=round-closed-no-verdict reason=foreign-nonce" "$(sed -n 1p "$SR_SB/.sr-fn-na" 2>/dev/null)"
  assert_eq "#546 shadow_round_rows: query-eligibility fails closed on a foreign nonce" \
    "eligible=no reason=foreign-nonce" "$(sed -n 1p "$SR_SB/.sr-fn-elig" 2>/dev/null)"
  assert_eq "#546 shadow_round_rows: query-arm reads the recorded DRAFT-UNREADABLE fact back from state (no caller flag)" \
    "1" "$(grep -c 'arm=embed marker=file-unreadable' "$SR_SB/.sr-rb-arm" 2>/dev/null)"
  assert_eq "#546 shadow_round_rows: a recorded retry dispatch clears pending — next-action answers the awaiting token" \
    "action=round-open-awaiting-return" "$(sed -n 1p "$SR_SB/.sr-rb-na" 2>/dev/null)"
  assert_eq "#546 shadow_round_rows: record-degraded surfaces in the summary" \
    "1" "$(grep -v '^summary-block ' "$SR_SB/.sr-deg-summary" 2>/dev/null | grep -c 'degraded=yes')"
  rm -rf "$SR_SB"
fi

# iter3_hardening_rows (#546, PR #552 review round 3) — CLI drives for the round-3 guards:
# the after-round operand validation (the sole event-ordering invalidation evidence must
# never fail open on a caller-supplied value), the forward-only attestation, the premature
# cap-reached refusal, the init load-failure detail, and the unsafe-slug CLI seam.
I3_SB="$(git_sandbox '#546 iter3_hardening_rows')"
if [ -d "$I3_SB" ]; then
  (
    cd "$I3_SB" || exit 1
    git init -q . 2>/dev/null
    mkdir -p .prflow/tmp
    printf '# T\n\nbody\n' > draft.md
    OID="$(git hash-object --stdin --no-filters < draft.md)"

    N4="$(python3 "$IAS" init it4 | sed -n '1s/nonce=//p')"
    ias_stage it4 "$N4" draft.md
    python3 "$IAS" record-offer it4 --nonce "$N4" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery it4 --nonce "$N4" --round 1 --arm file \
      --draft-file draft.md > /dev/null 2>&1
    python3 "$IAS" record-return it4 --nonce "$N4" --round 1 --verdict REVISE \
      --carriage-object-id "$OID" > /dev/null 2>&1
    # issue #705: the round dispatched on the file arm, so record-revision requires
    # --stdin-digest. The out-of-range after-round guard fires BEFORE the stdin read, so the
    # 0/2 rows still fail with the same plausible-round breadcrumb; the after-round 1 row
    # reads the bytes and records, so its stdout now carries the stdin_digest field.
    python3 "$IAS" record-revision it4 --nonce "$N4" --after-round 0 \
      --stdin-digest < draft.md > /dev/null 2> .i3-ar-low; printf '%s' "$?" > .i3-ar-low-rc
    python3 "$IAS" record-revision it4 --nonce "$N4" --after-round 2 \
      --stdin-digest < draft.md > /dev/null 2> .i3-ar-high; printf '%s' "$?" > .i3-ar-high-rc
    python3 "$IAS" record-revision it4 --nonce "$N4" --after-round 1 \
      --stdin-digest < draft.md > .i3-ar-ok 2>&1

    N5="$(python3 "$IAS" init it5 | sed -n '1s/nonce=//p')"
    ias_stage it5 "$N5" draft.md
    python3 "$IAS" record-offer it5 --nonce "$N5" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery it5 --nonce "$N5" --round 1 --arm file \
      --draft-file draft.md > /dev/null 2>&1
    python3 "$IAS" record-return it5 --nonce "$N5" --round 1 --verdict FILE \
      --carriage-object-id "$OID" > /dev/null 2>&1
    python3 "$IAS" record-creation-epoch it5 --nonce "$N5" --round 1 > /dev/null 2>&1
    printf 'other bytes\n' | python3 "$IAS" record-creation-attestation it5 \
      --nonce "$N5" > /dev/null 2>&1
    printf 'body\n' | python3 "$IAS" record-creation-attestation it5 \
      --nonce "$N5" > /dev/null 2> .i3-att-again; printf '%s' "$?" > .i3-att-again-rc
    python3 "$IAS" record-creation-epoch it5 --nonce "$N5" --round 1 \
      > /dev/null 2> .i3-rebind; printf '%s' "$?" > .i3-rebind-rc

    # Premature cap-reached. The fixture completes a round and binds the draft first, so
    # the two override PRECONDITIONS (a completed round exists; a file-arm epoch's
    # override is digest-bound — #546 override_precondition_rows) are both satisfied and
    # the guard under test here is unambiguously the premature-ceiling one. The earlier
    # zero-round fixture asserted this guard correctly while it was the only one on the
    # path; once the preconditions landed they refused first, so the fixture had to gain
    # a completed round to keep reaching the guard it is written to pin.
    N6="$(python3 "$IAS" init it6 | sed -n '1s/nonce=//p')"
    ias_stage it6 "$N6" draft.md
    python3 "$IAS" record-offer it6 --nonce "$N6" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery it6 --nonce "$N6" --round 1 --arm file \
      --draft-file draft.md > /dev/null 2>&1
    python3 "$IAS" record-return it6 --nonce "$N6" --round 1 --verdict REVISE \
      --carriage-object-id "$OID" > /dev/null 2>&1
    python3 "$IAS" record-override it6 --nonce "$N6" --kind cap-reached \
      --draft-file draft.md > /dev/null 2> .i3-cap; printf '%s' "$?" > .i3-cap-rc

    printf 'not json' > .prflow/tmp/issue-audit-state-it7.json
    python3 "$IAS" init it7 --nonce deadbeef > /dev/null 2> .i3-corrupt; printf '%s' "$?" > .i3-corrupt-rc

    python3 "$IAS" init 'a/b' > /dev/null 2> .i3-slug; printf '%s' "$?" > .i3-slug-rc
  )
  assert_eq "#546 iter3_hardening_rows: an after-round below the last completed round refuses (the fail-open shape)" \
    "1" "$(grep -c 'does not name a plausible round' "$I3_SB/.i3-ar-low" 2>/dev/null)"
  assert_eq "#546 iter3_hardening_rows: ... non-zero" "1" "$(cat "$I3_SB/.i3-ar-low-rc" 2>/dev/null)"
  assert_eq "#546 iter3_hardening_rows: an after-round above the last recorded round refuses" \
    "1" "$(cat "$I3_SB/.i3-ar-high-rc" 2>/dev/null)"
  assert_eq "#546 iter3_hardening_rows: the truthful after-round is accepted" \
    "1" "$(grep -cE '^ordinal=1 stdin_digest=[0-9a-f]+$' "$I3_SB/.i3-ar-ok" 2>/dev/null)"
  assert_eq "#546 iter3_hardening_rows: a second attestation refuses (forward-only tamper evidence)" \
    "1" "$(grep -c 'cannot be overwritten' "$I3_SB/.i3-att-again" 2>/dev/null)"
  assert_eq "#546 iter3_hardening_rows: an epoch re-bind after attestation refuses" \
    "1" "$(grep -c 'silently discard that tamper evidence' "$I3_SB/.i3-rebind" 2>/dev/null)"
  assert_eq "#546 iter3_hardening_rows: a premature cap-reached override refuses" \
    "1" "$(grep -c 'before the ceiling' "$I3_SB/.i3-cap" 2>/dev/null)"
  assert_eq "#546 iter3_hardening_rows: init --nonce over a corrupt state file names the load failure" \
    "1" "$(grep -c 'the load failed' "$I3_SB/.i3-corrupt" 2>/dev/null)"
  assert_eq "#546 iter3_hardening_rows: an unsafe slug refuses at the CLI seam with the named breadcrumb" \
    "1" "$(grep -c 'not a safe path segment' "$I3_SB/.i3-slug" 2>/dev/null)"
  rm -rf "$I3_SB"
fi

# iter4_variance_rows (#546, PR #552 review round 4) — two seams the round-4 variance
# pass showed untested at the CLI layer: the record-return negative findings-count
# refusal (previously covered only at the _validate layer) and the previously-untested
# _repo_root anchor-fallback stderr breadcrumb.
I4_SB="$(git_sandbox '#546 iter4_variance_rows')"
if [ -d "$I4_SB" ]; then
  (
    cd "$I4_SB" || exit 1
    git init -q . 2>/dev/null
    mkdir -p .prflow/tmp
    printf '# T\n\nbody\n' > draft.md
    OID="$(git hash-object --stdin --no-filters < draft.md)"
    N="$(python3 "$IAS" init i4 | sed -n '1s/nonce=//p')"
    ias_stage i4 "$N" draft.md
    python3 "$IAS" record-offer i4 --nonce "$N" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery i4 --nonce "$N" --round 1 --arm file \
      --draft-file draft.md > /dev/null 2>&1
    python3 "$IAS" record-return i4 --nonce "$N" --round 1 --verdict FILE \
      --findings-count -1 --carriage-object-id "$OID" > /dev/null 2> .i4-neg; printf '%s' "$?" > .i4-neg-rc

    # anchor-fallback breadcrumb: git unresolvable on PATH (the subprocess raises
    # OSError) -> init still works (cwd anchor) but breadcrumbs the selection change
    mkdir -p nogit-bin nogit-cwd
    ln -sf "$(command -v python3)" nogit-bin/python3
    ( cd nogit-cwd && PATH="$I4_SB/nogit-bin" python3 "$IAS" init fb > ../.i4-fb-out 2> ../.i4-fb-err )
    ls nogit-cwd/.prflow/tmp > .i4-fb-files 2>/dev/null
  )
  assert_eq "#546 iter4_variance_rows: a negative --findings-count refuses at the mutation seam" \
    "1" "$(cat "$I4_SB/.i4-neg-rc" 2>/dev/null)"
  assert_eq "#546 iter4_variance_rows: ... with the named breadcrumb" \
    "1" "$(grep -c 'is negative' "$I4_SB/.i4-neg" 2>/dev/null)"
  assert_eq "#546 iter4_variance_rows: with git unresolvable the anchor falls back to cwd WITH the selection breadcrumb" \
    "1" "$(grep -c 'anchoring state to the current directory' "$I4_SB/.i4-fb-err" 2>/dev/null)"
  assert_eq "#546 iter4_variance_rows: ... and the state file lands under the cwd anchor" \
    "issue-audit-state-fb.json" "$(cat "$I4_SB/.i4-fb-files" 2>/dev/null)"
  rm -rf "$I4_SB"
fi

# iter5_hardening_rows (#546, PR #552 review round 5) — the round-5 guards: the round-
# funding gate, the unrequested-re-dispatch refusal, the embed marker requirement, the
# no-digest-supplied eligibility reason, emit-body's empty-body refusal, the attestation
# trailing-newline tolerance, and the cap-reached accept side.
I5_SB="$(git_sandbox '#546 iter5_hardening_rows')"
if [ -d "$I5_SB" ]; then
  (
    cd "$I5_SB" || exit 1
    git init -q . 2>/dev/null
    mkdir -p .prflow/tmp
    printf '# T\n\nbody\n' > draft.md
    OID="$(git hash-object --stdin --no-filters < draft.md)"
    N="$(python3 "$IAS" init i5 | sed -n '1s/nonce=//p')"
    ias_stage i5 "$N" draft.md
    python3 "$IAS" record-offer i5 --nonce "$N" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery i5 --nonce "$N" --round 1 --arm file \
      --draft-file draft.md > /dev/null 2>&1
    # unrequested re-dispatch on the open round refuses
    ias_stage i5 "$N" draft.md
    python3 "$IAS" record-dispatch --kind discovery i5 --nonce "$N" --round 1 --arm file \
      --draft-file draft.md > /dev/null 2> .i5-redisp; printf '%s' "$?" > .i5-redisp-rc
    python3 "$IAS" record-return i5 --nonce "$N" --round 1 --verdict REVISE \
      --carriage-object-id "$OID" > /dev/null 2>&1
    # issue #1751: round 2 is user-elected too (the automatic re-audit is abolished), so it is
    # funded by the accepted offer above; round 3 with NO further offer is unfunded and refuses.
    ias_stage i5 "$N" draft.md
    python3 "$IAS" record-offer i5 --nonce "$N" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery i5 --nonce "$N" --round 2 --arm file \
      --draft-file draft.md > /dev/null 2>&1
    python3 "$IAS" record-return i5 --nonce "$N" --round 2 --verdict REVISE \
      --carriage-object-id "$OID" > /dev/null 2>&1
    ias_stage i5 "$N" draft.md
    python3 "$IAS" record-dispatch --kind discovery i5 --nonce "$N" --round 3 --arm file \
      --draft-file draft.md > /dev/null 2> .i5-unfunded; printf '%s' "$?" > .i5-unfunded-rc
    # ... and an accepted offer funds it
    python3 "$IAS" record-offer i5 --nonce "$N" --accepted > /dev/null 2>&1
    ias_stage i5 "$N" draft.md
    python3 "$IAS" record-dispatch --kind discovery i5 --nonce "$N" --round 3 --arm file \
      --draft-file draft.md > .i5-funded 2>&1; printf '%s' "$?" > .i5-funded-rc

    # embed dispatch without --marker refuses
    N2="$(python3 "$IAS" init i5b | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-offer i5b --nonce "$N2" --accepted > /dev/null
    printf 'x\n' | python3 "$IAS" record-dispatch --kind discovery i5b --nonce "$N2" --round 1 \
      --arm embed > /dev/null 2> .i5-nomark; printf '%s' "$?" > .i5-nomark-rc

    # no-digest-supplied: approve query with no --draft-file over a file-arm clean epoch
    N3="$(python3 "$IAS" init i5c | sed -n '1s/nonce=//p')"
    IOID_I5C="$(ias_instructions "$I5_SB" i5c draft.md)"
    ias_stage i5c "$N3" draft.md
    python3 "$IAS" record-offer i5c --nonce "$N3" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery i5c --nonce "$N3" --round 1 --arm file \
      --draft-file draft.md --instructions-file "$I5_SB/instr-i5c.md" \
      --instructions-draft-path "$I5_SB/draft.md" > /dev/null 2>&1
    python3 "$IAS" record-return i5c --nonce "$N3" --round 1 --verdict FILE \
      --carriage-object-id "$OID" --instructions-object-id "$IOID_I5C" \
      --extra-dispatch-content no > /dev/null 2>&1
    python3 "$IAS" query-eligibility i5c --nonce "$N3" --mode approve > .i5-nodig 2>/dev/null

    # emit-body on a title-only draft fails loudly (never exit-0-empty)
    printf '# Only a title\n' > title-only.md
    N4="$(python3 "$IAS" init i5d | sed -n '1s/nonce=//p')"
    IOID_I5D="$(ias_instructions "$I5_SB" i5d title-only.md)"
    ias_stage i5d "$N4" title-only.md
    python3 "$IAS" record-offer i5d --nonce "$N4" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery i5d --nonce "$N4" --round 1 --arm file \
      --draft-file title-only.md --instructions-file "$I5_SB/instr-i5d.md" \
      --instructions-draft-path "$I5_SB/title-only.md" > /dev/null 2>&1
    TOID="$(git hash-object --stdin --no-filters < title-only.md)"
    python3 "$IAS" record-return i5d --nonce "$N4" --round 1 --verdict FILE \
      --carriage-object-id "$TOID" --instructions-object-id "$IOID_I5D" \
      --extra-dispatch-content no > /dev/null 2>&1
    python3 "$IAS" emit-body i5d --nonce "$N4" --draft-file title-only.md \
      > .i5-empty-out 2> .i5-empty-err; printf '%s' "$?" > .i5-empty-rc

    # attestation trailing-newline tolerance: body + one extra newline still matches,
    # with the disclosed stderr note; two extra newlines stay a mismatch
    python3 "$IAS" record-creation-epoch i5c --nonce "$N3" --round 1 > /dev/null 2>&1
    { python3 "$IAS" emit-body i5c --nonce "$N3" --draft-file draft.md; printf '\n'; } \
      | python3 "$IAS" record-creation-attestation i5c --nonce "$N3" > .i5-att-nl 2> .i5-att-nl-err

    # cap-reached ACCEPT side: at the ceiling the cap record is legal
    N5="$(python3 "$IAS" init i5e | sed -n '1s/nonce=//p')"
    ias_stage i5e "$N5" draft.md
    python3 "$IAS" record-offer i5e --nonce "$N5" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery i5e --nonce "$N5" --round 1 --arm file \
      --draft-file draft.md > /dev/null 2>&1
    python3 "$IAS" record-return i5e --nonce "$N5" --round 1 --verdict REVISE \
      --carriage-object-id "$OID" > /dev/null 2>&1
    for _i in 1 2 3; do python3 "$IAS" record-offer i5e --nonce "$N5" --accepted > /dev/null 2>&1; done
    # --draft-file is required here because this epoch is a file-arm round: SKILL.md's
    # boundary-offer rule says EVERY record-override call on a file-arm epoch binds the
    # draft, and the tool now enforces it (#546 override_precondition_rows) rather than
    # trusting the prose. An unbound override is never compared against the draft, so it
    # would permit any bytes.
    python3 "$IAS" record-override i5e --nonce "$N5" --kind cap-reached \
      --draft-file draft.md > .i5-cap-ok 2>&1; printf '%s' "$?" > .i5-cap-ok-rc

    # bounded-tolerance negative control: TWO extra newlines stay a mismatch. Fresh slug
    # (the i5c epoch above is already attested match — forward-only).
    N6="$(python3 "$IAS" init i5f | sed -n '1s/nonce=//p')"
    IOID_I5F="$(ias_instructions "$I5_SB" i5f draft.md)"
    ias_stage i5f "$N6" draft.md
    python3 "$IAS" record-offer i5f --nonce "$N6" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery i5f --nonce "$N6" --round 1 --arm file \
      --draft-file draft.md --instructions-file "$I5_SB/instr-i5f.md" \
      --instructions-draft-path "$I5_SB/draft.md" > /dev/null 2>&1
    python3 "$IAS" record-return i5f --nonce "$N6" --round 1 --verdict FILE \
      --carriage-object-id "$OID" --instructions-object-id "$IOID_I5F" \
      --extra-dispatch-content no > /dev/null 2>&1
    python3 "$IAS" record-creation-epoch i5f --nonce "$N6" --round 1 > /dev/null 2>&1
    { python3 "$IAS" emit-body i5f --nonce "$N6" --draft-file draft.md; printf '\n\n'; } \
      | python3 "$IAS" record-creation-attestation i5f --nonce "$N6" > .i5-att-nl2 2> .i5-att-nl2-err

    # foreign-nonce trigger naming
    python3 "$IAS" query-triggers i5f --nonce badnonce > .i5-fn-trig 2>/dev/null

    # attestation-unavailable is re-attestable: record unavailable, then a corrective
    # retry attests the genuine bytes to match
    N7="$(python3 "$IAS" init i5g | sed -n '1s/nonce=//p')"
    IOID_I5G="$(ias_instructions "$I5_SB" i5g draft.md)"
    ias_stage i5g "$N7" draft.md
    python3 "$IAS" record-offer i5g --nonce "$N7" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery i5g --nonce "$N7" --round 1 --arm file \
      --draft-file draft.md --instructions-file "$I5_SB/instr-i5g.md" \
      --instructions-draft-path "$I5_SB/draft.md" > /dev/null 2>&1
    python3 "$IAS" record-return i5g --nonce "$N7" --round 1 --verdict FILE \
      --carriage-object-id "$OID" --instructions-object-id "$IOID_I5G" \
      --extra-dispatch-content no > /dev/null 2>&1
    python3 "$IAS" record-creation-epoch i5g --nonce "$N7" --round 1 > /dev/null 2>&1
    python3 "$IAS" record-creation-attestation i5g --nonce "$N7" --attestation-unavailable > /dev/null 2>&1
    python3 "$IAS" emit-body i5g --nonce "$N7" --draft-file draft.md \
      | python3 "$IAS" record-creation-attestation i5g --nonce "$N7" > .i5-uv-reattest 2>&1

    # creation cannot bind an open round
    N8="$(python3 "$IAS" init i5h | sed -n '1s/nonce=//p')"
    ias_stage i5h "$N8" draft.md
    python3 "$IAS" record-offer i5h --nonce "$N8" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery i5h --nonce "$N8" --round 1 --arm file \
      --draft-file draft.md > /dev/null 2>&1
    python3 "$IAS" record-creation-epoch i5h --nonce "$N8" --round 1 \
      > /dev/null 2> .i5-open-epoch; printf '%s' "$?" > .i5-open-epoch-rc
  )
  assert_eq "#546 iter5_hardening_rows: an unrequested re-dispatch on an open round refuses" \
    "1" "$(grep -c 'a re-dispatch was not requested' "$I5_SB/.i5-redisp" 2>/dev/null)"
  assert_eq "#546 iter5_hardening_rows: an unfunded round past the automatic budget refuses" \
    "1" "$(grep -c 'is not funded' "$I5_SB/.i5-unfunded" 2>/dev/null)"
  assert_eq "#546 iter5_hardening_rows: an accepted offer funds the same round (accept side)" \
    "0" "$(sed -n 1p "$I5_SB/.i5-funded-rc" 2>/dev/null)"
  assert_eq "#546 iter5_hardening_rows: an embed dispatch without --marker refuses" \
    "1" "$(grep -c 'requires --marker' "$I5_SB/.i5-nomark" 2>/dev/null)"
  assert_eq "#546 iter5_hardening_rows: approve with no draft file over a file-arm clean epoch names no-digest-supplied" \
    "eligible=no reason=no-digest-supplied" "$(sed -n 1p "$I5_SB/.i5-nodig" 2>/dev/null)"
  assert_eq "#546 iter5_hardening_rows: emit-body on a title-only draft fails loudly, never exit-0-empty" \
    "1:1" "$(sed -n 1p "$I5_SB/.i5-empty-rc" 2>/dev/null):$(grep -c 'empty body below its title' "$I5_SB/.i5-empty-err" 2>/dev/null)"
  assert_eq "#546 iter5_hardening_rows: one fetch-framing trailing newline still attests match (disclosed)" \
    "attestation=match:1" "$(sed -n 1p "$I5_SB/.i5-att-nl" 2>/dev/null):$(grep -c 'matched modulo' "$I5_SB/.i5-att-nl-err" 2>/dev/null)"
  assert_eq "#546 iter5_hardening_rows: TWO extra newlines stay a mismatch (the tolerance is bounded to exactly one)" \
    "attestation=mismatch:0" "$(sed -n 1p "$I5_SB/.i5-att-nl2" 2>/dev/null):$(grep -c 'matched modulo' "$I5_SB/.i5-att-nl2-err" 2>/dev/null)"
  assert_eq "#546 iter5_hardening_rows: query-triggers names a foreign nonce instead of misattributing unestablished" \
    "t1=not-hold t2=hold coverage=not-hold calibration=not-hold reason=foreign-nonce" "$(sed -n 1p "$I5_SB/.i5-fn-trig" 2>/dev/null)"
  assert_eq "#546 iter5_hardening_rows: an attestation-unavailable record may be re-attested (it is the honest unknown, not tamper evidence)" \
    "attestation=match" "$(sed -n 1p "$I5_SB/.i5-uv-reattest" 2>/dev/null)"
  assert_eq "#546 iter5_hardening_rows: creation cannot bind an OPEN round" \
    "1" "$(grep -c 'still open; creation can only bind' "$I5_SB/.i5-open-epoch" 2>/dev/null)"
  assert_eq "#546 iter5_hardening_rows: cap-reached at the ceiling is accepted (accept side)" \
    "0" "$(sed -n 1p "$I5_SB/.i5-cap-ok-rc" 2>/dev/null)"
  rm -rf "$I5_SB"
fi

# conv_shadow_rows (#546, PR #552 convergence shadow) — the shadow-pass guards: the
# retry-arm binding, dense round numbering, the honest empty-fetch compare, the
# unpersistable-state mutation breadcrumb, and query-nonce's happy-path recovery.
CS_SB="$(git_sandbox '#546 conv_shadow_rows')"
if [ -d "$CS_SB" ]; then
  (
    cd "$CS_SB" || exit 1
    git init -q . 2>/dev/null
    mkdir -p .prflow/tmp
    printf '# T\n\nbody\n' > draft.md
    OID="$(git hash-object --stdin --no-filters < draft.md)"

    # retry-arm binding: a pending embed retry refuses a file-arm dispatch
    N="$(python3 "$IAS" init cs | sed -n '1s/nonce=//p')"
    ias_stage cs "$N" draft.md
    python3 "$IAS" record-offer cs --nonce "$N" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery cs --nonce "$N" --round 1 --arm file \
      --draft-file draft.md > /dev/null 2>&1
    python3 "$IAS" record-return cs --nonce "$N" --round 1 --verdict DRAFT-UNREADABLE \
      > /dev/null 2>&1
    ias_stage cs "$N" draft.md
    python3 "$IAS" record-dispatch --kind discovery cs --nonce "$N" --round 1 --arm file \
      --draft-file draft.md > /dev/null 2> .cs-armbind; printf '%s' "$?" > .cs-armbind-rc

    # dense round numbering: after round 1 closes, round 7 refuses
    N2="$(python3 "$IAS" init cs2 | sed -n '1s/nonce=//p')"
    ias_stage cs2 "$N2" draft.md
    python3 "$IAS" record-offer cs2 --nonce "$N2" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery cs2 --nonce "$N2" --round 1 --arm file \
      --draft-file draft.md > /dev/null 2>&1
    python3 "$IAS" record-return cs2 --nonce "$N2" --round 1 --verdict REVISE \
      --carriage-object-id "$OID" > /dev/null 2>&1
    ias_stage cs2 "$N2" draft.md
    python3 "$IAS" record-offer cs2 --nonce "$N2" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery cs2 --nonce "$N2" --round 7 --arm file \
      --draft-file draft.md > /dev/null 2> .cs-sparse; printf '%s' "$?" > .cs-sparse-rc

    # honest empty-fetch compare: zero fetched bytes attest MISMATCH (the recorded
    # digest is non-empty), never attestation-unavailable
    N3="$(python3 "$IAS" init cs3 | sed -n '1s/nonce=//p')"
    ias_stage cs3 "$N3" draft.md
    python3 "$IAS" record-offer cs3 --nonce "$N3" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery cs3 --nonce "$N3" --round 1 --arm file \
      --draft-file draft.md > /dev/null 2>&1
    python3 "$IAS" record-return cs3 --nonce "$N3" --round 1 --verdict FILE \
      --carriage-object-id "$OID" > /dev/null 2>&1
    python3 "$IAS" record-creation-epoch cs3 --nonce "$N3" --round 1 > /dev/null 2>&1
    printf '' | python3 "$IAS" record-creation-attestation cs3 --nonce "$N3" > .cs-empty 2>&1

    # unpersistable state: a read-only .prflow/tmp makes the mutation exit non-zero
    # with the named breadcrumb, and a QUERY still answers (read-only contract)
    chmod 555 .prflow/tmp
    # issue #705: the round dispatched on the file arm, so record-revision requires
    # --stdin-digest. The arm guard and the stdin read both precede save_state, so the
    # unpersistable failure still surfaces with its could-not-persist breadcrumb.
    printf '# T\n\nrevised\n' | python3 "$IAS" record-revision cs3 --nonce "$N3" \
      --after-round 1 --stdin-digest > /dev/null 2> .cs-nopersist; printf '%s' "$?" > .cs-nopersist-rc
    python3 "$IAS" query-triggers cs3 --nonce "$N3" > .cs-nopersist-query 2>/dev/null
    chmod 755 .prflow/tmp

    # query-nonce happy path: the minted nonce round-trips exactly
    printf 'nonce=%s\n' "$N3" > .cs-nonce-expected
    python3 "$IAS" query-nonce cs3 > .cs-nonce-got 2>/dev/null
  )
  assert_eq "#546 conv_shadow_rows: a pending embed retry refuses a file-arm dispatch (arm binding)" \
    "1" "$(grep -c 'does not permit a dispatch on the file arm' "$CS_SB/.cs-armbind" 2>/dev/null)"
  assert_eq "#546 conv_shadow_rows: a sparse round number refuses (dense numbering)" \
    "1" "$(grep -c 'the next round is 2' "$CS_SB/.cs-sparse" 2>/dev/null)"
  assert_eq "#546 conv_shadow_rows: zero fetched bytes attest mismatch, never laundered into unavailable" \
    "attestation=mismatch" "$(sed -n 1p "$CS_SB/.cs-empty" 2>/dev/null)"
  assert_eq "#546 conv_shadow_rows: an unpersistable state exits non-zero with the named breadcrumb" \
    "1:1" "$(sed -n 1p "$CS_SB/.cs-nopersist-rc" 2>/dev/null):$(grep -c 'could not persist state' "$CS_SB/.cs-nopersist" 2>/dev/null)"
  assert_eq "#546 conv_shadow_rows: ... while a query still answers after the persistence failure" \
    "1" "$(grep -c 't1=' "$CS_SB/.cs-nopersist-query" 2>/dev/null)"
  assert_eq "#546 conv_shadow_rows: query-nonce round-trips the minted nonce exactly" \
    "$(sed -n 1p "$CS_SB/.cs-nonce-expected" 2>/dev/null)" "$(sed -n 1p "$CS_SB/.cs-nonce-got" 2>/dev/null)"
  rm -rf "$CS_SB"
fi

# override_precondition_rows (#546, PR #552 early shadow) — the override ground's two
# missing preconditions, each of which let `emit-body` emit a NEVER-AUDITED body at
# exit 0 (the exact outcome the module exists to prevent), plus the token-binding and
# re-init tamper-evidence guards the same pass surfaced.
#
# Each row drives the CLI end-to-end: the exploit is the test. Removing a guard in
# scripts/issue-audit-state.py turns its row RED, because the row asserts the refusal —
# and the emit rows additionally assert stdout is EMPTY, which is the refusal signature
# a caller that ignores the exit code depends on.
OP_SB="$(git_sandbox '#546 override_precondition_rows')"
if [ -d "$OP_SB" ]; then
  (
    cd "$OP_SB" || exit 1
    git init -q . 2>/dev/null
    mkdir -p .prflow/tmp
    printf '# T\n\nAUDITED body\n' > draft.md
    OID="$(git hash-object --stdin --no-filters < draft.md)"

    # (1) zero completed rounds: issue #1751 makes a user-decline the user's election to file
    # unaudited, so the WRITE now SUCCEEDS (this is the feature — a run that elected no audit
    # round still files). The read boundary's remaining guarantee — an UNBOUND decline must
    # not clear eligibility when canonical bytes are supplied — is (1b) below. A cap-reached
    # at zero rounds stays incoherent and is (1c).
    N="$(python3 "$IAS" init op1 | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-override op1 --nonce "$N" --kind user-decline \
      --surface t1t2-boundary > /dev/null 2> .op-noround; printf '%s' "$?" > .op-noround-rc
    # (1c) a cap-reached override at zero rounds is incoherent — a ceiling cannot be reached
    # before any round ran — so it still fails closed with the no-round-has-completed message.
    python3 "$IAS" record-override op1 --nonce "$N" --kind cap-reached \
      > /dev/null 2> .op-cap-noround; printf '%s' "$?" > .op-cap-noround-rc

    # (1b) read boundary: hand-plant the override the write guard refuses, proving a
    # corrupt/older state file cannot smuggle it past the gate either.
    python3 - <<'PY' > /dev/null 2>&1
import json, pathlib
p = pathlib.Path('.prflow/tmp/issue-audit-state-op1.json')
d = json.loads(p.read_text())
d['overrides'].append({'kind': 'user-decline', 'surface': 't1t2-boundary',
                       'recorded_at_ordinal': 0, 'draft_digest': None})
p.write_text(json.dumps(d))
PY
    python3 "$IAS" query-eligibility op1 --nonce "$N" --mode approve \
      --draft-file draft.md > .op-planted-elig 2>&1
    python3 "$IAS" emit-body op1 --nonce "$N" --draft-file draft.md \
      > .op-planted-emit 2> /dev/null; printf '%s' "$?" > .op-planted-emit-rc

    # (2) file-arm epoch + override with NO --draft-file: never compared against any
    # bytes, so it would permit any draft. Write boundary must refuse.
    N2="$(python3 "$IAS" init op2 | sed -n '1s/nonce=//p')"
    ias_stage op2 "$N2" draft.md
    python3 "$IAS" record-offer op2 --nonce "$N2" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery op2 --nonce "$N2" --round 1 --arm file \
      --draft-file draft.md > /dev/null 2>&1
    python3 "$IAS" record-return op2 --nonce "$N2" --round 1 --verdict REVISE \
      --findings-count 1 --carriage-object-id "$OID" > /dev/null 2>&1
    python3 "$IAS" record-override op2 --nonce "$N2" --kind user-decline \
      --surface t1t2-boundary > /dev/null 2> .op-unbound; printf '%s' "$?" > .op-unbound-rc
    # the bound form is still accepted (the guard refuses the unbound shape, not the kind)
    python3 "$IAS" record-override op2 --nonce "$N2" --kind user-decline \
      --surface t1t2-boundary --draft-file draft.md > /dev/null 2>&1
    printf '%s' "$?" > .op-bound-rc
    # tampered bytes under a bound override refuse, and emit-body stays silent.
    # The two channels are captured SEPARATELY (issue #611): this refusal now carries a
    # stale-override recovery breadcrumb on stderr, and folding it into stdout with
    # `2>&1` would both break the stdout-token assertion and, worse, leave the token
    # contract and the breadcrumb indistinguishable — a later regression that moved
    # text between the channels could not be caught. Splitting them asserts the closed
    # one-token stdout vocabulary and the additive stderr remedy independently.
    printf '# T\n\nNEVER AUDITED BYTES\n' > tampered.md
    python3 "$IAS" query-eligibility op2 --nonce "$N2" --mode approve \
      --draft-file tampered.md > .op-tampered-elig 2> .op-tampered-elig-err
    python3 "$IAS" emit-body op2 --nonce "$N2" --draft-file tampered.md \
      > .op-tampered-emit 2> .op-tampered-emit-err; printf '%s' "$?" > .op-tampered-emit-rc

    # (2b) READ boundary for the digest-unbound precondition — the symmetric partner of
    # (1b). The rows above drive only the WRITE boundary, and the tampered rows pin the
    # pre-existing `want != current_digest` branch, NOT the `want is None` one. Without
    # this row the read-boundary unbound check could be reverted with the whole block
    # staying green while emit-body emitted arbitrary bytes from a pre-delta or
    # hand-edited state file. Plant the unbound override the write guard refuses.
    N2B="$(python3 "$IAS" init op2b | sed -n '1s/nonce=//p')"
    ias_stage op2b "$N2B" draft.md
    python3 "$IAS" record-offer op2b --nonce "$N2B" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery op2b --nonce "$N2B" --round 1 --arm file \
      --draft-file draft.md > /dev/null 2>&1
    python3 "$IAS" record-return op2b --nonce "$N2B" --round 1 --verdict REVISE \
      --findings-count 1 --carriage-object-id "$OID" > /dev/null 2>&1
    python3 - <<'PY' > /dev/null 2>&1
import json, pathlib
p = pathlib.Path('.prflow/tmp/issue-audit-state-op2b.json')
d = json.loads(p.read_text())
d['overrides'].append({'kind': 'user-decline', 'surface': 't1t2-boundary',
                       'recorded_at_ordinal': 0, 'draft_digest': None})
p.write_text(json.dumps(d))
PY
    python3 "$IAS" query-eligibility op2b --nonce "$N2B" --mode approve \
      --draft-file tampered.md > .op-unbound-read-elig 2>&1
    python3 "$IAS" emit-body op2b --nonce "$N2B" --draft-file tampered.md \
      > .op-unbound-read-emit 2> /dev/null; printf '%s' "$?" > .op-unbound-read-emit-rc

    # (3) token binding: two byte-distinct drafts, each with its own digest-bound
    # override at the SAME revision ordinal, must mint DIFFERENT tokens. Keying on the
    # ordinal alone collapsed them onto one token — the replay the token exposes.
    #
    # ONE slug, ONE nonce, deliberately: issue_token hashes '{nonce}:{ground}:{key}', so
    # two slugs would mint two random nonces and the tokens would differ REGARDLESS of
    # the key — the assert would pass with the key fix reverted, i.e. it would pin
    # nothing. Same nonce + same ordinal isolates the key as the only free operand.
    N3="$(python3 "$IAS" init op3 | sed -n '1s/nonce=//p')"
    printf '# T\n\nbody A\n' > d-a.md
    printf '# T\n\nbody B\n' > d-b.md
    OA="$(git hash-object --stdin --no-filters < d-a.md)"
    ias_stage op3 "$N3" d-a.md
    python3 "$IAS" record-offer op3 --nonce "$N3" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery op3 --nonce "$N3" --round 1 --arm file \
      --draft-file d-a.md > /dev/null 2>&1
    python3 "$IAS" record-return op3 --nonce "$N3" --round 1 --verdict REVISE \
      --findings-count 1 --carriage-object-id "$OA" > /dev/null 2>&1
    # two digest-bound overrides at the same ordinal (no revision between them)
    python3 "$IAS" record-override op3 --nonce "$N3" --kind user-decline \
      --surface t1t2-boundary --draft-file d-a.md > /dev/null 2>&1
    python3 "$IAS" record-override op3 --nonce "$N3" --kind user-decline \
      --surface t1t2-boundary --draft-file d-b.md > /dev/null 2>&1
    python3 "$IAS" query-eligibility op3 --nonce "$N3" --mode approve \
      --draft-file d-a.md | sed -n -E '1s/.*(token=[^ ]*).*/\1/p' > .op-tok-op3a
    python3 "$IAS" query-eligibility op3 --nonce "$N3" --mode approve \
      --draft-file d-b.md | sed -n -E '1s/.*(token=[^ ]*).*/\1/p' > .op-tok-op3b

    # (4) re-init must not discard forward-only creation tamper evidence.
    N4="$(python3 "$IAS" init op4 | sed -n '1s/nonce=//p')"
    ias_stage op4 "$N4" draft.md
    python3 "$IAS" record-offer op4 --nonce "$N4" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery op4 --nonce "$N4" --round 1 --arm file \
      --draft-file draft.md > /dev/null 2>&1
    python3 "$IAS" record-return op4 --nonce "$N4" --round 1 --verdict FILE \
      --findings-count 0 --carriage-object-id "$OID" > /dev/null 2>&1
    python3 "$IAS" record-creation-epoch op4 --nonce "$N4" --round 1 > /dev/null 2>&1
    printf 'AUDITED body\n' | python3 "$IAS" record-creation-attestation op4 \
      --nonce "$N4" > .op-attest 2>&1
    python3 "$IAS" init op4 --nonce "$N4" --force > /dev/null 2> .op-reinit
    printf '%s' "$?" > .op-reinit-rc
  )
  assert_eq "#1751 override_precondition_rows: a zero-round user-decline WRITE now succeeds (the user's election to file unaudited)" \
    "0" "$(sed -n 1p "$OP_SB/.op-noround-rc" 2>/dev/null)"
  assert_eq "#1751 override_precondition_rows: a cap-reached override at zero rounds still refuses (no round has completed)" \
    "1:1" "$(sed -n 1p "$OP_SB/.op-cap-noround-rc" 2>/dev/null):$(grep -c 'no round has completed' "$OP_SB/.op-cap-noround" 2>/dev/null)"
  assert_eq "#1751 override_precondition_rows: a hand-planted UNBOUND zero-round decline is not honoured when canonical bytes are supplied (adversarial)" \
    "eligible=no reason=no-verdict-round" "$(sed -n 1p "$OP_SB/.op-planted-elig" 2>/dev/null)"
  assert_eq "#546 override_precondition_rows: ... and emit-body refuses it with the empty-stdout signature" \
    "1:" "$(cat "$OP_SB/.op-planted-emit-rc" 2>/dev/null):$(cat "$OP_SB/.op-planted-emit" 2>/dev/null)"
  assert_eq "#546 override_precondition_rows: a digest-unbound override on a file-arm epoch refuses (it would permit any bytes)" \
    "1:1" "$(sed -n 1p "$OP_SB/.op-unbound-rc" 2>/dev/null):$(grep -c 'must bind the draft it permits' "$OP_SB/.op-unbound" 2>/dev/null)"
  assert_eq "#546 override_precondition_rows: ... while the digest-bound form is still accepted (positive control)" \
    "0" "$(sed -n 1p "$OP_SB/.op-bound-rc" 2>/dev/null)"
  assert_eq "#546 override_precondition_rows: tampered bytes under a bound override refuse" \
    "eligible=no reason=stale-override" "$(sed -n 1p "$OP_SB/.op-tampered-elig" 2>/dev/null)"
  # issue #611, CLI level: the arm-selected recovery breadcrumb accompanies this refusal
  # on stderr. These bytes are digest-staled under a CURRENT-ordinal override, which is
  # arm a — the only arm that leads with `record-revision`. Asserting the arm here (not
  # merely "some stderr text") is what makes the CLI case catch a mis-keyed selector
  # that still emits a plausible-looking remedy.
  assert_eq "#611 override_precondition_rows: the tampered-bytes refusal carries the arm-a recovery breadcrumb on stderr" \
    "yes" "$(grep -q 'record-revision' "$OP_SB/.op-tampered-elig-err" 2>/dev/null && grep -q 'fresh explicit user election' "$OP_SB/.op-tampered-elig-err" 2>/dev/null && echo yes || echo no)"
  assert_eq "#611 override_precondition_rows: ... and emit-body's refusal carries it too (the costliest discovery point)" \
    "yes" "$(grep -q 'fresh explicit user election' "$OP_SB/.op-tampered-emit-err" 2>/dev/null && echo yes || echo no)"
  assert_eq "#611 override_precondition_rows: ... while emit-body keeps its existing _fail message unchanged" \
    "yes" "$(grep -q 'refusing to emit an unaudited body: eligibility answered not-eligible (stale-override)' "$OP_SB/.op-tampered-emit-err" 2>/dev/null && echo yes || echo no)"
  assert_eq "#546 override_precondition_rows: ... and emit-body refuses them with the empty-stdout signature" \
    "1:" "$(cat "$OP_SB/.op-tampered-emit-rc" 2>/dev/null):$(cat "$OP_SB/.op-tampered-emit" 2>/dev/null)"
  # (2b) the read boundary for the unbound precondition: a hand-planted/pre-delta
  # unbound override on a file-arm epoch must not be honoured either.
  assert_eq "#546 override_precondition_rows: a hand-planted digest-unbound override on a file-arm epoch is not honoured at the read boundary" \
    "1" "$(grep -c '^eligible=no ' "$OP_SB/.op-unbound-read-elig" 2>/dev/null)"
  assert_eq "#546 override_precondition_rows: ... and emit-body refuses it with the empty-stdout signature" \
    "1:" "$(cat "$OP_SB/.op-unbound-read-emit-rc" 2>/dev/null):$(cat "$OP_SB/.op-unbound-read-emit" 2>/dev/null)"
  # The token rows are a pair: each must be a real token (not empty — which would make
  # the inequality assert vacuous), and the two must differ.
  assert_eq "#546 override_precondition_rows: a digest-bound override mints a real token (guards the row below against vacuity)" \
    "1" "$(grep -c '^token=eat_' "$OP_SB/.op-tok-op3a" 2>/dev/null)"
  assert_eq "#546 override_precondition_rows: byte-distinct drafts at the same ordinal mint DIFFERENT override tokens" \
    "differ" "$( [ "$(sed -n 1p "$OP_SB/.op-tok-op3a" 2>/dev/null)" != "$(sed -n 1p "$OP_SB/.op-tok-op3b" 2>/dev/null)" ] && printf 'differ' || printf 'same' )"
  assert_eq "#546 override_precondition_rows: the attestation was actually recorded (guards the row below against vacuity)" \
    "attestation=match" "$(sed -n 1p "$OP_SB/.op-attest" 2>/dev/null)"
  assert_eq "#546 override_precondition_rows: a forced re-init refuses to discard a recorded creation attestation" \
    "1:1" "$(sed -n 1p "$OP_SB/.op-reinit-rc" 2>/dev/null):$(grep -c 'forward-only tamper evidence' "$OP_SB/.op-reinit" 2>/dev/null)"
  rm -rf "$OP_SB"
fi

# retry_arm_deadlock_rows (#546, PR #552 iteration-3 review) — the same-arm retry must
# be satisfiable when the canonical file goes unhashable between the return and the
# retry. query-arm routes that to embed; without the escalation record-dispatch refused
# the arm the tool itself just prescribed, the file arm could not read the file, and
# next-action re-answered the same spent token forever — a run with NO legal next call,
# which the skill is forbidden from improvising around. The negative rows keep the
# escalation scoped: it is file->embed only, and it never goes unmarked.
RD_SB="$(git_sandbox '#546 retry_arm_deadlock_rows')"
if [ -d "$RD_SB" ]; then
  (
    cd "$RD_SB" || exit 1
    git init -q . 2>/dev/null
    mkdir -p .prflow/tmp
    printf '# T\n\nbody\n' > draft.md

    # the deadlock: file-arm round -> no-parseable-verdict -> draft becomes unhashable
    N="$(python3 "$IAS" init rd | sed -n '1s/nonce=//p')"
    ias_stage rd "$N" draft.md
    python3 "$IAS" record-offer rd --nonce "$N" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery rd --nonce "$N" --round 1 --arm file \
      --draft-file draft.md > /dev/null 2>&1
    python3 "$IAS" record-return rd --nonce "$N" --round 1 > /dev/null 2>&1
    python3 "$IAS" query-next-action rd --nonce "$N" --round 1 > .rd-pending 2>&1
    rm -f draft.md
    python3 "$IAS" query-arm rd --nonce "$N" --write-landed yes --draft-file draft.md \
      > .rd-arm 2> /dev/null
    # obey query-arm verbatim — this is the call that used to deadlock
    printf '# T\n\nbody\n' | python3 "$IAS" record-dispatch --kind discovery rd --nonce "$N" --round 1 \
      --arm embed --marker digest-unrecorded > .rd-escalate 2>&1
    printf '%s' "$?" > .rd-escalate-rc

    # negative: inline is NOT permitted by a same-arm retry (stdin supplied, so the
    # arm guard is what refuses — not the missing-bytes check)
    N2="$(python3 "$IAS" init rd2 | sed -n '1s/nonce=//p')"
    printf '# T\n\nb\n' > d2.md
    ias_stage rd2 "$N2" d2.md
    python3 "$IAS" record-offer rd2 --nonce "$N2" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery rd2 --nonce "$N2" --round 1 --arm file \
      --draft-file d2.md > /dev/null 2>&1
    python3 "$IAS" record-return rd2 --nonce "$N2" --round 1 > /dev/null 2>&1
    printf '# T\n\nb\n' | python3 "$IAS" record-dispatch --kind discovery rd2 --nonce "$N2" --round 1 \
      --arm inline > /dev/null 2> .rd-inline; printf '%s' "$?" > .rd-inline-rc

    # negative: an INLINE-arm round's same-arm retry gains NO embed escalation. This is
    # the row that actually pins the scoping. Asserting that an embed round refuses the
    # FILE arm would be vacuous — the escalation only ever appends 'embed', so no
    # mutation of the scoping could permit 'file' and such a row would exercise only the
    # pre-existing base guard. Dropping the `same == 'file'` condition instead widens the
    # escalation to EVERY same-arm retry, and inline — the terminal degraded arm, which
    # the docstring explicitly disclaims — is where that shows.
    N3="$(python3 "$IAS" init rd3 | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-offer rd3 --nonce "$N3" --accepted > /dev/null
    printf '# T\n\nb\n' | python3 "$IAS" record-dispatch --kind discovery rd3 --nonce "$N3" --round 1 \
      --arm inline > /dev/null 2>&1
    python3 "$IAS" record-return rd3 --nonce "$N3" --round 1 > /dev/null 2>&1
    printf '# T\n\nb\n' | python3 "$IAS" record-dispatch --kind discovery rd3 --nonce "$N3" --round 1 \
      --arm embed --marker write-failed > /dev/null 2> .rd-inlineround
    printf '%s' "$?" > .rd-inlineround-rc

    # negative: the escalation never goes unmarked (it must stay recorded evidence)
    N4="$(python3 "$IAS" init rd4 | sed -n '1s/nonce=//p')"
    ias_stage rd4 "$N4" d2.md
    python3 "$IAS" record-offer rd4 --nonce "$N4" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery rd4 --nonce "$N4" --round 1 --arm file \
      --draft-file d2.md > /dev/null 2>&1
    python3 "$IAS" record-return rd4 --nonce "$N4" --round 1 > /dev/null 2>&1
    printf '# T\n\nb\n' | python3 "$IAS" record-dispatch --kind discovery rd4 --nonce "$N4" --round 1 \
      --arm embed > /dev/null 2> .rd-nomarker; printf '%s' "$?" > .rd-nomarker-rc

    # A CLOSED fd 0 (`0<&-`) must still produce the named breadcrumb, never a raw
    # traceback. This is the absent-operand shape: CPython sets `sys.stdin = None` at
    # startup, so the ATTRIBUTE access fails — an `except OSError` around the read is
    # blind to it. Without these rows the guard could be "simplified" back to a bare
    # except OSError and nothing would go RED while a traceback reached the caller's
    # stderr classifier instead of one of this tool's vocabulary strings.
    N5="$(python3 "$IAS" init rd5 | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-offer rd5 --nonce "$N5" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery rd5 --nonce "$N5" --round 1 --arm embed \
      --marker write-failed 0<&- > /dev/null 2> .rd-nostdin
    printf '%s' "$?" > .rd-nostdin-rc
    # after_round's READ boundary — the sibling of the override read guard, found by the
    # parked-class sweep. after_round is the SOLE invalidation evidence on the
    # event-ordering ground, so a value below the floor fails that guard OPEN: a revised,
    # never-audited draft answers eligible and emit-body emits it at exit 0. The write
    # boundary refuses it; this proves the read boundary does too. The positive control
    # keeps the fixture honest — a revision legitimately recorded while its round is
    # still open carries floor 0 and must STILL be accepted.
    N7="$(python3 "$IAS" init rd7 | sed -n '1s/nonce=//p')"
    printf '# T\n\nORIG\n' > d7.md
    python3 "$IAS" record-offer rd7 --nonce "$N7" --accepted > /dev/null
    printf '# T\n\nORIG\n' | python3 "$IAS" record-dispatch --kind discovery rd7 --nonce "$N7" --round 1 \
      --arm embed --marker write-failed > /dev/null 2>&1
    RD7_OPEN="$(python3 -c "import json,pathlib;print(json.loads(pathlib.Path('.prflow/tmp/issue-audit-state-rd7.json').read_text())['rounds'][0]['attempts'][-1]['sentinel_open'])")"
    RD7_CLOSE="$(python3 -c "import json,pathlib;print(json.loads(pathlib.Path('.prflow/tmp/issue-audit-state-rd7.json').read_text())['rounds'][0]['attempts'][-1]['sentinel_close'])")"
    python3 "$IAS" record-return rd7 --nonce "$N7" --round 1 --verdict FILE \
      --findings-count 0 --carriage-sentinel-open "$RD7_OPEN" \
      --carriage-sentinel-close "$RD7_CLOSE" > /dev/null 2>&1
    python3 "$IAS" record-revision rd7 --nonce "$N7" --after-round 1 > /dev/null 2>&1
    printf '# T\n\nREVISED never audited\n' > d7.md
    python3 - <<'PY' > /dev/null 2>&1
import json, pathlib
p = pathlib.Path('.prflow/tmp/issue-audit-state-rd7.json')
d = json.loads(p.read_text())
d['revisions'][0]['after_round'] = 0        # below the floor recorded with it
p.write_text(json.dumps(d))
PY
    python3 "$IAS" query-eligibility rd7 --nonce "$N7" --mode approve \
      --draft-file d7.md > .rd-afterround 2>/dev/null
    python3 "$IAS" emit-body rd7 --nonce "$N7" --draft-file d7.md \
      > .rd-afterround-emit 2>/dev/null; printf '%s' "$?" > .rd-afterround-emit-rc
    # positive control: floor 0 is legitimate while the round is still open
    N8="$(python3 "$IAS" init rd8 | sed -n '1s/nonce=//p')"
    ias_stage rd8 "$N8" d2.md
    python3 "$IAS" record-offer rd8 --nonce "$N8" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery rd8 --nonce "$N8" --round 1 --arm file \
      --draft-file d2.md > /dev/null 2>&1
    # issue #705: the round dispatched on the file arm, so record-revision requires
    # --stdin-digest even while the round is still open (floor 0 positive control).
    printf '# T\n\nORIG\n' | python3 "$IAS" record-revision rd8 --nonce "$N8" \
      --after-round 0 --stdin-digest > .rd-floor0 2>&1; printf '%s' "$?" > .rd-floor0-rc

    # the attestation twin: bind a real epoch first so the read is actually reached
    N6="$(python3 "$IAS" init rd6 | sed -n '1s/nonce=//p')"
    ias_stage rd6 "$N6" d2.md
    python3 "$IAS" record-offer rd6 --nonce "$N6" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery rd6 --nonce "$N6" --round 1 --arm file \
      --draft-file d2.md > /dev/null 2>&1
    D6="$(git hash-object --stdin --no-filters < d2.md)"
    python3 "$IAS" record-return rd6 --nonce "$N6" --round 1 --verdict FILE \
      --findings-count 0 --carriage-object-id "$D6" > /dev/null 2>&1
    python3 "$IAS" record-creation-epoch rd6 --nonce "$N6" --round 1 > /dev/null 2>&1
    python3 "$IAS" record-creation-attestation rd6 --nonce "$N6" 0<&- \
      > /dev/null 2> .rd-nostdin-att; printf '%s' "$?" > .rd-nostdin-att-rc
  )
  assert_eq "#546 retry_arm_deadlock_rows: a no-parseable-verdict completion leaves a same-arm retry pending (setup control)" \
    "action=dispatch-retry-same-arm" "$(sed -n 1p "$RD_SB/.rd-pending" 2>/dev/null)"
  assert_eq "#546 retry_arm_deadlock_rows: an unhashable draft routes the retry to the embed arm (setup control)" \
    "arm=embed marker=digest-unrecorded" "$(sed -n 1p "$RD_SB/.rd-arm" 2>/dev/null)"
  assert_eq "#546 retry_arm_deadlock_rows: the embed arm query-arm prescribed is ACCEPTED (no deadlock)" \
    "0" "$(sed -n 1p "$RD_SB/.rd-escalate-rc" 2>/dev/null)"
  assert_eq "#546 retry_arm_deadlock_rows: ... and the escalation is recorded on the round, never silent" \
    "1" "$(grep -c 'arm=embed' "$RD_SB/.rd-escalate" 2>/dev/null)"
  assert_eq "#546 retry_arm_deadlock_rows: a same-arm retry still refuses the inline arm" \
    "1:1" "$(sed -n 1p "$RD_SB/.rd-inline-rc" 2>/dev/null):$(grep -c 'does not permit a dispatch on the inline arm' "$RD_SB/.rd-inline" 2>/dev/null)"
  assert_eq "#546 retry_arm_deadlock_rows: an INLINE round's same-arm retry gains no embed escalation (the scoping is file-only)" \
    "1:1" "$(sed -n 1p "$RD_SB/.rd-inlineround-rc" 2>/dev/null):$(grep -c 'does not permit a dispatch on the embed arm' "$RD_SB/.rd-inlineround" 2>/dev/null)"
  assert_eq "#546 retry_arm_deadlock_rows: the escalated embed dispatch still requires its cause marker" \
    "1:1" "$(sed -n 1p "$RD_SB/.rd-nomarker-rc" 2>/dev/null):$(grep -c 'requires --marker naming the entry cause' "$RD_SB/.rd-nomarker" 2>/dev/null)"
  assert_eq "#546 retry_arm_deadlock_rows: a CLOSED fd 0 names the breadcrumb on record-dispatch, never a traceback" \
    "1:1" "$(sed -n 1p "$RD_SB/.rd-nostdin-rc" 2>/dev/null):$(grep -c 'no stdin is attached (fd 0 is closed)' "$RD_SB/.rd-nostdin" 2>/dev/null)"
  assert_eq "#546 retry_arm_deadlock_rows: ... and on record-creation-attestation, the tamper-detection surface" \
    "1:1" "$(sed -n 1p "$RD_SB/.rd-nostdin-att-rc" 2>/dev/null):$(grep -c 'no stdin is attached (fd 0 is closed)' "$RD_SB/.rd-nostdin-att" 2>/dev/null)"
  assert_eq "#546 retry_arm_deadlock_rows: an after_round below its recorded floor is refused at the READ boundary (the event-ordering fail-open)" \
    "eligible=no reason=state-unestablished" "$(sed -n 1p "$RD_SB/.rd-afterround" 2>/dev/null)"
  assert_eq "#546 retry_arm_deadlock_rows: ... and emit-body refuses it with the empty-stdout signature" \
    "1:" "$(cat "$RD_SB/.rd-afterround-emit-rc" 2>/dev/null):$(cat "$RD_SB/.rd-afterround-emit" 2>/dev/null)"
  assert_eq "#546 retry_arm_deadlock_rows: ... while a floor-0 revision recorded against a still-open round stays legal (positive control)" \
    "0" "$(sed -n 1p "$RD_SB/.rd-floor0-rc" 2>/dev/null)"
  rm -rf "$RD_SB"
fi

# iter6_seam_rows (#546, PR #552 review) — three CLI seams the review showed undriven:
# the EMPTY-but-open stdin dispatch (a `< /dev/null` redirect is not a closed fd 0, so
# the rd5 rows above never reach the received-none branch), the empty-object-id-on-exit-0
# digest guard (a shimmed/broken git that "succeeds" silently — without the guard the ''
# digest compares equal to another '' and grounds eligibility on unaudited bytes), and
# query-summary's foreign-nonce coercion (every OTHER query class has a foreign-nonce row
# above; the summary is the one an orchestrator reads fields from, so a foreign nonce
# rendering state=ok with a live token would hand a hostile/stale run a presentable
# answer). Each refusal is attributed by the guard's OWN breadcrumb and paired with a
# positive control on the SAME fixture, so a green negative row cannot be an unrelated
# precondition firing.
I6_SB="$(git_sandbox '#546 iter6_seam_rows')"
if [ -d "$I6_SB" ]; then
  (
    cd "$I6_SB" || exit 1
    git init -q . 2>/dev/null
    mkdir -p .prflow/tmp
    printf '# T\n\nbody\n' > draft.md
    OID="$(git hash-object --stdin --no-filters < draft.md)"

    # (1) stdin OPEN but EMPTY: the received-none branch, distinct from the closed-fd
    # AttributeError shape rd5 pins. The refusal must precede any state mutation, so
    # the positive control can re-dispatch the SAME round on the same fixture.
    N="$(python3 "$IAS" init i6a | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-offer i6a --nonce "$N" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery i6a --nonce "$N" --round 1 --arm embed \
      --marker digest-unrecorded < /dev/null > /dev/null 2> .i6-empty; printf '%s' "$?" > .i6-empty-rc
    printf '# T\n\nbody\n' | python3 "$IAS" record-dispatch --kind discovery i6a --nonce "$N" --round 1 \
      --arm embed --marker digest-unrecorded > /dev/null 2>&1; printf '%s' "$?" > .i6-empty-ctl-rc

    # (2) a git shim that answers hash-object with EMPTY stdout at exit 0 (every other
    # subcommand delegates to the real git, so state anchoring still resolves). The
    # digest guard must refuse — an empty '' object id must never read as a digest.
    REAL_GIT="$(command -v git)"
    mkdir -p stub-bin
    {
      printf '#!/bin/sh\n'
      printf 'case "$1" in hash-object) exit 0 ;; esac\n'
      printf 'exec "%s" "$@"\n' "$REAL_GIT"
    } > stub-bin/git
    chmod +x stub-bin/git
    N2="$(python3 "$IAS" init i6b | sed -n '1s/nonce=//p')"
    ias_stage i6b "$N2" draft.md
    python3 "$IAS" record-offer i6b --nonce "$N2" --accepted > /dev/null
    PATH="$I6_SB/stub-bin:$PATH" python3 "$IAS" record-dispatch --kind discovery i6b --nonce "$N2" \
      --round 1 --arm file --draft-file draft.md > /dev/null 2> .i6-oid; printf '%s' "$?" > .i6-oid-rc
    # positive control: the identical invocation without the shim succeeds.
    ias_stage i6b "$N2" draft.md
    python3 "$IAS" record-dispatch --kind discovery i6b --nonce "$N2" --round 1 --arm file \
      --draft-file draft.md > /dev/null 2>&1; printf '%s' "$?" > .i6-oid-ctl-rc

    # (3) query-summary on a foreign nonce: exit 0 (query contract), the rendered line
    # is the fail-closed unestablished shape with NO live token, and the stderr
    # breadcrumb names the mismatch so it is not misread as a missing/corrupt record.
    N3="$(python3 "$IAS" init i6c | sed -n '1s/nonce=//p')"
    # issue #709: the positive control below asserts a LIVE eligibility token, which the
    # clean ground only issues once steering-absence is established — so this epoch
    # establishes it the way a real run does.
    IOID6="$(ias_instructions "$I6_SB" i6c draft.md)"
    ias_stage i6c "$N3" draft.md
    python3 "$IAS" record-offer i6c --nonce "$N3" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery i6c --nonce "$N3" --round 1 --arm file \
      --draft-file draft.md --instructions-file "$I6_SB/instr-i6c.md" \
      --instructions-draft-path "$I6_SB/draft.md" > /dev/null 2>&1
    python3 "$IAS" record-return i6c --nonce "$N3" --round 1 --verdict FILE \
      --findings-count 0 --carriage-object-id "$OID" \
      --instructions-object-id "$IOID6" --extra-dispatch-content no > /dev/null 2>&1
    python3 "$IAS" query-summary i6c --nonce badnonce --draft-file draft.md \
      > .i6-fn-sum 2> .i6-fn-err; printf '%s' "$?" > .i6-fn-rc
    # positive control: the correct nonce on the SAME state renders ok + the live token.
    python3 "$IAS" query-summary i6c --nonce "$N3" --draft-file draft.md \
      > .i6-ok-sum 2>/dev/null
  )
  assert_eq "#546 iter6_seam_rows: an OPEN-but-EMPTY stdin refuses the embed dispatch non-zero" \
    "1" "$(cat "$I6_SB/.i6-empty-rc" 2>/dev/null)"
  assert_eq "#546 iter6_seam_rows: ... attributed to the received-none guard by its own breadcrumb" \
    "1" "$(grep -c 'requires the draft bytes on stdin; received none' "$I6_SB/.i6-empty" 2>/dev/null)"
  assert_eq "#546 iter6_seam_rows: positive control — the identical dispatch with non-empty stdin is accepted" \
    "0" "$(sed -n 1p "$I6_SB/.i6-empty-ctl-rc" 2>/dev/null)"
  assert_eq "#546 iter6_seam_rows: a git shim answering hash-object empty-at-exit-0 refuses non-zero" \
    "1" "$(cat "$I6_SB/.i6-oid-rc" 2>/dev/null)"
  assert_eq "#546 iter6_seam_rows: ... attributed to the empty-object-id digest guard by its own breadcrumb" \
    "1" "$(grep -c 'returned an empty object id on exit 0' "$I6_SB/.i6-oid" 2>/dev/null)"
  assert_eq "#546 iter6_seam_rows: positive control — the identical dispatch without the shim is accepted" \
    "0" "$(sed -n 1p "$I6_SB/.i6-oid-ctl-rc" 2>/dev/null)"
  assert_eq "#546 iter6_seam_rows: query-summary on a foreign nonce keeps the query exit-0 contract" \
    "0" "$(cat "$I6_SB/.i6-fn-rc" 2>/dev/null)"
  assert_eq "#546 iter6_seam_rows: ... and renders the fail-closed unestablished shape" \
    "1" "$(grep -c '^state=unestablished ' "$I6_SB/.i6-fn-sum" 2>/dev/null)"
  assert_eq "#546 iter6_seam_rows: ... with NO live token rendered for the foreign run" \
    "1" "$(grep -c ' token=none ' "$I6_SB/.i6-fn-sum" 2>/dev/null)"
  assert_eq "#546 iter6_seam_rows: ... and the stderr breadcrumb names the nonce mismatch, not a missing record" \
    "1" "$(grep -c 'nonce mismatch for slug i6c' "$I6_SB/.i6-fn-err" 2>/dev/null)"
  assert_eq "#546 iter6_seam_rows: positive control — the correct nonce on the SAME state renders state=ok" \
    "1" "$(grep -c '^state=ok ' "$I6_SB/.i6-ok-sum" 2>/dev/null)"
  assert_eq "#546 iter6_seam_rows: ... with the due live token rendered" \
    "1" "$(grep -c ' token=eat_' "$I6_SB/.i6-ok-sum" 2>/dev/null)"
  rm -rf "$I6_SB"
fi

# ────────────────────────────────────────────────────────────────────────────
# issue #562: the tiered draft-root binding, CLI-level. record-draft-binding round-trip
# (re-queried in a FRESH process so nothing rests on in-context memory), the once-per-run
# and validation breadcrumbs, record-write-failure, and a REAL linked-worktree binding.
DB_SB="$(git_sandbox '#562 draft_binding_cli_rows')"
if [ -d "$DB_SB" ]; then
  (
    cd "$DB_SB" || exit 1
    git init -q .
    git config user.email t@t; git config user.name t
    mkdir -p .prflow/tmp
    printf '# T\n\nB\n' > d.md
    git add -A > /dev/null 2>&1; git commit -qm init > /dev/null 2>&1
    N="$(python3 "$IAS" init db | sed -n '1s/nonce=//p')"
    # Unbound query first: the fail-closed bound=none token.
    python3 "$IAS" query-draft-binding db --nonce "$N" > .db-unbound
    # Record a worktree-root binding with a divergent non-bound main root.
    python3 "$IAS" record-draft-binding db --nonce "$N" \
      --path "$DB_SB" --tier worktree-root --non-bound-root /main/root > .db-rec
    # Re-query in a FRESH process (no in-context memory).
    python3 "$IAS" query-draft-binding db --nonce "$N" > .db-bound
    # A second binding is illegal.
    python3 "$IAS" record-draft-binding db --nonce "$N" --path /x --tier main-root \
      > /dev/null 2> .db-second; printf '%s' "$?" > .db-second-rc
    # Validation breadcrumbs (fail closed).
    python3 "$IAS" init dv > /dev/null 2>&1
    NV="$(python3 "$IAS" query-nonce dv | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-draft-binding dv --nonce "$NV" --path rel/x --tier main-root \
      > /dev/null 2> .dv-relpath; printf '%s' "$?" > .dv-relpath-rc
    python3 "$IAS" record-draft-binding dv --nonce "$NV" --path /a --tier bogus \
      > /dev/null 2> .dv-tier; printf '%s' "$?" > .dv-tier-rc
    python3 "$IAS" record-draft-binding dv --nonce "$NV" --path /a \
      > /dev/null 2> .dv-notier; printf '%s' "$?" > .dv-notier-rc
    python3 "$IAS" record-draft-binding dv --nonce "$NV" --path /a --tier main-root \
      --non-bound-root rel > /dev/null 2> .dv-nbr; printf '%s' "$?" > .dv-nbr-rc
    # record-write-failure records an ordinal at the bound path.
    python3 "$IAS" record-write-failure db --nonce "$N" --ordinal 1 > .db-wf
    # query-draft-binding on a foreign nonce: exit 0 (query contract), fail-closed token.
    python3 "$IAS" query-draft-binding db --nonce badnonce > .db-fn 2>/dev/null
    printf '%s' "$?" > .db-fn-rc
    # record-revision --stdin-digest producer: the emitted line carries the digest, and an
    # empty stdin fails loud (a fresh run so the revision has a round to attach to).
    python3 "$IAS" init dr > /dev/null 2>&1
    NR="$(python3 "$IAS" query-nonce dr | sed -n '1s/nonce=//p')"
    ias_stage dr "$NR" d.md
    python3 "$IAS" record-offer dr --nonce "$NR" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery dr --nonce "$NR" --round 1 --arm file \
      --draft-file d.md > /dev/null 2>&1
    OIDR="$(git hash-object --stdin --no-filters < d.md)"
    python3 "$IAS" record-return dr --nonce "$NR" --round 1 --verdict REVISE \
      --carriage-object-id "$OIDR" > /dev/null 2>&1
    printf 'revised bytes\n' | python3 "$IAS" record-revision dr --nonce "$NR" \
      --after-round 1 --stdin-digest > .dr-sd 2>&1
    printf '' | python3 "$IAS" record-revision dr --nonce "$NR" --after-round 1 \
      --stdin-digest > /dev/null 2> .dr-empty; printf '%s' "$?" > .dr-empty-rc
    # Bound-branch cannot-prove vs proven-failed tokens (#1841; was review Suggestion #5).
    # `dr` carries a recorded revision with an stdin digest but NO subsequent landed write
    # (only round 1 exists, predating the revision), so `latest_revision_landed` can prove
    # neither landing nor failure -> `unestablished` (the common basis=resolution terminal
    # path). Bind a root and query it. Then record an overwrite failure for the latest
    # ordinal and re-query: that PROVES non-landing -> `no`, the token a `yes`-hardcoding
    # regression in the bound-branch assembly (the exact stale-file bug the flag exists to
    # catch) would break RED.
    python3 "$IAS" record-draft-binding dr --nonce "$NR" \
      --path "$DB_SB" --tier worktree-root > /dev/null 2>&1
    python3 "$IAS" query-draft-binding dr --nonce "$NR" > .dr-unlanded 2>/dev/null
    python3 "$IAS" record-write-failure dr --nonce "$NR" --ordinal 1 > /dev/null 2>&1
    python3 "$IAS" query-draft-binding dr --nonce "$NR" > .dr-failed 2>/dev/null
    # AC1: the query-draft-binding --help text enumerates the three landed tokens.
    python3 "$IAS" query-draft-binding --help > .dbh-help 2>&1
    # Bound-path source override: bind a root, put the canonical draft under it, and prove
    # emit-body reads the BOUND file, not a drifted --draft-file (the anti-drift property).
    python3 "$IAS" init 'do' > /dev/null 2>&1
    NO="$(python3 "$IAS" query-nonce 'do' | sed -n '1s/nonce=//p')"
    BR="$DB_SB/boundroot"
    mkdir -p "$BR/.prflow/tmp"
    printf '# Draft title\n\nBOUND BODY\n' > "$BR/.prflow/tmp/issue-draft-do.md"
    printf '# Draft title\n\nDRIFTED BODY\n' > drift.md
    python3 "$IAS" record-draft-binding 'do' --nonce "$NO" --path "$BR" --tier main-root \
      > /dev/null 2>&1
    # issue #709: the anti-drift rows below assert a LIVE clean-ground answer, which now
    # requires established steering — so this epoch establishes it against the BOUND file
    # (the one the readers must resolve to), never the drifted one.
    IOIDO="$(ias_instructions "$DB_SB" 'do' "$BR/.prflow/tmp/issue-draft-do.md")"
    ias_stage 'do' "$NO" "$BR/.prflow/tmp/issue-draft-do.md"
    python3 "$IAS" record-offer 'do' --nonce "$NO" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery 'do' --nonce "$NO" --round 1 --arm file \
      --draft-file "$BR/.prflow/tmp/issue-draft-do.md" \
      --instructions-file "$DB_SB/instr-do.md" \
      --instructions-draft-path "$BR/.prflow/tmp/issue-draft-do.md" > /dev/null 2>&1
    OIDO="$(git hash-object --stdin --no-filters < "$BR/.prflow/tmp/issue-draft-do.md")"
    python3 "$IAS" record-return 'do' --nonce "$NO" --round 1 --verdict FILE \
      --findings-count 0 --carriage-object-id "$OIDO" \
      --instructions-object-id "$IOIDO" --extra-dispatch-content no > /dev/null 2>&1
    # emit-body is handed the DRIFTED file, but must emit the BOUND file's body.
    python3 "$IAS" emit-body 'do' --nonce "$NO" --draft-file drift.md > .do-body 2>/dev/null
    # The TWO merge-gating queries share emit-body's `_bound_draft_file(...) or --draft-file`
    # resolution — but only emit-body's anti-drift was proven above. query-eligibility
    # --mode approve is the answer the skill obeys at the merge gate; query-summary renders
    # the presentation token. Both are handed the DRIFTED file and must ground on the BOUND
    # one: eligibility answers `eligible=yes ground=file-identity` (the bound digest matches
    # the clean round's recorded dispatch digest) and the summary emits a non-`none` token —
    # a regression dropping the bound-first prefix from either query grounds on drift.md's
    # digest instead, answering `eligible=no`/`token=none` and re-opening the compacted-
    # context drift this feature closes (issue #562, review Important #1).
    python3 "$IAS" query-eligibility 'do' --nonce "$NO" --mode approve --draft-file drift.md \
      > .do-elig 2>/dev/null
    python3 "$IAS" query-summary 'do' --nonce "$NO" --draft-file drift.md > .do-summary 2>/dev/null
    # Unbound-run reader fallback (review Suggestion #7): the bound `do` rows above prove the
    # BOUND-first branch; the unbound arm (`_bound_draft_file` returns None → readers fall back
    # to the caller `--draft-file`) is otherwise only covered transitively. Record NO binding,
    # give emit-body a real draft on `--draft-file`, and prove it emits THAT file's body.
    python3 "$IAS" init du > /dev/null 2>&1
    NU="$(python3 "$IAS" query-nonce du | sed -n '1s/nonce=//p')"
    printf '# Draft title\n\nUNBOUND BODY\n' > ub.md
    IOIDU="$(ias_instructions "$DB_SB" du ub.md)"
    ias_stage du "$NU" ub.md
    python3 "$IAS" record-offer du --nonce "$NU" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery du --nonce "$NU" --round 1 --arm file \
      --draft-file ub.md --instructions-file "$DB_SB/instr-du.md" \
      --instructions-draft-path "$DB_SB/ub.md" > /dev/null 2>&1
    OIDU="$(git hash-object --stdin --no-filters < ub.md)"
    python3 "$IAS" record-return du --nonce "$NU" --round 1 --verdict FILE \
      --findings-count 0 --carriage-object-id "$OIDU" \
      --instructions-object-id "$IOIDU" --extra-dispatch-content no > /dev/null 2>&1
    python3 "$IAS" emit-body du --nonce "$NU" --draft-file ub.md > .du-body 2>/dev/null
    # A REAL linked worktree: bind its own toplevel and confirm the query round-trips.
    git branch -q wt-562 2>/dev/null
    if git worktree add -q ../wt562 wt-562 2>/dev/null; then
      WT="$(cd ../wt562 && pwd)"
      ( cd ../wt562 && mkdir -p .prflow/tmp
        NW="$(python3 "$IAS" init wtb | sed -n '1s/nonce=//p')"
        python3 "$IAS" record-draft-binding wtb --nonce "$NW" \
          --path "$WT" --tier worktree-root > /dev/null
        python3 "$IAS" query-draft-binding wtb --nonce "$NW" ) > "$DB_SB/.db-wt"
    fi
  )
  assert_eq "#562 draft_binding_cli_rows: an unbound run answers the fail-closed bound=none token" \
    "bound=none tier=none non_bound_root=none latest_revision_landed=yes" \
    "$(sed -n 1p "$DB_SB/.db-unbound" 2>/dev/null)"
  assert_eq "#562 draft_binding_cli_rows: a worktree-root binding round-trips (fresh process) with its non-bound root" \
    "bound=$DB_SB tier=worktree-root non_bound_root=/main/root latest_revision_landed=yes" \
    "$(sed -n 1p "$DB_SB/.db-bound" 2>/dev/null)"
  assert_eq "#562 draft_binding_cli_rows: a second record-draft-binding is illegal (exit non-zero)" \
    "1" "$(cat "$DB_SB/.db-second-rc" 2>/dev/null)"
  assert_eq "#562 draft_binding_cli_rows: ... named by the binding-already-recorded breadcrumb" \
    "1" "$(grep -c 'binding-already-recorded' "$DB_SB/.db-second" 2>/dev/null)"
  assert_eq "#562 draft_binding_cli_rows: a non-absolute bound path is refused (fail closed)" \
    "1" "$(cat "$DB_SB/.dv-relpath-rc" 2>/dev/null)"
  assert_eq "#562 draft_binding_cli_rows: ... named by the binding-path-not-absolute breadcrumb" \
    "1" "$(grep -c 'binding-path-not-absolute' "$DB_SB/.dv-relpath" 2>/dev/null)"
  assert_eq "#562 draft_binding_cli_rows: an unknown tier token is refused" \
    "1" "$(grep -c 'binding-tier-unknown' "$DB_SB/.dv-tier" 2>/dev/null)"
  assert_eq "#562 draft_binding_cli_rows: a missing tier token is refused" \
    "1" "$(grep -c 'binding-tier-missing' "$DB_SB/.dv-notier" 2>/dev/null)"
  assert_eq "#562 draft_binding_cli_rows: a non-absolute non-bound root is refused" \
    "1" "$(grep -c 'binding-nonbound-not-absolute' "$DB_SB/.dv-nbr" 2>/dev/null)"
  assert_eq "#562 draft_binding_cli_rows: record-write-failure records the ordinal at the bound path" \
    "write_failure_recorded ordinal=1 count=1" "$(sed -n 1p "$DB_SB/.db-wf" 2>/dev/null)"
  assert_eq "#562 draft_binding_cli_rows: query-draft-binding on a foreign nonce keeps the query exit-0 contract" \
    "0" "$(cat "$DB_SB/.db-fn-rc" 2>/dev/null)"
  assert_eq "#562 draft_binding_cli_rows: ... and answers the fail-closed foreign-nonce token" \
    "1" "$(grep -c '^bound=none .* reason=foreign-nonce$' "$DB_SB/.db-fn" 2>/dev/null)"
  assert_eq "#562 draft_binding_cli_rows: record-revision --stdin-digest emits the recorded digest" \
    "1" "$(grep -cE '^ordinal=1 stdin_digest=[0-9a-f]+$' "$DB_SB/.dr-sd" 2>/dev/null)"
  assert_eq "#562 draft_binding_cli_rows: record-revision --stdin-digest with empty stdin fails non-zero" \
    "1" "$(cat "$DB_SB/.dr-empty-rc" 2>/dev/null)"
  assert_eq "#562 draft_binding_cli_rows: ... named by the no-bytes breadcrumb" \
    "1" "$(grep -c 'no revised bytes were received on stdin' "$DB_SB/.dr-empty" 2>/dev/null)"
  assert_eq "#562 draft_binding_cli_rows: emit-body reads the BOUND file, not a drifted --draft-file (anti-drift)" \
    "1" "$(grep -c '^BOUND BODY$' "$DB_SB/.do-body" 2>/dev/null)"
  assert_eq "#562 draft_binding_cli_rows: ... and does NOT emit the drifted file's body" \
    "0" "$(grep -c 'DRIFTED BODY' "$DB_SB/.do-body" 2>/dev/null)"
  # The merge-gating queries resolve the SAME bound-first way (review Important #1): a
  # dropped prefix would ground on drift.md and answer eligible=no / token=none.
  assert_eq "#562 draft_binding_cli_rows: query-eligibility --mode approve grounds on the BOUND file, not a drifted --draft-file (anti-drift)" \
    "1" "$(grep -c '^eligible=yes ground=file-identity' "$DB_SB/.do-elig" 2>/dev/null)"
  # Pin a LIVE presentable token (neither `none` NOR `stale-token`): grounding on drift.md
  # yields a digest that mismatches the clean round, rendering `token=stale-token` — so a
  # bare `token=none` check would pass vacuously against the drift regression (caught at the
  # desk by the mutation run). A live `token=<hex>` proves the summary grounded on the BOUND file.
  assert_eq "#562 draft_binding_cli_rows: query-summary grounds on the BOUND file — a LIVE presentation token, not stale-token/none (anti-drift)" \
    "0" "$(grep -cE 'token=(none|stale-token)' "$DB_SB/.do-summary" 2>/dev/null)"
  # S#6: pin the query-summary `bound_root`/`bound_tier` substring AND its position — the
  # single fixed string `bound_root=<path> bound_tier=main-root attestation=` proves both the
  # values render and that they sit immediately before the trailing `attestation=` field
  # (a re-order or a dropped field fails RED). $BR is the bound root for the `do` epoch.
  assert_eq "#562 draft_binding_cli_rows: query-summary renders bound_root/bound_tier before the trailing attestation field (S#6)" \
    "1" "$(grep -cF "bound_root=$DB_SB/boundroot bound_tier=main-root steering=established steering_reason=canonical-match attestation=" "$DB_SB/.do-summary" 2>/dev/null)"
  # #1841: a bound run whose latest revision cannot be proven landed (no write-failure, no
  # subsequent matching dispatch) renders `latest_revision_landed=unestablished` — the
  # common basis=resolution terminal path, no longer the false-alarm `no`.
  assert_eq "#1841 draft_binding_cli_rows: a bound run whose latest revision cannot be proven landed renders latest_revision_landed=unestablished" \
    "bound=$DB_SB tier=worktree-root non_bound_root=none latest_revision_landed=unestablished" \
    "$(sed -n 1p "$DB_SB/.dr-unlanded" 2>/dev/null)"
  # #1841: once an overwrite failure is recorded for the latest ordinal, non-landing is
  # PROVEN -> `no` (the bound-branch `no` string a `yes`-hardcoding regression would break).
  assert_eq "#1841 draft_binding_cli_rows: a bound run with a recorded write-failure for the latest ordinal renders latest_revision_landed=no" \
    "bound=$DB_SB tier=worktree-root non_bound_root=none latest_revision_landed=no" \
    "$(sed -n 1p "$DB_SB/.dr-failed" 2>/dev/null)"
  # #1841 AC1: query-draft-binding --help enumerates the three landed tokens.
  assert_eq "#1841 draft_binding_cli_rows: query-draft-binding --help enumerates the yes/no/unestablished landed tokens" \
    "1" "$(grep -c 'yes/no/unestablished' "$DB_SB/.dbh-help" 2>/dev/null)"
  # S#7: an unbound run's readers fall back to the caller `--draft-file` (emit-body emits it).
  assert_eq "#562 draft_binding_cli_rows: an UNBOUND run's readers fall back to the caller --draft-file (S#7)" \
    "1" "$(grep -c '^UNBOUND BODY$' "$DB_SB/.du-body" 2>/dev/null)"
  # The real-worktree row runs only when `git worktree add` is available on the host.
  # `TMP_`-named because the haystack is this run's captured CLI output, not repository
  # source — the name is how pin-corpus-lint.py's runtime-scratch carve-out is declared,
  # so the grep below is read as the executable assertion it is rather than as a
  # source-presence pin. (In lib/test/run.sh the site was diff-unchanged and so never
  # reached that classifier; moving it here is what first put the question.)
  TMP_DB_WT="$DB_SB/.db-wt"
  if [ -s "$TMP_DB_WT" ]; then
    assert_eq "#562 draft_binding_cli_rows: a REAL linked worktree binds its own toplevel and the query round-trips" \
      "yes" "$(grep -qF 'tier=worktree-root' "$TMP_DB_WT" && echo yes || echo no)"
  fi
  git -C "$DB_SB" worktree remove -f ../wt562 > /dev/null 2>&1 || true
  rm -rf "$DB_SB" "$DB_SB/../wt562"
fi

# ────────────────────────────────────────────────────────────────────────────
# issue #569: the record-dispatch file-arm --write-path cross-check. When a run has bound a
# canonical-draft root and the skill reports its landed write path, the tool cross-checks
# that path against `<bound-root>/.prflow/tmp/issue-draft-<slug>.md` (the path it derives
# from the recorded binding) and fails closed with `write-path-mismatch` on divergence. The
# check is additive: an unbound run and a bound run that omits --write-path both proceed — but
# a present-but-EMPTY --write-path is an unestablished report, refused as `write-path-empty`
# rather than collapsed onto the omitted case. The check is scoped inside the file arm.
WP_SB="$(git_sandbox '#569 write_path_crosscheck_rows')"
if [ -d "$WP_SB" ]; then
  WP_SB="$(cd "$WP_SB" && pwd -P)"
  (
    cd "$WP_SB" || exit 1
    git init -q .
    mkdir -p .prflow/tmp
    printf '# T\n\nB\n' > d.md
    # A bound run: the matching write-path is accepted; a drifted one is refused.
    N="$(python3 "$IAS" init wp | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-draft-binding wp --nonce "$N" --path "$WP_SB" --tier worktree-root > /dev/null
    ias_stage wp "$N" d.md
    python3 "$IAS" record-offer wp --nonce "$N" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery wp --nonce "$N" --round 1 --arm file \
      --write-path "$WP_SB/.prflow/tmp/issue-draft-wp.md" --draft-file d.md > .wp-match 2>&1
    printf '%s' "$?" > .wp-match-rc
    # A NEW run (its own binding at the same root; a drifted write path, round 1) is refused.
    # Bindings are per-slug and immutable — wp2 records its own, it does not share wp's. The
    # bound canonical file for slug wp2 is $WP_SB/.prflow/tmp/issue-draft-wp2.md; report a
    # divergent /elsewhere path and expect the named breadcrumb + non-zero exit.
    N2="$(python3 "$IAS" init wp2 | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-draft-binding wp2 --nonce "$N2" --path "$WP_SB" --tier worktree-root > /dev/null
    ias_stage wp2 "$N2" d.md
    python3 "$IAS" record-offer wp2 --nonce "$N2" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery wp2 --nonce "$N2" --round 1 --arm file \
      --write-path /elsewhere/.prflow/tmp/issue-draft-wp2.md --draft-file d.md \
      > /dev/null 2> .wp-mismatch; printf '%s' "$?" > .wp-mismatch-rc
    # A bound run that OMITS --write-path proceeds unchanged (the cross-check is additive).
    N3="$(python3 "$IAS" init wp3 | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-draft-binding wp3 --nonce "$N3" --path "$WP_SB" --tier worktree-root > /dev/null
    ias_stage wp3 "$N3" d.md
    python3 "$IAS" record-offer wp3 --nonce "$N3" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery wp3 --nonce "$N3" --round 1 --arm file \
      --draft-file d.md > /dev/null 2>&1; printf '%s' "$?" > .wp-nowp-rc
    # An UNBOUND run's file arm still dispatches (the binding-required half is deferred); the
    # cross-check is scoped to a bound run, so no binding means no cross-check.
    N4="$(python3 "$IAS" init wp4 | sed -n '1s/nonce=//p')"
    ias_stage wp4 "$N4" d.md
    python3 "$IAS" record-offer wp4 --nonce "$N4" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery wp4 --nonce "$N4" --round 1 --arm file \
      --write-path /any/where.md --draft-file d.md > /dev/null 2>&1; printf '%s' "$?" > .wp-unbound-rc
    # An EMPTY --write-path is an unestablished report, NOT an opt-out: a truthiness test would
    # collapse it onto "caller omitted the flag" and silently disarm the cross-check on exactly
    # the drift it exists to catch (the skill composes this value in shell, so an unresolved
    # root yields ""). It is refused by name, distinctly from the omitted case above.
    N5="$(python3 "$IAS" init wp5 | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-draft-binding wp5 --nonce "$N5" --path "$WP_SB" --tier main-root > /dev/null
    ias_stage wp5 "$N5" d.md
    python3 "$IAS" record-offer wp5 --nonce "$N5" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery wp5 --nonce "$N5" --round 1 --arm file \
      --write-path "" --draft-file d.md > /dev/null 2> .wp-empty; printf '%s' "$?" > .wp-empty-rc
    # ARM ORDER, not just the two arms: the empty refusal sits ABOVE the binding guard, so it
    # fires on an UNBOUND run too. Without this row, scoping the empty check under the binding
    # guard keeps every other row green while an unbound run with --write-path "" flips from
    # refused to accepted — the unestablished report silently proceeding. (An empty value
    # reaches the tool from a caller that composes the path from a shell-resolved root; the
    # shipped skill substitutes an already-resolved literal, so this is defense in depth.)
    N8="$(python3 "$IAS" init wp8 | sed -n '1s/nonce=//p')"
    ias_stage wp8 "$N8" d.md
    python3 "$IAS" record-offer wp8 --nonce "$N8" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery wp8 --nonce "$N8" --round 1 --arm file \
      --write-path "" --draft-file d.md > /dev/null 2> .wp-empty-unbound
    printf '%s' "$?" > .wp-empty-unbound-rc
    # WHITESPACE-only is empty too: the guard is `.strip()`-based, so a "simplification" to a
    # bare falsiness test (`not args.write_path`) would keep every other row green while an
    # unbound run with "   " flips from refused to accepted.
    N9="$(python3 "$IAS" init wp9 | sed -n '1s/nonce=//p')"
    ias_stage wp9 "$N9" d.md
    python3 "$IAS" record-offer wp9 --nonce "$N9" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery wp9 --nonce "$N9" --round 1 --arm file \
      --write-path "   " --draft-file d.md > /dev/null 2> .wp-ws; printf '%s' "$?" > .wp-ws-rc
    # The mismatch rows above diverge the ROOT. Cover the other half of _bound_draft_file's
    # join: the correct bound root with a drifted <slug> — the compacted-context shape where a
    # run reuses a prior draft's slug — must also be refused.
    NA="$(python3 "$IAS" init wpa | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-draft-binding wpa --nonce "$NA" --path "$WP_SB" --tier main-root > /dev/null
    ias_stage wpa "$NA" d.md
    python3 "$IAS" record-offer wpa --nonce "$NA" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery wpa --nonce "$NA" --round 1 --arm file \
      --write-path "$WP_SB/.prflow/tmp/issue-draft-otherslug.md" --draft-file d.md \
      > /dev/null 2> .wp-slug; printf '%s' "$?" > .wp-slug-rc
    # The shipped skill binds --tier main-root (tier-2/tier-3 selection is the deferred half),
    # so pin the tier the production path actually uses, not only worktree-root: a matching
    # write-path under a main-root binding is accepted.
    N6="$(python3 "$IAS" init wp6 | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-draft-binding wp6 --nonce "$N6" --path "$WP_SB" --tier main-root > /dev/null
    ias_stage wp6 "$N6" d.md
    python3 "$IAS" record-offer wp6 --nonce "$N6" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery wp6 --nonce "$N6" --round 1 --arm file \
      --write-path "$WP_SB/.prflow/tmp/issue-draft-wp6.md" --draft-file d.md > /dev/null 2>&1
    printf '%s' "$?" > .wp-mainroot-rc
    # The cross-check is deliberately scoped INSIDE the file arm: an embed-arm dispatch ignores
    # --write-path entirely. Pin that scoping so a later refactor that HOISTS the check out of
    # the file-arm branch cannot change behavior with the suite green. (A refactor that narrows
    # or removes the check is caught by the .wp-mismatch row, not by this one.)
    N7="$(python3 "$IAS" init wp7 | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-draft-binding wp7 --nonce "$N7" --path "$WP_SB" --tier main-root > /dev/null
    python3 "$IAS" record-offer wp7 --nonce "$N7" --accepted > /dev/null
    printf '# T\n\nB\n' | python3 "$IAS" record-dispatch --kind discovery wp7 --nonce "$N7" --round 1 --arm embed \
      --marker write-failed --write-path /totally/bogus.md > /dev/null 2>&1
    printf '%s' "$?" > .wp-embed-rc
  )
  assert_eq "#569 write_path_crosscheck_rows: a matching write-path is accepted (exit 0)" \
    "0" "$(sed -n 1p "$WP_SB/.wp-match-rc" 2>/dev/null)"
  assert_eq "#569 write_path_crosscheck_rows: a drifted write-path is refused (exit non-zero)" \
    "1" "$(cat "$WP_SB/.wp-mismatch-rc" 2>/dev/null)"
  assert_eq "#569 write_path_crosscheck_rows: ... named by the write-path-mismatch breadcrumb" \
    "1" "$(grep -c 'write-path-mismatch' "$WP_SB/.wp-mismatch" 2>/dev/null)"
  assert_eq "#569 write_path_crosscheck_rows: a bound run that omits --write-path proceeds (cross-check is additive)" \
    "0" "$(sed -n 1p "$WP_SB/.wp-nowp-rc" 2>/dev/null)"
  assert_eq "#569 write_path_crosscheck_rows: an unbound file-arm dispatch still proceeds (binding-required half deferred)" \
    "0" "$(sed -n 1p "$WP_SB/.wp-unbound-rc" 2>/dev/null)"
  assert_eq "#569 write_path_crosscheck_rows: an EMPTY --write-path is refused, not read as an opt-out" \
    "1" "$(cat "$WP_SB/.wp-empty-rc" 2>/dev/null)"
  assert_eq "#569 write_path_crosscheck_rows: ... named by the write-path-empty breadcrumb" \
    "1" "$(grep -c 'write-path-empty' "$WP_SB/.wp-empty" 2>/dev/null)"
  assert_eq "#569 write_path_crosscheck_rows: the EMPTY refusal is binding-INDEPENDENT (unbound run refused too)" \
    "1" "$(cat "$WP_SB/.wp-empty-unbound-rc" 2>/dev/null)"
  assert_eq "#569 write_path_crosscheck_rows: ... the unbound empty refusal names write-path-empty" \
    "1" "$(grep -c 'write-path-empty' "$WP_SB/.wp-empty-unbound" 2>/dev/null)"
  assert_eq "#569 write_path_crosscheck_rows: a WHITESPACE-only --write-path is refused (strip-based, not bare falsiness)" \
    "1" "$(cat "$WP_SB/.wp-ws-rc" 2>/dev/null)"
  assert_eq "#569 write_path_crosscheck_rows: ... the whitespace refusal names write-path-empty" \
    "1" "$(grep -c 'write-path-empty' "$WP_SB/.wp-ws" 2>/dev/null)"
  assert_eq "#569 write_path_crosscheck_rows: right root + WRONG SLUG is refused (the other half of the join)" \
    "1" "$(cat "$WP_SB/.wp-slug-rc" 2>/dev/null)"
  assert_eq "#569 write_path_crosscheck_rows: ... the wrong-slug refusal names write-path-mismatch" \
    "1" "$(grep -c 'write-path-mismatch' "$WP_SB/.wp-slug" 2>/dev/null)"
  assert_eq "#569 write_path_crosscheck_rows: the shipped main-root tier is covered (matching path accepted)" \
    "0" "$(sed -n 1p "$WP_SB/.wp-mainroot-rc" 2>/dev/null)"
  assert_eq "#569 write_path_crosscheck_rows: an embed-arm dispatch ignores --write-path (check is file-arm scoped)" \
    "0" "$(sed -n 1p "$WP_SB/.wp-embed-rc" 2>/dev/null)"
  rm -rf "$WP_SB"
fi

# ── issue #1040: write-serialization sentinel at the process boundary ──────────────
# The shell-level assertions on the section's process boundary — the exit code and stderr
# breadcrumb the orchestrator routes on — driven with sub-second DEVFLOW_IAS_* overrides so
# the section's timing behavior is exercised in milliseconds rather than at the shipped
# 30s/45s bounds. Contention is created deterministically (the test plants the sentinel
# itself), never by racing two writers.
SL_SB="$(git_sandbox '#1040 cli_stale_break_exit_and_breadcrumb')"
(
  cd "$SL_SB" || exit 1
  mkdir -p .prflow/tmp
  # (1) stale break: plant a sentinel, age it past a sub-second stale_after_s, then run a
  #     real mutation. It must break the stale sentinel, proceed, and exit 0.
  printf '4242' > .prflow/tmp/issue-audit-state-s.json.lock
  sleep 0.2
  DEVFLOW_IAS_STALE_AFTER_S=0.05 DEVFLOW_IAS_ACQUIRE_WINDOW_S=0.5 \
    python3 "$IAS" init s > .sl-out 2> .sl-err
  printf '%s' "$?" > .sl-rc
  # (2) contention refusal: a FRESH sentinel with INVERTED bounds (window < stale) is never
  #     broken, so acquisition exhausts the window → exit non-zero, no state persisted, and
  #     the could-not-persist breadcrumb (the routing class the skill already carries).
  printf '9999' > .prflow/tmp/issue-audit-state-s3.json.lock
  DEVFLOW_IAS_ACQUIRE_WINDOW_S=0.2 DEVFLOW_IAS_STALE_AFTER_S=30 \
    python3 "$IAS" init s3 > .sl3-out 2> .sl3-err
  printf '%s' "$?" > .sl3-rc
  # the refused mutation left no state file for s3
  [ -f .prflow/tmp/issue-audit-state-s3.json ] && printf 'yes' > .sl3-state || printf 'no' > .sl3-state
) || true
assert_eq "#1040 cli_stale_break_exit_and_breadcrumb: the mutation breaks the stale sentinel and exits 0" \
  "0" "$(cat "$SL_SB/.sl-rc" 2>/dev/null)"
assert_eq "#1040 cli_stale_break_exit_and_breadcrumb: stderr carries the stale-break breadcrumb" \
  "1" "$(grep -c 'broke a stale audit-state sentinel' "$SL_SB/.sl-err" 2>/dev/null)"
assert_eq "#1040 cli_stale_break_exit_and_breadcrumb: the breadcrumb names the recorded pid" \
  "1" "$(grep -c '4242' "$SL_SB/.sl-err" 2>/dev/null)"
assert_eq "#1040 cli_contention_refusal: inverted bounds over a fresh sentinel exit non-zero (1)" \
  "1" "$(cat "$SL_SB/.sl3-rc" 2>/dev/null)"
assert_eq "#1040 cli_contention_refusal: the refusal names could-not-persist-state" \
  "1" "$(grep -c 'could not persist state' "$SL_SB/.sl3-err" 2>/dev/null)"
assert_eq "#1040 cli_contention_refusal: the refused mutation persisted no state file" \
  "no" "$(cat "$SL_SB/.sl3-state" 2>/dev/null)"
rm -rf "$SL_SB"

# readers_are_not_serialized (process boundary): a read-only subcommand acquires no
# sentinel, so a query-* invoked WHILE a sentinel is held for the same slug still exits 0
# (the AC: "a query-* invocation issued while a sentinel is held exits 0 with its decided
# answer line"). Plant a fresh sentinel and confirm query-nonce (read-only) is unaffected.
RO_SB="$(git_sandbox '#1040 readers_are_not_serialized_while_held')"
(
  cd "$RO_SB" || exit 1
  python3 "$IAS" init s >/dev/null 2>&1
  mkdir -p .prflow/tmp
  printf '4242' > .prflow/tmp/issue-audit-state-s.json.lock
  python3 "$IAS" query-nonce s > .ro-out 2> .ro-err
  printf '%s' "$?" > .ro-rc
) || true
assert_eq "#1040 readers_are_not_serialized: query-nonce exits 0 while a sentinel is held" \
  "0" "$(cat "$RO_SB/.ro-rc" 2>/dev/null)"
assert_eq "#1040 readers_are_not_serialized: the held sentinel is left untouched by the reader" \
  "1" "$( [ -f "$RO_SB/.prflow/tmp/issue-audit-state-s.json.lock" ] && echo 1 || echo 0 )"
rm -rf "$RO_SB"

# zero_round_decline_rows (#1751) — a run whose user declines every audit offer files its
# issue unaudited. Drives the declined-run lifecycle end to end at the CLI: the first-round
# funding refusal and the election that admits it (AC1), the user-round ceiling (AC5), the
# bound zero-round decline that grounds eligibility with its decline-bound creation epoch +
# attestation + emit-body + zero-round summary (AC10/AC11/AC12), the revision that
# invalidates a bound decline (AC10), and the unbound sandbox decline (AC10).
ZD_SB="$(git_sandbox '#1751 zero_round_decline_rows')"
if [ -d "$ZD_SB" ]; then
  (
    cd "$ZD_SB" || exit 1
    git init -q . 2>/dev/null
    mkdir -p .prflow/tmp
    printf '# Draft title\n\nAUDITED body line.\n' > draft.md

    # AC1: a first-round dispatch with NO election refuses (not funded); an election admits it.
    N="$(python3 "$IAS" init zd | sed -n '1s/nonce=//p')"
    ias_stage zd "$N" draft.md
    python3 "$IAS" record-dispatch --kind discovery zd --nonce "$N" --round 1 --arm file \
      --draft-file draft.md > /dev/null 2> .zd-unfunded; printf '%s' "$?" > .zd-unfunded-rc
    python3 "$IAS" record-offer zd --nonce "$N" --accepted > /dev/null
    python3 "$IAS" record-dispatch --kind discovery zd --nonce "$N" --round 1 --arm file \
      --draft-file draft.md > /dev/null 2>&1; printf '%s' "$?" > .zd-funded-rc

    # AC5: the user-chosen-round ceiling is three — a fourth accepted offer refuses.
    NC="$(python3 "$IAS" init zdcap | sed -n '1s/nonce=//p')"
    for _i in 1 2 3; do python3 "$IAS" record-offer zdcap --nonce "$NC" --accepted > /dev/null 2>&1; done
    python3 "$IAS" record-offer zdcap --nonce "$NC" --accepted > /dev/null 2> .zd-cap; printf '%s' "$?" > .zd-cap-rc

    # AC10/AC11/AC12: a bound zero-round decline grounds eligibility, binds a decline-bound
    # creation epoch, emit-body emits, a faithfully-posted body attests match, and the
    # summary reports rounds_run=0 with the decline.
    ND="$(python3 "$IAS" init zdd | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-override zdd --nonce "$ND" --kind user-decline --surface step4-offer \
      --draft-file draft.md > /dev/null 2>&1
    python3 "$IAS" query-eligibility zdd --nonce "$ND" --mode approve --draft-file draft.md > .zd-elig 2>&1
    python3 "$IAS" record-creation-epoch zdd --nonce "$ND" --round 0 --draft-file draft.md > .zd-epoch 2>&1
    python3 "$IAS" emit-body zdd --nonce "$ND" --draft-file draft.md > /dev/null 2> /dev/null
    printf '%s' "$?" > .zd-body-rc
    python3 "$IAS" emit-body zdd --nonce "$ND" --draft-file draft.md 2>/dev/null \
      | python3 "$IAS" record-creation-attestation zdd --nonce "$ND" > .zd-attest 2>&1
    python3 "$IAS" query-summary zdd --nonce "$ND" --draft-file draft.md > .zd-summary 2>&1

    # AC10 (invalidation): a bound decline stops grounding eligibility once a revision changes the bytes.
    NR="$(python3 "$IAS" init zdr | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-override zdr --nonce "$NR" --kind user-decline --surface step4-offer \
      --draft-file draft.md > /dev/null 2>&1
    python3 "$IAS" query-eligibility zdr --nonce "$NR" --mode approve --draft-file draft.md > .zd-elig-pre 2>&1
    printf '# Draft title\n\nREVISED body.\n' > revised.md
    python3 "$IAS" record-revision zdr --nonce "$NR" --after-round 0 > /dev/null 2>&1
    python3 "$IAS" query-eligibility zdr --nonce "$NR" --mode approve --draft-file revised.md > .zd-elig-post 2>&1
    # Isolate the ORDINAL invalidation mechanism (not the digest): query the ORIGINAL bound
    # bytes after the revision — the decline's digest still matches draft.md, so only the
    # bumped revision ordinal (recorded_at_ordinal != now) can drop the decline. eligible=no.
    python3 "$IAS" query-eligibility zdr --nonce "$NR" --mode approve --draft-file draft.md > .zd-elig-post-orig 2>&1

    # AC10 negative guard: a decline-bound creation epoch with NO --draft-file refuses (it
    # cannot recompute the body-only digest, and must never inherit the override's whole-file
    # digest). A fresh run, since zdd's epoch is already attestation-frozen above.
    NN="$(python3 "$IAS" init zdn | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-override zdn --nonce "$NN" --kind user-decline --surface step4-offer \
      --draft-file draft.md > /dev/null 2>&1
    python3 "$IAS" record-creation-epoch zdn --nonce "$NN" --round 0 \
      > /dev/null 2> .zd-epoch-nodraft; printf '%s' "$?" > .zd-epoch-nodraft-rc

    # AC11 discriminator: the decline-bound epoch's digest is BODY-ONLY, not whole-file.
    # Bind two fresh runs to drafts sharing a body but differing in TITLE — a whole-file
    # digest differs across them, a body-only digest is equal. Equality is the discriminator.
    printf '# A DIFFERENT TITLE ENTIRELY\n\nAUDITED body line.\n' > retitled.md
    NT="$(python3 "$IAS" init zdt | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-override zdt --nonce "$NT" --kind user-decline --surface step4-offer \
      --draft-file retitled.md > /dev/null 2>&1
    python3 "$IAS" record-creation-epoch zdt --nonce "$NT" --round 0 --draft-file retitled.md > .zd-epoch-retitled 2>&1
    # Positive control: the two drafts really are distinct FILES, so the equality above is a
    # body-only match and not two reads of one path.
    cmp -s draft.md retitled.md; printf '%s' "$?" > .zd-drafts-differ-rc
    # Compare here, not in the assertion: an extractor absent from PATH would yield two
    # empty strings and pass an equality assertion vacuously. Requiring non-empty fails closed.
    ZD_D1="$(sed -n 's/.*body_digest=//p' .zd-epoch)"
    ZD_D2="$(sed -n 's/.*body_digest=//p' .zd-epoch-retitled)"
    if [ -n "$ZD_D1" ] && [ "$ZD_D1" = "$ZD_D2" ]; then printf '1' > .zd-body-only-rc
    else printf '0' > .zd-body-only-rc; fi

    # AC11 negative guard: the decline arm's attestation-frozen refusal. zdd attested above,
    # so re-binding its creation epoch through the SAME decline arm must refuse.
    python3 "$IAS" record-creation-epoch zdd --nonce "$ND" --round 0 --draft-file draft.md \
      > /dev/null 2> .zd-epoch-refrozen; printf '%s' "$?" > .zd-epoch-refrozen-rc

    # AC10 (sandbox unbound): a decline recorded where NO canonical file exists is accepted
    # unbound and still reaches eligible=yes when queried with no digest.
    NS="$(python3 "$IAS" init zds | sed -n '1s/nonce=//p')"
    python3 "$IAS" record-override zds --nonce "$NS" --kind user-decline --surface step4-offer > /dev/null 2>&1
    python3 "$IAS" query-eligibility zds --nonce "$NS" --mode approve > .zd-elig-sandbox 2>&1
  )
  assert_eq "#1751 zero_round_decline_rows: a first-round dispatch with no election refuses (not funded)" \
    "1:1" "$(cat "$ZD_SB/.zd-unfunded-rc" 2>/dev/null):$(grep -c 'is not funded' "$ZD_SB/.zd-unfunded" 2>/dev/null)"
  assert_eq "#1751 zero_round_decline_rows: a recorded election admits the same first-round dispatch" \
    "0" "$(cat "$ZD_SB/.zd-funded-rc" 2>/dev/null)"
  assert_eq "#1751 zero_round_decline_rows: the user-chosen-round ceiling is three (a fourth offer refuses)" \
    "1" "$(cat "$ZD_SB/.zd-cap-rc" 2>/dev/null)"
  assert_eq "#1751 zero_round_decline_rows: a bound zero-round decline grounds eligibility on the override ground" \
    "1" "$(grep -c 'eligible=yes ground=override' "$ZD_SB/.zd-elig" 2>/dev/null)"
  assert_eq "#1751 zero_round_decline_rows: emit-body emits the declined run's body" \
    "0" "$(cat "$ZD_SB/.zd-body-rc" 2>/dev/null)"
  assert_eq "#1751 zero_round_decline_rows: a faithfully-posted body attests match against the decline-bound epoch" \
    "attestation=match" "$(sed -n 1p "$ZD_SB/.zd-attest" 2>/dev/null)"
  assert_eq "#1751 zero_round_decline_rows: the summary reports rounds_run=0 on a declined run" \
    "1" "$(grep -v '^summary-block ' "$ZD_SB/.zd-summary" 2>/dev/null | grep -c 'rounds_run=0')"
  assert_eq "#1751 zero_round_decline_rows: ... and the summary records the user decline" \
    "1" "$(grep -v '^summary-block ' "$ZD_SB/.zd-summary" 2>/dev/null | grep -c 'user_declined=yes')"
  assert_eq "#1751 zero_round_decline_rows: a bound zero-round decline grounds eligibility before a revision" \
    "1" "$(grep -c 'eligible=yes' "$ZD_SB/.zd-elig-pre" 2>/dev/null)"
  assert_eq "#1751 zero_round_decline_rows: a recorded revision stops the bound decline grounding eligibility (positive eligible=no control, not a vacuous absence)" \
    "1" "$(grep -c 'eligible=no' "$ZD_SB/.zd-elig-post" 2>/dev/null)"
  assert_eq "#1751 zero_round_decline_rows: ... and the ORDINAL bump alone drops it — querying the original bound bytes after the revision still answers eligible=no" \
    "1" "$(grep -c 'eligible=no' "$ZD_SB/.zd-elig-post-orig" 2>/dev/null)"
  assert_eq "#1751 zero_round_decline_rows: a decline-bound creation epoch with no --draft-file refuses (cannot recompute the body-only digest)" \
    "1:1" "$(cat "$ZD_SB/.zd-epoch-nodraft-rc" 2>/dev/null):$(grep -c 'must recompute the body-only digest' "$ZD_SB/.zd-epoch-nodraft" 2>/dev/null)"
  assert_eq "#1751 zero_round_decline_rows: the decline-bound epoch digest is BODY-ONLY — two drafts sharing a body but not a title bind the SAME digest (a whole-file digest would differ)" \
    "1" "$(cat "$ZD_SB/.zd-body-only-rc" 2>/dev/null)"
  assert_eq "#1751 zero_round_decline_rows: ... and the two drafts are genuinely distinct files (positive control against a vacuous self-comparison)" \
    "1" "$(cat "$ZD_SB/.zd-drafts-differ-rc" 2>/dev/null)"
  assert_eq "#1751 zero_round_decline_rows: the decline arm refuses to re-bind a creation epoch past a recorded attestation (tamper evidence is forward-only)" \
    "1:1" "$(cat "$ZD_SB/.zd-epoch-refrozen-rc" 2>/dev/null):$(grep -c 'an attestation is already recorded' "$ZD_SB/.zd-epoch-refrozen" 2>/dev/null)"
  assert_eq "#1751 zero_round_decline_rows: an unbound sandbox decline reaches eligible=yes with no digest supplied" \
    "1" "$(grep -c 'eligible=yes' "$ZD_SB/.zd-elig-sandbox" 2>/dev/null)"
  rm -rf "$ZD_SB"
fi

# issue #1803 — the three-part output contract (decided line first, summary-block, next_call=
# last) and the batched finding-evidence records-file form. Do not reorder the three parts: the
# audit references dropped the standalone read-backs whose answers the block now carries.
SBK_SB="$(git_sandbox '#1803 summary_block_and_batched_evidence')"
if [ -d "$SBK_SB" ]; then
  (
    cd "$SBK_SB" || exit 1
    mkdir -p .prflow/tmp
    # A mutation prints its decided line first, then the summary-block line, then next_call=.
    python3 "$IAS" init b1803 > .sbk-init 2>/dev/null
    NONCE="$(sed -n 's/^nonce=//p' .sbk-init | head -1)"
    # A state-defaulted read also carries the block between its decided line and next_call=.
    python3 "$IAS" query-summary b1803 --nonce "$NONCE" > .sbk-qs 2>/dev/null
    # An EXCLUDED subcommand (a multi-line read-back) prints NO summary-block line — the block
    # would otherwise forge an extra line on a machine-parsed read-back.
    python3 "$IAS" query-findings b1803 --nonce "$NONCE" > .sbk-qf 2>/dev/null
    # Batched finding-evidence: one call records a whole round's evidence, one decided line
    # per finding each with its own completeness verdict, then the block and next_call.
    printf '%s\n' '[{"finding_id":1,"locator":"a.py:1","command":"c","observed":"o","baseline_revision":"r"},{"finding_id":2,"locator":"b.py:2"}]' > .prflow/tmp/fe.json
    python3 "$IAS" record-finding-evidence b1803 --nonce "$NONCE" --round 0 --finding-evidence-records-file .prflow/tmp/fe.json > .sbk-batch 2>/dev/null
    printf '%s' "$?" > .sbk-batch-rc
    # A duplicate finding id in the batch is refused before any save.
    printf '%s\n' '[{"finding_id":3,"locator":"a"},{"finding_id":3,"locator":"b"}]' > .prflow/tmp/dup.json
    python3 "$IAS" record-finding-evidence b1803 --nonce "$NONCE" --round 0 --finding-evidence-records-file .prflow/tmp/dup.json > .sbk-dup 2> .sbk-dup-err
    printf '%s' "$?" > .sbk-dup-rc
    # The batched form and the per-finding flags are mutually exclusive.
    python3 "$IAS" record-finding-evidence b1803 --nonce "$NONCE" --round 0 --finding-id 5 --finding-evidence-records-file .prflow/tmp/fe.json > /dev/null 2> .sbk-mixed-err
    printf '%s' "$?" > .sbk-mixed-rc
    # A single-finding call naming no selector is refused.
    python3 "$IAS" record-finding-evidence b1803 --nonce "$NONCE" --round 0 > /dev/null 2> .sbk-nosel-err
    printf '%s' "$?" > .sbk-nosel-rc
    # Do not narrow the mutual-exclusion scan to --finding-id: every per-finding flag is a
    # mixed call, and the breadcrumb's singular/plural branch has its own wording.
    python3 "$IAS" record-finding-evidence b1803 --nonce "$NONCE" --round 0 --locator z.py:9 --finding-evidence-records-file .prflow/tmp/fe.json > /dev/null 2> .sbk-mixed-loc-err
    printf '%s' "$?" > .sbk-mixed-loc-rc
    python3 "$IAS" record-finding-evidence b1803 --nonce "$NONCE" --round 0 --locator z.py:9 --command c9 --finding-evidence-records-file .prflow/tmp/fe.json > /dev/null 2> .sbk-mixed-two-err
    printf '%s' "$?" > .sbk-mixed-two-rc
  ) || true
  assert_eq "#1803 summary_block: a mutation prints its decided line first" \
    "1" "$(sed -n 1p "$SBK_SB/.sbk-init" 2>/dev/null | grep -c '^nonce=')"
  assert_eq "#1803 summary_block: the summary-block line prints between the decided line and next_call=" \
    "1" "$(sed -n 2p "$SBK_SB/.sbk-init" 2>/dev/null | grep -c '^summary-block ')"
  assert_eq "#1803 summary_block: next_call= stays the final stdout line" \
    "1" "$(tail -n 1 "$SBK_SB/.sbk-init" 2>/dev/null | grep -c '^next_call=')"
  assert_eq "#1803 summary_block: the block carries the compact subset (state first, attestation last)" \
    "1" "$(grep -c '^summary-block state=ok .* attestation=none$' "$SBK_SB/.sbk-init" 2>/dev/null)"
  assert_eq "#1803 summary_block: query-summary also carries a summary-block line" \
    "1" "$(sed -n 2p "$SBK_SB/.sbk-qs" 2>/dev/null | grep -c '^summary-block ')"
  assert_eq "#1803 summary_block: query-summary's decided line stays first (state=...)" \
    "1" "$(sed -n 1p "$SBK_SB/.sbk-qs" 2>/dev/null | grep -c '^state=')"
  assert_eq "#1803 batched_finding_evidence: the batch exits 0" \
    "0" "$(cat "$SBK_SB/.sbk-batch-rc" 2>/dev/null)"
  assert_eq "#1803 batched_finding_evidence: finding 1 records complete" \
    "1" "$(grep -c '^finding=0:1 completeness=complete missing=none$' "$SBK_SB/.sbk-batch" 2>/dev/null)"
  assert_eq "#1803 batched_finding_evidence: finding 2 records incomplete with its own missing set" \
    "1" "$(grep -c '^finding=0:2 completeness=incomplete missing=command,observed,baseline_revision$' "$SBK_SB/.sbk-batch" 2>/dev/null)"
  assert_eq "#1803 batched_finding_evidence: the batch's first stdout line is a decided finding line" \
    "1" "$(sed -n 1p "$SBK_SB/.sbk-batch" 2>/dev/null | grep -c '^finding=0:1 ')"
  assert_eq "#1803 batched_finding_evidence: a duplicate finding id is refused non-zero" \
    "1" "$(cat "$SBK_SB/.sbk-dup-rc" 2>/dev/null)"
  assert_eq "#1803 batched_finding_evidence: ... naming the duplicate-id breadcrumb" \
    "1" "$(grep -c 'finding-evidence-records-duplicate-id' "$SBK_SB/.sbk-dup-err" 2>/dev/null)"
  assert_eq "#1803 batched_finding_evidence: the batched form and per-finding flags are mutually exclusive" \
    "1:1" "$(cat "$SBK_SB/.sbk-mixed-rc" 2>/dev/null):$(grep -c 'finding-evidence-records-mixed-form' "$SBK_SB/.sbk-mixed-err" 2>/dev/null)"
  assert_eq "#1803 batched_finding_evidence: a single-finding call naming no selector is refused" \
    "1:1" "$(cat "$SBK_SB/.sbk-nosel-rc" 2>/dev/null):$(grep -c 'finding-evidence-missing-finding-selector' "$SBK_SB/.sbk-nosel-err" 2>/dev/null)"
  assert_eq "#1803 batched_finding_evidence: a per-finding flag OTHER than --finding-id is a mixed call too" \
    "1:1" "$(cat "$SBK_SB/.sbk-mixed-loc-rc" 2>/dev/null):$(grep -c 'finding-evidence-records-mixed-form' "$SBK_SB/.sbk-mixed-loc-err" 2>/dev/null)"
  assert_eq "#1803 batched_finding_evidence: ... and the singular branch names that one flag" \
    "1" "$(grep -c -- '--locator was also passed' "$SBK_SB/.sbk-mixed-loc-err" 2>/dev/null)"
  assert_eq "#1803 batched_finding_evidence: two per-finding flags take the PLURAL breadcrumb branch, naming both" \
    "1" "$(grep -c -- '--locator,--command were also passed' "$SBK_SB/.sbk-mixed-two-err" 2>/dev/null)"
  # The batched form (multiple decided finding lines) still exhibits the full three-part
  # contract — a summary-block line then next_call= last, after the N decided lines.
  assert_eq "#1803 batched_finding_evidence: the batch prints a summary-block line after its decided lines" \
    "1" "$(grep -c '^summary-block ' "$SBK_SB/.sbk-batch" 2>/dev/null)"
  assert_eq "#1803 batched_finding_evidence: next_call= stays the batch's final stdout line" \
    "1" "$(tail -n 1 "$SBK_SB/.sbk-batch" 2>/dev/null | grep -c '^next_call=')"
  # An excluded (multi-line read-back) subcommand prints NO summary-block line.
  assert_eq "#1803 summary_block: an excluded read-back (query-findings) prints no summary-block line" \
    "0" "$(grep -c '^summary-block ' "$SBK_SB/.sbk-qf" 2>/dev/null)"
  rm -rf "$SBK_SB"
fi
