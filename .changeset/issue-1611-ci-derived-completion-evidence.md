---
bump: patch
type: Added
---

- **Accept a CI-derived completion-evidence record at the terminal `--status Complete` gate.**
  `workpad.py` gains a second completion-evidence marker family (`completion-ci:`) written by
  a new `--record-completion-evidence-ci <head-sha> <check-name> <conclusion> <run-url>` flag
  and validated offline (no network, no `gh`) by `check-completion-evidence.py`'s new
  `validate_implement_completion_ci`, so a local/interactive implement run that established a
  green required check for the commit it pushed (issue #1607's tier ladder) can finalize
  without running a suite the ladder does not gate on or misdescribing what it verified. Exactly
  one completion-evidence marker is required across both families together; the in-environment
  verification-flight path is unchanged, and a consumer repository's run — which never produces
  the new marker — is behaviourally unchanged. (#1619)
