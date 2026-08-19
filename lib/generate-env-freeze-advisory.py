#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Render (and audit) the frozen-`DEVFLOW_*`-identifier advisory (issue #1004).

THE DELIVERABLE IS A "DO NOT RENAME" INVENTORY, NOT A RENAME TABLE. The consumer-facing
`DEVFLOW_*` variables, secrets and environment overrides are frozen under that spelling
because no `PRFLOW_*` read side exists anywhere in the tree. Renaming one does not move a
setting, it deletes it -- and most of them delete it silently, because an unresolvable
GitHub variable is byte-identical to "deliberately not configured". Nothing this file
emits may read as an instruction to rename anything.

`lib/rename-map.json`'s `frozen.env_identifiers` block is the single source: the row set,
the per-row failure mode, the criterion and the two recorded adjudications all live there
and nothing here re-derives them. This helper has two jobs, kept apart because their
remedies differ:

  render / --check   The advisory table in the REGION_FILE document is a GENERATED region,
                     banner-stamped with a sha256 over its own body. `--check` reports
                     drift between the region and the JSON; the remedy is to re-run this
                     generator, so the batched-artifact pass carries it as a
                     `regenerate` row.

  --derive           Runs the criterion's two arms over the tree and prints the selected
                     names. `--audit` compares that live selection against the recorded
                     population (`identifiers` + `adjudicated_out`) and fails when they
                     disagree in either direction. The remedy there is a HUMAN
                     adjudication, never a regeneration, which is why it is not an
                     artifact row and is driven from the test module instead.

The arms are exactly the ones `frozen.env_identifiers.criterion` states:

  A1  cloud channel    -- `secrets.<NAME>` / `vars.<NAME>` in a workflow install.sh ships.
  A2  operator channel -- read as an ambient environment variable by a shipped
                          install.sh / scripts/ / lib/ file AND declared in a
                          consumer-facing document.

A2's never-assigned-internally clause is deliberately NOT a third grep here. A name can be
internally supplied to one reader and operator-supplied to another -- `DEVFLOW_REF` is
that case -- so it is applied as a recorded per-candidate adjudication in the JSON, and
`--audit` only enforces that every candidate the arms select has one.

EXIT CODES
  0  clean (region matches, or the derived population matches the record)
  1  drift -- a resolvable finding, reported with its direction
  2  input failure -- the map or a scanned file could not be read or parsed. Kept
     distinct from 1 so a batched pass never tells an agent to regenerate from a file it
     could not read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

GENERATOR = "lib/generate-env-freeze-advisory.py"
MAP_REL = "lib/rename-map.json"
REGION_FILE = "docs/internal/cloud-setup.md"
BEGIN_RE = re.compile(
    r"^(?P<indent>\s*)<!-- prflow-env-freeze:begin freeze_version=(?P<ver>\d+) "
    r"sha256=(?P<sha>[0-9a-f]{64}) "
)
END_TEXT = "<!-- prflow-env-freeze:end -->"

# The read shapes A2 accepts. A `${NAME:-...}` / `${NAME:=...}` self-default IS a read,
# not an assignment -- the value still comes from the ambient environment.
READ_PATTERNS = (
    r"\$\{(DEVFLOW_[A-Z0-9_]+)(?::[-=?+]|[-=?+]|\}|:)",
    r"\$(DEVFLOW_[A-Z0-9_]+)\b",
    r"environ\.get\(\s*[\"'](DEVFLOW_[A-Z0-9_]+)[\"']",
    r"environ\[\s*[\"'](DEVFLOW_[A-Z0-9_]+)[\"']\s*\]",
    r"getenv\(\s*[\"'](DEVFLOW_[A-Z0-9_]+)[\"']",
)
CLOUD_REF_RE = re.compile(r"\b(secrets|vars)\.(DEVFLOW_[A-Z0-9_]+)")
NAME_RE = re.compile(r"DEVFLOW_[A-Z0-9_]+")


class InputError(Exception):
    """An input could not be read or parsed. Routed to exit 2, never to exit 1."""


def repo_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return Path.cwd()
    return Path(out) if out else Path.cwd()


