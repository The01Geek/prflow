# Internal documentation architecture

> Status: approved design, 2026-08-12.

## Purpose

This document defines the information architecture for the repository's internal documentation. It is written for coding agents and developers who need a reliable map of how PRFlow works today before they plan or implement a change.

The documentation is an explanatory source of truth about the system. The executable repository surfaces remain authoritative for behavior, and every factual statement in the documentation must be checked against those surfaces.

## Primary reader and retrieval path

The primary reader is a coding agent or developer working on a brownfield change. The most common entry path is the early `/prflow:create-issue` investigation, where a `/prflow:docs-verify --report-only` peer reads the internal documentation as a map and then follows the map into code, tests, workflows, and configuration.

The root index must therefore answer three questions quickly:

- What system surface does this change touch?
- Which canonical document explains that surface today?
- Which source files, guards, tests, and related documents should be read next?

The index is a routing aid, not a second system reference. Detailed behavior and rationale belong in the canonical topic pages.

## Category model

The internal documentation uses one level of domain directories under `docs/internal/`. Categories describe concepts that agents work on, rather than mirroring the repository's implementation layers.

| Category | Owns | Does not own |
| --- | --- | --- |
| `architecture/` | System model, lifecycle, state, trust boundaries, repository layout, and cross-cutting invariants | One command's phase-by-phase behavior or a historical implementation record |
| `skills/` | Skill inputs, phases, outputs, gates, handoffs, failure paths, and skill-specific rationale | The executable skill body itself, which remains under `skills/` at the repository root |
| `agents/` | Agent roles, dispatch behavior, review agents, model and effort behavior, agent permissions, and execution artifacts | General workflow triggers or skill-specific orchestration that is not agent behavior |
| `workflows/` | Cross-skill orchestration, triggers, workpads, branch and pull-request lifecycle, resume behavior, and command handoffs | The internals of one skill or one agent |
| `operations/` | Installation, updates, cloud setup, command permissions, working-directory contracts, and publishing | Design rationale that belongs with a different canonical system topic |
| `improvement-loops/` | Telemetry, probes, calibration, runtime measurements, flight recording, evaluations, and incident analysis | Current command behavior that is not part of an improvement loop |
| `cutovers/` | Historical implementation records and migration evidence | Current normative behavior; canonical pages must summarize the current result and link here for history |

There is deliberately no `decisions/` category. A design decision belongs with the behavior it governs so that an agent can read the current mechanism and its rationale together.

## Canonical page contract

Every canonical page opens with its scope and intended reader. It then uses the following sections as applicable:

1. **Current behavior** — what the repository does now, grounded in source and tests.
2. **Why it works this way** — the decision, constraint, trade-off, or rejected alternative that explains the behavior.
3. **Boundaries and failure paths** — fallbacks, degraded outcomes, permissions, trust boundaries, and conditions that prevent a clean result.
4. **Source of truth** — bare repository paths naming the skills, agents, workflows, scripts, libraries, configuration, and tests that implement or guard the topic.
5. **Related topics** — links to other canonical pages and historical cutovers that an implementer may need.

The sections are a contract for retrieval, not a requirement to force every page into identical prose. A small reference page may use fewer sections when the omitted sections genuinely do not apply.

The prose must distinguish current behavior from historical evidence. A cutover can explain why a rule was introduced, but it cannot silently override the current source or canonical page.

## Root index

`docs/internal/index.md` is the primary entry point. It will provide:

- A short “before planning a change” path that starts with the relevant system surface, then points to the source files and guards to inspect.
- A workflow-oriented map for create-issue, implement, review, review-and-fix, documentation, retrospective, and cloud-triggered paths.
- A surface-oriented map for skills, agents, workflows, operations, and improvement loops.
- A history link to the navigable `cutovers/` records.

The index will point to canonical pages with short routing descriptions. It will not restate implementation rules, numeric inventories, or decision narratives that can drift from their owners.

## Splitting and migration rules

The restructuring preserves the existing content while changing its ownership and boundaries. It does not create placeholder pages or split documents merely because they are long.

A page is split when its sections have different readers, different source-of-truth files, different failure paths, or different verification methods. A page stays together when its sections describe one inseparable mechanism and separating them would force an agent to reconstruct the behavior from multiple fragments.

The large mixed documents are treated as source material rather than permanent canonical containers. In particular, `DEVFLOW_SYSTEM_OVERVIEW.md`, `implement-skill.md`, `cloud-setup.md`, `cloud-allowlist.md`, `workflow-triggers.md`, and `efficiency-trace.md` will be decomposed along their existing conceptual boundaries, then replaced by concise overview pages and focused canonical pages.

The current decision and rationale records are merged into the canonical page for the behavior they govern. A record that spans several surfaces is placed with the surface whose invariant it explains and linked from the other affected pages. Historical cutovers remain in `cutovers/` and retain their historical framing.

All tracked references are updated when a canonical page moves, including references in `CLAUDE.md`, source comments, workflows, tests, cutover records, and other internal pages. Internal documentation links use relative paths appropriate to their new location. No hard-coded line numbers are introduced.

## Source-of-truth and validation rules

The codebase remains the authority when prose and implementation disagree. During migration, each canonical page is checked against the relevant source files, tests, configuration schema, and workflow definitions.

Validation covers:

- Every index link resolves to a tracked page.
- Every moved or split page has its tracked references updated.
- Every canonical page names existing source paths and symbols without line-number anchors.
- No canonical page contains a duplicated block that is owned by another page.
- Historical pages remain clearly labeled as historical and do not present stale behavior as current.
- The internal documentation root remains separate from `docs/external/`, which is customer-facing output.

## Initial migration map

The existing corpus supplies the first migration set:

- `create-issue-context.md`, `implement-skill.md`, and `implement-context.md` become focused pages under `skills/`.
- `shadow-review.md`, `review-agent-overrides.md`, `agents-seam-probe.md`, `execution-file-shape.md`, and `subagent-write-probe.observed.md` become focused pages under `agents/`.
- `workflow-triggers.md` becomes a workflow page, with workpad and lifecycle material separated when its source and reader boundaries differ.
- `install.md`, `cloud-setup.md`, `cloud-allowlist.md`, `working-directory-contract.md`, and `mintlify-publishing.md` become focused pages under `operations/` or `architecture/` according to the boundary they explain.
- `efficiency-trace.md`, `workflow-flight-recorder.md`, calibration records, runtime-context studies, and measured incident records become focused pages under `improvement-loops/`.
- `DEVFLOW_SYSTEM_OVERVIEW.md` becomes the concise architecture entry point and links to the canonical skill, agent, workflow, operations, and improvement-loop pages.

This map is a starting point for implementation. The final page boundaries are validated against the actual headings, links, source references, and machine readers before files are moved.
