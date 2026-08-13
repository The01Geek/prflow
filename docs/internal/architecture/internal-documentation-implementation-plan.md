# Internal Documentation Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize and improve `docs/internal/` so coding agents and developers can find a code-grounded explanation of the system surface they are about to change.

**Architecture:** Keep a single navigable internal-doc root with six domain directories: `architecture/`, `skills/`, `agents/`, `workflows/`, `operations/`, `improvement-loops/`, plus the historical `cutovers/` directory. Use `docs/internal/index.md` as the routing map and make each canonical page own both current behavior and its rationale.

**Tech Stack:** Markdown, repository-relative links, `rg`, `git`, and the existing shell/Python validation suite.

## Global Constraints

- Work only inside `docs/internal/`; do not modify `docs/external/`.
- Keep `cutovers/` navigable and clearly historical.
- Do not create a disconnected `decisions/` category; rationale belongs with the behavior it governs.
- Preserve useful existing evidence while splitting mixed pages at real topic, reader, source, or verification boundaries.
- Preserve legacy root-level internal-doc paths when tests, installers, prompt guards, or source comments consume them as machine-readable contracts.
- Use bare source paths in prose and do not add hard-coded line numbers.
- Treat code, workflows, configuration, and tests as the authority when documentation conflicts with implementation.
- Keep the category structure one level below `docs/internal/`.

---

### Task 1: Build the internal documentation catalog and category skeleton

**Files:**
- Create: `docs/internal/index.md`
- Create directories: `docs/internal/skills/`, `docs/internal/agents/`, `docs/internal/workflows/`, `docs/internal/operations/`, `docs/internal/improvement-loops/`
- Reference: `docs/internal/architecture/internal-documentation-architecture.md`

**Interfaces:**
- Consumes: the approved information architecture and the current file inventory.
- Produces: the root routing page and category destinations used by every later migration task.

- [x] **Step 1: Reconcile the source inventory**

Read the current headings and source references in every top-level internal page and record each page's canonical destination in the index draft. Treat a page as a source record until its content has an explicit canonical owner.

- [x] **Step 2: Write the root routing page**

Create `docs/internal/index.md` with a short “before planning a change” path, workflow routes, surface routes for skills and agents, operations and improvement-loop routes, and a historical cutovers link. Keep descriptions concise and link-only; do not duplicate implementation prose.

- [x] **Step 3: Verify the skeleton**

Run `find docs/internal -maxdepth 2 -type d -print | sort` and confirm the six approved categories plus `cutovers/` exist, with no nested category hierarchy.

### Task 2: Establish architecture and cross-cutting system pages

**Files:**
- Create or modify: `docs/internal/architecture/system-overview.md`
- Create or modify: `docs/internal/architecture/execution-model.md`
- Create or modify: `docs/internal/architecture/prompt-surfaces.md`
- Preserve and reference: `docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md` as the detailed machine-read compatibility reference.
- Source material: `docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md`, `docs/internal/working-directory-contract.md`, `docs/internal/cloud-writer-boundary.md`, and the CLAUDE/prompt-extension audit records.

**Interfaces:**
- Consumes: the architecture sections and current boundary records.
- Produces: concise architecture entry points that link to skill, agent, workflow, operations, and improvement-loop pages.

- [x] **Step 1: Extract the current system model**

Use the existing system overview's pitch, tier, lifecycle, skill catalog, and repository-layout sections to write `system-overview.md`. Keep the page focused on the system map and link out to detailed surfaces.

- [x] **Step 2: Extract execution and trust boundaries**

Write `execution-model.md` from the tier, workpad, branch, runtime, working-directory, and cloud-writer material. Include current behavior, failure paths, and the rationale for the boundaries.

- [x] **Step 3: Consolidate prompt-surface ownership**

Write `prompt-surfaces.md` from the CLAUDE/prompt-extension audit records, preserving the code-verified consumer and coupling rules while moving historical audit narration into links to the relevant cutovers.

- [x] **Step 4: Reconcile architecture links**

Search the tracked tree for `DEVFLOW_SYSTEM_OVERVIEW.md`, `working-directory-contract.md`, and `cloud-writer-boundary.md` references. Update human-facing current links to the concise canonical pages, and retain legacy paths when the reader is a test, installer, prompt guard, source comment, or historical record.

### Task 3: Create the skills documentation family

**Files:**
- Create or modify: `docs/internal/skills/create-issue.md`
- Create or modify: `docs/internal/skills/implement.md`
- Create or modify: `docs/internal/skills/implement-verification.md`
- Create or modify: `docs/internal/skills/implement-documentation.md`
- Create or modify: `docs/internal/skills/review.md`
- Create or modify: `docs/internal/skills/review-and-fix.md`
- Create or modify: `docs/internal/skills/documentation.md`
- Create or modify: `docs/internal/skills/skill-loading.md`
- Source material: `create-issue-context.md`, `implement-skill.md`, `implement-context.md`, `shadow-review.md`, `skill-body-load-delivery.md`, and the corresponding root `skills/**` sources.

