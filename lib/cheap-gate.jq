# cheap-gate.jq — mechanical "clean PR" predicate for the devflow retrospective.
#
# Decides whether a PR context bundle can be skipped by the LLM analysis
# because all observable signals are clean. This is a pure filter with no
# side-effects; it never touches disk or network.
#
# Deliberately UNWIRED to the `Verification evidence:` marker (issues #730, #1249).
# Since issue #1249 that marker is recorded on EVERY tier that maintains a workpad
# (cloud `/prflow:implement` included, not just local/interactive), so the old
# population-coverage reason for leaving this gate unwired — that the marker's
# scoping excluded this gate's merged, predominantly-cloud watched-author input
# population (via lib/scan.sh) — no longer holds. Wiring the marker into this gate
# would nonetheless change retrospective sampling for every merged PR, which is a
# separate open decision (issue #1249 kept it explicitly out of scope) rather than
# a consequence of that superseded coverage argument. The marker's runtime consumer
# stays the shared review engine's non-blocking advisory
# (.prflow/skill-extensions/review.md and its byte-identical twin
# review-and-fix.md), which reads it per-PR on both tiers.
#
# Invocation:
#   jq -c -f lib/cheap-gate.jq <context-bundle.json
#
# Input (stdin):
#   A single context bundle object as emitted by fetch-pr-context.sh, which
#   must contain a ".signals" object with these fields:
#     review_comments_count     <int>    — human review comments left on the PR
#     post_bot_commits          <int>    — non-merge commits after the last
#                                          bot/PR-author commit that are positively
#                                          human-attributable: counted when EITHER
#                                          login is non-blank, does not end in [bot]
#                                          and is not the PR author. A commit whose
#                                          two logins are both blank or absent is
#                                          agent-side, never human (unknown is not a
#                                          human), so it is not counted
#     ci_failures_during_pr     <int>    — check-runs on the head SHA, across every
#                                          page, whose conclusion is a real red
#                                          signal. Superseded runs (cancelled,
#                                          stale) and success/neutral/skipped/null
#                                          do not count; failure, timed_out,
#                                          action_required and any unrecognised
#                                          conclusion do (a denylist, so an unknown
#                                          future conclusion fails closed)
#     workpad_final_status      <string|null> — final workpad status tag
#     review_reject_outstanding <bool>   — true if a review REJECT (from either the
#                                          PR conversation comments or the durable
#                                          bot PR reviews) has not been superseded
#                                          by a later APPROVE. Must be a genuine
#                                          boolean: if `.signals` is not an object,
#                                          or this field is absent/null/non-boolean,
#                                          the gate FAILS CLOSED with the reason
#                                          "review-verdict signal unreadable" (a
#                                          truthy JSON string like "false" must not
#                                          be read as an outstanding REJECT — issue
#                                          #895).
#     ci_status_unknown         <bool>   — true if CI check-runs could not be read
#                                          (fail-safe: such a PR is never "clean")
#   plus two TOP-LEVEL fields (siblings of .signals):
#     reflections               <array>  — the workpad's `## PRFlow Reflections`
#                                          bullets (flat string array; defaulted
#                                          to [] when absent — older bundles).
#     reflections_friction_count <int|absent> — how many of those bullets are
#                                          FRICTION (every reflection kind EXCEPT
#                                          the informational `note`). Only friction
#                                          forces analysis: a run whose reflections
#                                          are all `note`-kind is treated as clean.
#                                          Emitted by fetch-pr-context.sh. When
#                                          ABSENT (an older bundle, or a bundle
#                                          whose emission failed) the gate FAILS
#                                          CLOSED — it falls back to the legacy
#                                          "any reflection trips" behavior
#                                          (reflections | length > 0), so a missing
#                                          signal over-analyzes, never silently
#                                          skips a friction PR.
#
# Output:
#   One compact JSON object:
#     { "clean": <bool>, "reason": <string> }
#
#   "clean" is true iff ALL of the following hold:
#     • review_reject_outstanding == false
#     • ci_status_unknown        == false
#     • ci_failures_during_pr    == 0
#     • post_bot_commits         == 0
#     • review_comments_count    == 0
#     • workpad_final_status     is "Complete" (an absent workpad — "", null, or
#                                 an absent key — fails closed with the reason
#                                 "workpad absent or status unknown"; any other
#                                 non-"Complete" string keeps "workpad status not
#                                 Complete")
#     • no FRICTION reflections  (reflections_friction_count == 0; or, when that
#                                 field is absent, reflections is empty)
#
#   "reason" names the FIRST failing check when clean=false, or
#   "all clean signals" when clean=true. Check order matches the priority
#   used in the LLM triage prompt (most-blocking first) — with the
#   "review-verdict signal unreadable" fail-closed check evaluated BEFORE every
#   other arm, so an unreadable review signal is named as such rather than masked
#   by the workpad-absent reason a non-object `.signals` would otherwise trip. The
#   reflection check
#   is last: a run that left a FRICTION bullet on its workpad is forced into
#   LLM analysis even when every other signal is clean — that self-reported
#   friction is exactly the signal the retrospective exists to learn from. A run
#   whose only reflections are informational `note`-kind bullets is NOT friction
#   and is treated as clean (the note is still recorded verbatim by
#   clean-entry.jq). `reflections` and `reflections_friction_count` are top-level
#   bundle fields (siblings of .signals), read directly.

