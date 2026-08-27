# classify-pr-kind.jq — retrospection-kind dispatcher for the devflow retrospective.
#
# fetch-pr-context.sh consults this filter to decide which retro variant
# (if any) applies to a freshly-merged PR, and stores the result as `.kind`
# in the context bundle.
#
# Invocation (named args, no stdin needed):
#   jq -rn --arg branch "claude/issue-773-..." --argjson watched true \
#     --arg impl_prefix "claude/" --argjson labels '[]' --argjson closing '[]' \
#     -f lib/classify-pr-kind.jq
#
# $impl_prefix is the adopter's implementation-bot branch prefix
# (prflow_retrospective.implementation_branch_prefix, default "claude/").
# The devflow/* prefixes below are PRFlow's own internal branch conventions
# and are intentionally fixed.
#
# This filter MIRRORS lib/scan.sh's union retrospection predicate so a PR that
# scan SELECTS is not then dropped here: a DevFlow-labelled PR, or a
# watched-author PR that closes an issue, classifies as "implementation" even
# when its branch matches no prefix — PRFlow's own branches are
# issue-<N>-<slug>, which match neither "claude/" nor "devflow/learnings-". An
# EMPTY $impl_prefix disables the prefix arm; it must NOT startswith-match every
# branch (the match-all bug scan.sh also guards). $labels entries may be objects
# ({name}) or bare strings; each input array defaults so a missing arg never
# aborts the filter.
#
# Output: a single string — one of:
#   "implementation"      -- run the full per-PR retrospective
#   "skip"                -- not a retrospected branch (state-carrier or unrelated)

(($labels // []) | map(if type == "object" then (.name // "") else . end) | any(. == "PRFlow" or . == "DevFlow")) as $has_devflow_label
| ((($closing // []) | length) > 0) as $closes_issue
| if   ($branch | startswith("devflow/learnings-"))                  then "skip"
  elif (($impl_prefix != "") and ($branch | startswith($impl_prefix))) then (if $watched then "implementation" else "skip" end)
  elif $has_devflow_label                                            then "implementation"
  elif ($watched and $closes_issue)                                  then "implementation"
  else "skip"
  end
