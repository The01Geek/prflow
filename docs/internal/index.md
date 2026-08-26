# PRFlow internal documentation

<!-- verified-against: 26c9ad96d 2026-08-25 -->

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
| Review or review-and-fix behavior | [Review](skills/review.md) or [Review-and-fix](skills/review-and-fix.md) | [Review agents](agents/review-agents.md), [Shadow review](agents/shadow-review-overview.md), and the review skill sources |
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

## Reference pages

- [Glossary](glossary.md) — definitions of the repository-private terms used across these docs.
- [Naming](naming.md) — why DevFlow and PRFlow both appear; which spelling is current and which names are frozen.
- [Positioning](positioning.md) — marketing and messaging copy; skip when mapping system behavior.

## Historical context

[Cutovers](cutovers/index.md) contains historical implementation records. Use those pages to understand why a current rule exists or how a migration was performed, but use the current canonical page and its source links as the authority for present behavior.

## Legacy contract records

Some flat-root pages remain because tests, installers, prompt guards, or source comments read their exact paths. They are deep or machine-read references rather than the primary navigation. Start with the categorized page and follow its source links when one of those records is needed.

Every flat-root page, so nothing is reachable only by directory listing. A "deep reference" note means the file is large — budget your reads and open it selectively rather than whole.

**Deep contract references (each has a categorized entry page):**

- [`DEVFLOW_SYSTEM_OVERVIEW.md`](DEVFLOW_SYSTEM_OVERVIEW.md) — the detailed whole-system reference behind [the system overview](architecture/system-overview.md). Deep reference, ~650 KB — read selectively by section.
- [`implement-skill.md`](implement-skill.md) — implement sweep, verification, and finalization discipline evidence. Deep reference, ~290 KB.
- [`cloud-allowlist.md`](cloud-allowlist.md) — per-occurrence cloud command-shape allow/deny adjudications. Deep reference, ~150 KB.
- [`cloud-setup.md`](cloud-setup.md) — cloud-tier setup, credentials, and migration evidence. Deep reference, ~130 KB.
- [`install.md`](install.md) — installer and bash-selection details. Deep reference, ~90 KB.
- [`shadow-review.md`](shadow-review.md) — shadow-review mechanism, calibration, and cost evidence. Deep reference, ~80 KB.
- [`workflow-triggers.md`](workflow-triggers.md) — the detailed trigger matrix and the withheld-tier statement. Deep reference, ~70 KB.
- [`efficiency-trace.md`](efficiency-trace.md) — reviewer-effectiveness telemetry schema and derivation. Deep reference, ~95 KB.
- [`working-directory-contract.md`](working-directory-contract.md) — the canonical working-directory contract.
- [`cloud-writer-boundary.md`](cloud-writer-boundary.md) — the helper-emission boundary decision record.
- [`claude-md-tiered-suite-rationale.md`](claude-md-tiered-suite-rationale.md) — derivation of the tiered suite-running policy.
- [`mintlify-publishing.md`](mintlify-publishing.md) — the external-site publishing contract.
- [`workflow-flight-recorder.md`](workflow-flight-recorder.md) — the local workflow transcript recorder's lifecycle and privacy rules.
- [`skill-body-load-delivery.md`](skill-body-load-delivery.md) — how skill bodies are delivered to runs, with probe evidence. Deep reference, ~60 KB.
- [`review-agent-overrides.md`](review-agent-overrides.md) — `agent_overrides` resolution and version-skew evidence.
- [`test-suite-probe-conventions.md`](test-suite-probe-conventions.md) — how suite probes are written so they stay stable across hosts.
- [`execution-file-shape.md`](execution-file-shape.md) — the execution-file shape the runtime writes and its consumers.

**Measurement, study, and incident records (evidence, not current-behavior contracts):**

- [`create-issue-context.md`](create-issue-context.md), [`implement-context.md`](implement-context.md), [`review-context.md`](review-context.md) — measured runtime context and per-context read cost for the three commands.
- [`agents-seam-probe.md`](agents-seam-probe.md) — cloud per-agent-effort seam probe evidence.
- [`advisory-adjudication-calibration.md`](advisory-adjudication-calibration.md) — advisory-adjudication calibration corpus and failure modes.
- [`execution-diagnostics.md`](execution-diagnostics.md) — the redaction posture of surfaced diagnostic fields.
- [`subagent-write-probe.observed.md`](subagent-write-probe.observed.md) — raw probe output, kept verbatim (`.observed.md`).
- [`universal-criteria-grading-spike.md`](universal-criteria-grading-spike.md) — a grading-spike study record.
- [`review-and-fix-split-wording-study.md`](review-and-fix-split-wording-study.md) — a wording study for the review-and-fix split.
- [`incomplete-edit-cost-analysis.md`](incomplete-edit-cost-analysis.md) — a cost analysis of incomplete-edit failures.
- [`review-skill-load-outage-2026-08.md`](review-skill-load-outage-2026-08.md) — the 2026-08 review-skill load outage incident record.
- [`claude-md-extension-audit-consumers.md`](claude-md-extension-audit-consumers.md), [`claude-md-extension-audit-coupled-sites.md`](claude-md-extension-audit-coupled-sites.md), [`claude-md-extension-audit-duplicates.md`](claude-md-extension-audit-duplicates.md) — prompt-surface audit evidence.
- [`claude-md-relocated-rationale.md`](claude-md-relocated-rationale.md) — rationale for content relocated out of `CLAUDE.md`.
- [`create-issue-prehunt-valid-na-evidence.md`](create-issue-prehunt-valid-na-evidence.md) — create-issue pre-hunt valid-N/A evidence record.
- [`pin-corpus-issue-1759-sweep.md`](pin-corpus-issue-1759-sweep.md) — a pin-retirement disposition record whose exact path is cited from test comments; do not move it.

## Documentation rules

- Current behavior and its rationale live together on the canonical topic page.
- The codebase is authoritative when prose and implementation disagree.
- Source references use bare repository paths rather than line numbers.
- `docs/internal/` and `docs/external/` are separate documentation products; this map covers internal documentation only.
