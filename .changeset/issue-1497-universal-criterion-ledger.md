---
bump: patch
type: Changed
---

- **`/prflow:implement`'s acceptance-criteria gate now defines a universal criterion and gates it on a surfaces-examined ledger.** A universal criterion — one whose claim ranges over the units of a named surface rather than naming specific sites — is ticked only after a surfaces-examined ledger is recorded through the workpad `--note` path, stating per surface the units examined and a one-clause retention reason for each left unchanged; where the ledger states a size figure it uses the `prompt-surface-growth.py` byte figure, never a line count or diff stat, and a ledger that cannot be completed takes the gate's Blocked or deferral path instead of a tick. A paragraph in the fix loop's engine-resolution reference is trimmed of design narrative under the same instruction-plus-consequence prose rule, and two dense review-engine reference paragraphs are split into sub-bullets for legibility with their content unchanged. (#1790)
