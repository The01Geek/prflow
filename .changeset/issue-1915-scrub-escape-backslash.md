---
bump: patch
type: Fixed
---

- **The credential scrub no longer corrupts the text around a redacted token.** In
  `scripts/scrub-credentials.sh`, the `Bearer` `Authorization` rule and the `basic`
  `Authorization` rule listed a literal `\` as a member of their token character class, so a
  credential followed by a JSON escape backslash had that backslash swallowed and the
  published execution-transcript artifact stopped parsing. The same two classes also accepted
  a bare `//` as a token, eating the trailing slashes of a recorded
  `sed 's/AUTHORIZATION: basic //'`. Both classes are now `\`-free and carry a four-character
  minimum, so only the credential token is replaced and the bytes around it survive. The
  redacted shapes are unchanged. (#1921)
