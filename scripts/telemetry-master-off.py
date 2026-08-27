#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""PRFlow's telemetry master-switch predicate, as a standalone script (issue #2035).

`scripts/collect-staged-telemetry.sh` is the caller that execs this file.
`scripts/config-get.sh` and `lib/efficiency-trace.sh` carry inline `python3 -c`
copies of the same JSON-type test instead of exec-ing it — equivalent in what
they decide, differing only in the env var each passes the config path through
(`PRFLOW_TEL_CFG` and `DEVFLOW_TEL_CFG` respectively). Both are hardened
Stop-hook closure members, where a new source/exec edge would break the
issue-#458 drift guard. Change the decision here, change it in all three.

Exit 0 (telemetry OFF) ONLY when ``telemetry.enabled`` is the JSON boolean
``false`` in the config file named by argv[1]. Exit 1 (telemetry ON /
indeterminate) for every other state — the key absent, ``telemetry`` not an
object, ``enabled`` a string ("false"), a number (0), null, or any other type,
an unreadable/corrupt config, or a bad/missing argument. Telemetry therefore
FAILS SAFE to ON in every failure direction, matching the fail-safe direction
the existing per-key gates already use.

Reading the JSON TYPE here is load-bearing: config-get.sh's coerce() renders the
JSON boolean ``false`` and the string ``"false"`` onto identical stdout
("false"), so a caller comparing that coerced string could not tell them apart.
"""
import json
import sys


def telemetry_master_off(config_path: str) -> bool:
    try:
        with open(config_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    tel = data.get("telemetry")
    if not isinstance(tel, dict):
        return False
    # `is False`, never `== False`: in Python the number 0 equals False, so an
    # `== False` test would wrongly disable telemetry for the JSON number 0.
    return tel.get("enabled") is False


def _force_utf8_streams() -> None:
    # Force stdout/stderr to UTF-8 on the CLI entry path (not at import), so every
    # first-party command self-defends against a non-UTF-8 ambient codec (issue #1762).
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: list[str]) -> int:
    _force_utf8_streams()
    if len(argv) != 2:
        return 1
    return 0 if telemetry_master_off(argv[1]) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
