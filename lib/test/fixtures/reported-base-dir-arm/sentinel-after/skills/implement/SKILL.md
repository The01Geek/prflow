# SENTINEL-AFTER fixture — the sentinel exists but sits AFTER the value-consuming
# expansion, so the "arm ahead of it" ordering contract is violated → must be flagged
# (a regression weakening the check to mere sentinel presence would wrongly pass this).

Resolve the skill directory once now:

```bash
echo "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"
```

<!-- prflow:skill-dir-reported-base-first -->
This sentinel is placed below the fallback command, which is the wrong order.
