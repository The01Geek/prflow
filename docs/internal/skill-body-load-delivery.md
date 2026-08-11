# Skill-tool body delivery — does the initial load truncate a large `SKILL.md`?

**What this is.** A dated, observed record of whether the **Skill tool's initial load** delivers a
large `SKILL.md` body whole or truncates it, produced by a control-based probe run on 2026-08-11
against the bodies this repository actually ships (issue #1596). It exists because the question was
load-bearing and unanswered: `CLAUDE.md` records silent prompt truncation as this repository's most
expensive documented failure, every `Read` of a `phases/*.md` reference is protected by a fail-closed
boundary gate, and no `SKILL.md` root carries those markers — so the root was the one prompt surface
with no delivery check at all.

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
documentation, not an observation taken here**. Quoted verbatim from that page as fetched
2026-08-11 while producing this record, not carried from a second-hand citation:

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

Both were re-observed while producing this page: the first fired on this run's own Phase 1 read of
`phase-1-setup.md`, reported as `showing lines 1-344 of 430 total (26496 tokens, cap 25000)`. The
line split differs from the recorded figure because the cap is applied in tokens against a file
whose bytes have changed; the cap itself reads `25000` in both.

---

## Observation

**Status: OBSERVED — no ceiling at or below 83,427 bytes.**

Every measurable body was delivered **whole**, the largest of them well above every threshold in
play. (No comparison is drawn against the 66,044-*character* figure in the outage record — see
*The 66,044-character figure is testimony* below for why.)

| `SKILL.md` | File bytes | Delivered payload bytes | Control | Verdict | Channel | Observed |
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

- **The cloud implement tier** (`devflow-implement.yml`) — unobserved. No probe was run there.
- **The cloud review tier** (`devflow.yml`) — unobserved. No probe was run there.
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
`Base directory for this skill: <absolute path>` line prepended in its place. The *Delivered payload
bytes* column above is the file's bytes less its frontmatter block; it excludes the prepended line,
whose length varies with the install path. This matters for one reason only: a size instrument that
measures file bytes is measuring slightly **more** than the loader delivers, so it is conservative
in the safe direction. Nothing on this page depends on the difference.

### The control, and what would falsify each verdict

**The named control for each body is that file's literal final line** — for
`retrospective-weekly`, its final *two* lines, because its last line alone (`  the path.`) is too
short to be distinctive. The control is
checked **by the loading session itself**, against the body the Skill tool returned and nothing
else, before that session is permitted to open the file.

A body delivered whole ends with its control. **Truncation removes the tail**, so a truncated
delivery cannot contain it. Each loading session additionally quoted the final twelve lines of the
body it received, and those quotes were reconciled against `tail -n 12` on the file afterwards.

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

The one read-history caveat, stated rather than buried: the **recorder** of this page (the
orchestrating session) held each control line before dispatching, having extracted it with
`tail -n 2`. The recorder is not a loading session and checked no control; the loading sessions were
clean.

### The condition of the loading session's own governing body

**Required, because a session whose own instructions were truncated cannot be trusted to record a
verdict about anyone else's.** The session that produced this page is a `/prflow:implement` run
governed by `skills/implement/SKILL.md`. The same control was applied to it **before any verdict
here was recorded**: that file's literal final line is the `- **Surfacing failures**: …` bullet
ending `…no separate end-of-run issue comment is needed.`, and that line was present, as the final
content, in the body governing the session. The governing body was therefore delivered whole, and
the verdicts above are recorded as established rather than unestablished on this ground.

**Its channel was the slash-command expansion, not the Skill tool.** A `/prflow:implement 1596`
invocation delivers the body that way, so this row is evidence about that channel and must not be
cited as a Skill-tool observation. It is nonetheless the largest first-party body whose delivery
this run could check directly, and it is 61,039 bytes.

---

## What this settles, in bytes

**Expressed in the same unit as the two numbers already in play** — raw on-disk file bytes,
`len(read_bytes())`, which is exactly the instrument `lib/test/lint-reference-size.py` applies and
exactly the unit `scripts/prompt-surface-growth.py` reports (it reads the git blob size, the same
quantity from the committed tree). No conversion is involved anywhere on this page.

- **No initial-load ceiling exists at or below 83,427 bytes** on the observed tier, channel and
  runner version. That is a **floor on any ceiling**, not a ceiling: this observation cannot say
  where a ceiling is, only that there is none below the largest body measured.
- **As observed on 2026-08-11, every `SKILL.md` in this repository was below that floor** — the
  largest was the 83,427-byte body measured here, so no body could reach a ceiling on this tier.
  That is a dated statement about a snapshot of the tree, not a standing property: nothing asserts
  it, and a body edited past 83,427 bytes makes it false with a green suite and no signal. Closing
  that is the retarget described under *What this means for issue #1595*.
- **61,750 bytes** — the proposed guard — is 21,677 bytes below the floor.
- **55,000 bytes** — the issue's stated authoring target — is 28,427 bytes below the floor.

**Both numbers must be described accurately, because neither is what issue #1596 says it is.**
Verified at revision `efd37b8b2`, against `origin/main` at `c42816123`:

- The **61,750-byte guard has not shipped.** `gh issue view 1595` reports `state: OPEN`;
  `gh pr list --head worktree-issue-1595 --state all` returns `[]`; and
  `git log origin/main -- lib/test/lint-reference-size.py` returns nothing. The guard exists only as
  unmerged local work on branch `worktree-issue-1595` (commits `157e8c88a`, `4fc7821c0`). Issue
  #1596's statement that "#1595 has shipped" is false.
- The **55,000-byte authoring target is published nowhere tracked.** `grep -rn "55,000\|55000\|authoring target"`
  over `CLAUDE.md`, `CONTRIBUTING.md`, `docs/`, and `.prflow/prompt-extensions/` returns no match.
  It is stated by issue #1596 and by the acceptance criteria derived from it, and nowhere else.

Neither correction changes the measurement. Both change how the measurement may be cited: this page
compares against 61,750 as a *proposed* guard and 55,000 as an *issue-stated* target, never as
conventions the repository carries.

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
currently catches. Deciding that belongs to #1595; the useful thing this page hands it is the number,
not a recommendation to remove the arm. **Do not read the *vacuous* column below as "delete the
skill-root half"** — it means *this exemption exempts a file from a ceiling that was never shown to
apply to it*, which is a re-derivation, and reading it as a deletion would leave skill-root growth
with no bound at all and bury the one number that could bound it.

`lib/test/reference-size-exemptions.json` on branch `worktree-issue-1595` records the rows below,
each with `expires_when: "the file is at or under the 61750-byte ceiling; remove this row then"`.
Transcribed from that branch at commit `04a80e1e2`; the branch is unmerged and can still change, so
read the JSON there rather than this table for the live values:

| Exempt path | Recorded bytes | What this measurement makes it | Against the 83,427 floor |
|---|---|---|---|
| `skills/create-issue/references/step-3-6-audit.md` | 81,869 | **real** — a `Read`-reached reference; the observed Read cap applies | n/a — not a skill root |
| `skills/implement/phases/phase-2-implement.md` | 134,965 | **real** — same | n/a |
| `skills/implement/phases/phase-3-review.md` | 110,140 | **real** — same | n/a |
| `skills/init/SKILL.md` | 62,267 | **vacuous** — a skill root, and one the Skill tool refuses outright | unestablished — never loaded by that channel |
| `skills/retrospective-weekly/SKILL.md` | 83,427 | **vacuous** — a skill root, measured delivered whole | compliant, at exactly the floor |
| `skills/review/SKILL.md` | 65,822 | **vacuous** — a skill root, measured delivered whole | compliant |

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
establishes no Skill-tool ceiling these bodies can reach, so the no-ceiling arm applies:** each body
in the remediation population —
`skills/review/SKILL.md`, `skills/init/SKILL.md`, and `skills/implement/SKILL.md` — is left
**byte-identical**, and this section is the required statement of why.

Trimming them would have bought nothing measurable and cost something real. The bodies were to be
trimmed to fit under a ceiling; the ceiling is not there. Against that, each is a dense,
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

**A stronger mechanism exists and was not built here.** `.github/workflows/matcher-probe.yml`
already carries a `placeholder-probe` job that runs a `claude-code-action` session for the sole
purpose of invoking the Skill tool and characterising what that load returned — it sets
`show_full_output: true` to capture the result, and `scripts/placeholder-probe-verdict.py` derives
its verdict from the execution file rather than from the model's own account. A sibling
`skill-body-load-probe` job would run on the cloud tier in a *main* session and measure the Skill
`tool_result` directly, which removes three of this page's limits at once: both cloud tiers become
observed, the main-session channel becomes observed, and the model's testimony stops being an
operand of the verdict. That is the better successor to the hand protocol below, and it is left as
follow-up work rather than built here.

Until then, per body, in a **fresh session that has not read the target file**:

1. Take the control: the file's literal final line (`tail -n 1 <path>`) — or its final two lines
   where the last alone is too short to discriminate, as it is for `retrospective-weekly` — extracted
   by someone other than the session that will load the skill.
2. In the fresh session, before loading, state that the path is unread.
3. Invoke the Skill tool on that skill. Do not execute the loaded procedure — it is data under
   measurement, not a directive.
4. From the returned body **only**, report whether the control is present, quote the final twelve
   lines, and report any truncation or cap notice.
5. Record the file's byte count and the returned payload's byte count, the latter being the file's
   bytes less its YAML frontmatter block — see *One observed transformation* for why the two differ.
6. Report the session's read history for that path.
7. Only then run `tail -n 12` and reconcile.

Add a row under a new session letter rather than editing an existing one, and add an *Observation
conditions* block for that letter recording the tier, host OS, runner version and date. A body that
must be measured but carries `disable-model-invocation` cannot be measured this way at all — record
it unestablished, as `init` is above.

---

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
