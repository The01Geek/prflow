---
name: review
description: 'Use when the user wants code assessed rather than changed — "review PR 88", "is this branch ready to merge?", "look over my changes", "any problems with this diff?", "give me a code review", "what do you think of this PR?", "sanity-check this branch", "ship it?". Applies to a pull request or the current branch when findings, a verdict, or a merge-readiness opinion is wanted. This is the default for an unqualified review request; use prflow:review-and-fix only when the user explicitly asks for the problems to be corrected.'
argument-hint: "[pr-number] [--issue N]"
---

# /prflow:review — Comprehensive PR Review

You are the review engine orchestrator. Run a four-phase review and present an APPROVE/REJECT verdict.

Input: `$ARGUMENTS` may contain an optional PR number and/or the flag `--issue N`; either, both, or neither may be present. Only a bare numeric token binds `$PR_NUMBER` — never a value following `--issue`. The flag's value is `$ISSUE_OVERRIDE`, the caller-supplied issue Phase 0.4 reads acceptance criteria from. If no PR number is given, review the current branch vs its configured `base_branch`.

Every later PR-mode predicate and every `gh` command reads `$PR_NUMBER` — never the raw `$ARGUMENTS` string.

## Engine ground truth (only when the injected block is present)

Load the Phase 0.0 reference (*Phase routing*) only when this prompt carries the injected `> [!IMPORTANT]` block opening with the `> **Engine ground truth for this run.` line — an unrelated callout does not qualify. Read it right after the run-start extension load and before any other command. The rules from here to *When NOT to use* apply on every run.

**Portable helper anchor (single-statement).** The bundled-helper commands in this skill spell the skill directory as `${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}`. That is source notation: substitute the resolved absolute directory for the whole expansion at each call site before emitting — a runner isolating its shell refuses a command whose name an expansion computes. Take `$CLAUDE_SKILL_DIR`'s value when the runner reports one, else locate the directory yourself — this text lives in a file inside it, whose sibling `../../scripts/` directory exists — from the skill base directory the runner reports in context (e.g. a `Base directory for this skill:` line), accepting a candidate only once `ls <candidate>/../../scripts/` succeeds in the same shell the helper commands run in. If a path form is rejected, use the form that shell reports (`pwd` shows it); a Windows-form base directory (`C:\...`) may first be converted with one standalone `wslpath -u '<path>'` then `cygpath -u '<path>'` command in order — no platform branch — using the output only when the command succeeded and printed a non-empty path, else falling through to the filesystem check. Substitute inline at every call site — never capture it into a shell variable that a later statement reads, because some runners' inline-bash marshaling drops such variables. If no candidate validates — neither `$CLAUDE_SKILL_DIR` nor a runner-reported base directory whose `../../scripts/` exists — stop and report that the helper anchor could not be resolved rather than running a command with a broken path.

In cloud the resolved anchor IS the command's leading token and must resolve to the vendored literal: the anchor variable is set on the cloud `review` runner, so each helper call written through the portable anchor (`…/../../<dir>/<helper>`) resolves under `.prflow/vendor/prflow/<dir>/<helper>`, which the read-only `review` allowlist grants. That the leading-token position is permitted here is unconfirmed, so annotate each such call to make a refusal observable.

Cloud command-shape discipline. The cloud `review` runner's harness denies whole command *shapes* even when the command *head* is granted — silently, burning budget until a run can end with no verdict. Keep every command you emit to a permitted shape from the list below.

