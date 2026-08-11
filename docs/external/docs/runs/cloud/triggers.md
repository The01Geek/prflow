---
title: "Cloud Triggers"
description: "Use authorized standalone GitHub comments to start supported PRFlow workflows."
---

Start an installed PRFlow cloud workflow from GitHub with an authorized comment or supported event.

## Implement an Issue

Add a comment to a regular issue:

```text
/prflow:implement 123
```

The number is optional when the command is posted on the issue it targets. The implementation workflow does not run from a pull-request comment, issue title, issue description, label or `@claude` mention.

## Review a Pull Request

Add a comment on the pull request's **Conversation** tab:

```text
/prflow:review
```

The shipped workflow listens to issue comments. Text entered in the review-submission box or an inline review comment does not trigger it. A repository collaborator must request review for an outside contributor's pull request.

Fresh installs do not automatically review every pull request. The automatic review workflow is withdrawn from this release.

## Format Commands Correctly

A command must be the only content on its line. Up to three leading spaces and an optional `#` before the number are accepted. Commands in prose, blockquotes, indented code or fenced code blocks are ignored.

If one comment contains several standalone commands, the first recognized command wins. At most one cloud path dispatches from that comment.

Use the `/prflow:` spelling in new comments. The transitional `/devflow:` spelling is still accepted and normalized, but it should not be used in new documentation or automation.

## Understand Authorization

Human requesters must satisfy both checks:

- Their login matches `prflow.allowed_users`, which defaults to `*`.
- They have write, maintain or admin access to the repository.

Bots do not use the collaborator check. Their login must appear in the comma-separated `prflow.allowed_bots` setting. Authorization fails closed when identity or permission cannot be established.

An authorized command receives a best-effort 🚀 reaction as early acknowledgement. Unauthorized or unrecognized commands receive no reaction.

## Understand Reuse and Dedupe

Implementation uses one dedicated workpad comment per issue. A later run reuses that comment and records whether it resumed unfinished work or started from a terminal state. PRFlow's own workpad and review-progress comments carry hidden identifiers that prevent them from triggering new runs.

Overlapping implementation requests on the same thread are deduplicated. The oldest visible active run proceeds. The duplicate posts a notice and does not start another agent job. The check fails open on a query error, so a rare duplicate is possible.

Overlapping `/prflow:review` requests for the same pull-request commit are also deduplicated while a fresh live progress comment shows a review in flight. A new request after the pull-request head changes proceeds for the new commit. That progress comment is the only in-flight signal, and an in-flight review does not publish it until its agent job begins, so a request arriving in the short window before it appears is not deduplicated and a rare duplicate review is possible.
