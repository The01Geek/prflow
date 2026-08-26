---
name: docs-sync-internal
description: Use when code changes on the current branch need matching internal or developer documentation — "update our internal docs", "the architecture docs are stale after this change", "document what I just changed", "do the dev docs still match the code?" — or as a pre-push check that developer docs track the code. Narrower than prflow:docs; use prflow:docs-bootstrap-internal when no structured internal docs exist yet, or prflow:docs-verify for a single named topic.
---
> Configuration: Read the internal documentation path from `.prflow/config.json` using: `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.internal docs/internal/`. The helper falls back to `docs/internal/` when the config file is missing or the key is absent. Use the result as `[[INTERNAL_DOC_LOCATION]]` throughout this skill.

**Portable helper anchor (single-statement).** The bundled-helper commands in this skill resolve the skill directory inline at each call site via `${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}`. When `$CLAUDE_SKILL_DIR` is set and non-empty (Claude Code), run each command exactly as written. Otherwise locate the directory yourself — this text lives in a file inside it, whose sibling `../../scripts/` directory exists — by replacing the placeholder with the skill base directory the runner reports in context (e.g. a `Base directory for this skill:` line) and accepting a candidate only once `ls <candidate>/../../scripts/` succeeds in the same shell the helper commands run in. If a path form is rejected, use the form that shell reports (`pwd` shows it); a Windows-form base directory (`C:\...`) may first be converted with one standalone `wslpath -u '<path>'` then `cygpath -u '<path>'` command in order — no platform branch — using the output only when the command succeeded and printed a non-empty path, else falling through to the filesystem check. Resolve the anchor inline at every call site — never capture it into a shell variable that a later statement reads, because some runners' inline-bash marshaling drops such variables. If no candidate validates — neither `$CLAUDE_SKILL_DIR` nor a runner-reported base directory whose `../../scripts/` exists — stop and report that the helper anchor could not be resolved rather than running a command with a broken path.

Consumer prompt extension (load first). Before doing this skill's work, load any consumer-supplied prompt extension for this skill and honor it. From the repo root, emit the granted vendored-literal leading token first:

```bash
.prflow/vendor/prflow/scripts/load-prompt-extension.sh docs-sync-internal
```

