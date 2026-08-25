---
name: docs-sync-external
description: Use when customer-facing or public documentation needs to catch up with internal docs or shipped changes — "our public docs still mention the old flag", "sync the user guide", "update the customer docs", "is anything in the external docs outdated or leaking internal detail?", "update the docs site". Narrower than prflow:docs; use prflow:docs-bootstrap-external when external docs do not exist yet.
---
> Configuration: Read documentation paths from `.prflow/config.json`:
> - Internal: `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.internal docs/internal/`
> - External: `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.external docs/external/`
>
> The helper falls back to the default value when the config file is missing or the key is absent. Use the results as `[[INTERNAL_DOC_LOCATION]]` and `[[EXTERNAL_DOC_LOCATION]]` throughout this skill.

**Portable helper anchor (single-statement).** The bundled-helper commands in this skill resolve the skill directory inline at each call site via `${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}`. When `$CLAUDE_SKILL_DIR` is set and non-empty (Claude Code), run each command exactly as written. Otherwise locate the directory yourself — this text lives in a file inside it, whose sibling `../../scripts/` directory exists — by replacing the placeholder with the skill base directory the runner reports in context (e.g. a `Base directory for this skill:` line) and accepting a candidate only once `ls <candidate>/../../scripts/` succeeds in the same shell the helper commands run in. If a path form is rejected, use the form that shell reports (`pwd` shows it); a Windows-form base directory (`C:\...`) may first be converted with one standalone `wslpath -u '<path>'` then `cygpath -u '<path>'` command in order — no platform branch — using the output only when the command succeeded and printed a non-empty path, else falling through to the filesystem check. Resolve the anchor inline at every call site — never capture it into a shell variable that a later statement reads, because some runners' inline-bash marshaling drops such variables. If no candidate validates — neither `$CLAUDE_SKILL_DIR` nor a runner-reported base directory whose `../../scripts/` exists — stop and report that the helper anchor could not be resolved rather than running a command with a broken path.

Consumer prompt extension (load first). Before doing this skill's work, load any consumer-supplied prompt extension for this skill and honor it. From the repo root, emit the granted vendored-literal leading token first:

```bash
.prflow/vendor/prflow/scripts/load-prompt-extension.sh docs-sync-external
```

