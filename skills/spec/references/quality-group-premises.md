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
  `references/step-3-5-self-audit.md` (read it there if unloaded), a read confirms that the code
  does X only with the enclosing gates, conditionals and defaults on the path to X read too; state a non-default precondition inside the claim. When X is one clause of a multi-clause rule or one step
  of an ordered procedure, also read each other clause of that rule and the steps whose order the
  claim depends on; the `Verified:` bullet quotes only the clause that makes the claim true; a
  sibling read that is denied, empty, partial or inconclusive leaves the premise unverified and out
  of the `Verified:` bullets. This discipline runs **twice**: at drafting time, and again in Step
  3.5's self-audit, which re-applies it to the *assembled* draft before the user sees it.
- [ ] **Value semantics.** Ground a "Verified:" premise about a value's meaning or a reused
  component's result in its producer and the code that acts on it. Read the conversion, validation
  and defaulting that determine the claimed result, including the relevant output, status and
  diagnostic. An existing invocation establishes usage; a schema or declaration states constraints,
  not whether this call enforces them. Keep command success distinct from a usable result. Before
  claiming a value's domain, nullability or units, search for a wider domain and read its consumers;
  a consumer distinguishing more states withholds the narrower claim. Ground the distinction the
  proposed behavior relies on, using the existing probe or obligation route for an unstated
  dependency in Step 3.5 item 4.
<!-- prflow:spec-ref step=quality-group-premises file=skills/spec/references/quality-group-premises.md end -->