# Normalize .signals to an object once: a non-object value (absent, null, string,
# array, number) becomes {} so EVERY field read below is safe regardless of the
# if/elif arm order — no per-field type guard, and no reliance on the fail-closed
# arm short-circuiting to keep the later raw index reads safe (issue #895).
.signals as $s0
| ($s0 | type) as $signals_type
| (if $signals_type == "object" then $s0 else {} end) as $s
# review_reject_outstanding must be readable as a boolean, or the gate fails CLOSED.
# The raw read `if $s.review_reject_outstanding` is unsafe two ways: a non-object
# `.signals` (now normalized to {} above, so the field reads null) and a JSON
# *string* value ("false" is truthy in jq, "true" would pass a `// false`-style
# guard as a real boolean) both mis-read the signal. So require a genuine boolean:
# a normalized-away container yields null (type "null"), and a string yields type
# "string" — either selects the distinct fail-closed arm below, reported before
# every other arm so an unreadable review signal is named as such rather than
# masked by the workpad-absent reason. The reason literal is NEITHER workpad reason
# literal, so dispatch-disposition.jq routes such a bundle to `dispatch`.
| ($s.review_reject_outstanding) as $rro
| (($rro | type) == "boolean") as $rro_readable
| ((.reflections // []) | length) as $reflection_count
# Fail closed: when the friction field is ABSENT (null — an older bundle or a
# failed emission), fall back to the legacy "any reflection trips" count so a
# missing signal over-analyzes rather than reading as zero friction.
| (if (.reflections_friction_count == null) then $reflection_count
   else .reflections_friction_count end) as $friction_count
# The clean set is "Complete" ONLY (issue #626). An absent workpad — the empty
# string "" or JSON null (or an absent key, which jq reads as null) — is NOT
# clean: it fails closed with a distinct reason, symmetric with the present-but-
# corrupt `Unparsed` case, so a run that left no audit trail is surfaced rather
# than laundered past analysis. A non-empty non-"Complete" string (Unparsed /
# Blocked / Failed / Cancelled / any future word) keeps the existing reason.
# $s is normalized to an object above, so this read is direct and safe.
| ($s.workpad_final_status) as $wfs
| ($wfs == "Complete") as $workpad_ok
| (($wfs == "") or ($wfs == null)) as $workpad_absent
|
  if   ($rro_readable | not)                      then { clean: false, reason: "review-verdict signal unreadable" }
  elif $rro                                       then { clean: false, reason: "outstanding /review REJECT" }
  elif ($s.ci_status_unknown // false)            then { clean: false, reason: "CI status could not be read" }
  elif $s.ci_failures_during_pr   > 0             then { clean: false, reason: "CI failures during PR" }
  elif $s.post_bot_commits        > 0             then { clean: false, reason: "human commits after the bot" }
  elif $s.review_comments_count   > 0             then { clean: false, reason: "review comments present" }
  elif $workpad_absent                            then { clean: false, reason: "workpad absent or status unknown" }
  elif ($workpad_ok | not)                        then { clean: false, reason: "workpad status not Complete" }
  elif $friction_count            > 0             then { clean: false, reason: "friction reflections present" }
  else                                                 { clean: true,  reason: "all clean signals" }
  end
