---
bump: patch
type: Fixed
---

- **`/prflow:create-issue` prose fixes from consumer-repo feedback.** The no-options gate now carves out the verbatim quoted span inside a `Verified:` bullet, so a repository sentence that happens to contain a gate word (a docblock reading `optional`) no longer forces the drafter to shorten a citation another rule mandates. The default (no-audit-round) creation call now names its operand literally as `--round 0` rather than leaving it unstated. The synchronous-dispatch discipline in the Step 3.6 auditor dispatch and the Step 1 docs-verify peer dispatch now names wait-for-completion-notification as a first-class way to comply, for runners whose subagent tool launches asynchronously and offers no `run_in_background` parameter. And the provenance-line rule no longer claims the line is appended ahead of the first canonical write — the run bootstrap writes the canonical draft first — stating instead that it is appended before the presentation write.
