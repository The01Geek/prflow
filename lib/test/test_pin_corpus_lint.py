#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Focused tests for the issue-810 pin-corpus authoring gate.

SHARDING REQUIREMENT (issue #870). lib/test/modules/harness-python-guards.sh runs this
file as several concurrent selector processes, which is only safe because no test here
shares filesystem or process-global state with another. There is no ``os.chdir`` and no
module-level mutable state, and every test that touches the filesystem allocates its own
``tempfile.TemporaryDirectory()`` and passes an explicit ``cwd=`` to its subprocesses. A
test added here that takes a process-global lock on the working directory, or shares
mutable *state* across tests, breaks that property and makes the sharded run
order-dependent. Keep new tests self-contained.

The linter and census modules these tests drive do carry process-global
``functools.lru_cache`` stores, so tests landing in the same process share them.
That is compatible with the requirement above for two separate reasons, not one.
The per-source parse memos are keyed on the presented bytes — the census memos
additionally on the source's name, the linter memos on the text alone (the two
bundle-membership parses of issue #956 additionally on the ``lib`` path the caller
passed) — and on no ``repo_root`` and no filesystem state, so a hit returns a value
derived from exactly what the caller presented. The bundle resolver's glob
EXPANSION is deliberately left outside its memo for that reason;
``BundleTargetInspection956Tests`` pins that a tree change between two calls is
observed rather than answered from the cache. ``_load_mutation_census_module`` is
different: it takes no arguments at all and hands every caller one module
object; it is safe because nothing in that module is mutated after import beyond
those same key-pure memos, not because of its key. Its other module-level
objects — the compiled-regex dicts among them — are built once at import and
never written to, so a shared instance cannot carry one caller's state to the
next.

The executable form of the first claim is the three
``StaticPinWorktreeCompositionTests.test_leaked_*_would_misclassify_a_sibling*``
probes, which present two differing repositories to one process and are verified
to go RED under a simulated mis-keying of each memo they name.
``MemoizedParseContractTests`` pins the separate contracts that make a memo hit
safe to hand out, and
``StaticPinWorktreeCompositionTests.test_repository_mutations_do_not_leak_between_fixtures``
pins filesystem isolation only — it runs no scan, so no memo is populated during
it, and neither of those two would notice a memo that captured repository state.
"""

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
LINTER = HERE / "pin-corpus-lint.py"
EXTRACTOR = HERE / "extract-command-heads.py"
CLASSIFIER = HERE / "pin-corpus-classifier.py"


def load_linter():
    spec = importlib.util.spec_from_file_location("pin_corpus_lint_810", LINTER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_classifier():
    spec = importlib.util.spec_from_file_location(
        "pin_corpus_classifier_1057", CLASSIFIER
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_extractor():
    spec = importlib.util.spec_from_file_location(
        "extract_command_heads_687", EXTRACTOR
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def one_file_diff(path: str, old: str, new: str) -> str:
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    body = [f"diff --git a/{path} b/{path}", f"--- a/{path}", f"+++ b/{path}"]
    body.append(f"@@ -1,{len(old_lines)} +1,{len(new_lines)} @@")
    body.extend(f"-{line}" for line in old_lines)
    body.extend(f"+{line}" for line in new_lines)
    return "\n".join(body) + "\n"


class Issue687OutputRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.linter = load_linter()
        cls.extractor = load_extractor()

    def test_pin_corpus_clean_scans_route_accounting_only_to_stderr(self):
        with tempfile.TemporaryDirectory() as td:
            pin_source = Path(td) / "pins.sh"
            pin_source.write_text("", encoding="utf-8")
            for scan in (self.linter.run_lint, self.linter.run_wrapped):
                with (
                    self.subTest(scan=scan.__name__),
                    mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
                    mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
                ):
                    rc = scan(
                        str(pin_source),
                        str(REPO_ROOT),
                        {},
                        set(),
                        strict=True,
                    )
                    self.assertEqual(0, rc)
                    self.assertEqual("", stdout.getvalue())
                    self.assertEqual(
                        "UNRESOLVED-COUNT\t0\nRESOLVED-COUNT\t0\n",
                        stderr.getvalue(),
                    )

    def test_extract_heads_stdout_is_only_the_sorted_data_product(self):
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "commands.md"
            source.write_text(
                "```bash\n"
                "git status\n"
                "echo ready\n"
                "```\n",
                encoding="utf-8",
            )
            with (
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                rc = self.extractor.main(
                    ["extract-command-heads.py", "heads", str(source)]
                )
            self.assertEqual(0, rc)
            self.assertEqual("echo\ngit status\n", stdout.getvalue())
            self.assertEqual("", stderr.getvalue())

    def test_ungranted_strict_exit_tracks_the_emitted_finding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "commands.md"
            allowlist = root / "allowlist.txt"
            source.write_text(
                "```bash\nzzcmd687 --flag\n```\n",
                encoding="utf-8",
            )
            allowlist.write_text("Bash(othercmd:*)\n", encoding="utf-8")
            with (
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                rc = self.extractor.main(
                    [
                        "extract-command-heads.py",
                        "ungranted",
                        "--strict",
                        str(source),
                        str(allowlist),
                    ]
                )
            self.assertEqual(3, rc)
            self.assertEqual("zzcmd687\n", stdout.getvalue())
            self.assertEqual("", stderr.getvalue())


class MemoizedParseContractTests(unittest.TestCase):
    """Pin the contracts that make a memo hit safe to hand out, and the reuse it buys.

    The safety invariants are ones a later reader could plausibly "optimize
    away" — the defensive copy looks redundant, and the read-only view looks
    like ceremony — while the resulting corruption is silent and reaches every
    later cache hit rather than the edit site. None of them was observable from
    the rest of the suite: removing them left it green. The reuse is likewise
    invisible to any correctness assertion, which is why it is pinned here too.
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = load_linter()
        cls.text = (REPO_ROOT / "lib/test/modules/harness-python-guards.sh").read_text(
            encoding="utf-8"
        )

    def test_function_definitions_hands_each_caller_its_own_mapping(self):
        first = self.mod._function_definitions(self.text)
        self.assertNotEqual({}, first)
        first["devflow_leaked_definition"] = ("", 1, 1)
        self.assertNotIn(
            "devflow_leaked_definition", self.mod._function_definitions(self.text)
        )

    def test_helper_specs_hand_each_caller_their_own_mappings(self):
        specs, families, origins = self.mod.helper_specs_for_source(self.text)
        specs["devflow_leaked_spec"] = (1, 2, None)
        families["devflow_leaked_spec"] = "static-helper"
        origins["devflow_leaked_spec"] = 1
        again_specs, again_families, again_origins = self.mod.helper_specs_for_source(
            self.text
        )
        self.assertNotIn("devflow_leaked_spec", again_specs)
        self.assertNotIn("devflow_leaked_spec", again_families)
        self.assertNotIn("devflow_leaked_spec", again_origins)

    def test_variable_maps_are_read_only_views(self):
        maps = self.mod.variable_maps_by_line(
            self.text, str(REPO_ROOT / "lib"), {}
        )
        self.assertTrue(maps)
        path_vars, literal_vars = maps[next(iter(maps))]
        with self.assertRaises(TypeError):
            path_vars["devflow_leaked_var"] = "/tmp/leak"
        with self.assertRaises(TypeError):
            literal_vars["devflow_leaked_var"] = "leak"

    def test_census_reuses_every_audited_source_within_one_build(self):
        # The memos are a cost mechanism, so nothing about a correct verdict
        # tells you they are working: deleting every lru_cache decorator leaves
        # the rest of the suite green and only the wall clock moves. This pins
        # the reuse itself, against the real repository, because the property
        # depends on how many tracked shell sources the definition sweep visits
        # relative to the bound — a quantity no constant in the source encodes.
        census = self.mod._load_mutation_census_module()
        # Warm every memo first, then clear all three. Both halves are
        # load-bearing. Clearing all three is required because _definition_scan
        # and _extract_rows are _logical_lines' CALLERS, memoized on the same
        # (name, text) pairs: a warm entry in either answers the whole
        # derivation, _logical_lines is never reached, the hit count reads 0,
        # and the message below misdirects the reader to the cache bound.
        # Warming first is what makes that requirement self-enforcing — it puts
        # this test in the state a co-resident census would leave, so reducing
        # the clear back to _logical_lines alone turns THIS test RED instead of
        # arming a failure for whichever unrelated test later shares its
        # process. That latent ordering dependence is exactly what this file's
        # module docstring forbids.
        census.build_census(REPO_ROOT)
        census._logical_lines.cache_clear()
        census._definition_scan.cache_clear()
        census._extract_rows.cache_clear()
        census.build_census(REPO_ROOT)
        info = census._logical_lines.cache_info()
        audited_sources = census._audited_sources(REPO_ROOT)
        audited = len(audited_sources)
        self.assertEqual(
            audited,
            info.hits,
            "the census re-parses each audited source for its row extraction "
            "after the definition sweep has visited every tracked shell source, "
            f"so it should take {audited} within-build hits; it took "
            f"{info.hits} ({info}). Two causes produce a shortfall. If the "
            "tracked shell sources have outgrown _SOURCE_PARSE_CACHE_SIZE in "
            "mutation-pin-census.py, raise that bound — the memo is silently "
            "buying nothing until you do. Otherwise an audited source has left "
            "the swept population (the sweep visits tracked '.sh' paths under "
            "lib/test that decode as UTF-8), so it is extracted without ever "
            "having been swept and can take no repeat hit; the audited set was "
            f"{sorted(audited_sources)}.",
        )

    def test_census_outer_memos_are_reused_across_builds(self):
        # _logical_lines is the only memo the within-build pin above can see:
        # the sweep reaches _definition_scan once per source and the extraction
        # reaches _extract_rows once per audited source, so neither repeats
        # inside a single build. Their reuse is across builds, and without this
        # it has no detector — the same silent-degradation gap the bound comment
        # names for _logical_lines, for the two memos that bound was sized for.
        census = self.mod._load_mutation_census_module()
        for memo in (
            census._logical_lines,
            census._definition_scan,
            census._extract_rows,
        ):
            memo.cache_clear()
        census.build_census(REPO_ROOT)
        first_scan = census._definition_scan.cache_info()
        first_rows = census._extract_rows.cache_info()
        census.build_census(REPO_ROOT)
        for name, before, after in (
            ("_definition_scan", first_scan, census._definition_scan.cache_info()),
            ("_extract_rows", first_rows, census._extract_rows.cache_info()),
        ):
            with self.subTest(memo=name):
                self.assertGreater(
                    after.hits - before.hits,
                    0,
                    f"a second census over the same tree should reuse {name}; "
                    f"it took no new hit ({after}). If the swept population has "
                    "outgrown _SOURCE_PARSE_CACHE_SIZE in mutation-pin-census.py, "
                    "raise that bound — the memo is buying nothing until you do.",
                )

    def test_linter_image_memos_are_reused_within_one_extraction(self):
        # The census bound has a hit-count pin; the linter's two-image bound had
        # none, so a key that stopped matching would silently stop hitting with
        # the whole suite still green. One extraction reaches
        # _function_definitions_cached twice for the same image: once directly,
        # and once through _function_bodies inside the helper-spec inference.
        #
        # This covers key-match only. It cannot see the bound VALUE: one image
        # is one live key, which stays resident at any maxsize >= 1. The bound
        # is guarded by test_linter_image_memo_bound_retains_a_second_image.
        self.mod._function_definitions_cached.cache_clear()
        self.mod._helper_specs_for_source_cached.cache_clear()
        self.mod.extract_guard_sites(
            self.text, "lib/test/modules/harness-python-guards.sh", str(REPO_ROOT)
        )
        info = self.mod._function_definitions_cached.cache_info()
        self.assertGreaterEqual(
            info.hits,
            1,
            "one extraction presents the same image to _function_definitions "
            "twice, so the memo should take at least one within-extraction hit; "
            f"it took {info.hits} ({info}). The memo is keyed on the image text "
            "alone — if that key stopped matching, the reuse is gone.",
        )

    def test_linter_image_memo_bound_retains_a_second_image(self):
        # What _IMAGE_PARSE_CACHE_SIZE = 2 actually buys is CROSS-extraction
        # reuse: the linter presents more than one image per process, and the
        # bound is what keeps an earlier one resident while a later one is
        # parsed. A within-extraction hit count cannot detect a bound lowered to
        # 1, because a single live key never needs a second slot. Present two
        # distinct images and then re-present the first: at a bound of 2 it is
        # still resident and takes no new miss; at 1 the second evicted it and
        # re-presenting it re-parses.
        other = "b_helper() {\n  :\n}\n"
        self.assertNotEqual(self.text, other, "the two images must differ")
        self.mod._function_definitions_cached.cache_clear()
        self.mod._helper_specs_for_source_cached.cache_clear()
        self.mod.extract_guard_sites(
            self.text, "lib/test/modules/harness-python-guards.sh", str(REPO_ROOT)
        )
        self.mod.extract_guard_sites(
            other, "lib/test/modules/other-guards.sh", str(REPO_ROOT)
        )
        settled = self.mod._function_definitions_cached.cache_info().misses
        self.mod.extract_guard_sites(
            self.text, "lib/test/modules/harness-python-guards.sh", str(REPO_ROOT)
        )
        info = self.mod._function_definitions_cached.cache_info()
        self.assertEqual(
            settled,
            info.misses,
            "re-presenting the first image after a second one should take no "
            f"new miss; misses went {settled} -> {info.misses} ({info}). "
            "_IMAGE_PARSE_CACHE_SIZE in pin-corpus-lint.py no longer retains "
            "two images, so the linter re-parses an image it already holds "
            "every time it alternates between sources — raise the bound.",
        )

    def test_function_definition_line_numbers_match_a_counting_oracle(self):
        # _function_definitions_cached derives each definition's (start, end)
        # line numbers from a bisect over one newline index, replacing a
        # per-definition text.count("\n", 0, pos). An off-by-one here does not
        # crash: it shifts function_by_line, so a site is attributed to the
        # wrong enclosing function and the linter reports a subtly wrong
        # finding. Drive the real derivation and compare against an independent
        # counting oracle — deliberately NOT by re-running bisect here, which
        # would restate the implementation instead of testing it.
        texts = (
            "f() {\n  :\n}\n",
            "\n\n\nf() {\n  :\n}",  # leading blank lines, no trailing newline
            "a() {\n  :\n}\nb() {\n  :\n  :\n}\n",  # consecutive definitions
            self.text,
        )
        # A name or a body can occur more than once in a real source — a call
        # site preceding its definition, or two helpers with byte-identical
        # bodies. Anchoring on the FIRST occurrence would then compare against
        # the wrong span and go RED on a correct derivation. So the oracle
        # accepts the reported pair if ANY (header, body) occurrence yields it,
        # pairing each body occurrence with the nearest preceding name. That
        # still fails an off-by-one, which shifts every candidate at once.
        for text in texts:
            with self.subTest(text=text[:24]):
                definitions = self.mod._function_definitions(text)
                self.assertNotEqual({}, definitions)
                for name, (body, start, end) in definitions.items():
                    candidates = []
                    body_start = text.find(body)
                    while body_start >= 0:
                        header = text.rfind(name, 0, body_start)
                        if header >= 0:
                            candidates.append(
                                (
                                    text.count("\n", 0, header) + 1,
                                    text.count("\n", 0, body_start + len(body)) + 1,
                                )
                            )
                        body_start = text.find(body, body_start + 1)
                    self.assertIn(
                        (start, end),
                        candidates,
                        f"the (start, end) lines reported for {name} match no "
                        "occurrence of its header and body; the counting oracle "
                        f"offers {sorted(set(candidates))}",
                    )

    def test_newline_offsets_are_the_ascending_newline_positions(self):
        # The index the derivation above bisects. Pinned separately because an
        # empty or unsorted index is a silent wrong answer rather than a crash.
        for text in ("", "\n", "a\n\nb", "\n\n\n", "no trailing newline"):
            with self.subTest(text=text[:24]):
                offsets = self.mod._newline_offsets(text)
                self.assertEqual(
                    [i for i, ch in enumerate(text) if ch == "\n"], offsets
                )

    def test_census_module_load_failure_leaves_no_half_built_module(self):
        # The failed-exec arm exists so a half-initialized module is never left
        # registered for a later importer to find. lru_cache does not memoize
        # the raise, so the contract is two-part: the name is unregistered, AND
        # a later call re-execs successfully. Neither half is observable from
        # the success path, so without this test both could be dropped silently.
        loader = self.mod._load_mutation_census_module
        loader.cache_clear()
        self.addCleanup(loader.cache_clear)
        boom = RuntimeError("simulated exec failure")
        registered = []

        real_exec = importlib.util.module_from_spec

        def _record(spec):
            module = real_exec(spec)
            registered.append(spec.name)
            return module

        with mock.patch.object(
            importlib.util, "module_from_spec", side_effect=_record
        ):
            with mock.patch.object(
                importlib.machinery.SourceFileLoader,
                "exec_module",
                side_effect=boom,
            ):
                with self.assertRaises(RuntimeError):
                    loader()
        self.assertTrue(registered, "the loader never reached module creation")
        for name in registered:
            self.assertNotIn(
                name,
                sys.modules,
                "a half-initialized census module stayed registered after a "
                "failed exec_module",
            )
        # lru_cache must not have memoized the raise: the retry re-execs.
        self.assertIsNotNone(loader())

    def test_variable_maps_still_advance_across_an_assignment(self):
        # The snapshot is taken only where an assignment could have changed the
        # maps, so this pins that the sharing did not flatten the sequence into
        # one map: the line before an assignment must not see its value.
        text = "A='before'\nB='after'\nC='last'\n"
        maps = self.mod.variable_maps_by_line(text, "/tmp/lib", {})
        self.assertNotIn("B", maps[2][1])
        self.assertEqual("after", maps[3][1]["B"])


