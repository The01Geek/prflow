---
bump: patch
---

`workpad.py patch` now preserves the leading marker lines a full-body rewrite would otherwise drop. A rewrite composes its bytes from state the caller holds, so a caller that does not retype the run-key marker (`<!-- prflow:review-progress run=… -->`, line 1) or a stamped verdict marker (line 2) silently dropped them — and no consumer errored, because a marker scan that finds nothing reads as "there was no such comment". The helper now reads the live body first and re-inserts any leading marker the composed body omits, keeping the live body's order while letting a marker the caller does supply win for its own kind, so a deliberate re-stamp or `--marker` migration still lands. An unreadable live body degrades to the caller's bytes with a stderr breadcrumb.