- Permitted: only shapes with evidence on this profile: authoring a file with the Write tool under `.prflow/tmp/**`, the specific recorded `tee` forms, and the specifically recorded command-substitution forms. A granted command head does not establish that a statement containing a redirect is permitted; each complete shape needs its own evidence.
- Revision-anchored read-and-count: read a file at a revision with `git show <sha>:<path>`, the revision written as a literal, then count with the granted text tools — `grep -c -F '<symbol>'` counts the lines containing the symbol (matching lines, not occurrences; drop `-F` only for a deliberate regex match) and `grep -n -F '<symbol>'` locates them. The `git show` read piped into `grep -c` has no recorded review-tier verdict, so until one is recorded use the composed already-PERMITTED form: capture the read into `.prflow/tmp/` (the Write tool, or a recorded `tee` form), then `grep -c -F '<symbol>'` the scratch file. Confirm the `git show` read succeeded — read its error output from the invocation's own tool result — before trusting the count; a failed read pipes empty into `grep` and yields a spurious `0`, so on a read error take the INCONCLUSIVE fail direction the dispatched-agent routing contract uses, never reporting the `0`.
- **Denied — never emit:** a leading `VAR=value` assignment or env-prefix `M=x cmd …` (use the `VAR=$(cmd)` capture instead); a leading `cd`; a redirect targeting `/tmp` (`> /tmp/…`, `>> /tmp/…`) — or any other authoring there; the Write tool outside `.prflow/tmp/**`; a `cat`-headed heredoc write to ANY target; a stderr redirect that AUTHORS a file, measured refused even inside `.prflow/tmp/**` — read stderr from the invocation's own tool result instead (`2>/dev/null` discards rather than authoring, and is unmeasured); an interpreter head `python3`/`python`/`node` (ungranted); the *unexpanded* helper anchor placeholder as a leading token (emit the resolved literal path); a git -C directory form (use `git show <ref>:<path>` instead); a fused `A || B` two-path helper fallback that retries the same helper via two path spellings (`.prflow/vendor/prflow/scripts/x || scripts/x`) — emit two separate statements, the vendored literal first; a repo-relative `scripts/…` leading token — emit the `.prflow/vendor/prflow/scripts/…` vendored literal instead; a revision passed as a `$VAR`/`${VAR}` parameter expansion (write the resolved value as a literal).
- Prefer the Write tool over a stdout `>` redirect into `.prflow/tmp/**`, whose older PERMITTED rows a later cloud run did not reproduce. A phase reference still prescribing it is followed as written — the Phase 3 snapshot appends inside a read-loop the Write tool cannot source.
- Hard rule: after two permission denials of a shape, switch to a permitted alternative from this list — never iterate variants of the denied shape.

Working-directory contract. Every bundled-helper path here is a repo-relative literal that resolves against the repository root.

Consumer prompt extension (load first). The invocation ladder below is the only channel that delivers consumer policy into this skill, so run it unconditionally at the start of the run. Read its output whole — no `>/dev/null`, no `| head -<n>`, no truncation of any kind. From the repo root, run the granted vendored-literal leading token:

```bash
.prflow/vendor/prflow/scripts/load-prompt-extension.sh review
```

