---
bump: patch
type: Fixed
---

- **Correct the `/prflow:implement` Phase 1.3 note attributing the reproduction-row default.** The §1.3 sentence in `skills/implement/phases/phase-1-setup.md` no longer says the `new-body` skeleton renders the reproduction row "from the label"; it now attributes the pre-rendered default to whichever caller invoked `new-body` — the cloud `gate` job from the `bug` label, §1.3's own `new-body` calls from the §1.1 content classification — matching the attribution already used in `skills/implement/SKILL.md`, while still stating that either default can disagree with the content classification and that `--reconcile-reproduction` is the authoritative correction. (#1545)
