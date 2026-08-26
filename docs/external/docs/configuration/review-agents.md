---
title: "Review Agents"
description: "Override model, effort and iteration participation for individual review agents."
---

Tune individual review passes only when your results show a clear reason to do so. PRFlow can apply model overrides to each reviewer request. It accepts and resolves per-agent effort settings. The current client cannot apply a different effort value to each agent, so PRFlow reports that the reviewer inherited the session effort.

`prflow_review.agent_overrides` is an object. It accepts a `default` entry and these canonical agent keys:

- `prflow:checklist-generator`.
- `prflow:checklist-deduper`.
- `prflow:checklist-verifier`.
- `prflow:code-reviewer`.
- `prflow:silent-failure-hunter`.
- `prflow:comment-analyzer`.
- `prflow:type-design-analyzer`.
- `prflow:pr-test-analyzer`.
- `prflow:requesting-code-review`.

The transitional `devflow:` spelling of each key remains accepted for existing configuration. Use `prflow:` for new entries.

| **Nested setting** | **Type and accepted values** | **Fallback or scaffold** | **Tier and security note** | **Example** |
| --- | --- | --- | --- | --- |
| `model` | One of `sonnet`, `opus`, `haiku`, or `fable` (the Agent tool's accepted set) | No override; global or session model applies | Shared review engine. The selected model is passed to that reviewer. A value outside the accepted set is dropped with a warning and the agent inherits the top-level `claude_model`. | `"model": "opus"` |
| `effort` | `low`, `medium`, `high`, `xhigh` or `max` | No override; session effort applies | Shared review engine. The current client cannot apply a different effort value to each agent. Invalid values warn and fall back to the session effort. | `"effort": "low"` |
| `iterations` | `first-only` | Absent means every applicable iteration | Review-and-fix. `first-only` removes that agent from later fix-loop iterations. | `"iterations": "first-only"` |

A per-agent `model` override is expressible **only** as one of the four accepted aliases (`sonnet`, `opus`, `haiku`, `fable`). A consumer whose model is addressed through a provider route sets it at the top-level [`claude_model`](/docs/configuration/providers) rather than in an `agent_overrides` entry — that top-level setting still takes the full or provider-routed identifier the route expects.

An agent-specific entry replaces the `default` entry for that agent; the default does not fill missing fields inside a specific entry. The default applies only when no specific entry exists.

<Warning>
  These overrides apply to the shared review engine, so they change every review your repository runs, including the one a human reads before merging. Moving a reviewer to a smaller model to save money lowers the quality of that merge gate. Change one agent at a time and check the findings you get afterward.
</Warning>

## Valid Override Example

```json
{
  "prflow_review": {
    "agent_overrides": {
      "default": {
        "effort": "low"
      },
      "prflow:checklist-deduper": {
        "model": "sonnet",
        "effort": "low"
      },
      "prflow:code-reviewer": {
        "model": "opus",
        "effort": "low",
        "iterations": "first-only"
      }
    }
  }
}
```

Expected result: every review agent runs at low effort, the deduper runs on Sonnet, the project-guidelines reviewer runs on Opus and takes part only in the first fix-loop iteration, and every other agent keeps the model resolved from `claude_model`.
