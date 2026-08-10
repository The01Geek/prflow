---
bump: patch
type: Fixed
---

- **Propagate a failed redirect on a `!`-negated compound command.** bash does not carry a
  redirection failure on a compound command (`{ …; }` / `( … )`) through `!`, so
  `if ! { …; } > "$f"` read as success when the redirect could not open and the failure arm
  never ran. Four sites now capture the group's status and branch on it instead:
  `scripts/check-verdict-post-reached.sh` (the `receipt-read-failed` arm),
  `scripts/seed-review-progress.sh` (the normalize-body write, on every cloud review path),
  `scripts/provision-python3-shim.sh` (the shim-body write), and the
  `regenerate-artifacts.sh` fixture builder's index write. A new
  `lib/test/lint-negated-compound-redirect.py` guard fails the suite if the idiom is
  reintroduced. (#1539)
