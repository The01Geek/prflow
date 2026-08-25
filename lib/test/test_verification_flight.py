#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Focused tests for the single-flight verification coordination ledger (#528).

Covers the full issue #528 acceptance matrix: concurrent claims -> one owner,
token secrecy/replay, compare-and-swap, atomic publication, owner loss before and
during running, the complete JSON-shape matrix, every declared input drift, an
undeclared / non-hermetic profile, stale ownership, linked worktrees,
subdirectories, descriptor mismatch, wait expiry, skipped checks, failure
propagation, and successful attachment.

The helper is hyphenated (scripts/verification-flight.py) so it is loaded via
importlib.util.spec_from_file_location, the same workaround the hyphenated-script
tests use elsewhere in this suite.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

#: Single source of truth for the no-execution sweep (issue #528).
#:
#: The helper's headline contract is that it "launches no subprocess, accepts no
#: executable argv, and cannot become a shell-command bypass". A guard that
#: enumerates only *some* spellings certifies that contract against its own blind
#: spot: the original sweep listed 10 spellings, so a future edit reaching for
#: `os.posix_spawn`, `os.fork`, `multiprocessing`, `ctypes`, `runpy`, or
#: `asyncio.create_subprocess_exec` would have passed both guards while breaking
#: the contract outright. This tuple is the *population* — the process-spawn and
#: dynamic-code-execution surface of the CPython standard library — not a sample.
#:
#: `lib/test/run.sh` builds its own grep sweep by reading THIS tuple (python3 is a
#: hard preflight prerequisite), so the shell guard and the Python guard are
#: structurally single-sourced and cannot drift into disagreeing coverage.
BANNED_EXEC_SPELLINGS = (
    "import subprocess",
    "from subprocess import",
    "subprocess.",
    "os.system",
    "os.popen",
    "os.exec",
    "os.spawn",
    "os.posix_spawn",
    "os.fork",
    "os.forkpty",
    "import pty",
    "pty.spawn",
    "pty.fork",
    "import multiprocessing",
    "multiprocessing.",
    "asyncio.create_subprocess",
    "import ctypes",
    "ctypes.",
    "import runpy",
    "runpy.",
    "getoutput",
    "check_output",
    "__import__",
)

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "verification_flight", ROOT / "scripts" / "verification-flight.py"
)
vf = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vf)

# The producer is hyphenated too — load it the same way for the unit-level tests
# (the subprocess tests run it as a CLI; the backdate fail-closed test drives an
# internal helper).
_CF_SPEC = importlib.util.spec_from_file_location(
    "checkout_fingerprint", ROOT / "scripts" / "checkout-fingerprint.py"
)
cf = importlib.util.module_from_spec(_CF_SPEC)
_CF_SPEC.loader.exec_module(cf)


# A valid checkout fingerprint (issue #1243): the four content fields are git object
# ids (40-hex here), the shape scripts/checkout-fingerprint.py emits and
# _validate_checkout now REQUIRES. checkout_id is the opaque git-dir path, not shape-
# checked, so it stays an arbitrary non-empty string. Pre-#1243 this helper wrote junk
# like "abc"/"i1"; those are now rejected, so every checkout literal routes through here.
_BASE_CHECKOUT = {
    "checkout_id": "r1",
    "head": "a" * 40,
    "index_digest": "b" * 40,
    "tracked_digest": "c" * 40,
    "untracked_digest": "d" * 40,
}


def _hexid(seed) -> str:
    """A distinct-but-valid 40-hex object id from an arbitrary seed (drift tests)."""
    return hashlib.sha1(str(seed).encode("utf-8")).hexdigest()


def _ck(**over) -> dict:
    """A valid checkout dict, overriding fields (each override must be validly shaped)."""
    return {**_BASE_CHECKOUT, **over}


