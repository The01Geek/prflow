# review-verdict-union.jq — the review-verdict union filter.
#
# fetch-pr-context.sh loads this filter to build the UNION of a PR's conversation
# comments and its durable bot PR reviews into the verdict bundle it emits as
# `.review_verdicts` / `.review_verdict_unparsed_count`. It defines `verdicts_in`
# (the marker-first / heading-grammar / rung-3-fallback dispatcher) and its helpers.
#
# Invocation (comments on stdin, reviews via --slurpfile — never --argjson, so
# neither large GitHub payload reaches jq as an argv string; lint-argjson-transport.py
# enforces this):
#   printf '%s' "$PR_REVIEWS_RAW" > reviews.json
#   echo "$PR_COMMENTS_RAW" | jq --slurpfile reviews reviews.json -f lib/review-verdict-union.jq
#
# Input: stdin is the comments array; $reviews[0] is the reviews array. Output:
# {verdicts: [{verdict, createdAt, source}...], unparsed: <count>}. The array guards
# and empty-document handling are a fail-closed floor no producer-driven test can
# drive (the producer normalizes both payloads to arrays upstream); the focused test
# lib/test/test_review_verdict_units.py drives them directly.
    # Deliberately wider than rung 3 on the axes that matter — unmasked, a bare
    # substring, case-insensitive. Narrowing any axis onto rung 3 makes an artifact
    # rung 3 declined vanish from the count as well as the union, recreating the
    # two-meanings collapse the count exists to end.
    def token_in_window($lines):
        any($lines[0:30][]; test("APPROVE|REJECT"; "i"));
    # Drop every line rung 3 must not read a verdict from: an HTML-comment region (opening
    # line, continuations and close alike), a fenced block, a blockquote, and an indented
    # code block. A fence closes only on its own marker, so a tilde line cannot close a
    # backtick block and leave the rest of the window readable.
    # Returns a POSITIONAL mask — one entry per window line, the line itself or null —
    # never a compacted list. Compacting closes the gap between a heading and a later
    # token, so a stripped block would make a distant token read as the adjacent one.
    # Every branch below appends exactly one entry, or the mask stops lining up with the
    # lines it masks and a verdict is read from the wrong one; rung3 checks that length.
    # Dropped: HTML-comment regions, fenced blocks, blockquotes, indented code, list items,
    # table rows and strikethrough — every construct that marks a line as quoting.
    def rung3_mask($lines):
        (reduce ($lines[0:30][]) as $l ({comment: false, fence: null, out: []};
            if .comment then
                ((if ($l | test("-->")) then .comment = false else . end) | .out += [null])
            elif .fence != null then
                (.fence as $f
                 | (if ($l | test("^[ \t]*" + $f)) then .fence = null else . end)
                 | .out += [null])
            elif ($l | test("^[ \t]*```")) then (.fence = "```" | .out += [null])
            elif ($l | test("^[ \t]*~~~")) then (.fence = "~~~" | .out += [null])
            elif ($l | test("<!--")) then
                ((if ($l | test("-->")) then . else .comment = true end) | .out += [null])
            elif ($l | test("^[ \t]*>")) then .out += [null]
            elif ($l | test("^(\t| {4,})")) then .out += [null]
            elif ($l | test("^ {0,3}([-*+]|[0-9]+[.)])[ \t]")) then .out += [null]
            elif ($l | test("\\|")) then .out += [null]
            elif ($l | test("~~")) then .out += [null]
            else .out += [$l] end))
        | .out;
    # An allow-list of decoration glyphs, never a block range and never all of non-ASCII:
    # the dingbat and emoji planes also hold the bullet, ballot-box, heavy-quotation,
    # speech-bubble and pointer glyphs that mark a line as a recap QUOTING a verdict.
    def emoji: "[\\x{2705}\\x{274C}\\x{26A0}\\x{1F534}\\x{1F7E0}-\\x{1F7E2}\\x{FE0F}\\x{200D}]";
    def headline_prefix: "^(?:[ \t#*_]|" + emoji + ")*";
    # Letters in ANY script, so trailing prose in a non-Latin script is prose here too.
    def not_letters: "[^\\p{L}]";
    def rung3($lines; $login):
        if ((($login | strings) // "") | endswith("[bot]")) then
          rung3_mask($lines) as $m
          | if ($m | length) != ($lines[0:30] | length) then [] else
          ([ $m[] | select(. != null) ]) as $w
          # Every sub-rung reads its token from its OWN whole-line capture, anchored at both
          # ends. A guard that only anchors the prefix, or that re-derives the token with a
          # second pattern, admits the trailing prose an artifact quotes a prior verdict in.
          | ([ $w[]
               | capture(headline_prefix + "(?i:Verdict):" + not_letters + "*(?<v>APPROVE|REJECT)" + not_letters + "*$")
               | .v ]) as $r1
          | if ($r1 | length) > 0 then $r1[0:1]
            elif any($w[]; test(headline_prefix + "(?i:Verdict):")) then []
            else
              # Letters may appear only in one optional leading word, the anchor word, and
              # the token — collapsing punctuation away instead lets an ordinary sentence
              # ("Do not review. REJECT.") wear the headline shape. The token stays
              # case-SENSITIVE so lowercase prose cannot satisfy it.
              # The window is the first three non-blank lines BY POSITION, each kept only if
              # it survived stripping: a stripped line is skipped, never backfilled from
              # later in the body.
              ([ range(0; $m | length) | select($lines[.] | test("[^ \t]")) ][0:3]
               | map(select($m[.] != null))
               | map($m[.])
               | map(capture(headline_prefix + "(\\p{L}+" + not_letters + "+)?(?i:Review|Verdict)" + not_letters + "+(?<v>APPROVE|REJECT)" + not_letters + "*$"))
               | map(.v)) as $r2
              | if ($r2 | length) == 1 then $r2
                else
                  # The next non-blank line is found in the RAW body, and a stripped one is
                  # a hard stop: the line adjacent to the heading is what decides.
                  ([ range(0; $m | length) as $i
                     | select($m[$i] != null)
                     | select(($m[$i] | test("^#{1,6}[ \t]"))
                              and (($m[$i] | gsub("[^A-Za-z]"; "") | ascii_downcase) == "verdict"))
                     | ([ range($i + 1; $m | length) | select($lines[.] | test("[^ \t]")) ][0]) as $j
                     | select($j != null)
                     | select($m[$j] != null)
                     | ($m[$j] | capture(headline_prefix + "(?<v>APPROVE|REJECT)" + not_letters + "*$"))
                     | .v ]) as $r3
                  | $r3[0:1]
                end
            end
          end
        else [] end;
    def verdicts_in($body; $login):
        (($body | strings) | split("\n") | map(rtrimstr("\r"))) as $lines
        | ([ $lines[0:2][]
             | select(test("^<!-- prflow:review-verdict head=[0-9a-fA-F]{40} verdict=(APPROVE|REJECT) -->$"))
             | capture("verdict=(?<verdict>APPROVE|REJECT)")
             | .verdict ]) as $marked
        | (if ($marked | length) == 1 then $marked
           else ([ $lines[]
                   | select(test("^#{1,6}[ \t]*(/review[ \t]*[—–-]+[ \t]*)?Verdict:[ \t]*\\**[ \t]*(APPROVE|REJECT)"; "i"))
                   | capture("Verdict:[ \t]*\\**[ \t]*(?<verdict>APPROVE|REJECT)"; "i")
                   | (.verdict | ascii_upcase) ]) as $grammar
                | (if ($grammar | length) > 0 then $grammar else rung3($lines; $login) end)
           end)
        | .[];
    # Per-artifact scan record: the verdicts it yielded, and whether it is an
    # artifact that yielded none yet visibly carries a token (the residual count).
    def scanned($arts; $tskey; $src):
        [ $arts[]
          | select(type == "object")
          | . as $a
          | ($a.user | if type == "object" then .login else null end) as $login
          | ((($a.body | strings) // "") | split("\n") | map(rtrimstr("\r"))) as $lines
          | ([ verdicts_in($a.body; $login) ]) as $vs
          | { vs: $vs,
              unparsed: ((($vs | length) == 0) and token_in_window($lines)),
              createdAt: (($a[$tskey]) // ""),
              source: $src } ];
    # Guard both payloads to arrays before iterating: a non-array comments payload
    # (stdin `.`) or a non-array reviews payload ($reviews[0]) would otherwise abort
    # the whole filter on `.[]` (external structured format — fail closed to empty).
    # Defense-in-depth: both payloads are already normalized to arrays upstream by
    # the sections-7/8 jq add-or-empty slurp, so this guard is not reachable via the
    # producer path (no producer-driven test can drive it); it is kept as a
    # fail-closed floor in case that normalization ever changes or the filter is
    # reused directly.
    (if type == "array" then . else [] end) as $comments
    | (if ($reviews[0] | type) == "array" then $reviews[0] else [] end) as $reviews_arr
    | (
        scanned($comments; "created_at"; "pr_comment")
        +
        scanned([ $reviews_arr[] | objects | select(.state != "PENDING") ]; "submitted_at"; "pr_review")
      ) as $records
    | { verdicts:
          ( [ $records[] | . as $rec | $rec.vs[] | {verdict: ., createdAt: $rec.createdAt, source: $rec.source} ]
            | to_entries | map(.value + {index: .key})
            | ( map(select(.createdAt != "")) | sort_by(.createdAt, (.source == "pr_review"), .index) ) as $ts
            | ( map(select(.createdAt == "")) ) as $nots
            | ($ts + $nots)
            | map({verdict, createdAt, source}) ),
        unparsed: ([ $records[] | select(.unparsed) ] | length) }
