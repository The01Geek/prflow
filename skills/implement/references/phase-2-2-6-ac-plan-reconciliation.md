<!-- prflow:implement-ref step=2.2.6 file=skills/implement/references/phase-2-2-6-ac-plan-reconciliation.md start -->

#### 2.2.6 AC-Plan reconciliation — procedure

Reconciliation steps:
```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER \
    --rewrite-ac "{OLD AC substring}" "{NEW AC substring replacement}" \
    --scope-decision-rewritten pending "{FULL OLD criterion text, verbatim}" "{FULL NEW criterion text, verbatim}" \
    --note "AC rewrite: {old verbatim} → {new}. Motivated by: {structural change}"
```

Pass `--scope-decision-rewritten pending "{FULL OLD criterion text, verbatim}" "{FULL NEW criterion text, verbatim}"` in the same call as `--rewrite-ac`, so the text change and its machine-readable record land together. The PR literal is `pending` for the same reason as in 2.2.5 — §3.1 binds it once the draft PR exists — and the review engine reads that record rather than the free-text `--note`, which carries no criterion identifier.

The two flags deliberately take different text — never "simplify" them into the same value. `--rewrite-ac` performs an *in-place substring replacement* inside the criterion, so its first argument may be any distinguishing fragment. `--scope-decision-rewritten`'s OLD value is stored normalized and is later matched by the review engine as a whole-criterion equality lookup against the full issue-body criterion — so a fragment there simply fails to match, and the criterion is reported to the merge-gating reviewer as an unexplained dropped criterion. Pass the criterion's *entire* text as it stands immediately before the rewrite, and its entire text as it will read after.

Why the workpad criterion set is trustworthy as a review comparand, and what falsifies it. The review engine may treat the workpad's `## Acceptance Criteria` as authoritative because every writer that changes the set's membership or a criterion's text either emits a scope-decision record or can only ever widen the set — never narrow it:

- Record-emitting writers: §2.2.5's `--replace-acs-file` narrowing, and the `--rewrite-ac` call sites (this one, and phase-3-ac-gate.md §3.4's retroactive `(post-merge)` retag in post-merge-tagging.md).
- Widening-only writers: phase-1-intake.md §1.3's two `--replace-acs-file` mirrors — the fresh-workpad mirror and the resume-path mirror — which need no record because each sets the workpad's section equal to the issue body's criteria; that is never a narrowing, so `_acs_pr_identity_ok`'s superset early-return (`workpad_norm >= issue_norm`) accepts it with no record to explain.
- No record needed: `--tick-ac` and `--tick-ac-n` change only box state, which the engine's normalized comparison already ignores.

The assumption is falsified if any writer path can change the set's membership or a criterion's text without emitting a scope-decision record.

`--rewrite-ac` preserves the box state (don't tick during the rewrite — Phase 3.4 will tick via `--tick-ac-n` later). This is not scope adjustment — the rewritten AC is still gated in 3.4.

**When the rewrite records a design *deviation* (the plan intentionally diverges from what an AC prescribed), also leave an in-repo breadcrumb comment at the deviation site.** The workpad `--note`/AC-rewrite paper trail lives only on the issue, and blinded shadow reviewers (Phase 3.3's fix loop deliberately withholds loop history) never see it, so a signed-off deviation gets independently re-raised as a finding iteration after iteration. To make the sign-off travel in repo content the reviewer *does* see, add a short comment at the deviating code site naming the parent issue and pointing at the workpad record — e.g. `# Deviates from issue #<N>'s prescribed <X>: <one-line why>; see the workpad AC-rewrite note.` (A pure surface-identifier rewrite with no behavioral deviation needs no such comment; this obligation is scoped to a *deviation*.)

<!-- prflow:implement-ref step=2.2.6 file=skills/implement/references/phase-2-2-6-ac-plan-reconciliation.md end -->