def _decl(**over):
    profile = {
        "profile_version": 1,
        "argv": ["lib/test/run.sh"],
        "cwd": "/repo",
        "environment": {"CI": "1"},
        "toolchain": {"bash": "5.2"},
        "dependencies": {"jq": "1.7"},
        "output_roots": [".prflow/tmp"],
        "external_services": "none",
    }
    checkout = dict(_BASE_CHECKOUT)
    d = {"schema_version": 1, "profile": profile, "checkout": checkout}
    for k, v in over.items():
        if k in ("profile", "checkout"):
            d[k] = {**d[k], **v}
        else:
            d[k] = v
    return d


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state = os.path.join(self.tmp, "state")
        self.logs = os.path.join(self.tmp, "logs")
        # Neutralize any ambient DEVFLOW_FLIGHT_NOW so tests set it explicitly.
        os.environ.pop("DEVFLOW_FLIGHT_NOW", None)

    def tearDown(self):
        os.environ.pop("DEVFLOW_FLIGHT_NOW", None)

    def _write(self, obj) -> str:
        path = os.path.join(self.tmp, f"in-{os.urandom(4).hex()}.json")
        Path(path).write_text(json.dumps(obj), encoding="utf-8")
        return path

    def run_cmd(self, argv):
        """Run the CLI, returning (exit_code, parsed_stdout_or_None)."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = vf.main(argv)
        out = buf.getvalue().strip()
        parsed = None
        if out:
            try:
                parsed = json.loads(out.splitlines()[-1])
            except json.JSONDecodeError:
                parsed = None
        return code, parsed

    def run_cmd_expecting_exit(self, argv):
        """Run the CLI for a path that exits via SystemExit (argparse usage errors)."""
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                code = vf.main(argv)
        except SystemExit as exc:
            code = exc.code
        out = buf.getvalue().strip()
        parsed = json.loads(out.splitlines()[-1]) if out else None
        return code, parsed

    def claim(self, decl=None, lease=None):
        decl = decl if decl is not None else _decl()
        argv = ["claim", "--input-file", self._write(decl),
                "--state-dir", self.state, "--logs-dir", self.logs]
        if lease is not None:
            argv += ["--lease-seconds", str(lease)]
        return self.run_cmd(argv)


class TestDescriptorAndKey(Harness):
    def test_descriptor_deterministic(self):
        c1, o1 = self.run_cmd(["descriptor", "--input-file", self._write(_decl())])
        c2, o2 = self.run_cmd(["descriptor", "--input-file", self._write(_decl())])
        self.assertEqual(c1, vf.EXIT_OK)
        self.assertEqual(o1["descriptor_digest"], o2["descriptor_digest"])
        self.assertEqual(o1["flight_key"], o2["flight_key"])

    def test_byte_distinct_argv_distinct_descriptor(self):
        _, base = self.run_cmd(["descriptor", "--input-file", self._write(_decl())])
        _, alt = self.run_cmd(["descriptor", "--input-file",
                               self._write(_decl(profile={"argv": ["lib/test/run.sh", "--x"]}))])
        self.assertNotEqual(base["descriptor_digest"], alt["descriptor_digest"])

    def test_checkout_drift_distinct_flight_key_same_descriptor(self):
        _, base = self.run_cmd(["descriptor", "--input-file", self._write(_decl())])
        _, moved = self.run_cmd(["descriptor", "--input-file",
                                 self._write(_decl(checkout={"head": _hexid("def")}))])
        self.assertEqual(base["descriptor_digest"], moved["descriptor_digest"])
        self.assertNotEqual(base["flight_key"], moved["flight_key"])

    def test_output_roots_excluded_from_descriptor(self):
        # Negative pin (issue #528, S8): the descriptor is derived ONLY from the
        # identity operands {profile_version, argv, cwd, environment, toolchain,
        # dependencies}. `output_roots` is validated but deliberately NOT part of the
        # descriptor — it is a declared surface, not identity. If a regression added
        # it to `_descriptor_bytes`, byte-varying it would churn the descriptor (and
        # thus the flight key), silently defeating ALL reuse for callers that differ
        # only in `output_roots`. Assert exclusion so that regression fails RED here.
        #
        # SCOPE (issue #579 review): this pins ONLY `output_roots`, because it is the
        # only excluded field that can be *varied* in a valid declaration.
        # `external_services` is also excluded from the descriptor, but a valid
        # profile can only ever carry `external_services: "none"` (`_validate_profile`
        # rejects every other value), so a constant field cannot churn the key and no
        # differential test can falsify its exclusion — `test_external_services_only_none`
        # pins that invariant instead. Do not re-widen this test's name/claim to imply
        # a guard it cannot provide.
        base = self.run_cmd(["descriptor", "--input-file", self._write(_decl())])[1]
        moved_roots = self.run_cmd([
            "descriptor", "--input-file",
            self._write(_decl(profile={"output_roots": [".prflow/tmp", "build/"]})),
        ])[1]
        self.assertEqual(
            base["descriptor_digest"], moved_roots["descriptor_digest"],
            "output_roots must NOT be part of the command descriptor",
        )
        self.assertEqual(
            base["flight_key"], moved_roots["flight_key"],
            "an output_roots-only difference must not churn the flight key",
        )

    def test_external_services_only_none(self):
        # The reason `test_output_roots_excluded_from_descriptor` cannot also pin
        # `external_services` exclusion differentially: a valid profile's
        # `external_services` is invariantly "none". Any other value is rejected at
        # declaration time, so it can never reach `_descriptor_bytes` as a varying
        # operand. Pin that gate directly.
        code, out = self.claim(_decl(profile={"external_services": "local"}))
        self.assertEqual(code, vf.EXIT_INVALID)
        self.assertEqual(out["reason"], "non_hermetic_profile")

    def test_each_descriptor_operand_shifts_digest(self):
        base = self.run_cmd(["descriptor", "--input-file", self._write(_decl())])[1]["descriptor_digest"]
        for over in (
            {"profile_version": 2},
            {"cwd": "/other"},
            {"environment": {"CI": "2"}},
            {"toolchain": {"bash": "5.3"}},
            {"dependencies": {"jq": "1.8"}},
        ):
            d = self.run_cmd(["descriptor", "--input-file",
                              self._write(_decl(profile=over))])[1]["descriptor_digest"]
            self.assertNotEqual(base, d, f"operand {over} did not change descriptor")


class TestClaimAndAttach(Harness):
    def test_claim_owner_then_attach(self):
        code, owner = self.claim()
        self.assertEqual(code, vf.EXIT_OK)
        self.assertEqual(owner["role"], "owner")
        self.assertEqual(owner["state"], "claimed")
        self.assertIn("token", owner)
        # A matching active flight returns the handle without a second owner.
        code2, att = self.claim()
        self.assertEqual(code2, vf.EXIT_OK)
        self.assertEqual(att["role"], "attacher")
        self.assertNotIn("token", att)
        self.assertEqual(att["flight_key"], owner["flight_key"])

    def test_atomic_single_owner_no_second_token(self):
        _, owner = self.claim()
        # Simulate a concurrent second claim on the same key: O_CREAT|O_EXCL
        # means only the first create wins; the rest attach.
        tokens = set()
        for _ in range(5):
            _, res = self.claim()
            if res.get("role") == "owner":
                tokens.add(res["token"])
        self.assertEqual(tokens, set(), "a second owner token was granted for an active flight")

    def test_token_persisted_only_as_digest(self):
        _, owner = self.claim()
        path = Path(self.state) / f"{owner['flight_key']}.json"
        body = json.loads(path.read_text())
        self.assertNotIn("token", body)
        self.assertEqual(body["token_digest"], vf._sha256(owner["token"].encode()))
        self.assertNotEqual(body["token_digest"], owner["token"])

    def test_status_redacts_token(self):
        _, owner = self.claim()
        _, st = self.run_cmd(["status", "--flight", owner["flight_key"], "--state-dir", self.state])
        self.assertEqual(st["token_digest"], "REDACTED")

    def test_status_on_claimed_is_non_pass(self):
        # The two ACTIVE states (claimed/running) must NEVER satisfy verification —
        # the exact "unknown becomes a pass" regression this ledger exists to prevent.
        # Every terminal non-pass state is asserted elsewhere; these pin the active
        # ones, so a mutation widening `_satisfies` to an active state fails RED
        # (issue #579 review).
        _, owner = self.claim()
        code, st = self.run_cmd(["status", "--flight", owner["flight_key"], "--state-dir", self.state])
        self.assertEqual(st["state"], "claimed")
        self.assertFalse(st["satisfies_verification"], "a claimed flight must not satisfy verification")
        self.assertFalse(st["reuse_ready"], "a claimed flight is never reuse_ready")
        self.assertEqual(code, vf.EXIT_NON_PASS)

    def test_status_on_running_is_non_pass(self):
        _, owner = self.claim()
        k, t = owner["flight_key"], owner["token"]
        self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
        code, st = self.run_cmd(["status", "--flight", k, "--state-dir", self.state])
        self.assertEqual(st["state"], "running")
        self.assertFalse(st["satisfies_verification"], "a running flight must not satisfy verification")
        self.assertFalse(st["reuse_ready"], "a running flight is never reuse_ready")
        self.assertEqual(code, vf.EXIT_NON_PASS)

    def test_reuse_ready_requires_verified_checkout(self):
        # issue #1243: status/wait enforce the checkout AND themselves — a bare
        # status over a `passed` handle does NOT report a pass or exit 0, because the
        # working tree was never verified. `reuse_ready` mirrors the effective
        # verdict, and a safe consume (`reuse_ready and checkout_verified`) is the
        # ONLY path to EXIT_OK unless the explicit weaker read is requested.
        _, owner = self.claim()
        k, t = owner["flight_key"], owner["token"]
        chk = self._write(_ck())
        self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
        self.run_cmd(["finish", "--flight", k, "--token", t, "--result", "passed",
                      "--summary-file", self._write({"command": "x", "exit_status": 0, "skipped_checks": []}),
                      "--state-dir", self.state, "--logs-dir", self.logs])
        # No current-checkout: the tree is unverified, so this is NOT a reusable pass.
        code, st = self.run_cmd(["status", "--flight", k, "--state-dir", self.state])
        self.assertEqual(code, vf.EXIT_NON_PASS)
        self.assertFalse(st["reuse_ready"], "an unverified-checkout read is never reuse_ready")
        self.assertEqual(st["reuse_ready"], st["satisfies_verification"])
        self.assertFalse(st["checkout_verified"], "a bare status verifies no checkout")
        # Matching current-checkout: checkout_verified True AND the flight passes.
        code2, st2 = self.run_cmd(["status", "--flight", k, "--state-dir", self.state,
                                   "--current-checkout-file", chk])
        self.assertEqual(code2, vf.EXIT_OK)
        self.assertTrue(st2["checkout_verified"])
        self.assertTrue(st2["reuse_ready"])
        self.assertTrue(st2["satisfies_verification"])
        # Explicit weaker read: the state/evidence dimension alone, opt-in.
        code3, st3 = self.run_cmd(["status", "--flight", k, "--state-dir", self.state,
                                   "--allow-unverified-checkout"])
        self.assertEqual(code3, vf.EXIT_OK)
        self.assertTrue(st3["reuse_ready"])
        self.assertFalse(st3["checkout_verified"],
                         "the weaker read still reports the tree was not verified")

    def test_attach_to_passed_flight_consumes_prior_pass(self):
        # The ledger's raison d'être: a later same-checkout caller attaches to a
        # TERMINAL `passed` flight and consumes the prior pass — relaunch
        # suppressed. (Every other attach test attaches to a still-`claimed`
        # flight; this exercises the terminal-attach path the ledger exists for.)
        _, owner = self.claim()
        k, t = owner["flight_key"], owner["token"]
        self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
        self.run_cmd(["finish", "--flight", k, "--token", t, "--result", "passed",
                      "--summary-file", self._write({"command": "x", "exit_status": 0, "skipped_checks": []}),
                      "--state-dir", self.state, "--logs-dir", self.logs])
        # A later caller with the identical declaration attaches — no second owner.
        code, att = self.claim()
        self.assertEqual(code, vf.EXIT_OK)
        self.assertEqual(att["role"], "attacher")
        self.assertNotIn("token", att, "a terminal-attach must never mint a second owner token")
        self.assertEqual(att["state"], "passed")
        self.assertEqual(att["flight_key"], k)
        self.assertTrue(
            att["satisfies_verification"],
            "attaching to a passed flight must report the consumable prior pass so the "
            "caller can suppress relaunch",
        )


    def test_attach_candidate_identity_mismatch_is_not_a_reusable_pass(self):
        # Issue #550 (closing the PR #681 attach-path residual): candidate_identity
        # is OUTSIDE the flight key by design, so two declarations sharing a checkout
        # fingerprint but declaring DIFFERENT content identities map to ONE handle.
        # Before #550 the attacher silently received the first claimer's value and
        # could consume its `passed` handle for a DIFFERENT content identity. Now the
        # attacher whose own declared candidate_identity differs is NOT a reusable
        # pass: reuse_ready / satisfies_verification are False and
        # candidate_identity_match is False, so it launches its own verification.
        d_a = _decl(candidate_identity="tree-AAAA")
        d_b = _decl(candidate_identity="tree-BBBB")
        # flight_key and descriptor_digest stay byte-UNCHANGED across the two (and vs
        # a declaration with NO candidate_identity) — the field is outside the key.
        _, desc_a = self.run_cmd(["descriptor", "--input-file", self._write(d_a)])
        _, desc_b = self.run_cmd(["descriptor", "--input-file", self._write(d_b)])
        _, desc_none = self.run_cmd(["descriptor", "--input-file", self._write(_decl())])
        self.assertEqual(desc_a["flight_key"], desc_b["flight_key"])
        self.assertEqual(desc_a["flight_key"], desc_none["flight_key"])
        self.assertEqual(desc_a["descriptor_digest"], desc_b["descriptor_digest"])
        self.assertEqual(desc_a["descriptor_digest"], desc_none["descriptor_digest"])
        # Owner claims + passes with identity A; attacher declares identity B.
        _, owner = self.claim(d_a)
        k, t = owner["flight_key"], owner["token"]
        self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
        self.run_cmd(["finish", "--flight", k, "--token", t, "--result", "passed",
                      "--summary-file", self._write({"command": "x", "exit_status": 0, "skipped_checks": []}),
                      "--state-dir", self.state, "--logs-dir", self.logs])
        code, att = self.claim(d_b)
        self.assertEqual(code, vf.EXIT_OK)
        self.assertEqual(att["role"], "attacher")
        self.assertEqual(att["flight_key"], k, "the handle is still shared by flight key")
        self.assertFalse(att["candidate_identity_match"])
        self.assertFalse(att["reuse_ready"],
                         "a candidate_identity mismatch is not a reusable pass")
        self.assertFalse(att["satisfies_verification"])

    def test_attach_declared_identity_against_stored_none_is_not_reusable(self):
        # The asymmetric arm of the same residual: the OWNER declared NO
        # candidate_identity (a pre-#668 producer), so the handle records None, while
        # the attacher DOES declare one. Nothing observable proves the stored pass
        # covers the attacher's content, so it must NOT be reusable — treating the
        # unprovable pair as a match would fail OPEN. Positive control: the identical
        # fixture with a matching stored identity IS reusable
        # (test_attach_candidate_identity_match_is_reusable), so this rejection is
        # attributable to the stored-None asymmetry and not to an unrelated guard.
        _, owner = self.claim(_decl())  # owner declares no candidate_identity
        k, t = owner["flight_key"], owner["token"]
        self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
        self.run_cmd(["finish", "--flight", k, "--token", t, "--result", "passed",
                      "--summary-file", self._write({"command": "x", "exit_status": 0, "skipped_checks": []}),
                      "--state-dir", self.state, "--logs-dir", self.logs])
        code, att = self.claim(_decl(candidate_identity="tree-DECLARED"))
        self.assertEqual(code, vf.EXIT_OK)
        self.assertEqual(att["role"], "attacher")
        self.assertEqual(att["flight_key"], k, "the handle is still shared by flight key")
        self.assertFalse(att["candidate_identity_match"])
        self.assertFalse(att["reuse_ready"],
                         "a declared identity against a stored None is not a reusable pass")
        self.assertFalse(att["satisfies_verification"])

    def test_attach_no_declared_identity_keeps_pre_550_reuse(self):
        # The complementary non-regression: an attacher that declares NO
        # candidate_identity against a handle that stored one still reuses the pass
        # (pre-#550 behaviour), so the tightened predicate did not widen to the
        # non-declaring caller.
        _, owner = self.claim(_decl(candidate_identity="tree-STORED"))
        k, t = owner["flight_key"], owner["token"]
        self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
        self.run_cmd(["finish", "--flight", k, "--token", t, "--result", "passed",
                      "--summary-file", self._write({"command": "x", "exit_status": 0, "skipped_checks": []}),
                      "--state-dir", self.state, "--logs-dir", self.logs])
        code, att = self.claim(_decl())
        self.assertEqual(code, vf.EXIT_OK)
        self.assertFalse(att["candidate_identity_match"])
        self.assertTrue(att["reuse_ready"])
        self.assertTrue(att["satisfies_verification"])

    def test_attach_candidate_identity_match_is_reusable(self):
        # The complementary arm: an attacher declaring the SAME candidate_identity as
        # the passed handle reuses it (candidate_identity_match True, reuse_ready True).
        d = _decl(candidate_identity="tree-SAME")
        _, owner = self.claim(d)
        k, t = owner["flight_key"], owner["token"]
        self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
        self.run_cmd(["finish", "--flight", k, "--token", t, "--result", "passed",
                      "--summary-file", self._write({"command": "x", "exit_status": 0, "skipped_checks": []}),
                      "--state-dir", self.state, "--logs-dir", self.logs])
        code, att = self.claim(d)
        self.assertEqual(code, vf.EXIT_OK)
        self.assertTrue(att["candidate_identity_match"])
        self.assertTrue(att["reuse_ready"])
        self.assertTrue(att["satisfies_verification"])


class TestDeclarationValidation(Harness):
    def test_non_hermetic_profile_rejected(self):
        code, out = self.claim(_decl(profile={"external_services": "network"}))
        self.assertEqual(code, vf.EXIT_INVALID)
        self.assertEqual(out["reason"], "non_hermetic_profile")

    def test_incomplete_fingerprint_disables_reuse(self):
        code, out = self.claim(_decl(checkout={"head": ""}))
        self.assertEqual(code, vf.EXIT_INVALID)
        self.assertIn("checkout_incomplete_fingerprint", out["reason"])

    def test_missing_profile_field(self):
        d = _decl()
        del d["profile"]["toolchain"]
        code, out = self.claim(d)
        self.assertEqual(code, vf.EXIT_INVALID)
        self.assertEqual(out["reason"], "profile_missing_field:toolchain")

    def test_unknown_schema_version(self):
        code, out = self.claim(_decl(schema_version=999))
        self.assertEqual(code, vf.EXIT_INVALID)
        self.assertEqual(out["reason"], "unknown_schema_version")

    def test_argv_wrong_type(self):
        code, out = self.claim(_decl(profile={"argv": "lib/test/run.sh"}))
        self.assertEqual(code, vf.EXIT_INVALID)
        self.assertEqual(out["reason"], "profile_argv_not_nonempty_list")


class TestCompareAndSwap(Harness):
    def test_mark_running_requires_owner_token(self):
        _, owner = self.claim()
        code, out = self.run_cmd(["mark-running", "--flight", owner["flight_key"],
                                  "--token", "BOGUS", "--state-dir", self.state])
        self.assertEqual(code, vf.EXIT_CAS_REJECT)
        self.assertEqual(out["reason"], "token_mismatch")

    def test_attacher_cannot_mark_running(self):
        _, owner = self.claim()
        self.claim()  # attacher has no token at all
        # An attacher with a fabricated token is rejected.
        code, _ = self.run_cmd(["mark-running", "--flight", owner["flight_key"],
                                "--token", "guessed", "--state-dir", self.state])
        self.assertEqual(code, vf.EXIT_CAS_REJECT)

    def test_replay_mark_running_rejected(self):
        _, owner = self.claim()
        k, t = owner["flight_key"], owner["token"]
        c1, _ = self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
        self.assertEqual(c1, vf.EXIT_OK)
        c2, out = self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
        self.assertEqual(c2, vf.EXIT_CAS_REJECT)
        self.assertIn("not_claimed", out["reason"])

    def test_mark_running_records_supplied_owner_evidence(self):
        # --evidence is recorded verbatim as owner_evidence (logical owner
        # evidence the caller stamps immediately before launching its command).
        _, owner = self.claim()
        k, t = owner["flight_key"], owner["token"]
        code, _ = self.run_cmd(["mark-running", "--flight", k, "--token", t,
                                "--evidence", "pid=4242 launched run.sh",
                                "--state-dir", self.state])
        self.assertEqual(code, vf.EXIT_OK)
        _, st = self.run_cmd(["status", "--flight", k, "--state-dir", self.state])
        self.assertEqual(st["state"], "running")
        self.assertEqual(st["owner_evidence"], "pid=4242 launched run.sh")

    def test_mark_running_records_default_owner_evidence(self):
        # Without --evidence a non-empty default owner-evidence string is stored,
        # never left null on a running handle.
        _, owner = self.claim()
        k, t = owner["flight_key"], owner["token"]
        self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
        _, st = self.run_cmd(["status", "--flight", k, "--state-dir", self.state])
        self.assertEqual(st["owner_evidence"], "owner running verification command")

    def test_post_terminal_transition_rejected(self):
        _, owner = self.claim()
        k, t = owner["flight_key"], owner["token"]
        self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
        summ = self._write({"command": "x", "exit_status": 0, "skipped_checks": []})
        self.run_cmd(["finish", "--flight", k, "--token", t, "--result", "passed",
                      "--summary-file", summ, "--state-dir", self.state, "--logs-dir", self.logs])
        # finishing again (or marking running post-terminal) is rejected
        c, out = self.run_cmd(["finish", "--flight", k, "--token", t, "--result", "failed",
                               "--summary-file", summ, "--state-dir", self.state])
        self.assertEqual(c, vf.EXIT_CAS_REJECT)
        self.assertIn("not_running", out["reason"])


class TestOwnerLossBoundaries(Harness):
    def test_lease_expiry_before_running_becomes_incomplete(self):
        os.environ["DEVFLOW_FLIGHT_NOW"] = "1000"
        _, owner = self.claim(lease=10)
        # Advance past the lease boundary between claim and mark-running.
        os.environ["DEVFLOW_FLIGHT_NOW"] = "2000"
        code, out = self.run_cmd(["status", "--flight", owner["flight_key"], "--state-dir", self.state])
        self.assertEqual(out["state"], "incomplete")
        self.assertEqual(code, vf.EXIT_NON_PASS)
        # And mark-running now fails closed rather than reviving the flight.
        c2, _ = self.run_cmd(["mark-running", "--flight", owner["flight_key"],
                              "--token", owner["token"], "--state-dir", self.state])
        self.assertEqual(c2, vf.EXIT_CAS_REJECT)

    def test_owner_loss_during_running_missing_evidence_incomplete(self):
        _, owner = self.claim()
        k, t = owner["flight_key"], owner["token"]
        self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
        # finish a passed result with NO terminal evidence -> incomplete, not pass.
        code, out = self.run_cmd(["finish", "--flight", k, "--token", t,
                                  "--result", "passed", "--state-dir", self.state])
        self.assertEqual(out["result"], "incomplete")
        self.assertEqual(code, vf.EXIT_CAS_REJECT)
        _, st = self.run_cmd(["status", "--flight", k, "--state-dir", self.state])
        self.assertEqual(st["state"], "incomplete")
        self.assertFalse(st["satisfies_verification"])


class TestReadShapeMatrix(Harness):
    def _corrupt(self, raw: bytes):
        _, owner = self.claim()
        path = Path(self.state) / f"{owner['flight_key']}.json"
        path.write_bytes(raw)
        return self.run_cmd(["status", "--flight", owner["flight_key"], "--state-dir", self.state])

    def test_missing_flight(self):
        code, out = self.run_cmd(["status", "--flight", "deadbeef", "--state-dir", self.state])
        self.assertEqual(code, vf.EXIT_UNREADABLE)
        self.assertFalse(out["satisfies_verification"])

    def test_empty_json(self):
        code, out = self._corrupt(b"")
        self.assertEqual(code, vf.EXIT_UNREADABLE)
        self.assertFalse(out["satisfies_verification"])

    def test_truncated_json(self):
        code, out = self._corrupt(b'{"schema_version":1,"state":"pas')
        self.assertEqual(code, vf.EXIT_UNREADABLE)

    def test_malformed_json(self):
        code, out = self._corrupt(b"{not json]")
        self.assertEqual(code, vf.EXIT_UNREADABLE)
        self.assertEqual(out["reason"], "malformed_json")

    def test_array_toplevel(self):
        # A JSON array decodes fine but is not a flight handle object.
        code, out = self._corrupt(b"[1,2,3]")
        self.assertEqual(out["reason"], "not_object")
        self.assertEqual(code, vf.EXIT_UNREADABLE)

    def test_scalar_toplevel(self):
        code, out = self._corrupt(b'42')
        self.assertEqual(code, vf.EXIT_UNREADABLE)

    def test_valid_falsy_state(self):
        # state is a valid-falsy value (false / 0 / "") — never coerced to a pass.
        for payload in (b'{"schema_version":1,"state":false,"flight_key":"k","descriptor_digest":"d","token_digest":"t"}',
                        b'{"schema_version":1,"state":0,"flight_key":"k","descriptor_digest":"d","token_digest":"t"}',
                        b'{"schema_version":1,"state":"","flight_key":"k","descriptor_digest":"d","token_digest":"t"}'):
            code, out = self._corrupt(payload)
            self.assertEqual(out["reason"], "missing_or_invalid_state")
            self.assertEqual(code, vf.EXIT_UNREADABLE)

    def test_string_true_state(self):
        code, out = self._corrupt(b'{"schema_version":1,"state":"true","flight_key":"k","descriptor_digest":"d","token_digest":"t"}')
        self.assertEqual(out["reason"], "missing_or_invalid_state")

    def test_missing_required_field(self):
        code, out = self._corrupt(b'{"schema_version":1,"state":"passed","descriptor_digest":"d","token_digest":"t"}')
        self.assertEqual(out["reason"], "missing_field:flight_key")

    def test_unknown_schema_version_in_file(self):
        code, out = self._corrupt(b'{"schema_version":7,"state":"passed","flight_key":"k","descriptor_digest":"d","token_digest":"t"}')
        self.assertEqual(out["reason"], "unknown_schema_version")


class TestStaleDrift(Harness):
    def test_checkout_drift_marks_stale(self):
        _, owner = self.claim()
        current = self._write(_ck(head=_hexid("DIFFERENT")))
        code, out = self.run_cmd(["status", "--flight", owner["flight_key"],
                                  "--current-checkout-file", current, "--state-dir", self.state])
        self.assertEqual(out["state"], "stale")
        self.assertEqual(out["invalidation_reason"], "checkout_drift")
        self.assertEqual(code, vf.EXIT_NON_PASS)

    def test_matching_checkout_no_stale(self):
        _, owner = self.claim()
        current = self._write(_ck())
        _, out = self.run_cmd(["status", "--flight", owner["flight_key"],
                               "--current-checkout-file", current, "--state-dir", self.state])
        self.assertEqual(out["state"], "claimed")


class TestSubdirAndWorktree(Harness):
    def test_same_key_attaches_from_a_different_working_directory(self):
        # A subdirectory / linked-worktree caller that computes the SAME complete
        # flight key attaches to the same flight regardless of the process cwd —
        # the helper is cwd-independent (state dir is explicit, no git is run). Run
        # the attach from a different cwd to actually exercise that independence.
        _, owner = self.claim()
        subdir = os.path.join(self.tmp, "nested", "deep")
        os.makedirs(subdir)
        prev = os.getcwd()
        try:
            os.chdir(subdir)
            _, att = self.claim()  # same absolute --state-dir, different cwd
        finally:
            os.chdir(prev)
        self.assertEqual(att["role"], "attacher")
        self.assertEqual(att["flight_key"], owner["flight_key"])

    def test_different_checkout_id_does_not_attach(self):
        _, owner = self.claim()
        code, other = self.claim(_decl(checkout={"checkout_id": "OTHER_WORKTREE"}))
        # A different checkout identity is a different key -> a fresh owner claim.
        self.assertEqual(other["role"], "owner")
        self.assertNotEqual(other["flight_key"], owner["flight_key"])


class TestFinishPropagation(Harness):
    def _finish(self, result, summary):
        _, owner = self.claim()
        k, t = owner["flight_key"], owner["token"]
        self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
        argv = ["finish", "--flight", k, "--token", t, "--result", result,
                "--state-dir", self.state, "--logs-dir", self.logs]
        if summary is not None:
            argv += ["--summary-file", self._write(summary)]
        code, out = self.run_cmd(argv)
        return k, code, out

    def test_passed_satisfies(self):
        k, code, _ = self._finish("passed", {"command": "run.sh", "exit_status": 0, "skipped_checks": []})
        self.assertEqual(code, vf.EXIT_OK)
        # #1243: a bare status no longer passes; this asserts the state/evidence
        # dimension via the explicit weaker read.
        c, st = self.run_cmd(["status", "--flight", k, "--state-dir", self.state,
                              "--allow-unverified-checkout"])
        self.assertEqual(c, vf.EXIT_OK)
        self.assertTrue(st["satisfies_verification"])

    def test_failed_does_not_satisfy(self):
        k, _, _ = self._finish("failed", {"command": "run.sh", "exit_status": 1,
                                           "failure_text": "3 failed", "skipped_checks": []})
        c, st = self.run_cmd(["status", "--flight", k, "--state-dir", self.state])
        self.assertEqual(c, vf.EXIT_NON_PASS)
        self.assertEqual(st["state"], "failed")
        self.assertFalse(st["satisfies_verification"])

    def test_skipped_checks_recorded_and_block_clean_pass(self):
        # A pass whose summary carries skipped checks preserves them; the record
        # keeps them so the caller can refuse to report a clean pass.
        skipped = [{"name": "T6b", "kind": "host-capability", "reason": "no dash"}]
        k, code, _ = self._finish("passed", {"command": "run.sh", "exit_status": 0,
                                             "skipped_checks": skipped})
        _, st = self.run_cmd(["status", "--flight", k, "--state-dir", self.state])
        self.assertEqual(st["skipped_checks"], skipped)

    def test_timed_out_writable_without_evidence_and_non_pass(self):
        # timed_out / cancelled are owner-recorded terminal outcomes that carry no
        # suite summary — writable without evidence, never a pass, and immutable.
        for result in ("timed_out", "cancelled"):
            # distinct checkout per iteration → distinct flight key (avoids attach)
            _, owner = self.claim(_decl(checkout={"head": _hexid(f"head-{result}")}))
            k, t = owner["flight_key"], owner["token"]
            self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
            code, out = self.run_cmd(["finish", "--flight", k, "--token", t, "--result", result,
                                      "--state-dir", self.state, "--logs-dir", self.logs])
            self.assertEqual(code, vf.EXIT_OK, f"{result} finish should succeed without evidence")
            self.assertEqual(out["state"], result)
            c, st = self.run_cmd(["status", "--flight", k, "--state-dir", self.state])
            self.assertEqual(c, vf.EXIT_NON_PASS)
            self.assertFalse(st["satisfies_verification"])
            # immutable: a second finish is rejected
            c2, _ = self.run_cmd(["finish", "--flight", k, "--token", t, "--result", "passed",
                                  "--summary-file", self._write({"command": "x", "exit_status": 0, "skipped_checks": []}),
                                  "--state-dir", self.state])
            self.assertEqual(c2, vf.EXIT_CAS_REJECT)

    def test_malformed_summary_file_rejected(self):
        # A truncated / undecodable evidence file is rejected before any terminal write.
        _, owner = self.claim()
        k, t = owner["flight_key"], owner["token"]
        self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
        bad = os.path.join(self.tmp, "bad-summary.json")
        Path(bad).write_bytes(b'{"command": "run.sh", "exit')  # truncated JSON
        code, out = self.run_cmd(["finish", "--flight", k, "--token", t, "--result", "passed",
                                  "--summary-file", bad, "--state-dir", self.state])
        self.assertEqual(code, vf.EXIT_INVALID)
        self.assertTrue(out["reason"].startswith("summary:"))
        # the flight is untouched — still running, never a false pass
        _, st = self.run_cmd(["status", "--flight", k, "--state-dir", self.state])
        self.assertEqual(st["state"], "running")

    def test_present_but_malformed_summary_becomes_incomplete(self):
        # The evidence gate is the one place a pass is decided: a present-but-malformed
        # summary (a scalar / array / empty object) is the same unknown class as an
        # absent one and must become `incomplete`, never a clean `passed`.
        for i, payload in enumerate((42, "x", [], {})):
            # distinct checkout per iteration → distinct flight key (avoids attach)
            _, owner = self.claim(_decl(checkout={"head": _hexid(f"head-mal-{i}")}))
            k, t = owner["flight_key"], owner["token"]
            self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
            code, out = self.run_cmd(["finish", "--flight", k, "--token", t, "--result", "passed",
                                      "--summary-file", self._write(payload), "--state-dir", self.state])
            self.assertEqual(out["result"], "incomplete", f"summary {payload!r} must not be a pass")
            self.assertEqual(code, vf.EXIT_CAS_REJECT)
            _, st = self.run_cmd(["status", "--flight", k, "--state-dir", self.state])
            self.assertEqual(st["state"], "incomplete")
            self.assertFalse(st["satisfies_verification"])

    def test_command_duration_recorded(self):
        os.environ["DEVFLOW_FLIGHT_NOW"] = "5000"
        _, owner = self.claim()
        k, t = owner["flight_key"], owner["token"]
        self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
        os.environ["DEVFLOW_FLIGHT_NOW"] = "5060"
        self.run_cmd(["finish", "--flight", k, "--token", t, "--result", "passed",
                      "--summary-file", self._write({"command": "x", "exit_status": 0, "skipped_checks": []}),
                      "--state-dir", self.state, "--logs-dir", self.logs])
        _, st = self.run_cmd(["status", "--flight", k, "--state-dir", self.state])
        self.assertEqual(st["command_duration_s"], 60.0)


class TestExitStatusBackstop(Harness):
    """The `finish --result passed` exit-status backstop (issue #1053).

    The WRITE half of a contract whose read half shipped in PR #1119: the ledger
    used to mint a terminal `passed` handle that
    `scripts/check-completion-evidence.py` would later refuse, and the run learned
    that only at the phase where the work was already finished.

    Distinct from the fixture migration in this change: every pre-existing
    `--result passed` fixture elsewhere in this file gained an `exit_status: 0`
    so it keeps exercising its own subject, whereas every assertion in this class
    is new coverage of the refusal itself.
    """

    def _running(self, head="es-default"):
        """Claim + mark-running a flight with its own key, returning (key, token)."""
        _, owner = self.claim(_decl(checkout={"head": _hexid(head)}))
        k, t = owner["flight_key"], owner["token"]
        self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
        return k, t

    def _finish_passed(self, k, t, summary):
        return self.run_cmd(["finish", "--flight", k, "--token", t, "--result", "passed",
                             "--summary-file", self._write(summary),
                             "--state-dir", self.state, "--logs-dir", self.logs])

    def test_zero_exit_status_is_accepted(self):
        # Positive control: without it every refusal below could be a gate that
        # refuses everything.
        k, t = self._running("es-ok")
        code, out = self._finish_passed(k, t, {"command": "run.sh", "exit_status": 0})
        self.assertEqual(code, vf.EXIT_OK)
        self.assertEqual(out["state"], "passed")
        # #1243: a bare status no longer passes; this asserts the state/evidence
        # dimension via the explicit weaker read.
        c, st = self.run_cmd(["status", "--flight", k, "--state-dir", self.state,
                              "--allow-unverified-checkout"])
        self.assertEqual(c, vf.EXIT_OK)
        self.assertTrue(st["satisfies_verification"])

    def test_refused_exit_status_shapes(self):
        # The full refusal matrix. `True` and `"0"` are the two traps the reader
        # names explicitly: Python's bool subclasses int, and a JSON string that
        # *looks* like a zero is not a zero.
        cases = (
            ({"command": "run.sh"}, "exit_status_unestablished"),
            ({"command": "run.sh", "exit_status": None}, "exit_status_unestablished"),
            ({"command": "run.sh", "exit_status": True}, "exit_status_unestablished"),
            ({"command": "run.sh", "exit_status": False}, "exit_status_unestablished"),
            ({"command": "run.sh", "exit_status": "0"}, "exit_status_unestablished"),
            ({"command": "run.sh", "exit_status": 0.0}, "exit_status_unestablished"),
            ({"command": "run.sh", "exit_status": []}, "exit_status_unestablished"),
            ({"command": "run.sh", "exit_status": 1}, "exit_status_nonzero"),
            ({"command": "run.sh", "exit_status": -1}, "exit_status_nonzero"),
            ({"command": "run.sh", "exit_status": 2}, "exit_status_nonzero"),
        )
        for i, (summary, reason) in enumerate(cases):
            with self.subTest(summary=summary):
                k, t = self._running(f"es-bad-{i}")
                code, out = self._finish_passed(k, t, summary)
                self.assertEqual(code, vf.EXIT_CAS_REJECT)
                self.assertEqual(out["result"], "rejected")
                self.assertEqual(out["reason"], reason)
                self.assertFalse(out["satisfies_verification"])
                # NON-terminal: no state was written, so the handle is still an
                # owned `running` flight rather than a stranded terminal one.
                self.assertEqual(out["state"], "running")
                _, st = self.run_cmd(["status", "--flight", k, "--state-dir", self.state])
                self.assertEqual(st["state"], "running")
                self.assertFalse(st["satisfies_verification"])

    def test_refusal_output_names_the_owner_token_retention(self):
        # The re-issue needs the same owner token, and the refusal's own output is
        # the only place the caller learns the handle is still owned + re-finishable.
        k, t = self._running("es-remedy")
        _, out = self._finish_passed(k, t, {"command": "run.sh", "exit_status": 7})
        self.assertEqual(out["recorded_exit_status"], 7)
        self.assertIn("owner token", out["remedy"])

    def test_refused_pass_stays_re_finishable_as_failed(self):
        # The reason the refusal must never write a terminal state: the ledger is
        # one-shot per key, so a terminal write here would strand the very failure
        # the gate exists to surface.
        k, t = self._running("es-refinish")
        code, _ = self._finish_passed(k, t, {"command": "run.sh", "exit_status": 3})
        self.assertEqual(code, vf.EXIT_CAS_REJECT)
        _, st = self.run_cmd(["status", "--flight", k, "--state-dir", self.state])
        self.assertEqual(st["state"], "running")
        code2, out2 = self.run_cmd([
            "finish", "--flight", k, "--token", t, "--result", "failed",
            "--summary-file", self._write({"command": "run.sh", "exit_status": 3,
                                           "failure_text": "3 failed"}),
            "--state-dir", self.state, "--logs-dir", self.logs])
        self.assertEqual(code2, vf.EXIT_OK)
        self.assertEqual(out2["state"], "failed")
        c3, st3 = self.run_cmd(["status", "--flight", k, "--state-dir", self.state])
        self.assertEqual(c3, vf.EXIT_NON_PASS)
        self.assertEqual(st3["state"], "failed")

    def test_non_passed_results_are_not_gated(self):
        # `failed` is the arm whose truthful evidence is a NONZERO status, and the
        # two owner-recorded outcomes carry no summary at all. Gating any of them
        # would block the honest record.
        k, t = self._running("es-failed")
        code, out = self.run_cmd([
            "finish", "--flight", k, "--token", t, "--result", "failed",
            "--summary-file", self._write({"command": "run.sh", "exit_status": 1}),
            "--state-dir", self.state, "--logs-dir", self.logs])
        self.assertEqual(code, vf.EXIT_OK)
        self.assertEqual(out["state"], "failed")
        for result in ("timed_out", "cancelled"):
            k2, t2 = self._running(f"es-{result}")
            code2, out2 = self.run_cmd([
                "finish", "--flight", k2, "--token", t2, "--result", result,
                "--state-dir", self.state, "--logs-dir", self.logs])
            self.assertEqual(code2, vf.EXIT_OK)
            self.assertEqual(out2["state"], result)

    def test_unusable_summary_arm_runs_first_and_is_unchanged(self):
        # Ordering is load-bearing: an absent / scalar / array / empty-object
        # summary keeps its ORIGINAL terminal `incomplete` disposition and is never
        # rerouted through the new non-terminal refusal.
        for i, payload in enumerate((42, "x", [], {})):
            with self.subTest(payload=payload):
                k, t = self._running(f"es-unusable-{i}")
                code, out = self._finish_passed(k, t, payload)
                self.assertEqual(code, vf.EXIT_CAS_REJECT)
                self.assertEqual(out["result"], "incomplete")
                self.assertEqual(out["reason"], "missing_terminal_evidence")
                _, st = self.run_cmd(["status", "--flight", k, "--state-dir", self.state])
                self.assertEqual(st["state"], "incomplete")
        # …and the no-summary-at-all arm too.
        k, t = self._running("es-nosummary")
        code, out = self.run_cmd(["finish", "--flight", k, "--token", t, "--result", "passed",
                                  "--state-dir", self.state, "--logs-dir", self.logs])
        self.assertEqual(out["result"], "incomplete")
        self.assertEqual(out["reason"], "missing_terminal_evidence")

    def test_legacy_passed_flight_without_exit_status_is_not_reusable(self):
        # A handle written BEFORE this change is the only population the reuse
        # predicate's new limb can exclude. Its disposition must be the one the
        # already-shipped completion gate takes — refused — so an attacher is never
        # directed to consume a pass that gate refuses.
        k, t = self._running("es-legacy")
        self.run_cmd(["finish", "--flight", k, "--token", t, "--result", "passed",
                      "--summary-file", self._write({"command": "run.sh", "exit_status": 0}),
                      "--state-dir", self.state, "--logs-dir", self.logs])
        path = Path(self.state) / f"{k}.json"
        rec = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(rec["suite_summary"].pop("exit_status") == 0)
        path.write_text(json.dumps(rec), encoding="utf-8")
        code, st = self.run_cmd(["status", "--flight", k, "--state-dir", self.state])
        self.assertEqual(code, vf.EXIT_NON_PASS)
        self.assertEqual(st["state"], "passed")
        self.assertFalse(st["satisfies_verification"])
        self.assertFalse(st["reuse_ready"])

    def test_writer_and_reader_agree_on_every_exit_status_shape(self):
        # The contract this change exists to restore is a CROSS-FILE one, so it is
        # driven against the real reader rather than a restatement of it: for every
        # shape, "the ledger records a pass" and "the completion gate accepts that
        # record" must be the same answer.
        spec = importlib.util.spec_from_file_location(
            "check_completion_evidence_parity",
            ROOT / "scripts" / "check-completion-evidence.py",
        )
        reader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reader)

        shapes = (None, True, False, "0", 0.0, [], 0, 1, -1)
        for i, status in enumerate(shapes):
            with self.subTest(exit_status=status):
                summary = {"command": "run.sh"}
                if status is not None:
                    summary["exit_status"] = status
                k, t = self._running(f"es-parity-{i}")
                code, _ = self._finish_passed(k, t, summary)
                writer_accepts = code == vf.EXIT_OK

                identity = "identity-parity"
                rec = {
                    "state": "passed",
                    "result": "passed",
                    "candidate_identity": identity,
                    "suite_summary": dict(summary),
                    "skipped_checks": [],
                }
                try:
                    token, _detail = reader._validate_implement_record(rec, identity)
                    reader_accepts = token == reader.TOK_PASS
                except reader.Verdict:
                    reader_accepts = False
                self.assertEqual(
                    writer_accepts, reader_accepts,
                    f"writer/reader disagree on exit_status={status!r}",
                )


class TestWait(Harness):
    def test_wait_returns_on_terminal_pass(self):
        _, owner = self.claim()
        k, t = owner["flight_key"], owner["token"]
        self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
        self.run_cmd(["finish", "--flight", k, "--token", t, "--result", "passed",
                      "--summary-file", self._write({"command": "x", "exit_status": 0, "skipped_checks": []}),
                      "--state-dir", self.state, "--logs-dir", self.logs])
        code, out = self.run_cmd(["wait", "--flight", k, "--timeout", "1",
                                  "--poll-interval", "0", "--state-dir", self.state, "--logs-dir", self.logs,
                                  "--allow-unverified-checkout"])
        self.assertEqual(code, vf.EXIT_OK)
        self.assertTrue(out["satisfies_verification"])

    def test_wait_matching_checkout_passes(self):
        # #1243: wait computes checkout_verified in its OWN block; drive its matching
        # arm to EXIT_OK + checkout_verified True (the status path covers the same via
        # the shared _effective_pass, but wait's verified-match branch needs its own).
        _, owner = self.claim()
        k, t = owner["flight_key"], owner["token"]
        chk = self._write(_ck())
        self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
        self.run_cmd(["finish", "--flight", k, "--token", t, "--result", "passed",
                      "--summary-file", self._write({"command": "x", "exit_status": 0, "skipped_checks": []}),
                      "--state-dir", self.state, "--logs-dir", self.logs])
        code, out = self.run_cmd(["wait", "--flight", k, "--timeout", "1",
                                  "--poll-interval", "0", "--state-dir", self.state, "--logs-dir", self.logs,
                                  "--current-checkout-file", chk])
        self.assertEqual(code, vf.EXIT_OK)
        self.assertTrue(out["checkout_verified"])
        self.assertTrue(out["satisfies_verification"])

    def test_wait_expiry_non_mutating(self):
        _, owner = self.claim()
        k = owner["flight_key"]
        # Still `claimed` (active) -> wait bound elapses -> wait_expired, unchanged.
        code, out = self.run_cmd(["wait", "--flight", k, "--timeout", "0",
                                  "--poll-interval", "0", "--state-dir", self.state, "--logs-dir", self.logs])
        self.assertEqual(code, vf.EXIT_WAIT_EXPIRED)
        self.assertEqual(out["result"], "wait_expired")
        self.assertFalse(out["satisfies_verification"])
        # The flight was NOT mutated by the wait — still claimed.
        _, st = self.run_cmd(["status", "--flight", k, "--state-dir", self.state])
        self.assertEqual(st["state"], "claimed")

    def test_wait_on_failed_is_non_pass(self):
        _, owner = self.claim()
        k, t = owner["flight_key"], owner["token"]
        self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
        self.run_cmd(["finish", "--flight", k, "--token", t, "--result", "failed",
                      "--summary-file", self._write({"command": "x", "skipped_checks": []}),
                      "--state-dir", self.state, "--logs-dir", self.logs])
        code, out = self.run_cmd(["wait", "--flight", k, "--timeout", "0",
                                  "--poll-interval", "0", "--state-dir", self.state, "--logs-dir", self.logs])
        self.assertEqual(code, vf.EXIT_NON_PASS)
        self.assertEqual(out["state"], "failed")


class TestTelemetry(Harness):
    def _events(self):
        base = Path(self.logs)
        if not base.exists():
            return []
        return [json.loads(p.read_text())["event"] for p in base.glob("*.json")]

    def test_claim_and_attach_emit_events(self):
        self.claim()
        self.claim()
        ev = self._events()
        self.assertIn("flight_claimed", ev)
        self.assertIn("flight_attached", ev)

    def test_drift_emits_flight_invalidated(self):
        _, owner = self.claim()
        current = self._write(_ck(head=_hexid("DIFFERENT")))
        self.run_cmd(["status", "--flight", owner["flight_key"],
                      "--current-checkout-file", current, "--state-dir", self.state,
                      "--logs-dir", self.logs])
        self.assertIn("flight_invalidated", self._events())

    def test_lease_expiry_emits_flight_invalidated(self):
        os.environ["DEVFLOW_FLIGHT_NOW"] = "1000"
        _, owner = self.claim(lease=5)
        os.environ["DEVFLOW_FLIGHT_NOW"] = "2000"
        self.run_cmd(["status", "--flight", owner["flight_key"],
                      "--state-dir", self.state, "--logs-dir", self.logs])
        self.assertIn("flight_invalidated", self._events())

    def test_finish_emits_terminal_event(self):
        _, owner = self.claim()
        k, t = owner["flight_key"], owner["token"]
        self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
        self.run_cmd(["finish", "--flight", k, "--token", t, "--result", "passed",
                      "--summary-file", self._write({"command": "x", "exit_status": 0, "skipped_checks": []}),
                      "--state-dir", self.state, "--logs-dir", self.logs])
        self.assertIn("flight_finished", self._events())

    def test_non_serializable_payload_never_hardens_into_a_failure(self):
        # issue #579 review + changeset: `_emit_telemetry` widened its swallow to
        # (OSError, TypeError, ValueError) precisely so a non-serializable payload
        # (a value `_canonical`/json.dumps cannot encode -> TypeError/ValueError)
        # can never propagate out and fail the enclosing coordination op. Narrowing
        # the except back to `except OSError` is the exact regression this pins:
        # drive a set() (json-unserializable) through and assert it returns False,
        # raises nothing, and writes no record.
        result = vf._emit_telemetry(self.logs, "bad_event", {"unserializable": {1, 2, 3}})
        self.assertFalse(result, "a non-serializable payload must return False, not raise")
        self.assertNotIn("bad_event", self._events())


class TestNoExecutionContract(unittest.TestCase):
    """Static guard mirrored by run.sh: the helper is data-only."""

    def test_no_subprocess_or_git_import(self):
        src = (ROOT / "scripts" / "verification-flight.py").read_text()
        for banned in BANNED_EXEC_SPELLINGS:
            self.assertNotIn(banned, src, f"helper must not use {banned}")

    @staticmethod
    def _dotted_call_target(fn):
        """Resolve a call target to its full dotted path, or None.

        Walks the WHOLE attribute chain rather than a single level. A one-level
        `isinstance(fn.value, ast.Name)` test silently skips every chained call
        (`os.path.join`, `os.environ.get`, and equally
        `asyncio.subprocess.create_subprocess_exec`), which would make a guard that
        claims to inspect every called attribute blind to exactly the multi-level
        spellings an evasion would reach for.
        """
        import ast

        parts = []
        node = fn
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
            return ".".join(reversed(parts))
        return None  # a call on a call/subscript result — not a module-qualified target

    def test_no_execution_contract_holds_by_ast_not_only_by_substring(self):
        """An independent signal from the substring sweep.

        A substring list can only ban spellings someone thought to enumerate. This
        check derives the same property structurally — every `import`, and every
        module-qualified call target resolved through its FULL dotted chain — so a
        spelling absent from BANNED_EXEC_SPELLINGS is still caught. The two guards
        are deliberately different signals; agreeing is what makes the contract
        credible.

        Scope, stated honestly: a call whose target is not module-qualified (a call
        on a call's result, a subscript, or a local alias) resolves to None here and
        is not classified — the substring sweep and the import allowlist are the
        cover for that residue, since an evasion still has to import something.
        """
        import ast

        tree = ast.parse((ROOT / "scripts" / "verification-flight.py").read_text())
        allowed_imports = {
            "__future__", "argparse", "hashlib", "hmac", "json", "os",
            "re", "secrets", "sys", "time", "pathlib", "typing",
        }
        allowed_os_calls = {
            "os.chmod", "os.close", "os.getpid", "os.open", "os.replace", "os.write",
            "os.environ.get", "os.path.join",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name.split(".")[0], allowed_imports,
                                  f"unexpected import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                self.assertIn((node.module or "").split(".")[0], allowed_imports,
                              f"unexpected from-import {node.module}")
            elif isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name):
                    self.assertNotIn(fn.id, {"eval", "exec", "compile", "__import__"},
                                     f"dynamic code execution via {fn.id}()")
                    continue
                dotted = self._dotted_call_target(fn)
                if dotted is None:
                    continue
                if dotted.split(".")[0] == "os":
                    self.assertIn(dotted, allowed_os_calls,
                                  f"unexpected os call {dotted}")
                for banned in BANNED_EXEC_SPELLINGS:
                    self.assertNotIn(banned, dotted,
                                     f"call target {dotted} matches banned spelling {banned}")

    def test_ast_guard_resolves_chained_call_targets(self):
        """Mutation-proof for the guard above: a CHAINED dangerous call must resolve.

        The one-level predicate this replaced returned nothing for a two-level
        target, so `asyncio.subprocess.create_subprocess_exec(...)` would have been
        waved through by the AST guard entirely.
        """
        import ast

        chained = ast.parse("asyncio.subprocess.create_subprocess_exec(x)").body[0].value
        self.assertEqual(
            self._dotted_call_target(chained.func),
            "asyncio.subprocess.create_subprocess_exec",
        )
        single = ast.parse("os.posix_spawn(x)").body[0].value
        self.assertEqual(self._dotted_call_target(single.func), "os.posix_spawn")
        opaque = ast.parse("f()(y).z(w)").body[0].value
        self.assertIsNone(self._dotted_call_target(opaque.func))

    def test_states_are_exactly_the_declared_set(self):
        self.assertEqual(
            set(vf.ALL_STATES),
            {"claimed", "running", "passed", "failed", "timed_out", "cancelled", "stale", "incomplete"},
        )


class TestPermissionModes(Harness):
    """The secrecy/atomicity posture: the flight file is owner-only 0o600 and the
    state directory owner-only 0o700. A regression to a world-readable mode (the
    owner token digest and full checkout fingerprint live in the file) must fail
    here rather than pass CI. Portable across macOS/BSD + Linux via os.stat mode
    bits (POSIX-only; a non-POSIX host would need a skip, but the suite is POSIX)."""

    def test_flight_file_is_owner_only_0600(self):
        _, owner = self.claim()
        path = Path(self.state) / f"{owner['flight_key']}.json"
        mode = stat.S_IMODE(os.stat(path).st_mode)
        self.assertEqual(mode, 0o600, f"flight file must be 0o600, got {oct(mode)}")
        # No group/other bits at all — a widen to world-readable trips this.
        self.assertEqual(mode & 0o077, 0, f"flight file exposes group/other bits: {oct(mode)}")

    def test_state_dir_is_owner_only_0700(self):
        self.claim()
        mode = stat.S_IMODE(os.stat(self.state).st_mode)
        self.assertEqual(mode, 0o700, f"state dir must be 0o700, got {oct(mode)}")
        self.assertEqual(mode & 0o077, 0, f"state dir exposes group/other bits: {oct(mode)}")


class TestValidationReasonBranches(Harness):
    """Every fail-closed _validate_profile / _validate_checkout reason branch,
    driven by a malformed input and keyed on its EXACT reason literal. These
    reasons are caller-keyable contract (they surface in the CLI JSON `reason`
    field), so each is a tested shape — the adversarial input-shape matrix, not
    the happy path."""

    def _reason(self, decl_obj):
        code, out = self.run_cmd(["claim", "--input-file", self._write(decl_obj),
                                  "--state-dir", self.state, "--logs-dir", self.logs])
        self.assertEqual(code, vf.EXIT_INVALID, f"expected EXIT_INVALID for {decl_obj!r}")
        return out["reason"]

    def test_declaration_not_object(self):
        self.assertEqual(self._reason([1, 2, 3]), "declaration_not_object")

    def test_profile_not_object(self):
        d = _decl()
        d["profile"] = "not-a-dict"
        self.assertEqual(self._reason(d), "profile_not_object")

    def test_profile_argv_not_all_strings(self):
        self.assertEqual(self._reason(_decl(profile={"argv": ["run.sh", 5]})),
                         "profile_argv_not_all_strings")

    def test_profile_cwd_not_nonempty_string(self):
        self.assertEqual(self._reason(_decl(profile={"cwd": ""})),
                         "profile_cwd_not_nonempty_string")
        self.assertEqual(self._reason(_decl(profile={"cwd": 5})),
                         "profile_cwd_not_nonempty_string")

    def test_profile_environment_not_object(self):
        self.assertEqual(self._reason(_decl(profile={"environment": "x"})),
                         "profile_environment_not_object")

    def test_profile_toolchain_not_object(self):
        self.assertEqual(self._reason(_decl(profile={"toolchain": []})),
                         "profile_toolchain_not_object")

    def test_profile_dependencies_not_object(self):
        self.assertEqual(self._reason(_decl(profile={"dependencies": "x"})),
                         "profile_dependencies_not_object")

    def test_profile_output_roots_not_list(self):
        self.assertEqual(self._reason(_decl(profile={"output_roots": "x"})),
                         "profile_output_roots_not_list")

    def test_checkout_not_object(self):
        d = _decl()
        d["checkout"] = "not-a-dict"
        self.assertEqual(self._reason(d), "checkout_not_object")

    def test_checkout_missing_field(self):
        d = _decl()
        del d["checkout"]["head"]
        self.assertEqual(self._reason(d), "checkout_missing_field:head")


class TestReasonVocabulary(unittest.TestCase):
    """Construction-time validation of the closed .reason machine-code vocabulary.
    A typo at a raise site builds a valid-but-wrong error that would only fail a
    distant assertion; construction rejects an unknown code at the raise site."""

    def test_declaration_error_known_codes_accepted(self):
        # Bare literals and prefix:detail codes from real raise sites construct.
        vf.DeclarationError("non_hermetic_profile")
        vf.DeclarationError("profile_missing_field:toolchain")
        vf.DeclarationError("checkout_incomplete_fingerprint:head")

    def test_read_error_known_codes_accepted(self):
        vf.ReadError("malformed_json")
        vf.ReadError("missing_field:flight_key")
        vf.ReadError("unreadable:OSError")

    def test_declaration_error_unknown_bare_code_rejected(self):
        with self.assertRaises(ValueError):
            vf.DeclarationError("profile_not_an_object")  # typo of profile_not_object

    def test_declaration_error_unknown_prefix_rejected(self):
        with self.assertRaises(ValueError):
            vf.DeclarationError("profile_missing_feild:toolchain")  # typo'd prefix

    def test_read_error_unknown_bare_code_rejected(self):
        with self.assertRaises(ValueError):
            vf.ReadError("malfrmed_json")

    def test_read_error_unknown_prefix_rejected(self):
        with self.assertRaises(ValueError):
            vf.ReadError("unreadble:OSError")  # typo'd prefix


class TestReasonCodeImmutability(Harness):
    """`.reason` is the machine-readable operand distant assertions key on, so the
    closed-vocabulary invariant must hold for the object's LIFETIME, not only at
    construction — otherwise a later `exc.reason = "typo"` reintroduces exactly the
    valid-but-wrong error the construction-time check exists to prevent."""

    def test_declaration_error_reason_is_read_only(self):
        exc = vf.DeclarationError("profile_not_object")
        with self.assertRaises(AttributeError):
            exc.reason = "profile_not_an_object"
        self.assertEqual(exc.reason, "profile_not_object")

    def test_read_error_reason_is_read_only(self):
        exc = vf.ReadError("malformed_json")
        with self.assertRaises(AttributeError):
            exc.reason = "malfrmed_json"
        self.assertEqual(exc.reason, "malformed_json")

    def test_reason_backing_field_is_also_immutable(self):
        """The docstring's guarantee is LIFETIME immutability, so blocking only the
        `exc.reason = ...` spelling is not enough — the backing field must be sealed
        too, or the invariant is defeated by `exc._reason = "typo"`."""
        for exc in (vf.DeclarationError("profile_not_object"), vf.ReadError("empty")):
            with self.assertRaises(AttributeError):
                exc._reason = "typo"
            with self.assertRaises(AttributeError):
                exc.some_new_attribute = "x"
        self.assertEqual(vf.DeclarationError("profile_not_object").reason,
                         "profile_not_object")

    def test_both_coded_errors_share_one_validating_base(self):
        """A third coded-reason exception must inherit the wiring structurally,
        not by copy-paste convention."""
        self.assertTrue(issubclass(vf.DeclarationError, vf._CodedError))
        self.assertTrue(issubclass(vf.ReadError, vf._CodedError))


class TestStateDirChmodBreadcrumb(Harness):
    """A silently-swallowed chmod failure makes the module's own 0700 directory-mode
    claim false on that host with nothing recording it. It stays best-effort (never
    fatal) but must leave an auditable breadcrumb."""

    def test_chmod_failure_emits_telemetry_breadcrumb(self):
        real_chmod = os.chmod

        def boom(path, mode, *a, **kw):
            if str(path).endswith("state"):
                raise PermissionError("EPERM")
            return real_chmod(path, mode, *a, **kw)

        os.chmod = boom
        try:
            vf._state_dir(self.state, logs_dir=self.logs)
        finally:
            os.chmod = real_chmod
        events = [json.loads(p.read_text(encoding="utf-8"))
                  for p in Path(self.logs).glob("*.json")]
        kinds = [e["event"] for e in events]
        self.assertIn("state_dir_chmod_failed", kinds)


class TestWaitDriftAndInvalidCheckoutFile(Harness):
    """`wait` is the one command whose whole purpose is polling ACROSS a window in
    which another process can mutate the checkout — its own drift path must be
    exercised, not just `status`'."""

    def test_wait_detects_checkout_drift_mid_poll(self):
        _, owner = self.claim()
        drifted = self._write(_ck(head=_hexid("MOVED")))
        code, out = self.run_cmd([
            "wait", "--flight", owner["flight_key"], "--state-dir", self.state,
            "--logs-dir", self.logs, "--timeout", "0",
            "--current-checkout-file", drifted,
        ])
        self.assertEqual(out["state"], "stale")
        self.assertFalse(out["satisfies_verification"])
        self.assertNotEqual(code, vf.EXIT_OK)

    def test_wait_malformed_current_checkout_file_is_invalid(self):
        _, owner = self.claim()
        bad = os.path.join(self.tmp, "bad.json")
        Path(bad).write_text("{not json", encoding="utf-8")
        code, _ = self.run_cmd([
            "wait", "--flight", owner["flight_key"], "--state-dir", self.state,
            "--timeout", "0", "--current-checkout-file", bad,
        ])
        self.assertEqual(code, vf.EXIT_INVALID)

    def test_status_malformed_current_checkout_file_is_invalid(self):
        _, owner = self.claim()
        bad = os.path.join(self.tmp, "bad2.json")
        Path(bad).write_text("[]", encoding="utf-8")
        code, _ = self.run_cmd([
            "status", "--flight", owner["flight_key"], "--state-dir", self.state,
            "--current-checkout-file", bad,
        ])
        self.assertEqual(code, vf.EXIT_INVALID)


class TestOwnerCommandsAgainstAbsentFlight(Harness):
    """`mark-running`/`finish` drive `_cas_load`'s ReadError arm through a DIFFERENT
    output shape than `status` — a regression that collapsed 'no such flight' into
    'wrong token' would be invisible to the status-only shape matrix."""

    def test_mark_running_on_absent_flight_is_unreadable(self):
        code, out = self.run_cmd([
            "mark-running", "--flight", "0" * 64, "--token", "deadbeef",
            "--state-dir", self.state,
        ])
        self.assertEqual(code, vf.EXIT_UNREADABLE)
        self.assertEqual(out["reason"], "missing")

    def test_finish_on_absent_flight_is_unreadable(self):
        summary = self._write({"command": "lib/test/run.sh", "exit_status": 0})
        code, out = self.run_cmd([
            "finish", "--flight", "0" * 64, "--token", "deadbeef",
            "--result", "passed", "--summary-file", summary,
            "--state-dir", self.state,
        ])
        self.assertEqual(code, vf.EXIT_UNREADABLE)
        self.assertEqual(out["reason"], "missing")


class TestTerminalHandleIsOneShotPerKey(Harness):
    """Documented deliberate behavior: a terminal handle is never re-owned. A later
    caller attaches to it and falls back to a direct launch — it never mints a second
    owner over a terminal record, and never reads one as a pass."""

    def test_claim_over_terminal_incomplete_attaches_and_never_passes(self):
        os.environ["DEVFLOW_FLIGHT_NOW"] = "1000"
        _, owner = self.claim(lease=10)
        os.environ["DEVFLOW_FLIGHT_NOW"] = "2000"
        code, out = self.run_cmd([
            "status", "--flight", owner["flight_key"], "--state-dir", self.state,
            "--logs-dir", self.logs,
        ])
        self.assertEqual(out["state"], "incomplete")
        os.environ.pop("DEVFLOW_FLIGHT_NOW", None)
        code2, again = self.run_cmd([
            "claim", "--input-file", self._write(_decl()),
            "--state-dir", self.state, "--logs-dir", self.logs,
        ])
        self.assertEqual(again["role"], "attacher")
        self.assertEqual(again["state"], "incomplete")
        self.assertNotIn("token", again)
        self.assertFalse(again["satisfies_verification"])


class TestUsageErrorsAreAttributable(Harness):
    """A usage error must NOT collide with EXIT_NON_PASS.

    argparse's default usage-error status is 2, which this CLI documents as
    EXIT_NON_PASS ("read succeeded but the flight does NOT satisfy verification").
    A shell caller branching on 2 would read a typo'd flag as a real non-passing
    read, and would find no `reason` field to explain it.
    """

    def test_unknown_subcommand_is_invalid_not_non_pass(self):
        code, out = self.run_cmd_expecting_exit(["bogus-subcommand"])
        self.assertEqual(code, vf.EXIT_INVALID)
        self.assertNotEqual(code, vf.EXIT_NON_PASS)
        self.assertTrue(out["reason"].startswith("usage_error:"))
        self.assertIs(out["satisfies_verification"], False)

    def test_missing_flag_value_is_invalid_not_non_pass(self):
        code, out = self.run_cmd_expecting_exit(["status", "--flight"])
        self.assertEqual(code, vf.EXIT_INVALID)
        self.assertTrue(out["reason"].startswith("usage_error:"))

    def test_every_invalid_path_emits_the_same_key_set(self):
        """The _FlightArgumentParser docstring claims exactly this."""
        keys = set()
        code, out = self.run_cmd_expecting_exit(["bogus"])
        keys.add(frozenset(out))
        _, out2 = self.run_cmd(["descriptor", "--input-file",
                                os.path.join(self.tmp, "does-not-exist.json")])
        keys.add(frozenset(out2))
        _, out3 = self.run_cmd(["descriptor", "--input-file",
                                self._write({"schema_version": 1, "profile": {},
                                             "checkout": {}})])
        keys.add(frozenset(out3))
        self.assertEqual(len(keys), 1, f"invalid paths emit differing key sets: {keys}")
        self.assertEqual(
            next(iter(keys)),
            frozenset({"ok", "result", "reason", "satisfies_verification"}),
        )


class TestLedgerWriteFailure(Harness):
    """issue #579 review (S4): an owner-write OSError on the coordination path is an
    attributable `write_failed:<class>` JSON + non-zero exit, never an uncaught
    traceback. Fail-safe throughout: a non-zero exit means no attacher reuses the
    handle, so a write failure degrades to duplicate work, never a false pass."""

    def test_claim_write_failure_is_attributable_not_a_traceback(self):
        # Win the O_EXCL create, then fail os.write: the reviewer's exact case —
        # a zero-byte handle with the owner token never printed. Must emit JSON.
        orig_write = vf.os.write

        def boom(fd, data):
            raise OSError(28, "No space left on device")

        vf.os.write = boom
        try:
            code, out = self.claim()
        finally:
            vf.os.write = orig_write
        self.assertEqual(out["result"], "write_failed")
        self.assertTrue(out["reason"].startswith("write_failed:"))
        self.assertFalse(out["satisfies_verification"])
        self.assertNotEqual(code, vf.EXIT_OK)
        self.assertNotIn("token", out, "a failed create must never print an owner token")

    def test_finish_write_failure_is_attributable(self):
        _, owner = self.claim()
        k, t = owner["flight_key"], owner["token"]
        self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
        orig = vf._atomic_replace

        def boom(path, body):
            raise OSError(28, "No space left on device")

        vf._atomic_replace = boom
        try:
            code, out = self.run_cmd([
                "finish", "--flight", k, "--token", t, "--result", "passed",
                "--summary-file", self._write({"command": "x", "exit_status": 0, "skipped_checks": []}),
                "--state-dir", self.state, "--logs-dir", self.logs,
            ])
        finally:
            vf._atomic_replace = orig
        self.assertEqual(out["result"], "write_failed")
        self.assertFalse(out["satisfies_verification"])
        self.assertNotEqual(code, vf.EXIT_OK)


class TestCheckoutShapeGate(Harness):
    """issue #1243: _validate_checkout requires the four content fields to be git
    object ids (40/64-hex), so the junk strings pre-producer callers invented are
    rejected instead of silently keying a flight over a fingerprint of nothing."""

    def test_rejects_placeholder_checkout_values(self):
        # The exact degenerate values the issue names, plus the {k: "v"} shape the
        # old test_reception_identity fixture built.
        for junk in ("v", "clean", "clean-no-untracked"):
            code, out = self.claim(_decl(checkout={k: junk for k in vf._CHECKOUT_REQUIRED}))
            self.assertEqual(code, vf.EXIT_INVALID, f"{junk!r} must be refused")
            self.assertTrue(out["reason"].startswith("checkout_field_bad_shape:"),
                            f"{junk!r} -> {out['reason']}")

    def test_producer_shape_is_accepted(self):
        # AC1<->AC2: the object-id shape the producer emits passes validation.
        code, out = self.run_cmd(["descriptor", "--input-file",
                                  self._write(_decl(checkout=_ck()))])
        self.assertEqual(code, vf.EXIT_OK)
        self.assertIn("flight_key", out)

    def test_checkout_id_stays_loose(self):
        # checkout_id is the producer's opaque --absolute-git-dir path, not an object
        # id, so an arbitrary non-empty string is still accepted for it.
        code, out = self.run_cmd(["descriptor", "--input-file",
                                  self._write(_decl(checkout=_ck(checkout_id="/some/worktree/.git")))])
        self.assertEqual(code, vf.EXIT_OK)


class TestStaleFlightRegression(Harness):
    """issue #1243 regression, driven by the REAL producer over a real git tree: a
    passed flight over a tree that then moves must re-read as a non-pass."""

    def _fingerprint(self, repo) -> dict:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "checkout-fingerprint.py")],
            cwd=repo, capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def _git(self, repo, *args) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True,
                       capture_output=True, text=True)

    def test_passed_flight_over_moved_tree_is_non_pass(self):
        repo = os.path.join(self.tmp, "repo")
        os.makedirs(repo)
        self._git(repo, "init", "-q")
        self._git(repo, "config", "user.email", "t@example.invalid")
        self._git(repo, "config", "user.name", "t")
        Path(repo, "f.txt").write_text("one\n", encoding="utf-8")
        self._git(repo, "add", "f.txt")
        self._git(repo, "commit", "-qm", "init")

        before = self._fingerprint(repo)
        # The producer's fingerprint is itself declaration-valid (AC1<->AC2).
        decl = {
            "schema_version": vf.SCHEMA_VERSION,
            "profile": _decl()["profile"],
            "checkout": before,
            "candidate_identity": "deadbeef" * 5,
        }
        code, owner = self.claim(decl)
        self.assertEqual(owner["role"], "owner", (code, owner))
        k, t = owner["flight_key"], owner["token"]
        self.run_cmd(["mark-running", "--flight", k, "--token", t, "--state-dir", self.state])
        self.run_cmd(["finish", "--flight", k, "--token", t, "--result", "passed",
                      "--summary-file", self._write({"command": "run.sh", "exit_status": 0, "skipped_checks": []}),
                      "--state-dir", self.state, "--logs-dir", self.logs])

        # Same tree -> a verified, reusable pass.
        code_ok, st_ok = self.run_cmd(["status", "--flight", k, "--state-dir", self.state,
                                       "--current-checkout-file", self._write(before)])
        self.assertEqual(code_ok, vf.EXIT_OK)
        self.assertTrue(st_ok["satisfies_verification"])

        # Mutate a tracked file, re-fingerprint: the checkout differs.
        Path(repo, "f.txt").write_text("two\n", encoding="utf-8")
        after = self._fingerprint(repo)
        self.assertNotEqual(before, after, "editing a tracked file must change the fingerprint")

        # The passed flight, re-read against the MOVED tree, is a non-pass. The
        # handle itself is a terminal `passed` record and stays immutable — the
        # non-pass comes from the checkout AND (issue #1243): the current tree does
        # not match the recorded one, so `checkout_verified` is False and the read
        # reports non-pass / exits non-zero rather than reusing a pass over a moved
        # tree. This is the exact fail-open the issue is about.
        code_bad, st_bad = self.run_cmd(["status", "--flight", k, "--state-dir", self.state,
                                         "--current-checkout-file", self._write(after)])
        self.assertEqual(code_bad, vf.EXIT_NON_PASS)
        self.assertFalse(st_bad["satisfies_verification"])
        self.assertFalse(st_bad["reuse_ready"])
        self.assertFalse(st_bad["checkout_verified"])
        self.assertEqual(st_bad["state"], "passed")


