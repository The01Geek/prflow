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
    The run prints a report, links the state pull request and lists every issue it filed. Everything after that is yours to decide.
  </Step>
</Steps>

<Warning>
  This workflow changes your local checkout. It requires a clean working tree, may switch you to `main`, writes learning records, opens or updates a pull request and creates GitHub issues. Commit or stash your work before running it. A non-empty `git status` stops the run rather than proceeding.
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

Below that, sections appear only when they have content: the patterns found this run, patterns that regressed after being fixed, the filing queue, patterns a cap withheld, issues filed, patterns skipped by cooldown and any blockers.

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

A pattern with missing evidence is withheld rather than filed on a guess, and the report names which cap withheld what, so a withheld pattern is visible rather than silently dropped.

Each filed issue proposes the smallest change that could stop the problem happening again.

## The State Pull Request

PRFlow opens or updates a separate pull request holding the retrospective records, then returns to `main` before it files any issues.

Review that pull request and merge it yourself once continuous integration passes. PRFlow never merges it.

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

**It waits for the previous state pull request to merge.** Before running, an enabled run checks for an open `devflow/learnings-*` state pull request. When one is still open, it skips the retrospective and instead ensures exactly one open reminder issue asking a maintainer to merge that state pull request and re-dispatch the workflow. This keeps the scheduled loop from stacking un-merged learning records. With no open state pull request, the run proceeds normally.

## Where Humans Decide

<Note>
  The retrospective loop does not edit product code, does not implement the issues it proposes and does not merge any pull request. It proposes; you triage.
</Note>

Pick the findings worth acting on and run them through the normal [Implement](/docs/workflows/implement) and [Review](/docs/workflows/review) workflows. The loop never starts that for you.

Re-running is safe. The next run processes only pull requests it has not already recorded, and it does not refile a pattern it already filed this cycle.

## Related Articles

- [Create an Issue](/docs/workflows/create-issue)
- [Implement an Issue](/docs/workflows/implement)
- [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives)
- [Glossary](/docs/reference/glossary)
