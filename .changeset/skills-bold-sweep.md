---
bump: patch
type: Changed
---

- **Stripped ~87% of bold emphasis from the shipped skill prose.** Bold ran at roughly 27 spans per 1,000 words across `skills/**/*.md` — a density at which the marker no longer distinguishes anything — and now sits at 851. The sweep deletes asterisk pairs only: no word, punctuation, or whitespace changed. It retains every literal the suite asserts verbatim, bold inside fenced blocks, table rows and inline code spans, each gated reference's boundary markers, the output-format demonstrations whose bold the surrounding instruction requires, and one or two genuinely destructive-if-ignored rules per file. (#1748)
