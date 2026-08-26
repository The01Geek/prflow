---
schema: 1
kind: growth
---
# Issue #729 — declared dimension keys growth (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

Two **mandatory** rows grow in this diff (issue #729, PR #732):

- `skills/create-issue/references/step-3-6-audit.md` — group `create-issue-flow`,
  +295 bytes (74,465 → 74,760).
- `.prflow/prompt-extensions/create-issue.md` — group `extensions`, +451 bytes
  (23,419 → 23,870).

`skills/create-issue/references/audit-prompt-template.md` also grows (+2,941 bytes,
18,826 → 21,767), but its row is class `reference` (`conditional-references`), so it
is untolled by the Review gate and is recorded here only so the baseline diff reads
completely.

No mandatory row shrinks, and no ownership transfers — this is additive prose plus
machine-read declaration lines, not a cutover.

## Justification

**`step-3-6-audit.md` (+295 bytes) — a new degraded-arm route that would otherwise
have no rule.** This change makes `render-audit-prompt.py enumerate-dimensions` able
to exit non-zero on a malformed dim-key declaration — including one in the
*consumer's* own `.prflow/prompt-extensions/create-issue.md`, a file this repo does
not author. Step 3.6's degraded ladder previously named exactly two triggers (an
`unestablished` `render-status:`, and a keyset divergence). A non-zero exit produces
**no `render-status:` line at all**, so it matched neither, and the orchestrator would
have had no documented behavior for a failure mode this change newly introduces — the
whole #708 per-dimension coverage mechanism silently disabled by a typo in an optional
marker. The added sentence routes that outcome to `--render degraded` and records the
helper's stderr. These bytes are a *stop condition an agent must act on*, which the
Prose cutover policy names as a retained category that stays on the mandatory path.

**`.prflow/prompt-extensions/create-issue.md` (+451 bytes) — nine
`<!-- dim-key: … -->` declaration lines, one per audit dimension.** These are
machine-read identity data, not instruction prose: the renderer strips every one of
them before the text reaches an auditor's context, so the *rendered* prompt mass is
byte-for-byte unchanged (verified — every render mode is byte-identical to the
pre-change output). They are on the mandatory path only because the census measures
the file on disk, not the rendered projection. Without them this repo's own nine
consumer dimensions keep deriving their coverage keys from bold leads that embed issue
numbers (`c:cloud-allowlist-skew-issue-363`), so editing an issue reference out of a
heading would rekey a dimension the state owner has already recorded durably — exactly
the defect #729 exists to remove, left in place on the one file the change is about.
