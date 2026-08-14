# `/prflow:create-issue`

This page explains how the issue-shaping skill grounds a proposed change in the repository before asking the user to approve an issue.

## Current behavior

The skill starts with a rough user story or bug report. Its first investigation dispatches `/prflow:docs-verify --report-only` peers over the internal documentation and the rest of the tracked tree, using the resolved internal-doc path as the documentation search-space leg. The findings are captured before clarification or drafting continues.

The skill then clarifies the Definition of Ready, independently expands the solution space, drafts the issue, steelmans the draft against the code, runs a fresh-context audit, shows the complete draft to the user, and creates the issue only after explicit approval.

The documentation pass is a code-exploration input. It reports how the topic works today and exposes unestablished duties; it does not treat existing prose as authoritative or edit the repository in report-only mode.

## The completion tracker

Before it does any of the pipeline's work, a run establishes a seven-slot tracker. The slots are the pipeline's gates, in order: run Step 1's selected arm and write its evidence artifact; clarify the story to the Definition of Ready; draft the issue and pass the no-options gate; steelman the draft against the code and append the steelman record; audit the draft in a fresh context and act on the verdict; present the rendered issue, get explicit confirmation, and create it; and run the gated implement-offer step after creation succeeds. A slot is marked in progress when its step starts and completed only when the step is done, so the tracker is what makes an abandoned or abbreviated pipeline visible rather than inferable. Slot 6 is the creation gate — an unconfirmed run is paused there, not complete — and slot 7 is a post-creation hand-off rather than a gate on creating the issue.

The skill names the tracking tools it can use as an ordered ladder rather than a set: `TodoWrite`, then `TaskCreate`/`TaskUpdate`, then `update_plan`. A run picks only from candidates the runner lists as currently exposed and moves to the next candidate when the one it tried is unavailable. Where a run cannot establish which tools are visible, it tries the candidates in that same order and treats a returned failure as the failure arm. Where no candidate appears in the visible tool list, the run first re-reads any listing the runner already supplied of tools it has not yet exposed and tries any candidate it names, and failing that looks for a discovery mechanism the runner itself advertises — a listed tool whose stated purpose is to find and load tools the runner has not yet exposed — using it to search for the candidates rather than as a candidate itself, before concluding that no task tool is available. The ladder deliberately identifies that mechanism by its purpose rather than by name, because the skill ships verbatim into consumer repositories whose tool surfaces this repository does not control.

Any call the run makes while walking the rungs — the discovery mechanism's call included — that the runner answers with a failure takes the same degrade-and-continue arm the skill's reference-routing rules already define for a failed load: the run holds a breadcrumb naming the failure for emission after the announcement, and continues to the next rung. A discovery call that returns no candidate, or one the run cannot then invoke, counts as that candidate being unavailable — as does a call that returns without a failure but leaves no readable tracker, which the run detects through the tool's own read-back where it exposes one and through its rendered result otherwise — and where neither channel confirms a tracker, including where the tool offers no such channel, that candidate is unavailable too. No rung ends the run.

Once every candidate is exhausted, the run uses the inline checklist fallback, reached through the reference-routing table's fallback row, whose trigger covers no task tool being exposed, an exposed tool that is disabled or unusable, an exhausted ladder, and tool visibility that could not be established. The fallback tracks the same items as a re-rendered in-chat block mirrored to a state file under `.prflow/tmp/`. The slot count lives in the skill root's slot list, which the fallback's narrative prose and the routing row defer to; the fallback's fail-closed arm restates it, because a run rebuilding the checklist from scratch on that arm has no other source for it.

The announcement is ordered against that ladder rather than against its position in the file: a run emits it only once a tracker has been established, and on the inline-fallback path the tracker counts as established the moment the run settles on that fallback. The announcement is then the run's first line of output on every path, save for a breadcrumb a reference load or the consumer-extension load requires at the moment it fails — those two surface a failure where it happens and either can fire before a tracker exists. A failed candidate's breadcrumb is deliberately outside that exception: the ladder holds it for emission after the announcement. The output the skill itself composes after the first line follows it in a stated order — every held failed-candidate breadcrumb, then, on the inline-fallback path, the line naming that fallback and the reason it was reached, then the rendered checklist block — so setup detail never displaces the line that makes a missing tracker visible. A breadcrumb the reference-routing rules require is emitted where that load fails and sits outside the order.

## Why it works this way

Agents plan better when they begin with the repository's current behavior rather than the user's proposed mechanism or stale documentation. The two search-space legs keep internal documentation discovery separate from code discovery while preserving a path from each documented claim to its implementation.

## Boundaries and failure paths

- A docs-verify peer must finish and return its structured findings before clarification begins.
- A missing or unreadable internal-doc population is reported as unestablished, not silently treated as no documentation.
- A report-only peer does not write, commit, push, or dispatch another peer.
- A documentation claim that cannot be confirmed against code remains unconfirmed in the findings and cannot be promoted into the issue as fact.

## Source of truth

- `skills/create-issue/SKILL.md` — issue-shaping orchestration and approval gates.
- `skills/docs-verify/SKILL.md` — documentation-first code exploration and report-only contract.
- `skills/create-issue/references/step-2-clarify.md` — clarification and solution-space expansion.
- `skills/create-issue/references/step-3-5-steelman.md` and `skills/create-issue/references/step-3-6-audit.md` — code-grounding passes.
- `skills/create-issue/references/degradation-routing.md` — which reference loads on which trigger, and the degraded behavior each failed load falls back on.
- `skills/create-issue/references/fallback-no-task-tool.md` — the inline checklist fallback and its state-file mirror.
- `scripts/check-verified-premises.py` and `scripts/parse-acs.py` — verified-premise and acceptance-criteria handling.
- `docs/internal/create-issue-context.md` — runtime context and evaluation evidence.

## Related topics

- [System overview](../architecture/system-overview.md)
- [Documentation](documentation.md)
- [Implement](implement.md)
- [Historical cutovers](../cutovers/)
