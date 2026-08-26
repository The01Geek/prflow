#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Unit tests for the coverage-map ratchet guard (issue #591).

Each of the guard's arms is driven with a synthetic (tracked_files, map,
registry) fixture, following test_module_runner.py's fixture style. T-green
confirms the shipped tree + map passes; the named controls (T-planted, T-stale,
T-owner, T-shape, T-shape-registry, T-extension, T-subdir, T-misfile) each prove
the arm records a FAIL naming the offending path/entry."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
GUARD_SOURCE = HERE / "coverage_map_guard.py"

_spec = importlib.util.spec_from_file_location("coverage_map_guard", GUARD_SOURCE)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def _map(files=None, non_code_exempt=None, exempt_subtrees=None, run_sh_blocks=None):
    return {
        "schema_version": 1,
        "generated_by": "python3 -c '...'",
        "exempt_subtrees": ["lib/test/"] if exempt_subtrees is None else exempt_subtrees,
        "non_code_exempt": [] if non_code_exempt is None else non_code_exempt,
        "files": {} if files is None else files,
        "run_sh_blocks": {"unlabeled": {"owner": "unmodularized", "note": ""}}
        if run_sh_blocks is None
        else run_sh_blocks,
    }


def _registry(ids=("capability-profiles",)):
    return {"schema_version": 1, "test_modules": {i: {"path": f"lib/test/modules/{i}.sh"} for i in ids}}


def _owned(owner="unmodularized"):
    return {"owner": owner, "note": ""}


