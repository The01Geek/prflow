---
bump: patch
type: Fixed
---

- **Weekly retrospective Step-9 "Analyzed PRs" digest now includes analyst-graded clean PRs.** The
  Step-9 filter is extracted to `lib/analyzed-digest.jq` and widened to select analyst-graded clean
  entries — those with a populated `categories`, `descriptors`, or `suggested_interventions` field —
  alongside `imperfect` and `blocked`, while still excluding gate-skipped clean entries (whose
  analysis fields are empty, from `lib/clean-entry.jq`). Previously an analyst-graded clean PR cost a
  Stage A LLM call and was counted in `analyzed_count` yet was dropped from the digest, so the
  "Analyzed PRs" list under-reported. `lib/compute-patterns.jq` is unchanged, so clean still
  contributes no pattern occurrences. (#1873)
