---
title: "Human Control"
description: "See which decisions, permissions and merge actions stay with people."
---

See exactly where PRFlow stops and you decide.

PRFlow can prepare and review a change, but people keep authority over the repository. The boundaries below are deliberate. They are what makes an autonomous run something you can adopt without giving up control of what lands.

## Before a Run

- The [create-issue workflow](/docs/workflows/create-issue) saves the issue draft to a file and shows you its path — printing the full draft in chat only when you ask — and waits for your explicit approval of those exact bytes before it creates anything.
- A local run can ask you for clarification, and it asks your client for tool permission as it goes. See [Local Permissions](/docs/runs/local/permissions).
- Maintainers decide which configuration, prompt extensions and permission scopes are committed to the repository. A run can only use what you committed.
- A cloud run starts only for an authorized collaborator or an allowed bot. An outside fork contributor cannot start one. See [Security and Trust](/docs/concepts/security).

## During a Run

<CardGroup cols={2}>
  <Card title="Grant narrowly" icon="key">
    Review each permission request at the narrowest scope that still lets the work proceed. Keep broad shell, filesystem and credential access out of the run unless the workflow genuinely needs it.
  </Card>
  <Card title="Read Blocked before retrying" icon="octagon-exclamation">
    A `Blocked` workpad entry names a cause. Read it and resolve it. Retriggering the run without resolving the cause reproduces the same stop.
  </Card>
  <Card title="Treat gaps as decisions" icon="scale-balanced">
    A scope change, a deferred acceptance criterion or a verification that did not run is a decision that needs evidence. It is not an inconvenience to route around.
  </Card>
  <Card title="Watch the writes" icon="eye">
    PRFlow writes issue comments, branches, commits, pull requests, reviews and follow-up issues, when the active identity has permission. All of it stays visible in Git and GitHub.
  </Card>
</CardGroup>

## Pull-Request State

An implementation run opens a **draft** pull request before its review and documentation work finishes. When the run completes, the default is to publish it as ready for review. Maintainers can configure PRFlow to leave it as a draft instead.

<Warning>
  "Ready for review" means the configured workflow completed. It does not mean a person approved the change, that branch protection passed or that the deployment risk is acceptable.
</Warning>

## The Merge Boundary

PRFlow never merges a pull request. Before you do, work through these:

<Steps>
  <Step title="Review the change">
    Read the code, the tests and the documentation the run produced, the same way you would read a colleague's pull request.
  </Step>
  <Step title="Read the workpad">
    Check the acceptance-criteria evidence and the `PRFlow Reflections` section, which is where blockers, deferrals and dropped work are recorded. See [Workpads and Resume](/docs/concepts/workpads-and-resume).
  </Step>
  <Step title="Evaluate the review findings">
    Read the verdict and any remaining caveats. An approval-family verdict is evidence, not proof. See [The Review System](/docs/concepts/review-system).
  </Step>
  <Step title="Wait for your own checks">
    Required repository checks and required approvals apply exactly as they always did. See [How PRFlow Verifies a Change](/docs/concepts/verification).
  </Step>
  <Step title="Merge or request changes">
    Use your team's normal process. This step has no PRFlow equivalent.
  </Step>
</Steps>

This boundary is the point of the design. PRFlow automates the preparation and the evidence gathering, and leaves the irreversible decision with the people who own the repository.

## Related Documentation

- [Security and Trust](/docs/concepts/security)
- [The Review System](/docs/concepts/review-system)
- [How PRFlow Verifies a Change](/docs/concepts/verification)
- [Workpads and Resume](/docs/concepts/workpads-and-resume)
- [Local Permissions](/docs/runs/local/permissions)
