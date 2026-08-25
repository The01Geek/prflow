# clean-entry.jq — builds a retrospective entry for a mechanically-clean PR.
#
# Input (stdin):
#   A single context bundle object (kind == "implementation") as emitted by
#   fetch-pr-context.sh. The PR must have already passed the cheap-gate.jq
#   predicate (i.e. all signals are clean).
#
# Output:
#   One compact JSON object: the retrospective entry ready to append to
#   retrospectives.jsonl.  All verdict/analysis fields are set to their
#   "clean" defaults — no LLM call required.
#
# Invocation:
#   jq -c -f lib/clean-entry.jq <context-bundle.json

{
  schema_version: 3,
  kind: "implementation",
  pr: .pr,
  issue: .issue_number,
  merged_at: .merged_at,
  branch: .branch,
  head_sha: .head_sha,
  merge_commit_sha: .merge_commit_sha,
  verdict: "clean",
  categories: [],
  descriptors: [],
  signals: .signals,
  # Record the workpad's reflection bullets verbatim (additive field). A PR reaches
  # the clean path with a non-empty `reflections` only when every bullet is an
  # informational `note`-kind (non-friction) one — cheap-gate.jq exempts exactly
  # those — so preserving them here keeps an exempted note in the learnings instead
  # of dropping it. Byte-for-byte the bundle's flat string array; [] when absent.
  reflections: (.reflections // []),
  # Diff-size fields echoed from the bundle (additive; schema_version 3). Defaulted so an
  # entry written by a producer that lacks them still cleans without error.
  additions: (.additions // null),
  deletions: (.deletions // null),
  changed_files: (.changed_files // null),
  summary: (if ((.reflections // []) | length) > 0
    then "PR merged with no review comments, no outstanding /review REJECT, no substantive human commits after the bot, no CI failures, and a Complete workpad; recorded informational reflection note(s) with no analysis-forcing friction."
    else "PR merged with no review comments, no outstanding /review REJECT, no substantive human commits after the bot, no CI failures, and a Complete workpad — no retrospective signal."
    end),
  suggested_interventions: []
}
