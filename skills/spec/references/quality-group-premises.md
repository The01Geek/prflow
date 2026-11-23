<!-- prflow:spec-ref step=quality-group-premises file=skills/spec/references/quality-group-premises.md start -->
## Quality group — verified claims and external premises

- [ ] **Every relied-on third-party behavior went through the WebFetch → WebSearch → ask-the-user ladder with its source recorded, or became a Blocked question / flagged assumption.**
  The premise class is **relied-on third-party behavior** — every behavior of an external platform,
  API, or service the issue **relies on** (load-bearing for the Desired Behavior, an acceptance
  criterion, **or** the Implementation Notes Approach — not only an AC's mechanism): webhook / event
  delivery, trigger syntax, token scopes, endpoint behavior, response shapes, rate limits, and the
  like. Never assume it. Verify it with this **decided fallback ladder**, stopping at the first rung
  that resolves it: **(1)** the vendor's **official documentation via `WebFetch`** (not memory);
  **(2)** when the docs are not reachable, **`WebSearch`**; **(3)** when search is unavailable or
  fails, **ask the user to provide the documentation**. Record the fact and its source URL in
  `Technical Context` before you write the claim. **Ladder terminal arm — decided two ways.** When
  the ladder yields **no documentation** and **no working example in this codebase already proves**
  the behavior, the item becomes a `## 🚫 Blocked` entry phrased as a **direct question** — the exact
  vendor fact plus one line on why it blocks the work. When a
  **working in-codebase example does prove** the behavior but documentation is still unavailable,
  write the claim inline as an explicitly flagged `— assumption, confirm before implementing` line
  **citing that example**, not a Blocked entry. Treat an empty or inconclusive ladder result as
  **unverified**, never as silent confirmation. Verification covers **load-bearing** premises only,
  so an **incidental third-party mention** stays light and triggers none, and drafting is never
  blocked in a data-less authoring context.
- [ ] **Re-derivation handles.** Write a bolded `**Verified:**` label, the repository path in
  backticks, and a double-quoted sentence of at least eight characters copied verbatim from that
  file (the recognized quotation used by the handle-repair steps). Step 3.6's draft checks run
  `scripts/check-verified-premises.py` over the draft; inspect its `handle=` and `ungraded_claim=`
  report to check the handles and catch verification claims in ungraded shapes. An implementing run
  re-checks the filed issue with the same helper. Two forms the helper cannot grade stay prose,
  never `Verified:` bullets: an **externally verified fact** uses
  `Per <URL>, checked <YYYY-MM-DD>: <fact>` (the helper makes no network call); a
  **documentation-absence claim** names the search performed and its empty result (the helper has no
  negation). A `Verified:` premise asserts a **present-tense fact about the current tree**; a claim
  about the world *after* the change is written as an acceptance criterion, not a premise.
- [ ] **Enclosing gates.** Under the *Definition of verified* in
  `references/standards.md` (read it there if unloaded), a read confirms that the code
  does X only with the enclosing gates, conditionals and defaults on the path to X read too; state a non-default precondition inside the claim. When X is one clause of a multi-clause rule or one step
  of an ordered procedure, also read each other clause of that rule and the steps whose order the
  claim depends on; the `Verified:` bullet quotes only the clause that makes the claim true; a
  sibling read that is denied, empty, partial or inconclusive leaves the premise unverified and out
  of the `Verified:` bullets.
- [ ] **Value semantics.** Ground a "Verified:" premise about a value's meaning or a reused
  component's result in its producer and the code that acts on it. Read the conversion, validation
  and defaulting that determine the claimed result, including the relevant output, status and
  diagnostic. An existing invocation establishes usage; a schema or declaration states constraints,
  not whether this call enforces them. Keep command success distinct from a usable result. Before
  claiming a value's domain, nullability or units, search for a wider domain and read its consumers;
  a consumer distinguishing more states withholds the narrower claim. Ground the distinction the
  proposed behavior relies on with a cited probe or an implementer obligation to establish it, to
  add the capability or to establish whether it exists (**Obligation execution tier** in
  `references/quality-group-contracts.md`; read it there if unloaded).

- **Guard claims.** A criterion resting on an authorization-guard, permission-key, or gate-condition
  claim about existing code — exactly these three claim kinds, complete by construction — is
  accompanied by a `Verified:` bullet in Technical Context that quotes a span of the guard's own
  code line — a backtick span inside the quotation is part of the quoted sentence, and a
  double-quote inside such a span neither opens nor closes it — which
  `scripts/check-verified-premises.py` reports as `handle=path-quote state=holds` against the
  current tree. A criterion resting on the *absence* of such a guard is accompanied instead by a
  `Verified:` bullet quoting the gate the guarded code carries today, or the guarded code's first
  statement when it carries none, and rests on a worker's returned read of the producing surface — the
  guarded code and everything in the repository on each path the criterion relies on that reaches
  it and can stop it, such as decorators, attributes, middleware, filters, route rules, a job's or
  command's registration, a workflow `if:` condition and global registrations — together with a
  repo-wide whitespace-normalized search. A zero-hit search alone never establishes an absence, and a
  denied or unavailable search leaves it not established. No criterion asks the
  implementer to confirm the absence by reading code. A report that names a guard without quoting it is not grounding:
  without the graded bullet and a read confirming it under the *Definition of verified* in
  `references/standards.md` (read it there if unloaded) — for an absence, a read with
  that coverage and search — the claim is an unverified premise, not an admissible criterion.
<!-- prflow:spec-ref step=quality-group-premises file=skills/spec/references/quality-group-premises.md end -->
