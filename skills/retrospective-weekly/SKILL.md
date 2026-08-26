---
name: retrospective-weekly
description: >
  Run the weekly devflow self-improvement loop locally: scan freshly-merged
  watched-author PRs, write per-PR retrospective entries (LLM only for PRs
  that fail the mechanical clean-gate), derive recurring patterns, and file
  one human-reviewed GitHub issue per actionable pattern. Use when running
  the weekly devflow retrospective + audit.
---

# /prflow:retrospective-weekly — Weekly Orchestrator

This skill is the single entry point the maintainer invokes once a week (or
on demand). It is a *conductor*: it runs deterministic bash/jq scripts from
`lib/` at every mechanical step and dispatches LLM subagents only at the two
genuine-judgment points — per-PR retrospective analysis (Stage A) and
per-pattern issue-spec drafting (Stage B). The loop proposes, it does not dispose:
each actionable pattern is filed as one GitHub issue for the normal
implement → review pipeline, not landed as an autonomous PR.

Subagent dispatch is user-requested here (injection-condition clause). Invoking `/prflow:retrospective-weekly` is the user's request for subagent dispatch at this loop's two judgment points — the Stage A per-PR retrospective subagents (Step 4) and the Stage B per-pattern issue-spec subagents (Step 8b) — thereby satisfying any injected "do not call the AgentTool unless the user requested it" condition there and nowhere else; every other step stays the deterministic scripts the conductor runs directly.

`$LIB` notation (textual, not a shell variable). Throughout this skill, `$LIB` in a command denotes the resolved path `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib` — expand it textually (with the anchor already resolved for this runner) when composing each command you actually run. Never rely on a shell variable named `LIB` persisting from one statement or block to another — each Bash call is a fresh shell.

Working-directory contract. This skill's `lib/`/`scripts/` helper paths are repo-relative literals resolving against the repository root; no fence emits a leading `cd`.

Every `jq` in this skill is invoked through the execution-verified wrapper
`$LIB/../scripts/run-jq.sh` (`$LIB/../scripts` is the `scripts/` dir beside
`lib/`), never bare `jq` — a shim-shadowed Windows/WSL host otherwise resolves an
unrunnable jq. `DEVFLOW_JQ` is not exported to agent shells, so invoke the wrapper by
path.

All scratch files live under `.prflow/tmp/` (gitignored). Learnings files
(`.prflow/learnings/`) are tracked and committed via the state PR.

Writing standard (any text you compose that lands on a GitHub surface — issue/PR titles, the state-PR report comment, body content you assemble). Before composing such text, read the shared writing standard `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/writing-standard.md` and follow it. A failed load emits a breadcrumb naming the file and the failure kind, and you compose without it.

GitHub autolink hygiene (any text you compose that lands on a GitHub surface — issue/PR titles, the state-PR report comment, body content you assemble): never put a bare `#` immediately before a number unless it is a real issue or PR reference — GitHub renders `#2` as a link to issue/PR 2, which misleads readers. For an ordinal, count, or list position, spell it out ("item 2", "step 3"), never `#2`. Genuine references like `#123` stay as-is. <!-- pruned-path-ok: illustrative autolink examples, not citations -->

---

**Portable helper anchor (single-statement).** The bundled-helper commands in this skill resolve the skill directory inline at each call site via `${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}`. When `$CLAUDE_SKILL_DIR` is set and non-empty (Claude Code), run each command exactly as written. Otherwise locate the directory yourself — this text lives in a file inside it, whose sibling `../../scripts/` directory exists — by replacing the placeholder with the skill base directory the runner reports in context (e.g. a `Base directory for this skill:` line) and accepting a candidate only once `ls <candidate>/../../scripts/` succeeds in the same shell the helper commands run in. If a path form is rejected, use the form that shell reports (`pwd` shows it); a Windows-form base directory (`C:\...`) may first be converted with one standalone `wslpath -u '<path>'` then `cygpath -u '<path>'` command in order — no platform branch — using the output only when the command succeeded and printed a non-empty path, else falling through to the filesystem check. Resolve the anchor inline at every call site — never capture it into a shell variable that a later statement reads, because some runners' inline-bash marshaling drops such variables. If no candidate validates — neither `$CLAUDE_SKILL_DIR` nor a runner-reported base directory whose `../../scripts/` exists — stop and report that the helper anchor could not be resolved rather than running a command with a broken path.

Consumer prompt extension (load first). Before doing this skill's work, load any consumer-supplied prompt extension for this skill and honor it. From the repo root, run:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh retrospective-weekly
```

If the invocation fails because the helper path does not exist (`No such file`, exit 127, or the platform equivalent), that is the anchor-resolution failure described in the *Portable helper anchor* note above — fix the anchor, don't report a missing extension. Otherwise, if the helper exits non-zero, a consumer extension exists but could not be loaded — surface its stderr message and do not silently proceed as if none existed. If it exits 0 and prints text, treat that text as additional instructions appended to the end of this skill's own prompt for this run — it is upgrade-safe, consumer-owned customization committed under `.prflow/prompt-extensions/`. If it exits 0 and prints nothing, proceed unchanged.

## Procedure

### Step 1 — Preflight

Confirm the working tree is clean:

```bash
git status --porcelain
```

If the output is non-empty, **stop** and tell the user to stash or commit
their changes before running the loop.

Confirm `gh` is authenticated:

```bash
gh auth status
```

If it fails, tell the user to run `gh auth login` and stop.

Confirm you are on `main`:

```bash
git branch --show-current
```

If not on `main`, run `git checkout main`.

Prepare the scratch directory (`$LIB` below is the textual notation from the top of this skill — expand it when composing commands, do not assign a shell variable). This also removes prior-run scratch, so a run can never read another run's stale bundle, output, or overrides snapshot:

```bash
mkdir -p .prflow/tmp
rm -f .prflow/tmp/new-entries.jsonl
# Remove prior-run scratch with `find … -delete`, not a bare `rm -f <glob>` (which
# aborts under zsh's nomatch and leaves every pattern uncleaned). Name here every file
# a later step reads back by path: readers guard input by readability alone, so a
# surviving readable copy renders the report from stale state.
find .prflow/tmp -maxdepth 1 -type f \( -name 'result-*.json' -o -name 'pr-*.context.json' -o -name 'overrides-prefiling.json' -o -name 'patterns.json' -o -name 'patterns-full.json' -o -name 'patterns.stderr' \) -delete 2>/dev/null
```

---

### Step 2 — Scan

Fetch the list of unprocessed watched-author PRs merged in the last 7 days:

```bash
bash $LIB/scan.sh > .prflow/tmp/scan.json
```

Ad-hoc / backfill / test runs. To run the loop against a specific set of
PRs instead of the rolling 7-day window — e.g. backfilling old PRs, re-running
after a fix, or testing the pipeline — pass `--prs`:

```bash
bash $LIB/scan.sh --prs 774,786,772,789 > .prflow/tmp/scan.json
```

`--prs` skips the GitHub search and the already-processed filter (you named
the PRs, so the loop trusts you), but still drops any number that isn't a merged
retrospected branch. Everything downstream (Steps 3–10) is identical. Do not
use `--prs` for the scheduled weekly run.

`scan.sh` writes to stdout and exits non-zero on unrecoverable errors. If
the output array is empty:

```bash
$LIB/../scripts/run-jq.sh 'length == 0' .prflow/tmp/scan.json
```

→ `true`: report **"Nothing to process — no unprocessed watched-author PRs
in the last 7 days."** and STOP.

---

### Step 3 — Per-PR context fetch + cheap gate

Initialize counters:

```bash
prs_scanned=0
clean_count=0
analyzed_count=0
skipped_count=0     # mechanically- and Stage-A-skipped PRs
skip_records=()     # one-line report records, one per skip (never silent)
needs_analysis=()   # array of bundle paths
```

For each PR number in `scan.json` (iterate via `$LIB/../scripts/run-jq.sh -r '.[].number'`):

```bash
number=<the pr number>
CTX=$(bash $LIB/fetch-pr-context.sh "$number")
prs_scanned=$((prs_scanned + 1))
```

`fetch-pr-context.sh` writes the bundle to `.prflow/tmp/pr-<n>.context.json`
and echoes that file path to stdout — so `$CTX` is the path, not the
bundle content.

Run the cheap gate against the bundle content:

```bash
GATE=$($LIB/../scripts/run-jq.sh -c -f $LIB/cheap-gate.jq < "$CTX")
```

Outputs `{"clean": <bool>, "reason": "<string>"}`.

If `clean == true`:

Emit a clean entry (every retrospected PR is an `implementation` PR):

```bash
$LIB/../scripts/run-jq.sh -c -f $LIB/clean-entry.jq < "$CTX" >> .prflow/tmp/new-entries.jsonl
```

Increment `clean_count`.

If `clean == false`:

First run the mechanical pre-dispatch disposition. This decides —
with no LLM dispatch — whether the non-clean bundle warrants Stage A analysis
or is a mechanical skip (a foreign, non-DevFlow PR whose only non-clean signal is a
missing workpad audit trail):

```bash
DISP=$($LIB/../scripts/run-jq.sh -c --argjson gate "$GATE" -f $LIB/dispatch-disposition.jq < "$CTX")  # argjson-ok: gate -- one PR's cheap-gate result (bounded)
```

`DISP` is `{"disposition": "skip"|"dispatch", "reason": "<string>"}`. It returns
`skip` exactly when the gate reason is a workpad reason, the status is a
sentinel (`Absent`/`NoIssue`), and `pr_devflow_provenance` is `false` — otherwise
`dispatch`. So a bundle non-clean on any non-workpad signal (outstanding
REJECT, an unreadable review-verdict signal, CI failures, post-bot commits,
review comments) is always dispatched.

If `disposition == "skip"` (the mechanical no-provenance skip): this is a
permanently-terminal skip. Append a marker entry to the store and write a
one-line run-report record — costing zero LLM dispatches. Do not add it to
`needs_analysis`.

```bash
# $number is this PR (the loop variable); DISP's .reason is the skip reason line.
SKIP_REASON=$(printf '%s' "$DISP" | $LIB/../scripts/run-jq.sh -r '.reason')
# argjson-ok: pr -- scalar PR number.
$LIB/../scripts/run-jq.sh -cn --argjson pr "$number" --arg reason "$SKIP_REASON" \
  '{kind:"skip", pr:$pr, reason:$reason}' >> .prflow/tmp/new-entries.jsonl