class CoverageMapGuardTest(unittest.TestCase):
    def _arms(self, violations):
        return {v.split("]", 1)[0].lstrip("[") for v in violations}

    # ── T-green: the shipped tree + committed map + registry passes cleanly. ──
    def test_green_shipped_tree(self):
        map_value = json.loads((ROOT / guard.MAP_REL).read_text(encoding="utf-8"))
        registry_value = json.loads((ROOT / guard.REGISTRY_REL).read_text(encoding="utf-8"))
        # The argv is composed from the module under test's own `QUOTE_PATH_OFF` (issue
        # #1217) rather than a locally-spelled `git ls-files`: `_git_tracked` enumerates
        # unquoted, so a hardcoded quoted spelling here would build a population spelled
        # differently from the guard's for exactly the non-ASCII path class that fix
        # addresses, and the mode row would fail to join. Split on "\n" rather than
        # whitespace because a real path may contain spaces, which bare .split() would
        # shred into fragments.
        tracked = [
            line
            for line in subprocess.run(
                ["git", "-C", str(ROOT), *guard.QUOTE_PATH_OFF, "ls-files"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.split("\n")
            if line
        ]
        # `executable_files` is passed from the real index (issue #789) because arm 10's
        # unestablished-mode-set breadcrumb is a violation: omitting it here would grade the
        # shipped tree against a measurement that never ran.
        self.assertEqual(
            guard.evaluate(
                tracked,
                map_value,
                registry_value,
                executable_files=guard._git_executable(ROOT),
                # Issue #1078: the focused_test grants live in the union of the manifest
                # `implement` profile and .prflow/config.json's self-repo channel, exactly
                # as main() resolves them — a manifest-only read here would false-flag the
                # five moved targets.
                implement_tokens=guard._resolve_implement_grant_tokens(
                    guard._load_json(ROOT / guard.PROFILES_REL)[0],
                    guard._load_json(ROOT / guard.CONFIG_REL)[0],
                ),
            ),
            [],
        )

    # ── T-planted (arm 1): an unlisted depth-1 pattern unit records FAIL naming it. ──
    def test_planted_unlisted_depth1_unit(self):
        tracked = ["lib/newthing.sh"]
        v = guard.evaluate(tracked, _map(files={}), _registry())
        self.assertEqual(self._arms(v), {"arm1"})
        self.assertIn("lib/newthing.sh", v[0])

    # ── T-stale (arm 2): a map entry naming an untracked path records FAIL. ──
    def test_stale_untracked_files_entry(self):
        tracked = ["lib/real.sh"]
        v = guard.evaluate(tracked, _map(files={"lib/real.sh": _owned(), "lib/gone.sh": _owned()}), _registry())
        self.assertEqual(self._arms(v), {"arm2"})
        self.assertIn("lib/gone.sh", "".join(v))

    def test_stale_untracked_non_code_exempt_entry(self):
        tracked = ["lib/real.sh"]
        v = guard.evaluate(tracked, _map(files={"lib/real.sh": _owned()}, non_code_exempt=["lib/gone.json"]), _registry())
        self.assertEqual(self._arms(v), {"arm2"})
        self.assertIn("lib/gone.json", "".join(v))

    # ── T-owner (arm 3): an owner neither a registered id nor `unmodularized`. ──
    def test_owner_not_registered(self):
        tracked = ["lib/real.sh"]
        v = guard.evaluate(tracked, _map(files={"lib/real.sh": _owned("bogus-module")}), _registry())
        self.assertEqual(self._arms(v), {"arm3"})
        self.assertIn("bogus-module", "".join(v))

    def test_owner_registered_id_passes(self):
        tracked = ["lib/real.sh"]
        v = guard.evaluate(tracked, _map(files={"lib/real.sh": _owned("capability-profiles")}), _registry())
        self.assertEqual(v, [])

    def test_owner_in_run_sh_blocks_checked(self):
        tracked = ["lib/real.sh"]
        blocks = {"561": _owned("bogus"), "unlabeled": _owned()}
        v = guard.evaluate(tracked, _map(files={"lib/real.sh": _owned()}, run_sh_blocks=blocks), _registry())
        self.assertEqual(self._arms(v), {"arm3"})

    # ── T-focused (arm 10, issue #789): the recorded `focused_test` of a files entry. ──
    # Five cases: absent (the ordinary entry — no arm 10 traffic), present+valid+executable,
    # present-but-untracked, present-but-wrong-basename, present-but-not-executable. Each
    # non-clean case must record arm10 ALONE, so the arm cannot be credited by another arm's
    # noise. `_focused` builds the entry; `EXEC` is the injected index-mode set.
    _EXEC = {"lib/test/test_thing.py"}
    # The grant set arm 10 checks alongside the exec bit: an executable-but-ungranted
    # target is refused by the cloud matcher SILENTLY, so the map would promise a
    # focused run that never happens. Injected exactly like _EXEC.
    _TOKENS = {"Bash(lib/test/test_thing.py:*)"}

    @staticmethod
    def _focused(target, owner="unmodularized"):
        return {"owner": owner, "note": "", "focused_test": target}

    def test_focused_test_absent_is_clean(self):
        tracked = ["lib/real.sh"]
        v = guard.evaluate(
            tracked, _map(files={"lib/real.sh": _owned()}), _registry(), executable_files=self._EXEC, implement_tokens=self._TOKENS
        )
        self.assertEqual(v, [])

    def test_focused_test_valid_executable_passes(self):
        tracked = ["lib/real.sh", "lib/test/test_thing.py"]
        v = guard.evaluate(
            tracked,
            _map(files={"lib/real.sh": self._focused("lib/test/test_thing.py")}),
            _registry(),
            executable_files=self._EXEC,
            implement_tokens=self._TOKENS,
        )
        self.assertEqual(v, [])

    def test_focused_test_selector_suffix_resolves_to_the_file(self):
        # A `path::Class.test` selector narrows the run; only the path before `::` names a
        # file, so a valid executable target with a selector must still pass.
        tracked = ["lib/real.sh", "lib/test/test_thing.py"]
        v = guard.evaluate(
            tracked,
            _map(files={"lib/real.sh": self._focused("lib/test/test_thing.py::Cls.test_x")}),
            _registry(),
            executable_files=self._EXEC,
            implement_tokens=self._TOKENS,
        )
        self.assertEqual(v, [])

    def test_focused_test_untracked_records_arm10(self):
        tracked = ["lib/real.sh"]
        v = guard.evaluate(
            tracked,
            _map(files={"lib/real.sh": self._focused("lib/test/test_gone.py")}),
            _registry(),
            executable_files=self._EXEC,
            implement_tokens=self._TOKENS,
        )
        self.assertEqual(self._arms(v), {"arm10"})
        self.assertIn("lib/test/test_gone.py", "".join(v))

    def test_focused_test_wrong_basename_records_arm10(self):
        tracked = ["lib/real.sh", "lib/test/helper.py"]
        v = guard.evaluate(
            tracked,
            _map(files={"lib/real.sh": self._focused("lib/test/helper.py")}),
            _registry(),
            executable_files={"lib/test/helper.py"},
            implement_tokens={"Bash(lib/test/helper.py:*)"},
        )
        self.assertEqual(self._arms(v), {"arm10"})
        self.assertIn("lib/test/helper.py", "".join(v))

    def test_focused_test_not_executable_records_arm10(self):
        tracked = ["lib/real.sh", "lib/test/test_thing.py"]
        v = guard.evaluate(
            tracked,
            _map(files={"lib/real.sh": self._focused("lib/test/test_thing.py")}),
            _registry(),
            executable_files=set(),
            implement_tokens=self._TOKENS,
        )
        self.assertEqual(self._arms(v), {"arm10"})
        self.assertIn("not executable in the git index", "".join(v))

    def test_focused_test_unestablished_mode_set_is_reported_once_not_laundered(self):
        # `executable_files=None` is an UNESTABLISHED measurement, never "executable" and
        # never "absent": exactly one breadcrumb, and no per-entry executability claim.
        tracked = ["lib/real.sh", "lib/test/test_thing.py"]
        v = guard.evaluate(
            tracked,
            _map(files={"lib/real.sh": self._focused("lib/test/test_thing.py")}),
            _registry(),
            executable_files=None,
            implement_tokens=self._TOKENS,
        )
        self.assertEqual(self._arms(v), {"arm10"})
        self.assertEqual(len(v), 1)
        self.assertIn("could not be established", v[0])

    def test_focused_test_non_string_is_a_shape_error(self):
        tracked = ["lib/real.sh"]
        entry = {"owner": "unmodularized", "note": "", "focused_test": 7}
        v = guard.evaluate(
            tracked, _map(files={"lib/real.sh": entry}), _registry(), executable_files=self._EXEC, implement_tokens=self._TOKENS
        )
        self.assertEqual(self._arms(v), {"arm4"})
        self.assertIn("focused_test", "".join(v))

    def test_focused_test_without_an_implement_grant_records_arm10(self):
        # Executable and tracked is only HALF of cloud-runnability: an ungranted leading
        # token is refused SILENTLY, so the map would record a focused run that produces no
        # signal there. This is the fail-open the grant check closes.
        tracked = ["lib/real.sh", "lib/test/test_thing.py"]
        v = guard.evaluate(
            tracked,
            _map(files={"lib/real.sh": self._focused("lib/test/test_thing.py")}),
            _registry(),
            executable_files=self._EXEC,
            implement_tokens=set(),
        )
        self.assertEqual(self._arms(v), {"arm10"})
        self.assertIn("carries no `Bash(lib/test/test_thing.py:*)` grant", "".join(v))

    def test_unestablished_implement_tokens_are_reported_once_not_laundered(self):
        # Same "unknown is not zero" discipline as the mode set: a manifest that could not be
        # read is reported as unestablished, never as an absent grant on every entry.
        tracked = ["lib/real.sh", "lib/test/test_thing.py"]
        v = guard.evaluate(
            tracked,
            _map(files={"lib/real.sh": self._focused("lib/test/test_thing.py")}),
            _registry(),
            executable_files=self._EXEC,
            implement_tokens=None,
        )
        self.assertEqual(self._arms(v), {"arm10"})
        self.assertEqual(len(v), 1)
        self.assertIn("token list could not be established", v[0])

    def test_present_but_empty_focused_test_records_arm10(self):
        # A truthiness-keyed scan would treat "" as absent and ship an entry naming nothing
        # while the docs describe it as naming a runnable test.
        tracked = ["lib/real.sh"]
        entry = {"owner": "unmodularized", "note": "", "focused_test": "   "}
        v = guard.evaluate(
            tracked,
            _map(files={"lib/real.sh": entry}),
            _registry(),
            executable_files=self._EXEC,
            implement_tokens=self._TOKENS,
        )
        self.assertEqual(self._arms(v), {"arm10"})
        self.assertIn("present-but-empty", "".join(v))

    def test_implement_profile_tokens_expands_group_references(self):
        # The manifest expresses shared runs as `@group`; a token granted through a group is
        # still granted, so resolving must expand one level or the check false-flags.
        manifest = {
            "groups": {"shared": ["Bash(lib/test/test_grouped.py:*)"]},
            "profiles": {"implement": ["@shared", "Bash(lib/test/test_direct.py:*)"]},
        }
        self.assertEqual(
            guard._implement_profile_tokens(manifest),
            {"Bash(lib/test/test_grouped.py:*)", "Bash(lib/test/test_direct.py:*)"},
        )

    def test_implement_profile_tokens_is_none_on_a_malformed_manifest(self):
        for bad in (None, [], {}, {"profiles": {}}, {"profiles": {"implement": "x"}, "groups": {}}):
            self.assertIsNone(guard._implement_profile_tokens(bad), bad)

    def test_config_implement_tokens_reads_the_self_repo_grant_channel(self):
        # Issue #1078: focused_test grants moved out of the shipped `implement` profile into
        # .prflow/config.json's prflow_implement.allowed_tools (the self-repo channel).
        cfg = {"prflow_implement": {"allowed_tools": [
            "Bash(lib/test/test_python_scripts.py:*)", "Bash(shellcheck:*)"]}}
        self.assertEqual(
            guard._config_implement_tokens(cfg),
            {"Bash(lib/test/test_python_scripts.py:*)", "Bash(shellcheck:*)"},
        )

    def test_config_implement_tokens_is_none_on_a_malformed_config(self):
        for bad in (None, [], {}, {"prflow_implement": {}},
                    {"prflow_implement": {"allowed_tools": "x"}}):
            self.assertIsNone(guard._config_implement_tokens(bad), bad)

    def test_resolve_implement_grant_tokens_unions_manifest_and_config(self):
        # Issue #1078: arm 10 honors a grant from EITHER channel. A focused_test granted
        # only via config (its manifest grant removed) must resolve as granted.
        manifest = {"groups": {}, "profiles": {"implement": ["Bash(python3:*)"]}}
        config = {"prflow_implement": {"allowed_tools": ["Bash(lib/test/test_python_scripts.py:*)"]}}
        self.assertEqual(
            guard._resolve_implement_grant_tokens(manifest, config),
            {"Bash(python3:*)", "Bash(lib/test/test_python_scripts.py:*)"},
        )
        # None ONLY when NEITHER channel can be established — one readable channel suffices.
        self.assertEqual(
            guard._resolve_implement_grant_tokens(None, config),
            {"Bash(lib/test/test_python_scripts.py:*)"},
        )
        # The consumer-protecting direction: manifest established but config unreadable must
        # NOT false-flag a manifest-granted token — it returns the manifest set, never None.
        self.assertEqual(
            guard._resolve_implement_grant_tokens(manifest, None),
            {"Bash(python3:*)"},
        )
        self.assertIsNone(guard._resolve_implement_grant_tokens(None, None))

    def test_config_implement_tokens_breadcrumbs_a_present_but_wrong_typed_channel(self):
        # F2: a valid-JSON but wrong-typed grant channel is invisible to _load_json, so it
        # must not vanish silently (best-effort-parser: a specific breadcrumb per bad shape).
        import contextlib
        import io
        for bad, needle in (
            ({"prflow_implement": "oops"}, "'prflow_implement' is present but not a JSON object"),
            ({"prflow_implement": {"allowed_tools": "x"}}, "'prflow_implement.allowed_tools' is present but not a JSON array"),
        ):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertIsNone(guard._config_implement_tokens(bad))
            self.assertIn(needle, err.getvalue())
        # A legitimately-ABSENT key is silent (a consumer ships the channel empty) — no breadcrumb.
        for absent in ({}, {"prflow_implement": {}}):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertIsNone(guard._config_implement_tokens(absent))
            self.assertEqual(err.getvalue(), "")

    def test_config_only_grant_satisfies_arm10(self):
        # The end-to-end #1078 case: a focused_test whose grant lives ONLY in the config
        # channel passes arm 10 (no violation), proving the union closes the false-flag the
        # manifest-only check would otherwise raise for the five moved targets.
        tracked = ["lib/real.sh", "lib/test/test_thing.py"]
        grant = guard._resolve_implement_grant_tokens(
            {"groups": {}, "profiles": {"implement": ["Bash(python3:*)"]}},
            {"prflow_implement": {"allowed_tools": ["Bash(lib/test/test_thing.py:*)"]}},
        )
        v = guard.evaluate(
            tracked,
            _map(files={"lib/real.sh": self._focused("lib/test/test_thing.py")}),
            _registry(),
            executable_files=self._EXEC,
            implement_tokens=grant,
        )
        self.assertEqual(v, [])

    def test_unestablished_breadcrumbs_are_emitted_ONCE_over_MULTIPLE_entries(self):
        # Cardinality: with a single recorded entry, "once per run" and "once per entry" are
        # indistinguishable, so the guarded property would be vacuously satisfied. Two entries
        # is the smallest input that can tell them apart.
        tracked = ["lib/a.sh", "lib/b.sh", "lib/test/test_thing.py"]
        files = {
            "lib/a.sh": self._focused("lib/test/test_thing.py"),
            "lib/b.sh": self._focused("lib/test/test_thing.py"),
        }
        for kwargs in ({"executable_files": None, "implement_tokens": self._TOKENS},
                       {"executable_files": self._EXEC, "implement_tokens": None}):
            v = guard.evaluate(tracked, _map(files=files), _registry(), **kwargs)
            self.assertEqual(self._arms(v), {"arm10"}, kwargs)
            self.assertEqual(len(v), 1, f"expected ONE breadcrumb over two entries: {v}")

    def test_multiple_bad_entries_each_report_in_sorted_order(self):
        # The per-entry arm must scale with cardinality (one finding each) and be
        # deterministic — `_arm10` iterates `sorted(files)`, which one entry never exercises.
        tracked = ["lib/b.sh", "lib/a.sh"]
        files = {
            "lib/b.sh": self._focused("lib/test/test_gone_b.py"),
            "lib/a.sh": self._focused("lib/test/test_gone_a.py"),
        }
        v = guard.evaluate(
            tracked, _map(files=files), _registry(),
            executable_files=self._EXEC, implement_tokens=self._TOKENS,
        )
        self.assertEqual(len(v), 2, v)
        self.assertIn("'lib/a.sh'", v[0])
        self.assertIn("'lib/b.sh'", v[1])


    # ── T-shape (arm 4): the six governing shapes over the MAP input. ──
    def test_shape_matrix_map(self):
        tracked = ["lib/real.sh"]
        reg = _registry()
        # valid object → passes (arm 1 fires because files is empty, proving valid-falsy is non-vacuous)
        v = guard.evaluate(tracked, _map(files={"lib/real.sh": _owned()}), reg)
        self.assertEqual(v, [])
        # array
        self.assertEqual(self._arms(guard.evaluate(tracked, [], reg)), {"arm4"})
        # scalar
        self.assertEqual(self._arms(guard.evaluate(tracked, 7, reg)), {"arm4"})
        # valid-falsy: files:{} is a LEGAL shape whose emptiness makes every unit
        # unlisted — must NOT pass vacuously (arm 1, not arm 4).
        self.assertEqual(self._arms(guard.evaluate(tracked, _map(files={}), reg)), {"arm1"})
        # missing file (read error)
        self.assertEqual(
            self._arms(guard.evaluate(tracked, None, reg, map_read_error="coverage-map.json not found")),
            {"arm4"},
        )
        # wrong-type value: files not a dict
        bad = _map()
        bad["files"] = ["lib/real.sh"]
        self.assertEqual(self._arms(guard.evaluate(tracked, bad, reg)), {"arm4"})
        # wrong-type value: an entry owner not a string
        bad2 = _map(files={"lib/real.sh": {"owner": 7, "note": ""}})
        self.assertEqual(self._arms(guard.evaluate(tracked, bad2, reg)), {"arm4"})

    def test_shape_map_breadcrumb_names_file_and_remedy(self):
        v = guard.evaluate(["lib/real.sh"], [], _registry())
        self.assertTrue(any(guard.MAP_REL in line and "CONTRIBUTING" in line for line in v))

    # ── T-shape-registry (arm 8): the six governing shapes over the REGISTRY input. ──
    def test_shape_matrix_registry(self):
        tracked = ["lib/real.sh"]
        m = _map(files={"lib/real.sh": _owned()})
        # valid object
        self.assertEqual(guard.evaluate(tracked, m, _registry()), [])
        # array
        self.assertIn("arm8", self._arms(guard.evaluate(tracked, m, [])))
        # scalar
        self.assertIn("arm8", self._arms(guard.evaluate(tracked, m, 7)))
        # valid-falsy: test_modules:{} — a legal empty object; owners default to
        # unmodularized so no owner fails, and an empty id-set is a valid shape (arm 8
        # keys on non-object, not on emptiness).
        self.assertEqual(guard.evaluate(tracked, m, {"schema_version": 1, "test_modules": {}}), [])
        # missing file (read error)
        self.assertIn(
            "arm8",
            self._arms(guard.evaluate(tracked, m, None, registry_read_error="registry not found")),
        )
        # wrong-type: test_modules not an object
        self.assertIn("arm8", self._arms(guard.evaluate(tracked, m, {"test_modules": ["x"]})))

    def test_shape_registry_breadcrumb_names_registry(self):
        v = guard.evaluate(["lib/real.sh"], _map(files={"lib/real.sh": _owned()}), {"test_modules": 3})
        self.assertTrue(any(guard.REGISTRY_REL in line for line in v))

    # ── T-extension (arm 5): a depth-1 code file of an out-of-set extension. ──
    def test_extension_scripts_jq_ratcheted(self):
        tracked = ["scripts/x.jq"]
        v = guard.evaluate(tracked, _map(files={}), _registry())
        self.assertEqual(self._arms(v), {"arm5"})
        self.assertIn("scripts/x.jq", "".join(v))
        # the hint steers to extending the pattern set, not to non_code_exempt
        self.assertIn("pattern set", "".join(v))

    def test_non_pattern_non_code_depth1_needs_non_code_exempt(self):
        tracked = ["lib/data.json"]
        # absent from non_code_exempt → arm5
        self.assertEqual(self._arms(guard.evaluate(tracked, _map(), _registry())), {"arm5"})
        # listed → clean
        self.assertEqual(guard.evaluate(tracked, _map(non_code_exempt=["lib/data.json"]), _registry()), [])

    # ── T-subdir (arm 6): a code file in a new subtree outside exempt_subtrees. ──
    def test_subdir_code_file_ratcheted(self):
        tracked = ["scripts/hooks/deploy.sh"]
        v = guard.evaluate(tracked, _map(), _registry())
        self.assertEqual(self._arms(v), {"arm6"})
        self.assertIn("scripts/hooks/deploy.sh", "".join(v))

    def test_subdir_under_exempt_subtree_passes(self):
        tracked = ["lib/test/run.sh", "lib/test/modules/x.sh"]
        self.assertEqual(guard.evaluate(tracked, _map(), _registry()), [])

    # ── T-misfile (arm 7): a code unit misfiled into non_code_exempt. ──
    def test_misfile_code_in_non_code_exempt(self):
        tracked = ["scripts/x.sh"]
        # scripts/x.sh IS a pattern unit, so if it's only in non_code_exempt it also
        # trips arm1 (absent from files) AND arm7 (code ext in non_code_exempt).
        v = guard.evaluate(tracked, _map(non_code_exempt=["scripts/x.sh"]), _registry())
        self.assertIn("arm7", self._arms(v))
        self.assertIn("scripts/x.sh", "".join(line for line in v if line.startswith("[arm7]")))

    # ── Never raises on the fail-closed paths (arm 4 / arm 8 read errors). ──
    def test_both_inputs_unreadable_fails_closed_no_raise(self):
        v = guard.evaluate([], None, None, map_read_error="m gone", registry_read_error="r gone")
        arms = self._arms(v)
        self.assertIn("arm4", arms)
        self.assertIn("arm8", arms)

    # ── Arm 4 sub-shape controls: each structural guard in _map_shape_error fires. ──
    def test_shape_matrix_map_subshapes(self):
        tracked = ["lib/real.sh"]
        reg = _registry()

        def mutated(**overrides):
            m = _map(files={"lib/real.sh": _owned()})
            m.update(overrides)
            return m

        cases = [
            mutated(schema_version=2),  # schema_version != 1
            mutated(schema_version=True),  # bool is an int subclass; True == 1 must NOT pass
            mutated(run_sh_blocks=[]),  # run_sh_blocks not a dict
            mutated(run_sh_blocks={"561": {"owner": 7, "note": ""}}),  # non-string owner
            mutated(non_code_exempt=[7]),  # non_code_exempt non-string item
            mutated(exempt_subtrees=[7]),  # exempt_subtrees non-string item
            mutated(generated_by=7),  # generated_by not a string
        ]
        for m in cases:
            self.assertEqual(self._arms(guard.evaluate(tracked, m, reg)), {"arm4"})

    # ── Arm 3 registry-unavailable suppression: a wrong-shape registry records arm 8 only,
    # and does NOT double-report arm 3 on an owner that would otherwise be invalid. ──
    def test_arm3_suppressed_when_registry_unreadable(self):
        tracked = ["lib/real.sh"]
        m = _map(files={"lib/real.sh": _owned("would-be-invalid")})
        # wrong-shape registry (test_modules non-object) → arm8, arm3 suppressed
        self.assertEqual(self._arms(guard.evaluate(tracked, m, {"test_modules": ["x"]})), {"arm8"})
        # registry read error → same suppression
        self.assertEqual(
            self._arms(guard.evaluate(tracked, m, None, registry_read_error="gone")), {"arm8"}
        )

    # ── Cardinality: a violation loop names EVERY offender, not just the first (a `break`
    # regression would still pass a set-keyed assertion). ──
    def test_arm1_reports_every_offender(self):
        tracked = ["lib/one.sh", "lib/two.sh"]
        v = guard.evaluate(tracked, _map(files={}), _registry())
        self.assertEqual(self._arms(v), {"arm1"})
        joined = "".join(v)
        self.assertIn("lib/one.sh", joined)
        self.assertIn("lib/two.sh", joined)

    # ── Arm 6 boundary: an exempt_subtrees entry without a trailing slash exempts its own
    # subtree but NOT a sibling sharing the prefix (lib/test exempts lib/test/x, not
    # lib/testfoo/x). ──
    def test_arm6_prefix_is_slash_bounded(self):
        tracked = ["lib/testfoo/x.sh"]
        # exempt entry "lib/test" (no slash) must NOT exempt lib/testfoo/x.sh
        v = guard.evaluate(tracked, _map(exempt_subtrees=["lib/test"]), _registry())
        self.assertEqual(self._arms(v), {"arm6"})
        # but it DOES exempt its own subtree
        self.assertEqual(guard.evaluate(["lib/test/x.sh"], _map(exempt_subtrees=["lib/test"]), _registry()), [])

    # ── CLI / IO layer: main() returns non-zero and prints the arm on a violating tree,
    # and _load_json produces (not just consumes) each read-error breadcrumb. ──
    def test_cli_main_and_load_json_error_arms(self):
        # _load_json error arms — the breadcrumbs arms 4/8 rely on are actually PRODUCED here.
        with tempfile.TemporaryDirectory() as d:
            dp = Path(d)
            self.assertEqual(guard._load_json(dp / "missing.json")[0], None)
            self.assertIn("not found", guard._load_json(dp / "missing.json")[1])
            bad = dp / "bad.json"
            bad.write_text("{ not json", encoding="utf-8")
            self.assertEqual(guard._load_json(bad)[0], None)
            self.assertIn("malformed JSON", guard._load_json(bad)[1])
            adir = dp / "adir.json"
            adir.mkdir()
            self.assertEqual(guard._load_json(adir)[0], None)  # a directory is unreadable, not parsed
        # main() negative control: a real git tree with a planted unlisted depth-1 unit +
        # a map that doesn't list it → rc 1 and the arm-1 line on stdout.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
            (root / "lib" / "test" / "modules").mkdir(parents=True)
            (root / "scripts").mkdir()
            (root / "lib" / "planted.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            (root / "lib" / "test" / "modules" / "coverage-map.json").write_text(
                json.dumps(_map(files={})), encoding="utf-8"
            )
            (root / "scripts" / "workflow-flight-recorder-registry.json").write_text(
                json.dumps(_registry()), encoding="utf-8"
            )
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = guard.main(["coverage_map_guard.py", str(root)])
            self.assertEqual(rc, 1)
            self.assertIn("lib/planted.sh", out.getvalue())
            self.assertIn("[arm1]", out.getvalue())

    def _min_guardable_tree(self, root):
        # A minimal git tree main() can run over cleanly (no arm-1/2/9 noise): the two
        # required JSON inputs present, no depth-1 lib/scripts code unit to list.
        (root / "lib" / "test" / "modules").mkdir(parents=True)
        (root / "scripts").mkdir()
        (root / "lib" / "test" / "modules" / "coverage-map.json").write_text(
            json.dumps(_map(files={})), encoding="utf-8"
        )
        (root / "scripts" / "workflow-flight-recorder-registry.json").write_text(
            json.dumps(_registry()), encoding="utf-8"
        )
        subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)

    def test_cli_main_surfaces_a_present_but_malformed_grant_channel(self):
        # issue #1078: main() must surface a present-but-unparseable capability-profiles.json
        # / .prflow/config.json rather than discarding the _load_json error half (which would
        # misdirect arm10's "add the token to the config channel" remedy at an unusable file).
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._min_guardable_tree(root)
            (root / "lib" / "capability-profiles.json").write_text("{ not json", encoding="utf-8")
            (root / ".prflow").mkdir()
            (root / ".prflow" / "config.json").write_text("{ not json", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                guard.main(["coverage_map_guard.py", str(root)])
            text = out.getvalue()
            self.assertEqual(text.count("its cloud implement grant tokens were not read"), 2, text)
            self.assertIn("capability-profiles.json", text)
            self.assertIn("config.json", text)

    def test_cli_main_is_silent_on_a_legitimately_absent_grant_channel(self):
        # The exists()-gate: an absent optional file (a consumer/fixture that ships neither
        # file) must NOT produce a spurious breadcrumb — the union already fails closed.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._min_guardable_tree(root)  # no capability-profiles.json, no .prflow/config.json
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                guard.main(["coverage_map_guard.py", str(root)])
            self.assertNotIn("its cloud implement grant tokens were not read", out.getvalue())

    # ── main() fail-closed git branch: git ls-files failing → rc 1 + the named
    # breadcrumb (the only advertised fail-closed arm without a positive control).
    # Point main() at a non-existent directory under a fresh tempdir so `git -C <path>`
    # fails deterministically (cannot chdir) — independent of any ambient repo around
    # the test's cwd. Assert the breadcrumb, not just rc, so a silenced branch is caught.
    def test_cli_main_git_failure_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            missing = Path(d) / "no-such-dir"
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = guard.main(["coverage_map_guard.py", str(missing)])
            self.assertEqual(rc, 1)
            self.assertIn("[input-error]", out.getvalue())
            self.assertIn("git ls-files failed", out.getvalue())



# ── issue #695: arm 9 (run_sh_blocks completeness + fully-extracted attribution),
# the shared label derivation, and the hand-invoked --fix repair. ──────────────
class GitExecutableTest(unittest.TestCase):
    """`_git_executable` is the PRODUCER of arm 10's mode set, including the `None` that the
    whole unestablished-measurement design rests on. Driving it only through the shipped-tree
    test would leave that contract asserted by no test that can fail for the right reason."""

    def test_returns_none_when_git_cannot_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Not a git repository → CalledProcessError → the unestablished contract.
            self.assertIsNone(guard._git_executable(Path(tmp) / "definitely-absent"))

    def test_selects_only_the_executable_regular_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "plain.py").write_text("x", encoding="utf-8")
            exe = root / "runnable.py"
            exe.write_text("x", encoding="utf-8")
            exe.chmod(0o755)
            for args in (["init", "-q"], ["add", "-A"]):
                subprocess.run(["git", "-C", str(root), *args], check=True,
                               capture_output=True)
            found = guard._git_executable(root)
            self.assertEqual(found, {"runnable.py"}, found)


class LabelDerivationTest(unittest.TestCase):
    def test_derives_from_the_monolith_assertion_heads(self):
        text = 'assert_eq "#123 something" "1" "$x"\nassert_true "#124 other" yes\n'
        self.assertEqual(guard.derive_labels(text), {"123", "124"})

    def test_every_pin_corpus_lint_helper_is_a_recognized_derivation_head(self):
        # lib/test/pin-corpus-lint.py keeps its own HELPERS table of assertion helpers
        # over the SAME two corpora (lib/test/run.sh + lib/test/modules/*.sh). A helper
        # added there but not here makes arm 9 silently under-derive labels — a clean
        # pass on real drift, in a guard whose entire job is completeness. Couple the
        # two tables so that drift is RED instead. (Imported by path: the linter's
        # filename is hyphenated, so it is not importable as a module name.)
        lint_spec = importlib.util.spec_from_file_location(
            "pin_corpus_lint", HERE / "pin-corpus-lint.py"
        )
        lint = importlib.util.module_from_spec(lint_spec)
        lint_spec.loader.exec_module(lint)
        live_helpers = set(lint.HELPERS) - set(lint.MUTATION_TAKING_HELPERS)
        missing = sorted(live_helpers - set(guard._BASE_ASSERTION_HEADS))
        self.assertEqual(
            missing,
            [],
            "live pin-corpus-lint.py HELPERS the label derivation does not recognize: "
            f"{missing} — add them to _BASE_ASSERTION_HEADS",
        )

    def test_derives_from_the_namespaced_harness_api(self):
        text = (
            'devflow_module_pin_unique "#201 a" \'lit\' "$F"\n'
            'devflow_module_pin_present "#203 c" \'lit\' "$F"\n'
        )
        self.assertEqual(guard.derive_labels(text), {"201", "203"})

    def test_derives_from_a_module_private_assertion_wrapper(self):
        # The head-coverage criterion: a wrapper around assert_eq must be discovered,
        # or converting a call to the namespaced API/a wrapper makes the label vanish.
        text = (
            "_mod_pin() {\n"
            '  assert_eq "$1" "1" "$2"\n'
            "}\n"
            '_mod_pin "#301 through a private wrapper" "$v"\n'
        )
        self.assertEqual(guard.derive_labels(text), {"301"})

    def test_derives_from_a_wrapper_around_a_wrapper(self):
        text = (
            "_inner() {\n"
            '  assert_eq "$1" "a" "$2"\n'
            "}\n"
            "_outer() {\n"
            '  _inner "$1" "$2"\n'
            "}\n"
            '_outer "#302 nested wrapper" "$v"\n'
        )
        self.assertEqual(guard.derive_labels(text), {"302"})

    def test_an_assertion_name_may_carry_two_labels(self):
        text = 'assert_eq "#401 and #402 together" "1" "$x"\n'
        self.assertEqual(guard.derive_labels(text), {"401", "402"})

    def test_a_label_in_a_comment_is_not_derived(self):
        text = '# see issue #999 for history\nassert_eq "#501 real" "1" "$x"\n'
        self.assertEqual(guard.derive_labels(text), {"501"})

    def test_a_label_in_a_non_name_quoted_string_is_not_derived(self):
        # Anchored on name POSITION: a #NNN inside a later argument is not a label.
        text = 'assert_eq "#601 real" "1" "$(grep -c \'#997 prose\' "$F")"\n'
        self.assertEqual(guard.derive_labels(text), {"601"})

    def test_a_bare_label_token_outside_any_assertion_is_not_derived(self):
        self.assertEqual(guard.derive_labels('X="#998 just a string"\n'), set())

    def test_a_one_line_command_stub_is_not_promoted_to_an_assertion_head(self):
        # lib/test/run.sh shadows commands inside subshells with one-line stubs
        # (`mktemp() { return 1; }`, `sed() { return 2; }`). A body-extractor that only
        # looks for a `}` on its OWN line hands such a stub the surrounding real
        # assertions as its "body", promotes `sed`/`mktemp` to an assertion head, and
        # then derives a bogus label from any ordinary `sed \'s/#604/#609/\'` argument.
        # The trailing real wrapper is load-bearing: if a one-line stub's body were
        # allowed to bleed to the remainder of the file, it would swallow this
        # forwarding call and BE promoted. Without it the assertions below cannot
        # fail even with the carve-out removed — vacuous.
        text = (
            "  sed() { return 2; }\n"
            "  mktemp() { return 1; }\n"
            'assert_eq "#700 the real assertion" "1" "1"\n'
            "sed 's/#604/#609/' \"$F\" > \"$G\"\n"
            "_real_wrapper() {\n"
            '  assert_eq "$1" "a" "$2"\n'
            "}\n"
        )
        self.assertEqual(guard.derive_labels(text), {"700"})
        # _assertion_heads takes the SPLIT lines; passing the raw string iterates
        # characters, so bodies comes back empty and both assertions below pass
        # vacuously — including under a broken _function_bodies.
        heads = guard._assertion_heads(text.split("\n"))
        self.assertNotIn("sed", heads)
        self.assertNotIn("mktemp", heads)

    def test_a_wrapper_must_forward_its_own_first_positional(self):
        # A function that merely CONTAINS an assertion head is not a wrapper; only one
        # that forwards "$1"/"$@" into the head's name slot is.
        forwarding = "_w() {\n  assert_eq \"$1\" \"a\" \"$2\"\n}\n_w \"#701 forwarded\" x\n"
        self.assertEqual(guard.derive_labels(forwarding), {"701"})
        literal = "_v() {\n  assert_eq \"a fixed name\" \"a\" \"$1\"\n}\n_v \"#702 not a name\"\n"
        self.assertEqual(guard.derive_labels(literal), set())

    def test_a_wrapper_may_forward_through_a_local_variable_hop(self):
        # lib/test/modules/capability-profiles.sh's `_cap_fail` opens
        # `local name="$1" mut="$2" …` and then calls `assert_eq "$name" …`. Matching only
        # the literal "$1" misses that hop, leaving every label a module asserts SOLELY
        # through such a wrapper underived — a vacuous completeness guarantee.
        text = (
            "_hop() {\n"
            '  local name="$1" other="$2"\n'
            '  assert_eq "$name" "yes" "$other"\n'
            "}\n"
            '_hop "#703 through a local-variable hop" x\n'
        )
        self.assertEqual(guard.derive_labels(text), {"703"})
        self.assertIn("_hop", guard._assertion_heads(text.split("\n")))

    def test_the_shipped_cap_fail_wrapper_is_discovered(self):
        # The concrete instance the rule above exists for, pinned against the real module
        # so a future rewrite of either side is caught.
        module = (ROOT / "lib/test/modules/capability-profiles.sh").read_text(encoding="utf-8")
        self.assertIn("_cap_fail", guard._assertion_heads(module.split("\n")))

    def test_a_name_argument_wrapped_by_a_line_continuation_is_derived(self):
        # _call_pattern's separator class admits `\`-continuation + newline so a call whose
        # name argument wraps to the next line is still anchored at name position. Nothing
        # else exercised the `\`/`\n` members of that class: the live users are self-
        # redundant (each label is also asserted single-line), so a future narrowing of the
        # separator to `[ \t]+` would silently under-derive without any unit test going RED.
        self.assertEqual(
            guard.derive_labels('assert_eq \\\n  "#801 wrapped name" "1" "1"\n'), {"801"}
        )

    def test_a_wrapper_forwarding_all_positionals_is_derived(self):
        # "$@" is a forwarding alias too: a wrapper that passes "$@" into an assertion head's
        # name slot must be discovered, or a label asserted solely through such a wrapper
        # underives. The literal-name control forwards "$@" but with a fixed name, so the
        # head is not in name position and no label is derived.
        forwarding = (
            "_wall() {\n"
            '  assert_eq "$@"\n'
            "}\n"
            '_wall "#802 forwarded via all-positionals" "1" "1"\n'
        )
        self.assertEqual(guard.derive_labels(forwarding), {"802"})
        self.assertIn("_wall", guard._assertion_heads(forwarding.split("\n")))

    def test_a_default_expansion_is_not_a_forwarding_alias(self):
        # `name="${1:-default}"` is a default expansion, not a straight pass-through of "$1",
        # so `name` must NOT be bound as a forwarding alias — otherwise a wrapper calling
        # `assert_eq "$name" …` would be treated as forwarding the first positional when it
        # is not. The bare "$1" and balanced "${1}" hop cases stay aliased (positive control).
        self.assertNotIn("name", guard._forwarding_aliases('local name="${1:-default}"\n'))
        self.assertIn("plain", guard._forwarding_aliases('local plain="$1"\n'))
        self.assertIn("braced", guard._forwarding_aliases('local braced="${1}"\n'))

    def test_a_source_deriving_zero_labels_is_an_empty_set(self):
        self.assertEqual(guard.derive_labels('assert_eq "no label here" "1" "1"\n'), set())

    def test_the_shipped_modules_each_derive_their_own_labels(self):
        # Every module carrying labelled assertions derives a non-empty set containing
        # each label it asserts (the criterion the retired generated_by scanner failed).
        module_labels = {}
        for path in sorted((ROOT / "lib/test/modules").glob("*.sh")):
            module_labels[path.stem] = guard.derive_labels(path.read_text(encoding="utf-8"))
        self.assertIn("561", module_labels["capability-profiles"])
        self.assertIn("619", module_labels["regenerate-artifacts"])
        self.assertGreaterEqual(len(module_labels["create-issue-contract"]), 15)
        # Exact, so adding a labelled assertion to installer-wiring.sh lands here too --
        # that coupling is the point. `1041` joined when the Tier 4 rename's withheld-tier
        # regression (the review toggle disabled under whichever spelling the config
        # carries) took its coverage in this module, alongside tier1-rename-migration
        # which carries the same label for the config-key migration itself.
        self.assertEqual(
            {"487", "491", "533", "544", "599", "690", "959", "970", "971", "1002", "1041", "1388", "1882", "1925", "1963"},
            module_labels["installer-wiring"],
        )


class Arm9Test(unittest.TestCase):
    def _violations(self, blocks, run_sh_labels, module_labels, **kwargs):
        return guard.evaluate(
            [],
            _map(run_sh_blocks=blocks),
            _registry(ids=("mod-a", "mod-b")),
            run_sh_labels=run_sh_labels,
            module_labels=module_labels,
            **kwargs,
        )

    def _arm9(self, violations):
        return [v for v in violations if v.startswith("[arm9]")]

    # Happy path.
    def test_a_compliant_map_records_no_arm9_violation(self):
        blocks = {"100": _owned(), "200": _owned("mod-a"), "unlabeled": _owned()}
        self.assertEqual(
            self._arm9(self._violations(blocks, {"100"}, {"mod-a": {"200"}})), []
        )

    # Planted defect 1: a run.sh label with no entry.
    def test_a_run_sh_label_with_no_entry_is_reported(self):
        blocks = {"100": _owned()}
        found = self._arm9(self._violations(blocks, {"100", "101"}, {}))
        self.assertEqual(len(found), 1)
        self.assertIn("'101'", found[0])
        self.assertIn("has no coverage-map run_sh_blocks entry", found[0])

    # Planted defect 2: a fully-extracted label still marked unmodularized.
    def test_a_fully_extracted_label_owned_by_unmodularized_is_reported(self):
        blocks = {"200": _owned("unmodularized")}
        found = self._arm9(self._violations(blocks, set(), {"mod-a": {"200"}}))
        self.assertEqual(len(found), 1)
        self.assertIn("fully extracted into module(s) mod-a", found[0])
        self.assertIn("'unmodularized'", found[0])

    # Planted defect 3: a fully-extracted label whose entry is missing entirely.
    def test_a_fully_extracted_label_with_no_entry_is_reported(self):
        found = self._arm9(self._violations({}, set(), {"mod-a": {"200"}}))
        self.assertEqual(len(found), 1)
        self.assertIn("carried wholly by module(s) mod-a", found[0])

    # Planted defect 4: attributed to a module that does not carry the label.
    def test_a_fully_extracted_label_owned_by_a_non_carrier_is_reported(self):
        blocks = {"200": _owned("mod-b")}
        found = self._arm9(self._violations(blocks, set(), {"mod-a": {"200"}}))
        self.assertEqual(len(found), 1)
        self.assertIn("'mod-b'", found[0])

    # Negative control for the partial-extraction rule.
    def test_a_partially_extracted_label_marked_unmodularized_is_not_reported(self):
        blocks = {"487": _owned("unmodularized")}
        self.assertEqual(
            self._arm9(self._violations(blocks, {"487"}, {"mod-a": {"487"}})), []
        )

    def test_a_label_carried_by_two_modules_accepts_either_carrier(self):
        for owner in ("mod-a", "mod-b"):
            with self.subTest(owner=owner):
                blocks = {"200": _owned(owner)}
                self.assertEqual(
                    self._arm9(
                        self._violations(blocks, set(), {"mod-a": {"200"}, "mod-b": {"200"}})
                    ),
                    [],
                )

    def test_the_synthetic_unlabeled_key_is_exempt_from_both_checks(self):
        blocks = {"unlabeled": _owned()}
        self.assertEqual(
            self._arm9(
                self._violations(blocks, {"unlabeled"}, {"mod-a": {"unlabeled"}})
            ),
            [],
        )

    def test_an_empty_module_glob_reports_only_run_sh_completeness(self):
        blocks = {"100": _owned()}
        self.assertEqual(self._arm9(self._violations(blocks, {"100"}, {})), [])

    def test_a_map_with_only_the_unlabeled_key_still_reports_missing_run_sh_labels(self):
        found = self._arm9(self._violations({"unlabeled": _owned()}, {"100"}, {}))
        self.assertEqual(len(found), 1)
        self.assertIn("'100'", found[0])

    def test_no_attribution_violation_when_the_registry_yields_no_id_set(self):
        # Matches _valid_owner's stand-down: arm 8 already recorded the failure.
        violations = guard.evaluate(
            [],
            _map(run_sh_blocks={"200": _owned("unmodularized")}),
            {"schema_version": 1, "test_modules": "not-an-object"},
            run_sh_labels=set(),
            module_labels={"mod-a": {"200"}},
        )
        self.assertEqual(self._arm9(violations), [])
        self.assertIn("[arm8]", "".join(violations))

    def test_an_unreadable_source_is_reported_and_never_read_as_an_empty_set(self):
        violations = guard.evaluate(
            [],
            _map(run_sh_blocks={"200": _owned("unmodularized")}),
            _registry(ids=("mod-a",)),
            run_sh_labels=None,
            module_labels=None,
            scan_read_errors=["lib/test/run.sh (boom)"],
        )
        found = self._arm9(violations)
        self.assertEqual(len(found), 1)
        self.assertIn("lib/test/run.sh (boom)", found[0])
        self.assertIn("NOT an empty label set", found[0])

    def test_an_unreadable_module_is_reported_alongside_the_derived_arm(self):
        violations = guard.evaluate(
            [],
            _map(run_sh_blocks={}),
            _registry(ids=("mod-a",)),
            run_sh_labels={"100"},
            module_labels={},
            scan_read_errors=["lib/test/modules/mod-a.sh (boom)"],
        )
        found = self._arm9(violations)
        self.assertEqual(len(found), 2)
        self.assertIn("mod-a.sh (boom)", found[0])
        self.assertIn("'100'", found[1])

    def test_attribution_stands_down_when_a_module_read_failed(self):
        # module_labels is knowingly INCOMPLETE when a module file could not be read, so
        # "fully extracted" cannot be established: a label the unreadable module carries
        # would read as run.sh-only. The run.sh-completeness half still runs.
        violations = guard.evaluate(
            [],
            _map(run_sh_blocks={"200": _owned("unmodularized")}),
            _registry(ids=("mod-a",)),
            run_sh_labels={"100"},
            module_labels={"mod-a": {"200"}},
            scan_read_errors=["lib/test/modules/mod-b.sh (boom)"],
        )
        found = self._arm9(violations)
        self.assertTrue(any("mod-b.sh (boom)" in v for v in found))
        self.assertTrue(any("'100'" in v for v in found))
        self.assertFalse(any("fully extracted" in v for v in found))

    def test_arm9_stands_down_when_no_derivation_is_injected(self):
        # The 35 pre-existing positional evaluate() call sites pass no derivation and
        # must keep passing — arm 9 has nothing to compare against and reports nothing.
        violations = guard.evaluate([], _map(run_sh_blocks={"100": _owned()}), _registry())
        self.assertEqual(self._arm9(violations), [])

    def test_arm4_shape_rejection_short_circuits_before_arm9(self):
        violations = guard.evaluate(
            [],
            {"schema_version": 1, "files": {}, "run_sh_blocks": "not-an-object",
             "non_code_exempt": [], "exempt_subtrees": [], "generated_by": "x"},
            _registry(),
            run_sh_labels={"100"},
            module_labels={},
        )
        self.assertEqual(self._arm9(violations), [])
        self.assertIn("[arm4]", "".join(violations))

    def test_run_sh_blocks_adversarial_shapes_are_rejected_by_arm4_not_arm9(self):
        for bad in ([], "scalar", 0, False, None, {"100": "not-an-object"},
                    {"100": {"owner": 7}}):
            with self.subTest(shape=repr(bad)):
                map_value = _map()
                map_value["run_sh_blocks"] = bad
                violations = guard.evaluate(
                    [], map_value, _registry(), run_sh_labels={"100"}, module_labels={}
                )
                self.assertEqual(self._arm9(violations), [])
                self.assertIn("[arm4]", "".join(violations))

    def test_two_runs_over_unchanged_inputs_yield_identical_violation_lists(self):
        blocks = {"100": _owned()}
        first = self._violations(blocks, {"100", "101"}, {"mod-a": {"200"}})
        second = self._violations(blocks, {"100", "101"}, {"mod-a": {"200"}})
        self.assertEqual(first, second)


class Arm11CanonicalFormTest(unittest.TestCase):
    """Arm 11 (issue #1065): the map on disk is byte-identical to its canonical form."""

    def _arm11(self, violations):
        return [v for v in violations if v.startswith("[arm11]")]

    def _evaluate(self, map_value, **kwargs):
        # A minimal clean-elsewhere fixture so only arm 11 can speak: no tracked units,
        # a registry that yields an id set, and the map's own default run_sh_blocks.
        return guard.evaluate([], map_value, _registry(), **kwargs)

    def test_a_canonical_map_records_no_arm11_violation(self):
        m = _map(files={})
        canonical = guard._serialize_map(m)
        self.assertEqual(self._arm11(self._evaluate(m, map_raw_text=canonical)), [])

    def test_key_order_drift_with_an_unchanged_value_is_reported(self):
        # The measurement-3 case: the parsed JSON value is identical, only the serialized
        # key order differs — every presence/ownership arm passes, so arm 11 is the only
        # thing that can catch it.
        m = _map(run_sh_blocks={"126": _owned(), "139": _owned(), "unlabeled": _owned()})
        drift = json.dumps(
            {
                "schema_version": m["schema_version"],
                "generated_by": m["generated_by"],
                "files": m["files"],
                # reversed key order in run_sh_blocks; dict value is unchanged
                "run_sh_blocks": {"unlabeled": _owned(), "139": _owned(), "126": _owned()},
                "non_code_exempt": m["non_code_exempt"],
                "exempt_subtrees": m["exempt_subtrees"],
            },
            indent=2,
            sort_keys=False,
            ensure_ascii=False,
        ) + "\n"
        self.assertNotEqual(drift, guard._serialize_map(m))
        found = self._arm11(self._evaluate(m, map_raw_text=drift))
        self.assertEqual(len(found), 1)
        self.assertIn("not in canonical serialized form", found[0])
        self.assertIn(guard.MAP_REL, found[0])

    def test_formatting_drift_is_reported(self):
        # Compact (no-indent) bytes of the SAME value are non-canonical too — arm 11
        # covers whitespace/indent, not only key order.
        m = _map(files={})
        compact = json.dumps(m, sort_keys=True, ensure_ascii=False)  # no indent, no trailing \n
        found = self._arm11(self._evaluate(m, map_raw_text=compact))
        self.assertEqual(len(found), 1)

    def test_crlf_line_endings_are_non_canonical_drift(self):
        # The arm claims BYTE-identity, so a CRLF-encoded copy of an otherwise-canonical map
        # (a Windows hand-edit or a merge tool rewriting line endings) is non-canonical. A
        # newline-translating read would decode CRLF to `\n` and silently pass; the comparand
        # must preserve the on-disk `\r\n`.
        m = _map(files={})
        crlf = guard._serialize_map(m).replace("\n", "\r\n")
        self.assertNotEqual(crlf, guard._serialize_map(m))
        found = self._arm11(self._evaluate(m, map_raw_text=crlf))
        self.assertEqual(len(found), 1)
        self.assertIn("not in canonical serialized form", found[0])

    def test_main_flags_a_crlf_on_disk_map(self):
        # End-to-end: main() must read the raw bytes (not newline-translated) so a CRLF map
        # turns the guard RED. A read_text-based reader would pass it.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "lib/test/modules").mkdir(parents=True)
            (root / "scripts").mkdir()
            (root / "lib/test/run.sh").write_text("", encoding="utf-8")
            (root / guard.REGISTRY_REL).write_text(json.dumps(_registry()), encoding="utf-8")
            m = _map(files={}, non_code_exempt=[guard.REGISTRY_REL])
            crlf = guard._serialize_map(m).replace("\n", "\r\n").encode("utf-8")
            (root / guard.MAP_REL).write_bytes(crlf)
            subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = guard.main(["coverage_map_guard.py", str(root)])
            self.assertEqual(rc, 1)
            self.assertIn("[arm11]", out.getvalue())

    def test_an_unreadable_raw_file_is_unestablished_not_a_pass(self):
        # CLAUDE.md "unknown is not zero": a read failure is reported, never laundered
        # into a clean pass.
        found = self._arm11(self._evaluate(_map(files={}), map_raw_error="boom"))
        self.assertEqual(len(found), 1)
        self.assertIn("unestablished measurement", found[0])

    def test_arm11_stands_down_when_no_raw_text_is_injected(self):
        # Every pre-existing positional/keyword caller passes neither raw text nor a raw
        # error; arm 11 must report nothing rather than flag the map non-canonical.
        self.assertEqual(self._arm11(self._evaluate(_map(files={}))), [])

    def test_arm4_shape_rejection_short_circuits_before_arm11(self):
        # A malformed map must never reach the serialization: arm 4 early-returns first.
        bad = _map(files={})
        bad["run_sh_blocks"] = "not-an-object"
        v = guard.evaluate([], bad, _registry(), map_raw_text="anything at all")
        self.assertEqual(self._arm11(v), [])
        self.assertIn("[arm4]", "".join(v))

    def test_write_map_output_satisfies_arm11(self):
        # The structural "one definition of canonical" guarantee: whatever _write_map
        # writes is exactly what arm 11 accepts, so writer and checker cannot diverge.
        m = _map(run_sh_blocks={"200": _owned("unmodularized"), "unlabeled": _owned()})
        written = guard._serialize_map(m)
        self.assertEqual(self._arm11(self._evaluate(m, map_raw_text=written)), [])

    def test_main_reports_arm11_over_a_drifted_on_disk_map(self):
        # End-to-end through main(): a non-canonically-serialized map on disk turns the
        # guard RED and names arm 11, while the parsed value stays valid.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "lib/test/modules").mkdir(parents=True)
            (root / "scripts").mkdir()
            (root / "lib/test/run.sh").write_text("", encoding="utf-8")
            (root / guard.REGISTRY_REL).write_text(
                json.dumps(_registry()), encoding="utf-8"
            )
            m = _map(files={})
            # Non-canonical bytes: compact, no trailing newline. Value is well-shaped.
            (root / guard.MAP_REL).write_text(
                json.dumps(m, sort_keys=True, ensure_ascii=False), encoding="utf-8"
            )
            subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = guard.main(["coverage_map_guard.py", str(root)])
            self.assertEqual(rc, 1)
            self.assertIn("[arm11]", out.getvalue())

    def test_main_passes_a_canonical_on_disk_map(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "lib/test/modules").mkdir(parents=True)
            (root / "scripts").mkdir()
            (root / "lib/test/run.sh").write_text("", encoding="utf-8")
            (root / guard.REGISTRY_REL).write_text(
                json.dumps(_registry()), encoding="utf-8"
            )
            # Exempt the depth-1 registry file (arm 5) so only arm 11 governs rc here.
            m = _map(files={}, non_code_exempt=[guard.REGISTRY_REL])
            (root / guard.MAP_REL).write_text(guard._serialize_map(m), encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
            subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = guard.main(["coverage_map_guard.py", str(root)])
            self.assertEqual(rc, 0, out.getvalue())


class FixModeTest(unittest.TestCase):
    def _tree(self, directory, map_value, run_sh="", modules=None):
        root = Path(directory)
        (root / "lib/test/modules").mkdir(parents=True)
        (root / "lib/test/run.sh").write_text(run_sh, encoding="utf-8")
        for name, body in (modules or {}).items():
            (root / f"lib/test/modules/{name}.sh").write_text(body, encoding="utf-8")
        (root / guard.MAP_REL).write_text(
            json.dumps(map_value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return root

    def _fix(self, root):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = guard.main(["coverage_map_guard.py", str(root), "--fix"])
        return rc, out.getvalue()

    def test_fix_repairs_a_non_compliant_map_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._tree(
                d,
                _map(run_sh_blocks={"unlabeled": _owned()}),
                run_sh='assert_eq "#100 still in the monolith" "1" "1"\n',
                modules={"mod-a": 'assert_eq "#200 fully extracted" "1" "1"\n'},
            )
            rc, output = self._fix(root)
            self.assertEqual(rc, 0)
            self.assertIn("[fix] repaired", output)
            repaired = json.loads((root / guard.MAP_REL).read_text(encoding="utf-8"))
            self.assertEqual(repaired["run_sh_blocks"]["100"]["owner"], "unmodularized")
            self.assertEqual(repaired["run_sh_blocks"]["200"]["owner"], "mod-a")
            before = (root / guard.MAP_REL).read_bytes()
            rc, output = self._fix(root)
            self.assertEqual(rc, 0)
            self.assertIn("already satisfies", output)
            self.assertEqual(before, (root / guard.MAP_REL).read_bytes())

    def test_fix_output_satisfies_the_arm_it_repairs(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._tree(
                d,
                _map(run_sh_blocks={"200": _owned("unmodularized")}),
                run_sh='assert_eq "#100 monolith" "1" "1"\n',
                modules={"mod-a": 'assert_eq "#200 extracted" "1" "1"\n'},
            )
            self._fix(root)
            repaired = json.loads((root / guard.MAP_REL).read_text(encoding="utf-8"))
            run_sh_labels, module_labels, errors = guard._scan_labels(root)
            self.assertEqual(errors, [])
            violations = guard.evaluate(
                [], repaired, _registry(ids=("mod-a",)),
                run_sh_labels=run_sh_labels, module_labels=module_labels,
                scan_read_errors=errors,
            )
            self.assertEqual([v for v in violations if v.startswith("[arm9]")], [])

    def test_fix_never_removes_a_curated_entry(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._tree(
                d, _map(run_sh_blocks={"unlabeled": _owned(), "900": _owned()}),
                run_sh="", modules={},
            )
            self._fix(root)
            repaired = json.loads((root / guard.MAP_REL).read_text(encoding="utf-8"))
            self.assertIn("900", repaired["run_sh_blocks"])
            self.assertIn("unlabeled", repaired["run_sh_blocks"])

    def test_fix_refuses_to_write_a_malformed_map(self):
        for bad in ("not json at all", json.dumps([]), json.dumps({"schema_version": 2}),
                    json.dumps({"schema_version": 1, "files": {}, "run_sh_blocks": [],
                                "non_code_exempt": [], "exempt_subtrees": [],
                                "generated_by": "x"}),
                    json.dumps({"schema_version": 1, "files": {},
                                "run_sh_blocks": {"1": {"owner": 7}},
                                "non_code_exempt": [], "exempt_subtrees": [],
                                "generated_by": "x"})):
            with self.subTest(bad=bad[:40]), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                (root / "lib/test/modules").mkdir(parents=True)
                (root / "lib/test/run.sh").write_text("", encoding="utf-8")
                (root / guard.MAP_REL).write_text(bad, encoding="utf-8")
                rc, output = self._fix(root)
                self.assertEqual(rc, 1)
                self.assertIn("[fix-refused]", output)
                self.assertEqual((root / guard.MAP_REL).read_text(encoding="utf-8"), bad)

    def test_fix_refuses_with_a_breadcrumb_when_the_map_cannot_be_written(self):
        # Every READ failure path already breadcrumbs; the write path was the one that
        # would raise a raw traceback instead, breaking the file's fail-closed posture.
        with tempfile.TemporaryDirectory() as d:
            root = self._tree(
                d,
                _map(run_sh_blocks={"unlabeled": _owned()}),
                run_sh='assert_eq "#100 monolith" "1" "1"\n',
                modules={},
            )
            map_path = root / guard.MAP_REL
            before = map_path.read_bytes()
            map_path.chmod(0o444)
            try:
                rc, output = self._fix(root)
            finally:
                map_path.chmod(0o644)
            self.assertEqual(rc, 1)
            self.assertIn("[fix-refused]", output)
            self.assertIn("could not be written", output)
            self.assertEqual(before, map_path.read_bytes())

    def test_fix_refuses_when_a_derivation_source_is_unreadable(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._tree(d, _map(), run_sh="", modules={})
            (root / "lib/test/run.sh").unlink()
            rc, output = self._fix(root)
            self.assertEqual(rc, 1)
            self.assertIn("[fix-refused]", output)

    def test_fix_canonicalizes_order_only_drift(self):
        # Issue #1065 recorded scope decision: `--fix` re-canonicalizes an order-only
        # drifted map even with no presence/ownership repair pending, so its remedy is an
        # action that actually repairs an arm-11 violation.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "lib/test/modules").mkdir(parents=True)
            (root / "lib/test/run.sh").write_text("", encoding="utf-8")
            m = _map(run_sh_blocks={"126": _owned(), "139": _owned(), "unlabeled": _owned()})
            # Write NON-canonical bytes (reversed key order) whose parsed value is complete,
            # so `_apply_fix` finds nothing to repair — only the serialization is wrong.
            drift = json.dumps(
                {
                    "schema_version": m["schema_version"],
                    "generated_by": m["generated_by"],
                    "files": m["files"],
                    "run_sh_blocks": {"unlabeled": _owned(), "139": _owned(), "126": _owned()},
                    "non_code_exempt": m["non_code_exempt"],
                    "exempt_subtrees": m["exempt_subtrees"],
                },
                indent=2, sort_keys=False, ensure_ascii=False,
            ) + "\n"
            (root / guard.MAP_REL).write_text(drift, encoding="utf-8")
            rc, output = self._fix(root)
            self.assertEqual(rc, 0)
            self.assertIn("[fix] repaired", output)
            self.assertEqual(
                (root / guard.MAP_REL).read_text(encoding="utf-8"),
                guard._serialize_map(m),
            )
            # Idempotent: a second run no-ops.
            before = (root / guard.MAP_REL).read_bytes()
            rc, output = self._fix(root)
            self.assertIn("already satisfies", output)
            self.assertEqual(before, (root / guard.MAP_REL).read_bytes())

    def test_fix_is_a_noop_on_a_canonical_file(self):
        # Measured path 1 (AC6): unchanged on a canonical file.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "lib/test/modules").mkdir(parents=True)
            (root / "lib/test/run.sh").write_text("", encoding="utf-8")
            m = _map(run_sh_blocks={"unlabeled": _owned()})
            (root / guard.MAP_REL).write_text(guard._serialize_map(m), encoding="utf-8")
            before = (root / guard.MAP_REL).read_bytes()
            rc, output = self._fix(root)
            self.assertEqual(rc, 0)
            self.assertIn("already satisfies", output)
            self.assertEqual(before, (root / guard.MAP_REL).read_bytes())

    def test_fix_is_additive_only_on_a_real_repair(self):
        # Measured path 2 (AC6): a canonical map plus one new run.sh label gains exactly
        # the new block and moves no existing entry (the "4 added / 0 removed" property).
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "lib/test/modules").mkdir(parents=True)
            (root / "lib/test/run.sh").write_text(
                'assert_eq "#100 existing" "1" "1"\n', encoding="utf-8"
            )
            m = _map(run_sh_blocks={"100": _owned(), "unlabeled": _owned()})
            (root / guard.MAP_REL).write_text(guard._serialize_map(m), encoding="utf-8")
            before = json.loads((root / guard.MAP_REL).read_text(encoding="utf-8"))
            # Add one new labelled assertion; --fix must add ONLY its block.
            (root / "lib/test/run.sh").write_text(
                'assert_eq "#100 existing" "1" "1"\nassert_eq "#1099 new label" "1" "1"\n',
                encoding="utf-8",
            )
            rc, output = self._fix(root)
            self.assertEqual(rc, 0)
            self.assertIn("[fix] repaired", output)
            after = json.loads((root / guard.MAP_REL).read_text(encoding="utf-8"))
            self.assertEqual(set(after["run_sh_blocks"]) - set(before["run_sh_blocks"]), {"1099"})
            self.assertEqual(set(before["run_sh_blocks"]) - set(after["run_sh_blocks"]), set())
            # No existing entry's value changed.
            for k, val in before["run_sh_blocks"].items():
                self.assertEqual(after["run_sh_blocks"][k], val)

    def test_fix_preserves_the_positional_repo_root_cli_contract(self):
        # `main` still takes the repo root positionally, with or without --fix, so
        # lib/test/run.sh's existing `coverage_map_guard.py .` invocation is unedited.
        with tempfile.TemporaryDirectory() as d:
            root = self._tree(d, _map(), run_sh="", modules={})
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = guard.main(["coverage_map_guard.py", "--fix", str(root)])
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
