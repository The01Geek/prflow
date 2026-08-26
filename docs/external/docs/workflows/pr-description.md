---
title: "Pull Request Description"
description: "Write or refresh a structured pull request body from the current branch."
---

Use this workflow when a pull request body no longer matches the code it describes.

It updates an existing pull request body and never edits branch files. When no pull request exists yet, it prints the finished description instead of creating one.

## Run It

<Steps>
  <Step title="Start from the branch you want described">
    In Claude Code, with the branch checked out:

    ```text
    /prflow:pr-description 123
    ```

    The issue number is optional. When you supply one, PRFlow adds `Resolves #123` and reads that issue for context.

    On the cloud tier, comment on the pull request's Conversation tab with the bare command:

    ```text
    /prflow:pr-description
    ```

    This is one of the four commands a cloud install answers from a GitHub comment. A comment-triggered run describes the pull request it was posted on, so it takes no number.
  </Step>
  <Step title="Check the result">
    If the branch already has a pull request, its body is updated in place. If it does not, the full description is printed for you to paste when you open one.
  </Step>
</Steps>

### What Gets Written

The generated body uses a fixed set of sections:

| Section | Contents |
| --- | --- |
| `## Summary` | One to three bullets saying what changed and why. |
| `## Changes` | The changes grouped by area or concern, one line per area. |
| `## Resolves` | `Resolves #N`. Omitted when no issue number is known. |
| `## Test Plan` | Concrete verification steps as a checklist. |
| `## Post-Merge Verification` | Items that can only be checked after merge or deploy. Omitted when there are none. |
| `## Deferred Findings` | Review findings deliberately left for later. Omitted when there are none. |

`## Visual Changes` and `## Breaking Changes` are added when the diff calls for them.

## What PRFlow Reads

PRFlow compares the current branch against the base branch and reads the commit history, the diff summary and the detailed diff. When the branch came from an [implement](/docs/workflows/implement) run, it also carries that run's post-merge verification items into the body.

## Refreshing an Existing Body

Regenerated every run, from the current diff: Summary, Changes, Visual Changes, Breaking Changes, Post-Merge Verification and Deferred Findings.

Your own content survives:

- Test Plan items you added stay, as long as they still apply. Items for changes that no longer exist are removed.
- Existing issue links stay alongside a newly supplied issue number.
- Custom sections such as Reviewer Notes or Deploy Steps keep their position.
- Anything outside PRFlow's body markers stays outside them.
- A body with no markers at all is preserved above the newly generated section rather than replaced.

## Scope-Acknowledged Findings

A scope-acknowledged finding is a real review finding the team decided not to fix in this pull request. It appears in the `## Deferred Findings` section as a table: the severity, the file, a one-line summary and the follow-up issue that now owns it.

This is a disclosure, not a dismissal. It exists so a reviewer reading the pull request can see what was consciously left undone, and so a later [review](/docs/workflows/review) recognizes the finding instead of raising it again as new.

<Warning>
  A deferral holds only while its follow-up issue is open and linked to the finding in both directions. Close that issue, unlink it or delete the disclosure and the deferral stops applying — the next review raises the finding again and it blocks as it originally would have. A deferral parks a finding. It does not resolve it.
</Warning>

One kind of deferral has no follow-up issue: a finding settled by disclosure, where writing the caveat down *is* the deliverable. Those rows cite the document that carries the disclosure instead of an issue number, and a later review re-checks that the document still says it.

<Note>
  Because a settled-by-disclosure entry has no follow-up issue, the pull request body is its only durable record. PRFlow therefore never wipes an existing Deferred Findings block when it regenerates a body — it merges rather than overwrites.
</Note>

## When There Is No Pull Request

PRFlow does not create one. It outputs the complete description as plain text so you, or whatever opens the pull request, can supply it.

## Related Articles

- [Implement an Issue](/docs/workflows/implement)
- [Review](/docs/workflows/review)
- [Command Reference](/docs/reference/command-reference)
