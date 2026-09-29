# Reference: Over-grade calibration gate

The text below is written for the Decide outcome 2 trigger. On the Step 3.5 fix-delta trigger, `references/fix-delta-gate.md` owns the firing condition and routing, a flagged finding with no recorded evaluation included; the flag, the required `severity-calibrated` record and the behavior-inert cap below apply unchanged, and the fix-delta gate's own Reflections bullet replaces the one below.

Decide outcome 2 promotes a whole new iteration (plus a re-shadow) on a reviewer's emitted `Critical`/`Important` label with no severity re-check. The loop must not trust an emitted severity in *either* direction without a recorded technical evaluation against the finding's observable fail-direction and impact.

Fires before any new `Critical`/`Important` shadow Phase 3 finding drives a Decide outcome 2 promotion (the shadow-promotion path). Not on outcome 1, not on outcome 3, not on a REJECT.

For each new `Critical`/`Important` finding that would drive the promotion, flag it as a *suspected over-grade* when it matches one of the observable over-grade shapes — keyed on observable signals, never on a re-judgment of merits. **The over-grade shapes have a single definition, in `skills/review/phases/phase-4-verdict.md` Phase 4.1.5 (*Over-grade advisory annotation*); this gate consumes that canonical list and does not restate it here** (if it is not in context, Read it before flagging).

On a flag, the gate flags and requires a recorded technical evaluation; it never auto-demotes. The required evidence is a structured per-finding evaluation persisted to `fix_decisions` (the array Step 3 writes), of the shape `{finding_id, decision: "severity-calibrated", source_file, claim_text, original_severity, calibrated_severity, evidence}`, where `evidence` cites the observable fail-direction/impact: which over-grade shape matched, what the suite catches RED (or which direction the code fails), the real blast radius, and the grade it supports. That record — not the gate — decides the finding's fate: it either drives the promotion at its re-affirmed/calibrated severity, or calibrates it down with the recorded evidence as the reason (a Step 3 `decision`/`skip_category` records the parked outcome as usual). Who writes it: for a shadow-promoted finding this gate (Step 2.6, pre-promotion) and Step 3 item 2 coincide — one record satisfies both, and it exists before the promotion the gate guards.

A flagged finding with no recorded technical evaluation neither promotes nor is dropped — it blocks at this gate and is treated as non-convergence at Loop Exit (see "Verdict → chat output"): the run may not emit a clean APPROVE-family verdict while one exists, and at the iteration cap it surfaces through the `APPROVE WITH UNRESOLVED SHADOW FINDINGS` (or REJECT, if Critical) path.

One shape-2 sub-case resolves the required evaluation deterministically — the behavior-inert prose cap (consumed from `skills/review/phases/phase-4-verdict.md` Phase 4.1.5, not forked). A finding whose sole observable impact is the prose itself, on prose that is behavior-inert under review 4.1.5's two limbs, is classified ≤ Suggestion/Minor by review 4.1.5 as a classification rule. For such a finding the gate's required `severity-calibrated` record is produced deterministically — `{decision: "severity-calibrated", calibrated_severity: "suggestion", evidence: "behavior-inert prose cap (review 4.1.5) — sole observable impact is the prose itself and both inertness limbs hold"}` — so it is calibrated down with recorded evidence and therefore cannot drive a Decide-outcome-2 promotion. Inherited from 4.1.5: prose that can change behavior is never capped — it drives REJECT/promotion as usual.

Record one `## PRFlow Reflections` bullet — each flagged finding, its recorded evaluation, and the calibrated severity, or `over-grade calibration gate clean: no promote-path finding flagged`. State a calibration plainly in the verdict; never present a calibrated-down finding as if it had never been graded high.

A consumer repo sharpens these over-grade shapes with local instances via `.prflow/skill-extensions/review-and-fix.md`; the extension does not replace this gate.


<!-- END over-grade-gate.md -->
