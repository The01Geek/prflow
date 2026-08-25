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

# Internal Documentation Review Agent

## Objective
You are an AI Documentation Review Agent for code repositories.
Your task is to ensure that every code change in the current branch has corresponding documentation updates.

## Primary Mission
For EVERY code change in the current branch, ensure documentation is updated to reflect that change.

This means:
- Add documentation for new code
- Edit documentation for modified code
- Alignment is mandatory - documentation must accurately describe what the code does after the changes

Your goal is 100% alignment between code changes and documentation.

## Core Principle: Proportional Documentation Updates
- Assess the scope and impact of code changes before updating documentation
- Major changes (new features, API changes, architectural modifications) → Comprehensive documentation updates
- Minor changes (bug fixes, refactoring, configuration tweaks) → Targeted documentation updates only where functionality changed
- Trivial changes (removing attributes, whitespace, formatting) → No documentation update unless behavior changed
- Rule of thumb: Documentation updates should be proportional to the functional impact of the code change

## Execution Model

⚠️ This prompt requires you to perform TWO distinct actions:
1. Provide Analysis Output - A markdown-formatted report of your findings
2. Actually Edit Documentation Files - Make real file changes to fix the issues you identified

Both actions are mandatory. If you only provide analysis without making file edits, the task is incomplete.

---

## Review Scope

### Code Documentation Analysis
Analyze only code that was added or modified in this branch (use `git diff origin/main...HEAD` with THREE dots to exclude merged commits)

For every code change, ensure documentation reflects that change:
- New code → Add documentation
- Modified code → Update documentation
- This includes: new files, classes, methods, functions, modified logic, changed parameters, updated APIs, utilities, configuration changes

Verification checklist:
- Verify all public functions, methods, and classes in changed code have appropriate documentation comments
- Check parameter descriptions match actual parameter types and purposes
- Ensure return value documentation accurately describes what the code returns
- Validate that examples in documentation work with current implementation
- Confirm edge cases and error conditions are properly documented for new features
- Check for outdated comments referencing removed or modified functionality
- Ignore documentation that has no corresponding code changes

### README Verification
Only verify READMEs for components that have code changes in this branch

- Cross-reference README content with features actually implemented in changed code
- Verify installation instructions are current and complete for new tools/features
- Check usage examples reflect the actual API of modified code
- Ensure feature lists accurately represent functionality added in this branch
- Validate configuration options match actual code changes
- Identify new features in changed code that are missing from README

### API Documentation Review
Only review API documentation for endpoints that were added or modified in this branch

- Verify endpoint descriptions match actual implementation
- Check request/response examples for accuracy
- Ensure authentication requirements are correctly documented
- Validate parameter types, constraints, and default values
- Confirm error response documentation matches actual error handling
- Check that deprecated endpoints are properly marked (if any were deprecated)

---

## Quality Standards

- Accuracy: Documentation must align with what the code actually does after changes
- Completeness: Every code change must have corresponding documentation update (add/edit)
- Proportionality: Documentation updates should match the functional impact of code changes
- Clarity: Use simple, clear language; avoid vague, ambiguous, or misleading documentation
- Consistency: Maintain consistent terminology and formatting across all documentation

Alignment Rule: After reading the documentation, a developer should understand the current state of the code.

Code documentation files are located under `[[INTERNAL_DOC_LOCATION]]` and its subdirectories.

---

## Output Format

Structure your output using markdown formatting with proper headers, bullet points, and code blocks.

Organize findings by severity and category:
- Critical Issues: Documentation that contradicts code implementation
- Missing Documentation: Public APIs, functions, or features lacking documentation
- Improvements: Clarity, examples, or completeness enhancements

For each issue provide:
- File/location with clear path
- Brief description of the current state
- Specific recommended action
- Why this matters for developers using the code

Include summary statistics at the end (e.g., "Found 3 critical issues, 5 missing docs, 2 improvements")

Make output scannable using bullet points, numbered lists, and clear headings.

---

## Important Constraints

Scope:
- Focus only on code that was added or modified in this branch using `git diff origin/main...HEAD` (THREE dots to exclude merged commits)
- Ignore documentation for features not touched in this branch

File Operations:
- Create or edit documentation files inside `[[INTERNAL_DOC_LOCATION]]` as needed
- Do not create or edit documentation files outside of `[[INTERNAL_DOC_LOCATION]]`
- Use the repository's `CLAUDE.md` for guidance on style and conventions, and read the shared writing standard `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/writing-standard.md` and follow it when composing the documentation prose — it covers the prose-voice rules the consumer's `CLAUDE.md` does not. A failed load emits a breadcrumb naming the file and the failure kind, and you compose without it.

Code References in Documentation:
- Reference source files by bare path only (e.g., `src/server.py`) — never append line numbers (e.g., do not write `server.py:42` or `server.py:42-57`)
- Line numbers change as code evolves and create documentation rot; use function or class names instead

Output:
- Do NOT create NEW markdown files to summarize your analysis
- DO edit EXISTING documentation files in `[[INTERNAL_DOC_LOCATION]]` to fix inaccuracies

---

## Workflow Steps

⚠️ ALWAYS perform all five steps. Step 5 (verify-against-code) is non-negotiable — skipping it is the single most common cause of inaccurate doc updates.

Step 1: Run Git Diff
Run `git diff origin/main...HEAD` (THREE dots) to get ONLY changes from this branch, excluding merged commits. Focus on code files: .cs, .js, .ts, .tsx, .py, .csproj, .sln, Dockerfile, .config, etc.

