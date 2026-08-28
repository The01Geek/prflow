<!-- prflow:implement-ref step=2.3.0c file=skills/implement/references/sweep-2-3-0c-operand-trace.md start -->

#### 2.3.0c Operand-trace sweep (mandatory whenever the diff adds a guard, predicate, validator, or coverage invariant in code, or ships agent-executed imperative prose stating a policy)

2.3.0a/2.3.0b catch a rule or an enumerated value replicated across too few sites; 2.3.4 verifies a boundary the diff *reads* but explicitly carves out the diff's *own* code. This sweep closes the gap between them, and it has two authoritative triggers — run it when either fires:

- (a) Code trigger — the diff adds a guard, predicate, validator, or coverage invariant. A guard whose comparand comes from the diff's own code is covered by no other sweep: 2.3.4 carves out in-diff code, and 2.3.0a/2.3.0b watch peer sites and enumerated sets, not the operand a single guard reads.
- (b) Prose-policy trigger — the diff's deliverable is a policy-stating command block. When the deliverable is a `SKILL.md`, `phases/*.md`, or `references/*.md` command block that states a policy the agent must execute, the policy's operand is a value the *agent* has to observe at run time — and a policy stated against an operand no step produces is inert.

Both triggers are the same defect at bottom: a check written against an operand nobody traced back to what actually produces it, so the check passes — or is inert — exactly on the inputs it was added to catch.

Trigger (a) — the operand trace. For every comparand the added guard/predicate/validator/coverage invariant reads, commit **one `--note` per comparand** — never a single multi-row table in one note, which can exceed the workpad's 2,048-byte per-note budget and be refused. Each comparand's note carries these four fields:

- comparand
- producer (file + line)
- emitted on every path the guard now selects?
- what OTHER inputs produce the same value?

The fourth field — the one asking what *else* produces the guard's comparand value — is the **load-bearing** one: it asks "what else exits 2?", since unrelated causes routinely share an exit code, so a guard reading "exit code 2 ⇒ no workpad" acts on a state it never observed. A comparand whose fourth field names another producer of the same value that the guard does not distinguish is a fail-open guard and a defect in **this** PR.

Derived comparands enumerate their malformed/empty arms. When a comparand is *derived* — piped through a helper, a parse step, a subprocess, or any pipeline, rather than read as a plain literal — its note additionally enumerates the malformed/empty arms the producer can emit: producer failure (a non-zero exit or a denial), unparseable output, a wrong-type value, a valid-falsy/empty value, and a missing key or file (the six-shape adversarial input-shape matrix applied to a comparand) — and states the guard's decided behavior on each arm. A derived comparand whose note leaves any such arm unenumerated is an unauthored fail-open accident and a defect in **this** PR: the guard's behavior on the unenumerated arm was never decided, so it fails open on exactly the malformed input the operand-trace exists to surface (a `.get('stats')` on non-object JSON that raises, an empty parse result that passes the guard green).

Trigger (b) — the stated-policy contract. For every policy the prose states, name (a) the observable operand the agent keys the policy on, (b) the step that produces it, and (c) an explicit route for every outcome of that operand, **including the failure outcome** (the operand absent, the producing step failing, the value unresolvable). A stated policy whose operand no step produces is an inert guard and a defect in this PR — the promised routing can never fire, so the policy silently no-ops on exactly the input it was written to gate.

A stated policy places its obligation at the execution point it gates, carrying at most a cross-reference from any thematic section that also discusses it; prose that describes the hazard only in a thematic section, leaving the execution point it gates with no obligation, does not discharge this trigger.

The sweep is not done until every comparand has a completed four-field note — with a derived comparand's malformed/empty arms enumerated and each arm's decided behavior stated (trigger a) — and every stated policy names its observable operand, the step that produces it, a route for each outcome including failure, and places that obligation at the execution point it gates (trigger b).

<!-- prflow:implement-ref step=2.3.0c file=skills/implement/references/sweep-2-3-0c-operand-trace.md end -->
