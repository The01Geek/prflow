---
bump: patch
type: Changed
---

- **Fold label config resolution and outcome classification into `apply-labels.sh`.** The helper
  gains a `--config-key`/`--config-fallback` config-driven mode (it resolves the label list itself
  through `config-get.sh`), folds per-label creation in (call sites need no separate
  `ensure-label.sh` call), and prints exactly one stdout outcome token — `applied`,
  `nothing-to-apply`, `arg-slip`, `api-failure`, or `config-unreadable` — on every path it runs, so
  call sites route on a token instead of matching English stderr sentences. Every stderr breadcrumb
  is preserved byte-for-byte. `ensure-label.sh` now classifies an already-exists response with a
  bash `case` match instead of `grep`, so a host without `grep` reports the benign already-exists as
  success. The four implement label call sites collapse to a single `apply-labels.sh` invocation
  each, and two stale sentences in the internal docs plus a stale test comment are corrected. (#1936)
