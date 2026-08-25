#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Group unmodularized ``lib/test/run.sh`` assertion labels by source subject (issue #1928).

Extraction converges on the *subject* an assertion block is about (rather than the hottest
label or a co-edit cluster — see issue #1928 for why those do not): a change to
``skills/review``, ``skills/implement`` or ``scripts/workpad.py`` should have a covering
focused module that runs in seconds, and modules are extracted subject by subject in
descending volume.

This script derives, for every ``lib/test/run.sh`` assertion label that
``lib/test/modules/coverage-map.json`` marks ``unmodularized``, the dominant repository path
its assertions name, and prints the labels grouped by that path with each group's label count.
It reuses ``coverage_map_guard.py``'s label-location primitives (``_LABEL_RE``,
``_assertion_heads``/``_call_pattern``, and ``_git_tracked``) so the two can never disagree
about what a "label" is.

Runnable as a CLI over a repo root:
``python3 lib/test/group_labels_by_subject.py [repo_root] [--json]``
and importable — ``group_labels(...)`` is a pure function over the ``run.sh`` text and a label
filter, so ``test_group_labels_by_subject.py`` can drive it against a synthetic fixture.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

_GUARD_PATH = Path(__file__).resolve().parent / "coverage_map_guard.py"
try:
    _spec = importlib.util.spec_from_file_location("coverage_map_guard", _GUARD_PATH)
    if _spec is None or _spec.loader is None:
        raise ImportError(f"no loadable spec for {_GUARD_PATH}")
    _guard = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_guard)
except Exception as _exc:  # noqa: BLE001 — fail closed naming the reader that could not load
    raise SystemExit(
        f"group_labels_by_subject: the label-location machinery {_GUARD_PATH} could not be "
        f"loaded ({_exc.__class__.__name__}: {_exc}); refusing to group"
    ) from _exc

MAP_REL = "lib/test/modules/coverage-map.json"
RUN_SH_REL = "lib/test/run.sh"
UNMODULARIZED = "unmodularized"

# Group key for a label whose assertion lines name no repository path. Do not drop such
# labels from the output — the extraction must account for every unmodularized label, and
# a silently missing label reads as already extracted.
NO_PATH_KEY = "(no repository path)"

# The recognized top-level directories a repository path can start with. Do not inline
# this set into _path_re — it is a parameter so the unit test drives the matcher against
# a synthetic fixture without depending on the live tree.
DEFAULT_TOP_DIRS = frozenset(
    {
        "skills",
        "scripts",
        "lib",
        "agents",
        "docs",
        ".github",
        ".prflow",
        ".claude",
        ".claude-plugin",
        ".changeset",
        "LICENSES",
    }
)


def _label_re() -> "re.Pattern[str]":
    return _guard._LABEL_RE


@lru_cache(maxsize=None)
def _path_re(top_dirs: "frozenset[str]") -> "re.Pattern[str]":
    """A ``<top-dir>/<rest>`` repository-path matcher for the given top-dir set.

    The trailing character class stops at the first byte that cannot be part of a path
    (a quote, backtick, space, colon, comma), so a path named inside an assertion string
    is captured without its surrounding punctuation. A path must have at least one segment
    after the top directory, so a bare ``skills`` (no slash) is not a path mention.
    """
    alternation = "|".join(sorted((re.escape(d) for d in top_dirs), key=len, reverse=True))
    return re.compile(rf"(?<![\w./-])(?:{alternation})/[\w./-]*[\w]")


def _subject(path: str) -> str:
    """Reduce a repository path to its subject — its first two path components.

    ``skills/review/phases/phase-3-agents.md`` -> ``skills/review`` (a directory subject),
    ``scripts/workpad.py`` -> ``scripts/workpad.py`` (a file, which has only two
    components), ``lib/test/run.sh`` -> ``lib/test`` (the meta-subject). The two-component
    rule is what makes ``skills/review`` and ``scripts/workpad.py`` fall out of the same
    derivation despite one being a directory and the other a file.
    """
    return "/".join(path.split("/")[:2])


