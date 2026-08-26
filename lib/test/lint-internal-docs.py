#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Structure lint for the internal documentation tree (`docs/internal/`).

`docs/internal/architecture/internal-documentation-architecture.md` states
validation rules for the internal-docs corpus — every index link resolves, pages
follow the canonical section contract, and so on — and until this lint nothing
enforced any of them, which is how 80+ unlinked pages, dead placeholder links and
four duplicate basenames accumulated unnoticed. This lint makes those promises
mechanical.

Checks, each independently reported with its own key prefix:

* ``broken-link``       — a relative markdown link in a `docs/internal/**.md` file
                          whose target does not resolve to a tracked file.
* ``placeholder-link``  — a link whose text or target is an unfilled template
                          (`[...](...)`, `[…](<this run's URL>)`).
* ``glob-reference``    — a `docs/internal/…` path reference containing a literal
                          `*`, which no reader can follow.
* ``duplicate-basename``— one `.md` basename living in two directories under
                          `docs/internal/` (`index.md` exempt: every category
                          index shares it by design).
* ``orphan``            — a `docs/internal/**.md` file with no inbound reference
                          (markdown link or full-path mention) from the rest of
                          the docs tree, `CLAUDE.md`, `CONTRIBUTING.md`, `lib/`,
                          `scripts/`, or `.github/`.
* ``missing-sections``  — a canonical-layer page (under `architecture/`,
                          `skills/`, `workflows/`, `operations/`, `agents/`,
                          `improvement-loops/`; `index.md` files exempt) missing
                          one of the five contract H2s.
* long lines            — a prose line over 2,000 characters (fenced code blocks
                          and `*.observed.md` raw artifacts exempt); tracked as a
                          per-file COUNT rather than a keyed violation, failing
                          only when a file's count exceeds its baseline count.
* oversize (ADVISORY)   — a file over 60,000 bytes (roughly one Read-tool call);
                          reported, never failing.
* ``tracked-private``   — a tracked file matching `*.private.md` (the suffix
                          means "never committed"; enforcement is the `.gitignore`
                          `*.private.md` line, whose presence is also asserted and
                          whose absence fails closed with no baseline escape).

Baseline contract (the load-bearing design choice): the checked-in baseline
`lib/test/internal-docs-baseline.json` records the violations present when the
lint landed, and the lint exits non-zero ONLY for a violation not in the
baseline (or a long-line count above the recorded one). A baseline entry that no
longer violates is reported as an ADVISORY note and never a failure — DELIBERATE,
so that this lint and the corpus-repair work can land in either order without
one turning the other red; a later change may tighten stale entries to failures
once the corpus is repaired. Regenerate with ``--write-baseline`` after a repair.

Accepted residuals, each deliberate:

* Link extraction is a single regex over the raw text; a link split across lines,
  a target containing an unescaped `)`, and reference-style `[text][ref]` links
  are not seen. Fenced code blocks are NOT exempt from link extraction — a fenced
  dead link misleads a reader the same way — but are exempt from the line-length
  rule, whose cost is mechanical rather than semantic.
* The orphan check's inbound-reference test is textual: a full-path substring
  anywhere in the reference corpus, or a relative markdown link from another
  docs page that resolves to the file. A reference by bare basename, by a
  variable-assembled path, or from a surface outside the enumerated corpus is
  not counted, so the check can over-report (a baseline/advisory matter), never
  under-report an orphan into a false failure.
* ``missing-sections`` is keyed per file, not per missing section, so a
  baselined page that later loses a SECOND section does not re-fire. Stability
  of the key across partial fixes was chosen over that sensitivity.
* The long-line COUNT semantics mean a file that swaps one over-limit line for
  another at the same count is not caught; only growth is.
