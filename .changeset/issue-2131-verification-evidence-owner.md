---
bump: patch
---

`scripts/workpad.py update` gains `--record-verification-evidence`, which owns the
`Verification evidence:` completion-evidence record's field set. The caller supplies
`--command`, `--outcome`, and `--run-root` (required; `--run-root` repeatable, with the
literal `none` for a denied or ceiling-terminated launch), plus optional `--tallies`,
`--elapsed`, and `--started-at`; the tool stamps `recorded-at` (UTC) and the full
40-character `head` from `git rev-parse HEAD` (`unestablished` when git cannot answer).
It refuses, before any PATCH, a call missing a required field or one whose `--outcome`
names an aggregate result while `--run-root` is `none`, and appends one note-kind
reflection row per launch. `--record-completion-evidence-ci` now appends the same row
from its validated operands, so a local CI reading has one producer. The option's
`--help` is the field set's single source; CLAUDE.md, the implement skill, the implement
prompt extension, and the internal docs point at it instead of re-listing the fields.
