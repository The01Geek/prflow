<!-- prflow:review-ref phase=4.5 file=skills/review/phases/phase-4-5-telemetry.md start -->

### 4.5 Run telemetry + effectiveness trace

This step is gated by BOTH `prflow_review_and_fix.efficiency_telemetry_enabled` (read via `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .prflow_review_and_fix.efficiency_telemetry_enabled true`; shared with `/prflow:review-and-fix`) AND the caller's requested phase range. Skip it entirely — no telemetry, trace, or record — when the flag is `false`, or when the caller passed `phase_range_max = 4.3` (Phase 0.2 "Caller phase-range", every `/prflow:review-and-fix` engine entry), which puts Phase 4.5 outside the range so the caller owns the iteration record as sole writer. Scratch-file existence never establishes ownership; only the requested range does. Independent of the live-comment flag: either can be on while the other is off.

When enabled, assemble a single workpad-shaped object for this run from state the engine already produced and write it to `.prflow/tmp/review/<slug>/<run-id>/iter-1.json` (run-scoped, the same `<run-id>` Phase 0.2 resolved). The `telemetry` key is mandatory: when no phase figures were established, emit the literal JSON string `"unavailable"`, never a missing key or `null`. This scratch write is what `efficiency-trace.sh --mode trace` reads back; landing in gitignored `.prflow/tmp/`, it is not a tree write and is permitted under the read-only cloud `review` profile — only the durable `--persist` write to the telemetry branch is gated to writable runs.

Author it with an allow-listed command — the read-only cloud `review` profile grants the execution-verified jq wrapper `Bash(.prflow/vendor/prflow/scripts/run-jq.sh:*)` (invoke it as the leading token by path so a shim-shadowed Windows/WSL host resolves a runnable jq; bare `Bash(jq:*)` is also granted but skips that resolution), plus `Bash(printf:*)` and `Bash(tee:*)`. Build the object by running the builder bare and reading its stdout from that invocation's own tool result, e.g. `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/run-jq.sh -n --argjson findings '…' '{iter:1, source:"review", …}'` — the engine root's shape discipline prefers the Write tool to a `>` redirect. Then author `.prflow/tmp/review/<slug>/<run-id>/iter-1.json` with the **Write tool**, its content exactly that observed stdout; on a runner with no Write tool, a `tee <file> <<'EOF'` heredoc is the accepted alternative — never a `cat`-headed heredoc, which the *Cloud command-shape discipline* classifies as denied. This exact recipe remains fixture-pinned; its evidence is recipe-specific. An ungranted head is silently denied and the trace has no input.

Then confirm what landed is parseable:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/run-jq.sh -e . .prflow/tmp/review/<slug>/<run-id>/iter-1.json
```

Read the exit status from the tool result. On non-zero, emit `::warning::review telemetry record failed to parse after authoring: <the first line of the stderr that tool result showed, or the literal stderr=empty>` — this warning is emitted as its own action *after* the read, so the slot is renderable here — and skip the trace and persist below.

```json
{
  "iter": 1,
  "source": "review",
  "diff_profile": { … the Phase 0.5 flags … },
  "checklist": [ { "verification_mode": "lite|agent", "verdict": "…" }, … ],
  "phase3_dispatched": [ "<agent id>", … ],
  "phase3_findings": [ { "agent": "<id>", "corroboration_count": N, "contributed_to_verdict": true|false }, … ],
  "telemetry": { "phase_0_5": {…}, "phase_1": {…}, "phase_2": {…}, "phase_3": {…} }
}
```

`source: "review"` selects the review-mode derivation in `lib/efficiency-trace.jq` (distinguishing the record from `/prflow:review-and-fix`'s). Because standalone review never applies a fix, each Phase-3 finding carries `contributed_to_verdict` instead of `fix_decision`: `true` when it counted toward the verdict (drove the REJECT, or was a non-deferral-demoted Important/Suggestion in an APPROVE-with-notes), `false` when Phase 4.0's deferral match demoted it to Informational. The jq then classifies each agent `unique-effective` / `corroborating` / `noise` / `null` off contribution instead of applied-fix.

Then render the trace and (on a writable run) persist the record, reusing the same hardened invocation `/prflow:review-and-fix`'s Loop Exit uses (direct invocation — no `bash` prefix; rc/stderr `::warning::` breadcrumbs; remove-on-rc≠0):

```bash
WORKPAD_DIR=$(printf '%s' ".prflow/tmp/review/<slug>/<run-id>")   # run-scoped: read THIS run's iter-1.json. Capture form: a bare VAR="…" assignment is a denied shape; the matcher descends into $(…).
# Trace (renders to chat / the live comment; reads only):
# Three-way, mirroring /prflow:review-and-fix's Loop Exit. `if !` reads the helper's OWN
# exit status, never a captured rc read in a later statement: rc≠0 is a failure; rc=0-but-
# empty stdout (e.g. telemetry flag off, or zero readable workpads) is a benign no-trace —
# surface it but append nothing, never a blank trace section. Capture no stderr file: a
# `2>` redirect is refused by the cloud harness, and the warning below carries no cause —
# the stderr does not exist until this same statement runs, so no slot in it can be rendered.
if ! TELEM="$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/efficiency-trace.sh --workpad-dir "$WORKPAD_DIR" --slug "<slug>" --mode trace)"; then
  echo "::warning::review effectiveness trace unavailable (rc≠0); cause follows"; TELEM=""
elif [ -z "$TELEM" ]; then
  echo "::warning::review effectiveness trace rendered empty (rc=0, no output — telemetry disabled or no readable workpads); omitting the trace section"
fi
# When the rc≠0 arm fired, read this fence's own tool result and emit a SECOND warning
# carrying the cause; skipping it loses the cause from the Actions UI entirely:
#   ::warning::review effectiveness trace cause: <first stderr line, or stderr=empty>

# Record (WRITABLE runs only — never under the read-only cloud profile). --persist reads
# THIS run's iter-1.json (source:"review" → review-mode record) and advances the TELEMETRY
# BRANCH ref — the SAME code path /prflow:review-and-fix's Loop Exit uses; nothing touches
# the working tree or the current branch. Best-effort/exit-0: an unpushable branch
# (offline, no remote, read-only fork-PR token) still advances the local ref and warns.
# (No `|| true`: --persist is exit-0 by contract, and `true` is an ungranted head here.)
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../lib/efficiency-trace.sh --persist --workpad-dir "$WORKPAD_DIR" --slug "<slug>"
```

- PR mode + live comment on: append the Run telemetry summary (per-phase `calls`/`tokens`/`wall_clock_s`) and the rendered `$TELEM` trace into the live progress comment's finalization (Phase 4 of the update protocol). The comment edit goes through `gh` — permitted under the read-only cloud profile.
- Writable run (local/IDE) only: run the `--persist` record block above. Never run it under the read-only cloud `review` profile (`contents: read`).
- Telemetry-on with live comment OFF, in a read-only cloud run: there is no surface (comment disabled, `--persist` gated out). Do not silently compute-and-discard: emit a one-line chat note (`::warning::devflow review telemetry enabled but no surface available (live comment disabled, read-only run) — trace not persisted`).

Best-effort throughout: a telemetry/trace failure is a `::warning::`, never a downgrade of the verdict.

<!-- prflow:review-ref phase=4.5 file=skills/review/phases/phase-4-5-telemetry.md end -->
