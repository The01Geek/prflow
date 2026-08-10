---
bump: patch
---

Widen `lint-ungranted-helper-spelling.py`'s audited population from `skills/**`+`agents/**`
to the other prompt surfaces a cloud review run auto-loads: the consumer prompt-extension
prefix, `CLAUDE.md` (project memory at the review workspace root), and the internal overview
page `CLAUDE.md` cites as the canonical verdict-marker statement. Both taught a review run
the repo-relative `scripts/post-review-verdict.sh` spelling the cloud matcher denies before
it runs — a denial that produces no output, after which the engine takes its silence arm and
records no verdict (PR #1533, issue #1526). The widened lint now reports clean on them, the
occurrences it named having been reconciled to the bare-filename naming form it prescribes.
