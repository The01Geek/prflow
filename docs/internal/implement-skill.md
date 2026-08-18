# `/prflow:implement` skill — Phase 2.3 sweep discipline and Phase 4.3 finalize

**Skill:** `skills/implement/phases/phase-2-sweeps-contract.md` (Phase 2.3, *Implement*) — the detailed phase procedure read at phase entry by the thin `skills/implement/SKILL.md` orchestrator

## Early Phase 1 dependency preflight

After workpad hydration, Phase 1 runs the declared-dependency preflight before
any branch checkout, creation, checkpoint merge, or push. An open or
unresolvable dependency terminalizes the workpad as Blocked; Phase 1.6 keeps
the other audit passes without re-running this gate.

## Phase 1.6 Pass 0 — Desired Behavior projection

Desired Behavior is the issue's authoritative statement of intent. Acceptance Criteria are its exhaustive, merge-gated projection and remain the only formal specification consumed by implementation and review. The run does not copy Desired Behavior into the workpad, widen `scripts/parse-acs.py`, or create duplicate checklist items from narrative prose.

The existing `prflow:issue-claim-auditor` dispatch checks that boundary before Phase 2. It reads the cached issue body and the Acceptance Criteria already resolved by `scripts/parse-acs.py`, then classifies each independently verifiable post-change obligation in Desired Behavior as represented, unmatched, or non-obligatory explanation. Representation can come from one criterion or a jointly sufficient set, but it must preserve the obligation's subject, scope, outcome, and strength.

- A clean record returns `projection_disposition: represented` with an empty `unmatched_desired_behavior` array. Phase 1 writes that tuple to a scratch JSON file and evaluates it with `lib/projection-gate.jq` through `scripts/run-jq.sh` before proceeding.
- An uncovered obligation returns `outcome: blocked-specification`, `projection_disposition: unmatched`, and the exact Desired Behavior statement in `unmatched_desired_behavior`. The orchestrator records the issue as needing refinement and stops before Phase 2, even when the issue already contains other Acceptance Criteria.
- A missing field, wrong type, inconsistent tuple, unavailable gate, or non-zero gate result is not treated as clean. Phase 1 takes the existing unusable-record fallback and reruns the audit inline rather than entering implementation.
- The auditor never invents or rewrites a criterion. The issue author must repair the specification.

The same projection contract applies before PRFlow files an issue itself. `/prflow:create-issue` records a structured projection result and reruns the check after feedback has finished mutating the draft. Implement-generated deferred follow-ups carry the tuple in the deferral-drafter plan, and `skills/implement/references/deferred-ac-followups.md` omits an ineligible entry from filing, labeling, dependency registration, and deferred-criterion discharge. The weekly retrospective filters each Stage B finding through the same canonical predicate before selection and filing. `lib/desired-behavior-producers.json` records the non-interactive producer set so the contract test can detect a new producer that has not adopted the gate.

## Phase 1.6 Pass 6 — Verified-premise re-check (`scripts/check-verified-premises.py`)

A `Verified:` bullet in an issue body is what licenses an implementing run to **skip its own
investigation**. Those bullets are true when the issue is drafted, and until this pass existed
nothing re-checked them at implement time — so a premise that had since become false silently
converted "go and check" into "this was already checked", and the run built on it. Issue #857 is the
worked case: three of its premises were false by the time #864 implemented it, and two acceptance
criteria were unimplementable as prescribed.

Phase 1.6's Pass 6 (`skills/implement/phases/phase-1-setup.md`) closes that gap by re-deriving each
bullet against the tree the run will build on.

