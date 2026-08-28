---
"prflow": minor
---

Record a truthful externally-dependent verification as non-reusable completion evidence (#2084).

`scripts/verification-flight.py` now accepts a `claim` whose `external_services` truthfully names a live service the verification depends on, storing the flight under a distinct non-reusable record schema instead of refusing it at claim time. Such a flight satisfies verification and backs completion evidence, so an implement run that verified its change against a live external service can finish Complete honestly; but `status`, `wait`, and the claim-attach view report `reuse_ready: false`, so the reuse path never serves it as a clean prior result. A malformed `external_services` value (not a string, blank, or a value that names no service) is still refused, and an exact `"none"` declaration behaves exactly as before.
