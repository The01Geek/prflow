---
bump: patch
type: Fixed
---

- **Gate Python lint (`ruff`) inside the test suite so a lint regression can no longer ship green.**
  CI's `lint` job ran `ruff` but was never a required status check, so a Python lint regression
  stayed invisible to both an implement run's own completion gate and the merge gate
  (`lib + python tests`) — `lib/test/run.sh` contained no `ruff` invocation at all. `run.sh` now
  runs `ruff check` over the tracked Python files as part of the suite (the `monolith` shard),
  failing the suite on any violation and, because `ruff` is not preflight-guaranteed, self-skipping
  through the existing `skip … blocking-gate …` helper — never a silent pass — when `ruff` is not
  installed. The CI shard job now installs `ruff==0.15.*` (the same pin the `lint` job uses) so the
  gate arms on the required check rather than self-skipping there, and the suite reconciles the two
  pins mechanically — asserting each job declares one and that the specs are equal — so dropping the
  shard install cannot leave the gate self-skipping while the required check stays green. Scope is
  `ruff` only; `shellcheck`
  and `actionlint`, which share CI's non-required lint job, are deliberately left out of scope. (#1621)
