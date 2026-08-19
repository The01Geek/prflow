# PRFlow Cloud Tier — GitHub Actions setup (optional)

The **local tier** (the skills you run inside Claude Code) needs none of this.
The **cloud tier** makes PRFlow run *autonomously* on your repository: Claude
responds to issue/PR events and `/prflow:review` runs as a required status
check. This guide sets that up.

> Everything here is optional. Skip it entirely and PRFlow still works as an
> in-editor toolkit.

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
path**, and this change does not edit it. A repository collaborator with write, admin or
maintain permission comments `/prflow:review` on a pull request; `devflow.yml`'s `gate` job
authorizes the actor through `scripts/authorize-actor.sh`, and the review runs. **An outside
fork contributor cannot self-trigger a PRFlow review — a repository collaborator must post
the comment.** A consumer can *additionally* opt into having that comment posted
**automatically once CI is green** by copying the documented snippet in
[`workflow-triggers.md`](workflow-triggers.md); it is authorized by the same
`prflow.allowed_bots` gate (see the automatic-review note later in this guide).

**Duplicate `/prflow:review` commands are deduped (issue #989).** A second standalone
`/prflow:review` on a pull request while a review of the **same commit** is already in flight
is **suppressed once that review has published its live `prflow:review-progress` comment** —
the second run's `command` job is skipped and a notice naming the reason is
posted — so a commit receives one review rather than several billed engine runs and
duplicate verdicts. That published comment is the only in-flight signal, and it is seeded inside
the peer's agent job (Phase 0.3.5), so a request arriving before the peer seeds it — a pre-seed
window measured at 141 s on PR #1469 (2026-08-09) — is not suppressed and the detector fails
open through it (issue #1479). The check is **commit-scoped** (issue #1010): the engine stamps the head it
is reviewing into the progress comment it seeds, so a `/prflow:review` requested after pushing a
new commit — with the review of the *previous* commit still running — proceeds and reviews the
new head. An in-flight review seeded before this change carries no such head and is never
suppressed against.
`devflow.yml`'s `review_dedupe` job detects the in-flight review from the review
engine's own seeded live progress comment (`prflow:review-progress`, `🚀 Reviewing`,
bot-authored, fresh) via the bundled `scripts/dedupe-review-command.sh` helper. It **fails
open** in every failure direction (a missed suppression only reproduces a recoverable
double-comment; a wrong one would swallow a review you asked for), never suppresses a
`/prflow:review-and-fix` or a `prflow:review-backstop` auto-resume, and does nothing when
`prflow_review.live_progress_comment_enabled` is off (no seeded comment → present-day
behavior). This repair reaches your repository on upgrade, because `install.sh` copies
`devflow.yml`. Full behavior: [`workflow-triggers.md`](workflow-triggers.md).

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
as long as `workflows["prflow-review"]` is `true` in its `.prflow/config.json`**. Every upgrade
reports that exposure; removal stays an explicit opt-in:

1. Delete `.github/workflows/devflow-review.yml`, `.github/workflows/devflow-runner.yml`
   and `.github/workflows/telemetry-push.yml`.
2. Set `workflows["prflow-review"]` to `false` in `.prflow/config.json`.
3. Remove the `Devflow Review` context from any branch protection rule or ruleset that
   requires it — otherwise every subsequent pull request wedges against a required check
   that nothing will report.

`install.sh --apply --remove-withheld-review-tier` performs steps 1 and 2 (signature-guarded) and
prints step 3, which no installer can perform. The canonical statement is
[`workflow-triggers.md`](workflow-triggers.md).

The removed caller's bytes are preserved on the `preserved/auto-review-tier` branch, whose
`PRESERVATION.md` records the `devflow-runner.yml` object ID it was cut against. Re-shipping
the tier is a **reconstruction against whatever that callee says at that later time**, not a
restore.


## Install (and update) the cloud tier

**Only the cloud tier needs this installer.** Installing the PRFlow *plugin* —
`/plugin install prflow@devflow-marketplace`, or `claude plugin install
prflow@devflow-marketplace` — runs no installer script at all and needs none.
`install.sh` exists solely to add the optional GitHub Actions tier described on
this page; skip it if you only want the `/prflow:*` skills in your editor.

Run it from the root of your repository — it installs the workflows, composite
actions, a local `marketplace.json`, and a `.prflow/config.json` scaffold, and is
**idempotent** — re-running it at a newer release tag is also how you update. It
writes changes into your repository, so download it, read it, then run the file you
read:

```bash
curl -fsSL https://raw.githubusercontent.com/The01Geek/prflow/v2.33.24/install.sh -o devflow-install.sh
# review devflow-install.sh, then:
DEVFLOW_REF=v2.33.24 bash devflow-install.sh
```

Both refs are pinned to the same **release tag**, so the install is reproducible.
The URL ref fixes which *installer bytes* you review and run; `DEVFLOW_REF`
(default `main`, and it accepts a tag, a SHA, or a branch) fixes which ref the
installer clones its payload from — pinning the URL alone still leaves the payload
tracking `main`. Substitute a newer tag in both places to install a newer version;
every version is tagged, so
[the Tags page](https://github.com/The01Geek/prflow/tags) names the current
one (feature releases are additionally announced on
[the Releases page](https://github.com/The01Geek/prflow/releases)). Omit `DEVFLOW_REF` only if you deliberately want to track the moving `main`
branch. Piping the download straight into `bash` also works
(`curl -fsSL <pinned-url> | DEVFLOW_REF=<same-tag> bash`) but skips the review step,
so it is not the recommended form. See
[Installing & updating](install.md#pinning-the-installer) for the same guidance
alongside the local-tier install.

Then review with `git diff` and commit. `.prflow/config.json` ships with a
working default for every value — edit it only to customize.

This is a **thin install**: the bulky plugin tree is **not** committed to your
repo. The workflows fetch it at runtime (see below), pinned to the
`prflow_version` that `install.sh` writes into `.prflow/config.json` — the
commit it installed from. **To update**, bump `prflow_version` to a newer tag,
branch, or commit SHA (or just re-run the installer — now a small diff).
Re-running also **backfills any newly-added config keys** into your existing
`.prflow/config.json` (at any nesting depth) so you can discover and opt into
new features; values you've already set are preserved and your arrays (e.g.
`allowed_tools`) are left untouched. Because the pin is explicit, your CI never
silently tracks a moving `main`.

`prflow_version` gets one narrow exception to "existing values are preserved":
the installer re-stamps it to the commit it just installed from **only when the
current value already looks like a commit SHA** (7-40 lowercase hex chars) or
is empty. This is a **shape heuristic, not true provenance detection** — the
installer cannot tell a SHA it auto-stamped on a previous run apart from a SHA
you hand-set yourself (e.g. to pin to one specific commit for reproducibility),
so a hand-pinned exact SHA is *not* guaranteed to survive a re-run. Only a
**non-SHA-shaped** hand pin — `"main"` to deliberately track the moving branch,
or a tag like `"v1.2.0"` — is guaranteed protected and left untouched on re-run.

> **Prefer to commit the plugin instead?** Run `DEVFLOW_VENDOR=1 … | bash`. That
> vendors the full tree into `.prflow/vendor/prflow/` so nothing is fetched at
> runtime — self-hosting, fully auditable in your repo, at the cost of a large
> vendored diff on every update. `prflow_version` is then ignored.

### Why the plugin lives at a workspace path (not added as a github marketplace in CI)

The local skills locate their helpers via the portable `${CLAUDE_SKILL_DIR:-…}` anchor (with a runner-reported base-directory fallback), but in the
`claude-code-action` runner that variable is unset, the bash sandbox cannot read
`~/.claude` (where a marketplace plugin would install), and `$`-expansion in
commands is blocked. So the workflows reference helper scripts at the **literal
workspace path** `.prflow/vendor/prflow/scripts/…` — the plugin must physically
be at `.prflow/vendor/prflow/` when a job runs.

**Why `.prflow/vendor/` and not `.claude/`.** On every pull request,
`claude-code-action` runs a security step (`restoreConfigFromBase`) *before* it
installs plugins: for each of its `SENSITIVE_PATHS` — as of `claude-code-action`
v1, `.claude`, `.mcp.json`, `.claude.json`, `.gitmodules`, `.ripgreprc`,
`CLAUDE.md`, `CLAUDE.local.md`, `.husky` (see that action's
`src/github/operations/restore-config.ts` for the current set) — it deletes the
path (`rm -rf`) and then restores it from the **base branch**, so a PR can't
inject `.claude/` config into a trusted-token run. A
plugin vendored under `.claude/plugins/devflow/` is therefore wiped: the whole
`.claude/` directory is removed, and the base branch has no vendored tree to
restore, so the subsequent `plugin install` fails with `Source path does not
exist`. Vendoring to `.prflow/vendor/prflow/` — outside every `SENSITIVE_PATH`
— sidesteps the restore entirely; `claude-code-action` performs no other
working-tree-destructive step, so the runtime-vendored tree survives until
install. (A committed `DEVFLOW_VENDOR=1` tree at the old `.claude/` path used to
survive only because the restore re-checked-it-out from base — relocating makes
both install modes robust.)

A thin install satisfies that **at runtime** rather than by committing: every job
that needs the plugin runs the `vendor-plugin` composite action right after
checkout, which materializes the tree via a single deterministic algorithm —
**committed** (already in the checkout, e.g. a `DEVFLOW_VENDOR=1` install → used
as-is), **self** (the source repo, whose plugin lives at its own root → copied
in), or **fetch** (a thin consumer → clones `prflow_version` and copies it in —
shallow when it names a branch/tag, a full clone + checkout when it's the commit
SHA `install.sh` pins). The fetch branch refuses to run without a pinned
`prflow_version`, so a thin install never tracks mutable `main`.

**Which config supplies `prflow_version` differs by tier (issue #874).** The write
tiers read it from their default-branch checkout. The **automated review runner**
(`devflow-runner.yml`) reads it from the **trusted base ref** instead — a dedicated
step, declared above the `vendor-plugin` call so its output is resolvable there,
fetches the base ref and reads `.prflow/config.json` from it — because a
PR-head-supplied value would let a pull request choose the plugin commit, and
therefore the prompt-extension loader, that reviews it. So on the review tier the key
is **in-PR-inert via the base-ref trust boundary** (the same channel
`prflow_runner.allowed_tools` uses — *not* the separate trigger-time channel, in
which a `config` job checks out the **default branch**; the two resolve different
values for a PR targeting a non-default branch). A PR that bumps `prflow_version`
does not change its own review run, only later ones. The read fails **closed** to an
empty value on an unfetchable or empty base ref, a base ref carrying no or a
malformed config, and an absent key — inert on the `committed`/`self` vendor branches,
which ignore the ref, but on the `fetch` branch (the thin-install default) the vendor
step refuses an empty ref and fails the review job, so the step emits a `::warning::`
naming the base ref and the remedy rather than leaving only the vendor step's message.

> **Local editor use is different** — there you add this repo as a github
> marketplace with auto-update and never copy files. Running **`/prflow:init`
> provisions this for you** into the project `.claude/settings.json` (additively,
> never clobbering your values, idempotent on re-run), so you don't hand-edit it.
> This write is **ungated** — `/prflow:init` performs it directly, with no separate
> opt-in step, into a committed file collaborators inherit — and the registration
> carries **no version pin**, so the plugin auto-updates from the marketplace repo's
> default branch (`autoUpdate: true`). (Contrast the consent-gated auto-mode step
> three lines below, which asks before touching your user-global settings.)
> ```jsonc
> // project .claude/settings.json — provisioned by /prflow:init
> {
>   "extraKnownMarketplaces": {
>     "devflow-marketplace": {
>       "source": { "source": "github", "repo": "The01Geek/prflow" },
>       "autoUpdate": true
>     }
>   },
>   "enabledPlugins": { "prflow@devflow-marketplace": true }
> }
> ```
> On a **third-party model provider** (Bedrock / Vertex / Foundry) `/prflow:init`
> can additionally — **only with your explicit consent** — make
> `auto` permission mode **selectable** by writing `CLAUDE_CODE_ENABLE_AUTO_MODE="1"`
> into your **user-global** `~/.claude/settings.json` (it must be user scope —
> Claude Code filters this permission-gating env var out of project settings). It is
> *selectable, never on* (no `permissions.defaultMode` is written), preserves a
> deliberately-disabled `"0"`, and prints the one-line setting instead of writing if
> you decline. On the **Anthropic API the step is skipped** (auto mode is already
> available there by default). This is a **local-tier** convenience only — the cloud runner uses
> claude-code-action's own allowlist profile and consumes no `~/.claude/settings.json`
> (the user-global file, where `CLAUDE_CODE_ENABLE_AUTO_MODE` must live). The cloud tier
> *does* honor the **project** `.claude/settings.json`'s `enabledPlugins`/`extraKnownMarketplaces`
> — see [Honoring `.claude/settings.json` in cloud runs](#honoring-claudesettingsjson-in-cloud-runs) below.

## Honoring `.claude/settings.json` in cloud runs

The three claude-code-action call sites (`devflow-implement.yml`, `devflow.yml`, `devflow-runner.yml`) each compose their `plugins`/`plugin_marketplaces` inputs as the baked baseline (byte-identical across the three) **plus** the entries the repo's `.claude/settings.json` declares — `enabledPlugins` keys whose value is boolean `true`, and `extraKnownMarketplaces` entries with a `github`-kind source (mapped to `https://github.com/<repo>.git`). The composition runs in a step before claude-code-action (`scripts/resolve-extra-plugins.sh`, python3-backed), so a consumer repo's cloud plugin surface matches what its local team already sees — "commit the settings file once, every tier honors it." Every spliced entry beyond the baseline is logged as a `::notice::` so a change to the merge-gating judge's loaded-skill surface is auditable per run, never silent.

**Trusted-ref rule.** The write tiers (implement, command) check out the default branch, so their `.claude/settings.json` is maintainer-committed, trusted. The **review tier** checks out the PR head, so it reads the settings exclusively from the **trusted base ref**: the `baseprovision` step materializes `FETCH_HEAD:.claude/settings.json` into `$RUNNER_TEMP`, and the helper invocation consumes only that materialized path — **never the PR-head checkout's settings file**. The consequence: a PR that edits `.claude/settings.json` does **not** alter its own review run's plugin list (the review reads the base-ref copy); the change takes effect on the *next* run after the PR merges. The helper itself runs only from a trusted source on the review tier (base-ref materialized, or the vendored copy only when `vendor_source == "fetch"`); when no trusted copy is available the step appends nothing and emits the baseline with a `::warning::` naming the trusted-source rule. An absent settings file (the normal consumer case) leaves the composed inputs identical to the baked baseline, silently.

**Trusted-ref rule — `.prflow/prompt-extensions/` (issue #874, extended to the shipped command tier by issue #1075).** Both cloud tiers that run the review engine now bind this rule; what differs is the mechanism, because the untrusted tree arrives by a different route on each.

**`devflow.yml`'s `command` job** — the review path actually reachable in a consumer, covering `/prflow:review`, `/prflow:review-and-fix` and `/prflow:pr-description` — carries a `promptext` step that **unconditionally** creates `$RUNNER_TEMP/devflow-trusted-prompt-ext/` and exports `DEVFLOW_PROMPT_EXTENSION_ROOT` at it, then **conditionally** — inside its own base-ref fetch-success branch and nowhere else — populates it from the pull request's base ref through the same `scripts/materialize-trusted-prompt-extensions.sh`. Its protected set is the closed set those three commands can load (`review`, `requesting-code-review`, `review-and-fix`, `receiving-code-review`, `pr-description`), declared once as a job-level `env:`. As of issue #1163 this workflow runs on `issue_comment` alone with every checkout pinned to the default branch, so the job's own checkout is **always the default branch** and the exposure is never the checkout: `/prflow:review-and-fix`'s Step 0.5 runs `gh pr checkout` and moves the working tree to the PR head before the engine loads `review` and before Phase 3.1 loads `requesting-code-review`. Step 0.5 is a **fail-closed gate**: it asserts, before any Phase 0.2 diff or review work, that the checked-out branch equals the PR's head ref **and** that local `HEAD` equals the PR's head commit, and stops with a named cause on a failing `gh pr checkout`, on either mismatch, or on a head ref or head commit that could not be resolved — so a run that cannot reach the PR head neither reviews nor commits against the wrong branch. Where it diverges from the runner it does so deliberately. It does **not** truncate the workspace copies: this tier is write-capable, so a truncation would dirty the tree `gh pr checkout` refuses to run against and would be committed to the contributor's branch by the fix loop; a `::warning::` naming a vendored `load-prompt-extension.sh` that predates the variable replaces that belt. And it uses **no** three-rank trusted-source ladder for the materialization helper, because the workspace is the trusted default branch at checkout and turns untrusted only when Step 0.5's `gh pr checkout` moves it to the PR head — at which point a pull request that can edit that helper can equally edit the loader that consults the closure, which no ladder reaches. Residuals for that tier (the PR-head bytes the agent itself introduces once Step 0.5's `gh pr checkout` moves the tree — the composite actions and the `./`-resolved marketplace are *not* among them since #1163 pinned this job's checkout to the default branch — a stale pinned `prflow_version`, the local/interactive `/prflow:review-and-fix` path, and the deeper adversarial residual that a write-access actor can exfiltrate secrets via a workflow edit) are recorded with the others in [`DEVFLOW_SYSTEM_OVERVIEW.md`](DEVFLOW_SYSTEM_OVERVIEW.md)'s base-ref-trust-boundary bullet.

**Step 0.5 on the implement-inline path (issue #1640) — the tier split.** Since Phase 3.3 passes the
draft PR number, `/prflow:implement`'s inline fix loop reaches Step 0.5 too, but its capability surface
differs from the `devflow.yml` command tier above. `Bash(gh pr checkout:*)` is granted in the `command`
profile only; it is **ungranted in the `implement` profile**, so on the cloud implement tier the
`gh pr checkout` is refused before it runs and emits no `checkout-rc=` token. Step 0.5 answers that
**absent token** not with a stop but with its own **head-ref and head-commit assertion** — `git branch
--show-current` equals the PR's `headRefName` **and** `git rev-parse HEAD` equals its `headRefOid` — which
is the gate on that path (the assertion is the sole authority when the token is absent; every command it
needs is granted on every profile). The tree is already at the PR head there because Phase 1.5 pushed the
branch with upstream tracking and Phase 3.1 pushed to it, so the checkout's tree-moving and upstream-tracking
side effects are not needed. This does **not** change the statement above for the `devflow.yml` command
tier, where `gh pr checkout` **is** granted and moves the working tree to the PR head as the gate.

For the **automated runner** (`devflow-runner.yml`, withheld from this release by issue #936): the same rule binds the reviewer's own appended prompt, and for the same reason: on the review tier `.prflow/prompt-extensions/<skill>.md` comes from the PR head, and `skills/review/SKILL.md` treats whatever the loader prints as instructions appended to its own prompt. So the review job takes two steps. **Unconditionally**, on every run and outside every branch, it creates `$RUNNER_TEMP/devflow-trusted-prompt-ext/`, creates `.prflow/prompt-extensions/` in the workspace, truncates the workspace copy of each protected extension (`review`, `requesting-code-review`) to empty — creating an empty file for a name the checkout never carried — and exports `DEVFLOW_PROMPT_EXTENSION_ROOT` pointing at that closure. **Conditionally**, inside `baseprovision`'s base-ref fetch-success branch and nowhere else, it populates the closure from `FETCH_HEAD` through `scripts/materialize-trusted-prompt-extensions.sh`, itself resolved through the same trusted-source rank ladder the deny floor uses. The consequence mirrors the settings rule: a PR that edits `.prflow/prompt-extensions/review.md` does **not** change its own review run's prompt; the change takes effect after merge. Because the suppression is unconditional and the population is not, each non-population arm — a failed base-ref fetch, an empty base ref, an unresolvable materialization helper, a per-name read failure or unwritable target, a helper usage defect, a traversal-shaped protected name, and a non-blob object at a protected path — degrades to an empty closure, never to the PR-head file. The three not-established arms — a failed base-ref fetch, an empty base ref, no trusted source for the helper — emit a *not-attempted* notice rather than a reason-naming warning, because a run that never read the base ref cannot say whether an extension exists on it. A base ref that simply carries no extension is the ordinary consumer shape and is **silent**. **Upgrade window:** a consumer whose base ref pins a `prflow_version` predating #874 gets a loader that ignores the variable; the truncation is the only control there, and their committed extension does not load until they bump the pin. That fallback control is sound: `claude-code-action`'s restore pass replaces a **closed, enumerated** set of sensitive paths from the base branch — `.claude`, `.mcp.json`, `.claude.json`, `.gitmodules`, `.ripgreprc`, `CLAUDE.md`, `CLAUDE.local.md`, `.husky` (read from the pinned action's `src/github/operations/restore-config.ts`) — and `.prflow/` is not among them, so the truncated workspace copies survive into the agent's session rather than being restored from either branch.

**Security posture (a decided trade, not an implication).** Honoring `enabledPlugins` splices **unpinned** third-party content into credentialed runners: what the maintainer approves is a pointer (`plugin@marketplace`); what executes is the marketplace repo's content at run time — including plugin hooks, which run with the job's credentials (on the implement tier, the App token). This is accepted deliberately as the price of parity: it is the same live-pointer supply chain the repo's local team already runs under (auto-updating marketplaces) — a condition **`/prflow:init` itself establishes**, by provisioning the project `.claude/settings.json` with an unpinned, `autoUpdate: true` marketplace registration (the "Local editor use is different" aside above). Stating that attribution is the point: the appeal is not to a pre-existing external fact but to a condition DevFlow creates, and a maintainer who commits a marketplace pointer to the trusted ref accepts that marketplace's supply chain. The trade itself is unchanged; only its justification is made non-circular. The composed risk (unpinned content × runner credentials, which local sessions do not carry) is stated here as a named security decision, not implied. Plugin versions are not pinned (marketplace-latest, matching local sessions); a private-repo marketplace installs locally but is not clonable by the runner's credentials — the action's behavior on a failed install (which a `matcher-probe.yml`-style dispatch with an intentionally uninstallable spliced entry would record as probe evidence in the issue/PR) is stated here as the expected post-compose failure symptom, not a claim that such a dispatch has already been run.

## Required secrets

Add these as repository (or environment) secrets under **Settings → Secrets and
variables → Actions**:

| Secret | Used for | Notes |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Authenticates the Claude Code action (`/prflow:implement`, `/prflow:review` runners) on the Anthropic default path | From your Anthropic account. Optional only if **every** active workflow section routes through a third-party `provider`. |
| `GITHUB_TOKEN` | (built in — no action needed) | Provided automatically to workflows. |
| `DEVFLOW_PROVIDER_API_KEY` | (optional) API key for a third-party model provider, consumed when a `devflow` / `prflow_implement` / `prflow_runner` section sets `provider` | Only needed if you opt into third-party model routing — see [Third-party model providers](#third-party-model-providers-opt-in-best-effort). One fixed secret name regardless of provider count. |

That's the whole default — **no GitHub App is required** and `CLAUDE_CODE_OAUTH_TOKEN` is the only secret. Opting a workflow section into a third-party model provider (below) adds exactly one more, `DEVFLOW_PROVIDER_API_KEY`. (Earlier versions needed
one purely so a bot-authored "implement this" comment could re-trigger the
workflow; a human `/prflow:implement <#>` comment is itself a native user event,
so that need is gone.)

## Why these settings are still called `DEVFLOW_*` — and what happens if you rename them

The product was renamed DevFlow → PRFlow, and the rename stopped at the repository's own
files: the state directory, the vendored plugin path and the config keys moved, and
`/prflow:init` migrates all four together. The **variables, secrets and environment
overrides below did not move**, and they are not going to move on their own.

They live outside the repository — in GitHub's settings and in your shell profile — so
nothing PRFlow ships can migrate them. More to the point, **nothing in PRFlow reads a
`PRFLOW_*` equivalent**: every one of these names is read under its `DEVFLOW_` spelling
and under no other. So renaming one is not a migration. It is a deletion.

**It is also, in almost every case, a *silent* deletion.** GitHub has no concept of "this
variable used to be called something else": an unresolvable `vars.X` evaluates to the
empty string, which is exactly what a variable you deliberately never configured
evaluates to. Every gate that reads one takes its "not configured" arm, every job
falls back to its default, and the run goes **green** — under a degraded identity, or on
a runner you did not choose. The advisory below therefore states, for each name, what
renaming it actually does.

If the brand inconsistency bothers you, the answer is a future PRFlow release that
accepts both spellings — not a rename you perform yourself today.

<details>
<summary>How this list is derived (and why it is not hand-drawn)</summary>

A `DEVFLOW_*` name is consumer-facing if either arm selects it: **(A1)** it appears as
`secrets.<NAME>` or `vars.<NAME>` in a workflow `install.sh` ships, or **(A2)** it is read
as an ambient environment variable by a shipped `install.sh` / `scripts/` / `lib/` file
*and* is declared in a consumer-facing document. The tree defines close to two hundred
`DEVFLOW_*` names; almost all are internal, and A2's doc-declaration clause is what keeps
harness tuning knobs out of a list whose whole value is that every row on it matters.

The criterion is machine-run, not transcribed: `lib/rename-map.json`'s
`frozen.env_identifiers` block records the population and the two names adjudicated out of
it, `lib/generate-env-freeze-advisory.py` renders the table below from that block, and the
test suite re-runs both arms over the tree on every run. A workflow that starts reading a
new `vars.DEVFLOW_*` name — or a name here whose read side goes away — turns the suite red
until someone adjudicates it.

</details>

<!-- prflow-env-freeze:begin freeze_version=1 sha256=83e38517a288860f4311150801dc113ad42361758a9007239d49d4bacb832314 (generated by lib/generate-env-freeze-advisory.py -- do not hand-edit; source: lib/rename-map.json frozen.env_identifiers) -->
> **These names are frozen. Do not rename them.** PRFlow reads each one under its `DEVFLOW_` spelling and under no other spelling — there is no `PRFLOW_*` equivalent anywhere in the plugin. Renaming one of these does not move a setting; it removes it.

**The two GitHub App pairs fail asymmetrically.** The asymmetry inverts what a careful consumer would guess. Rename the SECRET alone and the mint step fails loudly — you find out immediately. Rename the VARIABLE alone and nothing fails: the mint is gated on `vars.<NAME> != ''`, an unresolvable name reads exactly like `deliberately not configured`, so every job falls back to `steps.app-token.outputs.token \|\| secrets.GITHUB_TOKEN` and the run goes GREEN under a degraded identity. Rename BOTH — the natural thing to do, since they are one setting in the consumer's head — and the variable's silent skip gates off the secret's loud guard, so the loud half never runs. The safe rename order is therefore the one nobody would guess, which is the reason this block exists.

#### Set in GitHub — repository or organization settings

You set these under **Settings → Secrets and variables → Actions**. PRFlow can only read them.

| Identifier | Where you set it | Renaming it fails | What renaming it does |
|---|---|---|---|
| `DEVFLOW_APP_ID` | repository or organization variable — GitHub → Settings → Secrets and variables → Actions → Variables | silent | Silent feature loss, the largest blast radius here. Every mint gate reads `vars.DEVFLOW_APP_ID != ''`, so an unresolvable name turns every gate false and every consumer falls back to `steps.app-token.outputs.token \|\| secrets.GITHUB_TOKEN`. The run stays green. What breaks is all downstream and none of it names the cause: pushes touching `.github/workflows/` are rejected with `refusing to allow a GitHub App to create or update workflow ... without workflows permission` (which reads as a missing App permission, and the App permission is fine); the credential refresher still reports `credential refresher started (detached)` while its empty-input arm writes `cannot mint` into a redirected log nobody reads, so long implement runs die on an expired token with no trace; and PR authorship and review attribution move to `github-actions[bot]`, which does not satisfy a branch-protection required-approval rule. |
| `DEVFLOW_APP_PRIVATE_KEY` | repository secret — GitHub → Settings → Secrets and variables → Actions → Secrets | loud, but only while its paired variable still resolves | The mint step fails loudly with an unusable private key — provided `vars.DEVFLOW_APP_ID` still resolves and the step therefore runs at all. Rename the variable as well and the gate is already false, the mint never executes, and this loud guard is gated off: see `pair_asymmetry`. |
| `DEVFLOW_REVIEWER_APP_ID` | repository variable — GitHub → Settings → Secrets and variables → Actions → Variables | silent | Silent identity reversion. This is the GATING half of the reviewer pair: unresolvable, the reviewer mint is skipped exactly as if you had chosen not to configure a reviewer App, and review attribution falls back to the default token. Nothing reports it, and a branch-protection rule that requires an approval from a non-`github-actions[bot]` identity silently stops being satisfiable. |
| `DEVFLOW_REVIEWER_PRIVATE_KEY` | repository secret — GitHub → Settings → Secrets and variables → Actions → Secrets | loud, but only while its paired variable still resolves | The reviewer mint fails loudly with an unusable private key — provided `vars.DEVFLOW_REVIEWER_APP_ID` still resolves. Rename the variable too and the gate is false, the mint is skipped, and the loud guard never runs: see `pair_asymmetry`. |
| `DEVFLOW_PROVIDER_API_KEY` | repository secret — GitHub → Settings → Secrets and variables → Actions → Secrets | loud on the provider path; unread otherwise | If a config section sets `provider`, the run refuses with an `::error::` naming DEVFLOW_PROVIDER_API_KEY — the one cloud row that fails loudly on its own. If no section routes through a third-party provider the secret is never read, so a rename is invisible until the day you opt into provider routing, at which point the error names a secret you believe you have set. |
| `DEVFLOW_RUNNER` | repository or organization variable — GitHub → Settings → Secrets and variables → Actions → Variables | silent **⚠ highest severity** | SILENT RUNNER RELOCATION, and the highest-severity outcome in this table. Unresolvable, the expression takes its `\|\| 'ubuntu-latest'` arm and EVERY job silently moves to a GitHub-hosted runner. That same job carries `secrets.DEVFLOW_APP_PRIVATE_KEY` and `secrets.DEVFLOW_PROVIDER_API_KEY` in its environment — so a consumer who self-hosts for network isolation or compliance has their GitHub App private key and their model-provider API key executed OUTSIDE the boundary they chose self-hosting for. Nothing errors, no job fails, and no log line names the cause; the only visible difference is the runner label in a page nobody re-reads after setup. Note the contrast with a MIS-SET value: a `DEVFLOW_RUNNER` that begins `[` but is not valid JSON fails loud at evaluation time. It is the name going missing, not the value being wrong, that is silent. |

#### Set on your machine — shell profile or install one-liner

You set these in your own environment. Every one resolves through a `${NAME:-…}`-style default, so a name that stops resolving is byte-identical to one that was never set.

| Identifier | Where you set it | Renaming it fails | What renaming it does |
|---|---|---|---|
| `DEVFLOW_BASH` | environment variable — your shell profile, or the invocation that launches the runner | silent | Silent reversion to whichever bash the host happens to select. On a healthy POSIX-bash host that is a no-op, so the rename looks successful; on the Windows host the override existed for, the shell helpers go back to running under whatever the launcher picks, and the preflight remedy naming WSL/Git Bash/MSYS2 bash returns. |
| `DEVFLOW_GH` | environment variable — your shell profile | silent | Silent PATH reversion, and the worst kind of silent: on a host where the probe already finds a working `gh` the rename changes nothing observable, so the consumer concludes it worked. On the Windows/WSL host the override existed for, it silently restores the shadowing-`gh` bug the override was added to route around — a present-but-unrunnable `gh` shim is selected again, and every `gh` call degrades to its best-effort empty-result path. |
| `DEVFLOW_JQ` | environment variable — your shell profile | silent | Silent PATH reversion, identical in shape to DEVFLOW_GH: a no-op on a host whose probe already resolves a working `jq`, so the rename appears to have worked, and a silent return of the shadowed-binary problem on the host that needed the override. |
| `DEVFLOW_REF` | environment variable (install-time) — the install one-liner — `DEVFLOW_REF=<tag> bash devflow-install.sh` | silent | Silent un-pin. Unresolvable, install.sh takes its `:-main` default and clones mutable `main` instead of the tag you named. The install succeeds, reports a version, and stamps `prflow_version` — with a ref you did not choose. A consumer pinning a known-good release to avoid an upgrade gets the upgrade, and the only evidence is the version the installer echoes. *Dual role:* Also an INTERNAL input: `.github/actions/vendor-plugin/action.yml` assigns DEVFLOW_REF for vendor-slice.sh's fetch branch, sourced from the consumer's `prflow_version`. That internal producer never reaches install.sh, so the name is consumer-facing here and internal there. It is not purely one or the other. |
| `DEVFLOW_VENDOR` | environment variable (install-time) — the install one-liner — `DEVFLOW_VENDOR=1 bash devflow-install.sh` | silent | Silent mode reversion to a thin install. The plugin tree stops being committed and is fetched at runtime instead, which is the opposite of what a consumer who set this wanted — typically an air-gapped or supply-chain-pinned repository. The installer says `thin install: the plugin is fetched at runtime`, which is a truthful line that reads as normal output rather than as a setting having been lost. |
| `DEVFLOW_DRY_RUN` | environment variable (install-time) — the install one-liner — `DEVFLOW_DRY_RUN=1 bash devflow-install.sh` | silent, and the only row that WRITES as a result | The only name here whose rename causes a WRITE. On a FIRST-TIME install the default mode is apply, so the preview you explicitly asked for silently becomes an apply and the installer writes to your repository. (On an existing install the default is already preview, so there the rename is a silent no-op.) The equivalent flag `--dry-run` is unaffected — an unknown flag is rejected outright, which is exactly the loudness the environment channel lacks. |
| `DEVFLOW_APPLY` | environment variable (install-time) — the install one-liner — `DEVFLOW_APPLY=1 bash devflow-install.sh` | silent | Silent no-write on an upgrade. An existing install defaults to preview, so the upgrade you believe you applied only previewed: the repository is unchanged and keeps running the previous workflows and the previous pin. The run exits 0 and its last line is the ordinary dry-run notice. The equivalent `--apply` flag is unaffected. |

Not on this list and wondering why: `DEVFLOW_PROMPT_EXTENSION_ROOT` is written by the cloud workflows that run the review engine and never set by you, and `DEVFLOW_CONFIG_FILE` is an internal seam that has never been published as a consumer setting. Both are recorded with their reasoning in `lib/rename-map.json`.
<!-- prflow-env-freeze:end -->

## Choosing the runner (`DEVFLOW_RUNNER`)

By default every job in the two consumer-shipped workflows (`devflow.yml`,
`devflow-implement.yml`) runs on `ubuntu-latest`. An optional GitHub
**repository or organization variable** — `DEVFLOW_RUNNER` — selects the runner
for all of those jobs uniformly. Set it under **Settings → Secrets and variables
→ Actions → Variables** (a *variable*, not a secret). Runner selection is
**infrastructure** — which machine runs the job — so it lives in GitHub Settings,
deliberately **not** in the versioned `.prflow/config.json` (which governs how
PRFlow behaves).

| `DEVFLOW_RUNNER` value | Rendered `runs-on` |
|---|---|
| unset **or** empty string | `ubuntu-latest` (byte-for-byte the previous behavior — existing Linux adopters set nothing and see no change) |
| a bare single label, e.g. `windows-latest` | that single-label runner |
| a JSON array, e.g. `["self-hosted","windows","PRFlow"]` | a runner matching that label set |
| begins with `[` but is **not** valid JSON | the job fails **loud** at evaluation time (a visible `fromJSON` error), not a silent fallback to `ubuntu-latest` — a mis-set variable surfaces as an error |

Both workflows also declare a top-level `defaults: run: shell: bash`,
so `run:` steps execute under **bash** even on a non-Linux runner (a self-hosted
Windows runner otherwise defaults to PowerShell/cmd). On Linux this changes nothing
observable. (A repository that installed the withheld auto-review tier before it was
pulled still carries `devflow-runner.yml` and `telemetry-push.yml`; those honor
`DEVFLOW_RUNNER` and declare the same `defaults:` block, but `install.sh` no longer
ships them — see [above](#withheld-from-this-release-the-automatic-pull-request-triggered-review-tier).)

### Self-hosted-runner prerequisites

`ubuntu-latest` supplies `git`, `gh`, `jq`, `python3`, bash, and Docker for free.
A self-hosted runner **owns its own toolchain** — it must provide them. PRFlow's
`lib/preflight.sh` *checks* for the required tools but does **not** install them.
Before pointing `DEVFLOW_RUNNER` at a self-hosted runner:

- Install `git`, `gh`, `jq`, and a POSIX **bash** on the runner. `defaults: run:
  shell: bash` requires **Git Bash** (or equivalent) on the runner's PATH.
- On a **Windows / Git-Bash** runner, make `python3` resolve via the existing
  `scripts/provision-python3-shim.sh --apply` (a one-time runner-provisioning step,
  not a workflow change).
- Use `DEVFLOW_GH` / `DEVFLOW_JQ` / `DEVFLOW_BASH` to point PRFlow at tools in
  non-standard locations (see [Installing & updating](install.md) for the local-tier
  binary overrides — the same env vars apply on the runner).

### Windows: point the action at a pre-installed Claude Code (`setup.claude_code_executable`)

`anthropics/claude-code-action@v1` installs the Claude Code CLI with a **Unix-only**
bundled installer. On a self-hosted **Windows** runner that installer aborts before
Claude ever starts (`Windows is not supported by this script … Failed to install
Claude Code after 3 attempts`), so a `/prflow:*` cloud job fails immediately even
when the runner is otherwise correctly provisioned.

To run PRFlow cloud jobs on such a runner, **pre-install the Claude Code CLI on the
runner** (e.g. `irm https://claude.ai/install.ps1 | iex`) and set the optional config
key `setup.claude_code_executable` to the resulting executable's path:

```jsonc
{
  "setup": {
    "claude_code_executable": "C:\\Users\\runner\\.local\\bin\\claude.exe"
  }
}
```

All three PRFlow workflows (`devflow.yml`, `devflow-implement.yml`,
`devflow-runner.yml`) forward this value to the action's
`path_to_claude_code_executable` input. When it is set, the action **skips its
installer and uses the named executable**; when it is **unset or empty (the default,
and every Linux consumer)** the input resolves to an empty string and the action's
automatic-install path runs unchanged — Linux consumers are unaffected.

**A rejected value falls back to auto-install and says so.** The extraction accepts only a
single-line, non-blank string: a non-string leaf (array/object/number/boolean), a non-object
`setup` block, a string carrying an embedded newline or carriage return, and a whitespace-only
string are each rejected and resolve to empty — the same result as leaving the key unset.
Because a mistyped path would otherwise
revert *silently* to the Windows-fatal auto-install path (leaving you debugging the installer's
misleading `Windows is not supported` error rather than your own typo), a **set-but-rejected**
value emits a workflow `::warning::` naming the key. An absent key, a JSON `null`, and an
explicit `""` are deliberate unsets and warn nothing.

**Effect is post-merge-only.** Unlike the `setup.*` keys the implement job reads at
**runtime** from the checked-out working tree (`setup.install`, `setup.node_version`,
`setup.services` — live in the same run), this key is resolved at **trigger time** (the workflows' `config` job — and, for `devflow-runner.yml`, the
trusted base-ref `baseprovision` step — read config from the default/base branch), so
a PR that *adds* the key cannot exercise it in that PR's own cloud run. It takes effect
only after the change merges to the default branch. (For `devflow-runner.yml` the value
is read **only** from the trusted base-ref config, never a PR-head-checked-out config,
because that job runs under a write token and the action executes the resolved path — a
PR-author-controllable path would be an arbitrary-code-execution vector.)

### Windows: the two opt-in git-env pins (`setup.git_dir_pin`, `setup.git_work_tree_pin`)

Two **independent** boolean keys, **both defaulting to `false`**, govern whether
PRFlow exports `GIT_DIR` and `GIT_WORK_TREE` into the cloud job environment before
the `Run Claude Code` (`anthropics/claude-code-action@v1`) step. With both off — the
default, and the configuration that works everywhere — neither variable is present
in the action's environment and all three tiers behave exactly as they did before
these variables were introduced.

```jsonc
{
  "setup": {
    "git_dir_pin": false,        // export GIT_DIR=<workspace>/.git
    "git_work_tree_pin": false   // export GIT_WORK_TREE=<workspace>
  }
}
```

**Why they are opt-in and separate.** An earlier release set both variables
unconditionally, so the action's `configureGitAuth` startup would resolve the
repository on a self-hosted Windows runner (otherwise — **inferred**, and only in
the both-pins-off default — it aborts `fatal: not in a git directory`, exit 128,
before the agent does any work; see the evidence label below the table). But
`GIT_WORK_TREE` also reaches the Claude Code CLI subprocess that installs plugins,
where it makes `git clone` refuse an existing working tree — so **every** cloud run
died at plugin install with `fatal: working tree '<path>' already exists.`,
producing not a wrong verdict but no verdict at all. The two variables serve
different populations and carry different costs, so they are now decoupled.

**What each of the four combinations costs.** The two keys are independent, so this
set is closed by construction:

| `git_dir_pin` | `git_work_tree_pin` | `configureGitAuth` | Plugin install | `git rev-parse --show-toplevel` from a subdirectory |
| --- | --- | --- | --- | --- |
| `false` | `false` (**the default**) | **inferred** fail — one completed self-hosted-Windows run contradicts it, pending the git-env evidence named below | succeeds | repository root |
| `true` | `false` | succeeds | succeeds | **the subdirectory** — see the silent-miss hazard below |
| `false` | `true` | succeeds | **fails** unless your marketplace list is local-only | repository root |
| `true` | `true` | succeeds | **fails** unless your marketplace list is local-only | repository root |

The `configureGitAuth` column is **inferred** from the pinned action's upstream
source plus a local `git config` proxy, with one exception now on record. A
`/prflow:implement` job has completed on a self-hosted Windows runner
(maintainer-reported from a consumer's runner, 2026-07-21; not independently
reproducible from this repository, and no run identifier is committed here —
the run belongs to a third party's repository and no reader here could resolve
it). What that establishes is narrow and certain: `configureGitAuth` did not
abort on that run. The consumer had set `git_dir_pin` and `git_work_tree_pin`
alike to `true`, yet neither variable was in force. `GIT_DIR` was **necessarily
absent** — `scripts/emit-git-env.sh` suppresses the assignment on the implement
tier regardless of the configured value, and `git_dir_pin` is not honored on
that tier at all. `GIT_WORK_TREE` is **inferred** absent rather than read: the
run's plugin install completed, and this table records as measured that an
exported `GIT_WORK_TREE` fails that install unless the marketplace list is
local-only, so the completed install is *consistent with* the variable having
been absent — which is weaker than asserting it was. That inference carries a
**named falsifier**: the plugin-install measurement was taken on this
repository's own **ephemeral** hosted runners, where the marketplace is cloned
fresh on every run, while the observation comes from a **persistent
self-hosted** runner, where a pre-existing marketplace checkout could make the
clone a no-op so the documented failure would never fire — a completed run with
`GIT_WORK_TREE` exported is therefore not excluded. The evidence that would
replace the inference with a direct observation is the run's **git-env step
output**, which has not been read. The plugin-install and working-tree-resolution
columns are measured. Treat the `git_dir_pin`-on path as **unverified on
Windows**.

**`git_work_tree_pin` serves a narrow population: adopters whose composed
marketplace list is local-only.** Such a run never performs the remote clone the
variable breaks, so for them it is **inferred** to fix `configureGitAuth` while
keeping working-tree resolution correct — the one combination that avoids the
`git_dir_pin` relocation hazard entirely. **Enabling it outside that population reproduces the outage above.**

**`git_dir_pin` is not honored on the implement tier.** That tier stages and pushes
commits, and ambient `GIT_DIR` makes a stage issued from a non-root working
directory record deletions across the rest of the tree. `devflow-implement.yml`
ignores the key and the helper prints a breadcrumb naming that it did; only
`git_work_tree_pin` can be opted into there.

**Silent-miss hazard when `git_dir_pin` is enabled.** Under ambient `GIT_DIR`,
`git rev-parse --show-toplevel` returns the *current subdirectory* rather than the
repository root. PRFlow's repo-root config readers — `config-get.sh`,
`workpad.py`, `load-prompt-extension.sh`, `match-deferrals.py` and
`match-lint-adjudications.py` — all anchor `.prflow/` on that command, so whenever
one of them runs from a non-root working directory it resolves a `.prflow/` that
**does not exist**. (`load-prompt-extension.sh` anchors that way only on its
*fallback* branch since issue #874: when `DEVFLOW_PROMPT_EXTENSION_ROOT` is set and
non-empty — which the cloud review tier does — it composes the path from that value
and never calls `git rev-parse`, so ambient `GIT_DIR` cannot misdirect it there.) The resulting failure is a **silent miss**, not an error: the
reader falls back to its default and nothing says so. **A run with `git_dir_pin`
enabled is therefore not a config-faithful run.** Because that failure mode is
otherwise undetectable, the helper emits a loud stderr warning naming it on every
run that exports `GIT_DIR`.

**The export is job-scoped, not step-scoped.** The mechanism appends assignments to
`$GITHUB_ENV`, which offers no removal verb, and the empty-value form that would
approximate one is fatal to git (`GIT_DIR=` yields `fatal: not a git repository: ''`).
GitHub's workflow syntax accepts no expression evaluating to a whole `env:` mapping,
so a variable's *key* cannot be made conditionally absent through an `env:`
expression — hence the append. Consequently an enabled variable is in force for
`Run Claude Code` **and every step after it**, including the agent's own git
operations.

**Both keys are read at trigger time from a trusted tree**, so their effect is
**post-merge-only**: `devflow.yml` and `devflow-implement.yml` resolve them in their
`config` job (which checks out the default branch), and `devflow-runner.yml`
resolves them from the trusted base-ref config its `baseprovision` step
materializes — never the PR-head checkout. A key set only in a PR head has no effect
on that PR's own run, and on the review tier the helper itself is executed only from
a trusted source (base-ref-materialized, or the vendored copy when the vendor step
reports `vendor_source: fetch`), else the step fails closed and warns.

**Two-channel upgrade ordering.** The workflows reach you through `install.sh`'s
file-copy, while the helper reaches you through the `prflow_version` vendor fetch.
A consumer who re-runs `install.sh` **without advancing `prflow_version`** therefore
gets the step before the helper. That is safe: an absent helper makes the step emit
no assignment and exit 0 — it **fails open to the working default** rather than
failing the job — which is exactly what keeps that skew from reproducing the
checkless-run outage.

### The `setup.services` Docker caveat

`setup.services` (see [Service containers](#php-service-containers-and-dependency-caching)
below) provisions databases/caches via `docker run`, and any `Bash(docker:*)` path
relies on Docker being present. Docker is **preinstalled on `ubuntu-latest`** but is
**not** guaranteed on a self-hosted non-ubuntu runner — so on such a runner
`setup.services` and Docker-dependent build steps can break unless you install
Docker on the runner yourself.

### Gotcha: a mismatched label array queues forever

If a JSON-array `DEVFLOW_RUNNER` value's label set does **not exactly match** a
registered runner's labels, GitHub does not raise an error — the job sits
**queued indefinitely** with no failure. Match the label set exactly to a
registered runner.

### Windows: POSIX mode bits do not constrain the credential files

**Resolved (issue #690).** With a GitHub App configured, both writer tiers run
`scripts/install-gh-wrapper.sh`, whose output 5/7 used to assert that the token
**fingerprint** file's POSIX mode was exactly `600`. On a native-Windows `python3`
(`os.name == 'nt'`) `os.stat()` synthesizes the permission bits from the
`FILE_ATTRIBUTE_READONLY` bit alone, so a writable file reports `666` and `600` is
simply not reachable — the assertion failed on every run and the `claude` job aborted
at that step, *before the agent started*. The gate is now platform-aware: on a
`posix` platform token it behaves exactly as before (`600` passes, anything else exits
1 naming `fingerprint-mode`), and on an `nt` token the mode value stops being a
failure condition and the installer writes an `install-gh-wrapper:` stderr line
recording that the owner-only guarantee could not be established. No `chmod` is
involved — Windows honors only the read-only flag, so `os.chmod` could not repair it.

The relaxation is scoped to the **interpreter build**: only a native Windows CPython
(python.org, `mingw-w64-*-python`) reports `nt`. The Cygwin-derived `msys/python`
build reports `posix` and keeps the strict comparison, as does any Linux host whose
`RUNNER_TEMP` sits on a filesystem that does not honor mode bits (WSL DrvFs without
`metadata`, CIFS/SMB, exFAT/FAT) — such hosts keep failing the gate deliberately,
because relaxing on a `posix` token would disable the guarantee on real POSIX runners.

**The weakened guarantee is real, and accepted rather than fixed here.** On Windows,
mode `666` grants **write** as well as read to every local principal, and the same is
true of the sibling credential file `scripts/refresh-app-credentials.sh` writes (whose
`umask 077` and `chmod 600` are equally ineffective there) — that file carries the
App token itself rather than a hash, so the exposure is strictly worse. A local
principal able to rewrite the fingerprint file can force every wrapped `gh` call down
the defer arm, costing the run the refresher's purpose once the job outlives the
token's 60-minute lifetime. Both exposures pre-date this change; it extends their
duration to the length of the run rather than creating them, on the basis that a
self-hosted runner is single-tenant by its own trust model. Narrowing them is tracked
separately.

Clearing this blocker does **not** by itself make the tier usable — see the
`setup.git_dir_pin` / `setup.git_work_tree_pin` table above for the next
**inferred** blocker (one completed self-hosted-Windows run now contradicts that
inference; the evidence label beside the table states what it does and does not
establish), and note that `git_dir_pin` is not honored on the implement tier.

### Dispatch-enabled, not certified — run a smoke test first

Setting `DEVFLOW_RUNNER` makes a self-hosted / Windows runner **selectable** and
forces bash for `run:` steps. It does **not** certify that every inline bash body
runs correctly on a Windows filesystem — PRFlow carries an extensive
Windows-portability contract (`[WinError 193]` on `.sh` exec, `wslpath`/`cygpath`
path normalization, the `python3` shim) precisely because Windows bash is not
drop-in, and full inline-step Windows correctness is a separate, larger hardening
effort. **Before treating a non-Linux runner as production-ready, run at least one
full consumer-shipped workflow end-to-end on the target self-hosted runner** and
confirm it completes.

### Optional: a GitHub App for workflow-file pushes and a single PRFlow identity

PRFlow's cloud writers — `/prflow:implement` (`devflow-implement.yml`) and the
write-capable `/prflow:review-and-fix` path (`devflow.yml`'s `command` job) — push
to the feature branch using the built-in `GITHUB_TOKEN`. GitHub **hard-blocks**
`GITHUB_TOKEN` from creating or updating any file under `.github/workflows/`
(the push is refused: *"refusing to allow … to create or update workflow … without
`workflows` permission"*), and `actions: write` does not lift it. So a ticket whose
change legitimately edits a workflow file cannot be completed by the cloud tier on
the default credential. Separately, everything PRFlow posts on the default
credential — reviews, verdicts, reactions, notice comments — is attributed to
`github-actions[bot]`, and an approval from `github-actions[bot]` cannot satisfy a
"required approving reviews" branch-protection rule.

The optional App unlocks both: workflow-file pushes for the writers, and **one App
identity for PRFlow's non-review user-visible cloud posts** — the 👀/🚀 trigger
reactions and the notice comments (the named exceptions below stay on
`GITHUB_TOKEN`). The **review** agent's posts — its progress comment, verdicts,
approvals, and rejections — are deliberately **not** on this App: they run under the
separate `DevFlow-Reviewer` App (see below) so the review is never a self-review of a
PR this App authored. This is **opt-in**. When it is **not** configured, behavior is
byte-for-byte unchanged — no new secret or variable is required. To enable it,
create a GitHub App, install it on the repo, and configure:

| Kind | Name | Value |
|---|---|---|
| Repository **variable** | `DEVFLOW_APP_ID` | The App's client ID. |
| Repository **secret** | `DEVFLOW_APP_PRIVATE_KEY` | The App's PEM private key. |

The App must be **installed on the repo** with **`Contents: write`**,
**`Workflows: write`** (the writers' push path — `Workflows: write` alone cannot
commit, and `Contents: write` alone hits the original `workflows`-permission
refusal), plus **`Pull requests: write`**, **`Issues: write`**, and
**`Actions: read`** (the reaction/notice sites below, and the writers' CI reads).
The formal-review posts are **not** on this App — they run under the separate
DevFlow-Reviewer App (see below). Set the variable +
secret under **Settings → Secrets and variables → Actions** (the App ID is a
*variable*, the private key a *secret*).

With `DEVFLOW_APP_ID` set, each cloud site mints its own short-lived App
installation token (via `actions/create-github-app-token`) **downscoped to exactly
what that site does** — a job-scoped token cannot cross jobs, and the `permission-*`
mint inputs are the sole enforcement of least privilege (an App installation token
ignores the job's `permissions:` block):

| Site | Scope | Can |
|---|---|---|
| Writers' agent (`devflow-implement.yml` / `devflow.yml` `command` for `/prflow:pr-description` + `/prflow:review-and-fix`) | full installation scope | push, incl. `.github/workflows/` files |
| Trigger reactions + notices (`devflow.yml` / `devflow-implement.yml` `gate`, `devflow.yml` `review_dedupe`) | `issues: write` and/or `pull-requests: write` | add reactions, post notice comments — nothing more |

The **review agent** (`devflow-runner.yml`'s automated review, and `devflow.yml`'s manual `/prflow:review` command) is the one exception: it runs under a **separate** `DevFlow-Reviewer` App, not the primary one — see [The dedicated DevFlow-Reviewer app](#the-dedicated-devflow-reviewer-app-review-identity) below.

In the two **writer** jobs the App token is minted *before* `actions/checkout` and
passed to it as `token:`. This is load-bearing, not stylistic: the credential
`actions/checkout` persists — not the `github_token` handed to
`claude-code-action` — is what the agent's `git push` authenticates with.
`checkout@v6` writes its auth header to an external config file included via
`includeIf.gitdir:` rather than into `.git/config`, so `claude-code-action`'s
attempt to clear that header finds nothing, and the header it leaves behind
outranks the token that action embeds in `origin`'s URL. An unseeded checkout
therefore pushes as `github-actions[bot]`, which holds no `workflows`
permission — every ordinary push succeeds and only `.github/workflows/` pushes
fail, with `refusing to allow a GitHub App to create or update workflow …
without workflows permission`. Seeding the checkout puts the App token in that
header instead. When the App is unset the mint is skipped and the checkout
falls back to `GITHUB_TOKEN`, exactly as checkout would default on its own.

Every primary-App mint step is gated on `vars.DEVFLOW_APP_ID != ''`, so it is skipped
when the variable is unset and each consumer falls back to `GITHUB_TOKEN` (the two
review mints gate on the separate `vars.DEVFLOW_REVIEWER_APP_ID` — see the
DevFlow-Reviewer section below). A
configured-but-broken App (invalid or rotated key, or an installation missing one of
the permissions a site requests) **fails the job at the mint step** — there is no
silent fall-back to `GITHUB_TOKEN`. Named exceptions to the App identity: the
`Devflow Review` check-run (emitted by the Actions runner from the job `name:`,
not token-authored — it can never be App-authored), and the `/prflow:implement`
workpad comment, which is *created* on `GITHUB_TOKEN` by the gate job (detection
is marker-based — `<!-- prflow:workpad -->` — never author-based, so the
claude-job fallback creation running under the App token is harmless). The
stale-rejection housekeeping runs inside the review agent, so it uses whichever
token the runner holds (the downscoped DevFlow-Reviewer token when configured — its
dismissal needs only `pull-requests: write`, and dismissal works cross-identity).
This fail-loud contract covers every **primary-App** site — the writers' `gate`
jobs and the trigger-reaction/notice jobs: with a broken primary App configured,
even the trigger-reaction job fails rather than silently posting as
`github-actions[bot]` — fix the App's key/permissions, or unset `DEVFLOW_APP_ID` to
restore the default-token behavior. The read-only review run has the same fail-loud
contract, but under its own `DEVFLOW_REVIEWER_APP_ID` (unset *that* to restore the
review run's default token) — see the DevFlow-Reviewer section below.

## Attributing commits to the triggering user (`prflow.attribute_commits_to_triggerer`)

By default, the git commits a cloud-tier **writer** run produces
(`/prflow:implement`'s `claude` job and `/prflow:review-and-fix`'s `command` job)
are authored by whatever git resolves from the runner's unconfigured `.git/config` —
*not* the human who triggered the run. Local runs already carry the triggering
developer's identity; only cloud-tier runs do not. If your reviewers and auditors read
`git blame`/history to see *which human owns a change*, that provenance is lost on every
cloud run.

Set the opt-in boolean key to close that gap:

```jsonc
// .prflow/config.json
{
  "prflow": {
    "attribute_commits_to_triggerer": true   // default: false
  }
}
```

When enabled, each cloud-tier writer run resolves the triggering user
(`github.event.sender.login`) to a GitHub commit identity and exports
`GIT_AUTHOR_NAME`/`GIT_AUTHOR_EMAIL`/`GIT_COMMITTER_NAME`/`GIT_COMMITTER_EMAIL` into the
job environment before the agent runs, so the agent's commits carry the triggering human
as both author and committer (name = the account's display name, or the login when it has
none; email = the canonical `<id>+<login>@users.noreply.github.com`).

Key properties:

- **Default-off, byte-for-byte unchanged when off.** With the key absent or `false`, the
  resolution step exports **no** `GIT_*` variable and commits are authored exactly as
  today.
- **Post-merge-only.** The flag is read at *trigger* time from a **trusted default-branch
  checkout** (never the PR head), so a value present only in a PR head has no effect on
  that PR's own run — it takes effect only after it merges to the default branch. This is
  the same trigger-time trusted-tree read the git-env pins use, and it is deliberate: a PR
  must not be able to set its own commit attribution.
- **Humans only, fail-safe.** Identity is emitted only for a GitHub account whose
  `.type == "User"` and whose login does not carry the `[bot]` suffix. Any other account
  type, a `[bot]` login, an empty login, or a type that cannot be established falls back to
  current authorship with a `::warning::` — never a mis-attributed bot commit. If the
  `gh api users/<login>` lookup itself fails (network/rate-limit), the run still preserves
  human attribution via a login-only email (`<login>@users.noreply.github.com`).
- **No new credential.** Commit author/committer is git metadata, independent of the push
  token — the push still authenticates as the App/`github-actions[bot]` identity, so
  nothing new is required. (The resolution step does authenticate its `gh api users/…`
  lookup with the run's existing token; no extra secret.)
- **Fail-open, never gates the run.** Attribution is advisory: a missing helper (during a
  workflow-vs-vendor version skew), an unreadable config, or any lookup failure emits a
  notice/warning and continues under current authorship — it never fails the job.
- **Scope.** The two writer tiers only. The read-only review tier (`devflow-runner.yml`)
  never commits, so it is unaffected. Posting the review *as* the human and the PR
  "opened-by" identity are out of scope — they require a per-user credential (tracked
  separately).

## Assigning the created PR to the triggering user (issue #1165)

Distinct from commit *attribution* above (which is opt-in and rewrites git metadata), every `/prflow:implement` run **assigns the draft PR it creates** to the developer who triggered it — always on, no config key — so reviewers can read ownership from the standard GitHub assignee field. This is the PR **assignee**, not the "opened-by" identity (which still requires a per-user credential and stays out of scope).

- **Cloud identity propagation.** `.github/workflows/devflow-implement.yml` exports `DEVFLOW_TRIGGERING_USER: ${{ github.event.sender.login }}` — the same authorized issue-comment sender authorization and commit attribution already use — into the `claude` writer step. Phase 3.1.1 of the implement engine passes it to `scripts/apply-pr-triggerer.sh`, which POSTs the login to `repos/{owner}/{repo}/issues/{number}/assignees`. The `DEVFLOW_` prefix is kept deliberately — the rename contract freezes environment identifiers. **You do not set this variable**, which is why it is absent from the frozen consumer-facing table above: the workflow derives it from the trigger event, and it is recorded as an adjudicated-out name in `lib/rename-map.json` (a consumer-supplied value would be an identity the authorization step never vetted).
- **Local identity resolution.** Outside Actions (a local `/prflow:implement`) the helper resolves the authenticated login through `gh api user --jq .login` instead.
- **Assignment confirmation.** GitHub can accept the POST while silently ignoring an unassignable login, so the helper reports success (`assignment: applied <login>`) only after confirming the login is present in the response; otherwise it records `assignment: skipped unconfirmed`. Reapplying is idempotent and never removes existing assignees.
- **Best-effort, fail-closed on identity.** The helper always exits 0; a skip or a harness refusal is recorded as a `dropped-failed` entry in the workpad's `## Devflow Reflection` and never gates the run. It is **CREATE-only** — a resumed run that adopts an existing PR leaves its assignees untouched.
- **Deployment skew.** A cloud run whose `DEVFLOW_TRIGGERING_USER` is empty (an older workflow paired with a newer skill, or a non-issue-comment trigger) skips assignment and **never** substitutes another account — not the token owner, the GitHub App identity, or `GITHUB_ACTOR`. A newer workflow paired with an older skill simply never invokes the helper. No new credential is required (the assignee POST uses the run's existing repo-scoped token).

## Durable denial forensics — a default-ON behavior change on upgrade (issue #1064)

When a cloud run emits a Bash command in a shape the permission matcher does not grant,
the command is refused silently. Since #1064 both live tiers record a **durable** denial
record — the count, the denied `tool_name`, and (by default) the **scrubbed text** of the
denied command — into each run's efficiency record on the long-lived `prflow-telemetry`
branch, so "which command shapes does the matcher keep refusing, and how often" is
answerable across runs.

**This is a genuine, durable behavior change on upgrade, and it is default-ON.** The new
`.prflow.execution_denial_commands_enabled` key defaults to `true`, and `install.sh`
backfills it as `true` into your `.prflow/config.json` on upgrade — so **a repository that
upgrades begins persisting scrubbed denied-command text to its own `prflow-telemetry`
branch without opting in.** Two things bound the exposure and one turns it off:

- The command text is run through an **incomplete** credential blocklist
  (`scripts/scrub-credentials.sh`: GitHub tokens/PATs, Anthropic keys, and both
  Authorization header forms) before it is written, and every record discloses
  `scrub.blocklist_incomplete: true` — a novel third-party credential shape can survive, so
  treat the branch as sensitive.
- The field is bounded (per-command and list caps) and command-only — never a whole
  transcript.
- **To disable it, set `.prflow.execution_denial_commands_enabled` to `false`** in
  `.prflow/config.json`. It is read at runtime, so the change takes effect on the very next
  run. The denial **count** and denied **`tool_name`** are always persisted and are *not*
  gated by this key (a number and a fixed-vocabulary tool identifier carry no credential
  risk). Which repositories are actually affected: only those already pushing telemetry
  records (one with no telemetry push path is unaffected in practice — persistence is
  best-effort and degrades silently where no credential exists).

This is deliberately the **opposite** default from `execution_transcript_artifact_enabled`
(default `false`), which gates the whole execution transcript — prompt text, repository
content, and a potentially dumped environment. Different surfaces, different risk, different
defaults; they are not harmonized.

## Startup-lifecycle observability & consumer version skew (issue #537)

The `/prflow:implement` startup lifecycle (see `docs/internal/workflow-triggers.md` and
`DEVFLOW_SYSTEM_OVERVIEW.md` for the full model) adds **zero** new configuration:
no new config key, permission, secret, repository variable, service, or install
mode. It reuses the existing issue-comment workpad, the job's existing token, and a
gitignored ephemeral JSON handoff record under `.prflow/tmp/` (non-secret,
advisory, never passed through Claude action settings). Thin cloud installs and
committed-vendor installs behave identically at runtime.

Because the fix spans **two independently-updated artifacts** — the workflow
(`devflow-implement.yml`, shipped by `install.sh`) and the plugin/skill + `workpad.py`
(materialized at the pinned `prflow_version`) — a partially-upgraded consumer sees
graceful degradation, not breakage:

- **Old workflow + new plugin** — no handoff record is written, so Phase 1 resolves
  provenance to `unknown` and runs with the neutral "provenance unavailable" wording.
  The old gate keeps its pre-fix `workpad.py id` duplicate-create risk until the
  workflow is upgraded.
- **New workflow + old pinned plugin** — the helper lacks `--checkpoint` /
  `handoff-state`, so the checkpoint steps warn (`::warning::`) and continue and
  Phase 1 keeps the legacy `run resumed` wording. The incomplete-vendor guard still
  fails the job before the action if the vendored `workpad.py` is entirely absent.

**Duplicate-read protection and the truthful lifecycle wording are complete only
once both the shipped workflow and the pinned plugin carry this fix** — upgrade the
two halves together (bump `prflow_version` when you update the workflow).

### Keeping writer-job credentials fresh past the token's 60-minute lifetime

A GitHub App installation token expires **exactly one hour** after it is minted and
cannot be renewed — only replaced by a fresh mint. PRFlow's writer jobs mint one
token at job start and ride it for the whole run, so a `/prflow:implement` or
`/prflow:review-and-fix` run that **outlives that hour** used to spend its remainder
with dead credentials: the agent's `git push` and every agent-side `gh` call both
`401`. The two writer jobs (`devflow-implement.yml`'s `claude` job and `devflow.yml`'s
`command` job) fix this with a **long-run credential refresher**, gated on the **same**
`vars.DEVFLOW_APP_ID != ''` condition as the App-token mint above — when the App is
unconfigured, every step below is skipped and behavior is **byte-identical** to today.
(The refresher is also excluded on the read-only `/prflow:review` path, which uses the
downscoped reviewer token and never pushes.)

**What it does.** After checkout — and before the `claude` step — the job starts
`scripts/refresh-app-credentials.sh loop` as a **detached `nohup` background process**
(deliberately *not* a `background:` step, a keyword `actionlint` rejects). The
refresher holds the App credentials and, on a **45-minute cadence** (dropping to a
**2-minute backoff** after a failed cycle until one succeeds), re-mints a fresh
installation token and rewrites the two repo-controlled credential surfaces in place:

1. the checkout-persisted `http.<server>/.extraheader` credential every in-run
   `git push` authenticates with (it *rewrites* that credential of record — it never
   replaces the push mechanism), and
2. a mode-0600 token file that the agent-side `gh` wrapper (`scripts/gh-fresh.sh`)
   reads at call time — **mode-0600 only where POSIX mode bits apply; on Windows they
   constrain neither this token file nor the wrapper installer's sibling fingerprint
   file, so both are left to whatever the filesystem's ACLs provide** (see
   [Windows: POSIX mode bits do not constrain the credential files](#windows-posix-mode-bits-do-not-constrain-the-credential-files)).
   The wrapper is installed by the checked-in, seven-output-validated
   `scripts/install-gh-wrapper.sh` (issue #533) ahead of the real `gh` on `PATH`, so
   direct `gh` calls and PRFlow's own resolver-routed gh-callers (whose PATH probe
   finds the wrapper when `DEVFLOW_GH` is unset) resolve the fresh token. The install
   step publishes **no** process-global `DEVFLOW_GH` — that env value would persist into
   every later job step and outrank fixture PATH stubs in the repository test suite;
   `DEVFLOW_GH` remains the explicit caller/test override seam. The wrapper discriminates the ambient
   job-start token from a deliberately-fresh backstop mint by fingerprint, so it only
   substitutes the refreshed token where the ambient (expiring) one would be used.

**Key handling.** The App's PEM private key is piped to the refresher's **stdin** — it
is never passed as a process argument and never written to disk (the JWT is signed with
the key handed to `openssl` over a file descriptor). The workflow's Start step exports
the key as a step-level env var only so that short-lived launcher shell can pipe it; the
**detached refresher is launched with `env -u DEVFLOW_APP_PRIVATE_KEY`**, so the raw PEM
is absent from the long-lived refresher's exec-time environment and therefore never
readable via its `/proc/<pid>/environ` by the concurrent same-uid `claude` agent step
(`/proc/<pid>/environ` snapshots the environment at `execve` time and is not updated by a
later `unset` — proc(5), so `env -u` at launch, not an in-process `unset`, is what closes
that vector). The key then lives only in the refresher's shell memory.

**Least privilege.** Each re-minted token is **scoped to this repository only**
(`repositories: [<repo>]`), matching the job-start token's default scope rather than
minting an installation-wide token across every repo the App is installed on.

**Loud degrade.** The refresher is best-effort and never fails the job: a failed cycle
emits a per-arm `::warning::` naming what failed and warns-and-continues. Almost every
failure arm leaves the previous credential in place, with one disclosed exception — if
the push credential (surface 1, the checkout extraheader) has already been rewritten to
the fresh token and only the gh token file (surface 2) then fails to write, the two
surfaces diverge (surface 1 fresh, surface 2 stale); the cycle warns naming that
divergence and the next 2-minute backoff retry re-converges them. Because a background process's `::warning::` lines are
inert in the Actions UI, an `if: always()` **Stop credential refresher** step
(`scripts/stop-refresher.sh`) retires the refresher by pidfile, tails its detached log
into the step output, and re-emits **one** live `::warning::` when the refresher was
actually defeated (never started/crashed before its first cycle, died mid-run — the
pidfile's pid no longer running, so a stale `cycle OK` in the log does not mask a death
after that cycle; the pidfile present but empty — the loop could not record its PID, so
its liveness cannot be verified — or its most recent cycle failed) — so a run that silently lost its
credentials is visible without log archaeology. The agent-side wrapper degrades loudly
too: a substitute decision that finds no token file (a refresher defeated at startup
never writes one) emits a stderr breadcrumb before riding the ambient token.

**Agent-side fail-fast — the last line of defense when the refresher is defeated
(issue #487).** The refresher can be defeated by sustained mint failure, so
`skills/implement/SKILL.md` carries an always-resident *Expired-credential fail-fast*
rule: after **two** consecutive `git push` / `gh` failures carrying the bad-credential
signature (`401`, `Bad credentials`, `Authentication failed`) the run stops retrying
that operation, records a `blocked` reflection, sets `Status: Blocked` and ends there.
The motivating evidence is the ~$60 run **29299441781**, which spent its remainder
iterating on dead credentials. That prose rule is **best-effort under context
compaction** — a >60-minute run is the maximally compaction-likely population — and its
compaction-immune sibling is `scripts/gh-fresh.sh`, which appends a distinctive
`devflow-gh-fresh: gh call failed with an expired/bad credential …` line to stderr at
every `gh` call failing with that signature, so the signal is re-derivable from the tool
result even if the rule has been evicted from the agent's context.

**Disclosed residual.** This refresher keeps PRFlow's own `git push` and `gh` calls
fresh, but `claude-code-action`'s **own internal API calls** still ride the static
`github_token` input passed to the action, which is not refreshed. That is an upstream
limitation tracked at `anthropics/claude-code-action#716`; until it lands, an extremely
long run can still see the action's internal calls fail on the expired token even
though PRFlow's push/gh surfaces stay fresh. A second assumption to re-probe on any
`claude-code-action` **major** upgrade: the wrapper's fingerprint discrimination relies
on the action exporting its `github_token` input **byte-identical** as `GH_TOKEN`
(verified against `src/entrypoints/run.ts` at drafting time). If a future version
exports a differently-derived token, every wrapped call takes the defer path and the
agent-side freshness fix goes silently inert (safe — the fail-fast rule still catches
the 401 — but ineffective).

### The dedicated DevFlow-Reviewer app (review identity)

GitHub forbids **requesting changes on — or approving — your own pull request**.
Without a dedicated reviewer identity, PRFlow's review agent would run under the
same identity that PRFlow uses to *author* PRs (the primary App above, or
`github-actions[bot]`), so Phase 4.4's
a formal `REQUEST_CHANGES` / `APPROVE` review would be a forbidden self-review:
the merge stays blocked by the required `Devflow Review` status check, but no
**visible** formal review (`reviewDecision`) is recorded. To restore the visible
formal review, run the review agent under a **dedicated second GitHub App**,
**`DevFlow-Reviewer`**, whose identity is distinct from the PR author.

| Kind | Name | Value |
|---|---|---|
| Repository **variable** | `DEVFLOW_REVIEWER_APP_ID` | The DevFlow-Reviewer App's ID (or client ID). |
| Repository **secret** | `DEVFLOW_REVIEWER_PRIVATE_KEY` | The DevFlow-Reviewer App's PEM private key. |

Create and install a second GitHub App on the repo with
**`Contents: read`**, **`Issues: read`**, **`Pull requests: write`**, and **`Actions: read`** —
the downscoped review permission set (it reads the repo/issue/CI and posts comments,
reviews, approvals, and rejections; it **cannot push**). Set the variable + secret
under **Settings → Secrets and variables → Actions**, mirroring the primary-App
convention.

**Review-identity invariant.** Every review path — the automated runner
(`devflow-runner.yml`) and the manual `/prflow:review` command (`devflow.yml`) —
uses the `DevFlow-Reviewer` installation token when `vars.DEVFLOW_REVIEWER_APP_ID`
is set, otherwise `github-actions[bot]` (`GITHUB_TOKEN`). The review path **never**
uses the primary `prflow-implementer` App token. Since implement authors PRs as the
primary App (or `github-actions[bot]` when no App is configured), the review
identity is structurally distinct from the author on every configured setup, so
Phase 4.4's formal review posts instead of failing self-review. `/prflow:pr-description`
and `/prflow:review-and-fix` are unchanged — they still use the primary App token
(they push/author, and `review-and-fix` posts no formal review). The mint is gated
and fail-loud exactly like the primary App: unset reviewer variable → `GITHUB_TOKEN`
fallback; a configured-but-broken reviewer App fails the job at the mint step.

> **Upgrade note (deliberate behavior change).** If you already run PRFlow with a
> single App (`DEVFLOW_APP_ID` set) and do **not** configure `DevFlow-Reviewer`,
> your review attribution moves from your PRFlow App to `github-actions[bot]`
> until you set `DEVFLOW_REVIEWER_APP_ID` + `DEVFLOW_REVIEWER_PRIVATE_KEY`. This is
> intentional: the review path no longer borrows the PR-authoring App identity, so
> the same-identity self-review collision cannot occur. A `github-actions[bot]`
> approval does not satisfy a "required approving reviews" branch-protection rule,
> so configure `DevFlow-Reviewer` if you rely on that.
>
> **Degenerate zero-app config.** With neither `DEVFLOW_APP_ID` nor
> `DEVFLOW_REVIEWER_APP_ID` set, implement and review are both
> `github-actions[bot]`, so the self-approval collision persists on that config —
> the `gh pr comment` fallback and the required `Devflow Review` check still apply.

The same App token also powers the implement workflow's **stall-backstop
auto-resume** (see `docs/internal/implement-skill.md`): a `/prflow:implement <#>` resume
comment authored by the built-in `GITHUB_TOKEN` never re-triggers the workflow
(GitHub suppresses recursive `GITHUB_TOKEN` events), so without the App the
backstop posts its resume comment and then fails the job loud instead of
pretending the resume happened — a human re-posts the trigger comment manually.
With the App configured, also add the App's bot login (e.g. `your-app[bot]`) to
`prflow.allowed_bots` in `.prflow/config.json`, or the gate's actor
authorization declines the App-authored resume comment. Because a `claude` job
can run longer than an App installation token's ~60-minute lifetime, the backstop
mints its **own fresh** App token just-in-time immediately before it runs rather
than reusing the token minted at the job's start; a `gh`-api/transport/auth
failure reading the workpad (e.g. an expired token) is a distinct `auth-failure`
class that fails the job loud **without** consuming a resume attempt, so a healthy
workpad behind a bad token is never misclassified as corrupt (see
`docs/internal/implement-skill.md`). The resume comment carries an inline `Resume note:`
that instructs the resumed run to invoke bundled helpers with the repo-relative
vendored literal (`.prflow/vendor/prflow/scripts/…`, `.prflow/vendor/prflow/lib/…`)
as the command's leading token — never an absolute path, never repo-root
`scripts/…`, never behind a `VAR=` prefix or `bash <path>` wrapper — since the
cloud allowlist silently denies any other form, which is exactly what killed
prior auto-resume runs on their first helper call (issue #405).

The same App token **also** powers the review workflow's **no-verdict
auto-resume backstop** (`prflow_review.stall_backstop`, issue #408 — the
review-side sibling of the implement backstop above; see
`docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md`). A headless cloud review can end `success`
with no verdict — not a timing race but the harness's **default dispatch mode**
meeting a headless runner: subagents are background-by-default, a background
dispatch's results arrive in a *later turn*, and a headless `claude -p` session
ends at its first tool-call-free turn, so the dispatched fleet is discarded
(issue #801; the cloud engine steps now set `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS`
to keep subagents in the foreground). When it still happens the auto-review
path (`devflow-review.yml`'s `finalize_check`) mints its **own fresh** App token
just-in-time and authors a `/prflow:review` re-trigger comment so the review
re-runs without a human. As with the implement resume, a `GITHUB_TOKEN`-authored
comment never re-triggers the workflow, so this needs the App: with `DEVFLOW_APP_ID`
unset the backstop degrades to the dead-end flip (a visible `❌ Review failed`
that a human must re-trigger). And exactly like the implement resume, add the
minting App's bot login (e.g. `your-app[bot]`) to `prflow.allowed_bots` in
`.prflow/config.json`, or the manual-`/prflow:review` gate the re-trigger
re-enters declines the App-authored comment. The backstop is capped at
`prflow_review.stall_backstop.max_resume_attempts` (default `2`) per head and
gated by `prflow_review.stall_backstop.enabled` (default `true`, disabled only
on a real JSON `false`); when the cap is exhausted, disabled, or no App token is
configured it reports no-fire and degrades to the dead-end flip.

A **third** path shares this `prflow.allowed_bots` requirement: the optional
**automatic review request on green CI**. A consumer that copies the
`pull_request` snippet from
[`workflow-triggers.md`](workflow-triggers.md#automatic-review-request-on-green-ci-ciyml-and-shipping-it-to-a-consumer-repository)
has their App post a `/prflow:review` comment automatically once CI is green — and
that comment is authorized by the same `prflow.allowed_bots` gate, so the minting
App's bot login (e.g. `your-app[bot]`) must be listed there too. As with the two
backstops above, `prflow.allowed_bots` is resolved from the **default branch at
trigger time**, so the slug must merge before the snippet can start a review; see
the snippet's adjacent preconditions for the full set.

> **Loop-safety note.** Unlike `GITHUB_TOKEN` pushes (which GitHub suppresses from
> re-triggering workflows), an **App-token push re-triggers workflows**. For PRFlow
> this is mostly desirable (a push to a non-draft PR re-runs `Devflow Review` on its
> own). Loop-safety does **not** rest on the push-suppression: it rests on the
> `@claude`-negation **partition invariant** (every PRFlow trigger negates `@claude`,
> so PRFlow and Anthropic's stock `claude.yml` never double-fire) and on
> `/prflow:implement` triggering from an `issue_comment` (a human action) rather than
> from `push`. Do not weaken those `if:` clauses.

## Triggering `/prflow:implement`

`devflow-implement.yml` runs the full implementation lifecycle when a real
comment **on an issue** contains a bare `/prflow:implement <#>` (no `@claude`
required — and **no** `@claude`: a comment containing `@claude` is ceded to
Anthropic's Claude GitHub App, not PRFlow). There is no label trigger — a human
`/prflow:implement <#>` comment is the sole entry point and is itself a native
user event, so it needs no bot comment, PAT, or GitHub App.

It is **issues-only**: the workflow subscribes to `issue_comment[created]` alone,
and because a PR comment is also an `issue_comment` in GitHub's API, the `gate`
job's `if:` requires `github.event.issue.pull_request == null` (with the resolver
re-checking via an `IS_PULL_REQUEST` backstop), so a comment on a pull request
never starts a run. This is what stops the weekly retrospective's audit-report
comment — which quotes the literal `/prflow:implement` phrase in prose on the
state PR — from self-triggering an implement run. The light `/prflow:review` and
`/prflow:pr-description` commands in `devflow.yml` remain PR-aware and are
unaffected.

> **Who can trigger it.** The `gate` job runs
> `scripts/resolve-implement-trigger.sh`, which authorizes the sender only if
> they are an allowed bot (`prflow.allowed_bots`) **or** their login matches
> `prflow.allowed_users` **and** they hold write / admin / maintain access — and
> fails closed otherwise. `prflow.allowed_users` defaults to `"*"` (any
> collaborator) and can be narrowed to a comma-separated list of logins to
> restrict who may start a run; it only tightens the collaborator gate, never
> bypasses it. Bots are governed separately by `prflow.allowed_bots` — this is
> the path for a custom GitHub App that posts the trigger comment on your behalf.
> The same gate guards the light `/prflow:*` command path in `devflow.yml`.
>
> **Early acknowledgement.** As soon as the gate authorizes a command, it adds a
> 🚀 reaction to the triggering comment via `scripts/react-to-trigger.sh` — so you
> can see the trigger was picked up well before the heavy job spins up. It's
> best-effort: a failed reaction never blocks the run, and a `/prflow:*` command
> submitted as a PR *review* gets no reaction (GitHub has no reactions API for
> reviews).

For the full idea → issue → PR walkthrough, see
[The workflow, end to end](../../README.md#the-workflow-end-to-end) in the README.

## Configure and enable

1. `install.sh` scaffolds `.prflow/config.json` from the template when absent;
   when it already exists it's kept and re-running only **backfills newly-added
   keys** from the template (existing values win, your arrays stay as-is). Every
   value has a working default, so commit it as-is or edit to customize — the
   workflows read it from the checked-out tree, so it must be committed (if your
   repo gitignores it, force-add: `git add -f .prflow/config.json`).
2. The `workflows` block in that file toggles each workflow on/off.
3. Make `Devflow Review` a required status check (Settings → Branches → branch
   protection) once you've confirmed it runs.

## Runtime provisioning (`setup`)

The light command (`devflow.yml`) and `/prflow:implement`
(`devflow-implement.yml`) always prepare the runner **before**
Claude runs by reading a `setup` block from `.prflow/config.json`; the
automated reviewer (`devflow-review.yml` → `devflow-runner.yml`) does so too,
but **only when you opt in** with `prflow_runner.provision_env: true` (see
"Letting the reviewer build/test a PR" below).
(`/prflow:init` auto-fills `node_version` + an install line from your repo's
language(s) and lockfile — see "Letting the reviewer build/test a PR" below.)
There is no hardcoded toolchain — PRFlow installs into repos of every shape
(Python package at root, npm frontend, Docker-only backend, polyglot), so you
declare what your project needs:

```json
"setup": {
  "python_version": "3.11",
  "node_version": "",
  "install": [
    "python -m pip install pyyaml",
    "pip install -e \".[dev]\"",
    "npm ci --prefix client"
  ]
}
```

- `python_version` / `node_version` gate the `actions/setup-python` /
  `actions/setup-node` steps — leave a value empty (`""`) to skip that language.
- `install` is an **array of shell lines**, joined with newlines and run
  verbatim **from the repo root** after the language setups; leave it `[]` to
  install nothing. A line that needs a subdirectory must `cd` into it itself
  (e.g. `(cd jsx && npm ci)` or `npm ci --prefix client`).
- **Keep `python_version` set and `pip install pyyaml` present even for
  non-Python projects** — PRFlow's own helper scripts currently require
  Python ≥ 3.11 with PyYAML. List PRFlow's deps first, then your project's.

Example for a split repo (Docker backend in `server/`, npm frontend in
`client/`): keep `"python_version": "3.11"` + `pip install pyyaml`, set
`"node_version": "20"`, and add `npm ci --prefix client` to the `install` array.

### PHP, service containers, and dependency caching

The `setup` block covers more than Python/Node, in this provisioning order
(**Python → Node → PHP → service containers → `install` lines**):

- **PHP** — set `setup.php_version` (e.g. `"8.3"`) to run
  [`shivammathur/setup-php`](https://github.com/shivammathur/setup-php) with
  Composer; `setup.php_extensions` is a CSV of extensions
  (`"mbstring, intl, pdo_mysql, redis"`), `setup.php_tools` an optional CSV of
  tools. `/prflow:init` fills these from `composer.json` and adds a
  `composer install` line.
- **Service containers** — `setup.services` starts databases/caches/queues your
  tests need, via `docker run` (PRFlow does **not** use GitHub Actions
  `services:` — those can't be defined in a composite action or driven by
  config). Each service is reachable on **`127.0.0.1:<host-port>`**, so point
  your *test* config at `127.0.0.1`. Give a `--health-cmd` in `options` so
  startup is awaited:

  ```json
  "setup": {
    "php_version": "8.3",
    "php_extensions": "mbstring, intl, pdo_mysql, redis",
    "services": [
      {
        "name": "mysql",
        "image": "mysql:8.0",
        "ports": ["3306:3306"],
        "env": { "MYSQL_ROOT_PASSWORD": "root", "MYSQL_DATABASE": "app_test" },
        "options": ["--health-cmd=mysqladmin ping -h 127.0.0.1 -uroot -proot", "--health-interval=5s", "--health-timeout=5s", "--health-retries=20"]
      },
      { "name": "redis", "image": "redis:7", "ports": ["6379:6379"] }
    ],
    "install": ["composer install --no-interaction", "php artisan migrate --env=testing --force"]
  }
  ```

  The runner has Docker preinstalled; the `docker` preset's `Bash(docker:*)`
  allowlist (auto-added when a `Dockerfile`/compose file is present) is what lets
  build steps talk to the containers.
- **Node dependency caching** — automatic: when `node_version` is set **and** a
  lockfile (`package-lock.json` / `yarn.lock` / `pnpm-lock.yaml` /
  `npm-shrinkwrap.json`) is present, `setup-node`'s download cache is enabled
  for the matching package manager. The lockfile is resolved under
  **`setup.node_working_directory`** — the repo root by default. No lockfile →
  caching is skipped (so it never errors).
- **Subdirectory / monorepo Node builds** — if your `package.json` + lockfile
  live in a subdirectory (a PHP/Rails app with a `/jsx` or `/resources/js`
  bundle, a monorepo `frontend/` package) rather than at the repo root, set
  `setup.node_working_directory` to that directory (e.g. `"jsx"`). Caching then
  keys off the lockfile there, and `/prflow:init` auto-detects it and scopes
  the generated Node install line into that directory (a subshell `cd`). Leave
  it empty/absent for a root-level build — provisioning is byte-for-byte the
  same as before. Remember `install` lines still run from the repo root, so any
  *additional* build line you add must scope itself into the subdirectory.

`/prflow:init` populates the deterministic parts (tool allowlists, `node_version`,
`npm ci`/`composer install`) from language markers, then **explores the repo**
(`docker-compose.yml`, `.env`, CI, `composer.json`) to enrich `php_version`,
`php_extensions`, and `services` — the judgement-heavy fields a marker→list table
can't infer. Review its additions before committing; service `env` and `install`
lines run in CI from your committed (base-branch) config.

## Extending the tool allowlist

The light `/prflow:*` command path runs under a fixed `--allowed-tools` allowlist baked into the
workflows (git/gh, the PRFlow scripts, Python, and common read-only shell
tools). Provisioning a tool in `setup.install` does **not** let Claude *run* it
— the tool also has to be on the allowlist. To grant your repo's own commands,
add them on top of the built-in base list via config; you never edit the
workflow YAML:

```json
"prflow": {
  "allowed_tools": ["Bash(make:*)", "Bash(docker compose:*)"]
},
"prflow_implement": {
  "allowed_tools": ["Bash(make:*)", "Bash(terraform:*)"]
}
```

- Entries use [claude-code-action tool syntax](https://github.com/anthropics/claude-code-action)
  (e.g. `Bash(make:*)`), and are **appended** to PRFlow's base list — they add,
  never replace.
- These keys are **independent**, one per execution path:
  `prflow.allowed_tools` → light `/prflow:*` command path (`devflow.yml`);
  `prflow_implement.allowed_tools` → `/prflow:implement` (`devflow-implement.yml`).
  None inherits another's extras, so list every tool you want for a given path
  under that path's key. The automated reviewer's build tools live in a third
  key, `prflow_runner.allowed_tools`, gated behind the `prflow_runner.provision_env`
  opt-in and bounded by a deny-list floor (see "Letting the reviewer build/test a
  PR" below).
- Leave a key out (or `[]`) to use the base list unchanged.
- These come from your committed config, so treat them with the same care as
  `setup.install`: only allowlist commands you trust to run unattended.

### Grant your test/lint commands so the run verifies in-env (issue #405)

`/prflow:implement` verifies **in its own environment, never via CI**. A
verification-command acceptance criterion — one whose verification is *running a
test/lint/build command* (your test suite, a linter, a `pytest`/build
invocation) — is ticked only on a pass the run **observes in-env**. The run
never waits on, polls, re-checks, or cites CI for its own progress; CI remains
the **required post-PR check that gates the human merge**, not an in-run
verification channel.

For the run to actually run those commands, they must be on the allowlist for
the execution path — invoked by their **direct leading-token** form (the
`bash <path>` wrapper is deny-floored and can never be granted). So:

- List your project's test/lint commands under **`prflow_implement.allowed_tools`**
  (the `/prflow:implement` path) **and** under **`prflow.allowed_tools`** (the
  `/prflow:*` command path, including `/prflow:review-and-fix`):

  ```json
  "prflow": {
    "allowed_tools": ["Bash(npm test:*)", "Bash(npm run lint:*)"]
  },
  "prflow_implement": {
    "allowed_tools": ["Bash(npm test:*)", "Bash(npm run lint:*)"]
  }
  ```

- **Leave them ungranted and the run does not silently defer to CI** — a
  verification-command AC goes **`Blocked`**, and the Blocked message names
  `prflow_implement.allowed_tools` as the exact remedy: grant the command so
  the run can verify in-env, then re-run. There is never a silent stall, and
  never a verdict resting on a CI result the run never saw.

- **A grant a PR ships is post-merge-only — never rely on a grant that same PR
  adds.** A grant added to `prflow_implement.allowed_tools` (and equally to
  `prflow.allowed_tools`, which this same section instructs populating) inside a PR
  takes effect only after that PR merges, because the workflows resolve grants at trigger time from the default branch — never from the PR's own head.
  So a criterion that must run a *newly*-granted command cannot verify in-env
  during that PR's own implementing run; grant the command in a prior (merged)
  change, or defer that verification to after merge.

- **The jobs that run your commands check out full history**, so a check of
  yours that reads history older than the last few dozen commits still resolves
  in-env. Both `devflow-implement.yml`'s `claude` job and `devflow.yml`'s
  `command` job use `fetch-depth: 0` (issue #1219 — before that they were
  depth-bounded, which silently turned this repository's own history-reading
  gate into a self-skip rather than a failure). A consumer whose copies
  `install.sh` still manages picks the new depth up on its next install run;
  a locally modified workflow keeps your copy, as the installer's preserve arm
  intends, so raise the depth yourself there if such a check matters to you.

(This repo's own `.prflow/config.json` grants `Bash(lib/test/run.sh:*)`,
`Bash(lib/test/run-parallel.sh:*)`, `Bash(lib/test/run-module.sh:*)`,
`Bash(lib/test/run-shard.sh:*)`, `Bash(lib/test/shard-tally.py:*)`,
`Bash(lib/preflight.sh:*)`, and `Bash(shellcheck:*)` under both keys for exactly
this reason. The two shard tokens are what let a run decompose a suite the tier's
per-command execution ceiling would otherwise terminate, and recombine it into one
whole-suite result, instead of downgrading its completion evidence — issue #1132.) See [`implement-skill.md`](implement-skill.md) for the Phase 3.4
gate behavior.

## Letting the reviewer build/test a PR

By default the automated reviewer is **read-only** — it inspects the diff but
cannot compile, lint, or test it, so a build-dependent claim (e.g. "does
`npx webpack` still compile after this change?") can only be flagged, not
verified. (Read-only still covers the live per-run `<!-- prflow:review-progress
run=<id>-<attempt> -->` progress comment: the `review` tool profile allow-lists `workpad.py`,
`config-get.sh`, `load-prompt-extension.sh`, and `efficiency-trace.sh` because those only
edit the PR comment via `gh`, read config, read the run's state, or `cat` a consumer-owned
prompt-extension file — they never mutate the tree. (`load-prompt-extension.sh` is the
standardized preflight every skill now runs — including `review` and `review-and-fix` — so
it must be on the read-only profile too, or the convention would silently no-op in the cloud
review tier. **Tree non-mutation is not provenance (issue #874):** "it only reads and prints"
says nothing about *whose* bytes it prints, and this job checks out the PR head, so the
printed text — which the calling skill appends to its own prompt — used to be PR-author-editable.
What makes the grant safe on this tier is what the job does *before* the agent starts: the
unconditional truncation plus the trusted base-ref closure described under the
**Trusted-ref rule — `.prflow/prompt-extensions/`** above, not the helper being read-only.) The
effectiveness-trace **record file** is the one piece gated to writable runs. See
[`workflow-triggers.md`](workflow-triggers.md) and
[`efficiency-trace.md`](efficiency-trace.md).) Read-only also covers
`resolve-review-overrides.py`, which the shared review engine runs to resolve the
per-subagent `prflow_review.agent_overrides` block — it only reads config via
`config-get.sh` and prints the resolved override map to stdout, never touching the
tree. For those overrides to take effect under the cloud `review` profile, that
script must be on the profile's tool allow-list (alongside the readers above); if
it is omitted, the engine's override resolution is denied and every override
silently falls back to `{}` (no override). See
[`review-agent-overrides.md`](review-agent-overrides.md). Flip one flag to opt in to
build/test:

```json
"prflow_runner": {
  "provision_env": true,
  "allowed_tools": ["Bash(npm:*)", "Bash(npx:*)", "Bash(node:*)"]
},
"setup": {
  "node_version": "20",
  "install": ["npm ci"]
}
```

When `prflow_runner.provision_env` is `true`, the runner (`devflow-runner.yml`)
does two extra things before launching Claude:

1. Runs the `setup-project-env` action — the same provisioning the
   `/prflow:*` command path and `/prflow:implement` already use (Python /
   Node / PHP → service containers → `setup.install`), so the reviewer has a
   real built environment. Service-container startup is best-effort: if a
   service fails to start or never becomes healthy, the runner prepends an
   infra-status note to the reviewer prompt naming the degraded service and
   instructing the reviewer to attribute any resulting build/test failures to
   infrastructure rather than the PR — so a transient outage surfaces as a clear
   caveat instead of silently degrading the review into a false "changes
   requested" verdict.
2. Extends the read-only `review` tool profile with the **freeform
   `prflow_runner.allowed_tools`** list from your base-branch config — read
   verbatim from the trusted base ref. This is **language-agnostic**: a Go shop
   lists `Bash(go:*)`, a Rust shop `Bash(cargo:*)`, and so on — no PRFlow
   release is needed per language. `/prflow:init` auto-populates it from your
   detected toolchain.

   Before appending, the runner enforces a deterministic **deny-list floor**: it
   strips file-mutation tools (`Edit`, `Write`, `MultiEdit`, `NotebookEdit`) —
   matched by tool **name** (the token before the first `(`, compared
   case-insensitively), so a **parameterized** entry like `Write(**)`,
   `Edit(src/**)`, or `notebookedit(x)` is stripped exactly like the bare name —
   and any `Bash(…)` whose command-position binary is a raw shell / eval /
   privilege tool (`bash`, `sh`, `zsh`, `dash`, `ksh`, `fish`, `eval`, `exec`,
   `source`,
   `sudo`, `doas`, `su`) **or** an exec-wrapper that would run its argument as the
   real command (`env`, `xargs`, `nice`, `timeout`, `nohup`, `setsid`, `command`,
   `chroot`, `runuser`) — so `Bash(env bash:*)`, `Bash(/bin/bash:*)`,
   `Bash(FOO=1 bash:*)`, and `Bash(go;sudo:*)` are all stripped, while legitimate
   build entries whose *subcommand or argument* happens to be a deny word
   (`Bash(docker exec:*)`, `Bash(make CC=gcc:*)`) are kept. The runner emits a
   `::warning::` for each stripped entry and continues with the safe remainder, so
   this catastrophic tier can never reach the reviewer's write-token job no matter
   what `config.json` lists. The floor's filter code itself is executed only from
   a **trusted source** — a copy materialized from your base branch, or the
   vendored copy when it was freshly fetched this run at the pinned
   `prflow_version` — never from the PR-head checkout, so a pull request cannot
   edit the filter that governs its own review; when no trusted copy is
   available the runner fails closed (no build tools appended). (The floor blocks *direct* shell/privilege access; it
   does **not** try to block interpreters like `node -e` / `python -c`, which are
   legitimate build tools — enabling `provision_env` already means accepting that
   the reviewer runs the PR's build code.) If the
   list is empty (or empty after stripping) while `provision_env` is on, the
   runner warns that build-aware review is enabled with no build tools.

When the flag is **absent or `false` (the default)**, none of this happens: the
runner is byte-for-byte the read-only reviewer it was before — no provisioning
step, no build tools, no added latency, regardless of what
`prflow_runner.allowed_tools` contains.

The `setup` block is still populated for you: **`/prflow:init` auto-detects
your repo's language(s)** (Node, Go, Rust, Java, Ruby, PHP, .NET, Make, Docker)
from their marker files and fills in `setup` (picking `npm ci` /
`pnpm install` / `yarn install` from your lockfile). Re-run it after adding a
language — the merge is an idempotent union that never drops your custom
entries. Enabling the reviewer's build environment is then just setting
`provision_env: true`.

> **⚠️ Security — read before enabling.** Build tools run the **PR author's
> code** (e.g. an `npm` package's `postinstall` script) inside the reviewer,
> which fires on `pull_request_target` with a `pull-requests: write` token. To
> stop a PR from escalating itself, the runner reads **both** the
> `provision_env` flag **and** the `setup` block **only from your repo's base
> branch** — never from the PR's own checkout — so a malicious PR can neither
> turn provisioning on for its own review nor inject `setup.install` commands.
> But enabling `provision_env` is still you opting into running untrusted build
> steps against fork PRs. Mitigations: enable
> [*Require approval for all outside collaborators*](https://docs.github.com/en/actions/managing-workflow-runs/approving-workflow-runs-from-public-forks)
> for Actions, and keep `setup.install` to mainstream build/test/lint commands.
> Residual limitation: the reviewer still runs the in-repo composite actions
> (and the `setup.install` lines) from the PR checkout, so a PR that edits
> `.github/actions/**` is a separate, louder vector — protect those paths if
> this matters to you. Note too that the `setup` block comes from the base
> branch but runs against the PR-head tree, so a PR that restructures the
> project (renames the package dir, regenerates the lockfile) can make the
> base-pinned install line fail — surfacing as a provisioning error, not a code
> defect.

### What the reviewer is told before it starts — the engine ground-truth block

Every cloud run of `/prflow:review` — the automated `devflow-review.yml` path and the
manual `/prflow:review` comment path alike — has a `> [!IMPORTANT]` **engine
ground-truth** block prepended to its prompt by `scripts/render-grounding-block.sh`. The
block states two facts the engine would otherwise spend turns rediscovering by attempting
commands and collecting denials:

1. **The CI results observed for the reviewed commit**, rendered by
   `scripts/summarize-ci-checks.sh` from the GitHub API. These are the **observed**
   conclusions — including a `failure` conclusion and an `in_progress` status — never a
   green assumption. When the CI state cannot be determined the block says
   `CI status unavailable`; an unknown state is never rendered as a passing one.
2. **The exact `--allowed-tools` string this run resolved**, quoted verbatim from the
   same value the runner passes to the engine, so the two cannot drift.

Check-run and job names inside the block are attacker-controlled text (any pull request
can add a workflow whose job `name:` is arbitrary), so they are sanitized, truncated, and
rendered inside a plain ` ```text ` fence, beneath prose that declares the names untrusted
data. The block tells the engine to quote a name, never to obey one — while treating the
conclusions beside them as the API facts they are.

**How this interacts with `require_ci_green`.** On the **auto** path the review is
triggered by `devflow-review.yml`'s `workflow_run` `[completed]` trigger and gated by
`scripts/derive-review-preconditions.sh`, whose `require_ci_green` precondition (default
`true`) defers the review until every other CI signal on the head has completed without
failing. CI completion is therefore a *precondition of the reviewer's invocation* on that
path, and the block's CI section normally reports completed, non-failing checks.

**The one path that bypasses it:** a `check_run[rerequested]` event — clicking **Re-run**
on the `Devflow Review` check — is deliberately left ungated by the preconditions (that is
what makes "Click Re-run … to force a review" true). A forced Re-run can therefore reach
the engine while CI is still running or after it failed. This is exactly why the block
reports *observed* conclusions rather than asserting green: on such a run the engine sees
`in_progress` or `failure` and reports it, instead of being told CI passed.

### Where the `review` profile grants its helpers — the path prefix matters

The read-only `review` profile grants its bundled helpers under the **vendored path prefix
`.prflow/vendor/prflow/`** — e.g. `Bash(.prflow/vendor/prflow/scripts/workpad.py:*)`,
`Bash(.prflow/vendor/prflow/scripts/config-get.sh:*)`,
`Bash(.prflow/vendor/prflow/lib/efficiency-trace.sh:*)`. That prefix is not decoration:
Claude Code matches a `Bash(...)` rule against the command's **leading token after
expansion**, so a helper invoked by any other path — or through a `bash <path>` wrapper —
matches nothing and is silently denied.

The one exception is `load-prompt-extension.sh`, granted **directory-agnostically** as
`Bash(*/load-prompt-extension.sh:*)` on the `review` and `command` profiles only (the
vendored-literal `Bash(.prflow/vendor/prflow/scripts/load-prompt-extension.sh:*)` is granted
on `review`, `implement`, and `command`; see the profile breakdown below). The final-pass reviewer (`requesting-code-review`) is
dispatched as an *installed skill*, so its `${CLAUDE_SKILL_DIR}` anchor resolves to the
plugin checkout rather than the vendored tree; without the wildcard rule its prompt-extension
load is denied and the consumer's extension silently never loads for that reviewer.

**Which profiles carry the `*/load-prompt-extension.sh` wildcard.** The `review` and
`command` profiles both carry the directory-agnostic `Bash(*/load-prompt-extension.sh:*)`
wildcard (the `review` profile for the auto-review reviewer above; the `command` profile
because `/prflow:requesting-code-review` is also invocable directly as an installed skill,
where the anchor resolves to the plugin checkout outside the vendored tree). The `implement`
profile does **not** carry the wildcard — under the Phase-3 dispatch the orchestrator supplies
the reviewer the **vendored literal** `.prflow/vendor/prflow/scripts/load-prompt-extension.sh`,
which `implement` already grants, so no wildcard is needed there.

**`render-prompt-extension.sh` still carries the wildcard on all three profiles, with no
call site left (issues #1264, #1472).** The render-time placeholder that invoked this
wrapper is gone from every skill body — a `Skill`-tool load of a body carrying one returns
a permission refusal and no skill body at all (run `31287654057`) — so nothing in the
shipped surface reaches the wrapper today. The grants are **retained deliberately**:
`Bash(*/render-prompt-extension.sh:*)` on `review`, `implement` and `command` alongside the
vendored literal, because removing the `review` one narrows a locked security boundary and
would need `lib/review-profile.tokens` to move in the same change for no behavioral gain.
The wildcard was needed at all because the anchor resolved to an **absolute** path in the
plugin checkout that no vendored literal matches, and rendering was matcher-gated (run
`31058504896` recorded a `Shell command permission check failed` on an ungranted
placeholder). Retired-channel record, accepted shape and probe run IDs:
[`cloud-allowlist.md`](cloud-allowlist.md).

## Effectiveness telemetry on the cloud `/prflow:implement` job

`/prflow:implement`'s Phase 3.3 drives `review-and-fix` **inline in the orchestrator's
context**, and that loop persists a per-run effectiveness record under
`.prflow/logs/efficiency/` (see [`efficiency-trace.md`](efficiency-trace.md)). Two properties
matter for the cloud tier:

- **The per-iteration `iter-<N>.json` emit is a non-optional obligation on every iteration,
  however the loop was executed** — whether `review-and-fix` ran as a `Skill` invocation or was
  **hand-run via direct `Agent` dispatch** under sandbox friction — and it is written **with the
  Write tool, never a shell `>`/heredoc redirect** the cloud sandbox denies into `.prflow/tmp`.
  A `claude-code-action` permission/sandbox denial is not the local-tier permission classifier and
  is **not** license to leave the instrumented loop: on the implement job `Skill`, `Agent`, `Write`,
  `efficiency-trace.sh`, `workpad.py`, and `config-get.sh` are all allow-listed, so the loop is
  navigable, not blocked. This guarantees the **effectiveness** half of the telemetry
  (dispatch counts, findings, verdicts, fix decisions) is captured even on a degraded run. The
  **token/wall-clock cost** half is captured *live* by the loop; on the **cloud** tier, issue #475's
  Layer-4 harness-side cost floor now reconstructs it deterministically from `claude-code-action`'s
  `execution_file` once the loop is abandoned, while the **local** tier still ships no such backstop,
  so there keeping the loop live is its only (probabilistic) protection. That closed a gap in what was
  built, **not** a limit of the platform: issue #437 observed that the cloud `execution_file` carries
  the tokens, wall-clock, the dispatch roster, and cost with zero agent cooperation, and that the local
  `Stop` transcript's per-message token counts are **real** figures rather than streaming
  placeholders (wall-clock and the dispatch roster were *not* measured on the local tier — see
  [`docs/internal/execution-file-shape.md`](execution-file-shape.md)), so an agent-independent cost floor is
  buildable — and #475 built the cloud half.
- **Implement-vs-runner `--permission-mode` asymmetry.** The read-only `review` runner
  (`devflow-runner.yml`) launches Claude with `--permission-mode acceptEdits`; the
  `/prflow:implement` job (`devflow-implement.yml`) deliberately does **not**. So the implement seam
  reduces friction through the `#275`/`#284` portability discipline — single-statement, leading-token
  helper invocations and the Write tool for scratch files — rather than by widening the permission
  grant. `acceptEdits` would not help here anyway: it auto-approves `Edit`/`Write` plus some
  filesystem `Bash`, not the piped/compound `.sh` forms that were the primary denial.

## Third-party model providers (opt-in, best-effort)

By default every cloud workflow authenticates to Anthropic with
`CLAUDE_CODE_OAUTH_TOKEN` and runs a Claude model. Each of the three
model-running workflow sections — the light command path (`devflow`),
`/prflow:implement` (`prflow_implement`), and the automated reviewer
(`prflow_runner`) — can instead be routed through an **Anthropic-compatible**
endpoint via a `providers` map in `.prflow/config.json` plus one fixed repo
secret, `DEVFLOW_PROVIDER_API_KEY`. Each section picks its own provider and model
independently; with no provider configured the cloud tier matches the
Anthropic-OAuth default (unchanged for a given `claude_model`).

> **Anthropic does not support routing Claude Code to non-Claude models, so this
> integration is best-effort.** It relies on the officially documented
> `ANTHROPIC_BASE_URL` gateway mechanism (code.claude.com/docs/en/llm-gateway-connect),
> but a non-Claude model behind a gateway can behave differently from Claude, and a
> gateway or model update can break a run at any time. Keep the review/runner path
> on Claude if review quality matters (this repo does).

**No provider-by-provider setup walkthrough ships in this release.** The
per-entry field reference — `base_url`, `auth`, `timeout_ms`, `effort_supported`,
and the `env` map — lives in [`.prflow/config.schema.json`](../../.prflow/config.schema.json)
under `providers`, which is the single source for those fields. Two operational
notes the schema does not carry:

- **The `env` map is exported unfiltered** into the job environment. It is read
  only from maintainer-controlled config (base-ref for the runner, the trusted
  default-branch checkout for the command workflows), so do not name a
  runtime-sensitive variable there (`PATH`, `GITHUB_TOKEN`, `ANTHROPIC_API_KEY`,
  …) — a stray such key would shadow the environment of every later step in the
  job, not just the action step.
- **The empty-secret guard.** If a section names a provider while
  `DEVFLOW_PROVIDER_API_KEY` is empty at run time, the job fails loud with an
  `::error::` naming the section and provider, before the action runs. (The secret
  name is a fixed literal on purpose — dynamic secret indexing resolves a missing
  key silently to an empty string, which would fail *open*.)

**Not to be confused with the `provision-auto-mode` provider detection.** The
`CLAUDE_CODE_USE_BEDROCK` / `_VERTEX` / `_FOUNDRY` "provider detection" mentioned
under *Install* and in `scripts/provision-auto-mode.sh` is a **local-tier**
concern — it only gates whether the selectable `auto` permission mode is offered
on those first-party clouds. The config `providers` map here is a **cloud-tier**
model-routing feature and is unrelated to that detection.

## Workflow inventory

`install.sh` copies **two** workflows into a consumer repository — `devflow.yml` and
`devflow-implement.yml`. Everything else below either belongs to this repository only,
or belongs to the withheld auto-review tier.

| Workflow | Shipped by `install.sh`? | Purpose | Needs |
|---|---|---|---|
| `devflow.yml` | **yes** | Light `/prflow:*` command listener (review, review-and-fix, pr-description) — event-driven only, no `workflow_call` | `CLAUDE_CODE_OAUTH_TOKEN` |
| `devflow-implement.yml` | **yes** | Runs `/prflow:implement` on a bare command in an issue comment (issues-only; PR comments never fire it) | `CLAUDE_CODE_OAUTH_TOKEN` |
| `ci.yml` | no — this repository only | Runs PRFlow's own test suite | — |
| `devflow-runner.yml` | no — withheld tier | Reusable runner (`workflow_call`) — a read-only job that only the withheld `devflow-review.yml` ever called. Retained in this repository — unreachable, but kept so the tier stays reconstructable and so the helpers an already-installed consumer copy calls are never swept as dead code. `install.sh` does not copy it, and the vendored plugin slice excludes `.github/` entirely | `CLAUDE_CODE_OAUTH_TOKEN` |
| `telemetry-push.yml` | no — withheld tier | Trusted relay for the auto-review tier's staged telemetry. Retained on the same terms as `devflow-runner.yml` | — |

**`devflow-review.yml` is not in this tree at all.** It was the auto-review caller and
was removed with the withheld tier (issue #936); there is nothing to install and no
`workflows:` list to edit. If you are looking at an older copy of this page that told you
to edit one, that instruction no longer applies. A repository that installed the tier
*before* it was withheld still has its own copy — see
[Withheld from this release](#withheld-from-this-release-the-automatic-pull-request-triggered-review-tier)
for what that means and how to remove it.

The **Needs** column lists the default (Anthropic-OAuth) secret. Each model-running
workflow (`devflow.yml` and `devflow-implement.yml`, plus the retained
`devflow-runner.yml`) **additionally** consumes the optional `DEVFLOW_PROVIDER_API_KEY`
when its section opts into a third-party `provider` (see [Third-party model providers](#third-party-model-providers-opt-in-best-effort)); with no provider configured that secret is unused and the OAuth token alone is required.

PRFlow never creates or overwrites `claude.yml` — that file belongs to
Anthropic's Claude GitHub App, which owns plain `@claude` mentions, Q&A, and
`/security-review`. Every PRFlow trigger negates `@claude`, so the two never
double-fire; if a repo had an old PRFlow-authored `claude.yml`/`claude-runner.yml`/`claude-implement.yml`,
`install.sh` removes it on upgrade (a genuine Anthropic `claude.yml` is left untouched).

## A note on validation

After installing (or updating), run a low-stakes test before relying on the
automation: open a throwaway PR and comment a bare `/prflow:review` on it, and
confirm the run provisions and responds. The CI permission model is settled —
each plugin-using job runs the `vendor-plugin` action right after checkout, which
materializes the plugin at `.prflow/vendor/prflow/` (from the commit, the source
repo, or the pinned `prflow_version` fetch), so its scripts resolve at the literal
`.prflow/vendor/prflow/scripts/…` paths the workflows allowlist. (A
github-marketplace install is deliberately *not* used in CI: the Actions sandbox
can't reach `~/.claude`, and `CLAUDE_SKILL_DIR` is unset there.)
