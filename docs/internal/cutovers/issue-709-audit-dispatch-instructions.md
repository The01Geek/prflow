---
schema: 1
kind: cutover
---

## Files

- `skills/create-issue/references/step-3-6-audit.md` (mandatory, `create-issue-flow`) — the
  Consumption-categories **arm (i)** "compact-preamble transport" enumeration (the freehand list of
  what the orchestrator composes into every dispatch prompt) and the file-arm renderer-invocation
  fence left the skill. What replaced them is the **invocation contract** for the generator, the
  closed-input forwarding contract for `record-dispatch`, the return-line forwarding contract for
  `record-return`, the honest-limits statement, and the withhold-then-disclose contract — policy,
  invocation, and stop conditions, which the *Prose cutover* convention retains by name.
- `skills/create-issue/references/audit-prompt-template.md` (reference; outside both create-issue
  word-budget operands and outside the #614 routing-table reconciliation, by the same filename
  exemption `issue-template.md` carries) — gains the `di` render blocks, the sole in-repo owner of
  the canonical audit-dispatch instruction prose. Its stale "**The draft title never appears here**"
  claim is corrected: the title now appears in the `di` blocks, read from the draft file. The
  PR-#718 review round added the **generated dispatch pointer** here: four shipped surfaces
  asserted the Agent-tool prompt string was a *generated* pointer (issue AC4 requires a
  "canonically-generated" one) while nothing generated it — the orchestrator composed it freehand
  under a name-only-the-two-paths rule. The `di` render now emits the exact pointer line with both
  paths substituted, so the claim is true by construction and the auditor's `extra-dispatch-content`
  judgment has a reference form to compare its received message against. This lands in the template,
  which no word-budget operand contains.
- `scripts/render-audit-prompt.py` (not swept) — gains the `dispatch-instructions` mode, the sole
  tested owner of the dispatch-instruction text. Its docstring's falsified claim that the draft
  title "travels in the orchestrator's dispatch preamble prose" is corrected in the same change.
- `scripts/issue-audit-state.py` (not swept) — `SCHEMA_VERSION` 2 → 3; the sole tested owner of the
  establishment decision (`steering_state`, `regenerate_instructions_digest`), the gated clean
  ground, the new trigger arm, and the two summary tokens. The PR-#718 review round added a
  **dispatch-time canonicality observation**: `record-dispatch` regenerates from the inputs it is
  about to record and stores what it saw as `instructions.dispatch_regeneration`
  (`verified`/`diverged`/`unverified`, a closed vocabulary `_validate` enforces). Without it, any
  byte divergence surfaced only at `record-return` as `instructions-object-id-mismatch` and was
  reported to the user as *steering*, at the surface furthest from the site that could still fix it.
  The divergence has **three reachable causes the tool cannot distinguish** — bytes altered between
  the generator and the disk (a CRLF or trailing-newline translation), a recorded input whose path
  *spelling* differs from the one the generator was given (the rendered bytes embed those paths
  verbatim, and the draft-path cross-check compares RESOLVED paths, so an equivalent spelling passes
  it and still renders different bytes), or a file edited after generation — so the warning names all
  three and asserts none.

  It is an observation and **not a refusal**, and review round 2 is why. A refusal (a) could not tell
  a genuinely steered file from a mangled write, so its own remedy — "re-write it verbatim from the
  generator stdout" — would overwrite the only evidence of the edit and let the re-dispatch record a
  clean canonical round, laundering the exact attack the mechanism exists to catch, with nothing
  persisted about the attempt; and (b) exited before any state write, making it a new hard stop on a
  legitimate host, against this change's own contract that filing is never blocked on any arm.
  Recording keeps the durable trail and blocks nothing, and it cannot fail open: the return-time
  regeneration still owns the verdict and still refuses to establish steering on a mismatch — it now
  additionally attributes that mismatch to dispatch rather than to the auditor when the dispatch-time
  observation already disagreed.
- `skills/create-issue/references/step-4-present-create.md`,
  `references/fallback-read-only-sandbox.md`, `references/fallback-audit-dispatch-arms.md`,
  `references/fallback-state-owner-unavailable.md` (mandatory / conditional references) — the
  audit-summary marker, the offer routing, and the unestablished-by-construction arms.

Word accounting (python3 word-split, never `wc -w`): default path 29,973 → 31,073 against an
unmoved 31,262 ceiling; root unchanged at 2,732. The PR-#718 review round accounts for the last
125 of those words: two corrections in `step-3-6-audit.md` that a reviewer proved false against
HEAD (the generator-failure arm claimed the steering marker would name its cause — it renders
`inputs-unrecorded`; and the `record-return` output contract omitted the `unestablished`/`none`
pair a refused completion actually prints), plus the sentence directing the orchestrator to
dispatch the generated pointer line and stating that its prefix and indent are framing either
side may drop. Growing a mandatory surface is an audited decision
under the *Prose cutover* convention, and this is its record: both additions replace a false
sentence with a true one on the same execution path, neither adds a new rule, and the shipped
default-path headroom after them is ~0.6% (189 words). The bulk of the new prose lives in the
renderer-owned template, which no budget operand contains — so the ceiling is not renegotiated and
`CLAUDE.md` is untouched. The figures and decision record are historical; the retained context is
in `create-issue-budget.md`, and `CHANGELOG.md` records the subsystem's retirement.

## Consuming paths

