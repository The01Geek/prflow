---
bump: patch
---

State the prompt-extension whole-read constraint at every `load-prompt-extension.sh`
ladder call site, not only `skills/implement/SKILL.md`. PR #1473 added "read the
ladder's output whole — no `>/dev/null`, no `| head -<n>`" where the failure was
measured; `skills/review/SKILL.md`, `skills/review-and-fix/SKILL.md` (both its own
extension and `receiving-code-review`) and `skills/pr-description/SKILL.md` invoke the
same ladder and could truncate its output the same way, with no equivalent constraint.
The sentence is byte-identical at all five sites so they read as one rule. The ladder
rungs are unchanged.