* The population is index-reading `git ls-files` (issue #711), so an untracked
  working file is invisible until added to the index.

Usage:
    lint-internal-docs.py [--root DIR] [--files-from PATH] [--baseline PATH]
                          [--write-baseline] [--self-test]

Exit 0 = no NEW violation (advisories and stale-baseline notes may print).
Exit 1 = a new violation, an unusable enumeration, an unreadable selected file,
or a missing `.gitignore` `*.private.md` line.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

_POP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lint_population.py")
_pop_spec = importlib.util.spec_from_file_location("lint_population", _POP_PATH)
_pop = importlib.util.module_from_spec(_pop_spec)
try:
    _pop_spec.loader.exec_module(_pop)
except Exception as _exc:
    raise SystemExit(
        f"lint-internal-docs: the shared population reader {_POP_PATH} could not "
        f"be loaded ({_exc.__class__.__name__}: {_exc}); refusing to audit"
    ) from _exc
_REQUIRED_POP_ATTRS = (
    "EnumerationError", "enumerate_population", "read_source",
    "add_population_arguments", "resolve_root", "LS_FILES_INDEX",
)
_pop_missing = [name for name in _REQUIRED_POP_ATTRS if not hasattr(_pop, name)]
if _pop_missing:
    raise SystemExit(
        f"lint-internal-docs: {_POP_PATH} no longer provides "
        f"{', '.join(_pop_missing)}; refusing to audit"
    )

EnumerationError = _pop.EnumerationError

DOCS_PREFIX = "docs/internal/"
CANONICAL_DIRS = (
    "architecture", "skills", "workflows", "operations", "agents", "improvement-loops",
)
REQUIRED_SECTIONS = (
    "## Current behavior",
    "## Why it works this way",
    "## Boundaries and failure paths",
    "## Source of truth",
    "## Related topics",
)
#: Prefixes (beyond the docs tree itself) whose tracked text files count as
#: inbound-reference sources for the orphan check.
REFERENCE_PREFIXES = ("lib/", "scripts/", ".github/")
REFERENCE_FILES = ("CLAUDE.md", "CONTRIBUTING.md")
LINE_LIMIT = 2000
SIZE_ADVISORY = 60000
DEFAULT_BASELINE = "lib/test/internal-docs-baseline.json"

_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
_GLOB_REF_RE = re.compile(r"docs/internal/[^`\s)]*\*[^`\s)]*")
_EXTERNAL_TARGET = re.compile(r"^(https?:|mailto:|#)")


def _is_placeholder(text: str, target: str) -> bool:
    stripped = target.strip()
    return text.strip() in ("...", "…") or stripped.startswith("<") or stripped in ("...", "…")


def _resolve(source: str, target: str) -> str | None:
    """Resolve a relative link target against its source file, repo-rooted."""
    cleaned = target.split("#", 1)[0].strip()
    if not cleaned:
        return None
    base = os.path.dirname(source)
    resolved = os.path.normpath(os.path.join(base, cleaned))
    return resolved.replace("\\", "/")


def _strip_fences(text: str) -> list[tuple[int, str, bool]]:
    """Return `(1-based line number, line, in_fence)` triples."""
    rows: list[tuple[int, str, bool]] = []
    fenced = False
    for number, line in enumerate(text.split("\n"), start=1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            rows.append((number, line, True))
            continue
        rows.append((number, line, fenced))
    return rows


def check_corpus(
    docs: dict[str, str],
    tracked: set[str],
    reference_texts: dict[str, str],
) -> tuple[set[str], dict[str, int], list[str]]:
    """Run every check over the corpus.

    `docs` maps each tracked `docs/internal/**.md` path to its text; `tracked` is
    the full tracked-path set; `reference_texts` maps every inbound-reference
    source (docs included) to its text. Returns `(violation keys, long-line
    counts, advisories)`.
    """
    violations: set[str] = set()
    long_lines: dict[str, int] = {}
    advisories: list[str] = []

    resolved_links: dict[str, set[str]] = {}
    for path, text in docs.items():
        for match in _LINK_RE.finditer(text):
            link_text, target = match.group(1), match.group(2)
            if _is_placeholder(link_text, target):
                violations.add(f"placeholder-link:{path}:{target.strip()}")
                continue
            if _EXTERNAL_TARGET.match(target.strip()):
                continue
            resolved = _resolve(path, target)
            if resolved is None:
                continue
            resolved_links.setdefault(path, set()).add(resolved)
            if resolved not in tracked:
                violations.add(f"broken-link:{path}:{target.strip()}")
        for match in _GLOB_REF_RE.finditer(text):
            violations.add(f"glob-reference:{path}:{match.group(0)}")

    by_basename: dict[str, set[str]] = {}
    for path in docs:
        name = os.path.basename(path)
        if name == "index.md":
            continue
        by_basename.setdefault(name, set()).add(os.path.dirname(path))
    for name, dirs in by_basename.items():
        if len(dirs) > 1:
            violations.add(f"duplicate-basename:{name}")

    for path in docs:
        referenced = False
        for source, links in resolved_links.items():
            if source != path and path in links:
                referenced = True
                break
        if not referenced:
            for source, text in reference_texts.items():
                if source != path and path in text:
                    referenced = True
                    break
        if not referenced:
            violations.add(f"orphan:{path}")

    for path, text in docs.items():
        relative = path[len(DOCS_PREFIX):]
        parts = relative.split("/")
        if (
            len(parts) == 2
            and parts[0] in CANONICAL_DIRS
            and parts[1] != "index.md"
        ):
            missing = [s for s in REQUIRED_SECTIONS if s not in text]
            if missing:
                violations.add(f"missing-sections:{path}")

    for path, text in docs.items():
        if path.endswith(".observed.md"):
            continue
        count = sum(
            1
            for _, line, fenced in _strip_fences(text)
            if not fenced and len(line) > LINE_LIMIT
        )
        if count:
            long_lines[path] = count

    for path, text in docs.items():
        size = len(text.encode("utf-8", errors="replace"))
        if size > SIZE_ADVISORY:
            advisories.append(
                f"advisory: {path} is {size} bytes (over the ~{SIZE_ADVISORY}-byte single-read budget)"
            )

    return violations, long_lines, advisories


def load_baseline(path: Path) -> tuple[set[str], dict[str, int]]:
    if not path.exists():
        return set(), {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return set(data.get("violations", [])), dict(data.get("long_lines", {}))


def write_baseline(path: Path, violations: set[str], long_lines: dict[str, int]) -> None:
    payload = {
        "schema": 1,
        "violations": sorted(violations),
        "long_lines": {k: long_lines[k] for k in sorted(long_lines)},
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def self_test() -> int:
    """RED/GREEN cases per check, over synthetic corpora (no git, no filesystem)."""
    failures: list[str] = []

    def run(docs, tracked_extra=(), refs=None):
        tracked = set(docs) | set(tracked_extra)
        reference = dict(docs)
        reference.update(refs or {})
        return check_corpus(docs, tracked, reference)

    linked = {"docs/internal/index.md": "[a](architecture/a.md)",
              "docs/internal/architecture/a.md": "body [up](../index.md)"}
    v, _, _ = run(linked)
    if any(k.startswith(("broken-link", "orphan")) for k in v):
        failures.append(f"GREEN resolved-link corpus fired: {sorted(v)}")

    v, _, _ = run({"docs/internal/index.md": "[a](architecture/missing.md)"})
    if "broken-link:docs/internal/index.md:architecture/missing.md" not in v:
        failures.append("RED broken-link not reported")

    v, _, _ = run({"docs/internal/index.md": "[...](...) and [x](<this run's URL>)"})
    if not any(k.startswith("placeholder-link") for k in v):
        failures.append("RED placeholder-link not reported")

    v, _, _ = run({"docs/internal/a.md": "see `docs/internal/claude-md-*.md` records"})
    if not any(k.startswith("glob-reference") for k in v):
        failures.append("RED glob-reference not reported")

    v, _, _ = run({"docs/internal/x/same.md": "a", "docs/internal/y/same.md": "b"})
    if "duplicate-basename:same.md" not in v:
        failures.append("RED duplicate-basename not reported")
    v, _, _ = run({"docs/internal/x/index.md": "a", "docs/internal/y/index.md": "b"})
    if any(k.startswith("duplicate-basename") for k in v):
        failures.append("GREEN index.md basename exemption fired")

    v, _, _ = run(
        {"docs/internal/lonely.md": "content"},
        refs={"lib/test/run.sh": "reads docs/internal/lonely.md here"},
    )
    if any(k.startswith("orphan") for k in v):
        failures.append("GREEN full-path-referenced file reported orphan")
    v, _, _ = run({"docs/internal/lonely.md": "content"})
    if "orphan:docs/internal/lonely.md" not in v:
        failures.append("RED orphan not reported")

    complete = "\n".join(REQUIRED_SECTIONS)
    v, _, _ = run({"docs/internal/architecture/page.md": complete})
    if any(k.startswith("missing-sections") for k in v):
        failures.append("GREEN complete section contract fired")
    v, _, _ = run({"docs/internal/architecture/page.md": "## Current behavior only"})
    if "missing-sections:docs/internal/architecture/page.md" not in v:
        failures.append("RED missing-sections not reported")

    long = "x" * (LINE_LIMIT + 1)
    _, counts, _ = run({"docs/internal/a.md": long})
    if counts.get("docs/internal/a.md") != 1:
        failures.append("RED long line not counted")
    _, counts, _ = run({"docs/internal/a.md": f"```\n{long}\n```"})
    if counts:
        failures.append("GREEN fenced long line counted")
    _, counts, _ = run({"docs/internal/raw.observed.md": long})
    if counts:
        failures.append("GREEN .observed.md long line counted")

    _, _, adv = run({"docs/internal/big.md": "y" * (SIZE_ADVISORY + 1)})
    if not adv:
        failures.append("RED oversize advisory not reported")

    v, _, _ = run({"docs/internal/notes.private.md": "secret"})
    if "tracked-private:docs/internal/notes.private.md" not in _private_violations(
        {"docs/internal/notes.private.md": ""}
    ):
        failures.append("RED tracked *.private.md not reported")

    baseline_v = {"orphan:docs/internal/lonely.md"}
    current_v, _, _ = run({"docs/internal/lonely.md": "content"})
    new = current_v - baseline_v
    if new:
        failures.append("GREEN baselined violation still counted as new")

    for failure in failures:
        print(f"lint-internal-docs: self-test FAIL: {failure}", file=sys.stderr)
    print(f"lint-internal-docs: self-test {'FAILED' if failures else 'OK'}")
    return 1 if failures else 0


def _private_violations(docs: dict[str, str]) -> set[str]:
    return {f"tracked-private:{p}" for p in docs if p.endswith(".private.md")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Structure lint for docs/internal/ (baseline-tolerant)."
    )
    _pop.add_population_arguments(parser)
    parser.add_argument("--baseline", default=None)
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    root = _pop.resolve_root(args.root, tool="lint-internal-docs")
    baseline_path = (
        Path(args.baseline) if args.baseline else root / DEFAULT_BASELINE
    )

    try:
        population = _pop.enumerate_population(
            root,
            Path(args.files_from) if args.files_from else None,
            ls_files_argv=_pop.LS_FILES_INDEX,
        )
    except EnumerationError as exc:
        print(f"lint-internal-docs: enumeration unusable: {exc}", file=sys.stderr)
        return 1

    tracked = {p.replace("\\", "/") for p in population}
    doc_paths = sorted(
        p for p in tracked if p.startswith(DOCS_PREFIX) and p.endswith(".md")
    )
    reference_paths = sorted(
        p
        for p in tracked
        if p in REFERENCE_FILES
        or p.startswith(REFERENCE_PREFIXES)
        or (p.startswith(DOCS_PREFIX) and p.endswith(".md"))
    )

    docs: dict[str, str] = {}
    reference_texts: dict[str, str] = {}
    unreadable: list[tuple[str, str]] = []
    for relative in reference_paths:
        text, skip_reason = _pop.read_source(root / relative, skip_nul=True)
        if text is None:
            # A non-text reference source (an image, a NUL-carrying fixture) simply
            # cannot mention a doc path; only an unreadable DOC file fails the run.
            if relative in doc_paths:
                unreadable.append((relative, skip_reason or "unknown"))
            continue
        reference_texts[relative] = text
        if relative in doc_paths:
            docs[relative] = text

    if unreadable:
        for relative, reason in unreadable:
            print(f"lint-internal-docs: SKIPPED {relative}: {reason}", file=sys.stderr)
        print(
            f"lint-internal-docs: {len(unreadable)} docs file(s) could not be read — "
            "refusing to report clean",
            file=sys.stderr,
        )
        return 1

    violations, long_lines, advisories = check_corpus(docs, tracked, reference_texts)
    violations |= _private_violations(docs)

    gitignore, _ = _pop.read_source(root / ".gitignore", skip_nul=True)
    gitignore_ok = gitignore is not None and any(
        line.strip() == "*.private.md" for line in gitignore.split("\n")
    )

    if args.write_baseline:
        write_baseline(baseline_path, violations, long_lines)
        print(
            f"lint-internal-docs: baseline written to {baseline_path} "
            f"({len(violations)} violation(s), {len(long_lines)} long-line file(s))"
        )
        return 0

    baseline_v, baseline_counts = load_baseline(baseline_path)
    new_violations = sorted(violations - baseline_v)
    stale = sorted(baseline_v - violations)
    count_failures = [
        f"long-lines:{path}: {count} over-limit line(s), baseline allows {baseline_counts.get(path, 0)}"
        for path, count in sorted(long_lines.items())
        if count > baseline_counts.get(path, 0)
    ]
    stale_counts = sorted(
        path for path in baseline_counts if long_lines.get(path, 0) < baseline_counts[path]
    )

    for line in new_violations:
        print(f"lint-internal-docs: NEW {line}")
    for line in count_failures:
        print(f"lint-internal-docs: NEW {line}")
    for line in advisories:
        print(f"lint-internal-docs: {line}")
    for key in stale:
        print(f"lint-internal-docs: note: baseline entry no longer violates (advisory): {key}")
    for path in stale_counts:
        print(
            "lint-internal-docs: note: baseline long-line count is higher than current "
            f"(advisory): {path}"
        )
    if not gitignore_ok:
        print(
            "lint-internal-docs: .gitignore no longer carries a `*.private.md` line — "
            "the *.private.md never-committed contract has no enforcement",
            file=sys.stderr,
        )

    failed = bool(new_violations or count_failures) or not gitignore_ok
    print(
        f"lint-internal-docs: audited {len(docs)} docs files; "
        f"{len(new_violations) + len(count_failures)} new violation(s); "
        f"{len(stale) + len(stale_counts)} baseline advisorie(s)"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
