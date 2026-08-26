# Skill loading and body delivery

This page explains how executable skill bodies and their references reach the agent, and why a documentation page must distinguish on-disk size from runtime delivery behavior.

## Current behavior

Skill roots are loaded through the Skill or slash-command surface. Skill references are loaded through the reference-reading path used by the skill. Prompt extensions are resolved through the shared loader and appended to the command's prompt surface when the command owns that extension.

The repository measures these loading paths separately because they have different caps, truncation shapes, and failure handling. The detailed evidence record distinguishes observed behavior from limits that remain unestablished.

## Why it works this way

Treating every Markdown byte as one runtime budget leads to incorrect fixes. A page can be short enough on disk but still be delivered through a path with a different reader boundary, or a large reference can fail closed at its boundary while a skill root has a different delivery mechanism.

## Boundaries and failure paths

- A missing or empty prompt extension is not equivalent to a successfully loaded extension.
- A truncated reference must not be treated as a complete instruction body.
- The portable skill-directory anchor must be resolved in the command form permitted by the active execution tier.
- Any reader or renderer that extracts by heading or marker creates a coupled interface that must be updated with the source.

## Source of truth

- `skills/docs-verify/SKILL.md` and `skills/docs-verify/references/write-mode.md` — reference-loading and write-mode boundaries.
- `scripts/load-prompt-extension.sh` — consumer extension loading.
- `scripts/render-prompt-extension.sh` and `scripts/render-audit-prompt.py` — prompt composition and extraction.
- `lib/test/lint-reference-size.py` — reference-size guard.
- [`docs/internal/skill-body-load-delivery.md`](../skill-body-load-delivery.md) — delivery evidence.
- [`docs/internal/architecture/prompt-surfaces.md`](../architecture/prompt-surfaces.md) — ownership and coupling rules.

## Related topics

- [Prompt surfaces](../architecture/prompt-surfaces.md)
- [Command permissions](../operations/command-permissions.md)
