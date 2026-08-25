---
bump: patch
type: Changed
---

- **Self-validating portable-helper anchor on non-Claude-Code runners.** The shared
  "Portable helper anchor" paragraph (the 17 identity-pinned `skills/*/SKILL.md` copies and
  `skills/create-issue/SKILL.md`'s variant) now locates the skill directory by validating a
  candidate against the filesystem — accepting it only once `ls <candidate>/../../scripts/`
  succeeds in the same shell — instead of computing a path from a runner-reported value and
  never checking it. The optional `wslpath`/`cygpath` probe is kept (tried in order, no
  platform branch, output used only on success with non-empty output); the tool-less
  drive-letter arithmetic, the WSL-vs-MSYS2 branch, and the platform guess are removed, and a
  runner that validates no candidate stops and reports rather than running a broken path
  (`create-issue` keeps its degrade-never-block carve-out). (#1940)
