---
title: "Implementation Problems"
description: "Recover an implement run that stops before it produces a finished pull request."
---

Match the stop you are looking at to an entry below, run its diagnostic command, then apply its fix.

<AccordionGroup>

<Accordion title="A declared issue dependency is still open">

**Symptom:** the run stops as Blocked before it creates a branch, and names an issue number the issue body mentions.

PRFlow reads the issue body for a declared prerequisite. Show every phrase it looks for:

```bash
gh issue view <number> --json body --jq .body | grep -inE "depends on #|must merge after #|blocked by #|follow-up to #|^[ >*-]*after #"
```

These are all the phrases that declare a blocking dependency, each followed by one or more issue numbers:

| Phrase | Example |
| --- | --- |
| `depends on` | `Depends on #123` |
| `must merge after` | `Must merge after #123` |
| `blocked by` | `Blocked by #123 — the schema has to land first` |
| `follow-up to` | `Follow-up to #123` |
| `after`, at the start of a line or bullet | `After #123 lands, do this` |

One phrase can name several issues at once, as in `blocked by #10 and #11`.

<Warning>
`follow-up to #123` reads like ordinary prose. People write it to record where the work came from, not to say the work is blocked, and PRFlow still treats it as a blocking dependency. If you meant provenance rather than ordering, reword it, for example to `this continues the work in #123`.
</Warning>

Check whether the named prerequisite is actually still open:

```bash
gh issue view <prerequisite> --json state,title
```

Close or merge the prerequisite, or correct the issue text. Then start the run again. A phrase that points the other way, such as `Blocks #123` or `Required by #123`, is read as an outbound relation and does not block the run.

If the run says a dependency could not be resolved, that is not the same as closed. Fix GitHub authentication or repository access, then retry.

</Accordion>

<Accordion title="PRFlow could not reproduce the bug">

**Symptom:** the run stops as Blocked on a bug issue, and the workpad records a reflection beginning `cannot reproduce:` followed by the obstacle it hit.

Reproduction is a hard gate for a bug issue. PRFlow will not plan a fix for a defect it has not seen happen, because a fix aimed at a guess is worse than no fix. It records the obstacle instead of inventing one.

Read what it recorded:

```bash
gh issue view <number> --comments
```

The workpad comment holds the obstacle. Then give the run what it was missing by editing the issue's `Current Behavior` section: the exact steps, the input that triggers the defect, the environment it happens on and the output you actually see against the output you expect. If the defect only happens in one environment, say which. If a fact genuinely cannot be established, write that down rather than leaving it out.

Start the run again once the issue carries reproduction steps a second person could follow.

</Accordion>

<Accordion title="The issue has no acceptance criteria">

**Symptom:** nothing fails. The run finishes and reports Complete, and the workpad's acceptance-criteria section reads `_(none provided in issue body)_`.

Check whether the issue has the section at all:

```bash
gh issue view <number> --json body --jq .body | grep -n "^## Acceptance Criteria"
```

<Warning>
With no criteria, the acceptance-criteria gate has nothing to check and passes trivially. A Complete on such a run means the run finished, not that the requested outcome was verified. Do not read it as evidence.
</Warning>

Write acceptance criteria into the issue before you run it. Each one is a testable statement about observable behavior, written as a markdown checkbox:

```markdown
## Acceptance Criteria

- [ ] Running `make check` on a repository with no config prints the missing-config remedy and exits 1
- [ ] An existing config is left byte-identical
```

Then start the run again. [Create an issue](/docs/workflows/create-issue) writes this section for you.

</Accordion>

<Accordion title="Acceptance criteria are written as prose or a numbered list">

**Symptom:** the issue clearly has criteria, but the run behaves as though it has none, and its workpad carries a reflection about the issue's accuracy that you did not cause.

PRFlow reads a criterion only when it is a markdown checkbox list item: `- [ ]`, `- [x]`, `* [ ]` or `* [x]`. Bold paragraphs such as `**AC1 — ...**` and numbered lists such as `1. ...` parse to zero items, exactly as an absent section would.

Count the checkbox rows in the issue:

```bash
gh issue view <number> --json body --jq .body | grep -cE "^[*-] \[[ xX]\]"
```

A count of 0 with a visible criteria section is this case. The run does not stop: it hand-extracts the criteria and records that it had to, which is the reflection you are reading. That reflection is about the issue's shape, not about your code.

