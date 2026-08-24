<!-- prflow:implement-ref phase=3 file=skills/implement/phases/phase-3-fix-loop.md start -->
<!-- prflow:implement-set phase=3 part=2 of=3 -->

## Phase 3: Review & Fix — the fix loop

### 3.3 Review & Fix

Snapshot this run's per-iteration workpad baseline first (before invoking `review-and-fix`). The observability backstop below decides whether *this* run wrote any `iter-*.json`; on the local/interactive tier `.prflow/tmp` persists across runs, so a whole-tree presence check would count a prior run's leftover and mask a genuine loss. Record the pre-existing set now so the post-return detector measures only what this run adds:
```bash
# Snapshot the pre-existing iter-*.json before driving review-and-fix inline, so the post-return
# detector measures whether THIS run wrote any per-iteration workpad — on the local/interactive
# tier .prflow/tmp persists across runs, so a leftover iter-*.json would satisfy a whole-tree
# presence check and MASK a genuine telemetry loss this run. Snapshot to a file because each
# phase bash block is a separate shell.
ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
# Check mkdir's own exit status so a failure names its root cause (permissions/read-only-fs/
# disk-full) here rather than surfacing only as the generic "snapshot file missing" degrade
# downstream.
if ! mkdir -p "$ROOT/.prflow/tmp" 2>/dev/null; then
  echo "::warning::phase-3.3: could not create $ROOT/.prflow/tmp (permissions/read-only-fs/disk-full?); pre-loop snapshot will be missing, degrading the no-inputs detector to whole-tree presence below" >&2
fi
# Portable enumeration (this prose block runs under the AGENT's shell — zsh/dash/sh — not a
# bash-shebanged .sh, so no bash-only glob-completion builtin, and the unquoted glob must survive zsh's
# default `nomatch`). The guard turns nomatch off under native zsh (no-op elsewhere: $ZSH_VERSION
# unset → `&&` short-circuits, `|| :` stays rc-0). `set --` captures the matched iter-*.json into
# "$@" (with nomatch off, an unmatched glob leaves $1 the literal pattern). `[ -e "$1" ]` gates
# the enumeration so the EMPTY-set case writes an EMPTY snapshot file — never the literal
# unmatched pattern — via the builtin `printf` (no external tool whose absence could fake output).
[ -n "${ZSH_VERSION:-}" ] && setopt nonomatch || :
set -- "$ROOT"/.prflow/tmp/review/*/*/iter-*.json
if [ -e "$1" ]; then printf '%s\n' "$@" | sort; fi
```
Consume the sorted listing from the tool result and author it to `$ROOT/.prflow/tmp/.phase33-iters-before` with the Write tool (an empty listing authors an empty file). Do not emit a shell redirect for this snapshot.

Invoke the Skill tool with `skill: review-and-fix` and `args: "<pr-number> --push-each-iteration --issue $ISSUE_NUMBER"`, while continuing to hold this orchestrator's `$ISSUE_NUMBER` in caller context. That caller-held value — not the public argument string — is the sole implement-origin signal the loop uses to bind its internal `progress_surface = workpad`; do not clear or reconstruct it at the invocation seam. `<pr-number>` is the draft PR number passed as a bare leading numeric token — the digits read from inside the brackets of the `draft PR number: [<n>]` line Phase 3.1 printed (passed without the brackets, so the token is bare) — and the issue number is likewise substituted as its literal digits. The bare leading token is what puts the loop in PR mode: this phase operates on the live draft PR created in 3.1, and only in PR mode does the shared engine apply the PR-specific branch-sync gate and Loop Exit's base-branch update Checkpoint 3; review progress itself stays on the issue workpad in both modes. Omit-the-token arm: when Phase 3.1's `draft PR number:` line printed empty brackets (`[]`), and when it did not print at all, omit the numeric token and pass `--push-each-iteration --issue $ISSUE_NUMBER` alone — the loop then runs in current-branch mode exactly as it did before this token existed. Record on the issue workpad which arm you took (the PR number passed, or that the token was omitted) with a workpad `--note`, so a compacted run's mode choice stays auditable. `--issue` remains load-bearing only for acceptance-criteria resolution; it does not select the progress surface. The `--push-each-iteration` flag is load-bearing here too: it propagates each fix iteration to the remote branch so its CI validates the converging state and progress survives a mid-loop crash, but it likewise does not select the progress surface. (Direct users of `/prflow:review-and-fix` omit the flag and the loop's fix commits stay local — though Loop Exit's `--persist` still pushes the `prflow-telemetry` branch regardless of the flag; see that skill's Input section for the flag's semantics.)

Stay on the instrumented loop — a cloud permission/sandbox denial is not license to leave it. This phase drives `review-and-fix` inline in your context. If you hit a `claude-code-action` permission or sandbox denial here — a piped/compound `.sh` invocation, a `$(...)` redirect target, or a shell `>` write into `.prflow/tmp` refused as "may only write to files in allowed working directories" — that denial is not the local-tier permission classifier, and is not license to abandon the instrumented loop and hand-run the review engine via direct `Agent` dispatch. On the cloud implement job `Skill`, `Agent`, `Write`, `efficiency-trace.sh`, `workpad.py`, and `config-get.sh` are all allowlisted, so the instrumented loop is navigable, not blocked. Whatever path the review runs, the per-iteration effectiveness record (`iter-<N>.json`) is a non-optional emit on every iteration, written with the Write tool (never a shell `>`/heredoc redirect the sandbox denies) — that is what keeps the effectiveness half of the telemetry recoverable even on a degraded, hand-run pass; and the emit is non-optional on every path, including a degraded one.

