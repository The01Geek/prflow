---
title: "Initialization"
description: "Scaffold and refresh the PRFlow configuration for one repository."
---

Create repository-specific PRFlow configuration by running the `init` skill once in each repository.

Initialization is separate from plugin installation. Run it after you install PRFlow and again after each update, so new configuration keys and new prompt-extension examples reach the repository. Local runs work on built-in defaults without it, so treat it as recommended rather than required.

## Run It

Open Claude Code anywhere inside the repository and enter:

```text
/prflow:init
```

The skill resolves the repository root itself, so the subdirectory you happen to be in does not matter.

### What You See

The skill runs a scaffolder and then a dependency preflight, and relays their output. A first run in a repository that has no PRFlow configuration prints lines like these:

```
devflow-scaffold: scaffolded /path/to/repo/.prflow/config.json — every value has a working default; edit it only to customize
devflow-scaffold: wrote /path/to/repo/.prflow/.gitignore (ignores ephemeral .prflow/tmp/ scratch)
devflow-scaffold: created/backfilled 18 prompt-extension example(s) in /path/to/repo/.prflow/prompt-extensions/ (rename <skill>.md.example to <skill>.md to activate)
devflow preflight: all dependencies present.
```

The paths are your repository's, and the number of examples matches the number of skills in the release you installed. A repository that already has a config prints `keeping existing …` instead, followed by a backfill line when the release added new keys.

### Files That Appear

```
.prflow/
  config.json                       your settings — every value has a working default
  config.schema.json                the schema your editor validates config.json against
  .gitignore                        ignores the ephemeral .prflow/tmp/ scratch directory
  prompt-extensions/
    implement.md.example            one inert example per skill
    review.md.example
    …
.claude/
  settings.json                     the project marketplace registration
```

Nothing here is committed for you. Initialization creates no Git commit on any path.

## What Initialization Writes

<Accordion title="Configuration and schema">
  - Creates `.prflow/config.json` from the shipped example when the file is absent.
  - Backfills newly added keys at any nesting depth when the file already exists. Your values always win, and arrays you tuned, such as tool allowlists, are left alone.
  - Refreshes `.prflow/config.schema.json` to the schema of the release you installed, so your editor validates against the current field set.
</Accordion>

<Accordion title="Prompt-extension examples">
  - Adds a commented `<skill>.md.example` file for each skill when that example is absent, so you can see which skills accept a consumer extension.
  - The `.example` suffix keeps every scaffolded file inert. Rename it to `<skill>.md` to activate it.
  - Never overwrites an existing example or a live extension you wrote.

  See [Prompt Extensions](/docs/configuration/prompt-extensions) for what these files do.
</Accordion>

<Accordion title="Detected tools and setup commands">
  - Detects Node, Go, Rust, Java, Ruby, PHP, .NET, Make and Docker markers.
  - Merges the matching build, test and lint tools into the three tool allowlists, and adds the install commands that go with the lockfiles it finds.
  - Reads the repository for services, runtime versions and project-specific build or verification commands that marker detection cannot infer, and proposes those as well.

  The merge is additive and idempotent. Re-running picks up tooling you added since the last run without removing custom entries and without creating duplicates. See [Tool Permissions](/docs/configuration/tool-permissions).
</Accordion>

<Accordion title="The project marketplace registration">
  Initialization deep-merges the PRFlow marketplace registration into the project `.claude/settings.json`. The registration enables `prflow@devflow-marketplace` and tracks the marketplace repository's default branch with `autoUpdate: true`.

  This write happens immediately, with no separate confirmation. It lands in a committed project file, so anyone who clones the repository inherits it, and because the registration is unpinned a change on the marketplace's default branch changes what runs in the editor. Review it before you commit.
</Accordion>

<Accordion title="Other checks">
  - Runs the dependency preflight for Git, a runnable GitHub CLI, `jq`, Python 3.11 or newer and PyYAML. Authentication is a separate `gh auth status` check.
  - Creates the reserved `PRFlow` GitHub label, on a best-effort basis.
  - Looks for shared project-memory files such as `CLAUDE.md` and reports suggestions. It never edits them.
</Accordion>

<Warning>
  The repository scaffold is written before the dependency preflight runs. A missing tool is reported, but it does not roll back `.prflow/` or any other change that already succeeded. Install the missing tool before you run implementation or review.
</Warning>

## Older Repositories Are Migrated First

Initialization is also where a repository that predates the PRFlow rename is moved to the current layout. Before it scaffolds anything, the skill checks whether the repository still keeps its state in `.devflow/` and, if so, runs the migration.

The migration moves the state directory, the vendored plugin path, the configuration keys and the workflow bodies that name them. All of those move together or not at all. If any precondition fails, the migration refuses and leaves the repository byte-for-byte unchanged, then reports what blocked it. Initialization continues either way.

Read [Migrate from DevFlow](/docs/getting-started/migrate-from-devflow) before you review that larger diff.

## Optional Guided Setup

Initialization can offer to do more than scaffold files. Every offer below asks first, and declining changes nothing that already succeeded.

- **Create internal documentation.** If the repository has no developer documentation, the skill explains what internal and external documentation are, why written documentation makes later runs cheaper, and offers to create the internal set for you. On your explicit consent it dispatches one agent that writes only under the internal documentation location and runs no version-control command. If you decline, it prints the command so you can run it yourself. It never runs the external bootstrap, and it commits nothing.
- **Sweep remaining product-name references.** After a successful rename migration, the skill can offer to update remaining `DevFlow` product-name mentions in your own files. See the privacy note in [Migrate from DevFlow](/docs/getting-started/migrate-from-devflow) before accepting.

## Review and Commit the Result

<Steps>
  <Step title="Read the Full Diff">
    Initialization writes files but never commits them. Look at every change before you decide what to keep.
  </Step>
  <Step title="Check the Four Paths That Matter">
    | **Path** | **What to Review** |
    | --- | --- |
    | `.prflow/config.json` | Detected setup commands, service configuration and tool permissions. |
    | `.prflow/config.schema.json` | The refreshed schema from the release you installed. |
    | `.prflow/prompt-extensions/*.md.example` | Newly added examples. They stay inert until you rename them. |
    | `.claude/settings.json` | The unpinned, auto-updating marketplace registration that your collaborators inherit. |
  </Step>
  <Step title="Tighten the Tool Allowlists">
    Grant enough access for PRFlow to run your real build and test commands, and prefer narrow patterns over broad ones. A reviewer that cannot run your test command will decline to judge anything that depends on it. See [Tool Permissions](/docs/configuration/tool-permissions).
  </Step>
  <Step title="Commit What Your Team Should Share">
    Commit the repository files through your normal review process. Do not commit a change to your user-global `~/.claude/settings.json`, which is personal and lives outside the repository.
  </Step>
</Steps>

## Next Steps

<CardGroup cols={2}>
  <Card title="First Run" icon="rocket" href="/docs/getting-started/first-run">
    Turn a real issue into a review-ready pull request.
  </Card>
  <Card title="Settings Reference" icon="sliders" href="/docs/configuration/settings">
    Every key in `.prflow/config.json`, with its default.
  </Card>
</CardGroup>
