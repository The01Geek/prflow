<!-- prflow:implement-finalization-ref file=skills/implement/references/phase-4-finalization.md start -->
## Phase 4 worker procedure

Execute this procedure only inside `prflow:implement-finalization`. Here, “orchestrator” and “caller” mean this worker for procedure execution and child returns. When a step says to emit a terminal reaction or stop, retain its immediate workpad write, then return the stopped result to the parent; publication, Complete, reactions, and terminal scratch cleanup remain with that parent.

Sections run in file order: §4.1 — the committing block and the request — first, then §4.0–§4.0.6 and §4.2 while the request runs, then §4.3 awaits it. After the PR-description child returns and its changes are committed, resume at §4.3 without redispatching that child or reloading this procedure or the implement extension.

Writing standard. Before composing this phase's first `--reflection` bullet, read the shared writing standard and follow it.

`workpad.py update $ISSUE_NUMBER --status Documenting`.

Finalization boundary (standing rule). §4.3's clean-tree backstop never authors an implementation-code change: when one is warranted, record it via `workpad.py update $ISSUE_NUMBER --reflection-kind note` naming the path and unperformed change, then continue — no implement/review cycle, not Blocked, no rollback. §4.2 reconciliation is exempt: it resolves the body's claims against the reviewed diff under its own rule.

### 4.1 Commit and request verification

Already run (targeted resume). When the `base-update-checkpoint-4` keyed row is recorded and the `Early verification request:` note's head equals a fresh `git rev-parse HEAD`, skip the *Committing block* — re-issue the request (it prints `REUSE`) and continue at the first unmet obligation.

**Committing block (the last committing steps before the request).** The base-update checkpoint below, the consumer policy's pre-request passes, and a clean-tree push run in that order, then the *Early verification request*. Only *Already run* above skips the block; §4.3 re-enters it (its single `update-branch-checkpoint.sh` invocation) after a commit lands past the request.

**Base-branch update checkpoint 4 (pre-ready) — the block's base update, before the pre-request passes and the request.** Bring the branch up to date as the last base merge before the request:

Route on the token the helper prints and the `route:` line it prints on stderr immediately before that token, as implement-driven checkpoint 4. Do not reload Phase 1.

```bash
.prflow/vendor/prflow/scripts/update-branch-checkpoint.sh
```

On exit 127 from that vendored literal, retry once through the portable anchor:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/update-branch-checkpoint.sh
```

Handle the printed token per the shared implement-driven outcome contract — its record-and-continue arm for `UNVERIFIED`/`PUSH_REJECTED` is checkpoints 1-3 only; at THIS checkpoint the publish gate below overrides both to a refusal — with one checkpoint-4-specific addition that gates the request and the publish below:

- On `UPDATED` a real merge landed, but no separate suite run is owed here. Proceed to the publish gate below and let the request's flight be the gate.
- On `UP_TO_DATE` / `DISABLED` nothing changed — proceed unchanged.

Read the token as the leading word of the emitted line, never as the whole line — the matching rule `scripts/update-branch-checkpoint.sh`'s own header states. Read it from the invocation's output, never from a shell capture.

First, separate "the invocation never ran" from "the invocation ran and reported something" — and be honest about which denials are observable. The invocation is known to have never run only when the tool boundary *reports* it — a local-tier classifier denial message, or an rc 127. Those take the *tier-refused* arm at the end of this section. A silent cloud matcher denial produces no output and no failure signal, so it takes the refusal arm below (fail-closed), not the tier-refused arm. Everything else ran, routed by the gate below on the first field of its output.

Publish gate (checkpoint-4-specific — the run does not request, publish, or complete on a non-clean checkpoint). The clean set is `UPDATED`, `UP_TO_DATE`, `DISABLED`; the non-clean set is `CONFLICT`, `UNVERIFIED`, `PUSH_REJECTED`, `MERGE_IN_PROGRESS`. Route the observed first field:

- Clean (`UPDATED` / `UP_TO_DATE` / `DISABLED`) — record the checkpoint-4 evidence row naming the observed token **before** the request, on all three alike, through the keyed-checkpoint carrier: `workpad.py update $ISSUE_NUMBER --checkpoint base-update-checkpoint-4 "Checkpoint 4: observed token <token> — clean, proceeding to the pre-request passes and the request"`. `DISABLED` keeps that key and that route but never the word `clean` — the branch was never compared with its base — so its row text is instead `Checkpoint 4: observed token DISABLED — base-update checkpoints disabled by config; branch not reconciled with origin/<base> (setup freshness <freshness>); proceeding to the pre-request passes and the request`, `<freshness>` being the dispatched branch-setup value (`fresh`, `behind-<n>`, `unverified`, `n/a` or `unestablished`). `--checkpoint` is a *structural* failure with zero PATCH on a non-canonical body (a duplicate `## Progress`, an empty body — an *absent* `## Progress` is repaired, not refused); the terminal `--status Complete` write is gated on this exact keyed row, so a `--checkpoint` call that exits non-zero here fails this step closed — resolve the non-canonical workpad body and retry. Then proceed.
- `CONFLICT` — not routed to the refusal below. It follows the shared contract's resolve-then-suite-then-commit-then-push path (a resolution that fails the suite keeps that contract's abort-and-`Blocked` path), and the checkpoint helper is then re-invoked; the first field of *that re-invocation's* line is the value this gate reads. The re-invocation is bounded to one: a second consecutive `CONFLICT` takes the refusal arm below rather than resolving again.
- **Non-clean (`UNVERIFIED`, `PUSH_REJECTED`, `MERGE_IN_PROGRESS`), or a first field that is empty or unrecognized** — stop and return a blocked result so the parent does not request, publish, or flip `Status` to `Complete`. On `UNVERIFIED`, or an empty/unrecognized field, re-invoke the helper once before refusing; `PUSH_REJECTED` and `MERGE_IN_PROGRESS` get no re-invocation and refuse immediately. Grade the re-invocation's first field where one was made; if it is still non-clean, record `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Checkpoint 4: the base-update checkpoint did not report a clean token after one re-invocation — observed line: <the observed line, verbatim>; helper breadcrumb: <the helper's own stderr breadcrumb, verbatim>; not requesting, publishing or completing"` — then emit the 👎 outcome reaction and stop.

