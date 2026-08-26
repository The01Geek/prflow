---
title: "Prompt Extensions"
description: "Add your team's own standing instructions to any PRFlow command without editing the plugin."
---

Teach a PRFlow command your repository's rules by committing a Markdown file that the command reads on every run.

## What a Prompt Extension Is

A prompt extension is a Markdown file in your repository whose text PRFlow adds to the end of a command's own instructions each time that command runs.

The file belongs to you, not to the plugin. A plugin update never overwrites it and never conflicts with it, in the same way that your `.prflow/config.json` stays yours across updates.

Settings in `.prflow/config.json` change values PRFlow already knows about. A prompt extension adds instructions PRFlow could not know about, such as the name of your verification command or a rule about code that must never change.

<Warning>
  A prompt extension has real authority over the run. Its text becomes instructions to an agent that can edit your repository, push commits, open pull requests and decide when work is finished. Anyone who can change the file can change how every later run behaves.

  Review and commit extension files through the same pull request process you use for code. Never put a token, password or other secret in one, because the file is committed to your repository.
</Warning>

## Where the File Goes

Put the file at `.prflow/prompt-extensions/<command>.md`. Replace `<command>` with the command name without the `/prflow:` prefix.

For example, `/prflow:review` reads `.prflow/prompt-extensions/review.md`.

Running [`/prflow:init`](/docs/getting-started/initialization) creates the directory and writes one commented example per command, named `<command>.md.example`. An example file is inert. It is a single Markdown comment, so it changes nothing even if you rename it by mistake. To activate it, rename it to `<command>.md` and replace the commented body with your own instructions.

Commit the file. Your team shares one copy, and cloud runs read it from the committed tree.

## Which Commands Read One

Every PRFlow command reads its own file. These are the commands documented on this site:

| Command | File it reads |
| --- | --- |
| [`/prflow:create-issue`](/docs/workflows/create-issue) | `.prflow/prompt-extensions/create-issue.md` |
| [`/prflow:implement`](/docs/workflows/implement) | `.prflow/prompt-extensions/implement.md` |
| [`/prflow:review`](/docs/workflows/review) | `.prflow/prompt-extensions/review.md` |
| [`/prflow:review-and-fix`](/docs/workflows/review-and-fix) | `.prflow/prompt-extensions/review-and-fix.md` and `.prflow/prompt-extensions/receiving-code-review.md` |
| [`/prflow:pr-description`](/docs/workflows/pr-description) | `.prflow/prompt-extensions/pr-description.md` |
| [`/prflow:docs`](/docs/workflows/documentation) | `.prflow/prompt-extensions/docs.md` |
| [`/prflow:retrospective-weekly`](/docs/workflows/retrospective-weekly) | `.prflow/prompt-extensions/retrospective-weekly.md` |
| [`/prflow:init`](/docs/getting-started/initialization) | `.prflow/prompt-extensions/init.md` |

`/prflow:review-and-fix` reads two files because its fix loop applies the code-review reception rules without running that command, so a rule you write once in `receiving-code-review.md` reaches every fix pass.

The focused documentation commands read their own files under the same rule: `docs-sync-internal.md`, `docs-sync-external.md`, `docs-release-notes.md`, `docs-verify.md`, `docs-bootstrap-internal.md` and `docs-bootstrap-external.md`. The final-pass reviewer inside the review engine reads `requesting-code-review.md`.

## How the Text Reaches the Run

The command loads the file at the start of the run and appends its contents, word for word, to the end of its own instructions for that run only. Nothing is merged, summarized or rewritten.

Long commands reload the file when they enter a new phase, so your instructions stay in effect through a run that lasts an hour. `/prflow:pr-description` is a single pass and loads it once.

Write the file as instructions, not as background reading. If you want a tool called, say so, because the agent acts on what the text tells it to do.

## Write One

A team keeps its checks behind one command and treats shipped database migrations as immutable. They commit this file.