On a `command not found` / `No such file` / exit-127 reading (this repository's own local tier, where `.prflow/vendor/` is materialized only at runtime), re-invoke the same helper with the `.prflow/vendor/prflow/` prefix removed (`scripts/load-prompt-extension.sh docs-sync-external`) as a single leading-token statement. If that too is not found (a non-Claude-Code runner where neither repo-relative path exists), fall back to the portable anchor form:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh docs-sync-external
```

If the invocation fails because the helper path does not exist (`No such file`, exit 127, or the platform equivalent) on every form above, that is the anchor-resolution failure described in the *Portable helper anchor* note above — fix the anchor, don't report a missing extension. If instead the harness refuses the command outright — a permission denial rather than a missing file — the extension's state is **unestablished**: report that in the run's output and never treat it as a clean policy pass (*unknown is not zero*). Otherwise, if the helper exits non-zero, a consumer extension exists but could not be loaded — surface its stderr message and do not silently proceed as if none existed. If it exits 0 and prints text, treat that text as additional instructions appended to the end of this skill's own prompt for this run — it is upgrade-safe, consumer-owned customization committed under `.prflow/prompt-extensions/`. If it exits 0 and prints nothing, proceed unchanged.

# External Documentation Alignment Agent

## Objective
You are an AI Documentation Alignment Agent. Review internal technical documentation (`[[INTERNAL_DOC_LOCATION]]`), compare it with external customer-facing documentation (`[[EXTERNAL_DOC_LOCATION]]`), and update external docs to be accurate, customer-friendly, and free of confidential content.

## Preflight

Check the documentation trees before doing anything:
- If `[[INTERNAL_DOC_LOCATION]]` is empty or absent, there is no source of truth to align from — stop and report that internal docs should be created first (run `/prflow:docs-bootstrap-internal` or `/prflow:docs-sync-internal`).
- If `[[EXTERNAL_DOC_LOCATION]]` is empty or absent, this is a first-time bootstrap, not an alignment — defer to `/prflow:docs-bootstrap-external` rather than aligning against nothing.

## Execution Model

⚠️ This prompt requires TWO actions:
1. Provide Status Summary — Structured alignment report for each topic analyzed
2. Actually Edit Documentation Files — Make real file changes in `[[EXTERNAL_DOC_LOCATION]]`

Both are mandatory. Analysis without file edits is incomplete.

---

## Tasks

### 1. Analyze and Compare
Work on one topic/feature at a time.

Before creating new docs, always search for existing content:
1. Read `[[EXTERNAL_DOC_LOCATION]]*`
2. Search for relevant topics by file/directory names
3. If a topic exists, update it rather than creating a duplicate

Categorize findings as:
- ✅ Aligned — External matches internal truth
- ⚠️ Outdated — External references old or deprecated details
- ❌ Missing — Important internal information absent externally
- 🔒 Internal-only — Confidential information that must not appear externally

### 2. Draft Updates
For each Outdated or Missing item:
- Rewrite or extend the external documentation
- Use a customer-appropriate tone (concise, instructive, non-technical where possible)
- Follow the Style Guide below for writing and formatting standards
- Keep hub pages focused; create child pages for deep how-to's and troubleshooting
- Exclude confidential or internal-only details

### 3. Housekeeping
- Remove any **Internal-only** sections from external documentation
- Never create parent/hub documents
- Never remove existing images or attachments

---

## Content Guidelines

### Include:
- Feature descriptions and benefits
- User-facing workflows and processes
- Setup and configuration instructions (customer-level)
- Troubleshooting and FAQs
- Integration steps (from user perspective)
- Best practices and recommendations

### Exclude:
- Internal API implementation details
- Database schema or SQL scripts
- Internal build/deployment processes
- Proprietary algorithms or business logic
- Internal tooling or admin-only features
- Security-sensitive configuration details
- Third-party API keys or credentials

---

## File Naming
Use the naming convention: `{short-descriptive-name}.md` with concise, hyphenated names.

---

## Quality Standards
- Accuracy: External docs must align with internal source of truth
- Clarity: Simple, clear language; avoid jargon
- Completeness: Cover all necessary user-facing aspects
- Security: Never expose confidential information
- Consistency: Consistent tone, terminology, and formatting

---

## Workflow Steps

Step 1: Understand Context
- Read `CLAUDE.md` for product overview
- Scan internal documentation (`[[INTERNAL_DOC_LOCATION]]`) for recent changes or new features

Step 2: Compare Documentation
- Compare with corresponding external documentation (`[[EXTERNAL_DOC_LOCATION]]`)
- Identify gaps, outdated content, or misalignments

Step 3: Create/Update Files
- Create/update external MD files in `[[EXTERNAL_DOC_LOCATION]]` as needed
- Follow all naming, formatting, and style guidelines from the Style Guide below

Only edit customer-facing files in `[[EXTERNAL_DOC_LOCATION]]` and its subdirectories.

---

## Style Guide

This Style Guide is the single source for customer-facing style mechanics — AP style, the Oxford-comma rule, preferred word choices, and the formatting conventions below. For the rules that are not audience-specific, follow the shared writing standard `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/writing-standard.md`; a failed load emits a breadcrumb naming the file and the failure kind, and you compose without it.

### Tone and Voice
- Clear, straightforward, and informative: Professional yet accessible
- Avoid jargon and overly technical language
- Use consistent terminology throughout
- Include helpful notes and tips where needed, but keep them concise
- Maintain a neutral, objective tone

### General Writing Guidelines
- Audience: Customers
- Use "and" instead of ampersands (&); write "percent" instead of %
- Punctuation outside quotes when quoting UI text
- Use colon format for defined terms in lists (Term: Description.)
- Use complete sentences in lists when possible
- Use full product name on first mention, then shorten naturally
- Use "user interface" instead of "UI"

### Content Organization
- Keep hub pages concise; break deep how-to's into separate pages
- Add short purpose line under each header
- Summarize processes in 2-3 sentences, then link to dedicated articles
- Add "See also" or "Related Articles" links
- Insert screenshot placeholders at UI/action points (e.g., "[Screenshot: Save button location]")

### Abbreviations and Numbers
- Spell out numbers < 10; use numerals >= 10
- Avoid Oxford comma per AP style
- Use ISO 4217 currency codes (USD, CAD, EUR)
- Use two-digit ISO country codes (US, UK, DE)
- Use B, MB, GB for file sizes

### Product and Technical Terms
- Write out acronyms on first use with abbreviation in parentheses
- Common technical terms (URL, HTTP, HTTPS) need not be written out
- Log in (verb), login (noun)
- Set up (verb), setup (noun)
- Username: One word; File name: Two words
- Prefer "use" over "utilize"
- Prefer "enter" over "type", "display" over "show"

### User Actions
- Click: Desktop (buttons, links); Tap: Mobile
- Press: Keyboard keys; Select: Dropdowns, menus
- Bold UI element names; omit element type unless needed for clarity

### MD Formatting
- Start page headings with H1; use title case for headings
- Bold UI elements; italics for emphasis
- Numbered steps for sequential processes only; imperative tone
- Start bullet items with capital letters
- Callouts: Bold label + colon (Note:, Tip:, Warning:); use sparingly
- Tables: Bold header row, left-align text, right-align numbers
- Never remove existing images or attachments
- Use fenced code blocks with proper indentation
