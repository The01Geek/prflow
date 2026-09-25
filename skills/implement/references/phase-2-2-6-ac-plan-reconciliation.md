<!-- prflow:implement-ref step=2.2.6 file=skills/implement/references/phase-2-2-6-ac-plan-reconciliation.md start -->

#### 2.2.6 AC-Plan reconciliation — procedure

Reconciliation steps:
```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER \
    --rewrite-ac "{fragment naming the one OLD criterion}" "{FULL NEW criterion text, verbatim}" \
    --scope-decision-rewritten <PR> "{FULL OLD criterion text, verbatim}" "{FULL NEW criterion text, verbatim}" \
    --note "AC rewrite: {old verbatim} → {new}. Motivated by: {structural change}"
```

Pass `--scope-decision-rewritten` in the same call as `--rewrite-ac`, so the text change and its machine-readable record land together; the review engine reads that record, never the free-text `--note`. `<PR>` is this run's draft PR number once §3.1 has run — the `number` of its `pr-open` record, or the workpad `**PR:**` line when that record is no longer in context — and `pending` before §3.1, which binds only the records already written when it runs.

`--rewrite-ac` replaces the whole row: its OLD may be any fragment that picks out one row, but its NEW is the complete new criterion. The record takes the criterion's *entire* text as it stands immediately before the rewrite and as it will read after, because the review engine matches it by whole-criterion equality — a fragment matches nothing and the criterion reads as an unexplained drop. When the call carries records, `workpad.py` refuses it unless rewritten rows and records pair one-to-one; correct the operand its error shows disagreeing and re-send.

Why the workpad criterion set is trustworthy as a review comparand, and what falsifies it. The review engine may treat the workpad's `## Acceptance Criteria` as authoritative because every writer that changes the set's membership or a criterion's text either emits a scope-decision record or can only ever widen the set — never narrow it:

- Record-emitting writers: §2.2.5's `--replace-acs-file` narrowing, and the `--rewrite-ac` call sites (this one, and phase-3-ac-gate.md §3.4's retroactive `(post-merge)` retag in post-merge-tagging.md).
- Widening-only writers: phase-1-intake.md §1.3's two `--replace-acs-file` mirrors — the fresh-workpad mirror and the resume-path mirror — which need no record because each sets the workpad's section equal to the issue body's criteria; that is never a narrowing, so `_acs_pr_identity_ok`'s superset early-return (`workpad_norm >= issue_norm`) accepts it with no record to explain.
- No record needed: `--tick-ac` and `--tick-ac-n` change only box state, which the engine's normalized comparison already ignores.

The assumption is falsified if any writer path can change the set's membership or a criterion's text without emitting a scope-decision record.

**Criterion defect (the cannot-all-be-met trigger).** When a rewrite resolves the defect without dropping a guarantee Desired Behavior states, rewrite the fewest criteria that resolve it in one `workpad.py update` call shaped as the fence above, with one `--rewrite-ac` and one `--scope-decision-rewritten` per rewritten criterion. The new text follows Desired Behavior wherever it decides between the readings and keeps every guarantee the criteria can deliver together. The `--note` quotes the conflicting criterion lines, or names the file that makes the criterion false, in place of the structural change. When no rewrite qualifies — including one that must pick a reading Desired Behavior leaves open — defer each criterion in the conflicting set through §2.2.5, its `--note` naming the conflict, so the follow-up puts the choice to a human. A criterion defect is never resolved only by an implementation workaround or a Reviewer Notes entry.

`--rewrite-ac` preserves the box state (don't tick during the rewrite — Phase 3.4 will tick via `--tick-ac-n` later). This is not scope adjustment — the rewritten AC is still gated in 3.4.

**When the rewrite records a design *deviation* (the plan intentionally diverges from what an AC prescribed), also leave an in-repo breadcrumb comment at the deviation site.** The workpad `--note`/AC-rewrite paper trail lives only on the issue, and blinded shadow reviewers (Phase 3.3's fix loop deliberately withholds loop history) never see it, so a signed-off deviation gets independently re-raised as a finding iteration after iteration. To make the sign-off travel in repo content the reviewer *does* see, add a short comment at the deviating code site naming the parent issue and pointing at the workpad record — e.g. `# Deviates from issue #<N>'s prescribed <X>: <one-line why>; see the workpad AC-rewrite note.` (A pure surface-identifier rewrite with no behavioral deviation needs no such comment; this obligation is scoped to a *deviation*.)

<!-- prflow:implement-ref step=2.2.6 file=skills/implement/references/phase-2-2-6-ac-plan-reconciliation.md end -->
