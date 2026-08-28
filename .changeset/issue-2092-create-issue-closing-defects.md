---
bump: patch
type: Fixed
---

- **Fixed the closing-step defects in `/prflow:create-issue` reported from a consumer repo.** The Step 4 run-state listing no longer names the audit artifact — it was absent on every run at listing time, so `ls -lL` printed a false not-found diagnostic; the presentation gate remains the sole owner of that artifact. The investigation-record comment now folds the run's decision record (the criterion disposition record, the steelman record, and the evidence bundle) so the reasoning behind each criterion survives the closing cleanup, which now reports the blocks it deletes; the folded comment is neutralized against workflow-trigger tokens and truncated when it exceeds GitHub's 65,536-byte comment limit. The shared provenance line is now appended in the run bootstrap so the run's first canonical draft write carries it, saving a second staged write and digest per run, and the internal documentation now describes that ordering. (#2093)