The superseded prose had exactly one consuming path: **the file-arm state-owner-routed audit
dispatch** (Step 3.6's initial round, same-round retries, user-elected offer rounds, and Step 4
sub-step 4 re-audits all reach the same composition step). Every one of them now invokes
`render-audit-prompt.py dispatch-instructions` and dispatches a generated pointer. (Issue #1751
abolished the automatic re-audit that followed a `REVISE` verdict — `_MAX_AUTOMATIC_REAUDITS` is
now `0` and every round is user-elected before it opens — so the former "revise-and-reaudit rounds"
class named here no longer exists; the composition step it reached is now reached only by a
user-elected round.)

The other four consumption categories are **not** superseded and keep their prose verbatim: the
degraded inline arm (ii), the Step 3.5 self-check (iii), Step 2's `## Evidence axes` forwarding
(iv), and the `state-owner unavailable` fallback (v) — none of them composes a dispatch preamble.
The **embed** arm keeps its own transport for the same reason it exists at all: it is entered
*because* the canonical draft-file write already failed, so it has no writable instruction file and
records the property unestablished by construction rather than consuming the generator.

## Branch coverage

- Generator (`lib/test/test_render_audit_prompt.py`, class `DispatchInstructions`): positional
  markers (D1), title-read-from-the-file plus the absence of any `--title` argument (D2),
  determinism across runs (D3), title substituted last so a title carrying a literal slot token is
  never re-scanned (D4), no consumer-extension read even when pointed straight at one via
  `--extension-file` (D5), the authorized set present in the render (D6), every fail-closed arm —
  title-less draft, unreadable draft, and each missing required argument, all rc≠0 with empty
  stdout (D7), and the scope check that the audit-prompt arms did **not** gain the title (D8).
- State owner (`lib/test/test_python_scripts.py`, the `#709` rows): every Move-3 named assertion
  from the issue, driven end-to-end through the CLI over a really-generated instruction file —
  the positive control (5/10), the three divergence shapes (1/2/3), the extra-dispatch-content
  positive path (4), the four fail-closed absence rows (6a–6d), the Quiet-Killer offer arm (7), the
  regeneration-failure arm (9), the round-binding row, the embed/inline by-construction rows, and
  the closed-input half-pair refusal.
- Contract prose (`lib/test/modules/create-issue-contract.sh`, the `#709` block): the generated-
  pointer contract, the generator invocation, the closed-input forwarding, the never-invent-an-
  absent-value rule, both honest-limits sentences, the never-blocks-filing sentence, the Step 4
  marker, the offer routing — plus two **preservation** pins asserting the Information-diet
  omission rule and the out-of-bounds declaration survived the cutover.

## Grants and probes

None. `/prflow:create-issue` runs on the local/interactive tier only (no `GITHUB_ACTIONS`), so no
`.github/workflows/` `TOOLS=`/`--allowed-tools` grant is involved and `lib/capability-profiles.json`
is untouched. The mechanism introduces no new host binary: hashing reuses the state owner's existing
`git hash-object --stdin --no-filters` path, and the generator is reached by in-process import, not
by a subprocess or a `.sh` exec (the #275 constraint). It adds no `.prflow/config.json` key — the
enforcement is always-on and a consumer cannot disable it.

## Shipping coupling

None. Every changed artifact — the state owner, the renderer, the skill references, the template —
reaches a consumer repo through the **single `prflow_version` vendor fetch** (`scripts/` and
`skills/` vendor together under `.prflow/vendor/prflow/`). No `install.sh` workflow half is
involved, so there is no two-artifact install skew of the #502/#455 class.

## Mutation evidence

The guarantee is a fail-closed gate, so the evidence is the planted-defect direction, not the happy
path. Each divergence row *plants* the defect the gate exists to catch and asserts the gate fires:

- Instruction file steered after generation (three shapes: a focus clause, a reassurance clause, a
  prior-finding leak) → `steering_reason=instructions-object-id-mismatch`,
  `eligible=no reason=steering-unestablished`. Observed RED against the pre-#709 behavior by
  construction: before this change `evaluate_eligibility` read no steering operand at all, so every
  one of these rows answered `eligible=yes ground=file-identity`.
- Absent quoted object ID, wrong file hashed, unrecorded dispatch inputs, unreported affirmation →
  four **distinct** reasons, all withholding the clean ground. These are the fail-open rows: each
  one is an input on which a guard that merely *read* an operand would have passed vacuously.
- The positive control (`canonical-match` → `eligible=yes ground=file-identity`) is what proves the
  gate is not refusing everything — without it every negative row above would pass against a gate
  that simply never grounds.

## Pin disposition

- `#600: SKILL invokes render-audit-prompt.py on the file arm` (`render-audit-prompt.py file --slug`
  against `$CI_BUNDLE`) — **retained, repointed.** The invocation relocated out of the skill prose
  into the generated instructions, so the pin follows the content: it now targets the **rendered**
  dispatch-instruction output (rendered in-module from a fixture draft), per the #375
  pin-the-rendered-surface rule, since the template assembles the invocation from a
  `{RENDERER_PATH}` slot and it therefore lives on no single source line. The guarded regression is
  unchanged — dropping the instruction to run the renderer on the file arm still turns it RED — and
  the rendered-surface target additionally proves the mode is invocable at all, which the source
  grep never did.
- No other pin was retired. The arm-(i) enumeration carried no pin of its own; the
  Information-diet and out-of-bounds prose it sat beside is **preserved** and now carries two new
  preservation pins it did not have before.
- `CI614_TOTAL_RECORDED` re-anchored 25,814 → 27,146 (the live root+references total), so the ±2%
  conservation band keeps guarding against a silent prose drop from the new size rather than
  reporting this change's intended growth as drift. The #614 split's own conservation arithmetic in
  `create-issue-budget.md` is left frozen and is now labelled a past-time snapshot.
