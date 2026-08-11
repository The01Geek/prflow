# DevFlow repo — operative policy for `/prflow:review-and-fix`

This repository is the DevFlow plugin itself: its findings frequently concern the engine prose in
`skills/` and the best-effort shell/`jq`/Python helpers in `scripts/`/`lib/`. The base skill's
gates stand unchanged — this extension **sharpens** (never supplants) the **fix-delta gate**
(Step 0.9) and the **Step 2.6 shadow reviewer prompts** with four repo-specific
verification-discipline shapes plus an interpreter-faithful-probe rule. Flag an instance of any
shape as at least **Important**, and require the fix to verify the *outcome*, not the precondition.

<!-- Coupled copy (same-commit reconciliation): the paragraph below is a real copy, mirrored in `.prflow/prompt-extensions/receiving-code-review.md`; each extension is loaded independently, so a pointer would not resolve for its reader. Edit both together. -->
When a review finding on prompt-surface prose would be answered by adding text, prefer **rewording the existing sentence** over appending a new one. If the finding is that a rule could be misread, fix the rule's wording. Append only when the finding identifies a genuinely missing instruction or consequence.

## Wording-only pin review policy

Flag every newly added wording-only, secondary-prose, documentation-presence, advisory-heading, or
comment-presence pin as an **Important** finding, whether it uses a pin helper or a raw
text-presence assertion — a `# structural-pin-ok:` comment does not make prose executable. A new
static presence pin is valid only under `CLAUDE.md`'s executable-evidence policy: the exact
declaration `# structural-pin-ok: <category> -- <rationale>`, a nonempty rationale, and one
category from that policy's closed set.

