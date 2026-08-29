# PRFlow delivery lifecycle

This page maps the cross-skill path from a request to a review-ready pull request.

## Current behavior

The normal lifecycle begins with `/prflow:create-issue`, which grounds a request in the current repository and obtains user approval for an issue. `/prflow:implement` then establishes the branch and workpad, implements and verifies the change, runs `/prflow:review-and-fix`, and completes the required documentation phase. `/prflow:review` remains available as an independent review path. The developer performs the final review and merge.

The same logical lifecycle can be entered locally through Claude Code or through supported GitHub comment triggers in the cloud tier. The entry point changes the runtime boundary, not the need for explicit state and evidence.

## Why it works this way

Separating issue shaping from implementation gives the implementer an approved, inspectable specification. Keeping review, documentation, and human merge as distinct handoffs makes each responsibility visible and prevents a successful code edit from being mistaken for a complete delivery.

## Boundaries and failure paths

- Issue creation requires explicit user approval of the draft as presented — saved to a file whose path is shown by default, with the full body printed in chat only on request.
- Implementation cannot skip its mandatory phases or turn an unavailable verification result into completion.
- Review and fix findings remain visible when deferred or unestablished.
- Documentation impact is evaluated separately for internal and external products.
- The final merge remains a human-controlled repository action.

## Source of truth

- `skills/create-issue/SKILL.md`, `skills/implement/SKILL.md`, `skills/review/SKILL.md`, and `skills/review-and-fix/SKILL.md` — command contracts.
- `skills/implement/phases/` — phase handoffs.
- `.github/workflows/devflow.yml` and `.github/workflows/devflow-implement.yml` — cloud entry points.
- `scripts/workpad.py` — durable lifecycle state.
- [`docs/internal/workflow-triggers.md`](../workflow-triggers.md) — event and command routing details.

## Related topics

- [Create issue](../skills/create-issue.md)
- [Implement](../skills/implement.md)
- [Review-and-fix](../skills/review-and-fix.md)
- [Workpad and resume](workpad-and-resume.md)
