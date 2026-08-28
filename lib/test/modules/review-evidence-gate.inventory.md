# review-evidence-gate module inventory

Provenance of the focused `review-evidence-gate` module (issue #2075). It is a
navigation aid, not a second source of behavior: `review-evidence-gate.sh` owns the
executable assertions, and the complete suite reaches the same coverage through
`module-harness.sh`'s `devflow_run_full_suite_module` boundary.

This module is **new coverage** for a new subject, not an extraction out of
`lib/test/run.sh` — so it moved no assertions out of the monolith and no
`run.sh` region was vacated. Subject: the cloud review-evidence gate
(`scripts/review-evidence-gate.py`, the workflow-side decision), the new
`--evidence-gate-fail` arm of `scripts/flip-review-progress-failed.sh`, and the
`devflow.yml` step shell that invokes them.

## Coverage

| What it drives | How |
| --- | --- |
| `scripts/review-evidence-gate.py` — the whole gate decision | one focused-python assertion (`devflow_run_focused_python_test`) runs `lib/test/review_evidence_gate_test.py`: the classification reuse from `scripts/workpad.py` (no re-copied constants — AC4), the malformed phase-log matrix, run-root attribution by the pre/post inventory delta, and every pass / fail / unestablished / no-verdict arm over throwaway git sandboxes and stubbed reviews payloads |
| `scripts/flip-review-progress-failed.sh` `--evidence-gate-fail` arm | driven against a stubbed `gh` and a copied `workpad.py`: a terminal verdict comment left untouched without the flag, rewritten to `❌ Review failed` with it, the interim-flip control unchanged, and an unrecognized 4th argument refused as a named no-op |
| `devflow.yml`'s `Review evidence gate` step shell | the step's `run:` body is sliced out of the workflow and driven against recording stubs (`python3` standing in for the gate, a `gh` that logs every call): an APPROVED and a CHANGES_REQUESTED unbacked review are dismissed by their parsed `review_id`, a COMMENTED verdict is left to the durable comment, an absent `review_id` dismisses nothing, a `pass` token exits 0 with no dismissal, and an empty gate output is warned as unrecognized rather than passing silently |

## Notes

The module is built on the caller-provided API (`assert_eq`, and the
`module-harness.sh` helper `devflow_run_focused_python_test`) plus `python3`,
`mktemp`, `grep`, and `$LIB`-relative paths; it declares no `devflow_module_pin_*`
helper, so it needs no audited-pin rename. The generic
test-harness, registry-validation, module-registration and module-runner checks
stay global so deleting this module cannot also delete the checks that prove it
is selected and executed.
