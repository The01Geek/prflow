## Phase 3: Review & Fix

Output: `Phase 3/4: Review & Fix — creating PR and running review...`

**Writing standard.** Before composing this phase's first `--reflection` bullet, read the shared writing standard `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/writing-standard.md` and follow it (the always-loaded Reflection style contract absorbed those rules into this read, so the read is what keeps them present). A failed load emits a breadcrumb naming the file and the failure kind, and you compose the reflection without it.

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

**Cloud-emission discipline (label helpers): emit each call as a single leading-token statement, and substitute the PR number as a LITERAL — see the *Cloud command-shape discipline* section in `skills/implement/SKILL.md`.** Two rules bind here, both learned from the silent-denial defect: the label helpers must never be wrapped in a shell loop or an output capture (probe rows I4/I5/I6), and `$PR_NUM` — set in the *previous* fence — **does not survive into this separate command**, so passing it as a variable applies the label to **no issue at all**: the helper sees an empty number, refuses at its arg-slip guard, and breadcrumbs `got a non-numeric issue/PR number ''` (unquoted, the empty expansion word-splits away and the *label* is swallowed as the number instead — same refusal). Nothing is ever applied to issue `""`, but nothing is applied to the PR either, and the provenance label is silently lost unless you read that breadcrumb. Read the printed `draft PR number` and substitute the digits:
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

### 3.3 Review & Fix

**Snapshot this run's per-iteration workpad baseline first (before invoking `review-and-fix`).** The observability backstop below decides whether *this* run wrote any `iter-*.json`; on the local/interactive tier `.prflow/tmp` persists across runs, so a whole-tree presence check would count a prior run's leftover and mask a genuine loss. Record the pre-existing set now so the post-return detector measures only what this run adds:
```bash
# Snapshot the pre-existing iter-*.json before driving review-and-fix inline, so the post-return
# detector measures whether THIS run wrote any per-iteration workpad — on the local/interactive
# tier .prflow/tmp persists across runs, so a leftover iter-*.json would satisfy a whole-tree
# presence check and MASK a genuine telemetry loss this run. Snapshot to a file because each
# phase bash block is a separate shell.
ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
# Check mkdir's own exit status so a failure names its root cause (permissions/read-only-fs/
# disk-full) here rather than surfacing only as the generic "snapshot file missing" degrade
# downstream.
if ! mkdir -p "$ROOT/.prflow/tmp" 2>/dev/null; then
  echo "::warning::phase-3.3: could not create $ROOT/.prflow/tmp (permissions/read-only-fs/disk-full?); pre-loop snapshot will be missing, degrading the no-inputs detector to whole-tree presence below" >&2
fi
# Portable enumeration (this prose block runs under the AGENT's shell — zsh/dash/sh — not a
# bash-shebanged .sh, so no bash-only glob-completion builtin, and the unquoted glob must survive zsh's
# default `nomatch`). The guard turns nomatch off under native zsh (no-op elsewhere: $ZSH_VERSION
# unset → `&&` short-circuits, `|| :` stays rc-0). `set --` captures the matched iter-*.json into
# "$@" (with nomatch off, an unmatched glob leaves $1 the literal pattern). `[ -e "$1" ]` gates
# the enumeration so the EMPTY-set case writes an EMPTY snapshot file — never the literal
# unmatched pattern — via the builtin `printf` (no external tool whose absence could fake output).
[ -n "${ZSH_VERSION:-}" ] && setopt nonomatch || :
set -- "$ROOT"/.prflow/tmp/review/*/*/iter-*.json
{ [ -e "$1" ] && printf '%s\n' "$@" | sort; } > "$ROOT/.prflow/tmp/.phase33-iters-before" || :
```

Invoke the **Skill tool** with `skill: review-and-fix` and `args: "--push-each-iteration --issue $ISSUE_NUMBER"`, substituting the issue number as its literal digits. `--issue` is load-bearing: it tells the review engine which issue to source the run's acceptance criteria from, and without it the engine judges this PR against a surface the run has already narrowed or rewritten. The `--push-each-iteration` flag is load-bearing here too: this phase operates on the live draft PR created in 3.1, and `--push-each-iteration` propagates each fix iteration to the remote branch so its CI validates the converging state and progress survives a mid-loop crash. (Direct users of `/prflow:review-and-fix` omit the flag and the loop's **fix commits** stay local — though Loop Exit's `--persist` still pushes the `prflow-telemetry` branch regardless of the flag; see that skill's Input section for the flag's semantics.)

**Stay on the instrumented loop — a cloud permission/sandbox denial is not license to leave it.** This phase drives `review-and-fix` **inline in your context**. If you hit a `claude-code-action` permission or sandbox denial here — a piped/compound `.sh` invocation, a `$(...)` redirect target, or a shell `>` write into `.prflow/tmp` refused as "may only write to files in allowed working directories" — that denial is not the local-tier permission classifier, and is not license to abandon the instrumented loop and hand-run the review engine via direct `Agent` dispatch. On the cloud implement job `Skill`, `Agent`, `Write`, `efficiency-trace.sh`, `workpad.py`, and `config-get.sh` are all allowlisted, so the instrumented loop is navigable, not blocked. Whatever path the review runs, the per-iteration effectiveness record (`iter-<N>.json`) is a non-optional emit on every iteration, written with the Write tool (never a shell `>`/heredoc redirect the sandbox denies) — that is what keeps the **effectiveness** half of the telemetry recoverable even on a degraded, hand-run pass; and the emit is non-optional **on every path, including a degraded one**.

**A denied `Skill` call is not the engine being unavailable — `Skill` is a loader, and the engine is a file in the tree.** This dissolves the dilemma before any telemetry argument is needed. `review-and-fix` executes the review engine's `SKILL.md` Phases 0–4.3 verbatim; those files are in the checkout — resolve the engine directory by the ordered, repo-root-anchored candidate list `review-and-fix`'s `references/loop-control.md` Step 1 defines (the repo-root `skills/review` for a devflow-self checkout, then `.prflow/vendor/prflow/skills/review` and the superseded `.devflow/vendor/devflow/skills/review` for a consumer checkout), binding the bundle to whichever resolves first. If the `Skill` invocation is refused twice, apply the repo's own shape discipline (two denials of a shape → switch to a permitted alternative, never iterate variants): **`Read` the engine from the tree and execute its phases inline.** That is not "hand-running the review from memory" — it *is* the engine, from source. The only thing you may never substitute is a **paraphrase**: five agents dispatched from recollection, with no checklist generate/dedupe/verify, no Step 2.5 classification, no shadow pass, no deferrals manifest, no convergence criteria, is a different artifact wearing the label of a DevFlow review.

**The emit is the only form any shipping code reads.** `lib/efficiency-trace.sh` pins the `iter-*.json` field contract and `--persist` derives `.prflow/logs/efficiency/` from it; `lib/efficiency-trace.jq` derives `verification_posture` from its `checklist[]`; and `defect_signature` is the correlation key the review engine itself joins on — Phase 3.2's mechanical corroboration and the fix loop's iter-(N+1) prior-findings handoff both key on it. Your **adjudication** (the calibrated `severity`, the `fix_decision` and its reasoning, the `defect_signature`) is a judgment that exists only because you record it, so dropping the emit means no shipping consumer sees any of it, on either tier.

