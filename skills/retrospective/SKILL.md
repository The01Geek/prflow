---
name: retrospective
description: >
  Stage A of /prflow:retrospective-weekly: analyze one non-clean PR from its pre-fetched
  context bundle and return a retrospective entry as JSON. Invoked as a
  subagent — do not call it directly.
disable-model-invocation: true
---

# retrospective — Stage A subagent analysis brief

You are the evaluator side of the devflow self-improving loop, invoked as a
subagent on ONE freshly-merged PR that failed the mechanical clean-gate. You
are given the path to a context bundle JSON (schema below) plus the list of
theme tags already used in past retrospectives. Do **not** call `gh`. Do **not**
touch git. Do **not** write any file. Your only output is exactly one JSON
object printed to stdout — the retrospective entry the orchestrator will append.
Nothing else on stdout.

Configuration (handed to you by value — resolve nothing). Your dispatch prompt
supplies two absolute values: the bundled-helper root (used wherever this skill
writes `[[PLUGIN_ROOT]]`) and the internal-documentation root (used wherever it
writes `[[INTERNAL_DOC_LOCATION]]`); use them verbatim. Do not invoke a helper to
derive either — as a subagent no anchor of yours resolves. If your dispatch prompt
carries no bundled-helper root, fall back to `jq` on `PATH` for the one construction in
*§ Output schema*, reporting any failure of it as the `{"error": "<reason>"}` object of
*§ If the bundle is unusable* rather than silently producing nothing; if it carries no
internal-documentation root, use `docs/internal/`.
Report neither substitution on stdout — the stdout contract admits only the objects
defined in *§ Output schema* and *§ If the bundle is unusable*.

Read the bundle with:

```bash
BUNDLE="$(cat "$BUNDLE_PATH")"
```

---

Scope of the anchor rule in this brief. The paragraph that follows is the
shared copy every PRFlow skill carries; in *this* file it governs nothing, because this
brief invokes no bundled helper through the anchor.

**Portable helper anchor (single-statement).** The bundled-helper commands in this skill resolve the skill directory inline at each call site via `${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}`. When `$CLAUDE_SKILL_DIR` is set and non-empty (Claude Code), run each command exactly as written. On a runner where it is unset or empty, replace the placeholder with the skill base directory the runner reports in context (e.g. a `Base directory for this skill:` line); if that reported path is Windows-form (`C:\...`), first convert it to this shell's POSIX form with one standalone `wslpath -u '<path>'` (WSL) or `cygpath -u '<path>'` (Git Bash/MSYS2) command and substitute the printed result only if the command succeeds and prints a non-empty path — otherwise fall through to the drive-letter rules exactly as if the tool were absent (lowercase the drive letter, map `C:\` to `/mnt/c` on WSL or `/c` on MSYS2, and turn backslashes into `/`; if the environment is neither WSL nor MSYS2, use the path unchanged and report that it could not be normalized). Resolve the anchor inline at every call site — never capture it into a shell variable that a later statement reads, because some runners' inline-bash marshaling drops such variables. If neither `$CLAUDE_SKILL_DIR` nor a runner-reported base directory is available, stop and report that the helper anchor could not be resolved rather than running a command with a broken path.

Consumer prompt extension (handed to you by path). Before doing this skill's work,
read the consumer-supplied prompt extension for this skill and honor it — your dispatch
prompt names that file at an absolute `.prflow/prompt-extensions/retrospective.md` path.
Read it with your file-read tool — never a shell invocation, and never
`load-prompt-extension.sh`, whose anchor you cannot resolve. Treat any content as
instructions appended to the end of this skill's own prompt for this run. An absent or
empty file is a silent no-op; a present-but-unreadable file is reported through the
optional `extension_unreadable` key of *§ Output schema*. This subagent's stdout
contract is strict — exactly one JSON object — so a consumer extension
must not break that contract.

## § The context bundle

