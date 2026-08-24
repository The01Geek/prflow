---
bump: patch
type: Fixed
---

- **Harden the CI-derived completion-evidence record and open it to the reception/fix-loop routes.** The `--record-completion-evidence-ci` marker family now carries a `tier` operand (only `local` is accepted; a `cloud` tier is refused, since a cloud run owes an in-environment result) and a set of check-name/conclusion pairs recorded via repeatable `--completion-ci-check NAME CONCLUSION`; the checker refuses a record whose checks do not cover the required-check set declared in `.github/workflows/ci.yml` or that carries a non-success conclusion. `check-completion-evidence.py --context-mode direct` and `--context-mode loop` now reach that validation through a `--ci-record` operand while still running their undischarged-findings and deferral-durability checks, so a reception or fix-loop pass that follows the push-and-read-CI rule can discharge its gate instead of being refused. No verdict token was added or removed. (#1917)
