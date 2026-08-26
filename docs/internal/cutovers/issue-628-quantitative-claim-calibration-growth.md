---
schema: 1
kind: growth
---
# Issue #628 — quantitative claim calibration growth (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

- `agents/code-architect.md`
- `agents/code-explorer.md`
- `skills/implement/phases/phase-2-implement.md`

## Justification

- Issue #628 closes a calibration failure mode in the two `/prflow:implement`
  discovery/planning subagents: both bodies mandate confident, decisive output yet grant
  no arithmetic or reliable-counting channel, so a volunteered measurement class (a word
  count, a size total, budget arithmetic) ships with mandated confidence and no calibration
  path. The fix is a two-sided prose contract — a producer-side calibration rule in each
  agent, and a consumer-side re-derivation obligation in the phase-2 orchestrator — none of
  which is relocatable to a progressively-loaded reference, because each rule governs how the
  agent phrases (or the orchestrator re-checks) a claim at the moment it is produced or
  consumed. There is no executable owner available: the defect is calibration of free-text
  claims an agent volunteers, which no hook can intercept and no helper can enforce, so the
  prose is the only possible owner and stays mandatory.
- **`agents/code-architect.md` (+703 bytes) and `agents/code-explorer.md` (+947 bytes).** Each
  gains one calibration paragraph in its Output Guidance: a quantitative claim not read
  directly from tool output this session (or derived from truncated/limited/count-mode
  output) is marked `(unverified estimate)`, a tool-derived claim states its operands and
  counting rule inline, and `file:line` references plus qualitative judgments stay under the
  existing decisiveness/precision mandate. The explorer additionally gains a one-sentence
  scoping clause after its line-numbers mandate stating that `file:line` precision is for the
  ephemeral in-context analysis while committed documentation references bare paths and symbol
  names (line numbers rot). Both paragraphs are repo-agnostic — the agents ship into consumer
  repos through the plugin vendor channel — so they carry no PRFlow-internal paths. The
  explorer's larger delta is the extra scoping sentence it alone carries.
  The architect's current contract is stricter about its available instruments: it has no command-execution tool, and `Grep` count mode is not accepted as a quantitative measurement because it counts matching lines rather than occurrences.
- **`skills/implement/phases/phase-2-implement.md` (+1637 bytes).** §2.2 Path B gains one
  re-derivation paragraph directly after the blueprint-hold line: the orchestrator
  independently re-derives any Phase-2 subagent quantitative claim (explorer and architect,
  Path A and Path B) before it feeds a plan step, gate, or budget decision, through a
  preflight-guaranteed channel (`python3`, never an ad-hoc `wc`/`tr`/`cut`/`head`), with a
  downstream consumer's own standalone-invocable counter taking precedence where one exists;
  an unresolvable or operand-less claim resolves to unverified (never confirmed) without
  blocking the run, and a claim that reaches the workpad Plan records its
  re-derived-or-unverified status in the workpad entry so the marker survives compaction and
  stall-backstop resume. This is the sole point at which the subagent numbers are consumed, so
  the obligation sits at the execution point it gates rather than as a standing caution.
- The re-derivation obligation is prose-governed by disclosed necessity: its suite-checkable
  surfaces are the sentence presence pin and the workpad-recorded status of claims that reach
  the Plan; a run that silently skips re-derivation for a claim reaching no workpad entry
  leaves no detectable artifact. This residual is accepted as the strongest available
  deterministic backstop (presence pins) for an ephemeral in-context artifact no hook can
  intercept.
