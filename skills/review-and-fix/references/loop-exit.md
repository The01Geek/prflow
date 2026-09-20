# Reference: Loop Exit

## Loop Exit

### Pre-mapping: Widens-surface guard + deferrals manifest

Run this step BEFORE the REJECT downgrade gate below. It enforces a widens-surface guard on Yes-downgrade skips and emits a manifest downstream callers (currently /prflow:implement Phase 4.0.5) consume to file follow-up issues and inject the Scope-Acknowledged Findings block into the PR body.

Widens-surface guard. Walk every `fix_decisions` entry in the final iter's workpad whose `skip_category` reads Yes in the enum table (Step 3, item 5 — currently `claim-quality`, `out-of-scope`, `already-tracked`). For each candidate, join to its Phase 3 finding via `finding_id` to obtain `defect_signature.file` and `defect_signature.line_range`, then read the cached diff (`.prflow/tmp/review/<slug>/<run-id>/diff.patch`) and check whether any non-comment hunk in the diff overlaps that file within ±10 lines of the line range. If that cache is absent at read time, do not read the absent file as an empty diff or a no-overlap reading: treat it as a failure of the engine entry that should have produced it — record a `PRFlow Reflections` bullet naming the absent cache and fail closed, keeping every candidate skip disqualified (its finding stays a REJECT trigger) because overlap cannot be ruled out. If overlap is detected, the skip is disqualified for the downgrade gate — append a bullet to the workpad's `PRFlow Reflections` (`widens-surface guard rejected skip for finding {finding_id}: PR diff overlaps {file}:{lines}`) and treat the finding as a non-skipped REJECT trigger for the gate that runs next. This catches the "refactor around a pre-existing bug, then defer the bug" pattern: the bug's lines were untouched, but surrounding changes widen reliance on the broken behavior.