Schema of `.prflow/tmp/pr-<n>.context.json` produced by `fetch-pr-context.sh`:

| Key | Type | Description |
|-----|------|-------------|
| `pr` | number | PR number |
| `kind` | string | `"implementation"` |
| `branch` | string | Head branch name |
| `base_ref` | string | Base branch name |
| `head_sha` | string | Head commit SHA |
| `merge_commit_sha` | string | Merge commit SHA |
| `merged_at` | string | ISO-8601 merge timestamp |
| `created_at` | string | ISO-8601 PR creation timestamp |
| `author` | string | PR author login (`[bot]`-suffix stripped) |
| `title` | string | PR title |
| `body` | string | PR description body |
| `additions` | number | Lines added |
| `deletions` | number | Lines deleted |
| `changed_files` | array | List of changed file paths |
| `diffstat` | string | Summary: `"N files changed, +A -D"` |
| `diff` | string\|null | Full unified diff (null when over byte cap) |
| `diff_truncated` | boolean | True when diff was over the byte cap |
| `human_postbot_diff` | string\|null | Combined patch of commits AFTER the bot's last commit |
| `issue_number` | number\|null | Linked issue number (from branch name or body) |
| `issue` | object\|null | `{title, body, labels[], comments[{author,body,createdAt}]}` |
| `review_comments` | array | Inline diff comments: `[{author,body,path,line,createdAt}]` |
| `pr_comments` | array | PR conversation thread: `[{author,body,createdAt}]` |
| `pr_reviews` | array | Formal reviews: `[{author,state,body,submittedAt}]` |
| `commits` | array | `[{sha,author_login,committer_login,committed_at,message}]` |
| `workpad_body` | string\|null | Full text of the `<!-- prflow:workpad -->` comment, read from the **issue** thread (where the workpad lives), not the PR thread |
| `reflections` | array | The bullet lines from the workpad's `## Devflow Reflection` `<details>` block — the bot's own self-reported friction notes (`[]` when none) |
| `review_verdicts` | array | Verdict entries in time order, drawn from the **union** of the PR conversation comments and the durable bot PR reviews: `[{verdict,createdAt,source}]` where `verdict` is APPROVE or REJECT and `source` is `pr_comment` or `pr_review`. Any verdict heading in either source qualifies (not only `/prflow:review` output). |
| `implement_summary_comment` | string\|null | The `/prflow:implement` completion summary comment body |
| `signals` | object | See below |

`signals` sub-keys:

| Key | Type | Description |
|-----|------|-------------|
| `review_comments_count` | number | Total inline review comments |
| `post_bot_commits` | number | Substantive commits by a human AFTER the bot's last commit — pure merge commits (`Merge branch 'main'` etc.) are not counted |
| `ci_failures_during_pr` | number | Check-runs on the head SHA, across every page, whose conclusion is a real red signal — `failure`, `timed_out`, `action_required`, or any unrecognised conclusion (a denylist, so an unknown future one counts). Superseded runs (`cancelled`, `stale`) and `success`/`neutral`/`skipped`/still-running do not count. |
| `workpad_final_status` | string | Parsed Status line from the workpad, e.g. `"Complete"`, `"Blocked"`, `"Cancelled"`, or one of the absent/corrupt sentinels `"Unparsed"` / `"Absent"` / `"NoIssue"`. |
| `pr_devflow_provenance` | boolean | True iff the `PRFlow` provenance label (or its superseded `DevFlow` spelling) is on the PR or the resolved linked issue. |
| `ttm_hours` | number | Time from PR creation to merge, in decimal hours |
| `review_reject_outstanding` | boolean | True when the chronologically-last review verdict (from either conversation comments or durable PR reviews) is REJECT |