skip_records+=("PR #$number skipped (mechanical, no DevFlow provenance): $SKIP_REASON")
skipped_count=$((skipped_count + 1))
```

The marker entry makes the processed-PRs filter treat this PR as handled on
subsequent runs.

If `disposition == "dispatch"`: add the bundle path to the analysis list:

```bash
needs_analysis+=("$CTX")
analyzed_count=$((analyzed_count + 1))
```

---

### Step 4 — Stage A: Retrospective subagents (per non-clean PR)

For each bundle path in `needs_analysis`, dispatch a subagent. Issue up to
3–4 subagents concurrently in a single message (use the Agent tool for
each). Each subagent prompt:

> Read and follow `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../retrospective/SKILL.md`
> exactly.
>
> Your context bundle path is: `<path>`
>
> Consumer prompt-extension handoff: your extension file for this skill is at the
> absolute path `<REPO_ROOT>/.prflow/prompt-extensions/retrospective.md`. Read it
> with your file-read tool and honor any content as instructions appended to the
> retrospective skill's own prompt. If the file is absent or empty, treat it as a
> no-op and report nothing about it; if it is present but you cannot read it, report
> that via the optional `extension_unreadable` key in your returned JSON object.
>
> Bundled-helper root: the plugin is at the absolute path `<PLUGIN_ROOT>`. Use that
> value wherever the retrospective skill writes `[[PLUGIN_ROOT]]` — for example
> `[[PLUGIN_ROOT]]/scripts/run-jq.sh`. Resolve no skill-directory anchor of your own.
>
> Internal-documentation root: `<INTERNAL_DOC_ROOT>`. Use that value wherever the
> retrospective skill writes `[[INTERNAL_DOC_LOCATION]]`.
>
> Print exactly one JSON object (the retrospective entry) and nothing else
> on stdout.

**Resolve `<REPO_ROOT>`, `<PLUGIN_ROOT>` and `<INTERNAL_DOC_ROOT>` ONCE, before the
dispatch loop begins, and reuse them for every dispatch (by-value handoff).** A subagent
receives neither `$CLAUDE_SKILL_DIR` nor a `Base directory for this skill:` context line,
so it cannot resolve its own anchor; resolve all three yourself and substitute the
absolute values into the handoff sentences above:

- `<REPO_ROOT>` — `git rev-parse --show-toplevel`.
- `<PLUGIN_ROOT>` — the resolved value of `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../`, with the trailing slash dropped. Substitute the resolved absolute path; never hand the child the unexpanded anchor, which it cannot expand. Resolve the first handoff sentence's anchor-relative path to the brief at emission too — a child that cannot expand it cannot find the brief.
- `<INTERNAL_DOC_ROOT>` — `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.internal docs/internal/`. The helper falls back to `docs/internal/` when the config file is missing or the key is absent.

Append all three sentences unconditionally — without them the child degrades to its
own fallbacks. Do not probe for or read the extension file yourself, so its content
stays out of this orchestrator's context. `<PLUGIN_ROOT>` names a bundled helper the
child executes (`[[PLUGIN_ROOT]]/scripts/run-jq.sh`), so the child's tier must
permit that invocation.

(Pass no "existing tags" list — the subagent picks `categories` from the fixed
vocabulary in that skill.)

Wait for all dispatched subagents to finish before continuing.

Collecting results: Each subagent's final message is its JSON object.
Subagent output can contain quotes, backticks, newlines, and `$` — never
interpolate it inline into a shell command. **Write each subagent's raw result
to a temp file with the Write tool** (e.g. `.prflow/tmp/result-<n>.json`), then
operate on the file. For each result:

1. Attempt to parse it: `$LIB/../scripts/run-jq.sh -c . < .prflow/tmp/result-<n>.json`
2. **A Stage A defined skip is recognized by the presence of a
   top-level `"skip"` key ONLY** — never by matching substrings of any error text
   (agent-authored free text is data, never a discriminator). A `"skip"`-keyed
   return is terminal: no retry, no blocker. Whether it leaves a marker depends
   on the bundle's `workpad_final_status` (a mechanical field, not the skip text):
   - `Cancelled` → a permanently-terminal skip → append a marker entry so
     the PR is seen as handled next run:
     `$LIB/../scripts/run-jq.sh -cn --argjson pr <n> --arg reason "<the skip .reason>" '{kind:"skip", pr:$pr, reason:$reason}' >> .prflow/tmp/new-entries.jsonl` # argjson-ok: pr -- scalar PR number
   - an interim state (`Setup`/`Discovering`/…/`Documenting`) → a transient
     skip → append no marker, so the PR stays unprocessed and is re-scanned
     while it remains inside the 7-day merge lookback.

   Either way, record the skip explicitly — append the report record AND increment
   the counter, so `skipped_count` and the rendered `skips[]` can never diverge:

   ```bash
   skip_records+=("PR #<n> skipped (Stage A, <Cancelled|interim>): <the skip .reason>")
   skipped_count=$((skipped_count + 1))
   ```

   That record is what Step 9 renders. Every skip writes one, so no skip is ever
   silent.
3. Otherwise, if parsing fails or the object has an `"error"` key (a genuine
   failure), retry the subagent once with the same prompt.
4. If still malformed (or still `"error"`-keyed) after one retry, record a blocker:
   `"PR #<n>: retrospective analysis failed"` and skip that PR.
5. If valid (a real retrospective entry, no `"skip"`/`"error"` key), append:
   `$LIB/../scripts/run-jq.sh -c . < .prflow/tmp/result-<n>.json >> .prflow/tmp/new-entries.jsonl`
6. Relay a child-reported unreadable extension. If the parsed object carries an
   `extension_unreadable` key, surface it in the run report by appending a one-line
   record naming the child skill and the reported value —
   `skip_records+=("Stage A PR #<n>: consumer prompt extension for retrospective present but unreadable: $($LIB/../scripts/run-jq.sh -r '.extension_unreadable' < .prflow/tmp/result-<n>.json)")` — so the operator sees the extension could not be honored. This never fails the PR's analysis; the entry is still appended in step 5.

---

### Step 5 — Materialize

Merge all new entries into the retrospectives file (idempotent — existing
entries for the same `pr`+`kind` are replaced):

```bash
bash $LIB/materialize-retrospectives.sh \
  .prflow/tmp/new-entries.jsonl \
  .prflow/learnings/retrospectives.jsonl