When you need a scratch or telemetry file under `.prflow/tmp`, author it with the Write tool, not a shell redirect; the pre-loop snapshot below is a shell-computed listing whose redirect may itself be refused — its failure does not abort the phase, though it degrades the no-inputs detector to whole-tree presence (which the detector's own `::warning::` surfaces on the run log, because on the persistent local tier a leftover `iter-*.json` can then mask a real loss); it is a degrade to note, not a hard blocker, and never a reason to leave the loop.

This runs the four-phase review engine in your context:
1. **Verification checklist** — generates and verifies every dependency interaction, test-mock alignment, data format assumption, and API contract claim against actual source code
2. **Existing review agents** — runs the first-party review agents (code-reviewer, silent-failure-hunter, comment-analyzer, type-design-analyzer, pr-test-analyzer) and the first-party `prflow:requesting-code-review` final-pass reviewer in parallel
3. **Automatic fix loop** — fixes findings using `prflow:receiving-code-review` principles, re-runs the engine, loops until APPROVE or the configured iteration cap (`prflow_review_and_fix.max_iterations`, default 5)

Follow the skill's instructions. It handles evaluation, fixing, testing, and re-review internally.

**Observability-persistence backstop (after `review-and-fix` returns, before the verdict branches below).** `review-and-fix`'s Loop Exit is what normally derives this run's effectiveness record (`.prflow/logs/efficiency/<slug>-<run-id>.json`) and durable workpad copy from its per-iteration `iter-*.json`. But this phase drives that loop **inline in your context**, so a dropped Loop Exit leaves those artifacts unpersisted and the run contributes nothing to `.prflow/logs/efficiency/` — the skill's own top-documented "Common Mistake," unguarded at this seam. So regardless of the verdict, first **verify this run's observability artifacts were persisted and run the efficiency-trace persist backstop when they are missing**; the backstop is idempotent (it never re-derives an existing record), so running it unconditionally is safe. **When the inline loop wrote no per-iteration workpad, `--persist` now first *synthesizes* a minimal iteration record from this run's fix commits** (`fix: address review findings (iteration N)` commits → the `ITER_SYNTH_EXPECTED_FIELDS` set in `lib/efficiency-trace.sh` (the effectiveness fields, plus `unrecoverable` provenance for the run-scoped evidence fields)), so the zero-workpad case is answered by synthesis, not only a reflection. The synthesized `iter-*.json` land under the same `.prflow/tmp/review/` tree, so the new-input detector below counts them as recovered inputs and does **not** fire the gap reflection. **Only when synthesis *also* finds nothing** — the loop wrote no workpad **and** synthesis recovered nothing (no unrecorded fix commit, a failed search — unresolvable base ref, a base ref left unestablished by a failed origin/<base> refresh, or a failed `git log` — failed writes, a discovery-mode skip: workpad-less run dirs ambiguous across slugs, or this dir not its slug's synthesis target, or an unsubstituted `<placeholder>` identity refused by either persist call; `--persist`'s warnings name which when a candidate dir was visited at all) — **record a `dropped-failed` reflection naming the observability gap** so the lost telemetry is visible rather than silently absent:
```bash
# Anchor on the repo root the SAME way efficiency-trace.sh does (git toplevel), so the "no
# inputs" detector below reads the exact .prflow/tmp/review tree --persist scans — a
# cwd-relative path could diverge from the wrapper and fire a false "telemetry lost" reflection
# or mask a real loss.
ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
# Idempotent Layer-3 persist: derives the effectiveness record and durable workpad copy
# from whatever iter-*.json this run left under .prflow/tmp/review/ and writes them to the
# long-lived orphan telemetry branch (default `prflow-telemetry`, key telemetry.branch) via
# git plumbing — it does NOT commit to this feature branch and never touches HEAD, the
# current branch, or the TRACKED working tree. Idempotent on that branch: the
# effectiveness record is presence-idempotent (a `git cat-file -e <ref>:<path>` probe skips a
# run already stored), the durable workpad copy re-writes identical bytes, and an unchanged
# tree makes no new branch commit; a full no-op if the inline loop wrote no per-iter workpad. Best-effort
# (always exits 0). Two calls, targeted FIRST: this orchestrator drove review-and-fix
# inline and holds the loop's <slug> and RUN_ID, and persisting its own run by explicit
# identity is immune to every discovery-mode skip (multi-slug ambiguity, not-latest
# ordering) AND to the lone-stale-foreign-dir shape, where discovery would misattribute
# this branch's fix commits to a leftover slug and the sha exclusion would lock the
# misattribution in while the new synthesized files suppressed the gap reflection. The
# argument-less discovery call then covers every OTHER leftover run dir on disk. If the
# slug/run-id are genuinely not held (the inline loop died before RUN_ID was computed),
# skip the targeted call with a --note recording that, and rely on discovery + the
# detector below as the loud floor — never substitute guessed values.
# On mktemp failure, degrade to /dev/null rather than aborting — the capture becomes a
# no-op (stderr is discarded, so the record-write-failure grep below can never match), but
# --persist's own best-effort exit-0 contract is preserved. Track the degrade explicitly in
# $PERSIST_ERR_IS_DEVNULL (not by re-testing the string later) so (a) the cleanup at the
# bottom of this block never runs `rm -f` on the LITERAL PATH `/dev/null` — under a root
# shell with a writable /dev this would delete the device node itself, breaking every other
# command in the environment that redirects to /dev/null — and (b) the degrade gets the same
# distinct ::warning:: breadcrumb discipline as the sibling $BEFORE-missing degrade below,
# instead of silently no-opping the record-write-failure detector for this run.
if PERSIST_ERR=$(mktemp 2>/dev/null); then
  PERSIST_ERR_IS_DEVNULL=0
else
  PERSIST_ERR=/dev/null
  PERSIST_ERR_IS_DEVNULL=1
  echo "::warning::phase-3.3: could not allocate a temp file for --persist's stderr (mktemp failed); ALL of --persist's stderr (durable-copy/staging/commit warnings included, not only the record-write-failure check) is discarded this run, and the record-write-failure detector is DISABLED (only the no-new-inputs case below is still checked)" >&2
fi
# Targeted persist FIRST (substituting this run's held <slug>/<run-id> — the
# targeted form is exempt from every discovery-mode skip by caller intent):
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/efficiency-trace.sh --workpad-dir "$ROOT/.prflow/tmp/review/<slug>/<run-id>" --slug "<slug>" --persist 2>"$PERSIST_ERR" || true
# Then argument-less discovery for every OTHER leftover run dir on disk; its
# stderr appends to the same capture so the single surfacing line carries both:
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/efficiency-trace.sh --persist 2>>"$PERSIST_ERR" || true   # best-effort; captured (not swallowed) so its ::warning:: breadcrumbs both surface to the run log below AND are checked for a record-write failure by the detector
cat "$PERSIST_ERR" >&2   # surface every --persist breadcrumb to the run log
# Detect the "no inputs FROM THIS RUN" case by diffing against the pre-loop snapshot, anchored
# on $ROOT (matching --persist): comm -13 lists iter-*.json present now but NOT before the
# inline loop — i.e. exactly what THIS run wrote. This is immune to prior-run leftovers on the
# persistent local tier, where a whole-tree presence check would let a leftover mask a real
# loss. If the snapshot file is somehow absent, treating it as empty degrades to whole-tree
# presence — and that degrade direction can MASK a real loss, not surface it: comm -13 against
# an empty snapshot counts every pre-existing leftover iter-*.json on the persistent local tier
# as if this run wrote it, so a leftover file makes the -z check false and suppresses the
# reflection even when this run's loop wrote nothing. Because this snapshot-absent path is the
# reachable failure mode the detector exists to guard against, emit a distinct ::warning:: so
# the degrade is visible on the run log rather than silently indistinguishable from the healthy
# case. Zero NEW iter-*.json means the inline loop wrote no per-iteration workpad, so --persist
# had nothing to derive from and this run's effectiveness telemetry is genuinely lost — surface
# it, do not swallow. (A persist that DID find inputs but failed to write still leaves
# efficiency-trace.sh's own ::warning:: on the run log, surfaced above.) The detector counts NEW
# iter-*.json unconditionally, which is correct here because at THIS seam the review-and-fix
# loop just driven inline is what writes this tree, so a foreign review-sourced dir being the
# sole new occupant is not a reachable in-flow shape.
BEFORE="$ROOT/.prflow/tmp/.phase33-iters-before"
if [ ! -f "$BEFORE" ]; then
  : > "$BEFORE"
  echo "::warning::phase-3.3: pre-loop iter-*.json snapshot missing; no-inputs detector degrades to whole-tree presence, which can MASK a real this-run telemetry loss behind a leftover iter-*.json from a prior local run" >&2
fi
# Portable, no bash-only glob-completion builtin (this prose runs under the agent's shell — zsh/dash/sh). The
# zsh nomatch guard + `set --` capture the current iter-*.json into "$@"; the two arms then make
# the "no inputs FROM THIS RUN" decision STRUCTURALLY distinguish a genuine zero-set from a failed
# enumeration: `[ ! -e "$1" ]` is definitive absence (zero iter-*.json exist at all — with nomatch
# off an unmatched glob leaves $1 the literal pattern, so `! -e` is true), and ONLY when files DO
# exist does the `-z` arm enumerate them via the builtin `printf` and diff `comm -13 "$BEFORE"`
# (files present now but not pre-loop = what THIS run wrote). The builtin `printf` over real
# matches avoids a fail-open path where empty output would fire the false telemetry-loss
# reflection. Caveat (mirrors the site-1 note): `[ ! -e "$1" ]` reads a dangling-symlink
# first-match as definitive absence, so it could record a false telemetry-loss — irrelevant
# here (this DevFlow-controlled iter-*.json tree is never symlinked).
[ -n "${ZSH_VERSION:-}" ] && setopt nonomatch || :
set -- "$ROOT"/.prflow/tmp/review/*/*/iter-*.json
if [ ! -e "$1" ] || [ -z "$(printf '%s\n' "$@" | sort | comm -13 "$BEFORE" -)" ]; then
  # Guard the loss-record write itself: if workpad.py fails (gh API/permission error,
  # absent reflection section, bad $ISSUE_NUMBER) the ::warning:: keeps the gap visible on
  # the run log rather than silently dropping both the telemetry AND its loss-record — a
  # double silent failure at the exact seam this clause exists to make visible. Mirrors the
  # --persist line's best-effort breadcrumb discipline.
  "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "review-and-fix inline loop wrote no iter-*.json this run AND lib/efficiency-trace.sh --persist synthesized nothing (no unrecorded 'fix: address review findings (iteration N)' commit to reconstruct from, a failed search — unresolvable base ref, a base ref left unestablished by a failed origin refresh, or failed git log — failed synthesized writes, or a discovery-mode skip such as multi-slug ambiguity or a refused unsubstituted placeholder identity; --persist's own warnings name which when a candidate dir was visited), so this run's effectiveness telemetry (.prflow/logs/efficiency/) is missing" \
    || echo "::warning::phase-3.3: failed to record dropped-failed observability-gap reflection on issue #$ISSUE_NUMBER; this run's effectiveness telemetry is lost AND its loss-record could not be written" >&2
fi
# The no-new-inputs case above only catches a dropped LOOP EXIT (the inline loop wrote no
# iter-*.json at all). It does NOT catch the sibling failure mode where the loop DID write
# iter-*.json but --persist's own record derivation/write step then failed — that failure is
# otherwise invisible to this this-run-scoped detector, which only measures INPUT presence,
# not persistence SUCCESS. Grep the captured --persist stderr for its record-derivation/write
# failure breadcrumbs so this second, independent failure mode is surfaced too, rather than
# reading "inputs existed" as "persisted successfully". efficiency-trace.sh's three record
# derivation/write failure paths do NOT share one common substring: jq-derivation failure and
# mkdir failure both end "...record not written[ for ...]", but the disk/permission write
# failure (a write after mkdir succeeded — ENOSPC/EROFS/quota/perms) instead reads "...failed
# (disk/permission); not persisted for ..." — so match BOTH literals, or a mutated/renamed
# breadcrumb on just the disk-write path would silently escape this detector exactly as the
# single-literal form did (review Step 3.5 fix-delta gate). This intentionally scopes to
# record derivation/write failures only, not the separate TELEMETRY-BRANCH write/push failure
# surface (telemetry-branch.sh's "::warning::telemetry-branch: ..." breadcrumbs — a lost CAS, a
# non-conforming store, an unwritable .prflow/tmp). The record is staged under gitignored
# .prflow/tmp/; afterward a DEGRADED branch write (or a CI staging-only run) RETAINS that staging
# root (only a clean rc-0 write deletes it), bounded by a newest-N prune on the next --persist; a
# DEGRADED write additionally emits one ::warning:: naming its absolute path, while a staging-only
# run retains silently — so on a LOCAL filesystem a failed branch write is recoverable rather than
# lost. On an EPHEMERAL CI runner the staging tree does not survive
# teardown, so the cloud recovery path is the UPLOADED WORKFLOW ARTIFACT the auto-review tier
# stages and uploads, which the trusted telemetry relay workflow
# downloads, validates, and pushes — not any on-disk copy the ephemeral runner cannot retain. This surface
# is still uncovered by this detector, and surfaced only by the helper's own
# stderr breadcrumb (which this step captures but does not grep). KNOWN LIMITATION (also deferred,
# review shadow pass): unlike the this-run-scoped no-inputs detector above, this grep
# runs against the combined capture (the targeted call's stderr plus the whole-tree
# discovery call's), so a
# persistently-failing LEFTOVER run directory elsewhere on the local tier can also match —
# the reflection below therefore does not assert the failure is scoped to this run.
if [ "$PERSIST_ERR_IS_DEVNULL" -eq 0 ] && grep -qE 'record not written|failed \(disk/permission\); not persisted for' "$PERSIST_ERR" 2>/dev/null; then
  "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "lib/efficiency-trace.sh --persist failed to derive/write an effectiveness record (see the record-derivation/write-failure breadcrumb above) — either this run's or an unresolved leftover run's on this host; some run's effectiveness telemetry under .prflow/logs/efficiency/ is missing" \
    || echo "::warning::phase-3.3: failed to record dropped-failed observability-gap reflection (record-write-failure case) on issue #$ISSUE_NUMBER; this run's effectiveness telemetry is lost AND its loss-record could not be written" >&2
fi
[ "$PERSIST_ERR_IS_DEVNULL" -eq 1 ] || rm -f "$PERSIST_ERR" 2>/dev/null
```


**Read the loop-verdict marker FIRST — it is the machine-readable channel, and the exact-wording headline match below is the version-gap fallback.** `review-and-fix` emits a producer-composed marker as **line 1** of its chat output, carrying both the loop's overall result and its coverage status in space-free tokens, so you need not string-match the human headline prose across a plugin-version boundary (the loop may be loaded from a different plugin version than this run). Before bucketing the verdict, write the skill's returned chat output — at minimum its **first line** — to `.prflow/tmp/rf-verdict-${ISSUE_NUMBER}.md` with the **Write tool** (the `.prflow/tmp/` precondition established in Phase 1.1 governs this scratch write; on its not-gitignored degraded arm, skip the marker read and go straight to the exact-wording fallback below), then read the marker:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/loop-verdict-marker.py read .prflow/tmp/rf-verdict-${ISSUE_NUMBER}.md
```

The helper inspects **line 1 only** (a marker a finding quotes deeper in the report is prose, not a stamp) and prints exactly one closed-vocabulary routing token, which decides both the verdict bucket and the coverage status:

- `CLEAN-FULL <result>` → a clean approve-family result **on a full-coverage shadow**: take the clean-completion path below and record `--record-review-coverage full attempted <roster> <checklist>`.
- `CLEAN-NOT-VERIFIED <result>` → a clean approve-family result whose shadow was **not verified**: record `--record-review-coverage not-verified attempted <roster> <checklist>` (the loop reports a shortfall on a fan-out it *did* dispatch), then take the not-verified branch below — which does **not** route unconditionally to clean completion.
- `AWUSF <coverage>` → `APPROVE WITH UNRESOLVED SHADOW FINDINGS`: take the AWUSF branch below.
- `REJECT` → take the REJECT branch below.
- `NO-MARKER` (line 1 is not a marker — an older loop that emits none) **or** `MALFORMED …` (a marker-shaped line 1 with a bad or out-of-vocabulary field) → the marker channel could not resolve the verdict: **fall back to the exact-wording headline match** described in the paragraphs below. Where the fallback resolves the coverage fact, record it exactly as the matching arm above; where it does not — and on any arm where the fact cannot be resolved at all — record `--record-review-coverage unestablished unestablished unestablished unestablished`, because collapsing an unresolved fact onto a clean value is the fail-open the terminal gate exists to close.

**Safe direction — non-negotiable.** Only `CLEAN-FULL` authorizes the clean, fully-covered completion path. A missing, malformed, or out-of-vocabulary marker is **never** read as a clean, fully-covered approval — it routes to the exact-wording fallback, and if that fallback cannot resolve the verdict either (an errored/garbled/absent headline), the run takes its existing **not-clean handling** (the Blocked path or the severity-aware exit below), never the clean-completion path.

After the skill completes with a clean approve-family verdict (`APPROVE`, `APPROVE WITH CAVEAT`, or `APPROVE WITH ADVISORY NOTES` — **not** `APPROVE WITH UNRESOLVED SHADOW FINDINGS`, which is handled separately below), flush any residual fixes. A run that does **not** return one of those three recognizable verdicts — it errors, can't run, or emits nothing parseable as a verdict — is **not** a clean completion: route it to the **Blocked path** below rather than letting an empty/garbled exit fall through to the flush. With `--push-each-iteration` the loop has already committed and pushed every iteration, so this is normally a no-op — guard the commit so an empty staging area doesn't error:
```bash
git add -A
git diff --cached --quiet || git commit -m "fix: address code review feedback for issue #$ARGUMENTS"
git push
```

**Stamp the machine-readable coverage record — on EVERY arm, before ticking the `review-and-fix` gate.** Run `workpad.py update $ISSUE_NUMBER --record-review-coverage <coverage> <dispatch> <roster> <checklist>`, deriving each operand from the loop-verdict marker read above:

- `<coverage>` — `full` (from `CLEAN-FULL`), `not-verified` (from `CLEAN-NOT-VERIFIED`), else `unestablished`.
- `<dispatch>` — `attempted` on both of those arms, `never` when this run positively knows no shadow fan-out was ever dispatched, else `unestablished`.
- `<roster>` — `complete` or `short`, else `unestablished`.
- `<checklist>` — `complete`, `skipped-intentional` (the shadow reference's `small_diff`+`config_only` skip, which is not a shortfall), `skipped`, else `unestablished`.

`<roster>` and `<checklist>` are this loop's own **comparison results**, not the roster itself — the gate never sees a roster and cannot re-derive one. Without this record the terminal `--status Complete` write is structurally refused as `[review-coverage-unestablished]`.

Then tick the `review-and-fix` gate: `workpad.py update $ISSUE_NUMBER --tick-progress "review-and-fix"`. **When the loop-verdict marker resolved above (`CLEAN-FULL`/`CLEAN-NOT-VERIFIED`), take the coverage status from it** and skip the headline harvest below; a free-text `--note` is optional colour, and the record is the source of truth. The exact-wording harvest that follows is the **fallback for an older loop that emitted no marker** (the `NO-MARKER`/`MALFORMED` arm). In that fallback, read these from the run's **verdict headline**: those exact literals are the `{shadow status}` parenthetical that review-and-fix renders on its APPROVE-family chat line (its Loop Exit "Verdict → chat output"), **not** from the report's `## Coverage` → `### Shadow agreement` section, which paraphrases the same fact in different prose (`Shadow ran with full reviewer coverage …` / `Shadow agreement NOT verified — {reason}`). Matching the headline token is exact; grepping the report body for the literal would miss. (Bucket the run by the loop's **verdict** first — this clean-completion path versus the AWUSF / REJECT / Blocked branches below — reading it from review-and-fix's **chat-output verdict line** (its Loop Exit "Verdict → chat output"). That line is the only surface carrying the *loop-level* verdicts: `APPROVE WITH UNRESOLVED SHADOW FINDINGS` is rendered there and **never** on the engine's report `## Verdict:` line, whose enum stops at the per-iteration engine verdicts (`APPROVE` / `APPROVE with notes` / `APPROVE WITH CAVEAT` / `APPROVE WITH ADVISORY NOTES` / `REJECT`) — so bucketing off `## Verdict:` would silently read an AWUSF run as a clean approve and ship it unreviewed. Only **after** the verdict has bucketed as clean approve-family, harvest the `{shadow status}` token from that same headline, so the AWUSF lost-write headline's own `… not verified …` prose can never be mis-harvested onto a clean run.) This is so a clean approve-family verdict that rode on a *not-verified* shadow (Step 2.6 outcome 3, a shadow fan-out shortfall the loop reports rather than elects) is visible in the workpad rather than silently consumed as if it had been fully audited. A `not-verified` record does **not** reach `Status: Complete` on its own: it reaches it only when Phase 4.3's disposition arm applies — a true, specific `--review-coverage-disposition shadow-coverage "<reason>"` over a record reading `dispatch=attempted`. A run that never dispatched the shadow has no disposition available (the gate refuses one as `[review-coverage-undispatched]`) and stops at a non-terminal or `Blocked` status naming budget exhaustion or whatever else prevented the fan-out (issue #1230). Contrast the bounded re-review below, which *does* require full coverage because it exists specifically to give an orchestrator hand-fix the independent pass it would otherwise never get.

**Tick the three Review extension rows on every Phase 3 exit** — this clean-completion path, the `APPROVE WITH UNRESOLVED SHADOW FINDINGS` and `REJECT` branches, the severity-aware soft-proceed and the Blocked path alike, because those three extensions loaded on all of them and an unticked row would assert the run never established their state. Apply the extension-row tick rule stated in `phase-1-setup.md` §1.3 to the review engine, the fix loop, and the code-review reception extensions:
```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER \
    --tick-progress "extension resolved: review engine" \
    --tick-progress "extension resolved: fix loop" \
    --tick-progress "extension resolved: code-review reception"
```
Accompany them with a `--note` stating how this run established the **review engine's** extension state: its ladder runs inside the fix loop's own turn sequence and is reached by a file read rather than a Skill-tool call, so there is no separate return to observe. Where that state cannot be established here, leave that row unticked and say so in the note — never tick it from recall.

**If the skill returns `APPROVE WITH UNRESOLVED SHADOW FINDINGS`** (the iteration-cap shadow pass surfaced new Important — never Critical — findings the loop could not address; see that skill's Step 2.6 outcome 2): this is **not** a clean approve. The findings came from a *full-coverage* shadow pass and are real, but they reach you only in chat + the report's `## Unresolved Shadow Findings` section (they do **not** flow through the Step-3 deferrals manifest, so Phase 4.0.5 will not file them). You may **not** silently hand-fix them and ship — any fix you apply to resolve them is itself unreviewed spec/code that no independent pass has seen, and shipping it is the unreviewed-final-edit gap the skill's caller contract forbids. Pick one:
1. **Fix + re-review (bounded once).** Apply fixes for the unresolved findings, commit (`fix:` prefix). **Before re-invoking, re-run the pre-invocation snapshot block from 3.3 above** (recomputes the repo-toplevel-anchored baseline of pre-existing per-iteration workpads) — the bounded re-review below is a **second, separate** inline `review-and-fix` invocation whose own Loop Exit can be dropped exactly like the first invocation's, so it needs its own fresh this-run baseline, not the first invocation's now-stale one. Then **re-invoke `review-and-fix` exactly one more time** (Skill tool, same `args: "--push-each-iteration --issue $ISSUE_NUMBER"`, the issue number substituted as its literal digits) so the fix delta gets an independent shadow/review pass, and **immediately after it returns, re-run the observability-persistence backstop block from 3.3 above** (the same persist-and-detect procedure — the idempotent Layer-3 persist call, the record-write-failure check, and the `dropped-failed` reflection) against the snapshot just taken — this second invocation's telemetry is protected exactly like the first invocation's, not left unguarded at this seam. **A clean approve-family verdict (`APPROVE` / `APPROVE WITH CAVEAT` / `APPROVE WITH ADVISORY NOTES`) on a full-coverage shadow clears the re-review** — read the re-review's own loop-verdict marker first exactly as above (a `CLEAN-FULL` token clears it; the `shadow agreed, full coverage` headline token is the older-loop fallback, same surface as the gate note above) — treat it exactly as a clean completion above (flush residual fixes **and** tick the `review-and-fix` gate), then continue. A clean verdict whose shadow was `not verified` does **not** clear it: the re-review exists precisely to give the hand-fix delta an *independent, full-coverage* pass. **Any other outcome routes through the severity-aware exit below — it does NOT automatically Block** (e.g. `APPROVE WITH UNRESOLVED SHADOW FINDINGS` again, `REJECT`, or a not-verified re-review). Do **not** loop a third time: trigger at most **one** orchestrator-initiated re-review, and that bound is what keeps this terminating. (The bounded re-review is an ordinary `review-and-fix` run, so if *it* defers a finding through the Step-3 deferrals manifest, that is the normal Phase 4.0.5 follow-up-issue channel and proceeds as usual — the "AWUSF findings do not flow through the deferrals manifest" rule above is about the *first* run's unresolved shadow findings, not the re-review's own deferrals.)
2. **Do not fix — route directly through the severity-aware exit below** (treat the unresolved findings as "unresolved after the cap").

**Severity-aware exit (do not fully block on diminishing-returns).** Reached when the bounded re-review did not return a clean **and** full-coverage verdict, or when you chose option 2. Two consecutive non-clean review passes (the capped first run + the bounded re-review) is **not**, by itself, grounds to abort the whole implement lifecycle — hard-blocking there discards the completed work and the review-ready PR over findings that are often advisory or over-graded. Instead, **classify the residual unresolved findings by severity** and route. **First ensure over-grade calibration has actually run on the residual:** the loop's **over-grade calibration gate** (`/prflow:review-and-fix` Step 2.6) — which *flags* a promote-path over-grade and *requires a recorded `severity-calibrated` technical evaluation*, never auto-demoting — ran on the residual **only if a bounded re-review actually ran** (option 1). On **option 2** (you chose not to re-review) and on a **first-run REJECT** (which may never have reached the shadow-promotion decision where the gate fires), the gate has *not* run — do **not** assume a finding was already calibrated; apply the same flag-and-evaluate calibration yourself before classifying, and grade conservatively (default to Critical-treatment on doubt). Then route:

- **A genuine unresolved Critical** — a real Critical (a data-loss/exploit/correctness break citing a concrete failing input), or an Important the orchestrator judges it cannot responsibly defer → **Blocked path** below (the human gate genuinely applies). The same applies to a re-review that errors / returns no parseable verdict at all (no findings to classify → fail closed), **and to any residual whose severity is missing, ambiguous, or cannot be confidently graded** — an ungradeable residual fails **closed** to the Blocked path, it does **not** fall through to soft-proceed.
- **Otherwise** — the residual is only advisory / Suggestion / `severity-calibrated`-down / a deferrable Important, *and every residual was confidently gradeable as non-Critical* → **Soft-proceed path**: do **NOT** block. The PR is review-ready, not auto-merged; the residual findings ride into the human's merge decision rather than aborting the run.

**Soft-proceed path.** Surface the residual findings durably and continue the lifecycle:
- Record each residual finding in the workpad: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "unresolved after bounded re-review (non-Critical, surfaced for human review): {finding}"` so it lands under `### ⚠️ Action required` (a non-empty reflection set keeps the run honest about what shipped unverified).
- Tick the `review-and-fix` gate and record `workpad.py update $ISSUE_NUMBER --tick-progress "review-and-fix" --note "review-and-fix did not reach a clean+full-coverage verdict; soft-proceeded on non-Critical residual findings (surfaced above) — PR is review-ready, not auto-merged"`.
- Continue to Phase 3.4 and Phase 4. The PR ships per the configured `implement_pr_state` with the residual findings documented in the workpad and (where the re-review wrote a deferrals manifest) carried into the PR body by Phase 4.0.5 / `/pr-description`. The human merger decides. Do **not** silently hand-fix the residual findings after this point — that is still the unreviewed-final-edit gap; they are *surfaced*, not *resolved*.

**Blocked path (genuine unresolved Critical only).** Reached from the severity-aware exit when a genuine unresolved Critical remains (or a verdict cannot be parsed at all — fail closed): `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "review-and-fix unresolved Critical (or unparseable verdict): {summary}"`, then emit the 👎 outcome reaction (see *Outcome reaction* in the Workpad Reference) and stop. A non-Critical residual is **not** a Blocked exit — it soft-proceeds per the path above.

**If the skill returns `REJECT`** (it could not converge — whether at the iteration cap or via a pre-cap convergence exit per that skill's Step 4.5, whose verdict is still REJECT): route through the **severity-aware exit** above — a REJECT whose unresolved triggers are all non-Critical/deferrable soft-proceeds (review-ready, surfaced), while a REJECT with a genuine unresolved Critical takes the Blocked path. Like AWUSF, a REJECT must **not** be silently hand-fixed and shipped as resolved; soft-proceed surfaces it for the human rather than resolving it.

### 3.4 Acceptance Criteria Gate

Before advancing to Phase 4, verify every **non-post-merge** checkbox in the workpad's `## Acceptance Criteria` section is ticked (`- [x]`). For each criterion, the verification is one of:

- a passing test in the diff that demonstrates the criterion,
- a documented manual check (recorded in the workpad notes via `--note` with the result), or
- a code reference (file:line) that satisfies the criterion.

**A verification-command criterion is satisfied only by an *in-env* observed pass — never by a CI conclusion. CI is the post-PR merge gate; it is never an in-run verification channel.** The scope is determinable, not a phrase to pattern-match: this rule fires for **any** acceptance criterion whose verification is *running a test/lint/build command* (the project's test suite passes, `shellcheck`/`ruff` pass, a `pytest`/build invocation, …). Run that command **in the run's own environment** and tick the criterion on the pass you observe there. Invoke the command by its **direct leading-token** form — the project's own test/lint command as the command's leading token, never behind a `bash <path>` wrapper (that wrapper is deny-floored and can never be granted) — which resolves because the project's verification commands are granted as direct-token forms and carry the exec bit + shebang that make the direct form runnable; this repository's concrete command name lives in the implement prompt extension. Do **not** wait for, poll, re-check, or cite CI to gate this criterion — the run neither waits for CI nor ticks anything on it.

**Single-flight coordination.** Resolve the gate with `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .verification_flight.enabled true` — it **defaults `true`**; only an explicit `false` disables it, and a resolver failure (rc≠0) warns and takes the default. When it resolves enabled, the inline review pass persists the flight handle + terminal evidence in the run's existing durable state (the workpad, and the fix loop's iteration record), and **re-anchors after nested work and compaction** — it re-reads the persisted handle rather than relaunching the command. **Re-anchoring recomputes the flight key from the *current* tree** (equivalently, re-reads via `status`/`wait` with a fresh `--current-checkout-file`): a bare re-read of the stored key *without* a fresh current-checkout is **not** a valid consume, because a tree change after a `passed` flight must yield either a key **miss** (the recomputed key names a different, absent flight → direct launch) or a `stale` read-transition — never a reused pass against a tree that has since moved. On `wait_expired`, take the existing Blocked path (below) without relaunch. **Carry the owner token across the calls:** `claim`, `mark-running`, the command, and `finish` are separate invocations and a shell variable does not survive between tool calls, so capture the token from `claim`'s JSON and keep it in context (or a run-scoped scratch file). A lost token fails CAS with `token_mismatch` and silently degrades the run to an uncoordinated direct launch — record that rather than ignoring it. **Record the candidate identity on the `claim`:** obtain the current-checkout candidate identity from the reception preflight — the granted `reception-record.py` prints a stdout JSON object carrying `candidate_identity` (the content-based git tree id `scripts/reception_identity.py` derives), the same value the completion gate re-derives — read that value from the tool output and set it as the declaration's `candidate_identity` field (write the declaration file with the value substituted — the same agent-level data-flow the label call sites use; do not rely on a shell capture the cloud matcher may deny). That gives the flight record a non-null identity the Phase 4.3 completion-evidence gate can bind against the final tree (a record with a null `candidate_identity` fails that gate). The `finish` summary file carries `command` (a nonempty string) and `exit_status` (integer `0` on a pass) with an empty `skipped_checks` list. **Produce the `checkout` fingerprint with `scripts/checkout-fingerprint.py`** (cloud vendored leading-token form `.prflow/vendor/prflow/scripts/checkout-fingerprint.py`), the single producer of the five-field checkout object: read its JSON output and set it as the `claim` declaration's `checkout` field (agent-level substitution into the declaration file, the same data-flow as `candidate_identity` above), and re-run it to write the `--current-checkout-file` fingerprint that every `status`/`wait` re-anchor reads — a bare re-read with no freshly-produced current-checkout is not a valid consume, and `status`/`wait` now enforce that AND themselves (a `passed` handle whose tree this read did not verify reports non-pass). The direct in-env command invocation itself is **unchanged** and still the leading-token authorized form (the project's own test command as the leading token, never behind a `bash <path>` wrapper).

- **In-env pass** — the command ran and passed in this environment. Establish the pass from what the command **reported**, never from an exit status you did not read: a command that prints a result tally is established from its **terminal summary line**, wherever the runner writes it (a summary on stderr rather than stdout is still this arm), and a process or wrapper exit status does not substitute for it; a command **silent on success** is established from its own **exit status**. Tick the criterion on that observed result (by its 1-based AC position): `workpad.py update $ISSUE_NUMBER --tick-ac-n {N} --note "verified in-env: '{cmd}' observed passing on $(git rev-parse HEAD)"`. The `[x]` asserts a result you *ran and saw* for *this* code.
- **In-env failure** — the command *ran and failed*. That is a real failure, **not** a deferral: do **not** tick and do **not** `(post-merge)` it. Fix it (a small follow-up per step 1 below), or take the gate's Blocked path — `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "AC unmet: '{cmd}' failed in-env on $(git rev-parse HEAD): {failing jobs}"`, emit the 👎 outcome reaction, and stop.
- **In-env run denied** — the direct-form command is **not granted** in this run's allowlist, so it was refused before it could run. This is a tooling gap, **not** a runtime-environment gap and **not** a CI-deferral: take the gate's **Blocked path** naming the config key that grants it — `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "AC unmet: verification command '{cmd}' is not granted in this run's environment (direct-form invocation denied) — add it to prflow_implement.allowed_tools (and prflow.allowed_tools for the command path) so the run can verify in-env, then re-run. CI is the post-PR merge gate, not an in-run verification channel, so this criterion is never ticked or deferred on a CI result"` — then emit the 👎 outcome reaction and stop. Never launder a denied verification command into a `(post-merge)` retag or a CI observation.

A bare direct **grep** of a few SKILL-contract pins is **not** a substitute for the suite — it confirms specific pins, not "the suite passes," so it can never by itself satisfy such a criterion.

Tick each criterion as you confirm it, **by its 1-based position** in the workpad's `## Acceptance Criteria` section (the list mirrors the issue's AC order): `workpad.py update $ISSUE_NUMBER --tick-ac-n {N}`. `--tick-ac-n` is repeatable and combinable, so the whole gate can tick every confirmed AC in one call (`--tick-ac-n 1 --tick-ac-n 2 …`) without hand-picking unique prose substrings — and a single bad index no longer discards the rest of the batch (it is reported as a volatile miss while the other ticks land). Cite the verification (a test, a file:line, or a prior note) in a `--note` on the same call where helpful.

**Consume the tick call's exit code — do not advance on the stdout body alone** (per the failure-isolation contract in the Workpad Reference). Because a volatile index miss still PATCHes the body and leaves the target AC `- [ ]`, an unchecked non-zero exit would let the gate pass with an in-scope AC still unticked — the exact silent failure the index contract elsewhere prevents. So after the tick call: if it exited **0**, the named AC rows are now `- [x]` and the gate proceeds; if it exited **non-zero**, read the stderr report naming each unresolved `--tick-ac-n`, re-resolve the position (a Phase 2.2.5 `--replace-acs-file` may have reordered/added/removed AC rows, so the criterion's section-scoped index can have drifted out of range or onto an already-ticked row — `--rewrite-ac` alone preserves order and count) and re-tick, and only when a criterion's tick genuinely cannot be resolved take the gate's Blocked path (step 4 below). The gate passes only when every non-post-merge AC row reads `- [x]` **and** the ticks that set it exited 0. **Read the row-state conjunct through `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py acs-gate $ISSUE_NUMBER`**, the degrading read. Its line-1 `source:` token and exit code route the gate:
- `source: workpad` (exit 0) — the workpad read cleanly; the rendered `## Acceptance Criteria` section (tick state and `(post-merge)` tags preserved, no criterion filtered, but **not a byte copy** — blank lines between items are dropped and a `* [ ]` bullet normalizes to `- [ ]`, so a diff against the stored section is not evidence the workpad drifted) is the authoritative row-state conjunct. The gate passes only when every non-post-merge AC row reads `- [x]` **and** the ticks that set it exited 0.
- `source: workpad-absent` (exit 2) — a clean absence (no workpad). This is the existing benign shape, **not** a transport failure: an **unestablished observation** — re-establish it (the workpad should exist by Phase 3); never let it stand as a passing gate.
- `source: workpad-read-failed` (exit 3) — the workpad read failed for a reason other than a clean absence (a GitHub fault confined to the comment-listing endpoint). The criteria are recovered from the **issue body** via `scripts/parse-acs.py` and printed, so you can still see the specification — but the workpad **tick state could not be established**, so this is likewise an **unestablished observation** that never passes the gate: re-establish the workpad read, or (if the outage persists) take the gate's Blocked path (step 4 below), never a silent pass.
- `source: unestablished` (exit 4) — the workpad read failed **and** the issue-body fallback was also unavailable. Nothing could be resolved; take the Blocked path (step 4).

