<!-- prflow:implement-ref phase=4 file=skills/implement/phases/phase-4-documentation.md start -->
## Phase 4: Documentation

Output: `Phase 4/4: Documentation — updating docs and finalizing PR...`

Writing standard. Before composing this phase's first `--reflection` bullet, read the shared writing standard and follow it.

`workpad.py update $ISSUE_NUMBER --status Documenting`.

### 4.0 File Follow-Up Issues for Deferred Work

Phase 4.0's follow-up-issue composition lives in the `deferral-drafter` subagent (`agents/deferral-drafter.md`) and its GitHub writes in the gated reference `<skill-dir>/references/deferred-ac-followups.md`, reached only when a durable predicate says work is outstanding. Ask the predicate first, substituting the PR number as a decimal literal — a `$PR_NUMBER` variable arrives empty on the cloud tier, and the helper's integer-typed PR argument turns that into a usage error that loads it every run with nothing red (`$ISSUE_NUMBER` per your standing substitution rule):

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py deferred-presence $ISSUE_NUMBER <this-run's-PR-number>
```

Read the exit code and printed count line from the tool result, never a captured shell variable or the workpad body. Route on the exit code:

- exit 1 — `not-outstanding: <n>`. Do not read the reference; continue to §4.0.5.
- exit 0 — `outstanding: <n>`, followed by one `criterion:` line each. `Read` `<skill-dir>/references/deferred-ac-followups.md` — via this file's entry-gate anchor — and follow it for exactly the projected criteria: it dispatches the drafter, then performs every GitHub write from the returned plan.
- exit 2 — `unestablished: reason=<token> unbound=<u> corrupted=<c>`, or no count line at all. Read the reference anyway (it handles any `filed:` lines the count line carries), and record `workpad.py update $ISSUE_NUMBER --reflection-kind note --reflection "…"` naming which operand could not be established, quoting the reason token and both counts. An unavailable operand is never read as "nothing was deferred": that reading silently strands deferred work.

Marker contract. Accept the load only when the file's first line is its `start` boundary marker and its last line the matching `end` marker, each naming that file's own path. A reference the reader returns only in pages — a partial-view notice with an `offset`/`limit` continuation — is not a mismatched marker: page it forward until a page adds no new content or no continuation is offered and apply this rule to the assembled whole document, recording the paged recovery in a `--note`; only a read the reader cannot complete, or a message you cannot classify as that notice, is the degraded arm below.

Degraded arm — degrade, never halt. When the predicate holds and the reference read fails — absent, empty, harness-refused, or mismatched boundary markers — record `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "…"` naming the reference path `skills/implement/references/deferred-ac-followups.md`, stating the deferred criteria were not filed, then continue to §4.0.5 without halting Phase 4 (`dropped-failed` is this arm; the unestablished arm above uses `note`).

### 4.0.5 File Follow-Up Issues for Deferred Review Findings

The Phase 4.0.5 procedure lives in `<skill-dir>/references/deferred-review-findings.md` and is read only when a durable predicate says a deferred review finding is present. Ask it first, as a single statement whose leading token is the granted vendored literal, substituting this run's PR number as a decimal literal (as §4.0 does, and for the same reason):

```bash
.prflow/vendor/prflow/scripts/discover-deferral-manifests.py --presence-for-pr <this-run's-PR-number>
```

On any reading that says the vendored path did not *run* — `command not found`, `No such file`, `Permission denied`, rc 126 or rc 127 — re-invoke the same helper through the portable anchor:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/discover-deferral-manifests.py --presence-for-pr <this-run's-PR-number>
```

Read the exit code and printed state line from the tool result, never a captured shell variable. Route on the exit code:

- exit 0 — `present: <n>`. `Read` `<skill-dir>/references/deferred-review-findings.md` — via the same `<skill-dir>` anchor this file's entry-gate uses — and follow it.
- **exit 1 *and* the printed line is exactly `absent: 0`.** Do not read the reference; continue to §4.1. Both conditions are required: 1 is also the status a crashing interpreter returns, so an exit 1 carrying no `absent: 0` line is the arm below, not this one.
- Every other outcome — exit 2 with `unestablished: reason=<token>` (optionally a `root:` line), exit 1 without that `absent: 0` line, any other exit code, or no output at all. Read the reference anyway, and record `workpad.py update $ISSUE_NUMBER --reflection-kind note --reflection "…"` naming what you observed: the reason token when one was reported, the exit code when it was outside the contract, or the no-output condition itself, rather than a token you did not receive. An unavailable operand is never read as "nothing was deferred": that reading silently strands acknowledged findings.

Marker contract. Accept the load only when the file's first line is its `start` boundary marker and its last line the matching `end` marker, each naming that file's own path. A reference the reader returns only in pages — a partial-view notice with an `offset`/`limit` continuation — is not a mismatched marker: page it forward until a page adds no new content or no continuation is offered and apply this rule to the assembled whole document, recording the paged recovery in a `--note`; only a read the reader cannot complete, or a message you cannot classify as that notice, is the degraded arm below.

Degraded arm — degrade, never halt. When the predicate holds and the reference read fails — absent, empty, harness-refused, or mismatched boundary markers — record `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "…"` naming the reference path `skills/implement/references/deferred-review-findings.md` and stating that deferred review findings were not filed, then continue to §4.1 without halting Phase 4. This arm uses `dropped-failed`; the unestablished arm uses `note`.

### 4.1 Update Documentation

The routine doc pass always runs — narrative never suppresses it. A narrative claim that documentation is unnecessary — including an absent, empty, or contradictory `**Documentation Needed**` bullet — never suppresses the routine documentation pass: the documentation subagent that invokes the `prflow:docs` skill still runs and updates the documentation the shipped behavior change warrants. The `**Documentation Needed**` bullet is an additive floor of mandatory deliverables, never a ceiling.

Stage 1 — Pre-flight briefing (before dispatch). Extract the issue's required documentation deliverables deterministically — do not interpret the prose yourself.

Shared read contract (both stages). The helper owns the scratch file and fails closed itself, so never treat its empty stdout as a no-op. Every line is self-identifying by prefix, never positional: find the single `docgate-outcome: ` line anywhere in the tool result and read the token after that prefix, and take the deliverables as the values after each `docgate-path: ` prefix. Route on that token and the invocation's exit status, never on a captured shell variable:

- `deliverables` (0) — the printed paths are the required deliverables.
- `no-deliverables` (10) — the legitimate empty signal.
- `body-read-failed` (11) or `extract-failed` (12) — fail closed: `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind dropped-failed --reflection "Phase 4.1: <observed token> — the Documentation Needed deliverable list could not be read; the deliverable cross-check could not run — retry"`, naming the token observed, then emit the 👎 outcome reaction and stop.
- Residual arm — every other observation routes to that same `Blocked` path, because a deliverable gate that continues on an unestablished read is not a gate: no output at all; no `docgate-outcome: ` line in the result; more than one `docgate-outcome: ` line; an unrecognized token; a recognized token paired with a status this contract does not pair it with; any status outside `{0, 10, 11, 12}`; and any reading that the helper did not run at all — `command not found`, `No such file`, `Permission denied`, rc 126, rc 127.

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/read-doc-needed-deliverables.sh $ISSUE_NUMBER
```

Span-suppression breadcrumb disclosure (once per run). The extractor emits a one-time `suppressed a span` breadcrumb on stderr that this gate does not capture. Record the residual once by Stage 1 so it is disclosed: `workpad.py update $ISSUE_NUMBER --note "Phase 4.1: extractor span-suppression breadcrumbs are not durably observable on the cloud tier (stderr not captured); a suppressed command/grant literal in the Documentation Needed block leaves no run-record trace"`.

If the helper reports `no-deliverables` but the issue body still contains a Documentation Needed section in either accepted form — the bold-bullet `**Documentation Needed**` form or a `### Documentation Needed` heading (`gh issue view $ISSUE_NUMBER --json body --jq '.body' | grep -qE '\*\*Documentation Needed\*\*|^###[[:space:]]+\*{0,2}Documentation Needed'`) — record a workpad note (`workpad.py update $ISSUE_NUMBER --note "Phase 4.1: Documentation Needed section present but the extractor found no file paths; the deliverable cross-check is skipped this run"`).

Dispatch barrier. Every subagent dispatch described here is bound by the dispatch-collection requirement in the engine-ground-truth block injected into this run's prompt — read it there (if your prompt carries no such block, collect every dispatch before the turn ends anyway).

Spawn a **subagent** (using the Agent tool) and instruct it to invoke the `prflow:docs` skill. Compose the dispatch instruction: begin with "Invoke the `prflow:docs` skill to update all documentation (internal docs, external docs, release notes). The issue context is provided for release notes generation." If Stage 1 reported `deliverables`, append: " The issue requires the following files to be updated; treat each as a mandatory deliverable: `<path1>`, `<path2>`, …" Send this composed instruction along with the issue title and number inline. **Hand the issue body off by path, not paste:** when the §1.1 cache was written, add an `Issue body path: .prflow/tmp/issue-body/issue-<ISSUE_NUMBER>.md` line instructing that subagent to Read that file directly, and do **not** paste the body into the prompt. **Only** ship this line when the §1.1 write landed — on the degraded arm where no cache was written, **paste the issue body inline** instead.

Consumer prompt-extension by-path handoff. A subagent cannot resolve its own skill anchor, so the `prflow:docs` child cannot reach its consumer prompt extension. So append this sentence unconditionally to the composed dispatch instruction, substituting the repository root you resolve (`git rev-parse --show-toplevel`) for `<REPO_ROOT>`: "Consumer prompt-extension handoff: your extension file for this skill is at the absolute path `<REPO_ROOT>/.prflow/prompt-extensions/docs.md`. Read it with your file-read tool and honor any content as instructions appended to the `prflow:docs` skill's own prompt. If the file is absent or empty, treat it as a no-op and report nothing about it; if it is present but you cannot read it, report that in your return so the orchestrator can relay it." Run no probe and read no extension file yourself — no extension content enters this orchestrator's context on any path. If the docs subagent's return reports its extension was present but unreadable, relay it — add a `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.1: consumer prompt extension for prflow:docs present but unreadable: <reported detail>"` bullet naming the child skill — this relay never blocks the docs pass.

Commit each documentation artifact changed by the completed subagent. Read configured paths from `.prflow/config.json` — `config-get.sh` prints each value; read all four results and substitute non-empty values as literals below. (A `VAR=$(…)` capture does not survive across Bash tool calls on the cloud runner — values expand empty in the later call and `git add ""` fails.)

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.internal docs/internal/
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.external docs/external/
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.release_notes_file ""
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.changelog_file ""
```

Each invocation is a separate observed tool call. For the required internal and external roots, success is rc 0 plus exactly one non-empty printed path. For the optional release-notes and changelog files, rc 0 with empty output means that artifact is disabled; any non-empty output must be exactly one path. A matcher refusal, non-zero exit, multi-line/non-path output, or empty required path is not "no documentation changes": retry that read once, then mark the workpad `Blocked` with a `dropped-failed` reflection naming the config key, emit the outcome reaction, and stop. Accept only repo-relative paths that do not begin with `-`.

Inspect unfiltered `git status --short` after the docs subagent returns. Build the explicit staging list from every documentation artifact that dispatch changed: configured internal/external paths, each enabled release-notes/changelog file, every `Documentation Needed` path, and any other doc/release artifact the subagent reports and `git status` confirms (for example `README.md` or a `.changeset/` entry). Do not stage unrelated code or pre-existing dirty paths. If that explicit list contains changes, stage and commit the literal paths:
```bash
git add "<literal-doc-path-1>" "<literal-doc-path-2>" # include every changed doc/release artifact; omit absent optional paths
git commit -m "docs: update documentation for issue #$ARGUMENTS"
git push
```

Only when the subagent returned cleanly and unfiltered status confirms it produced no documentation artifact may this be recorded as a clean no-change pass:
```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --note "Phase 4.1: no documentation changes to commit (docs subagent ran clean / made no changes)"
```

Then decide whether the docs pass succeeded: it succeeded if the docs subagent actually ran — either it produced changes (committed above) or it returned cleanly with no changes needed. If instead the docs subagent failed, returned no useful output, or was unable to run, that is actionable: add a `--reflection-kind dropped-failed --reflection "…"` bullet to the workpad and do not apply the post-docs labels at all (now or later). Post-docs label application is deferred to the end of Stage 2 (the label resolution is shown there).

**Stage 2 — Post-hoc diff gate (mandatory when Stage 1 found named paths).** After the docs-subagent commit and before ticking `Documentation`, verify that every required-deliverable path has been touched. Re-run the **same deterministic helper** as Stage 1 — do not rely on remembered Stage 1 output:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/read-doc-needed-deliverables.sh $ISSUE_NUMBER
```

