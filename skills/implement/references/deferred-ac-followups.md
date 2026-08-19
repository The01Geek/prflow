<!-- prflow:implement-ref step=4.0 file=skills/implement/references/deferred-ac-followups.md start -->

### 4.0 File Follow-Up Issues for Deferred Work (orchestrator GitHub writes)

You are reading this reference because the phase file's §4.0 routing stub has established — through the `deferred-presence` predicate — either that at least one acceptance criterion Phase 2.2.5 deferred is still outstanding, or that the answer could not be established. This reference dispatches the `deferral-drafter` agent to compose the follow-up issue bodies, then performs the GitHub writes from the plan it returns — the composition lives in the agent (`agents/deferral-drafter.md`), which makes no GitHub write. Dispatch it, then file the follow-up issues for the plan's drafts.

#### Dispatch the deferral-drafter agent

The drafter composes each follow-up issue body and returns a filing plan naming each draft by a path under `.prflow/tmp/`; it makes no GitHub write and dispatches nothing. This dispatch is authorized by `skills/implement/SKILL.md`'s injection-condition clause without any edit to it: this reference is a member of the implement bundle (surface (1) — "this orchestrator root, its `phases/*.md`, and its `references/*.md`"), so the dispatch instruction it carries is authorized by that clause on the shipped orchestrator alone, not on a consumer prompt extension.

**Commit any uncommitted tree state before dispatching.** The drafter works in this orchestrator's own checkout, so a version-control command it runs would be scoped to a path rather than to its edit and would discard whatever you left uncommitted. Run `git status --porcelain`; commit anything it reports **before** the dispatch. When the tree state cannot be established, establish it first; when the run holds work it must deliberately not commit, park it under a recorded handle and restore it after the drafter returns, or do not dispatch and record `Blocked` naming the uncommittable work.

Use the Agent tool with `subagent_type: prflow:deferral-drafter` and `run_in_background: false` (its return must be in hand this turn — a launch acknowledgment is never the return) and no worktree isolation (it must read the Phase 1.1 cache in this checkout and write its drafts here). Pass in its prompt, as literals you already hold: `ISSUE_NUMBER` (`$ISSUE_NUMBER`); `OUTSTANDING_CRITERIA` (on the exit-0 arm, each predicate `criterion:` projection line paired with its verbatim text from the Phase 2.2.5 `--note`; on the exit-2 arm, the verbatim criteria you enumerate from that note); `SCOPE_DECISION_NOTE` (the Phase 2.2.5 scope-decision `--note` text, and for each deferral whether it is an ordinary size/phased deferral or a capability-blocked one — Phase 1.6 Pass 5); `ISSUE_BODY_PATH` (the Phase 1.1 cache path `.prflow/tmp/issue-body/issue-$ISSUE_NUMBER.md` when the cache was written; on the degraded arm where it was not, say so and pass the parent slots inline); `TMP_DIR` (`.prflow/tmp/`); and the create-issue template and writing-standard plugin-relative read paths (`create-issue/references/issue-template.md`, `lib/writing-standard.md`) resolved via the same `<skill-dir>` anchor.

If the drafter dispatch fails or returns no usable plan, record `--reflection-kind dropped-failed` naming the failure and continue to §4.0.5 without halting Phase 4. Otherwise you hold a `DEFERRAL-DRAFTER PLAN` with one entry per composed draft: an entry names its `draft_path` under `.prflow/tmp/`, its `title`, whether it is `capability_blocked`, its `projection_disposition`, and one `marker_value` per criterion it covers. Perform the GitHub writes below yourself for an eligible plan entry.

Read the plan's degradation signals before you file anything. This reference is the only reader the drafter's `writing_standard_loaded`, `parent_slots_source` and `notes:` fields have, so a degradation you do not record here leaves no trace at all — the thin follow-up is filed, its criterion discharged, and it is never re-filed. Read all three from the returned plan and, before the first `gh issue create` below, record every non-clean one in a single durable reflection: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0's deferral-drafter returned a degraded plan (writing_standard_loaded: <value>; parent_slots_source: <value>; notes: <the verbatim notes text>); the follow-up issues filed below were composed from it and may carry thin parent-derived slots."` A plan reading `writing_standard_loaded: yes`, `parent_slots_source: cache` and an empty `notes:` is clean and needs no such reflection.