Source priority. The issue workpad is your highest-signal primary source,
and you treat each of its facets as primary analysis input:
- `reflections` — the bot's own `## Devflow Reflection` bullets. **Read every reflection bullet
  and let it drive the verdict, categories, and descriptors** — if this run
  left any reflection bullet, the cheap-gate forces it into analysis UNLESS
  every bullet is an informational `note`-kind (`ℹ️`) one (those are exempted
  and recorded verbatim on the clean path, not analyzed); every actionable
  kind — including `issue-accuracy` (`📝`) — still forces analysis.
- `signals.workpad_final_status` — the bot's final Status (`Complete` / `Blocked` / `Failed` / `Cancelled` / an interim state); it bounds the verdict (see below). `Failed` is the cloud stall backstop's dead-run flip: the run died mid-lifecycle rather than deciding an outcome. `Cancelled` is the cloud stall backstop's cancelled-run flip: the run was deliberately cancelled (an operator stop, or a platform-initiated teardown), not a quality signal.
- `workpad_body` — the full workpad, including the `## Progress` notes nested
  under each phase. Mine its append-only notes for the moment-to-moment story.

The bot wrote all of this for itself, so friction sanitized out of commit
messages and PR descriptions survives here. When the workpad conflicts with the
polished narrative elsewhere, favor the workpad and quote concrete passages.
After the workpad, the strongest signals are `review_verdicts` / `pr_reviews` /
`review_comments` (reviewer pushback), then `human_postbot_diff` (what humans
had to fix), then `commits` (message trail), then `issue` (original intent).

---

## § What you decide

### verdict

One of `imperfect` or `blocked`. (`clean` never reaches you — the orchestrator
handled those mechanically.)

- `imperfect` — the PR shipped but then needed substantive human commits
  after the bot's last commit (`signals.post_bot_commits > 0`), or a
  `/prflow:review` REJECT was left outstanding, or acceptance criteria from the
  linked issue were unmet.
- `blocked` — `signals.workpad_final_status == "Blocked"` or the workpad /
  PR thread shows work was abandoned mid-task with no shipped fix.

Interim workpad states (`Setup`, `Discovering`, `Reproducing`, `Planning`,
`Implementing`, `Reviewing`, `Documenting`) mean the run never reached Phase 4
— it is an incomplete run, not a quality issue. If `workpad_final_status` is one
of those, print `{"skip": "incomplete run — workpad_final_status is <status>; skipping"}` and stop.

A `Cancelled` final status takes a defined skip, not a `blocked` verdict: print
`{"skip": "operator-cancelled run — workpad_final_status is Cancelled; a deliberate stop, not a quality signal; skipping"}`
and stop.

Defined-skip vs. genuine-failure key. Both defined skips —
the interim-state skip and the `Cancelled` skip — emit a dedicated top-level
`"skip"` key carrying the reason. A genuine failure (you could not analyze the
bundle at all — a malformed bundle, a crash) still prints `{"error": "<reason>"}`.
The orchestrator recognizes a defined skip **by the presence of the `"skip"` key
only**, never by matching substrings of error text — so the two keys must stay
distinct and a skip must never be emitted under `"error"`.

Workpad-absent analysis rule. The absent-workpad sentinels
`"Absent"` (the linked issue resolved but carried no workpad comment) and
`"NoIssue"` (no linked issue resolved at all) are analyzed, never skipped. When
`workpad_final_status` is `"Absent"` or `"NoIssue"`:
- If `pr_devflow_provenance` is `true`, this was one of DevFlow's own runs that lost
  its audit trail (and, for `"NoIssue"`, its issue linkage). Analyze from the remaining
  evidence — the PR diff and commits, the reviews, and the issue thread when one
  resolved — and record the missing workpad (and, for `"NoIssue"`, the broken linkage)
  as friction in the entry's `descriptors`. Follow the existing `imperfect` / `blocked`
  verdict definitions; when neither strictly fits, default to `imperfect` with a
  descriptor naming the absent workpad.
- A sentinel bundle *without* provenance is analyzed under the same rule, minus the
  lost-audit-trail framing.

### categories

