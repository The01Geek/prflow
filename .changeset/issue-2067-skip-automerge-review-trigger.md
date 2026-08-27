---
bump: patch
type: Fixed
---

- **The CI-green auto-review trigger no longer requests a review for a pull request set to auto-merge.** `scripts/post-ci-review-trigger.sh`'s post-time state guard now reads the `auto_merge` field from the pull-request response it already fetches: an open pull request with GitHub auto-merge armed gets no `/prflow:review` comment and a distinct warning annotation naming enabled auto-merge, so the trigger stops racing the coming merge onto an already-merged target (a paid review with no reader). The merged test is still decided first and the new state is emitted only for an open pull request, so the existing merged/closed/unestablished arms are unchanged; the helper still makes a single state request. In a repository that also requires an approving review the armed pull request does not merge at CI-green, so this arm withholds the automatic request and the manual `/prflow:review` comment remains the supported path. (#2072)
