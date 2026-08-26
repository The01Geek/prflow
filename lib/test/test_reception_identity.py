#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Focused tests for the receiving-review session artifact producer (issue #668).

Drives the real scripts/reception_identity.py library and scripts/reception-record.py
CLI against real scratch git fixture repositories (git is not mocked), plus the
scripts/verification-flight.py optional-field extension through its module API.

Covers the issue #668 acceptance matrix:
  * the identity contract rows (edit+untracked, one-byte change, gitignored append,
    deletion, rename, `git commit -am` falsifier),
  * shallow-clone and cone-mode sparse-checkout invariance,
  * the exercised derivation failure modes -> named breadcrumb, no printed
    identity (the arms left untested are enumerated in the deferred-coverage
    record near the end of this file, with the fail-direction reasoning),
  * one-invocation-writes-both-artifacts, token nonce, gitignored keying,
  * the ignore-rule precondition, the session pointer, idempotency,
  * the findings ledger + disposition subcommand + the four-channel guard,
  * the six-shape adversarial matrix over the findings artifact BOTH read-back
    paths consume — the append-disposition path and the record path's
    existing_findings_* re-read,
  * degenerate inputs (no commits, empty tree, mode change, symlink, newline
    filename, absent index), the no-history / index-unmodified scale properties,
  * the flight_key-unchanged property for a candidate_identity sibling field.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1].parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import reception_identity as ri


