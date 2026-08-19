---
bump: patch
type: Added
---

- **Bounded terminal-result classifier for autonomous workflow actions.** Adds
  `scripts/terminal-result-class.sh`, a pure classifier that reconciles an autonomous
  action's outcome into a bounded terminal class: the implement tier maps the workpad
  status class plus job status to `complete`/`blocked`/`incomplete` (only the canonical
  `complete`/`blocked` words map through, a cancelled job maps to `incomplete` even over a
  stale terminal token, and every other token falls closed to `incomplete`); the review tier
  maps the six exact `POSTED review|comment REQUEST_CHANGES|APPROVE|COMMENT` producer
  outcomes to `verdict-posted` and everything else — including a `REACHED`-prefixed
  compatibility wrapper — to `incomplete`; and a conclusion mode maps `complete`/`verdict-posted`
  to `success` and the rest to `non-success`. A generated total mapping table
  (`lib/terminal-result-table.tsv`, produced by the independent Python oracle
  `lib/generate-terminal-result-table.py`) enumerates the closed input cross-product and is
  cross-checked against the classifier by a focused test module over every generated row, so a
  divergence between the two implementations turns the suite red. This is the foundational slice
  of the terminal-outcome enforcement
  work; the guard, observer, admission-controller, bootstrap, and workflow wiring are tracked
  in follow-up issues. (#1792)
