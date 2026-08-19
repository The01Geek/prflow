# Terminal-result classifier contract module inventory

This inventory records the provenance of the focused terminal-result classifier module
(issue #1273). It is a navigation aid, not a second source of behavior:
`terminal-result-class.sh` owns the executable assertions, and the complete suite calls
the same module through `module-harness.sh`'s `devflow_run_full_suite_module` boundary.
The `lib/test/run.sh` call site is registered under the `#1273 terminal-result
classifier + generated total table` box comment.

Source baseline: this is a **new module authored for issue #1273**, not an extraction
from `lib/test/run.sh` — the classifier it exercises (`scripts/terminal-result-class.sh`)
and its generated total mapping table (`lib/terminal-result-table.tsv`, produced by the
independent Python oracle `lib/generate-terminal-result-table.py`) are new in the same
change, so there was no prior in-`run.sh` section to carry forward. No sibling candidate
was left behind in `lib/test/run.sh`.

Its assertion floor is recorded once, in
`scripts/workflow-flight-recorder-registry.json`, and enforced on every run by
`lib/test/run-module.sh`; `test_module_runner.py` reconciles that floor against the
`lib/test/run.sh` call-site literal. This inventory deliberately states no exact
assertion count — the registry is the single source, so a count copied here could drift
out of it silently.

Every assertion is behavioural: `scripts/terminal-result-class.sh` is driven per row of
the generated total table and per acceptance criterion, judged on the classifier's stdout
token and its usage/arity exit code. There is no wording-only pin here (issues
#375/#666/#810).

| Contract group | Acceptance criterion | Representative contract |
| --- | --- | --- |
| Generated total table (drift) | implement/review closed sets | the bash classifier's live output equals every row of `lib/terminal-result-table.tsv` (the Python oracle's independent computation) for both the terminal class and the conclusion mapping |
| Totality | implement/review closed sets | the emitted row counts equal the fixed products (10 workpad classes × 4 job statuses = 40; 18-entry review vocabulary), so a shrunk vocabulary is a missing row |
| Implement hand oracle | canonical-only complete/blocked; every other token → incomplete; job cancellation over a stale complete token → incomplete; is_error/exit/progress never satisfy the gate | per-token stdout assertions against hand-written expected values |
| Review hand oracle | the six exact POSTED literals → verdict-posted; every SKIP/FAILED/blank/unknown/NOT-REACHED/UNESTABLISHED/REACHED-prefixed → incomplete; trailing-CR trimmed, leading whitespace not | per-literal stdout assertions |
| Conclusion matrix | complete/verdict-posted → success; blocked/incomplete/unknown → non-success (fail closed) | conclusion-mode stdout assertions |
| Usage / arity guard | — | a missing operand or unknown mode exits 2 (an absent operand is not an empty-string operand) |
