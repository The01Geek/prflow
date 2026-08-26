---
schema: 1
kind: relocate
---
# Issue #815 — deferred ac followups relocate (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Source rows

- `skills/implement/phases/phase-4-documentation.md` (mandatory, `implement-flow`) — 116,879
  bytes / 701 lines at this branch's merge base, of which section 4.0 (the deferred-AC
  follow-up filing procedure, lines 7–128) was 23,241 bytes. Issue #815 quotes 116,623 /
  699 lines: that was the true size when the issue was filed, and a concurrently-merged PR
  added 256 bytes to §4.1 before this branch merged the base. Both figures are correct at
  their own moment; the merge-base figure is the one this move's delta is measured against. The orchestrator's Phase 4 entry-gate
  reads the whole file on every `/prflow:implement` run, and re-reads it at each mid-phase
  re-anchor, so section 4.0's bytes were paid by every run and re-paid by every re-anchor —
  including the runs whose predicate could not fire.

## Destination

- `skills/implement/references/deferred-ac-followups.md` (`implement-conditional`,
  `reference` — a genuinely conditional file) — 29,651 bytes, reached only when
  `scripts/workpad.py deferred-presence <issue> <pr>` reports an outstanding or an
  unestablished answer, behind a first-line/last-line boundary-marker entry gate that
  degrades best-effort rather than halting. Trigger: at least one `kind=deferred`
  scope-decision record bound to this run's PR carries no filed marker, or the answer
  could not be settled.

The phase file retains a routing stub in section 4.0's place carrying the predicate call,
the three exit-code arms, the `<skill-dir>` reference path, the marker contract, and the
degraded arm.

## Measured delta (a past-time snapshot, counted with `wc -c` at the change's HEAD)

| File | Before | After |
| --- | --- | --- |
| `skills/implement/phases/phase-4-documentation.md` | 116,879 | 96,264 |
| `skills/implement/references/deferred-ac-followups.md` | — | 29,651 |

Removing section 4.0 alone leaves 93,638, so the routing stub was 2,626 bytes — inside the
acceptance criterion's ~3,200-byte allowance. The stub was trimmed twice: once at authoring
time, and again after the base merge added 256 bytes to §4.1. Every remaining element is one
the acceptance criteria require it to carry separately — the predicate call, each of the
three exit-code arms, the marker contract, the degraded arm and its stated residual, and the
self-sufficiency sentence.

**Superseded 2026-08-11 by issue #1595:** a byte ceiling now *is* enforced —
`lib/test/lint-reference-size.py` caps every boundary-gated reference and skill root at
61,750 bytes, a reader-capability limit rather than the authoring budget this paragraph
was denying. The paragraph stands as written below because it records what was true when
this page was made; this page still registers no ceiling of its own.

**No byte ceiling on this file is enforced anywhere in the tree, and none ever was.** Issue
#1374 searched `lib/test/run.sh` for a positional size assertion over
`skills/implement/phases/phase-4-documentation.md` and found none; the sentences that used
to stand here described such a gate as live and as turning a growing file RED, which would
have told a reader a check existed to catch an edit that in fact nothing catches. The
figures above and below stay because they are a past-time snapshot of what a change cost —
a record, not a threshold.

These figures are a **past-time snapshot**, not a live measurement: they record what the
move cost at the moment it was made, so a later change to either file does not retroactively
falsify the record. The counter is `wc -c`.

## Size record — issue #834

Issue #834 appends a consumer prompt-extension by-path handoff sentence to the Phase 4.1
`prflow:docs` dispatch in `skills/implement/phases/phase-4-documentation.md`. The addition
is **unconditional** — every Phase 4.1 run dispatches that subagent, and the child cannot
resolve its own skill anchor — so it is not routable behind a conditional
progressively-loaded reference the way section 4.0 was: a gate that always fires saves no
context and adds a degraded arm that could silently drop the handoff. The addition was
therefore taken rather than deferred or shrunk past its operative content.

| ref | `wc -c skills/implement/phases/phase-4-documentation.md` |
| --- | --- |
| pre-#834 (`main` at the change) | 96,264 |
| #834 first draft | 98,005 |
| #834 after trimming the paragraph's non-operative rationale | 97,729 |

The paragraph was trimmed before the raise was taken: the two sentences restating what the
quoted child-facing sentence already says (that it is inert when no extension exists, and
that a file read needs no allowlist or permission grant) were removed, keeping the
substitution rule, the verbatim child sentence, the no-probe prohibition, and the
unreadable-extension relay. These figures are a past-time snapshot on the same terms as the
table above; **97,729** is what the file measured after that trim, not a threshold any check
compares against.

## Conservation

The relocated prose moves verbatim apart from four recorded deviations, each of which the
change's own contract requires:

1. The opening sentence's `Skip this step if no criteria were deferred.` clause is replaced
   by a sentence stating that the stub's predicate has already established the answer, plus
   the reference's own skip sentence for the unestablished arm. That skip sentence is what
   the stub's cost argument leans on — a needless load on an unestablished operand costs one
   read the reference absorbs. The unestablished arm carries its own procedure, because the
   predicate exits before it computes the outstanding set and so prints no `criterion:`
   line there: the reference enumerates the deferred criteria directly from the Phase 2.2.5
   `--note` bullets, conditions the skip solely on that enumeration being empty, treats the
   two arms that print no `filed:` line at all (`reason=workpad-unresolved`,
   `reason=progress-section-unreadable`) as an operand that is unavailable rather than
   empty — checking GitHub for an existing follow-up before creating one — and normalizes
   the note's verbatim text itself before passing it to `--mark-deferred-filed`.
2. A paragraph distinguishing the two criterion channels: the predicate's `criterion:`
   projection is **normalized** (`scripts/section_parse.py`'s `normalize_criterion` strips a
   trailing ` (post-merge)` tag and collapses whitespace runs), so it identifies which
   criteria are outstanding, while the Phase 2.2.5 free-text `--note` stays the verbatim
   carrier the follow-up issue reproduces from.
3. A bullet sourcing the follow-up body's parent-derived slots from the Phase 1.1 issue-body
   cache by path, with the `NOT_IGNORED` degraded arm stated, and an explicit prohibition on
   adding a `gh issue view` of its own (`lib/test/lint-issue-body-refetch.py` audits every
   path under `skills/implement/`).
4. The terminal `--note` call gains one `--mark-deferred-filed` per filed criterion in the
   same call. That durable marker is what makes the predicate non-monotonic: nothing else
   discharges a scope-decision record, so a deferral-only predicate would stay true after
   filing and a second Phase 4 entry would file duplicates.

## Runtime-context axis

The acceptance criteria gate the **static shipped size** axis only. Runtime main-thread
context is a distinct quantity measured by its own behavioral instrument, as
`docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md` and `docs/internal/create-issue-context.md` establish; this change
carries the runtime-context reduction as a stated assumption rather than a gated criterion,
and no figure on that axis is recorded here.
