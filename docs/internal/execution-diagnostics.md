# Execution diagnostics — surfaced fields and their redaction posture

`scripts/surface-execution-diagnostics.sh` reads a `claude-code-action` run's execution
file (the file named by `steps.claude.outputs.execution_file`) and surfaces a best-effort
diagnostics block to stdout, `$GITHUB_STEP_SUMMARY`, and `$GITHUB_OUTPUT`. It is a pure
read-only diagnostic: it never changes the calling step's pass/fail result and always
exits 0.

## Published values

Two scalars are value-published to `$GITHUB_OUTPUT` for downstream jobs to read:

- `permission_denials_count` — the reconciled count of permission denials (issue #363).
- `claude_code_version` — the CLI build the run executed on, read from the execution
  file's `{"type":"system","subtype":"init"}` record (issue #1528).

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
