---
bump: patch
type: Changed
---

- **Gate the `/prflow:create-issue` Step 3 template read behind boundary markers.**
  `references/issue-template.md` is now a routed reference under marker id `issue-template`:
  it carries `start`/`end` boundary markers and a `## Reference routing` row, so a truncated,
  empty, or locally-edited copy degrades on the row's named behavior with an in-chat breadcrumb
  instead of passing untouched. Issue creation is never blocked — the entry gate degrades, it
  does not fail closed. (#1467)
