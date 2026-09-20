---
title: "Observability and Privacy"
description: "Configure diagnostics, transcript artifacts, denied-command records and telemetry storage."
---

Balance useful cloud-run diagnostics against the sensitivity of prompts, repository content and command text.

| **Setting** | **Type and accepted values** | **Fallback or scaffold** | **Tier and privacy note** | **Example** |
| --- | --- | --- | --- | --- |
| `prflow.execution_diagnostics_enabled` | Boolean | `true` | Cloud model jobs. Prints summary and denial detail to logs and the job summary. It uploads no artifact and does not change pass or fail. | `"execution_diagnostics_enabled": true` |
| `prflow.execution_transcript_artifact_enabled` | Boolean | Runtime and scaffold: `false` | Cloud model jobs. When true, uploads a scrubbed transcript artifact with seven-day retention. Treat it as sensitive. | `"execution_transcript_artifact_enabled": false` |
| `prflow.execution_transcript_job_log_enabled` | Boolean | Runtime and scaffold: `false` | Cloud implement jobs. When true, every agent message is written into the job log as it happens, **unscrubbed**, so a run whose runner dies abruptly can still yield a transcript. The log can include credentials, such as refreshed GitHub App tokens, which are not masked, and anyone who can read the run logs can read them. PRFlow therefore applies this setting only when GitHub reports the repository as private: in a public repository, or when the visibility is not reported, the run leaves streaming off and logs a warning that says why. The log grows to the transcript’s size. The rebuilt transcript artifact also needs `execution_transcript_artifact_enabled`: with only this key on, content is streamed to the log and no artifact is produced. | `"execution_transcript_job_log_enabled": false` |
| `prflow.execution_denial_commands_enabled` | Boolean | `true` | Cloud model jobs. Controls durable scrubbed command text only. Denial count and tool names remain available when a record can be built. | `"execution_denial_commands_enabled": false` |
| `prflow_review_and_fix.efficiency_telemetry_enabled` | Boolean | `true` | Local and cloud review-and-fix. False also prevents denied-command records from being persisted on the telemetry branch. | `"efficiency_telemetry_enabled": true` |
| `telemetry.enabled` | Boolean | `true` | Master quiet switch. Set to the JSON boolean `false` to turn off the five enrolled telemetry mechanisms at once, plus the workpad-copy push to the telemetry branch; `execution_transcript_artifact_enabled` is not enrolled. Only the boolean `false` disables; every other value leaves telemetry on. A key you have set to a real value wins over this master for those five, while the branch push reads the master alone. | `"enabled": false` |
| `telemetry.branch` | String branch name | `prflow-telemetry` | Writable runs persist observability records to this long-lived orphan branch. Exclude it from broad push-triggered CI. If you upgrade from a version that used the older `devflow-telemetry` branch, PRFlow moves those records onto this branch for you — once when you run `/prflow:init` (or `install.sh --apply`), and otherwise on your next writable run — so your full cost-and-effectiveness history stays visible; setting this key back to `devflow-telemetry` keeps the old name and skips that move. | `"branch": "prflow-telemetry"` |

## Know What Persists

- Execution diagnostics are enabled by default. They remain in Actions logs and the job summary.
- Full transcript artifacts are disabled by default, and so is streaming the transcript into the
  job log. The artifact is scrubbed and expires; the job log is neither.
- When a run is cancelled or interrupted before the model step writes its execution file, the transcript artifact instead holds the CLI's own session files for that run. Those files carry more than the action's message stream — tool results, attachments and file-history snapshots — so the artifact is larger and the incomplete-blocklist caveat below applies to it in full; treat it as sensitive.
- Scrubbed denied-command text is enabled by default and can persist on the telemetry branch.
- Denial count and tool identifiers are not controlled by the command-text toggle.
- Effectiveness records are enabled by default.

The transcript and command scrubber is an incomplete blocklist. It redacts these credential families: GitHub tokens/PATs, Anthropic keys, Bearer Authorization headers, basic Authorization headers, AWS access key IDs, npm tokens, Slack tokens, GitLab tokens, connection-string passwords, `Password=`/`Pwd=` values, and PEM private keys. The Authorization scheme keyword is matched whatever its casing, and an Authorization value shorter than four characters is left alone, so a literal command such as `sed 's/AUTHORIZATION: basic //'` is not mistaken for a credential.

Some credential shapes are not recognized. Unprefixed secrets have no distinguishing prefix to match — an AWS secret access key and an Azure DevOps personal access token are examples that pass through. Private-key body lines that follow the header line in raw multi-line text are not recognized either: only the `-----BEGIN … PRIVATE KEY-----` header line is redacted there. A `Password=`/`Pwd=` value ends at an escaped quote, so when the password itself contains one only the part before it is redacted and the rest of the value stays in the text. Other credential shapes can remain.

The scrub replaces each matched credential span in place with a `[REDACTED-…]` marker and leaves the surrounding non-credential text untouched — a private key is redacted only through its matching `-----END … PRIVATE KEY-----` marker, so anything after it survives; the scrub never empties a thinking block. A scrub failure prevents the affected text from being uploaded or persisted.

