#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Measure exact module tallies and raise their coupled floors without decreasing them.

The measurements run through a bounded worker pool (`MAX_MEASUREMENT_WORKERS`, lowered by
`DEVFLOW_SUITE_PROCESS_BUDGET`) and EVERY module's verdict is collected before anything is
reported: a run whose modules are measured one at a time is dominated by its longest module
regardless of host width. Any non-clean module still refuses the whole reconciliation, after
the pool has joined, and writes nothing.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

REGISTRY_PATH = "scripts/workflow-flight-recorder-registry.json"
RUN_PATH = "lib/test/run.sh"
SUMMARY = re.compile(
    r"^Module (?P<module>[a-z0-9][a-z0-9._-]*): "
    r"(?P<passed>[0-9]+) passed, (?P<failed>[0-9]+) failed"
    r"(?:, (?P<skipped>[0-9]+) skipped)?$",
    re.MULTILINE,
)


DIAGNOSTIC_TAIL_CHARS = 2000


# Do not raise this ceiling: each measurement is a whole `run-module.sh` process that
# itself spawns assertion subprocesses, so a wider pool oversubscribes the host and
# makes every module's wall clock worse than the serial run this replaced.
MAX_MEASUREMENT_WORKERS = 4


class Measurement(NamedTuple):
    """One module's verdict: EXACTLY one of `passed` / `refusal` is set.

    Construct through `clean` or `refused` — a direct call could represent the
    neither-set state the pool's consumption loop has no branch for.
    """

    module_id: str
    passed: int | None
    refusal: str | None

    @classmethod
    def clean(cls, module_id: str, passed: int) -> Measurement:
        return cls(module_id, passed, None)

    @classmethod
    def refused(cls, module_id: str, refusal: str) -> Measurement:
        return cls(module_id, None, refusal)


def _measurement_workers(count: int) -> int:
    """Bounded worker width for the measurement pool.

    `DEVFLOW_SUITE_PROCESS_BUDGET` — the same operator seam `lib/test/run-parallel.sh`
    reads — LOWERS the ceiling when it names a positive integer; a non-positive or
    non-numeric value is ignored rather than honored, so a malformed export cannot
    collapse the pool to nothing or widen it past the ceiling. The width never exceeds
    the number of modules to measure, and is never below 1.
    """
    ceiling = MAX_MEASUREMENT_WORKERS
    budget = (os.environ.get("DEVFLOW_SUITE_PROCESS_BUDGET") or "").strip()
    if budget.isdigit() and int(budget) >= 1:
        ceiling = min(ceiling, int(budget))
    return max(1, min(ceiling, count))


# Exact-policy modules whose module file actually reads MODULE_HEAVY_UNIT_MODE, so
# measuring them under `--heavy-units smoke` bounds a heavy unit that really runs. For
# every other exact-policy module `smoke` is a no-op that changes neither the tally nor
# the wall clock, so this set is a strict subset of exact_ids — do not add a module that
# ignores the mode (test_every_smoke_bound_module_reads_the_heavy_unit_mode enforces it
# from the tree). A module qualifies only when its bounded and full tallies are equal;
# harness-python-guards' heavy unit (devflow_run_sharded_python_test) is a
# single-assert_eq contract in lib/test/module-harness.sh, so its tally cannot move with
# the mode.
#
# Past-time snapshot — measured at origin/main 7d9691ecb (never machine-rendered):
#   lib/test/run-module.sh --heavy-units full  harness-python-guards -> 45 passed (~268 s wall)
#   lib/test/run-module.sh --heavy-units smoke harness-python-guards -> 45 passed (~54 s wall)
# The two `passed` tallies are equal, so the module is listed and the bound is real time.
HEAVY_UNIT_SMOKE_MODULES = frozenset({"harness-python-guards"})


