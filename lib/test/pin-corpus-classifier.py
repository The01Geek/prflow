#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Produce the frozen protected-asset census for existence-only test pins.

This is a maintainer-run measurement instrument, not a test-suite gate.  It
reuses pin-corpus-lint.py's shell parser and enumerates homes from an immutable
Git revision tree so runtime bundle targets never masquerade as source homes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import os
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
PCL_PATH = HERE / "pin-corpus-lint.py"
PIN_CORPUS_SOURCES = (
    "lib/test/run.sh",
    "lib/test/modules/create-issue-contract.sh",
    "lib/test/modules/capability-profiles.sh",
    "lib/test/modules/installer-wiring.sh",
    "lib/test/modules/regenerate-artifacts.sh",
    "lib/test/modules/review-stall-backstop.sh",
    "lib/test/modules/review-trigger-helpers.sh",
    # Added when the efficiency-trace + telemetry-persistence region was extracted out
    # of lib/test/run.sh: its 20 existence pins were already in the corpus as run.sh
    # sites, and a module left out of this tuple is not scanned at all — so omitting it
    # would drop those literals from the census and turn their still-present
    # adjudication rows into "unknown adjudication keys", failing generation outright.
    # Placement is deliberate rather than appended: test_pin_corpus_classifier.py pins
    # the tuple's LAST entry.
    "lib/test/modules/efficiency-trace-telemetry.sh",
    "lib/test/modules/review-and-fix-contract.sh",
    # Added when issue #1934 extracted the workpad-cli module: it carries the one
    # renamed devflow_module_pin_unique pin (the #338(T6) phase-3-ac-gate.md
    # boundary literal), so leaving it out would drop that literal from the census
    # and turn its still-present adjudication row into an "unknown adjudication key".
    "lib/test/modules/workpad-cli.sh",
)
DEFAULT_SOURCES = PIN_CORPUS_SOURCES
EXISTENCE_HELPERS = frozenset(
    {
        "assert_pin_unique",
        "assert_pin_red_on_removal",
        "devflow_module_pin_unique",
        "devflow_module_pin_present",
    }
)
MECHANICAL_BUCKETS = frozenset(
    {
        "suite-internal",
        "required-copy",
        "boundary",
        "generated",
        "config-key",
        "prose-sole-copy",
        "prose-multi-copy",
        "unclear",
    }
)
FINAL_BUCKETS = MECHANICAL_BUCKETS - {"unclear"}
COUNTED_EXCLUSIONS = (
    "lib/test/",
    ".prflow/learnings/",
    ".prflow/logs/",
    ".changeset/",
    "CHANGELOG.md",
)
COUNTED_EXCLUSION_HEADER = ";".join(COUNTED_EXCLUSIONS)
REQUIRED_COPY_PREFIXES = (
    "skills/receiving-code-review/",
    "skills/requesting-code-review/",
)
BOUNDARY_PREFIXES = (
    ".github/workflows/",
    ".github/actions/",
)
BOUNDARY_EXACT = frozenset(
    {
        "lib/capability-profiles.json",
        "lib/review-profile.tokens",
        "scripts/devflow-cloud-writer-contract.json",
        "scripts/post-issue-comment.sh",
        "scripts/cloud-auth-token.sh",
    }
)
GENERATED_EXACT = frozenset(
    {
        "scripts/devflow-cloud-writer-contract.json",
        "scripts/workflow-flight-recorder-registry.json",
        "lib/review-profile.tokens",
    }
)
OUT_OF_SCOPE_MODULES = tuple(
    source for source in PIN_CORPUS_SOURCES if source not in DEFAULT_SOURCES
)
TSV_COLUMNS = (
    "source_file",
    "assertion_name",
    "helper",
    "line_start",
    "line_end",
    "literal",
    "resolved_target",
    "target_defaulted",
    "homes",
    "counted_occurrences",
    "mutation_pin_count",
    "exact_count_pin_count",
    "registered_pin_region",
    "out_of_scope_pin_count",
    "bucket_mechanical",
    "bucket_final",
    "adjudication_rationale",
)
_OVERRIDE_NAME_RE = re.compile(r"""--var\s+["']([A-Za-z_]\w*)=""")


