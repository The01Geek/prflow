---
title: "Command Reference"
description: "Look up every public PRFlow command, argument, supported client and result."
---

Find the canonical syntax and client availability for every public PRFlow command. A command is the text you enter. It invokes a PRFlow skill, whose documented behavior is called a workflow in these guides.

This reference lists the commands you invoke yourself. PRFlow also ships internal skills (such as the retrospective analysis stages that `retrospective-weekly` dispatches) that are marked not directly invocable; they are intentionally absent from this matrix.

## Client Syntax

Replace `<skill>` with the command name from the matrix.

| **Client or Surface** | **Syntax** |
| --- | --- |
| Claude Code | `/prflow:<skill> [arguments]` |
| GitHub Copilot CLI | `/prflow/<skill> [arguments]` |
| Codex CLI | `$prflow:<skill> [arguments]` |
| GitHub comment | `/prflow:<skill> [arguments]` |

All public commands support the three local clients above. GitHub-comment availability is limited to the rows marked Supported.

## Commands

| **Command and Arguments** | **Purpose** | **Supported Clients** | **Local / Cloud** | **Mutation Authority** | **Expected Result** |
| --- | --- | --- | --- | --- | --- |
| `init` | Scaffold or update PRFlow repository configuration and check prerequisites. | Claude Code, GitHub Copilot CLI, Codex CLI | Local only | Writes configuration and approved setup files. | Updated repository configuration with existing values preserved, plus any reported prerequisite gaps. |
| `create-issue <user story>` | Turn a rough request into an approved GitHub issue. | Claude Code, GitHub Copilot CLI, Codex CLI | Local only | Creates one issue after explicit draft approval. | An approved issue. It is implementation-ready only when its Blocked section has no unresolved decision. |
| `implement <issue number>` | Complete the four-phase issue-to-pull-request lifecycle. | Claude Code, GitHub Copilot CLI, Codex CLI, GitHub comment | Local: Yes. Cloud: Supported comment. | Creates or adopts a branch, commits, pushes and creates or updates a pull request. | A review-ready or draft pull request with recorded verification evidence, or a Blocked result naming the required human action. |
| `review [pull request number] [--issue N]` | Assess a pull request or the current branch. | Claude Code, GitHub Copilot CLI, Codex CLI, GitHub comment | Local: Yes. Cloud: Supported comment. | Does not edit the reviewed tree. Pull request mode can post comments and attempts a formal review. | Findings and a review verdict, with any incomplete checks or missing formal signal reported. |
| `review-and-fix [pull request number] [--push-each-iteration] [--issue N]` | Assess changes and commit authorized corrections. | Claude Code, GitHub Copilot CLI, Codex CLI | Local only | Commits corrections. Pushes only with `--push-each-iteration`. | Corrections followed by recorded verification, or a report naming unresolved findings. Run `review` separately to attempt a formal signal. |
| `receiving-code-review [pull request number or feedback]` | Verify received feedback and address findings that meet the direct-use correction threshold. | Claude Code, GitHub Copilot CLI, Codex CLI | Local only | Can update the active branch, edit files and run tests. It applies corrections only after verifying the subject and feedback. | Verified dispositions, authorized corrections and verification evidence, or a report naming degraded context or blockers. |
| `requesting-code-review` | Request an assessment of the current work from an independent reviewer. | Claude Code, GitHub Copilot CLI, Codex CLI | Local only | Dispatches an assessment-only reviewer. The reviewer does not edit the assessed tree. | Review findings and an assessment returned to the active session. |
| `pr-description [issue number]` | Generate or update the current branch's pull request body. | Claude Code, GitHub Copilot CLI, Codex CLI | Local only | Updates an existing pull request body. Makes no branch file edits. | A structured description or plain text when no pull request exists. |
| `docs` | Run the internal, external and release-note documentation sequence. | Claude Code, GitHub Copilot CLI, Codex CLI | Local only | Edits documentation files. Does not commit. | A branch-wide documentation pass and summary. |
| `docs-sync-internal` | Align developer docs with changed code. | Claude Code, GitHub Copilot CLI, Codex CLI | Local only | Edits internal documentation. | Internal docs that match the branch's behavior changes. |
| `docs-sync-external` | Align existing public docs with internal sources and shipped behavior. | Claude Code, GitHub Copilot CLI, Codex CLI | Local only | Edits customer-facing documentation. | Updated public guidance with internal-only detail removed. |
| `docs-bootstrap-internal` | Create or comprehensively reorganize developer docs. | Claude Code, GitHub Copilot CLI, Codex CLI | Local only | Creates and edits internal documentation. | A domain-based internal documentation set. |
| `docs-bootstrap-external` | Create or comprehensively rebuild public docs from internal docs. | Claude Code, GitHub Copilot CLI, Codex CLI | Local only | Creates, edits and can remove customer-facing documentation. | A structured public documentation set. |
| `docs-verify [--report-only] [--search-space <pathspec>] <topic>` | Verify one documentation topic against code. | Claude Code, GitHub Copilot CLI, Codex CLI | Local only | Default mode edits internal docs. `--report-only` makes no changes. | Corrected topic docs or a structured findings report. |
| `docs-release-notes` | Add an applicable release note and reconcile the changelog. | Claude Code, GitHub Copilot CLI, Codex CLI | Local only | Edits the configured release-note and applicable changelog files. | A customer-facing note for visible changes or an explicit skip. |
| `retrospective-weekly` | Analyze recent merged work and file bounded improvements for human triage. | Claude Code, GitHub Copilot CLI, Codex CLI | Local only | Changes the local checkout, updates learning records, opens or updates a state pull request and files selected issues. | A retrospective report, state pull request, filed issues and explicit blockers. |

## GitHub Comment Boundary

Fresh installations ship comment automation for `implement` and manual `review`. A repository collaborator must issue the command on the relevant issue or pull request. Automatic pull-request-triggered review is not included in fresh installations.

PRFlow prepares review-ready work. No command merges a pull request.

## Related Articles

- [Workflows](/docs/workflows/index)
- [Cloud Triggers](/docs/runs/cloud/triggers)
- [Glossary](/docs/reference/glossary)
