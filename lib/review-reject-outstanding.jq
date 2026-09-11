# review-reject-outstanding.jq — the outstanding-rejection derivation.
#
# fetch-pr-context.sh loads this filter to derive `signals.review_reject_outstanding`
# from the `review_verdicts` array that review-verdict-union.jq emits. It runs over
# that array (the `.verdicts` the union filter produced), never over raw GitHub payloads.
#
# Invocation (the verdicts array on stdin):
#   echo "$REVIEW_VERDICTS" | jq -f lib/review-reject-outstanding.jq
#
# Input: an array of {verdict, createdAt, source}. Output: true when the
# chronologically-last TIMESTAMPED entry is a REJECT, OR when any TIMESTAMP-LESS entry
# is a REJECT (the one-directional rule). review_verdicts already places the sorted
# timestamped partition first, so its last timestamped element is the chronologically-last
# verdict.
    ( map(select(.createdAt != "")) ) as $ts
    | ( map(select(.createdAt == "")) ) as $nots
    | ((($ts | length) > 0) and ($ts[-1].verdict == "REJECT")) or ($nots | any(.verdict == "REJECT"))
