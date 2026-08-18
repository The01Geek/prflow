<!-- prflow:implement-ref step=4.0.5 file=skills/implement/references/deferred-review-findings.md start -->

### 4.0.5 File Follow-Up Issues for Deferred Review Findings

If Phase 3.3's /prflow:review-and-fix run emitted a deferrals manifest, file follow-up GitHub issues for those findings now and update the manifest in place with the assigned issue numbers + deterministic deferral IDs. Phase 4.2's /pr-description run will then surface them in the PR body as a Scope-Acknowledged Findings block that /prflow:review's verdict matcher honors.

**Manifests are run-scoped** (`.prflow/tmp/review/<slug>/<run-id>/deferrals.json` — see that skill's "Pre-mapping: Widens-surface guard + deferrals manifest" section for what's in it). A single /prflow:implement run can produce **two** of them: Phase 3.3's first /prflow:review-and-fix run and its bounded re-review both run on the same PR with distinct run-ids. Reading one fixed path would miss the other run's deferrals. So **merge every run-scoped manifest into one slug-level aggregate** before filing, then file from the aggregate. The aggregate is the single path /pr-description reads in Phase 4.2.

Skip this step if no run-scoped manifest exists or all are empty.

```bash
PR_NUMBER=$(gh pr view --json number --jq '.number')
SLUG_DIR=".prflow/tmp/review/pr-${PR_NUMBER}"
AGG="${SLUG_DIR}/deferrals.json"   # slug-level aggregate the consumers read; distinct from the per-run files
# A branch-mode run writes its manifest under the sanitized branch slug, not `pr-<N>/`, so
# searching only `pr-<N>/` misses its deferrals — discover under BOTH slug dirs. The aggregate
# stays at `pr-<N>/deferrals.json` (the path /pr-description reads in Phase 4.2). Read the
# branch name ONCE (reused for slug + breadcrumb) so the two reads can't disagree if HEAD moves.
CUR_BRANCH=$(git branch --show-current)
BRANCH_SLUG=$(printf '%s' "$CUR_BRANCH" | tr '/' '-' | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9._-')
# tr-dependence guard: BRANCH_SLUG keys a search dir and is derived through
# `tr`. A non-empty branch yielding an EMPTY slug (either `tr` missing/degraded, or a working
# `tr` dropped every char as all-non-`[a-z0-9._-]`) falls back to pr-<N>-only search; the
# breadcrumb names both candidate causes so an operator isn't misdirected. An EMPTY branch name
# is the benign detached-HEAD case (pr-<N>-only is correct, no breadcrumb). Best-effort; never blocks.
[ -z "$BRANCH_SLUG" ] && [ -n "$CUR_BRANCH" ] && echo "devflow: current branch produced an empty slug (either 'tr' is missing/degraded on PATH, or the branch name is composed entirely of characters dropped by the [a-z0-9._-] filter); falling back to pr-<N>-only deferral discovery (a current-branch-mode run's manifest may be missed)" >&2
BRANCH_DIR=".prflow/tmp/review/${BRANCH_SLUG}"
# Only add the branch-slug dir when non-empty AND distinct from pr-<N> (avoid searching twice).
SEARCH_DIRS="$SLUG_DIR"
[ -n "$BRANCH_SLUG" ] && [ "$BRANCH_DIR" != "$SLUG_DIR" ] && SEARCH_DIRS="$SLUG_DIR $BRANCH_DIR"
# $SEARCH_DIRS is path-safe, so its unquoted word-split into the helper's argv is safe.
# Discovery is delegated to a stdlib-only Python helper that searches EACH root independently
# and preserves discovery status through its EXIT CODE, so a failed search is observable instead
# of masked as a clean no-match (which would strand acknowledged deferrals). Do NOT derive
# partial-from-failed inside the fence by testing whether the capture is non-empty: a PARTIAL run
# whose surviving roots hold no manifest prints nothing, so that reading routes it to `failed`,
# the filing guard below refuses it, and a prior run's unfiled aggregate is never retried. Every
# non-zero status is `degraded`, classified after the fence from the helper's own markers, which
# reach this fence's tool result unchanged. Do NOT capture the status into a variable a later
# statement reads either: a runner that strips cross-statement variables leaves it empty and every
# healthy discovery routes to the degraded arm. Do NOT add a `2>file` stderr capture — the harness
# refuses an output redirection and returns NO OUTPUT AT ALL, losing the whole fence.
# DISCOVERY_STATE is initialized empty BEFORE the statement (sentinel-operand rule); a matcher
# refusal of the capture (treat NO OUTPUT AT ALL as a possible denial, never an empty value)
# leaves it empty, printed as discovery=[] and routed fail-closed.
DISCOVERY_STATE=""
if MANIFESTS=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/discover-deferral-manifests.py $SEARCH_DIRS); then
    DISCOVERY_STATE=ok
else
    DISCOVERY_STATE=degraded
fi
# The helper writes its `devflow: discovery roots: …` echo and any partial/failure detail to stderr
# on every discovery run, so read both from THIS fence's own tool result — nothing writes them to a
# file. A `partial` or `failed` discovery is recorded on the workpad after the fence, quoting that
# observed stderr (see *Recording discovery and filing outcomes* below).
if [ -n "$MANIFESTS" ]; then
    # Merge the deferrals[] arrays across runs. The dedup key mirrors file-deferrals.py's
    # _compute_id payload — (file|symbol|kind|summary.strip()), each field defaulted to "" — so a
    # finding deferred in both runs collapses to one row and a null field never errors the concat.
    # Header fields come from the first input. The merge passes whole objects through unique_by, so
    # a `settled-by-disclosure` entry's `category` and `disclosure` object survive unchanged.
    # Idempotent re-runs: feed any prior hydrated aggregate FIRST so its `follow_up` entries win
    # the dedup; otherwise a re-run rebuilds $AGG from raw manifests (no follow_up), wiping the
    # hydration so file-deferrals.py re-files duplicates. Write via temp so reading $AGG is safe.
    PRIOR=""; [ -s "$AGG" ] && PRIOR="$AGG"
    if "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/run-jq.sh -s '.[0] as $f | {schema_version:$f.schema_version, pr_branch:$f.pr_branch, base_branch:$f.base_branch, generated_at:$f.generated_at,
        deferrals: ([.[].deferrals[]] | unique_by((.file // "") + "|" + (.symbol // "") + "|" + (.kind // "") + "|" + ((.summary // "") | gsub("^\\s+|\\s+$";"")))) }' \
        $PRIOR $MANIFESTS > "${AGG}.tmp"; then
        mv "${AGG}.tmp" "$AGG"
    else
        # jq failed (malformed manifest, schema drift): keep any prior hydrated $AGG
        # intact, do NOT file from a half-merged temp, and surface the gap rather than
        # silently falling through to the filing guard with a stale aggregate.
        rm -f "${AGG}.tmp"
        "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0.5 deferrals merge (jq) failed over: ${MANIFESTS}; deferrals NOT filed this run — inspect the run-scoped manifests."
        AGG=""   # make the filing guard below unambiguously false
    fi
fi
# Initialize the sentinel's operands OUTSIDE the aggregate guard, since the sentinel reading them
# is outside it too — every field must be produced on every path, including the clean no-op that
# never enters the guard. `${FILED_NUMBERS//$'\n'/ }` cannot carry a `:-` default, so an UNSET
# FILED_NUMBERS aborts the whole `echo` under `set -u` on bash 5 — no sentinel prints and the
# reader fabricates a harness-denial reflection on a clean run. Init here makes the sentinel unconditional.
FILED_STATE=""
FILED_NUMBERS=""
if { [ "$DISCOVERY_STATE" = ok ] || [ "$DISCOVERY_STATE" = degraded ]; } && [ -n "$AGG" ] && [ -s "$AGG" ]; then
    # Guard on file-deferrals.py's OWN status inline — never capture that status into a variable a
    # later statement reads, which a runner that strips cross-statement variables leaves empty so
    # every outcome routes to one arm; and never a `2>file` capture, which the harness refuses,
    # returning no output at all. rc 0 = at least one group filed, `--dry-run`, or every survivor
    # settled-by-disclosure. Every non-zero status is `unclassified`: rc 2 alone is SHARED by five
    # conditions — two benign (no deferrals, already filed) and three genuine input errors — whose
    # only distinguisher is the message text, so no arm inside this fence can tell them apart, and
    # rc 1 (nothing filed) needs the same text to say why. The classification happens after the
    # fence from the observed stderr, and anything unrecognised stays a failure, so a genuine input
    # error can never be read as one of the benign cases. FILED_STATE names WHICH arm ran and
    # defaults to `failed`; without it every non-filing state prints `filed …=[]` like the one real
    # capture gap, so the reader's "hydrated + no numbers ⇒ gap" rule fires on all of them and
    # fabricates a reflection claiming issues were filed and lost.
    FILED_STATE=failed
    FILED_NUMBERS=""
    if FILED_OUT=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/file-deferrals.py \
        --source-issue $ARGUMENTS \
        --pr "$PR_NUMBER" \
        --manifest "$AGG"); then
        FILED_NUMBERS="$FILED_OUT"
        FILED_STATE=filed
    else
        FILED_STATE=unclassified
        echo "devflow: file-deferrals.py exited non-zero — classify this fence's stderr per the filing routing in Phase 4.0.5" >&2
    fi
    # Record the filed numbers AND print them IN THIS FENCE — the only place FILED_NUMBERS
    # exists. A shell variable does not survive into a later separate command on the cloud runner,
    # so reading it in a LATER fence sees it empty, prints `[]`, and labels NOTHING. Printing here
    # is the only channel carrying the numbers to the agent-level label calls below.
    if [ -n "${FILED_NUMBERS:-}" ]; then
        NUMBERS_CSV=$(echo "$FILED_NUMBERS" | tr '\n' ',' | sed 's/,$//' | sed 's/,/, #/g')
        "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --note "Filed follow-up issues for deferred review findings: #${NUMBERS_CSV}"
    fi
