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
# tr-dependence guard (guard-class 2): BRANCH_SLUG keys a search dir and is derived through
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
# of masked as a clean no-match (which would strand acknowledged deferrals). Discriminate its
# exit with the same if/elif stderr-marker idiom the file-deferrals.py call below uses.
# DISCOVERY_STATE is initialized empty BEFORE the statement (sentinel-operand rule); a matcher
# refusal of the capture (treat NO OUTPUT AT ALL as a possible denial, never an empty value)
# leaves it empty, printed as discovery=[] and routed fail-closed. exit 0 = paths printed, every
# root ok/absent; partial marker = at least one root failed but clean-root paths are usable;
# else = failed-or-refused.
# Remove any prior run's marker file FIRST, as its own statement: an unwritten (refused) file
# must be unambiguously ABSENT rather than inheriting a prior 'discovery partial:' marker, else
# `grep -q` below routes a discovery that never ran to the PARTIAL arm from a stale aggregate.
# Ensure the scratch leaf exists before any capture write; rc-checked (never `|| true` — a
# DENIED .prflow/tmp mkdir must fail loudly, mirroring lib/telemetry-branch.sh).
if ! mkdir -p .prflow/tmp; then
  echo "devflow: could not create .prflow/tmp for Phase 4.0.5 discovery scratch" >&2
fi
rm -f .prflow/tmp/devflow-dm.err
DISCOVERY_STATE=""
if MANIFESTS=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/discover-deferral-manifests.py $SEARCH_DIRS 2>.prflow/tmp/devflow-dm.err); then
    DISCOVERY_STATE=ok
elif grep -q 'devflow: discovery partial:' .prflow/tmp/devflow-dm.err; then
    # PARTIAL: at least one root failed, at least one did not. Keep the captured paths and file
    # from the clean roots, but record the failed root: once this run's filing hydrates the
    # aggregate, the failed root's deferrals can't be auto-filed by a later re-run
    # (file-deferrals.py refuses a mixed hydrated/raw manifest) — recover them by filing manually.
    DISCOVERY_STATE=partial
    "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0.5 deferral discovery was PARTIAL — at least one candidate root failed traversal: $(cat .prflow/tmp/devflow-dm.err); filing proceeds from the roots that did not fail (\`ok\`/\`absent\`; an \`absent\` root contributes nothing). The failed root's deferrals are NOT filed this run, and once this run hydrates ${AGG} they cannot be auto-filed by a later re-run (file-deferrals.py refuses a mixed hydrated/raw manifest) — recover them by filing from that root's run-scoped manifest manually."
else
    # FAILED or REFUSED: every root failed, OR the capture produced NO OUTPUT AT ALL (a likely
    # matcher denial). Blank MANIFESTS so the merge guard is unambiguously false, and record the
    # failure naming the PERSISTED aggregate path so an operator can re-trigger Phase 4.0.5.
    DISCOVERY_STATE=failed
    MANIFESTS=""
    "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0.5 deferral discovery FAILED (every candidate root failed traversal, or the discovery command produced no output at all — a likely harness denial): $(cat .prflow/tmp/devflow-dm.err 2>/dev/null). No deferrals were filed this run; any persisted aggregate at ${AGG} was left intact — re-trigger Phase 4.0.5 deliberately to recover its deferrals."
