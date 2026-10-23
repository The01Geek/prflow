---
name: spec
description: Turn a rough request into an implementable GitHub issue through bounded clarification and design decisions — "file a ticket", "open an issue", "track this bug", "spec this out for later". Open-ended product exploration belongs to brainstorming; building the work belongs to implementation.
argument-hint: <user-story>
---
## Completion checklist (do this first)

Before any of the pipeline's steps below, track these slots in the runner's task-tracking tool — the
one that keeps a list of tasks with statuses, whatever its name. When none is visible, first load one
the runner lists as not yet loaded or that its tool-search tool finds. Otherwise — and whenever the
tool errors, its setup call's result shows no tracker, it stops working later, or you cannot tell
whether a tool is one — keep the slots as an inline checklist in your reply, re-rendered on each
status change with each slot pending, in progress or completed, keeping the statuses already
reached. Change tracker only when the one in use stops working. A tracker problem never ends the run.

- [ ] 1. Run Step 1's arm and write its evidence artifact
- [ ] 2. Clarify the user story until the Definition of Ready is met (Step 2); a shown-gone *No change* choice ends the run here
- [ ] 3. Draft the issue and pass the no-options gate (Step 3)
- [ ] 4. Self-audit the draft against the code, revise, and re-pass the no-options gate (Step 3.5)
- [ ] 5. Run the draft checks and each draft's first audit round (Step 3.6)
- [ ] 6. Present the issue and obtain Step 4's filing election, then create it (sub-steps 1–5)
- [ ] 7. After filing succeeds, apply 3a's assignment and implement-offer answers (Step 4, sub-step 6)

Mark each slot in_progress when you start it and completed only when done — the canonical status
vocabulary; a task tool whose status fields differ uses its nearest equivalents. Step 1's
reports complete only slot 1.

Once the tracker exists, open your first reply with one line naming this skill and the tracker in
use — the task tool or the inline checklist — and name any tracking tool that failed directly after it.

## Iron Law

No run abbreviates or skips a step before it ends: at a created, widened or paused issue, at a stop a step documents, or at a *No change — file nothing* choice under Step 2's shown-gone rule.

## Rationalizations

| **Excuse** | **Why it does not hold** |
| --- | --- |
| "This ticket is trivial; a lighter pass is fine" | Triviality is a claim your self-audit tests; the one-line ticket that was not trivial is yours to catch. |
| "I'll abbreviate but say so" / "properly-ish, given time pressure" | Announcing an abbreviation does not authorize it: a shortened pipeline is not a pipeline. Run the step, or record what genuinely cannot be resolved in the Blocked section. |
| "The docs-verify dispatch is expensive" | Cost is not a gate. Step 1 grounds every later claim; skipping it drafts blind. |
| "No user is available" | The absence of a user does not excuse an artifact no user is needed for; self-answer from the issue's own material where the run is non-interactive and continue. |
| "The draft is solid; skip more grounding, or the audit round" / "the audit will catch it" | The draft is yours, and confidence comes from your own walk, not the audit's: the audit confirms quality and a defect your reads could have found is yours to find first. Step 3.6 sets when a draft's first round runs; a further round is the user's election wherever Step 4 offers it; on a run that asks for approval of its draft at Step 4, never skip the draft checks or the summary line. |
| "Render the draft and report, to be efficient" | Rendering and reporting is not creating. |
| "The design is simple; nothing it touches can break" | Simple designs break their consumers too. Run the pre-mortem rule; the self-audit and audit run only after the user has chosen the design. |

## Core principle

An issue is the output of resolved decisions — not a place to park unresolved ones.

**The ask-or-leave test** governs whether a decision is asked, written or left to the
implementer. A decision the request leaves open is asked and written unless a competent
implementer could clearly make it from the request and codebase and it is not a member's
outcome in a fully listable set, such as an agent-policy route or a text's clause. Then
the run leaves it out, naming it in one chat line; the implementer decides and PR review
judges it. The implementation-approach question is asked on every run and never left to
the implementer; a needed heuristic is asked as its rule, failure direction and limit.

