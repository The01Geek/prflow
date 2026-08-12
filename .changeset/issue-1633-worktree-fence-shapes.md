---
bump: patch
type: Fixed
---

- **Implement-bundle fences no longer use shell expansions a worktree-isolated Claude Code session refuses.** Every enrolled implement phase file (`phase-1-setup`, `phase-2-implement`, `phase-3-review`, `phase-4-documentation`) was migrated off command substitution, `$?`, and same-fence variable references; arm-selection is now agent-side routing on the tool result's exit code (a refused or no-output invocation is treated as an unestablished measurement that reaches the stop path). `scripts/preflight.py` and `scripts/parse-acs.py` gain a repository-relative anchoring mode so no fence computes the repository root, and a new `lib/test/lint-worktree-fence-shapes.py` fails the suite on any enrolled fence that reintroduces one of the three refused constructs. The `preflight.py` helper is now granted in the `command` capability profile as well as `implement`. (#1642)
