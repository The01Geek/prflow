---
bump: patch
---

Extend prompt-extension / skill-body arrival enforcement (issue #1446) beyond the cloud
implement tier to the local/interactive tier and the cloud review/command tier.

- `scripts/prompt-extension-arrival.py` gains a `classify-ladder-output` mode that
  classifies from the delivery ladder's own emitted `PROMPT-EXTENSION-STATUS:` line
  (stdin) by positive signal: `arrived` only on a produced `content-present` status,
  `absent` only on a produced `present-empty` status, and `unestablished` whenever no
  status line was produced at all — a helper denied when invoked by path emits no output,
  so it never reads as arrival.
- `.github/workflows/devflow.yml` gains the pre-agent classify / post-agent reconcile
  job-level pair the implement workflow already carries, reading the extension root from
  the trusted base-ref closure (`DEVFLOW_PROMPT_EXTENSION_ROOT`) rather than the PR-head
  checkout. Because the read-only review/command tier has no implement-style positive-tick
  arrival row, the post-agent step reconciles by the signals it can read at job level — it
  fails closed when the expectation could not be established on a successful run, and blocks
  a clean terminal when the run recorded a non-arrival on the PR. A lost skill body writes
  no such record; that residual stays covered by the pre-agent classify and the agent-side
  forced record.
- The three workpad-less skill bodies (`skills/review`, `skills/review-and-fix`,
  `skills/pr-description`) now force the non-arrival record to a durable surface in a fixed,
  terminating order — workpad, then the pull request, then the run's own output naming the
  record unrecordable.
- `scripts/prompt-extension-arrival.py` is granted in the `command` capability profile (the
  five generated allowlist literals regenerated, `manifest_version` bumped); the read-only
  `review` profile stays unwidened, so a review-tier invocation is denied and classified
  `unestablished` rather than reported as arrival.