Prefer `acs-gate` over a per-tick-call `--print-body`: this step makes per-criterion ticking the primary form, so no call is determinable as the last one in advance (a volatile miss produces a later one), and the flag would land on every call, restoring the full body cost, or on none, leaving the conjunct unobserved. **Any exit that is not 0 is a non-passing observation** — the defined degradation gives it a distinct label and, on a transport failure, the issue-body specification, but never a passing gate.

**On any run that issued a Phase 2.2.5 `--replace-acs-file` or a Phase 2.2.6 `--rewrite-ac`, run that same `workpad.py acs $ISSUE_NUMBER` read *before* this gate's first tick.** The two stale the inventory differently: `--replace-acs-file` can add, remove, or reorder rows, so the 1-based positions `--tick-ac-n` addresses shift; `--rewrite-ac` preserves order and count but replaces a row's label text in place, so it is the prose a `--tick-ac` substring matches that goes stale. Previously the mutating call's own echoed body was the view the gate *happened to* consume for the post-narrowing inventory; that call is silent by default now, and `acs` is the cheaper section-scoped channel the gate reads instead. Without this read the gate ticks from a stale inventory and collects volatile misses.

**Post-merge criteria are exempt from the gate.** A criterion whose checkbox line ends in `(post-merge)` (tagged during Phase 1.2) does not block. The orchestrator's responsibility for a post-merge criterion ends at "the code reaches the state where the live verification *becomes possible* to run." Leave the checkbox unticked — the merger will tick it after deploy via the `## Post-Merge Verification` section that `/pr-description` adds to the PR body in Phase 4.2. Do **not** invent evidence to tick a post-merge box during /prflow:implement; the live signal is what counts.

