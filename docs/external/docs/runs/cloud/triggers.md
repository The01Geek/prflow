---
title: "Cloud Triggers"
description: "Start a PRFlow cloud workflow with an authorized standalone GitHub comment."
---

Start an installed PRFlow cloud workflow by posting the right comment, in the right place, as an authorized person.

## The Four Comment Commands

A fresh installation answers four commands. Each one works on one surface only.

| **Command** | **Post It On** | **Who May Fire It** | **What It Does** |
| --- | --- | --- | --- |
| `/prflow:implement 123` | A comment on the issue itself. | An authorized collaborator or an allowed bot. | Creates a branch and opens a pull request for that issue. |
| `/prflow:review` | A comment on the pull request's **Conversation** tab. | An authorized collaborator or an allowed bot. | Reviews the pull request and reports a verdict. It changes no code. |
| `/prflow:review-and-fix` | A comment on the pull request's **Conversation** tab. | An authorized collaborator or an allowed bot. | Reviews the pull request, applies fixes and pushes them to its branch. |
| `/prflow:pr-description` | A comment on the pull request's **Conversation** tab. | An authorized collaborator or an allowed bot. | Writes or updates the pull-request description. |

### Implement an Issue

Add this as a comment on a regular issue:

```text
/prflow:implement 123
```

The number is optional when you post the command on the issue it targets. The workflow starts, acknowledges your comment with a 🚀 reaction, creates a workpad comment on the issue and keeps it updated as it works.

<Warning>
  `/prflow:implement` runs from an issue comment only. It does not run from a pull-request comment, an issue title, an issue description, a label or an `@claude` mention.
</Warning>

### Review, Fix or Describe a Pull Request

Add one of these as a comment on the pull request's **Conversation** tab:

```text
/prflow:review
```

```text
/prflow:review-and-fix
```

```text
/prflow:pr-description
```

`/prflow:review` and `/prflow:review-and-fix` post a single progress comment that PRFlow rewrites as it works, ending with the full report and an APPROVE or REJECT verdict. `/prflow:review-and-fix` also pushes its fixes to the pull-request branch. `/prflow:pr-description` updates the description in place and keeps content a person added.

<Warning>
  The shipped workflows listen to issue comments only. Text typed into GitHub's review-submission box, or into an inline comment on a diff, does not start a run. Post on the **Conversation** tab.
</Warning>

<Note>
  These three commands always act on the thread they were posted on. A trailing number is ignored, and a warning names both numbers in the run log. A repository collaborator must post the comment for an outside contributor's pull request.
</Note>

## Format the Comment Correctly

<Steps>
  <Step title="Put the Command on a Line of Its Own">
    Nothing else may share the line, apart from an optional issue or pull-request number.
  </Step>
  <Step title="Keep the Indentation Small">
    Up to three leading spaces are accepted. A tab, or four or more spaces, makes the line an indented code block and it is ignored.
  </Step>
  <Step title="Do Not Wrap It in Code or a Quote">
    A command inside a fenced code block, a blockquote or ordinary prose is ignored on purpose. That is what lets you write about a command without starting one.
  </Step>
</Steps>

An optional `#` before the number is accepted. If one comment contains several standalone commands, the first recognized command wins, and at most one cloud path starts from that comment.

Use the `/prflow:` spelling in new comments. The older `/devflow:` spelling is still accepted and normalized to the current form, but do not use it in new documentation or automation.

## Understand Authorization

A human requester must satisfy both checks:

- Their login matches `prflow.allowed_users`, which defaults to `*`.
- They have write, maintain or admin access to the repository.

A bot skips the collaborator check, but its login must appear in the comma-separated `prflow.allowed_bots` setting. The shipped default is `claude,dependabot`.

Authorization fails closed. If identity or permission cannot be established, no run starts.

An authorized command receives a best-effort 🚀 reaction. An unauthorized or unrecognized comment receives no reaction at all, so silence is the normal signal for both.

## Understand Reuse and Deduplication

<AccordionGroup>
  <Accordion title="Implementation Reuses One Workpad per Issue">
    Each issue has one dedicated workpad comment. A later run reuses that comment and records whether it resumed unfinished work or started from a terminal state. PRFlow's own workpad and progress comments carry hidden identifiers, so they can never start a new run themselves.
  </Accordion>
  <Accordion title="Overlapping Implementation Requests Are Deduplicated">
    The oldest visible active run proceeds. The duplicate posts a notice and starts no second agent job. The check fails open on a query error, so a rare duplicate is still possible.
  </Accordion>
  <Accordion title="Overlapping Review Requests Are Deduplicated per Commit">
    A second `/prflow:review` for the same pull-request head is suppressed while a fresh progress comment shows a review in flight. A request after the head changes proceeds for the new commit. That progress comment is the only in-flight signal, and it does not appear until the agent job begins, so a request in that short window is not deduplicated and a rare duplicate review is possible.
  </Accordion>
  <Accordion title="The Other Two Commands Are Not Deduplicated">
    Only `/prflow:review` is deduplicated. `/prflow:review-and-fix` and `/prflow:pr-description` are not, so overlapping requests each start a run. Wait for one to finish before you post another.
  </Accordion>
</AccordionGroup>

## What Is Not Included

Fresh installations do not review every pull request automatically. That workflow is withdrawn from this release. To get a review without anyone typing a comment, add the workflow on [Request a Review Automatically on Green CI](/docs/runs/cloud/auto-review).
