# PATH fixture — implement (anchor followed by a helper path; also a bare prose mention)

An anchor invocation that names a helper path after the expansion is left unflagged:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh implement
```

A bare prose mention of `${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}` that invokes nothing is not flagged either.
