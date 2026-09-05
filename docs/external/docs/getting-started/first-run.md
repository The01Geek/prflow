---
title: "First Run"
description: "Walk through one PRFlow run, from a GitHub issue to a review-ready pull request."
---

Follow one complete run and learn to read the progress workpad PRFlow writes while it works.

## Before You Start

Confirm all of the following:

- Your current directory is inside the Git repository you want to change.
- The GitHub repository you want to work in is the `origin` remote.
- `gh auth status` succeeds for an identity that can read the issue and create issue comments, branches and pull requests.
- The repository's tests and linters run from your local environment.
- The issue you plan to use has a clear outcome and acceptance criteria someone could check.

[Initialization](/docs/getting-started/initialization) is not a prerequisite. Local runs work on built-in defaults with no `.prflow/config.json`.

## The Walkthrough

<Steps>
  <Step title="Create or Pick an Issue">
    Skip this step if a suitable issue already exists. Otherwise describe the change in one sentence:

    ```text
    /prflow:create-issue Add an option to retain completed run logs for 30 days
    ```

    PRFlow asks about anything the description leaves undecided, saves the issue draft to a file and shows you its path (printing the full draft in chat only on request), and creates the issue only after you approve that draft. Note the issue number it reports.

    See [Create Issue](/docs/workflows/create-issue) for the full workflow.
  </Step>

  <Step title="Run Implementation">
    Pass the issue number:

    ```text
    /prflow:implement 123
    ```

    PRFlow reads the issue, creates a feature branch, posts a workpad comment on the issue, plans the change, writes it, runs your repository's verification commands, reviews the diff and updates documentation.

    Expect this to take a while. Every step reports into the workpad as it happens, so you can follow along on the issue page.
  </Step>

  <Step title="Read the Workpad on the Issue">
    Open the issue in GitHub. PRFlow keeps one comment there and edits it in place for the whole run, so it always shows the current state rather than a history you have to scroll.

    It looks like this, abridged:

    ```markdown
    # PRFlow Workpad — Issue #123

    **Status:** 🚀 Reviewing
    **Branch:** `issue-123-add-an-option-to-retain-completed-run-logs-for-30`
    **Run:** _(local run)_
    **PR:** https://github.com/your-org/your-repo/pull/456
    **Last updated:** 2026-08-26 14:07 UTC

    ## Progress
    - [x] **Setup** — branch & workpad
      - 13:42:11 — /prflow:implement run started
    - [x] **Implement**
      - [x] code + sweeps
    - [ ] **Review**
      - [x] `/simplify`
      - [ ] `review-and-fix`
      - [ ] acceptance-criteria gate
    - [ ] **Documentation**
    - [ ] **PR marked ready**

    ## Plan
    - [x] Add the retention setting and its default
    - [ ] Expire logs past the retention window
    - [ ] Cover both in tests

    ## Acceptance Criteria
    - [x] The retention window is configurable
    - [ ] Logs older than the window are removed

    ## PRFlow Reflections
    ```

    The header fields tell you where the work lives. **Status** is the current phase. **Branch** is the branch PRFlow created or adopted. **Run** links to the cloud run, or reads `_(local run)_` when you started it yourself. **PR** reads `_not yet created_` until the pull request exists, then holds its link. **Last updated** is the time of the most recent edit, in UTC.

    The **Progress** checklist has one top-level row per phase, with sub-rows beneath. Notes are timestamped and nest under the phase they belong to. **Plan** and **Acceptance Criteria** start as placeholders and fill in once PRFlow has read the issue and planned the work.

    **PRFlow Reflections** collects anything PRFlow wants a human to know: a limitation it hit, work it deferred, an assumption it had to make. Read it before you review the code. (The section reader also still accepts the older `Devflow Reflection` heading, so a workpad written before the rename stays readable.)
  </Step>

  <Step title="Review and Merge">
    Read the code, the tests, the documentation changes and the acceptance-criteria evidence, plus any reflections. Run a [standalone review](/docs/workflows/review) when you want a second, independent verdict.

    Then merge the pull request through your repository's normal human review and branch-protection process.
  </Step>
</Steps>

<Warning>
  PRFlow never merges the pull request and never approves its own work. The merge decision is always yours.
</Warning>

## Reading the Status Glyph

Every status word carries a glyph, so you can tell the state of a run at a glance without reading the word.

| **Glyph** | **Meaning** | **Status Words** |
| --- | --- | --- |
| 🚀 | Running | Setup, Discovering, Reproducing, Planning, Implementing, Reviewing, Documenting |
| 🎉 | Finished | Complete |
| 👎 | Stopped and waiting for you | Blocked |
| 💥 | A cloud run died | Failed |
| 🛑 | A cloud run was cancelled | Cancelled |

A local run you start yourself never writes `Failed` or `Cancelled`. Those two are written for cloud runs that ended without reaching a decision of their own.

## What a Run Produces

- **A branch** named `issue-<number>-<title-slug>`. PRFlow adds a date suffix when the plain name is already taken. A resumed run can adopt the head branch of an existing open pull request instead of creating one.
- **A workpad**, which is the single issue comment shown above.
- **A pull request**, opened as a draft during review. By default PRFlow publishes it as ready for review once verification, review and documentation finish. A repository can set `implement_pr_state` to `draft` to leave it unpublished. See [Implementation Settings](/docs/configuration/implementation).

## When a Run Reports Blocked

`👎 Blocked` means PRFlow stopped on purpose because something needs a human. It is not a crash. Common causes are a dependency that is missing, an acceptance criterion the change cannot satisfy, a verification command that fails or will not run and a repository state PRFlow refuses to work around, such as an unpushed branch tip.

Do this:

1. Read the `PRFlow Reflections` section. The reason is recorded there, along with what PRFlow observed.
2. Fix that specific cause. Install the tool, correct the acceptance criterion, repair the failing test or resolve the repository state.
3. Run `/prflow:implement 123` again with the same issue number.

PRFlow resumes from the latest workpad and the last pushed commit on the branch. Anything it did after that last push may be repeated. A re-run on a blocked workpad surfaces the recorded reason and pauses for your confirmation before it continues, so an automated retry cannot run straight past the gate that stopped the previous run.

See [Workpads and Resume](/docs/concepts/workpads-and-resume) for how resume decides what to redo, and [Implementation Troubleshooting](/docs/troubleshooting/implementation) for specific blocked causes.

## Next Steps

<CardGroup cols={2}>
  <Card title="The PRFlow Lifecycle" icon="timeline" href="/docs/concepts/lifecycle">
    The complete sequence a run follows, phase by phase.
  </Card>
  <Card title="Review Workflow" icon="magnifying-glass" href="/docs/workflows/review">
    Ask for an independent verdict on a pull request or branch.
  </Card>
  <Card title="Human Control" icon="user-shield" href="/docs/concepts/human-control">
    Where you approve, and what PRFlow will never decide for you.
  </Card>
  <Card title="Configuration" icon="sliders" href="/docs/configuration/index">
    Adjust verification, review and documentation behavior.
  </Card>
</CardGroup>
