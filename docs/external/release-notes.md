---
title: "Release Notes"
description: "User-visible PRFlow changes, fixes and upgrade notes."
---

# Release Notes

This page summarizes user-visible PRFlow changes. For a complete change history, see [GitHub Releases](https://github.com/The01Geek/prflow/releases).

**Release cadence:** PRFlow versions continuously and publishes releases periodically, so a published version number skips the intermediate versions developed between two releases. A gap between consecutive tags is expected and does not mean a release is missing.

**Legacy review tier:** Entries about automatic pull-request-triggered review apply only to repositories that installed that tier before July 29, 2026. Fresh installations do not receive it. Use a collaborator comment with `/prflow:review` for the supported cloud review path.

## September 5, 2026

Rename the consumer-facing per-skill extension directory from `.prflow/prompt-extensions/` to `.prflow/skill-extensions/`. `/prflow:init` migrates an existing `.prflow/prompt-extensions/` directory in place (renaming nothing when both directories already exist and reporting a conflict to reconcile by hand), and every reader resolves `.prflow/skill-extensions/` first and falls back to a present `.prflow/prompt-extensions/` with a migrate breadcrumb during the transition, so an un-migrated consumer keeps working. The `DEVFLOW_PROMPT_EXTENSION_ROOT` environment variable and the helper filenames are unchanged.
- **Outcome reactions find the latest implement trigger on long-running issues.** PRFlow checks every issue-comment page before choosing the triggering comment, so completion and blocked reactions reach the current request even after an issue has accumulated more than 100 comments. ([#191](https://github.com/The01Geek/prflow/issues/191))
- **Harden the `/prflow:create-issue` (`/prflow:specs`) run helpers.** The run's slug is now
  keyed on a run-directory registry (`run-meta.json`) instead of a session id, so a continued
  session recovers its own run, cleanup no longer leaves orphaned `issue-run-slug.<session-id>`
  pointer files behind, and concurrent runs and linked worktrees are told apart by topic and
  start time. A new `scripts/check-draft-provenance.py` checker, run in the draft bootstrap
  beside the existing two, catches a provenance signature that landed mid-body before the draft
  is presented. (#198)

## September 4, 2026

Fix the implement skill's end-of-run reaction so it posts the correct outcome on both tiers.

`scripts/react-to-trigger.sh` now accepts `--outcome complete|blocked` with `--issue`, choosing the reaction itself (🎉 `hooray` for a completed run, 👎 `-1` for a blocked one) and resolving the triggering comment itself — from the event file, else the newest non-workpad implement-trigger comment. The implement skill's outcome-reaction fence becomes a single leading-token call with a prefix-removed/anchor fallback ladder, so the correct reaction now posts on both the local and cloud tiers instead of re-posting the pickup 🚀.
- **Closed fail-open and security-shaped defects in the implement helper scripts.** The
  checkout-fingerprint helper now hashes untracked files without writing them to the git
  object store, so a verification step no longer copies an untracked secret into
  `.git/objects`. The acceptance-criteria parser tags only unambiguous live-environment
  phrases, so a code-verifiable criterion is no longer dropped from the merge gate on a
  loose phrase match. The verification flight honours its `DEVFLOW_FLIGHT_NOW` clock
  override only behind a companion test-clock gate and marks any handle written under it,
  so the override is inert in production. A `dispatched-but-lost` review-coverage
  disposition is now admitted only over a measured roster with a recorded dispatched
  reviewer, so a run cannot finalize on a lost-dispatch claim with no dispatch on record. (#181)
- **Trimmed every shipped agent `description` to a short trigger line and dropped the unused web
  tools from the discovery agents.** Each `agents/*.md` description is now a single ≤120-byte
  trigger statement, so every enabled session carries several kilobytes less system-prompt text
  on every turn; the worked scenarios and secondary triggers moved into each agent's body, which
  loads only when the agent runs. The `code-explorer` and `code-architect` discovery agents no
  longer grant `WebFetch` or `WebSearch` — an autonomous implement run's discovery agents cannot
  reach the web. A new byte ceiling in the frontmatter validator keeps the descriptions from
  growing back. (#179)
- **`/prflow:implement` Phase 1 now stops with a Blocked status on a failed push or uncommitted tracked changes instead of continuing.** A failed branch push is reported as a Blocked run naming the cause, rather than silently leaving an unpushed branch; uncommitted tracked changes stop the run for you to commit or stash, rather than gaining a stray commit on the base branch; and the setup file's agent-file fallbacks now resolve in a consumer checkout. (#178)
Make the implement Phase 2 sweep prose decidable and consumer-safe (issue #180). Comment
relocation now has one owner: a non-preventing comment is deleted or shortened in Phase 2, and
an explanation worth keeping is recorded through a `relocate to docs:` workpad note that Phase 4.1
hands to the docs pass. The §2.5 workflow-edit guard keys on the durability helper's observable
stderr token rather than a run-facts field that is never produced. The §2.2 complexity assessment
routes by one rule (Path B when any Complex bullet holds or the touched-file count exceeds five;
otherwise Path A). The test-first gate is runner-neutral — it confirms the runner collected and
reported the new test and extracts a branch-selecting snippet into a unit the repository's test
runner can drive, with a no-runner arm for repositories that have none. PRFlow-internal names are
removed from the shipped Phase 2 bodies.
- **`/prflow:implement`'s review phase now stays predictable when a tool is missing or refused, and never commits its own run scratch.** The pull request an implement run opens no longer carries PRFlow's working files, even in a repository whose ignore rules predate them. When the `/simplify` step is unavailable on your runner, the workpad records it as unavailable instead of an empty result that reads like a clean pass. When the review-and-fix step cannot be loaded, the run stops as Blocked and names the refusal, instead of attempting an unbounded review by hand. The review phase's guidance now reads correctly in any repository, not only PRFlow's own. (#182)

## September 3, 2026

Key the create-issue run-slug pointer by session. `scripts/cleanup-create-issue-run.sh` now
owns the pointer through `--record-slug` and `--resolve-slug` modes and writes it to
`.prflow/tmp/create-issue/issue-run-slug.<session-id>`, so concurrent `/prflow:create-issue`
runs in one checkout no longer overwrite each other's slug and no run adopts another session's
identity after context compaction. On a harness that exposes no session identity the helper
reports that plainly and the run takes the existing title-derived fallback.
- **Trust a GitHub App as a configured bot login everywhere by normalizing logins through one shared rule (issue #157).** A new `lib/login_normalize.py` trims whitespace, strips a leading `app/` and a trailing `[bot]`, and lowercases both a login and each configured comparand before comparing, so an `allowed_bots` (or `watched_authors`) entry written as the bare slug, `<slug>[bot]`, `app/<slug>`, or in mixed case all match the same App. The deferral matcher, the lint-adjudication allowlist arm, the workflow authorization gate, the CI review trigger, and the retrospective scanner now decide login trust and identity through this rule instead of their own strip-and-compare, so a GitHub App author's Scope-Acknowledged deferrals are honored rather than rejected as `untrusted-filer`. The `allowed_bots` and `watched_authors` config-schema descriptions now state the accepted entry forms. (#157)
- **Dead cloud runs now name why they died, and their comments are shorter.** When a cloud `/prflow:implement` or `/prflow:review` run ends in error, the run log, the step-summary diagnostics block, and the comment it posts now carry the engine's failure cause — the result subtype and terminal reason, an API-retry error, or a rejected rate-limit event — so a usage-limit rejection reads differently from a genuine stall without downloading the transcript. Each standalone failure comment is trimmed to a headline, the cause, and the run link (plus the trigger line on the auto-resume arms), and the review stall backstop headline now reads PRFlow. ([#158](https://github.com/The01Geek/prflow/issues/158))
- **Renamed the `/prflow:receiving-code-review` skill to `/prflow:fix`.** The skill that
  checks review feedback before applying it is now invoked as `/prflow:fix`; its description
  still contains the text `receiving-code-review` so a search by the old name still finds it.
  The old command name stops resolving in this release — there is no forwarding shim. A
  consumer who customized the extension keeps it working: the extension loader, asked for
  `fix`, reads a still-present `.prflow/prompt-extensions/receiving-code-review.md` when
  `fix.md` is absent and prints a breadcrumb telling you to rename the file, and `/prflow:init`
  (and `install.sh`) rename it to `fix.md` on an existing repository. Rolling the plugin back
  to a pre-rename version after init has renamed the file leaves the old skill reading an empty
  extension until you rename the file back. This release does not migrate consumer-side
  references to the old command that live outside the plugin — permission rules, hooks,
  scheduled commands, and any text in your own `CLAUDE.md` that names `/prflow:receiving-code-review`
  should be updated to `/prflow:fix` by hand. (#152)

## September 2, 2026

- **Warn at install time when a preserved guarded workflow's sidecar merge would strand the cloud implement gate.** When `install.sh --apply` preserves a locally-modified guarded artifact (the lint manifest, the `setup-project-env` action, or `.github/workflows/devflow-implement.yml`), the `PRESERVED` line now states that `.prflow/install-state.json` is bound to the kept bytes and that the installer must be re-run in apply mode after the sidecar is merged or adopted, and the apply prints one summary line naming every such sidecar and the exact re-run command. The cloud provisioning readiness refusal for a guarded `digest-mismatch` now names a merged or adopted `.prflow-new` sidecar as a cause, and the install and cloud-run docs carry the re-run-in-apply-mode step. (#92)
Reconcile the create-issue fresh-context audit's criterion-shape dimension with the issue template, and bring out-of-scope and Quiet Killer observations into the audit ledger.

The audit prompt's criterion-shape dimension no longer flags a qualifier that a drafter correctly wrote inside a criterion: a statement narrowing, bounding, quantifying, defining a term for, or naming a verification route for a criterion is never a finding when it repeats across criteria or when an identical copy also sits in the grounding block, and the dimension's flag toward the block is limited to pure framing whose deletion changes no criterion's truth value. A block statement that disagrees with the inline qualifier stays a finding. The authoring-discipline RESTATEMENT shape excludes those inline copies, the issue template is the single canonical statement of the rule, and the steelman reference points at it rather than restating it.

The auditor now reports every out-of-scope observation on a targeted round, and a qualifying Quiet Killer on any round, as an ordinary numbered finding under the per-finding bar; an out-of-scope finding carries an `out-of-scope` tag and changes no per-claim verdict, and `Quiet Killer: none` stays a non-finding. The per-round `--findings-count` tally is now defined as the number of findings the auditor returned, checked at adjudication to equal must-revise plus advisory plus invalid: `record-return` refuses an accepted return that omits the tally (`findings-count-required`), `record-adjudication` refuses a round whose recorded tally disagrees with the adjudicated class total (`findings-count-mismatch`) and emits a `tally-unrecorded` breadcrumb for a round returned before this change, and the audit summary renders `findings_count` as `none` when any completed round carries no recorded tally rather than presenting a partial sum as the total.
- **Finished the DevFlow→PRFlow rename for the remaining visible names.** The implement
  workpad's reflection section now reads `## PRFlow Reflections` and shows its bullets
  directly, with no collapsed `<details>` control. The shipped command workflows now display
  as `PRFlow` and `PRFlow (implement)` in the Actions tab (the reusable runner workflow's
  display name is likewise renamed to `PRFlow Runner (reusable)`, though it is retained rather
  than shipped). The cloud review check-run's rename to `PRFlow Review` is reader-side: the
  in-tree readers and self-exclusion filters now accept both `PRFlow Review` and the historical
  `Devflow Review`, so telemetry on older pull requests keeps working — the workflow that would
  post the check remains withheld from this release, so no in-tree job emits it today. Records
  written before the rename keep working: the workpad reader and updater accept both the new
  heading and the old `## Devflow Reflection`. Environment variables, workflow filenames, and
  command aliases are unchanged. (#112)
The context-cost instruments now read the cloud execution-transcript shape, and each cloud
implement run records its peak main-thread context and per-phase file-read counts on its
telemetry record. A single shared transcript reader in `scripts/context_eval_shared.py`
strips the scrubbed artifact's leading `# DEVFLOW SCRUB CAVEAT` line and parses a whole-file
JSON array, a whole-file object, or JSONL; the corpus collector now accepts `.json` files
alongside `.jsonl` and tallies every other suffix. `scripts/extract-execution-cost.py` adds
two `harness_cost` fields, `peak_main_thread_context` and `phase_file_reads`, which flow
through the telemetry record into `scripts/implement-run-report.py --retro`, so the weekly
retrospective's "Implement runtime trends" section reports the trailing-window median and
maximum peak context and total phase-file reads. Records written before this change lack the
two fields and are excluded from those aggregates (recorded as unestablished, never zero).
These are instrument outputs only — no threshold, ceiling, regression rule or gate reads them.
- **New opt-in weekly scheduled retrospective workflow.** A new shipped workflow,
  `devflow-retrospective.yml`, runs `/prflow:retrospective-weekly` automatically every
  Sunday at 05:23 UTC and on manual dispatch from the Actions tab, so the
  self-improvement loop keeps running without anyone remembering to start it. It is
  gated by a new per-workflow config key, `workflows["prflow-retrospective"]`, read from
  the default branch's `.prflow/config.json`: only the JSON boolean `true` enables it, so
  repositories are opted out by default and pay no Actions or Claude cost until they opt
  in. When an unmerged `devflow/learnings-*` state PR is still open, the run skips the
  retrospective and files a single reminder issue to merge it first.
  (#93)
- **`/prflow:init` now installs the cloud-tier workflows, not just the config.** After scaffolding `.prflow/config.json`, init runs the installer to place the `.github/workflows/` files whenever the config enables a workflow tier, so a repository whose config says the cloud tier is on no longer ends up with no workflows on disk. When no tier is enabled it asks first, and whenever it installs it points you at the `.github/` diff to review before committing. (#124)
Finish the DevFlow→PRFlow brand rename by sweeping the remaining "DevFlow" brand prose in comments, docs, skill bodies, prompt extensions, and test files to "PRFlow", draining `lib/test/brand-devflow-buckets.json`'s `pending_sweep_baseline` to empty. Occurrences that must stay "DevFlow" — the superseded provenance-label value that selectors still match, and the brand-sweep lint's own fixtures — are recorded in their frozen buckets.
Remove every `$?` from the shipped bash fences under `skills/` and `agents/` — the cloud permission matcher refuses any command carrying a parameter expansion, so a status trailer such as `; echo "seed-rc=$?"` was silently refused and burned a round trip. Each status-trailer site now ends in a constant trailer `; echo "<name>-done"` (a measured-permitted `;`-joined sequence with no expansion) and its prose routes on the tool result; each `VAR=$?` capture becomes the bare command routed on its own output, or an `if`/`then`/`else` block where control flow needs it. The worktree-fence lint (`lib/test/lint-worktree-fence-shapes.py`) now applies its `$?` rule to every tracked `skills/`/`agents/` file, enumerated from `git ls-files` with no baseline of tolerated hits, so a reintroduced `$?` fence turns the suite red. The cloud grounding block gains a refused-shape row naming the argument-position `simple_expansion` refusal and a `2>` stderr-redirect row, and no longer attributes `simple_expansion` to a leading assignment.
- **Route the light cloud jobs onto a cheaper runner with the new optional `DEVFLOW_LIGHT_RUNNER` variable.** The comment-driven workflows previously ran every job — including one-core helpers and the model-API-bound standalone review — on the single runner named by `DEVFLOW_RUNNER`. Set `DEVFLOW_LIGHT_RUNNER` (a bare label or a JSON label array, same shapes as `DEVFLOW_RUNNER`) and the light jobs move to it: `config`, `review_dedupe`, `gate`, `review_finalize`, and the `command` job on a standalone `/prflow:review` in the review workflow, plus `config` and `gate` in the implement workflow. A review-and-fix run and the implement `claude` job keep `DEVFLOW_RUNNER`'s 8-core capacity for the test suite. Leave `DEVFLOW_LIGHT_RUNNER` unset and every job stays exactly where it is today. ([#134](https://github.com/The01Geek/prflow/issues/134))
- **A resumed `/prflow:implement` run now clears a stale `PRFlow:Stuck` label and terminal status at the earliest resume hook.** When a run resumes an issue whose workpad status is terminal (any of `Failed`/`Cancelled`/`Blocked`/`Complete` — the stall backstop writes `Failed`/`Cancelled`), a shared reset routine resets the status to an in-progress word and — through the existing status-to-label mirror — swaps the managed status label (`PRFlow:Stuck`, or `PRFlow:Complete`) for `PRFlow:Implementing` on the issue and its open pull request. On the cloud tier this happens on the config/gate resume branch before the agent job starts; on the local/interactive tier at the start of Phase 1. The resume-kind classification stays correct by reading the prior terminal status from a durable workpad marker. (#137)

## September 1, 2026

- **`/prflow:create-issue` now names the recovery when the post-approval create path refuses on a run with completed audit rounds.** After the user elected *Create it as-is*, the state owner could refuse with no stated remedy: the `unaudited-revision` eligibility answer wrote nothing to stderr, and `record-creation-epoch --round 0` refused without naming which round to pass. Both refusals now name their own recovery — the `unaudited-revision` refusal points at the user's own `record-override --kind user-decline --surface step4-offer` filing election (and a fresh clean audit round as the alternative), and the `--round 0` refusal on a completed-round state names the newest completed round as `--round <M>` for the caller to re-issue. The shipped `create-issue` references state the rules these recoveries follow, so a run that trusts the references files the issue instead of stalling. (#82)
Trust established docs-verify results in `/prflow:create-issue` Step 1, and gate guard claims behind a machine-graded `Verified:` bullet.

The Step 1 shallow→deep escalation predicate no longer escalates on an `ABSENT` doc-reliability verdict: `ABSENT` is an established absence the shallow arm has already produced, so the trigger set is now exactly `UNRELIABLE`, an `unestablished` duty, and a `judged-not-engaged` duty whose bearing observation is anything other than `none-observed`. The `docs-verify` duty-status contract now states that a duty carried out with an empty result is `discharged` (not `judged-not-engaged`, which is reserved for a duty not carried out), and its `Search space surveyed` report field now states the resolved internal-doc location beside the `--search-space` operand so Step 1 can escalate an *exact operand and population identity* duty when the peer surveyed a location differing from the orchestrator's own `.docs.internal` resolution. An acceptance criterion resting on an authorization-guard, permission-key, or gate-condition claim about existing code must now carry a `Verified:` bullet that `scripts/check-verified-premises.py` grades `handle=path-quote state=holds`, so a solo peer's guard claim cannot become a requirement unverified.
- **The `/prflow:create-issue` audit summary now names which round its per-class counts describe.** The audit state tool emits a new `counts_round` token — the round number of the latest completed whole-draft round the class counts (`must_revise`, `advisory`, `invalid`, unresolved-at-close) are read from — on both its `summary-block` and `query-summary` lines, and the Step 4 audit summary line labels those counts with that round and says when a targeted re-check also ran. A two-round run that ran a targeted re-check no longer reads as one that lost its second round. Selection is unchanged: the counts still describe the latest whole-draft round, and a targeted round is still skipped. (#73)
`check-verified-premises.py` now grades the `Verified:`-bullet shapes the issue templates
actually produce. A bullet that cites a repository path and carries a backticked code literal
(with no double-quoted sentence) is graded on that literal — a hit reports `holds`, a miss
`unestablished` and never `refuted`. An absent weak span no longer short-circuits a bullet that
also cites a present path; the resolving quotation is adjudicated and the absent span is disclosed.
A `` `Verified:` `` label (backtick after the colon) is now consumed whole and grades like the bare
label. The premises quality group and the Step 3.5 handle-repair table name a prose form for the
two shapes the checker cannot grade — an externally verified fact (`Per <URL>, checked <YYYY-MM-DD>:
<fact>`) and a documentation-absence claim — so authors write them correctly from the start instead
of demoting a verified fact mid-gate, and the implement-side audit re-fetches those `Per <URL>`
sentences rather than re-litigating them as unverified.
Enforce the title-heading and staged-path contracts of the create-issue staged canonical-draft write (issue #79).

`stage-draft-write.py stage` now refuses stdin whose first two non-blank lines are both `# ` title headings with a `duplicate-title` breadcrumb, so a re-stage that doubles the draft title can no longer reach a created issue, and it resolves a relative `--path` base to an absolute path (refusing a rooted drive-less base on a Windows-style module with `staged-base-driveless`) so the printed `path=` is accepted by `record-staged-write --path` unmodified. The `stage --help`, `emit-body --help`, and the Step 3.6 staged-write procedure and posting-recipe prose now state these contracts.

## August 30, 2026

- **`/prflow:specs` now works as a spelling of the issue-drafting command.** It runs the same
  pipeline as `/prflow:create-issue`, which keeps working unchanged — no existing invocation
  breaks, and nothing needs updating in a repository that already uses the older spelling.
- **An interrupted `/prflow:implement` run resumes from its own pushed work.** A fresh run
  interrupted during implementation — after its checkpoints had pushed, but before the draft pull
  request opened — used to stall when re-triggered, because it could not tell its own branch from
  an unrelated one. It now recognizes that branch and continues where it left off. The guard that
  refuses a branch carrying foreign history is unchanged.
- **`/prflow:implement` works again in an isolated worktree.** Two commands were refused by Claude
  Code's worktree-isolation classifier, which left the run's marker file empty and its session
  guard blocking every session in that checkout. Both now run through bundled helpers that read
  what they need from their own environment rather than from a shell variable.
- **Fix-loop subagents can no longer land a commit on the wrong branch.** They are barred from
  switching the checkout, and the branch is verified after each one returns — a mismatch stops the
  loop instead of committing.
- **A cloud implement run records the branch it is working on.** The workpad's branch line could
  silently stay at its placeholder, because the command that filled it in was refused before it
  ran. It is now resolved directly, and reports a named reason instead of writing nothing when it
  cannot be determined.
- **Reviews finish faster.** Review subagents no longer launch the project's test suite — a
  verifier settles a claim about a test by reading that test's source, and says so explicitly when
  reading cannot settle it, leaving suite evidence to the run itself. Separately, later fix-loop
  iterations reuse the verification checklist from earlier ones instead of re-deriving it. Review
  coverage is unchanged by both.
- **A complete review is no longer reported as "Review failed" over a missing bookkeeping line.**
  The evidence gate now reads the artifacts each review actually writes, so a review that did its
  work keeps its verdict even if the reviewing agent omitted a progress line.
- **Four shipped tools report a clean not-applicable result in a consumer repository.** They each
  detect that a required development-tree input is absent, print one message naming it, and exit
  successfully — instead of a raw traceback or a misreported integrity failure. Behavior inside a
  PRFlow development tree is unchanged.
- **Comment traffic that can never start a command no longer starts a workflow run.** Both shipped
  command-listener workflows now decide this before any job spins up, so unrelated comments on
  issues and pull requests stop consuming Actions minutes.
- **The auto-mode provisioning step was removed from `/prflow:init`.** The optional, consent-gated
  step that made the `auto` permission mode selectable in the Shift+Tab cycle is retired. It only
  ever affected the third-party model providers (Bedrock, Vertex, Foundry) and was already a no-op
  on the Anthropic API. If you previously opted in, your existing `~/.claude/settings.json` value
  is left untouched.

## August 29, 2026

- **`/prflow:create-issue` asks one fixed decision question, and tells you how the last audit
  went before offering another round.** The pre-approval question now has fixed options — run an
  audit round, print the full draft in chat, create it as-is (or *file anyway*, its own option, when
  unresolved audit findings stand against the draft), or change something first — asked through your runner's question
  tool. A re-offered audit round states the previous round's verdict, findings by class and what
  remains unresolved, so the choice is informed. Clarification questions never offer "let the
  implementer choose" as an answer, and the no-options gate no longer flags an "or" inside a
  negation or a list.
- **A pull request from a fork can pass the release verification check.** Artifact
  verification is skipped for an ordinary pull request, because the digest manifest describes
  the published release and any edit is a mismatch. That exemption was gated on the pull
  request coming from the repository itself, so a contribution from a fork was verified
  against the manifest instead and failed on every file it changed — an outside contributor
  saw a red required check they could do nothing about. Origin no longer decides it. A
  release candidate is still verified whatever its origin, and a fork that touches the
  verifier is still refused.
- **A published tree carrying no provenance is refused.** The guard that rejects a missing
  `.release/source.json` keyed on the branch name alone, and a push carries the branch name
  `main` rather than a release branch name — so deleting that one file reported the whole
  check as passing, on the published branch as well as on the pull request that removed it. A
  push without provenance, and a pull request that deletes provenance the branch it targets
  carries, are both refused now.
- **`/prflow:create-issue` now prints the drafted issue in chat only on request, keeping the
  saved-file path as the default presentation.** Step 4 writes the draft file and shows its path,
  the audit summary, the disclosures and the investigation record first — without the body — and
  the combined decision question carries a new *print the full draft in chat* answer that renders
  the title and body verbatim on demand. A write-failed run, an unbound draft, and a
  non-interactive run still print the body as before. Approval stays explicit and about the exact
  saved bytes. (#2122)
- **PRFlow's public repository is now a generated distribution tree.** Development moved to a
  private canonical repository, and every file published here is produced by a deterministic
  exporter and verified before release. Nothing about installing or using PRFlow changes: the
  install commands, marketplace name, plugin name, command names and repository URL are all
  unchanged, and existing installations and version pins keep working. The published tree is
  smaller and easier to review, and each release now carries its own provenance under
  `.release/` — a source-commit record and a SHA-256 for every published file, so any published
  tree can be checked against the digests it ships with.
- **Installer and documentation links now point at the public documentation site.** Messages from
  `install.sh` and `SECURITY.md` that previously referenced maintainer-only documentation paths
  now link to the equivalent pages on the documentation site, so a reader can always reach them.
- **The documentation site deploys again.** The frozen-`DEVFLOW_*` advisory moved into the
  published cloud-setup page, and it carried its generated region's HTML comment delimiters
  with it. The documentation site parses those pages as MDX, which rejects an HTML comment
  outright, so the deployment failed and the site kept serving its previous build. The
  region's markers are now MDX comments and the docs build validates clean.
- **Release verification covers two surfaces it previously skipped.** SVG files are text and
  can carry anything, but were absent from the scanned set, so images shipped unexamined.
  The documentation navigation manifest is JSON, so the markdown link checker never read it
  — a navigation entry pointing at a page that no longer ships would have published a broken
  site. Both are now checked on every release, each proven against a planted defect.
- **The release verification check could be bypassed by a pull request from a fork.** The
  exemption that lets a maintainer change the verifier keyed on the branch name, and a fork
  chooses its own branch names — so a fork branch named `policy-update/…` skipped both the
  judge-comparison and the artifact verification, and reported the required check green on a
  tree that had never been verified. The judge-comparison step's exemptions are now gated on
  the pull request coming from the repository itself, so a fork can never introduce or edit
  the verifier that judges it.
- **The shipped workflows now declare a least-privilege floor.** They carried no top-level
  `permissions:`, so in a repository whose default workflow permission is read-and-write,
  every job received a full read-write token whether it needed one or not. They now default
  to `contents: read`, and the jobs that genuinely need more continue to declare it.
- **The implement workflow's gate job pins its checkout to the default branch**, matching its
  sibling. Without the pin, `actions/checkout` falls back to `GITHUB_REF` silently, leaving
  the trusted-tree property inferred from the trigger rather than stated in the file.

## August 28, 2026

- **Catch vacuous preservation tests and documentation-scope leaks earlier.** Implement runs now require distinguishable preservation fixtures, classify cleanup failures, and stop plain label-and-em-dash issue peers from becoming mandatory documentation. ([#2110](https://github.com/The01Geek/prflow/pull/2110))
- **Mirror the implement run's status onto issue and pull-request labels.** Every
  `/prflow:implement` run now keeps a managed status label in sync on its issue, and on its
  pull request once one exists, so a maintainer sees a stalled or finished run from the issue
  and PR lists without opening the workpad comment. Three labels track the workpad Status:
  `PRFlow:Implementing` (a run is in progress), `PRFlow:Stuck` (a run stopped and needs
  attention), and `PRFlow:Complete` (a run finished). The labels follow the workpad status
  automatically — applied even on the statuses written after the agent has already stopped —
  and a repository turns the whole feature off with the `status_labels.enabled` config key (on
  by default). (#2117)

## August 27, 2026

- **Implement runs author tests in proportion to the change.** On a small change, an `/prflow:implement` run can now skip extra test ceremony that would be out of proportion to the change, while still writing a covering test for each behavior change and recording what it waived on a `Test authoring waived:` line in the pull request's Test Plan. The coverage reviewer honors a recorded waiver — lowering only lesser-severity findings on the named surfaces while keeping its most serious findings at full strength — and a fresh install runs that reviewer only on the first fix-loop iteration. You get this through the normal plugin update. [#2031](https://github.com/The01Geek/prflow/issues/2031)
- **Improvement: `/prflow:implement` runs reach the coding phase sooner.** The pre-coding issue-claim audit now delivers all of its per-pass records to the run's workpad in one batched update at the end of the audit (plus one further call in the uncommon case where the records span more than one reflection kind), instead of a separate network write as each pass completes. Runs spend less time in the pre-coding phase and cloud runs hold their Actions slot for less time, with the recorded workpad content unchanged. You get this through the normal plugin update. [#2018](https://github.com/The01Geek/prflow/issues/2018)
- **Cloud review jobs fail when a review skips its own checks.** A cloud `/prflow:review` or `/prflow:review-and-fix` run that posts a merge-gating verdict without evidence that the review engine ran its verification phases now turns the job red, dismisses the unbacked review, and leaves a comment naming what is missing. A review that legitimately skips the checklist stays green, and a compliant run behaves exactly as before. You get this by re-running the installer to refresh your workflows. [#2075](https://github.com/The01Geek/prflow/issues/2075)

## August 25, 2026

- **Improvement: Issue-implementation runs start with verified lint tools already installed.** The installer now ships a lint manifest and publishes a digest-bound compatibility marker to your repository, and `/prflow:implement` cloud runs install the pinned ShellCheck and Ruff set — run-local and digest- and version-verified — before the agent starts, so runs no longer spend paid turns rediscovering and installing those tools. The change also hardens the cloud review job so it can never execute the environment-setup action edited in the pull request under review. You get this by re-running the installer to refresh your workflows. [#1963](https://github.com/The01Geek/prflow/issues/1963)
- **A completed `/prflow:implement` run can no longer silently leave a prompt-extension record unwritten.** Each run keeps one `prompt extension resolved: …` row per extension it consumes, and an unticked row is meant to be the run's deliberate record that it could not establish that extension's state. But ticking the row was a voluntary bookkeeping step, so a run that resolved an extension and simply forgot to record it produced the exact same unticked row as one that genuinely skipped it — and nothing caught the difference. Finalizing a run as `Complete` is now refused (naming each offending row) while any such row is both unticked and missing its `state not established` note, mirroring the existing refusal on an unticked acceptance criterion. A ticked row, an unticked row with that note, and an older workpad that predates these rows all still finish normally, and `Blocked`/`Failed` outcomes are unchanged. The effect is that an unticked extension row on a completed run is now trustworthy as a deliberate record rather than a possible oversight. You get this through the normal plugin update. [#1943](https://github.com/The01Geek/prflow/issues/1943)
- **Fix: a review no longer runs against a partly loaded review engine.** `/prflow:review-and-fix` — and the review step inside `/prflow:implement`, which drives it — reads PRFlow's review engine from your repository as a file, and it used to accept whatever came back as long as it was readable. A file delivered in part was therefore indistinguishable from a whole one, so a run could assess your pull request against review stages that never arrived and still report a result. The run now confirms it reached the end of that file before acting on it, and where it cannot it stops with `engine-root: incomplete` and the path it read, having applied no fixes and produced no verdict. The shadow pass reads the engine the same way and reports the condition as a coverage gap rather than stopping; a review started with `/prflow:review` loads the engine through your client instead of reading it as a file and is unaffected. You get this through the normal plugin update. [#1603](https://github.com/The01Geek/prflow/issues/1603)

## August 19, 2026

- **Fix: two Windows-only failures in PRFlow's Python helpers are closed.** On a Windows host whose default codec is not UTF-8, a first-party helper that printed an em-dash or emoji used to crash with an encoding error; every tracked helper now forces its output to UTF-8 on startup, so that output prints cleanly. Separately, the issue-audit step rejected a Windows drive-letter path (`C:/Users/…` or `C:\Users\…`), blocking `/prflow:create-issue`'s audit on Windows; the path check now accepts the absolute path forms the host actually uses — a leading `/` on Linux and macOS, or a drive-letter (`C:/…`, `C:\…`) or network-share root on Windows — and uses it unchanged. Linux and macOS are unaffected. You get this through the normal plugin update. [#1762](https://github.com/The01Geek/prflow/issues/1762)

## August 14, 2026

- **`/prflow:create-issue` now writes a minimum-sufficient implementation brief.** The issue body carries the decisions an implementer cannot safely derive on their own and keeps material only when removing it could change what gets built; the investigation behind those decisions — supporting evidence, audit history and detail the repository would rediscover during implementation — is recorded separately instead of being mixed into the body. So an approver reviews the implementation contract rather than the whole investigation, and an implementer spends less effort separating decisions from derivation. A `Verified:` premise stays in the body when the implementation relies on it and moves to the record when it is only confirmatory, and the over-retention audit flags a repeated claim only when no consumer or check needs that copy — it never touches the required projections or machine-read sections. No length, size or criterion-count limit decides what survives, and no load-bearing detail is dropped to make the body shorter. You get this through the normal plugin update. [#1676](https://github.com/The01Geek/prflow/issues/1676)
- **Fix: `/prflow:create-issue` no longer dies when your client lacks its first-choice task-tracking tool.** The workflow tracks its own progress through a seven-step checklist, and it used to reach for one particular tracking tool and stop dead if your client did not offer it — reporting an error such as `No such tool available` after it had already told you the checklist was set up. It now tries the tracking tools it knows in order, moving to the next one whenever the one it tried is unavailable, and asks your client for tools it has not yet offered before giving up. If none of them work, it keeps the same checklist inline in the conversation instead, so the run continues either way. It also announces the checklist only once it genuinely has one, and reports any tool it could not use just after that first line rather than in place of it. Clients that already offered the first tool behave exactly as before. You get this through the normal plugin update. [#1689](https://github.com/The01Geek/prflow/issues/1689)
- **Fix: `/prflow:implement` reliably records its cleanup gate on Windows Git Bash and MSYS2.** During implementation, `/prflow:implement` ticks a Progress row when its code-cleanup gate finishes. On Windows Git Bash and MSYS2 hosts, the value it passed to do that looked like a Unix path, so those shells silently rewrote it into a Windows path before it reached Python — the row stayed unticked and the run reported a spurious miss. The gate now passes a plain, non-path value that those shells leave alone, so the Progress row is ticked as expected. Nothing about the row's familiar label changes, and other platforms were never affected. You get this through the normal plugin update. [#1679](https://github.com/The01Geek/prflow/issues/1679)

## August 13, 2026

- **An issue can now say "no documentation is needed" without turning a page it mentions into required work.** When you write an issue, its `Documentation Needed` block can list files that the change must update, and `/prflow:implement` treats every file named there as a mandatory deliverable. Previously, if you wrote that no documentation was needed and then named a file to explain *why* it was already fine, that mentioned file was still demanded — so the honest, informative phrasing was punished and an otherwise-finished run stalled asking you to edit a page that needed no change. You can now open the block with the standalone word `none` (case-insensitive, optionally followed by a single `,` `.` `;` or `:`), and the block promises nothing — you can still add a sentence and name the page that explains the decision. The word must stand alone as the block's opener: an ordinary sentence such as `None of these pages may be skipped:` still names its files as required. The routine documentation pass runs and updates whatever the change warrants regardless. [#1663](https://github.com/The01Geek/prflow/issues/1663)
- **Fix: Implement review progress stays on the issue workpad** — An inline review-and-fix pass no longer opens a separate progress comment on the draft pull request during `/prflow:implement`; its review stages update the existing issue workpad instead. A standalone pull-request review still maintains its own live progress comment. [#1668](https://github.com/The01Geek/prflow/issues/1668)

## August 12, 2026

- **Improvement: Acceptance Criteria Now Cover Every Desired Outcome** — PRFlow now checks that every independently testable outcome in an issue's Desired Behavior is represented by its acceptance criteria before implementation begins. If an outcome is uncovered, issue creation revises the draft and implementation stops for refinement instead of silently omitting the requirement or inventing a criterion. [#1662](https://github.com/The01Geek/prflow/issues/1662)
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

## Older Releases

Entries from July 2026 are in the [release notes archive](/docs/reference/release-notes-archive-2026).
