---
title: "Skill Extensions"
description: "Add your team's own standing instructions to any PRFlow command without editing the plugin."
---

Teach a PRFlow command your repository's rules by committing a Markdown file that the command reads on every run.

## What a Skill Extension Is

A skill extension is a Markdown file in your repository whose text PRFlow adds to the end of a command's own instructions each time that command runs.

The file belongs to you, not to the plugin. A plugin update never overwrites it and never conflicts with it, in the same way that your `.prflow/config.json` stays yours across updates.

Settings in `.prflow/config.json` change values PRFlow already knows about. A skill extension adds instructions PRFlow could not know about, such as the name of your verification command or a rule about code that must never change.

<Warning>
  A skill extension has real authority over the run. Its text becomes instructions to an agent that can edit your repository, push commits, open pull requests and decide when work is finished. Anyone who can change the file can change how every later run behaves.

  Review and commit extension files through the same pull request process you use for code. Never put a token, password or other secret in one, because the file is committed to your repository.
</Warning>

## Where the File Goes

Put the file at `.prflow/skill-extensions/<command>.md`. Replace `<command>` with the command name without the `/prflow:` prefix.

For example, `/prflow:review` reads `.prflow/skill-extensions/review.md`.

Running [`/prflow:init`](/docs/getting-started/initialization) creates the directory and writes one commented example per command, named `<command>.md.example`. An example file is inert. It is a single Markdown comment, so it changes nothing even if you rename it by mistake. To activate it, rename it to `<command>.md` and replace the commented body with your own instructions.

Commit the file. Your team shares one copy, and cloud runs read it from the committed tree.

<Note>
  This directory was named `.prflow/prompt-extensions/` in an earlier release. If your repository still has it under the old name, everything keeps working: every command resolves `.prflow/skill-extensions/` first and falls back to a present `.prflow/prompt-extensions/`, printing a breadcrumb that names the old path. Running [`/prflow:init`](/docs/getting-started/initialization) (or re-running the installer, which runs the same scaffolder) renames the directory to `.prflow/skill-extensions/` for you, carrying every file across; when both directories already exist it renames nothing and tells you to merge them by hand.
</Note>

## Which Commands Read One

Every PRFlow command reads its own file. These are the commands documented on this site:

| Command | File it reads |
| --- | --- |
| [`/prflow:spec`](/docs/workflows/spec) | `.prflow/skill-extensions/spec.md` |
| [`/prflow:implement`](/docs/workflows/implement) | `.prflow/skill-extensions/implement.md` |
| [`/prflow:review`](/docs/workflows/review) | `.prflow/skill-extensions/review.md` |
| [`/prflow:review-and-fix`](/docs/workflows/review-and-fix) | `.prflow/skill-extensions/review-and-fix.md` and `.prflow/skill-extensions/fix.md` |
| [`/prflow:pr-description`](/docs/workflows/pr-description) | `.prflow/skill-extensions/pr-description.md` |
| [`/prflow:docs`](/docs/workflows/documentation) | `.prflow/skill-extensions/docs.md` |
| [`/prflow:retrospective-weekly`](/docs/workflows/retrospective-weekly) | `.prflow/skill-extensions/retrospective-weekly.md` |
| [`/prflow:init`](/docs/getting-started/initialization) | `.prflow/skill-extensions/init.md` |

