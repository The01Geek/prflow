---
title: "Command Problems"
description: "Fix an unknown command, failing GitHub calls, a command aimed at the wrong target and a denied verification command."
---

Match the symptom to an entry below, run its diagnostic command, then apply its fix.

<AccordionGroup>

<Accordion title="The command is unknown">

**Symptom:** the client answers that the command does not exist, or nothing happens when you send it.

Claude Code is the documented client, and the only syntax PRFlow uses is `/prflow:<skill>`. For example:

```
/prflow:implement 123
```

Check that the plugin is loaded:

```bash
claude plugin list
```

If `prflow` is missing or disabled, follow [Installation Problems](/docs/troubleshooting/installation). If it is loaded, run `/reload-plugins` and try again.

The older `/devflow:<skill>` spellings are still accepted, so an old habit or an old comment still works. They are permanent aliases, not a sign that something is out of date.

</Accordion>

<Accordion title="GitHub operations fail">

**Symptom:** the run reports that it cannot read the issue, open the pull request or post the review.

Check which account the GitHub CLI is using:

```bash
gh auth status
```

If no account is active, or the active one is the wrong account, sign in again:

```bash
gh auth login
```

Then confirm that account can reach the repository and do the specific thing PRFlow tried:

```bash
gh repo view
gh issue view <number>
gh pr view <number>
```

On Windows, also confirm the same bash session resolves the `gh` you signed in with. Run `which -a gh` and compare it against `DEVFLOW_GH` if you set that override.

</Accordion>

<Accordion title="The command is running on the wrong target">

**Symptom:** the run says the number is not an issue, not a pull request, or it works on something you did not mean.

Confirm what the number actually is before you send the command again:

```bash
gh issue view <number> --json number,title,state
gh pr view <number> --json number,title,state,headRefName
```

Then match the command to the target:

- `/prflow:implement <number>` takes an existing GitHub **issue**. In the cloud it answers a comment on an issue, never on a pull request.
- `/prflow:review <number>` takes a **pull request** and changes nothing. Use it when you want an assessment only.
- `/prflow:review-and-fix <number>` also takes a **pull request**, and it both reviews and fixes. It is not local-only: it is one of the three commands a fresh cloud installation answers from a pull-request comment, alongside `/prflow:review` and `/prflow:pr-description`.

In a comment on the pull request itself, send the review commands with no number. The run takes the pull request from the comment's own thread.

<Warning>
`/prflow:review-and-fix` edits files and pushes commits to the pull request's branch. `/prflow:review` never moves the working tree. If you wanted an opinion rather than a change, send `/prflow:review`.
</Warning>

</Accordion>

<Accordion title="Verification is blocked">

**Symptom:** the run stops and says a verification command it needed was not permitted. The command produced no output because it was refused before it ran.

Read the message for the exact command, then check whether that command is granted for the path you are on:

```bash
jq '.prflow_implement.allowed_tools' .prflow/config.json
```

An implementation run reads its extra grants from `prflow_implement.allowed_tools` in `.prflow/config.json`. Add the command's leading token and arguments there, using the tool syntax the file already shows, such as `"Bash(make:*)"`. If the tool also has to be installed on the runner, add its install step to the `setup` block.

`prflow_implement.allowed_tools` is the only setting that grants a verification command to an implementation run. `prflow.allowed_tools` grants commands to the light command path instead, and the two do not inherit from each other, so listing a tool in one does not make it available in the other.

<Warning>
A grant added by the same pull request does not apply to that pull request's own run. The workflow reads these settings from the default branch at the time the run is triggered, so the grant takes effect only after you merge it. Merge first, then start a new run.
</Warning>

If the command is granted and still fails, the cause is elsewhere. Install the missing repository dependency, correct the verification command in the issue, or fix the external service the command depends on.

A cloud implementation run must observe a verification command in its own environment. It does not accept a CI result in place of running the command, so a green pull-request check does not discharge a verification the run itself could not perform.

</Accordion>

</AccordionGroup>

## Related Articles

- [Command Reference](/docs/reference/command-reference)
- [Tool Permissions](/docs/configuration/tool-permissions)
- [Verification](/docs/concepts/verification)
- [Client Commands](/docs/runs/local/client-commands)
