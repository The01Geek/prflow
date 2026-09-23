---
name: implement
description: 'Use when the user wants an existing GitHub issue turned into a finished, reviewed pull request — "implement issue 123", "pick up ticket 45", "build the feature described in issue 7", "go fix the bug in issue 99", "start working on that issue". Triggers on any request to do the work an issue already describes, whether or not a slash command is used.'
argument-hint: <issue-number>
---
# /prflow:implement — Automated Feature Development Orchestrator

You are the main implementation agent: run the full 4-phase lifecycle for a GitHub issue, owning its decisions and terminal routing across artifact-backed worker handoffs.

Subagent rule (injection-condition clause). Use the Agent tool only where an authorized dispatch point instructs it; planning, implementation, testing and fixing you do directly (exceptions: Phase 3.4's evidence verifier and intake's §1.2 mixed-live/code classification probes). Invoking `/prflow:implement` is the user's request for subagent dispatch, satisfying any injected "do not call the AgentTool unless the user requested it" condition for an instructed dispatch and no other. Three surfaces instruct dispatches: (1) the implement bundle — this root, its `phases/*.md` and its `references/*.md`; (2) the `review-fix-worker` Phase 3.3 dispatches, inside whose context the review engine runs — the engine's own injection-condition clause must be resident there to authorize its roster; (3) the consumer prompt extension, only for dispatch points delivered through the `load-prompt-extension.sh` ladder.

