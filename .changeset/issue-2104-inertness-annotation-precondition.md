---
bump: patch
type: Changed
---

- **Record the Phase 4.1.5 inertness enumeration and require it before the self-contradicting-diff carve-out fires.** The review engine now writes a structured inertness annotation (`first-conjunct`/`limb-one`/`limb-two` dispositions plus an evidence clause) on every finding the Phase 4.1.5 behavior-inert prose cap evaluates, and Phase 4.2 treats that annotation as a precondition for a carve-out REJECT — a carve-out candidate lacking it triggers the enumeration on the spot rather than defaulting to the harsher outcome invisibly. The fail-closed routing is unchanged; the record only makes a skipped enumeration auditable in the posted report. (#2105)