**Documentation-AC deferral (Phase-4.1-owned, and NOT the `(post-merge)` channel).** An acceptance criterion whose satisfaction is a *documentation edit that Phase 4.1's documentation subagent (which invokes the `prflow:docs` skill) owns* — a `docs/…` deliverable that pass authors, as opposed to a `skills/`/`scripts/`/`lib/`/test change this phase can make now — is **left unticked at this gate, recorded in a workpad deferral note naming the AC (`workpad.py update $ISSUE_NUMBER --note "3.4: doc-AC deferred to Phase 4.1: {AC text}"`), and does not block the gate's blocking check.** This is deliberately **not** the `(post-merge)` channel (reserved for genuinely-live verification the host can never run in-session): a doc-AC is fully dischargeable *in this run* by Phase 4.1, which authors the docs through its normal pass and then ticks the box — so it is neither retagged `(post-merge)` nor routed through rule 1's "do it now" channel below. Phase 4.1 **must** discharge each such deferred doc-AC and tick it (citing the deferral note) **before** the §4.3 terminal `--status Complete` write; an undischargeable doc-AC routes to the existing Blocked path, never to a silent Complete. This deferral mirrors Phase 4.0's recorded-note-plus-downstream-discharge idiom for 2.2.5-deferred criteria, and it does not weaken Phase 2's docs-ownership rule (docs stay Phase-4.1-authored) — it stops the gate from forcing doc authoring into Phase 3 to satisfy a criterion Phase 4.1 owns.