A denied `Skill` call is not the engine being unavailable — `Skill` is a loader, and the engine is a file in the tree. `review-and-fix` executes the review engine's `SKILL.md` Phases 0–4.3 verbatim; those files are in the checkout — resolve the engine directory by the ordered, repo-root-anchored candidate list `review-and-fix`'s `references/loop-control.md` Step 1 defines (the repo-root `skills/review` for a devflow-self checkout, then `.prflow/vendor/prflow/skills/review` and the superseded `.devflow/vendor/devflow/skills/review` for a consumer checkout), binding the bundle to whichever resolves first. If the `Skill` invocation is refused twice, apply the repo's own shape discipline (two denials of a shape → switch to a permitted alternative, never iterate variants): `Read` the engine from the tree, establish the root's completeness by Step 1's predicate — that statement is canonical; do not re-derive it here — and execute its phases inline. A root whose completeness could not be established takes this phase's Blocked path below, recording `--reflection "engine-root: incomplete — <that SKILL.md path>"` in place of that path's unresolved-Critical literal, which would otherwise mislabel the durable record. That is not "hand-running the review from memory" — it *is* the engine, from source. The only thing you may never substitute is a paraphrase: five agents dispatched from recollection, with no checklist generate/dedupe/verify, no Step 2.5 classification, no shadow pass, no deferrals manifest, no convergence criteria, is a different artifact wearing the label of a DevFlow review.

The emit is the only form any shipping code reads. `lib/efficiency-trace.sh` pins the `iter-*.json` field contract and `--persist` derives `.prflow/logs/efficiency/` from it; `lib/efficiency-trace.jq` derives `verification_posture` from its `checklist[]`; and `defect_signature` is the correlation key the review engine itself joins on — Phase 3.2's mechanical corroboration and the fix loop's iter-(N+1) prior-findings handoff both key on it. Your adjudication (the calibrated `severity`, the `fix_decision` and its reasoning, the `defect_signature`) is a judgment that exists only because you record it, so dropping the emit means no shipping consumer sees any of it, on either tier.

