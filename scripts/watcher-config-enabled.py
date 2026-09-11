#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""watcher-config-enabled.py — type-preserving on-switch for the Spot-interruption
watcher (issue #261) and, via ``--key``, for any other strict-boolean opt-in.

Prints exactly ``true`` and exits 0 ONLY when
``prflow_implement.spot_interruption_watcher.enabled`` — or the dotted key named
by ``--key a.b.c`` (issue #305: ``prflow_implement.stall_backstop.defer_to_runner_retry``)
— is the JSON boolean ``true``. Every other shape — a JSON string ``"true"``, a number ``1``, ``null``,
an object, an array, the JSON boolean ``false``, an absent key/object, or an
unreadable/malformed config — prints ``false`` and exits 0 (fail-closed: the
watcher is opt-in and Linux/EC2-only, so an ambiguous config leaves it off, and a
malformed config never fails the workflow step that reads this gate).

This deliberately does NOT go through config-get.sh: its Python coercion folds a
JSON boolean ``true`` and a JSON string ``"true"`` to the same output string
``true`` (booleans -> lowercase true/false; everything else -> str(v)), so a
config-get read cannot distinguish them. The predicate here reads the raw JSON in
Python and tests ``value is True`` (the mirror-image on-switch of workpad.py's
``_status_labels_enabled`` off-switch), which the AC requires.

SHARED REPO-ROOT CONFIG CONTRACT (issue #295): the default config path is
``<git-repo-root>/.prflow/config.json`` (``git rev-parse --show-toplevel``,
falling back to the cwd), with ``.devflow/`` read through only when ``.prflow/`` is
absent. A non-empty ``--config`` argument is honored verbatim.
"""
import json
import subprocess
import sys
from pathlib import Path

try:
    # Reuse the shared .prflow/->.devflow/ resolution contract (lib/state_dir.py) —
    # the same import shim workpad.py uses — so this reader breadcrumbs /prflow:init
    # on a superseded-directory read-through exactly like every other Python reader,
    # rather than hand-rolling a divergent fallback. Degrades to .prflow/ if the
    # module cannot be imported (a partial vendored copy).
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
    from state_dir import state_config_path as _state_config_path
except Exception:  # pragma: no cover - partial-copy / exec'd-source arm
    def _state_config_path(repo_root, filename="config.json", stream=None):
        return str(Path(repo_root) / ".prflow" / filename)


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8 (issue #1762). Never called at import — only on the
    entry path — so importing this module for tests leaves the streams unchanged.
    Tolerates a stream with no usable `reconfigure`."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def _repo_root():
    try:
        r = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    root = r.stdout.strip()
    return root or None


def _default_config_path():
    base = _repo_root() or str(Path.cwd())
    return Path(_state_config_path(base))


DEFAULT_KEY = 'prflow_implement.spot_interruption_watcher.enabled'


def _enabled(config_path, key=DEFAULT_KEY):
    """Return (True, None) only when ``key`` is the JSON boolean true; else (False, reason)."""
    try:
        with config_path.open(encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return False, f'config file not found: {config_path}'
    except (OSError, ValueError) as exc:
        return False, f'config file unreadable/malformed ({config_path}): {exc}'
    if not isinstance(data, dict):
        return False, 'config root is not a JSON object'
    parts = key.split('.')
    node = data
    for name in parts[:-1]:
        node = node.get(name) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            return False, f'{".".join(parts[:-1])} object absent'
    if parts[-1] not in node:
        return False, f'{key} key absent'
    value = node[parts[-1]]
    # `value is True` matches ONLY the JSON boolean true — never the string
    # "true", never the number 1 (1 == True but `1 is True` is False), never any
    # other shape. That exact-identity test is the whole point of this gate.
    if value is True:
        return True, None
    return False, f'{key}: expected JSON boolean true, found {type(value).__name__}'


def main(argv):
    _force_utf8_streams()
    config_path = None
    key = DEFAULT_KEY
    i = 0
    while i < len(argv):
        if argv[i] == '--config' and i + 1 < len(argv) and argv[i + 1].strip():
            config_path = Path(argv[i + 1])
            i += 2
            continue
        if argv[i] == '--key' and i + 1 < len(argv) and argv[i + 1].strip():
            key = argv[i + 1].strip()
            i += 2
            continue
        i += 1
    if config_path is None:
        config_path = _default_config_path()
    ok, reason = _enabled(config_path, key)
    if ok:
        print('true')
    else:
        print('false')
        tail = ' — watcher not started' if key == DEFAULT_KEY else ''
        print(f'{key.rsplit(".", 1)[0].rsplit(".", 1)[-1]} not enabled: {reason}{tail}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