**A `(post-merge)` tag is permitted only when the criterion genuinely requires a runtime environment that does not exist during the implement run** — a live deploy target, a real third-party endpoint, a production data path, or similar. That is the *only* qualifying condition, and it is the observable test the gate applies: *would running this verification require an environment the orchestrator host can never be, no matter which tools were installed?* If yes, it is genuinely-live and `(post-merge)` is correct. If the verification could run on the orchestrator host given the right tools, it is **not** post-merge — even if those tools happen to be unavailable right now. Three cases therefore **never** qualify, and the gate must refuse the tag (or retag) for them:

- **Runnable-but-blocked (local tooling/environment gap).** A criterion you *could* verify on this host but can't right now because a command was denied, a build tool is missing, a helper won't spawn, or a restore errored. A tooling gap is not a runtime-environment gap — route it to the **Blocked path** (step 4 below: `--status Blocked`), which escalates to a human; never launder it into `(post-merge)`. (A denied *verification command* — the run's test/lint/build not granted in the allowlist — takes the same Blocked path, naming `prflow_implement.allowed_tools` as the remedy per the in-env-denied arm above. It never defers to a CI result: CI is the post-PR merge gate, not an in-run verification channel.)
- **Confirmation of a self-authored claim.** A criterion whose purpose is to confirm a behavioral claim the PR already asserts as already-true (in its description, its docs, or its code). It is runnable pre-merge **by construction** — the claim is *about the shipped diff* — so deferring it would defer the one check that could falsify the claim. Refuse the tag regardless of the stated reason: verify it now, or, if it genuinely cannot be satisfied, take the Blocked path.
- **Self-reconfiguration verification.** A criterion whose only unmet precondition is the orchestrator's own session/harness/account being in the configuration the diff just shipped — a `PreToolUse` hook the diff just registered now active, a flag/setting the diff just added now enabled. Because the host *can* become a fresh or child session with the change active, this verification **is runnable on this host and is never `(post-merge)`** — a fresh local session is something the host *can* be, so a "cleanest in a fresh session" rationale does not make it genuinely-live. Run and evidence it before the gate passes — by an **automated test that drives the now-active code path**, or by **spawning or reloading a separate session with the change active and recording the observed result** — or, if it genuinely cannot be run, take the **Blocked path** (step 4). Evidence already produced during development (a seam exercised while prototyping, a block confirmed live in-session before it was reverted) is **captured in the workpad and PR body rather than re-deferred** — do not let that evidence evaporate. The rule never mandates activating a blocking hook mid-run in the orchestrator's own session (that can break the run's own later tool calls); the safe evidencing paths above exist precisely so it never has to.

**Pre-merge probe contract (mandatory before any `(post-merge)` tag or retag exempts a criterion from this gate — whether tagged at Phase 1.2 parse time or retagged here).** The genuinely-live test above is *whole-criterion*: it asks whether the *verification* needs a runtime environment the host can never be. But a criterion that passes that test can still carry a **pre-merge-observable precondition that is already false** — and a `(post-merge)` tag means "the live verification genuinely cannot run until after merge, **and everything observable now has been checked**," not "the whole criterion is deferred unexamined." So before the tag lands, decompose the criterion and probe its observable preconditions:

1. **Decompose** the criterion into **(a) pre-merge-observable preconditions** — remote configuration state readable via a read-only `gh api` call (repo settings, a ruleset's required checks and bypass-actor list, branch protection), static properties of the shipped files (a workflow's declared `permissions:` / token wiring, a config key's presence), any fact the orchestrator host can observe now — and **(b) the genuinely-live residue** that only a merge / deploy / live CI run can produce.
2. **Probe every (a) precondition read-only**, using REST `gh api` reads (per the CLAUDE.md label/REST gotcha) and static greps of the shipped files. **The probe set MUST include any failure mode the linked issue's Potential Gotchas or Implementation Notes names for that criterion's mechanism** — the issue often already names the exact pre-merge-observable state that later detonates (the Potential Gotchas named the ruleset bypass-actor gap that a later PR then hit post-merge on all 5 push attempts). Keep the obligation **bounded** to the deferred criterion's own named mechanism plus those issue-named failure modes — it is not open-ended research.
3. **Record each probed precondition, the probe command, and its observed result in the deferral `--note`** — with the probe's timestamp, since pre-merge state can drift before merge — or, when the observable set is genuinely empty, the explicit finding `"no pre-merge-observable precondition"`. An empty set is legal and recordable; a *silent* deferral carrying no probe record is the defect.
4. **An observed result showing the deferred live verification cannot succeed as shipped routes to a pre-merge fix or the Blocked path (step 4 below) — never a deferral.** A probe that observes a precondition is already false is a blocker you can fix now, not a live check to punt.
5. **A denied probe (classifier / sandbox) is recorded as denied and the deferral proceeds.** A denial is *not* an observed-false result, so it never blocks a genuinely-live deferral — this must not recreate the runnable-but-blocked launder in reverse. **Tell the two apart by whether the probe obtained a definitive answer about the precondition — never by the raw exit status alone.** Classify *denied* only when the state could not be read at all: the classifier / sandbox refused the command, the network failed, or the API returned an auth/permission error (401/403 the token can't satisfy) so the config is unreadable. Everything that *did* obtain a definitive answer is an **observed** result routed by step 4 — and that explicitly includes a non-zero `gh api` exit that carries one: an HTTP **404** ("the ruleset / branch-protection object is absent") and a **200 with falsy data** (an empty required-checks array, an absent bypass actor) are **observed-false**, not denials. Do not read "`gh api` exited non-zero → the probe never ran → denied → proceed": a 404 is the object being observably absent, which is exactly the precondition failure, and laundering it into a denial is the reverse launder this rule forbids.
6. **A passed probe never ticks the AC box.** A passed probe only *narrows* the deferral to the genuinely-live residue; the live signal still owns the tick and the genuinely-live residue check always remains. The checkbox stays unticked either way.

This contract is the single source of truth for both the Phase 1.2 tag-time path (`skills/implement/phases/phase-1-setup.md`) and the retro-tag path below.

**Do not launder a runnable check into `(post-merge)`** — a runnable-but-blocked tooling gap (Blocked path naming `prflow_implement.allowed_tools`), a self-authored-claim confirmation, a self-reconfiguration verification (run-and-evidence), or an `observed-cannot-succeed probe: **never** a deferral` each routes to the Blocked path (step 4) per the three never-qualifying cases and the probe contract above, and a check runnable on this host with the right tools is not live; a denied probe (unlike an observed-false one) does not block a genuinely-live deferral.

If the workpad's Acceptance Criteria section reads `_(none provided in issue body)_`, the gate passes trivially.

The gate applies only to criteria currently in the workpad's `## Acceptance Criteria` section. If you scoped down via the 2.2.5 rule, deferred criteria live in the workpad notes and are **not** gated here — they will be carried into a follow-up issue in Phase 4.0.

If non-post-merge criteria remain unchecked after Phase 3.3:

1. If a criterion is satisfiable with a small follow-up edit, do it now (still inside Phase 3) — write the code, run tests, commit (using the `fix:` prefix), tick the box, and continue. **This "do it now" channel excludes documentation authoring owned by Phase 4.1** (a `docs/…` deliverable the documentation subagent authors by invoking the `prflow:docs` skill): a doc-AC is deferred to Phase 4.1 per the *Documentation-AC deferral* rule above, never written here in Phase 3 to tick the box.
2. If a criterion's *literal text* is now stale because /simplify or /prflow:review-and-fix refactored the structure (e.g. renamed jobs, merged files), but the *underlying behavior* the criterion verifies is preserved in the diff, apply **2.2.6** now: rewrite the AC text in the workpad with a `--note` paper trail, then tick the box.
3. If a criterion is genuinely outside this PR's scope and you missed it during 2.2.5, **go back to 2.2.5 now**: move the item to the workpad notes (`--note`) as deferred, rewrite the Acceptance Criteria section, PATCH, and re-run this gate against the narrowed set. Then continue to Phase 4.
4. Otherwise — i.e. the criterion is in-scope but you cannot satisfy it AND it is not tagged `(post-merge)` — `workpad.py update $ISSUE_NUMBER --status Blocked --reflection-kind blocked --reflection "AC unmet (in-scope, not post-merge): {AC text}"`, then emit the 👎 outcome reaction (see *Outcome reaction* in the Workpad Reference) and stop the run with a clear report to the user. Do **not** advance to Phase 4 with unmet in-scope, non-post-merge criteria.

Once the gate passes (every non-post-merge AC ticked), tick the gate **and its parent phase** in the workpad: `workpad.py update $ISSUE_NUMBER --tick-progress "acceptance-criteria gate" --tick-progress "**Review**"`.

(A criterion the orchestrator can't satisfy may be retroactively tagged `(post-merge)` **only if it is genuinely-live by the three never-qualifying cases above** (not a runnable-but-blocked tooling gap, a self-authored-claim confirmation, or a self-reconfiguration verification needing an active session). **Before the retag lands, run the Pre-merge probe contract above** — decompose the criterion, probe every pre-merge-observable precondition read-only (folding in any failure mode the linked issue's Potential Gotchas / Implementation Notes names for its mechanism), and record each probed precondition, the probe command, and its observed result in the retag `--note` — or the explicit finding `"no pre-merge-observable precondition"`. A probe whose observed result shows the deferred live verification cannot succeed as shipped routes to a pre-merge fix or the Blocked path — **never** this retag. When it qualifies and every probe passes (or is recorded denied), retag with `workpad.py update $ISSUE_NUMBER --rewrite-ac "{full old criterion text, verbatim}" "{full old criterion text, verbatim} (post-merge)" --scope-decision-rewritten <this PR's number> "{full old criterion text, verbatim}" "{full old criterion text, verbatim} (post-merge)" --note "retro-tagged as post-merge (genuinely-live): {the runtime env it requires}. Pre-merge probes: {precondition → command → observed result, each}; or 'no pre-merge-observable precondition'"` — the `--note` rationale is **mandatory**: `workpad.py` structurally aborts a `--rewrite-ac` that appends the `(post-merge)` tag without one, so the retag is always a recorded, auditable claim. Then let it pass the gate. The passed probes narrow the deferral to the genuinely-live residue; they do **not** tick the AC box. If it fails that genuinely-live rule, do **not** retag; take the Blocked path (step 4 above) instead.)

**This retag is a text-changing writer exactly like §2.2.6, so it emits its own `--scope-decision-rewritten` record in the same call — with this PR's real number, never `pending`, since the PR exists by §3.4.** Both flags take the criterion's **full** text here (never a fragment) — the review engine matches the `--scope-decision-rewritten` OLD value by whole-criterion equality, so a fragment produces a record that matches no criterion and therefore covers none. The record is **defensive, not load-bearing** for the divergence report: this retag only *appends* ` (post-merge)`, and the engine's `normalize_criterion` strips exactly that tag before comparing, so the retagged criterion normalizes back to its original text and is neither an unexplained text change nor a dropped criterion even with no record at all. It is emitted for consistency with §2.2.6 — every text-changing writer leaves a record, so the audit trail has no writer-shaped hole and a future change to what this step rewrites cannot silently become invisible. What *does* depend on timing: the retag runs after §3.3 and before the post-push standalone review, so the auto-review tier reads a section this step has already edited.

### 3.5 Tick Phase-3-completed Plan steps

Two kinds of `## Plan` step routinely **complete in Phase 3**, not Phase 2, so the Phase 2 "tick plan steps as they complete" loop never reaches them — leaving their rows falsely `- [ ]` on a finished run. Tick each **at the point its work completes here**, so the terminal Phase 4.3 `--status Complete` self-record gate's non-blocking `## Plan` warning fires only on a genuinely dropped/superseded step (that gate: a non-post-merge unticked **AC** row hard-fails the Complete write, while an unticked **Plan** row only warns — see the finalize call in Phase 4.3):

- **The versioning step** (where repo policy declares the version change — e.g. this repo's changeset workflow, per `.prflow/prompt-extensions/implement.md`, applied after the draft PR exists but before the review pass): once the artifact that step produces is committed — for a changeset-based repo, the `.changeset/*.md` file; for a repo that still bumps in-PR, the version bump + matching `CHANGELOG` entry — tick its Plan row — `workpad.py update $ISSUE_NUMBER --tick-plan "{substring of the versioning plan step}"`. The Phase 3 review gate then fails an engine-surface change that carries **no** such versioning artifact (for this repo, a missing changeset file) and passes one that does.
- **The project's own final verification run** (the full test/lint suite the repo runs before it calls a branch done): once you have observed it green **in-env** (the direct-form command granted via `prflow_implement.allowed_tools` — never a CI conclusion), tick its Plan row — `workpad.py update $ISSUE_NUMBER --tick-plan "{substring of the final-suite plan step}"`. A denied verification command takes the Blocked path (§3.4), not a CI deferral.

Only tick a step your plan actually lists (a `--tick-plan` that matches nothing is a volatile miss); if this run's plan carries no such step — a consumer repo with no version policy, say — skip its tick. Consume the tick call's exit code as everywhere else (a non-zero exit means the substring did not resolve to exactly one unticked row — re-resolve and re-tick).

**⚠ You are NOT done. PR is still a draft and needs documentation and a proper description. Proceed to Phase 4.**
