---
name: pr-description
description: Use when generating or updating a PR description for the current branch. Takes an optional issue number as argument.
argument-hint: <issue-number>
---

# /pr-description — Generate or Update PR Description

Generate a structured PR description by analyzing the current branch's changes against the base branch. When an existing PR is found, merges new content with human-added content instead of replacing it.

Input: `$ARGUMENTS` is an optional GitHub issue number. If provided, include a "Resolves #N" link.

**Portable helper anchor (single-statement).** The bundled-helper commands in this skill resolve the skill directory inline at each call site via `${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}`. When `$CLAUDE_SKILL_DIR` is set and non-empty (Claude Code), run each command exactly as written. On a runner where it is unset or empty, replace the placeholder with the skill base directory the runner reports in context (e.g. a `Base directory for this skill:` line); if that reported path is Windows-form (`C:\...`), first convert it to this shell's POSIX form with one standalone `wslpath -u '<path>'` (WSL) or `cygpath -u '<path>'` (Git Bash/MSYS2) command and substitute the printed result only if the command succeeds and prints a non-empty path — otherwise fall through to the drive-letter rules exactly as if the tool were absent (lowercase the drive letter, map `C:\` to `/mnt/c` on WSL or `/c` on MSYS2, and turn backslashes into `/`; if the environment is neither WSL nor MSYS2, use the path unchanged and report that it could not be normalized). Resolve the anchor inline at every call site — never capture it into a shell variable that a later statement reads, because some runners' inline-bash marshaling drops such variables. If neither `$CLAUDE_SKILL_DIR` nor a runner-reported base directory is available, stop and report that the helper anchor could not be resolved rather than running a command with a broken path.

Consumer prompt extension (load first). This skill's consumer extension reaches you through exactly one channel — the invocation ladder below — so load it yourself with that ladder, unconditionally, at the start of the run. Read the ladder's output whole — no `>/dev/null`, no `| head -<n>`, no truncation of any kind — because an extension whose text you never observed governs nothing in this run. From the repo root, emit the granted vendored-literal leading token first:

```bash
.prflow/vendor/prflow/scripts/load-prompt-extension.sh pr-description
```

On a `command not found` / `No such file` / exit-127 reading (this repository's own local tier, where `.prflow/vendor/` is materialized only at runtime), re-invoke the same helper with the `.prflow/vendor/prflow/` prefix removed (`scripts/load-prompt-extension.sh pr-description`) as a single leading-token statement. If that too is not found (a non-Claude-Code runner where neither repo-relative path exists), fall back to the portable anchor form:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh pr-description
```

Every extension-state failure arm below fires unconditionally — this ladder is the only channel, so a failure you do not report drops consumer policy from the run silently. If the invocation fails because the helper path does not exist (`No such file`, exit 127, or the platform equivalent) on every form above, that is the anchor-resolution failure described in the *Portable helper anchor* note above — report it in the run's output, since it breaks every other bundled-helper call site in this run; fix the anchor, don't report a missing extension. If instead the harness refuses the command outright — a permission denial rather than a missing file — the extension's state is **unestablished**: report that in the run's output and never treat it as a clean policy pass (*unknown is not zero*). Otherwise, if the helper exits non-zero, a consumer extension exists but could not be loaded — surface its stderr message and do not silently proceed as if none existed. If it exits 0 and prints text, treat that text as additional instructions appended to the end of this skill's own prompt for this run — it is upgrade-safe, consumer-owned customization committed under `.prflow/prompt-extensions/`. If it exits 0 and prints nothing, proceed unchanged.

## Step 1: Gather Context

Run these commands to understand what changed:

```bash
git fetch origin main
git log origin/main...HEAD --oneline
```

```bash
git diff origin/main...HEAD --stat
```

Read the diff details for any files that need deeper understanding:

```bash
git diff origin/main...HEAD
```

If an issue number was provided, fetch the issue for context:

```bash
gh issue view $ARGUMENTS --json title,body,labels
```

Check for an existing PR on the current branch:

```bash
gh pr view HEAD --json number,body,title 2>/dev/null
```

If this succeeds, an existing PR was found. Save the PR number and body for Step 2.

Best-effort: pull post-merge acceptance criteria from the /prflow:implement workpad. When `/prflow:implement` parses a related issue's Acceptance Criteria (its Phase 1.4), it tags items that can only be verified after merge with a trailing `(post-merge)` marker on the checkbox line. Surface those items in the PR body so the merger sees them and can tick them off after deploy.

If an issue number is available (from `$ARGUMENTS` or extracted from the existing PR body via `(?i)(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)` — mirroring GitHub's own case-insensitive closes-keyword detection), look up the workpad and read its body:

```bash
ISSUE_NUMBER=$ARGUMENTS  # or the extracted number
WORKPAD_ID=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py id "$ISSUE_NUMBER" 2>/dev/null || true)
if [ -n "$WORKPAD_ID" ]; then
    WORKPAD_BODY=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py body "$WORKPAD_ID" 2>/dev/null || true)
