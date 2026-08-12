---
bump: patch
type: Changed
---

- **`prflow_review.agent_overrides.<agent>.model` now takes the Agent tool's accepted aliases
  (`sonnet`, `opus`, `haiku`, `fable`) rather than a free-form model identifier.** The review
  engine dispatches each reviewer through the Agent tool's per-invocation `model` parameter,
  which is a closed enum; a full model identifier such as `claude-opus-4-8` is rejected there.
  `scripts/resolve-review-overrides.py` now validates `model` against that accepted set exactly
  as it already validates `effort`: an out-of-set value is dropped with a warning naming the
  value and the accepted set, and the agent dispatches with no model override (inheriting the
  top-level `claude_model`); an in-set value is forwarded unchanged. The config schema gains a
  matching `enum`, and the engine root states one arm for a dispatch-time rejection of the
  `model` parameter (re-dispatch that agent once with no model override and report the fallback).
  A per-agent `model` override is now expressible only in that alias vocabulary; a consumer whose
  model is addressed through a provider route sets it at the top-level `claude_model` instead.
  **Existing consumers: re-run `/prflow:init` or `install.sh --apply` to have your
  `agent_overrides` `model` values rewritten to the accepted aliases. Until you do, a dropped
  out-of-set override falls back to the top-level `claude_model`.** (#1650)
