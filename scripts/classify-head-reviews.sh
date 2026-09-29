#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# classify-head-reviews.sh PAYLOAD HEAD_SHA REVIEWER_LOGIN — reduce a reviews-API
# payload to ONE line from a closed four-token vocabulary (issue #1250).
#
# THE QUESTION IT ANSWERS. `Bash(gh api:*)` is granted in every capability profile,
# so a cloud run that cannot reach scripts/post-review-verdict.sh can still POST a
# real, merge-blocking pull-request review by calling the reviews endpoint directly —
# a review GitHub records (it sets `reviewDecision`) but which carries NO
# producer-emitted `prflow:review-verdict` marker, so none of PRFlow's
# verdict-derivation consumers read it as a verdict (run 30860699039 / review
# 4849248513). scripts/post-review-verdict.sh is therefore NOT the sole granted post
# path, only the sole MARKING one. This helper looks at the reviews actually recorded
# on the reviewed head and reports whether the run's own reviewer identity left a
# marked review, an UNMARKED one (the bypass), none at all, or a shape it could not
# settle — so the Phase 4.4 reach record (scripts/describe-verdict-post-gap.sh,
# rendered by the devflow.yml reach-record step) can stop asserting the reviews API
# was untouched when it was not.
#
# CONTRACT — exactly one stdout line, always exit 0:
#
#   none                    no own-identity review is recorded against HEAD_SHA, AND every
#                           own-identity review that exists was POSITIVELY placed on some
#                           other tree (an empty list, a review by another login, or an
#                           own review whose verdict marker names a different head all
#                           resolve here)
#   marked                  every own-identity review on the head carries the producer
#                           marker on its FIRST line
#   unmarked <id> [<id>…]   at least one own-identity review on the head carries no
#                           marker on line 1; the ids are the unmarked reviews', sorted
#                           ascending, space-separated on the one line
#   unestablished <reason>  the question could not be settled; <reason> is one closed
#                           token from the list below
#
# WHICH KEY PLACES A REVIEW ON THE HEAD (issue #1247, the precedence PR #1255 established
# for dismiss-stale-rejections.sh). GitHub can change a review's reviews-API `commit_id`
# AFTER submission — observed on pull request #1234, where a review's `commit_id` was
# advanced to a head committed 35 minutes later — so `commit_id` is NOT an authoritative
# record of the reviewed tree. The verdict marker's `head=`, stamped by
# scripts/post-review-verdict.sh at review time and never rewritten (issue #1030), IS. So
# each own-identity review is placed by:
#
#   marker head present .. AUTHORITATIVE. Equal to HEAD_SHA -> on the head (and `marked`,
#                          since the line-1 marker is exactly what makes it marked);
#                          different -> positively OFF the head.
#   marker absent ........ `commit_id` is the only key there is, and it is NOT
#                          authoritative. Equal to HEAD_SHA -> on the head (and `unmarked`,
#                          the bypass shape). Different, or absent -> the review CANNOT be
#                          positively placed off the head, so it is INDETERMINATE.
#
# `none` is the ONE arm the caller renders as "this run left the reviews API and
# `reviewDecision` untouched", so it is the one arm an indeterminate review must block: a
# run that posted an unmarked bypass review and then saw the head advance before this
# classification leaves exactly that shape behind, and grading it `none` would re-emit the
# categorical false statement issue #1250 exists to remove. It grades
# `unestablished review-placement-unprovable` instead — CLAUDE.md's "unknown is not zero".
# DISCLOSED RESIDUAL: an indeterminate review does NOT displace `unmarked` or `marked`,
# which assert that something EXISTS rather than that nothing does and so cannot be
# falsified by a review this helper could not place. On those two arms an unplaceable
# own-identity review goes unmentioned.
#
# Always exit 0 because the only caller is an `always()` post-run workflow step that
# must never change its job's pass and never change its fail.
#
# UNKNOWN IS NOT ZERO. A payload that cannot be parsed, a head SHA that is absent, a
# reviewer login that is absent, an own-identity review whose `body` is not a string, or an
# own-identity review this helper cannot positively place off the head
# are each UNESTABLISHED — never `none`. Collapsing any of them onto `none` would let
# the reach record assert "the reviews API is untouched" about a run it never actually
# measured, which is CLAUDE.md's "unknown is not zero" rule (the named prior instance is
# `permission_denials_count` publishing `0` for a run it never measured). The
# MARKER-ON-LINE-1 rule is deliberately strict: scripts/post-review-verdict.sh stamps the
# marker as line 1 of a review body, so a marker a finding quotes deeper in the body must
# NOT read as a stamp — a review with the marker on line 2 is `unmarked`, not `marked`.
#
# REASON VOCABULARY (closed; every arm emits one of these and nothing else):
#
#   head-sha-absent          HEAD_SHA was empty
#   reviewer-login-absent    REVIEWER_LOGIN was empty
#   payload-unreadable       the payload path is not a readable file
#   marker-module-unavailable the shared marker grammar is absent or unreadable
#   payload-unparseable      jq could not compile or process the payload
#   payload-not-an-array     the payload parsed but its top level is not an array
#   body-not-a-string        an own-identity review has a non-string body (every own review
#                            is body-read to place it, so this is not head-scoped)
#   review-placement-unprovable
#                            no own-identity review is placed on the head, but at least one
#                            markerless own-identity review could not be placed OFF it
#                            either (its only key is the non-authoritative `commit_id`)
#   classify-failed          the classifier produced no line at all
#
# The reasons are CLOSED TOKENS and never quote the payload's bytes. The caller renders
# the token into a `::warning::` and a pull-request comment; a reason that embedded
# payload bytes would carry whatever the review body contained onto those surfaces —
# including a `::warning::`/`##[…]` workflow command. Naming the SHAPE keeps every
# emitted surface free of payload-derived bytes. The one payload-derived value that DOES
# reach stdout — the review ids on the `unmarked` line — is produced by jq's `tostring`
# over the numeric `.id` field, so it is digits only by construction.
#
# Every selection value is derived through jq (a preflight-guaranteed tool) and bash
# builtins (`[`, `case`, parameter expansion) — never `tr`/`sed`/`wc`/`cut`/`head`,
# which lib/preflight.sh does not guarantee: a missing one yields an empty value and
# selects the wrong arm (CLAUDE.md guard-class 2).
#
# Usage: classify-head-reviews.sh PAYLOAD HEAD_SHA REVIEWER_LOGIN
#   PAYLOAD         path to a reviews-API JSON array, or `-` to read it from stdin.
#   HEAD_SHA        the reviewed head SHA the reviews are scoped to.
#   REVIEWER_LOGIN  the login of the run's own reviewer identity (`.user.login`).
set -u

