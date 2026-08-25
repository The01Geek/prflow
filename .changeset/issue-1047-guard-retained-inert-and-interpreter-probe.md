---
bump: patch
type: Fixed
---

- **The `PreToolUse` shape guard's hook command now fails open when `python3` is absent, and the wiring question is recorded as decided.** The registered hook probed for the guard *script* and exited 0 when it was missing, but ended in a bare `exec python3` — which exits 127 on a host with no `python3` on `PATH`, routine on a self-hosted Windows runner. Since a non-zero `PreToolUse` exit blocks the tool call rather than falling through, that turned a missing interpreter into a blocked Bash call on every invocation for a consumer still running the pre-#937 review tier; the command now carries `command -v python3 >/dev/null 2>&1 || exit 0`. Alongside it, issue #1047's wiring question is settled as **retained-but-inert** — the guard stays registered on `devflow-runner.yml` and no live tier registers it — with the rationale, the evidence that would reopen it, and why deletion was refused recorded in `docs/internal/cloud-allowlist.md`. Two implement-tier rationale comments that asserted a *measured* matcher refusal of leading `VAR=$(…)` captures are corrected to say unmeasured, matching what `lib/test/extract-command-shapes.py` already records. (#1047)