The "whether it uses a pin helper" scope is enforced mechanically as well as by review:
`mutation-routing-worktree` reports a **new or modified** count-helper pin (`pin_count` /
`devflow_module_pin_count`) whose literal resolves into prose exactly as it reports the equivalent
static-helper or raw-`grep` pin (issue #925 — helper identity selects no exemption). Only changed
sites are adjudicated, so an unmodified prose pin that predates the rule is not retroactively
failed.

An operative prompt regression instead uses an ordinary executable test over the rendered or
consumed prompt and demonstrates that test going RED when the behavior breaks.

## Focused test modules are the fix-iteration default

`CLAUDE.md`'s suite-running policy — test selection, the focused-first precondition, the
whole-suite gate, shard decomposition, and the per-launch `Verification evidence:` record —
governs this loop unchanged and is not restated here. This section states only what
`/prflow:review-and-fix` adds to it.

Do not infer or automate changed-file-to-module routing. For **local review-and-fix contract
iteration only**, run exactly `lib/test/run-module.sh review-and-fix-contract` as a direct
leading token.
Cloud-tier runs use `lib/test/run-module.sh <module-id>` (direct leading-token form) when the tier grants it and a registered module covers the fix; otherwise they use the already-permitted complete suite without requesting new permissions.

**Whose terminal the loop's gate is depends on the caller.** Inside `/prflow:implement`
(Phase 3.3) it is not the loop's own — every Phase 4 commit makes a Phase 3 flight stale by
definition, so a whole-suite pass paid at the loop's terminal is discarded rather than relied
on, and the obligation is owned exactly once by Phase 4.3. The caller is knowable with **no**
new flag, field, or counter: it is the axis the focused-selection sink already routes on — the
issue workpad inside `/prflow:implement`, `iter-<N>.json` standalone — and a loop that cannot
establish which caller it has treats itself as **standalone**.
<!-- Authoring constraint: keep this caller distinction invocation-derived — the same axis the focused-selection sink routes on — and never degrade it to workpad-presence-only inference. A workpad's presence or absence tracks things other than the caller, so that inference is what would produce an affirmative-but-wrong inside-implement classification, which the fail-closed clause cannot catch: it fires on an unestablished caller, never on a confidently wrong one. -->

**A standalone terminal owes the honesty floor first.** The terminal verdict is a **findings**
verdict — `Review converged after {N} iteration(s)…`, the APPROVE family, `REJECT` — and asserts
nothing about a test suite, but the loop *edits code*, so it verifies in-env, at the narrowest
covering target, every surface it changed, on every tier and for every caller.

**Past that floor the standalone whole-suite obligation survives only where no external backstop
exists.** Where the run establishes that nothing outside it will exercise the broader suite over
this tree — the ordinary standalone shape, since the skill reviews the current branch when given
no PR and `--push-each-iteration` is off by default — the loop is the last line and pays the pass
itself. Where it *does* publish to a PR whose merge this project gates on a check outside the run
that exercises the broader suite, the loop emits its findings verdict **without** that pass and
its wording may **not** assert or imply the broader suite is green. A loop that cannot establish
whether such a backstop exists takes the whole-suite result.

This scopes **which run pays** and **what the terminal may claim**, never **which channel
establishes** either: the issue-#405 in-env rule is neither weakened nor narrowed, and no loop
waits on, polls, re-checks, or cites CI for its own progress.

A nonempty skip tally is not clean.

## Guard-class shape 1 — existence-vs-sourceability (verify the outcome, not the precondition)

A guard that tests a file's **existence** and then treats a later **consumption** of that file as
guaranteed is fail-open: the file can exist yet be unreadable, corrupt, or fail to parse/source, so
the precondition passes while the outcome it stands in for never happens.

- **Flag:** any `[ -f <file> ] && . <file>` (or `[ -f x ] && source x`, `[ -e x ]` gating a
  later read/parse) where the guard's *intent* is "the thing the file provides is now
  available." `[ -f ]` proves the path exists — it proves nothing about whether sourcing
  succeeded or the symbol/function it defines is now callable.
- **Fix (verify the outcome):** assert the *consumed result* directly. For a sourced helper,
  check the function is defined after sourcing — `. <file> 2>/dev/null; type <fn> >/dev/null 2>&1 || { breadcrumb; fail-closed; }` — not that the file exists. For a parsed value, check the
  parse produced a usable value. Fail **closed** with a specific breadcrumb when the outcome
  check fails, never silently continue as if the sibling loaded.

## Guard-class shape 2 — tr-dependence (an external PATH tool whose absence silently changes output)

A value (a slug, a branch name, a path segment, a normalized identifier) derived by piping through
an external tool consulted on `PATH` — `tr`, `sed`, `awk`, `paste`, `jq` — degrades **silently**
where that tool is missing or behaves differently: the pipeline still runs, the value comes out
wrong, and the wrong value then selects the wrong directory, writes the wrong file, or no-ops a
gate, with no error.

- **Flag:** any selection- or output-determining value derived through such a tool where a
  failure of the tool (absent on `PATH`, a BSD/GNU behavioral difference, a locale effect)
  would silently change *which* thing is selected or *what* is emitted, rather than surfacing
  an error. Especially where the derived value keys a filesystem path or a comparison.
- **Fix:** either prove the tool is a hard, preflight-guaranteed prerequisite (and cite it), or
  make the failure observable — check the derived value is non-empty/well-formed before it is
  used to select or emit, and fail closed with a breadcrumb naming the tool if it is not. A
  value that is *only* correct when an un-guaranteed tool is present is an unverified boundary.

## Guard-class shape 3 — vacuous negative test (attribute the rejection, carry a positive control)

A negative test — one asserting that a bad input is *rejected* — passes while proving nothing when
the rejection comes from somewhere other than the guard it names: the fixture trips an unrelated
precondition, or a different guard rejects the input first, so an exit-code-and-no-output assertion
stays green even against a mutant that disables the very guard the test exists to kill.

- **Flag:** a negative test whose only assertions are the exit code and the absence of output/PATCH,
  on an input that more than one guard could reject — and no positive control on the same fixture
  proving the fixture is otherwise valid. The test names one guard but pins no signal that distinguishes
  it from a precondition or a sibling guard firing first.
- **Fix (attribute + control the outcome):** pin the **rejecting guard's own distinct signal** (its
  specific message/breadcrumb, e.g. `net-adds` absent with the offending pair named), not merely that
  the call failed — so the assertion fails if any *other* guard did the rejecting. And add a **positive
  control on the same fixture**: a companion assertion that the fixture is otherwise valid and the call
  would succeed but for the one property under test, so an unrelated precondition rejecting the fixture
  cannot masquerade as the rejection under test.
- **PR #340 cost this would have eliminated:** two vacuous tests and their follow-up findings.

## Guard-class shape 4 — re-derived consumer contract (write the guard as the operation it protects)

A guard written as a *separate predicate approximating* a downstream consumer's contract — instead
of using that consumer's own operation as the guard — accepts a **superset** of what the consumer
accepts, so inputs the guard waves through still break the consumer. The tell is a guard that
inspects a *proxy* for the protected value rather than the value the consumer actually operates on.

