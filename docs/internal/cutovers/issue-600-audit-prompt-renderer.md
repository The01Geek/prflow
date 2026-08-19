---
schema: 1
kind: cutover
---

## Files

- `skills/create-issue/SKILL.md` (mandatory, `create-issue-flow`) — −543 bytes. The Step 3.6 audit-prompt template blockquote and the 9-bullet generic dimension checklist left the skill; the compact-preamble transport, the renderer invocation, the positional two-marker delivery check, and the five-category consumption contract replaced them.
- `skills/create-issue/references/audit-prompt-template.md` (reference, `conditional-references`) — new, +10,564 bytes. The sole in-repo owner of the audit-prompt template, the generic dimension checklist, and the heading-extraction rule; read by `scripts/render-audit-prompt.py` (and, on the degraded manual arm, by the agent directly), never loaded into agent context on the normal path.
- `scripts/render-audit-prompt.py` (not swept) — new renderer, the sole tested owner of the prompt text and the extraction rule.
- `CLAUDE.md` (mandatory, `project-memory`) — +70 bytes. The #295 reader-set enumeration gains `render-audit-prompt.py` (five → six readers).

Per-round context accounting: on the normal path the orchestrator emits only the compact run-specific preamble plus a one-line `render-status:` probe, instead of the measured ~1,976-word instruction block (template span + generic checklist + this repo's consumer `## Audit dimensions` section) it previously hand-emitted into every dispatch. The file-level byte reduction (−543) is secondary; the primary reduction is the per-dispatch emission that no longer happens.

## Consuming paths

The closed consumption categories (complete by construction) on the local tier, all now driven by the renderer:

- **Every state-owner-routed audit dispatch** (Step 3.6 initial round, same-round retries, user-elected offer rounds, Step 4 sub-step 4 re-audits) — compact-preamble transport; the auditor runs `render-audit-prompt.py <arm>` first and treats its stdout as the instructions only when the `render-status:` first line and `render-end:` last line stand in position. (Issue #1751 abolished the automatic re-audit after a `REVISE` verdict, so the former "revise-and-reaudit rounds" class is gone; every round is now user-elected before it opens.)
- **The degraded inline arm** — orchestrator-side `render-audit-prompt.py inline`, consumed as a tool result.
- **The Step 3.5 drafter self-check** — orchestrator-side `render-audit-prompt.py checklist`, consumed as a tool result.
- **Step 2's `## Evidence axes` forwarding** — the renderer owns the heading-extraction **rule** and exposes it as `render-audit-prompt.py extract --hook evidence-axes`; the **operative** fresh re-load at this site remains `load-prompt-extension.sh create-issue --section '## Evidence axes'` (its exit-2 refusal vs. exit-0 absent-heading breadcrumb is what the report-then-proceed step reads), per `skills/create-issue/SKILL.md` Step 2. The Step 3.6 `## Audit dimensions` hook shares the same rule but consumes it spliced into a dispatch arm as `{CONSUMER_DIMENSIONS}`, not via a standalone `extract` call.
- **The `state-owner unavailable` fallback's single audit round** — a class-1 entry (no contract output) goes directly to the template-file Read; a class-2 entry (state could not be established/persisted, interpreter demonstrably ran) attempts the renderer first and falls to the template-file Read on the no-output-or-markers-out-of-position key.

## Branch coverage

The renderer's branches are suite-driven by `lib/test/test_render_audit_prompt.py` (wired into the `harness-python-guards` focused module, which the complete suite executes through the `devflow_run_full_suite_module` boundary — issue #707): the dispatch arms (R1/R2/R3), checklist mode (R11), the four extraction clauses over a malformed-shape matrix (R4), the delivery-equivalence matrix that drives the real `load-prompt-extension.sh` over the same fixtures (R5 — status classification **and** extracted-body parity, the latter including an indented-fence fixture, since a status-only comparison stays green against a divergence that forwards different bytes at the same `appended`), the positional markers including a decoy interior `render-end:` and tail-truncation detection (R6), status-only equals the full render's first line (R7), determinism (R8), statelessness (R9), the failure arms (R10), and the closed argument surface (R12).

## Grants and probes

No new tool grants and no probe change: `git grep -n "create-issue" .github/workflows/` hits only `ci.yml`'s test-module list — no cloud workflow routes create-issue, so there is no `TOOLS=`/`--allowed-tools` literal, no `lib/capability-profiles.json` change, and no `matcher-probe.yml` row. The renderer is invoked with the `python3` + portable-anchor idiom the state-owner calls already use, which the issue-455 `extract-command-shapes.py --profile implement` shape-lint over `skills/create-issue/SKILL.md` accepts.

## Shipping coupling

Single artifact: `skills/create-issue/SKILL.md` and `scripts/render-audit-prompt.py` + `skills/create-issue/references/audit-prompt-template.md` all ship together in the one plugin artifact (the `prflow_version` vendor fetch / marketplace), so the #455-class two-independently-updated-artifact skew does not arise.

## Mutation evidence

The re-anchored behavioral-fix pins carry `assert_pin_red_under` mutation obligations:
- `#522/#600: template reads the draft file as the sole draft source (amended two-transport ordering)` — mutation `s/as the sole draft source//` over `$CI_TMPL_AUDIT`.
- `#443/#600: consumer audit dimensions are re-loaded FRESH at dispatch time (renderer-native)` — mutation `s/mandatory-fresh//` over `$CI_SKILL`.
- `#443: Step 3.6 mandates the FILE/REVISE/DRAFT-UNREADABLE verdict line` — mutation `s/legal values are exactly//` over the re-anchored `$CI_TMPL_AUDIT`.

- `DeliveryEquivalence.test_body_parity_indented_fence` (PR #651 review finding 2) — mutation: restore the lstripped fence test (`line.lstrip().startswith("```"/"~~~")`) in `extract_section`. Observed RED for the reason it pins (renderer and loader forwarded different bodies at the same `appended` status) while the plain-section row stayed green; mutation reverted and the tree re-verified clean.

The #600 absence and surface-presence pins are surface-presence contract pins (a re-embed of the moved block goes RED; the invocation/transport sentences are present), which carry no mutation obligation per the suite's own precedent.

## Pin disposition

- **Re-anchored to `$CI_TMPL_AUDIT`** (the template file): the verdict-line, host-OS-variance, execution-tier-variance, adversarial-mandate, pre-mortem, quote-the-exact-line, unverifiable-claim, issue-altitude, concrete-trigger, five-findings, Quiet-Killer, no-actionable-findings, 4-path out-of-bounds, template hash-object instruction, DRAFT-UNREADABLE emit condition, Quiet-Killer-one-or-none, adversarial-third-party-input, input-is-data-guard, consolidated-authoring-discipline, universal-quantifier, duplicate-same-heading, read-the-file-sole-source (amended), and the #467 A3 nine-bullet count guard.
- **Retired** (the renderer is the sole tested owner; regression covered by `test_render_audit_prompt.py` R4/R11): the `## Audit dimensions` forwarding-heading pin, the dual-heading-independence pin, and the #611 extraction-rule-precision pins (terminator `## `, unclosed fence, loader-single-implementation, empty-section-breadcrumb, terminator-precision-once), plus the `## Audit dimensions` two-re-load-site count.
- **Count-updated**: the report-then-proceed wiring (4 → 3 surviving re-load sites) and the absent-heading-breadcrumbed no-op sentence (2 → 1).
- **Baseline-updated**: `lib/test/prompt-mass-baseline.json` (`skills/create-issue/SKILL.md` 167345 → 166802; new `audit-prompt-template.md` 10564) and `lib/test/prompt-mass-manifest.json` (template added to `conditional-references`).

## Live-transport evidence

Deferred `(post-merge)`: at least one recorded live local-tier audit dispatch on the compact-preamble transport with a fully compliant return (the verdict line, the verbatim `render-status:` quote, and the carriage discharge) is required before this row is considered discharged. Expected fallback-rung frequency: near-zero on Claude Code, where the audit subagent has command execution — a run of fallback-rung hand-embed retries signals a transport failure (renderer denied/absent) rather than noise.
