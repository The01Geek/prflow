---
bump: patch
type: Fixed
---

- **Check the fix loop's engine-helper reviewer roster against an operand the parent can evaluate.** The Step-1 (and shadow) well-formedness check previously recomputed the expected Phase-3 roster from `diff_profile`, which cannot express `pr-test-analyzer`'s test-relevance predicate — so a helper that correctly gated that reviewer out returned a roster the parent declared malformed, falling back to re-running the whole review engine inline and discarding the helper's finished work. The engine now records its own Phase 3.1 gate decisions as a new `expected_reviewers` return member (mirroring the shadow block's existing field), and the parent compares the dispatched roster against that reported roster instead of `diff_profile`. `expected_reviewers` is added to `lib/efficiency-trace.sh`'s `ITER_EXPECTED_FIELDS` as an unconditional field. (#1927)
