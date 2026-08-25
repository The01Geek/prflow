# review-contract module inventory

Provenance of the focused `review-contract` module (issue #1934). It is a
navigation aid, not a second source of behavior: `review-contract.sh` owns the
executable assertions, and the complete suite reaches the same coverage through
`module-harness.sh`'s `devflow_run_full_suite_module` boundary.

Source baseline: `origin/main` before issue #1934. Subject: `skills/review`
(the subject `lib/test/group_labels_by_subject.py` groups these labels under).

## Extracted coverage (moved out of `lib/test/run.sh`, asserted nowhere in it now)

| Label | Former run.sh region | Subject / what it drives |
| --- | --- | --- |
| `#1264` | the `#1264 render-time placeholder probe verdict helper` banner block | every VERDICT arm of `scripts/placeholder-probe-verdict.py`, a self-contained executable probe block building its own fixtures under its own `mktemp -d` root |
| `#1618` | the `#1618 skill-body-load-probe verdict deriver` banner block | every VERDICT value and reason arm of `scripts/skill-body-load-probe-verdict.py`, a self-contained executable probe block building its own fixtures |
| `#1897` | the issue-#1897 hardening arms interleaved inside the `#1618` block | the quoted-JSON name binding, ambiguity `unestablished`, and directory-selection hardening of the same probe; moves with `#1618`, its host block |

These two banner blocks are self-contained: they use only `assert_eq` (provided
by both runner paths), `python3`, `mktemp`, `$LIB`-relative helper/skill paths,
and their own fixtures. They carry **no** pin helper (`devflow_module_pin_*`), so
no rename was needed and the module carries no audited pin.

## Deliberate exclusions (labels of `skills/review` that stay in `lib/test/run.sh`)

The population is every label `group_labels_by_subject.py` groups under
`skills/review`: `#296`, `#529`, `#1264`, `#1618`, `#1897`. Each below is
excluded for a stated reason, not by omission.

| Label | Reason it stays resident |
| --- | --- |
| `#296` | Prose `assert_pin_unique` pins over the review-and-fix `$MAXI_SKILL`/`$MAXI_BUNDLE` and the phase-3.3 `$DEF_SKILL` — shared review-engine bundle surfaces built in `run.sh`; the obligation is about `review-and-fix`, better suited to `review-and-fix-contract` than to a `skills/review` probe module. Moving it would require rebuilding the review-engine bundle in this module for a handful of prose pins that are not this module's subject. |
| `#529` | The shared fail-closed review-engine **bundle infrastructure** (`$REVIEW_BUNDLE`/`_build_skill_bundle`) and its engine-content pins — a whole-population, shared-infrastructure label already **partially asserted** by `review-and-fix-contract.sh`. A single `owner` string cannot describe split coverage, so the coverage map correctly keeps it `unmodularized`; the shared builder must stay in `run.sh` where every subject's bundle pins consume it. |

## Notes

The generic test-harness, registry-validation, module-registration, full-suite
boundary and module-runner checks stay global so deleting this module cannot also
delete the checks that prove it is selected and executed. The module uses only the
caller-provided API (`assert_eq`, and the `module-harness.sh` helpers) plus
`$LIB`-relative paths, and references no helper that lives only in `lib/test/run.sh`.