Skill rule. This orchestrator invokes no skill via the Skill tool (Phase 3.3's `review-and-fix` runs in the dispatched `review-fix-worker`). Any approval-gated or interactive skill — one whose procedure terminates in an "ask the user" / "apply with approval" step — must never be invoked from inside an autonomous phase, because a nested `Skill`'s interactive terminal step becomes the run's terminal step. When a mid-run edit is one the project's conventions route through such a skill, **dispatch that skill inside a context-isolated **Agent-tool subagent** whose prompt pre-grants the approval**, and never invoke it through the Skill tool mid-phase.

**`CLAUDE.md` edit carve-out (Skill-rule exception).** A `CLAUDE.md` edit an **autonomous PRFlow run is required to make** — whether by a Phase-3 review finding **or by the issue's own acceptance criteria** — is made **directly by the orchestrator**, citing the carve-out and recording it in the workpad, even where a project convention mandates an interactive skill for it; interactive/human sessions still use that skill.

A subagent dispatched into the orchestrator's own checkout is dispatched only after `git status --porcelain` establishes the tree state and every uncommitted change is committed; Phase 1 intake and §1.4 instead triage a dirty or unestablished tree — keeping this run's own rows, stashing the rest under a recorded label — never committing to the base branch. Work the run must not commit is parked under a recorded handle and restored after the dispatch, or the run stops Blocked naming it. Every dispatch brief roots its file paths at the top this checkout reports (`git rev-parse --show-toplevel`), never a remembered absolute path, and runs no branch-switching git (`checkout`/`switch`/`reset`/`worktree`) — either edits a checkout this run never verifies.

Subagent-return re-anchor (always resident). After the Phase 3.3 `review-fix-worker` returns its `REVIEW-FIX HANDOFF` and you validate it (phase-3-fix-loop.md §3.3), continue in that file to Phase 3.4; after the Phase 4 finalization worker returns, validate its compact result and resume publication/terminal handling in the resident Phase 4 file. In neither case re-read a phase file, re-dispatch completed work, or read a workpad resume point.

Prompt-extension re-load at re-entry. Load it in full once at run start (*Consumer prompt extension (load first)*). At each later phase entry — never merely because a subagent returned — run `.prflow/vendor/prflow/scripts/load-prompt-extension.sh implement --digest`, anchor form on not-found/rc-127, and re-load in full unless both hold: the printed digest equals the last full load's, and you can quote verbatim from resident context — not a compaction summary — the extension's first `## ` heading (or first non-blank line) and its last non-blank line; a `bytes=0` digest satisfies by match alone. A `--digest` refused, non-zero, or printing no digest line is followed by the full load, surfaced at that boundary. Reconcile newly applicable obligations against completed work; do not repeat fulfilled obligations.

Self-answer rule. A nested skill's user-facing question strands an autonomous run on both tiers. Answer it yourself from the issue description (the workpad `## Plan` and `## Acceptance Criteria` are secondary), record question and answer via `--note`, and continue. This never authorizes answering the issue's own open questions.

Expired-credential fail-fast (two strikes, never open-ended retry). A cloud writer-job run mints one GitHub App installation token at job start; past its 60-minute lifetime every `git push` and agent-side `gh` call is rejected. After two consecutive `git push` or `gh` failures carrying the bad-credential signature — HTTP `401`, `Bad credentials`, `Authentication failed`, or the `devflow-gh-fresh: … expired/bad credential` stderr line — stop retrying that operation: record a `blocked` reflection naming the expired App installation credential, set `Status: Blocked`, emit the 👎 outcome reaction, and end there.

**Terminate a process by the identifier you recorded when you started it — never by a name or command-line pattern**, which cannot tell your process from an unrelated one and can destroy another session's work. With no recorded identifier, stop rather than fall back to a pattern; clear a stale process only by its own identifier, confirmed against its start time and parent.

Input: GitHub issue number provided as `$ARGUMENTS`

Fresh context (local/interactive tier, checked once at run start). If this conversation held work before the `/prflow:implement` command (local slash-command output, such as plugin management or reloads, is not work), stop before Phase 1 and tell the user to re-run `/prflow:implement <n>` in a fresh session. A cloud run (`tier: cloud` in the prompt's run-facts or grounding block) is a fresh process and never meets this condition; re-reading this root at a later phase entry does not repeat the check.

The Phase 1 intake worker reads issue/comments; consume its actionable handoff, not the comment history. ACs come from the issue body only.

**Portable helper anchor (single-statement).** The bundled-helper commands in this skill spell the skill directory as `${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}`. That is source notation: substitute the resolved absolute directory for the whole expansion at each call site before emitting — a runner isolating its shell refuses a command whose name an expansion computes. Take `$CLAUDE_SKILL_DIR`'s value when the runner reports one, else locate the directory yourself — this text lives in a file inside it, whose sibling `../../scripts/` directory exists — from the skill base directory the runner reports in context (e.g. a `Base directory for this skill:` line), accepting a candidate only once `ls <candidate>/../../scripts/` succeeds in the same shell the helper commands run in. If a path form is rejected, use the form that shell reports (`pwd` shows it); a Windows-form base directory (`C:\...`) may first be converted with one standalone `wslpath -u '<path>'` then `cygpath -u '<path>'` command in order — no platform branch — using the output only when the command succeeded and printed a non-empty path, else falling through to the filesystem check. Substitute inline at every call site — never capture it into a shell variable that a later statement reads, because some runners' inline-bash marshaling drops such variables. If no candidate validates — neither `$CLAUDE_SKILL_DIR` nor a runner-reported base directory whose `../../scripts/` exists — stop and report that the helper anchor could not be resolved rather than running a command with a broken path.

Inline workpad notation is source shorthand, never an emitted command: expand every inline `workpad.py …` instruction in the phase references to `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py …` with the anchor resolved as above. Never emit the bare `workpad.py` token or read the inline spelling as evidence the helper is on `PATH`.

Cloud helper-invocation form (load-bearing on the cloud tier; a resumed run uses it too). The cloud allowlist grants each bundled helper **only** as the repo-relative vendored literal in the command's **leading token** — `.prflow/vendor/prflow/scripts/…` (and `.prflow/vendor/prflow/lib/…`). Never an absolute path, the repo-root `scripts/…` form, a `VAR=value` prefix, or a `bash <path>` wrapper: each stops the command *beginning with* the granted literal and is silently denied, burning budget. So on this tier the anchor resolves to the vendored literal, not to an absolute directory. The local/interactive tier has no allowlist and takes the anchor's own resolution.

Cloud command-shape discipline (implement tier). The cloud harness also denies whole command *shapes* silently — no output, budget burned — even with a granted head; the implement allowlist is distinct from the review profile's, so a shape proven on one tier is unproven on the other.

- Permitted: a single statement whose *leading token* is a granted head or a resolved vendored-literal helper path. A grant is per-head across the whole pipeline: one ungranted head anywhere in a tail refuses the statement (`paste` is granted nowhere; `tr`/`sed`/`grep` are).
- Unproven — fail closed: a `VAR=$(cmd)` capture of a non-label command (e.g. `PR_NUMBER=$(gh pr view …)`); a phase depending on one treats *no output at all* as a possible denial, never an empty value.
- Denied — never emit: the unexpanded anchor placeholder as a leading token (emit the resolved vendored literal); a `for …; do <label-helper> …; done` or piped `while read … done` loop wrapping a label helper; a `VAR="$(<label-helper> …)"` capture; a leading `cd`; a stderr redirect that authors a file — read stderr from the tool result instead (`2>/dev/null` is unmeasured). Iterate at the agent level: one single-statement `apply-labels.sh <n> …` call per issue (it creates each label and reads config itself; no separate `ensure-label.sh` call), reading its stdout token and stderr from the tool result.
- After two denials of a shape, switch to a permitted alternative from this list — iterating denied variants exhausts the budget and freezes the workpad mid-phase.
- A helper your own branch introduced or modified is unreachable this run: the vendored checkout is version-pinned and grants resolve from the default branch at trigger time, so it is absent, stale (rc-0 on old bytes), or silently denied. Recognize it from your branch delta and route the dependent step to the deferral/Blocked path up front, naming post-merge grant/vendor timing; attempt no workaround (no copy into the vendored directory, `chmod`, heredoc, interpreter re-invocation, or path-prefix variant).

Each Bash call is a fresh shell: a value that must cross a fence boundary is printed and re-substituted as a literal into the next command. Substitute values already held (`$ISSUE_NUMBER`/`$ARGUMENTS`) before emitting — replace `$ISSUE_NUMBER` with digits in the phase files' `workpad.py update $ISSUE_NUMBER …` commands.

Working-directory contract. The run begins at the repository root and the Bash working directory persists across calls; every helper path is a repo-relative literal and no fence emits a leading `cd`.

Consumer prompt extension (load first). The extension reaches you only through this ladder: run it unconditionally at run start and read its output whole — no `>/dev/null`, `| head -<n>`, or truncation — an extension you never observed governs nothing, including this rule. Pass the outcome to intake, which records the `Skill extension resolved: implement.md` row after §1.3 establishes the workpad; do not repeat its hydration or tick. From the repo root, follow the *Tier-agnostic invocation* ladder:

```bash
.prflow/vendor/prflow/scripts/load-prompt-extension.sh implement
```

On `command not found` / `No such file` / exit 127 (a checkout without `.prflow/vendor/`, such as the plugin's own tree), fall back to the anchor form:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh implement
```

Every failure arm fires unconditionally — an unrecorded failure drops consumer policy silently. Not-found on the ladder is the *Portable helper anchor* resolution failure: record it (it breaks every bundled-helper call site) and fix the anchor rather than reporting a missing extension. Refused by the matcher (never ran — distinct from running and printing nothing): the extension is **unestablished**, never a clean pass — retain the exact note `load-prompt-extension.sh was refused by the matcher; the consumer prompt extension could not be loaded` and pass it to intake for `workpad.py update $ISSUE_NUMBER --note "…"` straight after §1.3 (no workpad exists yet here); the refusal is not complete until that write lands or its failure is surfaced. Exit non-zero: a consumer extension exists but could not be loaded — surface its stderr and never proceed as if none existed. Exit 0 with text: treat it as instructions appended to this skill's prompt for the run. Exit 0 empty: proceed unchanged.

Phase reference files (resolve once, read each phase at its entry). This root holds cross-phase rules, stubs and entry gates; authoritative phase procedures live under `phases/`. Resolve `<skill-dir>` once and reuse it textually in each phase-entry `Read`, never as a shell variable; shell commands still resolve the *Portable helper anchor* inline.

**Resolve `<skill-dir>` from the base directory the runner reports in context first — this path emits no shell command.** Take a runner-reported skill base directory (e.g. a `Base directory for this skill:` line) as `<skill-dir>`, normalizing a Windows-form path through the `wslpath -u` / `cygpath -u` ladder the *Portable helper anchor* directs.

<!-- prflow:skill-dir-reported-base-first -->
Only when the runner reports no base directory, emit the fallback and treat the printed path as `<skill-dir>` — the one command that carries the expansion itself, in argument position, since it exists to discover the value:

```bash
echo "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"
```

Classify the fallback's outcome into exactly three shapes. *(1) A tool-level refusal* — never ran, no output — leaves the `$CLAUDE_SKILL_DIR` channel **unestablished**, never a clean pass: report it naming the refusal and, with no reported base directory either, stop before Phase 1 and read no phase file. *(2) Ran and printed empty*, or *(3) ran and printed the placeholder unsubstituted*: stop and report that the skill-directory anchor did not resolve, so the phase files cannot be located; run no phase from its stub alone.

Each phase routes to an ordered SET of reference files. At the start of every phase, before taking any action in it — and only at that phase's own entry, never batched with a later phase's references — `Read` the set's members under `<skill-dir>/phases/` in the order below and follow them exactly. Phases 1, 2 and 4 read their whole set at entry; Phase 3 reads its set across its sub-steps — the first member at entry, each later member when its sub-step is reached. As each Phase 3 member clears boundary rows 1–8, fold `--checkpoint phase3-part-<k> "Phase 3 reference <k> of <n> read"` (`<k>`/`<n>` from the reference's own `part=`/`of=` marker line) into the next workpad call; row 9 (set-incomplete) runs once at the Phase 3→4 transition, reading those checkpoints back and halting when one is absent — a Blocked/Failed/Cancelled stop inside Phase 3 does not run it:

| Phase | Ordered reference set |
|---|---|
| 1 | `phase-1-setup.md` |
| 2 | `phase-2-implement.md`, `phase-2-sweeps-contract.md`, `phase-2-sweeps-quality.md` |
| 3 | `phase-3-review.md` at phase entry; `phase-3-fix-loop.md` when §3.2 completes; `phase-3-ac-gate.md` when §3.3 completes (sub-step reads — see the gate above) |
| 4 | `phase-4-documentation.md` |

If `<skill-dir>` is empty or an unsubstituted placeholder, or a member's `Read` fails, halt that phase with an attributable breadcrumb. Repeat these reads on every entry, resume or re-entry; never reuse an earlier read.

Shared procedures stay outside phase sets. At named call sites, Read only the named `<skill-dir>/references/` file and require its unique `prflow:implement-shared-ref` markers as literal first/last lines in order, or stop with the matching boundary shape. Re-read after context loss; never reload Phase 1.

Phase-reference boundary contract (accept-or-reject on every phase-file read). Each `phases/phase-N-<name>.md` carries these as its literal first and last lines:

`<!-- prflow:implement-ref phase=<N> file=skills/implement/phases/<name>.md start -->`
`<!-- prflow:implement-ref phase=<N> file=skills/implement/phases/<name>.md end -->`

A member of a multi-file phase carries `<!-- prflow:implement-set phase=<N> part=<k> of=<n> -->` as its literal second line; an intact marker pair speaks only for its own file, so the `part=`/`of=` lines — not the pair — establish the phase was held whole.

Paged-read recovery (before the counting below). A reader that returns a phase file in pages — a partial-view notice carrying an `offset`/`limit` continuation — has not damaged it: page forward until no continuation is offered or a page adds nothing new, then apply the taxonomy below — `part=`/`of=` lines included — over the **assembled whole document**, and record the file and page count in a `--note` (for the Phase 1 entry read, report it in chat and write the note straight after §1.3). A read you cannot complete, a gap in the page sequence, or a reader message you cannot classify as that notice is row 1 (`denied`).

After every `Read` of a phase reference, quote the body's literal first and last lines, and let `S` and `E` count the lines matching the *expected* `start` and `end` markers — bearing the phase id and path this gate intended to read. Strip any vendored (`.prflow/vendor/prflow/`) or absolute prefix from the resolved read path before comparing, and compare the marker's self-named `file=` against the plugin-relative form (starting `skills/implement/phases/`) only — comparing against the resolved path would halt every consumer run on a correct file. Test the rows in order; the first that fires is the attributed shape:

| # | Shape | Fires when | Stop label |
|---|---|---|---|
| 1 | denied | the `Read` errored or was refused — no body returned | `boundary: denied` |
| 2 | empty | body is zero-byte or whitespace-only | `boundary: empty` |
| 3 | missing | `S` = 0 **and** `E` = 0 | `boundary: missing` |
| 4 | truncated | exactly one of `S`, `E` is 0 | `boundary: truncated` |
| 5 | duplicate | `S` > 1 **or** `E` > 1 | `boundary: duplicate` |
| 6 | reversed | the `end` line precedes the `start` line | `boundary: reversed` |
| 7 | noncanonical | unique and ordered, but `start` is not the literal **first** line **or** `end` is not the literal **last** line | `boundary: noncanonical` |
| 8 | misrouted | the marker pair is present and canonical, but its self-named phase or path is not the file this gate intended to read | `boundary: misrouted` |
| 9 | set-incomplete | every member read cleared rows 1–8, but the run does not hold the full set: for a whole-set-at-entry phase a `part=<k>` is missing or members disagree on `of=<n>`; for Phase 3's sub-step reads a `phase3-part-<k>` workpad checkpoint is absent at the Phase 3→4 transition | `boundary: set-incomplete` |

On any boundary row: stop that phase, report the stop label with the phase id and reference path, and do not act on the body, improvise the phase from its stub, or repair the file — a failing marker is repaired out of band (a human edit or another command), since a broken marker halts every `/prflow:implement` run, including one dispatched to repair it.

Rows 1–7 and the paged-read recovery are a required copy of `skills/review/SKILL.md`'s *Reference boundary contract*, edited in the same change; rows 8–9 and the `part=`/`of=` set-completeness are this engine's own.

## MANDATORY: All Four Phases Must Execute

```
Phase 1: Setup → Phase 2: Implement → Phase 3: Review → Phase 4: Documentation
```

Every phase is mandatory, even for a one-line fix. Keep the PR a *draft* until Phase 4.3, so downstream workflows see "ready" only after docs and description. Output the phase header at the start of each phase.

---

## Workpad Reference

One canonical marker-tagged issue comment — the *workpad* — is the durable progress record and the source of truth for Phase 3's acceptance-criteria gate. Phase 1.3 resolves the marker before creating anything, resumes the matching comment (possibly created by the cloud `gate` job), and fills Plan and Acceptance Criteria. Uniqueness is best-effort: keep duplicate or ambiguous marker results visible for reconciliation, never as a second canonical surface.

Status glyph. Pass `workpad.py` a bare status (`--status Setup`, `--status Complete`, `--status Blocked`); the helper prepends the canonical glyph (🚀/🎉/👎/💥/🛑): 🚀 for any in-progress phase, 🎉 `Complete`, 👎 `Blocked`. The cloud stall backstop writes workpad-only 💥 (`Failed`) on dead runs and 🛑 (`Cancelled`) on cancelled runs; neither has an outcome reaction.

Outcome reaction on the triggering comment. At every terminal `Status` transition emit the matching reaction — 🎉 at `Status: Complete` (Phase 4.3), 👎 at any `Status: Blocked` finalizer (driven by the workpad `Status`, not the job exit code). `react-to-trigger.sh --outcome` resolves the reaction and the triggering comment itself; `--outcome=complete` is `=`-joined because the worktree-isolated local session refuses bare `complete` as a builtin, and `--report-failure` records a failed reaction on the workpad without blocking the run:

```bash
# Substitute --outcome=complete at Status: Complete (Phase 4.3), --outcome=blocked at any Blocked finalizer.
.prflow/vendor/prflow/scripts/react-to-trigger.sh --outcome=complete --issue $ISSUE_NUMBER --report-failure ||
  .prflow/vendor/prflow/scripts/workpad.py update $ISSUE_NUMBER --note "Outcome reaction: react-to-trigger.sh exited non-zero (best-effort; the run continues)"
```

Tier-agnostic invocation (do not classify your own tier): once at run start, before the extension load, run `ls -d .prflow/vendor/prflow/scripts/` as its own command. If it reports the folder absent, emit every helper through the anchor form alone for the rest of the run. Otherwise — present, refused, or failing any other way — emit the vendored literal first and on a `command not found` / `No such file` / exit-127 reading fall back to the anchor form. The same ladder governs every fence.

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/react-to-trigger.sh --outcome=complete --issue $ISSUE_NUMBER --report-failure ||
  "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --note "Outcome reaction: react-to-trigger.sh exited non-zero (best-effort; the run continues)"
```

When the helper resolves no triggering comment it prints a `::notice::` and exits 0 — the workpad `Status` glyph remains the authoritative signal.

Scratch removal (same terminal transitions; best-effort, a failure never blocks the run). At 🎉 `Complete` and every 👎 `Blocked` finalizer, remove the Phase 1.1 issue-body cache with the fixed-target `remove-cache` action (the helper derives `.prflow/tmp/issue-body/issue-$ISSUE_NUMBER.md` itself; no runtime-computed `rm` target):

```bash
.prflow/vendor/prflow/scripts/preflight.py scratch-issue --issue $ISSUE_NUMBER --action remove-cache || true
```

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/preflight.py scratch-issue --issue $ISSUE_NUMBER --action remove-cache || true
```

On the `NOT_IGNORED` scratch arm only, also remove the intake-owned body with `remove-intake-body` — only when the retained `ISSUE_BODY_PATH` still resolves inside the validated `<run-scratch>` with basename exactly `intake-issue-body-$ISSUE_NUMBER.md`; the helper derives the fixed target itself. Never glob or infer another path:

```bash
.prflow/vendor/prflow/scripts/preflight.py scratch-issue --issue $ISSUE_NUMBER --action remove-intake-body || true
```

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/preflight.py scratch-issue --issue $ISSUE_NUMBER --action remove-intake-body || true
```

On 🎉 `Complete` only, remove the per-issue folder last — after the file-based reflection write, so nothing recreates it:

```bash
.prflow/vendor/prflow/scripts/preflight.py scratch-issue --issue $ISSUE_NUMBER --action remove || true
```

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/preflight.py scratch-issue --issue $ISSUE_NUMBER --action remove || true
```

GitHub autolink hygiene (every GitHub surface you write): never put a bare `#` before a number unless it is a real issue or PR reference — spell out an ordinal, count, or list position; genuine references like `#123` stay. <!-- pruned-path-ok: illustrative autolink examples, not citations -->

### Workpad sections

`scripts/workpad.py new-body` produces the skeleton — never hand-author it. `--note` entries nest under their lifecycle phase inside `## Progress`; there is no separate Decisions / Notes section. Keep `## Acceptance Criteria` outside any `<details>` — the Phase 3.4 gate reads it.

Write the workpad only through the program (the *Workpad helper CLI* ladder), never a hand-rolled `gh api` PATCH, which validates nothing: a dropped marker line makes every later `workpad.py id` miss (exit 2), which the create paths read as "not yet seeded" and answer by opening a second workpad. `workpad.py patch COMMENT_ID BODY_FILE` re-inserts the leading marker a composed body omits (refusing the PATCH, exit 1, when it cannot read the live body and the composed body carries none) and preserves every section and header line the failure-isolation contract lists as a structural abort.

The `## Progress` row inventory is the set of rows the rendered workpad body carries — `workpad.py new-body`'s output, or the live comment. A `--tick-progress` operand matches like `--tick-plan`/`--tick-ac` below: a unique already-ticked match is satisfied, not a miss. Every note and reflection you compose opens with a capital letter, unless its first token is a literal a reader matches (`/prflow:implement`, `classification:`).

- `**Setup**`
  - `— /prflow:implement run started` (the run-started note)
  - `Skill extension resolved: implement.md`
- `**Implement**`
  - `Reproduction captured (bug issues only)`
  - `Code + sweeps`
- `**Review**`
  - the six `_REVIEW_PROGRESS_ROWS` tuples, in constant order
  - `Review-and-fix loop`
  - `Skill extension resolved: review.md`
  - `Skill extension resolved: review-and-fix.md`
  - `Skill extension resolved: fix.md`
  - `Acceptance-criteria gate`
- `**Documentation**`
- `**PR marked ready**`

The bug-only row is rendered by `new-body` unless `--no-reproduction` is passed — the local fresh-issue path passes it only when the §1.1 classification is non-bug; the cloud `gate` job decides from the `bug` label and renders the row when that lookup fails. Phase 1.3's `--reconcile-reproduction`, keyed on the recorded classification, is the authoritative correction.

### Workpad helper CLI

Every workpad operation goes through `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py`. It is stateless — each subcommand re-derives `REPO_FULL` and the marker — so nothing needs to survive between Bash calls.

Workpad-invocation ladder. `workpad.py` starts no shell and runs no `.sh` file (host needs: Python 3.11 or newer, an authenticated `gh`, and `scripts/section_parse.py` beside it). Rungs, advanced only when a rung fails: (1) the vendored path directly (`.prflow/vendor/prflow/scripts/workpad.py …`); (2) the file directly through the portable anchor form; (3) local/interactive tier only — `python3` against the vendored path, then the anchor-resolved path; the cloud matcher refuses any interpreter-leading command. A rung has failed only when the run observed no invocation at all; a writing subcommand changes the comment before it returns, so before advancing a rung on a write, re-read the workpad and skip the retry when the write already landed — a second completion-evidence marker makes the finishing gate refuse the run. A run that exhausts its tier's rungs stops at Blocked without hand-writing a status (itself a workpad write through the program it failed to reach) — except the *Terminal-status self-check*'s own status read, which records the status unestablished and continues — recording the skip, the program and each rung tried on the workpad when reachable, else in the PR description, else reported unrecordable.

For the helper's full subcommand and flag surface, emit `.prflow/vendor/prflow/scripts/workpad.py --help` and `.prflow/vendor/prflow/scripts/workpad.py update --help` (vendored literal first; an unexpanded anchor as a leading token is denied with no output). On a not-found reading, re-invoke both through the portable anchor form. If neither prints help, do not improvise flags: use only the complete invocations the phase files carry, and record the unresolved reference with a `--note`.

The marker-locating subcommands (`id`, `new-body`, `update`) accept `--marker M` (precedence: `--marker` > `DEVFLOW_WORKPAD_MARKER` env > `.prflow/config.json` > the built-in default `<!-- prflow:workpad -->`); `/implement` never passes it.

Reflection style contract (every `--reflection` / `--reflection-file` bullet). A non-empty `reflections[]` trips the weekly retrospective's cheap gate and forces an LLM analysis, so every bullet must earn its place. Prose rules live in the shared writing standard, read at the reflection compose points in the phase files (`"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/writing-standard.md`); a failed load emits a breadcrumb naming the file and failure kind, and the reflection is composed without it. Kind routing: friction/deviation you worked around → `note`; an engine/process-improvement proposal → `improvement`; the driving issue's claims were wrong or underspecified → `issue-accuracy`; a hard stop → `blocked`; punted work already tracked by a scope-decision-deferred record → `deferred`; untracked punted work, and failed-and-continued → `dropped-failed`. A **clean confirmation** — an assumption that held with no friction — is **not** a reflection: record it as a `## Progress` `--note`, which does not trip the cheap gate.

Interpolation-safe reflection text (file-based recipe, every tier). `--reflection TEXT` traverses bash quoting, so text with backticks, `$`, or double quotes is mangled before the helper sees it. For such text, author the payload to a `.prflow/tmp/` file with the **Write tool**, pass it as `workpad.py update $ISSUE_NUMBER --reflection-kind improvement --reflection-file <run-scratch>/refl-$ISSUE_NUMBER.md` (`<run-scratch>` is §1.1's per-arm scratch home, flat on the not-ignored arm), and delete the payload file after the helper call succeeds (`rm <run-scratch>/refl-$ISSUE_NUMBER.md`) — an adopter with no ignore rule for `.prflow/tmp/` would otherwise trip Phase 4.3's clean-tree backstop. A terminal-status call never carries `--reflection-file`: on a stop path the `--status Blocked` flip is its own `update` call, recorded first, and the file-based reflection follows separately — falling back to an inline `--reflection` on a structural error — so a bad payload can never cost the run its terminal status. Not a heredoc or `>`-redirect: the cloud matcher denies those shapes even with a granted head.

Failure-isolation contract (volatile vs. structural). Structural failures abort the whole call with no PATCH (exit 1, clear stderr): `gh` can't resolve the repo, the API call fails, a target section (`## Progress`/`## Plan`/`## Acceptance Criteria`) or the `Last updated` line is absent (or the `Status` line, for a `--status` mutation), a `--rewrite-ac` substring matches zero or multiple rows, a `--rewrite-ac` pair appends the `(post-merge)` tag (NEW ends with it; neither OLD nor the row it targets already does) without a non-empty `--note` rationale, a `--replace-*-file`/`--set-reproduction-file` is unreadable, or a `--reflection-file` payload is unreadable, non-UTF-8, or empty. A tick whose target row is already ticked is satisfied, whichever call ticked it. Volatile per-row tick misses are isolated, not aborted: a `--tick-*`/`--tick-*-n` flag that resolves to no row or ambiguously inside a present section (no match, several unticked matches, several ticked and no unticked matches, or an out-of-range index) does not discard the call — every other mutation is applied and PATCHed, and the call then exits non-zero naming each tick that did not land. The replay carve-out: a call whose only mutations are satisfied ticks returns `outcome=replay remedy=none` and makes no PATCH; a tick that lands now, an unresolved row, or any other mutation alongside stays on the ordinary path.

One moment, one call. Issue every workpad mutation belonging to one moment as a single `update` — repeatable flags repeated, independent flags combined, one PATCH — never one call per sub-step; each extra call spends a round-trip of resident context. Reconcile-row repairs apply before ticks, so a combined call is order-correct. Never dispatch these calls concurrently: an `update` fetches, mutates in memory and PATCHes the whole body back, and the `--expect-*` preconditions are checked against the fetched body, not at PATCH time, so concurrent calls lose writes. Four limits:

- A structural-abort flag carries only passengers one re-send restores. The `--expect-*` guards, `--replace-acs-file`, `--rewrite-ac`'s zero/multiple-match refusal, every `--record-*`/`--checkpoint` operand-arity check, and an absent `Last updated` line or `## Progress` section abort before any PATCH (the `--tick-*` family's row misses ride the PATCH through instead); `outcome=not-persisted remedy=reissue-call` re-sends the whole call, so what was folded in comes back. Three cases take no passengers: `--expect-comment-id`/`--expect-status`, whose `remedy=re-resolve-state` forbids a re-send (so the Phase 1.3 hydration call — `--replace-acs-file` plus its `--expect-*` guards — stays apart from progress writes); an abort whose cause must be repaired first, such as an unreadable or empty `--reflection-file` payload (Phase 3's soft-proceed splits its call for this); and any `landed-*` outcome, whose follow-up call carries only the corrective mutation.
- A second `--reflection-kind` — one kind per call, so two kinds need two calls.
- Anything across a `phase2-durability-checkpoint.sh` boundary — merging past one widens the work-loss window; for Phase 2's accruable population the boundary is itself the delivering moment (phase-2-implement.md §2.0.5).
- A staged decision point, where the next call's content depends on the previous call's outcome — two moments, not one.

Read the outcome line — it is the single signal. An `update` that reaches its exit path closes with the stderr line `workpad.py update: outcome=<token> remedy=<token>`; a crash bypasses it and emits none. Act on the named remedy; never infer the outcome from the prose lines above it.

| `outcome=` | Meaning | `remedy=` | Do this |
|---|---|---|---|
| `landed` | PATCH applied; every requested mutation landed | `none` | advance |
| `replay` | supported pure no-op, no PATCH: a keyed checkpoint replay, or a call whose only mutations are ticks whose rows are already ticked | `none` | advance |
| `landed-partial-ticks` | PATCH applied; one or more tick rows unresolved | `retick-named-rows` | re-issue only the named `--tick-*-n` |
| `landed-status-unverified` | PATCH applied; the `--status` read-back was empty, carried no Status line, or disagreed | `reset-status` | follow-up call carrying only `--status` |
| `landed-partial-ticks-status-unverified` | PATCH applied; tick rows unresolved **and** the `--status` read-back unreadable | `retick-and-reset-status` | follow-up call carrying only the missed ticks and `--status` |
| `not-persisted` | no PATCH was made, or the PATCH itself failed | `reissue-call` | fix the cause, then re-send the whole call |
| `precondition-mismatch` | an `--expect-comment-id`/`--expect-status` guard refused before any mutation | `re-resolve-state` | re-read the live workpad and re-decide against the current state |

No remedy re-sends a call whose PATCH landed — `reissue-call` pairs only with `not-persisted`; the corrective remedies each direct a *follow-up* call carrying only the corrective mutation, because re-sending a landed call double-writes the append-only notes. On `re-resolve-state` never re-send: live state changed, and a blind retry overwrites it.

An absent outcome line means the write did NOT land: a harness refusal or a crash emits nothing, so treat a missing line as unverified — never as landed — and re-resolve the live workpad before advancing.

Callers MUST read that line on any tick call — never advance on the stdout body alone, because a volatile miss PATCHes the body without landing its target tick; the echoed body is the row inventory to re-resolve a shifted index against. On `retick-named-rows` or `retick-and-reset-status`, re-resolve each named target (checkbox positions shift after a Phase 2.2.5 `--replace-acs-file`) and re-tick the named rows — do not blindly re-send the whole call, whose notes already landed — or, if a target cannot be resolved, route to the relevant Blocked path (the Phase 3.4 gate's step 4, or Phase 4.3's clean-tree/publish handling). The gate's pass condition is evidence-based: the targeted row is `- [x]` and the call reported `remedy=none` or `remedy=reset-status` (Status and ticks are independent); a satisfied tick's `outcome=replay remedy=none` is successful evidence too. This binds the Phase 3.4 AC gate, the Phase 4.3 `--tick-progress "PR marked ready"` finalize, and ordinary per-phase ticks.

`--tick-plan`/`--tick-ac` substring matching prefers a unique unticked (`[ ]`) row and accepts a unique already-ticked one as satisfied, so a duplicate tick is a no-op; `--tick-plan-n`/`--tick-ac-n` address by 1-based position within their own section, counting every `[ ]` and `[x]` row in `## Plan` or `## Acceptance Criteria` respectively — a whole-document count ticks the wrong row silently.

Resume the canonical workpad; never intentionally create another. Phase 1.3 performs the marker lookup before create; subsequent mutations go through `update`. Recover a lost `$ISSUE_NUMBER` mid-run per *Context recovery* below. On a re-run, intake reconciles the workpad's Progress/Reflections against corrective evidence, treating no review as complete, and hands off sourced decisions, corrections and blockers; outside intake, recover durable state directly. A prior `Blocked` status is a finished earlier run's history: intake records its cause, classifies the run `terminal-re-trigger`, and proceeds past Phase 1, re-raising Blocked only if the owning step still finds the cause live.

Always verify a Status PATCH actually landed. `gh api -X PATCH` can return success with the body unchanged, so an exit code cannot discharge this — the outcome line is the verification (the helper reads the Status back). Before advancing to the next phase, confirm `outcome=landed` or `outcome=replay` (`remedy=none`); any other token names its remedy above, and an absent line is unverified. Plan/Notes-only updates need no check.

---

## Phase 1: Setup

Orientation only (the phase file is authoritative): run intake, branch setup and issue-claim audit serially in the shared checkout; each worker loads its own procedure and returns an artifact-backed handoff. Keep worker procedures and transcripts out of this context; retain terminal decisions and exact requirement artifacts.

## Phase 2: Discover, Plan & Implement

Orientation only: explore the codebase; reproduce first when the recorded classification is bug-report; assess complexity and write the plan (the architect for complex work); implement against the plan under the mandatory code sweeps; test; commit.

## Phase 3: Review & Fix

Orientation only: open the draft PR; run the self-review and the review-and-fix loop; enforce the acceptance-criteria gate before advancing.

## Phase 4: Documentation

Orientation only: dispatch the finalization worker for follow-ups, documentation, PR description and final-tree gates; validate its compact evidence-backed result, then publish or leave a draft per config and finalize the workpad.

---

## Completion Checklist

Before reporting completion, verify ALL phases executed:

- Phase 1: issue fetched; workpad created before the branch with run link, `## Progress` checklist and mirrored Acceptance Criteria; branch exists and the workpad `Branch` line filled; Setup ticked
- Phase 2: reproduction signal recorded when the recorded classification is bug-report (Phase 1.3's `classification: ` note, not the `bug` label); for a multi-PR issue the 2.2.5 scope-adjustment applied and `## Acceptance Criteria` holds only in-scope items; the 2.3.0 changed-contract, 2.3.4 boundary-assumption, 2.3.4a self-authored-claim and 2.3.4b coverage-claim sweeps all ran over the §2.3 branch-delta operand (merge base → working tree, not just the uncommitted diff); code committed and pushed
- Phase 3: draft PR created; the code-reviewer cleanup pass ran; `/prflow:review-and-fix` ran; acceptance-criteria gate passed (PR still draft)
- Phase 4: follow-up issue(s) filed in 4.0 for 2.2.5-deferred criteria and in 4.0.5 (manifest hydrated) for a review-and-fix deferrals manifest; docs updated and the `Documented` label applied; PR description generated via `/pr-description`; working tree asserted clean (4.3 backstop, publish and draft cases alike) and any remainder committed; PR published via `gh pr ready` unless `prflow_implement.implement_pr_state` is `draft` (then left as the Phase 3.1 draft, no extra PR-thread comment); every applicable `## Progress` item ticked; workpad finalized with `Status: Complete` (🎉, draft-aware `--note` wording) and the 🎉 outcome reaction emitted

If a phase was skipped or a `Status` PATCH didn't land, go back and complete it now. Do not stop after the PR is created or review approves — the PR stays a draft until Phase 4.3 publishes it (or deliberately leaves it a draft after finalizing workpad and reaction). Do not stop because acceptance criteria are unchecked on a multi-PR issue — apply the 2.2.5 scope-adjustment, then re-run the gate; Phase 3.4's Blocked stop is only for genuinely-failing in-scope criteria.

### Terminal-status self-check (every turn boundary)

Once the workpad exists, read its live `Status` line — from the live comment, never from memory — before you end any turn; skip it and the run parks at an in-progress `Status` with nothing to restart it. Before §1.3 creates the workpad the grounds below alone govern. After §1.3, exit 2 (no workpad comment) means the workpad or its marker is gone: take §1.3's disappeared-workpad arm — stop with a diagnostic naming the failed `status` read and create no second workpad. Exit 1 (Status line missing or unrecognized) and exit 3 (gh transport or auth failure) are neither terminal nor a ground to end the turn: record the status unestablished and continue, as for a refused read.

Where the injected engine-ground-truth block is present, ending a turn ends the process, so no non-final ground below is usable there; the grounds govern the local/interactive tier only. The status read binds on every tier.

A turn may end only on:

- a harness refusal you cannot proceed past;
- a workpad `Status` that `scripts/workpad.py status` classes terminal — `complete` (🎉), `blocked` (👎), `failed` (💥) or `cancelled` (🛑) — though one read at the start of a resuming run is a finished earlier run's status and a resume trigger, not a ground, on either tier;
- the work driven to completion, the live `Status` terminal, and this turn carrying the run's final message.

Ending a turn on anything else — to report progress, request an uncalled-for confirmation, hand off, or at a "natural break" — is forbidden. An in-progress `Status` (🚀) means the run is unfinished: return to the phase that owns the remaining work and drive `Status` terminal. The commonest trip is stopping at "documentation done" when Phase 4.2 (`/pr-description`) and Phase 4.3 (finalize → `Status: Complete` 🎉 + outcome reaction) remain.

A refused status read is retried through the *Workpad-invocation ladder*; on a second refusal record the status unestablished and continue — a refused read is never a ground to end the turn. Only when the ladder is exhausted for writes too (no terminal `Status` reachable), or the status stays unestablished after it is exhausted for reads, end the turn on the harness-refusal ground, naming the refusal and each rung attempted, and report `Blocked` to your caller.

The check keys on the workpad `Status`, not PR draft state — a run finishing with a draft PR (`implement_pr_state=draft`) still reaches `Status: Complete`. On the cloud tier the `devflow-implement.yml` Stall backstop detects an interim `Status` post-run and re-dispatches (bounded auto-resume, honest-red on cap exhaustion) or, on a fail-loud exit, flips the workpad to `Failed` (💥) — it never drives a run to `Complete`; the local tier has no backstop.

---

## Error Handling

- Empty steps: a phase producing no file changes skips the commit and continues — no empty commit.
- Git conflicts: on a push rejected for conflicts, run `git pull --rebase origin {branch}` and retry once; a second failure stops and reports. After any successful rebase, re-run the Phase 2.3.0 changed-contract sweep against the newly-arrived sites — a clean textual rebase can still surface a base-branch fixture, call site, or assertion the change's contract now rejects.
- Subagent failures: a subagent that fails or returns nothing useful is recorded via `--reflection-kind dropped-failed --reflection "…"` and the run continues; never retry the same subagent more than once.
- Permission denials: a denial refuses the *form*, not the work — re-form per phase-3-fix-loop.md's ladder, never the denied *effect* via a tool, interpreter, checkout, or self-attested check. Ladder spent: `dropped-failed` reflection naming helper, tier, remedy (local `~/.claude/settings.json`; cloud `install.sh --apply`/`allowed_tools` token) and the absent artifact; `workpad.py` refused: PR body; no workpad/PR: name the terminal, unrecordable. A phase's own refusal arm stands. A denied verification is unestablished, not passed; never skip a phase over one.
- Commit prefixes: follow the project's declared commit-message convention; absent one, `docs:` for documentation, `feat:` for implementation, `fix:` for review and test fixes.
- Context recovery: recover the issue from `$ARGUMENTS`, branch/PR with `git`/`gh`, lifecycle with `workpad.py status`, and setup only from validated compact handoffs (`phase2_resume`, AC/audit paths, branch-setup record). Missing, stale, unreadable or evicted state: rerun the worker that owns it. Never read the full workpad, transcript, or setup procedure, or inline setup; later phases reread only their set and named shared refs.
- Surfacing failures: everything you "note and continue" on above goes to `PRFlow Reflections` via `--reflection`/`--reflection-file`, kind chosen by the *Reflection style contract*; no separate end-of-run comment is needed.