class PinCorpusLint810Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_linter()

    def test_closed_structural_categories_accept_nonempty_rationales(self):
        expected = {
            "helper-contract",
            "schema-config-vocabulary",
            "security-credential-boundary",
            "machine-sentinel-provenance",
            "routing-dispatch-contract",
            "lifecycle-state-transition",
            "generated-artifact-identity",
            "cross-file-phase-contract",
        }
        self.assertEqual(expected, set(self.mod.STRUCTURAL_PIN_CATEGORIES))
        for category in expected:
            declaration, error = self.mod.parse_structural_declaration(
                [f"# structural-pin-ok: {category} -- protects a machine boundary"]
            )
            self.assertIsNone(error)
            self.assertEqual(category, declaration.category)

    def test_structural_declaration_rejects_missing_unknown_empty_quoted_and_duplicate(self):
        invalid = {
            "missing category": ["# structural-pin-ok: -- because"],
            "unknown category": ["# structural-pin-ok: prose-presence -- because"],
            "empty rationale": ["# structural-pin-ok: helper-contract --   "],
            "quoted marker": [
                "assert_pin_unique 'x' '# structural-pin-ok: helper-contract -- fake' \"$F\""
            ],
            "duplicate marker": [
                "# structural-pin-ok: helper-contract -- one",
                "# structural-pin-ok: helper-contract -- two",
            ],
        }
        for label, lines in invalid.items():
            with self.subTest(label=label):
                declaration, error = self.mod.parse_structural_declaration(lines)
                self.assertIsNone(declaration)
                self.assertIsNotNone(error)

    def test_path_aware_diff_scopes_only_the_changed_file(self):
        shared = "assert_pin_unique \"wording\" 'same literal' \"$F\""
        sources = {"lib/test/a.sh": shared, "lib/test/b.sh": shared}
        base_sources = {"lib/test/a.sh": "old", "lib/test/b.sh": shared}
        findings = self.mod.scan_changed_sources(
            sources,
            base_sources,
            one_file_diff("lib/test/a.sh", "old", shared),
            repo_root="/repo",
        )
        self.assertEqual(1, len(findings))
        self.assertIn("lib/test/a.sh", findings[0])

    def test_partial_multiline_edit_scopes_the_complete_helper_site(self):
        old = (
            "assert_pin_unique \"wording\" \\\n"
            "  'old literal' \\\n"
            "  \"$F\""
        )
        new = old.replace("old literal", "new literal")
        diff = (
            "diff --git a/lib/test/a.sh b/lib/test/a.sh\n"
            "--- a/lib/test/a.sh\n+++ b/lib/test/a.sh\n"
            "@@ -2 +2 @@\n-  'old literal' \\\n+  'new literal' \\\n"
        )
        findings = self.mod.scan_changed_sources(
            {"lib/test/a.sh": new},
            {"lib/test/a.sh": old},
            diff,
            repo_root="/repo",
        )
        self.assertEqual(1, len(findings))
        self.assertIn("new literal", findings[0])

    def test_helper_and_raw_wording_pins_share_the_policy(self):
        helper = "assert_pin_unique \"wording\" 'literal' \"$F\""
        raw = (
            "DOC=\"$LIB/../docs/x.md\"\n"
            "assert_eq \"wording\" \"yes\" "
            "\"$(grep -qF -- 'literal' \"$DOC\" && echo yes || echo no)\""
        )
        for path, text in (("lib/test/helper.sh", helper), ("lib/test/raw.sh", raw)):
            with self.subTest(path=path):
                findings = self.mod.scan_changed_sources(
                    {path: text}, {path: ""}, one_file_diff(path, "", text), repo_root="/repo"
                )
                self.assertEqual(1, len(findings))
                self.assertIn("literal", findings[0])

    def test_valid_typed_helper_and_raw_pins_pass(self):
        marker = (
            "# structural-pin-ok: machine-sentinel-provenance -- "
            "the token is parsed by the consumer"
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "docs/x.md"
            target.parent.mkdir(parents=True)
            target.write_text("literal\n", encoding="utf-8")
            helper = (
                "F=\"$LIB/../docs/x.md\"\n"
                f"assert_pin_unique \"sentinel\" 'literal' \"$F\"  {marker}"
            )
            raw = (
                "DOC=\"$LIB/../docs/x.md\"\n"
                "assert_eq \"sentinel\" \"yes\" "
                f"\"$(grep -qF -- 'literal' \"$DOC\" && echo yes || echo no)\"  {marker}"
            )
            for path, text in (
                ("lib/test/helper.sh", helper),
                ("lib/test/raw.sh", raw),
            ):
                findings = self.mod.scan_changed_sources(
                    {path: text},
                    {path: ""},
                    one_file_diff(path, "", text),
                    repo_root=root,
                )
                self.assertEqual([], findings)

    def test_typed_declaration_requires_resolved_readable_target_and_literal(self):
        marker = (
            "# structural-pin-ok: cross-file-phase-contract -- "
            "claimed executable boundary"
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "repo"
            root.mkdir()
            target = root / "docs/x.md"
            target.parent.mkdir(parents=True)
            target.write_text("TOKEN\n", encoding="utf-8")
            outside = Path(td) / "outside.md"
            outside.write_text("TOKEN\n", encoding="utf-8")
            cases = (
                (
                    "unresolved target",
                    f"assert_pin_unique \"wording\" 'human-facing prose' \"$UNKNOWN\"  {marker}",
                ),
                (
                    "unresolved literal",
                    ("F=\"$LIB/../docs/x.md\"\n"
                    f"assert_pin_unique \"wording\" \"$UNKNOWN\" \"$F\"  {marker}"),
                ),
                (
                    "empty literal",
                    ("F=\"$LIB/../docs/x.md\"\n"
                    f"assert_pin_unique \"wording\" '' \"$F\"  {marker}"),
                ),
                (
                    "missing target",
                    ("F=\"$LIB/../docs/missing.md\"\n"
                    f"assert_pin_unique \"wording\" 'human-facing prose' \"$F\"  {marker}"),
                ),
                (
                    "outside repository",
                    (f"F=\"{outside}\"\n"
                    f"assert_pin_unique \"wording\" 'TOKEN' \"$F\"  {marker}"),
                ),
                (
                    "literal absent from target",
                    ("F=\"$LIB/../docs/x.md\"\n"
                    f"assert_pin_unique \"wording\" 'ABSENT' \"$F\"  {marker}"),
                ),
            )
            for label, source in cases:
                with self.subTest(label=label):
                    findings = self.mod.scan_changed_sources(
                        {"lib/test/a.sh": source},
                        {"lib/test/a.sh": ""},
                        one_file_diff("lib/test/a.sh", "", source),
                        repo_root=root,
                    )
                    self.assertEqual(1, len(findings))
                    self.assertIn("cannot be inspected", findings[0])

    def test_typed_declaration_cannot_launder_prose(self):
        marker = (
            "# structural-pin-ok: cross-file-phase-contract -- "
            "the sentence is claimed to connect two phases"
        )
        for target_path, target_text in (
            ("docs/x.md", "## Advisory heading\n\nThis is human-facing prose.\n"),
            ("docs/x.md", "## Overview\n"),
            ("lib/x.sh", "# Advisory heading\nprintf '%s\\n' runtime\n"),
        ):
            with self.subTest(target=target_path), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                target = root / target_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(target_text, encoding="utf-8")
                literal = "Overview" if target_text == "## Overview\n" else "Advisory heading"
                source = (
                    f"F=\"$LIB/../{target_path}\"\n"
                    f"assert_pin_unique \"heading\" '{literal}' \"$F\"  {marker}"
                )
                findings = self.mod.scan_changed_sources(
                    {"lib/test/a.sh": source},
                    {"lib/test/a.sh": ""},
                    one_file_diff("lib/test/a.sh", "", source),
                    repo_root=root,
                )
                self.assertEqual(1, len(findings))
                self.assertIn("prose", findings[0])

    def test_typed_markdown_machine_token_in_code_fence_is_not_prose(self):
        marker = (
            "# structural-pin-ok: machine-sentinel-provenance -- "
            "the fenced token is parsed by a consumer"
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "docs/x.md"
            target.parent.mkdir(parents=True)
            target.write_text("```text\nMACHINE SENTINEL\n```\n", encoding="utf-8")
            source = (
                "F=\"$LIB/../docs/x.md\"\n"
                f"assert_pin_unique \"sentinel\" 'MACHINE SENTINEL' \"$F\"  {marker}"
            )
            findings = self.mod.scan_changed_sources(
                {"lib/test/a.sh": source},
                {"lib/test/a.sh": ""},
                one_file_diff("lib/test/a.sh", "", source),
                repo_root=root,
            )
        self.assertEqual([], findings)

    def test_count_helper_prose_pin_is_reported_like_a_static_one(self):
        # Issue #925: a pin_count whose literal resolves into prose is reported
        # exactly as the equivalent static-helper pin, and the finding names the
        # literal, the prose file:line it resolved into, and that the helper does
        # not change the verdict.
        for helper in ("pin_count", "devflow_module_pin_count"):
            with self.subTest(helper=helper), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                target = root / "docs/x.md"
                target.parent.mkdir(parents=True)
                target.write_text(
                    "# Heading\n\nThe trailer form is written here.\n",
                    encoding="utf-8",
                )
                source = (
                    "F=\"$LIB/../docs/x.md\"\n"
                    f"{helper} 'trailer form is written' \"$F\""
                )
                findings = self.mod.scan_changed_sources(
                    {"lib/test/a.sh": source},
                    {"lib/test/a.sh": ""},
                    one_file_diff("lib/test/a.sh", "", source),
                    repo_root=root,
                )
                self.assertEqual(1, len(findings))
                self.assertIn("trailer form is written", findings[0])
                self.assertIn("resolves into prose", findings[0])
                self.assertIn("docs/x.md:3", findings[0])
                self.assertIn(f"the {helper} helper does not change", findings[0])

    def test_count_helper_machine_consumed_literal_with_declaration_passes(self):
        # The counterpart to the prose case: a count-helper pin over a genuinely
        # machine-consumed literal (a fenced token) that carries a valid typed
        # declaration is GREEN — the same scrutiny every typed pin takes.
        marker = (
            "# structural-pin-ok: machine-sentinel-provenance -- "
            "the fenced token is parsed by a consumer"
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "docs/x.md"
            target.parent.mkdir(parents=True)
            target.write_text("```text\nMACHINE SENTINEL\n```\n", encoding="utf-8")
            source = (
                "F=\"$LIB/../docs/x.md\"\n"
                f"pin_count 'MACHINE SENTINEL' \"$F\"  {marker}"
            )
            findings = self.mod.scan_changed_sources(
                {"lib/test/a.sh": source},
                {"lib/test/a.sh": ""},
                one_file_diff("lib/test/a.sh", "", source),
                repo_root=root,
            )
        self.assertEqual([], findings)

    def test_count_helper_prose_pin_red_first_real_regression(self):
        # AC3: the exact pin PR #923 removed — a pin_count over a command-form
        # trailer that lives in visible prose. WITH the pin present the gate
        # reports it (RED); with it absent the gate is clean (GREEN). Both
        # observations are recorded here so the RED-first proof is durable.
        literal = 'review-wp.md ; echo "seed-rc=$?"'
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "skills/review/SKILL.md"
            target.parent.mkdir(parents=True)
            target.write_text(
                "# Review\n\nSeed the comment with "
                'seed-review-progress.sh ... review-wp.md ; echo "seed-rc=$?"\n'
                "so a refusal is observable.\n",
                encoding="utf-8",
            )
            # RED: the removed pin, reintroduced, is reported.
            with_pin = (
                "ST_REV=\"$LIB/../skills/review/SKILL.md\"\n"
                f"pin_count '{literal}' \"$ST_REV\""
            )
            red = self.mod.scan_changed_sources(
                {"lib/test/run.sh": with_pin},
                {"lib/test/run.sh": ""},
                one_file_diff("lib/test/run.sh", "", with_pin),
                repo_root=root,
            )
            self.assertEqual(1, len(red))
            self.assertIn(literal, red[0])
            self.assertIn("resolves into prose", red[0])
            # GREEN: with the pin removed, the same tree is clean.
            without_pin = "ST_REV=\"$LIB/../skills/review/SKILL.md\"\n"
            green = self.mod.scan_changed_sources(
                {"lib/test/run.sh": without_pin},
                {"lib/test/run.sh": ""},
                one_file_diff("lib/test/run.sh", "", without_pin),
                repo_root=root,
            )
            self.assertEqual([], green)

    def test_unmodified_count_helper_prose_pin_is_grandfathered(self):
        # AC4/AC5: an existing count-helper prose pin the change does not touch is
        # not scanned (grandfathered → GREEN); the SAME site, once modified, takes
        # the full adjudication (RED).
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "docs/x.md"
            target.parent.mkdir(parents=True)
            target.write_text(
                "# Heading\n\nThe trailer form is written here.\n",
                encoding="utf-8",
            )
            pin_source = (
                "F=\"$LIB/../docs/x.md\"\n"
                "pin_count 'trailer form is written' \"$F\""
            )
            # Unmodified: the diff touches an unrelated file, so the pin site is
            # not in scope and draws no finding.
            grandfathered = self.mod.scan_changed_sources(
                {"lib/test/a.sh": pin_source},
                {"lib/test/a.sh": pin_source},
                one_file_diff("lib/test/other.sh", "", "echo unrelated"),
                repo_root=root,
            )
            self.assertEqual([], grandfathered)
            # Modified: the same pin site now appears in the diff and is reported.
            modified = self.mod.scan_changed_sources(
                {"lib/test/a.sh": pin_source},
                {"lib/test/a.sh": ""},
                one_file_diff("lib/test/a.sh", "", pin_source),
                repo_root=root,
            )
            self.assertEqual(1, len(modified))
            self.assertIn("resolves into prose", modified[0])

    def test_undeclared_count_helper_over_machine_content_requires_declaration(self):
        # The discriminating test for #925: an UNDECLARED count-helper pin over
        # genuinely machine-consumed (fenced) content is now RED for a missing
        # declaration — exactly as a static-helper pin is. This is the case that
        # would silently pass again if the count-helper short-circuit were
        # reintroduced, and unlike the declared-machine GREEN test it does NOT
        # also pass on the pre-#925 code.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "docs/x.md"
            target.parent.mkdir(parents=True)
            target.write_text("```text\nMACHINE SENTINEL\n```\n", encoding="utf-8")
            source = (
                "F=\"$LIB/../docs/x.md\"\n"
                "pin_count 'MACHINE SENTINEL' \"$F\""
            )
            findings = self.mod.scan_changed_sources(
                {"lib/test/a.sh": source},
                {"lib/test/a.sh": ""},
                one_file_diff("lib/test/a.sh", "", source),
                repo_root=root,
            )
        self.assertEqual(1, len(findings))
        self.assertIn("missing structural declaration", findings[0])
        self.assertNotIn("resolves into prose", findings[0])

    def test_count_helper_prose_pin_in_hash_comment_target_is_reported(self):
        # Helper-neutrality across the COMMENT_HASH_EXTS branch too: a pin_count
        # whose literal resolves into a `#` comment of a .sh target is reported
        # with the prose file:line, just like the markdown branch.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "lib/x.sh"
            target.parent.mkdir(parents=True)
            target.write_text(
                "printf '%s\\n' runtime\n# advisory phrase in a comment\n",
                encoding="utf-8",
            )
            source = (
                "F=\"$LIB/../lib/x.sh\"\n"
                "pin_count 'advisory phrase in a comment' \"$F\""
            )
            findings = self.mod.scan_changed_sources(
                {"lib/test/a.sh": source},
                {"lib/test/a.sh": ""},
                one_file_diff("lib/test/a.sh", "", source),
                repo_root=root,
            )
        self.assertEqual(1, len(findings))
        self.assertIn("resolves into prose", findings[0])
        self.assertIn("lib/x.sh:2", findings[0])
        self.assertIn("pin_count helper does not change", findings[0])

    def test_direct_inline_repository_file_is_a_raw_presence_pin(self):
        source = (
            "assert_eq \"wording\" \"yes\" "
            "\"$(grep -qF -- 'literal' \"$LIB/../docs/x.md\" "
            "&& echo yes || echo no)\""
        )
        sites = self.mod.extract_guard_sites(source, "lib/test/a.sh", repo_root="/repo")
        self.assertEqual(["raw-presence"], [site.family for site in sites])

    def test_equivalent_helper_and_raw_command_forms_are_extracted(self):
        sources = {
            "helper under if": (
                "F=\"$LIB/../docs/x.md\"\n"
                "if assert_pin_unique \"wording\" 'literal' \"$F\"; then :; fi"
            ),
            "private wrapper": (
                "_raf_pin_unique() { devflow_module_pin_unique \"$@\"; }\n"
                "F=\"$LIB/../docs/x.md\"\n"
                "_raf_pin_unique \"wording\" 'literal' \"$F\""
            ),
            "opaque forwarding wrapper": (
                "F=\"$LIB/../docs/x.md\"\n"
                "contract_surface() { "
                "devflow_module_pin_present \"wrapped $1\" \"$2\" \"$F\"; }\n"
                "contract_surface \"wording\" 'literal'"
            ),
            "generic forwarding wrapper": (
                "F=\"$LIB/../docs/x.md\"\n"
                "contract_surface() { devflow_module_pin_present \"$@\"; }\n"
                "contract_surface \"wording\" 'literal' \"$F\""
            ),
            "short flags reversed": (
                "DOC=\"$LIB/../docs/x.md\"\n"
                "assert_eq \"wording\" \"yes\" "
                "\"$(grep -Fq -- 'literal' \"$DOC\" && echo yes || echo no)\""
            ),
            "short flags split": (
                "DOC=\"$LIB/../docs/x.md\"\n"
                "assert_eq \"wording\" \"yes\" "
                "\"$(grep -q -F -- 'literal' \"$DOC\" && echo yes || echo no)\""
            ),
            "long flags": (
                "DOC=\"$LIB/../docs/x.md\"\n"
                "assert_eq \"wording\" \"yes\" "
                "\"$(grep --fixed-strings --quiet -- 'literal' \"$DOC\" "
                "&& echo yes || echo no)\""
            ),
            "numeric boolean": (
                "DOC=\"$LIB/../docs/x.md\"\n"
                "assert_eq \"wording\" \"1\" "
                "\"$(grep -Fq -- 'literal' \"$DOC\" && echo 1 || echo 0)\""
            ),
            "if control flow": (
                "DOC=\"$LIB/../docs/x.md\"\n"
                "if grep -Fq -- 'literal' \"$DOC\"; then "
                "assert_eq \"wording\" \"yes\" \"yes\"; fi"
            ),
            "literal variable": (
                "DOC=\"$LIB/../docs/x.md\"\n"
                "LIT='literal'\n"
                "assert_eq \"wording\" \"yes\" "
                "\"$(grep -Fq -- $LIT \"$DOC\" && echo yes || echo no)\""
            ),
        }
        for label, source in sources.items():
            with self.subTest(label=label):
                sites = self.mod.extract_guard_sites(
                    source, "lib/test/a.sh", repo_root="/repo"
                )
                self.assertEqual(1, len(sites))
                self.assertEqual("literal", sites[0].literal)

        reversed_output = (
            "DOC=\"$LIB/../docs/x.md\"\n"
            "assert_eq \"absence\" \"yes\" "
            "\"$(grep -Fq -- 'literal' \"$DOC\" && echo no || echo yes)\""
        )
        self.assertEqual(
            [],
            self.mod.extract_guard_sites(
                reversed_output, "lib/test/a.sh", repo_root="/repo"
            ),
        )

    def test_raw_presence_matches_bind_to_the_exact_executable_grep(self):
        inert = (
            "DOC=\"$LIB/../docs/x.md\"\n"
            "printf '%s' '$(grep -qF -- \"fake\" \"$DOC\")'; grep --help"
        )
        self.assertEqual(
            [],
            self.mod.extract_guard_sites(
                inert, "lib/test/a.sh", repo_root="/repo"
            ),
        )

        genuine = (
            "DOC=\"$LIB/../docs/x.md\"\n"
            "printf '%s' '$(grep -qF -- \"fake\" \"$DOC\")'; "
            "grep -qF -- 'real' \"$DOC\""
        )
        sites = self.mod.extract_guard_sites(
            genuine, "lib/test/a.sh", repo_root="/repo"
        )
        self.assertEqual(1, len(sites))
        self.assertEqual("real", sites[0].literal)
        self.assertEqual("/repo/docs/x.md", sites[0].target_path)

    def test_raw_presence_after_shell_command_boundaries_is_extracted(self):
        prefixes = {
            "pipe": "true | ",
            "attached pipe-stderr": "true|&",
            "background": "true & ",
            "subshell": "( ",
        }
        for label, prefix in prefixes.items():
            with self.subTest(label=label):
                source = (
                    "DOC=\"$LIB/../docs/x.md\"\n"
                    f"{prefix}grep -qF -- 'literal' \"$DOC\""
                )
                sites = self.mod.extract_guard_sites(
                    source, "lib/test/a.sh", repo_root="/repo"
                )
                self.assertEqual(1, len(sites))
                self.assertEqual("literal", sites[0].literal)

    def test_multiple_executable_raw_presence_commands_fail_closed(self):
        separators = {
            "semicolon": "; ",
            "spaced pipe": " | ",
            "attached pipe": "|",
            "attached pipe-stderr": "|&",
        }
        for label, separator in separators.items():
            with self.subTest(label=label):
                old = (
                    "DOC=\"$LIB/../docs/x.md\"\n"
                    "grep -qF -- 'one' \"$DOC\""
                )
                source = (
                    old
                    + separator
                    + "grep -qF -- 'two' \"$DOC\""
                )
                with self.assertRaisesRegex(
                    self.mod.InfrastructureError,
                    "multiple raw presence commands",
                ):
                    self.mod.scan_changed_sources(
                        {"lib/test/a.sh": source},
                        {"lib/test/a.sh": old},
                        one_file_diff("lib/test/a.sh", old, source),
                        repo_root="/repo",
                    )

    def test_declaration_cannot_hide_a_second_raw_presence_command(self):
        old = (
            "DOC=\"$LIB/../docs/x.md\"\n"
            "grep -qF -- 'one' \"$DOC\""
        )
        source = (
            old
            + "; grep -qF -- 'two' \"$DOC\"  "
            "# structural-pin-ok: helper-contract -- first grep is executable"
        )
        with self.assertRaisesRegex(
            self.mod.InfrastructureError,
            "multiple raw presence commands",
        ):
            self.mod.scan_changed_sources(
                {"lib/test/a.sh": source},
                {"lib/test/a.sh": old},
                one_file_diff("lib/test/a.sh", old, source),
                repo_root="/repo",
            )

    def test_assignment_change_preserves_identical_raw_occurrences(self):
        calls = (
            "grep -qF -- 'literal' \"$DOC\"; "
            "grep -qF -- 'literal' \"$DOC\""
        )
        old = "DOC=\"$LIB/../docs/old.md\"\n" + calls
        source = "DOC=\"$LIB/../docs/new.md\"\n" + calls
        diff = (
            "diff --git a/lib/test/a.sh b/lib/test/a.sh\n"
            "--- a/lib/test/a.sh\n"
            "+++ b/lib/test/a.sh\n"
            "@@ -1 +1 @@\n"
            "-DOC=\"$LIB/../docs/old.md\"\n"
            "+DOC=\"$LIB/../docs/new.md\"\n"
        )
        findings = self.mod.scan_changed_sources(
            {"lib/test/a.sh": source},
            {"lib/test/a.sh": old},
            diff,
            repo_root="/repo",
        )
        self.assertEqual(2, len(findings))
        self.assertTrue(
            all("missing structural declaration" in item for item in findings)
        )

    def test_quoted_escaped_and_argument_grep_words_are_not_executable(self):
        source = (
            "DOC=\"$LIB/../docs/x.md\"\n"
            "printf '%s' 'grep -qF -- \"one\" \"$DOC\"' "
            "'grep -qF -- \"two\" \"$DOC\"'; "
            "\\grep -qF -- 'escaped' \"$DOC\"; "
            "printf '%s' grep -qF -- 'argument' \"$DOC\""
        )
        self.assertEqual(
            [],
            self.mod.extract_guard_sites(
                source, "lib/test/a.sh", repo_root="/repo"
            ),
        )

    def test_command_substitution_looking_grep_in_comment_is_inert(self):
        source = (
            "DOC=\"$LIB/../docs/x.md\"\n"
            "printf x # $(grep -qF -- 'fake' \"$DOC\")"
        )
        self.assertEqual(
            [],
            self.mod.extract_guard_sites(
                source, "lib/test/a.sh", repo_root="/repo"
            ),
        )
        self.assertEqual(
            [],
            self.mod.scan_changed_sources(
                {"lib/test/a.sh": source},
                {"lib/test/a.sh": ""},
                one_file_diff("lib/test/a.sh", "", source),
                repo_root="/repo",
            ),
        )

    def test_runtime_pipe_count_absence_and_temp_greps_are_not_raw_presence_pins(self):
        source = 'assert_eq "runtime" "yes" "$(printf x | grep -qF x && echo yes || echo no)"\nassert_eq "count" "1" "$(grep -cF x "$DOC")"\nassert_eq "absence" "no" "$(grep -qF x "$DOC" && echo yes || echo no)"\nassert_eq "temp" "yes" "$(grep -qF x "$TMP_FILE" && echo yes || echo no)"\nassert_eq "temp dir" "yes" "$(grep -qF x "$TMP_MI/edit-args" && echo yes || echo no)"\nassert_eq "temp braced" "yes" "$(grep -qF x "${TEMP_D}/args" && echo yes || echo no)"'
        sites = self.mod.extract_guard_sites(source, "lib/test/a.sh", repo_root="/repo")
        self.assertEqual([], [site for site in sites if site.family == "raw-presence"])

    def test_a_temp_named_var_that_resolves_into_the_repo_stays_in_scope(self):
        # The carve-out is for UNRESOLVABLE runtime scratch only. A `TMP_`-named var
        # that actually resolves to repository source is a source-presence pin and
        # must not be exempted by its name.
        source = 'TMP_DOC="$LIB/../docs/x.md"\nassert_eq "named temp" "yes" "$(grep -qF x "$TMP_DOC" && echo yes || echo no)"\nassert_eq "inline temp" "yes" "$(grep -qF x "$TMP_DOC/y" && echo yes || echo no)"'
        sites = self.mod.extract_guard_sites(source, "lib/test/a.sh", repo_root="/repo")
        self.assertEqual(
            2, len([site for site in sites if site.family == "raw-presence"])
        )

    def test_moves_are_reclassified_under_the_current_site_policy(self):
        marker = "# structural-pin-ok: helper-contract -- the helper name is invoked"
        prefix = "F=\"$LIB/../docs/x.md\"\n"
        legacy = prefix + "assert_pin_unique \"legacy\" 'L' \"$F\""
        typed = prefix + f"assert_pin_unique \"typed\" 'T' \"$F\"  {marker}"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "docs/x.md"
            target.parent.mkdir(parents=True)
            target.write_text("L\nT\n", encoding="utf-8")
            findings = self.mod.scan_changed_sources(
                {"lib/test/new.sh": legacy},
                {"lib/test/old.sh": legacy},
                one_file_diff("lib/test/old.sh", legacy, "")
                + one_file_diff("lib/test/new.sh", "", legacy),
                repo_root=root,
            )
            self.assertEqual(1, len(findings))
            self.assertIn("missing structural declaration", findings[0])

            findings = self.mod.scan_changed_sources(
                {"lib/test/new.sh": typed},
                {"lib/test/old.sh": typed},
                one_file_diff("lib/test/old.sh", typed, "")
                + one_file_diff("lib/test/new.sh", "", typed),
                repo_root=root,
            )
            self.assertEqual([], findings)

            downgraded = prefix + "assert_pin_unique \"typed\" 'T' \"$F\""
            findings = self.mod.scan_changed_sources(
                {"lib/test/new.sh": downgraded},
                {"lib/test/old.sh": typed},
                one_file_diff("lib/test/old.sh", typed, "")
                + one_file_diff("lib/test/new.sh", "", downgraded),
                repo_root=root,
            )
            self.assertEqual(1, len(findings))

    def test_invalid_declaration_fails_after_a_move(self):
        old = "assert_pin_unique \"legacy\" 'L' \"$F\""
        invalid = (
            "assert_pin_unique \"moved\" 'L' \"$F\"  "
            "# structural-pin-ok: prose-presence -- invalid category"
        )
        findings = self.mod.scan_changed_sources(
            {"lib/test/new.sh": invalid},
            {"lib/test/old.sh": old},
            one_file_diff("lib/test/old.sh", old, "")
            + one_file_diff("lib/test/new.sh", "", invalid),
            repo_root="/repo",
        )
        self.assertEqual(1, len(findings))
        self.assertIn("unknown structural category", findings[0])

    def test_untyped_move_to_a_changed_target_surface_fails(self):
        old = (
            "F=\"$LIB/../scripts/tool.sh\"\n"
            "assert_pin_unique \"legacy\" 'TOKEN' \"$F\""
        )
        new = (
            "F=\"$LIB/../docs/tool.md\"\n"
            "assert_pin_unique \"moved\" 'TOKEN' \"$F\""
        )
        findings = self.mod.scan_changed_sources(
            {"lib/test/new.sh": new},
            {"lib/test/old.sh": old},
            one_file_diff("lib/test/old.sh", old, "")
            + one_file_diff("lib/test/new.sh", "", new),
            repo_root="/repo",
        )
        self.assertEqual(1, len(findings))

    def test_untyped_reformat_is_reclassified_and_no_move_matcher_remains(self):
        old = (
            'F="$LIB/../docs/x.md"\n'
            "assert_pin_unique \"legacy\" 'TOKEN' \"$F\""
        )
        new = (
            'F="$LIB/../docs/x.md"\n'
            "assert_pin_unique \\\n"
            "  \"legacy\" \\\n"
            "  'TOKEN' \\\n"
            "  \"$F\""
        )
        findings = self.mod.scan_changed_sources(
            {"lib/test/a.sh": new},
            {"lib/test/a.sh": old},
            one_file_diff("lib/test/a.sh", old, new),
            repo_root="/repo",
        )
        self.assertEqual(1, len(findings))
        self.assertIn("missing structural declaration", findings[0])
        self.assertFalse(hasattr(self.mod, "_move_class"))
        self.assertFalse(hasattr(self.mod, "_move_compatible"))

    def test_assignment_only_literal_change_reclassifies_unchanged_call(self):
        old = "LIT='old wording'\nassert_pin_unique \"wording\" \"$LIT\" \"$F\""
        new = "LIT='new wording'\nassert_pin_unique \"wording\" \"$LIT\" \"$F\""
        diff = (
            "diff --git a/lib/test/a.sh b/lib/test/a.sh\n"
            "--- a/lib/test/a.sh\n+++ b/lib/test/a.sh\n"
            "@@ -1 +1 @@\n-LIT='old wording'\n+LIT='new wording'\n"
        )
        findings = self.mod.scan_changed_sources(
            {"lib/test/a.sh": new},
            {"lib/test/a.sh": old},
            diff,
            repo_root="/repo",
        )
        self.assertEqual(1, len(findings))
        self.assertIn("new wording", findings[0])

    def test_inserted_site_does_not_shift_semantic_pairing_of_existing_sites(self):
        marker = "# structural-pin-ok: helper-contract -- executable helper token"
        prefix = "F=\"$LIB/../docs/x.md\"\n"
        existing_call = f"assert_pin_unique \"existing\" 'TOKEN' \"$F\"  {marker}"
        inserted = "assert_pin_unique \"new\" 'wording' \"$F\""
        existing = prefix + existing_call
        new = prefix + inserted + "\n" + existing_call
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "docs/x.md"
            target.parent.mkdir(parents=True)
            target.write_text("TOKEN\nwording\n", encoding="utf-8")
            findings = self.mod.scan_changed_sources(
                {"lib/test/a.sh": new},
                {"lib/test/a.sh": existing},
                one_file_diff("lib/test/a.sh", existing, new),
                repo_root=root,
            )
            self.assertEqual(1, len(findings))
            self.assertIn("wording", findings[0])

    def test_latest_assignment_before_call_controls_effective_literal(self):
        source = (
            "LIT='stale wording'\n"
            "LIT='effective wording'\n"
            "assert_pin_unique \"wording\" \"$LIT\" \"$F\""
        )
        sites = self.mod.extract_guard_sites(
            source, "lib/test/a.sh", repo_root="/repo"
        )
        self.assertEqual("effective wording", sites[0].literal)

    def test_legacy_scans_resolve_assignments_at_each_call_site(self):
        source = (
            "F=\"$LIB/../docs/first.md\"\n"
            "assert_pin_unique \"first\" 'FIRST' \"$F\"\n"
            "F=\"$LIB/../docs/second.md\"\n"
            "assert_pin_unique \"second\" 'SECOND' \"$F\""
        )
        pins = list(self.mod.extract_pins(source, "/repo/lib", {}))
        self.assertEqual(
            ["/repo/docs/first.md", "/repo/docs/second.md"],
            [pin["file"] for pin in pins],
        )

    def test_git_quoted_unified_diff_paths_are_decoded(self):
        for encoded, decoded in (
            ('"b/lib/test/quoted name.sh"', "lib/test/quoted name.sh"),
            ('"b/lib/test/\\303\\251.sh"', "lib/test/é.sh"),
        ):
            with self.subTest(encoded=encoded):
                diff = (
                    f'diff --git "a/lib/test/old.sh" {encoded}\n'
                    "--- a/lib/test/old.sh\n"
                    f"+++ {encoded}\n"
                    "@@ -0,0 +1 @@\n"
                    "+assert_pin_unique \"wording\" 'literal' \"$F\"\n"
                )
                patches = self.mod.parse_unified_diff(diff)
                self.assertEqual(decoded, patches[0].new_path)

    def test_malformed_unified_diff_fails_closed(self):
        malformed = (
            (
                "unterminated quoted path",
                ('diff --git a/lib/test/a.sh b/lib/test/a.sh\n'
                "--- a/lib/test/a.sh\n"
                '+++ "b/lib/test/a.sh\n'
                "@@ -0,0 +1 @@\n"
                "+assert_pin_unique \"wording\" 'literal' \"$F\"\n"),
            ),
            (
                "missing new header",
                ("diff --git a/lib/test/a.sh b/lib/test/a.sh\n"
                "--- a/lib/test/a.sh\n"
                "@@ -0,0 +1 @@\n"
                "+assert_pin_unique \"wording\" 'literal' \"$F\"\n"),
            ),
            (
                "malformed hunk",
                ("diff --git a/lib/test/a.sh b/lib/test/a.sh\n"
                "--- a/lib/test/a.sh\n"
                "+++ b/lib/test/a.sh\n"
                "@@ malformed @@\n"
                "+assert_pin_unique \"wording\" 'literal' \"$F\"\n"),
            ),
            (
                "truncated hunk",
                ("diff --git a/lib/test/a.sh b/lib/test/a.sh\n"
                "--- a/lib/test/a.sh\n"
                "+++ b/lib/test/a.sh\n"
                "@@ -0,0 +1,2 @@\n"
                "+assert_pin_unique \"wording\" 'literal' \"$F\"\n"),
            ),
            (
                "headers without hunk",
                ("diff --git a/lib/test/a.sh b/lib/test/a.sh\n"
                "--- a/lib/test/a.sh\n"
                "+++ b/lib/test/a.sh\n"),
            ),
            (
                "arbitrary post-header text",
                ("diff --git a/lib/test/a.sh b/lib/test/a.sh\n"
                "--- a/lib/test/a.sh\n"
                "+++ b/lib/test/a.sh\n"
                "GARBAGE\n"),
            ),
            (
                "both sides dev null",
                ("diff --git a/lib/test/a.sh b/lib/test/a.sh\n"
                "--- /dev/null\n"
                "+++ /dev/null\n"
                "@@ -0,0 +1 @@\n"
                "+wording\n"),
            ),
            (
                "misplaced no-newline marker",
                ("diff --git a/lib/test/a.sh b/lib/test/a.sh\n"
                "--- a/lib/test/a.sh\n"
                "+++ b/lib/test/a.sh\n"
                "@@ -1 +1 @@\n"
                "\\ No newline at end of file\n"
                "-old\n"
                "+new\n"),
            ),
            (
                "duplicate no-newline marker",
                ("diff --git a/lib/test/a.sh b/lib/test/a.sh\n"
                "--- a/lib/test/a.sh\n"
                "+++ b/lib/test/a.sh\n"
                "@@ -1 +1 @@\n"
                "-old\n"
                "\\ No newline at end of file\n"
                "\\ No newline at end of file\n"
                "+new\n"),
            ),
            (
                "bare diff header",
                "diff --git a/lib/test/a.sh b/lib/test/a.sh\n",
            ),
            (
                "index without change record",
                ("diff --git a/lib/test/a.sh b/lib/test/a.sh\n"
                "index 123..456 100644\n"),
            ),
            (
                "malformed index metadata",
                ("diff --git a/lib/test/a.sh b/lib/test/a.sh\n"
                "index garbage\n"),
            ),
        )
        for label, diff in malformed:
            with self.subTest(label=label), self.assertRaises(
                self.mod.InfrastructureError
            ):
                self.mod.parse_unified_diff(diff)

    def test_hunk_content_that_resembles_file_headers_is_valid(self):
        diff = (
            "diff --git a/lib/test/a.sh b/lib/test/a.sh\n"
            "--- a/lib/test/a.sh\n"
            "+++ b/lib/test/a.sh\n"
            "@@ -1 +1 @@\n"
            "---old\n"
            "+++new\n"
        )
        patches = self.mod.parse_unified_diff(diff)
        self.assertEqual(frozenset({1}), patches[0].deleted_lines)
        self.assertEqual(frozenset({1}), patches[0].added_lines)

    def test_valid_no_newline_markers_after_old_and_new_lines(self):
        diff = (
            "diff --git a/lib/test/a.sh b/lib/test/a.sh\n"
            "--- a/lib/test/a.sh\n"
            "+++ b/lib/test/a.sh\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "\\ No newline at end of file\n"
            "+new\n"
            "\\ No newline at end of file\n"
        )
        patches = self.mod.parse_unified_diff(diff)
        self.assertEqual(frozenset({1}), patches[0].deleted_lines)
        self.assertEqual(frozenset({1}), patches[0].added_lines)

    def test_complete_metadata_only_mode_change_is_valid(self):
        diff = (
            "diff --git a/lib/test/a.sh b/lib/test/a.sh\n"
            "old mode 100644\n"
            "new mode 100755\n"
        )
        self.assertEqual((), self.mod.parse_unified_diff(diff))

    def test_wrapper_family_comes_from_body_not_name_suffix(self):
        for name in ("fake_pin_red_under", "fake_pin_count"):
            with self.subTest(name=name):
                source = (
                    f"{name}() {{ devflow_module_pin_present \"$@\"; }}\n"
                    f"{name} \"wording\" 'literal' \"$F\""
                )
                sites = self.mod.extract_guard_sites(
                    source, "lib/test/a.sh", repo_root="/repo"
                )
                self.assertEqual(["static-helper"], [site.family for site in sites])
                findings = self.mod.scan_changed_sources(
                    {"lib/test/a.sh": source},
                    {"lib/test/a.sh": ""},
                    one_file_diff("lib/test/a.sh", "", source),
                    repo_root="/repo",
                )
                self.assertEqual(1, len(findings))

    def test_multiline_positional_wrapper_has_one_inferred_call_site(self):
        source = (
            "F=\"$LIB/../docs/x.md\"\n"
            "wrap() {\n"
            "  devflow_module_pin_present \"wrapped ${1}\" \"${2}\" \"${3}\"\n"
            "}\n"
            "wrap \"wording\" 'literal' \"$F\""
        )
        sites = self.mod.extract_guard_sites(
            source, "lib/test/a.sh", repo_root="/repo"
        )
        self.assertEqual(1, len(sites))
        self.assertEqual("literal", sites[0].literal)
        self.assertEqual("/repo/docs/x.md", sites[0].target_path)

    def test_helper_name_used_as_an_argument_is_not_a_call(self):
        sites = self.mod.extract_guard_sites(
            "printf '%s' assert_pin_unique",
            "lib/test/a.sh",
            repo_root="/repo",
        )
        self.assertEqual([], sites)

    def test_uninferred_forwarding_body_is_not_silently_skipped(self):
        source = 'f() { assert_pin_unique "$@" extra; }'
        sites = self.mod.extract_guard_sites(
            source, "lib/test/a.sh", repo_root="/repo"
        )
        self.assertEqual(1, len(sites))
        findings = self.mod.scan_changed_sources(
            {"lib/test/a.sh": source},
            {"lib/test/a.sh": ""},
            one_file_diff("lib/test/a.sh", "", source),
            repo_root="/repo",
        )
        self.assertEqual(1, len(findings))

    def test_function_comment_brace_does_not_terminate_wrapper_scan(self):
        source = (
            "F=\"$LIB/../docs/x.md\"\n"
            "wrap() {\n"
            "  # a comment with } must not close the body\n"
            "  devflow_module_pin_present \"$@\"\n"
            "}\n"
            "wrap \"wording\" 'literal' \"$F\""
        )
        sites = self.mod.extract_guard_sites(
            source, "lib/test/a.sh", repo_root="/repo"
        )
        self.assertEqual(1, len(sites))
        self.assertEqual("literal", sites[0].literal)

    def test_dependent_path_assignment_keeps_assignment_time_value(self):
        source = (
            "A=\"$LIB/../docs\"\n"
            "B=\"$A/x.md\"\n"
            "A=\"$LIB/../other\"\n"
            "assert_pin_unique \"wording\" 'literal' \"$B\""
        )
        sites = self.mod.extract_guard_sites(
            source, "lib/test/a.sh", repo_root="/repo"
        )
        self.assertEqual("/repo/docs/x.md", sites[0].target_path)

    def test_fixed_literal_inside_wrapper_definition_is_not_skipped(self):
        source = (
            "F=\"$LIB/../docs/x.md\"\n"
            "wrap() { devflow_module_pin_present \"wording\" 'literal' \"$F\"; }\n"
            "wrap"
        )
        sites = self.mod.extract_guard_sites(
            source, "lib/test/a.sh", repo_root="/repo"
        )
        self.assertEqual(1, len(sites))
        self.assertEqual("literal", sites[0].literal)

    def test_fixed_literal_wrapper_with_forwarded_target_is_inferred(self):
        for target_ref in ("$1", "${1}"):
            with self.subTest(target_ref=target_ref):
                source = (
                    "F=\"$LIB/../docs/x.md\"\n"
                    "wrap() { "
                    f"devflow_module_pin_present \"wording\" 'FIXED LITERAL' "
                    f'"{target_ref}"; }}\n'
                    "wrap \"$F\""
                )
                sites = self.mod.extract_guard_sites(
                    source, "lib/test/a.sh", repo_root="/repo"
                )
                self.assertEqual(1, len(sites))
                self.assertEqual("FIXED LITERAL", sites[0].literal)
                self.assertEqual("/repo/docs/x.md", sites[0].target_path)
                findings = self.mod.scan_changed_sources(
                    {"lib/test/a.sh": source},
                    {"lib/test/a.sh": ""},
                    one_file_diff("lib/test/a.sh", "", source),
                    repo_root="/repo",
                )
                self.assertEqual(1, len(findings))

    def test_fixed_prefix_before_splat_wrapper_is_inferred(self):
        source = (
            "F=\"$LIB/../docs/x.md\"\n"
            "wrap() { devflow_module_pin_present \"label\" \"$@\"; }\n"
            "wrap 'HUMAN PROSE' \"$F\""
        )
        sites = self.mod.extract_guard_sites(
            source, "lib/test/a.sh", repo_root="/repo"
        )
        self.assertEqual(1, len(sites))
        self.assertEqual("HUMAN PROSE", sites[0].literal)
        self.assertEqual("/repo/docs/x.md", sites[0].target_path)
        findings = self.mod.scan_changed_sources(
            {"lib/test/a.sh": source},
            {"lib/test/a.sh": ""},
            one_file_diff("lib/test/a.sh", "", source),
            repo_root="/repo",
        )
        self.assertEqual(1, len(findings))

    def test_raw_presence_unresolved_indented_and_quoted_targets_fail_closed(self):
        cases = (
            (
                "computed",
                ("DOC=\"$(printf %s \"$LIB/../docs/x.md\")\"\n"
                "assert_eq \"wording\" \"yes\" "
                "\"$(grep -qF -- 'HUMAN PROSE' \"$DOC\" && echo yes || echo no)\""),
            ),
            (
                "indented assignment",
                ("wrap() {\n"
                "  local DOC=\"$LIB/../docs/x.md\"\n"
                "  assert_eq \"wording\" \"yes\" "
                "\"$(grep -Fq -- 'HUMAN PROSE' \"$DOC\" && echo yes || echo no)\"\n"
                "}"),
            ),
            (
                "single-quoted target",
                ("assert_eq \"wording\" \"yes\" "
                "\"$(grep -Fq -- 'HUMAN PROSE' 'docs/x.md' "
                "&& echo yes || echo no)\""),
            ),
        )
        for label, source in cases:
            with self.subTest(label=label):
                sites = self.mod.extract_guard_sites(
                    source, "lib/test/a.sh", repo_root="/repo"
                )
                self.assertEqual(1, len(sites))
                findings = self.mod.scan_changed_sources(
                    {"lib/test/a.sh": source},
                    {"lib/test/a.sh": ""},
                    one_file_diff("lib/test/a.sh", "", source),
                    repo_root="/repo",
                )
                self.assertEqual(1, len(findings))

    def test_shell_cat_membership_presence_assertion_shares_policy(self):
        source = (
            "DOC=\"$LIB/../docs/x.md\"\n"
            "[[ \"$(cat \"$DOC\")\" == *'HUMAN PROSE'* ]]"
        )
        sites = self.mod.extract_guard_sites(
            source, "lib/test/a.sh", repo_root="/repo"
        )
        self.assertEqual(1, len(sites))
        self.assertEqual("HUMAN PROSE", sites[0].literal)
        findings = self.mod.scan_changed_sources(
            {"lib/test/a.sh": source},
            {"lib/test/a.sh": ""},
            one_file_diff("lib/test/a.sh", "", source),
            repo_root="/repo",
        )
        self.assertEqual(1, len(findings))

    def test_python_file_text_presence_assertion_shares_policy(self):
        source = (
            "from pathlib import Path\n"
            "import unittest\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_wording(self):\n"
            "        self.assertIn('advisory wording', Path('docs/x.md').read_text())\n"
        )
        sites = self.mod.extract_guard_sites(
            source, "lib/test/test_wording.py", repo_root="/repo"
        )
        self.assertEqual(1, len(sites))
        findings = self.mod.scan_changed_sources(
            {"lib/test/test_wording.py": source},
            {"lib/test/test_wording.py": ""},
            one_file_diff("lib/test/test_wording.py", "", source),
            repo_root="/repo",
        )
        self.assertEqual(1, len(findings))
        self.assertIn("advisory wording", findings[0])

    def test_python_regex_and_assigned_file_text_share_policy(self):
        cases = (
            (
                "regex",
                "self.assertRegex(Path('docs/x.md').read_text(), 'advisory wording')",
            ),
            (
                "assigned pathlib",
                ("text = Path('docs/x.md').read_text()\n"
                "self.assertIn('advisory wording', text)"),
            ),
            (
                "assigned open",
                ("text = open('docs/x.md').read()\n"
                "self.assertIn('advisory wording', text)"),
            ),
            (
                "plain assert",
                "assert 'advisory wording' in Path('docs/x.md').read_text()",
            ),
        )
        for label, body in cases:
            with self.subTest(label=label):
                source = "from pathlib import Path\n" + body + "\n"
                findings = self.mod.scan_changed_sources(
                    {"lib/test/test_wording.py": source},
                    {"lib/test/test_wording.py": ""},
                    one_file_diff("lib/test/test_wording.py", "", source),
                    repo_root="/repo",
                )
                self.assertEqual(1, len(findings))
                self.assertIn("advisory wording", findings[0])

    def test_python_assigned_read_respects_scope_order_and_reassignment(self):
        source = (
            "from pathlib import Path\n"
            "import unittest\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_runtime(self):\n"
            "        text = get_output()\n"
            "        self.assertIn('runtime status', text)\n\n"
            "    def test_file(self):\n"
            "        text = Path('docs/x.md').read_text()\n"
            "        text = get_output()\n"
            "        self.assertIn('later runtime status', text)\n"
        )
        sites = self.mod.extract_guard_sites(
            source, "lib/test/test_wording.py", repo_root="/repo"
        )
        self.assertEqual([], sites)

    def test_python_direct_file_assertion_can_use_valid_typed_boundary(self):
        marker = (
            "# structural-pin-ok: machine-sentinel-provenance -- "
            "the token is parsed by the consumer"
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "docs/x.md"
            target.parent.mkdir()
            target.write_text("TOKEN\n", encoding="utf-8")
            source = (
                "from pathlib import Path\n"
                "self.assertIn('TOKEN', Path('docs/x.md').read_text())  "
                f"{marker}\n"
            )
            findings = self.mod.scan_changed_sources(
                {"lib/test/test_wording.py": source},
                {"lib/test/test_wording.py": ""},
                one_file_diff("lib/test/test_wording.py", "", source),
                repo_root=root,
            )
        self.assertEqual([], findings)

    def test_scanner_population_is_exactly_registry_closed(self):
        registry = {
            "schema_version": 1,
            "test_modules": {
                "one": {
                    "path": "lib/test/modules/one.sh",
                    "minimum_assertions": 1,
                },
                "two": {
                    "path": "lib/test/modules/two.sh",
                    "minimum_assertions": 2,
                },
            }
        }
        expected = {
            "lib/test/run.sh",
            "lib/test/modules/one.sh",
            "lib/test/modules/two.sh",
        }
        self.assertEqual([], self.mod.validate_audited_population(registry, expected, expected))
        self.assertTrue(
            self.mod.validate_audited_population(
                registry, expected - {"lib/test/modules/two.sh"}, expected
            )
        )
        self.assertTrue(
            self.mod.validate_audited_population(
                registry, expected | {"lib/test/modules/stale.sh"}, expected
            )
        )

    def _static_registry(self):
        return {
            "schema_version": 1,
            "test_modules": {
                path.removeprefix("lib/test/modules/").removesuffix(".sh"): {
                    "path": path,
                    "minimum_assertions": 1,
                }
                for path in self.mod.AUDITED_PIN_SOURCES
                if path != "lib/test/run.sh"
            },
        }

    def _static_worktree_fixture(
        self,
        root,
        registry=None,
        calls=None,
        *,
        local_main_rc=1,
        merge_base="mergebase\n",
        python_tracked=(),
        python_untracked=(),
        show_rc=0,
    ):
        """Build a git_runner stub for ``scan_static_pin_changes``.

        The ``lib/test/test_*.py`` glob reads are answered from
        ``python_tracked``/``python_untracked`` and are kept distinct from the
        audited-source reads that share the same ``ls-files`` subcommand, so a
        test can drive the two populations independently.
        """
        for path in self.mod.AUDITED_PIN_SOURCES:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding="utf-8")
        adjudication_text = (
            REPO_ROOT / "lib/test/pin-corpus-adjudications.tsv"
        ).read_text(encoding="utf-8")
        adjudications = root / "lib/test/pin-corpus-adjudications.tsv"
        adjudications.parent.mkdir(parents=True, exist_ok=True)
        adjudications.write_text(adjudication_text, encoding="utf-8")
        retirement_manifests = {}
        for path in self.mod._RETIREMENT_MANIFEST_SPECS:
            payload = (REPO_ROOT / path).read_bytes()
            retirement_manifests[path] = payload
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        for path in tuple(python_tracked) + tuple(python_untracked):
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding="utf-8")
        registry_path = root / "scripts/workflow-flight-recorder-registry.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(
            json.dumps(registry or self._static_registry()),
            encoding="utf-8",
        )
        audited = "\n".join(sorted(self.mod.AUDITED_PIN_SOURCES)) + "\n"
        python_glob = "lib/test/test_*.py"

        def _lines(paths):
            return "".join(f"{path}\n" for path in sorted(paths))

        def _tree_rows(paths):
            return "".join(
                f"100644 blob object\t{path}\0" for path in sorted(paths)
            )

        def runner(args, **_kwargs):
            rendered = " ".join(args)
            if calls is not None:
                calls.append(rendered)
            if "show-ref --verify --quiet refs/heads/main" in rendered:
                return subprocess.CompletedProcess(args, local_main_rc, "", "")
            if "merge-base --is-ancestor" in rendered:
                return subprocess.CompletedProcess(args, 0, "", "")
            if "merge-base origin/main HEAD" in rendered:
                return subprocess.CompletedProcess(args, 0, merge_base, "")
            if "rev-parse HEAD" in rendered:
                return subprocess.CompletedProcess(args, 0, "head\n", "")
            if "ls-tree -r -z head" in rendered:
                return subprocess.CompletedProcess(
                    args,
                    0,
                    _tree_rows(set(self.mod.AUDITED_PIN_SOURCES) | set(python_tracked)),
                    "",
                )
            if "ls-tree -r -z mergebase" in rendered:
                return subprocess.CompletedProcess(
                    args,
                    0,
                    _tree_rows(set(self.mod.AUDITED_PIN_SOURCES) | set(python_tracked)),
                    "",
                )
            if python_glob in rendered:
                population = (
                    python_untracked
                    if "ls-files --others" in rendered
                    else python_tracked
                )
                return subprocess.CompletedProcess(args, 0, _lines(population), "")
            if "ls-files --cached" in rendered or "ls-tree -r" in rendered:
                return subprocess.CompletedProcess(args, 0, audited, "")
            if (
                "ls-tree HEAD -- lib/test/pin-corpus-adjudications.tsv"
                in rendered
            ):
                return subprocess.CompletedProcess(
                    args,
                    0,
                    "100644 blob object\t"
                    "lib/test/pin-corpus-adjudications.tsv\n",
                    "",
                )
            for path, payload in retirement_manifests.items():
                if f"ls-tree mergebase -- {path}" in rendered:
                    return subprocess.CompletedProcess(
                        args, 0, f"100644 blob object\t{path}\n", ""
                    )
                if f"ls-tree HEAD -- {path}" in rendered:
                    return subprocess.CompletedProcess(
                        args, 0, f"100644 blob object\t{path}\n", ""
                    )
                if (
                    f"show mergebase:{path}" in rendered
                    or f"show HEAD:{path}" in rendered
                ):
                    return subprocess.CompletedProcess(args, 0, payload, b"")
            if "show HEAD:lib/test/pin-corpus-adjudications.tsv" in rendered:
                return subprocess.CompletedProcess(
                    args, 0, adjudication_text.encode("utf-8"), b""
                )
            if (
                "show mergebase:lib/test/pin-corpus-adjudications.tsv"
                in rendered
            ):
                return subprocess.CompletedProcess(
                    args, 0, adjudication_text.encode("utf-8"), b""
                )
            if "show mergebase:" in rendered:
                return subprocess.CompletedProcess(args, show_rc, "", "injected")
            return subprocess.CompletedProcess(args, 0, "", "")

        return runner

    def test_static_worktree_git_and_population_failures_are_infrastructure(self):
        commands = (
            "rev-parse --verify origin/main",
            "merge-base --is-ancestor",
            "merge-base origin/main HEAD",
            "diff --no-color",
            "diff --cached",
            "ls-files --others",
            "ls-tree -r",
        )
        for failed_command in commands:
            with self.subTest(command=failed_command):

                def runner(args, failed_command=failed_command, **_kwargs):
                    rendered = " ".join(args)
                    rc = 1 if failed_command in rendered else 0
                    stdout = (
                        "mergebase\n"
                        if "merge-base origin/main HEAD" in rendered
                        else ""
                    )
                    return subprocess.CompletedProcess(args, rc, stdout, "injected")

                with self.assertRaises(self.mod.InfrastructureError):
                    self.mod.scan_static_pin_changes(
                        "/repo",
                        git_runner=runner,
                    )

        def broken_local_main(args, **_kwargs):
            rendered = " ".join(args)
            if "refs/heads/main" in rendered:
                return subprocess.CompletedProcess(args, 2, "", "injected")
            return subprocess.CompletedProcess(args, 0, "base\n", "")

        with self.assertRaisesRegex(
            self.mod.InfrastructureError,
            "local main resolution failed",
        ):
            self.mod.scan_static_pin_changes(
                "/repo",
                git_runner=broken_local_main,
            )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry = self._static_registry()
            registry["test_modules"].pop(next(iter(registry["test_modules"])))
            with self.assertRaisesRegex(
                self.mod.InfrastructureError,
                "stale audited pin source absent from registry",
            ):
                self.mod.scan_static_pin_changes(
                    root,
                    git_runner=self._static_worktree_fixture(root, registry),
                )

    def _public_static_failure(self, runner):
        def static_only(repo_root, base_ref="origin/main", **_kwargs):
            return self.mod.scan_static_pin_changes(
                repo_root,
                base_ref,
                git_runner=runner,
            )

        with (
            mock.patch.object(self.mod, "scan_worktree", side_effect=static_only),
            mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            try:
                rc = self.mod.main(
                    ["pin-corpus-lint.py", "mutation-routing-worktree", "/repo"]
                )
            except (OSError, UnicodeDecodeError) as exc:
                self.fail(
                    "public static gate leaked "
                    f"{type(exc).__name__} instead of infrastructure exit 2: {exc}"
                )
        return rc, stdout.getvalue(), stderr.getvalue()

    def test_public_static_git_spawn_failure_is_attributed_infrastructure(self):
        def runner(args, **_kwargs):
            raise OSError("injected spawn failure")

        rc, stdout, stderr = self._public_static_failure(runner)
        self.assertEqual(2, rc)
        self.assertEqual("", stdout)
        self.assertIn("MUTATION-ROUTING-INFRASTRUCTURE", stderr)
        self.assertIn("git rev-parse --verify origin/main", stderr)
        self.assertIn("injected spawn failure", stderr)

    def test_public_static_git_decode_failure_is_attributed_infrastructure(self):
        def runner(args, **_kwargs):
            rendered = " ".join(args)
            if "show-ref --verify --quiet refs/heads/main" in rendered:
                raise UnicodeDecodeError(
                    "utf-8",
                    b"\xff",
                    0,
                    1,
                    "injected decode failure",
                )
            return subprocess.CompletedProcess(args, 0, "base\n", "")

        rc, stdout, stderr = self._public_static_failure(runner)
        self.assertEqual(2, rc)
        self.assertEqual("", stdout)
        self.assertIn("MUTATION-ROUTING-INFRASTRUCTURE", stderr)
        self.assertIn(
            "git show-ref --verify --quiet refs/heads/main",
            stderr,
        )
        self.assertIn("injected decode failure", stderr)

    def test_static_worktree_reads_merge_base_blobs_without_local_main(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            calls = []
            findings = self.mod.scan_static_pin_changes(
                root,
                git_runner=self._static_worktree_fixture(root, calls=calls),
            )
        self.assertEqual([], findings)
        self.assertTrue(
            any("merge-base origin/main HEAD" in call for call in calls),
            calls,
        )
        self.assertTrue(any("show mergebase:" in call for call in calls), calls)

    def test_static_scan_completion_marker_is_written_only_when_both_passes_run(self):
        """Issue #967: the completion sentinel distinguishes "ran and clean" from
        "a precondition raised and the classifier never ran". Both directions are
        driven here because run.sh's assertion keys on the sentinel's presence."""
        marker = self.mod.STATIC_SCAN_COMPLETED_MARKER
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                findings = self.mod.scan_static_pin_changes(
                    root,
                    git_runner=self._static_worktree_fixture(root),
                )
            self.assertEqual([], findings)
            self.assertIn(marker, stderr.getvalue())

        # A precondition raise must leave the sentinel unwritten: that absence is
        # the whole signal, so a marker emitted on an aborted run would restore the
        # silent skip this guard exists to end.
        def raising_runner(args, **_kwargs):
            rendered = " ".join(args)
            rc = 1 if "rev-parse --verify origin/main" in rendered else 0
            return subprocess.CompletedProcess(args, rc, "", "injected")

        with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(self.mod.InfrastructureError):
                self.mod.scan_static_pin_changes("/repo", git_runner=raising_runner)
        self.assertNotIn(marker, stderr.getvalue())

    def test_static_worktree_with_local_main_present_verifies_ancestry(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            calls = []
            findings = self.mod.scan_static_pin_changes(
                root,
                git_runner=self._static_worktree_fixture(
                    root, calls=calls, local_main_rc=0
                ),
            )
        self.assertEqual([], findings)
        self.assertTrue(
            any(
                "merge-base --is-ancestor refs/heads/main origin/main" in call
                for call in calls
            ),
            calls,
        )

    def test_static_worktree_empty_merge_base_is_infrastructure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaisesRegex(
                self.mod.InfrastructureError,
                "comparison merge base resolved to empty output",
            ):
                self.mod.scan_static_pin_changes(
                    root,
                    git_runner=self._static_worktree_fixture(root, merge_base="  \n"),
                )

    def test_static_worktree_base_blob_read_failure_is_infrastructure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaisesRegex(
                self.mod.InfrastructureError,
                r"git show mergebase:.* failed \(exit 1\)",
            ):
                self.mod.scan_static_pin_changes(
                    root,
                    git_runner=self._static_worktree_fixture(root, show_rc=1),
                )

    def test_static_worktree_unreadable_pin_source_is_infrastructure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runner = self._static_worktree_fixture(root)
            # The fixture materialized every audited source as a file; replacing
            # one with a directory makes read_text raise IsADirectoryError, the
            # OSError arm of the pin-source read.
            victim = root / min(self.mod.AUDITED_PIN_SOURCES)
            victim.unlink()
            victim.mkdir()
            with self.assertRaisesRegex(
                self.mod.InfrastructureError,
                "pin source unreadable: " + re.escape(min(self.mod.AUDITED_PIN_SOURCES)),
            ):
                self.mod.scan_static_pin_changes(root, git_runner=runner)

    def test_static_worktree_reads_python_glob_populations_separately(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            calls = []
            findings = self.mod.scan_static_pin_changes(
                root,
                git_runner=self._static_worktree_fixture(
                    root,
                    calls=calls,
                    python_tracked=("lib/test/test_tracked_fixture.py",),
                    python_untracked=("lib/test/test_untracked_fixture.py",),
                ),
            )
        self.assertEqual([], findings)
        glob_calls = [call for call in calls if "lib/test/test_*.py" in call]
        self.assertEqual(1, len(glob_calls), calls)
        self.assertIn("ls-files --others", glob_calls[0])
        self.assertTrue(any("ls-tree -r -z head -- lib/test" in call for call in calls))
        # Both populations reached the scan: tracked Python leaves come from the
        # exact HEAD tree, while only the untracked population uses the glob and
        # receives a synthetic diff stanza.
        self.assertTrue(
            any("lib/test/test_tracked_fixture.py" in call for call in calls), calls
        )
        self.assertTrue(
            any("lib/test/test_untracked_fixture.py" in call for call in calls), calls
        )

    def test_duplicate_registry_keys_are_rejected_at_load_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "registry.json"
            path.write_text(
                '{"schema_version":0,"schema_version":1,"test_modules":{}}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                self.mod.InfrastructureError, "duplicate registry key"
            ):
                self.mod.load_registry(path)

    def test_public_worktree_command_maps_infrastructure_and_findings_to_exit_codes(self):
        with mock.patch.object(
            self.mod, "scan_worktree", side_effect=self.mod.InfrastructureError("boom")
        ):
            self.assertEqual(
                2, self.mod.main(["pin-corpus-lint.py", "mutation-routing-worktree", "/repo"])
            )
        with mock.patch.object(
            self.mod, "scan_worktree", return_value=["MUTATION-ROUTING\tfinding"]
        ):
            self.assertEqual(
                3, self.mod.main(["pin-corpus-lint.py", "mutation-routing-worktree", "/repo"])
            )

    def test_registry_fixture_is_json_serializable(self):
        # Sanity-check the same shape used by the production population validator.
        registry = {
            "schema_version": 1,
            "test_modules": {
                "x": {
                    "path": "lib/test/modules/x.sh",
                    "minimum_assertions": 1,
                }
            },
        }
        self.assertEqual(
            [],
            self.mod.validate_audited_population(
                registry,
                {"lib/test/run.sh", "lib/test/modules/x.sh"},
                {"lib/test/run.sh", "lib/test/modules/x.sh"},
            ),
        )


class AdjudicationStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_linter()

    def test_current_adjudications_preserve_exact_valid_rows(self):
        literal = "literal:" + "a" * 64
        site = "site:" + "b" * 64
        text = (
            "adjudication_key\tbucket_final\trationale\n"
            f"{literal}\tboundary\t exact rationale \n"
            f"{site}\tconfig-key\tsecond rationale\n"
        )
        self.assertEqual(
            {
                literal: ("boundary", " exact rationale "),
                site: ("config-key", "second rationale"),
            },
            self.mod.parse_current_adjudications(text),
        )

    def test_current_adjudications_reject_noncanonical_table_rows(self):
        key = "literal:" + "a" * 64
        invalid = {
            "reordered header": (
                "bucket_final\tadjudication_key\trationale\n"
                f"boundary\t{key}\twhy\n"
            ),
            "extra cell": (
                "adjudication_key\tbucket_final\trationale\n"
                f"{key}\tboundary\twhy\textra\n"
            ),
            "invalid key grammar": (
                "adjudication_key\tbucket_final\trationale\n"
                "literal:ABC\tboundary\twhy\n"
            ),
            "unclear bucket": (
                "adjudication_key\tbucket_final\trationale\n"
                f"{key}\tunclear\twhy\n"
            ),
            "empty rationale": (
                "adjudication_key\tbucket_final\trationale\n"
                f"{key}\tboundary\t\n"
            ),
            "duplicate key": (
                "adjudication_key\tbucket_final\trationale\n"
                f"{key}\tboundary\tfirst\n{key}\tboundary\tsecond\n"
            ),
            "carriage return": (
                "adjudication_key\tbucket_final\trationale\r\n"
                f"{key}\tboundary\twhy\r\n"
            ),
            "tombstone event": (
                "adjudication_key\tbucket_final\trationale\n"
                f"tombstone:{key}\ttombstone\twhy\n"
            ),
            "supersede event": (
                "adjudication_key\tbucket_final\trationale\n"
                f"supersede:{key}\tboundary\twhy\n"
            ),
        }
        for label, text in invalid.items():
            with self.subTest(label=label):
                with self.assertRaises(self.mod.InfrastructureError):
                    self.mod.parse_current_adjudications(text)

    def test_delta_manifest_requires_exact_canonical_json_states(self):
        key = "literal:" + "a" * 64
        valid = (
            "adjudication_key\tbase_state\tcurrent_state\n"
            f'{key}\tnull\t["boundary","new rationale"]\n'
        )
        self.assertEqual(
            {key: (None, ("boundary", "new rationale"))},
            self.mod.parse_adjudication_delta_manifest(valid),
        )

        invalid = {
            "operation field": (
                "adjudication_key\tbase_state\tcurrent_state\toperation\n"
                f'{key}\tnull\t["boundary","new rationale"]\tadd\n'
            ),
            "noncompact state": (
                "adjudication_key\tbase_state\tcurrent_state\n"
                f'{key}\tnull\t["boundary", "new rationale"]\n'
            ),
            "wrong state shape": (
                "adjudication_key\tbase_state\tcurrent_state\n"
                f'{key}\tnull\t["boundary"]\n'
            ),
            "event key": (
                "adjudication_key\tbase_state\tcurrent_state\n"
                f'tombstone:{key}\tnull\t["boundary","new rationale"]\n'
            ),
        }
        for label, text in invalid.items():
            with self.subTest(label=label):
                with self.assertRaises(self.mod.InfrastructureError):
                    self.mod.parse_adjudication_delta_manifest(text)

    def test_canonical_table_hash_and_delta_capture_all_state_changes(self):
        first = "literal:" + "a" * 64
        second = "site:" + "b" * 64
        third = "literal:" + "c" * 64
        base = {
            first: ("boundary", "old rationale"),
            second: ("config-key", "deleted rationale"),
        }
        current = {
            first: ("boundary", "new rationale"),
            third: ("generated", "added rationale"),
        }
        self.assertEqual(
            (
                '[['
                '"literal:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
                '"boundary","old rationale"],'
                '["site:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",'
                '"config-key","deleted rationale"]]'
            ),
            self.mod.canonical_adjudication_table_state(base),
        )
        self.assertEqual(
            self.mod.hash_adjudication_table_state(base),
            self.mod.hash_adjudication_table_state(dict(reversed(list(base.items())))),
        )
        self.assertNotEqual(
            self.mod.hash_adjudication_table_state(base),
            self.mod.hash_adjudication_table_state(current),
        )
        self.assertEqual(
            {
                first: (("boundary", "old rationale"), ("boundary", "new rationale")),
                second: (("config-key", "deleted rationale"), None),
                third: (None, ("generated", "added rationale")),
            },
            self.mod.compute_adjudication_delta(base, current),
        )

    def test_delta_authorization_requires_exact_complete_current_state(self):
        key = "literal:" + "a" * 64
        changed = ("boundary", "new rationale")
        cases = {
            "addition": ({}, {key: changed}, {key: (None, changed)}),
            "deletion": ({key: changed}, {}, {key: (changed, None)}),
            "modification": (
                {key: ("boundary", "old rationale")},
                {key: changed},
                {key: (("boundary", "old rationale"), changed)},
            ),
        }
        for label, (base, current, exact) in cases.items():
            with self.subTest(change=label):
                self.assertTrue(
                    self.mod.is_exactly_authorized_adjudication_delta(base, current, [exact])
                )
                self.assertFalse(
                    self.mod.is_exactly_authorized_adjudication_delta(base, current, [])
                )

        base, current, exact = cases["modification"]
        with self.assertRaisesRegex(self.mod.InfrastructureError, "stale or extra"):
            self.mod.is_exactly_authorized_adjudication_delta(
                base,
                current,
                [{key: (("boundary", "older rationale"), ("boundary", "new rationale"))}],
            )
        with self.assertRaisesRegex(self.mod.InfrastructureError, "stale or extra"):
            self.mod.is_exactly_authorized_adjudication_delta(
                base,
                current,
                [{key: (("boundary", "old rationale"), ("boundary", "old rationale"))}],
            )
        with self.assertRaisesRegex(self.mod.InfrastructureError, "duplicate key"):
            self.mod.is_exactly_authorized_adjudication_delta(base, current, [exact, exact])
        extra_key = "site:" + "b" * 64
        with self.assertRaisesRegex(self.mod.InfrastructureError, "stale or extra"):
            self.mod.is_exactly_authorized_adjudication_delta(
                base,
                current,
                [
                    exact,
                    {extra_key: (None, ("generated", "unrelated authorization"))},
                ],
            )

    def test_current_base_ancestry_requires_the_configured_base_tip(self):
        def runner(outputs):
            def invoke(args, **kwargs):
                return subprocess.CompletedProcess(args, 0, outputs[tuple(args[3:])], "")

            return invoke

        outputs = {
            ("merge-base", "origin/main", "HEAD"): "base-tip\n",
            ("rev-parse", "origin/main"): "base-tip\n",
        }
        self.assertEqual(
            "base-tip",
            self.mod.require_current_adjudication_base(
                "/repo", "origin/main", git_runner=runner(outputs)
            ),
        )
        outputs[("merge-base", "origin/main", "HEAD")] = "older-tip\n"
        with self.assertRaisesRegex(self.mod.InfrastructureError, "not based on current"):
            self.mod.require_current_adjudication_base(
                "/repo", "origin/main", git_runner=runner(outputs)
            )

    def _bundle_manifest(self):
        key = "literal:" + "a" * 64
        return (
            "adjudication_key\tbase_state\tcurrent_state\n"
            f'{key}\tnull\t["boundary","authorized rationale"]\n'
        )

    def _commit(self, root, message):
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", message], cwd=root, check=True)

    def _prepared_bundle_repo(self, root):
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"], cwd=root, check=True
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"], cwd=root, check=True
        )
        historical = (
            root
            / ".prflow/logs/pin-corpus-adjudication-changes/historical/adjudication-delta.tsv"
        )
        historical.parent.mkdir(parents=True)
        historical.write_text(self._bundle_manifest(), encoding="utf-8")
        self._commit(root, "base")
        base = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True, capture_output=True
        ).stdout.strip()
        current = (
            root
            / ".prflow/logs/pin-corpus-adjudication-changes/current/adjudication-delta.tsv"
        )
        current.parent.mkdir(parents=True)
        current.write_text(self._bundle_manifest(), encoding="utf-8")
        self._commit(root, "add current bundle")
        return base, historical, current

    def test_new_bundle_discovery_rejects_historical_changes(self):
        key = "literal:" + "a" * 64
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, historical, _added = self._prepared_bundle_repo(root)
            self.assertEqual(
                [{key: (None, ("boundary", "authorized rationale"))}],
                self.mod.discover_new_adjudication_delta_manifests(root, base),
            )
            historical.write_text(
                self._bundle_manifest().replace("authorized", "changed"), encoding="utf-8"
            )
            self._commit(root, "alter historical bundle")
            with self.assertRaisesRegex(self.mod.InfrastructureError, "historical"):
                self.mod.discover_new_adjudication_delta_manifests(root, base)

    def test_new_bundle_discovery_rejects_unsafe_ids_and_nested_paths(self):
        def runner(diff_row):
            def invoke(args, **kwargs):
                command = tuple(args[3:])
                output = "" if command[0] in {"ls-tree", "status"} else diff_row
                return subprocess.CompletedProcess(args, 0, output, "")

            return invoke

        for label, path in (
            ("dot id", ".prflow/logs/pin-corpus-adjudication-changes/./adjudication-delta.tsv"),
            ("dotdot id", ".prflow/logs/pin-corpus-adjudication-changes/../adjudication-delta.tsv"),
        ):
            with self.subTest(case=label):
                with self.assertRaisesRegex(self.mod.InfrastructureError, "unsafe bundle ID"):
                    self.mod.discover_new_adjudication_delta_manifests(
                        "/repo", "base", git_runner=runner(f"A\t{path}\n")
                    )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, _, current = self._prepared_bundle_repo(root)
            nested = current.parent / "nested" / "unexpected.tsv"
            nested.parent.mkdir()
            nested.write_text(self._bundle_manifest(), encoding="utf-8")
            self._commit(root, "add unexpected nested file")
            with self.assertRaisesRegex(self.mod.InfrastructureError, "unexpected bundle path"):
                self.mod.discover_new_adjudication_delta_manifests(root, base)

    def test_new_bundle_discovery_rejects_worktree_drift_and_head_symlinks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "repo"
            root.mkdir()
            base, historical, current = self._prepared_bundle_repo(root)
            current.write_text(
                self._bundle_manifest().replace("authorized", "tampered"), encoding="utf-8"
            )
            with self.assertRaisesRegex(self.mod.InfrastructureError, "bundle worktree differs"):
                self.mod.discover_new_adjudication_delta_manifests(root, base)
            current.unlink()
            with self.assertRaisesRegex(self.mod.InfrastructureError, "bundle worktree differs"):
                self.mod.discover_new_adjudication_delta_manifests(root, base)
            subprocess.run(["git", "checkout", "--", str(current.relative_to(root))], cwd=root, check=True)
            historical.write_text(
                self._bundle_manifest().replace("authorized", "tampered"), encoding="utf-8"
            )
            with self.assertRaisesRegex(self.mod.InfrastructureError, "bundle worktree differs"):
                self.mod.discover_new_adjudication_delta_manifests(root, base)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "repo"
            root.mkdir()
            base, _, current = self._prepared_bundle_repo(root)
            current.unlink()
            external = Path(td) / "external-manifest.tsv"
            external.write_text(self._bundle_manifest(), encoding="utf-8")
            current.symlink_to(external)
            self._commit(root, "add symlinked bundle manifest")
            with self.assertRaisesRegex(self.mod.InfrastructureError, "HEAD blob"):
                self.mod.discover_new_adjudication_delta_manifests(root, base)


class AdjudicationChangeScanTests(unittest.TestCase):
    MIGRATION_PATH = (
        ".prflow/logs/pin-corpus-adjudication-changes/"
        "2026-07-26-pr-849/migration.tsv"
    )

    @classmethod
    def setUpClass(cls):
        cls.mod = load_linter()
        cls.live_table = (
            REPO_ROOT / "lib/test/pin-corpus-adjudications.tsv"
        ).read_text(encoding="utf-8")
        cls.legacy_table = subprocess.run(
            [
                "git",
                "show",
                ("63585ad75031859db3b25db5432e3af3d515ba3a:"
                "lib/test/pin-corpus-adjudications.tsv"),
            ],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        cls.migration_certificate = (
            REPO_ROOT / cls.MIGRATION_PATH
        ).read_text(encoding="utf-8")

    def _commit(self, root, message):
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", message], cwd=root, check=True)
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def _repo(self, root, base_table):
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=root,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=root,
            check=True,
        )
        table = root / "lib/test/pin-corpus-adjudications.tsv"
        table.parent.mkdir(parents=True)
        table.write_text(base_table, encoding="utf-8")
        base = self._commit(root, "base")
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/main", base],
            cwd=root,
            check=True,
        )
        return base, table

    def _write_bundle(self, root, relative, text):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _scan(self, root, merge_base):
        return self.mod.scan_adjudication_changes(
            root, merge_base, "origin/main"
        )

    def test_former_legacy_base_is_rejected_by_strict_current_state_parser(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, table = self._repo(root, self.legacy_table)
            table.write_text(self.live_table, encoding="utf-8")
            self._commit(root, "replace legacy event table")
            with self.assertRaisesRegex(
                self.mod.InfrastructureError, "invalid adjudication key"
            ):
                self._scan(root, base)

    def test_new_migration_certificate_is_not_a_supported_bundle_payload(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, _table = self._repo(root, self.live_table)
            self._write_bundle(
                root, self.MIGRATION_PATH, self.migration_certificate
            )
            self._commit(root, "attempt a second migration")
            with self.assertRaisesRegex(
                self.mod.InfrastructureError, "unexpected bundle path"
            ):
                self._scan(root, base)

    def test_historical_migration_certificate_is_inert_but_immutable(self):
        for mutation in ("edit", "delete", "type"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                _base, _table = self._repo(root, self.live_table)
                certificate = self._write_bundle(
                    root, self.MIGRATION_PATH, self.migration_certificate
                )
                base = self._commit(root, "record historical migration")
                subprocess.run(
                    ["git", "update-ref", "refs/remotes/origin/main", base],
                    cwd=root,
                    check=True,
                )
                self.assertEqual([], self._scan(root, base))

                if mutation == "edit":
                    certificate.write_text(
                        self.migration_certificate + "changed\n",
                        encoding="utf-8",
                    )
                else:
                    certificate.unlink()
                    if mutation == "type":
                        target = root / "historical-certificate.tsv"
                        target.write_text(
                            self.migration_certificate, encoding="utf-8"
                        )
                        certificate.symlink_to(target)
                self._commit(root, f"{mutation} historical migration")
                with self.assertRaises(self.mod.InfrastructureError):
                    self._scan(root, base)

    def test_strict_table_delta_requires_exact_authorization(self):
        key = "literal:" + "a" * 64
        base_table = (
            "adjudication_key\tbucket_final\trationale\n"
            f"{key}\tboundary\told rationale\n"
        )
        current_table = base_table.replace("old rationale", "new rationale")
        manifest = (
            "adjudication_key\tbase_state\tcurrent_state\n"
            f'{key}\t["boundary","old rationale"]\t'
            '["boundary","new rationale"]\n'
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, table = self._repo(root, base_table)
            table.write_text(current_table, encoding="utf-8")
            self._commit(root, "unauthorized change")
            self.assertEqual(
                ["MUTATION-ROUTING\tunauthorized pin adjudication delta"],
                self._scan(root, base),
            )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, table = self._repo(root, base_table)
            table.write_text(current_table, encoding="utf-8")
            self._write_bundle(
                root,
                ".prflow/logs/pin-corpus-adjudication-changes/change-1/"
                "adjudication-delta.tsv",
                manifest,
            )
            self._commit(root, "authorized change")
            self.assertEqual([], self._scan(root, base))

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, table = self._repo(root, base_table)
            table.write_text(current_table, encoding="utf-8")
            self._write_bundle(
                root,
                ".prflow/logs/pin-corpus-adjudication-changes/change-1/"
                "adjudication-delta.tsv",
                manifest.replace("old rationale", "older rationale"),
            )
            self._commit(root, "stale authorization")
            with self.assertRaisesRegex(self.mod.InfrastructureError, "stale or extra"):
                self._scan(root, base)

    def test_adjudication_change_rejects_a_branch_behind_the_base_tip(self):
        key = "literal:" + "a" * 64
        base_table = (
            "adjudication_key\tbucket_final\trationale\n"
            f"{key}\tboundary\told rationale\n"
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, table = self._repo(root, base_table)
            subprocess.run(["git", "switch", "-qc", "feature"], cwd=root, check=True)
            table.write_text(
                base_table.replace("old rationale", "new rationale"),
                encoding="utf-8",
            )
            self._write_bundle(
                root,
                ".prflow/logs/pin-corpus-adjudication-changes/change-1/"
                "adjudication-delta.tsv",
                (
                    "adjudication_key\tbase_state\tcurrent_state\n"
                    f'{key}\t["boundary","old rationale"]\t'
                    '["boundary","new rationale"]\n'
                ),
            )
            feature = self._commit(root, "feature change")
            subprocess.run(["git", "switch", "--detach", base], cwd=root, check=True)
            (root / "main-advance.txt").write_text("new base tip\n", encoding="utf-8")
            main_tip = self._commit(root, "advance main")
            subprocess.run(
                ["git", "update-ref", "refs/remotes/origin/main", main_tip],
                cwd=root,
                check=True,
            )
            subprocess.run(["git", "switch", "--detach", feature], cwd=root, check=True)
            with self.assertRaisesRegex(
                self.mod.InfrastructureError, "not based on current"
            ):
                self._scan(root, base)

    def test_committed_delta_cannot_be_hidden_by_restoring_only_the_worktree(self):
        key = "literal:" + "a" * 64
        base_table = (
            "adjudication_key\tbucket_final\trationale\n"
            f"{key}\tboundary\told rationale\n"
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, table = self._repo(root, base_table)
            table.write_text(
                base_table.replace("old rationale", "unauthorized rationale"),
                encoding="utf-8",
            )
            self._commit(root, "committed unauthorized delta")
            self.assertEqual(
                ["MUTATION-ROUTING\tunauthorized pin adjudication delta"],
                self._scan(root, base),
            )
            table.write_text(base_table, encoding="utf-8")
            with self.assertRaisesRegex(
                self.mod.InfrastructureError,
                "adjudication table worktree differs from HEAD",
            ):
                self._scan(root, base)

    def test_adjudication_change_rejects_a_committed_table_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, table = self._repo(root, self.live_table)
            resolved = root / "resolved.tsv"
            resolved.write_text(self.live_table, encoding="utf-8")
            table.unlink()
            table.symlink_to("../../resolved.tsv")
            self._commit(root, "symlinked adjudication table")
            with self.assertRaisesRegex(
                self.mod.InfrastructureError,
                "adjudication table is not a regular HEAD blob",
            ):
                self._scan(root, base)

    def test_clean_head_rejects_dirty_table_edits_and_deletion(self):
        for mutation in ("edit", "delete"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                base, table = self._repo(root, self.live_table)
                self.assertEqual([], self._scan(root, base))
                if mutation == "edit":
                    table.write_text(
                        self.live_table.replace("boundary", "generated", 1),
                        encoding="utf-8",
                    )
                else:
                    table.unlink()
                with self.assertRaisesRegex(
                    self.mod.InfrastructureError,
                    "adjudication table worktree differs from HEAD",
                ):
                    self._scan(root, base)


class RetiredPinRevivalTests(unittest.TestCase):
    LITERAL = "MACHINE SENTINEL"
    RATIONALE = "the fenced token is consumed as a machine sentinel"
    MARKER = (
        "# structural-pin-ok: machine-sentinel-provenance -- "
        + RATIONALE
    )
    SOURCE = (
        'F="$LIB/../docs/x.md"\n'
        "assert_pin_unique \"sentinel\" 'MACHINE SENTINEL' \"$F\"  "
        + MARKER
        + "\n"
    )

    @classmethod
    def setUpClass(cls):
        cls.mod = load_linter()
        cls.classifier = load_classifier()
        cls.literal_key = (
            "literal:" + hashlib.sha256(cls.LITERAL.encode("utf-8")).hexdigest()
        )

    def _commit(self, root, message):
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", message], cwd=root, check=True)
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def _write_retirement_manifests(
        self,
        root,
        retired_source="lib/test/new.sh",
        retired_helper="assert_pin_unique",
    ):
        # Every source_file/literal/resolved_target cell is encode_cell (JSON)
        # inside a CSV cell -- the exact double-encoding pin-corpus-classifier.py
        # writes and _strict_retirement_manifest_literals now reads for all three
        # (issue #1006). The RETIRE_PROSE row's (source_file, helper,
        # resolved_target) matches the revival site the tests build below
        # (`lib/test/new.sh`, assert_pin_unique, docs/x.md), so retirement covers
        # that site by default; a caller passes ``retired_source`` to retire the
        # literal at a DIFFERENT site instead.
        manifests = {
            ".prflow/logs/residual-prose-retirement-manifest.tsv": (
                "source_file\thelper\tassertion_name\tliteral\tresolved_target\t"
                "target_defaulted\tsurface\tdisposition\trationale\n"
                f'"""{retired_source}"""\t{retired_helper}\t"old"\t'
                f'"""{self.LITERAL}"""\t"""docs/x.md"""\tfalse\tReview\t'
                "RETIRE_PROSE\tretired prose\n"
            ),
            ".prflow/logs/residual-required-copy-retirement-manifest.tsv": (
                "source_file\thelper\tassertion_name\tliteral\tresolved_target\t"
                "target_defaulted\tdisposition\trationale\n"
                '"""lib/test/kept.sh"""\tassert_pin_unique\t"kept"\t'
                '"""NOT RETIRED"""\t"""docs/x.md"""\tfalse\tRETAIN_BOUNDARY\tkept\n'
            ),
            ".prflow/logs/red-on-removal-retirement-manifest.tsv": (
                "source_file\thelper\tassertion_name\tliteral\tresolved_target\t"
                "target_defaulted\tdisposition\tcall_sha256\n"
                '"""lib/test/converted.sh"""\tassert_pin_red_on_removal\t"converted"\t'
                '"""NOT RETIRED EITHER"""\t"""docs/x.md"""\tfalse\tconvert_presence\t-\n'
            ),
        }
        for relative, text in manifests.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def _repo(
        self,
        root,
        *,
        base_source="",
        active_adjudication=True,
        retired_source="lib/test/new.sh",
        retired_helper="assert_pin_unique",
    ):
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=root,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=root,
            check=True,
        )
        self._write_retirement_manifests(
            root, retired_source=retired_source, retired_helper=retired_helper
        )
        target = root / "docs/x.md"
        target.parent.mkdir(parents=True)
        target.write_text("```text\nMACHINE SENTINEL\n```\n", encoding="utf-8")
        source = root / "lib/test/old.sh"
        source.parent.mkdir(parents=True)
        source.write_text(base_source, encoding="utf-8")
        table = root / "lib/test/pin-corpus-adjudications.tsv"
        table.write_text(
            "adjudication_key\tbucket_final\trationale\n"
            + (
                f"{self.literal_key}\tboundary\tlegacy rationale\n"
                if active_adjudication
                else ""
            ),
            encoding="utf-8",
        )
        base = self._commit(root, "base")
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/main", base],
            cwd=root,
            check=True,
        )
        subprocess.run(["git", "switch", "-qc", "topic"], cwd=root, check=True)
        return base, table

    def _write_authorization_bundle(
        self,
        root,
        *,
        include_delta=True,
        include_revival=True,
        duplicate_revival=False,
        added_adjudication=False,
        authorization_family="static-helper",
        authorization_helper="assert_pin_unique",
    ):
        bundle = (
            root
            / ".prflow/logs/pin-corpus-adjudication-changes/revive-machine-sentinel"
        )
        bundle.mkdir(parents=True, exist_ok=True)
        if include_delta:
            base_state = (
                "null"
                if added_adjudication
                else '["boundary","legacy rationale"]'
            )
            (bundle / "adjudication-delta.tsv").write_text(
                "adjudication_key\tbase_state\tcurrent_state\n"
                f"{self.literal_key}\t{base_state}\t"
                '["boundary","deliberate machine-boundary revival"]\n',
                encoding="utf-8",
            )
        if include_revival:
            row = (
                f"lib/test/new.sh\t{authorization_family}\t{authorization_helper}\t"
                f"{self.literal_key}\tdocs/x.md\tmachine-sentinel-provenance\t"
                f"{self.RATIONALE}\n"
            )
            (bundle / "retired-pin-revivals.tsv").write_text(
                "source_path\tfamily\thelper\tliteral_key\ttarget_path\t"
                "structural_category\tstructural_rationale\n"
                + row
                + (row if duplicate_revival else ""),
                encoding="utf-8",
            )

    def _scan_sources(self, root, base, analysis):
        diff = subprocess.run(
            ["git", "diff", "--no-color", "--unified=0", base, "HEAD", "--", "lib/test"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        current = {}
        base_sources = {}
        for relative in ("lib/test/old.sh", "lib/test/new.sh"):
            path = root / relative
            if path.exists():
                current[relative] = path.read_text(encoding="utf-8")
            result = subprocess.run(
                ["git", "show", f"{base}:{relative}"],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                base_sources[relative] = result.stdout
        return self.mod.scan_changed_sources(
            current,
            base_sources,
            diff,
            root,
            retired_literal_keys=self.mod.load_retired_wording_literal_keys(
                root, base
            ),
            revival_authorizations=analysis.revival_authorizations,
            adjudication_delta=analysis.delta,
            current_adjudications=analysis.current,
        )

    def _commit_revival(
        self,
        root,
        table,
        *,
        source=None,
        delta=False,
        revival=False,
        duplicate_revival=False,
        added_adjudication=False,
        authorization_family="static-helper",
        authorization_helper="assert_pin_unique",
    ):
        if source is None:
            source = self.SOURCE
        new_source = root / "lib/test/new.sh"
        new_source.write_text(source, encoding="utf-8")
        if delta:
            table.write_text(
                "adjudication_key\tbucket_final\trationale\n"
                f"{self.literal_key}\tboundary\tdeliberate machine-boundary revival\n",
                encoding="utf-8",
            )
        if delta or revival:
            self._write_authorization_bundle(
                root,
                include_delta=delta,
                include_revival=revival,
                duplicate_revival=duplicate_revival,
                added_adjudication=added_adjudication,
                authorization_family=authorization_family,
                authorization_helper=authorization_helper,
            )
        self._commit(root, "revive")

    def _analysis(self, root, base):
        return self.mod.analyze_adjudication_changes(
            root, base, "origin/main"
        )

    def test_retired_literal_requires_both_authorizations_not_just_a_marker(self):
        cases = (
            ("marker only", False, False),
            ("adjudication only", True, False),
        )
        for label, delta, revival in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                base, table = self._repo(root)
                self._commit_revival(
                    root, table, delta=delta, revival=revival
                )
                analysis = self._analysis(root, base)
                findings = self._scan_sources(root, base, analysis)
                self.assertEqual(1, len(findings))
                self.assertIn("retired wording-pin", findings[0])

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, table = self._repo(root, active_adjudication=False)
            self._commit_revival(root, table)
            analysis = self._analysis(root, base)
            findings = self._scan_sources(root, base, analysis)
            self.assertEqual(1, len(findings))
            self.assertIn("same-branch boundary adjudication", findings[0])

    def test_copied_and_moved_retired_literals_are_revival_candidates(self):
        for operation in ("copy", "move"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                base, table = self._repo(root, base_source=self.SOURCE)
                if operation == "move":
                    (root / "lib/test/old.sh").write_text("", encoding="utf-8")
                self._commit_revival(root, table)
                analysis = self._analysis(root, base)
                findings = self._scan_sources(root, base, analysis)
                self.assertEqual(1, len(findings))
                self.assertIn("retired wording-pin", findings[0])

    def test_exact_authorized_genuine_machine_boundary_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, table = self._repo(root)
            self._commit_revival(root, table, delta=True, revival=True)
            analysis = self._analysis(root, base)
            self.assertEqual([], analysis.findings)
            self.assertEqual([], self._scan_sources(root, base, analysis))
            (root / "unrelated.txt").write_text("worktree-only edit\n", encoding="utf-8")
            self.assertEqual([], self._scan_sources(root, base, analysis))

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, table = self._repo(root, active_adjudication=False)
            self._commit_revival(
                root,
                table,
                delta=True,
                revival=True,
                added_adjudication=True,
            )
            analysis = self._analysis(root, base)
            self.assertEqual([], self._scan_sources(root, base, analysis))

    def test_duplicate_or_unconsumed_revival_authorization_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, table = self._repo(root)
            self._commit_revival(
                root,
                table,
                delta=True,
                revival=True,
                duplicate_revival=True,
            )
            with self.assertRaisesRegex(
                self.mod.InfrastructureError, "duplicate revival"
            ):
                self._analysis(root, base)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, table = self._repo(root)
            self._commit_revival(root, table, delta=True, revival=True)
            analysis = self._analysis(root, base)
            with self.assertRaisesRegex(
                self.mod.InfrastructureError, "unconsumed revival"
            ):
                self.mod.scan_changed_sources(
                    {},
                    {},
                    "",
                    root,
                    retired_literal_keys=self.mod.load_retired_wording_literal_keys(
                        root, base
                    ),
                    revival_authorizations=analysis.revival_authorizations,
                    adjudication_delta=analysis.delta,
                    current_adjudications=analysis.current,
                )

    def test_duplicate_normalized_revival_sites_fail_closed_as_ambiguous(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, table = self._repo(root)
            self._commit_revival(
                root,
                table,
                source=self.SOURCE + self.SOURCE,
                delta=True,
                revival=True,
            )
            analysis = self._analysis(root, base)
            with self.assertRaisesRegex(
                self.mod.InfrastructureError, "revival site is ambiguous"
            ):
                self._scan_sources(root, base, analysis)

    def test_historical_retirement_manifests_are_immutable_regular_blobs(self):
        mutations = ("committed edit", "dirty edit", "symlink")
        relative = ".prflow/logs/residual-prose-retirement-manifest.tsv"
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                base, _table = self._repo(root)
                path = root / relative
                if mutation == "committed edit":
                    path.write_text(
                        path.read_text(encoding="utf-8") + "# changed\n",
                        encoding="utf-8",
                    )
                    self._commit(root, mutation)
                elif mutation == "dirty edit":
                    path.write_text(
                        path.read_text(encoding="utf-8") + "# dirty\n",
                        encoding="utf-8",
                    )
                else:
                    external = root / "external.tsv"
                    external.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
                    path.unlink()
                    path.symlink_to(external)
                with self.assertRaises(self.mod.InfrastructureError):
                    self.mod.load_retired_wording_literal_keys(root, base)

    def test_convert_presence_is_not_a_retired_wording_disposition(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, _table = self._repo(root)
            retired = self.mod.load_retired_wording_literal_keys(root, base)
            # convert_presence is not a retired disposition: the site key for the
            # converted row must not be in the retired SITE set (issue #1006).
            converted = self.mod._site_retirement_key(
                "lib/test/converted.sh",
                "assert_pin_red_on_removal",
                "NOT RETIRED EITHER",
                "docs/x.md",
            )
            self.assertNotIn(converted, retired)

    def test_count_helpers_cannot_bypass_retired_literal_policy(self):
        for helper in ("pin_count", "devflow_module_pin_count"):
            source = (
                'F="$LIB/../docs/x.md"\n'
                f"{helper} 'MACHINE SENTINEL' \"$F\"  {self.MARKER}\n"
            )
            with self.subTest(helper=helper), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                # Retire the literal at the count helper's OWN site (issue #1006:
                # helper is part of site identity), so this exercises a count
                # helper re-adding a literal retired AT that count-helper site.
                base, table = self._repo(root, retired_helper=helper)
                self._commit_revival(root, table, source=source)
                analysis = self._analysis(root, base)
                findings = self._scan_sources(root, base, analysis)
                self.assertEqual(1, len(findings))
                self.assertIn("retired wording-pin", findings[0])

    def test_count_helper_exact_authorized_structural_revival_passes(self):
        source = (
            'F="$LIB/../docs/x.md"\n'
            f"pin_count 'MACHINE SENTINEL' \"$F\"  {self.MARKER}\n"
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base, table = self._repo(root, retired_helper="pin_count")
            self._commit_revival(
                root,
                table,
                source=source,
                delta=True,
                revival=True,
                authorization_family="count-helper",
                authorization_helper="pin_count",
            )
            analysis = self._analysis(root, base)
            self.assertEqual([], self._scan_sources(root, base, analysis))

    def test_retirement_is_scoped_to_the_retired_site(self):
        # Issue #1006, driven end-to-end through scan_changed_sources:
        #  - "different-site" (AC2): the literal is retired at lib/test/old.sh, so a
        #    fully-declared boundary pin sharing that literal at lib/test/new.sh is a
        #    DIFFERENT site and is not swept into the retired-revival population --
        #    it routes through the ordinary ladder and passes with NO finding. Under
        #    the old literal-only keying this same input was reported as a
        #    "retired wording-pin revival" with no exit, which is the bug.
        #  - "own-site" (AC3, the negative control that distinguishes a fix from a
        #    hole): retiring the SAME literal at lib/test/new.sh -- the pin's own
        #    site -- still reports it, so the gate did not simply go quiet.
        cases = (
            ("different-site", "lib/test/old.sh", 0),
            ("own-site", "lib/test/new.sh", 1),
        )
        for label, retired_source, expected in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                base, table = self._repo(root, retired_source=retired_source)
                # A genuine, declared machine-boundary pin (docs/x.md is a fenced
                # machine sentinel) with NO revival authorization.
                self._commit_revival(root, table)
                analysis = self._analysis(root, base)
                findings = self._scan_sources(root, base, analysis)
                self.assertEqual(expected, len(findings), findings)
                if expected:
                    self.assertIn("retired wording-pin", findings[0])

    def test_conflicting_retain_and_retire_dispositions_resolve_per_site(self):
        # AC4 (issue #1006): one literal recorded RETIRE_PROSE at one target and
        # RETAIN_BOUNDARY at another (same source_file + helper) resolves to the
        # disposition recorded for EACH site. Literal-keying collapsed both to one
        # key and could not express this; site-keying keys on the resolved target
        # too, so only the retire target's site key is retired.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"], cwd=root, check=True
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"], cwd=root, check=True
            )
            prose = root / ".prflow/logs/residual-prose-retirement-manifest.tsv"
            prose.parent.mkdir(parents=True, exist_ok=True)
            prose.write_text(
                "source_file\thelper\tassertion_name\tliteral\tresolved_target\t"
                "target_defaulted\tsurface\tdisposition\trationale\n"
                '"""lib/test/run.sh"""\tassert_pin_unique\t"retire"\t'
                f'"""{self.LITERAL}"""\t"""docs/retired.md"""\tfalse\tReview\t'
                "RETIRE_PROSE\tprose\n"
                '"""lib/test/run.sh"""\tassert_pin_unique\t"retain"\t'
                f'"""{self.LITERAL}"""\t"""docs/retained.md"""\tfalse\tReview\t'
                "RETAIN_BOUNDARY\tkept\n",
                encoding="utf-8",
            )
            # The other two manifests are read too; write valid header-only files.
            (root / ".prflow/logs/residual-required-copy-retirement-manifest.tsv").write_text(
                "source_file\thelper\tassertion_name\tliteral\tresolved_target\t"
                "target_defaulted\tdisposition\trationale\n",
                encoding="utf-8",
            )
            (root / ".prflow/logs/red-on-removal-retirement-manifest.tsv").write_text(
                "source_file\thelper\tassertion_name\tliteral\tresolved_target\t"
                "target_defaulted\tdisposition\tcall_sha256\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "manifests"], cwd=root, check=True)
            base = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root, check=True, capture_output=True, text=True
            ).stdout.strip()
            retired = self.mod.load_retired_wording_literal_keys(root, base)
            retire_key = self.mod._site_retirement_key(
                "lib/test/run.sh", "assert_pin_unique", self.LITERAL, "docs/retired.md"
            )
            retain_key = self.mod._site_retirement_key(
                "lib/test/run.sh", "assert_pin_unique", self.LITERAL, "docs/retained.md"
            )
            self.assertIn(retire_key, retired)
            self.assertNotIn(retain_key, retired)

    def test_resolved_target_token_matches_the_classifier_three_shapes(self):
        # The site-side token must equal the classifier's resolved_target cell
        # (issue #1006). Three shapes, and the .devflow/ -> .prflow/ normalization
        # that lets a frozen (pre-#1002) manifest target match a current-spelling
        # live site -- a live path exercised by real manifest rows.
        root = "/repo"
        # DERIVE the expected token FROM the classifier rather than hardcoding it,
        # so a change to how the classifier resolves a target turns this test RED
        # instead of leaving the two sides coincidentally in agreement (issue #1057).
        # The classifier derives repo_root as Path(lib).parent, so a lib one level
        # below `root` makes its repo_root equal the site-side `root`.
        lib = "/repo/lib"
        # In-repo file target (absolute) -> repo-relative POSIX path. Expected value
        # is whatever _portable_target produces for the same (target, repo) pair.
        file_target = "/repo/docs/x.md"
        self.assertEqual(
            self.classifier._portable_target(file_target, lib),
            self.mod._resolved_target_token(file_target, None, None, root),
        )
        # Runtime bundle -> the /__pin_corpus_runtime__/<var> placeholder. Expected
        # value is whatever recover_override_names emits for the same var name, so
        # the shared sentinel prefix is asserted from ONE side, the classifier's.
        bundle_var_source = 'assert_pin_unique "s" "L" --var "CI_BUNDLE=$(cat a b)"'
        self.assertEqual(
            self.classifier.recover_override_names(bundle_var_source)["CI_BUNDLE"],
            self.mod._resolved_target_token(None, "CI_BUNDLE", ("a", "b"), root),
        )
        # Defaulted / out-of-repo / unresolvable -> None (fail-toward-not-matched).
        self.assertIsNone(self.mod._resolved_target_token(None, None, None, root))
        self.assertIsNone(
            self.mod._resolved_target_token("/elsewhere/y.md", None, None, root)
        )
        # The state-dir rename is applied symmetrically inside _site_retirement_key,
        # so a manifest .devflow/ target and a live .prflow/ token for one asset
        # produce EQUAL keys; a DEVFLOW-bearing filename is left byte-identical.
        self.assertEqual(
            self.mod._site_retirement_key(
                "lib/test/run.sh", "assert_pin_unique", self.LITERAL,
                ".devflow/prompt-extensions/implement.md",
            ),
            self.mod._site_retirement_key(
                "lib/test/run.sh", "assert_pin_unique", self.LITERAL,
                ".prflow/prompt-extensions/implement.md",
            ),
        )
        self.assertNotEqual(
            self.mod._site_retirement_key(
                "lib/test/run.sh", "h", self.LITERAL, "docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md",
            ),
            self.mod._site_retirement_key(
                "lib/test/run.sh", "h", self.LITERAL, "docs/PRFLOW_SYSTEM_OVERVIEW.md",
            ),
        )

    def test_malformed_retirement_manifest_site_fields_fail_closed(self):
        # The new source_file/resolved_target JSON parse must fail CLOSED
        # (InfrastructureError), matching the pre-existing literal-cell arm and
        # the repo's adversarial-input-shape convention for frozen parsers (#1006).
        base_header = (
            "source_file\thelper\tassertion_name\tliteral\tresolved_target\t"
            "target_defaulted\tsurface\tdisposition\trationale\n"
        )
        cases = {
            "invalid-json-source": (
                "not-json\tassert_pin_unique\t\"a\"\t"
                f'"""{self.LITERAL}"""\t"""docs/x.md"""\tfalse\tReview\t'
                "RETIRE_PROSE\tp\n"
            ),
            "non-string-source": (
                "123\tassert_pin_unique\t\"a\"\t"
                f'"""{self.LITERAL}"""\t"""docs/x.md"""\tfalse\tReview\t'
                "RETIRE_PROSE\tp\n"
            ),
            "non-string-target": (
                '"""lib/test/run.sh"""\tassert_pin_unique\t"a"\t'
                f'"""{self.LITERAL}"""\t123\tfalse\tReview\t'
                "RETIRE_PROSE\tp\n"
            ),
            # Bundle-target rows carry the non-trivial target, so an invalid-JSON
            # resolved_target cell (valid-JSON source) is the arm most likely to
            # meet a malformed cell in practice -- it must fail CLOSED via the
            # json.loads(row[target_index]) decode-error path (issue #1057).
            "invalid-json-target": (
                '"""lib/test/run.sh"""\tassert_pin_unique\t"a"\t'
                f'"""{self.LITERAL}"""\tnot-json\tfalse\tReview\t'
                "RETIRE_PROSE\tp\n"
            ),
        }
        prose_path = ".prflow/logs/residual-prose-retirement-manifest.tsv"
        spec = self.mod._RETIREMENT_MANIFEST_SPECS[prose_path]
        for label, row in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(self.mod.InfrastructureError):
                    self.mod._strict_retirement_manifest_literals(
                        base_header + row, prose_path, spec
                    )


class StaticPinWorktreeCompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_linter()

    def _repo(self, root):
        for relative in (
            *sorted(self.mod.AUDITED_PIN_SOURCES),
            "lib/test/module-harness.sh",
            "lib/test/pin-corpus-lint.py",
            "lib/test/test_pin_corpus_lint.py",
            "lib/test/pin-corpus-adjudications.tsv",
            ".prflow/logs/residual-prose-retirement-manifest.tsv",
            ".prflow/logs/residual-required-copy-retirement-manifest.tsv",
            ".prflow/logs/red-on-removal-retirement-manifest.tsv",
            ".prflow/logs/mutation-pin-corpus-inventory.tsv",
            "scripts/workflow-flight-recorder-registry.json",
        ):
            source = REPO_ROOT / relative
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        fixture = root / "lib/test/static-pin-fixture.sh"
        fixture.write_text("STATIC_PIN_FIXTURE=1\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=root,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=root,
            check=True,
        )
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/main", "HEAD"],
            cwd=root,
            check=True,
        )

    def _public_rc(self, root):
        with (
            mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            rc = self.mod.main(
                ["pin-corpus-lint.py", "mutation-routing-worktree", str(root)]
            )
        # Issue #967: a run that reached the end of the static classifier always
        # writes the completion sentinel to stderr, and its ABSENCE is what tells a
        # caller the classifier was skipped by a precondition raise. Assert it here
        # once — so every caller of this helper covers it — and strip it, keeping the
        # per-test stderr comparands about the finding text they were written for.
        # `rc == 2` is the aborted-run shape, where the sentinel must NOT appear.
        raw_stderr = stderr.getvalue()
        marker_line = self.mod.STATIC_SCAN_COMPLETED_MARKER + "\n"
        if rc == 2:
            self.assertNotIn(self.mod.STATIC_SCAN_COMPLETED_MARKER, raw_stderr)
        else:
            self.assertIn(marker_line, raw_stderr)
        return rc, stdout.getvalue(), raw_stderr.replace(marker_line, "")

    def test_undeclared_static_pin_is_a_public_worktree_policy_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            source = root / "lib/test/run.sh"
            source.write_text(
                source.read_text(encoding="utf-8")
                + "\nassert_pin_unique 'new static pin' 'STATIC_PIN_FIXTURE=1' "
                + "\"$LIB/test/static-pin-fixture.sh\"\n",
                encoding="utf-8",
            )
            rc, stdout, stderr = self._public_rc(root)
        self.assertEqual(3, rc, stderr)
        self.assertIn("MUTATION-ROUTING", stdout)

    def test_typed_static_boundary_passes_public_worktree_policy(self):
        marker = (
            "# structural-pin-ok: machine-sentinel-provenance -- "
            "the fixture token is consumed as an executable sentinel"
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            source = root / "lib/test/run.sh"
            source.write_text(
                source.read_text(encoding="utf-8")
                + "\nassert_pin_unique 'typed static pin' 'STATIC_PIN_FIXTURE=1' "
                + f"\"$LIB/test/static-pin-fixture.sh\"  {marker}\n",
                encoding="utf-8",
            )
            self.assertEqual((0, "", ""), self._public_rc(root))

    def test_unrelated_edit_passes_public_worktree_policy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            source = root / "lib/test/run.sh"
            source.write_text(
                source.read_text(encoding="utf-8") + "\n# unrelated fixture edit\n",
                encoding="utf-8",
            )
            self.assertEqual((0, "", ""), self._public_rc(root))

    def test_step_one_consumer_passes_the_public_worktree_ladder(self):
        # End-to-end proof of the issue-948 step-1 WIRING: the corpus population
        # is an index-reading `git ls-files` over scripts/, lib/ (non-test) and
        # .github/, and its contents come from the worktree. An UNDECLARED pin
        # over a literal a tracked scripts/ program reads is clean; the identical
        # pin is RED when that program's only mention is a comment. Note the pin's
        # own target (lib/test/static-pin-fixture.sh) also carries the literal and
        # cannot satisfy step 1 — the suite is excluded from the corpus.
        for body, expected_rc in (
            ('grep -qF "STATIC_PIN_FIXTURE=1" "$1"\n', 0),
            ("# only a comment mentions STATIC_PIN_FIXTURE=1\n", 3),
        ):
            with self.subTest(rc=expected_rc), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                self._repo(root)
                subprocess.run(
                    ["git", "switch", "-qc", "topic"], cwd=root, check=True
                )
                consumer = root / "scripts/read-fixture-token.sh"
                consumer.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
                subprocess.run(
                    ["git", "add", "scripts/read-fixture-token.sh"],
                    cwd=root,
                    check=True,
                )
                subprocess.run(
                    ["git", "commit", "-qm", "add consumer"], cwd=root, check=True
                )
                source = root / "lib/test/run.sh"
                source.write_text(
                    source.read_text(encoding="utf-8")
                    + "\nassert_pin_unique 'consumed pin' 'STATIC_PIN_FIXTURE=1' "
                    + "\"$LIB/test/static-pin-fixture.sh\"\n",
                    encoding="utf-8",
                )
                rc, stdout, stderr = self._public_rc(root)
                self.assertEqual(expected_rc, rc, stdout + stderr)

    def test_an_untracked_consumer_is_not_in_the_step_one_corpus(self):
        # The issue-#711 invariant at the production boundary: step 1's population
        # is an index-reading `git ls-files` with NO `--others`, so a consumer that
        # exists in the worktree but was never `git add`ed is not in the corpus and
        # its pin routes to step 2 (undeclared here, so a finding). The committed
        # variant of this exact fixture exits 0 in
        # test_step_one_consumer_passes_the_public_worktree_ladder, which is what
        # makes rc 3 here attributable to the missing index entry alone — a
        # regression to `--others` would silently widen the corpus and go green.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            subprocess.run(["git", "switch", "-qc", "topic"], cwd=root, check=True)
            consumer = root / "scripts/read-fixture-token.sh"
            consumer.write_text(
                '#!/usr/bin/env bash\ngrep -qF "STATIC_PIN_FIXTURE=1" "$1"\n',
                encoding="utf-8",
            )
            source = root / "lib/test/run.sh"
            source.write_text(
                source.read_text(encoding="utf-8")
                + "\nassert_pin_unique 'consumed pin' 'STATIC_PIN_FIXTURE=1' "
                + "\"$LIB/test/static-pin-fixture.sh\"\n",
                encoding="utf-8",
            )
            rc, stdout, stderr = self._public_rc(root)
            self.assertEqual(3, rc, stdout + stderr)
            self.assertIn("MUTATION-ROUTING", stdout)

    def test_an_unreadable_consumer_is_skipped_with_a_breadcrumb(self):
        # load_machine_consumer_sources' unreadable / non-UTF-8 branch. This path
        # fails TOWARD step 2 rather than to rc 2, so a regression letting the
        # decode error propagate — or "recovering" by decoding with a lenient
        # codec — would not be caught by any rc-2 assertion. The fixture consumer
        # holds the pinned literal in bytes and is tracked, so:
        #   * skipped correctly  -> not in the corpus -> step 2 -> rc 3 + breadcrumb
        #   * decoded leniently  -> passes step 1     -> rc 0
        #   * error propagates   -> neither
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            subprocess.run(["git", "switch", "-qc", "topic"], cwd=root, check=True)
            consumer = root / "scripts/read-fixture-token.sh"
            consumer.write_bytes(
                b'#!/usr/bin/env bash\ngrep -qF "STATIC_PIN_FIXTURE=1" "$1"\n\xff\xfe\n'
            )
            subprocess.run(
                ["git", "add", "scripts/read-fixture-token.sh"], cwd=root, check=True
            )
            subprocess.run(
                ["git", "commit", "-qm", "add undecodable consumer"],
                cwd=root,
                check=True,
            )
            source = root / "lib/test/run.sh"
            source.write_text(
                source.read_text(encoding="utf-8")
                + "\nassert_pin_unique 'consumed pin' 'STATIC_PIN_FIXTURE=1' "
                + "\"$LIB/test/static-pin-fixture.sh\"\n",
                encoding="utf-8",
            )
            rc, stdout, stderr = self._public_rc(root)
            self.assertEqual(3, rc, stdout + stderr)
            self.assertIn("MUTATION-ROUTING", stdout)
            self.assertIn("MUTATION-ROUTING-CONSUMER-CORPUS-SKIPPED", stderr)
            self.assertIn(
                "scripts/read-fixture-token.sh: UnicodeDecodeError", stderr
            )

    def test_unreadable_ledger_is_infrastructure_not_a_step_two_pass(self):
        # The fail-closed control for step 2 at the production boundary: a ledger
        # the gate cannot read is an infrastructure failure (rc 2), never an
        # empty-but-fine ledger and never a pass. The appended pin is one that
        # exits 0 on a readable ledger, so rc 2 here is attributable.
        marker = (
            "# structural-pin-ok: machine-sentinel-provenance -- "
            "the fixture token is consumed as an executable sentinel"
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            subprocess.run(["git", "switch", "-qc", "topic"], cwd=root, check=True)
            table = root / "lib/test/pin-corpus-adjudications.tsv"
            table.write_bytes(
                b"adjudication_key\tbucket_final\trationale\n\xff\xfe not utf-8\n"
            )
            subprocess.run(["git", "add", "-A"], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "unreadable ledger"], cwd=root, check=True
            )
            source = root / "lib/test/run.sh"
            source.write_text(
                source.read_text(encoding="utf-8")
                + "\nassert_pin_unique 'typed static pin' 'STATIC_PIN_FIXTURE=1' "
                + f"\"$LIB/test/static-pin-fixture.sh\"  {marker}\n",
                encoding="utf-8",
            )
            rc, stdout, stderr = self._public_rc(root)
            self.assertEqual(2, rc, stdout + stderr)

    # ── cross-repository memo-leak probes ──────────────────────────────────
    #
    # The linter and census memos live for the process, and _public_rc runs
    # main() IN-PROCESS, so two fixtures alive at once share them. A memo whose
    # key stopped distinguishing two sources would answer for the wrong
    # repository — but only a fixture whose difference the PRISTINE verdict
    # depends on can observe that. Seeding the mutated repository with any old
    # difference is not enough, which is what an earlier single-probe version of
    # this test got wrong: it appended one assert_pin_unique pin, which moves
    # none of the memoized derivations, and four distinct mis-keying mutations
    # all left it green.
    #
    # The probes are split because the two subgates cannot both be observed on
    # one fixture: a census InfrastructureError makes the whole scan rc 2,
    # masking the static-pin subgate's rc 3, and the census aborts on its
    # definition sweep before its row extraction runs. Each probe therefore
    # isolates one memo family, and each is verified to go RED under a
    # simulated mis-keying of the memo it names.

    # Inert on its own — an undefined name is not a helper — so it can sit in
    # the pristine image safely and only becomes a pin if a leaked definition or
    # helper-spec map arrives from the mutated one.
    _LEAK_PROBE_CALL = (
        "\nleak_probe_pin_unique 'leak probe' 'STATIC_PIN_FIXTURE=1' "
        '"$LIB/test/static-pin-fixture.sh"\n'
    )
    # Moves _function_definitions, and through the *_pin_unique fallback the
    # inferred helper specs.
    _LEAK_PROBE_DEFINITION = (
        "\nleak_probe_pin_unique() {\n"
        '  assert_pin_unique "$1" "$2" "$3"\n'
        "}\n"
    )
    # Moves the census ROW EXTRACTION: assert_pin_red_under is in the census
    # HELPERS tuple (assert_pin_unique is not), and run.sh is audited, so this
    # gives the audited sweep a row where the gate requires none.
    _LEAK_PROBE_AUDITED_CENSUS = (
        "\nassert_pin_red_under 'leak probe red' 'STATIC_PIN_FIXTURE=1' "
        '"$LIB/test/static-pin-fixture.sh" "$LIB/test/static-pin-fixture.sh"\n'
    )
    # Moves the census DEFINITION SWEEP. That sweep reconciles lexical helper
    # tokens against definition counts only for NON-audited sources, so the
    # token has to land in one; the same token in run.sh is skipped by the
    # audited carve-out.
    _LEAK_PROBE_NON_AUDITED_CENSUS = (
        "\n: assert_pin_red_under 'non-audited lexical token'\n"
    )

    def _leak_probe(self, mutate, expected_mutated_rc, expected_marker):
        """Scan a mutated repository, then assert a pristine sibling is clean.

        ``mutate`` receives the mutated root and appends whatever moves the memo
        under test. The mutated scan runs FIRST so every memo is seeded from its
        image; scanning the pristine one first would let a mis-keyed memo be
        seeded correctly and hide the leak.

        ``expected_marker`` is asserted against the mutated scan's own output,
        and it is what makes each probe discriminating: the exit code alone is
        not enough, because a mis-keyed memo can leave the mutated repository
        failing for an unrelated reason at the same rc. The marker names the
        finding the memo under test is responsible for producing.
        """
        with (
            tempfile.TemporaryDirectory() as mutated_dir,
            tempfile.TemporaryDirectory() as pristine_dir,
        ):
            mutated, pristine = Path(mutated_dir), Path(pristine_dir)
            self._repo(mutated)
            self._repo(pristine)
            for root in (mutated, pristine):
                run_sh = root / "lib/test/run.sh"
                run_sh.write_text(
                    run_sh.read_text(encoding="utf-8") + self._LEAK_PROBE_CALL,
                    encoding="utf-8",
                )
            mutate(mutated)
            mutated_rc, mutated_stdout, mutated_stderr = self._public_rc(mutated)
            self.assertEqual(expected_mutated_rc, mutated_rc, mutated_stderr)
            self.assertIn(expected_marker, mutated_stdout + mutated_stderr)
            self.assertEqual((0, "", ""), self._public_rc(pristine))

    def test_leaked_source_parse_would_misclassify_a_sibling_repository(self):
        def mutate(root):
            run_sh = root / "lib/test/run.sh"
            run_sh.write_text(
                run_sh.read_text(encoding="utf-8") + self._LEAK_PROBE_DEFINITION,
                encoding="utf-8",
            )

        # The marker is the WRAPPER's name: reaching it requires the definition
        # scan and the helper-spec inference to have run on this image. Under a
        # mis-keyed memo the scan instead reports the plain assert_pin_unique
        # inside the wrapper body — same rc 3, different finding — which is
        # exactly why the rc is not the discriminator here.
        self._leak_probe(mutate, 3, "leak_probe_pin_unique")

    def test_leaked_census_row_extraction_would_misclassify_a_sibling(self):
        def mutate(root):
            run_sh = root / "lib/test/run.sh"
            run_sh.write_text(
                run_sh.read_text(encoding="utf-8")
                + self._LEAK_PROBE_AUDITED_CENSUS,
                encoding="utf-8",
            )

        # rc 3, not 2: a mutation call outside the retained-boundary set is a
        # policy finding, so the census reports rather than aborting — which is
        # what leaves its row extraction reached and therefore observable here.
        self._leak_probe(mutate, 3, "adjudicated retained boundary")

    def test_leaked_census_definition_sweep_would_misclassify_a_sibling(self):
        def mutate(root):
            fixture = root / "lib/test/static-pin-fixture.sh"
            fixture.write_text(
                fixture.read_text(encoding="utf-8")
                + self._LEAK_PROBE_NON_AUDITED_CENSUS,
                encoding="utf-8",
            )

        self._leak_probe(mutate, 2, "unclassified supported helper token")

    def test_repository_mutations_do_not_leak_between_fixtures(self):
        # The filesystem half of the isolation claim: a destructively mutated
        # fixture leaves its sibling's bytes, untracked files, and branch alone.
        # The memo half is covered by the three probes above.
        with (
            tempfile.TemporaryDirectory() as mutated_dir,
            tempfile.TemporaryDirectory() as pristine_dir,
        ):
            mutated, pristine = Path(mutated_dir), Path(pristine_dir)
            self._repo(mutated)
            self._repo(pristine)
            pristine_run_sh = (pristine / "lib/test/run.sh").read_bytes()
            # Captured rather than assumed: _repo does not set init.defaultBranch,
            # so the fixture's starting branch is whatever the host configured.
            pristine_branch = self._branch(pristine)

            source = mutated / "lib/test/run.sh"
            source.write_text(
                source.read_text(encoding="utf-8") + self._LEAK_PROBE_DEFINITION,
                encoding="utf-8",
            )
            (mutated / "lib/test/leaked-fixture.sh").write_text(
                "LEAKED=1\n", encoding="utf-8"
            )
            subprocess.run(
                ["git", "switch", "-qc", "topic"], cwd=mutated, check=True
            )
            self.assertEqual(
                pristine_run_sh, (pristine / "lib/test/run.sh").read_bytes()
            )
            self.assertFalse((pristine / "lib/test/leaked-fixture.sh").exists())
            self.assertEqual(pristine_branch, self._branch(pristine))
            self.assertEqual("topic", self._branch(mutated))

    def _branch(self, root):
        # stderr is deliberately NOT captured: check=True raises
        # CalledProcessError, whose message carries only the exit status, so a
        # captured stderr would be swallowed on exactly the failures worth
        # diagnosing (git absent, a safe.directory refusal, a git too old for
        # the sibling `git switch`). Leaving it on the console matches every
        # other subprocess call in this fixture class.
        return subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        ).stdout.strip()

    def _audited_source_added_after_base(self, root, relative):
        """Rewind ``origin/main`` past ``relative`` so HEAD adds it, as a branch would."""
        (root / relative).unlink()
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "base without module"], cwd=root, check=True)
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/main", "HEAD"],
            cwd=root,
            check=True,
        )
        # Commit the registration on a BRANCH, not on main: the gate requires local
        # main to be an ancestor of origin/main, which is the real branch shape.
        subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=root, check=True)
        shutil.copy2(REPO_ROOT / relative, root / relative)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "register module"], cwd=root, check=True)

    def test_audited_source_registered_after_the_merge_base_passes(self):
        # A branch that registers a new focused module adds the module file and its
        # AUDITED_PIN_SOURCES entry in the same change, so the path is absent from the
        # base tree by construction. Requiring it there failed the gate closed on the
        # one shape the census exists to admit.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            self._audited_source_added_after_base(
                root, "lib/test/modules/experiment-records.sh"
            )
            self.assertEqual((0, "", ""), self._public_rc(root))

    def test_audited_source_absent_from_head_is_an_infrastructure_failure(self):
        # The HEAD arm still fails closed: an audited path the committed tree does not
        # carry leaves its pins unscanned, which is what the census exists to prevent.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            subprocess.run(["git", "checkout", "-q", "-b", "feature"], cwd=root, check=True)
            (root / "lib/test/modules/experiment-records.sh").unlink()
            subprocess.run(["git", "add", "-A"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "drop module"], cwd=root, check=True)
            rc, stdout, stderr = self._public_rc(root)
        self.assertEqual(2, rc, stderr)
        self.assertIn("lib/test/modules/experiment-records.sh", stdout + stderr)

    def test_retired_helper_remains_a_public_worktree_policy_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            source = root / "lib/test/run.sh"
            source.write_text(
                source.read_text(encoding="utf-8")
                + "\nassert_pin_red_under new retired helper call\n",
                encoding="utf-8",
            )
            rc, stdout, stderr = self._public_rc(root)
        self.assertEqual(3, rc, stderr)
        self.assertIn("MUTATION-ROUTING", stdout)

    def test_public_worktree_scans_tracked_and_untracked_python_tests(self):
        source = (
            "\nclass StaticPinFixtureTest(unittest.TestCase):\n"
            "    def test_wording(self):\n"
            "        self.assertIn(\n"
            "            'STATIC_PIN_FIXTURE=1',\n"
            "            Path('lib/test/static-pin-fixture.sh').read_text(),\n"
            "        )\n"
        )
        for state in ("tracked", "untracked"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                self._repo(root)
                if state == "tracked":
                    path = root / "lib/test/test_pin_corpus_lint.py"
                    path.write_text(
                        path.read_text(encoding="utf-8") + source,
                        encoding="utf-8",
                    )
                else:
                    path = root / "lib/test/test_static_pin_fixture.py"
                    path.write_text(
                        "from pathlib import Path\n"
                        "import unittest\n"
                        + source,
                        encoding="utf-8",
                    )
                rc, stdout, stderr = self._public_rc(root)
                self.assertEqual(3, rc, stderr)
                self.assertIn("MUTATION-ROUTING", stdout)

    def test_committed_head_pin_cannot_be_hidden_by_worktree_restore(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            subprocess.run(["git", "switch", "-qc", "topic"], cwd=root, check=True)
            source = root / "lib/test/run.sh"
            source.write_text(
                source.read_text(encoding="utf-8")
                + "\nassert_pin_unique 'hidden committed pin' "
                + "'STATIC_PIN_FIXTURE=1' \"$LIB/test/static-pin-fixture.sh\"\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", str(source)], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "commit undeclared pin"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "restore",
                    "--worktree",
                    "--source=origin/main",
                    "lib/test/run.sh",
                ],
                cwd=root,
                check=True,
            )
            rc, stdout, stderr = self._public_rc(root)
        self.assertEqual(3, rc, stderr)
        self.assertIn("STATIC_PIN_FIXTURE=1", stdout)
        self.assertIn("missing structural declaration", stdout)

    def test_staged_pin_cannot_be_hidden_by_worktree_restore(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            source = root / "lib/test/run.sh"
            source.write_text(
                source.read_text(encoding="utf-8")
                + "\nassert_pin_unique 'hidden staged pin' "
                + "'STATIC_PIN_FIXTURE=1' \"$LIB/test/static-pin-fixture.sh\"\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", str(source)], cwd=root, check=True)
            subprocess.run(
                [
                    "git",
                    "restore",
                    "--worktree",
                    "--source=HEAD",
                    "lib/test/run.sh",
                ],
                cwd=root,
                check=True,
            )
            rc, stdout, stderr = self._public_rc(root)
        self.assertEqual(2, rc)
        self.assertEqual("", stdout)
        self.assertIn("index differs from HEAD", stderr)

    def test_scanned_source_symlinks_fail_closed(self):
        cases = (
            "audited worktree",
            "audited HEAD",
            "untracked Python",
            "symlinked parent",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as td:
                root = Path(td) / "repo"
                root.mkdir()
                self._repo(root)
                external = Path(td) / "external.txt"
                external.write_text("# harmless external target\n", encoding="utf-8")
                if case == "symlinked parent":
                    test_dir = root / "lib/test"
                    real_dir = root / "lib/test-real"
                    test_dir.rename(real_dir)
                    test_dir.symlink_to(real_dir.name)
                    with self.assertRaisesRegex(
                        self.mod.InfrastructureError,
                        "symlinked worktree parent",
                    ):
                        self.mod._read_worktree_source(
                            root,
                            "lib/test/run.sh",
                            "100755",
                        )
                elif case.startswith("audited"):
                    source = root / "lib/test/run.sh"
                    source.unlink()
                    source.symlink_to(external)
                    if case.endswith("HEAD"):
                        subprocess.run(
                            ["git", "switch", "-qc", "topic"],
                            cwd=root,
                            check=True,
                        )
                        subprocess.run(["git", "add", str(source)], cwd=root, check=True)
                        subprocess.run(
                            ["git", "commit", "-qm", "symlink audited source"],
                            cwd=root,
                            check=True,
                        )
                else:
                    source = root / "lib/test/test_symlink_leaf.py"
                    source.symlink_to(external)
                rc, stdout, stderr = self._public_rc(root)
                self.assertEqual(2, rc)
                self.assertEqual("", stdout)
                self.assertIn("MUTATION-ROUTING-INFRASTRUCTURE", stderr)

    def test_multiple_direct_helpers_on_one_logical_line_fail_closed(self):
        marker = (
            "# structural-pin-ok: machine-sentinel-provenance -- "
            "the fixture token is an executable sentinel"
        )
        joiners = (" ; ", " && ", " | ", " |& ", " & ", ";", "|", "|&", "&")
        for joiner in joiners:
            with self.subTest(joiner=joiner), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                self._repo(root)
                source = root / "lib/test/run.sh"
                source.write_text(
                    source.read_text(encoding="utf-8")
                    + "\nassert_pin_unique 'typed first' 'STATIC_PIN_FIXTURE=1' "
                    + f"\"$LIB/test/static-pin-fixture.sh\"{joiner}"
                    + "assert_pin_unique 'undeclared second' 'STATIC_PIN_FIXTURE=1' "
                    + f"\"$LIB/test/static-pin-fixture.sh\" {marker}\n",
                    encoding="utf-8",
                )
                rc, stdout, stderr = self._public_rc(root)
                self.assertEqual(2, rc)
                self.assertEqual("", stdout)
                self.assertIn("multiple supported helper calls", stderr)

    def test_pipe_background_and_subshell_rhs_helpers_are_scanned(self):
        leaders = (": | ", ":|", ": |& ", ":|&", ": & ", ":&", "( ", "(")
        for leader in leaders:
            with self.subTest(leader=leader), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                self._repo(root)
                source = root / "lib/test/run.sh"
                suffix = " )" if leader.startswith("(") else ""
                source.write_text(
                    source.read_text(encoding="utf-8")
                    + f"\n{leader}assert_pin_unique 'operator-prefixed pin' "
                    + "'STATIC_PIN_FIXTURE=1' "
                    + f"\"$LIB/test/static-pin-fixture.sh\"{suffix}\n",
                    encoding="utf-8",
                )
                rc, stdout, stderr = self._public_rc(root)
                self.assertEqual(3, rc, stderr)
                self.assertIn("STATIC_PIN_FIXTURE=1", stdout)

    def test_quoted_and_escaped_operator_suffixes_are_not_command_boundaries(self):
        values = (
            "'|'",
            "'|&'",
            "'&'",
            "';'",
            "'not|'",
            "'not|&'",
            "'not&'",
            "'not;'",
            r"\|",
            r"\&",
            r"\;",
        )
        for value in values:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                self._repo(root)
                source = root / "lib/test/run.sh"
                source.write_text(
                    source.read_text(encoding="utf-8")
                    + f"\nprintf '%s\\n' {value} assert_pin_unique "
                    + "'argument only' 'STATIC_PIN_FIXTURE=1' "
                    + "\"$LIB/test/static-pin-fixture.sh\"\n",
                    encoding="utf-8",
                )
                rc, stdout, stderr = self._public_rc(root)
                self.assertEqual(0, rc, stderr)
                self.assertEqual("", stdout)

    def test_command_prefixed_direct_helper_is_not_skipped(self):
        for prefix in ("command", "command --", "command -p"):
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                self._repo(root)
                source = root / "lib/test/run.sh"
                source.write_text(
                    source.read_text(encoding="utf-8")
                    + f"\n{prefix} assert_pin_unique 'command-prefixed pin' "
                    + "'STATIC_PIN_FIXTURE=1' \"$LIB/test/static-pin-fixture.sh\"\n",
                    encoding="utf-8",
                )
                rc, stdout, stderr = self._public_rc(root)
                self.assertEqual(3, rc, stderr)
                self.assertIn("STATIC_PIN_FIXTURE=1", stdout)

        for lookup in ("command -v", "command -V", "echo command"):
            with self.subTest(lookup=lookup), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                self._repo(root)
                source = root / "lib/test/run.sh"
                source.write_text(
                    source.read_text(encoding="utf-8")
                    + f"\n{lookup} assert_pin_unique\n",
                    encoding="utf-8",
                )
                self.assertEqual((0, "", ""), self._public_rc(root))

    def test_time_prefixed_direct_helper_is_not_skipped(self):
        for prefix in (
            "time",
            "time -p",
            "PIN_LABEL=fixture time",
            "PIN_LABEL=fixture time -p",
            "time --",
            "time -p --",
            "X=1 time --",
            "time command",
            "time command --",
            "time -p command -p",
            "X=1 time command",
        ):
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                self._repo(root)
                source = root / "lib/test/run.sh"
                source.write_text(
                    source.read_text(encoding="utf-8")
                    + f"\n{prefix} assert_pin_unique 'time-prefixed pin' "
                    + "'STATIC_PIN_FIXTURE=1' \"$LIB/test/static-pin-fixture.sh\"\n",
                    encoding="utf-8",
                )
                rc, stdout, stderr = self._public_rc(root)
                self.assertEqual(3, rc, stderr)
                self.assertIn("STATIC_PIN_FIXTURE=1", stdout)

        for mention in (
            "echo time assert_pin_unique",
            "printf '%s' time assert_pin_unique",
            "time -v assert_pin_unique",
            "time command -v assert_pin_unique",
            "time command -V assert_pin_unique",
        ):
            with self.subTest(mention=mention), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                self._repo(root)
                source = root / "lib/test/run.sh"
                source.write_text(
                    source.read_text(encoding="utf-8") + f"\n{mention}\n",
                    encoding="utf-8",
                )
                self.assertEqual((0, "", ""), self._public_rc(root))

    def test_committed_prose_target_cannot_be_laundered_by_dirty_fenced_target(self):
        marker = (
            "# structural-pin-ok: machine-sentinel-provenance -- "
            "the fixture token is claimed as an executable sentinel"
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            subprocess.run(["git", "switch", "-qc", "topic"], cwd=root, check=True)
            target = root / "docs/static-pin-target.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("## STATIC PIN PROSE\n", encoding="utf-8")
            source = root / "lib/test/run.sh"
            source.write_text(
                source.read_text(encoding="utf-8")
                + "\nassert_pin_unique 'committed prose target' 'STATIC PIN PROSE' "
                + f"\"$LIB/../docs/static-pin-target.md\"  {marker}\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "commit invalid prose pin"],
                cwd=root,
                check=True,
            )

            clean_rc, clean_stdout, clean_stderr = self._public_rc(root)
            self.assertEqual(3, clean_rc, clean_stderr)
            self.assertIn("resolves into prose", clean_stdout)

            target.write_text(
                "```text\nSTATIC PIN PROSE\n```\n",
                encoding="utf-8",
            )
            dirty_rc, dirty_stdout, dirty_stderr = self._public_rc(root)
            self.assertEqual(3, dirty_rc, dirty_stderr)
            self.assertIn("resolves into prose", dirty_stdout)

    def test_authorized_retired_revival_cannot_launder_committed_prose_target(self):
        # Site-keying (issue #1006): the literal must be revived at ITS OWN retired
        # site for the pre-948 contract to apply, so this rewrites the fixture to a
        # literal the frozen prose manifest retires at (lib/test/run.sh,
        # assert_pin_unique, agents/checklist-verifier.md). The literal is not a
        # live boundary (absent from the adjudication table), so appending its
        # deliberate-boundary row below does not duplicate an existing key. The
        # target is committed prose, so a full authorization still cannot launder
        # it into a machine sentinel and the revival is still reported.
        literal = "#504 displaced-path routing."
        literal_key = (
            "literal:" + hashlib.sha256(literal.encode("utf-8")).hexdigest()
        )
        target_rel = "agents/checklist-verifier.md"
        rationale = "the token is claimed as an executable machine sentinel"
        marker = (
            "# structural-pin-ok: machine-sentinel-provenance -- " + rationale
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            self.assertIn(
                self.mod._site_retirement_key(
                    "lib/test/run.sh", "assert_pin_unique", literal, target_rel
                ),
                self.mod.load_retired_wording_literal_keys(root, "HEAD"),
            )
            subprocess.run(["git", "switch", "-qc", "topic"], cwd=root, check=True)
            target = root / target_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"## {literal}\n", encoding="utf-8")
            source = root / "lib/test/run.sh"
            source.write_text(
                source.read_text(encoding="utf-8")
                + f"\nassert_pin_unique 'retired prose target' '{literal}' "
                + f"\"$LIB/../{target_rel}\"  {marker}\n",
                encoding="utf-8",
            )
            table = root / "lib/test/pin-corpus-adjudications.tsv"
            table.write_text(
                table.read_text(encoding="utf-8")
                + f"{literal_key}\tboundary\tdeliberate machine-boundary revival\n",
                encoding="utf-8",
            )
            bundle = (
                root
                / ".prflow/logs/pin-corpus-adjudication-changes"
                / "retired-prose-snapshot-test"
            )
            bundle.mkdir(parents=True)
            (bundle / "adjudication-delta.tsv").write_text(
                "adjudication_key\tbase_state\tcurrent_state\n"
                f"{literal_key}\tnull\t"
                '["boundary","deliberate machine-boundary revival"]\n',
                encoding="utf-8",
            )
            (bundle / "retired-pin-revivals.tsv").write_text(
                "source_path\tfamily\thelper\tliteral_key\ttarget_path\t"
                "structural_category\tstructural_rationale\n"
                f"lib/test/run.sh\tstatic-helper\tassert_pin_unique\t{literal_key}\t"
                f"{target_rel}\tmachine-sentinel-provenance\t"
                f"{rationale}\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "authorize invalid retired revival"],
                cwd=root,
                check=True,
            )
            target.write_text(f"```text\n{literal}\n```\n", encoding="utf-8")

            rc, stdout, stderr = self._public_rc(root)
            self.assertEqual(3, rc, stderr)
            self.assertIn("resolves into prose", stdout)

    def test_worktree_target_snapshot_detects_byte_mode_and_recreate_races(self):
        # The `different_content_recreate` mutation recreates with DIFFERENT content
        # on purpose. An unlink+recreate with byte-identical content that reuses the
        # inode within one timestamp tick is indistinguishable from no change (and
        # harmless — the analyzed bytes are unchanged), so `_worktree_path_identity`
        # does not guard it by design; see its docstring. Asserting it here would be
        # a property the host's filesystem/clock does not guarantee (green on a slow
        # host, red on a fast one). A different-content recreate is a real path race
        # that the payload compare catches deterministically on every host, with no
        # sleep-to-cross-a-tick timing dependence.
        #
        # Coverage residual, decided rather than overlooked: because that recreate is
        # detected through the payload/`st_size` limb, no subtest here isolates
        # `st_ino`, `st_dev`, or `st_mtime_ns` as the sole differing field of the
        # identity tuple. Driving one of them in isolation deterministically would
        # require sleeping to cross a timer tick — exactly the host-timing dependence
        # issue #1100 exists to remove — so it is out of bounds. The identity
        # comparison itself stays covered: the `mode` subtest leaves the payload
        # byte-identical and differs only in metadata (`st_mode`, plus the
        # `st_ctime_ns` that chmod bumps with it), so deleting the identity compare
        # from `_worktree_target_snapshot`/`verify()` turns that subtest RED.
        for mutation in ("bytes", "mode", "different_content_recreate"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                target = root / "docs/target.md"
                target.parent.mkdir(parents=True)
                target.write_text("TOKEN\n", encoding="utf-8")
                loader, verify = self.mod._worktree_target_loader(root)
                self.assertEqual(("TOKEN\n", None), loader(target))
                if mutation == "bytes":
                    target.write_text("CHANGED\n", encoding="utf-8")
                elif mutation == "mode":
                    target.chmod(0o755)
                else:
                    target.unlink()
                    target.write_text("REPLACED\n", encoding="utf-8")
                with self.assertRaisesRegex(
                    self.mod.InfrastructureError,
                    "changed during worktree analysis",
                ):
                    verify()

    def test_composition_preserves_subgate_order_and_infrastructure_precedence(self):
        retired = ["MUTATION-ROUTING\tretired"]
        static = ["MUTATION-ROUTING\tstatic"]
        with (
            mock.patch.object(
                self.mod,
                "scan_retired_mutation_population",
                return_value=retired,
            ),
            mock.patch.object(
                self.mod,
                "scan_static_pin_changes",
                return_value=static,
            ),
        ):
            self.assertEqual(retired + static, self.mod.scan_worktree("/repo"))

        with (
            mock.patch.object(
                self.mod,
                "scan_retired_mutation_population",
                return_value=retired,
            ),
            mock.patch.object(
                self.mod,
                "scan_static_pin_changes",
                side_effect=self.mod.InfrastructureError("static unavailable"),
            ),
        ):
            with self.assertRaisesRegex(
                self.mod.InfrastructureError,
                "static unavailable",
            ):
                self.mod.scan_worktree("/repo")

        # The retired subgate runs first, so its infrastructure failure preempts
        # the static subgate rather than being masked by it.
        with (
            mock.patch.object(
                self.mod,
                "scan_retired_mutation_population",
                side_effect=self.mod.InfrastructureError("retired unavailable"),
            ),
            mock.patch.object(
                self.mod,
                "scan_static_pin_changes",
                side_effect=self.mod.InfrastructureError("static unavailable"),
            ) as static,
        ):
            with self.assertRaisesRegex(
                self.mod.InfrastructureError,
                "retired unavailable",
            ):
                self.mod.scan_worktree("/repo")
            static.assert_not_called()

    def test_public_retired_subgate_infrastructure_failure_exits_two(self):
        with (
            mock.patch.object(
                self.mod,
                "scan_retired_mutation_population",
                side_effect=self.mod.InfrastructureError("retired census unavailable"),
            ),
            mock.patch("sys.stdout", new_callable=io.StringIO) as stdout,
            mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            rc = self.mod.main(
                ["pin-corpus-lint.py", "mutation-routing-worktree", "/repo"]
            )
        self.assertEqual(2, rc)
        self.assertEqual("", stdout.getvalue())
        self.assertIn("MUTATION-ROUTING-INFRASTRUCTURE", stderr.getvalue())
        self.assertIn("retired census unavailable", stderr.getvalue())

    def test_pin_relocated_into_a_newly_committed_source_is_not_double_counted(self):
        """A pin source committed after the merge base appears in the real
        ``git diff`` output; it must be classified exactly once under the strict
        current-site policy rather than duplicated by a synthetic hunk."""
        pin = (
            "\nclass RelocatedFixtureTest(unittest.TestCase):\n"
            "    def test_wording(self):\n"
            "        self.assertIn(\n"
            "            'STATIC_PIN_FIXTURE=1',\n"
            "            Path('lib/test/static-pin-fixture.sh').read_text(),\n"
            "        )\n"
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            origin = root / "lib/test/test_pin_corpus_lint.py"
            origin.write_text(
                origin.read_text(encoding="utf-8") + pin, encoding="utf-8"
            )
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "add pin"], cwd=root, check=True)
            subprocess.run(
                ["git", "update-ref", "refs/remotes/origin/main", "HEAD"],
                cwd=root,
                check=True,
            )
            # Commit the relocation on a topic branch so local main stays at the
            # merge base and the ancestry precheck holds.
            subprocess.run(["git", "checkout", "-qb", "topic"], cwd=root, check=True)
            # Relocate the pin into a Python leaf committed in the same change:
            # tracked at HEAD, absent at the merge base, so it is already carried
            # by the real `git diff` output.
            origin.write_text(
                origin.read_text(encoding="utf-8").replace(pin, ""), encoding="utf-8"
            )
            (root / "lib/test/test_relocated_fixture.py").write_text(
                "from pathlib import Path\nimport unittest\n" + pin,
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "."], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "relocate"], cwd=root, check=True)
            rc, stdout, stderr = self._public_rc(root)
        self.assertEqual(3, rc, f"stdout={stdout!r} stderr={stderr!r}")
        self.assertEqual(1, stdout.count("MUTATION-ROUTING"))


class RetiredMutationHelperBanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_linter()

    def _repo(self, root):
        for relative in (
            *sorted(self.mod.AUDITED_PIN_SOURCES),
            "lib/test/module-harness.sh",
            "lib/test/pin-corpus-lint.py",
            ".prflow/logs/mutation-pin-corpus-inventory.tsv",
            "scripts/workflow-flight-recorder-registry.json",
        ):
            source = REPO_ROOT / relative
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)

    def test_zero_population_and_unrelated_edits_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            self.assertEqual(
                [],
                self.mod.scan_retired_mutation_population(root),
            )
            outside = root / "docs/unfrozen.md"
            outside.parent.mkdir(parents=True)
            outside.write_text("ordinary unrelated addition\n", encoding="utf-8")
            audited = root / min(self.mod.AUDITED_PIN_SOURCES)
            audited.write_text(
                "# ordinary non-helper edit\n"
                + audited.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            self.assertEqual(
                [],
                self.mod.scan_retired_mutation_population(root),
            )

    def test_every_retired_helper_invocation_is_a_policy_finding(self):
        for helper in (
            "assert_pin_red_under",
            "devflow_module_pin_red_under",
            "assert_count_red_under",
            "_ra_conflict_red_under",
        ):
            with self.subTest(helper=helper), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                self._repo(root)
                source = root / min(self.mod.AUDITED_PIN_SOURCES)
                source.write_text(
                    source.read_text(encoding="utf-8")
                    + f"\n{helper} new retired helper call\n",
                    encoding="utf-8",
                )
                findings = self.mod.scan_retired_mutation_population(root)
                self.assertTrue(findings)
                self.assertTrue(
                    all(finding.startswith("MUTATION-ROUTING\t") for finding in findings)
                )

    def test_retired_helper_definition_or_wrapper_fails_closed(self):
        cases = (
            (
                "definition",
                "lib/test/module-harness.sh",
                "\nassert_pin_red_under() { :; }\n",
            ),
            (
                "wrapper",
                min(self.mod.AUDITED_PIN_SOURCES),
                '\nwrap() { assert_pin_red_under "$@"; }\n',
            ),
        )
        for label, relative, addition in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                self._repo(root)
                path = root / relative
                path.write_text(
                    path.read_text(encoding="utf-8") + addition,
                    encoding="utf-8",
                )
                with self.assertRaises(self.mod.InfrastructureError):
                    self.mod.scan_retired_mutation_population(root)

    def test_inventory_missing_malformed_or_nonempty_is_infrastructure(self):
        cases = ("missing", "malformed", "nonempty")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                self._repo(root)
                inventory = (
                    root / ".prflow/logs/mutation-pin-corpus-inventory.tsv"
                )
                if case == "missing":
                    inventory.unlink()
                elif case == "malformed":
                    inventory.write_text(
                        "not\ta\tvalid\tinventory\n",
                        encoding="utf-8",
                    )
                else:
                    inventory.write_text(
                        inventory.read_text(encoding="utf-8")
                        + "lib/test/run.sh\tassert_pin_red_under\t"
                        '"assert_pin_red_under n l m f"\t1\t1\t'
                        + "a" * 64
                        + "\tretain_executable_boundary\tstale row\n",
                        encoding="utf-8",
                    )
                with self.assertRaises(self.mod.InfrastructureError):
                    self.mod.scan_retired_mutation_population(root)

    def test_required_path_runs_only_git_enumeration_not_mutation_semantics(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._repo(root)
            real_run = subprocess.run

            def git_only(args, **kwargs):
                self.assertEqual(args[:2], ["git", "ls-files"])
                return real_run(args, **kwargs)

            with mock.patch.object(
                subprocess,
                "run",
                side_effect=git_only,
            ):
                self.assertEqual(
                    [],
                    self.mod.scan_retired_mutation_population(root),
                )


class PinRoutingLadder948Tests(unittest.TestCase):
    """The issue-948 three-step routing ladder: every arm, and the arm ORDER.

    A reordered ladder changes verdicts silently, so each test names the arm it
    exercises and asserts the DECIDING message rather than only the count. The
    fixture literal is a whitespace-bearing visible Markdown sentence, i.e. one
    the lint classifies as prose — before #948 that classification ran first and
    returned unconditionally, so no declaration and no ledger row could be
    reached for it. Every step-2 test below is therefore a case that could not
    pass at all before this change.
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = load_linter()

    MARKER = (
        "# structural-pin-ok: cross-file-phase-contract -- "
        "the sentence spells the command shape a cloud grant must match"
    )
    INVALID_MARKER = "# structural-pin-ok: contract-presence over skill prose -- why"
    LITERAL = "re-opens the diff at every --verdict-threshold value"
    TARGET = "skills/review/SKILL.md"
    RATIONALE = "maintainer adjudication: declared security or interface boundary"

    def _fixture(self, td, *, marker="", literal=None, target_text=None):
        """Write the prose target and return (repo_root, pin source text)."""
        literal = literal or self.LITERAL
        root = Path(td)
        target = root / self.TARGET
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            target_text
            or f"# Review\n\nThe fix loop {literal} so the pass is observable.\n",
            encoding="utf-8",
        )
        source = (
            f'F="$LIB/../{self.TARGET}"\n'
            f"assert_pin_unique \"threshold\" '{literal}' \"$F\""
            + (f"  {marker}" if marker else "")
        )
        return root, source

    def _scan(self, root, source, **kwargs):
        return self.mod.scan_changed_sources(
            {"lib/test/a.sh": source},
            {"lib/test/a.sh": ""},
            one_file_diff("lib/test/a.sh", "", source),
            repo_root=root,
            **kwargs,
        )

    def _key(self, literal=None):
        return self.mod._literal_adjudication_key(literal or self.LITERAL)

    def _ledger(self, bucket="boundary", literal=None):
        return {self._key(literal): (bucket, self.RATIONALE)}

    # ── Step 1: a program demonstrably reads it ────────────────────────────
    def test_step_one_passes_with_no_tag_and_no_ledger_row(self):
        with tempfile.TemporaryDirectory() as td:
            root, source = self._fixture(td)
            consumer = {
                "scripts/derive-verdict.sh": (
                    "#!/usr/bin/env bash\n"
                    f"grep -qF '{self.LITERAL}' \"$1\" || exit 1\n"
                )
            }
            self.assertEqual([], self._scan(root, source, consumer_sources=consumer))
            # RED-first control: the identical site with no consumer corpus is a
            # finding, so the pass above is attributable to step 1 alone.
            unrouted = self._scan(root, source)
            self.assertEqual(1, len(unrouted))
            self.assertIn("resolves into prose", unrouted[0])

    def test_step_one_accepts_a_distinctive_token_not_only_the_whole_literal(self):
        with tempfile.TemporaryDirectory() as td:
            root, source = self._fixture(td)
            consumer = {
                "scripts/derive-verdict.sh": 'THRESHOLD_FLAG="--verdict-threshold"\n'
            }
            self.assertEqual([], self._scan(root, source, consumer_sources=consumer))

    def test_step_one_token_match_is_boundary_anchored(self):
        # Makes the `(?<![\w-])…(?![\w-])` anchoring a GUARANTEE rather than an
        # incidental property: step 1 widens deliberately (a single distinctive
        # token anywhere in a consumer's operative text passes), so the one thing
        # bounding its false positives is that the token must stand alone. A
        # consumer whose only mention of the token is buried inside a larger
        # identifier is not a program reading the pinned literal. Every case
        # below embeds the fixture literal's sole distinctive token,
        # `--verdict-threshold`, with a `[\w-]` neighbour on one side or both.
        for body in (
            'FLAG="--verdict-thresholds"\n',  # trailing word char
            'FLAG="--verdict-threshold-value"\n',  # trailing hyphen
            'FLAG="x--verdict-threshold"\n',  # leading word char
            'FLAG="legacy---verdict-threshold"\n',  # leading hyphen
            'FLAG="pre--verdict-thresholdpost"\n',  # both sides
        ):
            with self.subTest(body=body), tempfile.TemporaryDirectory() as td:
                root, source = self._fixture(td)
                findings = self._scan(
                    root,
                    source,
                    consumer_sources={"scripts/derive-verdict.sh": body},
                )
                self.assertEqual(1, len(findings), body)
                self.assertIn("no program consumer reads it", findings[0])
        # Positive control on the same token, so the rows above are attributable
        # to the anchoring and not to some unrelated reason the corpus was empty.
        with tempfile.TemporaryDirectory() as td:
            root, source = self._fixture(td)
            self.assertEqual(
                [],
                self._scan(
                    root,
                    source,
                    consumer_sources={
                        "scripts/derive-verdict.sh": 'FLAG="--verdict-threshold"\n'
                    },
                ),
            )

    def test_step_one_ignores_a_common_word_in_an_unrelated_file(self):
        # The negative control for the token rule. This literal carries no
        # machine-identifier-shaped token: "configuration" and "documentation"
        # are long, but a plain English word is never distinctive, and
        # "fail-closed" is a two-segment kebab word the rule excludes on purpose.
        literal = "the configuration documentation stays fail-closed"
        with tempfile.TemporaryDirectory() as td:
            root, source = self._fixture(td, literal=literal)
            consumer = {
                "scripts/unrelated.sh": (
                    "printf 'configuration documentation fail-closed verdict\\n'\n"
                )
            }
            findings = self._scan(root, source, consumer_sources=consumer)
            self.assertEqual(1, len(findings))
            self.assertIn("no program consumer reads it", findings[0])

    def test_step_one_ignores_a_mention_that_is_only_a_comment(self):
        with tempfile.TemporaryDirectory() as td:
            root, source = self._fixture(td)
            consumer = {"scripts/derive-verdict.sh": f"# quotes {self.LITERAL}\n"}
            findings = self._scan(root, source, consumer_sources=consumer)
            self.assertEqual(1, len(findings))
            self.assertIn("no program consumer reads it", findings[0])

    def test_step_one_corpus_excludes_the_suite_and_prose_surfaces(self):
        for path in (
            "lib/test/other-module.sh",
            "docs/internal/cloud-allowlist.md",
            "skills/review/phases/phase-4-verdict.md",
            "CONTRIBUTING.md",
        ):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as td:
                root, source = self._fixture(td)
                findings = self._scan(
                    root, source, consumer_sources={path: f"x {self.LITERAL} y\n"}
                )
                self.assertEqual(1, len(findings))

    def test_distinctive_token_shapes_are_machine_identifiers(self):
        qualifying = (
            "DEVFLOW_BASH",
            "scripts/workpad.py",
            "devflow:workpad",
            "--tick-progress",
            "config-get.sh",
            "phase-4-verdict",
            "mutation-routing-worktree",
        )
        for token in qualifying:
            with self.subTest(token=token):
                self.assertEqual(
                    (token,), self.mod.distinctive_consumer_tokens(f"see {token} here")
                )
        non_qualifying = (
            "configuration",
            "documentation",
            "fail-closed",
            "best-effort",
            "INCONCLUSIVE",
            "verdict",
            "2026-07-29",
        )
        for token in non_qualifying:
            with self.subTest(token=token):
                self.assertEqual(
                    (), self.mod.distinctive_consumer_tokens(f"see {token} here")
                )

    # ── Step 2: the ledger already recorded this literal as a boundary ──────
    def test_step_two_passes_a_prose_pin_with_a_tag_and_a_boundary_row(self):
        # The case that is impossible before #948: a prose-resolving literal
        # whose retention was adjudicated, tagged at the site.
        with tempfile.TemporaryDirectory() as td:
            root, source = self._fixture(td, marker=self.MARKER)
            self.assertEqual(
                [],
                self._scan(root, source, current_adjudications=self._ledger()),
            )

    def test_step_two_rejects_a_tag_with_no_ledger_row(self):
        # The anti-self-grant control: a tag is a POINTER to an authorized
        # decision, so tagging your own pin cannot make it legitimate.
        with tempfile.TemporaryDirectory() as td:
            root, source = self._fixture(td, marker=self.MARKER)
            findings = self._scan(root, source, current_adjudications={})
            self.assertEqual(1, len(findings))
            self.assertIn("records no boundary decision", findings[0])
            self.assertNotIn("no valid '# structural-pin-ok:'", findings[0])

    def test_step_two_rejects_a_ledger_row_with_no_tag(self):
        # DELIBERATE DECISION: the ledger row alone does NOT pass. Step 2 needs
        # both halves. Retrofitting tags onto the standing retained population is
        # out of scope precisely because the gate only asks when a site's own
        # lines change — and when they do, the reader of that line is owed the
        # reason at the site. This also keeps the change a pure loosening for
        # TAGGED pins and never a loosening for untagged ones.
        with tempfile.TemporaryDirectory() as td:
            root, source = self._fixture(td)
            findings = self._scan(root, source, current_adjudications=self._ledger())
            self.assertEqual(1, len(findings))
            self.assertIn("no valid '# structural-pin-ok:'", findings[0])
            self.assertNotIn("records no boundary decision", findings[0])

    def test_step_two_rejects_a_row_in_any_other_bucket(self):
        for bucket in (
            "prose-sole-copy",
            "prose-multi-copy",
            "required-copy",
            "suite-internal",
            "generated",
            "config-key",
        ):
            with self.subTest(bucket=bucket), tempfile.TemporaryDirectory() as td:
                root, source = self._fixture(td, marker=self.MARKER)
                findings = self._scan(
                    root, source, current_adjudications=self._ledger(bucket)
                )
                self.assertEqual(1, len(findings))
                self.assertIn("records no boundary decision", findings[0])

    def test_step_two_fails_closed_on_an_unestablished_ledger(self):
        # An unreadable ledger must never silently satisfy step 2. In production
        # it cannot even reach here (analyze_adjudication_changes raises first —
        # see StaticPinWorktreeCompositionTests.test_unreadable_ledger_*), and at
        # this boundary an unestablished or empty state is refused, not assumed.
        for label, ledger in (("unestablished", None), ("empty", {})):
            with self.subTest(ledger=label), tempfile.TemporaryDirectory() as td:
                root, source = self._fixture(td, marker=self.MARKER)
                findings = self._scan(root, source, current_adjudications=ledger)
                self.assertEqual(1, len(findings))
                self.assertIn("records no boundary decision", findings[0])

    def test_a_different_literals_boundary_row_does_not_carry_over(self):
        with tempfile.TemporaryDirectory() as td:
            root, source = self._fixture(td, marker=self.MARKER)
            findings = self._scan(
                root,
                source,
                current_adjudications=self._ledger(literal="an unrelated sentence"),
            )
            self.assertEqual(1, len(findings))
            self.assertIn("records no boundary decision", findings[0])

    # ── Step 3, and the arms that precede the ladder ────────────────────────
    def test_a_wording_only_pin_with_nothing_behind_it_is_still_a_finding(self):
        # The positive control that the policy did not get weaker.
        with tempfile.TemporaryDirectory() as td:
            root, source = self._fixture(td)
            findings = self._scan(root, source, consumer_sources={})
            self.assertEqual(1, len(findings))
            self.assertIn("resolves into prose", findings[0])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "docs/x.md"
            target.parent.mkdir(parents=True)
            target.write_text("```text\nMACHINE_SENTINEL\n```\n", encoding="utf-8")
            source = (
                'F="$LIB/../docs/x.md"\n'
                "assert_pin_unique \"sentinel\" 'MACHINE_SENTINEL' \"$F\""
            )
            findings = self._scan(root, source, current_adjudications=self._ledger())
            self.assertEqual(1, len(findings))
            self.assertIn("missing structural declaration", findings[0])

    def test_an_invalid_category_is_a_finding_ahead_of_the_whole_ladder(self):
        # Arm ORDER: declaration grammar is decided BEFORE routing, so neither a
        # program consumer nor a boundary row routes around a malformed tag. A
        # standing pin on a pre-vocabulary category therefore stays a finding
        # (fixing them is issue-948-out-of-scope follow-up work).
        for marker in (
            self.INVALID_MARKER,
            "# structural-pin-ok: helper-contract --   ",
            "# structural-pin-ok: -- no category at all",
        ):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as td:
                root, source = self._fixture(td, marker=marker)
                findings = self._scan(
                    root,
                    source,
                    consumer_sources={
                        "scripts/derive-verdict.sh": f"grep -qF '{self.LITERAL}' x\n"
                    },
                    current_adjudications=self._ledger(),
                )
                self.assertEqual(1, len(findings))
                self.assertNotIn("resolves into prose", findings[0])

    def test_each_configuration_selects_its_documented_arm(self):
        """One site, every configuration, the deciding arm named in each verdict.

        This is the arm-order driver: a reordered ladder moves at least one row.
        """
        consumer = {"scripts/derive-verdict.sh": f"grep -qF '{self.LITERAL}' x\n"}
        cases = (
            # (marker, consumer corpus, ledger, expected deciding fragment)
            ("valid", True, "boundary", None),
            ("valid", False, "boundary", None),
            ("none", True, "boundary", None),
            ("none", True, None, None),
            ("valid", False, None, "records no boundary decision"),
            ("none", False, "boundary", "no valid '# structural-pin-ok:'"),
            ("none", False, None, "no program consumer reads it"),
            ("invalid", True, "boundary", "unknown structural category"),
        )
        for marker, with_consumer, bucket, expected in cases:
            label = f"marker={marker} consumer={with_consumer} ledger={bucket}"
            with self.subTest(label), tempfile.TemporaryDirectory() as td:
                root, source = self._fixture(
                    td,
                    marker={
                        "valid": self.MARKER,
                        "invalid": self.INVALID_MARKER,
                        "none": "",
                    }[marker],
                )
                findings = self._scan(
                    root,
                    source,
                    consumer_sources=consumer if with_consumer else {},
                    current_adjudications=self._ledger(bucket) if bucket else {},
                )
                if expected is None:
                    self.assertEqual([], findings, label)
                else:
                    self.assertEqual(1, len(findings), label)
                    self.assertIn(expected, findings[0], label)

    def test_a_retired_literal_keeps_the_pre_948_revival_contract(self):
        # SCOPE: the ladder governs the RETAINED population. An authorized
        # revival of a RETIRED wording literal still requires a genuinely
        # machine-shaped target, because both ladder steps rest on the same
        # boundary row that contract says cannot alone authorize a revival. Here
        # the site has everything the ladder would want — valid tag, boundary
        # row, a program consumer — and is still reported, with no ladder clause.
        with tempfile.TemporaryDirectory() as td:
            root, source = self._fixture(td, marker=self.MARKER)
            key = self._key()
            # Retirement now keys on SITE identity (issue #1006): the site this
            # fixture builds is (lib/test/a.sh, assert_pin_unique, LITERAL, TARGET).
            # The ledger delta/current-state below still key on the literal, so both
            # keys appear -- exactly the two-key split scan_changed_sources makes.
            retirement_key = self.mod._site_retirement_key(
                "lib/test/a.sh", "assert_pin_unique", self.LITERAL, self.TARGET
            )
            state = ("boundary", self.RATIONALE)
            authorization = self.mod.RevivalAuthorization(
                "lib/test/a.sh",
                "static-helper",
                "assert_pin_unique",
                key,
                self.TARGET,
                "cross-file-phase-contract",
                self.MARKER.split(" -- ", 1)[1],
            )
            findings = self._scan(
                root,
                source,
                retired_literal_keys=frozenset({retirement_key}),
                revival_authorizations=frozenset({authorization}),
                adjudication_delta={key: (None, state)},
                current_adjudications={key: state},
                consumer_sources={
                    "scripts/derive-verdict.sh": f"grep -qF '{self.LITERAL}' x\n"
                },
            )
            self.assertEqual(1, len(findings))
            self.assertIn("resolves into prose", findings[0])
            self.assertNotIn("no program consumer reads it", findings[0])


class SanctionedRenameComparison1002Tests(unittest.TestCase):
    """Issue #1002: a site that is its own merge-base self, respelled, is not a
    changed site — and that exemption cannot absolve anything else.

    The fix corrects a COMPARISON. ``scan_changed_sources`` resolves the
    merge-base source image against current-tree path spellings, so across a
    branch that renames the state directory ``old_effective == new_effective``
    was measuring path spelling rather than pin identity and reported every pin
    under that directory as re-pointed. Each test below names the property that
    keeps this a correction rather than an amnesty, and every negative control
    asserts a FINDING — the direction a weakened filter would lose.

    The map is the repository's own shipped ``lib/rename-map.json``, copied into
    each fixture rather than restated here, so a change to the shipped frozen
    block is felt by these tests instead of being shadowed by a private copy.
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = load_linter()
        cls.map_text = (REPO_ROOT / "lib/rename-map.json").read_text(
            encoding="utf-8"
        )

    SOURCE_PATH = "lib/test/a.sh"

    def _repo(self, td, *, with_map=True):
        root = Path(td)
        if with_map:
            (root / "lib").mkdir(parents=True, exist_ok=True)
            (root / "lib/rename-map.json").write_text(
                self.map_text, encoding="utf-8"
            )
        return root

    @staticmethod
    def _pin(literal, target, *, name="pin", marker=""):
        return (
            f'F="$LIB/../{target}"\n'
            f"assert_pin_unique \"{name}\" '{literal}' \"$F\""
            + (f"  {marker}" if marker else "")
            + "\n"
        )

    def _scan(self, root, base, head):
        return self.mod.scan_changed_sources(
            {self.SOURCE_PATH: head},
            {self.SOURCE_PATH: base},
            one_file_diff(self.SOURCE_PATH, base, head),
            repo_root=root,
        )

    # ── The exemption itself ───────────────────────────────────────────────
    def test_a_rename_only_respelling_is_not_a_changed_site(self):
        """Both halves of a pin — its target path and its literal — respelled by
        the sanctioned rename, and nothing else."""
        cases = (
            (
                ".devflow/prompt-extensions/review.md",
                ".prflow/prompt-extensions/review.md",
                "a sentence that did not change at all",
                "a sentence that did not change at all",
            ),
            (
                "docs/x.md",
                "docs/x.md",
                "config-get.sh .devflow_review.verdict_severity_threshold critical",
                "config-get.sh .prflow_review.verdict_severity_threshold critical",
            ),
            (
                "docs/x.md",
                "docs/x.md",
                ".devflow/vendor/devflow/scripts/apply-labels.sh",
                ".prflow/vendor/prflow/scripts/apply-labels.sh",
            ),
            # The two workflows.* sub-keys, no longer frozen (issue #1041).
            (
                "docs/x.md",
                "docs/x.md",
                "reads .workflows.devflow // false",
                "reads .workflows.prflow // false",
            ),
            (
                "docs/x.md",
                "docs/x.md",
                "the workflows.devflow-review toggle",
                "the workflows.prflow-review toggle",
            ),
        )
        for base_target, head_target, base_literal, head_literal in cases:
            with self.subTest(base_literal), tempfile.TemporaryDirectory() as td:
                root = self._repo(td)
                base = self._pin(base_literal, base_target)
                head = self._pin(head_literal, head_target)
                self.assertEqual([], self._scan(root, base, head))
                # RED control on the SAME input: with no map to establish the
                # rename, the site is a candidate again. This is what proves the
                # exemption cleared it, and that an absent map fails closed.
                bare = self._repo(td + "-nomap", with_map=False)
                bare.mkdir(parents=True, exist_ok=True)
                try:
                    self.assertEqual(1, len(self._scan(bare, base, head)))
                finally:
                    shutil.rmtree(bare, ignore_errors=True)

    # ── The load-bearing negative control ──────────────────────────────────
    def test_a_rename_plus_any_other_edit_is_not_exempt(self):
        """Exact-tuple equality: the rename never carries a second edit through.

        Every row respells the target by the sanctioned rename AND changes one
        further element of the effective tuple. Each must still be reported.
        """
        base_target = ".devflow/prompt-extensions/review.md"
        head_target = ".prflow/prompt-extensions/review.md"
        literal = "the operative sentence"
        marker = (
            "# structural-pin-ok: cross-file-phase-contract -- "
            "a declaration the base site did not carry"
        )
        cases = {
            "literal edited": self._pin("the operative sentences", head_target),
            "literal widened": self._pin(literal + " naming", head_target),
            "declaration added": self._pin(literal, head_target, marker=marker),
            "target repointed elsewhere": self._pin(
                literal, ".prflow/prompt-extensions/implement.md"
            ),
            "helper changed": (
                f'F="$LIB/../{head_target}"\n'
                f"grep -qF '{literal}' \"$F\"\n"
            ),
        }
        for label, head in cases.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as td:
                root = self._repo(td)
                base = self._pin(literal, base_target)
                self.assertEqual(1, len(self._scan(root, base, head)), label)

    # ── The frozen block ───────────────────────────────────────────────────
    def test_a_frozen_name_is_never_mapped(self):
        """A name the map freezes must not be rewritten into an exemption.

        Without the frozen-first alternation a bare ``devflow`` rule would map a
        frozen name and silently absolve a real change to it — the exact hazard
        this ordering exists to stop. Every row is a genuine ``devflow -> prflow``
        edit to a frozen name, and every row must be REPORTED. (The two
        ``workflows.*`` sub-keys were frozen through Tiers 1–3 but are now
        renamed — issue #1041 — so their sanctioned respelling is covered by
        ``test_a_rename_only_respelling_is_not_a_changed_site`` instead.)
        """
        cases = {
            "frozen workflow filename": (
                ".github/workflows/devflow.yml",
                ".github/workflows/prflow.yml",
            ),
            "frozen identifier": (
                "the devflow-marketplace entry",
                "the prflow-marketplace entry",
            ),
            "frozen module-pin glob": (
                "devflow_module_pin_unique is the helper",
                "prflow_module_pin_unique is the helper",
            ),
            "frozen env var": ("DEVFLOW_GH selects the binary", "PRFLOW_GH selects the binary"),
            "frozen subagent namespace": (
                'dispatches "devflow:requesting-code-review"',
                'dispatches "prflow:requesting-code-review"',
            ),
        }
        for label, (base_literal, head_literal) in cases.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as td:
                root = self._repo(td)
                base = self._pin(base_literal, "docs/x.md")
                head = self._pin(head_literal, "docs/x.md")
                self.assertEqual(1, len(self._scan(root, base, head)), label)

    # ── One for one ────────────────────────────────────────────────────────
    def test_one_base_site_exempts_at_most_one_candidate(self):
        """The same discipline ``_deleted_pin_literals`` applies to moves: a
        duplicated pin still presents its duplicate for adjudication."""
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            literal = "the operative sentence"
            base = self._pin(literal, ".devflow/prompt-extensions/review.md")
            head = (
                'F="$LIB/../.prflow/prompt-extensions/review.md"\n'
                f"assert_pin_unique \"pin\" '{literal}' \"$F\"\n"
                f"assert_pin_unique \"pin\" '{literal}' \"$F\"\n"
            )
            self.assertEqual(1, len(self._scan(root, base, head)))
            # Two base sites exempt both, which is the boundary of the rule
            # rather than a second behaviour.
            base_two = base + self._pin(
                literal, ".devflow/prompt-extensions/review.md"
            )
            self.assertEqual([], self._scan(root, base_two, head))

    # ── One direction only ─────────────────────────────────────────────────
    def test_the_exemption_is_one_directional(self):
        """A HEAD site still spelled ``.devflow`` is never exempted by a
        ``.prflow`` twin at the merge base: the rename cannot be run backwards.
        """
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            literal = "the operative sentence"
            base = self._pin(literal, ".prflow/prompt-extensions/review.md")
            head = self._pin(literal, ".devflow/prompt-extensions/review.md")
            self.assertEqual(1, len(self._scan(root, base, head)))
            # The same pair in the sanctioned direction IS exempt, so the row
            # above fails for its direction and not for some unrelated reason.
            self.assertEqual([], self._scan(root, head, base))

    # ── The map loader ─────────────────────────────────────────────────────
    def test_an_unusable_map_exempts_nothing_and_says_so(self):
        """Fail-closed: every way the map can be unusable withdraws the whole
        exemption, and only an ABSENT map is silent."""
        literal = "the operative sentence"
        base = self._pin(literal, ".devflow/prompt-extensions/review.md")
        head = self._pin(literal, ".prflow/prompt-extensions/review.md")
        cases = {
            "absent": (None, False),
            "not json": ("{not json", True),
            "root not an object": ("[]", True),
            "no frozen block": ('{"paths": {}, "config_keys": {"a": "b"}}', True),
            "frozen field wrong type": (
                json.dumps(
                    {
                        "frozen": {
                            "config_keys": "workflows.devflow",
                            "identifiers": [],
                            "workflow_filenames": [],
                        },
                        "paths": {},
                        "config_keys": {"a": "b"},
                    }
                ),
                True,
            ),
            "paths entry incomplete": (
                json.dumps(
                    {
                        "frozen": {
                            "config_keys": [],
                            "identifiers": [],
                            "workflow_filenames": [],
                        },
                        "paths": {
                            "state_dir": {"superseded": ".devflow"},
                            "vendor_dir": {
                                "superseded": ".devflow/vendor/devflow",
                                "current": ".prflow/vendor/prflow",
                            },
                            "scratch_dirs": [],
                        },
                        "config_keys": {"devflow": "prflow"},
                    }
                ),
                True,
            ),
        }
        for label, (text, expect_breadcrumb) in cases.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as td:
                root = self._repo(td, with_map=False)
                if text is not None:
                    (root / "lib").mkdir(parents=True, exist_ok=True)
                    (root / "lib/rename-map.json").write_text(
                        text, encoding="utf-8"
                    )
                stderr = io.StringIO()
                with mock.patch.object(sys, "stderr", stderr):
                    findings = self._scan(root, base, head)
                self.assertEqual(1, len(findings), label)
                self.assertEqual(
                    expect_breadcrumb,
                    "MUTATION-ROUTING-RENAME-MAP-UNAVAILABLE" in stderr.getvalue(),
                    label,
                )

    def test_the_frozen_alternation_is_load_bearing_on_its_own(self):
        """Isolate the frozen guard from the qualified-key rule.

        Against the SHIPPED map the two protections overlap on every frozen name
        — `devflow` is qualified-only *and* each frozen name is listed — so
        deleting either one alone leaves the other holding, and no
        shipped-map case can tell them apart. That redundancy is worth having and
        is not worth mistaking for coverage: it makes a shipped-map test unable
        to fail when the frozen alternation is removed.

        This drives the guard where it is the SOLE protection, using the map
        shape that reaches it: a map whose ``frozen.config_keys`` is empty makes
        ``devflow`` an unqualified rule, and then only the frozen
        ``workflow_filenames`` entry stops ``devflow.yml`` becoming
        ``prflow.yml``.
        """
        document = json.loads(self.map_text)
        document["frozen"]["config_keys"] = []
        substitute = self.mod._compiled_rename_substitution(json.dumps(document))
        self.assertIsNotNone(substitute)
        # The unqualified rule is genuinely live in this shape — the control
        # that proves the row below is decided by the frozen entry.
        self.assertEqual('"prflow": true', substitute('"devflow": true'))
        for frozen in (
            "devflow.yml",
            "devflow-implement.yml",
            ".github/workflows/devflow-runner.yml",
            "devflow-marketplace",
            "devflow_module_pin_unique",
        ):
            self.assertEqual(frozen, substitute(frozen), frozen)

    def test_the_shipped_map_maps_the_rename_and_freezes_the_frozen_block(self):
        """The substitution derived from the SHIPPED map, driven directly.

        The site-level tests above can only observe the substitution through a
        whole scan; this one pins its answers, so a regression names the input
        that moved instead of surfacing as a changed finding count.
        """
        substitute = self.mod._compiled_rename_substitution(self.map_text)
        self.assertIsNotNone(substitute)
        for before, after in (
            (".devflow/logs/x.tsv", ".prflow/logs/x.tsv"),
            (
                ".devflow/vendor/devflow/scripts/x.sh",
                ".prflow/vendor/prflow/scripts/x.sh",
            ),
            (".devflow-scratch/a", ".prflow-scratch/a"),
            (".devflow-tmp/a", ".prflow-tmp/a"),
            (".devflow.allowed_tools", ".prflow.allowed_tools"),
            (
                ".devflow_review_and_fix.fix_severity_threshold",
                ".prflow_review_and_fix.fix_severity_threshold",
            ),
            ("devflow_implement.allowed_tools", "prflow_implement.allowed_tools"),
            ("devflow_runner.allowed_tools", "prflow_runner.allowed_tools"),
            ("devflow_retrospective.x", "prflow_retrospective.x"),
            ("devflow_version", "prflow_version"),
            # Issue #1003's identifier channel. The label is token-matched, the
            # branch and the marker namespace are prefix-matched, because their
            # shipped uses extend them with a hyphen / a family name.
            ("the DevFlow label", "the PRFlow label"),
            (
                "scripts/apply-labels.sh <issue_number> DevFlow",
                "scripts/apply-labels.sh <issue_number> PRFlow",
            ),
            ("devflow-telemetry", "prflow-telemetry"),
            (
                "name: devflow-telemetry-stage-${{ github.run_id }}",
                "name: prflow-telemetry-stage-${{ github.run_id }}",
            ),
            ("<!-- devflow:workpad -->", "<!-- prflow:workpad -->"),
            (
                "<!-- devflow:lint-adjudications-start -->",
                "<!-- prflow:lint-adjudications-start -->",
            ),
            (
                "<!-- devflow:review-progress run=${GITHUB_RUN_ID} -->",
                "<!-- prflow:review-progress run=${GITHUB_RUN_ID} -->",
            ),
            # Issue #1041 renames the two workflows.* sub-keys (no longer frozen).
            ("workflows.devflow", "workflows.prflow"),
            ("workflows.devflow-review", "workflows.prflow-review"),
            ('"workflows": {"devflow": true}', '"workflows": {"prflow": true}'),
        ):
            self.assertEqual(after, substitute(before), before)
        for frozen in (
            "devflow-marketplace",
            "lib + python tests",
            # Issue #1003 renames the LABEL `DevFlow`, and nothing else spelled
            # that way: the unrelated compound and every prose occurrence of the
            # product name are out of the token rule's reach, because `-` and a
            # following token character both continue the token.
            "DevFlow-layout closure paths would clobber",
            "DevFlow-layout",
            "DevFlowIsTheProduct",
            # The subagent-override namespace and the transitional command
            # spellings keep `devflow:` — only the HTML-comment marker form is
            # renamed, so the structural frozen entry still holds for these.
            "devflow_module_pin_unique",
            "devflow.yml",
            "devflow-implement.yml",
            "devflow-runner.yml",
            "devflow-review.yml",
            "telemetry-push.yml",
            '"devflow:requesting-code-review"',
            "DEVFLOW_GH",
            "/devflow:implement",
            ".prflow/prompt-extensions/review.md",
        ):
            self.assertEqual(frozen, substitute(frozen), frozen)


class IdentifierChannel1003Tests(unittest.TestCase):
    """Issue #1003: the map's identifier channel, and the three edits that were
    each a SILENT no-op before the compiler was taught to read it.

    The measured failure modes were: un-freezing a name without adding a rule
    (substitution unchanged, nothing raises); adding a rule while the name stays
    frozen (the frozen alternative is compiled first and consumes the match, so
    the rule is inert, nothing raises); and inventing a top-level block the
    builder does not read (validated blocks only, so an unknown key is ignored
    without a ValueError). Each is now a refusal that names the input.
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = load_linter()
        cls.map_text = (REPO_ROOT / "lib/rename-map.json").read_text(
            encoding="utf-8"
        )

    def _document(self):
        return json.loads(self.map_text)

    # ── the map and the compiler agree, both ways round ────────────────────
    def test_every_shipped_identifier_is_actually_mapped(self):
        """The reconciliation the issue's AC asks for, in the mapping direction.

        A name listed in `identifiers` that the compiled substitution leaves
        alone is exactly the "un-freeze only, no rule" / "unknown block" no-op:
        the map reads as edited and behaves identically. Driving the SHIPPED map
        makes that disagreement RED instead of invisible.
        """
        document = self._document()
        substitute = self.mod._compiled_rename_substitution(self.map_text)
        self.assertIsNotNone(substitute)
        self.assertTrue(document["identifiers"], "the channel must not be empty")
        for entry in document["identifiers"]:
            superseded, current = entry["superseded"], entry["current"]
            with self.subTest(entry["id"]):
                self.assertEqual(current, substitute(superseded))
                # And in a sentence, not only alone — a rule that fires only on a
                # bare literal would miss every real pin site.
                self.assertEqual(
                    f"x {current} y", substitute(f"x {superseded} y")
                )

    def test_every_shipped_frozen_name_is_still_left_alone(self):
        """The same reconciliation in the freezing direction: no entry of the
        frozen block is reachable by any rule, including the new channel."""
        document = self._document()
        substitute = self.mod._compiled_rename_substitution(self.map_text)
        self.assertIsNotNone(substitute)
        for field in ("config_keys", "identifiers", "workflow_filenames"):
            for literal in document["frozen"][field]:
                # The one glob form the map uses stands for a family; drive a
                # concrete member of it rather than the pattern text.
                probe = (
                    literal[:-1] + "unique" if literal.endswith("*") else literal
                )
                with self.subTest(f"frozen.{field}: {literal}"):
                    self.assertEqual(probe, substitute(probe))

    # ── the three refusals ─────────────────────────────────────────────────
    def test_a_rule_whose_name_is_also_frozen_is_refused(self):
        """"Add a rule but leave the name frozen" was inert and silent."""
        document = self._document()
        document["frozen"]["identifiers"].append("DevFlow")
        with self.assertRaises(ValueError) as ctx:
            self.mod._build_rename_substitution(document)
        self.assertIn("DevFlow", str(ctx.exception))
        self.assertIn("freezes and maps", str(ctx.exception))

    def test_an_unreadable_top_level_block_is_refused(self):
        """"Invent a new block without teaching the builder" was ignored."""
        document = self._document()
        document["brand_names"] = {"devflow": "prflow"}
        with self.assertRaises(ValueError) as ctx:
            self.mod._build_rename_substitution(document)
        self.assertIn("brand_names", str(ctx.exception))

    def test_an_identifier_entry_with_no_declared_match_is_refused(self):
        """The match semantics are per entry and REQUIRED: the label must not
        reach `DevFlow-layout` while the branch must reach
        `devflow-telemetry-stage-<run>`, so a defaulted match would silently pick
        the wrong one for half the channel."""
        for bad in (None, "", "substring", 1):
            document = self._document()
            entry = dict(document["identifiers"][0])
            if bad is None:
                entry.pop("match", None)
            else:
                entry["match"] = bad
            document["identifiers"][0] = entry
            with self.subTest(repr(bad)):
                with self.assertRaises(ValueError) as ctx:
                    self.mod._build_rename_substitution(document)
                self.assertIn("identifiers[0]", str(ctx.exception))

    def test_an_absent_identifier_channel_is_refused(self):
        document = self._document()
        del document["identifiers"]
        with self.assertRaises(ValueError):
            self.mod._build_rename_substitution(document)

    # ── the boundaries the two match kinds buy ─────────────────────────────
    def test_the_token_rule_cannot_reach_the_unrelated_compound_or_prose(self):
        """`DevFlow-layout` and the product name in prose stay put — the AC's
        explicit non-goal. A prefix rule here would rewrite both."""
        substitute = self.mod._compiled_rename_substitution(self.map_text)
        for untouched in (
            "DevFlow-layout",
            "the DevFlow-layout closure",
            "DevFlowRunner",
            "DevFlow_layout",
        ):
            with self.subTest(untouched):
                self.assertEqual(untouched, substitute(untouched))

    def test_the_marker_rule_narrows_the_frozen_subagent_namespace(self):
        """`<!-- devflow:` is longer than the frozen `devflow:`, so the ordering
        must let it win — and the frozen entry must still hold everywhere else.
        Without the longest-literal ordering this rename is a silent no-op."""
        substitute = self.mod._compiled_rename_substitution(self.map_text)
        self.assertEqual(
            "<!-- prflow:review-backstop head=abc -->",
            substitute("<!-- devflow:review-backstop head=abc -->"),
        )
        for untouched in (
            '"devflow:requesting-code-review"',
            "/devflow:implement",
            "subagent_type: devflow:code-reviewer",
        ):
            with self.subTest(untouched):
                self.assertEqual(untouched, substitute(untouched))


class BundleTargetInspection956Tests(unittest.TestCase):
    """Issue #956: a pin whose target is a bundle the source CONCATENATES at
    runtime is inspected against the bundle's MEMBER FILES.

    Every test states which direction it protects. The positive cases prove the
    unfreeze (a typed declaration on such a pin is now inspectable, so its line
    can be edited at all); the negative controls prove the fix is resolution, not
    amnesty — an unresolvable target, an unmodeled build shape, an unreadable
    member, an ambiguous name and a literal in no member all keep the refusal.
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = load_linter()

    MARKER = (
        "# structural-pin-ok: cross-file-phase-contract -- "
        "the sentence spells a contract the split surfaces share"
    )
    LITERAL = "the fix loop re-reads the reference before it edits"
    SKIPPED_LITERAL = "this template sentence is not part of the bundle"

    # The module shape the repository really uses: a root variable written with a
    # default expansion over a suffix strip, an array seeded with one member, a
    # for-loop over a directory glob with a basename skip, and one builder call.
    BUILD = (
        'ROOT="${DEVFLOW_MODULE_ROOT:-${LIB%/lib}}"\n'
        'SKILL="$ROOT/skills/demo/SKILL.md"\n'
        'BUNDLE="$SCRATCH/demo-bundle.md"\n'
        '_members=("$SKILL")\n'
        'for _ref in "$ROOT"/skills/demo/references/*.md; do\n'
        '  case "${_ref##*/}" in template.md) continue ;; esac\n'
        '  _members+=("$_ref")\n'
        "done\n"
        'devflow_module_build_bundle "demo" "$BUNDLE" "${_members[@]}"\n'
    )

    def _tree(self, td, *, literal=None, in_reference=True):
        """Write the demo skill tree; return its repository root."""
        root = Path(td)
        skill = root / "skills/demo/SKILL.md"
        skill.parent.mkdir(parents=True, exist_ok=True)
        references = skill.parent / "references"
        references.mkdir(parents=True, exist_ok=True)
        body = literal if literal is not None else self.LITERAL
        skill.write_text("# Demo\n\nThe root carries no contract.\n", encoding="utf-8")
        (references / "fixing.md").write_text(
            f"# Fixing\n\nStep two: {body}.\n" if in_reference else "# Fixing\n\nnone\n",
            encoding="utf-8",
        )
        # The excluded template member: never part of the bundle, so a literal
        # living only here must NOT satisfy inspection.
        (references / "template.md").write_text(
            f"# Template\n\n{self.SKIPPED_LITERAL}.\n", encoding="utf-8"
        )
        return root

    def _sites(self, root, source, path="lib/test/mod.sh"):
        return self.mod.extract_guard_sites(source, path, str(root))

    def _pin(self, literal=None, target="$BUNDLE", marker=None):
        marker = self.MARKER if marker is None else marker
        return (
            'devflow_module_pin_unique "demo contract" '
            f"'{literal or self.LITERAL}' \"{target}\""
            + (f"  {marker}" if marker else "")
            + "\n"
        )

    def _site(self, root, source):
        sites = [site for site in self._sites(root, source) if site.helper]
        self.assertEqual(1, len(sites), sites)
        return sites[0]

    # ── the unfreeze ───────────────────────────────────────────────────────
    def test_bundle_target_resolves_to_its_member_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            members = self.mod.resolve_bundle_targets(
                self.BUILD, str(root / "lib")
            )["BUNDLE"]
            self.assertEqual(
                [
                    str(root / "skills/demo/SKILL.md"),
                    str(root / "skills/demo/references/fixing.md"),
                ],
                list(members),
                "the basename skip must EXCLUDE template.md, not merely resolve",
            )

    def test_typed_declaration_on_a_bundle_target_is_inspectable(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            site = self._site(root, self.BUILD + self._pin())
            self.assertIsNone(site.target_path)
            self.assertEqual(2, len(site.target_members))
            self.assertIsNone(self.mod._typed_pin_inspection_error(site, str(root)))

    def test_an_alias_of_a_resolved_bundle_is_inspectable_too(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            source = self.BUILD + 'ALIAS="$BUNDLE"\n' + self._pin(target="$ALIAS")
            site = self._site(root, source)
            self.assertIsNone(self.mod._typed_pin_inspection_error(site, str(root)))

    def test_a_raw_grep_over_the_same_bundle_is_inspected_the_same_way(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            source = self.BUILD + (
                'assert_eq "demo raw" "yes" '
                f"\"$(grep -qF '{self.LITERAL}' \"$BUNDLE\" && echo yes || echo no)\""
                f"  {self.MARKER}\n"
            )
            sites = [
                site
                for site in self._sites(root, source)
                if site.family == "raw-presence"
            ]
            self.assertEqual(1, len(sites), sites)
            self.assertIsNone(
                self.mod._typed_pin_inspection_error(sites[0], str(root))
            )

    # ── the memo contract this resolver has to keep ─────────────────────────
    def test_membership_is_not_answered_from_a_memo_after_the_tree_changes(self):
        # The parse is memoized; the glob expansion must NOT be, or the memo would
        # capture filesystem state and a co-resident sharded test could be answered
        # from another fixture's tree (this file's module docstring forbids that).
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            lib = str(root / "lib")
            self.assertEqual(
                2, len(self.mod.resolve_bundle_targets(self.BUILD, lib)["BUNDLE"])
            )
            (root / "skills/demo/references/later.md").write_text(
                "# Later\n\nadded after the first resolution\n", encoding="utf-8"
            )
            self.assertEqual(
                3,
                len(self.mod.resolve_bundle_targets(self.BUILD, lib)["BUNDLE"]),
                "the expansion must be re-read, not served from the parse memo",
            )

    def test_each_caller_gets_its_own_mapping(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            lib = str(root / "lib")
            first = self.mod.resolve_bundle_targets(self.BUILD, lib)
            first["LEAKED_BUNDLE"] = ()
            self.assertNotIn(
                "LEAKED_BUNDLE", self.mod.resolve_bundle_targets(self.BUILD, lib)
            )

    # ── negative controls: the refusal still fires ──────────────────────────
    def test_an_unresolvable_non_bundle_target_still_cannot_be_inspected(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            source = self._pin(target="$SOME_RUNTIME_TEMP")
            site = self._site(root, source)
            self.assertEqual(
                "typed structural declaration target cannot be inspected",
                self.mod._typed_pin_inspection_error(site, str(root)),
            )

    def test_a_literal_in_no_member_is_still_reported_absent(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td, in_reference=False)
            site = self._site(root, self.BUILD + self._pin())
            self.assertEqual(
                "typed structural declaration literal cannot be inspected "
                "(absent from target)",
                self.mod._typed_pin_inspection_error(site, str(root)),
            )

    def test_a_literal_only_in_the_skipped_member_is_reported_absent(self):
        # The sharp form of the exclusion test: membership is exact, so content
        # the build skips can never satisfy a bundle pin.
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            site = self._site(
                root, self.BUILD + self._pin(literal=self.SKIPPED_LITERAL)
            )
            self.assertEqual(
                "typed structural declaration literal cannot be inspected "
                "(absent from target)",
                self.mod._typed_pin_inspection_error(site, str(root)),
            )

    def test_an_unreadable_member_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            build = self.BUILD.replace(
                'devflow_module_build_bundle "demo" "$BUNDLE" "${_members[@]}"',
                'devflow_module_build_bundle "demo" "$BUNDLE" "${_members[@]}" '
                '"$ROOT/skills/demo/absent.md"',
            )
            site = self._site(root, build + self._pin())
            self.assertEqual(
                "typed structural declaration target cannot be inspected "
                "(FileNotFoundError)",
                self.mod._typed_pin_inspection_error(site, str(root)),
            )

    def test_an_unresolvable_member_word_leaves_the_bundle_unresolved(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            build = self.BUILD.replace(
                '_members=("$SKILL")', '_members=("$SKILL" "$UNKNOWN_VAR")'
            )
            site = self._site(root, build + self._pin())
            self.assertEqual(
                "typed structural declaration target cannot be inspected",
                self.mod._typed_pin_inspection_error(site, str(root)),
            )

    def test_an_unmodeled_loop_append_leaves_the_bundle_unresolved(self):
        # A loop body that appends neither the loop variable nor a template
        # interpolating it contributes members this grammar cannot enumerate.
        # Resolving that array to "the words modeled so far" would yield a strict
        # SUBSET of the real membership and could report a present literal as
        # absent, so the shape must poison the bundle instead. (The interpolated
        # stem-list shape this test once covered IS modeled since issue #1008 —
        # BundleStemLoopAndAliasResolution1008Tests carries it, with its own
        # negative controls.)
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            build = (
                'ROOT="${DEVFLOW_MODULE_ROOT:-${LIB%/lib}}"\n'
                'SKILL="$ROOT/skills/demo/SKILL.md"\n'
                'STEMS="fixing"\n'
                '_members=("$SKILL")\n'
                "for _s in $STEMS; do\n"
                '  _members+=("$ROOT/skills/demo/references/fixing.md")\n'
                "done\n"
                'devflow_module_build_bundle "demo" "$BUNDLE" "${_members[@]}"\n'
            )
            site = self._site(root, build + self._pin())
            self.assertEqual(
                "typed structural declaration target cannot be inspected",
                self.mod._typed_pin_inspection_error(site, str(root)),
            )

    def test_two_builds_of_one_name_leave_it_ambiguous(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            build = self.BUILD + (
                'devflow_module_build_bundle "demo again" "$BUNDLE" "$SKILL"\n'
            )
            site = self._site(root, build + self._pin())
            self.assertEqual(
                "typed structural declaration target cannot be inspected",
                self.mod._typed_pin_inspection_error(site, str(root)),
            )

    def test_an_empty_glob_expansion_is_not_treated_as_inspected(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            for reference in (root / "skills/demo/references").iterdir():
                reference.unlink()
            site = self._site(root, self.BUILD + self._pin())
            self.assertEqual(
                "typed structural declaration target cannot be inspected",
                self.mod._typed_pin_inspection_error(site, str(root)),
            )

    # ── the ladder still decides, and the tag still cannot self-grant ───────
    def test_bundle_member_prose_still_requires_a_ledger_boundary_row(self):
        source = self.BUILD + self._pin()
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            key = self.mod._literal_adjudication_key(self.LITERAL)

            def scan(**kwargs):
                return self.mod.scan_changed_sources(
                    {"lib/test/mod.sh": source},
                    {"lib/test/mod.sh": ""},
                    one_file_diff("lib/test/mod.sh", "", source),
                    repo_root=str(root),
                    **kwargs,
                )

            unrouted = scan()
            self.assertEqual(1, len(unrouted))
            self.assertIn(
                "literal resolves into prose at skills/demo/references/fixing.md",
                unrouted[0],
                "prose resolution must follow the members, so the tag alone "
                "cannot self-grant a bundle pin",
            )
            self.assertEqual(
                [],
                scan(
                    current_adjudications={
                        key: ("boundary", "maintainer adjudication: demo boundary")
                    }
                ),
            )


class BundleStemLoopAndAliasResolution1008Tests(unittest.TestCase):
    """Issue #1008: the two independent reasons a bundle variable still failed to
    resolve after issue #956, each measured against ``lib/test/run.sh`` first.

    Cause A — the stem-loop build body. ``$REVIEW_BUNDLE`` iterates a word-list
    variable and appends a path TEMPLATE per stem rather than the loop variable
    itself, so it resolved to nothing while the two array-built bundles beside it
    resolved to 9 and 10 members. Cause B — a comment-suffixed alias
    (``ST_RAF="$MAXI_BUNDLE"   # …``) did not resolve even when its source bundle
    did, because the comment is part of the right-hand side.

    Either one left a ``# structural-pin-ok:`` declaration on the affected pin
    refused as uninspectable, which froze the whole logical line. The positive
    tests prove the unfreeze; the negative controls prove the widening is
    resolution, not amnesty — an unmodeled stem list, an unresolvable template, a
    reassigned list, a basename skip over a template, an unmodeled body statement
    and a hash that is not a trailing comment all keep the refusal.
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = load_linter()

    MARKER = (
        "# structural-pin-ok: cross-file-phase-contract -- "
        "the sentence spells a contract the split surfaces share"
    )
    LITERAL = "the reviewer re-derives bundle identity on every entry"
    ORPHAN_LITERAL = "this phase file is named by no stem in the list"

    # The shape `lib/test/run.sh` really uses for the review bundle: two literal
    # word lists composed into a third, an array seeded with the root, and a loop
    # that appends one interpolated path per stem.
    STEM_BUILD = (
        'ROOT="${DEVFLOW_MODULE_ROOT:-${LIB%/lib}}"\n'
        'SKILL="$ROOT/skills/demo/SKILL.md"\n'
        'DEFAULT_STEMS="alpha"\n'
        'GATED_STEMS="beta"\n'
        'STEMS="$DEFAULT_STEMS $GATED_STEMS"\n'
        '_members=("$SKILL")\n'
        "for _s in $STEMS; do\n"
        '  _members+=("$ROOT/skills/demo/phases/${_s}.md")\n'
        "done\n"
        'devflow_module_build_bundle "demo" "$BUNDLE" "${_members[@]}"\n'
    )

    def _tree(self, td, *, literal=None):
        """Write the demo skill tree; return its repository root.

        ``orphan.md`` sits in the same directory as the two stem-named phase
        files and is named by no stem, so it is the exactness control: content
        that lives only there can never satisfy a bundle pin.
        """
        root = Path(td)
        phases = root / "skills/demo/phases"
        phases.mkdir(parents=True, exist_ok=True)
        (root / "skills/demo/SKILL.md").write_text(
            "# Demo\n\nThe root carries no contract.\n", encoding="utf-8"
        )
        (phases / "alpha.md").write_text("# Alpha\n\nsetup only\n", encoding="utf-8")
        (phases / "beta.md").write_text(
            "# Beta\n\nStep two: %s.\n" % (literal or self.LITERAL), encoding="utf-8"
        )
        (phases / "orphan.md").write_text(
            f"# Orphan\n\n{self.ORPHAN_LITERAL}.\n", encoding="utf-8"
        )
        return root

    def _members(self, root, source):
        return self.mod.resolve_bundle_targets(source, str(root / "lib"))

    def _pin(self, literal=None, target="$BUNDLE"):
        return (
            'devflow_module_pin_unique "demo contract" '
            f"'{literal or self.LITERAL}' \"{target}\"  {self.MARKER}\n"
        )

    def _site(self, root, source):
        sites = [
            site
            for site in self.mod.extract_guard_sites(
                source, "lib/test/mod.sh", str(root)
            )
            if site.helper
        ]
        self.assertEqual(1, len(sites), sites)
        return sites[0]

    def _error(self, root, source):
        return self.mod._typed_pin_inspection_error(self._site(root, source), str(root))

    # ── Cause A: the unfreeze ──────────────────────────────────────────────
    def test_a_stem_loop_bundle_resolves_to_root_plus_one_member_per_stem(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            self.assertEqual(
                [
                    str(root / "skills/demo/SKILL.md"),
                    str(root / "skills/demo/phases/alpha.md"),
                    str(root / "skills/demo/phases/beta.md"),
                ],
                list(self._members(root, self.STEM_BUILD)["BUNDLE"]),
                "membership is the stem list composed across BOTH word-list "
                "variables, in list order, and nothing else in the directory",
            )

    def test_typed_declaration_on_a_stem_loop_bundle_is_inspectable(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            site = self._site(root, self.STEM_BUILD + self._pin())
            self.assertIsNone(site.target_path)
            self.assertEqual(3, len(site.target_members))
            self.assertIsNone(self.mod._typed_pin_inspection_error(site, str(root)))

    def test_a_bare_loop_variable_reference_in_the_template_resolves_too(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            build = self.STEM_BUILD.replace(
                'phases/${_s}.md', 'phases/$_s.md'
            )
            self.assertEqual(3, len(self._members(root, build)["BUNDLE"]))

    # ── Cause A: the negative controls ─────────────────────────────────────
    def test_a_phase_file_no_stem_names_is_not_a_member(self):
        # The sharp form of the exactness claim: the loop enumerates the STEM
        # LIST, never the directory, so a sibling file is outside the bundle.
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            self.assertEqual(
                "typed structural declaration literal cannot be inspected "
                "(absent from target)",
                self._error(
                    root, self.STEM_BUILD + self._pin(literal=self.ORPHAN_LITERAL)
                ),
            )

    def test_an_unmodeled_stem_list_leaves_the_bundle_unresolved(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            for unmodeled in (
                'STEMS="$(cat stems.txt)"',   # command substitution
                'STEMS="$ROOT/skills/demo/phases/alpha.md"',  # a path, not a stem
                'STEMS="alpha* beta"',        # a glob word
                'STEMS="$UNKNOWN_LIST"',      # an unmodeled word-list variable
                'STEMS=""',                   # empty is never "resolved to nothing"
            ):
                build = self.STEM_BUILD.replace(
                    'STEMS="$DEFAULT_STEMS $GATED_STEMS"', unmodeled
                )
                with self.subTest(unmodeled):
                    self.assertNotIn("BUNDLE", self._members(root, build))
                    self.assertEqual(
                        "typed structural declaration target cannot be inspected",
                        self._error(root, build + self._pin()),
                    )

    def test_a_reassigned_stem_list_leaves_the_bundle_unresolved(self):
        # The word-list map is a whole-source final state read at every loop, so a
        # name that is not the same list everywhere cannot answer for one.
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            build = self.STEM_BUILD.replace(
                'devflow_module_build_bundle',
                'STEMS="alpha"\ndevflow_module_build_bundle',
            )
            self.assertNotIn("BUNDLE", self._members(root, build))

    def test_a_template_that_does_not_resolve_leaves_the_bundle_unresolved(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            build = self.STEM_BUILD.replace(
                '"$ROOT/skills/demo/phases/${_s}.md"',
                '"$UNKNOWN_ROOT/skills/demo/phases/${_s}.md"',
            )
            self.assertNotIn("BUNDLE", self._members(root, build))

    def test_a_basename_skip_is_not_composed_with_a_template(self):
        # The skip filters an EXPANDED GLOB; there is no evidence for what it
        # should mean over a stem list, so the loop stays unresolved rather than
        # resolving to a set the filter may not really describe.
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            build = self.STEM_BUILD.replace(
                '  _members+=("$ROOT/skills/demo/phases/${_s}.md")\n',
                '  case "${_s##*/}" in alpha) continue ;; esac\n'
                '  _members+=("$ROOT/skills/demo/phases/${_s}.md")\n',
            )
            self.assertNotIn("BUNDLE", self._members(root, build))

    def test_an_unmodeled_statement_in_a_stem_loop_body_still_poisons(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            build = self.STEM_BUILD.replace(
                '  _members+=("$ROOT/skills/demo/phases/${_s}.md")\n',
                '  printf "%s\\n" "$_s"\n'
                '  _members+=("$ROOT/skills/demo/phases/${_s}.md")\n',
            )
            self.assertNotIn("BUNDLE", self._members(root, build))

    def test_a_missing_templated_member_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            (root / "skills/demo/phases/beta.md").unlink()
            self.assertEqual(
                "typed structural declaration target cannot be inspected "
                "(FileNotFoundError)",
                self._error(root, self.STEM_BUILD + self._pin()),
            )

    # ── Cause B: the comment-suffixed alias ────────────────────────────────
    def test_a_comment_suffixed_alias_resolves_to_its_source_bundle(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            source = self.STEM_BUILD + 'ALIAS="$BUNDLE"   # #1008: annotated alias\n'
            resolved = self._members(root, source)
            self.assertEqual(list(resolved["BUNDLE"]), list(resolved["ALIAS"]))

    def test_a_pin_on_a_comment_suffixed_alias_is_inspectable(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            source = (
                self.STEM_BUILD
                + 'ALIAS="$BUNDLE"   # #1008: annotated alias\n'
                + self._pin(target="$ALIAS")
            )
            self.assertIsNone(self._error(root, source))

    def test_a_hash_that_is_not_a_trailing_comment_is_not_a_false_alias(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td)
            for rhs in (
                '"$UNRELATED"   # this comment names $BUNDLE',
                '"one two # $BUNDLE"',
                '"$BUNDLE.md"',
            ):
                source = self.STEM_BUILD + f"ALIAS={rhs}\n"
                with self.subTest(rhs):
                    self.assertNotIn(
                        "ALIAS",
                        self._members(root, source),
                        "only a whole-token variable reference before the "
                        "comment may be read as an alias",
                    )


if __name__ == "__main__":
    unittest.main()
