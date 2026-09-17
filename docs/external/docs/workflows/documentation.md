---
title: "Documentation"
description: "Keep developer docs, public docs and release notes in step with the code."
---

Use this guide to pick the PRFlow documentation command that matches what you need.

PRFlow has seven documentation commands. One is a router that runs three of the others in sequence; the rest do one job each. Every command except the report-only mode described below can edit files, and none of them commits.

## Pick a Command

| Your need | Command |
| --- | --- |
| A general documentation pass before merge | `/prflow:docs` |
| Update developer docs for code you changed | `/prflow:docs-sync-internal` |
| Bring public docs in line with what shipped | `/prflow:docs-sync-external` |
| Check and fix the docs for one topic | `/prflow:docs-verify <topic>` |
| Understand one topic, with no file changes | `/prflow:docs-verify --report-only <topic>` |
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
    /prflow:docs-verify --report-only retry handling
    ```
  </Step>
  <Step title="Read the report">
    Nothing is edited, committed or pushed. The working tree is unchanged when the run finishes.
  </Step>
</Steps>

The report is compact — kept under 1,000 words — and names four fields:

- **Doc verdict and location** — one of `RELIABLE`, `UNRELIABLE` or `ABSENT`, together with the internal-doc location the run resolved. It describes the internal documentation only, a wrong default in a schema or a stale code comment being reported under current behavior instead. It is returned by default and under `--lead docs`; a `--lead code` run does not return it.
- **Relevant files** — the files that implement the topic, marked to show the minimum set someone must read, with file and line references for the entry points, guards and writers.
- **Current behavior** — what the code actually does today, including the failure paths and non-obvious couplings you would otherwise find the hard way.
- **Duty statuses** — what the run established and what it did not, with a one-clause reason for each duty it could not establish.

You can steer where the run starts. `--lead docs` reads the internal documentation first (from its index) before turning to the code; `--lead code` starts from the code and treats documentation as supporting evidence. With no `--lead`, the run reads documentation then code and returns the doc verdict.

<Tip>
  `ABSENT` means no internal document covers the topic. If the documentation location itself could not be read, the run says so instead — an absence it could not establish is not an established absence.
</Tip>

[Create an Issue](/docs/workflows/spec) uses this same report-only mode to understand a topic before drafting a ticket: it dispatches two of these runs at once, one led by the docs and one led by the code.

Drop `--report-only` and the same command fixes the internal documentation it found wrong.

## Related Articles

- [Implement an Issue](/docs/workflows/implement)
- [Documentation and Retrospectives](/docs/configuration/documentation-and-retrospectives)
- [Command Reference](/docs/reference/command-reference)
