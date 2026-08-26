#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Freeze the exact historical ``assert_pin_red_on_removal`` census."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
BASE_REVISION = "19b8d837f320e848983d420287e05bf356977bac"
MANIFEST = REPO_ROOT / ".prflow/logs/red-on-removal-retirement-manifest.tsv"
CLASSIFIER = HERE / "pin-corpus-classifier.py"
EXPECTED_DISPOSITIONS = {
    "redundant_retire": 59,
    "prose_retire": 5,
    "convert_presence": 32,
    "replace_behavioral": 17,
}
EXPECTED_DIGESTS = {
    "paired-canonical-sha256": (
        "b90c484664d05a81921bcd2d3b709baf3150e65eb6ca207e9f794f04e2e7217c"
    ),
    "sole-call-sha256": (
        "433575e25e9fb69f7899ae42c8d86ff1fddbf0fdbba75dd5a65c7d1dcdeaa463"
    ),
    "sole-distinct-pair-sha256": (
        "82bdcf80d68b72311786cc9502c62c055ac64d20b734d19b36a7bcf5218b226a"
    ),
    "disposition-map-sha256": (
        "902f9efac77c6dfd68516d9ced5f2737dfc840706706ec793251d296fc09ad1b"
    ),
}
MANIFEST_COLUMNS = (
    "source_file",
    "helper",
    "assertion_name",
    "literal",
    "resolved_target",
    "target_defaulted",
    "disposition",
    "call_sha256",
)


def load_classifier():
    spec = importlib.util.spec_from_file_location("pin_corpus_classifier", CLASSIFIER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def decode_row(row: dict[str, str]) -> dict[str, object]:
    return {
        "source_file": json.loads(row["source_file"]),
        "assertion_name": json.loads(row["assertion_name"]),
        "helper": row["helper"],
        "literal": json.loads(row["literal"]),
        "resolved_target": json.loads(row["resolved_target"]),
        "target_defaulted": row["target_defaulted"] == "true",
        "disposition": row["disposition"],
        "call_sha256": row["call_sha256"],
    }


def site_identity(row: dict[str, object]) -> tuple[object, ...]:
    """A location-free identity stable across unrelated source insertions."""
    return tuple(
        row[column]
        for column in MANIFEST_COLUMNS
        if column not in {"disposition", "call_sha256"}
    )


def compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RedOnRemovalRetirementManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_classifier()

    def test_historical_manifest_freezes_every_call_and_adjudication(self):
        # Break caught: a retirement call is silently added, omitted, or reclassified.
        raw = MANIFEST.read_text(encoding="utf-8")
        metadata = {}
        data = []
        for line in raw.splitlines():
            if line.startswith("# "):
                key, _, value = line[2:].partition(": ")
                metadata[key] = value
            else:
                data.append(line)
        self.assertEqual(BASE_REVISION, metadata["source-revision"])
        for key, digest in EXPECTED_DIGESTS.items():
            self.assertEqual(digest, metadata[key])

        reader = csv.DictReader(io.StringIO("\n".join(data)), delimiter="\t")
        self.assertEqual(MANIFEST_COLUMNS, tuple(reader.fieldnames or ()))
        rows = [decode_row(row) for row in reader]
        self.assertEqual(113, len(rows))
        self.assertEqual(113, len({site_identity(row) for row in rows}))
        self.assertEqual(EXPECTED_DISPOSITIONS, Counter(row["disposition"] for row in rows))
        self.assertEqual(
            EXPECTED_DIGESTS["disposition-map-sha256"],
            metadata["disposition-map-sha256"],
        )

        disposition_lines = [
            "\t".join(
                (
                    compact_json(row["source_file"]),
                    str(row["helper"]),
                    compact_json(row["assertion_name"]),
                    compact_json(row["literal"]),
                    compact_json(row["resolved_target"]),
                    "true" if row["target_defaulted"] else "false",
                    str(row["disposition"]),
                )
            )
            for row in rows
        ]
        disposition_canonical = (
            "source_file\thelper\tassertion_name\tliteral\tresolved_target\ttarget_defaulted\tdisposition\n"
            + "\n".join(sorted(disposition_lines))
            + "\n"
        )
        self.assertEqual(
            EXPECTED_DIGESTS["disposition-map-sha256"],
            sha256_text(disposition_canonical),
        )

        paired = [row for row in rows if row["disposition"] == "redundant_retire"]
        paired_lines = [
            "\t".join(
                (
                    compact_json(row["source_file"]),
                    str(row["helper"]),
                    compact_json(row["assertion_name"]),
                    compact_json(row["literal"]),
                    compact_json(row["resolved_target"]),
                    "true" if row["target_defaulted"] else "false",
                )
            )
            for row in paired
        ]
        paired_canonical = (
            "source_file\thelper\tassertion_name\tliteral\tresolved_target\ttarget_defaulted\n"
            + "\n".join(sorted(paired_lines))
            + "\n"
        )
        self.assertEqual(12_776, len(paired_canonical.encode("utf-8")))
        self.assertEqual(
            EXPECTED_DIGESTS["paired-canonical-sha256"],
            sha256_text(paired_canonical),
        )

        sole = [row for row in rows if row["disposition"] != "redundant_retire"]
        self.assertTrue(all(row["call_sha256"] != "-" for row in sole))
        self.assertTrue(all(row["call_sha256"] == "-" for row in paired))
        self.assertEqual(
            EXPECTED_DIGESTS["sole-call-sha256"],
            sha256_text("\n".join(sorted(row["call_sha256"] for row in sole)) + "\n"),
        )
        sole_pairs = {
            compact_json([row["literal"], row["resolved_target"]]) for row in sole
        }
        self.assertEqual(53, len(sole_pairs))
        self.assertEqual(
            EXPECTED_DIGESTS["sole-distinct-pair-sha256"],
            sha256_text("\n".join(sorted(sole_pairs)) + "\n"),
        )

        historical = subprocess.run(
            ["git", "show", f"{BASE_REVISION}:lib/test/run.sh"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        sites = self.mod.extract_existence_sites(
            historical,
            "lib/test/run.sh",
            str(REPO_ROOT / "lib"),
            self.mod.recover_override_names(historical),
        )
        expected = {
            (
                site.source_file,
                site.helper,
                site.assertion_name,
                site.literal,
                site.resolved_target,
                site.target_defaulted,
            )
            for site in sites
            if site.helper == "assert_pin_red_on_removal"
        }
        self.assertEqual(expected, {site_identity(row) for row in rows})

    def test_current_worktree_adjudications_close_the_classifier_corpus(self):
        # Break caught: a stale key or new unclear pin reaches inventory generation.
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "inventory.tsv"
            tracked = Path(raw) / "tracked-files"
            listed = subprocess.run(
                ["git", "ls-files", "-z"],
                cwd=REPO_ROOT,
                capture_output=True,
                check=True,
            ).stdout.split(b"\0")
            # Model the intended tree with intentionally deleted tracked
            # artifacts omitted: git ls-files continues to report paths deleted
            # from the worktree, but the classifier must not try to read them.
            present = [
                path
                for path in listed
                if path and (REPO_ROOT / path.decode("utf-8")).is_file()
            ]
            tracked.write_bytes(b"\0".join(present) + b"\0")
            result = subprocess.run(
                [
                    sys.executable,
                    str(CLASSIFIER),
                    "--repo-root",
                    str(REPO_ROOT),
                    "--adjudications",
                    "lib/test/pin-corpus-adjudications.tsv",
                    "--tracked-files",
                    str(tracked),
                    "--output",
                    str(output),
                    "--expected-out-of-scope",
                    "0",
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