@lru_cache(maxsize=None)
def _basename_re(basenames: "frozenset[str]") -> "re.Pattern[str]":
    """A matcher for the given distinctive filename basenames used as bare mentions.

    An assertion routinely names its subject by the bare command/file basename
    (``workpad.py new-body``, ``config-get.sh``, ``phase-3-agents.md``) rather than the
    full repository path, so a path-prefix-only recognizer misses the subject the
    assertion is really about. This matcher is anchored so the basename is a whole token
    (not a suffix of a longer path already caught by the path matcher, and not a substring
    of another identifier).
    """
    if not basenames:
        return re.compile(r"(?!x)x")  # matches nothing
    alternation = "|".join(sorted((re.escape(b) for b in basenames), key=len, reverse=True))
    return re.compile(rf"(?<![\w./-])(?:{alternation})(?![\w-])")


def build_basename_index(paths: "list[str]") -> "dict[str, str]":
    """Map each *distinctive* tracked-file basename to its path's subject.

    A basename shared by more than one preferred path is ambiguous and is dropped rather
    than guessed. "Preferred" excludes the vendored plugin copy (``.prflow/vendor/``) and
    the test tree (``lib/test/``) so a subject-name mention resolves to the real source
    unit, not its vendored duplicate or a test fixture of the same name. When exactly one
    preferred path carries a basename, that basename maps to that path's subject.
    """
    by_basename: "dict[str, set[str]]" = {}
    for path in paths:
        base = path.rsplit("/", 1)[-1]
        by_basename.setdefault(base, set()).add(path)
    index: "dict[str, str]" = {}
    for base, candidates in by_basename.items():
        preferred = {
            p
            for p in candidates
            if not p.startswith(".prflow/vendor/") and not p.startswith("lib/test/")
        }
        pool = preferred or candidates
        subjects = {_subject(p) for p in pool}
        if len(subjects) == 1:
            index[base] = next(iter(subjects))
    return index


def attribute_lines(text: str) -> "list[tuple[str, frozenset[str]]]":
    """Attribute each line of TEXT to the labels of its nearest preceding assertion call.

    Walk the lines in order holding the label set introduced by the most recent assertion
    call (comment lines carry no call, so they inherit the running set). A code line that
    carries an assertion call resets the running set to that call's labels — which is the
    empty set when the nearest call names no ``#NNNN`` label, so a line under an unlabelled
    assertion belongs to no label, exactly as the coverage guard's positional contract
    intends.
    """
    lines = text.split("\n")
    heads = frozenset(_guard._assertion_heads(lines))
    call_re = _guard._call_pattern(heads)
    label_re = _label_re()
    attributed: "list[tuple[str, frozenset[str]]]" = []
    current: "frozenset[str]" = frozenset()
    for line in lines:
        if not line.lstrip().startswith("#"):
            calls = list(call_re.finditer(line))
            if calls:
                found: "set[str]" = set()
                for call in calls:
                    found.update(label_re.findall(call.group(1)))
                current = frozenset(found)
        attributed.append((line, current))
    return attributed


def dominant_subject(
    label_lines: "list[str]",
    top_dirs: "frozenset[str]" = DEFAULT_TOP_DIRS,
    basename_index: "dict[str, str] | None" = None,
) -> str:
    """The subject the label's lines most name, or NO_PATH_KEY when they name no path.

    Every repository-path mention across LABEL_LINES is reduced to its subject and tallied,
    and — when BASENAME_INDEX is given — every bare distinctive-filename mention is tallied
    to its indexed subject as well. The most-mentioned subject wins, ties broken
    lexicographically so the result is deterministic. A label whose lines name no
    repository path and no indexed basename returns NO_PATH_KEY.
    """
    path_re = _path_re(top_dirs)
    subjects: "Counter[str]" = Counter()
    base_re = _basename_re(frozenset(basename_index)) if basename_index else None
    for line in label_lines:
        for match in path_re.finditer(line):
            subjects[_subject(match.group(0))] += 1
        if base_re is not None:
            for match in base_re.finditer(line):
                subjects[basename_index[match.group(0)]] += 1  # type: ignore[index]
    if not subjects:
        return NO_PATH_KEY
    top = max(subjects.values())
    return min(subject for subject, count in subjects.items() if count == top)


