<!-- prflow:review-ref phase=4.4 file=skills/review/phases/phase-4-4-github-post.md start -->
### 4.4 Record the verdict as a formal GitHub review (PR mode only)

**If — and only if — `$PR_NUMBER` is a PR number** (an actual PR, not the current branch), you MUST also submit the verdict as a formal GitHub Pull Request review.

**This gate, and every `gh` invocation in this phase, reads `$PR_NUMBER` — the PR number the skill root parsed out of `$ARGUMENTS` — and never the raw `$ARGUMENTS` string.**

Post the verdict through the bundled helper `post-review-verdict.sh`. You hand it the verdict token; it chooses the review channel, composes the machine-readable verdict marker, and stamps that marker on every durable surface it writes. You compose no marker of your own — not in the review body, not in the progress comment, not anywhere — because a verdict whose identity is prose an agent wrote is missed by the merge-gate consumers that scan for a marker shape. What goes in the review body depends on whether a progress comment already carries the full report — set `$BODY` accordingly. The discriminator is did the skill author the live progress comment this run (`$WP` set)? — NOT `$GITHUB_ACTIONS`. `$WP` is the single authoritative signal.

- A progress comment carries the report — true when the skill authored the live progress comment this run (PR mode AND `prflow_review.live_progress_comment_enabled` AND the Phase 0.3.5 seed succeeded, i.e. `$WP` is set), cloud or local alike. The full Phase 4.1 report already lives in that comment, so the review body is a short verdict-only stub. Set `$BODY` to `$STUB`:

  ```
  ## Verdict: {VERDICT} — full report in PR comment

  > The complete review report (checklist results, findings, details) is in the
  > PRFlow Review progress comment on this PR.
  ```

- No progress comment exists — `$WP` is unset: the live comment is off (`live_progress_comment_enabled` false), its seed failed, or this is current-branch/non-PR mode. Set `$BODY` to the full `$REPORT` from Phase 4.1. (Its own `## Verdict: {VERDICT}` line stays where it is; the helper prepends the producer marker above it, so a standalone REJECT is selected by `dismiss-stale-rejections.sh` on the marker and cleared by a later APPROVE.)

where `{VERDICT}` is the actual verdict line (e.g. `APPROVE`, `APPROVE with notes`, `APPROVE WITH CAVEAT`, `REJECT`) — reflect what Phase 4.2 decided, do not template-fill literally. The `## Verdict: {VERDICT}` line remains the transitional human-readable verdict line; the machine-readable identity is the marker the helper stamps, not this line.

The verdict token you pass the helper is the Phase 4.2 verdict line itself. The helper — not you — maps it to a review event and to the marker's normalized two-token verdict:

| Verdict token you pass | Review event the helper selects | `verdict=` it stamps |
|---|---|---|
| **REJECT** (any form) | `REQUEST_CHANGES` | `REJECT` |
| **APPROVE** (clean, no findings) | `APPROVE` | `APPROVE` |
| **APPROVE with notes** / **APPROVE WITH CAVEAT** / **APPROVE WITH ADVISORY NOTES** (any other approve-family token) | `COMMENT` | `APPROVE` |

A REJECT driven by the Phase 4.2 self-contradicting-diff carve-out is a REJECT (any form) like any other — no separate branch for it. A token outside that set is refused with `SKIP unknown-event` and no request is issued, so pass the verdict line verbatim rather than inventing a spelling.

Write `$BODY` to a file, then post it through the helper. The helper takes the body as a file path (not an inline string), so a report containing backticks, `$(`, or literal double quotes reaches the API unmangled. Write `$BODY` to `.prflow/tmp/review-verdict-body.md` with the **Write tool** (not a shell redirect), then invoke the helper as a single leading-token statement at the repo-relative vendored literal, with every other value in argument position — no leading `cd`, no `VAR=value` prefix, and no unexpanded skill-directory anchor placeholder as the leading token:

```bash
.prflow/vendor/prflow/scripts/post-review-verdict.sh "$PR_NUMBER" "REJECT" .prflow/tmp/review-verdict-body.md "$PR_HEAD_SHA" "$MARKER"
```

