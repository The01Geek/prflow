---
bump: patch
type: Fixed
---

- **Correct the embedded-`jq` gotcha in `CLAUDE.md`.** The bullet no longer claims the lint never reaches inline `jq` in workflow files: it now names shellcheck (over `.sh` files) and `actionlint` (over workflow `run:` blocks) as the two surfaces the apostrophe check reaches, keeps the still-uncaught warning about string ops on a possibly-non-string field and its `(.x | strings)` guard, and adds the `reduce`/`test()` trap where a field resolves against the line being tested rather than the accumulator unless it is bound to a variable first. (#1913)
