---
title: "Review Agents"
description: "Override the model and iteration participation of individual review agents."
---

Tune individual review passes only when your results show a clear reason to do so. PRFlow can apply a model override to each reviewer request. A per-agent `effort` is accepted but ignored: every review agent runs at the session effort.

`prflow_review.agent_overrides` is an object. It accepts a `default` entry and these canonical agent keys:

- `prflow:checklist-generator`.
- `prflow:checklist-verifier`.
- `prflow:code-reviewer`.
- `prflow:silent-failure-hunter`.
- `prflow:comment-analyzer`.
- `prflow:type-design-analyzer`.
- `prflow:pr-test-analyzer`.
- `prflow:requesting-code-review`.

The transitional `devflow:` spelling of each key remains accepted for existing configuration. Use `prflow:` for new entries. The checklist deduper no longer runs: an existing `prflow:checklist-deduper` entry is accepted and ignored.

| **Nested setting** | **Type and accepted values** | **Fallback or scaffold** | **Tier and security note** | **Example** |
| --- | --- | --- | --- | --- |
| `model` | One of `sonnet`, `opus`, `haiku`, or `fable` (the Agent tool's accepted set) | No override; global or session model applies | Shared review engine. The selected model is passed to that reviewer. A value outside the accepted set is dropped with a warning and the agent inherits the top-level `claude_model`. | `"model": "opus"` |
| `effort` | Deprecated: still validates, ignored | Session effort | Shared review engine. Every review agent runs at the session effort whatever this holds; remove it when convenient. | — |
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
      "prflow:checklist-verifier": {
        "model": "sonnet"
      },
      "prflow:code-reviewer": {
        "model": "opus",
        "iterations": "first-only"
      }
    }
  }
}
```

Expected result: the checklist verifier runs on Sonnet, the project-guidelines reviewer runs on Opus and takes part only in the first fix-loop iteration, and every other agent is dispatched with no override.

## Coverage Reviewer and Proportionate Verification

A fresh install ships the coverage reviewer (`prflow:pr-test-analyzer`) with `"iterations": "first-only"`, so it reviews on the first fix-loop iteration and the standalone review but is dropped from later fix-loop iterations. An existing configuration keeps its own value; the shipped default reaches an existing repository only for this key if the key is absent, at the next re-scaffold.

Implementation and fix runs choose the smallest reliable verification for the changed behavior, respecting your repository's testing requirements and agreed criteria. Existing coverage or direct checks can suffice; permanent tests are added for consequential behavior that needs recurring protection. Test-first remains preferred for reproducible bugs. The coverage reviewer assesses meaningful gaps and accepts coverage at another level instead of requiring a test per changed function. Test Plans report actual checks and limitations without requiring test-authoring waiver declarations; historical decisions remain intact.
