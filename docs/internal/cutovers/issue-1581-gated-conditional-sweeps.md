# Cutover — issue #1581: the eight conditional Phase 2.3 sweeps relocated behind predicates

`/prflow:implement` reads `skills/implement/phases/phase-2-sweeps-contract.md` and
`phase-2-sweeps-quality.md` in full at Phase 2 entry, and again at each re-entry. Fourteen
sweeps live in that §2.3 span, but only six of them fire on every diff. The other eight —
2.3.0, 2.3.0a, 2.3.0b, 2.3.0c, 2.3.0d, 2.3.1, 2.3.2, 2.3.7 — are trigger-gated, and their
procedures were paid on every read regardless, because the decision to skip a sweep is one the
agent makes *after* reading how to run it.

This change applies the shape issues #815 and #1374 established for Phase 4's two deferral
channels to the Phase 2.3 sweep set: a trigger heading and a resident `**Predicate.**`
paragraph stay in the phase file, the procedure moves to a per-sweep gated reference, and the
reference is read only when the predicate fires. **Sweep execution itself stays inline** — no
sweep was moved into a subagent, and no sweep's obligations changed.

## Measured delta (a past-time snapshot, `wc -c` at commit `a28c87e50` against merge base `e5d865f93`, captured 2026-08-17)

| File | Before | After |
| --- | --- | --- |
| `skills/implement/phases/phase-2-sweeps-contract.md` | 57,560 | 34,050 |
| `skills/implement/phases/phase-2-sweeps-quality.md` | 51,989 | 47,054 |
| `skills/implement/references/sweep-*.md` (eight files) | — | 38,122 |

The two phase files are the always-read surface, so the always-read count falls from 109,549
to 81,104 bytes per mandated Phase 2 read. A run pays for a conditional sweep's procedure only
when its diff warrants that sweep. These figures are a **past-time snapshot** recording what
the move cost when it was made; a later edit to either file does not retroactively falsify
them. No byte ceiling is registered here — the live ceiling is
`lib/test/lint-reference-size.py`'s 61,750 bytes over every boundary-gated reference and skill
root, which every file in the table clears.

## The protocol, stated once

A **Gated sweep procedures** block in the §2.3 preamble carries the whole contract, so no
sweep restates it:

- Evaluate each predicate from the resident text alone. A predicate never evaluated is a sweep
  that silently stops firing.
- Evaluate all eight predicates first, then issue the fired sweeps' reads **together in one
  turn** — the procedures carry no ordering dependency, and one read per turn costs a round
  trip each.
- **Marker contract.** Accept the load only when the file's first line is its `start` boundary
  marker and its last line the matching `end` marker, each naming that file's own path,
  compared against the plugin-relative form starting `skills/implement/references/` with any
  vendored (`.prflow/vendor/prflow/`) or absolute prefix stripped from the resolved read path
  first. Comparing the resolved path instead classifies a correct file as mismatched and
  degrades the sweep on every consumer and cloud run.
- **Degrade, never halt.** A fired predicate whose reference read fails — absent, empty,
  harness-refused, or mismatched markers — records a `dropped-failed` reflection naming the
  reference path and stating that the sweep did not run, then continues to the next sweep
  without halting Phase 2. A silently skipped sweep is indistinguishable from one that found
  nothing.
- A run that took the degraded arm for **2.3.0** does not tick the Completion Checklist's "the
  2.3.0 changed-contract … sweeps all ran" Phase 2 item: it restates that item naming 2.3.0 as
  the sweep that did not run, so a degraded sweep cannot be reported as a completed one.

## 2.3.0c's own trigger widened in the same change

2.3.0c's prose-policy trigger fires on a policy-stating agent-executed command block. Moving
eight procedures into `references/*.md` made that population a live one, so the trigger names
`references/*.md` alongside `SKILL.md` and `phases/*.md` at all three sites that state it: the
§2.3 selection preamble, 2.3.0c's own predicate, and the sweep's procedure. Left unwidened,
the sweep would have stopped selecting exactly the files this change created.

## Consumers re-anchored in the same commit

**The fix loop.** `skills/review-and-fix/references/fixing.md` item 3b resolves the §2.3 index
from the executing implement bundle and adjudicates against a durable `sweep_defs_read`
record. Its source set was the three phase files; a conditional sweep read from that set alone
now yields a predicate and no procedure, and a sweep run from a predicate stub is not run at
all. The Read protocol therefore adds a **warranted** conditional sweep's own gated reference
to the source set, records it in `sweep_defs_read` as its own entry (path, `whole`/`incomplete`,
sweep identifier) exactly like a phase-file member, and makes the completeness condition
require a `whole` entry for every warranted conditional sweep's reference as well as for all
three phase members. The unreadable-source arm is unchanged: record `sweeps: unrunnable …`,
name Step 3.5 and the shadow as the covering backstop, and continue.

**The desk lint.** `lib/test/run.sh`'s `#478` routing-marker lint checks that every
closed-vocabulary routing marker present in a §2.3 sweep body has a mapping-table row in item
3b. Its corpus was the phase files' `Sweep selection` → `### 2.4 Test` span; it now
concatenates `skills/implement/references/sweep-*.md` onto that span. Two fail-closed
properties are load-bearing and are why the extractor is not a plain `cat`: it returns before
the references when the span itself did not open, or the caller's empty-corpus RED arm becomes
vacuous; and it propagates a non-zero status from the concatenation, which the caller routes
to RED, because a *partial* corpus is populated but short — the emptiness test alone would let
the lint report GREEN having checked fewer markers than it claims.

**The dispatch table.** A new `#1581` block treats the phase files' `**Procedure:**` pointer
set as the gated sweeps' dispatch table and reconciles it against the tracked on-disk
`sweep-*.md` set **both ways round**: a pointer naming a missing file makes the gated read fail
and drops a mandatory sweep, and an unpointed reference is a sweep nothing dispatches. Each
limb is asserted non-empty before the comparison, because a two-sided disappearance — the
references directory and the phase files renamed in one change, which is the relocation class
this guard exists for — would otherwise compare `""` to `""` and report GREEN having
reconciled nothing. The on-disk limb comes from `git ls-files`, not a working-tree glob, so an
untracked scratch file cannot join the table; the declared limb is constrained to `sweep-`
basenames so a later non-sweep pointer cannot turn the check RED with a message asserting a
broken sweep table that is not broken. The block also pins each reference's first and last
lines as its own self-naming boundary markers: a `file=` value that drifts from its filename
makes the run's gated read treat the reference as truncated and drop a mandatory sweep with
every other check green.