Rewrite each criterion as a checkbox row, then start the run again so the machine-readable path is used.

</Accordion>

<Accordion title="The working tree has uncommitted changes">

**Symptom:** a local run stops as Blocked before it creates a feature branch, and the workpad records the uncommitted tracked files it found and asks you to commit or stash them.

PRFlow reaches this point still on your base branch, before any feature branch exists. Rather than sweep your uncommitted changes into a stray commit on the base branch, it stops and leaves your tree untouched.

List what it found:

```bash
git status --porcelain --untracked-files=no
```

<Warning>
This is a terminal stop, and it moves nothing. Your changes are still in your working tree exactly as you left them.
</Warning>

Commit those changes on a branch of your own, or stash them:

```bash
git stash
```

Then start the run again. Untracked files do not trigger this stop; only tracked changes do.

</Accordion>

<Accordion title="The feature branch is checked out in another worktree">

**Symptom:** the run stops as Blocked and reports that the branch is checked out in another linked worktree. The underlying git error reads `fatal: '<branch>' is already used by worktree at '<path>'`. Older git versions word it `already checked out at`.

List your worktrees and find the one holding the branch:

```bash
git worktree list
```

<Warning>
This is a terminal stop, not a switch. PRFlow shares the working tree it was started in and cannot move into another one, so it refuses rather than continuing on the wrong branch. It makes no change to your history when it stops.
</Warning>

Resolve it yourself, then start the run again:

```bash
git worktree remove <path>
```

Finish and remove the other worktree, or move its work elsewhere. Use `git worktree remove --force` only when you are sure that worktree holds nothing you want.

</Accordion>

<Accordion title="The branch-state check refuses to adopt the branch">

**Symptom:** the run stops before implementation and says it could not confirm that the existing commits on the feature branch belong to this issue's earlier work.

The run compares the feature branch against the base branch. List the commits that are on the branch but not on the base:

```bash
git log --oneline origin/<base>..<branch>
```

A refusal means those commits could not be shown to be the run's own prior work. That usually happens when the branch was created from an unpushed local commit, so it carries unrelated history that every later step would treat as part of this change.

Check the workpad's branch and pull-request links, and confirm the remote branch still exists and points where you expect:

```bash
git ls-remote origin <branch>
```

<Warning>
Do not clear the refusal by deleting the commits you do not recognize. Reconcile or publish that history on purpose first. The check is read-only and has moved nothing.
</Warning>

</Accordion>

<Accordion title="Every required change is under .github/workflows/">

**Symptom:** a cloud run stops as Blocked rather than opening an empty pull request, and names workflow files.

The built-in token cannot push a change to a workflow file. When every acceptance criterion needs that capability, the run has nothing it can ship.

Check what the issue requires:

```bash
gh issue view <number> --json body --jq .body | grep -n ".github/workflows/"
```

Either run the issue with a human credential, or configure the optional GitHub App with both `Contents: write` and `Workflows: write`. See [Cloud Setup](/docs/runs/cloud/setup). If only part of the work is workflow-bound, PRFlow can defer that part and ship the rest.

</Accordion>

<Accordion title="A verification command was denied">

**Symptom:** the run stops and names a command it needed but was not allowed to run.

Check the grant list for the implementation path:

```bash
jq '.prflow_implement.allowed_tools' .prflow/config.json
```

The full fix, including why a grant added by the same pull request does not apply to that pull request's own run, is in [Command Problems](/docs/troubleshooting/commands).

</Accordion>

<Accordion title="The run stopped midway">

**Symptom:** the workpad shows a status that is not Complete, and no finished pull request exists.

Read the workpad and the run it came from:

```bash
gh issue view <number> --comments
gh run view <run-id> --log-failed
```

The workpad holds the branch link, the pull-request link and the run's own record of where it stopped. Fix the cause it names, then post the original implement comment again. The new run reuses the same workpad and adopts any checkpoint that was already pushed.

A run interrupted before its first branch checkpoint may have no recoverable code. A cancelled run is terminal and is never resumed for you. See [Cloud Recovery](/docs/runs/cloud/recovery).

</Accordion>

</AccordionGroup>

## Related Articles

- [Implement](/docs/workflows/implement)
- [Workpads and Resume](/docs/concepts/workpads-and-resume)
- [Verification](/docs/concepts/verification)
- [Cloud Recovery](/docs/runs/cloud/recovery)
