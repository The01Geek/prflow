---
bump: patch
---

Remove the write-mode documentation-audit residue from `/prflow:docs-verify`'s `--report-only` mode (issue #1700).

Report-only now returns a code map plus one doc-reliability signal (`RELIABLE` / `UNRELIABLE` / `ABSENT`) in place of the `DOCS ACCURATE` / `DRIFT FOUND` / `DOCS MISSING` verdict, and no longer declares a `Drift detail` field. The write-mode documentation-comparison checklist is gated to the write path, report-only is directed instead to use documentation for context and establish every reported detail from the code, and the three-fate rule for doc-sourced claims moves into the report-only identity section with a contradiction routed to `Current behavior`.

`/prflow:create-issue` reads the new signal as its Step 1 escalation limb and no longer renders documentation drift into a filed issue: the issue template's `Documentation Drift` bullet is gone.