- **Flag:** a new guard/predicate over a string or shape that hand-derives what a nearby parser,
  splitter, or narrowing op already decides — a regex/`in`-check/type-check standing in for a
  `strptime`, a `splitlines()`, a `_find_checkbox_row`, a JSON decode — especially when the correct
  idiom already exists elsewhere in the same file. Naming the protected operation *after* the predicate
  is written is itself the smell.
- **Fix (write the guard as the operation):** name the downstream operation the guard protects, in the
  code, before writing the predicate; then write the guard **as** that operation (share its contract by
  construction, so the accepted sets are identical and cannot drift). Before writing any new predicate
  over a string or shape, grep the file for an existing idiom doing the same job and reuse it.
- **PR #340 cost this would have eliminated:** the original guard defect and an extra review iteration.

## Probe rule — run interpreter- and environment-dependent probes under the real interpreter

When a fix or a review probes behavior that depends on the **interpreter or environment** the
artifact actually runs under, run the probe under that interpreter, and prefer evidence from the
executable test under its real interpreter over a hand probe when the two disagree. A probe run
under the *wrong* interpreter reports a false vacuity — an assertion live under the artifact's real
shell looks dead under the shell you happened to type into — and chasing it costs real effort
across every reviewer who repeats the mistake, finding zero defects.

- **PR #340 cost this would have eliminated:** three false vacuity alarms over a `printf '%b'`
  loop whose octal escapes bash expands and that session's zsh did not — duplicated investigative
  effort across the orchestrator and two reviewers, with zero defects found.

## Count-locked prose — a `count-locked` row on an unpinned claim triggers the pin-or-don't-write policy

