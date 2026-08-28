# Review-engine dirty-tree backstop module inventory

This inventory records the provenance of the focused behavioural battery for the
review engine's dirty-tree backstop helper `scripts/review-dirty-tree.sh` (issues
#2082/#216/#484/#1470/#192). It is a navigation aid, not a second source of behavior:
`review-dirty-tree.sh` owns the executable assertions, and the complete suite calls
the same module through `module-harness.sh`'s `devflow_run_full_suite_module`
boundary. The `lib/test/run.sh` call site is registered directly after the
`phase2-durability-checkpoint` boundary.

Source baseline: this module was **extracted from `lib/test/run.sh` by issue #2109**
— it carries forward the pre-existing `#2082`/`#484`/`#216`/`#1470`/`#192` dirty-tree
helper-behavior battery verbatim in behaviour. The sibling left behind in
`lib/test/run.sh` is the skill<->helper wiring and fence-shape prose pins (they assert
the review bundle's prose, not the helper's runtime behaviour), which stay in the
whole-suite driver.

Its assertion floor is recorded once, in
`scripts/workflow-flight-recorder-registry.json` (`assertion_floor_policy: exact`),
and enforced on every run by `lib/test/run-module.sh`; `test_module_runner.py`
reconciles that floor against the `lib/test/run.sh` call-site literal. This inventory
deliberately states no exact assertion count — the registry is the single source, so a
count copied here could drift out of it silently.

Every assertion is behavioural: the helper is driven directly (`snapshot` /
`compare-and-restore OID`, with the `GIT_SNAP_BEFORE`/`GIT_SNAP_AFTER` env seam pointed
at per-test temp paths) against **real** throwaway git repositories allocated by the
harness's `git_sandbox` — the git plumbing under test is not mocked — and judged on the
resulting working-tree state and the helper's stderr breadcrumbs and exit code. There
is no wording-only pin here (issues #375/#666/#810).

| Contract group | Issue | Representative contract |
| --- | --- | --- |
| Helper existence + CLI dispatch | #2082 AC4 | the helper exists and is executable; a missing/empty restore-authorising OID, an unknown subcommand, and a wrong argument count each exit 2 — no restore from a malformed invocation |
| Snapshot capture | #216/#484 | a real `-z` capture produces an authenticated regular file whose object ID the orchestrator records; a stale snapshot symlink is removed without clobbering its target; a successful capture leaves no disabled sentinel |
| By-path restore safety | #216/#1470 | an already-dirty path is never clobbered while a newly-dirtied path is restored to HEAD, across spaced, glob-metacharacter and newline-containing pathnames |
| Rename / untracked residuals | #216/#192 | a true rename is surfaced-not-restored; an untracked dispatch-window file is never auto-deleted and its residual is breadcrumbed |
| Fail-closed snapshots | #484/#2082 | a truncated non-NUL and a genuinely-missing before-snapshot each fail closed without clobbering an existing edit |
| OID authentication | #484 | an authentic OID permits a snapshot-delta restore (positive control); a forged regular baseline and a symlink baseline each skip all restoration and emit their integrity/tamper breadcrumb |
| Symlink-attack (host-capability-gated) | #484 | stale/race-swapped symlinks at the before/after snapshot paths disable the backstop or are rejected as capture failures with the target untouched — routed through `module_host_capability_skip` on a host that cannot create symlinks |
| Disabled sentinel / scratch guards | #2082 | a disabled sentinel short-circuits compare-and-restore; the scratch-allocation and function-entry `mkdir` guards on both the snapshot and compare sides fail closed with distinct breadcrumbs |
| Comparison guards | #2082 | a `cmp` comparison error and an unverifiable post-restore `git status` (rc≠0) each fail closed with a distinct breadcrumb rather than driving a restore off a failed comparison |
