## Problem Statement

The retrospective loop's cheap gate decides which merged PRs get expensive LLM analysis. One of its inputs, `ci_failures_during_pr`, is wrong in both directions: it counts superseded CI runs as failures, and it silently truncates at 30 check-runs. Maintainers running `/prflow:retrospective-weekly` therefore pay for LLM analysis on PRs that were never broken, while a PR with a large CI matrix and a genuine failure can slip through the gate as clean.

## Current Behavior

`lib/fetch-pr-context.sh` derives the signal from a single unpaginated check-runs call filtered by a jq denylist.

Verified: `lib/fetch-pr-context.sh` contains the line ``_CI_RUNS_JSON="$("$DEVFLOW_GH" api "repos/${REPO}/commits/${HEAD_SHA}/check-runs" 2>&1)"`` — no `--paginate`.

Verified: `lib/fetch-pr-context.sh` contains the filter `[.check_runs[] | select(.conclusion != null and .conclusion != "success" and .conclusion != "neutral" and .conclusion != "skipped")] | length`.

Two independent defects follow.

**(a) Superseded runs count as failures.** The denylist leaves `cancelled` and `stale` counted. In this repo a new push cancels the in-flight CI run by design, so ordinary iteration manufactures "CI failures". PR 1282 reports `ci_failures_during_pr: 7`; a live check-run query on its head returned `cancelled` 6, `failure` 1, `skipped` 3, `success` 11 — six of the seven are superseded runs, not defects.

**(b) The read is unpaginated.** `/commits/{sha}/check-runs` serves only the first 30 check-runs per page, so a head with a larger CI matrix is silently truncated and the same field *under*counts real failures.

Verified: `scripts/build-experiment-records.py` documents the same endpoint's behavior in the comment "Paginate: /commits/{sha}/check-runs serves only the first 30 check-runs per page".

Both defects reach the gate's clean decision.

Verified: `lib/cheap-gate.jq` contains the line `elif $s.ci_failures_during_pr   > 0             then { clean: false, reason: "CI failures during PR" }`.

Blast radius for (a) is small — 8 of 232 recorded PRs (3%) have `ci_failures_during_pr > 0` — but those are exactly the PRs the gate acts on.

## Desired Behavior

`ci_failures_during_pr` counts only check-run conclusions that represent a real red signal on the head SHA, read across every page of the endpoint.

- `cancelled` and `stale` no longer count: both mean "superseded, never produced a verdict".
- `failure`, `timed_out` and `action_required` still count. A timeout is a real red signal — this repo has genuine execution-ceiling terminations — and `action_required` is an unaddressed check.
- The filter stays a **denylist**, not a failure allowlist, so an unrecognised future conclusion counts as a failure. The signal's stated posture is fail-safe; an allowlist would silently count an unknown conclusion as success and fail open.
- A multi-page head yields the count over all pages and does not set `ci_status_unknown`.
- The existing fail-safe arms are unchanged.

## User Impact

Maintainers running the weekly retrospective stop burning LLM analysis budget on PRs whose only "failures" were superseded runs, and stop having genuinely-failing large-matrix PRs routed past the gate as clean.

## Technical Context

> **Scope note:** The files and details below are the known starting points, not the full list. Before implementing, trace the change through the codebase to find every affected call site, consumer, and layer — this issue maps the work, it does not bound it.

