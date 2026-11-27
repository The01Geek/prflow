<!-- prflow:spec-ref step=quality-group-regression file=skills/spec/references/quality-group-regression.md start -->
## Quality group — regression reproduction and input readers

### Defect reproduction

A defect report carries concrete reproduction facts: triggering input or steps, observed and
expected results, and relevant environment. Each observed and expected result a reporter of the
defect states is its own fact; someone else's explanation of a result is not a result.
`Current Behavior` keeps every such result, including one a premise correction, an explanation or
the user's scope answer addresses: a result a premise correction contradicts is kept as the
reporter's result, marked as reported, with the correction stated beside it; any other kept
result, including one a scope answer moves out of the issue, is stated as the reporter states it.

### Convention-governed matrices

This section applies only when the Testing Strategy enumerates an input-shape or case matrix for a
surface (a parser, a config consumer, a best-effort input handler); a matrix-free Testing Strategy
imposes nothing. Where a repo-published convention governs that surface's matrix, a silently
narrower list must never override the convention.

### New external-input readers

An issue that introduces a **reader of input the repo does not itself produce** — historical
records, user- or reporter-controlled text, an external structured format, agent- or human-mutable
markdown — writes into the Testing Strategy at least one fixture shaped like a real record of that
input, not only a hand-built well-formed one, and asks the implementing run to test the new reader
with it. Build the fixture from the parts of a record this run read, with private content replaced;
when this run read none, write a reconstruction labelled as a reconstruction. When the
recorded-input rule in `references/quality-group-rule-text.md` also applies to that record, that
rule decides which parts are quoted and how.

### Code reading model-written text

Code reading text a model writes (an agent's report, comment or record) reads by default only what
the producer's contract marks for machine reading — a marker line, a fenced JSON block, a JSON file,
or a heading, section or line shape the contract names as machine-read; a model reads the rest. A
criterion, Approach or Architecture Alignment making code parse any other layout of that text
(headings, section order, bullet shapes, or a count of them) is a **decision fork** — a model reads
it; the producer emits the value as a machine-read field; or code parses the layout — routed like
any new fork (`references/revision-delta.md`'s Revision rule). Skip the fork only when the user chose code parsing of that
layout itself; a user decision naming an output or value the layout would supply is not that choice.
<!-- prflow:spec-ref step=quality-group-regression file=skills/spec/references/quality-group-regression.md end -->
