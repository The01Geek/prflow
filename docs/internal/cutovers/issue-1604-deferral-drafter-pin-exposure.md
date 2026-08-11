# Issue #1604 — deferral-drafter pin-exposure measurement

This record is produced **before any prose is removed** from
`skills/implement/references/deferred-ac-followups.md`, as issue #1604's first
acceptance criterion requires. It names, for each assertion in `lib/test/run.sh`
that reads the implement bundle, whether that assertion depends on text inside
that reference, so the relocation of the Phase 4.0 filing procedure into
`agents/deferral-drafter.md` can re-point every surviving pin and retire every
pin whose protected text the change removes — with the exposure decided by
measurement, not by reading the pins.

## Instrument

Per the acceptance criterion, verbatim: empty the reference in a scratch
checkout, run `lib/test/run-shard.sh monolith`, and record every assertion whose
result flips from pass to fail.

Reproduction:

```bash
printf '' | tee skills/implement/references/deferred-ac-followups.md >/dev/null
lib/test/run-shard.sh monolith
git checkout -- skills/implement/references/deferred-ac-followups.md
```

The baseline (full reference) run is all-green for these assertions on the tree
this branch forked from; every failure below is therefore a pass→fail flip
caused by emptying the reference.

## Result — 14 dependent assertions

Emptying the reference flips **14** assertions from pass to fail. Every one
depends on text inside the reference. The `monolith` shard reported
`9071 passed, 14 failed, 1 skipped` on the emptied tree (the lone skip is the
`#434` stale-prose self-scan, which self-skips on a dirty tree and is unrelated
to the reference).

| # | Assertion (as `run.sh` names it) | Depends on reference text? | Disposition under the relocation |
|---|---|---|---|
| 1 | `implement-skill bundle member: …/deferred-ac-followups.md` | yes (member must be non-empty) | survives — the file is deleted, so it leaves the bundle-member population; no assertion names it |
| 2 | `#1011: Phase 4.0 stamps native blocked-by deps via apply-issue-dependencies.py …` | yes | survives — bundle-scoped; the `apply-issue-dependencies.py` idiom relocates into `phase-4-documentation.md` (a bundle member), count unchanged |
| 3 | `deferred.labels: SKILL resolves the labels in BOTH deferral channels (4.0 + 4.0.5)` | yes | survives — bundle-scoped `>=2`; the 4.0 `config-get.sh .deferred.labels` idiom relocates into `phase-4-documentation.md` |
| 4 | `deferred.labels: SKILL keeps the exact normalization pipeline in BOTH channels` | yes | survives — bundle-scoped `==2`; the exact `CLEAN_DEFERRED_LABELS` pipeline relocates into `phase-4-documentation.md` |
| 5 | `deferred.labels: SKILL discriminates config-get read failure via single-statement if! (both channels)` | yes | survives — bundle-scoped `==2`; the `if ! DEFERRED_LABELS=$(` idiom relocates into `phase-4-documentation.md` |
| 6 | `#375 wrapped-literal meta-guard: no resolvable pin phrase is off-line/wrapped …` | yes (pin-corpus health) | survives — every re-pointed pin's phrase resolves against its new target on the final tree |
| 7 | `#455 AC4: all four label call sites carry a co-located Cloud-emission discipline note` | yes | survives — the 4.0 label call sites and their Cloud-emission note relocate into `phase-4-documentation.md` |
| 8 | `#480 phase 4.0's create fence prints its unconditional sentinel …` | yes | survives — the create fence relocates into `phase-4-documentation.md`; the pin is re-pointed from `$I815_REF` to `$I480_P4` |
| 9 | `#480/#815 the relocated phase-4.0 ensure-label call site quotes the label arg` | yes | retired — the reference-scoped count is removed; the `ensure-label.sh "<label>"` quoting is re-covered by the `phase-4-documentation.md` count pin (raised to 2) |
| 10 | `#815 the gated reference exists and is non-empty` | yes | retired — the reference file is deleted; the routing that read it is inlined into `phase-4-documentation.md` |
| 11 | `#815 the reference's first line is its own start boundary marker` | yes | retired — reference deleted |
| 12 | `#815 the reference's last line is the matching end boundary marker` | yes | retired — reference deleted |
| 13 | `#815 the reference carries the filed-marker flag at its obligation, fence, and contract sites` | yes | survives — `--mark-deferred-filed` discharge relocates into `phase-4-documentation.md`; the pin is re-pointed from `$I815_REF` to `$I480_P4` |
| 14 | `#815 the reference sources parent-derived slots from the Phase 1.1 cache` | yes | survives — the parent-cache read relocates into `agents/deferral-drafter.md`; the pin is re-pointed from `$I815_REF` to the agent file |

## Path/existence pins reconciled in the same commit (not text-dependent, so not flipped by the instrument)

Emptying the reference does not flip these, because they read the reference's
**path** in another file rather than its own text — but the deletion of the file
requires reconciling each in the relocation commit (issue #1604 AC11):

- `#815 the section-4.0 slice no longer carries the follow-up-issue create fence`
  (`grep -cF 'gh issue create'` over the §4.0 slice `== 0`) — **retired**: the
  create fence is deliberately re-homed into §4.0, so its premise inverts.
- `#815 the stub names the reference through the <skill-dir> anchor on both paths`
  (count `== 2` in the phase file) — **retired**: §4.0 no longer reads a gated
  reference.
- `#815 the implement shape-lint population reaches the gated reference`
  (`IMPL_SHAPE_FILES` membership) — **retired**: the file is deleted.
- `#815 the cloud-writer manifest classifies the gated reference as a reachable
  asset` — **retired**, together with the `deferred-ac-followups.md` entry in
  `lib/test/cloud_writer_contract.py` (`SKILL_ASSETS["implement"]`).

## Decision

This measurement is published whatever it shows. Issue #1604 fixes no threshold
for abandoning the relocation on a large exposure; the 14 dependent assertions
each have a clean disposition (10 survive by re-homing the text into another
bundle member or the agent; 4 are retired for prose whose protected literal the
change removes), so the relocation proceeds. Had it been abandoned, this same
record — with its count of 14 dependent assertions — would still be the artifact
the pull-request body carries.