class TestCheckoutFingerprintProducer(Harness):
    """Direct coverage of scripts/checkout-fingerprint.py's own contract (issue #1243):
    its fail-closed behavior, the untracked field, and an unborn HEAD."""

    def _run_producer(self, cwd):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "checkout-fingerprint.py")],
            cwd=cwd, capture_output=True, text=True,
        )

    def _git(self, repo, *args) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True,
                       capture_output=True, text=True)

    def _repo(self):
        repo = os.path.join(self.tmp, f"repo-{os.urandom(4).hex()}")
        os.makedirs(repo)
        self._git(repo, "init", "-q")
        self._git(repo, "config", "user.email", "t@example.invalid")
        self._git(repo, "config", "user.name", "t")
        return repo

    def test_fails_closed_outside_git_repo(self):
        # The producer's headline promise: any git failure prints NO object and exits
        # non-zero. A non-git directory makes _toplevel() raise.
        nongit = os.path.join(self.tmp, "not-a-repo")
        os.makedirs(nongit)
        proc = self._run_producer(nongit)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "", "must emit no fingerprint on failure")
        self.assertIn("checkout-fingerprint", proc.stderr)

    def test_untracked_change_moves_fingerprint_and_ignored_excluded(self):
        repo = self._repo()
        Path(repo, "tracked.txt").write_text("x\n", encoding="utf-8")
        self._git(repo, "add", "tracked.txt")
        self._git(repo, "commit", "-qm", "init")
        before = json.loads(self._run_producer(repo).stdout)

        # An untracked, non-ignored file moves the fingerprint (its untracked_digest).
        Path(repo, "new-untracked.txt").write_text("hello\n", encoding="utf-8")
        after = json.loads(self._run_producer(repo).stdout)
        self.assertNotEqual(before["untracked_digest"], after["untracked_digest"])
        self.assertNotEqual(before, after)

        # A gitignored file does NOT move the fingerprint.
        Path(repo, ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        self._git(repo, "add", ".gitignore")
        self._git(repo, "commit", "-qm", "ignore")
        baseline = json.loads(self._run_producer(repo).stdout)
        Path(repo, "ignored.txt").write_text("secret\n", encoding="utf-8")
        with_ignored = json.loads(self._run_producer(repo).stdout)
        self.assertEqual(baseline["untracked_digest"], with_ignored["untracked_digest"],
                         "a gitignored file must not change the fingerprint")

    def test_unborn_head_emits_zero_sha(self):
        # A fresh repo with no commit: head is the all-zero sentinel, and the
        # fingerprint is still declaration-valid (40 zeros are object-id-shaped).
        repo = self._repo()
        proc = self._run_producer(repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        fp = json.loads(proc.stdout)
        self.assertEqual(fp["head"], "0" * 40)
        # It passes the consumer's shape gate.
        self.assertEqual(vf._validate_checkout(dict(fp)), fp)


class TestProducerBackdateFailClosed(Harness):
    """The #1117 racy-stat hardening's fail-closed arm: when the filesystem does not
    store the backdate, _tracked_digest raises rather than fingerprinting from
    unprotected stat data."""

    def test_ineffective_backdate_raises(self):
        repo = os.path.join(self.tmp, "bd-repo")
        os.makedirs(repo)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "t@e"], cwd=repo, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True, capture_output=True, text=True)
        Path(repo, "a.txt").write_text("one\n", encoding="utf-8")
        subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-qm", "c"], cwd=repo, check=True, capture_output=True, text=True)
        # os.utime made a no-op: the scratch index keeps its real (current) mtime, so
        # the stored second is NOT the requested backdate and the verify must fail closed.
        with mock.patch.object(cf.os, "utime", lambda *a, **k: None), \
                self.assertRaises(cf._GitError) as ctx:
            cf._tracked_digest(repo)
        self.assertIn("backdate ineffective", str(ctx.exception))


