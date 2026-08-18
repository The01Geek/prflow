# RED fixture — anchor leading token with NO vendored-literal fallback arm (issue #1374)

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/discover-deferral-manifests.py --presence-for-pr <this-run's-PR-number>
```

Issue #1560: each newly-enrolled helper appears in anchor-only form (no vendored line), so
the anchor-only arm is exercised rather than the carries-neither arm.

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/checkout-fingerprint.py
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/verification-flight.py
```
