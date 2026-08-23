# Execution-file shape record

**What this is.** A dated, observed record of what `claude-code-action`'s
`steps.claude.outputs.execution_file` actually carries, produced by the re-runnable
probe jobs in [`.github/workflows/matcher-probe.yml`](../../.github/workflows/matcher-probe.yml)
(issue #437). It exists to settle — with evidence, not recollection — the question the
repo had asserted as settled fact: *can the token/wall-clock cost half of PRFlow's
telemetry be reconstructed from the harness's own output, without the agent's
cooperation?* See [`docs/internal/efficiency-trace.md`](efficiency-trace.md) for why that
question is load-bearing.

**The `execution_file` schema is NOT a public contract.** This record is a *dated
observation of one action version*, not a specification. `scripts/surface-execution-diagnostics.sh`
and `scripts/parse-engine-error.sh` deliberately tolerate three encodings; this record
confirms or narrows that tolerance but must never be used to hard-code a brittle
single-shape parser. Re-run the probe (`workflow_dispatch`) after any `claude-code-action`
or Claude Code CLI upgrade and refresh the table below.

**Consumed by (issue #475).** The cost half this record settles is now consumed by the
**harness-side cost floor**: `scripts/extract-execution-cost.py` normalizes the file's cost
(`costUSD`/`total_cost_usd`, per-message `usage` tokens, `modelUsage`, `num_turns`, `duration_ms`),
and `lib/efficiency-trace.sh --persist` lands it as a per-run `harness_cost` record field on the
telemetry branch — the first efficiency-pipeline floor NOT fed by an agent-volunteered operand. The
reader mirrors this doc's three-encoding tolerance (object / array / JSONL); because the schema is a
dated observation and not a contract, it is a preference-ordered tolerant parser, never a brittle
single-shape one. See [`docs/internal/efficiency-trace.md`](efficiency-trace.md)'s **Layer 4**.

**Also consumed by (issue #1528).** The file's `{"type":"system","subtype":"init"}` record's
`claude_code_version` is now read in-job on every live run by
`scripts/surface-execution-diagnostics.sh`, which value-publishes it (alongside
`permission_denials_count`) with an `unavailable` fallback and an `::notice::` read-back — no
dependency on the uploaded artifact. Every other init field stays type-only behind the redaction
boundary above. See [`docs/internal/execution-diagnostics.md`](execution-diagnostics.md).

**How each field is recorded (issue #437 AC3/AC4).** For every field, exactly one of:

- `present` — observed in the parsed execution file.
- `absent` — the file parsed **and carried a result event**, but the field was not seen.
- `unavailable` — the field could not be established (the file was absent/empty/
  unparseable, or carried no result event, or the probe run was denied). Per the repo's
  **unknown-is-not-zero** rule, `unavailable` is never collapsed onto `absent` and never
  onto `0`.

The observation is machine-produced by `scripts/extract-execution-shape.sh`, which also
**redacts** the execution file before anything is uploaded: the artifact carries the
structural shape (each object's immediate keys + value *types*) only — every string *value*
leaf is dropped, so no prompt text, repository content, secret, or attacker-controlled
check-run name leaves the run (AC2). (Object keys are the fixed schema field names, emitted
verbatim; the observed schema places untrusted content in value positions, not keys.)

> **One disclosed exception to the string-leaf redaction (issue #805).** The
> `permission_denials_commands` field carries the **raw text of the engine's own denied
> Bash commands**, length- and count-bounded but **not** redacted and **not** neutralized.
> It is the deliberate scope of the denied-command-visibility feature: the whole point is
> to surface those commands without downloading and parsing the multi-megabyte execution
> artifact by hand. They are the engine's own emitted Bash rather than arbitrary prompt or
> repository content, but a command can still quote attacker-influencable text, and the
> `::`-workflow-command / fence-breaking-backtick neutralization is the *rendering*
> layer's job — and no consumer of **this field** ships yet: nothing in the tree reads
> `permission_denials_commands` at this revision, so the precondition binds whoever adds
> the first reader (the `devflow-runner.yml` job output and the check-run consumer in
> the withheld `devflow-review.yml`, issue #936 —
> check-run summary are the intended ones). Scope note, so this is not read as "no denial
> text is rendered anywhere": the maintainer-run `matcher-probe.yml` already writes raw
> `permission_denials` entries into its own step summary, from its own independent walk of
> the execution file rather than from this field. That path is out of scope here — its
> input is maintainer-authored and `::` sequences are not interpreted in a step summary —
> but it is why "no consumer ships yet" is a statement about this field, not about the
> repository's rendering of denial text in general.
>
> **Precondition discharge (issue #1064).** The first *live* reader of the denied-command
> text now ships: `scripts/build-denial-record.sh` consumes `extract-execution-shape.sh`'s
> `permission_denials_commands` and persists the (scrubbed) command text into each run's
> efficiency record on the `prflow-telemetry` branch, wired into the `Persist … (backstop)`
> step of both live tiers (`devflow-implement.yml`, `devflow.yml`). That extractor gates
> every field on a `type: "result"` event, so on an execution file that never emitted one —
> a stall, timeout or crash, which is precisely what the `always()` persist step exists for
> — it reports `unavailable` even when the denied commands are present in streamed message
> events. `build-denial-record.sh` therefore recovers the commands from the denial objects
> directly in that case only, at the same field preference and the same 500-char/40-entry
> bounds, and the recovered value re-enters the same assembly, so it is scrubbed by the
> same blocklist on the same fail-closed path. The shared extractor's own `$has_result`
> contract is unchanged. Because this reader
> writes to a **durable, committed** branch — strictly worse than a 7-day artifact — the
> `#805` precondition is discharged by **the scrub plus a documented off switch together**,
> not by the length/count bounds (which were always there): (1) every command string is run
> through the shared credential blocklist `scripts/scrub-credentials.sh` before persistence
> and the record records `scrub.blocklist_incomplete: true` (the scrub is a blocklist, so it
> is disclosed as incomplete — never claimed as redaction); and (2) the text field is gated
> by the new `.prflow.execution_denial_commands_enabled` key. **The first reader ships
> DEFAULT-ON:** the key defaults to `true`, so an upgrading repository begins persisting
> scrubbed denied-command text without opting in — set `.prflow.execution_denial_commands_enabled`
> to `false` to disable it (the count and denied `tool_name` are always persisted and are
> **not** gated by that key, carrying no credential risk). Any *rendering* of the field still
> routes through `scripts/render-guard-visibility.sh`'s `::`/backtick neutralization; the
> scrub is a persistence-side control, the neutralizer a rendering-side one, and the two are
> independent.
>
> **The field's three values — `unknown` is never `0`.** It emits `unavailable` when the
> extraction was not established: the execution file itself is unavailable, no
> `permission_denials` array is present, **or** a non-empty denials array yields no
> extractable command (the harness carrying the text under a field other than
> `.tool_input.command`/`.command`, or under a non-string value). It emits
> `{"commands": [...], "total": N, "truncated": bool}` only when the extraction ran — with
> `total: 0` reserved for a run that genuinely denied nothing. A consumer must therefore
> render `unavailable` as *unestablished*, never as "this run denied nothing that carried
> a command", the same three-way discipline `permission_denials_count` carries. One
> disclosed residual: a *partial* extraction (some entries yield a command, some do not)
> emits the commands it could extract and counts those in `total`, so it under-reports
> rather than reporting a false zero.
>
> **Consequence for committed evidence:** the statement below that
> `lib/test/fixtures/execution-file-shape.observed.txt` is "redaction-safe by construction" holds for
> the *structural* section and for the probe run that produced it, whose record predates
> this field. It is **not** a standing guarantee for a future re-run: before committing a
> newly generated record, read its `permission_denials_commands` line and confirm the
> commands it carries are safe to publish, or drop that one line. Do not commit a fresh
> record on the strength of the by-construction claim alone.

---

## Observation

**Status: OBSERVED.** The `execfile-shape-probe` job ran and its `execution-file-shape`
artifact is the evidence below. **Every field the question turned on is present.** A second
reviewer, given the run URL, reaches the same verdict by downloading the same artifact —
*"the probe ran"* is not the evidence; the artifact's observed contents are.

| Field | Observed | Evidence |
|---|---|---|
| top-level encoding (array / object / jsonl) | **`array`** | `encoding: array` |
| per-message token `usage` | **`present`** | `usage: object`; keys observed in the structural set: `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `total_tokens` (the flattened, `unique`d key set erases parentage, so the per-message attachment of these keys is a schema-level observation from the run, not something the committed artifact itself can prove) |
| wall-clock timing | **`present`** | `duration_ms`, `duration_api_ms`, `ttft_ms`, `end_time` |
| `tool_use` events | **`present`** | `tool_name`, `tool_input`, `tool_use_id`, `tool_uses` |
| `subagent_type` on `Task` dispatches | **`present`** | `subagent_type: string` (plus `task_id`, `task_type`, `agents`) |
| `permission_denials` | **`present`** | `permission_denials: array` |

Cost is carried **directly**, which the issue did not even ask for: `costUSD`,
`total_cost_usd`, and a per-model `modelUsage` breakdown.

- **Probe run:** `29201071531` (the `execfile-shape-probe` job in `matcher-probe.yml`)
- **Committed evidence:** [`lib/test/fixtures/execution-file-shape.observed.txt`](../../lib/test/fixtures/execution-file-shape.observed.txt)
  — the probe artifact's machine-produced output (with a short provenance header prepended;
  everything below it is the helper's own unedited output), committed **because GitHub artifacts
  expire (~90 days)**. Without it the OBSERVED table above would eventually become an unfalsifiable claim
  with no surviving evidence; with it, a second reviewer can re-derive this table from bytes in
  the repo at any point in the future. (Redaction-safe by construction for the structural
  section — see below, and see the `permission_denials_commands` exception above before
  committing a freshly generated record.)
- **Artifact:** `execution-file-shape` (uploaded by the `execfile-shape-probe` job; also the
  source of the committed file above)
- **Observed on:** `anthropics/claude-code-action@v1`, 2026-07-12
- **Redaction held:** every string *value* leaf in the artifact is rendered as its *type* only
  (`prompt: string`, `text: string`, `command: string`) — no prompt text, repository
  content, or check-run name left the run. Object **keys** are additionally filtered
  **fail-closed**: a key is emitted only if it looks like a schema identifier (≤64 chars,
  `^[A-Za-z_][A-Za-z0-9_.-]*$`); anything else becomes `<redacted-key>`. The observed schema
  puts nothing untrusted in key positions, but that schema is *not a contract*, so the boundary
  does not rely on it holding.

**What this settles.** The cloud harness already emits, with **zero agent cooperation**,
every variable PRFlow's telemetry currently depends on the agent to volunteer: per-message
tokens, wall-clock, the subagent dispatch roster, and denials. (Per-*phase* attribution is a
downstream derivation this record does **not** establish — see "What it does NOT settle"
below.) An agent-independent (class-(c)) cost floor is therefore **buildable on the cloud
tier** — the constraint was never the platform, it was that nobody had looked. (The **local**
tier is established separately, from the transcript's real per-message token counts — the AC7
observation below; `docs/internal/efficiency-trace.md` states the combined both-tiers conclusion.)

**What it does NOT settle.** The `execution_file` schema is not a public contract, so this
is a *dated observation of one action version*, not a specification — re-dispatch after any
`claude-code-action` upgrade rather than hard-coding these key names into a brittle parser.
And presence of a field is not proof that its values are complete or correctly attributed
per phase; a floor that consumes them must verify attribution separately.

**Stated limitation — single-event JSONL reads as `encoding: object`.** A JSONL file holding
exactly one event is byte-for-byte identical to a file holding one top-level object, so the two
are genuinely indistinguishable and both record `object`. This is an ambiguity in the *input*,
not a detector defect, and it is deliberately not papered over by guessing from a trailing
newline (both shapes may carry one). It is harmless to every conclusion here: the helper slurps
array / object / JSONL into the same array, so all five **field** determinations are identical
either way — only the `encoding:` label differs, and only for a degenerate one-event run no real
probe produces. `lib/test/run.sh` pins this behavior so it stays a known, asserted limitation.

### Stop-hook execution under `claude-code-action` (AC6)

**Observed: `FIRED`.** A `Stop` hook committed to the **base** branch's
`.claude/settings.json` **does** execute under `claude-code-action`. The probe hook
(`scripts/stop-hook-probe.sh`, registered as a `Stop` hook in `.claude/settings.json`)
landed on the default branch in PR #438; `claude-code-action` removes `.claude/` and
restores it from the **base** branch before running, and the `hook-probe` job's
`workflow_dispatch` run observed the hook's gitignored marker present after the action.

- **Probe run:** `29224205805` (the `hook-probe` job in `matcher-probe.yml`, `main`, 2026-07-13)
- **Observed:** `**FIRED**` — the base-branch `.claude/settings.json` `Stop` hook executed.
- **Observed on:** `anthropics/claude-code-action@v1`, 2026-07-13

This is a **dated observation of one action version**, not a platform contract: the fact
that base-registered `.claude/` hooks execute is an action behavior, not a guarantee —
re-dispatch `matcher-probe.yml` via `workflow_dispatch` after any `claude-code-action`
upgrade to re-confirm. Because the hook is now on base, an absent marker on a later run is
an **anomaly** (the hook could not write, or the session never reached `Stop`), not the
expected state — but a "did not fire" still must **not** be read as "hooks do not fire"
(the reverse launder).

**Security corollary — FIRED is not a consequence-free telemetry fact.** That base-registered
`Stop` hooks execute checked-out-tree scripts inside `claude-code-action` has a threat-model
implication addressed by **issue #458** (base-branch `.claude/settings.json` `Stop` hooks
exec PR-head scripts under `lib/`/`scripts/`, bypassing the #402 deny-floor). The hardening
now ships: `devflow-runner.yml`'s review job overwrites each Stop-hook target script with a
trusted base-ref copy (or a fail-closed no-op stub) via `scripts/harden-stop-hooks.sh` —
run only from a trusted source — **before** `claude-code-action` starts, so the PR-head copy
is never executed (the implement job is unaffected: it checks out the default branch, never a
PR head). See the "Stop-hook trusted-source floor" bullet in
[`DEVFLOW_SYSTEM_OVERVIEW.md`](DEVFLOW_SYSTEM_OVERVIEW.md). This record states the
observation; #458 owns the hardening.

The marker path is a **coupled contract**: `scripts/stop-hook-probe.sh` writes it and
`matcher-probe.yml`'s `hook-probe` job reads it. Renaming it on one side alone would not
fail loudly — it would turn the AC6 probe into a permanent, silent "did not fire".
`lib/test/run.sh` pins both sides to the same literal, and pins that the hook is actually
registered in `.claude/settings.json` (an unregistered hook observes nothing at all).

### Local-tier transcript token shape (AC7)

**Observed: `real` — the local transcript carries GENUINE per-message token counts.**

Established by running the shipped `scripts/stop-hook-probe.sh` against a real local Claude
Code transcript (2026-07-12, a real local Claude Code session):

```json
{ "fired": true, "token_shape": "real", "usage_blocks": 196,
  "max_usage_figure": 342272, "transcript_path_present": true }
```

196 `usage` blocks were present and the largest figure was 342,272 — far outside the
0/1 range that would mark streaming placeholders. **This contradicts the widely-reported
claim that transcript token counts are placeholders never backfilled to real values**, and
it is the first hard evidence against `docs/internal/efficiency-trace.md`'s long-standing assertion
that the token/wall-clock cost half is unreconstructable: on the local tier, it demonstrably
is reconstructable from the harness's own output, with no agent cooperation.

**Two limits on what this observation licenses, both deliberate:**

1. **It is the LOCAL tier only.** Whether `claude-code-action`'s `execution_file` carries the
   same figures is a *separate* question, answered separately — and it **is** answered: see
   the cloud row above, which the `execfile-shape-probe` observed as `present` for every
   field (run `29201071531`). This local row is evidence about the **transcript**, not about
   the execution file; do not cite one for the other.
2. **Realness is not freshness.** Claude Code's docs warn the transcript is written
   asynchronously and may lag the in-memory conversation, steering `Stop` hooks toward
   `last_assistant_message` instead of parsing it. This probe establishes that the counts
   are *real*, **not** that the final turn's counts have landed by the time a `Stop` hook
   reads them. A floor built on this must measure that lag separately — an under-count from
   a not-yet-flushed tail is a distinct failure mode this row does not clear.

---

## Notes on denied / unestablished results

- **A denied probe is not an observed-false result.** If the artifact upload, the hook
  probe, or a sandbox read is refused, that is recorded as denied/`unavailable` — it never
  becomes "the field is absent" or "hooks do not fire".
- **Re-runnability (AC9).** Both #437 probe jobs — `execfile-shape-probe` and `hook-probe` —
  are `workflow_dispatch`-runnable, so this record can be refreshed after a
  `claude-code-action` upgrade, matching the existing matcher-probe contract. (The AC7
  transcript check is **not** a workflow job: it needs a real local Claude Code `Stop`, so it
  is refreshed by re-running `scripts/stop-hook-probe.sh` locally, not by a dispatch. The
  file's other jobs belong to other issues — some predating #437 (`probe`,
  `schedulewakeup-probe`), some added after it (`implement-probe`, `cancel-probe`, and the
  issue-#812 `background-tasks-probe`). Several of those later jobs also derive their verdict
  from the execution file rather than from the model's text, so this record's shape
  observations are load-bearing beyond the two #437 jobs; each such job's recorded result
  lives with its own issue — the `background-tasks-probe` verdict in
  [`docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md`](DEVFLOW_SYSTEM_OVERVIEW.md)'s
  `prflow_implement.stall_backstop` bullet — not here.)

---

## Wave 1 verification-launch baseline (issue #527)

The offline verification-launch baseline analyzer
(`scripts/verification_baseline.py`) excludes cloud launch analysis in Wave 1
because no durable redacted execution-event source exists without changing
workflows — the `execution_file` shapes documented above are not a stable,
redacted, per-launch event source the analyzer can read offline. The analyzer's
cloud denominator instead comes from an explicit, immutable, metadata-only
Actions run/job census snapshot (`scripts/export-workflow-lifecycle-census.py`,
the sole networked step, explicit-invocation-only): workflow/job identity, run ID
and attempt, the run-level `created_at`, job-level started/completed timestamps,
and job-level conclusion and status (the run-level values are carried separately
as `run_started_at`/`run_conclusion`/`run_status` reference fields), plus a public
`html_url` (the job's when the API provides one, else the run's) — no transcript
text, tool input, stdout/stderr, or secrets. An absent or incomplete snapshot
makes cloud coverage `unavailable`, never zero. See
[`docs/internal/workflow-flight-recorder.md`](workflow-flight-recorder.md#verification-launch-baseline-wave-1).
