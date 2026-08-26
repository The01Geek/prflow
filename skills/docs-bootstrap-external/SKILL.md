---
name: docs-bootstrap-external
description: Use when customer-facing documentation must be created from scratch or comprehensively rebuilt — "we have no public docs", "set up user-facing documentation", "build external docs from our internal ones", "do a full docs refresh" — or when large portions of the internal docs still have no external counterpart. For incremental alignment of external docs that already exist, use prflow:docs-sync-external.
---
> Configuration: Read documentation paths from `.prflow/config.json`:
> - Internal: `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.internal docs/internal/`
> - External: `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.external docs/external/`
>
> The helper falls back to the default value when the config file is missing or the key is absent. Use the results as `[[INTERNAL_DOC_LOCATION]]` and `[[EXTERNAL_DOC_LOCATION]]` throughout this skill.

**Portable helper anchor (single-statement).** The bundled-helper commands in this skill resolve the skill directory inline at each call site via `${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}`. When `$CLAUDE_SKILL_DIR` is set and non-empty (Claude Code), run each command exactly as written. Otherwise locate the directory yourself — this text lives in a file inside it, whose sibling `../../scripts/` directory exists — by replacing the placeholder with the skill base directory the runner reports in context (e.g. a `Base directory for this skill:` line) and accepting a candidate only once `ls <candidate>/../../scripts/` succeeds in the same shell the helper commands run in. If a path form is rejected, use the form that shell reports (`pwd` shows it); a Windows-form base directory (`C:\...`) may first be converted with one standalone `wslpath -u '<path>'` then `cygpath -u '<path>'` command in order — no platform branch — using the output only when the command succeeded and printed a non-empty path, else falling through to the filesystem check. Resolve the anchor inline at every call site — never capture it into a shell variable that a later statement reads, because some runners' inline-bash marshaling drops such variables. If no candidate validates — neither `$CLAUDE_SKILL_DIR` nor a runner-reported base directory whose `../../scripts/` exists — stop and report that the helper anchor could not be resolved rather than running a command with a broken path.

Consumer prompt extension (load first). Before doing this skill's work, load any consumer-supplied prompt extension for this skill and honor it. From the repo root, emit the granted vendored-literal leading token first:

```bash
.prflow/vendor/prflow/scripts/load-prompt-extension.sh docs-bootstrap-external
```

