# Contributing to PRFlow

Thanks for your interest in improving PRFlow! This guide covers the basics.

## Repository layout

PRFlow is a single Claude Code plugin published at the repository root:

```
.claude-plugin/   plugin.json + marketplace.json (manifests)
skills/           the /prflow:implement, /prflow:review, /prflow:docs, … skills (SKILL.md each)
agents/           subagent definitions
lib/              shell + jq helpers for the retrospective loop, plus lib/test/
scripts/          Python + shell CLIs (workpad.py, config-get.sh, …)
.github/          the optional "cloud tier" workflows + composite actions
docs/             cloud-setup guide and other docs
```

## Prerequisites

- `git`, `gh` (GitHub CLI, authenticated), `jq`
- Python 3.11+ with PyYAML (`python3 -m pip install -r requirements.txt`)

Run `bash lib/preflight.sh` to verify your environment. **Note for contributors:** `lib/preflight.sh` no longer *enforces* PyYAML — it reports a missing PyYAML as an advisory gap and still exits 0. The **test suite** (`bash lib/test/run.sh`) does still require PyYAML and fails without it, so install it before running the suite; a green preflight is not sufficient to confirm a contributor environment.

**Windows (stock Python): resolving `python3`.** A stock Windows Python install (python.org / `winget install python`) puts Python on PATH as `python` and the `py -3` launcher — there is **no `python3`**, so every PRFlow helper and the agent-typed `python3 <path>` calls fail. When `python3` is absent but a `>=3.11` Python is reachable as `python` or `py -3`, run the consent-gated provisioner to install a small `python3` shim onto your PATH:

```bash
bash scripts/provision-python3-shim.sh --apply
```

It picks the first of `python3`/`py -3`/`python` reporting `>=3.11`, writes a `python3` that forwards to it (a no-op when a real `python3 >=3.11` already resolves), and prints a `devflow-python:` breadcrumb. macOS/Linux already have a real `python3`, so this is a no-op there. `bash lib/preflight.sh` points you here when it detects the no-`python3`/has-alternate state.

## Running the tests

```bash
bash lib/test/run.sh
```

This runs the jq-filter tests, the shell-helper tests, and the Python script
tests (`lib/test/test_python_scripts.py`). CI runs the same suite on every PR
(`.github/workflows/ci.yml`). Tests use `gh` **stubs** — no network or GitHub
auth is required to run them.

Some coverage is factored into **selectable modules** under `lib/test/modules/`
(registered in `scripts/workflow-flight-recorder-registry.json`), which you can run
in isolation while iterating on their area:

```bash
bash lib/test/run-module.sh create-issue-contract
bash lib/test/run-module.sh installer-wiring
bash lib/test/run-module.sh harness-python-guards
```

`scripts/workflow-flight-recorder-registry.json`'s `test_modules` block is the
authoritative list of module IDs — read it there rather than from this sample.