When you need a scratch or telemetry file under `.prflow/tmp`, author it with the Write tool, not a shell redirect; the pre-loop snapshot below is a shell-computed listing whose redirect may itself be refused — its failure does not abort the phase, though it degrades the no-inputs detector to whole-tree presence (which the detector's own `::warning::` surfaces on the run log, because on the persistent local tier a leftover `iter-*.json` can then mask a real loss); it is a degrade to note, not a hard blocker, and never a reason to leave the loop.

This runs the four-phase review engine in your context:
1. Verification checklist — generates and verifies every dependency interaction, test-mock alignment, data format assumption, and API contract claim against actual source code
2. Existing review agents — runs the first-party review agents (code-reviewer, silent-failure-hunter, comment-analyzer, type-design-analyzer, pr-test-analyzer) and the first-party `prflow:requesting-code-review` final-pass reviewer in parallel
3. Automatic fix loop — fixes findings using `prflow:receiving-code-review` principles, re-runs the engine, loops until APPROVE or the configured iteration cap (`prflow_review_and_fix.max_iterations`, default 5)

Follow the skill's instructions. It handles evaluation, fixing, testing, and re-review internally.

Observability-persistence backstop (after `review-and-fix` returns, before the verdict branches below). `review-and-fix`'s Loop Exit is what normally derives this run's effectiveness record (`.prflow/logs/efficiency/<slug>-<run-id>.json`) and durable workpad copy from its per-iteration `iter-*.json`. But this phase drives that loop inline in your context, so a dropped Loop Exit leaves those artifacts unpersisted and the run contributes nothing to `.prflow/logs/efficiency/`. So regardless of the verdict, first verify this run's observability artifacts were persisted and run the efficiency-trace persist backstop when they are missing; the backstop is idempotent (it never re-derives an existing record), so running it unconditionally is safe. **When the inline loop wrote no per-iteration workpad, `--persist` now first *synthesizes* a minimal iteration record from this run's fix commits** (`fix: address review findings (iteration N)` commits → the `ITER_SYNTH_EXPECTED_FIELDS` set in `lib/efficiency-trace.sh` (the effectiveness fields, plus `unrecoverable` provenance for the run-scoped evidence fields)), so the zero-workpad case is answered by synthesis, not only a reflection. The synthesized `iter-*.json` land under the same `.prflow/tmp/review/` tree, so the new-input detector below counts them as recovered inputs and does not fire the gap reflection. **Only when synthesis *also* finds nothing** — the loop wrote no workpad and synthesis recovered nothing (no unrecorded fix commit, a failed search — unresolvable base ref, a base ref left unestablished by a failed origin/<base> refresh, or a failed `git log` — failed writes, a discovery-mode skip: workpad-less run dirs ambiguous across slugs, or this dir not its slug's synthesis target, or an unsubstituted `<placeholder>` identity refused by either persist call; `--persist`'s warnings name which when a candidate dir was visited at all) — record a `dropped-failed` reflection naming the observability gap so the lost telemetry is visible rather than silently absent:
```bash
# Anchor on the repo root the SAME way efficiency-trace.sh does (git toplevel), so the "no
# inputs" detector below reads the exact .prflow/tmp/review tree --persist scans — a
# cwd-relative path could diverge from the wrapper and fire a false "telemetry lost" reflection
# or mask a real loss.
ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
BEFORE="$ROOT/.prflow/tmp/.phase33-iters-before"
if [ -f "$BEFORE" ]; then
  echo "phase-3.3: pre-loop iter-*.json snapshot present"
else
  echo "::warning::phase-3.3: pre-loop iter-*.json snapshot missing; author an empty snapshot with the Write tool before continuing" >&2
fi
```
If the tool result reports the snapshot missing, author an empty file at `$ROOT/.prflow/tmp/.phase33-iters-before` with the Write tool before continuing. The next shell step re-anchors the path and disables the comparison with a distinct warning if that Write did not produce the file, so an absent operand cannot masquerade as a telemetry-loss result.

```bash
ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
BEFORE="$ROOT/.prflow/tmp/.phase33-iters-before"
if [ -f "$BEFORE" ]; then
  BEFORE_READY=1
else
  BEFORE_READY=0
  echo "::warning::phase-3.3: pre-loop iter-*.json snapshot remains missing; no-inputs comparison disabled because comm cannot classify this run without its baseline" >&2
fi
# Idempotent Layer-3 persist: derives the effectiveness record and durable workpad copy
# from whatever iter-*.json this run left under .prflow/tmp/review/ and writes them to the
# long-lived orphan telemetry branch (default `prflow-telemetry`, key telemetry.branch) via
# git plumbing — it does NOT commit to this feature branch and never touches HEAD, the
# current branch, or the TRACKED working tree. Idempotent on that branch: the
# effectiveness record is presence-idempotent (a `git cat-file -e <ref>:<path>` probe skips a
# run already stored), the durable workpad copy re-writes identical bytes, and an unchanged
# tree makes no new branch commit; a full no-op if the inline loop wrote no per-iter workpad. Best-effort
# (always exits 0). Two calls, targeted FIRST: this orchestrator drove review-and-fix
# inline and holds the loop's <slug> and RUN_ID, and persisting its own run by explicit
# identity is immune to every discovery-mode skip (multi-slug ambiguity, not-latest
# ordering) AND to the lone-stale-foreign-dir shape, where discovery would misattribute
# this branch's fix commits to a leftover slug and the sha exclusion would lock the
# misattribution in while the new synthesized files suppressed the gap reflection. The
# argument-less discovery call then covers every OTHER leftover run dir on disk. If the
# slug/run-id are genuinely not held (the inline loop died before RUN_ID was computed),
# skip the targeted call with a --note recording that, and rely on discovery + the
# detector below as the loud floor — never substitute guessed values.
# On mktemp failure, degrade to /dev/null rather than aborting — the capture becomes a
# no-op (stderr is discarded, so the record-write-failure grep below can never match), but
# --persist's own best-effort exit-0 contract is preserved. Track the degrade explicitly in
# $PERSIST_ERR_IS_DEVNULL (not by re-testing the string later) so (a) the cleanup at the
# bottom of this block never runs `rm -f` on the LITERAL PATH `/dev/null` — under a root
# shell with a writable /dev this would delete the device node itself, breaking every other
# command in the environment that redirects to /dev/null — and (b) the degrade gets the same
# distinct ::warning:: breadcrumb discipline as the sibling $BEFORE-missing degrade below,
# instead of silently no-opping the record-write-failure detector for this run.
if PERSIST_ERR=$(mktemp 2>/dev/null); then
  PERSIST_ERR_IS_DEVNULL=0
else
  PERSIST_ERR=/dev/null
  PERSIST_ERR_IS_DEVNULL=1
  echo "::warning::phase-3.3: could not allocate a temp file for --persist's stderr (mktemp failed); ALL of --persist's stderr (durable-copy/staging/commit warnings included, not only the record-write-failure check) is discarded this run, and the record-write-failure detector is DISABLED (only the no-new-inputs case below is still checked)" >&2
fi
# Targeted persist FIRST (substituting this run's held <slug>/<run-id> — the
# targeted form is exempt from every discovery-mode skip by caller intent):
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/efficiency-trace.sh --workpad-dir "$ROOT/.prflow/tmp/review/<slug>/<run-id>" --slug "<slug>" --persist 2>"$PERSIST_ERR" || true
# Then argument-less discovery for every OTHER leftover run dir on disk; its
# stderr appends to the same capture so the single surfacing line carries both:
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/efficiency-trace.sh --persist 2>>"$PERSIST_ERR" || true
cat "$PERSIST_ERR" >&2
# Detect the "no inputs FROM THIS RUN" case by diffing against the pre-loop snapshot, anchored
# on $ROOT (matching --persist): comm -13 lists iter-*.json present now but NOT before the
# inline loop — i.e. exactly what THIS run wrote. This is immune to prior-run leftovers on the
# persistent local tier, where a whole-tree presence check would let a leftover mask a real
# loss. If the snapshot file is somehow absent, treating it as empty degrades to whole-tree
# presence — and that degrade direction can MASK a real loss, not surface it. The separate
# preflight step above gives the agent a Write-tool seam for authoring the empty baseline; if
# the file remains absent, $BEFORE_READY disables comm rather than converting its missing-file
# error into an empty command substitution and a false telemetry-loss reflection. Zero NEW
# iter-*.json means the inline loop wrote no per-iteration workpad, so --persist
# had nothing to derive from and this run's effectiveness telemetry is genuinely lost — surface
# it, do not swallow. (A persist that DID find inputs but failed to write still leaves
# efficiency-trace.sh's own ::warning:: on the run log, surfaced above.) The detector counts NEW
# iter-*.json unconditionally, which is correct here because at THIS seam the review-and-fix
# loop just driven inline is what writes this tree, so a foreign review-sourced dir being the
# sole new occupant is not a reachable in-flow shape.
# Portable, no bash-only glob-completion builtin (this prose runs under the agent's shell — zsh/dash/sh). The
# zsh nomatch guard + `set --` capture the current iter-*.json into "$@"; the two arms then make
# the "no inputs FROM THIS RUN" decision STRUCTURALLY distinguish a genuine zero-set from a failed
# enumeration: `[ ! -e "$1" ]` is definitive absence (zero iter-*.json exist at all — with nomatch
# off an unmatched glob leaves $1 the literal pattern, so `! -e` is true), and ONLY when files DO
# exist does the `-z` arm enumerate them via the builtin `printf` and diff `comm -13 "$BEFORE"`
# (files present now but not pre-loop = what THIS run wrote). The builtin `printf` over real
# matches avoids a fail-open path where empty output would fire the false telemetry-loss
# reflection. Caveat (mirrors the site-1 note): `[ ! -e "$1" ]` reads a dangling-symlink
# first-match as definitive absence, so it could record a false telemetry-loss — irrelevant
# here (this DevFlow-controlled iter-*.json tree is never symlinked).
[ -n "${ZSH_VERSION:-}" ] && setopt nonomatch || :
set -- "$ROOT"/.prflow/tmp/review/*/*/iter-*.json
if [ "$BEFORE_READY" -eq 1 ]; then
  if [ ! -e "$1" ] || [ -z "$(printf '%s\n' "$@" | sort | comm -13 "$BEFORE" -)" ]; then
    # Guard the loss-record write itself: if workpad.py fails (gh API/permission error,
    # absent reflection section, bad $ISSUE_NUMBER) the ::warning:: keeps the gap visible on
    # the run log rather than silently dropping both the telemetry AND its loss-record — a
    # double silent failure at the exact seam this clause exists to make visible. Mirrors the
    # --persist line's best-effort breadcrumb discipline.
    "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "review-and-fix inline loop wrote no iter-*.json this run AND lib/efficiency-trace.sh --persist synthesized nothing (no unrecorded 'fix: address review findings (iteration N)' commit to reconstruct from, a failed search — unresolvable base ref, a base ref left unestablished by a failed origin refresh, or failed git log — failed synthesized writes, or a discovery-mode skip such as multi-slug ambiguity or a refused unsubstituted placeholder identity; --persist's own warnings name which when a candidate dir was visited), so this run's effectiveness telemetry (.prflow/logs/efficiency/) is missing" \
      || echo "::warning::phase-3.3: failed to record dropped-failed observability-gap reflection on issue #$ISSUE_NUMBER; this run's effectiveness telemetry is lost AND its loss-record could not be written" >&2
  fi
fi
# The no-new-inputs case above only catches a dropped LOOP EXIT (the inline loop wrote no
# iter-*.json at all). It does NOT catch the sibling failure mode where the loop DID write
# iter-*.json but --persist's own record derivation/write step then failed — that failure is
# otherwise invisible to this this-run-scoped detector, which only measures INPUT presence,
# not persistence SUCCESS. Grep the captured --persist stderr for its record-derivation/write
# failure breadcrumbs so this second, independent failure mode is surfaced too, rather than
# reading "inputs existed" as "persisted successfully". efficiency-trace.sh's three record
# derivation/write failure paths do NOT share one common substring: jq-derivation failure and
# mkdir failure both end "...record not written[ for ...]", but the disk/permission write
# failure (a write after mkdir succeeded — ENOSPC/EROFS/quota/perms) instead reads "...failed
# (disk/permission); not persisted for ..." — so match BOTH literals, or a mutated/renamed
# breadcrumb on just the disk-write path would silently escape this detector exactly as the
# single-literal form did (review Step 3.5 fix-delta gate). This intentionally scopes to
# record derivation/write failures only, not the separate TELEMETRY-BRANCH write/push failure
# surface (telemetry-branch.sh's "::warning::telemetry-branch: ..." breadcrumbs — a lost CAS, a
# non-conforming store, an unwritable .prflow/tmp). The record is staged under gitignored
# .prflow/tmp/; afterward a DEGRADED branch write (or a CI staging-only run) RETAINS that staging
# root (only a clean rc-0 write deletes it), bounded by a newest-N prune on the next --persist; a
# DEGRADED write additionally emits one ::warning:: naming its absolute path, while a staging-only
# run retains silently — so on a LOCAL filesystem a failed branch write is recoverable rather than
# lost. On an EPHEMERAL CI runner the staging tree does not survive
# teardown, so the cloud recovery path is the UPLOADED WORKFLOW ARTIFACT the auto-review tier
# stages and uploads, which the trusted telemetry relay workflow
# downloads, validates, and pushes — not any on-disk copy the ephemeral runner cannot retain. This surface
# is still uncovered by this detector, and surfaced only by the helper's own
# stderr breadcrumb (which this step captures but does not grep). KNOWN LIMITATION (also deferred,
# review shadow pass): unlike the this-run-scoped no-inputs detector above, this grep
# runs against the combined capture (the targeted call's stderr plus the whole-tree
# discovery call's), so a
# persistently-failing LEFTOVER run directory elsewhere on the local tier can also match —
# the reflection below therefore does not assert the failure is scoped to this run.
if [ "$PERSIST_ERR_IS_DEVNULL" -eq 0 ] && grep -qE 'record not written|failed \(disk/permission\); not persisted for' "$PERSIST_ERR" 2>/dev/null; then
  "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "lib/efficiency-trace.sh --persist failed to derive/write an effectiveness record (see the record-derivation/write-failure breadcrumb above) — either this run's or an unresolved leftover run's on this host; some run's effectiveness telemetry under .prflow/logs/efficiency/ is missing" \
    || echo "::warning::phase-3.3: failed to record dropped-failed observability-gap reflection (record-write-failure case) on issue #$ISSUE_NUMBER; this run's effectiveness telemetry is lost AND its loss-record could not be written" >&2
fi
[ "$PERSIST_ERR_IS_DEVNULL" -eq 1 ] || rm -f "$PERSIST_ERR" 2>/dev/null
```


Read the loop-verdict marker FIRST — it is the machine-readable channel, and the exact-wording headline match below is the version-gap fallback. `review-and-fix` emits a producer-composed marker as line 1 of its chat output, carrying both the loop's overall result and its coverage status in space-free tokens, so you need not string-match the human headline prose across a plugin-version boundary (the loop may be loaded from a different plugin version than this run). Before bucketing the verdict, write the skill's returned chat output — at minimum its first line — to `.prflow/tmp/rf-verdict-${ISSUE_NUMBER}.md` with the **Write tool** (the `.prflow/tmp/` precondition established in Phase 1.1 governs this scratch write; on its not-gitignored degraded arm, skip the marker read and go straight to the exact-wording fallback below), then read the marker:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/loop-verdict-marker.py read .prflow/tmp/rf-verdict-${ISSUE_NUMBER}.md
```

The helper inspects line 1 only (a marker a finding quotes deeper in the report is prose, not a stamp) and prints exactly one closed-vocabulary routing token, which decides both the verdict bucket and the coverage status:

- `CLEAN-FULL <result>` → a clean approve-family result on a full-coverage shadow: take the clean-completion path below and record `--record-review-coverage full attempted <roster> <checklist>`.
- `CLEAN-NOT-VERIFIED <result>` → a clean approve-family result whose shadow was not verified: record `--record-review-coverage not-verified <dispatch> <roster> <checklist>`, then take the not-verified branch below — which does not route unconditionally to clean completion.
- `AWUSF <coverage>` → `APPROVE WITH UNRESOLVED SHADOW FINDINGS`: take the AWUSF branch below.
- `REJECT` → take the REJECT branch below.
- `NO-MARKER` (line 1 is not a marker — an older loop that emits none) or `MALFORMED …` (a marker-shaped line 1 with a bad or out-of-vocabulary field) → the marker channel could not resolve the verdict: fall back to the exact-wording headline match described in the paragraphs below. Where the fallback resolves the coverage fact, record it exactly as the matching arm above; where it does not — and on any arm where the fact cannot be resolved at all — record `--record-review-coverage unestablished unestablished unestablished unestablished`, because collapsing an unresolved fact onto a clean value is the fail-open the terminal gate exists to close.
- A loop that stopped at `engine-root: incomplete` never reached Loop Exit, so it returns no verdict and no marker: a `NO-MARKER` reading alongside that reported terminal takes the Blocked path below directly, not the severity-aware exit, which would grade a residual population the engine never produced.

**Safe direction — non-negotiable.** Only `CLEAN-FULL` authorizes the clean, fully-covered completion path. A missing, malformed, or out-of-vocabulary marker is **never** read as a clean, fully-covered approval — it routes to the exact-wording fallback, and if that fallback cannot resolve the verdict either (an errored/garbled/absent headline), the run takes its existing **not-clean handling** (the Blocked path or the severity-aware exit below), never the clean-completion path.

After the skill completes with a clean approve-family verdict (`APPROVE`, `APPROVE WITH CAVEAT`, or `APPROVE WITH ADVISORY NOTES` — not `APPROVE WITH UNRESOLVED SHADOW FINDINGS`, which is handled separately below), flush any residual fixes. A run that does not return one of those three recognizable verdicts — it errors, can't run, or emits nothing parseable as a verdict — is not a clean completion: route it to the Blocked path below rather than letting an empty/garbled exit fall through to the flush. With `--push-each-iteration` the loop has already committed and pushed every iteration, so this is normally a no-op — guard the commit so an empty staging area doesn't error:
```bash
git add -A
git diff --cached --quiet || git commit -m "fix: address code review feedback for issue #$ARGUMENTS"
git push
```

Tick the `review-and-fix` gate here with `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --tick-progress "review-and-fix"`; it is a nested `## Progress` row, so a missed tick is not repaired by the `--status Complete` top-level backstop. The other exit paths carry the same tick as their own steps state. When the loop-verdict marker resolved above (`CLEAN-FULL`/`CLEAN-NOT-VERIFIED`), take the coverage status from it and skip the headline harvest below; a free-text `--note` is optional colour, and the record is the source of truth. The exact-wording harvest that follows is the fallback for an older loop that emitted no marker (the `NO-MARKER`/`MALFORMED` arm). In that fallback, read these from the run's verdict headline: those exact literals are the `{shadow status}` parenthetical that review-and-fix renders on its APPROVE-family chat line (its Loop Exit "Verdict → chat output"), not from the report's `## Coverage` → `### Shadow agreement` section, which paraphrases the same fact in different prose (`Shadow ran with full reviewer coverage …` / `Shadow agreement NOT verified — {reason}`). Matching the headline token is exact; grepping the report body for the literal would miss. (Bucket the run by the loop's verdict first — this clean-completion path versus the AWUSF / REJECT / Blocked branches below — reading it from review-and-fix's chat-output verdict line (its Loop Exit "Verdict → chat output"). That line is the only surface carrying the *loop-level* verdicts: `APPROVE WITH UNRESOLVED SHADOW FINDINGS` is rendered there and never on the engine's report `## Verdict:` line, whose enum stops at the per-iteration engine verdicts (`APPROVE` / `APPROVE with notes` / `APPROVE WITH CAVEAT` / `APPROVE WITH ADVISORY NOTES` / `REJECT`) — so bucketing off `## Verdict:` would silently read an AWUSF run as a clean approve and ship it unreviewed. Only after the verdict has bucketed as clean approve-family, harvest the `{shadow status}` token from that same headline, so the AWUSF lost-write headline's own `… not verified …` prose can never be mis-harvested onto a clean run.) This is so a clean approve-family verdict that rode on a *not-verified* shadow (Step 2.6 outcome 3, a shadow fan-out shortfall the loop reports rather than elects) is visible in the workpad rather than silently consumed as if it had been fully audited. A `not-verified` record does not reach `Status: Complete` on its own: it reaches it only when Phase 4.3's disposition arm applies — a true, specific `--review-coverage-disposition shadow-coverage "<reason>"` over a record reading `dispatch=attempted`. A run that never dispatched the shadow has no disposition available (the gate refuses one as `[review-coverage-undispatched]`) and stops at a non-terminal or `Blocked` status naming what prevented the fan-out. This refusal is not shadow-specific: a self-assessed budget or context state is an unestablished measurement, not a fact — a run cannot establish its own remaining context on any tier — so it never lowers the reviewer roster, the checklist steps, the bounded re-review, or the shadow fan-out, on the local and cloud tiers identically. A run that believes it is out of budget performs the step, or stops at a non-terminal/`Blocked` status naming the step it did not perform. Contrast the bounded re-review below, which *does* require full coverage because it exists specifically to give an orchestrator hand-fix the independent pass it would otherwise never get.

Stamp the machine-readable coverage record on every Phase 3 exit — this clean-completion path, the `APPROVE WITH UNRESOLVED SHADOW FINDINGS` and `REJECT` branches and the severity-aware soft-proceed alike, because each of those reaches the terminal `--status Complete` write, which Phase 4.3 structurally refuses as `[review-coverage-unestablished]` without a record; the Blocked path reaches no Complete write, so it stamps only if the run later resumes toward one. Run `workpad.py update $ISSUE_NUMBER --record-review-coverage <coverage> <dispatch> <roster> <checklist>`, deriving each operand from the loop-verdict marker read above. On the `REJECT` branch and on the severity-aware soft-proceed the record is `not-applicable not-applicable not-applicable not-applicable`: the loop routes a REJECT straight to Loop Exit with no convergence-time shadow trigger, so no shadow was owed, none of the four axes measured anything, there is no coverage to report and there is no gap — recording a measured or `unestablished` value on any axis would dead-end the soft-proceed exit at `Blocked`, contradicting its "do NOT block; the PR is review-ready, not auto-merged" contract. Because `not-applicable` describes the whole pass, the gate accepts it on all four axes or none and refuses any mixture as `[review-coverage-unestablished]`, so a dispatched pass cannot borrow it to hide a short roster. `not-applicable` is only for a pass that owed no shadow; a shadow the run owed and did not dispatch is `never`, which is not clean, carries no disposition, and cannot reach `Status: Complete`. The four operands:

- `<coverage>` — `full` (from `CLEAN-FULL`, or from an `AWUSF <coverage>` token whose own coverage field reads `full`), `not-verified` (from `CLEAN-NOT-VERIFIED`, or from an `AWUSF <coverage>` token whose coverage field reads anything else), `not-applicable` on the `REJECT` branch and the severity-aware soft-proceed, else `unestablished`.
- `<dispatch>` — `not-applicable` on the `REJECT` branch and the severity-aware soft-proceed; `attempted` only when this run positively knows the Step 2.6 fan-out was launched, including on the `CLEAN-NOT-VERIFIED` lost-write arm, where the fact is the `shadow fan-out dispatched: …` clause the loop renders on its missing-`shadow`-block arm (`loop-exit.md`), read from the loop's own record and never inferred from the missing block; `never` when this run positively knows a shadow the run owed was not launched; `unestablished` on any other arm, where the loop renders no dispatch fact at all.
- `<roster>` — `not-applicable` on the `REJECT` branch and the severity-aware soft-proceed, where no shadow was owed and no roster was measured; otherwise read from the fix loop's `iter-<N>.json` `shadow` block: `complete` when its `reviewers_dispatched` covers its `expected_reviewers`, `short` when it falls short; on `CLEAN-FULL` the marker's own full coverage is itself that roster measurement (see `skills/review-and-fix/references/shadow-review.md`), so record `complete` and read the block only for `<checklist>`; where no such block was read on any other arm, `unestablished`.
- `<checklist>` — `not-applicable` on those same two arms; otherwise read from that same block's checklist state: `complete`, `skipped-intentional` (`checklist_skipped` reading `"intentional"` — the shadow reference's `small_diff`+`config_only` skip, which is not a shortfall), `skipped` for any other skip; where no such block was read, `unestablished`.