```

The script prints `"materialized: appended N, replaced M"` to stdout.

---

### Step 6 — Reconcile lifecycle, then derive actionable patterns

First reconcile every pattern's lifecycle record against the live state of its
filed meta-issue: `pattern-state.sh run` migrates the overrides file to schema v3 in
place (stamping each record's `category` field) and refreshes each
`filed`/`fixed`/`declined` state. It runs before `actionable-patterns.sh`; a
wholesale reconcile failure exits non-zero and aborts the derivation, fail-closed.

```bash
# Guard this call: an unguarded non-zero exit derives patterns from stale,
# unreconciled state and the loop files nothing.
bash $LIB/pattern-state.sh run .prflow/learnings/overrides.json || {
  echo "::error::retrospective Step 6: the lifecycle reconcile failed — aborting BEFORE pattern derivation (deriving from unreconciled state is the defect this step exists to prevent)" >&2
  exit 1
}
# Capture stderr to a file, not a pipe (which would replace the script's own exit
# status): the report renders actionable-patterns.sh's `liveness:` line from it.
bash $LIB/actionable-patterns.sh \
  .prflow/learnings/retrospectives.jsonl \
  .prflow/learnings/overrides.json \
  > .prflow/tmp/patterns.json 2> .prflow/tmp/patterns.stderr || {
  # Guard it: `>` truncates before the script runs, so an unguarded non-zero exit
  # leaves an empty patterns.json and Step 8 files nothing.
  echo "::error::retrospective Step 6: actionable-pattern derivation failed — aborting rather than proceeding with an empty pattern set (which would report a quiet week)" >&2
  cat .prflow/tmp/patterns.stderr >&2 || true
  exit 1
}
cat .prflow/tmp/patterns.stderr >&2 || true
# Snapshot the post-reconcile, PRE-FILING overrides file for Step 9's won't-fix
# re-raise read — AFTER the reconcile and BEFORE any filing. Take it here, not in
# Step 8c, which is skipped when nothing is actionable. Remove the destination first
# and guard the copy: a stale surviving file renders the section from state this run
# never took.
rm -f .prflow/tmp/overrides-prefiling.json
cp .prflow/learnings/overrides.json .prflow/tmp/overrides-prefiling.json || {
  echo "::error::retrospective Step 6: could not snapshot the pre-filing overrides file — aborting rather than letting Step 9 render its won't-fix re-raise section from a stale or absent snapshot" >&2
  exit 1
}
# The unfiltered whole-pattern view for the run report; --full drops the actionable
# filters (every lifecycle state, below-threshold and suppressed included).
bash $LIB/actionable-patterns.sh \
  .prflow/learnings/retrospectives.jsonl \
  .prflow/learnings/overrides.json \
  --full \
  > .prflow/tmp/patterns-full.json || {
  echo "::error::retrospective Step 6: the unfiltered (--full) pattern derivation failed — aborting; the report's pattern section is rendered from this file" >&2
  exit 1
}
```

Print a summary line to the console, for example:

```
5 PRs: 3 clean, 2 analyzed; 2 actionable patterns: incomplete-edit (x5), lenient-verdict (x3)
```

Partition `patterns.json` into two lists:

```bash
to_act=$($LIB/../scripts/run-jq.sh '[.[] | select(.cooldown_active == false)]' .prflow/tmp/patterns.json)
cooldown_skipped=$($LIB/../scripts/run-jq.sh '[.[] | select(.cooldown_active == true) | .tag]' .prflow/tmp/patterns.json)
```

Record `cooldown_skipped` tags for the final report.

---

### Step 6.5 — Build experiment records (best-effort)

After Step 5 materialized this week's retrospective entries (and before the Step 7
state PR commits the learnings files), assemble the unified experiment record —
joining each merged PR's per-run cost to its review outcome (verdict, Important-finding
count, denial count, config fingerprint). Anchored here so this week's PRs join
against this week's freshly-materialized retrospective entries.

This is a best-effort step and never blocks the retrospective: a non-zero exit is
logged as a breadcrumb and the run continues. Carry that breadcrumb into the Step 9 status
report as a blocker note so the failure is visible, then proceed.

A non-zero exit means some PRs did not make it into the store, not that *nothing*
was written — report it as "N PRs missing from the experiment store," not as "the store
was not updated." An unestablished PR does not backfill by itself, so name the PRs
from the breadcrumb and re-run with `--prs` once the cause is resolved.

Before the reader runs, fetch the telemetry branch into its local ref so
`build-experiment-records.py` can union each run's durable record off that branch with any
legacy tracked `.prflow/logs/`. Best-effort: on a fresh repo the branch does not exist
and the fetch is a harmless no-op, so a missing telemetry branch never blocks the run.

```bash
# Fetch the telemetry branch into its local ref — deliberately NO force `+` refspec:
# the local ref can be AHEAD of the remote, and a forced fetch would rewind it and
# permanently orphan those records.
#
# Resolve the branch through the SAME resolver the writer uses (`devflow_telemetry_branch`
# in lib/telemetry-branch.sh): a bare `config-get.sh` read would target a branch nobody
# wrote to and every cost row silently goes missing. The `||` keeps this best-effort.
#
# Do NOT redirect the resolver's stderr to /dev/null: on a git-invalid `telemetry.branch`
# its breadcrumb is the one place that names the config key to fix.
#
# The lib sources `config-source.sh`, which sets `set -euo pipefail` in THIS shell; keep
# every command below `||`-guarded, or errexit will abort the step.
. "$LIB/telemetry-branch.sh" || true
TELEMETRY_BRANCH=$(devflow_telemetry_branch) || TELEMETRY_BRANCH=""
[ -n "$TELEMETRY_BRANCH" ] || TELEMETRY_BRANCH=prflow-telemetry
git fetch origin "${TELEMETRY_BRANCH}:${TELEMETRY_BRANCH}" 2>/dev/null || \
  echo "retrospective-weekly: could not fetch telemetry branch '${TELEMETRY_BRANCH}' (absent on a fresh repo, offline, or the local ref has commits the remote lacks) — the experiment-record reader unions whatever local '${TELEMETRY_BRANCH}' ref exists (if any) with any legacy tracked .prflow/logs/" >&2
python3 $LIB/../scripts/build-experiment-records.py || \
  echo "retrospective-weekly: build-experiment-records.py exited non-zero (rc=$?) — one or more PRs are MISSING from the experiment store (see its stderr for which, and whether they failed to assemble or had an unestablished merge state); records that did assemble were still written" >&2
```

The assembler is idempotent and incremental, so re-running is safe. It runs on the
local/interactive retrospective tier only — never from a workflow. The record's own
shape is documented in `scripts/build-experiment-records.py`'s module docstring.

---

### Step 7 — State PR

Open the state PR now, before Stage B, so that the learnings files are
committed onto their own branch. This captures the unstaged changes Steps 5–6
wrote to `.prflow/learnings/` before any issue is filed, so this run's
retrospective data survives even if Stage B or the filing step fails partway.

Ensure you are on `main`:

```bash
git checkout main
```

The working tree now has the updated
`.prflow/learnings/retrospectives.jsonl` and, normally, a modified
`.prflow/learnings/overrides.json`. That overrides diff is this run's output, not
carry-over — Step 6's reconcile rewrites the file unconditionally. Review it as fresh
reconcile output; do not discard it as stale. These changes are in-place on `main`'s
working tree and have never been committed to `main` — `open-state-pr.sh` handles
committing them onto a separate branch.

```bash
STATE_PR=$(bash $LIB/open-state-pr.sh)
```

`open-state-pr.sh` (no required args; optional `--branch <name>`,
`--base <ref>` — defaults to `main` —, and `--dry-run`):

- Creates/reuses branch `devflow/learnings-<YYYY-MM-DD>` from `--base`
  (`main` by default), so the PR diff is just the learnings files.
- Stages any learnings files that exist (`.prflow/learnings/retrospectives.jsonl`
  and, if present, `.prflow/learnings/overrides.json`).
- Commits and pushes (force-with-lease if the remote branch exists).
- Opens or updates the PR against `main`.
- Prints the PR number to stdout.

After it returns, go back to `main` so the working tree is clean and
Stage B starts from a known-good HEAD:

```bash
git checkout main
```

Initialize Stage B counters:

```bash
intervention_issues=() # will hold {key, category, url} objects — one per filed finding
blockers=()              # will hold strings
# Step 9 slurps both of these. Declare them here, or a run that files and withholds
# nothing leaves Step 9 a name it discovers is unset.
filed_slugs=()           # will hold COARSE pattern tags — one per pattern that filed at
                         # least one issue. Coarse, not composed: a
                         # `<category>-<subslug>` key never matches the pattern's own
                         # `.tag // .slug` that Step 9 keys on.
