---
title: "Weekly Retrospective"
description: "Turn recurring delivery problems from merged pull requests into a small number of issues for human triage."
---

Use this workflow when you want PRFlow to learn from what it already shipped.

It reads recently merged pull requests, records what went well or badly, looks for patterns that repeat and proposes a bounded number of GitHub issues for a human to triage. It never edits product code and never merges anything.

## Run It

<Steps>
  <Step title="Start from a clean tree on main">
    ```text
    /prflow:retrospective-weekly
    ```

    This is a local command. It is not available as a GitHub comment command. You can also run the same loop on a weekly schedule with the shipped GitHub Actions workflow — see [Run It On A Schedule](#run-it-on-a-schedule) below.
  </Step>
  <Step title="Let the preflight checks pass">
    The run confirms the working tree is clean, that the GitHub CLI is authenticated and that `main` is checked out. It switches to `main` itself when needed.
  </Step>
  <Step title="Read the report and triage">
    The run prints its full report and lists every issue it filed. Everything after that is yours to decide.
  </Step>
</Steps>

<Warning>
  This workflow changes your local checkout. It requires a clean working tree (changes under `.prflow/learnings/` are ignored), may switch you to `main`, writes learning records to the telemetry branch and creates GitHub issues. Commit or stash your work before running it. Any other change in `git status` stops the run rather than proceeding.
</Warning>

### What You Get Back

The report opens with a summary of the scan. For example:

```markdown
# DevFlow Weekly Report

**Run finished:** 2026-08-26T09:41:07Z

## Summary
PRs scanned: 12
clean (no analysis): 8
analyzed: 4
skipped: 0
```

Below that, sections appear only when they have content: the patterns found this run, patterns that regressed after being fixed, the filing queue, patterns a cap withheld, the scan-window notes, issues filed, patterns skipped by cooldown and any blockers.

<Note>
  The report still carries the product's former name in its heading. It is the same report. See [Migrate From DevFlow](/docs/getting-started/migrate-from-devflow).
</Note>

When there is nothing new, the run says so and stops:

```text
Nothing to process — no unprocessed watched-author PRs in the last 7 days.
```

## What It Scans

The weekly scan finds pull requests by the watched authors that merged in the last seven days and are not already recorded as processed. A pull request with no signal worth analyzing gets a short clean entry. The rest get a bounded analysis.

PRFlow then writes the results to its learning records and derives the patterns that recur across them.

<Tip>
  To re-run the loop over a specific set of pull requests — backfilling old ones, or re-checking after a fix — pass `--prs` with a comma-separated list instead of using the rolling seven-day window. Everything downstream behaves identically.
</Tip>

## Filing Is Deliberately Bounded

A learning loop that files freely produces a backlog nobody reads. Five settings keep the volume down:

| Setting | Default | Limits |
| --- | --- | --- |
| `prflow_retrospective.min_occurrences` | 2 | How often a pattern must recur before it can be filed at all. |
| `prflow_retrospective.max_issues_per_run` | 3 | Issues filed in one run. |
| `prflow_retrospective.max_open_issues` | 10 | Open retrospective issues in total. |
| `prflow_retrospective.max_open_per_category` | 2 | Open retrospective issues in one category. |
| `prflow_retrospective.cooldown_days` | 3 | How long before the same pattern can be filed again. |

A run audits and files a pattern only when at least one of its occurrences merged at or after the earliest merge among the pull requests that run scanned, or when that comparison cannot be established.

A pattern with missing evidence is withheld rather than filed on a guess, and the report names which cap withheld what, so a withheld pattern is visible rather than silently dropped.

Each filed issue proposes the smallest change that could stop the problem happening again.

## Where The Records Live

PRFlow saves its learning records and each run's report to the telemetry branch before it files any issues and again at the end of the run. No pull request is opened and nothing needs merging. See [Run It On A Schedule](#run-it-on-a-schedule) for how saves, dismissals and the one-time move work.

## Run It On A Schedule

The same loop can run unattended on GitHub Actions. PRFlow ships `devflow-retrospective.yml`, which runs `/prflow:retrospective-weekly` headlessly on two triggers:

- **Weekly cron** — every Sunday at 05:23 UTC.
- **Manual dispatch** — the workflow's *Run workflow* button (`workflow_dispatch`).

**It is disabled by default and opt-in.** The workflow runs only when the config key `workflows["prflow-retrospective"]` reads the JSON boolean `true` in your default branch's `.prflow/config.json`. Anything else — absent, `false`, or even the string `"true"` — leaves it off, so a fresh install never runs it until you opt in:

```json
{
  "workflows": {
    "prflow-retrospective": true
  }
}
```

The gate is read from the default branch, so enabling it takes effect once the change is merged to your default branch, not from a pull request.

**Its learning records live on the telemetry branch.** The retrospective keeps its records and reports under `.prflow/logs/learnings/` on the telemetry branch (default `prflow-telemetry`), not in your default branch, so a run opens no pull request and needs no merge. Each run copies the records into `.prflow/learnings/` (gitignored), works on that copy, and saves it back before filing issues and again at the end. A save never overwrites records someone else changed while the run was working: it refuses. When the save before filing does not land, refused or failed, the run files no issues and says why in its report; the end-of-run save's outcome is recorded in the run's outcome record, and when it lands it clears the earlier save's failure. Each run's report is saved as `.prflow/logs/learnings/reports/<run start, UTC>.md`, printed in the run's output, and appended to the job summary.

**Stop re-raising a pattern.** To stop a recurring pattern permanently, run `retro-helper.sh dismiss <pattern-key>` from your repository root (the vendored copy is `.prflow/vendor/prflow/scripts/retro-helper.sh`). It adds the key to the store's `dismissed` map on the telemetry branch.

**Moving an existing repository.** `/prflow:init` and `install.sh --apply` copy learning records still tracked under `.prflow/learnings/` to the telemetry branch, then stage their removal from your default branch and add `/learnings/` to `.prflow/.gitignore` for you to commit. If the telemetry branch already holds records and a tracked file differs from them, or a tracked file has uncommitted changes, the copy stops, stages nothing and names the file, so reconcile them and re-run. Merge or close any open `prflow/learnings-*` pull request first: while one is open, the copy stops and names it, and so does a run that finds no store on the telemetry branch.

**A failed delivery now fails the job.** The scheduled run records the outcome of each delivery step it must perform — saving the learning records, filing each selected issue, and saving the report — and a final check runs after the agent regardless of whether the agent step itself succeeded, failed or was cancelled. A delivery step that positively failed (for example a save that could not authenticate, or a selected issue whose filing errored) fails the workflow with the operation and cause named, so a run that lost state or filed nothing can no longer conclude success. When the outcome record is missing or unreadable the run emits a warning rather than failing, and never invents a failure it did not observe. A quiet week with no new pull requests stays green, as does a week with nothing to file whose saves succeeded. If the agent stopped before recording an outcome, the check reads GitHub: no commit on the telemetry branch saving the records or the report since the run started fails the job, and an unreadable GitHub leaves a warning. This gate is active only once the scheduled workflow and the vendored engine are upgraded together; an older vendored engine paired with this workflow stops before launching, with a message telling you to bump `prflow_version`.

**Every run keeps a copy of its learning records.** Whatever the outcome, including a failed save or a cancelled run, the workflow uploads `.prflow/learnings/` as the run artifact `retrospective-learnings-<run id>-<attempt>`, kept for 7 days.

<Note>
  Bump `prflow_version` and re-run `install.sh` in the same upgrade as the plugin. An older vendored engine under the new workflow cannot save its records (the workflow no longer grants the state pull request helper), and an older workflow under a newer engine skips every run with a "retrospective state guard not found" error.
</Note>

## Where Humans Decide

<Note>
  The retrospective loop does not edit product code, does not implement the issues it proposes and does not merge any pull request. It proposes; you triage.
</Note>

Pick the findings worth acting on and run them through the normal [Implement](/docs/workflows/implement) and [Review](/docs/workflows/review) workflows. The loop never starts that for you.

Re-running is safe. The next run processes only pull requests it has not already recorded, and it does not refile a pattern it already filed this cycle.

## Related Articles

- [Create an Issue](/docs/workflows/spec)
- [Implement an Issue](/docs/workflows/implement)
- [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives)
- [Glossary](/docs/reference/glossary)