# jq binary: resolved once via the single-source resolver (execution-verified); an
# explicit DEVFLOW_JQ still wins, so test stubs are untouched.
_CHR_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib"
# shellcheck source=../lib/resolve-jq.sh
. "$_CHR_LIB/resolve-jq.sh"

if [ ! -f "$_CHR_LIB/review-verdict-marker.jq" ] || [ ! -r "$_CHR_LIB/review-verdict-marker.jq" ]; then
  echo "unestablished marker-module-unavailable"
  exit 0
fi

PAYLOAD="${1:-}"
HEAD="${2:-}"
LOGIN="${3:-}"

# (1) The two operands the classification cannot proceed without. Absent head or login
#     is UNESTABLISHED, never `none`: with either missing nothing about the reviews was
#     measured.
if [ -z "$HEAD" ]; then
  echo "unestablished head-sha-absent"
  exit 0
fi
if [ -z "$LOGIN" ]; then
  echo "unestablished reviewer-login-absent"
  exit 0
fi

# (2) Resolve the payload source. A file path that is not a readable file is
#     UNESTABLISHED payload-unreadable (the payload was never observed). Stdin (`-`) is
#     handed to jq directly.
_CHR_SRC=""
if [ "$PAYLOAD" = "-" ]; then
  _CHR_SRC="-"
else
  if [ ! -r "$PAYLOAD" ] || [ -d "$PAYLOAD" ]; then
    echo "unestablished payload-unreadable"
    exit 0
  fi
  _CHR_SRC="$PAYLOAD"
fi

