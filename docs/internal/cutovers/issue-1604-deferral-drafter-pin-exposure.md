# Issue #1604 — deferral-drafter pin-exposure measurement

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.

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

The relocation this record gated keeps the reference **on disk** — its
composition prose moves to `agents/deferral-drafter.md`, while its **GitHub
writes and the dispatch instruction stay in the reference**, which the
orchestrator reads and executes only when the predicate says work is outstanding.
Because the reference retains every write literal these assertions read, **all 14
survive unchanged** against a literal present on the final tree — none is
re-pointed and none is retired.

| # | Assertion (as `run.sh` names it) | Depends on reference text? | Disposition under the relocation |
|---|---|---|---|
| 1 | `implement-skill bundle member: …/deferred-ac-followups.md` | yes (member must be non-empty) | survives — the reference stays on disk (writes-only), so it stays a non-empty bundle member |
| 2 | `#1011: Phase 4.0 stamps native blocked-by deps via apply-issue-dependencies.py …` | yes | survives — the `apply-issue-dependencies.py` idiom stays in the reference |
| 3 | `deferred.labels: SKILL resolves the labels in BOTH deferral channels (4.0 + 4.0.5)` | yes | survives — the 4.0 `config-get.sh .deferred.labels` idiom stays in the reference |
| 4 | `deferred.labels: SKILL keeps the exact normalization pipeline in BOTH channels` | yes | survives — the exact `CLEAN_DEFERRED_LABELS` pipeline stays in the reference |
| 5 | `deferred.labels: SKILL discriminates config-get read failure via single-statement if! (both channels)` | yes | survives — the `if ! DEFERRED_LABELS=$(` idiom stays in the reference |
| 6 | `#375 wrapped-literal meta-guard: no resolvable pin phrase is off-line/wrapped …` | yes (pin-corpus health) | survives — every pin phrase still resolves against its target on the final tree |
| 7 | `#455 AC4: all four label call sites carry a co-located Cloud-emission discipline note` | yes | survives — the 4.0 label call sites and their Cloud-emission note stay in the reference |
| 8 | `#480 phase 4.0's create fence prints its unconditional sentinel …` | yes | survives — the create fence stays in the reference |
| 9 | `#480/#815 the relocated phase-4.0 ensure-label call site quotes the label arg` | yes | survives — the `ensure-label.sh "<label>"` call stays in the reference |
| 10 | `#815 the gated reference exists and is non-empty` | yes | survives — the reference stays on disk |
| 11 | `#815 the reference's first line is its own start boundary marker` | yes | survives — boundary markers unchanged |
| 12 | `#815 the reference's last line is the matching end boundary marker` | yes | survives — boundary markers unchanged |
| 13 | `#815 the reference carries the filed-marker flag at its obligation, fence, and contract sites` | yes | survives — the `--mark-deferred-filed` discharge stays in the reference |
| 14 | `#815 the reference sources parent-derived slots from the Phase 1.1 cache` | yes | survives — the reference still names the `.prflow/tmp/issue-body/issue-` cache path (now as the drafter's `ISSUE_BODY_PATH` operand) |

## Path/existence pins — no reconciliation needed

The `#815` pins that read the reference's **path** in another file
(`IMPL_SHAPE_FILES` membership, the `cloud_writer_contract.py` reachable-asset
entry, the section-4.0 `gh issue create == 0` slice, the `<skill-dir>` anchored
path count) all continue to hold unchanged, because the reference still ships and
§4.0 still reads no create fence of its own (the create fence lives in the
reference the orchestrator loads). No boundary-marker pin and no
`cloud_writer_contract.py` closure entry names a file the change stops shipping,
so issue #1604 AC11's reconciliation clause is satisfied vacuously.

## Decision

This measurement is published whatever it shows. Issue #1604 fixes no threshold
for abandoning the relocation on a large exposure; all 14 dependent assertions
survive against a literal present on the final tree (the reference is retained as
the write/dispatch surface and its literals stay put), so **no assertion is
retired** and the relocation proceeds with the composition moved into the
`deferral-drafter` agent's isolated context. Had it been abandoned, this same
record — with its count of 14 dependent assertions — would still be the artifact
the pull-request body carries.
