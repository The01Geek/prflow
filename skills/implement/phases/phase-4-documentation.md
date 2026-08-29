<!-- prflow:implement-ref phase=4 file=skills/implement/phases/phase-4-documentation.md start -->
## Phase 4: Documentation

Output: `Phase 4/4: Documentation — updating docs and finalizing PR...`

Writing standard. Before composing this phase's first `--reflection` bullet, read the shared writing standard and follow it.

`workpad.py update $ISSUE_NUMBER --status Documenting`.

### 4.0 File Follow-Up Issues for Deferred Work

Phase 4.0's follow-up-issue composition lives in the `deferral-drafter` subagent (`agents/deferral-drafter.md`) and its GitHub writes in the gated reference `<skill-dir>/references/deferred-ac-followups.md`, reached only when a durable predicate says work is outstanding. Ask the predicate first, substituting the PR number as a decimal literal — a `$PR_NUMBER` variable arrives empty on the cloud tier (`$ISSUE_NUMBER` per your standing substitution rule):

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py deferred-presence $ISSUE_NUMBER <this-run's-PR-number>
```

Read the exit code and printed count line from the tool result, never a captured shell variable or the workpad body. Route on the exit code:

- exit 1 — `not-outstanding: <n>`. Do not read the reference; continue to §4.0.5.
- exit 0 — `outstanding: <n>`, followed by one `criterion:` line each. `Read` `<skill-dir>/references/deferred-ac-followups.md` — via this file's entry-gate anchor — and follow it for exactly the projected criteria: it dispatches the drafter, then performs every GitHub write from the returned plan.
- exit 2 — `unestablished: reason=<token> unbound=<u> corrupted=<c>`, or no count line at all. Read the reference anyway (it handles any `filed:` lines the count line carries), and record `workpad.py update $ISSUE_NUMBER --reflection-kind note --reflection "…"` naming which operand could not be established, quoting the reason token and both counts. An unavailable operand is never read as "nothing was deferred": that reading silently strands deferred work.

Marker contract. Accept the load only when the file's first line is its `start` boundary marker and its last line the matching `end` marker, each naming that file's own path. A reference returned only in pages (a partial-view notice with an `offset`/`limit` continuation) is not a mismatched marker: page forward until no continuation is offered or a page adds nothing new, apply this rule to the assembled whole, and record the recovery in a `--note`. A read you cannot complete, a gap in the page sequence, or an unclassifiable message is the degraded arm below.

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
- **exit 1 *and* the printed line is exactly `absent: 0`.** Do not read the reference; continue to §4.1. Both conditions are required, since exit 1 is also a crashing interpreter's status.
- Every other outcome — exit 2 with `unestablished: reason=<token>` (optionally a `root:` line), exit 1 without that `absent: 0` line, any other exit code, or no output at all. Read the reference anyway, and record `workpad.py update $ISSUE_NUMBER --reflection-kind note --reflection "…"` naming what you observed: the reason token when one was reported, the exit code when it was outside the contract, or the no-output condition itself. An unavailable operand is never read as "nothing was deferred": that reading silently strands acknowledged findings.

Marker contract. Accept the load only when the file's first line is its `start` boundary marker and its last line the matching `end` marker, each naming that file's own path. A reference returned only in pages (a partial-view notice with an `offset`/`limit` continuation) is not a mismatched marker: page forward until no continuation is offered or a page adds nothing new, apply this rule to the assembled whole, and record the recovery in a `--note`. A read you cannot complete, a gap in the page sequence, or an unclassifiable message is the degraded arm below.

Degraded arm — degrade, never halt. When the predicate holds and the reference read fails — absent, empty, harness-refused, or mismatched boundary markers — record `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "…"` naming the reference path `skills/implement/references/deferred-review-findings.md` and stating that deferred review findings were not filed, then continue to §4.1 without halting Phase 4. This arm uses `dropped-failed`; the unestablished arm uses `note`.

### 4.0.6 Audit Deferred Reflections Are Backed

A `--reflection-kind deferred` reflection renders under "⚠️ Action required" and reads as handled, yet may be backed by no tracked deferral — filed nowhere. Audit each, as a single statement whose leading token is the granted vendored literal, substituting this run's PR number as a decimal literal (as §4.0 does, and for the same reason):

```bash
.prflow/vendor/prflow/scripts/workpad.py deferred-reflection-audit $ISSUE_NUMBER <this-run's-PR-number>
```

On any reading that says the vendored path did not *run* — `command not found`, `No such file`, `Permission denied`, rc 126 or rc 127 — re-invoke the same helper through the portable anchor:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py deferred-reflection-audit $ISSUE_NUMBER <this-run's-PR-number>
```

Read the exit code and printed line from the tool result, never a captured shell variable. Route on the exit code:

- exit 0 — `backed: <n>`. Every deferred reflection is backed; continue to §4.1, no action.
- exit 1 — `unbacked: <n>`, followed by one `text:` line each. Record `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0.6: <n> deferred reflection(s) backed by no tracked deferral for this PR — filed nowhere: <the text(s)>"`, then continue to §4.1. Do not silently pass completion.
- exit 2 — `unestablished: reason=<token> unbound=<u> corrupted=<c>`, or no output. Record `workpad.py update $ISSUE_NUMBER --reflection-kind note --reflection "…"` quoting the reason token (or the no-output condition), then continue. Never read an unestablished audit as "nothing unbacked".

