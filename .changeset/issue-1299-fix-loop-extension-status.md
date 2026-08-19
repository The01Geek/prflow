---
bump: patch
type: Fixed
---

- **The review engine's consumer prompt-extension load now reports its status.**
  `scripts/load-prompt-extension.sh`, in whole-file mode, emits a
  `load-prompt-extension.sh: PROMPT-EXTENSION-STATUS: content-present|present-empty` line on
  stderr (reusing `scripts/render-prompt-extension.sh`'s status vocabulary), so an absent or
  empty consumer extension is distinguishable from a harness refusal — which produces no
  output at all — instead of being silently indistinguishable from it. The `/prflow:review`
  and `/prflow:review-and-fix` engine ladders now report that token as the extension's
  resolved status, and treat a total absence of the token as `unestablished`, never collapsed
  onto `present-empty`. stdout stays byte-verbatim, so the forwarded extension text is
  unchanged and the phase-3 reviewer's stdout-based classification is preserved by the
  diagnostic `load-prompt-extension.sh: ` prefix. (#1793)
