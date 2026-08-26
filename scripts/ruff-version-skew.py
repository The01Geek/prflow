#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Decide whether a reported ruff version skews from the manifest-pinned family (issue #2009).

The whole-suite coordinator's cheap-lint pre-launch gate (`lib/test/run-parallel.sh`)
uses this to refuse a launch when the `ruff` on PATH positively reports a version whose
minor family differs from the family pinned in `.prflow/lint-manifest.json` — the skew
that makes the in-suite `#1621` ruff gate go RED on rule-set drift rather than on real
findings. The expected version is read from the manifest at run time, so the caller keeps
no second copy of it.

Verdict (exit code):
  0  the reported minor family matches the pinned family — no skew.
  1  a positively-attributed skew — the families differ. The actionable message, with a
     manifest-derived `pip install 'ruff==<family>.*'` remedy, is printed to STDOUT.
  2  inconclusive — the manifest could not be read (missing/malformed/wrong shape) or the
     reported version could not be parsed. The caller FAILS OPEN (proceeds) on this, so
     an absent, non-executing, or unreadable comparand never turns into a refusal.

Fail-closed to 2 (never 0) on any manifest read problem: an unusable comparand is unknown,
not "matches". Unknown is not zero.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

# First `major.minor` in a version-ish string ("ruff 0.16.4" -> "0.16", "0.16.*" -> "0.16").
_FAMILY_RE = re.compile(r"([0-9]+)\.([0-9]+)")


def minor_family(text: str | None) -> str | None:
    """The `major.minor` family of the first version token in `text`, or None."""
    if not text:
        return None
    m = _FAMILY_RE.search(text)
    return f"{m.group(1)}.{m.group(2)}" if m else None


def manifest_ruff_family(path: str) -> str | None:
    """The pinned ruff version's minor family, or None when the manifest cannot be read as
    a mapping carrying a string `tools.ruff.version`. Every failure shape — missing file,
    non-JSON bytes, a top-level array/scalar, a non-object `tools`/`ruff`, a missing or
    non-string `version`, an empty or unparseable version — resolves to None (inconclusive),
    never to a spurious family."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    tools = data.get("tools")
    if not isinstance(tools, dict):
        return None
    ruff = tools.get("ruff")
    if not isinstance(ruff, dict):
        return None
    version = ruff.get("version")
    if not isinstance(version, str):
        return None
    return minor_family(version)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ruff version-skew verdict (issue #2009)")
    ap.add_argument("--manifest", required=True, help="path to .prflow/lint-manifest.json")
    ap.add_argument("--reported", required=True,
                    help="the observed `ruff --version` output, e.g. 'ruff 0.16.4'")
    args = ap.parse_args(argv)

    expected = manifest_ruff_family(args.manifest)
    reported = minor_family(args.reported)
    if expected is None or reported is None:
        print("ruff-version-skew: inconclusive — the lint manifest could not be read or the "
              "reported ruff version could not be parsed; proceeding", file=sys.stderr)
        return 2
    if expected == reported:
        return 0
    print(
        f"ruff-version-skew: the ruff on PATH reports the {reported} family but the lint "
        f"manifest pins the {expected} family; fix: "
        f"python3 -m pip install --user --force-reinstall 'ruff=={expected}.*'"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