### 4.1 Update Documentation

The routine doc pass always runs — narrative never suppresses it. The routine doc pass always runs. A claim that documentation is unnecessary — including an absent, empty, or contradictory `**Documentation Needed**` bullet — never suppresses it: the documentation subagent that invokes the `prflow:docs` skill still runs and updates the documentation the shipped change warrants. The `**Documentation Needed**` bullet is an additive floor of mandatory deliverables, never a ceiling.

Stage 1 — Pre-flight briefing (before dispatch). Extract the issue's required documentation deliverables deterministically — do not interpret the prose yourself.

Shared read contract (both stages). The helper owns the scratch file and fails closed itself, so never treat its empty stdout as a no-op. Every line is self-identifying by prefix, never positional: find the single `docgate-outcome: ` line anywhere in the tool result and read the token after that prefix, and take the deliverables as the values after each `docgate-path: ` prefix. Route on that token and the invocation's exit status, never on a captured shell variable:

- `deliverables` (0) — the printed paths are the required deliverables.
- `no-deliverables` (10) — the legitimate empty signal.
- `body-read-failed` (11) or `extract-failed` (12) — fail closed: `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind dropped-failed --reflection "Phase 4.1: <observed token> — the Documentation Needed deliverable list could not be read; the deliverable cross-check could not run — retry"`, naming the token observed, then emit the 👎 outcome reaction and stop.
- Residual arm — every other observation routes to that same `Blocked` path (a gate that continues on an unestablished read is not a gate): no output at all; no `docgate-outcome: ` line in the result; more than one `docgate-outcome: ` line; an unrecognized token; a recognized token paired with a status this contract does not pair it with; any status outside `{0, 10, 11, 12}`; and any reading the helper did not run at all — `command not found`, `No such file`, `Permission denied`, rc 126, rc 127.

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/read-doc-needed-deliverables.sh $ISSUE_NUMBER
```

Span-suppression note (only when the extractor dropped a span). When Stage 1's tool result holds a `docgate-suppressed: ` line — the read boundary's relay that the extractor suppressed a span — take its value as the span text, write `Phase 4.1: extractor suppressed a Documentation Needed span: <span>` (that value substituted, cut to fit the 2048-byte note budget) with the Write tool to `.prflow/tmp/docgate-suppressed-note-$ISSUE_NUMBER.txt`, then record it with `workpad.py update $ISSUE_NUMBER --note-file .prflow/tmp/docgate-suppressed-note-$ISSUE_NUMBER.txt` — never a double-quoted `--note "…"` argument, since the span is third-party text. No such line, no note; Stage 2 records nothing.

If the helper reports `no-deliverables` but the issue body still contains a Documentation Needed section in either accepted form — the bold-bullet `**Documentation Needed**` form or a `### Documentation Needed` heading (`gh issue view $ISSUE_NUMBER --json body --jq '.body' | grep -qE '\*\*Documentation Needed\*\*|^###[[:space:]]+\*{0,2}Documentation Needed'`) — record a workpad note (`workpad.py update $ISSUE_NUMBER --note "Phase 4.1: Documentation Needed section present but the extractor found no file paths; the deliverable cross-check is skipped this run"`).

Dispatch barrier. Every subagent dispatch described here is bound by the dispatch-collection requirement in the engine-ground-truth block injected into this run's prompt — read it there (if your prompt carries no such block, collect every dispatch before the turn ends anyway).

Spawn a **subagent** (using the Agent tool) and instruct it to invoke the `prflow:docs` skill. Compose the dispatch instruction: begin with "Invoke the `prflow:docs` skill to update all documentation (internal docs, external docs, release notes). The issue context is provided for release notes generation." If Stage 1 reported `deliverables`, append: " The issue requires the following files to be updated; treat each as a mandatory deliverable: `<path1>`, `<path2>`, …" Send this composed instruction along with the issue title and number inline. **Hand the issue body off by path, not paste:** when the §1.1 cache was written, add an `Issue body path: .prflow/tmp/issue-body/issue-<ISSUE_NUMBER>.md` line instructing that subagent to Read that file directly, and do **not** paste the body into the prompt. **Only** ship this line when the §1.1 write landed — on the degraded arm where no cache was written, **paste the issue body inline** instead.

Consumer prompt-extension by-path handoff. A subagent cannot resolve its own skill anchor, so append this sentence unconditionally to the composed dispatch instruction, substituting the repository root you resolve (`git rev-parse --show-toplevel`) for `<REPO_ROOT>`: "Consumer prompt-extension handoff: your extension file for this skill is at the absolute path `<REPO_ROOT>/.prflow/prompt-extensions/docs.md`. Read it with your file-read tool and honor any content as instructions appended to the `prflow:docs` skill's own prompt. If the file is absent or empty, treat it as a no-op and report nothing about it; if it is present but you cannot read it, report that in your return so the orchestrator can relay it." Run no probe and read no extension file yourself — no extension content enters this orchestrator's context on any path. If the docs subagent's return reports its extension was present but unreadable, relay it — add a `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.1: consumer prompt extension for prflow:docs present but unreadable: <reported detail>"` bullet naming the child skill — this relay never blocks the docs pass.

