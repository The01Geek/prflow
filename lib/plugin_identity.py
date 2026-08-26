#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""plugin_identity.py -- the SINGLE reader for PRFlow's accepted plugin identifiers.

Several PRFlow surfaces have to answer "is this identifier ours?":

  * the vendor trust ladder (`.github/actions/vendor-plugin/vendor-slice.sh`'s
    `self` branch, and five FETCH_HEAD-gated trusted-source arms in
    `.github/workflows/devflow-runner.yml`) -- SECURITY boundaries: a wrong
    answer here silently executes, or silently declines to execute, trusted
    helper code;
  * `install.sh`'s legacy prune (does this stale tree belong to us?);
  * `scripts/resolve-extra-plugins.sh`'s baked-baseline skip sets;
  * `scripts/resolve-review-overrides.py`'s closed `agent_overrides` allowlist;
  * `scripts/provision-local-settings.sh`'s local marketplace registration.

Historically each of those hardcoded the plugin name as a literal. This module
makes them derive the accepted set instead, so the set is declared once and the
discriminators carry no hand-maintained identifier.

Sources, in one place:

  canonical plugin name       .claude-plugin/plugin.json -> "name"
  additional accepted names   lib/plugin-identity.json   -> "plugin_aliases"
  canonical marketplace name  lib/plugin-identity.json   -> "marketplace_canonical"
  additional marketplaces     lib/plugin-identity.json   -> "marketplace_aliases"

The canonical plugin name deliberately stays in the manifest (it is the value
Claude Code itself reads, and the project freeze list pins it). The canonical
MARKETPLACE name cannot come from `.claude-plugin/marketplace.json`, because
`devflow_copy_slice` removes that file from the vendored plugin slice, so a
consumer-tree run could not read it; `lib/test/run.sh` gates the value stored
here against the real marketplace manifest instead.

Root resolution is `__file__`-relative (this file sits in `<root>/lib/`), which
resolves identically in the source repo and in a vendored
`.prflow/vendor/prflow/` tree. It is NOT `git rev-parse`-anchored: a vendored
tree is not its own git root.

FAIL-CLOSED: every accessor raises `IdentityError` rather than substituting a
default. A discriminator that cannot establish its accepted set must decline,
never guess -- callers translate that into their own documented degraded arm.

CLI (for shell callers; one identifier per line unless noted):
  --plugin-names            accepted plugin names (canonical first)
  --marketplace-names       accepted marketplace names (canonical first)
  --plugin-specs            accepted "<plugin>@<marketplace>" specs
  --canonical-plugin-spec   the one canonical "<plugin>@<marketplace>" spec
  --agent-namespaces        accepted "<plugin>:" subagent-id namespaces
  --plugin-name-ere         the ERE the baked discriminators match plugin.json with
  --json                    the whole resolved identity as a JSON object
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

IDENTITY_FILE = "lib/plugin-identity.json"
MANIFEST_FILE = ".claude-plugin/plugin.json"

# The ERE shape the baked discriminators use to recognize a plugin manifest.
# Kept here so the generator and the tests never re-spell it independently.
ERE_PREFIX = '"name"[[:space:]]*:[[:space:]]*"('
ERE_SUFFIX = ')"'


class IdentityError(RuntimeError):
    """The accepted-identifier set could not be established."""


def default_root() -> Path:
    """The plugin root: the parent of the directory holding this file."""
    return Path(__file__).resolve().parent.parent


def _load_json(path: Path, label: str):
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError as exc:
        raise IdentityError(f"{label} is missing at {path}") from exc
    except json.JSONDecodeError as exc:
        raise IdentityError(f"{label} at {path} is not valid JSON ({exc})") from exc
    except OSError as exc:
        raise IdentityError(f"{label} at {path} could not be read ({exc})") from exc


def _require_nonempty_str(value, label: str) -> str:
    if not isinstance(value, str) or value == "":
        raise IdentityError(f"{label} is missing, empty, or not a string")
    return value


