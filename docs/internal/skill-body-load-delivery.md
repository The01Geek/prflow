# Skill-tool body delivery — does the initial load truncate a large `SKILL.md`?

**What this is.** A dated, observed record of whether the **Skill tool's initial load** delivers a
large `SKILL.md` body whole or truncates it, produced by a control-based probe run on 2026-08-11
against the bodies this repository actually ships (issue #1596). It exists because the question was
load-bearing and unanswered: `CLAUDE.md` records a silent prompt truncation that cost a whole run
(the `| head -60` case, which truncated away a Phase 3 gate while the run still reported
`Complete`), and issue #1596 characterises that class as this repository's most expensive documented
failure. Every `Read` of a `phases/*.md` reference is protected by a fail-closed boundary gate, and
no `SKILL.md` root carries those markers — so the root was the one prompt surface with no delivery
check at all.

**Status: past-time snapshot.** This is a *dated observation of one runner version*, not a
specification and not a platform contract. Under `CLAUDE.md`'s *prefer-generated-evidence*
convention such a snapshot is the named exemption from live rendering: **nothing on this page is
machine-refreshed, and nothing here should be** — re-rendering it would overwrite the record rather
than update it. The one-line rationale registering every figure below as an exempt literal is this
paragraph. Re-run the procedure in *How to re-run this* after any Claude Code upgrade and add a row;
do not edit an existing row's figures.

Related: **#1595** (the proposed size guard whose skill-root half rests on the premise this page
settles), **#1446** (a run whose skill-body load *failure* goes unchecked and uncounted — the abort
mode, where this is the truncation mode),
[`docs/internal/review-skill-load-outage-2026-08.md`](review-skill-load-outage-2026-08.md) (the
abort mode, measured), [`docs/internal/execution-file-shape.md`](execution-file-shape.md) (the
dated-harness-observation this page is modelled on).

---

## The two loader mechanisms, and why they are exhaustive here

A `SKILL.md` body can reach a session's context by exactly two mechanisms in scope for this
question, and they are **not** the same mechanism:

1. **The initial Skill-tool load** — the tool call that puts the rendered body into the conversation.
   This is what this page measures.
2. **Post-compaction re-attachment** — the reduced re-injection of an already-loaded skill after the
   session compacts. This page records what vendor documentation says about it and measures nothing.

Those two are exhaustive **for this issue**, which asks about a body that a session obtains by
invoking a skill. Two adjacent paths are deliberately outside that pair and are named so no reader
infers they were folded in: **subagent preloading**, excluded by name in issue #1596 on the strength
of the vendor sentence quoted below; and the **slash-command expansion** channel, which is how a
`/prflow:<command>` invocation delivers a body and which is measured separately in the *Own
governing body* section below.

**The Read tool's cap and the Skill tool's budget are different numbers about different things —
neither is evidence about the other.** Keep them apart:

| | Read tool | Skill tool |
|---|---|---|
| Figure | **25,000 tokens**, a **per-read** cap | **25,000 tokens**, a **combined** budget across re-attached skills |
| When it applies | every `Read` of a file | **only** post-compaction re-attachment |
| Status here | observed, twice (below) | vendor-documented, not observed here |

They coincide numerically and govern nothing in common.

### What vendor documentation says about post-compaction re-attachment

Attributed to Anthropic's `code.claude.com/docs/en/skills`, "Skill content lifecycle" — **vendor
documentation, not an observation taken here**. Quoted from that page as fetched 2026-08-11 while
producing this record. That the fetch happened, rather than the text being carried from issue
#1596's own citation of it, is a transcript fact of the producing session and is testimony in the
same sense as the Verdict column below; what a later reader can re-derive is the quote's accuracy
against the live page, not its provenance here:

> When the conversation is summarized to free context, Claude Code re-attaches the most recent
> invocation of each skill after the summary, keeping the first 5,000 tokens of each. Re-attached
> skills share a combined budget of 25,000 tokens. Claude Code fills this budget starting from the
> most recently invoked skill, so older skills can be dropped entirely after compaction if you have
> invoked many in one session.

And of the initial load, the same page states:

> When you or Claude invoke a skill, the rendered `SKILL.md` content enters the conversation as a
> single message and stays there for the rest of the session

— and states **no cap** there. Silence about the initial load is not a measurement of it, which is
why the observation below exists. Post-compaction re-attachment is out of remediation scope: runs
here do not reach the context window that triggers compaction, so that budget does not engage in
practice.

The same page states the subagent-preloading exclusion this record relies on:

> [Subagents with preloaded skills] work differently: the full skill content is injected at startup.

### The Read cap, for comparison only

Observed twice, in this repository, by the truncation notice `Read` itself emits:

- `skills/implement/phases/phase-1-setup.md` → `showing lines 1-355 of 430 total (25678 tokens, cap 25000)`
- `skills/create-issue/references/step-3-6-audit.md` → `showing lines 1-299 of 399 total (28356 tokens, cap 25000)`

The first of the two was re-observed while producing this page — it fired on this run's own Phase 1
read of `phase-1-setup.md`, reported as `showing lines 1-344 of 430 total (26496 tokens, cap 25000)`.
Its line split differs from the recorded figure because the cap is applied in tokens against a file
whose bytes have changed; the cap reads `25000` in the earlier reading of that file and in this
run's. The `step-3-6-audit.md` figure was **not** re-observed here and is carried from the record
above.

