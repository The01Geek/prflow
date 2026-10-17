---
name: review
description: 'Use when the user wants code assessed rather than changed — "review PR 88", "is this branch ready to merge?", "look over my changes", "any problems with this diff?", "give me a code review", "what do you think of this PR?", "sanity-check this branch", "ship it?". Applies to a pull request or the current branch when findings, a verdict, or a merge-readiness opinion is wanted. This is the default for an unqualified review request; use prflow:review-and-fix only when the user explicitly asks for the problems to be corrected.'
argument-hint: "[pr-number] [--issue N]"
---

# /prflow:review — Comprehensive PR Review

You are the review engine orchestrator. Run a four-phase review and present an APPROVE/REJECT verdict.

Input: `$ARGUMENTS` may hold a PR number and/or `--issue N`. Only a bare numeric token or Phase 0.2's `pr` binds `$PR_NUMBER`; the flag's value binds `$ISSUE_OVERRIDE`, the issue Phase 0.4 reads acceptance criteria from. With no PR number, review the current branch against its configured `base_branch`. Every later PR-mode predicate and `gh` command reads `$PR_NUMBER`, never the raw `$ARGUMENTS`.

**Portable helper anchor (single-statement).** The bundled-helper commands in this skill spell the skill directory as `${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}`. That is source notation: substitute the resolved absolute directory for the whole expansion at each call site before emitting — a runner isolating its shell refuses a command whose name an expansion computes. Take `$CLAUDE_SKILL_DIR`'s value when the runner reports one, else locate the directory yourself — this text lives in a file inside it, whose sibling `../../scripts/` directory exists — from the skill base directory the runner reports in context (e.g. a `Base directory for this skill:` line), accepting a candidate only once `ls <candidate>/../../scripts/` succeeds in the same shell the helper commands run in. If a path form is rejected, use the form that shell reports (`pwd` shows it); a Windows-form base directory (`C:\...`) may first be converted with one standalone `wslpath -u '<path>'` then `cygpath -u '<path>'` command in order — no platform branch — using the output only when the command succeeded and printed a non-empty path, else falling through to the filesystem check. Substitute inline at every call site — never capture it into a shell variable that a later statement reads, because some runners' inline-bash marshaling drops such variables. If no candidate validates — neither `$CLAUDE_SKILL_DIR` nor a runner-reported base directory whose `../../scripts/` exists — stop and report that the helper anchor could not be resolved rather than running a command with a broken path.

Helper calls. A fence that leads with the vendored literal `.prflow/vendor/prflow/scripts/<helper>` runs from the repository root, never after a `cd`. When that helper is not found (`command not found`, `No such file` or exit 127 — read the output too, since a trailing `echo` masks the exit code) or exits 2 with a usage message, re-run the same arguments once through the anchor form `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/<helper>`, unless a command-shape table you hold does not permit that form. When neither prints what the call site routes on, take that call site's stop path.

Cloud command-shape discipline. A command-shape table reaches you in an injected engine-ground-truth block or in `.prflow/tmp/command-shapes.md`. Holding one, emit only the shapes it permits, author files with the Write tool rather than a `>` redirect or a `cat`-headed heredoc, and after two denials of a shape switch to a permitted one rather than retrying a variant.

Test evidence: the injected block's CI results when it lists them; otherwise an in-environment suite result for this HEAD you already hold (your own, or one the caller handed you), else report it missing — never assume CI passed.

Consumer prompt extension (load first). This ladder is the only channel that delivers consumer policy into this skill, so run it at the start of the run and read its output whole — no redirect, `head` or truncation:

```bash
.prflow/vendor/prflow/scripts/load-prompt-extension.sh review
```

On `command not found` / `No such file` / exit 127, fall back to the anchor form:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh review
```

Report the stderr `PROMPT-EXTENSION-STATUS:` token verbatim in the review output. `content-present`: append the stdout text to this prompt as instructions for the run; `present-empty`: proceed unchanged. A non-zero exit means a consumer extension exists but could not be loaded: surface its stderr. No status line — that, a refusal, or the helper missing on both forms (the anchor did not resolve) — is `unestablished`: report it so, never as `present-empty`.

Prompt-extension re-load at re-entry. Load it in full once at run start (*Consumer prompt extension (load first)*). At each later phase entry — never merely because a subagent returned — run `.prflow/vendor/prflow/scripts/load-prompt-extension.sh review --digest`, anchor form on not-found/rc-127, and re-load in full unless both hold: the printed digest equals the last full load's, and you can quote verbatim from resident context the extension's first `## ` heading (or first non-blank line) and its last non-blank line; a `bytes=0` digest satisfies by match alone. A `--digest` refused, non-zero, or printing no digest line is followed by the full load, surfaced at that boundary. Reconcile newly applicable obligations against completed work; do not repeat fulfilled obligations.

## Progress surfaces

Phase 0.2 binds `$PROGRESS_SURFACE` from the caller's `progress_surface`:

