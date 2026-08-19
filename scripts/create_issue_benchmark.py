#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Provider-neutral controlled A/B runner for create-issue evaluation.

The spec file is effectively an execution manifest: it names an argv this module
launches, and only `PRFLOW_BENCHMARK_*` is scrubbed from the inherited environment.
Run it on maintainer-authored specs only.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time


SCHEMA_VERSION = 1
UNESTABLISHED = "unestablished"
CONFIGURATIONS = ("baseline", "candidate")
CONTROLLED_ENVIRONMENT = (
    "PRFLOW_BENCHMARK_CONFIGURATION",
    "PRFLOW_BENCHMARK_SCENARIO_ID",
    "PRFLOW_BENCHMARK_REPETITION",
    "PRFLOW_BENCHMARK_PROMPT_PATH",
    "PRFLOW_BENCHMARK_SKILL_ROOT",
    "PRFLOW_BENCHMARK_OUTPUT_DIR",
)
HIGH_VARIANCE_CV = 0.25

_SCRIPT_DIR = Path(__file__).resolve().parent
_EVAL_SPEC = importlib.util.spec_from_file_location(
    "create_issue_benchmark_eval", _SCRIPT_DIR / "create_issue_eval.py"
)
if _EVAL_SPEC is None or _EVAL_SPEC.loader is None:
    raise ImportError("could not load scripts/create_issue_eval.py")
_EVAL = importlib.util.module_from_spec(_EVAL_SPEC)
_EVAL_SPEC.loader.exec_module(_EVAL)


def _error(diagnostic, detail):
    raise ValueError("{}: {}".format(diagnostic, detail))


def _required_string(mapping, key, diagnostic="missing_field"):
    value = mapping.get(key) if isinstance(mapping, dict) else None
    if not isinstance(value, str) or not value:
        _error(diagnostic, "{} must be a non-empty string".format(key))
    return value


def _contained(root, value, label, directory=False):
    if not isinstance(value, str) or not value:
        _error("missing_artifact", "{} has no path".format(label))
    candidate = Path(value) if os.path.isabs(value) else Path(root) / value
    resolved = Path(os.path.realpath(candidate))
    try:
        contained = os.path.commonpath((str(root), str(resolved))) == str(root)
    except ValueError:
        contained = False
    if not contained:
        _error("path_escape", "{} escapes declared root".format(label))
    exists = resolved.is_dir() if directory else resolved.is_file()
    if not exists:
        _error("missing_artifact", "{} not found".format(label))
    return resolved


def _read_json(path, diagnostic):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:  # noqa: BLE001 - malformed input has one stable boundary
        _error(diagnostic, "{}: {}".format(path, exc))