fi
```

If `WORKPAD_BODY` is set, scan its `## Acceptance Criteria` section for lines matching `^[-*]\s+\[[ x]\]\s+.*\(post-merge\)\s*$`. Strip the leading checkbox and the trailing `(post-merge)` tag from each match; collect them as `POST_MERGE_ITEMS` for Step 2's template.

If no workpad exists, no issue number is available, or no `(post-merge)`-tagged items are found, `POST_MERGE_ITEMS` stays empty and the template's Post-Merge Verification section is omitted entirely. The lookup is best-effort — never fail the run on a missing workpad.

Best-effort: pull deferred review findings from the manifest. /prflow:review-and-fix writes each run's manifest run-scoped (`.prflow/tmp/review/<slug>/<run-id>/deferrals.json`), and /prflow:implement Phase 4.0.5 merges every run-scoped manifest into one slug-level aggregate at `.prflow/tmp/review/pr-<N>/deferrals.json`, then files follow-up issues and updates that aggregate in place with `id` and `follow_up` fields per entry. Read the slug-level aggregate and surface its entries in the PR body as a Scope-Acknowledged Findings block so /prflow:review (run later as a formal merge signal) can match them and demote the corresponding findings to Informational.

```bash
PR_NUMBER=$(gh pr view --json number --jq '.number' 2>/dev/null || true)
if [ -n "$PR_NUMBER" ]; then
    DEFERRALS_FILE=".prflow/tmp/review/pr-${PR_NUMBER}/deferrals.json"   # slug-level aggregate written by /prflow:implement Phase 4.0.5
    if [ -s "$DEFERRALS_FILE" ]; then
        DEFERRALS_BODY=$(cat "$DEFERRALS_FILE")
    fi
fi
```

If `DEFERRALS_BODY` is set and the parsed JSON has at least one renderable entry under `deferrals[]`, render the Deferred Findings section in Step 2's template — a human-readable Markdown table (one row per deferral) for readers, plus the exact machine payload (the same `schema_version: 1` / `deferrals[]` YAML shape) inside the hidden `DEVFLOW_DEFERRED_PAYLOAD` HTML comment that `scripts/match-deferrals.py` parses. An entry is renderable when it has a populated `follow_up.issue` OR its `reason.category` (equivalently the aggregate's flat `category`) is `settled-by-disclosure` (a foreclosure, which never has a `follow_up.issue`). An ordinary entry (one of the three non-foreclosure categories) lacking a `follow_up.issue` is a stale half-written manifest — skip it silently.

**Carry-forward safety.** Because a `settled-by-disclosure` foreclosure files no follow-up issue, the PR-body Scope-Acknowledged block is its *only* durable record — a regeneration from a fresh environment (where `.prflow/tmp/review/…` is empty) must therefore **never** silently wipe it. So:
- When the slug aggregate is absent or unparseable (`DEFERRALS_BODY` empty/invalid), do not omit the section: read the existing PR body's `DEVFLOW_DEFERRED_PAYLOAD` block and preserve it verbatim (re-emit its entries unchanged). Only when neither an aggregate nor an existing block exists is the section omitted.
- When both an aggregate and an existing PR-body block exist, merge them: render the aggregate's entries, then carry forward any entry present in the existing body's `DEVFLOW_DEFERRED_PAYLOAD` but absent from the aggregate (matched by its `dfr-` id) so a foreclosure recorded on an earlier pass is never dropped by a later regeneration that no longer sees its manifest.

