# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Per-shard cloud-CI provenance envelope — the one owned producer/consumer contract (issue #419).

A cloud-CI verification dispatch offloads the suite to `.github/workflows/ci.yml`, whose
shard jobs each upload a `summary` tally. Nothing in that summary proved which run,
attempt, request, and candidate produced it, so an old or foreign tally directory could
supply passing counts for a different verification request (issue #419's bounded
reproduction). This module is the single contract that binds each summary to its producer:

  * the CI worker (`lib/test/shard-tally.py write-provenance`) builds a versioned
    `provenance.json` envelope beside the exact `summary` bytes it uploads, carrying the
    producing run's identity and the SHA-256 digest of those bytes;
  * the collector (`scripts/ci-verification-request.py`) requires and validates one
    envelope per summary, binding it to the request and the freshly-observed remote
    attempt before it constructs cloud completion evidence;
  * the shared offline validator (`scripts/check-completion-evidence.py`) recomputes the
    digest and re-parses the retained summary from the completion record alone, so it never
    reopens an ephemeral download directory.

This module SHIPS to consumers (under `scripts/`, copied wholesale by the vendor slice) so
the shipped collector and validator can import it; the producer under `lib/test/` imports it
too. The digest binds bytes to an envelope under the existing trusted CI-worker/artifact
channel — it detects mismatched or foreign bytes, it is NOT a signature and authenticates
no malicious worker or a caller that forges the whole record (issue #419's stated bound).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

# The envelope's own schema version. Bumped only when the envelope shape changes; distinct
# from the request-record `SCHEMA_VERSION` and the cloud-completion-evidence version below.
ENVELOPE_SCHEMA_VERSION = 1
# The cloud-completion-evidence format version the collector emits and the validator accepts.
# It is `2` because the version-1 evidence carried unbound tallies; a version-1 record is
# rejected rather than silently read (issue #419). It lives HERE so the collector (producer)
# and the validator (consumer) share one literal rather than two that could drift.
CLOUD_CI_EVIDENCE_SCHEMA_VERSION = 2
# The envelope's `kind` discriminator.
KIND = "cloud_ci_shard_provenance"
# The sidecar filename written beside each shard `summary`.
PROVENANCE_FILENAME = "provenance.json"
# The declared CI workflow the whole contract binds to (its filename, never a display name).
CI_WORKFLOW = "ci.yml"
# An envelope larger than this is refused rather than read whole — it is a small fixed-shape
# JSON object, and an unbounded read is a denial-of-service seam (a tighter bound than the
# collector's 4 MiB _MAX_ARTIFACT_BYTES summary cap, since the envelope is far smaller).
MAX_ENVELOPE_BYTES = 64 * 1024

# The evidence-record tally field names mapped from the tab-separated `summary` field names
# shard-tally.py's extract writes (`rc` is the shard's process exit status). parse_summary_tally
# below is the single owned reader of that format for the collector and validator (issue #419).
_TALLY_FIELD_MAP = (("passed", "passed"), ("failed", "failed"),
                    ("skipped", "skipped"), ("exit_status", "rc"))

# The version-2 cloud-evidence shard-entry keys — the single owner of the nested
# {tally, summary_text, provenance} shape the collector builds and the validator reads
# (issue #419), so the shape has one definition rather than duplicated literals in two modules.
SHARD_ENTRY_TALLY = "tally"
SHARD_ENTRY_SUMMARY = "summary_text"
SHARD_ENTRY_PROVENANCE = "provenance"

_REPO_RE = re.compile(r"^[^/\s]+/[^/\s]+$")
_REQUEST_ID_RE = re.compile(r"^[0-9a-f]{32,64}$")
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_INT_RE = re.compile(r"^-?\d+$")


class ProvenanceError(Exception):
    """A structural/binding failure over an envelope or summary. Carries a short `reason`
    token and a human-readable `detail`; the collector maps `reason` onto its `_Refuse`
    tokens and the validator onto its `Verdict`."""

    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def _positive_int(value: object) -> bool:
    """True for a genuine positive int, rejecting bool (isinstance(True, int) is True in
    Python, so a JSON `true` must never read as 1) and zero/negative — a run id or attempt
    is always >= 1."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def summary_sha256(summary_bytes: bytes) -> str:
    """The SHA-256 hex digest of the exact summary bytes uploaded."""
    return hashlib.sha256(summary_bytes).hexdigest()


def parse_summary_tally(text: str) -> dict:
    """Parse a shard `summary` (TAB-separated `key<TAB>value` lines) into
    {shard, passed, failed, skipped, exit_status}. Raises ProvenanceError('bad-summary')
    on a missing or duplicated key or a non-integer count — a malformed tally is never
    coerced to zero, and a repeated key is never resolved last-write-wins.

    The ONE owned summary parser the collector and the validator both call, so a single
    contract governs how the producer's bytes are read back (issue #419)."""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if "\t" not in line:
            continue
        key, _, value = line.partition("\t")
        key = key.strip()
        if key in fields:
            raise ProvenanceError("bad-summary", f"summary repeats key {key!r}")
        fields[key] = value.strip()
    name = fields.get("shard")
    if not name:
        raise ProvenanceError("bad-summary", "summary has no shard name")
    tally: dict = {"shard": name}
    for record_field, summary_field in _TALLY_FIELD_MAP:
        raw = fields.get(summary_field)
        if raw is None or not _INT_RE.fullmatch(raw):
            raise ProvenanceError(
                "bad-summary",
                f"summary field {summary_field!r} is not an integer ({raw!r})")
        tally[record_field] = int(raw)
    return tally


def build_envelope(*, repo: str, workflow: str, request_id: str, candidate_sha: str,
                   run_id: object, run_attempt: object, shard: str,
                   summary_bytes: bytes) -> dict:
    """Build a version-1 provenance envelope binding the producing run's identity to the
    exact `summary_bytes`. Validates every identity operand and raises ProvenanceError on
    the first malformed one, so a missing or malformed identity can never yield a usable
    bound artifact (issue #419 AC1). The digest is computed over the exact bytes passed."""
    envelope = {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "kind": KIND,
        "repo": repo,
        "workflow": workflow,
        "request_id": request_id,
        "candidate_sha": candidate_sha,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "shard": shard,
        "summary_sha256": summary_sha256(summary_bytes),
    }
    # Validate the assembled object through the same contract its consumers apply, so the
    # producer can never emit an envelope the collector would reject as malformed.
    return validate_envelope(envelope)


# Shard-attempt classification for leftover acceptance (issue #543). After a Spot retry
# reruns only the interrupted shard, the survivors keep an envelope stamped with their
# earlier attempt. The evidence collector and the offline completion validator both classify
# each shard's producing attempt through this one predicate, so the leftover rule cannot
# drift between the two modules.
ATTEMPT_CURRENT = "current"
ATTEMPT_LEFTOVER = "leftover"
ATTEMPT_REFUSE = "refuse"


def classify_shard_attempt(prov_attempt: object, current_attempt: int) -> str:
    """Classify a shard envelope's `run_attempt` against the run's current attempt:
    `ATTEMPT_CURRENT` when it equals it, `ATTEMPT_LEFTOVER` when it is a strictly-earlier
    positive integer, `ATTEMPT_REFUSE` otherwise (a foreign or ahead-of-run attempt, or a
    non-positive/bool value). `current_attempt` is the caller's already-validated integer."""
    if not _positive_int(prov_attempt):
        return ATTEMPT_REFUSE
    if prov_attempt == current_attempt:
        return ATTEMPT_CURRENT
    if prov_attempt < current_attempt:
        return ATTEMPT_LEFTOVER
    return ATTEMPT_REFUSE


def validate_request_identity(request_id: object, candidate_sha: object) -> None:
    """Apply the envelope's request/candidate contract before a selected worker runs tests."""
    if not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id):
        raise ProvenanceError("bad-envelope", "request_id is not 32-64 lowercase hex")
    if not isinstance(candidate_sha, str) or not _SHA40_RE.fullmatch(candidate_sha):
        raise ProvenanceError("bad-envelope", "candidate_sha is not 40 lowercase hex")


