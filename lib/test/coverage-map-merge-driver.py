#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""JSON-aware git merge driver for the coverage map (issue #1194).

`lib/test/modules/coverage-map.json` stores two large string-sorted JSON objects
(`files`, `run_sh_blocks`). When two branches each ADD a different key whose sort
positions are adjacent, git's line-based three-way merge sees one insertion point
and reports a textual conflict even though the two sides never semantically
conflict. Resolving such a conflict by taking either side silently DELETES the
other branch's entry.

This driver removes that class on the local merge/rebase path: git invokes it with
the ancestor/ours/theirs versions of the file, it parses all three as JSON, and it
does a per-KEY three-way merge of each object rather than a per-LINE one. Two
branches that add distinct keys therefore both survive; a genuine same-key
divergence (both sides changed the SAME key to different values) is left as a
conflict that requires a human decision, never silently resolved to one side.

Modes (one file, three jobs — AC6 wants "a registration path together with a
desk-runnable check"):

  merge  (default, three positional args `%O %A %B`) — the git-invoked path.
         Writes the merged result into the ours-path (`%A`) and exits 0 on a clean
         merge, non-zero (leaving conflict markers in `%A`) on a genuine conflict.
  --register — register `merge.coverage-map-json.driver` in THIS clone's local
         git config so the `.gitattributes` `merge=coverage-map-json` declaration
         resolves to this program. Never touches the global/user config.
  --check — verify the driver is active in this clone; exit non-zero with the exact
         registration command when it is not. A `.gitattributes` `merge=`
         declaration alone does NOT satisfy this: git falls back silently to the
         built-in three-way merge when `merge.<name>.driver` is undefined locally,
         reproducing the defect while appearing configured.

The driver is client-side only — it runs where a git client has it registered, and
NOT on GitHub's servers or in the web conflict editor. The CI-side key-retention
check (`lib/test/coverage-map-retention-check.py`) covers that path.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

DRIVER_NAME = "coverage-map-json"
MAP_REL = "lib/test/modules/coverage-map.json"
DRIVER_REL = "lib/test/coverage-map-merge-driver.py"
# The git merge-driver command line the `.gitattributes` `merge=coverage-map-json`
# attribute resolves to. `%O`/`%A`/`%B` are git's ancestor/ours/theirs placeholders;
# git runs the driver from the repository root, so a repo-relative path resolves.
DRIVER_COMMAND = f"python3 {DRIVER_REL} %O %A %B"
REGISTER_COMMAND = f"python3 {DRIVER_REL} --register"

# Reuse the coverage guard's ONE canonical serialization (issue #1065's
# `_serialize_map`) so a merged result is byte-identical to what `--fix` writes and
# arm 11 accepts — the driver must never emit a non-canonical map that the next
# guard run would then flag. Loaded by file location (the guard is a sibling in
# lib/test/, not an installed module).
_GUARD_PATH = Path(__file__).resolve().parent / "coverage_map_guard.py"
try:
    _spec = importlib.util.spec_from_file_location("coverage_map_guard", _GUARD_PATH)
    if _spec is None or _spec.loader is None:
        raise ImportError(f"no loadable spec for {_GUARD_PATH}")
    _guard = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_guard)
except Exception as _exc:  # pragma: no cover - exercised only on a broken checkout
    raise SystemExit(
        f"coverage-map-merge-driver: the coverage guard {_GUARD_PATH} could not be "
        f"loaded ({_exc.__class__.__name__}: {_exc}); refusing to merge"
    ) from _exc

_serialize_map = _guard._serialize_map


class MergeConflict(Exception):
    """Raised when a per-key three-way merge cannot resolve without a human."""

    def __init__(self, conflicts: list[str]) -> None:
        super().__init__("; ".join(conflicts))
        self.conflicts = conflicts