---

## Observation

**Status: TESTIMONY, STRUCTURALLY CORROBORATED — no ceiling found at or below the sizes measured.**

Not `OBSERVED`, and the distinction is this page's own to keep. Three of the four delivered-whole
verdicts rest on a dispatched session's **self-report** that a control was present and that no
truncation notice appeared — and a claim of *absence* is unestablished unless the output is shown,
which none of the three sessions' returned text is here. What corroborates them is structural, not
evidentiary: three independent sessions, three different bodies, each reconciling its quoted tail
against the file afterwards, all agreeing. That is strong enough to act on and not strong enough to
call a measurement. The mechanism that *would* make it one is named under *How to re-run this* and
was not built.

Every measurable body was delivered **whole**, the largest of them well above every threshold in
play. (No comparison is drawn against the 66,044-*character* figure in the outage record — see
*The 66,044-character figure is testimony* below for why.)

| `SKILL.md` | File bytes | File bytes less frontmatter (derived) | Control | Verdict | Channel | Observed |
|---|---|---|---|---|---|---|
| `skills/retrospective-weekly/SKILL.md` † | 83,427 | 83,030 | present | **delivered whole** | Skill tool, dispatched local subagent | 2026-08-11 / A |
| `skills/review/SKILL.md` | 65,822 | 65,214 | present | **delivered whole** | Skill tool, dispatched local subagent | 2026-08-11 / A |
| `skills/init/SKILL.md` | 62,267 | — | — | **unmeasurable by this channel** | Skill tool refused (see below) | 2026-08-11 / A |
| `skills/implement/SKILL.md` | 61,039 | 60,617 | present | **delivered whole** | slash-command expansion (not the Skill tool) | 2026-08-11 / A |
| `skills/receiving-code-review/SKILL.md` | 57,887 | 57,508 | present | **delivered whole** | Skill tool, dispatched local subagent | 2026-08-11 / A |

**† `skills/retrospective-weekly/SKILL.md` was delivered whole and is *not* compliant with either
byte number in play.** Delivery and compliance are different questions; see *Remediation* below, and
do not read this row's verdict as a compliance finding.

**Observation conditions — session A, 2026-08-11.** Local/interactive tier; macOS 26.5.2
(build 25F84); Claude Code 2.1.227; PRFlow plugin 2.32.33. The conditions are keyed to the session
letter in the `Observed` column rather than scoped to "the table", so a later re-run adds its own
rows under its own session letter and this block stays true.

**Tiers left unobserved, named rather than omitted:**

- **The cloud implement tier** (`devflow-implement.yml`) — unobserved as of session A. The probe
  mechanism now exists (session B below); its verdict is `unestablished` until a maintainer runs it.
- **The cloud review tier** (`devflow.yml`) — unobserved as of session A. Same as above: probe built
  in session B, verdict `unestablished` until dispatched.
- **The local main-session Skill-tool channel for a body in the census size range** — unobserved.
  The Skill-tool rows above were each observed from a *dispatched local subagent*, because the
  `/prflow:implement` orchestrator that produced this page is barred by its own exclusionary Skill
  rule from loading those skills itself. Whether the main session's loader is byte-identical to a
  subagent's is **not established here**; the two are recorded as one channel only in the sense that
  both are the Skill tool, and a reader must not read a subagent row as a main-session observation.

**`skills/init/SKILL.md` is unmeasurable by this channel, not delivered-partial.** Its frontmatter
carries `disable-model-invocation: true`, so the Skill tool refuses before any body is loaded:

> Skill prflow:init cannot be used with Skill tool due to disable-model-invocation. Ask the user to
> run /prflow:init themselves — it cannot be invoked via the Skill tool.

Zero body bytes were returned, so the control is neither present nor absent. Per the repository's
*unknown-is-not-zero* rule this is recorded as **unestablished**, never as a pass and never as a
failure. Verified independently of the probe: `grep -l "disable-model-invocation" skills/*/SKILL.md`
returns `init`, `retrospective`, and `retrospective-audit` — and of the census population only
`init`. The consequence is a real one, not a probe artifact: `skills/init/SKILL.md` **only ever**
reaches a session by slash-command expansion, so the Skill-tool question does not arise for it. Its
slash-command delivery is unobserved.

### One observed transformation — the delivered payload is not the file

On every successful load the delivered body was the file **minus its YAML frontmatter**, with a
`Base directory for this skill: <absolute path>` line prepended in its place.

**That column is derived from the file, never counted from the returned body** — which is why it is
headed *derived* and why it is **not** evidence of whole delivery. It is the file's bytes less its
frontmatter block **and the blank line that follows the closing `---`** (`implement`, which has no
such blank line, is the one row where the simpler rule and the applied rule coincide); it excludes
the prepended base-directory line, whose length varies with the install path. Nothing about whole
delivery rests on it. Its one use is that a size instrument measuring file bytes measures slightly
**more** than the loader delivers, so such an instrument is conservative in the safe direction.

