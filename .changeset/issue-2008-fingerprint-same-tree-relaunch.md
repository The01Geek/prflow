---
bump: patch
---

Permit a fingerprint-gated failed-shard-only suite relaunch after a RED completion-gate pass whose fix changed no repository file (issue #2008, PR #2016).

Each suite launch now records its five-field checkout fingerprint (from `scripts/checkout-fingerprint.py`) as `fingerprint.json` in its retained location — the run root for `lib/test/run-parallel.sh`, the tally dir for `lib/test/run-shard.sh` — written *unestablished* (never omitted) when it cannot be produced. Two new `lib/test/shard-tally.py` subcommands support the relaunch: `record-fingerprint` writes that record (best-effort, always exits 0) and `same-tree-eligible` exits 0 only when a fresh fingerprint equals the RED run's recorded one on all five fields. The completion-gate prose in `CLAUDE.md` states the eligibility rule: on a proven byte-identical tree, relaunch only the failed shards and recombine them with the RED run's retained clean-shard tallies through `shard-tally.py combine --require-shards`; on any field mismatch or unestablished fingerprint the full coordinator relaunch stays mandatory.
