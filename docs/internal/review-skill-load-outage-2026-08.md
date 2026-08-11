# The review-engine skill-load outage, 2026-08-06 → 2026-08-09

**Status: closed incident. This page is a past-time snapshot** — an unre-derivable measurement of a
window that has ended. Under CLAUDE.md's *prefer-generated-evidence* convention such a snapshot is
the named exemption from live rendering: nothing here is machine-refreshed, and nothing here should
be, because re-rendering it would overwrite the record rather than update it.

There is **no work item hiding in this page.** The one actionable residual — that a run which loses
a skill body is invisible to its own artifacts and denial telemetry, and still reports `Complete` —
already has a home in **issue #1446**. This page exists so the figures below are citable instead of
living only in a transcript. They previously did not: an agent reconciling issue #1299 was handed
the headline figure, searched the tree and every issue and pull-request body for it, could not
re-derive it, and correctly declined to cite it.

Related: **#1462 / PR #1463** (unconditional prompt-extension fetch and per-extension workpad
tracking), **PR #1471** (the experiment that removed the placeholder from the review root),
**#1473** (the retirement of the construct everywhere else), **#1470** (bounding the fix loop's
per-entry instruction cost), **#1299** (reconciled by this page),
[`docs/internal/skill-body-load-delivery.md`](skill-body-load-delivery.md) (the *truncation*
mode of the same load, probed 2026-08-11 and not found — where this page is the *abort* mode;
it also records why this page's 66,044-character figure is testimony rather than a bound).

---

## What broke

A render-time `` !`…render-prompt-extension.sh <name>` `` placeholder in a `SKILL.md` body makes a
`Skill`-tool load of that skill **fail outright**. The tool result comes back `is_error=true`
carrying only a permission-refusal string, and **no skill body at all** — not a truncated body, not
a body minus the extension. The load does not degrade; it aborts.

CLAUDE.md records the cause as a **phase mismatch**, and it is the reason no grant repairs this:
the `` !`cmd` `` injection runs as a *preprocessor during skill loading*, while `allowed-tools` /
`--allowed-tools` grants authorize the model's tool calls *after* the skill has loaded. The two
never meet. `lib/capability-profiles.json` already granted both `Bash(*/render-prompt-extension.sh:*)`
and the exact vendored literal, and the refusal still fired.

For the review engine the consequence is unusually severe, and it follows directly from the bundle
architecture described in §8 of the system overview. `skills/review/SKILL.md` is a **thin
orchestrator**: the actual procedures live in `skills/review/phases/*.md` behind a mandatory entry
gate. An aborted root load therefore leaves the agent with no root, no routing table, and no reason
to open a phase file — so it improvises from whatever the surrounding prompt gave it and posts a
**merge-gating verdict having executed none of the engine**. It does not error. It does not warn.
The run exits `success`.

## The window

| Boundary | Commit | Merge | Timestamp (UTC) |
| --- | --- | --- | --- |
| Placeholder added to `skills/review/SKILL.md` | `7b2943c94` | `adc88267f` (PR #1353) | 2026-08-06T06:52:30Z |
| Placeholder removed | `9a79f02e8` | `b7e3bc867` (PR #1471) | 2026-08-09T02:18:17Z |

**Duration: 2 days 19:25:47 — ≈67.4 hours.**

## Population and result

| Measure | Count |
| --- | --- |
| `devflow.yml` runs fired in the window | **170** |
| …of those, never reached the agent (`command` job skipped or cancelled) | **94** |
| …of those, executed the agent | **76** |
| Agent-executing runs whose transcript was retrieved and parsed | **76** (none expired) |
| Runs that invoked `Skill{prflow:review}` | **72** |
| …of those, returning `is_error=true` (no skill body) | **72 of 72** |
| In-window runs that made no `Skill` call at all | **4** |
| Post-removal runs sampled, returning `is_error=false` | **5 of 5** |

The 4 no-`Skill`-call runs are counted separately rather than folded into the degraded population:
each was 1 turn, $0.00, conclusion `failure` — they died before reaching the skill, so they are
neither evidence of the defect nor evidence against it.

## The discriminating field — read this before building a detector

**The signal is the `Skill` tool result's `is_error` flag. Nothing else separates a degraded run
from a healthy one.**

Agent-dispatch counts and phase-file-read counts look like they should work, and they do not. They
measure **severity**, not occurrence:

- Only **11 of 72** degraded runs had zero agents *and* zero phase reads.
- The median degraded run dispatched **1** agent and made **1** phase read.
- The worst-behaved degraded run dispatched **8** agents, read **6** phase files, and cost
  **$17.23** — by counts, indistinguishable from a healthy run.
- Conversely, a *healthy* post-removal run managed only 1 agent and 2 phase reads.

Any threshold over those counts therefore both misses most degraded runs and libels healthy ones.
A future detector must key on `is_error`.

## Two reference runs

Both are `devflow.yml` runs on `main`, ~57 minutes apart, straddling the removal merge.

**Degraded control — run `31288133212`** (PR #1468, started 2026-08-09T01:22:23Z, 56 minutes before
the removal landed): 17 turns, 227 s, **$2.36**, **0** agents dispatched, **0** phase files read.

**Restored — run `31290098875`** (PR #1469, started 2026-08-09T02:19:29Z, 72 seconds after the
removal landed): a **66,044-character** skill body injected, **6** phase reads each preceded by its
`git hash-object` re-identity check, **14** agent dispatches, 57 turns, 667 s, **$10.75**.

The cost ratio is the cheapest available smell test — but it is a smell test only, and it is not the
detector. See the previous section.

## Blast radius

**34 merged pull requests carry a governing bot approval issued from inside the window:**

#1358, #1360, #1361, #1363, #1376, #1378, #1381, #1384, #1386, #1387, #1403, #1407, #1408, #1409,
#1410, #1411, #1412, #1418, #1426, #1427, #1429, #1431, #1433, #1435, #1436, #1437, #1438, #1447,
#1448, #1459, #1460, #1461, #1463, #1468.

**Nine of those were approved by runs with zero engine activity** — no agent dispatched, no phase
file read: #1361, #1376, #1378, #1381, #1410, #1412, #1448, #1459, #1468.

**PR #1394 carries an in-window approval and is still open.** Its approval was submitted
2026-08-07T08:15:13Z, mid-window. It has had no governing approval since. Anyone preparing that pull
request for merge should treat the existing approval as not having been produced by the engine.

## Tier 1 audit — what was actually checked

Six of the 34 were audited for **defects surviving on `main` today**. Five came back clean; one did
not.

**Clean — #1435, #1436, #1460, #1410, #1459.** Nothing survives on any of them. Each was verified by
some combination of SHA recomputation over the asset manifest, live-text reads, and mirror sweeps of
deleted spans; #1459 additionally had its full population re-validated — 229/229 records and 21/21
override entries, re-run through the real `lib/cheap-gate.jq` and `clean-entry.jq`.

**#1438 — one Critical (since fixed) and one Low (live at audit time).**

The Critical is worth stating in full, because it is the same defect propagating:

> PR #1438 added a render-time `` !`…render-prompt-extension.sh` `` placeholder to
> `skills/pr-description/SKILL.md` — **the identical fatal construct** — while *the same branch*
> authored the CLAUDE.md bullet declaring that construct unfixably broken. (Re-derived: the bullet
> is commit `8836e08457`, an ancestor of the branch tip `a688e739f`, ~47 minutes before the branch
> merged as `76772a133` at 2026-08-08T05:35:51Z; the placeholder is commit `1248e5e624`.) This is a
> self-contradicting diff — precisely the shape the engine's Phase 4.2 carve-out would very likely
> have blocked, had the engine run.
>
> The consequence: `/prflow:implement` Phase 4.2 invokes `pr-description` on **every** run, so every
> implement run's `pr-description` load failed from that merge until commit `395e2c620` removed the
> placeholder — a second, narrower outage nested inside the first, on a different surface.

## What this measurement does **not** establish

Read these as hard limits on what may be cited from this page.

1. **No degraded run's verdict was assessed for correctness.** "The engine did not run" is
   established. "The verdict was wrong" is **not** — it was never tested, on any of the 72. A
   degraded approval may well have been the right call by luck or by the diff being trivial.
2. **Only 6 of the 34 approved pull requests were audited.** The other 28 are unexamined. Their
   absence from the Critical list means nothing was looked for, not that nothing was found.
3. **The audit asked "does a defect survive on `main` today", not "was the review adequate".** A
   defect introduced and later fixed by unrelated work reads clean here.
4. **Five of the six audited pull requests were prose-only — and that makes their exposure total,
   not their safety high.** This repository's recorded decision (issue #843, generalized by #876) is
   that agent-executed prompt prose carries **no automated regression coverage by design**, with the
   review pass as its *sole* compensating control. Remove the review pass and prose changes have
   nothing checking them at all. The honest finding is that those five diffs happened to be benign
   — not that the window was safe for prose.
5. **What did hold throughout are the mechanical gates**, which never depended on the engine: the
   SHA-256 asset manifests, the pin corpus, the shipped-path lints, and CI's required
   `lib + python tests` suite. Nothing in this incident bypassed those.

## One latent observation, recorded so it is not re-derived

From the #1459 audit: that pull request's 10 lifecycle filing keys are **47–74 characters** against
`lib/compose-filing-key.sh`'s contractual **≤40**, so the run bypassed the composer.

This was **refuted as actionable** on three independent legs, and the refutation is recorded here so
a future reader does not spend the same effort re-reaching it:

1. The alias lookup keys on the **subslug token set**, not on the whole key, and recovers correctly
   from the over-long forms.
2. There are **no truncation collisions** across all 21 keys.
3. The one real mismatch sits behind a `status` filter that **excludes those records**.

Latent only. Not a defect, not a work item.

---

## Provenance of the figures on this page

A reader must be able to tell measurement from testimony. This section is that line.

**Re-derived in this checkout, from `git` and the GitHub API:**

- Both placeholder commits and both merge commits, via `git log -S 'render-prompt-extension'` over
  `skills/review/SKILL.md` and `skills/pr-description/SKILL.md`.
- Both merge timestamps, and the ≈67.4-hour duration computed from them.
- The **170** in-window `devflow.yml` run count, filtered on the two merge timestamps.
- The **94 / 76** split, re-derived by fetching the `command` job conclusion for all 170 runs.
  *(One caveat, stated because it is a real discrepancy: the sub-split re-derives now as 92 skipped
  + 2 cancelled, where the session's own reading was 91 + 3. The 94 and 76 totals match exactly. The
  one-run difference in the sub-split is unexplained and immaterial to every claim above.)*
- The existence and timestamps of reference runs `31288133212` and `31290098875`, and that they
  straddle the removal merge.
- PR #1394's open state and its in-window approval timestamp.
- The #1438 self-contradiction: the CLAUDE.md bullet commit's ancestry on the #1438 branch, and the
  branch's merge time.
- The merge times of the window's boundary pull requests, #1358 and #1468, confirming both fall
  inside it.

**Carried from the session's audit, not re-verified here** — these come from transcript retrieval
and parsing, which is not reproducible from the repository:

- The **72 of 72** `is_error=true` result, and the 4 no-`Skill`-call runs.
- Every agent-dispatch count, phase-read count, turn count, duration, and dollar figure, including
  both reference runs and the $17.23 worst case.
- The 66,044-character restored body length.
- The 11-of-72 zero-activity figure and the median of 1 agent / 1 phase read.
- The full 34-PR blast-radius list and the 9-PR zero-activity subset.
- Every Tier 1 audit finding, including the #1438 Critical's *severity assessment* (the diff itself
  is re-derived above) and the #1459 filing-key refutation.
- The **5 of 5** post-removal `is_error=false` sample. That was a snapshot taken at measurement time;
  more post-removal runs have fired since, and this page deliberately does not update the number.