- **Relevant Classes/Files** — `lib/fetch-pr-context.sh`, the `ci_failures_during_pr + ci_status_unknown` block (the `_CI_RUNS_JSON` fetch and the `_CI_COUNT` jq); `lib/cheap-gate.jq`'s signal-header comment and its clean-decision chain; `skills/retrospective/SKILL.md`'s signal table; `lib/test/run.sh`'s `fetch-pr-context.sh` block and `lib/test/fixtures/gh-stub.sh`.
- **Documentation Drift** — `lib/cheap-gate.jq`'s header describes the signal as "CI runs that failed while the PR was open" and `skills/retrospective/SKILL.md`'s table row reads "Non-success check-runs on the head SHA". Both become inaccurate under the new semantics and are part of this change.
- **Architecture Alignment** — `scripts/build-experiment-records.py` already performs a shape-tolerant paginated merge over this exact endpoint; this change mirrors that handling in shell/jq.
- **Dependencies** — the GitHub REST check-runs endpoint, read through `lib/resolve-gh.sh`'s resolved `gh`, filtered through `lib/resolve-jq.sh`'s resolved `jq`.
- **Data/Schema Considerations** — `.prflow/learnings/*.jsonl` records are past-time snapshots of what was measured then; the signal is recomputed live at scan time, so no backfill is performed and no recorded learning is rewritten.
- **Cross-layer Impact** — the retrospective scan path only: signal derivation (`lib/fetch-pr-context.sh`) and its single consumer chain (`lib/cheap-gate.jq`, the retrospective skill's documented signal table).

Deduping re-run attempts to the latest per check name is **not** part of this change. A check that failed and was re-run green leaves both attempts on the head SHA and the count includes the superseded attempt — the same class of inflation by a different route, but it needs a rule for identifying the latest attempt per check name and new fixture shapes. It is out of scope here and is **not** currently tracked by any open issue; file one separately if it is wanted.

## Acceptance Criteria

The value-comparison rule is discharged for the whole set below by the verified filter and endpoint quotes in *Current Behavior*: every conclusion literal named is the string GitHub's check-runs API emits in the `conclusion` field, and every count assertion is over the integer `ci_failures_during_pr` written into the signals object.

- [ ] On a check-runs payload containing `cancelled` and `stale` conclusions alongside `success`, `neutral` and `skipped`, `ci_failures_during_pr` is `0` and `ci_status_unknown` is `false`.
- [ ] A payload containing `failure` increments the count; one containing `timed_out` increments the count; one containing `action_required` increments the count.
- [ ] A conclusion string in none of the recognised sets — an unrecognised value, including one GitHub introduces later — increments the count, so the denylist fails closed.
- [ ] A check-run with `conclusion: null` does not increment the count.
- [ ] For a head whose check-runs span more than one API page, `ci_failures_during_pr` counts the qualifying runs from every page, and `ci_status_unknown` is `false`.
- [ ] Each of the three fail-safe *conditions* still sets `ci_status_unknown=true` and `ci_failures_during_pr=1`: a non-zero `gh` exit, an empty response body, and a count that does not match the existing `^[0-9]+$` guard. Exactly these three — complete by construction, per the block today, where the first two share one `if` arm and the guard is the second arm.
- [ ] No file under `.prflow/learnings/` is modified by the change.
- [ ] `lib/cheap-gate.jq`'s signal-header description of `ci_failures_during_pr` and `skills/retrospective/SKILL.md`'s signal-table row for it both state the new semantics after the change.
- [ ] The whole suite is green with no new skipped checks, established by whichever signal the running tier's whole-suite gate takes (issue #1607): on the cloud implement tier a `lib/test/run-parallel.sh` result read from its aggregate line and skip tally, or the recombined complete shard partition; on the local/interactive tier the CI reading of `lib + python tests` for the commit the run pushed.

## Implementation Notes

- **Approach** — keep the single derivation block and its fail-safe arms; widen the jq denylist to also exclude `cancelled` and `stale`, and make the fetch paginated with a page-shape-tolerant merge before the filter runs.

  The pagination change is not a one-flag change. With `--paginate` this endpoint returns one `{check_runs:[…]}` object per page, *concatenated* — not a merged array. The current filter runs once per input, so it would emit one length per line; `_CI_COUNT` then fails the `^[0-9]+$` guard and every multi-page PR silently flips to `ci_status_unknown=true` / `CI_FAILURES=1`, making the bug worse. The filter therefore merges across page shapes before counting — `jq -n` over `inputs`, collecting `check_runs` from every page object — matching the merge `scripts/build-experiment-records.py` already performs for the same endpoint.

- **Relevant files** — at minimum `lib/fetch-pr-context.sh` (the `_CI_RUNS_JSON` fetch and the `_CI_COUNT` filter), `lib/cheap-gate.jq` (signal-header comment), `skills/retrospective/SKILL.md` (signal table row), `lib/test/run.sh` (the `fetch-pr-context.sh` assertion block) and `lib/test/fixtures/gh-stub.sh` (new check-runs fixture shapes). This likely also touches a `.changeset/*.md` entry, per the repo's versioning convention.

- **Code Patterns** — `scripts/build-experiment-records.py`'s paginated check-runs read and its shape-tolerant merge across page objects; the surrounding fail-safe idiom already in `lib/fetch-pr-context.sh` (capture, exit-code check, empty-body check, numeric-guard check); `lib/resolve-gh.sh` / `lib/resolve-jq.sh` for binary resolution, which the block already uses.

- **Testing Strategy**

  **Move 1 — test boundary.** An automated boundary exists: `lib/fetch-pr-context.sh` is a CLI emitting a JSON signals object, driven in the suite against `lib/test/fixtures/gh-stub.sh`. The level is the existing script-level contract test in `lib/test/run.sh` — assert the emitted `ci_failures_during_pr` / `ci_status_unknown` values for stubbed payloads. `lib/fetch-pr-context.sh` has **no entry at all** in `lib/test/modules/coverage-map.json` (verified against `origin/main`), so it is exempt from the focused-first precondition on the no-coverage-map-entry ground, its assertions are `run.sh`-resident, and the covering mid-iteration run is `lib/test/run-shard.sh monolith`.

  **Move 2 — coverage dimensions.**
  - *Happy path* — a mixed payload of `success`/`neutral`/`skipped`/`cancelled`/`stale` yields `0`; a payload with one `failure` yields `1`.
  - *Boundary & degenerate* — an empty `check_runs` array yields `0`; a single-element array; a payload whose every run is `conclusion: null`.
  - *Error & failure paths* — the three fail-safe arms, each asserted for both `ci_status_unknown=true` and `ci_failures_during_pr=1`: `gh` exiting non-zero, an empty body, and a body whose filter output is non-numeric.
  - *Adversarial / malformed input* — a body that is not JSON at all; a body that is valid JSON with no `check_runs` key; a `check_runs` value that is a scalar rather than an array. Each must land on a fail-safe arm rather than detonating the filter or emitting a non-numeric signal.
  - *Multiplicity* — a two-page concatenated stub response, with a qualifying failure on page 2 only, asserting the count sees it and `ci_status_unknown` stays `false`.
  - *State/idempotency, scale, security* — dropped: the derivation is a pure read with no state, no AC implies a performance property, and it crosses no access boundary beyond the already-resolved `gh` token.

  **Move 2a — governing conventions consulted:** `CLAUDE.md` (the best-effort-parser adversarial input-shape matrix, which governs this jq consumer of an external structured response). The malformed-input row above enumerates the shapes that matrix calls for on a non-config external JSON input: absent key, wrong-type value, and unparseable body.

  **Move 3 — named assertions.** Every AC above maps to at least one stubbed-payload assertion in the `fetch-pr-context.sh` block of `lib/test/run.sh`, and every assertion maps back to an AC. The change is a bug fix, so the new assertions are written first and must fail against today's code by exhibiting the exact wrong behavior: the mixed-conclusion assertion fails today reporting a non-zero count for a payload whose only non-success runs are `cancelled`/`stale`, and the two-page assertion fails today reporting only page 1's qualifying runs. The `gh` stub is the fixture; the jq filter and the derivation block under test are never stubbed.

- **Fixture mechanics (verified against `origin/main`)** — `lib/test/fixtures/gh-stub.sh` answers any `*check-runs*` path with `cat "$FX/${SET}-checkruns.json"`, falling back to `{"check_runs":[]}` when the file is absent, so each new payload shape is a new `<SET>-checkruns.json` fixture plus a `DEVFLOW_FIXTURE_PR`/`SET` selection — no stub-dispatch change is needed. Two consequences: (i) the stub cats one file irrespective of `--paginate`, so the multi-page case is exercised by a fixture file holding **two concatenated `{"check_runs":[…]}` objects**, which is exactly the shape real `gh --paginate` emits — do not try to simulate live pagination; (ii) the two existing fixtures are `793-checkruns.json` (`["failure","success"]`) and `CLEAN-checkruns.json` (`["success","success"]`), neither containing `cancelled` or `stale`, so the existing `ci_failures=1` / `ci_failures=0` / `ci_status_unknown=false` assertions in the `fetch-pr-context.sh` block keep their current expected values under the new semantics.

- **Documentation Needed** — `skills/retrospective/SKILL.md`

- **Potential Gotchas** — the `--paginate` output shape described under *Approach* is the dominant trap: adding the flag alone inverts the fix. Embedded jq programs live inside bash single quotes, so any comment added to the filter stays apostrophe-free ASCII. `.prflow/learnings/*.jsonl` byte contents are frozen and must not be rewritten.


