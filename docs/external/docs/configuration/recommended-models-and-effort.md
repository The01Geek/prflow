---
title: "Recommended Models and Effort"
description: "The model and effort level to start a PRFlow command's session with, and why a stronger setting costs more."
---

These recommendations cover the session you start a command in. `/prflow:help` reads this page to compare a session's model and effort with them.

| **Command** | **Model** | **Effort** |
| --- | --- | --- |
| `spec` | Opus 5.5 (`claude-opus-5-5`) | `high` or above |
| `implement` | Opus 5.5 (`claude-opus-5-5`) | `low`; `medium` for exceptionally complex implementations |

Commands without a row have no recommendation.

## How settings compare

Models are compared by family, from least to most capable: Haiku, then Sonnet, then Opus, then Fable.

Effort levels, from lowest to highest: `low`, `medium`, `high`, `xhigh`, `max`. Opus 5.5 defaults to `medium`, which is above the `implement` recommendation. Change the level for a session with `/effort`.

PRFlow subagents that set their own model are not governed by the session model.

## Why a stronger setting costs more

A more capable model or a higher effort level reasons longer and writes more tokens on each turn. Each turn takes longer and uses more tokens, so a whole run costs more time and money. Below the recommendation, results can lose quality. Above it, runs get slower and more expensive.