# (3) Classify in jq. The program emits `none`, `marked`, `unmarked <ids>`, or an
#     `ERR <reason>` token that bash maps to a closed UNESTABLISHED reason. A jq parse
#     or execution failure exits non-zero and is caught below as payload-unparseable.
#     `.user.login`/`.commit_id`/`.body` are indexed defensively: a missing object
#     yields null (jq does not error), and select() drops a review by another login. The
#     body-type check runs BEFORE any string op and short-circuits, so a non-string body
#     grades ERR rather than aborting the whole filter.
#
#     Both candidate comparands are ascii_downcase-d against a downcased HEAD_SHA so a
#     hand-authored uppercase marker head compares byte-exact against the lowercase SHA the
#     API returns — normalized IN jq, never with a bash-4 `${var,,}` (macOS ships bash 3.2)
#     and never with `tr`, which lib/preflight.sh does not guarantee and whose absence would
#     empty the value and select the wrong arm.
_CHR_PROG='
  include "review-verdict-marker";
  # Only a complete line-1 stamp supplies authoritative placement.
  def marker_head:
    (.body | verdict_marker_scan(1) | .markers) as $markers
    | if ($markers | length) == 1 then $markers[0].head else "" end;
  # `commit_id` as a lowercase string, or "" for null/absent/non-string. Type-checked before
  # ascii_downcase so a shape this helper does not produce cannot abort the whole filter.
  def commit_key:
    (.commit_id // "") as $c
    | if ($c | type) == "string" then ($c | ascii_downcase) else "" end;
  if (type != "array") then "ERR payload-not-an-array"
  else
    ($head | ascii_downcase) as $h
    # Scoped by LOGIN only. Scoping by commit here was the defect: a review the head
    # advanced past — or whose commit_id GitHub rewrote (issue #1247) — vanished from the
    # set entirely and the empty set graded `none`, re-emitting the categorical "left the
    # reviews API untouched" for a run that had posted an unmarked bypass review.
    | [ .[] | select(.user.login == $login) ] as $own
    | if ($own | length) == 0 then "none"
      elif ($own | map(.body | type) | any(. != "string")) then "ERR body-not-a-string"
      else
        # Place every own review: marker head first (authoritative), commit_id fallback
        # (not authoritative, so it can place a review ON the head but never OFF it).
        [ $own[]
          | . as $r
          | marker_head as $mh
          | commit_key as $cid
          | if $mh != "" then (if $mh == $h then {p:"on", marked:true, id:$r.id} else {p:"off"} end)
            elif $cid != "" and $cid == $h then {p:"on", marked:false, id:$r.id}
            else {p:"indeterminate"} end
        ] as $placed
        | [ $placed[] | select(.p == "on" and .marked == false) | .id ] as $unmarked
        | if ($unmarked | length) > 0
          then "unmarked " + ($unmarked | sort | map(tostring) | join(" "))
          elif ([ $placed[] | select(.p == "on") ] | length) > 0 then "marked"
          # Only `none` asserts that the API was untouched, so only `none` is blocked by a
          # review that could not be positively placed off the head.
          elif ([ $placed[] | select(.p == "indeterminate") ] | length) > 0
          then "ERR review-placement-unprovable"
          else "none"
          end
      end
  end
'

_CHR_OUT=""
if [ "$_CHR_SRC" = "-" ]; then
  _CHR_OUT="$("$DEVFLOW_JQ" -r -L "$_CHR_LIB" --arg head "$HEAD" --arg login "$LOGIN" "$_CHR_PROG" 2>/dev/null)" \
    || { echo "unestablished payload-unparseable"; exit 0; }
else
  _CHR_OUT="$("$DEVFLOW_JQ" -r -L "$_CHR_LIB" --arg head "$HEAD" --arg login "$LOGIN" "$_CHR_PROG" "$_CHR_SRC" 2>/dev/null)" \
    || { echo "unestablished payload-unparseable"; exit 0; }
fi

# (4) Map the jq answer to the closed stdout vocabulary. An `ERR <reason>` becomes
#     `unestablished <reason>`; an empty answer (jq ran but produced nothing) is
#     classify-failed rather than a silent `none`.
case "$_CHR_OUT" in
  none|marked) echo "$_CHR_OUT" ;;
  'unmarked '*) echo "$_CHR_OUT" ;;
  'ERR '*)      echo "unestablished ${_CHR_OUT#ERR }" ;;
  *)            echo "unestablished classify-failed" ;;  # empty (jq ran, produced nothing) or an unexpected shape
esac
exit 0
