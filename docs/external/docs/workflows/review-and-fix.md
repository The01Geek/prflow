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

The final chat report opens with a one-line result. On an approval-side outcome it names how many iterations ran and whether the independent shadow pass agreed, in the shape "Review passed after *N* iteration(s) (*shadow status*)". On an approval with parked findings it also states how many advisory findings were left for human review. A REJECT says so and the findings stay in the report below it.

Underneath the headline is the same report structure as a standalone review: the verdict, issue compliance, the verification-checklist tally and the findings grouped by severity. Each finding also carries what the loop decided about it — applied, pushed back, deferred, advisory or severity-calibrated.

The commits it made are on your branch, one per fix iteration.

<Note>
  This workflow does not post a formal GitHub review. Its verdict goes to chat. To get a merge signal on the pull request, run [Review](/docs/workflows/review) afterward — a separate, independent pass over the fixed head.
</Note>

## Edit Authority

This workflow applies fixes directly in the session that runs it, and commits as it converges.

In pull request mode it checks out the pull request head and confirms both the branch name and the head commit before it reviews or edits anything. A working tree too dirty to check out stops the run. In current-branch mode the commits land on the branch you already have checked out.

Use [Review](/docs/workflows/review) when you do not want your branch changed.

## Iterations and What Gets Fixed

The default iteration cap is five. Change it with `prflow_review_and_fix.max_iterations`. The loop also exits early when it converges.

Which findings reach the fixer is set by `prflow_review_and_fix.fix_severity_threshold`, which defaults to `important`:

| Threshold | Fixed | Left advisory |
| --- | --- | --- |
| `critical` | Critical only | Important, Major, Suggestion, Minor |
| `important` (default) | Critical, Important, Major | Suggestion, Minor |
| `suggestion` | Everything | Nothing |

Anything that drives a REJECT is always fixable, whatever this threshold says. That is deliberate: it means no combination of settings can produce a blocking finding the fixer is configured to ignore.

PRFlow can push back on a finding when the code disproves it, rather than "fixing" something that was never wrong. It can also defer a genuine finding when the deferral rules apply. A test broken by one of its own fixes must be repaired before the loop continues.

## Push Behavior

Where the fix commits end up depends on how you started the run.

**Locally**, they stay on your branch and are not pushed. Add `--push-each-iteration` to push each completed iteration and the final loop state to the feature branch, which keeps the remote branch and its continuous integration runs current.

**From a pull request comment**, the run pushes its fix commits to the pull request branch, so the fixes are on the pull request when the run finishes. You do not pass the flag, and could not — the workflow builds the command from the command word and the thread number alone, so any extra argument in a comment is ignored.

<Note>
  Pushing never posts a verdict. It only moves commits. To get a merge signal, run [Review](/docs/workflows/review) afterward.
</Note>

## Shadow Review

Before it concludes on the approval side, PRFlow runs a separate shadow review over the candidate. The shadow pass reports which planned reviewers completed and any coverage gaps it knows about.

<Note>
  Shadow agreement narrows the chance of a false clean result. It does not close it. A run reporting no gap has not proved that the review found every defect, and it is not a substitute for a human review or a formal merge signal.
</Note>

When the shadow pass cannot confirm its own coverage, the report says agreement was not verified rather than claiming agreement.

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

That run reviews the resulting pull request head from scratch and attempts to post the formal GitHub review. If GitHub refuses the post, PRFlow reports which fallback channel it used and that the merge signal is missing. Neither workflow merges the pull request.

## Related Articles

- [Review](/docs/workflows/review)
- [Implement an Issue](/docs/workflows/implement)
- [How the Review System Works](/docs/concepts/review-system)
- [Review Settings](/docs/configuration/review)
