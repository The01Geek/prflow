# Review stall-backstop contract module inventory

This inventory records the provenance of the focused review stall-backstop contract
module (issue #746, the measured first modularization tranche). It is a navigation
aid, not a second source of behavior: `review-stall-backstop.sh` owns the executable
assertions, and the complete suite calls the same module through
`module-harness.sh`'s `devflow_run_full_suite_module` boundary.

Source baseline: `2e9283f4` (`origin/main` after issue #745 landed).

The extracted region was **2 adjacent box-comment sections** in `lib/test/run.sh`
spanning 853 lines: `#408 cloud review no-verdict auto-resume backstop` and
`#414 review stall-backstop post-and-annotate helper extraction`. Its assertion
floor is recorded once, in `scripts/workflow-flight-recorder-registry.json`, and
enforced on every run by `lib/test/run-module.sh`; `test_module_runner.py`
reconciles that floor against the `lib/test/run.sh` call-site literal. This
inventory deliberately states no exact assertion count — the registry is the single
source, so a count copied here could drift out of it silently.

| Contract group | Former `lib/test/run.sh` section | Module destination | Representative contract |
| --- | --- | --- | --- |
| Fire / no-fire decision | `#408` head | `review-stall-backstop.sh` / decision section | `request-review-backstop.sh` owns the whole decision (config read, verdict guard, per-head attempt count, App-token guard, marker construction), every arm drivable with a stubbed `gh` |
| Guarantee-class arm | `#408` guarantee rows | decision section | an incomplete run is treated as a no-verdict resume candidate, never silently as a pass |
| Workflow wiring | `#408` `devflow.yml` rows | wiring section | the backstop step is wired on the manual `/devflow:review` path with a command-prefix `HEAD_SHA` (the auto path went with `devflow-review.yml` under issue #936) |
| Grounding-block coupling | `#408` `render-grounding-block.sh` rows | wiring section | the resume path carries the rendered grounding block rather than a second hand-copied one |
| Review-skill coupling | `#408` bundle pins | bundle-pin section | the headless-wait discipline sentences survive somewhere in the review engine bundle |
| Post-and-annotate helper | `#414` head | post-and-annotate section | `post-review-backstop-comment.sh` posts and annotates as one extracted helper |
| Empty-branch producer | `#1261` (post-extraction) | decision + wiring sections | `scripts/record-empty-branch.sh` records whether any commit reached a terminated run's remote branch, driven over NO_COMMIT / HAS_COMMIT / UNESTABLISHED against a real bare-origin git fixture, called only from the two claude-job flips and never on the resume path |
| Probe verdict readers | `#414` `schedulewakeup-probe-verdict.py` / `agents-seam-probe-verdict.py` rows, plus the `#812` `background-tasks-probe-verdict.py` rows added after extraction | probe-verdict section | the verdict arms each reader's own closed arm set defines, including its unestablished-measurement arm — and, for the seam reader after issue #1177, that a dispatched run which recorded neither marker is reported as an instrument non-fire rather than as a statement about the seam, that the workflow's own emitting lines still resolve to the verdicts the helper claims for them, and that the returned-text diagnostic is verdict-inert |

The generic test harness, registry validation, module registration, full-suite
boundary, and module-runner tests stay global so deleting this module cannot also
delete the checks that prove it is selected and executed.

Rewrite performed during extraction: every `assert_pin_unique` call became
`devflow_module_pin_unique` and every `assert_pin_red_under` call became
`devflow_module_pin_red_under` — a mechanical 1:1 rename onto the namespaced module
pin API, literals, mutations and targets unchanged. Those mutation-taking helpers
were retired in the later issue-#810 follow-up. Two run.sh globals are
re-derived in the module header rather than inherited:

- `REPO_ROOT`, derived from `LIB` but spelled `$LIB/..` — deliberately NOT the
  monolith's `$(cd "$LIB/.." && pwd)` form — so `pin-corpus-lint.py`'s resolver,
  which understands a `$LIB/relative` assignment but cannot see through a command
  substitution, can resolve every REPO_ROOT-derived pin target (the module header
  states this reason in full).
- `REVIEW_BUNDLE`, the concatenated review-engine bundle (thin root plus every
  phase reference) that two `#408` pins target so their sentences may live in the
  root or in any reference. The module rebuilds it with
  `devflow_module_build_bundle`, promoted into `lib/test/module-harness.sh` by this
  same change rather than hand-rolled a third time. `create-issue-contract.sh` was
  converted onto the promoted helper in the same change;
  `review-and-fix-contract.sh` still carries its own copy and is left for a
  follow-up, so this change retires one duplicate rather than both. Membership is derived
  from the tree — every `skills/review/phases/*.md` — never transcribed, so a phase
  reference added later cannot be silently omitted from the bundle the survival
  pins assert against.

Coverage-map ownership for the moved labels is recorded in
`lib/test/modules/coverage-map.json`.

## Post-extraction additions

- **`#801` — harness floor + injected dispatch barrier.** Authored in this
  module rather than extracted from `run.sh`. It is the natural home despite
  reaching beyond the review tier: the layers it asserts are the direct successors
  of the `#408`/`#415` headless-wait pin family this module already owns, and the
  `headless-literals-unchanged` obligation (that the additive edit desyncs none of
  those pre-existing mutation pins) is only checkable where they live. Its targets
  therefore include implement-tier and installer surfaces the rest of the module
  does not own: `.github/workflows/devflow-runner.yml` (new `$WFRUN801`), plus the
  already-owned `$WFI415` / `$WFD408` / `$RGB408` and `install.sh`
  (`$INSTALL801`). Consequence to know when running this module as the focused test
  for an implement-tier change: `coverage-map.json` routes label `801` here, so an
  implement-side regression in those surfaces surfaces in a review-scoped module.
- **`#1156` — the Phase 4.4 verdict-emitter reach record.** Authored in this module
  rather than extracted from `run.sh`, and placed here because this module already
  owns `devflow.yml`'s post-run handler region: the new `always()` step sits
  directly below the `#408` stall backstop whose command-prefix gate it reuses, and
  one assertion compares the two gates against each other rather than transcribing
  either. It drives three surfaces the module did not previously own —
  `lib/verdict-receipt.sh`, `scripts/check-verdict-post-reached.sh` and
  `scripts/describe-verdict-post-gap.sh` — plus the receipt write inside
  `scripts/post-review-verdict.sh`, whose own outcome-vocabulary coverage stays in
  `run.sh`'s `post-review-verdict.sh` block. Consequence to know when running this
  module as the focused test: `coverage-map.json` routes label `1156` and all three
  new files here, so a regression in the emitter's receipt write surfaces in a
  stall-backstop-scoped module.
- The `#801` barrier coverage is BEHAVIORAL, not a pin over any file's text: the
  barrier's sole home is now the executable `scripts/render-grounding-block.sh`, so
  the checks run the renderer in each of its three modes (`review`, `implement`,
  `generic` — the population the three cloud tiers render) and bound the awk range to
  the rendered headless section, which is location-sensitive in a way a whole-block
  presence check is not. Its two engine-root placement pins retired with the roots'
  copies, and the 12 dispatch-site pointer-presence assertions retired as a
  documentation-presence pin over agent-executed prompt prose (issues #843/#876); the
  module carries the disposition record and the machine-consumer evidence inline, and
  the declared floor decrease sits in `lib/test/assertion-floor-retention-allow.json`.