**Interfaces:**
- Consumes: current skill behavior and the source-of-truth contract.
- Produces: focused skill pages that an agent can read before opening the executable skill body.

- [x] **Step 1: Build the create-issue page**

Move the current create-issue runtime and docs-verify retrieval explanation into `skills/create-issue.md`. Preserve the report-only duties, search-space behavior, code-versus-doc authority, and failure/degraded paths.

- [x] **Step 2: Split implement behavior by decision boundary**

Use `implement-skill.md` and `implement-context.md` to create `implement.md`, `implement-verification.md`, and `implement-documentation.md`. Keep phase orchestration in the first page, verification gates and evidence in the second, and Phase 4 documentation enforcement in the third.

- [x] **Step 3: Write the review skill pages**

Create `review.md` and `review-and-fix.md` from the system overview, shadow-review material, and executable review surfaces. Keep review-engine behavior separate from fix-loop behavior while linking their shared contracts.

- [x] **Step 4: Add documentation and skill-loading pages**

Create `documentation.md` for the internal/external documentation boundary and `skill-loading.md` for skill-body delivery, loading limits, and the evidence that explains the current behavior.

- [x] **Step 5: Verify skill claims against source**

For each skill page, reopen the named `skills/**`, `agents/**`, scripts, workflows, and tests and remove or rewrite any claim that cannot be confirmed.

### Task 4: Create the agents documentation family

**Files:**
- Create or modify: `docs/internal/agents/review-agents.md`
- Create or modify: `docs/internal/agents/shadow-review.md`
- Create or modify: `docs/internal/agents/agent-runtime.md`
- Create or modify: `docs/internal/agents/agent-permissions.md`
- Source material: `shadow-review.md`, `review-agent-overrides.md`, `agents-seam-probe.md`, `execution-file-shape.md`, and `subagent-write-probe.observed.md`.

**Interfaces:**
- Consumes: agent definitions, review engine behavior, permission probes, and execution artifacts.
- Produces: agent-specific current behavior and rationale pages linked from the skills and architecture pages.

- [x] **Step 1: Document review-agent roles and overrides**

Consolidate reviewer roles, model/effort override behavior, accepted identifiers, and resolution rules in `review-agents.md`.

- [x] **Step 2: Document shadow review**

Move the shadow-review mechanism, independence boundary, coverage fail-safe, grading limits, and cost model into `shadow-review.md`.

- [x] **Step 3: Document agent runtime and artifacts**

Combine the execution-file shape and seam-probe findings into `agent-runtime.md`, distinguishing measured facts from self-reported or unestablished behavior.

- [x] **Step 4: Document permission boundaries**

Move the dispatched-subagent write probe and related permission evidence into `agent-permissions.md`, with the current allowed and denied behavior grounded in the relevant workflows and tests.

### Task 5: Create workflow and operations documentation

**Files:**
- Create or modify: `docs/internal/workflows/triggers.md`
- Create or modify: `docs/internal/workflows/workpad-and-resume.md`
- Create or modify: `docs/internal/workflows/delivery-lifecycle.md`
- Create or modify: `docs/internal/operations/installation.md`
- Create or modify: `docs/internal/operations/cloud-runs.md`
- Create or modify: `docs/internal/operations/command-permissions.md`
- Create or modify: `docs/internal/operations/working-directory.md`
- Create or modify: `docs/internal/operations/publishing.md`
- Source material: `workflow-triggers.md`, `install.md`, `cloud-setup.md`, `cloud-allowlist.md`, `working-directory-contract.md`, and `mintlify-publishing.md`.

**Interfaces:**
- Consumes: workflow definitions, install scripts, cloud workflows, allowlist manifests, and publishing configuration.
- Produces: task-oriented operational and cross-skill pages with current behavior and rationale together.

- [x] **Step 1: Split workflow triggers from lifecycle behavior**

Write `triggers.md` for event and command routing, `workpad-and-resume.md` for state and resume behavior, and `delivery-lifecycle.md` for the cross-skill path from request through review-ready pull request.

- [x] **Step 2: Split installation from cloud operation**

Write `installation.md` for local installation and update behavior, then write `cloud-runs.md` for cloud setup, runtime provisioning, secrets, runners, writer jobs, and provider behavior.

- [x] **Step 3: Split command permissions and working-directory rules**

Write `command-permissions.md` for allowlist heads, command shapes, grants, and probe evidence. Write `working-directory.md` for cwd contracts and their rationale.

- [x] **Step 4: Move publishing guidance**

