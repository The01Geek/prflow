<!--
Shared prompt fragment used by the /retrospective-audit drafting brief (Stage B subagent).
Stage B PROPOSES a corrective change (it files an issue spec; it does not edit). When choosing
the change to propose, the agent considers — but is NOT limited to — these surfaces. Any surface
is a valid proposal, because a human triages the issue and implements it through the normal
/prflow:implement -> review pipeline.
-->

## Candidate intervention surfaces

When the failure pattern recurs, the highest-leverage change to propose could live on any of these surfaces. Pick the smallest blast radius that actually addresses the root cause; do not optimize for "more visible" over "more correct".

### Process / workflow surfaces

- **Prompt extensions** (`.prflow/prompt-extensions/<skill>.md`) — the consumer-owned surface for a purely **additive** skill-behavior change. `scripts/load-prompt-extension.sh` prints this file and skill `<skill>` is instructed to append it verbatim to its own prompt (an absent/empty file is a silent no-op), so a "make skill X also do Y" fix can land here as an append instead of editing the shipped skill body. It is bounded: extensions are **append-only** (they cannot override or delete existing skill prose) and **consumer-local** (they don't change behavior for adopters who never pull this repo's extensions). A *structural* skill change — one that must override existing prose, or one that *must ship in the engine to take effect for adopters* — proposes a change to the engine itself instead. **Check the file's readers before estimating blast radius:** an extension is not always read by one skill. A skill that applies another skill's principles without invoking it loads that skill's extension too (issue #620), so `.prflow/prompt-extensions/receiving-code-review.md` now governs every autonomous `/prflow:review-and-fix` entry that goes through the skill preamble — the standalone loop, implement Phase 3 inline, and the Step 2.6 shadow entry — as well as direct reception passes (the documented Skill-denied Phase 3 fallback bypasses the preamble and loads neither extension). Editing it to change reception policy therefore reaches unattended loops, not only interactive ones.
**Consumer-owned is a statement about who MAY write the file, not about which checkout a given tier
reads it from.** On the cloud review tier those are different questions: that job checks out the pull
request's head, so since issue #874 the two extensions the reviewer loads (`review` and
`requesting-code-review`) are materialized from the trusted base ref and the workspace copies are
truncated — a PR's edit to them does not reach its own review. This is the base-ref trust
boundary.
- **`/prflow:implement` skill** (`skills/implement/SKILL.md` orchestrator + `skills/implement/phases/phase-N-*.md` reference files + `skills/implement/references/*.md` predicate-gated references) — the orchestrator drives the four-phase lifecycle; the detailed per-phase procedure you would strengthen/check/gate lives in the phase files (the orchestrator `SKILL.md` holds only thin per-phase stubs), while a procedure whose predicate is false on most runs — Phase 4.0's deferred-AC follow-up filing — lives in a `references/` file the phase file reaches only when that predicate holds.
- **`/prflow:create-issue` skill** (`skills/create-issue/SKILL.md` thin always-loaded root + `skills/create-issue/references/*.md` marker-gated step and fallback references) — the issue-quality entry point. If issues themselves are the bottleneck (vague acceptance criteria, missing repro steps, ambiguous scope), this is where to fix it; the root holds the routing pointer and load contract, the entry gate, and the non-degradable invariants, while the routing table itself (`references/degradation-routing.md`, relocated off the root in issue #1644) and the per-step procedure you would strengthen live in the reference files.
- **`/prflow:review` and `/prflow:review-and-fix` skills** — code-review discipline. If review caught a regression too late, the gap belongs here.
- **Phase sub-skills** (`pr-description`, `docs-sync-internal`, `docs-sync-external`, `docs-release-notes`) — narrower behaviors invoked by `/prflow:implement`.
- **`docs-verify` skill** (`skills/docs-verify/SKILL.md`) — invoked interactively in write mode, and dispatched in `--report-only` mode by **`/prflow:create-issue` Step 1, its only programmatic caller**. The two modes have **separate identities**: write mode is the documentation-accuracy pass; report-only is a **docs-first code explorer** whose deliverable is a map of current behavior, with documentation as its entry point and provisional evidence rather than its subject. Its report-only breadth bound (the duty floor) and its search-space operand are where to fix a Step 1 pass that surveys too much or too little; the *Who you are in report-only mode* section is where to fix one that returns the wrong **kind** of finding. The write-mode half lives in `references/write-mode.md`, loaded on the write path only and fail-closed; `/prflow:implement` does not invoke this skill.
- **Issue templates** (`.github/ISSUE_TEMPLATE/`) — when the failure is structural (humans omit the same field every time), the template itself can encode the requirement.

### Knowledge / convention surfaces

- **`CLAUDE.md`** at repo root — durable, agent-loaded conventions. Use sparingly: every rule here is loaded on every run. Strengthen an existing rule before adding a new one.
- **`docs/internal/<feature>.md`** — feature-specific technical context. The `/prflow:implement` skill is told to consult these first; if Claude missed one, the docs may be missing or stale.
- **`docs/external/`** — user-facing docs. Less common as an intervention surface but valid when the failure is documentation drift.
- **Lint rules** (`phpcs.xml.dist`, ESLint configs, etc.) — encode mechanical conventions where a human-readable rule won't reliably stick.

### Code surfaces

- **Application code itself** — when the failure is a real bug introduced by Claude that recurs because the surrounding code makes the wrong path easier than the right one. Refactor the API, rename, or add a guardrail.
- **Library / utility code** — extracting a helper that makes the correct pattern the obvious one (e.g., a `buildOrFilter()` helper if "use OR not IN" keeps recurring).

### Sub-agent surfaces

- **Agents** (`agents/<agent-name>.md`) — specialized contexts called via the Agent tool. If a failure pattern spans the work an agent does (research, design, review), the agent's instructions may be the leverage point.

### High-blast-radius surfaces (flag the second-order effects in the issue)

Every surface is a valid proposal — Stage B files an issue, not a PR, so a human reviews and implements the change through the normal pipeline. But a change to one of these engine surfaces carries extra blast radius on the self-improvement loop itself, so when you propose one, call out the second-order effects in the issue's Counterfactual/Gotchas so the reviewer can weigh them:

- The engine's own files (`skills/**`, `agents/**`, `lib/**`, `scripts/**`, `.claude-plugin/**`) — a change here ships to every consumer.
- `.prflow/learnings/**` — the loop's own ground-truth data files.
- `.github/workflows/claude*.yml`, `.github/workflows/devflow-*.yml` and the composite actions they consume — breaking these cripples the loop.
- `.prflow/config.json` — config changes touch every other workflow.
