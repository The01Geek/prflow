<!-- SPDX-FileCopyrightText: 2026 Daniel Radman -->
<!-- SPDX-License-Identifier: MIT -->

# Review-engine per-context read cost (issue #1852)

`scripts/review-context-eval.py` is a maintainer-only instrument that measures what
*entering the review engine* cost a run, read from that run's saved Claude Code transcript
directory. It is the third of this repository's transcript-walking context instruments,
after `scripts/create-issue-context-eval.py` (issue #767, `docs/internal/create-issue-context.md`)
and `scripts/implement-context-eval.py` (issue #1209, `docs/internal/implement-context.md`),
and reuses their streaming / per-record-degradation / symlink-escape / determinism design.

This page is the single source of truth for what the instrument measures; it is not
paraphrased in `DEVFLOW_SYSTEM_OVERVIEW.md`, which only points here.

## It gates nothing

No skill, workflow, or suite gate invokes the instrument for a measurement or a threshold.
The only automated execution is its own focused unit test,
`lib/test/test_review_context_eval.py`. It reads transcripts and writes a report; it stores
nothing and changes no repository state. Nobody's review behavior changes when it runs.

## What it measures

Run it against a saved transcript directory:

```bash
scripts/review-context-eval.py <transcript-dir> [--format {text,json}]
```

An **engine file** is any file under `skills/review/` or `skills/review-and-fix/`, matched
by path subtree (not basename — both subtrees carry a `SKILL.md`) and normalized across the
absolute, repo-relative, and vendored (`.prflow/vendor/prflow/…`) spellings the same file
resolves at on different tiers.

A **context** is one conversation thread: a main-thread context (keyed by `sessionId`) or a
subagent context (keyed by `agentId`, one per dispatched subagent). This per-context
attribution is the instrument's one substantive difference from its implement sibling,
which filters subagent records out entirely. After issue #1850 the review engine's entries
are dispatched into subagent contexts, so an instrument that counted only main-thread reads
would report the engine cost went to zero rather than that it moved — this one attributes
each read to the context that made it, distinguishing a main-thread read from a subagent
read both per engine file and per context.

The report gives, for one supplied directory:

- the number of times each engine file was read (per file, split main-thread vs subagent);
- every engine-file read attributed to the context that made it, with the main-thread /
  subagent distinction;
- the peak accumulated context of each context that read an engine file — `max` over that
  context's turns of `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`
  (output excluded), or `unestablished` when no turn carried an established residency
  measurement (an unmeasured peak is never collapsed onto a real-looking 0). A turn
  establishes one when at least one of those three sub-fields holds a usable count, so a
  turn with no `usage` object, and one whose every residency sub-field is absent, null,
  non-numeric or non-finite, are both counted as unmeasured turns instead;
- an aggregate summary and a skip tally.

A directory with no engine-file read produces a report saying so and exits zero. A record
the parser cannot read is reported as a skipped record with its reason, and the run still
reports on the records it could parse. A path that escapes the supplied directory through a
symbolic link is never read. Re-running over the same unchanged directory produces
byte-identical output.

Regrowth in the review-engine surface becomes visible in these numbers rather than only in
the per-file byte ceiling in `lib/test/lint-reference-size.py`, which fires on one file at a
time and says nothing about what a single engine entry costs.
