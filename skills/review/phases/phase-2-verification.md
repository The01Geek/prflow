<!-- prflow:review-ref phase=2 file=skills/review/phases/phase-2-verification.md start -->
## Phase 2: Checklist Verification

Output: `Phase 2/4: Verifying {N} checklist items...`

### 2.0 Partition by verification_mode

Phase 2 verifies Phase 1's durable artifact `.prflow/tmp/review/<slug>/<run-id>/checklist-iter-<N>.json` (§1.6) — without it Phase 2 has no checklist. Run `prepare` before the first verifier dispatch of each engine entry — the Phase 1 assembly-helper ladder (vendored literal, then the anchor, then `python3 <path>` on a local denial), every operand a literal:

```bash
.prflow/vendor/prflow/scripts/normalize-verdicts.py prepare .prflow/tmp/review/<slug>/<run-id>/checklist-iter-<N>.json --verdicts-dir .prflow/tmp/review/<slug>/<run-id>/verdicts/iter-<N>
```

It wipes the regular files in `verdicts/iter-<N>/` (a stale prior-iteration file can't be read as a fresh verdict), partitions as §2.2's helper will, and prints the plan to stdout, never to a file: `reused` (§2.0.5), `lite` (id and `lite_probe`, §2.1a), `agent` (id and `nonce`, §2.1b), `items_dir` (§2.1b), `missing_fields` and `counts`. Dispatch from the plan; the checklist artifact stays out of this context. A later single-item dispatch inside this entry (§2.2's one-repair loop and re-asks, dispatch-coverage re-entry, the fix loop's bounded recovery) mints its own fresh nonce and never re-runs `prepare` — a re-run wipes the wave's verdict files.

No plan (nothing printed, or no object carrying an `agent` array): Read the artifact and partition it yourself — `verification_mode: "lite"` with a well-formed `lite_probe` is lite (2.1a); everything else, missing/unrecognized included, is agent (2.1b) — mint each agent item's nonce, and wipe `verdicts/iter-<N>/` before the wave.

The lite path is bounded to claims reducing to substring presence/absence — see `checklist-generator.md` for eligibility rules.

Item-side field-completion re-ask (pre-dispatch). A generator miss of a load-bearing normalizer field must degrade to a measurement, not a silent stall. Collect the plan's `missing_fields` — agent items missing `claim_provenance`, and `source_authored` items missing `source_excerpt` — into **one field-completion re-ask** to the `checklist-generator`: pass the offenders back by `claim_signature`, have it return only the completed fields, accept no new items. Write its answer, keyed by the plan's item id (`{"<id>": {"claim_provenance": …, "source_excerpt": …}}`), to `.prflow/tmp/review/<slug>/<run-id>/fields-iter-<N>.json`, then re-run the `prepare` command above with `--fields <that path>` appended: `prepare` writes the fields into the checklist and prints the plan to dispatch from, so the item files carry them (no verdict exists yet to wipe). If that re-run prints no plan, dispatch from the first plan and name the checklist path in every dispatch. This pre-dispatch re-ask runs exactly once; items still missing the field stay normalization-ineligible downstream; those whose raw verdict later comes back FAIL are counted in `{field_defect_fail_count}` (item 6's membership — the label counts only FAILs; a PASS/INCONCLUSIVE survivor carries the marker uncounted).

### 2.0.5 Skip dispatch for reused items

Phase 1 §1.0 already selected the carried items and copied their prior `verdict`, `evidence`, `file_checked` and — when present — `raw_verdict` and `normalized` (the `NORMALIZED (wording-only): ` prefix travels in the copied `evidence`). So Phase 2 decides nothing here: an item tagged `reused_from_iter_prev: true` skips partitioning and dispatch entirely and keeps the verdict it arrived with. Every other item — carried but not reusing a PASS, and every new one — verifies fresh on the paths below.

Output: `Reused {K} of {N} checklist verdicts (carried forward with a prior PASS). Verifying remaining {N-K} fresh.`

### 2.1a Run lite probes directly

For each `lite` item, execute its `lite_probe`:

- `kind: "string_present"` — run `grep -nF -- "<string>" <file>` (or `rg -nF "<string>" <file>` if available). If a `line_range` is present, require at least one hit inside `[L1, L2]` (inclusive). Verdict: PASS if any in-range hit (or any hit when no range), FAIL otherwise.
- `kind: "string_absent"` — run the same grep. Verdict: PASS if no hit; FAIL if any hit.

Use fixed-string mode (`-F`); quote to escape shell-special characters.

Edge cases:
- File missing → record INCONCLUSIVE with `evidence: "file not found"`.
- `lite_probe` field missing despite `verification_mode: "lite"` (malformed item) → promote the item to the agent path; do not silently PASS.
- `grep` exit code 2 (real error, not just no-match) → INCONCLUSIVE with the stderr text in `evidence`.

Source view. Grep the lite probe's `<file>` in the run's commit-bound source view, not the working tree: `<head-view-dir>/<stored_path>` (a base-state probe `<base-view-dir>/<stored_path>`), resolving `<stored_path>` through the view's `inventory.json` (harness-instruction files under a `.src` suffix). Record the view's 40-hex `revision` as the lite result's `view_revision` so the collector can provenance-check it. A path the inventory records `kind: "deleted"` is proven-absent; a path absent from the inventory is unread → INCONCLUSIVE (`file not found`), never a working-tree fallback. When §0.2.8 materialized no view, grep the working tree and omit `view_revision`.

Record the result in the same JSON shape as agent verdicts:
```json
{"id": "VC-N", "verdict": "PASS|FAIL|INCONCLUSIVE", "evidence": "lite probe: 2 hits in lines 113, 117", "file_checked": "path/to/file.py", "view_revision": "<the view's 40-hex revision, omitted when no view was materialized>"}
```

### 2.1b Launch verifier agents

Dispatch barrier. Every subagent dispatch described here is bound by the dispatch-collection requirement in the engine-ground-truth block injected into this run's prompt — read it there (if your prompt carries no such block, collect every dispatch before the turn ends anyway).

Launch the verifier of every fresh agent item from one message, via multiple Agent tool calls, and proceed to §2.2 only once every dispatch of the wave has returned (the dispatch-barrier sentence above is the binding collection rule).

A dispatch the harness refuses at launch — an error result in place of a launched agent, of which `agent thread limit reached` is the known text — is not yet a failed verifier: after the wave returns, re-issue every refused item together in one message, and repeat while each round launches at least one verifier. A round that launches nothing ends its still-refused items as failed verifiers under §2.2, carrying the refusal text as their `response_text` reply, so the pass ends INCONCLUSIVE with evidence quoting it. A launched agent that later fails, times out, or returns a malformed reply is not a launch refusal and takes §2.2's existing paths unchanged.

A self-assessed budget or context state never lowers the dispatch count: a run cannot establish its own remaining context on any tier, so that belief is an unestablished measurement. Dispatch every agent item, or stop at a non-terminal/`Blocked` status naming the step not performed — never a narrowed pass, on any tier.

Reading source in this context never completes an agent item: a caller's no-suite-launch rule is the *dispatched verifier's* method, never a licence to settle the claim here. An agent item completes only when its verifier Wrote the nonce file (§2.2).

Use the Agent tool with `subagent_type: "prflow:checklist-verifier"` for each item. Resolve overrides for `prflow:checklist-verifier` once per Phase 2 per Per-Subagent Model/Effort Overrides above, applying any resolved `model` to the dispatch's Agent-tool `model` override.

Pass each item this prompt and nothing more — the verifier's agent definition carries the whole contract, so re-typing it adds only dispatch time:
```
Item {item id} of {<items_dir>/<item id>.json when the plan carries a non-null items_dir, else this iteration's checklist-iter-<N>.json path}
Verdict file: {VERDICT_FILE}
Head view: {§0.2.8 {VIEW_HEAD} directory and {VIEW_HEAD_REV} 40-hex revision, else "none"}
Base view: {§0.2.8 {VIEW_BASE} directory and {VIEW_BASE_REV} 40-hex revision, else "none"}
```
The verifier Reads that file; never paste the item. A later single-item dispatch in this entry names the same file; after the fix loop's bounded recovery regenerates the checklist, name the checklist path. Spell each path as `prepare` and §0.2.8 took or printed it: no absolute path as a working-directory hint, never a `Repo root: <path>` line. The `Head view`/`Base view` lines — the source-view directories and their 40-hex revisions as literals — bind the verifier's source-view reads and the `view_revision` it stamps on its verdict; when §0.2.8 materialized no view, pass `none` and the verifier falls back to the working tree. Add a further line only for context specific to this item and absent from its checklist entry (a field-completion re-ask names the two fields it wants).

### 2.2 Collect results

Each verifier replies with one line, `<item id> <VERDICT> <verdict-file path>` — its verdict and evidence live in the file. A verifier whose Write failed replies with its fenced verdict JSON instead; one that timed out or failed replies with neither, and the helper below stores that item INCONCLUSIVE unless a verdict file exists at its nonce path (a verifier that Wrote its file then timed out has delivered a verdict).

**Nonce-bound verdict files (agent path).** Each agent item's `<nonce>` is the plan's (§2.0; a later single-item dispatch mints its own); substitute the verdict-file path `.prflow/tmp/review/<slug>/<run-id>/verdicts/iter-<N>/<item-id>-<nonce>.json` for that item's `{VERDICT_FILE}` placeholder (2.1b). Carry each nonce **only** inside that one item's dispatch prompt and, once the wave has returned, the inputs file below (its `nonces` map) — never a sibling's prompt, never a file a running verifier could read. The review runs on PR-author-controlled source, so this binding is the forgery guard: a compromised verifier sees only its own nonce, so only its own item.

**Normalization and the verification artifact are owned by an executable helper — never applied or hand-written in this prose.** After the wave returns, Write one **inputs file** into the run-scoped `.prflow/tmp/` tree carrying only what the helper cannot derive:
```json
{"nonces": {"<item id>": "<nonce>"}, "lite": [<each 2.1a result>], "response_text": {"<item id>": "<reply of a verifier that wrote no file>"}, "pinned_from": {"<item id>": "<first answer's nonce>"}, "views": {"head": {"revision": "<VIEW_HEAD_REV>", "inventory": "<VIEW_HEAD>/inventory.json"}, "base": {"revision": "<VIEW_BASE_REV>", "inventory": "<VIEW_BASE>/inventory.json"}}}
```
Include `views` with the §0.2.8 head/base revisions and inventory paths as literals; the helper then runs the **view-provenance gate** before tallying — a verdict whose `view_revision` is not the bound head or base, is absent, or whose `file_checked` path is absent from that view's inventory and not recorded `deleted` cannot earn PASS (a raw PASS is forced to INCONCLUSIVE, cited evidence never byte-compared). Omit `views` only when §0.2.8 materialized no view (older engine); the gate is then inert.
Then invoke `scripts/normalize-verdicts.py` **as the command's single leading token** — the portable `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/normalize-verdicts.py` anchor resolved inline (the literal vendored `.prflow/vendor/prflow/scripts/normalize-verdicts.py` path in cloud workflows) — with the arguments `<inputs-file> --checklist <this iteration's checklist-iter-<N>.json> --verdicts-dir <its verdicts/iter-<N> directory> --out <the verification artifact path below>`, every path a literal, and **read the helper's printed JSON from the tool result** (no `VAR=$(…)` capture, no shell redirect — the vendored-literal leading-token form **is granted** on the `review` profile, but its review-tier permitted-ness is **unrecorded** — so read a refusal of it as possible and handle it by the everything-else arm below). **Local-tier second rung:** the local classifier routinely denies path-invoked helpers (documented fallback `python3 <path>`), so on a local denial invoke `python3 <resolved helper path>` with the same arguments instead (the interpreter-head ban is cloud-matcher-only); only when both rungs fail does the everything-else arm below engage. The helper partitions the checklist as 2.0/2.0.5 do (reused, lite, agent), reads each agent item's verdict from exactly `<verdicts-dir>/<item id>-<nonce>.json` (LAST `json` fence authoritative), normalizes, **writes the combined array to `--out`**, and prints `written`, the `tally`, the two `counts`, a `needs_retry` list, every `non_pass` entry with its evidence, and `input_warnings`.

One-repair loop over `needs_retry` (each item at most once). For each item the helper lists in `needs_retry`:
- kind `verdict` (a verdict defect — a malformed/absent/non-enum verdict, an id mismatch, an unparseable or fence-missing response): re-dispatch that item once under a fresh nonce replacing its `nonces` entry, and re-run the helper. If the defect persists, take the in-context recovery arm: read that item's reply; when it carries one unambiguous verdict token, add `"recovered": {"<item id>": {"verdict": "<token>", "evidence": "recovered via in-context parse (helper-defect: <shape>)"}}` to the inputs file and re-run — normalization-ineligible; an in-context-ambiguous reply is recovered as INCONCLUSIVE with an evidence line naming the shape and quoting the token.
- kind `auxiliary` — a raw `FAIL` + `generated_paraphrase` agent item the helper flagged for a one-shot re-ask, in **either** shape: an absent/wrong-typed `property_proven`/`inaccuracy_scope` (a field defect), **or** the well-typed contradiction the helper reports as `defect: contradiction:generated_claim_text_but_property_unproven` (`inaccuracy_scope: generated_claim_text` asserting the code is correct while `property_proven` is `false`). **Both fire the same re-ask, and it is not optional**: issue **one field-completion re-ask** requesting only the two auxiliary fields, under a fresh nonce, with `"pinned_verdict": {"<item id>": "FAIL"}` in the inputs file (pinning the raw FAIL to the first response) and the first answer's nonce under `"pinned_from": {"<item id>": "<nonce>"}` (the item keeps that answer's evidence and view binding), and re-run the helper; the helper ignores any verdict token the re-ask returns and normalizes only if the re-ask now positively proves the property. A persisting defect leaves the raw FAIL standing with its `normalization-ineligible` marker; a PASS/INCONCLUSIVE with a defective auxiliary field is never re-dispatched. **The report (Phase 4) names every `needs_retry` item of kind `auxiliary` whose re-ask did not actually run**, so a skipped contradiction re-ask is visible rather than silently carried into the tally.
- kinds `channel` and `helper_internal` (an unreadable nonce file; a contained helper exception): never re-dispatch; record the item normalization-ineligible and surface one warning line with the helper's stderr.

Three-way helper-degradation split (fail-closed, never conflated) — diagnosed by what the invocation printed:
- Results arm — the helper printed its summary JSON: proceed normally (normalized items count as passed). When `written` is null, Write the printed `verification` array to the artifact path yourself.
- Bad-input arm — the helper printed its structured bad-input report (`{"bad_input": true, …}`, the LLM-transcribed inputs file was unparseable/truncated): re-Write the inputs file once and re-invoke; a second bad-input report ends the attempt — proceed with zero normalization by the hand-written artifact below and one warning line naming the transcription failure, never the grant remedy.
- Everything-else arm — anything else printed, including a `No such file`/rc-127 error (a helper-less plugin prints error text, not a silent denial), a Python traceback, any non-zero-exit stderr, and true silence (a matcher denial produces no output at all — a possible denial, never an empty value): perform zero normalization and zero retry classification by the hand-written artifact below, and replace the appended counts line with one warning line quoting what the invocation printed plus the tier-appropriate remedy (cloud grant keys — the review/implement runner allowlists and the profile `TOOLS=` line / `prflow_implement.allowed_tools` — the `prflow_version`/workflow upgrade-together note, and local-tier operator provisioning). The run proceeds — never a stall, never an inferred normalization.

**Dispatch coverage, before the artifact is final.** Read `.prflow/tmp/review/<slug>/<run-id>/verdicts/iter-<N>/` with the Glob tool and compare it against this iteration's fresh agent items. Each one with no file there re-enters 2.1b **once** — that absence is what a run leaves when it settled the claim in this context instead of dispatching — and the helper re-runs over its returned verdict. An item the helper already classified `channel` has spent its repair and is exempt. Never synthesize a file or a nonce: the fix-loop caller's evidence gate grades these files and FAILs a missing one.

The helper's `--out` file is the verification artifact, `.prflow/tmp/review/<slug>/<run-id>/verification-iter-<N>.json` (same `<slug>/<run-id>` and `<N>` as the §1.6 checklist artifact): one combined array (reused + lite + agent), keyed by `id`, holding each item's stored (post-normalization) verdict; a normalized item stores `verdict: "PASS"`, `raw_verdict: "FAIL"`, `normalized: true`, and the `NORMALIZED (wording-only): ` evidence prefix, and counts passed in every tally. Phase 4.2 reads this file for its tallies, so a run that leaves it unwritten leaves Phase 4.2 with no verdicts to tally. Hand-write it with the Write tool only on the two degraded arms: the reused and lite results plus each agent item's raw verdict from its reply line (Read a non-PASS item's verdict file for its evidence; no reply and no file is INCONCLUSIVE, `Verifier agent failed or timed out.`). **The file root is the array itself, never an object wrapping it** — a `{"verification": [...]}` wrapper copies the engine-return shape and grades `review-artifact-malformed`, since the evidence gate reads the root and never unwraps. An empty array `[]` is valid for an empty checklist. Substitute the `<slug>/<run-id>/verification-iter-<N>.json` path literally, never as a `$VAR` expansion (denied on the cloud matcher).

Output, from the helper's `tally`: `Verified: {pass_count} passed, {fail_count} failed, {inconclusive_count} inconclusive ({lite_count} via lite probe, {agent_count} via agent).`

Then append one separate line (never editing the tally line above): `Normalized (wording-only): {normalized_count}; ineligible-on-field-defect FAILs: {field_defect_fail_count}` (replaced by the warning line on the bad-input / everything-else arms).

### 2.3 Update the progress comment (PR-comment surface)

When this run holds a live progress comment (`$WP` set), tick the Phase 2 Blueprint row and append the verification tally to `## Findings (live)` in one PATCH; skip this step entirely when `$WP` is unset. Substitute the tally counts as literals. A refused or failed command gets a `::warning::` and never stops the review. Emit the vendored literal `.prflow/vendor/prflow/scripts/workpad.py progress <comment-id> --tick "Verify checklist" --append "{pass_count} passed, {fail_count} failed, {inconclusive_count} inconclusive"` as a single leading-token statement first; on a `command not found` / `No such file` / exit-127 reading, fall back to the portable anchor `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/workpad.py progress <comment-id> --tick "Verify checklist" --append "{pass_count} passed, {fail_count} failed, {inconclusive_count} inconclusive"` as a single leading-token statement.

Substitute `<comment-id>` with the held `$WP` value as a literal — never `$WP` in the command.
<!-- prflow:review-ref phase=2 file=skills/review/phases/phase-2-verification.md end -->
