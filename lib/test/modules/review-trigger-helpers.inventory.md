# Review/implement trigger-helper contract module inventory

This inventory records the provenance of the focused review/implement
trigger-helper contract module (issue #746, the measured first modularization
tranche). It is a navigation aid, not a second source of behavior:
`review-trigger-helpers.sh` owns the executable assertions, and the complete suite
calls the same module through `module-harness.sh`'s `devflow_run_full_suite_module`
boundary.

Source baseline: `2e9283f4` (`origin/main` after issue #745 landed).

The extracted region was **11 consecutive box-comment sections** in
`lib/test/run.sh` spanning 2,058 lines. It ran from the section
`derive-review-verdict.sh (#249 HEAD-scoped, fail-closed verdict deriver)` through
`resolve-command-trigger.sh` inclusive. **It stops there deliberately:** the tranche
was scoped in advance to a measured set of low-risk sections, and the sections past
`resolve-command-trigger.sh` were not part of it. Its assertion floor is recorded once, in
`scripts/workflow-flight-recorder-registry.json`, and enforced on every run by
`lib/test/run-module.sh`; `test_module_runner.py` reconciles that floor against the
`lib/test/run.sh` call-site literal. This inventory deliberately states no exact
assertion count — the registry is the single source, so a count copied here could
drift out of it silently.

| Contract group | Former `lib/test/run.sh` section | Module destination | Representative contract |
| --- | --- | --- | --- |
| Review verdict derivation | `derive-review-verdict.sh (#249 …)` | `review-trigger-helpers.sh` / verdict section | the deriver is HEAD-scoped and fails closed — an unresolvable comment set yields no verdict, never a default pass |
| Review preconditions | `derive-review-preconditions.sh (#304 …)` | preconditions section | branch-freshness and other-CI-green gating, including the unestablished-measurement arms |
| Engine-error parsing | `parse-engine-error.sh (#249 …)` | engine-error section | the execution-log `is_error` parser feeding `engine_is_error` |
| Execution diagnostics | `surface-execution-diagnostics.sh (#329 …)` + `workflow wiring: … (#331)` | diagnostics section | the run summary and permission-denials surfacer honors `DEVFLOW_JQ` and degrades to "No diagnostics available" rather than a bare-`jq` read |
| Execution transcript | `execution transcript artifact: config key + scrub/gate hardening (#409)` | transcript section | the default-OFF polarity and the fail-closed transcript clamp, both proved by mutation |
| Implement trigger | `resolve-implement-trigger.sh`, `dedupe-implement-run.sh` | implement-trigger section | trigger resolution and the single-flight dedupe of an implement run |
| Actor authorization | `authorize-actor.sh (allowed_users filter)` | authorization section | the `allowed_users` filter's allow/deny arms and deny reasons |
| Standalone command routing | `detect-standalone-command.sh`, `resolve-command-trigger.sh` | command-routing section | both the resolver and `review_dedupe` route through the one shared detector, and the detector extraction fails open only under an `if !` guard |
| CI auto-review notification | *(no former section — added with `scripts/post-ci-review-trigger.sh`)* | `post-ci-review-trigger.sh` section | the composed comment body is fed through the REAL standalone-command detector and must resolve to the plain review command — the structural brake against widening the payload to the fix-loop command, whose App-token pushes escape GitHub's recursion guard — plus the per-SHA post-or-skip arms and the fail-closed unreadable-comment-list arm |
| CI auto-review PR-state guard | *(added with the issue-#1236 PR-state guard in `scripts/post-ci-review-trigger.sh`)* | `#1236` PR-state-guard arms, beside the `#990` block | the guard reads the target PR's state before posting and posts ONLY while it is open — merged / closed / gh-unreadable / empty-state each post nothing and warn with their OWN distinct annotation (no review spend on a dead target) |
| CI auto-review auto-merge guard | *(added with the issue-#2067 auto-merge arm in `scripts/post-ci-review-trigger.sh`)* | `#2067` auto-merge arms, beside the `#1236` PR-state-guard arms | an OPEN PR with GitHub auto-merge armed (non-null `auto_merge`) posts nothing and warns with its OWN distinct annotation, so the trigger does not race the coming auto-merge onto a merged target; the arms drive the helper's REAL `--jq` against a full JSON fixture (the auto_merge branch lives inside the jq), assert merged/closed are still decided before auto-merge, and assert exactly one PR-state read is made |
| ci.yml supersession concurrency | *(added with `lib/test/check-ci-concurrency.py`, issue #1236)* | `cicc #1236` arms, beside the PR-state-guard arms | the static checker over `.github/workflows/ci.yml`'s workflow-level `concurrency:` — the real file holds all three properties, and synthetic fixtures that violate the key's presence / the PR-varying group / the not-true-on-main-push `cancel-in-progress` each fail, with the unreadable file failing closed as `unavailable` |
| Dead-run review-progress upsert | *(no former section — added with `scripts/describe-dead-run-cause.sh` and the issue-#1154 upsert)* | `#1154` section, beside the `#1054` marker-ownership block | the four run-end modes and, by a reordering mutant, that their arm ORDER decides the diagnosis; the upsert's flip / create / already-terminal / idempotent-retry arms and every read, patch and create failure arm driven end to end against a stubbed `gh`; run scoping proved against a foreign run's comment; and `devflow.yml`'s own step shell extracted and executed over its command screen, its target-thread derivation and both degraded-helper arms |
| Review-dedupe pre-seed window | *(no former section — added with the issue-#1479 negative controls, beside the `#1010` commit-scope block)* | `dedupe-review-command.sh` detect-mode section | the decided fail-open through the pre-seed window (before a peer seeds its progress comment): an `isprogress`-rejected comment carrying the seed key and `🚀 Reviewing` status but no review-progress marker is discriminated on the marker conjunct (a single widening of which turns it RED) and yields `suppress=false`; and a timeline whose only per-head comment is the run's own `prflow:ci-review-trigger` marker is never read as a peer claim and likewise yields `suppress=false` |

The generic test harness, registry validation, module registration, full-suite
boundary, and module-runner tests stay global so deleting this module cannot also
delete the checks that prove it is selected and executed.

Rewrite performed during extraction: the 4 `assert_pin_unique` calls became
`devflow_module_pin_unique` and the 2 `assert_pin_red_under` calls became
`devflow_module_pin_red_under` — a mechanical 1:1 rename onto the namespaced module
pin API, with the pinned literals, mutations and target paths unchanged. Those
mutation-taking helpers were retired in the later issue-#810 follow-up. One run.sh
global is re-derived in the module header rather than inherited: `CG` — the
`scripts/config-get.sh` resolver path that the `#329`/`#409` key-read assertions
invoke — is bound from `LIB` exactly as the monolith binds it. The extracted body
keeps allocating and removing its own fixture trees with bare `mktemp -d`, exactly
as it did inline; the module adds no private root and no EXIT trap, for the reasons
its header records. Coverage-map ownership for the moved labels is recorded in
`lib/test/modules/coverage-map.json`.
