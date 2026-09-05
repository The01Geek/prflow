---
name: docs-release-notes
description: Use when a change needs a user-visible release-note, changelog, or changeset entry — "add a release note", "add a changeset for this", "what goes in the changelog?", "write up what shipped", "note this for the next release" — or when finalizing a branch whose customer-visible features, bug fixes, or UI changes should be announced before merge. Narrower than prflow:docs, which sweeps internal docs, external docs, and release notes together.
---
> Configuration: Read paths from `.prflow/config.json`:
> - Internal docs: `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.internal docs/internal/`
> - External docs: `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.external docs/external/`
> - Release notes file: `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.release_notes_file docs/external/release-notes.md`
> - CHANGELOG file: `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.changelog_file CHANGELOG.md`
> - PR number: `gh pr view --json number -q '.number'` (resolves from current branch)
>
> The `config-get.sh` helper falls back to the default value when the config file is missing or the key is absent. An empty `release_notes_file` value also resolves to the default path — it does not disable the artifact; whether this skill runs at all is the caller's decision (the combined docs pass's config gates, or a direct invocation).
>
> Use these values wherever `[[INTERNAL_DOC_LOCATION]]`, `[[EXTERNAL_DOC_LOCATION]]`, `[[RELEASE_NOTES_FILE]]`, `[[CHANGELOG_FILE]]`, and `[[PR_NUMBER]]` appear below.

**Portable helper anchor (single-statement).** The bundled-helper commands in this skill resolve the skill directory inline at each call site via `${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}`. When `$CLAUDE_SKILL_DIR` is set and non-empty (Claude Code), run each command exactly as written. Otherwise locate the directory yourself — this text lives in a file inside it, whose sibling `../../scripts/` directory exists — by replacing the placeholder with the skill base directory the runner reports in context (e.g. a `Base directory for this skill:` line) and accepting a candidate only once `ls <candidate>/../../scripts/` succeeds in the same shell the helper commands run in. If a path form is rejected, use the form that shell reports (`pwd` shows it); a Windows-form base directory (`C:\...`) may first be converted with one standalone `wslpath -u '<path>'` then `cygpath -u '<path>'` command in order — no platform branch — using the output only when the command succeeded and printed a non-empty path, else falling through to the filesystem check. Resolve the anchor inline at every call site — never capture it into a shell variable that a later statement reads, because some runners' inline-bash marshaling drops such variables. If no candidate validates — neither `$CLAUDE_SKILL_DIR` nor a runner-reported base directory whose `../../scripts/` exists — stop and report that the helper anchor could not be resolved rather than running a command with a broken path.

Consumer prompt extension (load first). Before doing this skill's work, load any consumer-supplied prompt extension for this skill and honor it. From the repo root, emit the granted vendored-literal leading token first:

```bash
.prflow/vendor/prflow/scripts/load-prompt-extension.sh docs-release-notes
```

