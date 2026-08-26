# Cutover — issue #1374: Phase 4.0.5 relocated behind a predicate-gated reference

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.

`/prflow:implement` reads `skills/implement/phases/phase-4-documentation.md` in full on every
Phase 4 entry, and again after the §4.1 documentation subagent returns. Both reads are
mandated by the always-resident orchestrator, so neither is avoidable. §4.0.5's filing
procedure — which runs only when Phase 3.3 produced a deferrals manifest — was paid on every
one of those reads regardless, because the decision to skip it is one the agent makes *after*
reading it.

This change applies §4.0's shape (issue #815) to the other deferral channel: a short stub in
the phase file, one predicate, and a gated reference read only when the predicate says a
deferred review finding is present.

## Measured delta (a past-time snapshot, counted with `wc -c` at commit `22e059c18` against
merge base `d51335bfb`, captured 2026-08-07)

| File | Before | After |
| --- | --- | --- |
| `skills/implement/phases/phase-4-documentation.md` | 95,924 | 69,266 |
| `skills/implement/references/deferred-review-findings.md` | — | 30,316 |

The phase file is the always-read surface, so the always-read count falls from 95,924 to
69,266 bytes per mandated read — 26,658 fewer, and 53,316 fewer across the two reads a Phase
4 run makes. The stub is larger than a minimal routing stub would be because review hardened
its arms: the skip requires both exit `1` and the literal `absent: 0` line, and the
fallback-arm trigger names `Permission denied` and rc 126 alongside the not-found readings. These figures are a **past-time snapshot**, not a live measurement: they record
what the move cost at the moment it was made, so a later change to either file does not
retroactively falsify the record. **No byte ceiling on either file is enforced anywhere in
the tree**, and this page registers none — the same correction this change made to the #815
cutover page, which had described such a gate as live. **Superseded 2026-08-11 by issue
#1595:** a ceiling now exists (`lib/test/lint-reference-size.py`, 61,750 bytes over every
boundary-gated reference and skill root that holds no live exemption). It is a reader-capability limit — above it a
single read returns a `start` marker and no `end` marker — not the authoring budget the
sentence above was denying, and this page still registers none of its own.

## The predicate's three-state contract

`scripts/discover-deferral-manifests.py --presence-for-pr N` answers over **both** presence
sources — the run-scoped manifests it discovers under the candidate search directories, and
the slug-level aggregate at `pr-<N>/deferrals.json`. Reading either alone fails open: on a
first Phase 4 entry the aggregate has no producer, and on a re-entry after filing the
run-scoped manifests are already consumed.

| State | Exit | stdout |
| --- | --- | --- |
| present | `0` | `present: <n>` |
| absent | `1` | `absent: 0` |
| unestablished | `2` | `unestablished: reason=<token>` (plus an optional `root:` line) |

A malformed invocation reports `2`, the same fail-closed convention `scripts/workpad.py
deferred-presence` adopts, so a bad call loads the reference rather than silently skipping it.

**`1` is also CPython's exit status for an uncaught exception**, and `1` here means "skip the
procedure" — so a caller routing on the exit status alone would read a crash as "nothing was deferred" and
strand every acknowledged finding.
Two layers close that. In the helper, `_run_presence` wraps the mode in a `BaseException` handler
that routes any escaping exception to `unestablished: reason=internal-error`. In the stub, the
skip arm requires **both** exit `1` **and** the literal `absent: 0` line, so an exit `1` carrying
no such line falls to the residual arm — read the reference, record a `note` reflection — rather
than to the skip. The three states are complete by construction only because of those two, not
because the enumeration says so.

The `reason=` tokens are a consumed contract — the stub quotes the token into its reflection — so
each names the operand that could not be established: `malformed-invocation`,
`unreadable-review-root`, `branch-unresolvable`, `unreadable-directory`,
`unreadable-aggregate`, `internal-error`, `branch-slug-empty` (a non-empty branch whose
every character the keep-filter drops, leaving the candidate unformable) and
`branch-slug-escapes-review-root` (a slug that is formable but resolves
outside the review root). Eight in all, named as module constants rather than literals at
each call site, because the stub quotes the token into its reflection and a drifted token
would be invisible until a reader met an unfamiliar word in a workpad.

The filing fence handles both branch-slug reasons — an empty slug and one escaping the review
root — by breadcrumbing and falling back to `pr-<N>`-only search,
which is right for a best-effort filing step. It is wrong for a *gate*: on a first Phase 4 entry
the branch candidate is the sole source, so a fallback there would report `absent` over evidence
the mode never looked at.

**Every probe presence mode itself performs is a guarded `stat`, never `os.path.exists`/`isdir`.**
Those suppress every `OSError`, so a mode-000 ancestor, a stale mount, or an `EIO` reads
identically to a genuinely missing path — which would classify an unreadable tree `absent` and
reintroduce the issue-#555 silent-loss shape one level above the guard that closed it. That
covers the review root, each candidate root, and the aggregate.

The candidate pre-probe is deliberately a *separate* guarded `stat` rather than a change to
`classify_root`, which still reaches its own verdict through `os.path.exists`/`os.path.isdir`.
`classify_root` is shared with the discovery mode, whose per-root classification this change
holds fixed, so hardening it here would alter behaviour the change promises to leave alone. The
consequence is stated rather than papered over: **discovery mode retains that swallow**, and an
`ELOOP` or `EIO` candidate still classifies `absent` for the filing fence. Presence mode no
longer inherits it; closing it for discovery mode is separate work.

