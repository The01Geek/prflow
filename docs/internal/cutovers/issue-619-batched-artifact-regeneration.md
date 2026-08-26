---
schema: 1
kind: growth
---
# Issue #619 — batched artifact regeneration (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

Each of the mandatory census rows listed below grows by one `## Batched artifact regeneration` section. The defining site is the `for _ra_ext in …` pin loop in `lib/test/run.sh`, which pins every listed surface — a count stated here would be a mirror-fact that rots if a fourth surface is added:

- `.prflow/prompt-extensions/implement.md` — the `/prflow:implement` entry surface, loaded
  unconditionally by its `load-prompt-extension.sh` step.
- `.prflow/prompt-extensions/review-and-fix.md` — the `/prflow:review-and-fix` entry surface,
  loaded unconditionally by its SKILL.md `load-prompt-extension.sh` step.
- `.prflow/prompt-extensions/receiving-code-review.md` — loaded whenever the
  receiving-code-review skill itself loads (interactive invocations and description-matched
  dispatches).

No other mandatory row moves. The vendored `skills/receiving-code-review/SKILL.md` is **not**
modified: its body must stay repo-agnostic, and this instruction names repo-specific paths.

## Justification

These bytes buy back full-suite runs, which are the repo's slowest verification step. Before this
change, a loop discovered each drifted generated artifact one full-suite run at a time — an
observed fix loop paid three such rerun cycles on three mechanical regeneration chores whose
commands were already known (the cloud-writer runtime manifest, the prompt-mass census baseline,
and the review-bundle budget record). The drift is induced by the loop's own edits, so it is
predictable before the rerun starts; the instruction converts N discover-fix-rerun cycles into one
batched pass plus one re-verify run.

The bytes belong on the **mandatory** path rather than a conditional reference because the
instruction must fire before *every* full-suite re-verify run. A reference file loaded only on a
rare path would be absent at exactly the moment the pass is due, which is the failure mode the
`batched-regeneration: run|refused|skipped` discharge line exists to make auditable.

Every named surface is grown rather than one, because each is the unconditional entry surface of a
distinct loop that induces this drift, and none of them is loaded by the others. In
particular, `/prflow:review-and-fix` cites the receiving-code-review skill by *principles* only —
a prose citation, not a guaranteed skill load — so the receiving-code-review extension alone would
not reach the flagship fix loop.

> **Superseded in part by issue #620** (see `docs/internal/cutovers/issue-620-reception-extension-port.md`).
> Two statements above described the load topology as it stood at this cutover and no longer hold:
> the `receiving-code-review` extension's load condition (the third bullet under **Files**) and the
> "none of them is loaded by the others" premise in the paragraph immediately above. Issue #620 added
> a second `load-prompt-extension.sh` call to the `/prflow:review-and-fix` preamble, so that
> extension now also loads unconditionally on every entry through that preamble — the standalone
> loop, the `/prflow:implement` Phase 3 inline run, and the Step 2.6 shadow entry. The flagship fix
> loop therefore *is* reached by the receiving extension today. The decision recorded here is left
> as written: it was sound on the topology of its time, and this note corrects the premise without
> re-litigating whether the resulting duplication is still wanted.

## Budget renegotiation (review-and-fix initial load)

`.prflow/prompt-extensions/review-and-fix.md` was sitting **six words** below its documented
initial-load ceiling — root 3,213 + extension 2,291 = 5,504 words against a 5,510 ceiling — so
this instruction could not fit under it at any phrasing. The section was
first trimmed to its operative minimum (the invocation, the act-on-the-report rule, the
infrastructure-failure arm, the two-denials degradation, and the discharge line) and only then
was the ceiling renegotiated **5,510 → 5,690**, mirroring the #556 precedent and carrying the
same kind of small headroom over the measured 5,686. `lib/test/run.sh`'s `RAF_LOAD_CEIL` and
every coupled cell in `docs/review-and-fix-budget.md` are updated in this same change; the
growth-delta (+4,323) and net-reduction (32,988) figures are unchanged, because the extension
term appears on both sides of each subtraction and cancels. This artifact is the audited
decision that widening records.

Growth is bounded by design: the sections carry **no artifact inventory**. Enumeration lives
solely in `lib/test/regenerate-artifacts.py`'s registry, so adding a sixth artifact later grows the
helper and not these three mandatory rows. Each section's invocation sentence and discharge-record
line are pinned by `assert_pin_unique` in `lib/test/run.sh`, so the grown bytes cannot silently
disappear from any one surface.
