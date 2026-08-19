---
title: "Release Notes"
description: "User-visible PRFlow changes, fixes and upgrade notes."
---

# Release Notes

This page summarizes user-visible PRFlow changes. For a complete change history, see [GitHub Releases](https://github.com/The01Geek/prflow/releases).

**Legacy review tier:** Entries about automatic pull-request-triggered review apply only to repositories that installed that tier before July 29, 2026. Fresh installations do not receive it. Use a collaborator comment with `/prflow:review` for the supported cloud review path.

## August 19, 2026

- **Fix: two Windows-only failures in PRFlow's Python helpers are closed.** On a Windows host whose default codec is not UTF-8, a first-party helper that printed an em-dash or emoji used to crash with an encoding error; every tracked helper now forces its output to UTF-8 on startup, so that output prints cleanly. Separately, the issue-audit step rejected a Windows drive-letter path (`C:/Users/…` or `C:\Users\…`), blocking `/prflow:create-issue`'s audit on Windows; the path check now accepts any path the interpreter treats as absolute — including the drive-letter form in either slash spelling — and uses it unchanged. Linux and macOS are unaffected. You get this through the normal plugin update. (#1762)

## August 14, 2026

- **`/prflow:create-issue` now writes a minimum-sufficient implementation brief.** The issue body carries the decisions an implementer cannot safely derive on their own and keeps material only when removing it could change what gets built; the investigation behind those decisions — supporting evidence, audit history and detail the repository would rediscover during implementation — is recorded separately instead of being mixed into the body. So an approver reviews the implementation contract rather than the whole investigation, and an implementer spends less effort separating decisions from derivation. A `Verified:` premise stays in the body when the implementation relies on it and moves to the record when it is only confirmatory, and the over-retention audit flags a repeated claim only when no consumer or check needs that copy — it never touches the required projections or machine-read sections. No length, size or criterion-count limit decides what survives, and no load-bearing detail is dropped to make the body shorter. You get this through the normal plugin update. (#1676)
- **Fix: `/prflow:create-issue` no longer dies when your client lacks its first-choice task-tracking tool.** The workflow tracks its own progress through a seven-step checklist, and it used to reach for one particular tracking tool and stop dead if your client did not offer it — reporting an error such as `No such tool available` after it had already told you the checklist was set up. It now tries the tracking tools it knows in order, moving to the next one whenever the one it tried is unavailable, and asks your client for tools it has not yet offered before giving up. If none of them work, it keeps the same checklist inline in the conversation instead, so the run continues either way. It also announces the checklist only once it genuinely has one, and reports any tool it could not use just after that first line rather than in place of it. Clients that already offered the first tool behave exactly as before. You get this through the normal plugin update. (#1689)
- **Fix: `/prflow:implement` reliably records its cleanup gate on Windows Git Bash and MSYS2.** During implementation, `/prflow:implement` ticks a Progress row when its code-cleanup gate finishes. On Windows Git Bash and MSYS2 hosts, the value it passed to do that looked like a Unix path, so those shells silently rewrote it into a Windows path before it reached Python — the row stayed unticked and the run reported a spurious miss. The gate now passes a plain, non-path value that those shells leave alone, so the Progress row is ticked as expected. Nothing about the row's familiar label changes, and other platforms were never affected. You get this through the normal plugin update. (#1679)

## August 13, 2026

- **An issue can now say "no documentation is needed" without turning a page it mentions into required work.** When you write an issue, its `Documentation Needed` block can list files that the change must update, and `/prflow:implement` treats every file named there as a mandatory deliverable. Previously, if you wrote that no documentation was needed and then named a file to explain *why* it was already fine, that mentioned file was still demanded — so the honest, informative phrasing was punished and an otherwise-finished run stalled asking you to edit a page that needed no change. You can now open the block with the standalone word `none` (case-insensitive, optionally followed by a single `,` `.` `;` or `:`), and the block promises nothing — you can still add a sentence and name the page that explains the decision. The word must stand alone as the block's opener: an ordinary sentence such as `None of these pages may be skipped:` still names its files as required. The routine documentation pass runs and updates whatever the change warrants regardless. (#1663)
- **Fix: Implement review progress stays on the issue workpad** — An inline review-and-fix pass no longer opens a separate progress comment on the draft pull request during `/prflow:implement`; its review stages update the existing issue workpad instead. A standalone pull-request review still maintains its own live progress comment. (#1668)

## August 12, 2026

- **Improvement: Acceptance Criteria Now Cover Every Desired Outcome** — PRFlow now checks that every independently testable outcome in an issue's Desired Behavior is represented by its acceptance criteria before implementation begins. If an outcome is uncovered, issue creation revises the draft and implementation stops for refinement instead of silently omitting the requirement or inventing a criterion. (#1662)
- **Weekly retrospectives no longer treat a cancelled CI run as a failure, and no longer miss failures on large CI matrices.** The retrospective decides whether a merged pull request needs a full model analysis partly from how its CI went. A run that was cancelled or superseded — which is what happens to the in-flight run every time you push again — was being counted as a CI failure, so ordinary iteration pushed healthy pull requests into paid analysis. In the other direction, only the first page of check results was being read, so a repository with a large CI matrix could have real failures go uncounted. Cancelled and superseded results are now excluded, all pages are read, and any result the check does not recognize still counts as a failure rather than as a pass. When the check results cannot be read at all, the pull request is still analyzed rather than assumed clean, and the reason is now named in the output. You get this through the normal plugin update. [#1441](https://github.com/The01Geek/prflow/issues/1441)
- **`/prflow:implement` now looks for reusable code by what it does, not by how you were about to write it.** Before writing new code, `/prflow:implement` searches your codebase for something that already does the job, so it can reuse it instead of reinventing it. But once a run had settled on how it was going to write the code, it naturally searched for that exact shape — a search that could only ever confirm the choice it had already made. An existing helper that did the same job in a different style matched none of those terms and stayed invisible, and the run recorded the empty result as if it had proven nothing existed. The reuse search is now keyed on the job itself — the operation it performs, the kind of data it handles, the thing it works on — and before running it the run checks that the search would actually match a different-looking implementation of the same job, re-keying it if it would not. An empty result is now recorded as "nothing matched what I searched for" rather than as a bare claim that nothing exists. The practical effect is fewer near-duplicate helpers introduced by a run. You get this through the normal plugin update. [#1635](https://github.com/The01Geek/prflow/issues/1635)

- **`/prflow:implement` and `/prflow:review` now start reliably on runners that refuse a routine command.** Both commands locate their own skill files at the very start of a run. They did that by running a small shell command that prints a directory path — and on some runners (for example Copilot CLI, and one hosted configuration) the permission layer refuses that exact command shape, even when the command itself is allowed. The old rule only described what to do when the command *ran*, so a flat refusal fell through the cracks: depending on how it was read, the run either stopped at its first step or quietly carried on having skipped it. Both commands now take the skill directory from the location the runner already reports in context first, and only fall back to that shell command when the runner reports no such location. A refusal of the fallback is now handled as its own distinct outcome — the run either finds the directory another way or stops and says the anchor could not be resolved, never skipping the step silently. You get this through the normal plugin update, with no workflow file to re-copy and no permission to add. [#1594](https://github.com/The01Geek/prflow/issues/1594)

## August 11, 2026

- **Your prompt extensions now survive a long run rather than being lost partway through.** PRFlow fetches `.prflow/prompt-extensions/<skill>.md` at the start of a run, but on a long run that fetch is delivered as ordinary command output that can be dropped from the agent's context, leaving the rest of the run applying none of your policy — a run has completed and reported success with the extension absent throughout. The skills that re-enter their own stages now re-fetch your extension at each of those boundaries as well as at run start: `/prflow:implement` at every phase entry and mid-phase re-anchor, `/prflow:review` at every phase and shadow entry, and `/prflow:review-and-fix` once per fix iteration (for both its own extension and `receiving-code-review.md`). A run that loses your policy to context eviction now recovers it instead of continuing without it, and a re-fetch that is refused or fails is reported at that point rather than passed over. `/prflow:pr-description` is a single-pass command and is unchanged. This is a reliability recovery, not a change to how you author extensions. [#1574](https://github.com/The01Geek/prflow/issues/1574)

- **An acceptance criterion is no longer ticked on the word of a check that was never fully carried out.** Before `/prflow:implement` ticks a criterion, two independent checkers look at it in fresh context and their two answers are reconciled — but each one reported only its conclusion, so a checker that skipped part of its own procedure and still answered "satisfied" was indistinguishable from one that did the whole thing, and the criterion was ticked. Each checker now also states, step by step, what it actually did: for every named step of its own procedure it records `yes` or `no` with a one-clause reason. A stated `no` is a perfectly acceptable answer and changes nothing on its own — what is not acceptable is saying nothing. A criterion where either checker left a step unstated is now treated as unverified and blocks, even when both checkers said "satisfied". The statements are recorded on the workpad alongside the verdict, so after the run you can see which steps were performed rather than only what was concluded. The practical effect is that a run is more likely to stop and tell you a criterion was not properly verified, instead of quietly ticking it. [#1580](https://github.com/The01Geek/prflow/issues/1580)

## August 10, 2026

- **A review no longer downgrades a real coverage gap because the gap was described in a comment.** Before a review computes its verdict, it caps a finding whose only effect is on wording that cannot change what the program does, so a cosmetic wording nit never blocks a merge. That test read as if it were about the kind of line the finding pointed at, so a finding that a check audits too small a population, that a guard misses an exception or that a validation misses a type could be capped at Suggestion whenever the gap happened to be described in a comment or docstring — a real defect reported as a minor note. The cap is now decided by what the finding is *about*: if the finding disputes what a mechanism covers, it is graded on that functional gap and never capped, whether or not the change touched the line. A genuinely cosmetic wording nit is still capped exactly as before. [#1455](https://github.com/The01Geek/prflow/issues/1455)
- **A rewritten progress comment no longer loses the hidden lines that identify it.** PRFlow's review progress comment and implementation workpad each begin with hidden marker lines: one identifying which run owns the comment, and, on a review, one recording the verdict and the commit it was issued against. A step that rewrote the whole comment body composed those bytes from what it was holding, so a step that did not retype the markers dropped them — and nothing reported an error, because a later reader looking for a marker found none and read that as "there was no such comment". The visible effect was a review that appeared not to have happened, or a second workpad opened beside the first. A whole-body rewrite now re-inserts any leading marker line it omits, keeping the live comment's order while letting a marker the step does supply win, so a re-stamped verdict still lands. When PRFlow cannot read the live comment to establish which markers it carries, it proceeds only if the new body already carries its own leading marker, and otherwise refuses the write rather than risk dropping one. [#1508](https://github.com/The01Geek/prflow/issues/1508)
- **An issue's `Documentation Needed` files are now actually enforced by `/prflow:implement`.** When an issue names files that must be documented, the run is supposed to name them to its documentation pass and then check each one against the pull request's diff before ticking `Documentation`. Both checks read the file list from a shell variable that does not survive between the run's commands, so the list arrived empty: the documentation pass was never told which files were mandatory, and the diff check compared against nothing. The read is now a single command that prints the file list, so the run reads it from the command's output and both checks see the files the issue named. A read that fails — the issue body could not be fetched, or the list could not be extracted — now stops the run with a recorded reason instead of being treated as "no files were named". Cloud installations should re-run the installer with the new tag rather than bumping `prflow_version` alone; taking only one half stops the documentation gate rather than silently skipping it — see [Cloud Updates](/docs/runs/cloud/updates). [#1554](https://github.com/The01Geek/prflow/issues/1554)

## August 9, 2026

- **Your prompt extensions are now fetched unconditionally, and an implementation run records what it resolved.** The August 5 change delivered `.prflow/prompt-extensions/<skill>.md` as prompt text prepared before the run starts, and demoted the older in-run load to a fallback taken only when that preparation had not delivered. On hosted runs the preparation is refused silently, and a run could then skip the fallback and complete having applied none of your policy — reporting success with nothing to distinguish it from a run that had applied all of it. Both channels now run every time, at all four skills that consume an extension: `/prflow:review`, `/prflow:review-and-fix` (its own extension and `receiving-code-review.md`), `/prflow:implement` and `/prflow:pr-description`. There is no longer a condition a run can decline to evaluate, and where both channels deliver they carry the same content. A `/prflow:implement` workpad's Progress checklist also gains one `prompt extension resolved: …` row per extension the run consumes, written whether or not the run cooperates; an unticked row is that run's own record that it did not establish that extension's state. A workpad created before this change has the rows repaired in on the next run that resumes it. [#1462](https://github.com/The01Geek/prflow/issues/1462)

## August 8, 2026

- **`/prflow:create-issue` no longer stumbles through its pre-filing audit.** The audit step follows a documented order of operations, and that order left out two steps the audit itself requires: reading the round's kind that the dispatch will not accept without, and recording the staged draft write the dispatch depends on. A run following the written order was therefore turned away — twice per round on the file arm a clean run takes — and had to recover before it could continue, which showed up as wasted turns and stray error output during issue creation. The written order now names those steps, and presents the final review-and-create steps in the order they actually run. No behavior of the audit changed — only the instructions the run follows, which now match it. [#1466](https://github.com/The01Geek/prflow/issues/1466)

## August 7, 2026

- **`/prflow:review-and-fix` no longer re-raises a finding the previous pass already recorded.** Before it approves, the fix loop runs one more independent review and compares those findings against the pass before it. A finding that names a whole file rather than a specific line range — the form used when a defect has no single location, such as a missing test file — was compared under a narrower rule than the review engine's own, so it read as brand new even when the previous pass had already recorded it. That spent an extra fix iteration, and at the iteration cap it could reach you as `APPROVE WITH UNRESOLVED SHADOW FINDINGS` on a finding that was not new. The comparison now applies the engine's own matching rule instead of a restatement of it. The same change repairs a pointer in the loop's severity-calibration gate that named the wrong file for the definition it cites. [#1406](https://github.com/The01Geek/prflow/issues/1406)

## August 6, 2026

- **A review's progress checklist now shows whether the run actually delivered its verdict.** The checklist gains a final item, *Run complete — everything this run owed*. On `/prflow:review` it is ticked only after the verdict reaches a durable channel — the formal GitHub review, or a marked comment when the review could not be posted. Previously a run could finish aggregating a verdict, tick its last item, show a finished status, and then deliver nothing, leaving a checklist that read complete either way. Such a run now leaves that item unticked and states why, and it makes one bounded attempt to complete the missing delivery before it ends. On `/prflow:review-and-fix`, which posts no verdict to GitHub, the item is ticked when the fix loop reaches its terminal work. A ticked item means a durable verdict exists; it does not by itself mean the pull request carries an approve or request-changes merge signal. [#1367](https://github.com/The01Geek/prflow/issues/1367)

## August 5, 2026

- **Your prompt extensions now reach review and implementation runs every time.** `.prflow/prompt-extensions/review.md`, `review-and-fix.md`, `receiving-code-review.md` and `implement.md` are delivered to the agent as prompt text prepared before the run starts, instead of depending on the agent choosing to load them mid-run. Previously the extension reached the agent in only 8 of 18 sampled review runs and 1 of 4 sampled implementation runs, and a run that never loaded your policy still posted an ordinary verdict, so nothing distinguished it from one that had. If an extension cannot be delivered, the run now says so explicitly rather than proceeding as though you had configured none. An absent or empty extension is still a silent no-op. Cloud installations should re-run the installer with the new tag rather than bumping `prflow_version` alone — see [Cloud Updates](/docs/runs/cloud/updates). [#1264](https://github.com/The01Geek/prflow/issues/1264)
- **`/prflow:create-issue` now writes a short implementer brief and keeps the investigation detail in a separate comment.** The issue body carries only what an implementer needs to build the change — what is broken, what "done" looks like, which files to start in, which hazards matter. Rejected designs, supporting evidence, deliberation and lower-severity notes are posted as a separate investigation-record comment on the same issue (with any workflow-trigger tokens neutralized so it cannot start a run). Set the new `create_issue.investigation_record_enabled` config key to `false` to skip posting that comment; the brief-versus-record sorting is unchanged either way. [#1331](https://github.com/The01Geek/prflow/issues/1331)
- **Cloud review comments now use a safer event boundary.** Post `/prflow:review` on the pull-request conversation tab. Commands entered in the review-submission box or an inline diff comment no longer start a run. Cloud jobs also check out the repository's default branch before they read trusted configuration. [#1163](https://github.com/The01Geek/prflow/issues/1163)

## August 3, 2026

- **Numerical acceptance criteria now name their measurement.** PRFlow records the exact command or counting rule behind a threshold. If it cannot establish that measurement, it labels the criterion as unestablished instead of presenting an ambiguous number. [#1223](https://github.com/The01Geek/prflow/issues/1223)

## July 29, 2026

- **Automatic pull-request-triggered review is withheld from fresh installations.** New installs do not receive `devflow-review.yml`, `devflow-runner.yml` or `telemetry-push.yml`. Manual collaborator-triggered `/prflow:review` remains supported. Repositories that retain the earlier tier should follow [Cloud-Run Problems](/docs/troubleshooting/cloud-runs) to remove it safely, including its required branch-protection check. [#936](https://github.com/The01Geek/prflow/issues/936)

## July 28, 2026

- **The legacy automatic reviewer reads prompt extensions and its PRFlow version from the trusted base branch.** This prevents the pull request under review from supplying those instructions. Upgrade both the installed workflow and `prflow_version` together if an older repository still uses this tier. [#892](https://github.com/The01Geek/prflow/issues/892)

## July 26, 2026

- **Resumed implementation runs check existing feature-branch commits before a merge or push.** PRFlow uses the issue workpad or a linked pull request from the same repository to confirm that earlier commits belong to the run. Unclear or unrelated history stops the run without changing the branch. [#780](https://github.com/The01Geek/prflow/issues/780)

## July 25, 2026

- **Implementation runs now check broad coverage claims before committing.** Claims such as “every call site” must be backed by an executed enumeration, narrowed to the verified scope or removed. This reduces documented falsehoods that would otherwise reach review. [#818](https://github.com/The01Geek/prflow/issues/818)
- **Cloud runs now wait for background reviews to finish.** Starting a review no longer counts as receiving its result. Re-run the cloud installer and advance `prflow_version` together to receive both parts of the fix. [#801](https://github.com/The01Geek/prflow/issues/801)
- **Workpad updates are quieter.** `workpad.py update` no longer prints the full workpad body by default. It reports the updated comment on standard error, while `--print-body` restores the earlier output when an external integration needs it. [#814](https://github.com/The01Geek/prflow/issues/814)

## July 24, 2026

- **Resumed implementation runs now reconcile with the base branch.** The base-update checkpoint runs for new, adopted and resumed branches. PRFlow refuses to publish or report completion when the final checkpoint cannot establish a clean result. [#779](https://github.com/The01Geek/prflow/issues/779)

## July 21, 2026

- **Cloud writer commits can use the triggering person's identity.** Set `prflow.attribute_commits_to_triggerer` to `true` to opt in. The setting applies only to verified human accounts, needs no new credential and takes effect after it reaches the default branch. [#683](https://github.com/The01Geek/prflow/issues/683)
- **Direct code-review reception now records which content it reviewed.** PRFlow links each finding decision to that recorded content. If the environment cannot create the record, it reports the limitation. [#668](https://github.com/The01Geek/prflow/issues/668)

## July 20, 2026

- **Review telemetry now records requested and applied effort for each reviewer.** It also records why PRFlow used a fallback. This does not change review behavior. [#630](https://github.com/The01Geek/prflow/issues/630)
- **Self-hosted Windows git setup is now opt-in.** The `setup.git_dir_pin` and `setup.git_work_tree_pin` settings address specific runner startup problems but have important working-directory and plugin-installation costs. Leave both off unless the [runner guide](/docs/runs/cloud/runners) matches your environment. [#643](https://github.com/The01Geek/prflow/issues/643), [#645](https://github.com/The01Geek/prflow/issues/645)

## July 19, 2026

- **Self-hosted Windows runners can use a preinstalled Claude Code executable.** Set `setup.claude_code_executable` to its path because the bundled installer does not support Windows. PRFlow can send jobs to non-Linux runners, but those environments are not certified. Run a complete smoke test first. [#604](https://github.com/The01Geek/prflow/issues/604)

## July 17, 2026

- **Issue-creation recommendations now carry structured evidence.** PRFlow records what it established about consumers, execution paths, lifecycle, migration and coupled tests or docs before recommending an approach. Unestablished evidence remains visible when you review the draft. [#570](https://github.com/The01Geek/prflow/issues/570)

## July 16, 2026

- **Issue creation now rechecks the exact draft before filing it.** A revised draft cannot rely on the check of an earlier version. If the normal checker is unavailable, PRFlow labels the reduced single-pass check. [#552](https://github.com/The01Geek/prflow/issues/552)
- **Direct code-review reception now checks its subject before editing.** PRFlow reports the pull request, branch, checkout, freshness, linked issues, configuration and scope. It labels missing facts. A confirmed checkout mismatch or ambiguous subject blocks edits. [#549](https://github.com/The01Geek/prflow/issues/549)

## July 15, 2026

- **Weekly retrospectives skip model analysis for informational-only notes.** Informational notes remain in the learning record. Actionable notes still receive the full analysis. Missing severity data keeps the earlier, more conservative behavior. [#519](https://github.com/The01Geek/prflow/issues/519)

## July 14, 2026

- **Shadow review now checks which instructions each reviewer received.** It reports missing planned reviewers or unexpected instructions with the review result. Real findings remain visible. [#509](https://github.com/The01Geek/prflow/issues/509)

## July 13, 2026

- **Issue drafts now reconcile repeated state descriptions.** When a draft describes the same statuses or outcomes in a summary, table and detailed criteria, PRFlow checks that the forms agree before presenting the draft. [#471](https://github.com/The01Geek/prflow/issues/471)
- **The legacy automatic reviewer remembers cleared stale-number findings.** A later run on the same pull request lowers the severity of the same cleared match instead of blocking again. If the comparison cannot run, PRFlow keeps the configured severity. [#466](https://github.com/The01Geek/prflow/issues/466)

## July 10, 2026

- **The legacy automatic reviewer can recover from an early run ending without a verdict.** A bounded backstop posts a fresh `/prflow:review` request when configured. It stops after the configured attempt limit and reports failure instead of retrying forever. [#410](https://github.com/The01Geek/prflow/issues/410)

## July 9, 2026

- **The legacy automatic reviewer ignores superseded CI runs.** It considers the latest run for each workflow and event, so an older cancelled or failed attempt cannot keep a newer green commit deferred. Manual-approval waits receive a distinct reason. [#352](https://github.com/The01Geek/prflow/issues/352)

## July 8, 2026

- **Cloud runs now place execution diagnostics in the job log and run summary.** The read-only report includes duration, cost, turn count and permission-denial information when available. Disable it with `prflow.execution_diagnostics_enabled: false`. [#337](https://github.com/The01Geek/prflow/issues/337)
- **Unsupported Python versions now produce a clear error.** Helpers report the detected version, the Python 3.11 or newer requirement and the installation or shim remedy instead of an opaque traceback. [#343](https://github.com/The01Geek/prflow/issues/343)

## July 7, 2026

- **The legacy automatic reviewer reuses its waiting status.** Repeated evaluations of the same reason update the existing neutral check instead of adding duplicates. If PRFlow cannot establish the required state, it keeps the review waiting. [#325](https://github.com/The01Geek/prflow/issues/325)
- **The legacy automatic reviewer responds to commit-status-only CI.** A successful status from systems such as classic Jenkins can re-evaluate a deferred review without a manual rerun. [#335](https://github.com/The01Geek/prflow/issues/335)

## July 4, 2026

- **The legacy automatic reviewer can wait for an up-to-date branch and green CI.** The retained `prflow_review.require_up_to_date` and `prflow_review.require_ci_green` settings control those preconditions. This tier is not present in fresh installations. [#307](https://github.com/The01Geek/prflow/issues/307)
- **Issue creation now stress-tests its draft before asking for approval.** PRFlow checks load-bearing claims, repository references, edge cases and acceptance criteria, then revises the draft before presenting it. [#307](https://github.com/The01Geek/prflow/issues/307)
- **Cloud runs can use an Anthropic-compatible provider.** Configure a named `providers` entry, route each active workflow section to it and store the credential in `DEVFLOW_PROVIDER_API_KEY`. Unconfigured sections continue to use the default Anthropic OAuth path. [#315](https://github.com/The01Geek/prflow/issues/315)

## July 3, 2026

- **Safety checks now work on non-Claude coding clients.** PRFlow's portable helper calls no longer lose values between shell statements, which restores warnings and fail-safe branches on compatible clients. [#286](https://github.com/The01Geek/prflow/issues/286)
- **Cloud stall recovery refreshes expired GitHub App tokens.** Authentication or API failures stop with a clear error and do not spend a resume attempt. [#287](https://github.com/The01Geek/prflow/issues/287)
- **Reviews can use a separate GitHub identity.** Configure the review App credentials to avoid a review posting under the same identity that authored the pull request; otherwise the workflow falls back to `github-actions[bot]`. [#303](https://github.com/The01Geek/prflow/issues/303)
- **Implementation workpads now link to the current resumed run.** A retry updates the run link, and a cloud-created draft pull request links back to the run that created it. [#302](https://github.com/The01Geek/prflow/issues/302)
- **Local skills now find configuration from repository subdirectories.** PRFlow anchors `.prflow/` to the nearest Git root. Nested repositories and layouts that intentionally store configuration elsewhere remain outside that behavior. [#299](https://github.com/The01Geek/prflow/issues/299)

## July 2, 2026

- **Cloud stall recovery now fails clearly on an unreadable workpad status.** It no longer treats a missing or unknown status as healthy progress or spends a resume attempt on a workpad it cannot interpret. [#283](https://github.com/The01Geek/prflow/issues/283)
