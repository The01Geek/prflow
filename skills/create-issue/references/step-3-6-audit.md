<!-- prflow:create-issue-ref step=3.6 file=skills/create-issue/references/step-3-6-audit.md start -->

### Step 3.6: Fresh-context audit bootstrap and offer (before the user sees it)

After Step 3.5 passes and before Step 4 presents anything, a fresh-context audit subagent is available. Every audit round is offered to the user before it opens, at Step 4's single pre-approval pause after the rendered draft is on screen; a user who is satisfied elects none, and a run that elects none is audited by none and files unaudited. This step supplies the round machinery; the election that opens any round lives at that pause.

Step 3.5-record entry gate (blocks the audit dispatch only). Before anything below runs, confirm this run's latest `## Steelman record` `### pass <n>` entry in `.prflow/tmp/create-issue/<slug>/issue-derivation-<slug>.md` per the entry-confirmation contract (item 9) of `references/step-3-5-steelman.md`. A missing or stale entry is a skipped Step 3.5 and blocks only this dispatch, not issue creation.
#### The bootstrap member, and the deferred audit-round members

This step is delivered as an ordered set — this entry plus three procedure members — but the members load at two different times:

1. `references/step-3-6-audit-shared.md` (part 1) — the run bootstrap (`init` and the nonce, the canonical-draft write and its two Step 3.5 gates, and the draft-root binding), Ledger maintenance after a revision, and the Staged canonical-draft write (the last two also referenced by name from Step 4). **Load this member on every entry into this step and run the bootstrap it carries**, because the bootstrap runs on the path to Step 4's pre-approval pause whether or not any audit round is elected.
2. `references/step-3-6-audit-dispatch.md` (part 2) — round kind and dispatch scope, the dispatch arm, the information diet, the carriage check, and instruction generation and rendering.
3. `references/step-3-6-audit-adjudication.md` (part 3) — the audit report, recording the return and adjudicating every finding, per-finding evidence, cross-round reconciliation, the Step 3.6 → Step 4 boundary read, coverage and calibration, the call sequence, and the fallbacks.

Members 2 and 3 carry only audit-round procedure. **A run that elects no audit round never loads them.** The election that opens any round lives at Step 4's single pre-approval pause (`references/step-4-present-create.md` sub-step 3a); only a run whose user accepts that offer loads the pair — the same trigger-time reference-loading pattern `references/degradation-routing.md` applies to its own predicate-gated members (this pair is governed here, not by a row in that file).

Load each member under the skill root's *Reference routing* boundary-marker contract (first line its `start` marker, last line its matching `end` marker, each naming that member's own path); each member's literal second line is `<!-- prflow:create-issue-set step=3.6 part=k of=3 -->`. Hold the bootstrap member (part 1) before any `init`, canonical-draft write, or state-owner mutation. Hold the dispatch and adjudication members (parts 2 and 3) as a whole pair before any dispatch — held only when both cleared their own boundary gate and you hold parts 2 and 3 at a consistent `of=3`. Run no dispatch until that pair has passed.

A required-member load failure — an attributable per-member outcome (`denied`, `empty`, `missing`, `truncated`, `duplicate`, `reversed`, `noncanonical`, `misrouted`) or the set-level `set-incomplete` (a missing `part=k`, or members disagreeing on `of=n`) — routes through the Step 3.6 entry row of `references/degradation-routing.md` to the one bounded in-chat audit round it names, exactly once before audit work, and never blocks issue creation.

#### The state owner owns the lifecycle

**Obey the state owner (the contract governing this whole step).** The deterministic audit lifecycle — transitions, round numbering, budgets, dispatch-arm routing, the T1/T2 triggers, override records, presentation eligibility, and the audit-summary field set — is owned by the bundled `issue-audit-state.py`, not by this prose. This step records each lifecycle event through that tool and obeys the answer it returns. Never re-derive a transition, a budget, a retry bound, a dispatch arm, or eligibility from this prose or remembered history. A draft you are certain is clean is presented for approval only after `query-eligibility --mode approve` answers `eligible=yes`. Your confidence that a revision addressed every finding is not an eligibility answer, and neither is a clean no-options gate.

**An illegal-transition rejection is NOT an unavailability signal.** When a mutation exits non-zero and its breadcrumb names an illegal transition — a nonce mismatch included — call `query-next-action` and obey that answer. Never route an illegal transition to the `state-owner unavailable` fallback below.

Invoke the tool with `python3` plus the portable anchor, resolved inline in the statement that uses it (never captured into a variable a later statement reads), substituting the `<slug>` and the nonce you hold:

```bash
python3 "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/issue-audit-state.py query-eligibility "<slug>" --nonce "<nonce>" --mode approve --draft-file "<absolute issue-draft-<slug>.md path>"
```

When eligibility refuses with `draft-undigestible` — the draft file could not be read or hashed (stderr `query: could not hash draft file …`) — re-establish it by re-running the canonical-write step (re-stage, apply, confirm landed); if git or file reads are broken so the re-write cannot help, route to the `state-owner unavailable` fallback below (an environmental signal of that fallback's environmental class 2). When it refuses with `no-digest-supplied` — a file-arm clean epoch queried with no `--draft-file` — re-issue with the canonical draft file path: a caller omission, not a revision or environmental failure.

<!-- prflow:create-issue-ref step=3.6 file=skills/create-issue/references/step-3-6-audit.md end -->
