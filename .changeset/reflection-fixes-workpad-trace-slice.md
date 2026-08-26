---
bump: patch
type: Fixed
---

- **`workpad.py update` no longer loses ticks when a plan is replaced in the same call.** Whole-section replacements (`--replace-plan-file`, `--replace-acs-file`, `--set-reproduction-file`) now run before the checkbox ticks, so a single call combining `--replace-plan-file` with `--tick-plan-n` resolves each index against the new section instead of the pre-replace one — previously the replace landed while every index past the old row count recorded a volatile miss. (#1389)
- **`workpad.py update` gained `--mark-deferred-filed-file`, the interpolation-free arm of `--mark-deferred-filed`.** A deferred criterion's normalized text routinely carries backticks and an apostrophe, which neither quoting style makes shell-safe on the cloud matcher, so the markers went unwritten and a later Phase 4 entry would re-file the same follow-up. Values are now read one per line from a file (or stdin). (#1446)
- **`lib/efficiency-trace.sh --persist` now recovers fix commits whose subject carries trailing text after the `(iteration N)` clause.** The synthesis backstop required the subject to *end* with that clause, while a fix commit's subject is authored per-run rather than emitted by a template, and in practice most carry a trailing summary (` for issue #N — …`) — 304 of this repository's own fix commits do, against 314 in the bare form. Every one of those was skipped, so the backstop recovered nothing on roughly half the commits it exists to reconstruct from. The iteration token is now read up to the first `)`; only an unterminated clause is skipped. (#1946)