The discriminator for "the helper did not report a token" is observable, not "no output at all": no line whose leading word is a member of the helper's documented token set appears in the invocation's combined output. That case takes the refusal arm above as an unrecognized field.

An invocation whose refusal the tier REPORTS is a distinct case, and it proceeds. The checkpoint never ran, so there is no token to grade — record it through the keyed-checkpoint carrier under its own key: `workpad.py update $ISSUE_NUMBER --checkpoint base-update-checkpoint-4-tier-refused "Checkpoint 4: the update-branch-checkpoint invocation was refused by this tier (<denial/rc 127>) — base reconciliation before the request is unverified this run; proceeding per the shared contract's degraded posture"`. A `--checkpoint` call that itself exits non-zero here fails this step closed. Then proceed to the pre-request passes and the request. It does **not** route to `Blocked`.

Pre-request passes and clean-tree push (the block's remaining committing steps). Run every pre-request pass the loaded consumer policy names, then commit any remainder they produced with the right prefix and push (a no-op on an already-clean tree) — so the request below covers a clean, pushed head.

Early verification request (the block's last step). When the loaded consumer policy establishes final-tree completion evidence through a verification it requests and then awaits, issue that request now for the pushed `HEAD` (after the committing block; a commit landing later takes §4.3's fresh-request arm), record `workpad.py update $ISSUE_NUMBER --note "Early verification request: head <sha>, handle <handle>"`, and continue to §4.0 while it runs — §4.3 awaits it. With no such policy, or on a refusal, request nothing: §4.3 establishes the evidence for the `HEAD` it reads either way.

### 4.0 File Follow-Up Issues for Deferred Work

Ask the durable acceptance-criterion predicate first, substituting the PR number as a decimal literal:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py deferred-presence $ISSUE_NUMBER <this-run's-PR-number>
```

Read the exit code and printed count line from the tool result, never a captured shell variable or the workpad body. Route on the exit code:

- exit 1 — `not-outstanding: <n>`. Continue to §4.0.5 without loading the filing procedure.
- exit 0 — `outstanding: <n>` plus `criterion:` lines. Read `<skill-dir>/references/deferred-filing.md` and follow its deferred-AC channel for exactly those criteria.
- exit 2, an unfamiliar status, or no count line — load the same deferred-AC channel and record the unestablished operand as a note. Unknown is never an empty deferred set.

Accept the reference only when its first and last lines are matching boundary markers naming its own path; page to the end before deciding. An incomplete or invalid load records `dropped-failed`, states that deferred criteria were not filed, and continues.

### 4.0.5 File Follow-Up Issues for Deferred Review Findings

Ask the deferred-review predicate as a direct helper call, substituting this run's PR number as a decimal literal:

```bash
.prflow/vendor/prflow/scripts/discover-deferral-manifests.py --presence-for-pr <this-run's-PR-number>
```

On any reading that says the vendored path did not *run* — `command not found`, `No such file`, `Permission denied`, rc 126 or rc 127 — re-invoke the same helper through the portable anchor:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/discover-deferral-manifests.py --presence-for-pr <this-run's-PR-number>
```

Read the exit code and printed state line from the tool result, never a captured shell variable. Route on the exit code:

- exit 0 — `present: <n>`. Read `<skill-dir>/references/deferred-filing.md`, follow its deferred-review channel, then continue to §4.0.6.
- exit 1 *and* the printed line is exactly `absent: 0` — do not read the reference; continue to §4.0.6. Both conditions are required: exit 1 is also a crashing interpreter's status.
- Every other outcome loads the same deferred-review channel, records the unestablished result as a note, then continues to §4.0.6. Unknown is never an empty manifest set.

Use §4.0's marker and paging contract. An incomplete or invalid load records `dropped-failed`, states that deferred review findings were not filed, and continues to §4.0.6.

### 4.0.6 Audit Deferred Reflections Are Backed

A `--reflection-kind deferred` reflection renders under "⚠️ Action required" and reads as handled, yet may be backed by no tracked deferral — filed nowhere. Audit each, as a single statement whose leading token is the granted vendored literal, substituting this run's PR number as a decimal literal:

```bash
.prflow/vendor/prflow/scripts/workpad.py deferred-reflection-audit $ISSUE_NUMBER <this-run's-PR-number>
```

On any reading that says the vendored path did not *run* (§4.0.5's list), re-invoke through the portable anchor:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py deferred-reflection-audit $ISSUE_NUMBER <this-run's-PR-number>
```

Read the exit code and printed line from the tool result, never a captured shell variable. Then route on the exit code:

- exit 0 — `backed: <n>`. Every deferred reflection is backed; write nothing and continue to §4.2.
- exit 1 — `unbacked: <n>`, followed by one `text:` line each. Record `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0.6: <n> deferred reflection(s) backed by no tracked deferral for this PR — filed nowhere: <the text(s)>"`, then continue to §4.2. Do not silently pass completion.
- exit 2 — `unestablished: reason=<token> unbound=<u> corrupted=<c>`, or no output. Record `workpad.py update $ISSUE_NUMBER --reflection-kind note --reflection "…"` quoting the reason token (or the no-output condition), then continue to §4.2. Never read an unestablished audit as "nothing unbacked".

### 4.2 Generate PR Description

Dispatch barrier. This dispatch is bound by the dispatch-collection requirement in this run's injected engine-ground-truth block — read it there; with no such block, collect it before the turn ends.

Spawn one general-purpose subagent (using the Agent tool) that both updates the PR description and reconciles its claims in the subagent's own context, not this orchestrator's. Compose its dispatch instruction to direct it to:

1. Invoke the `prflow:pr-description` skill with the issue number as its argument (`$ARGUMENTS`). The skill reconciles the existing PR's title and updates its body. After it returns, check for the placeholder — `gh pr view --json body --jq '.body' | grep -q "Work in progress — automated review pending"` — and report whether the body was updated from it (updated / still-placeholder / could-not-determine); a title or body write the skill reports failed, or a lookup it reports unestablished, is could-not-determine.
2. Reconcile the PR body's claims. Re-read the whole PR body and audit it against three claim classes — behavioral, verification, and artifact-existence — each with its own comparand and recorded outcome. The artifact — code, tests, and filed artifacts — is the fact, as in §2.3.4a. Binding all three classes: rewrite every figure the body copies from a value the source tree owns — a floor literal, a registry minimum, a constant — to name where the value lives instead of repeating its digits, even when accurate now (a later merge rots it). A number the tree does not own — a measured duration, a count of issues this run filed — keeps its digits.
   1. Behavioral claims — comparand: the actual shipped code path, followed into pre-existing code the diff calls. For every behavioral claim about what the shipped code does (including a `## Post-Merge Verification` item that actually describes *already-shipped* behavior rather than a live-only check), confirm the code does what the body says; a claim satisfied by pre-existing code the diff merely calls is true.
   2. **Verification claims** — compare claims with the cited test source (new or pre-existing) and recorded execution evidence. Run no test-suite runner or test file here; §4.3 owns completion verification. Audit Test Plan assertions and claims of coverage, mutation sensitivity or outcomes anywhere in the body. A coverage claim needs a check that establishes its stated scope; a result claim needs an attributable completed run applicable to the current candidate and environment. Check intervening edits before reusing an older result. Reading source alone establishes neither execution nor a passing result. Preserve accurately scoped existing coverage, direct checks, historical verification decisions and explicit limitations. Correct unsupported or stale claims, distinguishing planned checks from executed results; do not require a new test in the diff merely to substantiate existing coverage.
   3. **Artifact-existence claims** — comparand: the artifact's own resolvable identifier (an issue or PR number, or a repo-relative path). Audit every body assertion that a separate artifact exists or was created (a follow-up issue, filed deferral, linked issue/PR, cutover/growth artifact, docs page, changeset). A claim carrying no resolvable issue/PR number and no repo-relative path is false as written and is rewritten to state what actually exists. This class does not force a follow-up issue to be filed (Phase 4.0 owns filing): "Deferred to a follow-up: <items>" names no artifact and states an intention, so it passes; "A follow-up issue tracks the deferred half" names an artifact and needs the number.

   Resolution (shared across all three classes). A claim that fails its class is resolved by deleting it, fixing the code, or rewriting it — "note it and move on" is not an arm:

   - If the body overclaims (asserts something the diff, its tests, or the filed artifacts do not deliver), delete the claim or correct it to the truth via REST: write the corrected body to a file, resolve the PR number, and PATCH it with the `-F body=@<file>` form (reads the value literally, preserving backticks and `$`):
     ```bash
     gh pr view --json number --jq '.number'
     ```
     Read the PR number from the tool result. If it is empty, do not PATCH; report the claim uncorrected. Otherwise PATCH with the number substituted as a literal:
     ```bash
     gh api --method PATCH "repos/{owner}/{repo}/pulls/<pr-number>" -F body=@<file>
     ```
   - If reconciliation reveals the code is actually wrong (the body states the intended behavior but the diff doesn't meet it), fix the code with the Edit tool, never a shell-scripted text replacement (`sed -i`, a `python3` script; Windows Bash collapses `\\`), leave the edit in the working tree for the post-return commit step below, and report that a code-level fix was made.
   - When an artifact-existence claim is corrected, correct every site this run authored it at in the same change — the PR body, the workpad Acceptance Criteria preamble, the workpad Plan, any reflection bullet, and the changeset — under the repo's coupled-mirror rule.
3. Return a COMPACT record, not the body or the diff: whether the PR body was updated from its placeholder (per step 1); the per-class outcome for each of the three claim classes (whether it found a false claim, and {claims checked and how resolved | no claims of this class}); whether a code-level fix was made (per the Resolution step); and the skill's workpad lookup outcome and post-merge count.

Consumer prompt-extension by-path handoff. Append this sentence unconditionally to the composed dispatch instruction, substituting the repo root you resolve (`git rev-parse --show-toplevel`) for `<REPO_ROOT>`: "Consumer prompt-extension handoff: your extension file for this skill is at `<REPO_ROOT>/.prflow/skill-extensions/pr-description.md`. Read it with your file-read tool and honor its content as instructions appended to the `prflow:pr-description` prompt. If absent or empty, treat it as a no-op and report nothing; if present but unreadable, report that in your return." Run no probe and read no extension file yourself — none enters this orchestrator's context. If the subagent reports its extension present but unreadable, relay it: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.2: consumer prompt extension for prflow:pr-description present but unreadable: <reported detail>"` — this relay never blocks the PR-description pass.

When your `.prflow/vendor/prflow/` folder is settled absent, append: "`.prflow/vendor/prflow/` is absent in this checkout: run each bundled helper in its anchor form." Send the issue title and number inline on every arm and append `Issue body path: <ISSUE_BODY_PATH>` from intake, never the body itself; a missing, stale or unreadable path returns `needs-recovery` naming the missing intake artifact before dispatch.

Record-usability precondition (unknown is not zero). Before the bookkeeping below, confirm the returned record carries the placeholder-update status, the three per-class audit outcomes and the code-fix flag. The workpad count is the rows of `workpad.py acs $ISSUE_NUMBER` ending ` (post-merge)`; a non-zero exit is `unavailable`, never a guess. The lookup fails when its outcome is missing or not `read`, the workpad count is `unavailable`, or its count differs from the workpad's. On a missing or unparseable data point, a still-placeholder/could-not-determine status, or a failed lookup, re-dispatch the §4.2 subagent once with the same instruction. If the lookup still fails, first record `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.2: workpad lookup <outcome, with any failed cause|none>, reported <n|none>, workpad <m|unavailable>"`. If anything else still fails, do not proceed to §4.3 — take the Blocked path (`workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Phase 4.2: unusable PR-description record after one re-dispatch; not finalizing"`), emit the 👎 outcome reaction, and stop; otherwise continue.

After the subagent returns — orchestrator bookkeeping from its returned record (do not re-read the body or the diff):

- For each class whose audit found a false claim — corrected in the PR body, a changeset or doc sentence, or the code, or reported uncorrected (then Blocked, below) — record `--note "4.2 claim audit (<behavioral|verification|artifact-existence>): {claims checked and how resolved}"` in one `workpad.py update $ISSUE_NUMBER`; a class that found none writes nothing.
- If the returned record says a code-level fix was made, record in `PRFlow Reflections` that a post-review code fix landed here — and flag it more loudly on the draft path, where no automatic re-review will catch it.

Never finalize a PR whose subagent-returned record asserts a behavior the diff does not deliver, a coverage the diff's tests do not contain, or an artifact that does not exist: for a class the subagent could not resolve, once its note is recorded, take the Blocked path (`workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Phase 4.2: <class> claim unresolved; not finalizing"`), emit the 👎 outcome reaction, and stop.

Commit the subagent's working-tree edits before §4.3 — its `fix:` code edit and any body-file scratch land in this orchestrator's own checkout. Inspect unfiltered `git status --short` after the subagent returns; if it shows changes the subagent made, stage the literal paths explicitly (do not `git add -A`/`.` and do not stage unrelated code or pre-existing dirty paths), then commit and push with a `fix:` prefix (a body-only correction rides in the same commit):
```bash
git status --short
git add "<literal-path-1>" "<literal-path-2>" # every path the §4.2 subagent changed; omit unrelated/pre-existing dirty paths
git commit -m "fix: reconcile PR description claims for issue #$ARGUMENTS"
git push
```
When unfiltered status confirms the subagent produced no working-tree change, this is a no-op.

### 4.3 Finalize the PR (publish or leave draft) and Finalize Workpad

On `NOT_IGNORED`, after the PR-description child has completed, remove the dispatched intake-owned `ISSUE_BODY_PATH` only when its resolved parent is the validated flat scratch home and its basename is exactly `intake-issue-body-$ISSUE_NUMBER.md`; never glob or infer a different file. Leaving it untracked prevents the clean-tree gate.

Clean-tree backstop (always, before the publish decision). Assert nothing uncommitted survives the run:

```bash
git status --porcelain
```

If it is non-empty, do not finalize yet. Commit the part that belongs to this PR with the right prefix (`feat:`/`fix:`/`docs:`/`chore:`) and push, and record which phase under-committed via `--reflection-kind note --reflection "…"`. A newly discovered implementation-code change is **not** that part — report it, not commit it (Finalization boundary above). Surface (do not blindly `git add`) any unexpected untracked file. When the tree is already clean this is a no-op — create no empty commit.

Run-transient files are the exception — delete, never commit. A leftover reflection-payload file under `.prflow/tmp/` is run-transient scratch, not a deliverable (a plugin-only adopter has no `.prflow/.gitignore` scaffold, so a blind `git add` would commit it into the PR).

**Route on the block's head — before the wait.** Read a fresh `git rev-parse HEAD` and compare it with the head the committing block pushed — the *Early verification request* note's head when a request was issued.

- Equal — invoke neither the base-update helper nor any pre-request pass. With a request, re-issue it with fresh operands (it prints `REUSE`) and await it in *Establish final-tree completion evidence* below; with none (a consumer with no request-and-await policy, or a refused request), establish the evidence for this HEAD there as today.
- Any other head, or a note head that cannot be read (a commit landed after the block — a raised floor or a §4.2 code fix) — run the §4.1 committing block here (its single base-update invocation, the pre-request passes, the clean-tree push), then request and await below. A verdict still in flight for the superseded head is never collected for this new head.

Establish final-tree completion evidence — after the routing above, before the publish decision. Phase 4 mutated the candidate, so `scripts/workpad.py` gates the `--status Complete` write on a current, passing flight for the final in-env verification command. Run it as the run's single whole-suite obligation at the scope a prompt extension sets, or the full whole-suite command when none is set; parallelize it only as that command does — never relaxing a conflict resolution's suite run staying serialized before its commit. The single-flight consult obligation this flight discharges is scoped to any suite execution — whole-suite, shard, or focused, not only a full-suite relaunch — and reuse draws on the retained log whichever runner named it, so a clean handled result is re-read rather than re-executed.

1. Launch one verification flight for the final tree via the fence below, running the allowlisted verification command unchanged as its own leading token between `mark-running` and `finish`. Author the `claim` declaration and `finish --summary-file` with the Write tool under `<run-scratch>/` (no redirect/heredoc); each operand (`<key>`, `<tok>`, paths) is an agent-level literal, not a shell capture. Set `candidate_identity` from `reception-record.py`'s stdout (null fails the gate). `checkout-fingerprint.py`'s JSON is the `checkout` field, and a freshly-produced one is each `status`/`wait` re-anchor's `--current-checkout-file`. The summary needs a nonempty `command`, and its `skipped_checks` lists every skip the suite's output reports, pre-existing ones included. For subcommand behavior read the module header and `--help`: `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/verification-flight.py`.

```bash
.prflow/vendor/prflow/scripts/checkout-fingerprint.py
.prflow/vendor/prflow/scripts/verification-flight.py claim --input-file <run-scratch>/c.json
.prflow/vendor/prflow/scripts/verification-flight.py mark-running --flight <key> --token <tok>
.prflow/vendor/prflow/scripts/verification-flight.py finish --flight <key> --token <tok> --result passed --summary-file <run-scratch>/s.json
.prflow/vendor/prflow/scripts/verification-flight.py status --flight <key> --current-checkout-file <run-scratch>/f.json
```

On any reading a vendored path did not run (§4.0.5's list), re-invoke through the anchor; every other vendored line takes the same `.prflow/vendor/prflow/` prefix removal:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/checkout-fingerprint.py
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/verification-flight.py
```

Author the declaration from the worked example `verification-flight.py claim --help` prints, substituting its `<…>` placeholders and replacing the example hex from `checkout-fingerprint.py`. `schema_version` stays `1`; `external_services` stays `"none"` (or the live service, recorded non-reusable).
2. Record the validated flight key on the workpad: `workpad.py update $ISSUE_NUMBER --record-completion-evidence <flight-key>` (the `<flight-key>` is the `flight_key` value `claim`/`finish` printed). This validates the record under the implement-completion policy and, only on a pass, writes the hidden `completion-verification:<flight-key>` marker (replacing any prior one). A non-pass record aborts this call before any PATCH — do not proceed to Complete; take the Blocked path below.
3. On a non-pass or unrunnable suite → Blocked, never Complete. A failed suite, a non-empty skip population, or a verification command that is not locally re-runnable on this tier means there is no in-env pass. When the suite ran and reported failures on this candidate and the loaded prompt extension routes a failed verification back to the fix path, the failure is not yet terminal: write no status and no reaction, and return `needs-repair` with the failure detail as `reason` and the failed candidate SHA — the parent decides. Otherwise: `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Phase 4.3: final-tree verification did not establish a clean in-env pass (<token/cause>) — cannot record completion evidence; not publishing/completing"`, emit the 👎 reaction, and stop. This step is the sole owner of the unrunnable-verification case: a tier-refused verification routes to Blocked here rather than publishing-and-completing.

An execution ceiling is not a verdict: a completion command the tier's per-command execution ceiling *terminated* observed no verdict — no failure and no skip population — so the run takes the decomposition a prompt extension declares, and with none declared records `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Phase 4.3: execution-ceiling — the whole-suite verification could not be OBSERVED inside this tier's per-command ceiling (<command>); a runner limit, not a verdict on the change"`, emits the 👎 reaction, and stops.

With `.verification_flight.enabled` set to `false` the claim/mark-running/finish sequence still runs — `false` suppresses only flight *reuse*, never the machine record completion requires.

Review-coverage precondition — before the publish decision. When the parent passed `REVIEW_WAIVER_SOURCE`, skip this precondition: return `review_coverage` as `{"waived_by": "<REVIEW_WAIVER_SOURCE>"}`, write no coverage record or disposition, and continue to the tip-landed gate. Without it, read the review-coverage record §3.3 stamped on the workpad (`## Progress`, `<!-- prflow:checkpoint review-coverage:… -->`). If it is complete — either a measured clean pass (`coverage=full`, `dispatch=attempted`, `roster=complete`, `checklist=complete` or `skipped-intentional`) or the no-shadow-owed record §3.3 stamps on a `REJECT` that runs no bounded re-review and on the soft-proceed and `CLEAN-SHADOW-SKIPPED` arms (`not-applicable` on all four axes; a mixture of `not-applicable` and measured values is refused as `[review-coverage-unestablished]`) — proceed unchanged. If it records a gap and this run holds for each gap a true reason that names that specific gap and is at least 20 characters — over a record reading `dispatch=attempted`, record one `{gap, cause_class, reason}` disposition per gap (`shadow-coverage`, `roster`, `checklist`) in your `review_coverage` result field, which the parent carries to its finalize `--review-coverage-disposition` call. The `<cause-class>` is the closed set `environment-denial` (a capability the runner did not expose — admissible only with a recorded `missing` roster row corroborating it) | `dispatched-but-lost` (a dispatched reviewer whose result was lost, or a shadow run inline after a refused, dead or malformed engine dispatch); there is no elective member, so a budget belief or a partial pass judged adequate has no admissible class and takes the Otherwise arm. Otherwise — an absent, duplicated, malformed, or `dispatch`≠`attempted` record, a gap with no true, specific reason statable at that length, or a gap whose only available cause is elective/inadmissible — stop and return a blocked result so the parent does not publish or flip `Status` to `Complete`: record `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Phase 4.3: review coverage is incomplete or unestablished (<the observed record, verbatim>) and gap(s) <gaps> carry no statable disposition — not publishing and not completing"`, emit the 👎 outcome reaction, and stop.

Tip-landed gate (before the publish decision — guards `gh pr ready` and the `Complete` flip alike). The clean-tree backstop reports a committed-but-unpushed tip as clean, so confirm the tip is on the remote (`git rev-parse HEAD` == `git rev-parse @{u}`), classifying `HEAD` in order:

- Detached HEAD (`git rev-parse --abbrev-ref HEAD` prints `HEAD`) or no upstream (`git rev-parse @{u}` exits non-zero on a real branch): neither is *by itself* an unpushed tip, so never `Blocked` on the classification alone; with no `@{u}` comparand, confirm the remote holds `HEAD` with `git branch -r --contains HEAD` (local remote-tracking refs): non-empty → record a `--note` naming the state and proceed; empty → the remote lacks `HEAD`, so take the unpushed handling below (push and re-verify, else Blocked).
- Measurement unestablished — a needed `git rev-parse` is refused or prints nothing (the local-tier classifier can refuse it): no positive check can run, so record a `--note` naming it and proceed under the degraded posture, never onto an unpushed-tip `Blocked`.
- `@{u}` equals `HEAD` (landed): proceed to the publish decision.
- `@{u}` differs (unpushed): `git push`, then re-read both. Equal now → note it and proceed; still unequal (push rejected, or an `Everything up-to-date` push left them apart) → read `git rev-parse HEAD` if this route has not (refused or empty, this arm still applies, with `unknown` as the SHA), then stop and return a blocked result so the parent does not publish or flip `Status` to `Complete`: `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Tip-landed gate: local branch tip {that HEAD SHA} is not on the remote and a push did not land it — refusing to publish or complete a run whose body would cite a commit the remote lacks; land it and re-run"`, emit the 👎 outcome reaction (see *Outcome reaction* in the Workpad Reference) and stop.

<!-- prflow:implement-finalization-ref file=skills/implement/references/phase-4-finalization.md end -->