def group_labels(
    text: str,
    restrict: "set[str] | None" = None,
    top_dirs: "frozenset[str]" = DEFAULT_TOP_DIRS,
    basename_index: "dict[str, str] | None" = None,
) -> "dict[str, list[str]]":
    """Group the labels of TEXT by their dominant subject.

    RESTRICT, when given, limits the grouping to that set of labels (the unmodularized
    set); when ``None`` every label the text asserts is grouped. BASENAME_INDEX, when
    given, resolves bare filename mentions to their subject. Returns ``subject -> sorted
    label list``.
    """
    per_label_lines: "dict[str, list[str]]" = {}
    for line, labels in attribute_lines(text):
        for label in labels:
            if restrict is not None and label not in restrict:
                continue
            per_label_lines.setdefault(label, []).append(line)
    groups: "dict[str, list[str]]" = {}
    for label, lines in per_label_lines.items():
        subject = dominant_subject(lines, top_dirs, basename_index)
        groups.setdefault(subject, []).append(label)
    for labels in groups.values():
        labels.sort(key=int)
    return groups


def _sorted_groups(groups: "dict[str, list[str]]") -> "list[tuple[str, list[str]]]":
    """Groups ordered by descending label count, then subject ascending — deterministic."""
    return sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))


def unmodularized_labels(coverage_map: dict) -> "set[str]":
    """The set of ``run_sh_blocks`` labels the coverage map marks ``unmodularized``."""
    blocks = coverage_map.get("run_sh_blocks", {})
    return {
        label
        for label, entry in blocks.items()
        if isinstance(entry, dict) and entry.get("owner") == UNMODULARIZED
    }


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_root", nargs="?", default=".", help="repository root (default: cwd)")
    parser.add_argument("--json", action="store_true", help="emit the grouping as JSON")
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve()
    try:
        coverage_map = json.loads((root / MAP_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"group_labels_by_subject: cannot read {MAP_REL}: {exc}", file=sys.stderr)
        return 2
    try:
        run_sh_text = (root / RUN_SH_REL).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"group_labels_by_subject: cannot read {RUN_SH_REL}: {exc}", file=sys.stderr)
        return 2

    # Fail closed on a coverage-map that lacks a usable run_sh_blocks dict — a schema rename
    # or a corrupted file would otherwise make `restrict` empty and emit a silent, empty
    # grouping that reads identically to the legitimate "nothing is unmodularized" result.
    if not isinstance(coverage_map, dict) or not isinstance(
        coverage_map.get("run_sh_blocks"), dict
    ):
        print(
            f"group_labels_by_subject: {MAP_REL} has no usable 'run_sh_blocks' dict "
            "(schema drift?); refusing to emit an empty grouping",
            file=sys.stderr,
        )
        return 2
    restrict = unmodularized_labels(coverage_map)
    try:
        tracked = _guard._git_tracked(root)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(
            f"group_labels_by_subject: cannot enumerate tracked files under {root}: {exc}",
            file=sys.stderr,
        )
        return 2
    if not tracked:
        print(
            f"group_labels_by_subject: git reports no tracked files under {root}; "
            "bare-basename mentions will not resolve (full-path mentions still group)",
            file=sys.stderr,
        )
    basename_index = build_basename_index(tracked)
    groups = group_labels(run_sh_text, restrict=restrict, basename_index=basename_index)
    ordered = _sorted_groups(groups)

    if args.json:
        print(json.dumps({subject: labels for subject, labels in ordered}, indent=2))
        return 0

    for subject, labels in ordered:
        print(f"{subject} ({len(labels)} labels): {' '.join('#' + label for label in labels)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
