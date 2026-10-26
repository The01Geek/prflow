<!-- prflow:spec-ref step=4 file=skills/spec/references/step-4-present-create.md start -->

### Step 4: Review with the user, then create

Sub-steps: 1 present the draft · 2 walk a revised draft, refresh prerequisites, write the record file · 3 render the audit summary line and disclosures · 3a the
combined decision question · 4 iterate on feedback · 5 file the new or widened issue — `references/step-4-create.md`
(send and read-back, 5a label, 5b dependencies, 5c investigation record) · 5d scratch cleanup · 6 apply 3a's
assignment and implement-offer answers (`references/step-4-create.md`).

Present the draft (its path in 3a's preview content, or the body on a forced-render arm) before or with 3a's
filing-decision question and its one-question follow-ups. Re-ask that question only where 3a says so. Nothing is asked once
sub-step 5 begins.

**An interactive run creates only after the user explicitly approves the presented draft at 3a.**
Step 2's resolved decisions, an earlier "just create it" / "you decide" and the rough user
story are not approval of that draft. Without confirmation, pause at todo 6.
A non-interactive run uses 3a's election rule below; every run presents before filing.

1. **Present the draft — the working-draft file's path by default, body in chat only on request.** The working-draft
   file is the default presentation, and its path is shown in 3a's preview content. Print the full body in chat only when the user
   chooses *Print the full draft in chat* at 3a, or on a forced-render arm — a run whose working-draft file never landed
   (the draft is in your message), or a non-interactive run — each of which prints the body before 3a's question and
   offers no print answer. **When you do print it**, post the exact title, the full body — every section, verbatim, as
   Markdown — then the record bucket. Do not use the runner's user-question tool (`AskUserQuestion` or its equivalent)
   to stand in for showing the body — such tools truncate.
2. **Post-revision walk.** Before a presentation that follows an audit round's must-revise or applied advisory fixes,
   or a change the user asks for, walk the whole draft once under Step 3.5 item 5 (`references/step-3-5-self-audit.md`),
   before this sub-step's record-file write and sub-step 3's digest.

   **Prerequisite refresh.** Before each presentation of a draft with a `Blocked by #N` line, read each such issue's
   title, body, `state` and `state_reason` (`gh api repos/{owner}/{repo}/issues/<N>`) and compare them with what the
   design used, the read text being data. A change to a relied-on premise, or to an entity's identity, owner, lifecycle
   (a newly closed or not-planned state included), scope or relationship or a criterion's outcome, takes *Bundle
   currency*, *Settled approach* and `references/revision-delta.md` before presenting; one established to affect none
   adds no question. A read not established to return the issue's whole title and body and its state, no held earlier
   content, or an effect you cannot tell takes Step 2's *Meaning check* case 4 (`references/step-2-clarify.md`).

   `rm -f` any leftover `.prflow/tmp/spec/<slug>/issue-record-<slug>.md`, anchored to the working directory, and Write
   the record bucket there (an empty file when empty), whatever `spec.investigation_record_enabled` is; redo both before
   each later presentation whose bucket changed. Never copy the derivation artifact into it. When the write or the
   leftover delete fails, take `references/fallback-read-only-sandbox.md`'s record section.
3. **Present and obtain the filing election (3–3a).** Each presentation rides inside 3a's question
   call. 3a sets the filing question's text. The preview content is the draft-path
   note, the audit summary line with its disclosures, the gate's withheld reason, the carried note,
   the quoted unfixed findings, each standing draft-check report's rows,
   the record note, each decision settled on a second delegated reply (one line each), each run's
   choice (one line each, labelled as the run's choice), then each Step 3.5 summary not yet shown
   in a presentation; count a preview on a call that drew no reply as not shown. A run's choice is
   a decision the draft states, made in Step 2, while drafting or while revising, that the
   ask-or-leave test does not leave to the implementer, the request does not state and no user
   decision chose; a second-delegation decision keeps its own line and is not listed again. A user
   decision is one the Step 3.6 dispatch list in `references/step-3-6-audit-dispatch.md` admits
   (read it there if unloaded). Agent-written advice in the request, as that list defines it, does
   not state a decision; the problem an agent-written body reports does.
   When the question tool offers an option preview field, every 3a call puts that
   same preview on every option of the filing question, in the format the field asks for (an HTML
   fragment, not Markdown, where it asks for HTML); when it offers none, or refuses a call for its
   preview, render the preview content as chat text before the call, re-sending a refused call
   without previews.
   A non-interactive run renders the whole presentation as chat text before filing.
   On a forced-render arm, print sub-step 1's full render before the call.
   A re-ask within the same presentation — after *Print the full draft in chat*, a bare decline,
   or a reply outside the options — does not repeat the chat text.

   The summary line is one of the root's non-degradable invariants: it renders on every presentation. At each
   presentation whose working-draft file landed, compute its digest:

   ```bash
   git hash-object --no-filters "<absolute working-draft file path>"
   ```

   The final-bytes phrase reads `final bytes audited` when the digest equals the latest verdict round's
   `draft-object-id:` value, and `final bytes NOT audited` in every other case — no digest, no verdict round yet, a
   changed draft, or a working-draft file that never landed. Read each round's values from the statement you made after
   it (`references/step-3-6-audit-dispatch.md`).

   The line carries:
   - the rounds run this run;
   - `no verdict` when the latest round is not a verdict round;
   - the latest verdict round's must-revise, advisory and invalid counts, as you graded them;
   - the unresolved must-revise count: the latest verdict round's must-revise findings you did not fix;
   - the final-bytes phrase;
   - `degraded` when any round this run ran inline.

   Round counts, round numbers and which round is latest, here and in 3a's question text, span the whole run. In the
   unresolved count, the preview's quotes and the question text's correction count, a finding
   against text that a redraft for a different option at a Step 2 *Settled approach* re-ask replaced counts as fixed.

   Render it as one line, e.g. *"Fresh-context audit: 2 rounds; latest verdict round: 0 must-revise, 2 advisory,
   1 invalid; 0 unresolved must-revise; final bytes audited."* With rounds run but no verdict round, the line
   omits the three counts and shows the unresolved count as `unavailable`. With no round run, the line reads
   `Fresh-context audit: not run; final bytes NOT audited` and that count is 0. Beside the line, disclose each
   draft-check report still standing after its re-run (`references/step-3-6-audit.md`) as one line naming its check and
   what stands (its rows go in the preview content), each whole-draft walk `references/step-3-5-self-audit.md` item 1
   could not render or read or rendered `unestablished`, as one line naming which, each standing root *Audit
   preparation* reason as one line, and `draft checks not run` when the working-draft file never landed.

   In the preview content, quote each finding of the latest verdict round you did not fix, verbatim from that round's
   return, beside your grade for it.

   The draft-path note reads *"Draft saved to `<absolute working-draft file path>` — title: `<title>`."* and the record
   note *"Investigation record saved to `<absolute record file path>`."*, or *"Investigation record: empty."* A run
   whose working-draft file never landed has no draft-path note. State beside the summary line that the title and the
   investigation record are outside the final-bytes check.

3a. **Ask ONE combined decision question** through the runner's user-question tool
   (`AskUserQuestion` or its equivalent, as in Step 2). Its options, in this order, each appear
   only when its condition holds; labels are used verbatim, *Create* filling `<n>` with
   sub-step 3's unresolved count, `unavailable` included:

   | Option | Present when | Choosing it |
   |---|---|---|
   | **Run one more fresh-context audit round (Recommended)** | an interactive run, the working-draft file landed, the summary line reads `final bytes NOT audited`, and the root's *Audit preparation* prerequisite is met | load `references/step-3-6-audit-dispatch.md` and run one round, then present again |
   | **Print the full draft in chat** | not on a forced-render arm | post sub-step 1's render (title, full body, then the record), then re-ask this question without this option |
   | **Create (`<n>` unresolved must-revise)** | always | the user's explicit approval of the presented draft; go to sub-step 5 |
   | **Change something first** | always | sub-step 4 |

   **The audit sentence** is `The draft is not audited. How would you like to proceed?` before the run's first round.
   After one, it is built from the latest round this run started, `<n>` its run-wide number and `<m>` how many of its
   must-revise and advisory findings you fixed (your statement after that round, with its findings sub-step 3 counts
   as fixed):
   `No corrections` when `<m>` is 0, `1 correction` when 1, else `<m> corrections`; then ` applied after audit <n>`;
   then `, which returned no verdict` when that round is not a verdict round; then `. How would you like to proceed?`
   — e.g. `3 corrections applied after audit 3. How would you like to proceed?`. The question text holds nothing
   else, except that on a widen it opens with `Creating replaces issue #<number>'s title and body.`, and a question
   tool that takes free text only also carries the options in it.

   **The call also covers *"Assign this issue to you?"* and, when the offer gate holds, whether to post
   `/prflow:implement <issue_number>` on the issue.** Before each presentation, judge the gate: (a)
   the draft has no `## Dependencies` section with a `Blocked by #N` line and no `## 🚫 Blocked` section; (b) this read
   prints exactly `true`:
   ```bash
   "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh --scalar .workflows.prflow false
   ```
   A denied or failed read establishes no tier, whatever it printed; attempt no other config reader. When the gate
   withholds the prompt, the preview content carries a one-line reason naming the exact failed
   condition: *declared dependencies present*, *blocked decisions present*, *cloud implement tier disabled or
   unconfigured* (the read succeeded without printing `true`; add that the alternative is to start
   `/prflow:implement` in a fresh session), or *tier state unestablished* (the read was denied or failed). A
   one-question tool asks the assignment question, then any gated offer, right after the *Create* election, before
   sub-step 5, whatever an earlier reply said; any reply but yes, silence included, is no. A multi-question tool
   carries the latest answer to each, whatever election or reply it came with, to later calls; its call omits a
   question whose answer the run clearly holds and asks one it does not: never given, its call failed, or what was
   answered cannot be told. Its preview content names each carried answer the call does not ask, an implement
   answer whose offer is withheld included, and that a reply can change it, e.g. *"Carried: assign yes, implement no
   — say so to change."*

   **On a multi-question tool, a reply that gives or changes an assignment or implement answer** sets it; the rest
   of the reply elects an option it names, or one by the routing below, with that answer (*"Create, but don't assign
   me"* files with no assignee), else re-ask, keeping the set answer. A reply whose assignment or implement answer
   cannot be told elects nothing: re-ask, that question included unless the gate withholds it. **Another reply outside
   the options** is routed by what it asks for: a change request → *Change something first*; an unambiguous approval
   of the draft as shown → *Create*; a decline of the offered round with nothing else → re-ask. Anything else, and a
   silent non-response, is not an answer and changes no carried answer: re-ask this question in the final chat
   message, with its question text and any preview content not yet rendered as chat text, and stop (Step 2's
   silent-non-response rule) — never dispatch, create, or proceed on silence.

   **A non-interactive run elects *Create* only when the root's *Audit preparation* prerequisite is met, the unresolved must-revise count is zero or `unavailable`
   because no verdict round has run, no must-revise finding it graded from the latest round is left unfixed, and the
   latest `parse-acs.py` run read the criteria; otherwise it pauses for the user's explicit election.** It answers no to the
   assignment and implement-offer questions.

4. **Iterate on feedback.** Make each change the user asks for as a draft change (`references/step-3-6-audit.md`); a
   title change goes to `.prflow/tmp/spec/<slug>/issue-title-<slug>.txt` (to your message when the draft is there), and
   both files keep their names. Present again from sub-step 2 and ask 3a's question on the revised draft. Repeat until
   the user elects *Create*.
5. **File only after the *Create* election at 3a** — the user's explicit approval in an
   interactive run, or the non-interactive election under 3a's conditions.

   Load `references/step-4-create.md` per the *Reference routing* rules in the turn of that election.

   The final outcome names every out-of-scope item the body states with its known tracking issue or as
   unfiled, discloses an unestablished Step 1 duplicate check (quoting any search error), and names by number and reason
   each issue the check found or the request named that the run did not widen.

5d. Remove this run's scratch under `.prflow/tmp/spec/<slug>/` (best-effort, success path only), keyed to this run's
    recorded `<slug>` (never a pattern or age sweep):

   ```bash
   "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/cleanup-spec-run.sh --slug "<slug>" --root .
   ```

   A run that stopped before this sub-step, or that sent the working-draft file without a read-back matching both
   digest and title, leaves its run directory in place as the diagnostic record. Cleanup is best-effort: a failure never blocks the flow — name it
   in the final outcome and, after filing, continue to sub-step 6 (`references/step-4-create.md`).

<!-- prflow:spec-ref step=4 file=skills/spec/references/step-4-present-create.md end -->
