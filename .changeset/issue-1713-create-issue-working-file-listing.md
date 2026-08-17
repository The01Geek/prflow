---
bump: patch
---

`/prflow:create-issue` now shows its working files before the draft is presented.

Step 4 lists four of the run's working files and shows the raw output — error lines included — in the message that renders the draft, so those files are visible rather than asserted. A file the listing shows as missing sends the run back to the step that produces it before the draft is rendered. The listing never blocks issue creation, and reports itself unestablished rather than staying silent when it cannot run.

Step 1 now creates its temporary directory before writing into it, so the Step 1 evidence artifact and the run-slug pointer it writes there no longer depend on that directory already existing.
