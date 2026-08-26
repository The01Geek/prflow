---
title: "Request a Review Automatically on Green CI"
description: "Add a workflow that posts a PRFlow review request as soon as your own CI passes on a pull request."
---

Get a PRFlow review without anyone typing a comment, by letting your own CI request it once it goes green.

A fresh installation does not review pull requests automatically. The supported way to make review hands-free is a small workflow you add to your repository. When your CI succeeds on a pull request, that workflow posts a `/prflow:review` comment on it, and the PRFlow workflow you already installed handles the rest.

## Before You Start

<Warning>
  **This workflow is safe only under the `pull_request` event. Never move it to `pull_request_target`.**

  `pull_request_target` makes your repository secrets available to runs started by pull requests from forks. Under that trigger, the same-repository check inside the workflow would be the only thing stopping a fork from minting your GitHub App token. Under `pull_request`, GitHub withholds secrets from fork runs no matter what, so the same-repository check is a second line of defense rather than the only one.
</Warning>

Three preconditions must be true before the workflow can request anything:

<AccordionGroup>
  <Accordion title="A GitHub App Must Be Configured">
    The workflow mints a downscoped token from the App you configured as `DEVFLOW_APP_ID` and `DEVFLOW_APP_PRIVATE_KEY`. Without those, the job's own condition is false and nothing is requested. See [Cloud Setup](/docs/runs/cloud/setup).
  </Accordion>
  <Accordion title="The App's Bot Login Must Be Allowed">
    The comment is posted by your App, so PRFlow sees a bot as the requester. Add that App's bot login, such as `your-app[bot]`, to `prflow.allowed_bots` in `.prflow/config.json`. The shipped default is `claude,dependabot`, which names no App, so a fresh install does not authorize yours.

    **Merge the `allowed_bots` change first.** PRFlow reads that setting from your default branch at the moment a comment arrives. Adding your App's login in the same pull request that adds this workflow has no effect on that pull request.
  </Accordion>
  <Accordion title="Your Installed Version Must Be Recent Enough">
    The helper this workflow calls first ships in `prflow_version` `2.30.18`. Pin at or above it. Below that version the workflow warns and requests no review rather than failing.
  </Accordion>
</AccordionGroup>

## Add the Workflow

<Steps>
  <Step title="Create the File">
    Add a new file at `.github/workflows/prflow-auto-review.yml` in your repository. Do not put this content into an existing PRFlow workflow file, because the installer manages those.
  </Step>
  <Step title="Paste the Workflow">
    Copy the file below exactly as it is.
  </Step>
  <Step title="Name Your Own CI Job">
    Change `needs: [ci]` to the name of the job, or jobs, that must pass first. This is the only line you are expected to edit.
  </Step>
  <Step title="Commit and Open a Pull Request">
    Commit the file, then open a pull request and let your CI run.
  </Step>
</Steps>