The five arguments, in order:

1. `"$PR_NUMBER"` — never `"$ARGUMENTS"`.
2. the verdict token — substitute the Phase 4.2 verdict line for the `REJECT` token above, quoted.
3. the body-file path.
4. `"$PR_HEAD_SHA"` — the reviewed head from Phase 0.2, the same SHA Phase 4.3 writes into the progress comment's `Reviewed HEAD` line. It must be the full 40-character object name; an abbreviated or empty value is refused with `SKIP head-not-sha` and no request is issued.
5. `"$MARKER"` — the run-keyed progress-comment marker literal Phase 0.3.5 established, so the helper stamps the same verdict marker there too. When `$WP` is unset (no live progress comment this run) pass the empty literal `""`; the helper reports `PROGRESS not-requested` and posts the review exactly as it otherwise would.

One invocation procedure, tier-agnostic — never classify your own tier. The command above is the granted form on every tier: emit the vendored literal as the leading token first, cloud and local alike. Then read the *observable result of that first attempt* to decide whether a second is needed — never a judgement about which tier the run is on:

- It produced an outcome line (`POSTED …` / `FAILED …` / `SKIP …`), or no output at all — the helper resolved, or the harness refused it. Route on that result per the outcome vocabulary below; do not re-invoke at another path (a silent no-output reading is a harness refusal, which the vocabulary's *No output at all* arm already handles — it is never a not-found).
- It reported the file was not found — a `command not found` / `No such file` / exit 127 reading, which is distinct from the silent no-output of a harness refusal. Re-invoke the same helper with the `.prflow/vendor/prflow/` prefix removed (its repo-root path) as a single leading-token statement, then route on *that* invocation's outcome line.

Read the helper's FIRST stdout line — the outcome line — and route on it. The vocabulary is closed, names the durable channel that received the verdict, and has no silent path:

- `POSTED review <event>` (exit 0) — the formal review exists and its body's line 1 is the producer marker. Post no fallback comment; the `$BODY` stub-versus-full-report selection above stands unchanged. Tick the final Blueprint row in the progress comment — when `$WP` is unset there is no comment to tick and the engine root's *No progress comment for this run* fallback governs instead, which is the guard every tick clause in this phase inherits.
- `POSTED comment <event>` (exit 0) — the review POST was refused and the helper posted the same marker-stamped body to the pull request's comment thread instead. The verdict is durably recorded and machine-readable there, but the reviews API and `reviewDecision` are unchanged, so the merge signal is not present. Post no second comment — the helper already posted this one. Report in chat output that the formal review could not be posted, that the verdict reached the comment channel, and that the PR carries no `--request-changes`/`--approve` signal for it. Tick the final Blueprint row — the tick asserts the durable marked verdict this arm recorded, not the merge signal it just reported absent.
- `FAILED no-durable-channel <error>` (exit 1) — both channels were issued and refused, so no durable artifact carries this verdict; `<error>` names each captured cause on one line. Take the fallback arm below, recording that line. Leave the final Blueprint row unticked.
- `SKIP <reason>` (exit 3) — the helper declined to issue any request (`not-numeric` / `unknown-event` / `head-not-sha` / `body-file-unreadable`). Take the same fallback arm below, recording the skip reason in place of an error line. Every one of those reasons is an argument you supplied, so name the offending argument in what you record. Leave the final Blueprint row unticked.
- `SKIP evidence-missing` (exit 3) — the helper graded the run root and its execution evidence did not pass, so no request was issued; this reason has its own recovery arm and does NOT take the generic fallback above. **First occurrence this run:** re-enter Phase 2 once — re-run checklist verification so its durable artifacts and per-item nonce verifier files are produced — then continue through Phase 3 and Phases 4.1–4.3 before retrying this publication step, recording a durable one-shot marker (a progress/workpad note) so a second `SKIP evidence-missing` on the retried post routes to the terminal arm here. If a prerequisite for that recovery is missing, stop the recovery and report it rather than proceeding, so the run never publishes as though evidence passed. **Second occurrence (recovery already used):** end the run at ❌ with no verdict, taking neither the plain-comment fallback below nor the APPROVE dismissal step, because either would publish or clear a merge signal for a run whose evidence never passed. Leave the final Blueprint row unticked.
- No output at all — the harness/permission matcher refused the invocation before it ran. Read the silence as route to the fallback arm — never as authorization to treat the review as posted. Record the cause as `the review-post helper produced no output (harness refusal)`. Leave the final Blueprint row unticked.

The helper's SECOND stdout line reports the progress-comment stamp and never changes the routing above. `PROGRESS stamped <comment-id>` (the marker is now on the line after that comment's run key), `PROGRESS not-requested`, `PROGRESS not-found`, or `PROGRESS failed <error>`. Record a non-`stamped` reading in chat output — the review artifact is authoritative, so a failed secondary stamp is a diagnostic, not a verdict change — and do not retry it or hand-write the marker into the comment yourself.

