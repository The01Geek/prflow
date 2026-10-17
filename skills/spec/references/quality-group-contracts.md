<!-- prflow:spec-ref step=quality-group-contracts file=skills/spec/references/quality-group-contracts.md start -->
## Quality group — quantitative and closed-set contracts

### Quantitative criteria

A quantitative AC names its measurement instrument. When an AC expresses a number — a word, byte, or
line ceiling, a count, a coverage threshold, or a percentage tolerance — state the exact command or
counting rule that produces the measured value. Name the counter, not merely the unit; for example,
specify Python `str.split()` over the UTF-8 contents of the files named by the AC, summed once per
file. If the command or rule cannot be established, record `unestablished` for that criterion and do
not publish an unnamed counter as an accepted quantitative AC. A size or limit criterion the base
already breaks is non-conforming tree-wide ("every shipped file", "all references"), because an
untouched or exempted file already over the limit makes it false before the change: scope it to the
files the change adds or edits, and give any of those, or a summed budget, already over the limit a
"does not grow" criterion instead; a limit the base meets, or one the change introduces, may stay
tree-wide.

### Value comparisons

A value-comparison AC states its comparison in the words the producing surface emits. When an AC or
Testing-Strategy assertion compares a produced value with a literal or with another run's output,
phrase it in the terms that surface emits, grounded one of two ways; a run-to-run comparison also
names the other run and the input both runs take. **(a) The verified arm** — a drafting-time probe
cited in the issue that exercises the **boundary fixtures the comparison distinguishes** (for a
type-sensitive comparison, a JSON string `"true"` against a boolean `true`); a probe silent on that
axis does not ground it. **(b) The obligation arm** — a named implementer obligation stating the
**decided semantics** or the **exact fixture-and-output command** the implementer runs, not a bare
"establish the semantics." For a *probeable* fact, a drafter whose direct probe is classifier-denied
first tries the local-tier fallbacks (`python3 <path>` / `jq`); only when those also fail is the
obligation arm allowed. When the axis is a specification *choice*, it is a Step 2 decision fork
resolved with the user, not an obligation. **Adjective-only language** ("explicit `true`", "reads as
exactly `true`") without that grounding is **non-conforming**, including when a probe is present but
silent on the axis.

**Obligation execution tier.** Obligation arms are implement-tier verification commands (this
governs this AC and the Step 3.5 unstated-mechanism-dependency hunt alike): an obligation that
requires *running* an in-repo command must name one already granted on the consuming tier (the
repo's test/lint commands in `prflow_implement.allowed_tools`), or be a
**code-reading obligation citing the producer code** — not a run-this-ungranted-helper AC. Two
further obligation forms name work for the implementer rather than a drafting-time probe — adding a
capability, and establishing whether one exists — each routed by the existence-determination rule
whose single home is Step 3.5's item 4 (`skills/spec/references/step-3-5-self-audit.md`). This
constraint governs whatever in-repo command their discharge names.

### Universal claims

Every universal quantifier the body asserts about the system under change is grounded, or it does
not ship. A universal claim is any claim about every member of a set, found by what it asserts:
"never", "always", "each", "every", "all", "cannot", "only", "nothing else", "the same" and
"unchanged" are common forms, not the test. Each one asserted about the system under change anywhere
outside `## 🚫 Blocked` is grounded one of four decided ways: **(a) pinned** — a named AC or
assertion covers each arm, element and mode it ranges over, except a set a criterion points at under
**Enumeration closure** below and a set of sites (the template's *Brief / investigation-record
routing*) a property criterion covers, which counts as stated, named and pinned for every site
except one of which it is unclear whether the property covers it, and an
**accepted-loss / suppression** claim ("X is silently dropped", "never surfaces Y") is pinned by a
fixture in which the suppressed or lost input is *present*, except a removed outcome's loss the
Desired Behavior states as accepted; **(b) scoped** — rewritten to the precise form the mechanism
supports ("no *per-file* filename arguments", not "no filename arguments"), or, for a claim about
current code that a read confirms under the *Definition of verified* in
`references/step-3-5-self-audit.md` (read it there if unloaded, or after a failed read the first
sentence of its `references/degradation-routing.md` row), every clause of the confirming text read,
kept as written;
**(c) removed**; or **(d) stated as a heuristic** per the template's *Heuristics* rule, its accepted
limit needing no fixture unless the change removes an outcome whose loss the Desired Behavior does
not state as accepted. The carve-out is **extensional, not grammatical**: exempt are only (i)
mandated-verbatim template boilerplate (`Blocked by #N` lines) and (ii) rule text the change ships
as artifact content (a convention sentence the change adds to a file, quoted in the body). An
acceptance-criterion or Desired-Behavior sentence is **never** exempt however imperative its
phrasing. A **detector or guard coverage claim** ("catches all future X", "can never fall behind",
"every violation is flagged"), however grounded, additionally carries a
**planted-defect positive-control obligation** on the implementer — plant the defect the guard
targets and prove the guard fires on it.

### Decision-rule mapping

A **decision rule** is one whose outcome set its surface names — documented grades, severities,
classifications, routes, thresholds, verdicts, or a guard's allow or deny. A defect fix changes no
decision rule only when the draft quotes the restored outcome in a `Verified:` bullet and the
surface's documentation and tests agree on it; where either is absent, unread, or disagrees with the
other, the fix owes the mapping. A draft that changes one — creating, deleting, narrowing, widening,
re-grading, reclassifying or re-routing any outcome, a guard or guarantee included — maps the rule's
before→after outcome per input class, in each mode of the rule's surface that decides whether or how
it runs. The classes are those the before rule or the after rule distinguishes, crossed with each
other and taken from the two rules' text and surface, never the request; classes whose outcome does
not change may share one row, and a rule the change creates has "no rule" as every before cell. The
Desired Behavior states each class whose outcome changes and each unchanged class the decided change
reaches (the template's **omit/merge/add** reach test); the row of unchanged classes it does not
reach goes to the investigation record, unless **omit/merge/add** finds the request unestablished,
when the Desired Behavior states the whole mapping. An unreached unchanged class the request names
is still covered by a preservation under **omit/merge/add**. Where the change lets evidence excuse a case
from a rule or loosen, skip or demote its outcome, the mapping names that evidence and a class per
state: for model-read prose, each state the template routes for an agent-read value; else exactly
four, complete by construction: missing; malformed or wrong-type; produced by a step that did not
run; unreadable. Each such class keeps its before outcome unless the request names that state; a
created rule's mapping states each outcome. Each before cell of an existing rule's row whose
outcome changes is the base rule's own text quoted in a `Verified:` bullet, never a paraphrase
beside a quote; the shared row of unchanged classes still names each evidence state it covers but
carries no quote unless the base text disagrees with itself about a class it names; where the
base text disagrees with itself, quote each disagreeing line and state the conflict. Every claim
about the change's effect — an accepted change, a limit, an unchanged outcome — is read from the
mapping, and each changed rule's after column is a candidate criterion graded by the template's
**omit/merge/add** rule, with the request changing the rule as its admissible origin; a criterion
it adds or extends asserts each class the Desired Behavior states. An outcome the change removes
names the existing mechanism that still provides it for every case it covered, or the Desired
Behavior states the loss as accepted, which needs no fixture.

### Backstop verification

A draft that creates a deterministic hook, gate or backstop, or changes what one enforces, carries a
Testing Strategy case asserting the mechanism fires when the cooperative step it backs was skipped.
Where enforcement can repeat, the case also asserts that repeating it is idempotent.

### Trust-boundary closure

An AC establishing a trust or integrity boundary over executable artifacts defines the protected set
over the transitive closure. When an acceptance criterion protects scripts, hooks, or anything
sourced, exec'd, or imported — asserts they cannot be tampered with, are validated, or run from a
trusted copy — the protected set covers the **transitive source / exec / import closure** of the
named entry points, not the entry points alone. An issue that protects less states the
**residual unprotected surface** explicitly.

### Enumeration closure

Every enumerated member set inside a criterion declares its closure. Such a set, for example test
cases or existing producers, markers or consumers, takes one of two forms: a **floor**, carrying the
exact marker `at minimum`, or a **closed set**, carrying an explicit exhaustiveness statement of the
shape `exactly these N — complete by construction`. A closed set whose members the change does not
itself define is declared `complete by construction` only when a bundle entry meets the enumeration
rule in `references/step-2-clarify.md`, and otherwise a floor with `at minimum`. A set owned by a
file the change does not edit, where the criterion's reader can follow a pointer to it, is instead
pointed at by the criterion: the pointer covers every member and owes no floor, closed-set
statement, per-state criteria or per-member pin; the criterion names by name alone a member the
change gives an outcome of its own, with that outcome, and restates nothing that file defines for
the set (a member's definition or assigning condition, an order, a closure marker); when it is
unclear whether the reader can follow the pointer, the set takes a form above. Any other enumeration
carrying neither form is non-conforming.
<!-- prflow:spec-ref step=quality-group-contracts file=skills/spec/references/quality-group-contracts.md end -->
