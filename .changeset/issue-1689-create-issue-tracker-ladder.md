---
bump: patch
---

`/prflow:create-issue` now establishes its completion tracker before announcing it. The tracker mandate reads as an ordered candidate ladder — pick only from the tools the runner lists as exposed, move to the next candidate when one is unavailable, look for a runner-advertised discovery mechanism when none is listed, and fall through to the inline checklist fallback when every candidate is exhausted. A task-tool call the runner answers with a failure now leaves a breadcrumb and continues to the next rung instead of ending the run, matching the degrade-and-continue treatment a failed reference load already had. The announcement is emitted only once a tracker exists and stays the run's first line of output, with a failed-candidate breadcrumb reported after it.
