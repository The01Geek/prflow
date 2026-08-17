# DevFlow repo — operative policy for `/prflow:pr-description`

## Prompt-surface size section

Render the growth this branch introduced as a generated
fact in the PR body.

Run the bundled helper as the command's **leading token**, vendored literal first:

```bash
.prflow/vendor/prflow/scripts/prompt-surface-growth.py
```

If that reading is `command not found`, `No such file`, or rc 127, re-invoke the same
helper with the `.prflow/vendor/prflow/` prefix removed:

```bash
scripts/prompt-surface-growth.py
```

Insert the helper's stdout into the PR description **verbatim**, exactly as printed and
with no edits — **all of it**, however many lines it is. Its output is a markdown table
(which already carries its own `###` heading) or a breadcrumb, either of which may be
followed by one or more `> Note:` lines. Place everything it printed near the end of
the body, after the change summary.

**The table carries five columns — `Path`, `Before`, `After`, `Δ bytes`, `Δ %` — and a
bold `Whole covered surface` total row.** Paste every column and that row. Dropping a
column is the observed failure: a size section showing only `After` and `Δ bytes` leaves
a reader unable to judge whether a delta is large, which is the one question the section
exists to answer. If what you pasted has fewer than five columns or no total row, you
edited the output — re-run the helper and paste it whole.

**Compose no figure yourself.** Every byte count, before-size, delta, percentage, total,
and sha in that section comes from the helper's output. Do not estimate, round, re-order,
re-total, summarize, or restate any number it printed anywhere else in the description,
and do not add a number it did not print.

**This bans a hand-built size table anywhere in the body, not just inside that section.**
A separately authored before/after table measuring something the helper does not measure
(words rather than bytes, a subset of files, a different base) reads as the same claim
while being pinned to no sha — so the two disagree and neither is checkable. Where you
want a figure the helper does not print, the answer is to change the helper, not to
compute one beside it.

The helper always exits 0 and gates nothing: a breadcrumb instead of a table is a normal
outcome, never an error to work around or retry.

It also prints on every path it can reach, so **no output at all is never the helper
speaking** — it means the invocation never ran. Do not omit the section silently: write
one line in the PR body naming both paths you tried and the reading you got, and nothing
about size.
