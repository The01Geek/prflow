---
bump: patch
type: Fixed
---

- **`reconcile-module-floors.py` no longer leaks `DEVFLOW_TEST_EXPERIMENT_FORCE_FAILURE` into the focused-runner measurement.** The reconciler now scrubs that experiment variable from the environment it hands each exact-policy module's measurement, so an operator who left it exported gets a real measurement rather than a refusal that names a module instead of the override. The `exact-module-floors` batched-pass classifier and the reconciler's registry-scan and empty-population refusals also gain full test coverage. (#1506)
