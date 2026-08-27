---
bump: patch
type: Fixed
---

- **`workpad.py update` now resolves the workpad comment through the shared scan and a
  verified comment-id cache.** The update path no longer runs its own inlined comment scan
  or a standalone `gh repo view`: it finds the comment through `_find_workpad_comment`
  (which carries the not-a-JSON-array guard the inlined copy lacked — a rc-0 non-list
  comments response now fails through the labeled `update id-lookup` breadcrumb instead of
  crashing with a Python traceback), remembers the resolved id in a gitignored
  `.prflow/tmp/` cache, and on later calls fetches that comment directly — trusting the
  cached id only after verifying its marker and `issue_url`. Repository resolution rides
  `gh api`'s `{owner}/{repo}` placeholders. A warm-cache call makes two `gh` requests
  instead of four-plus, roughly halving an automation run's workpad API traffic. (#2048)