Every decision the test does not leave to the implementer must be resolved by asking the
user before drafting. A decision settled on a second delegated reply counts as
resolved by the user; remaining unresolved decisions go into one explicit Blocked section.

**The no-options rule.** The body states one decided behavior per fork: no alternative, open question or deferred choice is written outside `## 🚫 Blocked`, and a premise flagged `— assumption, confirm before implementing` is a fact to confirm, not an open choice. Every acceptance criterion is one concrete, unconditional assertion, and the ask-or-leave test decides what is left out. Wording the user approved, or the issue prescribes verbatim (quoted as text to add to a file), is never reworded silently: this overrides every other rule, sweep and standard, the writing standard included, and changing it is a decision fork asked of the user.

**The pre-mortem rule — hold it for the rest of the run.** From Step 2's first candidate
until the run ends, assume the fix shipped as designed and failed: name the consumer,
environment, input, state or later change that broke. Repeat when a candidate, answer or
revision changes the design. Confirm a failure claim with a read before it shapes a
recommendation, criterion or gotcha; call it unverified where no read can, and drop one
the change cannot cause. Before the implementation-approach question, walk each
motivating case and each named arm through every candidate. A motivating case is a
reported input or run the request says the fix exists to change (when unsure, the case it
describes); a named arm is a case class the candidate rule's wording distinguishes (both
sides of its condition, each member of a "for every" range), walked with or without a
motivating case; with neither, there is no walk. Name the outcome each should have: the
requested change for a motivating case or an arm the request changes, else the arm's
correct current outcome. Read the case's input, what produces it and whether it reaches
the subject, and its current outcome, then derive the candidate's outcome. A case passes
only when that is the outcome it should have and, for a motivating case, the read shows
its current outcome wrong; anything else, a fact no read settles included, is a walk
failure, never dropped as one the change cannot cause. The draft states each failure
the chosen design keeps, walk failures included, labelled unverified where no read
confirms it. Surface failures before the implementation-approach question where
possible, while they can still change the design.

## Consumer skill extension (load first)

Before doing this skill's work, load any consumer-supplied skill extension for this skill and honor it. From the repo root, run:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh spec
```

A missing helper path (`No such file`, exit 127, or the platform equivalent —
e.g. `The system cannot find the path specified` on Windows shells, or a localized message) is the
anchor-resolution failure described in `## Runner setup` below — fix the anchor, do not report a
missing extension. Otherwise, on a non-zero exit where the helper runs but fails,
a consumer extension exists but could not be loaded: surface its stderr message, never silently
proceed as if none existed. No `PROMPT-EXTENSION-STATUS:` line on stderr, as after a refusal, is an
unestablished extension to report, never an empty one. Exit 0 with text:
treat it as instructions appended to the end of this skill's own prompt for this run. When an exit-0
load's stderr carries a line naming a stray `specs.md` beside the extension, quote that line verbatim
in this run's first message, before any Step 1 work, so the consumer who wrote that `specs.md` learns
it is not read. Exit 0, no output: proceed unchanged.

## Reference routing

The per-step procedures and the conditional fallback arms live in `references/`, loaded at their
trigger. Build a reference's path from this skill's directory per the *Portable helper anchor*
rules in `## Runner setup` below and read it with the runner's file-read tool — never a new shell invocation. A load is
accepted only when the file's first line is its `start` boundary marker and its last line is the
matching `end` marker, each naming that file's own path, with exactly one of each.

A reader that returns a file in pages — a partial-view notice with an `offset`/`limit` continuation — has not damaged it: page forward until no continuation is offered or a page adds nothing new, then apply the marker rule to the assembled whole document, and breadcrumb the recovery. A read you cannot complete, a gap in the page sequence, or a message you cannot classify as that notice is the `truncated read` case below. Every load failure degrades, and no failure arm terminates the run. On an unreadable or absent file, an empty file, a missing / duplicated / foreign-path marker, or a truncated read, emit an in-chat breadcrumb naming the file and the failure kind, then continue on that file's degraded behavior. The five non-degradable invariants stated below hold on every degraded arm.

