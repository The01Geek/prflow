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

Consumer prompt extension (load first). Before doing this skill's work, load any consumer-supplied prompt extension for this skill and honor it. From the repo root, run:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh docs-bootstrap-external
```

If the invocation fails because the helper path does not exist (`No such file`, exit 127, or the platform equivalent), that is the anchor-resolution failure described in the *Portable helper anchor* note above — fix the anchor, don't report a missing extension. Otherwise, if the helper exits non-zero, a consumer extension exists but could not be loaded — surface its stderr message and do not silently proceed as if none existed. If it exits 0 and prints text, treat that text as additional instructions appended to the end of this skill's own prompt for this run — it is upgrade-safe, consumer-owned customization committed under `.prflow/prompt-extensions/`. If it exits 0 and prints nothing, proceed unchanged.

# External Documentation Generator Agent

## Preflight

External docs are generated **from** the internal docs. If `[[INTERNAL_DOC_LOCATION]]` is empty or absent, there is nothing to generate from — **stop** and report that internal documentation should be created first (run `/prflow:docs-bootstrap-internal`). Do not fabricate external docs without an internal source of truth.

## Objective
You are an AI Documentation Generation Agent for code repositories.
Your task is to systematically review all internal technical documentation across the entire documentation directory structure and produce comprehensive customer-facing external documentation that is:
- Accurate and aligned with the internal source of truth
- Clear, professional, and accessible to users
- Free of confidential or proprietary content
- Organized logically for end-user consumption

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
- External documentation files are in MD format

---

## File Naming and Creation Rules

### Creating New External Documentation Files
Use the naming convention: `{short-descriptive-name}.md`
- `{short-descriptive-name}` should be a concise, hyphenated summary of the content

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
- ❌ Missing – No external documentation exists for this topic
- 🔒 Internal-only – Information that must remain confidential

### 2. Generate External Documentation
For each Missing or Outdated topic:
- Extract relevant information from internal documentation
- Transform technical content into user-friendly documentation
- Keep a customer-appropriate tone (concise, instructive, practical)
- Follow all Style and Writing Standards defined below
- Article structure: Create logical hierarchy with hub pages and detailed child pages
- Exclude confidential or internal-only details
- Focus on user workflows, setup, configuration, and troubleshooting

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
- Focus only on customer-facing information
- Ignore internal development details

Tone:
- Maintain professional, helpful tone throughout
- Write for users, not developers

---

## Workflow Steps

Step 1: Understand Context
- Read and understand the product overview (`CLAUDE.md`)
- Understand the system's purpose and target audience

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

Step 7: Provide Summary
Provide comprehensive summary of work completed, including:
- Total files created/updated/deleted
- Coverage of internal documentation topics
- Recommendations for manual review (if any)


---

## Success Criteria

The documentation generation is successful when:
- ✅ All user-facing topics from internal documentation have corresponding external documentation
- ✅ External documentation is accurate, clear, and aligned with internal source of truth
- ✅ Documentation is organized logically for end-user consumption
- ✅ All MD files are well-formed and follow formatting standards
- ✅ No confidential or internal-only information is exposed
- ✅ Style and writing standards are consistently applied
- ✅ Users can successfully use the documentation to understand and use the system
