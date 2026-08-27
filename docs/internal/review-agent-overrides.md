# Per-subagent model & effort overrides for the review engine
<!-- verified-against: 15678c64c 2026-08-27 -->

**Config block:** `prflow_review.agent_overrides` in `.prflow/config.json`
**Resolver:** `scripts/resolve-review-overrides.py` (reads via `scripts/config-get.sh`)
**Applied by:** `skills/review/SKILL.md` (the shared review engine)

The shared `/prflow:review` engine fans out to up to nine subagents across Phases 1, 1.5, 2,
and 3. By default every one inherits the orchestrator's model and the session effort. The
`prflow_review.agent_overrides` block lets operators tune each subagent's `model` and `effort`
individually — turning the effectiveness telemetry in [efficiency-trace.md](efficiency-trace.md)
into an actionable lever.

Because the engine is shared, the overrides take effect **identically** whether it is reached via
standalone `/prflow:review` or via `/prflow:review-and-fix` (and thus the Phase-3 code-review
pass of `/prflow:implement`).

## Migration (v2.8.12): the five review-agent keys were renamed

**Breaking config change.** The five Phase-3 review agents were internalized as first-party PRFlow
agents (vendored from Anthropic's pr-review-toolkit plugin), so the engine now dispatches them under
the `prflow:` namespace. Their `agent_overrides` keys were renamed accordingly:

| Old key (pre-2.8.12) | New key |
|---|---|
| `pr-review-toolkit:code-reviewer` | `prflow:code-reviewer` |
| `pr-review-toolkit:silent-failure-hunter` | `prflow:silent-failure-hunter` |
| `pr-review-toolkit:comment-analyzer` | `prflow:comment-analyzer` |
| `pr-review-toolkit:type-design-analyzer` | `prflow:type-design-analyzer` |
| `pr-review-toolkit:pr-test-analyzer` | `prflow:pr-test-analyzer` |

If your `.prflow/config.json` keys `agent_overrides` on any old identifier, rename it to the new
one. A stale old key does **not** abort a run, but it silently stops applying: the engine only ever
dispatches the new `prflow:` identifier, so the resolver only ever reads the new key — it never
reads (and therefore never warns about) a stale `pr-review-toolkit:` key. Renaming is the only way
to make the override take effect again. (If you validate `.prflow/config.json` against
`config.schema.json`, the stale key is rejected outright by `additionalProperties: false`.) The
three checklist keys are canonically `prflow:checklist-generator`/`-deduper`/`-verifier`; their
`devflow:checklist-*` spelling remains accepted as the transitional alias.

## Migration (v2.8.12): the final-pass reviewer key was renamed

**Breaking config change.** The `superpowers` plugin's `requesting-code-review` skill — the Phase-3
final-pass reviewer — was internalized as a first-party PRFlow skill (vendored under
`skills/requesting-code-review/`, seam 3 of the #139 internalization), so its `agent_overrides` key
was renamed to the `prflow:` namespace:

| Old key (pre-2.8.12) | New key |
|---|---|
| `superpowers:requesting-code-review` | `prflow:requesting-code-review` |

Same rename discipline as the v2.8.12 table above — a stale old key is not an error, but it silently
stops applying: the engine only ever dispatches the new `prflow:requesting-code-review` identifier,
so the resolver only ever reads the new key and never warns about the stale one. Renaming is the
only way to make the override take effect again. With this seam PRFlow has **zero** companion-plugin
dependencies.

## The nine configurable identifiers

The override keys are byte-identical to the subagent identifiers the engine dispatches under, so
config, dispatch, and the effectiveness trace stay aligned. The six Phase-3 keys appear verbatim in
the `phase3_dispatched` telemetry and in each finding's `agent`; the three checklist-phase keys
(`prflow:checklist-generator`/`-deduper`/`-verifier`) run earlier, at Phases 1/1.5/2, and so do not
appear in `phase3_dispatched`:

| Identifier | Phase | Notes |
|---|---|---|
| `prflow:checklist-generator` | 1 | Verification-checklist generation. |
| `prflow:checklist-deduper` | 1.5 | Cross-batch dedup (only when >1 generator batch). |
| `prflow:checklist-verifier` | 2 | One dispatch per agent-mode checklist item. |
| `prflow:code-reviewer` | 3 | Always-on. |
| `prflow:silent-failure-hunter` | 3 | Always-on. |
| `prflow:comment-analyzer` | 3 | Always-on. |
| `prflow:type-design-analyzer` | 3 | Gated — only when the diff adds/changes types. |
| `prflow:pr-test-analyzer` | 3 | Gated — only when the test-relevance predicate matches. |
| `prflow:requesting-code-review` | 3 | Final pass; a first-party skill dispatched as a `general-purpose` Task but keyed under this identifier. |

Plus the special `default` key (below).

## Shape

Each value optionally sets `model`, `effort`, and/or `iterations`:

```jsonc
{
  "prflow_review": {
    "agent_overrides": {
      "default": { "effort": "high" },
      "prflow:checklist-deduper": { "model": "sonnet", "effort": "medium" },
      "prflow:code-reviewer": { "model": "opus", "effort": "high", "iterations": "first-only" }
    }
  }
}
```

> **The transitional `devflow:` namespace still validates.** The plugin was renamed
> `devflow` → `prflow`, and `.prflow/config.schema.json` declares a key for **every**
> accepted namespace, so a config committed before the rename keeps validating and keeps
> resolving: `"devflow:code-reviewer": { "model": "opus" }` and
> `devflow:requesting-code-review` are honored exactly like their `prflow:` spellings.
> `prflow:` is the canonical form and is what new configs should use — the shipped
> `.prflow/config.example.json` seeds it, and the config scaffolder renames a `devflow:`
> key to it on the next `install.sh --apply` or `/prflow:init` (see
> [`install.md`](install.md)). Writing the superseded spelling by hand still works and
> there is no behavioral difference; you will just find it renamed after the next
> scaffold. Either spelling is an **own entry** for that subagent, so it
> shadows `default` exactly like the canonical one. If a config somehow carries *both*
> spellings for the same subagent, the **canonical `prflow:` key wins** — precedence is
> positional (the dispatched spelling first, then the remaining accepted namespaces in
> `lib/plugin-identity.json` order), never dependent on which key appears first in the
> file — and `resolve-review-overrides.py` warns that the other entry is shadowed rather
> than dropping it silently. What is *not* accepted is a **pre-internalization** external id
> (the `pr-review-toolkit:` / `superpowers:` forms in the migration tables above):
> `agent_overrides` is `additionalProperties: false`, so those are rejected outright.

- `model` — one of the Agent tool's four accepted aliases (`sonnet`, `opus`, `haiku`, `fable`),
  validated against that closed set. An in-set value is forwarded to the dispatch unchanged; an
  out-of-set value (a full or provider-routed identifier, `inherit`, an unknown alias, or a case
  variant such as `Opus`) is dropped with a `::warning::` naming the rejected value and the accepted
  set, and the agent then inherits the top-level `claude_model`. A present-but-unusable model (empty
  string or non-string) is likewise dropped with a `::warning::`, mirroring the invalid-effort path. A
  consumer whose model is addressed through a provider route sets it at the top-level `claude_model`,
  which is unchanged and still takes a full/provider identifier.
- `effort` — one of `low`, `medium`, `high`, `xhigh`, `max`.
- `iterations` — optional, **default-off**; the only valid value is `first-only`. An agent whose
  resolved override carries it is **excluded from the Phase-3 review roster on fix-loop iterations
  ≥ 2** — so it reviews only on iteration 1 of a `/prflow:review-and-fix` (and thus
  `/prflow:implement`) fix loop. It is a **roster-scoping** key, not a dispatch-time model/effort
  parameter: the resolver only reads it and passes a valid value through, and the exclusion itself is
  enforced engine-side in `skills/review/phases/phase-3-agents.md` Phase 3.1. In **standalone `/prflow:review`** (a
  single pass) and on **iteration 1** the key is a no-op — behavior is byte-identical to omitting it.
  It is also **never** applied to the Step 2.6 shadow fan-out, whose blinded audit always keeps the
  full roster. An out-of-enum value (or empty string) is dropped with a `::warning::`, mirroring the
  invalid-effort path; the run never aborts.

> **Claude Haiku rejects `effort`.** The `effort` parameter is supported only on Opus 4.5–4.8, Opus 5, Sonnet 4.6, and
> Sonnet 5; Claude Haiku rejects it with **HTTP 400**. So any entry that pins a Haiku model (a
> `claude-haiku-*` id) **must not** also carry an `effort` key. The shipped `prflow:checklist-deduper`
> override pins Claude Sonnet 5 (which *does* support `effort`) with effort `low`, so it is exempt;
> the constraint matters if you re-pin a Haiku id there. The schema does not enforce this (it is a model-API fact, not a structural
> one), so the constraint is documented on the `prflow:checklist-deduper` property in
> `config.schema.json` and guarded by the shipped-example test in `lib/test/run.sh`.
>
> **Re-scaffold repairs stale configs.** Earlier releases shipped the deduper override *with* an
> `effort` key, so configs scaffolded before that was removed silently retain the HTTP-400 combo.
> The add-only config backfill cannot fix this — a key *removal* in the example never propagates to
> an existing config. Instead, `scripts/scaffold-config.sh` runs a best-effort, idempotent cleanup
> on every re-scaffold (`/prflow:init` or `install.sh`): it strips `effort` from *any*
> `agent_overrides` entry whose `model` is a Haiku id, leaving non-Haiku overrides untouched. An
> already-clean config is a quiet no-op (no file churn, no log line).

## This repo's `code-reviewer` application — baseline, revert trigger, deferred repricing (issue #425)

PRFlow's own tracked `.prflow/config.json` sets
`"prflow:code-reviewer": { "model": "opus", "effort": "low", "iterations": "first-only" }`
(the `opus` alias, which the accepted-set validation requires; it resolves to the current Opus family model).
The `iterations` scoping was added on the evidence of replay study **R2** (2026-07-11): on this repo's
overwhelmingly `engine_self_modifying` diffs, `prflow:code-reviewer` measured **6.7% unique-effective**
(9 of 135 dispatches), **2 sole-source applied Importants across 129 dispatches**, and — the positional
finding — **zero sole-source applied findings after iteration 1** (61 late-iteration dispatches produced
nothing unique). Scoping the agent to `first-only` stops ~47% of its dispatches (the positionally-worthless
late ones) with no measured loss.

**Pre-widening scope note (issue #1071).** The R2 figures above were measured under the **pre-widening** `engine_self_modifying` definition — its three source-directory arms (`skills/**`/`agents/**`/`lib/**`) only. Issue #1071 widened the flag's population with two further arms, and **both enlarge the population this baseline was measured over**: the state-directory `.md` arm (a prompt extension under `.prflow/`/`.devflow/`), and the `CLAUDE.md`-basename arm — the second widening it **further still**, on consumer repositories where `CLAUDE.md` is the consumer's own frequently-edited governance file and on this repository's own `CLAUDE.md`-only pull requests. The recorded figures are **not** re-read under the widened definition; they stand as the pre-widening measurement, and this note records that the adjudication baseline's population changed after they were taken.

- **Revert trigger for the `iterations` key.** Any retrospective entry attributing an escaped
  Important-or-higher defect on this repo to a *late-iteration miss* in this agent's specialty class
  (guideline-adherence / doc-mirror) reverts the `iterations` key. Baseline for adjudication is R2 above
  (6.7% unique-effective, 2/129 sole-source, 0 sole-source late).
- **Deferred repricing (pre-registered follow-up).** Model repricing is deliberately deferred:
  `agent_overrides` model values apply identically to standalone `/prflow:review`, and the frozen-judge
  guardrail of the 2026-07-11 optimization methodology forbids repricing the outcome judge's roster
  mid-window. After the current experiment window closes, a follow-up PR reprices `model` from
  `claude-opus-5` to the Haiku family (pre-registered as `claude-haiku-4-5-20251001`; since the
  accepted-set validation this change added now drops a full identifier, a live reprice sets the
  `haiku` alias) **and drops the entry's `effort: "low"` key** — a Haiku id must not carry
  `effort` (see the Haiku HTTP-400 callout above), so the swap is not literally one line: the entry
  becomes `{ "model": "claude-haiku-4-5-20251001", "iterations": "first-only" }`. That follow-up
  carries its own trigger: any specialty-class escaped
  Important-or-higher finding on a PR reviewed under the repriced config within **4 retrospective weeks**
  (extended until **30 repriced dispatches**) reverts the model to `claude-opus-5`. A deterministic
  auto-revert mechanism was considered and rejected — no machinery exists to edit tracked config on a
  metric threshold, and building it is out of proportion to a one-line revert.
- **Note on the pre-registered `from`/revert id (issue #1053).** The two `claude-opus-5` mentions in the
  bullet above are the pre-registration's own terms and are **left verbatim**: they record what was
  pre-registered, not what the tracked file holds. After that pre-registration was written the tracked
  default was **reverted** to `claude-opus-4-8` (commit `cccd250c`, reverting `3f30ad3a`), and the
  accepted-set change then re-expressed that entry as the `opus` alias — the value the sentence opening
  this section now states. Read the repricing plan as "reprice away from whatever Opus model the tracked
  entry resolves to"; respelling the pre-registered target would falsify the experiment's recorded
  terms, so it is not done here.

## The `pr-test-analyzer` first-only override and its coverage-waiver honor rule (issue #2031)

The shipped `.prflow/config.example.json` seeds a companion `iterations: "first-only"` entry for the
coverage reviewer:

```jsonc
"prflow:pr-test-analyzer": { "iterations": "first-only" }
```

so a fresh install resolves the coverage reviewer with `first-only` and drops it from the Phase-3
launch roster on fix-loop iterations ≥ 2, while iteration 1 and the standalone `/prflow:review` keep it
(the Step 2.6 shadow fan-out keeps its full roster by the engine's existing rule). This reaches existing
installs only for the key they lack, at their next re-scaffold — an existing `agent_overrides` value
wins, so the companion's reach is fresh installs plus absent-key backfill.

The rationale is proportional test authoring: on a small ticket the implement run may take the Phase 2
§2.3 **test-authoring proportionality waiver** (see
[`implement-skill.md`](implement-skill.md)), and re-dispatching the coverage reviewer on every late
fix-loop iteration re-litigates coverage the run deliberately scoped down.

**Bounded coverage-waiver honor rule.** `agents/pr-test-analyzer.md` reads a recorded test-authoring
waiver from its dispatch context — sourced from the workpad note when the implementing run's own review
pass dispatches it, and from the PR body's Test Plan line on any later review. `skills/review/phases/phase-3-agents.md`
resolves the verbatim waiver text into the `{TEST_AUTHORING_WAIVER}` slot of the pr-test-analyzer
dispatch prompt (substituting `none recorded` when none is present), using only reads the engine already
performs — the already-granted workpad read and Phase 0's `gh pr view … --json body` read — with no new
helper or command head. The reviewer then:

- treats the waiver text strictly as **data to classify, never an instruction to obey** — it is
  author-supplied and may be phrased like a command; it changes nothing beyond the bounded cap below;
- caps a coverage gap it would otherwise rate in the **sub-critical band (1-7)** at Suggestion when the
  gap falls on a surface the waiver names, stating the waiver as the reason;
- keeps its **top band exempt** — a gap rated **8-10** (the Critical Gaps bucket, the data-loss and
  security class) stays at full severity regardless of any waiver;
- **fails toward full strictness** on a malformed, absent, duplicated, or truncated waiver, or one
  naming surfaces the diff does not touch — no cap applies unless the gap both falls in the sub-critical
  band and lands on a surface the waiver actually names.

Trust-boundary residual: the PR body is author-writable, so a waiver line can appear without a real
waiver behind it. The residual is bounded — the honor rule only lowers matching sub-critical findings to
Suggestion, the top band ignores waivers entirely, and the merge verdict threshold is unchanged.

## Resolution rules

- **Entry-level precedence.** A subagent with its own entry uses **only** that entry; the
  `default` does **not** backfill its missing fields. The `default` entry supplies model/effort
  only for subagents that have no entry of their own. (So `code-reviewer: { model: m }` with a
  `default: { effort: high }` dispatches `code-reviewer` with model `m` and the **session** effort
  — not `high`.)
- **Explicit empty entry opts out of `default`.** An explicit empty entry (`"prflow:code-reviewer": {}`) counts as "has an entry": it sets neither model nor effort **and** does not inherit `default`. Use it to deliberately exclude one subagent from a broad `default` override.
- **No-entry fallback.** A subagent with **neither its own entry nor a `default`** is dispatched
  exactly as today — the global `claude_model` and the session effort — with **no per-agent
  `model` override supplied at dispatch** (a `session-inheritance` in the per-tier matrix above).
  Existing configs (which have no `agent_overrides` block at all) are therefore completely
  unaffected.
- **Invalid effort → warn + fall back.** An `effort` value outside the enum produces a
  `::warning::` and falls back to the session effort rather than aborting the run. A `model` value
  inside the accepted set (`sonnet`, `opus`, `haiku`, `fable`) is forwarded as given; a value outside
  that set — or an empty, whitespace-only, or non-string `model` — is dropped with its own warning,
  and the agent inherits the top-level `claude_model`.
- **Malformed shapes never abort.** A non-object entry (a hand-edited `"agent": "high"` or a list,
  which bypasses schema validation) is ignored with a warning and, on the engine-facing end-to-end
  path (`read_raw`), treated as no-entry — so `default` still applies. (A direct `resolve_overrides`
  call handed the same non-object entry skips it *without* applying `default`, since the entry's
  presence already counts as "has an entry"; operators only reach the resolver via `read_raw`, so the
  `default`-applies behavior is the one they observe.) A non-object `default` is likewise ignored. An
  entry that resolves to neither a model nor a valid effort emits no override at all. The engine never
  aborts on config shape.
  - **Object-valued `model`/`effort` leaf.** A hand-edited object leaf (e.g. `"model": {…}`) is
    dropped with a warning. If that was the entry's only field, the entry resolves to `{}` — which,
    being a present (empty) entry, **shadows `default`** for that subagent (it is dispatched at the
    session model/effort, not the `default` override).
  - **Array-valued leaf (narrow gap).** `config-get.sh` joins an array leaf with commas before this
    resolver sees it, so it is indistinguishable from a scalar string. A multi-element array effort
    (`["high","low"]` → `"high,low"`) fails the enum check and is dropped with a warning, but a
    **single-element** array (`["high"]` → `"high"`) silently passes, and an array `model`
    (`["a","b"]` → `"a,b"`) is forwarded verbatim as a model id. All of these require hand-editing
    past the schema (`additionalProperties:false` + the `effort` enum + `model:string` reject them
    in any validated config); the worst case is one malformed dispatch the harness would itself reject.
- **`iterations` roster scoping (default-off).** An optional `iterations: "first-only"` key excludes
  its agent from the Phase-3 roster on fix-loop iterations ≥ 2 (enforced engine-side, not by this
  resolver). It obeys the same **entry-level precedence** as `model`/`effort` — a
  `default: { "iterations": "first-only" }` supplies it only to no-entry agents, and an agent's own
  entry does not inherit the `default`'s `iterations`. The resolver only **reads** the key and passes
  a valid value through the resolved map; an out-of-enum value (or empty string) is dropped with a
  `::warning::` and the agent then participates on every iteration (the run never aborts). Standalone
  `/prflow:review` has a single pass, so the key is a structural no-op there. An excluded agent is
  legitimately absent from that iteration's `phase3_dispatched` (like a gated-out analyzer). An entry
  carrying *only* `iterations` (no `model`/`effort`) still resolves.
- **Gated agents.** The two structurally-gated Phase-3 analyzers (`type-design-analyzer`,
  `pr-test-analyzer`) are only dispatched on applicable diffs; an override is emitted only for an
  agent actually dispatched in a given run.

## Version-skew safety of the `iterations` key (both directions)

The `iterations` key was added additively (issue #425); it is safe across a version skew between a
consumer's vendored resolver/schema and its `.prflow/config.json`, in **both** directions:

- **Old resolver, new config.** A resolver vendored before the key existed reads only `model`/`effort`
  and simply ignores an `iterations` entry key — so a config that carries `iterations` degrades to
  today's behavior (the agent participates on every iteration). No error, no abort.
- **New config, stale schema.** If you validate `.prflow/config.json` against a `config.schema.json`
  that predates the key, `additionalProperties: false` on each override entry **rejects** the unknown
  `iterations` key outright. The fix is to ship the schema version that declares it — the key requires
  the schema that ships it. (An unvalidated config is unaffected; validation is opt-in.)

## Mechanism — how model and effort actually reach a subagent (issue #554)

All nine subagents are **first-party PRFlow assets** (the three `prflow:checklist-*` — whose
`devflow:checklist-*` spelling remains accepted as the transitional alias — and the
five vendored `prflow:` review agents under `agents/`, plus the vendored `prflow:requesting-code-review`
skill under `skills/`, dispatched via `general-purpose`). The engine resolves the overrides with
`scripts/resolve-review-overrides.py` (which reads the config through `config-get.sh`); each agent's
own `description`/`prompt`/`tools` come from its committed first-party definition (under `agents/`, or
`skills/` for the final-pass reviewer), with only the configured `model`/`effort` considered per run.

**Model and effort do NOT reach the subagent by the same path, and effort is not applied per-agent
on the path both tiers use today.** The review engine dispatches its subagents from an
**already-running session** via the **Agent tool**. That tool exposes a per-dispatch **`model`**
override parameter but **no effort parameter**, and an already-running session has **no per-dispatch
`--agents` injection**. So:

- a resolved per-agent **`model`** override IS delivered — supplied as the Agent tool's `model`
  override parameter at dispatch;
- a resolved per-agent **`effort`** override is **NOT** deliverable per-agent on this in-session path
  — the subagent inherits the **session effort**. This is reported honestly (a per-resolve
  `::notice::` summary from the resolver, distinct from `::warning::`), never claimed as applied.

**The parameter surface is not closed at `model`, and the omission that mattered was
background-dispatch semantics (issue #801).** Beyond `model`, the Agent tool carries a
**per-dispatch background/foreground** property, and it is the property that decides whether a
dispatch returns a result at all — so a survey of the surface that stops at "`model` yes, effort no"
omits the one parameter a no-verdict run turns on. Upstream, **subagents run in the background by
default** (vendor-documented as of Claude Code v2.1.198; read from
https://code.claude.com/docs/en/sub-agents on 2026-07-24 and not re-derived here), and a background subagent's results reach the caller as a
completion notification **in a later turn** — which a headless `claude -p` cloud run never reaches,
so the dispatched work is discarded and the run can end with no verdict. Two layers cover this:
the cloud engine workflow steps set `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS: "1"`, documented upstream
as keeping subagents in the foreground (and, since issue #812, no longer resting on that upstream
documentation alone — a `background-tasks-probe` job in `.github/workflows/matcher-probe.yml`
observed the variable's effect inside `claude-code-action`; the dated verdict, its run identifiers,
and its re-probe caveat are recorded once, in
[`DEVFLOW_SYSTEM_OVERVIEW.md`](DEVFLOW_SYSTEM_OVERVIEW.md)'s `prflow_implement.stall_backstop`
bullet); and the injected grounding block (`scripts/render-grounding-block.sh`) states the
requirement behaviorally, in every mode it renders. That block is the requirement's **sole home** —
neither engine root carries a copy any more — so every cloud tier gets it from one place, and a run
whose prompt carries no block is the case each dispatch site's pointer handles fail-closed. The
workflow variable is the floor, not the only lever: the corresponding **per-dispatch** parameter
(`run_in_background: false` on this runner) is the one the dispatching engine can set itself, and
the block names that one lever as the one to reach for rather than assuming the workflow-level one
is in force. It is named as the current mechanism, not as the definition of the requirement; the
cloud tier supports Claude Code headless only, so the block no longer hedges the requirement across
runtimes with no equivalent switch. A second consequence is relevant to *this* doc's
subject: a background subagent keeps its MCP tools but is restricted to a narrower set of built-in
tools than its definition grants, so forcing foreground also restores the roster's full declared
tool surface — an agent-behavior change independent of the stall itself.

Earlier releases of this doc and the engine described both model and effort as riding a per-run
`--agents` JSON block "for every subagent". That mechanism does **not** exist in an already-running
session — it was fictional for **model as well as effort** (model happens to be delivered by the
Agent tool's `model` parameter, a different, unstated mechanism). The description is corrected here;
"model behavior preserved" refers to model *delivery* (unchanged), not that old (false) description.

### Per-tier effort application-point matrix

Each dispatched review agent's effort decision carries an **application point** — one of four values:

| Application point | Meaning |
|---|---|
| `agent-definition` | The resolved per-agent effort was composed into a **proven** process-start agent-definition seam (an applied arm). This arm exists **only if** an empirical cloud-action seam spike proves the seam is reachable — see below; it is **not** shipped today. |
| `process-start-session` | The section-level session effort (`prflow.effort` / `prflow_implement.effort` / `prflow_runner.effort`) composed into `--effort` at process start — session-wide, inherited by all subagents, capability-gated by `providers.*.effort_supported` (#313). Not per-agent. |
| `session-fallback` | A resolved **per-agent** effort override the tier **cannot apply** (or a capability-restricted one). The override is not emitted; the agent inherits the session effort; the resolver reports the fallback with a reason. |
| `session-inheritance` | A dispatched agent with **no** per-agent effort override — it simply inherits the session effort. All-null effort block, no fallback reason. |

Per execution tier:

| Tier / dispatch context | Per-agent effort application point | Per-agent effort applied? |
|---|---|---|
| **Cloud** review — fresh `claude-code-action` process per run | `session-fallback` (see spike note) | **No** — the process-start `--agents` effort seam is **hypothesized but unproven**; the only `--agents` usage in `.github/` is the [seam probe](agents-seam-probe.md) itself (`.github/workflows/agents-seam-probe.yml`), which is authored but not yet dispatched to a `SEAM_PROVEN` verdict, so until it proves the seam the cloud per-agent row is honest fallback identical to local. |
| **Cloud/local session effort** — `prflow.effort` / `prflow_implement.effort` / `prflow_runner.effort` | `process-start-session` | Session-wide, not per-agent — capability-gated by `effort_supported` (#313). |
| **Local** review — already-running interactive session dispatching via the Agent tool | `session-fallback` | **No** — the Agent tool carries `model` but no effort, and no per-dispatch `--agents` injection exists; the run reports the limitation and effective fallback with a reason. |

On any `session-fallback` arm the resolved per-agent effort is **not** applied; the subagent inherits
the session effort, and the run states the limitation and the fallback reason at resolution time. The
**effective** effort is recorded only when it can be read back from an applied/composed artifact — on
every in-session arm the engine cannot introspect its own session effort, so `effective` is **null**
(unknown is not zero), never guessed. Model overrides are delivered exactly as before on every tier.

Each dispatched agent's effort decision — its `requested`, `resolved`, `application_point`,
`effective`, and `fallback_reason` — is emitted per agent into the per-run efficiency telemetry as the
per-iteration `agent_effort[]` observability block (issue #609), so the matrix above is not only a
resolution-time contract but an after-the-fact audit surface. The block covers the full dispatched
roster — the six Phase-3 keys via `phase3_dispatched` plus the three checklist-phase keys (Phases
1/1.5/2) via the iter-workpad's `dispatched_effort` field. `resolve-review-overrides.py`'s
`--effort-json` mode emits the five-field map that populates it. See
[efficiency-trace.md](efficiency-trace.md) for the record schema.

**How the fallback is reported (per resolve, i.e. per dispatch phase).** `resolve-review-overrides.py`
distinguishes the *cause* so a genuine misconfiguration is never laundered into steady-state noise:

- a **benign** in-session no-seam fallback (a valid override the tier simply has no per-agent effort
  seam for — the permanent local/unproven-cloud steady state) is reported as **one informational
  `::notice::` summary** over all such agents (never one line per agent), distinct from `::warning::`;
- a **capability-restricted** fallback (the resolved model is a Claude Haiku id that rejects `effort`,
  or the routed provider's `effort_supported` is `false`) is a genuine unusable-model/provider
  misconfiguration, so it is a **`::warning::` naming the model/provider** — the same channel the
  resolver already uses for an invalid effort value or an unusable model.

The provider `effort_supported` capability is resolved by the cloud workflow — the only layer that can
introspect the routed provider — and exported to the review job's environment as
`PRFLOW_EFFORT_SUPPORTED` (from the already-resolved `steps.provider.outputs.effort_supported`
decision, in all three cloud workflows). `resolve-review-overrides.py` reads that env var by default
(issue #1772), so an `effort_supported: false` provider now reaches the in-session per-agent effort
decision as a capability-restricted fallback instead of being silently ignored — closing the gap issue
#606's retrospective recorded. Precedence: an explicit `--effort-supported`
flag still wins; an absent or unrecognized env value falls back to `true` (the Anthropic path), so the
common default-path run keeps its per-agent effort and the model-level Haiku restriction (read from the
resolved model) remains the always-on capability guard.

> **Scope of the Haiku guard: the *resolved override entry's* model, not the session model.** The
> guard reads the `model` of the entry `resolve-review-overrides.py` resolved for that agent. Because
> resolution is **entry-level**, a `default`-supplied Haiku *is* covered — an agent with no entry of
> its own resolves to the `default` entry, so the guard sees that Haiku id, exactly as the dispatch
> would. The one uncovered case is the **global** `claude_model` (or a per-section
> `prflow_runner.claude_model`) being a Haiku id while the agent's resolved entry carries `effort`
> but **no** `model`: the resolver reads only `.prflow_review.agent_overrides.*`, so it cannot see
> that session model and classifies the fallback as the benign `::notice::` rather than a capability
> `::warning::`. **The outcome message stays honest either way** — both arms report the effort as NOT
> applied and the agent as inheriting the session effort; only the *cause* bucket is imprecise.
> Closing it needs a caller-supplied session model (the tier decides which section supplies it, so
> the resolver cannot derive it alone) and is deferred follow-up work, not a silent gap.

> **Spike-gated applied arm (`agent-definition`).** A per-agent *applied* arm — composing the
> resolved effort into a process-start agent-definition the platform reads at launch — exists only
> where an empirical spike in the real `claude-code-action` proves the startup `--agents` effort seam
> is reachable AND governs a runtime Agent-tool dispatch. That spike is implemented as the
> [`agents-seam-probe.yml`](../../.github/workflows/agents-seam-probe.yml) probe, whose deterministic
> verdict helper is `scripts/agents-seam-probe-verdict.py` and whose recorded evidence of record is
> [agents-seam-probe.md](agents-seam-probe.md) (issue #610). **The probe is authored but not yet
> dispatched to a `SEAM_PROVEN` verdict**, so until a dispatch proves BOTH facts (forwarding, and a
> human-adjudicated effort-governance self-report), **no per-agent effort application code ships** and
> every tier records honest fallback. On a proven applied arm the recorded `effective` would be the
> effort *composed into* the agent-definition — a spike-grounded proxy for the effort the dispatch
> reasons at, re-established by re-running the spike after a `claude-code-action` upgrade, **not** a
> per-run measurement.

The helper must be the command's **leading token** (the same cloud allow-list rule that governs
`workpad.py`); `OVERRIDES=$(…/resolve-review-overrides.py …)` is fine — the path is the leading
token inside the command substitution — but routing it through a shell variable or prepending a
`VAR=value` env-assignment makes the read-only cloud `review` profile deny it, and every override
silently resolves to `{}`. In the cloud review profile, `resolve-review-overrides.py` must also be
on the `review` tool allow-list for overrides to take effect (see
[cloud-setup.md](cloud-setup.md)); a local/interactive run is unaffected.