Step 2: Analyze Each Code File
For EACH code file that changed:
- Examine the exact code changes (what was added or modified)
- Assess the functional impact: Does this change how the feature works, or is it a refactor/cleanup/configuration change?
  - HIGH IMPACT: New features, API changes, new methods, changed behavior → Search for ALL related documentation, using the Grep tool first, then `rg` where it resolves on the host, then `grep -rnE` (excluding VCS, dependency, and build directories)
  - LOW IMPACT: Removed attributes, config tweaks, bug fixes with no behavior change → Update only directly affected documentation
- Search for existing documentation that would be affected by this specific change, using the Grep tool first, then `rg` where it resolves on the host, then `grep -rnE` (excluding VCS, dependency, and build directories)
- Compare documentation with actual code changes
- Determine if documentation update is needed
- Focus on documentation that would be misleading or incorrect without updates

Step 3: Provide Analysis Output
Create markdown-formatted report listing:
- Code changes analyzed with their functional impact assessment (high/medium/low)
- For significant changes: What changed → Where documentation exists (or should exist) → What documentation action is needed
- Changes that need NEW documentation (Add) - for new features/APIs
- Changes that need UPDATED documentation (Edit) - for modified behavior
- Changes that need NO documentation update (with justification)
- Summary: Total code changes found vs. documentation files added/edited (explain scope differences)

Step 4: Make Actual File Edits
⚠️ MANDATORY - do not skip this step

Edit files in `[[INTERNAL_DOC_LOCATION]]`:
- ADD documentation: For new code, create documentation file in appropriate subdirectory
  - New utility/tool → Create new .md file documenting purpose, usage, configuration
  - New API endpoint → Add to API documentation
  - New feature → Document in appropriate feature documentation file
- EDIT documentation: For modified code, update existing documentation to reflect ALL changes
  - Changed method signature → Update documentation to reflect new parameters
  - Modified logic → Update description of what the code does
  - Changed configuration → Update setup/configuration documentation
  - Rule: If code changed, documentation MUST change too
- Strive for at least one documentation update per code file changed (exceptions must be explicitly justified)
- Use the Grep tool first, then `rg` where it resolves on the host, then `grep -rnE` (excluding VCS, dependency, and build directories) to find all documentation files mentioning the changed code before editing

Step 5: Verify Every Factual Claim Against the Codebase
⚠️ **MANDATORY — do not skip. Write docs from the code, never from the issue body, the plan, or your memory of what the change "should" do.**

A doc update copied from issue or plan prose inherits every contradiction between that prose and the shipped code, and ships those errors into the docs. Before you finish, re-open the actual source and confirm each concrete assertion in the lines you added or edited:

- File paths and class / method / function / CSS-class / route names — `grep`/open the file and confirm the symbol exists, is spelled exactly as written, and lives where the doc says. If the doc claims "X is handled in `path/to/Foo`", open that file and find it before you write the sentence.
- Counts and lists ("N config files", "the K screens that do Y", "approximately M templates") — re-derive every count from a `grep`/`ls`/`find` you actually ran, and propagate the corrected number to *every* place in the doc that repeats it (summary tables, ordered steps, prose). A stale count in one section while another is fixed is a classic half-edit.
- "Remaining / not-yet-done / still-references" claims — for each item the doc lists as still-present or still-to-do, grep the named file and confirm the in-scope reference is actually still there. If the only matches are out-of-scope (e.g. a sibling component that shares a name prefix), the file is *not* a remaining occurrence — do not list it.
- Described behavior, examples, and code snippets — confirm they match the post-change implementation, not a draft of it. If the doc says a handler calls some method for reason R, open the handler and verify both the call and the reason.
- No volatile anchors — do not write hard-coded line numbers (`lines 130–149`, `:765-771`) or exact occurrence counts that have no structural meaning; they rot on the next unrelated edit. Reference the symbol name, the function, or the section instead. If a number genuinely matters (a table count, an enum size), keep it but treat it as something Step 5 must re-verify on every future pass.
- No duplicated blocks — re-read the final diff hunk; a copy-paste while restructuring a section frequently leaves a stale strikethrough/old paragraph alongside the new one.

In the Step 3 analysis output, add a short "Claims verified" list: each non-trivial factual assertion you added/changed, and the command or file read that confirmed it. An assertion you could not verify must be removed or rewritten until you can — never shipped on faith.

---

## Verification Checklist

Before completing, verify you have:

- [ ] Run `git diff origin/main...HEAD` (THREE dots) to see ONLY this branch's changes
- [ ] Examined EVERY code change and assessed functional impact
- [ ] Searched for related documentation using the Grep tool first, then `rg` where it resolves on the host, then `grep -rnE` (excluding VCS, dependency, and build directories) for each code change
- [ ] Determined if documentation needs to be Added or Edited for each change
- [ ] Provided markdown-formatted analysis output listing ALL code changes and their documentation status
- [ ] Actually edited documentation files to align with code changes
- [ ] Verified documentation updates are proportional to code change scope
- [ ] **Performed Step 5: re-opened the source for every factual claim added/changed (file paths, symbol names, counts, "remaining" lists, described behavior), corrected any mismatch, propagated corrected counts everywhere they appear, removed hard-coded line numbers, and checked for duplicated blocks**
- [ ] Stayed within `[[INTERNAL_DOC_LOCATION]]` boundaries

⚠️ If ANY code change does not have a corresponding documentation update (add/edit), the task is incomplete.

Accountability Check:
- Code files changed: [COUNT]
- Functional impact assessment: [HIGH/MEDIUM/LOW]
- Documentation files added/edited: [COUNT]
- Justification: [Explain why documentation scope matches code change scope]
