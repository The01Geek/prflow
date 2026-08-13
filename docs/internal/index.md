# PRFlow internal documentation

This is the source map for coding agents and developers working on PRFlow. Read the page for the system surface you are changing, then follow its source-of-truth links into the executable skills, agents, workflows, scripts, configuration, and tests.

## Before planning a change

1. Start with [the system overview](architecture/system-overview.md) to place the change in the wider lifecycle.
2. Open the page for the command, agent, workflow, or operational boundary the change touches.
3. Read the page's `Source of truth` and `Boundaries and failure paths` sections before choosing an implementation approach.
4. Follow the relevant tests and guards from the canonical page into the codebase.

## Find documentation by task

| If you are changing or investigating | Start with | Then inspect |
| --- | --- | --- |
| Issue shaping and documentation-first discovery | [Create issue](skills/create-issue.md) | `skills/create-issue/`, `skills/docs-verify/`, and the relevant feature code |
| Implementation phases, verification, or final documentation | [Implement](skills/implement.md) | [Implement verification](skills/implement-verification.md), [Implement documentation](skills/implement-documentation.md), and the phase files |
| Review or review-and-fix behavior | [Review](skills/review.md) or [Review-and-fix](skills/review-and-fix.md) | [Review agents](agents/review-agents.md), [Shadow review](agents/shadow-review.md), and the review skill sources |
| Command triggers, handoffs, workpads, or resume behavior | [Delivery lifecycle](workflows/delivery-lifecycle.md) | [Triggers](workflows/triggers.md) and [Workpad and resume](workflows/workpad-and-resume.md) |
| Installation, cloud execution, or command permissions | [Installation](operations/installation.md) or [Cloud runs](operations/cloud-runs.md) | [Command permissions](operations/command-permissions.md), [Working directory](operations/working-directory.md), and the workflow definitions |
| Telemetry, probes, calibration, or runtime measurements | [Improvement loops](improvement-loops/index.md) | The named mechanism, fixture, and validation command on that page |

## Find documentation by system surface

- [Architecture](architecture/index.md) — current system shape, execution model, trust boundaries, and prompt-surface ownership.
- [Skills](skills/index.md) — command-specific phases, gates, handoffs, and failure paths.
- [Agents](agents/index.md) — dispatched-agent roles, runtime behavior, artifacts, and permissions.
- [Workflows](workflows/index.md) — cross-skill triggers, workpads, resumes, and delivery lifecycle.
- [Operations](operations/index.md) — installation, cloud runs, allowlists, working directories, and publishing.
- [Improvement loops](improvement-loops/index.md) — telemetry, probes, calibration, evaluations, and incident records.

## Historical context

[Cutovers](cutovers/index.md) contains historical implementation records. Use those pages to understand why a current rule exists or how a migration was performed, but use the current canonical page and its source links as the authority for present behavior.

## Legacy contract records

Some flat-root pages remain because tests, installers, prompt guards, or source comments read their exact paths. They are deep or machine-read references rather than the primary navigation. Start with the categorized page and follow its source links when one of those records is needed.

## Documentation rules

- Current behavior and its rationale live together on the canonical topic page.
- The codebase is authoritative when prose and implementation disagree.
- Source references use bare repository paths rather than line numbers.
- `docs/internal/` and `docs/external/` are separate documentation products; this map covers internal documentation only.
