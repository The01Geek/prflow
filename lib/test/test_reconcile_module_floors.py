#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Behavioral tests for measured, raise-only module-floor reconciliation."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "lib/test/reconcile-module-floors.py"
REGISTRY = ROOT / "scripts/workflow-flight-recorder-registry.json"
REAL_RUNNER = ROOT / "lib/test/run-module.sh"


def _load_helper_module():
    """Import reconcile-module-floors.py by path (its hyphenated name blocks a normal
    import), so a test can reuse the helper's OWN compiled `SUMMARY` pattern and its
    `_registry_floor_span` scanner rather than re-spelling either."""
    spec = importlib.util.spec_from_file_location("reconcile_module_floors", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RMF = _load_helper_module()


class FloorReconcilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        (self.root / "lib/test/modules").mkdir(parents=True)
        (self.root / "scripts").mkdir()
        for module_id in ("alpha", "beta"):
            (self.root / f"lib/test/modules/{module_id}.sh").write_text(
                "# fixture module\n", encoding="utf-8"
            )
        self.registry_path = (
            self.root / "scripts/workflow-flight-recorder-registry.json"
        )
        self.run_path = self.root / "lib/test/run.sh"
        self.settings_path = self.root / "scripts/fake-measurements.json"
        self.runner_path = self.root / "lib/test/run-module.sh"
        self.runner_path.write_text(
            """#!/usr/bin/env bash
python3 - "$PWD" "$@" <<'PY'
import json
import os
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
args = sys.argv[2:]
registry = Path(args[args.index("--registry") + 1])
module_id = args[-1]
# Record the exact argv this measurement received, so a test can assert reconcile()
# passed `--heavy-units smoke` for a module in the smoke-bound constant ("with the bound
# in effect"). Benign for every other test, which simply never reads the file.
(root / f"received-argv-{module_id}.json").write_text(json.dumps(args))
if os.environ.get("DEVFLOW_TEST_EXPERIMENT_FORCE_FAILURE") == "1":
    # Mirror lib/test/run-module.sh, which injects a failing assertion when this
    # experiment variable is exported. reconcile() must scrub it from the environment
    # it hands the focused runner; if it leaks through, the measurement is dirty and the
    # run refuses. A test exports it to prove the scrub happens.
    print(f"Module {module_id}: 0 passed, 1 failed")
    raise SystemExit(1)
mapping = json.loads(registry.read_text())["test_modules"][module_id]
if mapping["minimum_assertions"] != 1:
    print("fixture runner: measurement floor was not lowered", file=sys.stderr)
    raise SystemExit(9)
record = json.loads((root / "scripts/fake-measurements.json").read_text())[module_id]
if record.get("require_trimmed_tmpdir"):
    # Root is the one value whose trailing separator is load-bearing: stripping "/"
    # yields the empty string, which is not a directory at all, so the reconciler
    # deliberately preserves it. Every other value must arrive stripped.
    _tmp = os.environ.get("TMPDIR", "")
    if _tmp != "/" and _tmp.endswith("/"):
        print("fixture runner: TMPDIR retained a trailing separator", file=sys.stderr)
        raise SystemExit(8)
    if not _tmp:
        print("fixture runner: TMPDIR was not supplied to the measurement", file=sys.stderr)
        raise SystemExit(8)
if record.get("mutate_run"):
    run_path = root / "lib/test/run.sh"
    run_text = run_path.read_text(encoding="utf-8")
    run_path.write_text(
        re.sub(
            rf'("{re.escape(module_id)}" )[0-9]+(; then)',
            rf'\\g<1>{record["mutate_run"]}\\g<2>',
            run_text,
        ),
        encoding="utf-8",
    )
if not record.get("omit"):
    for _ in range(record.get("copies", 1)):
        suffix = f', {record.get("skipped", 0)} skipped' if record.get("skipped") else ""
        print(
            f'Module {module_id}: {record["passed"]} passed, '
            f'{record.get("failed", 0)} failed{suffix}'
        )
rc = record.get("rc", 0)
if record.get("failed", 0):
    # Mirror the real runner, which sets RUN_RC to 1 whenever FAIL_COUNT is nonzero.
    # Left decoupled, the fake could emit a failed>0 summary alongside rc 0 — a pair
    # the real runner cannot produce — so the case would exercise the reconciler's
    # later not-clean branch instead of the rc gate that actually rejects it first,
    # and the test would attest to a path no real measurement reaches.
    rc = 1
raise SystemExit(rc)
PY
""",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write_contract(
        self,
        alpha_floor: int,
        beta_floor: int,
        *,
        beta_exact: bool = False,
        alpha_description: str | None = None,
        run_alpha_floor: int | None = None,
        run_beta_floor: int | None = None,
        alpha_id: str = "alpha",
    ) -> None:
        """Write the coupled registry/run.sh pair the reconciler reads.

        `run_alpha_floor` / `run_beta_floor` default to the registry values, so the
        common case keeps both coupled sites in sync; passing them explicitly is how a
        test reproduces real-world DESYNC (a hand-edited call site, or a merge that
        resolved only one side), which the reconciler's `or`-joined guards must handle.

        `alpha_id` renames the first exact module so a test can drive a module the
        reconciler recognizes as smoke-bound (a member of `HEAVY_UNIT_SMOKE_MODULES`)
        through the same fixture, proving the `--heavy-units smoke` bound is in effect.
        """
        alpha: dict[str, object] = {
            "path": f"lib/test/modules/{alpha_id}.sh",
            "minimum_assertions": alpha_floor,
            "assertion_floor_policy": "exact",
        }
        if alpha_description is not None:
            alpha["description"] = alpha_description
        beta: dict[str, object] = {
            "path": "lib/test/modules/beta.sh",
            "minimum_assertions": beta_floor,
        }
        if beta_exact:
            beta["assertion_floor_policy"] = "exact"
        self.registry_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "test_modules": {alpha_id: alpha, "beta": beta},
                    "workflows": {"placeholder": {}},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        self.run_path.write_text(
            f"""if ! devflow_run_full_suite_module "$LIB/test/modules/{alpha_id}.sh" \\
  "{alpha_id}" {alpha_floor if run_alpha_floor is None else run_alpha_floor}; then
  exit 1
fi
if ! devflow_run_full_suite_module "$LIB/test/modules/beta.sh" \\
  "beta" {beta_floor if run_beta_floor is None else run_beta_floor}; then
  exit 1
fi
""",
            encoding="utf-8",
        )

    def run_helper(
        self, environment: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "python3",
                str(HELPER),
                "--repo-root",
                str(self.root),
                "--runner",
                str(self.runner_path),
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_measured_increase_raises_both_coupled_sites(self) -> None:
        # Every expectation below is derived from these three, so the test states the
        # measured raise once instead of transcribing `4` into a bare literal that a
        # reader cannot tie back to the measurement that produced it.
        alpha_floor, beta_floor, measured = 2, 3, 4
        self.write_contract(alpha_floor=alpha_floor, beta_floor=beta_floor)
        self.settings_path.write_text(
            json.dumps({"alpha": {"passed": measured}}), encoding="utf-8"
        )

        result = self.run_helper()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertEqual(
            registry["test_modules"]["alpha"]["minimum_assertions"], measured
        )
        self.assertEqual(
            registry["test_modules"]["beta"]["minimum_assertions"], beta_floor
        )
        # Asserting the raised operand reached run.sh is the only thing separating a real
        # coupled raise from one that moved the registry alone.
        self.assertIn(
            f'"alpha" {measured}; then',
            self.run_path.read_text(encoding="utf-8"),
        )

    def test_measured_increase_changes_only_the_selected_numeric_tokens(self) -> None:
        self.write_contract(alpha_floor=2, beta_floor=3)
        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        registry["test_modules"]["beta"]["description"] = "kept byte-for-byte — café"
        before = json.dumps(
            registry, ensure_ascii=False, separators=(",", ":")
        ) + "\n"
        self.registry_path.write_text(before, encoding="utf-8")
        self.settings_path.write_text(
            json.dumps({"alpha": {"passed": 4}}), encoding="utf-8"
        )

        result = self.run_helper()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.registry_path.read_text(encoding="utf-8"),
            before.replace('"minimum_assertions":2', '"minimum_assertions":4', 1),
        )

    def test_measurement_runner_honors_the_devflow_bash_override(self) -> None:
        self.write_contract(alpha_floor=3, beta_floor=5)
        self.settings_path.write_text(
            json.dumps({"alpha": {"passed": 3}}), encoding="utf-8"
        )
        marker = self.root / "devflow-bash-used"
        bash_override = self.root / "selected-bash"
        bash_override.write_text(
            "#!/usr/bin/env bash\n"
            f"printf used > {marker}\n"
            'exec bash "$@"\n',
            encoding="utf-8",
        )
        bash_override.chmod(0o755)
        environment = os.environ.copy()
        environment["DEVFLOW_BASH"] = str(bash_override)

        result = self.run_helper(environment)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(marker.read_text(encoding="utf-8"), "used")

    def test_equal_measurement_is_clean_and_writes_nothing(self) -> None:
        self.write_contract(alpha_floor=3, beta_floor=5)
        self.settings_path.write_text(
            json.dumps({"alpha": {"passed": 3}}), encoding="utf-8"
        )
        before = (self.registry_path.read_bytes(), self.run_path.read_bytes())

        result = self.run_helper()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            (self.registry_path.read_bytes(), self.run_path.read_bytes()), before
        )
        self.assertIn("clean", result.stdout)

    def test_measurement_runner_receives_a_normalized_tmpdir(self) -> None:
        # Set TMPDIR EXPLICITLY rather than relying on the ambient value. The fixture
        # runner's guard reads `os.environ.get("TMPDIR", "").endswith("/")`, which is
        # false when the variable is absent — so on a host that does not export TMPDIR
        # (Linux CI) an ambient-only version of this test passes no matter what the
        # helper does, protecting the normalization on a macOS desk and nothing on the
        # required check.
        for raw in (str(self.root) + "/", "/"):
            with self.subTest(tmpdir=raw):
                self.write_contract(alpha_floor=3, beta_floor=5)
                self.settings_path.write_text(
                    json.dumps(
                        {"alpha": {"passed": 3, "require_trimmed_tmpdir": True}}
                    ),
                    encoding="utf-8",
                )
                environment = os.environ.copy()
                environment["TMPDIR"] = raw

                result = self.run_helper(environment)

                self.assertEqual(
                    result.returncode, 0, result.stdout + result.stderr
                )

    def test_braces_inside_a_string_value_do_not_derail_the_span_scan(self) -> None:
        # The span scanner is a hand-rolled STRING-AWARE depth counter precisely so a
        # brace inside a string VALUE cannot close the module's object early. No other
        # fixture contains one, so neutering the in_string handling leaves every other
        # test green.
        #
        # The decoy is an unbalanced OPEN brace, not a close: a `}` would merely truncate
        # alpha's span AFTER the floor field, which the scan still resolves, so that decoy
        # would not bite. An unmatched `{` inflates the depth instead, running the span
        # past alpha's real closing brace into beta's object, where the floor regex then
        # finds two candidates and the scan refuses. Verified by mutation: neutering the
        # in_string branch turns this test RED and leaves the other twelve green.
        #
        # The complementary half needs no fixture: JSON must escape a `"` inside a string,
        # so the exact literal `"minimum_assertions"` is unrepresentable in a string value
        # and can never be matched there.
        alpha_floor, measured = 2, 4
        adversarial = "guards { an unbalanced open brace"
        self.write_contract(
            alpha_floor=alpha_floor, beta_floor=3, alpha_description=adversarial
        )
        self.settings_path.write_text(
            json.dumps({"alpha": {"passed": measured}}), encoding="utf-8"
        )

        result = self.run_helper()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertEqual(
            registry["test_modules"]["alpha"]["minimum_assertions"], measured
        )
        # The decoy survives byte-for-byte: only the floor digits were rewritten.
        self.assertEqual(
            registry["test_modules"]["alpha"]["description"], adversarial
        )
        self.assertIn(
            f'"alpha" {measured}; then',
            self.run_path.read_text(encoding="utf-8"),
        )

    def test_two_exact_modules_both_raise_at_correct_offsets(self) -> None:
        # Every other fixture marks only alpha exact, so the sequential-offset
        # correctness of a multi-module raise is untested — yet the real registry has
        # eleven exact modules, making this the production case. reconcile()
        # recomputes the span per module because each substitution shifts later
        # offsets and can change digit width; hoisting that out of the loop, or
        # computing against the original text, would still pass every single-module test.
        # Both measurements widen their digit run (9 -> 12, 2 -> 30), which is what makes
        # the per-module span recomputation observable: the first substitution shifts
        # every later offset.
        alpha_measured, beta_measured = 12, 30
        self.write_contract(alpha_floor=9, beta_floor=2, beta_exact=True)
        self.settings_path.write_text(
            json.dumps(
                {
                    "alpha": {"passed": alpha_measured},
                    "beta": {"passed": beta_measured},
                }
            ),
            encoding="utf-8",
        )

        result = self.run_helper()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertEqual(
            registry["test_modules"]["alpha"]["minimum_assertions"], alpha_measured
        )
        self.assertEqual(
            registry["test_modules"]["beta"]["minimum_assertions"], beta_measured
        )
        run_text = self.run_path.read_text(encoding="utf-8")
        self.assertIn(f'"alpha" {alpha_measured}; then', run_text)
        self.assertIn(f'"beta" {beta_measured}; then', run_text)

    def test_every_unclean_module_is_reported_not_only_the_first(self) -> None:
        # The measurements run concurrently and join before anything is reported, so a
        # pass with two bad modules must name BOTH. Under the previous first-failure
        # abort the second module's verdict was never established, and a fix loop paid a
        # second multi-minute pass to discover it.
        self.write_contract(alpha_floor=2, beta_floor=2, beta_exact=True)
        self.settings_path.write_text(
            json.dumps(
                {
                    "alpha": {"passed": 4, "failed": 1},
                    "beta": {"passed": 4, "skipped": 1},
                }
            ),
            encoding="utf-8",
        )
        before = (self.registry_path.read_bytes(), self.run_path.read_bytes())

        result = self.run_helper()

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("alpha:", result.stderr)
        self.assertIn("beta:", result.stderr)
        self.assertEqual(
            (self.registry_path.read_bytes(), self.run_path.read_bytes()), before
        )

    def test_measurement_pool_width_is_bounded_and_honors_the_budget(self) -> None:
        # The width decides how many whole focused-runner processes run at once, so each
        # arm below is a real oversubscription or serialization the pool must not choose.
        cases = (
            # (budget value, module count, expected width)
            (None, 11, RMF.MAX_MEASUREMENT_WORKERS),
            ("2", 11, 2),
            ("99", 11, RMF.MAX_MEASUREMENT_WORKERS),
            ("1", 11, 1),
            # A non-positive or non-numeric export is ignored, never honored: a width of
            # zero would refuse to run anything at all.
            ("0", 11, RMF.MAX_MEASUREMENT_WORKERS),
            ("-3", 11, RMF.MAX_MEASUREMENT_WORKERS),
            ("many", 11, RMF.MAX_MEASUREMENT_WORKERS),
            ("", 11, RMF.MAX_MEASUREMENT_WORKERS),
            # Never wider than the work, and never below one.
            (None, 2, 2),
            (None, 0, 1),
        )
        for budget, count, expected in cases:
            with self.subTest(budget=budget, count=count):
                previous = os.environ.pop("DEVFLOW_SUITE_PROCESS_BUDGET", None)
                if budget is not None:
                    os.environ["DEVFLOW_SUITE_PROCESS_BUDGET"] = budget
                try:
                    self.assertEqual(RMF._measurement_workers(count), expected)
                finally:
                    os.environ.pop("DEVFLOW_SUITE_PROCESS_BUDGET", None)
                    if previous is not None:
                        os.environ["DEVFLOW_SUITE_PROCESS_BUDGET"] = previous

    def test_desynced_coupled_floors_refuse_below_the_higher_site(self) -> None:
        # Real drift: someone hand-edits the run.sh operand, or a merge resolves only
        # one side. The reconciler's decrease guard is `measured < registry or
        # measured < run`, so a tally BETWEEN the two must still refuse.
        self.write_contract(
            alpha_floor=2, beta_floor=3, run_alpha_floor=6
        )
        before = (self.registry_path.read_bytes(), self.run_path.read_bytes())
        self.settings_path.write_text(
            json.dumps({"alpha": {"passed": 4}}), encoding="utf-8"
        )

        result = self.run_helper()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("DECREASE REFUSED", result.stderr)
        self.assertEqual(
            (self.registry_path.read_bytes(), self.run_path.read_bytes()), before
        )

    def test_desynced_coupled_floors_raise_only_the_lagging_site(self) -> None:
        # The mirror of the case above: a tally equal to the HIGHER site is not a
        # decrease, so the lagging registry field is raised into agreement while the
        # already-correct run.sh operand is left byte-identical.
        self.write_contract(
            alpha_floor=2, beta_floor=3, run_alpha_floor=6
        )
        run_before = self.run_path.read_bytes()
        self.settings_path.write_text(
            json.dumps({"alpha": {"passed": 6}}), encoding="utf-8"
        )

        result = self.run_helper()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertEqual(registry["test_modules"]["alpha"]["minimum_assertions"], 6)
        self.assertEqual(self.run_path.read_bytes(), run_before)

    def test_lower_measurement_is_a_nonwriting_judgment(self) -> None:
        self.write_contract(alpha_floor=4, beta_floor=5)
        self.settings_path.write_text(
            json.dumps({"alpha": {"passed": 3}}), encoding="utf-8"
        )
        before = (self.registry_path.read_bytes(), self.run_path.read_bytes())

        result = self.run_helper()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(
            (self.registry_path.read_bytes(), self.run_path.read_bytes()), before
        )
        self.assertIn("DECREASE REFUSED", result.stderr)

    def test_untrustworthy_measurements_are_infrastructure_and_write_nothing(
        self,
    ) -> None:
        cases = {
            "failed process": {"passed": 4, "rc": 1},
            # Rejected at the rc gate, because the fake couples rc to failed exactly as
            # the real runner does. The reconciler's later not-clean branch stays
            # covered by the skipped case below, which the real runner CAN emit with
            # rc 0 — skips do not fail a module run.
            "failed assertion": {"passed": 3, "failed": 1},
            "skipped assertion": {"passed": 4, "skipped": 1},
            "missing summary": {"passed": 4, "omit": True},
            "duplicate summary": {"passed": 4, "copies": 2},
        }
        for label, record in cases.items():
            with self.subTest(label=label):
                self.write_contract(alpha_floor=2, beta_floor=5)
                self.settings_path.write_text(
                    json.dumps({"alpha": record}), encoding="utf-8"
                )
                before = (self.registry_path.read_bytes(), self.run_path.read_bytes())

                result = self.run_helper()

                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(
                    (self.registry_path.read_bytes(), self.run_path.read_bytes()),
                    before,
                )
                self.assertIn("INFRASTRUCTURE", result.stderr)

    def test_missing_coupled_site_is_infrastructure_and_writes_nothing(self) -> None:
        self.write_contract(alpha_floor=2, beta_floor=5)
        self.run_path.write_text("# no alpha boundary\n", encoding="utf-8")
        self.settings_path.write_text(
            json.dumps({"alpha": {"passed": 4}}), encoding="utf-8"
        )
        before = (self.registry_path.read_bytes(), self.run_path.read_bytes())

        result = self.run_helper()

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(
            (self.registry_path.read_bytes(), self.run_path.read_bytes()), before
        )

    def test_coupled_patch_failure_does_not_partially_raise_the_registry(self) -> None:
        self.write_contract(alpha_floor=2, beta_floor=5)
        self.settings_path.write_text(
            json.dumps({"alpha": {"passed": 4, "mutate_run": 99}}),
            encoding="utf-8",
        )
        registry_before = self.registry_path.read_bytes()

        result = self.run_helper()

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(self.registry_path.read_bytes(), registry_before)
        self.assertIn("coupled patch was not applied", result.stderr)

    def test_force_failure_experiment_variable_is_scrubbed_from_the_measurement(
        self,
    ) -> None:
        # AC2 (issue #1498). run-module.sh injects a failing assertion when
        # DEVFLOW_TEST_EXPERIMENT_FORCE_FAILURE is "1" (the fixture runner mirrors that).
        # An operator who left it exported would get a refusal naming a module rather than
        # the override, so reconcile() must scrub it from the environment it hands the
        # focused runner. Exporting it here fails on the pre-fix code (the variable leaks,
        # the fixture runner injects a failure, the run refuses at rc 2) and passes once
        # the scrub lands (measurement clean, normal exit).
        self.write_contract(alpha_floor=3, beta_floor=5)
        self.settings_path.write_text(
            json.dumps({"alpha": {"passed": 3}}), encoding="utf-8"
        )
        before = (self.registry_path.read_bytes(), self.run_path.read_bytes())
        environment = os.environ.copy()
        environment["DEVFLOW_TEST_EXPERIMENT_FORCE_FAILURE"] = "1"

        result = self.run_helper(environment)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("clean", result.stdout)
        # A clean measurement equal to both floors writes nothing.
        self.assertEqual(
            (self.registry_path.read_bytes(), self.run_path.read_bytes()), before
        )

    def test_measurement_argv_appends_heavy_units_only_for_constant_members(
        self,
    ) -> None:
        # AC1/AC2 (issue #1499). _measurement_argv appends `--heavy-units smoke` for a
        # module in HEAVY_UNIT_SMOKE_MODULES and, for a module absent from it, returns an
        # argv byte-identical to today's with no --heavy-units token — both directions.
        self.assertTrue(
            RMF.HEAVY_UNIT_SMOKE_MODULES, "the smoke-bound constant is empty"
        )
        runner = Path("/x/run-module.sh")
        registry = Path("/x/registry.json")
        log_dir = Path("/x/logs")
        head = os.environ.get("DEVFLOW_BASH") or "bash"
        baseline_prefix = [
            head,
            str(runner),
            "--registry",
            str(registry),
            "--log-dir",
            str(log_dir),
        ]

        member = min(RMF.HEAVY_UNIT_SMOKE_MODULES)
        member_argv = RMF._measurement_argv(runner, registry, log_dir, member)
        # The flag pair is present, adjacent, and sits immediately before the module id,
        # which stays last (the fixture runner and reconcile() both read args[-1]).
        self.assertEqual(member_argv, baseline_prefix + ["--heavy-units", "smoke", member])

        absent = "definitely-not-a-smoke-bound-module"
        self.assertNotIn(absent, RMF.HEAVY_UNIT_SMOKE_MODULES)
        absent_argv = RMF._measurement_argv(runner, registry, log_dir, absent)
        self.assertNotIn("--heavy-units", absent_argv)
        # Byte-identical to the pre-change argv: prefix plus the module id, nothing else.
        self.assertEqual(absent_argv, baseline_prefix + [absent])

    def test_every_smoke_bound_module_reads_the_heavy_unit_mode(self) -> None:
        # AC3 (issue #1499). Every module in the constant must be an exact-policy module
        # whose module file actually reads MODULE_HEAVY_UNIT_MODE — derived from the tree,
        # so a module that ignores the flag can never be listed (a bound that bounds
        # nothing would be a no-op that only adds the runner's notice line to the log).
        self.assertTrue(
            RMF.HEAVY_UNIT_SMOKE_MODULES, "the smoke-bound constant is empty"
        )
        modules = json.loads(REGISTRY.read_text(encoding="utf-8"))["test_modules"]
        modules_dir = ROOT / "lib/test/modules"
        # Derive, from the tree, the set of exact-policy modules whose source consumes
        # MODULE_HEAVY_UNIT_MODE, then assert the constant is a subset of it — so a module
        # that ignores the flag can never be listed (its bound would be a no-op). Building
        # the set from the tree (rather than asserting presence per module) is what keeps
        # this contract self-maintaining as the constant or the module set changes.
        mode_readers = {
            module_id
            for module_id, mapping in modules.items()
            if isinstance(mapping, dict)
            and mapping.get("assertion_floor_policy") == "exact"
            and (modules_dir / f"{module_id}.sh").is_file()
            and "MODULE_HEAVY_UNIT_MODE"
            in (modules_dir / f"{module_id}.sh").read_text(encoding="utf-8")
        }
        smoke_set = set(RMF.HEAVY_UNIT_SMOKE_MODULES)
        self.assertLessEqual(
            smoke_set,
            mode_readers,
            "smoke-bound modules that are not exact-policy MODULE_HEAVY_UNIT_MODE "
            f"readers: {sorted(smoke_set - mode_readers)}",
        )

    def test_decrease_refused_with_the_heavy_unit_bound_in_effect(self) -> None:
        # AC7 (issue #1499). A measured tally below either coupled floor still exits
        # non-clean with DECREASE REFUSED and leaves both declared outputs byte-unchanged
        # — asserted with the bound in effect (the measured module is a real constant
        # member, and the fixture records that reconcile passed --heavy-units smoke), so
        # the bound cannot silently lower a floor.
        smoke_module = min(RMF.HEAVY_UNIT_SMOKE_MODULES)
        self.write_contract(alpha_floor=4, beta_floor=5, alpha_id=smoke_module)
        self.settings_path.write_text(
            json.dumps({smoke_module: {"passed": 3}}), encoding="utf-8"
        )
        before = (self.registry_path.read_bytes(), self.run_path.read_bytes())

        result = self.run_helper()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("DECREASE REFUSED", result.stderr)
        self.assertEqual(
            (self.registry_path.read_bytes(), self.run_path.read_bytes()), before
        )
        # The bound was actually in effect: reconcile passed `--heavy-units smoke`, with
        # the module id still last.
        received = json.loads(
            (self.root / f"received-argv-{smoke_module}.json").read_text(
                encoding="utf-8"
            )
        )
        # `received` is the runtime argv the fixture recorded (what THIS run produced),
        # not repository source, so these are executable-argv-contract assertions: the
        # index() lookup raises if reconcile did not pass `--heavy-units`, and the
        # assertEqual then pins that it was followed by `smoke` and the module id last.
        self.assertEqual(received[received.index("--heavy-units") + 1], "smoke")
        self.assertEqual(received[-1], smoke_module)

    def _write_raw_registry(self, text: str) -> None:
        """Overwrite the registry with crafted SOURCE text (not json.dumps output), used
        by the `_registry_floor_span` refusal tests that need a specific byte layout."""
        self.registry_path.write_text(text, encoding="utf-8")

    def test_duplicate_registry_key_refuses_and_writes_nothing(self) -> None:
        # AC9 (issue #1498) — _registry_floor_span's first None return: the module key is
        # matched more than once in the registry SOURCE. A measured raise reaches the span
        # scanner, which refuses an ambiguous key match rather than rewrite the wrong
        # object, and the reconciler exits under the INFRASTRUCTURE contract.
        self.write_contract(alpha_floor=2, beta_floor=3)
        self._write_raw_registry(
            json.dumps(
                {
                    "schema_version": 1,
                    "test_modules": {
                        "alpha": {
                            "path": "lib/test/modules/alpha.sh",
                            "minimum_assertions": 2,
                            "assertion_floor_policy": "exact",
                        },
                        "beta": {
                            "path": "lib/test/modules/beta.sh",
                            "minimum_assertions": 3,
                        },
                    },
                    # A decoy key of the same name in an unrelated object makes the source
                    # match `"alpha"\s*:\s*{` twice while json still parses (one entry).
                    "workflows": {"alpha": {}},
                },
                indent=2,
            )
            + "\n"
        )
        self.settings_path.write_text(
            json.dumps({"alpha": {"passed": 4}}), encoding="utf-8"
        )
        before = (self.registry_path.read_bytes(), self.run_path.read_bytes())

        result = self.run_helper()

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("could not uniquely locate its registry floor token", result.stderr)
        self.assertEqual(
            (self.registry_path.read_bytes(), self.run_path.read_bytes()), before
        )

    def test_duplicate_floor_token_in_module_object_refuses_and_writes_nothing(
        self,
    ) -> None:
        # AC9 (issue #1498) — _registry_floor_span's third None return: a
        # `minimum_assertions` token matched other than exactly once inside the module's
        # own object. A nested object carrying a second `minimum_assertions` keeps the JSON
        # valid (parsed floor is the top-level 2) while the span scan finds two candidates
        # and refuses.
        self.write_contract(alpha_floor=2, beta_floor=3)
        self._write_raw_registry(
            json.dumps(
                {
                    "schema_version": 1,
                    "test_modules": {
                        "alpha": {
                            "path": "lib/test/modules/alpha.sh",
                            "minimum_assertions": 2,
                            "assertion_floor_policy": "exact",
                            "nested": {"minimum_assertions": 9},
                        },
                        "beta": {
                            "path": "lib/test/modules/beta.sh",
                            "minimum_assertions": 3,
                        },
                    },
                },
                indent=2,
            )
            + "\n"
        )
        self.settings_path.write_text(
            json.dumps({"alpha": {"passed": 4}}), encoding="utf-8"
        )
        before = (self.registry_path.read_bytes(), self.run_path.read_bytes())

        result = self.run_helper()

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("could not uniquely locate its registry floor token", result.stderr)
        self.assertEqual(
            (self.registry_path.read_bytes(), self.run_path.read_bytes()), before
        )

    def test_registry_with_no_exact_module_is_infrastructure_and_writes_nothing(
        self,
    ) -> None:
        # AC10 (issue #1498) — a registry declaring no `exact` module makes the reconciler
        # refuse under the INFRASTRUCTURE contract before any measurement, writing nothing.
        self.write_contract(alpha_floor=2, beta_floor=3)
        self._write_raw_registry(
            json.dumps(
                {
                    "schema_version": 1,
                    "test_modules": {
                        "alpha": {
                            "path": "lib/test/modules/alpha.sh",
                            "minimum_assertions": 2,
                        },
                        "beta": {
                            "path": "lib/test/modules/beta.sh",
                            "minimum_assertions": 3,
                        },
                    },
                },
                indent=2,
            )
            + "\n"
        )
        before = (self.registry_path.read_bytes(), self.run_path.read_bytes())

        result = self.run_helper()

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(
            "the registry selects no exact assertion-floor modules", result.stderr
        )
        self.assertEqual(
            (self.registry_path.read_bytes(), self.run_path.read_bytes()), before
        )


class RegistryFloorSpanUnitTests(unittest.TestCase):
    def test_unbalanced_module_object_returns_none_from_the_span_scan(self) -> None:
        # AC9 (issue #1498) — _registry_floor_span's second None return: the module
        # object's brace scan never returns to depth zero.
        #
        # This branch is UNREACHABLE end-to-end through reconcile(): reconcile() runs
        # json.loads(registry_text) before scanning the same text, and JSON and the
        # string-aware scanner agree on string escaping, so any text whose scan overruns
        # fails json.loads first (a different INFRASTRUCTURE refusal). The defensive guard
        # is therefore driven directly against the scanner rather than through the
        # reconciler's exit contract. See the issue's AC9 issue-accuracy note.
        overrunning = '"alpha": { "nested": { "minimum_assertions": 2 }'
        self.assertIsNone(RMF._registry_floor_span(overrunning, "alpha"))

    def test_a_balanced_module_object_locates_its_floor(self) -> None:
        # Positive control so the None assertion above is not vacuous.
        balanced = (
            '{ "test_modules": { "alpha": '
            '{ "minimum_assertions": 2, "assertion_floor_policy": "exact" } } }'
        )
        span = RMF._registry_floor_span(balanced, "alpha")
        self.assertIsNotNone(span)
        self.assertEqual(balanced[span[0] : span[1]], "2")


class RealRunnerContractTests(unittest.TestCase):
    def test_reconciler_summary_matches_the_real_runner_for_the_cheapest_module(
        self,
    ) -> None:
        # AC7 / AC8 (issue #1498). Drive the REAL lib/test/run-module.sh — never a double
        # — over the exact-policy module with the lowest minimum_assertions (resolved from
        # the registry, so the choice stays self-maintaining and cheap), passing the exact
        # flag set reconcile() builds, and assert the reconciler's own compiled SUMMARY
        # pattern matches exactly one line of that runner's stdout for that module id.
        registry_data = json.loads(REGISTRY.read_text(encoding="utf-8"))
        modules = registry_data["test_modules"]
        exact = {
            module_id: mapping
            for module_id, mapping in modules.items()
            if isinstance(mapping, dict)
            and mapping.get("assertion_floor_policy") == "exact"
        }
        self.assertTrue(exact, "the registry declares no exact-policy modules")
        module_id = min(exact, key=lambda mid: exact[mid]["minimum_assertions"])

        with tempfile.TemporaryDirectory(prefix="devflow-ac7-") as temporary:
            temporary_path = Path(temporary)
            # Lower the target module's floor to 1 exactly as reconcile() does for its
            # measurement registry, so a passing focused run cannot be refused for a floor.
            measurement = copy.deepcopy(registry_data)
            measurement["test_modules"][module_id]["minimum_assertions"] = 1
            measurement_registry = temporary_path / "registry.json"
            measurement_registry.write_text(
                json.dumps(measurement, indent=2) + "\n", encoding="utf-8"
            )
            log_dir = temporary_path / f"logs-{module_id}"
            proc = subprocess.run(
                [
                    os.environ.get("DEVFLOW_BASH") or "bash",
                    str(REAL_RUNNER),
                    "--registry",
                    str(measurement_registry),
                    "--log-dir",
                    str(log_dir),
                    module_id,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        matches = [
            match
            for match in RMF.SUMMARY.finditer(proc.stdout)
            if match.group("module") == module_id
        ]
        self.assertEqual(len(matches), 1, proc.stdout + proc.stderr)
        summary = matches[0]
        self.assertEqual(int(summary.group("failed")), 0, proc.stdout)
        self.assertIn(summary.group("skipped"), (None, "0"), proc.stdout)
        self.assertGreater(int(summary.group("passed")), 0, proc.stdout)

    def test_reconciler_summary_matches_the_real_runner_for_a_smoke_bounded_module(
        self,
    ) -> None:
        # AC6 (issue #1499). Drive the REAL run-module.sh over a module in the
        # smoke-bound constant, under `--heavy-units smoke`, and assert the reconciler's
        # own SUMMARY pattern still matches exactly one line for that module id — the
        # runner's extra `heavy units REQUESTED bounded` notice line, printed only on a
        # bounded run, must not break reconcile()'s parse.
        smoke_modules = sorted(RMF.HEAVY_UNIT_SMOKE_MODULES)
        self.assertTrue(smoke_modules, "the smoke-bound constant is empty")
        module_id = smoke_modules[0]
        registry_data = json.loads(REGISTRY.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory(prefix="devflow-ac6-") as temporary:
            temporary_path = Path(temporary)
            # Lower the target module's floor to 1 exactly as reconcile() does, so a
            # passing bounded run cannot be refused for a floor.
            measurement = copy.deepcopy(registry_data)
            measurement["test_modules"][module_id]["minimum_assertions"] = 1
            measurement_registry = temporary_path / "registry.json"
            measurement_registry.write_text(
                json.dumps(measurement, indent=2) + "\n", encoding="utf-8"
            )
            log_dir = temporary_path / f"logs-{module_id}"
            # Mirror the exact argv reconcile() builds for a smoke-bound module (module id
            # last, `--heavy-units smoke` immediately before it).
            proc = subprocess.run(
                [
                    os.environ.get("DEVFLOW_BASH") or "bash",
                    str(REAL_RUNNER),
                    "--registry",
                    str(measurement_registry),
                    "--log-dir",
                    str(log_dir),
                    "--heavy-units",
                    "smoke",
                    module_id,
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        matches = [
            match
            for match in RMF.SUMMARY.finditer(proc.stdout)
            if match.group("module") == module_id
        ]
        self.assertEqual(len(matches), 1, proc.stdout + proc.stderr)
        self.assertEqual(int(matches[0].group("failed")), 0, proc.stdout)
        self.assertGreater(int(matches[0].group("passed")), 0, proc.stdout)
        # The bounded-run notice WAS emitted (proving smoke was in effect) yet did not
        # itself register as a SUMMARY match above — the parse-safety AC6 pins.
        self.assertIn("heavy units REQUESTED bounded", proc.stdout)


if __name__ == "__main__":
    unittest.main()
