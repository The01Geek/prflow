<!-- prflow:review-ref phase=0.6 file=skills/review/phases/phase-0-6-stale-prose-lint.md start -->
### 0.6 Stale counted-prose lint (Phase 0.6 — deterministic, runs immediately after 0.5)

Run the bundled `stale-prose-lint.py` over the review diff from 0.2 — a deterministic pre-pass that flags diff-added prose whose counted claims a later commit outgrows or falsifies (a range header the block outgrew, a legend sum no longer matching its `Expected total = N`, an exact `count-locked` header, or a deny-absolute about a shell operator token the same file also asserts permitted). The helper's own header is the authoritative spec of the four rule classes (R1–R4) and of the out-of-scope behavioral-absolute subclass (routed to `comment-analyzer`, not detected here) — this skill does not paraphrase it.

Config gate. Read the `prflow_review.stale_prose` block via the same portable, skill-dir-anchored, no-`bash`-prefix `config-get.sh` invocation the verdict-threshold and live-comment reads use. `enabled` defaults `true`; only an explicit `false` disables the phase (every other shape resolves to enabled). `severity` defaults `important`; validate the enum inline and fall back to `important` on a resolver failure or a value outside `critical|important|suggestion`, with a specific breadcrumb:

```bash
if ! SP_ENABLED=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .prflow_review.stale_prose.enabled true); then
  echo "::warning::devflow review: could not read .prflow_review.stale_prose.enabled (config-get.sh rc≠0); defaulting to enabled" >&2
  SP_ENABLED=true
fi
if ! SP_SEVERITY=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .prflow_review.stale_prose.severity important); then
  echo "::warning::devflow review: could not read .prflow_review.stale_prose.severity (config-get.sh rc≠0); using default 'important'" >&2
  SP_SEVERITY=important
fi
case "$SP_SEVERITY" in
  critical | important | suggestion) ;;
  *) echo "::warning::devflow review: .prflow_review.stale_prose.severity '$SP_SEVERITY' is not one of critical/important/suggestion; using default 'important'" >&2; SP_SEVERITY=important ;;
esac
```

When `SP_ENABLED` is exactly `false`, skip the phase and record it — do not run the helper — with the note `stale-prose lint disabled by config`.

Confirm the cached diff is non-empty before running the helper. Phase 0.2 cached `diff.patch`; if that cache is absent or empty (an upstream truncation), the helper reads an empty diff and exits `0`. Do not run the phase against an empty cache: record the degraded-check note `stale-prose lint skipped: the Phase 0.2 diff cache is absent or empty` and route it exactly like arm (b).

Run the helper on the cached diff, resolving each claim's referent against the current head (`--rev HEAD`). It reads the unified diff on stdin and never derives the range itself. Feed it by pipe — the cloud-permitted shape Phase 0.2's own `… | tee` fence and `match-deferrals.py` already use; an input redirect is not in the enumerated permitted set:

```bash
cat .prflow/tmp/review/<slug>/<run-id>/diff.patch | "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/stale-prose-lint.py --rev HEAD
```

**Observe the helper's exit code — it is the authoritative arm selector, and stdout alone is not.** Do **not** capture it into a second shell variable (a split `SP_RC=$?` read in a later statement is stripped by some inline-bash runners). Route on the exit code first, then on each row's verdict, and **never read an empty stdout as "no stale claims" without first confirming the exit code was 0 or 1** — an internal error (exit 2) also prints no verdict rows:

- Exit code `0` or `1` — the helper ran to completion (`1` means at least one STALE row is present; `0` means none). Route each stdout row (`verdict<TAB>rule<TAB>file<TAB>line<TAB>detail`) by its verdict below.
- Exit code `2` — the helper reported an internal error and printed no verdict rows on stdout (its diagnostic is on stderr): take degradation arm (c). Do not read the empty stdout as a clean pass.
- The command was refused (never executed) or reported `No such file` — take degradation arm (a) / (b) respectively.

For the exit-code 0/1 path, route each output row by verdict:

- `STALE` → enter each row as an engine finding at `$SP_SEVERITY`, carrying its TSV row verbatim as the finding's evidence. These participate in Phase 4.2 verdict computation like any other finding at that severity — no new verdict or accounting rule.
- `UNRESOLVABLE` → record as an informational note; it never gates the verdict.
- `VERIFIED` → no action.

Adjudication carry-forward (PR mode only — demote STALE rows a prior run already adjudicated a false positive). Before finalizing the STALE rows as findings, join them against the false-positive adjudications a prior trusted run stamped in this PR's own progress comments, via the bundled helper `scripts/match-lint-adjudications.py` (which owns the entire join — trust guard, base64 decode, byte-identity match — so this prose only fetches comments, pipes JSON, and renders the map). Run this only when a PR number is in play and at least one STALE row was produced above; in current-branch mode, or on a PR's first run (no prior comments), there is nothing to join and it is a no-op.