A criterion the plan's `notes:` reports as unplaced was composed into no draft, so no filing discharges it — leave its deferral undischarged at *Discharge the filed criteria* below so the next Phase 4 entry re-files it, and name that criterion in the reflection above.

Consume each draft entry's complete projection tuple before its create fence. Write its `projection_disposition` and `unmatched_desired_behavior` JSON array, preserving every exact unmatched statement, to `<scratch-dir>/deferral-projection-$ISSUE_NUMBER-<entry>.json`, then run the canonical consumer as a single statement:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/run-jq.sh -e -f "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/projection-gate.jq <scratch-dir>/deferral-projection-$ISSUE_NUMBER-<entry>.json
```

Only exit zero makes that entry eligible for the filing checks below. A refused/non-zero invocation, missing field, wrong type, inconsistent disposition, or non-empty unmatched array is a degraded/failed draft: omit the entry from filing, labeling, dependency registration, and filed-marker discharge, then durably report `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0's deferral-drafter returned draft <draft_path> with an unusable projection tuple (disposition '<missing-or-value>'; unmatched statements: <exact JSON array or missing>); the draft was omitted from filing and its deferred criteria remain undischarged for a later Phase 4 entry."` Continue with another eligible entry and then §4.0.5; a bad draft does not invalidate an eligible sibling.

On the two unestablished arms that print no `filed:` line (`reason=workpad-unresolved` / `reason=progress-section-unreadable`) the filed-marker operand is unavailable, not empty — do not read it as "nothing was filed", which would re-file every follow-up a prior Phase 4 entry already created. On those arms, before creating an issue for a plan draft, check GitHub for an existing follow-up covering it (one `gh issue list` read, matched on the parent reference `#$ARGUMENTS` and the criterion text) and create one only when none exists. On the arms that print `filed:` lines, file only for a draft whose criteria those lines do not name.

For a projection-eligible `drafts:` entry in the plan, create a GitHub issue from its `draft_path` body. If the plan names several eligible drafts, issue the `gh issue create` calls in a single assistant turn so they run in parallel, and append a single combined note (`--note`) afterward (do not PATCH the workpad between each `gh issue create`). Post the body via `--body-file <draft_path>` — the file is read literally, so backticks and `$` in the markdown are not expanded — and add no `--label` on the `gh issue create` call itself; the configured `deferred.labels` are applied best-effort *after* creation (see *Apply the deferred-issue labels* below), mirroring the post-creation label-apply idiom Phase 3.1 uses for the `PRFlow` provenance label and Phase 4.1 uses for `docs.labels`.

```bash
CREATE_STATE=""
gh issue create \
  --title "<the plan entry's title>" \
  --body-file <the plan entry's draft_path under .prflow/tmp/> \
  && CREATE_STATE=ok || CREATE_STATE=failed
echo "phase 4.0 create fence ran; create=[${CREATE_STATE}]"
```

The trailing `echo` is an unconditional sentinel: without it a refused create and a create that had nothing to create reach you as the same empty tool result, and its `create=` field further distinguishes a create that ran and failed (also no issue number) from the capture gap below. This fence runs once per follow-up issue, so route each sentinel independently — an `ok` sentinel followed by a `failed` one means one issue exists and one does not, so never read the `failed` arm's "no issue exists" run-globally. Three states, three routes:

- No `phase 4.0 create fence ran` line at all, or the line reads `create=[]` ⇒ the create did not run. `CREATE_STATE` is initialized empty *before* the create statement, so it is produced on every path the fence can take: an empty value means the `gh issue create` statement itself never executed (a harness refusal of that statement), and no line at all means the whole fence was refused. Both mean no issue exists, and both take this exit. File nothing, label nothing, and record it — `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0's follow-up-issue create fence produced no output at all, or reported create=[] (likely a harness denial); no deferred-AC follow-up issue was filed or labelled this run."`
- `create=[failed]` ⇒ the create ran and the API rejected it. No issue exists — do not claim one was filed: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0's gh issue create failed; no deferred-AC follow-up issue was filed this run, so none was labelled."`
- `create=[ok]` ⇒ an issue exists; read its URL for the number and continue to the label applies below.

