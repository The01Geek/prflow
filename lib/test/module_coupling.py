#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Reusable module-coupling surfaces for the pre-suite gate (issue #2121).

`test_every_on_disk_module_is_fully_wired` (lib/test/test_module_runner.py) proved that a
new `lib/test/modules/*.sh` module is wired across every coupled surface — registered,
called from run.sh at a matching floor, sharded, shellcheck-listed, provenance-paired, and
contract-conforming. That assertion ran only inside the Python suite, minutes into a run. This
module factors those surfaces into reusable, stdlib-only checkers so the SAME logic backs both
that focused test AND the read-only `module-coupling` preflight row in
`lib/test/regenerate-artifacts.py`, which fails the coordinator's pre-suite gate in well under a
second when a coupling is left stale.

Each surface is a pure function over a `CouplingContext` returning a list of human-readable
failure strings (empty == clean). `build_context(root)` assembles the real data with real
registry parsing; an input failure (an unreadable registry, a git enumeration failure) raises
`CouplingUncheckable`, which the `--check` CLI reports with the `[input-error]` marker and
exit 2 so the preflight routes it to UNCHECKABLE rather than drift.

`PREFLIGHT_SURFACE_CHECKS` is the closed, ordered set of surfaces; the receipt's `checks=`
field is its key list.
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

# The monolith-only pin helpers a focused module may not reference, and the direct `skip`
# call a module may not make (run-module.sh overrides `skip` to a fatal). test_module_runner.py
# imports these — a second definition there would let the two lists drift apart.
MONOLITH_HELPER_RE = re.compile(
    r"(?:^|[^A-Za-z0-9_])"
    r"(pin_count|grep_present"
    r"|assert_pin_unique|assert_pin_red_on_removal)"
    r"(?:[^A-Za-z0-9_]|$)"
)
MODULE_SKIP_CALL_RE = re.compile(r"^[ \t]*skip(?:[ \t]|$)", re.MULTILINE)

# The module-body contract header line every focused module must carry.
_MODULE_CONTRACT_TEXT = "Contract: the caller sets LIB and RESULTS_FILE"
_SPDX_HEADER = (
    "# SPDX-FileCopyrightText: 2026 Daniel Radman\n"
    "# SPDX-License-Identifier: MIT\n"
)

# The dispatcher's module-carrying shards share this name prefix (monolith/python-pool carry none).
_MODULE_SHARD_PREFIX = "modules-"

# The census cache must clear the swept population with at least this much headroom.
CACHE_CAPACITY_HEADROOM = 5

# The machine marker the CLI prints for an input failure, so the preflight routes it to
# UNCHECKABLE (never drift), mirroring coverage_map_guard.py's `[input-error]` convention.
INPUT_ERROR_MARKER = "module-coupling: [input-error]"


class CouplingUncheckable(Exception):
    """An input failure that leaves the coupling surfaces unmeasurable (routed to UNCHECKABLE)."""


