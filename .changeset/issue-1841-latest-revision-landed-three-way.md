---
bump: patch
type: Fixed
---

- **`create-issue`: report `latest_revision_landed` three-way (`yes`/`no`/`unestablished`) instead of collapsing cannot-prove onto `no`.** `issue-audit-state.py`'s `latest_revision_landed` predicate now returns `no` only when a recorded write-failure proves the latest revision did not land, and `unestablished` when the recorded state proves neither landing nor failure (the common `basis=resolution` terminal path, or a revision with no recorded stdin digest) — so `query-draft-binding` no longer shows a false-alarm `no` on a healthy run, and its `--help` enumerates the three tokens. (#1868)
