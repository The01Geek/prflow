---
title: "Review"
description: "Assess a pull request or branch and get a verdict, without changing the reviewed code."
---

Use this workflow when you want findings and a verdict, and no edits.

It never changes the reviewed tree. The result is a report with a verdict, or a report naming the checks it could not complete.

## Run It

<Steps>
  <Step title="Start the review">
    In Claude Code, review a pull request by number:

    ```text
    /prflow:review 123
    ```

    Omit the number to review the current branch against the configured base branch. Add `--issue N` to check the change against a specific issue's acceptance criteria.

    On the cloud tier, comment on the pull request's Conversation tab with the bare command:

    ```text
    /prflow:review
    ```

    A comment-triggered run always reviews the thread it was posted on, so it takes no number. A number typed after the command is ignored.
  </Step>
  <Step title="Wait for the phases to finish">
    The engine classifies the diff, builds a verification checklist specific to that change, verifies each item, dispatches its review agents and aggregates the results into one verdict.
  </Step>
  <Step title="Read the report">
    A current-branch run returns the report in chat. A pull request run also posts a formal GitHub review, and maintains a progress comment on the pull request while it works.
  </Step>
</Steps>

### What You Get Back

The report is one Markdown document with a fixed set of sections, in this order:

- **`## Verdict:`** — one of the five verdicts below, followed by a short summary in parentheses. This is the first line, so it is what a reader sees first.
- **`## Issue Compliance`** — which issue the change was checked against, where the acceptance criteria came from, and whether this run narrowed the scope. When no issue was found, it says compliance was not checked rather than implying it passed.
- **`## Verification Checklist Results`** — a single tally line in the form "*N* passed, *N* failed, *N* inconclusive", then one line per failing or inconclusive item, each quoting the claim and the file and line it came from. Passing items are collapsed behind an expandable block.
- **`## Code Review Findings`** — findings grouped under `### 🔴 Critical`, `### 🟠 Important / Major`, `### 🟡 Suggestion / Minor` and `### ℹ️ Informational — Deferred`. Empty groups are omitted. Each finding says how many of the dispatched agents raised it, so you can tell a corroborated finding from a single-source one.
- **`## Verdict Criteria`** — the rules that produced the verdict, so the decision is auditable rather than asserted.

Failing and inconclusive items are never collapsed. Everything that blocks is visible without expanding anything.

## What Gets Reviewed

In pull request mode, PRFlow reviews the pushed pull request head against the pull request's base. Uncommitted local changes are not included.

In current-branch mode, it reviews committed changes between `HEAD` and the configured base branch. Commit what you want assessed before you start.

Four review agents always run: a general code reviewer, a silent-failure hunter, a comment-accuracy analyzer and a final-pass independent reviewer. Two more run only when the diff calls for them — a type-design analyzer when the change adds new types, and a test analyzer when the change touches test files or adds new testable logic. See [Review Agents](/docs/configuration/review-agents).

## The Verdicts

The engine emits one of five verdicts.

| Verdict | Meaning |
| --- | --- |
| APPROVE | No findings, and every checklist item passed. |
| APPROVE with notes | Findings exist, but all of them are below the configured severity threshold. |
| APPROVE WITH ADVISORY NOTES | Approved, with findings deliberately parked for a human to judge. |
| APPROVE WITH CAVEAT | Approved, but verification coverage was incomplete — for example, the verification checklist could not be generated. |
| REJECT | At least one blocking problem. On a pull request this posts a request for changes. |

<Note>
  An APPROVE from PRFlow is a machine verdict on one diff. It is not a human approval and it does not merge anything. Treat it as evidence for your reviewers, not as a substitute for them.
</Note>

## What Causes a REJECT

Three things drive a REJECT.

1. **A failed verification-checklist item.** A claim the change depends on was checked and found untrue.
2. **An inconclusive verification-checklist item.** The claim could not be established either way, so it needs a manual check. Unknown is not treated as fine.
3. **A finding at or above the configured severity threshold.** The default threshold is `critical`, so by default only Critical findings block. Set `prflow_review.verdict_severity_threshold` to `important` or `suggestion` to make the line stricter. Findings below the line stay visible as notes.

### The Rule That Surprises People

<Warning>
  If the change's own diff added or modified a documentation line, a code comment or a test that is **untrue**, that alone causes a REJECT — at every threshold setting, and whatever severity the finding was graded. Severity settings cannot lower it, deferring it does not clear it, and one agent raising it is enough. Only correcting the untrue claim, or the code it describes, clears the REJECT.
</Warning>

"Untrue" means the claim is stale, contradicts the code as it now stands, or contradicts another part of the same change. The rule covers the change's own additions and edits, not prose that was already there.

The narrow exception is wording that cannot affect behavior in either direction — a purely cosmetic phrasing problem in a message or a comment with no wrong output, no corrupted state and no skipped guard. That is capped as a Suggestion and does not block at the default threshold. A false claim is never treated as a wording problem.

<Accordion title="Why this rule exists">
  A change that ships a comment or a doc line describing behavior it does not have is worse than one that ships no comment at all: the next reader trusts it. The same applies to a test whose assertion does not match what the change claims to guarantee.

  Because the cost lands on a future reader rather than on today's run, a severity grade would let it be tuned away. So the rule sits outside severity entirely.
</Accordion>

## What Review Never Touches

Review does not edit, commit, check out or push the reviewed tree. It writes temporary scratch data, and in pull request mode it maintains a progress comment and posts the final GitHub review.

If the formal review cannot be posted, PRFlow records the report through whatever channel remains available and tells you the merge signal is missing. It never merges the pull request.

Use [Review and Fix](/docs/workflows/review-and-fix) when you want the findings corrected as well as reported.

## Related Articles

- [Review and Fix](/docs/workflows/review-and-fix)
- [How the Review System Works](/docs/concepts/review-system)
- [Review Agents](/docs/configuration/review-agents)
- [Review Settings](/docs/configuration/review)
