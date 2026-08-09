---
bump: patch
---

**`Status: Complete` is now gated on a machine-readable review-coverage record.** A run whose Phase 3 review pass fell short — a shadow that was not verified, a reviewer roster short of the expected set, a skipped checklist step — could previously write `Status: Complete`, mark the PR ready, and leave the shortfall recorded only as free-text prose nobody was required to read before merging.

Phase 3.3 now stamps the coverage fact it already resolves from the loop-verdict marker onto the workpad as a keyed record — `workpad.py update <issue> --record-review-coverage <coverage> <dispatch> <roster> <checklist>` — and `scripts/workpad.py`'s terminal gate gained a fourth member beside the acceptance-criteria, completion-evidence and required-artifact members: an `update --status Complete` write is structurally refused (no PATCH) when that record is absent, duplicated or malformed, or when a gap it records carries no disposition. Phase 4.3 instructs the run to refuse `gh pr ready` on the same condition, so an incomplete pass leaves the PR a draft rather than publishing beside a Blocked workpad.

The escape hatch is `--review-coverage-disposition <gap> "<reason>"`. Its **cause** predicate is the recorded dispatch-attempted fact rather than a cost/budget word blocklist: a fan-out that was dispatched and fell short may state any true cause, cost included, while a run that never dispatched the shadow cannot complete at all. The reason string is still screened for being a generic placeholder, so a disposition names the specific gap. Each accepted disposition also files its own `dropped-failed` reflection, so a run that carried a gap forward to `Complete` reaches the weekly retrospective. (#1453)
