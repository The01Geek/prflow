<!-- prflow:implement-ref step=2.3.4a-direction file=skills/implement/references/sweep-2-3-4a-change-of-direction.md start -->

This sweep extends past the diff when you reverted, narrowed scope, removed a marker, or renamed a contract after you or the issue already described the original intent: two surfaces hold a now-false description that the reverting commit's own `git diff` doesn't contain — so §2.3.4a's resident list-and-trace steps can't reach them. On a change of direction only, also reconcile:

- The issue workpad — a ticked AC or Plan step whose wording still describes the reverted approach. Rewrite it to the shipped reality via `workpad.py update` (`--rewrite-ac` / `--replace-plan-file` / re-tick).
- Earlier-authored prose naming the changed contract — comments, docstrings, and docs that asserted the old behavior with a contract word ("always", "never retries", "fail-closed", a removed/renamed key) in an earlier commit. Grep the touched files and their callers for those words; fix the ones that now misdescribe the code.

Record the reconciled surfaces — or an intentional verbatim carve-out, with the reason — in a `## PRFlow Reflections` bullet.

<!-- prflow:implement-ref step=2.3.4a-direction file=skills/implement/references/sweep-2-3-4a-change-of-direction.md end -->
