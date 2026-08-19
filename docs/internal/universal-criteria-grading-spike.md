# Spike: grading a universal acceptance criterion against the surface at HEAD

Investigation and design for issue #1500. This is a **spike**: it changes no engine
file. Its deliverable is this document — a design plus the offline measurements the
issue asked for. The recommendation is at the end.

A **universal acceptance criterion** is one that quantifies over *every unit of a named
surface* — e.g. *"each instruction carries the instruction, at most one sentence naming
what breaks if it is skipped, and a pointer only to an artifact that ships with the
plugin."* Confirming it means reading the whole surface and checking the property holds
for every unit; a reviewer who reads a single site confirms nothing, and neither does a
verifier reading `source_line ± 20`. The engine already holds this concept for a
*diff-added* universal — `agents/checklist-generator.md`'s `absolute_claim` category,
which states verbatim that *"a reviewer reading the claim confirms nothing — only a
failed attempt to falsify it does"* and forbids `lite` mode by construction. A universal
carried in the **issue** is instead routed to `issue_acceptance`, which inherits none of
that discipline: `claim_provenance` defaults to `generated_paraphrase`, and the verifier
reads a site (`agents/checklist-verifier.md` Step 2, the `±20 lines` read) rather than
the surface at HEAD.

## Detection

**Is a universal criterion reliably detectable from criterion text by the same quantifier
word-list `agents/checklist-generator.md` already uses for `absolute_claim`? No — the
word-list detects a much broader "universal-shaped" population with a high false-positive
rate, and misses genuine universals phrased without a listed token (false negatives).**

The `absolute_claim` word-list (`agents/checklist-generator.md`, the *Absolute claims*
bullet) is: `"no X can Y"`, `every`, `never`, `always`, `cannot`, `in all cases`,
`is caught by the same rule`, `handles every`. Extending it with the near-synonyms this
repo's criteria actually use (`each`, `all`, `any`, `none`, `only`, `whenever`,
`exactly`, `complete by construction`) and requiring a co-occurring surface reference
(a file path or a `skills/`/`agents/`/`phases/`/`references/` token), a word-list
classifier flags **17 of the 20** sampled issues (see *Frequency and size*). Hand-review
of those 17 shows only ~8 are genuine surface-universals; the rest are false positives.

**False-positive classes found while classifying** (each carries a listed quantifier and
a surface reference, but is *not* a surface-universal a verifier must read a whole file at
HEAD to grade):

- **Negative existence check** — resolvable by one `grep`, not a per-unit read. Issue
  #1730: *"a run of `grep -rnE "floor-marked" skills/create-issue/references/
  docs/internal/` prints no lines"*; issue #1734: *"No allowlist grant is added"*; issue
  #1729: *"carries no paragraph opening `**Move 2a —`, … each checked with `grep -c` …
  printing `0`"*. The criterion's own text names the single search that settles it.
- **Diff-scoped universal** — quantifies over *this change's own edits*, enumerable from
  the diff, not the surface at HEAD. Issue #1560: *"The span carries exactly one vendored
  fence, whose … lines are exactly these five — complete by construction"*; issue #1729:
  *"Every checkbox row present … before the change is present … after"*. `complete by
  construction` is a strong quantifier trigger but here ranges over a bounded diff.
- **Whole-suite / command-run gate** — satisfied by running a command, not reading a
  surface. Issue #1560: *"The whole test suite reports no failures and no skips"*; issue
  #1754: *"`git ls-files '*.sh' | … shellcheck …` reports no finding"*.
- **Measurement criterion** — a byte/size comparison. Issue #1560: *"at or under the
  61,750-byte ceiling"*; issue #1729: *"at least 3,500 bytes smaller"*. (These already
  have their own instrument and are out of scope for universal grading — but the
  word-list flags them because *"exactly"* / *"at least"* read as quantifiers.)

**False-negative class** — a genuine surface-universal phrased without a listed token.
Issue #1761: *"A reader of the Step 1 leg-partition passage in `skills/create-issue/
SKILL.md` can resolve the internal-documentation location using only that passage"* is a
universal over that passage's self-containedness (*"using only"*), and the closest listed
token is `only`, which was added only because this classifier extended the base list. The
base `absolute_claim` list alone would miss it, and would miss any universal expressed as
*"the whole …"*, *"throughout"*, or a bare plural noun (*"the statements … are true"*,
issue #1762 — detectable only via `all`/`every` if present, and #1762 happens to add
*"complete by construction"*, which the base list lacks).

**Conclusion.** The quantifier word-list is a usable *first-stage filter* (it has few
genuine misses once extended) but is **not** a reliable classifier on its own: its
false-positive rate on this corpus is ~50% of flagged items, because the same quantifier
tokens dominate diff-scoped universals, negative-existence checks, and command-run gates.
Reliable detection needs a second predicate the word-list cannot express — *does the
criterion's truth require reading every unit of a named surface as it stands at HEAD,
rather than the diff, a single grep, or a command run?* That predicate is a judgement, so
the design (below) puts the discriminator on the checklist item as an author-set field
rather than inferring it from criterion text.

## Frequency and size, measured

**Sample.** The 30 most recently merged PRs, enumerated by this exact command (run
2026-08-19 against `The01Geek/prflow`):

```
gh pr list --state merged --limit 30 --json number,title,mergedAt,closingIssuesReferences
```

Each PR's closing issues were then read with `gh issue view <n> --json body,title`, their
`## Acceptance Criteria` section extracted, and each criterion (checkbox, numbered-list,
or bold-`**AC…**` shape) classified with the extended quantifier+surface word-list above.
The full driver is reproduced in the *Measurement method* appendix.

