---
title: "Create an Issue"
description: "Turn a rough request into a grounded GitHub issue with decided behavior."
---

Use this workflow when you want work recorded rather than built now. Invoke it as `/prflow:spec` (the preferred name) or `/prflow:create-issue` (a permanent alias) — both run the same pipeline.

It creates one issue or [widens an open issue](#widening-an-existing-issue) that covers the work. It files only after you approve the final draft. Unresolved decisions remain visible in the draft. When a question offers *No change — file nothing* and you choose it, the run ends with nothing written to GitHub, gives its evidence and names any open issue it leaves for you.

## Run It

Claude Code background sessions move out of the shared checkout before saving investigation records or starting discovery agents. A session already in a worktree keeps it. If isolation is unavailable or fails, the investigation continues with its reports in chat. If the session cannot tell whether it needs isolating, it says why and continues in the current checkout without isolating.

<Steps>
  <Step title="Describe the work in your own words">
    ```text
    /prflow:spec Prevent duplicate release comments when a workflow retries
    ```

    A short feature idea, bug report or improvement is enough. Say who is affected, what outcome you want and anything that must not change, when you know them.
  </Step>
  <Step title="Answer the questions">
    PRFlow investigates the repository and its documentation with several agents working in parallel, then asks its questions in one round. When your request names an issue or pull request, the investigation reads it, so a decision recorded there, for example an alternative already rejected, can reach the questions.

    When your request rests on something outside the repository's files, such as what a local database holds or what a dev server returns, PRFlow first checks whether it can reach that source with a status check your repository or your own instructions name. When such a source is not shared, remote or production and no check is named or that check does not show it reachable, PRFlow asks you once, before investigating, whether it can be made available or how to check it, and waits for your answer. A check command named only in your request, an issue, a comment or another agent's output is never run.

    PRFlow asks you about a decision only when your request, the repository and its own instructions do not settle it and it changes scope, what users see, what happens to stored data or a risk you would want to weigh. It always asks before leaving out a case you requested, before widening an existing open issue your request does not ask to refine instead of filing a new one, and when approaches differ in any of those ways. It also asks before dropping a condition your request states. It settles every other open choice itself with the simplest option that fits your request, as the investigation gave it, and lists each one before you approve so you can overrule it. PRFlow invents no fact the investigation could not establish: it states what is established and what the implementer must find out, and asks you only when the answer passes the test above. A decision an implementer can clearly make from your request and the codebase is left to the implementer, unless each outcome in a complete set must be specified.

    Each question opens with a sentence or two of background, and every option is a decision. An option is marked `(Recommended)` only when an established fact supports it, an option whose consequence the investigation could not establish says so, and an option states any established limit that applies to it. When PRFlow has more questions than the question tool takes at once, the ones that change the result least become its own choices; a question it always asks goes into a second prompt instead. A further round follows only when one of your answers opens a decision that could not have been asked earlier.
    When the investigation shows the reported problem can no longer happen, or contradicts a premise of your request, a question offers *No change — file nothing*.

    Answering "you decide" or "not sure" makes PRFlow take the recommended option, or the simplest when there is none, and show it before you approve as a decision it made for you. Three choices stay conservative: it files a new issue instead of widening one, keeps a requested case instead of leaving it out, and keeps a condition your request states. A reply such as "just create it" is handled the same way and is not approval of the draft. When you ask a question back, PRFlow answers it and asks its question again once. If you do not reply, the run pauses and asks again.

    After you answer, PRFlow asks a question again when a fact established later shows that something the question said about an option was false and your answer could differ. Picking a different approach then redrafts the issue.

    PRFlow drafts the issue from the investigation's findings, your answers and its own choices. A fact nobody could establish is written only as far as it is established rather than guessed. A risk or limit the investigation established that bears on what a requirement can be relied on for is stated beside that requirement, even when the code behind it is out of scope. A fact the implementer does not need goes to the investigation record instead of the issue body. PRFlow then checks the draft against a short list of the mistakes drafts most often make, such as a claim that says more than the investigation showed or a fact the run holds that the draft drops, fixes what it finds, preferring to delete or narrow text, and says in one line what it changed, or that nothing needed changing.
  </Step>
  <Step title="Review the saved draft">
    PRFlow writes the draft to a file and saves the supporting investigation record beside it. The filing question's text says how many corrections PRFlow applied after the latest audit round, or that the draft is not audited. Its option preview shows the draft's path and title, the audit summary line, any reason the implementation offer is withheld, any answers carried from an earlier prompt, any audit findings PRFlow did not fix, any draft-check problems still standing, the record's path (or says the record is empty), each decision PRFlow made after you left it to PRFlow, one line for each choice PRFlow made itself (labelled as the run's choice, so you see it before approving) and the one-line result of the drafting step's check against common mistakes; where no option preview is shown, PRFlow prints these in chat just before the question. A run's choice is a decision the draft states that PRFlow made during *Answer the questions*, while drafting or while revising, did not leave to the implementer, and that your request does not state and none of your answers or requested changes chose; advice an agent wrote, such as a pasted challenge result or a note relayed into the conversation as your message, states no decision even inside your request, except the part you adopt in your own words, though the problem an agent-written body reports does; a decision you left to PRFlow keeps its own line rather than being listed again. A re-ask after no reply, or a reply PRFlow cannot act on, repeats in chat the question text and any of this not yet shown there. If PRFlow's Step 4 instructions fail to load, it prints the full draft and the audit summary line in chat and asks for your approval. It prints the complete title and body, followed by the record, in chat when you choose *print the full draft in chat* at the decision question below, and unasked when it cannot show you a saved draft path.
  </Step>
  <Step title="Decide, then approve">
    PRFlow audits each saved draft before you first see it, once [preparation](/docs/workflows/spec#approval-points) is finished, and audits it once more when the first round's findings changed it or part of that round returned no verdict. When the draft is still not audited, you choose whether to spend another audit round. You then approve that exact draft or ask for changes. You also answer whether to assign the issue to yourself and, when offered, whether to start implementation: on a runner that asks several questions at once, with that decision, each answer carrying to later prompts until you approve and shown there so you can change it; on one that asks one question at a time, right after you approve. PRFlow creates nothing until you approve, acts on your answers only after creating the issue, and asks nothing afterwards.
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
| `## Acceptance Criteria` | A checklist of independently testable outcomes. A documentation change can be one of them, naming the file and what it must state. |
| `## Implementation Notes` | Approach, the one list of relevant files and a testing strategy. Collapsed by default. |

`## Dependencies` and `## 🚫 Blocked — resolve before implementation` are added when they apply.

The testing strategy names what the acceptance criteria do not already state: the failures verification must tell apart from the criteria's outcomes, the evidence PRFlow already gathered and its limits, and any verification method you chose.

When the change edits instructions a model follows, such as an application's prompt, the testing strategy says for each case the change exists to fix whether that case is replayed (run with the old and the new instructions on the same scenario). For a replayed case it says what the scenario must keep so the failure can still happen. For example, it keeps an input the model must look up, and it leaves out the answers the new instructions oblige the model to find for itself. For a replayed case it also says whether the failure needs the context of the run it happened in, such as a long conversation. Each case's expected result is what the new instructions decide for it: the issue quotes and names the instruction whose condition the case meets. When it cannot tell which instruction decides the case, it names each one that might. When every one of them gives the requested outcome, it accepts any of their outcomes. When only some do, it marks the case not replayed, with a reason naming the instructions that decide it otherwise and saying its result would turn on which instruction the model picks rather than on the change, and expects only the outcomes of those that give the requested outcome. A case it marks not replayed for any other reason names what triggers the failure and why no replay can recreate it; when PRFlow cannot tell whether a replay can, it marks the case replayed instead. A case that none of the new instructions decides the way the change requires is dropped as a case the change exists to fix. The [implement workflow](/docs/workflows/implement) follows this statement and skips the replays it rules out.

When the issue asks the implementing run to replay or test with a recorded input PRFlow read, the testing strategy quotes the input's fields that decide the case next to the source it cites; a long input is quoted only in part and cited for the rest.

When the change adds code that reads input your repository does not produce, such as user-written text, historical records or an external file format, the testing strategy carries at least one test fixture shaped like a real record of that input, not only a hand-built well-formed one, and asks the implementing run to test the new reader with it. PRFlow builds the fixture from a record it read, with private content replaced; when it read none, it writes a reconstruction labelled as one.

After creation you get the new issue's URL, and the `PRFlow` label is applied when repository permissions allow it.

<Note>
  `## Technical Context` and `## Implementation Notes` are implementer reference material, so their contents ship inside a `<details>` block and render collapsed on GitHub — every other section renders open. Expand them to read the detail; agents read the raw body text either way.
</Note>

## The Second Comment Is Expected

PRFlow splits its output into two artifacts, and you will see both.

- **The issue body** is the implementer's brief. It holds only what a competent implementer cannot safely work out on their own: the problem, the desired behavior, non-obvious scope decisions, the acceptance criteria, real hazards and dependencies. It is the only channel implement takes acceptance criteria from.
- **The investigation record** is posted as a comment on the created or widened issue. It holds the narrative PRFlow sorted out of the body while drafting: supporting evidence, audit history, lower-severity hazards, rejected alternatives and anything the repository would rediscover during implementation anyway. When a question passes over any approach, PRFlow adds one `Considered-and-rejected:` line counting the approaches it passed over. When PRFlow revises the draft, it also replaces record text the revision makes false or supersedes. A record over 65,536 bytes, or one that cannot be built or saved, is not posted.

So a newly created issue normally has one comment on it already. That comment is PRFlow's, and nothing is missing from the body because of it.

<Tip>
  Set `spec.investigation_record_enabled` to `false` to stop that comment being posted. The default is `true`. The sorting between brief and record still happens on every draft — only the comment is switched off, and the issue body is identical either way. PRFlow still saves the record beside the draft for you to review, and prints it in chat whenever it prints the full draft; when that save or the removal of an older copy fails, it prints the record in chat instead.
</Tip>

Splitting the two means an approver reviews the implementation contract rather than the whole investigation. It never drops a load-bearing detail to make the body shorter, and no length limit decides what stays.

## Approval Points

Before offering or starting an audit, PRFlow finishes reviewing the current draft, applies its confirmed findings, and verifies the repairs and affected statements. If any of that work is unfinished or cannot be established, it pauses the audit and tells you why. When that work cannot finish before you see the draft, PRFlow runs no audit round and shows the reason beside the audit summary line.

Enough context alone does not authorize filing:

1. Review the draft PRFlow saved to a file, whose path it shows. Ask for the complete title and body in chat when you want them, by choosing *print the full draft in chat*.
2. Choose whether to spend another fresh-context audit round on a draft that is not audited. Once preparation is finished, PRFlow runs a first round before you first see each saved draft: separate auditors each check one part of the draft against the repository. Just before that round, another pass proposes deleting text the implementer does not need, and PRFlow applies the deletions it accepts, so the round audits the shorter draft. PRFlow fixes each must-revise finding it has verified without asking you, except that a finding needing one of your decisions is put to you as that decision. PRFlow checks a draft those fixes changed against the common mistakes again and, when the first round's fixes changed the draft or one of its auditors returned no verdict, runs one more round, so that round audits the check's corrections too. It also deletes or narrows a false statement it has verified that no criterion, required behavior, operator step or decision of yours rests on. It applies no other advisory finding: it quotes the unfixed advisory findings of the latest round that returned a verdict as not applied, with those of other rounds that still apply to the draft, and you can ask for any of them with *Change something first*. Whenever a prepared saved draft's audit summary reads `final bytes NOT audited`, PRFlow offers another round, however many rounds have run, unless its Step 4 instructions failed to load. The round is the recommended option until three rounds have returned a verdict; then *Create* is the first, recommended option, unless one of a round's separate part auditors returned no verdict and no round has returned a verdict since. Whenever *Create* is recommended this way, PRFlow adds that a further round is a fresh read of the whole draft, not a check of the latest change. Each round re-verifies the draft against the repository and takes time, so beyond those automatic rounds you pay only for the rounds you choose; a satisfied reviewer declines. A round run by a separate auditor is also told the number of the issue the draft replaces when the run widens one, and the decisions you made during the run. That auditor is instructed not to report the replaced issue as a duplicate, and, in any finding that argues against one of your decisions, to name that decision and the defect that justifies reopening it. That defect may be of any kind the audit grades. A draft that leaves a routine implementation detail open, such as a test fixture to repair or which test method to use, is not defective for that alone. When confirmed defects return, PRFlow applies the issue template's routing and decision rules before composing a repair, even when the finding supplies no remedy. For example, if those rules permit deleting a sentence or moving it to the investigation record and that resolves the finding, the brief gets no replacement incidental claim. To fix a finding, PRFlow deletes the attacked statement unless the issue must carry it, else narrows it to what the finding's quoted source, the investigation or the run's recorded decisions establish, else writes it as not established for the implementer. For content the brief needs, PRFlow changes the existing statement before adding required obligations, and adds no reason clause the brief does not need. It does not keep re-patching its own repairs: when a finding attacks a case PRFlow added earlier in the run to answer a missing-case finding, it removes that addition and states the case as an accepted limit unless your request names the case. When the same part of the draft keeps needing repair, PRFlow first weighs removing or reusing it, choosing that only when it keeps your requested behavior and decisions. PRFlow asks you to resolve choices its drafting rules reserve for you. For example, it asks when permitted fixes build different things, neither your request nor your answers choose between them, and the choice is not left to the implementer. For each finding it fixes, PRFlow searches the draft for other instances of the same defect and corrects the draft for each instance; it edits no repository file. A search that fails, is refused, returns cut-short output or has no search tool is disclosed as unverified reach. Unknown obligations stay protected by the drafting and decision rules. PRFlow then re-shows the revised version before offering another round.
3. Approve that exact draft with *Create*, which names how many must-revise findings remain unfixed, or request changes.
4. Answer whether to assign the issue to yourself and, when offered, whether to start implementation. On a runner that asks several questions at once, an answer carries to later prompts until you approve; a later prompt shows it instead of asking again, and you can change it there. A question still unanswered when you approve counts as no. On a runner that asks one question at a time, these come right after you approve, and anything but yes counts as no.
5. PRFlow files the issue without assigning anyone, then acts on your answers. It asks nothing after filing.

<Warning>
  An earlier "just create it" does not count as approval of the final rendered draft. PRFlow asks again against the actual text it is about to post.
</Warning>

### Understanding the Audit Summary

The audit summary is one line. It shows how many audit rounds ran (with `no verdict` when the latest round gave none), the latest verdict round's must-revise, advisory and invalid counts, how many must-revise findings were not fixed (`unavailable` when rounds ran but none gave a verdict), and whether the final bytes were audited. A round only counts toward a verdict when the auditor returns a FILE or REVISE verdict and names the exact draft it read.

`final bytes audited` means the draft PRFlow will post is byte-for-byte the draft the auditor of the latest verdict round read. Every other case reads `final bytes NOT audited`: an unavailable digest, no verdict round yet (with no round run at all, the line reads `Fresh-context audit: not run; final bytes NOT audited`), a draft body whose bytes differ from what that round read, or a draft that was never saved to a file. When [preparation](/docs/workflows/spec#approval-points) is finished, the draft was saved to a file and the line reads `final bytes NOT audited`, a run whose Step 4 instructions loaded offers another round, however many have run; the summary and the filing question count and number rounds across the whole run, a redraft's first round included. The title is outside that check. A round run without a subagent is marked `degraded`. PRFlow also quotes verbatim each finding of the latest verdict round it did not fix, with its grade. A finding against text that a redraft for a different option replaced counts as fixed, so it is neither quoted nor counted as unfixed.

Filing requires your explicit approval. After posting, PRFlow reports whether the stored body matches the approved draft, or that it did not compare them.

## Dependencies and Blockers

These are two different sections and they mean different things.

`## Dependencies` lists open prerequisite issues as `Blocked by #N`. A prerequisite PRFlow declared itself, which neither your request nor an answer of yours states, is listed with its evidence among the run's choices before you approve. The [implement workflow](/docs/workflows/implement) reads those declarations and stops while a prerequisite is still open, or when it cannot establish whether it is open. It recognizes prerequisite phrasing — `depends on`, `blocked by`, a line-leading `After #N` — wherever it appears, not only under this heading, so reserve that wording for real prerequisites.

To point at a related issue that does *not* gate the work, record it in `Technical Context` as `Related work: #N` rather than under `## Dependencies`. The neutral wording keeps an advisory reference from being read as an execution prerequisite. With the issue-template and final-outcome guidance loaded, a filed or widened issue states each agreed exclusion, and the final outcome names every out-of-scope item the body states with its already-known tracking issue or as unfiled. If either fails to load, PRFlow reports reduced coverage and that disclosure is not guaranteed. Agreeing to exclude a case does not authorize creating another issue.

`## 🚫 Blocked — resolve before implementation` lists unresolved product or implementation decisions. If you decline to settle a blocking decision, PRFlow records it here rather than inventing a default. Settle those before implementation starts.

An issue is implementation-ready when its Blocked section holds no unresolved decision.

## Write Criteria You Want Checked

Acceptance criteria must represent every independently testable outcome in Desired Behavior before PRFlow presents the draft. A quantitative criterion includes the command or counting rule that measures it. A criterion comparing a performance or resource measurement, such as elapsed time or memory use, with another run or a fixed limit also names how and where its runs are taken, for example the number of runs and the machine; one comparing such a measurement between runs also names a tolerance on the side it guards, such as "at most 15 percent slower than before", which comes from your repository's policy or from you, never chosen by PRFlow on its own. A draft that changes a decision rule — for example a grade, route, verdict or guard — maps the rule's outcome before and after the change for each kind of input and mode, quoting the old rule, and reads every claim about the change's effect from that full mapping. So a claim such as "nothing else changes" must hold for every row, not just the case you asked about. Unless your request is unreadable, absent or unwritten, the issue itself states the before and after outcome only for each kind of input the change alters or reaches; the unchanged rows it does not reach go to the investigation record, though a kind of input your request names is still covered by a criterion.

Unless your request is unreadable, absent or unwritten, PRFlow writes a "stays unchanged" criterion only when you ask for it or the change reaches that behavior, and even a reached guarantee that your project's own guidance already requires of every change, such as keeping mirrored copies in step, is left to review unless you ask for it or it is unclear whether that guidance covers the case. So a preservation you need belongs in your request.

PRFlow also leaves out of the issue the house rules your implementing run already follows: rules in your repository's `CLAUDE.md` (at the root or in `.claude/`), the files it imports and your implement skill extension. That holds even when your request or the approach you pick names such a rule, because a copy in the issue can drift from its source. For example, if your `CLAUDE.md` requires a license header on every new file, the issue gets no criterion for it. PRFlow keeps a criterion for such a rule when your request is unreadable, absent or unwritten, when your own words ask the issue to carry it, when your spec skill extension requires it, or when it is unclear whether the run follows that rule. Where a rule leaves the change a choice, one criterion states the choice made. A request to bring existing code or text into line with a house rule is the change itself, so it gets criteria as usual.

When a change relies on code having no authorization guard, permission check or gate condition, PRFlow's investigation confirms that absence by reading the code. The issue quotes the code it read and never asks the implementer to confirm the absence by reading code.

A criterion states the outcome, not the mechanism that produces it, unless you ask for that mechanism itself or another surface reads it as a contract; otherwise the mechanism, even one you chose, goes in Implementation Notes. A heuristic is a rule that sorts input whose cases cannot all be listed, such as a change's scope stated as a rule. Anywhere in the issue, PRFlow states it as its rule and which way it fails when a case is unclear, never as a pattern or a list of cases, and places its limit under the accepted-limit rule below; no check, the audit included, asks for more of its cases, except where a set's members can all be listed and each one's outcome is owed. Against text other than a case addition removed under the next sentence, including an addition repaired in place, a finding that any rule lists, misses or wrongly decides a case is answered by restating the rule, its failure direction or its limit, stating the case as an accepted limit, asking you, or refuting the finding because the rule already decides the case correctly, not by adding the case, unless you asked for that case or it is a missing member of a fully listable set whose outcome the rule already decides. A finding against a case PRFlow itself added in an earlier revision, to answer a finding that a case was missing, unhandled or had no outcome, is answered by removing that addition and stating the case as an accepted limit rather than patching it, unless removing it would drop a case you asked for; that addition is repaired in place under the same missing-case rule. This does not apply to text that records your answer or requested change, fixes a contradiction or a missing end condition, rewrites first-draft text, or that PRFlow cannot place or cannot tell is such an addition. When fixing a finding raises a question about how to handle a case, PRFlow's question also offers to leave that case uncovered as a stated limit.

Every limit the issue accepts, such as a case the change knowingly leaves uncovered or a decision not to change or test something, is written into an acceptance criterion as what the change does not add or repair, naming the case, for example "The change adds no handling of empty input to `scripts/sync.sh`." or "The change adds no timeout check to `docs/retry.md`'s retry step.", never as how the finished system or text behaves in that case, and stated nowhere else in the issue. A decision not to test something means a check against a named case that the finished change could ship and does not; a Testing Strategy note on how the change is verified that names no such check, such as whether the implementing run replays a case, is not a limit and stays in Testing Strategy. A limit stays in the criterion covering its case; decisions not to change something or ship a named check that no criterion covers share one criterion naming each surface and the work the change leaves out; any other limit gets a criterion of its own. Of the issue's text, review's verdict and grading rules read only the acceptance criteria. A limit written there keeps a generated checklist claim from failing on a counterexample lying wholly inside the case it accepts, though a claim quoting the change's own text still fails when that text asserts more than the case allows, and a reviewer's own finding can still raise the case. Covering that case later is a scope change: amend the issue first. Potential Gotchas hold pitfalls and warnings; an action the implementation must take that no existing rule already requires goes in Desired Behavior and a criterion.

A criterion that lists existing members of a set, for example every file that reads a value, marks the list `at minimum` unless PRFlow searched the whole repository for those members and read every match. When an answer or revision changes the design, PRFlow repeats that search with the new terms or stops treating its result as complete; it never reuses the earlier result as-is.

Before deciding where a term the draft creates or redefines is defined, PRFlow searches the existing files the issue names for that term. If one of them already gives the term a different meaning, the draft treats it as a term the change redefines, or uses a different word. PRFlow names in chat any such file it could not read or fully search.

This matters beyond the draft: the acceptance criteria are what an implement run verifies at the end. See [Implement an Issue](/docs/workflows/implement).

## Widening an Existing Issue

PRFlow searches open-issue titles and bodies for related mechanisms, then reads candidate issues. For an issue you ask it to refine, it also checks cross-references and the relevant issues' current state. Missing or incomplete evidence is disclosed without discarding successful reads; a reference alone adds no scope or permission to edit another issue.

PRFlow widens an open issue when your request asks it to refine that issue or you choose to widen it when PRFlow asks, and no other; when it is unclear whether your request asks that, PRFlow asks.

A widen asks approval to replace the named issue's title and body. After the filing election, PRFlow replaces both in one request; criteria belong in the body, not a comment. Its outcome reports whether the stored title and body match the approved draft, or that it did not compare them. It then applies the `PRFlow` label, tries to register the new body's `## Dependencies` as blocked-by links and reports failures, and posts the investigation record, as it does for a new issue. Links declared only by the old body remain and are disclosed.

A widen treats the existing body as your request. PRFlow may reword its criteria or merge duplicates into new ones. A fact the draft rewords, moves or newly states from the old body, or takes from a comment, cites that issue's or comment's URL; text kept word for word needs no citation. To keep exact wording, say so during the run; PRFlow then asks before changing it.

A widen asks the same assignment and implementation questions as a new issue.

## After Creation

PRFlow offers to start implementation, with the approval question, only when the draft declares no prerequisite or blocking decision and the cloud implement tier is enabled; otherwise it says why it withheld the offer. When you accepted and the offer still stands when you approve, it posts the trigger comment on the filed or widened issue after filing; it never starts implementing in the same session.

Assignment is best-effort and uses the authenticated GitHub identity. A failed lookup or assignment is reported without undoing filing. Spec's use of REST for issue operations does not establish support for every cloud credential or workflow.

You can also run [Implement](/docs/workflows/implement) later with the new issue number.

## Related Articles

- [Implement an Issue](/docs/workflows/implement)
- [The Lifecycle of a Change](/docs/concepts/lifecycle)
- [Command Reference](/docs/reference/command-reference)