```yaml
# .github/workflows/prflow-auto-review.yml
# Requests a PRFlow /prflow:review automatically once your CI is green on a
# non-draft, same-repository pull request. Safe ONLY under `pull_request`
# (see the hard precondition above — never `pull_request_target`).
name: PRFlow auto-review request
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
permissions:
  contents: read
jobs:
  request-review:
    # Replace `ci` with YOUR own CI job(s). This `needs:` IS the success gate:
    # because the `if:` below uses no status function (`always()`, `!cancelled()`,
    # `success()`, `failure()`), GitHub skips this job unless every `needs:` job
    # succeeded. Adding one of those functions REMOVES that implicit gate — if you
    # do, add your own `needs.<job>.result == 'success'` clauses to the steps that
    # mint the token and post, or a red CI run will request a review.
    needs: [ci]
    # These five eligibility clauses are the safety gate. Do not edit them.
    if: >-
      github.event_name == 'pull_request' &&
      github.event.pull_request.draft == false &&
      github.event.pull_request.head.repo.full_name == github.repository &&
      github.actor != 'dependabot[bot]' &&
      vars.DEVFLOW_APP_ID != ''
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      # The helper lives under .prflow/vendor/prflow/, where the installer put
      # the plugin, and the vendor-plugin action re-materializes it at run time.
      # The sparse checkout names both scripts/ and lib/ because the helper reads
      # files from both.
      - uses: actions/checkout@v6
        with:
          persist-credentials: false
          sparse-checkout: |
            .github/actions/vendor-plugin
            .prflow/vendor/prflow/scripts
            .prflow/vendor/prflow/lib
      - name: Materialize the vendored PRFlow helper tree
        uses: ./.github/actions/vendor-plugin
      - name: Mint downscoped comment token
        id: app_token
        uses: actions/create-github-app-token@v3
        with:
          client-id: ${{ vars.DEVFLOW_APP_ID }}
          private-key: ${{ secrets.DEVFLOW_APP_PRIVATE_KEY }}
          permission-pull-requests: write
      - name: Request a PRFlow review for this head
        env:
          GH_TOKEN: ${{ steps.app_token.outputs.token }}
          PR: ${{ github.event.pull_request.number }}
          HEAD_SHA: ${{ github.event.pull_request.head.sha }}
          EXPECTED_AUTHOR: ${{ steps.app_token.outputs.app-slug }}
        run: |
          HELPER=.prflow/vendor/prflow/scripts/post-ci-review-trigger.sh
          # Absent-file breadcrumb: a consumer pinned below the version that
          # carries the helper gets a NAMED warning rather than an rc-127 red step.
          if [ ! -x "$HELPER" ]; then
            echo "::warning::PRFlow auto-review: helper not found at $HELPER — is prflow_version >= 2.30.18? Skipping (no review requested)."
            exit 0
          fi
          "$HELPER"
```

## What You Should See

Once your CI job finishes successfully on the pull request, the `PRFlow auto-review request` workflow runs. It posts a `/prflow:review` comment on the pull request, authored by your GitHub App. That comment then starts a normal PRFlow review, exactly as if a collaborator had typed it, and the review posts its progress comment on the same pull request.

Three outcomes tell you something went wrong instead:

- **The job was skipped.** One of the five conditions was false: the pull request is a draft, it comes from a fork, its author is `dependabot[bot]`, `DEVFLOW_APP_ID` is not set or your CI job did not succeed.
- **The step logged a warning about a missing helper.** Your installed `prflow_version` is below `2.30.18`. Update the installation. See [Cloud Updates](/docs/runs/cloud/updates).
- **The comment was posted but no review started.** The App's bot login is not in `prflow.allowed_bots` on your default branch. See [Cloud Triggers](/docs/runs/cloud/triggers).

## Where This Does Not Reach

<Warning>
  This mechanism can only wait on GitHub Actions jobs in the same workflow run. It does not reach CI that reports from outside Actions, such as CircleCI, Buildkite or a classic Jenkins commit status. A `needs:` entry cannot name those.
</Warning>

If your CI runs outside GitHub Actions, keep the manual path: a repository collaborator comments `/prflow:review` on the pull request.

## Two Refinements You May Want

PRFlow's own repository runs a slightly richer version of this job. Both additions are optional, and neither is in the file above:

- **Serialize concurrent runs at the same commit**, so two green CI runs on one head cannot request two reviews.
- **Supersede stale CI runs**, by adding a workflow-level `concurrency:` key to your own CI so an older run for a superseded head stops.

Add either one to your own workflow if you want it.

## Related Pages

<CardGroup cols={2}>
  <Card title="Cloud Setup" icon="key" href="/docs/runs/cloud/setup">
    Configure the GitHub App this workflow mints its token from.
  </Card>
  <Card title="Cloud Triggers" icon="comment" href="/docs/runs/cloud/triggers">
    The comment format and authorization rules the posted comment must satisfy.
  </Card>
  <Card title="Review System" icon="magnifying-glass" href="/docs/concepts/review-system">
    What the review itself does once it starts.
  </Card>
  <Card title="Security" icon="shield" href="/docs/concepts/security">
    The wider trust boundaries around cloud runs.
  </Card>
</CardGroup>
