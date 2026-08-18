---
name: review-and-fix
description: Use when the user wants problems in a pull request or the current branch both found AND corrected — "review my changes and fix what's wrong", "clean up whatever the review turns up", "address the review feedback on this branch", "tidy this PR up before merge", "find and fix the issues here". Requires explicit fix intent; an unqualified request to review something goes to prflow:review instead.
argument-hint: "[pr-number] [--push-each-iteration] [--issue N]"
---

# /prflow:review-and-fix — Review, Fix, and Verify Loop

You are the review-and-fix orchestrator. Run /prflow:review's review engine, fix the findings it surfaces, and re-run until the engine returns a clean verdict.

**Input:** `$ARGUMENTS` may contain an optional PR number, the flag `--push-each-iteration`, and/or the flag `--issue N`. Parse the three independently — any, all, or none may be present. If no PR number is given, review and fix the current branch. The **bare** numeric token (if any) is `$PR_NUMBER`; the `--issue` value (if any) is `$ISSUE_OVERRIDE`. A value following `--issue` is never read as the PR number — only a bare numeric token binds `$PR_NUMBER`. **Every later PR-mode predicate and every `gh` command reads `$PR_NUMBER` — never the raw `$ARGUMENTS` string**, which fails an is-a-PR-number test and leaks the flag tokens into any command it is interpolated into.

**`--push-each-iteration` (default off).** When set, each fix and Loop Exit use the gated base checkpoint and push, keeping the PR and CI current. Otherwise fix commits stay local and the base is untouched. The flag never posts a GitHub verdict; mandatory telemetry persistence remains independent. Loop correctness uses local `HEAD` (with the PR head override), not pushed state.

**Key principle:** You perform fixes DIRECTLY in this session. Do NOT delegate fixes to a subagent. You need full conversation context to apply `prflow:receiving-code-review` principles (technical evaluation, pushback, verification).

**Subagent dispatch is user-requested at the loop's own dispatch points (injection-condition clause).** Invoking `/prflow:review-and-fix` **is** the user's request for subagent dispatch at the points that are this loop's own — the Step 2.6 shadow fan-out, the Step 3.5 fix-delta gate, the Step 3 scoped `comment-analyzer` re-dispatch, the parked-class sweep, and the Loop Exit post-shadow edit gate — thereby satisfying any injected "do not call the AgentTool unless the user requested it" condition there and nowhere else, and authorizing none of the inline work: you still perform fixes DIRECTLY and never delegate a fix, or the whole engine, to a subagent. (The shared engine's own dispatch points are authorized by the `/prflow:review` clause this loop inherits and does not copy.)

**Portable helper anchor (single-statement).** The bundled-helper commands in this skill resolve the skill directory inline at each call site via `${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}`. When `$CLAUDE_SKILL_DIR` is set and non-empty (Claude Code), run each command exactly as written. On a runner where it is unset or empty, replace the placeholder with the skill base directory the runner reports in context (e.g. a `Base directory for this skill:` line); if that reported path is Windows-form (`C:\...`), first convert it to this shell's POSIX form with one standalone `wslpath -u '<path>'` (WSL) or `cygpath -u '<path>'` (Git Bash/MSYS2) command and substitute the printed result **only if the command succeeds and prints a non-empty path — otherwise fall through to the drive-letter rules exactly as if the tool were absent** (lowercase the drive letter, map `C:\` to `/mnt/c` on WSL or `/c` on MSYS2, and turn backslashes into `/`; if the environment is neither WSL nor MSYS2, use the path unchanged and report that it could not be normalized). Resolve the anchor inline at every call site — never capture it into a shell variable that a later statement reads, because some runners' inline-bash marshaling drops such variables. If neither `$CLAUDE_SKILL_DIR` nor a runner-reported base directory is available, stop and report that the helper anchor could not be resolved rather than running a command with a broken path.

**Cloud command-shape discipline.** A granted command *head* is not sufficient: the cloud runner's harness — the `command` tier this bundle runs under, and the review tier the shared engine runs under — denies whole command *shapes* even when every head is granted, silently, burning budget until a run can end with no verdict. This is **additive to the three call-form rules in this bundle root** — the inline-resolved portable anchor, the granted vendored-literal leading token, and the tier-agnostic invocation procedure. Keep every command you emit to a **permitted** shape, consistent with the equivalent discipline in `skills/review/SKILL.md` whose engine this bundle executes inline. The permitted and denied shapes are:

