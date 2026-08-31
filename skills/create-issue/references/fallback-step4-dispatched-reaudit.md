<!-- prflow:create-issue-ref step=fallback-step4-dispatched-reaudit file=skills/create-issue/references/fallback-step4-dispatched-reaudit.md start -->

   A dispatched re-audit runs the pre-dispatch canonical-draft write, then `query-arm` → `record-dispatch` → dispatch, exactly as Step 3.6 specifies. Its return is handled by the same loop as Step 3.6 — `record-return`, obey `query-next-action`, verify findings against the code, revise, re-run the no-options gate, run **Revision-delta verification**, re-present — and its report overwrites the same `.prflow/tmp/create-issue/<slug>/issue-audit-<slug>.md` artifact.

<!-- prflow:create-issue-ref step=fallback-step4-dispatched-reaudit file=skills/create-issue/references/fallback-step4-dispatched-reaudit.md end -->