def _require_positive_int(value, label: str) -> int:
    """`identity_version` stamps every generated banner, so an absent or
    non-integer value would bake a literal `identity_version=None` that the
    reading regex happily matches -- fail closed like every other field rather
    than passing an unvalidated value through. `bool` is an `int` subclass in
    Python and is rejected explicitly."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise IdentityError(f"{label} is missing or not a positive integer")
    return value


def require_identifier_shape(name: str, label: str) -> str:
    """The one owner of the accepted-identifier CHARACTER contract.

    Both downstream bakings constrain identifiers the same way: the plugin-name
    ERE embeds them unescaped in an alternation, and the space-separated baked
    lists cannot carry whitespace or quoting. Re-deriving that predicate per
    consumer is how the accepted sets drift apart, so every caller shares this
    one."""
    if not isinstance(name, str) or name == "":
        raise IdentityError(f"{label} is empty or not a string")
    for ch in name:
        if not (ch.isascii() and (ch.isalnum() or ch in "-_")):
            raise IdentityError(
                f"{label} {name!r} carries a character outside [A-Za-z0-9_-]; it "
                "cannot be embedded in the discriminator ERE or a baked identifier list"
            )
    return name


def _alias_list(value, label: str) -> list[str]:
    """An alias list must be a list of non-empty strings. Absent is NOT accepted:
    the key is mandatory (empty list) so a typo/dropped key fails closed instead
    of silently narrowing the accepted set back to canonical-only."""
    if not isinstance(value, list):
        raise IdentityError(f"{label} is missing or not an array")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or item == "":
            raise IdentityError(f"{label} contains a non-string or empty entry")
        if item not in out:
            out.append(item)
    return out


def load(root: Path | None = None) -> dict:
    """Resolve the full identity. Raises IdentityError on any defect.

    Deferred (PR #943 review, Suggestion 6): typing this return as a `TypedDict`
    would make the key set checkable at zero runtime cost. Not taken here —
    every consumer reads it through the named accessors or the `--json` CLI, so
    the shape is already gated by `lib/test/run.sh`'s #927 G-block; revisit if a
    caller ever indexes it directly."""
    base = Path(root) if root is not None else default_root()
    manifest = _load_json(base / MANIFEST_FILE, "the plugin manifest")
    if not isinstance(manifest, dict):
        raise IdentityError(f"the plugin manifest at {base / MANIFEST_FILE} is not an object")
    identity = _load_json(base / IDENTITY_FILE, "the plugin identity file")
    if not isinstance(identity, dict):
        raise IdentityError(f"the plugin identity file at {base / IDENTITY_FILE} is not an object")

    plugin_canonical = _require_nonempty_str(manifest.get("name"), "the plugin manifest `name`")
    plugin_aliases = _alias_list(identity.get("plugin_aliases"), "plugin_aliases")
    market_canonical = _require_nonempty_str(
        identity.get("marketplace_canonical"), "marketplace_canonical"
    )
    market_aliases = _alias_list(identity.get("marketplace_aliases"), "marketplace_aliases")

    if plugin_canonical in plugin_aliases:
        raise IdentityError("plugin_aliases repeats the canonical plugin name")
    if market_canonical in market_aliases:
        raise IdentityError("marketplace_aliases repeats the canonical marketplace name")

    plugin_names = [plugin_canonical, *plugin_aliases]
    market_names = [market_canonical, *market_aliases]
    # Marketplace names are held to the SAME character contract as plugin names.
    # Plugin names are checked inside `plugin_name_ere` below; without this the
    # reader would accept a marketplace name only the generator later refuses,
    # so the two would disagree about what the accepted set is.
    for _m in market_names:
        require_identifier_shape(_m, "accepted marketplace name")
    return {
        "identity_version": _require_positive_int(
            identity.get("identity_version"), "identity_version"
        ),
        "plugin_canonical": plugin_canonical,
        "plugin_names": plugin_names,
        "marketplace_canonical": market_canonical,
        "marketplace_names": market_names,
        "canonical_plugin_spec": f"{plugin_canonical}@{market_canonical}",
        "plugin_specs": [f"{p}@{m}" for p in plugin_names for m in market_names],
        "agent_namespaces": [f"{p}:" for p in plugin_names],
        "plugin_name_ere": plugin_name_ere(plugin_names),
    }


def plugin_name_ere(names) -> str:
    """The ERE a baked discriminator greps a plugin.json with.

    Alternation over every accepted name. The names are `[a-z0-9-]`-shaped
    identifiers, so no ERE metacharacter escaping is required; a name carrying
    one is rejected rather than silently mis-anchored.
    """
    ordered: list[str] = []
    for name in names:
        require_identifier_shape(name, "accepted plugin name")
        if name not in ordered:
            ordered.append(name)
    return ERE_PREFIX + "|".join(ordered) + ERE_SUFFIX


def accepted_plugin_names(root: Path | None = None) -> list[str]:
    return load(root)["plugin_names"]


def accepted_marketplace_names(root: Path | None = None) -> list[str]:
    return load(root)["marketplace_names"]


def accepted_plugin_specs(root: Path | None = None) -> list[str]:
    return load(root)["plugin_specs"]


def agent_namespaces(root: Path | None = None) -> list[str]:
    return load(root)["agent_namespaces"]


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def _main(argv=None) -> int:
    _force_utf8_streams()
    ap = argparse.ArgumentParser(description="Report PRFlow's accepted plugin identifiers.")
    ap.add_argument("--root", default=None, help="plugin root (default: this file's parent's parent)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plugin-names", action="store_true")
    g.add_argument("--marketplace-names", action="store_true")
    g.add_argument("--plugin-specs", action="store_true")
    g.add_argument("--canonical-plugin-spec", action="store_true")
    g.add_argument("--agent-namespaces", action="store_true")
    g.add_argument("--plugin-name-ere", action="store_true")
    g.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        ident = load(args.root)
    except IdentityError as exc:
        print(f"plugin-identity: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(ident, indent=2, sort_keys=True))
        return 0
    if args.canonical_plugin_spec:
        print(ident["canonical_plugin_spec"])
        return 0
    if args.plugin_name_ere:
        print(ident["plugin_name_ere"])
        return 0
    key = (
        "plugin_names" if args.plugin_names
        else "marketplace_names" if args.marketplace_names
        else "plugin_specs" if args.plugin_specs
        else "agent_namespaces"
    )
    for item in ident[key]:
        print(item)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
