# GREEN fixture — review (inline-code shape inside a narrative bullet, arm ahead)

- **Reached via the `Skill` tool.** Resolve `<skill-dir>` from the base directory the runner reports in context first; this path emits no shell command. <!-- prflow:skill-dir-reported-base-first --> Only when the runner reports no base directory, run `echo "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"` as the fallback and treat the printed path as `<skill-dir>`.
