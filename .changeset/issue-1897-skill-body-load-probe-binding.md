---
bump: patch
---

Harden the issue-#1618 skill-body-load delivery probe so no verdict is silently wrong.
`scripts/skill-body-load-probe-verdict.py` bound a root to the first recorded `Skill` load
whose serialised input merely *contained* the root's bare name, so a session that loaded
`prflow:review-and-fix` before `prflow:review` bound the review root to the wrong load and
answered `unestablished` — the same word the helper uses for a genuine non-measurement.
A root now binds by the name's quoted JSON form, every matching load is collected, and more
than one match answers `unestablished` naming the ambiguity instead of keeping one silently,
which also stops a retried load from being answered from its errored first attempt.
`dirs_match` normalises separators after `normpath` rather than before, so the
component-boundary suffix comparison resolves on a Windows host as it does on a POSIX one;
the no-following-body reason now names the directory it actually compared rather than the
`SKILL.md` path; and the module docstring and the `matcher-probe.yml` comments that described
the `Skill` tool_result as the verdict operand now name the body record following it.
