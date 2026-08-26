#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Offline regression tests for the coverage-map merge tooling (issue #1194).

Two mechanisms, tested independently:

* the JSON-aware git merge driver (`coverage-map-merge-driver.py`) — driven against
  REAL `git merge`s in throwaway offline repositories (no network, no `gh`): two
  branches each add a distinct key at the same insertion point (AC1/AC2), and a
  genuine same-key divergence conflicts rather than silently picking a side (AC3).
  The driver is registered in each fixture's OWN local config; the developer's global
  git config is never written (AC4) and — since `_GitFixtureBase` redirects git's
  global/system config for every fixture test — never read either. The AC5 mutation arm
  runs the same distinct-key merge with the driver UNREGISTERED and asserts the textual
  conflict returns.

* the CI-side key-retention check (`coverage-map-retention-check.py`) — its pure
  `detect_losses` core is driven from in-memory fixtures over every loss shape,
  including a `run_sh_blocks` key with no derivation and a dropped `note`/`owner`
  (AC8), the non-empty-reason escape hatch, and the AC5 defeated-comparison arm.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from typing import ClassVar

HERE = Path(__file__).resolve().parent
DRIVER_SOURCE = HERE / "coverage-map-merge-driver.py"
RETAIN_SOURCE = HERE / "coverage-map-retention-check.py"
GUARD_SOURCE = HERE / "coverage_map_guard.py"
POP_SOURCE = HERE / "lint_population.py"
MAP_REL = "lib/test/modules/coverage-map.json"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


driver = _load("coverage_map_merge_driver", DRIVER_SOURCE)
retain = _load("coverage_map_retention_check", RETAIN_SOURCE)

# Reuse the ONE canonical serializer (issue #1065's `_serialize_map`, which the driver
# re-exports) rather than re-spelling `json.dumps(...)` here — a third copy of the pinned
# shape would let these fixtures silently drift from what the driver/guard produce.
_serialize = driver._serialize_map


def _base_map(run_sh_blocks=None, files=None):
    return {
        "schema_version": 1,
        "generated_by": "test",
        "exempt_subtrees": ["lib/test/"],
        "non_code_exempt": [],
        "files": files or {},
        "run_sh_blocks": run_sh_blocks or {},
    }


class _GitFixtureBase(unittest.TestCase):
    """Shared offline-git-repo scaffolding for the two fixture classes below.

    Holds the fixture contract once — the `mkdtemp` + repository-LOCAL `git init`
    (never the developer's global config, AC4), the `git -C` wrapper, the map
    writer, and the default-branch probe — so a change to it (e.g. another
    host-independence `git config`) is made in exactly one place.

    Config isolation is established here, in `setUp`, and therefore applies to EVERY
    fixture test and every process it spawns — `_git`, the driver, the retention CLI,
    and the `git clone`/`fetch` calls the shallow-clone fixture makes directly. It is
    deliberately not an opt-in helper a test must remember to call: the isolation is
    what makes these fixtures host-independent, and a future fixture test added below
    inherits it without its author doing anything. A maintainer with, say,
    `merge.coverage-map-json.driver` registered in their own global config would
    otherwise watch the AC5 unregistered-driver negative control union cleanly and
    fail on a correct tree."""

    prefix = "cm-fixture-"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix=self.prefix))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self._isolate_git_config()
        self.repo = self.tmp / "repo"
        (self.repo / "lib" / "test" / "modules").mkdir(parents=True)
        self._git("init", "-q")
        self._git("config", "user.email", "t@t")
        self._git("config", "user.name", "t")
        # commit.gpgsign off so signing config on the host machine cannot break fixtures.
        self._git("config", "commit.gpgsign", "false")

    def _isolate_git_config(self):
        """Redirect git's global/system config to isolated empty files for this test.

        Patched into `os.environ` rather than threaded through each call site, so a
        subprocess that this fixture never passes an explicit `env=` to — including
        one a future test adds — is isolated all the same. `GIT_CONFIG_GLOBAL`
        supersedes both `~/.gitconfig` and the XDG path, and `HOME` is moved too so
        anything resolving a home directory lands inside the throwaway tree.

        Isolation runs both ways: the host's real config can neither cause a false
        pass (a globally registered driver making the AC5 negative control merge
        cleanly) nor a false fail, and a `--register` that wrote global would be
        provably detectable as a non-empty `isolated_global`."""
        self.isolated_global = self.tmp / "isolated-global-gitconfig"
        self.isolated_system = self.tmp / "isolated-system-gitconfig"
        self.isolated_global.write_text("", encoding="utf-8")
        self.isolated_system.write_text("", encoding="utf-8")
        patcher = unittest.mock.patch.dict(os.environ, {
            "GIT_CONFIG_GLOBAL": str(self.isolated_global),
            "GIT_CONFIG_SYSTEM": str(self.isolated_system),
            "HOME": str(self.tmp),
        })
        patcher.start()
        self.addCleanup(patcher.stop)

    def _git(self, *args, check=True):
        return subprocess.run(
            ["git", "-C", str(self.repo), *args],
            capture_output=True,
            text=True,
            check=check,
        )

    def _write_map(self, map_value):
        (self.repo / MAP_REL).write_text(_serialize(map_value), encoding="utf-8")

    def _has_main(self):
        return self._git("rev-parse", "--verify", "main", check=False).returncode == 0

    def _base_branch(self):
        return "main" if self._has_main() else "master"


