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
  The classifier reads the invocation's environment prefix rather than discarding it, so
  `DEVFLOW_SKIP_SUITE_MODULES=1 DEVFLOW_SKIP_PYTHON_POOL=1 lib/test/run.sh` — verbatim what
  the `monolith` shard runs — is refused like the shard it is, as are the non-executing
  `--preflight` and `--list-shards` forms.
- **`verification-flight.py finish` gained `--from-runner-log`.** Terminal evidence can now be
  derived from the log a runner retained instead of hand-authoring a `--summary-file`, which
  is the improvisation that produced the bypass above. The log's own verdict decides the
  result, so a `--result passed` over a log reporting `aggregate FAILED` is refused
  non-terminally, leaving the flight running and re-finishable.
- **The runners now retain a log this mode can actually read.** `lib/test/run-parallel.sh`
  writes its terminal block — the recombined tally, the elapsed line and the `aggregate`
  verdict on both the passing and the failing path — to a `retained coordinator log` file it
  names on exit, where before the verdict existed only on the console and `retained logs:`
  named a directory. `lib/test/run-shard.sh` appends its `retained log:` marker into the log
  it names rather than printing it afterwards, and `lib/test/run.sh` self-identifies as the
  serial driver together with the two population selectors it ran under, so a reduced-population
  run is not read as the full serial suite. The derivation attributes a log to its OUTERMOST
  runner, reads each runner's own authoritative tally rather than the last bare tally in the
  capture, carries a module log's `K skipped` and each skip's `[kind]` into `skipped_checks`,
  ignores `summary.sh`'s parenthesised itemization-failure placeholders, and names a
  stdout-only coordinator capture as `runner_log_no_aggregate` rather than as unrecognized.
