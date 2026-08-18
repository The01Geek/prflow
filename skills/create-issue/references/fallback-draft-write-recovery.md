<!-- prflow:create-issue-ref step=fallback-draft-write-recovery file=skills/create-issue/references/fallback-draft-write-recovery.md start -->

## Recovering a disagreeing write and a drifted binding nonce

Recovery on disagreement (revision writes)

When `agree=no` after a revision write, record `record-write-failure --ordinal <N>` (N from the `record-revision --stdin-digest` step of the Staged canonical-draft write procedure in `references/step-3-6-audit-shared.md`, same turn), present from the in-context revision bytes rather than the canonical file, and re-run `apply` exactly once from the still-present staging artifact — named from the durably recorded path, never "the newest artifact on disk". Resolve it with:

```bash
python3 "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/issue-audit-state.py query-staged-write "<slug>" --nonce "<nonce>" --digest "<the revision's stdin_digest>"
```

If that single re-attempt also disagrees, stop retrying, report `--write-landed no` to `query-arm` (which routes the round to the embed arm), present from the staging artifact's bytes, and surface the persistent failure to the user — filing is never blocked. Once a retry agrees, record a fresh `record-revision --stdin-digest` over the same staged bytes. Clearing the presentation flag additionally needs a subsequent file-arm dispatch record carrying that revision's digest; that flag governs presentation source alone and gates nothing.

Foreign-nonce arm (a drifted nonce is NOT an unbound run — surface it, never fold it into `bound=none`)

`bound=none … reason=foreign-nonce` means the run is bound; only the nonce you hold has drifted from the one the record holds. On this answer: do not compose a path and do not silently proceed. First attempt recovery — re-derive the run's nonce with `query-nonce "<slug>"` and re-query with the recovered value; if it then answers a real absolute root, continue on the already-bound branch of `references/step-3-6-audit-dispatch.md`’s Bind the draft root step. If recovery is unavailable or the answer still carries `reason=foreign-nonce`, stop and tell the user that this run's nonce has drifted from the recorded draft-root binding, naming that the tool will still emit from the recorded binding so proceeding would file stale bytes.

<!-- prflow:create-issue-ref step=fallback-draft-write-recovery file=skills/create-issue/references/fallback-draft-write-recovery.md end -->