`/prflow:review-and-fix` reads two files because its fix loop applies the code-review reception rules without running that command, so a rule you write once in `fix.md` reaches every fix pass. When the loop loaded `review-and-fix.md` with content and a fingerprint, the reviewer that checks each fix iteration's changes loads the file itself and applies it only when it loads a copy matching the loop's; otherwise it reports that check as not verified. Without that load the reviewer gets no extension, for example when the file is empty or [cannot be read](#when-the-file-cannot-be-read), or when your vendored PRFlow is too old to report the fingerprint, which the loop notes in its reflections.

<Note>
  The `fix` extension was renamed from an earlier name in a recent release. If you customized the extension under its previous name, it keeps applying across the upgrade: when `fix.md` is absent the loader reads your old file and prints a breadcrumb naming the exact file to rename to `fix.md`. Running [`/prflow:init`](/docs/getting-started/initialization) (and re-running the installer, which runs the same scaffolder) renames the file to `fix.md` for you. On a cloud run the base-branch materialization still finds the old file and warns. Renaming it yourself, or letting `init` do it, ends the transitional read-through. The [release notes](/release-notes) name the previous file.
</Note>

The focused documentation commands read their own files under the same rule: `docs-sync-internal.md`, `docs-sync-external.md`, `docs-release-notes.md`, `docs-verify.md`, `docs-bootstrap-internal.md` and `docs-bootstrap-external.md`. The review engine reads `requesting-code-review.md` for its final-pass reviewer.

## How the Text Reaches the Run

The command loads the file at the start of the run and appends its contents, word for word, to the end of its own instructions for that run only. Nothing is merged, summarized or rewritten.

Long commands reload the file when they enter a new phase, so your instructions stay in effect through a run that lasts an hour. `/prflow:implement` also checks the file again when it merges your base branch just before review, so an extension change merged meanwhile applies to the review. `/prflow:pr-description` is a single pass and loads it once.

Write the file as instructions, not as background reading. If you want a tool called, say so, because the agent acts on what the text tells it to do.

## Write One

A team keeps its checks behind one command and treats shipped database migrations as immutable. They commit this file.

```markdown
<!-- .prflow/skill-extensions/implement.md -->

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

Expected result on the next `/prflow:implement` run: the workpad's `Skill extension resolved` line shows the extension loaded (see [Check That It Was Applied](#check-that-it-was-applied)), the run uses `make verify` as its verification command, opens the pull request with a "Rollback" section and refuses to edit a shipped migration, proposing a new migration file instead. See [Tool Permissions](/docs/configuration/tool-permissions) for the grant format.

<Accordion title="Two headings the spec extension treats specially">
  `/prflow:spec` reads two headings in `.prflow/skill-extensions/spec.md` by name, in addition to using the whole file as instructions.

  A section headed exactly `## Audit dimensions` is added to the standard audit checklist. PRFlow applies it to its own draft before the first audit round, and each audit round's auditor receives it too. Use it to teach the drafter and the auditor the assumptions your issues must respect. When PRFlow cannot apply it to its own draft, for example because its self-audit instructions failed to load, it says so and the audit rounds still apply it; the file as a whole still applies as instructions.

  A section headed exactly `## Evidence axes` is passed to the pass that gathers evidence before the draft is written. Use it to name the kinds of evidence a draft must cover for your repository.

  A section runs from its heading line to the next line that starts with `## `. An extension without these headings changes nothing about those passes and still works as ordinary appended instructions. The scaffolded `spec.md.example` contains an inert sample of both headings.
</Accordion>

## Check That It Was Applied

Do not assume the extension was used. Confirm it:

1. Run the command.
2. For `/prflow:review`, `/prflow:review-and-fix`, `/prflow:pr-description` and `/prflow:fix`, read the command's output: it names the extension's resolved status — content was loaded, the file was absent or empty, or the status could not be established. Other commands do not report the status themselves when the extension loads or its file is absent or empty; `/prflow:implement` records it in its workpad (step 3). For what a failed load reports, see [When the File Cannot Be Read](#when-the-file-cannot-be-read).
3. For `/prflow:implement`, open the workpad comment on the issue. Its progress list carries a `Skill extension resolved` line for the `implement`, `review-and-fix` and `fix` extensions. The run cannot report itself complete while such a line is unresolved and unexplained. The `review` extension, and each reviewer's extension, is loaded by the review itself and has no line: when the review reports that one of them failed to load, was refused or could not be established, the run records that in the workpad's reflections; if that write fails, no workpad or pull request records the failed load.

On a cloud run the workflow also checks some extensions on its own, separately from what the run says about itself: `implement` for `/prflow:implement`, and for `/prflow:review`, `/prflow:review-and-fix` or `/prflow:pr-description` that command's extension plus `requesting-code-review` (for `/prflow:review`) or `fix` (for `/prflow:review-and-fix`). A review command's job fails with an error when one of those files is present but cannot be delivered; an implement job fails when the run finishes Complete, or successfully with no workpad, and the `implement` extension's arrival cannot be established. Everything else, on either tier, rests on the command's own reported status: a run that cannot establish that an extension arrived records that fact in a durable place (the workpad, the pull-request description, or the command's own output) rather than passing silently — except a failed `review` or reviewer extension load in an implement run, which reaches the workpad only when its reflection write lands (step 3).

## When the File Cannot Be Read

| Situation | What happens |
| --- | --- |
| The file is absent, or present but empty | Nothing is appended. The command behaves exactly as it does without an extension. This is not an error. |
| The file exists but cannot be delivered, such as a broken symlink, a directory in its place or a file the run cannot read | The load fails loudly with an error and the run reports it. A broken extension never disappears silently. |
| The client refuses the command that loads the file | The run reports the state as unestablished. It never records this as "no extension", because a refused load and an absent file are different facts. |

If a run reports an unestablished state, fix it before you trust the run's output. That run followed none of your house rules.

<Note>
  On cloud runs the `review`, `review-and-fix`, `pr-description`, `fix` and `requesting-code-review` extensions are read from a copy taken from the pull request's base branch, not from the branch under review. A change to one of those files takes effect after it merges. This stops a pull request from editing the instructions its own reviewer follows. See [Security](/docs/concepts/security).
</Note>

## Keep It Short

The extension's text is added to the run every time, so every line costs tokens on every run. Keep it to the rules that actually change what PRFlow does in your repository, and delete a rule once it stops being true.

Related pages: [Tool Permissions](/docs/configuration/tool-permissions) for granting the commands your extension names, and [Implementation Settings](/docs/configuration/implementation) for the values that are settings rather than instructions.
