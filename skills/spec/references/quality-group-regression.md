<!-- prflow:spec-ref step=quality-group-regression file=skills/spec/references/quality-group-regression.md start -->
## Quality group — regression reproduction and specialized test matrices

### Defect reproduction

A defect report carries concrete reproduction facts: triggering input or steps, observed and
expected results, and relevant environment. Its Testing Strategy explains how the fix will be
distinguished from the failure, preferably with a focused regression test against the actual
implementation. Reuse existing coverage or a direct reproduction where sufficient; missing evidence
is an explicit limit, not an invented result. Honor repository testing requirements and agreed
criteria.

### Convention-governed matrices

A Testing Strategy enumerating a case matrix for a convention-governed surface carries the full
matrix (or a named, justified narrowing) and its `governing conventions consulted:` line. This
applies only when the Testing Strategy enumerates an input-shape or case matrix for a surface (a
parser, a config consumer, a best-effort input handler); a matrix-free Testing Strategy imposes
nothing. When it does, and a repo-published convention already governs that surface's matrix, the
issue either enumerates the **full convention matrix** or states the
**narrowing explicitly with its justification** — a silently narrower list must never override the
convention — and carries the one-line record
`governing conventions consulted: <sources cited by path, or "none found; searched <the bounded list>">`.
The search is **bounded to a named list** — `CLAUDE.md`, `CONTRIBUTING.md`, and testing guidance
under the repo's configured internal-docs path — with the **consumer skill extension** as the
override point naming where that repo's conventions live; cite sources by path when found. The
record is a **claim to verify, not an attestation to accept**: the Step 3.6 auditor re-runs the
search and flags the line when a governing matrix sits at a path the line omits —
**except on Step 3.6's degraded inline arm, where no auditor re-runs it and the record is attestation-only**,
which that arm's mandatory `degraded` audit-summary marker already signals.

### New external-input readers

This matrix rule also fires on introduction, not only on narrowing: an issue that introduces a
**reader of input the repo does not itself produce** — historical records, user- or
reporter-controlled text, an external structured format, agent- or human-mutable markdown —
**enumerates the malformed / boundary shape matrix of the parts code reads in the Testing Strategy**,
appropriate to the input's type, including **at least one production-realistic fixture** (a real
captured record, not only a hand-built well-formed token); a narrower enumeration states its
**justification**, and a **blanket testing-scope waiver** ("this artifact has no desk test") is
**non-conforming** — a conforming one states what **inside the exempted artifact remains governed**.

### Code reading model-written text

Code reading text a model writes (an agent's report, comment or record) reads by default only what
the producer's contract marks for machine reading — a marker line, a fenced JSON block, a JSON file,
or a heading, section or line shape the contract names as machine-read; a model reads the rest. A
criterion, Approach or Architecture Alignment making code parse any other layout of that text
(headings, section order, bullet shapes, or a count of them) is a **decision fork** — a model reads
it; the producer emits the value as a machine-read field; or code parses the layout — routed like
any new fork (`references/revision-delta.md`'s Revision rule); a run with no user never self-answers
it and records it in `## 🚫 Blocked`. Skip the fork only when the user chose code parsing of that
layout itself; a user decision naming an output or value the layout would supply is not that choice.
The corresponding Testing Strategy residual case is the **new mutable-input-reader matrix** carrying
its `governing conventions consulted:` record.
<!-- prflow:spec-ref step=quality-group-regression file=skills/spec/references/quality-group-regression.md end -->
