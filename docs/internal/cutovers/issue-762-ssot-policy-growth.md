---
schema: 1
kind: growth
---
# Issue #762 — ssot policy growth (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

- `CLAUDE.md`
- `skills/retrospective-audit/SKILL.md`

## Justification

- Issue #762 adopts a go-forward single-source-of-truth documentation/contract policy and
  redirects the retrospective remedy heuristic toward collapsing drift/desync/coupled-mirror
  root causes to a single canonical source. Both edited files are mandatory-byte census rows, so
  recording the new policy and the remedy-preference costs a baseline delta and this growth
  artifact. Both rows move the same direction (growth: `CLAUDE.md` +1896 bytes,
  `skills/retrospective-audit/SKILL.md` +390 bytes), so one `growth` artifact covers both.
- **`CLAUDE.md`** — the "Changing one site of a coupled invariant?" convention bullet is rewritten
  in place to a go-forward SSOT policy: the canonical statement is stated in go-forward normative
  terms (scoped to the new fact under introduction and to migrated content, never a present-tense
  universal over the current tree), and it enumerates two populations — permanent exceptions and a
  non-exhaustive existing-required-copy backlog — both of which stay under the coupled-invariant
  same-commit reconciliation discipline. The net growth is the go-forward framing plus the
  two-population enumeration, which the issue itself frames as a day-one slight growth of always-on
  memory (the substantial slimming is a follow-up word-budget-retirement ticket, out of scope
  here). This is a `CLAUDE.md` edit the acceptance criteria *require*, so the autonomous run makes
  it directly under the issue-#366 carve-out rather than invoking `revise-claude-md`. The bullet is
  the single canonical home of the policy; no `docs/` page copies it, so no pointer update is owed.
  The growth also raised the `CLAUDEMD_WORD_CEIL` ratchet in `lib/test/run.sh` to the measured
  post-rewrite word count (an audited raise recorded in the PR body).
- **`skills/retrospective-audit/SKILL.md`** — § 2 ("Pick the proposed change") gains one
  unconditional consideration on its proposal-*selection* step (the "highest-leverage,
  smallest-blast-radius single concrete change" sentence), stating that when the re-derived root
  cause is a drift/desync/coupled-mirror class the higher-leverage proposal collapses to a single
  canonical source rather than adding a new pin + mirror. It is homed at the selection step (not the
  conflict-gated "Conflict check" paragraph, which would no-op on a drift defect that contradicts no
  existing rule, and not § 1, which routes nowhere) so it fires on every proposal. The prose ships
  to consumer repos with the skill, so it is repo-agnostic (no PRFlow-internal paths, no
  `lib/test/run.sh`, no `CLAUDE.md`-specific references). The obligation belongs at this execution
  home — the point where the fix shape is actually chosen — rather than in a doc.
- Neither addition is relocatable to a progressively-loaded reference: the `CLAUDE.md` policy is
  load-bearing on every edit the repo makes, and the remedy-preference must be resident in the
  always-loaded § 2 selection step the audit subagent reaches directly. Each is the smallest form
  that records the new policy at the point it gates.
