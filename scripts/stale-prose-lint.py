#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Deterministic stale counted-prose lint (issue #423).

Detects the top defect class escaping PRFlow's in-run review-and-fix loop to the
standalone review: **diff-added prose asserting counts, ranges, sums, or absolutes
that the same PR's later commits outgrow or falsify**. Modeled on
``lib/test/pin-corpus-lint.py`` (deterministic scanner + fail-closed accounting).

The four deterministic rule classes, each evaluated over **diff-added comment / prose lines**
and resolved against the **post-diff file state**:

**Scoping (issue #434).** A claim is prose. A line of *code* that merely contains claim-shaped
text — a shell fixture string, an assertion name — is data, not an assertion about the file,
so it is not examined; ``prose_mask`` decides this per file type (markdown-family prose outside
fenced blocks; ``#`` comments; ``//`` comments and ``/* … */`` interiors; Python ``#`` comments
plus real docstrings, resolved with ``ast``). The same predicate scopes R4's *permit referent*,
so a code line can neither raise a claim nor contradict one. **An unrecognised file type fails
OPEN — every added line is examined, exactly as before — with a stderr breadcrumb.** Never the
reverse: a closed allowlist would silently reduce a consumer repo in an unlisted language to a
permanent no-op (empty output, exit 0, forever) while this header still advertised the check.
Deliberately NOT examined (accepted, not accidental): ``.sh`` heredoc prose, YAML block-scalar
prose, trailing comments after code, and ``#`` comments inside ```` ```bash ```` fences in
markdown. None of the four historical escape shapes lived on those surfaces.

**Excluded population: machine-appended corpora (issue #672).** Diff-added lines under
``.prflow/learnings/`` and ``.prflow/logs/``, and in the single rendered census artifact
``lib/test/mutation-pin-corpus-adjudications.tsv``, are not examined at all. Those files are
records PRFlow *writes* — a retrospective, an experiment record, a log — each quoting
reviewed prose verbatim inside a JSON string. The quoted text is data about a past PR, never
an assertion about the file it now sits in, and no referent for it exists in the post-diff
state to resolve against. The trigger was PR #673, whose only edit to two such records
replaced an operator home path with ``~``: that re-presented each whole 5 KB JSONL record as
a diff-*added* line, the unlisted ``.jsonl`` type failed open to examine-every-line as
designed, and a 2026-07-10 retrospective's narration of a *previous* PR's counted claim
graded STALE — failing CI on a diff that had authored no claim. Any later rewrite of a corpus
line re-trips it, so the exclusion is keyed to the path, not to that one edit. The census
artifact joined the list for the same reason on a different surface: its ``logical_call``
column quotes each censused pin's source text verbatim, so every count a pin name carries is
data about that pin, and the adjacent TSV rows are not its referent. Two neighbours
are deliberately **not** excluded: ``CHANGELOG.md`` and ``.changeset/`` are human-authored
prose about the current change, exactly the surface this lint exists to grade. The exclusion
is announced on stderr per run — an intended coverage drop is still a coverage drop, and must
be as discoverable as the fail-open arm above. Scope boundary: it selects which files' ADDED
lines are graded; the diff-global removed-line multiset behind the issue-#629 move exemption
is untouched, so an excluded path can still supply a relocation *source* — which requires
byte-equality between a JSON record and a prose line, and so is unreachable in practice.

* **R1 range-outgrowth.** A ``Cases A-B`` header whose forward region (the lines
  after it in the post-diff file) contains a ``Case N`` with ``N > B`` — the header
  was frozen while the block it introduces grew past it (the PR #328 shape).
* **R2 legend-sum.** An ``Expected total = N`` claim whose adjacent enumeration
  block does not contain exactly ``N`` items (the PR #320 shape).
* **R3 / R3b count-locked.** An exact-count claim (``N assertions``) or a two-item
  ``a X and a Y … both`` claim resolved against the adjacent assertion block; a
  mismatch is STALE, a match a VERIFIED ``count-locked`` row (the PR #336 shape).
  ``R3b`` names the two-item *shape* only; both sub-cases are emitted under the
  ``rule`` TSV token ``R3`` — there is no ``R3b`` output token. The numeric R3
  arm's ``_COUNT_RE`` requires the trigger noun in **plural** form and refuses a
  numeral directly preceded by ``#`` / ``§`` / a digit / ``.`` / ``-`` (issue
  #1405) — so a singular ordinal reference (``Step 3 item 6``) or a ``#402``-style
  reference is not read as a count claim; a plural ordinal (``Step 3 items 1-4``)
  is a disclosed residual that still gates.
* **R4 modality-conflict (operator-token restricted).** A deny-absolute
  (``never``/``no``/``not``/``any``/``forbidden`` …) about a **backticked operator
  token** — one of ``> >> < << | || && & |& 2> 2>> &>`` — that the SAME post-diff
  file also asserts is *permitted* elsewhere (the PR #397 shape). The
  **operator-token restriction is the only shipped operating point**: a backticked
  token that is not an operator (an arbitrary named identifier) is never examined,
  which is the false-positive boundary a named-token scope mismatch stays clear of.

**R3 recognition-only tier (issue #439).** Layered cleanly over the R3 count-locked rule
above without touching it, and **evaluated after every gating rule — R1/R2/R3b/R3 each
``continue`` on a match, and R4 ``continue``s on the match it CLAIMS (issue #818 narrowed it
to its emit path) — so it is reached only on a line no gating rule emitted a row for** (an earlier placement let a line matching both the widened count shape and a gating
R4 deny-absolute be consumed here before R4 could run, suppressing a real STALE). A diff-added
prose/comment line that matches a *widened* claim shape but that no gating rule (including the
gating ``_COUNT_RE``) claims emits a single ``UNRESOLVABLE`` ``R3`` row whose detail begins
``count-locked: recognition-only (<n> <noun>) — pin or drift-proof this claim``.
The widened shape is: a spelled-out numeral word (``two`` … ``twelve``, case-insensitive ASCII)
or a digit run; up to two intervening modifier words (each optionally wrapped in ``**…**`` /
``*…*`` / backticks); and a noun from the *widened* set — every noun in the gating
``_COUNT_NOUNS`` constant (interpolated in its ``s?`` form) plus the plural-only additions ``tags`` / ``members`` / ``fields`` / ``rows`` / ``columns`` /
``arms`` / ``files`` / ``rules`` / ``sites``. This tier is **non-gating by construction**: it
runs **no** referent resolution (no adjacency walk, no table parsing), never emits STALE, and
never affects the exit code (``UNRESOLVABLE`` never gates). Its only job is to surface the
``count-locked`` literal the pin-or-don't-write policy keys on, so an unpinned counted claim
announces itself in the fix loop's Step 3 pre-check and the Phase 0.6 note.

**Recognition-tier noise guards** (noise-limiting only — the tier cannot gate, so these need not
be correctness-critical): the numeral must not be directly preceded by ``#`` / ``§`` / a digit /
``.`` / ``-`` (so ``#402``-style references and ``§2.3`` section numbers are never read as
numerals); and an intervening modifier token that is numeral-shaped, or one of ``of`` / ``per`` /
``and`` / ``or`` (killing partitives like "two of these tags"), disqualifies the recognition. A
token carrying sentence punctuation cannot even form a modifier — the modifier pattern is a bare
word — so such a token structurally breaks the match rather than being separately rejected.

**Recognition-tier out of scope (by design, decided in issue #439).** Verification / gating of the
widened surface, markdown-table referent counting, and adjacency-walk relaxation are deliberately
**not** built — the #423 build methodology routes such n=1 verification shapes to the review-agent
LLM carve-out, which remains the gate for this class. Numeral words are English-only (a documented
accepted boundary for non-English consumer repos). Hyphenated numeral compounds (``twenty-one``)
and the word ``one`` (idiom-heavy) are excluded.

**Out of scope (by design).** The *behavioral-absolute* subclass — a deny-absolute
with no countable referent (the PR #383 "grep errors either way" shape) — is
deterministically out of reach and stays routed to ``comment-analyzer`` via the
fix loop's existing Step 3 item 3a machinery. This helper adds NO LLM fallback.

**Illustrative-example opt-out (issue #635).** The rules cannot tell an *assertion* of a claim
shape from an *illustrative example* of one — both are just claim-shaped text on a prose line —
so prose that DOCUMENTS a rule (this header's own design record, a test-fixture comment spelling
out an idiom, engine docs describing a claim class) was graded as a real claim and resolved
against whatever lines followed it. It fired twice while implementing issue #629 (PR #631): a
literal ``Expected total`` legend in a design record, plus a ``both``-summary R3b idiom
in a ``lib/test/run.sh`` fixture comment. The surface most likely to describe a claim shape is
exactly the one the lint most needs to keep clean, so those pulled against each other. The fix is
an **explicit author opt-out**: a prose/comment line carrying the marker ``stale-prose-lint: example``
anywhere on it is skipped for **every** gating rule (R1–R4) *and* for both non-gating
recognition tiers (the issue-#439 ``count-locked`` tier and the issue-#818 coverage-universal
tier), which is why it is checked before any of them.
The skip is **not silent** — the line still surfaces one non-gating ``UNRESOLVABLE`` audit row
(rule ``EX``, never ``STALE``, so the exit code is untouched), so a marker that lands on a real
claim (mis-placed, or dragged onto an adjacent claim by a relocation) stays visible to a reviewer
of the lint *output*, not only to a reader of the source. The
marker is matched as a plain substring of the raw line via ``_EXAMPLE_MARKER_RE`` (a trailing
negative-lookahead pins the exact token, so ``examples`` / ``example-driven`` do not opt a line out), so it is
**language-agnostic** — it works inside a Markdown ``<!-- … -->`` comment, a Python ``#`` /
docstring line, or a shell ``#`` comment alike, independent of comment syntax. Example (this very
line documents the R2 legend shape yet is skipped, because it carries the marker):
``Expected total = 3`` legend adjacent to a two-item list.  <!-- stale-prose-lint: example -->

Disclosed non-goals (by design): the opt-out is **line-scoped** — it exempts the whole line, not a
particular claim shape on it (a line carrying both a real claim and the marker is the author's
declared example, and is skipped in full). It is a **deliberate, discoverable opt-out**, NOT
example auto-detection: distinguishing an example from an assertion by content alone is undecidable
in the general case, so the author declares the intent explicitly rather than the helper guessing.
It does **not** weaken R4: R4's referent is a **single**-backticked operator token and its
recognition is untouched — a marked line is one the author declared illustrative, and a genuine R4
deny-absolute never carries the marker. The marker is a plain substring, so a line legitimately
containing the literal text ``stale-prose-lint: example`` for some *other* reason is also skipped
(accepted: that string is distinctive enough that its incidental appearance on a real claim line is
a non-concern, and the failure direction is a false *negative* the author can see and remove).

**Coverage-universal recognition tier (issue #818), non-gating.** A run authoring a change
routinely writes a sentence asserting a **universal about its own coverage** — "every call site
is updated", "all four arms are handled", "exactly these files" — and verifies it by *reading it
back* and finding it plausible. Reading confirms nothing; only a failed attempt to falsify does.
This tier recognizes the shape so the implement engine's Phase 2 §2.3.4b sweep has an **executed
seed list** rather than a remembered one. Like the R3 recognition tier above it is
**recognition-only**: it resolves no referent (no adjacency walk, no table parsing), never emits
``STALE``, and never affects the exit code. Its rows carry the TSV rule token ``CU``.

*The recognized shape* is a **coverage-scope token** from a closed set, adjacent to a
**coverage-referent noun** from a closed set, with up to two intervening bare-word modifiers.
The set is deliberately broader than "universal quantifier": ``only`` / ``complete`` /
``entire`` / ``whole`` are scope claims rather than universals, and are recognized because a
scope claim about the change's own coverage needs grounding for the same reason a universal
does. The quantifier may carry ``**…**`` / ``*…*`` / backtick / underscore emphasis. The scope
tokens are **exactly these — complete by construction**: ``every`` / ``all`` /
``each`` / ``any`` / ``both`` / ``no`` / ``none`` / ``exactly`` / ``only`` / ``complete`` /
``entire`` / ``whole``. The coverage-referent nouns are **exactly these — complete by
construction**, singular and plural alike: ``site`` / ``arm`` / ``branch`` / ``case`` / ``path``
/ ``file`` / ``rule`` / ``peer`` / ``consumer`` / ``caller`` / ``member`` / ``mirror`` /
``occurrence`` / ``instance`` / ``surface`` / ``checkpoint`` / ``call site`` / ``row`` /
``entry`` / ``population`` / ``partner`` / ``helper`` (the last five added for issue #1451, the
referent nouns the recurring ``incomplete-edit`` failures used). Both sets follow
the ``_COUNT_RE`` widened-noun-set precedent: they live as module-level constants and this
header is their authoritative spec. A modifier token may lead with a hyphen or backtick-hyphen
(e.g. `` `-x`-gated ``) via the CU-local ``_CU_MOD`` sibling of ``_RECOG_MOD`` (issue #1451),
which is left byte-identical because the gating-adjacent R3 tier shares it.

*Precedence, decided explicitly (against the R3 recognition tier).* The two non-gating tiers
**overlap by design** — ``arms`` / ``files`` / ``rules`` / ``sites`` sit in both noun sets, so
``all four arms are handled`` matches both. The shipped R3 tier terminates on a match, so a tier
placed *after* it would never be reached on exactly the collision shape. This tier is therefore
evaluated **before** it and **does not ``continue``**: a line matching both emits **both** rows,
and neither tier terminates the other. Both still sit after every gating rule, so a line a
gating rule emitted a row for reaches neither.

*Exclusions are inherited unchanged.* The pre-rule exclusions this header documents bind this
tier identically — the ``prose_mask`` prose/code predicate, the ``.prflow/learnings/`` and
``.prflow/logs/`` path exclusion (a whole-*file* skip, applied in ``run`` before the post-image
is read), the ``stale-prose-lint: example`` marker, and the content-anchor drop the working-tree
record below describes. The list is illustrative rather than exhaustive: this tier is reached
from the same point in ``examine_file`` as the shipped recognition tier, so whatever skips a
line before that point skips it here too, by construction rather than by enumeration.

*The issue-#629 relocation exemption is inert here, and that is the decided behavior.* That
exemption is **Demotion, not deletion** — a ``STALE`` row demoted to ``UNRESOLVABLE``. A tier
that never emits ``STALE`` has nothing to demote, so a byte-identical relocated line carrying a
coverage universal **still** emits its ``CU`` row.

*Declared opt-out —* ``stale-prose-lint: rule-text``. A line the author declares exempt carries
this marker, which suppresses the ``CU`` **seed row** and emits one non-gating ``UNRESOLVABLE``
``RT`` audit row whose detail names the declared exemption — the #635 visibility property,
ported: a marker that lands on a real claim stays visible to a reviewer of the lint *output*,
not only to a reader of the source. Matched as a plain substring with a trailing negative
lookahead (so ``rule-texts`` / ``rule-text-driven`` do not opt a line out), hence
language-agnostic across Markdown, Python, and shell comments alike. **Deliberately narrower
than the ``example`` marker:** ``rule-text`` is scoped to this tier only and never disarms a
gating rule, because an author declaring a sentence to be rule text has declared nothing about
a counted claim on the same line. It controls detector noise; it does **not** discharge
§2.3.4b's grounding obligation, which turns on whether the line is in fact one of that sweep's
two exempt kinds.

*R4's ``continue`` is narrowed to its claimed case (issue #818).* The ``continue`` of each
other gating rule — R1, R2, R3b, R3 — sits inside its own matched branch, whose every arm
appends a row. R4's sat on the outer deny-absolute match instead, so a line R4
examined and decided was **not** R4's — a deny-absolute carrying no backticked operator token,
therefore emitting no row — still short-circuited both non-gating recognition tiers. That is a
silent swallow rather than a claim, and it blinded them on every line containing ``never`` /
``no`` / ``not``: for a coverage-universal detector that is most of the population, since a
sentence asserting total coverage routinely says what is never missed. The ``continue`` now
fires only when R4 emitted a row. This adds only non-gating rows and cannot change the exit
code, and R4 still runs and still emits before either recognition tier, so the ordering
rationale recorded above is preserved.

*Disclosed non-goals.* Recognition is deterministic; adjudication is not, which is why this tier
is non-gating: a gating detector over rule prose would be a false-positive machine. The
quantifier vocabulary is English-only, inheriting the boundary the recognition-tier record above
already documents for numeral words. A universal whose referent noun is outside the closed set
("complete by construction", with no noun) is **not** recognized — the rows are a **floor** for
§2.3.4b's sweep, never its population.

**Working-tree post-image mode (issue #818).** The post-image file — the answer to "what does
this file look like after the change?" — is resolved one of two ways, selected by exactly one
required flag:

* ``--rev <revision>`` (the shipped behavior, unchanged): ``git show <rev>:<path>``. Both
  pre-#818 call sites pass this and are unaffected.
* ``--worktree``: the **on-disk** file is read directly, making the helper usable **before
  commit**, over a diff covering new, staged, and modified files alike. Internally the mode is
  carried by the distinct :data:`WORKTREE` sentinel rather than by ``None``, so an embedding
  caller threading an unset value cannot silently select it.

The mode matters more than a referent source: the post-image answer **gates entry to line
examination itself**. Under ``--rev`` on an uncommitted tree, a *modified* file resolves to its
*pre*-change content, so an added line whose text does not already appear elsewhere in the
pre-image fails its content anchor and is dropped before any rule, before ``prose_mask``, and
before the opt-out markers (``examine_file`` falls back to a whole-file text search, so an added
line that is byte-identical to some pre-existing line is instead examined at the wrong anchor —
also wrong, just differently); and a **new** file resolves to
nothing at all, emitting the file-level ``-`` row and skipping examination. A ``.changeset/*.md``
file — always new, and named in §2.3.4b's population — is exactly that second shape. So a
recognition-only tier is **not** immune to the skew, and the working-tree mode is what keeps the
obligation where the decided behavior puts it: before commit. The mode makes **no** history read
at all (not even ``git show``), so it is shallow-clone safe for the same reason the revision
mode is.

**Move-awareness (issue #629).** An extraction refactor *relocates* prose without authoring
it, but a relocated line is an **added** line in the unified diff — so every rule above used to
re-grade it as newly authored and resolve its claims against the *destination* file's context,
manufacturing a contradiction out of a move. A diff-added prose line that is a **byte-identical
relocation** is therefore never graded STALE. Two rules bound the exemption, and both fail
*toward* gating:

* **Multiplicity (multiset semantics).** A line text is exempt only when its **added**
  occurrences across the whole supplied diff do not outnumber its **removed** occurrences.
  When additions outnumber removals, every occurrence of that text grades as authored —
  surplus copies mean authorship, so a copy-amplification shape still gates and the exemption
  can never degrade to bare set-membership.
* **Referent.** The exemption holds only when the diff **adds no un-relocated referent**:
  every **diff-added** line that the claim's own rule resolves as referent content (a
  ``Case N`` item for R1, an enumeration/assertion item for R2/R3/R3b, and **every** permit
  line for R4 — not merely the first) must itself be a byte-identical relocation **whose
  provenance shares a source file with the claim's own**. A referent line the diff did
  **not** add is pre-existing content and imposes no obligation. So the *split-then-extend*
  shape — a moved ``Cases 1-2`` header with a diff-added ``Case 3`` beneath it — still gates,
  because that staleness is authored by the PR. This is what keeps the PR #328 shape
  detectable. Note the deliberate wording: **"adds no un-relocated referent", not "leaves the
  referent unchanged"** — a referent *deletion* also changes referent content and is **not**
  examined (case 10 below).
  **Provenance is part of this rule, not a refinement of it.** Relocation identity is
  full-line text equality, and referent lines are the shape most likely to be non-unique
  boilerplate, so without a provenance requirement a newly authored referent would read as
  "relocated" whenever any unrelated hunk anywhere in the diff removed a byte-identical line
  — silently disarming this half of the exemption on the very PR #336 shape it exists to keep
  gating. Requiring a shared source file (``MoveIndex.sources``) narrows that coincidence from
  "collides with any removal in the diff" to "collides with a removal in a file this claim
  also moved out of"; the residual is case 7 below.

Identity is compared on the **raw** line bytes of the diff's two sides — deliberately not
through ``_norm_line``, whose CR/BOM stripping exists for *scoping*. Both sides of a CRLF
file's diff carry the same trailing CR, so raw comparison preserves the exemption on a Windows
consumer repo, where a normalised comparison would be no less correct but a *narrower*
one — anything short of full-text identity is a relaxation this contract does not grant.

**Demotion, not deletion.** When an exempt line's resolution would have been ``STALE``, the row
is emitted as ``UNRESOLVABLE`` (the existing non-gating verdict token) with the original
diagnostic retained behind a relocation-naming prefix. The co-located contradiction stays
visible in Phase 0.6's informational channel and the fix loop's ``stale_prose_check`` record
without enforcing — and the exit-code contract, Phase 0.6's row routing, and
``match-lint-adjudications.py``'s STALE-keyed join all need no change. ``VERIFIED`` resolutions
are untouched.

**Move-awareness design record — each case explicitly decided** (the accepted-not-accidental
idiom above; a case recorded as a disclosed non-goal *fails toward gating*, which is the safe
direction for a lint). Deliberately count-free: the set accretes as review surfaces new
shapes, and an ordinal here would be an unpinned mirror-fact this file's own recognition tier
flags (``count-locked: … pin or drift-proof this claim``):

1. **File rename.** *Handled, by the producer, not by this exemption.* On the local-git
   producers (the ``#434`` self-scan's and the fix loop's ``git diff``) rename detection is on
   by default, so a whole-file ``git mv`` emits **zero** added lines and no claim is examined —
   this was already true before #629 and is unchanged. The PR-mode producer (``gh pr diff``) is
   a server-side GitHub diff that consults no host git config, so its rename pairing is
   GitHub's decision: when it emits a rename it behaves like the local case, and when it emits
   delete-plus-add the added lines are byte-identical relocations and this exemption covers
   them. Note the limitation this whole feature exists for: rename/copy detection is
   **whole-file-grained**, and unified-diff format cannot express a *line-level* move — so
   ``-C`` / ``--find-copies-harder`` do not help the block-extraction shape. The gap being
   closed is line-level move-awareness, never "no rename detection".
2. **Block split.** *Handled.* One source block relocated into two destinations is grading-wise
   just N added occurrences against N removed ones; the multiplicity rule admits it at equal
   counts and refuses it the moment the additions outnumber the removals.
3. **Partial move.** *Handled, per line.* The exemption is decided per line text, so the moved
   lines of a partially-moved block are exempt and the newly authored ones are not — and if an
   authored line is *referent* content for a moved claim, the referent rule denies that claim's
   exemption too.
4. **Cross-file resolution.** *Handled.* The multiplicity multiset is diff-**global**, not
   per-file, because a relocation's whole point is that its source and destination are
   different files. Referent resolution stays file-scoped, as every rule above already is.
5. **Copy amplification** (one removal, multiple identical additions). *Handled — gates.* The
   multiplicity rule's surplus arm grades **every** occurrence of the text as authored, not
   just the surplus one: a copy is an authorship act, and attributing "the moved one" among
   identical texts is not decidable from the diff.
6. **Byte-changing moves** (reindent, heading-level shift, rewrap). *Disclosed non-goal —
   gates.* Such a line's full text is not a removed line of the same diff, so it grades as
   authored, exactly as an edited line should. Whitespace-normalised or similarity-based
   near-matching is deliberately **not** built: every relaxation of full-text identity widens
   the set of *authored* lines a hostile or careless diff can launder past a gate, and this
   lint's failure direction must be toward gating. A wave that rewrites the lines it moves
   keeps its findings; that residual is accepted, not accidental.
7. **Deletion coincidence** — a genuine deletion in one file plus an independently authored
   byte-identical claim elsewhere, presenting equal counts. *Accepted — exempted.* At equal
   counts the rule reads the removal as a move source; it cannot tell a coincidence from a
   move, and the AC10 demotion is the compensating visibility (the contradiction is still
   emitted, just non-gating). The **deliberate-manufacture** variant is the same case seen
   adversarially: the removal side of the diff is untrusted PR content, so a removal planted
   solely to license an added claim *does* license it. That is deliberate, and it is bounded —
   the removal side licenses **nothing beyond what these rules already grant**: it cannot
   license surplus copies (the multiplicity rule), cannot delete the row (the demotion), and
   on the referent side is narrowed — but *not* eliminated — to a same-source-file collision
   (the referent rule plus its provenance requirement; see the sub-point below, which
   corrects an earlier absolute form of this clause). Planting the bait costs the
   attacker a visible removal in the same diff a human reviews, and buys only the downgrade of
   one already-emitted diagnostic from gating to informational.
   **The referent side is subject to the same coincidence — narrowed, not eliminated.** An
   earlier draft of this record claimed the deletion-coincidence risk "cannot suppress an
   authored referent (the referent rule)". That was **false**, and review demonstrated it: the
   referent rule decides relocation by the same text identity, so a newly authored referent
   colliding with an unrelated removal read as relocated and disarmed the referent half on the
   very PR #336 count-locked shape it exists to keep gating. The provenance requirement in the
   Referent rule above is the fix; it narrows the residual to a **same-source-file** collision
   — a claim moved out of file F plus an authored referent whose full text byte-identically
   matches some line the same diff also removed from F. That residual is accepted for the same
   reason as the claim-side case (full-text identity cannot distinguish it from a genuine
   co-moved referent) and carries the same compensating visibility.
8. **Data-to-prose promotion** — bytes moved from inside a code fence into examinable prose, so
   the assertion is new even though the text is not. *Disclosed non-goal — exempted.* Deciding
   it needs the **pre-image** file state (whether the removed occurrence was itself an
   examinable prose line rather than data inside a fence), which is not derivable from the
   supplied diff. Resolving it would mean taking a pre-image ``--rev`` input, and the
   caller-supplied-diff contract below is the more valuable invariant: it is what makes this
   helper shallow-clone safe and caller-uniform across all three tiers. The ``#434`` fail-open
   discipline does not bind here precisely because no new input shape is introduced — the
   helper still reads exactly the stdin diff and the one ``--rev`` it always did.
9. **Cross-diff relocation** — a copy-then-delete split across two PRs, or a
   reverted-then-relanded extraction. *Disclosed non-goal — gates.* The grading diff is
   additions-only, so the exemption is **inert by design**: with no removed occurrence to pair
   against, grading falls back to today's behavior. This follows directly from the
   caller-supplied-diff contract (the helper grades the diff it is handed and derives no other)
   and is the correct failure direction.
10. **Referent deletion** — the claim relocates byte-for-byte while the same diff *removes* a
    line from its resolution region (an ``Expected total`` legend moved into a file whose
    adjacent enumeration the same diff shrinks). *Disclosed non-goal —
    exempted.* The referent rule examines diff-**added** referent lines; a deletion changes
    referent content too, and the PR authored that change, so this is genuine over-suppression.
    It is not fixed because the operand is not available: the rules resolve referents by
    *position in the post-diff file*, and a removed line has no post-diff position to resolve
    against, so "the diff removed a line from THIS claim's resolution region" is not decidable
    from the supplied diff: a removed line has no post-diff position *within the resolved
    referent block*, and deciding its pre-move membership of that block needs pre-image block
    identity — the same operand case 8 lacks and the caller-supplied-diff contract forecloses.
    (The narrower claim is deliberate: a deletion's post-image insertion point *is* derivable
    from ``post_ln``; what is not derivable is whether the deleted line belonged to this
    claim's referent block.) This is why the Referent rule above is worded
    "adds no un-relocated referent" rather than "leaves the referent unchanged". The demoted row
    is still emitted, so the contradiction stays visible.
11. **Block merge** — the inverse of case 2: two source blocks consolidated into one
    destination. *Disclosed non-goal — exempted.* Every line is a byte-identical relocation and
    every diff-added referent is itself relocated with shared provenance, so both rules pass —
    yet a ``Cases 1-2`` header can be newly false because the PR authored the *co-location*.
    Deciding it needs pre-image block identity (case 8's missing operand again), so a routine
    consolidation refactor is exempted. Recorded rather than fixed, and reachable without any
    bait removal or unrelated file.

**Caller-supplied-diff contract (shallow-clone safe).** The helper reads the
unified diff from **stdin** and resolves post-diff file state through the explicitly
selected post-image mode — ``--rev`` (``git show <rev>:<path>``), or the issue-#818
``--worktree`` mode, whose record above is authoritative for it; this paragraph's
``--rev`` wording describes the revision mode and is not a claim that it is the only
one. Both modes are shallow-clone safe, and the working-tree mode makes no history
read at all. It never derives the diff range
itself (no base..head range computation) and never calls the range-deriving git
plumbing — the caller passes the diff it already computed (the review engine's
cached ``diff.patch``; the fix loop's branch diff). This is what makes the PR #328
shape detectable on every invocation: a claim line added by an *earlier* commit of
the branch whose referent a *later* commit outgrew is still in the supplied diff's
added set, and the post-diff file (``--rev``) shows the grown referent — no fix
commit ever has to touch the frozen header for the staleness to surface.

Output: one TSV row per examined claim on stdout —
``verdict<TAB>rule<TAB>file<TAB>line<TAB>detail`` — with ``verdict`` one of
``VERIFIED`` / ``STALE`` / ``UNRESOLVABLE``.

Exit codes:
  0  no STALE row (all VERIFIED / UNRESOLVABLE, or no claims at all)
  1  at least one STALE row
  2  internal error — an unreadable ``--rev`` (revision mode only; the working-tree mode
     validates no revision), an unreadable or non-UTF-8 stdin diff, a missing or duplicated
     post-image mode flag (argparse's own usage exit), or any other unexpected failure
     (e.g. ``git`` unavailable); all fail-closed
UNRESOLVABLE rows never affect the exit code.

Usage (exactly one post-image mode, always required):
    stale-prose-lint.py --rev REV   < unified.diff   # post-image = git show <rev>:<path>
    stale-prose-lint.py --worktree  < unified.diff   # post-image = the on-disk file (#818)
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from collections import Counter
from types import MappingProxyType
from typing import NamedTuple

# Operator tokens R4 is restricted to. A backticked token outside this set is an
# arbitrary named identifier and is deliberately never examined (the false-positive
# boundary): the operator-token restriction is the only shipped R4 operating point.
OP_TOKENS = frozenset({">", ">>", "<", "<<", "|", "||", "&&", "&", "|&", "2>", "2>>", "&>"})

# A deny-absolute marker on the claim line (case-insensitive, word-ish boundaries).
_DENY_RE = re.compile(
    r"(?i)\b(never|no|not|none|any|forbid|forbidden|forbids|banned|bans|"
    r"deny|denies|denied|disallow|disallowed|must\s+not|cannot|can't|don't|do\s+not)\b"
)
# A permit marker anywhere else in the post-diff file (case-insensitive).
_PERMIT_RE = re.compile(
    r"(?i)\b(permit|permits|permitted|permissible|allow|allows|allowed|"
    r"sanction|sanctions|sanctioned|grant|grants|granted)\b"
)

_RANGE_RE = re.compile(r"\bCases?\s+(\d+)\s*[-–—]\s*(\d+)\b")
_CASE_ITEM_RE = re.compile(r"\bCase\s+(\d+)\b")
_TOTAL_RE = re.compile(r"\bExpected\s+total\s*[=:]\s*(\d+)\b", re.IGNORECASE)
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\S")
# A leading line-comment marker, stripped from a REFERENT line before it is tested for
# enumeration-item shape. Load-bearing: the claims these rules resolve live in comment blocks,
# so their enumerations do too — PR #320's legend bullets are `#   - inline_missing: …`, and
# `_LIST_ITEM_RE` is anchored, so without this strip `_adjacent_list_idxs` returns empty on the
# very defect R2 exists to catch (a non-gating UNRESOLVABLE, exit 0 — a silent false negative;
# only a *bare*-bullet legend, which the historical defect never was, ever resolved).
# Deliberately only `#` and `//`: `*` is EXCLUDED because it is itself a markdown bullet
# marker, so stripping it would turn a real `* item` enumeration into a non-item and break the
# count in the opposite direction.
_COMMENT_PREFIX_RE = re.compile(r"^\s*(?:#+|//+)\s?")


def _uncomment(line):
    """A referent line with its leading line-comment marker removed (if any)."""
    return _COMMENT_PREFIX_RE.sub("", line, count=1)
_ASSERT_LINE_RE = re.compile(r"(?i)\bassert\w*\b")
# The gating R3 noun set — shared as one constant so the recognition tier's _RECOG_NOUN
# below cannot silently drift from the gating _COUNT_RE (a new noun added here reaches both).
_COUNT_NOUNS = r"assertions?|asserts?|checks?|bullets?|items?|entries?|cases?"
# The numeral lookbehind, shared by the gating _COUNT_RE and the recognition _RECOG_NUM below as
# ONE constant (the same single-source discipline _COUNT_NOUNS carries) so the two tiers' guard
# against a numeral glued to ``#`` / ``§`` / a digit / ``.`` / ``-`` cannot silently drift — the
# exact drift issue #1405 closed. Kills ``#402`` references, ``§2.3`` section numbers, decimals.
_NUM_LOOKBEHIND = r"(?<![#§\d.\-])"
# The gating R3 pattern carries two guards the non-gating recognition tier already ships (issue
# #1405): the trigger noun must be PLURAL, and the numeral must clear _NUM_LOOKBEHIND — see the
# module-header R3 spec for the rule and its disclosed plural-ordinal residual. Both live HERE,
# on the compiled pattern, leaving _COUNT_NOUNS byte-identical: the recognition tier interpolates
# that constant and must keep recognising singular nouns. The plural alternation is derived from
# _COUNT_NOUNS (the single source of nouns) by promoting each optional-plural ``s?`` to ``s``.
_COUNT_NOUNS_PLURAL = _COUNT_NOUNS.replace("s?", "s")
_COUNT_RE = re.compile(rf"{_NUM_LOOKBEHIND}\b(\d+)\s+({_COUNT_NOUNS_PLURAL})\b", re.IGNORECASE)
# ── R3 recognition-only tier (issue #439), non-gating ──────────────────────────────────
# Spelled-out numeral words two..twelve → their integer value. "one" is deliberately absent
# (idiom-heavy) and thirteen+ is out of scope; see the module header's recognition-tier records.
_WORD_NUM = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
# The widened noun set: the gating _COUNT_NOUNS (in their ``s?`` forms, interpolated so the
# gating surface stays byte-identical and cannot drift) plus the nine new nouns, matched
# PLURAL-ONLY so a singular ("tag", "rule") never trips the recognition.
_RECOG_NOUN = (
    r"(?:" + _COUNT_NOUNS + r"|tags|members|fields|rows|columns|arms|files|rules|sites)"
)
# A single intervening modifier token: a bare word, optionally wrapped in ``**…**`` / ``*…*`` /
# backticks, followed by whitespace. Because the word body is ``[A-Za-z][\w'-]*`` (no sentence
# punctuation), a token carrying a comma/period/colon cannot form a modifier — it structurally
# breaks the match, which is how the "sentence punctuation disqualifies" guard is realised.
_RECOG_MOD = r"[*`]{0,2}[A-Za-z][\w'-]*[*`]{0,2}\s+"
# The word alternation is DERIVED from _WORD_NUM (single source of truth) so the regex and the
# value map can never drift — a word the regex matched but the map lacked would KeyError. The
# ``\b`` anchors on the alternation below make alternative order irrelevant.
_WORD_ALT = "|".join(_WORD_NUM)
# The numeral: a word numeral (bounded) OR a digit run, guarded by the shared _NUM_LOOKBEHIND
# above (NOT directly preceded by ``#`` / ``§`` / a digit / ``.`` / ``-``) — one source with the
# gating _COUNT_RE, so the two tiers' numeral guard cannot drift (issue #1405).
_RECOG_NUM = _NUM_LOOKBEHIND + r"(?:\b(?P<word>" + _WORD_ALT + r")\b|(?P<digit>\d+))"
_RECOG_RE = re.compile(
    _RECOG_NUM + r"\s+(?P<mods>(?:" + _RECOG_MOD + r"){0,2})(?P<noun>" + _RECOG_NOUN + r")\b",
    re.IGNORECASE,
)
# Modifier words that disqualify the recognition (partitives / conjunctions).
_RECOG_MOD_DISQUALIFY = frozenset({"of", "per", "and", "or"})

# Two-item enumeration: "a X and a Y" plus a "both" summary → asserts exactly 2.
_TWO_ITEM_RE = re.compile(r"(?i)\ba\b\s+\S.*\band\b\s+\ba\b\s+\S")
_BOTH_RE = re.compile(r"(?i)\bboth\b")
_BACKTICK_RE = re.compile(r"`([^`]+)`")
# Illustrative-example opt-out (issue #635). A prose/comment line carrying this marker DESCRIBES a
# claim shape rather than asserting it, so `examine_file` skips all gating rules for it (emitting a
# single non-gating audit row so the suppression stays visible in the output). Matched as a plain
# substring (optional whitespace after the colon) so it is language-agnostic; the trailing
# `(?![\w-])` pins the exact token so `examples` / `example-driven` do not incidentally opt a line
# out. See the module header's #635 design record for the mechanism and disclosed non-goals.
def _marker_re(token):
    """The shared opt-out-marker grammar: the plain `stale-prose-lint: <token>` substring with a
    trailing negative lookahead pinning the exact token (so `examples` / `rule-texts` do not opt a
    line out), matched case-insensitively and independent of comment syntax. One owner, because the
    lookahead is the property every marker must keep identical — a hand-mirrored second copy is the
    coupled pair that drifts."""
    return re.compile(rf"stale-prose-lint:\s*{token}(?![\w-])", re.IGNORECASE)


_EXAMPLE_MARKER_RE = _marker_re("example")

# ── Coverage-universal recognition tier (issue #818), non-gating ───────────────────────
# The two closed sets below are the tier's authoritative shape; the module header is their
# authoritative spec. Kept as module-level constants for the same reason `_COUNT_NOUNS` is:
# one place to read, one place to change.
# The coverage-scope tokens — exactly these, complete by construction. Deliberately broader
# than "universal quantifier": `only` / `complete` / `entire` / `whole` are scope claims rather
# than universals, and are recognised because a scope claim about the change's own coverage
# needs grounding for the same reason a universal does.
_CU_QUANT = r"(?:every|all|each|any|both|no|none|exactly|only|complete|entire|whole)"
# The coverage-referent nouns — exactly these, complete by construction. Each matches singular
# or plural. `call site` is expressed as an OPTIONAL prefix on `site` rather than as a separate
# earlier alternative, so the alternation is order-independent: a leftmost-first `|` cannot let
# a bare `sites?` claim `call site`'s tail and misname the reported referent. The issue-#1451
# additions — `row` / `entry` / `population` / `partner` / `helper` — are the referent nouns the
# recurring `incomplete-edit` failures actually used; `entr(?:y|ies)` spells the irregular plural
# rather than relying on `s?`.
_CU_NOUN = (
    r"(?:(?:call )?sites?|arms?|branch(?:es)?|cases?|paths?|files?|rules?|peers?"
    r"|consumers?|callers?|members?|mirrors?|occurrences?|instances?|surfaces?"
    r"|checkpoints?|rows?|entr(?:y|ies)|populations?|partners?|helpers?)"
)
# Up to two intervening bare-word modifiers, matched by the CU-local `_CU_MOD` below (a widened
# sibling of `_RECOG_MOD`'s shape) so a token carrying sentence punctuation structurally breaks
# the match, while a leading hyphen / backtick-hyphen no longer does. Deliberately NOT routed through
# `_mods_ok`: that guard disqualifies a NUMERAL-shaped modifier, which is correct for the R3
# count tier (where the numeral IS the claim) but wrong here — `all four arms` is precisely the
# coverage universal this tier exists to surface, and disqualifying it would blind the tier to
# the issue's own worked example.
# The quantifier carries the same `**…**` / `*…*` / backtick emphasis tolerance `_RECOG_MOD`
# already gives a modifier token. Without it the tier misses `**every** call site` entirely.
# A repo-wide search at authoring time returned 16 emphasised occurrences against 515 bare
# ones, so this is a real minority shape rather than the majority one — it is recognised
# because a missed line is a line the sweep never grades, not because it is the common form.
# The CU-local modifier (issue #1451): `_RECOG_MOD` requires each intervening modifier to begin
# `[*`]{0,2}[A-Za-z]`, so a `-x`-gated token beginning with a backtick-hyphen structurally breaks
# the match and blinds the tier to `#1316`'s own worked example. This sibling tolerates a leading
# hyphen (and an internal backtick/hyphen run) so such a modifier is spanned. It is used ONLY by
# `_CU_RE`; `_RECOG_MOD` is left byte-identical because it is shared with the gating-adjacent R3
# recognition tier and must not drift. Only the two class widenings are load-bearing: a leading
# `-` in the mandatory class, and `` ` `` in the inner run (for the `` ` `` inside `x`-gated`); a
# leading backtick is already absorbed by the `[*`]{0,2}` emphasis wrapper, so it is NOT repeated
# in the mandatory class.
_CU_MOD = r"[*`]{0,2}[-A-Za-z][\w'`-]*[*`]{0,2}\s+"
_CU_RE = re.compile(
    r"[*`_]{0,2}\b" + _CU_QUANT + r"\b[*`_]{0,2}\s+(?:" + _CU_MOD + r"){0,2}"
    + _CU_NOUN + r"\b",
    re.IGNORECASE,
)
# Declared opt-out for the coverage-universal tier (issue #818). Built from the same
# `_marker_re` grammar as the example marker, so the two cannot drift. Scoped to THIS tier only
# — it never disarms a gating rule (see the module header's #818 record).
_RULE_TEXT_MARKER_RE = _marker_re("rule-text")

# Verdict tokens as module constants, referenced by every emit site AND the exit-code gate
# (``verdict == STALE`` in ``run``). The process exit code hinges on the STALE literal
# matching identically everywhere it is produced and compared; a bare repeated string would
# fail OPEN on a typo (a mistyped ``"STAEL"`` at one append site silently drops that row from
# the exit-code tally → the lint reports a clean pass on real staleness — the exact fail-open
# a fail-safe lint must not have). A constant turns that typo into a ``NameError`` at import.
# The working-tree post-image mode selector (issue #818). A DISTINCT sentinel rather than
# `None`, for the same reason the verdict tokens below are constants rather than bare strings:
# `None` on a parameter named `rev` reads as "unset" to every Python caller, so an embedding
# caller threading an absent config value — `run(cfg.get("rev"), diff)` — would silently select
# working-tree mode AND skip the only validation this helper has. With a distinct object, an
# accidental `None` resolves to no mode at all and fails loudly instead.
WORKTREE = object()

VERIFIED = "VERIFIED"
STALE = "STALE"
UNRESOLVABLE = "UNRESOLVABLE"

# The detail prefix every issue-#629 demoted row carries. A demotion is DELETION-FREE by
# contract: the original STALE diagnostic follows this prefix verbatim, so the co-located
# contradiction stays readable in Phase 0.6's informational channel and the fix loop's
# `stale_prose_check` record even though it no longer gates.
RELOCATED_PREFIX = (
    "relocated byte-identically in this diff (move-aware exemption, issue #629 — "
    "STALE demoted to non-gating): ")


class Row(NamedTuple):
    """One TSV verdict row. A NamedTuple (not a bare 5-tuple) so each field is named at every
    construction site and the arity is pinned structurally — a wrong-arity append is a
    construction-time error, not a silent positional-unpack drift. (Deliberately no count of
    those sites here: an unpinned exact count is the very claim this lint exists to catch, and
    this repo's pin-or-don't-write policy says don't write it.)"""

    verdict: str
    rule: str
    path: str
    line: int
    detail: str


class InternalError(Exception):
    """Raised for a fail-closed exit-2 condition — an unreadable/unresolvable ``--rev``
    (validated up front in ``run``). A general ``git show`` non-zero does NOT raise this:
    it returns None -> UNRESOLVABLE; an unavailable ``git`` binary raises
    ``FileNotFoundError``, caught by ``main``'s catch-all. This is the single raise site."""


# ── Line scoping (issue #434) ─────────────────────────────────────────────────────────
# A claim is prose. A line of CODE that merely *contains* claim-shaped text — a shell
# fixture string, an assertion name — is data, not an assertion about the file, and grading
# it is the helper's dominant false-positive source. These tables decide which lines can
# carry a claim, per file type.
#
# The `None` (unrecognised) arm is the load-bearing one: it FAILS OPEN to "examine every
# line" — today's behavior — never to "examine nothing". A closed allowlist would silently
# reduce a consumer repo in an unlisted language to a permanent no-op (empty TSV, exit 0,
# forever) while the docs still advertised the check. A file type we forgot must degrade to
# the status quo, not to no checking.
_PROSE_EXTS = frozenset({".md", ".markdown", ".mdx", ".rst", ".adoc", ".txt"})
_HASH_EXTS = frozenset({".sh", ".bash", ".zsh", ".yml", ".yaml", ".jq", ".toml",
                        ".rb", ".tf", ".ini", ".cfg"})
_HASH_BASENAMES = frozenset({"makefile", "dockerfile"})
_SLASH_EXTS = frozenset({".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".c", ".h",
                         ".cpp", ".cc", ".hpp", ".cs", ".swift", ".kt", ".scala", ".php"})
# A fence opener/closer: >=3 backticks or >=3 tildes. The RUN LENGTH is captured because a
# fence closes only on a run of the SAME character that is at least as long as its opener —
# which is what lets a 4-backtick fence wrap 3-backtick examples (CLAUDE.md does exactly
# this). A naive "toggle on any ```" inverts state for the rest of the file: mass mis-scoping
# in BOTH directions at once.
_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")

_unrecognised_exts = set()  # reported once, at the end of the run (see `run`)

# ── Excluded population: machine-appended corpora (issue #672) ─────────────────────────
# Path prefixes whose diff-added lines are never examined. See the module header for the
# rationale and for the two neighbours (`.changeset/`, `CHANGELOG.md`) deliberately NOT
# listed. This is a closed list of PATHS, not of languages: the fail-open rule above governs
# an unrecognised file TYPE, and nothing here changes it.
#
# The third entry is a FILE, not a directory. `lib/test/mutation-pin-corpus-adjudications.tsv`
# is rendered output of `lib/test/mutation-pin-census.py --format adjudication-tsv`, and it
# lives beside its generator rather than under `.prflow/logs/` (where its `master_sha256`
# counterpart, the mutation-pin corpus inventory, does sit). Its `logical_call` column embeds each
# censused pin's source text verbatim — pin names included, and many of those carry counts —
# so the count-locked rule resolves a quoted numeral against the surrounding TSV rows, which
# are not that claim's referent. That is exactly the issue-#672 shape: a machine-rendered
# record quoting prose as DATA, with no referent in the post-diff state to resolve against.
_EXCLUDED_PREFIXES = (".prflow/learnings/", ".prflow/logs/")
_EXCLUDED_FILES = frozenset(
    {"lib/test/mutation-pin-corpus-adjudications.tsv"}
)


def _is_excluded(path):
    """True when `path` is an exact corpus file or sits under a corpus prefix."""
    normalized = path.replace("\\", "/")
    return (
        normalized in _EXCLUDED_FILES
        or normalized.startswith(_EXCLUDED_PREFIXES)
    )


def _norm_line(line):
    """A line with its trailing CR and a leading UTF-8 BOM removed.

    A CRLF file (routine in a consumer Windows repo) otherwise leaves ``\\r`` on every line,
    so a fence marker reads as ``` + CR`` and never matches — the whole file's code blocks
    would be scoped as prose. A BOM is not whitespace to ``str.strip()``, so it hides a
    leading ``#`` and silently un-examines the first comment of the file."""
    return line.lstrip("﻿").rstrip("\r")


def _path_kind(path):
    """'prose' | 'hash' | 'slash' | 'py' | None (unrecognised -> examine every line)."""
    base = path.rsplit("/", 1)[-1].lower()
    if base in _HASH_BASENAMES:
        return "hash"
    dot = base.rfind(".")
    if dot <= 0:  # no extension (or a dotfile like `.gitignore`)
        _unrecognised_exts.add(base if dot < 0 else base[dot:])
        return None
    ext = base[dot:]
    if ext == ".py":
        return "py"
    if ext in _PROSE_EXTS:
        return "prose"
    if ext in _HASH_EXTS:
        return "hash"
    if ext in _SLASH_EXTS:
        return "slash"
    _unrecognised_exts.add(ext)
    return None


def _fenced_mask(lines):
    """True for each line that sits INSIDE a fenced code block (the fence markers included).

    An UNCLOSED fence fails OPEN: its opener is not treated as a fence at all, so the rest of
    the file stays prose. The alternative — treating everything after a stray backtick run as
    code — would silently un-examine the tail of a file, a false negative created by a typo.
    """
    inside = [False] * len(lines)
    open_at = None
    marker = ""
    for i, raw in enumerate(lines):
        m = _FENCE_RE.match(_norm_line(raw))
        if not m:
            continue
        run = m.group(1)
        if open_at is None:
            open_at, marker = i, run
        elif run[0] == marker[0] and len(run) >= len(marker):
            for j in range(open_at, i + 1):
                inside[j] = True
            open_at, marker = None, ""
    return inside  # an unclosed opener leaves its region False — fail open


def _py_docstring_mask(lines, path):
    """True for each line inside a module/class/function docstring.

    The helper's own counted claims live in docstrings, so `#`-comments-only scoping would
    lose them. Resolved with the stdlib ``ast`` over the post-diff file rather than by
    counting triple quotes: a naive quote-toggle classifies ANY triple-quoted string as a
    docstring, so fixture data in a test file (claim-shaped text inside a string literal)
    would be examined — re-creating in Python the exact false-positive class this change
    removes from shell. On a file that does not parse in the post-image the mask is empty
    (`#`-comments only) and a breadcrumb says so — never a silent skip. The breadcrumb names
    the post-image rather than a flag: under the issue-#818 working-tree mode no ``--rev`` was
    passed, and naming it would misdirect the reader to an input the invocation never had —
    the pre-commit window in which a half-written ``.py`` does not parse is exactly that
    mode's population."""
    mask = [False] * len(lines)
    try:
        tree = ast.parse("\n".join(lines))
    except (SyntaxError, ValueError) as exc:
        sys.stderr.write(
            f"stale-prose-lint.py: {path} does not parse in the post-image ({type(exc).__name__}); "
            f"scoping it to '#' comments only (docstring claims in this file are not "
            f"examined)\n")
        return mask
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            continue
        start = getattr(first, "lineno", 0) - 1
        end = getattr(first, "end_lineno", start + 1) - 1
        for j in range(max(start, 0), min(end + 1, len(mask))):
            mask[j] = True
    return mask


def prose_mask(path, lines):
    """Per-line 'may carry a claim' mask for ``path``, or None to examine every line.

    None (the unrecognised-type arm) means FAIL OPEN — see the table above."""
    kind = _path_kind(path)
    if kind is None:
        return None
    if kind == "prose":
        return [not inside for inside in _fenced_mask(lines)]
    if kind == "hash":
        return [_norm_line(ln).lstrip().startswith("#") for ln in lines]
    if kind == "py":
        doc = _py_docstring_mask(lines, path)
        return [doc[i] or _norm_line(ln).lstrip().startswith("#")
                for i, ln in enumerate(lines)]
    # slash: `//` line comments plus `/* … */` block-comment interiors.
    mask = []
    in_block = False
    for ln in lines:
        text = _norm_line(ln).lstrip()
        if in_block:
            mask.append(True)
            if "*/" in text:
                in_block = False
            continue
        if text.startswith("/*"):
            mask.append(True)
            if "*/" not in text[2:]:
                in_block = True
            continue
        mask.append(text.startswith("//"))
    return mask


def _may_carry_claim(mask, idx):
    """True when line index ``idx`` may carry a claim. A None mask examines everything."""
    if mask is None:
        return True
    return 0 <= idx < len(mask) and mask[idx]


def _run_git(args):
    """Run a git command, returning (rc, stdout_text, stderr_text). Never raises on non-zero.

    ``stderr_text`` is returned, not discarded, so a caller that degrades on a non-zero rc
    can carry git's own reason in its breadcrumb instead of collapsing every failure into
    an unexplained verdict.

    Decode git output with an explicit ``utf-8`` codec and ``errors="replace"`` —
    NEVER the locale-default codec ``text=True`` would pick. Under a ``C``/``POSIX``
    locale (common in CI containers and the cloud sandbox) that default is strict
    ASCII, so ``git show <rev>:<path>`` of any file carrying a non-ASCII byte (an
    en/em-dash, Latin-1, a UTF-8 BOM) would raise ``UnicodeDecodeError`` and abort
    the *entire* lint to exit 2 — masking every other file's verdict, including a
    real STALE. ``errors="replace"`` keeps a single odd byte in one reviewed file
    from detonating the whole pass at *decode* time (that file is still examined — a
    stray replacement char cannot manufacture a false countable claim); ``main``
    likewise reconfigures the output streams to ``utf-8``/``errors="replace"`` so
    emitting that byte cannot detonate the pass at *write* time either — so an odd byte
    in a reviewed file body does not detonate the pass through the git-show *read* or
    the stdout *write*. (A reviewed file's *invalid*-UTF-8 bytes can still reach exit 2
    by a third, intentional channel — the strict stdin-diff decode in ``main``, which
    treats a non-UTF-8 diff as a caller error; see the module header's Exit codes list,
    the single exit-2 catalog.)"""
    proc = subprocess.run(
        ["git", *args],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout, proc.stderr


def _unquote_path(target):
    """Decode git's C-quoted path form (``"b/caf\\303\\251.md"``) back to real text.

    With the default ``core.quotepath``, a non-ASCII path is emitted quoted and
    octal-escaped. Left as-is, the quotes and escapes reach ``git show`` (which then fails)
    and the extension test (which sees a trailing ``"`` and no known suffix) — so the file
    would land on the unrecognised arm for a reason that has nothing to do with its type."""
    if not (len(target) >= 2 and target.startswith('"') and target.endswith('"')):
        return target
    try:
        raw = target[1:-1].encode("latin-1").decode("unicode_escape").encode("latin-1")
        return raw.decode("utf-8", errors="replace")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return target[1:-1]


def parse_diff(diff_text):
    """Return {path: {post_lineno: added_text}} from a unified diff.

    The post-image half of :func:`parse_diff_full` — see it for the parsing contract.
    Kept as the narrow public shape so the #424 test corpus needs no edit; `run()` itself
    calls `parse_diff_full` directly, so the discarded removed-tally costs production
    nothing."""
    return parse_diff_full(diff_text)[0]


def parse_diff_full(diff_text):
    """Return the 3-tuple ``(files, removed, removed_by_file)``, where ``files`` is
    ``{path: {post_lineno: added_text}}``, ``removed`` is ``Counter(removed_text -> n)``
    tallied diff-globally, and ``removed_by_file`` is ``{src_path: Counter(removed_text
    -> n)}`` — the per-source-file provenance map the Referent rule's same-source-file
    narrowing depends on. Callers wanting only the post-image use :func:`parse_diff`.

    Both images are tracked: each ``+`` line is recorded against its post-image line
    number, and each ``-`` line's raw text is tallied into the diff-global removed
    multiset the move-awareness exemption (issue #629) pairs additions against, and
    additionally into that removal's own source path in ``removed_by_file``. The
    diff-global ``removed`` tally is **path-independent** by design — a relocation's
    source and destination are different files — so it is collected even from a hunk
    whose target is ``/dev/null`` (a wholly deleted source file, the commonest
    extraction shape: without this, the exemption would never fire on the very move it
    exists for).

    A hunk is "open" while **either** image still owes lines, so a pure-deletion hunk
    (``@@ -1,3 +0,0 @@``, whose post-image budget is 0 from the start) is consumed as
    content rather than falling through to the between-hunks arm.

    Structure and content are told apart by the hunk's own **image budgets**
    (``@@ -a,b +c,d @@`` promises exactly ``d`` post-image lines), not by a bare
    prefix test on each line. This is load-bearing twice over. First, a *content*
    line whose own text begins with ``++ `` is emitted in the diff as ``+++ ``: a
    prefix-only parser reads it as the next file header and silently retargets every
    later claim in the diff onto a phantom path. Second, the real callers (the engine's
    Phase 0.6 and the fix loop's pre-check) feed a ``base...HEAD`` diff — many hunks,
    interleaved context and ``-`` deletions, post-image starts well past 1 — where the
    ``post_ln`` bookkeeping is what aligns each claim with its referent; an off-by-one
    there does not fail loudly, it silently degrades real STALE rows to UNRESOLVABLE.
    A ``-`` line consumes pre-image budget only, so it never advances ``post_ln``.
    """
    files = {}
    removed = Counter()
    removed_by_file = {}
    path = None
    src_path = None
    added = None
    post_ln = 0
    budget = 0      # post-image lines still owed by the current hunk
    pre_budget = 0  # pre-image lines still owed (both 0 = between hunks)
    for line in diff_text.split("\n"):
        # A content line always carries a ``+``/``-``/space prefix (or is empty), so an
        # unprefixed ``@@`` or ``diff --git`` at column 0 is structure even mid-hunk: resync
        # on it rather than letting an overstated/truncated hunk count silently swallow the
        # next hunk (or file) header — which would drop every claim after it. Note the same
        # argument does NOT hold for ``+++ ``/``--- ``: those ARE reachable as content (a
        # ``++ ``-leading added line renders as ``+++ ``), which is why the budget, not a
        # prefix test, decides those.
        in_hunk = budget > 0 or pre_budget > 0
        if in_hunk and (line.startswith(("@@", "diff --git "))):
            budget = pre_budget = 0
            in_hunk = False
        if not in_hunk:
            if line.startswith("--- "):
                # The SOURCE path — the file each following `-` line was removed FROM. Only
                # reachable as structure here (the budget guard above means a `-- `-leading
                # removed line, which renders as `--- `, is consumed as content instead), so
                # this mirrors the `+++ ` handling exactly. Needed for move PROVENANCE: see
                # `MoveIndex`.
                src = line[4:].strip()
                if src == "/dev/null":
                    src_path = None
                else:
                    src = _unquote_path(src)
                    src_path = src.removeprefix("a/")
                continue
            if line.startswith("+++ "):
                target = line[4:].strip()
                if target == "/dev/null":
                    path = None
                    added = None
                    continue
                target = _unquote_path(target)
                # Strip a leading "b/" (git) prefix.
                path = target.removeprefix("b/")
                added = files.setdefault(path, {})
                continue
            if line.startswith("diff --git "):
                # Reset the source path at every file boundary. Without this, a section
                # carrying no `--- ` header inherits the PREVIOUS file's path and its
                # removals are attributed there — a false provenance record, which is worse
                # than a missing one because the referent rule's intersection can be
                # satisfied by it. An unattributed removal (src_path None) only fails toward
                # gating; a misattributed one fails open.
                src_path = None
                continue
            if line.startswith("@@"):
                m = re.search(r"\+(\d+)(?:,(\d+))?", line)
                if m:
                    post_ln = int(m.group(1))
                    # An absent count means a one-line post image ("@@ -1 +1 @@").
                    budget = int(m.group(2)) if m.group(2) is not None else 1
                    pm = re.search(r"-(\d+)(?:,(\d+))?", line)
                    pre_budget = (int(pm.group(2)) if pm.group(2) is not None else 1) if pm else 0
                else:
                    # The post-image side does not parse, so nothing in this hunk can be
                    # numbered. Fail CLOSED — zero BOTH budgets so the hunk stays shut,
                    # rather than letting a parsed pre-image side hold it open and record
                    # added lines at fabricated numbers from 0 (which would both anchor
                    # claims on arbitrary lines and, by colliding `added` keys, UNDERCOUNT
                    # occurrences and bias multiplicity toward granting the exemption).
                    post_ln = 0
                    budget = 0
                    pre_budget = 0
                    sys.stderr.write(
                        "stale-prose-lint.py: unparseable post-image hunk header, hunk "
                        f"skipped: {' '.join(line.split())[:80]}\n")
                continue
            continue  # "diff ", "index ", and any other between-hunk noise
        if line.startswith("+"):
            # `added` is None only for a /dev/null target — a wholly deleted file, which
            # contributes no post-image content but whose budget must still be spent.
            if added is not None:
                added[post_ln] = line[1:]
            post_ln += 1
            budget -= 1
        elif line.startswith("-"):
            removed[line[1:]] += 1  # raw bytes — identity, not the scoping normalisation
            if src_path is not None:
                removed_by_file.setdefault(src_path, Counter())[line[1:]] += 1
            pre_budget -= 1
        elif line.startswith("\\"):  # "\ No newline at end of file" — not a line of either image
            continue
        else:  # context line (leading space, or an empty line)
            post_ln += 1
            budget -= 1
            pre_budget -= 1
    return files, removed, removed_by_file


class MoveIndex(NamedTuple):
    """The diff-global move bookkeeping the issue-#629 exemption reads.

    ``relocated`` is the multiplicity verdict — the set of added line texts whose added
    occurrences do not outnumber their removed ones. ``sources`` maps each removed text to
    the set of source paths it was removed FROM, which is the **provenance** operand: it is
    what lets the referent rule require a referent to have come from a file that also gave
    up the claim, rather than from anywhere at all in the diff.

    Why provenance is needed (issue #629 review). Relocation identity is full-line text
    equality, and referent lines are exactly the shape most likely to be non-unique
    boilerplate — an assertion line, a bullet, a ``Case N`` row. Without provenance, a
    **newly authored** referent is read as "relocated" whenever *any* unrelated hunk anywhere
    in the diff happens to remove a byte-identical line, which silently disarms the referent
    half of the exemption on the very shape (the PR #336 count-locked defect) it exists to
    keep gating. Requiring a shared source file does not make coincidence impossible, but it
    narrows it from "collides with any removal in the diff" to "collides with a removal in a
    file this claim also moved out of" — and the residual is recorded as a disclosed case in
    the design record above."""

    #: Added line texts whose added occurrences do not outnumber their removed ones.
    relocated: frozenset[str]
    #: Removed line text -> the source paths it was removed FROM. :func:`build_move_index`
    #: is the sanctioned constructor and wraps this in a read-only ``MappingProxyType``, so
    #: the immutability the tuple advertises holds for every index the helper builds. Direct
    #: construction is deliberately still permitted (the empty-inert literal in ``grade`` and
    #: the unit tests both use it) and is NOT gated: the invariants live in the constructor,
    #: and every consumer here reads through ``.get``/``in`` only.
    sources: dict[str, frozenset[str]]


def build_move_index(files, removed, removed_by_file):
    """Assemble the :class:`MoveIndex` for one supplied diff."""
    sources = {}
    for src, counter in removed_by_file.items():
        for text in counter:
            sources.setdefault(text, set()).add(src)
    return MoveIndex(frozenset(relocated_texts(files, removed)),
                     MappingProxyType({t: frozenset(p) for t, p in sources.items()}))


def relocated_texts(files, removed):
    """The set of added line texts exempt as byte-identical relocations (issue #629).

    The multiplicity rule in one expression: a text is exempt only when its diff-global
    added occurrences do not outnumber its removed ones. ``n >= 1`` always holds for a
    key of the added tally, so an absent removal (0) can never satisfy the comparison —
    an additions-only diff (the cross-diff-relocation non-goal) yields an empty set and
    the exemption is inert, exactly as designed."""
    added_counts = Counter()
    for added in files.values():
        for text in added.values():
            added_counts[text] += 1
    return {text for text, n in added_counts.items() if removed.get(text, 0) >= n}


def _referents_relocated(added, move, claim_sources, idxs, lines=None):
    """True when the referent rule permits the exemption for a claim (issue #629).

    ``idxs`` are the 0-based indices of the post-diff lines this claim's rule resolved as
    its referent content. A referent line the diff did **not** add is pre-existing content
    — unchanged by this diff — and imposes no obligation; a diff-added one must itself be a
    byte-identical relocation, or the claim's staleness was authored by this PR.

    **The absent operand fails CLOSED (issue #629 review).** ``idxs`` index the post-diff
    *file* (``lines``) while ``added`` is keyed by post-image *diff* line numbers, so a
    lookup miss has two very different causes that must not be conflated: the referent is
    genuinely pre-existing (no obligation — the innocent case), or the two numberings do not
    correspond and the join is meaningless (``parse_diff_full``'s own docstring notes an
    off-by-one degrades silently). Reading the second as the first is the CLAUDE.md
    unverified-assumption class — a guard whose comparand can be absent failing open exactly
    where it claims to fail closed — so when ``lines`` is supplied the "pre-existing" arm is
    taken only after **confirming the join corresponds**: the diff must record no added text
    at that post-image number AND the file's own line there must be readable. Any
    inconsistency denies the exemption (returns False), which fails toward gating.

    **Correspondence is compared through ``_norm_line``, identity is not.** The two operands
    reach us through channels that disagree about line endings: the diff arrives as raw bytes
    (``sys.stdin.buffer`` + an explicit decode, so a CRLF file's ``+`` lines keep their
    ``\\r``), while ``lines`` comes from ``_run_git``, whose ``encoding=`` argument enables
    Python's universal-newline translation and silently rewrites ``\\r\\n`` to ``\\n``. A raw
    comparison across that boundary therefore fails on **every** line of a CRLF file and would
    deny the exemption wholesale on Windows consumer repos. Correspondence asks "is this the
    same line?", so it is the right place to absorb that known representational difference;
    relocation *identity* (``text not in relocated``) stays raw, because there both operands
    come from the same channel — the diff's own two sides — and full-byte identity is the
    contract."""
    for idx in idxs:
        text = added.get(idx + 1)
        if text is not None:
            if text not in move.relocated:
                return False
            # PROVENANCE: the referent must have been removed from a file that also gave up
            # the claim. Text identity alone cannot tell a genuine co-moved referent from a
            # newly authored one that happens to match an unrelated removal elsewhere in the
            # diff; a shared source narrows that coincidence to the same-file case.
            if not (move.sources.get(text, frozenset()) & claim_sources):
                return False
            # A corresponding join is one where the diff's recorded added text IS the file's
            # line at that index. A mismatch means the numbering is skewed, so this "relocated"
            # verdict was read off the wrong line — deny rather than trust it.
            if lines is not None and (idx >= len(lines)
                                      or _norm_line(lines[idx]) != _norm_line(text)):
                return False
            continue
        # No added text at this post-image number: the innocent reading is "pre-existing
        # content". Confirm the index is at least addressable in the post-diff file; an
        # out-of-range referent index means the operands do not correspond at all.
        if lines is not None and not (0 <= idx < len(lines)):
            return False
    return True


def _demote_ok(exempt, added, move, claim_sources, idxs, lines=None):
    """The issue-#629 demotion predicate — the SOLE owner of "may this STALE be demoted?".

    Both halves of the contract in one place: ``exempt`` is the multiplicity half (this
    line's text is a byte-identical relocation), ``_referents_relocated`` is the referent
    half. Every rule site routes its decision through here rather than restating the
    conjunction, so tightening or relaxing the contract is a one-site edit instead of a
    coupled edit at every site. Deliberately a pure predicate that appends no ``Row``: the
    STALE-emitting call sites keep their literal rule ids, which is what the ``#466``
    mla-rule-drift AST guard requires (it tolerates exactly one emit indirection,
    ``_emit_count``, and a new emit helper would violate it).

    ``lines`` is the post-diff file, forwarded so the referent half can verify its own join
    corresponds rather than reading an absent operand as innocence. A caller that cannot
    supply a trustworthy line correspondence passes ``exempt=False`` instead (see
    ``examine_file``'s ``_locate`` fallback), which denies the demotion outright."""
    return exempt and _referents_relocated(added, move, claim_sources, idxs, lines)


def _repo_root():
    """The repository root the working-tree post-image is resolved against (issue #818).

    Diff paths are repo-root-relative and the revision mode's ``git show <rev>:<path>`` is
    repo-root-anchored, so the working-tree mode must anchor the same way or the two modes
    disagree whenever the caller's CWD is not the root. Mirrors the shared repo-root contract
    (issue #295): ``git rev-parse --show-toplevel``, falling back to the CWD. The fallback is
    breadcrumbed rather than silent — a run resolving against the CWD instead of the root is
    the shape that emits zero rows while exiting 0, which the sweep would otherwise record as
    a clean pass.

    Deliberately **not** cached in module state. ``run`` resolves it once and threads it to
    every ``post_file_lines`` call, so there is no cache to invalidate and no ordering coupling
    for a direct ``post_file_lines`` caller (the test suite is one) — a module-level cache
    guaranteed its per-run scoping only for callers that entered through ``run``."""
    rc, out, _ = _run_git(["rev-parse", "--show-toplevel"])
    if rc == 0 and out.strip():
        return out.strip()
    cwd = os.getcwd()
    sys.stderr.write(
        "stale-prose-lint.py: could not resolve the repository root "
        "(git rev-parse --show-toplevel did not report one); resolving working-tree "
        f"post-image paths against the current directory {cwd} instead. Diff paths ARE "
        "repo-root-relative, so unless that directory IS the root every file will read as "
        "UNRESOLVABLE and the run will emit zero rows while exiting 0\n")
    return cwd


def post_file_lines(rev, path, root=None):
    """Return the post-diff file's lines (1-indexed via index+1), or None when the
    file cannot be resolved — an UNRESOLVABLE case, NOT an internal error (only an
    unreadable REV itself is exit-2, validated up front).

    ``rev`` of :data:`WORKTREE` selects the issue-#818 **working-tree** mode: the post-image is
    the on-disk file, read directly with no history read at all, so a new or modified
    uncommitted file resolves to its post-change content. ``root`` is the repository root that
    mode resolves against, threaded from ``run`` (resolved there once); when it is omitted this
    function resolves it itself, so a direct caller cannot accidentally read the CWD. Every
    other ``rev`` value keeps the shipped ``git show <rev>:<path>`` behavior byte-for-byte.

    Every non-zero ``git show`` lands on the same None -> UNRESOLVABLE arm, but the
    reasons are not the same: an expected absence (the file was deleted/renamed at
    ``rev``) reads identically to a transient/environmental failure on a file that IS
    present. The verdict row cannot tell them apart, so git's own reason goes to stderr
    — the downgrade stays non-gating, but it is never unexplained. The working-tree arm
    below follows the same discipline with the OS error as its reason.

    **The working-tree read is anchored to the repository root, never to the process CWD.**
    Diff paths are repo-root-relative and ``git show <rev>:<path>`` is repo-root-anchored, so
    a bare ``open(path)`` would make the two modes disagree the moment the caller's CWD is not
    the root: every file would land on this arm's ``None`` and the whole run would emit zero
    rows while exiting 0 — a *clean-shaped* result for work that never happened. Anchoring
    mirrors the shared repo-root contract the ``.prflow/`` readers already follow (issue
    #295): ``git rev-parse --show-toplevel``, falling back to the CWD with a breadcrumb."""
    if rev is WORKTREE:
        try:
            with open(os.path.join(root if root is not None else _repo_root(), path), "r",
                      encoding="utf-8", errors="replace") as fh:
                return fh.read().split("\n")
        except OSError as exc:
            reason = " ".join(str(exc).split())[:200] or f"{type(exc).__name__}"
            sys.stderr.write(
                "stale-prose-lint.py: "
                f"{path} not readable in the working tree (UNRESOLVABLE): {reason}\n")
            return None
    rc, out, err = _run_git(["show", f"{rev}:{path}"])
    if rc != 0:
        reason = " ".join(err.split())[:200] or f"git show exited {rc} with no stderr"
        sys.stderr.write(
            f"stale-prose-lint.py: {path} not resolvable at rev (UNRESOLVABLE): {reason}\n")
        return None
    return out.split("\n")


def _forward_cases(lines, start_idx):
    """``(max Case N, [indices of the lines carrying a Case item])`` strictly after
    ``start_idx`` (0-based). The indices are R1's referent content for the issue-#629
    referent rule; the max is its verdict operand. Both come from one scan so the
    verdict and the exemption can never be computed over different line sets."""
    best = None
    idxs = []
    for offset, line in enumerate(lines[start_idx + 1:]):
        found = False
        for m in _CASE_ITEM_RE.finditer(line):
            n = int(m.group(1))
            best = n if best is None else max(best, n)
            found = True
        if found:
            idxs.append(start_idx + 1 + offset)
    return best, idxs


def _adjacent_list_idxs(lines, claim_idx):
    """Indices of the contiguous enumeration items directly above (preferred) or below
    the claim line, tolerating blank separators. Empty when there is no adjacent block."""
    def scan_dir(step):
        i = claim_idx + step
        # Skip blank separators — including a bare `#` / `//` line inside a comment block,
        # which is that block's blank line and must not terminate the enumeration.
        while 0 <= i < len(lines) and _uncomment(lines[i]).strip() == "":
            i += step
        out = []
        while 0 <= i < len(lines) and _LIST_ITEM_RE.match(_uncomment(lines[i])):
            out.append(i)
            i += step
        return out

    above = scan_dir(-1)
    if above:
        return above
    return scan_dir(1)


def _adjacent_assert_idxs(lines, claim_idx):
    """Indices of the contiguous assertion lines below the claim, tolerating blanks. An
    assertion line contains ``assert`` or is an enumeration item."""
    i = claim_idx + 1
    while i < len(lines) and _uncomment(lines[i]).strip() == "":
        i += 1
    out = []
    while i < len(lines) and (_ASSERT_LINE_RE.search(lines[i])
                              or _LIST_ITEM_RE.match(_uncomment(lines[i]))):
        out.append(i)
        i += 1
    return out


def _mods_ok(mods):
    """True when every intervening modifier token in ``mods`` is a plain modifier word — not a
    partitive/conjunction (of/per/and/or) and not numeral-shaped. See the recognition-tier
    noise guards in the module header. ``mods`` may be empty (zero modifiers → always OK)."""
    for tok in mods.split():
        bare = tok.strip("*`").lower()
        if bare in _RECOG_MOD_DISQUALIFY:
            return False
        if bare in _WORD_NUM or bare.isdigit():
            return False
    return True


def _recognize_count(text):
    """Recognition-only tier (issue #439): return ``(n, noun)`` for a *widened* count claim that
    today's ``_COUNT_RE`` does not match, or ``None``. NON-GATING — the caller emits an
    ``UNRESOLVABLE`` row and never resolves a referent. ``finditer`` (not ``search``) so a first
    match disqualified by its modifiers does not mask a later valid claim on the same line."""
    for m in _RECOG_RE.finditer(text):
        if not _mods_ok(m.group("mods")):
            continue
        word = m.group("word")
        n = _WORD_NUM[word.lower()] if word else int(m.group("digit"))
        return n, m.group("noun")
    return None


def _recognize_coverage_universal(text):
    """Coverage-universal recognition tier (issue #818): return the matched quantifier-plus-noun
    phrase for a universal claim about the change's own coverage, or ``None``. NON-GATING — the
    caller emits an ``UNRESOLVABLE`` row and never resolves a referent."""
    m = _CU_RE.search(text)
    return _excerpt(m.group(0)) if m else None


def _excerpt(text):
    return " ".join(text.split())[:120]


def _emit_count(rows, rule, path, post_ln, n, c, unresolvable, stale, verified, demote=False):
    """Append the shared count-claim verdict for a claimed count ``n`` vs an actual
    adjacent-block count ``c``: 0 → UNRESOLVABLE (no block), ``c != n`` → STALE, else
    VERIFIED. R2/R3/R3b all resolve to this same three-arm shape, differing only in
    their per-verdict detail strings.

    ``demote`` (issue #629) turns only the STALE arm into a non-gating UNRESOLVABLE row
    carrying the same diagnostic behind the relocation prefix — the caller decides it by
    the multiplicity + referent rules. The UNRESOLVABLE and VERIFIED arms are untouched:
    an exempt line whose referent MATCHES is still a plain VERIFIED, not a demotion."""
    if c == 0:
        rows.append(Row(UNRESOLVABLE, rule, path, post_ln, unresolvable))
    elif c != n:
        if demote:
            rows.append(Row(UNRESOLVABLE, rule, path, post_ln, RELOCATED_PREFIX + stale))
        else:
            rows.append(Row(STALE, rule, path, post_ln, stale))
    else:
        rows.append(Row(VERIFIED, rule, path, post_ln, verified))


def examine_file(path, added, lines, rows, move=None):
    """Append ``Row(verdict, rule, path, line, detail)`` rows to ``rows`` for ``path``.

    ``added`` maps post-image line numbers to added text; ``lines`` is the whole
    post-diff file (0-indexed list). A claim is examined only when it sits on an
    added line **that may carry a claim** — a comment or prose line, per ``prose_mask``.
    A code line that merely contains claim-shaped text is data, not an assertion.

    ``move`` (issue #629) is the :class:`MoveIndex` carrying BOTH halves of the exemption's
    bookkeeping — ``relocated`` (the multiplicity verdict) and ``sources`` (the per-text
    provenance the referent rule intersects against). It only ever DEMOTES a STALE row to a
    non-gating UNRESOLVABLE — it never suppresses a row, changes a VERIFIED, or
    short-circuits the #434 scoping mask above it, so move-awareness is layered over scoping
    rather than bypassing it. It defaults to ``None``, normalised below to an empty
    ``MoveIndex``, which is exactly today's grading (every caller-supplied additions-only
    diff, and any caller that does not compute the index).
    """
    if move is None:
        move = MoveIndex(frozenset(), {})
    mask = prose_mask(path, lines)
    unlocated = 0
    for post_ln in sorted(added):
        text = added[post_ln]
        idx = post_ln - 1  # 0-based index into `lines`
        # `located_by_text` records that post-image numbering did NOT resolve for this claim.
        # It is load-bearing for the exemption, not merely for the referent lookup: on this
        # path `idx` comes from a text search, so the `added` map's post-image keys bear no
        # defined relationship to the file indices the rules derive their referents from. A
        # demotion decided off that join would be read from the wrong lines, so the whole
        # exemption is denied here — failing toward gating (issue #629 review).
        located_by_text = False
        if (idx < 0 or idx >= len(lines)
                or _norm_line(lines[idx]) != _norm_line(text)):
            # The added line's post-image number does not resolve to THIS line in the
            # post-diff file — either out of range (deleted/renamed race) or in range but
            # naming different content (a skewed post-image join, which a range test alone
            # cannot see). Resolve referents defensively by text. A range test is not a
            # correspondence test: without the content compare, a skewed-but-in-range join
            # anchored the claim on the wrong line, collected referents from the wrong
            # region, and — because those referents are then legitimately absent from
            # `added` — took the "pre-existing, no obligation" arm and DEMOTED a real STALE.
            # That is the primary path for this feature (the reported defect has no
            # diff-added referents at all), so the check has to live here on the anchor.
            idx = _locate(lines, text)
            if idx is None:
                # The added line corresponds to NOTHING in the post-image, so it is dropped
                # before any rule — silently, until #818. Under `--rev` a miss implied a
                # genuine race between an immutable commit and its own diff; under the
                # working-tree mode the post-image is a MUTABLE tree read at a later instant
                # than the diff, so ordinary conditions produce misses (a concurrent write, a
                # non-UTF-8 byte the `errors="replace"` read substitutes). Each miss is a line
                # the sweep never examined while the run still reports zero rows, so the drop
                # is counted and announced below rather than left to look like a clean pass.
                # A blank/whitespace-only added line is NOT counted: `_locate` returns None for
                # it by construction, independent of any post-image skew, so counting it would
                # inflate the figure on every diff that adds a blank line.
                if text.strip():
                    unlocated += 1
                continue
            located_by_text = True
        if not _may_carry_claim(mask, idx):
            continue
        # Illustrative-example opt-out (issue #635): an author-declared example of a claim shape
        # is DOCUMENTATION, not an assertion. Skip every gating rule for it — R1–R4 — and both
        # non-gating recognition tiers below — before any rule runs. Emit ONE non-gating
        # (UNRESOLVABLE, never STALE) audit row instead of falling silent, so the suppression is
        # greppable in the output: a marked line that lands on a real claim (a mis-placed or
        # relocated marker) is then visible to a reviewer of the lint's output, not only to a
        # reader of the source. Placed after `_may_carry_claim` so only lines that could carry a
        # claim pay the regex.
        if _EXAMPLE_MARKER_RE.search(text):
            rows.append(Row(UNRESOLVABLE, "EX", path, post_ln,
                            f"exempted by opt-out marker (stale-prose-lint: example) — "
                            f"all rules skipped — {_excerpt(text)}"))
            continue
        # Multiplicity half of the exemption; each rule adds its own referent half below.
        # Deliberately asymmetric with the referent rule: the CLAIM side does not additionally
        # require its own provenance to intersect anything. It has nothing to intersect against
        # — the claim is the thing being relocated, so there is no second party whose source
        # file must match. The only shape this asymmetry admits is a diff so malformed that a
        # removal carries no resolvable source path (header-less hunks), which contributes to
        # the diff-global `removed` tally but to no `sources` entry; that widens the claim half
        # only, and the referent half still gates. Failure direction stays toward gating.
        exempt = (text in move.relocated) and not located_by_text
        # The source files this claim itself was removed from — the provenance the referent
        # rule intersects against. Empty when the claim is not a relocation, in which case
        # `exempt` is already False and the intersection is never consulted.
        claim_sources = move.sources.get(text, frozenset())

        # R1 — range outgrowth
        rm = _RANGE_RE.search(text)
        if rm:
            a, b = int(rm.group(1)), int(rm.group(2))
            maxn, case_idxs = _forward_cases(lines, idx)
            if maxn is None:
                rows.append(Row(UNRESOLVABLE, "R1", path, post_ln,
                                f"range Cases {a}-{b}: no forward Case items found — {_excerpt(text)}"))
            elif maxn > b:
                r1_stale = (f"range claims Cases {a}-{b} but forward region reaches "
                            f"Case {maxn} — {_excerpt(text)}")
                if _demote_ok(exempt, added, move, claim_sources, case_idxs, lines):
                    rows.append(Row(UNRESOLVABLE, "R1", path, post_ln,
                                    RELOCATED_PREFIX + r1_stale))
                else:
                    rows.append(Row(STALE, "R1", path, post_ln, r1_stale))
            else:
                rows.append(Row(VERIFIED, "R1", path, post_ln,
                                f"range Cases {a}-{b} covers forward max Case {maxn} — {_excerpt(text)}"))
            continue

        # R2 — legend/enumeration sum vs "Expected total = N"
        tm = _TOTAL_RE.search(text)
        if tm:
            n = int(tm.group(1))
            item_idxs = _adjacent_list_idxs(lines, idx)
            c = len(item_idxs)
            _emit_count(rows, "R2", path, post_ln, n, c,
                        f"Expected total = {n}: no adjacent enumeration block — {_excerpt(text)}",
                        f"Expected total = {n} but adjacent enumeration has {c} items — {_excerpt(text)}",
                        f"Expected total = {n} matches {c} enumerated items — {_excerpt(text)}",
                        demote=_demote_ok(exempt, added, move, claim_sources, item_idxs, lines))
            continue

        # R3b — two-item "a X and a Y … both" count-locked claim (asserts 2)
        if _BOTH_RE.search(text) and _TWO_ITEM_RE.search(text):
            assert_idxs = _adjacent_assert_idxs(lines, idx)
            c = len(assert_idxs)
            _emit_count(rows, "R3", path, post_ln, 2, c,
                        f"count-locked: two-item claim but no adjacent assertion block — {_excerpt(text)}",
                        f"count-locked: claim asserts both (2) but adjacent block has {c} assertions — {_excerpt(text)}",
                        f"count-locked: two-item claim matches {c} assertions — {_excerpt(text)}",
                        demote=_demote_ok(exempt, added, move, claim_sources, assert_idxs, lines))
            continue

        # R3 — exact numeric count claim ("N assertions") count-locked
        cm = _COUNT_RE.search(text)
        if cm:
            n = int(cm.group(1))
            assert_idxs = _adjacent_assert_idxs(lines, idx)
            c = len(assert_idxs)
            _emit_count(rows, "R3", path, post_ln, n, c,
                        f"count-locked: '{n} {cm.group(2)}' claim but no adjacent assertion block — {_excerpt(text)}",
                        f"count-locked: claims {n} {cm.group(2)} but adjacent block has {c} — {_excerpt(text)}",
                        f"count-locked: {n} {cm.group(2)} matches adjacent block — {_excerpt(text)}",
                        demote=_demote_ok(exempt, added, move, claim_sources, assert_idxs, lines))
            continue

        # R4 — operator-token modality conflict
        if _DENY_RE.search(text):
            op = None
            for m in _BACKTICK_RE.finditer(text):
                if m.group(1) in OP_TOKENS:
                    op = m.group(1)
                    break
            if op is not None:
                permit_idxs = _permits_elsewhere(lines, idx, op, mask)
                if permit_idxs:
                    r4_stale = (f"deny-absolute forbids `{op}` but the same file asserts it "
                                f"permitted — {_excerpt(text)}")
                    # R4's referent is EVERY permit line that contradicts the claim — not just
                    # the first. A single-index referent set let a PR-authored permit below a
                    # pre-existing one escape the referent rule entirely (issue #629 review).
                    if _demote_ok(exempt, added, move, claim_sources, permit_idxs, lines):
                        rows.append(Row(UNRESOLVABLE, "R4", path, post_ln,
                                        RELOCATED_PREFIX + r4_stale))
                    else:
                        rows.append(Row(STALE, "R4", path, post_ln, r4_stale))
                else:
                    rows.append(Row(VERIFIED, "R4", path, post_ln,
                                    f"deny-absolute on `{op}`: no contradicting permit found — {_excerpt(text)}"))
                # `continue` ONLY when R4 actually CLAIMED the line — found an operator token
                # and emitted a row. A deny-absolute carrying no operator token is a line R4
                # examined and emitted nothing for: a silent swallow, not a claim. See the
                # module header's #818 record for why the outer-match placement blinded both
                # recognition tiers and why narrowing it cannot change the exit code.
                continue

        # Coverage-universal recognition tier (issue #818) — NON-GATING, and deliberately
        # placed BEFORE the R3 recognition tier below WITHOUT a `continue`, so a line the two
        # overlapping noun sets both claim emits both rows. See the module header's #818
        # "Precedence, decided explicitly" record. Both still sit after the gating rules.
        cov = _recognize_coverage_universal(text)
        if cov is not None:
            if _RULE_TEXT_MARKER_RE.search(text):
                # The declared opt-out suppresses the SEED row but is not silent: one
                # non-gating audit row keeps a marker that landed on a real claim visible in
                # the lint OUTPUT. It does not discharge the §2.3.4b grounding obligation.
                rows.append(Row(UNRESOLVABLE, "RT", path, post_ln,
                                "coverage-universal seed row suppressed by declared opt-out "
                                "marker (stale-prose-lint: rule-text) — the grounding "
                                f"obligation is undischarged — {_excerpt(text)}"))
            else:
                rows.append(Row(UNRESOLVABLE, "CU", path, post_ln,
                                f"coverage-universal: recognition-only ({cov}) — ground this "
                                "claim by enumeration, scoping, or removal — "
                                f"{_excerpt(text)}"))

        # R3 recognition-only tier (issue #439) — widened claim recognition, NON-GATING.
        # Placed LAST, after every gating rule: R1/R2/R3b/R3 each `continue` on a match, and
        # R4 `continue`s on the match it CLAIMS (#818 narrowed it to its emit path) — so the
        # recognition tier is reached ONLY on a line no gating rule emitted a row for. This ordering is load-bearing for the non-gating invariant: an earlier
        # placement let a line matching both the widened count shape AND a gating R4
        # deny-absolute be consumed here (via the `continue` below) before R4 could run,
        # suppressing a real STALE and flipping the exit code — the fail-open this position
        # forecloses. No referent resolution runs; the row is always UNRESOLVABLE and never
        # affects the exit code — its sole purpose is the count-locked policy trigger.
        rec = _recognize_count(text)
        if rec is not None:
            rec_n, rec_noun = rec
            rec_detail = ("count-locked: recognition-only "
                          f"({rec_n} {rec_noun}) — pin or drift-proof this claim — {_excerpt(text)}")
            rows.append(Row(UNRESOLVABLE, "R3", path, post_ln, rec_detail))
            continue

    # Dropping coverage is never silent — the same discipline `run` already applies to the
    # unrecognised-extension fail-open, the issue-#672 exclusions, and the #629 demotions.
    if unlocated:
        sys.stderr.write(
            f"stale-prose-lint.py: {unlocated} non-blank added line(s) in {path} did not "
            "correspond to the post-image and were NOT examined — the dominant cause is "
            "post-image skew (a revision-mode post-image that predates the added line), and a "
            "concurrent write or a substituted undecodable byte produce it too; this is a "
            "coverage drop, not a clean result\n")


def _permits_elsewhere(lines, claim_idx, op, mask=None):
    """**Every** index of a COMMENT/PROSE line (other than the claim) asserting operator ``op``
    is permitted — the complete list, empty when there is none.

    Completeness is load-bearing, not incidental: this list is R4's referent content for the
    issue-#629 referent rule, and a truncated list is a **fail-open**. Returning only the
    *first* permit (the shape this replaced) meant a pre-existing permit short-circuited the
    scan, so a second, PR-**authored** permit below it was never examined — the referent rule
    saw no diff-added referent, imposed no obligation, and demoted a contradiction the PR
    itself authored. R1/R2/R3 all collect their full referent index set for exactly this
    reason (see ``_forward_cases``, which returns the verdict operand and the index list from
    one scan "so the verdict and the exemption can never be computed over different line
    sets"); R4 is held to the same rule.

    The permit referent is scoped by the same predicate as the claim (issue #434). A code line
    is not an assertion about the file, so it cannot contradict one: before this, a shell
    fixture string like ``'An in-workspace `>` redirect … is permitted.'`` acted as a real
    "permit" and flipped a genuine comment deny-absolute to STALE. That is an independent
    false-positive source from the claim side, and scoping only the claim would leave it
    minting fresh false positives forever."""
    idxs = []
    for i, line in enumerate(lines):
        if i == claim_idx:
            continue
        if not _may_carry_claim(mask, i):
            continue
        if not _PERMIT_RE.search(line):
            continue
        for m in _BACKTICK_RE.finditer(line):
            if m.group(1) == op:
                idxs.append(i)
                break
    return idxs


def _locate(lines, text):
    stripped = text.strip()
    if not stripped:
        return None
    for i, line in enumerate(lines):
        if line.strip() == stripped:
            return i
    return None


def _demotion_breadcrumbs(rows, err):
    """Surface every issue-#629 demotion on stderr, then return the count (issue #636).

    A demotion is the SOLE mechanism in this helper that turns a would-be exit 1 into
    exit 0, and it was silent: a demoted row is emitted as a non-gating ``UNRESOLVABLE``
    carrying the original diagnostic behind ``RELOCATED_PREFIX``, indistinguishable from
    ordinary no-referent ``UNRESOLVABLE`` noise without grepping that prefix — so a caller
    reading the exit code and row count saw a clean pass. Every OTHER degradation in this
    file already writes a breadcrumb by explicit discipline; this closes the one gap.

    The demotion signature is exact: a row is demoted iff its verdict is ``UNRESOLVABLE``
    AND its detail begins with ``RELOCATED_PREFIX`` — that prefix is prepended at, and only
    at, the demotion sites (currently ``_emit_count``'s demote arm, R1, and R4; the scan
    needs no update when a site is added), so scanning for it here covers every current site
    and any future one at one altitude, rather than emitting from each site. Additive on
    stderr only: ``rows`` and stdout are untouched.
    """
    n = 0
    for row in rows:
        if row.verdict == UNRESOLVABLE and row.detail.startswith(RELOCATED_PREFIX):
            n += 1
            err.write(
                f"stale-prose-lint.py: {row.path}:{row.line} STALE demoted to non-gating "
                "(move-aware exemption, issue #629)\n")
    if n:
        # One end-of-run summary, mirroring the `_unrecognised_exts` pattern in `run`.
        err.write(
            f"stale-prose-lint.py: {n} STALE row(s) demoted to non-gating UNRESOLVABLE "
            "(move-aware exemption, issue #629); these do not affect the exit code\n")
    return n


def run(rev, diff_text):
    # Validate the rev up front — an unreadable rev is a caller error (exit 2), not
    # a per-file UNRESOLVABLE. `rev-parse --verify` never derives a diff range.
    # Resolve the working-tree post-image root ONCE for this run and thread it below (issue
    # #818) — a per-run value held on the stack, so two runs from two trees cannot share one
    # and a direct `post_file_lines` caller is not coupled to this run's ordering.
    root = _repo_root() if rev is WORKTREE else None

    # `rev is WORKTREE` is the issue-#818 working-tree mode: there is no revision to validate
    # (and no history read at all), so this precondition does not apply to it.
    if rev is not WORKTREE:
        rc, _, _ = _run_git(["rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"])
        if rc != 0:
            raise InternalError(f"--rev '{rev}' does not resolve to a commit")

    # The removed-line multiset is diff-GLOBAL and computed once, before the per-file walk:
    # a relocation's source and destination are different files, so a per-file tally could
    # never pair them (issue #629).
    files, removed, removed_by_file = parse_diff_full(diff_text)
    move = build_move_index(files, removed, removed_by_file)
    rows = []
    excluded = []
    for path in sorted(files):
        added = files[path]
        if not added:
            continue
        # A machine-appended corpus record is DATA that quotes prose, never an assertion
        # about the file (issue #672). Skipped before the post-image read, so an excluded
        # path costs no `git show` and can emit no row of any verdict.
        if _is_excluded(path):
            excluded.append(path)
            continue
        lines = post_file_lines(rev, path, root)
        if lines is None:
            for post_ln in sorted(added):
                rows.append(Row(UNRESOLVABLE, "-", path, post_ln,
                                f"post-diff file not resolvable in the post-image — {_excerpt(added[post_ln])}"))
            continue
        examine_file(path, added, lines, rows, move)

    # The fail-open arm must be DISCOVERABLE, not silent: a consumer whose language is not in
    # the scoping tables keeps today's examine-every-line behavior (no coverage is lost), but
    # they get the false positives that behavior implies — and with no breadcrumb they would
    # have no way to learn why, or that adding their type is the fix.
    # Dropping coverage is never silent either — including when the drop is INTENDED. An
    # excluded path is named on stderr so a claim a consumer expected to be graded is
    # traceable to this rule rather than looking like a missed detection.
    if excluded:
        sys.stderr.write(
            "stale-prose-lint.py: not examined (machine-appended corpus, issue #672): "
            f"{', '.join(excluded)}\n")

    if _unrecognised_exts:
        sys.stderr.write(
            "stale-prose-lint.py: no comment/prose scoping rule for "
            f"{', '.join(sorted(_unrecognised_exts))} — every added line in those files was "
            "examined (fail-open: coverage is never silently dropped for an unlisted type)\n")

    # Surface any issue-#629 demotions on stderr (issue #636) — a demotion is the sole
    # non-gating downgrade in this helper and was previously undiscoverable except by
    # grepping the detail prefix. Additive on stderr only; the stdout TSV below is
    # byte-identical and the exit code is still driven solely by the STALE literal.
    _demotion_breadcrumbs(rows, sys.stderr)

    stale = False
    for row in rows:
        sys.stdout.write(f"{row.verdict}\t{row.rule}\t{row.path}\t{row.line}\t{row.detail}\n")
        if row.verdict == STALE:
            stale = True
    return 1 if stale else 0


def main(argv):
    # The ENTIRE body sits inside the exit-2 catch-all. An exception escaping `main` at all
    # would exit with Python's default code 1 — and 1 is a CONTRACTED helper arm ("at least
    # one STALE row"), not an error code, so the callers' exit-code routers (Phase 0.6, the
    # fix loop's pre-check) would read a crashed run as a completed one over its empty
    # stdout. Every failure must therefore surface as 2. Two limbs used to sit outside the
    # guard: the stream reconfigure below (whose except-list is narrower than the set of
    # exceptions an exotic wrapped stream can raise) and the argparse construction.
    # `argparse`'s own usage exit is a SystemExit (a BaseException) and still passes
    # through with its own code, as does `--help`.
    try:
        # Harden the OUTPUT streams the same way `_run_git` hardens its input decode. Under
        # a `C`/`POSIX` locale (the threat model `_run_git` cites) sys.stdout/sys.stderr
        # default to the strict-ASCII codec, so writing a verdict row (or a diagnostic)
        # whose text carries a non-ASCII byte — an en/em-dash, Latin-1, a UTF-8 BOM copied
        # out of a reviewed line — would raise UnicodeEncodeError at write time and abort
        # the ENTIRE lint to exit 2, masking every other file's verdict (the read-side
        # hardening alone did not close this; the failure resurfaced at the stdout write).
        # Reconfigure to utf-8/errors="replace" so an odd byte degrades that one character,
        # never the pass. Guarded because a replaced/wrapped stream (a test harness, a pipe
        # object) may lack reconfigure() or reject the call.
        # Never widen this to OSError the way _force_utf8_streams does: here the
        # enclosing catch-all turns an escape into the contracted exit 2, and swallowing
        # would let the run report completion over stdout it could not write.
        for _stream in (sys.stdout, sys.stderr):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass
        parser = argparse.ArgumentParser(
            prog="stale-prose-lint.py",
            description="Detect stale countable claims in diff-added prose (issue #423).",
        )
        # Exactly one post-image mode, and never both (issue #818). `--rev` keeps its
        # shipped meaning; `--worktree` reads the on-disk file so an UNCOMMITTED tree can be
        # graded before commit. argparse enforces the exclusivity and the requirement, so
        # neither is re-derived in the body.
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument(
            "--rev",
            help="the revision whose post-diff file state resolves each claim's referent "
            "(git show <rev>:<path>); the caller supplies the diff on stdin. This helper "
            "never derives the diff range itself.",
        )
        mode.add_argument(
            "--worktree",
            action="store_true",
            help="resolve each claim's referent against the on-disk working-tree file "
            "instead of a revision, so a new or modified UNCOMMITTED file resolves to its "
            "post-change content; makes no history read at all.",
        )
        args = parser.parse_args(argv[1:])

        try:
            raw = sys.stdin.buffer.read()
        except Exception as exc:
            sys.stderr.write(f"stale-prose-lint.py: could not read stdin ({exc})\n")
            return 2
        try:
            diff_text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            sys.stderr.write(f"stale-prose-lint.py: diff is not valid UTF-8 ({exc})\n")
            return 2

        # The WORKTREE sentinel selects the working-tree post-image mode; argparse already
        # guaranteed exactly one of the two flags is present.
        return run(WORKTREE if args.worktree else args.rev, diff_text)
    except InternalError as exc:
        sys.stderr.write(f"stale-prose-lint.py: {exc}\n")
        return 2
    except Exception as exc:
        sys.stderr.write(f"stale-prose-lint.py: internal error ({type(exc).__name__}: {exc})\n")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