Route the token and its paired exit status by the Shared read contract stated in Stage 1 above, residual arm included.

1. No-op when empty. If the helper reported `no-deliverables`, this cross-check is a no-op — proceed directly to the post-docs-labels + `--tick-progress "Documentation"` step below.

2. Compute the diff once; fail closed on a broken command. Establish the base branch name you hold from Phase 1.4 — re-derive it exactly as Phase 1.4 does when you do not, applying its non-empty fallback and not just the config read, since the read alone returns nothing on malformed config — so when the read yields an empty value, substitute the literal `main`, never an empty string. Substitute that name for `<base-branch>` in each fence below: it is your own context state, not a shell variable the fence can read, and an unsubstituted or empty placeholder collapses the range to `origin/...HEAD` and judges every path absent. Compute the cumulative diff as a single command, and read its printed lines and exit status from the tool result — never a captured shell variable:
   ```bash
   git diff --name-only "origin/<base-branch>...HEAD"
   ```
   Route on the exit status read from the tool result:
   - exit 0 — the printed lines are the cumulative diff. An rc-0 result with empty output is not a failure: it is the genuine "touched none of these files" signal.
   - non-zero — re-fetch the base once and recompute, each its own single statement:
     ```bash
     git fetch origin <base-branch>
     ```
     ```bash
     git diff --name-only "origin/<base-branch>...HEAD"
     ```
     If this recompute also exits non-zero, fail closed — never fall through to a path-absent verdict on a broken command: `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind dropped-failed --reflection "Phase 4.1: could not compute the cumulative diff for the Documentation Needed gate (git diff / base-fetch failed — offline, auth, or wrong trunk)"`, then emit the 👎 outcome reaction and STOP the run.

   For each path Stage 2's helper reported as a `docgate-path: ` value (read from the tool result), decide satisfied vs absent against the diff lines read from the tool result: if it is a bare filename (contains no `/`), any diff entry whose basename matches it counts as satisfied; if it contains a `/`, it must appear as an exact match.

3. Repair each absent path, then block on any you could not deliver. For each absent path a repair is owed: `Read` `<skill-dir>/references/doc-deliverable-self-heal.md` — via this file's entry-gate anchor, under the Marker contract stated at §4.0 — and follow it for that path.

   Failed-load arm — halt, unlike the §4.0 and §4.0.5 degraded arms. A reference the reader returns only in pages (a partial-view notice with an `offset`/`limit` continuation) is not such a failure — page it forward until a page adds no new content or no continuation is offered and apply the marker rule to the assembled document, recording the paged recovery in a `--note`; only a read the reader cannot complete, or a message you cannot classify as that notice, takes this arm. When that read fails — absent, empty, harness-refused, or mismatched boundary markers — record `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.1: skills/implement/references/doc-deliverable-self-heal.md unreadable; no self-heal attempted for <path>"`, then do not tick `Documentation` and do not proceed to the labels step: take the terminal below.

   Undeliverable-path terminal. Collect every absent path the reference did not return an explicit repaired-and-verified outcome for, or reported any evidence the repair did not land for — whichever occurs, and including a path it reported nothing about, since an absent report is not a delivered file (a repair that could not be derived, a reference that could not be loaded, a repair that did not land per its re-check, and a procedure interrupted before it reported are examples of the first limb, not the test). When the last absent path has been attempted, do not tick `Documentation` — route to the Blocked path, issuing this write once per collected path with that path substituted for `<path>`: `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Phase 4.1: Documentation Needed file content cannot be determined for <path> — the docs subagent did not update this file and the correct content cannot be derived from the issue body; update manually and re-run Phase 4.1"`, then emit the 👎 outcome reaction (see *Outcome reaction* in the Workpad Reference) once and stop; stopping at the first such path would report one missing deliverable when several are missing.

Once every named path is satisfied (or Stage 1 found no paths), apply the deferred post-docs labels — only when the docs pass succeeded per the Stage-1 decision above. `docs.labels` is a comma-separated list (default `Documented`); normalize it (split on commas, trim each entry, drop empties) and apply through the shared REST label-apply helper. The REST path needs the PR number explicitly, so resolve it first from the current branch:

**Cloud-emission discipline (label helpers): iterate at the agent level, never in a shell loop or a capture — see the *Cloud command-shape discipline* section in `skills/implement/SKILL.md`.** The `apply-labels.sh` call must be a single leading-token statement, not nested inside an `if` compound, and the config read must fail closed on no output rather than reading a possible denial as "no labels configured". Resolve the label list and the PR number as two separate single-statement commands, reading each result from the tool output (a shell variable does not survive into a later separate command on the cloud runner):

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.labels Documented
```
```bash
gh pr view --json number --jq '.number'
```

Normalize the resolved `docs.labels` value at the agent level — split on commas, trim each entry, drop empties — never through a `tr`/`sed`/`grep` pipeline (`paste` is granted in no allowlist, and a piped tail refuses the whole command and empties the read).

Four exits before any label is applied — the same fail-closed set the deferral channels carry, routed on the two tool results and their exit statuses, never a captured variable:

- config-get produced no output at all. The command was refused, not answered. Do not read it as "no labels": record it and apply nothing — `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.1 could not resolve docs.labels — the config-get command produced no output at all (likely a harness denial, not an empty config); the PR carries none of the configured docs labels."`
- config-get exited non-zero. A hard read failure (config-get rc≠0 — corrupt config.json or python3 missing): record it and apply nothing — `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.1 could not read docs.labels (config-get rc≠0 — corrupt config.json or python3 missing); the PR carries none of the configured docs labels."`
- the PR-number command produced empty output. An empty value (a `gh` error, warning-corrupted output) is a real failure point, not a reason to skip silently and tick Documentation complete: record it and apply nothing — `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.1 could not resolve the PR number to apply docs labels; the PR carries none of the configured docs labels."`
- config-get exit 0 whose value is empty or trims to no entries. The config genuinely resolved to no labels: apply nothing — the clean no-op.

