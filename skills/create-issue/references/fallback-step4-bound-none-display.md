<!-- prflow:create-issue-ref step=fallback-step4-bound-none-display file=skills/create-issue/references/fallback-step4-bound-none-display.md start -->

`bound=none` arm (no `reason=`): for a legitimately unbound run there is no bound root to display; never substitute the token into the path. Omit the draft-path note entirely and print the full body per the forced-render arm (sub-step 1), exactly as the write-failure arm does. `reason=foreign-nonce` is a distinct arm, never this one: the run *is* bound and only the nonce drifted, so take the foreign-nonce arm of `references/fallback-draft-write-recovery.md`, loaded per `references/degradation-routing.md` — recover the nonce and re-query, else stop and tell the user the drift.

<!-- prflow:create-issue-ref step=fallback-step4-bound-none-display file=skills/create-issue/references/fallback-step4-bound-none-display.md end -->
