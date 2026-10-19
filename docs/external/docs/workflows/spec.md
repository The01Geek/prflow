---
title: "Create an Issue"
description: "Turn a rough request into a grounded GitHub issue with decided behavior."
---

Use this workflow when you want work recorded rather than built now. Invoke it as `/prflow:spec` (the preferred name) or `/prflow:create-issue` (a permanent alias) — both run the same pipeline.

It creates one issue or [widens an open issue](#widening-an-existing-issue) that covers the work. Interactive runs require your approval of the final draft; [non-interactive filing](#non-interactive-filing) has narrower conditions. Unresolved decisions remain visible in the draft. When the initial code and documentation checks show every reported failure is gone, choosing *No change — file nothing* ends the run with that evidence and no issue.

## Run It

In an interactive session:

<Steps>
  <Step title="Describe the work in your own words">
    ```text
    /prflow:spec Prevent duplicate release comments when a workflow retries
    ```

    A short feature idea, bug report or improvement is enough. Say who is affected, what outcome you want and anything that must not change, when you know them.
  </Step>
  <Step title="Answer the questions">
    PRFlow reads the repository and documentation, then asks about unresolved scope, behavior, dependencies and verification, always including which implementation approach to take. It leaves other decisions to the implementer when they can clearly be made from your request and the codebase, unless each outcome in a complete set must be specified.

    Before the implementation-approach question, PRFlow checks each option against the risks and constraints it recorded while reading the repository, and for facts it never confirmed, and the question names the ones that bear on each option. The question shows each fact the check found unconfirmed as not confirmed. When the independent check cannot run or returns an incomplete or malformed result, PRFlow makes the check itself and the question says the independent check did not run. After you pick, PRFlow asks the approach question again when later evidence shows, for example, that a fact the question stated was wrong or that the chosen option adds a stop or `Blocked` outcome the question never mentioned; picking a different option then redrafts the issue.

    Also before that question, PRFlow walks each option through each reported case your request says the fix exists to change and, for a proposed rule, each case class the rule's own wording distinguishes, for example both sides of a condition it states. It reads each case's facts and reports a case that fails the walk, for example one the option would not fix or would wrongly change, where possible while you can still pick a different design. A failure the chosen design keeps is stated in the drafted issue, marked unverified when no read confirms it.

    Other questions that mark an option `(Recommended)` also name evidence PRFlow already read or recorded that argues against that option, against a premise the question states, or for an option it does not recommend, for example a comment on your issue, so you can weigh it before you choose. PRFlow does not read anything new to find it.

    Questions wait for answers that determine whether or how they should be asked. Independent, ready questions can share a batch. For a bug report, PRFlow collects the trigger, actual and expected behavior, and environment.

    PRFlow also asks which meaning you intend when a word in your request means something different in the repository docs or code it has read, or could name more than one thing there, and the difference changes, or may change, what gets built. It does not ask when your request already states its meaning and names the repository meaning it replaces. A word that means the same thing in your request and your repository costs no question.

    Before excluding a case you requested, PRFlow reuses your agreement or asks, explaining the remaining work and known tracking status. Declining keeps the case in scope; silence pauses the interactive run.

    Answering "you decide" or "I don't know" makes PRFlow research the question and re-ask it with each option's pros and cons and, where the evidence supports one, a recommendation. A second such reply selects the recommendation and tells you why, or leaves the question in Blocked when there is no recommendation. Two choices stay conservative: file a new issue instead of widening one, and retain a requested case instead of excluding it. "You decide" or "I don't know" on a question PRFlow recognizes as one only you can answer, such as your release plans, sends it to Blocked without research or a re-ask; when unsure, it researches.

    Saying "just create it", or exhausting the question budget, leaves unresolved scope in Blocked; an unbuildable core prompts one more question before that happens. Non-interactive runs record unresolved scope there directly.

    If nobody can establish a fact, PRFlow records it as unestablished rather than guessing. That includes, for example, a fact resting on lines that a `head -30` PRFlow ran never printed, when PRFlow neither read those lines in full nor counted the matches with nothing cut.
  </Step>
  <Step title="Review the saved draft">
    PRFlow writes the draft to a file and shows you its path, and saves the supporting investigation record beside it and shows that path too, or says the record is empty. It prints the complete title and body, followed by the record, in chat when you choose *print the full draft in chat* at the decision question below, and unasked when it cannot show you a saved draft path or runs non-interactively.
  </Step>
  <Step title="Decide, then approve">
    You choose whether to spend an audit round on the draft, then approve that exact draft or ask for changes. You also answer whether to assign the issue to yourself and, when offered, whether to start implementation: on a runner that asks several questions at once, with that decision, each answer carrying to later prompts until you approve and shown there so you can change it; on one that asks one question at a time, right after you approve. PRFlow creates nothing until you approve, acts on your answers only after creating the issue, and asks nothing afterwards.
  </Step>
</Steps>

### What PRFlow Produces

The issue body follows a fixed structure:

| Section | Contents |
| --- | --- |
| `## Problem Statement` | A concise account of the problem or opportunity, in natural prose. |
| `## Current Behavior` | What the code does now. |
| `## Desired Behavior` | The intended outcome, stated as observable behavior. |
| `## User Impact` | Required: who is affected and how. |
| `## Technical Context` | Architecture fit, data and cross-layer impact, and verified premises. Collapsed by default. |
| `## Acceptance Criteria` | A checklist of independently testable outcomes. |
| `## Implementation Notes` | Approach, the one list of relevant files and a testing strategy. Collapsed by default. |

`## Dependencies` and `## 🚫 Blocked — resolve before implementation` are added when they apply.

After creation you get the new issue's URL, and the `PRFlow` label is applied when repository permissions allow it.

<Note>
  `## Technical Context` and `## Implementation Notes` are implementer reference material, so their contents ship inside a `<details>` block and render collapsed on GitHub — every other section renders open. Expand them to read the detail; agents read the raw body text either way.
</Note>

## The Second Comment Is Expected

PRFlow splits its output into two artifacts, and you will see both.

- **The issue body** is the implementer's brief. It holds only what a competent implementer cannot safely work out on their own: the problem, the desired behavior, non-obvious scope decisions, the acceptance criteria, real hazards and dependencies. It is the only channel implement takes acceptance criteria from.
- **The investigation record** is posted as a comment on the created or widened issue. It holds the narrative PRFlow sorted out of the body while drafting: supporting evidence, audit history, lower-severity hazards, rejected alternatives and anything the repository would rediscover during implementation anyway. When the run passed over heavier approaches, PRFlow adds one `Considered-and-rejected:` line counting them. A record over 65,536 bytes, or one that cannot be built or saved, is not posted.

So a newly created issue normally has one comment on it already. That comment is PRFlow's, and nothing is missing from the body because of it.

<Tip>
  Set `spec.investigation_record_enabled` to `false` to stop that comment being posted. The default is `true`. The sorting between brief and record still happens on every draft — only the comment is switched off, and the issue body is identical either way. PRFlow still saves the record beside the draft for you to review, and prints it in chat whenever it prints the full draft; when that save or the removal of an older copy fails, it prints the record in chat instead.
</Tip>

Splitting the two means an approver reviews the implementation contract rather than the whole investigation. It never drops a load-bearing detail to make the body shorter, and no length limit decides what stays.

## Approval Points

In an interactive run, enough context alone does not authorize filing:

1. Review the draft PRFlow saved to a file, whose path it shows. Ask for the complete title and body in chat when you want them, by choosing *print the full draft in chat*.
2. Choose whether to spend a fresh-context audit round on the draft. PRFlow offers one before it runs. Each round you accept re-verifies the draft against the repository and takes time, so you pay only for the rounds you choose. The default is none, and a satisfied reviewer declines. A round run by a separate auditor is also told the number of the issue the draft replaces when the run widens one, and the decisions you made during the run. That auditor is instructed not to report the replaced issue as a duplicate, and, in any finding that argues against one of your decisions, to name that decision and the defect that justifies reopening it. That defect may be of any kind the audit grades. When confirmed defects return, PRFlow applies the issue template's routing and decision rules before composing a repair, even when the finding supplies no remedy. For example, if those rules permit deleting a sentence or moving it to the investigation record and that resolves the finding, the brief gets no replacement incidental claim. For content the brief needs, PRFlow changes the existing statement before adding required obligations. Unknown obligations stay protected by the drafting and decision rules. PRFlow then re-shows the revised version before offering another round.
3. Approve that exact draft with *Create*, which names how many must-revise findings remain unfixed, or request changes.
4. Answer whether to assign the issue to yourself and, when offered, whether to start implementation. On a runner that asks several questions at once, an answer carries to later prompts until you approve; a later prompt shows it instead of asking again, and you can change it there. A question still unanswered when you approve counts as no. On a runner that asks one question at a time, these come right after you approve, and anything but yes counts as no.
5. PRFlow files the issue without assigning anyone, then acts on your answers. It asks nothing after filing.

<Warning>
  An earlier "just create it" does not count as approval of the final rendered draft. PRFlow asks again against the actual text it is about to post.
</Warning>

### Understanding the Audit Summary

The audit summary is one line. It shows how many audit rounds ran (with `no verdict` when the latest round gave none), the latest verdict round's must-revise, advisory and invalid counts, how many must-revise findings were not fixed (`unavailable` when rounds ran but none gave a verdict), and whether the final bytes were audited. A round only counts toward a verdict when the auditor returns a FILE or REVISE verdict and names the exact draft it read.

`final bytes audited` means the draft PRFlow will post is byte-for-byte the draft the auditor of the latest verdict round read. Every other case reads `final bytes NOT audited`: no verdict round yet (with no round run at all, the line reads `Fresh-context audit: not run; final bytes NOT audited`), a draft body whose bytes differ from what that round read, or a draft that was never saved to a file. When the draft was saved to a file and the line reads `final bytes NOT audited`, PRFlow offers another round while fewer than three have started on the current design; picking a different option at a repeated approach question starts that count again, while the summary and the audit question keep counting and numbering rounds across the whole run. The title is outside that check. A round run without a subagent is marked `degraded`. Below the line, PRFlow quotes verbatim each finding of the latest verdict round it did not fix, with its grade. A finding against text that a redraft for a different option replaced counts as fixed, so it is neither quoted nor counted as unfixed.

Interactive filing still requires your explicit approval. After posting, PRFlow reports whether the stored body matches the approved draft, or that it did not compare them.

### Non-interactive Filing

With its Step 4 instructions successfully loaded, a non-interactive run presents the full draft and can elect *Create* only when the unresolved must-revise count is zero and its latest acceptance-criteria parser run read the criteria. An unavailable count does not qualify. Such a run accepts neither assignment nor an implementation offer and runs no elective audit round.

If Step 4 instructions fail to load, the fallback requires explicit approval; it does not inherit this self-election route. These conditions concern filing an issue, not permission to choose unknown requirements or exclude requested work.

## Dependencies and Blockers

These are two different sections and they mean different things.

`## Dependencies` lists open prerequisite issues as `Blocked by #N`. The [implement workflow](/docs/workflows/implement) reads those declarations and stops while a prerequisite is still open, or when it cannot establish whether it is open. It recognizes prerequisite phrasing — `depends on`, `blocked by`, a line-leading `After #N` — wherever it appears, not only under this heading, so reserve that wording for real prerequisites.

To point at a related issue that does *not* gate the work, record it in `Technical Context` as `Related work: #N` rather than under `## Dependencies`. The neutral wording keeps an advisory reference from being read as an execution prerequisite. With the issue-template and final-outcome guidance loaded, a filed or widened issue states each agreed exclusion, and the final outcome names every out-of-scope item the body states with its already-known tracking issue or as unfiled. If either fails to load, PRFlow reports reduced coverage and that disclosure is not guaranteed. Agreeing to exclude a case does not authorize creating another issue.

`## 🚫 Blocked — resolve before implementation` lists unresolved product or implementation decisions. If you decline to settle a blocking decision, PRFlow records it here rather than inventing a default. Settle those before implementation starts.

An issue is implementation-ready when its Blocked section holds no unresolved decision.

## Write Criteria You Want Checked

Acceptance criteria must represent every independently testable outcome in Desired Behavior before PRFlow presents the draft. A quantitative criterion includes the command or counting rule that measures it. A draft that changes a decision rule — for example a grade, route, verdict or guard — maps the rule's outcome before and after the change for each kind of input and mode, quoting the old rule, and reads every claim about the change's effect from that full mapping. So a claim such as "nothing else changes" must hold for every row, not just the case you asked about. Unless your request is unreadable, absent or unwritten, the issue itself states the before and after outcome only for each kind of input the change alters or reaches; the unchanged rows it does not reach go to the investigation record, though a kind of input your request names is still covered by a criterion.

Unless your request is unreadable, absent or unwritten, PRFlow writes a "stays unchanged" criterion only when you ask for it or the change reaches that behavior, and even a reached guarantee that your project's own guidance already requires of every change, such as keeping mirrored copies in step, is left to review unless you ask for it or it is unclear whether that guidance covers the case. So a preservation you need belongs in your request.

A criterion states the outcome, not the mechanism that produces it, unless you ask for that mechanism itself or another surface reads it as a contract; otherwise the mechanism, even one you chose, goes in Implementation Notes. A heuristic is a rule that sorts input whose cases cannot all be listed, such as a change's scope stated as a rule. Anywhere in the issue, PRFlow states it as its rule, which way it fails when a case is unclear, and the limit it accepts, never a pattern or a list of cases, and no check, the audit included, asks for more of its cases, except where a set's members can all be listed and each one's outcome is owed. A finding that the heuristic misses a case is answered by restating the rule, not by adding the case. A finding against a case PRFlow itself added in an earlier revision, to answer a finding that a case was missing, unhandled or had no outcome, is answered by removing that addition and stating the case as an accepted limit rather than patching it, unless removing it would drop a case you asked for. This does not apply to text that records your answer or requested change, fixes a contradiction or a missing end condition, rewrites first-draft text, or that PRFlow cannot place or cannot tell is such an addition. When fixing a finding raises a question about how to handle a case, PRFlow's question also offers to leave that case uncovered as a stated limit.

A criterion that lists existing members of a set, for example every file that reads a value, marks the list `at minimum` unless PRFlow searched the whole repository for those members and read every match. When an answer or revision changes the design, PRFlow repeats that search with the new terms or stops treating its result as complete; it never reuses the earlier result as-is.

This matters beyond the draft: the acceptance criteria are what an implement run verifies at the end. An issue with no criteria gets a run with nothing to check at that gate. See [Implement an Issue](/docs/workflows/implement).

## Widening an Existing Issue

PRFlow searches open-issue titles and bodies for related mechanisms, then reads candidate issues. For an issue you ask it to refine, it also checks cross-references and the relevant issues' current state. Missing or incomplete evidence is disclosed without discarding successful reads; a reference alone adds no scope or permission to edit another issue.

PRFlow widens an open issue only when your request names it or you choose it from the duplicate check. A non-interactive run never widens an issue you did not name; if it files a new issue, it names the suspected duplicate in its outcome.

An interactive widen asks approval to replace the named issue's title and body. After the filing election, PRFlow replaces both in one request; criteria belong in the body, not a comment. Its outcome reports whether the stored title and body match the approved draft, or that it did not compare them. It then applies the `PRFlow` label, tries to register the new body's `## Dependencies` as blocked-by links and reports failures, and posts the investigation record, as it does for a new issue. Links declared only by the old body remain and are disclosed.

A widen asks the same assignment and implementation questions as a new issue.

## After Creation

PRFlow offers to start implementation, with the approval question, only when the draft declares no prerequisite or blocking decision and the cloud implement tier is enabled; otherwise it says why it withheld the offer. When you accepted and the offer still stands when you approve, it posts the trigger comment on the filed or widened issue after filing; it never starts implementing in the same session.

Assignment is best-effort and uses the authenticated GitHub identity. A failed lookup or assignment is reported without undoing filing. Spec's use of REST for issue operations does not establish support for every cloud credential or workflow.

You can also run [Implement](/docs/workflows/implement) later with the new issue number.

## Related Articles

- [Implement an Issue](/docs/workflows/implement)
- [The Lifecycle of a Change](/docs/concepts/lifecycle)
- [Command Reference](/docs/reference/command-reference)
