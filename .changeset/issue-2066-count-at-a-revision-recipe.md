---
bump: patch
type: Added
---

- **The cloud review tier's command-shape discipline now names a revision-anchored
  read-and-count recipe.** A review actor that needs to count how often a symbol appears
  in a file at a specific commit finds the recipe stated in the review skill root's
  command-shape block (`skills/review/SKILL.md`) and, self-contained, in the displaced-path
  routing contract each dispatched review agent receives
  (`skills/review/phases/phase-3-agents.md`): read the file with `git show <sha>:<path>`
  (the revision written as a literal) and count with the granted text tools
  (`grep -c -F` for a line count, `grep -n -F` to locate), with a composed
  Write/`tee`-into-`.prflow/tmp/`-then-`grep` fallback for when the pipe is refused. The
  same block's refused-shape list now names the spellings an agent would otherwise iterate
  — git's own grep sub-command, git -C, and a revision passed as a parameter expansion — so
  the block's existing two-refusal hard rule becomes actionable for this need. The exact
  pipe shape gains a `matcher-probe.yml` probe row and a pending-verdict record in
  `docs/internal/cloud-allowlist.md`. (#2074)
