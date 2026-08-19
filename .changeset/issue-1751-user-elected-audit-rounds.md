---
bump: patch
type: Changed
---

- **`/prflow:create-issue` now offers every fresh-context audit round to the user before it opens.** The default cost of a run drops to zero audit rounds: a user satisfied with the rendered draft elects none and files immediately. Rigor is opt-in — accept the offer at the Step 4 pre-approval pause and pay for exactly the rounds you choose, up to three elected discovery rounds plus one confirming round (against the previous automatic maximum of six). The automatic re-audit after a `REVISE` verdict is abolished, and a run that elects nothing still records its decision, binds creation to that decline, and emits its body. (#1756)
