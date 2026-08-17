---
bump: patch
---

Fire `/prflow:create-issue`'s Testing Strategy Move 2 coverage sweep on every enumerated
test/case/example list inside an acceptance criterion, not only floor-marked ones.

`skills/create-issue/references/issue-template.md` and
`skills/create-issue/references/quality-group-contracts.md` previously scoped the state /
case-variant / multiplicity / absence sweep to a list carrying the `at minimum` floor marker, so a
list declared a closed set (`exactly these N — complete by construction`) skipped the sweep. The
precondition is removed: the sweep obligation now reads over every such list regardless of which
closure marker it carries. Both closure declarations survive unchanged, and a list carrying neither
is still non-conforming. The `docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md` §11 `#464` entry is narrowed
to match. This is a deletion; no rule, checklist row, gate, or check is added. (#1730, PR #1735)
