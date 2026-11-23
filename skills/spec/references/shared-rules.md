<!-- prflow:spec-ref step=shared-rules file=skills/spec/references/shared-rules.md start -->

# Shared rules

The orchestrator and the workers both apply these.

## Ask budget

A fork is a **Decision**, asked of the user, only when (a) the request, the established facts and
the repository's own instructions do not settle it, and (b) it changes scope, user-visible
behavior, what happens to stored data, or a risk the user would want to weigh. Excluding a case the
request asks for or dropping a condition it states, widening an existing open issue rather than
filing new, and a choice between
approaches that differ in any of those always meet (b). Every other fork an implementer could not
simply decide while building is a **Default**: it takes the simplest option consistent with the
request and the repository's rules (an existing mechanism reused, a default kept, nothing added),
unasked, and is listed for the user to overrule.

A run's choice rests on a hand-back's Default, an established fact, or the simplest option where
a rule of this skill has the run take it, never on an invented fact; an investigator's Default
stands over the orchestrator's own reading unless a quoted fact contradicts it. A fact about the
system or its data that nobody established is stated `not established` in the draft, with what
the implementer must establish, and asked only when it meets (b).

## Relied-on limit

A risk or limit established with source lines that bears on what a requirement, the requested
change or an offered option would be relied on for: an access or permission boundary, the
integrity or fate of stored data, or a guarantee the request or the issue states or implies. It
holds when the code behind it is out of scope.

## Run-time behavior

What something does when it runs (what a caller receives from a function, request, command, job,
build or release step, on which inputs and in which environments) is established only by a full
trace or a permitted local run, as the worker rules define them. Anything else is
`not established`, stated with the level that is established; nobody states what an untraced
layer does.

## Ground hand-back

A ground investigator hands back, in at most about 40 lines:

- `report: <path>` and the number of entries in that report's `## Exact surfaces` section;
- **Facts**, one line each: the fact, then the file and line range read, or
  `not established — <why>` with the established level;
- **Limits**, one line per relied-on limit, or `none`;
- **Decisions** and **Defaults**, or `none`;
- **Repository rules**, from the ground asked for that list;
- `quality groups:` the quality groups its ground triggers, or `none`;
- `out of ground:` one-line notes of what belongs to another ground, or `none`;
- `problems:` each thing it could not read, load, write or run, a tool call refused or
  interrupted and not completed included, or `none`.

Limits and the rules list do not count toward the cap, and a report carried in the hand-back
because its write failed is carried whole.

## Never deleted by the leanness pass

Anything the request, a user decision or a run's choice asks the issue to carry; a `## Dependencies` or
`## 🚫 Blocked` line; a criterion that alone carries a Desired Behavior obligation or a case the
change knowingly leaves uncovered; a statement that something is not established; a relied-on
limit, or any sentence saying what a requirement does not guarantee or what a reader must not rely
on it for; a section heading; the last, italic provenance line.

<!-- prflow:spec-ref step=shared-rules file=skills/spec/references/shared-rules.md end -->
