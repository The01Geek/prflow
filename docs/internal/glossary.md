# Glossary

<!-- verified-against: 26c9ad96d 2026-08-25 -->

This page defines the repository-private terms used across the internal documentation. It is for a reader — human or coding agent — who meets one of these words for the first time. When you introduce a new repository-private term in any internal doc, add its definition here in the same change.

| Term | Meaning |
|---|---|
| **Workpad** | The single marker-tagged GitHub issue comment `/prflow:implement` maintains as the run's durable progress surface. Maintained through `scripts/workpad.py`. |
| **Verification checklist** | The list of every verifiable claim a diff makes, generated and then verified against source by the review engine. |
| **`defect_signature`** | The tuple used to mechanically corroborate findings across reviewers; `skills/review/phases/phase-3-agents.md` defines its fields and, at Phase 3.2, the corroboration rule over them. |
| **Shadow review** | A structurally-independent re-review run before declaring a clean approval, to audit the loop's self-agreement. |
| **Scope-Acknowledged Findings** | The contract that lets a deliberately-deferred finding be tracked in a follow-up issue instead of re-raised as a REJECT. |
| **Retrospective loop** | The weekly evaluator/optimizer pass that reads merged bot-PR evidence and proposes interventions. |
| **Clean gate** | The mechanical filter that lets clean PRs be processed with zero LLM cost in the retrospective loop. |
| **Thin install** | A cloud-tier install that doesn't commit the plugin tree; it's fetched at runtime, pinned to `prflow_version`. |
| **Vendoring / materialization** | Placing the plugin at `.prflow/vendor/prflow/` so the CI sandbox can reach its helpers. |
| **Partition invariant** | The rule (test-enforced) that PRFlow triggers always negate `@claude`, so PRFlow and Anthropic's Claude app never double-fire. |
| **Local tier / cloud tier** | Skills run in your editor (no infra) vs. autonomous GitHub Actions automation. |
| **Pin** | A test-suite assertion that a specific literal is present in (or absent from) a specific file. The suite uses pins to keep coupled copies of a fact from drifting apart. |
| **Pin corpus** | The census of all source-presence pins. The frozen snapshot lives in `.prflow/logs/pin-corpus-inventory.tsv`; per-pin decisions are changed in `lib/test/pin-corpus-adjudications.tsv`; `lib/test/pin-corpus-lint.py` enforces the rules over them. |
| **Adjudication** | A recorded per-item decision that answers a policy question for exactly one occurrence — for example, one pin's "does any tool read this content?" answer, or one cloud command shape's allow/deny record in `docs/internal/cloud-allowlist.md`. An absent adjudication means unanswered, never "no". |
| **Shard** | One member of the CI test-suite partition. `lib/test/run-shard.sh --list-shards` names the population; `lib/test/run-parallel.sh` runs them concurrently in one checkout; `lib/test/shard-tally.py` recombines the results. The `monolith` shard runs the serial `lib/test/run.sh`. |
| **Single flight** | The suite-run reuse coordinator `scripts/verification-flight.py`. It holds a durable status handle so a clean suite result for the current tree is reused instead of re-executed. |
| **Seam** | A boundary between two cooperating surfaces where behavior can silently diverge — for example, the per-agent-effort boundary probed by `docs/internal/agents-seam-probe.md`, or the boundary between two skills that must agree on one contract. |
| **Rung** | One step of an ordered fallback or decision ladder. The tier ladder in `CLAUDE.md` and the helper-invocation ladders in the skills are read rung by rung, taking the first rung that applies. |
| **Foreclosed** | A review finding answered in advance by an already-shipped disclosure, so it is settled rather than unresolved. A foreclosed finding's repeat skip does not escalate. |
| **Byte-identity** | The requirement that two copies of a deliberately-mirrored block stay byte-for-byte equal, usually enforced by a test that compares them. |
| **Cutover** | A historical implementation record under `docs/internal/cutovers/`, describing how a migration was performed. Cutovers are never the source of truth for current behavior. |
| **Growth record** | A cutover record with frontmatter `kind: growth`: a byte-budget justification memo for a prompt-surface size increase. Its figures are a snapshot at merge time and say nothing about current behavior. |
| **Prompt extension** | A consumer-owned markdown file under `.prflow/prompt-extensions/` that a skill loads at run start through `scripts/load-prompt-extension.sh` and appends to its own prompt. The sole channel for consumer policy into a skill body. |
| **Grounding block** | The engine-ground-truth block `scripts/render-grounding-block.sh` renders once into every cloud prompt. It carries the security-sensitive prompt-injection defenses and the run's resolved tool list. |
| **Provenance label** | The hardcoded `PRFlow` GitHub label (superseded spelling `DevFlow`) stamped on every issue and PR the automation creates, which the retrospective scan selects on. |
