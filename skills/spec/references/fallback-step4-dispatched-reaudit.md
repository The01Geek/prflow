<!-- prflow:spec-ref step=fallback-step4-dispatched-reaudit file=skills/spec/references/fallback-step4-dispatched-reaudit.md start -->

   A dispatched re-audit runs the pre-dispatch canonical-draft write, then `query-arm` → `record-dispatch` → dispatch, exactly as Step 3.6 specifies. Its return is handled by the same loop as Step 3.6 — `record-return`, then obey `query-next-action`, whose `revise-then-evaluate-offer` arm revises and re-presents the draft — and its report overwrites the same `.prflow/tmp/spec/<slug>/issue-audit-<slug>.md` artifact.

<!-- prflow:spec-ref step=fallback-step4-dispatched-reaudit file=skills/spec/references/fallback-step4-dispatched-reaudit.md end -->
