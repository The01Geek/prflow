---
bump: patch
type: Fixed
---

- **Say which path is authoritative in the review engine's reference boundary contract.** The contract told the agent to count the lines matching the expected `start` and `end` markers, "expected meaning bearing this phase's id and path", without stating **which** path — the one the run resolved the file from, or the bundle-relative path baked into the marker. The two readings disagree on any vendored install, where the engine reads a phase at `.prflow/vendor/prflow/skills/review/phases/<name>.md` while the marker names `skills/review/phases/<name>.md`: under the resolved-path reading every marker fails to match, so `S` and `E` both count 0 and every phase stops at `boundary: missing` with no verdict produced. The contract now states that the marker's own bundle-relative path is authoritative and that the resolved read path is not a comparand. `docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md`'s coupled restatement is reconciled in the same change; the marker template, the seven boundary stop labels and their fixed test order are unchanged. (#1561)
