# workpad-cli module inventory

Provenance of the focused `workpad-cli` module (issue #1934). It is a navigation
aid, not a second source of behavior: `workpad-cli.sh` owns the executable
assertions, and the complete suite reaches the same coverage through
`module-harness.sh`'s `devflow_run_full_suite_module` boundary.

Source baseline: `origin/main` before issue #1934. Subject: `scripts/workpad.py`
(the subject `lib/test/group_labels_by_subject.py` groups these labels under).

## Extracted coverage (moved out of `lib/test/run.sh`, asserted nowhere in it now)

| Label | Former run.sh region | Subject / what it drives |
| --- | --- | --- |
| `#338` | the `issue #338: --rewrite-ac (post-merge) retag requires a --note rationale` banner block | `scripts/workpad.py`'s `update --rewrite-ac` structural-abort guard (appending a `(post-merge)` tag with no `--note` aborts with no PATCH), driven as a real CLI subprocess against a gh stub with its own `S338` fixtures |

`#338` is the one `scripts/workpad.py` block whose fixtures (`S338`, `run338`) are
**not** reused by any sibling block, so it moves cleanly. Its single
`assert_pin_unique` (the `#338(T6)` cross-file `phase-3-ac-gate.md` pin) was
renamed to `devflow_module_pin_unique` — the module's one audited pin — so
`workpad-cli.sh` is registered on the three pin-census surfaces.

## Deliberate exclusions (labels of `scripts/workpad.py` that stay in `lib/test/run.sh`)

The population is every label `group_labels_by_subject.py` groups under
`scripts/workpad.py`: `#126`, `#169`, `#222`, `#258`, `#266`, `#268`, `#281`,
`#287`, `#289`, `#338`, `#356`, `#362`, `#498`, `#519`, `#682`, `#755`, `#781`,
`#814`, `#857`, `#871`, `#1025`, `#1611`. All except `#338` stay resident; each
below is excluded for a stated reason, not by omission.

The dominant reason is **shared setup**: the `scripts/workpad.py` coverage in
`run.sh` is one large intertwined region whose gh stubs and workpad fixtures
(`WP_BODY`, `WP_CREATEBODY`, `WP_PATCHLOG`, `S356`, and sibling `S<label>`/`GHD`
roots) are shared across many blocks. Extracting a single label's assertions
would strand fixtures its siblings consume.

| Label(s) | Reason it stays resident |
| --- | --- |
| `#222` | Its `U8_SCRIPTS`/`U8_*` UTF-8 self-defense fixtures are reused by the sibling `#1762` block that follows; removing the block would break `#1762`. |
| `#258` | Its `S258`/`run258` fixtures are reused by the sibling `#1348` terminal-required-artifact-gate block; removing the block would break `#1348`. |
| `#281` | Reuses the `#266` block's `WP266_GHD` gh-stub directory; not self-contained. |
| `#682`, `#781`, `#814` | Read the shared `WP_BODY`/`WP_CREATEBODY`/`WP_PATCHLOG`/`S356` fixtures set up once and consumed by many blocks. |
| `#266`, `#268`, `#287`, `#498`, `#1025` | Heavily interleaved across one shared workpad test region (multiple spans each, alternating labels); no single-subject contiguous block carries any of them. |
| `#356`, `#362`, `#519`, `#289`, `#857`, `#871` | Multi-span labels that interleave with each other and, in places, with non-workpad labels (`#857` shares assertion lines with `#529`); a single `owner` cannot describe split coverage, so the map keeps them `unmodularized`. |
| `#126`, `#169`, `#755`, `#1611` | Depend on shared phase-file-path variables (`$P1_FILE`/`$P2_FILE`) or shared workpad setup consumed by sibling blocks. |

Extracting any of these would require moving the shared workpad fixture harness
and disentangling interleaved sibling labels — out of scope for the per-block
extraction this change performs.

## Notes

The module uses only the caller-provided API (`assert_eq`, the
`devflow_module_pin_*` helpers, and the other `module-harness.sh` helpers) plus
`$LIB`-relative paths (`WP_PY="$LIB/../scripts/workpad.py"`), and references no
helper that lives only in `lib/test/run.sh`. The generic harness/registry/runner
checks stay global so deleting this module cannot delete the checks that prove it
runs.
