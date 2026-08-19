---
bump: patch
type: Fixed
---

- **`create-issue` no longer pauses a second time for a final-byte audit offer once a run has already converged.** When the drafter's own self-verified resolutions closed every finding from a steering-established round (the run converged `basis=resolution`), `issue-audit-state.py`'s `query-final-byte` now reports `final_byte_trigger=not-hold` with `final_byte_reason=resolution-settled`, so Step 4 sub-step 3a makes no redundant final-byte offer. The coverage axis still reports the bytes `uncovered` truthfully — only the offer is withheld — and the offer still fires whenever the round's independence was not established or findings remain unresolved. (#1782)
