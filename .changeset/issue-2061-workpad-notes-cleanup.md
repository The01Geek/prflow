---
bump: patch
type: Fixed
---

- **Trim boilerplate from the implement run's workpad Notes.** The implement skill no longer
  records a fixed Reflection note naming how it resolved its skill directory, and the branch
  resume pre-check now writes its `resume-precheck:` record to `## Progress` — through a
  written-out command in each recording case — instead of the Reflection block, matching the
  instruction that already called for a `## Progress` note. The reader and the internal docs
  were reconciled to match. (#2062)
