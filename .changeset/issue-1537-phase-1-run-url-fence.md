---
bump: patch
type: Fixed
---

- **Compose the workpad run link inline in `phase-1-setup.md` so it never renders empty.** The §1.3 create and resume arms assigned `RUN_URL` in one bash fence but read it as `--run-link "[View run]($RUN_URL)"` in later, separate fences; since each `SKILL.md` fence runs as its own shell the variable was empty at both read sites, yielding the broken link `[View run]()`. Each arm now composes `RUN_URL` inline and omits `--run-link` entirely when it cannot be established, matching the `phase-3-review.md` precedent. (#1555)