Apply the deferred-issue labels. As you create each follow-up issue above, capture its number from the `gh issue create` output (the command prints the new issue URL; the trailing path segment is the number) and keep the numbers in your own working notes — an agent-level list, not a shell variable. Do not write it as a shell assignment: a shell variable does not survive into the separate command that applies the labels below (a `VAR=value` prefix on the helper invocation — `FOO=1 apply-labels.sh …` — is separately denied, because it makes the granted helper path no longer the command's leading token; an ordinary in-fence assignment like the `config-get` capture below is *not* that shape). Then apply the configured `deferred.labels` to every filed issue. The labels are read from config (default `PRFlow,Deferred`) and normalized with the same split/trim/drop-empties idiom Phase 4.1 uses for `docs.labels`, so an empty or whitespace-only value applies no labels. Ensure each label exists first (best-effort), then apply them through the shared REST `apply-labels.sh` helper (`POST .../issues/{n}/labels` — repo-scope only, unlike `gh issue edit --add-label`'s org-scoped GraphQL resolution) per filed issue — best-effort and post-creation.

**Cloud-emission discipline (label helpers): iterate at the agent level, never in a shell loop or a capture — see the *Cloud command-shape discipline* section in `skills/implement/SKILL.md`.** The cloud implement matcher denies a `for`/piped-`while read` loop wrapping a label helper (`ensure-label.sh` / `apply-labels.sh`) and a `VAR="$(label-helper …)"` output capture. So do not wrap the label helpers in a shell loop or capture their output into a variable: emit one single-statement, leading-token call per label and per issue, iterating over the labels/numbers yourself.

The `config-get` capture below is unproven on the implement tier — not known-denied, just unmeasured — so every fence below fails closed on a read that produces no output rather than treating a possible denial as "no labels configured".

First resolve and print the clean label list — a `config-get` capture is permitted, and printing it lets you read the resolved value for the per-issue calls below (a shell variable set here does not survive into a later separate command on the cloud runner):

```bash
# The default arg covers the SOFT paths (missing file / unset key → config-get prints it,
# exit 0); only the HARD path (rc≠0 — corrupt config.json / missing python3) enters the
# `if !` branch, where DEFERRED_LABELS stays empty (no labels applied) AND a breadcrumb is
# left. The `if !` reads config-get's OWN exit status inline (never a captured rc read in a
# later statement, which a cross-statement-variable-stripping inline-bash runner would
# leave empty) and is exempt from `set -e`.
if ! DEFERRED_LABELS=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .deferred.labels PRFlow,Deferred); then
  DEFERRED_LABELS=""
  "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0 could not read deferred.labels (config-get rc≠0 — corrupt config.json or python3 missing); deferred follow-up issues filed WITHOUT labels."
fi
# Normalize with GRANTED heads only. `paste` is granted in NO allowlist (baked TOOLS,
# config.json, config.example.json), so a `| paste -sd, -` tail makes the WHOLE pipeline
# refused — the capture then produces no output, and a reader who treats that as "no
# labels" ships exactly the silent-denial defect this rework exists to end. `tr`/`sed`/
# `grep`/`echo` are all granted; the trailing-comma strip replaces what paste did.
CLEAN_DEFERRED_LABELS=$(echo "$DEFERRED_LABELS" | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' | grep -v '^$' | tr '\n' ',' | sed 's/,$//')
# Print BOTH: the RAW config value and the normalized list. Printing only the normalized
# one makes an emptied normalizer indistinguishable from an empty config — and the
# normalizer runs on PATH tools the preflight does not guarantee: a missing tool
# yields an empty value and the wrong thing is silently selected.
echo "deferred.labels raw: [$DEFERRED_LABELS]"
echo "deferred labels to apply: [$CLEAN_DEFERRED_LABELS]"
```

