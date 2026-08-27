---
bump: patch
type: Changed
---

- **`/prflow:implement` Phase 1.1 now authors the issue-body cache by tier.** On the cloud tier — and any run that cannot establish the tier — it keeps consuming the fetch's stdout and writing the cache with the Write tool (a cloud sandbox denies an absolute-target redirect). On the local/interactive tier it redirects the fetch's stdout straight to the cache path, so local runs stop spending two redundant copies of the issue body (the fetch output and the Write payload) in conversation. (#2019)
