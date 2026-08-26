# Development and testing

<!-- verified-against: 26c9ad96d 2026-08-25 -->

This page explains how to develop and verify changes in the PRFlow repository itself: which test commands exist, which one to use when, and which signal counts as the completion gate. It is for a contributor or coding agent working in this checkout.

## Current behavior

- `lib/test/run.sh` is the complete suite as one serial process: jq filters, shell helpers, and the Python suites, with `gh` stubbed so no network or auth is needed. It reports three tallies — passed, failed, and skipped — and a skipped check is never a clean pass.
- `lib/test/run-parallel.sh` runs the same suite as CI's shard partition, concurrently in this checkout, and recombines the tallies through `lib/test/shard-tally.py`. `lib/test/run-shard.sh --list-shards` names the shard population, and `lib/test/run-shard.sh <shard>` runs one shard.
- `lib/test/run-module.sh <module-id>` runs one registered focused module. `lib/test/modules/coverage-map.json` records which module (or which focused `lib/test/test_*.py` file) covers each `lib/` and `scripts/` unit, and `scripts/workflow-flight-recorder-registry.json` registers the module ids.
- Focused runs are the iteration default; the whole-suite completion gate is tier-scoped. In this repository a local/interactive run discharges it by pushing and reading CI for the pushed commit, while a cloud implement run verifies in its own environment. `CLAUDE.md`'s tier ladder is the single home of that policy.
- Lint commands: `shellcheck` over the tracked `.sh` set (with `lib/test/run.sh` needing ShellCheck ≥ 0.10.0 and `--extended-analysis=false`), `ruff check` over the tracked `.py` set, and `actionlint` over the workflows. CI runs them in the `lint` job.
- CI (`.github/workflows/ci.yml`) runs the suite and lint on every pull request. The GitHub branch-protection required status check is the job named `lib + python tests`; the completion-evidence set a local run must read also includes `lint (shellcheck + actionlint + ruff)` — the jobs marked `# prflow:required-check` in `ci.yml`.
- Test fixtures live under `lib/test/fixtures/` (deliberately malformed inputs, `gh` stubs, and probe captures), and focused modules under `lib/test/modules/` with a provenance inventory file per module.
- Probe conventions — how rendered-output and environment probes are written so they stay stable across hosts — are collected in [`docs/internal/test-suite-probe-conventions.md`](../test-suite-probe-conventions.md).

## Why it works this way

- The suite is `gh`-stubbed and network-free so a red result always means a code defect, never a credential or rate-limit accident.
- The local completion gate reads CI rather than a local full-suite pass because local full runs are slow, contend with sibling worktrees, and can disagree with the merge-gating signal in both directions; the derivation is in [`docs/internal/claude-md-tiered-suite-rationale.md`](../claude-md-tiered-suite-rationale.md).
- Focused modules exist so iteration on one surface does not pay the whole suite's runtime.

## Boundaries and failure paths

- A skipped check is reported with a kind (`blocking-gate` or `host-capability`) and is not laundered into a pass; a module run through `lib/test/run-module.sh` may not self-skip at all.
- Never run the suite backgrounded with a bare `&` — the child inherits an ignored SIGINT and the signal-trap assertions fail; `python3 lib/test/launch-detached.py <suite command>` is the sanctioned backgrounded launch.
- Stop a suite process by its recorded PID, never by a `pkill -f` pattern — sibling worktrees run the same command names.
- A local red that CI does not reproduce is uncharacterised, not explained; there is no known-flake set.

## Source of truth

- `CLAUDE.md` — the Commands section and the tier ladder are the operative suite-running policy.
- `lib/test/run.sh`, `lib/test/run-parallel.sh`, `lib/test/run-shard.sh`, `lib/test/run-module.sh` — the executable runners.
- `lib/test/modules/coverage-map.json` and `scripts/workflow-flight-recorder-registry.json` — module ownership and registration.
- `.github/workflows/ci.yml` — the CI jobs and the `# prflow:required-check` markers.
- `CONTRIBUTING.md` — the module-authoring checklist and pin-retirement rules.

## Related topics

- [Verification policy](verification-policy.md)
- [Command permissions](command-permissions.md)
- [Working directory](working-directory.md)