`<roster>` and `<checklist>` are this loop's own comparison results, not the roster itself — the gate never sees a roster and cannot re-derive one, so on any arm where a shadow was owed, guessing a clean value in place of a block that was not read fails open; `unestablished` is the honest record there, and `not-applicable` is available only on the two arms that owed no shadow at all.

Tick the three Review extension rows on every Phase 3 exit — this clean-completion path, the `APPROVE WITH UNRESOLVED SHADOW FINDINGS` and `REJECT` branches, the severity-aware soft-proceed and the Blocked path alike, because those three extensions loaded on all of them and an unticked row would assert the run never established their state. Apply the extension-row tick rule stated in `phase-1-setup.md` §1.3 to the review engine, the fix loop, and the code-review reception extensions:
```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER \
    --tick-progress "extension resolved: review engine" \
    --tick-progress "extension resolved: fix loop" \
    --tick-progress "extension resolved: code-review reception" \
    --note "<how this run established the review engine's extension state>"
```
One moment, one call: the `--record-review-coverage` stamp above stays its own call. The `--note` states how this run established the review engine's extension state: its ladder runs inside the fix loop's own turn sequence and is reached by a file read rather than a Skill-tool call, so there is no separate return to observe. Where that state cannot be established here, leave that row unticked and say so in the note — never tick it from recall.

