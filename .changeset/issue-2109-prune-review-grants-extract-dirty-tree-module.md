---
bump: patch
type: Security
---

- **Prune the review profile's orphaned `git checkout` / `cmp` grants and extract the dirty-tree helper's test battery into a focused module.** Issue #2082 moved the review engine's working-tree snapshot/compare/restore logic into the committed helper `scripts/review-dirty-tree.sh`, which runs `git checkout` and `cmp` as its own internal subprocesses — so the read-only `review` cloud tool profile no longer needs the agent-level `Bash(git checkout:*)` and `Bash(cmp:*)` grants. Both are removed from `lib/capability-profiles.json` and its `lib/review-profile.tokens` lock, the generated workflow/probe allowlists are regenerated, and the internal-docs grant rationales are reconciled; this narrows the review security boundary by dropping an unused tree-mutation grant that the internal docs named as a prompt-injection exfiltration channel. The `implement` and `command` profiles are untouched. Separately, the helper's behavioural test battery is extracted from `lib/test/run.sh` into the registered focused module `lib/test/modules/review-dirty-tree.sh`, so iterating on the helper costs one focused module run instead of a whole-suite pass. (#2109)
