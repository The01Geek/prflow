<!-- prflow:implement-ref step=4.0-4.0.5 file=skills/implement/references/deferred-filing.md start -->

### Deferred Filing

This reference owns both Phase 4 filing channels. Run only the channel selected by the phase stub, retain successful issue numbers in agent context, and perform one final human-readable workpad note after all selected filing completes. Helper records are shell-token records; parse them from the tool result, never through a shell capture.

| Channel | Units source | Idempotency key | Projection gate | Dependency registration | Search before create |
| --- | --- | --- | --- | --- | --- |
| Deferred AC | `deferral-drafter` plan paths | `marker_value` | required per draft | required per filed or adopted issue | only when the predicate is unestablished |
| Deferred review | persisted aggregate manifest | existing deterministic finding id | not applicable | not applicable | not applicable |

#### Shared rules

- Use the Write tool for JSON and Markdown scratch files. Do not compose files with shell output redirection.
- Substitute issue and PR numbers as decimal literals in helper calls.
- A helper refusal, silence, malformed record, or unknown outcome is a `dropped-failed` reflection, never a clean empty result.
- Neither filing channel runs, resolves, or aborts a merge.
- For each issue demonstrably filed or found by the guarded search, invoke the configured label helper exactly once:

  ```bash
  .prflow/vendor/prflow/scripts/apply-labels.sh <issue-number> --config-key .deferred.labels --config-fallback PRFlow,Deferred
  ```

  On `command not found`, `No such file or directory`, or exit 127 from that vendored literal, retry once through the portable anchor:

  ```bash
  "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/apply-labels.sh <issue-number> --config-key .deferred.labels --config-fallback PRFlow,Deferred
  ```

  `applied` and `nothing-to-apply` are clean. Record every other token or silence as `dropped-failed`; do not retry and do not add a second label call.

#### Deferred-AC channel

Dispatch one `prflow:deferral-drafter` with the predicate's projected criteria, the Phase 2.2.5 scope-decision note, issue-body cache or inline parent slots, `<run-scratch>`, spec template, and writing standard. Commit shared-checkout changes before dispatch, collect its completed return, and use its inline fallback only after a terminally unusable return.

The plan must provide, per draft, `chunk`, `draft_path`, `title`, `projection_disposition`, `unmatched_desired_behavior`, and a `covers_criteria` list whose every entry carries that criterion's `marker_value`, plus the plan-level `writing_standard_loaded`, `parent_slots_source`, and `notes`. The units.json `key` is derived from each `marker_value` at the template below, not supplied per draft. Record non-clean plan-level values once as `dropped-failed`. An unplaced criterion remains undischarged.

For each draft, use the Write tool to persist its projection tuple, then run:

```bash
.prflow/vendor/prflow/scripts/run-jq.sh -e -f .prflow/vendor/prflow/lib/projection-gate.jq <projection-json>
```

On `command not found`, `No such file or directory`, or exit 127 from that vendored literal, retry once through the portable anchor:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/run-jq.sh -e -f "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/projection-gate.jq <projection-json>
```

Only exit zero admits the draft. The shared filter also rejects a stream containing zero or multiple JSON documents. A refused/non-zero invocation, missing field, wrong type, inconsistent disposition, non-empty `unmatched_desired_behavior` JSON array, or non-singleton JSON stream is a failed tuple: omit it from filing, labeling, dependency registration, and `--mark-deferred-filed`; record its exact disposition and unmatched array as `dropped-failed`.

When the predicate was unestablished and exposed no trustworthy `filed:` set, search before filing each eligible draft:

```bash
gh issue list --state all --search "<parent-issue> in:body" --json number,title,body,url
```

Adopt only an exact result whose body identifies the parent and whose title/body contains the projected criterion; an unresolved or ambiguous search omits that unit and records `dropped-failed`. A unique match is treated as the criterion's issue and is not re-filed. When the predicate supplied trustworthy `filed:` markers, omit already-filed criteria without searching.

Use the Write tool to create one `units.json` array for every remaining eligible draft:

```json
[
  {"key": "<marker-value>", "title": "<title>", "body_file": "<draft-path>"}
]
```

Then invoke the only create boundary for this channel:

```bash
.prflow/vendor/prflow/scripts/file-deferrals.py --source-issue <issue-number> --pr <pr-number> --units <units-json>
```

On `command not found`, `No such file or directory`, or exit 127 from that vendored literal, retry once through the portable anchor:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/file-deferrals.py --source-issue <issue-number> --pr <pr-number> --units <units-json>
```

