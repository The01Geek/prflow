---
bump: patch
type: Changed
---

- **Name the search-tool ranking at every search instruction in the affected skill files.** In `receiving-code-review`, `docs-sync-internal`, and the implement stranded-dependents sweep, each instruction that tells an agent to search the codebase now names the existing Grep-tool-first ranking instead of a bare "grep"; `docs-bootstrap-internal`'s three recursive `find` pipelines are replaced with the Grep/Glob tools so exploration searches the tracked tree rather than walking dependency and build folders; and `CLAUDE.md`'s coupled-site sweep sentence now lists the three search tools in ranking order. (#1777)
