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
with no edits — **all of it**, however many lines it is. It prints either a markdown
table (which already carries its own `###` heading) or a short breadcrumb explaining why
there is nothing to show, and either of those may be followed by one or more `> Note:`
lines disclosing something that qualifies the figures. Place everything it printed near the end of
the body, after the change summary.

**Compose no figure yourself.** Every byte count, delta, total, and sha in that section
comes from the helper's output. Do not estimate, round, re-order, re-total, summarize,
or restate any number it printed anywhere else in the description, and do not add a
number it did not print. A figure you compose is an estimate, and an estimate presented
beside generated ones is indistinguishable from them.

The helper always exits 0 and gates nothing: a breadcrumb instead of a table is a normal
outcome, never an error to work around or retry.

It also prints on every path it can reach, so **no output at all is never the helper
speaking** — it means the invocation never ran (a permission refusal, which is silent by
design; `Permission denied` or rc 126 from a lost executable bit; a vendored copy that is
absent in a way the two arms above did not match). That is a deployment or grant fault a
maintainer needs to see, so do not omit the section silently: write one line in the PR
body naming both paths you tried and the reading you got, and nothing about size.
