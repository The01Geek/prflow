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

- **`## Verdict:`** — one of the five verdicts below with a short summary naming what drives it, then a one-line reason and a `Rule applied:` line naming the rule that produced the verdict. When the review rejects with a coverage shortfall, a `Coverage shortfall:` line follows it.
- **`## Code Review Findings`** — findings and verification-checklist items, grouped under `### 🔴 Critical`, `### 🟠 Important / Major`, `### 🟡 Suggestion / Minor` and `### ℹ️ Informational — Deferred`. Empty groups are omitted. Each group lists its numbered findings first, then the checklist items of that grade, one `- VC-n: …` line each. A failed checklist item sits in the group for its grade, whether or not it blocks, and that grade is its capped grade when the inert-prose cap lowers it (see [What Causes a REJECT](#what-causes-a-reject)); an inconclusive item sits under Informational — Deferred. The verdict line says what blocks. Each checklist line names the item's severity and quotes its claim, with the file and line it came from when the checklist recorded one, and its raw evidence collapsed beneath it. Each finding says how many dispatched agents raised it. A finding can also come from a checklist verifier: a separate defect it found while checking its item, even an item that passed. Such a finding names its item, and the verifier counts as one agent however many items raised it. Reviewers group a defect class's instances by file, listing each location and grading the finding by its most severe instance; milder instances are marked. A finding's line numbers are lines of the source file, never positions in the diff: content missing or deleted from the current file is described without a current line, a line from the base version is marked as base, and a location is marked unverified when the reviewer cannot read its file or cannot find its line. See [review agents](/docs/configuration/review-agents) for the test-coverage policy. A lower-severity group with no verdict-driving item is collapsed behind an expandable block.
- **`## Deferrals`** — shown only when the pull request body carries a scope-acknowledged deferred-findings block: each deferral that matches a current finding, with its follow-up issue (the word `disclosure` for one settled by a disclosure) and whether that finding was filed at or above your severity threshold, and each deferral not applied, with a reason. A deferral never lowers a finding's weight.
- **`## Issue Compliance`** — shown when the review found a related issue, unless the acceptance criteria came unchanged from the implement workpad or, with no workpad criteria, from the issue body: which issue the change was checked against, where the acceptance criteria came from, whether this run narrowed the scope, and which issue criteria the workpad lacks. Otherwise its one-line summary moves into Run details. A workpad that lacks issue criteria with no recorded decision means the issue was amended after the run mirrored its criteria, or another run overwrote them; the review grades the issue body's criteria either way, and after an amendment `workpad.py acs-remirror <issue>` re-mirrors them (see [Workpads and Resume](/docs/concepts/workpads-and-resume)).
- **`## Run details`** — a collapsed block holding the run's self-audit lines, such as the diff profile and any re-check of a failed item the review doubted (see [What Causes a REJECT](#what-causes-a-reject)). It also holds the checklist content that is not a graded item, including the tally line in the form "Checklist: *N* passed, *N* failed, *N* inconclusive" and the passing items. When the checklist did not run, a `Checklist not run:` line says why.

Every heading and every verdict-driving finding or checklist item stays visible; only supporting detail is collapsed.

## What Gets Reviewed

In pull request mode, PRFlow reviews the pushed pull request head against the pull request's base. Uncommitted local changes are not included.

In current-branch mode, it reviews committed changes between `HEAD` and the configured base branch. Commit what you want assessed before you start.

### Disclosed Stricter-Than-Criterion Fixes

A fix can deliberately go further than an acceptance criterion's wording, for example by applying the criterion's check to a case the criterion leaves out. When recorded in the pull request description, the disclosure is: `Stricter than criterion "<criterion>": <case> — <why>`, where `<criterion>` is the criterion's text on one line, checkbox marker excluded.

In pull request mode the review reads every description line that starts with `Stricter than criterion ` (not indented, not a list item), anywhere in the description. A line counts only when its quoted text equals one of the review's decided criteria exactly. A line whose criterion was reworded or removed is ignored until a fix pass discloses the stricter behavior again, and a numbered `Stricter than criterion <N>:` line written before this format is ignored too. The review hands the line, labeled as author data, to the checker of that criterion and to the checker of every item re-checked from the previous review. The line is a claim to check, never a waiver: the criterion passes on the coverage it names only when the code shows that coverage and every other case the criterion names still gets its required outcome.

When that check passes, a finding that reports only the disclosed departure moves under `### ℹ️ Informational — Deferred` with a `[Stricter than criterion <N> — confirmed by <item id>]` annotation and does not reject at any threshold. A line the code does not bear out changes nothing, and a disclosure never turns a checklist FAIL of this run into a PASS or moves a finding about any other defect; an earlier run's failure is the case under [Re-Checking the Previous Review](#re-checking-the-previous-review). A current-branch review reads no description. `## Run details` gives each read line's outcome: `confirmed` with the checklist item and the findings it moved, or `not confirmed` with the item's verdict — each listing the re-checked items that passed on the line — or `ignored` with the reason; a description that could not be read is recorded as `PR body: unread`. Amend the criterion afterwards if the stricter behavior should become the rule.

### Disputed-Criterion Lines

A fix that would weaken or contradict an acceptance criterion is declined through the caller's existing reporting path, including wording-only edits. A pull request description may carry: `Disputed criterion "<criterion>": <declined findings, summarized> — amend the issue or accept the criterion.`

The line is a prompt for you to amend the issue or accept the criterion; it changes no review outcome, and `## Run details` does not report it. You need no line for a criterion to count: a later pull request review that can read the issue's decided criteria gives them to each item it re-checks from the previous review, so an earlier finding that a criterion settles can pass on that criterion (see [Re-Checking the Previous Review](#re-checking-the-previous-review)).

### Rejected-Finding Lines

A finding judged not a defect, with evidence, can be recorded in the pull request description so later reviews of that pull request stop re-raising it. The line is not indented and reads: `Finding rejected "<the finding, on one line>": <evidence: the file and line read and what it shows>`. For example:

```text
Finding rejected "parse_args() drops an empty --label value": scripts/cli.py parse_args() rejects an empty --label with exit 2 before any caller reads it, so no empty value reaches the writer.
```

`/prflow:fix` adds such a line when it pushes back on a finding of a numbered pull request, and removes it when it later fixes that finding; a line it cannot add or remove goes in its report. Inside `/prflow:review-and-fix`, the fixer adds one only on a numbered pull request in a run with `--push-each-iteration`, as `/prflow:implement` runs it; otherwise, or when that write fails, the line goes in the run's report for you to add. `/prflow:pr-description` keeps these lines when it rewrites the description. A finding that argues against a decided criterion gets a [Disputed-Criterion Line](#disputed-criterion-lines) instead.

A line counts only when the pull request's author is `github-actions[bot]`, an identity listed in `prflow.allowed_bots`, or a person `prflow.allowed_users` admits with write access. If a custom GitHub App opens your `/prflow:implement` pull requests, list it in `prflow.allowed_bots`, or its lines never count. A current-branch review counts no line.

Each counted line reaches every checklist item except acceptance-criterion items, on every review entry, the `/prflow:review-and-fix` shadow pass included. An item asserting the same defect about the same subject passes, quoting the line, when the line's cited facts still hold in the reviewed code; it fails only when a fact the line did not consider shows the defect, such as cited code that changed. Unlike a `Stricter than criterion` disclosure, a counted line can turn this run's checklist item into a PASS. It never settles an acceptance criterion or a finding that a line the pull request added or changed is untrue. Review agents re-raise a covered finding only with new evidence. Verdict rules are unchanged: a review agent that re-raises a covered finding anyway can still reject.

`## Run details` quotes each counted line with the checklist items that passed on it, or `settled none`. When lines exist but none counts, for example because the author is not trusted, it records `Finding rejected lines not counted (<reason>)`. Anyone who can edit a trusted pull request's description can add a line, so check that listing and delete a line you disagree with. Older `**Finding rejected:**` comments are not read; re-record one as a line to restore it.

### Re-Checking the Previous Review

In pull request mode, each standalone review, and the first iteration of `/prflow:review-and-fix`, also re-checks the pull request's most recent finalized PRFlow review report, whatever its verdict. It reads only a review's live progress comment. A review run that kept no progress comment — for example because [`prflow_review.live_progress_comment_enabled`](/docs/configuration/review#review-engine) is `false`, because `telemetry.enabled` is `false` and that key is unset, or because the comment could not be created — leaves no report for a later run, which re-checks the newest earlier progress-comment report instead, or records `prior-report: none` when there is none. Failed checklist items and findings from that report can become checklist items that this run verifies at the current head; not every one is guaranteed to carry forward. Findings under `### ℹ️ Informational — Deferred` are not re-checked. The rest of the checklist is still built fresh from the diff, so a new defect can still be found.

A re-checked item that still fails counts like any other failed checklist item, except under the untrue-line rule described below. A re-checked item that now passes states why the earlier evidence no longer holds: the defect was fixed, the earlier evidence was wrong, or the earlier failure reports only a departure that a `Stricter than criterion "<criterion>": <case> — <why>` line in the pull request description discloses and the review confirms against the code, or a counted [rejected-finding line](#rejected-finding-lines) covers it and its cited facts still hold, or a decided criterion's words require the behavior the earlier evidence called a defect, or exclude what the earlier finding asks, and the code shows that behavior, or the code still shows the earlier behavior but it is no defect, with evidence opening `No defect:`: nothing that reads it fails, it causes none of the harms the review grades severity by, such as wrong output, lost data or a security gap, any cost it adds is bounded by its inputs, and the decided criteria are usable and none requires otherwise. That last reason never applies when, for example, the earlier finding shows a statement still untrue in the reviewed code, or reports a missing test of changed code or a broken explicit project rule. A finding of this run that repeats only an earlier finding passed on a criterion moves under `### ℹ️ Informational — Deferred` with a `[settled by criterion <N> — confirmed by <item id>]` annotation naming the re-checked item; it demotes no other finding, and a finding the review marks as a rejection carve-out, for example an unmet decided criterion, never moves.

Only a report posted by `github-actions[bot]`, by an identity listed in `prflow.allowed_bots`, or by a person `prflow.allowed_users` admits with write access is re-checked. A report from anyone else is skipped for the next older one. A review marked `REVIEW INCOMPLETE` is also skipped. The `## Run details` block records the outcome on a `prior-report:` line:

| `prior-report:` line | What it means |
| --- | --- |
| `prior-report: comment <id> by <author>, reviewed HEAD <sha>` | That report was re-checked. |
| `prior-report: none` | No earlier trusted report exists. The review runs as usual. A `(<n> untrusted report(s) skipped)` suffix counts the reports passed over for their author. |
| `prior-report: unavailable (<cause>)` | The earlier report could not be established, for example because the pull request's comments could not be fetched or an author's trust could not be decided. The verdict is capped at `APPROVE WITH CAVEAT`. |

When an earlier report was found but the re-check items made from it did not all reach a written checklist, for example because the step that writes them failed twice, `Run details` carries `seed shortfall: prior report not seeded` and the verdict is also capped at `APPROVE WITH CAVEAT`. A current-branch review re-checks nothing. Inside `/prflow:review-and-fix`, the first iteration re-checks the previous review and later iterations keep its `Run details` lines and any cap. The shadow pass re-checks nothing.

Four review agents always run: a general code reviewer, a silent-failure hunter, a comment-accuracy analyzer and a final-pass independent reviewer. Two more run only when the diff calls for them — a type-design analyzer when the change adds new types, and a test analyzer when the change touches test files or adds new testable logic. See [Review Agents](/docs/configuration/review-agents). Each finding says what is wrong and where, and suggests no fix.

## The Verdicts

The engine emits one of five verdicts.

| Verdict | Meaning |
| --- | --- |
| APPROVE | No findings, and every checklist item passed. |
| APPROVE with notes | Findings or failed checklist items exist, but none of them blocks: for example, each is below the configured severity threshold or is an exempt finding (one about pre-existing behavior the change does not touch, or one a decided acceptance criterion decides), or some checklist items are inconclusive at any severity. |
| APPROVE WITH ADVISORY NOTES | Approved, with findings deliberately parked for a human to judge. |
| APPROVE WITH CAVEAT | Approved, but verification coverage was incomplete: the verification checklist could not be generated, the checklist holds at least one item and every item is inconclusive, an item is inconclusive because verification itself failed, such as a verifier that timed out, or the pull request's previous review could not be established or turned into checklist items. It takes precedence over APPROVE with notes. |
| REJECT | At least one blocking problem. On a pull request this posts a request for changes. |

<Note>
  An APPROVE from PRFlow is a machine verdict on one diff. It is not a human approval and it does not merge anything. Treat it as evidence for your reviewers, not as a substitute for them.
</Note>

## What Causes a REJECT

Any one of these drives a REJECT.

1. **A failed verification-checklist item at or above the severity threshold.** Each item is graded `critical`, `important` or `suggestion` by how much would break if its claim were false; an item without a trustworthy grade counts as `critical`. A failed item about inert prose (defined below) counts at its capped grade; the report still lists it.
2. **A finding at or above the configured severity threshold.** The default threshold is `critical`, so by default only Critical findings and critical checklist failures block, less the inert-prose exception above. Set `prflow_review.verdict_severity_threshold` to `important` or `suggestion` to make the line stricter. At those two settings a finding below Critical that only argues against a decided acceptance criterion does not block: its whole claim is behavior the criterion's words require, or it asks for what they exclude. It stays in the report at its grade, marked `[decided by criterion <N>]`. Some still block, for example a Critical finding, a finding that is partly a real defect, and one whose relation to a criterion is unclear. Findings and checklist failures below the line stay visible as notes. An inconclusive checklist item never blocks; the report lists it under Informational — Deferred.

**A failure the review itself doubts is re-checked before it can block.** When the review's own reading of a file in the reviewed code contradicts the evidence behind a failed checklist item at or above the threshold, it sends that item back to a verifier once in the same run, with the doubt as a claim to check. It does the same for a failed item at or above the threshold that was re-checked from the previous review, when a decided criterion's words settle the point that item raised. The re-check's pass, or its failure at its own severity, replaces the stored failure unless the source-view check rejects its evidence; an inconclusive or unusable re-check keeps it. A doubt resting only on the pull request's text or an author's comment is never re-checked, and neither is an item settled by a quick text probe, an item whose cited file the review cannot read, or any item in a review whose verification results had to be written without the verdict helper. The report shows each doubt and its outcome only in `## Run details`, for example `re-verification VC-6: counter-reading '…'; FAIL (important) -> PASS (important)`, or a line ending `re-verification not applied (<reason>)` when the item was not re-checked. Each re-check costs one more verifier run.

### The Rules That Surprise People

Further rejection rules do not read the severity threshold. Their one exception is **inert prose**: a code comment, docstring or documentation line that no tool or agent reads to decide behavior. An untrue line of inert prose is capped at Suggestion, or at Important when it ships to readers outside the repository (a README, a published doc page, a release note, a user-facing message), so it never rejects at the default threshold.

<Warning>
  If the change's own diff added or modified a documentation line, a code comment or a test that is **untrue**, that alone causes a REJECT — at every threshold setting, and whatever severity the finding was graded. Severity settings cannot lower it, deferring it does not clear it, and one agent raising it is enough. Only correcting the untrue claim, or the code it describes, clears the REJECT. The exception is inert prose, capped as described above. When the earlier review a pull request review re-checks (see Re-Checking the Previous Review above) holds a finding that rejected a line under this rule, a re-check that finds the line still untrue keeps the REJECT on that review, whatever severity it is graded. A few review-side conditions stop this carry, for example a re-check item the review could not build correctly.
</Warning>

"Untrue" means the claim is stale, contradicts the code as it now stands, or contradicts another part of the same change. The rule covers the change's own additions and edits, not prose that was already there.

Prose a tool or agent reads to decide behavior is never inert, so an untrue line there always rejects.

<Accordion title="Why this rule exists">
  A change that ships a comment or a doc line describing behavior it does not have is worse than one that ships no comment at all: the next reader trusts it. The same applies to a test whose assertion does not match what the change claims to guarantee.

  Because the cost lands on a future reader rather than on today's run, a severity grade would let it be tuned away. So the rule sits outside severity entirely.
</Accordion>

<Warning>
  If a finding shows the change does not meet a **decided acceptance criterion** of the linked issue, that alone causes a REJECT — at every threshold setting, and whatever severity the finding was graded. Deferring it does not clear it, and a limitation the change discloses about itself that contradicts a criterion counts as that criterion being unmet, not as honest disclosure. Only meeting the criterion, or recording that it was genuinely out of scope, clears it. The exception is a criterion whose subject is inert prose: its finding is capped as described above.
</Warning>

A general quality or test-coverage finding that establishes no unmet criterion is unaffected and stays weighed by the severity threshold. Separately, on every run that builds a checklist, every decided acceptance criterion gets its own checklist item, however many the issue carries, and if any criterion is left without one, the review rejects with a coverage shortfall. A criterion ending in the `(post-merge)` tag is excluded from the reviewer-facing set, so tag a criterion the code alone cannot establish. A run whose checklist generation failed caps that run's verdict at `APPROVE WITH CAVEAT`, because no checklist was generated.

## What Review Never Touches

Review does not edit, commit, check out or push the reviewed tree. It writes temporary scratch data, and in pull request mode it maintains a progress comment and posts the final GitHub review.

Before it posts, the review checks its own evidence. It does not post an approval while a failed checklist item counts against your severity threshold; it posts REJECT instead. Nor does it post one while a reviewer the run planned, the final pass included, left no record of having run; it ends without a verdict instead, naming what was missing, and you re-run the review. A REJECT is checked too, for the reviewers every review runs. If the formal review cannot be posted, PRFlow posts the same verdict as a pull request comment when it can and tells you the merge signal is missing. A posted approval also clears PRFlow's own earlier change requests on older commits. It never merges the pull request.

Use [Review and Fix](/docs/workflows/review-and-fix) when you want the findings corrected as well as reported.

## Related Articles

- [Review and Fix](/docs/workflows/review-and-fix)
- [How the Review System Works](/docs/concepts/review-system)
- [Review Agents](/docs/configuration/review-agents)
- [Review Settings](/docs/configuration/review)