If the skill returns `APPROVE WITH UNRESOLVED SHADOW FINDINGS` (the iteration-cap shadow pass surfaced new Important — never Critical — findings the loop could not address; see that skill's Step 2.6 outcome 2): this is not a clean approve. The findings came from a *full-coverage* shadow pass and are real, but they reach you only in chat + the report's `## Unresolved Shadow Findings` section (they do not flow through the Step-3 deferrals manifest, so Phase 4.0.5 will not file them). You may not silently hand-fix them and ship — any fix you apply to resolve them is itself unreviewed spec/code that no independent pass has seen, and shipping it is the unreviewed-final-edit gap the skill's caller contract forbids. Pick one:
1. Fix + re-review (bounded once). Apply fixes for the unresolved findings, commit (`fix:` prefix). Before re-invoking, re-run the pre-invocation snapshot block from 3.3 above (recomputes the repo-toplevel-anchored baseline of pre-existing per-iteration workpads) — the bounded re-review below is a second, separate inline `review-and-fix` invocation whose own Loop Exit can be dropped exactly like the first invocation's, so it needs its own fresh this-run baseline, not the first invocation's now-stale one. Then re-invoke `review-and-fix` exactly one more time (Skill tool, same argument shape as the initial-review site in 3.3 above — the draft PR number as a bare leading numeric token ahead of `--push-each-iteration --issue $ISSUE_NUMBER`, its digits read from inside the brackets of that same printed `draft PR number: [<n>]` line, and the issue number substituted as its literal digits; take the same omit-the-token arm when that line printed empty brackets (`[]`) or did not print at all, and record on the workpad which arm you took) so the fix delta gets an independent shadow/review pass, and immediately after it returns, re-run the observability-persistence backstop block from 3.3 above (the same persist-and-detect procedure — the idempotent Layer-3 persist call, the record-write-failure check, and the `dropped-failed` reflection) against the snapshot just taken — this second invocation's telemetry is protected exactly like the first invocation's, not left unguarded at this seam. A clean approve-family verdict (`APPROVE` / `APPROVE WITH CAVEAT` / `APPROVE WITH ADVISORY NOTES`) on a full-coverage shadow clears the re-review — read the re-review's own loop-verdict marker first exactly as above (a `CLEAN-FULL` token clears it; the `shadow agreed, full coverage` headline token is the older-loop fallback, same surface as the gate note above) — treat it exactly as a clean completion above (flush residual fixes and issue that path's own `--tick-progress "review-and-fix"` call). Then continue. A clean verdict whose shadow was `not verified` does not clear it: the re-review exists precisely to give the hand-fix delta an *independent, full-coverage* pass. Any other outcome routes through the severity-aware exit below — it does NOT automatically Block (e.g. `APPROVE WITH UNRESOLVED SHADOW FINDINGS` again, `REJECT`, or a not-verified re-review). Do not loop a third time: trigger at most one orchestrator-initiated re-review. (The bounded re-review is an ordinary `review-and-fix` run, so if *it* defers a finding through the Step-3 deferrals manifest, that is the normal Phase 4.0.5 follow-up-issue channel and proceeds as usual — the "AWUSF findings do not flow through the deferrals manifest" rule above is about the *first* run's unresolved shadow findings, not the re-review's own deferrals.)
2. Do not fix — route directly through the severity-aware exit below (treat the unresolved findings as "unresolved after the cap").

