# efficiency-trace.jq — derives the per-run subagent effectiveness view from
# the /devflow:review-and-fix per-iteration workpads.
#
# This is the mechanical heart of the telemetry feature: it reads the
# `iter-<N>.json` workpads (already on disk under .prflow/tmp/review/<slug>/<run-id>/),
# assigns each dispatched Phase-3 subagent exactly one of four effectiveness
# verdicts, and emits EITHER a rendered Markdown trace ($mode == "trace") OR a
# single per-run JSON record ($mode == "record"). No LLM, no side effects —
# matching how the weekly retrospective does all mechanical work in lib/.
#
# Invocation (via lib/efficiency-trace.sh, which validates inputs first):
#   jq --raw-output --slurp -f lib/efficiency-trace.jq \
#      --arg mode {trace|record} --arg slug <slug> \
#      --arg generated_at <iso8601> --argjson cut_candidate_min_dispatch <int> \
#      iter-1.json iter-2.json ...
#   (--raw-output is load-bearing for trace mode: it renders the Markdown string
#   instead of emitting it JSON-quoted with literal \n.)
#
# Inputs:
#   stdin: array of per-iteration workpad objects (pass -s to slurp the
#          separate iter-*.json files into one array). May be empty.
#   $mode: "trace" → Markdown string; "record" → the JSON record object.
#   $slug: the run slug (pr-<N> or sanitized branch name).
#   $generated_at: ISO-8601 UTC timestamp for the record.
#   $cut_candidate_min_dispatch: carried into the record for the cross-run
#          analyzer (this filter does not act on it).
#   $config_fingerprint: the config-variant fingerprint object
#          ({sha256, partial, salient}) or null, computed by the wrapper (issue
#          #431). Carried verbatim into the record so an experiment analysis can
#          attribute the run to the config that produced it; this filter does not
#          act on it. null when the wrapper could not establish a fingerprint.
#
# Effectiveness taxonomy (4-way, per dispatched subagent, per iteration):
#   unique-effective — raised a finding that led to an applied fix and that no
#                      sibling agent corroborated (corroboration_count < 2).
#   corroborating    — its finding led to an applied fix but ≥1 other agent
#                      raised the same defect (corroboration_count ≥ 2).
#   noise            — its only findings were pushed back / demoted to advisory
#                      (fix_decision ∈ {pushed_back, advisory}); none applied.
#   null             — dispatched but raised nothing, or nothing that survived
#                      to an applied fix or a noise classification. A finding
#                      whose only outcome is `deferred` (real, but out-of-scope
#                      / already-tracked), `severity-calibrated` (real, but
#                      over-graded and calibrated down — not a false positive),
#                      or `settled-by-disclosure` (real, but foreclosed because
#                      the concern is already disclosed in the shipped tree —
#                      issue #621) is deliberately `null`, NOT `noise`: `noise`
#                      is reserved for `pushed_back` / `advisory` (false-positive
#                      / web-refuted). A #660 review note proposing
#                      `settled-by-disclosure` be bucketed as `noise` was
#                      DECLINED on exactly this rule — a foreclosed finding is
#                      true, so counting it as agent noise would understate the
#                      agent. Revisit only if `noise` is redefined to mean
#                      "raised but not acted on" rather than "false positive".
#                      Any future `fix_decision` value also defaults to `null`
#                      unless `verdict_for` is updated.
#
# Narrowed `null` class (issue #1849). `null` is a DERIVED residual, so a bare
# `null` verdict still collapses opposite states: an agent genuinely silent, one
# whose real findings were all deferred / severity-calibrated / foreclosed, and
# one that failed or returned an unusable result. Additive per-agent fields —
# `disposition` and `fix_decisions` — beside the verdict decompose it; they add
# NO new verdict and change no derivation: `disposition` (returned | failed | silent | unestablished — see
# `agent_disposition`) separates a failed return from silence and marks the split
# unestablished when the roster or failed set was never established (unknown is
# not zero); and `fix_decisions` (the per-agent roll-up of `fix_decision` values)
# separates an all-deferred/calibrated agent from one that raised nothing.
# Denominator confound (read the rates with it): a per-agent rate's denominator
# is the defects that existed to be found, not the agent's quality — a `null` or
# low-yield rate on a config-only / out-of-domain diff is correct silence, so raw
# per-agent rates are NOT reviewer quality until that shipped-defect denominator
# is characterised (see docs/internal/efficiency-trace.md).
#
# The four buckets above are written in `fix_decision` (review-and-fix) terms.
# `verdict_for` has a SECOND derivation for standalone-/devflow:review records
# (run-level `source == "review"`), where there is no `fix_decision`: a finding's
# `contributed_to_verdict` boolean replaces applied-fix as the effectiveness
# signal — `noise` = the agent raised findings but none satisfied
# `contributed_to_verdict == true` (deferral-demoted via explicit `false`, an omitted
# field, OR a malformed value such as a stringified `"true"` — the strict `== true`
# gate treats all three as non-contributing),
# `null` = dispatched but raised nothing. Buckets and precedence are identical;
# only the discriminator differs. See `verdict_for` for the authoritative logic.
#
# Verdict precedence (highest wins, so each agent gets exactly one):
#   unique-effective > corroborating > noise > null.
#
# Graceful degradation: a workpad missing `phase3_dispatched` still classifies
# the agents that appear in its `phase3_findings` (the roster is the union of
# `phase3_dispatched` and the agents seen in findings) — only genuinely-silent
# agents become invisible without the roster, which is the documented limit.