1. Collect the current STALE rows as a JSON array of their verbatim TSV lines (`verdict<TAB>rule<TAB>file<TAB>line<TAB>detail`) — author it with the **Write tool** into the run-scoped scratch file `.prflow/tmp/review/<slug>/<run-id>/stale-rows.json` (the same probe-permitted in-workspace shape the live-comment body uses).
2. Fetch this PR's own prior `prflow:review-progress` comments, shaped for the helper. Consume the `gh api` stdout from the tool result and Write it to the run-scoped file only after an exit-0 fetch; a granted `gh` head does not prove a redirect form. `--paginate` applies `--jq` PER PAGE, so the file holds CONCATENATED arrays (`[...][...]`) — step 3 flattens them (`$comments | add`).

   Use the `{owner}/{repo}` placeholders `gh` fills from the remote — never `$GITHUB_REPOSITORY`. Run this without a redirect, require exit 0, then Write its exact stdout to `prior-comments.json`:

   ```bash
   gh api --paginate "repos/{owner}/{repo}/issues/$PR_NUMBER/comments?per_page=100" \
     --jq '[.[] | {author: .user.login, author_type: .user.type, body: .body}]'
   ```

   A non-zero exit here, or a `prior-comments.json` that is empty / does not parse as a JSON array, is a fetch failure — not "no prior adjudications": take the step-5 degraded arm (leave every STALE row at `$SP_SEVERITY`, record a degraded-check note naming the failed fetch and carrying its stderr).
3. Assemble the helper input and run the join. `jq` combines the two arrays into the one stdin object the helper reads (`{rows, comments}`); the helper prints a demotion map on stdout. It resolves `.prflow/config.json` (for the `.prflow.allowed_bots` author allowance) from the repo root, so no `--config` is needed:

   ```bash
   "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/run-jq.sh -n \
     --slurpfile rows .prflow/tmp/review/<slug>/<run-id>/stale-rows.json \
     --slurpfile comments .prflow/tmp/review/<slug>/<run-id>/prior-comments.json \
     '{rows: $rows[0], comments: ($comments | add // [])}' \
     | "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/match-lint-adjudications.py
   ```
4. Apply the demotion map. For every entry in the map's `demoted[]`, take the STALE row at that `row_index` out of its `$SP_SEVERITY` finding bucket and render it under Informational with the exact annotation `previously adjudicated false positive (run <run-key>)` (using the entry's `run_key`), carrying its TSV row as evidence. A demoted row is excluded from Phase 4.2 verdict computation at every configured `stale_prose.severity`, including `critical`. A STALE row not in `demoted[]` stays a finding at `$SP_SEVERITY`, as routed above. The join is PR-scoped (it reads only this PR's own comments), so an adjudication never crosses PRs.
4b. Surface the helper's refusal counters. The helper accounts for everything it *declined* to honor (`payloads_untrusted`, `payloads_malformed`, `payloads_outside_sentinels`, `sentinel_tampered_comments`, `comments_malformed`, `rows_malformed`, `rows_rule_excluded`, `collisions`). Reading only `demoted[]` and discarding `stats` would let the channel be corrupt, forged, or permanently inert while the run reports a clean pass, so render an `## Adjudication carry-forward` note whenever any counter is non-zero, naming each non-zero counter and what it means, and in particular:
   - `sentinel_tampered_comments > 0` — a trusted comment carried more than one adjudications-section sentinel: a *suspected forged or quoted section*, the one observable signature of an attack on the trust channel. It fails closed (no payload from it is honored) and is surfaced as a visible warning in the report body, not a runner log.
   - `collisions > 0` — a prior adjudication matched two or more current STALE rows, so none was demoted (ambiguity never demotes). Say so.
   - `payloads_untrusted > 0` with `payloads_honored == 0` — every payload was refused for want of trust. Name the untrusted author login and the remedy (add it to `.prflow.allowed_bots`). This is the expected shape on a local/standalone PR-mode run, where the progress comment is authored by the human's own `gh` token (`author_type: User`) rather than a `Bot`.
   - `rows_rule_excluded > 0` — a STALE row of a rule not carry-forward-eligible (today `R4`, whose detail carries no referent — see the helper's *Match key* contract) stayed a finding at `$SP_SEVERITY`. Never demoted.

5. Loud degradation (the helper is absent, harness-refused, or errors). Leave **every** STALE row at its configured `$SP_SEVERITY` and record a degraded-check note naming the failure — a helper `No such file`, a harness refusal (name the missing `Bash(.prflow/vendor/prflow/scripts/match-lint-adjudications.py:*)` grant and the tier-appropriate remedy, exactly as arm (a) below), or a non-zero exit carrying its stderr. Never a silent skip, never a suppressed row. (The helper always exits 0 when it ran, even on malformed payloads, so a non-zero exit here means it could not run or rejected its input — it exits 2 on unusable stdin, per its Exit-codes contract.)

Degradation arms (fail-safe, never fail-silent — the run proceeds in every arm, the note visible in the review report):

- (a) Harness-refused invocation — the command never executes. Record a degraded-check note that must name the missing grant and the tier-appropriate remedy: for the cloud review runner, re-syncing the installed workflow's `TOOLS='…'` line — `prflow_runner.allowed_tools` is appended to the review profile *post-floor* but only inside the cloud review runner workflow's `prflow_runner.provision_env` gate, and `provision_env` defaults to `false`, so on a default read-only reviewer tracked config alone does **not** bridge the grant (name it as a remedy only for a consumer already running `provision_env: true`); and `prflow_implement.allowed_tools` / `prflow.allowed_tools` for the implement / command tiers.
- (b) Helper absent (`No such file`) — record a degraded-check note that the vendored stale-prose-lint.py was not found at its expected path.
- (c) Helper internal error (exit 2) — record a degraded-check note that the helper reported an internal error (exit 2) and carry its stderr.
- (d) Config-disabled — the explicit config-disabled note recorded at the config gate above.

No arm stalls the run or silently skips the phase.
<!-- prflow:review-ref phase=0.6 file=skills/review/phases/phase-0-6-stale-prose-lint.md end -->
