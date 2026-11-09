---
title: "Review and Fix"
description: "Review a pull request or branch, correct what the review finds and record the verification."
---

Use this workflow when you want the problems found and corrected in one pass.

It runs the same review engine as [Review](/docs/workflows/review), then fixes what it finds and commits as it goes. The result is a converged branch with recorded verification, or a report naming the findings it could not resolve.

## Run It

<Steps>
  <Step title="Start the loop">
    In Claude Code, on a pull request:

    ```text
    /prflow:review-and-fix 123
    ```

    Omit the number to work on the current branch. The full argument list is `[pull request number] [--push-each-iteration] [--issue N]`, and you can pass any, all or none of them.

    On the cloud tier, comment on the pull request's Conversation tab with the bare command:

    ```text
    /prflow:review-and-fix
    ```

    This is one of the four commands a cloud install answers from a GitHub comment. A comment-triggered run acts on the thread it was posted on, so it takes no number.
  </Step>
  <Step title="Let it iterate">
    Each iteration runs the full review engine, verifies each finding before acting on it, fixes the ones that qualify, commits and reviews the new commit. The default cap is five iterations.
  </Step>
  <Step title="Read the loop result">
    The loop ends with a verdict, the list of reviewers that completed and any known coverage gaps, all in chat.
  </Step>
</Steps>

### What You Get Back

The final chat report opens with a one-line result. On an approval-side outcome it names how many iterations ran and whether the shadow pass agreed, in the shape "Review passed after *N* iteration(s) (*shadow status*)". On an approval with parked findings it also states how many advisory findings were left for human review. A REJECT says so and the findings stay in the report below it.

Underneath the headline is the same report structure as a standalone review: the verdict, the findings and checklist items grouped by severity, issue compliance, and the verification-checklist tally in Run details. Each finding also carries what the loop decided about it — applied, pushed back, deferred, advisory or severity-calibrated. A finding the review itself moved to `Informational — Deferred`, such as one a confirmed stricter-than-criterion fix accounts for, is not sent to the fixer when the loop can match that report line to the finding; an unmatched line is noted and the finding keeps its original severity.

The commits it made are on your branch, one per fix iteration.

<Note>
  This workflow does not post a formal GitHub review. Its verdict goes to chat. To get a merge signal on the pull request, run [Review](/docs/workflows/review) afterward — a separate, independent pass over the fixed head.
</Note>

## Edit Authority

This workflow applies fixes directly in the session that runs it, and commits as it converges.

In pull request mode it checks out the pull request head and confirms both the branch name and the head commit before it reviews or edits anything. A working tree too dirty to check out stops the run. In current-branch mode the commits land on the branch you already have checked out.

Use [Review](/docs/workflows/review) when you do not want your branch changed.

## Iterations and What Gets Fixed

The default iteration cap is five. Change it with `prflow_review_and_fix.max_iterations`. The loop also exits early when it converges, except after an iteration that ends in REJECT and fixed a REJECT driver, or that fixed anything when its REJECT drivers or fix records cannot be confirmed: it then runs one more iteration to review the fixes, up to the cap.

Which findings reach the fixer is set by `prflow_review_and_fix.fix_severity_threshold`, which defaults to `important`:

| Threshold | Fixed | Left advisory |
| --- | --- | --- |
| `critical` | Critical only | Important, Major, Suggestion, Minor |
| `important` (default) | Critical, Important, Major | Suggestion, Minor |
| `suggestion` | Everything | Nothing |

Any finding or failed checklist item that drives a REJECT is always fixable, whatever this threshold says. That is deliberate: it means no combination of settings can produce a blocking finding the fixer is configured to ignore. A finding exempt from REJECT because a decided acceptance criterion decides it also stays eligible for the fixer whatever this threshold says. Suggestion and Minor findings that the check on each iteration's own fixes raises can also reach the fixer in that iteration, whatever this threshold says. An inconclusive checklist item never drives a REJECT and gives the fixer nothing to fix, so it is never sent; the report lists it under Informational — Deferred.