Commit each documentation artifact changed by the completed subagent. Read configured paths from `.prflow/config.json` — `config-get.sh` prints each value; read all five results and substitute non-empty values as literals below. (A `VAR=$(…)` capture does not survive across Bash tool calls on the cloud runner.)

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.internal docs/internal/
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.external docs/external/
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.external_enabled true
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.release_notes_file docs/external/release-notes.md
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.changelog_file CHANGELOG.md
```

Each invocation is a separate observed tool call. For the required internal root, success is rc 0 plus exactly one non-empty printed path. The external root is required only while `.docs.external_enabled` resolved to anything other than the exact literal `false`: on `false` the consumer has disabled external-doc alignment, so an empty or failed `.docs.external` read is not a `Blocked` condition — treat every external artifact as absent in the staging list below and continue (without this arm, a repo that set the toggle off is blocked on a key it deliberately does not use). For the release-notes and changelog files, the defaults above are the same paths the `prflow:docs-release-notes` child resolves for itself, so the staging list below covers what that child may have written in an unconfigured repo; success is rc 0 plus exactly one printed path, and rc 0 with empty output (a consumer resolver override that prints nothing) means that artifact is disabled. A matcher refusal, non-zero exit, multi-line/non-path output, or empty required path is not "no documentation changes": retry that read once, then mark the workpad `Blocked` with a `dropped-failed` reflection naming the config key, emit the outcome reaction, and stop. Accept only repo-relative paths that do not begin with `-`.

Inspect unfiltered `git status --short` after the docs subagent returns. Build the explicit staging list from every documentation artifact that dispatch changed: the configured internal path, the configured external path (omitted when `.docs.external_enabled` resolved to `false`), each enabled release-notes/changelog file, every `Documentation Needed` path, and any other doc/release artifact the subagent reports and `git status` confirms (for example `README.md` or a `.changeset/` entry). Do not stage unrelated code or pre-existing dirty paths. If that explicit list contains changes, stage and commit the literal paths:
```bash
git add "<literal-doc-path-1>" "<literal-doc-path-2>" # include every changed doc/release artifact; omit absent optional paths
git commit -m "docs: update documentation for issue #$ARGUMENTS"
git push
```

Only when the subagent returned cleanly and unfiltered status confirms it produced no documentation artifact may this be recorded as a clean no-change pass:
```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --note "Phase 4.1: no documentation changes to commit (docs subagent ran clean / made no changes)"
```

Then decide whether the docs pass succeeded: it succeeded if the docs subagent actually ran — either it produced changes (committed above) or it returned cleanly with no changes needed. If instead the docs subagent failed, returned no useful output, or was unable to run, add a `--reflection-kind dropped-failed --reflection "…"` bullet to the workpad and do not apply the post-docs labels at all (now or later). Post-docs label application is deferred to the end of Stage 2.

**Stage 2 — Post-hoc diff gate (mandatory when Stage 1 found named paths).** After the docs-subagent commit and before ticking `Documentation`, verify that every required-deliverable path has been touched. Re-run the **same deterministic helper** as Stage 1 — do not rely on remembered Stage 1 output:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/read-doc-needed-deliverables.sh $ISSUE_NUMBER
```

Route the token and its paired exit status by the Shared read contract stated in Stage 1 above, residual arm included.

1. No-op when empty. If the helper reported `no-deliverables`, this cross-check is a no-op — proceed directly to the post-docs-labels + `--tick-progress "Documentation"` step below.

2. Compute the diff once; fail closed on a broken command. Establish the base branch name you hold from Phase 1.4 — re-derive it exactly as Phase 1.4 does when you do not, applying its non-empty fallback and not just the config read — so when the read yields an empty value, substitute the literal `main`, never an empty string. Substitute that name for `<base-branch>` in each fence below: it is your own context state, not a shell variable the fence can read, and an unsubstituted or empty placeholder judges every path absent. Compute the cumulative diff as a single command, and read its printed lines and exit status from the tool result — never a captured shell variable:
   ```bash
   git diff --name-only "origin/<base-branch>...HEAD"
   ```
   Route on the exit status read from the tool result:
   - exit 0 — the printed lines are the cumulative diff. An rc-0 result with empty output is the genuine "touched none of these files" signal, not a failure.
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

   Failed-load arm — halt, unlike the §4.0 and §4.0.5 degraded arms. A reference returned only in pages (a partial-view notice with an `offset`/`limit` continuation) is not such a failure: page forward until no continuation is offered or a page adds nothing new, apply the marker rule to the assembled whole, and record the recovery in a `--note`. A read you cannot complete, a gap in the page sequence, or an unclassifiable message takes this arm. When that read fails — absent, empty, harness-refused, or mismatched boundary markers — record `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.1: skills/implement/references/doc-deliverable-self-heal.md unreadable; no self-heal attempted for <path>"`, then do not tick `Documentation` and do not proceed to the labels step: take the terminal below.

   Undeliverable-path terminal. Collect every absent path the reference did not return an explicit repaired-and-verified outcome for, or reported any evidence the repair did not land for — whichever occurs, and including a path it reported nothing about (an absent report is not a delivered file). When the last absent path has been attempted, do not tick `Documentation` — route to the Blocked path, issuing this write once per collected path with that path substituted for `<path>`: `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Phase 4.1: Documentation Needed file content cannot be determined for <path> — the docs subagent did not update this file and the correct content cannot be derived from the issue body; update manually and re-run Phase 4.1"`, then emit the 👎 outcome reaction (see *Outcome reaction* in the Workpad Reference) once and stop — stopping at the first such path would under-report the missing deliverables.

