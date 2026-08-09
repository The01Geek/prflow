## Phase 4: Documentation

Output: `Phase 4/4: Documentation — updating docs and finalizing PR...`

**Writing standard.** Before composing this phase's first `--reflection` bullet, read the shared writing standard `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/writing-standard.md` and follow it. A failed load emits a breadcrumb naming the file and the failure kind, and you compose the reflection without it.

`workpad.py update $ISSUE_NUMBER --status Documenting`.

### 4.0 File Follow-Up Issues for Deferred Work

The Phase 4.0 procedure lives in `<skill-dir>/references/deferred-ac-followups.md` and is **read only when a durable predicate says work is outstanding**. Ask it first, as a single statement whose leading token is the helper path, substituting the PR number as a decimal literal — a shell variable a later statement reads arrives **empty** on the cloud tier, which the helper's integer-typed PR argument turns into a usage error that loads the reference every run with nothing red. `$ISSUE_NUMBER` is substituted per your standing substitution rule:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py deferred-presence $ISSUE_NUMBER <this-run's-PR-number>
```

Read the **exit code and printed count line from the tool result**, never a captured shell variable. Do **not** read the workpad body to decide this. Route on the exit code:

- **exit 1 — `not-outstanding: <n>`.** Do **not** read the reference; continue to §4.0.5.
- **exit 0 — `outstanding: <n>`, followed by one `criterion:` line each.** `Read` `<skill-dir>/references/deferred-ac-followups.md` — via the same `<skill-dir>` anchor this file's entry-gate uses — and follow it for **exactly** the projected criteria.
- **exit 2 — `unestablished: reason=<token> unbound=<u> corrupted=<c>`, or no count line at all.** Read the reference **anyway**, and record `workpad.py update $ISSUE_NUMBER --reflection-kind note --reflection "…"` naming **which operand** could not be established, quoting the reason token and both counts. The count line may be followed by `filed:` lines; the reference files only for criteria those lines do not name. An unavailable operand is **never** read as "nothing was deferred": that reading silently strands deferred work, while a needless load costs one read.

**Marker contract.** Accept the load only when the file's **first line is its `start` boundary marker and its last line the matching `end` marker**, each naming that file's own path.

**Degraded arm — degrade, never halt.** When the predicate holds and the reference read fails — absent, empty, harness-refused, or mismatched boundary markers — record `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "…"` naming the reference path `skills/implement/references/deferred-ac-followups.md` and stating the deferred criteria were **not** filed, then **continue to §4.0.5 without halting Phase 4**. `dropped-failed` is reserved for this arm; the unestablished arm uses `note`.

### 4.0.5 File Follow-Up Issues for Deferred Review Findings

The Phase 4.0.5 procedure lives in `<skill-dir>/references/deferred-review-findings.md` and is **read only when a durable predicate says a deferred review finding is present**. Ask it first, as a single statement whose leading token is the granted vendored literal, substituting this run's PR number as a decimal literal — a shell variable a later statement reads arrives **empty** on the cloud tier, and the helper's digit-typed argument turns that into a usage error that loads the reference every run with nothing red:

```bash
.prflow/vendor/prflow/scripts/discover-deferral-manifests.py --presence-for-pr <this-run's-PR-number>
```

On any reading that says the vendored path did not *run* — `command not found`, `No such file`, `Permission denied`, rc 126 or rc 127 — re-invoke the same helper through the portable anchor, which is why the vendored spelling is an arm rather than a replacement. A consumer whose vendor step dropped the executable bit reports `Permission denied` rather than `command not found`, so a trigger naming only the not-found reading would leave that consumer with no second arm:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/discover-deferral-manifests.py --presence-for-pr <this-run's-PR-number>
```

Read the **exit code and printed state line from the tool result**, never a captured shell variable. Route on the exit code:

- **exit 0 — `present: <n>`.** `Read` `<skill-dir>/references/deferred-review-findings.md` — via the same `<skill-dir>` anchor this file's entry-gate uses — and follow it.
- **exit 1 *and* the printed line is exactly `absent: 0`.** Do **not** read the reference; continue to §4.1. Both conditions are required: 1 is also the status a crashing interpreter returns, so an exit 1 carrying no `absent: 0` line is the arm below, not this one.
- **Every other outcome** — exit 2 with `unestablished: reason=<token>` (optionally a `root:` line), exit 1 without that `absent: 0` line, any other exit code, or no output at all. Read the reference **anyway**, and record `workpad.py update $ISSUE_NUMBER --reflection-kind note --reflection "…"` naming what you observed: the reason token when one was reported, the exit code when it was outside the contract, or the no-output condition itself — the shape a harness refusal takes — rather than a token you did not receive. An unavailable operand is **never** read as "nothing was deferred": that reading silently strands acknowledged findings, while a needless load costs one read. This arm is the residual, so an outcome nobody enumerated lands here rather than on the skip.

**Marker contract.** Accept the load only when the file's **first line is its `start` boundary marker and its last line the matching `end` marker**, each naming that file's own path.

**Degraded arm — degrade, never halt.** When the predicate holds and the reference read fails — absent, empty, harness-refused, or mismatched boundary markers — record `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "…"` naming the reference path `skills/implement/references/deferred-review-findings.md` and stating that deferred review findings were **not** filed, then **continue to §4.1 without halting Phase 4**. `dropped-failed` is reserved for this arm; the unestablished arm uses `note`.

### 4.1 Update Documentation

**The routine doc pass always runs — narrative never suppresses it.** A narrative claim that documentation is unnecessary — including an **absent, empty, or contradictory** `**Documentation Needed**` bullet — **never** suppresses the routine documentation pass: the documentation subagent that invokes the `prflow:docs` skill still runs and updates the documentation the shipped behavior change warrants. The `**Documentation Needed**` bullet is an **additive floor** of mandatory deliverables (it can only *add* required files), **never a ceiling that authorizes skipping otherwise-warranted documentation** (the §2.1 authority hierarchy). The deterministic two-stage gate below enforces the floor (every named deliverable must ship); it does not decide whether the doc pass runs.

**Stage 1 — Pre-flight briefing (before dispatch).** Extract the issue's required documentation deliverables **deterministically — do not interpret the prose yourself.** Run the bundled helper, which scopes to the `**Documentation Needed**` bullet under `## Implementation Notes` and emits the recognizable file paths one per line:

