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
- **`prompt-surface-growth.py` now reports a before-size and a percentage delta.** The table
  printed only `Δ bytes` and `Bytes at HEAD`, so a reader could not judge whether a delta was
  large without the before-size the helper had already computed and discarded. It now renders
  `Path | Before | After | Δ bytes | Δ %`, with `n/a` as the percentage for a file added on the
  branch, where a zero denominator would otherwise fabricate one. (#1716)
