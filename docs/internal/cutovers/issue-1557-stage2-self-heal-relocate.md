# Cutover — issue #1557: Phase 4.1 Stage 2's self-heal repair behind a gated reference

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.

`/prflow:implement` reads `skills/implement/phases/phase-4-documentation.md` in full on every Phase 4
entry, and again after the §4.1 documentation subagent returns. Both reads are mandated, so neither is
avoidable. Stage 2's self-heal repair — reached only for a named documentation deliverable the run's
cumulative diff does not carry — was paid on both regardless.

This change applies the §4.0/§4.0.5 shape to that repair, but as a **split rather than a wholesale
move**: only the repair procedure relocates. The enforcement decision — satisfied-versus-absent, and
the undeliverable-path `Blocked` terminal — stays resident in the phase file. That is the point of the
change: a failed reference load costs the run its *repair*, never its *gate*. Degrading would have let
the gate silently stop gating while the run still reported `Complete`; failing closed would have rested
a run-ending decision on an operand with no machine producer, since nothing emits "the reference
loaded" — the only comparand is the agent's own report of a `Read`.

**The split removes the failure-posture *dilemma*; it does not make the posture self-evident.** An
earlier draft of this record claimed there was "no failure-posture question to get wrong", and review
falsified that twice over. The failed-load arm had to be labelled as halting *by name*, because two
structurally identical arms earlier in the same file are headed "degrade, never halt" and an
orchestrator generalizes from its neighbours. And the terminal had to be re-founded on the absence of a
positive report, because the split introduced a path — an unclassified failure inside the reference —
that produced no report and satisfied none of the enumerated causes. Both defects were *created* by the
split and neither was visible from the design.

## Measured delta — a 687-byte **increase** in the always-read surface

Counted with `wc -c`; the Before column is merge base `3e43e7b32` and the After column is the head this
record ships on, captured 2026-08-17.

| File | Before | After | Delta |
| --- | --- | --- | --- |
| `skills/implement/phases/phase-4-documentation.md` | 59,113 | 59,800 | **+687** |
| `skills/implement/references/doc-deliverable-self-heal.md` | — | 4,296 | +4,296 |

**This change does not reduce the always-read surface. It grows it, and the honest reading is that the
size argument for the move failed outright.** Issues #815 and #1374 each cut their always-read surface
by tens of thousands of bytes. This one adds 687 to the file it was meant to shrink — paid on both
mandated Phase 4 reads, so 1,374 bytes of context per run — and adds a 4,296-byte reference on top,
loaded whenever a deliverable is actually absent. There is no run that comes out ahead on bytes.

The increase is not drift: it was bought deliberately, in the final review pass, to close a defect the
split itself introduced. The relocated repair told the agent to borrow Stage 2's rules and named which
of Stage 2's *terminal* arms it must not take — but Stage 2's `no-deliverables` **no-op** arm is not a
terminal, so it passed that filter, and that arm is a literal instruction to tick `Documentation`. A
mid-run edit to the issue body could therefore have driven the repair path into ticking the very gate it
was entered to satisfy, over a deliverable that never shipped. Fixing it meant stating the borrowing as
a positive contract instead of an exclusion list, retriggering the terminal on the **absence of a
repaired-and-verified report** rather than on an enumeration of causes, and labelling the failed-load
arm as halting where its two neighbours in the same file degrade.

A fourth change came from the acceptance-criteria gate rather than from review, and is worth recording
because of *how* it surfaced. The gate runs two independent verifiers over the same text, and they
reached **opposite** conclusions about this terminal: one read it as halting the run at the first
undeliverable path, the other as not halting the loop over the remaining paths. Both readings were
available because the terminal said to take itself "for every absent path" and then to "stop", which
cannot both happen. Two fresh readers disagreeing is a stronger ambiguity signal than either verdict,
so the paragraph was rewritten rather than adjudicated: it now collects every undeliverable path and
stops once, which also means a single run surfaces every missing deliverable instead of only the first.
Those four changes are the bytes.

**The reference's own figure moved eight times inside this pull request**: 2,707 at the first draft,
2,534 after the `/simplify` trim, then 3,463, 3,725 and 4,148 as successive review iterations fixed it,
3,682 when an iteration reverted a relaxation and deleted a routing claim the caller could not honour,
3,899 when the next scoped step 1's stop to the path and disclosed step 4's remote-tracking-ref blind
spot, 4,383 with the borrowing fix above, and finally 4,296 when the last pass resolved a
self-contradiction that fix had left in step 4. Read the row as this record's own measurement, not a
property of the design.

