---
bump: patch
type: Fixed
---

- **Compress `skills/create-issue/references/step-3-6-audit.md` so its Step 3.6 load stops truncating.** The file had grown past the file-read tool's per-read token cap, so a whole-file read returned a partial view; because the reference is boundary-gated (its first line must be the `start` marker and its last the matching `end` marker), a truncated read failed the gate and `/prflow:create-issue` fell to its degraded one-round in-chat self-audit instead of dispatching the fresh-context auditor. Only prose the instruction-plus-consequence rule excludes was removed (explanation past one consequence sentence, reviewer pre-emption, restated facts); the fenced commands, section headings, boundary markers, and the literals the create-issue test suite pins are preserved verbatim, verified by the create-issue-contract module and the audit-lifecycle contract check staying green. The file now reads whole in one call, so Step 3.6 enters on its normal path and dispatches the fresh-context auditor. (#1601)
