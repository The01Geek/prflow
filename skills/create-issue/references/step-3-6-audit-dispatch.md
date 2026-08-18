<!-- prflow:create-issue-ref step=3.6-dispatch file=skills/create-issue/references/step-3-6-audit-dispatch.md start -->
<!-- prflow:create-issue-set step=3.6 part=2 of=3 -->

#### Audit-run bootstrap: `init`, the nonce, and recovery

This audit is the run's first nonce-taking call, so the audit run opens here. Open it with a cold-start `init` — no `--nonce`, that omission being what selects the delete-leftover-first wipe; a `--nonce` on `init` is only for a same-run re-init and needs `--force` over recorded rounds:

```bash
python3 "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/issue-audit-state.py init "<slug>"
```

`init` mints this run's nonce and prints `nonce=…`; hold it and substitute it into every later call — a value you carry, not a shell variable that survives between Bash calls. After a compaction, recover it with `query-nonce "<slug>"`; re-open with a cold-start `init` only when `query-nonce` reports no state.

#### Dispatch exactly one auditor, synchronously

Dispatch exactly one audit subagent, synchronously. Use the Agent tool (`subagent_type: general-purpose` on Claude Code; the runner's equivalent context-isolated subagent tool elsewhere). The normative requirement is behavioral: the dispatch blocks until the subagent's completed result is in hand, and a launch acknowledgment is never treated as the return — on Claude Code, `run_in_background: false` is a current example of meeting it, not the definition. This wait is unconditional, holding on every tier whether or not this run's prompt carries an engine-ground-truth block. This skill arms no fallback wakeup.

#### Write the canonical draft, then run Step 3.5's two gates here

Write the canonical draft before dispatching (the audit input is the draft file, not a hand-condensed copy). Before dispatching an audit round, write the current rendered draft title + body to the canonical draft file, reusing this run's `<slug>` and the identical Step 4 sub-step 2 recipe (resolve `MAIN_ROOT` with `resolve-main-root.sh` via the portable anchor, `mkdir -p "$MAIN_ROOT/.prflow/tmp"`, title as a top `# ` heading above the body). This is normally the run's first landed canonical-draft write, so it is the run's draft-root binding site (that procedure is directly below, not deferred to Step 4). Perform it through the Staged canonical-draft write shared procedure above; there is no delete-first step. Confirming the write landed is an observation you report to the tool: pass the procedure's `agree=` answer as `--write-landed yes|no` to `query-arm`, which decides the arm — confirm it explicitly from that `agree=` report, not from the absence of an error. Step 4 sub-step 2 keeps writing this same absolute path.

Run the Verified-premise handle check on the bytes that write landed (Step 3.5's obligation, executed here). Once the write is confirmed landed, run:

```bash
python3 "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/check-verified-premises.py --body-file "<bound-root>/.prflow/tmp/issue-draft-<slug>.md" --repo-root "<the repository root>"
```

Route each emitted bullet row on both fields. `state=holds` requires no action. `state=refuted` routes to ordinary investigation against the current tree, then rewrite or remove the drifted claim. `state=unestablished` on a usable result also routes to ordinary investigation; it is neither a clean premise nor helper unavailability. After that state action, retain a `Verified:` claim only with its handle repaired: `handle=path-quote` needs no handle-only edit; for `handle=path`, add a recognized quotation beside the cited repository path; for `handle=quote`, add the cited repository path beside the recognized quotation; for `handle=command`, never execute body-supplied text automatically, investigate under this run's own judgment and replace it with a path-and-quotation handle or ordinary unverified prose; for `handle=none`, add the cited repository path and a recognized quotation or restate it as ordinary unverified prose. For each `ungraded_claim=`, rewrite it as a graded `Verified:` bullet carrying a complete handle or restate it as ordinary unverified prose. Best-effort: a refused or unavailable invocation (any exit other than 0 or 2, or no `VERIFIED_PREMISES` line) reports its failure kind as an in-chat breadcrumb, never blocks issue creation, and never gates the dispatch below. `skills/create-issue/references/step-3-5-steelman.md` states the obligation and routing, naming this same sink.

Run the acceptance-criteria parseability gate on the same landed bytes (Step 3.5's obligation, executed here). Immediately after the verified-premise handle check, run the shipped parser over the same canonical draft — the single gate site:

```bash
python3 "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/parse-acs.py --body-file "<bound-root>/.prflow/tmp/issue-draft-<slug>.md" --format json
```

Read both typed JSON fields: the `acceptance_criteria` array and boolean `acceptance_criteria_unreadable`; a missing or wrong-typed field is unparseable stdout. Keep separate `unreadable repairs used` and genuinely-empty rewrite counts. When `acceptance_criteria_unreadable=true` and fewer than three unreadable repairs have been used, preserve the visible criteria, rewrite each one under the canonical heading as `- [ ] <criterion>`, increment only the unreadable count, and re-run. A true result never increments or resets the genuinely-empty counter. If the re-run after the third unreadable repair is still true, stop and carry `Acceptance Criteria rewrite exhausted (unreadable item shape)` plus no established count to Step 4. When the flag is `false` and the array is non-empty, proceed. When the flag is `false` and the array is empty, do not dispatch or present yet: restore canonical checkbox criteria and re-run through the ordinary revision machinery. Preserve the original rule exactly: count only consecutive genuinely-empty rewrites, and after the third such rewrite stop and carry genuinely-empty exhaustion to Step 4. Neither path spends the other's count. Step 4 discloses the applicable exhaustion and requires the explicit file-anyway election before ordinary approval. When the parser cannot run (unreadable helper, non-zero exit, denied invocation, or unparseable stdout), emit an in-chat breadcrumb naming the failure kind and proceed to presentation — this arm never blocks issue creation.

#### Bind the draft root

Bind the draft root here, once the write is confirmed landed — query first, bind only if unbound. Immediately after you confirm the pre-dispatch write landed, read `query-draft-binding "<slug>" --nonce "<nonce>"` and branch on its answer:

- It answers a real absolute root — the run is already bound. Skip the fence, take that `bound=` root as the binding, and proceed.
- It answers the literal `bound=none` with no `reason=` — a legal unbound run. Run the fence below. That first write records its resolved root through the state owner, immutably for the rest of the run:
- It answers `bound=none … reason=foreign-nonce` — take the *foreign-nonce arm* below, never the unbound arm. Do not run the fence.

```bash
python3 "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/issue-audit-state.py record-draft-binding "<slug>" --nonce "<nonce>" --path "$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/resolve-main-root.sh)" --tier main-root
```

Re-resolve the root inline in that statement; never pass `$MAIN_ROOT`. Each ```bash fence is a separate shell, so a variable assigned in the write fence expands empty here and the bind fails closed (`binding-path-not-absolute`). The inline re-resolution is licensed for the binding site only — later write sites read the bound root back from `query-draft-binding` — and the anchor stays expanded inline.

`binding-already-recorded` is a benign, expected outcome. If you ran the fence on an already-bound run, the tool refuses with that breadcrumb: re-read `query-draft-binding`, take the `bound=` root, and proceed as if you had skipped the fence. Never retry it or report it as a problem.

Then forward the bound canonical path to `record-dispatch --write-path` on the file arm (below); a later re-dispatch reads the bound root back from `query-draft-binding`. When the run is legitimately unbound (`bound=none`, no `reason=`, the fence could not bind — the `state-owner unavailable` fallback has no state file), `none` is a decided token, not a path, so never compose a path from it — write to the main root resolved for this turn and take the `bound=none` display arm in Step 4 sub-step 3.

Foreign-nonce arm. When `query-draft-binding` answers `bound=none … reason=foreign-nonce`, load `references/fallback-draft-write-recovery.md` per `references/degradation-routing.md` and take its foreign-nonce arm — never the unbound `bound=none` arm above.

#### Round kind and dispatch scope

Before each audit dispatch, ask which kind the next round takes:

```bash
python3 "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/issue-audit-state.py query-round-kind "<slug>" --nonce "<nonce>" --draft-file "<absolute issue-draft-<slug>.md path>"
```

It answers `kind=discovery|targeted reason=<token> …`. Obey the answer, never choose a kind. On `kind=targeted` only, write the round's dispatch-scope file next:

```bash
python3 "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/issue-audit-state.py write-dispatch-scope "<slug>" --nonce "<nonce>" --draft-file "<canonical>" --path "<bound-root>/.prflow/tmp/issue-audit-scope-<slug>.<digest>.md"
```

It prints `scope_path= scope_digest= basis_digest=`. Pass `--scope-file "<scope_path>"` to the renderer. `record-dispatch` requires `--kind <the kind query-round-kind answered>` on every round, plus `--scope-file` on a targeted one.

A scoped round re-checks resolved claims. A targeted round enumerates *every* finding raised in an earlier round, regardless of resolved status. Only the claim id and its one-line summary travel to the auditor — never the status, prior verdict, disposition or rationale. The tool selects the cold whole-draft kind when there are no earlier-round findings.

#### The dispatch arm and `record-dispatch`

Call `query-arm` and dispatch on the arm it returns:

```bash
python3 "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/issue-audit-state.py query-arm "<slug>" --nonce "<nonce>" --write-landed yes --draft-file "<absolute issue-draft-<slug>.md path>"
```

It answers `arm=file marker=none`, or `arm=embed marker=<write-failed|file-unreadable|digest-unrecorded>`; when the nonce you passed is not the one the record holds, the digest-unrecorded answer carries a third field, `arm=embed marker=digest-unrecorded reason=foreign-nonce`. Pass `--prior-unreadable` when re-dispatching after a `DRAFT-UNREADABLE` return.

Then record the dispatch with `record-dispatch --arm <the answered arm> --kind <the answered kind> --round "<round>"`, adding `--marker <the answered marker>` when one was named and `--scope-file "<scope_path>"` on a targeted round. On the file arm it reads `--draft-file` and — once the draft root is bound — takes `--write-path "<the absolute issue-draft-<slug>.md path you wrote>"` (required of the bound live caller, though the CLI keeps it optional; omission bypasses only the reported-path cross-check), which the tool cross-checks against the recorded binding (`write-path-mismatch` on divergence, `write-path-empty` on empty); on the embed and inline arms it takes the draft bytes on stdin.

A fresh file-arm dispatch also requires its bytes to be recoverable from this run's recorded byte history (`file-arm-requires-staged-write` on refusal). The remedy is the Staged canonical-draft write step 1 — stage those bytes and `record-staged-write` them — after which the identical `record-dispatch` call succeeds. A retry re-dispatch inside an already-open round is not subject to it.

On the file arm it additionally takes the pair `--instructions-file "<instructions path>" --instructions-draft-path "<the same absolute --draft-path you gave the generator>"` — the round's closed regeneration inputs (the tool refuses the pair half-given).

It prints `round=`, `arm=`, `digest=`, `body_digest=`, `instructions_digest=` (when that pair was given), `dispatch_regeneration=<verified|diverged|unverified>` (`unverified` is the environmental-failure token — regeneration could not run: unreadable template or unimportable generator), and — on the embed arm — the `sentinel_open=` / `sentinel_close=` values it generated. When `dispatch_regeneration=diverged`, surface it in chat the same turn, before dispatching the auditor. Step 4's `steering_reason=` rendering remains the end-of-run record. A retry re-dispatch *within* a round reuses the round's write and number; the tool decides whether a call opens a new round.

#### Information diet and the out-of-bounds declaration

Information diet (the whole mechanism — do not widen it). On the file arm the auditor's whole diet is the generated instruction file plus the draft file it names: the instructions carry the draft title and the absolute `issue-draft-<slug>.md` path and instruct the auditor to read that file as the sole draft source before any other repository read, while the Agent-tool prompt carries nothing but the two paths. It omits the drafting conversation, the Step 1 findings report, and the Step 2 derivation artifact. Refer to it as "the draft", never "your draft".

Reasoning artifacts are out of bounds; the draft file is not. On the file arm the generated instruction file — never a clause you add to the dispatch prompt — must declare this run's reasoning artifacts out of bounds, naming exactly these 8 paths and stating that any finding derived from those files is void:

- `.prflow/tmp/issue-derivation-<slug>.md` — the Step 2 derivation record plus this run's evidence-bundle, steelman, and revision-delta sections.
- `.prflow/tmp/issue-step1-<slug>.md` — the Step 1 evidence artifact.
- `.prflow/tmp/issue-audit-<slug>.md` — the audit report.
- `.prflow/tmp/issue-audit-state-<slug>.json` — the state owner's record.
- `.prflow/tmp/issue-audit-state-<slug>.md` — the retired event log. The retired `.md` path stays named even though this skill no longer writes it.
- `.prflow/tmp/issue-draft-<slug>.*.staged.md` — any staged canonical-draft artifact.
- `.prflow/tmp/issue-record-<slug>.md` — the investigation record.
- `.prflow/tmp/issue-audit-scope-<slug>.*.md` — any dispatch-scope artifact. It must persist, its digest being recompared at `record-return`. The glob is total, covering a round's own scope file too.

The generated instruction file `.prflow/tmp/issue-audit-dispatch-<slug>.md` and `issue-draft-<slug>.md` are not on this list; the embed arm names both, per `references/fallback-audit-dispatch-arms.md`.

#### Carriage / identity check (file arm)

File-arm carriage / identity check. The generated instruction file requires the auditor to run `git hash-object --no-filters` on the draft file it read and quote the printed object ID verbatim in its return. **Forward that quoted object ID verbatim to `record-return --carriage-object-id <the ID the auditor quoted>` and obey the classification the tool returns.** Do not compare it yourself: the tool holds the write-time digest and owns the comparison, including its fail-closed treatment of an absent ID. Omit `--carriage-object-id` when the return quoted none — never invent one.

The auditor must quote `git hash-object --no-filters`. The tool hashes via `git hash-object --stdin --no-filters` at every site; only the filter-free form makes the dispatch, auditor-quoted and eligibility digests agree on a host that configures clean/CRLF filters.

When the carriage evidence fails, the tool says why — on stderr. A `record-return` classified `no-parseable-verdict` for absent or mismatched carriage evidence writes a named breadcrumb to stderr; read it before treating the round as unreadable, loading `references/fallback-audit-evidence-degraded.md` per `references/degradation-routing.md` for its carriage arm.

Embed arm (the on-disk draft path is untrusted here). When `query-arm` answers `arm=embed`, the dispatch prompt carries the rendered body itself instead of the path, under its own out-of-bounds list and its own sentinel-bracketed carriage check — both stated in `references/fallback-audit-dispatch-arms.md`, loaded per `references/degradation-routing.md` whenever the tool answers a non-file arm.

#### Generate and dispatch the instruction file

The audit prompt is rendered by `scripts/render-audit-prompt.py`, not hand-emitted. The template, the generic dimension checklist, and the heading-extraction rule live in the committed `skills/create-issue/references/audit-prompt-template.md`; the renderer reads that file (resolved relative to its own location) and prints the arm-appropriate prompt. When that file cannot be read, the run takes the bounded one-round in-chat fallback below, never a silent skip. The orchestrator generates the dispatch instructions to a file (below) and lets the *auditor* run the renderer.

Consumption categories (complete by construction). (i) Every state-owner-routed file-arm audit dispatch — the initial round, same-round retries, boundary-offer rounds, revise-and-reaudit rounds, and Step 4 sub-step 4 re-audits — takes the generated-instructions transport below: the authorized instructions are exactly what the generator emits, and the Agent-tool prompt string is a **generated pointer** naming the instruction file and the draft file and nothing else, so add no framing or scoping to it. (ii) The degraded inline arm and (iii) Step 3.5 item 6's self-check run the renderer orchestrator-side, consuming its stdout under the same positional check. (iv) Step 2's `## Evidence axes` forwarding consumes the renderer's section-extraction mode. (v) The `state-owner unavailable` fallback's single audit round splits by that fallback's two entry classes. The embed arm keeps its own transport in `references/fallback-audit-dispatch-arms.md`.

Generate the canonical dispatch instructions, then write them (file arm). Substitute the bound `<slug>` and the absolute paths you hold; `<instructions path>` is `<the bound draft root>/.prflow/tmp/issue-audit-dispatch-<slug>.md`. Write the renderer's stdout to the instruction path with a shell redirect in the bash fence itself. The redirect truncates the target before the generator runs, so no separate delete-leftover step is needed. The write has landed when the generator exits zero and the file at the instruction path is non-empty; a non-zero exit or an empty file is the instructions-generation-failure route below:

```bash
python3 "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/render-audit-prompt.py dispatch-instructions --slug "<slug>" --draft-path "<absolute issue-draft-<slug>.md path>" --instructions-path "<instructions path>" > "<instructions path>" && test -s "<instructions path>"
```

`test -s` observes that landed criterion's second conjunct — a bash builtin, no external tool — so an empty file routes to the pre-dispatch `instructions-generation-failed` arm rather than a burned round.

Instruction-file lifetime. The instruction file is overwritten at each round's generation (the redirect truncates it) and persists after the run, like the other `.prflow/tmp/` artifacts.

The generated file carries the whole authorized set — the draft title (read by the generator from the draft file), the draft path, the renderer invocation the auditor runs first, the template-file path, the positional two-marker rule, the fallback ladder, the out-of-bounds declaration, and the return contract. The generator emits the `dispatch-pointer:` line on its own stderr, byte-identical to the line inside the file its stdout wrote — read it from that stderr and dispatch with it, no read-back step.

Select the pointer by its `dispatch-pointer:` prefix, never as "the stderr output". A successful run can emit a second stderr line (a resolver breadcrumb), so a positional read would take the wrong line as the auditor prompt. Match the prefix after stripping the block indent, and take the first match.

**If no stderr line carries the prefix**, treat the round as having no usable pointer and take the instructions-generation-failure route below — never dispatch a freehand prompt in its place.

Dispatch with that `dispatch-pointer:` line — its text copied verbatim as the entire Agent-tool prompt (the `dispatch-pointer: ` prefix and block indent are render framing the auditor is told to ignore, so carrying or dropping them is equally conforming). Restate nothing else in the dispatch prompt, and do not hand-edit the written file.

On a non-zero exit or empty output from that command, the round has no hashable instruction file: load `references/fallback-audit-evidence-degraded.md` per `references/degradation-routing.md` and follow its instruction-file-generation arm.

Forward the auditor's two new return lines to `record-return` alongside the carriage object ID: `--instructions-object-id <the ID the auditor quoted for the instruction file>` and `--extra-dispatch-content <yes|no>` from its `extra-dispatch-content:` line. Omit either flag when the return carried no such line — an absent value is evidence the tool needs; never invent one. Do not compare anything yourself: the tool re-runs the generator over the round's recorded closed inputs and owns the comparison. It prints `steering=<established|not-established|unestablished>` and `steering_reason=<token|none>` — the third value and `none` are what a refused completion (no parseable verdict, failed carriage) renders, so parse all three and carry them to Step 4.

A `steering=established` round proves the *instruction content* the auditor read was the canonically-generated set (its `git hash-object` matched a fresh regeneration), and nothing about the Agent-tool prompt string, which is not hashable. Never describe a clean audit as provably steering-free.

Withhold-then-disclose (the whole contract on a non-established round). The coverage-backed clean grounding is withheld — `query-eligibility --mode approve` answers `eligible=no reason=steering-unestablished` — and nothing else changes: the full rendered draft is still presented, the re-audit offer fires (the T2 arm holds with `reason=steering-unestablished`), and on explicit user approval the run files through the Step 4 override election. **Filing is never blocked on any arm.**

#### The rendered audit prompt: markers, extension forwarding, fallback ladder

On the embed arm the auditor's instructions come from `embed --slug "<slug>" --sentinel-open "<sentinel_open>" --sentinel-close "<sentinel_close>"` (the sentinels `record-dispatch` printed), with the full rendered draft body spliced between those sentinels in the dispatch prompt (the renderer never receives the draft bytes). On the degraded inline arm substitute `inline --slug "<slug>"`. The orchestrator's own dispatch-time `render-audit-prompt.py status-only` run is the fail-fast probe and the mismatch comparand for the consumer-dimensions state.

Positional two-marker delivery check (every full-render consumer — auditor-side and orchestrator-side alike). Treat the renderer's stdout as the complete audit instructions only when its first line begins `render-status:` and its last line is exactly `render-end:` — never mere presence anywhere (a decoy interior `render-end:` line must not pass, and a tail-cut after it reads as incomplete). Output whose markers are missing or out of position is handled exactly as no contract output (the fallback ladder below).

The recorded `--consumer-dimensions-appended` value derives from the auditor's returned quote, not the orchestrator's probe. The rendered dispatch-arm instructions require the auditor to quote the `render-status:` line verbatim in its return. A returned `appended` passes the flag to `record-return`; a returned `absent` omits the flag with no marker; a returned `unestablished`, a return with no quoted status line, or a quote that contradicts the orchestrator's own `status-only` probe omits the flag and mandates a `consumer-dimensions unestablished` marker in the in-chat audit summary line (a name distinct from the reserved `degraded` token).

Fallback ladder, and the terminal `template-unreadable` arm. When the renderer produces no output, or output whose markers are missing or out of position, load `references/fallback-audit-evidence-degraded.md` per `references/degradation-routing.md` and follow its fallback-ladder arm.

Dimension-list growth policy. The dimensions are renderer-owned (`render-audit-prompt.py` / `audit-prompt-template.md`); execution-blocking defect classes are reported ahead of authoring-discipline classes, and Adversarial third-party input is a distinct security class that outranks the authoring-discipline dimensions.

Extension forwarding (`## Audit dimensions`) is renderer-owned. The renderer performs the fresh `.prflow/prompt-extensions/create-issue.md` re-load and `## Audit dimensions` extraction natively in-process (reading the file directly in Python, never exec-ing a `.sh` helper, resolving the default extension path from the git repo root per the SHARED REPO-ROOT CONFIG CONTRACT), and its delivery triage agrees with `load-prompt-extension.sh` on every arm (present regular file with a non-empty section → appended; absent and present-but-empty → absent; present-but-unreadable, broken symlink, and present-but-non-regular file → unestablished, never absent). So the orchestrator no longer re-runs `load-prompt-extension.sh` for this hook — the renderer's `render-status:` line carries the {appended, absent, unestablished} answer. The re-load remains mandatory-fresh at dispatch; an `unestablished` status is surfaced, never laundered into the designed absent-heading no-op.

<!-- prflow:create-issue-ref step=3.6-dispatch file=skills/create-issue/references/step-3-6-audit-dispatch.md end -->
