---
title: "Working Directory"
description: "Understand how a local PRFlow run resolves the repository root, and what changes in a monorepo or a nested checkout."
---

Confirm which repository a local run will use before you start it, especially in a monorepo or a nested Git checkout.

## Check the Root First

PRFlow anchors its configuration to the Git root, not to the directory you are standing in. Run this before you start a command:

```bash
git rev-parse --show-toplevel
```

It prints one absolute path, such as `/Users/you/code/acme-api`. That path is the repository PRFlow will act on, and `.prflow/config.json` is read from it. If the printed path is not the repository you meant, move to the right directory before you start the command.

## Run From Any Subdirectory

PRFlow's configuration and prompt-extension readers resolve their default path from the Git root, so a command entered in `packages/web/` reads the same root `.prflow/config.json` and the same `.prflow/prompt-extensions/` files as a command entered at the top of the repository.

Bundled helper files are found relative to the helper itself, not relative to your current directory, so they resolve the same way from anywhere in the tree.

## The Nearest Git Root Wins

`git rev-parse --show-toplevel` returns the nearest enclosing Git root, which is not always the one you want. Watch for it in three layouts:

<AccordionGroup>
  <Accordion title="A Nested Repository Inside a Monorepo">
    A vendored or cloned repository inside your monorepo is its own Git root. A command started inside it anchors to that inner repository, and it will not see the monorepo's `.prflow/config.json`.
  </Accordion>
  <Accordion title="A Git Submodule">
    A submodule is a separate Git root for the same reason. Change to the parent checkout first if the parent is the repository you mean to work on.
  </Accordion>
  <Accordion title="Configuration Stored Below the Git Root">
    If your team stores `.prflow/` below the Git root, the default resolution will not find it. Where a helper offers an explicit configuration-path option, that option is honored exactly as written.
  </Accordion>
</AccordionGroup>

## Outside a Git Repository

Some helpers fall back to the current directory when no Git root can be found. That fallback is not enough for real work: issue, branch, workpad and pull-request workflows all depend on actual Git and GitHub state. Start those workflows from inside the intended checkout.

## Do Not Change Directory Mid-Run

<Warning>
  Do not run `cd` while a PRFlow command is in progress. In a cloud run the Bash working directory persists between tool calls and helper paths are repository-relative, so a directory change makes later helpers resolve against the wrong path. Locally it can select a different Git root or break project-specific test commands.
</Warning>

PRFlow's own commands are written to avoid a leading `cd` for this reason.

See [Local Runs](/docs/runs/local/index) for the rest of the local execution model.