Read every `unit key=<key> number=<number> url=<url>` success record and the closing `filing result=all|partial|none` record. A `unit key=<key> cause=<cause>` row did not file and remains undischarged. `partial` records `dropped-failed` and continues with successes; `none`, an unknown result, or silence records `dropped-failed` and creates no success claim.

For each unique matched or newly filed AC issue, run the one shared label call above, then register its parent dependency exactly once:

```bash
.prflow/vendor/prflow/scripts/apply-issue-dependencies.py <issue-number>
```

On `command not found`, `No such file or directory`, or exit 127 from that vendored literal, retry once through the portable anchor:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/apply-issue-dependencies.py <issue-number>
```

The dependency helper's linked, already-blocked, skipped-outbound, and done breadcrumbs are clean. Record API failure, argument slip after one corrected invocation, or silence as `dropped-failed`. A criterion receives `--mark-deferred-filed "<marker-value>"` only when its issue number came from a success record or unique guarded-search match.

#### Deferred-review channel

Aggregate the run-scoped manifests through the deterministic discovery boundary:

```bash
.prflow/vendor/prflow/scripts/discover-deferral-manifests.py --aggregate --pr <pr-number>
```

On `command not found`, `No such file or directory`, or exit 127 from that vendored literal, retry once through the portable anchor:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/discover-deferral-manifests.py --aggregate --pr <pr-number>
```

Read its `aggregate discovery=complete|partial|degraded path=<path> [cause=<cause>] [failed=<JSON-array>]` record.

- `complete` — continue with the returned aggregate path.
- `partial` — require the helper's `failed=<JSON-array>` field, record `dropped-failed` naming those failed roots or manifests, then continue with the aggregate containing trusted survivors. A missing `failed` field is malformed output and takes the no-aggregate path below.
- `degraded` — record `dropped-failed`. The helper preserves a pre-existing aggregate byte-for-byte when no new input is trusted; if the returned path still names a readable non-empty aggregate, continue from that prior aggregate. Otherwise file nothing for this channel.
- silence, malformed output, or an unfamiliar state — record `dropped-failed` and file nothing.

File the selected aggregate through the existing manifest contract so successful entries receive their deterministic ids and `follow_up` objects:

```bash
.prflow/vendor/prflow/scripts/file-deferrals.py --source-issue <issue-number> --pr <pr-number> --manifest <aggregate-path>
```

On `command not found`, `No such file or directory`, or exit 127 from that vendored literal, retry once through the portable anchor:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/file-deferrals.py --source-issue <issue-number> --pr <pr-number> --manifest <aggregate-path>
```

Read successful issue numbers from stdout and filing diagnostics from stderr. A partial result that reports entries `were dropped from manifest` records `dropped-failed` with the failed files and continues with successful numbers. The all-foreclosed exit-0 arm is a clean zero-number result because the aggregate rewrite is its deliverable. An already-hydrated idempotent result is a clean no-op; any other non-zero, silence, or unrecognised output records `dropped-failed`.

Invoke the shared label call once for each newly filed review issue. Review findings do not receive AC markers or parent-dependency registration.

#### Final durable record

After both selected channels finish, make one `workpad.py update` call containing exactly one human-readable `--note` that lists the AC and review issue numbers, and one `--mark-deferred-filed` operand per successfully backed AC marker. Omit empty groups from the note; if no issue was filed or adopted and no marker is discharged, make no success-note write. Reflections required above remain separate failure evidence and do not replace this one success note.

<!-- prflow:implement-ref step=4.0-4.0.5 file=skills/implement/references/deferred-filing.md end -->
