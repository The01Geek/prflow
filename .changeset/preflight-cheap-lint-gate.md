---
bump: patch
---

`lib/test/run-parallel.sh` now runs the two sub-second, read-only cheap lints — the
reference-size ceiling and the brand-baseline sweep — as part of its pre-launch checks,
on both the coordinator's own flow and the standalone `--preflight` route. Both are
`run.sh`-resident, so previously nothing cheaper than a full coordinator pass caught
either: a cloud implement run spent 12.6 minutes discovering one, then a further 12.5
minutes on the mandatory relaunch after a one-line fix. The gate refuses in well under a
second instead. It fails closed only on a positively-attributed finding (keyed on each
lint's own completion sentinel, since a traceback shares a finding's exit code) and fails
open on any outcome that leaves the check unusable, matching the existing generated-artifact
preflight's verdict contract.
