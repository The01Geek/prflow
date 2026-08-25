---
bump: patch
type: Changed
---

- **`lib/test/run-shard.sh` now names the absolute path of the log it retained, on both its passing and failing exits**, matching `run-parallel.sh`'s "retained logs" and `run-module.sh`'s "Log:" announcements — so an agent that tail-piped the shard's echoed output can re-read the full log instead of re-executing the shard. The single-flight consult obligation (in `CLAUDE.md`, `skills/review-and-fix/references/fixing.md`, `skills/implement/phases/phase-3-ac-gate.md`, and `skills/implement/phases/phase-4-documentation.md`) is widened from "before any full-suite relaunch" to any suite execution and any retained log; `fixing.md` gains a "narrowest covering test before the broadest" clause and a shipped-body retained-log re-read instruction; and the two `loop-exit.md` whole-suite triggers are caller-scoped so they do not double-pay against `/prflow:implement`'s Phase 4.3 whole-suite obligation. `CLAUDE.md` also drops rotted wall-clock measurements in favour of the qualitative claims they supported. (#1929)