def _load_hyphenated(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rr = _load_hyphenated("reception_record", "reception-record.py")
vf = _load_hyphenated("verification_flight", "verification-flight.py")


def _valid_checkout() -> dict:
    """A shape-valid checkout fingerprint (issue #1243): the four content fields are
    git object ids, the shape checkout-fingerprint.py emits and _validate_checkout now
    requires. The old {k: "v"} placeholder is rejected by that shape gate."""
    return {
        "checkout_id": "r1",
        "head": "a" * 40,
        "index_digest": "b" * 40,
        "tracked_digest": "c" * 40,
        "untracked_digest": "d" * 40,
    }


def git(cwd, *args, check=True, env=None):
    e = os.environ.copy()
    e.setdefault("GIT_AUTHOR_NAME", "t")
    e.setdefault("GIT_AUTHOR_EMAIL", "t@t")
    e.setdefault("GIT_COMMITTER_NAME", "t")
    e.setdefault("GIT_COMMITTER_EMAIL", "t@t")
    if env:
        e.update(env)
    p = subprocess.run(["git", *args], cwd=cwd, env=e,
                       capture_output=True, text=True)
    if check and p.returncode != 0:
        raise AssertionError(f"git {args} failed: {p.stderr}")
    return p


def committed_tree(cwd) -> str:
    return git(cwd, "rev-parse", "HEAD^{tree}").stdout.strip()


class ScratchRepo:
    def __init__(self, path: Path):
        self.path = path
        path.mkdir(parents=True, exist_ok=True)
        git(path, "init", "-q")
        # A gitignore so the session dir is ignored (mirrors the scaffolder).
        (path / ".gitignore").write_text("/.prflow/*\n")
        git(path, "add", ".gitignore")
        git(path, "commit", "-qm", "seed")

    def write(self, rel, content):
        p = self.path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    def commit_all(self, msg="c"):
        git(self.path, "add", "-A")
        git(self.path, "commit", "-qm", msg)


class IdentityContractTests(unittest.TestCase):
    def _repo(self):
        d = Path(tempfile.mkdtemp())
        return ScratchRepo(d)

    def test_edit_plus_untracked_committed_equal(self):
        r = self._repo()
        r.write("a.txt", "one\n")
        r.commit_all("a")
        r.write("a.txt", "two\n")      # tracked edit
        r.write("b.txt", "new\n")      # new untracked
        derived = ri.derive_candidate_identity(str(r.path))
        r.commit_all("stage")
        self.assertEqual(derived, committed_tree(r.path))

    def test_same_size_same_tick_edit_reflected(self):
        """A same-size edit within the seeding commit's mtime tick is still reflected.

        Issue #1117: derive_candidate_identity seeds its temp index from the repo's
        index, whose entries carry pre-edit stat data. When a tracked file is rewritten
        to the SAME size within the SAME whole-second mtime tick the index cached,
        `git add -A` reads the entry as clean and never re-hashes it, so the derived
        tree carries the STALE blob — two distinct working trees collide on one identity.

        The race is constructed deterministically (never by timing): `core.checkStat=minimal`
        makes git compare only whole-second mtime + size, and the file's mtime is pinned to a
        fixed time in the PAST — cached at `git add` time and restored after the edit — so the
        cached stat reads clean. The past mtime is load-bearing: it puts the entry's cached
        mtime well before the derivation's freshly-created temp index, so racy-git (which
        re-hashes a file whose cached mtime is not older than the index) does not intervene and
        mask the bug. Fails against the pre-fix implementation, whose derived tree carries the
        pre-edit blob.
        """
        past = 1609459200  # 2021-01-01 UTC — safely before the temp index git will create
        r = self._repo()
        git(r.path, "config", "core.checkStat", "minimal")
        r.write("a.txt", "one\n")
        os.utime(r.path / "a.txt", (past, past))   # cache the past mtime at `git add`
        r.commit_all("a")
        r.write("a.txt", "two\n")   # same 4-byte size, different content
        os.utime(r.path / "a.txt", (past, past))   # restore it after the edit
        # The construction is the whole point: if git does NOT read the edit as clean,
        # the test proves nothing (it would pass against the buggy code too). Guard it —
        # on a host that cannot reproduce the stat-clean condition, skip rather than lie.
        porcelain = git(r.path, "-c", "core.checkStat=minimal",
                        "status", "--porcelain").stdout
        if porcelain.strip():
            self.skipTest("host cannot construct the stat-clean same-tick condition")
        derived = ri.derive_candidate_identity(str(r.path))
        # The derived tree must carry the POST-edit blob for a.txt, not the pre-edit one.
        want = git(r.path, "hash-object", "a.txt").stdout.strip()  # blob of worktree "two\n"
        entry = git(r.path, "ls-tree", derived, "a.txt").stdout
        self.assertIn(want, entry,
                      f"derived tree carries a stale a.txt blob: {entry!r}")

    def test_ineffective_backdate_refuses_instead_of_deriving(self):
        """A backdate the filesystem did not store refuses with a named reason.

        The fail-closed sibling of the test above. `os.utime` reporting success is not
        evidence the value was stored: a coarse-granularity or clamping filesystem can
        truncate the epoch second to 0 — the value git reads as an unset index timestamp,
        which short-circuits `is_racy_stat` and disarms the very rule the backdate arms —
        and a filesystem that accepts the call while keeping the creation time fails the
        same comparison from the other side. Either one silently returns `git add -A` to
        the stale-stat path that yields the pre-edit blob, i.e. reintroduces the #1117
        collision with no error. A no-op `os.utime` stands in for both (the temp index
        keeps its creation mtime), proving the read-back raises rather than deriving an
        identity from stat data the backdate never protected.
        """
        r = self._repo()
        r.write("a.txt", "one\n")
        r.commit_all("a")
        orig = ri.os.utime

        def noop(*a, **k):
            return None

        ri.os.utime = noop
        try:
            with self.assertRaises(ri.IdentityError) as cm:
                ri.derive_candidate_identity(str(r.path))
        finally:
            ri.os.utime = orig
        self.assertTrue(
            cm.exception.reason.startswith("index_backdate_ineffective:"),
            cm.exception.reason,
        )
        # Negative control: with the real os.utime the same repository derives normally,
        # so the refusal above is attributable to the ineffective backdate and not to
        # anything else in the fixture.
        self.assertRegex(ri.derive_candidate_identity(str(r.path)), r"^[0-9a-f]{40,64}$")

    def test_one_byte_change_after_unequal(self):
        r = self._repo()
        r.write("a.txt", "one\n")
        derived = ri.derive_candidate_identity(str(r.path))
        r.write("a.txt", "onx\n")
        self.assertNotEqual(derived, ri.derive_candidate_identity(str(r.path)))

    def test_gitignored_append_equal(self):
        r = self._repo()
        r.write(".gitignore", "/.prflow/*\nignored.log\n")
        r.write("ignored.log", "x\n")
        derived = ri.derive_candidate_identity(str(r.path))
        r.write("ignored.log", "x\nmore\n")
        self.assertEqual(derived, ri.derive_candidate_identity(str(r.path)))

    def test_deletion_committed_equal(self):
        r = self._repo()
        r.write("a.txt", "one\n")
        r.commit_all("a")
        os.remove(r.path / "a.txt")
        derived = ri.derive_candidate_identity(str(r.path))
        r.commit_all("del")
        self.assertEqual(derived, committed_tree(r.path))

    def test_rename_committed_equal(self):
        r = self._repo()
        r.write("a.txt", "one\n")
        r.commit_all("a")
        os.rename(r.path / "a.txt", r.path / "renamed.txt")
        derived = ri.derive_candidate_identity(str(r.path))
        r.commit_all("ren")
        self.assertEqual(derived, committed_tree(r.path))

    def test_commit_am_falsifier_unequal(self):
        r = self._repo()
        r.write("a.txt", "one\n")
        r.commit_all("a")
        r.write("a.txt", "two\n")   # tracked mod
        r.write("b.txt", "new\n")   # untracked
        derived = ri.derive_candidate_identity(str(r.path))
        git(r.path, "commit", "-am", "am")   # stages tracked mods only
        self.assertNotEqual(derived, committed_tree(r.path))

    def test_index_not_modified(self):
        r = self._repo()
        r.write("a.txt", "one\n")
        r.commit_all("a")
        r.write("a.txt", "two\n")
        r.write("b.txt", "new\n")
        index = r.path / ".git" / "index"
        before = index.read_bytes()
        ri.derive_candidate_identity(str(r.path))
        self.assertEqual(before, index.read_bytes())

    def test_shallow_equals_full(self):
        src = self._repo()
        for i in range(3):
            src.write("a.txt", f"v{i}\n")
            src.commit_all(f"c{i}")
        src.write("a.txt", "dirty\n")
        src.write("u.txt", "untracked\n")
        full = ri.derive_candidate_identity(str(src.path))
        shallow = Path(tempfile.mkdtemp()) / "shallow"
        git(Path(tempfile.gettempdir()), "clone", "-q", "--depth", "1",
            f"file://{src.path}", str(shallow))
        (shallow / "a.txt").write_text("dirty\n")
        (shallow / "u.txt").write_text("untracked\n")
        self.assertEqual(full, ri.derive_candidate_identity(str(shallow)))

    def test_sparse_cone_equals_committed(self):
        src = self._repo()
        src.write("inc/keep.txt", "keep\n")
        src.write("exc/drop.txt", "drop\n")
        src.commit_all("tree")
        clone = Path(tempfile.mkdtemp()) / "sparse"
        git(Path(tempfile.gettempdir()), "clone", "-q", f"file://{src.path}", str(clone))
        git(clone, "sparse-checkout", "init", "--cone")
        git(clone, "sparse-checkout", "set", "inc")
        # exc/ is off disk now; make an in-cone change and derive
        (clone / "inc" / "keep.txt").write_text("keep2\n")
        derived = ri.derive_candidate_identity(str(clone))
        git(clone, "commit", "-am", "sparse")
        self.assertEqual(derived, committed_tree(clone))
        # the derived tree still lists the skip-worktree path
        listing = git(clone, "ls-tree", "-r", "--name-only", derived).stdout
        self.assertIn("exc/drop.txt", listing)

    def test_no_commits(self):
        d = Path(tempfile.mkdtemp())
        git(d, "init", "-q")
        (d / "a.txt").write_text("x\n")
        # No HEAD yet; write-tree still succeeds against the staged content.
        val = ri.derive_candidate_identity(str(d))
        self.assertRegex(val, r"^[0-9a-f]{40,64}$")

    def test_empty_tree(self):
        d = Path(tempfile.mkdtemp())
        git(d, "init", "-q")
        val = ri.derive_candidate_identity(str(d))
        self.assertRegex(val, r"^[0-9a-f]{40,64}$")

    def test_mode_change(self):
        r = self._repo()
        p = r.path / "s.sh"
        p.write_text("#!/bin/sh\n")
        r.commit_all("s")
        os.chmod(p, 0o755)
        derived = ri.derive_candidate_identity(str(r.path))
        r.commit_all("mode")
        self.assertEqual(derived, committed_tree(r.path))

    def test_symlink_tracked(self):
        r = self._repo()
        r.write("target.txt", "t\n")
        os.symlink("target.txt", r.path / "link")
        r.commit_all("link")
        r.write("target.txt", "t2\n")
        derived = ri.derive_candidate_identity(str(r.path))
        r.commit_all("edit")
        self.assertEqual(derived, committed_tree(r.path))

    def test_newline_filename(self):
        r = self._repo()
        weird = r.path / "a\nb.txt"
        try:
            weird.write_text("x\n")
        except OSError:
            self.skipTest("filesystem rejects newline in filename")
        derived = ri.derive_candidate_identity(str(r.path))
        r.commit_all("nl")
        self.assertEqual(derived, committed_tree(r.path))

    def test_assume_unchanged_edit_does_not_change_identity(self):
        """The documented CE_VALID invariance, exercised.

        Round-3 review: the docs assert that an `assume-unchanged` path's
        worktree edit does not change the derived identity — a surprising,
        load-bearing consequence of seeding the temp index from the real index,
        previously backed only by a throwaway manual probe. This is the more
        surprising direction than the sparse-checkout half: a REAL on-disk edit
        that `git add -A` must not re-stat. A future git behavior change (or a
        "simplify to a fresh index" refactor) breaks it silently otherwise.
        """
        r = self._repo()
        r.write("a.txt", "x\n")
        r.commit_all("seed a")
        before = ri.derive_candidate_identity(str(r.path))
        git(r.path, "update-index", "--assume-unchanged", "a.txt")
        r.write("a.txt", "EDITED — must be invisible to the identity\n")
        self.assertEqual(ri.derive_candidate_identity(str(r.path)), before)
        # Positive control on the SAME fixture: once the flag is cleared, the
        # very same edit DOES move the identity — so the equality above is the
        # assume-unchanged flag's doing, not an inert derivation.
        git(r.path, "update-index", "--no-assume-unchanged", "a.txt")
        self.assertNotEqual(ri.derive_candidate_identity(str(r.path)), before)

    def test_absent_index(self):
        r = self._repo()
        r.write("a.txt", "x\n")
        index = r.path / ".git" / "index"
        if index.exists():
            os.remove(index)
        val = ri.derive_candidate_identity(str(r.path))
        self.assertRegex(val, r"^[0-9a-f]{40,64}$")


class FailureModeTests(unittest.TestCase):
    def test_git_absent(self):
        r = ScratchRepo(Path(tempfile.mkdtemp()))
        orig = ri.GIT
        ri.GIT = "definitely-not-a-real-git-binary-xyz"
        try:
            with self.assertRaises(ri.IdentityError) as cm:
                ri.derive_candidate_identity(str(r.path))
            self.assertEqual(cm.exception.reason, "git_not_found")
        finally:
            ri.GIT = orig

    def test_not_a_repo(self):
        d = Path(tempfile.mkdtemp())
        with self.assertRaises(ri.IdentityError) as cm:
            ri.derive_candidate_identity(str(d))
        self.assertTrue(cm.exception.reason.startswith("git_failed:"))


class RecordCliTests(unittest.TestCase):
    def _repo(self):
        return ScratchRepo(Path(tempfile.mkdtemp()))

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = rr.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_record_writes_both_and_pointer(self):
        r = self._repo()
        r.write("a.txt", "x\n")
        code, out, err = self._run(["record", "--repo-root", str(r.path)])
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertTrue(payload["ok"])
        token = payload["claim_context_token"]
        self.assertRegex(token, r"^[0-9a-f]{32}$")
        idp = Path(payload["identity_path"])
        fdp = Path(payload["findings_path"])
        self.assertTrue(idp.exists() and fdp.exists())
        idrec = json.loads(idp.read_text())
        self.assertEqual(idrec["candidate_identity"], payload["candidate_identity"])
        self.assertEqual(idrec["claim_context_token"], token)
        fdrec = json.loads(fdp.read_text())
        self.assertEqual(fdrec["claim_context_token"], token)
        self.assertEqual(fdrec["findings"], [])
        pointer = json.loads((idp.parent / rr.POINTER_NAME).read_text())
        self.assertEqual(pointer["identity_path"], str(idp))
        self.assertEqual(pointer["findings_path"], str(fdp))

    def test_token_is_random(self):
        r = self._repo()
        t1 = json.loads(self._run(["record", "--repo-root", str(r.path)])[1])["claim_context_token"]
        t2 = json.loads(self._run(["record", "--repo-root", str(r.path)])[1])["claim_context_token"]
        self.assertNotEqual(t1, t2)

    def test_dir_not_ignored_no_write(self):
        # A repo with NO ignore rule for the session dir.
        d = Path(tempfile.mkdtemp())
        git(d, "init", "-q")
        (d / "a.txt").write_text("x\n")
        git(d, "add", "a.txt")
        git(d, "commit", "-qm", "seed")
        code, out, err = self._run(["record", "--repo-root", str(d)])
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assertIn("session_dir_not_ignored", err)
        self.assertFalse((d / rr.SESSION_DIRNAME).exists())

    def test_never_invoked_no_pointer(self):
        r = self._repo()
        self.assertFalse((r.path / rr.SESSION_DIRNAME / rr.POINTER_NAME).exists())

    def test_idempotent_record(self):
        r = self._repo()
        r.write("a.txt", "x\n")
        p1 = json.loads(self._run(["record", "--repo-root", str(r.path)])[1])
        token = p1["claim_context_token"]
        # append a disposition
        self._run(["append-disposition", "--repo-root", str(r.path), "--token", token,
                   "--summary", "s", "--disposition", "fixed"])
        # re-record for the same token: findings preserved, no duplicate
        p2 = json.loads(self._run(["record", "--repo-root", str(r.path), "--token", token])[1])
        self.assertEqual(p2["claim_context_token"], token)
        fdrec = json.loads(Path(p2["findings_path"]).read_text())
        self.assertEqual(len(fdrec["findings"]), 1)
        # UNCHANGED tree: the identity half of the AC. The value is re-derived, so
        # assert it re-derived EQUAL rather than assuming continuity, and assert the
        # rebind channel stayed silent.
        self.assertEqual(p2["candidate_identity"], p1["candidate_identity"])
        self.assertIsNone(p2["rebound_from"])

    def test_rerecord_after_edit_rebinds_and_surfaces_it(self):
        """A re-record whose tree changed rebinds the token — and says so.

        PR #681 review: the AC calls the identity artifact idempotent, but the value
        is re-derived every call, so a same-token re-record after an edit silently
        rebound a token a consumer already held. Rebinding is correct for a content
        identity; going UNANNOUNCED was the defect. Pins both halves: the value
        actually changes, and the change is reported on stdout and stderr.
        """
        r = self._repo()
        r.write("a.txt", "x\n")
        p1 = json.loads(self._run(["record", "--repo-root", str(r.path)])[1])
        token = p1["claim_context_token"]
        r.write("a.txt", "edited\n")
        code, out, err = self._run(["record", "--repo-root", str(r.path), "--token", token])
        self.assertEqual(code, 0)
        p2 = json.loads(out)
        # the identity genuinely re-derived to a different value
        self.assertNotEqual(p2["candidate_identity"], p1["candidate_identity"])
        self.assertEqual(p2["candidate_identity"], ri.derive_candidate_identity(str(r.path)))
        # and the rebind is surfaced on both channels, naming the superseded value
        self.assertEqual(p2["rebound_from"], p1["candidate_identity"])
        # Located by NAME, not by position: an unrelated warning (e.g. a failed
        # session-dir chmod) is emitted after this one on some hosts and would
        # otherwise displace the record under test.
        warn = ReviewFixTests._warning(err, "candidate_identity_rebound")
        self.assertEqual(warn["previous_candidate_identity"], p1["candidate_identity"])
        self.assertEqual(warn["candidate_identity"], p2["candidate_identity"])

    def test_append_disposition_checks_ignore_precondition(self):
        """append-disposition runs the ignore precondition too (PR #681 review).

        --session-dir is per-invocation, so nothing binds an append to the directory
        a prior record validated. Positive control: the same fixture succeeds through
        the default (ignored) session dir, so the rejection below is attributable to
        the ignore state and not to an unrelated precondition.
        """
        r = self._repo()
        r.write("a.txt", "x\n")
        token = json.loads(self._run(["record", "--repo-root", str(r.path)])[1])["claim_context_token"]
        # positive control: the fixture is otherwise valid
        ok, _out, _err = self._run(["append-disposition", "--repo-root", str(r.path),
                                    "--token", token, "--summary", "s",
                                    "--disposition", "fixed"])
        self.assertEqual(ok, 0)
        # now point the append at a NON-ignored session dir carrying a ledger
        tracked = r.path / "tracked-sessions"
        tracked.mkdir()
        (tracked / f"{token}.findings.json").write_text(
            json.dumps({"schema_version": rr.SCHEMA_VERSION,
                        "kind": "reception-findings",
                        "claim_context_token": token, "findings": []})
        )
        code, out, err = self._run(["append-disposition", "--repo-root", str(r.path),
                                    "--session-dir", str(tracked), "--token", token,
                                    "--summary", "s", "--disposition", "fixed"])
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        # attribute the rejection to the guard under test, not to a sibling guard
        self.assertIn("session_dir_not_ignored", json.loads(err)["reason"])

    def test_disposition_assigns_id(self):
        r = self._repo()
        r.write("a.txt", "x\n")
        token = json.loads(self._run(["record", "--repo-root", str(r.path)])[1])["claim_context_token"]
        c, out, err = self._run(["append-disposition", "--repo-root", str(r.path),
                                 "--token", token, "--summary", "s1", "--disposition", "fixed"])
        self.assertEqual(c, 0, err)
        self.assertEqual(json.loads(out)["finding_id"], "f001")
        c, out, _ = self._run(["append-disposition", "--repo-root", str(r.path),
                               "--token", token, "--summary", "s2", "--disposition",
                               "deferred", "--channel", "code-comment"])
        self.assertEqual(json.loads(out)["finding_id"], "f002")

    def test_deferral_requires_channel(self):
        r = self._repo()
        r.write("a.txt", "x\n")
        token = json.loads(self._run(["record", "--repo-root", str(r.path)])[1])["claim_context_token"]
        c, out, err = self._run(["append-disposition", "--repo-root", str(r.path),
                                 "--token", token, "--summary", "s", "--disposition", "deferred"])
        self.assertNotEqual(c, 0)
        self.assertEqual(out, "")
        self.assertIn("deferral_missing_channel", err)

    def test_disposition_records_channel(self):
        r = self._repo()
        r.write("a.txt", "x\n")
        token = json.loads(self._run(["record", "--repo-root", str(r.path)])[1])["claim_context_token"]
        self._run(["append-disposition", "--repo-root", str(r.path), "--token", token,
                   "--summary", "s", "--disposition", "pushback", "--channel", "pr-thread"])
        fdp = r.path / rr.SESSION_DIRNAME / f"{token}.findings.json"
        entry = json.loads(fdp.read_text())["findings"][0]
        self.assertEqual(entry["channel"], "pr-thread")

    def test_unwritable_dir_no_identity(self):
        # uid-independent unwritability: a regular FILE stands where a session-dir
        # parent component must be, so mkdir raises NotADirectoryError regardless
        # of the runner uid (a chmod 0500 dir is bypassed by root in CI).
        r = self._repo()
        r.write("a.txt", "x\n")
        blocker = r.path / ".prflow" / "tmp" / "blocker"
        blocker.parent.mkdir(parents=True, exist_ok=True)
        blocker.write_text("i am a file\n")
        sd = blocker / "sub"   # a directory under a file -> unwritable by construction
        code, out, err = self._run(["record", "--repo-root", str(r.path),
                                    "--session-dir", str(sd)])
        self.assertNotEqual(code, 0)
        self.assertNotIn("candidate_identity", out)
        self.assertIn("write_failed", err)


class AdversarialArtifactMatrixTests(unittest.TestCase):
    """Six-shape matrix over the findings artifact the append path reads back."""

    def _repo_token(self):
        r = ScratchRepo(Path(tempfile.mkdtemp()))
        r.write("a.txt", "x\n")
        out = io.StringIO()
        with redirect_stdout(out):
            rr.main(["record", "--repo-root", str(r.path)])
        token = json.loads(out.getvalue())["claim_context_token"]
        return r, token

    def _append(self, repo, token):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = rr.main(["append-disposition", "--repo-root", str(repo.path),
                            "--token", token, "--summary", "s", "--disposition", "fixed"])
        return code, out.getvalue(), err.getvalue()

    def _findings_path(self, repo, token):
        return repo.path / rr.SESSION_DIRNAME / f"{token}.findings.json"

    def test_matrix(self):
        cases = {
            # The positive control carries BOTH discriminators (`kind` and the
            # session's own token), so it proves the fixture is otherwise valid
            # rather than passing because the guard tolerated absent tags.
            "object_valid": ("__VALID__", True),
            "array": (json.dumps([1, 2, 3]), False),
            "scalar": (json.dumps(5), False),
            "valid_falsy": (json.dumps(False), False),
            "missing": (None, False),
            "wrong_type_findings": (json.dumps({"findings": "nope"}), False),
        }
        for name, (content, ok) in cases.items():
            with self.subTest(name):
                repo, token = self._repo_token()
                fdp = self._findings_path(repo, token)
                if content == "__VALID__":
                    content = json.dumps({
                        "schema_version": 1, "kind": "reception-findings",
                        "claim_context_token": token, "findings": [],
                    })
                if content is None:
                    os.remove(fdp)
                else:
                    fdp.write_text(content)
                code, out, err = self._append(repo, token)
                if ok:
                    self.assertEqual(code, 0, err)
                else:
                    self.assertNotEqual(code, 0)
                    self.assertEqual(out, "")
                    self.assertTrue(err.strip())

    def test_truncated_and_non_utf8(self):
        repo, token = self._repo_token()
        fdp = self._findings_path(repo, token)
        fdp.write_text('{"findings": [')  # truncated JSON
        code, _out, err = self._append(repo, token)
        self.assertNotEqual(code, 0)
        self.assertIn("findings_malformed", err)
        fdp.write_bytes(b"\xff\xfe not utf8")
        code, _out, err = self._append(repo, token)
        self.assertNotEqual(code, 0)


class FlightExtensionTests(unittest.TestCase):
    def _decl(self, with_ci=False):
        d = {
            "schema_version": vf.SCHEMA_VERSION,
            "profile": {
                "profile_version": "1",
                "argv": ["run.sh"],
                "cwd": "/x",
                "environment": {},
                "toolchain": {},
                "dependencies": {},
                "output_roots": [],
                "external_services": "none",
            },
            "checkout": _valid_checkout(),
        }
        if with_ci:
            d["candidate_identity"] = "deadbeef" * 5
        return d

    def test_flight_key_unchanged_by_sibling_field(self):
        base = vf._derive(self._decl(with_ci=False))
        withid = vf._derive(self._decl(with_ci=True))
        self.assertEqual(base["flight_key"], withid["flight_key"])
        self.assertEqual(base["descriptor_digest"], withid["descriptor_digest"])

    def test_candidate_identity_recorded(self):
        d = vf._derive(self._decl(with_ci=True))
        self.assertEqual(d["candidate_identity"], "deadbeef" * 5)

    def test_absent_field_records_none(self):
        d = vf._derive(self._decl(with_ci=False))
        self.assertIsNone(d["candidate_identity"])

    def test_claim_handle_records_candidate_identity(self):
        state = Path(tempfile.mkdtemp())
        logs = Path(tempfile.mkdtemp())
        decl = Path(tempfile.mkdtemp()) / "d.json"
        decl.write_text(json.dumps(self._decl(with_ci=True)))
        out = io.StringIO()
        with redirect_stdout(out):
            code = vf.main(["claim", "--input-file", str(decl),
                            "--state-dir", str(state), "--logs-dir", str(logs)])
        self.assertEqual(code, vf.EXIT_OK)
        key = json.loads(out.getvalue())["flight_key"]
        handle = json.loads((state / f"{key}.json").read_text())
        self.assertEqual(handle["candidate_identity"], "deadbeef" * 5)


class ReviewFixTests(unittest.TestCase):
    """PR #681 review round 2: fixes for findings the Phase-3 roster raised.

    Each test pins the OUTCOME the finding named, not the precondition — an
    unreadable prior identity must be reported as undetermined (not as absent),
    the default session dir must resolve from the git ROOT (not the cwd), and a
    ledger whose own tags disagree with the request must be refused rather than
    joined.
    """

    def _repo(self):
        return ScratchRepo(Path(tempfile.mkdtemp()))

    def _run(self, argv, cwd=None):
        out, err = io.StringIO(), io.StringIO()
        prev = os.getcwd()
        if cwd:
            os.chdir(cwd)
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = rr.main(argv)
        finally:
            os.chdir(prev)
        return code, out.getvalue(), err.getvalue()

    def _record(self, repo):
        return json.loads(self._run(["record", "--repo-root", str(repo.path)])[1])

    @staticmethod
    def _warning(err, name):
        """Find a named stderr warning record by NAME, never by position.

        Asserting on `err.splitlines()[-1]` couples the test to diagnostic
        ordering: on a host where the session-dir chmod fails, that unrelated
        warning would displace the record under test and fail the test for a
        reason it does not assert.
        """
        for line in err.strip().splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("warning") == name or (name == "error" and not rec.get("ok")):
                return rec
        raise AssertionError(f"no {name!r} record in stderr: {err!r}")

    # ── Finding A (corroborated x2): rebind detection fell open on a degraded
    # prior identity artifact — `rebound_from: null` positively asserted
    # "identity unchanged" while the artifact was being overwritten.
    def test_unreadable_prior_identity_reports_undetermined_not_absent(self):
        for name, content in (
            ("malformed", '{"candidate_identity": '),
            ("not_object", "[1,2,3]"),
            ("empty", "   "),
            ("non_utf8", None),
        ):
            with self.subTest(name):
                r = self._repo()
                r.write("a.txt", "x\n")
                p1 = self._record(r)
                token = p1["claim_context_token"]
                idp = Path(p1["identity_path"])
                if content is None:
                    idp.write_bytes(b"\xff\xfe not utf8")
                else:
                    idp.write_text(content)
                r.write("a.txt", "edited\n")
                code, out, err = self._run(
                    ["record", "--repo-root", str(r.path), "--token", token])
                self.assertEqual(code, 0, err)
                p2 = json.loads(out)
                # NOT null: null is the positive claim "identity unchanged".
                self.assertEqual(p2["rebound_from"], "unknown")
                warn = self._warning(err, "prior_identity_unreadable")
                self.assertTrue(warn["reason"])

    # ── Finding E: CLAUDE.md's #295 repo-root contract. The default session dir
    # was cwd-anchored, so a run from a subdirectory composed
    # `<subdir>/.prflow/...`, which the root-anchored ignore rule cannot match —
    # producing a `session_dir_not_ignored` breadcrumb whose remedy is wrong.
    def test_default_session_dir_anchors_on_repo_root_not_cwd(self):
        r = self._repo()
        r.write("a.txt", "x\n")
        sub = r.path / "nested" / "deeper"
        sub.mkdir(parents=True)
        code, out, err = self._run(["record"], cwd=str(sub))
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertTrue(payload["ok"])
        # The artifacts land under the REPO ROOT's session dir, not the subdir's.
        self.assertEqual(
            Path(payload["identity_path"]).resolve().parent,
            (r.path / rr.SESSION_DIRNAME).resolve())
        self.assertFalse((sub / ".prflow").exists())

    def test_explicit_repo_root_still_honored_verbatim(self):
        # The root-anchoring applies only to the DEFAULT; an explicit value wins.
        r = self._repo()
        other = self._repo()
        code, out, err = self._run(["record", "--repo-root", str(other.path)],
                                   cwd=str(r.path))
        self.assertEqual(code, 0, err)
        self.assertEqual(
            Path(json.loads(out)["identity_path"]).resolve().parent,
            (other.path / rr.SESSION_DIRNAME).resolve())

    # ── Finding N (corroborated x2): `kind`/`claim_context_token` were written
    # as discriminators and never checked on read, so a ledger belonging to a
    # different session (or a different artifact kind entirely) was joined
    # silently — the one matrix-adjacent shape that yields a VALID-LOOKING ledger.
    def test_prior_identity_bad_value_shape_is_undetermined_not_unchanged(self):
        """The value field is the third way into the same fail-open.

        Round-3 review: two arms already render `unknown` (unreadable artifact,
        tag mismatch), but a well-formed, correctly-tagged artifact whose
        `candidate_identity` is missing or non-string fell past the
        `isinstance(prior_value, str)` test and left `rebound_from` at null —
        which positively asserts "identity unchanged" across an overwrite the
        helper could not actually compare. Same class, entered through the value.
        """
        for name, planted in (
            ("missing", {}),
            ("null", {"candidate_identity": None}),
            ("int", {"candidate_identity": 5}),
            ("object", {"candidate_identity": {}}),
            ("list", {"candidate_identity": []}),
            ("bool_false", {"candidate_identity": False}),
        ):
            with self.subTest(name):
                r = self._repo()
                r.write("a.txt", "x\n")
                p1 = self._record(r)
                token = p1["claim_context_token"]
                Path(p1["identity_path"]).write_text(json.dumps({
                    "kind": "reception-identity",
                    "claim_context_token": token,
                    **planted,
                }))
                r.write("a.txt", "edited\n")
                code, out, err = self._run(
                    ["record", "--repo-root", str(r.path), "--token", token])
                self.assertEqual(code, 0, err)
                self.assertEqual(json.loads(out)["rebound_from"], "unknown")
                self.assertEqual(
                    self._warning(err, "prior_identity_unreadable")["reason"],
                    "identity_value_not_string")

    def test_findings_ledger_token_mismatch_refused(self):
        r = self._repo()
        p = self._record(r)
        token = p["claim_context_token"]
        fdp = Path(p["findings_path"])
        rec = json.loads(fdp.read_text())
        rec["claim_context_token"] = "0" * 32
        fdp.write_text(json.dumps(rec))
        code, out, err = self._run(
            ["append-disposition", "--repo-root", str(r.path), "--token", token,
             "--summary", "s", "--disposition", "fixed"])
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assertIn("findings_token_mismatch", err)

    def test_findings_ledger_wrong_kind_refused(self):
        r = self._repo()
        p = self._record(r)
        token = p["claim_context_token"]
        fdp = Path(p["findings_path"])
        rec = json.loads(fdp.read_text())
        rec["kind"] = "reception-identity"
        fdp.write_text(json.dumps(rec))
        code, _out, err = self._run(
            ["append-disposition", "--repo-root", str(r.path), "--token", token,
             "--summary", "s", "--disposition", "fixed"])
        self.assertNotEqual(code, 0)
        self.assertIn("findings_wrong_kind", err)

    # Positive control on the SAME fixture: it is otherwise valid and the call
    # succeeds but for the one property under test (guard-class shape 3).
    def test_relative_session_dir_is_checked_and_written_at_one_path(self):
        """The ignore guard must validate the path the write actually uses.

        Round-2 shadow: `git check-ignore` ran with cwd=repo-root while the write
        resolved its Path against the PROCESS cwd, so a relative --session-dir
        made the guard pass on an ignored <root>/.prflow/... while the artifacts
        landed at <cwd>/.prflow/... — untracked, NOT ignored, and therefore part
        of the very content the identity hashes. Both halves are pinned: the
        artifacts land under the repo root, and the tree stays clean.
        """
        r = self._repo()
        r.write("a.txt", "x\n")
        sub = r.path / "nested" / "deep"
        sub.mkdir(parents=True)
        rel = os.path.join(".prflow", "tmp", "reception-sessions")
        code, out, err = self._run(
            ["record", "--session-dir", rel], cwd=str(sub))
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(
            Path(payload["identity_path"]).resolve().parent,
            (r.path / rel).resolve())
        self.assertFalse((sub / ".prflow").exists())
        # The write added no non-ignored content, so the identity it recorded is
        # still the identity of the tree right after the write.
        self.assertEqual(
            payload["candidate_identity"], ri.derive_candidate_identity(str(r.path)))
        porcelain = git(r.path, "status", "--porcelain").stdout
        self.assertNotIn("nested", porcelain)

    def test_explicitly_empty_token_is_refused_not_silently_minted(self):
        # `--token ""` is an INVALID token, not an absent one; falsiness-based
        # defaulting silently minted a fresh nonce under a caller that believed
        # it had supplied one.
        r = self._repo()
        code, out, err = self._run(
            ["record", "--repo-root", str(r.path), "--token", ""])
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assertIn("invalid_token", err)

    def test_findings_ledger_absent_tags_refused(self):
        """An ABSENT discriminator is not agreement.

        Round-2 fix-delta gate: the first guard only rejected a tag that was
        present-and-different, so `{"findings": []}` — the shape a hand-corrupting
        edit most naturally leaves — was accepted. Worse, the append path rewrites
        the object it read without restoring the tags, so a tagless ledger stayed
        tagless and the guard could never fire on it again.
        """
        for name, planted in (
            ("both_absent", {"findings": []}),
            ("kind_absent", {"claim_context_token": "PLACEHOLDER", "findings": []}),
            ("token_absent", {"kind": "reception-findings", "findings": []}),
        ):
            with self.subTest(name):
                r = self._repo()
                p = self._record(r)
                token = p["claim_context_token"]
                if planted.get("claim_context_token") == "PLACEHOLDER":
                    planted = dict(planted, claim_context_token=token)
                Path(p["findings_path"]).write_text(json.dumps(planted))
                code, out, err = self._run(
                    ["append-disposition", "--repo-root", str(r.path),
                     "--token", token, "--summary", "s", "--disposition", "fixed"])
                self.assertNotEqual(code, 0)
                self.assertEqual(out, "")
                self.assertTrue(
                    "findings_wrong_kind" in err or "findings_token_mismatch" in err,
                    err)

    def test_identity_artifact_tag_mismatch_is_not_lifted_into_rebound_from(self):
        """A foreign identity artifact's value never reaches the rendered block.

        The skill renders a non-null `rebound_from` into preflight fact 10, so a
        planted artifact whose own tags disagree with the request must report the
        comparison as undetermined rather than echo an arbitrary string.
        """
        r = self._repo()
        r.write("a.txt", "x\n")
        p1 = self._record(r)
        token = p1["claim_context_token"]
        Path(p1["identity_path"]).write_text(json.dumps({
            "kind": "reception-identity",
            "claim_context_token": "deadbeef",
            "candidate_identity": "FOREIGN-VALUE",
        }))
        r.write("a.txt", "edited\n")
        code, out, err = self._run(
            ["record", "--repo-root", str(r.path), "--token", token])
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["rebound_from"], "unknown")
        self.assertNotIn("FOREIGN-VALUE", out)
        self.assertEqual(
            self._warning(err, "prior_identity_unreadable")["reason"],
            "identity_tag_mismatch")

    def test_findings_ledger_matching_tags_accepted(self):
        r = self._repo()
        p = self._record(r)
        code, out, err = self._run(
            ["append-disposition", "--repo-root", str(r.path),
             "--token", p["claim_context_token"],
             "--summary", "s", "--disposition", "fixed"])
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["finding_id"], "f001")

    # ── The six-shape matrix over `cmd_record`'s OWN read-backs. The shipped
    # matrix covered only the append-disposition read-back.
    def test_record_readback_matrix(self):
        cases = {
            # The positive-control row carries BOTH discriminators, so it proves
            # the fixture is otherwise valid rather than riding a permissive guard.
            "object_valid": ("__VALID__", True),
            "array": (json.dumps([1, 2, 3]), False),
            "scalar": (json.dumps(5), False),
            "valid_falsy_false": (json.dumps(False), False),
            "valid_falsy_empty_string": (json.dumps(""), False),
            "wrong_type_findings": (json.dumps({"findings": "nope"}), False),
        }
        for name, (content, ok) in cases.items():
            with self.subTest(name):
                r = self._repo()
                p = self._record(r)
                token = p["claim_context_token"]
                if content == "__VALID__":
                    content = json.dumps({
                        "schema_version": 1, "kind": "reception-findings",
                        "claim_context_token": token, "findings": [],
                    })
                Path(p["findings_path"]).write_text(content)
                code, out, err = self._run(
                    ["record", "--repo-root", str(r.path), "--token", token])
                if ok:
                    self.assertEqual(code, 0, err)
                else:
                    self.assertNotEqual(code, 0)
                    self.assertEqual(out, "")
                    self.assertIn("existing_findings_", err)

    # A well-formed object whose identity token is an empty string is the
    # valid-falsy row the Testing Strategy names for the IDENTITY artifact.
    def test_record_readback_empty_prior_identity_is_a_reported_rebind(self):
        r = self._repo()
        r.write("a.txt", "x\n")
        p1 = self._record(r)
        token = p1["claim_context_token"]
        idp = Path(p1["identity_path"])
        rec = json.loads(idp.read_text())
        rec["candidate_identity"] = ""
        idp.write_text(json.dumps(rec))
        r.write("a.txt", "edited\n")
        code, out, err = self._run(
            ["record", "--repo-root", str(r.path), "--token", token])
        self.assertEqual(code, 0, err)
        # An empty prior value is a real (falsy) string that differs from the
        # derived one, so it is a genuine rebind — reported, never swallowed.
        self.assertEqual(json.loads(out)["rebound_from"], "")

    # ── Finding I: the module docstring promises EVERY error path emits the
    # {"ok": false, "reason": ...} record; an exception outside IdentityError /
    # OSError escaped as a bare traceback instead.
    def test_unexpected_exception_becomes_attributable_record(self):
        r = self._repo()
        orig = rr._atomic_write_json

        def boom(*a, **k):
            raise RuntimeError("synthetic")

        rr._atomic_write_json = boom
        try:
            code, out, err = self._run(["record", "--repo-root", str(r.path)])
        finally:
            rr._atomic_write_json = orig
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        payload = self._warning(err, "error")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["reason"], "internal_error:RuntimeError")

    # ── Final-pass finding 5: the `temp_index_error` arm shipped untested.
    def test_unwritable_tmpdir_yields_temp_index_breadcrumb(self):
        r = self._repo()
        orig = ri.tempfile.mkstemp

        def denied(*a, **k):
            raise PermissionError("read-only TMPDIR")

        ri.tempfile.mkstemp = denied
        try:
            with self.assertRaises(ri.IdentityError) as cm:
                ri.derive_candidate_identity(str(r.path))
        finally:
            ri.tempfile.mkstemp = orig
        self.assertEqual(cm.exception.reason, "temp_index_error:PermissionError")

    # ── Final-pass / pr-test-analyzer: pin the atomicity property the
    # non-atomic-write deferral rationale rests on — a failed write leaves the
    # PRIOR artifact intact and drops no temp file.
    def test_failed_write_leaves_prior_artifact_intact(self):
        r = self._repo()
        p = self._record(r)
        fdp = Path(p["findings_path"])
        before = fdp.read_bytes()
        orig = os.replace
        os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError("no space"))
        try:
            code, _out, err = self._run(
                ["append-disposition", "--repo-root", str(r.path),
                 "--token", p["claim_context_token"],
                 "--summary", "s", "--disposition", "fixed"])
        finally:
            os.replace = orig
        self.assertNotEqual(code, 0)
        self.assertIn("write_failed", err)
        self.assertEqual(fdp.read_bytes(), before)
        strays = [q for q in fdp.parent.iterdir() if q.name.startswith(".rr-")]
        self.assertEqual(strays, [])

    # ── Type-design finding M: the one new declaration field was the only
    # unvalidated one; a dict/int/empty-string was persisted into the handle and
    # compared silently unequal by a downstream consumer.
    def test_flight_candidate_identity_must_be_nonempty_string(self):
        for bad in ({}, [], 5, "", "   ", False):
            with self.subTest(repr(bad)):
                d = {
                    "schema_version": vf.SCHEMA_VERSION,
                    "profile": {
                        "profile_version": "1", "argv": ["run.sh"], "cwd": "/x",
                        "environment": {}, "toolchain": {}, "dependencies": {},
                        "output_roots": [], "external_services": "none",
                    },
                    "checkout": _valid_checkout(),
                    "candidate_identity": bad,
                }
                with self.assertRaises(vf.DeclarationError) as cm:
                    vf._derive(d)
                self.assertIn("candidate_identity", str(cm.exception))

    def test_flight_absent_candidate_identity_still_accepted(self):
        # Positive control: absent stays legal and records None (the AC).
        d = {
            "schema_version": vf.SCHEMA_VERSION,
            "profile": {
                "profile_version": "1", "argv": ["run.sh"], "cwd": "/x",
                "environment": {}, "toolchain": {}, "dependencies": {},
                "output_roots": [], "external_services": "none",
            },
            "checkout": _valid_checkout(),
        }
        self.assertIsNone(vf._derive(d)["candidate_identity"])


