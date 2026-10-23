# Reference: Engine Entry (shared by Step 1 and the Step 2.6 shadow)

The `prflow:review-engine` agent, or on the inline arm the loop, executes this procedure for one engine entry. The dispatch prompt supplies the operands — `entry_kind` (`primary` or `shadow`), `iteration` `<N>`, `run_id` (`<run-id>`), `phase_range_max = 4.3`, `head_override`, `progress_surface`, `issue`, `pr`, `prior_diff_head`, `prior_findings` and `<loop-skill-dir>`, each `none` when absent. Root every artifact under this checkout's `.prflow/tmp/review/<slug>/<run-id>/`.

## Capability check (`fanned-out` and `unavailable` are the complete `dispatch_mode` set)

First: holding a delegation tool, follow the sections below with the Phase 3 roster fanned out and return `dispatch_mode: fanned-out` and the return file's path. Holding none, write that return file carrying `dispatch_mode: "unavailable"` and a `tools_held` array (empty when you can name none) and return that.

## Engine-directory resolution

Resolve the repository root once with `git rev-parse --show-toplevel` (else the current directory), then `Read` `<candidate>/SKILL.md` for candidates 1 and 2 in one message, and for candidate 3 only when neither is selected:

1. `<repo-root>/.prflow/vendor/prflow/skills/review`
2. `<repo-root>/.devflow/vendor/devflow/skills/review` (superseded, still accepted)
3. `<loop-skill-dir>/../review` (the running plugin's own engine)

Selection turns on resolution alone, in list order. A path the reader reports as non-existent is absent: advance. Any other answer that affirms the path exists — a permission denial on that path included — selects it over every later candidate. A refusal raised before the path was consulted, or an answer you cannot classify, selects nothing and advances. Report every candidate you advanced past and why.

The selected engine is usable only once its completeness is established. A permission failure, reader error, oversize error or empty body on the selected candidate leaves completeness unestablished — never fall through to a later candidate. After a read that appears whole, issue one more bounded read starting at the line after the last one held: only the reader reporting the file shorter than that position, or returning nothing, establishes end-of-file; returned content (a blank line included) means the held read was truncated — append it and confirm again. A partial-view read with an `offset`/`limit` continuation is paged forward, then put through that same confirming read, which alone terminates the paging. A reader with no start position, a refused or erroring confirming read, a reply not attributable to the requested position, and a gap in the pages each leave completeness unestablished.

- No candidate selected → fatal: report that no review engine was found, naming the candidates advanced past and `/prflow:init` as the remedy. Never paraphrase the phases or use another plugin-cache copy.
- Completeness unestablished → stop at `engine-root: incomplete`, naming that `SKILL.md` path; review nothing. A dispatched engine returns this terminal instead of a `fanned-out` payload.

The engine root's `<skill-dir>` is the located `<engine-dir>`; do not re-resolve the runner's skill-directory anchor, which names review-and-fix here.

## Execute the engine

Execute the engine's Phases 0 through 4.3 verbatim — never improvise the Phase 3 agent prompts or substitute your own verdict criteria — and skip Phase 4.4. Bind the operands as Phase 0.2's caller operands: a numeric `pr` runs PR mode with `head_override = local`, `pr` `none` current-branch mode. `prior_findings` is the `prior_phase3_findings` file path; Phase 1.0 takes `prior_diff_head`.

**Run no project test runner** or test file under any command head; a dispatched verifier settles a test claim by reading source.

On the shadow entry, a reviewer whose dispatch errored, or whose return has no assessment or verdict prose (under any heading) or raises a finding without a `defect_signature` failed: when exactly one failed, re-dispatch it once with the same prompt before Phase 3.2, and list in `phase3_failed_agents` every reviewer still failed.

## Return-file field set

Write this entry's `checklist-iter-<N>.json`, `verification-iter-<N>.json` and the per-item verifier files under `verdicts/iter-<N>/`, then the return file `engine-return-<entry>-iter-<N>.json` (`<entry>` is `step1` for a primary entry, else `shadow`). On `fanned-out` it carries `root_completeness: "established"`, `phase3_findings`, `phase3_dispatched`, `expected_reviewers`, `plan_eligible`, `plan_exclusions`, `phase3_failed_agents`, `diff_profile`, `cap_drops`, `acceptance_criteria` (Phase 0.4's reviewer-facing value, `""` when none resolved), `phase4_demoted`, `reject_drivers` and `criterion_exempt` (Phase 4.3's), `diff_produced_at_head`, the engine `verdict`, its complete Phase 4.1 `report`, and — whenever Phase 1+2 ran — the final `checklist`.

**Type only what you authored.** On `fanned-out`, the run directory's `verdict-body.md` holds the report Phase 4.1 produces (when 4.1 left it unwritten, write no return file); Write `engine-return-<entry>-iter-<N>.authored.json` holding every field above except `dispatch_mode`, `diff_produced_at_head`, `checklist`, `report` and, when Phase 0.4 resolved any criteria, `acceptance_criteria`, then run (portable anchor form on not-found):

```bash
.prflow/vendor/prflow/scripts/review-dirty-tree.sh engine-return --run-dir .prflow/tmp/review/<slug>/<run-id> --entry <entry> --iteration <N> --head <head-sha> --authored .prflow/tmp/review/<slug>/<run-id>/engine-return-<entry>-iter-<N>.authored.json --report-file .prflow/tmp/review/<slug>/<run-id>/verdict-body.md
```

`<head-sha>` is the commit Phase 0.2 produced `diff.patch` at; add `--no-checklist` when Phase 1+2 did not run. `status: "ok"` is the validation. `status: "error"` → fix the authored part or `verdict-body.md` its `reason` names and re-run; a `verification` other than `joined` or `skipped` means repair `verification-iter-<N>.json` and re-run. No JSON from either form → Write the whole return file yourself.

Return only your `dispatch_mode` and this return file's path, as your last action, with no other text.

<!-- END engine-entry.md -->
