---
schema: 1
kind: growth
---
# Issue #555 — discover deferral manifests (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

- `skills/implement/phases/phase-4-documentation.md` (mandatory, `implement-flow`) — +7,096 bytes.
- `CLAUDE.md` (mandatory, `project-memory`) — +988 bytes.

## Justification

Both additions land on the mandatory path because the decisions they carry are made *during* an
implement run, at the execution point they gate, and cannot be deferred to a conditionally-loaded
reference without leaving that execution point with nothing to execute.

`phase-4-documentation.md` §4.0.5 replaces a single `MANIFESTS=$(find … | sort)` statement — whose
masked exit status made a failed deferral search indistinguishable from a clean no-match search, the
issue #555 silent-loss defect observed live on issue #533 — with a discrimination the agent must
perform inline: the `discover-deferral-manifests.py` capture, its three-arm `if`/`elif`/`else`
classification into `DISCOVERY_STATE`, the two `dropped-failed` reflections the partial and
failed arms record, the roots-echo surfacing, the extended filing guard, the new `discovery=` field
on the unconditional sentinel, and three fail-closed reader-routing arms (`discovery=[]`,
`[failed]`, `[partial]`) plus the narrowing of the clean-no-op arm to require `discovery=[ok]`.
Every one of those bytes is a branch the run takes or a state it must not misread; the whole point
of the fix is that a degraded discovery must no longer route to the clean no-op, and a routing arm
moved to a rare-path reference is an arm the agent never reads on the path where it fires. The
executable half of the logic was extracted (that is what `scripts/discover-deferral-manifests.py`
is, and it carries the traversal, classification, and exit contract); what remains in the fence is
the invocation contract, the arm selection, and the fail-closed handling — the categories the
prose-cutover policy explicitly retains on the mandatory path.

**Superseded in part by issue #1374.** The paragraph above argues that §4.0.5's discrimination
cannot move to a conditionally-loaded reference "without leaving that execution point with
nothing to execute". That held while the *only* candidate gate was one the agent applied after
reading the section. #1374 supplied a gate that runs *before* it — the presence predicate
`discover-deferral-manifests.py --presence-for-pr N`, whose exit code decides the read — so the
whole fence, arms and all, now lives in `skills/implement/references/deferred-review-findings.md`
and the phase file carries only the predicate and its routing. Every routing arm this page
describes still exists and still fires; it fires from the reference, which a run with deferrals
has already loaded by the time it reaches them. The `+7,096 bytes` figure above stays as the
past-time record of what #555 cost on the mandatory path at the time.

`CLAUDE.md`'s addition is one clause appended to the existing #561 capability-manifest gotcha,
stating the implement-tier bundled-helper grant flow: such a grant is authored in
`lib/capability-profiles.json` and regenerated (which syncs the `matcher-probe.yml` `IMPLEMENT`
baseline with the baked `devflow-implement.yml` baseline), never by hand-editing either generated
literal. It is a targeted addition under the guidance it extends rather than a new section, and it
is pinned in `lib/test/modules/capability-profiles.sh` so it cannot be reworded back into
legitimizing a hand-edit without turning the suite red.