Tier-agnostic invocation procedure (the conditional form — do not classify your own tier). Emit the vendored literal above first. If it reports the file was not found (`command not found` / `No such file` / exit 127), fall back to the portable anchor form below:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh review
```

Every extension-state failure arm below fires unconditionally. If the invocation fails because the helper path does not exist (`No such file`, exit 127, or the platform equivalent) on every form above, that is the anchor-resolution failure above — report it in the review output; fix the anchor, don't report a missing extension. If instead the harness refuses the command outright — a permission denial rather than a missing file — the extension's state is unestablished: report that in the review output and never treat it as a clean policy pass (*unknown is not zero*). Otherwise, if the helper exits non-zero, a consumer extension exists but could not be loaded — surface its stderr message, don't silently proceed as if none existed. On exit 0 the helper prints a `PROMPT-EXTENSION-STATUS: content-present` or `PROMPT-EXTENSION-STATUS: present-empty` line on stderr; report that token verbatim in the review output as the extension's resolved status. On `content-present`, append the stdout text as instructions to the end of this skill's own prompt for this run; on `present-empty`, proceed unchanged. If no `PROMPT-EXTENSION-STATUS` line appeared at all — the command produced no output (a harness refusal) or exited non-zero (undeliverable) — the state is unestablished: report unestablished, never collapse it onto `present-empty`. A stderr breadcrumb naming the resolved extension directory is diagnostic output, never extension content.

Name those three resolved statuses **arrived** (`content-present`), **absent** (`present-empty`) and **unestablished** (no status line) — positive-signal only, so a denied helper's silence never reads as arrived. On **unestablished**, force the record to the first available durable surface in this fixed, terminating order: this run's workpad when one exists; else the pull request — its description or a PR comment — when the run has a PR but no workpad; else the review output, naming the unestablished state and reporting the record **unrecordable**. Write the first available surface — never skip an earlier one for a later one. The mechanized classifier is `.prflow/vendor/prflow/scripts/prompt-extension-arrival.py classify-ladder-output --skill review` — the granted vendored-literal leading token, invoked with the same repo-relative/anchor fallback ladder as the load above; it reads the ladder's captured output on stdin — capture the ladder's combined stdout and stderr when invoking it (the status line is on stderr, so a stdout-only pipe misclassifies every real arrival as `unestablished`) — and emits `final=arrived|absent|unestablished` plus, on unestablished, a `record=` line. Do not depend on it running: where it is not granted or not runnable it produces no output, and its silence is never a classification — the status line you already observed stays authoritative for the states above, and on unestablished the forced durable write happens regardless.

## When NOT to use

- Not for PRs you want auto-fixed — use `/prflow:review-and-fix` instead.
- Not for general code Q&A or learning the codebase — this skill is verdict-driven, not exploratory.
- Not for reviewing uncommitted local changes — commit to a branch first (Phase 0.1 will warn either way).
- Not for first-time review of a multi-PR feature branch — review the most-recent PR in isolation; the engine compares against the configured `base_branch` (or the PR base).

---

## Progress Surfaces

The engine has two progress surfaces, selected only by the internal `$PROGRESS_SURFACE` binding in Phase 0.2:

- Exact `workpad` → use the existing issue workpad identified by `$ISSUE_OVERRIDE`; do not seed or patch a `prflow:review-progress` PR comment, and tick no issue-workpad row — the fix loop records the boundary rows (its Step 1.8 evidence gate ticks the five phase rows, Loop Exit ticks `Run complete`).
- Absent, empty, or any unrecognized value → retain the PR-comment behavior below unchanged. Never treat an unknown value as `workpad`.

`$ISSUE_OVERRIDE` / `--issue`, `--push-each-iteration`, PR mode, and workpad presence do not select it. A repeated issue-workpad boundary tick the fix loop issues whose row is already ticked is an expected idempotent no-op; a missing row or failed update stays visible in the loop's helper output and is never hidden by falling back to a PR comment or by creating another progress surface.

### Live Progress Comment (PR-comment surface, PR mode)

When `$PROGRESS_SURFACE` is not exactly `workpad` and `$PR_NUMBER` is non-empty, the Phase 0.3.5 reference (*Phase routing*) carries this comment's seed, body template and update protocol. The arms below apply on every surface.

Gating & fallbacks.

**Any path that reaches no verdict — stamp a terminal `❌` as your final action.** Put that signal on the selected progress surface: the held PR progress comment, the issue workpad, or the chat narrative. The routing arms below own the exact write and must never create a different surface as fallback.

- `prflow_review.live_progress_comment_enabled` = `false` → skip the live comment entirely; behave as today (report produced once at the end). Read it via `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .prflow_review.live_progress_comment_enabled true`.
- Non-PR / current-branch mode → there is no comment surface; render the same blueprint-and-progress narrative incrementally to chat as you go, and create no comment.
- Comment create/patch is best-effort — a failure is logged and the review continues to its verdict; never abort the review on a workpad write failure.
- Termination-time re-read (PR-comment surface only). Before terminating — and before the terminal-`❌` stamp below, which stays your final action — re-read this run's own progress comment and locate the row matching the final tuple's `display_text` under its `## Blueprint` heading. If the row is ticked, terminate; if it is unticked, take the corrective attempt in the bullet below. When the re-read does not resolve — the comment cannot be fetched, or that tuple-derived row cannot be found under the heading — treat the row as unticked, take the unticked arm, and report the failed re-read alongside the corrective attempt's outcome where one was made. Where no attempt was made, report the delivery outcome and state that the row's state could not be established and could not be updated. When this run reached no verdict at all, there is nothing to deliver and no helper was invoked: leave the row unticked and state that reason rather than a helper output that does not exist. On the fix-loop PR-comment path make no corrective delivery attempt, because that path posts no verdict at all; where this bullet calls for a delivery outcome, report instead that the loop did not reach its terminal work. This reading applies to a run that has ended: on the fix-loop path the engine's aggregation phase runs once per iteration, so the window between the first iteration's terminal `Status` and Loop Exit is an in-flight state, not a delivery gap.
- Termination-time corrective attempt. Make it only on the standalone path, with the row unticked and this run's recorded Phase 4.4 reading being `FAILED no-durable-channel` — its sole trigger, so an operand you cannot establish never authorizes one. Every other reading is report-only: a `SKIP <reason>` reading names the offending argument and a no-output reading names the harness refusal. A `prflow:review-verdict` marker naming this run's reviewed head on the comment's first two lines corroborates that the delivery landed and routes to the bookkeeping arm below; one quoted deeper in the body is prose, not a producer key. When the attempt is warranted, `Read` the Phase 4.4 phase reference again first, per the engine's phase-entry contract. Re-invoke that phase's delivery helper only, running neither its fallback arm nor its stale-REJECT dismissal. Make exactly one such attempt and then stop. An attempt reaching `POSTED review <event>` or `POSTED comment <event>` ticks the row; any other reading leaves it unticked and states what the helper reported. On a reaching attempt, also note the correction — in chat, and best-effort as an appended line on the fallback comment the first pass posted — and say so when that amendment fails. When a `POSTED …` reading or a corroborating marker sits beside an unticked row, that is a bookkeeping failure and not a delivery gap: re-issue the tick and report it, and never re-post the verdict. When the tick write itself fails, report the delivery outcome and state that the row could not be updated.
- Intentional issue-workpad surface — when `$PROGRESS_SURFACE` is exact `workpad`, an unset progress-comment handle is expected and is not a disabled-comment or failed-seed fallback. Do not re-read, patch, or create a PR progress comment; the boundary tuples route to the issue workpad, ticked there by the fix loop (Step 1.8 for the five phase rows, Loop Exit for the final tuple), never by the engine. If the run ends without a verdict, report the concrete reason to the caller and best-effort append the terminal signal to the issue workpad with `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update "$ISSUE_OVERRIDE" --note "❌ review incomplete — <concrete reason>"`; surface a failed note write, but never fall back to a PR progress comment.
- No progress comment on the PR-comment surface — only when `$PROGRESS_SURFACE` is not exact `workpad` and this engine's own progress-comment handle `$WP` is unset. This covers `prflow_review.live_progress_comment_enabled` being false, a failed seed, and a non-pull-request run. With no held comment target, skip the comment-row re-read; at termination report `❌ Review incomplete — <concrete reason>` on the chat narrative channel that configuration already uses.
- No verdict on the PR-comment surface — stamp a terminal `❌` as your final action when `$WP` is set. This covers a fatal error after seeding (the diff becomes unfetchable mid-run, an agent dispatch fails irrecoverably) and equally a run that stops short of Phase 4: repeated permission denials, an unrecoverable harness refusal, or any other establishable reason you are ending without an APPROVE/REJECT. A self-assessed budget or context state is not such a reason — a run cannot establish its own remaining context on any tier. Best-effort `patch` the held comment to a clearly-failed terminal state — flip `Status` to `❌ Review failed`, replace whichever `## Verdict` section the body carries with a one-line `## Verdict` of `REVIEW INCOMPLETE — <reason>`, naming the reason concretely (e.g. `permission denials exhausted the run`), and leave the partial Blueprint ticks as-is — before surfacing the failure. When `$WP` is unset, the preceding no-progress-comment arm reports the reason to chat instead; this bullet never creates a comment.

  On the PR-comment surface with `$WP` set, treat this stamp as the no-verdict signal this engine owns; do not assume a separate workflow backstop will author it. On exact `workpad`, the caller report plus the best-effort issue-workpad note in the preceding arm are the owned signals instead.

