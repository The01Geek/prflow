#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Single source of PRFlow's telemetry master-switch predicate (issue #2035).

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
The three consumers — config-get.sh's enrolled-sub-key miss path,
lib/efficiency-trace.sh --persist, and scripts/collect-staged-telemetry.sh —
invoke this and branch on the exit code. Never raises: every error path exits 1.
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


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        return 1
    return 0 if telemetry_master_off(argv[1]) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