def load_benchmark_spec(path):
    """Load and validate one schema-1 provider-neutral benchmark spec."""
    source = _read_json(path, "invalid_spec")
    if not isinstance(source, dict):
        _error("invalid_spec", "top level is not an object")
    version = source.get("schema_version")
    if version != SCHEMA_VERSION or isinstance(version, bool):
        _error("unsupported_schema_version", repr(version))
    _required_string(source, "benchmark_id")
    repetitions = source.get("repetitions")
    if not isinstance(repetitions, int) or isinstance(repetitions, bool) or repetitions < 1:
        _error("invalid_repetitions", repr(repetitions))
    spec_dir = Path(path).resolve().parent
    root_value = _required_string(source, "root")
    root = Path(os.path.realpath(
        root_value if os.path.isabs(root_value) else spec_dir / root_value
    ))
    if not root.is_dir():
        _error("missing_artifact", "declared root not found")

    configurations = source.get("configurations")
    if not isinstance(configurations, dict) or set(configurations) != set(CONFIGURATIONS):
        _error("invalid_configurations", "exactly baseline and candidate are required")
    normalized_configurations = {}
    for name in CONFIGURATIONS:
        item = configurations[name]
        if not isinstance(item, dict):
            _error("invalid_configurations", name)
        argv = item.get("argv")
        if (not isinstance(argv, list) or not argv
                or not all(isinstance(value, str) and value for value in argv)):
            _error("invalid_argv", name)
        timeout_seconds = item.get("timeout_seconds")
        # math.isfinite is load-bearing: subprocess.run(timeout=nan) never fires, so
        # a NaN accepted here turns a declared limit into no limit at all.
        if timeout_seconds is not None and (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            _error("invalid_timeout_seconds", name)
        normalized_configurations[name] = {
            "skill_root": str(_contained(
                root, item.get("skill_root"), "{}.skill_root".format(name), directory=True
            )),
            "argv": list(argv),
            "timeout_seconds": timeout_seconds,
        }

    scenarios = source.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        _error("invalid_scenarios", "scenarios must be a non-empty list")
    normalized_scenarios = []
    seen = set()
    for index, item in enumerate(scenarios):
        scenario_id = _required_string(item, "scenario_id", "invalid_scenario")
        if (scenario_id in seen or scenario_id in (".", "..")
                or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
                       for char in scenario_id)):
            _error("invalid_scenario", scenario_id)
        seen.add(scenario_id)
        normalized_scenarios.append({
            "scenario_id": scenario_id,
            "prompt": str(_contained(root, item.get("prompt"), "scenario prompt")),
            "rubric": str(_contained(root, item.get("rubric"), "scenario rubric")),
        })
    normalized_scenarios.sort(key=lambda item: item["scenario_id"])
    return {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "benchmark_id": source["benchmark_id"],
        "repetitions": repetitions,
        "configurations": normalized_configurations,
        "scenarios": normalized_scenarios,
    }


def _write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _relative(root, path):
    return os.path.relpath(os.path.realpath(path), os.path.realpath(root))


def _provider_run(provider_manifest, assigned, output, expected, rubric_path):
    loaded = _EVAL.load_eval_manifest(str(provider_manifest))
    if os.path.realpath(loaded["root"]) != os.path.realpath(assigned):
        _error("provider_root_mismatch", "provider root is not the assigned output directory")
    if len(loaded["runs"]) != 1:
        _error("invalid_provider_manifest", "exactly one run is required")
    run = loaded["runs"][0]
    for key, value in expected.items():
        if run.get(key) != value:
            _error("provider_identity_mismatch", "{} differs".format(key))
    normalized = dict(run)
    normalized["transcript"] = _relative(output, run["transcript"])
    normalized["state_file"] = _relative(output, run["state_file"])
    normalized["checkpoints"] = {
        "initial": _relative(output, run["checkpoints"]["initial"]),
        "revisions": [_relative(output, path) for path in run["checkpoints"]["revisions"]],
        "final": _relative(output, run["checkpoints"]["final"]),
    }
    normalized["rubric"] = _relative(output, rubric_path)
    return normalized


def _record_error(output, execution, message):
    error_path = Path(execution["output_dir"]) / "error.txt"
    absolute = Path(output) / error_path
    absolute.write_text(message.rstrip() + "\n", encoding="utf-8")
    execution["status"] = "failed"
    execution["error"] = str(error_path)


