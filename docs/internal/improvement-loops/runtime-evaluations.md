# Runtime evaluations

This page explains the repository's measurements of prompt delivery, runtime context, and review wording.

## Current behavior

The repository contains maintainer and CI-adjacent instruments for create-issue and implement runtime context, skill-body delivery, and review-and-fix wording. These instruments measure specific populations and loader paths; they do not automatically become runtime gates merely because they produce a number.

Each evaluation records its population, measurement method, provenance, and known limits. A figure without a re-derivable comparand is not used as a current invariant.

## Why it works this way

Prompt size, delivered context, and model behavior are related but not identical. Separating those measurements prevents maintainers from optimizing a static byte count while missing a loader truncation, a repeated re-read, or a wording effect in a fresh-context sample.

## Boundaries and failure paths

- An evaluation instrument that is not called by a runtime path is not a runtime gate.
- A self-report is weaker evidence than a harness-recorded event.
- A measurement over one tier, runner, or corpus does not establish behavior for every tier or future corpus.
- An absent transcript or corpus is reported as unavailable rather than measured as zero.

## Source of truth

- `scripts/create-issue-context-eval.py` and `scripts/implement-context-eval.py` — context instruments; `scripts.create_issue_eval` also owns run-addressable manifest analysis and formal grading.
- `scripts/create-issue-benchmark.py` — provider-neutral paired execution, statistical reporting, and anonymized review export.
- `scripts/workflow_flight_recorder.py` — transcript and workflow evidence.
- `scripts/prompt-surface-growth.py` — prompt-surface measurement.
- `lib/test/` evaluation guards and fixtures — reproducibility checks.
- `docs/internal/skill-body-load-delivery.md` — skill delivery evidence.
- `docs/internal/implement-context.md` and `docs/internal/review-and-fix-split-wording-study.md` — detailed studies.

## Controlled create-issue benchmark workflow

Run a benchmark from the repository root with exactly two configurations, `baseline` and `candidate`. A schema-1 spec declares a root, benchmark ID, positive repetition count, each configuration's skill root and argv vector, and each scenario's prompt and rubric. The runner sorts scenarios, executes every `(scenario_id, repetition, configuration)` deterministically, and supplies `PRFLOW_BENCHMARK_CONFIGURATION`, `PRFLOW_BENCHMARK_SCENARIO_ID`, `PRFLOW_BENCHMARK_REPETITION`, `PRFLOW_BENCHMARK_PROMPT_PATH`, `PRFLOW_BENCHMARK_SKILL_ROOT`, and `PRFLOW_BENCHMARK_OUTPUT_DIR`. It passes argv directly with `shell=False`; a provider adapter is responsible only for writing one schema-1 `run-manifest.json` and its named artifacts beneath the assigned output directory.

This reproduction uses only committed prompts, rubrics, skill markers, the local provider stub, and the committed evaluation corpus. It needs no network or provider credentials:

```bash
benchmark_repo="$(pwd)"
benchmark_tmp="$(mktemp -d)"
cat >"$benchmark_tmp/spec.json" <<EOF
{
  "schema_version": 1,
  "root": "$benchmark_repo",
  "benchmark_id": "committed-local-stub",
  "repetitions": 1,
  "configurations": {
    "baseline": {
      "skill_root": "lib/test/fixtures/create-issue-benchmark/skills/baseline",
      "argv": ["python3", "lib/test/fixtures/create-issue-benchmark/provider_stub.py"]
    },
    "candidate": {
      "skill_root": "lib/test/fixtures/create-issue-benchmark/skills/candidate",
      "argv": ["python3", "lib/test/fixtures/create-issue-benchmark/provider_stub.py"]
    }
  },
  "scenarios": [
    {
      "scenario_id": "alpha",
      "prompt": "lib/test/fixtures/create-issue-benchmark/prompts/alpha.md",
      "rubric": "lib/test/fixtures/create-issue-benchmark/rubric.json"
    },
    {
      "scenario_id": "zeta",
      "prompt": "lib/test/fixtures/create-issue-benchmark/prompts/zeta.md",
      "rubric": "lib/test/fixtures/create-issue-benchmark/rubric.json"
    }
  ]
}
EOF
python3 scripts/create-issue-benchmark.py run \
  --spec "$benchmark_tmp/spec.json" --output "$benchmark_tmp/output"
python3 scripts/create-issue-benchmark.py report \
  --manifest "$benchmark_tmp/output/run-manifest.json" --format json
```

The run command writes the combined benchmark `run-manifest.json` — the per-run provider manifests plus an `executions` record per attempted triple, so it is a superset of the per-run schema-1 document and is not itself accepted by `load_eval_manifest` when every launch failed and `runs` is empty — alongside per-run stdout, stderr, duration, provider artifacts, and an `error.txt` for a failed launch or nonzero provider. It also writes `benchmark.json`, `benchmark.md`, and `review.json`. The review export assigns each exact pair to `A` and `B` by a stable pseudo-random side order derived from the pair digest, copies the local final issue and grade into a separate review workspace, and exposes only pointers in `review.json`; it does not reveal configuration names or copy draft bodies into the JSON. The side order is a pure function of non-secret data and `review.json` sits beside the un-blinded run artifacts, so blinding holds only when the reviewer is handed the `review/` directory alone.

The report publishes count, mean, median, population standard deviation, coefficient of variation, and a `high_variance` flag for each established configuration metric and paired delta. The measured axes are initial/final words, finding counts, first/final unresolved findings, audit rounds, main-thread peak context, auditor tokens, combined observed tokens, and monotonic `duration_ms`. A coefficient of variation above `0.25` is disclosed as high variance when at least two observations exist; a population whose mean is exactly zero with a non-zero deviation reports the coefficient as `unestablished` and is disclosed as high variance regardless of that threshold. Monotonic duration is a runner measurement, but causal confidence still depends on exact occurrence boundaries, complete pairs, and compatible provenance; non-exact boundaries, missing state, failed runs, or mixed provenance make paired statistics unestablished.

Quality is reported before efficiency. Each pair passes quality only when its candidate preserves or improves the baseline rubric pass rate and adds no forbidden-concept failure and no forbidden-section failure. Those two forbidden counts are gated separately from the pass rate, because a new forbidden failure offset by a newly-satisfied required assertion leaves the aggregate pass rate unchanged. Aggregate quality passes only when every exact pair passes. Paired reductions receive efficiency credit only when comparison evidence is established and aggregate quality passes; otherwise `efficiency.status` is `withheld` and `credited_paired_deltas` is `unestablished`, even when raw token or duration deltas are negative. The committed `historical-4-to-8.json` fixture is the canonical counterexample: fewer auditor tokens alongside worse formal quality and more findings receives no reduction credit.

## Related topics

- [Skill loading](../skills/skill-loading.md)
- [Efficiency telemetry](efficiency-telemetry.md)
- [Workflow flight recorder](workflow-flight-recorder.md)
