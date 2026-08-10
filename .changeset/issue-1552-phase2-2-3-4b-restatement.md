---
bump: patch
---

Trim `/prflow:implement` Phase 2 §2.3.4b (the coverage-claim enumeration sweep) down to its procedure. The `--worktree` flag's semantics, the TSV row-token definitions, and the catalog of conditions behind the helper's exit `2` are no longer restated in the phase file; one sentence now points at `scripts/stale-prose-lint.py`'s own `--help` output and module header instead. The section's three worked examples are deleted — one of them attributed a quoted sentence to that helper that the helper does not contain.

The sweep's procedure is unchanged. Its invocation legs, its outcome arms and their deciding observables, the grounding treatments, the carve-out, and the `--note` record obligation on the clean path as well as the dirty one all read as they did before.
