---
schema: 1
kind: cutover
---

# Cutover record — issue #795: Step 3.6 state-owner round-trips

**What changed.** `/prflow:create-issue`'s Step 3.6 audit lifecycle stopped paying a Bash
round-trip for work the state owner already knows how to do. `scripts/issue-audit-state.py`
resolves an omitted `--round` where the state uniquely determines it, publishes a `next_call=`
suggestion naming the next legal invocation, and answers the Step 3.6 → Step 4 boundary in one
composite read; `scripts/render-audit-prompt.py` folds its `dispatch-pointer:` line onto stderr so
the orchestrator needs no second extraction step. The measured round-trip cost this addresses, the
accidental-caller-contract-failure rate that motivated the `next_call=` channel, and the stamped
baseline for both live in [`create-issue-context.md`](../create-issue-context.md), which is the
single source of truth for that axis; no figure from it is restated here.

## Superseded prose, deleted in the same change

The *Prose cutover* convention retains policy, invocation contracts and stop conditions in the
skill and removes operative decision logic once an executable helper is its sole tested owner.
Three passages left `skills/create-issue/references/step-3-6-audit.md` on that rule:

- **The standalone `dispatch-pointer:` read-back fence** — a `python3 -c` extraction loop plus the
  paragraph mandating it and forbidding `grep`/`sed`/`awk`. The generator now emits that line on
  its own stderr in the invocation that writes the file, so no extraction runs at all and the
  non-preflight-PATH-tool constraint the paragraph existed to enforce is satisfied by
  construction. `scripts/render-audit-prompt.py` is the sole tested owner.
- **The four back-to-back boundary reads** (`query-triggers`, `query-convergence`,
  `query-coverage`, `query-calibration`) and the prose walking their combination. `query-boundary`
  answers the composite decision; `query-coverage` survives in the sequence only because its
  per-dimension rows are still needed. The four individual queries are **not** retired and answer
  exactly as before — the collapse is at the call site, not in the tool's surface.
- **The closed Queries enumeration** naming the multi-line read-back class. It is now
  `_MULTILINE_READBACKS` in the state owner, reconciled by
  `lib/test/check-audit-lifecycle-contracts.py` against the choices `build_parser()` registers.

`record-adjudication-render` additionally left the ordered unconditional call sequence: the state
owner *refuses* it with `no-records` on a round grading no advisory or invalid finding, so the
sequence had been prescribing a call that cannot succeed on the clean path.

## Why a default `--round` is not uniform

The rule the defaulted subcommands share, and the ones that keep `required=True` do not, is
whether the flag **names** a state-determined round or **selects** which operation runs.
`_ROUND_DEFAULTED` — `query-next-action`, `record-return`, `record-adjudication`,
`record-adjudication-render`, `record-coverage` — is the first class. `record-dispatch` is the
worked counter-example and the reason this is not a blanket change: `--round` is the branch
discriminator `_find_round` reads before any validation, so a default there would route an
intended same-round retry into opening a new round, silently spending the automatic re-audit
budget and making the still-open refusal unreachable. `record-creation-epoch`, `record-degraded`
and the cross-round id-scoped channels keep the flag for the same reason.

`check_round_defaulted` grades both halves. Comparing the constant against parser optionality
alone says the flag *may* be omitted and nothing about whether the handler resolves the round — a
member added to both the constant and the parser's optional set with the resolver call forgotten
would run with `args.round is None` into round-keyed guards. The guard therefore also walks each
member's handler and requires the resolver call.

## What `next_call=` is, and what it deliberately is not

It is a **generated suggestion the caller reviews before running, never an instruction.** The
decided answer line is unchanged and stays first; `next_call=` is second and final, in one of
three shapes — an invocation line, `next_call=none`, or `next_call=unestablished reason=<token>`.
State-derivable operands are filled; caller-supplied ones are named bare in a `needs=` field and
never guessed.

Two properties of that split are load-bearing and were live defects a review round caught:

- The caller-intent classification keys on the subcommand being **rendered**, not the one doing
  the rendering. Keyed on the emitter the guard could never fire — `query-arm` rendering a
  `record-dispatch` call filled `--round` from state and omitted it from `needs=`, handing the
  caller a pre-decided branch discriminator, the exact fail-open the class exists to prevent.
- The suggestions are reconciled against the target subcommand's own required-flag set, and the
  reconciliation additionally **runs** the tool's printed suggestion and requires it not to
  refuse. An argparse-only reading cannot see `record-dispatch`'s arm-conditional `--draft-file`
  requirement, which is enforced in the command body — so the most common lifecycle path was
  publishing a suggestion that refuses when copied.

The exclusion set is `_NEXT_CALL_EXCLUDED`: `emit-body` (its stdout is the payload a trailing line
would corrupt, which `record-creation-attestation` would then report as a digest mismatch),
`check-claim-staleness`, and every member of `_MULTILINE_READBACKS`.