def _measurement_argv(
    runner: Path, temporary_registry: Path, log_dir: Path, module_id: str
) -> list[str]:
    """Build the focused-runner argv for one exact-policy module's measurement.

    A module in HEAVY_UNIT_SMOKE_MODULES is measured under `--heavy-units smoke` so its
    heavy unit is bounded; every other module gets an argv byte-identical to the
    pre-#1499 form and carries no `--heavy-units` token. The flag pair sits immediately
    before `module_id`, which stays the trailing token — the focused-test fixture reads
    `args[-1]`, and `run-module.sh` takes the module id as its trailing positional
    argument. (reconcile() itself matches the module id in the runner's stdout SUMMARY
    line, not in argv, so it is indifferent to argv order.)
    """
    argv = [
        # The shell that RUNS a .sh helper is chosen at the invocation boundary via
        # DEVFLOW_BASH, never by a sourced resolver (#248): a hardcoded `bash` head would
        # ignore the operator's selected WSL/Git-Bash/MSYS2 interpreter and measure under
        # a different shell than the suite itself runs under.
        os.environ.get("DEVFLOW_BASH") or "bash",
        str(runner),
        "--registry",
        str(temporary_registry),
        "--log-dir",
        str(log_dir),
    ]
    if module_id in HEAVY_UNIT_SMOKE_MODULES:
        argv += ["--heavy-units", "smoke"]
    argv.append(module_id)
    return argv


def _fail(message: str) -> int:
    print(f"floor-reconciliation: INFRASTRUCTURE {message}", file=sys.stderr)
    return 2


def _diagnostics(proc: subprocess.CompletedProcess[str]) -> str:
    """Render a bounded tail of a failed measurement's own output.

    The measurement runs with `capture_output=True` and its per-module log directory
    lives inside the `TemporaryDirectory` that is destroyed the moment this function's
    caller returns, so without this the operator is told only a derived counter — no
    failing assertion name, no stderr, and no log left to open — for a failure that
    STOPS the batched pass. Bounded because a focused module run can emit thousands of
    passing lines and the tail is where the failure recap sits.
    """
    combined = (proc.stdout or "") + (proc.stderr or "")
    combined = combined.strip()
    if not combined:
        return "\n    output: (none)"
    if len(combined) > DIAGNOSTIC_TAIL_CHARS:
        combined = "…" + combined[-DIAGNOSTIC_TAIL_CHARS:]
    return f"\n    output: {combined}"


def _registry_floor_span(registry_text: str, module_id: str) -> tuple[int, int] | None:
    """Locate the module's own `minimum_assertions` digits in the registry SOURCE.

    The registry is rewritten textually rather than re-serialized, because
    `json.dumps` would reformat every unrelated byte — indentation, key order and
    non-ASCII escaping — turning a one-token floor raise into a whole-file diff
    that buries the change and conflicts with any concurrent registry edit. The
    scan walks the module's object with a string-aware depth counter so a brace
    or a `minimum_assertions` substring inside some other module's *string value*
    can never be selected. Returns the (start, end) offsets of the digit run, or
    None when the module's key or its floor cannot be uniquely located.
    """
    # Require a UNIQUE key match, mirroring the caller's one-site rule for the coupled
    # `run.sh` boundary. An unguarded first match would silently pick whichever
    # `"<id>": {` appeared first anywhere in the file — including one outside
    # `test_modules` — and rewrite a digit run inside the wrong object. Refusing on an
    # ambiguous match is the only fail direction that cannot corrupt a machine-consumed
    # floor.
    keys = list(re.finditer(rf'"{re.escape(module_id)}"\s*:\s*\{{', registry_text))
    if len(keys) != 1:
        return None
    key = keys[0]
    index = key.end()
    depth = 1
    in_string = False
    escaped = False
    while index < len(registry_text) and depth > 0:
        char = registry_text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        index += 1
    if depth != 0:
        return None
    floors = list(
        re.finditer(
            r'"minimum_assertions"\s*:\s*([0-9]+)', registry_text[key.end() : index]
        )
    )
    if len(floors) != 1:
        return None
    return (key.end() + floors[0].start(1), key.end() + floors[0].end(1))


def _site_pattern(module_id: str) -> re.Pattern[str]:
    return re.compile(
        rf'(devflow_run_full_suite_module\s+"\$LIB/test/modules/'
        rf'{re.escape(module_id)}[.]sh"\s*\\?\s+"{re.escape(module_id)}"\s+)'
        r"([0-9]+)(;\s*then)",
        re.MULTILINE,
    )


