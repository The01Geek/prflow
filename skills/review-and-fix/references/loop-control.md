# Reference: Loop Control (workpad, schema field semantics, Main Loop, Steps 0.5–2)

## Persistent workpad

The orchestrator persists per-iteration state under `.prflow/tmp/review/<slug>/<run-id>/iter-<N>.json` (relative to the repo root). `<slug>` is `pr-<N>` in PR mode or the sanitized current branch name in branch mode; `<run-id>` is a per-run discriminator (below); `<N>` is the iteration number, from 1.

Run-scoping (`<run-id>`). The workpad is scoped by a per-run id so a second `/prflow:review-and-fix` or `/prflow:review` invocation on the same PR (including `/prflow:implement` Phase 3.3's re-review of the *same* PR) never clobbers a prior run's `iter-*.json` or `deferrals.json`.

One-call loop setup. Run the setup helper once at loop start — it resolves the run key, `slug` and run directory and the four config values (`max_iterations`, `fix_severity_threshold`, `fix_below_threshold_iterations`, `efficiency_telemetry_enabled`) with the loop's clamps and fallbacks already applied, creates the run directory, and persists `<run_dir>/loop-setup.json`. It runs no `gh`. The vendored literal first:

```bash
.prflow/vendor/prflow/scripts/review-dirty-tree.sh loop-setup [--pr <PR_NUMBER>]
```

On a `command not found` / `No such file` / exit-127 reading — or an `unknown subcommand` exit-2 reading from an older vendored `review-dirty-tree.sh` — fall back to the portable anchor:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/review-dirty-tree.sh loop-setup [--pr <PR_NUMBER>]
```

Route on the one JSON line's `status`:

- `ok` → hold `run_id` (the `<run-id>` below), `slug`, `run_dir` and the four resolved values for the loop's lifetime, substituting them wherever the fallback fences below would derive them; `<run_dir>/loop-setup.json` holds the same line for a compacted context. Skip the run-key composer fence just below and the three config-resolution fences under **Main Loop**.
- `error` → the JSON's `step`/`reason` name where and why; fall back to the fences below and quote them in the loop's narrative.
- No JSON from both arms (refused, not found, or the exit-2 `unknown subcommand` skew) → fall back to the fences below.

Without a usable `loop-setup` line, obtain the discriminator by invoking the run-key composer as a leading token, the vendored literal first:

```bash
.prflow/vendor/prflow/scripts/compose-run-key.sh
```

On a not-found reading (`command not found` / `No such file` / exit 127), fall back to the portable anchor:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/compose-run-key.sh
```

Hold the observed one-line output as the run's literal run key for its whole lifetime and substitute it into every `<run-id>` slot below; never assign a shell variable or expand a `$GITHUB_*` variable. When the call prints nothing — refused, exited non-zero, or both arms not found (report the last as the anchor-resolution arm) — compose the key by literal substitution: on the implement tier, `<run id>-<run attempt>` from the prompt's run-facts block when both lines read other than `unestablished`; otherwise `local-<output>-1` from a bare `date -u +%Y%m%dT%H%M%SZ`, and if that too prints nothing stop at **Blocked** naming the run key unestablished — never a guessed key or an unsubstituted `<run-id>`. If a compaction later leaves the key unheld, re-invoke the helper: its cloud-arm output is a pure function of the runner environment, so it returns the identical key; a re-invocation printing nothing takes the run-facts fallback when that block is in context, else stops at **Blocked** as unheld, as does a local-arm re-invocation (the `date` fallback applies only to this first derivation).

Caller-origin progress surface (internal; bind once at loop entry). The only signal that this loop runs inside `/prflow:implement` is the invoking caller already holding `$ISSUE_NUMBER` in context — under `/prflow:implement` that caller is the dispatched `review-fix-worker`. When present, bind internal `progress_surface = workpad` once and retain it for the whole loop; else leave it absent. Never infer implement context from `$ISSUE_OVERRIDE` / `--issue`, `--push-each-iteration`, an issue workpad's existence, PR mode, or any repository state — each can occur standalone.

All in-run scratch is run-scoped — `diff.patch`, `iter-*.json`, and `deferrals.json` all live under `.prflow/tmp/review/<slug>/<run-id>/`. `diff.patch` is the full diff Phase 0.2 of `/prflow:review` writes every iteration; Phase 3 agents Read it directly via the `{DIFF_PATH}` substitution Phase 0.2 fills in. So Phase 0.2 and this wrapper agree on one `<run-id>`, the wrapper passes its held run key into Phase 0.2 (Step 1's `run_id` handoff; see `/prflow:review`'s Phase 0.2).

Only `.prflow/tmp/` is ephemeral; the rest of `.prflow/` is tracked. `scripts/scaffold-config.sh` (run by `install.sh` / `/prflow:init`) owns the `.prflow/.gitignore` entry for `tmp/`; this skill never manages it.

## Schema field semantics

`loop_role` names this iteration's role — `fix` for a normal fix iteration, `promoted` for one started by a Decide-outcome-2 shadow promotion (see Step 2.6 "Decide" outcome 2 and Step 4.5). `lib/efficiency-trace.jq` derives and surfaces it per iteration in the per-run record (iteration 1 → `fix`; iteration N → `promoted` when iteration N−1's `shadow` block recorded a promotion via `promoted_to_iter_next`, else `fix`). The `shadow` block remains the record of the shadow pass and any post-shadow delta-review, and the convergence/promotion logic keys off that block, not this field.

`phase3_dispatched` is the array of Phase-3 agent identifiers launched this iteration, captured at Step 1's Phase 3.1 dispatch *after* Phase 0.5 gating (so a gated-out `pr-test-analyzer` / `type-design-analyzer` is absent). It is load-bearing for the Loop Exit effectiveness trace: a `null` verdict (dispatched but silent) is derived as `phase3_dispatched − (agents present in phase3_findings)`.

Use the same identifier string in `phase3_dispatched` that you write to each finding's `phase3_findings.agent`, so the trace matches dispatch to outcome. For the five first-party review agents that is `prflow:<name>`; for the sixth Phase-3 dispatch — the general-purpose final-pass reviewer invoking `/prflow:requesting-code-review` — record `prflow:requesting-code-review` in both places.

`dispatched_effort` is the per-dispatch-phase effort observability roster: one entry per dispatched override-eligible agent per dispatch phase — `{"agent", "phase" ("1"|"1.5"|"2"|"3"), "requested", "resolved", "application_point", "effective", "fallback_reason"}` — using the same identifier strings as `phase3_dispatched`. Capture at each dispatch phase (Phase 1 checklist-generator, Phase 1.5 checklist-deduper, Phase 2 checklist-verifier, Phase 3 review roster), right after that phase's `resolve-review-overrides.py` call, by re-invoking the helper for the same roster with `--effort-json` and appending one phase-tagged entry per agent. `effective` stays `null` unless genuinely read back from the dispatched agent — never inferred; a `session-inheritance` entry is all-null.

