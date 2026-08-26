# Prompt-surface ownership

This page explains how the repository's loaded instructions, prompt extensions, and executable consumers fit together. Read it before moving or compressing `CLAUDE.md`, a live prompt extension, or a skill body.

## Current behavior

`CLAUDE.md` supplies repository-wide instructions. Live files under `.prflow/prompt-extensions/` add command-specific instructions to the skills that load them. The executable skill and agent bodies under `skills/` and `agents/` consume those instructions through their own runtime contracts.

The same wording can be coupled to more than one consumer. A heading, marker, literal, or section boundary may be read by a renderer, guard, workflow, test, or prompt composer. Moving such text without updating its reader can silently truncate a prompt or leave a guard checking the wrong surface.

Current prompt-surface ownership is established by the machine readers and coupling audits, not by visual similarity between Markdown files. A canonical rule belongs in its owning loaded surface; a maintainer explanation belongs in the relevant internal page or historical cutover.

## Why it works this way

Loaded prompt surfaces are executable inputs, not ordinary prose. Keeping one authoritative owner for a rule reduces semantic drift, while recording coupled readers makes a safe relocation possible. The separation also keeps maintainer rationale out of the prompt body that an agent must execute.

## Boundaries and failure paths

- A heading used as an extraction key is an interface. Renaming it requires updating the reader and its guard in the same change.
- A marker or literal consumed by a script is an interface even when the surrounding paragraph is prose.
- A rule may remain in more than one surface only when the coupling is explicit, mechanically guarded, or a command-specific application of a general rule.
- Historical audit pages explain prior placement decisions. They do not override the current loaded surface.

## Source of truth

- `CLAUDE.md` — repository-wide loaded instructions.
- `.prflow/prompt-extensions/*.md` — live consumer-owned prompt extensions.
- `skills/*/SKILL.md` and `skills/*/references/*.md` — executable skill and reference bodies.
- `scripts/render-audit-prompt.py`, `scripts/render-prompt-extension.sh`, and related renderers — prompt composition and extraction behavior.
- `lib/test/regenerate-artifacts.py` and the prompt-surface guards under `lib/test/` — coupled-site and drift checks.
- [`docs/internal/claude-md-extension-audit-consumers.md`](../claude-md-extension-audit-consumers.md) — consumer enumeration evidence.
- [`docs/internal/claude-md-extension-audit-coupled-sites.md`](../claude-md-extension-audit-coupled-sites.md) — coupled-site evidence.
- [`docs/internal/claude-md-extension-audit-duplicates.md`](../claude-md-extension-audit-duplicates.md) — permitted overlap evidence.

## Related topics

- [System overview](system-overview.md)
- [Skill loading](../skills/skill-loading.md)
- [Command permissions](../operations/command-permissions.md)
- [Historical cutovers](../cutovers/)