```markdown
<!-- .prflow/prompt-extensions/implement.md -->

## Verification

Run `make verify` before reporting any acceptance criterion as satisfied. It runs the unit tests, the type checker and the linter together. Do not substitute a single test file for it.

## Files that must never change

Never edit a file under `db/migrations/`. A migration that has shipped is immutable. If the work needs a schema change, add a new migration file instead.

## Pull request description

Always include a "Rollback" section that says how to undo the change in production.
```

For a cloud run, also grant the command you named. Installing a tool or naming it in an extension does not permit the agent to run it:

```json
{
  "prflow_implement": {
    "allowed_tools": [
      "Bash(make verify:*)"
    ]
  }
}
```

Expected result on the next `/prflow:implement` run: the run reports that the extension loaded, uses `make verify` as its verification command, opens the pull request with a "Rollback" section and refuses to edit a shipped migration, proposing a new migration file instead. See [Tool Permissions](/docs/configuration/tool-permissions) for the grant format.

<Accordion title="Two headings the create-issue extension treats specially">
  `/prflow:create-issue` reads two headings in `.prflow/prompt-extensions/create-issue.md` by name, in addition to using the whole file as instructions.

  A section headed exactly `## Audit dimensions` is passed to the pass that audits the draft issue, added to its standard checklist. Use it to teach the auditor the assumptions your issues must respect.

  A section headed exactly `## Evidence axes` is passed to the pass that gathers evidence before the draft is written. Use it to name the kinds of evidence a draft must cover for your repository.

  A section runs from its heading line to the next line that starts with `## `. An extension without these headings changes nothing about those passes and still works as ordinary appended instructions. The scaffolded `create-issue.md.example` contains an inert sample of both headings.
</Accordion>

## Check That It Was Applied

Do not assume the extension was used. Confirm it:

1. Run the command.
2. Read the command's own output. It reports the extension's resolved status: content was loaded, the file was absent or empty, or the status could not be established.
3. For `/prflow:implement`, open the workpad comment on the issue. Its progress list carries a `prompt extension resolved` line for each extension the run loaded. The run cannot report itself complete while such a line is unresolved and unexplained.

On a cloud run — whether `/prflow:implement` or an automated review — the workflow also checks arrival on its own, separately from what the run says about itself. If the repository has an extension whose text never reached the run, the job fails with an error rather than finishing quietly. On the local tier and on a run with no workpad, the same check is made from the command's own reported status: a run that cannot establish that the extension arrived records that fact in a durable place (the workpad, the pull-request description, or the command's own output) rather than passing silently.

## When the File Cannot Be Read

| Situation | What happens |
| --- | --- |
| The file is absent, or present but empty | Nothing is appended. The command behaves exactly as it does without an extension. This is not an error. |
| The file exists but cannot be delivered, such as a broken symlink, a directory in its place or a file the run cannot read | The load fails loudly with an error and the run reports it. A broken extension never disappears silently. |
| The client refuses the command that loads the file | The run reports the state as unestablished. It never records this as "no extension", because a refused load and an absent file are different facts. |

If a run reports an unestablished state, fix it before you trust the run's output. That run followed none of your house rules.

<Note>
  On cloud runs the `review`, `review-and-fix`, `pr-description`, `receiving-code-review` and `requesting-code-review` extensions are read from a copy taken from the pull request's base branch, not from the branch under review. A change to one of those files takes effect after it merges. This stops a pull request from editing the instructions its own reviewer follows. See [Security](/docs/concepts/security).
</Note>

## Keep It Short

The extension's text is added to the run every time, so every line costs tokens on every run. Keep it to the rules that actually change what PRFlow does in your repository, and delete a rule once it stops being true.

Related pages: [Tool Permissions](/docs/configuration/tool-permissions) for granting the commands your extension names, and [Implementation Settings](/docs/configuration/implementation) for the values that are settings rather than instructions.