`expected_reviewers` is the Phase-3 roster the engine's own Phase 3.1 gating selected this iteration — the same identifier strings as `phase3_dispatched`, evaluated against the actual diff (so `pr-test-analyzer`'s test-relevance predicate, not a `diff_profile` flag, is resolved here). It is a required field of the Step-1 return and a well-formedness operand, written on every iteration alongside `phase3_dispatched` (so `ITER_EXPECTED_FIELDS` includes it).

`phase3_failed_agents` is the array of Phase-3 agent identifiers dispatched but that did not return a usable result, or whose dispatch the runner refused before any subagent existed (evidence-empty / failed / lost / runner-refused), written unconditionally on every iteration (`[]` when none) with the same identifier strings as `phase3_dispatched`. `lib/efficiency-trace.jq` marks a `failed` per-agent disposition for a dispatched member (a runner-refused one is not in its roster).

`diff_profile` records the engine's Phase 0.5 classification for the iteration — the three profile-shaping flags (`small_diff`, `config_only`, `has_new_types`) plus a nested `checklist_skipped` member (`"intentional"` when Phase 0.5 bypassed Phase 1+2 on a small_diff+config_only diff, `"failure"` when checklist generation failed, else `null`) — so the checklist-skip tripwire's `diff_profile.checklist_skipped` read resolves against the nested field, not a sibling. (Phase 0.5's `detect_all_audit`, is intentionally **not** persisted here — it never alters the engine profile.)

`cap_drops` is populated from /prflow:review's Phase 1.1.5 output (read by the final report's Coverage section) — `count` is the total dropped at the 100-item cap, `by_category` the per-category breakdown.

