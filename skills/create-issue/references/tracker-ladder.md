<!-- prflow:create-issue-ref step=tracker-ladder file=skills/create-issue/references/tracker-ladder.md start -->
## Tracker ladder

Reached when `TodoWrite` is not exposed, or a `TodoWrite` call did not establish the tracker. Work
these rungs in order, moving to the next whenever the one you tried is unavailable.

1. `TaskCreate`/`TaskUpdate`.
2. `update_plan`.
3. When no candidate appears in the visible tool list, re-read any listing the runner already
   supplied of tools it has not yet exposed, and try any candidate it names.
4. Failing that, look for a discovery mechanism the runner itself advertises — a listed tool whose
   stated purpose is to find and load tools the runner has not yet exposed — and use it to search
   for the candidates above, never as a candidate itself.
5. Once every candidate is exhausted, use the inline fallback in
   `references/fallback-no-task-tool.md`.

Pick only from candidates the runner lists as currently exposed; where you cannot establish which
tools are visible, try them in this same order anyway.

**A candidate is unavailable** when it is not exposed, when a call returns a failure, or when a call
returns without a failure but leaves the tracker unconfirmed under the same confirmation test the
skill root applies to `TodoWrite`.

**No rung ends the run.** Hold a breadcrumb naming any failure — the discovery mechanism's call
included — and carry on to the next rung; the root's *Announcement* section fixes where the held
breadcrumbs are emitted.
<!-- prflow:create-issue-ref step=tracker-ladder file=skills/create-issue/references/tracker-ladder.md end -->
