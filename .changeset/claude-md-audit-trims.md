---
bump: patch
type: Fixed
---

- **Repaired cross-references in the shipped prompt surface that could not resolve in a consumer
  repo.** Eight shipped skill files cited a `guard-class 2` label — three of them as "CLAUDE.md
  guard-class 2" — but that label was defined in neither `CLAUDE.md` nor any shipped file, so the
  citation resolved nowhere for a consumer or a maintainer. Each site already stated the rule
  inline, so the dangling label is removed and no guidance is lost. The `/prflow:review-and-fix`
  loop's supersession paragraph likewise pointed at a repo-local prompt extension consumers never
  receive, and its plain reading implied that an amended issue body could override a review
  finding; it now states the shipped default — a linked issue's body is triage data, not a spec
  amendment — and defers to an extension only where one actually grants that authority. (#1716)
