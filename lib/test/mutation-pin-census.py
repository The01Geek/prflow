#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Build an opaque census of legacy mutation-pin calls.

The census deliberately treats every call as text.  It never executes or
interprets a mutation, resolves a target, or attempts semantic classification.
"""

from __future__ import annotations

import argparse
import ast
import functools
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


HELPERS = (
    "assert_pin_red_under",
    "devflow_module_pin_red_under",
    "assert_count_red_under",
    "_ra_conflict_red_under",
)
RETAINED_BOUNDARY_IDENTITIES = frozenset()
EXPECTED_SOURCE_COUNT = 19
NON_UTF8_SHELL_FIXTURES = frozenset(
    {"lib/test/fixtures/ghapi-repo-path/adversarial-nonutf8.sh"}
)
_WORD = r"[A-Za-z_][A-Za-z0-9_]*"
_DEFINITION_RE = {
    helper: re.compile(
        rf"^\s*(?:{helper}\s*\(\s*\)|"
        rf"function\s+{helper}(?:\s*\(\s*\))?)\s*\{{"
    )
    for helper in HELPERS
}
_DEFINITION_TEXT_RE = {
    helper: re.compile(
        rf"(?m)^[ \t]*(?:{helper}[ \t]*\([ \t]*\)|"
        rf"function[ \t]+{helper}(?:[ \t]*\([ \t]*\))?)[ \t]*"
        rf"(?:(?:#[^\n]*)?\n[ \t]*)*\{{"
    )
    for helper in HELPERS
}
_ASSIGNMENT = rf"(?:{_WORD})=(?:'(?:[^']*)'|\"(?:\\.|[^\"])*\"|\S+)"
_REDIRECTION = r"[0-9]*(?:<>|>>|>|<<|<)\S*"
_DIRECT_CALL_RE = re.compile(
    rf"^\s*(?:(?:{_ASSIGNMENT}|{_REDIRECTION})\s+)*"
    rf"(?P<helper>{'|'.join(HELPERS)})(?=\s|$)"
)
_PROBE_CALL_RE = re.compile(
    rf"^\s*(?:probe_assert|_acru_probe|probe_two_line)\s+"
    rf"(?P<helper>{'|'.join(HELPERS)})(?=\s|$)"
)
_SHELL_TOKEN_RE = re.compile(r"&&|\|\||;;|[;|&(){}!]|[^\s;|&(){}!]+")


class CensusError(RuntimeError):
    """The census population could not be established reliably."""


@dataclass(frozen=True)
class CensusRow:
    path: str
    helper: str
    logical_call: str
    line_start: int
    line_end: int

    @property
    def identity(self) -> str:
        """Opaque identity; source locations are intentionally not included."""
        return json.dumps(
            [self.path, self.helper, self.logical_call],
            ensure_ascii=False,
            separators=(",", ":"),
        )


@dataclass(frozen=True)
class CensusResult:
    sources: tuple[str, ...]
    rows: tuple[CensusRow, ...]
    master_sha256: str

    def helper_count(self, helper: str) -> int:
        return sum(row.helper == helper for row in self.rows)

    def identity_bytes(self) -> bytes:
        if not self.rows:
            return b""
        return ("".join(f"{row.identity}\n" for row in self.rows)).encode("utf-8")


@dataclass(frozen=True)
class Adjudication:
    disposition: str
    rationale: str


@dataclass(frozen=True)
class _LogicalLine:
    text: str
    physical: str
    line_start: int
    line_end: int


def _read_utf8(path: Path, description: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CensusError(f"missing {description}: {path}") from exc
    except UnicodeDecodeError as exc:
        raise CensusError(f"{description} is not valid UTF-8: {path}") from exc
    except OSError as exc:
        raise CensusError(f"cannot read {description}: {path}: {exc}") from exc


def _audited_sources(repo_root: Path) -> tuple[str, ...]:
    linter = repo_root / "lib/test/pin-corpus-lint.py"
    text = _read_utf8(linter, "pin-corpus linter")
    try:
        tree = ast.parse(text, filename=str(linter))
    except SyntaxError as exc:
        raise CensusError(f"cannot parse AUDITED_PIN_SOURCES: {exc}") from exc

    values: list[ast.expr] = []
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(
            isinstance(target, ast.Name) and target.id == "AUDITED_PIN_SOURCES"
            for target in targets
        ):
            continue
        value = node.value
        if value is not None:
            values.append(value)
    if len(values) != 1:
        raise CensusError(
            "AUDITED_PIN_SOURCES must have exactly one top-level definition"
        )

    value = values[0]
    if not (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "frozenset"
        and len(value.args) == 1
        and not value.keywords
    ):
        raise CensusError("AUDITED_PIN_SOURCES must be a literal frozenset")
    literal = value.args[0]
    if not isinstance(literal, ast.Set):
        raise CensusError("AUDITED_PIN_SOURCES is not a literal string set")
    entries = tuple(
        element.value
        for element in literal.elts
        if isinstance(element, ast.Constant)
        and isinstance(element.value, str)
        and element.value
    )
    if len(entries) != len(literal.elts):
        raise CensusError("AUDITED_PIN_SOURCES is not a literal string set")
    if len(entries) != len(set(entries)):
        raise CensusError("duplicate audited population entry")
    if len(entries) != EXPECTED_SOURCE_COUNT:
        raise CensusError(
            "audited population count disagreement: "
            f"expected {EXPECTED_SOURCE_COUNT}, found {len(entries)}"
        )
    return tuple(sorted(entries))


# Bound on the per-source parse memos below.
#
# The reuse this buys is a WITHIN-census repeat: the definition sweep parses
# every tracked shell source under lib/test, and the row extraction afterwards
# parses the audited subset again. What has to fit for that second parse to hit
# is NOT the audited set — the sweep is ordered and never revisits an entry, so
# an audited source whose parse happened early is evicted by the non-audited
# ones sorting after it, long before the extraction asks for it again. What has
# to fit is the whole set the sweep visits. Sizing this against the audited count instead was
# measured wrong: at a bound of 15 the audited 13 still "fit" and 12 of the 13
# repeat parses did not hit.
#
# So the bound clears the tracked shell sources one sweep visits. The headroom
# over that population is only a few files, and this repo adds one whenever a
# durable test module is extracted — so expect to raise this bound rather than
# treating it as sized for years of growth. Outgrowing it costs no correctness:
# an evicted entry is recomputed, never answered wrongly. It costs the reuse,
# which is why test_census_reuses_every_audited_source_within_one_build pins the
# hit count against the audited set and names raising this bound as the remedy.
#
# Reuse ACROSS censuses is a smaller, secondary win, and deliberately not what
# this bound is sized for: the suite driver launches one process per test
# (issue #870), so nothing here survives into another test. It pays only where a
# single test scans repeatedly — the subTest-looping tests in
# test_pin_corpus_lint.py do, which is most of that file's scans — and it costs
# nothing to collect where it does not.
#
# Measured 2026-07-28 on an arm64 laptop against this file's heaviest single
# worker: this bound costs roughly 90MB of peak RSS over one sized to the
# audited set alone, for the same 13 within-census hits on the tree as it stood
# at that run. Past-time snapshot of that run.
#
# Bound raise, 2026-08-02 (issue #1072). Note the wording here avoids the bare
# tokens `sed` and `grep` followed by a space: this module carries an executable
# guard (test_census_does_not_spawn_or_interpret_mutation_tools) that scans its
# own source for them, and a past participle of "raise" collides with the first.
# The shipped-pruned-path lint's fixture corpus
# adds nine tracked shell sources under lib/test/fixtures/shipped-pruned-path/,
# taking the population the sweep parses from 51 to 60 — past the old bound of
# 56, so every entry was evicted before the extraction asked for it again and
# test_census_outer_memos_are_reused_across_builds went RED with zero hits on
# _definition_scan, exactly as its remedy text predicts. The reception pass that
# followed added five more fixture slices for the lint's refusal arms, taking the
# population to 65, so the bound was 70: five above the swept population, the same
# few-files headroom the paragraph above describes (the prior 56 stood 5 above a
# population of 51). Sizing it AT the population would leave zero headroom and turn
# the next added shell source RED.
#
# Bound raise, issue #1309 (docs.* default exemption). The exemption's fixture
# corpus adds four tracked shell sources under
# lib/test/fixtures/shipped-pruned-path/slices/, taking the swept population from
# 68 to 72 — past the old bound of 70, so entries were evicted before extraction
# re-asked for them and test_census_outer_memos_are_reused_across_builds went RED
# with zero hits, exactly as its remedy text predicts. The bound is now 76: four
# above the swept population, preserving a few files of headroom.
#
# Bound raise, issue #1402 (never-shipped-workflow forbidden class). The class's
# refusal arms need their own installer fixtures, which add eight tracked shell
# sources under lib/test/fixtures/shipped-pruned-path/installs/, taking the swept
# population from 71 to 79 — past the old bound of 76, so entries were evicted
# before extraction re-asked for them and
# test_census_outer_memos_are_reused_across_builds went RED with zero hits on
# _definition_scan, exactly as its remedy text predicts.
#
# Bound raise, issue #1524 (negated-compound-redirect lint). That lint's fixture
# corpus adds seventeen tracked shell sources under
# lib/test/fixtures/lint-negated-compound-redirect/, taking the swept population
# from 80 to 97 — past the old bound of 84, tripping the same memo-reuse contract.
# The bound is now 102: five above the swept population, the same few-files
# headroom the raises above kept.
_SOURCE_PARSE_CACHE_SIZE = 102


@functools.lru_cache(maxsize=_SOURCE_PARSE_CACHE_SIZE)
def _logical_lines(text: str, path: str) -> tuple[_LogicalLine, ...]:
    """Decompose ``text`` into continuation-joined logical lines.

    The result is a tuple of frozen records, so the memo can share one
    immutable object instead of returning a defensive copy.
    """
    physical = text.splitlines()
    output: list[_LogicalLine] = []
    index = 0
    while index < len(physical):
        start = index + 1
        pieces: list[str] = []
        while True:
            line = physical[index]
            trailing = len(line) - len(line.rstrip("\\"))
            continued = trailing % 2 == 1
            pieces.append(line[:-1] if continued else line)
            if not continued:
                break
            index += 1
            if index >= len(physical):
                raise CensusError(
                    f"unterminated continuation in {path}:{start}"
                )
        normalized = " ".join(piece.strip() for piece in pieces)
        output.append(
            _LogicalLine(
                normalized,
                "\n".join(physical[start - 1 : index + 1]),
                start,
                index + 1,
            )
        )
        index += 1
    return tuple(output)


def _shell_segments(text: str) -> tuple[str, ...]:
    """Split an already joined line at unquoted shell command separators."""
    segments: list[str] = []
    start = 0
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if quote == "'":
            if char == "'":
                quote = None
            index += 1
            continue
        if quote == '"':
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = None
            index += 1
            continue
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\":
            escaped = True
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if char == "#":
            if index == 0 or text[index - 1].isspace():
                text = text[:index]
                break
        separator_length = 0
        if char == ";":
            separator_length = 1
        elif char == "|":
            separator_length = 2 if text[index : index + 2] == "||" else 1
        elif char == "&" and text[index : index + 2] == "&&":
            separator_length = 2
        if separator_length:
            segments.append(text[start:index])
            index += separator_length
            start = index
            continue
        index += 1
    segments.append(text[start:])
    return tuple(segment for segment in segments if segment.strip())


def _unquoted_shell_tokens(segment: str) -> tuple[str, ...]:
    visible: list[str] = []
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(segment):
        char = segment[index]
        if quote == "'":
            visible.append(" ")
            if char == "'":
                quote = None
            index += 1
            continue
        if quote == '"':
            visible.append(" ")
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = None
            index += 1
            continue
        if escaped:
            visible.append(" ")
            escaped = False
            index += 1
            continue
        if char == "\\":
            visible.append(" ")
            escaped = True
            index += 1
            continue
        if char in {"'", '"'}:
            visible.append(" ")
            quote = char
            index += 1
            continue
        if char == "#" and (index == 0 or segment[index - 1].isspace()):
            break
        visible.append(char)
        index += 1
    return tuple(_SHELL_TOKEN_RE.findall("".join(visible)))


def _lexical_helper_count(segment: str) -> int:
    return sum(token in HELPERS for token in _unquoted_shell_tokens(segment))


def _definition_counts(
    repo_root: Path, audited_sources: frozenset[str]
) -> dict[str, int]:
    counts = dict.fromkeys(HELPERS, 0)
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z", "--", "lib/test"],
            cwd=repo_root,
            capture_output=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CensusError(
            f"cannot enumerate tracked helper definitions: {exc}"
        ) from exc
    if result.returncode != 0:
        stderr = (
            result.stderr.decode("utf-8", errors="replace")
            if isinstance(result.stderr, bytes)
            else result.stderr
        ).strip()
        raise CensusError(
            "tracked helper-definition enumeration failed "
            f"(exit {result.returncode}): {stderr or '(no stderr)'}"
        )
    if not result.stdout or not result.stdout.endswith(b"\0"):
        raise CensusError(
            "tracked helper-definition enumeration is empty or malformed"
        )
    raw_paths = result.stdout[:-1].split(b"\0")
    try:
        relative_paths = [raw.decode("utf-8") for raw in raw_paths]
    except UnicodeDecodeError as exc:
        raise CensusError(
            "tracked helper-definition path is not valid UTF-8"
        ) from exc
    if (
        any(not path or "\0" in path for path in relative_paths)
        or len(relative_paths) != len(set(relative_paths))
    ):
        raise CensusError(
            "tracked helper-definition enumeration contains malformed or "
            "duplicate paths"
        )
    paths = [
        repo_root / relative
        for relative in sorted(relative_paths)
        if relative.startswith("lib/test/") and relative.endswith(".sh")
    ]
    if not paths:
        raise CensusError(
            "tracked helper-definition enumeration selected no shell sources"
        )
    for path in paths:
        relative = path.relative_to(repo_root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            if relative in NON_UTF8_SHELL_FIXTURES:
                try:
                    raw = path.read_bytes()
                except OSError as read_error:
                    raise CensusError(
                        f"cannot read tracked test shell fixture: {path}: "
                        f"{read_error}"
                    ) from read_error
                if not any(helper.encode("ascii") in raw for helper in HELPERS):
                    continue
            raise CensusError(
                f"tracked test shell source is not valid UTF-8: {path}"
            ) from exc
        except OSError as exc:
            raise CensusError(f"cannot read test shell source: {path}: {exc}") from exc
        path_counts, path_lexical_count = _definition_scan(relative, text)
        path_definition_count = 0
        for helper, count in path_counts:
            counts[helper] += count
            path_definition_count += count
        if (
            relative not in audited_sources
            and path_lexical_count != path_definition_count
        ):
            raise CensusError(
                "unclassified supported helper token in tracked test shell "
                f"source: {relative}: lexical={path_lexical_count}, "
                f"definitions={path_definition_count}"
            )
    return counts


@functools.lru_cache(maxsize=_SOURCE_PARSE_CACHE_SIZE)
def _definition_scan(
    relative: str, text: str
) -> tuple[tuple[tuple[str, int], ...], int]:
    """Count this source's helper definitions and lexical helper tokens.

    Returns ``(per-helper definition counts, lexical token total)``; the
    definition total the caller compares against is the sum of the counts, so
    it is derived there rather than returned twice. Split out of
    :func:`_definition_counts` so the derivation is a
    pure function of the source's own name and text, and therefore memoizable
    across the repeated censuses a single process builds. Only the name and the
    text reach the key; the caller keeps the accumulation and the
    audited-source reconciliation, which depend on the whole run.
    """
    path_counts: list[tuple[str, int]] = []
    for helper, pattern in _DEFINITION_TEXT_RE.items():
        path_counts.append((helper, sum(1 for _ in pattern.finditer(text))))
    path_lexical_count = 0
    for logical in _logical_lines(text, relative):
        for segment in _shell_segments(logical.physical):
            lexical = _lexical_helper_count(segment)
            path_lexical_count += lexical
            definitions = [
                helper
                for helper, pattern in _DEFINITION_RE.items()
                if pattern.match(segment)
            ]
            if definitions and lexical != len(definitions):
                raise CensusError(
                    "supported helper token shares a definition segment: "
                    f"{relative}:{logical.line_start}"
                )
    return tuple(path_counts), path_lexical_count


def _extract_source(repo_root: Path, source: str) -> tuple[CensusRow, ...]:
    return _extract_rows(source, _read_utf8(repo_root / source, "audited source"))


@functools.lru_cache(maxsize=_SOURCE_PARSE_CACHE_SIZE)
def _extract_rows(source: str, text: str) -> tuple[CensusRow, ...]:
    """Extract this source's census rows from its own name and text.

    Split out of :func:`_extract_source` for the same reason as
    :func:`_definition_scan`: the row derivation reads nothing but the name and
    the text, so it is memoizable across censuses, while the file read that
    supplies the text stays with the caller that knows the repository root.
    """
    rows: list[CensusRow] = []
    for logical in _logical_lines(text, source):
        lexical = 0
        extracted: list[CensusRow] = []
        for segment in _shell_segments(logical.physical):
            if any(pattern.match(segment) for pattern in _DEFINITION_RE.values()):
                continue
            segment_lexical = _lexical_helper_count(segment)
            lexical += segment_lexical
            direct_match = _DIRECT_CALL_RE.match(segment) or _PROBE_CALL_RE.match(
                segment
            )
            if not direct_match or segment_lexical == 0:
                continue
            helper = direct_match.group("helper")
            extracted.append(
                CensusRow(
                    path=source,
                    helper=helper,
                    logical_call=segment,
                    line_start=logical.line_start,
                    line_end=logical.line_end,
                )
            )
        if len(extracted) > 1:
            raise CensusError(
                f"multiple supported calls on one logical line: "
                f"{source}:{logical.line_start}"
            )
        if lexical != len(extracted):
            raise CensusError(
                f"lexical/extracted population disagreement at "
                f"{source}:{logical.line_start}: lexical={lexical}, "
                f"extracted={len(extracted)}"
            )
        rows.extend(extracted)
    return tuple(rows)


def build_census(repo_root: Path | str) -> CensusResult:
    root = Path(repo_root).resolve()
    sources = _audited_sources(root)
    for source in sources:
        if not (root / source).is_file():
            raise CensusError(f"missing audited source: {source}")

    definition_counts = _definition_counts(root, frozenset(sources))
    unexpected = {
        helper: count for helper, count in definition_counts.items() if count != 0
    }
    if unexpected:
        details = ", ".join(
            f"{helper}={count}" for helper, count in sorted(unexpected.items())
        )
        raise CensusError(
            f"unexpected helper definition count (expected zero): {details}"
        )

    rows = sorted(
        (
            row
            for source in sources
            for row in _extract_source(root, source)
        ),
        key=lambda row: row.identity,
    )
    identities = [row.identity for row in rows]
    duplicate = next(
        (
            identity
            for index, identity in enumerate(identities[1:], start=1)
            if identity == identities[index - 1]
        ),
        None,
    )
    if duplicate is not None:
        raise CensusError(f"duplicate identity: {duplicate}")

    provisional = CensusResult(sources=sources, rows=tuple(rows), master_sha256="")
    digest = hashlib.sha256(provisional.identity_bytes()).hexdigest()
    return CensusResult(
        sources=sources,
        rows=tuple(rows),
        master_sha256=digest,
    )


def _identity_sha256(row: CensusRow) -> str:
    return hashlib.sha256(row.identity.encode("utf-8")).hexdigest()


def adjudicate(row: CensusRow) -> Adjudication:
    return Adjudication(
        "reject_unadjudicated_mutation_site",
        "mutation-taking helpers are retired; write an executable behavioral test",
    )


def render_jsonl(result: CensusResult) -> str:
    lines = [
        json.dumps(
            {
                "path": row.path,
                "helper": row.helper,
                "logical_call": row.logical_call,
                "line_start": row.line_start,
                "line_end": row.line_end,
                "identity_sha256": _identity_sha256(row),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for row in result.rows
    ]
    lines.append(
        json.dumps(
            {"master_sha256": result.master_sha256},
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return "\n".join(lines) + "\n"


def _validate_source_revision(source_revision: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40,64}", source_revision):
        raise CensusError("source revision must be a full hexadecimal object ID")


def render_tsv(
    result: CensusResult, source_revision: str | None = None
) -> str:
    lines: list[str] = []
    if source_revision is not None:
        _validate_source_revision(source_revision)
        lines.append(f"# source_revision\t{source_revision}")
    lines.append(
        "path\thelper\tlogical_call\tline_start\tline_end\tidentity_sha256"
    )
    for row in result.rows:
        call = json.dumps(row.logical_call, ensure_ascii=False)
        identity_digest = _identity_sha256(row)
        lines.append(
            f"{row.path}\t{row.helper}\t{call}\t{row.line_start}\t"
            f"{row.line_end}\t{identity_digest}"
        )
    lines.append(f"# master_sha256\t{result.master_sha256}")
    return "\n".join(lines) + "\n"


def render_adjudication_tsv(
    result: CensusResult, source_revision: str
) -> str:
    _validate_source_revision(source_revision)
    lines = [
        f"# source_revision\t{source_revision}",
        f"# master_sha256\t{result.master_sha256}",
        (
            "path\thelper\tlogical_call\tline_start\tline_end\t"
            "identity_sha256\tdisposition\trationale"
        ),
    ]
    for row in result.rows:
        decision = adjudicate(row)
        lines.append(
            f"{row.path}\t{row.helper}\t"
            f"{json.dumps(row.logical_call, ensure_ascii=False)}\t"
            f"{row.line_start}\t{row.line_end}\t{_identity_sha256(row)}\t"
            f"{decision.disposition}\t{decision.rationale}"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument(
        "--format",
        choices=("jsonl", "tsv", "adjudication-tsv"),
        default="jsonl",
    )
    parser.add_argument("--source-revision")
    args = parser.parse_args(argv)
    try:
        result = build_census(args.repo_root)
        if args.format == "adjudication-tsv" and not args.source_revision:
            raise CensusError(
                "adjudication-tsv requires --source-revision"
            )
    except CensusError as exc:
        print(f"mutation-pin-census: infrastructure failure: {exc}", file=sys.stderr)
        return 2
    if args.format == "jsonl":
        output = render_jsonl(result)
    elif args.format == "tsv":
        output = render_tsv(result, args.source_revision)
    else:
        output = render_adjudication_tsv(result, args.source_revision)
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