The channel fails **soft and loud**: a render failure prints `next_call=unestablished
reason=render-failed` rather than dropping the line, the reason vocabulary is one closed set
validated at its single construction point, and an `AssertionError` — which comes from the
module's own self-checks and means the tool is wrong rather than the input — carries a distinctive
`CONTRACT VIOLATION` marker. All of these still exit 0: a suggestion channel must never turn a
succeeded call non-zero.

## `resolve-main-root.sh`: a selection derived through a non-preflight PATH tool

`git worktree list --porcelain` was parsed with `head`/`sed`/`grep`. `lib/preflight.sh` guarantees
only `git`/`gh`/`jq`/`python3`+PyYAML, so on a host whose `PATH` carries only the guaranteed set
the pipeline emitted `command not found` and yielded an **empty** `main_root` — falling back to
`pwd`, which inside a linked worktree is the *worktree* root, not the main root. The bound
canonical draft root was silently wrong with no error. It now parses with bash builtins only
(`while IFS= read -r`, `case`, `${var#prefix}`). Its always-exit-0 contract, `pwd` fallback and
breadcrumb text are unchanged.

One **scoped divergence** from the retired form is recorded at the call site rather than papered
over: `head -n 1` took record 1's literal first line whatever it was, while the loop takes the
first `worktree `-prefixed line in the record. `git` always opens a record with `worktree `, so
the two agree on every output `git` actually produces; the divergence is confined to input `git`
does not emit, and there the new form is the more robust of the two.

## Pin disposition — three deletions, none re-worded

- **`#768`: "never `grep`, `sed`, or `awk`" and "byte-identically to the line inside the written
  file"** — **deleted.** Their literals described a fence the skill no longer ships. Their
  guarantee did not go with them: `lib/test/run.sh`'s `#795` block now asserts it as a real
  executable property — the stderr line is byte-identical to the `dispatch-pointer:` line inside
  the stdout the same invocation wrote, that line is non-empty (the positive control against a
  vacuous empty-vs-empty compare), exactly one such line reaches stderr, and stdout still opens
  with the mode's own marker. That is a stronger anchor than either pin was; neither could have
  caught a fold emitting a re-derived or truncated line.
- **`#603`/AC14's multi-line read-back enumeration** — **deleted, not extended to name
  `query-boundary`.** Its own marker rationale said "presence only … no code regression to
  mutate", which is the wording-only signature this repo prohibits; adding a sixth multi-line
  query while leaving the five-name clause untouched would have kept it GREEN over a sentence the
  addition had just falsified.

**The scope of that re-anchor, stated exactly.** `check_readbacks` reconciles the state owner's
**module docstring** against the dispatched set. The deleted pin sat over
`step-3-6-audit.md`'s own enumeration, and the skill-prose↔code axis is *not* what the guard
grades. What makes the deletion sound is the prohibition itself: a skill-prose enumeration is
agent-executed prompt text whose only reader is the runtime agent, so per the recorded decision
under `CLAUDE.md`'s guard-executable-behavior convention it carries no automated regression
coverage by design, and its compensating control is the review pass that re-reads the shipped
prose each run. Do not read this record as a claim that both enumerations are machine-guarded —
one is, one deliberately is not.

## The reconciliation guards, and why they are not greps

`lib/test/check-audit-lifecycle-contracts.py` (driven from `lib/test/run.sh`) is machine-consumed
reconciliation, not prose presence. Its arms compare the shipped enumerations against what the
parser and the handlers actually expose: read-backs vs. `_MULTILINE_READBACKS`, the exclusion set
vs. the emitter's refusals, `_ROUND_DEFAULTED` vs. parser optionality **and** the handlers'
resolver calls, every `_NEXT_ACTIONS` member routed by one of the two `next_call=` tables with no
dead entry, both flag vocabularies against registered options, and — since issue #1466 — the
**reverse** of the sequence arm: every state-owner subcommand either reference file invokes inside
a ```bash fence must be named in the ordered sequence, in the declared `_FENCE_EXEMPT` set, or in
`_CONDITIONAL`. That reverse arm is what stops the sequence from *omitting* a call the documents
mandate; its reach is the ```bash fences alone, so a call written only in prose backticks stays
outside it — a sizeable minority of the sequence's distinct calls. It **refuses** a
subcommand-shaped token in the ordered sequence that the parser does not register rather than
silently skipping it — skipping is selection, not validation, and a typo had lowered the derived
figure by one while the success line still claimed "every one a registered subcommand".

The checker's own fail-closed arms are driven: every prior run was over a clean tree, so it had
only ever been observed passing. Planted-defect rows drive the `flag-vocabulary`,
`next-action-routing`, `read-backs` and `round-defaulted` refusals, and a further row requires the
unmutated checker to still pass, so those rows grade a live guard rather than a permanently-red one.
The arms are **sampled, not exhaustively covered** — `readonly-complement`, `emitting-complement`
and `sequence` have no `#795 checker:` planted-defect row of their own, and the first two are
observed only on the passing path. (`sequence` is driven to a Refusal by the #1466 rows below, which
reach it through the same crafted documents.) Read the driven set from those rows in
`lib/test/test_python_scripts.py`, not from a count copied here.

