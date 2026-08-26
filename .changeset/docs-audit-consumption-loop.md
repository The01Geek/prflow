---
bump: patch
---

Close the internal-docs consumption loop: code-explorer and code-architect read a dispatch-named documentation index first (code stays authoritative), Phase 2.1 names `index.md` as the exploration entry point, `PRIMARY_PATHS` supplements the doc map instead of replacing it, and the `.docs.internal` root is resolved orchestrator-side rather than inside the Bash-less explorer's prompt.
