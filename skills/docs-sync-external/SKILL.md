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
You are an AI Documentation Alignment Agent. Review internal technical documentation (`[[INTERNAL_DOC_LOCATION]]`), compare it with external user-facing documentation (`[[EXTERNAL_DOC_LOCATION]]`), and update external docs to be accurate, audience-appropriate, and free of confidential content.

External documentation exists for the humans who use the product. They cannot read the code, so every page must be precise, easy to read, well structured, and rich in worked examples — a page that is accurate but unusable has failed its reader.

Proportionality: match the size of the documentation update to the user-visible impact of the change. A change users never observe needs no external edit; a changed workflow needs its page rewritten, not a sentence appended.

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

### 0. Determine the Audience
Identify who this repository's product serves before writing a word, because register, examples, and depth all depend on it. Read the project memory file (e.g. `CLAUDE.md`), the README, and the product's own surface (commands, UI, API) and classify the reader: developers using a tool or library, employees using enterprise software, end users of a consumer application, or administrators operating a system. Record the determined audience in the Status Summary; every "user-appropriate" judgment below resolves against it, so for a developer tool "non-technical" wording is wrong, not safe.

### 1. Scope, Analyze and Compare
Scope the comparison before analyzing, or the pass either re-litigates the whole site or works from guesses:
- When a caller (the combined docs pass) supplied a summary of internal-doc changes, those changes plus the branch diff define the topics in scope — the caller's summary takes precedence where the two disagree. Tolerate its absence: it is an optional handoff.
- Standalone, scope by the branch diff (`git diff origin/main...HEAD`, THREE dots to exclude merged commits).
- Perform a full-tree alignment only when the request explicitly asks for one.

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
- Write for the audience determined in Task 0 (concise, instructive, at the reader's technical level)
- Follow the Style Guide below for writing and formatting standards
- Keep hub pages focused; create child pages for deep how-to's and troubleshooting
- Exclude confidential or internal-only details

Every page that teaches a procedure carries at least one worked, copy-pasteable example with its expected output — a procedure the reader cannot execute verbatim is a description, not documentation. Every troubleshooting section leads with the verbatim error or symptom text the user sees, then the diagnostic command, then the fix, so the page is findable by searching the error.

### 3. Site Structure and Navigation
- If `[[EXTERNAL_DOC_LOCATION]]` contains a navigation manifest (`docs.json`, `mkdocs.yml`, `SUMMARY.md`, `_sidebar.md`, or the local equivalent), that manifest is the navigation source of truth: register every page you add, move, or delete in it in the same change, or the page is invisible on the published site.
- Every directory keeps an index/landing page that orients the reader and links its children; deep reference detail lives in the child pages, not the hub.
- Match the frontmatter convention of neighboring pages when creating a page — a page without the site's expected frontmatter renders with a filename-derived title.
- Link resolution: every cross-reference you write must point at a page that exists, in the link style the site already uses.

### 4. Housekeeping
- Remove any **Internal-only** sections from external documentation
- Never remove existing images or attachments
- Never edit the release-notes or changelog files — they are owned by the release-notes workflow
- Never delete the site's landing page or styling assets

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
- Read `CLAUDE.md` for product overview and determine the audience (Task 0)
- Establish the comparison scope (Task 1), then scan the in-scope internal documentation for changes or new features

Step 2: Compare Documentation
- Compare with corresponding external documentation (`[[EXTERNAL_DOC_LOCATION]]`)
- Identify gaps, outdated content, or misalignments

Step 3: Create/Update Files
- Create/update external MD files in `[[EXTERNAL_DOC_LOCATION]]` as needed
- Follow all naming, formatting, and style guidelines from the Style Guide below
- Register every added/moved/deleted page in the navigation manifest (Task 3)

Step 4: Verify Every User-Visible Claim Against the Code
⚠️ MANDATORY — internal docs are a lagging source of truth, so a claim copied from them can ship an error two hops from the code. Before finishing, verify each user-visible claim you wrote against the implementation itself:
- Commands, flags, and their spellings — confirm each exists in the code exactly as written
- Configuration keys, defaults, and file paths — confirm against the schema or the reader the code actually uses
- Described behavior and examples — confirm they match the shipped implementation, and that every example's expected output is what the command produces
- Cross-references — confirm every link you wrote resolves (Task 3)
A claim you cannot back with a code reading is hedged ("as of this release") or removed — never shipped on faith. Record a short "Claims verified" list in the Status Summary: each claim and the file read or command that confirmed it.

Only edit user-facing files in `[[EXTERNAL_DOC_LOCATION]]` and its subdirectories.

## Verification Checklist

Before completing, verify you have:

- [ ] Determined and recorded the audience (Task 0)
- [ ] Established the comparison scope and stated it in the Status Summary
- [ ] Categorized every in-scope topic (Aligned / Outdated / Missing / Internal-only)
- [ ] Actually edited files — analysis alone is incomplete
- [ ] Registered every page add/move/delete in the navigation manifest, where one exists
- [ ] Given every procedure page a worked example with expected output
- [ ] Performed Step 4: verified commands, keys, paths, behavior, and links against the code, and recorded the "Claims verified" list
- [ ] Left release-notes/changelog files, the landing page, and styling assets untouched
- [ ] Stayed within `[[EXTERNAL_DOC_LOCATION]]` boundaries

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
- Audience: the reader determined in Task 0 — calibrate vocabulary and depth to them
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
- Illustrate a UI step with a real committed screenshot or omit the image — never publish a placeholder, which reads as a broken page

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

### User Actions — Match the Product's Shape
For a product with a graphical interface:
- Click: Desktop (buttons, links); Tap: Mobile
- Press: Keyboard keys; Select: Dropdowns, menus
- Bold UI element names; omit element type unless needed for clarity

For a CLI, API, or library product these rules do not apply — the equivalents are:
- Verbatim commands in fenced blocks, each followed by its expected output
- Configuration shown as a copyable snippet in the product's actual config format
- Errors quoted verbatim, so the reader can search for the exact text they see

### Rich Components and Diagrams
- Where the site framework supports rich components (e.g. Mintlify), select by content shape: per-client or per-platform instructions → tabs; configuration keys → parameter fields; a caveat or destructive action → note/warning callout; a sequential procedure → steps; a hub page's children → card group. Plain Markdown headings for all of these waste the framework the site already pays for.
- When a flow spans three or more moving parts, a diagram earns its place: mermaid or a committed SVG that matches the site's palette, carries descriptive alt text, and stays legible in both light and dark modes.

### MD Formatting
- Start page headings with H1; use title case for headings
- Bold UI elements; italics for emphasis
- Numbered steps for sequential processes only; imperative tone
- Start bullet items with capital letters
- Callouts: Bold label + colon (Note:, Tip:, Warning:); use sparingly
- Tables: Bold header row, left-align text, right-align numbers
- Never remove existing images or attachments
- Use fenced code blocks with proper indentation
