---
bump: patch
type: Fixed
---

- **`post_bot_commits` no longer counts blank-login agent commits as human rework.** The retrospective's `post_bot_commits` field (in `lib/fetch-pr-context.sh`) now counts a non-merge commit after the last bot/PR-author commit only when it is positively human-attributable — its `author_login` or `committer_login` is a non-blank string that neither ends in `[bot]` nor equals the PR author. A commit whose two logins the API returns blank (the local-tier agent identity GitHub cannot resolve to an account) is classified agent-side, never human — unknown is not a human; a commit with one blank and one human login is still counted. The classification is also type-guarded, so a non-string login cannot abort the filter — hardening, not a live fix, since the producer already normalizes an absent login to `""` before the filter sees it. The coupled `POSTBOT_SHAS` block and the field's `lib/cheap-gate.jq` description are updated to match. (#1941)
