---
bump: patch
type: Changed
---

- **Shrink the create-issue audit state owner's call protocol.** An `issue-audit-state.py`
  subcommand that prints a `next_call=` line now also prints a `summary-block` line — a compact
  fixed subset of the `query-summary` fields, enumerated in the tool's `--help` — between its
  decided answer line and the final `next_call=` line, so a caller reads post-mutation state from
  the call it just made. `record-finding-evidence` gains a `--finding-evidence-records-file` form
  that records a whole round's finding evidence from one JSON file (each entry keeping its own
  completeness verdict). The audit references' clean path drops the standalone `query-summary`
  read its enriched output now carries, lowering the per-run mandated state-owner call count. (#1807)
