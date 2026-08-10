---
bump: patch
---

**`/prflow:implement`'s always-resident Workpad Reference no longer duplicates `workpad.py --help`.** The orchestrator's `### Workpad helper CLI` section carried a subcommand table, a `workpad.py update` flag table, and a paragraph restating `update`'s re-fetch and all-or-nothing semantics — resident in every phase of every implement run, and superseded by the helper's own `--help`, which had drifted ahead of them. They are replaced by one sentence pointing at `workpad.py --help` and `workpad.py update --help`. Nothing composed a call from the tables: the `workpad.py` call sites in the phase files are complete invocations that restate the semantics they depend on. The cross-phase run policy is unchanged and stays where it was: the failure-isolation contract, the Status-PATCH read-back walk, the reflection-kind routing rule, the interpolation-safe `--reflection-file` recipe, and the never-two-workpads rule. (#1531)
