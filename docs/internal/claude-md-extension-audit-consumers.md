# CLAUDE.md / prompt-extension machine-reader enumeration (issue #1352 AC3)

This is the **AC3 consumer enumeration** for issue #1352: an exhaustive, verified inventory of every
MACHINE reader (`.py`, `.sh`, `.jq`, `.yml`) that depends on a heading, marker comment, or distinctive
literal in `CLAUDE.md` and the `.prflow/prompt-extensions/*.md` surfaces likely to be moved, compressed,
renamed, or split by this audit. Each consumer below records the exact literal/heading it reads, the
named symbol or assertion that reads it, and the failure mode if the audit changes that surface without
updating the reader in the same commit — classified as **silent truncation** (a reader that quietly extracts the wrong
or empty content), **loud pin failure** (a suite assertion that turns RED at the desk / CI), or
**proximity** (a section/heading-relative rule that breaks when a paragraph crosses a heading boundary).
Both suite pins and non-pin runtime readers are covered, and `lib/test/modules/*.sh` is swept alongside
`lib/test/run.sh`. All named consumers were confirmed to still exist as of this writing.

---

## 1. `scripts/render-audit-prompt.py` — heading + `dim-key` section extractor (runtime, non-pin)

Reads `.prflow/prompt-extensions/create-issue.md` by **literal heading**. This is the authoritative
owner of the heading-extraction rule (per `skills/create-issue/references/step-2-clarify.md`).

