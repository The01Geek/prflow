# Pin-corpus residual-prose sweep — issue #1759 disposition record

<!-- referenced-by-machine: comments in lib/test/modules/create-issue-contract.sh cite this exact path as their retirement disposition record — do not move, rename, or delete this file without updating those citations. -->

This is the prose disposition record `CONTRIBUTING.md`'s *Retiring existence-only pins* rule
requires for a pin-only prose retirement (the record is kept on the pull request / in the repo,
never as a ledger row). Issue #1759 swept the 23 create-issue-associated prose pins (22 distinct
adjudication keys; one literal is pinned at two sites) that PR #1754's re-adjudication moved into
their mechanical prose bucket. Each was an agent-executed-prose existence pin that no tool or
consumer reads.

## Disposition of the 23 swept sites: RETIRED

The universals in this section are grounded by the enumerated 23-row table below (executed:
the regenerated `.prflow/logs/pin-corpus-inventory.tsv` carries none of the 23 swept create-issue
literals as a prose row, and every retired site appears in the table with its arm). Any
prose-bucketed rows still in that census belong to a separate, concurrently-authorized
re-adjudication (issue #1765's implement-skill pins), outside this sweep's scope.

**Consumer search (shared by the 23 rows below).** For each of the 23 literals, `pin-corpus-lint.py`'s
`machine_consumer_evidence` search — run over the same consumer corpus the lint reads — returned
no hit for the literal or its distinctive tokens. This is the search PR #1754's re-adjudication
recorded per row, and it is enforced on the prose-bucketed rows (with anti-vacuity controls) by
`test_final_inventory_realizes_only_authorized_buckets` in
`lib/test/test_residual_prose_retirement_manifest.py`, which was green over these rows before the
sweep. The compensating control for each retirement is the review pass that re-reads the shipped
prose each run — it narrows the coverage gap, it does not close it.

**Arm applied.** A `prose-sole-copy` row (`counted_occurrences < 2`) is retired pin-only under
arm 2. A `prose-multi-copy` row (`counted_occurrences >= 2`) is retired under arm 1 — together
with the deletion of one counted copy of its literal, named in the row below; no `prose-multi-copy`
row is retired pin-only. No retired literal had a *wrapped* (adjacent-fragment) home: each is a
whole-sentence or whole-heading literal carried contiguously, so `counted_occurrences` is not
under-counting it.

Pins are identified by assertion name only; the retired literals are **not** quoted verbatim
here, because `docs/internal/` is a counted home and re-quoting a `prose-multi-copy` literal
would re-add the counted copy the arm-1 deletion just removed.

**Removal consequence (the same for every row).** The existence assertion that the pinned
sentence still survives in the create-issue prompt surface is no longer made. A `prose-sole-copy`
row was retired pin-only (arm 2, its sole counted home left in place); a `prose-multi-copy` row
was retired under arm 1, and the one counted copy removed is named in the last column.

| # | Assertion (site) | Bucket | Arm-1 counted copy removed |
| --- | --- | --- | --- |
| 1 | `#272 AC6: issue-template has the Visual Specification section heading` (`lib/test/run.sh`) | prose-multi-copy | docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md (visual-spec sentence reworded) |
| 2 | `#275 pin (P4-ci): create-issue preamble carries the never-capture operative sentence` (`lib/test/run.sh`) | prose-sole-copy | — (arm-2 pin-only) |
| 3 | `#443: audit summary renders the word degraded whenever the degraded arm ran` (`lib/test/modules/create-issue-contract.sh`) | prose-multi-copy | docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md (summary-contents sentence reworded) |
| 4 | `#546: the step records each lifecycle event through the tool and obeys its answer` (`lib/test/modules/create-issue-contract.sh`) | prose-sole-copy | — (arm-2 pin-only) |
| 5 | `#546: no tool-owned decision is ever re-derived from this prose` (`lib/test/modules/create-issue-contract.sh`) | prose-sole-copy | — (arm-2 pin-only) |
| 6 | `#546: an illegal-transition rejection is not an unavailability signal` (`lib/test/modules/create-issue-contract.sh`) | prose-sole-copy | — (arm-2 pin-only) |
| 7 | `#546: the state-owner-unavailable marker is distinct from the degraded marker` (`lib/test/modules/create-issue-contract.sh`) | prose-sole-copy | — (arm-2 pin-only) |
| 8 | `#522: audit summary carries the declined-further-audit phrase` (`lib/test/modules/create-issue-contract.sh`) | prose-multi-copy | docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md (summary-contents sentence reworded) |
| 9 | `#546: the retired .md event log stays declared out of bounds (pre-cutover leftovers re-anchor)` (`lib/test/modules/create-issue-contract.sh`) | prose-sole-copy | — (arm-2 pin-only) |
| 10 | `#522: audit-prompt template states the DRAFT-UNREADABLE emit condition` (`lib/test/modules/create-issue-contract.sh`) | prose-sole-copy | — (arm-2 pin-only) |
| 11 | `#462 rule3: zero arm states the falsifiable no-dependencies claim, not a count` (`lib/test/modules/create-issue-contract.sh`) | prose-multi-copy | docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md (rule-3 zero-arm sentence reworded) |
| 12 | `#467 D2 (CLAUDE.md leg): best-effort-parser gotcha widened to mutable-markdown/external-format` (`lib/test/modules/create-issue-contract.sh`) | prose-multi-copy | docs/internal/claude-md-extension-audit-consumers.md (create-issue pin bullets removed) |
| 13 | `#467 D2 (Phase 2.4 leg): dry-trace rule widened to mutable-markdown/external-format` (`lib/test/modules/create-issue-contract.sh`) | prose-multi-copy | docs/internal/claude-md-extension-audit-consumers.md (create-issue pin bullets removed) |
| 14 | `#593: CLAUDE.md grant-timing gotcha states the in-PR-inert rule` (`lib/test/modules/create-issue-contract.sh`) | prose-multi-copy | docs/internal/claude-md-extension-audit-consumers.md (create-issue pin bullets removed) |
| 15 | `#548: loader-failure arm records the dedicated line` (`lib/test/modules/create-issue-contract.sh`) | prose-multi-copy | docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md (loader-marker sentence reworded) |
| 16 | `#603/AC1: ledger text is identity data, never protocol` (`lib/test/modules/create-issue-contract.sh`) | prose-sole-copy | — (arm-2 pin-only) |
| 17 | `#603/AC1: the decided recovery for a refused summary` (`lib/test/modules/create-issue-contract.sh`) | prose-sole-copy | — (arm-2 pin-only) |
| 18 | `#603/AC15: a twice-listed defect counts per listing` (`lib/test/modules/create-issue-contract.sh`) | prose-sole-copy | — (arm-2 pin-only) |
| 19 | `#603/AC15: reconciliation arm — recurrence of an invalidated entry` (`lib/test/modules/create-issue-contract.sh`) | prose-sole-copy | — (arm-2 pin-only) |
| 20 | `#603/AC13: the shared ledger-maintenance procedure both revision sites call` (`lib/test/modules/create-issue-contract.sh`) | prose-sole-copy | — (arm-2 pin-only) |
| 21 | `#603/AC19: an erroneous invalidation needs no amend path` (`lib/test/modules/create-issue-contract.sh`) | prose-sole-copy | — (arm-2 pin-only) |
| 22 | `#464 AC1: Step 3.6 generic checklist gains the adversarial-third-party-input dimension` (`lib/test/modules/create-issue-contract.sh`) | prose-multi-copy | docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md (both #464 mentions reworded) |
| 23 | `#464 AC3: Move 2 writes the coverage-sweep output back as closed AC items before filing` (`lib/test/modules/create-issue-contract.sh`) | prose-multi-copy | docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md (Move-2 sentence reworded) |

## Retained create-issue pins

Every other create-issue-associated pin site is **retained**: it is adjudicated `boundary` in
`lib/test/pin-corpus-adjudications.tsv` (a tool or consumer reads its target — a marker, a
schema/sentinel value, a routing/lifecycle contract, a generated-artifact identity, or a typed
executable boundary) and, where it is a source-presence pin, carries its `# structural-pin-ok:
<category>` declaration. No retained pin's literal resolves into agent-executed prose that no tool
reads — that is the population this sweep drained.

