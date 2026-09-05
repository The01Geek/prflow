---
name: docs-bootstrap-internal
description: Use when a codebase has no structured developer documentation yet and needs it built from scratch — "we have no docs at all", "set up internal docs for this repo", "the docs directory is a mess, start over", "create developer documentation for this codebase" — including an empty or disorganized docs directory or a ground-up reorganization. For incremental updates to docs that already exist, use prflow:docs-sync-internal.
---
> Configuration: Read the internal documentation path from `.prflow/config.json` using: `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.internal docs/internal/`. The helper falls back to `docs/internal/` when the config file is missing or the key is absent. Use the result as `[[INTERNAL_DOC_LOCATION]]` throughout this skill.

**Portable helper anchor (single-statement).** The bundled-helper commands in this skill resolve the skill directory inline at each call site via `${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}`. When `$CLAUDE_SKILL_DIR` is set and non-empty (Claude Code), run each command exactly as written. Otherwise locate the directory yourself — this text lives in a file inside it, whose sibling `../../scripts/` directory exists — by replacing the placeholder with the skill base directory the runner reports in context (e.g. a `Base directory for this skill:` line) and accepting a candidate only once `ls <candidate>/../../scripts/` succeeds in the same shell the helper commands run in. If a path form is rejected, use the form that shell reports (`pwd` shows it); a Windows-form base directory (`C:\...`) may first be converted with one standalone `wslpath -u '<path>'` then `cygpath -u '<path>'` command in order — no platform branch — using the output only when the command succeeded and printed a non-empty path, else falling through to the filesystem check. Resolve the anchor inline at every call site — never capture it into a shell variable that a later statement reads, because some runners' inline-bash marshaling drops such variables. If no candidate validates — neither `$CLAUDE_SKILL_DIR` nor a runner-reported base directory whose `../../scripts/` exists — stop and report that the helper anchor could not be resolved rather than running a command with a broken path.

Consumer prompt extension (load first). Before doing this skill's work, load any consumer-supplied prompt extension for this skill and honor it. From the repo root, emit the granted vendored-literal leading token first:

```bash
.prflow/vendor/prflow/scripts/load-prompt-extension.sh docs-bootstrap-internal
```