def _patch(root: Path, before: dict[Path, str], after: dict[Path, str]) -> bool:
    chunks: list[str] = []
    for path, before_text in before.items():
        relative = path.relative_to(root).as_posix()
        chunks.extend(
            difflib.unified_diff(
                before_text.splitlines(keepends=True),
                after[path].splitlines(keepends=True),
                fromfile=f"a/{relative}",
                tofile=f"b/{relative}",
            )
        )
    proc = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        cwd=root,
        input="".join(chunks),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        print(
            "floor-reconciliation: INFRASTRUCTURE the coupled patch was not applied: "
            f"{(proc.stdout + proc.stderr).strip() or '(no output)'}",
            file=sys.stderr,
        )
        return False
    return True


def reconcile(root: Path, runner: Path) -> int:
    registry_path = root / REGISTRY_PATH
    run_path = root / RUN_PATH
    try:
        registry_text = registry_path.read_text(encoding="utf-8")
        registry = json.loads(registry_text)
        run_text = run_path.read_text(encoding="utf-8")
        modules = registry["test_modules"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        return _fail(f"could not read the coupled floor sources ({error})")

    exact_ids = [
        module_id
        for module_id, mapping in modules.items()
        if isinstance(mapping, dict)
        and mapping.get("assertion_floor_policy") == "exact"
    ]
    if not exact_ids:
        return _fail("the registry selects no exact assertion-floor modules")

    measurements: dict[str, int] = {}
    sites: dict[str, tuple[re.Match[str], int]] = {}
    runner_environment = os.environ.copy()
    if temp_root := runner_environment.get("TMPDIR"):
        runner_environment["TMPDIR"] = temp_root.rstrip("/") or "/"
    # `lib/test/run-module.sh` injects a failing assertion when
    # DEVFLOW_TEST_EXPERIMENT_FORCE_FAILURE is "1", so an operator who left it exported
    # would turn every exact-policy module's measurement here into a refusal that names
    # the module rather than the override. Scrub it from the environment the focused
    # runner receives so the measurement reflects the module, never the experiment knob.
    runner_environment.pop("DEVFLOW_TEST_EXPERIMENT_FORCE_FAILURE", None)
    measurement_registry = copy.deepcopy(registry)
    for module_id in exact_ids:
        measurement_registry["test_modules"][module_id]["minimum_assertions"] = 1
        matches = list(_site_pattern(module_id).finditer(run_text))
        if len(matches) != 1:
            return _fail(
                f"{module_id}: expected one coupled run.sh boundary, found {len(matches)}"
            )
        sites[module_id] = (matches[0], int(matches[0].group(2)))

    with tempfile.TemporaryDirectory(prefix="devflow-floor-reconcile-") as temporary:
        temporary_path = Path(temporary)
        temporary_registry = temporary_path / "registry.json"
        temporary_registry.write_text(
            json.dumps(measurement_registry, indent=2) + "\n", encoding="utf-8"
        )
        def measure_one(module_id: str) -> Measurement:
            """Measure ONE module.

            Every failure is RETURNED rather than raised or acted on, so the pool joins
            before anything is reported: a first-failure abort would leave the remaining
            workers' processes running against a tree the caller is about to be told is
            unusable, and would hide every other module's verdict behind whichever one
            happened to finish first.
            """
            log_dir = temporary_path / f"logs-{module_id}"
            try:
                proc = subprocess.run(
                    _measurement_argv(runner, temporary_registry, log_dir, module_id),
                    cwd=root,
                    env=runner_environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
            except OSError as error:
                # A DEVFLOW_BASH or runner path that cannot be executed raises here.
                # Without this arm the helper dies with a traceback instead of the
                # INFRASTRUCTURE contract every other failure honors, and a standalone
                # invocation reports no attributable cause at all.
                return Measurement.refused(
                    module_id,
                    f"{module_id}: the measurement runner could not be launched "
                    f"({error})",
                )
            matches = [
                match
                for match in SUMMARY.finditer(proc.stdout)
                if match.group("module") == module_id
            ]
            if proc.returncode != 0 or len(matches) != 1:
                return Measurement.refused(
                    module_id,
                    f"{module_id}: focused run was not a single clean measurement "
                    f"(rc={proc.returncode}, summaries={len(matches)})"
                    f"{_diagnostics(proc)}",
                )
            summary = matches[0]
            failed = int(summary.group("failed"))
            skipped = int(summary.group("skipped") or 0)
            if failed != 0 or skipped != 0:
                return Measurement.refused(
                    module_id,
                    f"{module_id}: measurement was not clean "
                    f"(failed={failed}, skipped={skipped})"
                    f"{_diagnostics(proc)}",
                )
            return Measurement.clean(module_id, int(summary.group("passed")))

        def measure(module_id: str) -> Measurement:
            """Run `measure_one`, returning ANY unexpected exception as a refusal.

            A worker that raises would escape the exit-2 INFRASTRUCTURE contract every
            other failure honors and surface as a bare traceback from a pool thread.
            """
            try:
                return measure_one(module_id)
            except Exception as error:
                return Measurement.refused(
                    module_id,
                    f"{module_id}: the measurement raised an unexpected "
                    f"{type(error).__name__} ({error})",
                )

        # Do not switch to `as_completed` or to processes: `map` yields in argument order
        # so the report stays in registry order rather than in finishing order, and each
        # worker only waits on a subprocess, so the GIL is released throughout.
        refusals: list[str] = []
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=_measurement_workers(len(exact_ids))
        ) as pool:
            for result in pool.map(measure, exact_ids):
                if result.refusal is not None:
                    refusals.append(result.refusal)
                else:
                    measurements[result.module_id] = result.passed
        if refusals:
            for refusal in refusals[:-1]:
                print(
                    f"floor-reconciliation: INFRASTRUCTURE {refusal}", file=sys.stderr
                )
            return _fail(refusals[-1])

    decreases = []
    for module_id, measured in measurements.items():
        registry_floor = modules[module_id]["minimum_assertions"]
        run_floor = sites[module_id][1]
        if measured < registry_floor or measured < run_floor:
            decreases.append(
                f"{module_id} measured={measured} registry={registry_floor} run.sh={run_floor}"
            )
    if decreases:
        print(
            "floor-reconciliation: DECREASE REFUSED — " + "; ".join(decreases),
            file=sys.stderr,
        )
        return 1

    registry_after = registry_text
    updated_run = run_text
    raised = []
    for module_id, measured in measurements.items():
        registry_floor = modules[module_id]["minimum_assertions"]
        run_floor = sites[module_id][1]
        if measured > registry_floor or measured > run_floor:
            span = _registry_floor_span(registry_after, module_id)
            if span is None:
                return _fail(
                    f"{module_id}: could not uniquely locate its registry floor token"
                )
            registry_after = (
                registry_after[: span[0]] + str(measured) + registry_after[span[1] :]
            )
            updated_run, count = _site_pattern(module_id).subn(
                rf"\g<1>{measured}\g<3>", updated_run
            )
            if count != 1:
                return _fail(f"{module_id}: coupled run.sh site changed during staging")
            raised.append(module_id)

    if not raised:
        print("floor-reconciliation: clean — every measured tally matches both floors")
        return 0

    before = {registry_path: registry_text, run_path: run_text}
    after = {registry_path: registry_after, run_path: updated_run}
    if not _patch(root, before, after):
        return 2
    print("floor-reconciliation: RAISED — " + ", ".join(raised))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--runner", default=None)
    args = parser.parse_args(argv)
    root = (
        Path(args.repo_root).resolve()
        if args.repo_root
        else Path(__file__).resolve().parents[2]
    )
    # `or`, not `get(key, default)`: an exported-but-EMPTY override makes `get` return
    # "", and `Path("")` resolves to the repo root — the run then becomes `bash <root>`,
    # exits nonzero, and is misreported as an unclean MODULE when the fault is the
    # override. Empty-behaves-as-unset is the repo's rule for every DEVFLOW_* override.
    runner = Path(
        args.runner
        or os.environ.get("DEVFLOW_RECONCILE_MODULE_FLOORS_RUNNER")
        or root / "lib/test/run-module.sh"
    ).resolve()
    if not runner.is_file():
        return _fail(
            f"the measurement runner {runner} is not an existing file — check the "
            "--runner argument or the DEVFLOW_RECONCILE_MODULE_FLOORS_RUNNER override"
        )
    return reconcile(root, runner)


if __name__ == "__main__":
    raise SystemExit(main())
