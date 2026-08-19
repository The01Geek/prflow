<!-- prflow:create-issue-ref step=3.6 file=skills/create-issue/references/step-3-6-audit.md start -->

### Step 3.6: Fresh-context audit (mandatory, before the user sees it)

After Step 3.5 passes and before Step 4 presents anything, dispatch one fresh-context audit subagent.

Step 3.5-record entry gate (blocks the audit dispatch only). Before anything below runs, confirm this run's latest `## Steelman record` `### pass <n>` entry in `.prflow/tmp/issue-derivation-<slug>.md` per the entry-confirmation contract (item 9) of `references/step-3-5-steelman.md`. A missing or stale entry is a skipped Step 3.5 and blocks only this dispatch, not issue creation.
#### The ordered procedure set

This step is delivered as an ordered set — this entry plus three procedure members, loaded in order:

1. `references/step-3-6-audit-shared.md` — Ledger maintenance after a revision; Staged canonical-draft write (both referenced by name from Step 4 too).
2. `references/step-3-6-audit-dispatch.md` — bootstrap, the canonical-draft write and its two Step 3.5 gates, draft-root binding, round kind and dispatch scope, the dispatch arm, the information diet, the carriage check, and instruction generation and rendering.
3. `references/step-3-6-audit-adjudication.md` — the audit report, recording the return and adjudicating every finding, per-finding evidence, cross-round reconciliation, the Step 3.6 → Step 4 boundary read, coverage and calibration, the call sequence, and the fallbacks.

Load each member in that order under the skill root's *Reference routing* boundary-marker contract (first line its `start` marker, last line its matching `end` marker, each naming that member's own path), and hold the set whole before any audit action: each member's literal second line is `<!-- prflow:create-issue-set step=3.6 part=k of=3 -->`, and the set is held only when every member cleared its own boundary gate and you hold parts 1..3 at a consistent `of=3`. Run no `init`, dispatch, or state-owner mutation until the full set has passed.

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
