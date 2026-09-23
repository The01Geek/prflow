#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Cloud-CI verification request/wait/evidence adapter (issue #403).

A PRFlow cloud implement run, in the explicitly-selected CI verification mode, offloads
a full-suite verification boundary to the repository's existing CI workflow instead of
running the suite on its own implementation host. This helper is the granted foreground
command that owns that lifecycle:

  request          persist a verification request BEFORE dispatch, bind it to the
                   candidate (repo, workflow, request identity, source HEAD, base
                   context, tested checkout fingerprint), then dispatch `ci.yml` for the
                   pushed candidate, record the accepted dispatch as
                   dispatched-uncorrelated before correlating it to a run id.
                   Repeated attachment reuses the run; an accepted dispatch whose
                   correlation is ambiguous, lost, or failed is reconciled by request
                   identity before another dispatch. A new dispatch first runs the
                   config-listed pre-request checks and refuses while one fails.
                   `--ref` must name the branch carrying the candidate: it defaults to
                   `--base`, so a caller that omits it dispatches a run whose checkout is
                   not the candidate and the worker-checkout binding refuses it.
  wait             poll the run inside ONE bounded foreground tool call (kept shorter
                   than the Bash ceiling); a per-call deadline records `pending` and
                   preserves the request for a further foreground attachment. Transport
                   errors are bounded and reported; auth failure, cancellation,
                   supersession, and exhausted budget are non-passing terminals carrying
                   the run URL and cause — none of them prints a passing outcome. Exit 0
                   is reserved for an established PASSED; a PENDING exits 3, so a caller
                   routing on the exit code alone cannot read it as a pass.
  collect-evidence build the versioned `cloud_ci_evidence` record for
                   `check-completion-evidence.py` from the run's shard-tally artifacts
                   (downloaded by the caller with `gh run download --dir <dir>`, named by
                   `--artifact-dir <dir>`) and its GitHub job conclusions, after
                   validating the worker tested the bound candidate. Artifact reads are
                   bounded and reject path traversal, and the diagnostic bytes are read as
                   data, never executed. The successful path emits the observed
                   identities, population, tallies and conclusions (inside the evidence
                   record); a refusal raised after the request record loads emits the
                   observed identities alone (population and tallies are not read before
                   the refusal points). A refusal raised while loading that record
                   (`no-request`/`bad-request`) has no identities to emit.
  check-deployment refuse CI mode with an actionable explanation when the deployment is
                   incomplete (config off, ci.yml dispatch inputs absent, the implement
                   profile missing either the helper grant or the `gh run download` grant
                   collect-evidence's artifact channel needs, or those grants missing from
                   devflow-implement.yml's GENERATED literal, which is what the matcher
                   reads), so an incompletely-deployed repository degrades to the existing
                   in-env cloud path rather than silently mis-verifying. Residual: it reads
                   this checkout, while a triggered run resolves the baked literal from the
                   default branch, so a grant this branch adds still ships inert (#593).

All GitHub and artifact I/O is behind two stub seams so the whole lifecycle is testable
offline with no network and no live Actions run:

  DEVFLOW_CI_REQUEST_GH_STUB      path to a JSON file mapping a gh-subcommand key to a
                                  canned {rc, stdout, stderr} response (or a list of
                                  responses consumed in order, for the poll loop).
  DEVFLOW_CI_REQUEST_ARTIFACT_DIR offline default for the artifact directory `collect-
                                  evidence --artifact-dir` names in production; a
                                  non-empty operand wins over it.

This helper only ever READS remote state and downloaded artifacts as data; it never
executes downloaded bytes and never widens a credential. The live end-to-end path is
exercised by the deferred post-activation pilot (issue #409), not by this helper's own
unit tests, which drive every branch through the stub seams.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unicodedata
import uuid
from pathlib import Path

# Resolve the state-config path through the shared #295/#1002 contract so a consumer
# still carrying a superseded `.devflow/` config is read-through and breadcrumbed exactly
# as every other Python reader does, rather than this helper hard-coding `.prflow/`.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
    from state_dir import state_config_path as _state_config_path
except Exception:  # pragma: no cover - partial-copy / exec'd-source arm
    def _state_config_path(repo_root, filename="config.json", stream=None):
        return str(Path(repo_root) / ".prflow" / filename)

# The shared per-shard provenance contract (issue #419), a sibling under scripts/. The
# explicit path insert is what lets an importlib-loaded copy (the test harness) resolve it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ci_shard_provenance as csp
from gh_fresh_env import fresh_gh_env

# The REQUEST-record schema version. Unchanged at 1 — issue #419 versions the EVIDENCE
# record separately (below) so bumping the evidence format never upgrades request records.
SCHEMA_VERSION = 1
# The cloud-completion-evidence format version, owned by the shared contract so the
# collector (producer) and check-completion-evidence.py (consumer) share one literal.
CLOUD_CI_EVIDENCE_SCHEMA_VERSION = csp.CLOUD_CI_EVIDENCE_SCHEMA_VERSION
# Where request records live. Under `.prflow/tmp/` so the state is per-checkout scratch,
# ignored by the same rule the issue-body cache relies on.
_REQUEST_DIRNAME = os.path.join(".prflow", "tmp", "ci-verification-requests")
# The declared CI contract this mode binds to. The completion validator binds the same
# name; a request naming any other workflow is out of contract.
_CI_WORKFLOW = "ci.yml"
# The per-call foreground wait must stay shorter than the Bash call ceiling so a run
# never loses the whole tool call to a timeout; a deadline reached records `pending` and
# the caller re-attaches. This default is a floor the caller may lower, never a hard cap
# on total budget (that is the caller's overall implementation budget).
_DEFAULT_DEADLINE_SECONDS = 600
_POLL_INTERVAL_SECONDS = 20
# Bounded transport retries: a transient gh failure is retried this many times before the
# wait reports a bounded transport error (never a passing or a hard-terminal outcome).
_MAX_TRANSPORT_RETRIES = 3
# Per-check wall-clock limit for a config-listed pre-request check (issue #870). Three checks
# at the limit (a pass, a failure, its merge-base re-run) stay under a 900 s Bash tool call.
_PRE_REQUEST_CHECK_TIMEOUT_SECONDS = 240
# A downloaded artifact larger than this is refused rather than read whole — the
# diagnostics are small text tallies, and an unbounded read is a denial-of-service seam.
_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024

# GitHub run conclusions that are terminal-and-non-passing. `success` is the only passing
# one; everything else (including an unknown string) is non-passing.
_SUCCESS_CONCLUSION = "success"
# The one non-passing conclusion a resume adopts: the suite ran on this head and failed.
_FAILURE_CONCLUSION = "failure"

# `wait` exit codes; the contract is stated in the module docstring.
_EXIT_PASSED = 0
_EXIT_PENDING = 3

# Failure-recap parse (issue #603). Reimplemented rather than imported: shard-tally.py, whose
# recap header/bullet rule this matches, lives under lib/test/ (pruned from the vendored
# plugin), so a shipped scripts/ helper must not import it (issue #603 AC10).
_RECAP_HEADER = "Failure recap:"
_RECAP_BULLET = re.compile(r"^  - (.*)$")
# Recap identifiers come from job-log text an attacker can influence, so bound their count
# and length and strip control bytes before printing them as data (as page-job-log.py does).
_RECAP_MAX_IDS = 200
_RECAP_MAX_CHARS = 500
_RECAP_ANSI_RE = re.compile(
    r"\x1b\[[0-9;:?]*[ -/]*[@-~]"          # CSI
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC … BEL or ST
    r"|\x1b[@-Z\\-_]"                      # other two-byte escapes
)
# A job log prefixes EVERY line with `<RFC3339 timestamp> ` (the jobs-logs API) or
# `group\tstep\t<RFC3339 timestamp> ` (`gh run view --log`); it must be stripped, or the
# exact-match recap header/bullet rule never fires against a real job log and the recap
# silently extracts nothing — issue #603 AC1. Anchored to the timestamp so a recap
# identifier that merely contains tabs is not mistaken for a prefix.
_GH_LOG_PREFIX_RE = re.compile(r"^(?:[^\t]*\t[^\t]*\t)?\d{4}-\d\d-\d\dT[\d:.]+Z ")


# _REFUSAL_TOKENS closes the refusal vocabulary so a raise-site typo cannot ship a
# garbage `REFUSED <token>` line to a caller that routes on the token (mirrors
# check-completion-evidence.py's ALL_TOKENS / verification-flight.py's ALL_STATES).
_REFUSAL_TOKENS = frozenset({
    "absent-shards",
    "ambiguous-dispatch",
    "artifact-too-large",
    "attempt-changed",
    "auth",
    "bad-artifact",
    "bad-head",
    "bad-jobs",
    "bad-provenance",
    "bad-request",
    "bad-request-id",
    "bad-tally",
    "dispatch-failed",
    "duplicate-shard",
    "foreign-workflow",
    "no-artifacts",
    "no-attempt",
    "no-provenance",
    "no-request",
    "no-run",
    "path-traversal",
    "pre-request-check-failed",
    "pre-request-check-unavailable",
    "provenance-mismatch",
    "run-not-successful",
    "transport",
    "worker-checkout-mismatch",
    "worker-checkout-unverifiable",
})


class _Refuse(Exception):
    """A validation/binding refusal. Carries a token and detail; the caller prints
    `REFUSED <token>: <detail>` and exits non-zero. Never a passing outcome."""

    def __init__(self, token: str, detail: str):
        # Closed-vocabulary guard: an out-of-vocabulary token is a programming error,
        # not a refusal to ship. It raises past main()'s _Refuse handler, so the process
        # still exits non-zero and prints no REFUSED line.
        if token not in _REFUSAL_TOKENS:
            raise ValueError(
                f"_Refuse token {token!r} is not one of {sorted(_REFUSAL_TOKENS)}")
        super().__init__(detail)
        self.token = token
        self.detail = detail


# ── stub-aware gh seam ─────────────────────────────────────────────────────────
def _gh_key(gh_args: list[str]) -> str:
    """A stable key for a gh invocation used to look up a canned stub response: the first
    two non-flag tokens — the subcommand and verb (e.g. `workflow run`, `run view`,
    `run list`) — so a positional operand (a workflow filename, a run id) does not vary
    the key."""
    parts: list[str] = []
    for a in gh_args:
        if a.startswith("-"):
            break
        parts.append(a)
        if len(parts) == 2:
            break
    return " ".join(parts)


_STUB_STATE: dict[str, int] = {}


def _gh(gh_args: list[str]) -> tuple[int, str, str]:
    """Run a gh subcommand, or return a canned stub response when
    DEVFLOW_CI_REQUEST_GH_STUB is set. Returns (rc, stdout, stderr). Never raises for a
    non-zero rc — the caller routes on rc and the outputs."""
    stub_path = os.environ.get("DEVFLOW_CI_REQUEST_GH_STUB")
    if stub_path:
        try:
            with open(stub_path, encoding="utf-8") as fh:
                table = json.load(fh)
        except (OSError, ValueError) as exc:
            return 3, "", f"ci-verification-request: unreadable gh stub table ({exc!r})"
        key = _gh_key(gh_args)
        resp = table.get(key)
        if resp is None:
            return 3, "", f"ci-verification-request: no stub response for gh key {key!r}"
        if isinstance(resp, list):
            # A sequence of responses consumed in order (the poll loop): the last one
            # repeats once exhausted, so a caller need not size the list to the retries.
            i = min(_STUB_STATE.get(key, 0), len(resp) - 1)
            _STUB_STATE[key] = _STUB_STATE.get(key, 0) + 1
            resp = resp[i]
        return int(resp.get("rc", 0)), str(resp.get("stdout", "")), str(resp.get("stderr", ""))
    gh_bin = os.environ.get("DEVFLOW_GH") or "gh"
    try:
        proc = subprocess.run(
            [gh_bin, *gh_args], capture_output=True, text=True, encoding="utf-8", env=fresh_gh_env()
        )
    except OSError as exc:
        return 3, "", f"ci-verification-request: gh invocation failed ({exc!r})"
    return proc.returncode, proc.stdout, proc.stderr


def _git(git_args: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(["git", *git_args], capture_output=True, text=True, encoding="utf-8")
    except OSError as exc:
        return 3, "", f"git invocation failed ({exc!r})"
    return proc.returncode, proc.stdout, proc.stderr


# ── request-record persistence ─────────────────────────────────────────────────
def _repo_root() -> str:
    rc, out, _ = _git(["rev-parse", "--show-toplevel"])
    return out.strip() if rc == 0 and out.strip() else os.getcwd()


def _request_dir() -> Path:
    d = Path(_repo_root()) / _REQUEST_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _request_path(request_id: str) -> Path:
    # request_id is our own generated uuid4 hex; guard anyway so a caller-supplied id can
    # never traverse out of the request directory.
    if not re.fullmatch(r"[0-9a-f]{8,64}", request_id):
        raise _Refuse("bad-request-id", f"request id {request_id!r} is not lowercase hex")
    return _request_dir() / f"{request_id}.json"


def _load_request(request_id: str) -> dict:
    path = _request_path(request_id)
    try:
        with open(path, encoding="utf-8") as fh:
            record = json.load(fh)
    except FileNotFoundError:
        raise _Refuse("no-request", f"no persisted request {request_id!r} under {path}")
    except (OSError, ValueError) as exc:
        raise _Refuse("bad-request", f"request {request_id!r} unreadable/corrupt ({exc!r})")
    if not isinstance(record, dict):
        raise _Refuse("bad-request", f"request {request_id!r} is not a JSON object")
    return record


def _store_request(record: dict) -> Path:
    path = _request_path(record["request_id"])
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(record, fh, sort_keys=True, indent=2)
    os.replace(tmp, path)  # atomic journal write
    return path


def _checkout_fingerprint() -> dict | None:
    """The five-field tested-checkout fingerprint, reused from the sibling helper rather
    than re-derived. Returns None (never raises) when the sibling cannot answer — the
    request still binds the source HEAD and base; the fingerprint is a best-effort
    extra tested-tree binding the worker-validation step cross-checks when present."""
    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checkout-fingerprint.py")
    try:
        proc = subprocess.run([sys.executable, helper], capture_output=True, text=True, encoding="utf-8")
    except OSError:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        obj = json.loads(proc.stdout)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _request_for_candidate(repo: str, head_sha: str, *, correlated: bool) -> dict | None:
    """The most recent persisted request bound to this (repo, source HEAD). `correlated`
    selects the run-id state: True returns one whose run id is known (the reuse handle —
    repeated attachment reuses that run rather than dispatching a second one); False returns
    an accepted-but-uncorrelated one, whose dispatch WAS accepted (`state ==
    "dispatched-uncorrelated"`) but whose run id is not yet visible (the reconcile handle —
    `cmd_request` re-correlates it before dispatching a second run, the second dispatch the
    reuse lookup's run-id-truthy filter would otherwise miss). The `correlated=False` arm
    requires that state so a never-accepted `pending-dispatch` record — persisted before
    dispatch and left behind when `gh workflow run` raised — is NOT read as an accepted
    dispatch to reconcile; it falls through to a fresh dispatch instead, and a transient
    dispatch failure does not wedge the candidate at RECONCILE forever."""
    best = None
    for path in sorted(_request_dir().glob("*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict):
            continue
        if rec.get("repo") == repo and rec.get("source_head_sha") == head_sha \
                and bool(rec.get("run_id")) == correlated \
                and (correlated or rec.get("state") == "dispatched-uncorrelated") \
                and (best is None
                     or str(rec.get("created_at", "")) >= str(best.get("created_at", ""))):
            best = rec
    return best


# ── run correlation ────────────────────────────────────────────────────────────
# A request-id marker is a uuid4 hex token; the regex must not match a 32-hex substring of a
# longer hex run (a 40-hex commit SHA), else a SHA in a run title reads as a foreign request id.
_REQUEST_ID_TOKEN_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])")


def _run_request_id_tokens(run: dict) -> set[str]:
    """The set of request-id-shaped (32-hex) tokens a run's displayTitle/name carries."""
    text = f"{run.get('displayTitle') or ''} {run.get('name') or ''}"
    return set(_REQUEST_ID_TOKEN_RE.findall(text.lower()))


def _is_real_int(value) -> bool:
    """True for a genuine int, excluding bool (a bool is an int subclass, so a JSON `true`
    would otherwise pass an `isinstance(x, int)` attempt/id check)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _correlate_run(repo: str, request_id: str, head_sha: str) -> tuple[int | None, int | None, str]:
    """Find the CI run this request's dispatch produced, matching by request identity and
    source HEAD (the earlier probe received an empty dispatch response, so correlation
    never relies on a returned run id). Returns (run_id, run_attempt, run_url); run_id is
    None when no matching run is visible yet (delayed run visibility)."""
    rc, out, err = _gh([
        "run", "list", "--workflow", _CI_WORKFLOW, "--repo", repo,
        "--json", "databaseId,headSha,attempt,url,event,displayTitle,name",
        "--limit", "40",
    ])
    if rc != 0:
        raise _Refuse("transport", f"gh run list failed (rc={rc}): {err.strip()}")
    try:
        runs = json.loads(out) if out.strip() else []
    except ValueError as exc:
        raise _Refuse("transport", f"gh run list returned non-JSON ({exc!r})")
    if not isinstance(runs, list):
        raise _Refuse("transport", "gh run list did not return a JSON array")
    # The base correlation filter is our own dispatch at the bound head: a
    # workflow_dispatch run of ci.yml at head_sha. A push/pull_request-triggered ci.yml
    # run at the same head — e.g. the draft PR's own synchronize run — is never adopted as
    # this request's run: it carried no request_id/expected_head_sha inputs and its worker
    # was not validated against the bound candidate (the earlier probe also showed a
    # dispatch response need not echo a run id, so correlation cannot rely on the title).
    dispatch_runs = [
        r for r in runs
        if isinstance(r, dict) and r.get("headSha") == head_sha
        and r.get("event") == "workflow_dispatch"
    ]
    # Partition by request-id binding so a run naming ANOTHER request id (foreign) is never
    # adopted, even as the sole same-SHA dispatch run: prefer OUR-id matches, else fall back
    # to unbound (no-token) runs only — a foreign-token run is excluded from both sets.
    id_matches = [r for r in dispatch_runs if request_id in _run_request_id_tokens(r)]
    unbound = [r for r in dispatch_runs if not _run_request_id_tokens(r)]
    candidates = id_matches or unbound
    if not candidates:
        # None is ours (not yet visible, or every same-SHA run names another request):
        # non-passing delayed/unreconciled identity, never a foreign adoption.
        return None, None, ""
    if len({r.get("databaseId") for r in candidates}) > 1:
        raise _Refuse(
            "ambiguous-dispatch",
            f"more than one CI run matches request {request_id!r} at head {head_sha[:12]} — "
            "reconcile by request identity before another dispatch")
    run = candidates[0]
    return run.get("databaseId"), run.get("attempt"), (run.get("url") or "")


def _adopt_completed_dispatch_run(repo: str, head_sha: str) -> dict | None:
    """A prior attempt's already-completed ci.yml dispatch run for this same head, adoptable
    by a resume on a fresh runner that holds no local request record (issue #545). Returns
    {request_id, run_id, run_attempt, run_url} for a completed workflow_dispatch run at
    head_sha whose title carries a single request-id token, else None. A green run wins; with
    none, a run that concluded `failure` is adopted too, so the resume's `wait` reports that
    head's known-red verdict at once instead of re-dispatching and re-waiting the same failure.
    `cancelled`/`skipped`/`timed_out` settle no verdict on the tree and are never adopted.

    Adoption reconstructs the runner-local handle the resume lost; it grants no new trust —
    collect-evidence still binds the downloaded shard provenance to this request_id/run_id/
    candidate before any evidence is built. A token is REQUIRED: an unbound (request_id='')
    run's provenance step is skipped in ci.yml, so its artifacts carry no envelope and
    collect-evidence would refuse them. A run whose title names more than one distinct token,
    or whose databaseId is not an integer, is skipped per run; more than one distinct
    remaining run id returns None. Either way the caller falls through to a fresh dispatch
    rather than guess — adoption is a best-effort optimization, not a gate. The match is
    head-scoped by design: CI is head-determined, and collect-evidence re-binds provenance."""
    rc, out, _err = _gh([
        "run", "list", "--workflow", _CI_WORKFLOW, "--repo", repo,
        "--json", "databaseId,headSha,attempt,url,event,displayTitle,name,status,conclusion",
        "--limit", "40",
    ])
    # Adoption is a best-effort optimization: a run-list transport failure or a non-JSON body
    # yields None so the caller falls through to a normal dispatch (correctness-preserving),
    # never aborting the request on the scan. The post-dispatch _correlate_run still surfaces a
    # persistent transport failure, leaving a reconcilable accepted record (issue #424).
    def _skip(reason: str) -> None:
        sys.stderr.write(f"ci-verification-request: adopt-scan skipped: {reason}\n")

    if rc != 0:
        _skip(f"rc={rc}")
        return None
    try:
        runs = json.loads(out) if out.strip() else []
    except ValueError:
        _skip("non-JSON run list")
        return None
    if not isinstance(runs, list):
        _skip("run list is not a JSON array")
        return None
    def _completed(conclusion: str) -> list:
        return [
            r for r in runs
            if isinstance(r, dict) and r.get("headSha") == head_sha
            and r.get("event") == "workflow_dispatch"
            and str(r.get("status") or "").lower() == "completed"
            and str(r.get("conclusion") or "").lower() == conclusion
            and len(_run_request_id_tokens(r)) == 1
            # A non-int databaseId would store a dispatched record with run_id=None: never
            # reusable, never reconcilable — skip the run rather than poison the record.
            and _is_real_int(r.get("databaseId"))
        ]

    adoptable = _completed(_SUCCESS_CONCLUSION) or _completed(_FAILURE_CONCLUSION)
    if not adoptable:
        return None
    if len({r.get("databaseId") for r in adoptable}) > 1:
        return None
    run = adoptable[0]
    (request_id,) = tuple(_run_request_id_tokens(run))
    attempt = run.get("attempt")
    return {
        "request_id": request_id,
        "run_id": run.get("databaseId"),
        "run_attempt": attempt if _is_real_int(attempt) else None,
        "run_url": run.get("url") or "",
    }


# ── pre-request checks (issue #870) ──────────────────────────────────────────────
class _CheckUnavailable(Exception):
    """A check list or check whose outcome is unknown; never a pass."""


class _CheckFailed(Exception):
    """A check that exited non-zero on the candidate and is not inherited from the base."""


_JSON_TYPE_NAMES = {dict: "an object", list: "an array", str: "a string", bool: "a boolean",
                    int: "a number", float: "a number", type(None): "null"}


def _check_label(argv) -> str:
    """The argv as bounded, control-stripped JSON — config text is untrusted in a refusal line."""
    return _sanitize_recap(json.dumps(argv, ensure_ascii=False))[:_RECAP_MAX_CHARS]


def _pre_request_checks(root: str) -> list:
    """prflow_implement.ci_verification.pre_request_checks from .prflow/config.json. An absent
    file, an absent key on the path, or [] yields []; every other unexpected shape raises
    _CheckUnavailable (fail-closed, so the valid-falsy values refuse)."""
    path = _state_config_path(root)
    try:
        with open(path, encoding="utf-8") as fh:
            node = json.load(fh)
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise _CheckUnavailable(f"{path} is unreadable ({exc.__class__.__name__})")
    except ValueError:
        raise _CheckUnavailable(f"{path} is not valid JSON")
    where = "the config"
    for key in ("prflow_implement", "ci_verification", "pre_request_checks"):
        if not isinstance(node, dict):
            raise _CheckUnavailable(f"{where} is {_JSON_TYPE_NAMES.get(type(node), 'unknown')}, "
                                    "not an object")
        if key not in node:
            return []
        node, where = node[key], key
    if not isinstance(node, list):
        raise _CheckUnavailable(
            f"pre_request_checks is {_JSON_TYPE_NAMES.get(type(node), 'unknown')}, not a list")
    for i, entry in enumerate(node):
        if not (isinstance(entry, list) and entry and all(isinstance(t, str) for t in entry)):
            raise _CheckUnavailable(f"pre_request_checks entry {i} is not a non-empty list of "
                                    f"strings: {_check_label(entry)}")
    return node


def _pre_request_check_timeout() -> float:
    """The per-check limit. DEVFLOW_CI_REQUEST_CHECK_TIMEOUT overrides it only while the gh
    stub seam is active (a test context), as _poll_interval does; a non-positive or
    non-numeric value keeps the constant."""
    raw = os.environ.get("DEVFLOW_CI_REQUEST_CHECK_TIMEOUT")
    if raw is None or not os.environ.get("DEVFLOW_CI_REQUEST_GH_STUB"):
        return _PRE_REQUEST_CHECK_TIMEOUT_SECONDS
    try:
        val = float(raw)
    except ValueError:
        return _PRE_REQUEST_CHECK_TIMEOUT_SECONDS
    return val if val > 0 else _PRE_REQUEST_CHECK_TIMEOUT_SECONDS


def _run_check(argv: list, cwd: str, limit: float) -> int:
    """Run one check with no shell, its output on this process's stderr (stdout stays the
    single-line contract). A `.py` first token runs under this interpreter, so a Windows host
    never executes the file directly. Returns the exit code; raises _CheckUnavailable when it
    cannot be launched or outlives `limit` (its process group is killed where supported)."""
    cmd = [sys.executable, *argv] if argv[0].endswith(".py") else list(argv)
    extra = {"start_new_session": True} if os.name == "posix" else {}
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=2, stderr=2,
                                **extra)
    except OSError as exc:
        raise _CheckUnavailable(
            f"{_check_label(argv)} could not be launched ({exc.__class__.__name__})")
    try:
        return proc.wait(timeout=limit)
    except subprocess.TimeoutExpired:
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except OSError:
            proc.kill()
        proc.wait()
        raise _CheckUnavailable(f"{_check_label(argv)} did not exit within the time limit of "
                                f"{limit:g}s and was terminated")


def _merge_base(head_sha: str, base_sha: str, base: str) -> str | None:
    refs = [base_sha] if base_sha else [base, f"origin/{base}"]
    for ref in refs:
        if not ref or ref.startswith("-"):
            continue
        rc, out, _ = _git(["merge-base", head_sha, ref])
        if rc == 0 and re.fullmatch(r"[0-9a-f]{40}", out.strip()):
            return out.strip()
    return None


def _exit_at_base(root: str, argv: list, merge_base: str, limit: float) -> int | str:
    """Re-run a failing check in a temporary detached worktree at `merge_base`. Returns its
    exit code, or a reason string when the base run could not be established."""
    tmp = tempfile.mkdtemp(prefix="prflow-pre-request-")
    try:
        rc, _, err = _git(["-C", root, "worktree", "add", "--detach", "--quiet", tmp, merge_base])
        if rc != 0:
            return f"worktree at {merge_base} not created ({err.strip()[:200]})"
        try:
            return _run_check(argv, tmp, limit)
        except _CheckUnavailable as exc:
            return str(exc)
    finally:
        rc, _, _ = _git(["-C", root, "worktree", "remove", "--force", tmp])
        shutil.rmtree(tmp, ignore_errors=True)
        if rc != 0:
            _git(["-C", root, "worktree", "prune"])


def _run_pre_request_checks(args, root: str) -> list:
    """Run every config-listed check in order from `root`; the first non-zero exit stops the
    sequence. A failure the candidate inherited from its base (the same exit at the merge-base
    of the head and `--base-sha`, else `--base`) is reported and skipped. Returns the inherited
    checks; raises _CheckFailed / _CheckUnavailable otherwise."""
    checks = _pre_request_checks(root)
    limit = _pre_request_check_timeout()
    inherited = []
    for argv in checks:
        code = _run_check(argv, root, limit)
        if code == 0:
            continue
        failed = f"{_check_label(argv)} exited {code}"
        merge_base = _merge_base(args.head_sha, args.base_sha, args.base)
        if merge_base is None:
            sys.stderr.write("pre-request-check: merge-base with the base is unresolvable\n")
            raise _CheckFailed(failed)
        at_base = _exit_at_base(root, argv, merge_base, limit)
        if at_base != code:
            sys.stderr.write(f"pre-request-check: at base {merge_base}: {at_base}\n")
            raise _CheckFailed(failed)
        sys.stderr.write(f"pre-request-check-inherited: {failed} at base {merge_base}\n")
        inherited.append({"argv": argv, "exit": code, "base_sha": merge_base})
    return inherited


# ── subcommand: request ──────────────────────────────────────────────────────────
def cmd_request(args) -> int:
    if args.workflow != _CI_WORKFLOW:
        raise _Refuse("foreign-workflow",
                      f"request workflow {args.workflow!r} is not the declared contract "
                      f"{_CI_WORKFLOW!r}")
    if not re.fullmatch(r"[0-9a-f]{40}", args.head_sha):
        raise _Refuse("bad-head", "head-sha must be exactly 40 lowercase hex characters")

    if not args.force_dispatch:
        reuse = _request_for_candidate(args.repo, args.head_sha, correlated=True)
        if reuse is not None:
            print(f"REUSE {reuse['request_id']} run={reuse.get('run_id')} "
                  f"url={reuse.get('run_url', '')}")
            return 0
        # Reconcile an accepted-but-uncorrelated dispatch before dispatching a second run,
        # else a request whose run was not yet visible double-dispatches: re-correlate it,
        # REUSE when its run is now visible, else stay pending (RECONCILE) — never dispatch.
        pending = _request_for_candidate(args.repo, args.head_sha, correlated=False)
        if pending is not None:
            run_id, run_attempt, run_url = _correlate_run(
                args.repo, pending["request_id"], args.head_sha)
            if run_id:
                pending.update(run_id=run_id, run_attempt=run_attempt, run_url=run_url,
                               state="dispatched")
                _store_request(pending)
                print(f"REUSE {pending['request_id']} run={run_id} url={run_url}")
            else:
                print(f"RECONCILE {pending['request_id']} run=none "
                      "state=dispatched-uncorrelated reason=run-not-yet-visible")
            return 0
        # No local record: adopt a prior attempt's already-completed same-head dispatch run
        # (issue #545). A resume on a fresh runner holds no request record, so without this
        # it re-dispatches and re-waits a CI cycle this head already passed — or failed.
        adopt = _adopt_completed_dispatch_run(args.repo, args.head_sha)
        if adopt is not None:
            record = {
                "schema_version": SCHEMA_VERSION,
                "repo": args.repo,
                "workflow": args.workflow,
                "request_id": adopt["request_id"],
                "source_head_sha": args.head_sha,
                "base": args.base,
                "base_sha": args.base_sha,
                "tested_checkout": _checkout_fingerprint(),
                "ref": args.ref or args.base,
                "run_id": adopt["run_id"],
                "run_attempt": adopt["run_attempt"],
                "run_url": adopt["run_url"],
                "state": "dispatched",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            _store_request(record)
            print(f"ADOPTED {record['request_id']} run={record['run_id']} "
                  f"url={record['run_url']}")
            return 0

    # Only the dispatch path runs the checks: a reused/reconciled/adopted head dispatches nothing.
    try:
        inherited = _run_pre_request_checks(args, _repo_root())
    except _CheckFailed as exc:
        raise _Refuse("pre-request-check-failed", str(exc))
    except _CheckUnavailable as exc:
        raise _Refuse("pre-request-check-unavailable", str(exc))

    request_id = uuid.uuid4().hex
    record = {
        "schema_version": SCHEMA_VERSION,
        "repo": args.repo,
        "workflow": args.workflow,
        "request_id": request_id,
        "source_head_sha": args.head_sha,
        "base": args.base,
        "base_sha": args.base_sha,
        "tested_checkout": _checkout_fingerprint(),
        "ref": args.ref or args.base,
        "run_id": None,
        "run_attempt": None,
        "run_url": "",
        "state": "pending-dispatch",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if inherited:
        record["pre_request_checks_inherited"] = inherited
    _store_request(record)  # persist BEFORE dispatch — a lost response is reconcilable

    rc, _out, err = _gh([
        "workflow", "run", _CI_WORKFLOW, "--repo", args.repo, "--ref", record["ref"],
        "-f", f"request_id={request_id}", "-f", f"expected_head_sha={args.head_sha}",
    ])
    if rc != 0:
        # Auth failures are a distinct, non-retryable terminal.
        if _looks_like_auth_failure(err):
            raise _Refuse("auth", f"CI dispatch was not authorized: {err.strip()}")
        raise _Refuse("dispatch-failed", f"gh workflow run failed (rc={rc}): {err.strip()}")

    # Persist acceptance as dispatched-uncorrelated (no run id) BEFORE correlating: moving this
    # write below _correlate_run would let a run-list failure leave the record at pending-dispatch,
    # which the reconcile selector skips, so a retry double-dispatches.
    record["state"] = "dispatched-uncorrelated"
    _store_request(record)

    # Correlate to a run id (the response may be empty).
    run_id, run_attempt, run_url = _correlate_run(args.repo, request_id, args.head_sha)
    record["run_id"] = run_id
    record["run_attempt"] = run_attempt
    record["run_url"] = run_url
    record["state"] = "dispatched" if run_id else "dispatched-uncorrelated"
    _store_request(record)
    print(f"REQUESTED {request_id} run={run_id} url={run_url} state={record['state']}")
    return 0


def _looks_like_auth_failure(text: str) -> bool:
    # Credential signals are tested BEFORE the rate-limit exclusion: a message carrying
    # both ("403: Bad credentials. API rate limit exceeded") is a permanent credential
    # failure, and excluding it first would retry it as transport and lose its cause.
    low = (text or "").lower()
    if any(sig in low for sig in ("bad credentials", "http 401", "authentication failed",
                                  "resource not accessible")):
        return True
    if "rate limit" in low or "secondary rate" in low or "abuse detection" in low:
        return False
    return "http 403" in low


def _sanitize_recap(line: str) -> str:
    """Strip ANSI escapes and control/format characters (Unicode category "C…") from a log
    line, keeping the tab, so an injected recap identifier prints as inert data. Mirrors
    page-job-log.py's _sanitize (reimplemented — that script's hyphenated filename is not
    importable as a module)."""
    line = _RECAP_ANSI_RE.sub("", line)
    return "".join(
        ch for ch in line if ch == "\t" or not unicodedata.category(ch).startswith("C"))


def _extract_recap_ids(log_text: str) -> list[str]:
    """The `  - <identifier>` bullets after a `Failure recap:` header in a job log, using
    shard-tally.py's exact rule (a 4-space continuation is ignored; any other non-bullet
    line ends the recap section). The job-log line prefix is stripped first, so
    the exact-match rule fires against a real job log and not only shard-tally.py's
    prefix-free summary artifact. Sanitized, length-bounded, and capped in count."""
    ids: list[str] = []
    in_recap = False
    for raw in log_text.splitlines():
        line = _GH_LOG_PREFIX_RE.sub("", _sanitize_recap(raw), count=1)
        if line.strip() == _RECAP_HEADER:
            in_recap = True
            continue
        if in_recap:
            m = _RECAP_BULLET.match(line)
            if m:
                ids.append(m.group(1)[:_RECAP_MAX_CHARS])
                if len(ids) >= _RECAP_MAX_IDS:
                    break
            elif line.startswith("    "):
                continue  # a run-module continuation (expected/actual); ignore
            else:
                in_recap = False
    return ids


# Job conclusions that name a job that actually ran and failed. A fail-fast sibling is
# `cancelled`/`neutral` and must not print as `failed-job:` — that line is what the next
# request is told to apply.
_JOB_FAILED_CONCLUSIONS = frozenset({"failure", "timed_out", "startup_failure"})


def _print_failure_recap(record: dict) -> None:
    """Print the `failed-job:`/`recap:` lines for a failed run, after the FAILED line and
    before the caller returns 7 (issue #603). Reads the run's jobs, prints one `failed-job:`
    per job whose conclusion is in `_JOB_FAILED_CONCLUSIONS` (in job order), then one `recap:`
    per Failure-recap bullet found in those jobs' logs (in job order). A job list that cannot
    be read, an empty failed set, or a job log fetch that fails, prints
    `recap-status: unestablished — <reason>` (a later job's fetch failure still keeps the recap
    ids already collected from earlier jobs). The diagnostic prefix is not `recap:`, so an
    agent applying every `recap:` identifier cannot treat the status line as a suite id. This
    function only prints and returns None, so the caller's exit 7 is never affected."""
    try:
        view = _run_view(record, "jobs")
    except _Refuse as exc:
        print(f"recap-status: unestablished — {exc.token}")
        return
    jobs = view.get("jobs")
    if not isinstance(jobs, list):
        print("recap-status: unestablished — bad-jobs")
        return
    failed = [j for j in jobs
              if isinstance(j, dict) and isinstance(j.get("conclusion"), str)
              and j["conclusion"] in _JOB_FAILED_CONCLUSIONS]
    if not failed:
        print("recap-status: unestablished — empty-failed-set")
        return
    for job in failed:
        name = job["name"] if isinstance(job.get("name"), str) else "<unnamed>"
        print(f"failed-job: {_sanitize_recap(name)[:_RECAP_MAX_CHARS]}")
    recap_ids: list[str] = []
    for job in failed:
        # The jobs-logs endpoint serves a finished job's log while other jobs still run;
        # the run-view log form refuses until the whole run completes.
        job_id = job.get("databaseId")
        rc, out, _err = _gh(["api", f"repos/{record['repo']}/actions/jobs/{job_id}/logs"])
        if rc != 0:
            print("recap-status: unestablished — log-fetch-failed")
            break
        recap_ids.extend(_extract_recap_ids(out))
        if len(recap_ids) >= _RECAP_MAX_IDS:
            recap_ids = recap_ids[:_RECAP_MAX_IDS]
            break
    for rid in recap_ids:
        print(f"recap: {rid}")


# ── subcommand: wait ─────────────────────────────────────────────────────────────
def cmd_wait(args) -> int:
    record = _load_request(args.request_id)
    repo = record["repo"]
    head_sha = record["source_head_sha"]

    if not record.get("run_id"):
        # Delayed run visibility: re-correlate by request identity before giving up.
        run_id, run_attempt, run_url = _correlate_run(repo, record["request_id"], head_sha)
        if run_id:
            record.update(run_id=run_id, run_attempt=run_attempt, run_url=run_url,
                          state="dispatched")
            _store_request(record)
        else:
            print(f"PENDING {record['request_id']} run=none "
                  "reason=run-not-yet-visible")
            return _EXIT_PENDING

    deadline = time.monotonic() + max(1, args.deadline_seconds)
    transport_failures = 0
    while True:
        rc, out, err = _gh([
            "run", "view", str(record["run_id"]), "--repo", repo,
            "--json", "status,conclusion,url,attempt",
        ])
        if rc != 0:
            # An authorization failure is a non-retryable terminal — report it at once
            # rather than burning the transport-retry budget or the deadline on it.
            if _looks_like_auth_failure(err):
                print(f"AUTH {record['request_id']} run={record['run_id']} "
                      f"url={record.get('run_url','')} reason=authorization-failed")
                return 4
            transport_failures += 1
            if transport_failures > _MAX_TRANSPORT_RETRIES:
                print(f"TRANSPORT {record['request_id']} run={record['run_id']} "
                      f"retries={transport_failures} detail={err.strip()[:200]}")
                return 5
            _sleep_until(deadline)
            if time.monotonic() >= deadline:
                return _emit_pending(record)
            continue
        transport_failures = 0
        try:
            view = json.loads(out) if out.strip() else {}
        except ValueError:
            view = {}
        status = (view.get("status") or "").lower()
        conclusion = (view.get("conclusion") or "").lower()
        run_url = view.get("url") or record.get("run_url", "")
        # Only a completed run is terminal. A conclusion seen alongside a not-completed
        # status (a transient/edge API state) is NOT honored — it falls through to the
        # deadline/sleep logic, so a `success` conclusion on a still-running status can
        # never print PASSED. An unrecognised status is likewise treated as pending.
        if status == "completed":
            record["run_url"] = run_url
            if conclusion == _SUCCESS_CONCLUSION:
                # Persist the attempt GitHub reports for the passing run so a later
                # collect-evidence binds to the retry's attempt, not the stale attempt from
                # the original correlation — else a Spot retry that bumped the attempt after
                # correlation is refused `attempt-changed` though the run itself passed
                # (issue #543). A view with no integer attempt leaves the stored value.
                view_attempt = view.get("attempt")
                if _is_real_int(view_attempt):
                    record["run_attempt"] = view_attempt
            _store_request(record)
            if conclusion == _SUCCESS_CONCLUSION:
                print(f"PASSED {record['request_id']} run={record['run_id']} url={run_url}")
                return _EXIT_PASSED
            if conclusion in ("cancelled", "canceled"):
                print(f"CANCELLED {record['request_id']} run={record['run_id']} url={run_url}")
                return 6
            if conclusion == "skipped":
                print(f"SUPERSEDED {record['request_id']} run={record['run_id']} url={run_url} "
                      "reason=run-skipped")
                return 6
            print(f"FAILED {record['request_id']} run={record['run_id']} url={run_url} "
                  f"conclusion={conclusion or 'unknown'}")
            _print_failure_recap(record)
            return 7
        if time.monotonic() >= deadline:
            return _emit_pending(record)
        _sleep_until(deadline)


def _poll_interval() -> float:
    """The poll interval. Overridable via DEVFLOW_CI_REQUEST_POLL_INTERVAL ONLY when the
    gh stub seam is also active (a test context) — so a production run never shortens the
    transport-retry backoff, which shares this interval. A non-numeric or negative value
    falls back to the default; a 0 lets a stubbed test exhaust the retry budget without
    real waiting."""
    raw = os.environ.get("DEVFLOW_CI_REQUEST_POLL_INTERVAL")
    if raw is None or not os.environ.get("DEVFLOW_CI_REQUEST_GH_STUB"):
        return _POLL_INTERVAL_SECONDS
    try:
        val = float(raw)
    except ValueError:
        return _POLL_INTERVAL_SECONDS
    return val if val >= 0 else _POLL_INTERVAL_SECONDS


def _sleep_until(deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return
    time.sleep(min(_poll_interval(), remaining))


def _emit_pending(record: dict) -> int:
    record["state"] = "pending"
    _store_request(record)
    print(f"PENDING {record['request_id']} run={record.get('run_id')} "
          f"url={record.get('run_url','')} reason=deadline-reached")
    return _EXIT_PENDING


# ── subcommand: collect-evidence ─────────────────────────────────────────────────
def _read_tally_artifacts(artifact_dir: Path) -> dict:
    """Read each shard's downloaded tally directory into a per-shard entry for the evidence
    record. Each shard's artifact is the directory shard-tally.py writes, whose `summary`
    file carries TAB-separated `key<TAB>value` lines (`shard`, `passed`, `failed`,
    `skipped`, `rc`) and — on the selected cloud-CI path — a `provenance.json` envelope
    beside it (issue #419). Returns `{shard: {passed, failed, skipped, exit_status,
    summary_text, provenance}}`, where `provenance` is the structurally-validated envelope
    or None when no sidecar is present (the binding REQUIREMENT is applied by
    cmd_collect_evidence, so this function stays usable for the summary-only shapes its
    direct tests drive). The summary is parsed through the one owned contract
    (ci_shard_provenance.parse_summary_tally); the text files are read as data — never
    executed; the reads are bounded and a path escaping the artifact directory is refused.
    A duplicate shard summary is refused (two directories claiming the same shard name)."""
    shards: dict = {}
    # rglob swallows a directory-level OSError, so a typo'd, missing, or unreadable path
    # would otherwise report `absent-shards` — sending the caller to re-run the download
    # instead of fixing the path it named.
    if not artifact_dir.is_dir():
        raise _Refuse("bad-artifact",
                      f"{artifact_dir} is not a readable directory; --artifact-dir must "
                      "name the directory the shard-tally artifacts were downloaded into")
    base = artifact_dir.resolve()
    for path in sorted(artifact_dir.rglob("summary")):
        rp = path.resolve()
        if base not in rp.parents and rp != base:
            raise _Refuse("path-traversal", f"artifact {path} escapes {artifact_dir}")
        try:
            # Decode exact bytes without CRLF translation: retained bytes carry the digest.
            text = csp.read_regular_file(path, _MAX_ARTIFACT_BYTES).decode("utf-8")
        except csp.ProvenanceError as exc:
            if exc.reason == "too-large":
                raise _Refuse("artifact-too-large", f"{path}: {exc.detail}")
            raise _Refuse("bad-artifact", f"{path}: {exc.detail}")
        except (OSError, UnicodeDecodeError) as exc:
            raise _Refuse("bad-artifact", f"{path} unreadable ({exc!r})")
        try:
            parsed = csp.parse_summary_tally(text)
        except csp.ProvenanceError as exc:
            # A malformed summary is refused, never coerced to a zero (the bad-tally class).
            raise _Refuse("bad-tally", f"{path}: {exc.detail}")
        name = parsed["shard"]
        if name in shards:
            raise _Refuse("duplicate-shard", f"two tally summaries claim shard {name!r}")
        # The sibling envelope: read from the summary's own directory, never a second rglob,
        # so an unpaired provenance.json cannot slip in. Absent → None (summary-only shape);
        # present → validated and bounded/traversal-guarded exactly like the summary.
        prov_path = path.parent / csp.PROVENANCE_FILENAME
        provenance = None
        if prov_path.exists():
            rpp = prov_path.resolve()
            if base not in rpp.parents and rpp != base:
                raise _Refuse("path-traversal", f"artifact {prov_path} escapes {artifact_dir}")
            try:
                provenance = csp.read_envelope_file(prov_path)
            except csp.ProvenanceError as exc:
                if exc.reason == "too-large":
                    raise _Refuse("artifact-too-large", f"{prov_path}: {exc.detail}")
                raise _Refuse("bad-provenance", f"{prov_path}: {exc.detail}")
        shards[name] = {
            "passed": parsed["passed"],
            "failed": parsed["failed"],
            "skipped": parsed["skipped"],
            "exit_status": parsed["exit_status"],
            "summary_text": text,
            "provenance": provenance,
        }
    return shards


def cmd_collect_evidence(args) -> int:
    record = _load_request(args.request_id)
    observed = {
        "repo": record.get("repo"),
        "workflow": record.get("workflow"),
        "request_id": record.get("request_id"),
        "run_id": record.get("run_id"),
        "run_attempt": record.get("run_attempt"),
        "source_head_sha": record.get("source_head_sha"),
    }
    if not record.get("run_id"):
        _emit_observed("REFUSED", "no-run", observed, "the request has no correlated run yet")
        raise _Refuse("no-run", f"request {args.request_id!r} has no correlated run yet")
    # One remote read serves the run-completion gate, the worker-checkout validation, and
    # the required-check conclusions (status/conclusion/headSha/jobs in a single gh run
    # view), halving the round-trips.
    # Once the record is loaded every refusal emits the observed identities (AC4), so one
    # raised before the run read must not return through the bare raise path.
    try:
        view = _run_view(record, "status,conclusion,headSha,jobs,attempt")
    except _Refuse as refuse:
        _emit_observed("REFUSED", refuse.token, observed, refuse.detail)
        raise
    # Run-completion gate: build evidence only from a run that has completed successfully.
    # collect-evidence must not trust the caller to have gated on `wait` — an in-progress
    # or non-success run must never yield a cloud_ci_evidence record.
    status = str(view.get("status") or "").lower()
    conclusion = str(view.get("conclusion") or "").lower()
    if status != "completed" or conclusion != _SUCCESS_CONCLUSION:
        _emit_observed("REFUSED", "run-not-successful", observed,
                       f"run status={status or 'unknown'} conclusion={conclusion or 'unknown'}")
        raise _Refuse("run-not-successful",
                      f"the CI run has not completed successfully (status={status or 'unknown'}, "
                      f"conclusion={conclusion or 'unknown'})")
    # Worker checkout validation: the run must have tested the bound candidate head. Fail
    # CLOSED on an absent/non-string headSha — an unverifiable worker checkout is refused,
    # not passed through (the guard must not be inert exactly where its comparand is missing).
    tested = view.get("headSha")
    if not isinstance(tested, str) or not tested:
        _emit_observed("REFUSED", "worker-checkout-unverifiable", observed,
                       "gh run view returned no headSha; cannot confirm the worker's tree")
        raise _Refuse("worker-checkout-unverifiable",
                      "the CI run reported no headSha, so its checkout cannot be confirmed "
                      "against the bound candidate")
    if tested != record["source_head_sha"]:
        _emit_observed("REFUSED", "worker-checkout-mismatch", observed,
                       f"worker tested {tested[:12]} not the bound candidate "
                       f"{record['source_head_sha'][:12]}")
        raise _Refuse("worker-checkout-mismatch",
                      "the CI worker did not check out the bound candidate head")

    # The operand is the production channel: the cloud matcher denies a `VAR=value`
    # prefix, so an env-only input has no invocable form on the tier this mode targets.
    artifact_dir = args.artifact_dir or os.environ.get("DEVFLOW_CI_REQUEST_ARTIFACT_DIR")
    if not artifact_dir:
        _emit_observed("REFUSED", "no-artifacts", observed, "no artifact directory supplied")
        raise _Refuse("no-artifacts",
                      "pass --artifact-dir <dir> (or set DEVFLOW_CI_REQUEST_ARTIFACT_DIR); "
                      "shard-tally artifacts must be downloaded before collect-evidence")
    try:
        shards = _read_tally_artifacts(Path(artifact_dir))
    except _Refuse as refuse:
        _emit_observed("REFUSED", refuse.token, observed, refuse.detail)
        raise
    if not shards:
        _emit_observed("REFUSED", "absent-shards", observed, "no shard-tally artifacts found")
        raise _Refuse("absent-shards", "no shard-tally artifacts found")

    try:
        required = _required_checks_from_view(view)
    except _Refuse as refuse:
        _emit_observed("REFUSED", refuse.token, observed, refuse.detail)
        raise

    # Never default an uncorrelated attempt to 1: the record would name attempt 1 for a
    # rerun the correlation never identified, which is exactly the foreign-attempt
    # evidence the completion contract refuses.
    attempt = record.get("run_attempt")
    if not _is_real_int(attempt):
        _emit_observed("REFUSED", "no-attempt", observed,
                       f"run_attempt is {attempt!r}, not an integer")
        raise _Refuse("no-attempt",
                      f"request {args.request_id!r} has no correlated run attempt; "
                      "re-correlate the request before collecting evidence")

    # Bind the evidence to the FRESHLY OBSERVED attempt, not the persisted one: a rerun that
    # bumped the attempt since correlation means these artifacts came from a different attempt,
    # so a mismatch must not pass. Fail CLOSED on an absent/non-integer observed attempt.
    observed_attempt = view.get("attempt")
    if not _is_real_int(observed_attempt):
        _emit_observed("REFUSED", "no-attempt", observed,
                       f"gh run view returned no integer run attempt ({observed_attempt!r})")
        raise _Refuse("no-attempt",
                      "the CI run reported no current attempt, so the bound attempt cannot "
                      "be reconciled against the run that produced these artifacts")
    if observed_attempt != attempt:
        _emit_observed("REFUSED", "attempt-changed", observed,
                       f"run attempt changed to {observed_attempt} since correlation "
                       f"(bound {attempt}); re-correlate before collecting evidence")
        raise _Refuse("attempt-changed",
                      f"the run's current attempt {observed_attempt} differs from the bound "
                      f"attempt {attempt} — a rerun invalidated the earlier evidence")

    # Per-shard provenance binding (issue #419): require one valid envelope per summary,
    # verify its digest over the exact summary bytes, and match every producer identity to the
    # bound request and observed attempt — never filling a missing identity from the request.
    evidence_shards: dict = {}
    current_attempt_shards = 0
    for name in sorted(shards.keys()):
        entry = shards[name]
        prov = entry["provenance"]
        if prov is None:
            _emit_observed("REFUSED", "no-provenance", observed,
                           f"shard {name!r} summary carries no provenance.json envelope")
            raise _Refuse("no-provenance",
                          f"shard {name!r} has no provenance.json beside its summary; an "
                          "unbound tally cannot be collected as cloud completion evidence")
        try:
            csp.verify_summary_binding(prov, entry["summary_text"].encode("utf-8"))
        except csp.ProvenanceError as exc:
            _emit_observed("REFUSED", "provenance-mismatch", observed, f"shard {name!r}: {exc.detail}")
            raise _Refuse("provenance-mismatch", f"shard {name!r}: {exc.detail}")
        binding = (
            ("repo", prov["repo"], record["repo"]),
            ("workflow", prov["workflow"], record["workflow"]),
            ("request_id", prov["request_id"], record["request_id"]),
            ("candidate_sha", prov["candidate_sha"], record["source_head_sha"]),
            ("run_id", prov["run_id"], record["run_id"]),
            ("shard", prov["shard"], name),
        )
        for field, got, want in binding:
            if got != want:
                detail = (f"shard {name!r} provenance {field}={got!r} does not match the bound "
                          f"request {want!r}")
                _emit_observed("REFUSED", "provenance-mismatch", observed, detail)
                raise _Refuse("provenance-mismatch", detail)
        # A Spot retry reruns only the interrupted shard, so the survivors keep an envelope
        # stamped with their earlier attempt. Classify each envelope's attempt against the
        # run's current attempt through the shared predicate (bound == observed here, checked
        # above), accepting a current or strictly-earlier leftover and refusing one ahead; the
        # whole-tree check below still refuses a tree with no current-attempt envelope (#543).
        prov_attempt = prov["run_attempt"]
        attempt_class = csp.classify_shard_attempt(prov_attempt, attempt)
        if attempt_class == csp.ATTEMPT_CURRENT:
            current_attempt_shards += 1
        elif attempt_class != csp.ATTEMPT_LEFTOVER:
            detail = (f"shard {name!r} provenance run_attempt={prov_attempt} is neither the "
                      f"current attempt {attempt} nor an earlier leftover (a foreign or "
                      "ahead-of-run attempt)")
            _emit_observed("REFUSED", "provenance-mismatch", observed, detail)
            raise _Refuse("provenance-mismatch", detail)
        evidence_shards[name] = csp.build_shard_entry(
            {k: entry[k] for k in ("passed", "failed", "skipped", "exit_status")},
            entry["summary_text"], prov)

    # A tree of only leftover envelopes proves nothing about the current attempt: require at
    # least one shard stamped with the bound/observed attempt, else refuse (issue #543).
    if current_attempt_shards == 0:
        detail = (f"no shard envelope names the current attempt {observed_attempt}; a tree of "
                  "only leftover envelopes is not evidence the current run produced them")
        _emit_observed("REFUSED", "provenance-mismatch", observed, detail)
        raise _Refuse("provenance-mismatch", detail)

    evidence = {
        "kind": "cloud_ci_evidence",
        "schema_version": CLOUD_CI_EVIDENCE_SCHEMA_VERSION,
        "repo": record["repo"],
        "workflow": record["workflow"],
        "request_id": record["request_id"],
        "run_id": record["run_id"],
        "run_attempt": observed_attempt,
        "run_url": record.get("run_url", ""),
        "head_sha": record["source_head_sha"],
        "expected_shard_population": sorted(shards.keys()),
        "shards": evidence_shards,
        "required_checks": required,
    }
    out = json.dumps(evidence, sort_keys=True, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
        print(f"EVIDENCE {record['request_id']} written={args.output} "
              f"shards={len(shards)} checks={len(required)}")
    else:
        print(out)
    return 0


def _run_view(record: dict, fields: str) -> dict:
    """Read `gh run view <id> --json <fields>` once and return the parsed object. Raises
    a transport `_Refuse` on a gh failure or non-JSON output; an empty/non-object body
    yields an empty dict (the caller's field lookups then miss and route themselves)."""
    rc, out, err = _gh(["run", "view", str(record["run_id"]), "--repo", record["repo"],
                        "--json", fields])
    if rc != 0:
        raise _Refuse("transport", f"gh run view failed (rc={rc}): {err.strip()}")
    try:
        view = json.loads(out) if out.strip() else {}
    except ValueError as exc:
        raise _Refuse("transport", f"gh run view returned non-JSON ({exc!r})")
    return view if isinstance(view, dict) else {}


def _required_checks_from_view(view: dict) -> list:
    """Every job's name/conclusion pair from a `gh run view --json jobs` object — ALL
    jobs, not a filtered subset. The required-check coverage filter is applied downstream
    by the completion validator, not here; this only surfaces what the run reported."""
    jobs = view.get("jobs")
    if not isinstance(jobs, list):
        raise _Refuse("bad-jobs", "gh run view did not return a jobs array")
    checks = []
    for job in jobs:
        if isinstance(job, dict) and isinstance(job.get("name"), str) \
                and isinstance(job.get("conclusion"), str):
            checks.append({"name": job["name"], "conclusion": job["conclusion"]})
    return checks


def _emit_observed(prefix: str, token: str, observed: dict, detail: str) -> None:
    """Emit the observed identities to stderr on a refusal, so a refusal still surfaces
    what was seen (issue #403 AC4). The successful path surfaces the same identities
    inside the emitted evidence record rather than through this helper."""
    sys.stderr.write(
        f"ci-verification-request: {prefix} {token}: {detail}; observed="
        + json.dumps(observed, sort_keys=True) + "\n")


# ── subcommand: check-deployment ─────────────────────────────────────────────────
def cmd_check_deployment(args) -> int:
    """Refuse CI mode with an actionable explanation when the deployment is incomplete.
    First unmet condition wins, in deploy order: config off -> ci.yml inputs absent ->
    grant absent. A fully-deployed, enabled repo prints PROCEED."""
    root = Path(_repo_root())
    enabled = _config_ci_verification_enabled(root)
    if not enabled:
        print("REFUSED not-selected: prflow_implement.ci_verification.enabled is not true "
              "in .prflow/config.json — CI verification mode is off; no CI "
              "verification was performed. Follow the repository verification policy.")
        return 2
    ci_yml = root / ".github" / "workflows" / "ci.yml"
    try:
        ci_text = ci_yml.read_text(encoding="utf-8")
    except OSError:
        print("REFUSED incomplete-deployment: .github/workflows/ci.yml is absent; the "
              "deployed workflow does not support CI-mode dispatch inputs")
        return 2
    if "request_id" not in ci_text or "expected_head_sha" not in ci_text:
        print("REFUSED incomplete-deployment: the deployed ci.yml lacks the "
              "workflow_dispatch request_id/expected_head_sha inputs — upgrade the "
              "workflow before activating CI mode")
        return 2
    # Scope the probe to the IMPLEMENT profile's own token list: a whole-file substring
    # scan would pass on a grant that sits only in another profile, which the cloud
    # implement matcher never consults. An unreadable/unparseable manifest grants nothing.
    profiles = root / "lib" / "capability-profiles.json"
    try:
        manifest = json.loads(profiles.read_text(encoding="utf-8"))
        tokens = manifest["profiles"]["implement"]
        tokens = tokens if isinstance(tokens, list) else []
    except (OSError, ValueError, KeyError, TypeError):
        tokens = []

    def _granted(needle: str) -> bool:
        return any(isinstance(t, str) and needle in t for t in tokens)

    if not _granted("ci-verification-request.py"):
        print("REFUSED incomplete-deployment: the implement capability profile does not "
              "grant ci-verification-request.py — regenerate grants before activating "
              "CI mode")
        return 2
    # PROCEED without this grant would promise a lifecycle that cannot finish.
    if not _granted("gh run download"):
        print("REFUSED incomplete-deployment: the implement capability profile does not "
              "grant `gh run download`, so the shard-tally artifacts collect-evidence "
              "needs cannot be fetched — regenerate grants before activating CI mode")
        return 2
    # The manifest is the SOURCE of the allowlist; the baked workflow literal is what the
    # matcher reads. A manifest edit that was never regenerated grants nothing at runtime,
    # so probing the manifest alone would pass on a grant no run can actually use.
    baked = root / ".github" / "workflows" / "devflow-implement.yml"
    try:
        baked_text = baked.read_text(encoding="utf-8")
    except OSError:
        baked_text = ""
    for token in ("ci-verification-request.py", "gh run download"):
        if token not in baked_text:
            print("REFUSED incomplete-deployment: devflow-implement.yml's generated "
                  f"allowed-tools literal does not carry `{token}` — regenerate with "
                  "tools/generators/generate-capability-profiles.py before activating "
                  "CI mode")
            return 2
    print("PROCEED ci-verification mode is deployed and enabled")
    return 0


def _config_ci_verification_enabled(root: Path) -> bool:
    """Read prflow_implement.ci_verification.enabled from .prflow/config.json, treating a
    missing key or any non-true value (including a valid-falsy false/0/'') as OFF — the
    fail-closed default so an absent key never activates the mode."""
    try:
        with open(_state_config_path(str(root)), encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return False
    node = cfg
    for key in ("prflow_implement", "ci_verification", "enabled"):
        if not isinstance(node, dict) or key not in node:
            return False
        node = node[key]
    return node is True


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Cloud-CI verification request/wait/evidence adapter")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("request", help="persist a request and dispatch CI for a candidate")
    r.add_argument("--repo", required=True)
    r.add_argument("--workflow", default=_CI_WORKFLOW)
    r.add_argument("--head-sha", required=True)
    r.add_argument("--base", required=True)
    r.add_argument("--base-sha", default="")
    r.add_argument("--ref", default="",
                   help="git ref the dispatched run checks out; pass the FEATURE BRANCH "
                        "carrying the pushed candidate. Defaults to --base, which only "
                        "carries the candidate when it is already on the base branch — "
                        "otherwise the worker-checkout binding fails closed.")
    r.add_argument("--force-dispatch", action="store_true",
                   help="dispatch a fresh run even if an existing request for this "
                        "candidate could be reused")
    r.set_defaults(func=cmd_request)

    w = sub.add_parser("wait", help="bounded foreground poll of a dispatched run")
    w.add_argument("--request-id", required=True)
    w.add_argument("--deadline-seconds", type=int, default=_DEFAULT_DEADLINE_SECONDS)
    w.set_defaults(func=cmd_wait)

    c = sub.add_parser("collect-evidence", help="build the cloud_ci_evidence record")
    c.add_argument("--request-id", required=True)
    c.add_argument("--artifact-dir", default="",
                   help="directory the run's downloaded shard-tally artifacts were "
                        "placed in (`gh run download --dir <dir>`). A non-empty value "
                        "overrides DEVFLOW_CI_REQUEST_ARTIFACT_DIR, which remains the "
                        "offline test seam; one of the two must name a readable "
                        "directory. Use a per-run directory — `gh run download` merges "
                        "into an existing one.")
    c.add_argument("--output", default="")
    c.set_defaults(func=cmd_collect_evidence)

    d = sub.add_parser("check-deployment", help="refuse CI mode when deployment is incomplete")
    d.set_defaults(func=cmd_check_deployment)
    return p


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8 on the entry path (issue #1762). Never call at
    import — that would mutate the streams of any process importing this module for
    tests. Tolerates a stream with no usable `reconfigure`."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_streams()
    args = _build_parser().parse_args(argv)
    try:
        return args.func(args)
    except _Refuse as refuse:
        sys.stderr.write(f"ci-verification-request: REFUSED {refuse.token}: {refuse.detail}\n")
        print(f"REFUSED {refuse.token}: {refuse.detail}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
