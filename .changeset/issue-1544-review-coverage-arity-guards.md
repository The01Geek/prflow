---
bump: patch
type: Fixed
---

- **Route the two review-coverage arity guards in `scripts/workpad.py` through `_require_arity`.** The `--record-review-coverage` and `--review-coverage-disposition` operand-arity checks were bare `len()` tests that let a bare `str` of the right character count slip through and unpack character-wise, producing a misleading `unknown coverage value` / `unknown gap` refusal instead of naming the non-sequence. Both now call `_require_arity`, which rejects the non-sequence explicitly; the refusal messages are byte-identical for the count-mismatch case. (#1547)
