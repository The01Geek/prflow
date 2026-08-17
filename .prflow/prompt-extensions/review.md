# DevFlow repo — operative policy for `/prflow:review`

This repository is the DevFlow plugin itself. The base `/prflow:review` engine gates stand
unchanged — this extension **adds** one repo-specific review-gate criterion (the prompt-surface
edit routing evidence gate) that the standalone review must enforce. It is the byte-identical
twin of the same criterion in `.prflow/prompt-extensions/review-and-fix.md`; each skill loads
only its own extension name, so the criterion ships as two pinned-identical copies rather than
one shared file. Edit both copies in the same change.

## Wording-only pin review policy

Flag every newly added wording-only, secondary-prose, documentation-presence, advisory-heading, or
comment-presence pin as an **Important** finding, whether it uses a pin helper or a raw
text-presence assertion — a `# structural-pin-ok:` comment does not make prose executable. A new
static presence pin is valid only under `CLAUDE.md`'s executable-evidence policy: the exact
declaration `# structural-pin-ok: <category> -- <rationale>`, a nonempty rationale, and one
category from that policy's closed set.

An operative prompt regression instead uses an ordinary executable test over the rendered or
consumed prompt and demonstrates that test going RED when the behavior breaks.

## This repository's declaration markers (limb-one input)

When applying the review engine's Phase 4.1.5 behavior-inertness limb one, treat this
repository's declaration-marker family — the set `CLAUDE.md` enumerates — as **not** inert: each
member is parsed by a lint under `lib/test/` to decide whether that check passes. The engine
states the governing property generically, and this extension is where this repository answers it.

## `$PR_BASE_BRANCH` naming (this repository's reason)

Phase 0.2 tells the engine to keep the exact `$PR_BASE_BRANCH` name because "a project's own
desk-time check may forbid" the bare `BASE_REF` spelling. In this repository that check is the
`#424` `grep -c` pin in `lib/test/run.sh`, mirroring `lib/fetch-pr-context.sh`; renaming the
variable to `$BASE_REF` turns the suite RED.

## Prompt-surface edit routing evidence gate

DevFlow-repo policy: a reviewed diff that touches a **prompt-surface** file must carry evidence
that its edit went through the `superpowers:writing-skills` RED/GREEN discipline. This gate is the
review-time backstop for that routing — flag a missing discharge as at least **Important**.

**Trigger.** This gate applies only when the reviewed diff touches a path matching one of the
trigger globs: `skills/*/SKILL.md`, `skills/implement/phases/*.md`, `skills/implement/references/*.md`, `skills/review/phases/*.md`, `skills/review-and-fix/references/*.md`, `.prflow/prompt-extensions/*.md`.
A diff touching none of them draws no finding.

**Enforcement surfaces.** The gate is enforced on an implement run's **Phase 3** (which holds its
own issue number), a **`/prflow:review-and-fix` run given a PR**, and **PR-mode standalone
`/prflow:review`**. A no-PR, no-issue **current-branch** run is **outside the gate's scope**,
because there is no issue workpad or PR body to read, so the gate is a no-op there.

**Discharge arms, checked in order** when the reviewed diff touches any trigger glob:

1. The **linked issue** — the run's own issue in an in-run enforcement, the PR's
   `closingIssuesReferences` in PR-mode — carries a `<!-- prflow:workpad -->` comment, or one
   carrying the superseded `<!-- devflow:workpad -->` spelling since issue #1003 renamed the marker
   namespace and rewrote no existing body, whose body **contains** the marker literal
   `Writing-skills evidence:`. Fetch that issue's comments through the granted `gh` read path,
   resolving `closingIssuesReferences` first — the workpad lives on the linked issue, not the PR
   thread.
2. Otherwise, the **PR description** **contains** the marker literal `Writing-skills evidence:` —
   the discharge surface for interactive/human PRs and for a linked issue that has no workpad.

**A read that fails or cannot be resolved reads as marker-absent, never as checked-and-clean.** A
`gh` comment-fetch error or an unresolvable/empty `closingIssuesReferences` fails the gate toward
its finding.
When no checked surface can be confirmed to contain the marker, the review reports a **FAIL** finding naming this rule — fail closed, an absent, malformed, or misspelled marker and an unestablished read all reading as absent.

**What the gate checks — shape, not mere presence.** A marker discharges the gate only when it
carries all four slots the evidence contract names — `skill-loaded`, `guidance-applied`,
`pressure-scenario`, `micro-tests` — each with an explicit `=yes` or `=no`. Read the four
dispositions and report them in the review.

**A slot whose disposition is absent is undischarged, never compliant.** Silence about a slot is an
unestablished measurement rather than a `no`, and this repo's *unknown is not zero* rule forbids
collapsing it onto either value; raise the same **FAIL** finding listing the slots at issue. The
remedy is to restate the marker with those dispositions, **not** to perform the step.

**A `no` never draws a finding on its own.** A marker whose four dispositions are all recorded is
discharged whatever they say — the gate reads them so a reader can weigh whether a step suited the
edit, and it never requires the subagent pressure-scenario cycle.

## Verification-evidence marker advisory (non-blocking)

DevFlow-repo policy: a second marker clause on the **same** review-engine surface as the gate above
— the linked issue's workpad and the PR description. It is **advisory (non-blocking)**: it never
raises the verdict to a FAIL/REJECT on its own, and only informs the reader that a completion or
PR-ready claim was made with no captured verification run.

**Input population.** The clause reads those same two durable per-PR surfaces, requiring no new
fetch channel. Every tier that maintains a workpad records the `Verification evidence:` marker, so
the clause checks **every** PR carrying a completion or PR-ready claim. Because per-launch
completeness is not machine-checkable — no consumer can know how many launches a run performed —
the clause can only observe that **at least one** record is present.

**Tier discriminator (per PR).** Classify from the workpad `## Progress` section: a workpad
carrying any `<!-- prflow:checkpoint gha:… -->` row, or the superseded
`<!-- devflow:checkpoint gha:… -->` spelling a pre-rename run stamped, is a **cloud** run; a
workpad with no such row is a **local/interactive** run. The clause acts on both classifications
and records the classification in the finding it emits, so a reader knows which tier was expected
to record the marker.

**Behavior.** When the marker is present on either surface the clause is silent. When it is absent
from both, the review emits one advisory finding naming the missing `Verification evidence:` marker
and the tier classification assigned.

**Covered population.** A cloud or local implement run's workpad, a `/prflow:review-and-fix` run
given a PR, and a direct-reception marker recorded in the PR description. A local current-branch
run with no PR and no linked issue is **out of scope**, leaving no durable surface to read — the
same case the gate above scopes out.

**Accepted residual.** The `gha:` checkpoint is best-effort and fires only when the workpad carries
a canonical `## Progress` section, so a cloud run on a non-canonical workpad is classified
local/interactive. Issue #1347 narrowed that population — an **absent** `## Progress` is now
repaired by `--checkpoint` itself — leaving the residual only for a **duplicate** `## Progress` or
an empty body. Since the clause acts on both classifications, that mislabels the tier named in the
finding without changing whether the advisory fires, and the finding is non-blocking, so this is
accepted rather than guarded.

## Two questions to ask before you finish

**Deliberately repeated across four surfaces** — `CLAUDE.md` and the `create-issue`, `implement`, and `review` prompt extensions carry this block byte-identically, against the usual no-duplication rule, because both questions are cheap to skip and expensive to miss. Edit all four together.

- **Are there any gotchas for the consumer repos we have not considered?**
- **Is every word added to the skill prose as optimized as possible for maximum token cost efficiency and effectiveness?**