Once every named path is satisfied (or Stage 1 found no paths), apply the deferred post-docs labels — only when the docs pass succeeded per the Stage-1 decision above. The REST label path needs the PR number explicitly, so resolve it first from the current branch:

**Cloud-emission discipline (label helpers): emit the call as a single leading-token statement, never a shell loop or a capture — see the *Cloud command-shape discipline* section in `skills/implement/SKILL.md`.** The `apply-labels.sh` call must be a single leading-token statement, not nested inside an `if` compound. Resolve the PR number as its own single-statement command, reading the result from the tool output (a shell variable does not survive into a later separate command):

```bash
gh pr view --json number --jq '.number'
```

One exit before the apply: if the PR-number command produced empty output — a `gh` error or warning-corrupted output — do not skip silently and tick Documentation complete: record it and apply nothing — `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.1 could not resolve the PR number to apply docs labels; the PR carries none of the configured docs labels."`

Otherwise apply the configured docs labels with one call — the helper resolves `.docs.labels` (fallback `Documented`) itself by running `config-get.sh .docs.labels Documented` internally, creates each label, and applies them, so no agent-side config read, normalization, or per-label ensure call is owed. Substitute the digits of the PR number printed above for `<docs-pr-number>` (a literal, never `$DOCS_PR_NUM`):
```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/apply-labels.sh <docs-pr-number> --config-key .docs.labels --config-fallback Documented
```

`apply-labels.sh` always exits 0 and prints exactly one stdout outcome token — `applied | nothing-to-apply | arg-slip | api-failure | config-unreadable`. `applied` means the labels landed and `nothing-to-apply` is the clean no-op (the config resolved to no labels); the run continues regardless. Any other token, or no output at all — a harness refusal, its only silent outcome — must not vanish: record it durably naming the token and continue — `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.1 could not apply the configured docs labels to PR #<docs-pr-number> — apply-labels.sh reported <token> (or produced no output at all, a harness denial); the PR carries none of the configured docs labels."` An invocation that failed because the helper path does not exist (`No such file`, exit 127) is an anchor-resolution failure, not a label outcome.

Then tick the Documentation phase in the workpad: `workpad.py update $ISSUE_NUMBER --tick-progress "Documentation"`.