def validate_envelope(obj: object) -> dict:
    """Structurally validate a decoded envelope and return it. Raises ProvenanceError with
    a `reason` of 'unknown-version' for an unsupported version, else 'bad-envelope' for any
    other malformed field. Pure and offline — no digest or identity cross-check here (that
    is `verify_summary_binding` and the consumers' identity comparisons)."""
    if not isinstance(obj, dict):
        raise ProvenanceError("bad-envelope", "provenance envelope is not a JSON object")
    version = obj.get("schema_version")
    if not (isinstance(version, int) and not isinstance(version, bool)):
        raise ProvenanceError("bad-envelope", "envelope schema_version is not an integer")
    if version != ENVELOPE_SCHEMA_VERSION:
        raise ProvenanceError(
            "unknown-version",
            f"envelope schema_version {version!r} is not the supported {ENVELOPE_SCHEMA_VERSION}")
    if obj.get("kind") != KIND:
        raise ProvenanceError("bad-envelope", f"envelope kind is {obj.get('kind')!r}, not {KIND!r}")
    repo = obj.get("repo")
    if not isinstance(repo, str) or not _REPO_RE.fullmatch(repo):
        raise ProvenanceError("bad-envelope", f"envelope repo {repo!r} is not owner/repo")
    if obj.get("workflow") != CI_WORKFLOW:
        raise ProvenanceError(
            "bad-envelope", f"envelope workflow {obj.get('workflow')!r} is not {CI_WORKFLOW!r}")
    validate_request_identity(obj.get("request_id"), obj.get("candidate_sha"))
    for field in ("run_id", "run_attempt"):
        if not _positive_int(obj.get(field)):
            raise ProvenanceError(
                "bad-envelope", f"envelope {field} is not a positive integer (bool rejected)")
    shard = obj.get("shard")
    if not isinstance(shard, str) or not shard.strip():
        raise ProvenanceError("bad-envelope", "envelope shard is not a nonempty string")
    digest = obj.get("summary_sha256")
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise ProvenanceError("bad-envelope", "envelope summary_sha256 is not 64 lowercase hex")
    return obj


