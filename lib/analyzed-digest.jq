# analyzed-digest.jq — selects the weekly retrospective's "Analyzed PRs" digest
# lines from the slurped new-entries.jsonl array (invoke with jq -s).
#
# The verdicts selected here — imperfect, blocked, and analyst-graded clean — are
# the Stage A outcomes counted in analyzed_count, so they belong in the digest. A
# gate-skipped clean entry (lib/clean-entry.jq) is
# mechanical, cost no LLM call, and stays excluded — it is told apart by its empty
# analysis fields: lib/clean-entry.jq hard-codes categories/descriptors/
# suggested_interventions to [], whereas an analyst-graded clean populates at least
# one. Selecting on empty-vs-populated (not on the summary text) keeps the two
# clean shapes distinguishable without pinning a template string.
#
# `arrays` guards each analysis field: those fields are LLM-authored, so a
# non-array shape on one row must not abort the whole filter (same discipline as
# lib/compute-patterns.jq's grouping_tags/descriptors guards).
#
# lib/compute-patterns.jq keeps its own imperfect-or-blocked select and is
# unchanged by this file (AC2).
#
# Invocation:
#   jq -sc -f lib/analyzed-digest.jq .prflow/tmp/new-entries.jsonl

def _analysis_nonempty:
  (((.categories | arrays) // []) | length) > 0
  or (((.descriptors | arrays) // []) | length) > 0
  or (((.suggested_interventions | arrays) // []) | length) > 0;

[ .[]
  | select(
      .verdict == "imperfect"
      or .verdict == "blocked"
      or (.verdict == "clean" and _analysis_nonempty)
    )
  | {pr, verdict, summary}
]
