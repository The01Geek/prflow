---
bump: patch
type: Changed
---

- **Bound the `exact-module-floors` reconciliation measurement where a bound actually saves time.** `lib/test/reconcile-module-floors.py` now measures the exact-policy modules that read `MODULE_HEAVY_UNIT_MODE` under `--heavy-units smoke` (today just `harness-python-guards`, whose bounded and full tallies are equal), cutting that module's measurement from roughly 268 s to 54 s while leaving every other exact-policy module's measurement argv byte-identical. (#1499)
