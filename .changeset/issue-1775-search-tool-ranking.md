---
bump: patch
type: Changed
---

- **Name the search-tool ranking at the codebase-search instructions in the affected skill files.** In `receiving-code-review`, `docs-sync-internal`, and the implement stranded-dependents sweep, each instruction that tells an agent to search the codebase now names the existing Grep-tool-first ranking instead of a bare "grep" (single-named-file and verification probes are left unchanged); `docs-bootstrap-internal`'s three recursive `find` pipelines are replaced with Glob-tool directives that skip dependency and build directories; and `CLAUDE.md`'s coupled-site sweep sentence now lists the three search tools in ranking order. (#1777)
