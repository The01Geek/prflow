---
bump: patch
type: Fixed
---

- **The implement completion gate now requires the declared verification command to be a
  whole-suite result.** `scripts/check-completion-evidence.py` enforced only that
  `suite_summary.command` was a nonempty string, so a lint invocation satisfied the gate: a
  cloud implement run reached `Complete` and published its PR having run no test suite,
  declaring `git ls-files '*.py' | xargs python3 -m ruff check`. The command must now invoke
  the serial full suite, the shard coordinator, or a `--require-shards`-reconciled
  recombination; a focused module, a single shard, a lint and an unreconciled combine are all
  refused as `missing-evidence`. The writer is deliberately unchanged — flights coordinate
  focused and shard runs too, so only the completion gate requires a whole-suite result.
- **`verification-flight.py finish` gained `--from-runner-log`.** Terminal evidence can now be
  derived from the log a runner retained instead of hand-authoring a `--summary-file`, which
  is the improvisation that produced the bypass above. The log's own verdict decides the
  result, so a `--result passed` over a log reporting `aggregate FAILED` is refused
  non-terminally, leaving the flight running and re-finishable.
