---
bump: patch
---

Dispatch Phase 1.4's branch resume-precheck, reuse-or-create signals, feature-branch creation, and §1.4.0.5 Verdict-B classification to a new first-party `branch-setup` subagent that shares the orchestrator's checkout, shrinking `skills/implement/phases/phase-1-setup.md` (re-read on every Phase 1 entry) while keeping the §1.4.1 checkpoint contract, its invocation, and §1.5 orchestrator-inline (#1582, PR #1589).
