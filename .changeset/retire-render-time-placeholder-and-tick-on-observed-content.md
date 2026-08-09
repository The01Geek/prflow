---
bump: patch
---

Remove the render-time prompt-extension placeholder from the last four call sites
(`skills/implement/SKILL.md`, `skills/review-and-fix/SKILL.md` — both blocks — and
`skills/pr-description/SKILL.md`), completing what PR #1471 began for
`skills/review/SKILL.md`. A `Skill`-tool load of a body carrying a placeholder fails
outright, returning a permission-refusal string and no skill body at all (run
`31287654057`), and issue #1462 had already made the `load-prompt-extension.sh` ladder
unconditional, so the placeholder was redundant where it worked and fatal where it did
not. The surrounding routing prose is reconciled to the single remaining channel at
every site, and the ladder itself is byte-identical.

Amend the implement Extension-row tick rule so a `prompt extension resolved: …` row is
ticked on **observed content** rather than a zero exit status: the ladder's full output
must have reached the run, and the ladder is emitted with no `>/dev/null` and no
`| head -<n>`. Run `31287654057` ticked the row off `exit=0` from a command that
discarded one arm and truncated the other to three lines of a 341-line extension.