### The control, and what would falsify each verdict

**The named control for each body is that file's literal final line** — for
`retrospective-weekly`, its final *two* lines, because its last line alone (`  the path.`) is too
short to be distinctive. The control is
checked **by the loading session itself**, against the body the Skill tool returned and nothing
else, before that session is permitted to open the file.

A body delivered whole ends with its control, so a delivery truncated **at the tail** cannot contain
it. Each loading session additionally quoted the final twelve lines of the body it received, and
those quotes were reconciled against `tail -n 12` on the file afterwards.

**This detects tail truncation only, and that is a real limit rather than a formality.** That a
loader which drops content drops it from the end is an assumption about failure geometry, not
something observed here — so an elision from the *middle* of a body, with the tail intact, would
pass every check above. Nothing on this page rules that out.

**What would falsify a `delivered whole` verdict**, any one of:

- the control absent from the returned body;
- the returned body's final lines differing from the file's;
- a truncation notice, cap notice, ellipsis, or `showing lines X-Y of Z` marker in the tool result
  — the `review`, `retrospective-weekly` and `receiving-code-review` sessions were each asked for
  one specifically and each reported `no truncation notice`;
- the loading session having obtained that body's content by any channel before the control was
  checked (see *Read history* below).

### Read history per verdict

**A verdict is recorded as unestablished when its loading session obtained that body's content by
any channel other than the Skill-tool load before the control was checked.** Taking the three
delivered-whole Skill-tool verdicts one at a time — `review`, `retrospective-weekly`,
`receiving-code-review` — each was produced by a fresh, context-isolated subagent that was
instructed not to read the target path or any cached copy before checking the control, stated before
loading that it had not, and reported afterwards that the Skill-tool load was the first and only
channel by which the content reached it. Each then ran `tail -n 12` as post-hoc verification and
labelled it as such. So none of the three is unestablished on this ground.

**The `implement` row is the fourth delivered-whole verdict and does not meet that standard — its
read history is stated here rather than left implicit.** For that row the recorder *is* the loading
session, so the two roles are not separated as they are above. The ordering was: the body arrived at
session start via the slash-command expansion, ahead of the session's first file read; the recorder
then extracted the control from disk with `tail -n 1` and compared it against the body already in
context. Contamination of the *body* is therefore impossible — it was fixed before any disk read —
but the check was not blind, because the session that checked the control had by then seen that line
of the file. **Record it as a weaker verdict class than the `review`, `retrospective-weekly` and
`receiving-code-review` rows**: whole delivery is
established for it against a control the checking session had already seen, which is enough to rule
out truncation of that line and not enough to match the blind protocol above.

The recorder's role in the subagent-observed rows is the mirror image and carries no such caveat: it
held their control lines before dispatching, having extracted them with `tail -n 2`, but it is not
their loading session and checked none of their controls.

### The condition of the loading session's own governing body

**Required, because a session whose own instructions were truncated cannot be trusted to record a
verdict about anyone else's.** The session that produced this page is a `/prflow:implement` run
governed by `skills/implement/SKILL.md`. The same control was applied to it **before any verdict
here was recorded**: that file's literal final line is the `- **Surfacing failures**: …` bullet
ending `…no separate end-of-run issue comment is needed.`, and that line was present, as the final
content, in the body governing the session. The governing body was therefore delivered whole, and
the verdicts above are recorded as established rather than unestablished on this ground — **subject
to the same weaker-class caveat this check carries as a table row**, since it is the same session,
body and channel: see the `implement` row's read history above, which states why its control check
was not blind.

**Its channel was the slash-command expansion, not the Skill tool.** A `/prflow:implement 1596`
invocation delivers the body that way, so this row is evidence about that channel and must not be
cited as a Skill-tool observation. It is nonetheless the largest first-party body whose delivery
this run could check directly, and it is 61,039 bytes.

---

## What this settles, in bytes

**Expressed in the same unit as the two numbers already in play** — raw on-disk file bytes,
`len(read_bytes())`, which is exactly the instrument `lib/test/lint-reference-size.py` applies —
now shipped and driven by the suite; see the guard's status below — and exactly the unit
`scripts/prompt-surface-growth.py` reports here (it reads the git blob size,
the same quantity from the committed tree). No conversion is involved anywhere on this page.

- **No initial-load ceiling was found at or below the largest body carried whole** — 83,427 file
  bytes, of which **83,030 bytes were the delivered payload** — on the observed tier, channel and
  runner version. That is a **floor on any ceiling**, not a ceiling: it cannot say where a ceiling
  is, only that there is none below what was carried.
- **Which of those two numbers to generalize with depends on the direction, and they do not
  substitute for each other.** For a *guard* on file bytes, the file figure is conservative: the
  loader delivers less than the file holds. For this *floor*, the direction reverses — a different
  file at 83,427 bytes with smaller frontmatter would deliver a payload larger than anything carried
  here, so the file figure over-claims by the frontmatter difference (about 400 bytes at the sizes
  in play). **The payload figure, 83,030 bytes, is the conservative one**, and it is the one to use
  where the margin matters — which for a zero-headroom guard set at the floor, it does.