`dispatch_mode` records how each engine entry ran — the top-level field and `shadow.dispatch_mode`, each exactly `fanned-out` or `unavailable` (copied from that entry's return file), or `null` only after a refused, dead, or malformed dispatch; the parent never self-assigns it, so `ITER_EXPECTED_FIELDS` excludes it. Never read an absent or `null` value as `fanned-out`. `dispatch_disposition` (top-level; `shadow.dispatch_disposition` for the shadow) records why a dispatch produced no usable return — exactly `refused` (harness refused it), `dead` (subagent returned nothing), or `malformed` (return failed the well-formedness check) — written when that entry's `pending_dispatch` is cleared on disposition, never itself cleared, so `ITER_EXPECTED_FIELDS` excludes it too.

`current_step`, `current_substep`, and `pending_dispatch` are the durable continuation operands: the run-scoped record — not agent recall — identifies the active procedure. `current_step` is `"loop-control"` during config resolution and Steps 0.5–2, then the routed step id (`"2.5"`, `"2.6"`, `"3"`, `"3.5"`, `"4.5"`, or `"loop-exit"`). `current_substep` is a coarse label such as `"run_shadow_fanout"`, or `null`. Immediately before every `Agent`/`Skill`/`Task` dispatch this reference itself issues — a dispatch made while executing the review engine's phases inline is the engine's own, not stamped here — write `pending_dispatch` with `kind`, `roster`, `dispatched_at`, and `issued_by` (this reference's own active `current_step`, the durable discriminator the root's re-read rule keys on). The engine-subagent dispatches this reference issues carry `kind` `engine_step1` (Step 1) or `engine_shadow` (the Step 2.6 shadow). Clear `pending_dispatch` after the attempt is joined or dispositioned (including terminal failure/not-verified) — it persists only while unresolved. A failed stamp is logged and takes the root contract's absent-operand fail-closed arm. They are not effectiveness telemetry, so `ITER_EXPECTED_FIELDS` excludes them. `dispatched_at` is an observed timestamp — the SKILL.md *Schema field semantics* rule governs it (the output of `date -u +%Y%m%dT%H%M%SZ` read immediately before the Write, or `null`).

`evidence_recovery` (top-level for the Step 1 entry; `shadow.evidence_recovery` for the shadow) — the per-entry recovery marker Step 1.8 writes before repair, `{entry, iteration, reviewed_head, attempted_at}`, keyed {run id, `entry` ∈ `step1`/`shadow`, iteration N, `reviewed_head`} so a HEAD change between visits to one entry cannot reset the allowance. `attempted_at` is an observed timestamp, as `dispatched_at` above. A progressive write into the current `iter-<N>.json` like `pending_dispatch`, so `ITER_EXPECTED_FIELDS` excludes it; its presence for a key means that entry's one recovery attempt is spent. A non-pass `check-evidence`/`compose --entry` detail reports it.

Dispatch barrier. Every subagent dispatch described here is bound by the dispatch-collection requirement in the engine-ground-truth block injected into this run's prompt — read it there (if your prompt carries no such block, collect every dispatch before the turn ends anyway).

`shadow` is populated by Step 2.6 (the shadow review pass). `coverage` is a pure roster measurement: `"full"` when the parent ran the complete multi-agent fan-out a standalone /prflow:review Phase 3 would launch (subject to the Phase 3.1 applicability gates), `"not_verified"` when the fan-out could not be completed (outcome 3 — see Step 2.6 "Decide"). Prompt composition is measured separately by `prompt_addenda`; it gates outcome 1 and the clean-agreement renders, never `coverage` or outcome 2. Step 2.6 defines `reviewers_dispatched`.

`parking_evidence` (authoritative shape). The **rationale-bearing** `fix_decisions` row classes — the Step 2.5 advisory-parked row, the Step 3 item 5 Yes-downgrade rows (`claim-quality` / `out-of-scope` / `already-tracked`), the **`settled-by-disclosure` foreclosure row** (Step 3 item 5 for a fixer-routed finding, or Step 2's per-finding foreclosure arm for a parked one), and the parked-class sweep's parked-sibling advisory row (the `parked-sibling: class-sweep` producer) — each carry, beside the retained one-line `evidence` string (the verbatim `deferrals.json` `explanation`), a structured `parking_evidence` object `{basis, failing_input, source, finding_ref}` written at parking time: `basis` — the one-line causal rationale (an uncitable Step 2.5 demotion names the recorded `step25_classification` outcome; the sweep sibling names its parking reason); `failing_input` — the concrete input/state relied on; `source` — the citation (refutation URL, source span, `git blame` proof, issue reference); `finding_ref` — the `{iter, index}` join to the parking-time `phase3_findings` record, explicit, never a fuzzy `source_file`/`claim_text` match. A field with no applicable value is JSON `null`; `finding_ref` is always applicable, so a null there is a writer omission (the fail-closed arm), as at comparison time is an omitted, empty, or wrong-type field. The `settled-by-disclosure` row adds a comparison-time check: its `source` names a disclosure `{path, phrase}`, so the comparer **opens the named file and searches for the quoted phrase whitespace-normalized**; each failure arm — file absent, unreadable, outside the checked-out tree, or phrase not found — routes to the missing-operand fail-closed treatment (row not preserved, finding promotes). The below-threshold producer row (`decision: "below-threshold"`, `skip_category: "below-threshold-parked"`) and the below-Important damper producer row (`decision: "below-important-damper"`, `skip_category: "below-important-damper-parked"`) are rationale-less and gain no new fields — their absent `parking_evidence` is not a missing operand.

`park_calibration` (authoritative shape). An additive top-level block the Step 2.6 Park-calibration gate writes when it runs the evidence classification (below): `park_calibration.evidence_comparisons[]` carries one record per shadow-re-raise↔parked-finding pair, written on both dispositions, shaped `{parked_finding_ref, parked_finding_id, shadow_finding_index, relation, rationale, operands_present, disposition}`. `parked_finding_ref` is the `{iter, index}` identity of the parking-time record, supplying every parked-side operand (condition (b)'s severity comparand and condition (c)'s `step25_classification`); a later iteration may re-grade a re-emitted finding without rewriting `step25_classification`, so a most-recent-appearance read would compare the wrong record. `parked_finding_id` carries the `fix_decisions.finding_id` when a row exists, else JSON `null`; `shadow_finding_index` indexes the shadow block's `phase3_findings`; `relation` is one of the five taxonomy relations; `rationale` is one line; `operands_present` is the boolean the fail-closed arm sets `false` on any missing/malformed/unresolvable operand; `disposition` is `preserved` or `promoted`. The block is absent when the gate wrote no evidence comparison.


## Main Loop

Expired-credential fail-fast (two strikes, never open-ended retry). A cloud writer-job's GitHub App installation token expires 60 minutes after job start, after which every `git push` and `gh` call is rejected with a bad-credential error. After two consecutive `git push` or `gh` failures whose output carries the bad-credential signature — HTTP `401`, `Bad credentials`, or `Authentication failed` — stop retrying that operation (no third variant), record the cause in the loop's record/workpad, and exit reporting the expired-credential cause rather than iterating on it. This prose rule is best-effort under compaction; the `gh-fresh.sh` wrapper is its compaction-immune sibling, appending a `devflow-gh-fresh: … expired/bad credential` diagnostic to stderr on every bad-credential `gh` failure.

Resolve the iteration cap once, at loop start. Read `prflow_review_and_fix.max_iterations` (default 5) via the config helper — the skill-dir-anchored, no-`bash`-prefix invocation `references/loop-exit.md` also uses, so the read is cwd-independent and the allow-list entry matches. Discriminate a resolver failure (missing `python3`, malformed `config.json` → non-zero exit with empty stdout) from a legitimately-absent key with the fence's single-statement `if !`, and clamp the result:

```bash
# CANONICAL config-read discriminator (the two reads below reference this): a single-statement
# `if !` reads config-get's OWN exit status inline — a captured rc in a later statement is
# stripped by an inline-bash runner. On failure warn, leave the var empty (the value-check below
# supplies the default), and never redirect stderr to a file — a cloud harness refuses it, so the
# fence returns no output and the warning loses its cause.
if ! MAX_ITERS=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .prflow_review_and_fix.max_iterations 5); then
  echo "::warning::devflow review-and-fix max_iterations read failed (config-get.sh rc≠0) — using default 5; cause follows"
fi
# Fall back to default 5 on a resolver failure (empty stdout above) or a non-integer/empty value;
# clamp a value below 1 up to 1 so the loop always runs once. No upper bound is imposed.
if ! printf '%s' "$MAX_ITERS" | grep -Eq '^-?[0-9]+$'; then
  MAX_ITERS=5
elif [ "$MAX_ITERS" -lt 1 ]; then
  MAX_ITERS=1
fi
```

When that warning fired, emit the cause as a separate second warning. Read this fence's own tool result and emit `::warning::devflow review-and-fix max_iterations cause: <the first line of the stderr it showed, or the literal stderr=empty>`.

Resolve the fix-severity threshold once, at loop start (right after the cap above). Read `prflow_review_and_fix.fix_severity_threshold` (default `important`) via the same `config-get.sh` invocation the cap read uses. `config-get.sh` coerces any JSON value to a string and does not validate the enum, so validate it inline; a resolver failure or a value outside the enum falls back to the default with a breadcrumb naming the key and fallback value (never aborting the loop):

```bash
# Per the canonical config-read discriminator above: the `if !` reads config-get's OWN exit
# status; the enum validation is a separate `case` on the value alone. Both fall back to the
# default, each with its own DISTINCT breadcrumb.
if ! FIX_THRESHOLD=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .prflow_review_and_fix.fix_severity_threshold important); then
  echo "::warning::devflow review-and-fix: could not read .prflow_review_and_fix.fix_severity_threshold (config-get.sh rc≠0 — malformed config.json or missing python3?); using default 'important'" >&2
  FIX_THRESHOLD=important
fi
case "$FIX_THRESHOLD" in
  critical|important|suggestion) : ;;
  *) echo "::warning::devflow review-and-fix: .prflow_review_and_fix.fix_severity_threshold value '$FIX_THRESHOLD' is not one of critical/important/suggestion; using default 'important'" >&2
     FIX_THRESHOLD=important ;;
esac
```

`$FIX_THRESHOLD` is the routing threshold used in Step 2 below. Severity ordering: `critical` > `important` > `suggestion`; "at or above `$FIX_THRESHOLD`" reads down that ladder (threshold `important` ⇒ Critical + Important/Major route to the fixer, Suggestion/Minor stay advisory; `suggestion` ⇒ every severity routes; `critical` ⇒ only Critical routes). Record the resolved value in the workpad.

Resolve the below-Important fix window once, at loop start (right after the threshold above). Read `prflow_review_and_fix.fix_below_threshold_iterations` (default 1) via the same `config-get.sh` invocation the cap read uses, then validate inline — honoring a configured `0` (a legal off-switch: park below-`important` findings from iteration 1 on), else falling back to `1` on a resolver failure (rc≠0) or a non-integer/negative value, each with a distinct breadcrumb naming the key (never aborting the loop):

```bash
if ! FIX_BELOW_ITERS=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .prflow_review_and_fix.fix_below_threshold_iterations 1); then
  echo "::warning::devflow review-and-fix: could not read .prflow_review_and_fix.fix_below_threshold_iterations (config-get.sh rc≠0 — malformed config.json or missing python3?); using default 1" >&2
  FIX_BELOW_ITERS=1
fi
if ! printf '%s' "$FIX_BELOW_ITERS" | grep -Eq '^-?[0-9]+$'; then
  echo "::warning::devflow review-and-fix: .prflow_review_and_fix.fix_below_threshold_iterations value '$FIX_BELOW_ITERS' is not a non-negative integer; using default 1" >&2
  FIX_BELOW_ITERS=1
elif [ "$FIX_BELOW_ITERS" -lt 0 ]; then
  echo "::warning::devflow review-and-fix: .prflow_review_and_fix.fix_below_threshold_iterations value '$FIX_BELOW_ITERS' is negative; using default 1" >&2
  FIX_BELOW_ITERS=1
fi
```

`$FIX_BELOW_ITERS` is the below-Important damper window used in Step 2 below: the count of leading iterations (1..`$FIX_BELOW_ITERS`) in which below-`important` findings the threshold admits still route to the fixer. Record the resolved value in the workpad.

Continuation of a killed attempt (only under `progress_surface = workpad`; a standalone run skips this). Read `.telemetry.branch` (default `prflow-telemetry`) with the same `config-get.sh` invocation as the cap read and hold the printed line, or `prflow-telemetry` on rc≠0 or empty output. Then, with the run key held and before iteration 1, ask the helper whether a prior run of this slug left iteration records bound to HEAD — the run root, the resolved cap and the held branch name substituted as literals, never `$VAR`; on a not-found reading fall back to the anchor form as for the run key:

```bash
.prflow/vendor/prflow/scripts/loop-verdict-marker.py continue-run --run-root .prflow/tmp/review/<slug>/<run-id> --max-iterations <resolved cap> --telemetry-branch <held branch name>
```

Record the printed line once as a workpad note (`workpad.py update <issue> --note …`, the Step 1.8 tick's ladder). Route on it. `continue-run: restored iteration=<N> …`: the run directory now holds `iter-1.json`…`iter-<N>.json`, the killed attempt's records stamped `restored_from`; start at iteration N+1 under the N ≥ 2 rules, count toward `$MAX_ITERS` from N+1, and never take the Clean-iteration-1 exit. The restored records' `current_step`, `current_substep`, `pending_dispatch` and `evidence_recovery` stamps route nothing — the re-read rule fires only on this run's own returns — and an engine or shadow return the killed loop never folded into a record is not consumed: iteration N's unrun fix-delta gate, suite run and convergence are absorbed by N+1's own pass. Any other line — `none`, `unestablished`, no output, an argparse or unknown-subcommand error from an older helper — starts at iteration 1 as today; never guess a continuation.

Execute this loop with a maximum of `$MAX_ITERS` iterations (the configured cap resolved above; default 5).

### Iteration Start

Output: `Review iteration {N}/$MAX_ITERS...`

At each Iteration Start, re-invoke both the `review-and-fix` and `fix` prompt-extension ladders (defined in the root `SKILL.md`), once per iteration, unconditionally — else iterations 2..N run without the consumer policy loaded only at loop entry. The returned text refreshes the already-loaded policy rather than issuing a fresh directive; a refused or non-zero re-load is surfaced here, not deferred.

If N ≥ 2: read `iter-<N-1>.json` from the workpad before proceeding.

### Step 0.5: PR-mode branch sync (PR mode only)

Skip this step in current-branch mode (no `$PR_NUMBER`) — that mode already commits to and diffs against the checked-out branch.

In PR mode, this step is a gate, not an optimization: before any Phase 0.2 diff or review work runs, it must prove that the checked-out branch is the PR's head branch — so Step 3's fix commits land on the PR's branch and local `HEAD` *is* the PR head. On iteration 1, check out the PR's head branch and route on the checkout's tool result (the arms below):

```bash
gh pr checkout $PR_NUMBER ; echo "checkout-done"   # checks out (and tracks) the PR's head branch
```

Keep the `echo` in that same statement and immediately after the checkout, so the token prints only when the checkout ran. Route on the tool result as follows:

- `checkout-done` present with no `gh` error text — the checkout succeeded. Proceed to the branch-sync below, which is the gate.
- `checkout-done` present beside `gh`'s error text — the checkout failed (e.g. dirty working tree, detached HEAD); stop and report naming that failure before running the assertion. Do not proceed to review, commit, or push onto the wrong branch. On this arm the checkout's own error output is the primary detector, since a name-only comparison passes vacuously when a stale local branch of the same name is already checked out.
- No output at all — a refused or unexecuted statement (a tier that does not grant `gh pr checkout` refuses it before it runs, emitting nothing). Proceed to the branch-sync below, which is then the sole authority; on this arm the head-commit comparison (not the name comparison) is authoritative. This arm establishes no upstream tracking — the checkout never ran — and relies on the caller having established it (on the implement path, Phase 1.5's `git push -u` and Phase 3.1's push before Step 0.5 runs).

One-call branch-sync. Run the sync helper once, right after the checkout above, to compute the PR-head comparison the assertion below makes by eye — the two `gh pr view` reads and the two `git` reads. It runs no checkout and changes no git state. The vendored literal first:

```bash
.prflow/vendor/prflow/scripts/review-dirty-tree.sh branch-sync --pr <PR_NUMBER>
```

On a `command not found` / `No such file` / exit-127 reading — or an `unknown subcommand` exit-2 reading from an older vendored `review-dirty-tree.sh` — fall back to the portable anchor:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/review-dirty-tree.sh branch-sync --pr <PR_NUMBER>
```

Route on the one JSON line's `status`, which the loop treats exactly as the by-eye assertion below:

- `ok` → the checkout landed on the PR head (`head_ref` equals `branch` and `head_oid` equals `head`); the gate is satisfied, proceed to Phase 0.2.
- `mismatch` → a comparand differs; stop and report, naming `head_ref`/`head_oid` (the PR head) against the `branch`/`head` actually checked out.
- `unresolved` → a `gh pr view` read exited non-zero, was empty, or was `null`; stop and report naming the unresolved comparand — never read an unresolved comparand as satisfied.
- No JSON from both arms (refused, not found, or the exit-2 `unknown subcommand` skew) → fall back to the by-eye assertion below, which routes the same stop conditions.

Then assert that the checkout landed on the PR head. Resolve the PR's head ref and head commit once — `gh pr view $PR_NUMBER --json headRefName --jq '.headRefName'` and `gh pr view $PR_NUMBER --json headRefOid --jq '.headRefOid'` — then require both: `git branch --show-current` equals that head ref, and `git rev-parse HEAD` equals that head commit. If either `gh pr view` read exits non-zero, or prints an empty or null value, stop and report naming which read failed — never compare against, or read as satisfied, an unresolved comparand. If either differs, stop and report naming the mismatch, the expected head ref and commit, and the branch (and commit) actually checked out. No stop arm of this step proceeds to review, commit, or push — a diff or fix computed against the wrong branch is the failure this gate exists to prevent.

### Step 0.9: Fix-delta handoff (skip on iter 1)

On iteration 1, skip this step (no prior iteration to hand off from) and proceed to Step 1.

On iterations N ≥ 2, prepare the prior-iteration state the engine's Phases 1-3 consume. Phase 1+2 always re-run; this step does NOT skip them. A promoted iteration is the explicit exception (Step 2.6): its short-circuit staging artifact also carries the promotion site's chosen `promotion_provenance`, and the fused iter-record Write reads that staged state, not conversational memory.

Compute:

1. Prior reviewed head (`prior_diff_head`). The `diff_produced_at_head` recorded in `iter-<N-1>.json` — the sha its Phase 0.2 diff was produced at, which Phase 1.0 diffs against the current HEAD to decide what may be carried forward. The field is absent only on an iteration that ran no engine entry — a promoted one; an intentional Phase 1+2 skip still records it, and item 2's absent snapshot carries nothing. When absent, pass none and log `carry-forward: none (prior_diff_head absent)` here; §1.0 is skipped and logs nothing. If `iter-<N-1>.json` itself is missing or unreadable, skip this whole handoff per root `SKILL.md` `### Lifecycle` "Iter N start" and proceed to Step 1.

2. Prior checklist (`prior_checklist`). The Step 1.8 snapshot pair at the run root, `checklist-step1-iter-<N-1>.json` and `verification-step1-iter-<N-1>.json` — never `iter-<N-1>.json`'s `checklist`, a verdict-only projection. Pass the pair by name; Phase 1.0's helper reads it itself and, when either file is unusable, carries nothing and logs the breadcrumb naming the file and shape.

3. Prior Phase 3 findings (`prior_phase3_findings`). `iter-<N-1>.json`'s full `phase3_findings`, plus each `iter-<K>.json` (K < N-1) finding whose `fix_decision` is not `applied`, tagged with K. Rows keep their `defect_signature` and `fix_decision`. An `iter-<K>.json` missing, unreadable or lacking a `phase3_findings` array carries nothing; log `prior-findings: iter-<K>.json unusable; not carried`; carry the rest.

Pass these into Step 1:
- Phase 1.0 receives `prior_checklist` and `prior_diff_head`, selects the carried items and hands only those to the generator (variance-recovery mode — see /prflow:review's Phase 1.0 and 1.2).
- Phase 2 skips dispatch for the items Phase 1.0 tagged reused (see /prflow:review's Phase 2.0.5).
- Every Phase 3 reviewer, final pass included, receives `prior_phase3_findings` as "already considered" (/prflow:review's Phase 3.1).

Log: `Fix-delta handoff: passing iter-{N-1}'s reviewed head ({prior_diff_head}) and checklist snapshot pair, and {len(prior_phase3_findings)} prior Phase 3 findings, into Phase 1+2+3.`

### Step 1: Run the Review Engine

**Engine dispatch (capability-checked; `fanned-out` and `unavailable` are the complete `dispatch_mode` set).** Before reading the review engine into this context, dispatch it as an **Agent-tool subagent**, `subagent_type: prflow:review-engine`. Compose its prompt from the entry's literal operands only — entry kind `primary` and this iteration's number `{N}`, the held `run_id` and `phase_range_max = 4.3`, the PR-mode `head_override`, the internal `progress_surface` when bound, the ordered engine-directory candidates and the captured `<loop-skill-dir>`, and (iter N≥2) the Step 0.9 carry-forward artifacts — plus the path of the shared engine-entry procedure `<loop-skill-dir>/references/engine-entry.md`; do not compose the engine's instructions inline. The agent Reads that procedure in its own context and executes it — the capability check, engine-directory resolution, completeness check, Phases 0 through 4.3, the Phase 3 roster fan-out, the no-suite-launch rule, and the return-file field set — writing the entry-scoped `engine-return-step1-iter-<N>.json` and returning `dispatch_mode` (`fanned-out` or `unavailable`) and that path. The agent's job, per `engine-entry.md`, is to invoke the `/prflow:review` engine in that fresh context. The return file carries the engine `verdict` and, on `fanned-out`, its complete Phase 4.1 `report` inline as a nonempty string — never a path, no standalone Markdown report — which Step 2's verdict routing reads; a `fanned-out` `report` that is missing, null, non-string, empty, or whitespace-only is a missing required field like a missing `verdict`, and a valid `unavailable` return carries no report. On `fanned-out`, Read the return file and fold those fields into the fused `iter-<N>.json` write this loop owns (Lifecycle → "Iter N end"). The parent copies `dispatch_mode` (top-level for Step 1, `shadow.dispatch_mode` for the shadow) from that return file, recording `null` only after a refused, dead, or malformed dispatch (which write `dispatch_disposition`), never self-assigning it. A returned `checklist` folds into `iter-<N>.json.checklist` as the per-item projection `references/fixing.md` item 7 specifies (`verification_mode`, `verdict`, `claim_signature`, `reused_from_iter_prev` and, when reused, `reused_from_iter`) — telemetry, never a carry input. It is optional (never well-formedness-required), so a `fanned-out` return lacking it stays well-formed: the loop writes `iter-<N>.json` without it. `dispatched_effort` is produced inside the subagent and not returned, so effort observability degrades to its documented fallback. Any `fanned-out` outcome that is not well-formed — the subagent died, returned a `dispatch_mode` outside the two-value set, or its return file is missing, unreadable, lacks a required field (on a re-entrant entry `diff_produced_at_head`; on a `fanned-out` entry the nonempty `report` string), or reports `root_completeness` as not established — falls back to the inline path, as a genuine `unavailable` return does; a whole-engine-subagent failure is never the Phase-3 INCONCLUSIVE-and-proceed case (which would drop the merge-gating review). Also verify the roster is not under-fanned: treat a returned `phase3_dispatched` not covering returned `expected_reviewers` (the plan's `selected`) as not well-formed. `expected_reviewers` must be present and an array; an empty array is malformed (falling back to inline) unless the return positively carries `plan_eligible`/`plan_exclusions` confirming a *justified empty plan* — the entry was primary at iteration ≥ 2, `plan_eligible` is **non-empty** (else `selected ∪ exclusions == eligible` holds vacuously over the empty set and accepts zero coverage), and `selected ∪ exclusions == eligible` (every `plan_eligible` member appears in `expected_reviewers` or in `plan_exclusions` with a `first-only` reason). When those fields are absent, malformed, or the accounting fails, an empty `expected_reviewers` falls back to inline. On iteration 1 additionally require `expected_reviewers` to cover the four always-on agents — `iterations: "first-only"` excludes nothing on iteration 1, so a reported roster short of that floor is malformed and falls back to inline. From iteration 2 do not require them here — a `first-only` override can legitimately drop an always-on agent from the fix loop's own roster (invisible to the parent), which the engine-reported roster already accounts for. Never recompute that roster from `diff_profile`, which cannot express `pr-test-analyzer`'s gate. This well-formedness fallback binds every engine-subagent dispatch — Step 1 and the Step 2.6 shadow alike; a dead or malformed shadow subagent falls back to the parent-inline shadow path. On `unavailable`, execute the engine inline per `engine-entry.md`'s resolution and execution steps (below). Gate that inline engine-root read: read the engine root only when this entry's return file exists, or when `iter-<N>.json` already carries a `dispatch_disposition` for it. A parent at that read with neither stamps `pending_dispatch` (kind `engine_step1`/`engine_shadow`) and dispatches the subagent exactly once; a re-entry finding a `dispatch_disposition` runs the engine inline without re-dispatching; a parent finding a `pending_dispatch` of that kind with no return file writes `dispatch_disposition: dead`, clears the stamp, and runs inline without re-dispatching. Record the entry's `dispatch_mode` on either arm.

The engine-entry procedure is stated once in `references/engine-entry.md`, which the dispatched `prflow:review-engine` agent Reads and executes. On the `unavailable` inline fallback, the parent Reads and executes those same steps itself, and a parent that cannot read `engine-entry.md` whole takes this entry's routing below rather than improvising the procedure. The `engine-root: incomplete` terminal routes by entry: a dispatched subagent returns it to the parent (read as not well-formed → the dispatch fallback above); a *Step 1 entry* then takes the stop below; a *Step 2.6 shadow entry* takes Step 2.6's outcome 3 (`references/shadow-review.md`).

- *Step 1 entry `engine-root: incomplete` stop.* **STOP before any mutation.** The loop halts here: it does not loop back to Step 1 and never reaches Loop Exit, so it renders no loop-verdict marker and no verdict headline — a caller routing on either reads their absence beside this reported terminal. Report the halt as non-convergence. The halt never reaches Step 3, so this iteration's fused `iter-<N>.json` emit never fires; a caller that maintains a workpad writes the record from its own blocked path, else this reported non-convergence stands in. It is never eligible for a caller's soft-proceed arm — the engine never ran, so nothing was graded; a caller routing on this loop's outcome takes its blocked terminal.

**Entry open (every engine entry, both dispatch arms; `shadow-review.md` mirrors this bracket with `--entry shadow`).** Immediately before the dispatch, run the entry helper once — the vendored literal first, the portable anchor (as elsewhere in this file) on a `command not found` / `No such file` / exit-127 reading or an `unknown subcommand` exit-2 reading from an older vendored copy. It deletes the run-scoped diff cache so the entry's Phase 0.2 rebuilds it at HEAD, snapshots the tree and writes the object ID to the entry's `dt-s1-<N>-*` scratch files under `.prflow/tmp/review/`:

```bash
.prflow/vendor/prflow/scripts/review-dirty-tree.sh entry-open --run-root .prflow/tmp/review/<slug>/<run-id> --entry step1 --iteration <N>
```

`status: ok` → dispatch. `status: error`, or no JSON from both arms → the fallback fences below, then dispatch.

Re-entrant freshness (every engine entry after the run's first — a Step 1 iteration from 2 on, and every Step 2.6 shadow; fallback). List the directory's `batch-*.patch` with the Glob tool, then repeat the literal batch operand per hit, and Glob again to confirm none remains — deletion only, never a regenerated or subsetted artifact (`references/shadow-review.md`'s blinding boundary):

```bash
rm -f .prflow/tmp/review/<slug>/<run-id>/diff.patch .prflow/tmp/review/<slug>/<run-id>/batch-<k>.patch
```

Then snapshot (same two-rung form) and Write the printed object ID (Write tool, never a redirect) to `.prflow/tmp/review/dt-s1-<n>-oid.txt`:

```bash
.prflow/vendor/prflow/scripts/review-dirty-tree.sh snapshot .prflow/tmp/review/dt-s1-<n>-before .prflow/tmp/review/dt-s1-<n>-after .prflow/tmp/review/dt-s1-<n>-disabled
```

A cache survivor, a missing `diff_produced_at_head` in the entry's return (the parent-inline arm writes it), or one unequal to `git rev-parse HEAD` at dispatch time takes that entry's failure handling — a Step 1 not-well-formed inline fallback, or a shadow's Step 2.6 outcome 3.

The dispatch-prompt operands above (`progress_surface` bound at loop entry from the caller-held `$ISSUE_NUMBER`, never synthesized later, per the Caller-origin rule) are consumed by `engine-entry.md`'s Phase 0.2 inputs; the inline `unavailable` fallback passes the same values itself. The fix loop posts no verdict; the final report goes to chat only at Loop Exit.

**Red flags — STOP and `Read` the engine from the `<engine-dir>` this entry already resolved, if you're about to:**
- Skip the Read because "I already know what /prflow:review does"
- Paraphrase the Phase 3 agent prompts instead of using them verbatim
- Treat the engine recap below as a substitute for the canonical phases
- Guess the engine directory instead of using the one `engine-entry.md`'s ordered candidate list resolved
- append focus/prioritize/scope clauses to a shadow prompt, hand it regenerated or subsetted diff artifacts, or write steering into its prompt-extension file

The engine-defined iter-N≥2 prior-findings handoff is sanctioned only for Step-1 loop iterations, never for a shadow prompt; Step 2.6 enumerates the sanctioned shadow-prompt additions.

The engine produces, for this iteration: a verdict in {APPROVE, APPROVE with notes, APPROVE WITH CAVEAT, APPROVE WITH ADVISORY NOTES, REJECT} (the `/prflow:review` Phase 4.1 enum) plus a markdown report. Phase 0.5 flags (`small_diff`, `config_only`, `has_new_types`, `checklist_skipped`) apply unchanged. Phase 0.5 scales the checklist, not the loop or the Phase 3 roster.

**Entry close (after the return, before Step 2 — a refused, dead or partial return included).** The engine subagent shares this checkout, so its dispatch prompt runs none of `gh pr checkout`, `git checkout`, `git switch`, `git worktree add`, or a `git -C <other-tree>` command. After it returns, run the close helper once (same two-rung form and skew reading as `entry-open`) with the entry's `<reviewed_head>` (the return's `diff_produced_at_head`; on a return lacking it, the `git rev-parse HEAD` the loop holds) and the branch to hold: the Step 0.5 head ref in PR mode, else the caller-held one. It runs the Post-return branch guard (`references/error-handling.md`), the compare-and-restore against the persisted OID file and this entry's Step 1.8 evidence grade, and prints one JSON line:

```bash
.prflow/vendor/prflow/scripts/review-dirty-tree.sh entry-close --run-root .prflow/tmp/review/<slug>/<run-id> --entry step1 --iteration <N> --head <reviewed_head> --branch <branch>
```

Route in this order:

- `status: branch-mismatch` → the guard's mismatch arms in `error-handling.md`; on its restored arm re-run `entry-close` once. `branch-unestablished` → the guard's unestablished stop.
- `restore: blocked` → the loop's non-convergence/Blocked path, making no fix commit (a missing or empty OID or before file, a before file no longer hashing to the persisted OID, a `SKIPPED` / `DISABLED` / `still dirty after restore attempt` breadcrumb, or the outer sentinel at compare start). `clean`, `restored` and `not-restored` continue; `restore_detail` is telemetry only — record no Important Phase 3.1 finding from it.
- `evidence.token` `PASS` with `evidence.exit` 0 → consume the verdict (Step 1.8). Any other token or exit (`FAIL` / `UNESTABLISHED` exit 3, an absent or refused marker helper, an empty token) → Step 1.8's bounded recovery; never verdict routing, the shadow pass, convergence or publication. On a return the well-formedness rule above sends to the inline fallback, `evidence` is ignored: route on `branch` and `restore` only, execute inline, then run the Step 1.8 fences below.
- `status: error`, or no JSON from both arms → the fallback: run the guard fence (`error-handling.md`); on its match arm read the OID file back (never re-hash the before file; a resumed context re-reads the file, not turn memory) and compare-and-restore, routing its breadcrumbs as the `restore` values above (a missing `dirty-tree-compare-done` token is `blocked`); then the Step 1.8 fences.

```bash
.prflow/vendor/prflow/scripts/review-dirty-tree.sh compare-and-restore <oid> .prflow/tmp/review/dt-s1-<n>-before .prflow/tmp/review/dt-s1-<n>-after .prflow/tmp/review/dt-s1-<n>-disabled ; echo dirty-tree-compare-done
```

### Step 1.8: Early run-root evidence gate (every engine entry, before its verdict is consumed)

`entry-close` grades THIS entry's own producer evidence — entry `step1` for the primary/inline return; `shadow-review.md` overrides it to `shadow` — through the same offline, non-publishing evidence authority the terminal marker uses, so an earlier iteration's evidence never satisfies the current entry. The fallback, and the recovery's re-grade below, invoke the two steps directly (vendored literal first, anchor fallback as elsewhere in this file), `<N>` and `<reviewed_head>` as literals, never `$VAR`:

```bash
.prflow/vendor/prflow/scripts/loop-verdict-marker.py write-active-entry-binding --run-root .prflow/tmp/review/<slug>/<run-id> --entry step1 --iteration <N> --head <reviewed_head>
.prflow/vendor/prflow/scripts/loop-verdict-marker.py check-evidence --run-root .prflow/tmp/review/<slug>/<run-id> --entry step1 --iteration <N> --head <reviewed_head>
```

Read the `check-evidence` line 1's first token and the exit code. `PASS` (exit 0) → consume the verdict; anything else takes the recovery, as the `evidence` arm above. The helper records each entry's grade, and while one's last grade is non-pass it refuses `write-active-entry-binding`, `check-evidence` and `compose --run-root` for every other entry: an `unrecovered-evidence-gate` refusal stops through the non-passing/blocked path naming that entry, never a new recovery. The terminal gate still rechecks at its boundary.

Workpad review-row ticks (primary/`step1` entry, bound `progress_surface = workpad` only). On a `PASS` for this primary entry under a bound `progress_surface = workpad`, and before Step 2, issue one workpad tick call recording the five review-phase rows the engine ran — the cloud-safe helper shape, issue number and substrings as literals:

```bash
.prflow/vendor/prflow/scripts/workpad.py update <issue> --tick-progress "Classify diff" --tick-progress "Generate verification checklist" --tick-progress "Verify checklist" --tick-progress "Review agents" --tick-progress "Aggregate & verdict"
```

Fall back to the anchor form (as elsewhere in this file) only on a `command not found` / `No such file` / rc-127 reading. Issue it once per primary entry; on iteration 2 and later the same call is a satisfied replay (`outcome=replay remedy=none`). The shadow entry (`shadow-review.md`, entry `shadow`) issues no tick, and a loop with no bound `progress_surface = workpad` (a standalone `/prflow:review-and-fix --issue N` run) issues none — `Run complete` stays Loop Exit's. A non-`PASS` grade ticks nothing (this call sits on the `PASS` arm). A stderr `workpad.py update: outcome=` line reporting any `remedy=` but `none`, or no outcome line at all, leaves the missed rows unticked: report it in the loop's narrative and continue to Step 2 with no second attempt — do not take the helper's `retick-named-rows` remedy — no fallback surface, and no block.

Bounded recovery (one attempt per entry). Before repair, write this entry's `evidence_recovery` marker (Schema field semantics); if it already exists for the key, the attempt is spent — stop through the non-passing/blocked path naming the missing/unestablished reason, never a second full-engine fallback. A returned verdict or summary is never itself evidence: it never authorizes synthesizing verifier files, assigning substitute nonces, deriving `property_proven` from a returned PASS, or reshaping a malformed artifact. Recover the least work by re-running the real Phase 1/2 producers in dependency order — an unavailable or verdict-only-projected original checklist requires Phase 1 checklist generation before verification; a missing verification re-runs the item's original valid `lite_probe` (§2.1a) or dispatches an actual per-item verifier (§2.1b), a missing/malformed lite probe taking the agent route, then the helper-owned §2.2 normalization (`normalize-verdicts.py`) consuming those verifier outputs and preserving their evidence and normalization audit fields, and refresh the dependent verdict; keep existing Phase-3 findings only when the reviewed state is unchanged, else recover full-engine. A qualifying earlier-iteration reuse the grader accepts still counts as actual verifier output; otherwise run the full-engine path once. Re-snapshot the recovered evidence by re-running `write-active-entry-binding`, then re-run `check-evidence` with the same `--entry step1 --iteration <N> --head <reviewed_head>` operands on the same run root: `PASS` advances (a recovered `PASS` performs the Step 1.8 workpad review-row tick above before advancing, exactly as a first-pass `PASS` does); any remaining non-pass stops through the non-passing/blocked path. New FAIL/INCONCLUSIVE findings the recovery surfaces join the refreshed verdict and route through normal fix handling; recovery preserves shadow blinding, the full reviewer roster, head/diff freshness, the explicit checklist-skip paths, and generator-failure handling, and the engine/subagent prohibition on launching the test suite.

### Step 2: Check Verdict

- Engine verdict APPROVE AND no advisory findings carry forward from any prior Step 2.5 → tentative final verdict `APPROVE`. When parked findings exist on this clean-APPROVE arm, run the parked-class sweep before **Step 2.6: Shadow review**; otherwise go directly to Step 2.6.
- Engine verdict APPROVE but advisory findings have been parked → tentative final verdict `APPROVE WITH ADVISORY NOTES`. Go to the parked-class sweep before **Step 2.6: Shadow review**.
- For this Step 2 split, advisory findings exclude `decision: "below-threshold"` rows — sweep inputs only, which do not change the verdict selected by the two arms above.
- Engine verdict APPROVE WITH CAVEAT (Phase 4.2 rule 4a — a checklist *coverage* gap, e.g. checklist generation failed; not a finding-severity verdict) → tentative final verdict `APPROVE WITH CAVEAT`. If parked findings exist on this arm, run the parked-class sweep before **Step 2.6: Shadow review**; else go directly to Step 2.6.
- Engine verdict APPROVE with notes (Phase 4.2 rule 6 — only findings *below* the engine's `verdict_severity_threshold` present, no REJECT-driver) → split on finding severity against the resolved `$FIX_THRESHOLD`:
  - If the current iteration's `phase3_findings` contains any finding whose severity is at or above `$FIX_THRESHOLD` → do NOT go to the shadow pass yet. Continue to Step 2.5 (verification gate) → Step 3 (fix), routing it exactly as a REJECT would route *for loop purposes*. The same Step 2.5 gate that guards Critical findings runs first, so a confidently-wrong finding at or above the threshold is demoted to advisory rather than applied. A finding Step 3 *cannot* fix is recorded via the existing `skip_category` pushback flow (Step 3, item 5), the same as a skipped Critical; it does not spin, because the `$MAX_ITERS`-iteration cap, the "same `(source_file, claim_text)` skipped twice → escalate to the user and stop" rule, and Step 4.5's convergence check jointly bound it (the below-Important damper additionally bounds this at `suggestion`).
  - **Below-Important damper (bounds below-`important` fix iterations after the opening window).** Within the first `$FIX_BELOW_ITERS` iterations, below-`important` findings the threshold admits route to the fixer as the bullet above describes. On an iteration N > `$FIX_BELOW_ITERS`, split the at-or-above-`$FIX_THRESHOLD` set routed this iteration: when it contains at least one Critical or Important finding, the below-`important` findings ride along to the fixer, adding no iterations of their own; when it contains none, park each below-`important` finding as advisory — append one `fix_decisions` row per finding with `decision: "below-important-damper"`, `skip_category: "below-important-damper-parked"`, and the pinned evidence marker `parked-origin: below-important-damper` (rationale-less: no `parking_evidence`, and its absence is not a missing operand) — start no fix iteration for it, set tentative final verdict `APPROVE WITH ADVISORY NOTES`, and go to the parked-class sweep before **Step 2.6: Shadow review**. A REJECT-driving finding always routes to the fixer regardless of the window (the REJECT-driver widening below). These damper-parked findings are ordinary unactioned below-`important` advisory findings — members of the reconciled parked population the shadow overlap rule and the Park-calibration gate re-read, counted in the loop's final advisory output — never excluded like a `below-threshold` sweep-only producer row.
  - If every finding is below `$FIX_THRESHOLD` → append one `fix_decisions` row per finding with `decision: "below-threshold"`, `skip_category: "below-threshold-parked"`, and the pinned evidence marker `parked-origin: below-threshold`; then set tentative final verdict `APPROVE WITH CAVEAT` and go to the parked-class sweep before **Step 2.6: Shadow review**. These rows make this parking arm derivable without reusing `advisory-parked`: exclude `decision: "below-threshold"` explicitly from the Step 2 clean-APPROVE versus `APPROVE WITH ADVISORY NOTES` “advisory findings carry forward” split, the Loop Exit `APPROVE WITH ADVISORY NOTES` trigger, and the chat headline's advisory count. Only the parked-class sweep union reads these rows. This producer covers findings parked by this arm; below-threshold findings omitted on mixed-severity iterations remain covered by the union's `phase3_findings` minus `applied` derivation.
  - Per-finding foreclosure arm (`settled-by-disclosure`). Independently of the all-below-threshold split above, any below-`verdict_severity_threshold` parked finding whose deliverable is an already-shipped disclosure is foreclosed at parking time — this arm runs on both the all-below-threshold path (above) and the mixed-severity path (where the parked below-threshold findings are otherwise row-less). Foreclosing writes one rationale-bearing `settled-by-disclosure` `fix_decisions` row — the same row shape Step 3's item 5 writes (`skip_category: "settled-by-disclosure"`, `parking_evidence` present with `source` naming the disclosure `{path, phrase}`). Foreclosure dominates: a finding foreclosed here carries the `settled-by-disclosure` row **instead of** a `below-threshold` row — exactly one row, never both. The writing precondition is `fixing.md` item 5's (below `verdict_severity_threshold`, not a REJECT driver).
- REJECT-driver widening (applies on every REJECT and every threshold combination). The loop's effective fix set is: every finding at or above `$FIX_THRESHOLD` PLUS every finding that drove the engine's REJECT (at or above `prflow_review.verdict_severity_threshold`, or driving a threshold-independent REJECT class — e.g. the Phase 4.2 self-contradicting-diff carve-out — regardless of its severity chip; excluding deferral-demoted findings) — even when that REJECT-driver is *below* `$FIX_THRESHOLD` — so a `verdict_severity_threshold` more inclusive than `$FIX_THRESHOLD` (e.g. verdict `suggestion`, fix `important`) never deadlocks the loop. These REJECT-drivers route through Step 2.5 → Step 3 like any other fixable finding.
- Engine verdict **REJECT** → continue to Step 2.5. (REJECT verdicts never reach the shadow pass — the loop is still finding things to fix; converge first.)

### Clean-iteration-1 exit (only under `progress_surface = workpad`)

Under `/prflow:implement` the caller's PR-level review is an independent full pass, so a clean iteration 1 owes no confirmation pass. Evaluate this at iteration 1 only, at two points: where Step 2 sends a tentative non-REJECT verdict to Step 2.6, and after Step 3.5 where Step 4 would loop back to Step 1. When iteration 1 is clean, do not dispatch the shadow and do not start iteration 2:

1. Post-fix point only: take iteration 1's engine verdict as the tentative final verdict, mapped as Step 2 maps it, and run the parked-class sweep when parked findings exist.
2. Run Step 2.6's Park-calibration gate as the Step 4.5 early-exit path does; a re-grade promotes as it does there and voids this exit.
3. Write top-level `shadow_skipped: {"reason": "iteration-1-clean", "head": "<git rev-parse HEAD>"}` into `iter-1.json` — never beside a `shadow` block — and go to Loop Exit, which renders the skip.

Iteration 1 is clean only when every operand below is established from `iter-1.json` and the iteration's engine return; an unestablished operand is not clean, and every not-clean case runs the loop unchanged:

- The engine verdict is non-REJECT, `checklist` holds no `FAIL` or `INCONCLUSIVE` verdict, `diff_profile.checklist_skipped` is not `"failure"`, and `phase3_failed_agents` is `[]`.
- Every `phase3_findings` entry is below Important — by its `severity`, or by the `calibrated_severity` of its `severity-calibrated` `fix_decisions` row. A Critical or Important that was fixed, pushed back, deferred or parked is not clean: a disputed finding is where the shadow's second opinion matters most.
- When iteration 1 committed a fix, `reference_reads.fix_delta` (persisted first, as Step 3.5 requires) reads `status: "verified"` with `outcome` `clean`, or `refixed` with no gate finding at Critical/Important — Step 3.5 gates every fix commit at any severity, so below-Important fixes do not make iteration 1 unclean.
- `parked_class_sweep`, when it ran, reads `dispatch: "verified"`, `truncation: null`, and an empty promotable set (`pre-fix-gates.md`, Routing).

This exit never applies outside `progress_surface = workpad`, to a caller's re-review of its own hand-fix, or where a consumer extension's declared shadow trigger holds. It is this procedure's rule, never an election: no budget or context belief widens it.



<!-- END loop-control.md -->
