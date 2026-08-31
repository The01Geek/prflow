#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""generate-plugin-identity.py -- compile the accepted-identifier set into the
surfaces that CANNOT read it at runtime.

Most PRFlow consumers of the accepted plugin-identifier set read
`lib/plugin_identity.py` live (see that module's header). The `REGIONS` table
below is the authoritative list of the ones that cannot; the notes here say why
each of them cannot -- each for a structural reason, not for convenience:

  .github/actions/vendor-plugin/vendor-slice.sh
      Its `self` branch asks "is the CHECKOUT ROOT the PRFlow plugin?". The only
      identity file reachable there belongs to the tree under examination, so
      reading it would make every tree self-certify. The accepted set must arrive
      with the checker.

  .github/workflows/devflow-runner.yml
      Five FETCH_HEAD-gated arms ask "is the BASE REF the PRFlow plugin repo?"
      before materializing trusted helper code (the deny-list floor, the git-env
      helpers, the compose helpers, the trusted prompt-extension materializer,
      the Stop-hook hardener). Same circularity, with a security boundary
      attached: an accepted set read out of the examined tree would let that tree
      nominate itself as trusted. The value is injected as a workflow-level
      `env:` entry, which is part of the workflow file itself and therefore
      carries exactly the trust the inline literal it replaces carried.

  install.sh
      Runs curl-piped with no repository, and inspects a FOREIGN stale tree. Its
      region carries more than the discriminator ERE: the installer also WRITES the
      canonical identifiers (into the local marketplace manifest) and REPORTS the
      superseded ones it finds in a consumer's Claude Code settings, so the whole
      identifier set has to arrive with the installer.

  scripts/resolve-extra-plugins.sh
      The review tier materializes this helper from the trusted base ref as a
      LONE FILE in a flat `$RUNNER_TEMP` directory (never as part of a plugin
      tree), so it has no sibling `lib/` to read and must carry its own sets.
      Not a security boundary — it is the compose skip set — but the deployment
      shape is the same, so the same mechanism applies.

So each `REGIONS` entry carries a GENERATED region, banner-stamped with the identity
version and a sha256 of the payload. `--check` (wired into lib/test/run.sh)
turns any drift between `lib/plugin-identity.json` + the manifest and the baked
regions RED with a directional diff, so the regions are never hand-edited.

Usage:
  python3 lib/generate-plugin-identity.py            # rewrite the regions
  python3 lib/generate-plugin-identity.py --check    # verify, exit 1 on drift
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plugin_identity

ROOT = Path(__file__).resolve().parent.parent
GENERATOR = "lib/generate-plugin-identity.py"

BEGIN_RE_TMPL = (
    r"^(?P<indent>[ \t]*)# devflow-plugin-identity:begin "
    r"identity_version=(?P<ver>[^ ]+) sha256=(?P<sha>[0-9a-f]{64})"
    r"(?: .*)?$"
)
END_TEXT = "# devflow-plugin-identity:end"


def payload_sh(ident: dict) -> list[str]:
    """Shell: a plain assignment (never `${VAR:-...}` -- an inherited environment
    value must not be able to widen or narrow a trust discriminator)."""
    return [f"DEVFLOW_PLUGIN_NAME_ERE='{ident['plugin_name_ere']}'"]


def payload_yaml_env(ident: dict) -> list[str]:
    """YAML: one workflow-level `env:` entry. The ERE contains `"` but no `'`,
    so a single-quoted YAML scalar needs no escaping; assert that rather than
    emitting something subtly wrong."""
    ere = ident["plugin_name_ere"]
    if "'" in ere:
        raise SystemExit("plugin-identity: the discriminator ERE contains a single quote")
    return [f"DEVFLOW_PLUGIN_NAME_ERE: '{ere}'"]


def payload_install(ident: dict) -> list[str]:
    """Shell: the discriminator ERE plus the CANONICAL identifiers the installer
    writes and the SUPERSEDED ones it migrates away from.

    `install.sh` composes the local marketplace manifest and reports a consumer's
    stale registrations, so it needs the identifiers themselves, not only the
    match ERE. Superseded = every accepted identifier that is not the canonical
    one, which is exactly what a declared alias means: a name a previous install
    may have written that this one must stop writing. Non-empty exactly when an
    alias is declared — a property of whatever `lib/plugin-identity.json` carries,
    never a fixed fact about this function. With the manifest's alias lists empty,
    as they are in the tree that ships this docstring, the baked
    `DEVFLOW_SUPERSEDED_PLUGIN_SPECS` is empty and
    `devflow_report_superseded_identifiers`'s non-empty gate short-circuits, so
    the migration report is a strict no-op; declare one alias and the gate passes
    and the scan of `.claude/settings.json` runs. Read the manifest before
    asserting which of the two holds — the #958 dual-accept probe declared an
    alias for one release and this claim inverted with it.

    Plain assignments, never `${VAR:-...}` — an inherited environment value must
    not be able to widen or narrow what the installer accepts as its own.
    """
    for group in (ident["plugin_names"], ident["marketplace_names"]):
        for name in group:
            try:
                plugin_identity.require_identifier_shape(name, "accepted identifier")
            except plugin_identity.IdentityError as exc:
                raise SystemExit(f"plugin-identity: {exc}") from exc
    superseded_markets = ident["marketplace_names"][1:]
    superseded_specs = [s for s in ident["plugin_specs"] if s != ident["canonical_plugin_spec"]]
    return [
        f"DEVFLOW_PLUGIN_NAME_ERE='{ident['plugin_name_ere']}'",
        f"DEVFLOW_PLUGIN_CANONICAL='{ident['plugin_canonical']}'",
        f"DEVFLOW_MARKETPLACE_CANONICAL='{ident['marketplace_canonical']}'",
        "DEVFLOW_SUPERSEDED_MARKETPLACES='" + " ".join(superseded_markets) + "'",
        "DEVFLOW_SUPERSEDED_PLUGIN_SPECS='" + " ".join(superseded_specs) + "'",
    ]


def payload_identity_sets(ident: dict) -> list[str]:
    """Shell: the accepted identifier sets as space-separated lists, for a
    helper that hands them to an interpreter rather than to `grep -E`.

    Space-separated (not newline-separated) so each region line stays one line —
    the region reader and writer are line-based, and an embedded newline would
    make a freshly generated region never compare equal to itself."""
    # Delegated to the reader's single owner of the character contract rather
    # than re-derived here: a second predicate approximating the same rule is
    # exactly how a baked set drifts wider than what the reader accepts.
    # `load()` already applies it, so this is defense in depth for a caller that
    # hands in a hand-built identity dict.
    for group in (ident["plugin_names"], ident["marketplace_names"]):
        for name in group:
            try:
                plugin_identity.require_identifier_shape(name, "accepted identifier")
            except plugin_identity.IdentityError as exc:
                raise SystemExit(f"plugin-identity: {exc}") from exc
    return [
        "DEVFLOW_PLUGIN_NAMES='" + " ".join(ident["plugin_names"]) + "'",
        "DEVFLOW_MARKETPLACE_NAMES='" + " ".join(ident["marketplace_names"]) + "'",
    ]


REGIONS = [
    {
        "id": "vendor-slice",
        "file": ".github/actions/vendor-plugin/vendor-slice.sh",
        "payload": payload_sh,
    },
    {
        "id": "install",
        "file": "install.sh",
        "payload": payload_install,
    },
    {
        "id": "runner-env",
        "file": ".github/workflows/devflow-runner.yml",
        "payload": payload_yaml_env,
    },
    {
        "id": "resolve-extra-plugins",
        "file": "scripts/resolve-extra-plugins.sh",
        "payload": payload_identity_sets,
    },
]


def region_sha(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def banner(ident: dict, lines: list[str]) -> str:
    return (
        f"# devflow-plugin-identity:begin identity_version={ident['identity_version']} "
        f"sha256={region_sha(lines)} (generated by {GENERATOR} -- do not hand-edit; "
        "source: lib/plugin-identity.json + .claude-plugin/plugin.json)"
    )


def locate(text: str, path: str) -> tuple[int, int, str, str, str]:
    """Return (begin_line_idx, end_line_idx, indent, sha, version) for the region.

    Fails closed: exactly one begin and one matching end are required."""
    lines = text.split("\n")
    begins = [(i, m) for i, line in enumerate(lines) if (m := re.match(BEGIN_RE_TMPL, line))]
    if len(begins) != 1:
        raise SystemExit(
            f"plugin-identity: {path} carries {len(begins)} "
            "`devflow-plugin-identity:begin` banner(s); expected exactly 1"
        )
    bi, m = begins[0]
    indent = m.group("indent")
    ends = [i for i, line in enumerate(lines) if line.strip() == END_TEXT and i > bi]
    if not ends:
        raise SystemExit(f"plugin-identity: {path} has no `{END_TEXT}` after its begin banner")
    return bi, ends[0], indent, m.group("sha"), m.group("ver")


def render(ident: dict, region: dict, indent: str) -> list[str]:
    body = region["payload"](ident)
    return [indent + banner(ident, body)] + [indent + b for b in body] + [indent + END_TEXT]


def run(check: bool) -> int:
    # Guard on lib/test, the one directory absent from BOTH consumer-facing trees: the vendor slice
    # deletes it and the release manifest never ships it, while .github DOES ship in the distribution
    # tree. A region absent under a present lib/test is a broken dev tree that must still raise.
    if not (ROOT / "lib" / "test").is_dir():
        print(
            "generate-plugin-identity.py: lib/test absent — this tool "
            "only applies inside a PRFlow development tree; nothing to do."
        )
        return 0
    try:
        ident = plugin_identity.load(ROOT)
    except plugin_identity.IdentityError as exc:
        print(f"plugin-identity: {exc}", file=sys.stderr)
        return 2

    drift = []
    for region in REGIONS:
        path = ROOT / region["file"]
        text = path.read_text(encoding="utf-8")
        bi, ei, indent, _found_sha, _found_ver = locate(text, region["file"])
        lines = text.split("\n")
        fresh = render(ident, region, indent)
        current = lines[bi : ei + 1]
        if current == fresh:
            continue
        if check:
            drift.append(
                f"  {region['file']} (region {region['id']}):\n"
                + "    expected:\n"
                + "".join(f"      {ln}\n" for ln in fresh)
                + "    found:\n"
                + "".join(f"      {ln}\n" for ln in current)
            )
            continue
        path.write_text("\n".join(lines[:bi] + fresh + lines[ei + 1 :]), encoding="utf-8")
        print(f"plugin-identity: regenerated {region['file']} (region {region['id']})")

    if drift:
        print(
            "plugin-identity: baked identity region(s) differ from "
            "lib/plugin-identity.json + .claude-plugin/plugin.json:\n"
            + "\n".join(drift)
            + f"\n  remedy: python3 {GENERATOR}",
            file=sys.stderr,
        )
        return 1
    if check:
        print("plugin-identity: all baked regions match the identity source.")
    return 0


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None) -> int:
    _force_utf8_streams()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="verify without writing")
    args = ap.parse_args(argv)
    return run(args.check)


if __name__ == "__main__":
    sys.exit(main())
