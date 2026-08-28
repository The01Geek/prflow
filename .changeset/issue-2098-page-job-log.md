---
bump: patch
type: Added
---

- **Cloud review runs can page a CI job's log through one helper instead of refetching the whole log.** The new `scripts/page-job-log.py` takes a job id and a line range as plain-word arguments, downloads the job's log once into `.prflow/tmp/`, and slices the stored copy on every later call — printing a header line (total line count, range served, stored path, truncation) then the capped, sanitized window. The helper is granted in all three cloud allowlist profiles, and the review engine names it as best-effort: a denied invocation or an absent helper file degrades to the direct `gh run view --job <id> --log` fetch without blocking the review. (#2103)
