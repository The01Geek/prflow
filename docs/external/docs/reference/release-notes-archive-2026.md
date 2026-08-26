---
title: "Release Notes Archive (2026)"
description: "Older user-visible PRFlow changes, kept verbatim as a historical record."
---

Older PRFlow release notes, moved here from the [release notes](/release-notes) page. Entries are kept verbatim as a historical record. For the complete change history, see [GitHub Releases](https://github.com/The01Geek/prflow/releases).

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