Discharge every 3.4-deferred documentation AC (mandatory, before §4.3). Phase 3.4's *Documentation-AC deferral* rule leaves any acceptance criterion whose satisfaction is a Phase-4.1-owned `docs/…` edit unticked at the gate, recording it in a workpad note of the form `3.4: doc-AC deferred to Phase 4.1: {AC text}`. For each such deferred doc-AC confirm the docs the criterion required actually landed in this run's diff, then tick it by its 1-based position, citing the deferral note — `workpad.py update $ISSUE_NUMBER --tick-ac-n {N} --note "Phase 4.1 discharged 3.4-deferred doc-AC: {AC text} — docs authored by the prflow:docs pass"` (consume the tick call's outcome line per the failure-isolation contract; a `remedy=retick-named-rows` or `remedy=retick-and-reset-status` means the index did not resolve — re-resolve and re-tick). When a deferred criterion instead names a check command, discharge it only after the docs commit by running that command yourself, in your own tool call over the landed docs — when the tier does not grant it, the covering run `lib/test/modules/coverage-map.json` names for that unit — and quote the result line of the command you actually ran in the tick note; a subagent's report that it ran the command does not discharge the criterion, and the tick note names no result of a gate that has not run yet. When the tier refuses both the named command and its covering run, leave the criterion unticked and take this paragraph's existing Blocked arm below, its reflection naming `prflow_implement.allowed_tools` as the remedy. This tick must happen before §4.3's terminal `--status Complete` write, which `_terminal_complete_gate` hard-fails while any non-post-merge Acceptance Criteria row is still `- [ ]`. If a deferred doc-AC genuinely cannot be discharged (the docs pass could not author it and the content cannot be derived), do not tick it and do not finalize Complete: take the existing Blocked path (`workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Phase 4.1: 3.4-deferred doc-AC could not be discharged: {AC text}"`), emit the 👎 outcome reaction, and stop. <!-- pruned-path-ok: issue #2129 AC6 names the coverage map as the source of a check command's covering run; lib/test is PRFlow-internal and the covering-run fallback is a PRFlow-repo mechanism -->

Resume directly at §4.2 (after the Phase 4.1 documentation subagent returns and its docs are committed). The docs subagent is an Agent-tool dispatch whose return enters this context as a report only, so proceed to §4.2 directly — do not re-dispatch the §4.1 docs subagent, and do not re-read this phase file. The prompt-extension re-load still fires at this boundary (SKILL.md's re-load trigger).

### 4.2 Generate PR Description

Dispatch barrier. Every subagent dispatch here is bound by the dispatch-collection requirement in the engine-ground-truth block injected into this run's prompt — read it there (if your prompt carries no such block, collect every dispatch before the turn ends anyway).

Spawn one general-purpose subagent (using the Agent tool) that both updates the PR description and reconciles its claims in the subagent's own context, not this orchestrator's. Compose its dispatch instruction to direct it to:

1. Invoke the `prflow:pr-description` skill with the issue number as its argument (`$ARGUMENTS`). The skill detects the existing PR and updates its body directly. After it returns, confirm the update landed and did not leave the placeholder — `gh pr view --json body --jq '.body' | grep -q "Work in progress — automated review pending"` — and report whether the body was updated from its placeholder (updated / still-placeholder / could-not-determine).
2. Reconcile the PR body's claims — a three-class claim audit. Re-read the whole PR body and audit it against three claim classes — behavioral, verification, and artifact-existence — each with its own comparand and recorded outcome. The artifact — code, tests, and filed artifacts — is the fact, under the same fix-or-rewrite rule as §2.3.4a.
   1. Behavioral claims — comparand: the actual shipped code path, followed into pre-existing code the diff calls. For every behavioral claim the body makes about what the shipped code does (including a `## Post-Merge Verification` item that on inspection actually describes *already-shipped* behavior rather than a genuinely live-only check), trace the actual shipped code path and confirm the code does what the body says. A claim satisfied by pre-existing code the diff merely calls is true.
   2. **Verification claims** — comparand: the tests actually present in this PR's diff. Audit every `## Test Plan` row that asserts a fact about the diff's tests, and every "pinned by" / "covered by" / "exercised by" / "mutation-proven" / suite-tally / coverage-enumeration assertion anywhere in the body. Bind each member the claim's own literal scope enumerates to a named test present in this PR's diff; a member with no such test makes the row false, and the row is rewritten to what the tests actually cover before finalize. An imperative Test Plan row ("the test suite is green end-to-end") asserts nothing about the diff's tests and passes trivially. A claim honest about being transitive ("covered through the shared validation routine") is true with the tests that exist; the remedy for an over-broad row is its wording. A Test Plan line that records a *test-authoring proportionality waiver* — stating that specific auxiliary ceremony was deliberately not written, and why — is not a verification claim: it asserts nothing about a test that exists, so leave it in place verbatim rather than binding it to a named test or rewriting it as an unbacked test claim.
   3. **Artifact-existence claims** — comparand: the artifact's own resolvable identifier (an issue or PR number, or a repo-relative path). Audit every body assertion that a separate artifact exists or was created (a follow-up issue, filed deferral, linked issue/PR, cutover/growth artifact, docs page, changeset). A claim carrying no resolvable issue/PR number and no repo-relative path is false as written and is rewritten before finalize to state what actually exists. This class does not force a follow-up issue to be filed (Phase 4.0 owns filing): "Deferred to a follow-up: <items>" names no artifact and states an intention, so it passes; "A follow-up issue tracks the deferred half" names an artifact and needs the number.

   Resolution (shared across all three classes). A claim that fails its class is resolved by fix-or-rewrite — "note it and move on" is not an arm:

   - If the body overclaims (asserts something the diff, its tests, or the filed artifacts do not deliver), correct the body to the truth via REST: write the corrected body to a file, resolve the PR number (guarding the empty case), and PATCH it with the `-F body=@<file>` form (reads the value literally, preserving backticks and `$`):
     ```bash
     gh pr view --json number --jq '.number'
     ```
     Read the PR number from the tool result. If it is empty, do not PATCH — the overclaiming body could not be corrected (best-effort, continue). Otherwise PATCH with the number substituted as a literal:
     ```bash
     gh api --method PATCH "repos/{owner}/{repo}/pulls/<pr-number>" -F body=@<file>
     ```
   - If reconciliation reveals the code is actually wrong (the body states the intended behavior but the diff doesn't meet it), fix the code (leaving the edit in the working tree for the orchestrator to commit — see the post-return commit step below) and report that a code-level fix was made.
   - When an artifact-existence claim is corrected, correct every site this run authored it at in the same change — the PR body, the workpad Acceptance Criteria preamble, the workpad Plan, any reflection bullet, and the changeset — under the repo's coupled-mirror rule.
3. Return a COMPACT record, not the body or the diff: whether the PR body was updated from its placeholder (per step 1); the per-class outcome for each of the three claim classes ({claims checked and how resolved | no claims of this class — pass complete}); and whether a code-level fix was made (per the Resolution step).

Consumer prompt-extension by-path handoff. A subagent cannot resolve its own skill anchor, so append this sentence unconditionally to the composed dispatch instruction, substituting the repository root you resolve (`git rev-parse --show-toplevel`) for `<REPO_ROOT>`: "Consumer prompt-extension handoff: your extension file for this skill is at the absolute path `<REPO_ROOT>/.prflow/prompt-extensions/pr-description.md`. Read it with your file-read tool and honor any content as instructions appended to the `prflow:pr-description` skill's own prompt. If the file is absent or empty, treat it as a no-op and report nothing about it; if it is present but you cannot read it, report that in your return so the orchestrator can relay it." Run no probe and read no extension file yourself — no extension content enters this orchestrator's context on any path. If the subagent's return reports its extension was present but unreadable, relay it — add a `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.2: consumer prompt extension for prflow:pr-description present but unreadable: <reported detail>"` bullet naming the child skill — this relay never blocks the PR-description pass.

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
- If the returned record says a code-level fix was made, record in `Devflow Reflection` that a post-review code fix landed here — and flag it more loudly on the draft path, where no automatic re-review will catch it.

Never finalize a PR whose subagent-returned record asserts a behavior the diff does not deliver, a coverage the diff's tests do not contain, or an artifact that does not exist — a class the subagent could not resolve to a clean pass or a fix-or-rewrite is a Blocked condition, not a note-and-move-on.

Commit the subagent's working-tree edits before §4.3. The subagent's `fix:` code edit (and any body-file scratch it left) lives in this orchestrator's own checkout, so commit it now rather than leaving it for §4.3's clean-tree backstop. Inspect unfiltered `git status --short` after the subagent returns; if it shows changes the subagent made, stage the literal paths explicitly (do not `git add -A`/`.` and do not stage unrelated code or pre-existing dirty paths), then commit and push with a `fix:` prefix (a body-only correction rides in the same commit):
```bash
git status --short
git add "<literal-path-1>" "<literal-path-2>" # every path the §4.2 subagent changed; omit unrelated/pre-existing dirty paths
git commit -m "fix: reconcile PR description claims for issue #$ARGUMENTS"
git push
```
When unfiltered status confirms the subagent produced no working-tree change, this is a no-op.

Resume directly at §4.3 (after the Phase 4.2 PR-description subagent returns and its edits are committed). The PR-description subagent is an Agent-tool dispatch whose return enters this context as a report only, so proceed to §4.3 directly — do not re-dispatch the §4.2 subagent, and do not re-read this phase file. The prompt-extension re-load still fires at this boundary (SKILL.md's re-load trigger).


### 4.3 Finalize the PR (publish or leave draft) and Finalize Workpad

Clean-tree backstop (always, before the publish decision). Assert nothing uncommitted survives the run:

```bash
git status --porcelain
```

If it is non-empty, do not finalize yet. Commit the part that belongs to this PR with the right prefix (`feat:`/`fix:`/`docs:`/`chore:`) and push, and record which phase under-committed via `--reflection-kind note --reflection "…"`. Surface (do not blindly `git add`) any unexpected untracked file. When the tree is already clean this is a no-op — create no empty commit.

Run-transient files are the exception — delete, never commit. A leftover reflection-payload file under `.prflow/tmp/` is run-transient scratch, not a deliverable: if one survives here, delete it rather than committing it (a plugin-only adopter has no `.prflow/.gitignore` scaffold, so a blind `git add` would commit it into the PR).

**Base-branch update checkpoint 4 (pre-ready) — after the clean-tree backstop, before the publish decision.** Bring the branch up to date one last time:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/update-branch-checkpoint.sh
```

Handle the printed token per the implement-driven outcome-handling contract in phase-1-setup.md §1.4.1 — its record-and-continue arm for `UNVERIFIED`/`PUSH_REJECTED` is checkpoints 1-3 only; at THIS checkpoint the publish gate below overrides both to a refusal — with one checkpoint-4-specific addition that gates the publish below:

- On `UPDATED` a real merge landed, but no separate suite run is owed here. Proceed to the publish gate below and let that flight be the gate.
- On `UP_TO_DATE` / `DISABLED` nothing changed — proceed to the publish decision unchanged.

Read the token as the leading word of the emitted line, never as the whole line — the matching rule `scripts/update-branch-checkpoint.sh`'s own header states. Read it from the invocation's output, never from a shell capture.

First, separate "the invocation never ran" from "the invocation ran and reported something" — and be honest about which denials are observable. The invocation is known to have never run only when the tool boundary *reports* it — a local-tier classifier denial message, or an rc 127. Those take the *tier-refused* arm at the end of this section. A silent cloud matcher denial produces no output and no failure signal, so it takes the refusal arm below (fail-closed), not the tier-refused arm. Everything else ran, routed by the gate below on the first field of its output.

Publish gate (checkpoint-4-specific — the run does not publish or complete on a non-clean checkpoint). The clean set is `UPDATED`, `UP_TO_DATE`, `DISABLED`; the non-clean set is `CONFLICT`, `UNVERIFIED`, `PUSH_REJECTED`, `MERGE_IN_PROGRESS`. Route the observed first field:

- Clean (`UPDATED` / `UP_TO_DATE` / `DISABLED`) — record the checkpoint-4 evidence row naming the observed token **before** publishing, on all three alike, through the keyed-checkpoint carrier: `workpad.py update $ISSUE_NUMBER --checkpoint base-update-checkpoint-4 "checkpoint 4: observed token <token> — clean, proceeding to the publish decision"`. `--checkpoint` is a *structural* failure with zero PATCH on a non-canonical body (a duplicate `## Progress`, an empty body — an *absent* `## Progress` is repaired, not refused); the terminal `--status Complete` write is gated on this exact keyed row, so a `--checkpoint` call that exits non-zero here fails this step closed — resolve the non-canonical workpad body and retry. Then proceed.
- `CONFLICT` — not routed to the refusal below. It follows §1.4.1's inherited resolve-then-suite-then-commit-then-push path (a resolution that fails the suite keeps that contract's abort-and-`Blocked` path), and the checkpoint helper is then **re-invoked**; the first field of *that re-invocation's* line is the value this gate reads. The re-invocation is **bounded to one**: a second consecutive `CONFLICT` takes the refusal arm below rather than resolving again.
- **Non-clean (`UNVERIFIED`, `PUSH_REJECTED`, `MERGE_IN_PROGRESS`), or a first field that is empty or unrecognized** — **refuse to run `gh pr ready` and refuse to flip `Status` to `Complete`.** A run that never reconciled with the base must not reach a published, `Complete` end state with no signal that its work was never checked against current trunk. **On `UNVERIFIED`, or an empty/unrecognized field, re-invoke the helper once before refusing**. **`PUSH_REJECTED` and `MERGE_IN_PROGRESS` get no re-invocation** — they refuse immediately. Grade the re-invocation's first field where one was made; if it is still non-clean, record `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "checkpoint 4: the base-update checkpoint did not report a clean token after one re-invocation — observed line: <the observed line, verbatim>; helper breadcrumb: <the helper's own stderr breadcrumb, verbatim>; not publishing and not completing"` — then emit the 👎 outcome reaction and stop.

The discriminator for "the helper did not report a token" is observable, not "no output at all": no line whose leading word is a member of the helper's documented token set appears in the invocation's combined output. That case takes the refusal arm above as an unrecognized field.

An invocation whose refusal the tier REPORTS is a distinct case, and it publishes. The checkpoint never ran, so there is no token to grade — record it through the keyed-checkpoint carrier under its own key: `workpad.py update $ISSUE_NUMBER --checkpoint base-update-checkpoint-4-tier-refused "checkpoint 4: the update-branch-checkpoint invocation was refused by this tier (<denial/rc 127>) — base reconciliation at pre-ready is unverified this run; publishing per §1.4.1's degraded posture"`. A `--checkpoint` call that itself exits non-zero here fails this step closed. Then proceed to the publish decision, matching §1.4.1's degraded posture. It does **not** route to `Blocked`.

Establish final-tree completion evidence — after checkpoint 4, before the publish decision. Phase 3's flight is stale here (Phase 4 mutated the candidate), so `scripts/workpad.py` gates the `--status Complete` write on a current, passing flight for the final in-env verification command. Run it as the run's single whole-suite obligation at the scope this repository's implement prompt extension sets, or the full whole-suite command when it sets none; parallelize it only as that command does — never relaxing a conflict resolution's suite run staying serialized before its commit. The single-flight consult obligation this flight discharges is scoped to any suite execution — whole-suite, shard, or focused, not only a full-suite relaunch — and reuse draws on the retained log whichever runner named it, so a clean handled result is re-read rather than re-executed (consistent with the run's other single-flight copies).

1. Launch one verification flight for the final tree via the fence below, running the allowlisted verification command unchanged as its own leading token between `mark-running` and `finish`. Author the `claim` declaration and `finish --summary-file` with the Write tool under `.prflow/tmp/` (no redirect/heredoc); each operand (`<key>`, `<tok>`, paths) is an agent-level literal, not a shell capture. Set `candidate_identity` from `reception-record.py`'s stdout (null fails the gate). `checkout-fingerprint.py`'s JSON is the `checkout` field, and a freshly-produced one is each `status`/`wait` re-anchor's `--current-checkout-file`. The summary's nonempty `command` and empty `skipped_checks` are enforced by `scripts/check-completion-evidence.py`. For subcommand behavior read the module header and `--help`: `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/verification-flight.py`.

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

Author the declaration from the worked example `verification-flight.py claim --help` prints — the single copyable template PRFlow ships — substituting its `<…>` placeholders and replacing the example hex from `checkout-fingerprint.py`. `schema_version` stays `1`; `external_services` stays `"none"` (or the live service, recorded non-reusable); the `checkout` object comes from `checkout-fingerprint.py`; and `candidate_identity` comes from `reception-record.py`.
2. Record the validated flight key on the workpad: `workpad.py update $ISSUE_NUMBER --record-completion-evidence <flight-key>` (the `<flight-key>` is the `flight_key` value `claim`/`finish` printed). This validates the record under the implement-completion policy and, only on a pass, writes the hidden `completion-verification:<flight-key>` marker (replacing any prior one). A non-pass record aborts this call before any PATCH — do not proceed to Complete; take the Blocked path below. Also record this launch's `Verification evidence:` marker through `workpad.py update $ISSUE_NUMBER --record-verification-evidence …`, the option that owns the record's field set (see its `--help`); record it right after the launch returns, because the tool stamps the head at record time.
3. On a non-pass or unrunnable suite → Blocked, never Complete. A failed suite, a non-empty skip population, or a verification command that is not locally re-runnable on this tier means there is no in-env pass, so the run cannot honestly finalize: `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Phase 4.3: final-tree verification did not establish a clean in-env pass (<token/cause>) — cannot record completion evidence; not publishing/completing"`, emit the 👎 reaction, and stop. This step is the sole owner of the unrunnable-verification case: a tier-refused verification routes to Blocked here rather than publishing-and-completing.

An execution ceiling is not a verdict. When the tier's per-command execution ceiling *terminated* the command instead of letting it reach a result, no failure and no skip population was observed, so item 3 does not apply. Take the decomposition path the implement prompt extension states, then establish the flight from that, per item 1. Only when the recombined run itself cannot be observed does the run stop: `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Phase 4.3: execution-ceiling — the whole-suite verification could not be OBSERVED inside this tier's per-command ceiling (<command>); decomposition was attempted and <outcome>. No suite failure or skip population was observed, so this is a runner limit, not a verdict on the change"`, emit the 👎 reaction, and stop.

The off-switch is honored: with `.verification_flight.enabled` set to `false`, an implement run still runs this claim/mark-running/finish sequence to produce the machine record completion requires — `false` suppresses only flight *reuse*, not the record's production.

Review-coverage precondition — before the publish decision. Read the review-coverage record §3.3 stamped on the workpad (`## Progress`, `<!-- prflow:checkpoint review-coverage:… -->`). If it is complete — either a measured clean pass (`coverage=full`, `dispatch=attempted`, `roster=complete`, `checklist=complete` or `skipped-intentional`) or the no-shadow-owed record §3.3 stamps on the `REJECT` branch and the severity-aware soft-proceed (`not-applicable` on all four axes; a mixture of `not-applicable` and measured values is refused as `[review-coverage-unestablished]`) — proceed unchanged. If it records a gap and this run holds for each gap a true reason that names that specific gap and is at least 20 characters — over a record reading `dispatch=attempted`, pass one `--review-coverage-disposition <gap> <cause-class> "<reason>"` per gap (`shadow-coverage`, `roster`, `checklist`) on the finalize `--status Complete` call below and publish. The `<cause-class>` is the closed set `environment-denial` (a capability the runner did not expose — admissible only with a recorded `missing` roster row corroborating it) | `dispatched-but-lost` (a reviewer that was dispatched whose result was lost); there is no elective member, so a budget belief or a partial pass judged adequate has no admissible class and takes the Otherwise arm. Otherwise — an absent, duplicated, malformed, or `dispatch`≠`attempted` record, a gap with no true, specific reason statable at that length, or a gap whose only available cause is elective/inadmissible — refuse to run `gh pr ready` and refuse to flip `Status` to `Complete`: record `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Phase 4.3: review coverage is incomplete or unestablished (<the observed record, verbatim>) and gap(s) <gaps> carry no statable disposition — not publishing and not completing"`, emit the 👎 outcome reaction, and stop.

Tip-landed gate (before the publish decision — guards `gh pr ready` and the `Complete` flip alike). The clean-tree backstop reports a committed-but-unpushed tip as clean, so without this check the run would publish and complete citing a commit the remote lacks. Confirm the tip is on the remote (`git rev-parse HEAD` == `git rev-parse @{u}`), classifying `HEAD` in order:

- Detached HEAD (`git rev-parse --abbrev-ref HEAD` prints `HEAD`) or no upstream (`git rev-parse @{u}` exits non-zero on a real branch): neither is *by itself* an unpushed tip, so the gate never `Blocked`s on the classification alone. But without `@{u}` it has no landing comparand, so it confirms the remote holds `HEAD` directly with `git branch -r --contains HEAD` (reads local remote-tracking refs): a non-empty result → record a `--note` naming the state and proceed; an empty result → the remote lacks `HEAD`, so route to the unpushed handling below (push and re-verify, else Blocked).
- Measurement unestablished — a needed `git rev-parse` is refused or returns no output at all (the local-tier classifier can refuse it). The tip-on-remote state cannot be read and no positive check can run either, so record a `--note` naming it and proceed under the degraded posture, never onto an unpushed-tip `Blocked`.
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

Substitute the outcome-specific `--note` above into the finalize call. The `--tick-progress "PR marked ready"` argument MUST match the `## Progress` row label owned by `scripts/workpad.py`. Consume the outcome line per the failure-isolation contract — only `remedy=none` or `remedy=reset-status` is cleanly Complete, and an absent line means the write did not land. The token tells the failures apart: (1) `remedy=retick-named-rows` / `remedy=retick-and-reset-status`, a volatile tick miss (body PATCHed, Status flipped, only the "PR marked ready" row still `- [ ]`) → re-tick just that row, adding `--status Complete` again when the remedy names it; (1a) `outcome=precondition-mismatch` (`remedy=re-resolve-state`) → re-read the live workpad and re-decide, never re-send; (2) `outcome=not-persisted` (`remedy=reissue-call`), a structural abort (NO PATCH, Status NOT flipped) when a non-post-merge `## Acceptance Criteria` row is still unticked, or the review-coverage record is unestablished / a recorded gap / undispatched / boilerplate → resolve per Phase 3.4 (`--tick-ac-n {N}` or the Blocked path) or stamp/disposition the record per §3.3 (the undispatched arm has no in-run remedy → Blocked), THEN re-issue; never retry verbatim. (Post-merge AC rows never trip this; an unticked `## Plan` row or an un-mirrored AC placeholder only warns.)

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER \
    --status Complete \
    --tick-progress "PR marked ready" \
    --note "{outcome-specific note above}" \
    [--review-coverage-disposition <gap> <cause-class> "<reason>" ...repeat per gap] \
    [--reflection-kind note --reflection "{noteworthy event}" ...repeat --reflection per event]
```

Add one `--reflection` flag per noteworthy event a human should know for troubleshooting: a failed step that was skipped, a subagent that returned no useful output, a permission denial, a test you couldn't run, an ambiguity you resolved with an assumption, or any deviation from the planned flow. Kind each by the reflection style contract's routing rule (see `skills/implement/SKILL.md`); genuinely actionable failures are emitted at the point they occur with `--reflection-kind dropped-failed` so they land under `### ⚠️ Action required`. `--reflection` is repeatable so all the same-kind events land in a single atomic update.

Finally, emit the 🎉 outcome reaction on the triggering comment (`REACTION=hooray`; see *Outcome reaction* in the Workpad Reference) in every case, then output the PR URL and a one- or two-line summary of what was accomplished (state whether the PR was published, left a draft, or whether `gh pr ready` failed).

<!-- prflow:implement-ref phase=4 file=skills/implement/phases/phase-4-documentation.md end -->