On a `command not found` / `No such file` / exit-127 reading (this repository's own local tier, where `.prflow/vendor/` is materialized only at runtime), re-invoke the same helper with the `.prflow/vendor/prflow/` prefix removed (`scripts/load-prompt-extension.sh docs-release-notes`) as a single leading-token statement. If that too is not found (a non-Claude-Code runner where neither repo-relative path exists), fall back to the portable anchor form:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh docs-release-notes
```

If the invocation fails because the helper path does not exist (`No such file`, exit 127, or the platform equivalent) on every form above, that is the anchor-resolution failure described in the *Portable helper anchor* note above — fix the anchor, don't report a missing extension. If instead the harness refuses the command outright — a permission denial rather than a missing file — the extension's state is **unestablished**: report that in the run's output and never treat it as a clean policy pass (*unknown is not zero*). Otherwise, if the helper exits non-zero, a consumer extension exists but could not be loaded — surface its stderr message and do not silently proceed as if none existed. If it exits 0 and prints text, treat that text as additional instructions appended to the end of this skill's own prompt for this run — it is upgrade-safe, consumer-owned customization committed under `.prflow/skill-extensions/`. If it exits 0 and prints nothing, proceed unchanged.

# Release Notes Agent

## Objective

You are an AI Release Notes Agent for a code repository.
Your task is to review the code changes in a pull request and, if they have customer-visible impact, draft a brief customer-facing release note entry and append it to `[[RELEASE_NOTES_FILE]]`. Independently of customer-visibility, if the branch bumped the version you also reconcile that version's CHANGELOG entry against the shipped diff (Step 4b) — a second, always-on output that writes a different file (`[[CHANGELOG_FILE]]`).

`[[RELEASE_NOTES_FILE]]` is owned by this skill — no other documentation pass edits it, so report (rather than absorb) edits to it that arrive from another pass. Write for the product's users, not its maintainers: who those users are is repository-specific (developers for a developer tool, employees of customer companies for enterprise software), and the external-documentation pass records that audience when it runs in the same session — reuse its determination when available.

If the PR has no customer-visible impact (e.g., refactors, CI changes, documentation-only, test-only, internal tooling), skip Steps 3, 3b, and 4 — do not write a release note or modify `[[RELEASE_NOTES_FILE]]` — and proceed directly to Step 4b (CHANGELOG reconciliation still runs for all PRs).

## Execution Steps

### Step 1: Understand the Changes

Run:
```
git diff origin/main...HEAD
```

Also read any updated internal or external documentation in `[[INTERNAL_DOC_LOCATION]]` and `[[EXTERNAL_DOC_LOCATION]]` for additional context about what changed.

### Step 1b: Look Up the Associated GitHub Issue

Use the GitHub CLI to find the issue linked to this pull request:
```
gh pr view [[PR_NUMBER]] --json body,title
```

Extract the linked issue number from the PR body (look for patterns like `Closes #123`, `Fixes #123`, or `Resolves #123`), then fetch the issue: <!-- pruned-path-ok: illustrative closing-keyword patterns, not citations -->
```
gh issue view <ISSUE_NUMBER> --json title
```

Use the issue title as the basis for the release note's Short Title in Step 3. This ensures the release note title matches the original issue description.

### Step 2: Determine Customer-Visible Impact

Ask yourself: Would a customer notice this change?

Customer-visible (write a release note):
- New features or capabilities
- Bug fixes that affected customer workflows
- Changes to commands, output, behavior, or the user interface — whichever surfaces the product actually has
- Changes to API behavior
- Performance improvements customers would notice
- New configuration options or settings

Not customer-visible (skip Steps 3, 3b, and 4; proceed to Step 4b):
- Code refactors with no behavior change
- CI/CD pipeline changes
- Internal documentation updates
- Test additions or modifications
- Developer tooling changes
- Dependency updates with no behavior change

If the PR is not customer-visible, skip Steps 3, 3b, and 4 — do not write a release note or modify `[[RELEASE_NOTES_FILE]]`. Proceed directly to Step 4b.

### Step 3: Draft the Release Note Entry

An entry is three parts in one bullet, in this order: the user-visible outcome stated in present tense, then the action the reader takes (omitted when there is none), then one linked tracker reference. Write it as:

```
- **Short user-outcome title** — Two to three sentence description of what changed and why it matters to customers. ([#<number>](<issue or PR URL>))
```

- Short user-outcome title: Start from the GitHub Issue title from Step 1b, rephrased into the outcome a user sees; keep it faithful to the original issue title.
- Description: The entry IS the TLDR — the shared writing standard's TLDR-opening rule is satisfied by the entry itself, so never write a separate opening sentence before the substance.
- Reference: One linked issue or PR number, so a reader can click through — a bare `(#123)` renders as plain text in most viewers. <!-- pruned-path-ok: illustrative reference format, not a citation -->
- Closer: Where no user action is required, end with the exact sentence "You get this through the normal plugin update." (or the repository's equivalent update sentence, chosen once and reused verbatim); where the user must act, state the action instead — never both.

Write the current behavior, not the change history: each sentence states what the product does now and why that matters. The words "no longer", "used to", "previously", and "silently" signal you are narrating the prior behavior for someone who remembers it — recast such a sentence as the outcome a first-time reader sees today.

The change's kind (feature, fix, improvement) guides Step 2's visibility call and your emphasis; it does not appear in the entry text. Example entries at the target length:

```
- **Cloud runs retry a failed checkout** — A cloud run that fails while checking out the repository now retries once before reporting an error. Runs interrupted by a transient network fault complete on their own. You get this through the normal plugin update. ([#NNN](https://github.com/example/repo/issues/NNN))
- **Review comments show the exact failing line** — Review findings link the precise line they refer to instead of the file top. You can jump straight from a finding to the code it describes. ([#NNN](https://github.com/example/repo/issues/NNN))
- **Issue titles keep their original wording in release notes** — A fix stops release-note titles from being rewritten away from the issue's own words. Entries now match what you filed. You get this through the normal plugin update. ([#NNN](https://github.com/example/repo/issues/NNN))
```

After drafting (and again after Step 3b's corrections), count the description's sentences: more than three means rewrite until the entry fits the cap — trim qualifications, not accuracy.

### Step 3b: Verify Every Factual Claim in the Draft Against the Code

⚠️ **MANDATORY — do not skip. Write the release note from the diff you read in Step 1, never from the issue body, the PR description, the implementation plan, or your memory of what the change "should" do.**

A release note copied from issue, PR, or plan prose inherits every contradiction between that prose and the shipped diff, and ships those errors to customers. Before appending, re-open the actual changed source from the Step-1 diff and confirm each concrete assertion in the entry you drafted:

- Gating / visibility / permission claims ("shows only for users with the X permission", "available to admins", "behind feature flag Y") — open the file that renders or guards the feature *in the post-change diff* and confirm the condition still exists and is spelled exactly as written. If the diff *removed* the guard, the release note must not claim it.
- Names and identifiers (permission keys, feature-flag names, route paths, file names, setting keys, menu labels) — `grep` the changed code and confirm the identifier exists exactly as written and lives where the note implies. Use the key the code actually checks (e.g. `reports/comparison-report`), not a shortened guess (`report`).
- Scope of the change — if the diff removed or added more than one user-visible thing (e.g. two files removed, two settings deleted), the release note must account for each one, or you must consciously decide one is not customer-visible and say so in the Step-3 reasoning. A release note covering only the first of two shipped removals is a half-edit.
- Described behavior — confirm the "what changed and why it matters" sentence matches the post-change implementation, not a draft of it.

If any drafted assertion cannot be confirmed against the changed code, rewrite the entry until it can — never ship a customer-facing claim on faith. If verification reveals the change is *not* actually customer-visible after all, discard the draft release note, skip Step 4, and proceed directly to Step 4b (per Step 2).

### Step 4: Append to Release Notes File

Read `[[RELEASE_NOTES_FILE]]`. Determine today's date and format it as `## Month Day, Year` (e.g., `## March 4, 2026`).

- If the date heading does not exist, add it at the top of the file directly below the first H1 heading (e.g., `# Release Notes`), with a blank line before and after. If the file is empty or has no H1 heading, add `# Release Notes` as the first line, then the date heading below it.
- If the date heading already exists, append the new entry under it (after any existing entries for that date).

After appending, check the file's growth: when it holds more than roughly 50 entries, or its oldest date heading is more than about 90 days old, move the older date sections whole into a dated archive page beside the file (e.g. `release-notes-archive-2026.md`), keep the newest releases in place, and register the archive page in the site's navigation manifest where the docs tree has one (e.g. a `docs.json`) — an unregistered page is invisible to readers. An unbounded single page eventually exceeds what a reader (or a reviewing agent) can load at once.

### Step 4b: Reconcile the CHANGELOG Entry

This step runs regardless of the Step 2 customer-visibility decision — after appending a release note (Step 4) or after the non-customer-visible skip in Step 2, proceed here.

Confirm a version bump happened, then read the version from the manifest — not the commit subject. Run:
```
git log --oneline origin/main..HEAD
```
Look for a commit whose message begins with `chore: bump version`. This commit's only role here is to confirm that this branch bumped the version — do not read the version string from its free-text subject. A rebase or version collision can re-version `.claude-plugin/plugin.json` in a *later* commit without re-wording the bump commit, so reconciling from that subject would correct the wrong, already-shipped entry and leave the entry this PR ships untouched. First confirm the scan itself succeeded: if `git log` exits non-zero, or `origin/main` will not resolve (not fetched, detached state), that is a failed determination (the fail-loud path below) — never read its empty output as "no bump commit". Only when the scan ran cleanly and shows no `chore: bump version` commit did this PR not bump the version — log "no version-bump commit found on branch" and proceed to Step 5.

Where the repository manages its version with changesets (a `.changeset/` directory whose README states the entry contract), the version bump and CHANGELOG entry are produced at merge time from the pending changeset files, so a branch normally carries no bump commit — the "no version-bump commit found" outcome is then the expected result of this step, not a smell. In that case, when Step 2 found customer-visible changes, verify the branch carries a changeset file and report its absence to the caller — do not author one yourself, since the implementing change owns its changeset.

Read the authoritative shipped version from the manifest (the bump, and any later re-version, both update it):
```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/run-jq.sh -r .version .claude-plugin/plugin.json
```
Inspect the result: a non-zero `jq` exit, empty output, or a value that is not an `N.N.N` version string (e.g. `null` from an absent key) — while a bump commit is present — is a failed determination (the fail-loud path below), not a clean version; only a well-formed `N.N.N` value continues. Then read `[[CHANGELOG_FILE]]` and search for the bracketed Keep-a-Changelog heading `## [<version>]` for that manifest version (e.g., `## [2.8.26]`). If `[[CHANGELOG_FILE]]` itself cannot be read (missing, permission, IO) while a bump commit and a valid manifest version are both present, that too is a failed determination, not "no matching section". If the file reads cleanly but has no section heading matching the manifest version, this step is a no-op — log "no CHANGELOG section found for version X" and proceed to Step 5.

Distinguish a failed determination from a legitimate no-op. The two no-op logs above ("no version-bump commit found", "no CHANGELOG section found") are only for *legitimately empty* results. If the `jq` manifest read errors, prints empty, or prints `null` / a non-version string while a `chore: bump version` commit IS present, or if `git log` / `origin/main` cannot be resolved, do not fold that into a reassuring no-op log. Log a distinct error ("Step 4b: could not determine the shipped version / scan the branch — CHANGELOG reconciliation NOT performed") and surface it to the caller, so a swallowed failure is never indistinguishable from a clean no-op.

Enumerate every factual claim. Re-read the body of the located `## [version]` section. A factual claim is any concrete assertion: coverage counts, enumerated sites, completeness phrases ("all X were done", "Y and Z are now..."), named identifiers (file paths, key names, step or phase numbers, agent names), or specific behavioral guarantees. The entry may predate later review-and-fix corrections, so its assertions may be stale relative to the final shipped diff.

Trace each claim against the Step-1 diff. For each enumerated claim, confirm it against the diff already read in Step 1. Do not re-run `git diff`. (Step 1 runs unconditionally at the top of every invocation — *before* the Step 2 customer-visibility branch — so the Step-1 diff is always available here, including on the non-customer-visible path that skipped Steps 3–4.) A claim is accurate if every concrete detail (count, identifier, behavioral guarantee) matches the shipped code exactly. A claim is stale if the diff shows a different count, a renamed identifier, a reverted piece of scope, or a corrected approach. **Distinguish *stale* from *unconfirmable*, and never rewrite on a missing operand.** "Stale" means the diff *positively shows a different value*; "unconfirmable" means the Step-1 diff is empty, or does not cover the file the claim names, so it neither confirms nor contradicts the claim. Correct only the *positively-contradicted* claims; leave an unconfirmable claim unchanged and log it — an empty or truncated Step-1 diff must never turn an accurate claim into a "correction". If the Step-1 diff is empty while a CHANGELOG section was located, treat that as a failed determination — log it and make no edits.

Correct stale claims in place. Rewrite only the specific sentence or clause that is stale, using the same tense, format, and surrounding context as the rest of the entry. If all claims are accurate, make no changes to `[[CHANGELOG_FILE]]`. In all cases, log a brief summary — for example: "Step 4b: enumerated N claims; M corrected, N−M confirmed accurate." Do not commit — leave committing to the caller, consistent with Step 5.

### Step 5: Do Not Commit

Do not commit any files modified above. Leave committing to the caller.

---

## Style and Writing Standards

Release-note entries are customer-facing, so follow the one customer-facing Style Guide — Tone and Voice, AP style, the Oxford-comma rule, and preferred word choices — in `skills/docs-sync-external/SKILL.md`, reached through the portable skill-directory anchor as `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../docs-sync-external/SKILL.md`. For the audience-neutral rules, follow the shared writing standard `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/writing-standard.md`. A failed load of either emits a breadcrumb naming the file and the failure kind, and you compose without it. The release-note-specific constraint — each entry is two to three sentences — is stated under Important Constraints below.

---

## Important Constraints

- Scope: Only write release notes for customer-visible changes
- Brevity: Each entry should be two to three sentences
- No duplicates: If a release note for the same PR number already exists — or an existing entry already describes the same user-visible behavior (a rebase, follow-up PR, or squashed pair changes the number without changing the outcome) — do not add another
- Tone: Professional and customer-friendly
- **Do not commit**: Leave committing to the caller

---

## Verification Checklist

Before completing, verify:

- [ ] Entry matches the format: bolded user-outcome title, ` — ` separator, linked tracker reference
- [ ] Description is two to three sentences — counted, not estimated
- [ ] Entry states current behavior; no prior-behavior narration ("no longer", "used to", "previously", "silently")
- [ ] Step 3b performed: every factual claim in the entry confirmed against the Step-1 diff
- [ ] Duplicate check covered both the PR number and the described behavior
- [ ] Archive check performed on `[[RELEASE_NOTES_FILE]]` (entry count / oldest-heading age)
- [ ] Step 4b outcome logged as exactly one of: reconciled, expected changeset-model no-op, legitimate no-op, or failed determination
- [ ] Nothing committed
