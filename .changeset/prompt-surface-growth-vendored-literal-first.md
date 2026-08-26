---
bump: patch
---

`scripts/prompt-surface-growth.py`'s invocation contract now names the vendored literal
`.prflow/vendor/prflow/scripts/prompt-surface-growth.py` as the form to try FIRST, with the
repo-relative `scripts/prompt-surface-growth.py` as the fallback for a checkout where the
vendored path does not resolve. The previous wording named the repo-relative spelling first
and the vendored literal as a parenthetical alternative, which is inverted for the cloud
tier: only the vendored literal is granted in the `implement` and `command` profiles, so a
cloud run following the docstring order spends a permission denial before reaching the form
that works. Ordering matches the ladder `.prflow/prompt-extensions/pr-description.md`
already prescribes. The same docstring's claim that the `python3 <path>` interpreter-head
form "is denied by the cloud permission matcher" is also corrected: two cloud implement runs
ran `python3 scripts/prompt-surface-growth.py` to a result under the granted `Bash(python3:*)`
head, so the claim steered runs away from a form that works. The correction is scoped to this
helper and asserts nothing about the interpreter head in general. Docstring only — no
behaviour change.
