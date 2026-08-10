---
bump: patch
type: Fixed
---

- **Guard the remaining fixed-arity argument unpacks in `scripts/workpad.py`.** A shared
  `_require_arity()` helper now validates arity before the positional unpack in every
  `update` flag that had a fixed `nargs` but no guard — `--checkpoint`,
  `--scope-decision-deferred`, `--scope-decision-rewritten`, `--rewrite-ac`, and
  `--record-classification`. A programmatic caller passing a wrong-length or bare-string
  element now gets a named `_UpdateError` ("… takes exactly N values …; No PATCH was made.")
  instead of a bare `ValueError`/`IndexError` traceback, and `checkpoint=["k1"]` no longer
  unpacks silently into a corrupt `key='k'` row. (#1523)