class TestPhaseEventAppend(Harness):
    """Issue #1853: the `event` subcommand appends clock-authored phase-boundary
    events to an append-only JSONL log, always exits 0, and breadcrumbs a failed
    write instead of blocking the run."""

    def _events_file(self, log_dir):
        return Path(log_dir) / vf.PHASE_EVENTS_FILENAME

    def test_appends_clock_authored_record(self):
        log_dir = os.path.join(self.tmp, "phase-events")
        os.environ["DEVFLOW_FLIGHT_NOW"] = "1000000000"
        code, _ = self.run_cmd(["event", "simplify-start", "--log-dir", log_dir])
        self.assertEqual(code, vf.EXIT_OK)
        lines = self._events_file(log_dir).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual(rec["event"], "simplify-start")
        # recorded_at is the helper's own clock (via _now/_iso), never model-volunteered.
        self.assertEqual(rec["recorded_at"], vf._iso(1000000000))
        self.assertEqual(set(rec), {"event", "recorded_at"})

    def test_append_only_accumulates(self):
        log_dir = os.path.join(self.tmp, "phase-events")
        for name in ("simplify-start", "simplify-end", "reviewer-dispatch"):
            code, _ = self.run_cmd(["event", name, "--log-dir", log_dir])
            self.assertEqual(code, vf.EXIT_OK)
        lines = self._events_file(log_dir).read_text(encoding="utf-8").splitlines()
        self.assertEqual(
            [json.loads(line)["event"] for line in lines],
            ["simplify-start", "simplify-end", "reviewer-dispatch"],
        )

    def test_default_location_under_prflow_logs(self):
        # No --log-dir: the record must actually land under <cwd>/.prflow/logs/ per
        # the AC — exercise the Path.cwd()/PHASE_EVENTS_DIRNAME default, not just the
        # constant. chdir into the scratch tmp so the write never pollutes the repo.
        self.assertIn(os.path.join(".prflow", "logs"), vf.PHASE_EVENTS_DIRNAME)
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            code, _ = self.run_cmd(["event", "phase2-checkpoint"])
        finally:
            os.chdir(cwd)
        self.assertEqual(code, vf.EXIT_OK)
        landed = Path(self.tmp) / vf.PHASE_EVENTS_DIRNAME / vf.PHASE_EVENTS_FILENAME
        self.assertTrue(landed.is_file())
        self.assertEqual(json.loads(landed.read_text(encoding="utf-8"))["event"], "phase2-checkpoint")

    def test_optional_payload_merged_reserved_keys_protected(self):
        log_dir = os.path.join(self.tmp, "phase-events")
        os.environ["DEVFLOW_FLIGHT_NOW"] = "1000000000"
        code, _ = self.run_cmd([
            "event", "reviewer-dispatch", "--log-dir", log_dir,
            "--payload", json.dumps(
                {"agent": "code-reviewer", "event": "SPOOF", "recorded_at": "SPOOF"}
            ),
        ])
        self.assertEqual(code, vf.EXIT_OK)
        rec = json.loads(
            self._events_file(log_dir).read_text(encoding="utf-8").splitlines()[0]
        )
        self.assertEqual(rec["agent"], "code-reviewer")
        # event/recorded_at are clock-authored and never shadowed by a payload key.
        self.assertEqual(rec["event"], "reviewer-dispatch")
        self.assertEqual(rec["recorded_at"], vf._iso(1000000000))

    def test_failed_write_breadcrumbs_and_exits_zero(self):
        # A log-dir that cannot be created (a path under a regular file) drives the
        # failed-write arm: exit 0, a specific stderr breadcrumb, run continues.
        blocker = os.path.join(self.tmp, "not-a-dir")
        Path(blocker).write_text("x", encoding="utf-8")
        log_dir = os.path.join(blocker, "phase-events")
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = vf.main(["event", "simplify-start", "--log-dir", log_dir])
        self.assertEqual(code, vf.EXIT_OK)
        self.assertIn("phase event", buf_err.getvalue())
        self.assertIn("simplify-start", buf_err.getvalue())

    def test_unparseable_payload_breadcrumbs_but_still_records(self):
        log_dir = os.path.join(self.tmp, "phase-events")
        buf_err = io.StringIO()
        with redirect_stderr(buf_err):
            code, _ = self.run_cmd(
                ["event", "shadow-entry", "--log-dir", log_dir, "--payload", "{not json"]
            )
        self.assertEqual(code, vf.EXIT_OK)
        rec = json.loads(
            self._events_file(log_dir).read_text(encoding="utf-8").splitlines()[0]
        )
        self.assertEqual(rec["event"], "shadow-entry")
        self.assertIn("unparseable", buf_err.getvalue())
        # exactly one breadcrumb: the parse-error arm must not also fall through to
        # the non-object arm, which is what a shared None sentinel would have caused.
        self.assertNotIn("non-object", buf_err.getvalue())

    def test_non_object_payload_shapes_all_breadcrumb(self):
        # The payload parser is a best-effort parser over caller-supplied JSON, so the
        # non-object shapes are swept together rather than only the array row: a JSON
        # `null` parses to None and must not be mistaken for the parse-error sentinel.
        for label, raw in (
            ("null", "null"),
            ("number scalar", "42"),
            ("string scalar", '"str"'),
            ("array", "[1, 2]"),
        ):
            with self.subTest(payload=label):
                log_dir = os.path.join(self.tmp, "phase-events-" + label.replace(" ", "-"))
                buf_err = io.StringIO()
                with redirect_stderr(buf_err):
                    code, _ = self.run_cmd(
                        ["event", "shadow-entry", "--log-dir", log_dir, "--payload", raw]
                    )
                self.assertEqual(code, vf.EXIT_OK)
                rec = json.loads(
                    self._events_file(log_dir).read_text(encoding="utf-8").splitlines()[0]
                )
                # the base event is still recorded, with no payload key merged in
                self.assertEqual(rec["event"], "shadow-entry")
                self.assertEqual(set(rec), {"event", "recorded_at"})
                self.assertIn("non-object", buf_err.getvalue())
                self.assertNotIn("unparseable", buf_err.getvalue())

    def test_empty_payload_is_absent_and_empty_object_merges_nothing(self):
        for label, raw in (("empty string", ""), ("empty object", "{}")):
            with self.subTest(payload=label):
                log_dir = os.path.join(self.tmp, "phase-events-" + label.replace(" ", "-"))
                buf_err = io.StringIO()
                with redirect_stderr(buf_err):
                    code, _ = self.run_cmd(
                        ["event", "phase2-checkpoint", "--log-dir", log_dir, "--payload", raw]
                    )
                self.assertEqual(code, vf.EXIT_OK)
                rec = json.loads(
                    self._events_file(log_dir).read_text(encoding="utf-8").splitlines()[0]
                )
                self.assertEqual(set(rec), {"event", "recorded_at"})
                # neither shape is malformed or non-object, so neither breadcrumbs
                self.assertEqual(buf_err.getvalue(), "")

    def test_valid_falsy_payload_values_survive_the_merge(self):
        # The repo's off-switch bug class: a real 0 / false / "" merged from a payload
        # must reach the record, never be dropped by a truthiness test on the value.
        log_dir = os.path.join(self.tmp, "phase-events")
        code, _ = self.run_cmd([
            "event", "phase3-simplify-end", "--log-dir", log_dir,
            "--payload", json.dumps({"count": 0, "reused": False, "note": ""}),
        ])
        self.assertEqual(code, vf.EXIT_OK)
        rec = json.loads(
            self._events_file(log_dir).read_text(encoding="utf-8").splitlines()[0]
        )
        self.assertEqual(rec["count"], 0)
        self.assertIs(rec["reused"], False)
        self.assertEqual(rec["note"], "")


if __name__ == "__main__":
    unittest.main()
