---
bump: patch
type: Fixed
---

- **Close two Windows-only failures in the Python helper floor.** Every tracked
  `scripts/*.py` and `lib/*.py` command now forces stdout/stderr to UTF-8 on its
  entry path, so a non-UTF-8 default codec (e.g. Windows cp1252) no longer crashes a
  helper that prints an em-dash or emoji; a new guard in `lib/test/test_python_scripts.py`
  derives its checked file list from the repository index, so a newly added helper is
  covered without editing the test. `scripts/render-audit-prompt.py`'s `_abs_path`
  argument check now accepts any path its interpreter reports as absolute — including a
  Windows drive-letter path in either the forward-slash or backslash spelling — and
  returns it unchanged, unblocking the issue-audit step on Windows. On Linux and macOS
  the behavior is unchanged. (#1764)
