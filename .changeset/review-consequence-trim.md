---
bump: patch
type: Changed
---

- **Removed rationale prose from the `/prflow:review` engine.** The skill root and its nine phase references drop 29,495 bytes (9.7%), from 303,098 to 273,603. The sweep deletes only sentences and clauses whose sole job is to explain why a rule exists or what breaks if it is skipped. Every severity definition, demotion rule, threshold, phase transition, agent dispatch, verification-mode routing rule and verdict condition is retained, as are all boundary markers, command fences and the `config_only` extension set that `phase-0-setup.md` and `phase-3-agents.md` deliberately carry in duplicate. Security-relevant prose — prompt injection, untrusted check names and command output, the trusted-source boundary, the read-only reviewer allowlist — was retained in full by rule rather than judged case by case. A side effect is that `skills/review/SKILL.md` moves from 640 bytes under the read-truncation ceiling to 5,224 under it.
