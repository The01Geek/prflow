# WRAPPED-SENTINEL fixture — the reported-base-directory-first sentinel is wrapped across
# adjacent lines, so it is found only after whitespace normalization. Deleting the
# `" ".join(text.split())` normalization would leave the raw `.find` unable to locate the
# sentinel, flip this to a false RED, and this fixture would catch that regression.

Resolve `<skill-dir>` from the base directory the runner reports in context first.

<!--
prflow:skill-dir-reported-base-first
-->
**Only when the runner reports no base directory**, emit the fallback:

```bash
echo "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"
```
