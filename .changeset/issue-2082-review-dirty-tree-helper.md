---
bump: patch
type: Fixed
---

- **Move the review engine's dirty-tree snapshot/restore fences into a committed helper the cloud matcher permits.** The Phase 3.1/3.2 backstop fences in the review engine were written with `${GIT_SNAP_BEFORE:-…}` variable expansions and shell redirects, which the cloud permission matcher denies — so on the cloud tier the whole statement was refused before it ran, the dirty-tree backstop was silently absent, and every review iteration paid a denial. The snapshot/authenticate/compare/restore loop now lives in the committed `scripts/review-dirty-tree.sh`, invoked by the fences as a granted leading token with literal arguments (no expansion, no redirect); the backstop's observable behavior is unchanged, and a tier that still refuses the helper records the backstop as disabled instead of losing it silently. (#2094)