---

## Per-Subagent Model/Effort Overrides

Operators can tune each review subagent's model and reasoning effort via the `prflow_review.agent_overrides` block in `.prflow/config.json` (see `config.schema.json`). The block maps a subagent identifier — or the special `default` key — to a `{model?, effort?, iterations?}` override; the shared engine applies it identically under `/prflow:review` and `/prflow:review-and-fix`.

Subagent dispatch is user-requested here (injection-condition clause). Invoking this review engine is the user's request for subagent dispatch at the engine's named points — Phase 1 (`prflow:checklist-generator`), Phase 1.5 (`prflow:checklist-deduper`), Phase 2 (`prflow:checklist-verifier`), Phase 3 (the specialist reviewer roster and the final-pass reviewer), and the Phase 0.3.6 blocker-recheck verifier — thereby satisfying any injected "do not call the AgentTool unless the user requested it" condition at those points and nowhere else. `/prflow:review-and-fix` inherits this through the shared engine bundle and carries no second copy (its own loop-specific dispatch points are authorized in its own SKILL.md).

effort is not a dispatch-time `Agent`/`Task` parameter, and there is no per-dispatch `--agents` injection in an already-running session — so a per-agent model override is delivered via the **Agent tool's `model` override parameter**, while a per-agent effort override is **not deliverable per-agent**: the subagent inherits the session effort as a `session-fallback` that `resolve-review-overrides.py` reports with its reason.