Otherwise, read the resolved PR number and the normalized label list and apply the labels with single granted-literal leading-token calls, iterating at the agent level:

- For each label in the printed comma-list (skip blanks), ensure it exists with one call — the helper path is the leading token, and `ensure-label.sh` is best-effort (always exits 0). `ensure-label.sh` always breadcrumbs to stderr, so no output at all means the command was refused by the harness — record it (`--reflection-kind dropped-failed`) and continue to the apply, which reports separately whether the label landed.
  ```bash
  "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/ensure-label.sh "<label>"
  ```
- Apply the whole comma-list to the PR with one call — the helper path is the leading token, the PR number and resolved label list substituted as literals (not `$DOCS_PR_NUM`/`$CLEAN_LABELS` shell variables):
  ```bash
  "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/apply-labels.sh <docs-pr-number> "<docs-labels>"
  ```
  `apply-labels.sh` is best-effort and always prints a breadcrumb to stderr — a harness refusal is its ONLY silent outcome. Read that stderr from the tool result and route on it — all four outcomes, not just the failure one: a `devflow: applied label(s) '…' to #N` line means the labels landed; a `devflow: warning: could not apply …` line is an API failure; a `devflow: warning: apply-labels.sh got no label content …` or `… got a non-numeric issue/PR number …` line is a caller arg-slip — re-emit the call once with the printed literal values before recording anything; and no output at all means the command was refused by the harness. Record any surviving non-success durably, naming which outcome it was: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.1 could not apply the configured docs labels (<docs-labels>) to PR #<docs-pr-number> — the apply reported an API failure or a caller arg-slip, or produced no output at all (a harness denial); the PR carries none of the configured docs labels."`

Then tick the Documentation phase in the workpad: `workpad.py update $ISSUE_NUMBER --tick-progress "Documentation"`.