def run_benchmark(spec_path, output_dir, monotonic_ns=time.monotonic_ns):
    """Execute every matched scenario/repetition pair and write benchmark artifacts."""
    spec = load_benchmark_spec(spec_path)
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    runs = []
    executions = []
    for scenario in spec["scenarios"]:
        for repetition in range(1, spec["repetitions"] + 1):
            for configuration in CONFIGURATIONS:
                config = spec["configurations"][configuration]
                relative_dir = Path("runs") / scenario["scenario_id"] / "{:03d}".format(
                    repetition
                ) / configuration
                assigned = output / relative_dir
                assigned.mkdir(parents=True, exist_ok=True)
                # Re-running into a populated --output would otherwise let a provider
                # that writes no manifest inherit the previous run's, which passes the
                # identity check by construction and is recorded as succeeded.
                (assigned / "run-manifest.json").unlink(missing_ok=True)
                rubric_path = assigned / "rubric.json"
                shutil.copyfile(scenario["rubric"], rubric_path)
                stdout_path = relative_dir / "stdout.txt"
                stderr_path = relative_dir / "stderr.txt"
                environment = {
                    key: value for key, value in os.environ.items()
                    if not key.startswith("PRFLOW_BENCHMARK_")
                }
                environment.update({
                    "PRFLOW_BENCHMARK_CONFIGURATION": configuration,
                    "PRFLOW_BENCHMARK_SCENARIO_ID": scenario["scenario_id"],
                    "PRFLOW_BENCHMARK_REPETITION": str(repetition),
                    "PRFLOW_BENCHMARK_PROMPT_PATH": scenario["prompt"],
                    "PRFLOW_BENCHMARK_SKILL_ROOT": config["skill_root"],
                    "PRFLOW_BENCHMARK_OUTPUT_DIR": str(assigned),
                })
                execution = {
                    "run_id": "{}-{}-{}".format(
                        configuration, scenario["scenario_id"], repetition
                    ),
                    "configuration": configuration,
                    "scenario_id": scenario["scenario_id"],
                    "repetition": repetition,
                    "output_dir": str(relative_dir),
                    "stdout": str(stdout_path),
                    "stderr": str(stderr_path),
                    "exit_code": None,
                    "error": None,
                    # main() indexes status unguarded; a future early-continue in
                    # this loop would otherwise raise KeyError past its exit-2 arm.
                    "status": "pending",
                    "duration_ms": None,
                }
                started = monotonic_ns()
                try:
                    with open(output / stdout_path, "w", encoding="utf-8") as stdout_handle, \
                            open(output / stderr_path, "w", encoding="utf-8") as stderr_handle:
                        completed = subprocess.run(
                            config["argv"],
                            cwd=spec["root"],
                            env=environment,
                            stdout=stdout_handle,
                            stderr=stderr_handle,
                            shell=False,
                            check=False,
                            timeout=config.get("timeout_seconds"),
                        )
                    execution["exit_code"] = completed.returncode
                except subprocess.TimeoutExpired as exc:
                    # TimeoutExpired is not an OSError, so it would otherwise escape
                    # main()'s (OSError, ValueError) arm as an uncaught traceback.
                    completed = None
                    _record_error(
                        output, execution,
                        "provider_timeout: {}s".format(exc.timeout),
                    )
                except OSError as exc:
                    completed = None
                    _record_error(output, execution, "provider_launch_error: {}".format(exc))
                finished = monotonic_ns()
                execution["duration_ms"] = max(0, (finished - started) // 1_000_000)
                if completed is not None and completed.returncode != 0:
                    _record_error(
                        output, execution,
                        "provider_exit_nonzero: {}".format(completed.returncode),
                    )
                elif completed is not None:
                    try:
                        runs.append(_provider_run(
                            assigned / "run-manifest.json",
                            assigned,
                            output,
                            {
                                "run_id": execution["run_id"],
                                "configuration": configuration,
                                "scenario_id": scenario["scenario_id"],
                                "repetition": repetition,
                            },
                            rubric_path,
                        ))
                        execution["status"] = "succeeded"
                    except (OSError, ValueError) as exc:
                        _record_error(output, execution, str(exc))
                executions.append(execution)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "root": ".",
        "benchmark_id": spec["benchmark_id"],
        "runs": runs,
        "executions": executions,
    }
    manifest_path = output / "run-manifest.json"
    _write_json(manifest_path, manifest)
    write_benchmark_outputs(manifest_path)
    return manifest


def describe(values):
    """Describe a numeric population with population standard deviation.

    `status: "established"` does not mean every field is numeric: on a zero mean with
    a non-zero deviation `coefficient_of_variation` is the UNESTABLISHED string, so a
    consumer must check that field before doing arithmetic on it.
    """
    if (not isinstance(values, list) or not values
            or any(not isinstance(value, (int, float)) or isinstance(value, bool)
                   or not math.isfinite(value) for value in values)):
        return UNESTABLISHED
    mean = statistics.fmean(values)
    deviation = statistics.pstdev(values)
    if mean == 0:
        coefficient = 0.0 if deviation == 0 else UNESTABLISHED
        high_variance = deviation > 0
    else:
        coefficient = abs(deviation / mean)
        high_variance = len(values) > 1 and coefficient > HIGH_VARIANCE_CV
    return {
        "status": "established",
        "count": len(values),
        "mean": mean,
        "median": float(statistics.median(values)),
        "population_stddev": deviation,
        "coefficient_of_variation": coefficient,
        "high_variance": high_variance,
    }


