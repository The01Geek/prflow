---
bump: minor
type: Changed
---

- **`/prflow:implement` now runs its judgment-heavy phases in fresh contexts.** Phase 1.6's
  issue-claim audit, Phase 3.4's acceptance-criteria gate (two independent verifiers — one for
  the literal claim, one for the evidence), Phase 4.0's deferral drafting, Phase 4.2's PR
  description and branch setup each dispatch a subagent rather than resolving inline, so a
  long orchestrator context can no longer colour those decisions.
- **Consumer prompt extensions reload at each surface's re-entry boundary**, not only at run
  start — a context compaction mid-run no longer silently drops the consumer's policy from the
  rest of the run.
- **`/prflow:create-issue`'s always-read surface was rewritten for instruction adherence and
  cost.** The routing table moved off the skill root, the Step 3.6 audit reference was
  decomposed below the single-read ceiling, the authoring checklist split into a core list plus
  five conditionally-loaded groups, and the shared writing standard now leads with plain
  language and models the prose it asks drafters to write.
- **A prevention-only comment standard governs added and changed comments.** A comment survives
  inline only when it names a specific wrong change it prevents; derivation, provenance and
  design narrative move to internal documentation. The same pass trimmed the implement
  orchestrator root, the retrospective skill and the checklist-trio agent bodies under the
  instruction-plus-consequence prose rule.
- **Verification got stricter in three places.** Phase 2 §2.3 sweeps grade the whole branch
  delta rather than the uncommitted remainder; a run no longer publishes a PR or records
  `Complete` while its local branch tip is absent from the remote; and `ruff` is gated inside
  the test suite, so a Python lint regression can no longer ship green.
- **Windows and BSD portability fixes.** Local text-file inputs decode explicitly as UTF-8,
  workpad ticks are protected from MSYS path conversion, implement-bundle fences avoid the
  shell expansions a worktree-isolated session refuses, and two suite assertions no longer
  fail on BSD `wc`'s padded output.
- **`prflow_review.agent_overrides.<agent>.model` accepts the Agent tool's model aliases**, and
  implement review progress is kept on a single surface. (#1720)
