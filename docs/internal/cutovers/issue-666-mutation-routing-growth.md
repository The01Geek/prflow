---
schema: 1
kind: growth
---
# Issue #666 — mutation routing growth (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

- `CLAUDE.md`
- `.prflow/prompt-extensions/implement.md`
- `.prflow/prompt-extensions/create-issue.md`

## Justification

- Issue #666 makes the behavioral-fix-pin mutation-check mandate mechanically enforced (a new
  `pin-corpus-lint.py mutation-routing` gate plus a runtime overbreadth guard). The three prose
  files this change grows are mandatory-byte census rows, so recording the new rule in each costs a
  baseline delta and this growth artifact.
- **`CLAUDE.md`** — the behavioral-fix-pin sentence in the wrapped-literal bullet is amended to
  record that the mandate is now enforced and to name the `# structural-pin-ok:` marker and the
  overbreadth guard. This is a `CLAUDE.md` edit the acceptance criteria *require*, so an autonomous
  run makes it directly under the issue-#366 carve-out rather than invoking `revise-claude-md`. It is
  the one repo-wide home every run loads, including cloud `/prflow:review-and-fix`, and it sits under
  no word ceiling — the reason the fix-loop's prose channel is `CLAUDE.md` rather than the
  `review-and-fix` extension (which is a `RAF_LOAD_CEIL`/`RAF_MAXSTEP_CEIL` budget term).
- **`.prflow/prompt-extensions/implement.md`** — the "Behavioral-fix pins — evidence, not
  attestation" section gains a paragraph stating that the mandate is now enforced by the
  `mutation-routing` gate and that a structural pin the change adds must carry the marker. This is the
  operative implement-time policy an autonomous run reads, so the obligation belongs at this execution
  home rather than only in a doc.
- **`.prflow/prompt-extensions/create-issue.md`** — the `#464` mutation-evidence audit dimension
  keeps its surface-presence carve-out and adds the declaration obligation as an **implement-time
  consequence**, phrased so the Step 3.6 auditor does not flag a draft's surface-presence pin for
  lacking a marker no issue draft can carry. Surface-presence pins are the dominant Testing-Strategy
  class, so a mis-phrasing as a drafting requirement would fire on most future drafts; the added
  clause is the smallest form that states the consequence without moving the obligation to issue
  altitude.
- None of the three additions is relocatable to a progressively-loaded reference: each states a rule
  that fires at an authoring/audit decision point the reader reaches directly, and each is the
  smallest conditional that records the new enforcement at the point it gates.