METRICS = (
    ("initial_word_count", lambda run, execution: run["draft_metrics"]["initial"]["word_count"]),
    ("final_word_count", lambda run, execution: run["draft_metrics"]["final"]["word_count"]),
    ("finding_count", lambda run, execution: run["finding_count"]),
    ("first_round_unresolved", lambda run, execution: run["audit_outcomes"]["first_round_unresolved"]),
    ("final_unresolved", lambda run, execution: run["audit_outcomes"]["final_unresolved"]),
    ("audit_rounds", lambda run, execution: len(run["dispatch_rounds"])),
    ("main_thread_peak_context", lambda run, execution: run["peak_context"]),
    ("auditor_tokens", lambda run, execution: run["attributed_auditor_cost"]),
    ("combined_observed_tokens", lambda run, execution: (
        run["peak_context"] + run["total_output_tokens"] + run["attributed_auditor_cost"]
    )),
    ("duration_ms", lambda run, execution: execution["duration_ms"]),
)


def _metric(run, execution, extractor, name=None, unextractable=None):
    try:
        value = extractor(run, execution)
    except (KeyError, TypeError, ValueError) as exc:
        # An extractor that cannot reach its key means the eval-report contract
        # broke; without this record the report reads as an honest "measured
        # nothing" rather than a schema break.
        if unextractable is not None and name is not None:
            unextractable.setdefault(name, "{}: {}".format(type(exc).__name__, exc))
        return UNESTABLISHED
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return UNESTABLISHED
    return value


