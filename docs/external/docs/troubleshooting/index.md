---
title: "Troubleshooting"
description: "Find the PRFlow error you are seeing and the command that fixes it."
---

Start with the first symptom you can see, then open the page that covers it.

<CardGroup cols={2}>
  <Card title="Installation Problems" icon="download" href="/docs/troubleshooting/installation">
    PRFlow commands do not appear, a preflight tool is missing, Python is too old or the installer preserved a file.
  </Card>
  <Card title="Command Problems" icon="terminal" href="/docs/troubleshooting/commands">
    The command is unknown, GitHub operations fail, the command runs on the wrong target or a verification command is denied.
  </Card>
  <Card title="Implementation Problems" icon="hammer" href="/docs/troubleshooting/implementation">
    An implement run stops before it opens a pull request: a declared dependency, a bug it cannot reproduce, missing acceptance criteria or a branch it cannot adopt.
  </Card>
  <Card title="Review Problems" icon="magnifying-glass" href="/docs/troubleshooting/review">
    A review cannot find the pull request, rejects over a documentation line, reports unverified coverage or delivers no verdict.
  </Card>
  <Card title="Configuration Problems" icon="gear" href="/docs/troubleshooting/configuration">
    `.prflow/config.json` is missing or invalid, a setting is ignored, an override does nothing or a change is not yet in effect.
  </Card>
  <Card title="Cloud-Run Problems" icon="cloud" href="/docs/troubleshooting/cloud-runs">
    A comment did not start a run, the actor was declined, model authentication failed, the job is queued or vendoring failed.
  </Card>
</CardGroup>

## Report a Problem

Run `/prflow:help` first. It checks your PRFlow version, setup and the failing run, tells you whether the cause is your setup or a likely PRFlow bug, and for a likely bug writes a report under `.prflow/tmp/help/` holding the version, operating system, command, local or cloud and the smallest error excerpt. For a cloud run it also saves the failed run's log in that folder, whatever the verdict. Review the report and remove credentials, prompt text and private repository content before you share it.

## Related Articles

- [Command Reference](/docs/reference/command-reference)
- [Glossary](/docs/reference/glossary)
- [Cloud Recovery](/docs/runs/cloud/recovery)
