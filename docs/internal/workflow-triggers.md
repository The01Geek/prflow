# PRFlow workflow trigger surface

How the PRFlow GitHub workflows decide *when* to run, *which* one runs, and how
duplicate `/prflow:implement` commands are collapsed. The codebase is the
source of truth — this doc records the *why*.

## Withheld from this release: the automatic pull-request-triggered review tier

**The automatic review on pull request is not shipped in this release.** A fresh
installation receives none of `.github/workflows/devflow-review.yml`,
`.github/workflows/devflow-runner.yml` or `.github/workflows/telemetry-push.yml`, and
`install.sh` no longer copies them.

**Why.** The tier's caller triggered on `pull_request`, `pull_request_target`, `check_run`,
`workflow_run`, `check_suite` and `status`, called a reusable workflow with
`secrets: inherit`, checked out the pull-request head, and carried no actor-authorization
gate. Two open defects describe the consequences and neither is close to landing:

- [**#930**](https://github.com/The01Geek/prflow/issues/930) — the `precheck` job
  performs a bare `actions/checkout`, which under the `pull_request` trigger resolves the
  pull request's merge ref. The config that decides whether a review runs at all therefore
  comes from the pull request under review, so "it defaults to off" is not a mitigation.
- [**#920**](https://github.com/The01Geek/prflow/issues/920) — blocked on #930.
  It is unknown whether the collaborator-permission API call succeeds under `precheck`'s
  `pull-requests: read` token, and a fork `pull_request` event receives a read-only
  `GITHUB_TOKEN` regardless of the `permissions:` block, so the job cannot post the required
  check and the context goes unreported.

**A repository collaborator commenting `/prflow:review` is the always-available review
path.** A repository collaborator with write, admin or maintain permission comments
`/prflow:review` on a pull request; `devflow.yml`'s `gate` job authorizes the actor
through `scripts/authorize-actor.sh`, and the review runs. **An outside fork
contributor cannot self-trigger a PRFlow review — a repository collaborator must post
the comment.** A consumer can *additionally* have that `/prflow:review` comment posted
**automatically once CI is green**, by copying the documented snippet in *Automatic
review request on green CI* below; the comment it posts is authorized by the same
`allowed_bots` gate. The collaborator comment remains the path for CI systems the
automatic snippet does not reach (see that section's coverage boundary).

**If you already installed the tier, you keep it.** `install.sh`'s
`prune_stale_devflow_workflows()` is deliberately not extended, so re-running the installer
leaves the three files in place and your auto-review keeps working. That continues to hold
across a plugin upgrade only because **every helper those workflows call is still shipped**
even though the withheld tier no longer reaches them (and, save `derive-review-verdict.sh` —
which the shipped dead-run verdict-presence gate reaches again, issue #1172 — nothing else in
PRFlow's own tree reaches them either): `install.sh` re-stamps
`prflow_version` to the installed commit, so re-running the installer keeps your workflow
files while vendoring a newer plugin, and a helper deleted as "unreachable" would go missing
underneath them — `finalize_check` fails **closed** when `derive-review-verdict.sh` is absent,
which would report every review `incomplete` and wedge every pull request behind a required
check that never reports, while an absent `derive-review-preconditions.sh` fails **open** and
silently drops the freshness and CI-green gates. That is why those helpers are retained rather
than swept. It also means such a repository **remains exposed to the #930 and #920 defects for
as long as `workflows["prflow-review"]` is `true` in its `.prflow/config.json`**.

**Every upgrade surfaces that exposure.** `install.sh` detects the three files and reports them,
naming issues #930 and #920 — it does not delete them, because in the repositories that adopted
the tier `Devflow Review` is a *required* status check, and deleting the workflow while a branch
protection rule still requires its context wedges every subsequent pull request behind a check
nothing will report. Removal is therefore an explicit opt-in, and step 3 below is a human action
no installer can perform:

1. Delete `.github/workflows/devflow-review.yml`, `.github/workflows/devflow-runner.yml`
   and `.github/workflows/telemetry-push.yml`.
2. Set `workflows["prflow-review"]` to `false` in `.prflow/config.json`.
3. Remove the `Devflow Review` context from any branch protection rule or ruleset that
   requires it — otherwise every subsequent pull request wedges against a required check
   that nothing will report.

Steps 1 and 2 are what `install.sh --apply --remove-withheld-review-tier` performs (signature-guarded,
so a same-named workflow of your own is never deleted); it prints step 3 rather than attempting it.
Preview the whole thing first — an upgrade is dry-run by default. Step 3 stays yours either way.

The removed caller's bytes are preserved on the `preserved/auto-review-tier` branch, whose
`PRESERVATION.md` records the `devflow-runner.yml` object ID it was cut against. Re-shipping
the tier is a **reconstruction against whatever that callee says at that later time**, not a
restore.

## Which workflow fires on what

| Workflow | Commands | Listens on |
|---|---|---|
| `devflow.yml` (light path) | `/prflow:review`, `/prflow:review-and-fix`, `/prflow:pr-description` | `issue_comment[created]` |
| `devflow-implement.yml` (heavy path) | `/prflow:implement` | `issue_comment[created]` |
| `ci.yml` — `auto_review_trigger` job **(repo-internal; `install.sh` does NOT ship it)** | posts `/prflow:review` automatically once CI is green on a non-draft same-repo pull request | `pull_request[opened, synchronize, reopened, ready_for_review]` (an automatic *producer* of the `/prflow:review` comment, not a listener for it; a consumer reproduces it with the documented snippet below — see *Automatic review request on green CI*) |
| `devflow-review.yml` **(withheld — see above; not shipped, still live in repositories that installed it)** | automated review | PR lifecycle + `check_run[rerequested]` + `workflow_run`/`check_suite` `[completed]` + `status` (CI-completion re-trigger for deferred reviews — `status` covers legacy commit-status-only CI, filtered to a green state; see the preconditions note in `DEVFLOW_SYSTEM_OVERVIEW.md` §14; the `workflow_run` `workflows:` list must name **every** first-party workflow that runs on PR events — the review waits on all of them but re-fires only on a listed one's completion, so a gating workflow omitted from the list can strand a deferred review, issue #579) |

**Both command namespaces are accepted in a comment.** The plugin was renamed
`devflow` → `prflow`, and each gate `if:` matches the transitional `/devflow:`
spelling alongside the canonical `/prflow:` one — so a comment reading
`/devflow:implement 42` fires exactly the same workflow as `/prflow:implement 42`.
The detected token is normalized to the canonical `/prflow:` form before any
consumer compares it. This dual acceptance is specific to the **cloud
comment-trigger** path: **local** slash commands are namespaced by the plugin
name, so `/devflow:*` does not resolve in Claude Code any more and only
`/prflow:*` does.

Both command listeners run `claude-code-action` in **agent mode** with a
synthesised prompt, so they need no `@claude` phrase. Every gate `if:` branch
also negates `@claude` and (for the light path) `/prflow:implement`, so a given
comment routes to exactly one listener and never collides with Anthropic's stock
`claude.yml`. This is the *partition invariant*, enforced by tests in
`lib/test/run.sh`.

**Both paths are `issue_comment`-only.** The light path's commands
(`/prflow:review` / `/prflow:pr-description`) still act on a pull request, but they
are requested by **commenting on the pull-request conversation** — which is an
`issue_comment` in GitHub's API — not from the review-submission box or an inline
diff comment. As of issue #1163 `devflow.yml` no longer subscribes to
`pull_request_review[submitted]` or `pull_request_review_comment[created]`: on those
events GITHUB_REF resolves to `refs/pull/N/merge`, so every job checked out
PR-author content (including the `config` job's authorization inputs and the agent's
tool grants), and the subscriptions were removed to close that accident class.
Requesting a review from the review-submission box or an inline diff comment
therefore no longer works; commenting `/prflow:review` on the PR conversation still
does. `devflow-implement.yml` was already `issue_comment`-only. Because a PR comment
is *also* an `issue_comment` in GitHub's API, the heavy path's gate `if:`
additionally requires
`github.event.issue.pull_request == null`, and `scripts/resolve-implement-trigger.sh`
re-checks via an `IS_PULL_REQUEST` signal and declines before authorization — so a
comment on a pull request never starts an implement run, whatever its body text.
This is what stops the weekly retrospective's audit-report comment (which quotes
the literal `/prflow:implement` phrase in prose) from self-triggering on the
state PR.

**The authorized comment sender becomes the created PR's assignee (issue #1165).** Because the implement trigger is an `issue_comment[created]` event, `github.event.sender.login` names the developer who requested the run. `devflow-implement.yml` propagates it to the writer as `DEVFLOW_TRIGGERING_USER`, and Phase 3.1.1 of the implement engine best-effort-assigns the newly-created draft PR to that login (a local run resolves `gh api user --jq .login` instead). Assignment is CREATE-only, fail-closed on identity (an empty sender substitutes no other account), and never gates the run — see [`docs/internal/cloud-setup.md`](cloud-setup.md) → *Assigning the created PR to the triggering user*.

`resolve-implement-trigger.sh` is **also markdown-aware** (issue #1032): it routes
through the shared `scripts/detect-standalone-command.sh` detector, so on an *issue*
comment a `/prflow:implement` token that is merely quoted in prose, blockquoted,
indented, or inside a fenced code block does **not** trigger — only a standalone
own-line command does. See the *"A light `/prflow:*` command fires only when
issued, never when quoted"* section below for the shared detector's exact
anchoring rules; the heavy path inherits them wholesale.

## Automatic review request on green CI (`ci.yml`), and shipping it to a consumer repository

PRFlow's own repository requests a `/prflow:review` automatically the moment CI is
green on a pull request, so the review it already expects before merge does not wait
on a human remembering to type the trigger. This lives in the `auto_review_trigger`
job of `.github/workflows/ci.yml`. **It is repo-internal: `install.sh`'s workflow copy
loop ships `devflow.yml` and `devflow-implement.yml` and NOT `ci.yml`**, so a consumer
repository does not receive it — the standing "a collaborator comments the trigger"
statement above stays literally true out of the box. A consumer that wants the same
automatic request copies the snippet below into their own CI.

**How the in-repo job behaves.** It fires on every green head, deduped only at an
identical head SHA via the marker `<!-- prflow:ci-review-trigger sha=<sha> -->` that
`scripts/post-ci-review-trigger.sh` posts and reads back. A prior comment suppresses
the request **only when this App itself authored it** — a human or another bot merely
quoting the marker no longer kills the review. This request-and-author-scoped-dedupe
core is exactly what the consumer snippet below reproduces. The in-repo job adds two
refinements the minimal snippet omits: concurrent runs at one head SHA are serialized
(`concurrency` group, `cancel-in-progress: false`) so the read-then-post dedupe is
atomic; and when a dependency (`test` or `lint`) concludes anything other than
`success`, the job posts nothing but emits a `::warning::` naming which dependency
withheld the request — `lint` is **not** a required status check, so such a pull
request is mergeable, and without the announcement its missing review would be silent.

**It never posts to a dead target.** Because the trigger fires unconditionally once
CI is green, a pull request that was merged or closed while CI was still running would
otherwise receive an automatic review request whose run lands on a target nobody can
act on — a full cloud agent run and its model tokens spent on output no one reads. So
`scripts/post-ci-review-trigger.sh` (`MODE=post`) reads the pull request's state
read-only and posts **only while it is still open**: a merged or closed target, or a
state it cannot establish, each declines to post and emits its own distinct
`::warning::` naming the condition. That decision is **fail-closed** — the same
asymmetry as the helper's idempotency read (a missed notification is recoverable by
hand; review spend on an already-merged target is not). The guard lives inside the
helper, not in the job's `if:`, so the consumer snippet below is unchanged and a
consumer inherits the behavior at its next vendor bump.

**Interaction with `/prflow:review-and-fix --push-each-iteration`.** When the fix loop
runs with `--push-each-iteration`, each iteration pushes the fix commit to the PR head,
producing one `synchronize` event. Whether that pushed head is then **automatically
re-reviewed** is exactly the conditionality this section describes, and it depends on the
repository: this repo (and any consumer that copied the snippet below) auto-requests a
`/prflow:review` once CI goes green on the pushed head; a consumer with neither this job
nor a retained pre-#936 `devflow-review.yml` gets no automatic re-review and re-reviews
by a collaborator comment; a consumer still carrying the withheld tier re-reviews via that
retained workflow. With `--push-each-iteration` off (the default) nothing is pushed, so no
`synchronize` fires and none of this applies — the fix loop still converges because it
rides the local head-override diff, not the pushed state. (The review-and-fix bundle states
the same conditionality from the loop's side; this section is the canonical trigger
statement.)

### Superseding stale CI runs (`ci.yml`'s workflow-level `concurrency`)

`ci.yml` also carries a **workflow-level** `concurrency:` key — distinct from the
job-scoped one on `auto_review_trigger` above. It cancels a superseded pull-request CI
run: when a new commit is pushed to a PR branch, the run for the commit it replaced is
still executing a full suite for a commit nobody will merge, on runners the new commit
is waiting for. The group is keyed on the pull request, so two pushes to one PR branch
share it and two different pull requests never do; on a `main` push the pull-request
number is empty, so `github.run_id` gives each main run its own group — main runs are
neither cancelled (each merged commit is a distinct artifact, not a superseded draft)
nor serialized behind one another — and `cancel-in-progress` resolves `true` only for
`pull_request` events.

This is **not** the duplicate-command case the repository's standing doctrine rules
GitHub-native `concurrency` out of. That doctrine (see the duplicate-command sections
above, and `scripts/dedupe-review-command.sh` / `scripts/dedupe-implement-run.sh`)
governs two requests for the *same* work, where the wanted behavior is "ignore the
second, leave the first untouched" — which neither `concurrency` mode expresses.
Supersession is the opposite shape: two CI runs for two *different* commits are not
duplicates, the first has been made obsolete by the second, and the wanted behavior
**is** "cancel the in-flight one" — the one thing `cancel-in-progress: true` does
natively well. The block stays on `ci.yml` only: a `concurrency` cancel on
`devflow.yml` or `devflow-implement.yml` would feed a deliberate cancel into the
run-identity machinery those workflows depend on. Like the job-scoped serialization
above, the consumer snippet below omits this refinement — a consumer that wants it adds
the workflow-level `concurrency:` key to their own CI.

### Consumer snippet

Add this as a new workflow file (e.g. `.github/workflows/prflow-auto-review.yml`) in
your repository.

> **Hard precondition — read before copying.** This snippet is safe **only** inside a
> `pull_request`-triggered workflow. **Never** place it under `pull_request_target`:
> that trigger makes your secrets available to fork-originated runs, and the
> head-repo clause (`…head.repo.full_name == github.repository`) would then be the
> *sole* defense keeping a fork from minting your App token. Under `pull_request`,
> secrets are withheld from fork runs regardless, so the fork gate is defense in
> depth rather than the only line.

<!-- prflow:ci-review-consumer-snippet -->
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
    # These five eligibility clauses are PORTABLE and are held byte-identical to
    # PRFlow's own auto_review_trigger job by a suite assertion — do not edit them.
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
      # The helper is NOT at a repo-root scripts/ in your repo — install.sh
      # vendored the plugin under .prflow/vendor/prflow/, and the vendor-plugin
      # composite action re-materializes it at runtime. The sparse cone names BOTH
      # scripts/ AND lib/ because the helper's transitive closure spans both:
      # post-ci-review-trigger.sh, post-issue-comment.sh, resolve-gh.sh,
      # resolve-bin.sh.
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
          # Absent-file breadcrumb (modeled on devflow.yml's review_dedupe detector
          # guard): a consumer pinned below the version that carries the helper gets
          # a NAMED warning rather than an rc-127 red step.
          if [ ! -x "$HELPER" ]; then
            echo "::warning::PRFlow auto-review: helper not found at $HELPER — has install.sh vendored the plugin at prflow_version >= 2.30.18? Skipping (no review requested)."
            exit 0
          fi
          "$HELPER"
```

**Preconditions to satisfy beside this snippet:**

- **Minimum version.** `scripts/post-ci-review-trigger.sh` first ships in
  `prflow_version` **`2.30.18`** — pin at or above it, or the absent-file guard in
  the snippet fires and no review is requested. Note that `2.30.18` itself predates
  the author-scoped dedupe described above: that release ignores `EXPECTED_AUTHOR`
  and suppresses on any comment carrying the marker, so a human quoting the marker
  still kills the request there. The snippet degrades rather than breaks — it still
  requests reviews — but pin to a release carrying the author-scoped helper to get
  the behavior this page describes.
- **The minting App's bot login must be in `prflow.allowed_bots`.** The review this
  snippet requests is dispatched by `devflow.yml`'s gate, which authorizes the
  commenting actor through `scripts/authorize-actor.sh`. The comment is posted by
  your GitHub App, so its bot login (e.g. `your-app[bot]`) must appear in
  `prflow.allowed_bots`. The shipped `.prflow/config.example.json` value is
  `"claude,dependabot"` — it names **no** App slug, so a fresh install does not
  authorize your App until you add it. **And `devflow.yml`'s `config` job resolves
  `prflow.allowed_bots` from your repository's *default branch at trigger time*** —
  so adding your App slug *inside the same pull request that adds this snippet* is
  inert for that pull request (the trigger reads the default branch, where the slug
  is not yet present). Merge the `allowed_bots` change first; only then does the
  snippet start a review. (This is the same trigger-time-resolution note
  `docs/internal/cloud-setup.md` carries for the two stall-backstop paths.)
- **No repository-root `scripts/`.** A consumer checkout has no repo-root `scripts/`
  directory — that exists only in PRFlow's own repository. The helper resolves under
  `.prflow/vendor/prflow/scripts/`, materialized by the `vendor-plugin` composite
  action `install.sh` ships. The sparse cone names both `.prflow/vendor/prflow/scripts/`
  and `.prflow/vendor/prflow/lib/` because the helper sources its `gh` resolver from
  the sibling `lib/` directory.

**Coverage boundary.** This mechanism reaches pull requests gated by **GitHub Actions
workflow jobs** only. It does **not** reach external CI apps that report through the
`check_suite` event (CircleCI, Buildkite, and the like) or systems that report through
the legacy `status` event (classic Jenkins, legacy CircleCI): the snippet's `needs:`
can only wait on Actions jobs in the same workflow run. Users of those CI systems keep
the manual collaborator-comment path — a repository collaborator comments
`/prflow:review` on the pull request.

## Automated review (`devflow-review.yml`): trigger + preconditions policy

> **Withheld from this release (issues #930 and #920) — see the section above.** This
> section describes the tier as it behaves in a repository that installed it before the
> withholding. A fresh installation has no such workflow.

The automated reviewer runs `/prflow:review` as a **required** status check on a
PR. Its trigger policy (issue #304):

- **First review — exactly once per PR.** The first review auto-triggers on
  whichever of `{opened non-draft, reopened non-draft, ready_for_review}` fires
  first, gated to exactly-once by a check-existence query (`precheck` skips when a
  `Devflow Review` check that actually ran already exists on the head or any
  commit). A `synchronize` (new commit on an open PR) re-reviews the new HEAD when
  it carries no already-passing check, so the required context is never missing.
- **Preconditions (both default-on, config-gated).** Before a review fires,
  `scripts/derive-review-preconditions.sh` evaluates two gates: `require_up_to_date`
  (the PR branch must not be **behind its base**) and `require_ci_green` (every
  *other* CI signal on the head must have completed without failing). For the
  Actions-runs signal, the non-self runs are first **collapsed to the latest run
  (highest `run_number`) per `(workflow_id, event)` group**, so a superseded run —
  an approval-gated re-dispatch, a double-fire, a cancelled sibling — never gates
  the review once a newer run of the same workflow+event exists (a run missing a
  numeric `workflow_id`/`run_number` or a string `event` fails closed as
  *unverifiable*). When a gate
  is unmet the review is **deferred**, not run: a neutral "waiting" `Devflow Review`
  check is posted so the required context is present but non-blocking (a neutral
  required check does not block merge — pair it with branch protection's "require
  branches up to date" if staleness must hard-block). A surviving run awaiting
  manual approval (conclusion `action_required`) defers with the distinct reason
  `ci-approval-required`, whose title is selected by
  `scripts/describe-skip-title.sh` (invoked in the `precheck` job and consumed by
  `create_check` via the `skip_title` output) — mapping it to the plain-language
  neutral check **"Devflow review waiting: CI approval required"** rather than the
  opaque "other CI not green".
- **CI-completion re-trigger.** A review deferred behind `require_ci_green` (or
  `require_up_to_date`) auto-re-fires once the PR becomes reviewable — via the
  `workflow_run` (Actions CI) and `check_suite` (external CI) `completed` events,
  or a `status` event (legacy commit-status-only CI — classic Jenkins, legacy
  CircleCI — reporting via the commit-status API, which emits neither of the
  other two; filtered to a green `state == 'success'` before a runner spins, and
  resolving the PR from the status head SHA since its payload carries no PR ref) —
  with no manual Re-run. Note the `status` trigger is **unconditional**: GitHub
  offers no context/branch scoping for it, so it fires for *any* commit status
  from *any* app (Codecov, Vercel, external bots), not only legacy CI — an
  Actions-CI repo that also has a status-posting app therefore spins a precheck
  runner per green status. Once a review already exists for the head each
  redundant spin no-ops after a couple of read calls (PR resolution + the
  exactly-once gate, which short-circuits before the expensive precondition and
  review work). A status arriving *before* sibling CI has completed instead
  re-enters the preconditions — several `gh api` reads that fail closed to
  *defer* on a rate-limited token — so a heavy status burst in that pre-review
  window could spuriously defer an otherwise-reviewable PR (bounded to the
  pre-review window; the exactly-once gate ends it once a review lands). This is
  the accepted cost of an unconditional trigger. `workflow_run` **requires an
  explicit workflow-name list**
  (a GitHub platform constraint — no wildcards): it ships naming **every**
  first-party workflow that runs on PR events (`[CI, Matcher probe]`), because a
  review deferred behind `require_ci_green` waits on *all* other head runs to
  complete but re-fires only on a *listed* one's completion — so a gating workflow
  omitted from the list can strand a deferred review at the neutral "waiting:
  other CI not green" check with no event left to clear it (issue #579).
  **A consumer repo must list every workflow that runs on its pull requests — not
  just the primary CI one — in the `workflow_run:` list in
  `.github/workflows/devflow-review.yml` when installing**, or the CI-completion
  re-trigger silently never fires for a deferred review (the installer prints a
  reminder to this effect; see also `docs/internal/cloud-setup.md`). The precondition
  *evaluation* itself stays fully generic (no job names).

### The injected block reports *observed* CI conclusions, never a green assumption

Every cloud review prompt carries a `> [!IMPORTANT]` engine ground-truth block
(`scripts/render-grounding-block.sh`) whose CI section is rendered by
`scripts/summarize-ci-checks.sh` from the GitHub API for the reviewed head. It lists one
line per signal with **the conclusion actually observed** — `success`, `failure`, or, for a
job still running, its `status` (e.g. `in_progress`). It never asserts that CI passed.

This is load-bearing precisely because of the trigger asymmetry documented above. On the
auto path `require_ci_green` defers the review until CI has completed without failing, so a
green assumption would *usually* be right. But a `check_run[rerequested]` **Re-run** is
deliberately ungated by the preconditions, so it can reach the engine while CI is still
running or after it failed. A block that hardcoded "CI passed" would hand that run a false
premise; a block that reports what it observed hands it the truth.

Two further properties follow from the same rule: `require_ci_green` treats `skipped` and
`neutral` as green, so rendering per-signal conclusions (rather than one summary boolean)
keeps a skipped test job from reading as a passing one; and when the CI state cannot be
determined at all, the block prints the literal `CI status unavailable` rather than
omitting the section — an absent result is never rendered as a passing one.

### Known limitation: a behind-base deferral is not re-evaluated when the base advances

A `require_up_to_date` (behind-base) deferral clears only when the review is
re-evaluated, and the re-evaluation triggers are all **head-scoped**: a new commit
pushed to the PR branch (`synchronize`), a CI workflow completing for the head
(`workflow_run` / `check_suite`), a legacy commit-status transition for the head
(`status`), or a manual **Re-run**. There is **no
push-to-base listener** — advancing the *base* branch (which is what actually
makes a behind-base PR fall further behind, or, after the PR rebases elsewhere,
could clear it) does **not** by itself re-evaluate the deferral. So a PR deferred
as "branch behind base" whose base moves but whose head is untouched stays in the
neutral "waiting" state until its branch is updated or its check is Re-run. This
is accepted: a behind-base neutral check does not block merge, updating the branch
(the action that actually resolves being behind) fires `synchronize` and clears
it, and the Re-run button is always available. Once the workflow-hardening
follow-up ships the summary pointer, the waiting check's deferral summary will
point operators here.

## Triggers fire on real comments only — never on descriptions

A `/prflow:*` phrase placed in an **issue or PR description (body or title)**
must never start a run — only a genuine comment can. This is why
neither command workflow listens on the `issues` event, and why each gate's
`TRIGGER_TEXT` is sourced solely from `github.event.comment.body` (never
`issue.body` / `issue.title`). Quoting a command while *describing* a bug or
feature is therefore safe. (Before issue #1163 the light path also read
`github.event.review.body`; dropping its two review-triggered subscriptions
left `github.event.comment.body` as the sole trigger-text source in both
workflows.)

Note: opening a PR does not trigger anything either — neither workflow listens
on `pull_request[opened]`, so a PR description is never a trigger source.

The partition tests assert all of this: no `issues:` event, no
`contains(github.event.issue.body|title, …)` in any gate, and no `issue.body` in
`TRIGGER_TEXT`.

## PRFlow's own workpad comment can't self-trigger `/prflow:implement`

The `/prflow:implement` orchestrator maintains one marker-tagged **workpad**
comment per issue (see `scripts/workpad.py`), and that comment quotes the literal
phrase `/prflow:implement` (e.g. its seeded `/prflow:implement run started`
note). Because the comment is posted by an allowed bot, it would otherwise re-enter
the gate as a fresh `issue_comment[created]` event and fire a duplicate run on its
own thread.

`scripts/resolve-implement-trigger.sh` closes this with a **self-trigger guard**
that runs *before* authorization and number resolution: it declines any
`TRIGGER_TEXT` that *contains* the effective workpad marker. The check reads:

- The marker comes from the `SELF_COMMENT_MARKER` env var, defaulting to
  `<!-- prflow:workpad -->` when unset/empty — the same fallback `workpad.py`
  uses, so the guard protects a repo with no config exactly the same.
- It is a literal **substring** match (`case "$text" in *"$marker"*`), not a
  regex, so a marker customized with regex-special characters still matches
  literally, and a marker quoted/embedded anywhere in the body is still caught.
  This is deliberately broader than `workpad.py`'s own marker check, which only
  matches with `startswith`.
- On a match the gate emits `should_run=false` (with an empty `number`) and logs a
  `::warning::`, regardless of actor or which command phrase the body quotes.

> **Workflow wiring.** Passing `SELF_COMMENT_MARKER` into the resolver's
> environment (and exposing a `workpad_marker` config output) lives in
> `.github/workflows/devflow-implement.yml`, and is **applied as shipped** — the
> config job extracts `prflow.workpad_marker` (defaulting to the built-in
> `<!-- prflow:workpad -->`) and the gate passes it to the resolver. So both the
> **default** marker and any repo-customized `prflow.workpad_marker` are protected
> out of the box, with no manual edit required.

## Startup lifecycle: "resumed" means an earlier execution, not the normal handoff

The cloud `/prflow:implement` path has two stages — a lean `gate` job that posts
the workpad the moment a command is authorized, and a heavy `claude` job that boots
and enters Phase 1 minutes later. The normal same-run handoff from `gate` to
`claude` is **not** a resume, and (since issue #537) the workpad no longer labels it
one. The lifecycle wording is decided from **provenance** (a workflow-owned handoff
record naming whether the gate *created* or *adopted* the workpad) crossed with the
workpad's **live status**:

- **`agent initialized; Phase 1 workpad hydrated`** — the ordinary first run (the
  gate created the workpad this run). No "resumed" claim.
- **`/prflow:implement run resumed; Phase 1 workpad hydrated`** — the gate adopted
  an **interim** (still-in-progress) workpad from an earlier execution (a re-trigger
  or a stall-backstop auto-resume). This is the only case that says "resumed".
- **`/prflow:implement new run initialized from terminal workpad; …`** — the
  adopted workpad was already terminal (🎉/👎/💥/🛑); a fresh run starts from it.
- **`agent initialized; workpad provenance unavailable; …`** — the handoff record
  was missing/malformed (e.g. a partially-upgraded consumer); the run continues
  without guessing.

Up to four `## Progress` checkpoints timestamp the startup boundaries — the gate
acknowledgment (only on the adopted/resume path, so a normal fresh run writes the
other three), `Claude job setup complete; invoking agent` (written immediately
before the action), `agent entered Phase 1 setup; workpad triage passed`, and the
hydration event above — so startup latency is attributable from the workpad alone.
Local runs read no cloud handoff record and select wording from live status only.

## A light `/prflow:*` command fires only when *issued*, never when *quoted*

The light command path (`/prflow:review`, `/prflow:review-and-fix`,
`/prflow:pr-description`) is intentionally **PR-aware** — a PR comment is also an
`issue_comment` in GitHub's API, and these commands act on a PR — so unlike the
issues-only heavy path it *retains* PR-comment and PR-review triggering by design.
Removing that surface would break the primary use case. The bug it must avoid is
different: a command **quoted in prose** (a human review that says "as
`/prflow:review` flagged…", PRFlow's own review narrative, an un-markered report
body) must not be mistaken for the command being *issued*. A quoted
`/prflow:review` inside a PR **review** body was the reported self-trigger vector.

Two mechanisms close this, both living in `scripts/resolve-command-trigger.sh`
(the authoritative gate; the workflow `gate` `if:` stays a coarse `contains()`
pre-filter):

1. **Anchoring (the core fix).** A light command is a trigger **only** when it is
   the sole content of its own line — it begins the line with at most three
   leading spaces (never a tab, never four-plus, so an *indented* code block never
   qualifies), it is **not** inside a fenced (triple-backtick / `~~~`) code block,
   and the remainder of the line is at most an optional `#`-prefixed number plus
   trailing whitespace. So `/prflow:review`, `/prflow:review 42`, and
   `/prflow:review #42` fire (alone on their line, even inside a longer body);
   `please run /prflow:review`, a `> /prflow:review` blockquote, an indented or
   fenced `/prflow:review`, and `I ran /prflow:review earlier` do **not**. The
   scan is a small **markdown-aware line scanner** (`scripts/detect-standalone-command.sh`,
   POSIX `awk`, ERE only) that tracks fenced-block state, skips indented-code
   lines, and applies the anchored own-line match most-specific-first
   (`/prflow:review-and-fix` outranks `/prflow:review`). It is deliberately
   **fail-closed on an unbalanced fence**: after an unclosed opening fence every
   following line reads as code and fires nothing — matching how GitHub itself
   renders an unbalanced fence, and the safe direction for a self-trigger fix. It
   approximates GitHub-flavored markdown (not a full CommonMark parser): it does
   not model list-relative indentation, so a command deeply indented inside a list
   item is treated as code and does not fire — an over-exclusion that still errs
   toward not-triggering.

2. **Self-marker guard (defense-in-depth).** Mirrored from
   `resolve-implement-trigger.sh`, the resolver additionally declines — *before*
   authorization — any body that carries a PRFlow self-comment marker: the
   run-keyed review-progress marker **prefix** `<!-- prflow:review-progress` (the
   review engine's live progress comment, whose narrative naturally quotes
   `/prflow:review` — see `scripts/derive-review-verdict.sh`) or the workpad
   marker `<!-- prflow:workpad -->`. Each is a literal **substring** match, and
   the effective markers **default to those built-in values internally**, so the
   guard protects a repo with no extra workflow wiring. Note this guard alone was
   insufficient for the reported vector — the PR-review body carried no marker —
   which is why anchoring is the necessary core and the marker guard is retained
   only for PRFlow's own progress comment.

Because anchoring operates on the resolver's `TRIGGER_TEXT` input, it is
**surface-agnostic**: whatever body the workflow routes into that input is
anchored the same way, so no per-surface wiring is added. When this landed the
workflow passed `${{ github.event.comment.body || github.event.review.body }}`,
which routed the PR-review body in; issue #1163 has since dropped the two
review-triggered subscriptions, so `TRIGGER_TEXT` is now
`${{ github.event.comment.body }}` alone and no review body reaches the
resolver at all. The anchoring itself is unchanged — it governs whichever
surface is wired in.

> **Landed (issue #321):** the `review_dedupe` job in `devflow.yml` now routes
> through the **same** `detect-standalone-command.sh` detector (not its own
> `case` substring), so a quoted/documented `/prflow:review` mention neither
> dedupes nor posts a "manual review suppressed" notice and the two matchers are
> a single source of truth that cannot drift. Because that change edits a file
> under `.github/workflows/`, it needed a `workflows`-scoped push the PRFlow
> bot's installation token lacks, so it landed via a human/PAT in the #321
> follow-up rather than in the bot-authored PR that shipped the resolver
> anchoring here.

> **Landed (issue #1032):** the **heavy** `/prflow:implement` path now routes
> through this **same** `detect-standalone-command.sh` detector too (the implement
> token was added to its most-specific-first ladder), so a quoted, blockquoted,
> indented, or fenced `/prflow:implement` occurrence — previously matched by a bare
> `grep` in `resolve-implement-trigger.sh` that fell through to the attached
> issue's number and fired a full run — no longer triggers. The heavy path
> inherits the identical fence/bareness and fail-closed-on-unbalanced-fence
> behavior described above, and the shared detector means the heavy and light
> matchers cannot drift. `resolve-command-trigger.sh` dispatches only the three
> light commands via a fail-closed allowlist, so the shared detector recognizing
> the implement token never leaks a heavy run into the light path.
>
> **Two standalone commands in one comment:** the detector stops at the **first**
> standalone command, and each resolver then filters that single token against its
> own allowlist — so the light and heavy paths are **mutually exclusive by
> construction**. A body whose first standalone command is `/prflow:review` and
> whose second is `/prflow:implement 42` dispatches the review and declines the
> implement; reverse the order and the implement fires while the light path
> declines. Between the two resolvers — `resolve-command-trigger.sh` for the
> light commands and `resolve-implement-trigger.sh` for the heavy one — at most
> one dispatches, and it is the single shared scanner, not the workflow `if:`
> filters, that makes a double-fire unrepresentable.

> **Out of scope (decided):** a light command posted on a plain **non-PR issue**
> comment still resolves a number and runs; narrowing that surface is deferred to
> a separate issue. This section covers only the markdown-aware anchoring and the
> self-marker guard.

## A comment-triggered light command addresses its own thread (issue #1863)

The detector recognises an optional trailing number on a light command
(`/prflow:review 42`, `/prflow:review #42`), so **which** comments fire is exactly
as the anchoring rules above describe. But `scripts/resolve-command-trigger.sh` no
longer *uses* that number to pick a target: it **discards** it and resolves to the
event's own context number — the number of the thread the comment was posted on —
unconditionally, for all three light commands (`/prflow:review`,
`/prflow:review-and-fix`, `/prflow:pr-description`). A command carrying no number
resolves to the thread's number exactly as before.

**Why the number is ignored rather than honoured.** `devflow.yml`'s `command` job
decides *whether* two `always()` steps run — the verdict-reach record and the
superseded-REJECT dismissal net — by asking whether the thread the comment sits on
is a pull request, then acts on the resolved command's number. Since #1858 those
two could differ: `/prflow:review 42` posted on a pull-request thread passed the
guard yet acted on issue 42, and `/prflow:review 99` on a plain issue skipped the
guard while a real review ran against pull request 99. Discarding the typed number
makes the guard's subject and the acted-on number the same value, with no functional
change to the workflow steps (only their comments were reworded). The heavy path
(`/prflow:implement`, `scripts/resolve-implement-trigger.sh`) is untouched — it
requires an explicit number and still resolves to it.

**The discard is logged.** When a light command carries a trailing number, the
resolver writes a `::warning::` line to standard error — reaching the workflow run
log — naming both the number that was ignored and the thread number that was used,
so someone who typed one number and got a review of a different thread can find out
why. The automated post-CI trigger (`scripts/post-ci-review-trigger.sh`) posts the
bare command with no number, so it never trips this path.

## A `/prflow:implement` run keeps progress on the issue workpad

A run maintains one canonical issue comment, the marker-tagged *workpad*
(`scripts/workpad.py`). It is both the immediate "job started" acknowledgment
and the durable progress surface — Status, the `## Progress` phase checklist
(with append-only timestamped notes nested under each phase), run/branch/PR
links, Plan, Acceptance Criteria, and (collapsed in `<details>`) the Devflow
Reflection. There is no separate Decisions / Notes section — notes live inside
`## Progress`. The `Last updated` line is friendly UTC (`2026-05-05 17:42 UTC`),
not raw ISO-8601.

- **`track_progress: false`** on the `claude-code-action` step in
  `.github/workflows/devflow-implement.yml` disables the action's own
  progress comment. The inline review-and-fix loop also receives the internal
  `progress_surface = workpad` binding, so it does not seed a
  `prflow:review-progress` comment on the draft PR. The light
  `/prflow:review` · `/prflow:pr-description` listener in `devflow.yml` keeps
  `track_progress` as-is. `/prflow:pr-description` has no workpad, while a
  standalone `/prflow:review` in PR mode authors the live progress comment
  described below.
- The workpad is created **as early as possible**, before the requester waits
  on any runtime. In a cloud run the **`gate` job** creates a lean workpad
  (`workpad.py new-body` → `create`) right after authorization + dedupe — *before*
  the heavy `claude` job boots and runs `setup-project-env` (Python/Node/services/
  deps), which the acknowledgment does not need. The `claude` job's Phase 1.3
  detects that workpad via `workpad.py id` and **resumes** it (filling in the Plan
  and the real Acceptance Criteria), never posting a second comment. A local-tier
  run (no `gate` job) creates the workpad itself in Phase 1.3 as the first GitHub
  write. Either way it is created *before* the branch. The `Run` link is built
  from `$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID`
  (standard env vars — no workflow wiring needed); the `Branch` line is filled the
  instant the branch exists, and the `PR` link once the draft PR is resolved in
  Phase 3.1 — freshly created, or, on a resume whose prior attempt already opened
  one, adopted by Phase 3.1's existing-PR resolver
  (`scripts/resolve-existing-pr.sh`).
- The workpad's **Review** phase contains the ordered review-engine rows rendered from
  `scripts/workpad.py::_REVIEW_PROGRESS_ROWS`. The shared engine ticks the rows
  in order for diff classification, checklist generation, checklist verification,
  review agents, aggregation and verdict, and terminal run completion. For an exact
  tuple-declared operand whose unique row is already ticked, replay succeeds without
  refreshing `Last updated` or issuing a GitHub PATCH. A missing, ambiguous, unknown,
  or unticked row keeps the normal update behavior so drift remains visible.

### Status-glyph / reaction vocabulary

The workpad `Status` line begins with a canonical glyph that `workpad.py`
derives from the status word, and the same glyph is mirrored as a reaction on
the **triggering** comment so the two never disagree. The vocabulary is
constrained to GitHub's fixed reaction set (`+1 -1 laugh confused heart hooray
rocket eyes` — ✅/❌ are *not* reactions):

| State | Glyph | Reaction |
|---|---|---|
| Running (any in-progress phase) | 🚀 | `rocket` (added on pickup by the `gate` job) |
| Complete | 🎉 | `hooray` (added in Phase 4.3) |
| Blocked | 👎 | `-1` (added at any Blocked finalizer) |

The completion/blocked reaction is emitted via `scripts/react-to-trigger.sh`
(the same script the gate uses for the pickup 🚀) and is driven by the run's
**final workpad `Status`**, not the job's exit code — a run can exit 0 while
`Blocked`. The reaction is best-effort: a failure never blocks the run, and the
workpad `Status` glyph remains the authoritative signal.

Resolving *which* comment to react to works on both tiers (issue #664). The
skill prefers `.comment.id` from `$GITHUB_EVENT_PATH` (present when the run was
comment-triggered) and otherwise lists the issue's comments via `gh api` using
the `{owner}/{repo}` placeholders `gh` fills from the git remote — never
`repos/$GITHUB_REPOSITORY/…`, since that variable is set only by the Actions
runner and is **empty** on the local/interactive tier, collapsing the path to
`repos//issues/…`. That failure is not self-announcing: `gh` writes the HTTP
error body to **stdout**, so a best-effort `VAR=$(gh api … 2>/dev/null || true)`
capture holds a 404 JSON blob rather than an empty string. The fence therefore
admits a resolved id only when it is a bare digit string, and reacts to nothing
otherwise. `lib/test/lint-gh-api-repo-path.py` (driven from `lib/test/run.sh`)
turns a reintroduced `$GITHUB_REPOSITORY` interpolation in a `gh api` path
argument RED at the desk, everywhere outside the Actions-only
`.github/workflows/` and `.github/actions/` surfaces.

## A PR-mode `/prflow:review` posts one live progress comment

Standalone `/prflow:review` is handled by the light listener in `devflow.yml`.
The same engine also runs in repositories that retained the now-withheld
`devflow-review.yml` automated reviewer, but that workflow is not shipped in
this tree. In **PR mode**, and when
`prflow_review.live_progress_comment_enabled` is `true` (the default), the
review engine maintains a **single per-run** marker-tagged comment — keyed by a
run-keyed marker (`<!-- prflow:review-progress run=<id>-<attempt> -->`; the bare
`prflow:review-progress` is its prefix) — and rewrites it **in place** as it works:
a blueprint of the phases up front, then per-phase results (diff classification,
checklist counts, each Phase-3 agent's findings appended *as that agent
returns*, the verdict), finalizing with the full Phase 4.1 report plus a
run-telemetry summary and effectiveness trace. `skills/review/SKILL.md` owns
the comment lifecycle. `scripts/seed-review-progress.sh` owns the cloud seed's
marker derivation and marker/body agreement.

- Cloud seeding runs through `scripts/seed-review-progress.sh`. With a usable
  `GITHUB_RUN_ID`, that helper derives
  `<!-- prflow:review-progress run=${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT:-1} -->`,
  inserts it as line 1 of the body passed to `workpad.py create` and reports the
  exact literal. The engine holds that reported value for each later rewrite.
  It never composes a second cloud marker after a successful helper call.
- A local run is the explicit exception. The engine computes one timestamp-based
  marker before invoking the helper and passes it through the helper's existing
  marker slot. The helper uses and reports that literal unchanged. If the helper
  never executes because it is absent or refused, the engine composes the
  effective marker itself and reauthors the body with that marker as line 1
  before a direct `workpad.py create` call.
- The review lifecycle still uses `scripts/workpad.py` for marker-scoped lookup,
  create and patch operations. `devflow-review.yml` does not seed, template or
  PATCH a competing comment; repositories that retained that withheld workflow
  run the shared engine. Exactly one such comment exists **per review run**.
  Earlier runs' comments are never overwritten and remain on the pull request as
  review history.
- Phase 4.4's posted review stays the authoritative merge signal (a short
  verdict stub); the live comment is the human-readable narrative pointing at it.
  The final comment state reflects the actual verdict — never a green check above
  a REJECT.
- **Dead-run backstop (issues #356 and #1154).** The agent flips this comment to
  `❌ Review failed` on its own fatal aborts, but on a run that ends without a
  verdict it never gets to. A workflow-level backstop then writes that state
  instead: `scripts/flip-review-progress-failed.sh` locates *this run's* comment
  by its run-keyed marker and **upserts**. When the comment exists and its
  `**Status:**` line still begins with the interim `🚀` glyph, it is rewritten to
  `❌ Review failed` with a one-line cause and run link. When the scan confirms
  *no* comment exists — a run that died before the engine reached its Phase 0.3.5
  seed — one is created carrying the same run-keyed marker as line 1 and that
  same terminal Status, so the pull request records the dead run instead of
  carrying nothing beside a green check. A terminal Status is never clobbered and
  no second comment is created beside it (which is also what makes the upsert
  idempotent across job retries), a lookup that *failed* never authorizes a
  create, and earlier runs' comments are never read or written. The helper is
  best-effort — always exits 0, so it never fails the required check.

  In the shipped tree, `devflow.yml` invokes it from an `always()` step whose
  decision to act no longer depends on the run's outcome at all. Before issue
  #1154 that step was gated on three disjuncts (a failed Claude step, a
  cancellation, or a final engine result carrying `is_error`), so a run that
  exited *cleanly* having written no verdict — the observed Phase 0
  permission-denial mode — matched none of them and left the pull request
  unmarked. The two observables the workflow has (the Claude step's raw outcome
  and the parsed engine `is_error`) are now inputs to the **cause** the backstop
  reports, and the four run-end modes they partition into are selected by
  `scripts/describe-dead-run-cause.sh` rather than by inline workflow shell.
  A command that seeds no progress comment (`/prflow:pr-description`) is screened
  out before the upsert, and a consumer whose vendored plugin pin predates the
  cause helper degrades with a warning rather than failing the step.

  Removing the outcome gate had a cost issue #1172 later corrected: an
  `always()` step that acts irrespective of outcome also fires on a clean-exit
  run that *did* post a verdict, stamping a false `❌ Review failed` banner
  (measured 16 false banners against 15 real verdicts in one day, 0 observed
  precision). The step now asks whether a verdict exists before writing:
  `scripts/dead-run-verdict-present.sh` reuses the HEAD-scoped, fail-closed
  `scripts/derive-review-verdict.sh` — consulting both channels the verdict
  marker is written to (the formal review and this run's run-keyed progress
  comment) — and prints present/absent. A *positively-determined* verdict
  suppresses the flip; every other outcome (no verdict, an engine error, an
  unresolvable HEAD, a query failure, a missing helper) still writes the banner,
  so a genuinely verdict-less run keeps getting it. This also restores
  `derive-review-verdict.sh` to a live in-tree call path. A repository
  that retained the withheld `devflow-review.yml` keeps that installed file's
  existing `finalize_check` call site; this change does not add new workflow
  wiring to that preserved copy.

  After the authoritative flip, the shipped `devflow.yml` path runs marker
  diagnosis only for canonical `/prflow:review` and `/prflow:review-and-fix`
  commands. `scripts/run-review-progress-diagnosis.sh` dispatches to
  `scripts/diagnose-review-progress-marker.sh`, which distinguishes an exact
  match, a clean absence, an active bot-authored `🚀 Reviewing` comment under a
  foreign marker and an unestablished comments read. The foreign outcome emits a
  warning phrased as a possible marker mismatch. Exact matches and clean
  absences remain silent. An unestablished read emits a non-asserting notice.
  Non-review commands do not run the diagnosis. The
  died-flip makes a dead review *visible* but leaves it a dead-end; the bounded
  **no-verdict auto-resume backstop** (`prflow_review.stall_backstop`, issue
  #408) then re-runs it without a human — when a cloud review ends with no
  verdict for the head, `finalize_check` posts a capped App-token-authored
  `/prflow:review` re-trigger (default `max_resume_attempts: 2` per head),
  degrading to exactly the dead-end flip when the cap is exhausted, the backstop
  is disabled, or no App token is configured. A cancelled run is excluded from
  auto-resume on every PRFlow backstop (issue #498) — a cancel is a decided
  ending, not a benign timing stall — so neither this review backstop nor the
  implement-tier one keys its resume decision on a cancelled run's stall
  signature; the review tier's exclusion is already correct at source (the
  dead-run signal fires only on is_error/failure, never on cancellation).
- It works under the **read-only cloud `review` profile**: the comment is
  created/edited via `gh` (a comment edit, not a tree write), and the runner's
  `review` tool profile additionally allow-lists `workpad.py`, `config-get.sh`,
  and `efficiency-trace.sh` for this. The effectiveness-trace **record**
  is persisted to the dedicated `prflow-telemetry` branch (issue #441). Every
  *writable* run pushes it directly. This read-only `review` runner
  (`contents: read`) still runs `--persist`, but in **staging-only** mode: because
  the workflow leaves the push operand `DEVFLOW_TELEMETRY_PUSH` unset, `--persist`
  fails closed under CI (issue #469 AC5) — it stages the records under
  `.prflow/tmp/`, writes no new branch records, and does no push (a best-effort
  fetch may fast-forward the *local* `prflow-telemetry` ref to mirror the remote;
  that leaves the tree and the *remote* ref untouched), so this runner leaves the
  remote `prflow-telemetry` ref untouched by its own action. To carry those staged records across
  the workflow boundary the runner **uploads** them as a workflow artifact, and a separate trusted
  telemetry-push relay (`telemetry-push.yml`, issue #489 — which does not check out the PR head,
  mints a write-capable token above its checkout, and validates the artifact as untrusted input)
  downloads and pushes them to the branch — see [`efficiency-trace.md`](efficiency-trace.md).
- Gating: `prflow_review.live_progress_comment_enabled = false` skips the live
  comment (the report is produced once at the end, as before); in non-PR /
  current-branch mode there is no comment surface and the narrative goes to chat.
  This flag is independent of
  `prflow_review_and_fix.efficiency_telemetry_enabled`, which separately gates
  the embedded telemetry/trace. Comment writes are best-effort — a failure is
  logged and the review continues to its verdict.

## Duplicate `/prflow:implement` runs are ignored per thread

A second `/prflow:implement` for an issue/PR while a run for it is already in
flight is **ignored** — the new command does not start a second `claude` job,
and the in-progress run is left untouched. A command for a *different* issue
runs in parallel as normal.

GitHub Actions has no native "skip if already running": `cancel-in-progress: true`
cancels the in-flight run (the wrong one), and `cancel-in-progress: false` queues
the duplicate so it eventually runs (not ignored). This is **repository doctrine
covering both duplicate-command paths** — the `/prflow:implement` path here and the
`/prflow:review` command path below — so both detect duplicates with a gate-stage
check rather than a `concurrency` group. So the implement gate detects duplicates
itself, in `scripts/dedupe-implement-run.sh`:

- `devflow-implement.yml` sets a `run-name` embedding the issue/PR number the
  command was posted on. The dedupe step lists this workflow's active runs and
  matches that number out of each run's display title.
- A run defers **only** to an active run with a *smaller* `databaseId` (an older
  run). Run ids increase monotonically, so among overlapping runs for one thread
  the oldest — having no older peer — proceeds and the rest ignore. The common
  case (duplicate commands seconds apart) thus collapses to one run. Because
  `gh run list` is eventually consistent, two commands fired in the same
  sub-second window can each query before the other's run appears and both
  proceed — a residual race that is accepted (it fails toward running, never
  toward swallowing a request).
- The check **fails open**: any query error yields `duplicate=false` and the run
  proceeds, because silently swallowing a legitimate single request is worse than
  a rare redundant run.

When a duplicate is ignored, the gate posts a brief notice on the thread.
**Critical:** that notice contains no PRFlow trigger phrase (no `/prflow:…`,
no `@claude`) — the bot's own comment is itself an `issue_comment[created]`
event, and a trigger phrase in it would re-enter the gate and could loop.

### Boundary

Dedupe keys on the issue/PR *thread the command was posted on* (the run-name
number), not on an explicit `/prflow:implement <n>` cross-posted to a different
thread. The dominant duplicate case — the same command repeated on one thread —
is fully covered.

## Duplicate `/prflow:review` commands are deduped by the in-flight review

A second standalone `/prflow:review` on a pull request while a review of the same
pull request is already **in flight** is **suppressed once that in-flight review
has published its live `prflow:review-progress` comment** — the second run's
`command` job is skipped and a notice naming the reason is posted, so a pull
request receives one review rather than several billed engine runs and duplicate
verdicts. Suppression is **conditioned on that published comment**: it is the only
in-flight signal the detector reads, and the engine seeds it inside the peer's
agent job (Phase 0.3.5), so a request arriving in the window after the peer starts
but before it seeds is **not** suppressed — the detector fails open through that
window (see *The pre-seed window* below). The scope is the **pull request**, not
the commit (see the accepted costs below). This is the
command path's analogue of the implement-path dedupe above, and it follows the same
gate-stage doctrine (native `concurrency` cannot express "ignore the duplicate,
leave the in-flight run untouched"). The branch-selecting decision lives in the
bundled helper `scripts/dedupe-review-command.sh`, invoked at its vendored path by
the `review_dedupe` job in `devflow.yml`.

- **How "already in flight" is detected (Candidate C, issue #989).** The review
  engine seeds a **live progress comment** at Phase 0.3.5 — before any review work
  — carrying a run-keyed `prflow:review-progress` marker and `**Status:** 🚀
  Reviewing`. Only the review engine writes that comment, so the candidate
  population is *reviews*, not conversation. The helper suppresses when the PR
  carries such a comment that is **bot-authored** (a forged marker from an ordinary
  commenter is not trusted), **not this workflow run's own** (excluded by the
  `run=<workflow-run-id>-` prefix, deliberately ignoring the attempt suffix),
  still in `🚀 Reviewing` (a terminal-flipped comment is a *completed*
  review, not an in-flight one), and **fresh** — its `updated_at` within a liveness
  window (default 120 minutes), so a *killed* run that froze its comment in
  `🚀 Reviewing` is treated as stale, not in-flight.
- **Exemptions.** `/prflow:review-and-fix` is not deduped (it auto-applies fixes and
  has no automated equivalent), and the `pr-description` flow is untouched. A
  `/prflow:review` carrying the `prflow:review-backstop` marker — the manual path's
  no-verdict auto-resume, posted from inside a still-active run — is **never**
  suppressed, so the resume still fires.
- **Commit scope, via a seed-time head key (issue #1010).** The suppression is
  **commit-scoped**: a review requested while a review of a *different* head is in
  flight proceeds. The engine stamps the head into the comment it seeds at Phase
  0.3.5, as its own machine-only producer key — the HTML-comment marker
  `<!-- prflow:review-seeded-head <sha> -->`, carried in the progress-comment
  template so every in-place rewrite re-emits it, and invisible in the rendered
  comment. It is deliberately **not** the comment's `Reviewed HEAD:` line, whose
  documented meaning is "a review *finished* at this head" and on which two
  consumers depend (Phase 0.3.6's blocker-recheck precondition 2, and
  `scripts/build-experiment-records.py`'s verdict↔finding-count join): stamping
  that line at seed time would make every in-flight comment present as a completed
  review to both. The value recorded is the PR's **API `headRefOid` as Phase 0.2
  resolved it, before any caller head-override** — the same quantity `review_dedupe`
  resolves for the incoming request, which is what keeps the second accepted cost
  below intact when a fix loop is reviewing a locally-committed, unpushed head.
  `MODE=detect` receives that head and requires an **exact** delimited match; an
  in-flight comment carrying **no** such key — one seeded by an installed copy
  predating this change — fails **open** with a breadcrumb naming the absent key,
  because a head that cannot be established is never grounds for suppression.
- **Two accepted, deliberate costs.** With `prflow_review.live_progress_comment_enabled`
  off there is no seeded comment, so nothing is suppressed (present-day behavior);
  and a `/prflow:review` issued during a `/prflow:review-and-fix` run *that seeds a
  live PR progress comment* is suppressed, because that run executes the review engine
  and the suppressed review would have been redundant. The second holds only for a
  hosting run that seeds such a comment, and only while the PR's remote head is the one
  that run seeded on — once the fix loop *pushes*, the remote head has genuinely
  moved and a request naming the new head is a review of a commit nothing is
  reviewing, which the commit scope above correctly lets through. Both were part of
  the Candidate C decision. A third cost — pull-request rather than commit scope —
  was found during PR #993's review and **retired by issue #1010**, which added the
  seed-time head key above.
- **The workpad-surfaced review (issue #1657).** Caller-scoped progress routing lets a
  `/prflow:review-and-fix` run pick its progress surface; an implement-hosted fix loop
  binds `progress_surface = workpad` and seeds **no** live PR progress comment at all
  (the review engine's Phase 0.3.5 — the caller's issue workpad is the surface instead).
  This detector reads only PR comments, so for such a host there is nothing to find and
  the suppression above does not hold: a `/prflow:review` issued during an
  implement-hosted review **fails open for the whole duration of that review**, not
  merely the transient pre-seed window below. Fail-open is the **decided** behavior — no
  new in-flight marker is stamped, because the alternatives are the same two the
  pre-seed-window entry records and rejects (absence-keyed suppression carries no
  `updated_at` to age out and would wedge every later request behind a silently-failed
  seed; a head-blind thread scope over-suppresses), and it costs only a recoverable
  duplicate run, never a swallowed review. Like the pre-seed window, it is an accepted
  fail-open exposure, deliberately **not** a numbered member of the two accepted costs
  above.
- **The pre-seed window (issue #1479).** The seeded progress comment is published
  inside the peer run's *agent* job (Phase 0.3.5), so it does not exist for a period
  after that run starts; a request arriving in that window sees no in-flight comment
  and the detector **fails open** — a second full review of the same head runs and
  is billed. Measured once as a dated observation, not a standing property: **141
  seconds** between the peer's `command` job starting and its progress comment
  appearing on **PR #1469 (2026-08-09)**. Fail-open through the window is the
  **decided** behavior (issue #1479), kept unchanged: keying suppression on the
  comment's *absence* has no `updated_at` to age out and would wedge every later
  request at that head forever if a peer's seed silently failed, and a head-blind
  thread scope suppresses unrelated conversation and legitimate re-requests. So the
  window is a **transient timing exposure** that self-heals the instant the peer
  seeds — deliberately **not** a numbered member of the two accepted costs above
  (whose ordinal "3" still denotes the retired pull-request scope).
- **Fails open in every direction.** A missing/unresolvable operand, a query error,
  an unparseable response, an unresolvable `jq`, or an absent/mis-vendored helper
  all yield *no suppression* with a specific breadcrumb — a missed suppression only
  reproduces the recoverable double-comment, whereas a wrong suppression would
  silently swallow a review the user asked for. A **non-executable** helper is one
  such absent/mis-vendored case: `review_dedupe` guards the helper with `[ ! -x … ]`,
  so a copy tracked `100644` fails the exec test and the job fails open exactly as if
  the file were missing — which is what silently disabled this suppression from when
  the feature landed until issue #1312 restored the helper's `100755` mode. A lost
  executable bit on an `-x`-gated bundled helper is now caught at the desk by
  `lib/test/lint-executable-helper-mode.py` (driven from `lib/test/run.sh`), which
  mechanically derives the guarded-helper set **within its audited population** —
  tracked `.github/workflows/*.yml`, `scripts/*.sh`, `lib/*.sh` — and fails RED when
  a resolved repo helper is not tracked `100755`. That population is not the whole
  tree, and the scope limit is an auditable decision rather than a claim of total
  coverage: the check's own module docstring enumerates its named residuals — today
  the repo-root `install.sh`, whose `$SRC`-anchored guard over
  `scripts/migrate-consumer-tier1.sh` resolves to a materialized source tree rather
  than this checkout, so that helper's tracked mode is asserted by
  `lib/test/modules/tier1-rename-migration.sh` instead.
- **Two legacy signals are retained** for a consumer whose installed copy predates
  the withheld auto-review tier: an in-flight `Devflow Review` check-run on the head,
  and a queued/in-progress `devflow-review.yml` run on the branch. In this tree
  neither fires (nothing posts that check and the workflow is withheld), so the
  in-flight-review signal above is what suppresses here.

The notice text is composed by the same helper (selected by the deciding cause) so
it, too, carries **no** PRFlow/`@claude` trigger phrase — the bot's own notice is an
`issue_comment[created]` event that would otherwise re-enter the gate.
