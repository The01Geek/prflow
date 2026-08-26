#!/usr/bin/env python3
"""Focused tests for the local DevFlow workflow flight recorder."""

# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import workflow_flight_recorder as recorder
from workflow_flight_recorder import (
    build_event_summary,
    capture_stop_payload,
    detect_occurrences,
    load_registry,
    parse_events,
    resolve_boundaries,
)

REGISTRY = ROOT / "scripts/workflow-flight-recorder-registry.json"


def transcript(*records: dict) -> bytes:
    return ("\n".join(json.dumps(record) for record in records) + "\n").encode()


def user(content: str, timestamp: str = "2026-07-16T01:00:00Z") -> dict:
    return {
        "type": "user",
        "timestamp": timestamp,
        "message": {"role": "user", "content": content},
    }


def assistant_text(content: str, timestamp: str = "2026-07-16T01:01:00Z") -> dict:
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "message": {"role": "assistant", "content": content},
    }


def skill_call(skill: str, args: str = "", timestamp: str = "2026-07-16T01:02:00Z") -> dict:
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": f"skill-{skill}-{timestamp}",
                    "name": "Skill",
                    "input": {"skill": skill, "args": args},
                }
            ],
        },
    }


def patched_git_status(stdout: str | None) -> mock._patch:
    """Return a patch that changes only `git status --porcelain`."""
    run = subprocess.run

    def status_aware_run(command: list[str], *args: object, **kwargs: object) -> subprocess.CompletedProcess:
        if command[-2:] == ["status", "--porcelain"]:
            if stdout is None:
                raise subprocess.CalledProcessError(128, command)
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")
        return run(command, *args, **kwargs)

    return mock.patch.object(recorder.subprocess, "run", side_effect=status_aware_run)


class InventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.sandbox = Path(self.temporary.name)
        self.repository = self.sandbox / "repository"
        self.projects = self.sandbox / "projects"
        self.repository.mkdir()
        self.projects.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repository)], check=True)

    def _project_directory(self, root: Path | None = None) -> Path:
        encoded = str((root or self.repository).resolve()).replace(os.sep, "-")
        project = self.projects / encoded
        project.mkdir(parents=True, exist_ok=True)
        return project

    def _write_session(
        self,
        session_id: str,
        *records: dict,
        project_root: Path | None = None,
        raw_tail: bytes = b"",
    ) -> Path:
        path = self._project_directory(project_root) / f"{session_id}.jsonl"
        path.write_bytes(transcript(*records) + raw_tail)
        return path

    def _record(self, record: dict, *, cwd: Path | None = None, branch: str | None = None) -> dict:
        enriched = dict(record)
        if cwd is not None:
            enriched["cwd"] = str(cwd)
        if branch is not None:
            enriched["gitBranch"] = branch
        return enriched

    def test_inventory_classifies_fixture_matrix_and_sorts_deterministically(self) -> None:
        exact_path = self._write_session(
            "sid-exact",
            self._record(user("/implement 520", "2026-07-16T03:00:00Z"), cwd=self.repository, branch="main"),
            self._record(
                {
                    "type": "assistant",
                    "timestamp": "2026-07-16T03:03:00Z",
                    "model": "claude-opus-4-6",
                    "effort": "high",
                    "message": {"role": "assistant", "content": "private assistant text"},
                },
                cwd=self.repository,
            ),
        )
        wrapped = (
            "<command-message>devflow:create-issue</command-message>"
            "<command-args>inventory native sessions</command-args>"
        )
        self._write_session(
            "sid-wrapped",
            self._record(user(wrapped, "2026-07-16T01:00:00Z"), cwd=self.repository),
        )
        secret_prompt = "Change PR525 to draft, then run /devflow:receiving-code-review 525 SECRET-PROMPT"
        self._write_session(
            "sid-embedded",
            self._record(user(secret_prompt, "2026-07-16T02:00:00Z"), cwd=self.repository),
            self._record(skill_call("devflow:receiving-code-review", "525", "2026-07-16T02:05:00Z"), cwd=self.repository),
        )
        self._write_session(
            "sid-later-only",
            self._record(user("ordinary request", "2026-07-16T00:00:00Z"), cwd=self.repository),
            self._record(user("/review-and-fix 525", "2026-07-16T00:01:00Z"), cwd=self.repository),
        )
        malformed = self._write_session(
            "sid-malformed",
            self._record(user("/implement 999"), cwd=self.repository),
            raw_tail=b"{broken\n",
        )
        other_repository = self.sandbox / "other-repository"
        other_repository.mkdir()
        subprocess.run(["git", "init", "-q", str(other_repository)], check=True)
        self._write_session(
            "sid-unrelated",
            self._record(user("/implement 404"), cwd=other_repository),
            project_root=other_repository,
        )

        result = recorder.inventory_native_transcripts(self.projects, self.repository, REGISTRY)

        self.assertEqual(
            [row.session_id for row in result.sessions],
            ["sid-wrapped", "sid-embedded", "sid-exact"],
        )
        by_id = {row.session_id: row for row in result.sessions}
        self.assertEqual(by_id["sid-exact"].workflow, "implement")
        self.assertEqual(by_id["sid-exact"].subject, {"kind": "issue", "number": 520})
        self.assertEqual(by_id["sid-exact"].native_path, str(exact_path.resolve()))
        self.assertEqual(by_id["sid-exact"].cwd, str(self.repository.resolve()))
        self.assertEqual(by_id["sid-exact"].started_at, "2026-07-16T03:00:00.000Z")
        self.assertEqual(by_id["sid-exact"].finished_at, "2026-07-16T03:03:00.000Z")
        self.assertEqual(by_id["sid-exact"].duration_ms, 180000)
        self.assertEqual(by_id["sid-exact"].longest_gap_ms, 180000)
        self.assertEqual(by_id["sid-exact"].event_count, 2)
        self.assertEqual(by_id["sid-exact"].transcript_bytes, exact_path.stat().st_size)
        self.assertEqual(by_id["sid-exact"].observed_models, ["claude-opus-4-6"])
        self.assertEqual(by_id["sid-exact"].observed_effort, ["high"])
        self.assertEqual(by_id["sid-exact"].branch, "main")
        self.assertEqual(by_id["sid-exact"].association_confidence, "exact")
        self.assertEqual(by_id["sid-exact"].manifest_status, "absent")
        self.assertEqual(by_id["sid-exact"].import_status, "not_imported")
        self.assertEqual(by_id["sid-embedded"].workflow, "receiving-code-review")
        self.assertIsNone(by_id["sid-wrapped"].duration_ms)
        self.assertEqual(result.summary["scanned"], 6)
        self.assertEqual(result.summary["matched"], 3)
        self.assertEqual(result.summary["already_bundled"], 0)
        self.assertEqual(result.summary["unreadable"], 1)
        self.assertEqual(
            result.summary["by_workflow"],
            {"create-issue": 1, "implement": 1, "receiving-code-review": 1},
        )
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0].native_path, str(malformed.resolve()))

        document = recorder.render_inventory_json(result)
        self.assertEqual(
            set(json.loads(document)),
            {"schema_version", "repository_root", "sessions", "errors", "summary"},
        )
        self.assertNotIn(secret_prompt, document)
        self.assertNotIn("SECRET-PROMPT", document)
        self.assertNotIn("inventory native sessions", document)
        self.assertNotIn("private assistant text", document)

    def test_unreadable_transcript_is_an_inventory_error_not_a_crash(self) -> None:
        readable = self._write_session(
            "sid-readable", self._record(user("/implement 520"), cwd=self.repository)
        )
        unreadable = self._write_session(
            "sid-unreadable", self._record(user("/implement 521"), cwd=self.repository)
        )
        # Positive control: both fixtures classify identically, so the only difference
        # driving the error below is that this one cannot be read.
        self.assertTrue(readable.is_file() and unreadable.is_file())

        real_read_bytes = Path.read_bytes

        def deny_one(self_path: Path, *args: object, **kwargs: object) -> bytes:
            if self_path == unreadable:
                raise OSError(13, "Permission denied")
            return real_read_bytes(self_path, *args, **kwargs)

        with mock.patch.object(Path, "read_bytes", deny_one):
            result = recorder.inventory_native_transcripts(self.projects, self.repository, REGISTRY)

        self.assertEqual([row.session_id for row in result.sessions], ["sid-readable"])
        self.assertEqual([error.native_path for error in result.errors], [str(unreadable.resolve())])
        self.assertIn("Permission denied", result.errors[0].error)
        # An unreadable session is scanned but not readable, and the tallies must say so
        # rather than quietly shrinking the denominator.
        self.assertEqual(result.summary["readable"], 1)

    def test_inventory_associates_linked_worktree_by_common_dir(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.repository), "config", "user.email", "inventory@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repository), "config", "user.name", "Inventory Test"],
            check=True,
        )
        (self.repository / "tracked").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repository), "add", "tracked"], check=True)
        subprocess.run(["git", "-C", str(self.repository), "commit", "-qm", "base"], check=True)
        linked = self.sandbox / "linked-worktree"
        subprocess.run(
            ["git", "-C", str(self.repository), "worktree", "add", "-q", "--detach", str(linked)],
            check=True,
        )
        self._write_session(
            "sid-linked",
            self._record(user("/review-and-fix 77"), cwd=linked),
            project_root=linked,
        )

        result = recorder.inventory_native_transcripts(self.projects, self.repository, REGISTRY)

        self.assertEqual([row.session_id for row in result.sessions], ["sid-linked"])
        self.assertEqual(result.sessions[0].cwd, str(linked.resolve()))
        self.assertEqual(result.sessions[0].association_confidence, "exact")

    def test_encoded_directory_fallback_is_uncertain_and_unknowns_remain_none(self) -> None:
        self._write_session(
            "sid-unknown",
            {
                "type": "user",
                "message": {"role": "user", "content": "/create-issue preserve unknowns"},
                "futureNativeField": {"ignored": True},
            },
        )
        storage_root, _ = recorder._shared_storage_root(self.repository)
        manifest = storage_root / ".prflow/tmp/workflow-manifests/sid-unknown.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("{}\n", encoding="utf-8")
        imported = storage_root / ".prflow/tmp/workflow-runs/sid-unknown/transcript.jsonl"
        imported.parent.mkdir(parents=True)
        imported.write_text("already imported\n", encoding="utf-8")

        result = recorder.inventory_native_transcripts(self.projects, self.repository, REGISTRY)

        self.assertEqual(len(result.sessions), 1)
        row = result.sessions[0]
        self.assertEqual(row.association_confidence, "uncertain")
        self.assertIsNone(row.cwd)
        self.assertIsNone(row.started_at)
        self.assertIsNone(row.finished_at)
        self.assertIsNone(row.duration_ms)
        self.assertIsNone(row.longest_gap_ms)
        self.assertIsNone(row.observed_models)
        self.assertIsNone(row.observed_effort)
        self.assertIsNone(row.branch)
        self.assertEqual(row.manifest_status, "present")
        self.assertEqual(row.import_status, "imported")
        self.assertEqual(result.summary["already_bundled"], 1)

    def test_cli_json_is_private_and_table_uses_unavailable_markers(self) -> None:
        secret = "SECRET CLI PROMPT"
        self._write_session(
            "sid-cli",
            self._record(user(f"/implement 88 {secret}", timestamp=""), cwd=self.repository),
        )
        command = [
            sys.executable,
            str(ROOT / "scripts/inventory-workflow-transcripts.py"),
            "--claude-projects-root",
            str(self.projects),
            "--repo-root",
            str(self.repository),
            "--registry",
            str(REGISTRY),
        ]

        table = subprocess.run(command, check=False, text=True, capture_output=True)
        json_result = subprocess.run([*command, "--json"], check=False, text=True, capture_output=True)

        self.assertEqual(table.returncode, 0, table.stderr)
        self.assertIn("sid-cli", table.stdout)
        self.assertIn("unavailable", table.stdout)
        self.assertNotIn(secret, table.stdout + table.stderr)
        self.assertEqual(json_result.returncode, 0, json_result.stderr)
        self.assertEqual(json.loads(json_result.stdout)["sessions"][0]["session_id"], "sid-cli")
        self.assertNotIn(secret, json_result.stdout + json_result.stderr)

    def test_cli_fails_when_projects_root_is_unavailable(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/inventory-workflow-transcripts.py"),
                "--claude-projects-root",
                str(self.sandbox / "missing"),
                "--repo-root",
                str(self.repository),
                "--registry",
                str(REGISTRY),
            ],
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("projects root", result.stderr.lower())

    def test_cli_fails_when_no_meaningful_scan_can_occur(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/inventory-workflow-transcripts.py"),
                "--claude-projects-root",
                str(self.projects),
                "--repo-root",
                str(self.repository),
                "--registry",
                str(REGISTRY),
            ],
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no readable transcript scan", result.stderr.lower())


class RegistryAndOccurrenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = load_registry(REGISTRY)

    def test_registry_has_the_initial_five_workflows(self) -> None:
        self.assertEqual(
            set(self.registry),
            {"implement", "create-issue", "receiving-code-review", "review-and-fix", "review"},
        )

    def test_additive_test_module_mapping_does_not_change_runtime_registry_behavior(self) -> None:
        document = json.loads(REGISTRY.read_text(encoding="utf-8"))
        with_modules = document.copy()
        without_modules = document.copy()
        without_modules.pop("test_modules", None)

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with_path = root / "with-modules.json"
            without_path = root / "without-modules.json"
            with_path.write_text(json.dumps(with_modules), encoding="utf-8")
            without_path.write_text(json.dumps(without_modules), encoding="utf-8")

            registry_with_modules = load_registry(with_path)
            registry_without_modules = load_registry(without_path)

        self.assertEqual(registry_with_modules, registry_without_modules)
        events = parse_events(transcript(user("/devflow:review-and-fix 565")))
        self.assertEqual(
            [item.workflow for item in detect_occurrences(events, registry_with_modules)],
            [item.workflow for item in detect_occurrences(events, registry_without_modules)],
        )

    def test_review_surfaces_cover_the_whole_engine_bundle(self) -> None:
        # #529: the Review engine is a bundle — a root plus gated phase references.
        # Every path that reaches the engine must enumerate the references too, or
        # editing one changes no fingerprint and the recorder under-reports the
        # prompt surface it actually loaded.
        for workflow in ("review", "review-and-fix", "implement"):
            globs = {item.glob for item in self.registry[workflow].surfaces}
            with self.subTest(workflow=workflow):
                self.assertIn("skills/review/SKILL.md", globs)
                self.assertIn("skills/review/phases/*.md", globs)
                self.assertIn(".prflow/prompt-extensions/review.md", globs)

    def test_receiving_code_review_extension_surface_is_recorded(self) -> None:
        # #620: /devflow:review-and-fix loads the receiving-code-review extension at
        # entry (a second always-loaded extension), and /devflow:implement reaches it
        # through the inline engine. The row rides `required: false`, so a dropped or
        # typo'd glob ships desk-green while the recorder under-reports the loaded
        # surface. Bind the registry rows to disk, as the references glob is bound.
        extension_glob = ".prflow/prompt-extensions/receiving-code-review.md"
        for workflow in ("review-and-fix", "implement", "receiving-code-review"):
            with self.subTest(workflow=workflow):
                rows = [
                    item
                    for item in self.registry[workflow].surfaces
                    if item.glob == extension_glob
                ]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].load_class, "extension")
        self.assertTrue((ROOT / extension_glob).is_file())

    def test_review_and_fix_reference_surfaces_resolve_to_the_shipped_files(self) -> None:
        # #530/#539: the references glob rides `required: false`, so a typo'd or
        # stale glob would silently record ZERO surfaces (the census under-reports
        # with no signal). Bind the registry rows to disk: the glob must be present
        # under BOTH parents with load_class "reference", and must resolve to the
        # eight shipped references — never an empty set.
        reference_glob = "skills/review-and-fix/references/*.md"
        for workflow in ("review-and-fix", "implement"):
            with self.subTest(workflow=workflow):
                rows = [
                    item
                    for item in self.registry[workflow].surfaces
                    if item.glob == reference_glob
                ]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].load_class, "reference")
        resolved = sorted(path.name for path in ROOT.glob(reference_glob))  # tree-walk-ok: reference_glob resolves under skills/, which no worktree lives under
        self.assertEqual(
            resolved,
            [
                "convergence.md",
                "error-handling.md",
                "fix-delta-gate.md",
                "fixing.md",
                "loop-control.md",
                "loop-exit.md",
                "pre-fix-gates.md",
                "shadow-review.md",
            ],
        )

    def test_each_user_command_creates_a_top_level_occurrence(self) -> None:
        cases = [
            ("/devflow:implement 520", "implement", {"kind": "issue", "number": 520}),
            ("/devflow:create-issue improve local capture", "create-issue", {"kind": "topic", "value": "improve local capture"}),
            ("/devflow:receiving-code-review 42", "receiving-code-review", {"kind": "pull_request", "number": 42}),
            ("/devflow:review-and-fix #77", "review-and-fix", {"kind": "pull_request", "number": 77}),
            ("/devflow:review #88", "review", {"kind": "pull_request", "number": 88}),
        ]
        for command, workflow, subject in cases:
            with self.subTest(command=command):
                found = detect_occurrences(parse_events(transcript(user(command))), self.registry)
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0].workflow, workflow)
                self.assertEqual(found[0].mode, "top-level")
                self.assertEqual(found[0].subject, subject)
                self.assertEqual(found[0].invocation_source, "user_command")

    def test_short_user_commands_create_top_level_occurrences(self) -> None:
        cases = [
            ("/implement 520", "implement", {"kind": "issue", "number": 520}),
            ("/create-issue improve local capture", "create-issue", {"kind": "topic", "value": "improve local capture"}),
            ("/review-and-fix #77", "review-and-fix", {"kind": "pull_request", "number": 77}),
            ("/review #88", "review", {"kind": "pull_request", "number": 88}),
        ]
        for command, workflow, subject in cases:
            with self.subTest(command=command):
                found = detect_occurrences(parse_events(transcript(user(command))), self.registry)
                self.assertEqual(
                    [(item.workflow, item.mode, item.subject) for item in found],
                    [(workflow, "top-level", subject)],
                )

    def test_review_command_prefix_does_not_swallow_review_and_fix(self) -> None:
        # #540: `review` is a token-prefix of `review-and-fix`, so their
        # disambiguation rests on `_user_invocation` requiring whitespace between
        # the command and its args — `/devflow:review` cannot match
        # `/devflow:review-and-fix` because `-` is not that separator. Registry
        # iteration order currently masks this (review-and-fix is enumerated
        # before review, so it wins regardless of the separator), which makes the
        # separator the *only* thing standing between a reorder and a silent
        # misclassification. Pin it with review enumerated FIRST, so the guard
        # under test is the `\s+` separator itself and a regression that makes it
        # optional turns this RED (verified by mutation). The reversed ordering is
        # a proper subset: it also proves the shorter command still classifies its
        # own input, and the natural-order rows below add the short-form aliases.
        review_first = {"review": self.registry["review"], **self.registry}
        for registry, label in ((review_first, "review-first"), (self.registry, "natural")):
            for command, workflow in (
                ("/devflow:review-and-fix #77", "review-and-fix"),
                ("/review-and-fix #77", "review-and-fix"),
                ("/devflow:review #77", "review"),
                ("/review #77", "review"),
            ):
                with self.subTest(order=label, command=command):
                    found = detect_occurrences(
                        parse_events(transcript(user(command))), registry
                    )
                    self.assertEqual(
                        [(item.workflow, item.subject) for item in found],
                        [(workflow, {"kind": "pull_request", "number": 77})],
                    )

    def test_embedded_first_prompt_is_top_level_only_when_skill_call_corroborates(self) -> None:
        events = parse_events(
            transcript(
                user("Change PR525 to draft, then run /devflow:receiving-code-review 525"),
                skill_call("devflow:receiving-code-review", "525"),
            )
        )
        found = recorder.classify_inventory_occurrences(events, self.registry)
        self.assertEqual(
            [(item.workflow, item.mode, item.subject) for item in found],
            [("receiving-code-review", "top-level", {"kind": "pull_request", "number": 525})],
        )
        self.assertEqual(found[0].start_event, events[0].index)

    def test_embedded_first_prompt_without_matching_skill_call_does_not_classify(self) -> None:
        events = parse_events(
            transcript(user("Please document /devflow:receiving-code-review 525 for the team"))
        )
        self.assertEqual(recorder.classify_inventory_occurrences(events, self.registry), [])

    def test_matching_command_in_a_later_user_turn_does_not_classify(self) -> None:
        events = parse_events(
            transcript(
                user("Change PR525 to draft"),
                user("/devflow:receiving-code-review 525", "2026-07-16T01:01:00Z"),
                skill_call("devflow:receiving-code-review", "525"),
            )
        )
        self.assertEqual(recorder.classify_inventory_occurrences(events, self.registry), [])

    def test_tool_result_only_user_content_is_not_the_first_authoritative_message(self) -> None:
        events = parse_events(
            transcript(
                {
                    "type": "user",
                    "timestamp": "2026-07-16T01:00:00Z",
                    "message": {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "tool-1",
                                "content": "/implement 999",
                            }
                        ],
                    },
                },
                user("/review-and-fix 525", "2026-07-16T01:01:00Z"),
            )
        )
        self.assertEqual(recorder.first_authoritative_user_event(events), events[1])
        found = recorder.classify_inventory_occurrences(events, self.registry)
        self.assertEqual(
            [(item.workflow, item.mode, item.subject, item.start_event) for item in found],
            [("review-and-fix", "top-level", {"kind": "pull_request", "number": 525}, 1)],
        )

    def test_nested_skill_is_parented_to_top_level_implement(self) -> None:
        events = parse_events(
            transcript(
                user("/devflow:implement 520"),
                skill_call("review-and-fix", "--push-each-iteration"),
                skill_call("review-and-fix", "--push-each-iteration", "2026-07-16T01:03:00Z"),
            )
        )
        found = detect_occurrences(events, self.registry)
        self.assertEqual([item.occurrence_id for item in found], ["implement-1", "review-and-fix-1", "review-and-fix-2"])
        self.assertEqual(found[1].mode, "nested")
        self.assertEqual(found[1].parent_occurrence_id, "implement-1")
        self.assertEqual(found[2].parent_occurrence_id, "implement-1")

    def test_assistant_prose_and_tool_output_do_not_classify(self) -> None:
        records = [
            assistant_text("Try /devflow:review-and-fix 77"),
            user("I often run /devflow:review-and-fix 77"),
            {
                "type": "tool_result",
                "timestamp": "2026-07-16T01:02:00Z",
                "content": "/devflow:create-issue not an invocation",
            },
        ]
        self.assertEqual(detect_occurrences(parse_events(transcript(*records)), self.registry), [])

    def test_nested_parent_does_not_cross_a_new_top_level_root(self) -> None:
        events = parse_events(
            transcript(
                user("/devflow:implement 520"),
                user("/devflow:create-issue improve capture", "2026-07-16T01:01:00Z"),
                skill_call("review-and-fix", "520"),
            )
        )
        found = detect_occurrences(events, self.registry)
        self.assertIsNone(found[-1].parent_occurrence_id)

    def test_message_role_is_authoritative_over_contradictory_type(self) -> None:
        contradictory = skill_call("review-and-fix", "520")
        contradictory["message"]["role"] = "user"
        self.assertEqual(detect_occurrences(parse_events(transcript(contradictory)), self.registry), [])

    def test_command_markup_is_user_evidence(self) -> None:
        content = (
            "<command-message>devflow:implement</command-message>"
            "<command-args>521</command-args>"
        )
        found = detect_occurrences(parse_events(transcript(user(content))), self.registry)
        self.assertEqual(found[0].subject, {"kind": "issue", "number": 521})

    def test_transcripts_with_no_events_are_rejected_rather_than_read_as_empty(self) -> None:
        for case, raw in {"empty": b"", "newlines only": b"\n\n", "whitespace": b"  \n\t\n"}.items():
            with self.subTest(case=case):
                # Fail closed: a transcript that yields no events is unusable evidence,
                # not a session that legitimately did nothing.
                with self.assertRaisesRegex(ValueError, "transcript JSONL is empty"):
                    parse_events(raw)

    def test_non_object_records_are_rejected_naming_the_line(self) -> None:
        for case, raw in {
            "array record": b'["not an object"]\n',
            "scalar record": b"42\n",
            "null record": b"null\n",
        }.items():
            with self.subTest(case=case):
                # A positive control on the same shape: the record is well-formed JSON, so
                # the rejection can only come from the not-an-object guard under test.
                self.assertIsInstance(json.loads(raw), (list, int, type(None)))
                with self.assertRaisesRegex(ValueError, "record 1 is not an object"):
                    parse_events(raw)

    def test_naive_and_unparseable_timestamps_yield_no_event_time(self) -> None:
        for case, timestamp in {
            "naive": "2026-07-16T01:00:00",
            "unparseable": "not-a-timestamp",
            "empty": "",
        }.items():
            with self.subTest(case=case):
                events = parse_events(transcript(user("/implement 520", timestamp)))
                # A naive timestamp has no zone, so it cannot be placed on the UTC line
                # the recorder compares against: it is unknown, never assumed to be UTC.
                self.assertEqual(len(events), 1)
                self.assertIsNone(events[0].timestamp_ms)
        aware = parse_events(transcript(user("/implement 520", "2026-07-16T01:00:00Z")))
        self.assertIsNotNone(aware[0].timestamp_ms)

    def test_malformed_jsonl_tail_is_rejected(self) -> None:
        raw = transcript(user("/devflow:implement 520")) + b"{broken\n"
        with self.assertRaisesRegex(ValueError, "line 2"):
            parse_events(raw)


class TimingAndSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = load_registry(REGISTRY)

    def test_exact_completion_marker_sets_normalized_boundary(self) -> None:
        records = [
            user("/devflow:implement 520", "2026-07-15T19:00:00-06:00"),
            skill_call("review-and-fix", "520", "2026-07-16T01:03:00Z"),
            {
                "type": "assistant",
                "timestamp": "2026-07-16T01:05:00.125Z",
                "workflow_completion": {"workflow": "review-and-fix"},
                "message": {"role": "assistant", "content": "done"},
            },
        ]
        events = parse_events(transcript(*records))
        occurrences = detect_occurrences(events, self.registry)
        resolve_boundaries(events, occurrences)
        implement, review = occurrences
        self.assertEqual(implement.started_at, "2026-07-16T01:00:00.000Z")
        self.assertEqual(review.finished_at, "2026-07-16T01:05:00.125Z")
        self.assertEqual(review.duration_ms, 120125)
        self.assertEqual(review.boundary_confidence, "exact")
        self.assertEqual(review.finish_timestamp_source, "explicit_completion_marker")

    def test_parent_continuation_is_approximate_and_missing_time_stays_unknown(self) -> None:
        records = [
            user("/devflow:implement 520"),
            skill_call("review-and-fix", "520", timestamp=""),
            {
                "type": "assistant",
                "timestamp": "2026-07-16T01:04:00Z",
                "parent_continuation": "implement",
                "message": {"role": "assistant", "content": "continuing parent"},
            },
        ]
        events = parse_events(transcript(*records))
        occurrences = detect_occurrences(events, self.registry)
        resolve_boundaries(events, occurrences)
        nested = occurrences[1]
        self.assertEqual(nested.end_event, 2)
        self.assertEqual(nested.boundary_confidence, "approximate")
        self.assertEqual(nested.finished_at, "2026-07-16T01:04:00.000Z")
        self.assertIsNone(nested.duration_ms)

    def test_terminal_stop_is_an_approximate_real_boundary_with_occurrence_model_effort(self) -> None:
        records = [
            user("/devflow:implement 520", "2026-07-16T01:00:00Z"),
            {
                "type": "assistant",
                "timestamp": "2026-07-16T01:00:01Z",
                "model": "claude-opus-4-6",
                "effort": "high",
                "message": {"role": "assistant", "content": "working"},
            },
            assistant_text("stopped", "2026-07-16T01:05:00Z"),
        ]
        events = parse_events(transcript(*records))
        occurrences = detect_occurrences(events, self.registry)
        resolve_boundaries(events, occurrences)
        occurrence = occurrences[0]
        self.assertEqual(occurrence.finish_timestamp_source, "terminal_stop_boundary")
        self.assertEqual(occurrence.boundary_confidence, "approximate")
        self.assertEqual(occurrence.finished_at, "2026-07-16T01:05:00.000Z")
        self.assertEqual(occurrence.duration_ms, 300000)
        self.assertEqual(occurrence.observed_models, ["claude-opus-4-6"])
        self.assertEqual(occurrence.observed_effort, ["high"])
        self.assertEqual(occurrence.model_effort_source, "events_within_boundary")

    def test_next_top_level_root_bounds_prior_occurrence_at_previous_event(self) -> None:
        records = [
            user("/devflow:implement 520", "2026-07-16T01:00:00Z"),
            {"type": "assistant", "timestamp": "2026-07-16T01:01:00Z", "model": "model-a", "message": {"role": "assistant", "content": "implement work"}},
            user("/devflow:create-issue another topic", "2026-07-16T01:02:00Z"),
            {"type": "assistant", "timestamp": "2026-07-16T01:03:00Z", "model": "model-b", "message": {"role": "assistant", "content": "issue work"}},
        ]
        events = parse_events(transcript(*records))
        occurrences = detect_occurrences(events, self.registry)
        resolve_boundaries(events, occurrences)
        implement, create_issue = occurrences
        self.assertEqual(implement.end_event, 1)
        self.assertEqual(implement.finish_timestamp_source, "next_top_level_boundary")
        self.assertEqual(implement.observed_models, ["model-a"])
        self.assertNotIn("model-b", implement.observed_models)
        self.assertEqual(create_issue.finish_timestamp_source, "terminal_stop_boundary")

    def test_summary_records_model_effort_usage_tools_and_gaps(self) -> None:
        records = [
            user("/devflow:implement 520"),
            {
                "type": "assistant",
                "timestamp": "2026-07-16T01:00:01Z",
                "model": "claude-opus-4-6",
                "effort": "high",
                "usage": {"input_tokens": 120, "output_tokens": 30},
                "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "false"}}]},
            },
            {
                "type": "user",
                "timestamp": "2026-07-16T01:00:03Z",
                "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "permission denied"}]},
            },
            {
                "type": "assistant",
                "timestamp": "2026-07-16T01:00:04Z",
                "model": "claude-opus-4-6",
                "effort": "high",
                "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "false"}}]},
            },
            {
                "type": "assistant",
                "timestamp": "2026-07-16T01:10:04Z",
                "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "a1", "name": "Agent", "input": {"prompt": "review"}}]},
            },
            {"type": "system", "timestamp": "2026-07-16T01:10:05Z", "subtype": "compact_boundary", "message": {"role": "system", "content": "summary omitted"}},
        ]
        events = parse_events(transcript(*records))
        occurrences = detect_occurrences(events, self.registry)
        summary = build_event_summary(events, occurrences)
        self.assertEqual(summary["model_effort"]["observed_models"], ["claude-opus-4-6"])
        self.assertEqual(summary["model_effort"]["observed_effort"], ["high"])
        self.assertEqual(summary["usage"]["shape"], "real")
        self.assertEqual(summary["usage"]["figures"]["input_tokens"], 120)
        self.assertEqual(summary["tool_calls"]["by_name"], {"Agent": 1, "Bash": 2})
        self.assertEqual(summary["tool_calls"]["failed"], 1)
        self.assertEqual(summary["tool_calls"]["permission_denials"], 1)
        self.assertEqual(summary["tool_calls"]["equivalent_retries"], 1)
        self.assertEqual(summary["tool_calls"]["paired_duration_count"], 1)
        self.assertEqual(summary["subagents"]["dispatched"], 1)
        self.assertEqual(summary["compactions"]["count"], 1)
        self.assertEqual(summary["gaps"]["longest_ms"], 600000)
        self.assertNotIn("permission denied", json.dumps(summary))

    def test_placeholder_usage_and_decreasing_time_are_not_claimed_real(self) -> None:
        records = [
            {"type": "assistant", "timestamp": "2026-07-16T01:00:02Z", "usage": {"input_tokens": 0, "output_tokens": 0}, "message": {"role": "assistant", "content": "a"}},
            {"type": "assistant", "timestamp": "2026-07-16T01:00:01Z", "message": {"role": "assistant", "content": "b"}},
        ]
        summary = build_event_summary(parse_events(transcript(*records)), [])
        self.assertEqual(summary["usage"]["shape"], "placeholder")
        self.assertIsNone(summary["usage"]["figures"])
        self.assertIsNone(summary["gaps"]["longest_ms"])
        self.assertTrue(any(item["kind"] == "decreasing_timestamp" for item in summary["evidence"]))


class ManifestObserverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repository"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "config", "user.email", "observer@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.root), "config", "user.name", "Observer Test"],
            check=True,
        )
        for relative in [
            "skills/implement/SKILL.md",
            "skills/implement/phases/setup.md",
            "skills/review/SKILL.md",
            "skills/review-and-fix/SKILL.md",
            "skills/docs/SKILL.md",
        ]:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# observer {relative}\n", encoding="utf-8")
        (self.root / ".claude").mkdir()
        (self.root / ".claude/settings.local.json").write_text(
            json.dumps({"outputStyle": "Default", "verbose": True}),
            encoding="utf-8",
        )
        (self.root / ".claude-plugin").mkdir()
        (self.root / ".claude-plugin/plugin.json").write_text(
            json.dumps({"name": "devflow", "version": "9.8.7"}),
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "fixture"], check=True)
        self.head_sha = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.strip()

    def _payload(self, prompt: str, session_id: str = "sid-manifest") -> dict:
        return {
            "session_id": session_id,
            "cwd": str(self.root),
            "transcript_path": str(self.root / "must-not-exist.jsonl"),
            "user_prompt": prompt,
        }

    def _capture(self, prompt: str, session_id: str = "sid-manifest") -> tuple[dict, dict]:
        result = recorder.capture_prompt_manifest(self._payload(prompt, session_id), REGISTRY)
        manifest_path = self.root / f".prflow/tmp/workflow-manifests/{session_id}.json"
        return result, json.loads(manifest_path.read_text(encoding="utf-8"))

    def test_exact_wrapper_and_embedded_prompts_create_provisional_candidates(self) -> None:
        cases = [
            (
                "/devflow:implement 525",
                "implement",
                {"kind": "issue", "number": 525},
                "exact_user_command",
            ),
            (
                ("<command-message>devflow:review-and-fix</command-message>"
                "<command-args>#77</command-args>"),
                "review-and-fix",
                {"kind": "pull_request", "number": 77},
                "command_markup",
            ),
            (
                "Make PR 42 draft, then run /devflow:receiving-code-review 42",
                "receiving-code-review",
                {"kind": "pull_request", "number": 42},
                "embedded_user_command_candidate",
            ),
        ]
        for index, (prompt, workflow, subject, evidence) in enumerate(cases):
            with self.subTest(prompt=prompt):
                result, manifest = self._capture(prompt, f"sid-candidate-{index}")
                self.assertTrue(result["captured"])
                self.assertEqual(
                    manifest["candidate"],
                    {
                        "workflow": workflow,
                        "subject": subject,
                        "invocation_evidence": evidence,
                        "provisional": True,
                    },
                )
                self.assertNotIn(prompt, json.dumps(manifest))

    def test_manifest_snapshots_git_config_version_prompt_surfaces_and_unknown_model_effort(self) -> None:
        _, manifest = self._capture("/implement 525")

        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["session_id"], "sid-manifest")
        self.assertEqual(manifest["native_transcript_path"], str(self.root / "must-not-exist.jsonl"))
        self.assertRegex(manifest["submitted_at"], r"^\d{4}-\d{2}-\d{2}T")
        self.assertEqual(manifest["cwd"], str(self.root.resolve()))
        self.assertEqual(manifest["repository_root"], str(self.root.resolve()))
        self.assertEqual(manifest["storage_root"], str(self.root.resolve()))
        self.assertEqual(manifest["storage_root_source"], "git_common_dir_parent")
        self.assertEqual(manifest["git"]["head_sha"], self.head_sha)
        self.assertIsInstance(manifest["git"]["branch"], str)
        self.assertFalse(manifest["git"]["dirty_tree"])
        self.assertEqual(manifest["prflow_version"], {"value": "9.8.7", "source": "plugin_manifest"})
        self.assertEqual(
            manifest["claude_configuration"]["outputStyle"],
            {"value": "Default", "source": "project_local_settings", "effective": False},
        )
        self.assertIn("provider", manifest)
        self.assertEqual(
            manifest["model_effort"],
            {
                "requested_model": None,
                "requested_model_source": None,
                "requested_effort": None,
                "requested_effort_source": None,
            },
        )
        self.assertEqual(manifest["prompt_surfaces"]["schema_version"], 1)
        self.assertIn("implement", manifest["prompt_surfaces"]["fingerprints"])
        surface = next(
            item
            for item in manifest["prompt_surfaces"]["surfaces"]
            if item["path"] == "skills/implement/SKILL.md"
        )
        self.assertGreater(surface["bytes"], 0)
        self.assertGreater(surface["lines"], 0)
        self.assertGreater(surface["words"], 0)
        self.assertGreater(surface["approx_tokens"], 0)
        self.assertRegex(surface["sha256"], r"^[0-9a-f]{64}$")

        self.assertFalse((self.root / "must-not-exist.jsonl").exists())
        self.assertFalse((self.root / ".prflow/tmp/workflow-runs").exists())
        self.assertFalse(any(self.root.rglob("transcript.jsonl")))  # tree-walk-ok: self.root is a per-test sandbox, not the repository root

    def test_manifest_dirty_tree_distinguishes_clean_dirty_and_failed_status(self) -> None:
        cases = [
            ("", False),
            (" M skills/implement/SKILL.md\n", True),
            (None, None),
        ]
        for index, (status_stdout, expected) in enumerate(cases):
            with self.subTest(status_stdout=status_stdout):
                with patched_git_status(status_stdout):
                    _, manifest = self._capture("/implement 525", f"sid-status-{index}")
                self.assertIs(manifest["git"]["dirty_tree"], expected)

    def test_payload_supplied_model_effort_and_prompt_alias_are_recorded(self) -> None:
        payload = self._payload("ignored")
        payload.pop("user_prompt")
        payload.update(
            {
                "prompt": "/review-and-fix 91",
                "model": "claude-opus-test",
                "effort": "high",
                "claude_code_version": "1.2.3",
            }
        )

        result = recorder.capture_prompt_manifest(payload, REGISTRY)
        manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))

        self.assertEqual(manifest["candidate"]["workflow"], "review-and-fix")
        self.assertEqual(manifest["model_effort"]["requested_model"], "claude-opus-test")
        self.assertEqual(manifest["model_effort"]["requested_model_source"], "user_prompt_submit_payload")
        self.assertEqual(manifest["model_effort"]["requested_effort"], "high")
        self.assertEqual(manifest["model_effort"]["requested_effort_source"], "user_prompt_submit_payload")
        self.assertEqual(
            manifest["claude_code_version"],
            {"value": "1.2.3", "source": "user_prompt_submit_payload"},
        )

    def test_declared_model_effort_fills_gaps_but_never_overrides_the_payload(self) -> None:
        declaration = {
            "DEVFLOW_RECORDER_MODEL": "declared-model",
            "DEVFLOW_RECORDER_EFFORT": "declared-effort",
        }

        with mock.patch.dict(os.environ, declaration):
            payload = self._payload("/implement 525", "sid-declared")
            result = recorder.capture_prompt_manifest(payload, REGISTRY)
        declared = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))["model_effort"]

        # The documented launch-line declaration survives when the host reports nothing.
        self.assertEqual(declared["requested_model"], "declared-model")
        self.assertEqual(declared["requested_model_source"], "explicit_recorder_environment")
        self.assertEqual(declared["requested_effort"], "declared-effort")
        self.assertEqual(declared["requested_effort_source"], "explicit_recorder_environment")

        with mock.patch.dict(os.environ, declaration):
            payload = self._payload("/implement 525", "sid-observed")
            payload.update({"model": "observed-model", "effort": "observed-effort"})
            result = recorder.capture_prompt_manifest(payload, REGISTRY)
        observed = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))["model_effort"]

        # An observation is stronger evidence than a declaration, so it wins outright.
        self.assertEqual(observed["requested_model"], "observed-model")
        self.assertEqual(observed["requested_model_source"], "user_prompt_submit_payload")
        self.assertEqual(observed["requested_effort"], "observed-effort")
        self.assertEqual(observed["requested_effort_source"], "user_prompt_submit_payload")

    def test_linked_worktree_stores_manifest_in_shared_checkout(self) -> None:
        linked = Path(self.temporary.name) / "linked"
        subprocess.run(
            ["git", "-C", str(self.root), "worktree", "add", "-q", "--detach", str(linked)],
            check=True,
        )
        payload = self._payload("/implement 88", "sid-linked-manifest")
        payload["cwd"] = str(linked)
        payload["transcript_path"] = str(linked / "native.jsonl")

        result = recorder.capture_prompt_manifest(payload, REGISTRY)

        central = self.root.resolve() / ".prflow/tmp/workflow-manifests/sid-linked-manifest.json"
        self.assertEqual(Path(result["manifest"]), central)
        self.assertTrue(central.is_file())
        self.assertFalse((linked / ".prflow/tmp/workflow-manifests").exists())
        manifest = json.loads(central.read_text(encoding="utf-8"))
        self.assertEqual(manifest["repository_root"], str(linked.resolve()))
        self.assertEqual(manifest["storage_root"], str(self.root.resolve()))

    def test_non_candidate_and_multiple_embedded_candidates_create_no_artifact(self) -> None:
        cases = [
            "ordinary prompt",
            "run /implement 1, then /review-and-fix 2",
        ]
        for index, prompt in enumerate(cases):
            with self.subTest(prompt=prompt):
                session_id = f"sid-none-{index}"
                result = recorder.capture_prompt_manifest(self._payload(prompt, session_id), REGISTRY)
                self.assertEqual(result, {"captured": False, "session_id": session_id})
                self.assertFalse(
                    (self.root / f".prflow/tmp/workflow-manifests/{session_id}.json").exists()
                )

    def test_unsafe_or_malformed_payloads_fail_without_artifacts(self) -> None:
        cases = [
            None,
            [],
            {},
            self._payload("/implement 1", "../unsafe"),
            {**self._payload("/implement 1"), "cwd": 7},
            {**self._payload("/implement 1"), "cwd": str(self.root / "missing")},
            {**self._payload("/implement 1"), "transcript_path": ""},
            {**self._payload("/implement 1"), "transcript_path": 7},
            {**self._payload("/implement 1"), "user_prompt": 7},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    recorder.capture_prompt_manifest(payload, REGISTRY)
        self.assertFalse((self.root / ".prflow/tmp/workflow-manifests").exists())
        self.assertFalse((self.root / ".prflow/tmp/workflow-runs").exists())

    def _run_entry(self, entry: Path, raw: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(entry)],
            input=raw,
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )

    def test_thin_entry_point_is_fail_open_for_success_and_every_failure(self) -> None:
        entry = ROOT / "scripts/capture-workflow-manifest.py"
        manifests = self.root / ".prflow/tmp/workflow-manifests"

        # Positive control: this fixture differs from the failure cases below in exactly
        # the one property under test, so a failure case rejected by some unrelated
        # precondition cannot masquerade as the rejection being asserted.
        result = self._run_entry(entry, json.dumps(self._payload("/implement 525", "sid-entry")))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((manifests / "sid-entry.json").is_file())

        failures = {
            "malformed json": "{malformed",
            "non-object payload": "[]",
            "unsafe session id": json.dumps(self._payload("/implement 1", "../unsafe")),
            "cwd outside any repository": json.dumps(
                {**self._payload("/implement 1"), "cwd": str(self.root / "missing")}
            ),
        }
        before = sorted(path.name for path in manifests.iterdir())
        for case, raw in failures.items():
            with self.subTest(case=case):
                result = self._run_entry(entry, raw)
                # Fail-open: never block the prompt, but leave a breadcrumb and no artifact.
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("devflow: workflow-manifest-observer:", result.stderr)
                self.assertEqual(sorted(path.name for path in manifests.iterdir()), before)
        self.assertFalse((self.root / ".prflow/tmp/workflow-runs").exists())

    def test_stop_entry_point_is_fail_open_when_capture_itself_raises(self) -> None:
        entry = ROOT / "scripts/capture-implement-session.py"

        # A malformed payload never reaches capture_stop_payload, so drive the observer's
        # broad except through the capture call itself rather than through json.load.
        with mock.patch.object(recorder, "capture_stop_payload", side_effect=RuntimeError("boom")):
            code = recorder.fail_open_main(REGISTRY, io.StringIO(json.dumps(self._payload("/implement 1"))))
        self.assertEqual(code, 0)

        for case, raw in {"malformed json": "{malformed", "non-object payload": "[]"}.items():
            with self.subTest(case=case):
                result = self._run_entry(entry, raw)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("workflow-flight-recorder:", result.stderr)
        self.assertFalse((self.root / ".prflow/tmp/workflow-runs").exists())


class ImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.sandbox = Path(self.temporary.name)
        self.repository = self.sandbox / "repository"
        self.projects = self.sandbox / "projects"
        self.repository.mkdir()
        self.projects.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repository)], check=True)
        subprocess.run(
            ["git", "-C", str(self.repository), "config", "user.email", "import@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repository), "config", "user.name", "Import Test"],
            check=True,
        )
        for relative in [
            "skills/implement/SKILL.md",
            "skills/implement/phases/setup.md",
            "skills/review/SKILL.md",
            "skills/review-and-fix/SKILL.md",
            "skills/docs/SKILL.md",
        ]:
            path = self.repository / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# import {relative}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repository), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repository), "commit", "-qm", "fixture"], check=True)

    def _native_path(self, session_id: str, directory: str = "native") -> Path:
        project = self.projects / directory
        project.mkdir(parents=True, exist_ok=True)
        return project / f"{session_id}.jsonl"

    def _record(self, record: dict) -> dict:
        return {**record, "cwd": str(self.repository)}

    def _import(self, session_id: str) -> Path:
        self.assertTrue(
            hasattr(recorder, "import_inventory_session"),
            "explicit native import is not implemented",
        )
        return recorder.import_inventory_session(
            session_id,
            self.projects,
            self.repository,
            REGISTRY,
        )

    def test_import_refreshes_short_issue_525_bundle_from_native_tail_and_uses_start_manifest(self) -> None:
        session_id = "issue-525-session"
        first_prompt = "Change PR525 to draft, then run /devflow:receiving-code-review 525"
        records = [
            self._record(user(first_prompt, "2026-07-15T19:00:00Z")),
            self._record(
                skill_call(
                    "devflow:receiving-code-review",
                    "525",
                    "2026-07-15T19:01:00Z",
                )
            ),
            self._record(assistant_text("reviewing", "2026-07-15T19:02:00Z")),
            self._record(assistant_text("ISSUE-525-NATIVE-FINAL-TAIL", "2026-07-15T19:03:00Z")),
        ]
        native = self._native_path(session_id)
        native.write_bytes(transcript(*records))
        native.chmod(0o640)
        source_bytes = native.read_bytes()
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        source_mode = native.stat().st_mode & 0o777

        manifest_result = recorder.capture_prompt_manifest(
            {
                "session_id": session_id,
                "cwd": str(self.repository),
                "transcript_path": str(native),
                "user_prompt": first_prompt,
                "model": "claude-start-model",
                "effort": "high",
            },
            REGISTRY,
        )
        manifest_path = Path(manifest_result["manifest"])
        start_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        start_fingerprint = start_manifest["prompt_surfaces"]["fingerprints"]["receiving-code-review"]
        (self.repository / "skills/review/SKILL.md").write_text(
            "# changed only after UserPromptSubmit\n",
            encoding="utf-8",
        )

        bundle = self.repository.resolve() / ".prflow/tmp/workflow-runs" / session_id
        bundle.mkdir(parents=True)
        (bundle / "transcript.jsonl").write_bytes(transcript(*records[:3]))
        (bundle / "stop-attempts.jsonl").write_text(
            '{"result":"historical_partial","source":"stop_observer"}\n',
            encoding="utf-8",
        )
        bundle.chmod(0o755)
        (bundle / "transcript.jsonl").chmod(0o644)
        (bundle / "stop-attempts.jsonl").chmod(0o644)

        imported = self._import(session_id)

        self.assertEqual(imported, bundle)
        self.assertTrue(native.is_file())
        self.assertEqual(native.read_bytes(), source_bytes)
        self.assertEqual(hashlib.sha256(native.read_bytes()).hexdigest(), source_hash)
        self.assertEqual(native.stat().st_mode & 0o777, source_mode)
        destination = bundle / "transcript.jsonl"
        self.assertEqual(destination.read_bytes(), source_bytes)
        self.assertEqual(hashlib.sha256(destination.read_bytes()).hexdigest(), source_hash)
        self.assertIn(b"ISSUE-525-NATIVE-FINAL-TAIL", destination.read_bytes())
        occurrences = json.loads((bundle / "occurrences.json").read_text(encoding="utf-8"))
        self.assertEqual(len(occurrences), 1)
        self.assertEqual(occurrences[0]["workflow"], "receiving-code-review")
        self.assertEqual(occurrences[0]["mode"], "top-level")
        self.assertEqual(occurrences[0]["subject"], {"kind": "pull_request", "number": 525})
        prompt_surfaces = json.loads((bundle / "prompt-surfaces.json").read_text(encoding="utf-8"))
        self.assertEqual(
            prompt_surfaces["fingerprints"]["receiving-code-review"],
            start_fingerprint,
        )
        summary = json.loads((bundle / "event-summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["model_effort"]["requested_model"], "claude-start-model")
        self.assertEqual(summary["model_effort"]["requested_model_source"], "user_prompt_submit_payload")
        self.assertEqual(summary["model_effort"]["requested_effort"], "high")
        attempts = [
            json.loads(line)
            for line in (bundle / "stop-attempts.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[-1]["source"], "explicit_import")
        self.assertEqual(attempts[-1]["result"], "captured")
        self.assertEqual(attempts[-1]["transcript_sha256"], source_hash)

        self.assertEqual(manifest_path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(manifest_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(bundle.stat().st_mode & 0o777, 0o700)
        for artifact in bundle.iterdir():
            if artifact.is_file():
                self.assertEqual(artifact.stat().st_mode & 0o777, 0o600, artifact.name)

    def test_import_retains_direct_root_and_later_nested_occurrences(self) -> None:
        session_id = "direct-root-with-nested"
        self._native_path(session_id).write_bytes(
            transcript(
                self._record(user("/devflow:implement 525", "2026-07-15T18:00:00Z")),
                self._record(
                    skill_call("review-and-fix", "525", "2026-07-15T18:01:00Z")
                ),
            )
        )

        bundle = self._import(session_id)

        occurrences = json.loads((bundle / "occurrences.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [
                (item["workflow"], item["mode"], item["parent_occurrence_id"])
                for item in occurrences
            ],
            [
                ("implement", "top-level", None),
                ("review-and-fix", "nested", "implement-1"),
            ],
        )
        metadata = json.loads((bundle / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["occurrence_count"], 2)
        summary = json.loads((bundle / "event-summary.json").read_text(encoding="utf-8"))
        self.assertEqual(
            summary["workflow_invocations"],
            {
                "implement": {"top-level": 1, "nested": 0},
                "review-and-fix": {"top-level": 0, "nested": 1},
            },
        )

    def test_import_promotes_embedded_root_and_parents_later_nested_occurrence(self) -> None:
        session_id = "embedded-root-with-nested"
        self._native_path(session_id).write_bytes(
            transcript(
                self._record(
                    user(
                        "Please run /devflow:implement 525 now",
                        "2026-07-15T18:00:00Z",
                    )
                ),
                self._record(skill_call("implement", "525", "2026-07-15T18:01:00Z")),
                self._record(
                    skill_call("review-and-fix", "525", "2026-07-15T18:02:00Z")
                ),
            )
        )

        bundle = self._import(session_id)

        occurrences = json.loads((bundle / "occurrences.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [
                (
                    item["workflow"],
                    item["mode"],
                    item["parent_occurrence_id"],
                    item["start_event"],
                    item["invocation_source"],
                )
                for item in occurrences
            ],
            [
                ("implement", "top-level", None, 0, "embedded_user_command_corroborated"),
                ("review-and-fix", "nested", "implement-1", 2, "assistant_skill_tool"),
            ],
        )
        metadata = json.loads((bundle / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["occurrence_count"], 2)

    def test_cli_imports_issue_522_native_tail_and_warns_when_manifest_is_absent(self) -> None:
        session_id = "issue-522-session"
        native = self._native_path(session_id)
        native.write_bytes(
            transcript(
                self._record(user("/implement 522", "2026-07-15T18:00:00Z")),
                self._record(assistant_text("working", "2026-07-15T18:01:00Z")),
                self._record(assistant_text("ISSUE-522-NATIVE-FINAL-TAIL", "2026-07-15T18:02:00Z")),
            )
        )
        entry = ROOT / "scripts/import-workflow-transcript.py"
        result = subprocess.run(
            [
                sys.executable,
                str(entry),
                session_id,
                "--claude-projects-root",
                str(self.projects),
                "--repo-root",
                str(self.repository),
                "--registry",
                str(REGISTRY),
            ],
            check=False,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        bundle = self.repository.resolve() / ".prflow/tmp/workflow-runs" / session_id
        self.assertEqual(Path(result.stdout.strip()), bundle)
        self.assertIn(b"ISSUE-522-NATIVE-FINAL-TAIL", (bundle / "transcript.jsonl").read_bytes())
        metadata = json.loads((bundle / "metadata.json").read_text(encoding="utf-8"))
        self.assertIn(
            "start manifest unavailable; prompt/config/git metadata measured at import time",
            metadata["warnings"],
        )

    def test_import_dirty_tree_distinguishes_clean_dirty_and_failed_status(self) -> None:
        cases = [
            ("", False),
            (" M skills/implement/SKILL.md\n", True),
            (None, None),
        ]
        for index, (status_stdout, expected) in enumerate(cases):
            with self.subTest(status_stdout=status_stdout):
                session_id = f"issue-522-status-{index}"
                self._native_path(session_id).write_bytes(
                    transcript(self._record(user("/implement 522")))
                )
                with patched_git_status(status_stdout):
                    bundle = self._import(session_id)
                metadata = json.loads((bundle / "metadata.json").read_text(encoding="utf-8"))
                self.assertIs(metadata["dirty_tree"], expected)

    def test_missing_and_duplicate_session_ids_fail_without_mutating_sources_or_bundles(self) -> None:
        duplicate_bytes = transcript(self._record(user("/implement 525")))
        duplicates = [
            self._native_path("duplicate-session", "first"),
            self._native_path("duplicate-session", "second"),
        ]
        for path in duplicates:
            path.write_bytes(duplicate_bytes)
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in duplicates}

        with self.assertRaisesRegex(ValueError, "exactly one.*missing-session"):
            self._import("missing-session")
        self.assertFalse((self.repository / ".prflow/tmp").exists())

        with self.assertRaisesRegex(ValueError, "exactly one.*duplicate-session"):
            self._import("duplicate-session")
        self.assertFalse((self.repository / ".prflow/tmp").exists())
        self.assertEqual(
            {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in duplicates},
            before,
        )


class CaptureTests(unittest.TestCase):
    def test_linked_worktree_launches_shared_recorder_and_stores_centrally(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            sandbox = Path(temporary)
            shared = sandbox / "shared"
            linked = sandbox / "linked"
            shared.mkdir()

            def git(*args: str, cwd: Path = shared) -> str:
                result = subprocess.run(
                    ["git", *args],
                    cwd=cwd,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                return result.stdout.strip()

            git("init", "-q")
            git("config", "user.email", "recorder-test@example.invalid")
            git("config", "user.name", "Recorder Test")
            for relative in [
                "skills/implement/SKILL.md",
                "skills/implement/phases/setup.md",
                "skills/review/SKILL.md",
                "skills/review-and-fix/SKILL.md",
                "skills/docs/SKILL.md",
            ]:
                path = shared / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"# linked {relative}\n", encoding="utf-8")
            git("add", "skills")
            git("commit", "-qm", "base without recorder")
            base_sha = git("rev-parse", "HEAD")

            for name in [
                "capture-implement-session.py",
                "workflow_flight_recorder.py",
                "workflow-flight-recorder-registry.json",
            ]:
                destination = shared / "scripts" / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / "scripts" / name, destination)
            git("add", "scripts")
            git("commit", "-qm", "add recorder only to shared checkout")
            git("worktree", "add", "-q", "--detach", str(linked), base_sha)
            (linked / "nested").mkdir()
            transcript_path = linked / "session.jsonl"
            transcript_path.write_bytes(transcript(user("/devflow:implement 520")))

            self.assertFalse((linked / "scripts/capture-implement-session.py").exists())
            payload = json.dumps(
                {
                    "session_id": "sid-linked",
                    "transcript_path": str(transcript_path),
                    "cwd": str(linked / "nested"),
                }
            )
            command = (
                'python3 "$(git rev-parse --path-format=absolute '
                '--git-common-dir 2>/dev/null)/../scripts/capture-implement-session.py"'
            )
            launched = subprocess.run(
                command,
                cwd=linked / "nested",
                shell=True,
                executable="/bin/bash",
                input=payload,
                capture_output=True,
                text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(launched.returncode, 0, launched.stderr)

            central_bundle = shared / ".prflow/tmp/workflow-runs/sid-linked"
            self.assertTrue((central_bundle / "transcript.jsonl").is_file())
            self.assertFalse((linked / ".prflow/tmp/workflow-runs/sid-linked").exists())
            metadata = json.loads((central_bundle / "metadata.json").read_text())
            self.assertEqual(metadata["repository_root"], str(linked.resolve()))
            self.assertEqual(metadata["storage_root"], str(shared.resolve()))
            self.assertEqual(metadata["storage_root_source"], "git_common_dir_parent")
            manifest = json.loads((central_bundle / "prompt-surfaces.json").read_text())
            self.assertTrue(
                any(item["path"] == "skills/implement/SKILL.md" for item in manifest["surfaces"])
            )

    def test_one_generic_bundle_stores_multiple_occurrences_and_config_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".git").mkdir()
            (root / "skills/implement/phases").mkdir(parents=True)
            (root / "skills/review").mkdir(parents=True)
            (root / "skills/review-and-fix").mkdir(parents=True)
            (root / "skills/docs").mkdir(parents=True)
            (root / ".claude").mkdir()
            for relative in [
                "skills/implement/SKILL.md",
                "skills/implement/phases/setup.md",
                "skills/review/SKILL.md",
                "skills/review-and-fix/SKILL.md",
                "skills/docs/SKILL.md",
            ]:
                path = root / relative
                path.write_text(f"# {relative}\n", encoding="utf-8")
            (root / ".claude/settings.local.json").write_text(
                json.dumps({"outputStyle": "Default", "verbose": True, "viewMode": "verbose"}),
                encoding="utf-8",
            )
            transcript_path = root / "session.jsonl"
            transcript_path.write_bytes(
                transcript(user("/devflow:implement 520"), skill_call("review-and-fix", "520"))
            )
            result = capture_stop_payload(
                {"session_id": "sid-capture", "transcript_path": str(transcript_path), "cwd": str(root)},
                REGISTRY,
            )
            self.assertTrue(result["captured"])
            bundle = root / ".prflow/tmp/workflow-runs/sid-capture"
            self.assertEqual(json.loads((bundle / "occurrences.json").read_text())[1]["workflow"], "review-and-fix")
            metadata = json.loads((bundle / "metadata.json").read_text())
            self.assertEqual(metadata["occurrence_count"], 2)
            self.assertEqual(metadata["repository_root"], str(root.resolve()))
            self.assertEqual(metadata["storage_root"], str(root.resolve()))
            self.assertEqual(metadata["storage_root_source"], "repository_root_fallback")
            self.assertEqual(metadata["claude_configuration"]["outputStyle"]["value"], "Default")
            self.assertEqual(metadata["claude_configuration"]["outputStyle"]["source"], "project_local_settings")
            manifests = json.loads((bundle / "prompt-surfaces.json").read_text())
            self.assertIn("implement", manifests["fingerprints"])
            physical_bytes = sum(
                len((root / relative).read_bytes())
                for relative in (
                    "skills/implement/SKILL.md",
                    "skills/implement/phases/setup.md",
                    "skills/review/SKILL.md",
                    "skills/review-and-fix/SKILL.md",
                    "skills/docs/SKILL.md",
                )
            )
            self.assertEqual(manifests["session_unique_totals"]["bytes"], physical_bytes)
            self.assertEqual((bundle / "transcript.jsonl").read_bytes(), transcript_path.read_bytes())

    def test_non_workflow_session_creates_no_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".git").mkdir()
            transcript_path = root / "session.jsonl"
            transcript_path.write_bytes(transcript(user("hello")))
            result = capture_stop_payload(
                {"session_id": "sid-none", "transcript_path": str(transcript_path), "cwd": str(root)},
                REGISTRY,
            )
            self.assertFalse(result["captured"])
            self.assertFalse((root / ".prflow/tmp/workflow-runs/sid-none").exists())


if __name__ == "__main__":
    unittest.main()
