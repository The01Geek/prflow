---
title: "Glossary"
description: "Look up any term PRFlow prints in its output, in plain language."
---

Use this glossary to read PRFlow's own output without knowing how the product is built.

**Acceptance criteria**: Testable statements in an issue that define when the requested outcome is complete. PRFlow reads a criterion only when it is written as a markdown checkbox row.

**APPROVE**: The clean verdict. The review found nothing that blocks the merge and verified its own coverage.

**APPROVE with notes**: Nothing blocked the merge, and the review still reported findings that sat below the line where a finding causes a rejection.

**APPROVE WITH ADVISORY NOTES**: The review-and-fix loop approved the change and parked one or more findings for a person to judge instead of fixing them.

**APPROVE WITH CAVEAT**: The review approved the change and could not confirm how much of its own checking actually ran. Read it as approved with unknown coverage.

**APPROVE WITH UNRESOLVED SHADOW FINDINGS**: The review-and-fix loop converged, and its final independent pass then surfaced findings it had no iterations left to address. Read it as approved with known, unaddressed work, listed in the report.

**Base branch**: The repository branch a feature branch or pull request is compared with, such as `main`.

**Blocked**: This word means two different things. In an issue, a `🚫 Blocked` section lists unresolved decisions that must be settled before anyone implements the issue. As a run outcome, Blocked means the run stopped on purpose without finishing and recorded why.

**Checkpoint**: A commit and push a run makes at a step boundary so that an interrupted run loses only the work done since the last one.

**Cloud run**: A supported PRFlow command executed by repository automation after an authorized GitHub comment.

**Deferred finding**: A verified review concern that is intentionally not fixed in the current pull request and is disclosed with a follow-up record.

**Draft pull request**: A pull request that is open but not yet published as ready for review.

**Effort**: How much reasoning the model is asked to spend on a run. The accepted values are `low`, `medium`, `high`, `xhigh` and `max`, set per configuration section.

**Feature branch**: The branch that holds the commits for one issue or pull request.

**Finding severity**: The grade a review agent gives a finding: Critical, Important, Suggestion or Informational. Only Informational never affects the verdict.

**Formal review**: A GitHub pull request review that records an approval, comment or request for changes. A comment review is a durable report but creates no approval or request-changes merge signal.

**Human merge boundary**: The rule that PRFlow prepares and reviews pull requests, and a person owns the final merge decision.

**Investigation record**: A separate comment PRFlow posts on an issue it creates, holding the investigation behind the issue — rejected designs, confirmatory evidence and deliberation — so the issue body carries only what an implementer needs.

**Iteration**: One pass of the review-and-fix loop: review, fix what qualifies, then review again.

**Local run**: A PRFlow skill executed in the user's active Claude Code session.

**Post-merge verification**: An acceptance check that requires a deployed or otherwise genuinely live environment, and so must run after merge.

**Preflight**: The dependency check that confirms working `git`, `gh`, `jq` and Python 3.11 or newer. Initialization runs it for you, and its output keeps the older `devflow` spelling.

**PRFlow**: A plugin that prepares documented pull requests with verification and review evidence for human evaluation.

**Progress comment**: The comment a review keeps up to date on the pull request while it works. It is edited in place, so a superseded verdict disappears from it. It is the review's equivalent of the workpad.

**Skill extension**: A markdown file under `.prflow/skill-extensions/` that adds your repository's own policy to one skill's instructions. See [Skill Extensions](/docs/configuration/skill-extensions).

**Provenance label**: The label `PRFlow`, applied to every issue and pull request PRFlow creates so later runs can recognize their own work. The older `DevFlow` spelling is still recognized.

**Ready for review**: A pull request state that tells reviewers the authoring workflow is complete. It does not mean the pull request has been approved or merged.

**Reflection**: A short durable note a run writes on the workpad about friction it hit, a stop it made or a problem with the issue itself. The workpad heading is `PRFlow Reflections`; the section reader also still accepts the older `Devflow Reflection` spelling, so records written before the rename stay readable.

**REJECT**: The blocking verdict. At least one checklist item failed or was inconclusive, or a finding reached the severity that blocks a merge, or the change's own diff added a line that is untrue.

**Review agent**: One of the nine subagents the review engine dispatches, each looking for a different class of problem — project guidelines, comment accuracy, test coverage, silent failures and type design among them.

**Review-and-fix loop**: A bounded cycle that reviews a candidate, verifies findings, commits authorized fixes and reviews the result again. It stops after five iterations by default, and reports its latest verdict when it does.

**Run status**: The single word on a workpad saying where a run is. In order: Setup, Discovering, Reproducing, Planning, Implementing, Reviewing, Documenting, then Complete. Blocked, Failed and Cancelled are the ways a run ends early. Each word carries a glyph — 🚀 for any status still running, 🎉 Complete, 👎 Blocked, 💥 Failed and 🛑 Cancelled.

**Scope-acknowledged finding**: A review finding deliberately left unfixed in this pull request and recorded in the pull-request body with a follow-up issue, so the next review reports it as informational instead of rejecting the change again.

**Shadow review**: A separate review pass that looks for significant findings the primary review-and-fix loop missed. It reports whether its coverage was verified, and it cannot prove that every defect was found. When it raises findings the loop cannot resolve within its iteration cap, the verdict says so.

**State pull request**: A pull request containing retrospective learning records instead of product-code changes. A person reviews and merges it.

**Telemetry branch**: A long-lived branch, `prflow-telemetry` by default, that holds per-run efficiency records rather than product code. A fresh cloud installation does not receive the workflow that pushes to it.

**Verdict**: The review's overall answer about a pull request, and the thing that decides whether a merge is blocked. It is one of the APPROVE forms above, or REJECT.

**Verification checklist**: The list of checkable claims the review engine derives from the diff before it dispatches its agents. Each item resolves to PASS, FAIL or INCONCLUSIVE, and anything other than PASS causes a REJECT.

**Workpad**: The single GitHub issue comment that records an implementation run's branch, status, plan, progress, acceptance criteria and important recovery notes.

## Related Articles

- [Command Reference](/docs/reference/command-reference)
- [Workflows](/docs/workflows/index)
- [Review System](/docs/concepts/review-system)
- [Troubleshooting](/docs/troubleshooting/index)