| Measure | Count |
| --- | ---: |
| Merged PRs sampled | 30 |
| PRs with a closing issue reference | 20 |
| Closing issues examined | 20 |
| Issues whose body has an `## Acceptance Criteria` section | 20 |
| Issues that **resolved any acceptance criteria** (≥1 parsed) | 20 |
| Issues carrying **≥1 word-list-flagged universal** | 17 |
| Issues carrying **≥1 genuine surface-universal** (hand-classified) | ~8 |

So **frequency is high**: even after narrowing to genuine surface-universals, ~40% of
issues in this engine-prose-heavy repo carry at least one. This is the number that
matters for the cost question the issue raised — a rare shape would not justify the
blast-radius edit; a shape on ~2 in 5 PRs does.

**Surface sizes**, measured as byte totals using the same metric
`scripts/prompt-surface-growth.py` reports (its `surface_at()` reads
`git ls-tree -r -z --long <ref>` and takes the blob-size field; the equivalent
reproducible per-file command is `git show <ref>:<path> | wc -c`, which returns the same
blob byte count). Measured at `origin/main`:

| Named surface (appears in a genuine surface-universal, or cited by the issue) | Bytes at HEAD | Covered by prompt-surface-growth.py? |
| --- | ---: | --- |
| `skills/implement/SKILL.md` | 57,124 | yes (`skills/` `.md`) |
| `skills/review/SKILL.md` | 56,526 | yes |
| `skills/review-and-fix/references/loop-exit.md` | 56,951 | yes |
| `skills/implement/phases/phase-4-documentation.md` (issue #1560) | 59,933 | yes |
| `skills/create-issue/references/issue-template.md` (issues #1729/#1730) | 36,949 | yes |
| `docs/internal/implement-skill.md` (issue #1656) | 279,658 | **no** — outside covered prefixes |
| `docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md` (issues #1656/#1729) | 619,073 | **no** |
| `lib/test/run.sh` (issues #1557/#1581) | 3,946,915 | **no** — not `.md` |

Two findings fall out of the size column:

1. **The issue's own "Honest cost statement" byte figures are stale.** It cited
   `skills/implement/SKILL.md` at 78,745, `skills/review/SKILL.md` at 65,601, and
   `loop-exit.md` at 55,567; the measured values at HEAD are 57,124, 56,526, and 56,951.
   The first two are materially smaller than claimed (recent prose-compression passes),
   the third slightly larger. AC3's live measurement supersedes those figures.
2. **`scripts/prompt-surface-growth.py` does not cover the largest universal-bearing
   surfaces.** Its covered set is tracked `*.md` under `skills/`, `agents/`,
   `.prflow/prompt-extensions/` (its `COVERED_PREFIXES`), so `docs/internal/*.md`
   (hundreds of KB) and `lib/test/run.sh` (~3.9 MB) — both named by genuine
   surface-universals in the sample — are invisible to it. A verifier told to "read the
   whole surface" for a `lib/test/run.sh` universal would read a 3.9 MB file; that is the
   worst-case cost the design must bound. Additionally, the tool has no per-file query
   mode: it reports only merge-base→HEAD deltas for branch-changed covered files, so the
   byte figures above come from its measurement *primitive* (blob bytes) rather than a
   table it printed (on this spike's own branch it correctly prints *"no branch commits to
   measure"* because the deliverable is under `docs/internal/`, an uncovered prefix).

## Field decision

**A new machine-parsed field is warranted.** Reusing existing fields is possible but
worse:

- **Reuse `category: absolute_claim`** (route a universal issue criterion to that
  category instead of `issue_acceptance`). This inherits the falsification discipline and
  the lite-exclusion for free, but loses the `issue_acceptance` tag that Phase 1.1.5's
  rank-1 cap and the `## Issue Compliance` reporting key on, and conflates
  issue-specification items with diff-added universals. Rejected.
- **Reuse `claim_provenance: source_authored`** (which every `absolute_claim` carries and
  which already makes an item normalization-ineligible). This fixes the normalization
  hazard as a side effect (see below) but does not change the verifier's read strategy —
  it would still read `±20 lines`. Insufficient on its own.

The proposed field is a **`criterion_scope` discriminator** on `issue_acceptance` items,
with values `site` (default — a criterion satisfied at a specific location) and
`universal` (quantifies over every unit of a named surface). A `universal` item carries a
`universal_surface` sub-value naming the file the verifier must read whole.

Every new checklist-item field is a five-way contract. Coupled sites that must change **in
the same commit** (this spike edits none of them):

| Coupled site | Relationship to the field |
| --- | --- |
| `agents/checklist-generator.md` | **writes** — emits `criterion_scope`/`universal_surface` on each `issue_acceptance` item; the generator is the sole producer of `issue_acceptance` items (`phase-1-checklist.md` §1.2). |
| `agents/checklist-verifier.md` | **reads** — on `criterion_scope: universal`, reads the whole `universal_surface` at HEAD and applies the `absolute_claim` falsification discipline (construct a falsifying unit) instead of the Step 2 `±20 lines` read; sets `property_proven: true` only on an enumerated whole-surface pass. |
| `skills/review/phases/phase-1-checklist.md` | **tolerates / writes** — §1.1.5 rank-1 cap and the §1.2 `<acceptance_criteria>` prompt block; must pass the scope through and must not let a `universal` item be silently `lite`-eligible (it already cannot be — `issue_acceptance` is not an eligible lite category). |
| `skills/review/phases/phase-2-verification.md` | **reads / routes** — the §2.0 partition and §2.2 normalization invocation; must route `universal` items to `agent` mode (already forced) and must exclude them from the normalization eligibility (see *Normalization hazard*). |
| `skills/review/phases/phase-4-verdict.md` | **reads** — §4.2 rules 1/2 and the `## Issue Compliance` section; reads `criterion_scope` (and the advisory flag) to apply the scoped exclusion and to report the universal item's advisory status. |
| `scripts/normalize-verdicts.py` | **reads** — must add `criterion_scope: universal` (or the reused `source_authored` provenance) to the real-value blocker set so a universal FAIL can never normalize to a stored PASS. |
| `lib/efficiency-trace.jq` | **tolerates** — `iter_view` selects checklist items on `.verification_mode` only (`select(.verification_mode == "lite"/"agent")`) and tolerates unknown item keys, so a new field is additive and needs no change beyond confirming tolerance. |

The generator/verifier/Phase-2-orchestrator trio must change together or items arrive
underspecified (the generator emits a field the verifier ignores, or the verifier is told
to read a surface the generator never named). `normalize-verdicts.py` and
`efficiency-trace.jq` use key-tolerant access, so their change is a hardening, not a
break.

## Advisory channel

**Phase 4.2 rules 1 and 2, quoted as they read at HEAD** (`skills/review/phases/
phase-4-verdict.md` §4.2):

> 1. Any verification checklist item with verdict FAIL → REJECT
> 2. Any verification checklist item with verdict INCONCLUSIVE → REJECT (add "manual
>    check needed" note)

**Why returning INCONCLUSIVE is not an advisory arm here.** INCONCLUSIVE is rule 2 — the
*maximally* blocking outcome, tied with FAIL. A universal that a verifier honestly cannot
establish from a single read returns INCONCLUSIVE and therefore **REJECTs** the PR. So the
intuitive "ship it advisory by returning INCONCLUSIVE" is inverted in this engine: it
blocks the merge rather than noting a caveat. An advisory channel cannot be built by
choosing a verdict token; it must carve an exclusion into rules 1 and 2 themselves — the
two rules that gate every PR in every consumer repo.

**Concrete advisory channel.** Keep the universal item in the checklist (so it is graded
and reported) but stop its verdict from driving rules 1/2 when the feature is in advisory
mode:

1. The generator/verifier produce the item with `criterion_scope: universal`. The verifier
   still grades it (PASS / FAIL / INCONCLUSIVE) and reports its enumeration evidence.
2. Phase 4.2 rules 1 and 2 gain the scoped exclusion below.
3. The `## Issue Compliance` section (Phase 4.1) gains one line per universal item —
   *"Universal criterion (advisory): {claim} — {PASS|FAIL|INCONCLUSIVE}: {evidence}"* — so
   the grade is visible to the human merging even though it did not gate.

**The exact scoped exclusion the gating edit would need**, appended to rules 1 and 2:

> 1. Any verification checklist item with verdict FAIL → REJECT *(excluding an item with
>    `criterion_scope: universal` while `prflow_review.universal_criteria_grading.enabled`
>    resolves off — such an item is reported under `## Issue Compliance` as advisory and
>    does not gate)*
> 2. Any verification checklist item with verdict INCONCLUSIVE → REJECT (add "manual check
>    needed" note) *(same `criterion_scope: universal` advisory exclusion as rule 1)*

The exclusion is keyed on the machine field, never on the finding's prose, and is scoped
so a `site` item (the default) is completely unaffected — an ordinary `issue_acceptance`
FAIL still REJECTs exactly as today. When the gating key resolves **on**, the exclusion
does not apply and a universal FAIL/INCONCLUSIVE REJECTs like any other item.

## Gating

A config key modelled on the existing `prflow_review.stale_prose` object shape in
`.prflow/config.schema.json` (which is `{ "enabled": boolean, "severity": enum }`):

```json
"universal_criteria_grading": {
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "enabled": {
      "type": "boolean",
      "description": "Master switch for universal-criterion grading of issue_acceptance items on the merge-gating review engine. Default false: a universal criterion is graded and reported under ## Issue Compliance but does NOT gate the verdict unless this is EXPLICITLY true. Any value other than explicit true resolves OFF.",
      "default": false
    }
  }
}
```

**Default and resolution rule.** Default `false`. Resolved via the same
skill-dir-anchored, no-`bash`-prefix `config-get.sh` invocation Phase 4.2 already uses for
`verdict_severity_threshold`:
`config-get.sh .prflow_review.universal_criteria_grading.enabled false`. **The safe
direction is the opposite of `stale_prose.enabled`'s.** `stale_prose.enabled` defaults
**on** and treats *"any value other than an explicit `false`"* as enabled — correct for a
feature that is safe to run by default. A new arm on the *merge judge* is the reverse: a
universal grade that gates a merge must be opt-in, so **anything other than an explicit
`true` resolves off**, and the extraction default is `false` (not `true`).

**The valid-falsy hazard** (the documented off-switch-that-never-worked bug, #312/#304):
because `config-get.sh` coerces any JSON value to a string and does not validate it, an
`// true` extraction default (or an `// true` jq fallback) would silently coerce a real
configured `false` — or an absent key — to `true`, turning the gate **on** against the
operator's intent. For a default-off gate the corresponding trap is to write the resolver
as `… // true` or to treat *"not the string `false`"* as on; both re-introduce the
off-switch-never-worked bug in the on-direction. The resolver must default `false`, must
enable **only** on the byte-exact string `true`, and must be validated inline (a `case`
on the resolved value, exactly as §4.2 validates the threshold enum), never trusted as a
raw truthy coercion.

## Normalization hazard

**Can the `generated_paraphrase` normalization path currently turn a FAIL on an
`issue_acceptance` item into a stored PASS? Yes.** `scripts/normalize-verdicts.py`'s
five-conjunct predicate is computed in **`_process_pair`** (the `can_normalize` assignment:
`raw == "FAIL" and not real_blockers and not field_defect_blockers`), which then sets
`result["verdict"] = "PASS"` and `result["normalized"] = True`. The conjuncts are: (1)
`verification_mode == "agent"`; (2) `claim_provenance == "generated_paraphrase"`; (3) raw
verdict byte-exact `FAIL`; (4) `property_proven` is JSON boolean `true`; (5)
`inaccuracy_scope == "generated_claim_text"` — conjuncts (4) and (5) evaluated in the
helper's **`_aux_state`** function.

An `issue_acceptance` item satisfies conjuncts (1) and (2) *structurally*:
`agents/checklist-generator.md` defaults `issue_acceptance` items to
`claim_provenance: generated_paraphrase` and they are never `lite`-eligible, so they run in
`agent` mode. That leaves only the verifier's own `property_proven`/`inaccuracy_scope`
fields between a raw FAIL and a stored PASS. For a universal, this is exactly the wrong
place to leave the decision: a verifier reading a single site *cannot legitimately* prove a
universal (`property_proven` should be `false`), but nothing prevents it from emitting
`property_proven: true` + `inaccuracy_scope: generated_claim_text` — at which point all
five conjuncts hold and the FAIL is silently stored as PASS, which Phase 4.2 rule 1 never
sees. The normalization is *correct* for its intended case (a genuine wording artifact
over code the verifier positively established); it is *unsafe* for a universal, whose
property is not establishable from the read the verifier actually performed.

**This warrants its own small ticket, independent of the universal-grading design.** The
fix is a one-line hardening: add `criterion_scope == "universal"` (or, more broadly, the
`issue_acceptance` category, or the reused `source_authored` provenance) to the
`real_blockers` set in `_process_pair`, so a universal/issue-acceptance FAIL is never
normalization-eligible. It is independent because it protects the current
`issue_acceptance` path *today*, before any `criterion_scope` field ships, and because it
is a `normalize-verdicts.py`-only change with its own unit test (the helper is stdlib-only
and unit-testable per its module header), whereas the grading design touches the generator,
verifier, and verdict phases.

## Recommendation

**Implement-with-narrowed-scope.**

Frequency justifies the work: ~40% of sampled issues carry a genuine surface-universal, and
the review that missed one (PR #1436's *"split dense preconditions"* claim, false against a
3,322-byte paragraph) is the recurring failure this targets. But three findings narrow how
it should ship:

1. **Split out the normalization hazard now, as its own ticket** (the one-line
   `_process_pair` hardening above). It is a live silent-fail on the *existing*
   `issue_acceptance` path, independent of the rest, and cheap.
2. **Do not build automatic text-based detection.** The quantifier word-list is too noisy
   (~50% false positives on this corpus) and the true predicate — *does this require
   reading a whole surface at HEAD?* — is a judgement, so the discriminator belongs on the
   checklist item as an author-set `criterion_scope` field the generator assigns, not an
   inferred classification. Reliability comes from making the verifier read the whole
   surface and falsify (reusing the `absolute_claim` discipline) *once a criterion is
   tagged universal*, not from detecting universals mechanically.
3. **Ship the gate opt-in, defaulting off.** The advisory-channel exclusion carves into
   Phase 4.2 rules 1 and 2 — the merge judge for every consumer repo — so it must default
   off (a universal is graded and reported but does not gate) and be widened to gating only
   by an explicit `true`, guarding the valid-falsy off-switch bug. The cost of a whole-
   surface read (up to ~3.9 MB for a `lib/test/run.sh` universal) also argues for opt-in
   until measured against real runs.

A "do not implement" outcome was considered and rejected on the frequency evidence; a
full "implement" was rejected because shipping the gate on-by-default on the merge judge,
with text-based detection, is exactly the high-blast-radius guess the issue warned against.

## Measurement method (appendix)

The sample and classification were produced offline (no engine change) by the driver
below, run against the 30-PR sample. It fetches each closing issue, extracts the
`## Acceptance Criteria` section, parses criteria (checkbox / numbered / bold-`**AC…**`),
and flags a criterion as a candidate universal when it carries a quantifier token
(`every`, `each`, `all`, `any`, `never`, `always`, `cannot`, `no`, `none`, `exactly`,
`only`, `whenever`, `in all cases`, `is caught by the same rule`, `handles every`,
`complete by construction`) **and** a surface reference (a `*.md`/`*.py`/`*.sh`/`*.jq`/
`*.json`/`*.yml` path, or a `skills/`/`agents/`/`phases/`/`references/` token). The
word-list-flagged count is a *first-stage* number; the genuine-surface-universal count
(~8) is the hand-classification described under *Detection*, distinguishing surface
universals from negative-existence checks, diff-scoped universals, command-run gates, and
measurement criteria. Byte sizes were taken with `git show origin/main:<path> | wc -c`,
the blob-byte primitive `scripts/prompt-surface-growth.py`'s `surface_at()` uses.
