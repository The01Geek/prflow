# Create-issue contract module inventory

This inventory records the provenance of the focused create-issue contract module.
It is a navigation aid, not a second source of behavior: `create-issue-contract.sh`
owns the executable assertions, and the complete suite calls the same module through
`module-harness.sh`'s `devflow_run_full_suite_module` boundary.

Source baseline: `553e13da` (`origin/main` before issue #577).

The extracted region was one contiguous block in `lib/test/run.sh` — it began at the
issue #443 audit contract and ended after the issue #559 revision-delta pins. The
issue-#548 evidence-bundle coverage sat interleaved inside that block (between #467
and #465) and reused the same create-issue file variables, so it migrated with the
block; the issue text enumerated eight issues but the contiguous region carried nine.
The unrelated implement coverage before the region and the review-and-fix drift-guard
coverage (issue #199) after it stay in the monolith.

| Contract group | Former `lib/test/run.sh` coverage | Module destination | Representative contract |
| --- | --- | --- | --- |
| Step 3.6 fresh-context audit | `3744–3892` | `create-issue-contract.sh` / issue-#443 section | the FILE/REVISE/DRAFT-UNREADABLE verdict line and the information-diet exclusion |
| Canonical draft-file audit + state-owner cutover | `3894–4220` | issue-#522 and #546 sections | presentation eligibility is the tool's answer; the canonical draft file is the sole draft source |
| Authoring-discipline rules and hardenings | `4222–4384` | issue-#462 and #467 sections | value-comparison observed-output grounding; the universal-quantifier sweep |
| Evidence-bundle sub-pass and actionability | `4385–4435` | issue-#548 section | the evidence-bundle axis floor and the bounded-actionability verdict definitions |
| Multi-state reconciliation, adversarial input, floor rule | `4436–4543` | issue-#465 and #464 sections | within-text multi-state-contract reconciliation; the adversarial-third-party-input dimension |
| Revision-delta verification coverage guard | `4545–4732` | issue-#559 section | every `no-options gate` occurrence classified; the shared Revision-delta verification block |
| Shift-left evidence disciplines | _(none — never lived in the monolith)_ | issue-#613 section | the Consumers-axis evidence floor and closed-set complement entries; the self-referential-count gate scan and the negative sweep retiring the overview's axis enumeration |
| Step 4 listing shell-behavior boundary | _(none — never lived in the monolith)_ | issue-#1733 section | `ls -lL` classifies present/absent/unestablished from what the shell shows (a dangling link draws a not-found message that is decisive over a stale row), exercised against the host `ls` and a second implementation |

The issue-#613 group also plants at least one pin outside its own section: a
`devflow_module_pin_unique` on the Consumers-axis floor's sweep-leg paraphrase, placed
beside the issue-#593 exactly-3 repo-wide-scope-sentence count with a comment recording
why that count deliberately excludes the paraphrase. Read the two together — the count and
the paraphrase pin are the same contract stated canonically and in paraphrase.

## Pin-target routing after the issue-#614 split

`skills/create-issue/SKILL.md` became a thin root plus marker-gated references under
`skills/create-issue/references/` (issue #614), so every pre-existing pin in this module had
to be routed to the surface that preserves its guarantee. The routing rule is decided, not
per-pin ad hoc:

| Pin class | Post-split target | Why |
| --- | --- | --- |
| Content-survival — the pin asserts a contract sentence still exists somewhere in the shipped skill | `$CI_BUNDLE` (root + the 16 references, concatenated) | Which reference currently hosts a sentence is an implementation detail that may be re-partitioned; "present-and-unique in the shipped skill" is the semantically correct claim. Deleting the sentence from a reference still turns the pin RED, because the bundle is rebuilt from the real files on every run. |
| Location-sensitive — the pin asserts a sentence lives in a *specific* surface | that specific file | A bundle target would pass while the sentence sat anywhere, which is exactly what these pins exist to forbid. |

The location-sensitive population is exactly:

| Pin | Target | Reason |
| --- | --- | --- |
| `A skipped or degraded audit is **never silent**` | `$CI_SKILL` (root) | AC4 invariant 3 — the root is the sole home of this sentence; `step-4-present-create.md` carries a seam pointer to it, deliberately worded to quote no pinned literal. |
| `**The audit summary line is mandatory and always renders**` | `$CI_SKILL` (root) | Same invariant, same reason. |
| the `s/the evidence the audit ran and which arm it took//` mutation | `$CI_SKILL` (root) | Guards the same root sentence; a bundle target would let the invariant drift out of the root. |
| `A fallback lifecycle is **never silent**` | `$CI_REF_FB_STATEOWNER` | AC4's second never-silent sentence; the two phrasings are near-identical, so a bundle target would collide their uniqueness. |
| the ten `#614 T4` purity representatives | each fallback reference, plus an absence sweep over the root and every step reference | AC8 — the whole claim is *where* the prose is not. |
| the three `#275` A2b anchor call-site pins (`lib/test/run.sh`) | `step-4-present-create.md` (label helpers), the root (extension load) | Each pin follows the file that now performs the call. |

`$CI_BUNDLE` is assembled in-module from the root plus the 16 references by a `references/*.md`
glob (a dropped reference still fails LOUD via the T1 routing reconciliation, whose routing row
would name a file that is gone, rather than silently shrinking the bundle), and `lib/test/run.sh`
hoists an identical `CREATE_ISSUE_BUNDLE` and binds it through `CI_MOD_VARS` so these targets
stay **resolved** under the pin-corpus meta-guard instead of dropping out of the lint. Only
`audit-prompt-template.md` is exempt from the routing reconciliation (its consumer is a Python
renderer, not a gated runtime read). `issue-template.md` is a routed reference that is
nonetheless kept out of this bundle: bundle membership tracks where content-survival pins point,
not runtime routing, and it keeps its own dedicated target (`$CI_TMPL`), so bundling it would add
uniqueness collisions.

The `#614` block itself adds the structure (T1), marker (T2), budget (T3 + the AC7 planted-defect
positive control), purity (T4), routing-table (T6), and extension-axis (T7) assertions.

The generic test harness, registry validation, module registration, full-suite
boundary, and module-runner tests stay global so deleting this module cannot also
delete the checks that prove it is selected and executed. The shared pin/count/
mutation machinery lives in `module-harness.sh` (the namespaced `devflow_module_*`
API), so this module carries no private copy of it — it uses only `assert_eq`, that
namespaced API, and a small set of domain-private helpers: `ci559_classify` /
`ci559_field` for the revision-delta coverage guard, and `_ci613_classify` /
`_ci613_scan` for the issue-#613 negative repo-wide sweep (the latter pair is
`unset` immediately after its assertions, so it does not outlive its block).