Severity-aware exit (do not fully block on diminishing-returns). Reached when the bounded re-review did not return a clean and full-coverage verdict, or when you chose option 2. Two consecutive non-clean review passes (the capped first run + the bounded re-review) is not, by itself, grounds to abort the whole implement lifecycle — hard-blocking there discards the completed work and the review-ready PR over findings that are often advisory or over-graded. Instead, classify the residual unresolved findings by severity and route. First ensure over-grade calibration has actually run on the residual: the loop's over-grade calibration gate (`/prflow:review-and-fix` Step 2.6) — which *flags* a promote-path over-grade and *requires a recorded `severity-calibrated` technical evaluation*, never auto-demoting — ran on the residual only if a bounded re-review actually ran (option 1). On option 2 (you chose not to re-review) and on a first-run REJECT (which may never have reached the shadow-promotion decision where the gate fires), the gate has *not* run — do not assume a finding was already calibrated; apply the same flag-and-evaluate calibration yourself before classifying, and grade conservatively (default to Critical-treatment on doubt). Then route:

- A genuine unresolved Critical — a real Critical (a data-loss/exploit/correctness break citing a concrete failing input), or an Important the orchestrator judges it cannot responsibly defer → Blocked path below (the human gate genuinely applies). The same applies to a re-review that errors / returns no parseable verdict at all (no findings to classify → fail closed), and to any residual whose severity is missing, ambiguous, or cannot be confidently graded — an ungradeable residual fails closed to the Blocked path, it does **not** fall through to soft-proceed. The same applies to a non-convergence reported as `engine-root: incomplete`: the engine never ran, so there are no graded residuals and the soft-proceed test below would pass vacuously on an unreviewed PR.
- Otherwise — the residual is only advisory / Suggestion / `severity-calibrated`-down / a deferrable Important, *and every residual was confidently gradeable as non-Critical* → Soft-proceed path: do NOT block. The PR is review-ready, not auto-merged; the residual findings ride into the human's merge decision rather than aborting the run.

