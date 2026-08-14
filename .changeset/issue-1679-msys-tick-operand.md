---
bump: patch
type: Fixed
---

- **Protect workpad ticks from MSYS path conversion.** The Phase 3 `/simplify` gate now ticks
  its Progress row with the host-safe substring `simplify` instead of `/simplify`, so Git Bash
  and MSYS no longer rewrite the standalone slash-leading argument into a Windows path before
  native `python3` receives it. The derived live-tick guard is extended to reject every static
  standalone slash-leading `--tick-progress` operand (quoted and unquoted) and to classify the
  shell-variable operand forms, and the Windows docs gain the standalone-argument hazard and the
  host-safe operand rule. (#1680)