The arithmetic is structural rather than an authoring failure. A **split** leaves the `Blocked` terminal
resident where a **wholesale move** takes it along, and adds a gated-load instruction and a failed-load
arm on top of it. The file-level figure is the one to quote — Stage 2's step 3 grew rather than shrank,
which is what the **+687** in the table above measures — because a split pays for the apparatus twice
over: the resident half keeps the terminal and gains the load instruction and the failure arm, while
the reference re-states the context the moved procedure needs. A wholesale move pays neither. The
first draft
(`709cf0172`) was already **347 bytes larger** than the pre-change file — 59,460 against 59,113 — and
the branch spent three commits pulling that back below zero (`48cde1a30` cut 262 by merging the
failed-load paragraph into step 3; the `/simplify` pass `dddeda1b8` cut a further 147 by replacing a
third restatement of the boundary-marker contract with a pointer) only for the correctness fixes above
to put it back at +687. Every figure here is a `wc -c` reading of the commit named, taken 2026-08-17 —
the `+85` this paragraph carried through three review iterations was inherited from `dddeda1b8`'s own
commit message and never re-derived from the tree.

Three consequences, none hedged:

- The issue's **User Impact** claim — that such a run "stops carrying the enforcement steps twice for a
  gate it will never enter" — is **false as written**. The enforcement steps do not stop being carried:
  the read, the diff computation, the satisfied-versus-absent rule and the `Blocked` terminal all stay
  resident by design, and what left is the repair alone. The run now carries *more* on that path, not
  less.
- The change's justification is therefore **entirely** the failure-posture split described above, which
  the issue's own Problem Statement anticipated: "the recovered residency is a fraction of that 719 and
  the change is not justified on size." On size it is now negative, so nothing rests on it.
- **A reviewer weighing whether this was worth doing should weigh the split, and should know the size
  argument inverted.** The defensible reading is that the split is worth its bytes because it makes a
  gate failure impossible to confuse with a repair failure, and because the review pass it forced
  surfaced a live path to ticking `Documentation` over a missing file. The indefensible reading would be
  to keep quoting a byte reduction this branch no longer delivers.

These figures are a **past-time snapshot**, not a live measurement, so a change made after this branch
merges does not retroactively falsify the record. **That exemption does not extend to this branch's own
later commits**, because the After column is defined above as the head this record ships on: while the
branch is still moving, every commit that touches either file owes a re-measurement here. Read as
covering branch-side edits too, the sentence licensed exactly the error that had to be corrected four
times in review — each time by a revision that copied the previous figure forward instead of re-running
`wc -c`. The reference sits far under the 61,750-byte reader-capability ceiling
`lib/test/lint-reference-size.py` enforces over every boundary-gated reference and skill root.

## What moved, and what deliberately did not

Moved into `skills/implement/references/doc-deliverable-self-heal.md`:

- deriving the missing update from the issue body's `**Documentation Needed**` prose;
- performing it, recording the workpad note, committing with a `docs:` prefix and pushing;
- the remote-anchored re-check (`git rev-parse HEAD` equals `git rev-parse @{u}`) and the per-path
  re-computation of the cumulative diff;
- reporting the per-path outcome back to the caller, naming the resolved repository path the repair
  landed at. **That report is an audit record, not a control.** Nothing consumes the path: the terminal
  routes on whether an outcome was returned, never on where the file went, and the re-check applies the
  same lenient rule. So a bare-filename deliverable written to the wrong directory still satisfies
  Stage 2 — any basename match counts — and the only thing this change adds is that the wrong location
  is now *legible* in the caller's record instead of invisible. Closing it properly means resolving a
  bare filename against the configured docs roots, which is a separate change.

**What the reference deliberately does *not* re-decide** is whether the path is owed at all. It borrows
Stage 2's diff mechanics and nothing else: a re-read of the deliverables helper reporting
`no-deliverables`, or reporting a set that omits the path under repair, means *not repaired* — never
that the obligation lapsed. Naming this positively is load-bearing. The first draft named the excluded
arms instead, and Stage 2's `no-deliverables` arm — a no-op that proceeds directly to ticking
`Documentation` — is not a terminal, so it slipped through the exclusion list and gave the repair path
a route to ticking the gate over a file that never shipped.

