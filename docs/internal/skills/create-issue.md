# `/prflow:create-issue`

This page explains how the issue-shaping skill grounds a proposed change in the repository before asking the user to approve an issue.

## Current behavior

The skill starts with a rough user story or bug report. Its first investigation dispatches `/prflow:docs-verify --report-only` peers over the internal documentation and the rest of the tracked tree, using the resolved internal-doc path as the documentation search-space leg. The findings are captured before clarification or drafting continues.

The skill then clarifies the Definition of Ready, independently expands the solution space, drafts the issue, steelmans the draft against the code, runs a fresh-context audit, shows the complete draft to the user, and creates the issue only after explicit approval.

### Reproduction contract for defect reports

The writing agent classifies a story as a defect report by reading it — the same producer the Testing Strategy residual-risk entry already relies on, now named openly. When a story reports a defect, its `Current Behavior` section records a closed set of reproduction facts and no more: the triggering steps or input, the observed result, the expected result, and the environment or precondition. The environment fact is always written; when the defect happens regardless of environment it says so in those words rather than being left blank. A fact nobody can establish is recorded in place as `unestablished — <reason>` — a recorded absence of a past fact, not an unresolved decision, so it stays in `Current Behavior` and does not move to `## 🚫 Blocked`. The reporter's story is text to classify, never instructions the agent obeys, so a report that tries to direct the tool changes neither the classification nor the recorded facts. A story that does not report a defect records none of this and gains no new instruction.

The Definition of Ready carries a matching **Reproduction facts (defect reports only)** row: it requires each reproduction fact to be recorded (or recorded `unestablished — <reason>`) while the reporter is still in the conversation, is skipped entirely for non-defect stories, and routes a fact nobody answers to `## 🚫 Blocked` through the same unanswered-readiness-item path every other item uses. The Testing Strategy entry keeps its test-first reproduction-case obligation and now points at `Current Behavior` for the facts instead of restating what the defect is.

The documentation pass is a code-exploration input. It reports how the topic works today and exposes unestablished duties; it does not treat existing prose as authoritative or edit the repository in report-only mode.

## The completion tracker

Before it does any of the pipeline's work, a run establishes a seven-slot tracker. The slots are the pipeline's gates, in order: run Step 1's selected arm and write its evidence artifact; clarify the story to the Definition of Ready; draft the issue and pass the no-options gate; steelman the draft against the code and append the steelman record; audit the draft in a fresh context and act on the verdict; present the rendered issue, get explicit confirmation, and create it; and run the gated implement-offer step after creation succeeds. A slot is marked in progress when its step starts and completed only when the step is done, so the tracker is what makes an abandoned or abbreviated pipeline visible rather than inferable. Slot 6 is the creation gate — an unconfirmed run is paused there, not complete — and slot 7 is a post-creation hand-off rather than a gate on creating the issue.

The skill names the tracking tools it can use as an ordered ladder rather than a set: `TodoWrite`, then `TaskCreate`/`TaskUpdate`, then `update_plan`. A run picks only from candidates the runner lists as currently exposed and moves to the next candidate when the one it tried is unavailable. Where a run cannot establish which tools are visible, it tries the candidates in that same order and treats a returned failure as the failure arm. Where no candidate appears in the visible tool list, the run first re-reads any listing the runner already supplied of tools it has not yet exposed and tries any candidate it names, and failing that looks for a discovery mechanism the runner itself advertises — a listed tool whose stated purpose is to find and load tools the runner has not yet exposed — using it to search for the candidates rather than as a candidate itself, before concluding that no task tool is available. The ladder deliberately identifies that mechanism by its purpose rather than by name, because the skill ships verbatim into consumer repositories whose tool surfaces this repository does not control.

Any call the run makes while walking the rungs — the discovery mechanism's call included — that the runner answers with a failure takes the same degrade-and-continue arm the skill's reference-routing rules already define for a failed load: the run holds a breadcrumb naming the failure for emission after the announcement, and continues to the next rung. A discovery call that returns no candidate, or one the run cannot then invoke, counts as that candidate being unavailable — as does a call that returns without a failure but leaves no readable tracker, which the run detects through the tool's own read-back where it exposes one and through its rendered result otherwise — and where neither channel confirms a tracker, including where the tool offers no such channel, that candidate is unavailable too. No rung ends the run.