def aggregate_benchmark(evaluation, executions):
    """Aggregate exact pairs from an evaluator report, with quality before efficiency."""
    # `executions` is the only evidence that the runs were actually produced, so a
    # non-list or non-object member is absent evidence, never a succeeded run.
    execution_items = [
        item for item in (executions if isinstance(executions, list) else [])
        if isinstance(item, dict)
    ]
    execution_by_run = {
        item["run_id"]: item for item in execution_items
        if isinstance(item.get("run_id"), str)
    }
    runs = evaluation.get("runs", [])
    grouped = {}
    for run in runs:
        grouped.setdefault((run["scenario_id"], run["repetition"]), {})[
            run["configuration"]
        ] = run
    comparison = evaluation.get("comparison", {})
    diagnostic = comparison.get("diagnostic")
    failed_execution = any(
        item.get("status") != "succeeded" for item in execution_items
    )
    # `any` over an empty population is False, so the failed-execution test alone
    # credits a run set carrying no execution evidence at all: require coverage too.
    uncovered_run = any(
        run.get("run_id") not in execution_by_run for run in runs
    )
    if failed_execution or uncovered_run or diagnostic in (
        "unpaired_runs", "no_pairable_configurations", "duplicate_pair_member"
    ):
        status = UNESTABLISHED
        diagnostic = "incomplete_pairs"
    elif comparison.get("status") != "established":
        status = UNESTABLISHED
        diagnostic = diagnostic or "unestablished_comparison"
    else:
        status = "established"
        diagnostic = None

    pairs = []
    unextractable = {}
    for scenario_repetition in sorted(grouped):
        members = grouped[scenario_repetition]
        if set(members) != set(CONFIGURATIONS):
            continue
        baseline = members["baseline"]
        candidate = members["candidate"]
        quality = _EVAL.quality_gate(baseline.get("grade"), candidate.get("grade"))
        baseline_execution = execution_by_run.get(baseline["run_id"], {})
        candidate_execution = execution_by_run.get(candidate["run_id"], {})
        delta = {}
        values = {"baseline": {}, "candidate": {}}
        for name, extractor in METRICS:
            # An absent execution record is already reported as incomplete_pairs, so
            # only a key missing from a PRESENT record evidences a schema break.
            before = _metric(
                baseline, baseline_execution, extractor, name,
                unextractable if baseline_execution else None,
            )
            after = _metric(
                candidate, candidate_execution, extractor, name,
                unextractable if candidate_execution else None,
            )
            values["baseline"][name] = before
            values["candidate"][name] = after
            delta[name] = (
                after - before
                if before != UNESTABLISHED and after != UNESTABLISHED
                else UNESTABLISHED
            )
        pairs.append({
            "scenario_id": scenario_repetition[0],
            "repetition": scenario_repetition[1],
            "quality": quality,
            "values": values,
            "delta": delta,
        })

    quality_established = (
        status == "established" and pairs
        and all(pair["quality"]["status"] == "established" for pair in pairs)
    )
    quality_passed = sum(1 for pair in pairs if pair["quality"].get("passed"))
    quality = {
        "status": "established" if quality_established else UNESTABLISHED,
        "pair_count": len(pairs),
        "passed_pairs": quality_passed if quality_established else UNESTABLISHED,
        "pass_rate": quality_passed / len(pairs) if quality_established else UNESTABLISHED,
        "passed": quality_established and quality_passed == len(pairs),
    }

    configuration_statistics = {}
    for configuration in CONFIGURATIONS:
        configuration_statistics[configuration] = {}
        members = [run for run in runs if run["configuration"] == configuration]
        for name, extractor in METRICS:
            values = [
                _metric(run, execution_by_run.get(run["run_id"], {}), extractor)
                for run in members
            ]
            configuration_statistics[configuration][name] = describe(values)

    if status == "established" and pairs:
        paired_deltas = {
            name: describe([pair["delta"][name] for pair in pairs])
            for name, _extractor in METRICS
        }
    else:
        paired_deltas = UNESTABLISHED
    credited = status == "established" and quality["passed"]
    efficiency = {
        "status": "credited" if credited else "withheld",
        "quality_gate_passed": quality["passed"],
        "credited_paired_deltas": paired_deltas if credited else UNESTABLISHED,
    }
    disclosures = []
    if status != "established":
        disclosures.append(diagnostic)
    for configuration, metrics in configuration_statistics.items():
        for metric, summary in metrics.items():
            if isinstance(summary, dict) and summary["high_variance"]:
                disclosures.append("high_variance:{}:{}".format(configuration, metric))
    if isinstance(paired_deltas, dict):
        for metric, summary in paired_deltas.items():
            if isinstance(summary, dict) and summary["high_variance"]:
                disclosures.append("high_variance:paired_delta:{}".format(metric))
    for metric in sorted(unextractable):
        sys.stderr.write(
            "create-issue-benchmark: metric {} unextractable ({})\n".format(
                metric, unextractable[metric]
            )
        )
        disclosures.append("metric_unextractable:{}".format(metric))
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark_id": evaluation.get("benchmark_id"),
        "status": status,
        "diagnostic": diagnostic,
        "quality": quality,
        "configuration_statistics": configuration_statistics,
        "pairs": pairs,
        "paired_deltas": paired_deltas,
        "efficiency": efficiency,
        "disclosures": disclosures,
    }


def _evaluate_manifest(manifest_path):
    """Read a benchmark manifest and return (evaluation, report).

    Single-sourced so `build_benchmark_report` and `write_benchmark_outputs` cannot
    drift in their manifest-shape guards or their empty-runs fallback.
    """
    manifest = _read_json(manifest_path, "invalid_manifest")
    # A valid non-object top level would reach `.get` as an AttributeError instead of
    # this module's contracted exit 2.
    if not isinstance(manifest, dict):
        _error("invalid_manifest", "top level is not an object")
    executions = manifest.get("executions", [])
    # Refuse a wrong-typed executions field here rather than letting it reach
    # `aggregate_benchmark`, whose defensive normalization would silently report
    # every metric unestablished instead of naming the malformed manifest.
    if not isinstance(executions, list):
        _error("invalid_manifest", "executions is not a list")
    # A list of non-objects reaches aggregate_benchmark's defensive normalization and
    # degrades every metric silently, which is the outcome this guard exists to name.
    if any(not isinstance(item, dict) for item in executions):
        _error("invalid_manifest", "executions contains a non-object member")
    if manifest.get("runs"):
        evaluation = _EVAL.build_manifest_report(str(manifest_path))
    else:
        evaluation = {
            "benchmark_id": manifest.get("benchmark_id"),
            "runs": [],
            "comparison": {"status": UNESTABLISHED, "diagnostic": "unpaired_runs"},
        }
    return evaluation, aggregate_benchmark(evaluation, executions)


