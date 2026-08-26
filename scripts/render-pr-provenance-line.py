#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Render a PRFlow provenance line on stdout, in Markdown italics.

The line names the command it was run for (the required ``--command`` argument) and the
plugin build that executed the run, and — when they can be established and the consumer
has not switched the clause off — the session model and reasoning effort:

    _Generated via /prflow:implement (v2.32.70, claude-opus-5, high)_
    _Generated via /prflow:create-issue (v2.32.70)_

The command name is supplied by the caller, so one renderer serves every command; both
``/prflow:implement`` and ``/prflow:create-issue`` paste the finished italic line verbatim.

Three value-sources besides the command, each read soft:

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
other shell-active construct — the caller substitutes it into a double-quoted ``--body``,
so every value is dropped (omitted + breadcrumbed) if it carries one, enforcing the
guarantee by construction rather than trusting the source — and the ``--command`` value
flows through that same guard, so a shell-active command drops the whole line (nothing on
stdout, a breadcrumb on stderr) rather than shipping. The helper exits 0 in every case
except a missing required ``--command`` argument, which is an argparse usage error (usage
to stderr, nothing to stdout, a non-zero exit): an unreadable source shortens the line, it
never fails the caller's fence.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

#: The plugin manifest, resolved beside this file (mirroring lib/efficiency-trace.sh).
_MANIFEST_BESIDE_HELPER = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"

#: The prflow config key gating the model+effort clause (raw JSON false suppresses).
_CONFIG_SECTION = "prflow"
_CONFIG_KEY = "publish_model_effort"

#: Characters that would make a value shell-active once substituted into the caller's
#: double-quoted --body, or break the single-line body: backtick and ``$`` (command/var
#: substitution), backslash and double-quote (quoting escapes), and any control char
#: including newline/tab. A value carrying one is dropped rather than shipped, so the
#: "no shell-active construct" guarantee is enforced by construction, not by trust.
_SHELL_ACTIVE = re.compile(r'[`$\\"\x00-\x1f\x7f]')


def _breadcrumb(msg: str) -> None:
    """Emit a provenance breadcrumb on stderr (never stdout)."""
    print(f"render-pr-provenance-line: {msg}", file=sys.stderr)


def _shell_inert(label: str, value: str | None) -> str | None:
    """Return value stripped when it is non-blank and carries no shell-active or control
    character; else None + breadcrumb. This is the single enforcement point for the
    line's shell-inert guarantee, applied to every value whatever its source."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if _SHELL_ACTIVE.search(stripped):
        _breadcrumb(f"{label} omitted (carries a shell-active or control character; the provenance line must stay shell-inert)")
        return None
    return stripped


def _env_nonblank(name: str) -> str | None:
    """Return the environment variable stripped, when set and not whitespace-only; else None.
    An unset variable expands to None, and an empty or blank value is treated as unset."""
    raw = os.environ.get(name)
    return raw.strip() if raw and raw.strip() else None


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
    effort = _env_nonblank("CLAUDE_EFFORT")
    if effort is not None:
        return effort
    _breadcrumb("effort unestablished (CLAUDE_EFFORT unset, empty, or whitespace-only)")
    return None


def _config_dir() -> Path:
    """The Claude Code config directory: CLAUDE_CONFIG_DIR when set and non-blank,
    else the default user-level ~/.claude directory."""
    raw = _env_nonblank("CLAUDE_CONFIG_DIR")
    return Path(raw) if raw is not None else Path.home() / ".claude"


def _project_segment(cwd: Path) -> str:
    """Claude Code's transcript project segment: the working-directory path with every
    non-alphanumeric character replaced by a dash (documented scheme)."""
    return re.sub(r"[^a-zA-Z0-9]", "-", str(cwd))


def transcript_path() -> Path | None:
    """Derive the session transcript path from CLAUDE_CONFIG_DIR (or the default), the
    session's own working directory, and CLAUDE_CODE_SESSION_ID. Returns None (with a
    breadcrumb) only when there is no session id to name the file with."""
    session_id = _env_nonblank("CLAUDE_CODE_SESSION_ID")
    if session_id is None:
        _breadcrumb("model unestablished (CLAUDE_CODE_SESSION_ID unset, empty, or whitespace-only)")
        return None
    segment = _project_segment(Path.cwd())
    return _config_dir() / "projects" / segment / f"{session_id}.jsonl"


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
        _breadcrumb(f"config at {path} is not a JSON object; model+effort clause left enabled")
        return True
    section = data.get(_CONFIG_SECTION)
    if section is not None and not isinstance(section, dict):
        _breadcrumb(f"config {_CONFIG_SECTION} is not an object; model+effort clause left enabled")
        return True
    if not isinstance(section, dict):
        return True
    value = section.get(_CONFIG_KEY)
    return value is not False


def render_line(*, command: str, explicit_config: str | None = None) -> str | None:
    """Compose the italic provenance line for ``command``. Established values are named in
    order (version, model, effort); an empty set yields no parenthetical at all — never
    empty punctuation. Returns None (nothing to print) when the command itself is blank or
    carries a shell-active/control character, so a dropped command emits no line rather than
    a line with an empty command name."""
    command_clean = _shell_inert("command", command)
    if command_clean is None:
        if not (command and command.strip()):
            # _shell_inert breadcrumbs a shell-active value but drops a blank one silently;
            # name the blank case so a mis-substituted call site reports its own reason.
            _breadcrumb("command omitted (blank or whitespace-only); no provenance line rendered")
        return None
    version = _shell_inert("version", read_version())
    if model_effort_permitted(explicit_config):
        model = _shell_inert("model", read_model())
        effort = _shell_inert("effort", read_effort())
    else:
        _breadcrumb(f"model+effort clause suppressed ({_CONFIG_SECTION}.{_CONFIG_KEY} is false)")
        model = None
        effort = None
    values = [v for v in (f"v{version}" if version else None, model, effort) if v]
    base = f"Generated via {command_clean}"
    inner = f"{base} ({', '.join(values)})" if values else base
    return f"_{inner}_"


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_streams()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--command",
        required=True,
        help="The command name to name in the line (e.g. /prflow:implement or "
        "/prflow:create-issue). Required: a missing value is an argparse usage error "
        "(usage to stderr, nothing to stdout, non-zero exit). A value carrying a "
        "shell-active or control character drops the whole line (nothing to stdout, exit 0).",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Explicit config file to read the gating key from (default: the working-tree "
        ".prflow/config.json under the repo root). A non-empty value is honored verbatim.",
    )
    args = parser.parse_args(argv)
    line = render_line(command=args.command, explicit_config=args.config)
    if line is not None:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
