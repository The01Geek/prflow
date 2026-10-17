<!-- prflow:implement-ref step=2.3.0c file=skills/implement/references/sweep-2-3-0c-operand-trace.md start -->

#### 2.3.0c Operand-trace sweep (mandatory whenever the diff adds or hardens a guard, predicate, validator, or coverage invariant in code, or ships agent-executed imperative prose stating a policy)

2.3.0a/2.3.0b catch a rule or an enumerated value replicated across too few sites; 2.3.4 verifies a boundary the diff *reads* but explicitly carves out the diff's *own* code. This sweep closes the gap between them, and it has two authoritative triggers — run it when either fires:

- (a) Code trigger — the diff adds **or hardens** a guard, predicate, validator, or coverage invariant. A guard whose comparand comes from the diff's own code is covered by no other sweep: 2.3.4 carves out in-diff code, and 2.3.0a/2.3.0b watch peer sites and enumerated sets, not the operand a single guard reads.
- (b) Prose-policy trigger — the diff's deliverable is a policy-stating command block. When the deliverable is a `SKILL.md`, `phases/*.md`, or `references/*.md` command block that states a policy the agent must execute, the policy's operand is a value the *agent* has to observe at run time — and a policy stated against an operand no step produces is inert.

Record. The sweep writes **one `--note`** when its trace fits the per-note byte budget (over budget, phase-2-implement.md §2.0.5's continuation route), one compact line per traced item: a guard comparand's line gives the comparand, its producer, and the guard's route when the value is absent and when it has the wrong type; a stated policy's line gives its operand, the producing step, and the route when that step fails. The fuller work below stays in your context.

Trigger (a) — the operand trace. For every comparand the added **or hardened** guard/predicate/validator/coverage invariant reads, work through these four fields:

- comparand
- producer (file + line)
- producer behavior on every path the guard now selects — can it fail or emit nothing, and what establishes a successful production?
- what OTHER inputs produce the same value?

The fourth field — the one asking what *else* produces the guard's comparand value — is the **load-bearing** one: it asks "what else exits 2?", since unrelated causes routinely share an exit code, so a guard reading "exit code 2 ⇒ no workpad" acts on a state it never observed. A comparand whose fourth field names another producer of the same value that the guard does not distinguish is a fail-open guard and a defect in **this** PR.

Every comparand enumerates the producer's silence and the guard's decided behavior — a direct read, a file-presence check, and a derived value alike. Enumerate the arms the producer can present that apply to that comparand: producer failure (a non-zero exit or a denial), unparseable or wrong-type output, a valid-falsy/empty value, and a missing key, file, or value — and state the guard's decided behavior on each. **Distinguish an established result from an unestablished observation:** a valid empty collection, `false`, `0`, an explicitly optional field, or a documented best-effort default keeps its intended meaning when the contract permits it — not every empty value or advisory failure blocks — while a required input that is absent, unreadable, malformed, or incomplete is unestablished evidence, never a clean value. A comparand whose trace leaves an applicable arm unenumerated is a defect in **this** PR: the guard's behavior on the unenumerated arm was never decided — so where the guard carries no fail-closed default it fails open on exactly the input the operand-trace exists to surface (a `.get('stats')` on non-object JSON that raises, an empty parse result that passes the guard green, a `[ -f "$f" ]` that never confirms the file it gates parses).

A gate whose contract requires established evidence to pass records, on its line, its non-passing route for evidence that is absent, unreadable, malformed, or incomplete — and passes only on evidence that meets the contract, never on the mere absence of an unsafe-state signal when the producer may emit nothing (no unsafe-state signal need exist for the gate to refuse).

Trigger (b) — the stated-policy contract. For every policy the prose states, name (a) the observable operand the agent keys the policy on, (b) the step that produces it — agent recall carried across a subagent dispatch is not one — and (c) an explicit route for every outcome of that operand, **including the failure outcome** (the operand absent, the producing step failing, the value unresolvable). A stated policy whose operand no step produces is an inert guard and a defect in this PR — the promised routing can never fire, so the policy silently no-ops on exactly the input it was written to gate.

A stated policy places its obligation at the execution point it gates, carrying at most a cross-reference from any thematic section that also discusses it; prose that describes the hazard only in a thematic section, leaving the execution point it gates with no obligation, does not discharge this trigger.

The sweep is not done until every comparand has a completed four-field trace and its note line — with each comparand's applicable producer-silence arms enumerated and each arm's decided behavior stated, an established valid-empty/optional result distinguished from unestablished required evidence, and a gate's non-passing route recorded for missing evidence (trigger a) — and every stated policy has its note line and names its observable operand, the step that produces it, a route for each outcome including failure, and places that obligation at the execution point it gates (trigger b).

<!-- prflow:implement-ref step=2.3.0c file=skills/implement/references/sweep-2-3-0c-operand-trace.md end -->
