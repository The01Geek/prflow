---
title: "Documentation"
description: "Keep developer docs, public docs and release notes in step with the code."
---

Use this guide to pick the PRFlow documentation command that matches what you need.

PRFlow has seven documentation commands. One is a router that runs three of the others in sequence; the rest do one job each. Every command except `/prflow:docs-verify` can edit files (it writes only a report file you ask for), and none of them commits.

## Pick a Command

| Your need | Command |
| --- | --- |
| A general documentation pass before merge | `/prflow:docs` |
| Update developer docs for code you changed | `/prflow:docs-sync-internal` |
| Bring public docs in line with what shipped | `/prflow:docs-sync-external` |
| Check one topic's docs against the code, with no file changes | `/prflow:docs-verify <topic>` |
| Build developer docs from nothing | `/prflow:docs-bootstrap-internal` |
| Build public docs from the developer docs | `/prflow:docs-bootstrap-external` |
| Add a release note for a customer-visible change | `/prflow:docs-release-notes` |

<Note>
  Use a **sync** command when the documentation tree already exists. Use a **bootstrap** command when it is absent, empty or needs a full rebuild.
</Note>

## Run the Complete Pass

<Steps>
  <Step title="Run it on the branch you are about to merge">
    ```text
    /prflow:docs
    ```
  </Step>
  <Step title="Watch three steps run in order">
    Internal developer docs first, then external docs aligned against them, then release notes. Steps one and two are each switched on or off by configuration; step three is always evaluated and does nothing when your repository has no release-notes artifacts.
  </Step>
  <Step title="Read the final summary and commit yourself">
    `/prflow:docs` does not commit. That is left to you, or to the [implement](/docs/workflows/implement) run that called it.
  </Step>
</Steps>

### What the Final Summary Says

Each step ends in exactly one of four outcomes, and the summary names one per step:

| Outcome | Meaning |
| --- | --- |
| completed | The step ran to its own completion. |
| skipped | Switched off by configuration. |
| failed | The step errored. |
| unestablished | Whether the step should run could not be determined. |

The summary also lists the internal files added or edited, the public-doc impact list carried forward from step one, the external files added or edited and whether a release note was added or skipped, with the reason.

<Warning>
  A failed or unestablished step is reported as itself, never rolled up into a clean pass. If a configuration read was refused rather than answered, the summary says `unestablished` and the step still runs, because the switches default to on. Read the summary; do not assume a run that finished did everything.
</Warning>

## The Two Switches

| Setting | Default | Effect when `false` |
| --- | --- | --- |
| `docs.internal_enabled` | `true` | `/prflow:docs` skips the internal-docs step. |
| `docs.external_enabled` | `true` | `/prflow:docs` skips the external-docs alignment step. |

Both affect the combined pass only. Running `/prflow:docs-sync-internal` or `/prflow:docs-sync-external` directly ignores them.

The locations themselves come from `docs.internal` (default `docs/internal/`) and `docs.external` (default `docs/external/`). See [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives).

## External Docs Need an Internal Source

`/prflow:docs-bootstrap-external` generates public documentation from your internal documentation. If the internal location is empty or absent, it stops and tells you to run `/prflow:docs-bootstrap-internal` first.

<Note>
  This refusal is deliberate. Without an internal source of truth, generated public guidance would be invented rather than derived, and a confidently wrong public doc is worse than a missing one.
</Note>

## Verify One Topic Without Changing Files

<Steps>
  <Step title="Name the topic">
    ```text
    /prflow:docs-verify retry handling
    ```
  </Step>
  <Step title="Read the report">
    Nothing is edited, committed or pushed. The working tree is unchanged when the run finishes, apart from the report file when you ask for one (see below).
  </Step>
</Steps>

The report names four fields:

- **Doc verdict and location** — one of `RELIABLE`, `UNRELIABLE` or `ABSENT`, together with the resolved internal-doc location. This is a spot-check of the inspected internal claims, not a verdict on external docs or source comments. It is returned by default and under `--lead docs`; a `--lead code` run omits it.
- **Relevant files** — a compact map to the implementing paths, guards, writers and consumers.
- **Current behavior** — what the code actually does today, including the failure paths and non-obvious couplings you would otherwise find the hard way.
- **Not established** — material unresolved relationships or claims, why they remain unresolved and what decision each could affect. It also includes an extension-load failure; `none` when nothing qualifies.

You can steer where the run starts. `--lead docs` reads the internal documentation before turning to the code; `--lead code` starts from the code and treats documentation as supporting evidence. With no `--lead`, the run reads documentation then code and returns the doc verdict.

To keep the report as a file instead of chat text, add `--report-file` with a path under `.prflow/tmp/`, written relative (as below) or absolute. The run writes the report there, makes no other change and replies with the path alone. If it cannot write the file, it says so and returns the whole report as text.

```text
/prflow:docs-verify --report-file .prflow/tmp/retry-report.md retry handling
```

The run refuses to start when `--report-file` is given without a path or more than once, or when the path contains a `..` segment or does not resolve inside the working directory's `.prflow/tmp/`.

<Tip>
  `ABSENT` means no internal document covers the topic. If the documentation location itself could not be read, the run says so instead — an absence it could not establish is not an established absence.
</Tip>

[Create an Issue](/docs/workflows/spec) runs this discovery with `--lead docs` alongside an independent investigator of request-specific assumptions, constraints and conditional risks before drafting a ticket.

To fix the internal documentation a report found wrong, edit it yourself, or run `/prflow:docs-sync-internal` when the drift comes from your branch's changes.

## Related Articles

- [Implement an Issue](/docs/workflows/implement)
- [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives)
- [Command Reference](/docs/reference/command-reference)
