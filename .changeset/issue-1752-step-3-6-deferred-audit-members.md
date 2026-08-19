---
bump: patch
type: Changed
---

- **`/prflow:create-issue` loads the Step 3.6 dispatch and adjudication procedure members only when an audit round is elected.** The run bootstrap (`init` and the nonce, the canonical-draft write and its two Step 3.5 gates, and the draft-root binding) is re-homed into the always-loaded shared member, so a run that elects no audit round at the Step 4 pre-approval pause no longer reads the two audit-only members — cutting the reference bytes such a run pays for on every invocation. The bootstrap, the acceptance-criteria parseability gate, and the Verified-premise handle check still run unconditionally before the pause. (#1767)