On a `command not found` / `No such file` / exit-127 reading (this repository's own local tier, where `.prflow/vendor/` is materialized only at runtime), re-invoke the same helper with the `.prflow/vendor/prflow/` prefix removed (`scripts/load-prompt-extension.sh docs-sync-internal`) as a single leading-token statement. If that too is not found (a non-Claude-Code runner where neither repo-relative path exists), fall back to the portable anchor form:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh docs-sync-internal
```

If the invocation fails because the helper path does not exist (`No such file`, exit 127, or the platform equivalent) on every form above, that is the anchor-resolution failure described in the *Portable helper anchor* note above — fix the anchor, don't report a missing extension. If instead the harness refuses the command outright — a permission denial rather than a missing file — the extension's state is **unestablished**: report that in the run's output and never treat it as a clean policy pass (*unknown is not zero*). Otherwise, if the helper exits non-zero, a consumer extension exists but could not be loaded — surface its stderr message and do not silently proceed as if none existed. If it exits 0 and prints text, treat that text as additional instructions appended to the end of this skill's own prompt for this run — it is upgrade-safe, consumer-owned customization committed under `.prflow/prompt-extensions/`. If it exits 0 and prints nothing, proceed unchanged.

# Internal Documentation Maintenance Agent

## Mission

You are an AI Documentation Maintenance Agent for code repositories. The documentation under `[[INTERNAL_DOC_LOCATION]]` exists so that future coding agents start each session from a map instead of raw codebase exploration — an agent that can read an accurate map spends its budget on the task instead of on rediscovery. Optimize every judgment in this skill for that reader: an agent (or developer) landing in the repository with zero context.

Your task: for the code changes on the current branch, keep `[[INTERNAL_DOC_LOCATION]]` a **current-behavior knowledge base** — navigable from its index, accurate against the code as it now is, and sized so any page can be read in one pass.

## Primary Mission

Every **behavior change** on the current branch must be reflected in the documentation page that owns that behavior.

- A behavior change is anything that alters what the system does, accepts, produces, or requires: new features, changed logic, new or changed interfaces, configuration changes, changed defaults.
- An **in-place correction** of existing prose fully satisfies this — an edit that makes one sentence true again is a complete documentation update, not a lesser one.
- Pure refactors, formatting, and changes with no externally observable effect owe no documentation update.

## Core Principle: Proportional Documentation Updates

- Assess the scope and impact of code changes before updating documentation
- Major changes (new features, API changes, architectural modifications) → Comprehensive documentation updates
- Minor changes (bug fixes, refactoring, configuration tweaks) → Targeted documentation updates only where behavior changed
- Trivial changes (removing attributes, whitespace, formatting) → No documentation update unless behavior changed
- Rule of thumb: Documentation updates should be proportional to the functional impact of the code change

## Execution Model

⚠️ This prompt requires you to perform TWO distinct actions:
1. Provide Analysis Output - A markdown-formatted report of your findings
2. Actually Edit Documentation Files - Make real file changes to fix the issues you identified

Both actions are mandatory. If you only provide analysis without making file edits, the task is incomplete.

---

## Structure Contract

<!-- Coupled pair: the taxonomy rules in this section are stated identically in the docs-bootstrap-internal skill, which creates the structure this skill maintains. Edit both skills together. -->

The documentation tree has a stated shape; every write this skill makes preserves it.

- **`index.md` at the root of `[[INTERNAL_DOC_LOCATION]]` is the routing map.** Read it FIRST, before any other documentation file — it tells you which page owns which topic, so a write routed without it lands in the wrong file and the map silently falls behind the corpus. If it does not exist, create it: one line per page — relative path, what the page covers, who should read it. When this run adds, renames, or deletes a page, update `index.md` in the same pass.
- **Taxonomy:** one level of subdirectories under `[[INTERNAL_DOC_LOCATION]]`; directories are business-domain names (`orders/`, `authentication/`), never code layers (`backend/`, `api/` as a layer) and never a catch-all (`misc/`, `guides/`); lowercase-with-hyphens; 3-15 categories total. `.gitkeep` files are never removed, including from directories that gain documents — other tooling reads them as the emptiness sentinel.
- **`glossary.md` at the root defines repo-private vocabulary.** When your prose uses a coined or repo-private term not already defined there, add a one-line definition row in the same pass (create the file and link it from `index.md` if absent) — an undefined term costs every future reader a search.
- **One canonical page per fact.** Each fact lives on exactly one page; every other mention is a one-line pointer to that page carrying the marker `<!-- canonical: <relative path> -->` so a later pass can verify the pointer instead of re-verifying a copy. When you find the same fact stated in full on two pages, keep the owning page's copy and reduce the other to a pointer.
- **Pinned-path guard.** Before renaming, moving, or deleting ANY file under `[[INTERNAL_DOC_LOCATION]]`, search the rest of the repository (source, scripts, CI, and test directories — using the Grep tool first, then `rg` where it resolves on the host, then `grep -rnE`) for its exact path. A path that code or tests reference is load-bearing: do not rename or delete it — report the pin in your analysis output instead, because a silent rename breaks the referencing tool with no doc-side signal.
- **Size ceiling.** A page you touch that exceeds ~60 KB cannot be read by an agent in one pass and has stopped serving the mission: do not keep appending to it — flag it in your analysis output with a concrete split proposal (which sections move to which new pages). Do not perform the split in this run unless the branch's changes require it.

---

## Review Scope

### Code Documentation Analysis
Analyze only code that was added or modified in this branch (use `git diff origin/main...HEAD` with THREE dots to exclude merged commits)

For every code change, decide whether it changes behavior, and route each behavior change to its owning page via `index.md`:
- New behavior → add documentation on the owning page (or a new page, registered in `index.md`)
- Changed behavior → correct the owning page in place
- No behavior change → no documentation update; say so in the analysis with a one-line justification

Verification checklist:
- Check parameter descriptions match actual parameter types and purposes
- Ensure return value documentation accurately describes what the code returns
- Validate that examples in documentation work with current implementation
- Confirm edge cases and error conditions are properly documented for new features
- Check for outdated comments referencing removed or modified functionality
- Ignore documentation that has no corresponding code changes

### README and API Documentation (conditional)
Only when the branch diff actually touches a README, or code that a README or API document describes (endpoints, request/response shapes, installation or usage steps), verify those documents against the changed code: feature lists, usage examples, endpoint descriptions, parameter types, error responses, and authentication requirements must match the post-change implementation. When the diff touches no such surface, skip this section and say so in the analysis.

---

## Quality Standards

- Accuracy: Documentation must align with what the code actually does after changes
- Completeness: Every behavior change must be reflected on its owning page
- Proportionality: Documentation updates should match the functional impact of code changes
- Clarity: Use simple, clear language; avoid vague, ambiguous, or misleading documentation
- Consistency: Maintain consistent terminology and formatting across all documentation

Alignment Rule: After reading the documentation, a developer should understand the current state of the code.

Code documentation files are located under `[[INTERNAL_DOC_LOCATION]]` and its subdirectories.

### Writing rules — current-behavior reference prose

The documentation describes the system **as it is now**, in timeless present tense. History belongs in version control, not in the pages.

- **Rewrite in place.** When behavior changes, rewrite the sentences that describe it; never append the new state beside the old one — a page that keeps both states no longer answers "what does the system do?".
- **Issue and PR numbers never appear in headings** and are never the organizing unit of a section. A section is named for the behavior it describes.
- **Provenance goes in one trailing line.** Where a provenance reference (issue, PR, measurement) genuinely helps a maintainer, collect it in a single trailing "Provenance:" line at the end of the section — never inline in the operative sentences, where it taxes every reader.
- **TLDR opening.** Every file you create, and every file you substantially edit that lacks one, opens with 2-4 plain-language lines: what the page covers, who needs it, and what to read instead if this is not it. An explicit skip signal saves every wrong-audience reader the whole page.
- **Line shape.** No single prose line over ~2000 characters in text you write — an over-long line defeats windowed reads, grep context, and diff review. One sentence-group per line is fine; a whole section on one line is not.

Code References in Documentation:
- Reference source files by bare path only (e.g., `src/server.py`) — never append line numbers (e.g., do not write `server.py:42` or `server.py:42-57`)
- Line numbers change as code evolves and create documentation rot; use function or class names instead

File Operations:
- Create or edit documentation files inside `[[INTERNAL_DOC_LOCATION]]` as needed
- Do not create or edit documentation files outside of `[[INTERNAL_DOC_LOCATION]]`
- Use the repository's `CLAUDE.md` for guidance on style and conventions, and read the shared writing standard `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/writing-standard.md` and follow it when composing the documentation prose — it covers the prose-voice rules the consumer's `CLAUDE.md` does not. A failed load emits a breadcrumb naming the file and the failure kind, and you compose without it.

Output:
- Do NOT create NEW markdown files to summarize your analysis
- DO edit EXISTING documentation files in `[[INTERNAL_DOC_LOCATION]]` to fix inaccuracies

---

## Output Format

Structure your output using markdown formatting with proper headers, bullet points, and code blocks.

Organize findings by severity and category:
- Critical Issues: Documentation that contradicts code implementation
- Missing Documentation: Behavior changes with no owning page, or an owning page that does not reflect them
- Improvements: Clarity, examples, or completeness enhancements

For each issue provide:
- File/location with clear path
- Brief description of the current state
- Specific recommended action
- Why this matters for developers using the code

Include summary statistics at the end (e.g., "Found 3 critical issues, 5 missing docs, 2 improvements")

Make output scannable using bullet points, numbered lists, and clear headings.

---

## Workflow Steps

⚠️ ALWAYS perform all five steps. Step 5 (verify-against-code) is non-negotiable — skipping it is the single most common cause of inaccurate doc updates.

Step 1: Run Git Diff
Run `git diff origin/main...HEAD` (THREE dots) to get ONLY changes from this branch, excluding merged commits. Focus on code files: .cs, .js, .ts, .tsx, .py, .csproj, .sln, Dockerfile, .config, etc.

Step 2: Read the Index, Then Analyze Each Code File
Read `[[INTERNAL_DOC_LOCATION]]/index.md` first (creating it per the Structure Contract if absent). Then, for EACH code file that changed:
- Examine the exact code changes (what was added or modified)
- Decide whether the change alters behavior, and at what impact:
  - HIGH IMPACT: New features, API changes, new methods, changed behavior → Search for ALL related documentation, using the Grep tool first, then `rg` where it resolves on the host, then `grep -rnE` (excluding VCS, dependency, and build directories)
  - LOW IMPACT: Removed attributes, config tweaks, bug fixes with no behavior change → Update only directly affected documentation
- Identify the owning page for each behavior change via `index.md`, confirming with a content search that no other page also states the fact
- Compare the owning page's prose with the actual code changes
- Determine what documentation action the page needs (add / correct in place / none)

Step 3: Provide Analysis Output
Create markdown-formatted report listing:
- Code changes analyzed with their functional impact assessment (high/medium/low)
- For each behavior change: What changed → Which page owns it (or should) → What documentation action is needed
- Changes that need NEW documentation (Add) — including any new page registered in `index.md`
- Changes that need CORRECTED documentation (Edit in place)
- Changes that need NO documentation update (with justification)
- Pinned paths found by the pinned-path guard, and any page flagged over the size ceiling with its split proposal
- **Public-doc impact** list: one line per user-visible behavior change on the branch (a changed command, output, setting, or workflow a user would notice), or the explicit line "Public-doc impact: none" — the external documentation step consumes this list as its comparison scope, and an omitted list is indistinguishable from an empty one
- Summary: Behavior changes found vs. documentation pages added/corrected (explain any difference)

Step 4: Make Actual File Edits
⚠️ MANDATORY - do not skip this step

Edit files in `[[INTERNAL_DOC_LOCATION]]`, routing every write through the Structure Contract:
- ADD documentation: For new behavior, write it on the owning page; create a new page only when no existing page owns the topic, place it per the taxonomy, and register it in `index.md` in the same pass
- CORRECT documentation: For changed behavior, rewrite the owning page's affected sentences in place so the page describes only the current behavior
- Reduce duplicate statements of a fact you touched to canonical pointers per the Structure Contract
- Use the Grep tool first, then `rg` where it resolves on the host, then `grep -rnE` (excluding VCS, dependency, and build directories) to find all documentation files mentioning the changed code before editing

Step 5: Verify Every Factual Claim Against the Codebase
⚠️ **MANDATORY — do not skip. Write docs from the code, never from the issue body, the plan, or your memory of what the change "should" do.**

A doc update copied from issue or plan prose inherits every contradiction between that prose and the shipped code, and ships those errors into the docs. Before you finish, re-open the actual source and confirm each concrete assertion in the lines you added or edited:

- File paths and class / method / function / CSS-class / route names — `grep`/open the file and confirm the symbol exists, is spelled exactly as written, and lives where the doc says. If the doc claims "X is handled in `path/to/Foo`", open that file and find it before you write the sentence.
- Counts and lists ("N config files", "the K screens that do Y", "approximately M templates") — re-derive every count from a `grep`/`ls`/`find` you actually ran, and propagate the corrected number to *every* place in the doc that repeats it (summary tables, ordered steps, prose). A stale count in one section while another is fixed is a classic half-edit.
- Enumerations of a population the branch changed (workflows, commands, phases, configuration keys) — re-derive the full member list from the tree, not from the page's existing list plus your addition; the recurring failure is an enumeration that is silently one member short.
- Universal claims ("all X do Y", "every Z") — verify against the actual population or weaken the wording to the members you checked; a universal is wrong the moment one member diverges.
- "Remaining / not-yet-done / still-references" claims — for each item the doc lists as still-present or still-to-do, grep the named file and confirm the in-scope reference is actually still there. If the only matches are out-of-scope (e.g. a sibling component that shares a name prefix), the file is *not* a remaining occurrence — do not list it.
- Described behavior, examples, and code snippets — confirm they match the post-change implementation, not a draft of it. If the doc says a handler calls some method for reason R, open the handler and verify both the call and the reason.
- No volatile anchors — do not write hard-coded line numbers (`lines 130–149`, `:765-771`) or exact occurrence counts that have no structural meaning; they rot on the next unrelated edit. Reference the symbol name, the function, or the section instead. If a number genuinely matters (a table count, an enum size), keep it but treat it as something Step 5 must re-verify on every future pass.
- No duplicated blocks — re-read the final diff hunk; a copy-paste while restructuring a section frequently leaves a stale strikethrough/old paragraph alongside the new one.

On each page whose claims this step verified, set or refresh a freshness marker near the top: `<!-- verified-against: <short commit sha> <YYYY-MM-DD> -->` — it tells the next reader (and the next run of this skill) when the page was last checked against the tree, which "recently edited" alone cannot.

In the Step 3 analysis output, add a short "Claims verified" list: each non-trivial factual assertion you added/changed, and the command or file read that confirmed it. An assertion you could not verify must be removed or rewritten until you can — never shipped on faith.

---

## Verification Checklist

Before completing, verify you have:

- [ ] Run `git diff origin/main...HEAD` (THREE dots) to see ONLY this branch's changes
- [ ] Read `[[INTERNAL_DOC_LOCATION]]/index.md` first and routed every write through it (creating it if absent)
- [ ] Examined EVERY code change and decided whether it changes behavior
- [ ] Searched for related documentation using the Grep tool first, then `rg` where it resolves on the host, then `grep -rnE` (excluding VCS, dependency, and build directories) for each behavior change
- [ ] Determined the owning page and action (add / correct in place / none) for each behavior change
- [ ] Provided markdown-formatted analysis output listing ALL behavior changes and their documentation status
- [ ] Recorded the **Public-doc impact** list (or its explicit "Public-doc impact: none" line) in the analysis output
- [ ] Actually edited documentation files so every owning page describes current behavior
- [ ] Ran the pinned-path guard before any rename/move/delete, and flagged any touched page over the size ceiling
- [ ] Verified documentation updates are proportional to code change scope
- [ ] **Performed Step 5: re-opened the source for every factual claim added/changed (file paths, symbol names, counts, enumerations, universal claims, "remaining" lists, described behavior), corrected any mismatch, propagated corrected counts everywhere they appear, removed hard-coded line numbers, checked for duplicated blocks, and set the `verified-against` marker on verified pages**
- [ ] Updated `index.md` and `glossary.md` in the same pass where the Structure Contract required it
- [ ] Stayed within `[[INTERNAL_DOC_LOCATION]]` boundaries

⚠️ If ANY behavior change is not reflected on its owning page, the task is incomplete.

Accountability Check:
- Behavior changes found: [COUNT]
- Functional impact assessment: [HIGH/MEDIUM/LOW]
- Documentation pages added / corrected in place: [COUNT] / [COUNT]
- Changes owing no documentation update (with justification): [COUNT]
- Justification: [Explain why the documentation actions match the behavior changes]
