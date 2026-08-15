---
bump: patch
type: Fixed
---

- **Corrected three create-issue contracts that claimed more certainty than their surfaces provided.** A malformed reserved leading dependency heading (a `Dependencies` section spelled at a Markdown level other than two, above `## Problem Statement`) is now reported as malformed rather than read as an empty prerequisite set: the reversible implement preflight returns its `UNAVAILABLE` class naming the canonical `## Dependencies` spelling, and the best-effort native stamp breadcrumbs the malformed heading instead of claiming the issue declared no prerequisites. The `--write-path` contract now states its two layers (optional at the `record-dispatch` CLI boundary, required of the live create-issue caller once bound). The Step 3.5-record entry gate and the Verified-premise unavailable arm now name the in-chat breadcrumb as their observable sink. (#1710)