The single most important field — pattern detection groups occurrences by
`categories`. You must pick from this fixed vocabulary — every category that
genuinely applies, one or more. Do not coin new slugs: a unique slug forms
no pattern and the loop never acts on it. If nothing fits, use `other` and
explain why in `descriptors`.

| category | use when |
|---|---|
| `doc-accuracy` | a doc, comment, docstring, or release-note describes code that does not match what shipped (wrong file path/symbol/CSS class, stale count, "remaining" list that isn't, behavior that isn't there). |
| `fabricated-claim` | the PR description or release notes assert a deliverable that is **not in the diff** — a workflow, test, file, guard, or behavior that was never added. |
| `outstanding-reject` | the PR merged while its **chronologically-last** `/prflow:review` verdict was still REJECT — a review gate ran, landed a REJECT, and it was never cleared before merge. |
| `lenient-verdict` | a review / lint / typecheck gate **ran and returned an approve-family verdict**, but the PR shipped a defect that pass should have caught — a finding flagged then demoted-and-shipped, or a defect the gate passed over. Requires a gate to have *run*: a PR with no gate or review (e.g. a purely human-authored PR) is **not** this. |
| `deferred-verification` | a verification that was **runnable before merge** was deferred past the gate instead of run — e.g. a runnable acceptance criterion laundered into a `(post-merge)` tag, or a check punted to post-merge/CI that the orchestrator host could in fact have run. A check that genuinely needs a live runtime environment (deploy target, real third-party endpoint) is **not** this. |
| `unmet-acceptance-criteria` | the PR merged without satisfying an explicit requirement from the linked issue. |
| `incomplete-edit` | a partial change — an orphaned setup line after a deletion, a half-applied rename, a stale count not propagated, a leftover-after-removal artifact — i.e. the kind of thing a human had to clean up in `human_postbot_diff`. |
| `convention-violation` | the bot broke a project convention: a `CLAUDE.md` rule, a `phpcs.xml.dist`/lint rule, a skill instruction, or a workpad invariant. |
| `unverified-assumption` | the bot claimed something without checking it — a phantom symbol/class, "X already inherits Y so no edit needed", an unverified parent-component behavior, a wrong API rationale. |
| `issue-quality` | the bottleneck was upstream of implementation — the issue was vague, missing acceptance criteria, missing repro steps, or out of scope. |
| `tooling-gap` | the failure exposes a defect in the **devflow plugin itself**, its CI workflows, or the composite actions they consume (e.g. the clean-gate let an unclean PR through, a primary source was missing from the bundle, a workflow step is wrong). |
| `other` | none of the above fits; `descriptors` must say what the failure actually is. |

### descriptors

One or more short free-text phrases (no slug rules — write for a human reading
the weekly report) that say, concretely, *what* went wrong inside the chosen
category. e.g. for `incomplete-edit`: `"unused EnvironmentService fetch left in
NexioWebhook::handleEvent after the call site was deleted"`. Be specific; "code
quality issue" is useless.

### summary

Before composing this paragraph, read the shared writing standard at
`[[PLUGIN_ROOT]]/lib/writing-standard.md` with your file-read tool and follow it. If
it cannot be read, compose the summary without it and report nothing about it — a
breadcrumb here would violate the stdout contract.

One dense paragraph grounded in the bundle's primary sources. Quote the
workpad status, the `/prflow:review` verdict(s), what the human had to fix in
`human_postbot_diff` / `commits`, and which acceptance criteria slipped (if
any). The reader should understand what went wrong without opening the PR.

### suggested_interventions

Array of up to 2 objects. Consult `[[PLUGIN_ROOT]]/lib/intervention-surfaces.md` when
reasoning. Each object:

```json
{
  "summary": "Strengthen CLAUDE.md EntityService rule with a visible warning + linkable example",
  "candidate_targets": ["CLAUDE.md", "[[INTERNAL_DOC_LOCATION]]entity-service.md"],
  "change_type": "rule-strengthen",
  "confidence": "medium"
}
```