Soft-proceed path. Surface the residual findings durably and continue the lifecycle:
- One moment, one call: every residual finding and the `review-and-fix` gate tick go in a single `update` — one `--reflection-kind` covers them all, and `--reflection` repeats once per residual: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "unresolved after bounded re-review (non-Critical, surfaced for human review): {finding}" --reflection "…{each further residual}" --tick-progress "review-and-fix" --note "review-and-fix did not reach a clean+full-coverage verdict; soft-proceeded on non-Critical residual findings (surfaced above) — PR is review-ready, not auto-merged"`. The reflections land under `### ⚠️ Action required`.
- Carve-out — text needing the file-based recipe splits the call. Review-finding prose routinely carries a backtick, a `$` or a double quote, and the interpolation-safe contract in `SKILL.md` mandates `--reflection-file` for it on every tier. That flag is not repeatable — one file-based reflection per call — and aborts the whole call with no PATCH on an unreadable or empty payload, so each residual needing it is its own call and the gate tick plus the `--note` follow in a final one.
- Continue to Phase 3.4 and Phase 4. The PR ships per the configured `implement_pr_state` with the residual findings documented in the workpad and (where the re-review wrote a deferrals manifest) carried into the PR body by Phase 4.0.5 / `/pr-description`. The human merger decides. Do not silently hand-fix the residual findings after this point — that is still the unreviewed-final-edit gap; they are *surfaced*, not *resolved*.

Blocked path (genuine unresolved Critical, or an `engine-root: incomplete` root). Reached from the severity-aware exit when a genuine unresolved Critical remains (or a verdict cannot be parsed at all — fail closed), and from the engine-read arm above when the engine root's completeness could not be established: `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "review-and-fix unresolved Critical (or unparseable verdict): {summary}"` — on the `engine-root: incomplete` entry substitute `--reflection "engine-root: incomplete — {path}"` for that literal so the record names the real cause — then emit the 👎 outcome reaction (see *Outcome reaction* in the Workpad Reference) and stop. A non-Critical residual is not a Blocked exit — it soft-proceeds per the path above.

If the skill returns `REJECT` (it could not converge — whether at the iteration cap or via a pre-cap convergence exit per that skill's Step 4.5, whose verdict is still REJECT): route through the severity-aware exit above — a REJECT whose unresolved triggers are all non-Critical/deferrable soft-proceeds (review-ready, surfaced), while a REJECT with a genuine unresolved Critical takes the Blocked path. Like AWUSF, a REJECT must not be silently hand-fixed and shipped as resolved; soft-proceed surfaces it for the human rather than resolving it.

<!-- prflow:implement-ref phase=3 file=skills/implement/phases/phase-3-fix-loop.md end -->