The shared engine's Phase 0.6 `stale-prose-lint.py` ships **detection only**, tagging an exact-count
claim in diff-added prose as `count-locked`; the **policy** lives here, in this repo's layer. When
the fix loop's Step 3 stale-prose pre-check (or Phase 0.6) reports a `count-locked` row whose claim
is **not** already bound to a test assertion that would fail if the count drifts, apply the repo's
**pin-or-don't-write** policy: either bind the counted claim to a suite pin in the same change, or
reword it drift-proof — a lower bound instead of an exact count, a pointer to the defining symbol
instead of a copied enumeration. Do not ship an unpinned exact-count claim in engine prose;
authoring a fresh one is a self-inflicted Important finding. (#423)

## Config-derivation fixes sweep the full six-shape adversarial matrix, not just the reviewer-cited row

When a fix touches **how a config value is read, derived, or defaulted** — a `config-get.sh` read, an
inline `jq` extraction over `.prflow/config.json`, an `// default` / `// true`-style fallback, an enum
validation, or any other code that turns a raw config value into a decision — the **same fix** sweeps the
full CLAUDE.md six-shape adversarial matrix over that value: `{object, array, scalar, valid-falsy (explicit false / 0 / empty string), missing, wrong-type}`.
Each shape is **tested in `lib/test/run.sh` in the same change** (exit-0 + a specific, not generic,
breadcrumb per shape; the **valid-falsy** row is load-bearing — a real `false` / `0` / `""` an
`// true` / `// default` extraction silently coerces to its truthy default is the documented
off-switch-that-never-worked defect, #312/#304). A shape that genuinely does not apply to this value is
recorded with a **written reason** instead of a test — never silently skipped. A fix that covers **only**
the reviewer-cited shape row is **incomplete by policy**, because the sibling rows are exactly the next
run's predictable test-gap findings. This is DevFlow-repo policy; the governing convention is CLAUDE.md's
best-effort-parser adversarial-matrix gotcha, and this section is its coupled mirror in
`.prflow/prompt-extensions/receiving-code-review.md` — edit both in the same change. (#466)

## Merge conflicts in generated artifacts

This section's trigger is a **merge conflict**, not an edit: whenever a rebase, base merge, or branch
update leaves a conflict in a checked-in file, resolve it as follows before touching the conflicted
bytes. No post-edit pass routes through this rule, so it stands on its own.

The listing this rule reads comes from the granted direct leading-token form:

```bash
lib/test/regenerate-artifacts.py --list
```

1. Run that command.
2. **Establish that the listing is usable before classifying anything.** This gate precedes the
   classification below, and the order is load-bearing: an unusable listing emits no `conflict-path`
   lines, so every conflicted path would otherwise satisfy step 3's "not among them" exit and be
   hand-merged — the guard failing open on exactly the input it exists to catch. The listing is
   usable only if the command exited **0** and emitted at least one `artifact` line and at least one
   `conflict-class` line. If it was refused, the interpreter is absent, the exit code is anything
   else, or the output is empty, truncated, or otherwise unattributable, treat every conflicted
   generated artifact as **needs-human-reconciliation** and stop rather than blind-regenerating. This
   verdict is **residual, not an enumeration of known failures**: any outcome you cannot positively
   attribute is unusable. An unestablished class is unknown — not `by-hand`, and not "absent from the
   set".
3. With a usable listing, look for the conflicted path among the emitted `conflict-path` and
   `conflict-sibling` paths. If it is **not** among them, hand-merge it as any normal file — the
   fail-closed default for the complement of the generated-artifact set.
4. If it **is**, follow the class of the **line that matched**, not the row's class unconditionally.
   A `conflict-path` match is governed by that row's `conflict-class` and `conflict-recipe`. A
   `conflict-sibling` match is governed by **that line's own fourth field**, which is the sibling's
   class — never the owning row's `conflict-class`: a coupled sibling is a file the row's gate reads
   but its generator never writes, so the row's recipe would send you to regenerate a file no
   generator produces. Then follow the governing recipe verbatim — never hand-merge the conflicted
   generated bytes. `regenerate` means re-run the recipe's named write command against the merged
   tree. `reconcile-source` means merge the recipe's named source of truth first, regenerate from it,
   then hand-update the coupled by-hand sibling the `conflict-sibling` line names. `by-hand` means the
   record has no writer and is re-measured or hand-merged deliberately.

Hand-merged generated bytes match no source of truth, so the artifact's own gate then reports them as
drift with a remedy aimed at the wrong file — the run burns a loop chasing a misdirected diagnosis
while silently reverting whatever a concurrent PR added. This rule hardcodes no artifact path and no
command: both are read from `--list` at runtime, so the rule and the registry structurally cannot
drift.

## Batched artifact regeneration

After each edit batch, run the granted direct leading-token form once:

```bash
lib/test/regenerate-artifacts.py
```

Then, once and only immediately before the completion-gate whole-suite pass, run it with the opt-in floors row:

```bash
lib/test/regenerate-artifacts.py --with-floors
```

A fix loop's edits drift the checked-in generated records, and rediscovering each one a full suite run later is an iteration's dominant cost. The bare form takes about a second; the floors row measures every exact-policy module through the real focused runners and takes minutes, which is why it runs once at the gate rather than after every batch. The helper is the sole enumeration point; no inventory is listed here.

Act on its report first: commit a changed manifest with its causing edits, and resolve every exit-1-forcing judgment item under the policy it names. Informational lines need reading, not action. A `not measured` line for the opt-in floors row is the expected default-pass outcome and needs no action there, but it is an unchecked floor rather than a clean one — the module harness fails only a tally below the floor — so the gate pass above is what catches a floor left un-raised.

**Any outcome but exit 0 or a fully-reported exit 1** — exit 2, a traceback, an empty or truncated report, an unattributable exit code — means an artifact went unchecked: unknown, not clean. Judge residually, never by hunting a named token. Never record `run`; record `batched-regeneration: skipped` naming what you saw, and fall back to serial discovery.

If the matcher refuses the invocation **twice**, stop — record the refusal and proceed to the suite run rather than iterating variants (the issue-401 two-denials discipline). On a run that maintains a workpad, record one line before each full-suite run — `batched-regeneration: run|refused|skipped`.

## Prompt-surface edit routing evidence gate

DevFlow-repo policy: a reviewed diff that touches a **prompt-surface** file must carry evidence
that its edit went through the `superpowers:writing-skills` RED/GREEN discipline. This gate is the
review-time backstop for that routing — flag a missing discharge as at least **Important**.

**Trigger.** This gate applies only when the reviewed diff touches a path matching one of the
trigger globs: `skills/*/SKILL.md`, `skills/implement/phases/*.md`, `skills/implement/references/*.md`, `skills/review/phases/*.md`, `skills/review-and-fix/references/*.md`, `.prflow/prompt-extensions/*.md`.
A diff touching none of them draws no finding.

**Enforcement surfaces.** The gate is enforced on an implement run's **Phase 3** (which holds its
own issue number), a **`/prflow:review-and-fix` run given a PR**, and **PR-mode standalone
`/prflow:review`**. A no-PR, no-issue **current-branch** run is **outside the gate's scope**,
because there is no issue workpad or PR body to read, so the gate is a no-op there.

**Discharge arms, checked in order** when the reviewed diff touches any trigger glob:

1. The **linked issue** — the run's own issue in an in-run enforcement, the PR's
   `closingIssuesReferences` in PR-mode — carries a `<!-- prflow:workpad -->` comment, or one
   carrying the superseded `<!-- devflow:workpad -->` spelling since issue #1003 renamed the marker
   namespace and rewrote no existing body, whose body **contains** the marker literal
   `Writing-skills evidence:`. Fetch that issue's comments through the granted `gh` read path,
   resolving `closingIssuesReferences` first — the workpad lives on the linked issue, not the PR
   thread.
2. Otherwise, the **PR description** **contains** the marker literal `Writing-skills evidence:` —
   the discharge surface for interactive/human PRs and for a linked issue that has no workpad.

**A read that fails or cannot be resolved reads as marker-absent, never as checked-and-clean.** A
`gh` comment-fetch error or an unresolvable/empty `closingIssuesReferences` fails the gate toward
its finding.
When no checked surface can be confirmed to contain the marker, the review reports a **FAIL** finding naming this rule — fail closed, an absent, malformed, or misspelled marker and an unestablished read all reading as absent.

**What the gate checks — shape, not mere presence.** A marker discharges the gate only when it
carries all four slots the evidence contract names — `skill-loaded`, `guidance-applied`,
`pressure-scenario`, `micro-tests` — each with an explicit `=yes` or `=no`. Read the four
dispositions and report them in the review.

**A slot whose disposition is absent is undischarged, never compliant.** Silence about a slot is an
unestablished measurement rather than a `no`, and this repo's *unknown is not zero* rule forbids
collapsing it onto either value; raise the same **FAIL** finding listing the slots at issue. The
remedy is to restate the marker with those dispositions, **not** to perform the step.

**A `no` never draws a finding on its own.** A marker whose four dispositions are all recorded is
discharged whatever they say — the gate reads them so a reader can weigh whether a step suited the
edit, and it never requires the subagent pressure-scenario cycle.

## Verification-evidence marker advisory (non-blocking)

DevFlow-repo policy: a second marker clause on the **same** review-engine surface as the gate above
— the linked issue's workpad and the PR description. It is **advisory (non-blocking)**: it never
raises the verdict to a FAIL/REJECT on its own, and only informs the reader that a completion or
PR-ready claim was made with no captured verification run.

**Input population.** The clause reads those same two durable per-PR surfaces, requiring no new
fetch channel. Every tier that maintains a workpad records the `Verification evidence:` marker, so
the clause checks **every** PR carrying a completion or PR-ready claim. Because per-launch
completeness is not machine-checkable — no consumer can know how many launches a run performed —
the clause can only observe that **at least one** record is present.

**Tier discriminator (per PR).** Classify from the workpad `## Progress` section: a workpad
carrying any `<!-- prflow:checkpoint gha:… -->` row, or the superseded
`<!-- devflow:checkpoint gha:… -->` spelling a pre-rename run stamped, is a **cloud** run; a
workpad with no such row is a **local/interactive** run. The clause acts on both classifications
and records the classification in the finding it emits, so a reader knows which tier was expected
to record the marker.

**Behavior.** When the marker is present on either surface the clause is silent. When it is absent
from both, the review emits one advisory finding naming the missing `Verification evidence:` marker
and the tier classification assigned.

**Covered population.** A cloud or local implement run's workpad, a `/prflow:review-and-fix` run
given a PR, and a direct-reception marker recorded in the PR description. A local current-branch
run with no PR and no linked issue is **out of scope**, leaving no durable surface to read — the
same case the gate above scopes out.

**Accepted residual.** The `gha:` checkpoint is best-effort and fires only when the workpad carries
a canonical `## Progress` section, so a cloud run on a non-canonical workpad is classified
local/interactive. Issue #1347 narrowed that population — an **absent** `## Progress` is now
repaired by `--checkpoint` itself — leaving the residual only for a **duplicate** `## Progress` or
an empty body. Since the clause acts on both classifications, that mislabels the tier named in the
finding without changing whether the advisory fires, and the finding is non-blocking, so this is
accepted rather than guarded.
