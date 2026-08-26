<!-- prflow:docs-verify-ref mode=write file=skills/docs-verify/references/write-mode.md start -->

# Write-mode procedure

This reference carries the whole write-mode half of `/prflow:docs-verify`: the action paths, the file
operations, the quality bar, the scope constraints, and the completion criteria. It is loaded only
on the default (write) path. A `--report-only` run never loads it and never applies it — that run's
contract is the *Report-Only Output* section of `SKILL.md`.

## Determine actions needed — choose ONE path

Path A: Documentation is accurate and complete
- Provide analysis confirming accuracy
- No file edits needed
- Recommend areas for future enhancement

Path B: Documentation is outdated or inaccurate
- Identify specific inaccuracies
- Provide corrected content
- Edit the documentation file(s) to align with current code
- Preserve accurate sections while fixing inaccurate ones

Path C: Documentation is missing
- Analyze the codebase thoroughly
- Draft comprehensive documentation
- Create a new `.md` file in appropriate `[[INTERNAL_DOC_LOCATION]]` subdirectory
- When the documentation root keeps an `index.md` routing map, place the page where that map's taxonomy says it belongs and add a routing line for the page to the index in the same pass — an unregistered page is invisible to readers who navigate by the map
- Include all essential information about the topic

## Quality Checklist

- [ ] All related code files examined
- [ ] Documentation content compared against actual code behavior
- [ ] Inaccuracies identified and corrected
- [ ] Missing sections added
- [ ] Documentation file(s) created or edited
- [ ] Outdated references removed or updated

## File Operations

### Creating New Documentation
- Create in appropriate `[[INTERNAL_DOC_LOCATION]]` subdirectory
- Use Markdown formatting with clear structure
- Open with a 2-4 line plain-language summary of what the page covers and who reads it, and write timeless present-tense reference prose — issue numbers stay out of headings and provenance goes in a single trailing line, because per-change narrative turns a reference page into a decision log
- Include: Overview, Key Components, Code Examples, Configuration, Important Notes
- Follow existing documentation style and formatting in `[[INTERNAL_DOC_LOCATION]]`
- Reference source files by bare path only (e.g., `src/app/server.py`) — never append line numbers (e.g., do not write `server.py:42`); use function or class names instead, as line numbers change as code evolves

### Editing Existing Documentation
- Update content to match current code
- Preserve accurate sections
- Replace/update inaccurate sections
- Add missing details
- Remove outdated information
- Maintain consistent formatting

### File Naming
Use descriptive names matching the topic:
- Lowercase with hyphens: `feature-name.md`
- Examples: `customer-auto-verification.md`, `order-backorder-system.md`

## Quality Standards

- Audience: future coding agents and developers exploring this codebase — the documentation is their map, so optimize every page for a reader arriving with zero context
- Accuracy: Every statement must reflect current code implementation
- Completeness: All essential information about the topic must be included
- Clarity: Use simple, clear language that developers can understand
- Consistency: Match formatting and style of existing documentation files
- Examples: Include code examples showing actual usage where applicable
- Alignment Rule: After reading the documentation, a developer should understand the current implementation

## Important Constraints

Scope:
- Focus only on the specified topic
- Search comprehensively for all related code and documentation
- Stay within `[[INTERNAL_DOC_LOCATION]]` boundaries for edits

File Operations:
- Create or edit only documentation files inside `[[INTERNAL_DOC_LOCATION]]`
- Do not modify code files
- Do not modify files outside `[[INTERNAL_DOC_LOCATION]]`

## Verification Checklist

Before completing, verify you have:

- [ ] Located all existing documentation about the topic
- [ ] Searched codebase comprehensively for related code
- [ ] Compared documentation against actual code implementation
- [ ] Identified inaccuracies, missing content, and outdated information
- [ ] Determined if documentation needs to be Created, Edited, or is Accurate
- [ ] Created or edited documentation files as needed
- [ ] Ensured documentation aligns with current code
- [ ] Re-opened the source for every factual claim you added or edited — file paths, symbol names, counts, described behavior — and corrected any mismatch; a claim you cannot verify against the code is removed or rewritten until you can, never shipped on faith
- [ ] Set or refreshed a `<!-- verified-against: <short-sha> <date> -->` marker near the top of each page you verified, so a later reader can tell a checked page from an abandoned one
- [ ] Registered any created page in the documentation root's `index.md` routing map, where one exists
- [ ] Verified documentation is complete and accurate
- [ ] Stayed within `[[INTERNAL_DOC_LOCATION]]` boundaries

## Task Complete When

1. Documentation accurately reflects current code implementation
2. All important details about the topic are documented
3. No contradictions between documentation and code
4. Documentation file(s) created/updated in `[[INTERNAL_DOC_LOCATION]]`
5. Nothing is committed — leave committing to the caller

<!-- prflow:docs-verify-ref mode=write file=skills/docs-verify/references/write-mode.md end -->