The capture gap is the `create=[ok]` but no number case, and only that one — the other two empty-handed outcomes are routed above and must not be collapsed into it, because only this one means an issue exists that went unlabelled:

- `create=[ok]` and you captured no issue URL/number — the issue was created and you cannot read its number. That is a real capture gap (not a benign no-op) — record it durably and apply nothing: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0 filed deferred follow-up issues but captured no issue numbers — the configured deferred labels were applied to NONE of them; the filed issues carry none of the configured deferred labels."`
- `create=[failed]`, or no sentinel line at all — no issue was created. Take the matching exit above; do not record the capture-gap reflection, which would assert issues exist that do not.

Read the two printed lines together — three outcomes, and only one is a benign no-op:

- Neither line printed at all. The command was refused by the harness, so it produced no output. Do not read that as "no labels": the capture shape is unproven on this tier (above). Record it and apply nothing: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0 could not resolve deferred.labels — the config-get command produced no output at all (likely a harness denial, not an empty config); deferred follow-up issues were filed WITHOUT labels."`
- `raw` is NON-empty but `to apply` is empty. The config *did* resolve labels and the normalizer dropped them — a missing `tr`/`sed`/`grep` on this host, or a refused pipeline. That is a broken derivation, not an empty config: record it and apply nothing: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0 resolved deferred.labels to a non-empty value but the normalizer produced an empty list (a missing/denied tr|sed|grep in the pipeline); deferred follow-up issues were filed WITHOUT labels."`
- `raw` is empty (and printed), and no rc≠0 breadcrumb was recorded above. The config genuinely resolved to no labels: apply nothing — the clean no-op. (If the `if !` hard-read-failure branch fired, `raw` is empty because the read *failed*, not because there are no labels; that path already recorded its own `dropped-failed` reflection and is not a no-op.)

Otherwise, read the printed `CLEAN_DEFERRED_LABELS` value and apply the labels with single granted-literal leading-token calls, iterating at the agent level:

- For each label in the printed comma-list (skip blanks), ensure it exists with one call — the helper path is the command's leading token, and `ensure-label.sh` is best-effort (always exits 0). `ensure-label.sh` always breadcrumbs to stderr (`created` / `already exists` / `warning: …`), so no output at all means the command was refused by the harness — record it (`--reflection-kind dropped-failed`) and continue to the apply, which reports separately whether the label landed.
  ```bash
  "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/ensure-label.sh "<label>"
  ```
