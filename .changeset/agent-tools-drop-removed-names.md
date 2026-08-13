---
bump: patch
---

Drop the removed tool names `LS` and `NotebookRead` from the `code-explorer` and
`code-architect` agent frontmatter. Claude Code merged `NotebookRead` into `Read` and
retired `LS` in favour of `Glob`, so both names resolved to nothing; the agents keep the
same effective tool set and the stale names no longer suggest a broken grant to consumers
on other runners.
