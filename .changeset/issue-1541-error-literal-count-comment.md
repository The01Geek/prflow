---
bump: patch
type: Changed
---

- **Reworded a stale count in the `compose-implement-prompt.sh` extraction rationale.** The comment claimed "the two `::error::` literals" when the helper emits four; both the helper's own comment and its mirror in `devflow-implement.yml`'s `Compose implement grounding block` step are now count-free, preserving the extraction rationale without a figure that drifts. (#1543)
