---
bump: patch
---

Fetch every implement-run prompt extension unconditionally, and track each on the workpad.

All five consumer-prompt-extension call sites — `skills/implement/SKILL.md`,
`skills/review/SKILL.md`, `skills/review-and-fix/SKILL.md` (its own extension and
`receiving-code-review`) and `skills/pr-description/SKILL.md` — now invoke the
`load-prompt-extension.sh` ladder unconditionally rather than as a fallback that applies
only when the render-time placeholder did not render. On the cloud headless tier that
placeholder is refused deterministically and silently, and the fallback arm — reachable,
with its predicate satisfied — was simply not executed, so a consumer's committed policy
never reached the run while the run reported `Complete`. Each body's failure arm is now
scoped to fire only where the placeholder did not already resolve that extension's state,
so the local tier (where the placeholder works and the ladder's later rungs are routinely
denied) cannot record a refusal for an extension it received.

The workpad `## Progress` template gains one nested checkbox row per extension surface,
rendered from a single-source text/substring constant pair, plus an idempotent
`workpad.py update --reconcile-extension-rows` that repairs the rows into a workpad
created before they existed. A row's existence is deterministic; an unticked row survives
to the finished workpad as the record that a run did not establish that extension's state.