<Warning>
  A successful scrub does not prove that output is secret-free. Transcript artifacts and denied-command records go through the scrubber, but Actions diagnostics can still contain truncated tool input. Treat those logs as sensitive.
</Warning>

## Who Can Download a Transcript, and For How Long

Downloading a transcript artifact needs read access to the repository: "Read access to the repository is required" ([Downloading workflow artifacts](https://docs.github.com/en/actions/managing-workflow-runs-and-deployments/managing-workflow-runs/downloading-workflow-artifacts), checked 2026-09-16). A public repository is accessible to everyone on the internet: "Public repositories are accessible to everyone on the internet." ([About repositories](https://docs.github.com/en/repositories/creating-and-managing-repositories/about-repositories), checked 2026-09-16).

The engine workflows request seven-day retention for the transcript artifact. "The `retention-days` value cannot exceed the retention limit set by the repository, organization, or enterprise." ([Storing and sharing data from a workflow](https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/storing-and-sharing-data-from-a-workflow), checked 2026-09-16).

## What a Run Record Contains

`prflow_review_and_fix.efficiency_telemetry_enabled` is on by default, so a review-and-fix run writes one record per run to the telemetry branch. Read this before you decide whether to keep it.

One record is a single JSON file. It holds:

- **Which run it was.** A record format version, the repository slug and the time the record was written. The file name carries the run identifier.
- **How the run was configured.** A hash of your review settings, so two runs can be compared, plus three values recorded in the clear: the verdict threshold, the fix threshold and the iteration limit.
- **One entry per fix-loop iteration.** How many review agents ran. Flags describing the shape of the change, such as whether the diff was small, config only or added new types. How the verification checklist was handled and how it split between cheap direct checks and dispatched agents. How many fixes were applied, and whether the iteration applied none at all. Each agent's verdict and whether it led to a fix. The model effort each agent asked for and got.
- **Cost figures.** Calls, token counts and wall-clock time, per phase and per iteration. A cloud run can also carry a whole-job summary: cost in dollars, tokens, usage per model, number of turns and total duration.

The record holds counts, flags, identifiers and settings. It does not hold your source code, your diff, prompt text or the wording of any finding.

<Warning>
  The record is not the only thing stored. Each run also copies its workpad to the same branch, and a workpad contains the run's own written notes about the work: what it planned, what it changed and what it deferred. Scrubbed denied-command text can be stored there too. Anyone who can read the repository can read that branch.
</Warning>

A run with no readable iterations writes no record at all rather than an empty one. Set `efficiency_telemetry_enabled` to false to stop writing records entirely.

## One-Switch Quiet Mode

If you want a private, low-noise setup without hunting down each individual key, set one master switch:

```json
{
  "telemetry": {
    "enabled": false
  }
}
```

With `telemetry.enabled` set to the JSON boolean `false`, the enrolled telemetry mechanisms turn off in one place: the efficiency trace, execution diagnostics, durable scrubbed denied-command text, the live review progress comment and the created-issue investigation record all resolve to disabled wherever their own key does not resolve to a value — you have not set it, or you set it to `null` or an empty string, and the workpad-copy push to the `prflow-telemetry` branch is skipped — so quiet runs write nothing to that branch.

Neither `execution_transcript_artifact_enabled` nor `execution_transcript_job_log_enabled` is enrolled, because both already default to `false`; if you turned one on, it stays on until you turn it off yourself.

A few things to know:

- **Only the boolean `false` disables.** Every other value — the string `"false"`, `0`, `null`, a wrong type, a missing key or an unreadable config — leaves telemetry **on**. This fail-safe direction is deliberate: a malformed config never silently drops your observability.
- **A key you set to a real value always wins for the five sub-keys.** If you set one of them (for example `prflow.execution_diagnostics_enabled`) to `true` or `false` it overrides the master, in both directions — so you can turn the master off but keep that mechanism on, or leave the master on and turn it off. The `prflow-telemetry` branch push is the exception: it reads the master alone, so a master `false` skips it even when `efficiency_telemetry_enabled` is explicitly `true`.
- **The value is ergonomics and privacy, not cost.** Turning telemetry off saves only a small amount of run time; the point is fewer GitHub writes, no telemetry branch and no stored records.
- **Rollback is removing the key**, which restores every default. Mixed plugin versions are safe: a repository whose vendored PRFlow copy predates this key simply ignores it and keeps telemetry on until the next upgrade.

## Choose Your Settings

Use repository access controls and artifact retention as part of the privacy decision. Set both text-bearing options to false when even scrubbed prompt or command content is unacceptable:

```json
{
  "prflow": {
    "execution_diagnostics_enabled": true,
    "execution_transcript_artifact_enabled": false,
    "execution_transcript_job_log_enabled": false,
    "execution_denial_commands_enabled": false
  },
  "prflow_review_and_fix": {
    "efficiency_telemetry_enabled": true
  },
  "telemetry": {
    "branch": "prflow-telemetry"
  }
}
```

Expected result: runs still print diagnostics to the Actions log, no transcript artifact is uploaded, no scrubbed command text is stored durably and effectiveness records keep going to the `prflow-telemetry` branch.

Disabling denied-command text does not disable ordinary log diagnostics. Disable `execution_diagnostics_enabled` separately for quieter logs.