- Exact `workpad` → the caller's issue workpad. Seed or patch no PR progress comment and tick no workpad row: the fix loop records the boundary rows.
- Anything else → in PR mode, unless `prflow_review.live_progress_comment_enabled` reads `false`, the PR progress comment (Phase 0.3.5); otherwise narrate progress in chat.

**Any path that reaches no verdict — stamp a terminal `❌` as your final action.** Put it on the selected surface, naming the concrete reason (e.g. `permission denials exhausted the run`): the PR comment per Phase 0.3.5; on `workpad`, report the reason to the caller and best-effort run `.prflow/vendor/prflow/scripts/workpad.py update <issue> --note "❌ review incomplete — <reason>"` (`<issue>` is `$ISSUE_OVERRIDE`); otherwise chat. Never create another surface as a fallback. A self-assessed budget or context state is not a reason.

Delivery retry (standalone only). When this run's Phase 4.4 reading was `FAILED no-durable-channel`, before terminating, with `$WP` set patch `Status` back to the line Phase 4 wrote, then run Phase 4.4's helper call once more and route on its first line as that phase does, reporting a `POSTED` reading as a correction in chat. No other reading triggers this retry.

## Subagent dispatch and model overrides

Invoking this engine is the user's request for subagent dispatch at its named points — Phase 1 (`prflow:checklist-generator`), Phase 2 (`prflow:checklist-verifier`) and Phase 3 (the reviewer roster and the final-pass reviewer) — satisfying any injected "do not call the AgentTool unless the user requested it" condition at those points and nowhere else.

`prflow_review.agent_overrides` sets a per-subagent `model`. Before each dispatch phase, resolve the identifiers about to be dispatched (Phase 3 uses §3.1's `--plan-phase3` call instead):

```bash
.prflow/vendor/prflow/scripts/resolve-review-overrides.py "prflow:checklist-generator"
```

It prints one JSON object keyed by agent (`{}` when none applies) and exits 0 even on a malformed entry; surface any `::warning::` lines it writes to stderr before the dispatch. Pass an agent's `model` value as the Agent tool's `model` parameter (an `iterations` value is not a dispatch parameter); dispatch any other agent unchanged; on a non-zero exit or no JSON, report it and dispatch with no overrides. If the Agent tool rejects a resolved model, re-dispatch that agent once without it and report the fallback.

## The engine bundle

`<skill-dir>` is the directory holding this `SKILL.md`; every phase reference resolves to `<skill-dir>/phases/<file>`, never the working directory. A caller that already located the bundle (the fix loop's engine entries) supplies it. Through the `Skill` tool, take the base directory the runner reports in context (e.g. a `Base directory for this skill:` line), normalizing a Windows-form path per the *Portable helper anchor* rule; this emits no command. <!-- prflow:skill-dir-reported-base-first --> Only when the runner reports none, run `echo "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"` and take the printed path. A refused call, an empty output or the unsubstituted placeholder means the bundle did not resolve: report it and run no phase. `<skill-dir>` is a textual substitution, never a shell variable.

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

On any boundary row: stop that phase, report the label with the phase id and reference path, and do not act on the body, improvise the phase from its orientation text, or repair the file.

### Phase routing

Entry gate. Once any re-load above is done, every phase, on a shadow entry too, begins with the `Read` of its reference whole, at that phase's own entry and never ahead of it, then the boundary check; no step of the phase runs before both. A gated phase whose condition is unmet is neither loaded nor run; evaluate each gate from state earlier phases established, never from a guess.

| Phase | Reference under `<skill-dir>/phases/` | Loaded when | Orientation only — the reference is authoritative |
|---|---|---|---|
| 0 | `phase-0-setup.md` | always | setup helper, progress surface, issue and criteria, review brief, diff profile (0.1–0.5) |
| 0.3.5 | `phase-0-3-5-progress-comment.md` | `$PROGRESS_SURFACE` is not exactly `workpad` **and** PR mode (`$PR_NUMBER` is non-empty) **and** `prflow_review.live_progress_comment_enabled` does not read `false` | live progress comment seed, body template and update protocol |
| 3 | `phase-3-agents.md` | always; after Phase 0, before Phase 1 | prepare §3.1's roster and prompts; launch with Phase 1's first generator, or alone on the checklist-skip arm; resume §3.1.5/§3.2 after Phase 2 without repeating preparation or initial dispatch |
| 1 | `phase-1-checklist.md` | always; after Phase 3.1 preparation | checklist generation and reviewer co-dispatch |
| 2 | `phase-2-verification.md` | always | checklist verification |
| 4 | `phase-4-verdict.md` | always | verdict, report |
| 4.5 | `phase-4-5-telemetry.md` | `$PHASE_RANGE_MAX` is absent or not `4.3` | run telemetry record; runs after 4.3, before 4.4 |
| 4.4 | `phase-4-4-github-post.md` | standalone only, PR mode only (`$PR_NUMBER` is non-empty) | only `post-review-verdict.sh` posts a verdict; yours isn't one. `/prflow:review-and-fix` **skips 4.4** |
