#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Static check for ci.yml's workflow-level supersession `concurrency` (issue #1236).

`.github/workflows/ci.yml` gains a WORKFLOW-LEVEL `concurrency:` key so that a push
superseding a still-running pull-request CI run cancels it, while `main` pushes are
neither cancelled nor serialized. This is a `ci.yml`-scheduler behavior that cannot
be executed locally, so this is the closest mechanical surface: a static check over
the workflow file's own concurrency region.

The properties (AC2):
  1. a workflow-level `concurrency` key exists (a sibling of name/on/permissions/jobs);
  2. its `group` VARIES WITH THE PULL REQUEST — it references
     `github.event.pull_request.number` (so two runs on one PR branch share a group and
     two different PRs never do) AND falls back to something unique per run for non-PR
     events (`github.run_id`), so a `main` push gets its own group rather than sharing
     one collapsed group;
  3. its `cancel-in-progress` does NOT resolve `true` for a `main` push — it is gated on
     the event being a `pull_request` (`github.event_name == 'pull_request'`), not a bare
     literal `true`.

Fails CLOSED: an unreadable, empty, or unparseable workflow file, or a `concurrency`
value of the wrong shape, is `unavailable`/`fail`, never a silent pass.

Exit codes:
  0  all three properties hold (prints `CI_CONCURRENCY ok`)
  1  a property is violated (prints `CI_CONCURRENCY fail: <reason>`)
  3  the measurement could not be established (prints `CI_CONCURRENCY unavailable: <cause>`)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is a suite prerequisite
    print("CI_CONCURRENCY unavailable: PyYAML not importable", file=sys.stderr)
    sys.exit(3)


def _load(ci_file: Path):
    """Return the parsed top-level mapping, or (None, cause) fail-closed."""
    try:
        text = ci_file.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"could not read {ci_file} ({exc})"
    if not text.strip():
        return None, f"{ci_file} is empty"
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return None, f"{ci_file} is not parseable YAML ({exc})"
    if not isinstance(doc, dict):
        return None, f"{ci_file} did not parse to a mapping"
    return doc, ""


def _check(doc: dict) -> tuple[int, str]:
    conc = doc.get("concurrency")
    if conc is None:
        return 1, "no workflow-level concurrency key"
    if not isinstance(conc, dict):
        return 1, "concurrency is not a mapping"

    group = conc.get("group")
    if not isinstance(group, str) or not group.strip():
        return 1, "concurrency.group is missing or not a string"
    # Property 2: the group varies with the pull request and is unique-per-run off-PR.
    if "github.event.pull_request.number" not in group:
        return 1, "group does not vary with the pull request (no github.event.pull_request.number)"
    if "github.run_id" not in group:
        return 1, "group has no per-run fallback for non-PR events (no github.run_id)"

    # Property 3: cancel-in-progress must not resolve true for a main push. It is
    # normalized to a string because a `${{ … }}` expression parses as a str while a
    # bare YAML `true` parses as a bool.
    cip = conc.get("cancel-in-progress")
    cip_s = str(cip).strip()
    if cip is None or cip_s == "":
        return 1, "concurrency.cancel-in-progress is missing"
    if "github.event_name == 'pull_request'" not in cip_s:
        return (
            1,
            ("cancel-in-progress is not gated on the pull_request event, so it would "
            f"resolve true for a main push (got {cip_s!r})"),
        )
    return 0, ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ci-file",
        default=".github/workflows/ci.yml",
        help="path to the workflow file to check (default: .github/workflows/ci.yml)",
    )
    args = parser.parse_args(argv)

    doc, cause = _load(Path(args.ci_file))
    if doc is None:
        print(f"CI_CONCURRENCY unavailable: {cause}")
        return 3
    code, reason = _check(doc)
    if code == 0:
        print("CI_CONCURRENCY ok")
    else:
        print(f"CI_CONCURRENCY fail: {reason}")
    return code


if __name__ == "__main__":
    sys.exit(main())
