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

The surface partition (which surfaces are the pre-suite `preflight` tier and which stay
`suite-only`) is the authoritative `MODULE_COUPLING_SURFACES` inventory in
`lib/test/regenerate-artifacts.py`; `PREFLIGHT_SURFACE_CHECKS` here is its executable
counterpart, and `test_module_coupling_surface_tiers_are_closed_complete_and_disjoint`
reconciles the two so they cannot drift.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

# The monolith-only pin helpers a focused module may not reference, and the direct `skip`
# call a module may not make (run-module.sh overrides `skip` to a fatal). Single-sourced here
# and re-imported by test_module_runner.py, which used to define them (issue #2121).
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

# The shards that carry focused modules (monolith/python-pool carry none). Read from the
# dispatcher at build time, not hardcoded as a membership list; this names only which shards
# to interrogate.
_MODULE_SHARDS = ("modules-pin", "modules-large", "modules-rest")

# The census cache must clear the swept population with at least this much headroom (AC42).
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
    coverage_row_ok: bool


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CouplingUncheckable(f"cannot load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so a module-level @dataclass can resolve its own __module__ via
    # sys.modules (a NoneType.__dict__ crash otherwise, e.g. mutation-pin-census.py).
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def module_ids(root: Path) -> tuple[str, ...]:
    """The on-disk focused-module ids, derived from lib/test/modules/*.sh (never a registry)."""
    return tuple(sorted(p.stem for p in (root / "lib/test/modules").glob("*.sh")))


def _shard_membership(root: Path) -> dict[str, tuple[str, ...]]:
    dispatcher = root / "lib/test/run-shard.sh"
    membership: dict[str, tuple[str, ...]] = {}
    for shard in _MODULE_SHARDS:
        try:
            proc = subprocess.run(
                ["bash", str(dispatcher), "--modules-of", shard],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as error:
            raise CouplingUncheckable(
                f"cannot enumerate shard membership for {shard}: {error}"
            ) from error
        if proc.returncode != 0:
            raise CouplingUncheckable(
                f"shard dispatcher failed for {shard} (exit {proc.returncode}): "
                f"{proc.stderr.strip() or '(no stderr)'}"
            )
        membership[shard] = tuple(proc.stdout.split())
    return membership


def _coverage_row_ok(root: Path) -> bool:
    """Coverage ownership is delegated to the existing coverage-map-ratchet preflight row.

    Rather than re-implement coverage_map_guard.py's population cross-check (a second,
    driftable copy), confirm the registry still carries that read-only, preflight-eligible
    row invoking the guard's non-writing `.` form. An import failure of the registry helper
    is an input failure, not a coupling omission.
    """
    try:
        ra = _load_module(root / "lib/test/regenerate-artifacts.py", "_ra_for_coupling")
    except CouplingUncheckable:
        raise
    except Exception as error:  # any import fault is uncheckable input, not a coupling omission
        raise CouplingUncheckable(
            f"cannot load the artifact registry for coverage-ownership: {error}"
        ) from error
    for row in getattr(ra, "ROWS", ()):
        if row.get("name") == "coverage-map-ratchet":
            argv = tuple(row.get("argv", ()))
            return bool(row.get("preflight_eligible")) and argv[-2:] == (
                "lib/test/coverage_map_guard.py",
                ".",
            )
    return False


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
        coverage_row_ok=_coverage_row_ok(root),
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


def surface_coverage_ownership(ctx: CouplingContext) -> list[str]:
    if not ctx.coverage_row_ok:
        return [
            (
                "coverage ownership: the preflight-eligible coverage-map-ratchet row "
                "(coverage_map_guard.py .) is missing or altered"
            )
        ]
    return []


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
    swept = set(ctx.swept_population)
    return [
        f"{module_id}: lib/test/modules/{module_id}.sh is outside the swept shell population"
        for module_id in ctx.module_ids
        if f"lib/test/modules/{module_id}.sh" not in swept
    ]


def surface_exact_policy_population_membership(ctx: CouplingContext) -> list[str]:
    on_disk = set(ctx.module_ids)
    failures = []
    for module_id, mapping in ctx.registry.items():
        if (
            isinstance(mapping, dict)
            and mapping.get("assertion_floor_policy") == "exact"
            and module_id not in on_disk
        ):
            failures.append(
                f"{module_id}: exact-policy registry entry names no on-disk module"
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
    ctx_or_root, *, population=None, capacity=None
) -> dict:
    """Numeric receipt for the mutation-census cache-capacity surface (AC42).

    Sizes the census parse cache against `len(swept population) + CACHE_CAPACITY_HEADROOM`,
    never `AUDITED_PIN_SOURCES`. `population`/`capacity` are injection seams for the census
    test to force the drift arm without a host-speed dependency.
    """
    if isinstance(ctx_or_root, CouplingContext):
        swept = list(ctx_or_root.swept_population)
        cache = ctx_or_root.cache_capacity
    else:
        census = _load_module(
            Path(ctx_or_root) / "lib/test/mutation-pin-census.py", "_census_for_receipt"
        )
        swept = list(census.swept_shell_population(Path(ctx_or_root)))
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


# The executable counterpart of MODULE_COUPLING_SURFACES's `preflight` tier in
# regenerate-artifacts.py. Ordered dict: surface id -> checker. Reconciled against the
# authoritative inventory by test_module_coupling_surface_tiers_are_closed_complete_and_disjoint.
PREFLIGHT_SURFACE_CHECKS = {
    "registry-membership": surface_registry_membership,
    "full-suite-invocation": surface_full_suite_invocation,
    "shard-membership": surface_shard_membership,
    "coverage-ownership": surface_coverage_ownership,
    "ci-shellcheck-membership": surface_ci_shellcheck_membership,
    "provenance-inventory": surface_provenance_inventory,
    "mutation-pin-fixture-membership": surface_mutation_pin_fixture_membership,
    "exact-policy-population-membership": surface_exact_policy_population_membership,
    "module-body-contract": surface_module_body_contract,
}

# The mutation-census cache-capacity assertion is folded into the same read-only check (AC42)
# but is NOT one of the enumerated MODULE_COUPLING_SURFACES tier entries — it is a numeric
# headroom bound, not a per-module wiring surface. Kept separate so the tier reconciliation
# above stays a clean bijection with the nine coupling surfaces.
ADDITIONAL_CHECKS = {
    "mutation-census-cache-capacity": surface_mutation_census_cache_capacity,
}


def run_checks(ctx: CouplingContext) -> dict[str, list[str]]:
    """Every preflight surface's failures plus the census-capacity check, keyed by id."""
    results = {surface: check(ctx) for surface, check in PREFLIGHT_SURFACE_CHECKS.items()}
    for name, check in ADDITIONAL_CHECKS.items():
        results[name] = check(ctx)
    return results


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
            root = (
                Path(out.stdout.strip())
                if out.returncode == 0 and out.stdout.strip()
                else Path(__file__).resolve().parents[2]
            )
        except OSError:
            root = Path(__file__).resolve().parents[2]

    try:
        ctx = build_context(root)
    except CouplingUncheckable as error:
        print(f"{INPUT_ERROR_MARKER} {error}", file=sys.stderr)
        return 2

    results = run_checks(ctx)
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