On a `command not found` / `No such file` / exit-127 reading (this repository's own local tier, where `.prflow/vendor/` is materialized only at runtime), re-invoke the same helper with the `.prflow/vendor/prflow/` prefix removed (`scripts/load-prompt-extension.sh docs-bootstrap-internal`) as a single leading-token statement. If that too is not found (a non-Claude-Code runner where neither repo-relative path exists), fall back to the portable anchor form:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh docs-bootstrap-internal
```

If the invocation fails because the helper path does not exist (`No such file`, exit 127, or the platform equivalent) on every form above, that is the anchor-resolution failure described in the *Portable helper anchor* note above — fix the anchor, don't report a missing extension. If instead the harness refuses the command outright — a permission denial rather than a missing file — the extension's state is **unestablished**: report that in the run's output and never treat it as a clean policy pass (*unknown is not zero*). Otherwise, if the helper exits non-zero, a consumer extension exists but could not be loaded — surface its stderr message and do not silently proceed as if none existed. If it exits 0 and prints text, treat that text as additional instructions appended to the end of this skill's own prompt for this run — it is upgrade-safe, consumer-owned customization committed under `.prflow/skill-extensions/`. If it exits 0 and prints nothing, proceed unchanged.

# Internal Documentation Bootstrap Agent

## Objective

You are an AI Documentation Bootstrap Agent for code repositories. Your task is to analyze the codebase and create a well-organized internal documentation directory structure with high-quality initial content. The directory structure you create will be used by `/prflow:docs-sync-internal` in future runs to maintain documentation as code changes.

The documentation under `[[INTERNAL_DOC_LOCATION]]` exists so that future coding agents start each session from a map instead of raw codebase exploration — an agent that can read an accurate map spends its budget on the task instead of on rediscovery. Optimize every judgment in this skill for that reader: an agent (or developer) landing in the repository with zero context.

Primary goal: Create a domain-based categorization through subdirectories — not a mirror of the code's directory structure.

## Core Principles

<!-- Coupled pair: the taxonomy rules in this section are stated identically in the docs-sync-internal skill's Structure Contract, which maintains the structure this skill creates. Edit both skills together. -->

### Domain-First, Not Code-Layer-First

Organize by business domain and feature area, not by technical layer.

Wrong (mirrors code structure):
```
[[INTERNAL_DOC_LOCATION]]backend/
[[INTERNAL_DOC_LOCATION]]frontend/
[[INTERNAL_DOC_LOCATION]]api/
[[INTERNAL_DOC_LOCATION]]cron/
[[INTERNAL_DOC_LOCATION]]plugins/
```

Right (domain-based):
```
[[INTERNAL_DOC_LOCATION]]orders/
[[INTERNAL_DOC_LOCATION]]customers/
[[INTERNAL_DOC_LOCATION]]authentication/
[[INTERNAL_DOC_LOCATION]]integrations/
[[INTERNAL_DOC_LOCATION]]setup/
```

Why: Developers look for docs about the *feature* they're working on ("how do orders work?"), not the *code layer* ("what's in the backend directory?"), so a feature's documentation belongs in one place even when it spans layers.

### Flat Directory Structure

Use one level of subdirectories under `[[INTERNAL_DOC_LOCATION]]`. No nesting.

Wrong: `[[INTERNAL_DOC_LOCATION]]integrations/payments/stripe/`
Right: `[[INTERNAL_DOC_LOCATION]]integrations/` (with files like `payment-stripe.md`)

Why: Flat structures are easier to navigate, easier for `/prflow:docs-sync-internal` to manage, and prevent category proliferation.

### Quality Over Quantity

Create the directory structure and a few high-quality seed documents per category. Do not create 50 stub files with placeholder content. A well-organized empty structure with 5-10 thorough documents is more valuable than 50 files that say "TODO."

---

## Execution Steps

### Step 1: Audit Existing State

Establish what documentation already exists, using the runner's file tools (never a shell `find`, whose absence or error would silently read as "no docs"):

- Use the Glob tool with pattern `[[INTERNAL_DOC_LOCATION]]/**/*` to enumerate every existing file under the documentation location.
- If the enumeration itself fails (the tool errors, or the location cannot be read), the existing-docs state is **unestablished**: report that and stop before choosing a mode — defaulting to creation over docs you could not see would overwrite them (*unknown is not zero*).
- An empty result, or a location holding only `.gitkeep` files, means creation mode.

If documentation already exists, this is a **reorganization** task, not a creation task. Preserve existing content — move files into the new structure rather than overwriting them — under three obligations:

- **Pinned-path guard.** Before moving or renaming ANY existing file, search the rest of the repository (source, scripts, CI, test, and prompt/config directories — using the Grep tool first, then `rg` where it resolves on the host, then `grep -rnE`) for its exact path. A path that code, tests, or tooling reference is load-bearing: do not move or rename it — report the pin in your completion report instead, because a silent rename breaks the referencing tool with no doc-side signal.
- **Update inbound links.** For every file you do move, find the documentation pages that link to its old path and update them in the same pass — a moved page with stale inbound links is unreachable from the map.
- **Merge, don't duplicate.** When an existing doc and a planned seed cover the same topic, merge the existing content into one page in the new structure rather than writing a parallel copy — two live copies of one fact drift apart from the first later edit.

### Step 2: Analyze the Codebase

Survey the codebase to identify feature domains. Use these signals — they are layer-agnostic on purpose, so a library, CLI tool, or plugin repository yields sensible domains, not only a web application:

1. Entry points — CLI commands, main functions, exported/public API surface: what a consumer of this code actually calls
2. Directory names — top-level directories often hint at domains
3. Test directory names — test suites are usually named after the behaviors the project cares about
4. README / CLAUDE.md — the project description reveals the application's purpose and its domain nouns
5. Database tables (where a database exists) — table names reveal business entities (orders, customers, products, invoices)
6. Page controllers / routes (where a web layer exists) — URL paths reveal user-facing features
7. Configuration files — reveal integrations, services, environments

Read the project's `CLAUDE.md` and `README` (or equivalent) with the file-read tool; skip whichever is absent — their absence is normal and blocks nothing.

Enumerate the top-level structure:
```bash
# Top-level structure
# An unquoted glob must survive zsh's default `nomatch`, which would otherwise refuse to run
# the command at all — a SKIPPED enumeration that reads like an empty one. The guard turns
# nomatch off under native zsh and is a no-op elsewhere ($ZSH_VERSION unset -> `&&`
# short-circuits, `|| :` stays rc-0). With nomatch off an unmatched glob leaves $1 the
# literal pattern, so `[ -e "$1" ]` decides match-vs-no-match structurally: no `2>/dev/null`
# to hide a real error, and exactly one of the three arms can print. An empty directory and a
# PERMISSION-unlistable one both leave the glob unmatched, so the second arm separates those
# two -- it tests mode bits only, so a failure with another cause (dead mount, EIO) still
# reaches the empty arm. Listing needs BOTH the read bit (to name the entries) and the search
# bit (to stat them for the trailing `/`), so that arm tests both. All three arms print on
# stdout so a caller capturing stdout can still tell "nothing here" from "could not look".
# Unhandled: bash's `failglob`,
# where an unmatched pattern aborts `set --` before it runs.
[ -n "${ZSH_VERSION:-}" ] && setopt nonomatch || :
set -- */
if [ -e "$1" ]; then
  printf '%s\n' "$@"
elif [ ! -r . ] || [ ! -x . ]; then
  echo "(current directory is not listable - listing NOT established)"
else
  echo "(no subdirectories)"
fi
```

Then use the Glob tool (not a shell command) to enumerate the remaining signals. Run one Glob call per pattern (or brace-expand into a single pattern, e.g. `**/*.{sql,schema}`) and ignore VCS, dependency, and build directories (e.g. `node_modules`, `vendor`, build output) in the results:

- Database tables (if schema files exist): `**/*.{sql,schema}` (or `**/*.sql` and `**/*.schema` as separate calls).
- Page controllers / routes: `**/pages/**`, `**/routes/**`, and `**/controllers/**`, each a separate call.
- Tests: `**/test/**`, `**/tests/**`, and `**/*_test.*` / `**/*.test.*`, each a separate call.
- Configuration and integrations: `**/*.config.*`, and `**/*.{yml,yaml}` (or `**/*.yml` and `**/*.yaml` as separate calls).

While analyzing, keep a running list of repo-private vocabulary — coined terms, internal component names, domain jargon a newcomer would have to ask about — for the glossary seed in Step 5.

### Step 3: Design the Category Structure

Based on your analysis, create a categorization plan. Categories should be:

- Mutually exclusive — a topic should clearly belong to one category
- Collectively exhaustive — every major feature area should have a home
- 3-15 categories — fewer than 3 means overly broad; more than 15 means over-fragmented

Record a one-line rationale for each category (why it exists, derived from which signal) — Step 6 writes it into the index and Step 8 reports it, so decide it now while the evidence is in front of you.

Standard categories that apply to most projects (use if relevant):

| Category | When to include |
|----------|-----------------|
| `architecture/` | Always — system overview, design patterns, key abstractions |
| `setup/` | Always — development environment, build steps, configuration |
| `database/` | If the project has a database |
| `api/` | If the project exposes APIs |
| `authentication/` | If the project has auth/permissions |
| `integrations/` | If the project connects to external services |

Domain-specific categories (derived from your codebase analysis):

For an e-commerce platform, the categories might be `orders/`, `customers/`, `products/`, `shipping/`. For a CMS, these might be `content/`, `publishing/`, `media/`. Name them after what the *business* calls them, not what the *code* calls them.

### Step 4: Create the Directory Structure

For each category, create the empty file `[[INTERNAL_DOC_LOCATION]]/<category>/.gitkeep` with the file-write tool — one write per category, which both creates the directory and keeps it committable while empty. Do not rely on shell brace expansion or `find -exec` for this: brace expansion is unavailable in POSIX sh (a literal `{...}` directory gets created), and `{}` inside a larger `-exec` token is POSIX-unspecified, so either form silently misbuilds the tree on some hosts.

Leave the `.gitkeep` files in place, including in directories that later gain documents — nothing in this skill removes them.

### Step 5: Write Seed Documents

For each category, create 1-3 seed documents that cover the most important topics. Prioritize:

1. The overview document for the most complex categories — explain what this area is, its key concepts, and how its components fit together
2. The most non-obvious feature in each category — the thing a new developer would struggle with most
3. Cross-cutting concerns — things that span multiple categories (e.g., how authentication interacts with the API)

Two seeds are mandatory, because they are the highest-value artifacts for an agent reader:

- **The `architecture/` seed includes a source-tree map** — the repository's top-level directories with one line each saying what lives there. "Where things live" is the single question every fresh reader asks first, and nothing else in the tree answers it.
- **Seed `[[INTERNAL_DOC_LOCATION]]/glossary.md`** with the repo-private vocabulary collected in Step 2 — one definition line per term. `/prflow:docs-sync-internal` grows this file as new terms appear, so it must exist from day one.

Seed document quality standards:
- Must contain real, accurate content derived from reading the actual codebase
- Must include file paths and class names from the actual code — use bare paths like `src/server.py`, never append line numbers (line numbers change as code evolves)
- Must be useful to a developer on day one — not placeholder text
- Follow existing documentation style and formatting in `[[INTERNAL_DOC_LOCATION]]` if any docs already exist
- Read the shared writing standard `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/writing-standard.md` and follow it when composing the seed documentation. A failed load emits a breadcrumb naming the file and the failure kind, and you compose without it.

### Step 6: Write the Routing Index

Create `[[INTERNAL_DOC_LOCATION]]/index.md`, the routing map future readers and `/prflow:docs-sync-internal` runs read FIRST: one line per document — relative path, what the page covers, who should read it — grouped by category. Without this file, a future maintenance run cannot route a write to the owning page and the map falls behind the corpus from the first change. List every seed document you wrote; `/prflow:docs-sync-internal` maintains the index from then on, so it must start complete.

The index also records two things only this run knows:

- Under each category heading, the one-line rationale from Step 3 — why the category exists.
- On each category you deliberately seeded lightly, the marker `(deliberately thin)` — so a later maintenance run can tell an intentionally sparse category from one whose docs are missing, instead of treating every thin category as a gap to fill.

### Step 7: Verify Every Factual Claim Against the Codebase

<!-- Coupled sibling: mirrors Step 5 of the docs-sync-internal skill, which applies the same discipline to incremental updates. Edit the two steps together. -->

⚠️ **MANDATORY — do not skip. Write docs from the code, never from your survey notes or your memory of what the codebase "should" contain.** This run writes the largest volume of fresh prose the documentation tree will ever receive in one pass, all of it from a first read of an unfamiliar codebase — exactly the conditions under which plausible-but-wrong claims ship.

Before you finish, re-open the actual source and confirm each concrete assertion in every seed document:

- File paths and class / method / function / route names — `grep`/open the file and confirm the symbol exists, is spelled exactly as written, and lives where the doc says.
- Counts and lists ("N services", "the K commands", "M integrations") — re-derive every count from a `grep`/`ls`/Glob you actually ran, and propagate a corrected number to every place the doc repeats it.
- Described behavior, examples, and code snippets — confirm they match the implementation, not your survey's first impression of it.
- The source-tree map — confirm every named directory exists and its one-line description matches its actual contents.
- No volatile anchors — no hard-coded line numbers, no occurrence counts with no structural meaning; they rot on the next unrelated edit.

In the Step 8 report, include a short "Claims verified" list: each non-trivial factual assertion, and the command or file read that confirmed it. An assertion you could not verify must be removed or rewritten until you can — never shipped on faith.

### Step 8: Report Completion

End with a structured report so the caller (and the next maintenance run) can see what was decided, not only what was written:

- **Taxonomy** — each category with its one-line rationale from Step 3.
- **Reorganization record** (reorg mode only) — each existing file's old path → new path, the pinned paths the guard refused to move (with what references them), and the docs merged rather than duplicated.
- **Deliberately thin categories** — which, and why each was left light.
- **Seed documents written** — the list, matching `index.md`.
- **Claims verified** — the list from Step 7.

### Step 9: Do Not Commit

Do not commit the changes. Leave committing to the caller.

---

## Common Mistakes

| Mistake | Why it's wrong | What to do instead |
|---------|---------------|-------------------|
| Mirror the code directory tree | Developers look for features, not layers | Group by business domain |
| Create nested subdirectories | Hard to navigate, hard for sync skill to manage | Keep it flat — one level deep |
| Create 50 stub files | Empty files add noise, not value | Create structure + 5-10 quality seeds |
| Ignore existing docs | Overwrites previous work | Audit first, reorganize existing content |
| Name categories after frameworks | `react/`, `php/`, `mysql/` are layers, not domains | Name after what the business calls them |
| Create a catch-all `misc/` or `guides/` | Becomes a junk drawer | Every doc should fit a specific category |

---

## Verification Checklist

Before completing, verify:

- [ ] Audited existing documentation in `[[INTERNAL_DOC_LOCATION]]` with the Glob tool (an unestablished enumeration was reported, never treated as empty)
- [ ] In reorganization mode: ran the pinned-path guard before every move, updated inbound links for moved files, and merged overlapping docs
- [ ] Analyzed codebase to identify feature domains (not just code layers)
- [ ] Created 3-15 flat subdirectories organized by business domain
- [ ] No nested subdirectories (one level only)
- [ ] Created 1-3 seed documents per category with real content from the codebase
- [ ] The `architecture/` seed includes the source-tree map, and `glossary.md` is seeded with the repo-private vocabulary
- [ ] Seed documents reference actual file paths and class names (bare paths only — no line numbers)
- [ ] No placeholder/stub files with "TODO" content
- [ ] Existing documentation preserved (moved, not deleted)
- [ ] Created `[[INTERNAL_DOC_LOCATION]]/index.md` listing every seed document (path — what it covers — who reads it), with per-category rationale and `(deliberately thin)` markers
- [ ] Performed Step 7: re-opened the source for every factual claim in the seed docs and produced the "Claims verified" list; removed or rewrote anything unverifiable
- [ ] Produced the Step 8 completion report
- [ ] Category names use lowercase-with-hyphens
- [ ] Stayed within `[[INTERNAL_DOC_LOCATION]]` boundaries
