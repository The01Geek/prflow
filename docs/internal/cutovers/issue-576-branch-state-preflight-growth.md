---
schema: 1
kind: growth
---
# Issue #576 — branch state preflight growth (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

- `skills/implement/phases/phase-1-setup.md`

## Justification

- These mandatory bytes add the §1.4.0.5 Verdict B branch-state classification to Phase 1: the
  state the helper is handed, the JSON-boolean encoding constraint on the two gate flags, the
  one-token verdict/exit-code routing, and the load-bearing ordering that places the
  classification after branch determination and before the §1.4.1 checkpoint and §1.5 push. The
  procedure is on the normal adopted-branch path and terminalizes the run, so it cannot live in
  a conditionally-loaded reference; the recognizer and derivation semantics stay owned by
  `scripts/preflight.py` rather than being duplicated here.
