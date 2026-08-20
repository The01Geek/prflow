---
bump: patch
type: Fixed
---

- **`check-verified-premises.py` grades only real premise quotations and stops reporting clean passes it did not earn.** Text inside backtick code spans is no longer scanned for the premise quotation, so a backticked command's double-quoted argument is not matched as the premise; a blockquote-prefixed `> Verified:` line is now surfaced in the `UNGRADED_CLAIMS` output instead of vanishing into a byte-identical `total=0`; a quotation truncated at an internal `"` is graded `unestablished` with the delimiter rule named rather than `refuted` against the fragment; and a quotation-shape refusal `detail=` (a cited path with no usable premise quotation, and the new truncated-quotation refusal) now states the delimiter-and-floor rule it applied, the eight-character minimum quotation length included. The create-issue premises quality group is updated to match the recognizer and to state that a `Verified:` premise asserts a present-tense fact, with a post-change claim written as an acceptance criterion instead. (#1872)
