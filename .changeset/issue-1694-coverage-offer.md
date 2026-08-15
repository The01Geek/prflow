---
bump: patch
type: Changed
---

- **A clean `create-issue` audit round that recorded no per-dimension coverage now joins the pre-approval recovery offer.** Previously the coverage offer trigger fired only on a genuinely-unbacked full-render round (`not-backed` + `full`), so a clean `VERDICT: FILE` round whose mandated `record-coverage` was skipped or lost reached Step 4 with the gap disclosed but never offered a round to recover it. `evaluate_coverage_trigger` now also fires on that named `no-coverage-recorded` arm, routing it through the existing single boundary offer, Step 4 precedence, `record-offer`, and the shared user-round cap. The state's backing/render/reason tokens are unchanged (absent coverage is never relabelled `not-backed`/`full`), coverage stays advisory, and filing is never blocked. (#1709)