Discharge every 3.4-deferred documentation AC (mandatory, before §4.3). Phase 3.4's *Documentation-AC deferral* rule leaves any acceptance criterion whose satisfaction is a Phase-4.1-owned `docs/…` edit unticked at the gate, recording it in a workpad note of the form `3.4: doc-AC deferred to Phase 4.1: {AC text}`. For each such deferred doc-AC confirm the docs the criterion required actually landed in this run's diff, then tick it by its 1-based position, citing the deferral note — `workpad.py update $ISSUE_NUMBER --tick-ac-n {N} --note "Phase 4.1 discharged 3.4-deferred doc-AC: {AC text} — docs authored by the prflow:docs pass"` (consume the tick call's outcome line per the failure-isolation contract; a `remedy=retick-named-rows` or `remedy=retick-and-reset-status` means the index did not resolve — re-resolve and re-tick). This tick must happen before §4.3's terminal `--status Complete` write, because `scripts/workpad.py`'s `_terminal_complete_gate` hard-fails a Complete write while any non-post-merge Acceptance Criteria row is still `- [ ]`. If a deferred doc-AC genuinely cannot be discharged (the docs pass could not author it and the content cannot be derived), do not tick it and do not finalize Complete: take the existing Blocked path (`workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Phase 4.1: 3.4-deferred doc-AC could not be discharged: {AC text}"`), emit the 👎 outcome reaction, and stop.

Re-anchor before §4.2 (mandatory, after the Phase 4.1 documentation subagent returns and its docs are committed). Before proceeding to §4.2, `Read` `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/phases/phase-4-documentation.md` again and follow it exactly — re-anchoring the remaining §4.2 (PR description) and §4.3 (finalize) procedure, never relying on the earlier entry-gate read. This re-anchor is scoped to **subagent** returns — here, the Phase 4.1 docs subagent; do not apply it to the Phase 2 or Phase 3 subagent returns, whose phases carry their own entry-gate reads.

### 4.2 Generate PR Description

Dispatch barrier. As at §4.1, every subagent dispatch here is bound by the dispatch-collection requirement in the engine-ground-truth block injected into this run's prompt.

Spawn one general-purpose subagent (using the Agent tool) that both updates the PR description and reconciles its claims, so the diff-reading claim audit runs in the subagent's own context, not this orchestrator's. Compose its dispatch instruction to direct it to:

1. Invoke the `prflow:pr-description` skill with the issue number as its argument (`$ARGUMENTS`). The skill detects the existing PR and updates its body directly. After it returns, confirm the update landed and did not leave the placeholder — `gh pr view --json body --jq '.body' | grep -q "Work in progress — automated review pending"` — and report whether the body was updated from its placeholder (updated / still-placeholder / could-not-determine).
2. Reconcile the PR body's claims — a three-class claim audit. Re-read the whole PR body and audit it against three claim classes — behavioral, verification, and artifact-existence — each naming its own comparand and producing its own recorded outcome. The artifact — the code, the tests, and the filed artifacts — is the fact, under the same fix-or-rewrite rule as §2.3.4a.
   1. Behavioral claims — comparand: the actual shipped code path, followed into pre-existing code the diff calls. For every behavioral claim the body makes about what the shipped code does (a "this PR adds X that does Y", a described flow, a stated guarantee, or a `## Post-Merge Verification` item that on inspection actually describes *already-shipped* behavior rather than a genuinely live-only check), trace the actual shipped code path and confirm the code does what the body says. A claim satisfied by pre-existing code the diff merely calls is true.
   2. **Verification claims** — comparand: the tests actually present in this PR's diff. Audit every `## Test Plan` row that asserts a fact about the diff's tests, and every "pinned by" / "covered by" / "exercised by" / "mutation-proven" / suite-tally / coverage-enumeration assertion anywhere in the body. Bind each member the claim's own literal scope enumerates to a named test present in this PR's diff; a member with no such test makes the row false, and the row is rewritten to what the tests actually cover before finalize. An imperative Test Plan row ("the test suite is green end-to-end") asserts nothing about the diff's tests and passes trivially. A claim honest about being transitive ("covered through the shared validation routine") is true with the tests that exist; the remedy for an over-broad row is its wording, not necessarily a new test.
   3. **Artifact-existence claims** — comparand: the artifact's own resolvable identifier (an issue or PR number, or a repo-relative path). Audit every body assertion that a separate artifact exists or was created — a follow-up issue, a filed deferral, a linked issue or PR, a cutover or growth artifact, a docs page, a changeset. A claim carrying no resolvable issue/PR number and no repo-relative path is false as written and is rewritten before finalize to state what actually exists. This class does not force a follow-up issue to be filed (Phase 4.0 owns filing): "Deferred to a follow-up: <items>" names no artifact and states an intention, so it passes; "A follow-up issue tracks the deferred half" names an artifact and needs the number.

   Resolution (shared across all three classes). A claim that fails its class is resolved by fix-or-rewrite — "note it and move on" is not an arm:

   - If the body overclaims (asserts something the diff, its tests, or the filed artifacts do not deliver), correct the body to the truth via REST: write the corrected body to a file, resolve the PR number (guarding the empty case), and PATCH it. The `-F body=@<file>` form reads the field value literally from the file, preserving backticks and `$`:
     ```bash
     gh pr view --json number --jq '.number'
     ```
     Read the PR number from the tool result. If it is empty, do not PATCH — the overclaiming body could not be corrected (best-effort, continue). Otherwise PATCH with the number substituted as a literal:
     ```bash
     gh api --method PATCH "repos/{owner}/{repo}/pulls/<pr-number>" -F body=@<file>
     ```
   - If reconciliation reveals the code is actually wrong (the body states the intended behavior but the diff doesn't meet it), fix the code (leaving the edit in the working tree for the orchestrator to commit — see the post-return commit step below) and report that a code-level fix was made. On the default `ready_for_review` path that fix rides into the cloud `/prflow:review`; when `implement_pr_state=draft` the PR is left a draft and the cloud review does not auto-fire until a human publishes (see §4.3).
   - When an artifact-existence claim is corrected, correct every site this run authored it at in the same change — the PR body, the workpad Acceptance Criteria preamble, the workpad Plan, any reflection bullet, and the changeset — under the repo's coupled-mirror rule.
3. Return a COMPACT record, not the body or the diff: whether the PR body was updated from its placeholder (per step 1); the per-class outcome for each of the three claim classes ({claims checked and how resolved | no claims of this class — pass complete}); and whether a code-level fix was made (per the Resolution step).

Consumer prompt-extension by-path handoff. A subagent cannot resolve its own skill anchor, so the `prflow:pr-description` child cannot reach its consumer prompt extension. So append this sentence unconditionally to the composed dispatch instruction, substituting the repository root you resolve (`git rev-parse --show-toplevel`) for `<REPO_ROOT>`: "Consumer prompt-extension handoff: your extension file for this skill is at the absolute path `<REPO_ROOT>/.prflow/prompt-extensions/pr-description.md`. Read it with your file-read tool and honor any content as instructions appended to the `prflow:pr-description` skill's own prompt. If the file is absent or empty, treat it as a no-op and report nothing about it; if it is present but you cannot read it, report that in your return so the orchestrator can relay it." Run no probe and read no extension file yourself — no extension content enters this orchestrator's context on any path. If the subagent's return reports its extension was present but unreadable, relay it — add a `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.2: consumer prompt extension for prflow:pr-description present but unreadable: <reported detail>"` bullet naming the child skill — this relay never blocks the PR-description pass.

Hand the issue body off by path, not paste: when the §1.1 cache was written, add an `Issue body path: .prflow/tmp/issue-body/issue-<ISSUE_NUMBER>.md` line instructing the subagent to Read that file directly, and do not paste the body into the prompt. Only ship this line when the §1.1 write landed — on the degraded arm where no cache was written, paste the issue body inline instead. Send the issue title and number inline on every arm.

Record-usability precondition (before any bookkeeping — unknown is not zero). Before the bookkeeping below, confirm the subagent's returned record carries each of: the placeholder-update status, the three per-class audit outcomes (behavioral, verification, artifact-existence), and the code-fix flag. If any of these is absent or unparseable, or the placeholder status is still-placeholder or could-not-determine, re-dispatch the §4.2 subagent exactly once with the same instruction; a good record on this second return proceeds to the bookkeeping below. If the second return is still missing a data point or still reports still-placeholder/could-not-determine, do not proceed to §4.3 — take the Blocked path (`workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Phase 4.2: the PR-description subagent returned an unusable record (missing data point or unresolved placeholder) after one re-dispatch — cannot audit the body's claims; not finalizing"`), emit the 👎 outcome reaction, and stop.

After the subagent returns — orchestrator bookkeeping (do not re-read the body or the diff). Record the audit outcomes and the placeholder status from the subagent's returned record:

- Record one workpad `--note` outcome per class, reading each from the subagent's returned record; a class the subagent reported found nothing records an explicit clean-pass note, so a class that ran clean is distinguishable from a class that never ran:
  ```bash
  "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER \
    --note "4.2 claim audit (behavioral): {claims checked and how resolved | no behavioral claims to reconcile — pass complete}" \
    --note "4.2 claim audit (verification): {rows checked and how resolved | no verification claims found — pass complete}" \
    --note "4.2 claim audit (artifact-existence): {assertions checked and how resolved | no artifact-existence claims found — pass complete}"
  ```
- Determine whether the PR body changed from its placeholder from the subagent's returned status. Record that resolved status via `--note`.
- If the returned record says a code-level fix was made, record in `Devflow Reflection` that a post-review code fix landed here so it is not mistaken for a reviewed change — and flag it more loudly on the draft path, where no automatic re-review will catch it.

Never finalize a PR whose subagent-returned record asserts a behavior the diff does not deliver, a coverage the diff's tests do not contain, or an artifact that does not exist — a class the subagent could not resolve to a clean pass or a fix-or-rewrite is a Blocked condition, not a note-and-move-on.

Commit the subagent's working-tree edits before §4.3. The subagent's `fix:` code edit (and any body-file scratch it left) lives in this orchestrator's own checkout, so commit it now rather than leaving it for §4.3's clean-tree backstop. Inspect unfiltered `git status --short` after the subagent returns; if it shows changes the subagent made, stage the literal paths explicitly (do not `git add -A`/`.` and do not stage unrelated code or pre-existing dirty paths), then commit and push with a `fix:` prefix (a body-only correction rides in the same commit):
```bash
git status --short
git add "<literal-path-1>" "<literal-path-2>" # every path the §4.2 subagent changed; omit unrelated/pre-existing dirty paths
git commit -m "fix: reconcile PR description claims for issue #$ARGUMENTS"
git push
```
When unfiltered status confirms the subagent produced no working-tree change, this is a no-op.

Re-anchor before §4.3 (mandatory, after the Phase 4.2 PR-description subagent returns and its edits are committed). Before proceeding to §4.3, `Read` `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/phases/phase-4-documentation.md` again and follow it exactly — re-anchoring the remaining §4.3 (finalize) procedure, never relying on the earlier entry-gate read. This re-anchor fires on a **subagent** return only — here, the Phase 4.2 pr-description subagent.


### 4.3 Finalize the PR (publish or leave draft) and Finalize Workpad

Clean-tree backstop (always, before the publish decision). Assert nothing uncommitted survives the run:

```bash
git status --porcelain
```

If it is non-empty, do not finalize yet. Anything dirty here is this run's own work an earlier phase failed to commit. Commit the part that belongs to this PR with the right prefix (`feat:`/`fix:`/`docs:`/`chore:`) and push, and record which phase under-committed via `--reflection-kind note --reflection "…"`. Surface (do not blindly `git add`) any unexpected untracked file. When the tree is already clean this is a no-op — create no empty commit.

Run-transient files are the exception — delete, never commit. A leftover reflection-payload file under `.prflow/tmp/` is run-transient scratch, not a deliverable: if one survives here, delete it rather than committing it (a plugin-only adopter has no `.prflow/.gitignore` scaffold, so it shows up untracked and a blind `git add` would commit it into the PR).

**Base-branch update checkpoint 4 (pre-ready) — after the clean-tree backstop, before the publish decision.** Bring the branch up to date one last time:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/update-branch-checkpoint.sh
```

Handle the printed token per the implement-driven outcome-handling contract in phase-1-setup.md §1.4.1 — its record-and-continue arm for `UNVERIFIED`/`PUSH_REJECTED` is checkpoints 1-3 only; at THIS checkpoint the publish gate below overrides both to a refusal — with one checkpoint-4-specific addition that gates the publish below:

- On `UPDATED` a real merge landed and the pushed state was not seen by any review pass — but no separate suite run is owed here. Proceed to the publish gate below and let that flight be the gate.
- On `UP_TO_DATE` / `DISABLED` nothing changed, so no suite re-run is needed — proceed to the publish decision unchanged.

Read the token as the leading word of the emitted line, never as the whole line — the matching rule `scripts/update-branch-checkpoint.sh`'s own header states. Read it from the invocation's output, never from a shell capture (a `TOKEN=$(…)` capture changes the statement's leading token away from the vendored-literal form).

First, separate "the invocation never ran" from "the invocation ran and reported something" — and be honest about which denials are observable. The invocation is known to have never run only when the tool boundary *reports* it — a local-tier classifier denial message, or an rc 127. Those take the *tier-refused* arm at the end of this section. A silent cloud matcher denial produces no output and no failure signal, so it takes the refusal arm below (fail-closed), not the tier-refused arm. Everything else ran, routed by the gate below on the first field of its output.

Publish gate (checkpoint-4-specific — the run does not publish or complete on a non-clean checkpoint). The clean set is `UPDATED`, `UP_TO_DATE`, `DISABLED`; the non-clean set is `CONFLICT`, `UNVERIFIED`, `PUSH_REJECTED`, `MERGE_IN_PROGRESS`. Route the observed first field:

- Clean (`UPDATED` / `UP_TO_DATE` / `DISABLED`) — record the checkpoint-4 evidence row naming the observed token **before** publishing, on all three alike, through the keyed-checkpoint carrier: `workpad.py update $ISSUE_NUMBER --checkpoint base-update-checkpoint-4 "checkpoint 4: observed token <token> — clean, proceeding to the publish decision"`. `--checkpoint` is a *structural* failure with zero PATCH on a non-canonical body (a duplicate `## Progress`, an empty body — an *absent* `## Progress` is repaired, not refused); the terminal `--status Complete` write is gated on this exact keyed row, so a `--checkpoint` call that exits non-zero here fails this step closed — resolve the non-canonical workpad body and retry. Then proceed.
- `CONFLICT` — not routed to the refusal below. It follows §1.4.1's inherited resolve-then-suite-then-commit-then-push path (a resolution that fails the suite keeps that contract's abort-and-`Blocked` path), and the checkpoint helper is then **re-invoked**; the first field of *that re-invocation's* line is the value this gate reads. The re-invocation is **bounded to one**: a second consecutive `CONFLICT` takes the refusal arm below rather than resolving again.
- **Non-clean (`UNVERIFIED`, `PUSH_REJECTED`, `MERGE_IN_PROGRESS`), or a first field that is empty or unrecognized** — **refuse to run `gh pr ready` and refuse to flip `Status` to `Complete`.** A run that never reconciled with the base must not reach a published, `Complete` end state with no signal that its work was never checked against current trunk. **On `UNVERIFIED`, or an empty/unrecognized field, re-invoke the helper once before refusing**. **`PUSH_REJECTED` and `MERGE_IN_PROGRESS` get no re-invocation** — they refuse immediately. Grade the re-invocation's first field where one was made; if it is still non-clean, record `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "checkpoint 4: the base-update checkpoint did not report a clean token after one re-invocation — observed line: <the observed line, verbatim>; helper breadcrumb: <the helper's own stderr breadcrumb, verbatim>; not publishing and not completing"` — then emit the 👎 outcome reaction and stop.

The discriminator for "the helper did not report a token" is observable, not "no output at all": no line whose leading word is a member of the helper's documented token set appears in the invocation's combined output. That case takes the refusal arm above as an unrecognized field.

An invocation whose refusal the tier REPORTS is a distinct case, and it publishes. The checkpoint never ran, so there is no token to grade — record it through the keyed-checkpoint carrier under its own key: `workpad.py update $ISSUE_NUMBER --checkpoint base-update-checkpoint-4-tier-refused "checkpoint 4: the update-branch-checkpoint invocation was refused by this tier (<denial/rc 127>) — base reconciliation at pre-ready is unverified this run; publishing per §1.4.1's degraded posture"`. A `--checkpoint` call that itself exits non-zero here fails this step closed. Then proceed to the publish decision, matching §1.4.1's degraded posture. It does **not** route to `Blocked`.

Establish final-tree completion evidence — after checkpoint 4, before the publish decision. Phase 3's flight is stale here (Phase 4 mutated the candidate), so `scripts/workpad.py` gates the `--status Complete` write on a current, passing flight for the final in-env verification command. Run it as the run's single whole-suite obligation at the scope this repository's implement prompt extension sets, or the full whole-suite command when it sets none; parallelize it only as that command does — never relaxing a conflict resolution's suite run staying serialized before its commit.

1. Launch one verification flight for the final tree via the fence below, running the allowlisted verification command unchanged as its own leading token between `mark-running` and `finish`. Author the `claim` declaration and `finish --summary-file` with the Write tool under `.prflow/tmp/` (no redirect/heredoc); each operand (`<key>`, `<tok>`, paths) is an agent-level literal, not a shell capture. Set `candidate_identity` from `reception-record.py`'s stdout (null fails the gate). `checkout-fingerprint.py`'s JSON is the `checkout` field, and a freshly-produced one is each `status`/`wait` re-anchor's `--current-checkout-file`. The summary's nonempty `command` and empty `skipped_checks` are enforced by `scripts/check-completion-evidence.py`, not `verification-flight.py`. For subcommand behavior read the module header and `--help`: `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/verification-flight.py`.

```bash
.prflow/vendor/prflow/scripts/checkout-fingerprint.py
.prflow/vendor/prflow/scripts/verification-flight.py claim --input-file .prflow/tmp/c.json
.prflow/vendor/prflow/scripts/verification-flight.py mark-running --flight <key> --token <tok>
.prflow/vendor/prflow/scripts/verification-flight.py finish --flight <key> --token <tok> --result passed --summary-file .prflow/tmp/s.json
.prflow/vendor/prflow/scripts/verification-flight.py status --flight <key> --current-checkout-file .prflow/tmp/f.json
```

On any reading a vendored path did not run — `command not found`, `No such file`, `Permission denied`, rc 126, rc 127 — re-invoke through the anchor; every other vendored line takes the same `.prflow/vendor/prflow/` prefix removal:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/checkout-fingerprint.py
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/verification-flight.py
```

Author the declaration from this template — substitute only the `<…>` placeholders; `schema_version` stays `1`, `external_services` `"none"`, the four `checkout` object-id fields keep example hex replaced from `checkout-fingerprint.py`:

```json
{"schema_version": 1, "candidate_identity": "<candidate_identity>",
 "profile": {"profile_version": "<ver>", "argv": ["<cmd+args>"], "cwd": "<cwd>",
   "environment": {}, "toolchain": {}, "dependencies": {}, "output_roots": [], "external_services": "none"},
 "checkout": {"checkout_id": "<checkout_id>",
   "head": "1111111111111111111111111111111111111111", "index_digest": "2222222222222222222222222222222222222222",
   "tracked_digest": "3333333333333333333333333333333333333333", "untracked_digest": "4444444444444444444444444444444444444444"}}
```
2. Record the validated flight key on the workpad: `workpad.py update $ISSUE_NUMBER --record-completion-evidence <flight-key>` (the `<flight-key>` is the `flight_key` value `claim`/`finish` printed). This validates the record under the implement-completion policy and, only on a pass, writes the hidden `completion-verification:<flight-key>` marker (replacing any prior one). A non-pass record aborts this call before any PATCH — do not proceed to Complete; take the Blocked path below.
3. On a non-pass or unrunnable suite → Blocked, never Complete. A failed suite, a non-empty skip population, or a verification command that is not locally re-runnable on this tier means there is no in-env pass for the final candidate, so the run cannot honestly finalize: `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Phase 4.3: final-tree verification did not establish a clean in-env pass (<token/cause>) — cannot record completion evidence; not publishing/completing"`, emit the 👎 reaction, and stop. This step is the sole owner of the unrunnable-verification case: a tier-refused verification routes to Blocked here rather than publishing-and-completing.

An execution ceiling is not a verdict. When the tier's per-command execution ceiling *terminated* the command instead of letting it reach a result, no failure and no skip population was observed, so item 3 does not apply. Take the decomposition path the implement prompt extension states, then establish the flight from that, per item 1. Only when the recombined run itself cannot be observed does the run stop: `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Phase 4.3: execution-ceiling — the whole-suite verification could not be OBSERVED inside this tier's per-command ceiling (<command>); decomposition was attempted and <outcome>. No suite failure or skip population was observed, so this is a runner limit, not a verdict on the change"`, emit the 👎 reaction, and stop.

The off-switch is honored: with `.verification_flight.enabled` set to `false`, an implement run still runs this claim/mark-running/finish sequence to produce the machine record completion requires — `false` suppresses only flight *reuse*, not the record's production.

Review-coverage precondition — before the publish decision. Read the review-coverage record §3.3 stamped on the workpad (`## Progress`, `<!-- prflow:checkpoint review-coverage:… -->`). If it is complete — either a measured clean pass (`coverage=full`, `dispatch=attempted`, `roster=complete`, `checklist=complete` or `skipped-intentional`) or the no-shadow-owed record §3.3 stamps on the `REJECT` branch and the severity-aware soft-proceed (`not-applicable` on all four axes; a mixture of `not-applicable` and measured values is refused as `[review-coverage-unestablished]`) — proceed unchanged. If it records a gap and this run holds for each gap a true reason that names that specific gap and is at least 20 characters — over a record reading `dispatch=attempted`, pass one `--review-coverage-disposition <gap> "<reason>"` per gap (`shadow-coverage`, `roster`, `checklist`) on the finalize `--status Complete` call below and publish. Otherwise — an absent, duplicated, malformed, or `dispatch`≠`attempted` record, or a gap with no true, specific reason statable at that length — refuse to run `gh pr ready` and refuse to flip `Status` to `Complete`: record `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Phase 4.3: review coverage is incomplete or unestablished (<the observed record, verbatim>) and gap(s) <gaps> carry no statable disposition — not publishing and not completing"`, emit the 👎 outcome reaction, and stop. The ordering matters because `gh pr ready` runs before the finalize write, so gating only the workpad would publish a PR beside a `Blocked` workpad.

Tip-landed gate (before the publish decision — guards `gh pr ready` and the `Complete` flip alike). The clean-tree backstop's short-form status reports a committed-but-unpushed tip as clean, so without this check the run publishes a PR — and records `Complete` — citing a commit the remote lacks. Confirm the tip is on the remote (`git rev-parse HEAD` == `git rev-parse @{u}`), classifying `HEAD` in order:

- Detached HEAD (`git rev-parse --abbrev-ref HEAD` prints `HEAD`) or no upstream (`git rev-parse @{u}` exits non-zero on a real branch): neither is *by itself* an unpushed tip, so the gate never `Blocked`s on the classification alone. But without `@{u}` it has no landing comparand, so it confirms the remote holds `HEAD` directly with `git branch -r --contains HEAD` (reads local remote-tracking refs, like `@{u}`): a non-empty result → record a `--note` naming the state and proceed; an empty result → the remote lacks `HEAD`, so route to the unpushed handling below (push and re-verify, else Blocked).
- Measurement unestablished — a needed `git rev-parse` is refused or returns no output at all (the local-tier classifier can refuse it; distinct from a resolved value). The tip-on-remote state cannot be read and no positive check can run either, so record a `--note` naming it and proceed under the degraded posture — never collapse this onto an unpushed-tip `Blocked`.
- `@{u}` equals `HEAD` (landed): proceed to the publish decision.
- `@{u}` differs (unpushed): `git push`, then re-read both. Equal now → note it and proceed; still unequal (push rejected, or an `Everything up-to-date` push left them apart) → refuse to run `gh pr ready` and refuse to flip `Status` to `Complete`: `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "tip-landed gate: local branch tip \`$(git rev-parse HEAD)\` is not on the remote and a push did not land it — refusing to publish or complete a run whose body would cite a commit the remote lacks; land it and re-run"`, emit the 👎 outcome reaction (see *Outcome reaction* in the Workpad Reference), remove the run marker, and stop.

**Publish decision — `implement_pr_state`.** Resolve it as a single command and read the printed value from the tool result (default `ready_for_review`; a hard read failure — non-zero exit or no output — falls back to `ready_for_review`). Publish **only** when the value is not the exact literal `draft` — a missing key, empty string, or any unrecognized value publishes.

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .prflow_implement.implement_pr_state ready_for_review
```

Carry an outcome value — one of `draft` | `published` | `publish_failed` — that the finalize wording below reads. Route on the resolved value read from the tool result:

- exactly `draft` — leave the PR the draft from Phase 3.1: do not run `gh pr ready`, post no additional comment to the PR thread, and set the outcome to `draft`.
- anything else — run `gh pr ready` and read its exit status from the tool result:
  ```bash
  gh pr ready
  ```
  - exit 0 — outcome `published`.
  - non-zero — `gh pr ready` returns non-zero on any *already non-draft* PR, so confirm the real state before concluding failure:
    ```bash
    gh pr view --json isDraft --jq '.isDraft'
    ```
    Read the printed value: exactly `false` → the PR is already non-draft → outcome `published` (idempotent re-run). Anything else, an error, or no output at all → outcome `publish_failed` (still a draft, or the state could not be confirmed) — fail closed, never record `published` on an unestablished read.

Then finalize the workpad — tick the final `## Progress` item and flip `Status` to `Complete` in every case; only the `--note` wording differs. Pick the `--note` by the outcome you carried:

- `draft` outcome → `--note "/prflow:implement run finished, PR left as draft per implement_pr_state=draft: <PR_URL>"`
- `published` outcome → `--note "/prflow:implement run finished, PR published (gh pr ready): <PR_URL>"`
- `publish_failed` outcome → `--note "/prflow:implement run finished, but gh pr ready FAILED — PR is still a draft, or its state could not be confirmed: <PR_URL>"` and emit a separate `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "gh pr ready failed at Phase 4.3 — PR left unpublished despite implement_pr_state not being draft; publish it manually (gh pr ready) so the cloud review and CI ready_for_review listener fire"` call. It is a `dropped-failed` reflection, so it goes in its own `update` call — separate from the `note`-kind finalize below — because one `--reflection-kind` applies to the whole call.

Substitute the outcome-specific `--note` above into the finalize call. The `--tick-progress "PR marked ready"` argument MUST match the `## Progress` row label owned by `scripts/workpad.py`. Consume the outcome line per the failure-isolation contract — only `remedy=none` or `remedy=reset-status` is cleanly Complete, and an absent line means the write did not land. The token tells the failures apart: (1) `remedy=retick-named-rows` / `remedy=retick-and-reset-status`, a volatile tick miss (body WAS PATCHed, Status flipped, only the "PR marked ready" row still `- [ ]`) → re-tick just that row, adding `--status Complete` again when the remedy names it; (1a) `outcome=precondition-mismatch` (`remedy=re-resolve-state`) → re-read the live workpad and re-decide, never re-send; (2) `outcome=not-persisted` (`remedy=reissue-call`), a structural abort (NO PATCH, Status NOT flipped) when a non-post-merge `## Acceptance Criteria` row is still unticked, or the review-coverage record is unestablished / a recorded gap / undispatched / boilerplate → resolve per Phase 3.4 (`--tick-ac-n {N}` or the Blocked path) or stamp/disposition the record per §3.3 (the undispatched arm has no in-run remedy → Blocked), THEN re-issue; never retry verbatim. (Post-merge AC rows never trip this; an unticked `## Plan` row or an un-mirrored AC placeholder only warns.)

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER \
    --status Complete \
    --tick-progress "PR marked ready" \
    --note "{outcome-specific note above}" \
    [--review-coverage-disposition <gap> "<reason>" ...repeat per gap] \
    [--reflection-kind note --reflection "{noteworthy event}" ...repeat --reflection per event]
```

Add one `--reflection` flag per noteworthy event a human should know for troubleshooting: a failed step that was skipped, a subagent that returned no useful output, a permission denial, a test you couldn't run, an ambiguity you resolved with an assumption, or any deviation from the planned flow. Kind each by the reflection style contract's routing rule (see `skills/implement/SKILL.md`); genuinely actionable failures are emitted at the point they occur with `--reflection-kind dropped-failed` so they land under `### ⚠️ Action required`. `--reflection` is repeatable so all the same-kind events land in a single atomic update.

Finally, emit the 🎉 outcome reaction on the triggering comment (`REACTION=hooray`; see *Outcome reaction* in the Workpad Reference) in every case, then output the PR URL and a one- or two-line summary of what was accomplished (state whether the PR was published, left a draft, or whether `gh pr ready` failed).

<!-- prflow:implement-ref phase=4 file=skills/implement/phases/phase-4-documentation.md end -->
