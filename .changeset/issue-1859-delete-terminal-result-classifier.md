---
bump: patch
type: Removed
---

- **Delete the unwired `terminal-result` classifier (issue #1273 dead code).** The classifier `scripts/terminal-result-class.sh`, its generated total table `lib/terminal-result-table.tsv`, that table's generator `lib/generate-terminal-result-table.py`, and the focused suite module `lib/test/modules/terminal-result-class.sh` (with its `.inventory.md`) were shipped by PR #1792 but never wired to any workflow, skill, or script, and the follow-up family that would have wired them is closed. This removes them along with their suite registration (the flight-recorder registry, the `lib/test/run.sh` dispatch, the `run-shard.sh` and `ci.yml` module lists, the coverage-map entries, the `regenerate-artifacts.py` drift row, and the audited-population lists and count in the pin-corpus census). (#1862)