@dataclasses.dataclass(frozen=True)
class CouplingContext:
    root: Path
    module_ids: tuple[str, ...]
    registry: dict
    run_text: str
    ci_text: str
    shard_modules: dict[str, tuple[str, ...]]
    inventory_ids: frozenset[str]
    module_texts: dict[str, str]
    swept_population: tuple[str, ...]
    cache_capacity: int
    audited_pin_sources: frozenset[str]
    expected_source_count: int
    declared_exact_population: tuple[str, ...]


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CouplingUncheckable(f"cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so a module-level @dataclass can resolve its own __module__ via
    # sys.modules (a NoneType.__dict__ crash otherwise, e.g. mutation-pin-census.py).
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as error:  # an import failure is an input failure, not a coupling omission
        raise CouplingUncheckable(f"cannot import {name} from {path}: {error}") from error
    return module


def module_ids(root: Path) -> tuple[str, ...]:
    """The on-disk focused-module ids, derived from lib/test/modules/*.sh (never a registry)."""
    return tuple(sorted(p.stem for p in (root / "lib/test/modules").glob("*.sh")))


def _dispatcher(root: Path, *args: str) -> list[str]:
    try:
        proc = subprocess.run(
            ["bash", str(root / "lib/test/run-shard.sh"), *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise CouplingUncheckable(f"cannot run the shard dispatcher {args}: {error}") from error
    if proc.returncode != 0:
        raise CouplingUncheckable(
            f"shard dispatcher failed for {args} (exit {proc.returncode}): "
            f"{proc.stderr.strip() or '(no stderr)'}"
        )
    return proc.stdout.split()


def _shard_membership(root: Path) -> dict[str, tuple[str, ...]]:
    """Module ids per module-carrying shard, both derived from `run-shard.sh` itself."""
    shards = [s for s in _dispatcher(root, "--list-shards") if s.startswith(_MODULE_SHARD_PREFIX)]
    if not shards:
        raise CouplingUncheckable("the shard dispatcher lists no modules-* shard")
    return {shard: tuple(_dispatcher(root, "--modules-of", shard)) for shard in shards}


def _audited_pin_sources(root: Path) -> frozenset[str]:
    """The literal `AUDITED_PIN_SOURCES` frozenset in lib/test/pin-corpus-lint.py, by AST."""
    linter = root / "lib/test/pin-corpus-lint.py"
    try:
        tree = ast.parse(linter.read_text(encoding="utf-8"), filename=str(linter))
    except (OSError, SyntaxError, ValueError) as error:
        raise CouplingUncheckable(f"cannot parse AUDITED_PIN_SOURCES: {error}") from error
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "AUDITED_PIN_SOURCES" for t in node.targets
        ):
            value = node.value
            if isinstance(value, ast.Call) and len(value.args) == 1:
                value = value.args[0]
            try:
                return frozenset(ast.literal_eval(value))
            except (ValueError, TypeError) as error:
                raise CouplingUncheckable(f"AUDITED_PIN_SOURCES is not a literal set: {error}") from error
    raise CouplingUncheckable("AUDITED_PIN_SOURCES has no top-level definition")


_EXACT_POPULATION_TEST = "test_repository_declares_the_exact_floor_population"


def _declared_exact_population(root: Path) -> tuple[str, ...]:
    """The hand-named exact-floor module list in test_module_runner.py's population test, by AST.

    The list is deliberately maintained by hand there (a reviewer-read diff, not a count), so
    this reads the single literal in that test rather than duplicating it here.
    """
    source = root / "lib/test/test_module_runner.py"
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    except (OSError, SyntaxError, ValueError) as error:
        raise CouplingUncheckable(f"cannot parse the exact-floor population test: {error}") from error
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == _EXACT_POPULATION_TEST:
            lists = [n for n in ast.walk(node) if isinstance(n, ast.List)]
            if len(lists) != 1:
                raise CouplingUncheckable(
                    f"{_EXACT_POPULATION_TEST} must contain exactly one list literal, found {len(lists)}"
                )
            try:
                return tuple(ast.literal_eval(lists[0]))
            except (ValueError, TypeError) as error:
                raise CouplingUncheckable(f"exact-floor population is not a literal: {error}") from error
    raise CouplingUncheckable(f"{_EXACT_POPULATION_TEST} not found in {source}")



def build_context(root: Path) -> CouplingContext:
    root = Path(root)
    registry_path = root / "scripts/workflow-flight-recorder-registry.json"
    try:
        registry_doc = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CouplingUncheckable(f"cannot read the module registry: {error}") from error
    registry = registry_doc.get("test_modules")
    if not isinstance(registry, dict):
        raise CouplingUncheckable("registry test_modules is missing or not a mapping")
    try:
        run_text = (root / "lib/test/run.sh").read_text(encoding="utf-8")
        ci_text = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    except OSError as error:
        raise CouplingUncheckable(f"cannot read a coupled source: {error}") from error

    ids = module_ids(root)
    module_texts: dict[str, str] = {}
    inventory_ids = set()
    for module_id in ids:
        try:
            module_texts[module_id] = (
                root / f"lib/test/modules/{module_id}.sh"
            ).read_text(encoding="utf-8")
        except OSError as error:
            raise CouplingUncheckable(
                f"cannot read module {module_id}: {error}"
            ) from error
        if (root / f"lib/test/modules/{module_id}.inventory.md").is_file():
            inventory_ids.add(module_id)

    census = _load_module(root / "lib/test/mutation-pin-census.py", "_census_for_coupling")
    try:
        swept = tuple(census.swept_shell_population(root))
        cache_capacity = int(census._SOURCE_PARSE_CACHE_SIZE)
        expected_source_count = int(census.EXPECTED_SOURCE_COUNT)
    except Exception as error:  # a census input failure is uncheckable, not a coupling omission
        raise CouplingUncheckable(
            f"cannot derive the swept shell population: {error}"
        ) from error

    return CouplingContext(
        root=root,
        module_ids=ids,
        registry=registry,
        run_text=run_text,
        ci_text=ci_text,
        shard_modules=_shard_membership(root),
        inventory_ids=frozenset(inventory_ids),
        module_texts=module_texts,
        swept_population=swept,
        cache_capacity=cache_capacity,
        audited_pin_sources=_audited_pin_sources(root),
        expected_source_count=expected_source_count,
        declared_exact_population=_declared_exact_population(root),
    )


# ── Surface checkers (each: CouplingContext -> list[str] of failures) ─────────


def surface_registry_membership(ctx: CouplingContext) -> list[str]:
    failures = []
    for module_id in ctx.module_ids:
        mapping = ctx.registry.get(module_id)
        if not isinstance(mapping, dict):
            failures.append(f"{module_id}: on disk but unregistered in the module registry")
            continue
        expected = f"lib/test/modules/{module_id}.sh"
        if mapping.get("path") != expected:
            failures.append(f"{module_id}: registry path {mapping.get('path')!r} != {expected!r}")
        floor = mapping.get("minimum_assertions")
        if not isinstance(floor, int) or isinstance(floor, bool) or floor <= 0:
            failures.append(f"{module_id}: registry minimum_assertions {floor!r} is not a positive int")
    return failures


def surface_full_suite_invocation(ctx: CouplingContext) -> list[str]:
    failures = []
    for module_id in ctx.module_ids:
        if f'devflow_run_full_suite_module "$LIB/test/modules/{module_id}.sh"' not in ctx.run_text:
            failures.append(f"{module_id}: never invoked from run.sh's full-suite boundary")
            continue
        floor_match = re.search(rf'"{re.escape(module_id)}" ([0-9]+); then', ctx.run_text)
        mapping = ctx.registry.get(module_id) or {}
        registry_floor = mapping.get("minimum_assertions")
        if floor_match is None:
            failures.append(f"{module_id}: no run.sh call-site floor literal")
        elif isinstance(registry_floor, int) and int(floor_match.group(1)) != registry_floor:
            failures.append(
                f"{module_id}: run.sh floor {floor_match.group(1)} != registry floor {registry_floor}"
            )
    return failures


def surface_shard_membership(ctx: CouplingContext) -> list[str]:
    failures = []
    for module_id in ctx.module_ids:
        owning = [shard for shard, mods in ctx.shard_modules.items() if module_id in mods]
        if len(owning) != 1:
            failures.append(
                f"{module_id}: appears in {len(owning)} module shard(s) {owning}, must be exactly one"
            )
    return failures



def surface_ci_shellcheck_membership(ctx: CouplingContext) -> list[str]:
    failures = []
    for module_id in ctx.module_ids:
        if f"lib/test/modules/{module_id}.sh" not in ctx.ci_text:
            failures.append(f"{module_id}: not in ci.yml's explicit shellcheck list")
    return failures


def surface_provenance_inventory(ctx: CouplingContext) -> list[str]:
    return [
        f"{module_id}: has no lib/test/modules/{module_id}.inventory.md"
        for module_id in ctx.module_ids
        if module_id not in ctx.inventory_ids
    ]


def surface_mutation_pin_fixture_membership(ctx: CouplingContext) -> list[str]:
    """Every module is in pin-corpus-lint.py's AUDITED_PIN_SOURCES, and its size literal agrees."""
    failures = [
        f"{module_id}: lib/test/modules/{module_id}.sh is not in AUDITED_PIN_SOURCES "
        "(lib/test/pin-corpus-lint.py)"
        for module_id in ctx.module_ids
        if f"lib/test/modules/{module_id}.sh" not in ctx.audited_pin_sources
    ]
    if len(ctx.audited_pin_sources) != ctx.expected_source_count:
        failures.append(
            f"AUDITED_PIN_SOURCES has {len(ctx.audited_pin_sources)} entries but "
            f"mutation-pin-census.py EXPECTED_SOURCE_COUNT is {ctx.expected_source_count}"
        )
    return failures


def surface_exact_policy_population_membership(ctx: CouplingContext) -> list[str]:
    """The registry's `assertion_floor_policy: exact` set equals the hand-named test population."""
    registry_exact = {
        module_id
        for module_id, mapping in ctx.registry.items()
        if isinstance(mapping, dict) and mapping.get("assertion_floor_policy") == "exact"
    }
    declared = set(ctx.declared_exact_population)
    failures = [
        f"{module_id}: registry declares assertion_floor_policy exact but "
        f"{_EXACT_POPULATION_TEST} does not name it"
        for module_id in sorted(registry_exact - declared)
    ]
    failures.extend(
        f"{module_id}: named by {_EXACT_POPULATION_TEST} but the registry does not "
        "declare it assertion_floor_policy exact"
        for module_id in sorted(declared - registry_exact)
    )
    return failures


def surface_module_body_contract(ctx: CouplingContext) -> list[str]:
    failures = []
    for module_id in ctx.module_ids:
        text = ctx.module_texts[module_id]
        if not text.startswith(_SPDX_HEADER):
            failures.append(f"{module_id}: missing/incorrect SPDX header")
        if _MODULE_CONTRACT_TEXT not in text:
            failures.append(f"{module_id}: missing caller-contract text")
        if "devflow_run_full_suite_module" in text:
            failures.append(f"{module_id}: self-invokes the full-suite boundary")
        module_code = "\n".join(
            line for line in text.split("\n") if not line.lstrip().startswith("#")
        )
        helper_hits = sorted(
            {match.group(1) for match in MONOLITH_HELPER_RE.finditer(module_code)}
        )
        if helper_hits:
            failures.append(f"{module_id}: references monolith-only helper(s) {helper_hits}")
        if MODULE_SKIP_CALL_RE.search(module_code):
            failures.append(f"{module_id}: calls skip directly")
    return failures


def census_cache_receipt(
    ctx_or_root, *, population=None, capacity=None, timeout=None
) -> dict:
    """Numeric receipt for the mutation-census cache-capacity surface.

    Sizes the census parse cache against `len(swept population) + CACHE_CAPACITY_HEADROOM`,
    never `AUDITED_PIN_SOURCES`. `population`/`capacity` are injection seams for the census
    test to force the drift arm without a host-speed dependency; `timeout` (seconds) bounds
    the root-form git enumeration and surfaces an overrun as `CensusError`.
    """
    if isinstance(ctx_or_root, CouplingContext):
        swept = list(ctx_or_root.swept_population)
        cache = ctx_or_root.cache_capacity
    else:
        census = _load_module(
            Path(ctx_or_root) / "lib/test/mutation-pin-census.py", "_census_for_receipt"
        )
        swept = list(census.swept_shell_population(Path(ctx_or_root), timeout=timeout))
        cache = int(census._SOURCE_PARSE_CACHE_SIZE)
    if population is not None:
        swept = list(population)
    if capacity is not None:
        cache = int(capacity)
    tracked = len(swept)
    required_minimum = tracked + CACHE_CAPACITY_HEADROOM
    return {
        "tracked_shell_count": tracked,
        "cache_capacity": cache,
        "required_minimum": required_minimum,
        "headroom": cache - tracked,
        "ok": cache >= required_minimum,
    }


def surface_mutation_census_cache_capacity(ctx: CouplingContext) -> list[str]:
    receipt = census_cache_receipt(ctx)
    if not receipt["ok"]:
        return [
            (
                "mutation-census cache capacity: _SOURCE_PARSE_CACHE_SIZE "
                f"{receipt['cache_capacity']} < swept population "
                f"{receipt['tracked_shell_count']} + {CACHE_CAPACITY_HEADROOM} headroom = "
                f"{receipt['required_minimum']} — raise the bound (lost memo reuse, a "
                "performance regression)"
            )
        ]
    return []


# Ordered: surface id -> checker. The receipt's `checks=` field is this key list.
PREFLIGHT_SURFACE_CHECKS = {
    "registry-membership": surface_registry_membership,
    "full-suite-invocation": surface_full_suite_invocation,
    "shard-membership": surface_shard_membership,
    "ci-shellcheck-membership": surface_ci_shellcheck_membership,
    "provenance-inventory": surface_provenance_inventory,
    "mutation-pin-fixture-membership": surface_mutation_pin_fixture_membership,
    "exact-policy-population-membership": surface_exact_policy_population_membership,
    "module-body-contract": surface_module_body_contract,
    "mutation-census-cache-capacity": surface_mutation_census_cache_capacity,
}


def run_checks(ctx: CouplingContext) -> dict[str, list[str]]:
    """Every preflight surface's failures, keyed by id."""
    return {surface: check(ctx) for surface, check in PREFLIGHT_SURFACE_CHECKS.items()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only module-coupling check: validate every on-disk focused module is wired "
            "across the preflight coupling surfaces. Exit 0 clean / 1 drift / 2 uncheckable."
        )
    )
    parser.add_argument("--check", action="store_true", help="Run the coupling surfaces.")
    parser.add_argument("--repo-root", default=None, help="Root to check (defaults to git toplevel).")
    args = parser.parse_args(argv)

    if args.repo_root:
        root = Path(args.repo_root).resolve()
    else:
        try:
            out = subprocess.run(
                ("git", "rev-parse", "--show-toplevel"),
                cwd=str(Path(__file__).resolve().parents[2]),
                capture_output=True,
                text=True,
                check=False,
            )
            root = Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None
        except OSError:
            root = None
        if root is None:
            root = Path(__file__).resolve().parents[2]
            print(
                f"module-coupling: git rev-parse --show-toplevel failed; falling back to {root}",
                file=sys.stderr,
            )

    try:
        ctx = build_context(root)
        results = run_checks(ctx)
    except CouplingUncheckable as error:
        print(f"{INPUT_ERROR_MARKER} {error}", file=sys.stderr)
        return 2
    except Exception as error:
        # Exit 1 is inside the row's declared `exits` (the DRIFT arm): an escaped traceback
        # would refuse the whole suite launch over an input error. Route it to exit 2.
        print(f"{INPUT_ERROR_MARKER} unexpected {type(error).__name__}: {error}", file=sys.stderr)
        return 2

    drift = False
    for surface, failures in results.items():
        if failures:
            drift = True
            for failure in failures:
                print(f"module-coupling: DRIFT [{surface}] {failure}")
        else:
            print(f"module-coupling: clean [{surface}]")
    if drift:
        print(
            "module-coupling: coupling drift — wire the module(s) above across every coupled "
            "surface and commit before the suite run"
        )
        return 1
    print("module-coupling: every on-disk module is fully wired")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
