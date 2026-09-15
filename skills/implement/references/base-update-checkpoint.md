<!-- prflow:implement-shared-ref file=skills/implement/references/base-update-checkpoint.md start -->
# Base-update checkpoint outcome contract

Read the helper's stdout as a leading token with its matching exit code. At an implement-driven call site, record outcomes on the issue workpad; a standalone review-and-fix call site records them in its iteration artifact and uses its native stop/report path where this contract says `Blocked`.

- `UP_TO_DATE` / `DISABLED` — continue without a workpad note. `DISABLED` means the consumer disabled implement update checkpoints.
- `UPDATED <n>` — the helper merged `origin/<base>` and pushed. Record `checkpoint <N>: merged origin/<base> and pushed (was behind by <n>)`; base-sensitive read-target rules no longer bind this run.
- `CONFLICT` — resolve deliberately. Regenerate known generated artifacts rather than hand-merging them; if you cannot establish whether the conflicted file is generated, stop and mark it needs-human-reconciliation rather than hand-merging. Preserve base additions in append-only records; abort and retry if a moving base produced an implausibly broad merge. Run the project suite, commit, push, record the conflicted files, and rerun the changed-contract sweep. If the suite is unavailable, commit and push with a locally-unverified note. If it fails, abort the merge, set the implement workpad to `Blocked` (or stop/report in standalone review-and-fix), and stop.
- `UNVERIFIED` — record the helper breadcrumb as a note and continue with base freshness unverified.
- `PUSH_REJECTED` — record a dropped-failed breadcrumb and continue without a third push attempt only when the helper restored the pre-checkpoint tree. If stderr contains the failed-restore `WARNING`, hard-stop: the branch may carry an unpushed merge commit even when the tree is clean.
- `MERGE_IN_PROGRESS` — hard-stop rather than absorbing a prior run's unresolved merge into an ordinary commit.

Each call site may tighten this common contract explicitly; it may not silently weaken a hard stop. Checkpoint 1 blocks on every `CONFLICT` because setup recovery may not hold authorship context. Checkpoint 4 refuses publication on every non-clean token under its own bounded retry rules.
<!-- prflow:implement-shared-ref file=skills/implement/references/base-update-checkpoint.md end -->