Deferrals manifest. After the guard runs, emit `.prflow/tmp/review/<slug>/<run-id>/deferrals.json` (run-scoped, alongside this run's `iter-*.json`) containing every surviving Yes-downgrade skip (i.e. `claim-quality` / `out-of-scope` / `already-tracked` entries that the widens-surface guard did not disqualify) and every surviving `settled-by-disclosure` foreclosure row. The manifest is written regardless of whether the downgrade gate ultimately fires; `claim-quality` and `already-tracked` skips on non-REJECT runs are still legitimate deferrals worth tracking for the verdict matcher. A `settled-by-disclosure` row carries `category: "settled-by-disclosure"` plus a top-level `disclosure: {path, phrase}` object (copied from its `parking_evidence.source`) and no follow-up issue — the shipped disclosure is the deliverable, so no work is tracked. If zero entries survive, omit the file entirely.

Schema:

```json
{
  "schema_version": 1,
  "default_channel": "loop-record",
  "pr_branch": "<current branch>",
  "base_branch": "<base_branch from .prflow/config.json; if absent, the repo default branch via `gh repo view --json defaultBranchRef -q .defaultBranchRef.name`, falling back to `main`>",
  "generated_at": "<ISO 8601 UTC>",
  "deferrals": [
    {
      "finding_id": "<from phase3_findings.finding_id>",
      "agent": "<from phase3_findings.agent>",
      "severity": "<Critical | Important | Suggestion>",
      "file": "<from defect_signature.file>",
      "line_range": [<start>, <end>],
      "symbol": "<best-effort, see below>",
      "kind": "<from defect_signature.kind>",
      "summary": "<verbatim from phase3_findings.description>",
      "category": "<one of: out-of-scope, already-tracked, claim-quality, settled-by-disclosure>",
      "explanation": "<verbatim from fix_decisions.evidence>",
      "disclosure": {"path": "<repo-relative disclosure path>", "phrase": "<short verbatim phrase>"}
    }
  ]
}
```

`default_channel` is the literal `"loop-record"`: this manifest is the durable loop record every entry in it is traced by, which is what the completion-evidence check (`scripts/check-completion-evidence.py`, read below at Loop Exit) means by that channel. Emit it verbatim — the check resolves each entry's channel from this declaration, so a manifest that omits it makes every entry read as citing no durable channel and the check reports `non-durable-deferral` against a legitimately-complete run. `finding_id` carries the same identifier the widens-surface guard above joins on, so the check names the offending entry when one fails.

The `disclosure` object is present only on a `settled-by-disclosure` entry (copied from that row's `parking_evidence.source`); it is absent on the three ordinary categories. A foreclosure entry carries no `follow_up` — the downstream implement Phase 4.0.5 filer passes it through unchanged (files no issue) and `/pr-description` renders it citing the disclosure path in place of an issue number.

`symbol` is best-effort: scan the finding's `description` for the first backtick-quoted identifier; if none, leave empty string. Downstream matchers (the /prflow:review verdict engine) fall back to `line_range` + summary similarity when `symbol` is absent.

This step does NOT file follow-up issues, mutate the PR body, or post a verdict to GitHub — those are /prflow:implement Phase 4.0.5's responsibility. When the caller is standalone /prflow:review-and-fix (no orchestrator wrapping it), the manifest is still written.

### Pre-mapping: Step-3-evaluated REJECT downgrade

If the engine's final verdict is REJECT AND the trigger set is non-empty AND every REJECT trigger (checklist FAILs, Critical Phase 3 findings, every finding driving a §4.2 threshold-independent REJECT carve-out at any severity — self-contradicting-diff and unmet-decided-criterion alike — and a §4.2 rule 2a coverage shortfall — decided acceptance criteria left uncovered, or a shortfall that could not be established) was Step-3-skipped with a `skip_category` whose "qualifies for REJECT downgrade?" column in the `skip_category` enum (authoritative) table (Step 3, item 5) reads Yes AND survived the widens-surface guard above, downgrade the final verdict to `APPROVE WITH CAVEAT` and surface each trigger in the report's `## Downgraded Findings` section with its category label and evidence.

This downgrade conclusion passes through neither convergence entry, so it does not run the parked-class sweep. Record the sanctioned `parked-class sweep not applicable: downgrade-path conclusion` Reflection sentinel before mapping the APPROVE-family output; the completeness gate recognizes this explicit non-goal rather than mistaking it for a skipped sweep.

The gate consults that table directly — it does not maintain its own list. If a future edit adds another `skip_category`, mark its downgrade-eligibility in the table row and the gate picks it up automatically. One trigger whose category reads "No" (or "N/A", or whose category isn't in the table at all) keeps the REJECT. Both §4.2 threshold-independent carve-out classes are **non-downgradable**: a self-contradicting-diff or unmet-decided-criterion finding keeps the REJECT at any severity even when Step 3 skipped it under a Yes category, because a Step-3 skip is not the recorded scope decision §4.2 requires — only a fix, or meeting the criterion, clears it. A rule 2a coverage shortfall is **non-downgradable** likewise: it is not a finding, so no `skip_category` reaches it and it is never Step-3-skipped — its presence keeps the REJECT and makes this downgrade inapplicable, and only a later engine run recording no shortfall clears it. An empty trigger set likewise never downgrades: the every-trigger test is vacuously true over it, so the REJECT stands unexamined until a trigger is actually skipped. Similarly, any REJECT trigger that was NOT skipped at all (i.e. the orchestrator addressed it in Step 3 but the post-fix engine re-run still rejects) keeps the REJECT; the downgrade gate is for false-positive REJECTs, not for unfinished work.

### Pre-mapping: Post-shadow edit gate (no unreviewed final edits)

The shadow pass (Step 2.6) is the loop's last independent review, so its verdict is honest only if nothing changed after it ran. A fix, tweak, or "advisory flush" committed *after* the shadow reviewed HEAD is unverified, and a green test suite does not cover it (a weak/vacuous test passes, and a prose/doc edit has no test at all).

Read `reviewed_sha` from the shadow block of the iteration the final shadow ran on (the most recent iter carrying a `shadow` block; for an ordinary `APPROVE WITH UNRESOLVED SHADOW FINDINGS` promotion, the one-iter-back block). Sweep-at-cap arm: when the unresolved verdict was produced by an unfixed at-or-above-threshold sibling already registered by the current iteration's `parked_class_sweep`, read the current iteration's shadow block instead; no promoted successor exists in this arm. Clean-iteration-1 exit arm: when the final iteration records `shadow_skipped` and no `shadow` block, read `shadow_skipped.head` as `reviewed_sha`. Then compare it to the commit that will actually ship:

```bash
HEAD_NOW=$(git rev-parse HEAD)
```

- `HEAD_NOW` == `reviewed_sha` → the shadow reviewed exactly what ships; proceed to the verdict unchanged.
- **`HEAD_NOW` != `reviewed_sha` but the post-shadow delta touches only `.prflow/logs/**`** → these are observability artifacts, not reviewable code, and the same paths the review diff filter strips. Confirm the delta is logs-only with `git diff --name-only <reviewed_sha>..HEAD` and verify the changed-path list is **non-empty** *and* that **every** path in it is under `.prflow/logs/`; if so, set `reviewed_sha = HEAD_NOW`, record the logs-only exemption on the shadow block, and proceed to the verdict unchanged. An empty or errored `git diff` output is NOT exempt — with `HEAD_NOW != reviewed_sha` a diff that lists no paths means the command failed or the SHAs are not comparable, not that a logs-only commit landed, and "every path is under `.prflow/logs/`" is vacuously true over an empty list. Fail closed directly: set the verdict's `{shadow status}` to `shadow agreement not verified`, do **not** set `reviewed_sha = HEAD_NOW`, and do **not** fall through to the delta-review arm below — that arm re-runs the same `git diff <reviewed_sha>..HEAD` and would read the equally empty result as a clean delta (line "Delta-review clean → proceed with the verdict"). Any commit touching a path outside `.prflow/logs/**` still trips the gate and takes the delta-review arm below (a mixed commit touching logs and other paths is not exempt).
- `HEAD_NOW` != `reviewed_sha` (a commit touching paths outside `.prflow/logs/**` landed after the shadow) → the approve-family verdict is stale over the post-shadow delta; do not emit it as-is. Run a bounded delta-review: dispatch the standard Phase-3 reviewer roster (blinded, per Step 2.6) over just `git diff <reviewed_sha>..HEAD`.
  - Delta-review clean (no new Critical/Important) → set `reviewed_sha = HEAD_NOW`, record the delta-review on the shadow block, and proceed with the verdict.
  - Delta-review surfaces a new Important (or cannot run at all) → downgrade the chat verdict's `{shadow status}` to `shadow agreement not verified`.
  - Delta-review surfaces a new Critical → the verdict becomes REJECT.
  - **Never emit `shadow agreed, full coverage` over a delta the shadow never saw.**

This gate is also `reviewed_sha`-absent fail-closed: if no shadow block carries a `reviewed_sha` (older/partial workpad), treat the verdict's shadow status as `shadow agreement not verified` rather than assuming the shadow covered HEAD.

Dispatch barrier. Every subagent dispatch described here is bound by the dispatch-collection requirement in the engine-ground-truth block injected into this run's prompt — read it there (if your prompt carries no such block, collect every dispatch before the turn ends anyway); it is deliberately not restated here.

Make the shadow-reviewed commit the deliverable: Suggestion-level findings from the final shadow become notes / follow-up issues, not post-convergence code edits. A final-shadow finding worth fixing is worth re-reviewing — route it through a promoted iteration (which re-shadows), never a quiet flush after the verdict.

### Verdict → chat output

The fix loop posts no verdict to GitHub — it does NOT post a `gh pr review` or `gh pr comment` for any verdict. Its progress artifact is surface-dependent: the inline engine's run-keyed progress comment for a standalone PR-mode run, or the existing issue workpad for an implement-driven run. The final report (including any `## Advisory Findings`, `## Coverage`, and `## Unresolved Shadow Findings` sections) is emitted to chat only. A human who wants a formal `--request-changes` / `--approve` / `--comment` review on the PR runs `/prflow:review <PR>` separately; that skill performs an independent re-review and posts the result via its own Phase 4.4.

Over-grade gate non-convergence (fail-closed). A promote-path `Critical`/`Important` Phase 3 finding that the Step 2.6 Over-grade calibration gate flagged but for which no `decision: "severity-calibrated"` technical-evaluation `fix_decisions` entry was recorded is non-convergence: the run may not emit a clean APPROVE-family verdict while one exists. At the iteration cap it surfaces through the `APPROVE WITH UNRESOLVED SHADOW FINDINGS` (or REJECT, if the unexamined finding was Critical) path, never as a clean approve and never silently dropped.

Map the final verdict to the chat line that precedes the full report:

In all three APPROVE-family lines below (APPROVE, APPROVE WITH ADVISORY NOTES, APPROVE WITH CAVEAT), `{shadow status}` states whether the clean shadow signal is independently verified. Read the most recent iteration with a `shadow` block. The exact clean-agreement string requires both persisted operands: `coverage` must equal `"full"` and `prompt_addenda` must equal `"none"`. Only then render `shadow agreed, full coverage`. A recorded addenda array renders `shadow agreement not verified (prompt addenda: {entries})`; an absent field renders `shadow agreement not verified (attestation not recorded)` and must never be described as steering. Any other coverage or attestation value renders `shadow agreement not verified`. A final iteration recording `shadow_skipped` and no `shadow` block renders `shadow skipped, iteration 1 clean` unless the gate above downgraded it, and takes the `See report.` clause. Any other missing block fails closed. When not verified, drop the trailing `All checks approved.` / `with caveats.` clause and replace it with `See report.` `APPROVE WITH UNRESOLVED SHADOW FINDINGS` remains the separate outcome-2-at-cap verdict and never routes through this template.

Park-calibration completeness (non-convergence on a missing sentinel). An APPROVE-family verdict is only emitted after Step 2.6's Park-calibration gate has run to completion, recorded as a `## PRFlow Reflections` bullet — the gate-clean sentinel on a clean run, the preservation sentinel `park-calibration gate: {N} parking(s) preserved on evidence equivalence` on a run whose parked re-raises were all preserved on evidence equivalence, or one bullet per re-graded finding (matching the gate's own "each re-graded finding and where it routed" record). Recognize the preservation sentinel as gate-completion exactly as the clean sentinel and re-grade bullets are recognized. An APPROVE-family conclusion that carries no park-calibration sentinel or re-grade bullet is treated as non-convergence (the gate did not run to completion): do not emit the APPROVE-family line — re-run Step 2.6 to completion first. If the gate genuinely cannot run, fall through to the not-verified rendering rather than presenting the run as converged.

Parked-class-sweep completeness (convergence-entry conclusions only). An in-scope APPROVE-family conclusion with parked findings but no parked-class sweep evidence is non-convergence. Evidence is a per-class result, `parked-class sweep clean: no new siblings`, or `parked-class sweep not verified: {cause}`; do not emit the APPROVE-family line until the sweep completes, and use the not-verified rendering after the single bounded re-dispatch fails. The REJECT-downgrade conclusion satisfies this rule with `parked-class sweep not applicable: downgrade-path conclusion`. A run with zero parked findings requires no bullet — but that zero must be an established zero, not an unestablished one. Unknown is not zero: the arming comparand — whether this run has parked findings — is the same best-effort three-source union the sweep reads (`fix_decisions` advisory-parked/below-threshold/`settled-by-disclosure` rows, `phase3_findings` minus `applied`, Yes-downgrade deferrals), and those workpad rows can be lost or partial. So when the parked-finding population cannot be established — the union derivation reads a missing or unparseable workpad instead of resolving over present rows to an affirmative empty set — do not collapse that unknown onto zero and skip the bullet; trip: run the sweep, or record `parked-class sweep not verified: parked-finding population unestablished` and take the not-verified rendering. Only an established empty union (resolved over present rows) requires no bullet. Truncation is the same discipline on a second comparand: a per-class-result or `parked-class sweep clean: no new siblings` bullet satisfies this gate only when its emitting `parked_class_sweep` block records `truncation: null`. Read that field directly — do not trust a clean-looking bullet over it — and treat a non-null `truncation`, or a `truncation` that cannot be established, as incomplete coverage that forces the `parked-class sweep not verified: capacity truncation ({details})` rendering no matter how many siblings the completed batches found; a truncated sweep is never a clean pass. The same direct-read applies to `dispatch`: the gate also requires the emitting block's `dispatch: "verified"` and does not trust a clean-looking bullet written over a `dispatch: "not_verified"` (or an unestablished `dispatch`) field — a non-verified sweep is never a clean pass either. Only conclusions that passed through the Step 2, Step 4.5 or Clean-iteration-1 exit convergence entries owe a sweep.

- APPROVE: `Review passed after {N} iteration(s) ({shadow status}). All checks approved.` (→ `… ({shadow status}). See report.` when not-verified)
- APPROVE WITH ADVISORY NOTES: `Review passed after {N} iteration(s) ({shadow status}) with {M} advisory finding(s) parked for human review. See report.`
  - The headline advisory count excludes `decision: "below-threshold"` rows. Count only the advisory population that selected this verdict; the sweep-only producer never increments `{M}`.
- APPROVE WITH CAVEAT (engine verdict APPROVE WITH CAVEAT / APPROVE with notes, or the Step-3-evaluated REJECT downgrade fired): `Review passed after {N} iteration(s) ({shadow status}) with caveats. See report.`
- APPROVE WITH UNRESOLVED SHADOW FINDINGS (iteration-cap outcome 2 — see Step 2.6):
  - Ordinary shadow-promotion arm: `Review converged after {N} iteration(s) but a final shadow pass surfaced {K} new Important finding(s) that the loop could not address within the iteration cap. See report.`
  - Sweep-at-cap arm: `Review converged after {N} iteration(s) but the parked-class sweep registered {K} at-or-above-threshold sibling finding(s) that the loop could not address within the iteration cap. See report.` For the sweep-at-cap arm, source `{K}` and the unresolved list from the current iteration’s unfixed `parked_class_sweep.new_siblings` at or above `$FIX_THRESHOLD`, not from the shadow's new-finding count.
  - Render-time coverage assertion (this line is exempt from `{shadow status}`, so assert explicitly here). Select the ordinary promotion-triggering shadow block one iter back, except that a sweep-at-cap verdict reads the current iteration's block whose `parked_class_sweep` registered the unresolved sibling. Require the selected block to be present with `coverage: "full"`; otherwise use the existing not-verified fallback. When full coverage is present, an addenda array appends `Prompt attestation caveat: {entries}.` and an absent field appends `Prompt attestation not recorded.` The verdict and promotion are unchanged because attestation never gates outcome 2.
- REJECT (max iterations reached or convergence exit with the iteration's verdict still REJECT *and* the downgrade did not apply, OR shadow surfaced a new Critical at the iter cap): `Review still has findings after {N} iteration(s). Remaining issues require manual review:` followed by the list of unresolved findings. Then append the formal-merge-signal hint, conditional on mode:
  - PR mode (`$PR_NUMBER` is non-empty): `To post this verdict as a formal merge signal (e.g. a blocking --request-changes review), run \`/prflow:review {PR_NUMBER}\` — it performs an independent re-review and posts the result.`
  - Current-branch mode (no PR yet): `To post this verdict as a formal merge signal once a PR exists, push the branch and open a PR, then run \`/prflow:review <PR>\` — it performs an independent re-review and posts the result.`

Producer-emitted verdict marker — emit it as line 1 of the chat output. The verdict headline above is ordinary prose, and a caller (`/prflow:implement` Phase 3.3) reads it by exact string match to decide whether the work was independently reviewed — a fragile contract across a plugin-version boundary. So alongside the human headline, emit one machine-readable marker line carrying the loop's overall result and its coverage status. Compose it with the bundled helper — never hand-write the marker in free text. Pass `--entry latest --iteration <N>` (the final iteration) and the helper selects the binding to grade — the `step1` binding at `<N>` when it exists, else, for a shadow-promoted final iteration (which ran no `step1` engine), the `shadow` binding at `<N>` or `<N>`-1 — so terminal completion re-grades the entry that actually covered the final diff and cannot reuse an earlier entry's PASS as current proof. Pass no `--head`; the selected binding's own recorded head is graded:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/loop-verdict-marker.py compose --result "<the loop result>" --coverage "<the {shadow status} phrase>" --run-root ".prflow/tmp/review/<slug>/<run-id>" --entry latest --iteration <N>
```

- `<the loop result>` is the exact human result you mapped above — one of `APPROVE` / `APPROVE with notes` / `APPROVE WITH CAVEAT` / `APPROVE WITH ADVISORY NOTES` / `APPROVE WITH UNRESOLVED SHADOW FINDINGS` / `REJECT`. `<the {shadow status} phrase>` is the exact `{shadow status}` string you rendered for the APPROVE-family lines (`shadow agreed, full coverage`, `shadow skipped, iteration 1 clean`, or a `shadow agreement not verified …` variant); for the `APPROVE WITH UNRESOLVED SHADOW FINDINGS` and `REJECT` lines (which carry no `{shadow status}`), pass the coverage you determined at render time (`shadow agreed, full coverage` when the promotion rode a full-coverage shadow block, otherwise a not-verified phrase). The helper normalizes both to space-free tokens and prints exactly `<!-- prflow:loop-verdict result=<token> coverage=<full|skipped|not-verified> -->`. It never over-claims: only the exact phrase `shadow agreed, full coverage` yields `coverage=full`, only the exact skip phrase yields `skipped`, and every other phrase yields `not-verified`.
- Fixed position: line 1, immediately before the human verdict headline. The reader inspects that line only, so a marker quoted deeper in the report (a finding citing this contract) is prose, not a stamp. Namespace is `<!-- prflow:` (no superseded `devflow:` spelling).
- Only this marker is tool-read; the headline prose carries no new coverage. The compose helper refuses (stderr diagnostic, exit 3, no marker line) in two cases, handled differently: (a) an unmappable-result refusal — emit the human headline alone with no marker line rather than hand-writing one, and a caller then falls back to the headline match; (b) a `--run-root` evidence-missing refusal (the run root did not pass the offline grade) — do NOT emit the approval headline; instead report the terminal `evidence-missing: <run root>` as line 1 of the chat output and stop, so the caller reads it as not-clean/Blocked.

### Coverage

Inject a `## Coverage` section into the final report, positioned between the engine report's `## Code Review Findings` and `## Verdict Criteria` sections (those headings come from /prflow:review's Phase 4.1 template).

Compute by reading every `iter-<K>.json` workpad (plus the appended `shadow` block, if any) and rendering:

```markdown
## Coverage

### Per-iteration finding counts

| Iter | Phase 3 findings | Critical | Important | Suggestion | Phase 2 FAILs | Phase 2 INCONCLUSIVE |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 7 | 1 | 3 | 3 | 2 | 0 |
| 2 | 4 | 0 | 2 | 2 | 0 | 1 |
| ... | | | | | | |

### Shadow agreement

Select the block to read by verdict, and fix branch precedence. For `APPROVE WITH UNRESOLVED SHADOW FINDINGS`, select the current triggering iteration when its `parked_class_sweep` registered an at-cap unresolved sibling; otherwise pin to the specific promotion-triggering iter one back. Read **only** the selected block—do not fall back to an earlier shadow if its write was lost—or the Coverage section can contradict the headline. For every other non-REJECT verdict, read the most recent iteration that has a `shadow` block (normally the final iter). **Branch precedence:** evaluate the selected-block lost-write case before `coverage: "full"`, and render full coverage only when that pinned current-iter or one-iter-back block is present and full. **Also scan every iter's `shadow` block:** if any shadow on an iteration strictly before the selected block ran `coverage: "not_verified"`, append `Note: an earlier shadow pass (iter K) was not verified ({reason}); only the later pass achieved full coverage.` Exclude the selected block itself from this scan so its failure is not reported twice.

{If `coverage` is `"full"` and `prompt_addenda` is `"none"`: "Shadow ran with full reviewer coverage ({reviewers_dispatched roster}). It raised X findings; Y were already in iter N (overlap = Y/X); Z were new (Z_crit Critical, Z_imp Important)." then — If Z == 0: "Genuine convergence — shadow agreed with the loop." / If Z > 0: render the existing unresolved-finding text.} {If `coverage` is `"full"` and `prompt_addenda` is an array, with no outcome-2 findings: "Shadow agreement NOT verified — prompt addenda: {serialized JSON array}; the loop's tentative verdict stands but was not independently audited."} {If `coverage` is `"full"` and `prompt_addenda` is absent, with no outcome-2 findings: "Shadow agreement NOT verified — attestation not recorded; the loop's tentative verdict stands but was not independently audited."} {If `coverage` is `"full"` and `prompt_addenda` is present but is neither the string `"none"` nor an array, with no outcome-2 findings: "Shadow agreement NOT verified — prompt attestation value is invalid; the loop's tentative verdict stands but was not independently audited." Any other present attestation value is not attested.} {For `APPROVE WITH UNRESOLVED SHADOW FINDINGS` with full coverage, retain the unresolved-finding rendering and append `Prompt attestation caveat: {serialized JSON array}.` for an addenda array, `Prompt attestation not recorded.` when absent, or `Prompt attestation value is invalid.` for any other present non-`"none"` value; do not change the verdict.} {If `coverage` is `"not_verified"`: "Shadow agreement NOT verified — {reason}; the loop's tentative verdict stands but was not independently audited." If `reason` is empty, null, or absent, substitute `shadow coverage was not verified (specific reason not recorded)`.} {If the final iteration records `shadow_skipped` and no `shadow` block (evaluate before the missing-block arm): "Shadow pass skipped — iteration 1 was clean, so no shadow was owed; this verdict was not independently audited inside the loop, and the caller's PR-level review is that pass."} {If the verdict is non-REJECT but no iteration has a `shadow` block or `shadow_skipped`: "Shadow agreement NOT verified — the shadow result was not recorded (workpad write may have failed); shadow fan-out dispatched: {this run launched the Step 2.6 fan-out | no shadow fan-out was ever dispatched | not established}; the loop's tentative verdict stands but was not independently audited." Read that dispatch fact from this run's own record of whether the parent launched the fan-out, never from the missing block, because the caller's coverage record needs it as its `dispatch` operand. **This state is not a clean pass:** the caller records it as `coverage=not-verified` with the true `dispatch` value (`attempted`, `never`, or `unestablished`), and where the caller maintains a workpad — the `/prflow:implement` orchestrator — a run that never dispatched has no disposition available and stops at a non-terminal or `Blocked` status rather than completing.} {If `APPROVE WITH UNRESOLVED SHADOW FINDINGS` lacks its selected current-iter or one-iter-back full-coverage block, use the existing shadow-coverage-not-verified fallback.} {If shadow did not run because the verdict was REJECT: "Shadow pass did not run — final verdict was REJECT before convergence."}

### Phase 1.1.5 cap drops

Phase 1.1.5 dropped M items at the 100-item cap (categories: dependency_interaction: K1, api_contract: K2, ...). {Omit this subsection entirely if M == 0 across all iters.}
```

If a workpad is missing or unreadable, omit the corresponding row and append a one-line note: `Iter K workpad unreadable; coverage row omitted.` Coverage rendering never blocks the final verdict.

Coverage and the Run telemetry summary (below) both consume the per-iter workpads. Read each `iter-<K>.json` once into memory at Loop Exit and render both sections from the same in-memory array — do not re-open files.

### Run telemetry summary

After the verdict line, print a compact telemetry table to chat (informational only — best-effort). Aggregate across all iterations by reading every `iter-<K>.json` workpad and summing per-phase counts.

For each agent invocation during the run, record (these are the same per-phase values that Step 7 persists into each `iter-<N>.json` workpad's mandatory `telemetry` block — capture them as the phase runs so Step 7 has them, don't reconstruct them here):
- `calls` / `agent_call_count` — increment by 1 per Agent / Task tool call in that phase.
- `tokens` / `total_tokens` — parse the `usage.total_tokens` value from each agent's tool-result `<usage>` block when present. If one source's value is missing, skip *that source* silently; if no figures were established at all, persist the literal `"unavailable"` marker — never omit the telemetry key or publish JSON `null`.
- `wall_clock_s` — measure elapsed time between phase enter and phase exit using the orchestrator's clock.

Phase boundaries (matching the workpad schema): `phase_0`, `phase_0_5`, `phase_1`, `phase_1_5`, `phase_2`, `phase_3`, `step_2_5`, `step_2_6` (shadow pass), `phase_4_x` (covers Phase 4.1–4.3 + Loop Exit final-report emission).

Render as:

```
## Run telemetry
| Phase | Iter | Calls | Tokens | Wall-clock |
| --- | --- | --- | --- | --- |
| Phase 1 | 1 | 2 | ~9.4k | 28s |
| Phase 1.5 | 1 | 1 | ~3.1k | 11s |
| Phase 2 | 1 | 39 | ~140k | 4m12s |
| Phase 3 | 1 | 5 | ~48k | 3m00s |
| Phase 2 | 2 | 27 | ~95k | 3m40s |
| ... | | | | |
| **Total** | | 52 | ~310k | 11m05s |
```

Notes:
- Token counts are approximate (best-effort parsing of `<usage>` blocks). Mark with `~` to signal estimation.
- Failures to collect telemetry are non-fatal — print whatever was captured, omit rows with no data.
- Skip the table entirely when no iterations produced workpads (e.g. catastrophic early failure).

### Subagent effectiveness trace

After the Run telemetry table, derive and persist the per-run subagent effectiveness trace. This is gated behind a config flag (on by default) and is best-effort and non-fatal: a missing/unreadable workpad, an absent `phase3_dispatched` field, or a write failure logs a warning and the loop still emits its normal verdict. Never abort the loop here.

All derivation lives in `lib/efficiency-trace.jq` (a mechanical jq filter, no LLM) behind the `lib/efficiency-trace.sh` wrapper. The wrapper reads the gating flag itself, so when the flag is off it emits nothing and no file is written.

Invoke both helpers directly — no `bash` prefix. `config-get.sh` below and `efficiency-trace.sh` in step 3 are executables resolving to a `.prflow/vendor/prflow/…` path, never `bash <path>`. Resolved-path allow-list entries (`Bash(.prflow/vendor/prflow/lib/efficiency-trace.sh:*)`, `Bash(.prflow/vendor/prflow/scripts/config-get.sh:*)`) match on the command's leading token after expansion; a `bash`-prefixed command starts with `bash` and matches nothing, so on a headless run the prompt is denied and the trace is silently skipped. Direct invocation requires `lib/efficiency-trace.sh` to keep its executable bit (it is committed `+x`); never re-add a `bash` prefix to dodge a missing bit.

1. Read the gating flag via the config helper (use the portable skill-dir-anchored path so the read is cwd-independent, matching how this engine invokes `match-deferrals.py` / `dismiss-stale-rejections.sh`). Discriminate a resolver failure from an intentional flag-off with a single-statement `if !` — `config-get.sh` exits non-zero with empty stdout when `python3` is missing or `config.json` is malformed, and an empty `ENABLED` would otherwise fall into the "not true → skip" branch indistinguishably from `false`:
   ```bash
   # `if !` reads config-get's OWN exit status — never a captured rc read in a later
   # statement (an inline-bash runner that strips such cross-statement variable reads —
   # Copilot CLI / Cursor / Codex CLI / Gemini CLI — would leave the rc empty and make the
   # fail check inert). On a resolver failure, warn and force ENABLED=false so the read
   # fails CLOSED (skips the trace) rather than masquerading as a deliberate flag-off.
   # Do NOT redirect stderr to a file: a cloud harness refuses the redirect construct outright,
   # so the fence returns no output at all. The warning below therefore carries no cause — the
   # stderr does not exist until this same statement runs, so no slot in it can be rendered.
   if ! ENABLED=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .prflow_review_and_fix.efficiency_telemetry_enabled true); then
     echo "::warning::devflow efficiency-trace gate read failed (config-get.sh rc≠0) — skipping trace; cause follows"
     ENABLED=false
   fi
   ```
   When that warning fired, emit the cause as a separate second warning — read this fence's own tool result and emit `::warning::devflow efficiency-trace gate cause: <the first line of the stderr it showed, or the literal stderr=empty>`.
   If `ENABLED` is not `true`, skip this entire section — render no trace and write no file under `.prflow/logs/`. (The wrapper re-checks the flag itself; the read here is what gates the render below. A stripped-empty `ENABLED` is likewise not `true`.)

2. Resolve the run slug and run-id. `<slug>` is `pr-<N>` in PR mode or the sanitized current branch name in branch mode; `<run-id>` is the per-run discriminator computed once at loop start (see the Run-scoping rule in `references/loop-control.md`). The run's workpads live in the run-scoped directory `.prflow/tmp/review/<slug>/<run-id>/`. The per-run record filename is keyed by `<run-id>` (`<slug>-<run-id>.json`), not a fresh `date` timestamp: the agent's Loop-Exit write here and the Layer-3 `lib/efficiency-trace.sh --persist` backstop must resolve the *same* path, or they would each write a duplicate record for one run. The run-id already embeds a timestamp on local runs (`local-<ts>-<attempt>`) and the run number on cloud runs, so it stays unique across runs while being deterministic *within* a run.

3. Render the trace to chat. Discriminate the trace's failure via a single-statement `if !` so a real failure surfaces a reason rather than degrading silently to an empty skip. The trace is read-only (renders to chat); the durable per-run record is derived and persisted to the telemetry branch by the single `--persist` call in "Persisting observability artifacts" below, which reads these same run-scoped workpads:
   ```bash
   WORKPAD_DIR=".prflow/tmp/review/<slug>/<run-id>"   # run-scoped: the trace must read THIS run's iter-*.json, not a sibling run's
   # Render the Markdown trace to chat. Use ::warning:: (not a plain echo) so a
   # failure surfaces in the Actions UI on a headless run; and detect the
   # all-workpads-malformed case, where the helper exits 0 with empty stdout (the
   # `elif [ -z "$TRACE" ]` arm reports it) — print an explicit notice so it isn't a silent no-op.
   # `if !` reads the helper's OWN exit status — never a captured rc read in a later
   # statement (a cross-statement-variable-stripping inline-bash runner would leave it empty).
   # Do NOT redirect stderr to a file: a cloud harness refuses the redirect construct outright,
   # so the fence returns no output at all. Neither warning arm below carries a cause — the
   # stderr does not exist until this same statement runs, so no slot in it can be rendered.
   if ! TRACE="$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/efficiency-trace.sh --workpad-dir "$WORKPAD_DIR" --slug "<slug>" --mode trace)"; then
     echo "::warning::devflow efficiency-trace unavailable (rc≠0); cause follows"
   elif [ -z "$TRACE" ]; then
     echo "::warning::devflow efficiency-trace produced no output (all workpads unreadable/malformed?); cause follows"
   else
     printf '%s\n' "$TRACE"
   fi
   ```
   When either warning arm fired, emit the cause as a separate second warning — read this fence's own tool result and emit `::warning::devflow efficiency-trace cause: <the first line of the stderr it showed, or the literal stderr=empty>`.
   Print the rendered Markdown trace (the `--mode trace` output) into the chat report, after the Run telemetry table. The trace assigns each dispatched subagent exactly one verdict — unique-effective, corroborating, noise, or null (see `lib/efficiency-trace.jq`'s header for the derivation rules) — shows the per-iteration diff profile (the Phase 0.5 flags) and verification posture, the Phase-3 dispatch count, and flags any iteration that applied zero fixes as having added nothing. The repo-relative helper paths here resolve against the repository root.

4. The record and the durable workpad copy are not written into the working tree and not committed on the current branch; they are derived from this run's tmp workpads and persisted to the durable telemetry branch by the single `--persist` call in "Persisting observability artifacts" below — mandatory on every writable run, local included, never skipped (including when this skill is driven interactively/inline by an orchestrator). The push lives inside the helper, so local mode does not depend on the feature branch ever being pushed. The record carries the per-phase/per-iteration cost telemetry forward from the workpads.

If `lib/efficiency-trace.sh` is missing or errors, the trace step above already emits `Effectiveness trace unavailable: {reason}` to chat; proceed — the verdict is unaffected.

### Persisting observability artifacts

Persist this run's observability artifacts — the effectiveness record (`.prflow/logs/efficiency/<slug>-<run-id>.json`, when telemetry is enabled and the run had readable iterations) and the durable workpad copy (`.prflow/logs/review/<slug>/<run-id>/`) — to the durable telemetry branch with a single `--persist` call. The helper derives the record and stages the durable workpad copy from this run's own tmp workpads, then writes them onto the long-lived orphan branch via git plumbing and pushes — without committing anything on the current or default branch, and without touching the working tree or `HEAD`. This persist step is mandatory on every writable run — it is the most-dropped step when this skill is driven inline by an orchestrator (see Common Mistakes), so treat it as non-skippable, not best-effort-optional:

```bash
# Derive + durably persist this run's record and workpad copy to the telemetry
# branch. Everything — the record derivation, the durable copy, the compare-and-
# swap ref advance, and the push (with a fetch/re-parent retry loop) — lives inside
# the helper, so this is the SAME code path a local run and a cloud run use; the
# ambient git credential is the only difference (cloud: the workflow token; local:
# the developer's own credentials). Best-effort and exit-0: when the branch cannot
# be pushed (offline, no remote, a read-only fork-PR token) the local telemetry ref
# still advances and a ::warning:: is emitted — the loop is never aborted. Invoke the
# helper directly (no `bash` prefix) so the resolved-path allow-list entry matches on
# a headless run. (No `|| true`: --persist is exit-0 by contract, and a trailing
# `|| true` would introduce an ungranted `true` command head — silently refused on
# the cloud command path per the head-grant rule — the same reason review
# Phase 4.5's persist fence drops it.)
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/efficiency-trace.sh --persist --workpad-dir ".prflow/tmp/review/<slug>/<run-id>" --slug "<slug>"
```

Run this on every writable run; skip it under the read-only cloud `review` profile (`contents: read`), where the tree — and now the telemetry-branch push — is not writable and the run's surface is the PR comment. The helper is a clean no-op when nothing new needs persisting (an idempotent re-run derives no new record and the branch's tree is unchanged, so no new branch commit is made). Because persistence targets a dedicated branch that shares no history with `main` and is never merged into it, the current branch's history and the reviewed diff are unaffected.

### Base-branch update checkpoint 3 — Loop Exit (terminal pushed state)

Only in PR mode with `--push-each-iteration` (a direct invocation without the flag never touches the base — the same contract the per-iteration checkpoint in Step 3 item 6 carries; and the whole mechanism honors the consumer off-switch `prflow_implement.update_branch_checkpoints`, which governs this checkpoint even inside a standalone `/prflow:review-and-fix --push-each-iteration` run). A standalone `/prflow:review-and-fix <N> --push-each-iteration` never reaches `/prflow:implement`'s Phase 4.3, so this final checkpoint is what keeps the terminal pushed state the review tier evaluates current. After the observability commit above, invoke the shared checkpoint helper once more:

First Read `../implement/references/base-update-checkpoint.md` relative to this skill's directory and require its exact `prflow:implement-shared-ref` boundary markers. Use that shared outcome contract with the standalone loop's record/stop adaptation; never load the implement setup phase.

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/update-branch-checkpoint.sh
```

Handle the token by the context split exactly as Step 3 item 6 does (implement-driven → issue workpad + `Blocked` hard stop; standalone → Loop-Exit record + native "stop and report").

Loop-exit suite rule. Re-run the project test suite at Loop Exit whenever a Checkpoint-3 merge landed after the loop's last suite run — a per-iteration `UPDATED` *or* this loop-exit `UPDATED`, including the final iteration's `UPDATED` even when this loop-exit checkpoint itself reports `UP_TO_DATE` (a suite keyed on the loop-exit token alone would let the final iteration's merge ship with no local verification and no review pass having seen it). This suite launch is coordinated by the same single-flight helper (see the Single-flight verification coordination note in `references/fixing.md` Step 3's test-run step). This trigger does not fire when the loop's caller is `/prflow:implement`: Phase 4.3 owns that run's exactly-once whole-suite obligation, so a loop-exit re-run there would double-pay it. It fires unchanged for a standalone caller, and a loop that cannot establish which caller it has treats itself as standalone and fires. Read the caller from the axis the focused-selection sink already routes on — the issue workpad inside `/prflow:implement` versus `iter-<N>.json` standalone — introducing no new flag, field, or counter.
<!-- Authoring constraint: keep this caller distinction invocation-derived — the same axis the focused-selection sink routes on — and never degrade it to workpad-presence-only inference. A workpad's presence or absence tracks things other than the caller, so that inference is what would produce an affirmative-but-wrong inside-implement classification, which the fail-closed clause cannot catch: it fires on an unestablished caller, never on a confidently wrong one. -->

A standalone loop owes an honesty floor before that suite rule: it verifies every surface it changed at the narrowest covering target on every tier. Past that floor it pays the whole-suite pass itself only where nothing outside the run will exercise the broader suite over this tree. Where it publishes to a PR whose merge a check outside the run gates by exercising the broader suite, the loop emits its findings verdict without that pass and never words the verdict as a claim about the broader suite; a loop that cannot establish whether such a check exists takes the whole-suite result.

The operand this rule reads is named and durable, not a remembered fact. Decide it mechanically: re-run the suite iff this loop-exit checkpoint printed `UPDATED`, or any iteration's persisted `iter-<K>.json` carries `base_checkpoint.token == "UPDATED"` (the bare token word — item 6 requires the count be split into `behind_by`, precisely so this equality test can match; a record storing the helper's printed line whole would hold `"UPDATED 3"` and this test would be false for every real merge). No "since the last suite run" qualifier is needed and none is used: item 4's suite run always precedes item 6's checkpoint within the same iteration, so any recorded `UPDATED` is necessarily later than that iteration's suite run.

Item 6 requires `base_checkpoint` on every iteration whose checkpoint ran, in both contexts, and Loop Exit already reads every `iter-<K>.json` into memory (see the Coverage / telemetry sections, which read the same array) — so this rule consults a persisted field, never the orchestrator's recollection of "an `UPDATED` landed a few iterations ago." A rule keyed on remembered state fails open exactly when a long loop's context is compacted, which is when a mid-loop base merge is most likely to have been forgotten.

**Absent comparand ⇒ fail closed — and "absent" means the *field*, not only the file.** The dangerous shape is not a missing `iter-<K>.json`; it is a present, readable record whose `base_checkpoint` is missing — which is what the `--persist` synthesis backstop produces (it reconstructs only the `ITER_SYNTH_EXPECTED_FIELDS` set, carrying no `base_checkpoint`), and what a degraded or hand-run iteration produces. Read literally, such a record is indistinguishable from the legitimate "the checkpoint never ran" case, and reading it as "no merge landed" is a silent fail-open. So discriminate on whether the checkpoint *could* have run, not on the field alone: for any iteration that made a fix commit while `--push-each-iteration` was set (a run-level flag, so this is knowable without the record) the checkpoint DID run — so a missing, unreadable, `synthesized`, or `base_checkpoint`-less `iter-<K>.json` for that iteration is an ABSENT COMPARAND, never a "no merge landed": re-run the suite and record that the decision was made without a readable per-iteration record. Only an iteration that made no fix commit, or a run without the flag, legitimately carries no `base_checkpoint` — that, and only that, reads as "no merge landed."

A resolved `CONFLICT` needs no loop-exit re-run: it records `base_checkpoint.token == "CONFLICT"` so the `UPDATED` test above does not fire on it, and that is safe because the `CONFLICT` arm runs the project test suite on the resolved tree before committing. Its explicitly-permitted "suite unrunnable on this tier → commit and push locally-unverified" sub-arm is the exception — there the merge ships unverified, the resolution is recorded as locally-unverified and CI is the validating gate, so do not read the `UPDATED`-only test above as covering it.

Three arms: a pass finishes the loop normally; an absent / ungranted / unrunnable suite proceeds with a locally-unverified record (CI validates); a failure is reported loudly in the chat report and recorded in the Loop-Exit record naming the merge commit — the state is already pushed, so there is no publish to withhold, and the loud record is the honest terminal action.

### Completion-evidence check (Loop Exit discharge of the receiving-review item)

This is the loop's discharge site for the `prflow:fix` Verification Gate's completion-evidence item (that skill's scoping sentence names Loop Exit as this site — PRFlow's own dispatch surfaces name the plugin-qualified copy, never a side-by-side upstream `fix` copy that lacks this gate). Run the bundled validator over this run's run-scoped records and quote its verdict line in the final report. The validator is `scripts/check-completion-evidence.py`; invoke it via the portable anchor as a single leading-token vendored literal (the granted cloud form — its review-tier permitted-ness is unrecorded, so a refusal is handled by the degraded arm below rather than treated as impossible; locally the `python3 <path>` fallback), never a `bash <path>` wrapper.

Operands (all run-scoped — the loop states what it cites; the validator checks only what is stated):
- Verification record — the durable status handle's flight file (`.prflow/tmp/verification-flights/<flight_key>.json`), read as the single loop-side verification operand. Never a raw per-iteration `verification_evidence` record: a per-iteration record's run can legitimately predate Step 3.5's inner re-fix commits, and a converging no-fix iteration legitimately records a whole-run skip.
- Findings inventory — the per-iteration Phase-3 findings union from the run's `iter-<N>.json` records, written to a run-scoped temp file carrying `claim_context_token: "<run-id>"` and a `findings` array; each finding the loop routed into the effective fix set is marked `in_fix_set: true` (a REJECT-driver additionally `reject_driver: true`) by the loop's own routing — the validator performs no severity comparison.
- Disposition ledger — the `fix_decisions` union, written to a run-scoped temp file as `{ "fix_decisions": [ … ] }`.
- Deferrals — this run's `deferrals.json` (the Pre-mapping manifest above), or omitted when zero entries survived (the established zero-deferral state — a `pass`-arm input, never `missing-evidence`).
- Claim-time candidate identity — computed by the loop (the same content-based derivation the reception producer ships) and passed with `--claim-identity`; `--context <run-id> --context-mode loop`.

Identity-keyed refresh (recovery arm). When the claim-time candidate identity differs from the verification record's recorded identity — Step 3.5 inner re-fixes are the routine producer of this state; the ordinary verify-then-commit iteration compares equal and triggers nothing — refresh the verification record first: one suite re-run recorded through the handle before validating, the recovery arm of a would-be `stale-candidate`. Like the base-merge trigger above, this refresh does not fire when the loop's caller is `/prflow:implement` — Phase 4.3's completion-evidence flight refreshes the record for the final tree there — and it fires unchanged for a standalone caller, with a loop that cannot establish its caller treating itself as standalone and firing; read the caller from the same focused-selection-sink axis (issue workpad versus `iter-<N>.json`). A converging no-fix final iteration validates against the handle's last completed run: the content is unchanged, so the recorded identity still equals claim time.

Build the run-scoped operand files (findings inventory + `fix_decisions` union) from this run's `iter-*.json` via the granted jq wrapper first, then invoke the validator as a single leading-token vendored literal (never a `VAR="$(…)"` capture — that composite shape is a denied/unproven cloud shape; read the verdict line from the printed tool output instead). `<slug>`/`<run-id>` are this run's values; `<flight_key>` is the handle key from the Step-3 coordination:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/check-completion-evidence.py \
  --context "<run-id>" --context-mode loop \
  --verification-record ".prflow/tmp/verification-flights/<flight_key>.json" \
  --findings-inventory ".prflow/tmp/review/<slug>/<run-id>/completion-inventory.json" \
  --disposition-ledger ".prflow/tmp/review/<slug>/<run-id>/completion-dispositions.json" \
  --deferrals ".prflow/tmp/review/<slug>/<run-id>/deferrals.json" \
  --claim-identity "<claim-time candidate identity>"
```

Quote, record, and carry the token. Quote the single verdict line verbatim in the final chat report, and record it in the workpad. Parse its token (the second field). When the token is not `pass`, append `— completion evidence: <token>` to the reported final verdict line (`<verdict> — completion evidence: <token>`). Where an issue workpad exists (implement-driven runs), additionally record a `## PRFlow Reflections` bullet quoting the verdict line — a non-empty reflections list already forces retrospective analysis, so the outcome is durable with zero status-word mirror edits (the closed status-word set, glyph map, and retrospective parsers are untouched). A validator invocation that produced no verdict line — silent denial (denied/absent helper/no output) and internal failure (exit 2) alike — is the degraded arm: report `degraded: unvalidated (<reason>)`, never read absent output as `pass`.

### Persistence self-check (Layer 2 — warn-only backstop)

After the persist block above, on a converged writable run with telemetry enabled, run the standalone self-check so a dropped persistence step leaves a loud breadcrumb rather than a silent hole in the telemetry dataset. It only warns — it never writes, never commits, never changes the verdict, and never aborts (it always exits 0):

```bash
# Skip under the read-only cloud `review` profile (no Loop Exit there) and on a
# non-converged early failure. The helper is itself silent when telemetry is off,
# so this is doubly safe. WORKPAD_DIR is the run-scoped dir from the trace block;
# <slug> is this run's slug. Invoke the helper directly (no `bash` prefix) so the
# resolved-path allow-list entry matches on a headless run. (No `|| true`:
# --self-check is exit-0 by contract, and a trailing `|| true` would introduce an
# ungranted `true` command head — silently refused on the cloud command path per
# the head-grant rule — the same reason the --persist fence above drops it.)
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/efficiency-trace.sh --self-check --workpad-dir ".prflow/tmp/review/<slug>/<run-id>" --slug "<slug>"
```

If the self-check warns that the record or the workpads were not persisted, the deterministic recovery is `lib/efficiency-trace.sh --persist` (Layer 3) — the same command the `Stop` hook and the cloud wrapper invoke. The warning is observability, not a gate.

### Tick the final Blueprint row

As the loop's last terminal-work step, after the persistence self-check above, route the final Blueprint row — text `Run complete — everything this run owed`, tick substring `Run complete` — by the held progress surface:

- Exact `progress_surface = workpad` → tick the row in the cloud-safe helper shape: invoke `.prflow/vendor/prflow/scripts/workpad.py update <issue> --tick-progress "Run complete"` with the issue number substituted as a literal (never `$ISSUE_OVERRIDE`), falling back to the portable anchor `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update <issue> --tick-progress "Run complete"` only on a `command not found` / `No such file` / rc-127 reading. This applies in both PR and current-branch modes. An already-ticked row is the expected idempotent no-op on re-entry; a missing row or update failure remains visible in helper output and never falls back to creating or patching a PR progress comment.
- Otherwise, when `$PR_NUMBER` is non-empty, tick that row in this run's progress comment. When `$PR_NUMBER` is empty, no PR-comment target is selected and no PR-comment tick is attempted.

Tick it on every termination that reaches this terminal work — converged, capped, and final REJECT alike — and leave it unticked on an abnormal stop-and-report exit (an unresolved base conflict, say) that never reached here. Here the tick asserts only that the loop reached its terminal work. This path makes no corrective delivery attempt, because it posts no verdict to GitHub at all.

---


<!-- END loop-exit.md -->
