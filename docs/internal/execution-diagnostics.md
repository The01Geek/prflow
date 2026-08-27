# Execution diagnostics — surfaced fields and their redaction posture

`scripts/surface-execution-diagnostics.sh` reads a `claude-code-action` run's execution
file (the file named by `steps.claude.outputs.execution_file`) and surfaces a best-effort
diagnostics block to stdout, `$GITHUB_STEP_SUMMARY`, and `$GITHUB_OUTPUT`. It is a pure
read-only diagnostic: it never changes the calling step's pass/fail result and always
exits 0.

## Published values

Two scalars are value-published to `$GITHUB_OUTPUT`:

- `permission_denials_count` — the reconciled count of permission denials (issue #363).
  `devflow-runner.yml` re-exposes it as a job output for downstream jobs to read.
  See "Count resolution" below for how the value is measured versus left `unavailable`.
- `claude_code_version` — the CLI build the run executed on, read from the execution
  file's `{"type":"system","subtype":"init"}` record (issue #1528). No workflow maps it
  to a job output today; its only reader is the in-job `::notice::` below. Add a job-output
  mapping when a cross-job consumer actually exists, not before.

`claude_code_version` is resolved by reusing `lib/probe-observation.sh`'s
`devflow_probe_cli_version` rather than a second extraction `jq`, so the extraction, the
three-state `unavailable` discipline, and the fail-closed version-alphabet sanitization
live in one place. It is read in-job on every live run — no dependency on the 7-day
transcript artifact or the `prflow.execution_transcript_artifact_enabled` opt-in — and an
in-job `::notice::` names the resolved version so the run records the build it ran on. The
version lives in the `system/init` record independent of the `result` event, so an
incomplete run (an init record but no result event — the stalled-run case this diagnostic
exists to illuminate) still publishes and renders it.

An absent or unreadable init record resolves to the literal `unavailable` — never an empty
or zero value. A `$GITHUB_OUTPUT` write failure leaves a stderr breadcrumb rather than a
silent empty output, mirroring the sibling `permission_denials_count` channel.

### The read-back-from-block invariant

Both `_publish_denials` and `_publish_claude_code_version` read the value they publish back
out of the *already-rendered* diagnostics block (parsing the `- <label>: <value>` line with
bash builtins only — `sed`/`head`/`grep`/`awk`/`cut`/`tr` are not preflight-guaranteed and
would fail-open to an empty value on a host lacking one) rather than re-deriving it. This
keeps the human-readable line and the machine-readable output from ever disagreeing: the
rendered block is the single source of truth for both sinks.

## Count resolution

`permission_denials_count` is reconciled from two carriers the execution file's `result`
event may hold: a `permission_denials_count` scalar (a number or a digit string) and a
`permission_denials` array of denial objects. The count is the larger of the reported scalar
(when present) and the length of the gathered, deduped, object-typed denial entries.

**The presence of a `permission_denials` array is itself a measurement (issue #2064).** When
any `permission_denials` value in the slurped input is an array, the gathered denial-object
length is the count — so an array that is present but empty, or holds only non-object entries,
yields a measured **`0`**, not `unavailable`. The array-presence signal is read independently
of the object-type filter that collects denial detail, because that filter drops non-object
entries while the array's mere presence still counts as a measurement. This matters on
claude-code CLI 2.1.247, whose `result` event carries a `permission_denials` array (empty on a
clean run) and **no** `permission_denials_count` field; before the fix such a run fell through
to `unavailable`, mis-reporting a measured zero.

**`unavailable` survives only for the neither-carrier case** — a file carrying no
`permission_denials_count` field and no `permission_denials` array anywhere. Per the repo's
**unknown-is-not-zero** rule, that sentinel is never collapsed onto `0`: a downstream consumer
(the no-verdict `::error::` clause, the installed review tier's denial clause) must be able to
tell "the harness refused nothing" from "the count could not be established".

**Shape-drift warning.** When a `result` event is present but the count still resolves to
unknown (neither carrier found), each extractor emits one warning breadcrumb — a
`::warning::` annotation whose text is `execution-file shape drift suspected …` from
`surface-execution-diagnostics.sh` and a `devflow: build-denial-record.sh: execution-file
shape drift suspected …` line from `build-denial-record.sh` — so the next execution-file shape
change announces itself instead of degrading silently to `unavailable`. The two wordings are
deliberately distinct (and distinct from the positive-denial `this run recorded N permission
denial(s)` warning the suite greps for) so each extractor's warning is asserted independently.
No warning fires when the count resolved to `0` or to a positive number.

**Job-output mapping (issue #2064).** `devflow-runner.yml` maps the step output to its job
output with the string-equality form
`steps.diagnostics.outputs.permission_denials_count == '' && 'unavailable' || …`, which
resolves `unavailable` only when the diagnostics step published nothing (empty string) and
otherwise passes the published value through verbatim — so a measured `0` survives to
consumers. The older `|| 'unavailable'` truthiness form would have depended on GitHub Actions'
underdocumented coercion of the string `0`.

## Redaction posture

The `system/init` record also carries `tools`, `agents`, `skills`, `plugins`,
`mcp_servers`, `model`, `permissionMode`, `capabilities`, and `slash_commands`. Among the
init fields, **only** `claude_code_version` — a low-sensitivity version scalar — is
value-published here. The others stay type-only behind `scripts/extract-execution-shape.sh`'s
redaction boundary, which is unchanged: a resolved `tools` list can carry consumer-specific
paths from `.prflow.allowed_tools`, and the job log is public on a public repository, so
their *values* are never emitted — `extract-execution-shape.sh` renders each object's
immediate keys and value *types* only. Do not value-publish another init field from
`surface-execution-diagnostics.sh` without re-weighing that boundary.
