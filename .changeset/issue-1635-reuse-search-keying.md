---
bump: patch
type: Fixed
---

- **`/prflow:implement`'s Phase 2.2.4 Reuse gate now keys its search on the job the code will do, not on the syntax the run intends to write, and records a zero match bounded to what was searched.** The gate previously mandated the reuse search without constraining how it was keyed, so a run that had already decided its implementation naturally grepped for that intended shape — a search that could only confirm the decision, leaving an existing helper doing the same job in a different idiom invisible and recording the resulting clean zero as verified absence. §2.2.4's Reuse item now states the job-keying rule (build the query from the endpoint, API/operation name, data shape, or domain noun as an illustrative floor), adds a disconfirmation check as a precondition on running the search (would this match a same-job implementation written in a different idiom? re-key and re-run when it would not), and requires a zero-match result to be recorded bounded to the predicates searched — carried in the plan step that consumes the reuse result, adding no new command, tool grant, config key, or `workpad.py` invocation. (#1635)
