---
bump: patch
---

Phase 4.1's Documentation-Needed read is now a bundled helper,
`scripts/read-doc-needed-deliverables.sh`, invoked once per stage instead of
twelve lines of inline shell written twice. The helper owns the issue-body fetch,
its scratch file, the extractor invocation and both retries, and prints an outcome
token paired with its own exit status — `deliverables` (0), `no-deliverables` (10),
`body-read-failed` (11), `extract-failed` (12) — on a `docgate-outcome: ` line, with
one `docgate-path: ` line per deliverable. Those prefixes keep the outcome readable
in a tool result that merges the helper's stdout with `gh`'s and the extractor's
stderr. Stage 1's dispatch briefing and Stage 2's
per-path diff check now read that list from the command's output rather than from a
shell variable the runner does not carry between calls, the retry-and-fail-closed
rule is stated once instead of in two paragraphs that had drifted apart, and a
residual arm routes every observation outside the token-and-status contract to
`Blocked`. The read's branch selection and arm ordering are driven by the test
suite.
