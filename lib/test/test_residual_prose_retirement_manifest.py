#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Freeze the audited residual prose-pin population before source retirement."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from collections import Counter
from collections.abc import Set as AbstractSet
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
BASE_REVISION = "1d4d306bcacd4970df170faeab94e602724943b8"
# BASE_REVISION predates the .devflow/ -> .prflow/ state-directory rename (issue
# #1002), which moved every frozen record with its directory and rewrote none of
# their bytes.  This names a path in a historical tree, so it keeps the spelling
# that tree used; the live constants above/below carry the current spelling.
BASE_REVISION_INVENTORY = f"{BASE_REVISION}:.devflow/logs/pin-corpus-inventory.tsv"
MANIFEST_DECISION_REVISION = "b430c9b8b2ff83069bfe24a2ec4aa9424e56e200"
MANIFEST = REPO_ROOT / ".prflow/logs/residual-prose-retirement-manifest.tsv"
# The manifest's own identity set is frozen against BASE_REVISION's committed
# inventory, so a row there can never be edited to track a rename.  A rename is
# declared here instead, and only the current-tree realization consumes it.  This
# is live hand-maintained maintainer intent, so it lives beside its sibling
# pin-corpus-adjudications.tsv rather than under .prflow/logs/, which holds
# frozen audit artifacts.
IDENTITY_REFRESHES = HERE / "pin-identity-refreshes.tsv"
ADJUDICATIONS = REPO_ROOT / "lib/test/pin-corpus-adjudications.tsv"
CLASSIFIER = HERE / "pin-corpus-classifier.py"
LINT = HERE / "pin-corpus-lint.py"
# Controls over both arms of machine_consumer_evidence, in .sh and .py only: an arm or a
# comment-stripped language with no control can regress to matching nothing while the
# screen below still reports green.  .yml/.yaml and .jq carry no control.
_CONTROL_VERBATIM = (  # .sh, whole-literal arm: scripts/render-grounding-block.sh
    "> is not a verdict — it reads like an approval to a human while counting as"
)
_CONTROL_TOKEN = (  # absent verbatim; token arm via lib/scan.sh
    "the PROVENANCE_LABEL_SUPERSEDED selector spelling is accepted here"
)
_CONTROL_PY = "could not read audit-prompt template at"  # scripts/render-audit-prompt.py

IDENTITY_COLUMNS = (
    "source_file",
    "helper",
    "assertion_name",
    "literal",
    "resolved_target",
    "target_defaulted",
)
MANIFEST_COLUMNS = IDENTITY_COLUMNS + ("surface", "disposition", "rationale")
REFRESH_COLUMNS = IDENTITY_COLUMNS + ("new_assertion_name", "rationale")
MAPPING_CANONICAL_HEADER = "\t".join(MANIFEST_COLUMNS) + "\n"
RAW_SELECTOR_INDICES = (0, 2, 1, 5, 6, 7)
PROSE_BUCKETS = {"prose-sole-copy", "prose-multi-copy"}
EXPECTED_SURFACES = {
    "Review": 120,
    "Implement/Create-Issue": 119,
    "other/shared": 3,
}
EXPECTED_DISPOSITIONS = {"RETIRE_PROSE": 39, "RETAIN_BOUNDARY": 203}
# This is the independently recorded selector digest in the implementation plan.
EXPECTED_SELECTOR_DIGEST = "7505469a1b2538622d653cc225fe3571bf9c41d4d3c004011241e89b1e93bf40"
EXPECTED_AUDIT_MAPPING_DIGEST = (
    "047165133b3aa37e7c44a902f73b46ba428f00eb8b7b1468acf985a4f5489d1b"
)
SOURCE_FILES = (
    "lib/test/run.sh",
    "lib/test/modules/create-issue-contract.sh",
)


def compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def decode_cell(value: str) -> object:
    return json.loads(value)


def decode_identity_row(row: dict[str, str]) -> dict[str, object]:
    """Decode the six identity cells shared by the manifest and the refresh ledger."""
    return {
        "source_file": decode_cell(row["source_file"]),
        "helper": row["helper"],
        "assertion_name": decode_cell(row["assertion_name"]),
        "literal": decode_cell(row["literal"]),
        "resolved_target": decode_cell(row["resolved_target"]),
        "target_defaulted": row["target_defaulted"] == "true",
    }


def decode_manifest_row(row: dict[str, str]) -> dict[str, object]:
    return {
        **decode_identity_row(row),
        "surface": row["surface"],
        "disposition": row["disposition"],
        "rationale": row["rationale"],
    }


def identity(row: dict[str, object]) -> tuple[object, ...]:
    return tuple(row[column] for column in IDENTITY_COLUMNS)


def canonical_identity(row: dict[str, object]) -> str:
    """Keep identities independent of a source line number or audit report order."""
    cells = []
    for column in IDENTITY_COLUMNS:
        value = row[column]
        if column in {"source_file", "assertion_name", "literal", "resolved_target"}:
            cells.append(compact_json(value))
        elif column == "target_defaulted":
            cells.append("true" if value else "false")
        else:
            cells.append(str(value))
    return "\t".join(cells)


def canonical_mapping(row: dict[str, object]) -> str:
    return "\t".join(
        (
            canonical_identity(row),
            str(row["surface"]),
            str(row["disposition"]),
            str(row["rationale"]),
        )
    )


class RefreshLedgerError(ValueError):
    """A structurally malformed refresh-ledger row, named by row and cause.

    Raised while parsing, and by `refresh_mapping_of` on a duplicated old
    identity.  An admissible-but-wrong declaration is a different failure:
    `refresh_admission_error` RETURNS its reason as a string and never raises --
    it screens duplicates before the mapping build, so nothing in the admission
    path produces this exception.
    """


