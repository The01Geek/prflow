---
bump: patch
type: Fixed
---

- **Decode PRFlow local text-file inputs explicitly as UTF-8.** `parse-acs.py --body-file`,
  `workpad.py`'s `_read_section_file` (serving `--replace-plan-file`, `--replace-acs-file`,
  and `--set-reproduction-file`), and `branch-for-issue.py --title-file` now decode with
  `encoding="utf-8"` instead of the ambient locale codec, so non-ASCII issue text (punctuation,
  emoji, non-ASCII identifiers) survives on Windows and a non-ASCII title no longer blocks fresh
  branch creation. Invalid UTF-8 on each reader now exits non-zero with a flag-specific
  diagnostic and no traceback (the workpad path makes no GitHub PATCH), and an AST guard blocks
  new ambient-codec `read_text`/`open` calls in `scripts/*.py`. (#1683)
