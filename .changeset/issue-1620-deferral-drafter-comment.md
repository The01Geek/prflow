---
bump: patch
type: Fixed
---

- **Corrected a misleading comment in the `#1604` deferral-drafter pin block of `lib/test/run.sh`.** The block's header comment attributed the agent's write-literal and dispatch prohibitions to `lint-shipped-pruned-path.py`, which audits path/citation references in `skills/**`/`agents/**` and enforces no such thing. The comment now states the wrong change it prevents (do not relax the write-literal absence pins as redundant) and names the real runtime enforcer — the agent's `tools:` frontmatter pinned in that same block. Comment prose only; no assertion or pin changed. (#1779)