**Focused verification is the iteration default (issues #707, #789).** While
iterating, run the focused test that covers the surface you changed rather than
the complete suite. Two kinds of focused test count: a registered shell module,
run as `bash lib/test/run-module.sh <module-id>`; and, for a `scripts/*.py` or
`lib/*.py` unit, the `lib/test/test_*.py` file its coverage-map entry names in a
`focused_test` field — invoked as a direct leading token (`lib/test/test_python_scripts.py`),
never as `python3 <path>`, so the same command works on the cloud tier, where the
interpreter-head shape is denied. Reach for `bash lib/test/run.sh` mid-iteration
only for a surface no focused test covers, and then only for its first cycle: a
second mid-iteration cycle on that same uncovered surface extracts a durable
module instead of paying the complete suite again. Selection stays explicit —
consult `lib/test/modules/coverage-map.json` to find a candidate and confirm a
module ID in the registry; changed files never auto-route to a module. The whole-suite gate is not weakened, but since
issue #1607 **this repository's** local/interactive tier discharges it by
committing, pushing, and reading CI for the pushed commit rather than by a local
complete-suite pass. `CLAUDE.md`'s rung 1 carries that procedure and its
fail-open traps in one copy — follow it there rather than from this summary,
which deliberately restates no part of it, since a partial restatement is what
would send a reader past the trap the full rule names. The local
run stays the signal you **troubleshoot** from, because
its failure detail is richer than CI's, and the issue-#456 skip accounting is
unchanged — a nonempty skip tally is not clean, and a module may not self-skip,
so focused iteration cannot launder a skip. A mid-iteration issue-#434
stale-prose `blocking-gate` skip on a dirty tree is expected and clears once the
tree is committed, so do not re-run the complete suite mid-iteration just to
clear it. When the complete suite does run and fails, read its terminal
`Failure recap` from the captured output rather than relaunching it. The operative statement of this
policy for agent runs lives in `CLAUDE.md`'s Commands section, which carries the
tier ladder in one copy; the cloud `/prflow:implement` in-env gate
(issue #405) is untouched by it, because a headless run cannot suspend and resume
and so cannot wait on CI. `CLAUDE.md` is also the one home of the
**focused-first precondition** on the mid-iteration full-suite launch — every
touched surface with a covering focused test invocable on the tier is run first,
with a total four-ground exempt set governing the rest; this section points there
for the full statement and carries only the compact restatement above.

Each module is also executed by the full suite through the fail-closed
`devflow_run_full_suite_module` boundary, and shares the namespaced pin helpers in
`lib/test/module-harness.sh` (`devflow_module_pin_count` / `pin_unique` /
`pin_present` / `pin_red_under`) so a module carries no private pin machinery. The
harness is likewise the single home of the shared fixture helpers `mint_blk`,
`probe_tmp` and `probe_assert` (`lib/test/run.sh` sources them from there rather than
defining its own), and it clears an inherited `DEVFLOW_GH` before sourcing a module body
so a focused run gets the same fixture isolation as the full suite.
A per-module inventory (e.g. `lib/test/modules/create-issue-contract.inventory.md`)
records what it covers.

A test that matches against the text a command renders follows the colour convention in
[`docs/internal/test-suite-probe-conventions.md`](docs/internal/test-suite-probe-conventions.md).

**A module fixture is built from git-tracked content only (issue #714).** A module that
needs a repository image must reproduce it from the index (`git ls-files -s -z`), file by
file, with each file's mode taken from the index rather than from the working tree — never
by `cp -R`-ing a whole top-level directory. A tracked file inside an otherwise-untracked
directory makes the directory form copy that directory wholesale: because
`.claude/settings.json` is tracked, `regenerate-artifacts` used to copy the entire
untracked `.claude/` tree into every fixture, so a checkout carrying `git worktree`
checkouts under `.claude/worktrees/` paid that whole payload on every fixture copy — the
dominant cost of a full local suite run. Build caches and `.prflow/tmp` are excluded by
construction under the tracked-only rule, so a fixture builder needs no prune step —
while *tracked* content under an otherwise-ignored directory (`.prflow/config.json` and
the rest of `.prflow/`, force-added past the ignore rule) is still reproduced, which is
exactly what completeness requires. The
measured before/after figures are recorded once, in
[`lib/test/modules/regenerate-artifacts.inventory.md`](lib/test/modules/regenerate-artifacts.inventory.md).

#### Coverage-map block ownership (every PR that adds an assertion)

`lib/test/modules/coverage-map.json` is the ranked to-do list for future
extractions. Its `run_sh_blocks` half is **mostly derived** — a label asserted in the
tree that carries no entry is added mechanically by `--fix` — but it is **not purely
derived**: an entry whose assertions were later deleted or renamed has no live
derivation behind it and becomes a **curated historical record** the guard deliberately
neither reports nor removes (a few dozen such `run_sh_blocks` keys), and every
`note` in both halves plus every `files`-row's content is curated. So treat the half as
derived *for the ratchet's completeness arm* and curated *for the content a merge must
not lose*. The coverage
guard (`lib/test/coverage_map_guard.py`, driven by the complete suite) derives the
issue labels asserted by `lib/test/run.sh` and by every `lib/test/modules/*.sh` —
anchored on assertion-name position, so a `#NNN` in a comment derives nothing — and
turns the suite RED when:

- a label asserted in `lib/test/run.sh` has **no** `run_sh_blocks` entry, or
- a **fully extracted** label — carried by a module and asserted nowhere in
  `lib/test/run.sh` — has no entry, or names `unmodularized` instead of a module
  that carries it.

So **any** PR that adds an assertion named for a new issue owes that label a map
entry, not only a PR that extracts a module. The remedy is mechanical — run it and
commit the result:

```bash
python3 lib/test/coverage_map_guard.py . --fix
```

`--fix` is **hand-invoked only**. It is deliberately not wired into the batched
generated-artifact pass, where the coverage map stays a `by-hand` judgment row whose
write-scope assertion proves the pass leaves the file byte-unchanged. Running it
twice in a row leaves the file byte-unchanged the second time, and it refuses to
write a malformed map rather than corrupting it.

The guard also fails RED when the map on disk is **not in canonical serialized form**
— its key order or formatting differs from what `--fix` writes (issue #1065). This
catches drift the ownership arms miss (a merge-conflict resolution that reorders
entries leaves the parsed value unchanged), so it fails at the point the drift is
introduced instead of being silently folded into a later, unrelated `--fix`. The
remedy is the same command: `--fix` re-canonicalizes an order-only drifted map even
when it has no ownership repair to make, so you can always run it and commit the
result.

A label a module carries while assertions remain in `lib/test/run.sh` is *partially*
extracted and correctly stays `unmodularized`: one `owner` string cannot truthfully
describe split coverage.

The arm is deliberately **one-directional**: it reports a label the tree asserts but the
map does not carry, never the reverse. A map entry with no derivation behind it — a
block whose assertions were deleted or renamed — is a curated historical record, so it is
neither reported nor removed by `--fix`. Prune such an entry by hand when you want it gone.

**Merge conflicts in this file are NOT resolved with `--fix` (issue #1194).** The map is
two large string-sorted JSON objects, so two branches that each *add* a different key at
an adjacent sort position conflict textually even though they never semantically
conflict — and resolving by taking either side silently **drops the other branch's
entry**. `--fix` cannot undo that: it only *adds* missing derivable rows, so it cannot
restore a curated `run_sh_blocks` record, any dropped `note`, or any `files`-row content —
running it after a lossy resolution just produces a green suite over the loss. So when
this file conflicts, keep **every key from both sides**:

- Register the **JSON-aware merge driver** once per clone and let it union the objects
  automatically on your next merge/rebase (it conflicts only on a genuine same-key
  divergence):

  ```bash
  python3 lib/test/coverage-map-merge-driver.py --register   # then: --check to verify it is active
  ```

  The `.gitattributes` `merge=coverage-map-json` declaration only *names* the driver;
  git falls back silently to its line-based merge until the driver is registered locally,
  so `--check` (which prints the exact registration command when it is not) is the thing
  to run if you are unsure.
- If you resolve by hand (or in GitHub's web editor, where the driver cannot run), take
  **both** sides' entries and then re-canonicalize with `--fix` (canonical form only — the
  entries must already all be present first).

The CI-side **key-retention check** backstops both paths regardless of local
configuration — it fails RED when a key or its `note`/`owner` content disappears relative
to the merge base, including for the curated keys no ratchet arm inspects:

```bash
python3 lib/test/coverage-map-retention-check.py .
```

A genuinely legitimate removal (a deleted tracked file, a truly retired block) is declared
with a non-empty reason in `lib/test/coverage-map-retention-allow.json`.

It reports **three** outcomes, because "I could not establish whether a key was lost" is
not "no key was lost": `0` clean, `1` a dropped key (or an input it could not read), and
`3` **the base comparand could not be established**. Exit 3 is what you get on a shallow
or partial clone, where `git merge-base` either fails outright or succeeds against a
truncated commit graph and names a boundary commit whose tree predates the map — either
way the comparison proves nothing, so it must not report green. The remedy is a real
comparand (`git fetch --unshallow`, which is why CI checks out with `fetch-depth: 0`); if
you are deliberately working in a shallow clone and want the run to exit 0 anyway, pass
`--allow-degraded-base`, which still prints the reasons and reports the run as
acknowledged-degraded rather than as a verified clean pass. Do not add that flag to CI.

**Retired mutation-pin helpers (issue #810 follow-up).** The required
`mutation-routing-worktree` gate builds the audited test-source census and requires
both it and the checked-in inventory to remain empty. The former mutation-taking
helpers and wrappers are retired: adding any definition or invocation fails closed.
Write an ordinary executable behavioral test instead. The gate preserves the exact
audited-source/module-registry population check and does not execute or interpret
mutations, classify mutation effects, or infer assignment dependencies. Historical
mutation dispositions remain in the frozen mutation retirement manifest; a consistency
test derives their totals and verifies the live inventory summary rather than trusting
repeated counts.

A new static helper or direct positive source-presence assertion is allowed only for
an executable structural boundary and must carry
`# structural-pin-ok: <category> -- <non-empty rationale>` on its logical line.
`<category>` is exactly one of `helper-contract`, `schema-config-vocabulary`,
`security-credential-boundary`, `machine-sentinel-provenance`,
`routing-dispatch-contract`, `lifecycle-state-transition`,
`generated-artifact-identity`, or `cross-file-phase-contract`.

**The marker is a declaration required of a NEW or CHANGED pin — it is not a retention
badge you can retrofit onto the standing population (issue #885).** The gate scopes the
requirement to a site whose every physical line is in the diff's added set. For such a
site — once its declaration *grammar* has been checked, which happens first and which no
later arm routes around — the gate **routes** through an ordered three-step ladder
(issue #948), and the routing is deliberately not a judgement:

1. **A program demonstrably reads it.** The literal, or a machine-identifier-shaped
   token it names, occurs in the text of a tracked `scripts/**`,
   `lib/**`-outside-`lib/test/` or `.github/**` file — with comment regions
   subtracted for the `#`-comment extensions only (`.sh`, `.py`, `.jq`, `.yml`,
   `.yaml`), which is what `build_machine_consumer_corpus` implements: no other
   comment syntax is stripped, so a mention inside some other language's comment
   still counts as operative text. Pass; no
   declaration and no ledger row needed. A grep-shaped search misses a *generic*
   consumer by construction — a helper that walks a routing table row by row names no
   individual row — so "found none" routes to step 2 and never to a finding.
2. **The ledger already recorded the decision.** `lib/test/pin-corpus-adjudications.tsv`
   carries this literal as `boundary` **and** the site carries a valid
   `# structural-pin-ok:` declaration. The marker is a *pointer to an authorized
   decision*, never a self-granted permission: a tag with no ledger row is a finding,
   and so is a ledger row with no tag. Step 2 fails closed — an absent, unestablished
   or non-`boundary` row never satisfies it, and a ledger the gate cannot read is an
   infrastructure failure before the ladder runs at all.
3. **Neither.** The finding stands: `literal resolves into prose at <target>:<line>`,
   naming which half of step 2 was missing. This is the pin the policy exists to remove.

Be honest about where the control sits: after step 2 the gate is only routing, and the
real safeguard is the **review of ledger changes**, which is separately delta-gated and
needs an exact branch change manifest. A large majority of the retained pins resolve
into prose (a past-time snapshot, not a live figure: 229 of them measured on the
post-sweep population at the #885 sweep commit, kept as provenance for the probe below
and deliberately not re-rendered) — they are retained because a tool or consumer reads
the *thing the literal names* (a marker, a grant-matched invocation shape, a schema
field set), a distinction the lint's prose boundary cannot see; step 2 exists so that
such a pin can carry its reason at the site *and* be edited normally, which before #948
it could not. The per-pin retention record still lives where it is delta-gated and
auditable — `lib/test/pin-corpus-adjudications.tsv`, surfaced per row in the census —
and not as several hundred uncoupled copies in source comments, so retrofitting a marker
onto the standing population is still not the ask. Two cases the ladder does **not**
reach: a pin whose declared target the lint cannot resolve at all
(`typed structural declaration target cannot be inspected`) is still unfixable, and a
*retired* wording literal's revival keeps its own stronger contract below. A
**concatenated in-module bundle** target is no longer one of those unresolvable cases
(issue #956): the lint resolves the bundle variable to the member files its own builder
call concatenates and inspects the declaration against that member set, so such a pin is
editable like any other. Issue #1008 widened the modeled build grammar twice more, each
arm measured against `lib/test/run.sh` first: an array built by looping a literal **stem
list** and appending one interpolated path per stem (how `$REVIEW_BUNDLE` is assembled —
it had resolved to nothing at all), and an **annotated alias** whose assignment carries a
trailing comment (`ST_RAF="$MAXI_BUNDLE"   # …`, which had not resolved even though
`$MAXI_BUNDLE` did). What still cannot be resolved — a build shape outside that grammar,
an ambiguous bundle name, an empty glob expansion, an unreadable member — keeps the
refusal, and a literal present in no member is still reported absent. Touch a retained
pin's lines only when you are prepared to answer the gate for it.

One narrow exemption (issue #1002). A pin site whose only difference from its merge-base
self is a **sanctioned rename** declared in `lib/rename-map.json` is not new authorship,
and the gate withdraws it before the policy ladder runs. The comparison is exact — the
whole effective tuple (family, helper, literal, target path, target members, declaration)
must match — the superseded-to-current mapping is applied to the **merge-base side only**,
so a HEAD-side superseded spelling can never be laundered through it, and one base site
exempts at most one candidate. Names in the map's `frozen` block are never mapped, and an
absent or malformed map withdraws the exemption entirely rather than widening it. This is
a correctness fix to the comparison, not an amnesty: the gate previously resolved a
merge-base source image against current-tree path spellings, so across a rename it
measured path *spelling* rather than pin *identity*. Anything the exemption does not match
reaches the unchanged policy path, so a rename **plus** any other edit still answers the
gate in full.

`lib/test/pin-corpus-adjudications.tsv` contains only the current active adjudication
state. Every addition, removal, or change to that table must be authorized by an exact
branch change manifest; prior decisions remain available through Git history, the
historical migration certificate, and the frozen retirement manifests rather than
event rows in the active table. Prefer an ordinary
executable behavioral test over a static presence pin. Reviving a retired wording
literal requires both deliberate revival authorization and a genuine declared
structural boundary; a new boundary row alone does not make the revival valid.

**Retiring existence-only pins (issue #798, restated by #876).** What decides the
disposition is **whether the pin was buying a divergence check** — whether anything
depends on two or more homes agreeing. Find the pin's row in the frozen census
`.prflow/logs/pin-corpus-inventory.tsv` and walk these arms **in order, first match
wins**. Only arm 2 authorizes a *pin-only* removal; arm 1 permits removal solely
alongside a copy deletion, and arms 0 and 3 retain outright — so an unanswered
question always retains:

**Which corpus these arms govern (issue #1061).** They range over the **existence-pin
census** and nothing else — the sites `lib/test/pin-corpus-classifier.py`'s
`extract_existence_sites` yields, which are the calls to its `EXISTENCE_HELPERS` names
plus the presence-suffixed module wrappers `source_existence_helpers` admits. A pin of
any other shape — a count-family helper (`pin_count`, `devflow_module_pin_count`) or a
raw `grep -qF` presence check — is not a member and never has been, so **no arm below
decides it, arm 0's *retain* included**. Its disposition is the separate rule under
*Disposing of a pin outside the existence census*, after the arms.

0. **No row** — the census is a **frozen snapshot**, not a live index, so a pin added
   since its `# revision:` line has none. This is the normal state between refreshes,
   and it means the census *cannot answer*, **never** that the answer is "no".
   Either regenerate the census (below) and re-read, or **retain the pin**. This arm
   is about a row that is *absent* — obtainable, just not taken yet — and never about
   one that is **unobtainable** because the pin is not in this corpus at all; that is
   the case the scoping paragraph above routes elsewhere. Do not hand-count: the
   deciding number excludes the census's own
   `# counted-file-exclusions` set (`lib/test/`, `.prflow/learnings/`,
   `.prflow/logs/`, `.changeset/`, `CHANGELOG.md`), so a `git grep` over-counts.
1. **`counted_occurrences >= 2`** — remove the pin only in the same change that
   removes at least one of those copies; a pin-only removal is not an accepted
   disposition, because it leaves the duplicated content without its divergence
   check. This is the unchanged #798 rule. **Read `counted_occurrences`, not
   `homes`:** `homes` is the full home list *including* the excluded paths above, so
   the two columns routinely differ, and on a large minority of rows they select
   *different arms* — measured at revision `7b45285a`, 636 of 897 rows read
   `len(homes) >= 2` while `counted_occurrences < 2` (a past-time snapshot; the
   columns differed numerically on 848 of those rows). `homes` is not the deciding
   operand.
2. **`counted_occurrences < 2` AND the row's `bucket_final` is a prose bucket**
   (`prose-sole-copy` / `prose-multi-copy`) — the target is agent-executed prose no
   tool reads, the class `CLAUDE.md`'s *Recorded decision* bullet for issue #843
   governs. Then **a pin-only removal IS the accepted disposition**: retirement owes
   no copy deletion, because there was no second copy to protect. The compensating
   control is the review pass that reads the prose. **Before taking this arm, confirm
   the literal has no *wrapped* home:** `counted_occurrences` is derived by
   `pin-corpus-classifier.py`'s `_homes()`, a contiguous-byte substring test, so a
   home that carries the literal as wrapped adjacent string fragments is invisible to
   it exactly as it is to a `git grep`. That blind spot under-counts in the one
   direction that wrongly authorizes removal, so an unconfirmed literal retains.
3. **`counted_occurrences < 2` and any other `bucket_final`** — including `boundary`,
   which is what every row not moved into a prose bucket by a re-adjudication pass
   carries, in the window and out of it, so this arm is live for those rows whether or
   not a sweep is pending. A tool or
   consumer reads the target (a
   marker a tool parses, a routing-table row a module reconciles, a
   generated-artifact identity, a typed executable boundary), so **retain** the pin
   under the `# structural-pin-ok:` rule above.

Adjudications are *read* from the inventory but *changed* in
`lib/test/pin-corpus-adjudications.tsv` (the delta-gated table), then regenerated;
never hand-edit the generated inventory.

**Disposing of a pin outside the existence census (issue #1061).** Such a pin is
**outside the ledger's domain**, and each ledger disposition is structurally
unavailable to it rather than merely unused:

- **No census row is obtainable.** `extract_existence_sites` yields a site only for a
  helper in the existence set, and `source_existence_helpers` deliberately declines to
  admit count-family wrappers — a recorded decision its own docstring states. So such a
  literal has no site at any revision and therefore no adjudication key at all. Its row
  is not missing; it cannot be produced.
- **No row may be added by hand.** `pin-corpus-classifier.py` requires the adjudication
  table's key set to be exactly closed over the sites it extracts and fails generation
  on any key it cannot match, and
  `test_current_worktree_adjudications_close_the_classifier_corpus` in
  `lib/test/test_red_on_removal_retirement_manifest.py` enforces that against the
  working tree. **Do not add rows for non-existence literals** — that closure stays as
  it is.
- **A `# structural-pin-ok:` declaration does not rescue one whose literal resolves
  into prose.** The routing ladder weighs prose resolution *before* the bare
  declaration pass, and helper identity buys no exemption (issue #925), so a
  declaration clears a prose-resolving literal only in company with a `boundary` ledger
  row — the row the point above says cannot be minted.

The disposition is therefore taken **directly under the parent prose-pin policy**
(`CLAUDE.md`'s *Recorded decision* bullet for issues #843/#876), on that policy's own
question: does any tool or consumer read the pinned content? If one does — and the
routing ladder's step 1 will usually have said so already — the pin is **retained**
under the `# structural-pin-ok:` rule above, and nothing here authorizes removing it.
If none does, the target is agent-executed prose, retirement owes no replacement
coverage, and the pin is retired on that basis with **its disposition and the evidence
for it recorded in prose** — the issue or pull request that retires it — never as a
ledger row. That record carries the consumer search establishing no reader (run over
the consumer surface the lint's own `machine_consumer_evidence` reads, so it is the
same question the gate asks) and names what stops being asserted afterwards; the
compensating control is the review pass that reads the prose, which narrows the gap
and does not close it. Issue #1007's two literals are the worked case: both were
count-helper or raw-`grep -qF` pins, and PR #1067 retired them under exactly this rule,
with the per-literal consumer search and the accepted trade-off recorded on the issue
instead of in the table.

**Worked cases — the `#291` boundaries, which split across two arms.** Two of the
three `#291` sites (`291(AC1)` and the `291(AC4)` severity-calibrated-eval pin) carry
`counted_occurrences: 1` and take **arm 3**: review-and-fix Step 2.6 consumes the
cap's *consequence*, so they are retained even though the cap's applicability limbs
are read by nobody but the agent. The third (`291(AC4)`, the
`Decide-outcome-2 promotion` pin) carries `counted_occurrences: 2` and takes **arm
1** instead — same retention, different reason and a coupled copy-removal
requirement. Do not generalize one `#291` pin's arm to the others.

**Current state — arm 2 is populated, awaiting the sweep it authorizes (issue #1753).**
Arm 2 selected nothing until #885, because every census row was
adjudicated `boundary`. #885's re-adjudication pass walked every mechanically
prose-bucketed site, confirmed per site whether any tool or consumer reads the pinned
literal, and moved the ones nothing reads into `prose-sole-copy` — and the sweep that
immediately followed retired exactly those pins. **A retired site's row goes with it**
(a stale `literal:` key makes the classifier error), which drained the population back
to boundary-only. #946 then refilled and drained it again: step 1 brought
`lib/test/modules/review-and-fix-contract.sh`'s wrapper-routed pins into the corpus,
step 2's re-adjudication moved the 28 sites nothing reads into `prose-sole-copy`, and
step 3's sweep retired exactly those 28 pins with their rows. #1753 refilled it again,
for the create-issue-associated pins, and the sweep those rows authorize has not yet
landed. Read the authorization record for any pass in history — the census as of the re-adjudication
commit, plus the `pin-corpus-adjudication-changes` bundles, which name every key that
moved and every key that went. Expect the same shape every time: a prose-bucketed
population exists only between a re-adjudication and the sweep it authorizes.

Arm 2's condition reads the *recorded* `bucket_final` rather than an in-the-moment
judgment about who reads the prose, because the record is what a later reader can audit
— and changing a site's adjudication is itself delta-gated (below), so the record
cannot drift ahead of an authorization.
`test_final_inventory_realizes_only_authorized_buckets` in
`lib/test/test_residual_prose_retirement_manifest.py` is arm 2's coupled site: it holds
the shipped census to the legal bucket set, and holds every prose-bucketed row to arm
2's own precondition — a `counted_occurrences` matching its bucket, and an explicit
maintainer rationale rather than the classifier's mechanical fallback. That per-row half
ranges over whatever sits in a prose bucket at the time, so it is live between a
re-adjudication and the sweep it authorizes and empty otherwise; the bucket-set half
stays live over every row either way.

One limit on that population is worth knowing before you read a missing row as
permission. A site adjudicated `boundary` in the #885 or #946 pass was adjudicated **on
recorded evidence** — a consumer, a cross-file phase contract, or a wrapped second
home — so re-litigating one needs an evidence argument, not a fresh opinion. The
census's other former blind spot is closed: pins routed through the module-private
wrapper `lib/test/modules/review-and-fix-contract.sh`'s `_raf_pin_unique` used to sit
outside `PIN_CORPUS_SOURCES` and so outside the corpus entirely, with arm 0 governing
them; #946 step 1 brought that module in, step 2 adjudicated all 44 of its sites, and
step 3 retired the 28 of them nothing reads.

Refresh the census with a two-commit, inventory-free snapshot protocol: preserve the
prior snapshot in history; delete the inventory in the source/retirement commit;
generate the replacement against that exact inventory-free commit; and commit the
generated artifact separately. The source/retirement commit is intentionally
non-green while the artifact is absent, so never leave that intermediate commit as
the PR head.

Skipping that refresh is no longer undetectable (issue #962). The classifier resolves the
adjudication table **at the census's recorded revision**, so regenerating the census against
that revision faithfully reproduces the rationales it already carries however far the working
tree's table has moved on. `test_frozen_inventory_matches_its_recorded_revision` therefore
repeats its byte-comparison a second time, reconciling the working tree's adjudications into
the recorded revision's table, and names the drifting row and column when the two disagree.
Changing an adjudicated cell — a `bucket_final` or a rationale — for a key the census already
carries is RED, so a rationale correction is a census refresh, not a one-file edit.

What that comparison deliberately does **not** treat as drift is a key set that has moved.
A site that resolves a literal is keyed by a hash of that literal, so rewording a pinned
sentence re-keys the same adjudication, and the census — a frozen snapshot — keeps the old key
until it is next refreshed. (A literal-less site is keyed by its assertion identity instead,
which a reword leaves alone.) That lag is the designed, fail-closed behaviour (an absent census row reads as
*unanswered*, never as *no*), so only keys the two files share are compared; a key that exists
on one side alone is counted and reported in the failure message rather than being read as a
disagreement. A census refresh therefore remains driven by the two-commit protocol, not
demanded by every source edit that touches a pinned literal.

**Refreshing a frozen pin identity (issue #843).** Renaming a retained pin is a different
operation from retiring one, and it uses a different mechanism. The residual prose-pin
manifest `.prflow/logs/residual-prose-retirement-manifest.tsv` freezes each identity — source,
helper, assertion name, literal, target — against the base revision's committed pin-corpus
inventory, so a manifest row is **never** edited: an edit there breaks the historical partition
permanently. When a retained pin's guarded rule is legitimately renamed, declare the rename in
`lib/test/pin-identity-refreshes.tsv` — live hand-maintained maintainer intent, so it sits
beside its sibling `lib/test/pin-corpus-adjudications.tsv` rather than under `.prflow/logs/`,
which holds frozen audit artifacts — in the **same commit** as the source
rename. `lib/test/test_residual_prose_retirement_manifest.py` applies the declared mapping when
it realizes retained identities against the current tree, and admits a row only when the old
identity names a `RETAIN_BOUNDARY` identity in the frozen manifest, the old name is gone from
the tree, and the new one is present — so the rename and its re-freeze cannot come apart, and a
refresh cannot outlive the rename it recorded. This is not the two-commit inventory protocol
above: `.prflow/logs/pin-corpus-inventory.tsv` is a frozen census refreshed by its own
maintenance commits and owes no same-change update for a rename.

Two scope limits. The ledger covers renames of identities frozen in the **residual prose-pin**
manifest only — the sibling `.prflow/logs/residual-required-copy-retirement-manifest.tsv` makes
the same retained-vs-tree assertion with no mapping applied, so renaming a pin frozen *there* has
no refresh path yet and adding a row for it fails with `old identity is not a RETAIN_BOUNDARY row`.
And the ledger refreshes an assertion **name** only: changing a retained pin's literal or resolved
target changes the identity itself, which the ledger cannot express — that is a retirement, handled
by the manifest protocol, not by editing a refresh row.

**Declaring a repository-tree walk (issue #711).** `# tree-walk-ok: <reason>` is a
member of the same declaration-marker family (`# structural-pin-ok:`, `# raw-guard-ok:`,
`# tree-walk-ok:`, `# argjson-ok:`, `# pruned-path-ok:`, `# glob-ok:`), in the same one-line-reason framing. A tracked `.py` or `.sh` file under `lib/test/`
that enumerates with a recursive walk — `rglob(`, `os.walk(`, `iglob(`, a `recursive=True`
call, a `glob(` whose pattern carries a `**` component or is not a string literal (these two
are judged by a Python parse, so they apply to `.py` files only), or a shell `find` / `grep -r`
rooted at the repository root — must carry that marker on the walk's line, or source its
population from an index-reading `git ls-files` instead. **The walk's own line is always the
safe placement.** Span acceptance — the marker anywhere within a statement — applies only to a
multi-line `glob(`-family call judged by the Python parse and to a `\`-continued shell
statement; the four literal tokens (`rglob(`, `os.walk(`, `iglob(`, `recursive=True`) are judged
line by line, so a wrapped one must carry its marker on the token's own line. The reason exists
because a root-anchored walk descends into every sibling worktree under `.claude/worktrees/`
and reports a count that has nothing to do with the repository's state. `lib/test/lint-tree-enumeration.py`
turns the suite RED for an undeclared walk; it never judges what a reason claims, so a marked
walk still ships — it ships visibly.

**Declaring an unguarded filename pattern in a shipped shell fence (issue #1211).**
`# glob-ok: <reason>` is the newest member of that same family. A fenced shell snippet
under `skills/` is prose an agent runs verbatim, in whatever shell its harness supplies —
commonly zsh, whose default `nomatch` makes an unmatched filename pattern a refusal of
*that one command*: the shell prints `zsh: no matches found: <pattern>` and skips it, then
carries on with the rest of the block (no skill fence sets `set -e`). The harm is a
silently empty enumeration — nothing distinguishes "there is nothing here" from "the shell
declined to look". The standard remedy is one line beside the glob, inside the same fence:

```bash
[ -n "${ZSH_VERSION:-}" ] && setopt nonomatch || :
```

It is a no-op on every other shell (`$ZSH_VERSION` is unset, `&&` short-circuits, `|| :`
holds the exit status at zero). Reporting the empty case explicitly is better still.
`lib/test/lint-skills-glob-guard.py` (driven from `lib/test/run.sh`) is the mechanical
backstop: it flags the narrow, high-confidence shape only, and is discharged by either
that guard line earlier in the same fence or a `# glob-ok: <reason>` marker. It
deliberately claims no completeness — its recognised shape and its accepted residuals are
enumerated in the helper's own module docstring, which is the place to read them rather
than a copy here that would drift. The written convention is the primary control; the
check is the backstop for the commonest shape.

### Regenerating suite-owned artifacts

Several suite gates compare a checked-in generated artifact against what the tree
implies, so a source edit can turn the suite red until the artifact is refreshed.
Run one batched pass after each edit batch:

```bash
lib/test/regenerate-artifacts.py
```

and one more with the opt-in floors row immediately before the whole-suite pass you
intend to claim completion on:

```bash
lib/test/regenerate-artifacts.py --with-floors
```

The bare form writes nothing (the cloud-writer runtime manifest,
`scripts/devflow-cloud-writer-contract.json`, is no longer a registry row — as of issue
#1445 it is written on `main` alone) and runs a **non-writing** check for each
judgment-gated artifact, reporting every judgment item together in one pass instead of one
red run at a time — about a second in total. `--with-floors` adds the one
opt-in row, which measures every exact-policy module through the real focused runners
(minutes, not milliseconds) and may raise the assertion floors in
`scripts/workflow-flight-recorder-registry.json` and their coupled `lib/test/run.sh` call
sites from that measured tally, never lowering either. The default pass prints an
explicit `not measured` line for that row rather than staying silent about it, and skips
it even under the flag when an earlier row has already reported the tree red. Deferring it
is a bounded gap, not a free one: the module harness and the `modules-*` shards fail only
a tally *below* the floor, so a floor left un-raised is caught by
`test_module_runner.py`'s equality assertion, which executes every exact-policy module on
CI — meaning a stale floor surfaces on CI rather than in your own run unless you run the
flagged pass before a completion claim.
The registry inside the helper is
the sole enumeration point — run `--list` for the current set rather than trusting a
copy here, which would go stale the next time an artifact is added. Judgment items are yours to resolve deliberately — the helper never
edits them. Exit codes: `0` clean, `1` action required, `2` infrastructure failure
(which wins over `1`). Use `--list` to see the registered artifacts and `--repo-root` to
point it at another checkout.

#### The parallel coordinator refuses to launch on a drifted artifact

Running the batched pass is a discipline, so it can be skipped — and before issue #1244 a
stale generated artifact was then caught only by a full ~13-minute suite run. The parallel
coordinator `lib/test/run-parallel.sh` now closes that gap mechanically: before it launches
any shard it runs `lib/test/regenerate-artifacts.py --preflight`, a **read-only** pass over
the registry's sub-second, non-writing rows (the judgment-gated `--check` rows; the
multi-minute `exact-module-floors` row is declared ineligible, and the cloud-writer manifest
is no longer a registry row at all — it is written on `main` alone as of issue #1445). On detected drift the coordinator prints the failing row and its governing
policy, launches no shard, and exits non-zero in under a couple of seconds — so you fix the
artifact with the batched pass above rather than paying a whole suite run to discover it. An
*inconclusive* preflight (a crash, an unreadable exit, or a disabled check) warns and
launches the shards anyway: detected drift fails closed, an unestablished check does not. The
preflight is read-only and reconciles nothing — the batched `regenerate-artifacts.py` pass
stays the only writer, and running it after your edits is what keeps the coordinator from
refusing your own launch. It touches neither `.github/workflows/ci.yml` nor
`lib/test/run-shard.sh`, so CI's per-shard behaviour is unchanged.

#### The registry is also the merge-conflict oracle

When a branch update lands a merge conflict in a checked-in **generated** artifact, do
not hand-merge its bytes: hand-merged bytes match no source of truth, so the artifact's
own suite gate then reports them as drift with a remedy aimed at the wrong file, while
silently reverting whatever the other side added. The same registry answers what to do
instead, via `--list`:

- `conflict-path <row> <path>` — the generated paths a conflict in that row can land in.
- `conflict-class <row> <class>` — one of `regenerate` (re-run the row's generator against
  the merged tree), `reconcile-source` (merge the *source* first, then regenerate), or
  `by-hand` (a genuine hand-merge is correct for this row).
- `conflict-recipe <row> <text>` — the row's governing policy, reused verbatim as the
  recipe so the batched pass's `governing policy:` output and this rule cannot drift.
- `conflict-sibling <row> <path> <class>` — a coupled path a row's conflict can also touch,
  governed by **that line's own** class (e.g. `lib/review-profile.tokens`, the reviewer
  security-boundary lock the capability generator never writes, is `by-hand`).

These four line kinds are emitted strictly *after* the existing `artifact` lines,
whose format is byte-unchanged, so prefix-anchored consumers parse as before. The
rule is fail-closed at both ends: a conflicted path that is **not** among
the emitted `conflict-path`/`conflict-sibling` paths is an ordinary hand-merge, and a
`--list` that cannot run — or that emits no `artifact`/`conflict-class` lines — means
needs-human-reconciliation and stop, never a guessed hand-merge.

Autonomous `/prflow:implement`, `/prflow:review-and-fix`, and `/prflow:receiving-code-review`
runs apply this automatically: the rule lives, byte-identical, in the three
`.prflow/prompt-extensions/` files, and each skill's in-run conflict arm carries a generic
pointer to it. Adding a new artifact row therefore extends the conflict rule with no prompt
edit — the registry stays the sole enumeration point.

### Authoring a new focused module

When you extract a cohesive block of `lib/test/run.sh` coverage into a new
selectable module, complete all of the following in the same PR:

1. **Registry entry** — add the module to `test_modules` in
   `scripts/workflow-flight-recorder-registry.json` with its `path`,
   `minimum_assertions` floor, and a `description`.
2. **Floor from the extraction-time count** — establish the floor with the
   over-floor probe under the already-granted direct `lib/test/run.sh`
   invocation: set the registry and call-site floor to a deliberately over-high
   value, run the suite, read the boundary's below-floor line
   (`executed N assertions; minimum is M`) to obtain the true executed count `N`,
   then set the floor to `N` (the boundary's success path prints no count, so a
   floor seeded without the probe is unverified).
3. **Mirror the floor at the call site** — the same floor literal appears at the
   `run.sh` `devflow_run_full_suite_module` boundary call. The registry floor and
   the call-site literal are one coupled contract, cross-checked for every module
   by `lib/test/test_module_runner.py`.
4. **Per-module inventory** — add `lib/test/modules/<module-id>.inventory.md`
   recording the module's provenance (source baseline + coverage groups). When
   the extraction deliberately leaves sibling candidates in `lib/test/run.sh`,
   record each one and the reason it stayed, so the residue is a stated decision
   rather than an omission (`harness-python-guards.inventory.md` is the model).
5. **CI shellcheck list** — add the module's `.sh` path to the explicit
   shellcheck file list in `.github/workflows/ci.yml` (module files are not
   globbed there; the glob excludes `lib/test/` because that tree carries
   deliberately-malformed fixtures). This is enforced:
   `lib/test/lint-carveout-guard.py`, driven from the suite, turns the run RED
   and names the path when a tracked `lib/test/**/*.sh` file is neither in the
   set `ci.yml` actually lints nor under the one exempt prefix
   `lib/test/fixtures/` (issue #745). Put the new file on one side or the other
   — there is no third option.
6. **Coverage-map ownership** — update `lib/test/modules/coverage-map.json` so
   each `lib/`/`scripts/` depth-1 unit the module now owns names it as `owner`.
   `owner` answers "which registered shell module carries this unit", so a
   `scripts/*.py` or `lib/*.py` helper whose coverage lives in a
   `lib/test/test_*.py` file correctly stays `unmodularized` and instead records
   that test in the optional `focused_test` field (issue #789), which the ratchet
   validates as a git-tracked, `test_*.py`-named file that is executable in the
   index — the exec bit is what makes it invocable as a direct leading token on
   the cloud tier. Record the mapping explicitly; it is never inferred
   (the coverage ratchet, `lib/test/coverage_map_guard.py`, fails the suite RED
   on a stale, misfiled, or unlisted unit). If the ratchet fires on a code
   extension outside the five depth-1 patterns, extend the pattern set (a map +
   guard + this convention change in one PR) — never list a code file in
   `non_code_exempt`. The `run_sh_blocks` half is **derived and enforced** by the
   guard, not hand-maintained: it scans `lib/test/run.sh` and every
   `lib/test/modules/*.sh` at assertion-name position and fails RED on a `run.sh`
   label with no map entry, and on a **fully extracted** label (carried by a module,
   asserted nowhere in `run.sh`) whose entry is absent or still names
   `unmodularized`. A **partially extracted** label — one a module carries while
   assertions remain in `run.sh` — correctly keeps `unmodularized`, because a single
   `owner` string cannot describe split coverage. Repair a *ratchet violation* (a
   label the tree asserts but the map does not carry) with
   `python3 lib/test/coverage_map_guard.py . --fix` rather than by hand. **A merge
   conflict in this file is a different case — `--fix` is NOT the remedy there**
   (it cannot restore a key a resolution dropped); register the JSON-aware merge
   driver or take both sides by hand, and let the CI key-retention check backstop it
   (see *Coverage-map block ownership* under Running the tests for both).
7. **Module-contract compliance** — the module must satisfy the module contract
   documented in `lib/test/module-harness.sh`'s header (private fixture root and
   cleanup, caller-provided `LIB`/`RESULTS_FILE`/`assert_eq`, no self-skip, no
   monolith helper). Comply **by reference** to that header — do not restate its
   cleanup/trap terms here, so this checklist cannot go stale as the contract
   evolves. "No self-skip" bars the raw `skip` helper, not a host that genuinely
   cannot express a condition: declare that through `module_host_capability_skip`
   (issue #838), whose contract the same header documents.
8. **Focused-runner smoke test** — add a `runs_green_through_the_real_runner` test
   for the module to `lib/test/test_module_runner.py`, matching the shape the
   existing module tests use: invoke `lib/test/run-module.sh <module-id>`, read the
   module's `minimum_assertions` floor from
   `scripts/workflow-flight-recorder-registry.json`, and assert the emitted summary
   line equals `Module <module-id>: {floor} passed, 0 failed` (read the floor from
   the registry, never a second hard-coded copy). This drives the module through its
   *own* runner — the assertion issue #695 exists to make — so the convention that
   the existing modules already follow stops being convention by accident (issue
   #719). When a module's heaviest unit is already run in full by a module shard,
   this test may pass `--heavy-units smoke` so the shard's execution is not paid a
   second time here (issue #890); the three requirements above are unchanged by it,
   and the run still asserts the emitted tally equals the registry floor.
9. **Routing classification** — when the extraction moves a `lib/test/test_*.py`
   suite from a `lib/test/run.sh` invocation to a module driver, move its name in
   `lib/test/test_module_runner.py` from `SERIAL_BY_EXCLUSION_SUITES` to
   `MODULE_DRIVEN_SUITES`, and delete the `run.sh` invocation in the same change.
   Since issue #867 those tuples are not a hand-maintained taxonomy: the suite
   asserts each membership claim against the tree, matching the `$LIB`-anchored
   quoted invocation shape `"$LIB/test/<name>"` (never a bare basename, so a
   comment mentioning the path neither satisfies nor violates a claim). A
   `MODULE_DRIVEN_SUITES` member must occur zero times in `lib/test/run.sh` and in
   exactly one file across `lib/test/modules/*.sh` plus
   `lib/test/module-harness.sh` — distinct files, not occurrences, since one
   module legitimately carries several occurrences for a suite it drives. A
   `SERIAL_BY_EXCLUSION_SUITES` member must occur at least once in
   `lib/test/run.sh`, which is what catches a deleted driver block.
   `POOLED_SUITES` carries no such assertion: it is already pinned by set
   equality against `run.sh`'s parsed `devflow_pool_open` triples, a stronger
   guarantee. Leaving a stale invocation behind, or reclassifying without moving
   the driver, turns the suite RED at the desk naming the offending suite.

The suite reports passed, failed, and *skipped* tallies (issue
#456) — so `0 failed` is never mistaken for "everything ran." A check can
**self-skip** when the environment cannot run it or express its condition; with
nothing skipped the summary is byte-identical to before (`N passed, M failed`),
and with skips it reads `N passed, M failed, K skipped` followed by one line per
skipped check naming the check, its **kind** (`blocking-gate` for a real gate
that should have run here but could not, `host-capability` for a condition the
host cannot express), and the reason. The exit code is unchanged — a skip never
fails the suite. The summary renderer lives in `lib/test/summary.sh`.

## Conventions

- **Skills reference bundled files via the portable single-statement anchor
  `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../<dir>/…`** so they
  resolve regardless of install location and runner (`$CLAUDE_SKILL_DIR` on Claude Code;
  the runner-reported skill base directory substituted for the placeholder elsewhere —
  never assigned to a shell variable read by a later statement, which some runners'
  inline-bash marshaling drops). Never hardcode `.prflow/vendor/prflow/…`
  in a skill (the cloud-tier *workflows* are the one exception — see below).
- **Portability:** avoid GNU-only flags. Use `python3` for date math (not `date -d`)
  and ERE / `sed -E` (not `grep -P`).
- **Windows / non-UTF-8 hosts.** The helpers self-defend at two layers: a committed
  `.gitattributes` pins every `*.sh`/`*.py`/`*.jq` to `eol=lf` on checkout (so
  `core.autocrlf=true` can't turn a shebang into `bash\r`), and every first-party
  `scripts/*.py` forces its own `stdout`/`stderr` and `gh` I/O to UTF-8 (so an em-dash
  or emoji can't trip a cp1252 codec). A **third, distinct** layer decodes the local
  text files a helper reads as input: `parse-acs.py --body-file`, `workpad.py`'s
  section-file flags (`--replace-plan-file`/`--replace-acs-file`/`--set-reproduction-file`,
  via a shared `_decode_utf8` helper) and `branch-for-issue.py --title-file` pass
  `encoding="utf-8"` explicitly instead of the ambient locale codec, so UTF-8 issue text
  survives on a non-UTF-8 default host — separate from the stream/subprocess hardening
  above, which governs the helpers' own streams and `gh` I/O rather than the files they
  read. A decode or OS failure routes through the parser, workpad, and branch-create
  clean non-zero paths (a flag-specific diagnostic, no traceback, no partial output, and
  no GitHub PATCH on the workpad path); an AST guard over tracked `scripts/*.py` fails the suite on any new
  ambient-codec `read_text`/`Path.open`/builtin `open` text read. Two caller-side traps
  remain the contributor's responsibility on Windows, because they corrupt output
  **after** the helper ran cleanly:
  - **bash file-association.** Invoking a `.sh` via the `git-bash.exe --no-cd "%L"`
    file association (e.g. from PowerShell) can capture no stdout while exiting 0 —
    invoke `bash` explicitly with a POSIX path (`bash scripts/foo.sh`), never rely on
    the `.sh` double-click / file-association launcher.
  - **PowerShell 5.1 `>` / `Out-File`.** These re-encode captured stdout to UTF-16LE
    (a `FF FE` BOM + interleaved null bytes), which was the original cause of
    workpad-comment corruption. Capture helper output from a UTF-8 shell (Git Bash,
    WSL, `pwsh` 6+), or use `cmd /c "... > file"` / an explicit UTF-8-no-BOM write —
    **never** PowerShell 5.1 `>` or `Out-File`.

  If you already checked out the tree under `core.autocrlf=true` before `.gitattributes`
  existed, renormalize once with `git add --renormalize .` (or re-clone) — `.gitattributes`
  governs future checkout/normalization, not a tree that is already CRLF on disk.
- **No secrets, owner-specific IDs, or product names** in committed files. Config
  lives in `.prflow/config.json` (created from the example). This repo **tracks**
  its live `config.json` — force-added past the `/.prflow/*` ignore rule with
  `git add -f` so the cloud tier reads it from the committed tree — so keep secrets
  and owner-specific IDs out of it. The `.prflow/learnings/` corpus
  (`retrospectives.jsonl`, `experiment-records.jsonl`, `overrides.json`) is likewise
  tracked and published — re-included by the `!/.prflow/learnings/` negation in
  `.gitignore` — so keep host-local and owner-identifying data —
  operator home-directory paths, account names — out of it too;
  `lib/materialize-retrospectives.sh` rewrites operator home prefixes to `~` on the
  merge write path as a backstop, but the rule is the primary guard.
- New `.py`/`.sh` files carry an SPDX header:
  ```
  # SPDX-FileCopyrightText: 2026 Daniel Radman
  # SPDX-License-Identifier: MIT
  ```
- **Every `skills/*/SKILL.md` carries the standardized consumer prompt-extension
  step.** As a preflight, each skill invokes
  `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh <skill-name>` and honors
  any returned text as instructions appended verbatim to the end of its own prompt — the
  consumer-owned, upgrade-safe `.prflow/prompt-extensions/<skill-name>.md` (absent or
  empty → no-op). **Which checkout supplies those bytes is a per-tier question, separate
  from who owns the file:** the cloud review tier checks out the pull request's head, so
  the extensions it loads come from the trusted base ref through
  `DEVFLOW_PROMPT_EXTENSION_ROOT` instead (issue #874) — see
  [`docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md`](docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md)'s base-ref trust
  boundary bullet for the canonical statement. A skill's own load step is unchanged by
  that: it invokes the helper identically on every tier. When you **add a new skill**, copy this step verbatim (substituting the
  new skill's directory name) so it inherits the convention, **and** add the new skill's
  name plus a one-line hint to the prompt-extension scaffold list in
  `scripts/scaffold-config.sh` — `/prflow:init` scaffolds one inert
  `<skill-name>.md.example` per skill, so a new skill needs a matching example. Two
  coverage tests in `lib/test/run.sh` enforce both halves: one enumerates every
  `skills/*/SKILL.md` and fails if a skill omits the standardized step, and the
  prompt-extension scaffold test derives the expected example set from `skills/*/` and
  fails if the scaffolder's list forgets one.
- **A skill loads the extensions its behavior draws on — usually one, sometimes more
  (issue #620).** The step above is a floor, not a cap: a skill that applies *another*
  skill's principles without invoking that skill loads that skill's extension too, so the
  policy follows the behavior rather than the invocation. `/prflow:review-and-fix` is the
  instance — its preamble loads `review-and-fix` and then `receiving-code-review`, because
  the fix loop applies those principles without ever invoking that skill. When you add or
  change a skill, ask which other skills' principles it applies un-invoked. The rule and
  its coverage are stated in
  [`docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md`](docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md) under *Extending
  skills with prompt extensions*.
- Prompt cutovers, trims, and relocations follow the advisory sole-owner discipline in
  [`CLAUDE.md`](CLAUDE.md)'s **Helper cutover** convention, with the lean-prose guidance in
  [`.prflow/prompt-extensions/implement.md`](.prflow/prompt-extensions/implement.md)
  under **Keeping prompt prose lean**.

## Cloud-tier workflows

The `.github/workflows/*.yml` files run inside GitHub Actions, where they reference
plugin scripts at `.prflow/vendor/prflow/scripts/…`. That path assumes the cloud
tier is used with the plugin **vendored** into the consuming repo at that path (see
`docs/internal/cloud-setup.md`). This is intentional and distinct from the local skills, which
resolve the portable `${CLAUDE_SKILL_DIR:-…}` anchor at runtime.

## Submitting changes

1. Branch and make focused changes, iterating on the module that covers the
   surface you touched (see *Running the tests*). Before marking the PR ready,
   commit and push, then read CI for that pushed commit following `CLAUDE.md`'s
   rung 1 — since issue #1607 made that reading this repository's local-tier
   whole-suite gate. Run the suite locally when you want its richer failure
   detail to troubleshoot from; that run is not the gate.
2. Open a PR with a clear description. If your change reaches consumers (the engine surface —
   `skills/`, `agents/`, `lib/`, `scripts/`, the workflows, the config schema), add a
   **changeset** instead of editing `CHANGELOG.md` or `.claude-plugin/plugin.json`: create a
   uniquely-named `.changeset/<slug>.md` with a `bump: patch|minor|major` frontmatter key and
   your Keep-a-Changelog prose (PR-cited). See [`.changeset/README.md`](.changeset/README.md).
   Internal-only changes (tests, CI, dev-only docs) need no changeset.
3. Be kind in review (see `CODE_OF_CONDUCT.md`).

### Versioning (changesets)

PRFlow versions itself with changesets so concurrent PRs never collide on the `version` line
or the top of `CHANGELOG.md`. Each PR adds a `.changeset/*.md`; when it merges to `main`, the
`version-consolidate` GitHub Action (`.github/workflows/version-consolidate.yml`),
running `scripts/consolidate-changesets.py`, bumps
`.claude-plugin/plugin.json` by the **highest**
pending bump type, prepends one dated, PR-cited CHANGELOG entry assembled from all the pending
prose, deletes the consumed changesets, and commits to `main` with a `chore: bump version`
subject. A malformed changeset fails the Action loudly; with no pending changesets it is a
clean no-op. Cadence stays per-merge — every merged *engine-surface* change (one carrying a
changeset) still ships as a version increment; an internal-only merge with no changeset is a
deliberate no-op (no bump).
