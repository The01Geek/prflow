# Cutovers

<!-- verified-against: 26c9ad96d 2026-08-25 -->

These are historical implementation and migration records. They explain why a current rule exists, what was moved, and what evidence supported the change. They are not the source of truth for current behavior: start from the relevant page in the categorized documentation and use these records for history or rationale that the current page links to.

The records remain in this directory because their issue-oriented names and links are part of the repository's historical documentation surface.

Each record's frontmatter carries a `kind:` field. `kind: growth` marks a byte-budget justification memo for a prompt-surface size increase — its figures were true at merge time and say nothing about current behavior, so a reader mapping the present system can skip it. `kind: cutover` marks a migration record, and `kind: relocate` a content move.

## Records

- [Internal documentation restructure implementation plan](internal-documentation-implementation-plan.md) — completed 2026-08-12.
- [Issue #693 — issue-body cache](693-issue-body-cache.md)
- [Issue #745 — run.sh CI lint](745-run-sh-ci-lint.md)
- [Issue #1053 — focused-first precondition growth](issue-1053-focused-first-precondition-growth.md)
- [Issue #1374 — deferred review findings relocation](issue-1374-deferred-review-findings-relocate.md)
- [Issue #1557 — Stage 2 self-heal relocation](issue-1557-stage2-self-heal-relocate.md)
- [Issue #1581 — gated conditional Phase 2.3 sweeps](issue-1581-gated-conditional-sweeps.md)
- [Issue #1604 — deferral-drafter pin exposure](issue-1604-deferral-drafter-pin-exposure.md)
- [Issue #541 — reference-reads evidence schema](issue-541-reference-reads-evidence-schema.md)
- [Issue #551 — prompt-mass growth](issue-551-prompt-mass-growth.md)
- [Issue #555 — deferral manifest discovery](issue-555-discover-deferral-manifests.md)
- [Issue #576 — branch-state preflight growth](issue-576-branch-state-preflight-growth.md)
- [Issue #600 — audit prompt renderer](issue-600-audit-prompt-renderer.md)
- [Issue #603 — prompt-mass growth](issue-603-prompt-mass-growth.md)
- [Issue #609 — agent-effort observability](issue-609-agent-effort-observability.md)
- [Issue #611 — create-issue section wiring growth](issue-611-create-issue-section-wiring-growth.md)
- [Issue #613 — create-issue shift-left disciplines](issue-613-create-issue-shift-left-disciplines.md)
- [Issue #614 — create-issue thin-root relocation](issue-614-create-issue-thin-root-relocate.md)
- [Retired create-issue budget record](create-issue-budget.md)
- [Issue #618 — self-apply authorization](issue-618-self-apply-authorization.md)
- [Issue #619 — batched artifact regeneration](issue-619-batched-artifact-regeneration.md)
- [Issue #620 — reception extension port](issue-620-reception-extension-port.md)
- [Issue #628 — quantitative-claim calibration growth](issue-628-quantitative-claim-calibration-growth.md)
- [Issue #640 — direct-pass editor authority](issue-640-direct-pass-editor-authority.md)
- [Issue #655 — conflict oracle](issue-655-conflict-oracle.md)
- [Issue #656 — prompt-mass growth](issue-656-prompt-mass-growth.md)
- [Issue #661 — relocation-drift growth](issue-661-relocation-drift-growth.md)
- [Issue #664 — GitHub API repository-path growth](issue-664-gh-api-repo-path-growth.md)
- [Issue #666 — mutation routing growth](issue-666-mutation-routing-growth.md)
- [Issue #668 — reception artifacts growth](issue-668-reception-artifacts-growth.md)
- [Issue #672 — retrospective-skill redaction note](issue-672-retrospective-skill-redaction-note.md)
- [Issue #705 — staged-draft write growth](issue-705-staged-draft-write-growth.md)
- [Issue #707 — focused-default growth](issue-707-focused-default-growth.md)
- [Issue #708 — audit-coverage growth](issue-708-audit-coverage-growth.md)
- [Issue #709 — audit-dispatch instructions](issue-709-audit-dispatch-instructions.md)
- [Issue #711 — tree-enumeration growth](issue-711-tree-enumeration-growth.md)
- [Issue #719 — verification-evidence marker growth](issue-719-verification-evidence-marker-growth.md)
- [Issue #729 — declared-dimension keys growth](issue-729-declared-dimension-keys-growth.md)
- [Issue #730 — verification-evidence advisory growth](issue-730-verification-evidence-advisory-growth.md)
- [Issue #743 — advisory-adjudication calibration growth](issue-743-advisory-adjudication-calibration-growth.md)
- [Issue #749 — step-one right-sizing growth](issue-749-step1-right-sizing-growth.md)
- [Issue #754 — scaffold reuse growth](issue-754-scaffold-reuse-growth.md)
- [Issue #762 — single-source-of-truth policy growth](issue-762-ssot-policy-growth.md)
- [Issue #792 — final-byte audit coverage](issue-792-final-byte-audit-coverage.md)
- [Issue #793 — round-kinds byte history](issue-793-round-kinds-byte-history.md)
- [Issue #795 — audit-state round trips](issue-795-audit-state-round-trips.md)
- [Issue #815 — deferred acceptance-criteria follow-ups](issue-815-deferred-ac-followups-relocate.md)
