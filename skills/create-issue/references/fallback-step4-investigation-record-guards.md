<!-- prflow:create-issue-ref step=fallback-step4-investigation-record-guards file=skills/create-issue/references/fallback-step4-investigation-record-guards.md start -->

     Bound the assembled record's size before posting. GitHub refuses a comment body over 65,536 characters; enforce that conservatively over UTF-8 bytes, the same measure `scripts/workpad.py` applies to the same platform limit (a string's byte length is never below its character count). Measure the written record file's byte length with Python `len()` over its UTF-8-encoded bytes:

     ```bash
     python3 -c 'import sys; print(len(open(sys.argv[1],"rb").read()))' "<record-file>"
     ```

     When that count exceeds 65536, truncate the folded blocks — the criterion disposition record, the steelman record, and the evidence bundle, largest first, never the line-1 marker — re-measuring after each cut until the body fits, name each truncated block inside the posted comment, and re-write the file so the neutralization check below runs over the truncated bytes. If the count cannot be established at all (no readable output from the measurement — a refusal, or python3 unavailable), fail closed a different way, since "truncate until it fits" needs the measurement that just failed: omit the folded decision blocks entirely so the posted body is the small base record bucket, which cannot exceed the limit, and name in the final reported outcome that the blocks were omitted because the comment size could not be measured. Either arm keeps the record postable rather than losing it to a refused over-limit POST followed by the 5d cleanup.

     Verify neutralization mechanically before posting — do not trust the hand-rewrite alone. After writing the file, run this one status-preserving check:

     ```bash
     if grep -nE '/(pr|dev)flow:|@claude' "<record-file>"; then
       neutralization_grep_status=0
     else
       neutralization_grep_status=$?
     fi
     printf 'neutralization_grep_status=%s\n' "$neutralization_grep_status"
     ```

     Read the final status line together with any match lines. First require exactly one final result line matching `neutralization_grep_status=<decimal integer>` with no extra text. Zero result lines, multiple result lines, a non-decimal value, or trailing text are all `neutralization grep harness refusal`: withhold the post and report that refusal. Only a valid result line reaches status routing. Status `0` plus its match lines means triggers survive: do not post, re-neutralize those exact occurrences, and re-run the fence. Status `1` is the only clean no-match result and permits posting. Status `2` or greater is a grep failure: withhold the post and report it. The line-1 marker `<!-- prflow:investigation-record -->` is safe — it carries no leading `/` and no `@`. If surviving triggers cannot be made clean, withhold the post and name them in the final outcome.

<!-- prflow:create-issue-ref step=fallback-step4-investigation-record-guards file=skills/create-issue/references/fallback-step4-investigation-record-guards.md end -->