def _load(path: Path):
    """Parse PATH as JSON, or raise MergeConflict naming it (an unparseable side is
    not something the driver may silently paper over)."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        # A merge base that did not contain the file (the map did not yet exist) is a
        # legitimate two-way add; treat an absent ancestor as the empty object.
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MergeConflict([f"{path} is not readable JSON ({error})"]) from error


def _three_way_object(base: dict, ours: dict, theirs: dict, where: str) -> dict:
    """Per-key three-way merge of one JSON object.

    For each key in the union, the standard three-way rule:
      * ours == theirs                 → take it (both-absent, both-added-identical)
      * ours == base (ours unchanged)  → take theirs (incl. a delete on theirs)
      * theirs == base (theirs unchanged) → take ours (incl. a delete on ours)
      * otherwise                      → both sides changed the key differently: a
                                         genuine conflict that needs a human.
    The union of DISTINCT added keys resolves cleanly: each added key is absent on
    the other side and in the base, so exactly one of the middle two rules fires."""
    merged: dict = {}
    conflicts: list[str] = []
    absent = object()
    for key in sorted(set(base) | set(ours) | set(theirs)):
        b = base.get(key, absent)
        o = ours.get(key, absent)
        t = theirs.get(key, absent)
        if o == t:
            chosen = o
        elif o == b:
            chosen = t
        elif t == b:
            chosen = o
        else:
            conflicts.append(f"{where}[{key!r}] changed differently on both sides")
            continue
        if chosen is not absent:
            merged[key] = chosen
    if conflicts:
        raise MergeConflict(conflicts)
    return merged


def merge_maps(base: dict, ours: dict, theirs: dict) -> dict:
    """Three-way merge of two whole coverage maps.

    `files` and `run_sh_blocks` merge per-key (the whole point); every other
    top-level key merges with the same three-way scalar rule so a real divergence in
    `schema_version`/`generated_by`/the exempt arrays still conflicts rather than
    silently picking a side."""
    if not all(isinstance(m, dict) for m in (base, ours, theirs)):
        raise MergeConflict(["a merge input is not a JSON object"])
    merged: dict = {}
    conflicts: list[str] = []
    per_key_objects = ("files", "run_sh_blocks")
    for section in per_key_objects:
        b = base.get(section, {})
        o = ours.get(section, {})
        t = theirs.get(section, {})
        if not all(isinstance(v, dict) for v in (b, o, t)):
            conflicts.append(f"{section!r} is not an object on every side")
            continue
        try:
            merged[section] = _three_way_object(b, o, t, section)
        except MergeConflict as mc:
            conflicts.extend(mc.conflicts)
    # Every remaining top-level key merges by the SAME per-key three-way rule
    # `_three_way_object` owns — a whole-value comparison of `schema_version`,
    # `generated_by`, and the exempt arrays — so delegate rather than re-inline the
    # ladder (the per_key_objects above already merged recursively and are excluded).
    rest = {
        which: {k: v for k, v in m.items() if k not in per_key_objects}
        for which, m in (("base", base), ("ours", ours), ("theirs", theirs))
    }
    try:
        merged.update(_three_way_object(rest["base"], rest["ours"], rest["theirs"], "top-level"))
    except MergeConflict as mc:
        conflicts.extend(mc.conflicts)
    if conflicts:
        raise MergeConflict(conflicts)
    return merged


def _conflict_body(ours_path: Path, theirs_path: Path, conflicts: list[str]) -> str:
    """A git-style conflict-marked body describing the genuine divergence.

    Left in the ours-path so a human sees exactly which keys diverged. It is
    deliberately invalid JSON: the coverage guard's arm 4 fails closed on a committed
    conflict-marked map, so an unresolved conflict can never ship green either."""
    detail = "\n".join(f"# {c}" for c in conflicts)
    return (
        "<<<<<<< ours (this branch)\n"
        f"{ours_path.read_text(encoding='utf-8')}"
        "=======\n"
        "# coverage-map merge driver: genuine same-key divergence — resolve by hand.\n"
        f"{detail}\n"
        f"{theirs_path.read_text(encoding='utf-8')}"
        ">>>>>>> theirs (incoming)\n"
    )


def _run_merge(argv: list[str]) -> int:
    if len(argv) < 3:
        print(
            "coverage-map-merge-driver: merge mode needs three paths (%O %A %B)",
            file=sys.stderr,
        )
        return 2
    base_path, ours_path, theirs_path = (Path(argv[0]), Path(argv[1]), Path(argv[2]))
    try:
        try:
            base = _load(base_path)
        except FileNotFoundError:
            base = {}
        # ours/theirs are the working versions git always materializes; a genuinely
        # missing one is an environment fault, so fail loudly with a clear message and a
        # merge-failed exit (2) rather than an opaque traceback — never a silent merge.
        try:
            ours = _load(ours_path)
            theirs = _load(theirs_path)
        except FileNotFoundError as error:
            print(
                f"coverage-map-merge-driver: a merge input file is missing ({error}); "
                f"cannot merge {MAP_REL}",
                file=sys.stderr,
            )
            return 2
        merged = merge_maps(base, ours, theirs)
    except MergeConflict as mc:
        # Leave conflict markers in the ours-path and fail so git records the path as
        # unmerged and stops for a human decision (AC3).
        try:
            body = _conflict_body(ours_path, theirs_path, mc.conflicts)
            ours_path.write_text(body, encoding="utf-8")
        except (OSError, UnicodeError):
            pass
        print(
            f"coverage-map-merge-driver: conflict — {mc}; resolve "
            f"{MAP_REL} by hand",
            file=sys.stderr,
        )
        return 1
    # A clean merge: write the canonical serialization into the ours-path (%A), which
    # git adopts as the merge result.
    try:
        ours_path.write_bytes(_serialize_map(merged).encode("utf-8"))
    except (OSError, UnicodeError, TypeError, ValueError) as error:
        print(
            f"coverage-map-merge-driver: could not write merged {MAP_REL} ({error})",
            file=sys.stderr,
        )
        return 2
    return 0


def _git_config_get(key: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "config", "--local", "--get", key],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _run_register() -> int:
    key = f"merge.{DRIVER_NAME}.driver"
    name_key = f"merge.{DRIVER_NAME}.name"
    try:
        subprocess.run(
            ["git", "config", "--local", name_key, "coverage-map JSON-aware merge driver"],
            check=True,
        )
        subprocess.run(["git", "config", "--local", key, DRIVER_COMMAND], check=True)
    except (FileNotFoundError, OSError, subprocess.CalledProcessError) as error:
        print(
            f"coverage-map-merge-driver: could not register the driver ({error}); "
            "run this from inside the git clone",
            file=sys.stderr,
        )
        return 1
    print(
        f"coverage-map-merge-driver: registered '{DRIVER_NAME}' "
        f"(merge.{DRIVER_NAME}.driver = {DRIVER_COMMAND})"
    )
    return 0


def _run_check() -> int:
    key = f"merge.{DRIVER_NAME}.driver"
    active = _git_config_get(key)
    if active == DRIVER_COMMAND:
        print(f"coverage-map-merge-driver: driver '{DRIVER_NAME}' is active in this clone")
        return 0
    if active:
        print(
            f"coverage-map-merge-driver: merge.{DRIVER_NAME}.driver is set to {active!r}, "
            f"not the expected {DRIVER_COMMAND!r} — re-run: {REGISTER_COMMAND}",
            file=sys.stderr,
        )
        return 1
    print(
        f"coverage-map-merge-driver: the '{DRIVER_NAME}' merge driver is NOT registered in "
        "this clone, so git silently falls back to its line-based three-way merge and "
        f"{MAP_REL} will conflict on adjacent key insertions (issue #1194). Register it:\n"
        f"    {REGISTER_COMMAND}",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(add_help=True, description=__doc__)
    parser.add_argument("--register", action="store_true", help="register the driver in this clone")
    parser.add_argument("--check", action="store_true", help="verify the driver is active; exit non-zero if not")
    parser.add_argument("paths", nargs="*", help="git merge placeholders: %%O %%A %%B")
    args = parser.parse_args(argv[1:])
    if args.register and args.check:
        print("coverage-map-merge-driver: pass at most one of --register/--check", file=sys.stderr)
        return 2
    if args.register:
        return _run_register()
    if args.check:
        return _run_check()
    return _run_merge(args.paths)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
