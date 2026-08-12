---
bump: patch
type: Fixed
---

- **`/prflow:implement` and `/prflow:review` now resolve their skill directory from the runner-reported base directory first, falling back to the `echo "${CLAUDE_SKILL_DIR:-…}"` command only when the runner reports no base directory.** The resolve-once command is refused on runners whose permission matcher denies the `${VAR:-default}` argument expansion, and the old fail-closed rule listed only outcomes where the command *ran* — so a tool-level refusal fell outside every arm, either halting the run at its first command or skipping the step silently. The two skill bodies now classify the fallback command's outcome into three shapes (a tool-level refusal reported as the `$CLAUDE_SKILL_DIR` channel being unestablished, a command that ran and printed empty, and one that ran and printed the placeholder unsubstituted), and an implement run that resolved from the reported base directory records the resolving channel in a reflection. A new desk-time lint (`lib/test/lint-reported-base-dir-arm.py`) keeps the reported-base-directory-first arm ahead of the value-consuming expansion at each enrolled call site. (#1626)
