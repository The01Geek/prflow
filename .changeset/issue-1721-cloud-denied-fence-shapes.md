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

The Phase 0 local-diff staging path keeps its guard structure as five ordered steps (produce,
stage, filter, publish, confirm), each with an observable exit status and a single failure rule
that clears the cache and stops. Its redundant promotion command is gone: the Write that authors
`diff.patch` is the promotion.

One error-handling arm is corrected rather than rewritten. The acceptance-criteria resolver's
failure arm told the run to read a `.err` file that only the refused redirect could have created,
so on any tier that refuses the redirect the diagnostic channel could never produce a cause; it
now quotes the stderr the invocation itself returned.

Two fences that routed on `grep`-ing a captured stderr file now route on the helper's exit code,
which fully discriminates for deferral discovery. Where an exit code is genuinely ambiguous —
`file-deferrals.py` shares one code between "no deferrals" and "already filed" — the run reads
that call's stderr to tell them apart, and records an unrecognised shape as a failure rather
than guessing.

One file is deliberately unchanged: the weekly retrospective skill, which no workflow dispatches
and which therefore runs only on the interactive tier, where these redirects execute normally. It
was not degraded to satisfy a cloud constraint.

Two cloud-reachable populations are adjudicated but not rewritten, because the Write-tool remedy
cannot reach them: appends made inside a shell read-loop, and captures targeting a `mktemp` path.
Both are recorded with their reason and carried to a follow-up.