- For each filed issue number in your working notes (not a live `$DEFERRED_ISSUE_NUMBERS` shell variable — it does not survive into this separate command), apply the whole comma-list with one call — the helper path is the leading token, the issue number and the resolved label list substituted as literals:
  ```bash
  "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/apply-labels.sh <filed-issue-number> "<deferred-labels>"
  ```
  `apply-labels.sh` is best-effort (always exits 0) and always prints a breadcrumb to stderr on every path it can take — a harness refusal is its ONLY silent outcome. Read that stderr from the tool result and route on it — all four outcomes, not just the failure one: a `devflow: applied label(s) '…' to #N` line means the labels landed; a `devflow: warning: could not apply …` line is an API failure (POST `.../issues/{n}/labels` — repo-scope only; never `gh issue edit --add-label`'s org-scoped GraphQL); a `devflow: warning: apply-labels.sh got no label content …` or `… got a non-numeric issue/PR number …` line is a caller arg-slip — the breadcrumb says outright that it is *not* a harness denial — meaning the label list you substituted was empty/whitespace-only, or the number did not survive into this command, so re-emit the call once with the printed literal values before recording anything; and no output at all means the command was refused by the harness. Record any surviving non-success durably (stderr is ephemeral in an autonomous cloud run), naming which outcome it was: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0 could not apply the configured deferred labels (<deferred-labels>) to issue #<filed-issue-number> — the apply reported an API failure or a caller arg-slip, or produced no output at all (a harness denial); the issue was filed but carries none of the configured deferred labels."`

Register the parent as a GitHub-native blocked-by dependency (best-effort, per filed issue). Immediately after the label stamp above, register the follow-up's declared prerequisite — the `Blocked by #$ARGUMENTS` line the `## Dependencies` section carries — as a GitHub-native blocked-by dependency, so the parent-blocked follow-up carries its parent link on GitHub. The helper `scripts/apply-issue-dependencies.py` mirrors the label-stamp contract exactly — it fetches the filed issue's body itself (so it takes only the number), derives the prerequisites through the same recognizer this phase's `## Dependencies` shape is written for, always exits 0, and leaves a specific `apply-issue-dependencies.py:`-prefixed stderr breadcrumb on every path it can reach. For each filed issue number in your working notes (not a live shell variable — it does not survive into this separate command), invoke it as a single-statement, leading-token call with the filed issue's number substituted as a literal:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/apply-issue-dependencies.py <filed-issue-number>
```

Cloud-emission discipline (dependency helper): the same as the label helpers above — one single-statement, leading-token call per filed issue, never a `for`/`while read` loop wrapping the helper and never a `VAR="$(…)"` capture of its output. Read the helper's stderr from the tool result and route on it — the same four outcomes: a `apply-issue-dependencies.py: linked …` / `… already blocked_by …` / `… skipped #<n>: … reads as an OUTBOUND relation …` / `… done for #<n>: …` line is a successful registration outcome (the `skipped …` line names a prerequisite the helper correctly dropped because its `## Dependencies` line declares this issue as the prerequisite, not a blocker — it is not a failure); a `… could not link … (API refused …)` or `… every declared prerequisite's registration was refused …` line is an API failure; a `… missing or non-numeric issue-number argument …` line is a caller arg-slip (the breadcrumb says outright it is *not* a harness denial) — re-emit once with the captured number before recording; and no output at all means the command was refused by the harness rather than that nothing needed doing. Record any surviving non-success durably, naming which outcome it was: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0 could not register the parent #$ARGUMENTS as a GitHub-native blocked-by dependency of follow-up #<filed-issue-number> — the helper reported an API failure or a caller arg-slip, or produced no output at all (a harness denial); the follow-up was filed but carries no native blocked-by link to its parent."` The registration is best-effort and post-creation.

Discharge the filed criteria. Record the new issue numbers in the workpad and, in the SAME `workpad.py update` call, write one `--mark-deferred-filed` marker per criterion you filed — emit a `--mark-deferred-filed` value only for a criterion whose own create fence printed `create=[ok]` and whose issue number you captured; a criterion on the `create=[failed]` arm, the no-sentinel/`create=[]` arm, the capture-gap arm, or the plan's unplaced-criterion note gets no marker, so the next Phase 4 entry re-files it. The marker irreversibly suppresses that next entry, so marking a criterion whose create did not demonstrably land strands it permanently. Each marker value is the plan entry's `marker_value` — the normalized projection the scope-decision record is matched against, which the drafter computed for you (on the predicate's *outstanding* arm it is the `criterion:` projection; on the *unestablished* arm the drafter normalized the verbatim text exactly as `scripts/section_parse.py`'s `normalize_criterion` does). Emit the call as a single statement whose leading token is the helper path, like every other helper call in this file:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --note "Filed follow-up issues for deferred work: #N (phase 2), #N+1 (phase 3), …" --mark-deferred-filed "<plan entry's marker_value>" --mark-deferred-filed "<second plan entry's marker_value>"
```

This durable machine-readable marker is what makes a second Phase 4 entry's predicate read `not-outstanding`, so that entry dispatches the drafter for nothing and files no duplicate follow-up issue. The free-text `--note` stays the human-readable record and is not the predicate's operand; a run that writes the note and omits the markers files duplicates on its next Phase 4 entry. `--mark-deferred-filed` only breadcrumbs on a value it cannot use, so a wrong `marker_value` is stored as written and never matches later (a duplicate follow-up) — this is why the drafter, not this reference, computes it.

Then continue to 4.0.5.

<!-- prflow:implement-ref step=4.0 file=skills/implement/references/deferred-ac-followups.md end -->
