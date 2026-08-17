---
bump: patch
---

`/prflow:create-issue` now shows its working files before the draft is presented.

Step 4 lists this run's working files and shows the raw output — error lines included — in the message that renders the draft, so a reader can see which pipeline steps left artifacts behind instead of relying on the run's own account of what it did. A file the listing shows as missing sends the run back to that step before the draft is rendered. The listing never blocks issue creation, and reports itself unestablished rather than staying silent when it cannot run.

Step 1 now creates its temporary directory before writing into it, so the run's evidence artifacts no longer depend on that directory already existing.
