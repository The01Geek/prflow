---
bump: patch
type: Fixed
---

- **The credential scrub no longer eats the JSON escape backslash after a redacted token.** In
  `scripts/scrub-credentials.sh`, the `Bearer` `Authorization` rule and the `basic`
  `Authorization` rule listed a literal `\` as a member of their token character class, so a
  credential followed by a JSON escape backslash had that backslash swallowed, ending the string
  early and leaving the published execution-transcript artifact unparseable. A token is now
  matched as a run of class members plus the two escape units `\/` and `\\`, so an escaped slash
  inside a token is still redacted while a lone `\` before a closing quote is left to the document
  it belongs to. A four-unit floor replaces the old `+`, so the bare `//` of a recorded
  `sed 's/AUTHORIZATION: basic //'` is no longer taken for a token; a run shorter than four units
  after the scheme keyword is left alone, which is a deliberate narrowing of what the two
  `Authorization` rules redact. Each now matches its scheme keyword
  case-insensitively per letter, as they already matched the header name, so a third-party
  emitter's `AUTHORIZATION: BASIC` is redacted rather than passing through; the scheme keyword is
  rewritten to its canonical casing alongside the token, as before. (#1921)
