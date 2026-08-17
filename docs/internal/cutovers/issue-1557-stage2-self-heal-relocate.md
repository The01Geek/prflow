# Cutover — issue #1557: Phase 4.1 Stage 2's self-heal repair behind a gated reference

`/prflow:implement` reads `skills/implement/phases/phase-4-documentation.md` in full on every Phase 4
entry, and again after the §4.1 documentation subagent returns. Both reads are mandated, so neither is
avoidable. Stage 2's self-heal repair — reached only for a named documentation deliverable the run's
cumulative diff does not carry — was paid on both regardless.

This change applies the §4.0/§4.0.5 shape to that repair, but as a **split rather than a wholesale
move**: only the repair procedure relocates. The enforcement decision — satisfied-versus-absent, and
the undeliverable-path `Blocked` terminal — stays resident in the phase file. That is the point of the
change: a failed reference load costs the run its *repair*, never its *gate*, so there is no
failure-posture question to get wrong. Degrading would have let the gate silently stop gating while
the run still reported `Complete`; failing closed would have rested a run-ending decision on an operand
with no machine producer, since nothing emits "the reference loaded" — the only comparand is the
agent's own report of a `Read`.

## Measured delta — a 62-byte reduction, not the reduction the precedents bought

Counted with `wc -c` at merge base `3e43e7b32`, captured 2026-08-17.

| File | Before | After | Delta |
| --- | --- | --- | --- |
| `skills/implement/phases/phase-4-documentation.md` | 59,113 | 59,051 | **−62** |
| `skills/implement/references/doc-deliverable-self-heal.md` | — | 2,534 | +2,534 |

**Read that number before assuming this move resembles its precedents.** Issues #815 and #1374 each cut
their always-read surface by tens of thousands of bytes. This one cuts 62 — about a tenth of one
percent — which over the two mandated Phase 4 reads is 124 bytes of context per run, against +2,534
loaded on the repair path when a deliverable is actually absent. On any run that owes a repair the
change is net additive; only a run that owes none comes out ahead, and then barely.

The arithmetic is structural rather than an authoring failure. A **split** leaves the `Blocked` terminal
resident where a **wholesale move** takes it along, and adds a gated-load instruction and a degraded arm
on top of it, so the gating apparatus costs nearly as much as the repair it gates. The first draft of
this change was in fact 85 bytes *larger* than the pre-change file; it reaches −62 only because the
`/simplify` pass noticed the stub was restating the boundary-marker contract a **third** time in one
file (§4.0 and §4.0.5 already state it identically) and replaced that restatement with a pointer.

Two consequences, neither hedged:

- The issue's **User Impact** claim — that such a run "stops carrying the enforcement steps twice for a
  gate it will never enter" — is **true in direction and badly wrong in magnitude**. The enforcement
  steps do not stop being carried: the read, the diff computation, the satisfied-versus-absent rule and
  the `Blocked` terminal all stay resident by design, and what left is the repair alone. Read as written
  the sentence promises a reduction this scope cannot deliver.
- The change's justification is therefore the **failure-posture split** described above, which the
  issue's own Problem Statement anticipated: "the recovered residency is a fraction of that 719 and the
  change is not justified on size."

These figures are a **past-time snapshot**, not a live measurement, so a later change to either file
does not retroactively falsify the record. The reference sits far under the 61,750-byte reader-capability
ceiling `lib/test/lint-reference-size.py` enforces over every boundary-gated reference and skill root.

## What moved, and what deliberately did not

Moved into `skills/implement/references/doc-deliverable-self-heal.md`:

- deriving the missing update from the issue body's `**Documentation Needed**` prose;
- performing it, recording the workpad note, committing with a `docs:` prefix and pushing;
- the remote-anchored re-check (`git rev-parse HEAD` equals `git rev-parse @{u}`) and the per-path
  re-run of the helper-driven diff check;
- reporting the per-path outcome back to the caller.

Stayed resident in `skills/implement/phases/phase-4-documentation.md`:

- the Documentation-Needed helper re-run and its shared read contract routing, including the residual
  arm — the contract forbids trusting remembered Stage 1 output, so the read is what decides the load;
- the no-op-when-empty step;
- the cumulative-diff computation, its `$BASE` re-derivation with the non-empty fallback, and its
  fail-closed arm on a broken command;
- the satisfied-versus-absent rule;
- the undeliverable-path `Blocked` terminal — its routing verbatim, its condition clause widened by
  `the reference could not be loaded`, which is the mechanism that makes the split fail closed.

The reference writes no run status at all — it carries no `--status Blocked` call — which is what keeps
the terminal a single resident decision rather than a duplicated one.

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
- `docs/internal/implement-skill.md`'s Stage 2 section, `docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md`'s
  durability-checkpoint bullet, and `scripts/phase2-durability-checkpoint.sh`'s header each named the
  landing-verification rule as "`phase-4-documentation.md` step 3" and now name the reference, which is
  where that rule went.

The bundle-scoped pins needed no re-pointing: `lib/test/run.sh` builds the implement bundle from
`skills/implement/references/*.md` by glob, so a literal that moved from the phase file into the
reference is still found. The implement shape-lint population, the create-issue contract module's
bundle, the module-runner fixture and the flight-recorder registry all enrol by the same glob.

## What the suite asserts, and what it deliberately does not

Asserted: the reference exists and is non-empty; its first line is its `start` marker and its last line
the matching `end` marker; **each marker occurs exactly once**, so a mid-file duplicate cannot pass a
first-line-and-last-line check; the stub names the reference through the `<skill-dir>` anchor twice (an
*occurrence* count via `pin_count`, because both sit on one line and a line count would read 1); the
reference is a member of the implement shape-lint population and of the cloud-writer manifest; it is not
a `phases/` member and the phase-stem reconciliation is unchanged; and both hand-maintained lint
enrolments carry it — read from each lint's own `--print-inventory`, never grepped out of its source,
because a source grep is satisfied by a path in a comment or a commented-out entry, and for the
anchor-fallback lint the inventory row is a *pair* whose helper operand a bare path match would miss.

The move itself is asserted by a **Stage-2-scoped slice**: a `sed` range from the `**Stage 2 —` opening
literal to the `config-get.sh .docs.labels Documented` invocation, proved non-empty before anything is
counted, then a zero count for `performed update from Documentation Needed prose` — a literal unique to
the moved repair. The terminator is a machine-consumed helper invocation rather than a prose sentence,
and it carries its own retention pin, because a vanished terminator would silently widen the range to
end-of-file and restore the vacuity the scoping exists to close. The paired positive count — the same
literal present twice in the reference — sits **outside** the scratch guard, because it reads only the
reference and would otherwise vanish on a scratch failure, taking with it the half that makes the pair
non-vacuous. Scratch-allocation failure routes the two slice-dependent assertions to the `skip` helper,
named individually and classified `blocking-gate`, since they are real gates that could not run here.

Not asserted: the stub's prose contract — the marker contract it applies, and the route it takes on an
empty read. Those sentences are agent-executed prompt prose, whose only reader is the runtime agent, so
pinning them would be the wording-only class `CLAUDE.md`'s authoring boundary prohibits, wearing a
mutation costume. Per the recorded decision that such prose carries no automated regression coverage by
design, the review pass is their control, and this page states the gap rather than implying coverage.