- **Input is the §1.1 issue-body cache, not a re-fetch** (issue #693): the pass invokes the bundled
  helper with `--body-file` pointing at `.prflow/tmp/issue-body/issue-<ISSUE_NUMBER>.md` and
  `--repo-root` naming the tree to adjudicate against, so the helper never guesses a root from the
  working directory. On the degraded arm where §1.1 wrote no cache, the fetched body is written to a
  file and that path is passed instead. The helper decodes that `--body-file` **explicitly as UTF-8**
  (not the ambient locale codec), so a non-ASCII issue body survives on a non-UTF-8 default host — a
  local-file decoding layer distinct from the stream/`gh`-I/O UTF-8 forcing (issue #222); invalid
  UTF-8 exits non-zero with a flag-specific diagnostic and no traceback rather than adjudicating
  against mojibake. The same explicit-UTF-8 decode covers `workpad.py`'s section-file flags and
  `branch-for-issue.py --title-file`, and an AST guard over `scripts/*.py` blocks any new
  ambient-codec text read.
- **Scope is every bullet the helper's marker recognises**, not only the ones the plan expects to
  lean on — the run cannot know in advance which premise a later phase will rest on. The marker's
  `_MARKER` constant carries **three alternation arms**: (A) the pure bolded label `**Verified**` /
  `**Verified:**`, matched anywhere including mid-sentence; (B) a line or list item opening with
  `Verified:`, optionally bolded or backticked; and (C) a bolded run opening a list item whose first
  word is `Verified`. The recognised set is a **floor, not a closed set, in BOTH directions** — as
  the helper's own comment records. *Under-recognition:* a bullet written in a spelling none of the
  three arms matches contributes nothing to the reported total, so the total is read as a floor on
  the bullets present, never as proof the issue carried no others. *Over-recognition:* arms B and C
  can mint a phantom bullet from ordinary prose (a bolded sentence that merely opens with the word
  Verified, or a `Verified:`-opening line inside a fenced block or table cell); the over-recognition
  half is the safety-relevant one, because a phantom that cites a genuinely-absent strong path can
  reach the refuting verdict.
- **Ungraded claims (issue #1634).** A verification asserted in a shape **none** of the three arms
  grades — "verified against origin/main" inside a bold-bullet label, a mid-sentence "checked against
  source" — is graded by nothing, yet an implementing run may skip its own investigation on the
  strength of it. A second, **non-adjudicating** pass reports each such collocation-family phrase
  found in a premise-bearing region (the `Current Behavior`, `Technical Context` and
  `Implementation Notes` sections plus every heading line) that no recognised marker span already
  covers and that is not inside code. These reports carry no `holds`/`refuted`/`unestablished`, move
  no exit code, and share no *state* token with the adjudicated vocabulary (the field names `detail=`
  and `total=` do recur there) — they say one thing: this claim is graded by nothing.
- **Output.** One `bullet=<n> handle=<path-quote|path|quote|command|none> state=<holds|refuted|unestablished> detail=…`
  line per bullet, then a `VERIFIED_PREMISES` summary line carrying the totals. On the normal path it
  then prints one `ungraded_claim=<n> region=… phrase=… detail=…` line per ungraded claim and an
  `UNGRADED_CLAIMS total=…` summary (emitted even when the total is zero). When the ungraded pass
  itself fails it prints `UNGRADED_CLAIMS unavailable reason=internal-error detail=…` in place of that
  summary, leaving the adjudicated output above it and the exit code unchanged. The handle classes,
  states, and this ungraded class are defined authoritatively in the helper's own module docstring.
- **Refuting is deliberately the hardest verdict to reach**, because a refutation makes the run
  discard the premise and file issue-accuracy feedback against the issue. Only a positively
  adjudicated claim refutes — a strongly-cited repository path absent from the tree, or a quoted
  sentence that no longer occurs in the file it cites. Everything the helper would have to guess at
  resolves to `unestablished` instead: a cited directory, a glob, a `::`/anchor/line locator, a
  span that is not a strong path claim (a filename-shaped identifier naming no directory, or a
  slash-bearing token such as a git ref whose tail is not path-shaped), a URL, an elided quotation
  whose fragments do not resolve, a quotation carrying no adjudicable text at all, an unreadable
  cited file, and a path resolving outside the repository (refused, not refuted). A `path` handle never reports `holds` either — the path's presence is checkable, but
  presence is not the premise.
- **Routing (four adjudicated arms plus the ungraded arm).** Exit **0** with zero bullets **and**
  `UNGRADED_CLAIMS total=0` records the falsifiable zero-findings `## Progress` note — the
  pass-complete arm is reached only when the helper reported no bullets *and* no ungraded claims, so
  a nonzero `UNGRADED_CLAIMS total` never lands that note; exit **0** with bullets records the clean
  confirmation naming the tallies; exit **2** (a refuted premise) records an `issue-accuracy`
  reflection, **discards** that premise, and investigates the surface directly from Phase 2 onward —
  it does **not** Block the run, because a stale premise is recoverable by investigation; exit **3**,
  a refusal, or no output at all records a `dropped-failed` reflection and treats **every** bullet as
  unverified. An unestablished measurement is never read as a clean pass. Orthogonally to the exit
  code, **each `ungraded_claim=` line** records an `issue-accuracy` reflection naming it as an
  ungraded claim (never a refutation) that does **not** license a skipped investigation, and an
  `UNGRADED_CLAIMS unavailable` line records a `dropped-failed` reflection — an unestablished ungraded
  measurement, never zero ungraded claims.
- **`handle=none` and `state=unestablished` are undecided, not refuted.** They restore exactly the
  state the run would have been in had the bullet never existed — go and check. That is the
  fail-closed direction.
- **Security boundary.** The issue body is third-party text, so the helper performs read-only file
  reads and nothing else: it imports no `subprocess`, makes no network call, never executes a
  command drawn from the body (a `command` handle is *reported* for the caller to re-run under its
  own judgment), and refuses a cited path that is absolute or escapes the repository root.
- **Freshness.** The pass reads the tree to adjudicate a claim, so it obeys §1.6's *Fresh-tree
  verification* rules (the read-target and cross-pass-coherence rules documented under
  *Stale-checkout guard for adopted branches* below) — a bullet must never be reported refuted off a
  stale checkout, the #322→#325 false-refutation shape.
- **Cloud grant.** The helper's vendored literal is granted on the `implement` and `command`
  capability profiles in `lib/capability-profiles.json`; the workflow allowlist literals are
  regenerated from that manifest and the `review` lock is unchanged (see [`cloud-allowlist.md`](cloud-allowlist.md)).

The drafting side of the same fix is in `/prflow:create-issue`: `skills/create-issue/references/issue-template.md`
now requires every `Verified:` bullet to carry a self-contained re-derivation handle — the repository
path in backticks followed by the source sentence verbatim inside an ASCII or typographic double-quoted span (with
any bullet punctuation after the closing quote) — with a matching drafting-checklist row. `skills/create-issue/references/step-3-5-steelman.md`
states the obligation, and `skills/create-issue/references/step-3-6-audit.md`'s pre-dispatch canonical
write is where it executes (the first anchor at which the canonical draft file exists). A
`handle=none` bullet is rewritten before the user sees the draft; a `state=refuted` bullet is
re-derived rather than filed. Like every arm of that skill it is best-effort and never blocks issue
creation.

## Issue-body cache (issue #693)

A single implement run used to materialize the GitHub issue body many times over — six API
fetches plus an inline paste into every dispatched subagent's prompt. Phase 1 §1.1 now fetches
the body **once per run attempt** into an in-tree cache file and the Phase 1–2 consumers read it
by explicit hand-off.

- **Path and content.** The cache is `.prflow/tmp/issue-body/issue-<ISSUE_NUMBER>.md`, anchored to
  the repo-or-worktree root (`git rev-parse --show-toplevel`, falling back to `pwd`). The producer
  uses the extracting `gh issue view … --json body --jq '.body'` form, so the file holds the bare
  body, never a JSON envelope. §1.1's own remaining metadata fetch drops `body`
  (`--json title,labels,number`), so the body is materialized in the orchestrator's context exactly
  once — by the cache read.
- **Per-run-attempt lifecycle.** The write is an unconditional delete-then-fetch on every entry
  path, so a resumed, re-triggered, or stall-backstop-auto-resumed run always writes a freshly
  fetched cache rather than reading a prior attempt's file. When §1.4's resume pre-check moves the
  run into a linked worktree, the cache is re-materialized under that worktree's root before any
  Phase 2 consumer reads it. It is removed at every terminal `Status` transition alongside the run
  marker (best-effort; a leftover file is inert because reads are hand-off-only).
- **Ignore precondition.** The in-tree write is preconditioned on an ignore rule already covering
  `.prflow/tmp/`; the run never creates one (a new dotfile would be an untracked file a blind
  `git add -A` would stage). The precondition is resolved by `scripts/preflight.py
  ignore-precondition`, which calls `git check-ignore` in-process — no new matcher command head and
  no new vendored-literal token. A denied or no-output invocation is an unestablished measurement
  routed to the stop path, never a decided degraded arm.
- **Hand-off only.** No consumer decides to use the cache by testing for the file in the tree; the
  path reaches a consumer only as an explicit parameter of the orchestrator's invocation, so no
  consumer can be induced to read a file the reviewed PR authored. Shell helpers read it through
  their `--body-file` arms (§1.2 `parse-acs.py`, §1.3.5 `preflight.py dependencies`); the §2.1
  `code-explorer`, §2.2 `code-architect`, and §4.1 `prflow:docs` dispatches carry an
  `Issue body path:` line naming the cache with an instruction to Read it, and stop pasting the body
  into the prompt (title and labels stay inline). On the degraded arm where the ignore precondition
  is unsatisfied, the cache is not written: shell helpers revert to their `--issue` arms and the
  dispatches revert to the inline body paste, because `code-explorer` and `code-architect` declare
  no `Bash` tool and cannot fetch the body themselves.
- **Freshness dispositions.** The cache is a cost optimization applied only where staleness cannot
  change a verdict. Every verdict-bearing reader keeps fetching live, because a human can amend the
  issue mid-run: §4.1's Documentation-Needed gate (a stale snapshot would read as "no deliverables"),
  the Phase 3.3 inline review's issue-compliance check (`skills/review/phases/phase-0-setup.md` §0.4,
  whose live fetch keeps the **narrative** `issue_context` current — the acceptance criteria that
  check judges against are a separate resolution: §0.4 hands them to `scripts/workpad.py acs-resolve`,
  which prefers the workpad comment's set over the issue body's and fetches the issue body itself, so
  the live fetch here is not what keeps the criteria current), `/pr-description`
  (renders the acceptance criteria into the PR body), and `receiving-code-review`'s per-iteration
  re-read.
- **Regression guard.** `lib/test/lint-issue-body-refetch.py` (driven from `lib/test/run.sh`) fails
  the suite when any detected re-fetch form reappears at a cut-over site under `skills/implement/`;
  the re-paste regression is guarded by prose pins on the three dispatch sites.

The `/prflow:implement` orchestrator runs a set of mandatory **sweeps** in Phase 2.3, after writing the
code and before running tests. Each sweep closes a class of blast-radius bug that survives `git diff`
review because nothing is *syntactically* broken — the affected lines still compile, parse, or run;
they are only *semantically* stale. This doc is the internal-docs counterpart of that section: it
records *why* each sweep exists so the skill text can stay terse. A pre-write counterpart to these
sweeps runs earlier, in Phase 2.2's planning (§2.2.7, *Pre-flight coupled-site map*): before any §2.3
edit, the run enumerates the coupled sites a change will touch by searching for them first and recording
what it found — so a missed copy surfaces at plan time rather than as a red suite or a reviewer REJECT.

A **"Sweep selection (run first)"** preamble in the skill indexes which of these sweeps a given diff's shape warrants. Its trigger shapes are **substrate-agnostic** — a contract, a peer-replicated rule, or an enumerated-set membership can live in prose/`SKILL.md`/doc/config as much as in code, so the preamble classifies by *what the change replicates across sites*, not by whether it is code: an add-only diff that replicates nothing across sites runs just the six always-on sweeps (2.3.3/2.3.4/2.3.4a/2.3.4b/2.3.5/2.3.6) instead of consciously dispatching the deletion/contract sweeps as no-ops, but an add-only prose/doc/config diff that adds a peer-replicated rule, an enumerated-set member, or a mirrored contract literal still runs the contract-completeness sweeps (2.3.0 / 2.3.0a / 2.3.0b). The index is **fail-safe**: each sweep's own heading (the *Triggers on* column below) stays authoritative, so a drifted or incomplete index can only over-select, never skip a warranted sweep.

## The sweeps

| Sweep | Triggers on | Closes |
|---|---|---|
| 2.3.0 Changed-contract | a change that **modifies** a signature, renames/moves a symbol, tightens a validator, alters a classifying predicate, **or relocates a prose literal, heading, section, or file path** | dependent sites left on the *old* contract (other predicate branches, sibling callers, fixtures/assertions) — and, for a relocation, an existing citation of the content's *old* location (a `run.sh` pin, a docs cross-reference, a config-key list) left dangling at the vanished source |
| 2.3.0a Peer-checkpoint completeness | a change that **adds** a rule/clause/guard/invariant which has *co-equal peer sites* (two or more sites that must each enforce the same rule for it to hold, **or the paths through one unit of code**) | the rule stated at only *some* peers — a guard applied to one config-leaf branch but not its siblings, a read-only clause present at 2 of 4 gate checkpoints, a fallback in the selection predicate but not the parallel derivation. A step-0 classification selects the enumeration: a shared-marker **search** for textually co-locatable peers, a **call-edge trace** for a control-flow property (a rule the run cannot classify takes both arms, with the trace bounded to one hop), and the traced arm's note records the unit and the technique's reach rather than a match count |
| 2.3.0b Enum-enumeration reconciliation | a change that **adds a value to an enumerated value set** (a new enum/string-union member, status, kind, verdict, or `fix_decision`) | enumerating sites left stale — a doc/comment list of the value set, or a fall-through consumer (an `else`/`default`/`// null` arm) — that the code-site sweeps (2.3.0's dependent grep, 2.3.0a's peer search or call-edge trace) miss, even when the runtime stays correct because the new value rides an intended fall-through |
| 2.3.0c Operand-trace | a change that **adds a guard, predicate, validator, or coverage invariant** in code, **or** ships **agent-executed imperative prose stating a policy** (a `SKILL.md`/`phases/*.md` command block) | a guard whose comparand comes from the diff's *own* code (the blind spot 2.3.4 carves out and 2.3.0a/2.3.0b's peer/enum focus misses), and a stated policy whose operand no step produces (an inert guard). Trigger (a) demands a four-column operand table — comparand, producer (file+line), emitted on every selected path?, and the load-bearing *what OTHER inputs produce the same value?*; trigger (b) demands every policy name its observable operand, its producing step, and a route for every outcome including failure |
| 2.3.0d Describing-prose reconciliation | a change that **removes** a member from an enumerated value set (code-defined *or* doc-enumerated — a workflow trigger list, a config-key set, a permissions list), **or weakens a universal it previously asserted** by softening, scoping, or removing it | prose the change made false **without editing it** — describing prose that names no member literal (where the set came from, how many members it has, what they are for), which 2.3.0b's member-literal search structurally cannot reach, and surviving copies of a weakened claim still asserted at full strength in another directory. Its enumeration is repo-wide and reuses §2.3.0's *Relocation is a contract change too* step 2's `grep -rnE` + `tr -s '[:space:]' ' '` normalization; an absent tool or a denied search records an **unrunnable** outcome naming the covering backstop, never a clean pass — an obligation the §2.3 preamble binds to *every* search-based sweep, not to this one alone. Precedence: an addition is 2.3.0b's, adding a peer-replicated rule is 2.3.0a's, and a **rename** is assigned to 2.3.0b alone |
| 2.3.1 Orphaned-setup | a **deletion** of code | setup lines (a dependency fetch, lookup, computed local, import) whose only consumer was the deleted code |
| 2.3.2 Stranded-dependents | a **deletion** of a method, file, route, or page | references *outside* the diff the deletion stripped of purpose (callerless public methods, dead args, surviving inbound links) |
| 2.3.3 Convention-compliance | any code the diff **added or modified** | `CLAUDE.md` convention violations in touched code |
| 2.3.4 Boundary-assumption | any diff that **depends on** a fact about something it does not own | claims about a dependency version, the supported runtime, a sibling producer's output, the real host, or an **external tool's output string/message/exit code** that were asserted from memory instead of verified — the external-output kind carries a reproduction obligation (paste the observed bytes; doc prose is not evidence) and the companion outcome-verification rule (a precondition check never stands in for verifying the consumed outcome). In-diff guards carved out here route to **2.3.0c** |
| 2.3.4a Self-authored-claim reconciliation | any diff that **authors** a behavioral claim in prose — internal/external docs it edits, or code comments it adds/changes | a sentence or comment that asserts what the shipped code does but contradicts the actual code path (including the diff's *own* new code, which 2.3.4 carves out) — caught by tracing each authored claim to the code, following dispatch into pre-existing helpers the diff calls |
| 2.3.4b Coverage-claim enumeration | any diff that **adds prose** — rule surfaces, docs, comments, `.changeset/*.md`, `CHANGELOG.md` | a **coverage universal**: a sentence asserting a universal about *this change's own coverage* ("every call site is updated", "all four arms are handled"). It describes the change rather than the shipped code, so 2.3.4a's population does not select it, and 2.3.4a's method — trace and read — could not close it anyway. Seeded by `scripts/stale-prose-lint.py`'s recognition-only coverage-universal tier run in its `--worktree` mode over the §2.3 sweep operand (the merge base → working-tree branch delta), and closed by grounding each claim one of three ways: pinned by an executed enumeration, scoped, or removed |
| 2.3.5 Simplification & Efficiency | any code the diff **added or modified** | avoidable complexity (redundant/derivable state, copy-paste variation, deep nesting, dead code) and wasted work (redundant I/O or computation, needless sequential ops, hot-path/startup cost) that only show up once the change is assembled |
| 2.3.6 Error-handling & silent-failure | any code the diff **added or modified** | silent failures — swallowed or over-broadly-caught errors, unjustified or fail-open fallbacks, mock/stub leaks, generic/misdirected breadcrumbs, plus two fail-open guard classes mirrored from the reviewer extension: the **existence-standing-in-for-outcome** shape (verify the outcome, not the precondition) and the **un-guaranteed-tool derivation** shape (a value that decides a selection or an emission must not be derived through a tool the project's preflight does not guarantee, cosmetic sanitization excepted when it fails closed) — all shipping clean because the happy path works and only firing on an input the tests don't exercise |
| 2.3.7 Collection-cardinality | a change that **adds a collection output with ordering, dedup, or aggregation logic** (a sorted list, deduped set, grouped/counted tally, tie-broken ranking) | a cardinality-sensitive output shipped with only a single-element test, which exercises no ordering/dedup/aggregation logic — closed by a multi-element test case (order-sensitive elements + collapsing duplicates) that would catch a wrong sort key, mis-keyed dedup, or off-by-one tally. Trigger-gated, **not** one of the always-on sweeps |

2.3.1–2.3.3 trigger on *deletion* or *addition*. **2.3.0** fills the gap for *modification*: changing a
contract is just as blast-radius-prone as deleting one, but it is harder to catch because every
dependent site still compiles. The common failure mode is fixing the originating site but not its
siblings — a predicate corrected in one branch but not the others, one caller that plumbs a new
per-request input while its sibling sharing the same object does not, or a fixture/assertion left
encoding the old contract. **2.3.4** is orthogonal to all of the above: it is not about the diff's own
consistency but about facts the diff *relies on* across a boundary it does not control.

**2.3.0a** is the *additive* twin of 2.3.0. Where 2.3.0 watches a *modified* contract for stale
*dependent* sites (caller→callee), 2.3.0a watches a *newly-added* rule for incomplete *co-equal peer*
coverage: a guard, validator clause, read-only precondition, classification tripwire, or fallback that
must hold at every member of a peer set but lands at only some. The distinction matters because the two
fire on different diff shapes and enumerate different things — 2.3.0 greps for the old
symbol/predicate/contract across dependents; 2.3.0a's enumeration is selected by a step-0 classification of
the rule it just added. A rule whose peers are *textually co-locatable* greps for their *shared marker* (the
clause keyword, the guarded variable, the predicate name, the step heading) to enumerate the set the rule must
blanket. A rule that is a **control-flow property** — an invariant quantified over the paths through a unit of
code rather than over textually similar sites, such as "every terminating path writes an outcome line" — has a
peer set no shared marker can reach, because a path terminating inside a helper the unit calls is spelled
nowhere in that unit's own text; the sweep establishes it by **tracing the unit's call edges**, and a rule the
run cannot classify takes both arms, with that trace bounded to one hop on every edge kind the trace
arm names — an undecided
classification leaves the co-locatable case live, so the trace alone would discharge it vacuously. The
traced arm records the unit and the
technique's *reach* instead of a match count, so a search result on a control-flow rule can no longer read as a
closed set — the motivating instance being an abstract-syntax-tree walk of one function's own body, stronger
than any text search and still blind to two terminating paths reached through helpers, whose clean count
shipped as evidence the set was closed. **A disclosed residual, stated because the traversal's own reach is
narrower than its obligation:** a callee reached through dynamic dispatch, a registry or decorator table, a
callback passed in, or an inherited override is not enumerable by reading the source, so the traced note names
which edge kinds it established and which it could not — narrowing the blind spot to a declared one rather
than closing it. The weekly retrospective surfaced
this as a recurring `incomplete-edit` sub-pattern distinct from 2.3.1/2.3.2 (deletion-triggered) and
2.3.0 (modification-triggered): a read-only clause present at 2 of 4 gate checkpoints, a config-leaf
warning on the object path but not the scalar/array paths, a `closingIssuesReferences` fallback in the
selection predicate but not the parallel workpad derivation — each correct in isolation, each described
by its PR's prose as if it held everywhere, each surfacing only as a REJECT or post-bot fix. A deliberately
exempt peer is allowed when recorded with a `--note`; only a *silent* asymmetry is the defect. It is
numbered 2.3.0a (not renumbering 2.3.1–2.3.6) for the same presentational reason the higher-numbered
sweeps (2.3.6, then the trigger-gated 2.3.7) are appended rather than renumbering their predecessors.

**Where the traced arm stops reading.** The trace states a bound for each direction it follows rather than one global depth. A **callee** edge is read until the reading reaches a construct that ends or leaves the unit being read, or reaches a unit already visited on this traversal — an already-visited unit is recorded instead of walked again. A **caller-direction** edge, meaning an error the unit raises and a caller handles, is followed to the first enclosing handler and no further. A **handler-installation** edge — a shutdown or signal handler, or an at-exit registration — is followed to the handler body and no further. A **scope-exit** construct is read as a terminating path of the unit that encloses it and is not followed past that unit. Those four bounds are what make a cycle and a mutually recursive pair terminate, and they are why the arm is a bounded read rather than a walk of the whole program's call graph. The path shapes the arm has to cover are, at minimum, a terminating path, an early return, and an error exit; and because a terminating path can be reached without a direct call, the arm also reads the raised-error, handler and scope-exit edges above.

**The traced arm is not code-only.** Where the swept unit is prose rather than code — a phase procedure, for example — its step-to-step transfers, its gated reference reads, and its terminal, blocked and degraded arms are read as its call edges, and the enclosing procedure file is the unit. A prose substrate therefore has a trace to run, rather than falling back to the search arm's match count on a rule the search arm cannot establish.

**One question the traced set asks once.** Once the trace has established the peer set, the sweep asks whether a *single* enforcement point would hold the invariant for every path the trace found, including the paths reached through other units, and records the answer in the same `--note` that carries the reach disclosure. A negative answer discharges the question outright. A positive answer is discharged by installing that enforcement point and naming, in that note, which paths it covers; those paths meet the apply-at-every-member obligation through it and need no per-path exemption. Asking the question later, once per path, is how a rule ends up restated at every path that could have carried it in one place.

**How the traced arm's outcome is graded, and how it divides from 2.3.0.** Only a fully resolved traversal earns the claim that the peer set is *closed*. The other three outcomes — an unresolvable edge that falls in one of the four declared reach classes, a traversal bounded to one hop because step 0 could not classify the rule, and the preamble's unrunnable arm for an edge that is neither resolvable nor placeable in a declared class — each withhold that closure claim while still requiring the rule at every member already reached; a search arm running on the same rule keeps recording its own match-count evidence regardless. The division of labour with 2.3.0 is stated so the two do not overlap: a *changed* contract's dependent call sites remain 2.3.0's, and the traversal for an *added* control-flow rule's peer paths is 2.3.0a's, caller-direction and handler and scope-exit edges included. So the caller→callee wording above separates the two sweeps by the diff shape each fires on, not by the directions 2.3.0a's trace is allowed to read.

**2.3.0b** is a second sibling in the 2.3.0 family, for a different additive shape: *adding a value to an
enumerated value set*. Where 2.3.0a watches a newly-added rule for incomplete peer coverage, 2.3.0b watches
a newly-added enum/status/kind/verdict value for *stale enumerating sites* — and, critically, it greps a
class the code-call-site sweeps do not: **doc/comment enumerations** of the value set and **fall-through
consumers** (an `else`/`default`/`// null` arm). The motivating case (#160) is the worked example: adding
`fix_decision: "severity-calibrated"` was behaviorally correct because the value rode an intended `else null`
fall-through in `verdict_for`, yet `lib/efficiency-trace.jq`'s and `docs/internal/efficiency-trace.md`'s prose
enumerations of the value set went stale until a shadow reviewer flagged them — "consistent behavior" is not
"reconciled enumeration." 2.3.0 greps *code* sites and 2.3.0a reaches them by search or by call-edge trace;
2.3.0b keys on the *observable* member literals
of the set (grep each known value, not a re-judgment) so the doc/comment and fall-through sites are caught at
implement time. A site deliberately exempt (a fall-through that *should* absorb the value) is allowed when
recorded with a `--note`; only a *silent* stale enumeration is the defect.

**2.3.5** is different in kind from the correctness sweeps above: it front-loads the *cleanup* lenses that the Phase 3.2 `/simplify` pass (`/code-review --fix`) would otherwise be the first to catch. `/code-review` applies four cleanup lenses — reuse, simplification, efficiency, altitude. The first two of those are *design* decisions and are settled earlier, at the **2.2.4 Reuse & Altitude plan gate**, because reusing an existing helper or picking the right altitude is far cheaper before the code is written than after. Simplification and efficiency are properties of the *assembled* diff, so they belong in a post-write sweep — hence 2.3.5. Together, 2.2.4 + 2.3.5 mean the in-loop `/simplify` should find little; when it finds a lot, that is the signal those two gates were skipped or rushed. `/simplify` still earns its place as a backstop because it sees the whole diff at once and catches cross-change duplication and dead code no single in-loop sweep would. One asymmetry the orchestrator must close at apply time: the `/simplify` cleanup agents see only the diff, never the issue's `## Acceptance Criteria` or the Phase 2.2.5 scope decisions, so a cleanup that reads as correct against the diff alone can directly violate the issue's deliberate scope (move a rule out of the file an AC pinned it to, trim an exclusion list an AC mandated). On the issue-context `/prflow:implement` path, Phase 3.2 therefore **triages each finding against the in-scope acceptance criteria and Phase 2.2.5 scope notes before applying it** — a finding whose fix would break an AC or the decided scope is skipped, with the AC conflict recorded as the skip rationale via `workpad.py --note`; non-conflicting findings apply as before. This is the apply-time analogue of the Phase 3.4 AC gate and exists only here (standalone `/simplify` / `/code-review` carries no issue/AC context and is unchanged). The one carve-out: a finding that conflicts with a now-*stale* AC a legitimate refactor superseded is not a silent skip but Phase 2.2.6 AC-rewrite territory — rewrite the AC text with a `--note` paper trail, then let the finding apply.

**2.3.6** front-loads the Phase 3.3 `silent-failure-hunter` review agent the way 2.3.5 front-loads `/simplify`. Its defect class — a swallowed error, an over-broad `except`/catch, a fallback that masks a failure (or fails *open*, defaulting an error to a success-shaped value), a mock/stub leaking into production, or a generic/misdirected breadcrumb — has no home among the other sweeps: it isn't a contract change (2.3.0), a deletion (2.3.1/2.3.2), or, in general, a documented `CLAUDE.md` rule (2.3.3), and it only sometimes doubles as a boundary claim (2.3.4) or added complexity (2.3.5). Baseline testing of the implement skill confirmed the gap: capable agents running 2.3.0–2.3.5 caught these defects only when they happened to overlap another sweep's trigger, attributed them inconsistently, and missed a pure swallow (a `gh … 2>/dev/null || true` that printed success for a comment that never posted) outright — exactly the findings `silent-failure-hunter` then raised in Phase 3.3. Making it an always-on, explicitly-named sweep gives the class a deterministic home so it is caught at implement time, not a review iteration later. It is a *correctness* sweep numbered to avoid renumbering its predecessors — the later trigger-gated 2.3.7 is appended after it under the same presentational convention; each sweep's intro references "2.3.0–2.3.N" of the lower-numbered sweeps, so the ordering is presentational, not an execution dependency. The sweep also carries a **per-branch-breadcrumb** sub-check: for any multi-branch no-op path the diff adds (e.g. "if A, stop; else find B; if B absent, stop"), it confirms each branch emits a distinct diagnostic naming which condition fired — two failure modes converging on one shared breadcrumb is flagged, a variant of the misdirected/generic-breadcrumb kind.

**2.3.7** (collection-cardinality) is trigger-gated, not one of the always-on sweeps: it fires only when the diff adds a **collection output whose value depends on cardinality** — a sorted list, a deduped set, a grouped/counted tally, a tie-broken ranking. That logic is invisible to a single-element test (one element is already sorted, already unique, already its own tally), so a green happy-path test with one input exercises neither the ordering comparator, the dedup key, nor the aggregation step, and a wrong sort key / mis-keyed dedup / off-by-one tally ships clean until a `pr-test-analyzer` review agent or a two-element production input hits it. The sweep requires a **multi-element** test case (order-sensitive elements plus collapsing duplicates) — a single-element happy-path test does not discharge it; where no automated test can drive the output, the obligation becomes the Phase 2.4 adversarial dry-trace over a multi-element input. It provenance-traces to the recurring missing-multi-row-test class (PR #468's `demoted[]` ordering/dedup behavior had no test until a review agent flagged it), the same way 2.3.6 homes the silent-failure class.

**2.3.0c** (operand-trace) sits with the additive 2.3.0a/2.3.0b family but targets a different blind spot: an operand nobody traced to its producer. Its code trigger owns exactly the diff's *own* guards that 2.3.4 carves out (2.3.4 verifies boundaries the diff doesn't own; 2.3.0a/2.3.0b watch peer sites and enumerated sets, not the operand a single guard reads), demanding a four-column operand table whose load-bearing fourth column asks *what OTHER inputs produce the same value?* — the "what else exits 2?" question that, unanswered, let a marker-deletion guard read `python3`/argparse/unopenable-script's shared exit-2 as "no workpad." When the comparand is *derived* (piped through a helper, a parse step, a subprocess, or any pipeline rather than read as a plain literal), the row additionally enumerates the malformed/empty arms the producer can emit — producer failure, unparseable output, wrong-type, valid-falsy/empty, missing key or file (the `CLAUDE.md` six-shape adversarial matrix) — and states the guard's decided behavior on each; a derived comparand with any arm left unenumerated fails open on exactly the malformed input the sweep exists to surface. Its prose-policy trigger fires on agent-executed `SKILL.md`/`phases/*.md` command blocks: a policy stated against an operand no step produces is an inert guard that silently no-ops on exactly the input it was written to gate, so every stated policy must name its observable operand, its producing step, and a route for every outcome including failure — **and place that obligation at the execution point it gates**, carrying at most a cross-reference from a thematic section, because thematic-only prose leaves the enforcement point with nothing to execute and the policy no-ops where it was meant to fire.

**2.3.0d** (describing-prose reconciliation) joins the 2.3.0 family as the *subtractive* counterpart the additive siblings leave uncovered. 2.3.0b arms on **adding** a member to an enumerated set and searches for the set's *member literals*; 2.3.0a arms on **adding** a rule with co-equal peers. Neither reaches the two edits that make a claim false **without editing the claim**: a **removal** from an enumerated set, and a **weakening** of a universal the code previously asserted (softening it, scoping it, or removing it). Both leave prose that still parses and still reads plausibly, so it ships clean and is rediscovered a full engine pass later — the motivating instance being a universal softened in one file while a byte-identical copy stood unchanged in another directory. **A disclosed residual, stated because the sibling instance in the same report is *not* covered:** an eleventh path *added* to a list that staled a comment describing where the list came from is an **addition**, so the precedence rule below routes it to 2.3.0b — whose member-literal search cannot reach a comment naming no member. That case therefore falls between the two sweeps and is covered by neither; closing it would need an addition-side describing-prose arm, which this change deliberately does not add. 2.3.0d's enumeration is therefore two searches rather than one: the set's *defining symbol/heading/path* (to reach describing prose naming no member) and the pre-change claim text recovered from the diff's deletion hunks (to reach surviving full-strength copies). Its domain is repo-wide by construction — a surviving copy characteristically lives in a different directory from the edit — and it reuses §2.3.0's *Relocation is a contract change too* step 2's `grep -rnE` + `tr -s '[:space:]' ' '` normalization rather than inventing a second technique for the identical search, because a hard-wrapped claim lives on no single line. Because `tr` is *granted* on the implement and command profiles but is **not** preflight-guaranteed, a missing tool empties a pipeline instead of failing it, so the sweep carries an explicit **unrunnable arm**: an absent tool or a denied search records an unrunnable outcome naming the covering backstop (the Phase 3 review pass; inside the fix loop, Step 3.5 plus the convergence shadow) rather than a clean pass. That arm is the §2.3 preamble's, binding every search-based sweep; 2.3.0d restates it in its own body, as 2.3.0a now does for its unresolvable-call-edge route. Precedence is stated so no *membership change* draws two sweeps with different search domains: an addition is 2.3.0b's, adding a peer-replicated rule is 2.3.0a's, and a **rename** — an addition and a removal at once — is assigned to **2.3.0b alone**, whose member-literal enumeration already reaches both the vacated and the arriving literal.

**Phase 2.4** splits the "no automated test" verification by one question — *does this text enter a model's context as instruction?* Human-read prose keeps the adversarial dry-trace; prose that becomes an agent's prompt (an injected block, a composed prompt, a `SKILL.md`/`phases/*.md` command block) gets a `writing-skills` subagent RED/GREEN micro-test with a no-guidance control, because a dry-trace cannot catch a prompt-prose defect — the text reads perfectly while steering the model wrong. The trigger is what the text *becomes*, never where the file lives (a block in a script or workflow YAML that becomes a prompt still takes the micro-test).

## The final full-suite gate: the parallel coordinator (issue #1086)

Focused modules are the iteration default; where a run discharges its completion gate by an
in-environment whole-suite pass — the cloud implement tier, and any local run deliberately
choosing one — the command is `lib/test/run-parallel.sh`. (Since issue #1607 the
local/interactive tier's own gate is a CI reading for the pushed commit, per `CLAUDE.md`'s tier
ladder, so the coordinator is that tier's diagnostic instrument rather than its gate.) It runs the same tested partition CI shards — its launch
population comes from `lib/test/run-shard.sh --list-shards`, so it is derived rather than
copied — concurrently **inside the current checkout**, and recombines it through the existing
`lib/test/shard-tally.py` tally protocol. `lib/test/run.sh` is unchanged and remains the serial
primitive: the `monolith` shard runs it, and the documented uncovered-surface fallback still
names it.

**Why it is a bare token.** The cloud permission matcher refuses caller-side environment
assignments, redirects, pipelines, interpreter prefixes and background syntax even when the
command head is granted (issues #363/#401/#455). Every one of those lives *inside* the
coordinator — the per-shard `TMPDIR` and tally exports, the log capture, the background
launches, the capacity arithmetic, the aggregation — so the cloud tiers invoke exactly
`lib/test/run-parallel.sh` with nothing around it, granted through
`prflow_implement.allowed_tools` and `prflow.allowed_tools`. Those grants resolve from
the **default branch at trigger time**, so a grant is inert on the PR that adds it
(`docs/internal/cloud-setup.md` states the general rule) — until it lands there, the cloud tier's
final gate falls back to a whole-suite form already granted on the default branch, and an
invocation that produces no output at all is a denial, not an empty result. The local/interactive tier reaches
the same coordinator through the `DEVFLOW_BASH` invocation-layer selector `CLAUDE.md`
documents, because on that tier the shell that *runs* a `.sh` helper is chosen at the
invocation boundary.

**When the ceiling terminates the coordinator, decompose it (issue #1132).** The cloud
implement tier terminates any single command at the ceiling `devflow-implement.yml` sets on
the Claude step — `BASH_MAX_TIMEOUT_MS`, raised via the step's `settings` input to 20 minutes
(issue #1179) from Claude Code's 600000 ms default so the coordinator can run to a verdict.
That value is fixed at *authoring* time by the workflow, but it is not escapable *in-run*: an
agent mid-run cannot raise its own ceiling (`devflow-implement.yml` sets
`CLAUDE_CODE_DISABLE_BACKGROUND_TASKS: "1"`, and `nohup` is ungranted **to the agent's Bash
tool** — the workflow's own `run:` steps are a different execution context and do use it, for
the credential refresher), so decomposition stays the in-run route whenever a command is
terminated at whatever ceiling the workflow set. A run in that
position does **not** downgrade its evidence to a focused module — the Phase 4.3 completion
gate takes a whole-suite result, and the prompt extensions state that scope once. It instead
does what CI already does to satisfy the same required check: **first run the pre-launch
generated-artifact drift preflight once with `lib/test/run-parallel.sh --preflight`** (issue
#1288) — a read-only, sub-second check nowhere near the ceiling that launches no shard and
carries the SAME verdict contract the coordinator applies before its own launch, so the
recombined whole-suite result carries the same drift check the coordinator does. It exits 0 to
proceed (clean, or a fail-open inconclusive result) or non-zero on a positively-attributed
drift, in which case you regenerate the artifact(s) under their governing policy and commit
before launching any shard, rather than paying the full sharded suite to rediscover the drift
as an ordinary shard-assertion failure. Then enumerate the partition with
`lib/test/run-shard.sh --list-shards`, run each shard as its own command (CI observes
1m44s–4m48s per shard, comfortably inside the ceiling), and recombine the run's own tally
paths through `lib/test/shard-tally.py combine`, passing `--require-shards` derived from that
same `--list-shards` population so the recombination is reconciled against the partition **by
name** (issue #1289) — a missing, unexpected, or duplicated shard fails closed naming the gap.
Both helpers are granted in
`prflow_implement.allowed_tools` and `prflow.allowed_tools` for exactly this reason; before
that grant existed, a run that took the strict reading had no sanctioned discharge at all and
its shard attempts were silently denied. Only an unobservable *recombined* run terminates the
work, and it does so as the `execution-ceiling` Blocked terminal that Phase 4.3 names —
distinguishable in the workpad from a run that observed a failing suite.

**Retained logs, not truncated ones.** The aggregate is compact by design — bounded by the
`DETAIL_CAP` constant `lib/test/run-parallel.sh` passes to `shard-tally.py combine`, per
detail class, with the omitted count announced — because its other reader is a model's
context window. Nothing is lost: every shard's complete captured log is retained under the run
root the coordinator prints, which is the artifact a failing gate is diagnosed from and the one
the `Verification evidence:` marker records (on every tier that maintains a workpad since issue
#1249, cloud `/prflow:implement` included). That also removes the pre-#1086 caller-side
`> .prflow/tmp/verification-<N>.log 2>&1` capture: the coordinator retains the launch itself.

**Same-checkout isolation.** Each shard gets a private tally directory under a *fresh* run root and a private
`TMPDIR` allocated outside the checkout (a shard's `mktemp -d` fixtures must not land
inside a git working tree), and aggregation is handed this run's explicit tally paths rather than
a `--scan` of the shared parent — so a stale sibling run's tally can never satisfy the current
invocation's missing-shard floor. Concurrency is bounded by one `python3`-derived process
budget (capped at eight, overridable with `DEVFLOW_SUITE_PROCESS_BUDGET`, failing closed to a
serial-but-complete width 1), out of which the nested Python pool's width is **reserved**
rather than added, so the real process count matches the scheduler's.

**Same-checkout concurrency is a new exposure, not a proven-safe one.** CI has only ever run these shards in separate checkouts on separate runners. The coordinator isolates each shard's `TMPDIR` and tally directory, but not repo-relative writes a shard's own assertions may make, and its whole purpose is to produce the CPU saturation under which a load-sensitive assertion's slack budget is tested. This repository keeps **no known-flake set**, so a red coordinator result that a serial `lib/test/run.sh` does not reproduce is a defect to diagnose — in the assertion's isolation or its slack budget — never something to re-run and hope on. The coordinator's own header states this beside the code.

**Single-runner agent timing is not multi-runner CI timing.** CI isolates each shard on its own
runner; here they share one host's CPU, memory, checkout and process namespace. The
coordinator's `real` time is therefore the slowest shard *under contention with its siblings*,
and CI's per-shard step durations are not a prediction of it. Any migration decision that rests
on speed rests on a same-host measurement of both commands, never on CI's numbers.

## Changed-contract sweep (2.3.0) and the post-merge re-sweep

The skill spells out the three checks (predicate variants, sibling call sites, fixtures/assertions).
The *why*: the common failure mode is fixing the originating site but not its siblings — and those
siblings still compile, so `git diff` review misses them.

The sweep must also be **re-run after any merge or rebase of `main`** — the skill's Error Handling
conflict-recovery path (`git pull --rebase origin {branch}`) and anywhere else the run pulls in
`main`. A clean textual merge is not a clean semantic merge: `main` can arrive with a fixture, call
site, or assertion (often from a concurrently-merged PR) that the change's new contract now rejects,
merged cleanly with no conflict. A newly-arrived violating site is a defect in *this* PR, not a
follow-up.

**Relocation is a contract change too (issue #661).** Moving a *prose literal, heading, section, or
file path* to a new location while an existing citation of its **old** location survives — a
`lib/test/run.sh` pin, a docs cross-reference, a budget cell, a config-key list — is the same
stale-dependent defect: the citation still parses and only *semantically* dangles at the vanished
source, so it ships clean and is found reactively (a suite red at Phase 2.4, a `/prflow:review`
REJECT — issue #530/PR #539 is the archetype). The hardened §2.3.0 therefore arms on a relocation
and, at the sweep's existing point, recovers what moved from the §2.3 sweep operand (the merge base →
working-tree branch delta; a **content** move from its deletion hunks; a **file-path** move's old path
from its `--name-status` projection, a rename record's `R### old new` source or a `D old` deletion
entry), then enumerates
the old-location citations in **both** forms — those that *quote the recovered content* (with a
**whitespace-normalized** search plus a rendered-surface check, so a wrapped-adjacent-literal citation
on no single line is still found, the #375 blind spot) **and** those that *name the vacated
path/anchor/heading* (which a content search never sees) — and reconciles each against the
destination. This ports the authoring-tier discipline of `.prflow/prompt-extensions/create-issue.md`'s
Interaction-surface map down to the implement tier; the cloud-safe search uses `grep -rnE`/`tr`, never
`git grep` (ungranted in the implement profile). The deterministic desk-time net is
`lib/test/pin-corpus-lint.py`'s `--reloc` relocation diagnosis, which turns a bare `ABSENT` pin into
`relocated to <file>` (or a genuine `deleted`, fail-closed on an unresolvable search set).

## Boundary-assumption sweep (2.3.4)

The five boundary kinds and how to verify each are in the skill (and summarized in the table above).
The *why*: these bugs ship clean and pass the author's own tests — because the tests encode the same
wrong assumption — so a green run is not confirmation, and a test assertion *about* a boundary is
itself an unverified claim. A boundary that genuinely cannot be verified in-environment is never
asserted as true: it is recorded with a `--reflection` note and, only when a specific acceptance
criterion's verification depends on it, retagged `(post-merge)` — and that retag is itself gated (see
*Acceptance-criteria gate* below): an unverifiable external boundary is the one genuinely-live case the
gate accepts, never a runnable-but-blocked or self-claim-confirming criterion.

## Self-authored-claim sweep (2.3.4a)

2.3.4a is the enforced twin of 2.3.4 on the *output* side. 2.3.4 verifies the facts the diff **depends
on** across boundaries it doesn't own; 2.3.4a verifies the behavioral claims the diff **authors** — the
sentences it writes into internal docs, external docs, and code comments — against what the shipped code
actually does. The trigger is the authored prose, not the code's boundaries, and that is why it is a
separate sweep: 2.3.4 explicitly carves out claims about *code defined in the same diff*, so a comment
that misdescribes the diff's own new function, or a doc sentence the diff adds that overstates a
guarantee, is precisely the blind spot 2.3.4 leaves and 2.3.4a closes. These contradictions ship clean —
the prose reads plausibly, the code compiles, and the author's tests assert the prose's *intent* rather
than the code's *behavior* — so the engine reconciles every authored claim before commit: it traces each
claim to the actual code path (following dispatch into pre-existing helpers the diff calls) and, on any
divergence, **the code is the fact** — it fixes the code or rewrites the claim, and never commits the
unreconciled pair. The **PR body** is reconciled in Phase 4.2, where the body is authored
(it does not exist at commit time) — there the sweep broadens into a **three-class claim audit**, each class
naming its own comparand and recording its own workpad outcome (an explicit clean-pass note when a class
finds nothing): **behavioral** claims traced to the shipped code path (the same trace 2.3.4a does),
**verification** claims (`## Test Plan` rows and "covered by" / "pinned by" / suite-tally assertions) bound to
the tests actually present in this diff, and **artifact-existence** claims (a follow-up issue, a filed
deferral, a linked issue/PR, a changeset) bound to the artifact's own resolvable identifier. Each failing
claim is fixed-or-rewritten under the same **code-is-the-fact** rule before finalize. The sweep also carries a **clean-path-evidence** sub-check: for any
step the diff adds that claims to enumerate, verify, or scan a set, it confirms the step logs a summary
(count, result) even when nothing needs changing — a silent no-op step is indistinguishable from one that
never ran, so the human reviewing the run cannot tell it executed. It also carries a **mirror-fact
drift-proofing** clause: any comment the diff adds or changes that carries an exact count, an enumerated list
of sites/values, or a predicate-restating scope word is rewritten or removed per the §2.3 authoring
treatments before commit — even when it is currently accurate — because an accurate-today mirror-fact comment
is precisely the one that silently rots once a later change updates the code and not the comment.

Beside the mirror-fact clause the sweep carries two further always-on steps, both enforcing the §2.3
prevention-only comment standard on the diff's own added or changed comments. The **prevention** step
moves or deletes, before commit, every comment that names no specific wrong change it prevents — including
one that is accurate, interesting and true, because an explanation no reader would mis-edit without is not
prevention. The **restatement** step forbids a fact stated in one comment the change adds or modifies from
being restated in another, keeping the docstring as the retained site where one states it; it is distinct
from the mirror-fact step — that one governs a comment mirroring the *code* beside it, this one a comment
mirroring *another comment*, and neither subsumes the other. Each step carries its own routing and
fail-closed arm in its own text: displaced rationale goes to the project's internal-documentation location,
and where no such location is available to the run the comment is compressed to the three-line cap or
deleted rather than silently kept at length — self-contained so the fix loop, which imports the sweep
bodies from the sweep-selection preamble down, carries them intact.

## Coverage-claim enumeration sweep (2.3.4b)

2.3.4b exists because a **coverage claim is a different claim type from a behavioral one**, and the
difference is not a matter of degree. A behavioral claim asserts what the *shipped code* does, so it has a
code path to trace — which is exactly what 2.3.4a prescribes, and the trace either confirms it or does not.
A **coverage universal** asserts something about *this change itself*: that it reached every member of some
set — "every call site is updated", "all four arms are handled", "exactly these files". There is no code
path to trace, because the sentence is not about code behavior at all; it is about the extent of the diff.
So 2.3.4a's population — *"any behavioral assertion the diff introduces about what the shipped code does"* —
does not select it. The claim reads as project description rather than behavioral assertion and slips
through the one pre-commit sweep that could have caught it.

Nor would 2.3.4a's *method* have closed it if the population had. Tracing and reading verify a claim against
a referent; a coverage universal's referent is a **set the reader has to enumerate**, and reading the
sentence back tells you only that it is well-formed. The engine already states this on the review side —
`agents/checklist-generator.md` calls such claims *"the highest-value verification targets precisely because
a reviewer reading the claim confirms nothing — only a failed attempt to falsify it does."* Before 2.3.4b,
the authoring side prescribed the reading method the review side had already declared insufficient.

**Enumeration is what closes it.** The sweep's obligation is that every coverage universal in the diff's
added prose is grounded one of three ways — **pinned** by an *executed* enumeration of the set the
quantifier ranges over, **scoped** to what the change actually covers, or **removed**. The first is the one
that does real work: run the search, read what it returned, and write the sentence against that result
rather than against your recollection of the change.

Two halves ship together. The **detector** is a recognition-only tier in `scripts/stale-prose-lint.py` —
non-gating by construction, resolving no referent and never affecting the exit code — that recognizes a
**coverage-scope** token adjacent to a coverage-referent noun and emits one row per recognized line under
the `CU` rule token. The scope set is deliberately wider than the universal quantifiers (`only`, `complete`,
`entire`, `whole` are scope claims about the change's own coverage and are recognized too); both closed sets
are specified authoritatively in the helper's own header; the four tokens named here are an illustration of
the widening, not a transcription of the set. It gives the sweep an *executed* seed list rather than a remembered one, and it costs
no model tokens. It runs in the helper's `--worktree` post-image mode, because the shipped `--rev` mode
resolves the post-image through `git show <rev>:<path>` — which on an uncommitted tree names the *pre*-change
file, so a modified file's added lines fail their content anchor and a **new** file (the `.changeset/*.md`
shape, always new) resolves to nothing at all. Two properties of the invocation are load-bearing rather than
incidental. It **never stages** — no `git add -A`, no intent-to-add — because the fix loop that inherits this
sweep stages by explicit path in the same iteration, and an unscoped stage here would land unrelated
working-tree state on the branch; the untracked leg therefore names each new file the change authored rather
than enumerating the working tree. And it accounts for **three** outcomes, not two: rows produced, a clean
pass (zero rows *and* helper exit `0` *and* a producer that actually emitted hunks), and everything else — an
errored, refused, or empty run — recorded as degraded. An empty row set is the same observable as a sweep
that never ran, so without the third conjunct a run that examined nothing would read as a clean discharge.
The **obligation** is the sweep prose itself, and it is what
actually closes the claim: the detector's rows are a **floor**, not the population, so a universal the
closed noun set does not recognize stays in scope and is grounded the same way.

The carve-out is deliberately narrow — **extensional, not grammatical**: mandated-verbatim boilerplate, and
text the change quotes verbatim from another artifact. Prose the change *authors* into a shipped rule
surface is outside it, however rule-shaped it reads. That narrowing is load-bearing on this repository's
dominant diff shape (engine prose in `skills/`, `scripts/` headers, `docs/`, `CLAUDE.md`): a broader second
kind would be coextensive with the population the sweep exists to grade, exempting it wholesale while the
workpad note read as a clean discharge. The declared `stale-prose-lint: rule-text` marker follows the same
logic — it suppresses the detector's seed row (and emits a visible audit row in its place, so a marker that
lands on a real claim stays greppable in the lint output), but it controls **detector noise** and never
discharges the obligation. Membership in the carve-out is what exempts.

## Review-engine hardening: forced operative-sentence pin note + inline-review observability backstop

Two guards close gaps the review surface let ship "green" and only a blinded shadow pass (or nothing) caught.

**Executable behavioral-regression evidence (Phase 2.3 + review-and-fix Step 3).**
Behavioral regressions are covered at a machine-observable interface: rendered output,
parser results, routing decisions, emitted state, or another executable contract. The
author breaks that behavior on a copy, observes the ordinary executable test go RED,
and records the evidence in the workpad. The former mutation-taking source-presence
helpers are retired and their audited-source census must remain empty. Typed structural,
count, and absence guards retain their narrower roles. Three mechanical suite guards
(`lib/test/pin-corpus-lint.py`,
self-scanned by `lib/test/run.sh`) now catch the blind spots the parents (#370/#371) had to
rediscover in a shadow: a **pin-in-comment lint** (a pin literal that also appears in a comment of its own
target inflates the count — its `.md` arm subtracts not only `<!-- … -->` regions but also the `#`
comments inside fenced ```` ```bash ```` code blocks of a skill bundle, issue #394); a
**wrapped-literal meta-guard** (a phrase assembled from wrapped adjacent string literals lives on no
single line, so a line-based `git grep` misses it — pin the rendered `--help`/stderr surface instead);
and the **`mutation-routing` declaration gate** (issues #666 and #810), a path-aware,
diff-scoped, fail-closed check over helper calls and direct positive source-presence
assertions. A wording-only pin protects a literal that can change without changing
executable behavior or a machine-consumed contract; new wording-only, secondary-prose,
documentation-presence, advisory-heading, and comment-presence pins are prohibited.
A permitted static boundary pin declares
`# structural-pin-ok: <category> -- <non-empty rationale>`, where the category is one of
`helper-contract`, `schema-config-vocabulary`, `security-credential-boundary`,
`machine-sentinel-provenance`, `routing-dispatch-contract`,
`lifecycle-state-transition`, `generated-artifact-identity`, or
`cross-file-phase-contract`. The required gate validates its audited-source population
against every registered module, requires the retired-helper census and checked-in
inventory to remain empty, and treats base, diff, enumeration, and scratch failures
as suite failures. Its raw-presence path
covers positive fixed-and-quiet `grep` checks against repository files and direct
file-text assertions in tracked or untracked `lib/test/test_*.py` leaves
(`assertIn`/`assertRegex`, or a literal `in` a `read()`/`read_text()` result). Python
leaf sites whose target cannot be resolved for inspection fail closed instead of gaining
an exemption from a typed marker. A move is exempt one-to-one only when its
classification is not weakened. The static-pin guards run over
`run.sh` itself and over every registered `lib/test/modules/*.sh` file, so pins that
module extraction moves out of `run.sh` stay covered (issue #591). Behavioral
regressions use ordinary executable tests instead of mutation-taking source-presence
helpers.

**Renaming a retained pin (issue #843).** A retained pin's assertion name is part of a
frozen identity, so renaming it in `lib/test/run.sh` without a declaration turns
`lib/test/test_residual_prose_retirement_manifest.py` RED. Declare the old-to-new
assertion-name mapping in `lib/test/pin-identity-refreshes.tsv` in the **same commit** as
the rename; the frozen manifest row itself is never edited. The ledger maps an assertion
name only, and only for identities frozen in the residual prose-pin manifest — the full
protocol, its scope limits, and how it differs from pin retirement are in `CONTRIBUTING.md`.

### Protected-asset taxonomy for existence-only pins

The maintainer-run classifier in `lib/test/pin-corpus-classifier.py` evaluates every
in-scope existence-only pin against exactly these eight protected-asset buckets:

| Bucket | Protected asset |
| --- | --- |
| `suite-internal` | A literal whose homes are all inside `lib/test/`, with no counted prose occurrence. |
| `required-copy` | A literal in a copy set that project policy requires to remain duplicated. |
| `boundary` | Code, workflow, or contract text on a security, credential, or interface boundary; this requires maintainer adjudication rather than path-only classification. |
| `generated` | A generated artifact whose byte identity is the contract. |
| `config-key` | A configuration key name. |
| `prose-sole-copy` | Prose with exactly one counted tracked home. |
| `prose-multi-copy` | Prose with two or more counted tracked homes. |
| `unclear` | The fail-closed result when the mechanical walk cannot establish the literal, its homes, or a semantic classification. |

Each inventory row records `bucket_mechanical` in the exact eight-value vocabulary,
although the mechanical walk deliberately never emits `boundary`. An `unclear`
mechanical result requires explicit adjudication, so `bucket_final` is one of the
other seven values. Classification belongs to the literal rather than the call site, so
every in-scope pin for the same resolved literal receives the same final bucket. The
classifier mechanically orders `suite-internal`, `required-copy`, `generated`,
`config-key`, and the counted-home prose buckets; declared boundary paths and any other
undecided case first become `unclear`. The committed snapshot, including each site's
mechanical and final bucket plus its retirement entanglements, is
`.prflow/logs/pin-corpus-inventory.tsv`.

`bucket_final` is not only descriptive: it is a **deciding operand** for whether an
existence-only pin may be retired (issue #876). A row whose `bucket_final` is one of the
two prose buckets and whose `counted_occurrences` is below two identifies a pin over
agent-executed prose no tool reads, which may be removed on its own; every other bucket
— including `boundary`, the value every shipped row carries between one re-adjudication
pass and the next — keeps the pin under the `# structural-pin-ok:` rule above. The ordered, first-match-wins arms, the
`counted_occurrences`-not-`homes` operand rule, the wrapped-home confirmation step, and
the fail-closed handling of a pin with no census row are stated once in `CONTRIBUTING.md`
under **Retiring existence-only pins**; adjudications are read from the inventory but
changed only in `lib/test/pin-corpus-adjudications.tsv`, never by hand-editing the
generated inventory.

**Phase 3.3 invocation, PR mode, and progress routing.** Phase 3.3 invokes the shared fix loop with the
draft PR number Phase 3.1 printed passed as a **bare leading numeric token** ahead of the flags —
`review-and-fix <pr-number> --push-each-iteration --issue <issue-number>` (the Skill-tool `args` string).
The bare numeric token binds `$PR_NUMBER` in each engine root; the `--issue <issue-number>` value binds
`$ISSUE_OVERRIDE` and is never mistaken for the PR number. The bare token is what puts the loop in
**PR mode** against the run's own PR — matching the phase file's claim that Phase 3.3 "operates on the
live draft PR created in 3.1." When Phase 3.1 printed no PR number (an empty or absent
`draft PR number:` line), Phase 3.3 **omits the token** and passes `--push-each-iteration --issue
<issue-number>` alone, falling back to current-branch mode; the bounded re-review carries the same
argument shape and the same omit-the-token arm, and the taken arm is recorded on the issue
workpad. Passing the PR number **activates** the PR-mode engine surfaces that stay dormant in
current-branch mode: **Step 0.5**, the branch-sync gate that makes the head-override diff precondition non-vacuous
(`skills/review-and-fix/references/loop-control.md`); **Loop Exit Checkpoint 3**, the base-branch update
that keeps the terminal pushed state current for the merge gate; **§0.4's `pr-identity-mismatch`
acceptance-criteria identity check** (the `--pr`-bearing acceptance-criteria resolution fence); and
**§0.6's stale-prose adjudication carry-forward join**. PR mode does not select the progress surface.
The caller-held `$ISSUE_NUMBER` is the only implement-origin signal, and the fix loop converts it to the
internal `progress_surface = workpad` binding. The public `--issue` value, the push flag, PR mode, and
workpad lookup results never select that binding. Each review iteration therefore suppresses the
run-keyed `prflow:review-progress` PR comment and ticks the ordered review-engine rows under the issue
workpad's **Review** phase instead. The rows cover diff classification, checklist generation, checklist
verification, review agents, aggregation and verdict, and terminal run completion. The final row belongs
to Loop Exit, not to an iteration's aggregation phase. Because `Bash(gh pr checkout:*)` is granted only
in the `command` profile — not in `implement` — Step 0.5's newly-activated `gh pr checkout` is refused
before it runs on the cloud implement tier and emits no `checkout-rc=` token; §0.5 answers that **absent
token** with its own head-ref and head-commit assertion (the sole authority on that arm), which
establishes no upstream tracking and relies on the caller (Phase 1.5's `git push -u`, Phase 3.1's push)
having established it. See [`cloud-setup.md`](cloud-setup.md).

**Inline-review observability backstop (Phase 3.3).** `review-and-fix`'s Loop Exit is what normally
persists a run's effectiveness record (`.prflow/logs/efficiency/<slug>-<run-id>.json`) and durable
workpad copy, derived from its per-iteration `iter-*.json`. But Phase 3.3 drives that loop **inline in the
orchestrator's context**, and a dropped Loop Exit then leaves those artifacts unwritten — the run
contributes nothing to `.prflow/logs/efficiency/`, which is `review-and-fix`'s own #1 documented "Common
Mistake," unguarded at this seam. So after the inline `review-and-fix` invocation returns — regardless of
verdict — the orchestrator deterministically runs the existing `lib/efficiency-trace.sh --persist` Layer-3
backstop (idempotent: it never re-derives an existing record, and with no `--workpad-dir`/`--slug` it
scans every run-scoped dir, which is exactly the "the orchestrator does not hold the loop's internal
slug/run-id" case). When even `--persist` has no `iter-*.json` inputs — the inline loop wrote no
per-iteration workpad this run, so the telemetry is genuinely lost — the orchestrator records a
`dropped-failed` reflection naming the gap rather than letting it vanish silently. The "no inputs"
detection is **this-run-scoped**: the orchestrator snapshots the pre-existing `iter-*.json` set
*before* driving the loop and, after, records a loss only when no *new* `iter-*.json` appeared
(`comm -13` against the snapshot). This matters on the local/interactive tier, where `.prflow/tmp`
persists across runs — a whole-tree presence check would let a prior run's leftover mask a genuine
loss. If the snapshot itself is missing, the detector degrades to whole-tree presence and emits a
distinct `::warning::` naming that degrade, since it can then mask a real loss behind a leftover
file. The backstop also catches the sibling failure mode where the loop *did* write `iter-*.json`
but `--persist`'s own record derivation/write step then failed silently (rc 0 by design): it
captures the invocation's stderr and greps it for `--persist`'s own `record not written`
breadcrumb (jq/mkdir failures) **and** its differently-worded disk/permission write-failure
breadcrumb — a single-literal grep would silently miss the latter — recording a second
`dropped-failed` reflection when either fires. The surface it does **not** cover is the
telemetry-branch write/push itself (`::warning::telemetry-branch: …`). The record is staged under
gitignored `.prflow/tmp/`; post-#469 a **degraded** branch write (or a CI staging-only run)
**retains** that staging root (only a *clean* write deletes it), bounded by a newest-N prune on the
next `--persist`; a *degraded* write additionally emits one `::warning::` naming its **absolute
path**, while a staging-only run retains silently, so on a **local**
filesystem a failed branch write is recoverable rather than lost. On an **ephemeral CI runner** the
staging tree does not survive teardown, so the cloud recovery path is the **uploaded workflow
artifact** the auto-review tier stages and uploads, which the trusted telemetry-push relay
(`telemetry-push.yml`, issue #489) downloads, validates, and pushes — not any on-disk copy the
ephemeral runner cannot retain (coupled with `skills/implement/phases/phase-3-fix-loop.md` and
`docs/internal/efficiency-trace.md`, which say the same — the shipped phase file names the relay
generically rather than by filename, because since issue #1423 the never-shipped-workflow lint
forbids a withheld-tier workflow name on the shipped prompt surface; do not re-sync the literal
into it). If the stderr capture itself can't be allocated
(`mktemp` fails), the backstop degrades to discarding `--persist`'s stderr entirely rather than
aborting — this disables the record-write-failure check for that run (the no-inputs case still
runs) and emits its own distinct `::warning::`, the same degrade-and-warn discipline as the
snapshot-missing case above. Because the
`APPROVE WITH UNRESOLVED SHADOW FINDINGS` path can drive a **second**, separate inline
`review-and-fix` invocation (the bounded re-review in §3.3), the orchestrator re-runs the whole
snapshot-then-backstop procedure around that second invocation too — a fresh this-run baseline
before, the persistence check after — so it is not left unguarded at the same seam. The retained
§3.3 executable boundaries are checked directly in `lib/test/run.sh` (#235 finding B, extended
by the #236 review); detailed phase prose is intentionally not existence-pinned.

**The backstop detects a dropped telemetry gap; the upstream fix is to not drop it (#296).** The
Layer-3 `--persist` backstop can only recover what was *written* — so the real protection is that the
per-iteration `iter-<N>.json` emit is a **non-optional obligation on every iteration, however the loop
was executed**: whether `review-and-fix` ran as a `Skill` invocation or was **hand-run via direct
`Agent` dispatch** on a degraded path, the record is still written, and always **with the Write tool,
never a shell `> .prflow/tmp/…` redirect** the cloud sandbox denies. A cloud `claude-code-action`
permission/sandbox denial is **not** the local-tier permission classifier and is **not** license to
leave the instrumented loop and hand-run the engine — on the implement job `Skill`, `Agent`, `Write`,
`efficiency-trace.sh`, `workpad.py`, and `config-get.sh` are all allowlisted, so the loop is navigable,
not blocked. This makes only the **effectiveness** half of the telemetry (dispatch/findings/verdicts)
recoverable on a degraded run; the **token/wall-clock cost** half is captured *live* by the loop. On
the **cloud** tier, issue #475's Layer-4 harness-side cost floor now reconstructs it deterministically
from `claude-code-action`'s `execution_file` once the loop is abandoned; the **local** tier still
ships no such backstop, so there it carries no deterministic guarantee, only the probabilistic
protection of staying on the loop. (That closed a gap in what was built, **not** a limit of the
platform: issue #437 observed that the cloud `execution_file` *does* carry the tokens, wall-clock, the
dispatch roster, and cost with zero agent cooperation, and that on the local tier the `Stop`
transcript's per-message token counts are **real** figures, not streaming placeholders — wall-clock
and the dispatch roster were *not* measured locally; see
[`docs/internal/execution-file-shape.md`](execution-file-shape.md).
An agent-independent cost floor is buildable — and #475 built the cloud half.) Note the deliberate implement-vs-runner asymmetry:
the read-only `review` runner uses `--permission-mode acceptEdits`, but `/prflow:implement` does
**not** — friction at the seam is reduced by single-statement leading-token helper forms and the Write
tool for scratch, never by widening the permission grant.

## Phase 2 criterion-lifecycle ledger: the producer side (issue #1674)

The exhaustive, criterion-level accounting of *how every resolved acceptance criterion will be
verified* is owned here, in the Phase 2 test-first gate (`skills/implement/phases/phase-2-sweeps-contract.md`),
not in the filed issue. The gate no longer decides testability only for the change as a whole:
**before any implementation code is written**, it enumerates every resolved workpad
acceptance-criterion row (the exact rows `scripts/parse-acs.py` mirrored into the workpad, never new
criteria inferred from narrative prose) and records each row's verification lifecycle route through
the existing test-first workpad note channel. The recorded routes are the criterion's *existing*
lifecycle dispositions, one per row:

- **Testable** → a named RED/GREEN automated assertion, preserving test-first RED-for-the-right-reason
  evidence. One assertion may discharge several rows when it directly proves each one, and a shared
  assertion lists every criterion it covers so grouping never hides a row the assertion does not prove.
- **Genuinely-untestable Phase 2 deliverable** → the existing Phase 2.4 reproducible dry trace.
- **Documentation criterion owned by the documentation pass** → the existing Phase 3.4 deferral, then
  the mandatory Phase 4.1 discharge — not a Phase 2.4 trace.
- **Genuinely-live** → the existing `(post-merge)` disposition and its pre-merge probe contract (the
  gated tag whose permitted conditions the Phase 3.4 gate below enforces), never a fabricated
  pre-merge assertion.

Recording the ledger through the workpad note makes any resolved criterion with no lifecycle route
visible **before implementation begins**, which is where an uncovered criterion is cheapest to catch.

**Ownership split.** This is the completeness half of a deliberate division of labor introduced by
issue #1674. `/prflow:create-issue`'s Testing Strategy is a **residual-risk supplement**: it no longer
restates a named assertion for every acceptance criterion, and records only cases that add information
beyond the criteria (bug reproduction, hostile-input pairing, new mutable-input-reader specialized-test matrices
with their `governing conventions consulted:` record, guarantee-class skipped-step paths,
retry/idempotency) — or a single concise statement that the acceptance criteria fully express the
verification contract when no residual-risk case exists. The Acceptance Criteria remain the exhaustive,
merge-gated specification. **Exhaustive criterion-level verification-lifecycle accounting lives here in
implement Phase 2**, and the Phase 3.4 gate below is its downstream verifier. The old "every AC maps to
a named assertion, and every assertion maps back" duty in the issue body is retired; do not reintroduce
it as current create-issue behavior.

## Acceptance-criteria gate: the gated `(post-merge)` tag (Phase 3.4)

### Two dispatched fresh-context verifiers, reconciled (issue #1575)

The gate does **not** resolve inline in the orchestrator's own context. The orchestrator drove Phase 2's
implementation and Phase 3.3's fix loop, so a gate it resolves in its own turn inherits its own
assumptions about what it built — the issue #1450 failure mode where the gate "ticks criteria satisfied
without re-verifying the shipped claim" — and a lone dispatched verifier that is wrong is silently wrong.
So Phase 3.4 **dispatches two fresh-context verifiers in the same turn** and routes the gate from their
**reconciled** per-criterion record:

- **`prflow:ac-evidence-verifier`** (`agents/ac-evidence-verifier.md`) establishes each in-scope
  criterion's verification evidence. It is the **only** one that runs an in-env verification command or
  touches the single-flight coordination, so the two verifiers never race the same command run.
- **`prflow:ac-claim-verifier`** (`agents/ac-claim-verifier.md`) checks the shipped code against each
  criterion's literal claim from the diff and current tree, and **executes nothing** — its declared
  `tools:` list (`Read, Grep, Glob`, with no `Bash`) is what enforces that inability to run a command.
  For a verification-command criterion it reads the command's *source* and checks that each clause of the
  criterion has a corresponding assertion in it; for a **measurement criterion** — one whose verification
  names a measuring instrument whose output is a value (a `wc -c` byte count, a `git merge-base`-driven
  list comparison) — it grades whether that instrument measures the criterion's literal claim (a byte
  counter for a byte ceiling → `satisfied`; a byte counter for a word ceiling → `unmet`), leaving the
  measured value itself to the evidence verifier, and so no longer reports `unestablished` merely because
  producing the value would require execution.

The orchestrator commits any uncommitted tree first (issue #1254's shared-checkout convention), resolves
the extension-governed facts the verifiers need (the test command, the single-flight helper paths, the
plugin root) and passes them **by value** into each dispatch prompt following the `[[PLUGIN_ROOT]]`
pattern — **neither verifier reads or reloads the consumer prompt extension**. Each verifier reports, per
criterion, one status (`satisfied`, `unmet`, or `unestablished`, never collapsing an `unestablished` onto
either) **and a `dispositions` object declaring what procedure it actually ran** (issue #1580): one entry
per named step of that verifier's own charter — `type-decided`, `command-run`, `single-flight`,
`evidence-recorded` for the evidence verifier; `claim-traced`, `command-source-read`, `evidence-recorded`
for the claim verifier — each written `yes` or `no` followed by a one-clause reason. A stated **`no` is a
permitted, fully discharging value**: the gate asks for a *stated* disposition, never a particular one. A
slot left unstated (or stated without a parseable verdict-plus-reason) is **undischarged**, not compliant.
Neither verifier dispatches a further subagent or writes anything to the workpad — the orchestrator
performs every mutation, and records the whole gate's dispositions durably on the workpad once, before any
criterion is ticked.

The orchestrator reconciles the two reports per criterion through `scripts/reconcile-ac-verifiers.py`.
**The slot gate resolves first, per side, before the two statuses are paired:** a side that left any named
charter step undispositioned is forced to `unestablished` up front, so a criterion **both** verifiers
called `satisfied` still blocks whenever either failed to attest — an abbreviated check cannot ride the
other verifier's agreement into `satisfied`. Only an *absent* record and a *duplicate-poisoned* one name no
undischarged slots: each is a vote never usably cast (already blocking on its own), not an attestation
failure. The paired rules then apply as before: **both verifiers agreeing records that status; any
disagreement records `unestablished`** (never resolved by preferring one verifier), and a **`satisfied`
never lands without an evidence pointer** from at least one verifier (a `satisfied` with no evidence, and
an unreadable/malformed report at exit 3, both reconcile `unestablished`). The reconciled record carries
`evidence_dispositions`, `claim_dispositions` and side-qualified `undischarged_slots` (e.g.
`evidence:command-run`) so what each verifier did survives the dispatch return, plus
`evidence_status_reported` / `claim_status_reported` — each side's own conclusion, retained even where the
slot gate overrode it, so a criterion blocking on a real `unmet` stays distinguishable from one blocking
only on an attestation gap. A reconciled `unestablished` **blocks exactly as an unmet criterion blocks** — so a
verification command that passes while its assertions exercise a *different* claim than the criterion
states reconciles `unestablished`, not `satisfied`. The routing below (the `(post-merge)` rules, the
documentation-AC deferral, the in-env verification rule, the `Blocked` escalation) is **unchanged in
substance** and now driven from the reconciled `status`/`evidence` rather than the orchestrator's own
inline check.

The Phase 3.4 gate requires every **non-post-merge** acceptance criterion to be verified before the run
advances. A `(post-merge)` tag exempts a criterion from blocking, so the gate enforces — as engine
behavior, not advisory prose — exactly **when** that tag is permitted: **only when the criterion
genuinely requires a runtime environment that does not exist during the implement run** (a live deploy
target, a real third-party endpoint, a production data path). The observable test is whether the
verification could ever run on the orchestrator host given the right tools; if it could, it is not
post-merge. Three cases are therefore never eligible and the gate refuses the tag for them:

- **Runnable-but-blocked (local tooling/environment gap)** — a criterion verifiable on this host but
  blocked right now by a denied command, a missing build tool, an un-spawnable helper, or a failed
  restore. A tooling gap is not a runtime-environment gap; it takes the existing **`Blocked`** escalation
  path (human handoff), never a silent post-merge pass. (A *verification command* that is **not granted**
  in the run's allowlist — its direct-form invocation refused before it could run — takes that same
  **`Blocked`** path, naming `prflow_implement.allowed_tools` (and `prflow.allowed_tools` for the command
  path) as the exact remedy: grant the command so the run can verify in-env, then re-run. It is **never**
  deferred to a CI result — see *In-env verification is the gate* below.)
- **Confirmation of a self-authored claim** — a criterion whose purpose is to confirm a behavioral claim
  the PR already asserts as true. It is runnable pre-merge by construction (the claim is about the shipped
  diff), so deferring it would defer the one check that could falsify the claim; the gate refuses the tag
  regardless of stated reason.
- **Self-reconfiguration verification** (issue #338) — a criterion whose only unmet precondition is the
  orchestrator's own session/harness/account being in the configuration the diff just shipped (a hook the
  diff registered now active, a flag/setting the diff added now enabled). The host *can* become a fresh or
  child session with the change active, so it is runnable pre-merge and never `(post-merge)`: it is run and
  evidenced — by an automated test driving the now-active code path, or by a separate/fresh session
  observing the change live — or it takes the **`Blocked`** path. Evidence produced while prototyping is
  captured in the workpad and PR body rather than re-deferred; the rule never mandates activating a
  blocking hook mid-run in the orchestrator's own session.

This is the gate enforcing "verified before merge" rather than trusting the run's narrative: a local
tooling gap can no longer be laundered into a post-merge pass, a self-claim confirmation can no
longer be deferred past the one test that would catch it, and a self-reconfiguration check can no longer
ride a "cleanest in a fresh session" rationale into an unchecked post-merge deferral. To keep every mid-run
`--rewrite-ac` retag auditable, `workpad.py` structurally rejects a `--rewrite-ac` call that appends the
`(post-merge)` tag (a single pair or a crafted multi-pair sequence) without a non-empty `--note` rationale
(issue #338). (The Phase 2.2.5 `--replace-acs-file` wholesale channel is a deliberate, known exception.)

### The gate reads through a degrading `acs-gate` — a workpad read failure never passes (issue #1214)

The gate reads the row-state conjunct through `workpad.py acs-gate`, a sibling of `acs` that gives a workpad read failure a *defined degradation* instead of wedging the run. Its line-1 `source:` token and exit code route the gate: `workpad` (exit 0) is a clean read whose rendered `## Acceptance Criteria` section is authoritative; `workpad-absent` (exit 2) is the existing benign no-workpad shape, kept distinct from a transport failure; `workpad-read-failed` (exit 3) is a read that failed for a reason other than a clean absence (a GitHub fault confined to the comment-listing endpoint), for which the criteria are recovered from the issue body via `scripts/parse-acs.py` so the specification is still visible — but the workpad *tick state* could not be established, so it is an unestablished observation that never passes the gate; `unestablished` (exit 4) is a workpad read failure whose issue-body fallback was also unreachable. Every non-zero exit is a non-passing observation: the degradation makes the failure legible (a distinct label, and on a transport failure the issue-body specification) without ever letting a read the run could not establish stand as a clean gate. A failed `workpad.py update` PATCH separately buffers its append-only notes/reflections under `.prflow/tmp/` and replays them idempotently on the next successful update, so a note or reflection dropped during an outage is not lost.

### In-env verification is the gate — CI is never an in-run verification channel (issue #405)

A **verification-command** acceptance criterion — one whose verification is *running a test/lint/build
command* (the project's test suite, `shellcheck`/`ruff`, a `pytest`/build invocation) — is satisfied
**only by an in-environment observed pass**, on both the local and cloud `/prflow:implement` tiers. The
run executes the command **in its own environment** and ticks the criterion on the pass it observes there.
It **never waits on, polls, re-checks, or cites CI** for its own progress, and ticks nothing on a CI
result. CI (for this repo, the `lib + python tests` job) is the **required post-PR check that gates the
human merge** — not a channel the run reads to verify itself.

The command is invoked by its **direct leading-token** form (`lib/test/run.sh`, not `bash lib/test/run.sh`
— the `bash <path>` wrapper is deny-floored and can never be granted), which resolves because the
suite/lint commands are granted through `prflow_implement.allowed_tools` (and `prflow.allowed_tools` for
the `/prflow:*` command path). The two keys' granted sets are **not** identical and are not
restated here: read them from `.prflow/config.json`, which is their single source — `prflow.allowed_tools`
for the command path and `prflow_implement.allowed_tools` for the implement run, the latter a superset
carrying the additional heads a run needs in its own environment. A count or list transcribed onto this
page is a mirror-fact that goes stale the moment either key changes and nothing reconciles it — which is
exactly what happened to the enumeration this sentence replaces. The command runs in the
**`ac-evidence-verifier`'s** own context (the only verifier that executes anything), and its observed
outcome flows through reconciliation into the gate. The three outcomes:

- **In-env pass** — the command ran and passed; the evidence verifier reports the pass and, on
  reconciliation with the claim verifier, the criterion ticks on that observed result.
- **In-env failure** — the command *ran and failed*; that is a real failure, not a deferral: fix it or
  take the **`Blocked`** path. Never `(post-merge)` it.
- **In-env run denied** — the direct-form command is **not granted** in this run's allowlist, so it was
  refused before it could run. Take the **`Blocked`** path naming `prflow_implement.allowed_tools` (and
  `prflow.allowed_tools` for the command path) as the remedy, then re-run. Never launder a denied
  verification command into a `(post-merge)` retag or a CI observation — never a silent stall, never a
  verdict resting on a CI result the run never saw.

**Consumer rule.** List your repo's test/lint commands in `prflow_implement.allowed_tools` (and
`prflow.allowed_tools` for the command path) and the run verifies them in-env; leave them ungranted and a
verification-command AC goes **`Blocked`**, its message naming `prflow_implement.allowed_tools` as the
exact remedy. See [`cloud-setup.md`](cloud-setup.md#extending-the-tool-allowlist) for the config surface.

**Grant-timing bootstrap — a grant a PR ships is post-merge-only.** A grant added to
`prflow_implement.allowed_tools` (or `prflow.allowed_tools`) inside a PR
is live only after that PR merges, because the workflows resolve config grants at trigger time from the default branch, not from the PR's own head.
So a run must not rely on a grant its own PR ships: grant the command in a prior merged change, or
leave that verification for after merge.
The shared review engine, executed inline by Phase 3.3, takes its **test evidence from the orchestrator's
own in-env suite/lint results** for the current HEAD — never a CI conclusion. (The read-only `review`
runner is a separate, unchanged case: its wait-for-CI-then-review posture is the correct *post-PR*
sequence.)

**Inline-engine grant coupling.** Because Phase 3 executes the shared review engine inline under the implement allowlist (not the review one), every helper the normal inline flow can reach needs a grant on the implement profile (`devflow-implement.yml`) as well as the review profile and `devflow.yml` — otherwise that reachable call is silently refused on cloud implement runs (#363). The `lib/test/run.sh` #484 head guard deliberately over-approximates the runtime surface: it audits all fenced source in `skills/implement/**`, `skills/review*/**`, and the dispatched `skills/requesting-code-review/**` final pass, including standalone-only review Phase 4.4. It fails when an audited fenced head is neither granted on the implement profile nor named in the exact deliberately-withheld list; the allowlist is assembled from the workflow's baked literal alone. A separate removal-proof contract requires inline `workpad.py` source shorthand to expand to the portable granted helper path before emission.

### Single-flight verification (issue #528)

The in-env verification command above is coordinated as a **single flight** through `scripts/verification-flight.py` so an unchanged suite is not relaunched within one lifecycle (as sampled in issue #528, duplicate full-suite launches — several per run, each on the order of minutes — are the clearest measured runtime cost). The helper is **non-executing**: it launches no subprocess and accepts no executable argv, so the run still invokes the same allowlisted leading-token command exactly as documented above — the flight only decides *whether* to launch or attach.

- **Owner path.** `claim` (atomic, one owner; a one-time token is returned and only its SHA-256 digest stored), `mark-running` immediately before the launch, then `finish` with terminal evidence (suite summary, exit status, `skipped_checks`). The handle + evidence are persisted in the run's durable state (workpad / iteration record), and the run **re-anchors** after nested work and compaction — re-reading the handle rather than relaunching.
- **Attacher path.** A later same-checkout caller (identical descriptor + checkout fingerprint) attaches and consumes a `passed` result instead of relaunching.
- **Unknown is never a pass.** A missing, partial, timed-out, unreadable, `incomplete`, or `stale` handle never satisfies verification and never authorizes an automatic relaunch — the caller falls back to a direct launch under the existing rules. On a `wait_expired`, the in-env run takes the existing **`Blocked`** path (implement-driven) without relaunch. The three Phase 3.4 outcomes above (in-env pass / in-env failure / in-env run denied) are unchanged; the flight sits *in front of* the launch, never replacing the gate. Config lives under the `verification_flight` namespace; the vendored helper is granted only in `devflow-implement.yml` and `devflow.yml` (never the read-only `devflow-runner.yml`, whose CI-grounded review launches no suite).

**Documentation-AC deferral (Phase-4.1-owned, distinct from `(post-merge)`).** A criterion whose
satisfaction is a *documentation edit that Phase 4.1's `prflow:docs` subagent owns* — a `docs/…`
deliverable that pass authors, rather than a `skills/`/`scripts/`/`lib/`/test change this phase can make
now — is **left unticked at the 3.4 gate, recorded in a workpad deferral note naming the AC (`3.4: doc-AC
deferred to Phase 4.1: {AC text}`), and does not block the gate**. This is deliberately not the
`(post-merge)` channel (reserved for genuinely-live verification the host can never run in-session): a
doc-AC is fully dischargeable *in this run* by Phase 4.1, so it is neither retagged `(post-merge)` nor
routed through the gate's "satisfiable with a small follow-up edit — do it now" channel, whose remediation
explicitly excludes doc authoring owned by Phase 4.1. The deferral keeps docs Phase-4.1-authored (it does
not weaken Phase 2's docs-ownership rule) while stopping the gate from forcing doc authoring into Phase 3
to satisfy a criterion Phase 4.1 owns. Phase 4.1 **must** discharge each such deferred doc-AC and tick it
(citing the deferral note) before the §4.3 terminal `--status Complete` write — see the Phase 4.1 gate
below; an undischargeable doc-AC routes to the existing `Blocked` path, never to a silent Complete.

**Pre-merge probe contract.** Passing the genuinely-live test is necessary but not sufficient: a
criterion whose *verification* needs a runtime environment can still carry a **pre-merge-observable
precondition that is already false**, and a `(post-merge)` tag means "the live check can't run until after
merge **and everything observable now has been checked**" — not "the criterion is deferred unexamined."
So before any `(post-merge)` tag or retag lands (whether at Phase 1.2 parse time or retro-tagged here),
the run must decompose the criterion into **(a) pre-merge-observable preconditions** — remote
configuration readable via read-only `gh api` reads (repo settings, a ruleset's required checks and
bypass-actor list, branch protection), static properties of the shipped files (a workflow's declared
`permissions:` / token wiring, a config key's presence) — and **(b) the genuinely-live residue** only a
merge/deploy/live-CI run can produce; probe every (a) precondition read-only (folding in any failure mode
the linked issue's Potential Gotchas / Implementation Notes name for that mechanism); and record each
probed precondition, its probe command, and its observed result in the deferral `--note` (or the explicit
finding `"no pre-merge-observable precondition"` — an empty set is legal, a *silent* deferral is the
defect). A probe whose observed result shows the deferred live verification cannot succeed as shipped
routes to a pre-merge fix or the `Blocked` path — **never** a deferral. A *denied* probe (classifier /
sandbox refused it, or the API returned an auth/permission error so state was unreadable) is recorded as
denied and the deferral proceeds; the two are told apart by whether the probe obtained a definitive answer
about the precondition, not by raw exit status — a `gh api` **404** (object observably absent) or **200
with falsy data** (empty required-checks array, absent bypass actor) is **observed-false**, not a denial.
A passed probe only *narrows* the deferral to the genuinely-live residue; it never ticks the AC box. The
contract lives in `skills/implement/phases/phase-3-ac-gate.md` and is the single source of truth for both
the Phase 1.2 tag-time path (`skills/implement/phases/phase-1-setup.md`) and the Phase 3.4 retro-tag path.

### Focused-vs-full selection and the run budget (issue #789)

The two rules above answer *where* verification runs (in-env, #405) and *how often the
same suite is launched* (single flight, #528). They say nothing about **which** command
the run picks mid-iteration, and that gap is what made one run pay for the full suite
repeatedly. The selection rule lives in the shared focused-verification policy — this
repo's `.prflow/prompt-extensions/{implement,review-and-fix,receiving-code-review}.md`,
mirrored in `CLAUDE.md`'s tiered-runner bullet, `CONTRIBUTING.md`, and
[`DEVFLOW_SYSTEM_OVERVIEW.md`](DEVFLOW_SYSTEM_OVERVIEW.md)'s *Focused review-and-fix
iteration* section (the canonical description of the tiers). In outline:

- **Tier 1 — iterate on the covering focused test.** A shell surface with a registered
  module uses `lib/test/run-module.sh <module-id>`; a `scripts/*.py` / `lib/*.py` unit
  uses the `lib/test/test_*.py` file its `lib/test/modules/coverage-map.json` entry names
  in an optional `focused_test` field. (`owner` is unchanged: it still names a registered
  *shell* module or `unmodularized`, so `focused_test` is the orthogonal Python-layer
  credit, not a redefinition.)
- **Tier 2 — coalescing extraction.** A surface no focused test covers takes the full
  suite for its **first** mid-iteration cycle; a **second** cycle on that same surface
  extracts a durable module instead. A one-off fix pays one full run; an
  iteratively-fixed surface extracts once.
- **The full-suite fallback stays a closed set**, and a run that takes it records a
  `## Devflow Reflection` bullet naming which case applied.
- **Focused-first binds as a precondition on the mid-iteration full-suite launch.**
  Before a mid-iteration full-suite launch, every touched surface with a covering
  focused test invocable on the tier is run first; the exempt set is total over four
  grounds (no coverage-map entry — the map covers only `lib/`/`scripts/`; a declared
  exempt subtree; an `unmodularized` entry with no `focused_test`; or a tier-ungranted
  covering test), and a covering test that ran and failed discharges the precondition
  for a diagnostic launch. The precondition binds the mid-iteration launch only, never
  the final completion gate.
- **The run has a named place to record what it did (issue #1229).**
  `scripts/focused_selection.py` is the round-trippable producer/reader for that
  per-surface selection: each entry names either the discharging focused result (the
  coverage-map entry consulted plus the target selected) or the exemption ground, plus a
  `single_flight_consulted` field for whether the `scripts/verification-flight.py` flight
  was consulted before a full-suite relaunch. An implement run sinks the
  `<!-- prflow:focused-selection … -->` marker as a `## Progress` note via
  `scripts/workpad.py`; a standalone fix loop stores the record verbatim as
  `iter-<N>.json`'s `verification_evidence.focused_selection`. It is a record of what the
  run did, never a launch counter or a changed-file-to-module routing table (AC7). The
  three prompt extensions are its source of record.

The `/simplify` commit that Phase 3.2 pushes owes **no** verification round of its own:
Phase 3.3's `review-and-fix` loop runs a verification as its first act, so the just-committed
`/simplify` edits ride into that first verification. A fresh commit does not, on its own,
owe a verification round when the very next step verifies it — `skills/implement/phases/phase-3-review.md`
§3.2 states this for the shipped skill.

The Phase 3.2 tick passes the **host-safe substring** `simplify`, not `/simplify`, while the
displayed `` `/simplify` `` Progress row keeps its label. A standalone slash-leading argument is
rewritten by Git Bash/MSYS into a Windows path before native `python3` receives it (see the
standalone-argument hazard in `docs/internal/install.md`), so a `/simplify` operand would tick
nothing and report a volatile miss on those hosts; `simplify` still uniquely matches the row. The
derived guard in `lib/test/test_python_scripts.py` enforces the rule: a static standalone
`--tick-progress` operand under `skills/implement/` may be quoted or unquoted, must not begin with
`/`, and must carry no shell metacharacter — an unquoted or double-quoted shell-variable operand
is runtime-resolved and exempt (a single-quoted `'$X'` suppresses expansion, so it is a static
literal and stays guarded).

**The same command must work on both tiers**, so a focused Python test is invoked as a
**direct leading token** (`lib/test/test_python_scripts.py <selector>`) — never `python3
lib/test/test_python_scripts.py`, which is the interpreter-head shape the cloud matcher
denies (#401) even though `python3` is a granted head. That requires two things the
selection cannot supply on its own: the file carries the **exec bit**, and its
`Bash(lib/test/<file>.py:*)` token is granted for the implement run. Since issue #1078
that grant lives in `.prflow/config.json`'s `prflow_implement.allowed_tools` — the
self-repo-only channel described above (`config.example.json` ships it empty, so no
consumer inherits it), not the `lib/capability-profiles.json` manifest. The seven
`Bash(lib/test/…)` tokens issue #789 originally baked into the `implement` profile
delivered zero benefit in a consumer (the `vendor-plugin` slice prunes `lib/test`, so
none can ever match a PRFlow file there) while pre-authorizing any consumer file that
collided with a PRFlow-chosen path, so #1078 removed all seven from the manifest: the
five `focused_test` targets plus `coverage_map_guard.py` moved to that config key, and
`test_module_harness.py` — not a `focused_test` target, invoked only via the `python3
<path>` interpreter head — was dropped. The `.py`-as-direct-leading-token shape is
probe-proven PERMITTED on the implement tier — see
[`cloud-allowlist.md`](cloud-allowlist.md)'s row 17 for the run of record and the
grant history.

**None of this weakens the gate.** The final completion claim still takes a whole-suite
result, and the #456 skip accounting is unchanged — a nonempty skip tally is not clean, and a
focused module may not self-skip. Which result counts is tier-scoped since issue #1607: the
cloud implement tier runs the suite in its own environment, while this repository's
local/interactive tier commits, pushes, and reads CI for that pushed commit, treating an
absent run or an unestablished reading as a stop rather than a pass. A suite result is
established from the runner's **terminal summary line** — wherever the runner writes it —
never from a bare process or wrapper exit status when a tally was printed; a command
silent on success is established from its own exit status, and a command that never ran
is established as nothing. A mid-iteration #434 stale-prose `blocking-gate` skip
on a dirty tree is expected and clears on commit; it is not a reason to relaunch.

**Batching is what bounds how many passes are paid (issue #1252).** The relaunch rules above
govern relaunching over an *unchanged* tree; none of them covers relaunching over a tree
that changed by one small edit, which is the expensive case — on the run that motivated the
rule, two whole-suite passes were launched 44 and 48 seconds after the previous one
finished. So before launching a whole-suite pass the run applies every fix it already
owes rather than launching one per fix, and where a covering focused test exists it is
the instrument for confirming a single edit — mid-iteration only, never at the completion
gate, which no focused result discharges. The operative statement lives in the three
`.prflow/prompt-extensions/` files (`implement.md` is the single-source home;
`review-and-fix.md` and `receiving-code-review.md` carry declared coupled copies), which
also state what it does not override and how an unestablished owed-fix set resolves at
each launch kind. This paragraph is a non-authoritative pointer to them.

**Diagnosis reads the capture, not a relaunch.** On a failing run `lib/test/run.sh`
prints a named `Failure recap` re-listing each failing assertion's identifier, built from
an on-disk record every FAIL site appends to (so stderr-only failures are listed too).
Recovering *which* assertion failed reads that recap plus the stderr-merged capture — the
`2>&1` `.prflow/tmp/verification-<ISSUE>.log` redirect locally (#719; `>` redirects are
matcher-denied on cloud, where the recap rides in the runner log instead). The recap
preserves `run.sh`'s exit status, so `scripts/verification-flight.py` still records
`failed` for a RED suite; on a clean run nothing extra prints.

## PR-body composition: two writers and the provenance line (issue #1655)

A `/prflow:implement` PR body has **two distinct writers**, and both must be understood together
because the second regenerates over the first's output:

- **Phase 3.1 (the draft-PR create fence)** is the sole author of the **provenance line** —
  `Generated via /prflow:implement (v<version>[, <model>][, <effort>])`. The line is rendered by
  the bundled helper `scripts/render-pr-provenance-line.py` in its own fence and substituted into
  the `gh pr create --body` as a literal, because each phase fence is a separate shell and the
  create fence must stay a single statement. The helper resolves the **version** from the plugin
  manifest beside itself (mirroring `lib/efficiency-trace.sh`), the **model** from the most-recent
  assistant record of the session transcript (never the `resolvedModel` field, which names a
  dispatched subagent's model), and the **effort** from `CLAUDE_EFFORT`; any value it cannot
  establish is omitted with a stderr breadcrumb rather than guessed, so a cloud run — which has no
  model or effort source — renders the version alone. The line carries no backtick and no other
  shell-active construct by construction, so nothing in it can reach the double-quoted `--body` it
  is substituted into. This writes only on the **CREATE** arm; a resumed run that adopts an
  existing PR leaves the body untouched. The provenance line is gated by the config key
  `prflow_implement.publish_model_effort` (default `true`; an explicit JSON `false` suppresses the
  model+effort clause while the version is always emitted), read at run time from the working tree
  so the value is live in the same run (it is absent from the trigger-time extract step of
  `devflow-implement.yml`).
- **Phase 4.2 (`skills/pr-description/SKILL.md`)** authors the rest of the body — the summary,
  `Resolves #N`, acceptance-criteria and test-plan sections — and **regenerates** it late in the
  run. Before issue #1655 the provenance line survived that regeneration only by accident, as
  unnamed pre-marker content the regenerator happened to re-emit. `skills/pr-description/SKILL.md`
  now carries an explicit rule naming the provenance line, so it is **preserved deliberately across
  Phase 4.2 regeneration** rather than by luck — the line is present in the PR body after the
  regeneration. That rule is a **relocation**, not a preserve-in-place: the draft body Phase 3.1
  writes carries no `<!-- PR_BODY_START -->`/`<!-- PR_BODY_END -->` markers, so the regenerator's
  no-markers rule treated the whole draft — provenance line included — as pre-marker content and
  hoisted the line to the **top** of the regenerated body (PR #1704). The regenerator now emits the
  line as the **last line of the whole output**, below `<!-- PR_BODY_END -->`, wherever it found it,
  so it reads as the body's signature.

## Phase 3.1.1 assigns the draft PR to the triggering user (issue #1165)

Immediately after Phase 3.1's **CREATE** path opens a draft PR, the engine best-effort-assigns it to the developer who triggered the run, so reviewers can read ownership from the standard GitHub assignee field. This runs on the **CREATE arm only** — the **ADOPT** path (a resumed run whose PR a prior attempt created) skips it entirely and leaves the existing PR's assignees untouched.

The single assignment path is `scripts/apply-pr-triggerer.sh <pull-request-number>`, which resolves the triggerer by tier:

- **Local identity resolution.** On a local run (`GITHUB_RUN_ID` empty) the helper resolves the authenticated GitHub login through `gh api user --jq .login` — the repository's established local-login pattern. An empty result (`empty-identity`) or a failed query (`identity-lookup-failed`) skips assignment **without guessing** a login.
- **Cloud identity propagation.** On a cloud run (`GITHUB_RUN_ID` set) the helper reads the authorized issue-comment sender the workflow propagates through `DEVFLOW_TRIGGERING_USER` (`.github/workflows/devflow-implement.yml` exports `github.event.sender.login` — the same trusted login authorization and commit attribution use). The `DEVFLOW_` prefix is kept because the rename contract freezes environment identifiers.
- **Assignment confirmation.** GitHub can accept the add-assignee POST (`repos/{owner}/{repo}/issues/{number}/assignees`) and *silently ignore* an unassignable login, so HTTP success alone is not enough: the helper inspects the response and reports `assignment: applied <login>` only when the requested login is present, otherwise `assignment: skipped unconfirmed`. Because the endpoint only *adds* assignees, reapplying to an already-assigned PR reports `applied` and never removes existing assignees (idempotent). **`unconfirmed` records an *unestablished* outcome, not a failed one** — the POST returned rc 0, so the request succeeded and only the confirmation did not (an ignored login, an empty or truncated response body, or a degraded `jq` all land here). Per the repo's *unknown is not zero* rule it is reported as "could not confirm assignment" and **never** as "unassigned"; every other skip reason does establish that no assignment was made.
- **Workpad Reflection behavior.** The helper always exits 0 and prints exactly one outcome token to stdout — so `assignment: skipped <reason>` (`invalid-input`, `no-triggering-user`, `identity-lookup-failed`, `empty-identity`, `api-failure`, `unconfirmed`) **or no output at all** (a harness refusal) routes to a `dropped-failed` entry in the workpad's `## Devflow Reflection`, preserving the created PR. Assignment never gates the run.
- **Deployment skew.** Workflow files and vendored skills reach consumers through independent upgrade channels. A new workflow paired with an *older* skill simply never calls the helper (no assignment, fully compatible). A newer skill paired with an *older* workflow finds `DEVFLOW_TRIGGERING_USER` empty on the cloud tier and takes the **skew-safe** path: it skips assignment and **never** substitutes another account (the token owner, the GitHub App identity, or `GITHUB_ACTOR`). The helper's implement-tier grant is trigger-time inert for its own PR's cloud run, so pre-merge coverage is executable helper tests plus code-reading assertions against the grant producers.

## Phase 4.3 finalize: publish vs. draft (`implement_pr_state`)

Phase 4.3 (*Finalize the PR and Finalize Workpad*) is where a run ends. It runs five things in order:

1. **Clean-tree backstop (unconditional).** `git status --porcelain` must be empty before finalizing. The run started from a clean base-branch checkout, so anything dirty here is this run's own work an earlier phase failed to commit — it is committed with the right prefix and the under-committing phase is recorded in `Devflow Reflection`, never papered over. This runs in *both* the publish and draft cases; it is independent of the publish decision.
2. **Base-branch update checkpoint 4 (pre-ready).** `scripts/update-branch-checkpoint.sh` brings the branch up to date with the base one last time. Since issue #779 its outcome **gates the two steps below**: only a clean first field (`UPDATED` / `UP_TO_DATE` / `DISABLED`) proceeds, and a non-clean one refuses both the publish and the `Complete` flip. The clean-token row it records (`--checkpoint base-update-checkpoint-4`, or the tier-refused key) is, since issue #1348, a **required run artifact** the terminal `--status Complete` gate refuses to finalize without — so the earlier degrade-to-`--note` fallback is removed and a non-canonical-body `--checkpoint` failure fails this step closed. See *Base-branch update checkpoints* below for the full routing.
3. **Tip-landed gate (issue #1616).** Before the publish decision — guarding `gh pr ready` and the `Complete` flip alike — the run confirms its local branch tip is on the remote (`git rev-parse HEAD` == `git rev-parse @{u}`). See *Tip-landed gate* below.
4. **Publish decision.** By default the run publishes the draft PR created in Phase 3.1 by running `gh pr ready`.
5. **Workpad finalization.** `Status` flips to `Complete` (🎉), the final `## Progress` item is ticked, and the 🎉 outcome reaction is emitted on the triggering comment — in both cases. The final-item tick is a `--tick-progress` substring match against the `## Progress` "PR marked ready" row; if that label has drifted (or was already ticked on a resumed run) the tick is a *volatile* miss — the `## Progress` section is still present, so the call still flips `Status` to `Complete` and writes its note but **exits non-zero** rather than aborting. The finalize must consume that exit code (per the failure-isolation contract below): a non-zero finalize means the box is still `- [ ]` and the row must be re-resolved and re-ticked before the run is treated as cleanly Complete.

**Terminal self-record gate on `--status Complete`.** Because Phase 4.3 is the deterministic chokepoint where a run flips to `Complete`, `workpad.py` reconciles the workpad self-record against reality on every `--status Complete` write (`_terminal_complete_gate`, issue #258), running *last* over the post-mutation sections so a call that ticks the final AC row and flips to `Complete` in one shot still passes. Its three outcomes:

- **Hard-fail (structural abort, no PATCH).** If any **non-post-merge** `## Acceptance Criteria` row is still `- [ ]`, the finalize aborts before any PATCH and `Status` is *not* flipped — the run is not allowed to record itself Complete over an unmet AC. The stderr names each offending row (`refusing to finalize Status: Complete — … Acceptance Criteria row(s) still unticked`). `(post-merge)` AC rows are excluded, byte-for-byte the Phase 3.4 exclusion. The Phase 3.4 gate should already have ticked every non-post-merge AC, so this fires only on a drift; the fix is to tick the outstanding AC once its work is real (`--tick-ac-n`) or take the Blocked path, then re-issue the finalize — never a verbatim retry.
- **Non-blocking warning — unticked `## Plan` rows.** A still-unticked Plan row only warns (a genuinely dropped/superseded step may honestly stay unticked); the finalize still succeeds. Phase 3.5 ticks the versioning and final-suite Plan steps (which complete in Phase 3, so the Phase 2 tick loop never reaches them) precisely so this warning fires only on a real drop. (The versioning step commits the repo's version artifact — for this repo the `.changeset/*.md` file that the merge-time `version-consolidate` Action later consolidates into a bump + `CHANGELOG` entry, not an in-PR version bump.)
- **Non-blocking warning — un-mirrored AC placeholder.** If the `## Acceptance Criteria` section still holds the un-mirrored `new-body` placeholder (AC-mirroring never ran, so the checkbox scan has nothing to check and the hard-fail is vacuously satisfied), the finalize warns and succeeds — the self-record was never populated, so investigate the mirroring rather than trusting the Complete. A genuinely AC-less issue carries the *distinct* `_(none provided in issue body)_` sentinel and is unaffected.

**Required-artifact gate (issue #1348).** Beyond the self-record reconciliation and the evidence gate, a `--status Complete` write also requires the `## Progress` section to carry a row for every member of `workpad.py`'s module-level `_REQUIRED_ARTIFACTS` set — initially exactly the base-update checkpoint-4 record, satisfiable by either its clean `base-update-checkpoint-4` marker **or** #1347's `base-update-checkpoint-4-tier-refused` marker, so a tier-refused run still completes. The gate (`_required_artifact_verdict`, called by `_terminal_complete_gate` under the same `_status_glyph(...) == '🎉'` terminal-status test as the AC hard-fail) resolves each artifact's keyed marker with the same `_marker_variants(_checkpoint_marker(key))` idiom `_plan_checkpoints` uses — so both the `prflow:` and superseded `devflow:` spellings count and a workpad mutated across the #1003 rename boundary is not falsely refused. A missing row is a **structural abort before PATCH** whose stderr names the exact producing command (`update-branch-checkpoint.sh`, recorded via `--checkpoint base-update-checkpoint-4`). It is a **pure read** — it mutates nothing on any path; every repair lives earlier in the producer, and the deleted `--note` degrade path (§4.3) is gone precisely so this gate has one recording format to read. The Phase 1.3 resume strip (`--strip-inherited-checkpoints`, issue #1347) clears a prior attempt's row so a resumed run cannot satisfy the gate on inherited evidence. This asserts only that checkpoint 4 was reached and its outcome recorded — **not** that the base is current at publish (a `DISABLED` or tier-refused run satisfies it having reconciled nothing).

**Completion verification-flight evidence gate (issue #1087).** Beyond the self-record reconciliation above, a `--status Complete` write now also requires **current, machine-readable verification evidence** for the run's final in-env verification command. Phase 4.3 establishes it after the last candidate-changing operation (docs/changeset commit, a `fix:` claim-audit commit, the clean-tree backstop, checkpoint 4's merge): it obtains the final candidate identity from the reception preflight (`reception-record.py`'s stdout `candidate_identity`, the git tree id `scripts/reception_identity.py` derives), launches one verification flight through the non-executing `scripts/verification-flight.py` ledger (declaring that identity on the `claim`), and records the validated flight key with `workpad.py update --record-completion-evidence <flight-key>`. That records one hidden `completion-verification:<flight-key>` marker on the existing keyed-checkpoint marker family (no second marker family is minted; a later validated key replaces the prior one). `workpad.py`'s `_terminal_complete_gate` then, immediately before PATCH, resolves the canonical `.prflow/tmp/verification-flights/<flight-key>.json` record, re-derives the candidate identity, and runs the **implement-completion** context of `scripts/check-completion-evidence.py` (an importable entry point, `validate_implement_completion`, reusing the closed eight-token vocabulary — no ninth token). The record passes only when its `state` and `result` are `passed`, its `suite_summary.command` is a nonempty string, its `suite_summary.exit_status` is the integer `0`, its top-level `skipped_checks` is an empty list (the stricter no-skip policy — not even a host-capability skip is admitted), and its `candidate_identity` equals the current tree. Any missing/duplicate marker, unestablished operand, non-`passed` flight state, nonzero exit, non-empty skip population, or stale identity is a **structural abort before PATCH** — the workpad stays at its prior status and the run routes to Blocked (or re-launches a fresh flight for the final tree). The off-switch (`.verification_flight.enabled: false`) suppresses only flight *reuse* for an implement run; the record is still produced. A standalone `workpad.py` copy lacking the evidence sibling fails a Complete write closed with the `missing-evidence` token naming the absent module, while its non-Complete subcommands are unaffected. The `check-completion-evidence.py` validator plus its transitive import closure (`reception_identity.py`, and `workpad.py`'s `section_parse.py` sibling) are byte-pinned in `scripts/devflow-cloud-writer-contract.json` so a mutation to any of them is a `HASH_MISMATCH`.

**The completion-evidence member accepts two evidence families (issues #1087, #1611).** The
verification-flight family above is the in-environment family. Issue #1607 made a CI reading the local
tier's *policy* completion gate in `CLAUDE.md`, and issue #1611 gave `_terminal_complete_gate` a second
accepted family so a local implement run following that tier ladder can write `Complete` without either
running a suite the ladder does not gate on or misdescribing what it verified. The two families are:

- **In-environment verification-flight** (`completion-verification:<flight-key>`) — the record described
  above, unchanged in shape and strictness. This is what the cloud implement tier produces, and its
  path is byte-for-byte as before.
- **CI-derived reading** (`completion-ci:<payload>`) — recorded with `workpad.py update <issue>
  --record-completion-evidence-ci <head-sha> <check-name> <conclusion> <run-url>`, whose four operands
  are exactly enough for a later reader to re-audit the reading against GitHub. The payload is a
  base64url-unpadded JSON object riding the **same** keyed-checkpoint marker family under a distinct
  `completion-ci:` key namespace (no third marker family is minted), so a reader tells an in-env suite
  pass from a CI reading without inspecting any command string. `workpad.py`'s `_validate_ci_evidence`
  validates it through the sibling `check-completion-evidence.py`'s importable
  `validate_implement_completion_ci` — **offline and deterministic: no network call and no `gh`
  invocation.** The record passes only when every field is a nonempty string, the `head_sha` is exactly
  40 lowercase hex characters equal to `git rev-parse HEAD` over a clean `git status --porcelain`, and
  the `conclusion` is `success`. It mints **no ninth token**: a missing or malformed field is
  `missing-evidence`, a SHA that does not match the current head or a dirty tree is `stale-candidate`,
  and a non-success conclusion is `verification-not-pass` — the same closed eight-token vocabulary and
  first-failing-class order the flight context uses. The flight ledger is untouched, so a CI reading is
  never laundered into a reusable flight.

`_completion_evidence_verdict` collects markers from **both** families and keeps its refuse-unless-exactly-one
rule over the combined count, dispatching the single marker to the validator its family owns — so a run
carrying one of each family, or two of either, is refused, and a run recording the CI marker must not also
record a flight marker. Both the `prflow:` and superseded `devflow:` spellings are read per record for the
CI family too. Which family a local run records is a tier-scoped **policy** decision that stays in
`CLAUDE.md` (rung 1) and is deliberately not shipped to consumers; a consumer repository's implement run
never produces the CI marker and so reaches exactly the outcomes it reaches today.

**Review-coverage gate (issue #1453).** The fourth member of `_terminal_complete_gate`, after the completion-evidence and required-artifact gates: a `--status Complete` write also requires the `## Progress` section to carry exactly one resolvable **review-coverage record** for the run's Phase 3 review pass. Phase 3.3 stamps it on **every** Phase 3 exit that can reach a Complete write — the clean-completion path, the `APPROVE WITH UNRESOLVED SHADOW FINDINGS` and `REJECT` branches, and the severity-aware soft-proceed — with `workpad.py update $ISSUE_NUMBER --record-review-coverage <coverage> <dispatch> <roster> <checklist>`, deriving each operand from the loop-verdict marker (and, for the roster/checklist comparisons, the fix loop's `iter-<N>.json` `shadow` block). The record rides the **existing** keyed-checkpoint marker family under a `review-coverage:` key namespace carrying the colon-joined four-axis payload — not the `_REQUIRED_ARTIFACTS` literal-key family, because the payload legitimately changes between calls and `--checkpoint`'s replay semantics key on the whole key string, so a second call would insert a *second* independent row with nothing to say which is authoritative; the producer therefore strips the prior row and appends a fresh one, and the reader refuses on anything other than exactly one record. Both marker namespaces (`prflow:` and superseded `devflow:`) are read per record.

The axes, their closed vocabularies, which values are clean, and the gap token each reports are declared once in `workpad.py`'s module-level `_REVIEW_COVERAGE_AXIS_SPECS` — the single source, with every derived view (`_REVIEW_COVERAGE_AXES`, the vocabulary/clean/gap maps and the gap ordering) computed from it and an import-time validator refusing a table edit that would fail the gate open (notably adding `unestablished` to any axis's `clean` tuple, since `unestablished` is a first-class member of every axis precisely so an unresolvable fact is recordable as unknown rather than collapsed onto a clean value). Read that table rather than a prose copy; prose mirrors exist in the implement phase files and the review-and-fix references and cannot import it, so a vocabulary change reconciles them in the same commit.

`_review_coverage_verdict` — a **pure read** over the post-mutation `## Progress` content, taking no flags from `args`, because the Phase 4.3 finalize is a plain `--status Complete` that repeats no coverage flags — refuses in four ways, each a **structural abort before PATCH** whose stderr carries a bracketed token:

- `[review-coverage-unestablished]` — no record, more than one, a malformed payload, or a vocabulary-valid record holding `not-applicable` on some but not all four axes. An unresolvable coverage fact is never read as a complete one; the remedy is the Phase 3.3 stamp. `not-applicable` is the no-shadow-owed record (the `REJECT` branch and the severity-aware soft-proceed) and describes the whole pass, so it is all-four-or-none — a subset would let a dispatched pass borrow it to hide a short roster or a skipped checklist. The same check runs at write time on `--record-review-coverage`.
- `[review-coverage-gap]` — the record shows at least one gap (an axis holding a non-clean value) and some gap carries no disposition row. Either complete the review pass, or record one `--review-coverage-disposition <gap> "<reason>"` per gap.
- `[review-coverage-undispatched]` — a disposition offered over a record whose `dispatch` is not `attempted`. The disposition is an honest-degradation record, never an election channel (issue #1230): a run that never dispatched the shadow — or cannot establish that it did — has no legal way to record a shortfall and complete, and stops at a non-terminal or `Blocked` status instead. This is deliberately gated on the recorded dispatch fact rather than on a cost/budget word blocklist, because the shipped `shadow-review.md` permits cost as a *true* cause on a dispatched-and-fell-short record.
- `[review-coverage-boilerplate]` — a disposition reason `_review_coverage_reason_rejection` refuses: a known placeholder, one shorter than `_REVIEW_COVERAGE_REASON_MIN_LEN`, one carrying an HTML-comment delimiter the row cannot hold, or a gap named by two disposition rows so no single reason resolves. Restate the reason so it names this run's specific gap, and remove the duplicate row where one exists.

The disposition's *reason* rides the row's visible text rather than the marker key, because the checkpoint key grammar admits neither spaces nor base64's characters; the reason pattern is anchored on the gap the marker itself reported, so a row whose marker and visible text disagree cannot bind the wrong reason to the wrong gap. Each accepted `--review-coverage-disposition` also files its own `dropped-failed` `## Devflow Reflection` bullet by construction, so an honest degradation reaches the retrospective without the caller remembering a second flag. Every channel that writes a `## Progress` row — `--note`, a `--checkpoint`'s text, a `--record-classification`'s rationale — is screened at the shared `_append_progress_note` chokepoint for either reserved marker, so no prose channel can smuggle a record into `## Progress`; `--reflection` needs no such screen, because it targets `## Devflow Reflection`, which the gate never reads. Phase 4.3 mirrors this gate as a **publish precondition** evaluated *before* `gh pr ready`, since `gh pr ready` runs before the finalize write and gating only the workpad would publish a PR beside a `Blocked` workpad.

**Tip-landed gate (issue #1616).** Between checkpoint 4 and the publish decision, before both `gh pr ready` and the terminal `--status Complete` write, the run confirms its local branch tip actually reached the remote. It closes a class of bug the field incident PR #1610 (issue #1561) exhibited: a run committed a Phase-3 changeset (`6df169132`) by explicit path, never pushed it, and then published a PR whose body cited that commit — `gh api repos/{owner}/{repo}/commits/6df169132` returns `422 No commit found`. Every downstream step (PR-body composition, the AC gate, `gh pr ready`, `--status Complete`) reads the *local* checkout, so the divergence was invisible to all of them; the clean-tree backstop did not catch it because `git status --porcelain`'s short form suppresses the `Your branch is ahead of 'origin/…'` header, and `update-branch-checkpoint.sh` measures only whether the branch is *behind base*, never whether local `HEAD` reached its own upstream. The gate covers **any** commit a run makes from Phase 3 onward — the changeset, a review-fix commit, a docs commit, an artifact regeneration — not the changeset alone, which was merely the artifact a reviewer happened to check for.

The check compares `git rev-parse HEAD` against `git rev-parse @{u}` (a local remote-tracking ref, deliberately *not* a live `git fetch` — this run's own pushes are what advance it, which is exactly right for detecting a commit this run never pushed), classifying `HEAD` in order:

- **Detached HEAD** (`git rev-parse --abbrev-ref HEAD` prints `HEAD`) or **no configured upstream** (`git rev-parse @{u}` fails on a real branch). Neither is *by itself* an unpushed tip, so the gate never `Blocked`s on the classification alone — each is reported distinctly. Lacking `@{u}` as a comparand, it positively confirms the remote holds `HEAD` with `git branch -r --contains HEAD` (which reads local remote-tracking refs, like `@{u}`): a **non-empty** result records a `--note` naming the state and proceeds; an **empty** result means the remote lacks `HEAD` and routes to the unpushed handling below.
- **Measurement unestablished** — a needed `git rev-parse` is refused or returns no output (the local-tier permission classifier can refuse a `git rev-parse` fence outright). A refused measurement is *not* evidence of an unpushed tip, so this is never collapsed onto an unpushed-tip `Blocked`; it records a `--note` naming the state and proceeds under the degraded posture. On the cloud tier `git rev-parse` is granted, so this arm is reached only on a local run where a human is present.
- **Landed** (`@{u}` equals `HEAD`) — proceed to the publish decision. Landing `HEAD` publishes its ancestors, so every SHA the PR body cites then resolves on the remote at publish time.
- **Unpushed** (`@{u}` differs) — `git push`, then re-read both. Equal now → note it and proceed; still unequal (push rejected, or an `Everything up-to-date` push left them apart) → **refuse to run `gh pr ready` and refuse to flip `Status` to `Complete`**, record `--status Blocked` with a `blocked`-kind reflection naming the unlanded commit, emit the 👎 outcome reaction, remove the run marker, and stop.

Like the review-coverage gate, this is a **publish precondition evaluated before `gh pr ready`** — because `gh pr ready` runs before the finalize write, gating only the workpad would publish a PR beside a `Blocked` workpad. It ships in the shared `skills/implement/**` body (engine behavior a consumer needs), so it names no PRFlow-internal path and carries no source-presence pin.

The publish step is gated by a per-consumer config key, **`prflow_implement.implement_pr_state`** (string, read via `config-get.sh .prflow_implement.implement_pr_state ready_for_review`):

| Value | Phase 4.3 behavior |
|---|---|
| `ready_for_review` (default) | Runs `gh pr ready` — the PR is published, exactly as before. |
| `draft` | Skips `gh pr ready` — the PR is left as the Phase 3.1 draft. No extra comment is posted to the PR thread. The workpad `--note` wording states the PR was *left as a draft* rather than marked ready. |
| missing / empty / any other value | Resolves to `ready_for_review` (publish). |

**Default-to-publish is the safe direction**: only the exact literal `draft` suppresses publishing, so a typo'd or future value can never accidentally leave a PR unpublished, and a hard config read failure (malformed config) also falls back to publishing. Existing consumers and PRFlow's own runs — which do not set the key — are unaffected.

**Downstream consequence of `draft`.** Publishing a PR is what fires the rest of the pipeline: CI's `ready_for_review` listener keys off the draft→ready transition (before issue #936 withheld the automatic pull-request-triggered review tier, `devflow-review.yml`'s `ready_for_review` trigger did too; a repository that still has that workflow installed still sees both). Choosing `draft` therefore *intentionally* suppresses those for that run until a human publishes the PR — this is the documented trade-off a consumer accepts, not a bug to be fixed. It lets maintainers of repos that adopt PRFlow keep bot-completed PRs out of the ready-for-review queue and publish them on their own cadence (after a manual look, on a release boundary, or to avoid auto-notifying reviewers).

The gate lives once in `skills/implement/phases/phase-4-documentation.md` (Phase 4.3, read at phase entry by the `skills/implement/SKILL.md` orchestrator) — the skill body is shared by the local and cloud `/prflow:implement` paths, and both read the same `config.json` via `config-get.sh`, so no workflow change is needed and the logic is never forked.

## Terminal-status self-check and Phase 4.1 re-anchor (guarding against an early run stop)

A `/prflow:implement` run can *under-complete* Phase 4: it commits the Phase 4.1 documentation, then stops before Phase 4.2 (`/pr-description`) and Phase 4.3 (finalize). The run exits `success`, so nothing signals the shortfall — the workpad is frozen at an in-progress `Status` (`Documenting` 🚀), the draft PR stays un-described, and no terminal outcome reaction is emitted. Two agent-side guards, both in the shared skill body (so local and cloud `/prflow:implement` get them with no workflow change), close this:

- **Terminal-status self-check (`skills/implement/SKILL.md`).** A cross-phase invariant near the Completion Checklist forbids the orchestrator from emitting its run-final message while the workpad `Status` is any in-progress value; it must first have reached a terminal `Status` — `Complete` (🎉) or `Blocked` (👎). The check keys on the workpad `Status`, **not** on PR draft state, so the intended `implement_pr_state=draft` path (which still reaches `Status: Complete`) is never a false positive, while a published PR whose workpad is still `Documenting` does trip it. It reuses the existing `🚀`/`🎉`/`👎` status vocabulary from `scripts/workpad.py` — no new status value.
- **Phase 4.1 post-subagent re-anchor (`skills/implement/phases/phase-4-documentation.md`).** After the Phase 4.1 `prflow:docs` subagent returns and its docs are committed, the orchestrator re-`Read`s `phases/phase-4-documentation.md` (via the same portable `${CLAUDE_SKILL_DIR:-…}` skill-directory anchor the entry-gate uses) before §4.2, re-anchoring the remaining §4.2/§4.3 procedure that a long context-isolated subagent return may have evicted from the working set. It is scoped to **subagent** returns — here, the Phase 4.1 docs subagent; the Phase 2 and Phase 3 subagent returns carry their own phase entry-gate reads. This is **not** the engine's only subagent-return re-anchor: as of issue #1577 the Phase 4.2 PR-description subagent (which invokes `prflow:pr-description`) carries its own parallel counterpart at both levels §4.1 has — a phase-file "Re-anchor before §4.3" note and an always-resident trigger in `SKILL.md`'s Phase 4 section — restoring the §4.3 procedure after that subagent returns. A **Skill-tool** return is covered by the separate generalized re-anchor below. Phase 2's *dispatch* idempotency has its own dedicated source — the §2.0 resume-idempotency gate stated authoritatively in `skills/implement/phases/phase-2-implement.md` — so the "own entry-gate reads" scoping restores only the Phase 2 procedure and is not evidence Phase 2 needs no idempotency mechanism.

Both are prose contracts, so their current automated source boundary in `lib/test/run.sh` is an exactly-once `assert_pin_unique` presence assertion for each operative clause; the section heading is pinned presence-only. The always-loaded orchestrator also repeats the Phase 4.1 re-anchor *trigger* in its Phase 4 section (the phase file carries the operative instruction, but the trigger to re-read survives the subagent-return eviction only if it lives in the always-resident body), and the terminal-status self-check binds every termination path — not only a deliberate wrap-up — so a run that simply halts at "documentation done" without concluding is still caught. To make that binding checkable rather than merely stated, the orchestrator must **read the live workpad `Status` line immediately before emitting any run-final message** — from the comment, not from its memory of where the run got to — and conclude only when that line reads a terminal value.

### The dispatch-authorization surface (§7's always-resident authorization)

Two always-resident sentences at the head of `skills/implement/SKILL.md` decide which Agent-tool dispatches an implement run may make. They exist to satisfy the "do not call the AgentTool unless the user requested it" condition some Claude Code harnesses inject into the system prompt: invoking `/prflow:implement` **is** that request, at the points the run's own surfaces instruct. The **Subagent rule** states the direct-work default — planning, implementation, testing, and fixing are the orchestrator's own inline work — with one named exception, Phase 3.4's evidence verifier, which is permitted to run an in-environment verification command. The **injection-condition clause** (the *dispatch-authorization sentence*, referenced by that identity elsewhere in this doc) states authorization as a **property, not a closed enumeration**: a dispatch is authorized exactly when one of three dispatch-instructing surfaces instructs it.

- **The implement bundle** — the orchestrator root, its `phases/*.md`, and its `references/*.md`. A dispatch instruction added to any of them is authorized without editing the clause. At the moment this surface was made property-based the bundle instructed dispatch at Phase 1.4 (`prflow:branch-setup`), Phase 1.6 (`prflow:issue-claim-auditor`), Phase 2.1 (`code-explorer`), Phase 2.2 (`code-architect`), Phase 3.4 (`prflow:ac-claim-verifier` and `prflow:ac-evidence-verifier`), Phase 4.1 (the `prflow:docs` subagent), Phase 4.2 (the `prflow:pr-description` subagent), and the interactive-skill Agent-tool wrapper (instructed in the root, not any phase file). The clause names none of these — it names the property — precisely so a later-shipped point does not require re-editing it and cannot silently fall outside it.
- **The Phase 3.3 review engine**, which the orchestrator runs in its own context. Its own injection-condition clause authorizes its roster and must be resident for that authorization to hold — inherited when Phase 3.3 drives the engine through the `review-and-fix` Skill tool, and carried by the engine's own files on its degraded read-the-engine-from-the-tree arm.
- **The consumer prompt extension**, but only for the dispatch points it delivers through the `load-prompt-extension.sh` ladder. This repository's own extension instructs one before any prompt-surface edit. The extension-derived grant is **bounded to what that ladder delivers and the clause fixes its own extent** rather than delegating it to whatever an in-tree file says, because `devflow-implement.yml` sets no trusted extension root: an implement run resolves its extension from the checked-out pull-request head, unlike the review tiers, which materialize a base-ref copy so a pull request cannot rewrite its own run's prompt.

The clause grants nothing those surfaces do not instruct. Because it is orchestrator-root prose, a run that loses everything else to context compaction still holds it beside the injected prohibition, so it stays always-resident rather than moving into a phase file or gated reference. The word **testing** survives in both sentences (carrying the Phase 3.4 evidence-verifier exception) deliberately: issue #1581's recorded decision that Phase 2.3's verification sweeps stay inline rests on it. This surface has no in-tree mirror and no presence/count pin — it is agent-executed prompt prose whose only reader is the runtime agent, so the review pass, not an automated regression, is its control.

### Nested-skill tail-call guard (Skill rule, completion re-anchor, and `CLAUDE.md` carve-out)

The Phase 4.1 re-anchor above generalizes into a broader guard against a *nested `Skill` tail call* stopping the run early (issue #366). A nested `Skill` runs as a tail call, so an interactive skill's terminal "ask the user / apply with approval" step becomes the *run's* terminal step, stalling the run mid-phase with the workpad frozen at an in-progress `Status`; a non-interactive nested skill can instead complete cleanly but leave the phase continuation evicted from the working set. Three coupled clauses in `skills/implement/SKILL.md` (all in the always-resident orchestrator body, pinned in `lib/test/run.sh`) close both variants:

- **Exhaustive, exclusionary Skill rule.** The *only* skills the orchestrator may invoke via the Skill tool are `simplify` and `review-and-fix` (code review). `pr-description` is **not** among them: as of issue #1577 Phase 4.2 dispatches PR-description generation and its claim audit inside a context-isolated Agent-tool subagent (mirroring §4.1's `prflow:docs` subagent), so `pr-description` is authorized as a §4.2 bundle dispatch point under the dispatch-authorization surface above (which authorizes by property rather than by naming it), not by this Skill rule. Any approval-gated or interactive skill — one whose procedure ends in an "ask the user" / "apply with approval" step (e.g. `claude-md-management:revise-claude-md`, the `superpowers` `brainstorming` skill) — must **never** be invoked from inside an autonomous phase, generalizing the existing precedent that the autonomous run does not invoke the full interactive `/prflow:create-issue` pipeline. This clause prevents the *observed* incident: an interactive skill stalling mid-procedure awaiting approval, a point no completion-anchored re-anchor can ever reach.
- **Nested-skill completion re-anchor.** After completing any nested skill's *procedure* (anchored on completion of the nested procedure, **not** on the `Skill` tool call's immediate return — that return is merely the loaded skill body the orchestrator then executes over later turns), and before any other action, re-`Read` the current phase file and resume the interrupted step, **never re-invoking the nested skill** (the same idempotency clause the Phase 4.1 re-anchor carries). This closes the *latent* variant where a non-interactive nested skill completes but the continuation was evicted. It lives in the always-resident body for the same eviction-resistance reason.
- **`CLAUDE.md` edit carve-out.** `CLAUDE.md`'s Conventions section mandates `revise-claude-md` / `claude-md-improver` for `CLAUDE.md` edits, but invoking either mid-run would reproduce the very stall the exclusionary rule prevents. So any `CLAUDE.md` edit an autonomous run is *required* to make — by a Phase-3 review finding **or** by the issue's own acceptance criteria — is made **directly by the orchestrator**, citing the carve-out and recording it in the workpad; interactive/human sessions still use `revise-claude-md` / `claude-md-improver`. This is one half of a coupled pair with a matching Conventions bullet in `CLAUDE.md`, kept in lockstep.

### The Skill tail-call hazard, and the three cross-phase rules that contain it (issue #362)

The two guards above catch a run that *under-completes* Phase 4. A distinct failure kills a run outright, anywhere in the lifecycle: **a mid-phase Skill-tool invocation is a tail call, not a subroutine call.** The nested skill's body arrives as a new instruction gradient, so when that skill's own procedure ends in a user-facing report or approval step, the implement run ends *with* it — the workpad freezes at an in-progress `Status`, no terminal reaction fires, and nothing announces the death. (Observed on issue #356: the run invoked `claude-md-management:revise-claude-md` mid-Phase-3.3 and died on that skill's final approval step. The terminal-status self-check above cannot fire, because the resident instruction gradient at that moment belongs to the nested skill, not the orchestrator.) Three always-resident cross-phase rules in `skills/implement/SKILL.md` contain it — always-resident because a Skill-return eviction can strike in any phase, and only the resident body is out of its reach:

- **Subagent path for interactive skills (the Skill rule).** A mid-run edit that project conventions route through an *interactive* skill — any skill whose procedure ends in a user approval step — is performed by dispatching that skill inside a context-isolated **Agent-tool subagent** whose prompt pre-grants the approval, never by invoking it through the Skill tool mid-phase. The subagent absorbs the nested instruction gradient and hands control back. **"Context-isolated" scopes context, never the working copy** — unless the runner hands the subagent a checkout of its own, it edits the same files the orchestrator has open, so the orchestrator commits its own work before it dispatches; the canonical statement of that condition, its degraded arms, and the `#192` incident behind it is the commit-before-dispatch convention in `CLAUDE.md` (issue #1254). `simplify` and `review-and-fix` stay direct Skill invocations precisely because neither ends in a user approval step; `pr-description` is no longer a direct invocation at all — Phase 4.2 dispatches it into an Agent-tool subagent (issue #1577), and it is authorized as a §4.2 bundle dispatch point under the dispatch-authorization surface above, not as a direct Skill invocation. The rule is phrased repo-agnostically (the orchestrator ships to consumer repos); this repo's own instance of it lives in `CLAUDE.md`'s "Updating `CLAUDE.md`?" convention, which names `revise-claude-md` as the interactive skill to dispatch that way.
- **Generalized mid-phase re-anchor.** After **every** Skill-tool return mid-phase — not only the Phase 4.1 docs subagent — the orchestrator re-`Read`s the current phase file and resumes at the step immediately following the invocation, never re-dispatching the skill that just returned. This is the same eviction defense as the Phase 4.1 re-anchor, generalized from one subagent return to every nested-skill return; the older rule remains, now scoped to *subagent* returns.
- **Non-interactive self-answer rule.** On the cloud tier (`GITHUB_ACTIONS` set) there is no user to answer a nested skill's question, so asking one strands the run. The orchestrator answers such a question itself on the user's behalf — the issue description is the primary guide, the workpad `## Plan` and `## Acceptance Criteria` secondary — records each self-answered question and its answer via `--note`, and continues the nested procedure. An interactive local run still asks the user. The rule reaches **only** questions a nested skill directs at the user: it never answers the issue's own open questions, and a workpad `Blocked` pause stays a pause.

### Local-tier Stop-hook backstop (`lib/implement-stop-guard.sh`)

The workflow-level stall backstop below is **cloud-only**, so an unattended *local-tier* run that dies mid-phase has no deterministic net. (The reason is *not* that `Stop` hooks are unavailable on the cloud tier — `claude-code-action` removes `.claude/` and then **restores it from the base branch**, so a base-registered `Stop` hook does execute inside the action; `docs/internal/execution-file-shape.md` records the observation, **`FIRED`**, from probe run `29224205805`. What makes the cloud net workflow-level is that it must key on the workpad `Status` *after* the `claude` step has ended, which a hook inside the session cannot do; and the guard here is repo-local, so no consumer's cloud run wires it either way.) `lib/implement-stop-guard.sh` is that net. It is **repo-local by design**: it is wired in this repo's own `.claude/settings.json` and ships to no consumer repo.

The guard is **marker-gated**, so an ordinary session never pays for it. Phase 1.3 writes a run-marker `.prflow/tmp/implement-active-<issue>` the moment the workpad exists (gitignored, anchored to the repo or worktree root), recording the run's owning session id as the marker's first line when the runner exports one (Claude Code's `CLAUDE_CODE_SESSION_ID`, the same value the Stop payload carries as `session_id`) and leaving the marker empty when it does not; the always-resident *Outcome reaction* block — which already binds every terminal `Status` transition — removes it at each of them. On `Stop`, the guard:

1. allows immediately when `GITHUB_ACTIONS` is set (the cloud tier has its own backstop);
2. globs for a marker with pure bash and **allows immediately when none exists** — this arm spawns no interpreter and makes no network call (only the one local `git rev-parse` its repo-root resolver runs), which is the property every non-implement session relies on;
3. allows when `python3` is unavailable (its own breadcrumb, not folded into the parse arm below), and otherwise parses `session_id` out of the hook's stdin JSON, allowing when the JSON is unparseable, the id is missing, or the id is unsafe as a filename component;
4. allows when this session's sentinel `.prflow/tmp/stop-guard-<session_id>` already exists;
5. allows, keeping **every** marker, when `scripts/workpad.py` itself is absent — `python3 <script>` exits 2 on an unopenable script, which is the very code `workpad.py` uses for "no workpad", so without this check a missing helper would be read as a stale marker and delete it, silently disabling the backstop;
6. otherwise reads each marker's live workpad `Status` with `scripts/workpad.py status <n>`, which is the **source of truth** — the marker only gates *whether* to ask.

`workpad.py status` routes the outcome: a `terminal` class deletes the marker and continues (self-heal, so a marker left by a killed run costs at most one query) — **regardless of which session owns the marker**, so the self-heal is unchanged by the ownership arm below; exit 2 (no workpad) deletes the stale marker likewise; exit 1 (unreadable), exit 3 (`gh` transport/auth failure), and an unrecognized status class all keep the marker and **fail open** — the guard never blocks on a workpad it could not read. When several markers are present the first `interim` one that is *not owned by another session* blocks; markers after it in scan order are simply re-scanned on a later Stop event, so their self-heal is deferred, never lost.

On `interim`, the guard reads the marker's first line to decide ownership (issue #1222). Ownership is compared **like with like**: only when both the marker's recorded first line and this stop's payload `session_id` are non-empty and well-formed under the filename-safe charset check does the guard treat them as comparable. A marker owned by **another** session — a well-formed recorded id that differs from the stopper's — never blocks that unrelated session: the guard prints an issue+status breadcrumb (so the "a run may be stuck" signal survives), writes **no** sentinel, and keeps scanning. This is why a live implement run for issue A no longer blocks an unrelated session that merely resolves the same checkout. Every **absent** identity fails **closed** and blocks exactly as before — a zero-byte marker (every marker written before this change), an empty/blank first line, an unreadable marker, or a first line carrying a char outside the charset. Solely on an `interim` marker owned by **this** session (or one carrying no usable identity), it writes the sentinel, prints to stderr an instruction naming the issue and the interim status word, and exits **2** — the documented Stop-hook code that prevents the stop and feeds stderr back to the agent. The instruction addresses both readers: an implement run is told to return to the phase that owns the remaining work and drive `Status` to a terminal value; any other session is told to say the guard blocked the stop and simply end its turn again.

The `session_id`-keyed sentinel bounds the guard to **at most one block per session**, so a run that genuinely cannot finalize is never trapped. Every non-blocking path exits 0 with a stderr breadcrumb naming *that arm* (including a failed sentinel write, which allows rather than blocking without a bound). The hook entry in `.claude/settings.json` therefore carries a short `timeout` and — load-bearing — **no `|| true`**, which would swallow the blocking exit 2 and neuter the whole mechanism; `lib/test/run.sh` pins that absence against the guard's own command string, and drives every arm as a unit test.

### Resume detection of an existing PR (`agents/branch-setup.md` §1.4, `phase-3-review.md` §3.1)

Since issue #1582 the §1.4 branch resume pre-check, the reuse-vs-create Signals, feature-branch creation, and §1.4.0.5's Verdict-B classification are executed by the **dispatched `prflow:branch-setup` subagent** (`agents/branch-setup.md`), which shares the orchestrator's checkout and never a worktree; the orchestrator dispatches it (committing any uncommitted tree state first, issue #1254), re-reads `git branch --show-current` on return, then keeps the §1.4.1 checkpoint contract, its invocation, and §1.5 orchestrator-inline. The behavior below is unchanged by that move — only its home file is now the agent, not `phase-1-setup.md`. The §3.1 counterpart guard stays in `phase-3-review.md`.

A re-triggered run — a manual retrigger, or the stall backstop's auto-resume — may already have a feature branch and an open draft PR from its first attempt, while the local harness hands it a *fresh* worktree on a different branch. §1.4's original Signal 1 (linked worktree) would adopt that worktree's branch, opening a second branch and a second PR and silently abandoning the committed work. A **resume pre-check now runs before Signal 1**: it reads the workpad's `**Branch:**` line and queries the issue's open PRs both by head branch and by body reference (either query alone has a blind spot). When an open PR exists, the run checks out that PR's head branch — fetching it first when absent locally — and skips branch creation entirely; with several open PRs it picks the one whose head matches the workpad `Branch` line, else the newest. If the checkout is refused because the branch is already checked out in another linked worktree, the run continues in *that* worktree rather than duplicating the branch. With no workpad `Branch` line and no open PR, §1.4 behaves exactly as it did before the pre-check existed.

**The pre-check is unconditional, it is the authority on branch adoption, and it records its outcome durably (issue #1134).** It runs on every §1.4 entry — fresh run, resume, and terminal re-trigger alike — and no value of Phase 1.3's `resume-kind:` marker waives it. The two surfaces read different evidence and answer different questions: Phase 1.3 classifies the *workpad* (its `Status` word and whether a `classification: ` note is present) and feeds only the Phase 2 §2.0 gate, while this pre-check reads observable repository state and decides which branch the run works on. Where they disagree, the pre-check governs — the case that made this explicit was a backstop resume whose first attempt's workpad writes had been silently denied, so Phase 1.3 classified it `fresh` while that attempt's branch and an open PR closing the issue were both on the remote, and the run started a second branch. `fresh` means only *this workpad carries no record of a prior attempt*. Symmetrically, the observable state is deliberately **not** promoted into the `resume-kind:` classification: a terminal re-trigger over a completed run routinely still has an open PR closing the issue, and relabeling that population as an in-flight resume would arm the §2.0 gate over the prior run's stale all-`- [x]` Plan — the failure that gate's first conjunct exists to prevent. So the three-token vocabulary is unchanged and a run whose pre-check adopted a branch under a `fresh` marker simply re-runs full discovery over it. Every arm of the pre-check now writes one durable `resume-precheck: ` workpad note naming the state it consulted (the `**Branch:**` value, which queries ran, what was selected), so an adoption is distinguishable from a first attempt from the workpad alone; nothing parses that note, and branch creation is reachable only through a recorded outcome. Its adoption operand is an **open pull request** for the issue, never the bare existence of a branch named for it — stated so that later work which changes when an implement run's branch first carries commits can be sequenced against this pre-check rather than assuming its behavior.

Since issue #780 this pre-check is also a **provenance producer**: the landed-resume path it takes routes onward into §1.4.0.5's Verdict B classification, and the PR-linkage operands that classification reads are the entry this pre-check selected, plus the query field naming which of its two queries selected it. Its `gh pr list --json` field list is therefore coupled to that classification — a field the query stops fetching is a conjunct the classification can no longer satisfy. See *Ahead-of-base branch-state preflight — Verdict B* below for the operands and their gathering rule.

**The §1.4 pre-check is only half of it — §3.1 carries the matching existing-PR guard, and the resolution lives in a tested helper.** §1.4 adopts a branch, but a resumed run still walks into §3.1's `gh pr create`, and on a resume that PR already exists (created by the prior attempt), so a bare create aborts with *a pull request already exists* and wedges the run. The decision is *branch-selecting* logic, so it is not inline shell in the skill body (issue #782): §3.1 invokes `scripts/resolve-existing-pr.sh` as a single leading-token vendored-literal command, passing only the issue number — the helper re-derives the head branch and the base internally, because neither survives the shell boundary between one fence and the next. This follows the repo's workflow inline-shell extraction convention, whose reference implementation is `scripts/describe-denial-count.sh`, and `lib/test/run.sh` drives every arm plus the arm order over the full input matrix (`gh` non-zero, empty result, one PR, two PRs on one head, empty branch name), so a reordered or collapsed arm turns the suite RED at the desk.

The helper prints **exactly one token line** with a matching exit code — `ADOPT <n> OK` (0), `ADOPT <n> WARN:<checks>` (0), `CREATE` (2), `REFUSED` (3) — and it has no silent path, so a fence that prints *nothing at all* is a harness refusal the skill routes exactly as `REFUSED`. The arms:

- **Adopt** the open PR (the newest by `createdAt` on that head), leaving its body — and its §1.4-refreshed `[View run]` line — untouched, and resolving its URL by explicit PR number rather than by branch. Adoption is **validated**, not head-branch-match alone: the helper checks that the PR lists the run's issue in `closingIssuesReferences` and that it targets the run's base, and names each failed check in the `WARN:<checks>` token (`closes-issue`, `base-ref`, in that order). Adoption still proceeds on a `WARN` — a wrong-PR adoption must be *visible*, not stopped — so §3.1 records the failed checks durably on the workpad with `--reflection-kind note` before continuing, rather than letting them vanish into stderr.
- **Create** when the query ran cleanly and found no open PR.
- **REFUSED** when the question could not be answered at all — deliberately asymmetric: on a resume it is a terminal `Blocked` stop with a durable reflection, because creating blind risks duplicating the prior attempt's PR; on a fresh run it falls through to the create, because there is nothing to duplicate and gating the common path on a second network call would trade a real risk for a new one. `REFUSED` never collapses onto `CREATE`.

A `gh pr create` that fails takes the resume arm's terminal stop as well, rather than continuing into the PR-link write with no PR; the create and PR-link fences each print their own `create:` / `pr-link:` outcome token so the run reads success as an observable instead of inferring it from stderr. Since issue #1210 two more things hold on the create path. First, the CREATE arm **pushes `HEAD` to an explicitly-named destination** (`origin` + the branch's full ref — never a bare `git push`, matching `scripts/update-branch-checkpoint.sh`'s "Never a bare `git push` here" reasoning; `git config` is not read in-fence because it is granted on no implement profile) *before* the create, because `gh pr create` only defaults `--head` correctly when the branch is already pushed at the same commit — passing `--head` would *skip* that check rather than satisfy it, and the failure it prevents is a `gh` refusal that cannot confirm a pushed branch and cannot prompt, **not** a git-worktree effect (`refs/remotes/*` is a shared store, so a linked worktree sees the same server-side records). Second, the create fence **captures `gh`'s stderr** and the failure stop carries that captured text into the `blocked` note, so the run names a cause rather than only `create: failed`; the separate "printed nothing at all" harness-refusal case is unchanged. The matching Phase 2.5 commit-push likewise now detects and acts on a failed push (naming the local permission-refusal and cloud `.github/workflows/`-only rejection modes, issue #357). The authoritative statement of the resolution contract is the header comment of `scripts/resolve-existing-pr.sh`; §3.1 of `skills/implement/phases/phase-3-review.md` holds the routing prose. The helper's vendored-literal token is granted in the `implement` profile of `lib/capability-profiles.json` (an implement-only grant — the `review` profile lock is untouched); per the grant-timing bootstrap that grant is in-PR-inert and takes effect after merge.

### Stale-checkout guard for adopted branches (`agents/branch-setup.md` §1.4, `phase-1-setup.md` §1.6, `phase-2-implement.md` §2.1)

An implement run that *adopts* a pre-existing branch (the worktree/`USE_CURRENT` path) used to perform **no base fetch** — the explicit `git fetch origin "$BASE"` ran only on the new-branch arm — so every later verification read the tree as it stood at the fork point, possibly days behind the base. The verified #325 incident: a run adopted `worktree-issue-322`, forked 43 hours before PR #319 merged, grepped its stale tree for the jq fixture that issue #322 truthfully said "already shipped in PR #319," found nothing, and recorded "Code wins: treating it as not-yet-shipped" — a **false refutation of a true claim** that re-implemented merged work into a human-resolved dirty merge (while the same run's dependency note said "#319 MERGED, safe to build on"). Four bounded rules close this:

- **Freshness guard (§1.4).** The adopted-branch arm now runs the same breadcrumbed `git fetch origin "$BASE"`, derives how far `HEAD` is behind `origin/$BASE` with `git rev-list --count HEAD..origin/$BASE` (git is preflight-guaranteed; the compare uses bash builtins per guard-class 2), and records the result in the workpad — **including the behind-by-0 case, so freshness is provably checked, not assumed.** A fetch failure on this arm records a **freshness-unverified reflection and continues** (the tree is marked unvouched); it never hard-blocks adoption, unlike the new-branch arm's `exit 1`.
  - Since issue #779 that fetch uses the forced refspec `+refs/heads/$BASE:refs/remotes/origin/$BASE` — the same one `scripts/update-branch-checkpoint.sh` uses, and the same one the new-branch arm's create fence now uses — so neither arm can read a remote-tracking ref an unforced fetch left unadvanced.
- **Read-target rule (§1.6 + §2.1, coupled mirrors).** When the adopted branch is behind `origin/$BASE` — unconditionally when freshness is unverified, and equally when no freshness record exists at all (Phase 1.4's workpad write is best-effort; a missing record reads as unverified, never as behind-by-0) — verification reads that adjudicate shipped-work claims target `origin/$BASE` state (`git show origin/$BASE:<path>`), never the unfetched fork point. It governs read targets only; the working branch is instead reconciled at the **Phase 1.4 update-branch checkpoint** (see *Base-branch update checkpoints* below), and this rule (with the coherence rule) stays in force whenever that checkpoint's outcome is neither `UPDATED` nor `UP_TO_DATE`.
- **Cross-pass coherence rule (§1.6 + §2.1, coupled mirrors).** A "shipped/landed in PR #N" claim is REFUTED from tree reads only after a read-only `gh pr view N --json state,mergeCommit` confirms PR #N is MERGED **and** `git merge-base --is-ancestor <merge_commit_sha> HEAD` confirms the merge commit is an ancestor of the checkout. MERGED + non-ancestor — and every indeterminate outcome (shallow-history ancestor error, `gh` failure) — yields "checkout stale — refresh and re-verify," never "code wins." The §2.1 code-wins paragraph carries the matching qualifier: the code wins over a descriptive claim only when the code being read is verified fresh.
- **Sibling-PR annotation rule (§4.0).** When split-AC composition writes an already-shipped annotation, it must name the sibling PR **and its merge state at filing time** (e.g. "shipped in PR #N, unmerged at filing"), so a later run's verification checks PR #N's live state and ancestry (the coherence rule) instead of grepping whatever tree it holds. The parent's decided criteria remain the unreworded semantic source; the composed sibling-PR annotation is the stated, bounded exception to the 2.2.5 verbatim guarantee.

The two coherence-rule sites and the two read-target-rule sites are **coupled mirrors** (edited and pinned together per the `CLAUDE.md` coupled-invariant discipline); the change adds no helper, workflow, allowlist, or config surface — consumers inherit it through the shared skill.

### Ahead-of-base branch-state preflight — Verdict B (`agents/branch-setup.md` §1.4.0.5, `scripts/preflight.py branch-state`)

The freshness guard above derives only the *behind*-by count, so a branch that is not behind the base can still carry unrelated **ahead-only** history — foreign commits every downstream step then treats as the run's own, so §1.5 publishes them and the PR diff carries their files (the PR #524 incident: four unrelated files forked from an unpushed local-`main` commit that read "behind-by-0 / up to date"). **Verdict B** closes that blind spot. It runs on the **adopted-branch** arm (`USE_CURRENT` set — the arm a run that adopts a branch takes) and, since issue #780, on the **landed-resume** arm (`LANDED` is `yes`, which never binds `USE_CURRENT`) — on the adopted arm after the freshness record, and on both arms **before** the end-of-§1.4 checkpoint invocation and the §1.5 push, so a stop verdict still precedes every history-mutating step. §1.4.0.5 classifies the working branch against the base by writing the state it holds (base, current branch, workpad body, prior-proceed evidence, workpad provenance, open-PR facts, repo) to `.prflow/tmp/branch-state-$ISSUE_NUMBER.json` with the Write tool and invoking `scripts/preflight.py branch-state --state-file …` as a single leading-token command.

**Two provenance sources for ahead history (issue #780).** This section is the **canonical statement** of that admission and its threat model; `agents/branch-setup.md` §1.4.0.5 (the dispatched subagent that runs Verdict B since issue #1582) and `docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md` carry coupled operative summaries, and `scripts/preflight.py`'s header points here rather than restating it — edit them together.

Ahead-of-base commits may be vouched for by the **workpad** (`provenance_established`) or by the **open-PR linkage** — an open PR in *this* repository whose head branch is the working branch, which is not cross-repository, and which is tied to this issue either by closing it or by having been selected by the pre-check's head-branch query. Its operands (`open_pr_branch` / `open_pr_closes_issue` / `open_pr_cross_repository` / `open_pr_selected_by`) were promoted by #780 from payload-only context to load-bearing gate operands; each is either fetched by, or derived from a field fetched by, the §1.4 resume pre-check's `gh pr list --json`.

The second source is what makes the landed-resume arm classifiable at all: that arm has ahead history by definition, while its workpad provenance is unestablished across two large populations — a cloud run whose §1.3 `HANDOFF` is `unknown`, and a local resumed run that did not create its own workpad — so a workpad-only gate would have converted ordinarily-resumable runs into terminal `DECISION_BLOCKED` stops.

**Threat model, stated rather than papered over.** The workpad is a marker-detected *issue comment* any issue-commenter can forge, whereas the PR-linkage record requires push access to this repository — but that population **overlaps** the population that can push the branch it vouches for, so the source does not defend against a hostile collaborator and no such claim is made. It is admitted because it is strictly stronger than the workpad against the wider commenter population, and because `VALIDATED_RESUME`'s other conjunct (published-tip reachability) already rests on a signal any pusher can produce.

**Three properties of the implementation.** (1) The **issue-linkage is a disjunction** — closes-this-issue *or* head-branch-query selection — mirroring the pre-check's own rule that a head-branch match is a resume target by construction; requiring the closing linkage unconditionally would terminally block a run the pre-check had just landed, the outcome this source exists to remove. (2) When both sources vouch the **workpad takes precedence**, because its recorded branch and proceed verdict resolve a finer verdict family than the PR can — so a workpad-vouched run classifies exactly as it did before #780. (3) On the PR-vouched path the untrusted workpad is **neutralized, not consulted**. Every conjunct fails **closed**; a *partial* gather of the four operands is **refused** (`UNAVAILABLE state`) rather than read as a refutation the caller never established; and every boolean operand the helper reads is likewise refused when written as a quoted string.

**Honest scope on the landed-resume arm.** There, `current_branch` is `$HEAD_REF` and the PR operands come from the entry the pre-check selected, so the head-branch conjunct is a *composition self-check*, not a live screen. The screens that can actually fire on that arm are the fork-headed PR, a body-query-selected PR with no closing linkage, a partial gather, and — the substantive one — a `HEAD` no longer reachable from `origin/<branch>`.

The helper owns the recognizer and derivation semantics (ahead-of-base count with shallow unshallow-once-then-rederive, recorded-branch existence, published-tip reachability) and, mirroring `scripts/update-branch-checkpoint.sh`'s one-token-stdout contract, prints exactly one verdict token with a matching exit code. It is **read-only with respect to history** — it derives via `git rev-list`/`git rev-parse`/`git check-ref-format`/`git merge-base` plus a single `git fetch --unshallow` on a shallow repo, and never resets, rebases, checks out, commits, merges, pushes, or deletes a branch — so a stop verdict makes **no history mutation**:

| token | exit | meaning |
| --- | --- | --- |
| `FRESH` | 0 | no ahead-of-base history (fresh fork, or adopted branch fast-forwarded to base) — proceed to the end-of-§1.4 checkpoint invocation |
| `VALIDATED_RESUME` | 0 | ahead history validated as this run's own prior work (published-tip reachable, corroborated by a prior proceed verdict) — proceed to the end-of-§1.4 checkpoint invocation |
| `AMBIGUOUS <payload-file>` | 2 | ahead history could not be validated as this run's own and needs a human decision (recorded branch matching without a verdict, divergent-but-recorded branch, duplicate/absent Branch line) — **stop before the end-of-§1.4 checkpoint invocation and §1.5**, flip the workpad `Blocked` |
| `DECISION_BLOCKED <payload-file>` | 2 | ahead history under unverified/hostile provenance, a named divergent branch that does not exist (marker-forged or corrupted workpad), or a divergent existing branch with no prior proceed verdict (`divergent-without-verdict`) — same terminal `Blocked` stop |
| `UNAVAILABLE <reason>` | 3 | the ahead count, base ref, or existence probe could not be established (`base`/`count`/`shallow-probe`/`shallow-undeepened`/`existence-probe`/`state`) — fail closed to the same `Blocked` stop rather than risk a spurious proceed |

Any non-zero exit is a non-clean measurement — the run never proceeds to the end-of-§1.4 checkpoint invocation on it. The ordering is load-bearing: the classification completes after branch determination and before any history-mutating step (the checkpoint's base merge, the push), so a stop verdict aborts the run with the working tree unchanged and no local branch tip moved (the shallow deepen's refspec does force-update the `origin/$BASE` remote-tracking ref, which can advance if origin's base moved, and `git fetch` tag-auto-following can additionally create `refs/tags/*` entries for tags reachable from the newly-deepened history — both are ref changes outside `refs/heads`; no local branch and no tracked file is touched). The state file is written with the Write tool (a granted class into `.prflow/tmp/**`) and the helper invoked as the repo-relative vendored literal leading token — never behind a `VAR=value` prefix, a `bash <path>` wrapper, or a `>`-redirect (denied cloud shapes, issues #363/#401); a local runner that refuses the direct helper path falls back to `python3 <resolved path> branch-state …`. The change adds the `preflight.py` subcommand and the §1.4.0.5 prose; no workflow, allowlist, or config surface changes — consumers inherit it through the shared skill and the vendored helper.

### Base-branch update checkpoints (`prflow_implement.update_branch_checkpoints`)

An `/prflow:implement` run can take hours while sibling PRs merge, leaving its feature branch behind base. In a repo whose branch protection requires PR branches to be up to date before merge, the run would otherwise publish a PR on a stale branch — skipped/missing CI, and — because PRFlow's own `prflow_review.require_up_to_date` deferral is head-scoped and cannot see the *base* advancing (the known limitation in [`DEVFLOW_SYSTEM_OVERVIEW.md`](DEVFLOW_SYSTEM_OVERVIEW.md) §14) — a PR that can strand indefinitely behind a neutral "branch behind base" check. The run therefore brings its branch up to date with the configured `base_branch` at **four checkpoints**, all through one shared helper — `scripts/update-branch-checkpoint.sh` — so every state the merge gate or an auto-review consumes is current, including the terminal pushed state (up to the residual gaps §14 notes: a deferral already stranded on an earlier base advance, and a base that advances in the narrow window between the checkpoint push and the review firing):

1. **End of Phase 1.4 — every arm.** The helper is invoked as the **last** step of §1.4, on the new-branch arm, the adopted-branch arm, and the landed-resume arm alike (issue #779): Phase 1 reconciles the branch with the base on **every** path that reaches Phase 1.5, so a resumed run cannot proceed on a stale base. It is not gated on `USE_CURRENT`, and it takes no operand naming which arm was taken — the helper resolves the base from `.prflow/config.json` and the branch from `HEAD` inside its own process. On the adopted arm it runs after the freshness record and after §1.4.0.5's Verdict B; since issue #780 **Verdict B also runs on the landed-resume arm** (the §1.4 freshness record remains adopted-arm-only), so that arm now reaches the checkpoint *with* an ahead-of-base classification. Even so, a `CONFLICT` **at this call site only** routes to `Blocked` as needs-human-reconciliation on every arm rather than to §1.4.1's agent-resolution contract — #780 revisited that routing and left it standing, because classification establishes the ahead history's *provenance* but not the orchestrator's *authorship context* over it, and because no operand readable at the call site distinguishes the landed-resume arm (each fenced block may run as its own shell, and `scripts/workpad.py`'s notes are append-only, so a prior attempt's record — Verdict B's own verdict included — is indistinguishable from this run's). Checkpoints 2 and 3 keep the inherited `CONFLICT` contract unchanged; checkpoint 4 inherits the same resolution path but bounds it to a single re-invocation. Both of §1.4's own base fetches use the same forced refspec the helper uses (`+refs/heads/$BASE:refs/remotes/origin/$BASE`), so every §1.4 path resolves the same base tip.
2. **Pre-draft-PR (Phase 3.1).** Immediately before §3.1's existing-PR guard resolves (and so before any `gh pr create`), so the self-review and first review pass see current base — on the guard's adopt arm the checkpoint still runs, only the create does not.
3. **Each fix iteration + Loop Exit (`/prflow:review-and-fix` loop).** After each iteration's fix commit and immediately before that iteration's push — the helper's single push carries the fix and the base merge together — this per-iteration checkpoint is gated on the `--push-each-iteration` flag alone (`skills/review-and-fix/references/fixing.md`). The **Loop Exit** base-branch-update checkpoint (Checkpoint 3), by contrast, `skills/review-and-fix/references/loop-exit.md` gates **only in PR mode with `--push-each-iteration`** — not on the flag alone — so a current-branch-mode run under the flag runs the per-iteration pushes but *not* the Loop Exit checkpoint. It runs once at Loop Exit after the observability commit, covering the terminal pushed state of a standalone `/prflow:review-and-fix N --push-each-iteration` run (which never reaches Phase 4.3). A direct invocation without the flag never touches the base. The **`prflow_implement.*`** off-switch also governs this checkpoint inside such a standalone review-and-fix run.
4. **Pre-ready (Phase 4.3).** After the clean-tree backstop and before the publish decision. A real merge (`UPDATED`) owes **no suite run of its own** at this checkpoint: the Phase 4.3 completion-evidence flight (issue #1087) runs after it and before the publish decision, over that same merged tree — checkpoint 4's merge is one of the candidate-changing operations that flight exists to cover — and its non-pass arm routes a failed suite, a non-empty skip population, or an unrunnable verification command to `Blocked` rather than publishing, so a second whole-suite run here would re-verify a tree the completion gate already gates on. Since issue #779 this checkpoint also **gates the completion claim**: the run grades the **first whitespace-delimited field** of the helper's emitted line (`emit "UPDATED $BEHIND"` prints `UPDATED 3`, so a whole-line test would be false for every real merge), records the observed token before publishing on `UPDATED`/`UP_TO_DATE`/`DISABLED` alike through the **keyed-checkpoint** carrier `workpad.py update --checkpoint base-update-checkpoint-4` (issue #1050) — a machine-readable evidence row `lib/fetch-pr-context.sh` derives into the bundle's `base_update_checkpoint4_present` field, so an absent record on a run that reached pre-ready is detectable without a substring search over the free-text note; the key is deliberately outside the `gha:` prefix so the review-tier cloud/local discriminator is unaffected. Since issue #1348 the terminal `--status Complete` write is **gated** on this exact keyed row (see the required-artifact gate below), so the earlier degrade-to-`--note` fallback for a non-canonical workpad body is **removed outright**: a `--checkpoint` that structurally no-PATCHes — a duplicated `## Progress` or an empty body (an *absent* `## Progress` is repaired since issue #1347: `--checkpoint` creates the section at the head of the section list ahead of its own section-shape validation) — now fails this step **closed**, and the run resolves the non-canonical workpad body and retries rather than recording an unkeyed row the terminal gate cannot read. The keyed row is what that gate resolves — and this checkpoint also **refuses both `gh pr ready` and the `Status: Complete` flip** — recording `Blocked` naming the observed line — when that field is `UNVERIFIED`, `PUSH_REJECTED`, `MERGE_IN_PROGRESS`, empty, or unrecognized. `CONFLICT` is exempt: it resolves per the inherited contract, the helper is re-invoked **once**, and that re-invocation's field is what the gate reads — a second consecutive `CONFLICT` takes the refusal arm. An invocation whose refusal the tier **reports** (a local classifier denial message, rc 127) is a distinct case — since issue #1347 it records through its **own** keyed checkpoint, `base-update-checkpoint-4-tier-refused` (also non-`gha:`, for the same discriminator reason), rather than a prose-only reflection, so a consumer can tell "the base was reconciled" from "the tier refused the check" instead of reading one indistinguishable blob; it still publishes as before, so a reported permission boundary never becomes a run-ending stop; since issue #1348 a `--checkpoint base-update-checkpoint-4-tier-refused` that itself exits non-zero fails **closed** at the terminal gate rather than degrading to an unkeyed reflection the gate cannot read. A **silent** cloud matcher denial is a disclosed residual: it produces no output and no failure signal, so it is indistinguishable from an unrecognized field and takes the refusal arm — the remedy is to grant the helper in `prflow_implement.allowed_tools`.

**The helper owns the whole mechanical sequence** — the off-switch read, base derivation, the pre-state guards, `git fetch`, behind-by derivation, `git merge --no-edit origin/$BASE` when behind, `git push`, and the push-race recovery arm — so a cloud call site invokes one granted leading-token command (the cloud allowlists grant no inline `git rev-list`, so the behind-by derivation and the base merge run inside the helper's own subprocess; `Bash(git merge:*)` *is* granted, but only for the agent-level `git merge --abort` the conflict contract prescribes at a call site). It is git-only plus `config-get.sh` reads (no `gh`, no `jq`), guard-class-2 throughout (every decision derives from git output, `python3`, and bash builtins). It prints exactly one machine-readable token with a matching exit code:

| token | exit | meaning |
| --- | --- | --- |
| `UP_TO_DATE` | 0 | behind-by 0; tree untouched |
| `UPDATED <n>` | 0 | merged and pushed (incl. via push-race recovery) |
| `DISABLED` | 0 | off-switch; tree untouched |
| `CONFLICT` | 2 | base merge left in progress (`MERGE_HEAD` present); conflicted paths + resolution contract on stderr |
| `UNVERIFIED` | 3 | the `base_branch` config read, fetch, or behind-by derivation failed, the tree was dirty, HEAD is detached / on no branch, or no merge base was reachable (even after the unshallow retry); nothing merged |
| `PUSH_REJECTED` | 4 | push refused twice (or a conflicted integrate); the local branch is restored to its pre-checkpoint SHA — *attempted, not guaranteed*: a failed restore keeps the token but emits a `WARNING` breadcrumb saying the tree may still carry the base-merge commit, and the call site hard-stops on that breadcrumb rather than continuing |
| `MERGE_IN_PROGRESS` | 5 | `MERGE_HEAD` existed at invocation; nothing touched |

A **`CONFLICT`** at checkpoints 2, 3 and 4 is resolved *in-run* (the Phase 1 checkpoint instead routes `CONFLICT` to `Blocked` as needs-human-reconciliation on every arm, aborting the merge first — issue #779): the agent resolves the conflicts (it holds full context of its own changes), runs the project test suite on the resolved tree, commits the merge, pushes, records the conflicted files, and re-runs the Phase 2.3.0 changed-contract sweep. A resolution whose suite run **fails** is **aborted** (`git merge --abort`, restoring the pre-checkpoint tree) before the run hard-stops — the workpad `Blocked` flip when implement-driven, the loop's native "stop and report" when review-and-fix runs standalone — so a failed resolution never remains in the tree. `UNVERIFIED`/`PUSH_REJECTED` are loud but non-fatal (record and continue) **at checkpoints 1-3; at checkpoint 4 they block publication and the `Complete` flip after one bounded re-invocation** (issue #779) — **with one exception: a `PUSH_REJECTED` whose stderr carries the failed-restore `WARNING` hard-stops too**, because the branch may still carry an unpushed base-merge commit that no clean-tree backstop can see (the divergence is in committed history); **`MERGE_IN_PROGRESS` hard-stops** (continuing would absorb an abandoned resolution into the next ordinary commit). The helper's one `git fetch --unshallow origin "$BASE"` retry on an out-of-shallow merge base is not theoretical: it targets the base ref explicitly because a depth-limited checkout's single-branch refspec would otherwise leave `origin/$BASE` un-deepened. Since issue #1219 this repository's own `devflow-implement.yml` and `devflow.yml` check out full history (`fetch-depth: 0`), so the shallow arm no longer fires on those tiers here; it stays live for any consumer still running an installed copy that predates that change. When even the unshallow retry cannot establish a merge base, the checkpoint degrades to `UNVERIFIED` — record-and-continue at checkpoints 1-3, publication-blocking at checkpoint 4 (issue #779) — never a bad merge.

**Config.** The off-switch is **`prflow_implement.update_branch_checkpoints`** (boolean, default `true`), read via `config-get.sh`: the checkpoints are disabled exactly when the value serializes to the string `false` — an explicit JSON `false`, or a shape `config-get.sh` serializes identically (the JSON string `"false"`, or `[false]`, since arrays comma-join); a missing config file, missing key, empty string, or any other value leaves them enabled (issue #312 valid-falsy discipline — the documented off-switch genuinely disables, and near-`false` shapes fail toward "off", the pre-feature status quo). On-by-default mirrors `stall_backstop.enabled`'s safe-direction default. A consumer repo without an up-to-date branch-protection rule keeps working unchanged apart from ordinary base merges on feature branches — and turns the whole mechanism off with one key.

### Workflow-level stall backstop (harness-side, `prflow_implement.stall_backstop`)

The two guards above are **agent-side**: they can only fire while the agent is still generating and re-enters its loop. A **cloud** `/prflow:implement` run has a failure mode they cannot reach — the headless `claude-code-action` session is single-shot, and the SDK ends the session the moment the model emits a tool-call-free turn (e.g. a narrate-and-hand-back turn right after `gh pr create`). When that happens at, say, the Phase 2→3 boundary, the agent never re-enters, so the terminal-status self-check is structurally unreachable — yet the Actions job still reports `success` (the action returns `subtype: success`, not `error_max_turns`). The run is then a green success that actually stalled mid-lifecycle, indistinguishable from a healthy one and feeding the stale-workpad retrospective gap (observed on issue #259 → PR #264 and issue #258 → PR #265).

A **workflow-level backstop** closes this, governed by two config keys under `prflow_implement.stall_backstop` (read via `config-get.sh`):

- **`stall_backstop.enabled`** (boolean, default `true`) — master switch. When `false`, the backstop is skipped entirely and the job behaves exactly as before (green on a mid-lifecycle stop). An unrecognized/missing value resolves to `true` (the safe, honest-failure direction).
- **`stall_backstop.max_resume_attempts`** (integer, default `2`, minimum `0`) — hard cap on automatic resume attempts. `0` means detect-and-fail-loud only; `N` means up to `N` auto-resumes before failing loud. A negative/non-integer value resolves to `2`.

When enabled, a post-`claude` step keys on the issue workpad `Status` (via `workpad.py status`, which reports the status as a `CLASS GLYPH WORD` line reusing the same `🚀`/`🎉`/`👎`/`💥`/`🛑` vocabulary — **never** on PR draft state, mirroring the agent-side self-check so an intended `implement_pr_state=draft` run that reached `Status: Complete` is never a false positive):

**Cancelled-run exclusion (issue #498).** A cancelled run is a decided ending, not a stall: the step additionally reads `job.status` (`JOB_STATUS: ${{ job.status }}` — the documented job-context string, deliberately not a status-check function, which the docs scope to `if:` conditionals), and only the exact value `cancelled` selects the cancellation path. Every other value (absent, empty, `success`, `failure`, any other token) leaves the table below byte-identical — fail toward resume, so an un-upgraded caller (a four-arg decide call, or a non-cancelled job status) never suppresses a resume. On `cancelled`: a **terminal** `Status` → `noop`; an **interim** `Status` → `flip-cancelled` (flip the workpad to `🛑 Cancelled` with the note `run cancelled (job.status=cancelled) — <run URL>`, post no comment, consume no resume attempt, exit 0); `unreadable`/`auth-failure`/unknown class → `skip-cancelled` (log one line, exit 0, no fail-loud diagnostic comment). Both arms post **no** comment — the run's own `cancelled` conclusion in the Actions UI is the record. The decision echo additionally prints `job_status=` so every future run records what the runner actually delivered. The exclusion is unconditional — no config key opts back into resume-on-cancel. A seconds-wide residual race is accepted and out of scope (a cancel landing *after* a latched hard-death signal can still post its re-trigger, recovering the latched signal not the cancellation), as is the pre-backstop/force-cancel loss (a cancel before the step can act leaves the workpad interim with no flip; nothing self-resumes, and recovery is a fresh manual trigger). A `Cancelled` workpad resumes through Phase 1's existing terminal-`Status` re-trigger arm on a fresh `/prflow:implement <n>`, exactly like a `Failed` workpad.

- **Terminal `Status`** → the class decides (issue #1025 widened `workpad.py status` so each terminal glyph carries its own class rather than collapsing to `terminal`): `Complete` 🎉 → `noop` (the job concludes `success`); `Blocked` 👎 and `Failed` 💥 → `fail-blocked`, which emits a `::error::` naming the issue number and the workpad `Status` and exits non-zero so the job concludes **non-`success`** — a run that produced no branch/PR (or blocked mid-lifecycle) is then visible in `gh run list` without opening the workpad, and the workpad is left unchanged (its 👎/💥 already truthful, and `flip_to_failed`'s `CLASS=interim` guard makes it a no-op on a terminal status); a **stale** `Cancelled` 🛑 read on a non-cancelled job → `noop` (never converted to a failure). (`Failed` is written by this backstop's own dead-run flip below, and `Cancelled` by its cancelled-run flip above, so a re-triggered run reads either as a decided end rather than a stall.)
- **Interim `Status`** (any 🚀 phase) → auto-resume: post a distinct audit comment (attempt *k* of `max_resume_attempts`) and re-dispatch `/prflow:implement <n>` so the skill's Phase 1.3 workpad-resume continues from where it stopped, bounded by the cap. **"Continues from where it stopped" is workpad-state continuity, not in-place phase resumption:** the fresh process re-enters Phase 1, and because the Phase 2 `code-explorer`/`code-architect` artifacts are non-persistent (neither agent declares a `Write`/`Edit`/`Bash` tool), Phase 2 is re-entered from its top — where the §2.0 resume-idempotency gate builds on the committed `## Plan` instead of re-running discovery/architecture.

**Denial-proof helper invocation on a resumed run (issue #405).** A resumed run — and every cloud helper invocation — must invoke bundled helpers with the **repo-relative vendored literal** (`.prflow/vendor/prflow/scripts/…`, `.prflow/vendor/prflow/lib/…`) as the command's **leading token**: never an absolute path (`/home/runner/.../scripts/workpad.py`), never the repo-root `scripts/…` form, and never behind a `VAR=value` prefix or a `bash <path>` wrapper. Each of those makes the command no longer *begin with* the granted literal, so the cloud allowlist silently denies it — and a resumed run that reaches for the absolute or repo-root form is denied on its very first `workpad.py` call and dies without resuming. The stall-backstop **resume comment now carries this discipline inline** (a `Resume note:` line in the comment body), so a resumed run receives the rule inside its own triggering comment even if it never re-reads the skill prose; the same rule is stated in the skill's always-resident orchestrator body. After two denials of a given command shape, switch to a listed legal form rather than iterating a third spelling. That covers a *denied* spelling; the distinct case where `scripts/workpad.py` **cannot be executed at all** — a host with no `bash`/WSL, a missing interpreter, or every invocation form refused — follows the **workpad-invocation ladder stated once in `skills/implement/SKILL.md`**: try that ladder's rungs in order, and when a run exhausts every rung available on its own tier it stops at Blocked, leaves the workpad status untouched rather than hand-writing one, and records the skip (naming the program and each rung tried) on the workpad, else the PR description, else as unrecordable.
- **Cap exhausted** (including `max_resume_attempts: 0`) → the job exits non-zero (red) and posts a distinct comment naming the stall for a manual retrigger.
- **Unreadable `Status`** (workpad missing / unparseable — `workpad.py status` exits 2 or 1, where exit 2 is "no workpad" and exit 1 covers both a missing/empty `Status` line and a present `Status` line whose word isn't in the canonical vocabulary (`Reviewing`/`Complete`/`Blocked`/etc.)) → fail closed (`unreadable` class) with a distinct diagnostic comment, never a false "stalled at X" claim.
- **Auth/API failure reading the workpad** (`workpad.py status` exits **3** — a `gh`-api/transport/auth failure such as an expired App installation token, reading either the workpad `Status` or the issue comment list that counts prior attempts) → fail closed (`auth-failure` class, distinct from `unreadable`) with an auth-specific diagnostic comment, and **without consuming a resume attempt** — the workpad may be perfectly healthy; only the read failed (issue #287).

**Dead-run `Status` flip → `💥 Failed` (issue #356).** On every **fail-loud** exit of the `Stall backstop` step that is reached after successfully reading a genuinely **interim** `Status` — the `fail-exhausted` arm (cap exhausted), the `mktemp` abort, the dropped-resume-comment abort, and the resume-posted-but-no-App-token abort — the step first performs a best-effort `workpad.py update <n> --status Failed --note "run died: <cause> — <run URL>"`, then exits with today's exit code. This introduces one new canonical **terminal** workpad status word, **`Failed`**, with the glyph **💥** (added to `workpad.py`'s `_STATUS_GLYPHS`; `_status_glyph` maps `failed`→💥; `cmd_status` classes it `failed` (issue #1025 widened the class vocabulary so each terminal glyph has its own class rather than collapsing to `terminal`); it is deliberately left out of `_STATUS_TO_PROGRESS_PHASE`, so a `--note` accompanying the flip nests under the most-recent-ticked `## Progress` phase, exactly like `Blocked`). Without this flip a dead run leaves its workpad frozen at `🚀 Implementing`, silently lying that it is still working; the flip makes the death visible in the run's own comment. The flip is guarded on the `interim` status class (a terminal/unreadable/auth-failure `Status` is never clobbered — fail closed) and is positional, not temporal: it is called only at genuine fail-loud exits, **never** on the green resume path (writing a terminal `Failed` before a resume would make the resumed run's own backstop read a decided terminal end and misjudge it — pre-#1025 a silent `terminal → noop` disarm, and since #1025 a spurious `fail-blocked` that concludes the resumed job non-`success` — so the flip must never precede a resume). It is best-effort — a flip whose `workpad.py update` fails emits a `::warning::` and leaves the step's exit code exactly what it is today — and stays inside the step's `set +e` discipline. **💥 is a workpad-only glyph with no triggering-comment reaction equivalent** (unlike 🚀/🎉/👎, which map to rocket/hooray/-1): the backstop emits no outcome reaction for a `Failed` flip. A `Failed` workpad resumes normally on a fresh `/prflow:implement <n>` re-trigger — the gate's early-acknowledgement refreshes the `Run` link and Phase 1.3's resume arm resets `Status` to `🚀 Setup`; `Failed` is not `Blocked`, so it never joins the Blocked pause branch. A dead implement run also stops masquerading as clean in the weekly retrospective: `lib/cheap-gate.jq`'s clean condition is `workpad_final_status == "Complete"`, so `Failed` (which `lib/fetch-pr-context.sh` now strips the 💥 from, like the other glyphs) gates non-clean with reason `workpad status not Complete`. The **🛑 `Cancelled`** flip (issue #498, the cancelled-run exclusion above) is the sibling: the same `interim` positional guard and best-effort `::warning::`, written on a `cancelled` `job.status` instead of a fail-loud exit. 🛑 joins 💥 as a workpad-only terminal glyph with no triggering-comment reaction equivalent; `lib/fetch-pr-context.sh` strips the 🛑 exactly like 💥, so `cheap-gate.jq` gates a `Cancelled` workpad non-clean with the same reason, and `skills/retrospective/SKILL.md`'s Stage A takes a defined `Cancelled` skip — never improvising a deliberate cancel into a `blocked` verdict feeding the pattern loop.

**Empty-branch record (issue #1261).** A terminated run that pushed **no** commit to its remote branch leaves the branch present and the workpad's recorded progress intact, so the aftermath reads as a partially-completed attempt rather than an empty one — and establishing that the branch is actually empty takes a deliberate commit-count check nothing in the artifacts prompts. So both terminal flips above (`💥 Failed` and `🛑 Cancelled`) now additionally record, on the workpad, whether any commit reached the run's remote branch. The three-valued decision and the note it writes live in `scripts/record-empty-branch.sh` — *beside* the step, keeping `scripts/stall-backstop-decide.sh` pure (no I/O) so the suite can still drive every decision branch deterministically — and are invoked from a `record_empty_branch` shell function called only from `flip_to_failed`/`flip_to_cancelled`, inheriting their positional `CLASS=interim` guard so the statement is written at a genuine terminal flip and **never on the resume path** (a no-commit statement written before a resume would be stale the moment the resumed run pushes). The decision is three-valued, not boolean, per the *unknown is not zero* rule: a branch **0 commits ahead** of its base gets an explicit no-commit statement (`NO_COMMIT`); a branch that **carries work** gets none (`HAS_COMMIT` — the absence is meaningful, so a false positive is as much a defect as a miss); and a state that **cannot be established** — the remote unreachable, the branch name unavailable, or the fetch/query failed — is recorded as *could not establish* (`UNESTABLISHED`), never collapsed onto no-commit (which would report a data-loss event that may not have happened). The producer's fetch is authoritative: a definite answer is written only when the base and branch refs were freshly fetched this invocation, so a failed fetch routes to `UNESTABLISHED` rather than trusting a possibly-stale remote-tracking ref. It is best-effort like the flips — a workpad-write failure emits a `::warning::` and never changes which exit arm the `Stall backstop` step takes — and it coexists with the terminal `Status` the flips write rather than overwriting it. The run's feature branch is read from the workpad `**Branch:**` line the helper receives as the workpad body.

On **every** resume — whether triggered by this backstop's auto-resume, a manual re-trigger, or an external stall-backstop retry — the `gate` job's early-acknowledgement step (`Create workpad (early acknowledgement)` in `devflow-implement.yml`) deterministically refreshes the workpad's `**Run:**` link to the *current* run before handing off. When it finds a workpad already exists (`workpad.py id` succeeds), instead of only skipping the duplicate create it first runs `workpad.py update <n> --run-link "[View run](<this run's URL>)"`, so an operator watching a stalled/retried run can click through the workpad to the currently-active job's logs rather than the original run's. This write lands at the workflow (gate) level, independent of whether the subsequent `claude` job goes on to execute Phase 1.3 — so the `Run:` link stays current even on a resume that stalls again before Phase 1.3's own workpad-resume runs. It is best-effort (mirroring the create-failure path): a failed refresh emits a `::warning::` breadcrumb noting the `claude` job will refresh it in Phase 1.3 instead, then exits 0, so a workpad-update hiccup never fails the gate job or blocks the run. (The Phase 3.1 draft-PR body carries the same `[View run]` link for the run that created the PR, omitted entirely on a local-tier run where there is no Actions run URL.)

**Prevention layer (issue #415).** The backstop above is the deterministic *convergence* net; a coordinated *prevention* layer reduces how often the early-quit fires in the first place (mirroring the review tier's #408/#410 fix). **(1) Headless-wait discipline (prose).** The injected engine-ground-truth block (`scripts/render-grounding-block.sh` in `MODE=implement`, prepended by `scripts/compose-implement-prompt.sh`) tells the orchestrator this is a headless (`claude -p`) run where **ending the turn ends the process** with no re-invocation: never end the turn while any dispatched Agent-tool subagent has not returned (the Phase-1.4 `prflow:branch-setup` and Phase-1.6 `prflow:issue-claim-auditor` agents, a Phase-2 `code-explorer`/`code-architect`, Phase-3's inline `review-and-fix` agents, the Phase-3.4 `prflow:ac-claim-verifier`/`prflow:ac-evidence-verifier` pair, the Phase-4.1 `prflow:docs` subagent, the Phase-4.2 `prflow:pr-description` subagent — each dispatched `run_in_background: false`, so a launch acknowledgment is never its return), poll to keep the turn alive, and treat `ScheduleWakeup`/future task-notifications as unavailable. It began as an always-resident cross-phase rule in `skills/implement/SKILL.md`, cloud-conditioned on `GITHUB_ACTIONS` beside the *Non-interactive self-answer rule*; delivering it in the prompt instead removes the dependency on that section surviving nested-skill body eviction, and the block's implement-mode clause names the Phase-3 inline review pass among the dispatch points it binds. A one-line mirror rides inside the stall-backstop resume comment (`devflow-implement.yml`) as a second `Headless note:` line beside the #405 `Resume note:` — coupled with the skill rule in one commit and pinned in `lib/test/run.sh` — so a resumed run receives it even if it never re-reads the skill prose. It stays cloud-scoped structurally rather than by a condition in the prose: only a cloud tier injects the block, so a local/interactive run receives none of it and `ScheduleWakeup`/task-notifications work normally. **(2) Probe-verified `ScheduleWakeup` denial.** `.github/workflows/matcher-probe.yml`'s `schedulewakeup-probe` job runs a `claude-code-action` session with `--disallowedTools ScheduleWakeup` (the tool also granted in `--allowed-tools`, so the flag under test is the only possible removal cause), has the model attempt one `ScheduleWakeup` call bracketed by two positive controls, and derives a deterministic DENIED/AVAILABLE/REMOVED/INCONCLUSIVE verdict from the execution file (never the model's text). The verdict gates whether `devflow-implement.yml`'s `claude` step ships `--disallowedTools ScheduleWakeup`: a removed/denied verdict ships the flag plus a `lib/test/run.sh` pin, a still-available verdict ships no flag and records the omission rationale on the PR — the same probe-before-grant discipline the matcher-probe corpus already uses. **Executed (issue #418):** the probe measured **AVAILABLE** across real cloud runs 29140791165 and 29138117625 (both recorded a `ScheduleWakeup` `tool_use` that was not denied; a third run, 29139012320, hit the documented compliant-model false-positive — presumptive REMOVED with both controls run — and the two positive observations are dispositive over it), so per the tool-still-available arm no flag or `--disallowedTools`-flag `lib/test/run.sh` pin shipped, and at that point the early-quit prevention rested on the headless-wait prose alone. **(3) Harness floor (issue #801).** The prose layer prohibits *ending the turn* with an agent pending, but never reaches the decision that creates a pending agent: subagents are background-by-default upstream and a background dispatch's results arrive on a **later turn**, which a headless `claude -p` run never reaches. So `devflow-implement.yml`'s `claude` step (and the two sibling engine workflows) now sets `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS: "1"`, documented upstream as keeping subagents in the foreground — binding the Phase-1.4/1.6 `prflow:branch-setup` and `prflow:issue-claim-auditor` dispatches, the Phase-2 `code-explorer`/`code-architect` dispatches, the Phase-3 inline review pass, the Phase-3.4 `prflow:ac-claim-verifier`/`prflow:ac-evidence-verifier` pair, and the Phase-4.1 `prflow:docs` subagent. It ships unconditionally rather than probe-gated because it is **inert when ignored**; whether it takes effect inside `claude-code-action` is now **observed** (issue #812) — `matcher-probe.yml`'s `background-tasks-probe` job measured **FOREGROUND** across real cloud runs 30210679122 and 30211584731, i.e. a dispatched subagent's completed result WAS in hand within the same turn, so the floor is effective on this action version. Beside it, the injected block states the requirement behaviorally — every dispatched result is collected before the orchestrator proceeds past the dispatch point and before the turn ends, more than one dispatch may be outstanding at a time provided all are collected within the turn, and a launch acknowledgment is never the return, with the per-dispatch `run_in_background: false` lever named as the one to reach for — and each implement dispatch site in the closed list the suite pins carries a one-clause pointer to that statement rather than a copy. Each measured verdict is version-dependent — re-probe layer (2)'s via the `schedulewakeup-probe` job, and layer (3)'s via the `background-tasks-probe` job, after a `claude-code-action` upgrade before trusting it.

**Implement-tier matcher probe (issues #450, #455, #571, and #1514).** The sibling `implement-probe` job applies execution-file measurement to the read-write `devflow-implement` profile. Rows 19–20 measure exact production-shaped `gh issue view` statements with distinct target forms; their evidence is not a general permission for a command head, redirect, or target class.

| Row | Command shape | Observed verdict |
|---:|---|---|
| 1 | Unexpanded `${CLAUDE_SKILL_DIR:-…}` anchor leading token | DENIED |
| 2 | Vendored-literal `apply-labels.sh` leading token | PERMITTED |
| 3 | Vendored-literal `ensure-label.sh` leading token | PERMITTED |
| 4 | `for …; do helper; done` | DENIED |
| 5 | Piped `while read` loop | DENIED |
| 6 | `VAR="$(label-helper …)"` capture with `2>&1` | DENIED |
| 7 | Plain granted command (positive control) | PERMITTED |
| 8 | `VAR=$(non-label-helper …)` capture | PERMITTED |
| 9 | Redirect-free `VAR="$(label-helper …)"` capture | DENIED |
| 10 | Granted head with `> /tmp/f` | DENIED |
| 11 | Granted head with `> .prflow/tmp/f` | PERMITTED |
| 12 | Plain heredoc write through a granted head | PERMITTED |
| 13 | Captured `VAR="$(cat <<'EOF' …)"` heredoc | PERMITTED |
| 14 | `echo "$VAR"` simple expansion after a granted head | DENIED |
| 15 | Literal leading `VAR=value` assignment | DENIED |
| 16 | Computed leading `VAR="$(head)"` assignment | DENIED |
| 17 | Executable `.py` invoked as a direct leading token | PERMITTED |
| 18 | Unexpanded skill-dir anchor leading token (`load-prompt-extension.sh`) | DENIED |
| 19 | Exact repo-relative `gh issue view 1514 … > .prflow/tmp/issue-body/iprobe19-gh-relative.md` | PERMITTED |
| 20 | Exact absolute-target `gh issue view 1514 … > $GITHUB_WORKSPACE/.prflow/tmp/issue-body/iprobe20-gh-absolute.md` | DENIED |

Rows 1–16 are recorded by [run 29623046995](https://github.com/The01Geek/prflow/actions/runs/29623046995), job `88021801138`, at head `f2162d7683bc7a352fce4efce3f092e864aab8b9`. Rows 17–20 are recorded by [run 31733588260](https://github.com/The01Geek/prflow/actions/runs/31733588260), `implement-probe` job `94559726777`, at head `8eafa06e605b0f043a1e014acb35fb27e63cc008`. Every row recorded `tool_use=yes`; row 7 recorded `shape=n/a`, every discriminated row recorded `shape=ok`, and none was REFORMULATED or UNATTEMPTED. The split row-19/20 verdict is why production cache authoring stays on the Write-tool path.

The decision itself is a pure, unit-tested helper (`scripts/stall-backstop-decide.sh`) so `lib/test/run.sh` drives every branch; the audit/fail comments go through the best-effort repo-scoped REST helper `scripts/post-issue-comment.sh` (the `ensure-label.sh`/`apply-labels.sh` always-exit-0 + stderr-breadcrumb contract), so a comment hiccup never flips a *fail* decision green; on the resume arm — where the comment *is* the action — a dropped re-dispatch comment fails the job loud (a never-posted resume must not read as green). The thin workflow-caller step (`Stall backstop`, `if: always()` after the observability-persist backstop in `devflow-implement.yml`'s `claude` job) wires these together: it reads the two config keys via the vendored `config-get.sh`, reads the workpad `Status` via `workpad.py status`, counts prior auto-resume attempts by grepping the issue's comments for the `<!-- prflow:stall-backstop-audit -->` marker each resume comment carries (the count input is CR-stripped, and a failed comment read makes the attempt count unknowable, so it fails the job loud rather than resuming unbounded past an unenforceable cap), feeds all four inputs to `stall-backstop-decide.sh`, and acts on the token. Only the resume comment carries the `/prflow:implement <n>` trigger phrase; the fail-loud comments deliberately do not (so a failed run never self-retriggers). Three boundaries govern the auto-resume in practice: a `/prflow:implement` comment authored by the built-in `GITHUB_TOKEN` does **not** re-trigger the workflow (GitHub suppresses recursive `GITHUB_TOKEN` events), so when no `DEVFLOW_APP_ID` App token is configured the step posts the resume comment and then **fails the job loud** (auto-resume is inert under `GITHUB_TOKEN`, and an inert resume must not read as green — a human re-posts the trigger, or configures the App); that App's bot login must be present in `prflow.allowed_bots` or the gate's actor authorization declines the resume comment; and the new run's `gate` dedupe must not classify the resume as a duplicate of the still-finishing original — which it no longer does: `dedupe-implement-run.sh` reads the triggering comment body from `GITHUB_EVENT_PATH` and, when it carries the `<!-- prflow:stall-backstop-audit -->` marker every resume comment writes, skips deduping so the taking-over run proceeds instead of being swallowed (issue #280, resolving the deferred #268 finding; the detection lives in the script — reading the event payload rather than a workflow-passed env — precisely so the fix needs no `.github/workflows/` change). The fail-loud + audit-comment behavior is correct regardless of all three.

## Workpad ticking: failure-isolation contract and index-based ticking

`workpad.py update` PATCHes the workpad once per call, and it distinguishes two failure classes so a batch of mutations is not lost to a single bad checkbox tick:

- **Structural failures abort the whole call before any PATCH** (exit 1, clear stderr): `gh` cannot resolve the repo, the API call fails, a target section (`## Progress`/`## Plan`/`## Acceptance Criteria`) is absent, the `Last updated` line is missing (or the `Status` line when `--status` is supplied), a `--rewrite-ac` substring matches zero or multiple rows, a `--rewrite-ac` pair appends the `(post-merge)` tag (NEW ends with it; neither OLD nor the row it targets already does) without a non-empty `--note` rationale (issue #338 — so every mid-run `(post-merge)` retag is a recorded, auditable claim; a text tweak on an already-`(post-merge)` row creates no new deferral and needs no note), or a `--replace-*-file`/`--set-reproduction-file` is unreadable. A `--status Complete` write with any non-post-merge `## Acceptance Criteria` row still `- [ ]` is also a structural abort — the terminal self-record gate (see Phase 4.3 above) — so a run can never record itself Complete over an unmet AC. A structural failure persists nothing — all-or-nothing, as it always was.
- **Volatile per-row tick misses are isolated, not aborted.** A `--tick-*`/`--tick-*-n` flag that does not resolve to exactly one tickable row *inside a present section* — a substring matching zero or multiple unticked rows, or a `-n` index that is out of range or lands on an already-ticked row — does **not** discard the call. Every other mutation (`--status`, `--note`, `--reflection`, and every tick that *did* resolve) is applied and PATCHed, and the call then **exits non-zero** with a stderr report naming each tick that did not land. So one bad tick in a batch no longer silently loses the accompanying status/notes.

A single `_report_failed_ticks` chokepoint in `scripts/workpad.py` writes the collected misses on all three exit paths — the structural-abort path, the `gh`-PATCH-failure path, and the clean-PATCH-but-ticks-missed path — so a miss is never silently dropped, and the stderr preamble states whether a PATCH was persisted so the caller can distinguish "nothing landed, re-send the whole call" from "the body PATCHed, re-tick only the named row(s)."

**Callers read the terminal outcome line, not the printed body — and not the shape of the prose above it (issue #1562).** Any `update` that reaches its own exit path closes with one machine-readable stderr line as its last:

```
workpad.py update: outcome=<token> remedy=<token>
```

`outcome=` comes from a closed set of seven tokens and `remedy=` from a closed set of six, paired by a fixed table in `scripts/workpad.py` so a call site cannot mismatch them:

| `outcome=` | Meaning | `remedy=` |
|---|---|---|
| `landed` | PATCH applied; every requested mutation landed | `none` |
| `replay` | pure no-op, no PATCH needed — a keyed checkpoint replay, or a call whose only operands are exact `_REVIEW_PROGRESS_ROWS` tick substrings whose rows already read `[x]` | `none` |
| `landed-partial-ticks` | PATCH applied; one or more tick rows unresolved | `retick-named-rows` |
| `landed-status-unverified` | PATCH applied; the `--status` read-back was empty, carried no Status line, or disagreed | `reset-status` |
| `landed-partial-ticks-status-unverified` | both of the above | `retick-and-reset-status` |
| `not-persisted` | no PATCH was made, or the PATCH itself failed | `reissue-call` |
| `precondition-mismatch` | an `--expect-comment-id`/`--expect-status` guard refused before any mutation | `re-resolve-state` |

Two properties make the line safe to act on blindly. **`reissue-call` is paired only with `not-persisted`**, whose paths persist nothing, so no remedy ever re-sends a call whose PATCH already landed and double-writes the append-only notes; `reset-status` and `retick-and-reset-status` each direct a *follow-up* call carrying only the corrective mutation. And an outcome the emitting path does not itself select is resolved from an observed "the PATCH returned" flag rather than from the exit code — the emission is routed through a `cmd_update` wrapper around `_cmd_update_inner` that catches `SystemExit` and `BaseException` alike — so a crash in the tail after a landed PATCH reports `landed-status-unverified`, never `not-persisted`. **An absent line means the write did not land**: a crash or a harness refusal emits nothing, and the caller treats that as unverified and re-resolves the live workpad.

Exit codes are unchanged by this line (clean and replay 0; structural, absent, PATCH-failure and volatile-miss 1; both precondition guards 4), and so is every pre-existing prose line, which is still written *before* it. `skills/implement/SKILL.md` carries the caller-facing form of the table above, and the Phase 1, Phase 3.4 and Phase 4.3 tick sites route on the `remedy=` token rather than on exit codes or stderr prose shapes. The stdout-silence section below describes the stderr success breadcrumb that preceded this line; it is still written, but as human-readable detail rather than as the signal a caller routes on.

**`update` writes nothing to stdout by default (issue #814).** The whole-body echo cost every caller the entire workpad comment per call — thousands of tokens per phase boundary in a `/prflow:implement` run — and no production caller consumed it — the four `lib/test/run.sh` harnesses that did now pass `--print-body`, and an out-of-tree consumer's own scripts cannot be enumerated from this repository — so the exit code became the documented success signal for a clean mutation, not only for ticks. Two things preserve what the echo was actually load-bearing for. First, a one-line stderr **success breadcrumb** is written on exactly the paths that PATCH and return exit 0, naming the PATCHed comment id and — on a `--status` call — the `Status:` value read back from the PATCH response (rendered `(empty response)` or `(not found)` when the response carries no readable Status, and followed by an explicit `WARNING` line when the read-back does not match the requested status). Without it a successful call would be byte-identical to one the cloud permission matcher silently refused, and the read-back is the landed-`Status` check an exit code cannot discharge by construction. The **success breadcrumb** is **not** written on the volatile-miss path, where a success-shaped line beside a failing exit code would re-create the split the exit-code rule prevents; the mismatch `WARNING` is a separate, failure-shaped line that **is** still written there whenever the read-back disagrees with the requested status. Second, the **volatile-miss path still echoes the body**, because the failure-isolation contract requires re-resolving a section-scoped checkbox index before re-ticking and the body is the row inventory that resolution reads — and on that one path the echoed `**Status:**` line is also where the landed-`Status` read-back comes from, since the breadcrumb is withheld there. `--print-body` restores the old bytes wherever `update` used to write them — only the volatile-miss path echoes without it, and every other path either echoes solely under the flag or exits before reaching a write; the Phase 3.4 gate instead reads whole-section state through `workpad.py acs-gate` (the degrading read, issue #1214), which on a clean read re-renders the `## Acceptance Criteria` section from its parsed rows — tick state and `(post-merge)` tags preserved, not a byte copy — and on a workpad read failure routes to a distinct non-passing label rather than wedging.

**The orchestrator no longer restates the helper's CLI surface (issue #1531).** `skills/implement/SKILL.md`'s `### Workpad helper CLI` section used to carry a subcommand table and a `workpad.py update` flag table, both resident in every phase of every implement run and both able to drift behind the helper. It now carries one sentence pointing the run at `workpad.py --help` and `workpad.py update --help`, invoked vendored-literal-first with a repo-relative fallback, plus an instruction not to improvise flags when neither form prints help. So the authoritative statements of the subcommand and flag surface are the helper's own `--help` output and this page; the run policy the orchestrator still states in its own body is unchanged, including the failure-isolation contract, the Status read-back walk, the reflection-kind routing rule, the interpolation-safe `--reflection-file` recipe, and the one-workpad-per-issue rule.

**Ticking is addressable by substring or by index.** Besides the substring flags (`--tick-progress`/`--tick-plan`/`--tick-ac`), Plan and Acceptance Criteria accept a **1-based index** form (`--tick-plan-n`/`--tick-ac-n`) that counts every `[ ]` and `[x]` row within that section in document order (the index is section-scoped, not whole-document; Progress has no index form). The Phase 3.4 AC gate ticks confirmed criteria by index — repeatable and combinable in one call — so it no longer depends on hand-picking a unique prose substring per AC.

## `## Devflow Reflection`: grouped-by-kind rendering (`--reflection-kind`)

**Disposition after the shared writing standard (issue #1039).** This section, and its `--reflection-kind` restatement in `docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md`, are **retained unchanged**. They document the reflection-*kind* routing — which sub-section a bullet renders under, a workpad-mechanics contract the `#126` pin requires `--reflection-kind` to appear in both files for — not the prose-*style* rules the shared writing standard (`lib/writing-standard.md`) absorbed from the implement Reflection style contract. The kind routing is unaffected by that absorption, so nothing here points at the standard.

**Where the standard lives (issue #1039).** The standard sits in `lib/`, not `docs/`, because roughly nineteen skill surfaces read it while they execute — it is a shipped runtime asset that happens to be prose, and `lib/` is where this repository keeps shipped assets a skill reads (`lib/intervention-surfaces.md` is the existing precedent). Do not move it back under `docs/` as a tidy-up.

**Pointer form (issue #1039).** A pointer to `lib/writing-standard.md` from a skill body, a phase file, or a reference file under a skill directory resolves the standard through the portable skill-directory anchor (`"${CLAUDE_SKILL_DIR:-…}"/../../lib/writing-standard.md`), because a bare repo-relative path does not exist in a consumer checkout where the skill is vendored. A pointer from a documentation page (such as this file) or from `CLAUDE.md`, where no skill-directory anchor resolves, uses the bare repo-relative path `lib/writing-standard.md` instead — the form those non-skill sites take.

Reflection bullets are grouped by **kind** so a human triaging a PRFlow PR/issue sees the items that need follow-up separated from improvement proposals and purely informational notes, without expanding and reading a flat list. `scripts/workpad.py update` takes a `--reflection-kind {blocked|deferred|dropped-failed|improvement|issue-accuracy|note}` flag that applies to that call's `--reflection` / `--reflection-file` bullet(s); the helper — the single chokepoint every reflection flows through — owns the glyph, bold label (or none, for the glyph-only kinds), and sub-section placement, so the structure holds regardless of how the orchestrator phrases the text.

| Kind | Rendered bullet | Label? | Sub-section |
|---|---|---|---|
| `blocked` | `- ⛔ **Blocked:** …` | labeled | `### ⚠️ Action required` |
| `deferred` | `- ⏭️ **Deferred:** …` | labeled | `### ⚠️ Action required` |
| `dropped-failed` | `- ❗ **Dropped/Failed:** …` | labeled | `### ⚠️ Action required` |
| `improvement` | `- 💡 …` | glyph-only | `### 💡 Improvements` |
| `issue-accuracy` | `- 📝 **Issue accuracy:** …` | labeled | `### ℹ️ Notes` |
| `note` (default when omitted) | `- ℹ️ …` | glyph-only | `### ℹ️ Notes` |

The three sub-sections render in the canonical order `### ⚠️ Action required` → `### 💡 Improvements` → `### ℹ️ Notes`, all inside the existing `## Devflow Reflection` `<details>` block. A kind whose sub-heading already names it renders **glyph-only** (`note` under `### ℹ️ Notes`, `improvement` under `### 💡 Improvements`) — the redundant bold label is dropped (issue #476); the others keep a label because their heading does not uniquely name them (the three actionable kinds share `### ⚠️ Action required`; `issue-accuracy` renders under `### ℹ️ Notes`). Mechanics, baked into the helper:

- A sub-heading is emitted **only** when its group has ≥1 bullet (an empty group produces no heading); a second bullet of an existing kind nests under the existing heading without duplicating it; appended content stays before `</details>`.
- Sub-headings are `### ` (level-3), **never** `## ` — `lib/fetch-pr-context.sh` terminates the reflection parse at the first `## ` heading, so a level-2 sub-heading would truncate `reflections[]`. The parser captures every kind bullet (glyph, and bold-label prefix when present — a glyph-only bullet is captured identically; useful signal for the retrospective LLM, irrelevant to `cheap-gate.jq`'s friction check) and excludes the `### ` headings, for the grouped shape and a legacy flat block alike. Beyond capturing the bullets, the parser now splits them by **friction**: it emits a top-level `reflections_friction_count` counting every bullet EXCEPT an informational `note` (`ℹ️` under `### ℹ️ Notes`), and `cheap-gate.jq` forces LLM analysis only when that count is > 0 — a run whose reflections are all `note`-kind is treated as clean (an exempted note is still recorded verbatim into the clean entry by `lib/clean-entry.jq`). The gate fails closed if the field is absent (falls back to the legacy "any reflection trips" count), and a present-but-unparseable block is substituted with a friction sentinel, so a missing or broken signal over-analyzes rather than skipping a friction PR.
- `--reflection-kind` defaults to `note`, so un-kinded call-sites degrade to the Notes sub-section — never to Action required. A single kind applies to every bullet in the call, so the orchestrator emits different kinds in separate `update` calls (this is why the Phase 4.3 `publish_failed` `dropped-failed` reflection is its own call, separate from the `note`-kind finalize). This mirrors `workpad.py`'s existing helper-owns-the-rendering-token idiom (`--status` derives and prepends the status glyph; `--note` nests under the right `## Progress` phase).
- **The Phase 1.6 issue-claim audit records clean confirmations as `## Progress` `--note`s, not reflections** — an assumption checked that held carries no friction signal, and a reflection trips the retrospective cheap gate. Only audit *findings* reflect: a wrong count/exclusion as `issue-accuracy`, punted workflow-capability work as `deferred`, a policy/dependency contradiction as `blocked`.
- **Interpolation-safe input.** `--reflection-file PATH` reads the bullet text verbatim as UTF-8 from a file (or stdin when `PATH` is `-`), bypassing shell interpolation — the recipe for reflection text containing backticks, `$`, or double quotes. The call-site recipe (in `skills/implement/SKILL.md`) authors the payload to a `.prflow/tmp/` file with the Write tool, passes `--reflection-file <path>` alongside the `--reflection-kind`, then deletes the payload after the helper call succeeds; an unreadable, undecodable, or empty payload aborts the call before any PATCH.

## Phase 4.0.5 deferral-manifest discovery (`scripts/discover-deferral-manifests.py`)

Before Phase 4.0.5 can merge or file anything it has to *find* the run-scoped `deferrals.json` manifests under the candidate roots (the PR-slug scratch dir, plus the branch-slug dir when it differs). That search used to be one multi-root `find $SEARCH_DIRS … | sort` whose exit status was masked by the pipe and then discarded by the capture — so a search that **failed** (an unreadable root, a mid-traversal `OSError`) and a search that genuinely **matched nothing** produced the same empty string. The failure therefore read as the clean no-op: nothing filed, nothing recorded, and acknowledged deferred review findings silently stranded (observed live on issue #533).

Discovery is now delegated to the stdlib-only `scripts/discover-deferral-manifests.py`, which makes the outcome observable:

- **Per-root, independent.** Each candidate root is searched on its own and classified `ok` (searched cleanly; zero or more matches), `absent` (root does not exist) or `failed` (traversal error — the walk passes a *raising* `onerror` rather than relying on `os.walk`'s silent skip, so a mid-traversal error cannot be swallowed). One bad root no longer contaminates or hides the others.
- **Status in the exit code.** `0` = every root ok/absent (clean), `3` = partial (at least one root failed, at least one did not fail — `ok` or `absent`), `4` = every root failed, `2` = called with zero arguments. Output production and sorting cannot alter the status. The two degraded outcomes also emit fixed stderr markers (`devflow: discovery partial:` / the failure marker) so the fence can discriminate them with the same single-statement `if`/`elif` stderr-marker idiom it already uses for `file-deferrals.py`.
- **Roots echo on every discovery run.** A `devflow: discovery roots:` line naming each root and its classification goes to stderr and is surfaced into the tool result on *every* path, including the clean one — so an `absent`-classified root is visible rather than silent. That echo is also the input to the documented **cwd-drift** heuristic: if the fix loop reported emitting a manifest but every root classifies `absent`, the run is suspect (compare the echoed absolute paths against where Phase 3.3 executed) rather than a clean no-op.
- **Deduplicated, sorted, POSIX-form** manifest paths on stdout.

The phase consumes that status fail-closed. `DISCOVERY_STATE` is initialized **empty** before the statement and no arm sets a non-empty default, so a harness refusal of the capture (the non-label capture shape is unproven on the implement tier — *no output at all* is a possible denial, never an empty value) leaves it empty; the unconditional sentinel gained a `discovery=` field, and the filing guard requires `ok` or `partial`. Consequently: `discovery=[]` (refused or never ran) and `discovery=[failed]` file nothing and record a `dropped-failed` reflection; `discovery=[partial]` files from the clean roots only and records the failed root plus the honest limitation that, once this run hydrates the aggregate, the failed root's deferrals can no longer be auto-filed by a later re-run (`file-deferrals.py` refuses a mixed hydrated/raw manifest all-or-nothing) and must be filed manually from that root's run-scoped manifest; and only `discovery=[ok]` with `manifest=[]` is the clean no-op.

On the cloud implement tier the helper is subject to the same **two-halves upgrade** as the label helpers: `devflow-implement.yml` must grant `Bash(.prflow/vendor/prflow/scripts/discover-deferral-manifests.py:*)` (arrives by re-running `install.sh`; authored through the generated capability manifest, never by hand-editing the workflow literal) *and* the §4.0.5 fence must invoke it (arrives by bumping `prflow_version`). Unlike the label class, a skew here fails **loudly** — the discovery statement is refused, produces no output, and the reader takes the fail-closed `discovery=[]` exit. That grant is a **prefix** grant, so it already covers the presence mode below; a consumer holding only the skill half reaches the presence mode's fail-closed unestablished arm, which reads the reference, rather than losing anything silently.

### The presence mode, and the gate it drives (issue #1374)

Everything above — the fence, its arms, the sentinel, the reader routing — now lives in `skills/implement/references/deferred-review-findings.md`, which the phase file reads only when a predicate says a deferred review finding is present. The predicate is a second mode on the same helper, selected by `--presence-for-pr N` as the **leading argument**; every element of `argv` is otherwise still a candidate root, so the filing fence's unquoted word-split `$SEARCH_DIRS` invocation classifies exactly the roots it always did and returns the same exit code.

Presence mode answers over **both** presence sources — the run-scoped manifests it discovers and the slug-level aggregate at `pr-<N>/deferrals.json` — because reading either alone fails open: a first Phase 4 entry has no aggregate, and a re-entry after filing has no unconsumed run-scoped manifests. It reports **present as exit `0`**, **absent as `1`** and **unestablished as `2`**; the exit status carries each state, and the stub's skip arm additionally requires the literal `absent: 0` line, because a crashing interpreter also exits `1`. A malformed invocation reports `2`, mirroring `scripts/workpad.py deferred-presence`, so a bad call loads the reference rather than skipping it. Discovery mode's `3`/`4` split is deliberately unreachable here: any unreadable candidate or aggregate collapses onto `2`, an accepted loss taken so both gated Phase 4 sub-steps document one three-state contract.

It derives the branch-slug search directory in Python rather than through the fence's `tr` chain, so a host without `tr` resolves the same search directories — closing the dependence for the *gate*, not for the fence, which keeps its own breadcrumb and `pr-<N>`-only fallback.

## Phase 4.0 / 4.0.5 deferred-issue labels (`deferred.labels`)

Phase 4.0's filing procedure is **predicate-gated** (issue #815): it lives in `skills/implement/references/deferred-ac-followups.md` and the phase file reads it only when `scripts/workpad.py deferred-presence <issue> <pr>` reports an outstanding or an unestablished answer, so a run that deferred nothing never loads it. When a run scopes itself down, it files follow-up issues for the work it deferred: Phase 4.0 files an issue per **logical chunk** of deferred work — typically one per remaining phase of a phased cleanup, carrying the deferred criteria verbatim from the 2.2.5 scope decision — and Phase 4.0.5 files an issue per **source file** the deferred review findings touch (`scripts/file-deferrals.py` groups the Step-3 deferrals manifest that way). The labels applied to those follow-up issues are configurable via **`deferred.labels`** — a comma-separated string under the top-level `deferred` object (default `PRFlow,Deferred`), read by both phases with `config-get.sh .deferred.labels PRFlow,Deferred`.

Both phases resolve and apply the labels with the **same idiom Phase 4.1 uses for `docs.labels`**, so there is one normalization rule to learn:

- **Normalize** the raw value by splitting on `,`, trimming whitespace from each entry, and dropping empties. `"PRFlow, Deferred"` applies both labels; a whitespace-only or all-separators value (e.g. `" , "`) normalizes to *none* and applies no labels. (A literal empty string resolves to the `PRFlow,Deferred` default rather than meaning no-labels, matching how config defaults resolve.)
- **Ensure-then-apply, best-effort, post-creation.** The issue is created with **no** `--label` on `gh issue create`; the normalized labels are then ensured to exist via `ensure-label.sh` (which always exits 0) and applied through the shared REST `apply-labels.sh` helper (`POST .../issues/{n}/labels`, repo-scope only — not `gh issue edit --add-label`'s org-scoped GraphQL path) per filed issue. Like every PRFlow `gh api` **path argument** on a surface that can run outside Actions — the skill's own fences included — that endpoint addresses the repository through the `{owner}`/`{repo}` placeholders `gh` resolves from the git remote, not through `$GITHUB_REPOSITORY`, which exists only on the cloud tier; `lib/test/lint-gh-api-repo-path.py` turns a reintroduced interpolation RED at the desk (issue #664). The rule governs the path argument only: a repo string reached through a flag value or an assignment hop (`scripts/react-to-trigger.sh`'s `--repo`, which fails closed with a warning and no POST when empty) is an accepted residual outside that guard's reach. A label hiccup is logged to stderr and a `Devflow Reflection` note, never allowed to block or unwind the filing — mirroring the post-creation label-apply idiom Phase 3.1 uses for the hardcoded `PRFlow` provenance label.
- **Emitted as agent-level single-leading-token calls, never a shell loop or a capture (issue #455).** On the read-write cloud tier the matcher **denies** a `for`/`while` loop or a `VAR="$(…)"` capture that wraps a label helper (probe rows I4/I5/I6), and a denied command fails *silently* — it prints nothing. So the phases resolve the label list once, **print** it (a shell variable does not survive into a later separate command on the cloud runner), and then the orchestrator iterates *itself*, emitting one `ensure-label.sh <label>` and one `apply-labels.sh <number> "<labels>"` call per item with the vendored helper path as the command's leading token. The same rework applies to Phase 3.1's `PRFlow` provenance apply and Phase 4.1's `docs.labels` apply — all four label channels. `lib/test/extract-command-shapes.py --profile implement` turns a re-introduced loop/capture shape RED at the desk.
- **Every label channel fails CLOSED.** Each channel reads the helper's printed output and routes on it: `apply-labels.sh` breadcrumbs on **every path it can take** (`devflow: applied label(s) …` on success, `devflow: warning: could not apply …` on an API failure, and its own arg-slip warning on a non-numeric/missing number or an empty label list), and `ensure-label.sh` always breadcrumbs (`created` / `already exists` / `warning: …`), so **no output at all** — the single silent outcome either helper has — means the command was refused by the harness. That is recorded as a `dropped-failed` reflection, never read as "no labels configured". The phases likewise print the **raw** config value alongside the normalized list, so a normalizer emptied by a missing/denied `tr|sed|grep` is distinguishable from a genuinely empty `deferred.labels`. Both arg-slip breadcrumbs explicitly say *not a harness denial* — the shapes a dropped shell variable or an empty label literal produce — so a caller routes them to a re-emit with the printed literals rather than mis-attributing them to the API or to a refusal, and the four outcomes the phases route on stay distinguishable.

The reason it lives in the **skill**, not in `file-deferrals.py`, is the standing config rule: config is read through the single resolver (`config-get.sh`), never re-parsed ad hoc inside a helper — so the resolve/normalize/ensure/apply steps stay in the skill body and the deferral helper stays config-agnostic. A **hard** `config-get.sh` read failure (corrupt `config.json`, missing python3) is distinguished from an empty result: its non-zero rc is captured and recorded in a reflection, and the run continues filing the issues *without* labels rather than aborting.

This key controls **only** deferred-issue labeling. It is independent of the hardcoded `PRFlow` provenance label (and its superseded `DevFlow` spelling) that retrospective detection matches literally (`lib/scan.sh`, `lib/classify-pr-kind.jq`) — that string is a constant no config key controls — and separate from the `docs.labels` docs-pass label.

## Phase 4.1 Documentation Needed enforcement: two-stage gate

Phase 4.1 (*Update Documentation*) dispatches a `prflow:docs` subagent. When the issue body names
specific files in its `**Documentation Needed**` bullet (a sub-bullet of `## Implementation Notes`
in the issue template), Phase 4.1 enforces delivery through a two-stage gate.

**The bullet is a floor, not a ceiling.** The `Documentation Needed` bullet is an *additive* floor of
mandatory deliverables — it can only *add* required files. A narrative claim that documentation is
unnecessary — including an absent, empty, contradictory, or standalone-`none`-declared (issue #1663)
`Documentation Needed` bullet — never
suppresses the routine doc pass: the `prflow:docs` subagent still runs and updates documentation
warranted by the shipped behavior change, and the bullet is never read as a ceiling that authorizes
skipping otherwise-warranted documentation. The standalone-`none` declaration (below) changes only what
the extractor treats as a *named deliverable* — it removes the block's floor of mandatory files; it does
not, and cannot, suppress the routine doc pass, exactly like the absent/empty/contradictory states. This mirrors the Phase 2.1 authority hierarchy (the issue
narrative is a non-authoritative starting point; only Desired Behavior and Acceptance Criteria are the
decided spec). The two-stage gate described below is unchanged by this framing — it enforces the floor
of named deliverables; it does not decide whether the doc pass runs.

Path extraction is **deterministic, not LLM-interpreted** (issue #185 Addendum): a bundled helper,
`scripts/extract-doc-needed-paths.sh`, is the single extraction boundary, reached by both stages through
the read helper described below (issue #1554). It reads
the issue body, scopes strictly to the Documentation Needed block under `## Implementation
Notes` — recognized in **any** of the three scope-opening shapes real bodies use: the template's
canonical `- **Documentation Needed** — …` list item (issue #185), a bare, blank-line-preceded
`**Documentation Needed** — …` bold paragraph with no `- ` marker (the form an LLM-drafted `##
Implementation Notes` section commonly renders, which the older `- `-required anchor matched nothing of,
silently skipping the gate; issue #309, a sibling of the #289 miss class), **or** a `### Documentation
Needed` level-3 heading (issue #380 — the form a body that renders its deliverables under a subheading
uses, the real issue #363 body, which matched nothing under the two bold openers and silently skipped the
gate). The heading opener anchors to exactly level 3 inside `## Implementation Notes`, so a deeper `####
…` heading or a bullet that merely mentions the label does not open, and any other level-3+ heading closes
an open heading-form scope so later-subsection paths never leak. The template canonically emits the
bold-bullet form; the heading form is accepted so a differently-rendered body still gates. A bold-emphasis span that only begins a wrapped continuation
line inside the bullet does not close the scope, so paths on later wrapped lines are still captured.
Two adjacent grammar shapes are handled explicitly (issue #327), both in the leak-safe direction: (1) a
top-level bold **deliverable** list after the bullet stays in scope — a backtick-led bold item
(`- **`docs/a.md`**`) is a listed deliverable, not a peer section label, so it is captured instead of
silently closing the scope to empty output (a non-backticked `- **docs/a.md**`, being indistinguishable
from a peer label, still closes — an accepted, `run.sh`-pinned tradeoff, since real deliverable lists
backtick their paths); (2) a trailing blank-line-preceded **plain-prose** paragraph (not blank, not a
list item, not bold) closes the scope so its path-like tokens do not leak as deliverables — but only
**once a deliverable has already been captured** in the scope (an `emitted` gate), so a primary prose
declaration and any intervening prose before the deliverables stay in scope. A blank-separated plain
sub-list stays in scope. The `emitted` gate arms only on a structural line (list item or bold line)
bearing a token Stage B would emit, mirroring Stage B's basename+extension predicate, so plain prose can
never arm the close — keeping the fix strictly leak-safe (it never introduces a new fail-open).
It then emits the recognizable file paths one per line — a token counts as a path only if it
ends in a recognized doc/source extension **or** names an in-tree tracked regular file (the
`[ -f ] && git ls-files --error-unmatch` rescue for extensionless real files like `Makefile`/`LICENSE`).
A bare "contains `/`" test is deliberately **not** sufficient — it wrongly emitted directory tokens
(`docs/internal`) and rooted skill-invocation refs (`/claude-md-management`, from colon-splitting); rooted
(`/…`), parent-dir-escaping (`../…`), and trailing-slash directory tokens are dropped outright (issue #254). So prose, skill names
(`prflow:docs`), directories, and paths named in *other* sections or bullets are excluded by
construction (no judgement call, and none of the LLM-extraction drift that earlier incarnations of this
gate suffered). Its behavior is verified by a fixture-based input-shape matrix in `lib/test/run.sh`
(bullet-with-paths, no-paths, absent section, path-in-another-section-not-extracted, directory-token and
rooted-token rejection) rather than by the shadow review.

**Standalone `none` declaration (issue #1663).** A writer can declare that the block promises nothing by
opening it with the standalone word `none`, so the honest phrasing that explains *why* a page needs no
change no longer creates work (the friction hit on issue #1659, where `none.` followed by a backticked
already-correct file turned that file into a mandatory deliverable). The extractor examines the block's
**first content token alone**, wherever it falls (after the label on the opener line for the list-item and
bold-paragraph openers, or on a later line for a bare opener's sub-list and the level-3 heading): the
declaration is recognized when that token is exactly `none` (case-insensitive) carrying at most one
trailing terminator from the closed set `,` `.` `;` `:`, or when `none` stands alone as the block's only
content. It is a whole-token literal comparison (never a leading prefix, so no multibyte separator is
decomposed under the script's byte-wise locale), which is why an ordinary sentence opening `None of these
pages may be skipped:` runs on into prose and still extracts its paths, and `none!` / `none)` — carrying a
character outside the terminator set — are not declarations. Content after the first token, including a
backticked path, is deliberately not consulted. When the declaration is recognized the extractor emits no
paths for the block, so the read helper reports `no-deliverables` (exit 10) — the existing empty-extraction
signal, needing no new token — and Stage 1's existing safety-net note records that the cross-check was
skipped. **Stated residual:** a writer who declares `none` and then names a file that genuinely needs
editing loses that file's mandatory status; the routine doc pass still runs and updates what the change
warrants, so the case is auditable rather than silent — the accepted cost of a declared empty form.

**Span, call-group, and fence rules (issue #644).** Inside the scoped block, three constructs are
treated as scope markers rather than deliverable text, so a routine PRFlow issue that quotes a
tool-grant literal or a shell command no longer produces a phantom deliverable. (1) A **backtick span**
yields deliverables only when its whole content is a single bare-path token (`` `docs/a.md` ``), or
several whitespace-separated bare-path tokens each carrying a recognized extension or naming an in-tree
tracked file (`` `docs/a.md docs/b.md` ``, `` `docs/a.md LICENSE` ``). Any other span — one bearing a
`(`, `:`, `*`, or any non-path character (a grant `` `Bash(x.sh:*)` ``), or a bare command word like
`` `bash lib/test/run.sh` `` (`bash` is extensionless and not an in-tree file) — is a command/grant
literal: it contributes no tokens, and a **one-time stderr breadcrumb** names the first suppressed span
(disclosed by Phase 4.1 as ephemeral on the cloud tier — the gate does not capture that stderr, so a
suppressed span leaves no run-record trace there; see the phase file's cloud-tier residual note). (2) Outside
spans, a `Word(...)` **call group** (a word immediately followed by a parenthesized group, e.g. an
un-backticked `Bash(lib/test/run.sh:*)`) contributes no tokens. (3) A **fenced code block** — opened and
closed by a line whose first non-whitespace characters are three-plus backticks or three-plus tildes (the
two GitHub-flavored-markdown forms; indented four-space code blocks are a disclosed non-goal) — is inert
to the *entire* pipeline: its delimiter and interior lines drive no scope transition and contribute no
tokens, so a fenced example (a command transcript, a config snippet, a template illustration) is never a
declaration. The single fence tracker lives in Stage A and runs from the top of the body, so the block
Stage B receives is fence-free by construction; when the fence-aware pass enters no Documentation Needed
scope at all **and a fence actually disrupted parsing** — an unbalanced fence still open at end-of-body, or
the section heading itself swallowed by a straddling fence (a truncated body, a lone stray delimiter, a
fence straddling the scope boundary) — Stage A re-runs fence-blind — today's semantics — so a mis-fenced
body degrades to today's behavior instead of silently emptying. A *balanced* fenced example that opens no
real scope (a phantom scope inside an entered section) does **not** trip the fallback, so it stays empty. Two drops are **disclosed**: a command-shaped span is a breadcrumbed
under-enforcement residual (not a leak-safe property — the rule cannot always distinguish it from a
deliverable list), and an **un-backticked bare command in plain prose** (`run bash lib/test/run.sh`, no
backticks, no call-group syntax, outside any fence) still emits its path token, because it is textually
indistinguishable from a deliverable mention (the rejected wrapper-word-heuristic alternative rots and
false-positives). The Stage A `emitted` proxy (`arms()`) applies the same span/call-group rules
(extension-only, since it cannot run the filesystem in-tree rescue) so it stays in lockstep with what
Stage B emits.

### The read boundary: `scripts/read-doc-needed-deliverables.sh`

`scripts/read-doc-needed-deliverables.sh <issue-number>` owns the read both stages perform — the
`gh issue view` fetch, its scratch file, the invocation of `extract-doc-needed-paths.sh` over it, and
a retry on each. It prints an **outcome token** on a `docgate-outcome: ` line and, on success with
paths, one `docgate-path: ` line per deliverable. **That helper's own header is the canonical
statement of its token vocabulary and the exit status paired with each; read it there rather than
from a copy.** Each token has its own status, and the success statuses are disjoint from the failure
ones, so a token paired with the wrong status is detectable.

**Why the output lines are prefixed rather than positional.** The caller is an agent reading a Bash
tool result, which merges the helper's stdout with the stderr of `gh` and of the extractor — and the
extractor emits a `suppressed a span` breadcrumb on stderr for exactly the adversarial bodies this
gate exists to handle. Under a "line 1 is the token" contract that breadcrumb could present itself as
the outcome on a read that *succeeded*, routing a good read into the residual `Blocked` arm, and an
interleaved stderr line could be read as a deliverable path. The suite's fixture harness therefore
merges the two streams too, rather than isolating them into a contract the caller never gets.

Why the read is a helper at all (issue #1554): both stages previously carried the same inline shell,
byte-for-byte, capturing the paths into a `DOC_NEEDED_PATHS` shell variable. That cost three things
at once. The value never reached the run — a `VAR=$(…)` capture does not survive to the next Bash
tool call, so the dispatch briefing that names the mandatory deliverables and the per-path diff check
both read a value the run never observed. The branch logic was reachable by no test, because a fence
in agent-executed prose has no executable boundary to drive. And the governing rule was stated twice,
in two paragraphs that had never been the same text. Printing the outcome fixes the first, an
executable CLI fixes the second, and one shared contract paragraph in the phase file fixes the third.

Both failure tokens fail **closed**: the deliverable list is unknown, never empty, so §4.1 routes
them to `Blocked`. The phase file also carries a **residual arm** for every observation outside the
token-and-status contract — no output at all, no `docgate-outcome: ` line in the result, more than one
such line, an unrecognized token, a token paired with a status the contract does not pair it with, a
status outside the closed set, and any reading that the helper did
not run (`command not found`, `No such file`, `Permission denied`, rc 126, rc 127) — routing to that
same `Blocked` path, because a deliverable gate that continues on an unestablished read is not a
gate. `gh` writes HTTP error bodies to stdout, so the helper judges each attempt by its own exit
status and never by the capture being non-empty.

The helper honours two overrides verbatim with no probe: `DEVFLOW_GH` (the shared resolver's own
override) selects the `gh` binary, and `DEVFLOW_DOC_NEEDED_EXTRACTOR` selects the extractor — the
seams the suite drives its token-and-arm-ordering matrix through, including that a body read failing
both attempts reports a read failure rather than an empty extraction, and that a read recovering on
its second attempt yields a success token.

**Stage 1 — Pre-flight briefing (before dispatch).** The orchestrator invokes that helper and routes
on the token it printed. On `deliverables` the printed paths are the required deliverables and the
dispatch instruction sent to the `prflow:docs` subagent is extended with "The issue requires the
following files to be updated; treat each as a mandatory deliverable: `<path1>`, `<path2>`, …". If the
helper reports `no-deliverables` **but** the issue body still contains a Documentation Needed section **in either
accepted form** — the bold-bullet `**Documentation Needed**` form **or** a `### Documentation Needed`
heading (the safety-net grep matches both, carrying the same `\*{0,2}` bold-tolerance as the extractor's
own opener so the two heading recognizers cannot drift) — the orchestrator records an auditable workpad
note (the skipped enforcement is logged rather than silently disabled). Matching only the bold-bullet form
here would leave a heading-form issue's empty extraction silently unrecorded — the exact #363 gap. When no
paths are extractable the subagent receives the normal instruction unchanged.

**Stage 2 — Post-hoc diff gate (after the subagent commits).** After the subagent completes and before
ticking `Documentation`, the orchestrator **re-runs `read-doc-needed-deliverables.sh`** — the single
source of truth, so the two passes can never disagree about which files were named — routes its token
by the same shared read contract Stage 1 states (residual arm included), and on `deliverables` checks
each printed path against the PR's cumulative diff:

```bash
if ! DIFF_OUT=$(git diff --name-only "origin/$BASE...HEAD") \
   && { git fetch origin "$BASE" >/dev/null 2>&1; ! DIFF_OUT=$(git diff --name-only "origin/$BASE...HEAD"); }; then
  # command failure on the read AND its retry → route to Blocked, never a path-absent verdict
fi
```

Before trusting that output the orchestrator guards two fail-open inputs. It ensures `$BASE` is
non-empty by re-deriving it exactly as Phase 1.4 does — **applying Phase 1.4's non-empty fallback, not
just the config read** (the read alone returns nothing on malformed config, which would collapse the
range to `origin/...HEAD` and judge every path absent). And it reads the **exit status, never stdout
emptiness**, as the failure signal — discriminated by the single-statement `if !` guard reading git's
**own** exit status inline (never a captured `DIFF_RC` read in a later statement, which an inline-bash
runner that strips cross-statement variable reads would leave empty): a `git diff` failure (or an
unfetched `origin/$BASE`) is a command failure that says nothing about any path — the guard re-fetches
and retries, and if the re-fetch itself fails it routes to Blocked rather than falling through to a
path-absent verdict on a broken command. An rc-0 result with empty stdout, by contrast, is the
legitimate "none of these files were touched" signal (the genuine absence the gate exists to catch) and
is acted on as real.

Bare-filename paths (containing no `/`) are considered satisfied if any diff entry's basename matches
— for example, the diff entry `docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md` satisfies the named path
`DEVFLOW_SYSTEM_OVERVIEW.md`. (Because basename matching is intentionally lenient, issue authors should
use a qualified path — e.g. `docs/README.md` rather than bare `README.md` — when a specific file, not
any same-named file, is the deliverable.) Paths containing a `/` must appear as an exact match. If
the helper reported `no-deliverables`, this cross-check is a no-op and the orchestrator proceeds
directly to applying the post-docs labels and ticking `Documentation`.

**For each absent path the orchestrator either self-heals or blocks — and the two halves live in
different files (issue #1557).** The *repair* is a predicate-gated reference,
`skills/implement/references/doc-deliverable-self-heal.md`, read only on the arm where a named path
is absent and a repair is therefore owed; the *enforcement decision* — satisfied-versus-absent, and
the undeliverable-path `Blocked` terminal — stays resident in
`skills/implement/phases/phase-4-documentation.md`. That split is the point of the move rather than
an implementation detail: a failed reference load costs the run its repair, never its gate, so the
orchestrator still evaluates every named path and still refuses to tick `Documentation` for one it
cannot deliver, from resident prose alone. The load is accepted under the same boundary-marker
contract §4.0 and §4.0.5 apply to their own references.

- **Self-heal (in the gated reference):** if the correct update can be derived from the issue body's
  `**Documentation Needed**` prose, the orchestrator performs the missing update itself, records a
  workpad note (`Phase 4.1 self-heal: <path> absent from diff; performed update from Documentation
  Needed prose`), commits with a `docs:` prefix, and pushes. It then **re-verifies the self-heal
  landed and reached the remote** — re-running the per-path diff check and confirming the commit and
  push both succeeded *and* that the local branch is in sync with its upstream (`git rev-parse HEAD`
  equals `@{u}`), so a no-op edit, a failed commit, or a no-op/rejected push (which leaves a
  still-local commit) falls through to *Blocked* rather than ticking `Documentation` over a
  deliverable that never reached the PR. The reference writes no run status; it reports the per-path
  outcome back to the caller, which routes it.
- **Failed-load arm (resident, and it halts):** when the reference read fails — absent, empty,
  harness-refused, or boundary-marker mismatched — the orchestrator records a `dropped-failed`
  reflection naming the reference path and stating the repair was not attempted, then takes the
  terminal below without ticking `Documentation` or proceeding to the labels step. The arm carries a
  heading that contrasts it with the §4.0 and §4.0.5 degraded arms *by name*, because those two sit
  earlier in the same file, are structurally identical, and are each headed "degrade, never halt" — an
  orchestrator that generalized from them would continue past an absent deliverable.
- **Blocked (resident):** the terminal fires on the **absence of an explicit repaired-and-verified
  outcome** for an absent path — including a path the reference reported nothing about, since an
  absent report is not a delivered file. A repair that could not be derived, a reference that could
  not be loaded, a repair that did not land per the re-check and a procedure interrupted before it
  reported are examples of that condition, not the test; the trigger is stated positively so that an
  unclassified mid-procedure failure, which satisfies none of the named causes, still routes here. The
  orchestrator does *not* tick `Documentation`. It routes to `--status Blocked
  --reflection-kind blocked` with a reflection naming the missing path
  (`Phase 4.1: Documentation Needed file content cannot be determined for <path> — the docs subagent
  did not update this file and the correct content cannot be derived from the issue body; update
  manually and re-run Phase 4.1`) and emits the 👎 outcome reaction.

The post-docs labels (`docs.labels`, default `Documented`) are applied only after Stage 2's gate has
passed — every named deliverable satisfied, or Stage 1 found no paths — and only when the docs pass
itself succeeded. A run that routes to Blocked stops before this point, so a Blocked PR never carries
the `Documented` label that would mislead downstream docs automation. They are applied through the
same cloud-permitted idiom as the deferred labels (issue #455): the PR number and the normalized
label list are resolved and **printed**, then the orchestrator emits one leading-token
`ensure-label.sh` / `apply-labels.sh` call per label — never a shell loop or an output capture around
a label helper — and reads the helper's stderr breadcrumb to tell *applied* from *API failure* from
*refused by the harness* (no output at all), recording the latter two as a `dropped-failed`
reflection rather than silently shipping an unlabeled PR.

The two-stage gate closes a silent-miss class: prior to this change, if a docs subagent missed a
named deliverable, Phase 4.1 ticked `Documentation` without any cross-check and the gap was only
visible to a human reading the PR diff.

**Discharging 3.4-deferred documentation ACs (before §4.3 Complete).** Any acceptance criterion the
Phase 3.4 gate deferred as Phase-4.1-owned (a `docs/…` deliverable, recorded in a `3.4: doc-AC deferred to
Phase 4.1: {AC text}` workpad note — see the Phase 3.4 gate above) is this phase's obligation to close.
Once the docs pass has run and its changes are committed, for **each** such deferred doc-AC the
orchestrator confirms the required docs actually landed in this run's diff (Stage 2 already verified the
named deliverable paths) and ticks the criterion by its 1-based position, citing the deferral note. This
tick **must** happen before §4.3's terminal `--status Complete` write, because `workpad.py`'s terminal
Complete gate hard-fails a Complete write while any non-post-merge acceptance-criteria row is still
unticked — a doc-AC left unticked would abort the finalize. A deferred doc-AC that genuinely cannot be
discharged (the docs pass could not author it and the content cannot be derived) is *not* ticked and *not*
finalized: it takes the existing `Blocked` path and emits the 👎 outcome reaction, never a silent Complete
over an undischarged doc-AC.

## Scope boundary between Phase 2.3.2 and Phase 4.1

The 2.3.2 stranded-dependents sweep covers references in **code, config, and routing tables** — things
that break behavior at runtime if left dangling (a surviving `href` to a deleted page, a call site
still passing dead arguments). It does **not** cover prose references to the deleted symbols/paths
inside `docs/internal/` (descriptions, walkthroughs, install steps). Those are handled by the Phase
4.1 documentation pass, which spawns the `prflow:docs` subagent after the code is committed. If a
2.3.2 grep turns up only docs hits, the skill notes them and moves on rather than editing
`docs/internal/` from Phase 2.3 — the docs pass has the full picture (shipped code, not just the
plan) and the right mandate to update prose.