`change_type` ∈ `rule-strengthen | rule-add | doc-update | skill-update |
code-change | template-update | other`. `confidence` ∈ `low | medium | high`.

Plugin self-audit first. Before picking a surface, ask whether this pattern
reveals a flaw in the devflow plugin itself
(the engine's own files — `skills/**`, `agents/**`, `lib/**`, `scripts/**`) — if so, set `categories` to
include `tooling-gap` and point `suggested_interventions` at the plugin file:

- Workpad blind spot? Did `workpad_body` contain clear root-cause evidence
  that your classification missed? → `change_type: "skill-update"`,
  `candidate_targets: ["skills/retrospective/SKILL.md"]`.
- Clean-gate false negative? Did the PR nearly qualify as clean but the
  workpad shows a major abandoned design? → points at `lib/cheap-gate.jq`.
- Mis-categorized? Was the failure forced into `other` or into a category
  that doesn't really fit? → points at this skill's `categories` vocabulary.
- Cache miss? Was a primary source absent from the bundle that would have
  changed your verdict? → points at `fetch-pr-context.sh`.

If yes to any of the above, your intervention MUST target the plugin file
directly. Do not silently downgrade to a smaller surface — that hides the
blind spot that let the failure through.

---

## § Output schema

Construct the entry via `jq -n` — never hand-write JSON or use echo/heredoc
(review-comment text routinely contains backticks, backslashes, and raw
newlines that break naive serialization).

```json
{
  "schema_version": 2,
  "kind": "implementation",
  "pr": <bundle.pr>,
  "issue": <bundle.issue_number>,
  "merged_at": "<bundle.merged_at>",
  "branch": "<bundle.branch>",
  "head_sha": "<bundle.head_sha>",
  "merge_commit_sha": "<bundle.merge_commit_sha>",
  "verdict": "imperfect | blocked",
  "categories": ["...", "..."],
  "descriptors": ["...", "..."],
  "signals": <bundle.signals verbatim>,
  "summary": "...",
  "suggested_interventions": [{"summary":"...","candidate_targets":[...],"change_type":"...","confidence":"..."}]
}
```

Optional `extension_unreadable` key (consumer prompt-extension handoff).
When the consumer prompt-extension file is present but you cannot read it, add
one optional string key `extension_unreadable` to the object above, naming the path
and the read failure; the return stays exactly one JSON object with nothing else on
stdout. Omit the key entirely in every other case.

`categories` must be drawn from the fixed vocabulary above; `descriptors` is
free text. Echo `pr`, `issue`, `branch`, `head_sha`, `merge_commit_sha`,
`merged_at`, and `signals` straight from the bundle — do not recompute them.
Print the object and stop.

Example construction:

```bash
[[PLUGIN_ROOT]]/scripts/run-jq.sh -nc \
  --argjson bundle "$BUNDLE" \
  --arg verdict "$VERDICT" \
  --argjson categories "$CATEGORIES_JSON" \
  --argjson descriptors "$DESCRIPTORS_JSON" \
  --arg summary "$SUMMARY" \
  --argjson suggested_interventions "$SUGGESTED_INTERVENTIONS_JSON" \
  '{
    schema_version: 2,
    kind: "implementation",
    pr: $bundle.pr,
    issue: $bundle.issue_number,
    merged_at: $bundle.merged_at,
    branch: $bundle.branch,
    head_sha: $bundle.head_sha,
    merge_commit_sha: $bundle.merge_commit_sha,
    verdict: $verdict,
    categories: $categories,
    descriptors: $descriptors,
    signals: $bundle.signals,
    summary: $summary,
    suggested_interventions: $suggested_interventions
  }'
```

---

## § If the bundle is unusable

If the file at `$BUNDLE_PATH` is missing, empty, or not valid JSON, print:

```json
{"error": "<reason>"}
```

so the orchestrator can record a blocker and skip the PR. Do not attempt
partial analysis on a corrupt bundle.