# The agent identifier for a single phase3_findings entry.
def finding_agent: .agent;

# The defect-kind label for a single phase3_findings entry (issue #1903). A
# well-formed signature is an object carrying a non-empty string `kind`; an
# absent or malformed signature (a non-object, or a missing/empty/non-string
# kind) renders explicitly as "unknown" rather than dropping the finding from
# the recurrence count. The object type-guard is load-bearing: indexing a
# present-but-non-object signature (a string/number/array/boolean) with `.kind`
# would abort the whole filter.
def finding_kind:
  (.defect_signature) as $sig
  | if ($sig | type) == "object"
    then (($sig.kind) as $k
          | if ($k | type) == "string" and ($k | length) > 0 then $k else "unknown" end)
    else "unknown"
    end;

# Per-agent disposition decomposing the derived `null` residual (issue #1849).
# `null` collapses three opposite states — an agent that returned findings, one
# that failed / returned an unusable result, and one dispatched but silent. This
# splits them, gated on what the producer actually established (unknown is not
# zero):
#   returned      — the agent appears in this iteration's phase3_findings.
#   failed        — the agent is named in the established failed set (the
#                   `phase3_failed_agents` sink or a shadow per-reviewer
#                   assessment that marked it not-returned).
#   silent        — dispatched, absent from findings, and the failed set is
#                   established and does NOT name it.
#   unestablished — the split cannot be read from what the producer emitted: the
#                   roster is absent (a non-returning agent cannot be enumerated
#                   at all) or the failed set is absent/malformed (a silent agent
#                   cannot be told from a failed one). Never mapped onto silent.
# A returning agent is establishable from findings alone, so it reads `returned`
# even when the roster or failed set is absent. `$failed_established` is
# per-AGENT, not per-iteration: the authoritative `phase3_failed_agents` sink
# covers every dispatched agent, but the shadow `per_reviewer_assessment` covers
# only the reviewers it lists, so an agent that neither sink establishes reads
# `unestablished` even when the other sink is present for other agents.
def agent_disposition($returned; $roster_established; $failed_established; $is_failed):
  if $returned then "returned"
  elif ($roster_established | not) then "unestablished"
  elif $is_failed then "failed"
  elif ($failed_established | not) then "unestablished"
  else "silent"
  end;

