---
bump: patch
type: Added
---

- **`/prflow:create-issue` Step 3.5 now sweeps the assembled draft for unrequested guarantees.** A new mandatory request-origin sweep flags every acceptance criterion and named Testing-Strategy assertion whose asserted guarantee the request did not name and which no failure the change introduces requires, reporting them in the step's one-line summary (with a falsifiable zero arm) and its persisted `### pass <n>` record so the drafter revises them away under the existing revise-and-re-gate loop; a criterion resting on a change-introduced failure is not flagged, and the sweep refuses no draft. (#1703)