```bash
# Read the issue body to a FIXED temp FILE (statement 1), then extract from that file
# (statement 2). The intermediary is a file PATH on disk, not a variable or shell option, so no
# marshaled cross-statement state has to survive on an inline-bash runner that strips it (Copilot
# CLI / Cursor / Codex CLI / Gemini CLI). Each statement's `if ! A && ! B` reads its OWN command's
# exit status inline (gh's, then the extractor's); a command failure never reads as a no-op — read
# AND retry both failing → fail CLOSED to Blocked. An rc-0 EMPTY extraction legitimately leaves
# DOC_NEEDED_PATHS empty for the no-op below.
# Ensure the scratch leaf exists (rc-checked, never `|| true`) and drop any stale capture.
if ! mkdir -p .prflow/tmp; then
  echo "devflow: could not create .prflow/tmp for the Documentation Needed gate" >&2
fi
rm -f .prflow/tmp/devflow-docgate-body-$ISSUE_NUMBER.txt .prflow/tmp/devflow-docgate-gh.err
if ! gh issue view $ISSUE_NUMBER --json body --jq '.body' > .prflow/tmp/devflow-docgate-body-$ISSUE_NUMBER.txt 2>.prflow/tmp/devflow-docgate-gh.err \
   && ! gh issue view $ISSUE_NUMBER --json body --jq '.body' > .prflow/tmp/devflow-docgate-body-$ISSUE_NUMBER.txt 2>.prflow/tmp/devflow-docgate-gh.err; then
  "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind dropped-failed --reflection "Phase 4.1: could not read the issue body to extract Documentation Needed deliverables (gh command failure); the deliverable cross-check could not run — retry when GitHub is reachable"
  # then emit the 👎 outcome reaction (see the Workpad Reference) and STOP the run.
fi
if ! DOC_NEEDED_PATHS=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/extract-doc-needed-paths.sh < .prflow/tmp/devflow-docgate-body-$ISSUE_NUMBER.txt) \
   && ! DOC_NEEDED_PATHS=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/extract-doc-needed-paths.sh < .prflow/tmp/devflow-docgate-body-$ISSUE_NUMBER.txt); then
  "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind dropped-failed --reflection "Phase 4.1: the Documentation Needed extractor failed (token scan error); the deliverable cross-check could not run — retry"
  # then emit the 👎 outcome reaction and STOP the run.
fi
```

**Each `if ! A && ! B` guard discriminates a command failure by that command's own exit status, never stdout emptiness.** A gh failure (auth, network, rate-limit, wrong issue number) fails statement 1's guard; an extractor failure fails statement 2's — either is a *command failure* that says nothing about which paths the issue names, so **never treat its empty stdout as a no-op** the way an empty `DOC_NEEDED_PATHS` is treated below (the fail-open this gate exists to close). Each statement's retry is folded into its guard, so the fail-closed branch fires only when the read *and* its retry both fail, then routes to the Blocked path, emits the 👎 outcome reaction, and stops. Only an rc-0 read with empty `DOC_NEEDED_PATHS` is the legitimate empty signal handled below.

**Span-suppression breadcrumb disclosure (once per run).** The extractor suppresses command/grant literals inside the Documentation Needed block (a `` `bash <test command>` `` command span, a `` `Bash(x.sh:*)` `` grant, an un-backticked `Word(...)` call group) so they never become phantom deliverables, emitting a one-time `suppressed a span` breadcrumb on **stderr**. This gate does **not** capture that stderr (no implement-probe row proves a stderr-capture shape on this tier), so on the cloud tier the breadcrumb is ephemeral. Record the residual once by Stage 1 so it is disclosed: `workpad.py update $ISSUE_NUMBER --note "Phase 4.1: extractor span-suppression breadcrumbs are not durably observable on the cloud tier (stderr not captured); a suppressed command/grant literal in the Documentation Needed block leaves no run-record trace"`. This is a plain note, not a reflection — it discloses an accepted residual, not a per-run failure.

These paths are the required deliverables. Stage 2 re-runs the **same helper** rather than re-deriving them, so the two passes can never disagree about which files were named. If `DOC_NEEDED_PATHS` is empty (the section is absent, names no file paths, or holds only non-path prose), Stage 1 is a no-op and the subagent is dispatched with its normal instruction unchanged. If the helper emits nothing **but** the issue body still contains a Documentation Needed section **in either accepted form** — the bold-bullet `**Documentation Needed**` form **or** a `### Documentation Needed` heading (`gh issue view $ISSUE_NUMBER --json body --jq '.body' | grep -qE '\*\*Documentation Needed\*\*|^###[[:space:]]+\*{0,2}Documentation Needed'` — the heading alternative carries the same `\*{0,2}` bold-tolerance as the extractor's own opener so the two heading recognizers cannot drift) — record a workpad note (`workpad.py update $ISSUE_NUMBER --note "Phase 4.1: Documentation Needed section present but the extractor found no file paths; the deliverable cross-check is skipped this run"`) so the skipped enforcement is auditable for either form — matching only the bold-bullet form here would leave a heading-form issue's empty extraction silently unrecorded.

**Dispatch barrier.** Every subagent dispatch described here is bound by the barrier statement in the engine root's *Cloud headless-wait discipline* block (`skills/implement/SKILL.md`) — read the requirement there.

Spawn a **subagent** (using the Agent tool) and instruct it to invoke the `prflow:docs` skill. Compose the dispatch instruction: begin with "Invoke the `prflow:docs` skill to update all documentation (internal docs, external docs, release notes). The issue context is provided for release notes generation." If `DOC_NEEDED_PATHS` is non-empty, append: " The issue requires the following files to be updated; treat each as a mandatory deliverable: `<path1>`, `<path2>`, …" Send this composed instruction along with the issue title and number inline (the prflow:docs dispatch, on every arm). **Hand the issue body off by path, not paste:** when the §1.1 cache was written, add an `Issue body path: .prflow/tmp/issue-body/issue-<ISSUE_NUMBER>.md` line instructing that subagent to Read that file directly, and do **not** paste the body into the prompt. **Only** ship this line when the §1.1 write landed — on the degraded arm where no cache was written, **paste the issue body inline** instead. (The Documentation-Needed gate fences above read the body live, because a human can amend the deliverable list mid-run.)

**Consumer prompt-extension by-path handoff.** A subagent receives neither `$CLAUDE_SKILL_DIR` nor a `Base directory for this skill:` context line, so the `prflow:docs` child cannot resolve its own anchor to reach its consumer prompt extension. So **append this sentence unconditionally** to the composed dispatch instruction, substituting the repository root you resolve (`git rev-parse --show-toplevel`) for `<REPO_ROOT>` so the child receives a working-directory-independent absolute path: "Consumer prompt-extension handoff: your extension file for this skill is at the absolute path `<REPO_ROOT>/.prflow/prompt-extensions/docs.md`. Read it with your file-read tool and honor any content as instructions appended to the `prflow:docs` skill's own prompt. If the file is absent or empty, treat it as a no-op and report nothing about it; if it is present but you cannot read it, report that in your return so the orchestrator can relay it." Run **no** probe and read **no** extension file yourself — no extension content enters this orchestrator's context on any path. **If the docs subagent's return reports its extension was present but unreadable, relay it** — add a `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.1: consumer prompt extension for prflow:docs present but unreadable: <reported detail>"` bullet naming the child skill — this relay never blocks the docs pass.

Commit each documentation artifact changed by the completed subagent. Read configured paths from `.prflow/config.json` — `config-get.sh` **prints** each value; read all four results and substitute non-empty values as literals below. (A `VAR=$(…)` capture does not survive across Bash tool calls on the cloud runner — values expand empty in the later call and `git add ""` fails.)

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.internal docs/internal/
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.external docs/external/
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.release_notes_file ""
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.changelog_file ""
```

Each invocation is a separate observed tool call. For the required internal and external roots, success is rc 0 plus exactly one non-empty printed path. For the optional release-notes and changelog files, rc 0 with empty output means that artifact is disabled; any non-empty output must be exactly one path. A matcher refusal, non-zero exit, multi-line/non-path output, or empty required path is **not** "no documentation changes": retry that read once, then mark the workpad `Blocked` with a `dropped-failed` reflection naming the config key, emit the outcome reaction, and stop. Accept only repo-relative paths that do not begin with `-`.

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

Then decide whether the docs pass succeeded: it succeeded if the docs subagent actually ran — either it produced changes (committed above) or it returned cleanly with no changes needed. If instead the docs subagent failed, returned no useful output, or was unable to run, that is actionable: add a `--reflection-kind dropped-failed --reflection "…"` bullet to the workpad and do **not** apply the post-docs labels at all (now or later). The post-docs labels signal "the docs pass ran and was reviewed", but application is **deferred to the end of Stage 2** so a PR that routes to Blocked for an undelivered deliverable never carries them (the label resolution is shown there).

**Stage 2 — Post-hoc diff gate (mandatory when Stage 1 found named paths).** After the docs-subagent commit and before ticking `Documentation`, verify that every required-deliverable path has been touched. Re-run the **same deterministic helper** as Stage 1 — re-running the helper is the single source of truth; do not rely on remembered Stage 1 output:

```bash
# Same fixed-temp-FILE two-statement guard as Stage 1: gh writes the body to a literal disk path
# (statement 1), the extractor reads that file (statement 2). The intermediary is a file PATH, so
# no marshaled cross-statement state has to survive on a stripping inline-bash runner. Each
# statement's `if ! A && ! B` reads its OWN command's exit status inline; read AND retry both
# failing → fail CLOSED to Blocked; an rc-0 EMPTY extraction stays the genuine no-op signal.
# Ensure the scratch leaf exists (rc-checked, never `|| true`) and drop any stale capture.
if ! mkdir -p .prflow/tmp; then
  echo "devflow: could not create .prflow/tmp for the Documentation Needed gate" >&2
fi
rm -f .prflow/tmp/devflow-docgate-body-$ISSUE_NUMBER.txt .prflow/tmp/devflow-docgate-gh.err
if ! gh issue view $ISSUE_NUMBER --json body --jq '.body' > .prflow/tmp/devflow-docgate-body-$ISSUE_NUMBER.txt 2>.prflow/tmp/devflow-docgate-gh.err \
   && ! gh issue view $ISSUE_NUMBER --json body --jq '.body' > .prflow/tmp/devflow-docgate-body-$ISSUE_NUMBER.txt 2>.prflow/tmp/devflow-docgate-gh.err; then
  "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind dropped-failed --reflection "Phase 4.1: could not read the issue body to extract Documentation Needed deliverables (gh command failure); the deliverable cross-check could not run — retry when GitHub is reachable"
  # then emit the 👎 outcome reaction and STOP the run.
fi
if ! DOC_NEEDED_PATHS=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/extract-doc-needed-paths.sh < .prflow/tmp/devflow-docgate-body-$ISSUE_NUMBER.txt) \
   && ! DOC_NEEDED_PATHS=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/extract-doc-needed-paths.sh < .prflow/tmp/devflow-docgate-body-$ISSUE_NUMBER.txt); then
  "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind dropped-failed --reflection "Phase 4.1: the Documentation Needed extractor failed (token scan error); the deliverable cross-check could not run — retry"
  # then emit the 👎 outcome reaction and STOP the run.
