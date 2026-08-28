---
bump: patch
type: Fixed
---

- **Shipped skill prose no longer states PRFlow-internal instructions a consumer's tree cannot honor.** Removed the `structural-pin-ok` pin-corpus marker syntax and its category list from the shipped pin-corpus paragraphs, replaced the `CLAUDE.md`-content pointers with the claim stated inline, and reworded the weekly-retrospective suite-runtime step so it describes what the step does rather than asserting PRFlow's own suite state. A new module-constant denylist class in `lib/test/lint-shipped-pruned-path.py` (`structural-pin-ok`, `CEILING_TRIPWIRE_FRACTION`, `run-parallel`) reports any such identifier in a `skills/**`/`agents/**` body so the leak cannot return unnoticed. (#2115)
