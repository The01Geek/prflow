# Retired create-issue budget record

This page preserves the internal link target used by historical create-issue cutover records. It is not a current runtime budget or enforcement source.

## Current status

The former create-issue word-budget and prompt-length enforcement subsystem was retired. Current skill loading and reference-size behavior are documented in [Skill loading](skills/skill-loading.md) and [Runtime evaluations](improvement-loops/runtime-evaluations.md). The executable skill and its guards remain authoritative for present behavior.

## Historical evidence

The historical cutovers under `cutovers/` retain the measurements and decision context for the earlier thin-root and reference split. The repository changelog records the retirement and the associated historical figures.

## Source of truth

- `CHANGELOG.md` — release history for the retired budget subsystem.
- `docs/internal/cutovers/issue-614-create-issue-thin-root-relocate.md` — original split record.
- `docs/internal/cutovers/issue-749-step1-right-sizing-growth.md` — later growth and ceiling record.
- `skills/create-issue/SKILL.md` and `skills/create-issue/references/` — current executable behavior.