def build_benchmark_report(manifest_path):
    return _evaluate_manifest(manifest_path)[1]


def render_text(report):
    lines = [
        "Create-issue benchmark {}".format(report["benchmark_id"]),
        "",
        "Quality",
        "- status: {}".format(report["quality"]["status"]),
        "- pass rate: {}".format(report["quality"]["pass_rate"]),
        "- passed: {}".format(report["quality"]["passed"]),
        "",
        "Measurements",
        "- status: {}".format(report["status"]),
        "- diagnostic: {}".format(report["diagnostic"]),
        "- paired deltas: {}".format(report["paired_deltas"]),
        "",
        "Efficiency",
        "- status: {}".format(report["efficiency"]["status"]),
        "- quality gate passed: {}".format(report["efficiency"]["quality_gate_passed"]),
    ]
    if report["disclosures"]:
        lines.extend(["", "Disclosures"])
        lines.extend("- {}".format(item) for item in report["disclosures"])
    return "\n".join(lines)


def _review_workspace(manifest_path, evaluation):
    output = Path(manifest_path).resolve().parent
    grouped = {}
    for run in evaluation.get("runs", []):
        grouped.setdefault((run["scenario_id"], run["repetition"]), {})[
            run["configuration"]
        ] = run
    entries = []
    benchmark_id = evaluation.get("benchmark_id")
    for key in sorted(grouped):
        if set(grouped[key]) != set(CONFIGURATIONS):
            continue
        digest = hashlib.sha256(
            "{}\0{}\0{}".format(benchmark_id, key[0], key[1]).encode("utf-8")
        ).hexdigest()
        order = CONFIGURATIONS if int(digest[-1], 16) % 2 == 0 else tuple(reversed(CONFIGURATIONS))
        pair_root = Path("review") / digest[:16]
        sides = {}
        for label, configuration in zip(("A", "B"), order):
            run = grouped[key][configuration]
            issue_path = pair_root / "{}-issue.md".format(label)
            grade_path = pair_root / "{}-grade.json".format(label)
            (output / pair_root).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(run["checkpoints"]["final"], output / issue_path)
            _write_json(output / grade_path, run["grade"])
            sides[label] = {
                "issue_artifact": str(issue_path),
                "grade_artifact": str(grade_path),
            }
        entries.append({
            "scenario_id": key[0],
            "repetition": key[1],
            "A": sides["A"],
            "B": sides["B"],
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "benchmark_id": benchmark_id,
        "entries": entries,
    }


def write_benchmark_outputs(manifest_path):
    manifest_path = Path(manifest_path).resolve()
    evaluation, report = _evaluate_manifest(manifest_path)
    output = manifest_path.parent
    _write_json(output / "benchmark.json", report)
    (output / "benchmark.md").write_text(render_text(report) + "\n", encoding="utf-8")
    _write_json(output / "review.json", _review_workspace(manifest_path, evaluation))
    return report


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None):
    _force_utf8_streams()
    parser = argparse.ArgumentParser(description="Run and report controlled create-issue A/B benchmarks.")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run")
    run_parser.add_argument("--spec", required=True)
    run_parser.add_argument("--output", required=True)
    report_parser = commands.add_parser("report")
    report_parser.add_argument("--manifest", required=True)
    report_parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            manifest = run_benchmark(args.spec, args.output)
            return 0 if all(item["status"] == "succeeded" for item in manifest["executions"]) else 1
        report = build_benchmark_report(args.manifest)
    except (OSError, ValueError) as exc:
        sys.stderr.write("error: {}\n".format(exc))
        return 2
    if args.format == "json":
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
    else:
        sys.stdout.write(render_text(report) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