fi
# Surface the helper's roots-echo line into the tool result on every path, so an absent-classified
# root is observable. (A non-empty $SEARCH_DIRS is assumed; the zero-arg usage error exits before
# any roots-echo.) Best-effort — a missing line never blocks the fence.
grep 'devflow: discovery roots:' .prflow/tmp/devflow-dm.err || true
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
if { [ "$DISCOVERY_STATE" = ok ] || [ "$DISCOVERY_STATE" = partial ]; } && [ -n "$AGG" ] && [ -s "$AGG" ]; then
    # Discriminate file-deferrals.py's exit codes via the helper's OWN status inline (rc 0 =
    # filed), telling non-zero cases apart by grepping its stderr markers — "already has
    # follow_up" (benign idempotent-re-run) vs. a genuine failure — never a captured rc a
    # stripping inline-bash runner would empty. FILED_STATE names WHICH of the four arms ran;
    # without it three benign arms (idempotent, no-deferrals, failure — none set FILED_NUMBERS)
    # print `filed …=[]` like the one real capture gap, so the reader's "hydrated + no numbers ⇒
    # gap" rule fires on all four and fabricates a reflection claiming issues were filed and lost.
    FILED_STATE=failed
    FILED_NUMBERS=""
    # Delete any stale capture so a resumed run cannot read a prior attempt's stderr
    # (the .prflow/tmp leaf was already created at the top of this fence).
    rm -f .prflow/tmp/devflow-fd.err
    if FILED_OUT=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/file-deferrals.py \
        --source-issue $ARGUMENTS \
        --pr "$PR_NUMBER" \
        --manifest "$AGG" 2>.prflow/tmp/devflow-fd.err); then
        FILED_NUMBERS="$FILED_OUT"
        FILED_STATE=filed
        # file-deferrals.py exits 0 even on PARTIAL success: a per-file group whose
        # `gh issue create` failed is dropped from the manifest, yet the helper still
        # exits 0. Surface that so the dropped findings (which won't reach the PR's
        # Scope-Acknowledged block) leave a breadcrumb instead of vanishing silently.
        grep -q 'were dropped from manifest' .prflow/tmp/devflow-fd.err && \
            "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "file-deferrals.py filed partially (rc=0): $(cat .prflow/tmp/devflow-fd.err); dropped groups will NOT appear in the PR's Scope-Acknowledged Findings block."
    elif grep -q 'already has follow_up' .prflow/tmp/devflow-fd.err; then
        FILED_STATE=idempotent
        "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --note "Deferrals already filed on a prior run (idempotent re-run) — nothing new to file; the hydrated aggregate stands."
    elif grep -q 'no deferrals' .prflow/tmp/devflow-fd.err; then
        FILED_STATE=none
        "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --note "Aggregate held no deferrals to file — nothing to do."
    else
        "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "file-deferrals.py failed (rc≠0): $(cat .prflow/tmp/devflow-fd.err); no follow-up issues filed this run."
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
# which guard-class 2 forbids deriving through a non-preflight PATH tool.
MANIFEST_STATE=""; [ -n "${AGG:-}" ] && [ -s "${AGG:-}" ] && MANIFEST_STATE=hydrated
echo "phase 4.0.5 filing fence ran; pr=[${PR_NUMBER:-}] discovery=[${DISCOVERY_STATE:-}] manifest=[${MANIFEST_STATE}] filing=[${FILED_STATE:-}] filed deferred-finding issues=[${FILED_NUMBERS//$'\n'/ }]"
```

The helper groups manifest entries by `file` (one issue per source file), files each issue with a repo-agnostic title/body template (`<area>: deferred review findings in <file> (carried from #<source_issue>)` and a body containing the verbatim findings plus the `PR #<pr_number>` substring that the verdict matcher's mutual-cross-link guard validates against), then rewrites the manifest in place with `id: dfr-<6-hex>` (deterministic hash of `file + symbol + kind + summary`) and `follow_up: {issue, url, filed_at, filed_by}` populated per entry. Filed issue numbers are printed to stdout, one per line.

Failure mode: if `gh issue create` fails for a particular file-group, that group's entries are dropped from the manifest entirely — no fake deferral can downgrade a future review. The helper exits 0 as long as at least one group succeeded. Capture stderr in your `Devflow Reflection` notes if anything was dropped.

**Foreclosure passthrough.** A `settled-by-disclosure` entry files **no** follow-up issue — the shipped disclosure is its deliverable — yet still survives into the rewritten aggregate unchanged (with a `dfr-` id assigned, no `follow_up`, its `category` and `disclosure` object preserved) so `/pr-description` can render it and `/prflow:review` can honor it. Consequently a manifest whose entries are **all** foreclosures files zero issues and **still exits 0** (printing no issue numbers), rewriting the aggregate; the `FILED_STATE=filed` arm handles it benignly (empty `FILED_NUMBERS`). This is the all-foreclosed exit-0 arm — do not treat an exit-0 with no printed issue numbers as a failure.

The fence printed the filed issue numbers (`filed deferred-finding issues=[...]`) from **inside** the filing fence because `FILED_NUMBERS` does not survive into a later separate command on the cloud runner — reading it from a later fence would see it empty and conclude "nothing was filed" on a run that filed issues, labelling none. Read the printed list from that tool result; it is the only channel carrying the numbers to the agent-level label calls below.

Then apply the configured `deferred.labels` to each filed issue — the **same** resolve/normalize idiom as Phase 4.0 (default `PRFlow,Deferred`; empty/whitespace → none). `file-deferrals.py` itself stays out of config-reading (config is resolver territory — read through `config-get.sh`, not re-parsed ad hoc); the skill owns labeling, best-effort and post-filing, so a label hiccup never unwinds an already-filed issue.

**Cloud-emission discipline (label helpers): iterate at the agent level, never in a shell loop or a capture — identical to Phase 4.0, see the *Cloud command-shape discipline* section in `skills/implement/SKILL.md`.** The cloud implement matcher denies a `for`/piped-`while read` loop wrapping a label helper and a `VAR="$(label-helper …)"` capture; the `config-get` capture below rests on the same unproven inference, so it fails **closed** on no output. First resolve and **print** the clean label list (a shell variable does not survive into a later separate command on the cloud runner, so printing is how you read the value for the per-issue calls):

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
# indistinguishable from an empty config (CLAUDE.md guard-class 2).
echo "deferred.labels raw: [$DEFERRED_LABELS]"
echo "deferred labels to apply: [$CLEAN_DEFERRED_LABELS]"
```

**A non-empty `raw` with an empty `to apply`** is a broken normalizer (a missing/denied `tr`/`sed`/`grep`), **not** an empty config — record it and apply nothing: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0.5 resolved deferred.labels to a non-empty value but the normalizer produced an empty list (a missing/denied tr|sed|grep in the pipeline); deferred review-finding issues were filed WITHOUT labels."`

The exits before any label is applied are the same fail-closed set Phase 4.0 carries. Most are read off the **sentinel** the filing fence prints unconditionally; the label-config exit off the separate `deferred labels to apply:` line the config fence prints. Some bullets below are *qualifiers* rather than exits — the **`discovery=[partial]`** one (applies nothing on its own) and the **Cwd-drift suspicion** one (a heuristic qualifying the clean-no-op arm):

- **No `phase 4.0.5 filing fence ran` sentinel at all, OR the sentinel present with `discovery=[]`.** The fence was refused, not answered — do **not** read it as "nothing was filed". A refusal or non-execution of the discovery statement lands as `discovery=[]` on the sentinel or as no sentinel at all — and it does not matter which; both take this exit. Record it and apply nothing: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0.5's filing fence produced no sentinel at all, or a sentinel carrying discovery=[] (the discovery statement was refused or never ran) — likely a harness denial, not an empty aggregate; no deferred review-finding issues were filed or labelled this run."`
- **Sentinel present, `pr=[]`** — the `gh pr view` read ran and yielded no number, so every path built on it (`SLUG_DIR`, the manifest discovery, `AGG`) resolved against a truncated slug and found nothing. **Do not read the `manifest=[]` that follows it as the clean no-op**: no manifest was even looked for at the right path, so this run's deferrals (if any) were neither filed nor labelled. Record it and apply nothing: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0.5 could not resolve the PR number — the gh pr view read yielded no value; no deferrals manifest could be located, so no deferred review-finding issues were filed or labelled this run."` (A matcher *denial* of that capture lands in this state or in the no-sentinel exit above — and it does not matter which: both record `dropped-failed` and apply nothing, so this routing does not depend on a denial granularity no probe row establishes.)
- **Sentinel present with `discovery=[failed]`** — every candidate root failed traversal, or the discovery command produced no output at all (the fence's else arm). The fence already blanked `MANIFESTS`, so `manifest=[]` and nothing was filed. Do **not** read that `manifest=[]` as the clean no-op: no manifest could be discovered. The fence already recorded a `dropped-failed` discovery-failure reflection naming the persisted aggregate path — apply nothing further this run.
- **Sentinel present with `discovery=[partial]` — a qualifier on the arms below, not an exit:** at least one candidate root failed traversal and the failed root was **already recorded in-fence** (a `dropped-failed` reflection). Whether any deferrals were filed is read off `manifest=` and `filing=` per the arms below — a partial run with `manifest=[]` or an empty `filing=` filed nothing; partial does not by itself imply any manifest was found. Apply labels only if `filing=[filed]` with a non-empty filed list, per the arms below.
- **Sentinel present with `discovery=[ok]`, `pr=[<n>]` and `manifest=[]`** — no hydrated aggregate (either there were no deferrals this run, or the merge produced nothing), so nothing was filed and there is nothing to label: apply nothing. This is the clean no-op (the `discovery=[ok]` requirement is what distinguishes this genuine clean no-op from a failed/partial discovery that also printed `manifest=[]`). (A jq-merge *failure* already recorded its own `dropped-failed` reflection inside the fence, so it is not silently swallowed here.)
- **Cwd-drift suspicion (known limitation) — a heuristic qualifying the clean-no-op arm above, not an exit:** when Phase 3.3's run reported emitting a deferrals manifest but every root classifies `absent` in the surfaced `devflow: discovery roots:` line, treat the run as suspect and compare the roots-echo's absolute paths against where Phase 3.3 executed, rather than accepting the clean no-op.
- **Sentinel present with `manifest=[hydrated]` and `filing=[filed]`, but `filed deferred-finding issues=[]`** — the aggregate held deferrals, the filing arm *ran and succeeded*, yet you can read no filed issue numbers. That is a real capture gap, not a benign no-op: record it durably and apply nothing — `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0.5 filed deferred review-finding issues but could not read their numbers — the configured deferred labels were applied to NONE of them; the filed issues carry none of the configured deferred labels."`
  **Read `filing=` before concluding a capture gap.** Three other arms also print an empty number list, and none of them is a capture gap — asserting one would fabricate a durable reflection claiming issues were filed on a run that filed none: `filing=[idempotent]` (a prior run already filed them; the hydrated aggregate stands — nothing to label this run), `filing=[none]` (the aggregate held no deferrals), and `filing=[failed]` (the filing itself failed and **already recorded its own accurate reflection inside the fence** — do not add a second, contradicting one). Only `filing=[filed]` with an empty list is the gap.
- **The config read produced no output at all** — you received no `deferred labels to apply: [...]` line whatsoever. The command was refused, not answered: do **not** read that as "no labels configured" (the capture shape is unproven on this tier — see the discipline note above). Record it and apply nothing — `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0.5 could not resolve deferred.labels — the config-get command produced no output at all (likely a harness denial, not an empty config); deferred review-finding issues were filed WITHOUT labels."`

If the printed `CLEAN_DEFERRED_LABELS` is present but empty (config resolved to no labels), apply nothing. Otherwise, read it and apply the labels with **single granted-literal leading-token calls, iterating at the agent level** (the label helpers must never be wrapped in a shell loop or an output capture):

- For **each** label in the printed comma-list (skip blanks), ensure it exists with one call — the helper path is the leading token, and `ensure-label.sh` is best-effort (always exits 0). `ensure-label.sh` always breadcrumbs to stderr (`created` / `already exists` / `warning: …`), so **no output at all means the command was refused by the harness** — record it (`--reflection-kind dropped-failed`) and continue to the apply, which reports separately whether the label landed.
  ```bash
  "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/ensure-label.sh "<label>"
  ```
- For **each** filed issue number in the printed `filed deferred-finding issues=[…]` list (the numbers `file-deferrals.py` filed, echoed back to you above — **not** a live `$FILED_NUMBERS` shell variable, which does not survive into this separate command), apply the whole comma-list with one call — the helper path is the leading token, the issue number and resolved label list substituted as literals:
  ```bash
  "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/apply-labels.sh <filed-issue-number> "<deferred-labels>"
  ```
  `apply-labels.sh` is best-effort (always exits 0) and **always** prints a breadcrumb to **stderr** on **every path it can take** — a harness refusal is its ONLY silent outcome. **Read that stderr from the tool result and route on it — all four outcomes, not just the failure one:** a `devflow: applied label(s) '…' to #N` line means the labels landed; a `devflow: warning: could not apply …` line is an **API failure** (POST `.../issues/{n}/labels` — repo-scope only; never `gh issue edit --add-label`'s org-scoped GraphQL); a `devflow: warning: apply-labels.sh got no label content …` or `… got a non-numeric issue/PR number …` line is a **caller arg-slip** — the breadcrumb says outright that it is *not* a harness denial — meaning the label list you substituted was empty/whitespace-only, or the number did not survive into this command, so re-emit the call once with the printed literal values before recording anything; and **no output at all means the command was refused by the harness**. Record any surviving non-success durably (stderr is ephemeral in an autonomous cloud run), naming which outcome it was: `workpad.py update $ISSUE_NUMBER --reflection-kind dropped-failed --reflection "Phase 4.0.5 could not apply the configured deferred labels (<deferred-labels>) to issue #<filed-issue-number> — the apply reported an API failure or a caller arg-slip, or produced no output at all (a harness denial); the issue was filed but carries none of the configured deferred labels."`

The rc handling above distinguishes three cases: a clean filing (rc 0), the benign idempotent-re-run (`exit 2` with "already has follow_up" — the prior aggregate is still hydrated, `/pr-description` reads it fine, recorded as a plain note), and a genuine failure (any other non-zero — every `gh issue create` group failed, or an unusable/corrupt manifest), which lands a `Devflow Reflection` breadcrumb. On a genuine failure continue to 4.1 anyway — the PR can still ship; it just won't carry the Scope-Acknowledged Findings block, so `/prflow:review` will treat any deferred findings as new.

<!-- prflow:implement-ref step=4.0.5 file=skills/implement/references/deferred-review-findings.md end -->