The lookup is best-effort — never fail the run on a missing or unparseable manifest, and never wipe an existing foreclosure block on one.

## Step 2: Generate the PR Description

Read the shared writing standard before composing. The PR description is change-describing prose, so read `lib/writing-standard.md` — reached through the portable skill-directory anchor as `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/writing-standard.md` — and follow it when you write the summary and body below. A failed load emits a breadcrumb naming the file and the failure kind, and you compose the description without it.

### Mode A: No existing PR (or empty body)

Generate a fresh description using the template below.

### Mode B: Existing PR with content

Fetch the existing body and apply these merge rules:

Re-generate from the diff (always overwrite — these reflect current state):
- Summary
- Changes
- Visual Changes
- Breaking Changes
- Post-Merge Verification (when `POST_MERGE_ITEMS` is non-empty — re-derived from the workpad on every run so the list stays in sync with the latest /prflow:implement parse)
- Deferred Findings (when there is at least one renderable entry, as defined in Step 1 — re-derived from the manifest on every run so the block stays in sync with the latest /prflow:implement Phase 4.0.5 filing; carry-forward-safe: a regeneration with no manifest present preserves the existing block's entries verbatim rather than wiping them, per the carry-forward rule in Step 1)

Merge (keep existing items that are still relevant, add new ones, remove stale ones):
- Test Plan — preserve human-added checklist items; add items for new changes; remove items for changes that no longer exist

Merge (combine existing and new):
- Resolves — if `$ARGUMENTS` provides an issue number, include it; also keep any existing issue references that differ from `$ARGUMENTS`

Preserve as-is:
- Any non-template sections found between the markers (e.g., "## Reviewer Notes", "## Deploy Steps") — carry them forward in the same position
- Any content that appears BEFORE `<!-- PR_BODY_START -->` or AFTER `<!-- PR_BODY_END -->` in the existing body — output it in the same position relative to the markers, except the provenance line, which the next rule places

Relocate, do not preserve in place:
- A provenance line of the form `Generated via /prflow:implement (...)` — wherever it appears in the existing body, carry it forward verbatim as the last line of the whole output, below `<!-- PR_BODY_END -->` and below any other post-marker content. It is a durable record of the run that opened the PR and is meant to read as the body's signature, so a copy left higher up — above `<!-- PR_BODY_START -->`, or in the middle of the body — is moved down rather than kept, and exactly one copy is emitted.

If the existing body has NO markers: Treat the entire existing body as pre-marker content, except the provenance line, which the relocation rule above places. Output that pre-marker content above `<!-- PR_BODY_START -->`, then generate the full template below the marker, then the provenance line last.

### Template

Output the description as plain text (not inside a code block) so it appears directly in your response:

<!-- PR_BODY_START -->
## Summary
- [1-3 concise bullet points describing what changed and why]

## Changes
[Group changes by module or concern. Use bold for the area name, colon, then a brief description.]

[Area name]: [What changed]
[Area name]: [What changed]

## Resolves
Resolves #[issue number, or omit this section if no issue number was provided]

## Test Plan
- [ ] [Concrete verification step]
- [ ] [Concrete verification step]

## Post-Merge Verification
[Omit this entire section when POST_MERGE_ITEMS is empty. When non-empty, render as:]
The following items can only be verified after this PR is merged or deployed. Tick each after performing the check.
- [ ] [Post-merge AC text, with the trailing (post-merge) tag stripped]
- [ ] [...]

## Deferred Findings
[Omit this entire section only when there are NO renderable entries (as defined in Step 1) AND no existing PR-body block to carry forward. When rendering, render with the markers — the /prflow:review verdict matcher parses them exactly. The visible content is a human-readable Markdown table; the exact machine payload lives in a hidden HTML comment (`DEVFLOW_DEFERRED_PAYLOAD`) so it does not appear in the rendered PR body. One table row per deferral; one payload entry per deferral, in the same order. A foreclosure row cites the disclosure path in the Follow-up column (e.g. `disclosure: docs/…`) instead of a `#<N>` issue reference. Carry forward any existing-body entry absent from the aggregate, per Step 1's carry-forward rule:]

<!-- DEVFLOW_DEFERRED_FINDINGS_START -->
These review-agent findings were deferred under the Scope-Acknowledged Findings contract. /prflow:review honors matching entries as Informational; closing a linked follow-up issue invalidates the deferral and forces re-verification. A `settled-by-disclosure` foreclosure has no follow-up issue — the cited disclosure is its deliverable, and a review re-verifies the disclosure phrase against the tree.

| Severity | File | Finding | Follow-up |
| --- | --- | --- | --- |
| <severity> | `<path>:<start>-<end>` | <one-line summary> | #<N> |
| <severity> | `<path>:<start>-<end>` | <one-line summary> | disclosure: `<disclosure path>` |

<!-- DEVFLOW_DEFERRED_PAYLOAD
schema_version: 1
deferrals:
  - id: <dfr-...>
    finding:
      agent: <agent>
      severity: <Critical | Important | Suggestion>
      file: <path>
      line_range: [<start>, <end>]
      symbol: <symbol or empty>
      kind: <kind>
      summary: |
        <verbatim summary>
    reason:
      category: <out-of-scope | already-tracked | claim-quality | settled-by-disclosure>
      explanation: |
        <verbatim explanation>
    # follow_up is present for the three ordinary categories; a settled-by-disclosure
    # entry OMITS follow_up and instead carries a top-level `disclosure: {path, phrase}`.
    follow_up:
      issue: <N>
      url: <url>
      filed_at: <ISO 8601 UTC>
      filed_by: <login>
    disclosure:
      path: <repo-relative disclosure path>   # settled-by-disclosure entries only
      phrase: <short verbatim phrase>
-->
<!-- DEVFLOW_DEFERRED_FINDINGS_END -->

## Visual Changes
[Describe UI changes, or "N/A" if none]

## Breaking Changes
[Describe breaking changes and migration steps, or "None"]

<!-- PR_BODY_END -->

Rules:
- Follow the shared writing standard read at the top of this step for how the prose reads.
- Summary bullets should explain *what* and *why*, not list files.
- Changes section groups by logical area (e.g., "Orders module", "Frontend", "Database"), not individual files.
- Test Plan items must be concrete and actionable, not generic ("Run tests").
- The entire output between the markers must be valid GitHub-flavored Markdown.
- GitHub autolink hygiene (the PR body is posted to GitHub): never put a bare `#` immediately before a number unless it is a real issue or PR reference — GitHub renders `#2` as a link to issue/PR 2, which misleads readers. For an ordinal, count, or list position, spell it out ("item 2", "step 3"), never `#2`. Genuine references like `#123` stay as-is. <!-- pruned-path-ok: illustrative autolink examples, not citations -->
- Do NOT wrap the output in a code block. Output the markers and content as plain text so they appear directly in your response.
- When updating an existing PR, do NOT discard human-added content. If in doubt about whether something was human-added, preserve it.

## Step 3: Apply the Description

- If an existing PR was found (Mode B): Update it directly via REST (repo-scope only — `gh pr edit --body` resolves the repo through org-scoped GraphQL and fails under a repo-scoped token). The `-F body=@-` form reads the field value literally from stdin, so the quoted-heredoc's no-expansion guarantee (backticks and `$` preserved) holds:
  ```bash
  gh api --method PATCH "repos/{owner}/{repo}/pulls/$PR_NUMBER" -F body=@- <<'EOF'
  [full output including any pre/post-marker content]
  EOF
  ```
- **If no existing PR (Mode A):** Output the description as plain text for the caller to use when creating the PR.
