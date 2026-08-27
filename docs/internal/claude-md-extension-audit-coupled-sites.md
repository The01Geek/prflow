# CLAUDE.md ⇄ prompt-extension coupled-site enumeration (issue #1352 AC2)

This is the durable AC2 artifact for the repo audit in issue #1352: a precise enumeration of every
**coupled site** — text or value that more than one file must carry identically or in lockstep —
whose partner set includes `CLAUDE.md` or a live prompt extension under
`.prflow/prompt-extensions/*.md` (the live extensions are `implement.md`, `review-and-fix.md`,
`receiving-code-review.md`, `create-issue.md`, `review.md`, `docs-bootstrap-external.md`,
`docs-sync-external.md`, `docs-sync-internal.md`, `pr-description.md`). It is built from three
inputs, none complete on its own: (1) the coupled-site registry emitted by
`lib/test/regenerate-artifacts.py --list` — which lists extensions under their **pre-rename**
`.devflow/prompt-extensions/` spelling, reconciled here to `.prflow/`; (2) a prose search over
`CLAUDE.md` and the extensions for self-declared couplings ("coupled pair/mirror/copy/sibling",
"edited together", "in lockstep", "same-commit", "byte-identical", …); (3) a whitespace-normalized
tree search for each contract sentence's mirror half. Column (d) records whether **any** mirror half
sits under `skills/` (the vendor-shipped surface), because those couplings have the widest blast
radius. This artifact gates every later move in the audit — treat it as the working index, not a
summary.

## A. Registry-derived coupling (from `regenerate-artifacts.py --list`)

Only one `coupled-site` registry row has an extension or `CLAUDE.md` partner.