PRFlow can push back on a finding when the code disproves it, rather than "fixing" something that was never wrong. On a numbered pull request in a run with `--push-each-iteration`, it records that pushback as a [rejected-finding line](/docs/workflows/review#rejected-finding-lines) in the description, so later iterations and reviews treat the finding as settled; otherwise, or when that write fails, the line goes in the run's report. For a failed checklist item, it reads the cited code and the requirement the item rests on, and fixes only a defect that reading shows. It pushes back an item whose evidence is accurate but whose requirement the code does not have to meet, an item that misreads the code, and an item the reading cannot settle, naming what it could not establish. A Suggestion or Minor finding that reaches the fixer is fixed unless the fixer records one of a fixed set of decline reasons, for example code shown to be already correct, a fix that needs a design decision the issue, its criteria and the code leave open, or a project instruction that forbids it; "only polish" or "low priority" is not a reason. When a later iteration edits a file, the fixer re-checks the findings earlier iterations declined on that file without a standard category, except one declined only because it was not sent to the fixer, and fixes any defect still present unless its recorded reason is one of those valid decline reasons and still holds. After fixing a finding, the fixer looks for the same defect at related sites, including outside the pull request's changes, and fixes those in the same iteration. When it deliberately leaves such a defect unfixed for a reason other than an acceptance-criterion conflict or another issue or pull request already tracking it, it names the site, the defect and why it left it: under `/prflow:implement` in a reflection on the issue's workpad, otherwise in the run's report. Under `/prflow:implement` that reflection is the only record. A workpad write whose update request fails is saved locally, and a later successful workpad update from that checkout can add it as the same kind of reflection; a write that saves nothing, for example one that fails before its request is sent, or one no later update adds, leaves none. Each such site is reported when first left, and the report stands even if a later iteration fixes it. It can also defer a genuine finding when the deferral rules apply. A decision you recorded never makes a finding wrong. When the fixer finds that a valid Critical or Important finding can be fixed only in ways that contradict your latest recorded answer, the run stops in that iteration instead and names the finding, its evidence and your decision. End the stop by changing the decision so a fix is allowed or, for an Important finding, by adding an acceptance criterion that every fix would contradict, and run again. If one allowed fix keeps every recorded decision, or it is unclear whether a fix contradicts one, the fixer makes the fix. A test broken by one of its own fixes is repaired before the loop continues, or, when no permitted repair exists, reported failing, and a check still failing at the end makes the run's verdict REJECT for manual review.

Fixes remove or reuse before they add, and at every severity a fix a project instruction forbids is not made, here and in `/prflow:fix`. A fix that would delete or rewrite text and so bring back a finding about that file that an earlier iteration fixed is reworked so both stay fixed; when that is impossible, the later fix is not made and its finding is pushed back. The exception is removing text a project instruction forbids: that removal is made anyway, unless an acceptance criterion bars it, and the finding it brings back is recorded as pushed back. Before committing a fix, the fixer compares it with each of the linked issue's acceptance criteria that decides, or may decide, something the edited code or text handles: for the finding's own case and each case the criterion names or excludes, it compares the outcome the fix gives with the outcome the criterion requires. A finding's argument, suggested scope or suggested remedy does not count as evidence that the fix meets a criterion. The loop's record of an applied fix names each criterion, case and pair of outcomes compared, so you can see what was checked. A standalone `/prflow:fix` run makes the same comparison and records it in its report. A fix that would weaken or contradict one of the linked issue's acceptance criteria is pushed back, but only when the fixer can name what in that criterion the fix would weaken or contradict; otherwise the criterion is no reason to decline it; one stricter than a criterion is applied and, when the run has a pull request, disclosed in its description. When the check of an iteration's fixes finds a problem in a fix made for another finding, the fixer can answer that finding without adding code or text or, in some cases, withdraw an optional fix, a stricter one included, instead of growing it.

When a finding says a written instruction, for example a rule in a skill or prompt file, misses or wrongly decides a case, the fixer restates the rule as one general clause instead of adding that case; the clause says what happens to cases it does not name and what limit it accepts. The fixer pushes back on a finding whose case the clause already decides correctly; a finding about a case the stated limit accepts is weighed as usual and answered by restating the clause, its default outcome or the limit. A list whose members can all be named, for example a fixed set of values, still gets the missing member. `/prflow:fix` follows the same rule.

## Push Behavior

Where the fix commits end up depends on how you started the run.

**Locally**, they stay on your branch and are not pushed. Add `--push-each-iteration` to push each completed iteration and the final loop state to the feature branch, which keeps the remote branch and its continuous integration runs current.

**From a pull request comment**, the run pushes its fix commits to the pull request branch, so the fixes are on the pull request when the run finishes. You do not pass the flag, and could not — the workflow builds the command from the command word and the thread number alone, so any extra argument in a comment is ignored.

<Note>
  Pushing never posts a verdict. It only moves commits. To get a merge signal, run [Review](/docs/workflows/review) afterward.
</Note>

## Shadow Review

Before it concludes on the approval side, PRFlow runs a shadow review with prior findings withheld from its prompts. A separate write directory reduces accidental discovery without isolating reads. The shadow reports reviewer coverage gaps; if its engine runs inline in the informed loop context, agreement is not verified even with a complete reviewer roster.

One case skips it. When the loop runs inside `/prflow:implement` and its first iteration is clean — among other conditions, no check failed or left inconclusive at Important or above, apart from acceptance-criterion checks left inconclusive, and no finding that stands at Important or above — the loop ends without a re-review or a shadow pass, and the result line reads `shadow skipped, iteration 1 clean`. The pull-request review is the independent pass for that run. A standalone `/prflow:review-and-fix` run is unchanged.

<Note>
  Shadow agreement narrows the chance of a false clean result. It does not close it. A run reporting no gap has not proved that the review found every defect, and it is not a substitute for a human review or a formal merge signal.
</Note>

When the shadow pass cannot confirm its own coverage, the report says agreement was not verified rather than claiming agreement.

A shadow pass that adds only findings below Important, for example a new Suggestion, can still count as agreement. When it does, those findings are listed in the report's `## Coverage` section, each with its id, severity and summary, and are not fixed, even when `fix_severity_threshold` is `suggestion`. When the coverage line says the shadow ran with full reviewer coverage, it also counts the shadow's new findings by Critical, Important and below Important from the findings the loop recorded, or says they were not recorded. For a run that ends in an approval other than the one described below, the report says agreement was not verified in cases including a missing record of those findings or of the shadow's verdict, a REJECT shadow verdict, and a new finding that stands at Important or above.

### When the Shadow Pass Finds Something Too Late

The shadow pass can surface a new finding after the loop has already used its iterations. Rather than quietly approving or silently dropping it, the run reports a distinct result:

```text
Review converged after 5 iteration(s) but a final shadow pass surfaced 2 new
Important finding(s) that the loop could not address within the iteration cap.
See report.
```

Read this as an approval with known, unaddressed findings, listed in the report below the headline. Treat those findings as work still to do. Raise `prflow_review_and_fix.max_iterations` and run the loop again, or fix them yourself, before you merge.

## Getting a Merge Signal Afterward

Once the loop converges, run an independent assessment:

```text
/prflow:review 123
```

That run reviews the resulting pull request head from scratch and attempts to post the formal GitHub review. If GitHub refuses the post, PRFlow posts the verdict as a pull request comment instead when it can and reports that the merge signal is missing. Neither workflow merges the pull request.

## Related Articles

- [Review](/docs/workflows/review)
- [Implement an Issue](/docs/workflows/implement)
- [How the Review System Works](/docs/concepts/review-system)
- [Review Settings](/docs/configuration/review)
