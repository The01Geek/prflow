---
bump: patch
type: Fixed
---

- **`/prflow:create-issue` Step 1 now names how to resolve the internal-documentation location, so a run no longer misreads `.docs.internal` as a missing file and reports a false "no documentation."** A resolution that yields no usable location now records the documentation leg unestablished rather than an established absence. (#1763)