Once every candidate is exhausted, the run uses the inline checklist fallback, reached through the reference-routing table's fallback row, whose trigger covers no task tool being exposed, an exposed tool that is disabled or unusable, an exhausted ladder, and tool visibility that could not be established. The fallback tracks the same items as a re-rendered in-chat block mirrored to a state file under `.prflow/tmp/`. The slot count lives in the skill root's slot list, which the fallback's narrative prose and the routing row defer to; the fallback's fail-closed arm restates it, because a run rebuilding the checklist from scratch on that arm has no other source for it.

The announcement is ordered against that ladder rather than against its position in the file: a run emits it only once a tracker has been established, and on the inline-fallback path the tracker counts as established the moment the run settles on that fallback. The announcement is then the run's first line of output on every path, save for a breadcrumb a reference load or the consumer-extension load requires at the moment it fails — those two surface a failure where it happens and either can fire before a tracker exists. A failed candidate's breadcrumb is deliberately outside that exception: the ladder holds it for emission after the announcement. The output the skill itself composes after the first line follows it in a stated order — every held failed-candidate breadcrumb, then, on the inline-fallback path, the line naming that fallback and the reason it was reached, then the rendered checklist block — so setup detail never displaces the line that makes a missing tracker visible. A breadcrumb the reference-routing rules require is emitted where that load fails and sits outside the order.

## Why it works this way

Agents plan better when they begin with the repository's current behavior rather than the user's proposed mechanism or stale documentation. The two search-space legs keep internal documentation discovery separate from code discovery while preserving a path from each documented claim to its implementation.

## Canonical owner of the no-options rule

