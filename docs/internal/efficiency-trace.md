# `/prflow:review-and-fix` subagent effectiveness telemetry

**Skill:** `skills/review-and-fix/references/loop-exit.md` (Loop Exit, *Subagent effectiveness trace*; the reference the thin `skills/review-and-fix/SKILL.md` root routes to at loop termination — see issue #530)
**Derivation:** `lib/efficiency-trace.jq` + `lib/efficiency-trace.sh`

When `/prflow:review-and-fix` runs, its fix loop dispatches a lot of subagents per iteration —
up to six Phase-3 review agents (four always-on plus two structurally-gated analyzers) plus the
Phase-2 checklist verifiers, re-run across as many iterations as the configurable cap allows
(`prflow_review_and_fix.max_iterations`, default 5), plus a shadow pass (the parent-orchestrated convergence audit — see
[shadow-review.md](shadow-review.md) for its mechanics and the `step_2_6` telemetry shape). This
doc records *why* the run now emits a durable effectiveness record, what that record contains, and
how each subagent earns its verdict.

> **Related measurement substrate.** The offline verification-launch baseline
> (`scripts/verification_baseline.py`, issue #527 Wave 1; see
> [`docs/internal/workflow-flight-recorder.md`](workflow-flight-recorder.md#verification-launch-baseline-wave-1))
> is a sibling measurement: it baselines actual verification-command launches
> (transport-retry candidates, intentional reruns, independent lifecycles) from
> local native transcripts plus a local + cloud lifecycle census, reusing the
> same unknown-is-not-zero and source-provenance discipline. It measures
> verification-launch cost, not subagent effectiveness.

## The problem this closes

The per-iteration workpads under `.prflow/tmp/review/<slug>/<run-id>/iter-<N>.json` (run-scoped, so
repeated or concurrent reviews of the same PR never clobber each other) already carry the
data needed to answer "which subagents earned their cost on this PR" — `phase3_findings`
(with `agent`, `corroboration_count`, `fix_decision`), `fix_decisions`, and per-phase cost
telemetry (calls / tokens / wall-clock). But `.prflow/tmp/` is **ephemeral** scratch in every
run — gitignored and routinely cleaned out locally, and destroyed wholesale when a cloud GitHub
runner is torn down. Either way, the moment a run finishes the data is liable to vanish.
Optimization decisions ("is this agent pulling its weight?") were left to guesswork.

At Loop Exit the loop now derives a per-run effectiveness trace, prints it to chat, and persists one
durable record to a dedicated **telemetry branch** (issue #441) so the data survives teardown, lands
in one place across every writable run (local and cloud), and is reviewable after the fact.

## The workpad roster field: `phase3_dispatched`

A `null` verdict — an agent that was dispatched but raised nothing — can only be detected if we
know which agents were *launched*. The findings array alone can't tell a silent agent from one
that was never dispatched (Phase 0.5 gates `pr-test-analyzer` and `type-design-analyzer` on
small/config-only diffs). So each `iter-<N>.json` workpad records a `phase3_dispatched` array: the
Phase-3 agent identifiers actually launched that iteration, captured **after** Phase 0.5 gating.

`null` is then derived as `phase3_dispatched − (agents present in phase3_findings)`. The field is
best-effort: an older or partially-written workpad without it degrades to classifying only the
agents that appear in `phase3_findings`, and the trace flags the gap for that iteration.

## The 4-way effectiveness taxonomy

Each dispatched subagent is assigned **exactly one** verdict per iteration, by these rules
(highest-precedence match wins, so the assignment is total and deterministic):

| Verdict | Meaning | Derivation |
|---|---|---|
| **unique-effective** | Raised a finding that led to an applied fix, and no sibling agent corroborated it. | ∃ finding with `fix_decision == "applied"` **and** `corroboration_count < 2`. |
| **corroborating** | Its finding led to an applied fix, but ≥1 other agent raised the same defect — added confidence, not coverage. | ∃ finding with `fix_decision == "applied"` (and not unique-effective, i.e. `corroboration_count ≥ 2`). |
| **noise** | Its only findings were pushed back as false-positive or web-refuted. | No applied finding; ∃ finding with `fix_decision ∈ {pushed_back, advisory}`. |
| **null** | Dispatched but raised nothing, or nothing that survived to an applied fix or a noise classification. | Everything else, including no findings at all. |

A finding whose only outcome is `deferred` (the defect is real but out-of-scope / already-tracked)
or `severity-calibrated` (the defect is real but was over-graded and calibrated down by the over-grade
calibration gate — not a false positive) is deliberately classified **null**, *not* noise — `noise` is
reserved for `pushed_back` / `advisory` (false-positive / web-refuted). The agent wasn't wrong, but it
added no fix to *this* run, so it does not count against it as noise. Any future `fix_decision` value
also defaults to `null` until `verdict_for` is taught about it.

`corroboration_count` is sourced from `phase3_findings`; a missing value is treated as `1`
(single-source / unique). The verdict reads `fix_decision` directly off each finding, so the
classification needs no join into `fix_decisions`.

### Decomposing the `null` residual (issue #1849)

`null` is a **derived residual**, so a bare `null` verdict still collapses three opposite states: an
agent genuinely **silent**, an agent whose real findings were all **deferred / severity-calibrated /
foreclosed**, and an agent that **failed** or returned an unusable result. Two additive per-agent
fields beside the verdict decompose it — they add no new verdict and change no derivation above:

| Field (per `agent_verdicts[]` entry) | Value set | Separates |
|---|---|---|
| `disposition` | `returned` \| `failed` \| `silent` \| `unestablished` | a failed return from silence; `returned` = the agent is in `phase3_findings`; `failed` = the agent is in the established failed set (the `phase3_failed_agents` sink, or a shadow `per_reviewer_assessment` entry with `returned: false`); `silent` = dispatched, absent from findings, and the failed set is established without it; `unestablished` = the split cannot be read (roster absent, or the failed set absent/malformed) — never mapped onto `silent` (unknown is not zero). |
| `fix_decisions` | sorted-unique set of the agent's `fix_decision` values (`[]` in review-mode) | an all-deferred/calibrated agent (verdict `null`, non-empty roll-up) from one that raised nothing (verdict `null`, empty roll-up). |

The residual is decomposed only over an **established roster** (`phase3_dispatched_present`): a
roster-absent iteration is reported as `unestablished` per non-returning agent rather than silently
shrinking the null denominator, and each `per_iteration[]` entry carries a `phase3_failed_agents_present`
flag so a historical record (which lacks the field) reads as disposition-unestablished, never silent.

**Denominator confound — read the per-agent rates with it.** A per-agent rate's denominator is *the
defects that existed to be found*, not the agent's quality. A `null` or low-yield rate on a
config-only or out-of-domain diff is correct silence (see the diff-profile confound below), so **raw
per-agent rates are not reviewer quality until that shipped-defect denominator is characterised** —
the prerequisite for any cross-run cut-candidate analysis.

## The diff profile and verification posture

A `null` verdict means different things on different diffs. On an app-code change with real bugs, a
silent `code-reviewer` may genuinely have under-earned its cost; on a config-only or
engine-self-modifying jq/docs change, the *same* silence is correct — that reviewer's domain simply
wasn't in the diff. Aggregating raw `null`-rate across diff shapes would systematically recommend
cutting the generalist agents, which is backwards. So each iteration carries a `diff_profile`: the
engine's Phase 0.5 classification (the four profile-shaping flags `small_diff`, `config_only`,
`has_new_types`, `engine_self_modifying`, plus the derived `checklist_skipped` member; Phase 0.5's fifth flag `detect_all_audit` is
not persisted — it only forces the completeness-critic pass and never shapes the profile). The cross-run analyzer **must segment by
`diff_profile`** before drawing any cut conclusion — a `null` on a diff outside the agent's domain is
not a cut signal.

The `engine_self_modifying` flag (Phase 0.5) is a checklist-only override — it forces the full
checklist but no Phase 3 agent. The four always-on agents are roster members on every profile, and
`type-design-analyzer` and `pr-test-analyzer` keep their structural-applicability gates on every
profile (`has_new_types` for the former, the test-relevance predicate for the latter). So on a docs-only / config-only engine PR
those two analyzers are correctly skipped rather than padding the dispatch roster with `null` /
`corroborating`-only runs — which is exactly what made the earlier engine-PR records overstate cost.

The same `diff_profile` drives a **verification posture** that keeps a healthy cost-saving choice
from looking like a gap. The orchestrator deliberately avoids dispatching verifier subagents when it
doesn't need them — resolving substring claims via the cheap orchestrator-direct `lite` probe, or
skipping Phase 1+2 entirely when Phase 0.5 classifies the diff as low-risk (`small_diff` +
`config_only`). That is good behavior, not absence of work, so the trace names it explicitly rather
than printing a bare "0 verifiers". **The "low-risk" characterization is scoped, not unconditional over the whole config-extension class:** a config-extension file that is part of the engine surface — a prompt extension under the `.prflow/`/`.devflow/` state directory ending in `.md`, or a file whose basename is `CLAUDE.md` — classifies `engine_self_modifying` (Phase 0.5) and therefore keeps the full checklist rather than taking this skip, precisely because a defect in the reviewer's own appended instructions is not low-risk. The skip below is the good-behavior posture only for a genuinely low-risk config-only diff that touches no such file:

| Posture | When | Trace line |
|---|---|---|
| `skipped-intentional` | Phase 0.5 bypassed Phase 1+2 (small_diff + config_only) | "Checklist: skipped by Phase 0.5 (…) — verifier subagents intentionally not dispatched for a low-risk diff." |
| `skipped-failure` | checklist generation failed | "Checklist: generation failed — proceeded with review agents only." |
| `lite-only` | items resolved via `lite` probes, zero agents dispatched | "Checklist verifiers: N lite (orchestrator-direct), 0 agent — … without dispatching verifier subagents (cost-saving, by design)." |
| `agent-only` / `mixed` | verifier subagents dispatched | "Checklist verifiers: N lite, M agent." |
| `none-recorded` | no skip reason and zero items recorded | "Checklist verifiers: none recorded for this iteration." (the one posture that flags a genuine instrumentation gap) |

`/prflow:review-and-fix` now writes the `checklist[]` array (with each item's `verification_mode`)
and the `telemetry` key to every `iter-<N>.json` workpad whenever Phase 1+2 ran. When no phase
figures were established, the writer emits the literal string `"unavailable"`; it never omits the
key or writes JSON null. The persistence backstop applies the same marker to absent/null keys on
new durable paths. As a result `none-recorded` is reachable **only** in genuinely degraded cases;
a `none-recorded` posture on a run
where Phase 1+2 ran is now a real regression worth investigating, not the expected steady state. The
fields remain best-effort and non-fatal: a single missing `<usage>` block is skipped per-source
without dropping the whole `telemetry` block. Legacy readers continue tolerating absent/null data.

## The rendered trace

`lib/efficiency-trace.sh --mode trace` renders Markdown printed to chat after the Run telemetry
table. Per iteration it shows the diff profile, the verification posture (above), the count of
Phase-3 agents dispatched, the fixes applied, and each agent's verdict. Any iteration that applied
**zero** fixes is flagged with a marginal-yield line ("added nothing"), making a wasted iteration
visible at a glance.

## The per-run record

`lib/efficiency-trace.sh --mode record` emits one JSON record object **to stdout**; `--persist` derives
that same object and stores it on the telemetry branch at `.prflow/logs/efficiency/<slug>-<run-id>.json`
— **one file per run** (not an appended JSONL), so parallel writers never touch the same file. The
filename is keyed by the run's `<run-id>` (the same
discriminator that scopes the workpad directory), **not** a fresh `date` timestamp: this is what lets
`--persist` be idempotent — it tests record presence **on the branch** (`git cat-file -e
refs/heads/<branch>:.prflow/logs/efficiency/<slug>-<run-id>.json` — the fully-qualified ref the
code actually probes, not a bare-name lookup) and never re-derives an existing record, so a
re-run is a clean no-op (no new branch commit, `generated_at` unchanged) and a run is never recorded
twice. **The one exception is the harness-cost floor's merge arm (Layer 4, issue #475):** on a
cooperative run it adds a single `harness_cost` key to this run's already-persisted record — one
extra branch commit that byte-preserves `generated_at` and every other field. A record that already
carries `harness_cost` is left untouched, so re-running the backstop is still a clean no-op ending at
the tree-equality guard, and every OTHER path stays strictly per-run-immutable. The record carries:

- `schema_version`, `slug`, `generated_at`, `iterations`, and `synthesized` — record-level `true`
  when **any** iteration was reconstructed by `--persist`'s synthesis floor rather than written by
  the loop (see *Non-droppable persistence* below); an agent-written run reads `false`.
- `cut_candidate_min_dispatch` — the config threshold (below), carried forward for the follow-up
  cross-run analyzer.
- `config_fingerprint` — the config-variant fingerprint (issue #431): an object
  `{sha256, partial, salient}` (or `null` when it could not be established), where `sha256` is over
  the canonicalized `prflow_review` + `prflow_review_and_fix` blocks, `partial` is `true` when only
  one of the two blocks exists (the hash covers what exists), and `salient` carries a few
  interrupted-time-series-relevant key values **verbatim** (`verdict_severity_threshold`,
  `fix_severity_threshold`, `max_iterations`). Computed by the wrapper via python3 (a hard preflight
  prerequisite — **no new command head**), it names the config variant that produced the run, which
  is what makes an experiment's interrupted-time-series comparison attributable.
  **`schema_version` decision (issue #431):** the field is additive and **optional** (nullable), and
  **no consumer gates on `schema_version`**, so the record stays at `schema_version: 1` — a bump would
  imply a breaking change this is not. Records predating the field remain valid; the experiment-record
  assembler (below) handles presence/absence uniformly, falling back to
  `git show <merge_sha>:.prflow/config.json` and marking the fingerprint source when the record
  carries none.
- `per_iteration[]` — dispatch counts, `diff_profile` (Phase 0.5 flags — segment cut decisions by
  this), `verification_posture`, checklist lite/agent split, fixes applied, the `added_nothing` flag,
  `phase3_dispatched_present` (so the analyzer can tell a genuinely zero-dispatch iteration from one
  degraded by an absent roster — both show count 0), the `agent_effort[]` per-agent effort
  observability blocks with their `dispatched_effort_present` flag (issue #609: agent id plus
  exactly `requested`, `resolved`, `application_point`, `effective` — null unless read back — and
  `fallback_reason`, populated over `phase3_dispatched` ∪ the iter workpad's `dispatched_effort`
  roster, so a Phase-1/1.5/2 checklist agent's effort decision is carried too; an agent with no
  entry records an all-null `session-inheritance` block; additive and nullable, `schema_version`
  stays 1), the `agent_verdicts` roster (each entry carrying the derived `verdict` plus the issue-#1849
per-agent `disposition` and `fix_decisions` roll-up that decompose the `null` residual — see *Decomposing
the `null` residual* above) and its `phase3_failed_agents_present` flag, `synthesized`
  (whether *this* iteration was reconstructed by the synthesis floor — a strict `== true` of the
  workpad field, so an absent field reads `false`), and `loop_role`
  (`fix` | `promoted`) — each iteration's role in the fix loop, **derived here** from the prior
  iteration's shadow block (iteration 1 → `fix`; iteration N → `promoted` when iteration N−1's
  `shadow.promoted_to_iter_next` is set, else `fix`), preserving any non-empty value the orchestrator
  already persisted into the iter workpad. This derivation is the field's real consumer: the
  per-iteration `loop_role` in `iter-<N>.json` is legibility the orchestrator writes best-effort, and
  the record surfaces it reliably whether or not that write happened.
- `telemetry[]` — the existing per-phase / per-iteration cost telemetry (calls / tokens /
  wall-clock) lifted out of each workpad, so cost data is no longer lost with `.prflow/tmp/`.
  Each entry's `phases` mirrors the workpad's `telemetry` block **verbatim** (unnormalized; `null`
  when the workpad recorded none) — it is a pass-through, not a versioned sub-schema.
- `harness_cost` — the **harness-side cost floor** (Layer 4, issue #475), added by `--persist`'s
  merge arm from `claude-code-action`'s `execution_file` when the cloud backstop supplies it. A
  distinct top-level object `{cost_source: "execution-file", engine_version, workflow, command,
  scope: "whole-job", cost_usd, tokens, model_usage, num_turns, duration_ms}`. It is **whole-JOB**
  cost, not per-phase: `scope`/`workflow` mark that so analyses segment by `workflow` and never
  compare it to per-phase `telemetry` figures as like-for-like. It is deliberately **invisible** to
  `_run_cost`/`_telemetry_complete` (neither reads `harness_cost` — `_run_cost` sums only
  `telemetry`, and `_telemetry_complete` reads only `telemetry` and `synthesized`), so per-phase
  aggregates are unchanged by its presence. Absent on records from a run whose execution file the floor never saw.

A run with zero readable iterations (catastrophic early failure) writes **no record at all** rather
than a contentless skeleton — symmetric with the flag-off contract.

**The durable store is a dedicated telemetry branch (issue #441).** Every writable run — local
and cloud, `/prflow:review-and-fix` **and** standalone `/prflow:review` — persists its record
and durable workpad copy to a single long-lived **orphan branch, `prflow-telemetry`** (name
configurable via `telemetry.branch`). The branch shares no history with `main` and is never
merged into it.

**Migrating a repository that already has a `devflow-telemetry` branch (issue #1003).** The
default branch name renamed `devflow-telemetry` -> `prflow-telemetry`. Records already published
on the superseded branch are **not** migrated automatically and **not** dual-read: the branch is
a single orphan ref whose whole content is JSON records, so one push renames it with every byte
preserved, and a silent dual-read would entrench the superseded name permanently — the ruling
issue #988 made for the config keys, applied here. Rename it once:

```bash
git push origin devflow-telemetry:prflow-telemetry
git push origin --delete devflow-telemetry
```

Records stranded on the superseded branch are **detected, never silent** — and since issue #1826
the detection fires **whether or not the canonical branch is present**, because the superseded
branch stores its records under the pre-rename path `.devflow/logs/efficiency/` (the canonical
`.prflow/logs/efficiency/` is empty on it), and `scripts/build-experiment-records.py` reads that
branch under the path it actually uses. The reader still ingests from **exactly one** branch and
mutates no ref — this is detection only; recovering the stranded records stays an operator action.
The remedy the warning names depends on the branch state, because the two are independent orphan
refs:

- **Canonical branch absent** (the unmigrated case) — the one-push rename above is a fast-forward
  with nothing to overwrite, so the warning names both refs and that command, rather than reading
  the absence as "no telemetry".
- **Canonical branch present** (this repository's actual state, where the two branches have
  diverged) — force-pushing the superseded ref onto the canonical one would **discard every
  canonical record**, so the warning explicitly says *do not* do that and instead names a
  copy-across remedy that mutates no ref: on a checkout of the canonical branch, copy the record
  files from `devflow-telemetry:.devflow/logs/efficiency/` into `.prflow/logs/efficiency/`, commit
  and push, then delete the superseded branch.

Setting `telemetry.branch` to
`devflow-telemetry` keeps the old name indefinitely and is equally supported. The persist step (`lib/efficiency-trace.sh --persist`) writes each run's
artifacts to that branch **through git plumbing** — hashing them into the object store,
assembling a tree against a temporary index, `git commit-tree`, and a compare-and-swap
`git update-ref` — **without checking the branch out and without materializing anything in the
tracked working tree.** After `--persist`, the current branch, its `HEAD`, the default branch,
and `git status` are byte-for-byte unchanged. It then pushes the branch (a fetch → re-parent →
push retry loop lives inside the helper), using the **same code path** in both environments:
cloud authenticates with the workflow token, local with the developer's own git credentials.

This replaces the former current-branch `chore:` commit, and with it three problems it caused:
durability no longer depends on whichever branch the run sat on ever being pushed and merged (a
local run's telemetry is retained on the local `prflow-telemetry` ref even offline, and pushed
when a remote is reachable); a local run on the default branch can no longer diverge local `main`
from `origin/main`; and telemetry from every writable run lands in **one** place. Persistence is
best-effort and exit-0: when the branch cannot be pushed (offline, no remote, a read-only fork-PR
token, a missing permission, or the read-only cloud `review` profile) the local ref still
advances, a `::warning::` is emitted, and the run is never aborted. Before appending to an
existing `prflow-telemetry` ref the write verifies it is a telemetry store (its tip tree holds
only `.prflow/logs/`-shaped paths) and breadcrumb-skips on mismatch — and the push-rejection
re-parent re-runs the same verification against the freshly-fetched **remote** tip before building
the union commit (the case where a consumer's same-named branch exists only on the remote and first
surfaces as the push rejection) — so it never commits onto a same-named branch a consumer uses for
something else, on either the local-append or the push-reconcile path. The ref advance is a compare-and-swap that
re-reads the tip and rebuilds on it when a sibling worktree/process advanced it first, so two
parallel local worktrees sharing `.git/refs` both survive with no lost commit. The read-only
cloud `review` profile (`devflow-runner.yml`, `contents: read`) **does** run `--persist` — the
base-branch `.claude/settings.json` Stop hook is restored into every `claude-code-action` job (this
rests on the same **unverified platform premise** the writable-tier workflow-env comments flag: that
`claude-code-action` fires the restored Stop hook and propagates the job env into its subprocess; on
this read-only tier the fail direction is safe either way — if the hook does not fire, nothing is
staged and nothing is lost) — but
in **staging-only** mode: the workflow does not set the push operand `DEVFLOW_TELEMETRY_PUSH`, so
under `GITHUB_ACTIONS` `--persist` fails closed (issue #469 AC5), staging the run's artifacts under
`.prflow/tmp/` and writing **no new** telemetry-branch records and doing **no** push. (The
best-effort fetch-before-exclusion step `do_persist` runs on *every* tier may fast-forward the
**local** `refs/heads/prflow-telemetry` ref to mirror already-published remote records — a read
that leaves the tracked tree, `HEAD`, the current branch, and the **remote** ref all byte-unchanged;
it appends no record and pushes nothing.) The read-only tier therefore leaves the remote
`prflow-telemetry` ref untouched by its own action. Landing those staged records on the branch is
the job of a separate **trusted telemetry-push relay**, which now ships (issue #489):
`.github/workflows/telemetry-push.yml` — a job that does **not** check out the PR head, mints a
write-capable App token above its checkout, downloads the review run's uploaded artifact, and
validates the staged artifacts as untrusted PR-influenced input (`scripts/validate-telemetry-artifact.sh`,
all-or-nothing) before pushing them through `lib/telemetry-branch.sh`. To make those records
reachable across the workflow boundary, the auto-review tier now **uploads** its staged tree as a
workflow artifact (`scripts/collect-staged-telemetry.sh`, with `include-hidden-files: true` since the
tree is under the dot-prefixed `.prflow/`); the relay is triggered off the auto-review workflow's
`workflow_run` completion and pushes the validated records. On the ephemeral cloud runner the staged
tree does **not** survive job teardown, so **the cloud-tier recovery path for a degraded persist is
that uploaded workflow artifact, not on-disk retention** — the runner filesystem is gone by the time
any later step could read it, so on-disk retention cannot help there. A degraded persist's on-disk
staging-root retention (below) helps a **local** run, where the filesystem persists.

**Headless persistence.** `/prflow:review-and-fix` invokes `config-get.sh` and
`efficiency-trace.sh` **directly** (resolving to a `.prflow/vendor/prflow/…` path), the same way
`/prflow:implement` invokes its helpers — never `bash <path>`. Resolved-path allow-list entries
match on the command's leading token after expansion, so a `bash`-prefixed command would start with
`bash`, match nothing, prompt, and be denied on a headless run (silently skipping the trace). Direct
invocation requires `lib/efficiency-trace.sh` to be committed with its executable bit, and **every**
workflow allow-list under which `/prflow:review-and-fix`'s Loop Exit runs to carry
`Bash(.prflow/vendor/prflow/lib/efficiency-trace.sh:*)`. Two workflows qualify, because the loop's
Loop Exit runs on both entry paths:

- `.github/workflows/devflow.yml` — the inline allow-list for the `/prflow:review-and-fix` comment
  path.
- `.github/workflows/devflow-implement.yml` — the heavy `/prflow:implement` path (partitioned out of
  `devflow.yml`, which carries the comment-trigger routing). `/prflow:implement` Phase 3.3 invokes
  the fix loop with the draft PR number as a bare leading numeric token followed by the flags —
  `/prflow:review-and-fix <pr-number> --push-each-iteration --issue <issue-number>` (the numeric token
  puts the loop in PR mode against the run's own PR; when Phase 3.1 printed no number the token is
  omitted and it falls back to current-branch mode) — which runs the full Loop Exit, so this workflow's
  allow-list needs the entry too — alongside the `config-get.sh` entry it already carries.

The slim `review` profile in `devflow-runner.yml` is read-only and never runs the Loop Exit, so it
needs no entry.

## Config keys

Both live under `prflow_review_and_fix` in `.prflow/config.json`
(schema in `config.schema.json`, example in `config.example.json`):

| Key | Type | Default | Effect |
|---|---|---|---|
| `efficiency_telemetry_enabled` | boolean | `true` | Master gate. When `false`, the loop renders no trace and persists no effectiveness record to the telemetry branch — **and no permission-denial forensics**, which ride the same per-run record as its `permission_denials` key (`apply_denial_floor` is gated on this flag exactly as record derivation is). Disabling this for cost gives up denial forensics too. |
| `efficiency_cut_candidate_min_dispatch` | integer | `3` | Minimum dispatch count before an all-null/noise agent is flagged as a cut candidate. Defined here so the config surface is stable; **consumed by the follow-up cross-run analyzer**, not by `/prflow:review-and-fix` itself (the record carries it forward). |

The telemetry-store branch is configured separately, at the top level of `.prflow/config.json`:

| Key | Type | Default | Effect |
|---|---|---|---|
| `telemetry.branch` | string | `prflow-telemetry` | Name of the long-lived orphan branch every writable run persists its observability artifacts to (issue #441). Auto-created on first use; verified to be a telemetry store (its tip tree holds only `.prflow/logs/`-shaped paths) before appending. Keep every workflow `push:` trigger branch-filtered so a push to it runs no CI — PRFlow's own workflows filter `push:` to `main`; a consumer whose `on: push` is unfiltered should add a `branches-ignore` entry for this branch. |

**Acting on the trace.** The telemetry above tells you *which* subagents earn their cost; the
per-subagent `prflow_review.agent_overrides` block is the lever to *act* on it — move a mechanical
pass to a cheaper model / lower effort, or pin a high-value reviewer to a stronger model / higher
effort. When the trace shows an agent earns its cost on the first pass but adds nothing unique on
later fix-loop iterations, its optional `iterations: "first-only"` key (default-off) drops it from
the Phase-3 roster on `/prflow:review-and-fix` iterations ≥ 2 — a positional cost lever, distinct
from the model/effort levers (see [review-agent-overrides.md](review-agent-overrides.md)). The
override keys are byte-identical to the subagent identifiers the engine dispatches
under: the six Phase-3 keys are the `phase3_dispatched` / finding `agent` identifiers used
throughout this doc, while the three checklist-phase keys (Phases 1/1.5/2) run earlier and so do not
appear in `phase3_dispatched`. Either way the trace and the override config stay aligned. See
[review-agent-overrides.md](review-agent-overrides.md).

> **Effort lever caveat (issue #554).** A per-agent **model** override reaches the subagent, but a
> per-agent **effort** override is **not** applied per-agent on the in-session Agent-tool dispatch
> path both tiers use today (the Agent tool has no effort parameter) — the subagent inherits the
> session effort, reported honestly as a `session-fallback`. Only the section-level session effort
> (`process-start-session`) is composed today. The per-tier application-point matrix is in
> [review-agent-overrides.md](review-agent-overrides.md); a per-agent effort observability field in
> this trace (and the applied arm that would populate it) is a spike-gated deferred follow-up.

## Non-fatal by design

Derivation and persistence are best-effort: a missing or unreadable workpad, an absent
`phase3_dispatched` field, or a write failure logs a warning and the fix loop continues to its
normal verdict. The trace is observability, never a gate — it must never abort the loop.

## Non-droppable persistence (the self-check + `--persist` backstop)

Best-effort persistence has a failure mode: when `/prflow:review-and-fix` is driven
**interactively/inline** by an orchestrator rather than as a discrete end-to-end invocation, the
agent can follow the engine's *substance* (review, shadow, fixes) but silently drop the Loop Exit
*bookkeeping* — the per-iteration workpad write, the record derivation, the durable copy, and the
telemetry-branch persist. Nothing distinguishes "correctly persisted nothing because telemetry was
off" from "silently forgot to persist," so the gap is invisible, and the lost *full* record is not
reconstructed by any shipped backstop. Token/wall-clock telemetry is captured live — whether the
harness's own output *could* reconstruct it has been **measured by the #437 probe** (result in
[`docs/internal/execution-file-shape.md`](execution-file-shape.md); see the cost-half note below). The Layer-3+
synthesis floor below recovers a minimal effectiveness skeleton from the fix
commits, never that detail. Layered
backstops close this, weakest to strongest — the deterministic backstop (Layer 3) and its synthesis
floor (Layer 3+) are the actual guarantee; the others shrink the blast radius and provide a portable
fallback.

**The telemetry splits into two halves with different recoverability, and the split drives the whole
design.** The **effectiveness** data — findings-per-agent, dispatch counts, verdicts, fix decisions —
is in the agent's context during *any* run, including a hand-run; it is lost only because the
`iter-<N>.json` write was optional, so it is made recoverable by turning that write into a
**non-optional obligation** (see Layer 1). The **token/wall-clock cost** half is captured *live* by
the running loop; when a loop is abandoned, the **cloud** tier's Layer-4 harness-side cost floor
(#475, below) reconstructs the cost from `claude-code-action`'s `execution_file`, but the **local**
tier ships no such backstop, so there the emit-obligation guarantees the effectiveness half but does
**not** promise the cost half — keep the loop running live to protect it. Whether an *agent-independent* floor **could** reconstruct the
cost half from the harness's own output — `claude-code-action`'s `execution_file` and the `Stop`-hook
transcript — was long asserted here as settled fact ("no backstop can reconstruct it"), but that
assertion was never measured. Issue #437 replaced the assertion with a re-runnable probe
([`.github/workflows/matcher-probe.yml`](../../.github/workflows/matcher-probe.yml)) whose **observed**
results are recorded in [`docs/internal/execution-file-shape.md`](execution-file-shape.md): read that shape
record — not this sentence — before deciding whether an agent-independent cost floor is buildable.

**The measurements refute the old claim. It was false.** Each tier refutes it — but they were
measured to *different depths*, and the difference matters (do not read the two rows below as
parity; the cloud row is a full field sweep, the local row is a token-realness check):

- **Cloud** (`execfile-shape-probe`, run `29201071531`, 2026-07-12): `claude-code-action`'s
  `execution_file` carries per-message token `usage` (`input_tokens` / `output_tokens` /
  `cache_read_input_tokens`), wall-clock (`duration_ms`, `duration_api_ms`, `ttft_ms`), `tool_use`
  events, `subagent_type` on `Task` dispatches, `permission_denials` — **and cost directly**
  (`costUSD`, `total_cost_usd`, per-model `modelUsage`).
- **Local** (`scripts/stop-hook-probe.sh`, 2026-07-12): the `Stop`-hook transcript carries **real**
  per-message token counts (196 `usage` blocks, largest figure 342,272) — not the streaming
  placeholders it was assumed to hold. **That is the whole local measurement**: token *realness*.
  Wall-clock and the subagent dispatch roster were **not** measured on this tier — they may well be
  derivable from the transcript, but nothing here establishes that, so do not cite the cloud row's
  field sweep as if it applied locally.

So *"no backstop **can** reconstruct the cost half"* is **not true**, and repeating it steered three
issues' worth of work (#170, #381, #426) into building ever-more-elaborate floors fed by operands the
agent had to volunteer, while the harness was emitting the same data, deterministically, the whole
time. The honest statement was the weaker one: **no backstop PRFlow *shipped* reconstructed it** — a
gap in what we built, not a law of the platform. An agent-independent (class-(c)) cost floor is
**buildable on both tiers**, and **#475 builds the cloud half** (the Layer-4 harness-side cost floor,
below): on the cloud tier `--persist` now reconstructs cost from the full observed field set above.
The **local** tier remains buildable-but-unbuilt — from the transcript's real token counts (wall-clock
and the dispatch roster were *not* measured there, so a local floor's phase attribution is an open
question, not an observed fact); see
[`docs/internal/execution-file-shape.md`](execution-file-shape.md) for the observed shape and the run URL, and
build against that record rather than this paragraph.

Two things remain genuinely open, and a floor must not assume them away: the `execution_file` schema
is **not a public contract** (the record is a dated observation of one action version — re-dispatch the
probe after any upgrade), and on the local tier **realness is not freshness** (the docs warn the
transcript is written asynchronously and may lag, so a `Stop`-time read may miss the final turn's
counts). Until a floor actually ships, keeping the loop running live is still what protects the cost
half — but that is now a statement about our backlog, not about what is possible.

**Layer 1 — wording (portable, agent-executed).** The SKILL.md Loop Exit persistence steps are
marked **mandatory on every writable run**, and a `## Common Mistakes` entry names the
interactive-drop failure mode so a future orchestrator does not silently skip them. The
per-iteration `iter-<N>.json` emit specifically is a **non-optional obligation on every iteration,
regardless of how the loop was executed** — whether `review-and-fix` ran as a `Skill` invocation or
was **hand-run via direct `Agent` dispatch** on a degraded path — and it is written **with the Write
tool, never a shell `>`/heredoc redirect** (which the cloud sandbox denies into `.prflow/tmp`). This
is what keeps the effectiveness half recoverable even when the instrumented loop is left; a cloud
`claude-code-action` permission/sandbox denial is never license to abandon the loop. (This asymmetry
is worth noting: the read-only `review` runner runs under `--permission-mode acceptEdits`, but the
`/prflow:implement` job deliberately does **not** — so the implement seam relies on single-statement
leading-token helper forms and the Write tool for scratch, not a broadened permission grant.)

**Layer 2 — self-check + incremental capture (portable, agent-executed).**
- *Incremental capture, fused to the fix commit.* Each `iter-<N>.json` is written **at Step 3
  item 6's fix-commit moment** — capture `fix_commit_sha`, then Write, as one step, so an
  inline-driven loop has no seam between "fix landed" and "record exists" (Step 3 item 7 is the
  authoritative specification of the record's shape and fields) — not batched at Loop Exit. A
  dropped Loop Exit therefore still leaves the workpads on disk for Layers 2/3 to derive from,
  shrinking the blast radius from "everything" to "just the final derive+commit."
- *Self-check.* `lib/efficiency-trace.sh --self-check --workpad-dir DIR --slug SLUG` is run at Loop
  Exit on a converged writable run. If the run wrote **zero** `iter-*.json` workpads, or persisted no
  effectiveness record for `<slug>-<run-id>` to the telemetry branch (`git cat-file -e
  refs/heads/<branch>:.prflow/logs/efficiency/<slug>-<run-id>.json`), it emits a loud
  `::warning::` naming exactly what was not persisted (and points at `--persist` as the recovery).
  It **additionally validates each `iter-<N>.json`'s field set**: for every iter workpad missing a
  field in the single-source `ITER_EXPECTED_FIELDS` set (the iter schema's top-level fields minus the
  conditional and non-telemetry ones — `shadow` and `reference_reads`, appended later by Step 2.6 and
  Step 3.5's fix-delta gate respectively and so legitimately absent, plus the promotion/parking and
  navigation-stamp fields; `LR_CONDITIONAL_FIELDS` in `lib/test/run.sh` is the single list that
  declares the full subtracted set and drives both the subtraction and its presence pins), it emits a `::warning::` naming
  the field and the iter file — turning a silently-dropped inline-persist field into a visible signal.
  A workpad carrying `synthesized: true` (written by the Layer-3+ synthesis floor, below) is a
  recognized degraded class validated against its **own** minimal set (`ITER_SYNTH_EXPECTED_FIELDS`
  — see that variable in `lib/efficiency-trace.sh` for the members) rather than the full set — so a
  truncated synthesized record still warns instead of validating silently. That minimal set includes
  the run-scoped evidence fields, which is what makes `--self-check` **enforce** that a
  synthesized record actually carries its unrecoverable-provenance stamps. And the zero-workpad
  warning names the **targeted** recovery command (`--persist --workpad-dir DIR --slug SLUG` — the
  form immune to discovery-mode synthesis skips) rather than implying there is nothing left to
  persist.
  It **warns, never blocks** — it never writes, never commits, never changes the verdict, and always
  exits 0 (a malformed/unparseable/unreadable iter file is skipped rather than aborting the pass; that
  case is breadcrumbed by the `--persist`/`--mode` parse paths). It is **silent** when telemetry is
  disabled (no record is expected) and on a read-only run (the cloud `review` profile, where SKILL.md
  never invokes it — there is no Loop Exit there).

**Layer 3 — deterministic backstop (harness-executed, the actual guarantee).**
- *`lib/efficiency-trace.sh --persist`.* Derives the effectiveness record **and** stages the durable
  workpad copy from whatever `iter-*.json` workpads exist on disk into `.prflow/tmp/` scratch, then
  writes both to the **telemetry branch** via git plumbing (object-store hash → tree → `commit-tree`
  → compare-and-swap `update-ref` → fetch/re-parent/push retry) — nothing is materialized in the
  tracked working tree. With `--workpad-dir`/`--slug` it persists one run; without them it
  **discovers** every `.prflow/tmp/review/<slug>/<run-id>/` run dir and persists each — a dir holding
  `iter-*.json` directly, a workpad-less dir via the Layer-3+ synthesis floor below. As of issue #441
  standalone `/prflow:review` runs (`source == "review"`) are **no longer skipped** — they persist
  through this same path to the same branch (their Phase 4.5 step invokes `--persist` too), unifying
  every writable run into one store. It is **idempotent**: the record filename is run-id-keyed and its
  presence is tested **on the branch** (an existing record is never re-derived, so its `generated_at`
  can't churn), the durable copy is content-identical bytes, and the branch write skips the commit
  when the resulting tree is unchanged — so a re-run produces no new branch commit and never an empty
  one. Best-effort: every failure logs a `::warning::` and it always exits 0. The durable copy runs on
  every writable run (not telemetry-gated); the record is telemetry-gated.
- *`Stop` hook (local-tier only).* The project's `.claude/settings.json` registers a `Stop` hook
  that runs `--persist` after the agent's turn ends — when the run is already complete, so persisting
  there is **non-blocking by construction**. `--persist`'s discovery + presence-based idempotency *is*
  the "review-and-fix activity detected but no committed record exists" gate: it is a clean no-op when
  there is nothing unpersisted. It is best-effort (`|| true`); a failure never fails the session. The
  hook config (for this repo). Besides the `--persist` step, the `Stop` array carries the
  local-tier terminal-status guard (`lib/implement-stop-guard.sh`, the backstop documented in
  [`implement-skill.md`](implement-skill.md)) and the `Stop`-hook transcript probe
  (`scripts/stop-hook-probe.sh`). Every entry resolves its target through the same git-root
  anchor — `bash "$(git rev-parse --show-toplevel 2>/dev/null || printf '%s' "${CLAUDE_PROJECT_DIR:-.}")/…"` —
  so each launches correctly from any nested directory or linked worktree (a bare
  `bash lib/…` cwd-relative launcher would fail from a subdirectory). The entries are
  independent: only the `--persist` entry takes `|| true`; the guard deliberately does **not**,
  because its blocking exit code 2 must reach the harness; and the probe's `|| echo …` tail only
  surfaces a launch/path fault as a stderr diagnostic (the probe itself promises exit 0). This
  example is pinned equal to the tracked `.claude/settings.json` Stop entries by
  `lib/test/run.sh`, so it stays in lockstep with the real wiring:

  ```json
  {
    "hooks": {
      "Stop": [
        {
          "matcher": "",
          "hooks": [
            {
              "type": "command",
              "command": "bash \"$(git rev-parse --show-toplevel 2>/dev/null || printf '%s' \"${CLAUDE_PROJECT_DIR:-.}\")/lib/efficiency-trace.sh\" --persist || true"
            },
            {
              "type": "command",
              "command": "bash \"$(git rev-parse --show-toplevel 2>/dev/null || printf '%s' \"${CLAUDE_PROJECT_DIR:-.}\")/lib/implement-stop-guard.sh\"",
              "timeout": 15
            },
            {
              "type": "command",
              "command": "bash \"$(git rev-parse --show-toplevel 2>/dev/null || printf '%s' \"${CLAUDE_PROJECT_DIR:-.}\")/scripts/stop-hook-probe.sh\" || echo \"devflow stop-hook-probe: exited rc=$? (the script promises exit 0, so this is a launch/path or hard-crash problem; CLAUDE_PROJECT_DIR='${CLAUDE_PROJECT_DIR:-}')\" >&2",
              "timeout": 15
            }
          ]
        }
      ]
    }
  }
  ```

  **Adopter note.** The guard (`lib/implement-stop-guard.sh`) and probe
  (`scripts/stop-hook-probe.sh`) entries are **this-repo-local** — they ship to no consumer, so an
  adopter does not wire them. What an adopter adapts is only the `efficiency-trace.sh` entry,
  pointing it at the vendored copy `.prflow/vendor/prflow/lib/efficiency-trace.sh` (keeping the
  same git-root anchor form).

  > **Note on this repo's `.claude/settings.json`.** Writing `.claude/` is a privileged,
  > self-modifying action. The boundary an agent cannot cross is widening its own
  > `permissions.allow` allowlist — that is what stops an agent granting itself new
  > capabilities. The **hook wiring** in this same file is not covered by that boundary:
  > editing the `hooks` block is an ordinary file write, so a `/prflow:implement` run may
  > add or change a hook entry (and the classifier may still deny it, in which case the run
  > routes the change to a human rather than skipping it silently). It ships committed in
  > this repo (`.claude/settings.json`); the `--persist` mode it calls and the cloud-tier
  > guarantee land in the same wiring.
- *Cloud-tier wrapper.* **`Stop` hooks are local-only**: `claude-code-action` `rm -rf`s and restores
  `.claude/` from the **base** branch before installing plugins, so a PR branch's `.claude/` hook is
  discarded for that PR's own cloud run, and the cloud guarantee must **never** depend on the hook.
  Instead the cloud writable workflows — **`.github/workflows/devflow.yml`** (the
  `/prflow:review-and-fix` comment path's `command` job) and **`.github/workflows/devflow-implement.yml`**
  (the `/prflow:implement` path) — invoke `--persist`
  unconditionally (`if: always()`, best-effort) in a workflow step **after** `Run Claude Code`. As of
  issue #441 the helper owns the entire write: it commits to the telemetry branch via git plumbing
  and pushes it with a fetch/re-parent retry loop, so the former before/after-`HEAD` gate and bare
  `git push` are gone — the step is just `bash "$HELPER" --persist`. (`devflow-runner.yml` is the
  read-only `review` profile — it runs no fix loop and cannot write, so it is intentionally
  **excluded**: there is nothing to persist there.) Because a GitHub App token cannot self-modify
  `.github/workflows/`, a maintainer committed this step after `Run Claude Code` in each of those two
  workflows; it now ships committed in both:

  ```yaml
  - name: Persist review-and-fix observability artifacts (backstop)
    if: ${{ always() }}
    run: |
      set +e
      HELPER=.prflow/vendor/prflow/lib/efficiency-trace.sh
      [ -f "$HELPER" ] || { echo "::warning::observability backstop: $HELPER missing; skipped"; exit 0; }
      # --persist writes to the telemetry branch and pushes it, all inside the helper
      # (it sets its own committer identity). No HEAD gate, no bare git push here.
      bash "$HELPER" --persist
      exit 0
  ```

  **Issue #475 extends this step (both workflows) with the harness-cost floor glue** (the actual
  workflow YAML is the source of truth — this doc snippet is the pre-#475 core it builds on): the
  step now sets `EXECUTION_FILE` / `DEVFLOW_COMMAND` / `DEVFLOW_CANDIDATE_NUMBER` / `GH_TOKEN` in its
  `env:`, runs `scripts/prepare-harness-floor.sh` (guarded by the same `[ -f ]` pattern as `$HELPER`,
  with a named `::warning::` when a vendored tree pinned to an older `prflow_version` lacks it), and
  passes the resulting `DEVFLOW_EXECUTION_COST` / `DEVFLOW_EXECUTION_PR` / `DEVFLOW_COMMAND_CLASS` on
  the `bash "$HELPER" --persist` line. See **Layer 4** above.

- *`/prflow:implement` Phase 3.3 inline backstop (agent-executed).* `/prflow:implement` drives
  `/prflow:review-and-fix` **inline in the orchestrator's own context** (Phase 3.3), so its Loop Exit
  runs in-context and can be dropped exactly like any other interactive/inline drive. To close that
  seam without waiting for a harness-tier caller, `phase-3-fix-loop.md` runs `--persist` directly
  (resolved via the portable skill-dir anchor as `…/../../lib/efficiency-trace.sh`, best-effort `|| true`) the moment
  the inline loop returns — regardless of verdict, before the verdict branches. It runs `--persist`
  **twice, targeted first**: this orchestrator drove the loop inline and *does* hold its
  `<slug>`/`<run-id>`, and persisting its own run by explicit `--workpad-dir`/`--slug` identity is
  immune to every discovery-mode synthesis skip (multi-slug ambiguity, not-latest ordering) **and**
  to the lone-stale-foreign-dir shape, where discovery would misattribute this branch's fix commits
  to a leftover slug and the sha exclusion would lock the misattribution in. An argument-less
  discovery call then covers every *other* leftover run dir on disk; both calls' stderr land in one
  capture. When the slug/run-id are genuinely not held (the inline loop died before `RUN_ID` was
  computed), the targeted call is skipped with a workpad note recording that, and discovery plus the
  detector below remain the loud floor — never guessed values. The "no inputs" detector is **this-run-scoped**, not a
  whole-tree presence check: before driving the loop, Phase 3.3 snapshots the `iter-*.json`
  already on disk, then after `--persist` returns it diffs (`comm -13`) the current tree against
  that snapshot — only files that are genuinely NEW this run count. This is deliberate: a
  whole-tree presence check would let a leftover `iter-*.json` from an earlier local run mask a
  real loss on this run. Because the Layer-3+ synthesis floor writes its reconstructed
  `iter-*.json` under the same `.prflow/tmp/review/` tree, the detector counts synthesized files
  as recovered inputs — a zero-workpad run that synthesis recovered does **not** fire the gap
  reflection. Only when the diff is empty — the inline loop wrote no per-iteration workpad **and**
  synthesis also recovered nothing (no unrecorded fix commit, a failed search, failed writes, or a
  discovery-mode skip; `--persist`'s own warnings name which when a candidate dir was visited at
  all) — is the telemetry genuinely lost, and Phase 3.3 records a `dropped-failed` reflection
  naming the gap rather than letting it vanish. The phase anchors both
  the snapshot and the detector on the git top-level the **same** way `efficiency-trace.sh` does, so
  it scans the exact `.prflow/tmp/review/` tree `--persist` scans and never fires a false "telemetry
  lost" reflection from a cwd-relative divergence (if the pre-loop snapshot is itself missing, the
  detector degrades to whole-tree presence and emits a distinct `::warning::` naming that degrade,
  since it can then mask a real loss behind a leftover file). The detector counts every NEW
  `iter-*.json` unconditionally — there is no longer a `source == "review"` skip for it to be
  "regardless of" (issue #441 removed it, unifying standalone `/prflow:review` onto this same
  `--persist` path) — and in any case, at this inline seam the review-and-fix loop just driven is
  what writes the tree, so a foreign review-sourced dir being the sole new occupant is not a
  reachable in-flow shape. The no-new-inputs case above only catches a dropped *Loop Exit*
  (the loop wrote nothing at all); it does not by itself catch the sibling failure mode where the
  loop *did* write `iter-*.json` but `--persist`'s own record derivation/write step then failed —
  its jq-derivation and mkdir failure paths both leave a `record not written` breadcrumb on stderr,
  and its disk/permission write-after-mkdir failure path (ENOSPC/EROFS/quota/perms) leaves a
  differently-worded `...failed (disk/permission); not persisted for...` breadcrumb — all while
  still exiting 0 by design. Phase 3.3 captures the `--persist` invocation's stderr and greps it for
  both breadcrumb shapes (a single-literal grep here would silently miss the disk/permission path),
  recording a second, independent `dropped-failed` reflection when either fires, so a record
  derivation/write failure is surfaced even when inputs existed — this is deliberately narrower than
  every conceivable `--persist` failure surface. **The uncovered surface is the telemetry-branch
  write/push itself** (`::warning::telemetry-branch: …` — a non-conforming store, a lost CAS, an
  unwritable `.prflow/tmp`), which the detector's two literals do not match. Note what that costs:
  post-#441 the record is staged under gitignored `.prflow/tmp/`, and post-#469 a **degraded**
  branch write (or a CI staging-only run) **retains** that staging root instead of deleting it — only
  a *clean* write (pushed / idempotent no-op / nothing staged, `persist_tree` rc 0) deletes the
  scratch, so `git status` stays byte-unchanged on the success path. A degraded write emits one
  `::warning::` naming the staging root's **absolute path** so the run's only copy is recoverable, and
  a bounded newest-N prune (`_DEVFLOW_TELEMETRY_STAGE_KEEP`, default 8) at the start of the next
  `--persist` keeps retained roots from accumulating. On a **local** filesystem this makes a failed
  branch write recoverable; on an **ephemeral CI runner** the filesystem does not survive teardown, so
  on-disk retention is moot there — the trusted telemetry-push relay (`telemetry-push.yml`, issue
  #489) is the cloud recovery path, consuming the **uploaded workflow artifact** the auto-review tier
  stages and uploads rather than any on-disk copy the ephemeral runner cannot retain. This uncovered surface is still surfaced only by the helper's own stderr
  breadcrumb, which Phase 3.3 captures but does not currently grep for. And because the `APPROVE WITH UNRESOLVED
  SHADOW FINDINGS` path can drive a **second**, separate inline `review-and-fix` invocation (the
  bounded re-review), Phase 3.3 re-runs the whole snapshot-then-backstop procedure — a fresh
  this-run baseline before, the persistence check after — around that second invocation too, so it
  is not left unguarded at the same seam the first invocation's backstop protects.

**Layer 3+ — synthesis floor (part of `--persist`): reconstruct a fully-dropped run from its fix
commits.** When `--persist` finds a run dir with **zero** `iter-*.json` (targeted or discovered), it
no longer stops at "nothing to derive": it reconstructs **minimal** iteration records from the
branch's fix commits, so even a run whose every workpad emit was dropped still contributes an
effectiveness floor. The floor is exactly that — a floor, **never license to skip the item-6 emit**:
it recovers only the skeleton below and none of the checklist / findings / per-phase cost detail the
real record carries, none of which is recoverable **from the fix commits**.

- *Commit-subject selector (coupled two-site invariant).* Commits are selected by the subject
  template `fix: address review findings (iteration {N})` — **written** by
  `skills/review-and-fix/references/fixing.md` Step 3 item 6 (the fixing reference the root
  routes to; issue #530) and **parsed** by `lib/efficiency-trace.sh`
  (`FIX_COMMIT_SUBJECT_PREFIX`). `lib/test/run.sh` pins both sites; rewording the subject means
  editing both in the same commit. The commit range is `<base>..HEAD`, where the base ref prefers
  `origin/<base>` over the local base branch (routinely stale in worktrees — a stale local base
  would widen the range to sweep already-merged history and misattribute an old PR's fix commits);
  `<base>` is config `.base_branch`, default `main`, and an unresolvable base fails closed with a
  breadcrumb naming the tried value. **`--persist` refreshes the base ref before synthesis selects
  any commit (issue #532):** when an `origin` remote is configured, it fetches `origin/<base>` into
  `refs/remotes/origin/<base>` (the remote-tracking **cache** only — it advances no local branch
  ref at all; this is separate from the telemetry-branch handling, whose *fetch refspec* likewise
  targets `refs/remotes/origin/<telemetry-branch>` but which then additionally fast-forwards its own
  local ref `refs/heads/<telemetry-branch>` — the base-ref refresh has no such local-ref step).
  The base branch name has a **single producer** in
  `lib/efficiency-trace.sh` — `do_persist` resolves `.base_branch` once and both the refresh and
  `synth_base_ref` consume that one resolution. This closes the misattribution window: before the
  refresh, a stale `origin/<base>` (shared across linked worktrees, which nobody pulls) widened
  `origin/<base>..HEAD` back into already-merged foreign history, so another PR's fix commits were
  booked against this run. **Cutoff:** because this fix is forward-only and the record's field set is
  unchanged, synthesized records predating this change's merge (landed in **PR #581** — the PR
  that shipped this base-ref refresh) are **untrusted** and are **not distinguishable by record shape**
  from records the fix produces; a consumer must treat every synthesized record older than that PR's
  merge as suspect (the existing corrupted records are left in place, fix-forward only). Adversarial
  subject shapes are each breadcrumbed and skipped,
  always exit 0: a fix-loop-family subject without the `(iteration N)` suffix, trailing text after
  the suffix or a missing `)`, and a non-numeric iteration token; a leading-zero token is normalized
  (`01` and `1` are the same iteration), and a duplicate N keeps the **earliest** commit
  (`git log --reverse`).
- *Synthesized-record shape.* Each synthesized `iter-<N>.json` carries exactly `iter`,
  `fix_commit_sha`, `fix_files` (from `git diff-tree`; **`null` when that derivation fails** —
  unestablished, deliberately distinct from a genuine empty commit's `[]`), `loop_role: "fix"`,
  `synthesized: true`, and the run-scoped evidence fields `sweep_defs_read`, `sweep_evidence`,
  and `reference_reads`. A fix commit carries no trace of which sweep definitions an iteration read,
  what its sweeps found, or whether the fix-delta gate ran, so each of those three is stamped with an
  explicit `{"status": "unrecoverable", "reason": …}` object rather than a real-looking value. This is
  deliberate and load-bearing: `sweep_defs_read: []` and `sweep_evidence: {"status": "not-run", …}`
  are the *legitimate* values of a real no-fix iteration, so emitting either here would assert
  something about an iteration this floor never observed. `reference_reads` is a registry, so its
  stamp is written **inside** its `fix_delta` member — a top-level stamp would make the documented
  `.reference_reads.fix_delta` read return `null`, which is indistinguishable from the legitimate
  "the gate did not run" absence.

  **Consumer contract.** Read `status: "unrecoverable"` as *unknown*, never as *empty*, and
  **type-check before any shape-specific operation**: on a synthesized record `sweep_defs_read` is an
  *object*, whereas on a real record it is an *array*, so an unguarded `.sweep_defs_read | length`
  returns the provenance object's key count (2) and reads as "two sweep definitions were read" — an
  unestablished measurement collapsed onto a real positive value. Branch on `.status` first.

  **Compatibility boundary.** `ITER_SYNTH_EXPECTED_FIELDS` gained these three members in the issue
  #541 change, so a synthesized record written by an *earlier* build lacks them and `--self-check`
  now emits a missing-field `::warning::` for each. That is the intended fail-loud behavior (a
  truncated synthesized record must still warn) rather than a regression; the blast radius is narrow
  because `--workpad-dir` is a per-run ephemeral directory, so a pre-change record only appears when
  a run directory survives a tool upgrade. The same boundary applies to **ordinary** (non-synthesized)
  records: `ITER_EXPECTED_FIELDS` gained `sweep_defs_read` and `sweep_evidence` in the same change, so
  a pre-change agent-written workpad warns for those two on the identical rationale — this is not a
  synthesized-record-only boundary. `lib/efficiency-trace.jq` surfaces the marker at every level: per-iteration
  and in each `per_iteration[]` entry as a strict `== true` (an absent or malformed field reads
  `false`; and since issue #534 a persisted agent-written record affirmatively **carries**
  `synthesized: false` — the emitted-provenance backfill below stamps it on the durable copy — so
  the emitted-vs-synthesized distinction is a deterministic JSON boolean rather than a field-absence
  inference),
  and record-level as `any(…)` — `true` when **any** iteration was reconstructed, the key a
  cross-run analyzer uses to weight a reconstructed record differently from an agent-written one. A
  synthesized-only run renders normally in both `--mode trace` and `--mode record`, with
  `verification_posture: "none-recorded"` (no checklist was ever captured — correctly flagged as
  the instrumentation gap it is).
- *Emitted-provenance backfill (issue #534).* After the durable workpad copy (and after any
  synthesis above), `--persist` runs `stamp_emitted_provenance` over the **durable** copy of every
  `iter-*.json`: any valid-object record that lacks a `synthesized` key is stamped
  `synthesized: false`, so a persisted agent-written record records its provenance affirmatively
  rather than by field-absence. This moves the emitted-record provenance stamp **off the agent's
  decision path** — the fix loop's per-iteration emit is agent-authored prose that carries no stamp,
  and this deterministic backfill guarantees the persisted artifact a later reader consults still
  distinguishes an emitted record (`.synthesized == false`) from a synthesized one
  (`.synthesized == true`), with a lost emit surfacing as the absent record. It changes **no**
  synthesized record (they already carry `synthesized: true`, so the issue-#381 synthesis contract
  and `--self-check`'s synthesized-class validation are unaffected), operates on the staged durable
  copy only (the source run dir stays byte-identical), is idempotent (a key-present record is left
  untouched, so a second `--persist` is a no-op), and is best-effort per file (a malformed/non-object
  record or a failed write breadcrumbs and is left untouched, never aborting `--persist`).
- *Double-count defenses.* Three guards keep a fix commit from being counted into two runs'
  records or misattributed across runs: (a) **sha-level exclusion** — any commit already recorded
  as a `fix_commit_sha` by another run's `iter-*.json`, in the live tmp tree **or** the committed
  durable copies under `.prflow/logs/review/`, is skipped; the exclusion is checked **before**
  duplicate-N dedupe so an excluded commit never consumes its iteration number and shadows this
  run's own commit; (b) among one slug's workpad-less dirs, only the **lexicographically-latest**
  run-id synthesizes — earlier ones breadcrumb and decline; (c) workpad-less dirs spanning
  **multiple slugs** in one discovery pass are **all declined** — slug ownership of the branch's
  commits is not derivable offline, so the ambiguity fails closed for every candidate, each
  breadcrumb naming the targeted `--workpad-dir` escape hatch. Documented residual windows: a run
  whose every workpad copy (tmp *and* durable) was deleted after its record was derived; a **lone**
  stale foreign slug's workpad-less dir when the current run left no tmp dir at all (a single
  candidate is offline-indistinguishable from the legitimate run — the phase-3.3 targeted-first
  call is the mitigation); within one slug, a stale earlier run-id that is the only candidate
  receives the record (right slug, wrong run-id; the sha exclusion still prevents any
  double-count); and a workpad-less dir left by a standalone `/prflow:review` run synthesizes
  under the default `source: "review-and-fix"` (a synthesized workpad carries no `source` field).
  Two further residual windows come from the base-ref refresh (issue #532): (d) the **no-`origin`
  stale-local-base window** — a repo with no `origin` remote has no refresh mechanism, so synthesis
  proceeds against the **local** base branch (`refs/heads/<base>`), which is itself shared across
  linked worktrees and can be stale; the floor is kept (so offline and fixture runs keep working)
  and the residual is recorded here rather than silently closed; (e) the **transient-failure
  window** — when `origin` is configured but the refresh fails for any reason (an offline session, a
  VPN reconnect, an expired credential, or a run losing the `refs/remotes/origin/<base>.lock` race
  to a sibling worktree's concurrent `--persist`), that run **declines synthesis** rather than
  trusting a possibly-stale remote-tracking ref; a transient failure's next `--persist` (from the
  Stop hook) re-attempts seconds later, while a persistently-offline session forfeits the floor for
  that session.
- *Honesty ladder (unknown is never collapsed onto "found none").* `synthesize_iter_workpads`
  returns **0** (wrote ≥1 record), **2** (the selection ran and found no unrecorded matching
  commit), **3** (the search **could not run** — an uncreatable target dir, an unresolvable base
  ref, a base ref left **unestablished** by a failed pre-synthesis `origin/<base>` refresh (issue
  #532), a telemetry-branch fetch left **unestablished** by a failed/unattempted pre-synthesis fetch
  (issue #916) — since `recorded_fix_shas` reads the local telemetry ref to build the fix-commit
  exclusion set, a non-`ok` `_DEVFLOW_TELEMETRY_FETCH_STATUS` means that set may be incomplete and
  synthesis could re-attribute an already-recorded commit, so it declines rather than double-book;
  mirrors the #532 base-ref guard — or a failed `git log` enumeration, each with its own producer
  breadcrumb naming the tried value), or **4** (commits *were* selected but every record write failed, with per-commit
  warnings). `persist_one` dispatches each arm to a distinct `::warning::`, plus an unknown-rc arm
  so a future rc drift is never reported as "no commits were found."
- *Unsubstituted-placeholder guards.* A `<placeholder>` identity is refused loudly (best-effort
  exit 0 preserved) on **both** routes it can arrive by: the **argv** route (`--workpad-dir` /
  `--slug` containing `<` or `>` — a verbatim-run backstop fence) and the **basename-derived**
  route (a literal `<slug>/<run-id>` *directory* reaching discovery mode is refused by
  `persist_one`'s twin guard). Without these, a non-substituting run would fabricate a placeholder
  identity, synthesize the branch's real fix commits under it, and the sha exclusion would then
  lock the misattribution in — a placeholder identity is never fabricated.
- *Telemetry gating.* `efficiency_telemetry_enabled: false` skips synthesis entirely — a
  synthesized workpad exists **only** to feed the (disabled) effectiveness record, so fabricating
  one would commit telemetry artifacts to a repo that switched telemetry off. The durable copy of
  **real** workpads stays ungated, as before.

This guarantees **persistence of whatever telemetry was captured**. It does **not** guarantee
*capture* of `tokens` / `wall_clock_s` — those come from `<usage>` blocks the agent reads live and no
post-hoc tool can recover them if the agent never recorded them (the incremental writes + the
self-check warning maximize capture, but it remains irreducibly agent-dependent).

### Shadow synthesis floor (issue #426)

`--persist` carries a second, narrower synthesis floor for the **shadow** block, sibling to the
iter floor above. The shadow pass (`/prflow:review-and-fix` Step 2.6) appends a `shadow` block to
the triggering iter's workpad, but that block can drop entirely (the issue-304 drop shape), leaving
a promotion with no record of whether a predecessor shadow ran. A promoted successor now carries
`promotion_provenance`, which separates shadow precedence from the broader `loop_role`:

- `shadow` recovers a dropped block with `promoted_to_iter_next: true`;
- `park-calibration-post-shadow` recovers one with `promoted_to_iter_next: false`;
- `park-calibration-pre-shadow` writes nothing because no predecessor shadow ran;
- any other non-empty string writes nothing and warns; absent, null, empty, or non-string values
  recover the legacy floor with `provenance_unestablished: true` and hedged warning text.

Park-gate promotion credit lives only in provenance and never changes a surviving predecessor
shadow block. Future promotion producers must choose a defined value to opt into drop recovery; an
unknown string defaults to no synthesis, with a breadcrumb.

- *Synthesized shadow-marker shape.* Established `shadow` and post-shadow markers contain exactly
  `shadow_synthesized` and `promoted_to_iter_next`; the post-shadow value is false. The hedged legacy
  arm adds only `provenance_unestablished: true`. `--self-check` validates a
  `shadow_synthesized: true` block against this minimal set (`SHADOW_SYNTH_EXPECTED_FIELDS`) as a
  recognized degraded class — a truncated synthesized marker still warns, exactly like a truncated
  synthesized iter record; a real (agent-written) shadow block carries no `shadow_synthesized` key
  and is never validated by this branch (it stays unvalidated, as before).
- *Never overwrites an agent-written block.* The floor writes only when `.shadow` is `null` — the key
  missing, or present with an explicit JSON `null` (both are "no block"); an
  existing block — agent-written or already synthesized — is left untouched. It is telemetry-gated
  (a disabled repo gets none) and runs before the durable copy, so a synthesized marker is committed
  alongside the workpads it annotates. Best-effort: any failure warns and continues, never aborting
  `--persist`.
- *Every failure arm names its own cause.* The marker is merged in via a temp file plus `mv`, and
  both write arms surface the underlying tool's error text — the failing `jq`'s message, and `mv`'s
  own errno (read-only mount, `ENOSPC`) — rather than discarding it, so a floor that could not write
  is diagnosable rather than merely reported. On either failure the source `iter-<N>.json` is left
  untouched and the temp file is removed: no half-written marker, no orphaned `.shadowtmp`.
- *Stated limitation — provenance-licensed shadows only.* A clean outcome-1 shadow whose block dropped leaves no promotion
  evidence to synthesize from, so it is unrecoverable here — the fused Step 2.6 emit (mandatory on
  both termination paths, authored with the Write tool) is the primary fix and this floor is its
  backstop, not its equal. Like the iter floor, it recovers **attribution, not cost**: the
  `step_2_6` token/wall figures are captured live and no shipped backstop reconstructs them after the
  fact. Whether the harness's own `execution_file`/transcript could supply an agent-independent cost
  floor is no longer asserted here as settled — it was **measured by the #437 probe**, with the
  observed result recorded in [`docs/internal/execution-file-shape.md`](execution-file-shape.md).
  Older records without the marker remain valid.

**Layer 4 — harness-side cost floor (issue #475): the FIRST floor NOT fed by an agent-volunteered
operand.** Every layer above reconstructs a record from artifacts the agent authored (workpads, fix
commits). This floor's operand is `claude-code-action`'s `execution_file` — written **harness-side**,
independent of anything the agent volunteers — so a cloud run that dropped every telemetry emit still
contributes a **cost** record. That closes the specific gap the layers above leave open: they recover
*structure* but never the *cost* half, because that half was only ever in the agent's live context.
The #437 probe ([`docs/internal/execution-file-shape.md`](execution-file-shape.md)) established the execution
file carries cost directly (`costUSD`/`total_cost_usd`, per-model `modelUsage`, per-message `usage`),
so the floor is buildable on the cloud tier without the agent's cooperation.

- *Reader (`scripts/extract-execution-cost.py`).* A stdlib-only, slurp-tolerant (object / array /
  JSONL) normalizer that prints `{cost_usd, tokens{…}, model_usage, num_turns, duration_ms}`, with
  every absent figure `null` (never `0` — unknown-is-not-zero). Best-effort exit-0 over the full
  adversarial input matrix. It is **never** exec'd from `lib/efficiency-trace.sh` — that would add a
  `python3` exec edge to a Stop-hook trusted-closure entry (the #458 constraint) — so the glue helper
  runs it and passes the normalized JSON in via the environment.
- *Glue (`scripts/prepare-harness-floor.sh`).* The backstop-step branch selector (extracted per the
  `describe-denial-count.sh` inline-shell convention, so every branch is suite-drivable): it runs the
  reader, resolves/verifies the run's PR via `gh` (`lib/resolve-gh.sh`), and emits the floor env
  values. Each non-happy branch (execution file absent, not-a-PR, lookup failed, `pr-description`
  class) leaves a specific `::warning::` so a skipped skeleton/inert floor is auditable in the step log.
  An **inert cost does not suppress the PR resolution**: the two operands fail independently, and
  `DEVFLOW_EXECUTION_PR` has a second consumer (the denial floor's skeleton arm below). The cost side
  is unchanged either way — `apply_harness_floor` returns at its first guard on an empty
  `DEVFLOW_EXECUTION_COST`, so no cost skeleton is written and no all-null `harness_cost` is staged.
- *Writer (`--persist`, `apply_harness_floor`).* Gated exactly like record derivation
  (`efficiency_telemetry_enabled`). It attaches `harness_cost` to **exactly** the record whose run-id
  equals this run's `${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}` identity — via a **merge arm** (a
  record derived this pass, or one already on the branch read back with `devflow_telemetry_show_blob`
  and re-staged add-if-absent, byte-preserving `generated_at`) or a **skeleton arm** (a minimal
  `{schema_version:1, slug: pr-<N>, generated_at, source: null, synthesized: true, iterations: 0,
  per_iteration: [], telemetry: [], harness_cost}` when no record for the run-id exists and the
  command class derives records; `pr-description` takes a no-record-by-design breadcrumb instead).
  With the floor env unset, `--persist` is byte-identical to before and silent about the floor.
- *Race safety.* The floor makes the store's first path **mutation**, so the push-retry union
  (`commit_union_on`) is now **merge-aware** (base-wins by default; a path this run did not stage
  never overwrites the base side; a staged efficiency record present on base re-applies the
  add-if-absent `harness_cost` onto the fetched base version) — so a stale local snapshot does not
  revert another writer's `harness_cost` on the normal jq-available merge path (a jq-unavailable or
  empty-blob fallback to a plain local-wins overlay remains possible and is disclosed by a named
  `::warning::` — the "narrows, never closes" posture, not an absolute).
- *Coverage boundaries (explicit, so `harness_cost` presence is never read as complete cloud-cost
  coverage).* A hard-death run that never produced an execution file stays uncovered (a named inert
  breadcrumb in the backstop log, never silent). The read-only auto-review tier
  (`devflow-runner.yml`) is **cost-unmeasured** by this floor — it has no persist step (following-up
  scope, once #469's artifact-staged pusher lands).

## The unified experiment record (`experiment-records.jsonl`)

`scripts/build-experiment-records.py` (issue #431) is the **join** that makes the operator's
experiment program measurable: it assembles one line per merged PR into the tracked
`.prflow/learnings/experiment-records.jsonl`, joining what a run **spent** (the efficiency records
above) to whether its PR came out **clean** (the review outcome). It is a **reader** of every
historical store shape — python3 stdlib plus `gh`/`git` subprocesses (the `DEVFLOW_GH` env-read
pattern, no probe; native `git` subprocess per the #295 Windows rule) — and runs on the
**local/interactive retrospective tier only** (invoked by `skills/retrospective-weekly/SKILL.md`
between Step 5 (Materialize) and Step 7 (State PR), best-effort — its failure logs a stderr breadcrumb
carried into the Step 9 status report as a blocker note and never blocks the retrospective;
`lib/open-state-pr.sh` then commits the store on the state PR so `main` is clean entering Stage B).

**Sourcing telemetry (issue #441).** The efficiency records the reader joins against are read as a
**union** of two sources, keyed by `(slug, run-id)` with **branch-wins** precedence so a run present
in both contributes exactly one cost row: the durable **telemetry branch** (enumerated via
`git ls-tree`/`git show`, where every run now persists) unioned with any **legacy tracked
`.prflow/logs/efficiency/`** in the working tree (the read-only archive a consumer repo may still
carry from before the branch existed — no history is lost, no manual migration needed). The
orchestrator (`skills/retrospective-weekly/SKILL.md`) **fetches the telemetry branch before the
reader runs**; when the branch does not exist yet (a not-yet-upgraded repo), the fetch is a harmless
no-op and the reader reads the legacy archive alone.

Each line carries its own `schema_version` (currently `1`, independent of the efficiency record's)
plus the PR's identity — `pr`, `issue`, `branch`, `merged_at`, `merge_commit_sha` — and then the
joined fields:

- **`efficiency_runs[]`** — **all** matching efficiency records for the PR as a per-run list with
  per-run `cost` (never newest-wins, since discarding earlier runs' cost corrupts a cost-vs-outcome
  experiment). Both slug families are resolved: `pr-<N>` directly, and the branch slug from the
  retrospective entry's `branch` field (with a `gh` lookup fallback). Each entry carries the full
  key set `_efficiency_entry` emits: `slug`, `run_id`, `source`, `iterations`, `synthesized`, `cost`,
  `telemetry_complete`, `config_fingerprint`,
  `harness_cost` (issue #475 — the Layer-4 floor's whole-job cost, passed through verbatim by
  `_efficiency_entry`; `null` when the run has none, and deliberately NOT summed into `cost`),
  `permission_denials` (issue #1064 D2 — the denial-forensics object, passed through verbatim; `null`
  when the run has none), and — since issue #1826 — the producer's whole `per_iteration` array and the
  run-level `cut_candidate_min_dispatch`, both passed through verbatim so the cross-run roster analyzer
  reads per-reviewer outcome by diff shape and loop position from the tracked store rather than
  hand-querying a telemetry branch. `per_iteration` is normalized to `[]` when the record's value is
  missing or not a list (a floor/synthesis run writes a reduced set — an empty array is an ordinary,
  expected input), and `cut_candidate_min_dispatch` is `null` when the record has none. Older stored
  lines predate these two keys and are left untouched; the store is a mixed file by design, and no
  reader compares an entry's key set.
- **`telemetry_complete`** (per efficiency run) — `true` **only** when the record is not synthesized,
  every iteration carries non-null token telemetry, and no degradation breadcrumb is present. Analyses
  exclude degraded records **by this flag** rather than silently averaging them in.
- **`retrospective`** — the PR's retrospective entry (the `branch`-slug join key and PR metadata).
- **`verdict`** — selected by **artifact shape**: the first completed PR review whose body matches the
  `## Verdict:` contract **regardless of bot identity**; when none exists, the run-keyed
  `prflow:review-progress` comment's `## Verdict:` line is the fallback; when neither exists the
  verdict is `null` (the #403 shape). The parser strips both the full-report `(summary)` suffix and
  the pr-review stub suffix `— full report in PR comment` the engine appends when a live progress
  comment is active, so the stored verdict is the bare token (`APPROVE` / `REJECT` / …) on every
  surface. The `provenance.verdict` field names which arm resolved it — `pr-review`,
  `progress-comment`, `progress-comment-degraded` (the comment supplied the verdict *because* the
  authoritative reviews call could not be established, so the value may predate the final reviewed
  HEAD — degraded, not merely second-choice; the reason is spelled out in `provenance.notes`),
  `unparseable` (a `## Verdict:` marker was present but its line did not parse), `absent`, or one of
  the **unestablished** tags enumerated below.
- **`important_finding_count`** — parsed from the run-keyed progress comment joined via
  `review.commit_id` == the comment's `**Reviewed HEAD:**` line (the engine's own join — see
  `skills/review/SKILL.md`, the normative source). This is a measurement join, not a reviewed-tree
  authority: `review.commit_id` is mutable (GitHub can change it after submission — issue #1247), so
  the reviewed *tree* is identified elsewhere by the verdict marker's `head=`. `null` with provenance
  when no progress comment joins to the review's commit_id (absent or superseded by a later run's
  comment), its findings section is unparseable, or the comment could not be established.
- **`permission_denials_count`** — read from the `Devflow Review` check-run `output[summary]`
  `permission_denials_count:` line (issue #431) for PRs after that change; for historical PRs it falls
  back to best-effort check-run **annotation** retrieval (provenance `check-run-annotation`), whose
  bias is recorded in `provenance.notes` (annotations carry only **positive** counts, so a historical
  zero is indistinguishable from unavailable, and expired logs yield nothing). Carried **verbatim** in
  every path — `unavailable` stays `unavailable`, and **no code path coerces an unestablished count to
  `0`** (the repo's unknown-is-not-zero contract, end to end).
- **`config_fingerprint`** — from the efficiency record's `config_fingerprint` when present, else
  recomputed from `git show <merge_sha>:.prflow/config.json` (records predating the field);
  `provenance.config_fingerprint` marks the source (`efficiency-record` / `merge-commit-config` /
  `absent`, plus the unestablished tags below). When a PR's runs carry **disagreeing** fingerprints
  (its runs straddled a config change), the record-level value is `null` with source
  `mixed-across-runs` rather than first-wins: this field is the experiment's *attribution key*, so
  silently stamping such a PR with the older variant would misattribute its outcome. Nothing is lost —
  the per-run fingerprints remain in `efficiency_runs[]`.
- **`provenance`** — a map naming which sources joined (and a `notes` list), so a `null` field is
  always distinguishable from an unqueried one.

**Unestablished is not absent.** `absent` is the strong claim *"we looked and it genuinely was not
there"*. The **unestablished** tags below mean the opposite — the join could not be measured at all — and they are never
collapsed onto `absent` (the provenance-dimension analogue of the value-level unknown-is-not-zero
contract). They apply to every gh-sourced field above:

| Tag | Meaning |
| --- | --- |
| `fetch-failed` | The call ran and did not yield a usable answer — a non-zero `gh` exit, or an exit-0 response whose body was unparseable. |
| `no-repo` | The repo could not be resolved, so no *join* call was attempted (the single `gh repo view` probe that resolves it having already failed). |
| `no-sha` | The PR metadata that supplies the query key (head / merge sha) was itself unestablished, so this join is unestablished *by cascade*. |
| `unparseable` | The artifact was retrieved, but the value could not be read out of it (a `## Verdict:` marker whose line does not parse; a fingerprint envelope carrying no `sha256`). |

The normative list is `PROVENANCE_UNESTABLISHED` in `scripts/build-experiment-records.py`; a record is
rejected at construction if any field governed by one of these tags carries a non-null value, so an
unqueryable join can never publish a measurement.

**Idempotent** (one line per PR, keyed by PR number — a re-run replaces, never duplicates) and
**incremental** (it processes merged PRs absent from the store plus any passed via `--prs`, never a
full-history sweep per invocation). **Missing-source-tolerant — for the *inputs***: every join input
is optional, so an absent source yields null fields plus a provenance tag, and an unreadable *input*
store emits a stderr breadcrumb and simply does not join. Never a fabricated value.

**But tolerance is a claim about the inputs, not about the exit status.** The *destination* store
(`experiment-records.jsonl`) is read **strictly**, because the assembler REWRITES it rather than
appending: tolerating a corrupt line there would silently delete every record it could not parse, and
`lib/open-state-pr.sh` would commit the truncation. The run **exits 2** — writing nothing — in that
case, and also when a PR's merge state could not be **established** (a `gh` outage: excluding it
silently would lose it for good, since only stored or retrospective-listed PRs are ever re-selected)
or when any candidate failed to assemble. Records that *did* assemble are still written on a partial
failure, so a non-zero exit means "some PRs are missing from the store," not "nothing was written."
A PR **observed** to be unmerged is a clean exclusion and exits 0 — observed-unmerged and
unestablished are never conflated in either direction.

**CLI surface.** Invoked bare, the assembler resolves everything from the repo root and needs no
arguments — that is how `/prflow:retrospective-weekly` calls it. The flags exist for re-runs and
tests: `--prs <n,n,…>` forces specific PRs into the candidate set (the re-run path after a partial
failure, since an unestablished PR never enters the store and so is not re-selected on its own),
`--dry-run` assembles and reports without writing the store, and `--repo-root` / `--store` /
`--retrospectives` / `--efficiency-dir` override the four resolved paths. Exit codes are **0**
(everything selected was assembled, or cleanly excluded as observed-unmerged) and **2** (see above);
there is no exit 1.

**Abandoned-run exclusion and its cost-side bias.** The record is keyed on **merged** PRs, so a run
whose slug never produced a merged PR (an abandoned branch) contributes **no cost row** — the cost side
therefore carries a documented survivorship bias (abandoned-run cost is invisible to the join). This is
deliberate: the experiment measures cost-vs-outcome for PRs that shipped.

## Migrating legacy unavailable telemetry

The persist backstop normalizes only a new durable workpad path. It first copies the run bytes,
then classifies staged `iter-*.json` with two gates: the file must parse as a JSON object, and only
an absent or null `telemetry` key is stamped. Established empty, false, zero, wrong-type, and
already-marked values remain byte-identical; malformed and non-object inputs remain untouched with
a warning. Existing durable paths are reserved for the migration, so an old Stop-hook discovery
cannot rewrite history opportunistically. Derived run records use `phases: "unavailable"` for the
same absent/null inputs.

After the stamping code lands, maintainers should refresh old writers, upgrade consumer vendored
`prflow_version` pins, let in-flight writes drain, and invalidate diverged local telemetry refs
that could retain pre-migration snapshots. Then run `scripts/backfill-telemetry-unavailable.sh`.
It rewrites absent/null iter blocks and only present `telemetry[].phases: null` entries in run
records, using the shared telemetry-branch CAS/push path. It is intentionally re-runnable: a second
run selects nothing, while later stale-writer pollution can be converged by running it again. The
drafting baseline was 43 of 111 telemetry-branch iter blobs and 25 of 56 run records; the expected
post-run counts are zero selected blobs in both families. Readers still tolerate legacy shapes in
clones, forks, and branches produced by pre-change code.

The push-retry union is marker-monotonic on collisions. A stale local absent/null iter blob or
null-phases run record cannot overwrite a normalized remote blob; every other collision retains
the historical local-wins behavior.

## Out of scope (tracked as follow-up)

The cross-run analyzer (`lib/efficiency-report.jq`) and the weekly-loop recommendation section remain
open work this issue does **not** supersede — the cut-candidate aggregation that consumes
`cut_candidate_min_dispatch` / `phase3_dispatched_present` is still unbuilt. Issue #431 added the
`experiment-records.jsonl` **join** (above), which is the measurement substrate those analyzers will
read; it does not itself compute cut candidates or weekly recommendations.

(Standalone `/prflow:review` was previously listed here as out of scope; it now produces its own
per-run record and live trace — see **Standalone /prflow:review** below.)

## Standalone /prflow:review

`/prflow:review` (the single-pass engine, no fix loop) produces the same observability as
`/prflow:review-and-fix`, surfaced through a **live progress comment** on the PR and — on a writable
run — a per-run record. Two differences from the fix-loop case:

**Review-mode effectiveness derivation.** Standalone review never applies a fix, so its records have
no `fix_decision`. Each Phase-3 finding instead carries `contributed_to_verdict` (a boolean):
`true` when the finding counted toward the verdict (drove the REJECT, or was a non-deferral-demoted
finding in an APPROVE-with-notes), `false` when Phase 4.0's deferral match demoted it to
Informational. `verdict_for` in `lib/efficiency-trace.jq` selects its **review-mode branch** off the
run-level `source == "review"` (passed as an explicit `$review_mode` argument), *not* off per-finding
field presence — a demoted finding may carry `contributed_to_verdict: false` or omit it entirely, and
keying on presence would mis-route such an agent into the fix-loop branch and downgrade it from
`noise` to `null`. In review mode: `unique-effective` = a contributing finding no sibling corroborated,
`corroborating` = a contributing finding ≥2 agents raised, `noise` = the agent raised findings but
none contributed, `null` = dispatched but silent. The buckets and precedence are
identical to the fix-loop's; only the "did it count?" signal differs. Records produced by
`/prflow:review-and-fix` (which carry `fix_decision`, not `contributed_to_verdict`) keep the
applied-fix derivation unchanged.

**`source` field.** Every record carries `source` — `"review"` for standalone `/prflow:review`,
`"review-and-fix"` (the default when absent) for the fix loop. Both write into the same
`.prflow/logs/efficiency/` store, so `source` (not the filename) is what a cross-run analyzer uses
to segment by originating skill. (The two skills key the filename differently — review-and-fix by
`<run-id>` for its `--persist` backstop's idempotency, standalone review by timestamp — but since
`source` is the segmentation key, the filename scheme is free to differ.)

**Live progress comment + read-only cloud.** In PR mode (and when
`prflow_review.live_progress_comment_enabled` is `true`, the default), `/prflow:review` authors a
`prflow:review-progress` comment incrementally — a blueprint of the phases, then
per-phase results and each Phase-3 agent's findings as they land, finalizing with the verdict, the
full report, and the telemetry summary + effectiveness trace. One such comment is seeded **per review
run**, keyed by a run-keyed marker (`<!-- prflow:review-progress run=<id>-<attempt> -->`) carrying a
link to that job, so a later run never overwrites an earlier run's comment. It reuses
`scripts/workpad.py` via the helper's `--marker` flag (passed as a plain argument so the command still
starts with the allow-listed helper path) rather than a parallel helper. The slim
cloud `review` profile is read-only for the tree but grants `gh api` / `gh pr comment`, so the comment
edits are permitted there; the per-run record **file** write is gated to writable (local/IDE) runs —
under the read-only cloud profile the trace renders into the comment only, and no file/tree write or
`git` is attempted. The two flags compose independently:
`prflow_review.live_progress_comment_enabled` gates the live comment, and
`prflow_review_and_fix.efficiency_telemetry_enabled` gates the embedded telemetry/trace + record.
One combination has no output surface: telemetry **on** with the live comment **off** in a read-only
cloud run — the record file is gated out of cloud and the comment is disabled, so there is nowhere to
put the trace. The skill emits a one-line `::warning::` in that case rather than silently
computing-and-discarding, so the no-op is visible. (In a writable run that combination still writes
the record file.)

## Verification single-flight telemetry (issue #528)

The single-flight verification coordinator (`scripts/verification-flight.py`) emits its own
per-event JSON records under `.prflow/logs/verification-flight/` (the default; a caller may
redirect them with `--logs-dir`). These are **local** records in the effectiveness-record
family. They are **not** relayed to the telemetry branch by the current plumbing: the trusted
relay (`scripts/collect-staged-telemetry.sh`) harvests only the `.prflow/tmp/telemetry-stage-*/`
staging roots the read-only reviewer stages, and the two workflows that actually run the
coordinator (`devflow-implement.yml`, `devflow.yml`) carry no collect/upload step — so a caller
that wants these records relayed must write them into a staging root (via `--logs-dir`) that a
relay step then harvests. Until then they remain local, per-checkout diagnostics. The events are:

- **`flight_claimed`** — a new owner claim published a `claimed` handle (carries the flight key and
  command-descriptor digest).
- **`flight_attached`** — a later same-checkout caller attached to a matching existing flight —
  **active, or terminal to consume its result** — rather than opening a second owner claim (carries
  the attached-at state, which is what the honesty rule below keys on).
- **`flight_invalidated`** — a read-time transition invalidated an active flight (carries the
  `invalidation_reason`: `checkout_drift` when a supplied current checkout no longer matches, or
  `lease_expired_before_running` when a `claimed` handle's lease elapsed before `mark-running`).
- **`flight_finished`** — the owner recorded a terminal state (carries the terminal state, the
  command duration, and the skipped-checks count).
- **`flight_wait_completed`** — an attacher's `wait` observed a terminal state.

One further record shares this directory and shape without being a coordination event:
**`state_dir_chmod_failed`** — the diagnostic breadcrumb written when the state directory could not
be chmod-ed to `0700` (the flight files are still `0600`; a host that also cannot take this record
gets a stderr line instead). It is a degradation record, not a lifecycle event, so a cross-run
analyzer counting coordination events should exclude it.

Two honesty rules hold. A **stale or incomplete** handle is never counted as saved work — only a
genuine attach-and-consume of a `passed` flight is a suppressed launch, so the suppressed-launch
count the cross-run analyzer derives from these events excludes non-pass handles. And telemetry is
**best-effort and hermetic**: the helper writes these records locally with no network or `git`, and a
failure to write a record never fails the coordination operation or the verification run itself.