- **As observed on 2026-08-11, every `SKILL.md` in this repository was at or below that floor** —
  the largest was the 83,427-byte body measured here, which sits *at* it, so no body could reach a
  ceiling on this tier.
  That is a dated statement about a snapshot of the tree, not a standing property: nothing asserts
  it, and a body edited past 83,427 bytes makes it false with a green suite and no signal. Closing
  that is the retarget described under *What this means for issue #1595*.
- **61,750 bytes** — the proposed guard — is 21,677 bytes below the floor.
- **55,000 bytes** — the issue's stated authoring target — is 28,427 bytes below the floor.

**Both numbers must be described accurately, because neither is what issue #1596 says it is.**
Verified at revision `efd37b8b2`, against `origin/main` at `c42816123`:

- The **61,750-byte guard has shipped.** `git log origin/main -- lib/test/lint-reference-size.py`
  now returns commits — that check is the shipped/not-shipped discriminator, and it is the one to
  re-run — and `test -f lib/test/lint-reference-size.py` confirms the guard is present in this tree
  and driven by the test suite. #1595's work merged (via PR #1599, which was open while this record
  was first written), so issue #1596's statement that "#1595 has shipped" — false when this page was
  first authored, when the guard existed only as unmerged work on branch `worktree-issue-1595` — is
  now true. This bullet records the earlier not-shipped state as superseded, not as the current one.
- The **55,000-byte authoring target is published nowhere tracked.** `grep -rn "55,000\|55000\|authoring target"`
  over `CLAUDE.md`, `CONTRIBUTING.md`, `docs/`, and `.prflow/prompt-extensions/` returns no match.
  It is stated by issue #1596 and by the acceptance criteria derived from it, and nowhere else.

Neither correction changes the measurement. Both change how the measurement may be cited: this page
compares against 61,750 as the guard's ceiling (now shipped in `lib/test/lint-reference-size.py`) and
55,000 as an *issue-stated* target that is published nowhere tracked.

### The 66,044-character figure is testimony

[`docs/internal/review-skill-load-outage-2026-08.md`](review-skill-load-outage-2026-08.md) records
cloud run `31290098875` as "a **66,044-character** skill body injected". That page itself lists
"The 66,044-character restored body length." under the heading **"Carried from the session's audit,
not re-verified here"**. It is therefore **testimony**, and this page treats it as such: it is not
an established ceiling, it is not an established floor, and it is not evidence that 66,044 is a
boundary of any kind. It is one reported successful load on a cloud tier this page did not probe.

The same discipline applies reflexively. **Any figure on this page that cannot be re-derived by the
procedure below is testimony too.** Concretely, the *Verdict* and *Control* columns rest on what
each loading session reported about its own tool result — a transcript observation, not something a
later reader can recompute from repository bytes. Only the byte columns, the frontmatter split, the
`disable-model-invocation` fact, and the two `git`/`gh` status checks above are re-derivable from
this checkout.

---

## What this means for issue #1595

**The measurement does not confirm #1595's skill-root premise. That half of its population should be
rescoped.**

#1595 derives one ceiling — `25,000 tokens × 0.95 × 2.60 bytes-per-token = 61,750` — from the
**Read tool's** observed cap, and applies it to two populations: boundary-gated reference files,
which really are reached by `Read`, and **skill roots, which are not**. Its own text says the
skill-root half rests on the unmeasured premise that the Skill tool shares that cap. It does not:
83,427 bytes loaded whole, 35% above the derived ceiling, with no truncation notice.

So the guard's reference half is measured and correct, and its **skill-root half is derived from the
wrong instrument** — a Read cap that does not govern the loader those files actually arrive by.

**Rescoped means retargeted, not dropped.** This measurement did not show that skill roots need no
bound. It showed that 61,750 is the wrong number for them, and it produced a defensible replacement
in the same breath: **83,427 bytes**, the observed floor. A skill-root guard set there would hold
every body in the tree today while catching the growth past measured territory that nothing
currently catches — though #1595 should note it would hold with **zero headroom**: the floor is
derived from the largest body, which then sits exactly at it, so one added byte to
`retrospective-weekly` trips the guard. Deciding all of that belongs to #1595; the useful thing this
page hands it is the number, not a recommendation to remove the arm. **Do not read the *vacuous* column below as "delete the
skill-root half"** — it means *this exemption exempts a file from a ceiling that was never shown to
apply to it*, which is a re-derivation, and reading it as a deletion would leave skill-root growth
with no bound at all and bury the one number that could bound it.

`lib/test/reference-size-exemptions.json` on branch `worktree-issue-1595` records the rows below,
each with an `expires_when` string keyed to that ceiling. Transcribed from that branch at commit
`04a80e1e2`; the branch is unmerged and still moving — its `expires_when` wording had already been
rewritten by the branch tip while this page was being written — so read the JSON there rather than
this table for the live values, and treat the paths and the adjudication as this page's contribution
rather than the transcription:

| Exempt path | Recorded bytes | What this measurement makes it | Against the 83,427 floor |
|---|---|---|---|
| `skills/create-issue/references/step-3-6-audit.md` | 81,869 | **real** — a `Read`-reached reference; the observed Read cap applies | n/a — not a skill root |
| `skills/implement/phases/phase-2-implement.md` | 134,965 | **real** — same | n/a |
| `skills/implement/phases/phase-3-review.md` | 110,140 | **real** — same | n/a |
| `skills/init/SKILL.md` | 62,267 | **vacuous** — a skill root, and one the Skill tool refuses outright | unestablished — never loaded by that channel |
| `skills/retrospective-weekly/SKILL.md` | 83,427 | **vacuous** — a skill root, reported delivered whole | would sit *at* the floor, with zero headroom |
| `skills/review/SKILL.md` | 65,822 | **vacuous** — a skill root, reported delivered whole | would sit under it |

The rows marked **real** are obligations against a measured cap and stay as they are. The rows
marked **vacuous** are exemptions from a ceiling that was never shown to apply to them — and the
last column is what they become if #1595 retargets the skill-root arm at the measured floor instead
of removing it: two resolve as compliant with no exemption needed, and `init` stays unestablished
under this page's own unknown-is-not-zero handling.

**Boundary-gated references remain fully in scope.** Nothing here relaxes the Read cap, the
`phases/*.md` boundary contract, or the reference half of #1595. The reference exemptions above sit
against an oversize that is a genuine, measured hazard.

---

## Remediation: nothing was changed, and why

Issue #1596's remediation criterion is written as a ceiling arm and a no-ceiling arm. **The record
establishes no Skill-tool ceiling these bodies can reach, so the no-ceiling arm applies** — with one
caveat carried forward rather than glossed: for `skills/init/SKILL.md` the Skill tool refuses the
load outright, so its leave-it-alone rationale rests not on an observation but on the absence of one,
its real channel being the unobserved slash-command expansion. Each body in the remediation
population —
`skills/review/SKILL.md`, `skills/init/SKILL.md`, and `skills/implement/SKILL.md` — is left
**byte-identical**, and this section is the required statement of why.

Trimming them would have bought nothing **against the delivery question** — which is the only
question this page settles — and cost something real. The bodies were to be trimmed to fit under a
ceiling; no such ceiling was found. Limit 6 below is the honest remainder: cost, latency and
readability are separate reasons to bound a prompt surface, and this page weighs none of them. The
strongest form of the trim case, issue #1596's own — four trim pull requests each landing within 151
bytes of the guard, leaving bodies "unable to absorb one added sentence" — was an argument about
authoring room *under that guard*, and it largely dissolves now the guard is shown not to govern
skill roots. Against that, each is a dense,
heavily-pinned prompt surface: `.prflow/logs/pin-corpus-inventory.tsv` — itself a frozen census, at
its recorded revision `6a0d31a99` — carries 174 rows whose `homes` column names a census body, 195
body-mentions across them, re-derived here by an executed count over that file rather than quoted.
And `CLAUDE.md`'s recorded decision under *Guard executable behavior…* (issues #843 and #876) is that
agent-executed prompt prose carries no automated regression coverage by design, with the review pass
as its **sole** compensating control — so an editorial pass over these bodies risks losing an
instruction that nothing would catch. Editing was the more expensive option and the measurement
removed its justification.

Because no body changed, the per-changed-body instruction inventory that issue #1596 requires has an
**empty population**: with no pre-change body to inventory, the inventory is empty, so its count of
rows carrying a disposition other than kept, merged, or removed-under-the-prose-rule is zero.

**`skills/retrospective-weekly/SKILL.md` is measured, non-compliant, and excluded from remediation
as low-priority.** State it that way and not otherwise: at 83,427 bytes it is the largest body in
the repository and sits above both the 61,750-byte proposed guard and the 55,000-byte stated target.
It was **not** found compliant. It is excluded because the retrospective skills are the least used,
and it remains available for a follow-up if that priority changes. The vendored `superpowers` bodies
`skills/receiving-code-review/SKILL.md` (57,887 B) and `skills/requesting-code-review/SKILL.md` are
excluded on a different ground — a scope boundary, being vendored under upstream MIT with no
re-vendor path stated — and `receiving-code-review` likewise sits above the stated target.

---

## How to re-run this