fi
# UNCONDITIONAL sentinel — OUTSIDE the aggregate guard, so it prints on every path, making three
# otherwise-indistinguishable states distinct: no line => refused; manifest=[] => nothing to file
# (clean no-op); manifest=[…] with an empty filed list => the real capture gap.
# Print the manifest STATE (from the same [ -s "$AGG" ] predicate the filing guard uses), not the
# raw path, or a no-deferrals run reads as hydrated and misroutes to the capture-gap exit.
# Print the numbers RAW — NUMBERS_CSV is display-formatted for the workpad
# note (`201, #202`), so it is not what to substitute into the per-issue calls. # pruned-path-ok: illustrative bad-substitution example, not a citation
# `pr=` carries the PR_NUMBER capture's outcome, so a `gh pr view` returning nothing is observable
# rather than masquerading as the clean no-op state on a run that had deferrals to file.
# The `\n`→space fold is a BASH BUILTIN, not `tr`: this emitted field is one the reader ROUTES on,
# so it must not be derived through a non-preflight PATH tool.
MANIFEST_STATE=""; [ -n "${AGG:-}" ] && [ -s "${AGG:-}" ] && MANIFEST_STATE=hydrated
echo "phase 4.0.5 filing fence ran; pr=[${PR_NUMBER:-}] discovery=[${DISCOVERY_STATE:-}] manifest=[${MANIFEST_STATE}] filing=[${FILED_STATE:-}] filed deferred-finding issues=[${FILED_NUMBERS//$'\n'/ }]"
```

Recording discovery and filing outcomes. The fence captures no stderr to a file (the harness refuses an output redirection and returns no output at all), so read the helpers' stderr in the fence's own tool result and make the matching record below — an unrecorded partial discovery or unrecognised filing failure strands acknowledged deferrals with no durable trace. Substitute the stderr you observed for each `<observed …>` placeholder, verbatim, or the literal `stderr=empty` when the invocation showed none: a harness refusal produces no stderr at all, and a fabricated quote there would misattribute the cause.

- `discovery=[degraded]` — the discovery statement exited non-zero. The fence does not tell the two shapes apart, so classify by the marker in this fence's observed stderr and record exactly one; an unrecognised shape takes the failed arm, so a genuine failure can never be recorded as the milder one:

  - `devflow: discovery partial:` → at least one root failed and at least one did not; the clean roots' paths are still filed from:

    `<skill-dir>/../../scripts/workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0.5 deferral discovery was PARTIAL — at least one candidate root failed traversal: <observed discovery stderr>; filing proceeds from the roots that did not fail (\`ok\`/\`absent\`; an \`absent\` root contributes nothing). The failed root's deferrals are NOT filed this run, and once this run hydrates the aggregate they cannot be auto-filed by a later re-run (file-deferrals.py refuses a mixed hydrated/raw manifest) — recover them by filing from that root's run-scoped manifest manually."`

  - any other stderr, including none at all → every root failed, the invocation was refused, or the shape is unrecognised. Name the persisted aggregate path so an operator can re-trigger Phase 4.0.5:

    Read the sentinel's `filing=` field before choosing between the two texts below — the filing guard admits `degraded`, so a total discovery failure over a persisted prior aggregate still files, and the "nothing was filed" text would then contradict the same run's own sentinel and invite a duplicate-filing retry.

    - `filing=` anything other than `filed`: `<skill-dir>/../../scripts/workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0.5 deferral discovery FAILED (every candidate root failed traversal, the discovery command produced no output at all — a likely harness denial — or its stderr carried no recognised discovery marker): <observed discovery stderr>. No deferrals were filed this run; any persisted aggregate at .prflow/tmp/review/pr-<N>/deferrals.json was left intact — re-trigger Phase 4.0.5 deliberately to recover its deferrals."`
    - `filing=[filed]`: `<skill-dir>/../../scripts/workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0.5 deferral discovery FAILED (<observed discovery stderr>), but a previously persisted aggregate was still on disk and WAS filed from this run — see the sentinel's filed issue numbers. This run's own deferrals were not discovered; do NOT re-trigger to recover them, which would re-file the aggregate that already landed."`

- `filing=[filed]` whose stderr contains `were dropped from manifest` — `file-deferrals.py` exits 0 even on partial success, so record the drop or those findings vanish without reaching the PR's Scope-Acknowledged block:

  `<skill-dir>/../../scripts/workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "file-deferrals.py filed partially (rc=0): <observed filing stderr>; dropped groups will NOT appear in the PR's Scope-Acknowledged Findings block."`

- `filing=[unclassified]` (the state the fence sets on any non-zero status) — classify by the message text and record exactly one; never silently pick one of the benign two when the shape is unrecognised:
  - `already has follow_up` → the idempotent state: `<skill-dir>/../../scripts/workpad.py update $ISSUE_NUMBER --note "Deferrals already filed on a prior run (idempotent re-run) — nothing new to file; the hydrated aggregate stands."`
  - `no deferrals` → the none (nothing-to-file) state: `<skill-dir>/../../scripts/workpad.py update $ISSUE_NUMBER --note "Aggregate held no deferrals to file — nothing to do."`
  - any other stderr → an unrecognised shape, recorded as a failure: `<skill-dir>/../../scripts/workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "file-deferrals.py exited non-zero with an unrecognised message: <observed filing stderr>; no follow-up issues filed this run."`
  - The `idempotent` and `none` records supersede the sentinel's `filing=[unclassified]`, which is what the fence prints before the classification exists.

- `filing=[failed]` — the defensive initial value, which the fence's own `if`/`else` is total over and therefore always overwrites; a harness refusal kills the whole fence, so no sentinel prints at all and that case takes the no-sentinel exit instead. Observing this value therefore means the fence's control flow was violated in a way this reference does not model: record it as unexplained rather than as a known outcome — `<skill-dir>/../../scripts/workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0.5 printed filing=[failed], a value the fence's own routing should have overwritten: <observed filing stderr>; treat the filing outcome as unestablished and inspect the fence's output before assuming anything was or was not filed."`

The helper groups manifest entries by `file` (one issue per source file), files each issue with a repo-agnostic title/body template (`<area>: deferred review findings in <file> (carried from #<source_issue>)` and a body containing the verbatim findings plus the `PR #<pr_number>` substring that the verdict matcher's mutual-cross-link guard validates against), then rewrites the manifest in place with `id: dfr-<6-hex>` (deterministic hash of `file + symbol + kind + summary`) and `follow_up: {issue, url, filed_at, filed_by}` populated per entry. Filed issue numbers are printed to stdout, one per line.

Failure mode: if `gh issue create` fails for a particular file-group, that group's entries are dropped from the manifest entirely — no fake deferral can downgrade a future review. The helper exits 0 as long as at least one group succeeded. Capture stderr in your `Devflow Reflection` notes if anything was dropped.

Foreclosure passthrough. A `settled-by-disclosure` entry files no follow-up issue — the shipped disclosure is its deliverable — yet still survives into the rewritten aggregate unchanged (with a `dfr-` id assigned, no `follow_up`, its `category` and `disclosure` object preserved) so `/pr-description` can render it and `/prflow:review` can honor it. Consequently a manifest whose entries are all foreclosures files zero issues and still exits 0 (printing no issue numbers), rewriting the aggregate; the `FILED_STATE=filed` arm handles it benignly (empty `FILED_NUMBERS`). This is the all-foreclosed exit-0 arm — do not treat an exit-0 with no printed issue numbers as a failure.

The fence printed the filed issue numbers (`filed deferred-finding issues=[...]`) from inside the filing fence because `FILED_NUMBERS` does not survive into a later separate command on the cloud runner — reading it from a later fence would see it empty and conclude "nothing was filed" on a run that filed issues, labelling none. Read the printed list from that tool result; it is the only channel carrying the numbers to the agent-level label calls below.

Then apply the configured `deferred.labels` to each filed issue — the same resolve/normalize idiom as Phase 4.0 (default `PRFlow,Deferred`; empty/whitespace → none). `file-deferrals.py` itself stays out of config-reading (config is resolver territory — read through `config-get.sh`, not re-parsed ad hoc); the skill owns labeling, best-effort and post-filing, so a label hiccup never unwinds an already-filed issue.

**Cloud-emission discipline (label helpers): iterate at the agent level, never in a shell loop or a capture — identical to Phase 4.0, see the *Cloud command-shape discipline* section in `skills/implement/SKILL.md`.** The cloud implement matcher denies a `for`/piped-`while read` loop wrapping a label helper and a `VAR="$(label-helper …)"` capture; the `config-get` capture below rests on the same unproven inference, so it fails closed on no output. First resolve and print the clean label list (a shell variable does not survive into a later separate command on the cloud runner, so printing is how you read the value for the per-issue calls):

```bash
# The `if !` reads config-get's OWN exit status inline and is exempt from set -e; the default arg
# covers the SOFT paths (missing file / unset key → exit 0); only the HARD path (rc≠0 — corrupt
# config.json / missing python3) leaves DEFERRED_LABELS empty AND a breadcrumb.
if ! DEFERRED_LABELS=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .deferred.labels PRFlow,Deferred); then
    DEFERRED_LABELS=""
    "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0.5 could not read deferred.labels (config-get rc≠0 — corrupt config.json or python3 missing); deferred review-finding issues filed WITHOUT labels."
fi
# GRANTED heads only — `paste` is granted in no allowlist, so a `| paste -sd, -` tail makes
# the whole pipeline refused and the capture silently empty (see Phase 4.0's note).
CLEAN_DEFERRED_LABELS=$(echo "$DEFERRED_LABELS" | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' | grep -v '^$' | tr '\n' ',' | sed 's/,$//')
# Print BOTH, for the same reason Phase 4.0 does: an emptied normalizer must not be
# indistinguishable from an empty config.
echo "deferred.labels raw: [$DEFERRED_LABELS]"
echo "deferred labels to apply: [$CLEAN_DEFERRED_LABELS]"
```

A non-empty `raw` with an empty `to apply` is a broken normalizer (a missing/denied `tr`/`sed`/`grep`), not an empty config — record it and apply nothing: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0.5 resolved deferred.labels to a non-empty value but the normalizer produced an empty list (a missing/denied tr|sed|grep in the pipeline); deferred review-finding issues were filed WITHOUT labels."`

The exits before any label is applied are the same fail-closed set Phase 4.0 carries. Most are read off the sentinel the filing fence prints unconditionally; the label-config exit off the separate `deferred labels to apply:` line the config fence prints. Some bullets below are *qualifiers* rather than exits — the `discovery=[degraded]` one (applies nothing on its own) and the Cwd-drift suspicion one (a heuristic qualifying the clean-no-op arm):

- **No `phase 4.0.5 filing fence ran` sentinel at all, OR the sentinel present with `discovery=[]`.** The fence was refused, not answered — do **not** read it as "nothing was filed". A refusal or non-execution of the discovery statement lands as `discovery=[]` on the sentinel or as no sentinel at all — and it does not matter which; both take this exit. Record it and apply nothing: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0.5's filing fence produced no sentinel at all, or a sentinel carrying discovery=[] (the discovery statement was refused or never ran) — likely a harness denial, not an empty aggregate; no deferred review-finding issues were filed or labelled this run."`
- **Sentinel present, `pr=[]`** — the `gh pr view` read ran and yielded no number, so every path built on it (`SLUG_DIR`, the manifest discovery, `AGG`) resolved against a truncated slug and found nothing. **Do not read the `manifest=[]` that follows it as the clean no-op**: no manifest was even looked for at the right path, so this run's deferrals (if any) were neither filed nor labelled. Record it and apply nothing: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0.5 could not resolve the PR number — the gh pr view read yielded no value; no deferrals manifest could be located, so no deferred review-finding issues were filed or labelled this run."` (A matcher *denial* of that capture lands in this state or in the no-sentinel exit above — and it does not matter which: both record `dropped-failed` and apply nothing, so this routing does not depend on a denial granularity no probe row establishes.)
- **Sentinel present with `discovery=[degraded]` — a qualifier on the arms below, not an exit:** the discovery statement exited non-zero. Classify and record it per *Recording discovery and filing outcomes* above — the fence itself writes no reflection. Whether any deferrals were filed is read off `manifest=` and `filing=` per the arms below: a degraded run with `manifest=[]` or an empty `filing=` filed nothing, and a degraded discovery does not by itself imply any manifest was found. Apply labels only if `filing=[filed]` with a non-empty filed list, per the arms below.
- **Sentinel present with `discovery=[ok]`, `pr=[<n>]` and `manifest=[]`** — no hydrated aggregate (either there were no deferrals this run, or the merge produced nothing), so nothing was filed and there is nothing to label: apply nothing. This is the clean no-op (the `discovery=[ok]` requirement is what distinguishes this genuine clean no-op from a degraded discovery that also printed `manifest=[]`). (A jq-merge *failure* is recorded by the fence itself, which writes its own `dropped-failed` reflection before blanking `AGG`, so it is not silently swallowed here.)
- **Cwd-drift suspicion (known limitation) — a heuristic qualifying the clean-no-op arm above, not an exit:** when Phase 3.3's run reported emitting a deferrals manifest but every root classifies `absent` in the surfaced `devflow: discovery roots:` line, treat the run as suspect and compare the roots-echo's absolute paths against where Phase 3.3 executed, rather than accepting the clean no-op.
- **Sentinel present with `manifest=[hydrated]` and `filing=[filed]`, but `filed deferred-finding issues=[]`** — the aggregate held deferrals, the filing arm *ran and succeeded*, yet you can read no filed issue numbers. That is a real capture gap, not a benign no-op: record it durably and apply nothing — `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0.5 filed deferred review-finding issues but could not read their numbers — the configured deferred labels were applied to NONE of them; the filed issues carry none of the configured deferred labels."`
  Read `filing=` before concluding a capture gap. Two other sentinel values also print an empty number list, and neither is a capture gap — asserting one would fabricate a durable reflection claiming issues were filed on a run that filed none: `filing=[unclassified]` (the non-zero state; classify its stderr per *Recording discovery and filing outcomes* above — the benign idempotent and no-deferrals cases both land here, and neither filed anything this run) and `filing=[failed]` (the filing statement never ran to a classified outcome). `idempotent` and `none` are outcomes RECORDED after that classification, never sentinel readings — the fence assigns only `filed`, `failed`, `unclassified`, or the empty initial value. Only `filing=[filed]` with an empty list is the gap.
- **The config read produced no output at all** — you received no `deferred labels to apply: [...]` line whatsoever. The command was refused, not answered: do **not** read that as "no labels configured" (the capture shape is unproven on this tier — see the discipline note above). Record it and apply nothing — `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0.5 could not resolve deferred.labels — the config-get command produced no output at all (likely a harness denial, not an empty config); deferred review-finding issues were filed WITHOUT labels."`

If the printed `CLEAN_DEFERRED_LABELS` is present but empty (config resolved to no labels), apply nothing. Otherwise, read it and apply the labels with single granted-literal leading-token calls, iterating at the agent level (the label helpers must never be wrapped in a shell loop or an output capture):

- For each label in the printed comma-list (skip blanks), ensure it exists with one call — the helper path is the leading token, and `ensure-label.sh` is best-effort (always exits 0). `ensure-label.sh` always breadcrumbs to stderr (`created` / `already exists` / `warning: …`), so no output at all means the command was refused by the harness — record it (`--reflection-kind dropped-failed`) and continue to the apply, which reports separately whether the label landed.
  ```bash
  "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/ensure-label.sh "<label>"
  ```
- For each filed issue number in the printed `filed deferred-finding issues=[…]` list (the numbers `file-deferrals.py` filed, echoed back to you above — not a live `$FILED_NUMBERS` shell variable, which does not survive into this separate command), apply the whole comma-list with one call — the helper path is the leading token, the issue number and resolved label list substituted as literals:
  ```bash
  "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/apply-labels.sh <filed-issue-number> "<deferred-labels>"
  ```
  `apply-labels.sh` is best-effort (always exits 0) and always prints a breadcrumb to stderr on every path it can take — a harness refusal is its ONLY silent outcome. Read that stderr from the tool result and route on it — all four outcomes, not just the failure one: a `devflow: applied label(s) '…' to #N` line means the labels landed; a `devflow: warning: could not apply …` line is an API failure (POST `.../issues/{n}/labels` — repo-scope only; never `gh issue edit --add-label`'s org-scoped GraphQL); a `devflow: warning: apply-labels.sh got no label content …` or `… got a non-numeric issue/PR number …` line is a caller arg-slip — the breadcrumb says outright that it is *not* a harness denial — meaning the label list you substituted was empty/whitespace-only, or the number did not survive into this command, so re-emit the call once with the printed literal values before recording anything; and no output at all means the command was refused by the harness. Record any surviving non-success durably (stderr is ephemeral in an autonomous cloud run), naming which outcome it was: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0.5 could not apply the configured deferred labels (<deferred-labels>) to issue #<filed-issue-number> — the apply reported an API failure or a caller arg-slip, or produced no output at all (a harness denial); the issue was filed but carries none of the configured deferred labels."`

The rc handling above distinguishes three cases: a clean filing (rc 0), the benign idempotent-re-run (`exit 2` with "already has follow_up" — the prior aggregate is still hydrated, `/pr-description` reads it fine, recorded as a plain note), and a genuine failure (any other non-zero — every `gh issue create` group failed, or an unusable/corrupt manifest), which lands a `Devflow Reflection` breadcrumb. On a genuine failure continue to 4.1 anyway — the PR can still ship; it just won't carry the Scope-Acknowledged Findings block, so `/prflow:review` will treat any deferred findings as new.

<!-- prflow:implement-ref step=4.0.5 file=skills/implement/references/deferred-review-findings.md end -->
