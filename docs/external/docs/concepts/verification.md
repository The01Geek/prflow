---
title: "How PRFlow Verifies a Change"
description: "Understand what recorded verification evidence means, which results count and what happens when a check cannot run."
---

Understand what PRFlow means when it says a run recorded verification evidence.

PRFlow does not decide for itself whether a change works. It runs your repository's own checks, reads what they returned and records that. Everything on this page follows from one rule: **a result PRFlow did not establish is unknown, and unknown never counts as a pass.**

## PRFlow Runs Your Checks, Not Its Own

PRFlow has no test framework of its own. It runs the tests, linters and build commands your repository already has, in the environment the run is executing in, using commands your repository configures and permits.

That means two things:

- The quality of PRFlow's verification is the quality of your test suite. PRFlow can only report what your checks are able to detect.
- PRFlow can only run a command you have permitted. See [Tool Permissions](/docs/configuration/tool-permissions).

A cloud implementation run can execute a command only if the run's permitted tool list covers it. `prflow_implement.allowed_tools` is where you add your repository's own commands. Here is how you permit a test command:

```json
{
  "prflow_implement": {
    "allowed_tools": [
      "Bash(npm test:*)",
      "Bash(npm run lint:*)"
    ]
  }
}
```

With that in place, a run can execute `npm test` and `npm run lint` and record what they returned. Without it, the same commands are refused before they run.

<Note>
  `prflow_implement.allowed_tools` covers implementation runs. It does not inherit from `prflow.allowed_tools`, which covers the general cloud command workflow. Set the one that matches the runs you want to change.
</Note>

## A Focused Check Is Not a Finished Job

While PRFlow is iterating on a change, it runs the narrow check that covers the code it just touched. That is the right thing to do mid-change: it is fast and it tells the run whether the last edit worked.

A focused check is evidence **for that iteration**. It is not evidence that the change is finished, because it only ever covered the part of the repository it was selected for. Before a run can report `Complete`, it needs a result that covers the full set your repository expects, not the slice it happened to iterate on.

<Warning>
  If you read a run's evidence and see only a narrow test file, that is iteration evidence. It does not tell you the whole suite passed.
</Warning>

## Unknown Is Never a Pass

This is the rule that decides most of PRFlow's behavior around verification. Each of these is an **unknown** result, and none of them lets a run claim its work is verified:

| Result | Why it is not a pass |
| --- | --- |
| The check was skipped | Nothing ran, so nothing was established. |
| The check could not run | A missing tool, a refused command or a broken environment produced no verdict. |
| The check is still running | There is no result yet. |
| The check reported nothing at all | A refused command can produce no output, which looks the same as silence. |
| The result could not be read | An unreadable or incomplete record is not a verdict. |

A run that ends with any of those in place of a required result stops and says so. It does not round the unknown down to a pass and it does not round it up to a failure. It reports that the result was never established.

<Accordion title="Why silence is treated as unknown rather than success">
  A command that a permission boundary refuses does not print an error the way a failing test does. It simply produces nothing. If a run treated "no output" as "no problems", every refused check would read as a clean pass, and the runs most likely to be under-verified would be the ones reporting the cleanest results. Treating silence as unknown is what makes that failure visible instead of invisible.
</Accordion>

## When a Needed Command Is Not Permitted

If verifying an acceptance criterion requires a command the run is not permitted to execute, PRFlow does not skip the criterion and does not quietly mark it satisfied.

The run stops. It records `Blocked` on the workpad, names the criterion it could not verify and names the permission setting you would add to unblock it. On the workpad you see:

```markdown
**Status:** 👎 Blocked
```

with the recorded cause in the run's notes. Add the command to the relevant `allowed_tools` list and run the command again.

<Tip>
  A missing tool or an environment gap is treated the same way. It is a reason to stop and ask a person, not a reason to call the criterion post-merge work.
</Tip>

## Continuous Integration Is a Different Gate

Your CI is the check a person reads before merging. It runs on the pull request, under your branch protection rules, on your infrastructure. PRFlow does not merge and does not tick anything on your behalf there. See [Human Control](/docs/concepts/human-control).

CI is **not** a substitute for the run verifying its own work. An implementation run has to establish its own result while it is still working, because a run that outsources its verification to a later CI job is reporting on a change it never checked. When the run finishes, both signals exist for you: the evidence the run recorded, and CI's independent result on the pushed commit.

<Note>
  A cloud implementation run never waits for CI, polls it or cites it as its own test evidence. It verifies in its own environment and leaves CI to you.
</Note>

## What the Evidence Looks Like

Verification evidence is recorded on the workpad, alongside the run's other progress. The `Review` section of the progress checklist shows the gate that consumes it:

```markdown
## Progress
- [ ] **Review**
  - [x] `/simplify`
  - [x] `review-and-fix`
  - [ ] acceptance-criteria gate
```

The acceptance-criteria gate is where verification evidence is actually spent. Every in-scope acceptance criterion must be supported by a passing check, a documented manual check or a code reference before the run may finish. A criterion that could not be established blocks exactly the same way a criterion that failed blocks.

A criterion that genuinely needs a real deployed environment is the one exception. It is tagged as post-merge work, left unticked and surfaced in the pull-request description for you to verify after merging. A criterion that is merely awkward to verify does not qualify.

## What This Does Not Promise

- Passing checks mean your checks passed. They do not mean the change is correct.
- Verification evidence cannot show a defect your test suite has no way to detect.
- The run environment can differ from production.
- A recorded pass is a record of what a command returned at one point in time on one commit.

## Related Documentation

- [The PRFlow Lifecycle](/docs/concepts/lifecycle)
- [Workpads and Resume](/docs/concepts/workpads-and-resume)
- [The Review System](/docs/concepts/review-system)
- [Tool Permissions](/docs/configuration/tool-permissions)
- [Implement an Issue](/docs/workflows/implement)
