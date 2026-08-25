---
bump: patch
type: Added
---

- **`lib/test/run-parallel.sh` now reports its own elapsed wall-clock time.** The parallel full-suite coordinator prints a `run-parallel: elapsed Ns` line to standard output, placed before its clean/failed branch so it appears whether the aggregate is clean or failed, using only the bash `SECONDS` builtin. This makes the coordinator's runtime visible in a run's own records instead of recoverable only by hand from execution transcripts, so the drift that motivated this change is caught from the repository itself. (#1939)