Resolve overrides with the bundled helper — do not hand-roll the precedence/validation in prose. Before each dispatch phase, pass the identifiers about to be dispatched to `resolve-review-overrides.py`; it reads each one's `model`/`effort` (and the `default`) via `config-get.sh` (PRFlow's single config reader), applies the rules below, and prints the override map as JSON (`{}` when nothing applies). Like every PRFlow config read, it resolves the default `.prflow/config.json` anchored to the git repository root; pass `--config <path>` to point it elsewhere:

```bash
# Pass ONLY the agents actually being dispatched this phase (e.g. omit gated-out
# type-design-analyzer / pr-test-analyzer). Empty/`{}` output → no per-agent override to apply.
# Redirect stderr to no file: the harness refuses that and returns no output at all,
# so read this resolve's stderr from its own tool result instead.
OVERRIDES=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/resolve-review-overrides.py \
    "prflow:checklist-generator")
```

The leading-token rule that governs `workpad.py` applies here too. `OVERRIDES=$(…)` is fine — the path leads *inside* the command substitution — but routing the executable through a shell variable or an env-assignment prefix is silently denied.

Resolution rules the helper enforces (so the engine just consumes its output):
- Entry-level precedence. A subagent with its own entry uses only that entry — the `default` does not backfill its missing fields; it supplies model/effort only to subagents with no entry.
- No-entry passthrough. A subagent with neither its own entry nor a `default` produces no override — dispatch it unchanged.
- Invalid effort → warn + fall back. An `effort` outside the `low/medium/high/xhigh/max` enum is dropped with a `::warning::` (the subagent falls back to the session effort); the run never aborts. A `model` outside the accepted set (`sonnet`/`opus`/`haiku`/`fable`) is dropped with a `::warning::` naming the value and that set (the subagent falls back to the top-level `claude_model`); an in-set value is forwarded; an empty/whitespace-only/non-string `model` is likewise dropped with a `::warning::`, mirroring the invalid-effort path.
- Dispatch-time `model` rejection → re-dispatch once with no override. If the Agent tool rejects the resolved `model` when it is dispatched, re-dispatch that one agent a single time with no model override — it inherits the top-level `claude_model` — and report the fallback; never retry the rejected value or abort the review.
- `iterations` (roster scoping, default-off). An entry may carry an optional `iterations` key whose only valid value is `first-only`; any other value is dropped with a `::warning::`. It is not a dispatch-time model/effort parameter — when you build a subagent's dispatch you use only its resolved `model`/`effort` and ignore `iterations`. Its sole effect is roster membership, owned by the resolver's `--plan-phase3` mode that Phase 3.1 invokes (see *Obtain the Phase-3 plan first*) and applied in no engine prose: the plan excludes an agent carrying `iterations: "first-only"` on `--entry-kind primary` at iteration ≥ 2 only — a no-op on iteration 1, in standalone `/prflow:review`, and in the Step 2.6 shadow fan-out. Entry-level precedence matches `model`/`effort` (a `default: {iterations: …}` supplies it only to no-entry agents).