fi
```

**Each `if ! A && ! B` guard discriminates a command failure by that command's own exit status, never stdout emptiness** — symmetric to the diff side below. A gh failure (auth, network, rate-limit, wrong issue number) fails statement 1's guard; an extractor failure fails statement 2's — either is a *command failure* that says nothing about which paths the issue names, so **never treat its empty stdout as a no-op** (the step-1 escape hatch below), which would wave the gate through exactly when the deliverable list could not be read. Each statement's retry is folded into its guard, so the fail-closed branch fires only when the read *and* its retry both fail, then routes to the Blocked path, emits the 👎 outcome reaction, and stops. Only an rc-0 read with empty `DOC_NEEDED_PATHS` is the legitimate empty signal step 1 treats as a no-op.

1. **No-op when empty.** If `DOC_NEEDED_PATHS` is empty, this cross-check is a no-op — proceed directly to the post-docs-labels + `--tick-progress "Documentation"` step below.

2. **Compute the diff once; fail closed on a broken command.** Verify `$BASE` is non-empty; if empty, re-derive it exactly as Phase 1.4 does, **applying its non-empty fallback and not just the config read** — the read alone returns nothing on malformed config and would otherwise leave `$BASE` empty, collapsing the range to `origin/...HEAD` and judging every path absent. Compute the cumulative diff, guarding git's exit status **inline** (never a captured rc read in a later statement, which a cross-statement-variable-stripping inline-bash runner would leave empty):
   ```bash
   # Single-statement `if ! A && { re-fetch; ! B; }`: the failure branch fires off git's OWN
   # exit status read inline. The retry re-fetches the base branch (as Phase 1.4 does)
   # between attempts; read AND retry both failing → fail CLOSED to Blocked. An rc-0 result
   # with EMPTY stdout is NOT a failure — the `if !` leaves DIFF_OUT set and the per-path
   # check below reads it as the genuine "touched none of these files" signal.
   if ! DIFF_OUT=$(git diff --name-only "origin/$BASE...HEAD") \
      && { git fetch origin "$BASE" >/dev/null 2>&1; ! DIFF_OUT=$(git diff --name-only "origin/$BASE...HEAD"); }; then
     "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind dropped-failed --reflection "Phase 4.1: could not compute the cumulative diff for the Documentation Needed gate (git diff / base-fetch failed — offline, auth, or wrong trunk); never falling through to a path-absent verdict on a broken command"
     # then emit the 👎 outcome reaction and STOP the run.
   fi
   ```
   The `if !`-guard discriminates the failure by git's own exit status, **never** stdout emptiness. A `git diff` failure (or `origin/$BASE` not present locally) says nothing about any path: it re-fetches the base branch as Phase 1.4 does and retries once, and if the retry also fails it routes to the Blocked path and stops — **never fall through to a path-absent verdict on a broken command.** Conversely, **an rc-0 result with empty stdout is NOT a failure** — it is the legitimate signal that the diff touched none of these files; treat it as real and continue to the per-path check. For each path in `DOC_NEEDED_PATHS`, decide satisfied vs absent against `DIFF_OUT`: if it is a bare filename (contains no `/`), any diff entry whose basename matches it counts as satisfied (e.g. the diff entry `docs/architecture.md` satisfies the named path `architecture.md`); if it contains a `/`, it must appear as an exact match in `DIFF_OUT`.

3. **Self-heal or block for each absent path.** For each named path absent from the diff, perform the missing update when you can: if the correct update can be derived from the issue body's `**Documentation Needed**` prose, perform the missing update yourself, record a workpad note (`workpad.py update $ISSUE_NUMBER --note "Phase 4.1 self-heal: <path> absent from diff; performed update from Documentation Needed prose"`), commit (`docs:` prefix), and push. **Then re-verify the self-heal landed and reached the remote:** confirm the commit and push both succeeded *and* that the local branch is in sync with its upstream — `git rev-parse HEAD` must equal `git rev-parse @{u}` (a no-op `Everything up-to-date` push or a rejected non-fast-forward leaves them unequal, so a re-diff of the still-local commit would falsely satisfy the gate) — then re-run the helper-driven diff check for that path. A non-zero rc on commit/push, an upstream that does not match HEAD, or the path still absent from the re-checked diff all mean the self-heal did not land. Only a path now present in the re-checked diff **and** whose commit and push both reached the remote counts as satisfied. If the correct update cannot be derived from context (the prose is insufficient), **or** the self-heal did not land per the re-check, do not tick `Documentation` — route to the Blocked path: `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Phase 4.1: Documentation Needed file content cannot be determined for <path> — the docs subagent did not update this file and the correct content cannot be derived from the issue body; update manually and re-run Phase 4.1"`, then emit the 👎 outcome reaction (see *Outcome reaction* in the Workpad Reference) and stop.

