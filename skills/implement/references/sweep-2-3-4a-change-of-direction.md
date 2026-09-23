<!-- prflow:implement-ref step=2.3.4a-direction file=skills/implement/references/sweep-2-3-4a-change-of-direction.md start -->

This sweep extends past the diff when you reverted, narrowed scope, removed a marker, or renamed a contract after you or the issue already described the original intent: the surfaces below hold a now-false description that the reverting commit's own `git diff` doesn't contain — so §2.3.4a's resident list-and-trace steps can't reach them. On a change of direction only, also reconcile before requesting review:

- The issue workpad — a ticked AC or Plan step whose wording still describes the reverted approach. Rewrite it to the shipped reality via `workpad.py update` (`--rewrite-ac` / `--replace-plan-file` / re-tick). A `--rewrite-ac` follows `<skill-dir>/references/phase-2-2-6-ac-plan-reconciliation.md`, read here unless this run already did.
- Earlier-authored prose naming the changed contract — comments, docstrings, and docs that asserted the old behavior with a contract word ("always", "never retries", "fail-closed", a removed/renamed key) in an earlier commit. Grep the touched files and their callers for those words; fix the ones that now misdescribe the code.
- The changeset or release-note entry — a sentence still announcing deferred or reverted work as shipped. Rewrite it to the shipped scope.
- CLI and argparse help text — a `--help` string or argument description written from the earlier plan. Rewrite it to the shipped behavior.

Record the reconciled surfaces — or an intentional verbatim carve-out, with the reason — in a `## PRFlow Reflections` bullet.

<!-- prflow:implement-ref step=2.3.4a-direction file=skills/implement/references/sweep-2-3-4a-change-of-direction.md end -->