**A branch git could not resolve is `branch-unresolvable`, not a detached HEAD.** Only git
*answering cleanly with empty output* is the benign case. On a first Phase 4 entry there is no
aggregate yet, so a branch-mode `/prflow:review-and-fix` run's manifest lives **only** under the
branch slug: reading a `dubious ownership` refusal, an absent `git`, or a timeout as a detached
HEAD would search the PR slug alone and report `absent` on exactly the run the predicate protects.

## Accepted loss: partial and all-failed collapse into unestablished

The helper's discovery mode distinguishes a *partial* traversal failure (`3`) from a *total*
one (`4`). Presence mode does not: any unreadable candidate directory or unreadable aggregate
reports `2`, whether one candidate failed or both. That distinction is genuinely lost, and it
is taken deliberately so both gated Phase 4 sub-steps document one identical three-state
contract a reader learns once. The cost is bounded — the stub's response to `2` is to read the
reference, which is the same response it would give to a partial failure — and the discovery
mode's own richer contract is untouched for the filing fence that consumes it.

## The stub's degraded arms, in full

- **exit 0** — read the reference and follow it.
- **exit 1 *and* the printed line is exactly `absent: 0`** — do not read the reference; continue
  to §4.1. Both conditions, because `1` is also a crashing interpreter's status.
- **every other outcome** — exit `2` with its reason token, exit `1` without that line, any other
  exit code, or no output at all (the shape a harness refusal takes). Read the reference anyway
  and record a `note`-kind reflection naming what was actually observed. This arm is the
  **residual**, so an outcome nobody enumerated lands here rather than on the skip. An unavailable
  operand is never read as "nothing was deferred".
- **the vendored path did not run** — `command not found`, `No such file`, `Permission denied`,
  rc 126 or rc 127. Re-invoke through the portable anchor. `Permission denied` is in that set
  because a consumer whose vendor step dropped the executable bit reports rc 126, which a trigger
  naming only the not-found reading would leave with no second arm.
- **the reference read fails** — absent, empty, harness-refused, or mismatched boundary
  markers. Records a `dropped-failed` reflection naming the reference path and continues to
  §4.1 without halting Phase 4.

## The `tr` dependence the predicate does not inherit

The filing fence derives its branch-slug search directory through a `tr` chain, and `tr` is
not in the project's preflight-guaranteed set. A missing `tr` empties the slug, which the
fence handles with a breadcrumb and a fallback to `pr-<N>`-only search. The predicate cannot
take that fallback silently — a gate that skips a search directory would report `absent` for a
PR whose deferrals live under the branch slug — so it derives the slug in Python instead.

`lib/test/test_python_scripts.py` asserts the port against the fence's own `tr` pipeline over a
table of branch-name shapes, **extracting that pipeline from the shipped reference file at test
time** rather than re-typing it. That is what makes it a differential: a hand-typed chain in the
test would keep agreeing with the port after someone widened the fence's keep-set, and the drift
the criterion exists to catch would ship green.

This closes the dependence for the **gate**, not for the fence: on a host without `tr` the
predicate can now report present from a branch-slug directory the fence then does not search,
which routes to the fence's existing breadcrumb and files nothing from that root. That is the
pre-existing behaviour for such a host, unchanged.

## Coupled sites moved in the same commit

Every assertion that located §4.0.5 content by naming the phase file's path was re-targeted
rather than deleted — **with the one retirement recorded below** — because an assertion left on
the phase file reports a count of zero and passes nothing. That covers the `#254` branch-slug and
search-set pins, the `#555` discovery pins, the `#275` portable-anchor `file-deferrals.py` pin,
the `#271` `run-jq.sh` pin, the `#480` sentinel pins (two of which *execute* the shipped sentinel
line, and one of which probes operand-initialization ordering), the `ensure-label.sh` per-file
counts, and the positional routing-bullet count. The `### 4.0.5` heading stays at line start in
the phase file, because the `#815` section-4.0 `sed` range terminates on it; without it the
slice runs to end of file and stops being scoped to §4.0, so its count no longer attributes
what it measures to the section it names.

### The one retirement, and its authorization

`lib/test/run.sh`'s routed-comparand loop asserted three printed literals against the phase file.
Two belong to §4.1 and stay. The third, `deferred labels to apply: [`, moved with the fence and
was **retired rather than re-pointed**.

That literal resolves into agent-executed prompt prose, so re-stating it against a new target is
new wording-only pin authorship — which `CLAUDE.md`'s issue-#810 authoring boundary prohibits and
the diff-scoped mutation-routing gate reports. The pin is a raw `grep -qF` inside `assert_eq`, so
it is **outside** the existence-pin census and no ledger row for it can be minted; `CONTRIBUTING.md`'s
*Disposing of a pin outside the existence census* therefore routes the decision to the parent
prose-pin policy's own question — does any tool or consumer read the pinned content?

**The consumer search, run over the surface the lint's own `machine_consumer_evidence` reads**
(tracked `scripts/`, `lib/`, `.github/` minus `lib/test/`, with `#`-comment regions subtracted —
211 files) returned **no reader**: the literal occurs in no consumer file's operative text.
`distinctive_consumer_tokens` yields an empty token set for this literal, so the search reduced to
whole-literal containment; that narrowing is recorded here rather than left implicit, since a
token-level match could in principle have found a generic consumer this search cannot see.

What stops being asserted: that the §4.0.5 label-config fence still *prints* the line its own
reader-routing arms literal-match. Per the recorded decision that agent-executed prompt prose
carries no automated regression coverage by design, retirement owes no replacement coverage, and
the compensating control is the review pass.