def _load_pin_lint():
    spec = importlib.util.spec_from_file_location("pin_corpus_lint", PCL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load shared parser: {PCL_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PCL = _load_pin_lint()


@dataclass(frozen=True)
class Site:
    source_file: str
    assertion_name: str | None
    helper: str
    line_start: int
    line_end: int
    literal: str | None
    resolved_target: str | None
    target_defaulted: bool

    @property
    def adjudication_key(self) -> str:
        if self.literal is not None:
            return literal_adjudication_key(self.literal)
        # Unresolved literals cannot use the literal-level digest. Key those rare
        # sites by their stable assertion identity rather than a line number, so
        # an unrelated insertion above the site does not invalidate adjudication.
        raw = (
            f"{self.source_file}\0{self.helper}\0{self.assertion_name or ''}"
        ).encode()
        return f"site:{hashlib.sha256(raw).hexdigest()}"


def encode_cell(value) -> str:
    """Encode a free-text/list value reversibly inside one TSV cell."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def literal_adjudication_key(literal: str) -> str:
    return f"literal:{hashlib.sha256(literal.encode('utf-8')).hexdigest()}"


def recover_override_names(text: str) -> dict[str, str]:
    """Recover only NAME from source-level ``--var "NAME=...`` bindings."""
    return {
        name: f"/__pin_corpus_runtime__/{name}"
        for name in sorted(set(_OVERRIDE_NAME_RE.findall(text)))
    }


def _raw_token(segments) -> str:
    return "".join(value for _, value in segments)


def _portable_target(target: str | None, lib: str) -> str | None:
    """Keep repo-owned resolved targets stable across clone locations."""
    if target is None:
        return None
    repo_root = Path(lib).parent
    try:
        return Path(target).relative_to(repo_root).as_posix()
    except ValueError:
        return target


def source_existence_helpers(text: str) -> tuple[frozenset[str], dict]:
    """Existence helpers callable in one source, plus the specs to resolve them.

    A focused module may route its pins through a module-private wrapper rather
    than calling the shared API directly (issue #946): ``review-and-fix-contract.sh``
    defines ``_raf_pin_unique``, so with only the built-in ``EXISTENCE_HELPERS``
    names known, every one of its pins is invisible to the census.

    The wrapper is resolved by reusing ``pin-corpus-lint.py``'s existing
    ``helper_specs_for_source`` inference rather than by naming ``_raf_pin_unique``
    here.  Which of that function's two mechanisms actually fires matters, and it
    is *not* the positional/``$@``-forwarding fixpoint: ``_raf_pin_unique``'s body
    calls ``assert_eq`` on a ``_raf_pin_count`` command substitution, and neither
    callee is a known helper, so the forwarding pass never reaches it (it reports
    no wrapper origin line, unlike the forwarding wrappers in ``run.sh`` and
    ``create-issue-contract.sh``).  What resolves it is that function's name-only
    fallback over ``STATIC_PRESENCE_WRAPPER_SUFFIXES``, which assigns the shared
    ``(literal, file)`` argument shape used by ``assert_pin_unique`` — the shape
    ``_raf_pin_unique <assertion-name> <literal> <file>`` genuinely has.  This
    reader therefore admits exactly the wrappers that fallback names, applying
    the same suffix convention rather than a second, divergent rule.  Scoping the
    admission to that suffix set is load-bearing: ``helper_specs_for_source``
    also infers count-family wrappers (``run.sh``'s ``pf545_illegal_count``,
    ``create-issue-contract.sh``'s ``ci749_iface``), and admitting those would
    silently move sites into the existence census that were never in it.
    """
    specs, _, _ = PCL.helper_specs_for_source(text)
    wrappers = {}
    for name, spec in specs.items():
        if name in PCL.HELPERS or not name.endswith(
            PCL.STATIC_PRESENCE_WRAPPER_SUFFIXES
        ):
            continue
        # Admit only a spec this reader's own extraction pass can resolve.
        # ``PCL.extract_pins`` skips a spec whose literal selector is not a
        # positional index (a fixed-literal wrapper) — so admitting one here would
        # make the two passes disagree: the shared pass would drop the site while
        # this reader's physical-token loop still counted it, and the cardinality
        # reconciliation below would then raise a "mismatch" naming the wrong
        # cause. Reject it at the seam instead, so the diagnostic names the real
        # problem. Dropping it silently is NOT the alternative: a wrapper whose
        # name claims the presence convention but whose shape is not the resolvable
        # one is an inconsistency a human must look at, and silence would let its
        # pins escape the census entirely.
        if not isinstance(spec[0], int):
            raise ValueError(
                f"presence-suffixed wrapper {name!r} infers a fixed-literal spec "
                f"({spec!r}); the census can only resolve a positional-literal "
                "wrapper. Rename it out of "
                f"{PCL.STATIC_PRESENCE_WRAPPER_SUFFIXES!r} or give it the "
                "<assertion-name> <literal> <file> shape."
            )
        wrappers[name] = spec
    resolvable = {name: PCL.HELPERS[name] for name in EXISTENCE_HELPERS}
    resolvable.update(wrappers)
    return frozenset(EXISTENCE_HELPERS) | frozenset(wrappers), resolvable


def extract_existence_sites(
    text: str,
    source_file: str,
    lib: str,
    overrides: dict[str, str],
) -> list[Site]:
    """Extract one record per existence-only call, paired to shared extraction."""
    existence_helpers, helper_specs = source_existence_helpers(text)
    shared = {
        (pin["lineno"], pin["helper"]): pin
        for pin in PCL.extract_pins(text, lib, overrides, helper_specs=helper_specs)
        if pin["helper"] in existence_helpers
    }
    path_vars, literal_vars = PCL.build_var_maps(text, lib, overrides)
    physical = text.split("\n")
    result = []
    for lineno, logical in PCL.join_logical_lines(text):
        stripped = logical.lstrip()
        if stripped.startswith("#"):
            continue
        tokens = PCL.tokenize(stripped)
        if not tokens:
            continue
        helper = _raw_token(tokens[0])
        if helper not in existence_helpers:
            continue
        if re.match(r"^\w+\s*\(\)", stripped):
            continue
        pin = shared.get((lineno, helper))
        if pin is None:
            raise ValueError(
                f"shared extraction cardinality mismatch at {source_file}:{lineno}"
            )
        args = tokens[1:]
        assertion_name = None
        if args:
            assertion_name = PCL.resolve_arg(
                args[0], literal_vars, path_vars, want_path=False, lib=lib
            )
            if assertion_name is None:
                assertion_name = _raw_token(args[0])
        _, file_idx, default_file = helper_specs[helper]
        target_defaulted = file_idx >= len(args) and default_file is not None
        span = PCL.site_physical_lines(physical, lineno, logical)
        result.append(
            Site(
                source_file=source_file,
                assertion_name=assertion_name,
                helper=helper,
                line_start=lineno,
                line_end=lineno + max(0, len(span) - 1),
                literal=pin["literal"],
                resolved_target=_portable_target(pin["file"], lib),
                target_defaulted=target_defaulted,
            )
        )
    if len(result) != len(shared):
        raise ValueError(
            f"shared extraction cardinality mismatch in {source_file}: "
            f"{len(result)} metadata rows != {len(shared)} extracted rows"
        )
    return result


def _command_substitutions(text: str):
    """Yield quote-aware, nested ``$(...)`` bodies."""
    index = 0
    while index + 1 < len(text):
        if text[index : index + 2] != "$(":
            index += 1
            continue
        start = index + 2
        cursor = start
        depth = 1
        quote = None
        escaped = False
        while cursor < len(text):
            char = text[cursor]
            if escaped:
                escaped = False
            elif char == "\\" and quote != "'":
                escaped = True
            elif quote is not None:
                if char == quote:
                    quote = None
            elif char in "'\"":
                quote = char
            elif text[cursor : cursor + 2] == "$(":
                depth += 1
                cursor += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    body = text[start:cursor]
                    yield body
                    # An outer substitution can contain the pin-count substitution
                    # below a test/printf wrapper. Descend into its balanced body so
                    # those nested command heads are not hidden by the outer head.
                    yield from _command_substitutions(body)
                    index = cursor
                    break
            cursor += 1
        index += 1


def extract_exact_count_literals(
    text: str, lib: str, overrides: dict[str, str]
) -> dict[str, int]:
    """Count literals referenced from command-substitution pin-count helpers."""
    path_vars, literal_vars = PCL.build_var_maps(text, lib, overrides)
    counts = Counter()
    for body in _command_substitutions(text):
        tokens = PCL.tokenize(body.strip())
        if not tokens:
            continue
        helper = _raw_token(tokens[0])
        if helper not in PCL.COUNT_HELPERS or len(tokens) < 2:
            continue
        literal = PCL.resolve_arg(
            tokens[1], literal_vars, path_vars, want_path=False, lib=lib
        )
        if literal is not None:
            counts[literal] += 1
    return dict(counts)


def _is_counted(path: str) -> bool:
    if path == "CHANGELOG.md":
        return False
    return not any(
        path.startswith(prefix)
        for prefix in COUNTED_EXCLUSIONS
        if prefix != "CHANGELOG.md"
    )


def _is_boundary(path: str) -> bool:
    return path in BOUNDARY_EXACT or path.startswith(BOUNDARY_PREFIXES)


def classify_mechanical(
    literal: str | None,
    homes: tuple[str, ...] | list[str],
    counted_homes: tuple[str, ...] | list[str],
    *,
    config_keys: frozenset[str],
) -> str:
    """Apply the complete ordered eight-bucket mechanical walk.

    ``boundary`` is deliberately absent from the return arms: matching a
    declared boundary path fails closed to ``unclear`` for human adjudication.
    """
    if literal is None or not homes:
        return "unclear"
    if all(path.startswith("lib/test/") for path in homes):
        return "suite-internal"
    if any(_is_boundary(path) for path in homes):
        return "unclear"
    if any(path.startswith(REQUIRED_COPY_PREFIXES) for path in homes):
        return "required-copy"
    if any(path in GENERATED_EXACT for path in homes):
        return "generated"
    if literal in config_keys:
        return "config-key"
    if len(counted_homes) == 1:
        return "prose-sole-copy"
    if len(counted_homes) >= 2:
        return "prose-multi-copy"
    return "unclear"


def parse_adjudications(text: str) -> dict[str, tuple[str, str]]:
    """Parse and validate the explicit semantic override table."""
    try:
        return PCL.parse_current_adjudications(text)
    except PCL.InfrastructureError as exc:
        raise ValueError(str(exc)) from exc


def _config_keys(tracked: dict[str, bytes]) -> frozenset[str]:
    keys = set()
    for relative in (".prflow/config.schema.json", ".prflow/config.json"):
        raw = tracked.get(relative)
        if raw is None:
            continue
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot derive config keys from {relative}: {exc}") from exc

        def collect(node):
            if isinstance(node, dict):
                properties = node.get("properties")
                if isinstance(properties, dict):
                    keys.update(properties)
                for child in node.values():
                    collect(child)
            elif isinstance(node, list):
                for child in node:
                    collect(child)

        collect(value)
    return frozenset(keys)


def _tracked_paths(explicit: Path) -> list[str]:
    raw = explicit.read_bytes()
    separator = b"\0" if b"\0" in raw else b"\n"
    paths = [part.decode("utf-8") for part in raw.split(separator) if part]
    if not paths:
        raise ValueError("tracked-file population is empty")
    return sorted(set(paths))


def _file_bytes(repo_root: Path, paths: list[str]) -> dict[str, bytes]:
    result = {}
    for relative in paths:
        try:
            result[relative] = (repo_root / relative).read_bytes()
        except OSError as exc:
            raise ValueError(f"tracked file unreadable: {relative}: {exc}") from exc
    return result


def _tracked_input(
    repo_root: Path, path: Path, tracked: dict[str, bytes]
) -> bytes:
    candidate = path if path.is_absolute() else repo_root / path
    try:
        relative = candidate.resolve().relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"revision-bound input must be inside the repository: {path}"
        ) from exc
    raw = tracked.get(relative)
    if raw is None:
        raise ValueError(f"revision-bound input missing at snapshot: {relative}")
    return raw


def _resolve_revision(repo_root: Path, revision: str | None) -> str:
    candidate = revision or "HEAD"
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{candidate}^{{commit}}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    resolved = result.stdout.strip()
    if result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", resolved):
        detail = result.stderr.strip() or "not a commit"
        raise ValueError(f"cannot resolve revision {candidate!r}: {detail}")
    if revision is not None and resolved != revision:
        raise ValueError(
            f"revision must be the canonical 40-character commit SHA: {resolved}"
        )
    return resolved


def _revision_files(repo_root: Path, revision: str) -> dict[str, bytes]:
    """Read one immutable Git tree without consulting the live index/worktree."""
    result = subprocess.run(
        ["git", "archive", "--format=tar", revision],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(
            f"git archive failed with rc {result.returncode}: "
            f"{result.stderr.decode('utf-8', errors='replace')}"
        )
    files = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
            for member in archive:
                if member.isfile():
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise ValueError(f"cannot read revision file: {member.name}")
                    files[member.name] = extracted.read()
                elif member.issym():
                    files[member.name] = member.linkname.encode("utf-8")
    except tarfile.TarError as exc:
        raise ValueError(f"cannot read git archive for {revision}: {exc}") from exc
    if not files:
        raise ValueError(f"tracked-file population is empty at revision {revision}")
    return files


def _homes(literal: str | None, tracked: dict[str, bytes]) -> tuple[str, ...]:
    if literal is None:
        return ()
    needle = literal.encode("utf-8")
    return tuple(path for path, data in tracked.items() if needle in data)


def _mutation_counts(
    source_texts: dict[str, str], lib: str, overrides: dict[str, str]
) -> Counter:
    result = Counter()
    for text in source_texts.values():
        for pin in PCL.extract_pins(text, lib, overrides):
            if (
                pin["helper"] in PCL.MUTATION_TAKING_HELPERS
                and pin["literal"] is not None
            ):
                result[pin["literal"]] += 1
    return result


def _out_of_scope_counts(
    tracked: dict[str, bytes],
    lib: str,
    overrides: dict[str, str],
    sources: tuple[str, ...],
    expected: int,
) -> tuple[Counter, int, tuple[str, ...]]:
    result = Counter()
    sites = 0
    outside_modules = tuple(
        source for source in PIN_CORPUS_SOURCES if source not in sources
    )
    for relative in outside_modules:
        raw = tracked.get(relative)
        if raw is None:
            continue
        text = raw.decode("utf-8")
        outside_helpers, outside_specs = source_existence_helpers(text)
        for pin in PCL.extract_pins(
            text, lib, overrides, helper_specs=outside_specs
        ):
            if pin["helper"] not in outside_helpers:
                continue
            sites += 1
            if pin["literal"] is not None:
                result[pin["literal"]] += 1
    if sites != expected:
        raise ValueError(
            f"out-of-scope site count mismatch: expected {expected}, found {sites}"
        )
    return result, sites, outside_modules


def _region_ranges(run_text: str) -> dict[str, tuple[int, int]]:
    result = {}
    for name, prefix in (
        ("park-calibration", "PARKCAL_GUARD_REGION"),
        ("fix-delta", "FIXDELTA_GUARD_REGION"),
    ):
        begin = end = None
        for number, line in enumerate(run_text.splitlines(), start=1):
            if f"{prefix}_BEGIN" in line:
                begin = number
            elif f"{prefix}_END" in line:
                end = number
        if begin is not None and end is not None and begin < end:
            result[name] = (begin, end)
    return result


def _region_for(site: Site, ranges: dict[str, tuple[int, int]]) -> str | None:
    if site.source_file != "lib/test/run.sh":
        return None
    for name, (begin, end) in ranges.items():
        if begin < site.line_start < end:
            return name
    return None


def _mechanical_rationale(bucket: str, counted: int) -> str:
    if bucket == "suite-internal":
        return "mechanical: every tracked home is under lib/test/"
    if bucket == "required-copy":
        return "mechanical: home is in an enumerated vendored-skill copy set"
    if bucket == "generated":
        return "mechanical: home is an explicitly registered generated artifact"
    if bucket == "config-key":
        return "mechanical: literal is a recursively derived configuration key"
    if bucket == "prose-sole-copy":
        return "mechanical: exactly one counted tracked home"
    if bucket == "prose-multi-copy":
        return f"mechanical: {counted} counted tracked homes"
    raise ValueError(f"no mechanical rationale for {bucket}")


def _semantic_recommendation(
    site: Site, homes: tuple[str, ...], mechanical: str
) -> tuple[str, str] | None:
    if mechanical == "unclear" and any(_is_boundary(path) for path in homes):
        return "boundary", "maintainer adjudication: declared security or interface boundary"
    if "CLAUDE.md" in homes and any(path.startswith("docs/") for path in homes):
        return (
            "required-copy",
            "maintainer adjudication: CLAUDE.md summary paired with canonical docs page",
        )
    if mechanical == "unclear" and site.literal is None:
        return (
            "boundary",
            "maintainer adjudication: dynamic literal is fail-closed pending retirement review",
        )
    if mechanical == "unclear":
        return (
            "prose-sole-copy",
            "maintainer adjudication: no established counted home; retained as a sole-copy asset",
        )
    return None


def _write_adjudication_template(
    path: Path,
    sites: list[Site],
    facts: dict[str, dict],
) -> None:
    rows = {}
    for site in sites:
        fact = facts[site.adjudication_key]
        recommendation = _semantic_recommendation(
            site, fact["homes"], fact["mechanical"]
        )
        if recommendation is not None:
            rows[site.adjudication_key] = recommendation
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(("adjudication_key", "bucket_final", "rationale"))
        for key in sorted(rows):
            writer.writerow((key, *rows[key]))


def _write_inventory(
    output: Path,
    command: str,
    revision: str,
    sources: tuple[str, ...],
    outside_total: int,
    outside_modules: tuple[str, ...],
    sites: list[Site],
    facts: dict[str, dict],
    mutation_counts: Counter,
    exact_counts: Counter,
    outside_counts: Counter,
    regions: dict[str, tuple[int, int]],
    adjudications: dict[str, tuple[str, str]],
) -> Counter:
    known_keys = {site.adjudication_key for site in sites}
    unknown = set(adjudications) - known_keys
    if unknown:
        raise ValueError(f"unknown adjudication keys: {', '.join(sorted(unknown))}")
    final_by_literal = {}
    bucket_counts = Counter()
    rows = []
    for site in sites:
        fact = facts[site.adjudication_key]
        mechanical = fact["mechanical"]
        adjudicated = adjudications.get(site.adjudication_key)
        if adjudicated is not None:
            final, rationale = adjudicated
        elif mechanical == "unclear":
            raise ValueError(
                f"missing adjudication for {site.adjudication_key} "
                f"({site.source_file}:{site.line_start})"
            )
        else:
            final = mechanical
            rationale = _mechanical_rationale(
                mechanical, len(fact["counted_homes"])
            )
        if final not in FINAL_BUCKETS:
            raise ValueError(f"invalid final bucket {final!r}")
        if site.literal is not None:
            prior = final_by_literal.setdefault(site.literal, final)
            if prior != final:
                raise ValueError(
                    f"inconsistent final bucket for literal digest "
                    f"{literal_adjudication_key(site.literal)}"
                )
        bucket_counts[final] += 1
        rows.append(
            (
                encode_cell(site.source_file),
                encode_cell(site.assertion_name),
                site.helper,
                site.line_start,
                site.line_end,
                encode_cell(site.literal),
                encode_cell(site.resolved_target),
                "true" if site.target_defaulted else "false",
                encode_cell(list(fact["homes"])),
                len(fact["counted_homes"]),
                mutation_counts[site.literal],
                exact_counts[site.literal],
                encode_cell(_region_for(site, regions)),
                outside_counts[site.literal],
                mechanical,
                final,
                encode_cell(rationale),
            )
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write("# snapshot: frozen pin-corpus census; not a live index\n")
            handle.write(f"# producing-command: {command}\n")
            handle.write(f"# revision: {revision}\n")
            handle.write(f"# in-scope: {';'.join(sources)}\n")
            handle.write(
                f"# out-of-scope: {outside_total} sites in "
                f"{len(outside_modules)} unselected candidate sources\n"
            )
            handle.write(
                f"# counted-file-exclusions: {COUNTED_EXCLUSION_HEADER}\n"
            )
            writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
            writer.writerow(TSV_COLUMNS)
            writer.writerows(rows)
        os.replace(temporary, output)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return bucket_counts


def _parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--source", action="append", dest="sources")
    parser.add_argument("--tracked-files", type=Path)
    parser.add_argument("--adjudications", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision")
    parser.add_argument("--expected-out-of-scope", type=int, default=0)
    parser.add_argument("--write-adjudication-template", action="store_true")
    return parser.parse_args(argv)


def _canonical_command_argv(
    raw_argv: list[str], sources: tuple[str, ...]
) -> list[str]:
    """Drop redundant source flags when they spell the complete default scope."""
    if sources != DEFAULT_SOURCES:
        return raw_argv
    canonical = []
    index = 0
    while index < len(raw_argv):
        argument = raw_argv[index]
        if argument == "--source":
            index += 2
            continue
        if argument.startswith("--source="):
            index += 1
            continue
        canonical.append(argument)
        index += 1
    return canonical


def main(argv=None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = _parse_args(raw_argv)
    repo_root = Path(args.repo_root).resolve()
    sources = tuple(args.sources or DEFAULT_SOURCES)
    try:
        if args.revision is not None and not re.fullmatch(
            r"[0-9a-f]{40}", args.revision
        ):
            raise ValueError("revision must be a 40-character lowercase git SHA")
        revision_bound = args.tracked_files is None
        if revision_bound:
            revision = _resolve_revision(repo_root, args.revision)
            tracked = _revision_files(repo_root, revision)
        else:
            revision = args.revision
            if revision is None:
                revision = _resolve_revision(repo_root, None)
            tracked_paths = _tracked_paths(args.tracked_files)
            tracked = _file_bytes(repo_root, tracked_paths)
        source_texts = {}
        for relative in sources:
            raw = tracked.get(relative)
            if raw is None:
                raise ValueError(f"in-scope source missing: {relative}")
            source_texts[relative] = raw.decode("utf-8")
        overrides = {}
        for text in source_texts.values():
            overrides.update(recover_override_names(text))
        lib = str(repo_root / "lib")
        sites = []
        for relative, text in source_texts.items():
            sites.extend(extract_existence_sites(text, relative, lib, overrides))
        config_keys = _config_keys(tracked)
        facts = {}
        for site in sites:
            if site.adjudication_key in facts:
                continue
            homes = _homes(site.literal, tracked)
            counted_homes = tuple(path for path in homes if _is_counted(path))
            mechanical = classify_mechanical(
                site.literal,
                homes,
                counted_homes,
                config_keys=config_keys,
            )
            fact = {
                "homes": homes,
                "counted_homes": counted_homes,
                "mechanical": mechanical,
            }
            facts[site.adjudication_key] = fact
        if args.write_adjudication_template:
            _write_adjudication_template(args.adjudications, sites, facts)
        if revision_bound and not args.write_adjudication_template:
            adjudication_text = _tracked_input(
                repo_root, args.adjudications, tracked
            ).decode("utf-8")
        else:
            adjudication_text = args.adjudications.read_text(encoding="utf-8")
        adjudications = parse_adjudications(adjudication_text)
        mutation_texts = {}
        for relative, raw in tracked.items():
            if relative == "lib/test/run.sh" or (
                relative.startswith("lib/test/modules/")
                and relative.endswith(".sh")
            ):
                mutation_texts[relative] = raw.decode("utf-8")
        mutation_counts = _mutation_counts(mutation_texts, lib, overrides)
        exact_counts = Counter()
        for text in source_texts.values():
            exact_counts.update(extract_exact_count_literals(text, lib, overrides))
        outside_counts, outside_total, outside_modules = _out_of_scope_counts(
            tracked, lib, overrides, sources, args.expected_out_of_scope
        )
        regions = _region_ranges(source_texts.get("lib/test/run.sh", ""))
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("revision must be a 40-character lowercase git SHA")
        command = shlex.join(
            [
                "python3",
                "lib/test/pin-corpus-classifier.py",
                *_canonical_command_argv(raw_argv, sources),
            ]
        )
        bucket_counts = _write_inventory(
            args.output,
            command,
            revision,
            sources,
            outside_total,
            outside_modules,
            sites,
            facts,
            mutation_counts,
            exact_counts,
            outside_counts,
            regions,
            adjudications,
        )
        resolved_literals = {site.literal for site in sites if site.literal is not None}
        unresolved_literals = sum(site.literal is None for site in sites)
        unresolved_targets = sum(site.resolved_target is None for site in sites)
        summary = " ".join(
            [
                f"total_sites={len(sites)}",
                f"distinct_resolved_literals={len(resolved_literals)}",
                f"unresolved_literals={unresolved_literals}",
                f"unresolved_targets={unresolved_targets}",
                f"out_of_scope_sites={outside_total}",
                *(
                    f"{bucket}={bucket_counts[bucket]}"
                    for bucket in sorted(FINAL_BUCKETS)
                ),
            ]
        )
        sys.stderr.write(summary + "\n")
        return 0
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        sys.stderr.write(f"pin-corpus-classifier: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
