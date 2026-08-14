# `/prflow:create-issue`

This page explains how the issue-shaping skill grounds a proposed change in the repository before asking the user to approve an issue.

## Current behavior

The skill starts with a rough user story or bug report. Its first investigation dispatches `/prflow:docs-verify --report-only` peers over the internal documentation and the rest of the tracked tree, using the resolved internal-doc path as the documentation search-space leg. The findings are captured before clarification or drafting continues.

The skill then clarifies the Definition of Ready, independently expands the solution space, drafts the issue, steelmans the draft against the code, runs a fresh-context audit, shows the complete draft to the user, and creates the issue only after explicit approval.

The documentation pass is a code-exploration input. It reports how the topic works today and exposes unestablished duties; it does not treat existing prose as authoritative or edit the repository in report-only mode.

## Why it works this way

Agents plan better when they begin with the repository's current behavior rather than the user's proposed mechanism or stale documentation. The two search-space legs keep internal documentation discovery separate from code discovery while preserving a path from each documented claim to its implementation.

## Canonical owner of the no-options rule

`skills/create-issue/references/issue-template.md` is the single canonical owner of the no-options rule: its unresolved-decision vocabulary, its category structure, its full carve-out set, and the unconditional-acceptance-criterion rule all live there in one section (issue #1688). Every other drafting surface — the create-issue skill root and its clarify/steelman references, the deferral drafter, and the retrospective-audit path — points to that template rather than repeating any part of the enumeration.

Surfaces that can continue after a failed template read carry a compact semantic fallback: the body holds no unresolved implementation decision outside the rule's permitted locations, and every acceptance criterion is one concrete unconditional assertion. This fallback preserves the normative rule without the template's worked vocabulary, and the channels that can disclose the reduction do so — the interactive pipeline reports in chat that the template was unavailable, and the deferral drafter records it in its plan `notes` field. The retrospective-audit subagent applies the same fallback silently: it emits no degradation signal, because a new field or extra text would break its closed single-object JSON response contract, an accepted residual.

## Boundaries and failure paths

- A docs-verify peer must finish and return its structured findings before clarification begins.
- A missing or unreadable internal-doc population is reported as unestablished, not silently treated as no documentation.
- A report-only peer does not write, commit, push, or dispatch another peer.
- A documentation claim that cannot be confirmed against code remains unconfirmed in the findings and cannot be promoted into the issue as fact.

## Source of truth

- `skills/create-issue/SKILL.md` — issue-shaping orchestration and approval gates.
- `skills/docs-verify/SKILL.md` — documentation-first code exploration and report-only contract.
- `skills/create-issue/references/issue-template.md` — canonical owner of the no-options rule (vocabulary, categories, carve-out set, unconditional-criterion rule).
- `skills/create-issue/references/step-2-clarify.md` — clarification and solution-space expansion.
- `skills/create-issue/references/step-3-5-steelman.md` and `skills/create-issue/references/step-3-6-audit.md` — code-grounding passes.
- `scripts/check-verified-premises.py` and `scripts/parse-acs.py` — verified-premise and acceptance-criteria handling.
- `docs/internal/create-issue-context.md` — runtime context and evaluation evidence.

## Related topics

- [System overview](../architecture/system-overview.md)
- [Documentation](documentation.md)
- [Implement](implement.md)
- [Historical cutovers](../cutovers/)
