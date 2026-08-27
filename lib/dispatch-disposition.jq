# dispatch-disposition.jq — mechanical skip-or-dispatch classifier for the
# devflow weekly retrospective (issue #626).
#
# Runs ONLY on a bundle the cheap-gate already reported non-clean, and decides —
# with NO LLM dispatch — whether that non-clean bundle should be skipped
# (recorded, not analyzed) or dispatched to Stage A analysis. This is the repo
# convention that branch-selecting decision logic lives in a suite-drivable
# helper, never inline orchestrator prose (cf. scripts/describe-denial-count.sh).
#
# Invocation (bundle on stdin, gate result as an arg):
#   jq -c --argjson gate "$(jq -c -f lib/cheap-gate.jq <bundle.json)" \
#     -f lib/dispatch-disposition.jq <bundle.json
#
# Inputs:
#   stdin  — the context bundle emitted by fetch-pr-context.sh. Reads:
#     .signals.workpad_final_status  <string|null> — the sentinel/status word
#     .pr_devflow_provenance         <bool>        — true iff the PRFlow label
#            is on the PR or the resolved issue (fail-closed: any non-`true`
#            value, including a wrong type or an absent field, reads as false).
#   --argjson gate — the cheap-gate.jq output object { clean, reason }. Reads
#            .reason to establish WHY the bundle is non-clean.
#
# Decision: return "skip" EXACTLY when all three hold —
#   1. the gate's reason is one of the two workpad reason literals
#      ("workpad absent or status unknown" | "workpad status not Complete"),
#   2. the status word is a sentinel ("Absent" | "NoIssue"),
#   3. provenance is false.
# Otherwise "dispatch". Precedence is therefore explicit: a bundle non-clean on
# ANY non-workpad signal (outstanding REJECT, an unreadable review-verdict signal,
# CI failures, post-bot commits, review comments) is dispatched regardless of
# sentinel or provenance — exactly the analysis it receives today.
#
# Output: one compact JSON object:
#   { "disposition": "skip"|"dispatch", "reason": <string> }
# A skip carries the exact operator-facing reason line; a dispatch echoes the
# gate reason so the run report can name why it was analyzed.

# Guard the index: a `.signals` that is not a JSON object (absent, null, string,
# array, number) would abort the filter on `.signals.workpad_final_status`. Treat
# any non-object as an unknown workpad status (null), which is never a sentinel, so
# the bundle routes to `dispatch` (issue #895) — the safe direction for a
# truncated/hand-edited bundle.
(if (.signals | type) == "object" then .signals.workpad_final_status else null end) as $status
| (.pr_devflow_provenance == true) as $has_provenance
| ($gate.reason) as $gate_reason
# COUPLED CONTRACT: these two literals are cheap-gate.jq's workpad reason lines —
# rewording either there without updating here silently mis-classifies a workpad-
# absent PR as `dispatch`. Only the FIRST is test-guarded end-to-end: lib/test/run.sh's
# `disp()` block pipes REAL cheap-gate output through this filter, and because the
# producer's sentinels are non-empty strings, cheap-gate answers "workpad status not
# Complete" on every skip-eligible bundle — so a reword of THAT literal flips the
# "Absent + no provenance → skip" assertion RED. The "workpad absent or status
# unknown" disjunct is defense-in-depth for a leaked ""/null status, which can never
# co-occur with a sentinel and therefore never yields a skip; reword it in lockstep
# by hand, since no assertion covers it.
| (($gate_reason == "workpad absent or status unknown")
   or ($gate_reason == "workpad status not Complete")) as $workpad_reason
| (($status == "Absent") or ($status == "NoIssue")) as $is_sentinel
| if ($workpad_reason and $is_sentinel and ($has_provenance | not))
  then { disposition: "skip",
         reason: ("no PRFlow provenance and no workpad audit trail — workpad_final_status is "
                  + ($status | tostring)
                  + "; skipping without analysis") }
  else { disposition: "dispatch", reason: ($gate_reason // "dispatched for analysis") }
  end
