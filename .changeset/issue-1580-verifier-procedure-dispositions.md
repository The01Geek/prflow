---
bump: patch
---

Phase 3.4's two acceptance-criteria verifiers now declare what procedure they ran, not
only what they concluded. Each per-criterion record carries a stated disposition for
every named step of that verifier's own charter, written `yes` or `no` with a one-clause
reason, and the reconciliation core checks slot completeness before it reads any status:
a side that left a step undispositioned is forced to `unestablished` ahead of the pairing,
so a criterion both verifiers called `satisfied` still blocks when either failed to
attest. A stated `no` fully discharges its slot and changes no status by itself. The
dispositions ride into the reconciled record so the orchestrator writes them durably
alongside the verdict, making an abbreviated verification auditable after the run.