Stayed resident in `skills/implement/phases/phase-4-documentation.md`:

- the Documentation-Needed helper re-run and its shared read contract routing, including the residual
  arm — the contract forbids trusting remembered Stage 1 output, so the read is what decides the load;
- the no-op-when-empty step;
- the cumulative-diff computation, its `$BASE` re-derivation with the non-empty fallback, and its
  fail-closed arm on a broken command;
- the satisfied-versus-absent rule;
- the undeliverable-path `Blocked` terminal — its `workpad.py` invocation, reflection text and 👎
  reaction verbatim. **Its trigger is not merely reworded but re-founded.** Before the move it fired
  on an enumeration of causes; it now fires on the *absence of an explicit repaired-and-verified
  outcome* for an absent path, with the causes demoted to examples. The reason is that the split
  introduced a way for a path to have no outcome at all: the reference's commit-and-push step has no
  failure arm, so an unclassified failure there — or a procedure interrupted mid-way — produced no
  report and satisfied none of the enumerated causes, leaving the terminal unfired and the run free to
  tick `Documentation`. A positive trigger has no such gap, because "no report" is itself the
  condition. The enumeration also gained `the reference could not be loaded`, the limb that makes a
  failed load fail closed.

The reference writes no run status at all and emits no outcome reaction — it carries no `--status`
call in any spelling and no 👎 — which is what keeps the terminal a single resident decision rather
than a duplicated one. The suite pins both prohibitions at that width rather than at `--status
Blocked` alone: a `--status Complete` or a stray reaction dragged into the reference would end the
run mid-loop exactly as wrongly, and a pin quoting only the Blocked spelling would not see it.

## The predicate is the existing read, not a new helper

§4.0 and §4.0.5 each paired their relocation with an executable helper that became the sole owner of the
load decision. This change adds none: the branch's `--name-status` delta against the merge base carries
no `A` entry under `scripts/`, and its two `scripts/` entries are both modifications — the manifest key
and the durability helper's header comment. Stage 2 already re-runs
`scripts/read-doc-needed-deliverables.sh` and already decides satisfied-versus-absent from its printed
`docgate-path:` values against the cumulative diff; the reference is read on the arm where that decision
came out *absent*. So the predicate that gates the load is the decision the phase file was already
making, and `CLAUDE.md`'s helper-cutover rule — that operative decision logic must not migrate into a
progressively loaded reference — is satisfied by the split rather than by a new owner: the operative
decision never leaves the phase file.

## Coupled sites moved in the same commit

- `lib/test/cloud_writer_contract.py`'s `SKILL_ASSETS["implement"]` gains the reference, and
  `scripts/devflow-cloud-writer-contract.json` gains **only that key**. `main` is that manifest's sole
  writer of digests, so the branch adds the new entry by hand rather than regenerating — regeneration
  would also refresh the digests of the assets this branch edited, which
  `lib/test/cloud-writer-retention-check.py` refuses.
- `lib/test/lint-worktree-fence-shapes.py`'s `ENROLLED` gains the reference. The relocated procedure
  states its steps as bash fences where the phase file stated them as prose, so this change
  introduces fenced call sites that hand-maintained, new-file-blind tuple would never audit.
- `lib/test/lint-anchor-fallback-arm.py`'s `ENROLLED` gains a `workpad.py` row for the reference. This
  is an **addition, not a re-pointing**: the issue's Call-site migration paragraph states that a
  `phase-4-documentation.md` row already enrolled this call site. Reading the tuple refutes that —
  before this change `phase-4-documentation.md` occurred once in that file, as the §4.0.5
  `discover-deferral-manifests.py --presence-for-pr` predicate's row, whose call site does not move and
  which is left untouched.
- `docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md`'s durability-checkpoint bullet and
  `scripts/phase2-durability-checkpoint.sh`'s header each named the landing-verification rule as
  "`phase-4-documentation.md` step 3" and now name the reference, which is where that rule went. A
  fourth site, `skills/implement/phases/phase-2-implement.md`, carried the same pointer and is
  repointed too. Three of the four spell the phrase with the filename in backticks — the exception is
  `phase2-durability-checkpoint.sh`, whose comment spelled it bare — so no single search string
  matched all four, and a sweep for the unquoted form missed the three that were quoted. That is how
  the fourth site hid through two sweeps; after a widened search surfaced it, it survived a further
  two review iterations because it had been *identified* without being *fixed*. It is the only one of
  the four in a shipped skill body, so a reader of a consumer's checkout was the one this dangling
  pointer would have stranded.
