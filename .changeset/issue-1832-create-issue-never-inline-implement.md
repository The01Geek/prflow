---
bump: patch
type: Fixed
---

- **Forbid `/prflow:create-issue`'s closing step from starting implementation inline.** Step 4 sub-step 6 of `skills/create-issue/references/step-4-present-create.md` specified only the trigger-comment post mechanism and never stated what the run must not do instead, so a spent-context run could offer to implement inline. The offered and withheld arms now both state that the closing offer is only ever to post the trigger comment and that the run never starts implementation itself (because implement must begin in a fresh-context agent); the *cloud implement tier disabled or unconfigured* withheld arm additionally tells the user to start `/prflow:implement` in a fresh session; and invariant 5 of the non-degradable invariants block in `skills/create-issue/SKILL.md` carries the same rule so it survives context compaction. (#1867)
