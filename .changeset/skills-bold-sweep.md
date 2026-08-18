---
bump: patch
type: Changed
---

- **Stripped ~88% of bold emphasis from the shipped skill prose.** Bold ran at roughly 27 spans per 1,000 words across `skills/**/*.md` (6,385 spans in 83 files), a density at which the marker no longer distinguishes anything; it now sits at 762. The sweep deletes asterisk pairs only — no word, punctuation, or whitespace changed — and retains every literal the suite asserts verbatim, bold inside fenced blocks, table rows and inline code spans, each gated reference's boundary markers, and one or two genuinely destructive-if-ignored rules per file. (#1748)