withheld=()              # will hold {tag, cap} objects — one per pattern a cap held back
truncations=() # will hold {tag, delivered, total, selected} objects — one per pattern the audit_bundle_cap (or a fetch failure) truncated
```

---

### Step 8 — Stage B: File one issue per selected finding

For each actionable pattern, a Stage B subagent returns a ranked `findings` array
(one to three sub-patterns), and the orchestrator files **one GitHub issue per
selected finding** via `meta-issue.sh` — under an opaque `<category>-<subslug>`
filing key composed by the composer. Which findings become filings is decided by
`lib/select-findings.sh`, the owner of that decision on the findings-array path;
the legacy `{title, body}` shape never reaches it and derives its own cap verdict in
8c. That legacy shape carries no projection disposition, so 8c's projection gate
blocks it unconditionally and loudly — intended, because the shipped Stage B
composer returns only the findings-array shape, and a stale composer that still
returns `{title, body}` has had no projection audit to file on. No worktrees, no commits, no PRs — the loop proposes; a human triages each issue and runs it through the normal
`/prflow:implement` → review pipeline. Your main checkout stays on `main` and is
never edited. The drafting subagents (8b) parallelize; the cheap filing (8c) is done
serially.

#### 8a — Gather occurrence bundles (bounded by `audit_bundle_cap`)

The enriched pattern object carries per-occurrence
`summary`/`descriptors`/`suggested_interventions` and can run into hundreds of
occurrences, so — beyond the single scalar read that names its own file (`SLUG`,
below) — read each scalar field (`SLUG`, `TAG`, `CATEGORY`, `TOTAL`) from the on-disk
`pattern-${SLUG}.json` file, never through a second/third herestring or an inline
prompt interpolation. `devflow_select_audit_bundles` below is exempt: it receives the
whole in-memory `$pattern` once as a bounded positional argument.

**`SLUG` names the file every later step reads, so it is derived — and that file
written — before any other field is read off the pattern object:**

1. `SLUG` — `$LIB/../scripts/run-jq.sh -r .slug <<< "$pattern"`. The one
   sanctioned herestring over the enriched object; the exception is scoped to this one
   scalar and licenses no second read.
2. Write that pattern's object to `.prflow/tmp/pattern-${SLUG}.json` with the
   **Write tool**.
3. `TAG` (`$LIB/../scripts/run-jq.sh -r .tag ".prflow/tmp/pattern-${SLUG}.json"`)
   and `CATEGORY`
   (`$LIB/../scripts/run-jq.sh -r .category ".prflow/tmp/pattern-${SLUG}.json"` — the
   attribution category the opaque filing key belongs to). Read these **from the
   file**, never as a second and third herestring over the enriched object.
4. Record also the absolute path `.prflow/tmp/pattern-${SLUG}.json` (Step 8b
   hands that path to the subagent, matching the bundle-path handoff).

Stage B fetches at most `audit_bundle_cap` occurrence bundles per pattern,
most-recent-first. Resolve and validate the cap **once, before the per-pattern
loop begins**, so no pattern is fetched before an unusable cap is detected. The
config read stays in this fence (via `config-get.sh`, default `10`); the validation
and selection live in the sourced `lib/audit-bundle-selection.sh`:

```bash
# Source the helper with a fail-closed arm. Without it an unsourceable helper leaves
# devflow_validate_audit_bundle_cap / devflow_select_audit_bundles /
# devflow_audit_dispatch_ok undefined and the run proceeds on unvalidated values.
source $LIB/audit-bundle-selection.sh || {
  echo "::error::retrospective Step 8a: lib/audit-bundle-selection.sh could not be sourced — the audit-bundle cap has no validator/selector; aborting rather than fetching every occurrence on an unvalidated cap" >&2
  exit 1
}
# config-get.sh resolves an absent file / absent key / null / empty string / empty
# array to the default 10. devflow_validate_audit_bundle_cap rejects every unusable
# cap non-zero; the `|| exit 1` propagates it so no pattern is judged on a bad cap.
AUDIT_BUNDLE_CAP_RAW="$(bash $LIB/../scripts/config-get.sh '.prflow_retrospective.audit_bundle_cap' 10)"
AUDIT_BUNDLE_CAP="$(devflow_validate_audit_bundle_cap "$AUDIT_BUNDLE_CAP_RAW")" || exit 1
# Resolve loop-invariant REPO_ROOT once. Keep `|| pwd`: unguarded, a git-absent host
# leaves it EMPTY and every bundle path becomes a phantom `/.prflow/tmp/pr-N…` path.
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
```

Then, for each `pattern` in `to_act` — with `SLUG`/`TAG`/`CATEGORY` and the
`.prflow/tmp/pattern-${SLUG}.json` file already derived and written above —
select the most-recent-N occurrence PRs and fetch only their bundles, tracking **three distinct
quantities** — *selected* (the post-cap set size), *delivered* (the bundles Stage B
actually receives, after excluding any that failed to fetch), and *total*
(`occurrence_count`):

```bash
# TOTAL is occurrence_count, falling back to the occurrences[] length. SELECTED_PRS
# are the most-recent AUDIT_BUNDLE_CAP occurrence PRs in DESCENDING ts order — the
# emitted order is fact the dispatch prompt states.
# `dispatch` carries the no-dispatch floor: 8b/8c act only on patterns whose
# `dispatch` is still 1 here. Start optimistic; clear it on any arm that leaves the
# pattern without evidence.
dispatch=1
# The jq `// 0` protects a null FIELD, not a failed invocation. Unknown is not zero —
# an unestablished TOTAL is recorded and the truncation entry skipped, never
# fabricated from a laundered 0.
TOTAL="$($LIB/../scripts/run-jq.sh -r '(.occurrence_count // (.occurrences // [] | length)) // 0' ".prflow/tmp/pattern-${SLUG}.json" 2>/dev/null || true)"
case "$TOTAL" in
    ''|*[!0-9]*)
        blockers+=("Pattern ${SLUG}: the occurrence total could not be established (got '${TOTAL}') — truncation reporting skipped for this pattern")
        TOTAL="" ;;
esac
# Fail CLOSED on a selector failure. Without this arm the loop below never runs and
# the run blames `gh` for a config-/corpus-shape defect; the `::error::` the helper
# already wrote to stderr carries the real cause.
SELECTED_PRS="$(devflow_select_audit_bundles "$AUDIT_BUNDLE_CAP" "$pattern")" || {
    blockers+=("Pattern ${SLUG}: occurrence selection failed — see the audit-bundle-selection ::error:: above for the cause; not dispatched to Stage B and not filed")
    SELECTED_PRS=""
    dispatch=0
}
selected=0; delivered=0; bundle_paths=()
for n in $SELECTED_PRS; do
    selected=$((selected + 1))
    BUNDLE="$REPO_ROOT/.prflow/tmp/pr-${n}.context.json"
    # Use `-s`, not `-f`: an interrupted fetch leaves a zero-byte bundle that `-f`
    # would count as evidence. Test and deliver the SAME absolute string, or an
    # oddly-resolved REPO_ROOT passes the guard on one path and hands Stage B another.
    FETCH_ERR=""
    if [ ! -s "$BUNDLE" ]; then
        # Capture fetch-pr-context.sh's own diagnostics instead of discarding them:
        # an expired token, a deleted PR, an absent `gh` and a jq shape error are
        # fixed differently.
        FETCH_ERR="$(bash $LIB/fetch-pr-context.sh "$n" 2>&1 >/dev/null || true)"
    fi
    if [ -s "$BUNDLE" ]; then
        delivered=$((delivered + 1))
        bundle_paths+=("$BUNDLE")
    else
        # A selected occurrence whose bundle is ABSENT (or zero-byte) after the fetch
        # attempt is excluded from the path array handed to Stage B and named in the
        # blockers — never a phantom path, and never counted as evidence. The blocker
        # quotes the fetcher's own diagnostic rather than guessing the cause.
        blockers+=("Pattern ${SLUG}: occurrence PR #${n} bundle could not be fetched — ${FETCH_ERR:-fetch-pr-context.sh produced no diagnostic} — excluded from Stage B evidence")
    fi
done
# delivered == 0 (every selected bundle failed to fetch): DO NOT dispatch this pattern
# to Stage B, record a blocker, and file NOTHING for it — an empty bundle set has Stage
# B re-derive a root cause from metadata alone and file an evidence-free issue.
# devflow_audit_dispatch_ok owns the decision; `dispatch` is what 8b/8c read.
if ! devflow_audit_dispatch_ok "$delivered"; then
    blockers+=("Pattern ${SLUG}: no occurrence bundle was delivered out of ${selected} selected — not dispatched to Stage B and not filed")
    dispatch=0
fi
# Truncation entry when Stage B was delivered fewer bundles than the pattern has
# occurrences. Carry `selected` too, so the renderer can name the fetch-failure gap
# (delivered < selected) distinctly from the cap-dropped gap. Built with jq so the
# element is valid JSON for the Step 9 slurp.
#
# Gated on `dispatch`: a pattern that was never dispatched contributed NO Stage B
# evidence, and its blocker above already covers it. Gated on a non-empty TOTAL too,
# since an unestablished total cannot establish a shortfall.
if [ "$dispatch" -eq 1 ] && [ -n "$TOTAL" ] && [ "$delivered" -lt "$TOTAL" ]; then
    # argjson-ok: delivered,total,selected -- bounded per-pattern counts, never corpus-sized operands
    TRUNC_ENTRY="$($LIB/../scripts/run-jq.sh -nc --arg tag "$TAG" \
        --argjson delivered "$delivered" --argjson total "$TOTAL" --argjson selected "$selected" \
        '{tag:$tag,delivered:$delivered,total:$total,selected:$selected}' 2>/dev/null || true)"
    # A failed build would otherwise append an EMPTY element that Step 9's
    # `map(select(. != null))` slurps away silently, losing the record with no
    # diagnostic. Record it as a blocker instead.
    if [ -n "$TRUNC_ENTRY" ]; then
        truncations+=("$TRUNC_ENTRY")
    else
        blockers+=("Pattern ${SLUG}: the truncation record could not be built (delivered=${delivered}, total=${TOTAL}, selected=${selected}) — this pattern is absent from the run report's truncation section")
    fi