Issue #1466's reverse arm arrived with its own rows on the same pattern, driven mostly against
crafted reference documents, with one mutating `_FENCE_EXEMPT` to plant an unregistered exemption.

## Measurement

The per-round unconditional call count is **derived from the shipped prose, not transcribed**, and
`lib/test/run.sh` prints it on every green run as a `MEASURE  #795 …` line carrying
`unconditional_call_count=` and `registered_subcommand_count=`. It is also *pinned*, so an added
unconditional call turns the suite RED rather than only moving a printed figure.

**The figure rose by three at issue #1466, and that rise is a correction, not a regression.** The
repaired sequence adds `query-round-kind` once and `record-staged-write` twice, so the derived
count moved from 18 to 21. No behavior changed: those three calls were always being made — the
state owner refuses a fresh file-arm dispatch that finds no recorded staged write, and refuses a
`record-dispatch` with no `--kind`, so the pre-dispatch pair is tool-enforced; the presentation
write's `record-staged-write` is prose-mandated by the shared write procedure. Only the document
omitted them, so the rise measures the prose catching up with the run. Read a later green MEASURE
line against that baseline rather than against the pre-#1466 one.

**Issue #1751 moved the figure again, and this time behavior did change.** With every fresh-context
audit round now offered to the user before it opens, the mandated call sequence is re-ordered so the
`record-offer` election precedes the first `record-dispatch`, and the calls that a round now takes
only when the user elects it are re-classified as conditional in `lib/test/check-audit-lifecycle-contracts.py`'s
`_CONDITIONAL` set (whose first member is `record-offer`) rather than counted in the per-round
unconditional list. The derived `unconditional_call_count` therefore moves, and the pinned
`ALC_795_EXPECT` in `lib/test/run.sh` moves with it. Read the live MEASURE line — not a number
copied here — and read it against the post-#1751 baseline.

The real-corpus before/after record, the stated reason its "after" row is a post-merge obligation
rather than a pre-merge figure, and the reproduction recipe that produces it are in
[`create-issue-context.md`](../create-issue-context.md). The unfilled row there is unfilled by
decision, not by omission; do not fill it from a pre-merge corpus, which would re-read runs that
executed the pre-change lifecycle and report a change of zero.

## Schema, grants and shipping coupling

`SCHEMA_VERSION` stays **3**. Every mechanism is additive at the output layer and reads state the
file already holds; no new state key, no changed stored shape. A create-issue run can span
sessions, so a state file written before the change stays readable by the changed code mid-run —
which the unchanged `_REQUIRED_TOP` set and validation spine already guarantee.

**No new tool grant.** `/prflow:create-issue` is local/interactive-tier only, every invocation
introduced or modified is `python3`-headed, and `lib/capability-profiles.json`, its five generated
allowlist literals and `lib/review-profile.tokens` are byte-identical after the change.

**No shipping skew.** Both halves — `scripts/` and `skills/` — reach a consumer repo through the
single `prflow_version` vendor fetch, so there is no `install.sh` workflow half and no
two-artifact skew of the #502/#455 class.

## Coupled sites edited in the same change

- `scripts/issue-audit-state.py` — round resolution, the `next_call=` emitter and its two routing
  tables, `query-boundary`, and the `_MULTILINE_READBACKS` / `_NEXT_CALL_EXCLUDED` /
  `_ROUND_DEFAULTED` / reason-token constants.
- `scripts/render-audit-prompt.py` — the stderr fold, and `_abs_path`'s single-line check made
  total over `str.splitlines()` (it tested only `\n`/`\r` while every downstream consumer splits
  with `splitlines()`).
- `scripts/resolve-main-root.sh` — the builtin parse loop.
- `skills/create-issue/references/step-3-6-audit.md`,
  `references/fallback-state-owner-unavailable.md` — the superseded prose above, the ordered call
  sequence, and the boundary-read procedure.
- `lib/test/check-audit-lifecycle-contracts.py`, `lib/test/run.sh`,
  `lib/test/modules/create-issue-contract.sh`, `lib/test/test_python_scripts.py`,
  `lib/test/test_render_audit_prompt.py` — the guards, the pin deletions and the behavioral rows.
  Issue #1466 added `lib/test/extract-command-heads.py` to that set as a *read* dependency: the
  reverse arm imports its fence enumeration rather than carrying a second Markdown scanner, so a
  change to what counts as a scanned block reaches this gate too.
- `docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md` §11 — the two-class-contract paraphrase, which carried the
  same short read-back enumeration as a third uncovered carrier and is why that clause drifted
  unseen.