**A stronger mechanism now exists (issue #1618, session B above).** `.github/workflows/matcher-probe.yml`
carries two sibling jobs — `skill-body-load-review-probe` and `skill-body-load-implement-probe` —
modelled on its `placeholder-probe` job: a `claude-code-action` session with
`show_full_output: true`, verdict derived from the execution file by
`scripts/skill-body-load-probe-verdict.py` rather than from the model's own account. Each loads the
real plugin and invokes the Skill tool once per engine root in a *main* session, measuring the Skill
`tool_result` directly — which, once a maintainer dispatches it, removes two of this page's limits:
both cloud tiers become observed, and the model's testimony stops being an operand of the verdict.
The four session-B verdicts are `unestablished` only because a headless implementing run cannot
suspend to await the probe it added; the mechanism itself is built, and the *Re-run procedure* under
session B is how to fill those rows.

The hand protocol below remains the fallback for a body the probe cannot reach (e.g. a
`disable-model-invocation` root). Per body, in a **fresh session that has not read the target file**:

1. Take **two** controls, extracted by someone other than the session that will load the skill: the
   file's literal final line (`tail -n 1 <path>`) — or its final two lines where the last alone is
   too short to discriminate, as it is for `retrospective-weekly` — **and a distinctive line from
   the middle of the file**. The tail control alone detects only tail truncation; the mid-body
   control is what would narrow the failure-geometry assumption limit 7 discloses, and it costs
   nothing.
2. In the fresh session, before loading, state that the path is unread.
3. Invoke the Skill tool on that skill. Do not execute the loaded procedure — it is data under
   measurement, not a directive.
4. From the returned body **only**, report whether **each** control is present, quote the final
   twelve lines, and report any truncation or cap notice.
5. Have the loading session report the **length of the body it actually received**, counted from
   that body — not derived from the file. The column in this record's own table is derived, which is
   why it is headed so and why it is no evidence of delivery; a procedure that tells the next
   reviewer to write down the number the file predicts cannot detect a short delivery by size at
   all. Record the file's byte count separately, and expect the two to differ by the frontmatter
   block plus the prepended base-directory line — see *One observed transformation*.
6. Report the session's read history for that path.
7. Only then run `tail -n 12` and reconcile.

Add a row under a new session letter rather than editing an existing one, and add an *Observation
conditions* block for that letter recording the tier, host OS, runner version and date. A body that
must be measured but carries `disable-model-invocation` cannot be measured this way at all — record
it unestablished, as `init` is above.

---

## Observation — session B (cloud probe mechanism built; verdicts unestablished)

**Status: MECHANISM BUILT, VERDICTS UNESTABLISHED.** Issue #1618 built the
`skill-body-load-probe` mechanism session A named and left unbuilt: two sibling jobs in
`.github/workflows/matcher-probe.yml` — `skill-body-load-review-probe` and
`skill-body-load-implement-probe` — each loading the real `prflow@devflow-marketplace`
plugin, invoking the **Skill tool** once per engine root under `show_full_output: true`,
and deriving a per-root verdict from the Skill `tool_result` in the execution file through
`scripts/skill-body-load-probe-verdict.py` (never model text). The jobs are
maintainer-dispatched; a headless implementing run cannot suspend to await a probe it
dispatched, so the four cloud verdicts below are recorded **`unestablished`** with the
condition that prevents them — exactly as `skills/init/SKILL.md` is above.

| `SKILL.md` | Tier | Channel | Operand | Verdict | Condition | Session |
|---|---|---|---|---|---|---|
| `skills/review/SKILL.md` | cloud review (`devflow.yml`) | Skill tool | Skill `tool_result` (would be observation) | **unestablished** | probe built, not yet dispatched | 2026-08-19 / B |
| `skills/implement/SKILL.md` | cloud review (`devflow.yml`) | Skill tool | Skill `tool_result` (would be observation) | **unestablished** | probe built, not yet dispatched | 2026-08-19 / B |
| `skills/review/SKILL.md` | cloud implement (`devflow-implement.yml`) | Skill tool | Skill `tool_result` (would be observation) | **unestablished** | probe built, not yet dispatched | 2026-08-19 / B |
| `skills/implement/SKILL.md` | cloud implement (`devflow-implement.yml`) | Skill tool | Skill `tool_result` (would be observation) | **unestablished** | probe built, not yet dispatched | 2026-08-19 / B |

**Channel (AC).** Every row above is the **Skill tool** channel — the tool call that renders
the body into context — *not* the slash-command expansion by which a real `/prflow:implement`
run delivers `skills/implement/SKILL.md` (session A's `implement` row). A cloud row must never
be compared with session A's slash-command `implement` row as if they measured the same channel.

**Operand, and why it will be observation not testimony (AC).** When a job runs, the verdict is
derived from the Skill `tool_result` recorded in the execution file — the rendered body itself —
checked against controls read **from disk** at verdict time. That is an observation a later reader
recomputes from repository bytes and the captured execution file, not the model's account of what
it received. Until a job runs, the operand does not exist and the row stays `unestablished`; a row
filled from a model's own report of what it saw would be **testimony**, and must be labelled so,
under the same standard session A applies to its Verdict column.

**Observation conditions — session B, 2026-08-19.** Tier: cloud review (`devflow.yml`) and cloud
implement (`devflow-implement.yml`), each approximated by a matcher-probe job (see the
approximation limit below). Host runner image: `ubuntu-latest` — the exact `ImageOS`/`ImageVersion`
is captured by the job when it runs and transcribed into the row then. Action version:
`anthropics/claude-code-action@v1`. Date: 2026-08-19 (record authored; the four verdicts are
unestablished, so no observation date exists yet).

**The approximation limit (why a cloud row can be `unestablished` and still honest).** A
matcher-probe job runs under `matcher-probe.yml`'s own harness, not under `devflow.yml` or
`devflow-implement.yml`, so it **approximates** each cloud tier's delivery conditions rather than
reproducing them byte-for-byte. The two jobs are separate sessions labelled by tier so a maintainer
dispatches and records each independently. Because delivery is allowlist-independent (the `Skill`
grant loads the body; the loaded engine's helper grants do not bear on whether it arrived whole),
this approximation is close, but it is not the tier's own workflow — a row must not be upgraded past
`unestablished` on the strength of the approximation alone.

### Re-run procedure and falsifier (AC)

1. On this branch, dispatch `matcher-probe.yml` via `workflow_dispatch` (available on the default
   branch after merge), or push an edit to `.github/workflows/matcher-probe.yml` to trigger its
   `pull_request` path from the branch. Either launches the two `skill-body-load-*-probe` jobs (one
   paid session each).
2. Read each job's `Compute skill-body-load verdict` step. The helper prints one `VERDICT:` line per
   root: `delivered-whole`, `short-delivery`, or `unestablished`.
3. Transcribe each root's verdict into the row above under a new observation date, and record the
   runner `ImageVersion` and the resolved `claude-code-action` version from the job log.

**What falsifies a `delivered-whole` verdict**, any one of: the Skill `tool_result` for that root
lacks the file's last non-empty line (tail lost); it lacks the distinctive interior control (an
interior loss); or it carries a truncation/cap notice (`showing lines X-Y of Z`, `cap 25000`). Any
of these makes the verdict `short-delivery`. A row stays `unestablished` when no Skill `tool_use`
for that root was recorded, its load returned an error, or the execution file was unreadable or of
the wrong shape.

### Delivery geometry this probe can and cannot distinguish (AC)

The verdict rests on **two** controls read from disk: the file's last non-empty line (tail) and one
distinctive interior line (mid). This detects a **lost tail** and **one interior point** — it does
**not** exclude an arbitrary middle elision that spares both controls. A `delivered-whole` verdict
here therefore means "the tail and one interior anchor arrived", never "every byte between them
arrived". This is the same failure-geometry limit session A discloses for its single tail control,
narrowed by one interior anchor and no further.

### What session B means for the skill-root half of the byte ceiling (AC)

Expressed in the ceiling's own unit — raw on-disk file bytes, `len(read_bytes())`, the instrument
`lib/test/lint-reference-size.py` applies:

- Measured 2026-08-19 at this branch's then-merge-base, `skills/review/SKILL.md` is **56,526 bytes**
  and `skills/implement/SKILL.md` is **57,124 bytes** — both **under** the 61,750-byte ceiling, and
  **neither carries an exemption row**. `lib/test/reference-size-exemptions.json` exempts exactly one
  skill root, `skills/retrospective-weekly/SKILL.md` (recorded at 83,427 bytes in that file's frozen
  snapshot; 71,331 bytes on disk at that snapshot, still above the 61,750-byte ceiling — the recorded
  and the on-disk figure are different numbers, and only the on-disk one is the deliverable size).
  (Session A's own figures — `review` at 65,822 bytes — predate the trims that brought both roots
  under the ceiling; issue #1618's premise cited the older 65,970-byte size, corrected on this run.)
- **Re-measured 2026-08-21 at merge base `1bcc25bca`,** when this branch was brought up to date:
  `skills/review/SKILL.md` **57,559 bytes**, `skills/implement/SKILL.md` **60,656 bytes**,
  `skills/retrospective-weekly/SKILL.md` **71,268 bytes**. The conclusions below are unchanged — both
  engine roots remain under the ceiling with no exemption row, and `retrospective-weekly` remains the
  sole skill-root exemption. What moved is *which* root sits closest to the line: `implement` now has
  1,094 bytes of headroom and is reported by the `#1614` near-full advisory, so the delivery question
  this probe answers has migrated from the review root to the implement root rather than lapsing.
- So the skill-root half of the ceiling currently carries **one** exemption, and it is **not** either
  root measured here. The two engine roots are compliant on file bytes with no exemption to classify.
- Because the four cloud verdicts are `unestablished`, session B **cannot yet** say whether the loader
  on either cloud tier shares the byte ceiling's premise. Session A settled that for the local tier
  (the Skill tool carried that body whole at its then-recorded 83,427 bytes, 35% above the ceiling),
  making the ceiling the wrong instrument for the *loader* there and the sole `retrospective-weekly`
  skill-root exemption **vacuous as a delivery obligation** on the local tier. Whether that exemption
  is a **real** delivery obligation or **vacuous** on the two cloud tiers waits on a cloud verdict: a
  cloud `short-delivery` below the file's on-disk size would make it real there; a cloud
  `delivered-whole` at or above its on-disk size would make it vacuous there too. Until then it is
  `unestablished` on both cloud tiers, and this record says so
  rather than importing session A's local adjudication onto tiers it did not observe.

## Observation — session C (extended probe verdict; verdicts unestablished)

**Status: PROBE EXTENDED, VERDICTS UNESTABLISHED.** Issue #1893 extended
`scripts/skill-body-load-probe-verdict.py` so each per-root report now names the *cause* of a short
delivery rather than only its fact. Extending the probe does **not** dispatch it: a headless
implementing run cannot suspend to await a probe it added, so every row below is recorded
**`unestablished`** with that condition — exactly as sessions A and B record theirs. The existing
session-A and session-B figures are untouched; this block adds a new record, it re-keys nothing.

What the extended probe now reports per root, beyond the bare verdict:

- the delivered body's character **LENGTH** (counted from the Skill `tool_result`, not derived from
  the file);
- the **FIRST-DIVERGENCE** character offset — the longest-common-prefix boundary between the
  delivered body and the on-disk `SKILL.md` with YAML frontmatter stripped and the prepended
  `Base directory for this skill:` line skipped;
- a **TAIL-CONTROL** present/absent result (the file's last non-empty line);
- an **INTERIOR-CONTROL** present/absent result (a distinctive interior line);
- a **COPY** comparison outcome — `identical` | `differing` | `unreadable` — of the `SKILL.md` at the
  delivered body's `Base directory for this skill:` line against the checkout file.

**The verdict vocabulary is now exactly four values: `delivered-whole`, `short-delivery`, `no-body`,
`unestablished`.** A new `no-body` arm sits ahead of the tail-loss arm, so a result carrying *neither*
control — including the documented already-loaded short note — returns `no-body` rather than
`short-delivery`; `short-delivery` is now reserved for a result that carried a body but lost part of
it, and its cause is read from the fields above.

| `SKILL.md` | Tier | Channel | Operand | Verdict | Condition | Session |
|---|---|---|---|---|---|---|
| `skills/review/SKILL.md` | cloud review (`devflow.yml`) | Skill tool | Skill `tool_result` (would be observation) | **unestablished** | extended probe not yet dispatched | 2026-08-24 / C |
| `skills/implement/SKILL.md` | cloud review (`devflow.yml`) | Skill tool | Skill `tool_result` (would be observation) | **unestablished** | extended probe not yet dispatched | 2026-08-24 / C |
| `skills/review/SKILL.md` | cloud implement (`devflow-implement.yml`) | Skill tool | Skill `tool_result` (would be observation) | **unestablished** | extended probe not yet dispatched | 2026-08-24 / C |
| `skills/implement/SKILL.md` | cloud implement (`devflow-implement.yml`) | Skill tool | Skill `tool_result` (would be observation) | **unestablished** | extended probe not yet dispatched | 2026-08-24 / C |

**Observation conditions — session C, 2026-08-24.** Tier: cloud review (`devflow.yml`) and cloud
implement (`devflow-implement.yml`), each approximated by a `matcher-probe.yml` job as in session B.
Action version: `anthropics/claude-code-action@v1`. Date: 2026-08-24 (record authored; the four
verdicts are unestablished, so no observation date exists yet). The approximation limit session B
states applies unchanged — a row must not be upgraded past `unestablished` on the strength of the
matcher-probe approximation alone.

### Re-run procedure (session C)

1. Dispatch `matcher-probe.yml` via `workflow_dispatch` (available on the default branch after
   merge), or push an edit to `.github/workflows/matcher-probe.yml` to trigger its `pull_request`
   path. Either launches the two `skill-body-load-*-probe` jobs (one paid session each).
2. Read each job's `Compute skill-body-load verdict` step. For each root the extended helper prints,
   alongside the `VERDICT:` line, the delivered-body character **LENGTH**, the **FIRST-DIVERGENCE**
   character offset, the **TAIL-CONTROL** present/absent result, the **INTERIOR-CONTROL**
   present/absent result, and the **COPY** comparison outcome (`identical` | `differing` |
   `unreadable`).
3. Transcribe each root's verdict — one of `delivered-whole`, `short-delivery`, `no-body`,
   `unestablished` — into the row above under a new observation date, recording the five reported
   fields so a `short-delivery` or `no-body` verdict carries its named cause rather than only its
   fact, and record the runner `ImageVersion` and resolved `claude-code-action` version from the job
   log.

**How the five fields name the cause.** A `short-delivery` with the TAIL-CONTROL absent and a
FIRST-DIVERGENCE offset short of the delivered LENGTH is a tail loss; one with the TAIL-CONTROL
present but the INTERIOR-CONTROL absent is an interior loss; a `no-body` verdict is a result that
carried neither control (a refused or already-loaded-short delivery); and a `differing` or
`unreadable` COPY outcome flags that the checkout file at the delivered base-directory line does not
match the body the probe measured against, so the divergence figures are read against a moved target.

## What this measurement does NOT establish

Hard limits on what may be cited from this page.

1. **It does not locate a ceiling.** It establishes that none exists at or below 83,427 bytes on one
   tier. A ceiling above that is neither found nor excluded.
2. **It is one tier, one host, one runner version, one day.** Both cloud tiers are unobserved. A
   Claude Code upgrade can change the answer, which is why *How to re-run this* exists.
3. **It observed the Skill tool from dispatched subagents.** The local main session's Skill-tool
   delivery of a body in this size range is unobserved.
4. **It says nothing about the abort mode.** A `SKILL.md` load can fail outright and return no body
   at all — measured, at scale, in
   [`review-skill-load-outage-2026-08.md`](review-skill-load-outage-2026-08.md), and unfixed as a
   detection gap in issue #1446. Truncation and abort are different failures; this page closes only
   the first.
5. **It does not measure post-compaction re-attachment.** That section quotes vendor documentation
   and observes nothing.
6. **It does not establish that no body here ever needs trimming.** Delivery is one reason to bound a
   prompt surface; cost, latency and readability are others this page does not weigh.
7. **It detects tail truncation only.** A control is a file's final line, so a mid-body elision
   leaving the tail intact would pass every check here. See *The control* above.
