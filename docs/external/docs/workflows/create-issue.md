---
title: "Create an Issue"
description: "Turn a rough request into a GitHub issue you explicitly approved."
---

Use this workflow when you want work recorded rather than built now.

It creates one issue, and only after you approve the final draft. The result is an approved issue, or a draft that visibly names the decision nobody has made yet.

## Run It

<Steps>
  <Step title="Describe the work in your own words">
    ```text
    /prflow:create-issue Prevent duplicate release comments when a workflow retries
    ```

    A short feature idea, bug report or improvement is enough. Say who is affected, what outcome you want and anything that must not change, when you know them.
  </Step>
  <Step title="Answer the questions">
    PRFlow reads the repository and its documentation before drafting, then asks focused questions until scope, behavior, dependencies, verification and the important edge cases are decided. For a bug report it collects what triggered the defect, what happened, what you expected instead and the environment.

    If nobody can establish a fact, PRFlow records it as unestablished rather than guessing.
  </Step>
  <Step title="Review the rendered draft">
    PRFlow prints the complete title and body in chat, along with the supporting investigation as a separate, clearly labeled block.
  </Step>
  <Step title="Decide, then approve">
    You choose whether to spend an audit round on the draft, then approve that exact draft or ask for changes, then choose whether to assign the issue to yourself. PRFlow creates nothing until those decisions are explicit.
  </Step>
</Steps>

### What PRFlow Produces

The issue body follows a fixed structure:

| Section | Contents |
| --- | --- |
| `## Problem Statement` | Who is affected and what they cannot do today. |
| `## Current Behavior` | What the code does now. |
| `## Desired Behavior` | The intended outcome, stated as observable behavior. |
| `## User Impact` | Who gains, and who is unaffected. |
| `## Technical Context` | Known starting files, architecture fit, dependencies, data and cross-layer impact. |
| `## Acceptance Criteria` | A checklist of independently testable outcomes. |
| `## Implementation Notes` | Approach, relevant files and a testing strategy. |

`## Dependencies` and `## 🚫 Blocked — resolve before implementation` are added when they apply.

After creation you get the new issue's URL, and the `PRFlow` label is applied when repository permissions allow it.

<Note>
  The `## Technical Context` section opens with a scope note saying the listed files are starting points, not the full list. That is deliberate. The issue maps the work; it does not bound it.
</Note>

## The Second Comment Is Expected

PRFlow splits its output into two artifacts, and you will see both.

- **The issue body** is the implementer's brief. It holds only what a competent implementer cannot safely work out on their own: the problem, the desired behavior, non-obvious scope decisions, the acceptance criteria, real hazards and dependencies. It is the only channel an [implement](/docs/workflows/implement) run reads.
- **The investigation record** is posted as the first comment on the created issue. It holds the narrative that produced those decisions: supporting evidence, audit history, lower-severity hazards, rejected alternatives and anything the repository would rediscover during implementation anyway.

So a newly created issue normally has one comment on it already. That comment is PRFlow's, and nothing is missing from the body because of it.

<Tip>
  Set `create_issue.investigation_record_enabled` to `false` to stop that comment being posted. The default is `true`. The sorting between brief and record still happens on every draft — only publication is switched off, and the issue body is identical either way. PRFlow always shows you the investigation in chat, including when publication is disabled.
</Tip>

Splitting the two means an approver reviews the implementation contract rather than the whole investigation. It never drops a load-bearing detail to make the body shorter, and no length limit decides what stays.

## Approval Points

PRFlow does not create an issue as soon as it has enough context.

1. Review the complete title and body rendered in chat.
2. Choose whether to spend a fresh-context audit round on the draft. PRFlow offers one before it runs. Each round you accept re-verifies the draft against the repository and takes time, so you pay only for the rounds you choose. The default is none, and a satisfied reviewer declines.
3. Approve that exact draft, or request changes.
4. Choose whether to assign the new issue to yourself. Issues are created unassigned.
5. PRFlow creates the issue once both decisions are explicit.

<Warning>
  An earlier "just create it" does not count as approval of the final rendered draft. PRFlow asks again against the actual text it is about to post.
</Warning>

## Dependencies and Blockers

These are two different sections and they mean different things.

`## Dependencies` lists open prerequisite issues as `Blocked by #N`. The [implement workflow](/docs/workflows/implement) reads those declarations and stops while a prerequisite is still open, or when it cannot establish whether it is open.

`## 🚫 Blocked — resolve before implementation` lists unresolved product or implementation decisions. If you decline to settle a blocking decision, PRFlow records it here rather than inventing a default. Settle those before implementation starts.

An issue is implementation-ready when its Blocked section holds no unresolved decision.

## Write Criteria You Want Checked

Acceptance criteria must represent every independently testable outcome in Desired Behavior before PRFlow presents the draft. A quantitative criterion includes the command or counting rule that measures it.

This matters beyond the draft: the acceptance criteria are what an implement run verifies at the end. An issue with no criteria gets a run with nothing to check at that gate. See [Implement an Issue](/docs/workflows/implement).

## After Creation

PRFlow offers to start implementation only when the issue has no unresolved blocking decision and the repository checks needed for the handoff succeeded. The offer posts the trigger comment on the new issue; it never starts implementing in the same session.

You can also run [Implement](/docs/workflows/implement) later with the new issue number.

## Related Articles

- [Implement an Issue](/docs/workflows/implement)
- [The Lifecycle of a Change](/docs/concepts/lifecycle)
- [Command Reference](/docs/reference/command-reference)