def verify_summary_binding(envelope: dict, summary_bytes: bytes) -> dict:
    """Confirm `envelope` describes `summary_bytes`: recompute the digest and compare it to
    the envelope's, then re-parse the summary and confirm its shard name equals the
    envelope's. Raises ProvenanceError('digest-mismatch'/'shard-mismatch'/'bad-summary').
    Returns the parsed summary tally so the caller need not re-parse."""
    validate_envelope(envelope)
    actual = summary_sha256(summary_bytes)
    if actual != envelope["summary_sha256"]:
        raise ProvenanceError(
            "digest-mismatch",
            f"summary digest {actual[:12]} does not match the envelope's "
            f"{envelope['summary_sha256'][:12]} — the summary bytes changed after stamping")
    tally = parse_summary_tally(summary_bytes.decode("utf-8"))
    if tally["shard"] != envelope["shard"]:
        raise ProvenanceError(
            "shard-mismatch",
            f"summary shard {tally['shard']!r} does not match the envelope shard "
            f"{envelope['shard']!r} — a summary paired with another shard's envelope")
    return tally


def build_shard_entry(tally: dict, summary_text: str, envelope: dict) -> dict:
    """The version-2 evidence shard entry — the single builder of the nested
    {tally, summary_text, provenance} shape (issue #419), so the collector and validator
    agree on the keys through SHARD_ENTRY_* rather than duplicated literals."""
    return {
        SHARD_ENTRY_TALLY: tally,
        SHARD_ENTRY_SUMMARY: summary_text,
        SHARD_ENTRY_PROVENANCE: envelope,
    }


def _reject_duplicate_keys(pairs: list) -> dict:
    obj: dict = {}
    for key, value in pairs:
        if key in obj:
            raise DuplicateKeyError(key)
        obj[key] = value
    return obj


class DuplicateKeyError(ValueError):
    """A JSON object repeats a key; raised by `loads_strict`."""


def loads_strict(text: str) -> object:
    """`json.loads` that raises DuplicateKeyError (a ValueError) on any repeated object key
    at any depth, so an ambiguous identity or tally key is refused rather than resolved
    last-write-wins (issue #419 AC4)."""
    return json.loads(text, object_pairs_hook=_reject_duplicate_keys)


def read_regular_file(path: Path, max_bytes: int) -> bytes:
    """Read bounded bytes from a regular file; never block opening a substituted FIFO."""
    if not stat.S_ISREG(path.stat().st_mode):
        raise ProvenanceError("not-regular", f"{path} is not a regular file")
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise ProvenanceError("not-regular", f"{path} is not a regular file")
        if metadata.st_size > max_bytes:
            raise ProvenanceError("too-large", f"{path} exceeds {max_bytes} bytes")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ProvenanceError("too-large", f"{path} exceeds {max_bytes} bytes")
        return data
    finally:
        os.close(fd)


def read_envelope_file(path: Path) -> dict:
    """Read and structurally validate a provenance.json file, bounded to MAX_ENVELOPE_BYTES.
    Raises ProvenanceError('too-large'/'not-regular'/'bad-envelope'). The read is data-only —
    the bytes are parsed as JSON, never executed."""
    try:
        text = read_regular_file(path, MAX_ENVELOPE_BYTES).decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ProvenanceError("bad-envelope", f"{path} unreadable ({exc!r})")
    try:
        obj = loads_strict(text)
    except DuplicateKeyError as exc:
        raise ProvenanceError("bad-envelope", f"{path} repeats JSON key {exc.args[0]!r}")
    except ValueError as exc:
        raise ProvenanceError("bad-envelope", f"{path} is not valid JSON ({exc!r})")
    return validate_envelope(obj)