For each subagent present in `$OVERRIDES`, dispatch it via the Agent tool, passing the resolved `model` as the Agent tool's `model` override parameter (its `description`/`prompt`/`tools` come from its committed definition under `agents/`, or `skills/` for the final-pass reviewer); the resolved `effort` is not applied per-agent (see above), so the subagent inherits the session effort. Dispatch any subagent absent from `$OVERRIDES` exactly as before. The helper is best-effort: surface the stderr this resolve's own tool result shows whenever it is non-empty — not only on a non-zero exit, and do so immediately after this phase's resolve, before the next dispatch phase runs. The helper deliberately exits 0 even when it drops a malformed entry (invalid effort, non-object entry, unusable model), writing those `::warning::` lines to stderr. The resolver runs once per dispatch phase (Phase 1, 1.5, 2, 3). On a non-zero exit, additionally dispatch with no overrides rather than blocking the review.

---

## The engine bundle

Resolve the Review root here. How `<skill-dir>` is resolved depends on how this engine was entered:

- Reached by a caller that already located the bundle directory (the file-read path — `/prflow:review-and-fix`'s Step 1 loop and its Step 2.6 shadow). Treat the directory it supplies as `<skill-dir>`; do not re-resolve the runner anchor here.
- Reached via the `Skill` tool (the manual `/prflow:review` comment path). Resolve `<skill-dir>` from the base directory the runner reports in context first — when the runner states a skill base directory (e.g. a `Base directory for this skill:` line), take that reported value as `<skill-dir>`, normalizing a Windows-form path to POSIX through the `wslpath -u` / `cygpath -u` ladder per the *Portable helper anchor* rule above; this path emits no shell command. <!-- prflow:skill-dir-reported-base-first --> Only when the runner reports no base directory in context, run `echo "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"` as the fallback and treat the printed path as `<skill-dir>`.

Either way, `<skill-dir>` is a textual substitution you make when emitting each command below, never a shell variable. The canonical Review root is `<skill-dir>/SKILL.md`, and every reference resolves relative to that located root, at `<skill-dir>/phases/<file>` — never relative to the working directory. The bundled-helper anchor is a separate resolution this does not move: helpers stay at `<runner-anchor>/../../scripts/…`. Fail closed — the fallback command's outcome is exactly three shapes: (1) a tool-level refusal (the runner declined it, so it never ran and produced no output) leaves the `$CLAUDE_SKILL_DIR` channel unestablished, never a clean pass, and is reported as such; (2) it ran and printed empty, or (3) it ran and printed the unsubstituted `<absolute skill base directory this runner reports in context>` placeholder — on either output shape, stop and report that the Review root did not resolve. Either way, run no phase.

### Root identity

At engine entry (Phase 0), hash the root and its references:

```bash
git hash-object <skill-dir>/SKILL.md <skill-dir>/phases/phase-0-setup.md <skill-dir>/phases/phase-0-3-6-blocker-recheck.md <skill-dir>/phases/phase-0-6-stale-prose-lint.md <skill-dir>/phases/phase-1-checklist.md <skill-dir>/phases/phase-2-verification.md <skill-dir>/phases/phase-3-agents.md <skill-dir>/phases/phase-4-verdict.md <skill-dir>/phases/phase-4-1-7-stale-adjudication.md <skill-dir>/phases/phase-4-4-github-post.md <skill-dir>/phases/phase-0-0-engine-ground-truth.md <skill-dir>/phases/phase-0-3-5-progress-comment.md <skill-dir>/phases/phase-4-5-telemetry.md
```

Fail closed: if it errors, is refused, prints empty, or prints fewer hashes than paths, report identity as underived, author no manifest, and run no phase.

Phase 0.2's setup helper writes the bundle manifest — canonical root path, root hash, and each reference's path and hash — to `.prflow/tmp/review/<slug>/<run-id>/root-identity.json`; where it never ran, Write it.

Re-deriving identity means: re-run the anchor `echo`, `Read` the manifest, and re-run `git hash-object` on the root and the reference you are about to read. Then require the same identity:

| Fires when | Stop label |
|---|---|
| no hash is available for the root or the reference about to be read — the manifest lacks its entry, or derivation errored, was refused, printed empty, or returned fewer hashes than paths | `identity: underived` |
| manifest absent, unreadable, or unparseable | `identity: state-missing` |
| re-resolved root path differs from the manifest's canonical root path | `identity: root-moved` |
| a re-derived hash differs from the manifest's hash for that path | `identity: mismatch` |

### Reference boundary contract

Each reference carries these as its literal first and last lines:

```
<!-- prflow:review-ref phase=<id> file=skills/review/phases/<name>.md start -->
<!-- prflow:review-ref phase=<id> file=skills/review/phases/<name>.md end -->
```

Paged-read recovery (before the counting below). A reader that returns the file in pages — a partial-view notice carrying an `offset`/`limit` continuation — has not damaged it: page forward until no continuation is offered or a page adds nothing new, then run the checks below over the **assembled whole document**, and report the file and page count. A read you cannot complete, a gap in the page sequence, or a reader message you cannot classify as that notice is row 1 (`denied`).

After the `Read`: quote the body's literal first and last lines, and let `S` and `E` count the lines matching the expected `start` and `end` markers — expected meaning bearing this phase's id and the reference's own bundle-relative path exactly as written in the marker — the path the run resolved and read the file from is not compared, so a marker naming a different phase or file matches nothing here and a mis-routed read fails closed. Decide rows 6 and 7 from those two quoted lines, never from an impression the markers *look* right. Test the rows in order; the first that fires is the attributed shape:

| # | Shape | Fires when | Stop label |
|---|---|---|---|
| 1 | denied | the `Read` errored or was refused — no body returned | `boundary: denied` |
| 2 | empty | body is zero-byte or whitespace-only | `boundary: empty` |
| 3 | missing | `S` = 0 **and** `E` = 0 | `boundary: missing` |
| 4 | truncated | exactly one of `S`, `E` is 0 | `boundary: truncated` |
| 5 | duplicate | `S` > 1 **or** `E` > 1 | `boundary: duplicate` |
| 6 | reversed | the `end` line precedes the `start` line | `boundary: reversed` |
| 7 | noncanonical | unique and ordered, but `start` is not the literal **first** line **or** `end` is not the literal **last** line | `boundary: noncanonical` |

On any identity or boundary row: stop that phase, report the label with the phase id and reference path, and do not act on the body, improvise the phase from its orientation text, or repair the file. A body can read as complete and correct and still fail these checks: a defective boundary or identity means what you hold is not the bundle this engine was built against.

Required copy. Rows 1–7 and the paged-read recovery above are mirrored in `skills/implement/SKILL.md`'s *Phase-reference boundary contract*; edit both in the same change. That copy adds the rows `misrouted` and `set-incomplete` this one omits.

### Phase routing

Entry-gate (mandatory, on every phase entry — and every shadow entry, as `/prflow:review-and-fix` Step 2.6 re-enters this engine; identity alone is excepted at the Phase 0.0 pre-read, which precedes the first derivation yet still clears the boundary contract, so Phase 0's entry derives identity over that reference through the *Root identity* hash). Before any action in a phase: re-invoke the run-start review prompt-extension ladder (the `load-prompt-extension.sh review` invocation defined under *Consumer prompt extension (load first)* above), re-derive root identity, `Read` its reference, and clear the boundary contract — all in that order, at this phase's own entry only and never batched ahead of it, never from an earlier read or a remembered summary — then follow the reference exactly. A refused or non-zero re-load is surfaced here, at this boundary, rather than deferred to a later phase.

| Phase | Reference under `<skill-dir>/phases/` | Loaded when | Orientation only — the reference is authoritative |
|---|---|---|---|
| 0 | `phase-0-setup.md` | always | PR/branch resolution, diff scope + cache, live-comment seed, issue discovery, five-flag classification (0.1–0.5) |
| 0.0 | `phase-0-0-engine-ground-truth.md` | only when this engine's prompt carries the injected `> [!IMPORTANT]` block opening with the `> **Engine ground truth for this run.` line | read once, after the run-start extension load and before any other command; applies for the whole run |
| 0.3.5 | `phase-0-3-5-progress-comment.md` | `$PROGRESS_SURFACE` is not exactly `workpad` **and** PR mode (`$PR_NUMBER` is non-empty) | live progress comment seed, body template and update protocol; read at 0.3.5 and again at Phase 4 entry |
| 0.3.6 | `phase-0-3-6-blocker-recheck.md` | standalone PR mode only, and only over a prior REJECT driven **solely** by carve-out blockers — never an ordinary pass | blocker re-check — evaluate right after 0.3.5 and **before** 0.4/0.5; on a hit it **replaces Phases 1–3**, ending the run with a re-verdict, so 0.4/0.5 outputs are never consumed. Absent from the default Implement and fix-loop paths |
| 0.6 | `phase-0-6-stale-prose-lint.md` | config `prflow_review.stale_prose.enabled` — defaults **true**; only an explicit `false` disables | stale-prose lint; runs immediately after 0.5 |
| 3 | `phase-3-agents.md` | always; after Phase 0/optional 0.6, before Phase 1 | prepare §3.1's snapshot, selected roster and prompts; launch with Phase 1's first generator, or alone on the checklist-skip arm; resume §3.1.5/§3.2 after Phase 2 without repeating preparation or initial dispatch |
| 1 | `phase-1-checklist.md` | always; after Phase 3.1 preparation | checklist generation and reviewer co-dispatch, then 1.5 dedup |
| 2 | `phase-2-verification.md` | always | checklist verification |
| 4 | `phase-4-verdict.md` | always | verdict, report |
| 4.1.7 | `phase-4-1-7-stale-adjudication.md` | PR mode only, and only over STALE findings from 0.6 being adjudicated false positives | stale-finding adjudication; runs after 4.1.6 and **before** 4.2 |
| 4.5 | `phase-4-5-telemetry.md` | `$PHASE_RANGE_MAX` is absent or not `4.3` | run telemetry record; runs after 4.3, before 4.4 |
| 4.4 | `phase-4-4-github-post.md` | standalone only, PR mode only (`$PR_NUMBER` is non-empty) | only `post-review-verdict.sh` posts a verdict; yours isn't one. `/prflow:review-and-fix` **skips 4.4** |

A gated phase whose condition is unmet is neither loaded nor run; evaluate each gate from the state earlier phases established, never from a guess.
