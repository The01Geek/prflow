---
schema: 1
kind: growth
---

# Issue #693 — issue-body cache: mandatory-prose growth

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.

This records the audited mandatory-surface growth the issue-body cache ships, per the
"Prose cutover" procedure in `.prflow/prompt-extensions/implement.md`. The change adds
operative decision logic (a new cache producer, an ignore precondition, a content check,
a worktree re-materialization arm, per-consumer degraded-arm dispositions, and three
subagent hand-off lines), so the growth is an audited decision, not a side effect.

## Files

Per-file byte growth measured by `lib/test/prompt-mass-census.py` (baseline → current):

- `skills/implement/phases/phase-1-setup.md` — +8207 bytes. §1.1 gains the cache
  producer (root anchor → ignore precondition → delete-then-fetch → content check),
  the two non-satisfied arms (UNAVAILABLE→stop, NOT_IGNORED→degraded), the hand-off-only
  rule; §1.2 and §1.3.5 gain their `--body-file` cutovers with the degraded `--issue`
  fallback and §1.2's fail-closed guard; §1.4's linked-worktree arm gains the cache
  re-materialization; §1.6 gains its cache body-source pointer.
- `skills/implement/phases/phase-2-implement.md` — +1331 bytes. §2.1 (`code-explorer`)
  and §2.2 Path B (`code-architect`) dispatches gain the `Issue body path:` hand-off
  and the no-`Bash`-tool degraded inline-paste disposition.
- `skills/implement/phases/phase-4-documentation.md` — +648 bytes. §4.1's `prflow:docs`
  dispatch gains the `Issue body path:` hand-off and the degraded inline-paste
  disposition; the Documentation-Needed gate fences are deliberately untouched.
- `skills/implement/SKILL.md` — +405 bytes. The terminal-status cleanup gains the cache
  removal alongside the run-marker removal, plus its accompanying prose.

## Justification

The mandatory surface grows because every added instruction is operative decision logic
that governs a run's behavior on its normal path, not rare-path explanation that could
be moved to a progressively-loaded reference:

- The cache producer, ignore precondition, and content check decide whether the cache is
  written and whether it is valid — a fail-closed gate the run must evaluate every entry.
- The per-consumer degraded-arm dispositions are load-bearing: `code-explorer` and
  `code-architect` declare no `Bash` tool, so a single blanket "fetch live" fallback would
  silently leave them planning from title and labels alone. Each consumer class needs its
  own stated fallback, which cannot be abbreviated without losing the safety property.
- The three `Issue body path:` hand-off lines and the hand-off-only rule are the mechanism
  the cost saving depends on, and the trust boundary that keeps a consumer from reading a
  PR-authored file — both must be stated where the dispatch is composed.
- The worktree re-materialization arm closes a correctness gap (a repo-relative read from a
  switched worktree would miss a cache anchored to the original root).

The offsetting saving is realized at runtime, not in prompt bytes: three subagent
dispatches stop pasting a multi-KB issue body into the orchestrator's context, and the
duplicate Phase-1 fetches collapse into one. The prompt-surface growth buys that
context-headroom saving.