fi
```

The per-pattern `bundle_paths` array (absolute paths, *delivered* only) is what 8b
dispatches. **A pattern whose `dispatch` is `0` — a selector failure, or no bundle
delivered — is excluded from the 8b dispatch set and from the 8c filing set alike;
its blocker is what the run report carries for it.**

#### 8b — Dispatch all Stage B subagents concurrently

Issue **one Agent call per pattern whose `dispatch` is `1`, all in a single
message** so they run in parallel. A pattern whose 8a fence cleared `dispatch` gets
no Agent call at all. No worktree is created or passed — the subagent makes no edits.
Each dispatched subagent's prompt:

> Read and follow
> `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../retrospective-audit/SKILL.md`
> exactly.
>
> Occurrence-PR context bundle paths (absolute): `<json array of DELIVERED paths>`
>
> Your bundle-path array is a capped, most-recent-first subset bounded by
> `audit_bundle_cap`: it holds `<delivered>` bundle(s) out of the pattern's
> `<total>` total occurrences. The pattern metadata's `occurrences[]` below remains
> the authoritative full list of occurrence PRs.
>
> Pattern metadata is on disk at the absolute path `<REPO_ROOT>/.prflow/tmp/pattern-<slug>.json` — read it with your file-read tool.
>
> Consumer prompt-extension handoff: your extension file for this skill is at the
> absolute path `<REPO_ROOT>/.prflow/prompt-extensions/retrospective-audit.md`.
> Read it with your file-read tool and honor any content as instructions appended
> to the retrospective-audit skill's own prompt. If the file is absent or empty,
> treat it as a no-op and report nothing about it; if it is present but you cannot
> read it, report that via the optional `extension_unreadable` key in your returned
> JSON object.
>
> Bundled-helper root: the plugin is at the absolute path `<PLUGIN_ROOT>`. Use that
> value wherever the retrospective-audit brief writes `[[PLUGIN_ROOT]]` — for example
> `[[PLUGIN_ROOT]]/scripts/run-jq.sh`. Resolve no skill-directory anchor of your own.
>
> Make no edits and no worktree. Print exactly one JSON object (the
> `findings`-array return contract from § 5 of that skill) and nothing else
> on stdout.

Resolve `<REPO_ROOT>` and `<PLUGIN_ROOT>` before dispatch (by-value handoff). As in
Step 4, a subagent resolves no anchor of its own, so you (the orchestrator) resolve
both and substitute them into the handoff sentences above:

- `<REPO_ROOT>` — `git rev-parse --show-toplevel` (the pattern-metadata path and the prompt-extension path).
- `<PLUGIN_ROOT>` — resolved exactly as in Step 4, with the first handoff sentence's anchor-relative path to the brief resolved at emission too.

Append the sentences unconditionally, run no probe, and read no extension file
yourself — no extension content enters this orchestrator's context. `<PLUGIN_ROOT>` names
a bundled helper the child executes (`[[PLUGIN_ROOT]]/scripts/run-jq.sh`), so the
child's tier must grant that helper.

Wait for all subagents to finish. Pair each result JSON with its pattern.

#### 8c — File one issue per selected finding (serial, under the filing back-pressure caps)

The filing set is the patterns 8b dispatched — those whose `dispatch` is `1`. A
pattern excluded by the 8a floor never reaches a cap decision and appears in the run
report through its 8a blocker rather than under a filing-cap heading.

Before filing, read the three back-pressure caps, and source the helper that owns
both the open-issue counts and the cap decision. The counts are derived from the
`overrides.json` lifecycle records — the meta-issue entries whose reconciled state is
`filed` — never from a label query or a title parse, so a human-applied label cannot
consume the loop's budget:

```bash
MAX_PER_RUN="$(bash $LIB/../scripts/config-get.sh '.prflow_retrospective.max_issues_per_run' 3)"
MAX_OPEN="$(bash $LIB/../scripts/config-get.sh '.prflow_retrospective.max_open_issues' 10)"
MAX_PER_CAT="$(bash $LIB/../scripts/config-get.sh '.prflow_retrospective.max_open_per_category' 2)"
# Validate the caps HERE, once, before any pattern is judged. config-get.sh coerces
# whatever JSON the key holds into a string, so a single config typo withholds EVERY
# pattern as `invalid-operand` and the report renders that as ordinary back-pressure.
# Abort and name the offending key instead.
case "$MAX_PER_RUN" in
  ''|*[!0-9]*) echo "::error::retrospective Step 8c: .prflow_retrospective.max_issues_per_run is not a count (got '$MAX_PER_RUN') — aborting rather than withholding every pattern behind an invalid-operand verdict that would read as back-pressure" >&2
     exit 1 ;;
esac
case "$MAX_OPEN" in
  ''|*[!0-9]*) echo "::error::retrospective Step 8c: .prflow_retrospective.max_open_issues is not a count (got '$MAX_OPEN') — aborting rather than withholding every pattern behind an invalid-operand verdict that would read as back-pressure" >&2
     exit 1 ;;
esac
case "$MAX_PER_CAT" in
  ''|*[!0-9]*) echo "::error::retrospective Step 8c: .prflow_retrospective.max_open_per_category is not a count (got '$MAX_PER_CAT') — aborting rather than withholding every pattern behind an invalid-operand verdict that would read as back-pressure" >&2
     exit 1 ;;
esac
# Both cap comparands come from `lib/filing-decisions.sh`, never from inline jq here.
# Source it at top level so its functions persist in this shell; that is safe only
# because the helper sets NO shell options. If you ever add options to it, source it in
# a subshell instead — a leaked `set -euo pipefail` aborts this orchestrator.
source $LIB/filing-decisions.sh || {
  echo "::error::retrospective: lib/filing-decisions.sh could not be sourced — the filing decisions have no owner; aborting rather than silently withholding every pattern" >&2
  exit 1
}
# Initialize the per-run counter EXPLICITLY. Left unset it expands empty, which
# devflow_filing_cap_verdict rejects as `invalid-operand`, withholding every pattern
# for the whole run.
filed_this_run=0
```

`filed_this_run` is the only counter this orchestrator carries across patterns;
increment it after each successful filing. The two `filed`-count comparands — the
whole-file total and the per-category count for the slug — are **re-derived from the
overrides file inside the per-pattern block below**, not tracked here, so they cannot
drift. A `meta-issue.sh` recovery-path filing (create succeeded, lifecycle write failed
— exit 0 + URL + a loud `::error::`) is missed by that fresh read but still counted by
`filed_this_run`.

Both count helpers fail closed by printing nothing — never `0` — when the
overrides file is missing, unreadable, or malformed. Do not default an empty
count to `0`: `devflow_filing_cap_verdict` reads the empty operand as
`invalid-operand` and withholds, whereas a laundered `0` would report an empty
backlog and file straight past both caps.

The pre-filing overrides snapshot Step 9 reads (`.prflow/tmp/overrides-prefiling.json`)
is taken in Step 6, not here — Step 8 is skipped when nothing is actionable, while
Step 9 reads it unconditionally.

For each `(pattern, result)` pair, bind `$STATUS` once — the operand both
`select-findings.sh` and the legacy cap check key the `regressed` bypass off. An
unbound `$STATUS` expands empty, leaving the bypass dead at runtime:

```bash
STATUS="$($LIB/../scripts/run-jq.sh -r --arg t "$TAG" '.[] | select((.tag // .slug) == $t) | .status' .prflow/tmp/patterns.json)"
case "$STATUS" in
  dismissed|regressed|declined|filed|fixed|open) : ;;
  *) echo "::error::retrospective Step 8c: could not bind a lifecycle status for pattern '$TAG' (got '$STATUS') — refusing to file on an unestablished status, which would silently disable the regressed bypass" >&2
     exit 1 ;;
esac
```

Dispatch on the Stage B result's SHAPE. Write the subagent's raw
result to `.prflow/tmp/result-${SLUG}.json` with the **Write tool** first (it can
contain quotes, backticks, newlines, and `$` — never interpolate it inline into a
shell command). Then:

- A result carrying a `findings` array → the normal path. `lib/select-findings.sh`
  is the owner of the selection on this path: it composes and legality-checks
  each `<category>-<subslug>` key through the composer, aliases a churned subslug onto
  an existing lifecycle record of the same category (equal token set), ranks by
  descending evidence-PR count and truncates to the top three, and asks
  `devflow_filing_cap_verdict` for each finding's cap decision (passing the
  running `filed_this_run`). You do
  not re-derive the per-category or open-total comparands here — the helper owns
  them. An empty `findings` array files nothing and records a per-pattern report
  line, distinct from the malformed blocker.
- A result carrying a top-level `title` and `body` and no `findings` array → the
  deployed-subagent coexistence path: treat it as one finding with an absent subslug
  and file under the bare category key (`--tag`/`--slug` = `$SLUG`), cap-checked
  exactly as at HEAD.
- A result carrying neither a `findings` array nor a `title`/`body` pair → the
  existing malformed blocker; file nothing.

You increment `filed_this_run` once per issue filed (not per pattern), and append
the pattern's coarse tag `$SLUG` — once per pattern that filed anything, never the
composed key — to `filed_slugs` for Step 9's annotation, which indexes on the coarse
`.tag // .slug` a composed key can never equal.