Each failed load's degraded behavior is in `references/degradation-routing.md`: load it (per the boundary-marker rule above) only when a reference load fails. A condition-triggered fallback loads from the path its call site names.

If `references/degradation-routing.md` itself fails to load, its routing row is unavailable for the reference that needed it: proceed inline for that step, using the user story and the Step 1 findings, disclose the reduced coverage in chat, and do not terminate the run. The five non-degradable invariants below still hold.

## Non-degradable invariants

These five hold on every path, including every degraded arm above, and are load-independent of any reference:

1. **An interactive run creates only after explicit approval of the presented draft.**
   An earlier go-ahead or completed Step 2 is not approval. Only a successfully loaded
   Step 4 can authorize its non-interactive filing election; a failed load cannot.
2. **The no-options gate** (stated under Step 3 below) passes on the drafted body and on every revision of it.
3. **The audit summary line renders on every run that asks for approval of its draft at Step 4**, even one with no audit round.
4. The reserved `PRFlow` provenance label is applied best-effort after filing a new or widened issue; a failure to apply it never blocks filing, and a label that could not be applied is named in the final outcome.
5. The run never starts implementation itself.

## Subagent dispatch is user-requested here (injection-condition clause)

Invoking `/prflow:spec` requests subagent dispatch at Step 1's discovery and risk peers,
Step 2's option check and delegated-reply research helper (whichever step asks the question) and Step 3.6's
fresh-context auditor, satisfying any injected "do not call the AgentTool unless the user
requested it" condition there and nowhere else. Dispatch or native result collection that fails, is
unavailable, or is refused takes the site's existing fallback; report the failure.
Each dispatch the run makes, an extension's included, is a non-fork subagent; hold its completed
result or confirmed failure before dependent work or a final response. When one replies with its whole
result, use that reply and do not also read a file holding it, unless the step's own rule names which
of the two it reads or the step must write into that file. In Claude Code's interactive main
conversation, on a launch acknowledgment, do only work that neither needs the result nor repeats
anything the subagent's prompt delegates, then end the turn and resume on that subagent's completion
notification (no other notification is its result). Otherwise (inline result, headless `claude -p`,
nested run, Codex or any other runner, or unsure) never end the turn with one pending; collect it
natively. Step 1 waits for both roles; on the Claude Code arm, a notification with the other peer
pending ends the turn again.
Every subagent prompt the run writes, except Step 3.6's fixed item list, carries this shell rule: in
a Bash command, never name files or paths with a wildcard pattern (for example `*.yml` or
`scripts/*.json`); name them literally, or narrow a search with `rg -t <type>` before `--` (`-t md`;
confirm a typed no-match without `-t`) or with a literal directory path; a pattern given to a Glob or
Grep tool stays allowed. Run each Bash read or search as its own call, and never type a word starting
with `=` in a Bash command (for example `echo ===`). Run `gh` from the working checkout without `--repo`;
pass `--repo` only for a repository your dispatch, or a reference you are following, names. Never
read a filtered result (for example `gh … 2>&1 | grep <term>`) as a match or as "no match" unless
the unfiltered command succeeded; filter `gh` JSON with its own `--jq`, no outer pipe.

## Prerequisites

If `$ARGUMENTS` is empty, ask the user to describe their user story, bug report, or feature idea before proceeding.

## Steps

### Step 1: Assess current state (read-only)

Extract the topic from the user story.

