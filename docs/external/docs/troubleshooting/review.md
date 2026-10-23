---
title: "Review Problems"
description: "Fix a review that cannot find the pull request, rejects unexpectedly, reports unverified coverage or delivers no verdict."
---

Match the symptom to an entry below, run its diagnostic command, then apply its fix.

<AccordionGroup>

<Accordion title="The pull request cannot be resolved">

**Symptom:** the run says it cannot find the pull request, or it never gets as far as reading a diff.

Confirm the number exists in this repository and that you can read it:

```bash
gh pr view <number>
gh pr diff <number>
```

If either command fails, fix GitHub authentication or repository access first. Pass only the number. The skill expects a bare pull-request number and no extra flags.

</Accordion>

<Accordion title="The review targets the wrong branch or commit">

**Symptom:** the findings describe code you already changed, or code you never wrote.

Check what GitHub thinks the pull request points at:

```bash
gh pr view <number> --json headRefOid,headRefName,baseRefName
```

A standalone review reads the pull request's pushed head and its current base. Push your local commits before you request a review, or the review reads the older head.

If the pull request was retargeted, fetch the new base and try again. A deleted or unreachable base stops the review, because the diff cannot be established safely.

</Accordion>

<Accordion title="My pull request was rejected over a documentation line, comment or test I touched">

**Symptom:** the verdict is REJECT, and the finding says that a documentation line, a release-note line, a code comment or a test that this change itself added or modified is untrue.

Read the finding and see the line it names:

```bash
gh pr view <number> --json reviews --jq '.reviews[-1].body'
gh pr diff <number>
```

This is a deliberate rule, not a severity judgment. When the change's own diff adds or modifies a line that is false — stale, contradicting the current code, or contradicting another part of the same change — that alone causes a REJECT.

<Warning>
Except for inert prose (below), this REJECT cannot be lowered by configuration. It fires at every value of the severity threshold, including the most permissive one, and whatever severity the reviewing agent assigned it. Deferring the finding does not clear it either.
</Warning>

Only two things clear it:

- Correct the untrue line so it matches the code.
- Correct the code so the line becomes true.

One case is graded normally instead: **inert prose**, a code comment, docstring or documentation line that no tool or agent reads to decide behavior. An untrue line of it, whether a cosmetic slip or a false claim, is capped at Suggestion, or at Important when it ships outside the repository (a README, a published doc page, a release note), so it never rejects at the default threshold. Prose that a machine reads or that instructs an agent is never inert.

</Accordion>

<Accordion title="The report says coverage could not be verified, or the verdict reads APPROVE WITH CAVEAT">

**Symptom:** the pull request is approved, but the verdict line reads `APPROVE WITH CAVEAT`, or the summary contains a phrase beginning `shadow agreement not verified`.

Read the verdict and the summary line together:

```bash
gh pr view <number> --json reviews --jq '.reviews[-1].body'
```

Both signals mean the same thing: the review found nothing that blocks the merge, and it could not confirm how much of its own checking actually happened. It says so rather than reporting a clean approval it cannot support.

The common causes are:

- The verification checklist could not be generated, so the phases that check each claim were skipped. That caps the verdict at `APPROVE WITH CAVEAT` and never lets it be a clean `APPROVE`.
- The checklist holds at least one item and every item is inconclusive, or an item is inconclusive because verification itself failed, such as a verifier that timed out or returned no usable verdict. The report lists those items under `### ℹ️ Informational — Deferred`.
- The pull request's previous review could not be established, or the re-check items made from it did not all reach a written checklist. `Run details` then carries a `prior-report: unavailable (<cause>)` line or `seed shortfall: prior report not seeded`.
- Every finding sat below the fix loop's severity threshold, so the findings were parked as advisory rather than fixed.
- The shadow pass did not establish agreement, including when it ran inline in the informed loop context after an engine dispatch failed. The summary then reads `shadow agreement not verified`, sometimes with the reason in parentheses. Separate write directories do not isolate reads.

Treat it as approved with unknown coverage. Read the report and decide as a human whether the gap matters. Requesting the review again is worth doing when the cause was transient. Nothing about this verdict means a defect was found and hidden.

</Accordion>

<Accordion title="I get too many findings, or too few">

**Symptom:** every pull request comes back REJECT over small things, or obvious problems come back only as notes.

Read the two settings that move those lines:

```bash
jq '{verdict: .prflow_review.verdict_severity_threshold, fix: .prflow_review_and_fix.fix_severity_threshold}' .prflow/config.json
```

