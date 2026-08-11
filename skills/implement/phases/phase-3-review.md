<!-- prflow:implement-ref phase=3 file=skills/implement/phases/phase-3-review.md start -->
<!-- prflow:implement-set phase=3 part=1 of=3 -->

## Phase 3: Review & Fix

Output: `Phase 3/4: Review & Fix — creating PR and running review...`

**Writing standard.** Before composing this phase's first `--reflection` bullet, read the shared writing standard and follow it.

`workpad.py update $ISSUE_NUMBER --status Reviewing`.

### 3.1 Create Draft PR

**Base-branch update checkpoint 2 (pre-draft-PR) — run FIRST, before `gh pr create`.** Phase 2 can run for hours, so immediately before the draft PR exists, bring the feature branch up to date with the configured base so the self-review (3.2) and the first review pass (3.3) see current base. Invoke the shared checkpoint helper — it derives the base branch *internally* (from `base_branch`, the same fail-closed fallback the draft-PR block re-derives below), so no `$BASE` needs to be in scope here:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/update-branch-checkpoint.sh
```

Handle the printed token **per the implement-driven outcome-handling contract in phase-1-setup.md §1.4.1** (record on the issue workpad; `Blocked` on `MERGE_IN_PROGRESS` or a failed conflict resolution; resolve a `CONFLICT` and re-run the Phase 2.3.0 sweep before continuing; record-and-continue on `UNVERIFIED`/`PUSH_REJECTED`). **Do not open the draft PR on a tree the run has hard-stopped on**: `MERGE_IN_PROGRESS`, an unresolved (or suite-failed, aborted) `CONFLICT`, and a `PUSH_REJECTED` whose stderr carries the failed-restore `WARNING` (see §1.4.1's `PUSH_REJECTED` caveat) each stop the run instead. **Every other token proceeds to open the draft PR** — `UP_TO_DATE`, `UPDATED`, `DISABLED`, a *resolved* `CONFLICT`, and equally the record-and-continue outcomes `UNVERIFIED` and an ordinary (restore-succeeded) `PUSH_REJECTED`: those two are *degraded but non-fatal* by the §1.4.1 contract, and the branch is simply not vouched current (the read-target rules stay in force). Withholding the PR on them would contradict the contract's own "record and continue" and would leave the run wedged at Phase 3.1 with no PR and no stop.

**Resolve whether this run ADOPTS an already-open PR or CREATES one — through the extracted resolver, emitted as its own leading-token command.** A §2.0 gate-fire resume — or any run whose §1.4 resume pre-check adopted an already-open PR — reaches §3.1 with the PR already created by a prior attempt, and a bare `gh pr create` would abort with "a pull request already exists". That decision is *branch-selecting* logic, so it is not inline shell here: it lives in a helper the suite drives arm-by-arm, whose comments state the full contract (why the query is open-scoped rather than `gh pr view`, why an empty branch name never reaches the query, how the newest PR on a shared head is selected, and why an unresolvable query never collapses onto "none found"). Pass only the issue number — the helper re-derives the head branch and the base internally, because neither survives the shell boundary between this command and the next:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/resolve-existing-pr.sh --issue $ISSUE_NUMBER
```

The helper prints **exactly one token line**, with a matching exit code:

| Printed token | Exit | Meaning |
|---|---|---|
| `ADOPT <n> OK` | 0 | an open PR was resolved and both validations passed — adopt PR `<n>` |
| `ADOPT <n> WARN:<checks>` | 0 | adopt PR `<n>`, but `<checks>` (a comma-separated subset of `closes-issue`, `base-ref`) did not hold |
| `CREATE` | 2 | the query ran cleanly and found no open PR |
| `REFUSED` | 3 | the answer could not be established |
| *nothing at all* | — | the fence was **refused by the harness**, which answers nothing: route it exactly as `REFUSED` (the helper breadcrumbs on every path it can take, so silence is never one of its own outcomes) |

**Route the arms — the REFUSED arm is a terminal stop, not a breadcrumb.** stderr is not a durable channel: on the cloud tier the workpad is the only record the stall backstop reads, so a REFUSED arm that merely printed would leave the workpad at an interim `🚀 Reviewing` with no `PR` link and let §3.2–§3.4 run with no PR — the wedged state this guard exists to prevent, and the one it would then cause. So:

- **REFUSED** (the token printed, **or the fence printed nothing at all**). **Route this by whether the run is a resume, because the risk is asymmetric and only a resume carries it.** Both halves of that evidence are durable **in the workpad**, not merely in context, so no further network call is needed: §1.4's resume pre-check outcome (did it adopt an existing branch/PR?) is read back from its `resume-precheck: ` note, and Phase 1.3's durable `resume-kind:` marker is the other half.
  - **On a resume** (§1.4 adopted a PR or branch, or `resume-kind` is `in-flight`) a prior attempt's PR probably exists, so creating blind risks a duplicate: do **not** continue into the PR-link resolution, the label calls, or §3.2. Record the cause durably and stop — `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "Phase 3.1: could not resolve whether an open PR already exists for this branch (empty branch name, a gh pr list failure, or a refused fence) on a RESUME; refusing to create a PR that may duplicate a prior attempt's — resolve and re-run"` — then emit the 👎 outcome reaction (see *Outcome reaction* in the Workpad Reference) and end the run at that terminal status.
  - **On a fresh run** there is no prior attempt to duplicate, so a transient failure must **not** end the run: fall through to the create fence below — which fails loudly and harmlessly with "a pull request already exists" in the vanishingly rare case the query was wrong — and record the degraded query with `--reflection-kind note`. This asymmetry is deliberate: before this guard existed a fresh run simply created the PR, and gating the common path on a *second* network call succeeding would trade a real duplicate-PR risk that fresh runs do not have for a new Blocked-on-rate-limit failure they would.
- **ADOPT** (either form): continue below, treating `<n>` as the run's PR, and **skip the create fence entirely**. On the `WARN:<checks>` form adoption still proceeds — this is a visibility obligation, not a stop — but the named checks must not vanish into stderr: record them durably first with `workpad.py update $ISSUE_NUMBER --reflection-kind note --reflection "Phase 3.1 adopted open PR #<n> whose validation failed (<checks>): it may be an unrelated PR that merely shares this head branch."`
- **CREATE**: run the fence below and route on the **token it prints as its last line** — the create can fail for an auth expiry, an API 5xx, a `--base` that no longer resolves, or a rate limit, and `gh pr create`'s own diagnostics go to stderr, so the fence prints its outcome to stdout instead of leaving you to infer it. Read that token; do **not** issue a further `gh` call to establish it:
  - `create: ok` — the PR exists (its URL is on the preceding line). Continue below.
  - `create: failed` — the create failed and the fence prints `gh`'s own explanation (captured from its stderr) on the lines above the token. Take the **same terminal stop as REFUSED**, but **name the cause**: read that captured `gh` output and carry it into the durable `blocked` reflection (it distinguishes an expired login, an API 5xx, a `--base` that no longer resolves, a rate limit, or `gh`'s unpushed-branch refusal `aborted: you must first push …`) rather than recording only `create: failed`; then emit the 👎 outcome reaction and end the run. **The separate case where the fence printed nothing at all** (a harness refusal, which answers nothing and captures no output) is unchanged — route it exactly as REFUSED. In both cases do **not** continue into the PR-link resolution, which would write a broken `[#]()` link and run §3.2–§3.4 with no PR.

