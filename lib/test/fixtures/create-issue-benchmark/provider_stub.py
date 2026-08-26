#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Local provider stub for the controlled create-issue benchmark."""

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

CONTROLLED = (
    "PRFLOW_BENCHMARK_CONFIGURATION",
    "PRFLOW_BENCHMARK_SCENARIO_ID",
    "PRFLOW_BENCHMARK_REPETITION",
    "PRFLOW_BENCHMARK_PROMPT_PATH",
    "PRFLOW_BENCHMARK_SKILL_ROOT",
    "PRFLOW_BENCHMARK_OUTPUT_DIR",
)


def main():
    env = {key: os.environ[key] for key in CONTROLLED}
    output = Path(env["PRFLOW_BENCHMARK_OUTPUT_DIR"])
    output.mkdir(parents=True, exist_ok=True)
    observation = {
        "argv": sys.argv[1:],
        "controlled_environment": {
            key: value for key, value in os.environ.items()
            if key.startswith("PRFLOW_BENCHMARK_")
        },
    }
    (output / "provider-observation.json").write_text(
        json.dumps(observation, indent=2) + "\n", encoding="utf-8"
    )
    print("provider stdout")
    print("provider stderr", file=sys.stderr)
    if "--fail" in sys.argv:
        return 9

    repository = Path(__file__).resolve().parents[4]
    fixture_root = repository / "lib/test/fixtures/create-issue-eval/manifests"
    source_manifest = json.loads(
        (fixture_root / "two-occurrences.json").read_text(encoding="utf-8")
    )
    configuration = env["PRFLOW_BENCHMARK_CONFIGURATION"]
    source = next(
        run for run in source_manifest["runs"]
        if run["configuration"] == configuration
    )

    def copy_artifact(value, destination):
        shutil.copyfile(fixture_root / value, output / destination)
        return destination

    transcript = copy_artifact(source["transcript"], "transcript.jsonl")
    state_file = copy_artifact(source["state_file"], "audit-state.json")
    initial = copy_artifact(source["checkpoints"]["initial"], "draft-initial.md")
    revisions = [
        copy_artifact(value, f"draft-revision-{index}.md")
        for index, value in enumerate(source["checkpoints"]["revisions"], 1)
    ]
    final = copy_artifact(source["checkpoints"]["final"], "draft-final.md")
    prompt_bytes = Path(env["PRFLOW_BENCHMARK_PROMPT_PATH"]).read_bytes()
    repetition = int(env["PRFLOW_BENCHMARK_REPETITION"])
    scenario_id = env["PRFLOW_BENCHMARK_SCENARIO_ID"]
    run_id = f"{configuration}-{scenario_id}-{repetition}"
    occurrence = dict(source["occurrence"])
    occurrence["session_id"] = f"session-{configuration}-{run_id}"
    occurrence["occurrence_id"] = f"occurrence-{run_id}"
    run = {
        "run_id": run_id,
        "configuration": configuration,
        "scenario_id": scenario_id,
        "repetition": repetition,
        "transcript": transcript,
        "state_file": state_file,
        "occurrence": occurrence,
        "checkpoints": {
            "initial": initial,
            "revisions": revisions,
            "final": final,
        },
        "provenance": {
            "repo_sha": source["provenance"]["repo_sha"],
            "skill_fingerprint": f"sha256:{configuration}",
            "prompt_fingerprint": f"sha256:{hashlib.sha256(prompt_bytes).hexdigest()}",
            "model": "stub-model",
            "effort": "stub-effort",
            "output_style": "stub-style",
            "provider": "local-stub",
        },
    }
    root = "."
    if "--escape-root" in sys.argv:
        root = ".."
        prefix = output.name + "/"
        for key in ("transcript", "state_file"):
            run[key] = prefix + run[key]
        run["checkpoints"] = {
            "initial": prefix + initial,
            "revisions": [prefix + value for value in revisions],
            "final": prefix + final,
        }
    provider_manifest = {
        "schema_version": 1,
        "root": root,
        "benchmark_id": "provider-stub",
        "runs": [run],
    }
    if "--omit-manifest" not in sys.argv:
        (output / "run-manifest.json").write_text(
            json.dumps(provider_manifest, indent=2) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
