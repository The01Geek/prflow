# Reference: Pre-fix Gates (Step 2.5 + Parked-class sweep)

### Step 2.5: Pre-fix verification gate

Before applying any fix, classify each finding in Step 2's effective fix set, so the loop never auto-applies a confidently stated but wrong fix. Phase 2 checklist FAILs and Phase 3 findings with `corroboration_count >= 2` are corroborated: pass them straight to Step 3. For each remaining single-source finding:

1. Classify the claim. An external-tool claim rests on a framework, CLI flag, CI semantic, library API or platform behavior that documentation can settle (e.g. *"`id-token: write` only takes effect at workflow level"*): verify it below. A codebase claim is about this repository only: pass it to Step 3 unchanged.
2. Verify on the web, at most 5 WebFetches per iteration (an external-tool claim past the budget becomes advisory): fetch the most authoritative source — official documentation, then the tool's repository or release notes — using WebSearch only to find it.
   - Confirmed (the docs support the claim) → Step 3 fixes it.
   - Refuted (the docs contradict it) → demote to advisory tagged `refuted by {url}`, and add a `## PRFlow Reflections` line `verified false positive — {claim text} — refuted by {url}`.
   - Inconclusive → demote to advisory.

   Without WebFetch/WebSearch, demote each external-tool claim to advisory with `step25_classification: "tools_unavailable"`.
3. List every advisory finding verbatim under the iteration report's `## Advisory Findings`, with its one-line reason (`refuted by {url}`, `inconclusive after web verification`, `over verification budget`). Advisory findings stay unfixed unless Step 2.6 reopens one, and turn a clean final APPROVE into `APPROVE WITH ADVISORY NOTES`. At demotion time append the row `{finding_id, decision: "advisory", source_file, claim_text, skip_category: "advisory-parked", evidence: <reason>, parking_evidence}` (root *Field rules*), whose `parking_evidence.source` is the refutation URL on a `web_refuted` demotion, else `null`.

### Parked-class sweep (pre-shadow convergence gate)

When a convergence entry — Step 2's tentative non-REJECT verdict, Step 4.5's non-REJECT early exit, or the Clean-iteration-1 exit — carries parked findings, search for unfixed siblings of their classes before the shadow runs. This sweep is in-line, uncounted toward `$MAX_ITERS`, and dispatches nothing.

Inputs: advisory-parked rows; every unactioned Suggestion/Minor finding (recorded `phase3_findings` minus each record's `applied` rows and Phase-4-demoted rows, `below-threshold` producer rows included); deferral rows (`claim-quality` / `out-of-scope` / `already-tracked`). `settled-by-disclosure` foreclosure rows are also part of this union. Skip a finding whose recorded evidence proves it false (`refuted by {url}`, or a `claim-quality` pushback disproving it). When a record is missing or unparseable, sweep what is readable; the sweep is not completed (`parked population unestablished`).

For each input, take its class — `defect_signature.kind`, or the defect its description names when the kind is missing — and search the changed surface (the PR diff plus files this run's fixes touched) for other instances, by the class's identifiers and shape, with the Grep tool, else `git grep --untracked -nP -e '<pattern>' -- :/`; a Grep tool error or `git grep` exit above 1 leaves the sweep not completed (`search failed`). A site already registered (same file, overlapping `line_range`) is not new. Append each new sibling to the triggering iteration's `phase3_findings` with its full `defect_signature` and its source finding's severity (re-graded only with recorded evidence). Then route:

- A sibling at or above `$FIX_THRESHOLD` that is Critical or Important, or lands within the damper window (N+1 ≤ `$FIX_BELOW_ITERS`), and whose source finding the engine report did not cap at Suggestion as behavior-inert prose (all three inertness slots `held`), drives a promotion: every at-or-above-threshold sibling of the sweep — its *promotable set* — enters Step 2.5 → Step 3 as one promoted iteration, by Decide outcome 2's machinery (no Step 1, re-shadowed).
- Every other sibling is parked under `## Advisory Findings` with an advisory row marked `parked-sibling: class-sweep` and `parking_evidence` (`basis` its parking reason, `source` its site, `finding_ref` its registered row).
- At the iteration cap, register every sibling anyway; while an unfixed promotable sibling exists Decide outcome 1 is barred and the shadow's cap branch surfaces it (`APPROVE WITH UNRESOLVED SHADOW FINDINGS`, or REJECT for a Critical).

Record the `parked_class_sweep` block (`not_completed` the cause, else `null`) in the triggering iteration's record. Add a `## PRFlow Reflections` bullet only for a class that found siblings or a sweep not completed, blocking nothing.

<!-- END pre-fix-gates.md -->