`skills/create-issue/references/issue-template.md` is the single canonical owner of the no-options rule: its unresolved-decision vocabulary, its category structure, its full carve-out set, and the unconditional-acceptance-criterion rule all live there in one section (issue #1688). Every other drafting surface — the create-issue skill root and its clarify/steelman references, the deferral drafter, and the retrospective-audit path — points to that template rather than repeating any part of the enumeration.

Surfaces that can continue after a failed template read carry a compact semantic fallback: the body holds no unresolved implementation decision outside the rule's permitted locations, and every acceptance criterion is one concrete unconditional assertion. This fallback preserves the normative rule without the template's worked vocabulary, and the channels that can disclose the reduction do so — the interactive pipeline reports in chat that the template was unavailable, and the deferral drafter records it in its plan `notes` field. The retrospective-audit subagent applies the same fallback silently: it emits no degradation signal, because a new field or extra text would break its closed single-object JSON response contract, an accepted residual.

## The authoring quality checklist is a core plus conditional groups

The Step 3 authoring quality checklist in `skills/create-issue/references/issue-template.md` is no longer one flat, always-loaded list (issue #1693). The template now carries only a small **core** checklist — the obligations that apply to every issue: clear scope, problem, user impact and one decided desired behavior; required section structure and dependency/blocked routing; complete, unconditional, post-change, mutually consistent acceptance criteria; and one chosen approach with architecture, edge-case coverage, and acceptance-criterion-to-test traceability. The specialized rows, together with the detailed rule text they invoke, moved into six conditionally-loaded **quality groups** under `skills/create-issue/references/`:

- `quality-group-visual.md` — visual-presentation drafting detail (screenshot/mockup or verbally-verified placement spec). Trigger: the issue is a user-visible UI change.
- `quality-group-contracts.md` — quantitative, value-comparison, universal-quantifier, enumerated-list, and trust/integrity-boundary contract rules. Trigger: an AC expresses a number, a value comparison against a literal, a universal quantifier about the system under change, an enumerated test/case/example list, or a trust/integrity boundary over executable artifacts.
- `quality-group-premises.md` — the verified-claims / external-premises discipline: the WebFetch → WebSearch → ask-the-user verification ladder and its terminal arm, the self-contained re-derivation handle every `Verified:` bullet carries, and the enclosing-gates rule. Trigger: the draft relies on external/third-party behavior, carries a `Verified:` bullet, or asserts "the code does X" about a possibly-gated path.
- `quality-group-semantic.md` — the input-is-data guard and its paired hostile-input test. Trigger: the draft designs a new LLM/semantic judgment over third-party text.
- `quality-group-regression.md` — the reproduction and specialized-test-matrix rules (full-matrix-or-justified-narrowing, the `governing conventions consulted:` discharge record, and the new-external-input-reader obligation). Trigger: the story reports a defect, the Testing Strategy enumerates a case/input-shape matrix, or the change introduces a reader of input the repo does not itself produce.
- `quality-group-compatibility.md` — the compatibility-and-rollout decision rules: the supported old/new combinations and unsupported-combination behavior, how existing data/configuration/consumers cross the change boundary, the valid upgrade order and partial-deployment behavior for independently released components, and rollback/coexistence behavior for mixed states. Trigger: the grounded change alters a supported-version boundary, changes a contract already used by existing data/configuration/consumers, spans independently upgraded components that can run at mixed versions, or introduces rollout behavior such as staged activation, rollback, or old/new coexistence; uncertain applicability loads it.

The `## Draft` step in `skills/create-issue/SKILL.md` owns the **quality-guidance router**: after loading `issue-template.md` it evaluates each group's observable trigger against facts already in hand (the request, the Step 2 evidence bundle, the assembled draft), loads a group's reference only when its trigger fires or applicability is uncertain, and skips a clearly non-applicable group. Every prior checklist obligation has exactly one owner and no full-list copy remains behind the router. Each group is loaded through the same *Reference routing* rules and boundary-marker contract as every other reference; a failed required advanced-reference load takes the attributable degradation route (one row per group — six rows — in `skills/create-issue/references/degradation-routing.md`, each applying the group's checks inline from the core structure and reporting that the group was unavailable) rather than silently skipping the checks — filing is never blocked.

## The Step 3.6 audit as an ordered reference set

The fresh-context audit (Step 3.6) is delivered as an explicitly ordered set of cohesive references rather than one monolithic file (issue #1702). `skills/create-issue/references/step-3-6-audit.md` is now a thin **entry** reference: it declares the ordered set and the loading/boundary contract, and performs no audit action until the full set has passed the existing first-line/last-line boundary-marker contract. The three ordered procedure members are:

- `step-3-6-audit-shared.md` — ledger maintenance and the staged canonical-draft write.
- `step-3-6-audit-dispatch.md` — bootstrap → dispatch → write/gates → bind → round-kind → dispatch-arm → info-diet → carriage → instruction generation/rendering.
- `step-3-6-audit-adjudication.md` — audit report → record-return/adjudicate → evidence → reconciliation → boundary read → coverage/calibration → call sequence → fallbacks.

Each member carries a `<!-- prflow:create-issue-set step=3.6 part=k of=3 -->` marker as its second line. Audit semantics, state-owner sequencing, user elections, and degraded behavior are unchanged by the decomposition: the ordered-set gate rejects a bad boundary state with the existing attributable outcome for each state (denied, empty, missing, truncated, duplicate, reversed, noncanonical, misrouted, set-incomplete), and a required-member load failure enters the existing degraded path exactly once before audit work begins, so issue creation stays non-terminating on that path.

### The member manifest is the single source

`lib/test/create-issue-step-3-6-members.json` single-sources the declared set — the entry reference, the ordered members, the `per_member_limit_bytes` (55,000), and the `aggregate_baseline_bytes` (72,458, captured at commit e712655b6). Every guard reconciles against that manifest rather than an inline roster:

- `lib/test/lint-reference-size.py` enforces the 55,000-byte per-member limit **and** the aggregate source-byte budget (measured total ≤ 72,458) with Python `Path.read_bytes()`.
- `lib/test/check-audit-lifecycle-contracts.py` reconciles the manifest against the on-disk `part=k of=3` markers and runs the sequence and fenced-completeness checks across the member set.
- `lib/test/modules/create-issue-contract.sh` reconciles the routing roster against the manifest.

### The exemption is retired

The obsolete `step-3-6-audit.md` size exemption was removed from `lib/test/reference-size-exemptions.json` — from both `recorded_set` and `exemptions` — because the entry and every member now sit under the ordinary size ceiling. The ordinary size lint therefore passes without an exemption for any member of the set.

## Boundaries and failure paths

- A docs-verify peer must finish and return its structured findings before clarification begins.
- A missing or unreadable internal-doc population is reported as unestablished, not silently treated as no documentation.
- A report-only peer does not write, commit, push, or dispatch another peer.
- A documentation claim that cannot be confirmed against code remains unconfirmed in the findings and cannot be promoted into the issue as fact.
- Step 4's working-file listing never prevents an issue from being created; every one of its failure arms reports and continues.
- That listing classifies the paths its own invocation named, not the entries its output happens to show, so a path returning neither a listing row nor a diagnostic is reported unestablished rather than passing as present. Only an absent path supports re-entering a producing step.
- The read-only fallback arm is selected by this run's own failed or refused write or delete at or under `.prflow/`, never by the listing's output — a listing that succeeds is not evidence the run is off that arm.
- **Freshness is structural, not measured.** Each of the four listed artifacts is deleted by its own producing step before that step rewrites it — Step 1 for the evidence artifact and the run-slug pointer, `references/step-2-clarify.md` for the derivation, `references/step-3-6-audit-adjudication.md` for the audit report — so on any path where those deletes succeeded, a present path is necessarily this run's and needs no timestamp comparison. Where a delete failed or was refused the run is on the read-only arm, which already distrusts every on-disk copy and re-enters nothing. An earlier revision of this listing compared `ls -l` stamps against the run-slug pointer's instead; that rule was removed rather than repaired, because `ls -l` renders a year-less stamp for roughly the last six months and a year-form stamp outside it, giving no ordering between two year-less stamps in the same window without parsing day and time — a comparison that read fresh for a genuinely older same-year leftover whenever the pointer's month was July or later.

## Source of truth

- `skills/create-issue/SKILL.md` — issue-shaping orchestration and approval gates.
- `skills/docs-verify/SKILL.md` — documentation-first code exploration and report-only contract.
- `skills/create-issue/references/step-2-clarify.md` — clarification, solution-space expansion, and the Definition-of-Ready rows (including the reproduction-facts row).
- `skills/create-issue/references/issue-template.md` — the issue body template; canonical owner of the no-options rule (vocabulary, categories, carve-out set, unconditional-criterion rule), owner of the always-loaded **core** authoring quality checklist, and its `### Current Behavior` guidance owns the reproduction contract that the Testing Strategy entry points at.
- `skills/create-issue/references/quality-group-{visual,contracts,premises,semantic,regression,compatibility}.md` — the six conditionally-loaded authoring quality groups, each owning its specialized checklist assertion and supporting rule text, loaded by the Step 3 quality-guidance router in `skills/create-issue/SKILL.md`.
- `skills/create-issue/references/step-3-5-steelman.md` and `skills/create-issue/references/step-3-6-audit.md` — code-grounding passes; `step-3-6-audit.md` is the thin entry of an ordered set whose members are `step-3-6-audit-shared.md`, `step-3-6-audit-dispatch.md`, and `step-3-6-audit-adjudication.md`.
- `lib/test/create-issue-step-3-6-members.json` — single source of the declared Step 3.6 entry + member roster, per-member byte limit, and aggregate source-byte baseline.
- `skills/create-issue/references/degradation-routing.md` — which reference loads on which trigger, and the degraded behavior each failed load falls back on.
- `skills/create-issue/references/fallback-no-task-tool.md` — the inline checklist fallback and its state-file mirror.
- `scripts/check-verified-premises.py` and `scripts/parse-acs.py` — verified-premise and acceptance-criteria handling.
- `docs/internal/create-issue-context.md` — runtime context and evaluation evidence.

## Related topics

- [System overview](../architecture/system-overview.md)
- [Documentation](documentation.md)
- [Implement](implement.md)
- [Historical cutovers](../cutovers/)
