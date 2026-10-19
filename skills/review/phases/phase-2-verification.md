<!-- prflow:review-ref phase=2 file=skills/review/phases/phase-2-verification.md start -->
## Phase 2: Checklist Verification

Output: `Phase 2/4: Verifying {N} checklist items...`

Phase 2 verifies §1.6's checklist with `.prflow/vendor/prflow/scripts/normalize-verdicts.py`. When `prepare` or `collect` prints anything but a `status: ok` line, verification is unestablished: stop, quoting what it printed; under `/prflow:implement` that stop is Blocked.

### 2.0 Plan

Before the entry's first verifier dispatch, and never again in it (a re-run empties the wave's verdict files):

```bash
.prflow/vendor/prflow/scripts/normalize-verdicts.py prepare --contract 2 --checklist .prflow/tmp/review/<slug>/<run-id>/checklist-iter-<N>.json
```

It writes one item file per fresh item and prints `agent` (the ids to dispatch), `reused` (carried PASSes, not dispatched), `items_dir`, `verdicts_dir`, `disclosures`, `pr_body`, `rejections` and `warnings`. Hold `disclosures`, `pr_body` and `rejections` for Phase 4's `Run details`; report each warning. Output, from `counts`: `Reused {reused} of {N} checklist verdicts; verifying {agent} fresh.`

### 2.1 Launch

In one message, launch one `prflow:checklist-verifier` Agent call per `agent` id (resolved `model` override), each prompt exactly `Item: <items_dir>/<id>.json`, copying the helper's absolute `items_dir`. On §1.2's local tier follow that message, and each retry round's, with a foreground Bash call (timeout 600000 ms) over its verifiers and earlier ones yet to hand back:

```bash
.prflow/vendor/prflow/scripts/normalize-verdicts.py wait --verdicts-dir <verdicts_dir> --expect <id>.a1 <id>.a1... --deadline 540 --idle 30
```

Retain each actual dispatch's Agent ID with its item and current attempt, regardless of reply format. Collect replies before §2.2. Refused launches establish no ID: after the wave, retry them together while each round launches at least one; keep the refusal text for items still refused.

Dispatch every `agent` id: a self-assessed budget or context state never narrows the pass, and reading source never settles an item — only its verifier's answer does.

### 2.2 Collect

Write `.prflow/tmp/review/<slug>/<run-id>/normalize-inputs-iter-<N>.json` as `{"response_text": {"<id>": "<reply>"}, "agent_id": {"<id>": "<current attempt's Agent ID>"}}` whenever either map has entries or the file exists, and never otherwise, rebuilding `agent_id` at each write: on §1.2's local tier, each item's current Agent ID unless the most recent wait whose `--expect` named that attempt listed it in `present`; on the cloud tier, every current Phase 2 Agent ID. Put every reply other than the normal one-line `<id> <VERDICT> <verdict-file>` handback verbatim in `response_text`. Rewrite the file whole, preserving other items' replies and any `reverify` key even when both maps are empty. Phase 4.1 disputes keep their separate collection rule, outside these maps and this retry loop. Then:

```bash
.prflow/vendor/prflow/scripts/normalize-verdicts.py collect --contract 2 --checklist .prflow/tmp/review/<slug>/<run-id>/checklist-iter-<N>.json
```

It writes `verification-iter-<N>.json` and prints `tally`, `counts`, `needs_retry`, `non_pass`, `findings` and `input_warnings`. Send each `delivery` entry one `SendMessage` to its `agent_id`: `Delivery only: if you are still verifying, finish your verification first; then Write your answer as verdict JSON to <verdict_file> unless it exists. If you already returned JSON, keep it unchanged. Do not re-verify.` Never write that file yourself. Keep its original ID and attempt even if delivery fails.

Re-dispatch other entries carrying an `item` with `run_in_background: false`, prompt `Item: <item>`. First remove that item's old reply and ID; record a new ID only for a launched agent. Send one `collect`'s delivery `SendMessage` calls and re-dispatch Agent calls in one message; on §1.2's local tier end it with §2.1's wait over every delivery and re-dispatch entry's `verdict_file` basename minus `.json`. Collect replies, update the snapshot, and re-run `collect` until no entry carries an `item`. Report each entry without an `item` and each `input_warnings` line, and hold the last run's `findings` for §3.2.

Output, from `tally` and `counts`:
- `Verified: {pass} passed, {fail} failed, {inconclusive} inconclusive.`
- `Normalized (wording-only): {normalized_count}`

With `$WP` set, tick the progress row with the tally (a failure gets a `::warning::` and never stops the review):

```bash
.prflow/vendor/prflow/scripts/workpad.py progress <comment-id> --tick "Verify checklist" --append "{pass} passed, {fail} failed, {inconclusive} inconclusive"
```
<!-- prflow:review-ref phase=2 file=skills/review/phases/phase-2-verification.md end -->