- `docs/internal/implement-skill.md`'s Stage 2 section is **not** one of those repointings: it never
  carried the "step 3" phrase. It described the self-heal and `Blocked` arms as one undivided
  procedure, and is rewritten here to describe them as the split this change makes — repair gated,
  decision resident, with the failed-load arm named.

The bundle-scoped pins needed no re-pointing: `lib/test/run.sh` builds the implement bundle from
`skills/implement/references/*.md` by glob, so a literal that moved from the phase file into the
reference is still found. The implement shape-lint population, the create-issue contract module's
bundle, the module-runner fixture and the flight-recorder registry all enrol by the same glob.

## What the suite asserts, and what it deliberately does not

Asserted: the reference exists and is non-empty; its first line is its `start` marker and its last line
the matching `end` marker; **each marker occurs exactly once**, so a mid-file duplicate cannot pass a
first-line-and-last-line check; the stub resolves the gated load through the `<skill-dir>` anchor
exactly once (an *occurrence* count via `pin_count` rather than `grep -cF`, so a second occurrence
added to the same line could not hide behind a line count); the
reference is a member of the implement shape-lint population and of the cloud-writer manifest; it is not
a `phases/` member and the phase-stem reconciliation is unchanged; and both hand-maintained lint
enrolments carry it — read from each lint's own `--print-inventory`, never grepped out of its source,
because a source grep is satisfied by a path in a comment or a commented-out entry, and for the
anchor-fallback lint the inventory row is a *pair* whose helper operand a bare path match would miss.

The move itself is asserted by a **Stage-2-scoped slice**: a `sed` range from the `**Stage 2 —` opening
literal to the `config-get.sh .docs.labels Documented` invocation, proved non-empty before anything is
counted, then a zero count for `performed update from Documentation Needed prose` — a literal unique to
the moved repair. **The gate's own residency is asserted from both ends**, because the terminal's
presence does not establish that the decision firing it stayed put: alongside the resident-terminal
pin, the slice carries a positive count for `docgate-path`, the helper-printed sentinel the
satisfied-versus-absent rule reads. Without that row, a later change that dragged the decision into
the reference — which the reference invites, since it tells the agent to re-run the same check — would
leave the slice non-empty, the zero count 0, the anchor count 1, the terminator unique and the terminal
unique: every `#1557` row green while the gate had followed the repair out of Stage 2. The terminator is
a machine-consumed helper invocation rather than a prose sentence,
and it carries its own retention pin, because a vanished terminator would silently widen the range to
end-of-file and restore the vacuity the scoping exists to close. The paired positive count — the same
literal present twice in the reference — sits **outside** the scratch guard, because it reads only the
reference and would otherwise vanish on a scratch failure, taking with it the half that makes the pair
non-vacuous. Scratch-allocation failure emits one `skip` per slice-dependent assertion, each named
byte-identically to the `assert_eq` it stands in for and classified `blocking-gate`, since they are
real gates that could not run here — there are four such assertions and four skips, and a single
composite skip would report one loss where four occurred and would reconcile to none of them.

Not asserted: the stub's prose contract — the marker contract it applies, and the route it takes on an
empty read. Those sentences are agent-executed prompt prose, whose only reader is the runtime agent, so
pinning them would be the wording-only class `CLAUDE.md`'s authoring boundary prohibits, wearing a
mutation costume. Per the recorded decision that such prose carries no automated regression coverage by
design, the review pass is their control, and this page states the gap rather than implying coverage.

Also not asserted, and a coverage loss taken knowingly: the failed-load arm's **reflection text**.
While that arm spelled the reference with the `<skill-dir>` anchor, the occurrence count of 2 incidentally
covered it; naming the plain repo-relative path there — correct, because `<skill-dir>` resolves against
nothing in a durable workpad record — drops the count to 1 and leaves the reflection's path unpinned. A
pin would be worth less than it looks: the arm is agent-executed prose, so it falls under the same
recorded decision as the paragraph above, and the coverage it lost was a side effect of a spelling
rather than a property anyone chose to assert.
