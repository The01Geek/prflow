---
bump: patch
---

`/prflow:create-issue` now shows its working files before the draft is presented.

Step 4 of the skill root lists this run's working files with `ls -l` and shows the raw output — error lines included — in the message that renders the draft. A reader can see which pipeline steps left artifacts behind instead of relying on the run's own account of what it did. An absent path, or one older than the run-slug pointer in the same listing, sends the run back to that file's producing step before the draft is rendered. The listing never blocks issue creation, and reports itself unestablished rather than silent when the command cannot run.

Step 1 now creates `.prflow/tmp` before writing into it, so the run-slug pointer and the Step 1 evidence artifact no longer depend on the write channel to succeed on a fresh clone.
