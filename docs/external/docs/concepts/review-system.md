---
title: "The Review System"
description: "Understand which reviewers PRFlow runs, what verdict it reports and what drives a rejection."
---

PRFlow combines mechanical evidence with independent review passes to find defects before it hands the change to you. That raises confidence. It does not prove the change is correct.

![The prflow:review skill moves through setup and classification, a verification checklist, specialized reviewers and a verdict. The prflow:review-and-fix skill uses the same engine, applies justified corrections, verifies them and reviews the result again. A shadow pass checks an approval-side result before the loop exits.](/images/review-system-loop.svg)

## Four Review Phases

<Steps>
  <Step title="Setup and Classification">
    The engine identifies the diff under review, its base, the related issue's acceptance criteria and the risk profile of the changed files.
  </Step>

  <Step title="Verification Checklist">
    PRFlow builds a checklist of the claims this specific change makes: dependency interactions, test and mock alignment, data-format assumptions, API contracts and absolute claims. It removes overlapping checks. Simple presence or absence claims are resolved directly. Deeper claims go to a reviewer for evidence-based evaluation.

    Each item comes back as pass, fail or inconclusive. A failed item and an inconclusive item both prevent a clean approval.
  </Step>

  <Step title="Specialized Reviewers">
    PRFlow dispatches reviewers with different focus areas, in separate contexts, so they do not inherit each other's conclusions. Four always run and two run only when the change warrants them.

    Findings identify a file, a line and a defect type where possible. PRFlow uses that signature to count independent corroboration: when several reviewers report the same defect, confidence in the finding rises. A finding from a single reviewer stays visible for closer human scrutiny.
  </Step>

  <Step title="Verdict">
    PRFlow combines the checklist results, the findings, which reviewers completed and the configured severity threshold into one verdict. It reports incomplete checklist items and any reviewer that did not complete.
  </Step>
</Steps>

## Which Reviewers Run

Four reviewers run on every review:

| Reviewer | What it looks for |
| --- | --- |
| Code reviewer | Correctness problems, plus adherence to the project's own guidelines, conventions and patterns |
| Silent-failure hunter | Swallowed errors, over-broad exception handling and fallbacks that mask a failure or fail open |
| Comment analyzer | Comments and docstrings that do not accurately describe the code they sit beside |
| Final-pass reviewer | A fresh independent read of the completed work against what it was supposed to do |

Two more run only when the diff warrants them:

| Reviewer | When it runs |
| --- | --- |
| Type-design analyzer | The change adds new types |
| Test analyzer | The change touches test files, or adds new logic that can be tested |

<Note>
  A reviewer that does not run is not a reviewer that found nothing. When two or more reviewers fail to return results, PRFlow adds a partial review coverage note to the verdict so you can see the gap.
</Note>

## The Verdict Vocabulary

Every review reports one of five verdicts.

| Verdict | What it means |
| --- | --- |
| `APPROVE` | No findings and no failed or inconclusive checklist item. |
| `APPROVE with notes` | Findings exist, but all of them are below the configured severity threshold. |
| `APPROVE WITH CAVEAT` | Approved, but part of the review could not be completed. It is never a clean approval. |
| `APPROVE WITH ADVISORY NOTES` | The fix loop approved and parked findings it deliberately did not fix, for a person to read. |
| `REJECT` | Something blocking was found. |

<Warning>
  An approval-family verdict is evidence for your review. It is not proof of correctness and it is not authorization to merge.
</Warning>

## What Drives a Rejection

Any one of these produces a `REJECT`:

- A verification-checklist item that **failed**.
- A verification-checklist item that was **inconclusive**. An unknown result is treated as blocking, not as a pass.
- A finding at or above the configured severity threshold. The default is `critical`, so only critical findings reject. Set `prflow_review.verdict_severity_threshold` to `important` or `suggestion` to make more findings reject. See [Review Settings](/docs/configuration/review).

### The Rule That Surprises People

There is one more rejection rule, and it does not read the severity threshold at all.

<Warning>
  If the change's **own diff** added or modified a documentation line, a code comment or a test that is untrue, that alone produces a `REJECT`. It rejects at every threshold setting, including the default. It cannot be lowered by severity configuration and it cannot be waived by deferring the finding. Only fixing the untrue line clears it.
</Warning>

"Untrue" here means the added or modified line contradicts the code as it now stands, is already stale or contradicts another part of the same change. PRFlow treats this as a correctness principle rather than a severity grade: a change that documents itself incorrectly is wrong regardless of how minor the wording looks.

<Accordion title="Why this rule is absolute">
  A wrong comment or a wrong documentation line survives the pull request and misleads every reader afterwards, including the next automated run. A severity threshold exists so a team can decide how much polish blocks a merge. It is not meant to let a change ship a statement about itself that is false. Rating that as a suggestion, and then letting the default threshold ignore it, is exactly how such lines used to reach the default branch.
</Accordion>

## Review and Fix

`/prflow:review-and-fix` runs the same engine inside a correction loop. It evaluates each finding, applies the corrections it can justify, verifies each correction and reviews the result again. The configured default cap is five fix iterations.

Before an approval-side result stands, a shadow pass reviews the diff again without seeing the primary reviewers' conclusions. It can send a missed finding back into another iteration. It also reports which planned reviewers completed and any coverage gap it knows about.

<Note>
  A report with no gaps means only that PRFlow recorded no known gap. It does not mean every defect was found.
</Note>

The inline review-and-fix loop reports its result in your session. Run the standalone [review workflow](/docs/workflows/review) when you want a formal pull-request review verdict recorded on GitHub.

## What Independent Review Means

Separate prompts and separate reviewer contexts reduce shared blind spots. Corroboration across several reviewers, and a fresh shadow pass, can expose an approval that nothing actually supports.

They narrow the risk. They do not remove it. Reviewers can share the same model limitations, a test can encode the same mistaken assumption as the implementation it covers and production conditions can differ from the repository environment.

Use the review output as structured evidence for your own review.

## Related Documentation

- [Review Workflow](/docs/workflows/review)
- [Review and Fix Workflow](/docs/workflows/review-and-fix)
- [Review Settings](/docs/configuration/review)
- [Review Agent Settings](/docs/configuration/review-agents)
- [How PRFlow Verifies a Change](/docs/concepts/verification)
- [Human Control](/docs/concepts/human-control)
