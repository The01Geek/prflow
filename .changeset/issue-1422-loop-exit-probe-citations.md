---
bump: patch
type: Fixed
---

- **Drop non-consumer-resolvable probe-row and run-id citations from the shipped `review-and-fix` loop-exit reference.** The *Completion-evidence check* paragraph in `skills/review-and-fix/references/loop-exit.md` justified treating the completion-evidence validator's review-tier permitted-ness as unrecorded by citing this repository's own matcher-probe row ordinals and a GitHub Actions run id — pointers a consumer repo (which receives the file verbatim) cannot consult. The paragraph now states each surviving instruction by naming the thing rather than the ordinal, preserving all four instructions. (#1857)
