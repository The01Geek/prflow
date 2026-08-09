---
bump: patch
---

Remove the render-time prompt-extension placeholder from `skills/review/SKILL.md` and reconcile
its surrounding prose to the single `load-prompt-extension.sh` invocation ladder. The placeholder's
permission check aborts a `Skill`-tool load of `prflow:review` on the cloud tier, so the engine root
returned no body at all and the run improvised past its phase references. Single-variable experiment:
the other three placeholder sites are unchanged.
