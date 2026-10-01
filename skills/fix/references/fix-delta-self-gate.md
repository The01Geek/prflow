# Reference: Direct-pass fix-delta gate (Step 8 sub-item)

Read by the Step 8 sub-item of a direct pass that recorded at least one `fixed` disposition. It reuses the review-and-fix loop's fix-delta gate as review policy only: read `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../skills/review-and-fix/references/fix-delta-gate.md` as a file and take exactly two parts of it — the checks list (from "The gate's checks explicitly include:" through the interpreter-probe paragraph) and its blinding sentence ("withhold the loop's prior findings, fix decisions, and fixer reasoning from the subagent's prompt"). Everything else in that file — dispatch barrier, extension carry, over-grade routing, iteration cap and promotion, `iter-<N>.json`, shadow carry, push hand-back — is loop machinery and does not apply here.

## Delta

`<pre-fix-head>` is the SHA `git rev-parse HEAD` printed immediately before the pass's first IMPLEMENT edit. The delta is `git diff <pre-fix-head>` over tracked paths plus every untracked file `git status --porcelain --untracked-files=all` lists (read each untracked file whole). Every gate run, re-gates included, uses this cumulative delta.

## Prompt

Dispatch one `general-purpose` subagent that does not itself fan out. Its prompt holds only: the delta, an instruction to read the consumer code the delta calls into and, for each assertion the delta adds, that assertion's target file, and the two parts of `fix-delta-gate.md` above, applied as written with "the fix delta" read as this pass's delta. Apply the blinding sentence to this pass: the prompt carries no caller-supplied finding, no disposition, none of your reasoning, and no consumer prompt-extension text. Ask for each finding's check, severity (Critical, Important, Suggestion, Minor), location and evidence.

## Routing

- Critical or Important finding → review feedback under the Response Pattern: verify it, then fix it or push back with evidence, and record it in the disposition ledger as `fixed` or `pushback`.
- Added-assertion attribution finding, any severity, an unestablished (unreadable-target) one included → correct the assertion in this pass (`fixed`) or record `pushback`.
- Suggestion or Minor finding from the other checks → list it in the report as advisory; no re-fix.
- A `fixed` gate finding re-enters Step 8 items 1–3 — item 3 re-runs and re-records the suite, so the record item 5 reads carries the post-re-fix candidate identity — then the gate re-runs over the cumulative delta. At most 2 re-fix attempts per pass; a Critical, Important or attribution finding still raised after the second is `unresolved`.

## Outcome line

Render exactly one `fix-delta gate: <outcome>` line. Take the highest-precedence outcome present, `unresolved` > `not verified` > `pushed back` > `refixed` > `clean`, and list in `<finding>` every finding at that outcome:

- `clean` — the gate raised no Critical or Important finding and no attribution finding.
- `refixed` — every such finding was fixed and the last re-gate was clean.
- `pushed back: <finding>` — a finding recorded `pushback`.
- `unresolved: <finding>` — a finding still raised after the attempt cap.
- `not verified (<reason>)` — one of the failure arms below.

`skipped (no fix applied)` is rendered by the root, never here.

## Failure arms

Each renders `not verified (<reason>)` with its own reason, never `clean`:

- `fix-delta-gate.md unreadable` — the checks list or blinding sentence could not be read.
- `pre-fix head not captured` — no `<pre-fix-head>` SHA was recorded before the first edit.
- `git diff failed` / `git status failed` — the command exited non-zero.
- `untracked file unreadable` — an untracked file the delta lists could not be read.
- `disposition ledger write failed` — a gate finding's `fixed` or `pushback` record could not be written.
- `subagent dispatch unavailable` — the runner cannot dispatch a subagent.
- `gate subagent failed after one re-dispatch` — the subagent errored or returned no usable finding list twice; re-dispatch once with the same prompt first.
- `empty delta despite a fixed disposition` — the delta is empty although the ledger holds a `fixed` disposition; do not re-dispatch.

<!-- END fix-delta-self-gate.md -->