# Human-readable Phase 0.5 diff-profile label for the trace.
def diff_profile_label($dp):
  if $dp == null then "not recorded"
  else
    ([ (if ($dp.engine_self_modifying // false) then "engine_self_modifying" else empty end),
       (if ($dp.small_diff // false)            then "small_diff"            else empty end),
       (if ($dp.config_only // false)           then "config_only"           else empty end),
       (if ($dp.has_new_types // false)         then "has_new_types"         else empty end) ]) as $flags
    | if ($flags | length) == 0 then "full engine (no flags)" else ($flags | join(" + ")) end
  end;

# Verification-posture line: makes the orchestrator's cost decision legible so a
# low verifier count reads as a deliberate cheap-path choice, not "nothing ran".
def posture_line($it):
  $it.checklist_lite_count as $l | $it.checklist_agent_count as $a
  | if   $it.verification_posture == "skipped-intentional" then
      "- Checklist: skipped by Phase 0.5 (\(diff_profile_label($it.diff_profile))) — verifier subagents intentionally not dispatched for a low-risk diff."
    elif $it.verification_posture == "skipped-failure" then
      "- Checklist: generation failed — proceeded with review agents only."
    elif $it.verification_posture == "none-recorded" then
      "- Checklist verifiers: none recorded for this iteration."
    elif $it.verification_posture == "lite-only" then
      "- Checklist verifiers: \($l) lite (orchestrator-direct), 0 agent — verifiable items resolved without dispatching verifier subagents (cost-saving, by design)."
    else
      "- Checklist verifiers: \($l) lite, \($a) agent."
    end;

# Classify one agent's findings (an array of phase3_findings rows for that
# agent in one iteration) into a single verdict.
#
# Two derivations, selected by the `$review_mode` arg (the run-level `source`):
#   * review-and-fix records carry `fix_decision` (applied/pushed_back/advisory) —
#     "effective" means the finding led to an APPLIED fix.
#   * standalone /devflow:review records carry `contributed_to_verdict` (a boolean)
#     instead — review never fixes, so "effective" means the finding CONTRIBUTED
#     to the verdict (drove the REJECT or was counted in APPROVE-with-notes), and
#     `noise` means the agent raised findings but none satisfied
#     `contributed_to_verdict == true` (explicit `false`, the field absent, or a
#     malformed value — the strict `== true` gate, see verdict_for). The buckets and precedence
#     (unique-effective > corroborating > noise > null) are identical; only the
#     "did it count?" signal differs.
# `$review_mode` is the run-level discriminator (`source == "review"`), NOT the
# per-finding field shape. Keying on the run-level source — not on
# `any(has("contributed_to_verdict"))` — is deliberate: a review-mode agent whose
# only finding was deferral-demoted may carry `contributed_to_verdict: false` *or*
# omit it entirely, and a per-finding-presence test would mis-route that whole
# agent into the fix-loop branch and silently downgrade a real-but-demoted finding
# from `noise` to `null`. With the run-level key, review-mode `noise` is reached
# whenever the agent raised findings but none contributed — robust to an omitted
# field.
def verdict_for($findings; $review_mode):
  if $review_mode then
    # review-mode: contribution-to-verdict replaces applied-fix. A finding counts
    # as contributing only on explicit `contributed_to_verdict == true`; anything
    # else (false, the field absent, or a non-boolean/malformed value such as a
    # stringified "true" from an LLM-authored record) is treated as
    # non-contributing — the strict `== true` is deliberately the only truthy gate.
    ($findings | map(select(.contributed_to_verdict == true))) as $contributing
    | if ($contributing | any(((.corroboration_count // 1)) < 2)) then "unique-effective"
      elif ($contributing | length) > 0 then "corroborating"
      # Raised findings but none contributed → noise (handles explicit false AND
      # an omitted field); no findings at all → null (dispatched but silent).
      elif ($findings | length) > 0 then "noise"
      else null
      end
  else
    # review-and-fix mode: applied-fix is the effectiveness signal.
    ($findings | map(.fix_decision)) as $decisions
    | ($findings | map(select(.fix_decision == "applied"))) as $applied
    # corroboration_count missing → treat as 1 (unique / single-source).
    | if ($applied | any(((.corroboration_count // 1)) < 2)) then "unique-effective"
      elif ($applied | length) > 0 then "corroborating"
      elif ($decisions | any(. == "pushed_back" or . == "advisory")) then "noise"
      else null
      end
  end;

# Per-iteration derived view.
def iter_view:
  . as $it
  | (($it.phase3_findings) // []) as $findings
  | (($it.phase3_dispatched) // []) as $dispatched
  | (($it.checklist) // []) as $checklist
  | (($it.convergence_inputs.fixes_applied) // 0) as $fixes_applied
  | (($it.diff_profile) // null) as $diff_profile
  | ([$checklist[] | select(.verification_mode == "lite")]  | length) as $lite_count
  | ([$checklist[] | select(.verification_mode == "agent")] | length) as $agent_count
  | ($diff_profile.checklist_skipped // null) as $checklist_skipped
  # Verification posture makes the orchestrator's cost decision LEGIBLE: a low
  # verifier count is a deliberate cheap-path choice (lite-only / Phase-0.5 skip),
  # not "nothing happened". Distinguishes the healthy no-subagent paths from a
  # genuine instrumentation gap (none-recorded with no skip reason).
  | (if   $checklist_skipped == "intentional" then "skipped-intentional"
     elif $checklist_skipped == "failure"     then "skipped-failure"
     elif ($lite_count + $agent_count) == 0   then "none-recorded"
     elif $agent_count == 0                    then "lite-only"
     elif $lite_count == 0                     then "agent-only"
     else "mixed"
     end) as $verification_posture
  # Roster = dispatched ∪ agents-seen-in-findings (degradation safety).
  | (($dispatched + ($findings | map(finding_agent))) | unique) as $roster
  # Failed-agent operands for the per-agent disposition (issue #1849). The
  # `phase3_failed_agents` sink (written by the review engine's Phase 3 for a
  # non-returning agent) is unioned with the shadow block's per-reviewer
  # assessment, whose `returned == false` reviewers are the shadow join's
  # dispatched-but-lost set. Both are type-guarded so an agent-mutable, malformed
  # producer value never aborts the filter: a non-array `phase3_failed_agents`
  # (object/scalar/valid-falsy) and a non-array/absent assessment each yield no
  # failed entries. Establishment is per-AGENT (see agent_disposition): the
  # authoritative `phase3_failed_agents` array covers every dispatched agent, while
  # the shadow `per_reviewer_assessment` authoritatively covers only the reviewers
  # it lists with a boolean `returned`. A malformed present value on either channel
  # establishes nothing for the agents it fails to cover (unknown is not zero), so
  # a silent agent that neither sink covers reads `unestablished`, never `silent`.
  | (($it.phase3_failed_agents) // null) as $failed_raw
  # The shadow `per_reviewer_assessment` is authoritative only on a full-coverage
  # block: on a not_verified (outcome 3) block it holds a partial pre-shortfall
  # capture (per shadow-review.md), so a reviewer that returned but was not yet
  # captured could read `returned: false` — using it to establish failed/silent
  # there would mis-classify. Gate on `coverage == "full"`; otherwise the channel
  # decides nothing and its agents fall back to unestablished (unknown is not zero).
  | (($it.shadow | objects | select(.coverage == "full") | .per_reviewer_assessment) // null) as $assess_raw
  # Element-aware establishment (issue #1849 review): keying on container type alone
  # (== "array") would treat a malformed-element array ([{...}], ["x",7]) as a total
  # establishment and re-collapse an uncovered silent agent onto "silent" — every
  # element must be a string ([] is a valid "none failed" establishment).
  | (($failed_raw | type) == "array") as $failed_is_array
  | (if $failed_is_array then ($failed_raw | map(type == "string") | all) else false end) as $failed_direct_present
  | (if $failed_direct_present then [$failed_raw[] | strings] else [] end) as $failed_direct
  # Only assessment entries with a boolean `returned` and a string `agent` are
  # authoritative; `$assess_covered` names the agents the assessment can decide,
  # and its `returned == false` members are the shadow-lost (failed) set.
  | (if ($assess_raw | type) == "array"
     then [$assess_raw[] | select(type == "object" and ((.returned) | type) == "boolean" and ((.agent) | type) == "string")]
     else [] end) as $assess_entries
  | ($assess_entries | map(.agent)) as $assess_covered
  | ([$assess_entries[] | select(.returned == false) | .agent]) as $assess_failed
  | (($failed_direct + $assess_failed) | unique) as $failed_agents
  # Roster presence: the residual can only be decomposed over an established
  # roster. Absent `phase3_dispatched` means a non-returning agent cannot be
  # enumerated, so the iteration is roster-unestablished (AC3) — reused from the
  # existing phase3_dispatched_present idiom below.
  | ($it | has("phase3_dispatched")) as $roster_established
  # dispatched_effort (issue #609): the iter-workpad field capturing every
  # dispatch phase's roster with its per-agent effort decision — including the
  # Phase-1/1.5/2 checklist agents that never appear in phase3_dispatched.
  # Type-guarded: a non-array field (absent/null/scalar alike), or a
  # non-object/agent-less entry, yields no usable entries (the filter never
  # aborts on a malformed producer value).
  | (if ($it.dispatched_effort | type) == "array"
     then [$it.dispatched_effort[] | select(type == "object" and ((.agent) | type) == "string")]
     else [] end) as $de
  # The effort roster is the FULL dispatched set (phase3_dispatched ∪ the
  # dispatched_effort agents), never the resolver map: an agent with no entry
  # still gets an all-null session-inheritance block below.
  | (($dispatched + ($de | map(.agent))) | unique) as $effort_roster
  # Defect-kind recurrence inputs (issue #1903). Only object findings are read:
  # `defect_signature_present` is whether ANY finding in this iteration carries
  # the `defect_signature` key at all — the run-level "unestablished" trigger
  # keys on this being false everywhere, distinct from a finding that carries a
  # malformed signature (present-but-wrong, rendered as the "unknown" kind).
  # `defect_kinds` is this iteration's distinct kind labels.
  | ([$findings[] | select(type == "object")]) as $obj_findings
  | ($obj_findings | map(has("defect_signature")) | any) as $defect_signature_present
  | ($obj_findings | map(finding_kind) | unique) as $defect_kinds
  | {
      iter: ($it.iter // null),
      phase3_dispatched: $dispatched,
      phase3_dispatched_count: ($dispatched | length),
      checklist_lite_count:  $lite_count,
      checklist_agent_count: $agent_count,
      # Phase 0.5 classification (small_diff / config_only / has_new_types /
      # engine_self_modifying / checklist_skipped). Carried into the record so
      # the cross-run analyzer can segment by diff shape — a `null` agent on a
      # config-only diff is correctly silent, NOT a cut candidate.
      diff_profile: $diff_profile,
      verification_posture: $verification_posture,
      fixes_applied: $fixes_applied,
      added_nothing: ($fixes_applied == 0),
      # The roster is "present" iff the field exists at all. A legitimately-empty
      # roster ("phase3_dispatched": []) is still present — only a genuinely
      # absent field triggers the degradation warning in the trace. Reuses the
      # $roster_established binding above (the same has() test) rather than
      # re-evaluating it.
      phase3_dispatched_present: $roster_established,
      # Presence mirror for the #609 roster field, same unknown-vs-zero honesty
      # as phase3_dispatched_present: an empty array is present; only a
      # genuinely absent field reads false (an older workpad).
      dispatched_effort_present: ($it | has("dispatched_effort")),
      # Per-agent effort observability (issue #609): agent id + exactly the five
      # effort fields, complete by construction. An agent with no
      # dispatched_effort entry records the all-null session-inheritance block —
      # the degradation mirror of build_effort_observability's no-override arm
      # in scripts/resolve-review-overrides.py (a coupled pair, edit together);
      # `effective` is carried verbatim (null unless genuinely read back —
      # unknown is not zero). With multiple entries for one agent the last wins.
      agent_effort: [
        $effort_roster[] as $agent
        | ([$de[] | select(.agent == $agent)] | last) as $entry
        | {
            agent: $agent,
            requested: $entry.requested,
            resolved: $entry.resolved,
            application_point:
              (if $entry == null then "session-inheritance"
               else $entry.application_point end),
            effective: $entry.effective,
            fallback_reason: $entry.fallback_reason
          }
      ],
      # Per-agent effectiveness view. `verdict` is UNCHANGED (issue #1849 adds no
      # new verdict and perturbs no derivation); `disposition` decomposes the
      # `null` residual and `fix_decisions` rolls up the per-finding decisions so
      # an all-deferred/calibrated agent (verdict null, non-empty roll-up) is
      # distinguishable from one that raised nothing (verdict null, empty roll-up).
      # `fix_decisions` is the sorted-unique set of string `fix_decision` values
      # this agent's findings carry (type-guarded via `strings`; empty in
      # review-mode records, which carry no fix_decision).
      agent_verdicts: [
        $roster[] as $agent
        | ([$findings[] | select(finding_agent == $agent)]) as $af
        | {
            agent: $agent,
            verdict: verdict_for($af; ($it.source == "review")),
            disposition: agent_disposition(
              (($af | length) > 0);
              $roster_established;
              ($failed_direct_present or (($assess_covered | index($agent)) != null));
              (($failed_agents | index($agent)) != null)),
            fix_decisions: ($af | map(.fix_decision) | map(strings) | unique)
          }
      ],
      # Presence flag for the #1849 authoritative failed-set sink, same
      # unknown-vs-zero honesty as phase3_dispatched_present: a well-formed
      # `phase3_failed_agents` array reads true; an absent/malformed one reads
      # false, so a historical record lacking the field surfaces as
      # disposition-unestablished (AC7). The shadow `per_reviewer_assessment` is a
      # separate, per-agent channel and does not set this iteration-level flag.
      phase3_failed_agents_present: $failed_direct_present,
      telemetry: ($it | if (type == "object" and has("telemetry") and .telemetry != null) then .telemetry else "unavailable" end),
      # Which skill produced this iteration: "review" (standalone /devflow:review)
      # vs the default review-and-fix loop. Carried so a cross-run analyzer can
      # segment effectiveness by originating skill (both write into the same
      # .prflow/logs/efficiency/ store; the filename does not disambiguate them).
      source: ($it.source // null),
      # True when this iteration was RECONSTRUCTED by lib/efficiency-trace.sh's
      # synthesis floor (issue #381) from a fix commit rather than written by the
      # loop — a strict `== true` so an absent/malformed field reads false. Surfaced
      # in the record so downstream analysis never mistakes a reconstructed record
      # for an agent-written one.
      synthesized: (($it.synthesized) == true),
      # Carried for the loop_role derivation resolved in the top-level pass below
      # (where the full sorted array is in scope). loop_role_persisted is the
      # workpad's own value when present and non-empty — it wins over derivation.
      # shadow_promoted is THIS iter's shadow.promoted_to_iter_next, read by the
      # NEXT iter to decide promoted-vs-fix. Both type-guarded so a malformed
      # shadow block or a non-string loop_role never aborts the filter. Coerced to
      # a strict boolean (`== true`): a non-object shadow, an absent/null field, or
      # a malformed non-boolean value (e.g. the string "yes") all become false, so a
      # malformed producer value can never over-classify the next iter as promoted.
      loop_role_persisted: (($it.loop_role) | if (type == "string" and (length > 0)) then . else null end),
      shadow_promoted: ((($it.shadow | objects | .promoted_to_iter_next) // false) == true),
      # Defect-kind recurrence inputs (issue #1903), carried for the run-level
      # derivation resolved in the top-level pass below.
      defect_signature_present: $defect_signature_present,
      defect_kinds: $defect_kinds
    };

# ── Build the ordered per-iteration array ───────────────────────────────────
(. | map(iter_view) | sort_by(.iter // 0)) as $iters

# ── Derive loop_role per iteration (issue #170) ─────────────────────────────
# A persisted non-empty loop_role wins; otherwise the first iteration (in order)
# is "fix" and a later iteration is "promoted" when its immediately-preceding
# iteration recorded a Decide-outcome-2 shadow promotion (shadow.promoted_to_iter_next
# == true), else "fix". Positional (sorted) prior is used because .iter is
# best-effort; on any degenerate input the rule degrades to "fix". This gives the
# field a real consumer in the per-run record below, so it is no longer left to be
# reconstructed by inference from the prior iter's shadow block.
| ([ range(0; ($iters | length)) as $i
     | $iters[$i]
     | .loop_role = (
         if   (.loop_role_persisted != null)   then .loop_role_persisted
         elif $i == 0                          then "fix"
         elif ($iters[$i - 1].shadow_promoted) then "promoted"
         else "fix"
         end)
   ]) as $iters

# ── Derive recurring defect kinds per run (issue #1903) ─────────────────────
# A recurring kind is a defect_signature.kind value appearing in the
# phase3_findings of three separate iterations of the run. When no iteration
# record carries a defect_signature at all, the recurrence signal cannot be
# read from what the producer emitted, so the field renders as the explicit
# "unestablished" sentinel rather than an empty set (the repo's rule that a
# check must not silently read an operand its producer never emitted). A
# malformed-but-present signature is "established" and counts under the
# "unknown" kind, so it is not the unestablished case.
| ($iters | map(.defect_signature_present) | any) as $defect_signature_established
| (if ($defect_signature_established | not) then "unestablished"
   else
     # Each $iters element is one iteration record, so distinctness keys on the
     # element POSITION, not the `.iter` value — the loop_role pass above abandons
     # `.iter` as best-effort for the same reason, and a null/duplicate `.iter`
     # would otherwise collapse two separate records and undercount. The reported
     # `iterations` list still carries the `.iter` values for legibility.
     ( [ range(0; ($iters | length)) as $i
         | ($iters[$i].iter) as $label
         | $iters[$i].defect_kinds[] | {kind: ., pos: $i, iter: $label} ]
       | group_by(.kind)
       | map({ kind: (.[0].kind),
               iterations: ([.[].iter] | unique),
               _positions: ([.[].pos] | unique | length) })
       | map(select(._positions >= 3))
       | map(del(._positions))
       | sort_by(.kind) )
   end) as $recurring_defect_kinds

# ── record mode: the single per-run JSON record ─────────────────────────────
# With zero readable iterations (catastrophic early failure) emit nothing, not a
# contentless skeleton — symmetric with the flag-off contract and the trace
# mode's "unavailable" degradation, so the caller's `[ -s ]` guard removes the
# 0-byte file and no empty record is committed.
| if $mode == "record" then
    if ($iters | length) == 0 then empty else
    {
      # schema_version stays 1 across the issue #431 config_fingerprint addition:
      # the field is additive and OPTIONAL (nullable), no consumer gates on the
      # version, and the #431 assembler handles presence/absence uniformly
      # (falling back to `git show <merge_sha>:.prflow/config.json` when it is
      # null/absent). A bump would imply a breaking change this is not — records
      # predating the field remain valid.
      schema_version: 1,
      slug: $slug,
      generated_at: $generated_at,
      # The config-variant fingerprint (issue #431), carried verbatim from the
      # wrapper: {sha256, partial, salient} or null when it could not be
      # established (the assembler then falls back to the merge-commit config).
      config_fingerprint: $config_fingerprint,
      # Originating skill for the whole run, taken from the workpads (each iter
      # may carry `source`; default to the historical producer when absent so
      # existing review-and-fix records read unchanged). Assumes one source per
      # run (a run is either a /devflow:review pass or a review-and-fix loop, never
      # both) — takes the first non-null. Per-iteration `verdict_for` still keys
      # off each iter's own `source`, so a (not-currently-produced) mixed-source
      # run would still classify each iteration correctly even though this
      # run-level label collapses to one value.
      source: ($iters | map(.source) | map(select(. != null)) | (.[0] // "review-and-fix")),
      # True when ANY iteration was reconstructed by the issue #381 synthesis floor
      # (a fully-dropped run recovered from fix commits) — the record-level marker a
      # cross-run analyzer keys on to weight a reconstructed record differently.
      synthesized: ($iters | any(.synthesized == true)),
      cut_candidate_min_dispatch: $cut_candidate_min_dispatch,
      # Every defect_signature.kind that appeared in three separate iterations of
      # this run, each with the sorted list of iterations it appeared in (issue
      # #1903) — or the "unestablished" sentinel when no iteration carried a
      # defect_signature to read. A kind that never repeated that often is absent.
      recurring_defect_kinds: $recurring_defect_kinds,
      iterations: ($iters | length),
      per_iteration: ($iters | map({
        iter: .iter,
        # Each iteration's role in the fix loop (fix | promoted), derived above
        # (issue #170) — the real consumer of the iter workpad's loop_role field.
        loop_role: .loop_role,
        # Whether this iteration was reconstructed by the issue #381 synthesis floor.
        synthesized: .synthesized,
        phase3_dispatched: .phase3_dispatched,
        phase3_dispatched_count: .phase3_dispatched_count,
        # Carried into the durable record so the cross-run analyzer can tell a
        # genuinely zero-dispatch iteration from one degraded by an absent roster
        # (both show count 0) — the chat-only trace warning does not survive teardown.
        phase3_dispatched_present: .phase3_dispatched_present,
        # Issue #1849: whether the failed-set operand was established this
        # iteration, carried into the durable record so a reader can tell a
        # decomposed disposition from an unestablished (historical/malformed) one.
        phase3_failed_agents_present: .phase3_failed_agents_present,
        # Issue #609: the per-agent effort observability block and its roster
        # field's presence flag, carried into the durable record (additive and
        # nullable — schema_version stays 1, mirroring config_fingerprint).
        dispatched_effort_present: .dispatched_effort_present,
        agent_effort: .agent_effort,
        # Phase 0.5 diff classification + the orchestrator's verification posture,
        # so the analyzer never penalizes an agent for being correctly silent on
        # an out-of-domain diff and can see when subagents were intentionally skipped.
        diff_profile: .diff_profile,
        verification_posture: .verification_posture,
        checklist_lite_count: .checklist_lite_count,
        checklist_agent_count: .checklist_agent_count,
        fixes_applied: .fixes_applied,
        added_nothing: .added_nothing,
        agent_verdicts: .agent_verdicts
      })),
      # Cost telemetry carried forward from each workpad so it is no longer lost
      # when .prflow/tmp/ is destroyed at GH-runner teardown. `phases` mirrors
      # established workpad value verbatim, or the explicit unavailable marker.
      telemetry: ($iters | map({iter: .iter, phases: .telemetry}))
    }
    end

# ── trace mode: the rendered Markdown effectiveness trace ───────────────────
  elif $mode == "trace" then
    (
      ["## Subagent effectiveness trace", ""]
      + (
          if ($iters | length) == 0 then
            ["_No iteration workpads were readable — effectiveness trace unavailable._"]
          else
            ($iters | map(
              # Review mode (source == "review") never applies fixes — effectiveness is
              # verdict contribution, not applied fixes. So the fixes-oriented summary and
              # the "added nothing" warning are review-mode-adapted; otherwise a healthy
              # review (agents contributed) would print a contradictory "0 fixes — added
              # nothing" line right below its unique-effective verdicts.
              (.source == "review") as $review_mode
              | ([.agent_verdicts[] | select(.verdict == "unique-effective" or .verdict == "corroborating")] | length) as $contributed
              | [ "### Iteration \(.iter)",
                  "- Diff profile: \(diff_profile_label(.diff_profile))",
                  "- Phase 3 agents dispatched: \(.phase3_dispatched_count)",
                  posture_line(.),
                  (if $review_mode
                   then "- Effectiveness signal: verdict contribution (standalone review applies no fixes) — \($contributed) of \(.agent_verdicts | length) agent(s) contributed"
                   else "- Fixes applied: \(.fixes_applied)" end)
                ]
              + (.agent_verdicts | map("  - \(.agent) — \(.verdict)") | (if length == 0 then ["- Agent verdicts: (none dispatched)"] else ["- Agent verdicts:"] + . end))
              + (if $review_mode
                 then (if ($contributed == 0 and (.agent_verdicts | length) > 0) then ["- ⚠ Marginal yield: no dispatched agent contributed to the verdict this run."] else [] end)
                 else (if .added_nothing then ["- ⚠ Marginal yield: this iteration applied 0 fixes — added nothing."] else [] end) end)
              + (if (.phase3_dispatched_present | not) then ["- ⚠ `phase3_dispatched` absent — null agents (dispatched but silent) cannot be shown for this iteration."] else [] end)
              + [""]
            ) | add)
          end
        )
      # Recurring defect kinds (issue #1903): a kind seen across 3+ iterations is
      # the signal to model the artifact rather than extend an enumeration.
      + (if $recurring_defect_kinds == "unestablished" then
           ["### Recurring defect kinds", "- _Unestablished — no iteration record carried a defect_signature to read._", ""]
         elif ($recurring_defect_kinds | length) == 0 then
           []
         else
           ["### Recurring defect kinds (3+ iterations — model the artifact, do not extend an enumeration)"]
           + ($recurring_defect_kinds | map("- \(.kind) - iterations \(.iterations | map(tostring) | join(", "))"))
           + [""]
         end)
    ) | join("\n")

  else
    error("efficiency-trace.jq: unknown $mode '\($mode)' (expected 'trace' or 'record')")
  end