| Setting | Default | What it does |
| --- | --- | --- |
| `prflow_review.verdict_severity_threshold` | `critical` | A finding, or a failed checklist item, at or above this severity causes REJECT; a failed item about untrue inert prose counts at its capped grade, and at `important` or `suggestion` a finding below Critical that clearly does nothing but argue against a decided acceptance criterion does not, unless another rejection rule applies to it. Set it to `important` to make Important ones block the merge too. Both `/prflow:review` and the review pass inside `/prflow:review-and-fix` use it. |
| `prflow_review_and_fix.fix_severity_threshold` | `important` | The fix loop sends every finding and failed checklist item at or above this severity to the fixer, subject to `fix_below_threshold_iterations`. Anything below it stays advisory, except as the paragraph below this table says, and an inconclusive checklist item is never sent. Set `suggestion` for a more aggressive fixer, or `critical` for a conservative one. |

Severity runs `critical`, then `important`, then `suggestion`. An unknown or wrongly typed value falls back to the default with a note, and never stops the run. Whatever the fix threshold says, any finding or failed checklist item that would cause REJECT, and any finding exempt from REJECT because a decided acceptance criterion decides it, stays eligible for the fixer. Suggestion and Minor findings from the check the loop runs on its own fixes can also reach the fixer.

Remember that the untrue-line rule above ignores both settings.

</Accordion>

<Accordion title="A cloud review comment does nothing">

**Symptom:** you commented on the pull request and no run started.

Post `/prflow:review` as a standalone comment on the pull request's **Conversation** tab. Review-submission text and inline review comments are not trigger surfaces, so a command typed into a code-review reply is never seen. The account that comments must be an authorized repository collaborator. See [Cloud-Run Problems](/docs/troubleshooting/cloud-runs) for the authorization check.

</Accordion>

<Accordion title="A duplicate review was suppressed">

**Symptom:** you asked for a review and the run declined, saying one is already in flight for the same commit.

PRFlow suppresses a second request while a fresh progress comment shows a review of the same head commit running. Wait for that run to finish. If the head has moved, push the new commit first and then ask again. The review request PRFlow posts when CI passes is never suppressed by that progress comment.

Suppression depends on that progress comment already being published. A request sent in the short window before an in-flight review posts its comment is not suppressed, so two reviews of the same commit can occasionally run. That is harmless and clears itself once the comment appears.

</Accordion>

<Accordion title="The progress comment has no verdict">

**Symptom:** the progress comment looks finished, but no verdict reached the pull request.

Check the last item of the comment's checklist first: **Run complete — everything this run owed**. On a standalone `/prflow:review` the posting step ticks that item only once the verdict has reached a durable channel — the formal GitHub review, or a marked comment when the review could not be posted. An unticked final item usually means the run ended without delivering, and the run states why: after a failed post the comment's status reads `❌ <verdict> not posted`, followed by the reason. The item also stays unticked when the verdict was posted but the one write that marks and ticks the comment failed; the run reports that in its output, and the review on the pull request is the record. Otherwise the status field can read finished while the item is unticked, so a ticked item, not the status, is what tells you delivery happened.

A ticked item confirms a durable verdict exists. It does not confirm the pull request carries an approve or request-changes merge signal. When the verdict reached the comment channel instead of the reviews API, the run says so.

Before it ends, a standalone review whose verdict failed to post on both channels makes one more attempt to deliver it. If that attempt also fails on a run that was not cancelled, the run's job fails. With a workflow-capable GitHub App configured, the review stall backstop may also request the review again, up to `prflow_review.stall_backstop.max_resume_attempts` times per head commit. Both the failed job and the renewed request need the installed workflow and the vendored PRFlow helpers to be current.

On `/prflow:review-and-fix`, which posts no verdict to GitHub at all, the same item is ticked when the fix loop reaches its terminal work. When that skill is driven by another run, its closing bookkeeping can be skipped and the item is left unticked. On that path this is a bookkeeping gap, not a missing verdict.

If the item is still unticked, open the linked Actions run and look at the execution diagnostics for permission denials or an engine error:

```bash
gh run view <run-id> --log-failed
```

A failed run can flip the comment to `Review failed`. A configured backstop may post a bounded resume request, but it does not retry forever.

Fresh installations do not include the old automatic `Devflow Review` status workflow. Do not add that status as a required check unless your repository deliberately kept and still operates that older tier.

</Accordion>

<Accordion title="The run stopped with engine-root: incomplete">

