# PRFlow system overview

This page gives coding agents and developers the shortest reliable map of PRFlow before they plan a change. It explains the major surfaces and points to the focused page that owns each one.

## Current behavior

PRFlow is a Claude Code plugin that carries a request through issue shaping, implementation, verification, review, documentation, and a human handoff. The local tier runs inside Claude Code. The optional cloud tier runs selected workflows through GitHub Actions.

The normal delivery path is:

1. `/prflow:create-issue` turns a rough request into an approved, implementation-ready issue.
2. `/prflow:implement` creates or adopts a branch, plans and implements the change, verifies it, runs the review-and-fix loop, and updates documentation.
3. `/prflow:review` can perform an independent review of a pull request.
4. A developer performs the final review and merge.

PRFlow prepares a review-ready pull request. It does not merge the pull request on the developer's behalf.

The system is divided into six runtime surfaces:

- Skills define the command-level orchestration and gates.
- Agents perform specialized discovery, planning, verification, and review work.
- Workflows connect comments, events, workpads, branches, and pull requests.
- Operations define installation, cloud execution, permissions, and publishing.
- Improvement loops measure behavior and turn recurring evidence into proposed changes.
- Architecture pages describe the boundaries shared by those surfaces.

## Why it works this way

The system keeps specification, implementation, verification, review, and documentation connected because a code change is not ready for human review until its behavior and supporting explanation agree. The separate local and cloud tiers exist because the same workflow can run interactively in a developer's checkout or headlessly in GitHub Actions with different trust, permission, and verification constraints.

Human review remains the final control point. Automated review, shadow review, and the weekly improvement loop provide evidence and proposed changes; they do not replace the developer's merge decision.

## Boundaries and failure paths

The executable skill and workflow surfaces are authoritative when this overview conflicts with a detailed page. A focused page must be consulted before changing one of the system surfaces listed above because the relevant gates and failure paths are owned there.

The cloud tier has different trust boundaries from the local tier. Read [the execution model](execution-model.md) before changing cloud checkout, credential, prompt, or tool-permission behavior.

## Source of truth

- `README.md` — product intent, supported command path, tiers, and high-level repository layout.
- `skills/*/SKILL.md` — executable skill contracts.
- `agents/*.md` — executable agent definitions.
- `.github/workflows/*.yml` — cloud triggers and job orchestration.
- `.prflow/config.schema.json` — configuration shape and descriptions.
- `scripts/` and `lib/` — runtime helpers, gates, and verification mechanisms.
- `lib/test/run.sh` — repository verification suite and documentation-related contract checks.

## Related topics

- [Execution model](execution-model.md)
- [Skills](../skills/index.md)
- [Agents](../agents/index.md)
- [Workflows](../workflows/index.md)
- [Operations](../operations/index.md)
- [Improvement loops](../improvement-loops/index.md)
- [Historical cutovers](../cutovers/)
