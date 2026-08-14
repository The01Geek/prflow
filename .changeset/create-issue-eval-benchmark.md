---
bump: patch
type: Added
---

- **Provider-neutral create-issue A/B benchmark harness.** Add `scripts/create_issue_benchmark.py`, a controlled baseline-vs-candidate runner over the create-issue evaluation, alongside the renamed `scripts/create_issue_eval.py` implementation module; both keep their hyphenated compatibility entry points so existing invocations resolve unchanged. Malformed manifests and unmirrored audit-state vocabularies now fail closed with the modules' own diagnostics rather than an interpreter traceback. The paired quality gate withholds efficiency credit for a new forbidden-*section* failure as well as a new forbidden-concept one, so a regression the aggregate pass rate hides cannot be credited as a win. (#1681)
