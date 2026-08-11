---
bump: patch
type: Fixed
---

- **`/prflow:implement` no longer publishes a PR or records `Complete` while its local branch tip is absent from the remote.** A Phase-3-or-later commit (a changeset, a review-fix, a docs or artifact commit) could be committed locally and never pushed; the Phase 4.3 clean-tree backstop uses `git status --porcelain`, whose short form reports a committed-but-unpushed tip as clean, so the run would publish a PR whose body cited a commit the remote could not resolve. A new tip-landed gate now runs before the publish decision: it confirms `git rev-parse HEAD` equals `@{u}`, landing an unpushed tip with a push or stopping at `Blocked`, and reports a detached HEAD or a no-upstream branch distinctly rather than as an unpushed tip. (#1617)
