---
title: "Create an Issue"
description: "Turn a rough request into an explicitly approved GitHub issue."
---

Use this workflow when you want to record work in GitHub instead of implementing it now. It creates one issue only after you approve the final draft. The result is an approved issue or a visible unresolved blocker.

```text
/prflow:create-issue Prevent duplicate release comments when a workflow retries
```

The example uses Claude Code syntax. Use `/prflow/create-issue` in GitHub Copilot CLI or `$prflow:create-issue` in Codex CLI.

## What to Provide

A short feature idea, bug report or improvement is enough. Include the affected user, the desired outcome and any constraint that must not change when you know them.

PRFlow inspects the repository and existing documentation before it drafts. It asks focused questions until scope, behavior, dependencies, verification and important edge cases are decided. When it reads your request as a bug report, it captures the facts needed to reproduce the defect — what triggered it, what happened, what you expected instead, and the environment — and records any fact nobody can establish as unestablished rather than guessing. If you explicitly decline to resolve a blocking decision, the draft records it in a visible Blocked section instead of inventing a default.

## Approval Points

PRFlow does not create an issue as soon as it has enough context.

1. Review the complete title and body that PRFlow renders in chat.
2. Choose whether to spend a fresh-context audit round on the draft. PRFlow offers one before it runs; a satisfied reviewer declines and the issue is filed unaudited. Each round you accept re-verifies the draft against the repository and takes time, so you pay only for the rounds you choose — the default is none.
3. Approve that exact draft or request changes.
4. Choose whether to assign the new issue to yourself.
5. Let PRFlow create the issue after both decisions are explicit.

An earlier instruction such as "just create it" does not replace approval of the final rendered draft. The `PRFlow` label is applied after creation when repository permissions allow it.

## Dependencies and Blockers

Open prerequisite issues appear in a `Dependencies` section as `Blocked by #N`. The [implementation workflow](/docs/workflows/implement) reads these declarations and stops while a prerequisite remains open or cannot be resolved.

The Blocked section serves a different purpose. It contains unresolved product or implementation decisions. Resolve those decisions before starting implementation.

## Expected Result

The issue contains a problem statement, current and desired behavior, user impact, technical context, acceptance criteria, implementation notes and a testing strategy. Desired behavior states the intended outcome. Acceptance criteria must represent every independently testable outcome in that section before PRFlow presents the draft for approval. Quantitative criteria include the command or counting rule that measures them.

The body is a minimum-sufficient implementation brief: it carries the decisions an implementer cannot safely derive on their own, and it keeps material only when removing it could change what gets built. The investigation that produced those decisions — supporting evidence, audit history and other detail the repository would rediscover during implementation — is recorded separately rather than mixed into the body, so an approver reviews the implementation contract instead of the whole investigation. This never drops a load-bearing detail to make the body shorter, and no length or size limit decides what stays.

The result is an approved issue. It is implementation-ready only when no unresolved decision remains in its Blocked section.

PRFlow offers implementation only when the issue has no unresolved blocking decision and the repository checks needed for the handoff succeeded. You can also run the [Implement workflow](/docs/workflows/implement) later with the new issue number.

## Related Articles

- [Implement an Issue](/docs/workflows/implement)
- [Command Reference](/docs/reference/command-reference)