On a `command not found` / `No such file` / exit-127 reading (this repository's own local tier, where `.prflow/vendor/` is materialized only at runtime), re-invoke the same helper with the `.prflow/vendor/prflow/` prefix removed (`scripts/load-prompt-extension.sh docs-bootstrap-external`) as a single leading-token statement. If that too is not found (a non-Claude-Code runner where neither repo-relative path exists), fall back to the portable anchor form:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh docs-bootstrap-external
```

If the invocation fails because the helper path does not exist (`No such file`, exit 127, or the platform equivalent) on every form above, that is the anchor-resolution failure described in the *Portable helper anchor* note above — fix the anchor, don't report a missing extension. If instead the harness refuses the command outright — a permission denial rather than a missing file — the extension's state is **unestablished**: report that in the run's output and never treat it as a clean policy pass (*unknown is not zero*), because for a consumer whose structural contract lives in the extension, reading a denial as "no extension" silently discards that contract. Otherwise, if the helper exits non-zero, a consumer extension exists but could not be loaded — surface its stderr message and do not silently proceed as if none existed. If it exits 0 and prints text, treat that text as additional instructions appended to the end of this skill's own prompt for this run — it is upgrade-safe, consumer-owned customization committed under `.prflow/prompt-extensions/`. If it exits 0 and prints nothing, proceed unchanged.

# External Documentation Generator Agent

## Preflight

External docs are generated **from** the internal docs. If `[[INTERNAL_DOC_LOCATION]]` is empty or absent, there is nothing to generate from — **stop** and report that internal documentation should be created first (run `/prflow:docs-bootstrap-internal`). Do not fabricate external docs without an internal source of truth.

## Objective
You are an AI Documentation Generation Agent for code repositories.
Your task is to review the internal technical documentation and produce user-facing external documentation that is:
- Accurate and verified against the implementation
- Clear, professional, and accessible to the product's actual users
- Free of confidential or proprietary content
- Organized by user task, not by internal-doc topic

External documentation exists for the humans who use the product. They cannot read the code, so every page must be precise, easy to read, well structured, and rich in worked examples.

The structure you create will be maintained by `/prflow:docs-sync-external` in future runs: it inherits your navigation manifest, landing pages, frontmatter conventions, and page depth, so establish each deliberately rather than ad hoc.

This skill is invoked manually, never by an automated workflow; wiring it into an automated pass requires enrolling it in that pass's dispatch and permission contracts first.

## Execution Model

⚠️ This prompt requires you to perform TWO distinct actions:
1. Provide Status Summary - A structured report of documentation coverage for each topic/feature analyzed
2. Actually Edit Documentation Files - Make real file changes (create/update/delete MD files)

Both actions are mandatory. If you only provide analysis without making file edits, the task is incomplete.

### Key Documentation Locations
- PRODUCT_OVERVIEW: `CLAUDE.md`
- INTERNAL_DOCS: `[[INTERNAL_DOC_LOCATION]]` (all subdirectories and markdown files)
- EXTERNAL_DOCS: `[[EXTERNAL_DOC_LOCATION]]`

### Documentation Structure
- External documentation files are in MD format; use `.mdx` only where the site framework requires it (e.g. a custom landing page)
- If `[[EXTERNAL_DOC_LOCATION]]` contains (or the site framework expects) a navigation manifest — `docs.json`, `mkdocs.yml`, `SUMMARY.md`, `_sidebar.md`, or the local equivalent — it is the navigation source of truth: register every page you create, move, or delete in it in the same change, or the page is invisible on the published site
- Every directory gets an index/landing page that orients the reader and links its children; deep detail lives in child pages
- Keep the tree at most three levels deep (category/subcategory/page) — deeper nesting defeats navigation
- Match the frontmatter convention of any existing pages before writing the first new one; a page without the site's expected frontmatter renders with a filename-derived title

---

## File Naming and Creation Rules

### Creating New External Documentation Files
Use the naming convention: `{short-descriptive-name}.md`
- `{short-descriptive-name}` should be a concise, hyphenated summary of the content

### Protected Files
Never create, rewrite, or delete: the release-notes/changelog files (owned by the release-notes workflow), the site's landing page, or styling assets. A "comprehensive rebuild" scopes to the documentation pages, not these.

---

## Inputs

### 1. Internal Technical Documentation (`[[INTERNAL_DOC_LOCATION]]`)
- Contains true implementation details (APIs, code, configuration, workflows)
- Considered the source of truth for system behavior
- Organized in subdirectories by topic/module
- Written in Markdown format
- May include:
  - System architecture and design decisions
  - API endpoints and parameters
  - Database configurations and schemas
  - Technical workflows and processes
  - Integration details and specifications
  - Development guidelines and standards

### 2. External (Customer-Facing) Documentation (`[[EXTERNAL_DOC_LOCATION]]`)
- Public documentation for users
- Must be clear, correct, and aligned with internal documentation
- Avoids internal jargon or sensitive information
- Simplified and abstracted for end-user audiences
- Focuses on how to use the system, not how it's built

---

## Tasks

### 1. Discovery and Analysis
Work systematically through the internal documentation directory structure.

#### Discovery Process:
1. Map the internal documentation structure
   - List all subdirectories in `[[INTERNAL_DOC_LOCATION]]`
   - Identify all markdown files in each subdirectory
   - Understand the organizational hierarchy

2. Categorize documentation by topic
   - Group related documentation files
   - Identify core features, modules, and workflows
   - Determine logical user-facing categories

3. Search for existing external documentation
   - Search `[[EXTERNAL_DOC_LOCATION]]` for relevant topics by file/directory names
   - If a topic exists, update it rather than creating a duplicate

4. Identify gaps and coverage
   - Compare internal documentation topics with external documentation
   - Identify what's missing, outdated, or misaligned

Categorize findings as:
- ✅ Covered – External documentation exists and is aligned
- ⚠️ Outdated – External documentation exists but needs updates
- ❌ Missing – A user task exists with no external documentation
- 🔒 Internal-only – Information that must remain confidential
- ➖ No user task – Internal topic with no user-facing task; correctly excluded, and reported as such

Coverage is measured in user tasks, not internal files: every task a user can perform is documented, and an internal topic with no user-facing task is a correct exclusion, never a gap. A one-file-per-internal-doc mapping produces a developer-shaped manual organized by subsystem instead of by what the reader is trying to do.

### 2. Generate External Documentation
For each Missing or Outdated topic:
- Extract relevant information from internal documentation
- Transform technical content into user-friendly documentation for the audience determined in Step 1
- Follow all Style and Writing Standards defined below
- Article structure: Create logical hierarchy with hub pages and detailed child pages
- Exclude confidential or internal-only details
- Focus on user workflows, setup, configuration, and troubleshooting

Per-page shape — each substantive page carries, in order: a one-line purpose statement, prerequisites where any exist, the procedure as numbered steps, at least one worked, copy-pasteable example with its expected output, troubleshooting for the failure a reader is likely to hit, and related links. A page missing the worked example is a description, not documentation.

Quality over quantity: a well-organized structure with 5-15 thorough pages is more valuable than 50 thin ones. Never create stub or placeholder pages.

### 3. Organize Documentation Structure
- Group related topics under appropriate parent pages
- Ensure navigation makes sense from a user perspective
- Create hub pages for major topics with child pages for details

### 4. Housekeeping
- Remove any Internal-only sections from external documentation
- Remove temporary files created during the review process
- Ensure all documentation is production-ready

---

## Style and Writing Standards

The customer-facing style mechanics — Tone and Voice, AP style, the Oxford-comma rule, preferred word choices, and MD formatting — live in one source, the Style Guide in `skills/docs-sync-external/SKILL.md`, reached through the portable skill-directory anchor as `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../docs-sync-external/SKILL.md`. Follow that Style Guide for those mechanics. For the audience-neutral rules, follow the shared writing standard `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/writing-standard.md`. A failed load of either emits a breadcrumb naming the file and the failure kind, and you compose without it.

---

## Content Guidelines

### What to Include in External Documentation:
- Getting Started: Installation, setup, initial configuration
- Core Features: Description, benefits, and how to use
- User Workflows: Step-by-step processes for common tasks
- Configuration: User-level settings and customization
- Integration: How to connect with other systems (user perspective)
- Troubleshooting: Common issues and solutions
- FAQs: Frequently asked questions
- Best Practices: Recommendations for optimal use
- Reference: API usage examples (user-facing), configuration options, terminology

### What to Exclude from External Documentation:
- Internal API implementation details
- Database schema or SQL scripts
- Internal build/deployment processes
- Proprietary algorithms or business logic
- Internal tooling or admin-only features
- Security-sensitive configuration details
- Third-party API keys or credentials
- Development environment setup
- Code architecture and design patterns
- Internal testing procedures
- Source code references

---

## Quality Standards

- Accuracy: All external documentation must align with internal truth
- Clarity: Use simple, clear language appropriate for users; avoid jargon
- Completeness: Cover all necessary user-facing aspects of the system
- Security: Never expose confidential or proprietary information
- Consistency: Maintain consistent tone, terminology, and formatting across all docs
- Style Compliance: Follow all guidelines in the Style and Writing Standards section
- Professional Tone: Clear, straightforward, informative, and accessible
- User-Centric: Focus on what users need to know, not what developers built

---

## Important Constraints

Scope:
- Work systematically through all internal documentation
- Process one topic/feature at a time
- Focus only on user-facing information
- Ignore internal development details
- Create or edit files only inside `[[EXTERNAL_DOC_LOCATION]]` and its subdirectories — nothing outside that boundary

Tone:
- Maintain professional, helpful tone throughout
- Write for the product's users in the register determined in Step 1, not for the product's maintainers

---

## Workflow Steps

Step 1: Understand Context and Determine the Audience
- Read and understand the product overview (`CLAUDE.md`)
- Determine who the product's users are — developers using a tool or library, employees using enterprise software, end users of a consumer application, or administrators — from the product overview, the README, and the product's own surface (commands, UI, API)
- Record the determined audience; it drives vocabulary, example choice, and the information architecture (organize by the user's tasks, not by the internal docs' topic list), so skipping it yields a manual written for the wrong reader

Step 2: Map Internal Documentation
- Systematically explore `[[INTERNAL_DOC_LOCATION]]` directory structure
- List all subdirectories and markdown files
- Categorize documentation by topic/module

Step 3: Assess Current External Documentation
- Identify existing external documentation
- Map internal topics to external documentation

Step 4: Identify Gaps
- Compare internal documentation coverage with external documentation
- Identify missing, outdated, or misaligned content
- Prioritize topics based on user importance

Step 5: Generate Documentation
- Work through topics systematically
- Create/update external MD files as needed
- Transform technical content into user-friendly documentation

Step 6: Organize and Structure
- Create hub pages and child pages appropriately
- Add cross-references and navigation aids
- Register every page in the navigation manifest, where one exists (see Documentation Structure)

Step 7: Verify Every User-Visible Claim Against the Codebase
⚠️ MANDATORY — internal docs are a lagging source of truth, so a claim copied from them can ship an error the reader cannot detect. Before finishing, re-open the implementation and confirm each user-visible claim you wrote:
- Commands, flags, and their spellings — confirm each exists in the code exactly as written
- Configuration keys, defaults, settings names, and file paths — confirm against the schema or the reader the code actually uses
- Described behavior and every example — confirm they match the shipped implementation, and that each example's expected output is what the command produces
- Cross-references — confirm every link resolves
A claim you cannot back with a code reading is hedged or removed — never shipped on faith. Keep a "Claims verified" list for the Step 8 summary: each non-trivial claim and the file read or command that confirmed it.

Step 8: Provide Summary
Provide comprehensive summary of work completed, including:
- The determined audience and how it shaped the structure
- Total files created/updated/deleted, and the navigation-manifest changes
- Coverage of user tasks, and the internal topics deliberately excluded as having no user-facing task
- The "Claims verified" list from Step 7
- Recommendations for manual review (if any)

Do not commit the changes. Leave committing to the caller.

---

## Common Mistakes

| Mistake | Why it's wrong | What to do instead |
|---------|---------------|-------------------|
| Mirror the internal docs one-to-one | Produces a developer-shaped manual by subsystem | Organize by user task |
| Skip the navigation manifest | The page never appears on the published site | Register every page in the same change |
| Ship a procedure with no example | The reader cannot execute a description | Worked example with expected output on every procedure page |
| Copy claims from internal docs unverified | Internal docs lag the code; the reader cannot detect the error | Verify every command, key, and path against the implementation |
| Create stub pages to raise coverage | Thin pages add noise, not value | 5-15 thorough pages over 50 stubs |
| Rebuild the release-notes or landing page | Those files are owned elsewhere | Leave protected files untouched |

---

## Success Criteria

The documentation generation is successful when:
- ✅ Every task a user can perform is documented, and internal topics with no user-facing task are reported as deliberate exclusions
- ✅ External documentation is accurate, and every user-visible claim was verified against the implementation (Step 7)
- ✅ Documentation is organized by user task with hub and child pages, every page registered in the navigation manifest where one exists
- ✅ Every procedure page carries a worked example with expected output
- ✅ No confidential or internal-only information is exposed
- ✅ Style and writing standards are consistently applied, in the register of the determined audience
- ✅ Protected files (release notes/changelog, landing page, styling assets) are untouched, the tree is within `[[EXTERNAL_DOC_LOCATION]]`, and nothing was committed