Bind the slug, then clear state — before any dispatch. Bind this run's kebab-case slug here; no
later step binds one. Run `mkdir -p .prflow/tmp/spec/<slug>` first, treating any stderr from it as its failure
signal; a write or delete you or a script you run make at or under `.prflow/` that fails or is refused routes this evidence
record and this registry entry onto `references/fallback-read-only-sandbox.md`'s Step 1 arm.
The Step 1 record is the index `issue-step1-<slug>.md` plus the role files
`issue-step1-discovery-<slug>.md` and `issue-step1-risk-<slug>.md`, all under `.prflow/tmp/spec/<slug>/`;
a dispatch or step given the record by path gets all three paths, made absolute from the working directory.
Delete all three:
```bash
rm -f "<absolute index path>" "<absolute discovery role file path>" "<absolute risk role file path>"
```
Then register this run through the run-directory registry:
```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/cleanup-spec-run.sh --register-slug <slug> --topic "<one line from the user story, reduced to letters, digits, spaces and . , : - _ / only>" --root .
```
The helper reads no environment variable, writes the run's `run-meta.json`, and prints one
`registered=` line; read the line you received. A run that received `registered=no` never invokes
`--resolve-slug` later and treats a lost slug as unestablished (the title-derived fallback in *Runner setup*).

When the request names an existing issue in this repository, have the helper fetch it once, comments included, into
the story file, `<absolute story path>` being `.prflow/tmp/spec/<slug>/issue-story-<slug>.md` made absolute:
```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/preflight.py issue-body --issue <n> --with-comments --out <absolute story path>
```
On a `CACHED` line, read that file rather than fetching the issue again, and give both peers the
request as the user typed it plus that path, telling them to fetch the issue only when their read of
the file fails. Any other output, or none, passes no story file, never taking the sandbox arm: say
so, and each peer reads the issue itself.

Dispatch two independent peers in parallel; when Step 1 is already on that sandbox arm, dispatch them as it says instead:

- Discovery: a subagent holding a file-write tool (on Claude Code, `general-purpose`) running `/prflow:docs-verify --report-only --report-file .prflow/tmp/spec/<slug>/issue-step1-discovery-<slug>.md --lead docs <topic>` with the user story, retaining its whole-repository search and six-duty floor, and also measuring each file it reports against any size or count limit a guard holds that file to, and searching the history of the topic's text when a finding depends on it.
- Risk investigation: `subagent_type: prflow:spec-risk-investigator` with the original story, repository path, established user constraints/decisions (never agent-written advice, as the Step 3.6 dispatch list in `references/step-3-6-audit-dispatch.md` defines it; read it there if unloaded), the risk role file's absolute path as its report file, and the paths of files the session saved before Step 1 as a record of the reported failure (a downloaded job log, a failing run's output). Pass paths only, never file content or a conclusion drawn from a file; never pass the session's own transcript or this run's other `.prflow/tmp/spec/<slug>/` files, the story file excepted, as evidence. Supply no preferred design or other peer's conclusions.

Each peer writes its whole report to its role file with its file-write tool, never a shell
redirect, and replies with the path; one that cannot write says so and replies with its whole
report, a peer's own failed write never taking the sandbox arm. Both dispatches give this evidence
form: each fact the report relies on as its locator with the text its read returned, quoted, and
each whole-tree search as its command, scope and found/read counts.

After both return or fail, read once, whole, each role file that exists and is non-empty, whatever
its peer replied. Into an absent or empty role file write the peer's reply, the risk report kept
concise; a reply giving a path and no report is instead a role failure, its failure note naming the
replied path when that names another file, which you leave in place. Required fields:
- **Discovery**: **Doc verdict and location**, **Current behavior**, **Relevant files** and **Not established**.
- **Risk investigation**: **Constraints and premise corrections**, **Conditional risks**, **Not established** and **Scope examined**.

For both roles, mark missing, empty, malformed or unreadable required fields
`unestablished — <reason>`, writing the marker into the role file in place of the field it rejects; retain usable evidence. `none` denotes no findings after inspection.
A risk report with no identifiable inspected evidence is a role failure, with scope
`unestablished — <reason>`; field gaps alone do not invalidate grounded partial evidence.
Only discovery or inline recovery supplies the doc verdict; values outside
`RELIABLE`/`UNRELIABLE`/`ABSENT` are `unestablished`.

