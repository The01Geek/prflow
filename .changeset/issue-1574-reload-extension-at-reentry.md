---
bump: patch
type: Fixed
---

- **Reload each consumer prompt extension at its surface's re-entry boundary, not only at run start.** The `implement`, `review`, and `review-and-fix` skill bodies now re-invoke their `load-prompt-extension.sh` ladder at each existing re-entry boundary — every phase (re-)entry and mid-phase re-anchor for `implement`, every phase and shadow entry for `review`, and once per iteration for the fix loop's `review-and-fix` and `receiving-code-review` ladders — so a run that loses the extension to context compaction recovers it rather than continuing its whole remainder without consumer policy. Each re-invocation refreshes already-loaded policy rather than issuing a fresh directive, and `pr-description` (single-pass) is unchanged. (#1578)