Fallback arm (`FAILED no-durable-channel`, any `SKIP` except a repeated `evidence-missing`, or silence — a repeated `evidence-missing` took its terminal arm above and reaches nothing here). Post the full `$REPORT` (not `$STUB`) as a plain comment with `gh pr comment $PR_NUMBER --body-file <file>`, where the file's body opens with a failure record stating, at minimum: that the formal review post could not be posted; the helper's captured error line (or the skip reason / harness-refusal note); the verdict that was reached; and the sentence *"This comment is not read as a verdict by the verdict-derivation consumers (`reviewDecision` and the reviews API are unchanged); it is a human-readable record only."* Compose the file with the Write tool, prepending that failure record above the `$REPORT` body, then pass its path. Do not compose a verdict marker into it — a marker this arm wrote would assert a producer guarantee that did not hold, which is exactly the confusion this removes. Never silently skip this step on a REJECT. A failed post never downgrades the verdict — it stands; only the durable GitHub artifact changed shape.

Then, on any APPROVE form only (APPROVE / APPROVE with notes / APPROVE WITH CAVEAT), clear a stale REJECT — and run this dismissal REGARDLESS of the post outcome above (`POSTED review`, `POSTED comment`, `FAILED no-durable-channel`, a `SKIP …` other than a repeated `evidence-missing`, or silence) — a repeated `evidence-missing` ended the run with no verdict above, so this dismissal does not run for it, else it would clear a merge signal for a run whose evidence never passed. The script dismisses only PRFlow Review's own reports (body marker), never a human's `--request-changes`. On REJECT, skip this — the changes-request must stand. Run (re-run safe):

```bash
.prflow/vendor/prflow/scripts/dismiss-stale-rejections.sh "$PR_NUMBER"
```

Pass `"$PR_NUMBER"` here, never `"$ARGUMENTS"`. (The same tier-agnostic invocation procedure as the verdict post applies here: emit the vendored literal first, and only on a not-found / rc-127 reading of that attempt re-invoke the same helper with the `.prflow/vendor/prflow/` prefix removed — never on a tier judgement.)

Record the dismissal's exit code. On a `POSTED review` APPROVE, a non-zero exit is reported in chat output (token scope) and that the PR stays blocked until dismissed manually. On a `FAILED no-durable-channel` / `SKIP …` / silent APPROVE, the dismissal ran with no formal review at all, so write its outcome into the fallback comment's failure record (dismissed / non-zero exit and cause). On a `POSTED comment` APPROVE the helper already posted the only durable artifact and you add no second comment, so report the dismissal outcome in chat output alongside the failed-review-post note. A dismissal failure never downgrades the verdict — it stands; only merge-gate housekeeping failed.

The dismissal's own exit codes are unchanged: `0` cleared or nothing outstanding, `1` a query or a dismissal failed, `3` a candidate was left outstanding because it could not be shown superseded. It may also emit a `NOTE:` on stderr counting outstanding `CHANGES_REQUESTED` reviews it did not select. That count is not a failure — a human reviewer's block belongs there — but a PRFlow verdict landing there means a post did not stamp its marker, so surface the note rather than discarding it.
<!-- prflow:review-ref phase=4.4 file=skills/review/phases/phase-4-4-github-post.md end -->