Missing or wholly unusable reports also count as role failures. Name failed roles, failure kinds
and coverage gaps in chat and in the failed role's file beside partial evidence. Risk failure continues
from discovery. If discovery fails, perform bounded inline discovery with its six-duty floor, the
discovery dispatch's added duties and the evidence form, degraded, with unanswered duties or verdict `unestablished`, and write it to the discovery role file
marked degraded. Every role file exists after Step 1 unless its write took the sandbox arm. Never substitute risk evidence
for discovery or present partial coverage as whole.

Then write the index with the role headings **Discovery** and **Risk investigation**, under each
the role file's absolute path, its delivery (`written by peer`, `written from reply` or `failed`)
and the role's failure kinds; it holds no report text. If the record is unavailable, carry the entire
record through `references/fallback-read-only-sandbox.md`'s Step 1 arm; no failure ends the run.

Duplicate-issue check (read-only, before Step 2's first question). Search titles and bodies across
all open-issue pages, returning only candidates. Substitute lowercase mechanism terms, JSON-escaped
with apostrophes as `\u0027`:
`gh api 'repos/{owner}/{repo}/issues?state=open&per_page=100' --paginate --jq '.[] | select(has("pull_request") | not) | select((.title + "\n" + (.body // "") | ascii_downcase) | contains("<term-1>") or contains("<term-2>")) | {number,title}'`.
For an issue the request names for refinement, also read
`gh api 'repos/{owner}/{repo}/issues/<n>/timeline?per_page=100' --paginate --jq '.[] | select(.event=="cross-referenced") | .source.issue | {number,title,url,pull_request}'`.
Check each source's repository and type; read the named issue from the story file when one was passed, its `url` giving the type;
read plausible same-repository matches, and the named issue otherwise or when that read fails, with `gh api repos/{owner}/{repo}/issues/<n>` to compare mechanisms and establish current state.
A refused, failed or incomplete retrieval leaves that source unestablished, not empty;
retain results from successful sources and disclose the gap. A reference alone neither
adds scope nor authorizes changing another issue. Widen only an open non-PR issue the
request names or the user chose to widen (Step 2); follow no recursive reference chain.

### Step 2: Clarify until the Definition of Ready is met

Load `references/step-2-clarify.md` per the *Reference routing* rules above and follow it exactly, on every entry into this step.

### Step 3: Draft the issue and pass the no-options gate

Precondition — the Step 2 derivation-artifact gate applies here too, unconditionally. Before drafting, confirm `.prflow/tmp/spec/<slug>/issue-derivation-<slug>.md` exists and holds *this run's*
derivation — or, in a read-only sandbox, rely solely on the visible inline-in-chat stand-in
re-posted in this turn and do not trust any on-disk file (it can only be a stale leftover).
If the artifact is missing or you cannot confirm it is this run's, the requirements self-check
was skipped — stop and run it now (Step 2) before drafting.
This equally gates the `## Evidence bundle`: it must have an entry for every axis its header lists
and, unless `references/step-2-clarify.md` failed to load, its header must pass Step 2's *Axis-list header*
rule; otherwise stop and run the evidence-bundle sub-pass before drafting.

Draft the issue from Step 1's documentation findings (relevant files, current behavior), Step 2's
decisions and these recorded facts when they bear on the chosen approach:

- the Step 1 record's constraints, premise corrections and **Not established** entries, and its
  conditional risks only when the design keeps their triggering choice (record:
  the index and role files Step 1 names);
- the derivation artifact's derived edge cases;
- from every *Option check* record this run made, the chosen option's items and each item whose
  claim the draft repeats, whichever option it is about, reading each earlier record, as Step 2's
  record rule selects it, from its file and any part of it that exists only in chat from what the run
  still holds of it; treat one you cannot place under that rule as a record you cannot read;
- the pre-mortem failures the design keeps, as the pre-mortem rule requires, and those it
  remedies by a decided change.

Bundle claims the draft relies on follow Step 2's "Carry relied-on bundle claims into the draft"
rule. Place each issue the bundle's overlapping-open-issues entry names: leave the issue being
widened out of its own body and name one a recorded user scope answer absorbs only as absorbed; put a
prerequisite the user confirmed under `## Dependencies`; make every other one a `Related work: #N`
bullet; state whatever that entry marks unestablished as not established. As a heuristic, a fact bears on the approach when it is about the chosen option, a choice
the design keeps, a requirement the derivation derived or a claim the draft repeats; draft one you
cannot tell bears on it as an accepted limit or not established (limit: a fact never written down
can still be lost). A record you cannot read gets an in-chat breadcrumb naming it and the failure
kind, and the draft states as not established that it went unread; an earlier chat-only *Option
check* record's items the run no longer holds are instead stated, outside the criteria, as having gone unread.

Each drafted fact lands as handled, an accepted limit (in the criterion `references/issue-template.md`'s
*Accepted limits* names), not established or, for those unread items alone, as stated above,
keeping the record's triggering condition, strength and every actor or phase it
names; a fact about the spec run is never an accepted limit. One that existing behavior
already handles without a design change adds no criterion or Testing Strategy case; one the design
remedies by a decided change is handled, its remedy in Desired Behavior and graded for a criterion
under `references/issue-template.md`'s omit/merge/add rule. A kept failure under the pre-mortem
rule is an accepted limit or not established, labelled as that rule says. Draft an item a record
labels `unclear` or `unestablished`, or a **Not established** entry, as handled only once a read
settles it, else as an accepted limit or not established. Check a request or derivation claim the draft repeats
against the premise corrections and the evidence bundle first, and state a contradicted one in its
corrected form. State each drafted fact's outcome; never copy the Step 1 record wholesale. The records
are leads, not your understanding: before drafting, read the code the chosen design changes
yourself.

Before composing the draft prose, read the shared writing standard `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/writing-standard.md` and follow it (an issue is change-describing prose).
Per this skill's degrade-never-terminate contract, a failed load emits a breadcrumb naming the file and the failure kind and you draft without it.

Load `references/issue-template.md` per the *Reference routing* rules above and follow it for the required section structure, the self-check, and autolink hygiene, on every entry into this step. Key rules:

- No-options gate (run before showing the draft): re-read the rendered body against the no-options rule (*Core principle*). If you find an unresolved decision, delete it when the ask-or-leave test leaves it to the implementer; otherwise either ask the user now through Step 2's clarification routes, or move it verbatim to the Blocked section. Do not proceed to Step 4 until the body is clean.
- Advanced quality-guidance routing: evaluate these triggers against facts already held
  (the request, Step 2 evidence bundle and assembled draft). Load a group only when its
  trigger fires or applicability is uncertain, under *Reference routing*. A failed required
  load takes its `references/degradation-routing.md` route, never a silent skip.

| Reference | Trigger |
| --- | --- |
| `references/quality-group-visual.md` | User-visible UI change; reuse Step 2's load. |
| `references/quality-group-contracts.md` | An AC or Testing-Strategy assertion expresses a number, value comparison, universal quantifier about the system under change, enumerated list, or trust/integrity boundary over executable artifacts; or the draft changes a decision rule whose surface names its outcomes (grades, severities, classifications, routes, thresholds, verdicts, guard allow/deny), including creating, deleting, narrowing, widening, re-grading, reclassifying or re-routing a guard or guarantee. |
| `references/quality-group-premises.md` | Reliance on external/third-party behavior (webhooks, trigger syntax, token scopes, endpoint behavior, response shapes, rate limits), a `Verified:` bullet, or a claim that code does something on a possibly-gated or default-off path. |
| `references/quality-group-semantic.md` | A new LLM/semantic judgment over third-party text drives automated selection or action; reuse of a cited, already-guarded judgment path is exempt. |
| `references/quality-group-regression.md` | A defect report, a Testing Strategy case/input-shape matrix (parser, config consumer, best-effort input handler), or a new reader of input the repo does not produce (historical records, user/reporter-controlled text, external structured formats, agent/human-mutable markdown). |
| `references/quality-group-compatibility.md` | A grounded supported-version boundary change across runtimes, tools, APIs, schemas, configurations or plugin releases; a changed contract used by existing data, configuration or consumers; independently upgraded components that can run at mixed versions; or rollout behavior such as staged activation, rollback or old/new coexistence. Merely touching a shipped path does not trigger it. |

Write the title, one line, to `.prflow/tmp/spec/<slug>/issue-title-<slug>.txt`, then the body alone to `.prflow/tmp/spec/<slug>/issue-working-draft-<slug>.md`, both anchored to the working directory. The body file is the working-draft file: the run edits, presents, audits and posts it. Its last line is the provenance signature: paste verbatim the italic line the fence below prints, and omit it when the fence prints nothing.

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/render-pr-provenance-line.py --command /prflow:spec
```

Re-read and retry once a failed write or edit that is not a permission refusal or filesystem failure. A first write of either file refused, failing in the filesystem or failing its retry moves the title and body to your message for the rest of the run: the working-draft file never landed, and neither file on disk is read or posted. Once both first writes land, a write, edit or read of either file failing any of those ways is a stop: report in chat that the draft is lost, and file nothing. A shell command's read of either file fails only when its error names the file missing, empty or unreadable; its other failures take that command's own route.

### Step 3.5: Self-audit the draft against the code (mandatory, before the user sees it)

Load `references/step-3-5-self-audit.md` per the *Reference routing* rules above and follow it exactly, on every entry into this step.

### Step 3.6: Run the draft checks and each draft's first audit round

Load `references/step-3-6-audit.md` per the *Reference routing* rules above and follow it exactly, on every entry into this step.

Before the first presentation of each draft whose working-draft file landed — the first draft, or a redraft for a different option at a Step 2 *Settled approach* re-ask — run that draft's first round after the draft checks, on every run, following `references/step-3-6-audit-dispatch.md`. A later change to the same draft runs a round only when the user elects one at Step 4.

### Step 4: Review with the user, then create

Load `references/step-4-present-create.md` per the *Reference routing* rules above and follow it exactly, on every entry into this step.

## Runner setup

The portable helper anchor is a single-statement rule for the helpers bundled beside this skill.
Resolve the skill directory inline, in the same statement that uses it, as
`${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}`, whose `:-`
form uses `$CLAUDE_SKILL_DIR` only when it is set and non-empty.
Otherwise substitute the base directory this runner reports in context — e.g. a `Base directory for
this skill:` line. Never capture the anchor into a shell variable that a later statement reads:
some runners' inline-bash marshaling drops a variable assigned in an earlier statement of the same command.
When the harness refuses a command carrying the inline anchor — as its leading token, or as an argument
under a `python3` head — re-issue that one command with the runner-reported skill base directory written
as a literal path where the anchor stood, in the same single statement and with no variable capture.

Normalize a Windows-form base directory before substituting it: run one standalone `wslpath -u '<path>'` (WSL) or `cygpath -u '<path>'` (Git Bash/MSYS2), in that order, and
use its output only if the command succeeds and prints a non-empty path — otherwise substitute the
runner-reported path unchanged.

Run-slug resolve fence. A caller reads the run's kebab-case `<slug>` from turn-one context, else
resolves it through the run-directory registry — this single-line fence, which reads no environment variable:
```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/cleanup-spec-run.sh --resolve-slug --root .
```
Use the slug a `slug=<name>` line prints; on a `slug=unestablished reason=ambiguous candidates=…` line
pick the candidate whose topic matches the story you hold and use its slug;
on any other `slug=unestablished` line derive one from the issue title (e.g. "Add CSV export for
survey results" → `add-csv-export-for-survey-results`).

An unresolvable anchor degrades; it never stops the run — an anchor failure must never block issue creation.
Proceed and let the underlying "No such file" error surface: a `/prflow:docs-verify` pass whose
anchor cannot resolve takes Step 1's degraded arm, and a draft check or audit render that cannot run
takes its own no-result arm.

---

User Story (rough draft): $ARGUMENTS
