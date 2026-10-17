<!-- prflow:review-ref phase=4.4 file=skills/review/phases/phase-4-4-github-post.md start -->
### 4.4 Record the verdict as a formal GitHub review (PR mode only)

Only `post-review-verdict.sh` posts the verdict; compose no verdict marker. When `$WP` is set and the latest Phase 4 comment write succeeded, pass that comment's body `.prflow/tmp/review/<slug>/<run-id>/review-wp.md` as `<body-file>` (the helper posts a short stub instead when it finds the progress comment); otherwise Write the full Phase 4.1 report to `.prflow/tmp/review/<slug>/<run-id>/verdict-body.md` with the Write tool and pass that, running `rm -f` on that path when the Write is refused or fails so no earlier report is posted. Then run:

```bash
.prflow/vendor/prflow/scripts/post-review-verdict.sh "$PR_NUMBER" "REJECT" <body-file> "$PR_HEAD_SHA" "$MARKER" .prflow/tmp/review/<slug>/<run-id>
```

Substitute literals: the PR number for `$PR_NUMBER`, the Phase 4.2 verdict (the words after `## Verdict: `, before the parenthetical) for `REJECT`, the full 40-character reviewed head for `$PR_HEAD_SHA`, and Phase 0.3.5's marker for `$MARKER` (`""` with the report file). Route on the first stdout line:

- `POSTED review <event>` or `POSTED comment <event>` → done. `POSTED comment` means the formal review was refused and the verdict reached the comment thread without a merge signal: say so in chat. Report in chat a `PROGRESS` line other than `PROGRESS stamped …` or `PROGRESS not-requested`, after an approve-family verdict a `DISMISS` line that is missing or not `DISMISS 0`, and a stderr line starting `NOTE:`; none changes the verdict.
- Anything else, or no output → the verdict was not posted.
  - `SKIP evidence-missing`: its stderr grade names what this run lacks.
    - `fail missing=` naming any `checklist-fail-at-threshold:<id>` token: the verdict breaks rule 1. Make the verdict REJECT, driven by those ids; rewrite the report, and with `$WP` set the progress comment per Phase 4; present it per 4.3, then retry this step once.
    - Any other grade, or none: end with no verdict, naming it.
  - A `SKIP` naming an argument you supplied: fix it and retry once; a second such `SKIP` takes the next arm.
  - Anything else: report the line, or the silence, in chat; with `$WP` set, patch the progress comment's `Status` to `❌ <verdict> not posted — <the line, or "no output">`.
<!-- prflow:review-ref phase=4.4 file=skills/review/phases/phase-4-4-github-post.md end -->