| # | Name | CLAUDE.md / extension location | Mirror half file(s) & location | skills/ mirror? | Enforcing test/pin |
|---|------|--------------------------------|--------------------------------|-----------------|--------------------|
| A1 | `wsr-swept-relpaths` (frozen old paths) | Partner set includes `CLAUDE.md` (Gotchas — the #1002 rename bullet's `_WSR_SWEPT_RELPATHS` / revision-side-read rule), `.prflow/prompt-extensions/implement.md`, `.prflow/prompt-extensions/review-and-fix.md`, `.prflow/prompt-extensions/receiving-code-review.md` | Owner `lib/test/run.sh` `_WSR_SWEPT_RELPATHS` array; also `docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md`, `CONTRIBUTING.md`. These hold `git show <old-commit>:<path>` args that must keep the **old** `.devflow/` spelling, so a repo-wide rename must NOT rewrite them. | No | `lib/test/run.sh` `_WSR_SWEPT_RELPATHS` (module `tier1-rename-migration` / pin-corpus-lint) |

## B. Couplings with `CLAUDE.md` as a named partner (prose-derived)

| # | Name | CLAUDE.md location (section + phrase) | Mirror half file(s) & location | skills/ mirror? | Enforcing test/pin |
|---|------|---------------------------------------|--------------------------------|-----------------|--------------------|
| B1 | Tiered-runner final-gate / single-turn policy | **DISSOLVED by the #1352 edits.** `CLAUDE.md`'s Commands section is now the single home (*Choosing the iteration test*, *The whole-suite gate*, *Recording a whole-suite launch*); no extension restates it, so there is no longer a mirror to reconcile | Formerly `.prflow/prompt-extensions/implement.md`, `review-and-fix.md`, `receiving-code-review.md`. Each now carries only its own command's binding; the relocated mechanics live unlinked in `docs/internal/claude-md-tiered-suite-rationale.md` | No | n/a — the coupling no longer exists |
| B2 | Writing-skills evidence marker routing | Conventions, writing-skills bullet: "**This bullet and that extension routing rule are a coupled pair — edit both together**"; producer/consumer named as `implement.md`'s evidence contract + "the two review extensions' byte-identical gate" | `.prflow/prompt-extensions/implement.md` ("Prompt-surface edit routing" rule, evidence contract, `Writing-skills evidence:` marker literal); consumer gate byte-identical in `review-and-fix.md` and `review.md` | Indirect — gate is consumed by the review-engine skill; base "invoke writing-skills" rule sits in `skills/*/SKILL.md` | `lib/test/run.sh` pins the `Writing-skills evidence:` marker literal in lockstep across `review-and-fix.md` & `review.md` (#1171); disposition-slot shape (#1171) |
| B3 | Grant-timing bootstrap (trigger-time-inert config) | Gotchas, grant-timing bullet: "**Semantic (not literal) mirror sites — sweep and reconcile all three when editing this bullet**" | `.prflow/prompt-extensions/create-issue.md` (Grant-timing-bootstrap evidence axis), `docs/internal/cloud-setup.md`, `docs/internal/implement-skill.md` | No | None (explicitly *semantic*, not literal — no pin) |
| B4 | Versioning-via-changeset policy home | Gotchas, versioning bullet: "PRFlow manages its own version through its consumer prompt extension `.prflow/prompt-extensions/implement.md` — **edit that extension, not the skill**"; plus "a **coupled invariant** with `skills/docs-release-notes/SKILL.md` Step 4b … both pinned in `lib/test/run.sh`" | `.prflow/prompt-extensions/implement.md` (versioning rule, §"CHANGELOG correctness"); `skills/docs-release-notes/SKILL.md` Step 4b (the `chore: bump version` subject); `.github/workflows/version-consolidate.yml` (producer) | Yes (`skills/docs-release-notes/SKILL.md`) | `lib/test/run.sh` coupling pin on the `chore: bump version` subject (producer ↔ consumer) |
| B5 | Non-preflight-PATH-tool selection guard (guard-class 2) | Gotchas, "value that decides a SELECTION" bullet: "This is the repo's `.prflow/prompt-extensions/review-and-fix.md` **guard-class 2**" | `.prflow/prompt-extensions/review-and-fix.md` (guard-class 2) and its coupled mirror `.prflow/prompt-extensions/receiving-code-review.md` — see C1/C3 | No | None machine (review pass); cross-reference direction |
| B6 | Autonomous CLAUDE.md-edit carve-out (#366) | Conventions, autonomous-edit bullet: "This bullet is the `CLAUDE.md` half of a **coupled pair** — its mirror is the `CLAUDE.md` edit carve-out in `skills/implement/SKILL.md`; **edit both together**" | `skills/implement/SKILL.md` (CLAUDE.md-edit carve-out) | Yes (`skills/implement/SKILL.md`) | **Both halves pinned** in `lib/test/run.sh`'s `#366` block: `#366: SKILL carve-out — required CLAUDE.md edit made directly by the orchestrator (operative)` ↔ `#366: CLAUDE.md carve-out bullet mirrors the SKILL rule (coupled half)`, plus the AC4-widening pair `#366: SKILL carve-out is widened to cover the issue's own ACs (AC4 widening arm)` ↔ `#366: CLAUDE.md carve-out bullet carries the same AC4 widening arm (coupled)` |
| B7 | Repo-root `.prflow/` reader contract (fallback-only scope) | Gotchas, anchor bullet: "the enumerations naming this reader in `.prflow/config.schema.json` and `scripts/emit-git-env.sh` are a **coupled pair** that records the fallback-only scope" (partner set touches the prompt-extension *reader* `load-prompt-extension.sh`, not extension bodies) | `.prflow/config.schema.json`, `scripts/emit-git-env.sh`, `lib/load-prompt-extension.sh` | No | `lib/test/run.sh` #295/#874 pins |

## C. Extension ⇄ extension couplings (both partners are live extensions)

| # | Name | Location A | Location B (mirror) | skills/ mirror? | Enforcing test/pin |
|---|------|-----------|---------------------|-----------------|--------------------|
| C1 | Guard-class best-effort-parser adversarial-matrix section (#466) | `review-and-fix.md` "this section is its **coupled mirror** in `receiving-code-review.md` — edit both in the same change" | `receiving-code-review.md` (reciprocal) | No | None machine (review pass); real copy |
| C2 | Guard-class-2 selection-guard paragraph (real copy) | `review-and-fix.md` HTML comment: "**Coupled copy (same-commit reconciliation)** … mirrored in `receiving-code-review.md` … **Edit both together**" | `receiving-code-review.md` (reciprocal comment + the copied paragraph) | No | None machine; each extension loaded independently so no pointer resolves |
| C3 | Single-turn CI-push + full-run mandate | `review-and-fix.md` "**Coupled copy (same-commit reconciliation)** with `receiving-code-review.md`'s single-turn mandate" | `receiving-code-review.md` single-turn mandate paragraph | No | None machine (real copy) |
| C4 | Issue-#1252 batching rule (THREE-way real copy) | `implement.md` HTML comment: "THREE-way real copy — this file is its single-source home … edit all three together" | `review-and-fix.md` and `receiving-code-review.md` batching-rule copies | No | None machine (3-way copy) |
| C5 | Prompt-surface edit-routing evidence gate (byte-identical twin) | `review.md` "It is the **byte-identical twin** of the same criterion in `review-and-fix.md` … Edit both copies in the same change" | `review-and-fix.md` (same review-gate criterion); marker literal also produced by `implement.md` | Indirect (review-engine skill consumes it) | `lib/test/run.sh` marker-literal lockstep pin (`review-and-fix.md` ↔ `review.md`), see B2 |
| C6 | Focused-test-modules fix-iteration default (adapted, not lockstep) | `receiving-code-review.md` "`review-and-fix.md`'s 'Focused test modules …' section governs and this one defers … adapted rather than mirrored in lockstep" | `review-and-fix.md` "Focused test modules are the fix-iteration default" section | No | None (deliberately *not* lockstep — source-of-record + adaptation) |
| C7 | Conflict-sibling / `conflict-class` registry procedure prose | `implement.md`, `review-and-fix.md`, `receiving-code-review.md` (near-identical `conflict-sibling` by-hand procedure) | Reciprocal across all three; describes `regenerate-artifacts.py` registry vocabulary | No | Registry itself (`regenerate-artifacts.py --list`); prose copies unpinned |

## D. Extension ⇄ non-extension couplings (extension is a partner)

| # | Name | Extension location | Mirror half file(s) & location | skills/ mirror? | Enforcing test/pin |
|---|------|--------------------|--------------------------------|-----------------|--------------------|
| D1 | Preflight-guaranteed tool set enumeration | `implement.md` "this enumeration is a **coupled mirror** of that header … `lib/test/run.sh` pins the two" | `lib/preflight.sh` header (git / gh / jq / python3≥3.11 + PyYAML) | No | `lib/test/run.sh` pins both sides (rename/remove on either turns suite RED) |
| D2 | `chore: bump version` subject producer↔consumer | `implement.md` "The producer (`version-consolidate.yml`) and consumer (Step 4b) are kept in **lockstep** by a coupling pin in `lib/test/run.sh`" | `.github/workflows/version-consolidate.yml`; `skills/docs-release-notes/SKILL.md` Step 4b | Yes (`skills/docs-release-notes/SKILL.md`) | `lib/test/run.sh` coupling pin (same pin as B4) |
| D3 | Writing-skills marker literal ↔ review-gate criterion | `implement.md` "a **coupled site**, pinned in **lockstep** across `review-and-fix.md` and `review.md`" | `review-and-fix.md`, `review.md` review-gate criterion | Indirect | `lib/test/run.sh` marker-literal pin (same as B2/C5) |
| D4 | `$PR_BASE_BRANCH` variable-name pin (no `$BASE_REF` spelling) | `review.md` "## `$PR_BASE_BRANCH` naming (this repository's reason)" — "`#424` `grep -c` pin in `lib/test/run.sh`, **mirroring** `lib/fetch-pr-context.sh`" | `skills/review-and-fix/` engine surface (the fence the pin scans); `lib/fetch-pr-context.sh`, which supplies the variable | No | `lib/test/run.sh` assertion `#424 (item 6a) fence references no undefined $BASE_REF (the VC-12 silent-no-op var)` — a `grep -c` zero-occurrence guard. (The extension's own wording calls this a "`verdicts_in`"-adjacent pin; it is not — `verdicts_in` is an unpinned jq function in `lib/fetch-pr-context.sh`.) |
| D5 | Repo-specific command names / coupled-pin recognizers (relocation from CLAUDE.md, #1072) | `implement.md` — concrete command names/pin recognizers relocated here; phase files state obligations **generically** | `skills/implement/phases/*.md` (generic form-constraint statements); `lib/test/**` (pruned from vendored plugin by `.github/actions/vendor-plugin/vendor-slice.sh`) | Yes (`skills/implement/phases/*.md`) | `lib/test/lint-shipped-pruned-path.py` (audits `skills/**`/`agents/**` for pruned-path refs); form-constraint in phase files |
| D6 | Coupled-mirror-sites authoring doctrine (self-describing rule) | `create-issue.md` "**Coupled mirror sites.** A value or contract sentence that more than one file must carry … edited in every mirror in the *same* change" | Governs the whole tree (whitespace-normalized enumeration discipline); mirrors the same doctrine in `CLAUDE.md`'s single-source-of-truth Convention | No | None machine (authoring doctrine / review pass) |

## Post-edit reconciliation (the #1352 placement edits)

Rows whose state changed when the placement rule was applied. Every other row above is unchanged.

| # | What changed | Same-commit reconciliation |
|---|--------------|----------------------------|
| B1 | Dissolved — the tier-scoped policy is single-homed in `CLAUDE.md` and restated in no extension | Removed the three extension copies and the `CLAUDE.md` bullet's self-declared-mirror sentence together; relocated their rationale unlinked |
| C1 | Unchanged — `review-and-fix.md` ⇄ `receiving-code-review.md` config-derivation mirror survives | Both copies compressed under the prose rule; the pinned `$SIXSHAPE_SET` literal is byte-identical in both and in `CLAUDE.md` |
| C2 | Unchanged — the guard-class-2 selection-guard copy survives with its reciprocal HTML comments | Both compressed identically in the same commit |
| C3 | Dissolved — the single-turn CI-push mandate moved into `CLAUDE.md` with the rest of the tier policy | Removed from both extensions in the same commit as the `CLAUDE.md` statement |
| C4 | Dissolved — the issue-#1252 batching rule is now stated once in `CLAUDE.md` | The three-way real copy and its three authoring comments removed together |
| C5 | Unchanged — the byte-identical review-gate twin survives | The shared tail was rewritten once and spliced into `review.md` and `review-and-fix.md` from the same source, and `run.sh`'s `#506` byte-identity assertion re-verified |
| C6 | Unchanged — `receiving-code-review.md` still defers to `review-and-fix.md`'s section by verbatim heading | The heading text is untouched; `run.sh`'s `#707` heading pin re-verified |
| C7 | Dissolved — the near-identical `conflict-sibling` procedure is now stated once in `CLAUDE.md` | Removed from all three extensions in the same commit; `implement.md` retains a `regenerate-artifacts.py` fence because `run.sh`'s `#1354 T2` asserts that file's head against the config grant channel |
| D1 | Weakened, and the prose corrected — the extension-side preflight-enumeration pin was already retired | `implement.md` no longer enumerates the set nor claims the pin exists, and `run.sh:10205`'s assertion name no longer advertises the retired pin |

## Notes on completeness and blast radius

- The registry (input 1) surfaces **only** `wsr-swept-relpaths` (A1) as an extension/CLAUDE.md
  partner; the bulk of the couplings are prose-declared (inputs 2–3) and carry **no machine pin**,
  relying on same-commit reconciliation and the review pass. Treat every unpinned row as a
  hand-maintenance hazard.
- **skills/ mirror rows** (B4, B6, C5-indirect, D2, D5, B2-indirect) have the widest blast radius:
  their mirror half ships into consumer repos, so a desync is a vendored-surface defect. D5 is
  additionally guarded because `lib/test/**` is pruned from the vendored plugin.
- The three-way batching copy (C4), the tiered-runner mirror (B1), and the byte-identical review-gate
  twin (B2/C5) are the densest coupling clusters across the `implement.md` / `review-and-fix.md` /
  `receiving-code-review.md` / `review.md` extension family — edit any one member and check all
  siblings in the same change.
- This enumeration does not claim exhaustiveness over incidental cross-references (e.g. a bullet that
  merely *points at* an extension without a lockstep obligation, such as the CLAUDE.md
  "Helper cutover deletes the superseded prose" Convention bullet's advisory reference to
  implement.md "Keeping prompt prose lean"); those are noted where found but are not
  coupled sites.
