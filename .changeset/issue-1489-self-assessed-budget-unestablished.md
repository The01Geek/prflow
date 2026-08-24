---
bump: patch
type: Changed
---

- **A run's self-assessed budget or context state is now stated as an unestablished measurement, and may not narrow a mandated verification step.** The #1230 refusal — previously scoped to the Step 2.6 shadow pass — is generalized: a run cannot establish its own remaining context on any tier, so a self-assessed budget or context state is never a reason to skip, narrow, defer, or degrade any mandated verification step (the reviewer roster, the checklist steps, the bounded re-review, or the shadow). The prohibition and its legal exit (perform the step, or stop at a non-terminal/`Blocked` status naming the step not performed) now sit at the review engine's two dispatch-deciding phase references, the shadow-review reference, the implement fix-loop exit, and the review engine's no-verdict terminal arm, binding local and cloud runs identically. (#1908)
