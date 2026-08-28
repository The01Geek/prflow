---
bump: patch
type: Changed
customer-visible: true
---

- **`/prflow:create-issue` now prints the drafted issue in chat only on request, keeping the
  saved-file path as the default presentation.** Step 4 writes the draft file and shows its path,
  the audit summary, the disclosures and the investigation record first — without the body — and
  the combined decision question carries a new *print the full draft in chat* answer that renders
  the title and body verbatim on demand. A write-failed run, an unbound draft, and a
  non-interactive run still print the body as before. Approval stays explicit and about the exact
  saved bytes. (#2122)
