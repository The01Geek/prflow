#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Stamp repository identity onto the retrospective record stores.

Every record in the three learnings stores keys on a bare GitHub number, which is
ambiguous the moment PRFlow development spans more than one repository. This is
the one-time, deterministic, idempotent migration that qualifies them:

  retrospectives.jsonl     schema_version 2 -> 4, adds `repo` + `pr_key`
  experiment-records.jsonl schema_version 1 -> 2, adds `repo` + `pr_key`
  overrides.json           schema_version 3 -> 4, adds `repo` to every
                           `patterns[].meta_issues[]` entry

The repository stamped on a record that names none is the `legacy_record_repo`
from lib/repo-identity.json — the explicit one-time compatibility rule, and the
only sanctioned substitution. A record that already names a repository is left
alone, so a store holding records from a second repository survives a re-run
unchanged.

Idempotency is by construction: the transform is a pure function of each record,
and re-running it over its own output reproduces that output byte for byte.

Usage:
  scripts/migrate-record-repo.py [--learnings-dir <dir>] [--check]

`--check` reports what would change and exits 1 when anything would, writing
nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RETROSPECTIVES_SCHEMA = 4
EXPERIMENT_RECORDS_SCHEMA = 2
OVERRIDES_SCHEMA = 4


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _legacy_record_repo(identity_file: Path) -> str:
    """The repository every pre-qualification record belongs to.

    Read from lib/repo-identity.json rather than hardcoded: the constant is a
    coupled site shared with lib/repo-identity.sh, and a second copy here would
    drift the day the value is corrected."""
    data = json.loads(identity_file.read_text(encoding="utf-8"))
    value = data.get("legacy_record_repo")
    if not isinstance(value, str) or value.count("/") != 1 or not all(value.split("/")):
        raise SystemExit(
            f"migrate-record-repo: {identity_file} holds no usable legacy_record_repo "
            f"({value!r}) — refusing to stamp records with an unestablished repository"
        )
    return value


def _stamped_record(record: dict, legacy_repo: str, schema: int) -> dict:
    """Return `record` with `repo`, `pr_key` and `schema_version` established.

    Field order is preserved for records that already carry a key, and new keys are
    appended, so a re-run over an already-stamped record reproduces it exactly."""
    out = dict(record)
    existing = out.get("repo")
    repo = existing if isinstance(existing, str) and existing else legacy_repo
    out["repo"] = repo
    number = out.get("pr")
    if isinstance(number, int):
        out["pr_key"] = f"{repo}#{number}"
    out["schema_version"] = schema
    return out


def _migrate_jsonl(path: Path, legacy_repo: str, schema: int, check: bool) -> int:
    """Rewrite one JSONL store in place. Returns the number of changed records."""
    if not path.exists():
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    out_lines: list[str] = []
    changed = 0
    for lineno, line in enumerate(lines, 1):
        if not line.strip():
            out_lines.append(line)
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"migrate-record-repo: {path}:{lineno} does not parse as JSON ({exc}) — "
                "refusing to rewrite a store it cannot read in full"
            ) from exc
        if not isinstance(record, dict):
            raise SystemExit(
                f"migrate-record-repo: {path}:{lineno} is not a JSON object — "
                "refusing to rewrite a store it cannot read in full"
            )
        stamped = _stamped_record(record, legacy_repo, schema)
        rendered = json.dumps(stamped, separators=(",", ":"), ensure_ascii=False)
        if rendered != json.dumps(record, separators=(",", ":"), ensure_ascii=False):
            changed += 1
        out_lines.append(rendered)
    if changed and not check:
        path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return changed


def _migrate_overrides(path: Path, legacy_repo: str, check: bool) -> int:
    """Stamp `repo` on every meta-issue entry and move the document to v4."""
    if not path.exists():
        return 0
    original = path.read_text(encoding="utf-8")
    try:
        doc = json.loads(original)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"migrate-record-repo: {path} does not parse as JSON ({exc}) — "
            "refusing to rewrite a store it cannot read in full"
        ) from exc
    if not isinstance(doc, dict):
        raise SystemExit(f"migrate-record-repo: {path} is not a JSON object")
    patterns = doc.get("patterns")
    if isinstance(patterns, dict):
        for record in patterns.values():
            if not isinstance(record, dict):
                continue
            entries = record.get("meta_issues")
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                existing = entry.get("repo")
                if not (isinstance(existing, str) and existing):
                    entry["repo"] = legacy_repo
    doc["schema_version"] = OVERRIDES_SCHEMA
    rendered = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    if rendered == original:
        return 0
    if not check:
        path.write_text(rendered, encoding="utf-8")
    return 1


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
        "--learnings-dir",
        default=None,
        help="directory holding the three stores (default: <repo>/.prflow/learnings)",
    )
    parser.add_argument(
        "--identity-file",
        default=None,
        help="path to repo-identity.json (default: <repo>/lib/repo-identity.json)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report what would change and exit 1 when anything would; write nothing",
    )
    args = parser.parse_args(argv)

    root = _repo_root()
    learnings = Path(args.learnings_dir) if args.learnings_dir else root / ".prflow" / "learnings"
    identity_file = Path(args.identity_file) if args.identity_file else root / "lib" / "repo-identity.json"
    legacy_repo = _legacy_record_repo(identity_file)

    total = 0
    total += _migrate_jsonl(
        learnings / "retrospectives.jsonl", legacy_repo, RETROSPECTIVES_SCHEMA, args.check
    )
    total += _migrate_jsonl(
        learnings / "experiment-records.jsonl", legacy_repo, EXPERIMENT_RECORDS_SCHEMA, args.check
    )
    total += _migrate_overrides(learnings / "overrides.json", legacy_repo, args.check)

    if args.check:
        print(f"migrate-record-repo: {total} store change(s) pending", file=sys.stderr)
        return 1 if total else 0
    print(f"migrate-record-repo: stamped {legacy_repo} onto {total} record(s)/store(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
