# implement-contract module inventory

Provenance of the focused `implement-contract` module (issue #1934). It is a
navigation aid, not a second source of behavior: `implement-contract.sh` owns the
executable assertions, and the complete suite reaches the same coverage through
`module-harness.sh`'s `devflow_run_full_suite_module` boundary.

Source baseline: `origin/main` before issue #1934. Subject: `skills/implement`
(the subject `lib/test/group_labels_by_subject.py` groups these labels under).

## Extracted coverage (moved out of `lib/test/run.sh`, asserted nowhere in it now)

| Label | Former run.sh region | Subject / what it drives |
| --- | --- | --- |
| `#693` | the `#693 issue-body cache: no cut-over site re-fetches the body` banner block | `lib/test/lint-issue-body-refetch.py` driven over the real tree and its `--files-from` fixture arm; a self-contained executable block using `assert_eq`, `$LIB`-relative paths, on-disk `lib/test/fixtures/issue-body-refetch`, and its own `ibr_run` helper |

The block carries **no** pin helper, so no rename was needed and the module
carries no audited pin.

## Deliberate exclusions (labels of `skills/implement` that stay in `lib/test/run.sh`)

The population is every label `group_labels_by_subject.py` groups under
`skills/implement`: `#345`, `#448`, `#693`, `#815`, `#1557`, `#1581`, `#1633`,
`#1652`. Each below is excluded for a stated reason, not by omission.

| Label | Reason it stays resident |
| --- | --- |
| `#345` | Prose `assert_pin_unique` pins that read the shared `$IMPL_PHASES_DIR` phase-file-path variable set once in `run.sh` and consumed by many non-implement blocks; extracting the block would strand that shared setup. |
| `#448` | Drives `scripts/update-branch-checkpoint.sh` through the shared `git_sandbox` harness helper (28 call sites), a fixture used across many non-implement `run.sh` blocks; a module cannot carry it without duplicating shared harness infrastructure. |
| `#815`, `#1557` | Multi-span labels interleaved across the anchor-fallback region with each other; no single contiguous banner block carries either alone. |
| `#1581` | Its region interleaves the foreign labels `#478` and `#1606` (a shared gated-sweep-reference fixture); it is not a single-subject block. |
| `#1633`, `#1652` | Drive `lib/test/lint-worktree-fence-shapes.py` through the shared `_suite_tmp_dir`/`$REPO_ROOT` harness helpers, and `#1652`'s assertions are interleaved inside the `#1633` block; extracting them would require moving shared harness infrastructure and would split a block. |

## Notes

The module uses only the caller-provided API (`assert_eq`, and the
`module-harness.sh` helpers) plus `$LIB`-relative paths, and references no helper
that lives only in `lib/test/run.sh`. The generic harness/registry/runner checks
stay global so deleting this module cannot delete the checks that prove it runs.
