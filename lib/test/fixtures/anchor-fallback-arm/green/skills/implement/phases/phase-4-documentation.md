# GREEN fixture — vendored-literal leading token + anchor fallback arm (issue #1374)

```bash
.prflow/vendor/prflow/scripts/discover-deferral-manifests.py --presence-for-pr <this-run's-PR-number>
```

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/discover-deferral-manifests.py --presence-for-pr <this-run's-PR-number>
```

Issue #1560: the Phase 4.3 call site carries both forms for checkout-fingerprint.py and verification-flight.py.

```bash
.prflow/vendor/prflow/scripts/checkout-fingerprint.py
.prflow/vendor/prflow/scripts/verification-flight.py claim --input-file .prflow/tmp/c.json
```

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/checkout-fingerprint.py
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/verification-flight.py
```
