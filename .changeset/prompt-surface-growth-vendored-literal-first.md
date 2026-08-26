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
already prescribes. Docstring only — no behaviour change.