class MergeDriverGitFixtureTest(_GitFixtureBase):
    """AC1–AC5: the driver against real offline `git merge`s."""

    prefix = "cm-merge-"

    def setUp(self):
        super().setUp()
        # The driver imports the coverage guard, which imports lint_population; copy all
        # three so the fixture is self-contained and offline.
        for src in (DRIVER_SOURCE, GUARD_SOURCE, POP_SOURCE):
            shutil.copy(src, self.repo / "lib" / "test" / src.name)
        self._write_map(_base_map(
            run_sh_blocks={
                "1210": {"note": "n1210", "owner": "unmodularized"},
                "1290": {"note": "n1290", "owner": "unmodularized"},
            },
            files={"lib/aaa0.sh": {"note": "pre", "owner": "unmodularized"}},
        ))
        (self.repo / ".gitattributes").write_text(
            f"{MAP_REL} merge=coverage-map-json\n", encoding="utf-8"
        )
        self._git("add", "-A")
        self._git("commit", "-qm", "base")

    def _read_map(self):
        return json.loads((self.repo / MAP_REL).read_text(encoding="utf-8"))

    def _register_driver(self):
        self._git(
            "config", "merge.coverage-map-json.name", "coverage-map JSON-aware merge driver"
        )
        self._git(
            "config",
            "merge.coverage-map-json.driver",
            f"python3 lib/test/{DRIVER_SOURCE.name} %O %A %B",
        )

    def _add_key_on_branch(self, branch, section, key, entry):
        self._git("checkout", "-q", "main" if self._has_main() else "master")
        self._git("checkout", "-qb", branch)
        m = self._read_map()
        m[section][key] = entry
        self._write_map(m)
        self._git("commit", "-qam", f"{branch} adds {key}")

    def _two_distinct_keys(self, section, key_a, key_b):
        self._add_key_on_branch("A", section, key_a, {"note": f"{key_a} note", "owner": "unmodularized"})
        self._add_key_on_branch("B", section, key_b, {"note": f"{key_b} note", "owner": "unmodularized"})
        self._git("checkout", "-q", "A")
        return self._git("merge", "--no-edit", "B", check=False)

    def test_AC1_distinct_run_sh_blocks_keys_both_survive(self):
        self._register_driver()
        result = self._two_distinct_keys("run_sh_blocks", "1211", "1212")
        self.assertEqual(result.returncode, 0, f"merge should be clean:\n{result.stderr}")
        m = self._read_map()
        self.assertEqual(m["run_sh_blocks"]["1211"], {"note": "1211 note", "owner": "unmodularized"})
        self.assertEqual(m["run_sh_blocks"]["1212"], {"note": "1212 note", "owner": "unmodularized"})
        # The two pre-existing adjacent keys are untouched, byte-intact.
        self.assertEqual(m["run_sh_blocks"]["1210"], {"note": "n1210", "owner": "unmodularized"})

    def test_AC2_distinct_files_keys_both_survive(self):
        self._register_driver()
        result = self._two_distinct_keys("files", "lib/aaa.sh", "lib/aab.sh")
        self.assertEqual(result.returncode, 0, f"merge should be clean:\n{result.stderr}")
        m = self._read_map()
        # AC2 requires note/owner byte-intact — assert the full entries, not mere presence.
        self.assertEqual(m["files"]["lib/aaa.sh"], {"note": "lib/aaa.sh note", "owner": "unmodularized"})
        self.assertEqual(m["files"]["lib/aab.sh"], {"note": "lib/aab.sh note", "owner": "unmodularized"})
        # The pre-existing files entry is untouched, byte-intact.
        self.assertEqual(m["files"]["lib/aaa0.sh"], {"note": "pre", "owner": "unmodularized"})

    def test_AC3_same_key_divergence_conflicts(self):
        self._register_driver()
        # Both branches add the SAME key with different content.
        self._add_key_on_branch("A", "run_sh_blocks", "1250", {"note": "A version", "owner": "unmodularized"})
        self._add_key_on_branch("B", "run_sh_blocks", "1250", {"note": "B version", "owner": "unmodularized"})
        self._git("checkout", "-q", "A")
        result = self._git("merge", "--no-edit", "B", check=False)
        self.assertNotEqual(result.returncode, 0, "same-key divergence must NOT merge silently")
        # The path is left conflicted (unmerged) — a human decision is required.
        status = self._git("status", "--porcelain", MAP_REL)
        self.assertTrue(status.stdout.strip().startswith(("UU", "AA")),
                        f"map should be unmerged, got: {status.stdout!r}")

    def test_AC5_mutation_unregistered_driver_reintroduces_conflict(self):
        # No _register_driver(): the attribute names the driver but git falls back to its
        # line-based three-way merge, which conflicts on the adjacent insertion point.
        result = self._two_distinct_keys("run_sh_blocks", "1211", "1212")
        self.assertNotEqual(
            result.returncode, 0,
            "with the driver UNREGISTERED the adjacent-key merge must conflict (the defect)",
        )

    def _driver(self, *args):
        return subprocess.run(
            ["python3", f"lib/test/{DRIVER_SOURCE.name}", *args],
            cwd=str(self.repo), capture_output=True, text=True, check=False,
        )

    def test_AC6_register_and_check_modes(self):
        # --check before registration fails RED and prints the exact registration command.
        before = self._driver("--check")
        self.assertEqual(before.returncode, 1, before.stdout + before.stderr)
        self.assertIn("--register", before.stdout + before.stderr)
        # --register succeeds...
        reg = self._driver("--register")
        self.assertEqual(reg.returncode, 0, reg.stdout + reg.stderr)
        # ...and --check now passes.
        after = self._driver("--check")
        self.assertEqual(after.returncode, 0, after.stdout + after.stderr)
        # AC4: registration wrote ONLY the repo-local config — the isolated global file
        # is byte-empty, proving --register never wrote --global.
        self.assertEqual(self.isolated_global.read_text(encoding="utf-8"), "",
                         "--register must never write the global git config")
        # And a real end-to-end merge with the driver registered by --register (not the
        # test helper) unions distinct keys cleanly.
        result = self._two_distinct_keys("run_sh_blocks", "1211", "1212")
        self.assertEqual(result.returncode, 0, result.stderr)
        m = self._read_map()
        self.assertIn("1211", m["run_sh_blocks"])
        self.assertIn("1212", m["run_sh_blocks"])

    def test_AC6_check_detects_wrong_value(self):
        self._git("config", "merge.coverage-map-json.driver", "some-other-driver %O %A %B")
        result = self._driver("--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("--register", result.stdout + result.stderr)

    def test_AC4_no_global_git_config_written(self):
        # Registration writes only the fixture's local config; assert the driver key is
        # absent from the ISOLATED global config after a full registered merge, so the
        # assertion neither depends on nor perturbs the developer's real ~/.gitconfig.
        self._register_driver()
        self._two_distinct_keys("run_sh_blocks", "1211", "1212")
        globalcfg = subprocess.run(
            ["git", "config", "--global", "--get", "merge.coverage-map-json.driver"],
            capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(globalcfg.returncode, 0,
                            "the driver must never be written to the global git config")
        self.assertEqual(self.isolated_global.read_text(encoding="utf-8"), "")


class MergeDriverUnitTest(unittest.TestCase):
    """The pure `merge_maps` core, independent of git."""

    def test_distinct_keys_union(self):
        base = _base_map(run_sh_blocks={"a": {"note": "", "owner": "unmodularized"}})
        ours = _base_map(run_sh_blocks={"a": {"note": "", "owner": "unmodularized"},
                                        "b": {"note": "B", "owner": "unmodularized"}})
        theirs = _base_map(run_sh_blocks={"a": {"note": "", "owner": "unmodularized"},
                                          "c": {"note": "C", "owner": "unmodularized"}})
        merged = driver.merge_maps(base, ours, theirs)
        self.assertEqual(set(merged["run_sh_blocks"]), {"a", "b", "c"})

    def test_delete_on_one_side_is_honored(self):
        base = _base_map(run_sh_blocks={"a": {"note": "x", "owner": "unmodularized"}})
        ours = _base_map(run_sh_blocks={})  # ours deletes a
        theirs = _base_map(run_sh_blocks={"a": {"note": "x", "owner": "unmodularized"}})
        merged = driver.merge_maps(base, ours, theirs)
        self.assertNotIn("a", merged["run_sh_blocks"])

    def test_same_key_divergence_raises(self):
        base = _base_map(run_sh_blocks={"a": {"note": "base", "owner": "unmodularized"}})
        ours = _base_map(run_sh_blocks={"a": {"note": "ours", "owner": "unmodularized"}})
        theirs = _base_map(run_sh_blocks={"a": {"note": "theirs", "owner": "unmodularized"}})
        with self.assertRaises(driver.MergeConflict):
            driver.merge_maps(base, ours, theirs)

    def test_top_level_divergence_raises(self):
        base = _base_map()
        ours = _base_map()
        ours["generated_by"] = "ours"
        theirs = _base_map()
        theirs["generated_by"] = "theirs"
        with self.assertRaises(driver.MergeConflict):
            driver.merge_maps(base, ours, theirs)


class RetentionCheckTest(unittest.TestCase):
    """AC8 + AC5-retention: the pure `detect_losses` core."""

    def test_clean_when_nothing_dropped(self):
        base = _base_map(run_sh_blocks={"1": {"note": "n", "owner": "unmodularized"}})
        head = _base_map(run_sh_blocks={"1": {"note": "n", "owner": "unmodularized"},
                                        "2": {"note": "n2", "owner": "unmodularized"}})
        self.assertEqual(retain.detect_losses(base, head, None), [])

    def test_removed_run_sh_blocks_key_detected(self):
        base = _base_map(run_sh_blocks={"431": {"note": "curated record", "owner": "unmodularized"}})
        head = _base_map(run_sh_blocks={})
        losses = retain.detect_losses(base, head, None)
        self.assertTrue(any("431" in v and "absent" in v for v in losses), losses)

    def test_removed_files_key_detected(self):
        base = _base_map(files={"lib/x.sh": {"note": "n", "owner": "unmodularized"}})
        head = _base_map(files={})
        losses = retain.detect_losses(base, head, None)
        self.assertTrue(any("lib/x.sh" in v for v in losses), losses)

    def test_dropped_note_content_detected(self):
        base = _base_map(run_sh_blocks={"1": {"note": "two-clause record", "owner": "efficiency-trace"}})
        head = _base_map(run_sh_blocks={"1": {"note": "", "owner": "efficiency-trace"}})
        losses = retain.detect_losses(base, head, None)
        self.assertTrue(any("'note'" in v and "dropped" in v for v in losses), losses)

    def test_dropped_owner_content_detected(self):
        base = _base_map(run_sh_blocks={"1": {"note": "n", "owner": "some-module"}})
        head = _base_map(run_sh_blocks={"1": {"note": "n", "owner": ""}})
        losses = retain.detect_losses(base, head, None)
        self.assertTrue(any("'owner'" in v and "dropped" in v for v in losses), losses)

    def test_owner_change_is_not_a_drop(self):
        base = _base_map(run_sh_blocks={"1": {"note": "n", "owner": "module-a"}})
        head = _base_map(run_sh_blocks={"1": {"note": "n", "owner": "module-b"}})
        self.assertEqual(retain.detect_losses(base, head, None), [])

    def test_escape_hatch_with_reason_permits_removal(self):
        base = _base_map(run_sh_blocks={"431": {"note": "n", "owner": "unmodularized"}})
        head = _base_map(run_sh_blocks={})
        allow = [{"half": "run_sh_blocks", "key": "431", "reason": "block genuinely retired in PR #999"}]
        self.assertEqual(retain.detect_losses(base, head, allow), [])

    def test_escape_hatch_empty_reason_rejected(self):
        base = _base_map(run_sh_blocks={"431": {"note": "n", "owner": "unmodularized"}})
        head = _base_map(run_sh_blocks={})
        allow = [{"half": "run_sh_blocks", "key": "431", "reason": "   "}]
        losses = retain.detect_losses(base, head, allow)
        # Both the malformed-entry breadcrumb AND the unpermitted removal are reported.
        self.assertTrue(any("no non-empty 'reason'" in v for v in losses), losses)
        self.assertTrue(any("absent" in v for v in losses), losses)

    def test_escape_hatch_absent_reason_key_rejected(self):
        base = _base_map(run_sh_blocks={"431": {"note": "n", "owner": "unmodularized"}})
        head = _base_map(run_sh_blocks={})
        # The 'reason' key is entirely absent (not merely blank) — a distinct limb.
        allow = [{"half": "run_sh_blocks", "key": "431"}]
        losses = retain.detect_losses(base, head, allow)
        self.assertTrue(any("no non-empty 'reason'" in v for v in losses), losses)
        self.assertTrue(any("absent" in v for v in losses), losses)

    def test_malformed_allowlist_is_fail_closed(self):
        base = _base_map(run_sh_blocks={"431": {"note": "n", "owner": "unmodularized"}})
        head = _base_map(run_sh_blocks={})
        losses = retain.detect_losses(base, head, {"not": "a list"})
        self.assertTrue(any("must be a JSON array" in v for v in losses), losses)
        self.assertTrue(any("absent" in v for v in losses), losses)

    def test_AC5_mutation_defeated_comparison_misses_the_drop(self):
        # Defeating the comparison = comparing head against itself (no base to lose from).
        # With the comparison intact (base carries the key) the drop is caught; with it
        # defeated (base == head) the very same dropped-key input reports clean — the
        # mutation the AC5 arm records.
        head = _base_map(run_sh_blocks={})
        base_with_key = _base_map(run_sh_blocks={"431": {"note": "n", "owner": "unmodularized"}})
        self.assertNotEqual(retain.detect_losses(base_with_key, head, None), [],
                            "intact comparison must catch the drop")
        self.assertEqual(retain.detect_losses(head, head, None), [],
                         "defeated comparison (base==head) misses the drop")


class RetentionOutcomeSelectionTest(unittest.TestCase):
    """The three-outcome selector: a degraded base comparand must not report clean.

    `classify_outcome` is the whole selection, so every arm AND the arm ORDER is driven
    here from in-memory fixtures — a grep on a message literal is not coverage of the
    branch that chooses it.

    The fifth argument, `comparand_substituted`, is what separates arm 1 from arm 2: the
    same violation list is an established loss against a sound comparand and only an
    unconfirmed difference against BASE_REF's substituted tip. Every call below states it
    explicitly, because which arm a violation reaches is the whole point of these tests."""

    KEY_LOSS: ClassVar[list[str]] = ["[retain] files key 'lib/x.sh' ... absent"]
    WHY: ClassVar[list[str]] = ["the base map at abc123 carried no files/run_sh_blocks keys"]
    SUBSTITUTED: ClassVar[list] = [("could not compute a merge base against origin/main; compared "
                   "against origin/main's tip instead")]

    def test_clean_requires_an_established_comparand(self):
        status, lines = retain.classify_outcome([], [], False, "origin/main", False)
        self.assertEqual(status, retain.EXIT_CLEAN)
        self.assertTrue(
            any("no coverage-map key or content was dropped" in line for line in lines), lines)

    def test_unestablished_comparand_is_not_clean(self):
        # The Important finding: a degraded base previously exited 0 with a stderr note.
        status, lines = retain.classify_outcome([], self.WHY, False, "origin/main", False)
        self.assertEqual(status, retain.EXIT_UNESTABLISHED)
        self.assertNotEqual(status, retain.EXIT_CLEAN)
        self.assertNotEqual(status, retain.EXIT_LOSS)
        body = "\n".join(lines)
        self.assertIn("NOT a clean pass", body)
        self.assertIn(self.WHY[0], body)
        self.assertIn(retain.ACK_FLAG, body)

    def test_unestablished_status_is_distinct_from_both_other_outcomes(self):
        # The distinguishability requirement, asserted as a property of the constants
        # rather than of any one message: a caller must be able to tell all three apart.
        self.assertEqual(
            len({retain.EXIT_CLEAN, retain.EXIT_LOSS, retain.EXIT_UNESTABLISHED}), 3
        )

    def test_acknowledgement_downgrades_to_zero_but_still_reports(self):
        status, lines = retain.classify_outcome([], self.WHY, True, "origin/main", False)
        self.assertEqual(status, retain.EXIT_CLEAN)
        body = "\n".join(lines)
        # Acknowledged is never laundered into "verified clean": the reasons and the
        # acknowledgement both stay on stdout.
        self.assertIn(self.WHY[0], body)
        self.assertIn("acknowledged degraded run, not a verified clean one", body)
        self.assertNotIn("no coverage-map key or content was dropped", body)

    def test_arm_order_loss_outranks_a_degraded_comparand(self):
        # A loss measured against a SOUND comparand is an ESTABLISHED fact, so it must
        # win over "unestablished" — reordering the arms would report exit 3 for a run
        # that actually found a loss. The comparand here is the real merge base; only
        # the base map's own thinness is unestablished.
        status, lines = retain.classify_outcome(
            self.KEY_LOSS, self.WHY, False, "origin/main", False)
        self.assertEqual(status, retain.EXIT_LOSS)
        self.assertEqual(lines[:len(self.KEY_LOSS)], self.KEY_LOSS)

    def test_arm_order_loss_outranks_even_an_acknowledged_degraded_base(self):
        # The acknowledgement flag must not be able to suppress a real finding measured
        # against a sound comparand — the invariant the substituted-comparand routing
        # below must not weaken.
        status, lines = retain.classify_outcome(
            self.KEY_LOSS, self.WHY, True, "origin/main", False)
        self.assertEqual(status, retain.EXIT_LOSS)
        self.assertEqual(lines[:len(self.KEY_LOSS)], self.KEY_LOSS)

    def test_sound_comparand_loss_still_reports_the_degraded_context(self):
        # A loss must never be announced with the degraded reasons SUPPRESSED: before
        # this, arm 1 returned the violations alone, so a developer reading "a merge
        # dropped it" got no hint the run had also failed to establish something.
        _, lines = retain.classify_outcome(
            self.KEY_LOSS, self.WHY, False, "origin/main", False)
        body = "\n".join(lines)
        self.assertIn(self.WHY[0], body)

    def test_no_degraded_context_is_invented_when_there_is_none(self):
        # Negative control for the line above: with nothing unestablished, arm 1 reports
        # the violations and nothing else. Without this, a check that always appended a
        # context block would pass the assertion above.
        _, lines = retain.classify_outcome(self.KEY_LOSS, [], False, "origin/main", False)
        self.assertEqual(lines, self.KEY_LOSS)

    def test_violation_against_a_substituted_comparand_is_not_an_established_loss(self):
        # The Important finding. `common.merge_base` hands back BASE_REF's TIP when no merge
        # base can be computed, and that tip may carry a key added AFTER the fork which
        # the branch legitimately never had. Reporting that as exit-1 "a merge dropped
        # it" misattributes it, so it routes through the degraded arm instead.
        status, lines = retain.classify_outcome(
            self.KEY_LOSS, self.SUBSTITUTED, False, "origin/main", True)
        self.assertEqual(status, retain.EXIT_UNESTABLISHED)
        self.assertNotEqual(status, retain.EXIT_LOSS)
        body = "\n".join(lines)
        # The findings are still shown — routing them is not hiding them.
        self.assertIn(self.KEY_LOSS[0], body)
        # ...and never without the substitution named beside them.
        self.assertIn(self.SUBSTITUTED[0], body)
        self.assertIn("SUBSTITUTE comparand", body)
        self.assertIn("NOT established losses", body)

    def test_substituted_comparand_violation_can_be_acknowledged(self):
        # The unacknowledgeable half of the finding: the flag documented as downgrading
        # a degraded comparand must actually reach this case.
        status, lines = retain.classify_outcome(
            self.KEY_LOSS, self.SUBSTITUTED, True, "origin/main", True)
        self.assertEqual(status, retain.EXIT_CLEAN)
        body = "\n".join(lines)
        self.assertIn("acknowledged degraded run, not a verified clean one", body)
        # Acknowledged still means shown, never silenced.
        self.assertIn(self.KEY_LOSS[0], body)
        self.assertIn("SUBSTITUTE comparand", body)
        # An acknowledged degraded run is never laundered into a verified clean pass.
        self.assertNotIn("no coverage-map key or content was dropped", body)

    def test_substitution_alone_does_not_downgrade_a_clean_run_to_a_finding(self):
        # Negative control on the new flag: `comparand_substituted` routes violations,
        # it does not manufacture them. With no violations it behaves exactly as the
        # pre-existing degraded arm did.
        status, lines = retain.classify_outcome(
            [], self.SUBSTITUTED, False, "origin/main", True)
        self.assertEqual(status, retain.EXIT_UNESTABLISHED)
        body = "\n".join(lines)
        self.assertNotIn("SUBSTITUTE comparand", body)

    def test_substituted_comparand_report_names_the_base_ref(self):
        # The report must say WHICH tip stood in, not merely that one did — the
        # developer's next action is to fetch that ref's real history.
        _, lines = retain.classify_outcome(
            self.KEY_LOSS, self.SUBSTITUTED, False, "upstream/develop", True)
        self.assertIn("upstream/develop's own tip", "\n".join(lines))

    def test_every_unestablished_reason_is_reported(self):
        reasons = ["no merge base against origin/main", "base map was empty"]
        _, lines = retain.classify_outcome([], reasons, False, "origin/main", False)
        body = "\n".join(lines)
        for reason in reasons:
            self.assertIn(reason, body)


class RetentionMergeBaseTest(_GitFixtureBase):
    """`common.merge_base`: the substitute comparand must be reported, never silent."""

    prefix = "cm-mb-"

    def setUp(self):
        super().setUp()
        self._write_map(_base_map(run_sh_blocks={"431": {"note": "n", "owner": "unmodularized"}}))
        self._git("add", "-A")
        self._git("commit", "-qm", "base")

    def test_resolvable_base_reports_no_degradation(self):
        base, error, degraded = retain.common.merge_base(self.repo, self._base_branch())
        self.assertIsNone(error)
        self.assertIsNone(degraded, "a real merge base must not be flagged degraded")
        self.assertRegex(base, r"^[0-9a-f]{40}$")

    def test_unresolvable_base_ref_falls_back_and_reports_it(self):
        base, error, degraded = retain.common.merge_base(self.repo, "origin/never-fetched")
        self.assertIsNone(error)
        self.assertEqual(base, "origin/never-fetched")
        self.assertIsNotNone(degraded, "the fallback substitute must be reported")
        self.assertIn("could not compute a merge base", degraded)

    def test_success_naming_no_commit_is_reported_as_degraded(self):
        # `git merge-base` exiting 0 while naming NOTHING is the same silent substitution
        # as the rc!=0 arm — BASE_REF's tip stands in for a merge base that was never
        # computed. Driven through a stubbed subprocess because git does not produce this
        # shape on demand; without it the branch is a fail-open nothing can reach.
        stub = subprocess.CompletedProcess(args=[], returncode=0, stdout="  \n", stderr="")
        with unittest.mock.patch.object(subprocess, "run", return_value=stub):
            base, error, degraded = retain.common.merge_base(self.repo, "origin/main")
        self.assertIsNone(error)
        self.assertEqual(base, "origin/main")
        self.assertIsNotNone(degraded, "an empty merge-base result must not pass as real")
        self.assertIn("named no commit", degraded)

    def test_unrelated_histories_fall_back_and_report_it(self):
        # `git merge-base` exits nonzero with NO stderr when there is simply no common
        # ancestor — the shape a shallow clone's truncated graph also produces.
        trunk = self._base_branch()
        self._git("checkout", "-q", "--orphan", "orphan")
        self._git("rm", "-rq", "--cached", ".", check=False)
        (self.repo / MAP_REL).unlink(missing_ok=True)
        (self.repo / "OTHER.md").write_text("unrelated\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-qm", "orphan root")
        # Back onto the trunk so HEAD and the orphan branch have no common ancestor.
        self._git("checkout", "-qf", trunk)
        base, error, degraded = retain.common.merge_base(self.repo, "orphan")
        self.assertIsNone(error)
        self.assertEqual(base, "orphan")
        self.assertIsNotNone(degraded)


class RetentionConfigBaseTest(_GitFixtureBase):
    """`common.read_config_base` + the default `origin/<base_branch>` — the path CI runs."""

    prefix = "cm-cfgbase-"

    def test_absent_resolver_falls_back_to_main(self):
        # No scripts/config-get.sh in the fixture: the documented best-effort default.
        self.assertEqual(retain.common.read_config_base(self.repo), "main")

    def test_resolver_value_is_honored(self):
        resolver = self.repo / "scripts" / "config-get.sh"
        resolver.parent.mkdir(parents=True, exist_ok=True)
        resolver.write_text("#!/bin/sh\necho develop\n", encoding="utf-8")
        resolver.chmod(0o755)
        self.assertEqual(retain.common.read_config_base(self.repo), "develop")

    def test_empty_resolver_output_falls_back_to_main(self):
        resolver = self.repo / "scripts" / "config-get.sh"
        resolver.parent.mkdir(parents=True, exist_ok=True)
        resolver.write_text("#!/bin/sh\necho\n", encoding="utf-8")
        resolver.chmod(0o755)
        self.assertEqual(retain.common.read_config_base(self.repo), "main")

    def test_default_base_ref_is_origin_prefixed_and_unestablished_when_unfetched(self):
        # With NO --base-ref (what CI passes) the check composes origin/<base_branch>.
        # In this fixture there is no remote at all, so the run must fail closed rather
        # than report clean — and the message must name the composed ref.
        self._write_map(_base_map(run_sh_blocks={"431": {"note": "n", "owner": "unmodularized"}}))
        self._git("add", "-A")
        self._git("commit", "-qm", "base")
        result = subprocess.run(
            ["python3", str(RETAIN_SOURCE), str(self.repo)],
            capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("origin/main", result.stdout + result.stderr)


class RetentionUnreadableInputTest(_GitFixtureBase):
    """The head-map and allow-file read branches: unreadable input is never 'empty'."""

    prefix = "cm-unread-"

    def setUp(self):
        super().setUp()
        self._write_map(_base_map(run_sh_blocks={"431": {"note": "n", "owner": "unmodularized"}}))
        self._git("add", "-A")
        self._git("commit", "-qm", "base")
        self.base = self._base_branch()
        self._git("checkout", "-qb", "feature")

    def _run(self, *extra):
        return subprocess.run(
            ["python3", str(RETAIN_SOURCE), str(self.repo), "--base-ref", self.base, *extra],
            capture_output=True, text=True, check=False,
        )

    def test_unparseable_head_map_fails_closed(self):
        (self.repo / MAP_REL).write_text("{ not json", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, retain.EXIT_LOSS, result.stdout + result.stderr)
        self.assertIn("could not read the head", result.stdout)

    def test_absent_head_map_fails_closed(self):
        (self.repo / MAP_REL).unlink()
        result = self._run()
        self.assertEqual(result.returncode, retain.EXIT_LOSS, result.stdout + result.stderr)
        self.assertIn("could not read the head", result.stdout)

    def test_unparseable_allow_file_fails_closed_and_is_not_treated_as_empty(self):
        (self.repo / "lib" / "test" / "coverage-map-retention-allow.json").write_text(
            "[ {,", encoding="utf-8")
        result = self._run()
        self.assertEqual(result.returncode, retain.EXIT_LOSS, result.stdout + result.stderr)
        self.assertIn("refusing to treat it as empty", result.stdout)

    def test_absent_allow_file_is_not_an_error(self):
        # The escape hatch is optional; its absence must not be confused with a bad one.
        allow = self.repo / "lib" / "test" / "coverage-map-retention-allow.json"
        self.assertFalse(allow.exists())
        self.assertEqual(self._run().returncode, retain.EXIT_CLEAN)


class RetentionShallowCloneTest(_GitFixtureBase):
    """The Important finding, end to end: a real shallow clone must not report clean.

    Builds an upstream whose history predates the coverage map, clones it shallowly, and
    drops a key on the feature side — the exact input that previously exited 0."""

    prefix = "cm-shallow-"

    def setUp(self):
        super().setUp()
        # History BEFORE the map exists — a shallow boundary lands here.
        (self.repo / "README.md").write_text("pad\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-qm", "pre-map")
        self.premap = self._git("rev-parse", "HEAD").stdout.strip()
        self._write_map(_base_map(run_sh_blocks={
            "keep": {"note": "kept", "owner": "unmodularized"},
            "drop": {"note": "dropped by a merge resolution", "owner": "unmodularized"},
        }))
        self._git("add", "-A")
        self._git("commit", "-qm", "add map")
        self.base = self._base_branch()
        self._git("checkout", "-qb", "feature")
        self._write_map(_base_map(run_sh_blocks={"keep": {"note": "kept", "owner": "unmodularized"}}))
        self._git("commit", "-qam", "drop a key")

        self.clone = self.tmp / "shallow"
        subprocess.run(
            ["git", "clone", "-q", "--depth", "1", "--branch", "feature",
             str(self.repo), str(self.clone)],
            capture_output=True, text=True, check=True,
        )
        # Shallow-fetch the base at a commit that predates the map: the truncated graph
        # that makes `git merge-base` succeed while naming a useless boundary commit.
        subprocess.run(
            ["git", "-C", str(self.clone), "fetch", "-q", "--depth", "1", "origin",
             f"+{self.premap}:refs/remotes/origin/{self.base}"],
            capture_output=True, text=True, check=True,
        )

    def _run(self, *extra):
        return subprocess.run(
            ["python3", str(RETAIN_SOURCE), str(self.clone),
             "--base-ref", f"origin/{self.base}", *extra],
            capture_output=True, text=True, check=False,
        )

    def test_shallow_clone_with_a_dropped_key_does_not_report_clean(self):
        result = self._run()
        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, retain.EXIT_UNESTABLISHED, combined)
        self.assertIn("NOT a clean pass", result.stdout)
        # The old fail-open wording must not be what a caller sees here.
        self.assertNotIn("no coverage-map key or content was dropped", result.stdout)

    def test_shallow_clone_acknowledged_exits_zero_but_says_so(self):
        result = self._run(retain.ACK_FLAG)
        self.assertEqual(result.returncode, retain.EXIT_CLEAN, result.stdout + result.stderr)
        self.assertIn("acknowledged degraded run", result.stdout)

    def test_unshallowed_clone_recovers_the_comparand_and_catches_the_loss(self):
        # Negative control for the whole mechanism: once the history is real, the same
        # inputs produce the ESTABLISHED loss verdict rather than exit 3. Without this,
        # a check that always exited 3 would pass the assertions above.
        subprocess.run(
            ["git", "-C", str(self.clone), "fetch", "-q", "--unshallow", "origin"],
            capture_output=True, text=True, check=False,
        )
        subprocess.run(
            ["git", "-C", str(self.clone), "fetch", "-q", "origin",
             f"+refs/heads/{self.base}:refs/remotes/origin/{self.base}"],
            capture_output=True, text=True, check=True,
        )
        result = self._run()
        self.assertEqual(result.returncode, retain.EXIT_LOSS, result.stdout + result.stderr)
        self.assertIn("'drop'", result.stdout)


class RetentionSubstitutedComparandTest(_GitFixtureBase):
    """A branch that legitimately PREDATES a key the base tip carries, end to end.

    The mirror image of `RetentionShallowCloneTest`: there, a key really was dropped and
    the degraded comparand must not launder it into a pass. Here NOTHING was dropped —
    the trunk added a key after the fork point and the branch simply never had it — but
    a shallow clone makes `common.merge_base` substitute the trunk's TIP, against which the
    key reads as "absent from head". Reporting that as an exit-1 `a merge/resolution
    dropped it` is a misattribution about a comparison the run never performed, and one
    the developer could not acknowledge away.

    The unshallowed run at the end is the control that proves the difference was an
    artifact of the substitute: with the real merge base, the same tree is CLEAN."""

    prefix = "cm-subst-"

    def setUp(self):
        super().setUp()
        # History BEFORE the map exists — where the shallow boundary lands.
        (self.repo / "README.md").write_text("pad\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-qm", "pre-map")
        # The fork point: the map exists, with the key the branch will carry.
        self._write_map(_base_map(run_sh_blocks={
            "keep": {"note": "kept", "owner": "unmodularized"},
        }))
        self._git("add", "-A")
        self._git("commit", "-qm", "add map")
        self.base = self._base_branch()
        # The branch forks here and never touches the map again.
        self._git("checkout", "-qb", "feature")
        (self.repo / "feature.txt").write_text("work\n", encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "-qm", "feature work, map untouched")
        # The trunk advances PAST the fork and adds a key the branch never had.
        self._git("checkout", "-q", self.base)
        self._write_map(_base_map(run_sh_blocks={
            "keep": {"note": "kept", "owner": "unmodularized"},
            "mainonly": {"note": "added on the trunk after the fork", "owner": "unmodularized"},
        }))
        self._git("add", "-A")
        self._git("commit", "-qm", "trunk adds a key after the fork")

        self.clone = self.tmp / "shallow"
        subprocess.run(
            ["git", "clone", "-q", "--depth", "1", "--branch", "feature",
             str(self.repo), str(self.clone)],
            capture_output=True, text=True, check=True,
        )
        # Shallow-fetch the trunk's TIP. Both sides are depth-1, so the truncated graph
        # holds no common ancestor and `git merge-base` cannot name one.
        subprocess.run(
            ["git", "-C", str(self.clone), "fetch", "-q", "--depth", "1", "origin",
             f"+refs/heads/{self.base}:refs/remotes/origin/{self.base}"],
            capture_output=True, text=True, check=True,
        )

    def _run(self, *extra):
        return subprocess.run(
            ["python3", str(RETAIN_SOURCE), str(self.clone),
             "--base-ref", f"origin/{self.base}", *extra],
            capture_output=True, text=True, check=False,
        )

    def test_precondition_the_fixture_really_degrades_the_comparand(self):
        # Without this the whole class could silently be exercising the SOUND path and
        # asserting nothing: every claim below depends on merge-base failing here.
        merge_base = subprocess.run(
            ["git", "-C", str(self.clone), "merge-base", "HEAD", f"origin/{self.base}"],
            capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(merge_base.returncode, 0, merge_base.stdout)
        _, _, degraded = retain.common.merge_base(self.clone, f"origin/{self.base}")
        self.assertIsNotNone(degraded)

    def test_key_the_branch_predates_is_not_reported_as_a_dropped_key(self):
        result = self._run()
        combined = result.stdout + result.stderr
        # It is NOT an established loss: the branch never had 'mainonly' to drop.
        self.assertEqual(result.returncode, retain.EXIT_UNESTABLISHED, combined)
        self.assertNotEqual(result.returncode, retain.EXIT_LOSS, combined)
        # The difference is still surfaced, but named for what it is...
        self.assertIn("'mainonly'", result.stdout)
        self.assertIn("NOT established losses", result.stdout)
        # ...and the substituted comparand is disclosed, so the misattributing sentence
        # is never read on its own.
        self.assertIn("SUBSTITUTE comparand", result.stdout)
        self.assertIn(f"origin/{self.base}'s own tip", result.stdout)

    def test_the_developer_can_acknowledge_it(self):
        # The second half of the finding: the degraded acknowledgement documented by
        # ACK_FLAG must actually reach this case rather than being outranked by arm 1.
        result = self._run(retain.ACK_FLAG)
        self.assertEqual(result.returncode, retain.EXIT_CLEAN, result.stdout + result.stderr)
        self.assertIn("acknowledged degraded run", result.stdout)

    def test_unshallowed_clone_shows_there_was_never_a_loss(self):
        # The control. Once the real merge base resolves, the SAME tree is clean — which
        # is what makes the exit-1 report above a misattribution rather than a finding.
        subprocess.run(
            ["git", "-C", str(self.clone), "fetch", "-q", "--unshallow", "origin"],
            capture_output=True, text=True, check=False,
        )
        subprocess.run(
            ["git", "-C", str(self.clone), "fetch", "-q", "origin",
             f"+refs/heads/{self.base}:refs/remotes/origin/{self.base}"],
            capture_output=True, text=True, check=True,
        )
        result = self._run()
        self.assertEqual(result.returncode, retain.EXIT_CLEAN, result.stdout + result.stderr)
        self.assertIn("no coverage-map key or content was dropped", result.stdout)

    def test_a_real_loss_against_the_sound_comparand_still_exits_one(self):
        # The invariant the routing must not weaken, driven end to end on this same
        # fixture: with the real history restored, actually dropping a key is an
        # established loss again — exit 1, and ACK_FLAG cannot acknowledge it away.
        subprocess.run(
            ["git", "-C", str(self.clone), "fetch", "-q", "--unshallow", "origin"],
            capture_output=True, text=True, check=False,
        )
        subprocess.run(
            ["git", "-C", str(self.clone), "fetch", "-q", "origin",
             f"+refs/heads/{self.base}:refs/remotes/origin/{self.base}"],
            capture_output=True, text=True, check=True,
        )
        (self.clone / MAP_REL).write_text(_serialize(_base_map(run_sh_blocks={})),
                                          encoding="utf-8")
        for extra in ([], [retain.ACK_FLAG]):
            result = self._run(*extra)
            self.assertEqual(result.returncode, retain.EXIT_LOSS,
                             f"{extra}: {result.stdout}{result.stderr}")
            self.assertIn("'keep'", result.stdout)


class MergeDriverErrorBranchTest(unittest.TestCase):
    """`_run_merge`'s error branches — each must fail the merge, never merge silently."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cm-driver-err-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _path(self, name, value):
        p = self.tmp / name
        p.write_text(value if isinstance(value, str) else _serialize(value), encoding="utf-8")
        return p

    def test_too_few_arguments_is_a_merge_failure(self):
        self.assertEqual(driver._run_merge([]), 2)
        self.assertEqual(driver._run_merge(["a", "b"]), 2)

    def test_missing_ours_input_is_a_merge_failure(self):
        base = self._path("base.json", _base_map())
        theirs = self._path("theirs.json", _base_map())
        rc = driver._run_merge([str(base), str(self.tmp / "absent.json"), str(theirs)])
        self.assertEqual(rc, 2)

    def test_missing_theirs_input_is_a_merge_failure(self):
        base = self._path("base2.json", _base_map())
        ours = self._path("ours2.json", _base_map())
        rc = driver._run_merge([str(base), str(ours), str(self.tmp / "absent2.json")])
        self.assertEqual(rc, 2)

    def test_absent_base_is_a_legitimate_two_way_add_not_a_failure(self):
        # The one absent input that is NOT an error: an ancestor predating the map.
        ours = self._path("ours3.json", _base_map(run_sh_blocks={"a": {"note": "n", "owner": "m"}}))
        theirs = self._path("theirs3.json", _base_map(run_sh_blocks={"b": {"note": "n", "owner": "m"}}))
        rc = driver._run_merge([str(self.tmp / "no-base.json"), str(ours), str(theirs)])
        self.assertEqual(rc, 0)
        merged = json.loads(ours.read_text(encoding="utf-8"))
        self.assertEqual(sorted(merged["run_sh_blocks"]), ["a", "b"])

    def test_unparseable_side_conflicts_rather_than_merging(self):
        base = self._path("base4.json", _base_map())
        unparseable = "{ not json"
        ours = self._path("ours4.json", unparseable)
        theirs = self._path("theirs4.json", _base_map(
            run_sh_blocks={"incoming": {"note": "from theirs", "owner": "m"}}))
        theirs_text = theirs.read_text(encoding="utf-8")

        rc = driver._run_merge([str(base), str(ours), str(theirs)])
        self.assertEqual(rc, 1, "an unparseable side must conflict, never merge silently")

        # Assert the CONSEQUENCES of conflicting, not the presence of git's conflict-marker
        # literal in the file text (which the #810 gate correctly classifies as a
        # source-presence pin). Git adopts %A as the merge result, so all three of these
        # are the behavior that matters: the driver replaced %A with a conflict body; that
        # body does not parse as a coverage map (a parseable one there would BE the silent
        # merge this test exists to prevent); and it carries the incoming side verbatim so
        # a human can actually resolve it.
        body = ours.read_text(encoding="utf-8")
        self.assertNotEqual(body, unparseable, "the driver must write a conflict body into %A")
        with self.assertRaises(json.JSONDecodeError):
            json.loads(body)
        self.assertIn(theirs_text, body)

    def test_canonical_write_failure_is_a_merge_failure(self):
        # A clean merge whose result cannot be written must NOT report success — git
        # would otherwise adopt the unmodified ours-path as the merge result.
        base = self._path("base5.json", _base_map())
        ours = self._path("ours5.json", _base_map(run_sh_blocks={"a": {"note": "n", "owner": "m"}}))
        theirs = self._path("theirs5.json", _base_map(run_sh_blocks={"b": {"note": "n", "owner": "m"}}))
        unwritable = self.tmp / "nodir" / "ours.json"
        original_write = Path.write_bytes

        def refuse(self_path, data):
            if self_path == ours:
                raise OSError("simulated write failure")
            return original_write(self_path, data)

        with unittest.mock.patch.object(Path, "write_bytes", refuse):
            rc = driver._run_merge([str(base), str(ours), str(theirs)])
        self.assertEqual(rc, 2)
        self.assertFalse(unwritable.exists())


class RetentionCheckGitFixtureTest(_GitFixtureBase):
    """The retention CLI end-to-end against an offline git repo (desk == CI inputs)."""

    prefix = "cm-retain-"

    def test_cli_detects_dropped_key_against_merge_base(self):
        self._write_map(_base_map(run_sh_blocks={"431": {"note": "curated", "owner": "unmodularized"}}))
        self._git("add", "-A")
        self._git("commit", "-qm", "base")
        base = self._base_branch()
        self._git("checkout", "-qb", "feature")
        # drop the key
        self._write_map(_base_map(run_sh_blocks={}))
        self._git("commit", "-qam", "drop 431")
        result = subprocess.run(
            ["python3", str(RETAIN_SOURCE), str(self.repo), "--base-ref", base],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("431", result.stdout)

    def test_cli_clean_when_nothing_dropped(self):
        self._write_map(_base_map(run_sh_blocks={"431": {"note": "curated", "owner": "unmodularized"}}))
        self._git("add", "-A")
        self._git("commit", "-qm", "base")
        base = self._base_branch()
        self._git("checkout", "-qb", "feature")
        self._write_map(_base_map(run_sh_blocks={
            "431": {"note": "curated", "owner": "unmodularized"},
            "432": {"note": "new", "owner": "unmodularized"},
        }))
        self._git("commit", "-qam", "add 432")
        result = subprocess.run(
            ["python3", str(RETAIN_SOURCE), str(self.repo), "--base-ref", base],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