def load_block(root: Path) -> dict:
    path = root / MAP_REL
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InputError(f"rename map unreadable: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputError(f"rename map malformed JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise InputError("rename map is not a JSON object")
    frozen = data.get("frozen")
    if not isinstance(frozen, dict):
        raise InputError("rename map has no object `frozen` block")
    block = frozen.get("env_identifiers")
    if not isinstance(block, dict):
        raise InputError("rename map has no object `frozen.env_identifiers` block")
    return block


REQUIRED_ROW_FIELDS = (
    "name",
    "arm",
    "channel",
    "kind",
    "set_where",
    "read_as",
    "failure_visibility",
    "failure_mode",
)
CHANNELS = ("cloud", "operator")
ARMS = ("A1", "A2")


def validate(block: dict) -> list[dict]:
    """Shape-check the block and return its identifier rows.

    Fails closed: a row missing its failure mode is exactly the defect this advisory
    exists to prevent, so an incomplete row is an input failure and not a rendered blank.
    """
    rows = block.get("identifiers")
    if not isinstance(rows, list) or not rows:
        raise InputError("`frozen.env_identifiers.identifiers` is not a non-empty list")
    seen: set[str] = set()
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise InputError(f"identifier row {i} is not an object")
        for field in REQUIRED_ROW_FIELDS:
            value = row.get(field)
            if not isinstance(value, str) or not value.strip():
                raise InputError(
                    f"identifier row {i} ({row.get('name', '?')}) has an empty or "
                    f"non-string `{field}`"
                )
        if row["channel"] not in CHANNELS:
            raise InputError(
                f"identifier row {row['name']} has channel {row['channel']!r}; "
                f"expected one of {CHANNELS}"
            )
        if row["arm"] not in ARMS:
            raise InputError(
                f"identifier row {row['name']} has arm {row['arm']!r}; expected one of {ARMS}"
            )
        if not NAME_RE.fullmatch(row["name"]):
            raise InputError(f"identifier row {i} name {row['name']!r} is not a DEVFLOW_* name")
        if row["name"] in seen:
            raise InputError(f"identifier {row['name']} is recorded twice")
        seen.add(row["name"])
    for i, row in enumerate(block.get("adjudicated_out") or []):
        if not isinstance(row, dict):
            raise InputError(f"adjudicated_out row {i} is not an object")
        for field in ("name", "selected_by", "decided_by", "verdict", "evidence"):
            value = row.get(field)
            if not isinstance(value, str) or not value.strip():
                raise InputError(
                    f"adjudicated_out row {i} ({row.get('name', '?')}) has an empty or "
                    f"non-string `{field}`"
                )
    return rows


# ── the criterion ───────────────────────────────────────────────────────────


def tracked_files(root: Path) -> list[str]:
    # git ls-files (index-reading, no --others): a repository-root-anchored recursive walk
    # would descend into sibling worktrees under .claude/worktrees/ and count another
    # branch's checkout (issue #711).
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InputError(f"could not enumerate tracked files under {root}: {exc}") from exc
    return out.split("\n")


def read_text(root: Path, rel: str) -> str | None:
    path = root / rel
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise InputError(f"could not read {rel}: {exc}") from exc


def strip_region(text: str) -> str:
    """Drop this generator's own output from a document before scanning it.

    Load-bearing, not tidiness. The advisory region names every identifier it covers AND
    the two it excludes, and it is rendered INTO a document A2 scans for declarations. Left
    in, the generated output becomes an input to its own derivation: a name recorded as
    adjudicated-out would be re-selected purely because the sentence explaining its
    exclusion mentions it, and the record could never converge. A2 asks where the SETUP
    instructions declare a name a consumer sets; derived output is not such a declaration.
    Only complete begin/end pairs are dropped, so a malformed region falls through to
    locate()'s fail-closed handling instead of silently swallowing the rest of the file.
    """
    lines = text.split("\n")
    kept: list[str] = []
    depth = 0
    for line in lines:
        if BEGIN_RE.match(line):
            depth += 1
            continue
        if line.strip() == END_TEXT and depth:
            depth -= 1
            continue
        if not depth:
            kept.append(line)
    # An unterminated begin banner: keep the document intact rather than truncate it.
    return text if depth else "\n".join(kept)


def is_shipped_reader(rel: str) -> bool:
    return (
        rel == "install.sh"
        or rel.startswith("scripts/")
        or (rel.startswith("lib/") and not rel.startswith("lib/test/"))
    )


def derive(root: Path, block: dict) -> dict[str, set[str]]:
    """Run both arms over the tree. Returns {name: {"A1"} | {"A2"} | both}."""
    criterion = block.get("criterion")
    if not isinstance(criterion, dict):
        raise InputError("`frozen.env_identifiers.criterion` is not an object")
    workflows = criterion.get("shipped_workflows")
    docs = criterion.get("consumer_docs")
    if not isinstance(workflows, list) or not workflows:
        raise InputError("criterion `shipped_workflows` is not a non-empty list")
    if not isinstance(docs, list) or not docs:
        raise InputError("criterion `consumer_docs` is not a non-empty list")

    selected: dict[str, set[str]] = {}

    # A1 — the cloud channel.
    for name in workflows:
        rel = f".github/workflows/{name}"
        text = read_text(root, rel)
        if text is None:
            raise InputError(f"shipped workflow {rel} is absent")
        for match in CLOUD_REF_RE.finditer(text):
            selected.setdefault(match.group(2), set()).add("A1")

    # A2 — the operator channel: an ambient read by a shipped file, intersected with the
    # names a consumer-facing document declares.
    reads: set[str] = set()
    for rel in tracked_files(root):
        if not rel or not is_shipped_reader(rel):
            continue
        text = read_text(root, rel)
        if text is None or "DEVFLOW_" not in text:
            continue
        for pattern in READ_PATTERNS:
            for match in re.finditer(pattern, text, re.M):
                reads.add(match.group(1))

    declared: set[str] = set()
    for rel in docs:
        text = read_text(root, rel)
        if text is None:
            raise InputError(f"consumer document {rel} is absent")
        declared.update(match.group(0) for match in NAME_RE.finditer(strip_region(text)))

    for name in reads & declared:
        selected.setdefault(name, set()).add("A2")

    return selected


def audit(root: Path, block: dict) -> tuple[int, str]:
    rows = validate(block)
    recorded_in = [row["name"] for row in rows]
    recorded_out = [row["name"] for row in (block.get("adjudicated_out") or [])]
    adjudicated = set(recorded_in) | set(recorded_out)
    selected = derive(root, block)

    unadjudicated = sorted(set(selected) - adjudicated)
    # A recorded row the arms no longer select. `adjudicated_out` rows are exempt: an entry
    # is legitimately recorded there BECAUSE neither arm selects it (DEVFLOW_CONFIG_FILE is
    # exactly that), so requiring one to stay selected would invert the block's meaning.
    unselected = sorted(set(recorded_in) - set(selected))

    parts = []
    if unadjudicated:
        parts.append(
            "the criterion selects name(s) that are recorded NOWHERE in "
            "frozen.env_identifiers — adjudicate each into `identifiers` (consumer-facing) "
            "or `adjudicated_out` (with the deciding arm and its evidence):\n"
            + "".join(f"    + {n}  [{'/'.join(sorted(selected[n]))}]\n" for n in unadjudicated)
        )
    if unselected:
        parts.append(
            "name(s) recorded in `identifiers` are no longer selected by the criterion — "
            "the read side moved or went away, so re-adjudicate the row rather than "
            "leaving a consumer warning about a name nothing reads:\n"
            + "".join(f"    - {n}\n" for n in unselected)
        )
    if parts:
        return 1, (
            "env-freeze: the recorded consumer-facing population disagrees with the "
            "criterion run over this tree:\n  " + "\n  ".join(parts)
        )
    return 0, (
        f"env-freeze: the criterion selects {len(selected)} name(s); all are adjudicated "
        f"({len(recorded_in)} consumer-facing, {len(recorded_out)} recorded out)."
    )


# ── the generated region ────────────────────────────────────────────────────


def md_cell(text: str) -> str:
    """Escape a JSON string for a markdown table cell (single-line, pipes escaped).

    The source block is ASCII (a JSON file the shell and jq consumers also read), so the
    two ASCII digraphs it uses for prose punctuation are lifted to their typographic
    forms here rather than being carried as non-ASCII in the map.
    """
    return (
        text.replace("|", "\\|")
        .replace("\n", " ")
        .replace(" -- ", " — ")
        .replace(" -> ", " → ")
        .strip()
    )


def body(block: dict, rows: list[dict]) -> list[str]:
    out: list[str] = []
    out.append(
        "> **These names are frozen. Do not rename them.** PRFlow reads each one under "
        "its `DEVFLOW_` spelling and under no other spelling — there is no `PRFLOW_*` "
        "equivalent anywhere in the plugin. Renaming one of these does not move a "
        "setting; it removes it."
    )
    out.append("")
    asymmetry = block.get("pair_asymmetry")
    if isinstance(asymmetry, str) and asymmetry.strip():
        out.append(f"**The two GitHub App pairs fail asymmetrically.** {md_cell(asymmetry)}")
        out.append("")

    for channel, title, lead in (
        (
            "cloud",
            "Set in GitHub — repository or organization settings",
            "You set these under **Settings → Secrets and variables → Actions**. "
            "PRFlow can only read them.",
        ),
        (
            "operator",
            "Set on your machine — shell profile or install one-liner",
            "You set these in your own environment. Every one resolves through a "
            "`${NAME:-…}`-style default, so a name that stops resolving is "
            "byte-identical to one that was never set.",
        ),
    ):
        selected = [r for r in rows if r["channel"] == channel]
        if not selected:
            continue
        out.append(f"#### {title}")
        out.append("")
        out.append(lead)
        out.append("")
        out.append("| Identifier | Where you set it | Renaming it fails | What renaming it does |")
        out.append("|---|---|---|---|")
        for row in selected:
            marker = " **⚠ highest severity**" if row.get("severity") == "highest" else ""
            note = row.get("dual_role")
            detail = md_cell(row["failure_mode"])
            if isinstance(note, str) and note.strip():
                detail += f" *Dual role:* {md_cell(note)}"
            out.append(
                f"| `{row['name']}` | {md_cell(row['kind'])} — {md_cell(row['set_where'])} "
                f"| {md_cell(row['failure_visibility'])}{marker} | {detail} |"
            )
        out.append("")

    out.append(
        "Not on this list and wondering why: `DEVFLOW_PROMPT_EXTENSION_ROOT` is written "
        "by the cloud workflows that run the review engine and never set by you, and `DEVFLOW_CONFIG_FILE` "
        "is an internal seam that has never been published as a consumer setting. Both "
        "are recorded with their reasoning in `lib/rename-map.json`."
    )
    return out


def region_sha(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def banner(block: dict, lines: list[str]) -> str:
    return (
        f"<!-- prflow-env-freeze:begin freeze_version={block.get('freeze_version', 0)} "
        f"sha256={region_sha(lines)} (generated by {GENERATOR} -- do not hand-edit; "
        f"source: {MAP_REL} frozen.env_identifiers) -->"
    )


def locate(text: str, rel: str) -> tuple[int, int, str]:
    """Return (begin_idx, end_idx, indent). Fails closed on 0 or 2+ banners."""
    lines = text.split("\n")
    begins = [(i, m) for i, line in enumerate(lines) if (m := BEGIN_RE.match(line))]
    if len(begins) != 1:
        raise InputError(
            f"{rel} carries {len(begins)} `prflow-env-freeze:begin` banner(s); expected exactly 1"
        )
    bi, match = begins[0]
    ends = [i for i, line in enumerate(lines) if line.strip() == END_TEXT and i > bi]
    if not ends:
        raise InputError(f"{rel} has no `{END_TEXT}` after its begin banner")
    return bi, ends[0], match.group("indent")


def render(block: dict, rows: list[dict], indent: str) -> list[str]:
    payload = body(block, rows)
    return (
        [indent + banner(block, payload)]
        + [(indent + line).rstrip() for line in payload]
        + [indent + END_TEXT]
    )


def run_region(root: Path, block: dict, check: bool) -> tuple[int, str]:
    rows = validate(block)
    text = read_text(root, REGION_FILE)
    if text is None:
        raise InputError(f"{REGION_FILE} is absent")
    bi, ei, indent = locate(text, REGION_FILE)
    lines = text.split("\n")
    fresh = render(block, rows, indent)
    current = lines[bi : ei + 1]
    if current == fresh:
        return 0, f"env-freeze: the {REGION_FILE} advisory region matches {MAP_REL}."
    if check:
        return 1, (
            f"env-freeze: the generated advisory region in {REGION_FILE} differs from "
            f"{MAP_REL} frozen.env_identifiers:\n"
            "    expected:\n"
            + "".join(f"      {ln}\n" for ln in fresh)
            + "    found:\n"
            + "".join(f"      {ln}\n" for ln in current)
            + f"  remedy: python3 {GENERATOR}"
        )
    (root / REGION_FILE).write_text(
        "\n".join(lines[:bi] + fresh + lines[ei + 1 :]), encoding="utf-8"
    )
    return 0, f"env-freeze: regenerated the advisory region in {REGION_FILE}."


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8 on the CLI entry path only (not at import, so a
    unit-test import never mutates the importer's streams). A no-op where the ambient
    codec is already UTF-8; self-defends against a non-UTF-8 default codec such as
    Windows cp1252. Tolerates a non-TextIOWrapper stream (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv=None) -> int:
    _force_utf8_streams()
    ap = argparse.ArgumentParser(description="Render the frozen-DEVFLOW_* advisory region.")
    ap.add_argument("--check", action="store_true", help="verify the region without writing")
    ap.add_argument("--derive", action="store_true", help="print the names the criterion selects")
    ap.add_argument(
        "--audit",
        action="store_true",
        help="compare the criterion's live selection against the recorded population",
    )
    ap.add_argument("--repo-root", default=None, help="tree to operate on (default: the git root)")
    args = ap.parse_args(argv)

    root = repo_root(args.repo_root)
    try:
        block = load_block(root)
        if args.derive:
            selected = derive(root, block)
            for name in sorted(selected):
                print(f"{name}\t{'/'.join(sorted(selected[name]))}")
            return 0
        if args.audit:
            rc, message = audit(root, block)
        else:
            rc, message = run_region(root, block, args.check)
    except InputError as exc:
        print(f"env-freeze: {exc}", file=sys.stderr)
        return 2
    print(message, file=sys.stderr if rc else sys.stdout)
    return rc


if __name__ == "__main__":
    sys.exit(main())
