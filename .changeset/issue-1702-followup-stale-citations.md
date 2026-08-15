---
bump: patch
---

Follow-up to issue #1702's Step 3.6 decomposition: repoint four stale intra-skill citations in
the `create-issue` fallback references at the members that now own the procedures they name, and
harden the shared Step 3.6 manifest reader (validation on construction, `schema_version`
recognition, normalized path comparison) plus coverage for the non-numeric `peak_context`
sentinel paths in the context evaluator.
