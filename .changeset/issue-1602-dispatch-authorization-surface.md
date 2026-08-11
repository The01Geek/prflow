---
bump: patch
type: Changed
---

- **Express the `/prflow:implement` dispatch-authorization as a property over dispatch-instructing surfaces.** The orchestrator's always-resident authorization clause no longer carries a closed enumeration of dispatch points that shipped agents outgrew; it now authorizes a dispatch exactly when one of three surfaces instructs it — the implement bundle (root, phases, references), the review engine Phase 3.3 runs in the orchestrator's own context, and the consumer prompt extension (bounded to what the `load-prompt-extension.sh` ladder delivers, with the implement-vs-review trust asymmetry named). The `Subagent rule` and the clause both keep "testing" as inline work with a named exception for Phase 3.4's evidence verifier. (#1605)