Once every named path is satisfied (or Stage 1 found no paths), apply the deferred post-docs labels — only when the docs pass succeeded per the Stage-1 decision above; a run that routed to Blocked never reaches this point, so a Blocked PR never carries them. `docs.labels` is a comma-separated list (default `Documented`); normalize it (split on commas, trim each entry, drop empties) and apply through the shared REST label-apply helper (a PR is an issue, so `POST .../issues/{n}/labels` serves it — repo-scope only, unlike `gh pr edit --add-label`'s org-scoped GraphQL resolution). The REST path needs the PR number explicitly, so resolve it first from the current branch:

**Cloud-emission discipline (label helpers): iterate at the agent level, never in a shell loop or a capture — identical to Phase 4.0/4.0.5, see the *Cloud command-shape discipline* section in `skills/implement/SKILL.md`.** The `apply-labels.sh` call must be a **single leading-token statement**, not nested inside an `if` compound (a shape **no probe row measured** — see that section's *Unproven* bullet), and the config read must fail **closed** on no output rather than reading a possible denial as "no labels configured". First resolve and **print** the values (a shell variable does not survive into a later separate command on the cloud runner, so the per-call values must reach you through a tool result):

```bash
# GRANTED heads only — `paste` is granted in NO allowlist, so a `| paste -sd, -` tail makes
# the whole pipeline refused and the capture silently empty (the same trap Phase 4.0 notes).
if ! DOCS_LABELS=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.labels Documented); then
  DOCS_LABELS=""
  "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.1 could not read docs.labels (config-get rc≠0 — corrupt config.json or python3 missing); the PR carries none of the configured docs labels."
fi
CLEAN_LABELS=$(echo "$DOCS_LABELS" | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' | grep -v '^$' | tr '\n' ',' | sed 's/,$//')
DOCS_PR_NUM=$(gh pr view --json number --jq '.number')
# Print all three: an emptied normalizer must not be indistinguishable from an empty config
# (CLAUDE.md guard-class 2), and the PR number is needed as a literal in the apply call below.
echo "docs.labels raw: [$DOCS_LABELS]"
echo "docs labels to apply: [$CLEAN_LABELS]"
echo "docs PR number: [$DOCS_PR_NUM]"
```

Four exits before any label is applied — the same fail-closed set the deferral channels carry:

- **No lines printed at all.** The command was refused, not answered. Do **not** read it as "no labels": record it and apply nothing — `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.1 could not resolve docs.labels — the config-get command produced no output at all (likely a harness denial, not an empty config); the PR carries none of the configured docs labels."`
- **`raw` non-empty but `to apply` empty.** A broken normalizer (a missing/denied `tr`/`sed`/`grep`), not an empty config: record it and apply nothing — `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.1 resolved docs.labels to a non-empty value but the normalizer produced an empty list (a missing/denied tr|sed|grep in the pipeline); the PR carries none of the configured docs labels."`
- **`docs PR number` empty.** The REST endpoint needs the PR number, which the old `gh pr edit` form resolved implicitly — so an empty value (a `gh` error, warning-corrupted output) is a real failure point, not a reason to skip silently and tick Documentation complete: record it and apply nothing — `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.1 could not resolve the PR number to apply docs labels; the PR carries none of the configured docs labels."`
- **`raw` empty (and printed), and no rc≠0 breadcrumb above.** The config genuinely resolved to no labels: apply nothing — the clean no-op. (The `if !` hard-read-failure branch also leaves `raw` empty, but it recorded its own `dropped-failed` reflection and is not a no-op.)

Otherwise, read the printed values and apply the labels with **single granted-literal leading-token calls, iterating at the agent level**:

- For **each** label in the printed comma-list (skip blanks), ensure it exists with one call — the helper path is the leading token, and `ensure-label.sh` is best-effort (always exits 0). `ensure-label.sh` always breadcrumbs to stderr (`created` / `already exists` / `warning: …`), so **no output at all means the command was refused by the harness** — record it (`--reflection-kind dropped-failed`) and continue to the apply, which reports separately whether the label landed.
  ```bash
  "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/ensure-label.sh "<label>"
  ```
- Apply the whole comma-list to the PR with one call — the helper path is the leading token, the PR number and resolved label list substituted as literals (**not** `$DOCS_PR_NUM`/`$CLEAN_LABELS` shell variables, which do not survive into this separate command):
  ```bash
  "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/apply-labels.sh <docs-pr-number> "<docs-labels>"
  ```
  `apply-labels.sh` is best-effort (always exits 0) and **always** prints a breadcrumb to **stderr** on **every path it can take** — a harness refusal is its ONLY silent outcome. **Read that stderr from the tool result and route on it — all four outcomes, not just the failure one:** a `devflow: applied label(s) '…' to #N` line means the labels landed; a `devflow: warning: could not apply …` line is an **API failure** (POST `.../issues/{n}/labels` — repo-scope only; never `gh pr edit --add-label`'s org-scoped GraphQL); a `devflow: warning: apply-labels.sh got no label content …` or `… got a non-numeric issue/PR number …` line is a **caller arg-slip** — the breadcrumb says outright that it is *not* a harness denial — meaning the label list you substituted was empty/whitespace-only, or the number did not survive into this command, so re-emit the call once with the printed literal values before recording anything; and **no output at all means the command was refused by the harness**. Record any surviving non-success durably (stderr is ephemeral in an autonomous cloud run), naming which outcome it was: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.1 could not apply the configured docs labels (<docs-labels>) to PR #<docs-pr-number> — the apply reported an API failure or a caller arg-slip, or produced no output at all (a harness denial); the PR carries none of the configured docs labels."`

Then tick the Documentation phase in the workpad: `workpad.py update $ISSUE_NUMBER --tick-progress "Documentation"`.

**Discharge every 3.4-deferred documentation AC (mandatory, before §4.3).** Phase 3.4's *Documentation-AC deferral* rule leaves any acceptance criterion whose satisfaction is a Phase-4.1-owned `docs/…` edit **unticked** at the gate, recording it in a workpad note of the form `3.4: doc-AC deferred to Phase 4.1: {AC text}`. Those deferrals are this phase's obligation to close: now that the docs pass has run and its changes are committed, for **each** such deferred doc-AC confirm the docs the criterion required actually landed in this run's diff (the Stage 2 gate above already verified the named deliverable paths), then tick it by its 1-based position, citing the deferral note — `workpad.py update $ISSUE_NUMBER --tick-ac-n {N} --note "Phase 4.1 discharged 3.4-deferred doc-AC: {AC text} — docs authored by the prflow:docs pass"` (consume the tick call's exit code per the failure-isolation contract; a non-zero exit means the index did not resolve — re-resolve and re-tick). This tick **must** happen before §4.3's terminal `--status Complete` write, because `scripts/workpad.py`'s `_terminal_complete_gate` hard-fails a Complete write while any non-post-merge Acceptance Criteria row is still `- [ ]` — a doc-AC left unticked would abort the finalize. If a deferred doc-AC genuinely **cannot** be discharged (the docs pass could not author it and the content cannot be derived), do **not** tick it and do **not** finalize Complete: take the existing Blocked path (`workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Phase 4.1: 3.4-deferred doc-AC could not be discharged: {AC text}"`), emit the 👎 outcome reaction, and stop — never a silent Complete over an undischarged doc-AC.

**Re-anchor before §4.2 (mandatory, after the Phase 4.1 documentation subagent (which invokes the `prflow:docs` skill) returns and its docs are committed).** Phase 4.1 above dispatched a context-isolated documentation subagent that invokes the `prflow:docs` skill (Stage 1/Stage 2); a long subagent return can evict this phase file from your working set, which is exactly how a run stops at "documentation done" before reaching §4.2/§4.3. So now that the docs subagent has returned and its docs are committed, before proceeding to §4.2, **`Read` `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/phases/phase-4-documentation.md` again and follow it exactly** — re-anchoring the remaining §4.2 (PR description) and §4.3 (finalize) procedure, never relying on the earlier entry-gate read. This re-anchor is scoped to **subagent** returns — here, the Phase 4.1 docs subagent; do not apply it to the Phase 2 or Phase 3 subagent returns, whose phases carry their own entry-gate reads. A **Skill-tool** return is covered instead by the generalized mid-phase re-anchor in the orchestrator's cross-phase rules, which fires after every Skill return in any phase.

### 4.2 Generate PR Description

Invoke the **Skill tool** with `skill: "pr-description"` and `args: "$ARGUMENTS"` (the issue number). The skill detects the existing PR and updates its body directly.

Once that invocation returns, tick the PR-description extension row, applying the extension-row tick rule stated in `phase-1-setup.md` §1.3:
```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --tick-progress "extension resolved: PR description"
```
The `--tick-progress "Documentation"` call above runs *before* this invocation, so at that moment this row is still unticked. Where the state was not established, leave the row unticked and say so with `--note`.

Verify the PR Description update landed before moving to the next step.

```bash
gh pr view --json body --jq '.body' | grep -q "Work in progress — automated review pending" && echo "STILL PLACEHOLDER" || echo "OK"
```

**Reconcile the PR body's claims (mandatory, before finalizing) — a three-class claim audit.** `/pr-description` authored the body just now, so this is the Phase 4.2 counterpart of the §2.3.4a self-authored-claim sweep, applied to the one surface that did not exist at commit time. Re-read the whole PR body and audit it against **three claim classes — behavioral, verification, and artifact-existence** — each naming its own comparand and producing its own recorded outcome. **The artifact — the code, the tests, and the filed artifacts — is the fact**, under the same fix-or-rewrite rule as §2.3.4a: a claim that fails its class is corrected in place and never left standing for the post-publish `/prflow:review` to catch.

1. **Behavioral claims** — comparand: the actual shipped code path, followed into pre-existing code the diff calls. For **every** behavioral claim the body makes about what the shipped code does (a "this PR adds X that does Y", a described flow, a stated guarantee, or a `## Post-Merge Verification` item that on inspection actually describes *already-shipped* behavior rather than a genuinely live-only check — the same confirmation-of-self-claim case the Phase 3.4 gate refuses a `(post-merge)` tag for), trace the actual shipped code path — following dispatch into pre-existing code the diff calls — and confirm the code does what the body says. A claim satisfied by pre-existing code the diff merely calls is true; do not re-litigate a behavioral claim under a comparand meant for tests or artifacts.
2. **Verification claims** — comparand: the tests actually present in this PR's diff. Audit every `## Test Plan` row that asserts a **fact about the diff's tests**, and every "pinned by" / "covered by" / "exercised by" / "mutation-proven" / suite-tally / coverage-enumeration assertion anywhere in the body. Bind each member the claim's **own literal scope** enumerates to a named test present in this PR's diff; a member with no such test makes the row false, and the row is rewritten to what the tests actually cover before finalize. An **imperative** Test Plan row ("the test suite is green end-to-end") asserts nothing about the diff's tests and passes trivially — an instruction to a reader is not a claim. A claim honest about being **transitive** ("covered through the shared validation routine") is true with the tests that exist; the remedy for an over-broad row is its wording, not necessarily a new test.
3. **Artifact-existence claims** — comparand: the artifact's own resolvable identifier (an issue or PR number, or a repo-relative path). Audit every body assertion that a separate artifact **exists or was created** — a follow-up issue, a filed deferral, a linked issue or PR, a cutover or growth artifact, a docs page, a changeset. A claim carrying no resolvable issue/PR number and no repo-relative path is false as written and is rewritten before finalize to state what actually exists. This class does **not** force a follow-up issue to be filed (Phase 4.0 owns filing): "Deferred to a follow-up: <items>" names no artifact and states an intention, so it passes; "A follow-up issue tracks the deferred half" names an artifact and needs the number.

**Resolution (shared across all three classes).** A claim that fails its class is resolved by fix-or-rewrite — "note it and move on" is not an arm:

- If the body **overclaims** (asserts something the diff, its tests, or the filed artifacts do not deliver), correct the body to the truth via REST (repo-scope only, unlike `gh pr edit`'s org-scoped GraphQL resolution): write the corrected body to a file, resolve the PR number (guarding the empty case so a `gh pr view` hiccup doesn't build a malformed `pulls/` path), and PATCH it. The `-F body=@<file>` form reads the field value literally from the file, preserving backticks and `$` exactly as `--body-file` did. This is the common case, since the body was just auto-generated and can overstate:
  ```bash
  OVERCLAIM_PR_NUM=$(gh pr view --json number --jq '.number')
  if [ -n "$OVERCLAIM_PR_NUM" ]; then
    gh api --method PATCH "repos/{owner}/{repo}/pulls/$OVERCLAIM_PR_NUM" -F body=@<file>
  else
    echo "devflow: Phase 4.2 could not resolve the PR number to correct an overclaiming body (best-effort, continuing)" >&2
  fi
  ```
- If reconciliation reveals the **code** is actually wrong (the body states the intended behavior but the diff doesn't meet it), that is a real defect that escaped review: fix the code, commit with `fix:`, and push. On the default `ready_for_review` publish path that fix rides into the cloud `/prflow:review` that re-runs when Phase 4.3 publishes the PR; **but when `implement_pr_state=draft` the PR is left a draft and the cloud review does not auto-fire until a human publishes** (see §4.3), so the fix ships *unreviewed* until then. Either way, record in `Devflow Reflection` that a post-review code fix landed here so it is not mistaken for a reviewed change — and flag it more loudly on the draft path, where no automatic re-review will catch it.
- When an **artifact-existence** claim is corrected, correct **every site this run authored it at in the same change** — the PR body, the workpad Acceptance Criteria preamble, the workpad Plan, any reflection bullet, and the changeset — under the repo's coupled-mirror rule, so the corrected fact is not contradicted by a stale copy the run left elsewhere.

Never finalize a PR whose description asserts a behavior the diff does not deliver, a coverage the diff's tests do not contain, or an artifact that does not exist. **Record one workpad `--note` outcome per class** (mirroring §1.6's per-pass notes), and a class that found nothing records an **explicit clean-pass** note, so a class that ran clean is distinguishable from a class that never ran:
```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER \
  --note "4.2 claim audit (behavioral): {claims checked and how resolved | no behavioral claims to reconcile — pass complete}" \
  --note "4.2 claim audit (verification): {rows checked and how resolved | no verification claims found — pass complete}" \
  --note "4.2 claim audit (artifact-existence): {assertions checked and how resolved | no artifact-existence claims found — pass complete}"
```


### 4.3 Finalize the PR (publish or leave draft) and Finalize Workpad

**Clean-tree backstop (always, before the publish decision).** Assert nothing uncommitted survives the run — this runs **unconditionally**, independent of whether the PR will be published or left a draft:

```bash
git status --porcelain
```

If it is non-empty, **do not** finalize yet. The run began from a clean base-branch checkout (`origin/` + the configured `base_branch`), so anything dirty here is this run's own work an earlier phase failed to commit. Commit the part that belongs to this PR with the right prefix (`feat:`/`fix:`/`docs:`/`chore:`) and push, and record which phase under-committed via `--reflection-kind note --reflection "…"` (a corrected under-commit is informational, not a standing failure) — surface the gap, don't paper over it. Surface (do not blindly `git add`) any unexpected untracked file. When the tree is already clean this is a no-op — create no empty commit.

**Run-transient files are the exception — delete, never commit.** A leftover **reflection-payload file** under `.prflow/tmp/` (authored by the file-based `--reflection-file` recipe when a reflection's text carried backticks/`$`/quotes — see `skills/implement/SKILL.md`) is run-transient scratch, not a deliverable: if one survives here, **delete it** rather than committing it. A **plugin-only adopter** has no `.prflow/.gitignore` scaffold, so the leftover shows up as an untracked file a blind `git add` would commit into the PR. Treat any `.prflow/tmp/` reflection-payload leftover as transient (delete it), never as run work to commit.

**Base-branch update checkpoint 4 (pre-ready) — after the clean-tree backstop, before the publish decision.** So the terminal *published* state carries current base (the review-tier deferral's head-scoped re-evaluation cannot see base advances), bring the branch up to date one last time:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/update-branch-checkpoint.sh
```

Handle the printed token **per the implement-driven outcome-handling contract in phase-1-setup.md §1.4.1** (workpad recording; `Blocked` on `MERGE_IN_PROGRESS` or a failed conflict resolution; resolve a `CONFLICT`, run the suite, and re-run the Phase 2.3.0 sweep; record-and-continue on `UNVERIFIED`/`PUSH_REJECTED` — **that record-and-continue arm is checkpoints 1-3 only; at THIS checkpoint the publish gate below overrides both to a refusal**), with one **checkpoint-4-specific** addition that gates the publish below:

- On **`UPDATED`** a real merge landed and the pushed state was **not** seen by any review pass — but **no separate suite run is owed here.** The *Establish final-tree completion evidence* step below runs after this checkpoint and before the publish decision, over that same merged tree — it names checkpoint 4's merge as one of the candidate-changing operations it exists to cover — and its non-pass arm already routes a failed suite, a non-empty skip population, or a verification command unrunnable on this tier to **Blocked** instead of publishing. Running the whole suite twice over one tree buys no signal, so proceed to the publish gate below and let that flight be the gate.
- On **`UP_TO_DATE` / `DISABLED`** nothing changed, so no suite re-run is needed — proceed to the publish decision unchanged.

**Read the token as the leading word of the emitted line, never as the whole line** — the matching rule `scripts/update-branch-checkpoint.sh`'s own header states for every call site. The value every test below reads is the **first whitespace-delimited field** of the emitted line, read from the invocation's output; never a shell capture (a `TOKEN=$(…)` capture changes the statement's leading token away from the vendored-literal form, the only one carrying a recorded permitted measurement).

**First, separate "the invocation never ran" from "the invocation ran and reported something" — and be honest about which denials are observable.** This test comes *before* the routing list below, because both cases can present with no token line and the routing list would otherwise swallow the first. The invocation is known to have **never run** only when the tool boundary *reports* it — a local-tier classifier denial message, or an rc 127. Those take the *tier-refused* arm at the end of this section (record a degraded reflection and publish). **A silent cloud matcher denial** produces no output and no failure signal, so it is indistinguishable from an invocation that ran and emitted no recognizable token — it therefore takes the **refusal** arm below (fail-closed), not the tier-refused arm: a consumer whose allowlist omits the helper sees the run Blocked at pre-ready, the remedy being to grant `.prflow/vendor/prflow/scripts/update-branch-checkpoint.sh` in `prflow_implement.allowed_tools`. Everything else **ran**, routed by the gate below on the first field of its output.

**Publish gate (checkpoint-4-specific — the run does not publish or complete on a non-clean checkpoint).** The clean set is `UPDATED`, `UP_TO_DATE`, `DISABLED`; the non-clean set is `CONFLICT`, `UNVERIFIED`, `PUSH_REJECTED`, `MERGE_IN_PROGRESS` — together exactly the token set `scripts/update-branch-checkpoint.sh`'s header enumerates, complete by construction against that header. Route the observed first field:

- **Clean (`UPDATED` / `UP_TO_DATE` / `DISABLED`)** — record the checkpoint-4 evidence row naming the observed token **before** publishing, on all three alike, through the **keyed-checkpoint** carrier: `workpad.py update $ISSUE_NUMBER --checkpoint base-update-checkpoint-4 "checkpoint 4: observed token <token> — clean, proceeding to the publish decision"`. The key `base-update-checkpoint-4` deliberately carries **no `gha:` prefix**: the tier discriminator classifies any `<!-- prflow:checkpoint gha:… -->` row as a *cloud* run, and checkpoint 4 runs on **both** tiers, so a `gha:` key would misclassify every local run as cloud. The row's hidden `<!-- prflow:checkpoint base-update-checkpoint-4 -->` marker is what `lib/fetch-pr-context.sh` reads into the bundle's `base_update_checkpoint4_present` field. `--checkpoint` is a *structural* failure with zero PATCH on a non-canonical body (a **duplicate** `## Progress`, an empty body — an *absent* `## Progress` is repaired, not refused); the terminal `--status Complete` write is gated on this exact keyed row, so a `--checkpoint` call that exits non-zero here fails this step **closed** — resolve the non-canonical workpad body and retry. The row records the **checkpoint's** result, not the run's outcome (the completion-evidence flight below still runs after it and can route to `Blocked` before publishing), so `UPDATED` records on the same footing as the other two clean tokens. §1.4.1's rule that `UP_TO_DATE`/`DISABLED` add **no** workpad traffic stays byte-unchanged for checkpoints 1-3, which is why the existing checkpoint note cannot serve as this channel. Then proceed (a `DISABLED` run — the consumer set `prflow_implement.update_branch_checkpoints: false` — publishes and completes exactly as it does today).
- **`CONFLICT`** — **not** routed to the refusal below. It follows §1.4.1's inherited resolve-then-suite-then-commit-then-push path (a resolution that fails the suite keeps that contract's abort-and-`Blocked` path), with one checkpoint-4 bound stated below, and the checkpoint helper is then **re-invoked**; the first field of *that re-invocation's* line is the value this gate reads. The re-invocation is **bounded to one**: a second consecutive `CONFLICT` takes the refusal arm below rather than resolving again.
- **Non-clean (`UNVERIFIED`, `PUSH_REJECTED`, `MERGE_IN_PROGRESS`), or a first field that is empty or unrecognized** — **refuse to run `gh pr ready` and refuse to flip `Status` to `Complete`.** A run that never reconciled with the base must not reach a published, `Complete` end state with no signal that its work was never checked against current trunk. **On `UNVERIFIED`, or an empty/unrecognized field, re-invoke the helper once before refusing** — several such causes are transient and environmental rather than staleness facts (a failed `git fetch`, a `config-get.sh` read failure), and the helper mutates nothing on any `UNVERIFIED` path, so a second invocation is free. **`PUSH_REJECTED` and `MERGE_IN_PROGRESS` get no re-invocation**: those paths re-run fetch/merge/push and a second `git reset --hard`, so re-invoking would compound an already-failed restore rather than clear a blip — they refuse immediately. Grade the re-invocation's first field where one was made; if it is still non-clean, record `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "checkpoint 4: the base-update checkpoint did not report a clean token after one re-invocation — observed line: <the observed line, verbatim>; helper breadcrumb: <the helper's own stderr breadcrumb, verbatim>; not publishing and not completing"` — quoting the breadcrumb rather than asserting non-reconciliation as the cause — then emit the 👎 outcome reaction and stop. (The work is preserved on the branch, so the remedy is a re-trigger. A shallow checkout whose history cannot be extended emits `UNVERIFIED` with a "no reachable merge base" breadcrumb and blocks here, the intended fail-closed direction.)

**The discriminator for "the helper did not report a token" is observable, not "no output at all."** `scripts/update-branch-checkpoint.sh` rebinds fd 1 to stderr (`exec 3>&1 1>&2`) and emits the token on the saved fd 3, so git's own chatter reaches you interleaved with the token and a successful invocation is **never silent**. The discriminator is therefore: **no line whose leading word is a member of the helper's documented token set appears in the invocation's combined output.** That case takes the refusal arm above as an unrecognized field.

**An invocation whose refusal the tier REPORTS is a distinct case, and it publishes.** This is the arm the tool-boundary test above routes to — a local-tier classifier denial message, or rc 127 — separated from an unrecognized field by *that* reported signal, never by the shared "no token line" observable. The checkpoint never ran, so there is no token to grade — record it through the **keyed-checkpoint** carrier under its own key: `workpad.py update $ISSUE_NUMBER --checkpoint base-update-checkpoint-4-tier-refused "checkpoint 4: the update-branch-checkpoint invocation was refused by this tier (<denial/rc 127>) — base reconciliation at pre-ready is unverified this run; publishing per §1.4.1's degraded posture"`. This key is deliberately **distinct** from the clean-token key so a consumer can tell "the base was reconciled" from "the tier refused the check"; like it, it carries **no `gha:` prefix**. A `--checkpoint` call that itself exits non-zero here fails this step **closed**. Then **proceed to the publish decision**, matching §1.4.1's degraded posture. It does **not** route to `Blocked`: converting a permission boundary into a run-ending stop would end every such run with no escape, because the `update_branch_checkpoints: false` off-switch yields `DISABLED` only when the helper actually runs.

**Establish final-tree completion evidence — after checkpoint 4, before the publish decision.** The terminal `--status Complete` write below is gated by `scripts/workpad.py` on a *current, passing* verification-flight record for the run's final in-env verification command (the `_terminal_complete_gate` re-validates the record and re-derives the candidate identity immediately before PATCH). Several Phase 4 operations mutate the candidate **after** Phase 3's verification — the 4.1 docs/changeset commit, a 4.2 `fix:` claim-audit commit, the 4.3 clean-tree backstop commit, and checkpoint 4's merge — so Phase 3's flight is stale by definition here. The **parallelization** of this final verification defers to the consumer prompt extension's final-verification rule; that deferral relaxes no suite run still **serialized before its commit** — a conflict resolution's **resolve-then-verify** ordering runs the suite on the resolved tree before that tree is committed. Establish evidence for the **final** tree now:

1. **Launch one verification flight for the final tree** through the existing non-executing `scripts/verification-flight.py` protocol (`claim` → `mark-running` → run the project's already-allowlisted verification command **unchanged** → `finish --result passed|failed …`), exactly as the Phase 3.3 inline pass does. **Scope is not decided here:** run it at the scope the repository's implement prompt extension's `Verification-flight scope` statement sets — the single source; a scope answer derived anywhere else is wrong. **Set the flight's `candidate_identity` to the final-tree identity:** obtain it from the reception preflight — the granted `reception-record.py` prints a stdout JSON object carrying `candidate_identity` (the git tree id `scripts/reception_identity.py` derives, which the gate re-derives) — read the value from the tool output and put it in the `claim` declaration's `candidate_identity` field (agent-level substitution into the declaration file, not a shell capture) — a record with a null `candidate_identity` fails the gate. The `finish` summary file carries `command` (a nonempty string) and `exit_status` (the integer `0` on a pass), with an **empty** `skipped_checks` list — the implement-completion policy admits no skip population. **Produce both the declaration's `checkout` fingerprint and the re-anchor `--current-checkout-file` with `scripts/checkout-fingerprint.py`** (cloud vendored leading-token form `.prflow/vendor/prflow/scripts/checkout-fingerprint.py`), the single producer of the five-field checkout object: set its JSON output as the `claim` declaration's `checkout` field, and pass a freshly-produced fingerprint to every `status`/`wait` re-anchor as `--current-checkout-file` — without it the read reports non-pass, because `status`/`wait` enforce the checkout AND themselves.
2. **Record the validated flight key** on the workpad: `workpad.py update $ISSUE_NUMBER --record-completion-evidence <flight-key>` (the `<flight-key>` is the `flight_key` value `claim`/`finish` printed). This validates the record under the implement-completion policy and, only on a pass, writes the hidden `completion-verification:<flight-key>` marker (replacing any prior one). A non-pass record aborts this call before any PATCH — do not proceed to Complete; take the Blocked path below.
3. **On a non-pass or unrunnable suite → Blocked, never Complete.** A failed suite, a non-empty skip population, or a verification command that is **not locally re-runnable on this tier** means there is no in-env pass for the final candidate, so the run cannot honestly finalize: `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Phase 4.3: final-tree verification did not establish a clean in-env pass (<token/cause>) — cannot record completion evidence; not publishing/completing"`, emit the 👎 reaction, and stop. This step is the sole owner of the unrunnable-verification case: a **tier-refused verification** routes to **Blocked here** rather than publishing-and-completing (in-env verification is the run's gate; CI is the post-PR merge gate, never an in-run completion authority). The checkpoint-4 *base-update* tier-refusal arm (§ above) still **publishes** its degraded note — that arm is about the base-update checkpoint, not the verification suite, which this step's Blocked path owns when it is unrunnable.

**An execution ceiling is not a verdict.** When the tier's per-command execution ceiling *terminated* the command instead of letting it reach a result, no failure and no skip population was **observed**, so item 3 does not apply and its wording would misreport the change. Take the decomposition path the implement prompt extension states — run the same population one unit at a time, each inside the ceiling, and recombine them into one whole-suite result — then establish the flight from that, per item 1. Only when the recombined run itself cannot be observed does the run stop, at a terminal distinguishable from item 3's: `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Phase 4.3: execution-ceiling — the whole-suite verification could not be OBSERVED inside this tier's per-command ceiling (<command>); decomposition was attempted and <outcome>. No suite failure or skip population was observed, so this is a runner limit, not a verdict on the change"`, emit the 👎 reaction, and stop.

The off-switch is honored per this issue: with `.verification_flight.enabled` set to `false`, an implement run still runs this claim/mark-running/finish sequence to **produce** the machine record completion requires — `false` suppresses only flight *reuse* (attaching to another owner's terminal evidence), not the record's production.

**Publish decision — `implement_pr_state`.** Whether the run publishes the PR or leaves it the draft created in Phase 3.1 is a per-consumer config choice. Read it (default `ready_for_review`), then publish **only** when it is not the exact literal `draft` — default-to-publish is the safe direction, so a missing key, empty string, or any unrecognized value publishes, and a hard read failure (malformed config) falls back to publishing. **Capture whether `gh pr ready` actually succeeded** so the finalize wording reflects the *real* end state — a fallen-through failure (the `else` arm catches *any* non-zero exit — auth scope, GitHub 5xx, rate limit, a race that already merged/closed the PR) would otherwise leave the workpad falsely claiming the PR was published when it is still a draft:

```bash
PR_STATE=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .prflow_implement.implement_pr_state ready_for_review) || PR_STATE=ready_for_review
PR_OUTCOME=draft   # one of: draft | published | publish_failed (overwritten below unless PR_STATE=draft)
if [ "$PR_STATE" = "draft" ]; then
    echo "devflow: implement_pr_state=draft — leaving PR as a draft (skipping gh pr ready)" >&2
elif gh pr ready; then
    PR_OUTCOME=published
elif [ "$(gh pr view --json isDraft --jq '.isDraft' 2>/dev/null)" = "false" ]; then
    # `gh pr ready` returns non-zero on any non-draft PR, so a non-zero exit with the PR NOT a
    # draft is the already-ready case (a re-run, or a PR a human/race already published). Treat as
    # published so a re-run doesn't emit a spurious "publish failed" reflection. Fails SAFE: if
    # `gh pr view` itself errors, the substitution is empty (`!= "false"`) → else arm → publish_failed.
    PR_OUTCOME=published
    echo "devflow: gh pr ready returned non-zero but PR is already non-draft — treating as published (idempotent re-run)" >&2
else
    PR_OUTCOME=publish_failed
    echo "devflow: gh pr ready FAILED — PR is still a draft, or its state could not be confirmed (implement_pr_state=$PR_STATE); do NOT finalize the workpad as 'marked ready'" >&2
fi
```

When `PR_STATE` is `draft` the PR is **left as the draft** from Phase 3.1: no `gh pr ready`, and **no additional comment** is posted to the PR thread. The downstream consequence: a CI `ready_for_review` listener does not auto-fire until a human publishes the PR.

Then finalize the workpad — tick the final `## Progress` item and flip `Status` to `Complete` (the helper swaps the glyph to 🎉) in **every** case; only the `--note` wording differs, and on a publish failure a `dropped-failed` reflection is added (in its own `update` call, see below), so the workpad never falsely claims a PR was published. Pick the `--note` by `PR_OUTCOME`:

- **`PR_OUTCOME=draft`** → `--note "/prflow:implement run finished, PR left as draft per implement_pr_state=draft: <PR_URL>"`
- **`PR_OUTCOME=published`** → `--note "/prflow:implement run finished, PR published (gh pr ready): <PR_URL>"`
- **`PR_OUTCOME=publish_failed`** → `--note "/prflow:implement run finished, but gh pr ready FAILED — PR is still a draft, or its state could not be confirmed: <PR_URL>"` **and** emit a separate `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "gh pr ready failed at Phase 4.3 — PR left unpublished despite implement_pr_state=$PR_STATE; publish it manually (gh pr ready) so the cloud review and CI ready_for_review listener fire"` call (the durable note mirrors the stderr breadcrumb's wording — it must not assert "still a draft" as fact on the unconfirmed-state path where the `isDraft` re-check itself errored). It is a **`dropped-failed`** reflection (a publish failure needing human action), so it goes in its own `update` call — separate from the `note`-kind finalize below — because one `--reflection-kind` applies to the whole call.

```bash
# Substitute the PR_OUTCOME-specific --note above. The general --reflection events are `note`-kind;
# the publish_failed `dropped-failed` reflection above is a SEPARATE update call (different kind).
# `--tick-progress "PR marked ready"` MUST match the `## Progress` row label verbatim — that label
# is owned by scripts/workpad.py; do NOT rename it here without renaming it there (and the tests).
# TWO distinct non-zero exits are possible — read the stderr to tell them apart, consuming the exit
# code per the failure-isolation contract rather than treating the run as cleanly Complete:
#   (1) a *volatile* tick miss: the body WAS PATCHed (Status flipped, note written), only the
#       "PR marked ready" row is still `- [ ]` — re-tick just that row (label drift / already ticked).
#   (2) the terminal self-record gate *structurally aborts* this Complete write — NO PATCH, Status
#       NOT flipped — when a non-post-merge `## Acceptance Criteria` row is still `- [ ]` (stderr:
#       "refusing to finalize Status: Complete — … Acceptance Criteria row(s) still unticked"). The
#       Phase 3.4 gate should have ticked every non-post-merge AC, so this is a drift; do NOT retry
#       verbatim — resolve the AC as Phase 3.4 does (`--tick-ac-n {N}`, or the Blocked path), THEN
#       re-issue. (post-merge AC rows never trip this; an unticked `## Plan` row, or an
#       `## Acceptance Criteria` section still holding the un-mirrored placeholder, only prints a
#       non-blocking warning — if that fires, investigate the mirroring, don't just re-run.)
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER \
    --status Complete \
    --tick-progress "PR marked ready" \
    --note "{PR_OUTCOME-specific note above}" \
    [--reflection-kind note --reflection "{noteworthy event}" ...repeat --reflection per event]
# Check the exit code of the finalize update above (per the failure-isolation
# contract): exit 0 means the "PR marked ready" box is now `- [x]` and the run is
# Complete; a non-zero exit means the tick missed (label drift / already ticked on a
# resumed run) — re-resolve and re-tick the row before treating the run as done.
```

Add one `--reflection` flag per noteworthy event a human should know for troubleshooting: a failed step that was skipped, a subagent that returned no useful output, a permission denial, a test you couldn't run, an ambiguity you resolved with an assumption, or any deviation from the planned flow. Kind each by the reflection style contract's routing rule (see `skills/implement/SKILL.md`): a deviation you worked around is the *informational* `note` kind (`--reflection-kind note`); an engine/process-improvement proposal is `improvement`; feedback that the driving issue's claims were wrong or underspecified is `issue-accuracy`; genuinely actionable failures (a dropped manifest entry, a publish failure) are emitted at the point they occur with `--reflection-kind dropped-failed` so they land under `### ⚠️ Action required`. `--reflection` is repeatable so all the same-kind events land in a single atomic update. (No separate "Notes from /prflow:implement run" comment is posted — the workpad replaces it.)

Finally, emit the 🎉 outcome reaction on the triggering comment (`REACTION=hooray`; see *Outcome reaction* in the Workpad Reference) — the implement lifecycle completed regardless of the publish decision (`draft`, `published`, or `publish_failed`; the publish failure is surfaced via the `--reflection` above, not by suppressing the reaction) — then output the PR URL and a one- or two-line summary of what was accomplished (state whether the PR was published, left a draft, or whether `gh pr ready` failed).