# Deferred coverage gaps (PR #681 reception pass, review Important finding 2 —
# annotated by the review itself as a suspected over-grade; triaged on the code).
# WHAT: the untested arms — the `git_exec_error` and `empty_tree_output`
#   IdentityError breadcrumbs; the `invalid_token` charset guard; and the
#   `ignore_check_failed` (git rc 128) arm.
#   (PR #681 review round 2 DISCHARGED two arms this note previously listed:
#   `temp_index_error` is now covered by ReviewFixTests'
#   test_unwritable_tmpdir_yields_temp_index_breadcrumb, and the `record`
#   read-back six-shape matrix by test_record_readback_matrix plus its
#   empty-string-token valid-falsy sibling. Both were removed from this list
#   rather than left as a stale claim.)
# WHY deferred: every one of these arms fails CLOSED by construction — each
#   raises/returns a named breadcrumb on stderr, prints nothing a caller could
#   read as a derived identity, and exits non-zero. The untested surface is the
#   *attribution* of an already-safe refusal, not a path that can admit a wrong
#   identity or a valid-looking ledger. The happy paths and the fail-open-capable
#   reads (the append-disposition read-back matrix, the ignore-rule precondition)
#   are covered. Nothing here gates the verdict at the `critical` threshold.
# REVISIT: if any of these arms is ever changed to return a value instead of
#   raising, if a caller starts branching on a specific reason string, or if a
#   regression lands in one of them — at which point add the missing rows rather
#   than re-litigating the deferral.

if __name__ == "__main__":
    unittest.main()
