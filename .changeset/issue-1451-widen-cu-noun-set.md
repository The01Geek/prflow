---
bump: patch
---

**The coverage-universal detector now seeds §2.3.4b on the referent nouns and modifier shape the recurring `incomplete-edit` failures actually used.** `scripts/stale-prose-lint.py`'s `CU` tier matched its quantifiers against a closed referent-noun set that carried no `row`, `entry`, `population`, `partner`, or `helper`, so sentences built on those nouns produced no `CU` seed row and the implement engine's §2.3.4b enumeration sweep under-represented the claims the diff authored.

`_CU_NOUN` now additionally recognises `row` / `entry` (spelling the irregular `entries` plural) / `population` / `partner` / `helper`, singular and plural. A new CU-local `_CU_MOD` modifier constant tolerates an intervening modifier token that leads with a hyphen or backtick-hyphen (e.g. `` `-x`-gated ``), so a line like "on any `` `-x`-gated `` bundled helper …" is recognised; `_RECOG_MOD` is left byte-identical because it is shared with the gating-adjacent R3 recognition tier. Both prose statements of the closed noun set — the comment above `_CU_NOUN` and the module-header spec paragraph — are updated in the same commit. The tier stays non-gating: every `CU` row is `UNRESOLVABLE`, so this only widens the seed floor and flips no exit code. (#1451)