def parse_identity_refreshes(raw: str) -> list[dict[str, object]]:
    """Parse the refresh ledger, naming the offending row rather than raising raw.

    The ledger is hand-maintained, so the decode-level shapes a maintainer can
    produce -- a short row, a surplus cell, an unquoted cell, a `target_defaulted`
    that is neither "true" nor "false" -- are named rather than surfacing as a
    bare TypeError or JSONDecodeError from deep inside the decode.  Each is
    reported with the offending row, and with the column where one is
    identifiable: a surplus cell belongs to no column, and a header mismatch is
    reported against the header, which has no row number.  A wrapped `#`
    continuation line is NOT malformed -- it is dropped as a comment (see below),
    so it parses cleanly.
    """
    # Drop every "#" line, not only "# " ones, so a bare "#" spacer between
    # header blocks cannot parse as a data row.  The current ledger's wrapped
    # continuation lines all carry "# " and would be dropped either way -- the
    # widening is for the bare-"#" shape alone.
    table = [line for line in raw.splitlines() if not line.startswith("#")]
    reader = csv.DictReader(io.StringIO("\n".join(table)), delimiter="\t")
    fieldnames = tuple(reader.fieldnames or ())
    if fieldnames != REFRESH_COLUMNS:
        raise RefreshLedgerError(
            f"refresh ledger header is {fieldnames!r}, expected {REFRESH_COLUMNS!r}"
        )
    rows = []
    for number, row in enumerate(reader, start=1):
        if row.get(None) is not None:
            raise RefreshLedgerError(f"row {number} carries more cells than columns")
        decoded: dict[str, object] = {}
        for column in REFRESH_COLUMNS:
            cell = row[column]
            # csv.DictReader pads a short row with None. Reject that explicitly:
            # str(None) is the truthy "None", so a non-empty check downstream
            # would read an ABSENT cell as a supplied one.
            if cell is None:
                raise RefreshLedgerError(f"row {number} is missing the {column!r} cell")
            if column in ("rationale", "helper"):
                decoded[column] = cell
            elif column == "target_defaulted":
                # Never `cell == "true"`: that coerces "True"/"TRUE"/"flase" to
                # False, silently changing the row's IDENTITY.  The failure then
                # surfaces as "old identity is not a RETAIN_BOUNDARY row", which
                # sends the maintainer to re-check the manifest disposition when
                # the real fault is one unrecognized boolean literal.
                if cell not in ("true", "false"):
                    raise RefreshLedgerError(
                        f"row {number} cell 'target_defaulted' is {cell!r}, "
                        "expected 'true' or 'false'"
                    )
                decoded[column] = cell == "true"
            else:
                try:
                    value = decode_cell(cell)
                except json.JSONDecodeError as exc:
                    raise RefreshLedgerError(
                        f"row {number} cell {column!r} is not a JSON-encoded cell: {exc}"
                    ) from exc
                # A JSON `null`/number/list decodes to a non-str whose str() is
                # truthy ("None", "0"), so a downstream `str(...).strip()` check
                # would read an absent name or rationale as a supplied one.
                if not isinstance(value, str):
                    raise RefreshLedgerError(
                        f"row {number} cell {column!r} decodes to {type(value).__name__}, "
                        "expected a JSON string"
                    )
                decoded[column] = value
        rows.append(decoded)
    return rows


def duplicate_old_identity(rows: list[dict[str, object]]) -> dict[str, object] | None:
    """Return the first row whose old identity a preceding row already declared."""
    seen = set()
    for row in rows:
        old = identity(row)
        if old in seen:
            return row
        seen.add(old)
    return None


def refresh_mapping_of(rows: list[dict[str, object]]) -> dict[tuple[object, ...], tuple[object, ...]]:
    """Project each declared old identity onto the identity the tree now carries.

    Raises on a duplicated old identity rather than letting the dict silently keep
    the last row's new name: `refresh_mapping()` hands this mapping straight to
    the current-tree realization, where a collapsed row would surface as a missing
    identity blamed on the TREE instead of on the ledger.  The admission rule
    screens duplicates before it ever reaches this call, so the raise is the
    direct-caller's guard, not that arm's.
    """
    mapping = {}
    for row in rows:
        refreshed = dict(row)
        refreshed["assertion_name"] = row["new_assertion_name"]
        old = identity(row)
        if old in mapping:
            raise RefreshLedgerError(
                f"refresh ledger declares {row['assertion_name']!r} twice; "
                "a duplicated old identity would silently collapse two rows"
            )
        mapping[old] = identity(refreshed)
    return mapping


def refresh_admission_error(
    rows: list[dict[str, object]],
    retained: AbstractSet[tuple[object, ...]],
    current: AbstractSet[tuple[object, ...]],
) -> str | None:
    """Return why these refresh rows are inadmissible, or None when they are clean.

    This is the single implementation of the admission rule: the live guard calls
    it over the shipped ledger, and the negative table drives every arm over
    synthetic rows.  A mirrored second copy would let an inverted arm here stay
    green there, which is the coupled-mirror hazard the split exists to avoid.
    """
    # One row per declared old identity: a duplicate would make mapping[old]
    # resolve to the last row's new name, so an earlier row's missing target
    # would slip past the per-row liveness arm below. Screened by scanning rather
    # than by a length comparison, so the reason can NAME the colliding row the
    # way every per-row reason below does -- and so it runs BEFORE the mapping
    # build, whose own duplicate raise would otherwise pre-empt this arm.
    collided = duplicate_old_identity(rows)
    if collided is not None:
        return (
            f"duplicate old identity (declared twice: "
            f"{collided['assertion_name']!r})"
        )
    mapping = refresh_mapping_of(rows)
    # No injectivity arm: `refreshed` rewrites only assertion_name, so two rows
    # could collide on one new identity only by agreeing on all five other
    # identity cells -- and the frozen manifest carries no two RETAIN_BOUNDARY
    # rows sharing those five.  It is digest-pinned and can never grow, so that
    # collision is decidable now and absent, exactly like the chaining case
    # below.  Asserting either would be a dead arm.
    for number, row in enumerate(rows, start=1):
        old = identity(row)
        # Name the offending row in every reason, matching the parser's own
        # discipline: with more than one declared rename a bare cause tells the
        # maintainer WHAT is wrong but not WHICH row produced it, and the loop
        # short-circuits, so a second bad row stays invisible until the first is
        # fixed.  Callers match the cause with `assertIn`, not equality.
        def named(cause: str) -> str:
            return (
                f"{cause} (row {number}: {row['assertion_name']!r} "
                f"-> {row['new_assertion_name']!r})"
            )

        if old not in retained:
            # Renaming an already-refreshed pin UPDATES that row's
            # new_assertion_name in place; it never adds a second row, because
            # `old` would then name an intermediate the frozen manifest lacks.
            return named("old identity is not a RETAIN_BOUNDARY row")
        # No `str(...)` wrapper on either emptiness arm: str(None) is the truthy
        # "None", so coercing would launder a null cell straight past both checks
        # and misattribute the row to the tree-absence arm below -- the same
        # bypass the parser's isinstance check closes for parsed rows. A caller
        # that hand-builds a row (the negative table does) gets a TypeError
        # naming the cell instead of a silent pass.
        if not row["new_assertion_name"].strip():
            return named("empty new_assertion_name")
        if row["assertion_name"] == row["new_assertion_name"]:
            return named("self-mapping row")
        if not row["rationale"].strip():
            return named("empty rationale")
        # A refresh is only ever a live rename: the old name must be gone from
        # the tree and the new one present.  A refresh whose old identity still
        # resolves is stale and would silently outlive the rename it recorded.
        if old in current:
            return named("stale refresh: the old identity is still live")
        if mapping[old] not in current:
            return named("refreshed identity is absent from the tree")
    # Chaining needs no arm of its own: the two liveness checks above make it
    # unreachable, because a chained hop's middle identity would have to be both
    # present in the tree (as one row's new name) and absent from it (as the
    # next row's old name).  So the mapping is always a single hop.
    return None


