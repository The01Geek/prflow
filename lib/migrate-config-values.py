#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Migrate the superseded `devflow` spellings a consumer config carries in its
VALUES and NESTED KEYS (issue #1028, Axis 2) — and report the ones that stay.

`scripts/scaffold-config.sh`'s `PRFLOW_MIGRATE_PY` renames TOP-LEVEL config keys and
stops there, so after a Tier-1 migration a consumer's `.prflow/config.json` still spells
the superseded product name in four places. This helper renames those, so the config
reads `prflow` / `PRFlow` throughout:

  1. `agent_overrides` KEYS      `devflow:<leaf>` -> `prflow:<leaf>`
  2. the `workpad_marker` VALUE  `<!-- devflow:...` -> `<!-- prflow:...`
  3. `docs.labels` VALUE         the `DevFlow` provenance label -> `PRFlow`
  4. `deferred.labels` VALUE     ditto

Every one is safe because each reader dual-accepts both spellings, in both directions:
the accepted subagent namespaces come from `lib/plugin-identity.json` (canonical first),
`scripts/workpad.py`'s marker pair and `lib/fetch-pr-context.sh` map either marker
namespace onto the other, `scripts/resolve-implement-trigger.sh` DERIVES the superseded
marker from the configured one (so the self-trigger guard keeps recognising a pre-rename
workpad and does not fail open into a duplicate run), and label SELECTION accepts both
spellings through the single `--search "label:PRFlow,DevFlow"` OR qualifier.

WHAT IT MUST NOT TOUCH, and why each would break something:

  - `workflows.devflow` / `workflows.devflow-review` — these ARE renamed (issue #1041,
    `workflows.prflow` / `workflows.prflow-review`), but NOT here: their readers do not
    dual-accept (the shipped workflows read `.workflows.prflow // false`, so a config that
    moved ahead of a stale workflow reads as "disabled"), so they migrate only under the
    freshness gate in `scripts/scaffold-config.sh` (`workflows_config_keys` in the rename
    map). This ungated value pass leaves them exactly as it finds them.
  - the `DEVFLOW_*` ENVIRONMENT identifiers — they live in GitHub org/repo settings and
    shell profiles, so no config migration can reach them. The advisory POINTS at
    `lib/generate-env-freeze-advisory.py`, which owns that inventory, and deliberately
    does not restate a row of it.
  - `allowed_bots` entries such as a `devflow`-spelled bot login — those are real GitHub
    logins, and renaming one breaks authorization unless the account itself was renamed.
  - absolute workspace paths inside tool grants — those name a consumer's own repository,
    so a general migrator cannot know what they should become.

There is NO freshness gate here, deliberately. The top-level key migration needs one
because the trigger-time channel reads those key names out of the workflow files, so a
config that moved ahead of a stale workflow is silently mis-read. These are values and
nested keys whose readers all dual-accept, so no such skew exists.

CONFLICT RULE (both spellings present). Mirrors the top-level migration's shape: when a
config carries both `devflow:<leaf>` and `prflow:<leaf>` in `agent_overrides`, the
current-spelled entry is compared against the shipped example. If it still holds the
example default it was GRAFTED by the scaffolder's deep merge rather than authored, so
the consumer's superseded value wins and is written at the position the current key
already occupies. Otherwise it is a deliberate consumer edit that a rename must not
discard: that one key is REFUSED (both entries survive byte-identical) and reported, so
the consumer resolves it by hand. Every other key in the same block still migrates.

For a comma-separated label list the same collision is not a conflict but a duplicate of
one label: the renamed entry is dropped when an earlier entry already names the current
spelling, keeping the first occurrence's position.

IDEMPOTENT. A second run finds nothing superseded and writes an identical file.

VALID-FALSY SAFE. The config is carried through structurally — every key and value the
rules above do not name is written back exactly as read — so a deliberate `false`,
`0` or `""` keeps its meaning and is never coerced onto a default (issue #312).

REPORT PROTOCOL (stdout, tab-separated; the caller renders each record as a log line):
  CHANGED\t<detail>                       one per applied rename
  CONFLICT\t<superseded key>\t<current key>  one per refused both-present key
  NOTE\t<line>                            one per arm skipped for want of its inputs
  ADVISORY\t<line>                        the residual notice, already rendered

EXIT CODES
  0  a usable result was written to <out> (which may be byte-identical to the input)
  2  input failure — the config or the rename map could not be read or is not an
     object. Nothing is written; a breadcrumb goes to stderr. The caller treats this
     as "could not migrate" and continues: this pass is best-effort and never blocks a
     scaffold.
"""

from __future__ import annotations

import json
import sys

try:  # `lib/` is sys.path[0] when this file is invoked by path, as the scaffolder does.
    import plugin_identity
except ImportError:  # pragma: no cover - a partial deployment; handled at the call site
    plugin_identity = None  # type: ignore[assignment]


class InputError(Exception):
    """The config or the rename map could not be read. Routed to exit 2."""


def _load_json_object(path: str, label: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as exc:
        raise InputError(f"{label} could not be read: {exc}") from exc
    except ValueError as exc:
        raise InputError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise InputError(f"{label} is not a JSON object")
    return data


def _identifier(renames: dict, ident_id: str) -> tuple[str, str] | None:
    """The (superseded, current) pair the rename map records under `ident_id`.

    Read from the map rather than carried as a literal: `lib/rename-map.json` is the
    single source for the rename, and a second copy here is exactly the drift this
    repository's coupled-invariant discipline exists to prevent. An absent or malformed
    row disables that one rule rather than guessing at it.
    """
    rows = renames.get("identifiers")
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict) or row.get("id") != ident_id:
            continue
        old, new = row.get("superseded"), row.get("current")
        if isinstance(old, str) and old and isinstance(new, str) and new:
            return old, new
        return None
    return None


def _superseded_top_level(renames: dict) -> dict[str, str]:
    """current top-level block name -> its superseded spelling, from `config_keys`."""
    keys = renames.get("config_keys")
    if not isinstance(keys, dict):
        return {}
    return {
        new: old
        for old, new in keys.items()
        if isinstance(old, str) and isinstance(new, str)
    }


def _block(cfg: dict, canonical: str, supers: dict[str, str]) -> dict | None:
    """The `canonical` top-level block, or its superseded twin, when it is an object.

    Both spellings are probed because the top-level key migration is separately gated
    (a stale shipped workflow refuses it), so this pass must work on a config whose
    blocks are still keyed under the superseded names. Every access is type-guarded: a
    scalar, an array, or an absent block contributes nothing and never raises.
    """
    for key in (canonical, supers.get(canonical, "")):
        if key:
            value = cfg.get(key)
            if isinstance(value, dict):
                return value
    return None


def _agent_namespaces() -> tuple[tuple[str, str] | None, str]:
    """((superseded, canonical) namespace prefixes, "") — or (None, why it is unavailable).

    `lib/plugin-identity.json` (through `lib/plugin_identity.py`) is the single source
    for the accepted namespace set, canonical first. When it cannot be resolved — a
    partial deployment, an unreadable manifest — this arm is SKIPPED rather than guessed:
    a `devflow:`-spelled override key still resolves, so leaving it is the safe side.

    The skip is NOT silent. It reaches the consumer as a `NOTE` record, because a run that
    renamed the marker and the labels and quietly left the override keys alone reads as a
    migration that half-worked with no reason given.
    """
    if plugin_identity is None:
        return None, "the plugin identity reader (lib/plugin_identity.py) is not importable"
    try:
        namespaces = plugin_identity.agent_namespaces()
    except Exception as exc:  # IdentityError, or any read failure under it
        return None, str(exc)
    if not isinstance(namespaces, list) or len(namespaces) < 2:
        return None, "the accepted namespace set does not carry a superseded spelling"
    canonical, superseded = namespaces[0], namespaces[1]
    if not (isinstance(canonical, str) and canonical and isinstance(superseded, str) and superseded):
        return None, "the accepted namespace set is not a pair of non-empty strings"
    return (superseded, canonical), ""


def migrate_workpad_marker(cfg: dict, renames: dict, supers: dict[str, str]) -> list[str]:
    """Rewrite a superseded-namespace `workpad_marker` value in place."""
    pair = _identifier(renames, "comment-marker-namespace")
    block = _block(cfg, "prflow", supers)
    if pair is None or block is None:
        return []
    old_prefix, new_prefix = pair
    marker = block.get("workpad_marker")
    # A prefix rule, per the map's own `match` for this identifier: the marker namespace
    # always opens with the HTML comment token, and a prefix test cannot reach the bare
    # `devflow:` namespace the override keys and command spellings keep as an alias.
    if not isinstance(marker, str) or not marker.startswith(old_prefix):
        return []
    block["workpad_marker"] = new_prefix + marker[len(old_prefix):]
    return [f"workpad_marker -> {block['workpad_marker']}"]


def migrate_agent_override_keys(
    cfg: dict, supers: dict[str, str], example: dict
) -> tuple[list[str], list[tuple[str, str]], list[str]]:
    """Rename `devflow:<leaf>` override keys to `prflow:<leaf>`, in place and in order.

    Returns (changed, conflicts, notes) — `notes` carrying the one line that discloses a
    skipped arm, so a partial deployment never produces a silently partial migration.
    """
    namespaces, why = _agent_namespaces()
    block = _block(cfg, "prflow_review", supers)
    if block is None:
        return [], [], []
    overrides = block.get("agent_overrides")
    if not isinstance(overrides, dict):
        return [], [], []
    if namespaces is None:
        return [], [], [
            "NOTE: the `agent_overrides` keys were left as they are — the accepted subagent"
            f" namespaces could not be resolved ({why}), and this migration will not guess at"
            " them. Nothing is broken: a key under the superseded namespace still resolves."
            " Re-run after repairing the plugin install to complete the rename."
        ]
    old_ns, new_ns = namespaces

    example_block = _block(example, "prflow_review", supers) or {}
    example_overrides = example_block.get("agent_overrides")
    if not isinstance(example_overrides, dict):
        example_overrides = {}

    def current_spelling(key) -> str | None:
        if isinstance(key, str) and key.startswith(old_ns):
            return new_ns + key[len(old_ns):]
        return None

    def was_grafted(new_key: str) -> bool:
        """The current-spelled entry still holds the shipped example default, so the
        scaffolder's deep merge grafted it rather than the consumer authoring it."""
        return new_key in example_overrides and overrides[new_key] == example_overrides[new_key]

    changed: list[str] = []
    conflicts: list[tuple[str, str]] = []
    # Rebuilt rather than mutated while iterating, so each entry keeps its position and
    # the consumer diff reads as a rename rather than a reshuffle.
    out: dict = {}
    for key, value in overrides.items():
        new_key = current_spelling(key)
        if new_key is None:
            out[key] = value
            continue
        if new_key not in overrides:
            out[new_key] = value
            changed.append(f"agent_overrides key {key} -> {new_key}")
            continue
        if was_grafted(new_key):
            changed.append(
                f"agent_overrides key {key} -> {new_key}"
                f" (the existing {new_key} entry still held the shipped example default"
                " and was replaced)"
            )
            continue  # dropped here; the value is written at new_key's own position below
        conflicts.append((key, new_key))
        out[key] = value
    # Second pass for the grafted case: the consumer's superseded value wins, written at
    # the position the current key already occupies.
    for key, value in overrides.items():
        new_key = current_spelling(key)
        if new_key is not None and new_key in overrides and was_grafted(new_key):
            out[new_key] = value

    block["agent_overrides"] = out
    return changed, conflicts, []


def migrate_label_values(cfg: dict, renames: dict) -> list[str]:
    """Rename the provenance label inside the comma-separated label list values.

    Entry-wise, never substring: a labels value is a LIST OF LABEL NAMES, so the entry is
    the unit that can be a label. `DevFlow-legacy`, or a label that merely contains the
    word, is a different label and is left alone — the map records this identifier as a
    `token` match for exactly that reason, and whole-entry equality is its strictest
    application. Surrounding whitespace is preserved, because the readers trim entries.
    """
    pair = _identifier(renames, "provenance-label")
    if pair is None:
        return []
    old, new = pair
    changed: list[str] = []
    for block_name in ("docs", "deferred"):
        block = cfg.get(block_name)
        if not isinstance(block, dict):
            continue
        value = block.get("labels")
        if not isinstance(value, str) or old not in value:
            continue
        entries = value.split(",")
        originals = [e.strip() for e in entries]
        kept: list[str] = []
        emitted: set[str] = set()
        touched = False
        for index, entry in enumerate(entries):
            if originals[index] != old:
                kept.append(entry)
                emitted.add(originals[index])
                continue
            touched = True
            # A collision here is the SAME label twice, not a conflicting edit — so the
            # rename never introduces a duplicate. Tested against the WHOLE original list,
            # not just the entries already emitted, so a current-spelled entry sitting
            # AFTER the superseded one collapses it exactly like one sitting before.
            if new in originals or new in emitted:
                continue
            kept.append(entry.replace(old, new, 1))
            emitted.add(new)
        if not touched:
            continue
        block["labels"] = ",".join(kept)
        changed.append(f"{block_name}.labels -> {block['labels']}")
    return changed


def residual_advisory(cfg: dict, renames: dict) -> list[str]:
    """The notice for what deliberately REMAINS after the migration.

    Derived, never static: only the frozen keys this consumer's config actually carries
    are named, and a config carrying none draws no notice at all (the scaffolder's ethos
    of staying silent when nothing is actionable). The frozen set is read from the rename
    map, so this cannot drift from the freeze itself.
    """
    # Every hop is type-guarded: this helper is best-effort over files a partial or
    # hand-edited deployment can corrupt, and an uncaught traceback here would land AFTER
    # the migrated file is written but before the caller is told to swap it in — silently
    # discarding a migration it just reported, under a misleading "could not read" line.
    frozen_block = renames.get("frozen")
    frozen = frozen_block.get("config_keys") if isinstance(frozen_block, dict) else None
    if not isinstance(frozen, list):
        return []
    present = [p for p in frozen if isinstance(p, str) and p and _path_exists(cfg, p)]
    if not present:
        return []
    return [
        "NOTICE: these `devflow`-spelled config keys are kept ON PURPOSE and were not renamed — "
        + ", ".join(f"`{p}`" for p in present)
        + ". Your workflow files read those key names, so renaming one here would read as"
        " `disabled` and silently switch the workflow it toggles off; they move only in a"
        " change that migrates both sides together. Leave them as they are.",
        "NOTICE: the `DEVFLOW_*` ENVIRONMENT identifiers (GitHub variables and secrets, and"
        " shell overrides) are frozen too and must never be hand-renamed — nothing reads a"
        " `PRFLOW_*` equivalent, so renaming one removes the setting rather than moving it."
        " That is a separate inventory this notice does not restate:"
        " `lib/generate-env-freeze-advisory.py` renders it.",
    ]


def _path_exists(cfg: dict, path: str) -> bool:
    """Whether a dotted path resolves, including onto a valid-falsy value.

    A `false` / `0` / `""` value is PRESENT. Testing presence by truthiness is the
    documented off-switch-that-never-worked bug (issue #312), so presence is decided by
    key membership and never by the value.
    """
    node = cfg
    for segment in path.split("."):
        if not isinstance(node, dict) or segment not in node:
            return False
        node = node[segment]
    return True


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8 on the CLI entry path only (not at import, so a
    unit-test import never mutates the importer's streams). A no-op where the ambient
    codec is already UTF-8; self-defends against a non-UTF-8 default codec such as
    Windows cp1252. Tolerates a non-TextIOWrapper stream (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv=None) -> int:
    _force_utf8_streams()
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 3:
        sys.stderr.write(
            "usage: migrate-config-values.py <config> <out> <rename-map> [<config.example.json>]\n"
        )
        return 2
    cfg_path, out_path, map_path = argv[0], argv[1], argv[2]
    example_path = argv[3] if len(argv) > 3 else ""

    try:
        cfg = _load_json_object(cfg_path, "the config")
        renames = _load_json_object(map_path, "the rename map")
    except InputError as exc:
        sys.stderr.write(f"migrate-config-values: {exc}\n")
        return 2
    # The example is OPTIONAL and its absence is not an input failure: it is consulted
    # only to tell a grafted default from an authored edit, and without it every
    # both-present key is REFUSED — the conservative side of that decision.
    example: dict = {}
    if example_path:
        try:
            example = _load_json_object(example_path, "the shipped example config")
        except InputError as exc:
            sys.stderr.write(f"migrate-config-values: {exc}; refusing every both-present key\n")

    supers = _superseded_top_level(renames)
    changed = migrate_workpad_marker(cfg, renames, supers)
    override_changed, conflicts, notes = migrate_agent_override_keys(cfg, supers, example)
    changed.extend(override_changed)
    changed.extend(migrate_label_values(cfg, renames))

    try:
        with open(out_path, "w", encoding="utf-8") as fh:
            # ensure_ascii=False so an em-dash or any other non-ASCII character a consumer
            # wrote into a description survives as itself; escaping it would turn a
            # one-value change into a whole-file diff.
            json.dump(cfg, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    except OSError as exc:
        sys.stderr.write(f"migrate-config-values: could not write {out_path}: {exc}\n")
        return 2

    for detail in changed:
        sys.stdout.write("CHANGED\t" + detail + "\n")
    for old_key, new_key in conflicts:
        sys.stdout.write("CONFLICT\t" + old_key + "\t" + new_key + "\n")
    for line in notes:
        sys.stdout.write("NOTE\t" + line + "\n")
    for line in residual_advisory(cfg, renames):
        sys.stdout.write("ADVISORY\t" + line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
