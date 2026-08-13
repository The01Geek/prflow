# Workflow triggers

This page explains which events and commands enter PRFlow workflows and how duplicate or unsafe requests are handled.

## Current behavior

Cloud workflows route supported issue and pull-request comments into the corresponding `/prflow:*` command. The trigger surface distinguishes real comments from quoted text, ignores PRFlow's own workpad as a new implement request, and applies command-specific authorization and deduplication before dispatching the agent.

The trigger path is separate from the skill body. A change to a comment matcher, event filter, actor gate, or concurrency rule can change whether the skill runs at all and must be traced through the workflow definition and its helper scripts.

## Why it works this way

Event routing is a security and cost boundary. Restricting the accepted event and actor shapes prevents arbitrary pull-request content from reaching a privileged writer job, while deduplication prevents repeated comments or concurrent requests from producing conflicting runs.

## Boundaries and failure paths

- A command in a description, quoted block, or workpad is not automatically a trigger.
- A request that cannot establish its actor or event precondition must not be treated as authorized.
- Dedupe behavior is intentionally scoped to the command and head it protects; a failure-open path must remain visible.
- The withheld automatic review tier is not the supported default trigger path for fresh installations.

## Source of truth

- `.github/workflows/devflow.yml` and `.github/workflows/devflow-implement.yml` — event and command routing.
- `.github/workflows/ci.yml` — pull-request verification jobs.
- `scripts/authorize-actor.sh`, `scripts/react-to-trigger.sh`, and deduplication helpers — trigger decisions.
- `skills/*/SKILL.md` — command behavior after dispatch.
- `docs/internal/workflow-triggers.md` — detailed trigger matrix and historical rationale.

## Related topics

- [Delivery lifecycle](delivery-lifecycle.md)
- [Workpad and resume](workpad-and-resume.md)
- [Cloud runs](../operations/cloud-runs.md)