def site_identity(site: object) -> tuple[object, ...]:
    """Project a current extracted site onto the manifest identity contract."""
    return tuple(getattr(site, column) for column in IDENTITY_COLUMNS)


def canonical_tsv(header: str, lines: list[str]) -> str:
    """The newline-terminated, sorted bytes used for frozen census digests."""
    return header + "\n".join(sorted(lines)) + "\n"


def load_classifier():
    spec = importlib.util.spec_from_file_location("pin_corpus_classifier", CLASSIFIER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_lint():
    spec = importlib.util.spec_from_file_location("pin_corpus_lint", LINT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_consumer_corpus(lint):
    """Return the step-1 machine-consumer corpus, via the lint's own loader.

    Never re-derive the enumeration here: a second copy of the corpus rules
    drifts silently from the ladder that actually gates a pin, leaving this
    assertion measuring a corpus production never uses.
    """
    return lint.build_machine_consumer_corpus(
        lint.load_machine_consumer_sources(REPO_ROOT)
    )


_HISTORICAL_INVENTORY_CACHE: dict[str, str] = {}


def encode_tracked_paths(paths: list[str]) -> bytes:
    """Encode Git paths without newline or platform line-ending ambiguity."""
    return b"".join(path.encode("utf-8") + b"\0" for path in paths)


def historical_inventory(revision: str) -> str:
    """Run a recorded revision's classifier, linter, table, and tracked tree together."""
    cached = _HISTORICAL_INVENTORY_CACHE.get(revision)
    if cached is not None:
        return cached
    with tempfile.TemporaryDirectory() as temporary:
        scratch = Path(temporary)
        archive = subprocess.run(
            ["git", "archive", "--format=tar", revision],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        ).stdout
        tracked_paths = []
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
            for member in tar:
                if not member.isfile():
                    continue
                extracted = tar.extractfile(member)
                if extracted is None:
                    raise AssertionError(f"cannot extract historical file: {member.name}")
                destination = scratch / member.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(extracted.read())
                tracked_paths.append(member.name)
        required = {
            "lib/test/pin-corpus-classifier.py",
            "lib/test/pin-corpus-lint.py",
            "lib/test/pin-corpus-adjudications.tsv",
        }
        missing = required - set(tracked_paths)
        if missing:
            raise AssertionError(
                "historical classifier fixture is incomplete: " + ", ".join(sorted(missing))
            )
        tracked = scratch / "tracked-files.txt"
        tracked.write_bytes(encode_tracked_paths(tracked_paths))
        inventory = scratch / "inventory.tsv"
        result = subprocess.run(
            [
                sys.executable,
                str(scratch / "lib/test/pin-corpus-classifier.py"),
                "--repo-root",
                str(scratch),
                "--tracked-files",
                str(tracked),
                "--adjudications",
                str(scratch / "lib/test/pin-corpus-adjudications.tsv"),
                "--output",
                str(inventory),
                "--revision",
                revision,
            ],
            cwd=scratch,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise AssertionError(
                f"historical classifier failed for {revision}: {result.stderr}"
            )
        raw = inventory.read_text(encoding="utf-8")
    _HISTORICAL_INVENTORY_CACHE[revision] = raw
    return raw


def historical_adjudications(revision: str) -> dict[str, tuple[str, str]]:
    """Parse a decision table with the classifier and linter from that same commit."""
    with tempfile.TemporaryDirectory() as temporary:
        scratch = Path(temporary)
        for relative in (
            "lib/test/pin-corpus-classifier.py",
            "lib/test/pin-corpus-lint.py",
            "lib/test/pin-corpus-adjudications.tsv",
        ):
            result = subprocess.run(
                ["git", "show", f"{revision}:{relative}"],
                cwd=REPO_ROOT,
                capture_output=True,
                check=True,
            )
            destination = scratch / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(result.stdout)
        program = """\
import importlib.util
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
classifier = root / "lib/test/pin-corpus-classifier.py"
spec = importlib.util.spec_from_file_location("historical_pin_corpus_classifier", classifier)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
table = (root / "lib/test/pin-corpus-adjudications.tsv").read_text(encoding="utf-8")
print(json.dumps(module.parse_adjudications(table), sort_keys=True))
"""
        result = subprocess.run(
            [sys.executable, "-c", program, str(scratch)],
            cwd=scratch,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise AssertionError(
                f"historical adjudication parser failed for {revision}: {result.stderr}"
            )
        parsed = json.loads(result.stdout)
    return {key: tuple(value) for key, value in parsed.items()}


def inventory_rows(raw: str) -> list[dict[str, str]]:
    return list(
        csv.DictReader(
            (line for line in raw.splitlines() if not line.startswith("# ")),
            delimiter="\t",
        )
    )


class ResidualRequiredCopyRetirementManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.classifier = load_classifier()
        cls._current_identities = None

    def load_manifest(self) -> tuple[dict[str, str], list[dict[str, object]]]:
        raw = MANIFEST.read_text(encoding="utf-8")
        metadata = {}
        table = []
        for line in raw.splitlines():
            if line.startswith("# "):
                key, _, value = line[2:].partition(": ")
                metadata[key] = value
            else:
                table.append(line)
        reader = csv.DictReader(io.StringIO("\n".join(table)), delimiter="\t")
        self.assertEqual(MANIFEST_COLUMNS, tuple(reader.fieldnames or ()))
        return metadata, [decode_manifest_row(row) for row in reader]

    def load_identity_refreshes(self) -> list[dict[str, object]]:
        """Return the declared same-change renames of frozen retained identities."""
        return parse_identity_refreshes(IDENTITY_REFRESHES.read_text(encoding="utf-8"))

    def refresh_mapping(self) -> dict[tuple[object, ...], tuple[object, ...]]:
        """Project each declared old identity onto the identity the tree now carries."""
        return refresh_mapping_of(self.load_identity_refreshes())

    def selected_base_inventory(self) -> set[tuple[object, ...]]:
        result = subprocess.run(
            ["git", "show", BASE_REVISION_INVENTORY],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        reader = csv.DictReader(
            (line for line in result.stdout.splitlines() if not line.startswith("# ")),
            delimiter="\t",
        )
        selected = set()
        for row in reader:
            if row["bucket_final"] not in PROSE_BUCKETS:
                continue
            # Decode through the shared identity contract rather than transcribing
            # the six cells positionally, so a change to IDENTITY_COLUMNS cannot
            # desync this projection from identity()'s ordering.
            selected.add(identity(decode_identity_row(row)))
        return selected

    def selected_base_raw_canonical(self) -> bytes:
        """Return the documented raw-cell selector bytes from immutable inventory text.

        The historical digest intentionally operates on the six JSON-encoded TSV
        cells as stored by the classifier, not their decoded Python values.  Keep
        the raw field positions explicit: source, helper, assertion, literal,
        target, and target_defaulted are indexes 0, 2, 1, 5, 6, and 7.
        """
        result = subprocess.run(
            ["git", "show", BASE_REVISION_INVENTORY],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        lines: list[bytes] = []
        for raw in result.stdout.splitlines():
            if raw.startswith("#") or raw.startswith("source_file\t"):
                continue
            cells = raw.split("\t")
            if cells[15] not in PROSE_BUCKETS:
                continue
            lines.append(
                "\t".join(cells[index] for index in RAW_SELECTOR_INDICES).encode("utf-8")
            )
        # Sorting encoded records is deliberately bytewise, matching LC_ALL=C.
        return b"\n".join(sorted(lines)) + b"\n"

    def current_source_identities(self) -> frozenset[tuple[object, ...]]:
        # Re-extracting the sites is the expensive step here — the classifier
        # walks all of run.sh — and several tests in this class need the same
        # answer, so memoize it on the class (the sentinel is initialized in
        # setUpClass; the fill happens at the end of this method). The cache is
        # valid only while this class reads one fixed SOURCE_FILES set: the
        # sibling class's current_source_identities takes a per-call source set
        # and must not reuse this method. Hand out a frozenset so a caller
        # cannot mutate the shared answer.
        cached = getattr(type(self), "_current_identities", None)
        if cached is not None:
            return cached
        source_texts = {
            source_file: (REPO_ROOT / source_file).read_text(encoding="utf-8")
            for source_file in SOURCE_FILES
        }
        overrides = {}
        for text in source_texts.values():
            overrides.update(self.classifier.recover_override_names(text))
        identities = frozenset(
            site_identity(site)
            for source_file, text in source_texts.items()
            for site in self.classifier.extract_existence_sites(
                text, source_file, str(REPO_ROOT / "lib"), overrides
            )
        )
        type(self)._current_identities = identities
        return identities

    def test_manifest_exactly_partitions_the_frozen_prose_selector(self):
        # Break caught: an audited site is silently omitted, duplicated, or reassigned.
        metadata, rows = self.load_manifest()
        self.assertEqual(BASE_REVISION, metadata["source-revision"])
        self.assertEqual(EXPECTED_SELECTOR_DIGEST, metadata["selector-identity-sha256"])
        self.assertEqual(242, len(rows))
        self.assertEqual(EXPECTED_SURFACES, Counter(row["surface"] for row in rows))
        self.assertEqual(EXPECTED_DISPOSITIONS, Counter(row["disposition"] for row in rows))

        identities = {identity(row) for row in rows}
        self.assertEqual(242, len(identities))
        base_identities = self.selected_base_inventory()
        self.assertEqual(base_identities, identities)
        base_raw_canonical = self.selected_base_raw_canonical()
        self.assertEqual(
            EXPECTED_SELECTOR_DIGEST,
            hashlib.sha256(base_raw_canonical).hexdigest(),
        )
        self.assertEqual(
            EXPECTED_SELECTOR_DIGEST,
            metadata["raw-selector-canonical-sha256"],
        )

        by_surface = {
            surface: {identity(row) for row in rows if row["surface"] == surface}
            for surface in EXPECTED_SURFACES
        }
        self.assertEqual(set(), by_surface["Review"] & by_surface["Implement/Create-Issue"])
        self.assertEqual(set(), by_surface["Review"] & by_surface["other/shared"])
        self.assertEqual(
            set(), by_surface["Implement/Create-Issue"] & by_surface["other/shared"]
        )
        self.assertEqual(identities, set().union(*by_surface.values()))

        canonical = "\n".join(sorted(canonical_identity(row) for row in rows)) + "\n"
        self.assertEqual(metadata["canonical-bytes"], str(len(canonical.encode("utf-8"))))
        self.assertEqual(
            metadata["canonical-sha256"],
            hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )
        mapping_canonical = canonical_tsv(
            MAPPING_CANONICAL_HEADER, [canonical_mapping(row) for row in rows]
        )
        self.assertEqual(
            EXPECTED_AUDIT_MAPPING_DIGEST,
            hashlib.sha256(mapping_canonical.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(EXPECTED_AUDIT_MAPPING_DIGEST, metadata["audit-mapping-sha256"])

    def test_every_retained_literal_has_an_explicit_non_mechanical_adjudication(self):
        # Break caught: the frozen decision did not classify its retained site as a boundary.
        _, rows = self.load_manifest()
        adjudications = historical_adjudications(MANIFEST_DECISION_REVISION)
        retained = [
            row["literal"] for row in rows if row["disposition"] == "RETAIN_BOUNDARY"
        ]
        self.assertEqual(203, len(retained))
        for literal in retained:
            key = self.classifier.literal_adjudication_key(literal)
            self.assertIn(key, adjudications, literal)
            bucket, rationale = adjudications[key]
            self.assertEqual("boundary", bucket, literal)
            self.assertFalse(rationale.startswith("mechanical:"), literal)

    def test_identity_refreshes_are_declared_and_live(self):
        # Break caught: a refresh launders a vanished pin, or outlives its rename.
        _, rows = self.load_manifest()
        retained = {
            identity(row) for row in rows if row["disposition"] == "RETAIN_BOUNDARY"
        }
        current = self.current_source_identities()
        self.assertIsNone(
            refresh_admission_error(self.load_identity_refreshes(), retained, current),
            "the shipped refresh ledger is inadmissible",
        )

    def test_refresh_admission_rejects_every_malformed_declaration(self):
        # Break caught: an admission arm is inverted, dropped, or made vacuous.
        # The fixture is FULLY SYNTHETIC — base row, `retained`, and `current` are
        # all fabricated here rather than read from the shipped ledger or derived
        # from the live tree. `refresh_admission_error` takes `retained`/`current`
        # as parameters precisely so it can be driven over synthetic sets, and
        # binding them to real data would make the arm coverage depend on a rename
        # currently existing: the ledger's documented lifetime makes ZERO rows a
        # supported steady state (renaming a pin back to its frozen name DELETES
        # its row), and in that state a tree-derived fixture finds no candidate and
        # the whole negative table stops running. The shipped ledger's own
        # admissibility is the sibling test's job, and only its job.
        base = {
            "source_file": "lib/test/run.sh",
            "helper": "assert_pin_unique",
            "assertion_name": "a frozen assertion name",
            "literal": "a guarded literal",
            "resolved_target": "/__pin_corpus_runtime__/SOME_BUNDLE",
            "target_defaulted": False,
            "new_assertion_name": "the renamed assertion name",
            "rationale": "negative-table probe",
        }
        retained = {identity(base)}
        current = {identity({**base, "assertion_name": base["new_assertion_name"]})}
        # Positive control (guard-class shape 3): the unmutated base row is
        # ADMISSIBLE against these sets, so each rejection below is attributable to
        # the one property that case mutates rather than to a defect in the fixture.
        self.assertIsNone(
            refresh_admission_error([dict(base)], retained, current),
            "the synthetic base row must itself be admissible",
        )

        def mutated(**overrides):
            row = dict(base)
            row.update(overrides)
            return [row]

        unretained = dict(base)
        unretained["literal"] = "a literal no retained identity carries"
        cases = {
            "duplicate old identity": [dict(base), dict(base)],
            "old identity is not a RETAIN_BOUNDARY row": [unretained],
            "empty new_assertion_name": mutated(new_assertion_name="   "),
            "self-mapping row": mutated(new_assertion_name=base["assertion_name"]),
            "empty rationale": mutated(rationale=""),
            "refreshed identity is absent from the tree": mutated(
                new_assertion_name="a name the tree does not carry"
            ),
        }
        for expected, rows in cases.items():
            with self.subTest(case=expected):
                # assertIn, not assertEqual: each reason now names the offending
                # row and its old/new names after the cause.
                self.assertIn(
                    expected, refresh_admission_error(rows, retained, current) or ""
                )
        # The stale arm needs an old identity that is BOTH retained and still live,
        # which no mutation of `base` can produce (its old identity is retained but
        # deliberately absent from `current`). Widen the synthetic `current` for
        # this one case instead of reaching into the tree.
        stale_current = set(current) | {identity(base)}
        self.assertIn(
            "stale refresh: the old identity is still live",
            refresh_admission_error([dict(base)], retained, stale_current) or "",
        )

    def test_refresh_mapping_refuses_a_duplicated_old_identity(self):
        # Break caught: refresh_mapping_of's duplicate raise is dropped. Its
        # direct caller refresh_mapping() has NO admission screen in front of it,
        # so a collapsed row would surface through
        # test_current_tree_realizes_the_retirement_manifest as a MISSING retained
        # boundary -- blaming the tree for a ledger fault. The admission path
        # screens duplicates first, so only this test drives the raise.
        row = {
            "source_file": "lib/test/run.sh",
            "helper": "assert_pin_unique",
            "assertion_name": "a frozen assertion name",
            "literal": "a guarded literal",
            "resolved_target": "/__pin_corpus_runtime__/SOME_BUNDLE",
            "target_defaulted": False,
            "new_assertion_name": "the renamed assertion name",
            "rationale": "duplicate probe",
        }
        self.assertEqual(1, len(refresh_mapping_of([dict(row)])))
        with self.assertRaises(RefreshLedgerError) as caught:
            refresh_mapping_of([dict(row), dict(row)])
        self.assertIn("declares", str(caught.exception))
        self.assertIn(row["assertion_name"], str(caught.exception))

    def test_an_empty_refresh_ledger_parses_and_admits(self):
        # Break caught: the ledger's documented zero-row steady state (a pin renamed
        # back to its frozen name DELETES its row) stops parsing or stops admitting,
        # which no other test would notice until the day a maintainer empties it.
        header = "\t".join(REFRESH_COLUMNS)
        self.assertEqual([], parse_identity_refreshes(f"# a comment\n#\n{header}\n"))
        self.assertIsNone(refresh_admission_error([], set(), set()))

    def test_no_two_retained_rows_share_the_five_non_name_identity_cells(self):
        # Break caught: the premise refresh_admission_error cites for omitting an
        # injectivity arm stops holding.  The harmed consumer is NOT
        # refresh_mapping_of (it keys on the OLD identity, so colliding VALUES
        # drop nothing) -- it is test_current_tree_realizes_the_retirement_manifest,
        # whose `retained` SET comprehension would collapse two distinct frozen
        # identities into one and let a genuinely vanished boundary pass.
        # The manifest is digest-pinned, so this is decidable — assert it rather
        # than leaving a load-bearing premise living only in a comment.
        _, manifest = self.load_manifest()
        name_index = IDENTITY_COLUMNS.index("assertion_name")
        seen: dict[tuple[object, ...], object] = {}
        for row in manifest:
            if row["disposition"] != "RETAIN_BOUNDARY":
                continue
            old = identity(row)
            rest = old[:name_index] + old[name_index + 1 :]
            self.assertNotIn(
                rest,
                seen,
                f"two RETAIN_BOUNDARY rows share the five non-assertion_name identity "
                f"cells ({row['assertion_name']!r} and {seen.get(rest)!r}), so the "
                f"omitted injectivity arm is no longer dead",
            )
            seen[rest] = row["assertion_name"]

    def test_refresh_ledger_parser_names_its_malformed_rows(self):
        # Break caught: a hand-edit fails with a raw decode error naming no row.
        def tsv(cells):
            # Render through csv so the JSON cells carry the same quoting the
            # real ledger has; a hand-joined row would decode differently.
            buf = io.StringIO()
            csv.writer(buf, delimiter="\t", lineterminator="").writerow(cells)
            return buf.getvalue()

        header = tsv(REFRESH_COLUMNS)
        good = tsv(
            (
                compact_json("lib/test/run.sh"),
                "assert_pin_unique",
                compact_json("old name"),
                compact_json("a literal"),
                compact_json("a target"),
                "false",
                compact_json("new name"),
                "why",
            )
        )
        self.assertEqual(1, len(parse_identity_refreshes(f"# c\n{header}\n{good}\n")))
        # A wrapped header continuation is a comment, not a data row -- and so is
        # a BARE "#" spacer, which is what the widened prefix is actually for: a
        # "# "-only filter would leave it to parse as a short data row.
        self.assertEqual(
            1, len(parse_identity_refreshes(f"# c\n#   more\n#\n{header}\n{good}\n"))
        )
        cases = {
            "header": f"# c\n{tsv(IDENTITY_COLUMNS)}\n",
            "missing the 'rationale' cell": f"# c\n{header}\n{good.rsplit(chr(9), 1)[0]}\n",
            "more cells than columns": f"# c\n{header}\n{good}\textra\n",
            "not a JSON-encoded cell": f"# c\n{header}\n{good.replace(tsv([compact_json('a literal')]), 'a literal', 1)}\n",
            # A near-miss boolean silently changes the row's IDENTITY under a
            # bare `cell == "true"`, so it is rejected by name rather than
            # resurfacing as a misdirected "not a RETAIN_BOUNDARY row".
            "'target_defaulted' is 'True', expected 'true' or 'false'": (
                f"# c\n{header}\n{good.replace(chr(9) + 'false' + chr(9), chr(9) + 'True' + chr(9), 1)}\n"
            ),
            # A JSON null decodes to None, whose str() is the truthy "None" — the
            # emptiness arms downstream would read it as a supplied value.
            "decodes to NoneType, expected a JSON string": (
                f"# c\n{header}\n{good.replace(tsv([compact_json('new name')]), 'null', 1)}\n"
            ),
        }
        for expected, text in cases.items():
            with self.subTest(case=expected):
                with self.assertRaises(RefreshLedgerError) as caught:
                    parse_identity_refreshes(text)
                self.assertIn(expected, str(caught.exception))

    def test_current_tree_realizes_the_retirement_manifest(self):
        # Break caught: a retired wording pin remains in the current tree.
        _, rows = self.load_manifest()
        retired = {
            identity(row) for row in rows if row["disposition"] == "RETIRE_PROSE"
        }
        current = self.current_source_identities()
        self.assertSetEqual(
            set(),
            retired & current,
            "still-live RETIRE_PROSE identities:\n"
            + "\n".join(sorted(map(repr, retired & current))),
        )


NEW_BASE_REVISION = "29f3298b0cd0bbd5efea4c01ca592041a2be92e4"
NEW_MANIFEST_DECISION_REVISION = "83bb532037676e9742d7e1bd036f3c33e610c59b"
NEW_MANIFEST = REPO_ROOT / ".prflow/logs/residual-required-copy-retirement-manifest.tsv"
NEW_MANIFEST_COLUMNS = IDENTITY_COLUMNS + ("disposition", "rationale")
NEW_EXPECTED_SELECTOR_DIGEST = "d412dfc70f1830fafe8388f33d42057722999d5f34876b6cfd16a629bd6b7abb"
NEW_EXPECTED_CANONICAL_BYTES = 31254
NEW_EXPECTED_CANONICAL_SHA256 = "d412dfc70f1830fafe8388f33d42057722999d5f34876b6cfd16a629bd6b7abb"
NEW_EXPECTED_AUDIT_MAPPING_BYTES = 55610
NEW_EXPECTED_AUDIT_MAPPING_SHA256 = "30c00f2b96f79c5fe4ff64fa42d01767a46288eb0ebf1c92727259460cae1829"
NEW_EXPECTED_COUNTS = {"historical": 141, "retire_prose": 30, "retain_boundary": 111, "distinct_literals": 130, "retired_distinct_literals": 26, "retained_distinct_literals": 105}
HARNESS_INVENTORY = REPO_ROOT / "lib/test/modules/harness-python-guards.inventory.md"


class ResidualProseRetirementManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.classifier = load_classifier()

    def load_manifest(self) -> tuple[dict[str, str], list[dict[str, object]]]:
        raw = NEW_MANIFEST.read_text(encoding="utf-8")
        metadata: dict[str, str] = {}
        table = []
        for line in raw.splitlines():
            if line.startswith("# "):
                key, _, value = line[2:].partition(": ")
                metadata[key] = value
            else:
                table.append(line)
        reader = csv.DictReader(io.StringIO("\n".join(table)), delimiter="\t")
        self.assertEqual(NEW_MANIFEST_COLUMNS, tuple(reader.fieldnames or ()))
        rows = []
        for row in reader:
            rows.append(
                {
                    "source_file": decode_cell(row["source_file"]),
                    "helper": row["helper"],
                    "assertion_name": decode_cell(row["assertion_name"]),
                    "literal": decode_cell(row["literal"]),
                    "resolved_target": decode_cell(row["resolved_target"]),
                    "target_defaulted": row["target_defaulted"] == "true",
                    "disposition": row["disposition"],
                    "rationale": row["rationale"],
                }
            )
        return metadata, rows

    def selected_base_rows(self) -> tuple[set[tuple[object, ...]], bytes]:
        raw = historical_inventory(NEW_BASE_REVISION)
        reader = csv.DictReader(
            (line for line in raw.splitlines() if not line.startswith("# ")),
            delimiter="\t",
        )
        rows = []
        canonical = []
        for row in reader:
            if row["bucket_final"] == "boundary":
                continue
            rows.append(
                (
                    decode_cell(row["source_file"]),
                    row["helper"],
                    decode_cell(row["assertion_name"]),
                    decode_cell(row["literal"]),
                    decode_cell(row["resolved_target"]),
                    row["target_defaulted"] == "true",
                )
            )
            canonical.append(
                "\t".join(
                    row[column]
                    for column in IDENTITY_COLUMNS
                ).encode("utf-8")
            )
        return set(rows), b"\n".join(sorted(canonical)) + b"\n"

    def test_manifest_exactly_partitions_the_frozen_selector(self):
        # Break caught: an audited required-copy or suite-internal site is omitted or reassigned.
        metadata, rows = self.load_manifest()
        base_identities, raw_canonical = self.selected_base_rows()
        self.assertEqual(NEW_BASE_REVISION, metadata["source-revision"])
        self.assertEqual(NEW_EXPECTED_SELECTOR_DIGEST, metadata["raw-selector-canonical-sha256"])
        self.assertEqual(NEW_EXPECTED_SELECTOR_DIGEST, hashlib.sha256(raw_canonical).hexdigest())
        canonical = "\n".join(sorted(canonical_identity(row) for row in rows)) + "\n"
        self.assertEqual(str(NEW_EXPECTED_CANONICAL_BYTES), metadata["canonical-bytes"])
        self.assertEqual(NEW_EXPECTED_CANONICAL_BYTES, len(canonical.encode("utf-8")))
        self.assertEqual(NEW_EXPECTED_CANONICAL_SHA256, metadata["canonical-sha256"])
        self.assertEqual(NEW_EXPECTED_CANONICAL_SHA256, hashlib.sha256(canonical.encode("utf-8")).hexdigest())
        mapping = (
            "\t".join(NEW_MANIFEST_COLUMNS)
            + "\n"
            + "\n".join(
                sorted(
                    canonical_identity(row)
                    + "\t"
                    + str(row["disposition"])
                    + "\t"
                    + str(row["rationale"])
                    for row in rows
                )
            )
            + "\n"
        )
        self.assertEqual(str(NEW_EXPECTED_AUDIT_MAPPING_BYTES), metadata["audit-mapping-bytes"])
        self.assertEqual(NEW_EXPECTED_AUDIT_MAPPING_BYTES, len(mapping.encode("utf-8")))
        self.assertEqual(NEW_EXPECTED_AUDIT_MAPPING_SHA256, metadata["audit-mapping-sha256"])
        self.assertEqual(NEW_EXPECTED_AUDIT_MAPPING_SHA256, hashlib.sha256(mapping.encode("utf-8")).hexdigest())
        self.assertEqual(NEW_EXPECTED_COUNTS["historical"], len(rows))
        self.assertEqual(NEW_EXPECTED_COUNTS["historical"], len(set(map(identity, rows))))
        self.assertEqual(base_identities, set(map(identity, rows)))
        self.assertEqual(
            {"RETIRE_PROSE": NEW_EXPECTED_COUNTS["retire_prose"], "RETAIN_BOUNDARY": NEW_EXPECTED_COUNTS["retain_boundary"]},
            Counter(row["disposition"] for row in rows),
        )
        self.assertTrue({row["disposition"] for row in rows} <= {"RETIRE_PROSE", "RETAIN_BOUNDARY"})
        for row in rows:
            if row["disposition"] == "RETAIN_BOUNDARY":
                self.assertRegex(str(row["rationale"]), r"^Retain .+ boundary:")
        self.assertEqual(NEW_EXPECTED_COUNTS["distinct_literals"], len({row["literal"] for row in rows}))
        self.assertEqual(NEW_EXPECTED_COUNTS["retired_distinct_literals"], len({row["literal"] for row in rows if row["disposition"] == "RETIRE_PROSE"}))
        self.assertEqual(NEW_EXPECTED_COUNTS["retained_distinct_literals"], len({row["literal"] for row in rows if row["disposition"] == "RETAIN_BOUNDARY"}))

    def test_every_retained_literal_has_an_explicit_non_mechanical_adjudication(self):
        # Break caught: the recorded decision did not classify its retained site as a boundary.
        _, rows = self.load_manifest()
        adjudications = historical_adjudications(NEW_MANIFEST_DECISION_REVISION)
        retained = {
            row["literal"]
            for row in rows
            if row["disposition"] == "RETAIN_BOUNDARY"
        }
        self.assertEqual(NEW_EXPECTED_COUNTS["retained_distinct_literals"], len(retained))
        for literal in retained:
            key = self.classifier.literal_adjudication_key(literal)
            self.assertIn(key, adjudications, literal)
            bucket, rationale = adjudications[key]
            self.assertEqual("boundary", bucket, literal)
            self.assertTrue(rationale and not rationale.startswith("mechanical:"), literal)

    def current_source_identities(
        self, source_files: set[str]
    ) -> set[tuple[object, ...]]:
        source_texts = {
            source_file: (REPO_ROOT / source_file).read_text(encoding="utf-8")
            for source_file in source_files
        }
        overrides = {}
        for text in source_texts.values():
            overrides.update(self.classifier.recover_override_names(text))
        return {
            site_identity(site)
            for source_file, text in source_texts.items()
            for site in self.classifier.extract_existence_sites(
                text, source_file, str(REPO_ROOT / "lib"), overrides
            )
        }

    def test_current_tree_realizes_the_retirement_and_inventory_summary(self):
        # Break caught: a wording-only pin remains or the historical summary drifts.
        _, rows = self.load_manifest()
        retired = {identity(row) for row in rows if row["disposition"] == "RETIRE_PROSE"}
        retained = {identity(row) for row in rows if row["disposition"] == "RETAIN_BOUNDARY"}
        current = self.current_source_identities(
            {str(row["source_file"]) for row in rows}
        )
        self.assertSetEqual(
            set(),
            retired & current,
            "still-live RETIRE_PROSE identities:\n"
            + "\n".join(sorted(map(repr, retired & current))),
        )
        summary = {}
        for line in HARNESS_INVENTORY.read_text(encoding="utf-8").splitlines():
            if not line.startswith("residual_required_copy_retirement "):
                continue
            summary = dict(field.split("=", 1) for field in line.split()[1:])
        self.assertEqual(
            {
                "historical": str(len(rows)),
                "retire_prose": str(len(retired)),
                "retain_boundary": str(len(retained)),
            },
            summary,
        )

    def test_final_inventory_realizes_only_authorized_buckets(self):
        inventory = REPO_ROOT / ".prflow/logs/pin-corpus-inventory.tsv"
        raw = inventory.read_text(encoding="utf-8")
        metadata = dict(
            line[2:].split(": ", 1) for line in raw.splitlines() if line.startswith("# ")
        )
        revision = metadata["revision"]
        self.assertRegex(revision, r"^[0-9a-f]{40}$")
        subprocess.run(["git", "cat-file", "-e", f"{revision}^{{commit}}"], cwd=REPO_ROOT, check=True)
        self.assertEqual(
            "python3 lib/test/pin-corpus-classifier.py --repo-root . --adjudications "
            "lib/test/pin-corpus-adjudications.tsv --output .prflow/logs/pin-corpus-inventory.tsv "
            f"--revision {revision}",
            # The census is frozen at a revision that predates the .devflow/ ->
            # .prflow/ state-directory rename (issue #1002).  Project the recorded
            # command onto the current spelling rather than editing the frozen
            # record, which would falsify it.
            metadata["producing-command"].replace(".devflow/", ".prflow/"),
        )
        rows = list(csv.DictReader((line for line in raw.splitlines() if not line.startswith("# ")), delimiter="\t"))
        self.assertTrue(rows)
        # Issue #885's re-adjudication moved every site whose pinned literal is
        # agent-executed prose no tool reads out of `boundary` and into
        # `prose-sole-copy`, so the census is no longer the boundary-only realization
        # this test used to assert.  What must still hold is arm 2's own precondition:
        # a prose bucket may appear only on a row arm 2 would have authorized, and only
        # with an explicit maintainer adjudication behind it.  Asserting the
        # precondition rather than a transcribed population count keeps this a live
        # gate that a later re-adjudication cannot silently widen — a prose bucket on a
        # multi-home row, or one resting on the classifier's mechanical fallback rather
        # than a recorded judgment, is RED here before it can authorize a retirement.
        self.assertLessEqual(
            {row["bucket_final"] for row in rows}, {"boundary"} | PROSE_BUCKETS
        )
        classifier = load_classifier()
        table = classifier.parse_adjudications(ADJUDICATIONS.read_text(encoding="utf-8"))
        # One-sided screen: a hit proves the bucket WRONG, a miss proves nothing.  Never
        # read a green here as evidence the prose population is clean.
        lint = load_lint()
        corpus = build_consumer_corpus(lint)
        # Every miss below is indistinguishable from a degraded search, so establish the
        # search still works before trusting one.  Never drop one of these as redundant:
        # each catches a degradation the others pass.
        # Floored near the live population, not at a token value: load_machine_consumer_sources
        # drops an unreadable file to a stderr breadcrumb nothing asserts on, so a slack
        # floor tolerates a majority collapse.
        self.assertGreater(len(corpus), 200, "machine-consumer corpus is implausibly small")
        self.assertEqual(
            {path.split("/")[0] for path, _ in corpus},
            {prefix.rstrip("/") for prefix in lint.MACHINE_CONSUMER_PATH_PREFIXES},
            "a declared machine-consumer prefix contributed no files",
        )
        # Assert WHICH arm answered: machine_consumer_evidence tries the whole literal
        # first, so a token control that ever appears verbatim would pass while silently
        # testing the other arm.
        for control, phrase in (
            (_CONTROL_VERBATIM, "contains the pinned literal"),
            (_CONTROL_TOKEN, "contains the distinctive token"),
            (_CONTROL_PY, "contains the pinned literal"),
        ):
            evidence = lint.machine_consumer_evidence(control, corpus)
            self.assertIsNotNone(evidence, f"machine-consumer search lost a control: {control!r}")
            self.assertIn(phrase, evidence)
        for row in rows:
            bucket = row["bucket_final"]
            if bucket not in PROSE_BUCKETS:
                continue
            where = f"{decode_cell(row['source_file'])}:{row['line_start']}"
            counted = int(row["counted_occurrences"])
            if bucket == "prose-sole-copy":
                self.assertEqual(1, counted, where)
            else:
                self.assertGreaterEqual(counted, 2, where)
            rationale = decode_cell(row["adjudication_rationale"])
            self.assertFalse(rationale.startswith("mechanical:"), where)
            literal = decode_cell(row["literal"])
            digest = hashlib.sha256(literal.encode("utf-8")).hexdigest()
            self.assertIn(f"literal:{digest}", table, where)
            evidence = lint.machine_consumer_evidence(literal, corpus)
            self.assertIsNone(evidence, f"{where}: {evidence}")
        # The census is frozen at a revision that predates the .devflow/ ->
        # .prflow/ state-directory rename (issue #1002), so its homes carry the
        # superseded spelling.  Project each home before the membership test,
        # which would otherwise pass vacuously for every row.
        self.assertTrue(
            all(
                ".prflow/logs/pin-corpus-inventory.tsv"
                not in {
                    home.replace(".devflow/", ".prflow/")
                    for home in decode_cell(row["homes"])
                }
                for row in rows
            )
        )
        _, manifest = self.load_manifest()
        retired = {identity(row) for row in manifest if row["disposition"] == "RETIRE_PROSE"}
        observed = {
            (decode_cell(row["source_file"]), row["helper"], decode_cell(row["assertion_name"]), decode_cell(row["literal"]), decode_cell(row["resolved_target"]), row["target_defaulted"] == "true")
            for row in rows
        }
        self.assertFalse(retired & observed)


if __name__ == "__main__":
    unittest.main()
