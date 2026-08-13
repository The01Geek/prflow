---
bump: patch
type: Added
---

- **Let an issue declare that no documentation is needed without creating work.** The `Documentation Needed` block extractor (`scripts/extract-doc-needed-paths.sh`) now recognizes a standalone `none` as the block's first content token — exactly `none` (case-insensitive) plus at most one terminator from `,.;:`, or `none` standing alone — and emits no deliverables for that block, so a writer can explain why a page needs no change (and name it) without turning it into a mandatory deliverable. The match is a whole-token literal, so an ordinary sentence opening `None of these …` still extracts its paths. (#1666)
