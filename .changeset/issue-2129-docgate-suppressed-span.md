---
bump: patch
---

Phase 4.1 documentation gate records only run-specific workpad facts (issue #2129).

`scripts/read-doc-needed-deliverables.sh` now captures the extractor's stderr, forwards it unchanged to its own stderr, and relays the first suppressed Documentation Needed span onto stdout as a self-identifying `docgate-suppressed: ` line (the span's text with the breadcrumb's surrounding backticks removed). Phase 4.1 Stage 1 records a workpad note naming that span only when such a line is present — delivered through `--note-file`, never a double-quoted shell argument — replacing the fixed, always-false once-per-run disclosure sentence. The deferred documentation-AC discharge now ticks a criterion that names a check command only after the orchestrator has itself run that command (or the covering run the coverage map names) over the landed docs and quoted the result line, never on a subagent's report or a gate that has not yet run.
