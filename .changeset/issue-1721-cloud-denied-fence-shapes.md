---
bump: patch
---

Shipped fences no longer prescribe command shapes the cloud harness refuses.

Every cloud-reachable fence that redirected into a scratch path under `.prflow/tmp/` has been
rewritten to a shape the harness accepts: whole-file artifacts are authored with the Write tool,
and a command's stderr is read from that invocation's own tool result instead of being captured
to a `.err` file. A refused fence produced no output at all and burned a request, so the run
recovered by improvising — for the Phase 0 diff-staging path that improvisation dropped the
fail-closed staging entirely.

The Phase 0 local-diff staging path keeps its guard structure as ordered, separately-checked
stages that stream through `tee` rather than passing the diff through the agent, so a truncated
tool result cannot publish a thinned cache. Each stage reports its own section count, and a single
failure rule clears the cache and stops; a count that legitimately falls to zero (a logs-only
diff) publishes and is reviewed as nothing to flag.

One error-handling arm is corrected rather than rewritten. The acceptance-criteria resolver's
failure arm told the run to read a `.err` file that only the refused redirect could have created,
so on any tier that refuses the redirect the diagnostic channel could never produce a cause; it
now quotes the stderr the invocation itself returned.

Two fences that routed on `grep`-ing a captured stderr file now guard on each invocation's own
exit status, read inline rather than captured into a variable a later statement reads — a shape
that leaves the status empty on a runner that strips variables between statements, routing every
healthy run to the unrecognised arm. Deferral discovery collapses every non-zero status into a
single degraded state and tells a partial search from a failed one after the fence, from the
marker its helper writes to stderr — never by testing whether the call returned any paths, which
a partial search over roots holding no manifest would route to the failed arm.
Where the status is genuinely ambiguous — `file-deferrals.py` shares one code between "no
deferrals", "already filed" and three input errors — the run reads that call's stderr to tell
them apart, and records an unrecognised shape as a failure rather than guessing.

One file is deliberately unchanged: the weekly retrospective skill, which no workflow dispatches
and which therefore runs only on the interactive tier, where these redirects execute normally. It
was not degraded to satisfy a cloud constraint.

Two cloud-reachable populations are adjudicated but not rewritten, because the Write-tool remedy
cannot reach them: appends made inside a shell read-loop, and captures targeting a `mktemp` path.
Both are recorded with their reason and carried to a follow-up.