**Ensure the branch is pushed to an explicitly-named destination — run this BEFORE the create fence.** `gh pr create` (below) refuses when it cannot confirm the feature branch is pushed at the current commit, so make that condition true first by pushing `HEAD` to a destination named **explicitly** — never a bare `git push`, whose no-upstream and name-mismatch failure modes `scripts/update-branch-checkpoint.sh` documents at length under its *"Never a bare `git push` here"* comment. Name the remote and the full destination ref outright — `origin` + `refs/heads/<branch>` — which is that helper's own no-mismatch convention and byte-for-byte what Phase 1.5's `git push -u origin HEAD` already established as this branch's upstream, so a bare push's implicit `push.default` resolution (the failure mode the helper warns about) never enters into it. (`git config` is deliberately **not** read in this fence: it is granted on no cloud implement profile, so an in-fence `git config` read would be silently refused there — leaving the whole fence to fall through or be denied, the very silent-failure this step exists to remove. A checkout whose upstream was deliberately renamed to a *different* remote/ref must set that upstream before this step, exactly the known-limitation the helper's own comment records.) Re-pushing an already-current branch is a safe no-op (`Everything up-to-date`). Guard a detached HEAD — where `git rev-parse --abbrev-ref HEAD` prints `HEAD` — rather than pushing to a ref literally named `HEAD`. The fence captures the push's own output and prints a token:

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$BRANCH" = HEAD ] || [ -z "$BRANCH" ]; then
  printf 'detached HEAD (no branch to push) — expected to run on the checked-out feature branch\npush: failed\n'
elif PUSH_ERR=$(git push origin "HEAD:refs/heads/$BRANCH" 2>&1); then
  printf 'push: ok\n'
else
  printf '%s\npush: failed\n' "$PUSH_ERR"
fi
```

Route on the token: on `push: ok` continue to the create fence. On `push: failed` — the branch is not pushed, so `gh pr create` would refuse anyway — take the terminal stop: record a durable `blocked` reflection carrying the captured `git` output printed above the token (naming the cause instead of a bare failure), emit the 👎 outcome reaction (see *Outcome reaction* in the Workpad Reference), and end the run. On **no output at all** (a harness refusal, which answers nothing) on a **resume**, stop exactly as the REFUSED arm above; on a **fresh** run, fall through to the create fence, which fails loudly and names its own cause if the branch really is unpushed.

**The CREATE fence — re-derive the base branch and open the draft PR against it in ONE bash block.** Each phase's bash block runs as a **separate** shell, so the `$BASE` resolved in Phase 1.4 is **not** in scope here — re-read it (behaviorally identical to Phase 1.4: the `config-get.sh` read plus the fail-closed empty-read fallback to `main`) so `gh pr create` targets the **configured** `base_branch` rather than the repo default branch. Keep the re-derivation and `gh pr create` in the **same** block so `$BASE` cannot be lost to a shell boundary between them (an empty `--base ""` would mistarget silently — the very failure this fix prevents). The create is wrapped in an `if` whose two arms each print a token, so the fence's own stdout answers "did it succeed?" without a second network call — `gh pr create` still prints the new PR's URL on success, and that line is preserved above the token. Pass the re-derived base as the `--base` flag; do **not** pass `--head`. `gh pr create` defaults `--head` to the checked-out feature branch, but that default is correct **only when the branch is already pushed and its pushed copy is at the same commit as the local branch** — `gh` resolves `--head` by comparing the local `HEAD` commit against the recorded server-side ref, and when it cannot confirm they match it refuses with `aborted: you must first push the current branch to a remote, or use the --head flag`. Passing `--head` does **not** satisfy that condition — it makes `gh` *skip* the check and assume the branch is already on the server, so on an unpushed or stale-pushed branch it either fails server-side (the named head ref does not exist) or opens a PR against a server-side ref that lacks the work; either way it is not the fix. The push step above makes the condition true instead.

Derive the run link exactly the way Phase 1.3 §1.3 does — the same
`$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID` form — so the draft PR
links back to the run that created it, letting a reviewer trace it to its originating job's
logs. On a **local-tier** run there is no GitHub Actions run, so `$RUN_URL` is empty and the
`View run` line is omitted entirely rather than rendering a broken `[View run]()` link. The
heredoc uses an **unquoted** `<<EOF` so `$RUN_URL` expands (the `/prflow:implement` backticks
are backslash-escaped so they stay literal, not command substitution):

```bash
BASE=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .base_branch main) || BASE=""
[ -n "$BASE" ] || { echo "devflow: base_branch read failed (malformed config or missing python3); falling back to 'main'" >&2; BASE=main; }
# Empty on a local-tier run (no GITHUB_RUN_ID) → the View-run line is stripped below.
RUN_URL=""
[ -n "$GITHUB_RUN_ID" ] && RUN_URL="$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID"
BODY=$(cat <<EOF
Work in progress — automated review pending.

Resolves #{issue_number}
[View run]($RUN_URL)

Generated via \`/prflow:implement $ARGUMENTS\`
EOF
)
# Local-tier run has no run URL: drop the broken "[View run]()" line rather than
# leaving a placeholder link in the PR body.
[ -n "$RUN_URL" ] || BODY=$(printf '%s\n' "$BODY" | grep -vF '[View run]()')
if CREATE_OUT=$(gh pr create --base "$BASE" --draft --title "{issue title}" --body "$BODY" 2>&1); then
  printf '%s\ncreate: ok\n' "$CREATE_OUT"
else
  printf '%s\ncreate: failed\n' "$CREATE_OUT"
fi
```

**On the adopt arm, do NOT re-write the PR body** — the prior attempt's body (and its §1.4-refreshed `[View run]` line) stands; re-creating or re-bodying it would clobber a human's edits.

Then populate the workpad's `PR` link from the resolved draft PR — **freshly created, or the one just adopted** — and **print the PR number** — you need it as a literal in the label call below, and a shell variable does not survive into a later separate command on the cloud runner.

**On the ADOPT arm, use this fence instead of the one below**, substituting the adopted digits for `<adopted-pr>`. Both values must come from one **explicitly-addressed** read: the bare `gh pr view` in the create-arm fence is the unscoped form the resolver's contract rejects, so re-resolving there could bind `PR_URL` to a *different* PR than the number just adopted (a closed sibling, or another PR on the same head) — producing a workpad link whose number and URL disagree, the exact failure the resolver exists to prevent. Passing the number as a positional argument removes the branch-wide ambiguity entirely:

```bash
# ADOPT ARM ONLY — <adopted-pr> is the number from the resolver's `ADOPT <n>` token,
# substituted as a literal. The positional argument is what makes this read scoped;
# without it `gh pr view` resolves by branch across OPEN/CLOSED/MERGED (the unscoped
# form the resolver's contract rejects).
PR_URL=$(gh pr view <adopted-pr> --json url --jq '.url') || PR_URL=""
# Guard the link write on a non-empty URL: writing first and remedying after would
# already have PATCHed a broken `[#N]()` link that the remedy cannot undo.
if [ -n "$PR_URL" ]; then
  "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --pr-link "[#<adopted-pr>]($PR_URL)"
  printf 'pr-link: ok\n'
else
  printf 'pr-link: unresolved\n'
fi
echo "draft PR number: [<adopted-pr>]"
```

**Route on the `pr-link:` token this fence prints — the guard's outcome is an observable, not an inference.** Both arms print one, exactly as the create fence's `create:` tokens do, because an empty `PR_URL` is otherwise indistinguishable from a successful write: the guard suppresses the link (writing first and remedying after would already have PATCHed a broken `[#N]()` link the remedy cannot undo), and the `draft PR number` line still prints regardless, because the adopted number is known whether or not its URL resolved — so neither of the two exits below would fire. On `pr-link: unresolved` — **or no `pr-link:` line at all**, a harness refusal, which answers nothing — the workpad carries no `PR` link: record it durably with `--reflection-kind dropped-failed` and apply no label, exactly as the create arm's failures below are recorded. On `pr-link: ok` the link is written; continue.

**On the CREATE arm**, use the original fence:
```bash
PR_URL=$(gh pr view --json url --jq '.url')
PR_NUM=$(gh pr view --json number --jq '.number')
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --pr-link "[#$PR_NUM]($PR_URL)"
echo "draft PR number: [$PR_NUM]"
```

Then stamp the reserved `PRFlow` **provenance** label on the PR (best-effort). `PRFlow` is a hardcoded provenance constant (no config key controls it; its superseded `DevFlow` spelling stays selectable on already-labelled history, but new runs stamp only `PRFlow`) — it is the branch-naming-independent signal the weekly retrospective uses to detect DevFlow-authored PRs. Apply it through the shared REST label-apply helper after creation (a PR is an issue, so the same `POST .../issues/{n}/labels` endpoint serves it) so a label hiccup can never block the run.

**Cloud-emission discipline (label helpers): emit each call as a single leading-token statement, and substitute the PR number as a LITERAL — see the *Cloud command-shape discipline* section in `skills/implement/SKILL.md`.** Two rules bind here, both learned from the silent-denial defect: the label helpers must never be wrapped in a shell loop or an output capture, and `$PR_NUM` — set in the *previous* fence — **does not survive into this separate command**, so passing it as a variable applies the label to **no issue at all**: the helper sees an empty number, refuses at its arg-slip guard, and breadcrumbs `got a non-numeric issue/PR number ''` (unquoted, the empty expansion word-splits away and the *label* is swallowed as the number instead — same refusal). Nothing is ever applied to issue `""`, but nothing is applied to the PR either, and the provenance label is silently lost unless you read that breadcrumb. Read the printed `draft PR number` and substitute the digits:
**Two exits before the apply.** If **no `draft PR number` line was printed at all**, the fence was refused, not answered (the `VAR=$(gh pr view …)` capture is an unproven shape on this tier) — do **not** read it as "empty": record it and apply nothing, noting the workpad `PR` link written in that same refused fence may also be unset — `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 3.1: the draft-PR-number fence produced no output at all (likely a harness denial); the PR carries no PRFlow label and the workpad PR link may be unset."` If the line printed but is **empty**, the PR number could not be resolved: record it durably and apply nothing — `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 3.1 could not resolve the draft PR number to apply the PRFlow provenance label; the PR carries no PRFlow label, so the retrospective's label-first detection will not see this run."`

This is **two separate calls**, not one fence split for readability: each helper path must really be its own command's leading token, so they are emitted as two distinct Bash invocations (the three phase-4 label channels do the same). Never merge them into one fence, and never chain them with `&&` or `;` — the second head would no longer lead its command.

**Call 1 — ensure the `PRFlow` label exists in the repo** (idempotent; creates it if absent):
```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/ensure-label.sh PRFlow
```

**Call 2 — apply it to the draft PR**, substituting the digits of the `draft PR number` printed above for `<draft-pr-number>` (a literal, never `$PR_NUM` — see the discipline note above):
```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/apply-labels.sh <draft-pr-number> PRFlow
```

Both helpers always exit 0 and need only the `repo` scope: `ensure-label.sh` always breadcrumbs — created / present / a `gh` error — so **no output at all from it means the harness refused it**; record that (`--reflection-kind dropped-failed`) and continue, and `apply-labels.sh` applies via REST `POST .../issues/{n}/labels` (not `gh pr edit --add-label`, which resolves the repo via org-scoped GraphQL and fails under a repo-scoped token).

**Route on the apply's stderr — all four outcomes, not just the failure one.** `apply-labels.sh` **always** breadcrumbs on **every path it can take**, so a harness refusal is its ONLY silent outcome: `devflow: applied label(s) 'PRFlow' to #N` on success; `devflow: warning: could not apply …` on an API failure; `devflow: warning: apply-labels.sh got a non-numeric issue/PR number …` (or `… got no label content …`) on a **caller arg-slip** — the breadcrumb says outright that it is *not* a harness denial, and it is the shape a `$PR_NUM` that did not survive into this command produces, so re-emit the call once with the printed digits substituted as a literal before recording anything; and **no output at all when the harness refuses the command** (a denied command prints nothing — which is why the helper breadcrumbs on every other path: otherwise "applied", "denied" and an empty label list would be indistinguishable). The run continues regardless of the label outcome, but a non-success must not vanish: `PRFlow` is the hardcoded provenance constant the weekly retrospective's label-first detection matches, so a silently-dropped provenance label makes this whole run invisible to the retrospective loop. On a surviving warning line **or no output at all**, record it durably, naming which outcome it was: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 3.1 could not apply the PRFlow provenance label to the draft PR — the apply reported an API failure or a caller arg-slip, or produced no output at all (a harness denial); the PR carries no PRFlow label, so the retrospective's label-first detection will not see this run."`

**Bind the Phase-2 scope-decision records to this PR — here, at the first moment the PR number exists.** §2.2.5 and §2.2.6 wrote their scope-decision records carrying the literal `pending`, because no PR existed when they ran, and a record still reading `pr=pending` at review time deliberately covers nothing — the review engine's membership check fails closed on it — so binding is not optional. Substitute the digits of the `draft PR number` printed above for `<draft-pr-number>` (a literal, never `$PR_NUM` — the discipline note above):

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --bind-scope-decisions <draft-pr-number>
```

The call is idempotent — it rewrites only records still reading `pr=pending` and leaves already-bound records untouched — so a resumed run re-entering §3.1 re-binds nothing. When a run wrote **no** scope-decision records, no record changes — but the call is still a real mutation (`--bind-scope-decisions` is one of the flags `workpad.py` counts as a non-checkpoint mutation), so it refreshes `Last updated` and issues one PATCH. That is harmless, so run this step **unconditionally** — do not try to detect first whether any records exist.

#### 3.1.1 Assign the draft PR to the triggering user (CREATE arm ONLY)

**This step runs ONLY on the CREATE arm — never on ADOPT.** Assignment is a create-time ownership action: a freshly-created draft PR has no assignee, so PRFlow assigns it to the developer who triggered the run. An **adopted** PR already belongs to its first attempt's assignees, so the ADOPT arm **skips this step entirely and leaves the existing assignees untouched** — do not invoke the helper on that arm.

The `apply-pr-triggerer.sh` helper resolves the triggerer by tier and best-effort-assigns the PR: on a **cloud** run it reads the authorized comment sender the workflow propagates through `DEVFLOW_TRIGGERING_USER` (fail-closed — a missing value is a deployment-skew signal, never permission to substitute the token owner, the App identity, or `GITHUB_ACTOR`); on a **local** run it resolves the authenticated login through `gh api user --jq .login`. It always exits 0 and prints exactly one outcome token to stdout — `assignment: applied <login>` or `assignment: skipped <reason>` — so a hiccup never blocks the run.

**Cloud-emission discipline (assignment helper): emit the call as a single leading-token statement, substituting the PR number as a LITERAL — see the *Cloud command-shape discipline* section in `skills/implement/SKILL.md`.** As with the label helpers, `$PR_NUM` — set in an earlier fence — **does not survive into this separate command**, so read the printed `draft PR number` and substitute the digits (never a variable, never a loop or output capture). Substitute the digits of the `draft PR number` printed above for `<draft-pr-number>`. Emit the granted **vendored literal** below first — the bare anchor is denied as a leading token by the cloud matcher, so it is retained only as the fallback arm:

```bash
.prflow/vendor/prflow/scripts/apply-pr-triggerer.sh <draft-pr-number>
```

**Tier-agnostic invocation procedure (the conditional form — do not classify your own tier).** Emit the vendored literal above first. If it reports the file was not found (`command not found` / `No such file` / exit 127 — this repository's own local tier, where `.prflow/vendor/` is materialized only at runtime and so is absent from a working checkout), re-invoke **the same helper with the `.prflow/vendor/prflow/` prefix removed** (`scripts/apply-pr-triggerer.sh <draft-pr-number>`) as a single leading-token statement, then route on that invocation's outcome. If *that* is also not found (a non-Claude-Code runner — Copilot CLI, Cursor, Codex CLI, Gemini CLI — where neither repo-relative path exists), fall back to the portable anchor form below, which **preserves the helper's portability on those runners** (`${CLAUDE_SKILL_DIR}` is empty there and the runner reports a base directory the agent substitutes for the placeholder):

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/apply-pr-triggerer.sh <draft-pr-number>
```

**Route on the token this helper prints — all outcomes.** The helper breadcrumbs to stderr on every path and prints exactly one `assignment:` line to stdout, so a harness refusal is its ONLY silent outcome:
- `assignment: applied <login>` — the PR was assigned; continue (optionally note it).
- `assignment: skipped <reason>` — **for every `<reason>` EXCEPT `unconfirmed`, which the next bullet owns** — a path on which **no assignment was made** (`invalid-input`, `no-triggering-user`, `identity-lookup-failed`, `empty-identity`, `api-failure`); the PR is preserved. Record it durably and continue, substituting the printed reason for `<reason>`: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 3.1.1 could not assign the draft PR to the triggering user (assignment: skipped <reason>); the PR is preserved and unassigned."`
- `assignment: skipped unconfirmed` — **not the same claim**: here the add-assignee request itself *succeeded* and only the confirmation failed (GitHub silently ignoring an unassignable login, an empty or truncated response body, or a degraded `jq`), so the helper knows it could not **confirm** assignment — never that assignment did not happen. Record what was observed and **do not write "unassigned"**: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 3.1.1 could not confirm the draft PR was assigned to the triggering user (assignment: skipped unconfirmed — the add-assignee request succeeded but its response did not confirm the login); the PR is preserved and its assignee state is unconfirmed."`
- **no `assignment:` line at all** — a harness refusal, not an empty value; record it durably the same way, naming it a likely harness denial, and continue: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 3.1.1: the assignment helper produced no output at all (likely a harness denial); the draft PR is preserved and its assignee state is unconfirmed."` (A denial issues no request at all, but a helper killed between the POST and its outcome line would also print nothing — so this outcome establishes no assignee state either way.)

The run continues regardless of the assignment outcome — assignment is best-effort and never gates the PR.

### 3.2 Self-Review with /simplify

Invoke the **Skill tool** with `skill: simplify` — this runs the **built-in Claude Code `/simplify` slash-command**, not a DevFlow plugin skill (so there's no `devflow:` prefix and nothing to install). It ships with Claude Code and is always present; do not treat it as a missing skill or skip this phase.

`/simplify` runs the code-review engine over the current diff in **quality-only** mode — the **reuse / simplification / efficiency / altitude** cleanup angles — and applies the fixes directly instead of stopping at a report (skipping any whose fix would change intended behavior). By its own charter it does not hunt for bugs; use `/code-review` for that. It remains a fast self-review that catches the quality issues the heavier `review-and-fix` engine in 3.3 would otherwise spend turns on, keeping 3.3 focused on correctness, contracts, and verification rather than quality nits.

**Cleanup agents are quality-only; they never own correctness.** These operative rules follow from that charter:

- `/simplify`'s cleanup agents are quality-only reviewers, never correctness reviewers — chartered for the reuse / simplification / efficiency / altitude angles only.
- The orchestrator never solicits a correctness or guard-class verdict from a `/simplify` cleanup agent.
- The orchestrator never records a cleanup agent's "clean" report as evidence toward any correctness class — a "clean" from an agent chartered not to examine correctness is not evidence that correctness holds.
- Correctness is owned by the Phase 3.3 reviewers, whose dispatch prompts carry the repo's guard classes via `.prflow/prompt-extensions/review-and-fix.md` (a consumer prompt extension that `/simplify`, a built-in Claude Code skill, never loads).

**Triage each `/simplify` finding against the issue's acceptance criteria before applying it (this `/prflow:implement` path only).** The `/simplify` cleanup agents see only the diff — never the issue's `## Acceptance Criteria` or any Phase 2.2.5 scope decisions — so a cleanup that reads as correct against the diff alone can directly violate the issue's deliberate scope (e.g. move a rule out of the file an AC pinned it to, or trim an exclusion list or wording an AC mandated). Before applying each finding, evaluate it against the workpad's in-scope `## Acceptance Criteria` and Phase 2.2.5 scope-decision notes — **against both the *literal* AC text and the *generality / consumer-facing* ACs** (an AC that mandates a surface stay broad, work for all consumers, or not narrow an event/input/filter). A finding can satisfy every literal AC while breaking a generality one: **any finding that narrows an event, input, or filter surface re-runs the consumer-boundary question before it lands** — does this narrowing still serve every consumer the AC intends, or does it optimize for the literal cases only? (an applied efficiency finding narrowed the `workflow_run` event filter in a way that satisfied every literal AC while breaking push-CI consumer repos — a generality AC — caught only by a later shadow.) If its fix would violate an acceptance criterion (literal or generality) or the decided scope, **skip the finding and record the AC conflict as the skip rationale** via `workpad.py update $ISSUE_NUMBER --note "skipped /simplify finding: {finding}; would violate AC: {which criterion}"`. Apply findings that do not conflict as normal. This triage is the apply-time analogue of the Phase 3.4 AC gate and exists only on the issue-context `/prflow:implement` path — it does **not** change standalone `/simplify` / `/code-review` behavior, which carry no issue/AC context. One carve-out: a finding that conflicts with a now-*stale* AC that a legitimate refactor superseded is **not** a silent skip — that is Phase 2.2.6 AC-rewrite territory (rewrite the AC text with a `--note` paper trail, then let the finding apply), never this guardrail.

After the skill completes, commit any fixes and push:
```bash
git add -A
git commit -m "refactor: address /simplify findings for issue #$ARGUMENTS"
git push
```

If `/simplify` reported the code was already clean and made no changes, skip the commit and continue.

**No verification round is owed between §3.2 and §3.3.** This commit ships without its own full-suite run: §3.3's `review-and-fix` loop runs a verification as its first act, and the `/simplify` edits just committed ride into that first verification. So do **not** launch a full suite here to verify the `/simplify` commit — a fresh commit does not, on its own, owe a verification round when the very next step verifies it. (This changes nothing about §3.2's acceptance-criteria triage guardrail, which still governs which findings are applied, and it does not remove this commit — both are unchanged.)

Then tick the `/simplify` gate: `workpad.py update $ISSUE_NUMBER --tick-progress "/simplify"`.

<!-- prflow:implement-ref phase=3 file=skills/implement/phases/phase-3-review.md end -->
