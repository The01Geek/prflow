#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Render the /prflow:implement draft-PR provenance line on stdout.

The line names the plugin build that executed the run, and — when they can be
established and the consumer has not switched the clause off — the session model
and reasoning effort:

    Generated via /prflow:implement (v2.32.70, claude-opus-5, high)
    Generated via /prflow:implement (v2.32.70)

Three values, three sources, each read soft:

* **version** — ``.version`` of the plugin manifest resolved *beside this helper*
  (``../.claude-plugin/plugin.json``), mirroring ``lib/efficiency-trace.sh``. It is
  the version *actually executing*, never ``prflow_version`` config (the vendor pin)
  or a repository-root manifest a consumer does not even have.
* **effort** — the ``CLAUDE_EFFORT`` environment variable; unestablished when unset,
  empty, or whitespace-only.
* **model** — the most recent ``assistant`` record's ``message.model`` in the session
  transcript. The store is an internal Claude Code format the vendor documents as
  changing between releases, so every read of it fails soft; ``resolvedModel`` (a
  dispatched subagent's model) is never a source.

An unestablished value is omitted rather than guessed, and a stderr breadcrumb names
it and why, so a short line reports its own reason. The line carries no backtick or
other shell-active construct, because its caller substitutes it into a double-quoted
``--body``. The helper always exits 0: an unreadable source shortens the line, it never
fails the caller's fence.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

#: The plugin manifest, resolved relative to THIS file's location (scripts/ -> repo
#: root), mirroring lib/efficiency-trace.sh: the version that is actually executing,
#: not a repository-root manifest a consumer lacks.
_MANIFEST_BESIDE_HELPER = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"

#: The config key (under prflow_implement) that gates the model+effort clause. An
#: explicit JSON ``false`` suppresses the clause; anything else (absent, true, a
#: wrong-typed value) leaves it enabled — the version is emitted whatever it holds.
_CONFIG_SECTION = "prflow_implement"
_CONFIG_KEY = "publish_model_effort"


def _breadcrumb(msg: str) -> None:
    """Emit a provenance breadcrumb on stderr (never stdout)."""
    print(f"render-pr-provenance-line: {msg}", file=sys.stderr)


def read_version() -> str | None:
    """Return the beside-the-helper manifest ``.version`` string, or None + breadcrumb."""
    path = _MANIFEST_BESIDE_HELPER
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        _breadcrumb(f"version unestablished (no manifest beside helper at {path})")
        return None
    except (OSError, ValueError) as exc:
        _breadcrumb(f"version unestablished (manifest at {path} unreadable: {exc})")
        return None
    version = data.get("version") if isinstance(data, dict) else None
    if isinstance(version, str) and version.strip():
        return version
    _breadcrumb(f"version unestablished (manifest at {path} has no string .version)")
    return None


def read_effort() -> str | None:
    """Return CLAUDE_EFFORT when set and non-blank, else None + breadcrumb."""
    raw = os.environ.get("CLAUDE_EFFORT")
    if raw is not None and raw.strip():
        return raw.strip()
    _breadcrumb("effort unestablished (CLAUDE_EFFORT unset, empty, or whitespace-only)")
    return None


def _config_dir() -> Path:
    """The Claude Code config directory: CLAUDE_CONFIG_DIR when set and non-blank,
    else the default user-level ~/.claude directory."""
    raw = os.environ.get("CLAUDE_CONFIG_DIR")
    if raw is not None and raw.strip():
        return Path(raw.strip())
    return Path.home() / ".claude"


def _project_segment(cwd: Path) -> str:
    """Claude Code's transcript project segment: the working-directory path with every
    non-alphanumeric character replaced by a dash (documented scheme)."""
    return re.sub(r"[^a-zA-Z0-9]", "-", str(cwd))


def transcript_path() -> Path | None:
    """Derive the session transcript path from CLAUDE_CONFIG_DIR (or the default), the
    session's own working directory, and CLAUDE_CODE_SESSION_ID. Returns None (with a
    breadcrumb) only when there is no session id to name the file with."""
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if session_id is None or not session_id.strip():
        _breadcrumb("model unestablished (CLAUDE_CODE_SESSION_ID unset, empty, or whitespace-only)")
        return None
    segment = _project_segment(Path.cwd())
    return _config_dir() / "projects" / segment / f"{session_id.strip()}.jsonl"


def _model_from_record(rec: object) -> str | None:
    """Return message.model of an assistant record when it is a non-empty string, else
    None. resolvedModel (a dispatched subagent's model) is deliberately never read."""
    if not isinstance(rec, dict) or rec.get("type") != "assistant":
        return None
    message = rec.get("message")
    if not isinstance(message, dict):
        return None
    model = message.get("model")
    if isinstance(model, str) and model.strip():
        return model
    return None


def read_model() -> str | None:
    """Return the most recent assistant record's model from the session transcript, or
    None + breadcrumb. Fails soft on every read: an absent store, a truncated final
    record, malformed JSON, a wrong-typed field, and an empty file all yield None."""
    path = transcript_path()
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        _breadcrumb(f"model unestablished (no transcript at derived path {path})")
        return None
    except (OSError, ValueError) as exc:
        _breadcrumb(f"model unestablished (transcript at {path} unreadable: {exc})")
        return None
    latest: str | None = None
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            # A truncated final record or a malformed line — skip it; the last COMPLETE
            # assistant record still wins.
            continue
        model = _model_from_record(rec)
        if model is not None:
            latest = model
    if latest is None:
        _breadcrumb(f"model unestablished (transcript at {path} carries no assistant record with a model)")
    return latest


def _repo_root() -> Path:
    """The git working-tree root (SHARED REPO-ROOT CONFIG CONTRACT), falling back to the
    process CWD when git cannot resolve one."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return Path.cwd()
    if out.returncode == 0 and out.stdout.strip():
        return Path(out.stdout.strip())
    return Path.cwd()


def _config_path(explicit: str | None) -> Path:
    """The config file to read: a non-empty explicit --config verbatim, else
    <repo-root>/.prflow/config.json (with a .devflow fallback when only that exists)."""
    if explicit is not None and explicit.strip():
        return Path(explicit.strip())
    root = _repo_root()
    canonical = root / ".prflow" / "config.json"
    if not canonical.exists():
        superseded = root / ".devflow" / "config.json"
        if superseded.exists():
            return superseded
    return canonical


def model_effort_permitted(explicit_config: str | None) -> bool:
    """False only when the config key serializes to an explicit JSON boolean ``false``
    read directly from the working-tree config (mirroring scripts/workpad.py, never
    exec-ing config-get.sh, whose string coercion is the Windows failure #220). A
    missing key, a truthy value, or a wrong-typed value all leave the clause enabled —
    the truthy-default direction, so only a deliberate ``false`` switches it off."""
    path = _config_path(explicit_config)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return True
    except (OSError, ValueError) as exc:
        _breadcrumb(f"config unreadable at {path} ({exc}); model+effort clause left enabled")
        return True
    if not isinstance(data, dict):
        return True
    section = data.get(_CONFIG_SECTION)
    if not isinstance(section, dict):
        return True
    value = section.get(_CONFIG_KEY)
    if value is False:
        return False
    return True


def render_line(*, explicit_config: str | None = None) -> str:
    """Compose the provenance line. Established values are named in order (version,
    model, effort); an empty set yields no parenthetical at all — never empty punctuation."""
    version = read_version()
    if model_effort_permitted(explicit_config):
        model = read_model()
        effort = read_effort()
    else:
        _breadcrumb(f"model+effort clause suppressed ({_CONFIG_SECTION}.{_CONFIG_KEY} is false)")
        model = None
        effort = None
    values = [v for v in (f"v{version}" if version else None, model, effort) if v]
    base = "Generated via /prflow:implement"
    if values:
        return f"{base} ({', '.join(values)})"
    return base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=None,
        help="Explicit config file to read the gating key from (default: the working-tree "
        ".prflow/config.json under the repo root). A non-empty value is honored verbatim.",
    )
    args = parser.parse_args(argv)
    print(render_line(explicit_config=args.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