- `scripts/render-audit-prompt.py`, module constant `_HOOKS = {"audit-dimensions": "## Audit dimensions", "evidence-axes": "## Evidence axes"}`. These two exact heading strings are the extraction keys.
- `scripts/render-audit-prompt.py`, module constant `_DIM_KEY_TOKEN = "dim-key:"`; the `<!-- dim-key: <lowercase-kebab> -->` declaration markers pair each `## Audit dimensions` bullet with a stable key, parsed by the dim-key scan in the same module.
- Section-span rule (implemented by `render-audit-prompt.py`'s heading-section extraction helpers and their callers): a section spans its heading line to the **next line beginning `## `** (two hashes + space), else to EOF; an inserted `## ` heading therefore **truncates** the section.

**Failure mode: silent truncation.** Renaming/rewording either heading makes `_HOOKS` extract nothing (empty section == absent heading), so the auditor prompt is rendered without the consumer dimensions/axes. Inserting a new `## ` heading mid-section silently cuts the section short. Moving a `dim-key` marker away from the bullet it declares raises `RenderError` (loud) or misbinds the key. `### ` sub-headings do NOT terminate — only `## `.

## 2. `scripts/load-prompt-extension.sh --section` — independent second extractor (runtime, non-pin) + its module

A sibling `--section` implementation invoked at runtime by the create-issue skill against `## Evidence axes`.

- `scripts/load-prompt-extension.sh` — the `--section '<## heading>'` flag (its usage banner, argument parser, and section-extraction branch); matching is EXACT on the full heading line (so `## Evidence axes <!-- note -->` is selected by the full line, not the bare heading). Reads `.prflow/prompt-extensions/create-issue.md`.
- `skills/create-issue/references/step-2-clarify.md` — runtime invocation: `load-prompt-extension.sh create-issue --section '## Evidence axes'`, re-run fresh at Step 2 forwarding and at each bundle-coverage gate site. Step 3.6 consumes `## Audit dimensions` via the renderer's splice.
- `lib/test/modules/prompt-extension-reader.sh`, its dual-hook block over the live `create-issue` extension — drives the live `create-issue` extension through BOTH hooks (`## Audit dimensions`, `## Evidence axes`) and asserts each extracts non-empty AND that **neither hook leaks the other's section** (the dual-hook independence contract).

**Failure mode: silent truncation** at runtime (absent-heading breadcrumb → treated as "no consumer section"); **loud pin failure** in `prompt-extension-reader.sh` if a heading is renamed (extraction goes empty → the non-empty assertion fails) or if a section boundary is broken so one hook captures the other's heading (the cross-leak assertion fails).

## 3. `lib/test/run.sh` `#506` / `#719` block — byte-identity, three-file lockstep, absence sweeps (suite pins)

The `#506` / `#719` prompt-surface block in `lib/test/run.sh`. Surface vars: `WSR_IMPL=implement.md`, `WSR_RAF=review-and-fix.md`, `WSR_REV=review.md`, `WSR_CLAUDE=CLAUDE.md`.

- **Byte-identity** (the `#730`/`#506` routing-gate byte-identity extract): the entire `## Prompt-surface edit routing evidence gate` section (heading → EOF) of `review-and-fix.md` must be **byte-identical** to that of `review.md`. The heading is pinned present-and-unique first so the equality can't pass vacuously on two empty extracts.
- **Operative-sentence pins**: implement.md `'the orchestrator dispatches a context-isolated Agent-tool subagent whose prompt instructs'`; review-and-fix.md + review.md both `'the review reports a **FAIL** finding naming'`; CLAUDE.md `'Autonomous \`/devflow:implement\` runs satisfy this mandate differently'` (assertion `#506 CLAUDE.md carries the autonomous-run routing sentence`).
- **Three-file lockstep literals** (assertions `#506 trigger-glob list is identical across all three extensions (lockstep)` and `#506 Writing-skills evidence marker is present in the contract and both gate copies (lockstep)`): `WSR_TGL` trigger-glob list (`` `skills/*/SKILL.md`, `skills/implement/phases/*.md`, `skills/implement/references/*.md`, `skills/review/phases/*.md`, `skills/review-and-fix/references/*.md`, `.prflow/prompt-extensions/*.md` ``) must be identical across implement/review-and-fix/review; `WSR_MARK='Writing-skills evidence:'` must be present in implement.md's contract and both review gate copies.
- **Zero-occurrence ABSENCE sweeps** — the `_WSR_RETIRED_LITS[]` array (retired-convention phrases e.g. `'A focused result discharges no gate'`, `'A focused result is never a completion gate.'`, `'Before a commit, phase completion, push, or'`, …) swept to 0 hits across implement.md, review-and-fix.md, **receiving-code-review.md**, CLAUDE.md, `docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md`, CONTRIBUTING.md (the `_WSR_RETIRED_LITS` sweep loop); plus the `#719` undefined-disjunct sweeps: `'module or path'` == 0 in implement.md/review-and-fix.md/receiving-code-review.md/overview, `'focused path'` == 0 in CONTRIBUTING.md. `#719` also carries a per-member baseline-corpus control against blob ref `607ec800`.

**Failure mode: loud pin failure.** Renaming the gate heading breaks the heading pin and empties the byte-identity extract; letting the two review copies diverge breaks byte-identity; editing the trigger-glob list or evidence marker in only some of the three files breaks lockstep; re-introducing any retired phrase anywhere in the six-file set turns the sweep RED.

## 4. `lib/test/lint-subagent-extension-handoff.py` — section-proximity rule (suite lint)

Splits a file into sections at markdown headings (`#`..`######`), each section owning only its **own** lines (heading through the next heading of ANY level — a nested subsection is a separate section). A section is a candidate when it contains BOTH a dispatch token AND a skill reference **in the same section** (`lint-subagent-extension-handoff.py`'s section splitter and candidacy scan).

- `declared_non_dispatch` registry is **keyed per `(dispatcher-path, section-heading)`** (the lint's registry loader); a stale entry (naming a section the scan no longer flags) is itself a failure.
- Registry file `lib/subagent-dispatch-sites.json`: `schema_version:1`, a `sites[]` array (dispatcher/skill/handoff), and `"declared_non_dispatch": []` (currently empty).

**Failure mode: proximity.** Moving a paragraph across a heading boundary re-scopes which section owns the token/reference conjunction — a token and reference that were co-located can split into two sections (or two that were split can merge), changing candidacy. A `declared_non_dispatch` waiver keyed on a heading breaks the instant that heading is renamed or the paragraph moves out from under it.

## 5. `lib/test/modules/create-issue-contract.sh` — hardcoded bullet-count assertions (suite pins)

Counts `^- **`-shaped bullets within a heading-delimited section of `create-issue.md` (`CI_EXT`) via `awk '/^## Heading/{f=1;next} /^## /{f=0} f' | grep -c '^- \*\*'`:

- Assertion `#467 D3 (re-scoped by #548): create-issue extension ## Audit dimensions section is 9 dimension bullets` — `## Audit dimensions` section == **9** dimension bullets.
- Assertion `#548 Evidence-axes: create-issue extension ## Evidence axes section is 6 axis bullets` — `## Evidence axes` section == **6** axis bullets.
- Related template count (`CI_TMPL_AUDIT`), assertion `#467 A3: Step 3.6 generic dimension checklist is guard-locked at its sanctioned bullet count` — `**Audit dimensions` → `{CONSUMER_DIMENSIONS}` range == **10** bullets, with the two `#467 A3` START/END line-anchor assertions and the `#467 A3` END-anchor presence pin beside it.
- Heading-presence pin `#443: live create-issue extension carries the exact ## Audit dimensions heading` — `'## Audit dimensions'` present-and-unique in `CI_EXT`.

**Failure mode: loud pin failure.** Adding/removing a dimension or axis bullet without updating the count literal turns the suite RED; renaming a heading empties the `awk` range (count → 0) and fails; inserting a stray `## ` heading inside the section truncates the count.

## 6. All CLAUDE.md / review-and-fix.md pin calls across `run.sh` AND `lib/test/modules/*.sh`

CLAUDE.md is reached via `$LIB/../CLAUDE.md`, `$WSR_CLAUDE`, `$E711_CLAUDE`, and (in modules) `$CI_CLAUDE = $CI_ROOT/CLAUDE.md`. Each pin below is an exact literal that must survive verbatim in CLAUDE.md.

`lib/test/run.sh`:
- The `#312` six-shape-set assertion on the CLAUDE.md matrix gotcha (its item-4 leg) — `$SIXSHAPE_SET` (six-shape valid-falsy matrix set) present in CLAUDE.md's best-effort-parser gotcha.
- `#366: CLAUDE.md carve-out bullet mirrors the SKILL rule (coupled half)` — `'is made **directly by the orchestrator**, citing this carve-out and recording it in the workpad, **never** by invoking'`.
- `#366: CLAUDE.md carve-out bullet carries the same AC4 widening arm (coupled)` — `'whether by a Phase-3 review finding **or by the issue'`.
- `#506 CLAUDE.md carries the autonomous-run routing sentence` — `'Autonomous \`/devflow:implement\` runs satisfy this mandate differently'` (via `$WSR_CLAUDE`).
- The `#142` pair asserting that CLAUDE.md references the EXTERNAL `writing-skills` authoring convention and does NOT claim a vendored first-party one — `$SP_PAT_WRI_DEV` present AND `'devflow:writing-skills'` absent in CLAUDE.md. (Both assertion names spell the external namespaced id verbatim; it is not quoted here because the `#142` bare-namespaced-id sweep does not except `docs/internal/`.)
- `#711 CLAUDE.md carries the enumeration-source rule` — `'sources its population from an index-reading \`git ls-files\`'` (via `$E711_CLAUDE`; carries `# structural-pin-ok: helper-contract`).

`lib/test/modules/capability-profiles.sh` (targets `$LIB/../CLAUDE.md`):
- `#555 CLAUDE.md documents the implement-tier bundled-helper grant flow` — `'Implement-tier bundled-helper grant flow (issue #555)'`.
- `#555 CLAUDE.md forbids hand-editing either generated workflow literal for such a grant` — `'**Never hand-edit either workflow literal** to add such a grant.'`.

(The former `lib/test/modules/create-issue-contract.sh` CLAUDE.md pins — the `#467 D2` best-effort-parser-widening leg and the `#593` grant-timing-rule leg — were retired by the issue #1759 residual-prose sweep, so no create-issue pin now asserts CLAUDE.md content; the operative CLAUDE.md sentences themselves are unchanged.)

`lib/test/modules/review-and-fix-contract.sh` — module-private `_raf_pin_unique` wrapper pins against `RAF_EXTENSION = .prflow/prompt-extensions/review-and-fix.md`:
- `raf extension: explicit local focused selection` — `'lib/test/run-module.sh review-and-fix-contract'`.
- `raf extension: focused selection never auto-routes files` — `'automate changed-file-to-module routing'`.
- `raf extension: skips cannot certify a clean run` — `'A nonempty skip tally is not clean.'`.
  (The same wrapper also pins `RAF_SKILL`, `RAF_REVIEW_BUNDLE`, `RAF_RECEIVING_SKILL`, and the overview page; those are review-engine surfaces, not the extension.)

**Failure mode: loud pin failure.** Rewording, moving between files, or renaming any pinned CLAUDE.md / review-and-fix.md literal turns the required `lib + python tests` check RED. Note `assert_pin_unique` also fails if the literal becomes **non-unique** (appears twice), so duplicating a sentence during a "split" also breaks it.

## 7. Trusted prompt-extension materialization + dispatch-namespace guards (workflow + suite)

- `scripts/materialize-trusted-prompt-extensions.sh` — populates the review tier's trusted prompt-extension closure from the base ref; reads `.prflow/prompt-extensions/${name}.md` in its per-name materialization loop for each protected NAME. It reads the extension **files by name**, not their headings.
- `DEVFLOW_PROTECTED_PROMPT_EXTENSIONS` job env:
  - `.github/workflows/devflow-runner.yml`, `run` job env — `"review requesting-code-review"` (consumed by its `baseprovision` materialize step and the reviewer step's extension load).
  - `.github/workflows/devflow.yml`, `command` job env — `"pr-description receiving-code-review requesting-code-review review review-and-fix"` (consumed by that job's materialize step).
- Two `run.sh` drift guards assert the declared protected set equals the extension names actually loaded via `load-prompt-extension.sh <name>` from the dispatched skill trees:
  - `lib/test/run.sh`, the `#874` protected-set drift guard — devflow-runner.yml `run` job set vs names reachable from `skills/review/`.
  - `lib/test/run.sh`, the `#1075` protected-set drift guard — devflow.yml `command` job set vs names from `skills/review`, `skills/review-and-fix`, `skills/pr-description`. Regex: `^(?:"[^"]*"|\S)*?/load-prompt-extension\.sh\s+([A-Za-z0-9][A-Za-z0-9._-]*)`.
- `lib/test/lint-subagent-dispatch-namespace.py` — audits `.prflow/prompt-extensions/*.md` (module constant `_EXTENSION_RE`) for `<namespace>:<leaf>` subagent references, failing when a dispatchable leaf carries a non-canonical namespace (its namespace-validation branch).

**Failure mode: mixed.** **Renaming a prompt-extension FILE** (e.g. splitting `review.md`) without updating `DEVFLOW_PROTECTED_PROMPT_EXTENSIONS` and the skill's `load-prompt-extension.sh <name>` call: the materializer silently produces no file for the renamed name (`::warning::`, reviewer runs with no extension text — **silent-ish at runtime**), and the #874/#1075 drift guards turn **RED** at the desk if the declared set and the loaded names diverge. Renaming the plugin namespace inside an extension without sweeping references is caught **loud** by `lint-subagent-dispatch-namespace.py`.

---

### Enumeration gap this audit shipped with, and how it surfaced

This inventory swept `lib/test/run.sh` and three named modules. The issue's Implementation Notes
directed a sweep of the **whole** `lib/test/modules/` directory, and
`lib/test/modules/regenerate-artifacts.sh` was never opened — so its `#655`/`#1055` population,
which pins the two generated-artifact sections per extension, is absent from the consumer list
below. CI caught the resulting 13 module failures plus 5 `run.sh` pin failures; the rules were
restored and recorded as permitted exception **P9** in the duplicate list. Treat the numbered
consumers below as the verified set, not as the complete one.

### Post-edit disposition, consumer by consumer (AC3's second limb)

For each consumer above, whether its dependency **survives unchanged** under the #1352 placement edits
or what same-commit change accompanied it.

1. **`render-audit-prompt.py` heading + `dim-key` extractor — SURVIVES UNCHANGED.** No `## ` heading
   was renamed, none was inserted inside either hooked section, and no `dim-key` marker moved. The
   three non-exempt `create-issue.md` sections that were compressed all precede `## Audit dimensions`.
   Verified by extracting both sections from the pre-edit blob and the edited file and comparing:
   `## Audit dimensions` 9,470 B identical, `## Evidence axes` 4,571 B identical.
2. **`load-prompt-extension.sh --section` and `prompt-extension-reader.sh` — SURVIVES UNCHANGED.** Both
   hooks were run against the edited file; the extractions are non-empty and neither leaks the other's
   section, and the `## Evidence axes` body hashes to the same bytes as before the edit.
3. **`run.sh`'s `#506`/`#719` block — SURVIVES, with the gate text rewritten in lockstep.** The
   `## Prompt-surface edit routing evidence gate` heading is unchanged in both review extensions; the
   compressed gate-plus-advisory tail was authored once and spliced into `review.md` and
   `review-and-fix.md` from the same source, so the heading→EOF byte-identity extract still compares
   equal. The trigger-glob list literal and the `Writing-skills evidence:` marker are unchanged across
   the lockstep set the `#506` block reads, the operative-sentence pins resolve, and every
   `_WSR_RETIRED_LITS` sweep and the
   `module or path` / `focused path` zero-occurrence sweeps still read 0 across the six-file set.
   Two wrapped-literal near-misses were caught and fixed during the pass — `pin_count` is line-based,
   so re-wrapping `Cloud-tier runs use …` and `the review reports a **FAIL** finding naming` across a
   line break would have read as absent; both were restored to a single line.
4. **`lint-subagent-extension-handoff.py` section-proximity rule — SURVIVES UNCHANGED.** Sections were
   removed and compressed but no skill reference was moved next to a dispatch token; the lint was run
   against the edited tree and audited 5 of 5 records clean, and `lib/subagent-dispatch-sites.json`
   needed no `declared_non_dispatch` entry.
5. **`create-issue-contract.sh` bullet-count assertions — SURVIVE UNCHANGED, and are untouched.** Both
   counted sections are AC6-exempt and byte-identical to their pre-edit bytes, so neither the 9 nor the
   6 literal was edited — which AC8 names as the signal that the exemption held.
6. **The `CLAUDE.md` and `review-and-fix.md` pin populations — SURVIVE UNCHANGED.** Every pinned literal
   reached through `$LIB/../CLAUDE.md`, `$WSR_CLAUDE`, `$E711_CLAUDE`, `$CI_CLAUDE` and
   `review-and-fix-contract.sh`'s `_raf_pin_unique` was re-verified present **and unique** after each
   splice, using a line-based count that mirrors `pin_count`'s `grep -oF` semantics. `assert_pin_unique`
   fails on duplication as well as absence, and a compression pass that de-duplicates prose is exactly
   the shape that can break a uniqueness pin, so the check was re-run after every edit rather than once
   at the end.
7. **Trusted materialization and the dispatch-namespace guards — SURVIVE UNCHANGED.** No extension file
   was added, removed, or renamed, so `DEVFLOW_PROTECTED_PROMPT_EXTENSIONS` and both `run.sh` drift
   guards are untouched; `lint-subagent-dispatch-namespace.py` was run against the edited tree and
   audited 62 prompt surfaces clean.

One consumer outside this list was affected and reconciled in the same change:
`run.sh`'s `#376 AC8` assertion **name** claimed the implement extension's preflight enumeration was
pinned "by w2-preflight-set-coupling below". That pin was retired, so the name was reworded to say the
assertion covers the `lib/preflight.sh` header alone — the same-commit reconciliation for removing the
extension's matching (and equally stale) claim.

### Cross-cutting audit cautions

- The two `## Audit dimensions` / `## Evidence axes` headings in `create-issue.md` are read by **four** independent machine consumers (render-audit-prompt `_HOOKS`, load-prompt-extension `--section`, prompt-extension-reader module, create-issue-contract bullet counts) — renaming either heading breaks all four, some silently (extractors) and some loudly (counts).
- The `## Prompt-surface edit routing evidence gate` heading anchors a **byte-identity** extract across two files; any edit must be applied identically to review.md and review-and-fix.md in the same commit.
- CLAUDE.md pins use `assert_pin_unique`, which is sensitive to both **absence** and **duplication** of the pinned sentence — a compression pass that de-duplicates prose can break a uniqueness pin.
