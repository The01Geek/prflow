# GREEN fixture — implement (fenced shape, arm ahead)

**Resolve `<skill-dir>` from the base directory the runner reports in context first — this path emits no shell command.** When the runner states a base directory, take that value as `<skill-dir>`.

<!-- prflow:skill-dir-reported-base-first -->
**Only when the runner reports no base directory**, emit the fallback command:

```bash
echo "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"
```
