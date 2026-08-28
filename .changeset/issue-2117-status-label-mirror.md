---
bump: patch
type: Added
customer-visible: true
---

- **Mirror the implement run's status onto issue and pull-request labels.** Every
  `/prflow:implement` run now keeps a managed status label in sync on its issue, and on its
  pull request once one exists, so a maintainer sees a stalled or finished run from the issue
  and PR lists without opening the workpad comment. Three labels track the workpad Status:
  `PRFlow:Implementing` (a run is in progress), `PRFlow:Stuck` (a run stopped and needs
  attention), and `PRFlow:Complete` (a run finished). The labels follow the workpad status
  automatically — applied even on the statuses written after the agent has already stopped —
  and a repository turns the whole feature off with the `status_labels.enabled` config key (on
  by default). (#2117)
