# RED fixture — anchor leading token with NO vendored-literal fallback arm (issue #1374)

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/discover-deferral-manifests.py --presence-for-pr <this-run's-PR-number>
```

Issue #1560: checkout-fingerprint.py and verification-flight.py appear in anchor-only form (no
vendored line), so those sites exercise the anchor-only arm, not the carries-neither arm.

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/checkout-fingerprint.py
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/verification-flight.py
```
