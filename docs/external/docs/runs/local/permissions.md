---
title: "Local Permissions"
description: "Grant a local PRFlow run only the repository, Git and GitHub access it needs."
---

Approve the tool access a local PRFlow run asks for, and keep each grant as narrow as the workflow allows.

A local run has no allowlist of its own. It uses whatever Claude Code lets it use, so your answers to the permission prompts are the boundary. The exact prompt wording and the options for remembering an answer come from Claude Code, not from PRFlow.

## Match the Grant to the Workflow

<Tabs>
  <Tab title="Read-Only Review">
    `/prflow:review` inspects but does not change your code. It normally needs:

    - Read access to files inside the target repository.
    - Git history, status and diffs.
    - Pull-request data through the GitHub CLI.
    - The repository's own verification commands, such as its test and lint commands.

    It does not need write access to your files.
  </Tab>
  <Tab title="Implementation and Fixing">
    `/prflow:implement` and `/prflow:review-and-fix` change code. On top of the read-only set they need:

    - Write access to files inside the target repository.
    - Permission to create a branch, commit and push.
    - Authenticated `gh` commands for the issue or pull request being worked on.
  </Tab>
</Tabs>

## Keep Grants Narrow

- Prefer a specific command such as `make test`, `npm test` or `cargo test` over unrestricted shell access.
- Limit filesystem access to the target repository unless a known dependency lives somewhere else.
- Grant GitHub operations for the current issue or pull request rather than broad administrative access.
- Treat `sudo`, raw shell evaluation and writes outside the repository as separate, high-risk decisions.
- Review a persistent or project-wide grant more carefully than a one-time approval.

<Note>
  Declining a tool the run needs is a safe outcome. The run reports the missing verification or stops with a recorded blocker instead of reporting unobserved work as validated.
</Note>

## Cloud Allowlists Are a Different Boundary

Cloud runs cannot ask a person anything, so they read their tool allowlist from `.prflow/config.json`:

```json
{
  "prflow": {
    "allowed_tools": []
  },
  "prflow_implement": {
    "allowed_tools": []
  }
}
```

`prflow.allowed_tools` applies to the comment commands, and `prflow_implement.allowed_tools` applies to issue implementation. The two lists are independent. Adding an entry to one does not add it to the other.

These lists never replace Claude Code's own prompts. A local run still asks you, whatever `.prflow/config.json` contains. Review both boundaries in a repository that supports local and cloud runs. See [Tool Permissions](/docs/configuration/tool-permissions).

## Check What Actually Ran

Before you merge, read the workpad and the pull request for any command that was denied, skipped or unavailable. A review verdict narrows risk only to the extent that the evidence behind it was actually observed.

See [Verification](/docs/concepts/verification) for how a run records its evidence, and [Human Control](/docs/concepts/human-control) for the wider approval and merge boundaries.
