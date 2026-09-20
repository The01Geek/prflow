<!-- prflow:implement-ref step=2.5-workflow-guard file=skills/implement/references/phase-2-5-workflow-edit-guard.md start -->

Decide push-capability from the run-facts predicate *first*, before naming any file into a bundle: the run is push-incapable iff its run-facts block reads `tier: cloud` and `DEVFLOW_APP_ID: absent` (the `GITHUB_TOKEN` fallback, which cannot push workflows), and push-capable otherwise. The disposition is chosen up front, never inferred from a checkpoint's outcome.

Enumerate the workflow's coupled files up front — the tests and other files whose pins assert its content — by grepping the reverted-or-bundled workflow's distinctive content (a step name, a job id, or the exact literal a pin asserts) across the test suite; where the suite is runnable on the tier, run it and treat any RED as a further coupled-file signal. This grep is best-effort — it misses a pin on a structural or derived property (a line count, a file-exists check), for which the required CI test job on push is the final catch. The enumeration serves both paths.

- **Push-capable** → name the workflow edit together with its coupled files to a single durability checkpoint under the run's honest implementation message with no `[skip ci]` token, ordered before the run's remaining unrelated paths, so it is the run's first push that touches `.github/workflows/` and the tip it creates is internally consistent (CI-observed, not red).
- **Push-incapable** → invoke no bundled durability checkpoint at all: revert (or delete, for an untracked add) the workflow edit, and revert every file coupled to it in the same step, before any of them is named to a commit; route the served AC through §2.2.5 immediately, so no coupled-files-only commit is ever created or pushed.

The helper's detect-and-do-not-stage half still emits `workflow-edit guard: NOT staging` as a defense-in-depth backstop, but the up-front run-facts predicate is the primary control.

<!-- prflow:implement-ref step=2.5-workflow-guard file=skills/implement/references/phase-2-5-workflow-edit-guard.md end -->