Write `publishing.md` from the Mintlify source contract and validation flow, with links back to the external documentation boundary.

### Task 6: Create improvement-loop documentation

**Files:**
- Create or modify: `docs/internal/improvement-loops/efficiency-telemetry.md`
- Create or modify: `docs/internal/improvement-loops/workflow-flight-recorder.md`
- Create or modify: `docs/internal/improvement-loops/calibration-and-adjudication.md`
- Create or modify: `docs/internal/improvement-loops/runtime-evaluations.md`
- Create or modify: `docs/internal/improvement-loops/incidents-and-audits.md`
- Source material: `efficiency-trace.md`, `workflow-flight-recorder.md`, `advisory-adjudication-calibration.md`, `implement-context.md`, `review-and-fix-split-wording-study.md`, and `review-skill-load-outage-2026-08.md`.

**Interfaces:**
- Consumes: measurement mechanisms, probes, calibration records, and incident findings.
- Produces: evidence pages that state what was measured, what remains unestablished, and how to re-check it.

- [x] **Step 1: Separate telemetry from its experiment record**

Move the current efficiency-trace behavior and record schema into `efficiency-telemetry.md`, retaining the non-fatal and persistence boundaries.

- [x] **Step 2: Preserve the flight recorder as a focused mechanism page**

Move `workflow-flight-recorder.md` and keep its inventory, lifecycle, privacy, analysis, and recovery sections together when they describe the same recorder.

- [x] **Step 3: Consolidate calibration and runtime studies**

Combine calibration, context-evaluation, and wording-study material in `calibration-and-adjudication.md` and `runtime-evaluations.md` according to whether the page explains a grading mechanism or a runtime measurement.

- [x] **Step 4: Preserve incidents and audits as evidence**

Move outage reports and audit records into `incidents-and-audits.md`, clearly marking their current conclusion and historical scope.

### Task 7: Reconcile cutovers, links, and canonical ownership

**Files:**
- Modify: all moved-page references under `docs/internal/`, `CLAUDE.md`, `CONTRIBUTING.md`, workflows, scripts, tests, and other tracked Markdown.
- Preserve: `docs/internal/cutovers/**` as navigable historical records.
- Preserve: machine-read flat-root contract pages; remove or rename only a flat-root page whose readers have been migrated and whose content has an owned destination.

**Interfaces:**
- Consumes: every canonical page produced by Tasks 2–6.
- Produces: one resolvable internal-doc graph with no stale current links or duplicate canonical owners.

- [x] **Step 1: Enumerate old-path references**

Search the tracked tree for every moved filename and every `docs/internal/` reference. Classify each hit as current, historical, source comment, test pin, or documentation link.

- [x] **Step 2: Update current references**

Change current references to canonical paths. Keep a historical path only when it is part of a cutover record's provenance, and add a nearby link to the current canonical page when the historical record needs one.

- [x] **Step 3: Remove duplicate owners**

Do not delete machine-read flat-root pages. Add canonical pages that own the agent-facing explanation, link to the legacy contract record, and make the legacy page's role clear without duplicating or contradicting its behavior.

- [x] **Step 4: Complete the index**

Update `docs/internal/index.md` with the final page map and the “read this before changing” routes for common agent topics.

### Task 8: Validate the restructured internal docs

**Files:**
- Verify: all files under `docs/internal/` and all tracked references to them.
- Modify: only documentation files needed to correct validation findings.

**Interfaces:**
- Consumes: the completed internal-doc graph.
- Produces: verified links, verified source claims, and a clean documentation-focused diff.

- [x] **Step 1: Check the category and page inventory**

Run `find docs/internal -maxdepth 2 -type f -name '*.md' -print | sort`, confirm the approved categories, confirm every page has a clear title and scope, and confirm cutovers remain present.

- [x] **Step 2: Check links and moved paths**

Enumerate Markdown links with `rg -n '\]\([^)]*\.md(?:#[^)]+)?\)' docs/internal --glob '*.md'`, resolve each relative target from its referring file, and use `test -f` to report missing targets. Run separate `rg` scans for old flat-root paths, `docs/external/`, and `DEVFLOW_SYSTEM_OVERVIEW.md`.

- [x] **Step 3: Check prose contracts**

Search canonical pages for hard-coded line numbers, placeholders, duplicated “source of truth” sections, and claims that name missing files or symbols. Re-open each source path named by a changed page.

- [x] **Step 4: Run repository verification**

Run `git diff --check`, the link/path checks from Steps 1–3, and `lib/test/run.sh`. Treat any nonzero failure or unestablished verification result as a finding to resolve or report; do not convert it into a clean pass.

- [x] **Step 5: Review the final diff**

Read the complete diff, confirm no content was silently dropped, confirm no external docs were changed, and report any residual unestablished claim instead of presenting it as verified.