**Symptom:** the run reports `engine-root: incomplete` together with the path it read, and applies no fixes.

`/prflow:review-and-fix` reads PRFlow's review engine as a file, and confirms it received that file whole before acting on it. When it cannot confirm that, it stops rather than reviewing your pull request against a partly loaded engine. A run that stops this way has applied no fixes and reports no verdict, so nothing has been assessed.

On a local-tier run the engine is read from the vendored tree in your repository when one exists, and otherwise from the plugin you have installed — so a repository with no committed `skills/` directory and no runtime-vendored `.prflow/vendor/` tree still finds the engine that ships with the running plugin. A cloud run always reads the vendored tree.

Check these in order:

- **The engine file cannot be read.** Confirm the run can read the engine's `SKILL.md` — `.prflow/vendor/prflow/skills/review/SKILL.md` when your repository has a vendored tree, otherwise the copy inside the installed plugin. Fix file permissions, or re-run the installer with your current tag if the vendored copy is missing or incomplete — see [Cloud Updates](/docs/runs/cloud/updates).
- **Your client cannot read a file in parts.** PRFlow confirms it reached the end of the engine file by reading past what it already holds. A client whose file reader does not accept a starting position cannot answer that question, so the run stops even when the file is intact. Run the workflow from a client whose file reader accepts a starting position.

The shadow pass reads the engine the same way. When the condition occurs there, the run does not stop. It reports a coverage gap for that pass and continues.

</Accordion>

<Accordion title="The review did not apply my prompt extension">

**Symptom:** a run appears to ignore the policy you wrote in `.prflow/skill-extensions/`.

`/prflow:review`, `/prflow:review-and-fix`, `/prflow:implement` and `/prflow:pr-description` read `.prflow/skill-extensions/<skill>.md` through two independent channels, and both run on every applicable run. Where the client supports it, the extension is prepared as prompt text before the agent starts. Independently of that, the run also loads the extension through the bundled reader, whether or not the first channel delivered.

Earlier releases made the second channel a fallback that applied only when the first had not delivered. On hosted runs the first channel is refused silently, so a run could skip the fallback and finish having applied none of your policy. That condition is gone. Where both channels deliver, they carry the same content and the run treats them as one set of instructions.

Check these when a run appears to ignore your policy:

- **The extension is reported as `unestablished`.** The run states this rather than staying silent. It means the extension's state could not be established — an unreadable file, a broken symlink, something that is not a regular file, or a trusted-extension directory that did not materialize. Treat it as *not applied*, never as an empty extension. Fix the file and run again.
- **The file name does not match the skill.** The name is the skill's own directory name: `review.md`, `review-and-fix.md`, `implement.md`, `pr-description.md`. `/prflow:review-and-fix` additionally reads `fix.md`, because its fix loop applies that skill's principles without invoking it. The `fix` extension was renamed from an earlier name; if you customized it under that name the old file still applies until you rename it to `fix.md` (or let `/prflow:init` rename it), and the run prints a breadcrumb naming the exact file.
- **An implement run left the row unticked.** An implement workpad's Progress checklist carries one `Skill extension resolved: …` row each for the `implement`, `review-and-fix` and `fix` extensions; a `review` or reviewer extension load that the review reports as failed, refused or unestablished is recorded as a workpad reflection instead; if that write fails, no workpad or pull request records the failed load. The row is written whether or not the run cooperates, so an unticked row is that run's own record that it did not establish that extension's state. On a run that finished Complete that record is deliberate: the finalize step is refused while any such row is left both unticked and without an accompanying `state not established` note. It is still the run's report, not a verified fact — a ticked row is evidence the state was resolved, not proof the policy changed the outcome. An older workpad may still hold an unticked `review.md` row; it no longer blocks Complete.
- **A cloud installation is out of date.** The reader is invoked by the installed workflows' permission entries, while the skills themselves ship in the plugin. Updating only `prflow_version` can leave the two halves out of sync and the loader unpermitted. Re-run the installer with the new tag — see [Cloud Updates](/docs/runs/cloud/updates).

A file that is absent or empty is not an error. The run proceeds with PRFlow's own defaults.

</Accordion>

</AccordionGroup>

## Related Articles

- [Review](/docs/workflows/review)
- [Review and Fix](/docs/workflows/review-and-fix)
- [Review System](/docs/concepts/review-system)
- [Review Settings](/docs/configuration/review)
- [Skill Extensions](/docs/configuration/skill-extensions)