```bash
# Keep the wrapper precheck a SEPARATE single-statement branch (no rc carried across
# statements), so an unexpanded $LIB or missing run-jq.sh reads as the anchor failure it
# is, not a malformed subagent result. `[ ! -x ]` (not `[ ! -e ]`) also catches a
# present-but-non-executable wrapper.
if [ ! -x "$LIB/../scripts/run-jq.sh" ]; then
    blockers+=("Pattern ${SLUG}: run-jq.sh wrapper not found or not executable (unexpanded \$LIB notation, missing wrapper, or lost +x bit; fix the anchor) — not filed")

# Relay a child-reported unreadable consumer extension — informational,
# never blocks filing, and read on every non-anchor shape.
elif $LIB/../scripts/run-jq.sh -e '(.findings | type) == "array"' < ".prflow/tmp/result-${SLUG}.json" >/dev/null 2>&1; then
    # ── Findings-array path: select-findings owns the selection ──
    EXT_UNREADABLE="$($LIB/../scripts/run-jq.sh -r '.extension_unreadable // empty' < ".prflow/tmp/result-${SLUG}.json")"
    [ -n "$EXT_UNREADABLE" ] && echo "::warning::retrospective Stage B (pattern ${SLUG}): consumer prompt extension for retrospective-audit present but unreadable: ${EXT_UNREADABLE}" >&2
    if [ "$($LIB/../scripts/run-jq.sh -r '.findings | length' < ".prflow/tmp/result-${SLUG}.json")" -eq 0 ]; then
        # Empty findings array: file nothing, record a per-pattern report LINE —
        # distinct from the malformed blocker.
        skip_records+=("Pattern ${SLUG}: Stage B returned an empty findings array — nothing to file for this pattern")
    else
        # Ask select-findings which findings become filings; it returns the to-file
        # array on stdout. A NON-ZERO exit is a withhold-everything condition and names
        # the cause on its own ::error:: channel.
        $LIB/../scripts/run-jq.sh -c '.findings' < ".prflow/tmp/result-${SLUG}.json" > ".prflow/tmp/findings-${SLUG}.json"
        # GUARD the source: an unsourceable select-findings.sh would otherwise be
        # misreported by the `else` arm below as its withhold-everything condition.
        # --withheld-file: a JSON array of {tag, cap} for every finding a cap held
        # back, read back into `withheld` below.
        # --dropped-file: likewise for the top-three truncation, whose notice is
        # otherwise stderr-only and never reaches the run report.
        if ! source $LIB/select-findings.sh; then
            blockers+=("Pattern ${SLUG}: could not source lib/select-findings.sh (missing, unreadable, or a syntax error) — nothing filed for this pattern")
        elif ! devflow_projection_eligible_findings ".prflow/tmp/findings-${SLUG}.json" ".prflow/tmp/projection-dropped-${SLUG}.json" > ".prflow/tmp/findings-projected-${SLUG}.json"; then
            blockers+=("Pattern ${SLUG}: the Stage B projection gate could not establish eligibility — nothing filed for this pattern")
        elif ! mv ".prflow/tmp/findings-projected-${SLUG}.json" ".prflow/tmp/findings-${SLUG}.json"; then
            blockers+=("Pattern ${SLUG}: the projection-filtered finding set could not replace its input — nothing filed for this pattern")
        else
            if [ -s ".prflow/tmp/projection-dropped-${SLUG}.json" ]; then
                while IFS= read -r _pd; do
                    [ -n "$_pd" ] && blockers+=("Pattern ${SLUG}: finding $($LIB/../scripts/run-jq.sh -r '.subslug' <<< "$_pd") omitted before filing because its projection disposition was missing, inconsistent, or unmatched")
                done < <($LIB/../scripts/run-jq.sh -c '.[]' < ".prflow/tmp/projection-dropped-${SLUG}.json")
            fi
          if TO_FILE="$(devflow_select_findings \
                --category "$CATEGORY" \
                --findings-file ".prflow/tmp/findings-${SLUG}.json" \
                --overrides .prflow/learnings/overrides.json \
                --status "$STATUS" \
                --filed-this-run "$filed_this_run" \
                --max-per-run "$MAX_PER_RUN" \
                --max-per-cat "$MAX_PER_CAT" \
                --max-open "$MAX_OPEN" \
                --withheld-file ".prflow/tmp/withheld-${SLUG}.json" \
                --dropped-file ".prflow/tmp/dropped-${SLUG}.json")"; then
            # Fold each cap-withheld finding into `withheld` so Step 9 reports it under
            # "withheld by a filing cap".
            if [ -s ".prflow/tmp/withheld-${SLUG}.json" ]; then
                while IFS= read -r _wh; do
                    [ -n "$_wh" ] && withheld+=("$_wh")
                done < <($LIB/../scripts/run-jq.sh -c '.[]' < ".prflow/tmp/withheld-${SLUG}.json")
            fi
            # Fold a truncation record into `skip_records` so the run names the pattern
            # and the count Stage B returned but this selection dropped.
            if [ -s ".prflow/tmp/dropped-${SLUG}.json" ]; then
                while IFS= read -r _dr; do
                    [ -n "$_dr" ] && skip_records+=("Pattern ${SLUG}: Stage B returned $($LIB/../scripts/run-jq.sh -r '.total' <<< "$_dr") findings — kept the top 3 by evidence-PR count, dropped $($LIB/../scripts/run-jq.sh -r '.dropped' <<< "$_dr")")
                done < <($LIB/../scripts/run-jq.sh -c '.[]' < ".prflow/tmp/dropped-${SLUG}.json")
            fi
            FINDINGS_N="$(printf '%s' "$TO_FILE" | $LIB/../scripts/run-jq.sh 'length')"
            # A pattern whose findings all drop as stderr-only breadcrumbs, with no
            # cap withhold and no truncation, would otherwise leave no report trace.
            # Test array EMPTINESS BY CONTENT via run-jq.sh's length, not file size:
            # devflow_select_findings defaults both files to `[]`, so `[ ! -s … ]` is
            # always false.
            _WH_N="$($LIB/../scripts/run-jq.sh 'length' < ".prflow/tmp/withheld-${SLUG}.json" 2>/dev/null || echo 0)"
            _DR_N="$($LIB/../scripts/run-jq.sh 'length' < ".prflow/tmp/dropped-${SLUG}.json" 2>/dev/null || echo 0)"
            if [ "${FINDINGS_N:-0}" -eq 0 ] && [ "${_WH_N:-0}" -eq 0 ] && [ "${_DR_N:-0}" -eq 0 ]; then
                skip_records+=("Pattern ${SLUG}: select-findings.sh selected 0 findings to file (no cap withhold, no top-three truncation) — every returned finding was individually dropped; see its stderr breadcrumbs for which check")
            fi
            _fi=0
            _pattern_filed=0   # reset PER PATTERN — a stale 1 from the previous pattern
                               # would annotate this one as filed on a run that filed nothing
            while [ "$_fi" -lt "$FINDINGS_N" ]; do
                # $KEY is the composed (or aliased) opaque filing key; it passes as
                # BOTH --tag and --slug (they share the [A-Za-z0-9_-]+ grammar the key
                # already satisfies), with the attribution --category alongside.
                KEY="$(printf '%s' "$TO_FILE" | $LIB/../scripts/run-jq.sh -r ".[$_fi].key")"
                printf '%s' "$TO_FILE" | $LIB/../scripts/run-jq.sh -r ".[$_fi].body"  > ".prflow/tmp/issue-body-${KEY}.md"
                F_TITLE="$(printf '%s' "$TO_FILE" | $LIB/../scripts/run-jq.sh -r ".[$_fi].title")"
                if ISSUE_URL="$(bash $LIB/meta-issue.sh --tag "$KEY" --slug "$KEY" --category "$CATEGORY" --title "$F_TITLE" --body-file ".prflow/tmp/issue-body-${KEY}.md" --overrides .prflow/learnings/overrides.json)"; then
                    intervention_issues+=("$($LIB/../scripts/run-jq.sh -nc --arg key "$KEY" --arg cat "$CATEGORY" --arg url "$ISSUE_URL" '{key:$key,category:$cat,url:$url}')")
                    filed_this_run=$((filed_this_run + 1))
                    _pattern_filed=1
                else
                    blockers+=("Finding ${KEY} (category ${CATEGORY}): meta-issue.sh failed to file the issue — not filed")
                fi
                _fi=$((_fi + 1))
            done
            # Push the coarse $SLUG once per pattern, never a composed
            # `<category>-<subslug>` key: Step 9's `devflow_annotate_patterns` indexes
            # on `.tag // .slug` and would annotate every filed pattern as "not filed".
            [ "${_pattern_filed:-0}" -eq 1 ] && filed_slugs+=("$SLUG")
            # Same domain mismatch on the withheld side: `$wmap` is looked up by the
            # coarse tag. When a cap held back EVERY finding of this pattern, add one
            # coarse-tag entry so the pattern row still renders `withheld_by`.
            if [ "${_pattern_filed:-0}" -ne 1 ] && [ -s ".prflow/tmp/withheld-${SLUG}.json" ]; then
                _FIRST_CAP="$($LIB/../scripts/run-jq.sh -r '.[0].cap // empty' < ".prflow/tmp/withheld-${SLUG}.json")"
                [ -n "$_FIRST_CAP" ] && withheld+=("$($LIB/../scripts/run-jq.sh -nc --arg tag "$SLUG" --arg cap "$_FIRST_CAP" '{tag:$tag,cap:$cap}')")
            fi
        else
            # devflow_select_findings returns 2 for a wiring/argument fault and 1 for
            # every withhold-everything condition it decides on the pattern's data.
            # Branch on the code, or a wiring regression reads as back-pressure.
            _SF_RC=$?
            if [ "$_SF_RC" -eq 2 ]; then
                blockers+=("Pattern ${SLUG}: select-findings.sh refused the call (wiring/argument fault, exit 2) — see its ::error:: breadcrumb for the missing/empty flag; nothing filed")
            else
                blockers+=("Pattern ${SLUG}: select-findings.sh withheld every finding (cap owner unsourceable, or overrides unreadable/unmigrated — see its ::error:: breadcrumb) — nothing filed")
            fi
          fi
        fi
    fi

