---
title: "Review Problems"
description: "Fix unresolved pull-request targets, stale bases, missing progress and verdict problems."
---

Recover a review that cannot identify, inspect or finish the intended pull request.

## The Pull Request Cannot Be Resolved

Pass a numeric pull-request number and confirm it exists in the current repository. Run:

```bash
gh pr view <number>
gh pr diff <number>
```

If either command fails, fix GitHub authentication or repository access. Do not pass additional flags where the skill expects only a number.

## The Review Targets the Wrong Branch or Commit

Standalone review uses the pull request's pushed head and its current base. Confirm the pull request has the expected head commit and base branch in GitHub. Push local commits before requesting standalone review.

If a pull request was retargeted, fetch the new base and retry. A deleted or unreachable base can stop review because the diff cannot be established safely.

## A Cloud Review Comment Does Nothing

Post `/prflow:review` as a standalone comment on the pull request's **Conversation** tab. Review-submission text and inline review comments are not subscribed trigger surfaces. The requester must be an authorized repository collaborator.

## A Duplicate Review Was Suppressed

PRFlow suppresses a second review request while a fresh progress comment shows a review of the same head commit in flight. Wait for that run. Push a new commit before requesting review again if the pull-request head has changed. Suppression depends on that progress comment being published: a request sent in the brief window before an in-flight review posts it is not suppressed, so two reviews of the same commit can occasionally run — this is harmless and self-heals as soon as the comment appears.

## The Progress Comment Has No Verdict

Check the last item of the comment's checklist first: **Run complete — everything this run owed**. On a standalone `/prflow:review` it is ticked only once the verdict has reached a durable channel — the formal GitHub review, or a marked comment when the review could not be posted. An unticked final item means the run ended without delivering, and the run states why. The comment's status field can read finished while that item is unticked; the item, not the status, is what tells you delivery happened.

Note that a ticked item confirms a durable verdict exists, not that the pull request carries an approve or request-changes merge signal. When the verdict reached the comment channel instead of the reviews API, the run says so.

Before it terminates, a standalone review re-reads its own checklist and makes one bounded attempt to complete a missing delivery. It does not retry beyond that one attempt.

On `/prflow:review-and-fix`, which posts no verdict to GitHub at all, the same item is ticked when the fix loop reaches its terminal work. When that skill is driven inline by another run, its closing bookkeeping can be skipped and the item is left unticked; on that path this is a bookkeeping gap, not a missing verdict.

If the item is still unticked, open the linked Actions run and inspect execution diagnostics for permission denials or an engine error. A failed run can flip the comment to `Review failed`. A configured backstop may post a bounded resume request, but it does not retry forever.

Fresh installs do not provide the old automatic `Devflow Review` status workflow. Do not add that status as a required check unless your repository deliberately retained and operates the legacy tier.

## The Review Did Not Apply My Prompt Extension

`/prflow:review`, `/prflow:review-and-fix`, `/prflow:implement` and `/prflow:pr-description` read `.prflow/prompt-extensions/<skill>.md` through two independent channels, and both run on every applicable run. Where the client supports it, the extension is prepared as prompt text before the agent starts. Independently of that, the run also loads the extension through the bundled reader — unconditionally, whether or not the first channel delivered.

Earlier releases made the second channel a fallback that applied only when the first had not delivered. On hosted runs the first channel is refused silently, and a run could skip the fallback and complete having applied none of your policy. That condition is gone: there is no longer a branch a run can decline to take. Where both channels deliver, they carry the same content and the run treats them as one set of instructions.

Check these when a run appears to ignore your policy:

- **The extension is reported as `unestablished`.** The run states this rather than staying silent. It means the extension's state could not be established — an unreadable file, a broken symlink, something that is not a regular file, or a trusted-extension directory that did not materialize. Treat it as *not applied*, never as an empty extension. Fix the file and re-run.
- **The file name does not match the skill.** The name is the skill's own directory name: `review.md`, `review-and-fix.md`, `implement.md`, `pr-description.md`. `/prflow:review-and-fix` additionally reads `receiving-code-review.md`, because its fix loop applies that skill's principles without invoking it.
- **An implement run left the row unticked.** A `/prflow:implement` workpad's Progress checklist carries one `prompt extension resolved: …` row per extension the run consumes. The row is written whether or not the run cooperates, so an unticked row is that run's own record that it did not establish that extension's state. On a run that finished `Complete`, that record is now deliberate rather than a bookkeeping miss: the finalize is refused while any such row is left both unticked and without an accompanying `state not established` note, so a completed workpad cannot silently carry a resolved-but-unrecorded row. It is still the run's report, not a verified fact — a ticked row is evidence the state was resolved, not proof the policy changed the outcome.
- **A cloud installation is out of date.** The reader is invoked by the installed workflows' permission entries, while the skills themselves ship in the plugin. Updating only `prflow_version` can leave the two halves out of sync and the loader invocation unpermitted. Re-run the installer with the new tag — see [Cloud Updates](/docs/runs/cloud/updates).

A file that is absent or empty is not an error. The run proceeds with PRFlow's own defaults.