- **Permitted:** only shapes with evidence on this profile: authoring a file with the **Write tool** under `.prflow/tmp/**`, the specific recorded `tee` forms, and the specifically recorded command-substitution forms. A granted command head does **not** establish that a statement containing a redirect is permitted; each complete shape needs its own evidence.
- **Denied — never emit:** a helper invocation that is not the statement's leading token — no leading `VAR=value` assignment or env-prefix (`M=x cmd …`), no leading `cd`, and no `echo … &&` or other command prefix ahead of the helper; a scratch write targeting `/tmp` rather than `.prflow/tmp/**` (a `> /tmp/…` or `>> /tmp/…` redirect, or any other authoring under `/tmp`); the Write tool outside `.prflow/tmp/**`; a `cat`-headed heredoc write to any target (use the Write tool or `tee` instead); a stderr redirect that AUTHORS a file, measured refused even for a target inside the workspace — read stderr from the invocation's own tool result instead (`2>/dev/null` discards rather than authoring, and is unmeasured either way); an interpreter head (`python3` / `python` / `node`); the *unexpanded* helper anchor placeholder as a leading token (emit the resolved vendored-literal path instead; this does not bar the tier-agnostic procedure's anchor fallback arm).
- **Scratch writes target `.prflow/tmp/**`, never `/tmp`.** Author run-scoped scratch with the Write tool — or a `tee` heredoc where no Write tool exists — under `.prflow/tmp/**`; a `/tmp`-targeted redirect or heredoc is a denied shape.
- **Hard rule: after a second permission denial of a shape, switch to a permitted alternative from this list — never iterate variants of the denied shape.** Iterating denied variants is what exhausts the run's budget and ends it with no verdict.

**Consumer prompt extension (load first).** This skill's consumer extension reaches you through exactly one channel — the invocation ladder below — so load it yourself with that ladder, unconditionally, at the start of the run; nothing else delivers consumer policy into this skill. **Read the ladder's output whole** — no `>/dev/null`, no `| head -<n>`, no truncation of any kind — because an extension whose text you never observed governs nothing in this run, including the rules that say so. This load covers only this file: the review engine this skill loads by `Read`ing `skills/review/SKILL.md` as a file carries its own ladder, which the engine runs on the prose path inside the fix loop. From the repo root, run the **granted vendored-literal leading token** — the cloud matcher denies the unexpanded anchor as a leading token, so this is the form that executes on the cloud tiers:

```bash
.prflow/vendor/prflow/scripts/load-prompt-extension.sh review-and-fix
```

**Tier-agnostic invocation procedure (the conditional form — do not classify your own tier).** Emit the vendored literal above first. On a `command not found` / `No such file` / exit-127 reading (this repository's own local tier, where `.prflow/vendor/` is materialized only at runtime), re-invoke **the same helper with the `.prflow/vendor/prflow/` prefix removed** (`scripts/load-prompt-extension.sh review-and-fix`) and route on that outcome; if that too is not found (a non-Claude-Code runner where neither repo-relative path exists), fall back to the portable anchor form below:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh review-and-fix
```

**Every extension-state failure arm below fires unconditionally** — this ladder is the only channel, so a failure you do not report drops consumer policy from the run silently. A missing helper path (`No such file`/exit 127) on **every** form above is the **anchor-resolution** failure above — report it in the loop's output, since it breaks every other bundled-helper call site in this run; fix the anchor, don't report a missing extension. A harness refusal of the command — a permission denial rather than a missing file — leaves the extension's state **unestablished**: report that in the loop's output and never read it as a clean policy pass (*unknown is not zero*). Any other non-zero exit means a consumer extension exists but could not be loaded — surface its stderr, never proceed silently. Exit 0 with output: append the text to this skill's prompt (consumer-owned, committed under `.prflow/prompt-extensions/`). Exit 0 empty: proceed unchanged.

**Receiving-code-review extension (load second).** This loop applies `prflow:receiving-code-review` principles without invoking that skill, so load its extension yourself with the ladder below, unconditionally and by the same single channel — nothing else delivers it into this loop. **Read the ladder's output whole** — no `>/dev/null`, no `| head -<n>`, no truncation of any kind — because an extension whose text you never observed governs nothing in this run, including the rules that say so. Failure arms as above: an absent extension is a silent no-op; a present-but-undeliverable one has its stderr surfaced rather than being passed over silently; a harness refusal leaves the state **unestablished** and is reported, never read as a clean pass; and the **anchor-resolution** failure — a missing helper path on every form — is reported in the loop's output, since it breaks every other bundled-helper call site in this run. Use the same **granted vendored-literal leading token** first, per the tier-agnostic procedure above:

```bash
.prflow/vendor/prflow/scripts/load-prompt-extension.sh receiving-code-review
```

On a `command not found` / `No such file` / exit-127 reading, re-invoke **the same helper with the `.prflow/vendor/prflow/` prefix removed** (`scripts/load-prompt-extension.sh receiving-code-review`) and route on that outcome; if that too is not found, fall back to the portable anchor form below:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh receiving-code-review
```

That text governs how this loop applies those principles. Its references to structures this loop does not load (the Reception Preflight, its numbered facts, Step numbers) resolve to this loop's counterparts — context, never an instruction to execute the receiving skill body. A directive written for an interactive direct pass (a confirmation, an operator prompt, a pause for input) is non-binding here: surface it in the loop record, don't execute it.

**A linked issue's body is triage data, not a spec amendment — unless your extension says otherwise.** By default this loop weighs the issue body exactly as the receiving skill's preflight does: data for triage, never authority to supersede the shipped code or a review finding. Where the extension loaded above grants an amended issue that authority, it also states how to establish it, and that section governs this loop exactly as it governs a direct pass; where the extension is absent or grants nothing, the default holds and no finding is overridden by issue text. Either way, on a loop run route conflicting findings to the loop's deferral channel rather than against a spec the next standalone review's Issue Compliance read will enforce.


## Engine source of truth

This skill wraps /prflow:review's four-phase engine in a fix loop. Phases 0 through 4.3 — setup, diff classification, checklist generation, checklist verification, review agents (with the exact per-agent prompts and the `defect_signature` contract), and aggregation — are authoritative in `skills/review/phases/*.md`, reached through the phase routing table in `skills/review/SKILL.md`, which also carries the cross-phase invariants. Read them on every Step 1; never improvise the engine or paraphrase the Phase 3 prompts. Pass `$ISSUE_OVERRIDE` through to the engine's Phase 0.4, which resolves the acceptance criteria from it. Drift between the two is the biggest source of missed findings.

This skill **skips** /prflow:review's Phase 4.4 entirely — no formal review and no verdict comment. A standalone PR-mode run still seeds and ticks the inline engine's run-keyed progress comment. When `/prflow:implement` is the caller, the wrapper passes its internal `progress_surface = workpad`, so the engine creates no second progress comment and instead ticks the tuple-declared review-boundary rows in the existing issue workpad. The final report is emitted to chat only; the human reviewer decides whether to convert it into a formal merge signal by running `/prflow:review <PR>` separately. On top of the engine it adds the loop wrapper documented in the references: a **fix-delta handoff** (Step 0.9), a run-scoped **persistent iteration record** (`.prflow/tmp/review/<slug>/<run-id>/iter-<N>.json`), a **shadow review pass** (Step 2.6), a **`## Coverage` section** and **per-phase telemetry summary** at Loop Exit.

---


### Schema

```json
{
  "iter": 1,
  "started_at": "2026-05-16T20:45:00Z",
  "fix_commit_sha": "abc1234",
  "fix_files": ["src/example_pkg/foo.py", "tests/test_foo.py"],
  "loop_role": "fix | promoted",
  "promotion_provenance": "shadow | park-calibration-post-shadow | park-calibration-pre-shadow (promoted iterations only)",
  "current_step": "2.6",
  "current_substep": "run_shadow_fanout",
  "pending_dispatch": {"kind": "shadow_reviewer_fanout", "roster": ["prflow:code-reviewer", "prflow:silent-failure-hunter"], "dispatched_at": "2026-05-16T20:46:00Z"},
  "sweep_defs_read": [{"path": "phase-2-implement.md", "read": "whole", "sweeps": ["2.3.0"]}, {"path": "phase-2-sweeps-contract.md", "read": "whole", "sweeps": ["2.3.0a"]}, {"path": "phase-2-sweeps-quality.md", "read": "whole", "sweeps": ["2.3.1"]}, {"path": "references/sweep-2-3-1-orphaned-setup.md", "read": "whole", "sweeps": ["2.3.1"]}],
  "sweep_evidence": {"status": "run"},
  "checklist": [
    {
      "id": "VC-1",
      "claim": "...",
      "file": "src/example_pkg/foo.py",
      "verification_mode": "lite",
      "claim_signature": "api_contract:foo.py:spdx-header-present",
      "verdict": "PASS",
      "raw_verdict": "FAIL",
      "normalized": true,
      "evidence": "...",
      "reused_from_iter_prev": false
    }
  ],
  "dispatched_effort": [
    {"agent": "prflow:checklist-generator", "phase": "1", "requested": "low", "resolved": "low", "application_point": "session-fallback", "effective": null, "fallback_reason": "per-agent effort 'low' resolved but not applied: no in-session per-agent effort seam"}
  ],
  "phase3_dispatched": [
    "prflow:code-reviewer",
    "prflow:silent-failure-hunter",
    "prflow:comment-analyzer",
    "prflow:requesting-code-review",
    "prflow:type-design-analyzer",
    "prflow:pr-test-analyzer"
  ],
  "diff_profile": {
    "small_diff": false,
    "config_only": false,
    "has_new_types": true,
    "engine_self_modifying": false,
    "checklist_skipped": null
  },
  "phase3_findings": [
    {
      "agent": "prflow:code-reviewer",
      "severity": "Critical",
      "description": "...",
      "defect_signature": {"file": "src/example_pkg/foo.py", "line_range": [42, 47], "kind": "null_deref"},
      "corroboration_count": 2,
      "step25_classification": "codebase | web_confirmed | web_refuted | web_inconclusive | over_budget | tools_unavailable",
      "fix_decision": "applied | pushed_back | deferred | advisory | severity-calibrated"
    }
  ],
  "fix_decisions": [
    {"finding_id": "F-3", "decision": "applied", "commit": "abc1234"},
    {
      "finding_id": "F-7",
      "decision": "pushed_back",
      "source_file": "src/example_pkg/foo.py",
      "claim_text": "function returns None when input is empty",
      "skip_category": "claim-quality",
      "evidence": "lines 200-220 of foo.py show the empty-input branch raises ValueError instead",
      "parking_evidence": {
        "basis": "the code handles the empty-input branch correctly; the claim misreads it",
        "failing_input": "empty input to the function",
        "source": "src/example_pkg/foo.py:200-220",
        "finding_ref": {"iter": 1, "index": 1}
      }
    },
    {
      "finding_id": "F-9",
      "decision": "deferred",
      "source_file": "src/example_pkg/bar.py",
      "claim_text": "race condition in concurrent writer",
      "skip_category": "already-tracked",
      "evidence": "issue 42",
      "parking_evidence": {
        "basis": "a separate open issue already tracks this defect",
        "failing_input": "the concurrent-writer race the finding describes",
        "source": "issue 42",
        "finding_ref": {"iter": 1, "index": 2}
      }
    },
    {
      "finding_id": "F-11",
      "decision": "deferred",
      "source_file": "src/example_pkg/baz.py",
      "claim_text": "preexisting style violation on line 88",
      "skip_category": "out-of-scope",
      "evidence": "git blame shows line 88 unchanged by this PR (last touched in commit 9abcdef, three months ago)",
      "parking_evidence": {
        "basis": "the flagged line is pre-existing code this PR's diff does not touch",
        "failing_input": "the pre-existing style violation on line 88",
        "source": "git blame: line 88 last touched in commit 9abcdef, three months ago",
        "finding_ref": {"iter": 1, "index": 3}
      }
    },
    {
      "finding_id": "F-13",
      "decision": "deferred",
      "source_file": "src/example_pkg/qux.py",
      "claim_text": "log message is slightly imprecise about which retry attempt failed",
      "skip_category": "uncategorized",
      "evidence": "real but minor wording nit; not worth a fix-loop iteration"
    },
    {
      "finding_id": "F-15",
      "decision": "advisory",
      "source_file": "src/example_pkg/quux.py",
      "claim_text": "claim about a specific Postgres lock mode behavior",
      "skip_category": "advisory-parked",
      "evidence": "Step 2.5 demoted this finding after WebFetch verification; refuted by https://www.postgresql.org/docs/current/explicit-locking.html",
      "parking_evidence": {
        "basis": "web verification refuted the claim against the canonical Postgres locking docs",
        "failing_input": "the specific lock-mode interaction the finding asserted",
        "source": "https://www.postgresql.org/docs/current/explicit-locking.html",
        "finding_ref": {"iter": 1, "index": 4}
      }
    },
    {
      "finding_id": "F-16",
      "decision": "below-threshold",
      "source_file": "src/example_pkg/quuz.py",
      "claim_text": "same-class advisory instance",
      "skip_category": "below-threshold-parked",
      "evidence": "parked-origin: below-threshold"
    },
    {
      "finding_id": "F-17",
      "decision": "severity-calibrated",
      "source_file": "src/example_pkg/corge.py",
      "claim_text": "missing key crashes the loader",
      "original_severity": "Critical",
      "calibrated_severity": "Important",
      "evidence": "over-grade gate shape 1 (fail-closed): the loader raises KeyError on the missing key and test_loader_missing_key catches it RED — a loud bounded stop, not a silent corruption; recorded technical evaluation, did not auto-demote"
    }
  ],
  "convergence_inputs": {
    "fixes_applied": 4,
    "fix_diff_lines": 22,
    "new_corroborated_critical_count": 0
  },
  "cap_drops": {
    "count": 0,
    "by_category": {}
  },
  "parked_class_sweep": {
    "classes": [
      {
        "source_finding_ids": ["F-16"],
        "kind_literal": "unchecked_type",
        "sites_examined": ["src/example_pkg/quuz.py:40-72"],
        "new_siblings": [
          {"finding_id": "F-18", "site": "src/example_pkg/quuz.py:63-66", "severity": "Suggestion", "disposition": "advisory", "marker": "parked-sibling: class-sweep", "parking_evidence": {"basis": "parked by the parked-class sweep registration as a below-threshold sibling of class unchecked_type", "failing_input": null, "source": "src/example_pkg/quuz.py:63-66", "finding_ref": {"iter": 1, "index": 5}}}
        ]
      }
    ],
    "truncation": null,
    "dispatch": "verified"
  },
  "reference_reads": {"fix_delta": {"status": "verified|not_verified", "outcome": "clean|refixed|promoted", "reason": null}},
  "shadow": {
    "ran_at": null,
    "reviewed_sha": null,
    "verdict": null,
    "coverage": null,
    "prompt_addenda": null,
    "reviewers_dispatched": [],
    "expected_reviewers": [],
    "reason": null,
    "checklist_skipped": null,
    "phase3_findings": [],
    "phase2_fails": [],
    "comparison": {
      "shadow_total": 0,
      "overlap_with_iter_N": 0,
      "new": 0,
      "new_critical": 0,
      "new_important": 0
    },
    "promoted_to_iter_next": false
  },
  "park_calibration": {
    "evidence_comparisons": [
      {
        "parked_finding_ref": {"iter": 1, "index": 4},
        "parked_finding_id": "F-15",
        "shadow_finding_index": 0, /* see loop-control.md's park_calibration shape */
        "relation": "equivalent",
        "rationale": "shadow re-raises the same Postgres lock-mode claim on the same evidentiary basis, adding no new failing input",
        "operands_present": true,
        "disposition": "preserved"
      }
    ]
  },
  "telemetry": {
    "phase_0":    {"calls": 0, "tokens": 0,     "wall_clock_s": 1.2},
    "phase_0_5":  {"calls": 0, "tokens": 0,     "wall_clock_s": 0.3},
    "phase_1":    {"calls": 2, "tokens": 9400,  "wall_clock_s": 28},
    "phase_1_5":  {"calls": 1, "tokens": 3100,  "wall_clock_s": 11},
    "phase_2":    {"calls": 27,"tokens": 95000, "wall_clock_s": 220},
    "phase_3":    {"calls": 5, "tokens": 48000, "wall_clock_s": 180},
    "step_2_5":   {"calls": 0, "tokens": 0,     "wall_clock_s": 4,  "webfetches": 2},
    "step_2_6":   {"calls": 35,"tokens": 155000,"wall_clock_s": 440}, /* aggregates a full Phases 0–4.3 fan-out (tens of agent calls), not a single call — contrast phase_3's 5 above */
    "phase_4_x":  {"calls": 0, "tokens": 0,     "wall_clock_s": 1}
  }
}
```

**Field semantics** — `loop_role`, `dispatched_effort`, `phase3_dispatched`, `diff_profile`, `cap_drops`, `shadow`, and the durable operands `current_step`/`current_substep`/`pending_dispatch` — are documented in `references/loop-control.md` (*Schema field semantics*). `ITER_EXPECTED_FIELDS` in `lib/efficiency-trace.sh` is the single-source set the unconditional top-level fields mirror.

### Lifecycle

- **Iter 1 start:** create the run-scoped directory `.prflow/tmp/review/<slug>/<run-id>/` if missing (using the `RUN_ID` computed once at loop start). There is no prior iteration to read.
- **Iter N start (N≥2):** before doing anything else, read `iter-<N-1>.json`. The fix-delta handoff (Step 0.9) and convergence check both consume it. If the file is missing or unreadable, log a warning and continue without the handoff optimizations (Phase 1 generator runs without the prior-checklist variance-recovery block; Phase 2.0.5 reuses nothing; Phase 3 runs without prior-findings context). Phase 1+2+3 still run — they always do.
- **Iter N end — non-optional emit, fused to the fix commit:** write `iter-<N>.json` with everything collected during the iteration. The write is **anchored to Step 3's item 6's fix-commit moment** (capture `fix_commit_sha`, then Write, as one step) rather than deferred to a separate end-of-iteration step, so an inline-driven loop has no seam in which to lose it. Writing this per-iteration record is **mandatory on every iteration regardless of how the loop was executed** — whether this loop ran as a `Skill` invocation or was hand-run via direct `Agent` dispatch on a degraded path — and it is written **with the Write tool, never a shell output redirect or heredoc**. The `lib/efficiency-trace.sh --persist` synthesis backstop is a *floor* that reconstructs a minimal record from the fix commits when this emit is dropped — never license to skip it. See Step 3's item 7 for the full record shape and fields.
- **Step 2.6 end (shadow pass) — non-optional emit, fused to the pass's termination:** when the shadow review pass runs, append the `shadow` block to the latest iter's iteration record (re-writing `iter-<N>.json` with the shadow result included) with the **Write tool**. This is **mandatory on every shadow pass regardless of how the loop was executed**, and it is fused to the moment the pass *terminates* — covering **both** termination paths (Parse-and-compare completion for a full fan-out, and the honest-degradation fail-safe for an outcome-3 pass that dies mid-fan-out). If the shadow promotes new findings into iter (N+1), iter (N+1) is a normal iter from a lifecycle standpoint — it will write its own `iter-<N+1>.json` per the regular end-of-iter rule.

The iteration record (the fix loop's local per-iteration JSON file `.prflow/tmp/review/<slug>/<run-id>/iter-<N>.json`) is best-effort and informational — it is a local scratch file, distinct from the GitHub issue comment that `/prflow:implement` calls the *workpad*. A write failure should not abort the loop — log it and continue.

---


## Running the loop

The loop control — config resolution, Iteration Start, Step 0.5 (PR-mode branch sync), Step 0.9 (fix-delta handoff), Step 1 (run the engine — load `/prflow:review`'s SKILL.md), and Step 2 (check verdict) — lives in `references/loop-control.md`. Load it at loop entry per the *Reference-loading contract*, follow it, and from Step 2's verdict route to the step references via the **Step routing** table below. Like every reference it is loaded on demand, not held resident.

## Step routing (which reference implements each step)

Every loop step's authoritative procedure lives in a file under `skills/review-and-fix/references/` and is loaded at step entry (the *Reference-loading contract* below governs how); the root retains the invocation contract, `### Schema`, `### Lifecycle`, routing, terminal mapping, and fail-closed handling, and never paraphrases a reference's procedure. When any prose names "Step N.M", resolve it to its reference via this table.

| Step (`current_step`) | Reference file | Fires when |
| --- | --- | --- |
| `loop-control` — Iteration setup + Steps 0.5–2 | `references/loop-control.md` | loop entry, and throughout config resolution, branch sync, fix-delta handoff, review-engine execution, and verdict routing |
| `2.5` — Pre-fix verification gate + Parked-class sweep | `references/pre-fix-gates.md` | Step 2 routed to a fix path (REJECT, a REJECT-driver, or an at-or-above-`$FIX_THRESHOLD` finding), **or** a tentative non-REJECT verdict carries parked findings needing the pre-shadow parked-class sweep |
| `2.6` — Shadow review | `references/shadow-review.md` | a tentative non-REJECT verdict at convergence time, **or** the `engine_self_modifying` early-shadow trigger after iteration 1 |
| `3` — Fix Findings | `references/fixing.md` | after the Step 2.5 gate resolves the effective fix set |
| `3.5` — Fix-delta verification gate | `references/fix-delta-gate.md` | every iteration that committed a fix (unconditional; skipped only on a no-fix iteration) |
| `4.5` — Convergence check | `references/convergence.md` | before looping back to Step 1, on iteration ≥ 2 |
| `loop-exit` — Loop Exit | `references/loop-exit.md` | the loop terminates (converged, capped, or final REJECT) |

## Reference-loading contract (fail-closed)

Every step reference loads at entry, **before any action in that step**, and a reference that cannot be loaded whole takes the mapped fail-closed outcome below — never an improvised step from memory.

**Entry-gate read shape:**

1. **Stamp the position** (best-effort Write, non-blocking): set `current_step` (and `current_substep` when meaningful) in the active `iter-<N>.json` before reading, so a compacted/resumed run recovers its position from the record, not recall. **Exception — first `loop-control` entry:** its slug/`RUN_ID` recipe lives there; read it first, then stamp (may create a stamps-only `iter-<N>.json`, completed by item 6's Write). Use `current_step: "loop-control"` while executing config resolution and Steps 0.5–2. Immediately before every `Agent`/`Task`/`Skill` dispatch, also write `pending_dispatch: {kind, roster, dispatched_at}`. That obligation covers the dispatches **this reference itself issues**; a dispatch made while executing the review engine's phases inline is the engine's own and is not stamped here. Clear it after the returned attempt is joined or dispositioned, including failure, timeout, exhausted-retry, and not-verified outcomes; retain it only while the attempt is unresolved. A dispatch without those writes has not satisfied the continuation contract.
2. **Read the reference.** Resolve the skill directory per the *Portable helper anchor* rule above and `Read` `<skill-dir>/references/<name>.md`.
3. **Completeness check — the single ordered start/end boundary rule.** The returned content's first non-blank line MUST be the reference's canonical `# Reference: <title>` heading and its last non-blank line MUST be the canonical `<!-- END <name>.md -->` marker, **each occurring exactly once, in that order**. A `Read` failure, an empty result, a truncated result, a result missing either marker, a **duplicated** marker, a **reversed** order (END before START), or a marker at a **noncanonical** position (not at the document edge) all mean **reference unreadable** and take the failure-map row below.
4. On success, execute the reference's procedure; on failure, apply the failure-map row — do not enter the step.

**Failure-map (per reference):**

| Unreadable reference | Outcome |
| --- | --- |
| `pre-fix-gates.md` | **STOP before any mutation.** No fix without gate coverage. Record a `blocked` reflection; report non-convergence. |
| `shadow-review.md` | Record `shadow.coverage: "not_verified"` on the active iter (the existing outcome-3 shape) — **prohibits a clean approve**. Then branch on the **trigger context**: a **convergence-time** trigger proceeds to Loop Exit reported not-verified; an **early** `engine_self_modifying` trigger (after iteration 1) instead continues the loop as in the `convergence.md` row. An unreadable reference is a covered degradation cause, so both arms above are legal; what is prohibited is *electing* to skip the shadow to save budget — a run that never dispatched the shadow may not report its result as independently audited, nor present the shortfall as though the audit had happened to it, since that reports an unaudited PR as a reviewed one. The legal exit is the one `shadow-review.md`'s never-elective paragraph names: a workpad-holding caller stops at a non-terminal or `Blocked` status naming what prevented the fan-out, and a caller with no workpad reports non-convergence and posts no clean approve-family verdict (the `pre-fix-gates.md`/`fixing.md` terminal). |
| `fixing.md` | **STOP before any mutation.** Never apply a fix blind. Record a `blocked` reflection; report non-convergence. |
| `fix-delta-gate.md` | Record a not-verified fix-delta outcome (the existing gate-subagent-failure shape) in the formal `reference_reads.fix_delta` field, which **prohibits a clean APPROVE-family verdict** for this run. |
| `convergence.md` | Treat as "a convergence condition failed" — never early-exit: loop back to Step 1 for iteration N+1, or at the cap proceed to Loop Exit reporting non-convergence. |
| `loop-exit.md` | Run the persistence backstop directly (`lib/efficiency-trace.sh --persist`), record an **incomplete terminal state** reflection, and emit a generic non-clean chat message (never an APPROVE-family template) — **prohibits a clean approve**. |
| `loop-control.md` | The loop spine (config, Iteration Start, Steps 0.5/0.9/1/2), loaded at loop entry: **STOP before any mutation**. Record a `blocked` reflection; report non-convergence. |
| `error-handling.md` | Contextual guidance (not a loop step) — **best-effort**: log and continue; its absence degrades only guidance, never a gate. Its fail-closed-*looking* prose (the shadow-reviewer exception, the engine-location fatal) echoes contracts *owned* by `shadow-review.md` and `loop-control.md`/Step 1, each with its own row above. |

**Always-resident re-read rule.** **Two returns of control fire it:** an `Agent`/`Task`/`Skill`-tool return that resolves — in whole or in part — a `pending_dispatch` **the active reference stamped**, and the handback that ends an engine entry **this reference executed inline** (control coming back to Step 1's verdict routing, or to the Step 2.6 shadow's parse-and-compare). After **every** such return, and **before the next cross-reference routing action**, re-`Read` the active reference — identified by `current_step`/`current_substep` in the active `iter-<N>.json`, **not** by conversational memory — and resume the interrupted substep; never re-dispatch the agent/skill that just returned. A dispatch made **while executing the review engine's own phases inline**, which this reference never stamped — including every Phase 3 reviewer the engine dispatches during Step 1 — does **not** fire it: the engine's own **phase procedure** governs its phases, and its **Entry-gate** in `skills/review/SKILL.md` binds every phase entry and every shadow entry — read the requirement there; it is deliberately not restated here. The durable operands are the step predicate; **agent recall is never the sole predicate**. **Absent operand → fail closed, never recall.** Absent `current_step`/`current_substep` (unstamped, or an unreadable `iter-<N>.json`) is re-stamped from the last reference entry-gate, or — if unrecoverable — takes the step's fail-closed not-verified failure-map outcome; a `pending_dispatch` missing for a dispatch still in flight is re-written from the live dispatch operands where the parent still holds them, and otherwise takes that fail-closed not-verified outcome directly. Neither is **ever** inferred from conversational memory.


### Step 4: Continue Loop

Output: `Fixed {N} issues, skipped {M}. Re-running review...`



## Terminal verdict → chat output (mapping)

The externally-visible terminal contract that downstream callers (e.g. `/prflow:implement` Phase 3.3) rely on. The authoritative rendering (headlines, counts, deferrals manifest, coverage/telemetry appendix) lives in `references/loop-exit.md` under *Verdict → chat output*, and may only be rendered **after** its Pre-mapping gates have run (see the *Step routing* `loop-exit` row).

| Converged verdict | Terminal chat outcome |
| --- | --- |
| `APPROVE` | clean approve — only when shadow `coverage: "full"` and no gate prohibits it |
| `APPROVE WITH ADVISORY NOTES` | approve, surfacing the parked advisory findings |
| `APPROVE WITH CAVEAT` | approve, surfacing the verification-coverage caveat (incl. shadow `not_verified`) |
| `APPROVE WITH UNRESOLVED SHADOW FINDINGS` | non-clean approve — iteration-cap outcome 2 |
| `REJECT` | non-clean — cap exhausted, convergence exit still REJECT, or a post-shadow Critical |
| incomplete / not-verified (any fail-closed reference outcome above) | a generic non-clean message; **never** an APPROVE-family template |

Alongside the human headline, the loop emits **one producer-emitted machine-readable marker line** carrying the same verdict + coverage facts, as line 1 of the chat output, so a caller need not string-match the prose across a plugin-version boundary. It is composed by `scripts/loop-verdict-marker.py`, never hand-written; the authoritative rendering rule (its fields, its fixed line-1 position, and the both-directions version-gap compatibility) lives in `references/loop-exit.md` under *Verdict → chat output*.

Read `references/error-handling.md` at invocation, before the loop (*When NOT to use* gates applicability), and again on any tool/commit/test failure.