elif $LIB/../scripts/run-jq.sh -e '.title and .body' < ".prflow/tmp/result-${SLUG}.json" >/dev/null 2>&1; then
    # ── Legacy title/body coexistence path: bare category key, cap-checked ────
    EXT_UNREADABLE="$($LIB/../scripts/run-jq.sh -r '.extension_unreadable // empty' < ".prflow/tmp/result-${SLUG}.json")"
    [ -n "$EXT_UNREADABLE" ] && echo "::warning::retrospective Stage B (pattern ${SLUG}): consumer prompt extension for retrospective-audit present but unreadable: ${EXT_UNREADABLE}" >&2
    if ! $LIB/../scripts/run-jq.sh -e -f $LIB/projection-gate.jq < ".prflow/tmp/result-${SLUG}.json" >/dev/null 2>&1; then
      blockers+=("Pattern ${SLUG}: legacy Stage B result omitted because its projection disposition was missing, inconsistent, or unmatched — not filed")
    elif ! source $LIB/filing-decisions.sh; then
      echo "::error::retrospective: lib/filing-decisions.sh could not be sourced — the filing decisions have no owner; aborting rather than silently withholding" >&2
      exit 1
    else
    PER_CAT="$(devflow_open_filed_for_category .prflow/learnings/overrides.json "$CATEGORY")"
    case "$PER_CAT" in
      ''|*[!0-9]*) echo "::error::retrospective Step 8c: could not derive the per-category filed count for category '$CATEGORY' (got '$PER_CAT') — the overrides file is missing, unreadable, or malformed; aborting rather than withholding every pattern behind an invalid-operand verdict that would read as back-pressure" >&2
           exit 1 ;;
    esac
    OPEN_TOTAL="$(devflow_open_filed_total .prflow/learnings/overrides.json)"
    case "$OPEN_TOTAL" in
      ''|*[!0-9]*) echo "::error::retrospective Step 8c: could not derive the total filed count (got '$OPEN_TOTAL') — the overrides file is missing, unreadable, or malformed; aborting rather than withholding every pattern behind an invalid-operand verdict that would read as back-pressure" >&2
           exit 1 ;;
    esac
    VERDICT="$(devflow_filing_cap_verdict "$STATUS" "$filed_this_run" "$MAX_PER_RUN" "$PER_CAT" "$MAX_PER_CAT" "$OPEN_TOTAL" "$MAX_OPEN")"
    if [ "$VERDICT" = file ]; then
        $LIB/../scripts/run-jq.sh -r '.body' < ".prflow/tmp/result-${SLUG}.json" > ".prflow/tmp/issue-body-${SLUG}.md"
        TITLE="$($LIB/../scripts/run-jq.sh -r '.title' < ".prflow/tmp/result-${SLUG}.json")"
        if ISSUE_URL="$(bash $LIB/meta-issue.sh --tag "$SLUG" --slug "$SLUG" --category "$CATEGORY" --title "$TITLE" --body-file ".prflow/tmp/issue-body-${SLUG}.md" --overrides .prflow/learnings/overrides.json)"; then
            intervention_issues+=("$($LIB/../scripts/run-jq.sh -nc --arg key "$SLUG" --arg cat "$CATEGORY" --arg url "$ISSUE_URL" '{key:$key,category:$cat,url:$url}')")
            filed_this_run=$((filed_this_run + 1)); filed_slugs+=("$SLUG")
        else
            blockers+=("Pattern ${SLUG}: meta-issue.sh failed to file the issue — not filed")
        fi
    else
        # Build the element with jq so what lands in `withheld` is valid JSON (Step 9
        # slurps it with `run-jq.sh -sc`).
        withheld+=("$($LIB/../scripts/run-jq.sh -nc --arg tag "$SLUG" --arg cap "$VERDICT" '{tag:$tag,cap:$cap}')")
    fi
    fi

else
    # Neither shape: record a blocker and file NOTHING (load-bearing failure path).
    blockers+=("Pattern ${SLUG}: Stage B subagent returned malformed JSON (neither a findings array nor a title/body pair) — not filed")
fi
```

Never report a pattern as filed when it was not. A malformed Stage B result
or a `meta-issue.sh` non-zero exit records a per-pattern blocker and the run
continues to the next pattern; the pattern is absent from `intervention_issues`.

Do not post `/prflow:implement` (or any auto-trigger comment) on a filed
issue — filed issues await human triage.

(`meta-issue.sh` mutates `.prflow/learnings/overrides.json` in your `main`
checkout's working tree. That happens after the Step 7 state PR was opened,
so the new lifecycle record lands in next week's state PR — see § Notes for the optional
follow-up commit if you want it in this run's PR.)

---

### Step 9 — Status report

Collect the per-analyzed-PR digest lines (verdict + a one-line summary) and the
unfiltered whole-pattern view produced by `actionable-patterns.sh --full` in
Step 6 (`patterns-full.json`) — every pattern with its lifecycle status
(`filed`/`fixed`/`declined`/`regressed`/`open`/`dismissed`), including the
suppressed and below-threshold ones:

```bash
ANALYZED_JSON="$($LIB/../scripts/run-jq.sh -sc -f "$LIB/analyzed-digest.jq" .prflow/tmp/new-entries.jsonl)"
# The report's `.patterns` is the UNFILTERED whole-pattern view (patterns-full.json),
# not the filtered actionable list, or the report reads like a quiet week.
# Annotate that view with each pattern's filing outcome and, where a cap withheld it,
# that cap: the `--full` view carries neither, so without this join both fields render
# nothing on every pattern.
source $LIB/filing-decisions.sh || {
  echo "::error::retrospective: lib/filing-decisions.sh could not be sourced — the filing decisions have no owner; aborting rather than silently withholding every pattern" >&2
  exit 1
}
FILED_SLUGS_JSON="$(printf '%s\n' "${filed_slugs[@]:-}" | $LIB/../scripts/run-jq.sh -sRc 'split("\n") | map(select(. != ""))')"
WITHHELD_JSON="$(printf '%s\n' "${withheld[@]:-}" | $LIB/../scripts/run-jq.sh -sc 'map(select(. != null))')"
PATTERNS_JSON="$(devflow_annotate_patterns .prflow/tmp/patterns-full.json "$FILED_SLUGS_JSON" "$WITHHELD_JSON")"
RECURRING_TARGETS_JSON="$(bash $LIB/recurring-targets.sh .prflow/learnings/retrospectives.jsonl)"

# The liveness line actionable-patterns.sh wrote to stderr in Step 6, and the
# won't-fix patterns this run re-raised — the two remaining report sections. Both are
# empty on a run that produced neither, and render-report.sh omits their sections.
LIVENESS_WARNING="$(devflow_liveness_warning .prflow/tmp/patterns.stderr)"
DECLINED_REFILED_JSON="$(devflow_declined_refiled .prflow/tmp/overrides-prefiling.json "$FILED_SLUGS_JSON")"

# Truncation entries: the {tag, delivered, total, selected} objects Step 8a appended
# for every pattern the audit_bundle_cap (or a fetch failure) truncated. Assembled into
# a shell variable guarded by :? and passed with --slurpfile, the same carrier shape the
# `withheld` array uses. `[]` at minimum on a run that truncated nothing.
TRUNCATIONS_JSON="$(printf '%s\n' "${truncations[@]:-}" | $LIB/../scripts/run-jq.sh -sc 'map(select(. != null))')"

