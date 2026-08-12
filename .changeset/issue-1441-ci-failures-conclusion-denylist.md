---
bump: patch
---

Fix `ci_failures_during_pr`, the retrospective cheap gate's CI signal, which was wrong in both directions.

A `cancelled` or `stale` check-run conclusion no longer counts as a failure. Each means the run was superseded before producing a verdict, and a new push cancels the in-flight run by design, so ordinary iteration was manufacturing "CI failures" and forcing LLM analysis on PRs that were never broken.

The check-runs read is now paginated. The endpoint serves a bounded page of check-runs per request, so a head with a larger CI matrix was silently truncated and the same field undercounted real failures. The filter merges across the concatenated per-page objects `gh api --paginate` emits before counting — adding the flag alone would have made every multi-page PR fail the numeric guard instead.

`failure`, `timed_out` and `action_required` still count, and the filter remains a denylist rather than a failure allowlist, so an unrecognised future conclusion counts as a failure instead of being read as success. The existing fail-safe arms are unchanged: a signal that cannot be read still reports unknown rather than clean. A body carrying no check-run pages, a `check_runs` that is not an array, and a check-run that is not an object are each an explicit error, so the paginated read cannot report a clean zero for a body it could not parse. The fail-safe path now leaves a breadcrumb naming which condition fired, so an API failure, an unreadable body and a genuinely clean head are no longer indistinguishable.
