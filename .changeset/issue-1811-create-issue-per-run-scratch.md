---
bump: patch
type: Changed
---

- **create-issue now namespaces its scratch under `.prflow/tmp/create-issue/<slug>/` and reaps it on success.** Every run artifact (drafts, staged history, audit files, audit state, emitted body, fetched copies, derivation artifact) is written into a per-run sub-directory instead of as a flat file directly under `.prflow/tmp/`, and a run that creates its issue removes its own run directory as its final step (keyed to the recorded slug — never a pattern or age sweep, so concurrent runs in sibling worktrees are untouched); a run that ends any other way leaves the directory in place as its diagnostic record. Pre-existing flat `issue-*` files are left untouched. (#1957)