# Filing-queue aggregate operands, derived HERE in Step 9 — not reusing Step 8c's
# OPEN_TOTAL/MAX_OPEN, a stale pre-filing snapshot. Both pass as --arg STRINGS, so an
# unestablished value is the empty string, rendered `unavailable` and never laundered
# to 0; neither is :?-guarded, because empty is a valid state here.
FILING_QUEUE_OPEN="$(devflow_open_filed_total .prflow/learnings/overrides.json)"
FILING_QUEUE_MAX="$(bash $LIB/../scripts/config-get.sh '.prflow_retrospective.max_open_issues' 10)"
```

`recurring-targets.sh` groups every accumulated entry's
`suggested_interventions[].candidate_targets[]` by exact target path and emits
only the targets named in ≥2 distinct PRs (report-only; `[]` when nothing
recurs, which `render-report.sh` then omits).

Build the summary JSON and assign it to `$SUMMARY_JSON`:

```bash
# Route the corpus-sized operands (the --slurpfile flags below) through files rather
# than --argjson argv slots: they grow with the corpus and, as argv slots, overflow the
# kernel arg limit at scale (jq: "Argument list too long"). --slurpfile wraps
# each file in a one-element array, so the jq program dereferences [0].
_SUMMARY_TMP="$(mktemp -d)"
trap 'rm -rf "$_SUMMARY_TMP"' EXIT
# Preserve --argjson's fail-loud-on-empty semantics after the --slurpfile switch:
# an empty operand slurps to []→[0]=null (silent) where --argjson aborted loud. These
# three are upstream producer output, valid JSON ([] at minimum) on success — an empty
# string means that producer failed, so fail loud rather than emit analyzed/patterns:null.
: "${ANALYZED_JSON:?devflow retrospective Step 9: ANALYZED_JSON is empty — upstream Stage-A analysis failed}"
: "${PATTERNS_JSON:?devflow retrospective Step 9: PATTERNS_JSON is empty — devflow_annotate_patterns printed nothing over .prflow/tmp/patterns-full.json (missing, empty, or unreadable)}"
: "${RECURRING_TARGETS_JSON:?devflow retrospective Step 9: RECURRING_TARGETS_JSON is empty — recurring-targets.sh failed}"
# Same fail-loud property for the two operands: both helpers print at
# minimum `[]` on success, so an empty string is producer failure, not "nothing
# to report". (LIVENESS_WARNING is deliberately NOT guarded — an empty string is
# its normal no-warning value, and it is passed as --arg, never slurped.)
: "${WITHHELD_JSON:?devflow retrospective Step 9: WITHHELD_JSON is empty — the Step 8c withheld producer failed}"
: "${DECLINED_REFILED_JSON:?devflow retrospective Step 9: DECLINED_REFILED_JSON is empty — devflow_declined_refiled failed}"
: "${TRUNCATIONS_JSON:?devflow retrospective Step 9: TRUNCATIONS_JSON is empty — the Step 8a truncation producer failed}"
printf '%s\n' "${skip_records[@]:-}"        | $LIB/../scripts/run-jq.sh -sRc 'split("\n") | map(select(. != ""))' > "$_SUMMARY_TMP/skips.json"
printf '%s' "$ANALYZED_JSON"                > "$_SUMMARY_TMP/analyzed.json"
printf '%s' "$PATTERNS_JSON"                > "$_SUMMARY_TMP/patterns.json"
printf '%s' "$RECURRING_TARGETS_JSON"       > "$_SUMMARY_TMP/recurring_targets.json"
printf '%s\n' "${intervention_issues[@]:-}" | $LIB/../scripts/run-jq.sh -sc '.' > "$_SUMMARY_TMP/intervention_issues.json"
printf '%s\n' "${cooldown_skipped[@]:-}"    | $LIB/../scripts/run-jq.sh -sc '.' > "$_SUMMARY_TMP/cooldown_skipped.json"
# blockers carry RAW PROSE, so slurp them with the raw `-sRc split` shape (like
# `skips`), NOT the JSON `-sc '.'` slurp — under which a prose element is a jq parse
# error that empties blockers.json, trips the empty-file guard, and aborts the run,
# losing every blocker.
printf '%s\n' "${blockers[@]:-}"            | $LIB/../scripts/run-jq.sh -sRc 'split("\n") | map(select(. != ""))' > "$_SUMMARY_TMP/blockers.json"
# withheld_patterns: each {tag, cap} the Step-8 caps held back, and
# declined_refiled: the slugs whose meta-issue was previously closed NOT_PLANNED.
# Both are `[]` on a run that produced neither, which render-report omits.
printf '%s' "$WITHHELD_JSON"                > "$_SUMMARY_TMP/withheld_patterns.json"
printf '%s' "$DECLINED_REFILED_JSON"        > "$_SUMMARY_TMP/declined_refiled.json"
printf '%s' "$TRUNCATIONS_JSON"             > "$_SUMMARY_TMP/truncations.json"
# Same fail-loud property for the four INLINE producers above: their `> file` redirect
# truncates before the pipeline runs, so a failing jq leaves the file EMPTY, while on
# success each writes at minimum `[]` — so an empty file is unambiguously producer
# failure. Guard by file, not by variable, because these operands never pass through a
# shell variable.
for _op in skips intervention_issues cooldown_skipped blockers; do
  [ -s "$_SUMMARY_TMP/$_op.json" ] || {
    echo "devflow retrospective Step 9: $_op.json is empty — its inline jq producer failed" >&2
    rm -rf "$_SUMMARY_TMP"; exit 1
  }
done
# argjson-ok: prs_scanned, clean_count, analyzed_count, skipped_count, state_pr --
# bounded scalars (counts and one PR number) — safe as argv.
SUMMARY_JSON="$($LIB/../scripts/run-jq.sh -nc \
  --argjson prs_scanned           "$prs_scanned" \
  --argjson clean_count           "$clean_count" \
  --argjson analyzed_count        "$analyzed_count" \
  --argjson skipped_count         "$skipped_count" \
  --slurpfile skips               "$_SUMMARY_TMP/skips.json" \
  --slurpfile analyzed            "$_SUMMARY_TMP/analyzed.json" \
  --slurpfile patterns            "$_SUMMARY_TMP/patterns.json" \
  --slurpfile recurring_targets   "$_SUMMARY_TMP/recurring_targets.json" \
  --slurpfile intervention_issues "$_SUMMARY_TMP/intervention_issues.json" \
  --slurpfile cooldown_skipped    "$_SUMMARY_TMP/cooldown_skipped.json" \
  --slurpfile blockers            "$_SUMMARY_TMP/blockers.json" \
  --slurpfile withheld_patterns   "$_SUMMARY_TMP/withheld_patterns.json" \
  --slurpfile declined_refiled    "$_SUMMARY_TMP/declined_refiled.json" \
  --slurpfile truncations         "$_SUMMARY_TMP/truncations.json" \
  --arg       liveness_warning    "$LIVENESS_WARNING" \
  --arg       filing_queue_open   "$FILING_QUEUE_OPEN" \
  --arg       filing_queue_max    "$FILING_QUEUE_MAX" \
  --argjson state_pr              "$STATE_PR" \
  '{prs_scanned:$prs_scanned,clean_count:$clean_count,analyzed_count:$analyzed_count,
    skipped_count:$skipped_count,skips:$skips[0],
    analyzed:$analyzed[0],patterns:$patterns[0],recurring_targets:$recurring_targets[0],
    intervention_issues:$intervention_issues[0],
    cooldown_skipped:$cooldown_skipped[0],blockers:$blockers[0],
    withheld_patterns:$withheld_patterns[0],declined_refiled:$declined_refiled[0],
    truncations:$truncations[0],
    liveness_warning:$liveness_warning,
    filing_queue_open:$filing_queue_open,filing_queue_max:$filing_queue_max,
    state_pr:$state_pr}')"
rm -rf "$_SUMMARY_TMP"
```

(The `"${array[@]:-}"` form handles an empty bash array safely under `set -u`.)

Render the report markdown and post it as a comment on the state PR:

```bash
source $LIB/render-report.sh
devflow_render_report "$SUMMARY_JSON" > .prflow/tmp/report.md
# Buffer the implement-runtime section, append it before the report is posted, and gate that
# append on content rather than exit status: --retro exits 1 on an unreadable store while
# still writing the section that says so.
$LIB/../scripts/implement-run-report.py --retro > .prflow/tmp/implement-runtime.md || true
if [ -s .prflow/tmp/implement-runtime.md ]; then
  cat .prflow/tmp/implement-runtime.md >> .prflow/tmp/report.md
else
  printf '## Implement runtime trends\n\n_(section omitted — implement-run-report.py --retro produced no output)_\n' >> .prflow/tmp/report.md
fi
bash $LIB/post-status.sh --pr "$STATE_PR" --report-file .prflow/tmp/report.md
```

---

### Step 10 — Report to the user

Print the rendered report (`cat .prflow/tmp/report.md`) to the console.

Then list each item that needs human action:

- State PR (contains the updated retrospectives): `https://github.com/<repo>/pull/<state_pr>`
- Filed issues (one per actionable pattern, awaiting human triage): list
  each as `<tag>: <url>`

If there are any blockers, list them explicitly.

Tell the user:

> Review and merge the state PR once CI passes. Each filed issue awaits human
> triage — pick the ones worth acting on and run them through the normal
> implement → review pipeline; the loop never starts that for you. The loop is
> idempotent — re-running next week will only process new PRs not yet in
> `retrospectives.jsonl` on `main`, and a pattern already filed this cycle is
> not re-filed.

Do not run `gh pr merge --auto` on anything, and do not auto-start
implementation on a filed issue. The maintainer triages and merges manually
after reviewing.

---

## § Notes

- Overrides after Stage B. `meta-issue.sh` records each filed pattern's
  lifecycle entry in `.prflow/learnings/overrides.json` after the Step 7 state PR
  was opened, so the change lands in next week's state PR. To include it in *this*
  run's PR, after Step 8 push a follow-up commit onto the same
  `devflow/learnings-<date>` branch:

  ```bash
  if ! git diff --quiet HEAD -- .prflow/learnings/overrides.json 2>/dev/null; then
      LB="devflow/learnings-$(date -u +%F)"
      git fetch origin "$LB"
      git checkout "$LB"
      git add .prflow/learnings/overrides.json
      git commit -m "chore(devflow): add overrides from Stage B filed issues"
      git push --force-with-lease origin "$LB"
      git checkout main
  fi
  ```
- Never auto-merge, never auto-implement. The maintainer merges the state PR
  manually after CI, and triages each filed issue manually — the loop never
  starts an implement run for you.
- `actionable-patterns.sh` signature: takes two required positional args
  — `<retrospectives.jsonl>` and `<overrides.json>` — plus an optional third,
  `--full`, which emits the unfiltered whole-pattern view the run report
  renders. Always pass both required args; pass `--full` only for
  the report view. An unrecognized third argument is rejected with rc 2.
