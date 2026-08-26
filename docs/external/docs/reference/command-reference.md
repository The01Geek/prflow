---
title: "Command Reference"
description: "Look up every PRFlow command, its arguments, where it runs, what it can change and what it returns."
---

Find the exact syntax for every PRFlow command you can invoke yourself.

A command is the text you enter. It runs a PRFlow skill, whose behavior these guides call a workflow.

## Syntax

Every PRFlow command uses the `prflow` namespace:

```text
/prflow:<command> [arguments]
```

For example, to implement issue 123 and then ask for an independent review of the resulting pull request 456:

```text
/prflow:implement 123
/prflow:review 456
```

<Warning>
  Always include the `prflow` namespace. Names such as `review` and `init` collide with commands built into coding clients, and a bare name can run something else entirely.
</Warning>

The same `/prflow:` spelling works in a GitHub comment for the commands marked below. Comments also still accept the older `/devflow:` spelling, which is normalized to the current one. Use `/prflow:` in anything you write today.

PRFlow also ships internal skills that it dispatches on its own, such as the stages behind the weekly retrospective. They are not invocable and are deliberately absent from this table.

## Commands

| Command and Arguments | Purpose | Where It Runs | What It Can Change | Expected Result |
| --- | --- | --- | --- | --- |
| `init` | Scaffold or refresh repository configuration and check prerequisites. | Local | Writes configuration and approved setup files. | Updated configuration with your existing values preserved, plus any prerequisite gaps it found. |
| `create-issue <user story>` | Turn a rough request into an approved GitHub issue. | Local | Creates one issue, only after you approve the draft. | An approved issue. It is ready to implement when its Blocked section holds no unresolved decision. |
| `implement <issue number>` | Carry an issue through to a pull request. | Local, and a comment on an **issue** | Creates or adopts a branch, commits, pushes and creates or updates a pull request. | A review-ready or draft pull request with recorded verification evidence, or a Blocked result naming what a person must do. |
| `review [pull request number] [--issue N]` | Assess a pull request or the current branch. | Local, and a comment on a **pull request** | Nothing in the reviewed tree. In pull-request mode it can post comments and a formal review. | Findings and a verdict, with any incomplete check reported. |
| `review-and-fix [pull request number] [--push-each-iteration] [--issue N]` | Assess changes and commit authorized corrections. | Local, and a comment on a **pull request** | Commits corrections. A local run pushes only with `--push-each-iteration`; a comment-triggered run pushes to the pull request branch. | Corrections followed by recorded verification, or a report naming unresolved findings. |
| `pr-description [issue number]` | Generate or refresh the current branch's pull request body. | Local, and a comment on a **pull request** | Updates an existing pull request body. Makes no file edits. | A structured description, or plain text when no pull request exists. |
| `receiving-code-review [pull request number or feedback]` | Verify review feedback you received and address what meets the correction threshold. | Local | Can edit files on the active branch and run tests, after verifying the feedback. | Verified dispositions, authorized corrections and verification evidence, or a report naming blockers. |
| `requesting-code-review` | Ask an independent reviewer to assess the current work. | Local | Nothing. The reviewer does not edit the tree. | Review findings returned to your session. |
| `docs` | Run the internal, external and release-note documentation sequence. | Local | Edits documentation files. Does not commit. | A branch-wide documentation pass and a summary. |
| `docs-sync-internal` | Bring developer docs in line with changed code. | Local | Edits internal documentation. | Internal docs matching the branch's behavior changes. |
| `docs-sync-external` | Bring public docs in line with internal sources and shipped behavior. | Local | Edits customer-facing documentation. | Updated public guidance with internal-only detail removed. |
| `docs-bootstrap-internal` | Create or comprehensively reorganize developer docs. | Local | Creates and edits internal documentation. | A structured internal documentation set. |
| `docs-bootstrap-external` | Create or comprehensively rebuild public docs from internal docs. | Local | Creates, edits and can remove customer-facing documentation. | A structured public documentation set. |
| `docs-verify [--report-only] [--search-space <pathspec>] <topic>` | Check one documentation topic against the code. | Local | Corrects internal docs by default. `--report-only` changes nothing. | Corrected topic docs, or a findings report. |
| `docs-release-notes` | Add a release note where one applies and reconcile the changelog. | Local | Edits the configured release-note and changelog files. | A customer-facing note, or an explicit decision to skip. |
| `retrospective-weekly` | Analyze recently merged work and file bounded improvements for human triage. | Local | Updates learning records, opens or updates a state pull request and files selected issues. | A report, a state pull request, filed issues and any blockers. |

## What Runs From a GitHub Comment

A fresh cloud installation answers four commands posted as a comment by an authorized person:

- `/prflow:implement <issue number>` — on a comment on an **issue**, not on a pull request.
- `/prflow:review` — on a comment on a **pull request's Conversation tab**.
- `/prflow:review-and-fix` — same surface.
- `/prflow:pr-description` — same surface.

Every one of them requires a repository collaborator with write, maintain or admin access who also matches the allowed-users setting, or a listed bot identity. Someone commenting from a fork cannot start a privileged run.

Automatic review triggered by pull-request events is not included in a fresh installation. To get review without typing a command, see [Request a Review Automatically on Green CI](/docs/runs/cloud/auto-review).

<Note>
  No command merges a pull request. PRFlow prepares review-ready work and stops there.
</Note>

## Related Articles

- [Workflows](/docs/workflows/index) — which command to reach for
- [Cloud Triggers](/docs/runs/cloud/triggers) — the comment surface in detail
- [Glossary](/docs/reference/glossary) — the terms these commands use
