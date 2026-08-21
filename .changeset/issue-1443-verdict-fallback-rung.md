---
bump: patch
---

`lib/fetch-pr-context.sh` now recognises four bot-authored review-verdict shapes its
`Verdict:`-on-a-heading fallback missed, through a third rung consulted only when the
producer marker and that heading grammar both yield nothing. The rung reads only a
`[bot]` author's first 30 lines, skips commented-out, fenced and quoted lines, requires a
verdict anchor on the line it reads or on the heading immediately above it, and
contributes at most one verdict. The emitted
bundle also gains `review_verdict_unparsed_count`, the number of scanned artifacts that
yielded no verdict yet carry an `APPROVE`/`REJECT` token in that window, so an empty
`review_verdicts` no longer means both "no review happened" and "a verdict was posted in a
shape the extractor does not read". The count feeds nothing; `review_reject_outstanding`
is still derived from `review_verdicts` alone.
