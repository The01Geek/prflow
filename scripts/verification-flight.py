#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Single-flight verification coordination ledger (issue #528, Wave 2).

A NON-executing coordination helper. It never launches the verification command,
never accepts an executable argv to run, spawns no subprocess, makes no network
call, and runs no `git` — it is a pure Python standard-library data-only state
machine over a local, per-checkout ledger. Existing callers keep ownership of the
already-authorized verification command; this helper only grants one owner claim,
records logical owner evidence, stores terminal evidence through a token-checked
compare-and-swap, and lets a later same-checkout caller attach and consume the
result. Missing, partial, timed-out, unreadable, and stale state never becomes a
pass and never authorizes an automatic relaunch.

Subcommands:
  descriptor    Print the immutable command descriptor digest + flight key for an
                input declaration (data only; callers cannot supply a static digest).
  claim         Atomically publish a `claimed` handle and mint a one-time owner
                token, OR attach to an existing flight for the same key — active or
                terminal (e.g. a `passed` flight to consume) — without a second owner.
  mark-running  Owner-only CAS: claimed -> running, recording logical owner evidence
                immediately before the caller launches its authorized command.
  finish        Owner-only CAS: running -> passed/failed/timed_out/cancelled with
                terminal evidence (suite summary, skip details, exit status). A
                `passed` result requires a JSON integer 0 `exit_status` in that
                evidence; a missing, wrong-typed, or nonzero one is refused
                NON-terminally, leaving the flight running and re-finishable so the
                truthful `failed` can still be recorded (issue #1053).
  status        Read a flight (token redacted); report whether it satisfies
                verification. Applies lease-expiry (-> incomplete) and checkout
                drift (-> stale) read-transitions. Any unreadable/malformed shape is
                an attributable non-pass, never a pass. A pass additionally requires
                the working tree to be verified against a supplied
                `--current-checkout-file` (issue #1243) — the AND is enforced here,
                not left to the caller; `--allow-unverified-checkout` is the explicit
                opt-out for a caller that wants the state/exit dimension alone.
  event         Append a clock-authored phase-boundary event (issue #1853) to an
                append-only JSONL log under .prflow/logs/phase-events/, reusing the
                {"event": …, "recorded_at": …} shape. Always exits 0 — a failed
                write emits a stderr breadcrumb and the run continues, because
                instrumentation must never make a phase boundary blocking.
  wait          Bounded poll for a terminal state. It never records a terminal
                result of its own — a wait-bound expiry returns a `wait_expired`
                observation and leaves an active flight unchanged — but it is NOT
                side-effect-free: like `status` it applies the two read-time
                invalidations (lease expiry -> incomplete, checkout drift -> stale)
                and persists them.

State lives under .prflow/tmp/verification-flights/ (directory mode 0700,
file mode 0600), published atomically (O_CREAT|O_EXCL create for the single-owner
guarantee; temp + os.replace for updates), and is durable only within the current
checkout.

Determinism for tests: the LOGICAL clock is read through _now(), which honors the
DEVFLOW_FLIGHT_NOW epoch-seconds override, so lease-expiry and recorded durations are
testable without real sleeping. That override does NOT drive `wait`'s poll deadline —
cmd_wait bounds itself with real time.monotonic() — so a wait test spends real time and
should use a small --timeout rather than the override.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_LEASE_SECONDS = 900  # bounded owner-token lease on a `claimed` handle
STATE_DIRNAME = os.path.join(".prflow", "tmp", "verification-flights")
LOGS_DIRNAME = os.path.join(".prflow", "logs", "verification-flight")
# Append-only phase-boundary event log (issue #1853): the `event` subcommand
# appends clock-authored records here, one JSON object per line, so a run's
# interior timeline is reconstructible from disk without trusting agent recall.
PHASE_EVENTS_DIRNAME = os.path.join(".prflow", "logs", "phase-events")
PHASE_EVENTS_FILENAME = "phase-events.jsonl"

# The exact, exhaustive state set (issue #528 AC). Only `passed` (with complete,
# matching input + command bindings) satisfies verification.
ACTIVE_STATES = ("claimed", "running")
TERMINAL_STATES = ("passed", "failed", "timed_out", "cancelled", "stale", "incomplete")
ALL_STATES = ACTIVE_STATES + TERMINAL_STATES

# Exit codes — a shell caller gates reuse on `status`/`wait` exiting 0.
EXIT_OK = 0            # operation succeeded; for status/wait: state satisfies verification
EXIT_NON_PASS = 2     # read succeeded but the flight does NOT satisfy verification
EXIT_INVALID = 3      # invalid / incomplete declaration or arguments
EXIT_CAS_REJECT = 4   # ownership / transition compare-and-swap rejected
EXIT_UNREADABLE = 5   # state file missing, empty, truncated, or malformed
EXIT_WAIT_EXPIRED = 6  # wait bound elapsed with the flight still active


# ─────────────────────────────────────────────────────────────────────────────
# Time (test-overridable) and canonicalization
# ─────────────────────────────────────────────────────────────────────────────
def _now() -> float:
    """Wall-clock epoch seconds, overridable via DEVFLOW_FLIGHT_NOW for tests."""
    override = os.environ.get("DEVFLOW_FLIGHT_NOW")
    if override:
        try:
            return float(override)
        except ValueError:
            pass
    return time.time()


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def _canonical(obj: Any) -> bytes:
    """Sorted-key, compact, UTF-8 JSON — the byte form fed to SHA-256."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Declaration validation + descriptor/flight-key derivation
# ─────────────────────────────────────────────────────────────────────────────
_PROFILE_REQUIRED = (
    "profile_version",
    "argv",
    "cwd",
    "environment",
    "toolchain",
    "dependencies",
    "output_roots",
    "external_services",
)
_CHECKOUT_REQUIRED = (
    "checkout_id",
    "head",
    "index_digest",
    "tracked_digest",
    "untracked_digest",
)
# The four content fields of a checkout fingerprint are git object ids — 40-hex
# (SHA-1) or 64-hex (SHA-256) — exactly the shape scripts/checkout-fingerprint.py
# emits. Enforcing that shape is what makes `_validate_checkout` reject the junk
# strings pre-#1243 callers invented ("v", "clean", "clean-no-untracked", …) that
# the old presence-only bar accepted. `checkout_id` is deliberately NOT shape-checked
# here: it is the producer's opaque `--absolute-git-dir` path, not an object id, so it
# stays a non-empty-string field (the four object-id fields carry the tree content).
_OBJECT_ID_FIELDS = ("head", "index_digest", "tracked_digest", "untracked_digest")
_OBJECT_ID_RE = re.compile(r"\A(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def _validate_reason_code(
    reason: str, exact: frozenset[str], prefixes: frozenset[str]
) -> None:
    """Fail-fast guard on a closed machine-code vocabulary.

    `.reason` is a coupled machine code a distant assertion keys on, so a typo at
    a raise site would build a valid-but-wrong error that only fails somewhere
    far away. Validate at construction instead: a bare code must be a known
    literal; a `prefix:detail` code must carry a known prefix. An unknown code is
    a programming error and raises ValueError here, at the raise site.
    """
    head = reason.split(":", 1)[0] if ":" in reason else reason
    known = prefixes if ":" in reason else exact
    if head not in known:
        raise ValueError(f"unknown reason code: {reason!r}")


class _CodedError(Exception):
    """Shared base for the closed-reason-vocabulary errors.

    Subclasses declare `_EXACT_REASONS` / `_REASON_PREFIXES`; this base owns the
    construction-time validation and makes `.reason` **read-only for the object's
    lifetime**. The lifetime part is load-bearing, not stylistic: `.reason` is the
    machine code distant assertions key on, so a post-construction
    `exc.reason = "typo"` would rebuild exactly the valid-but-wrong error the
    construction-time check exists to prevent. Sharing the wiring here also means a
    future third coded-reason error inherits it structurally rather than by
    copy-paste convention.
    """

    _EXACT_REASONS: frozenset[str] = frozenset()
    _REASON_PREFIXES: frozenset[str] = frozenset()

    __slots__ = ("_reason",)

    def __init__(self, reason: str):
        _validate_reason_code(reason, self._EXACT_REASONS, self._REASON_PREFIXES)
        super().__init__(reason)
        # object.__setattr__ bypasses the seal below, which is exactly what
        # construction needs — and nothing after construction gets to do it.
        object.__setattr__(self, "_reason", reason)

    def __setattr__(self, name: str, value: Any) -> None:
        # Seal the instance AFTER construction. A read-only `reason` property alone
        # is not the guarantee the docstring makes: `__slots__` does not remove the
        # `__dict__` an Exception subclass inherits, so without this both
        # `exc._reason = "typo"` (the backing field) and an arbitrary new attribute
        # still succeed — and the first of those defeats the closed-vocabulary
        # invariant just as completely as assigning `.reason` would.
        raise AttributeError(
            f"{type(self).__name__} is immutable after construction "
            f"(attempted to set {name!r}); build a new error instead"
        )

    @property
    def reason(self) -> str:
        return self._reason


class DeclarationError(_CodedError):
    """An incomplete / non-hermetic declaration — reuse is disabled."""

    # The closed reason vocabulary — coupled to every DeclarationError raise site
    # in the derive/validation path (_derive + _validate_profile + _validate_checkout).
    # A new raise site adds its code here in the same change (a construction-time
    # ValueError otherwise catches the omission at the desk).
    _EXACT_REASONS = frozenset({
        "declaration_not_object",
        "unknown_schema_version",
        "profile_not_object",
        "profile_argv_not_nonempty_list",
        "profile_argv_not_all_strings",
        "profile_cwd_not_nonempty_string",
        "profile_environment_not_object",
        "profile_toolchain_not_object",
        "profile_dependencies_not_object",
        "profile_output_roots_not_list",
        "non_hermetic_profile",
        "checkout_not_object",
        "candidate_identity_not_nonempty_string",
    })
    _REASON_PREFIXES = frozenset({
        "profile_missing_field",
        "checkout_missing_field",
        "checkout_incomplete_fingerprint",
        "checkout_field_bad_shape",
    })



def _validate_profile(profile: Any) -> dict:
    if not isinstance(profile, dict):
        raise DeclarationError("profile_not_object")
    for key in _PROFILE_REQUIRED:
        if key not in profile:
            raise DeclarationError(f"profile_missing_field:{key}")
    # argv is a data descriptor operand, never an argv the helper will execute.
    if not isinstance(profile["argv"], list) or not profile["argv"]:
        raise DeclarationError("profile_argv_not_nonempty_list")
    if not all(isinstance(x, str) for x in profile["argv"]):
        raise DeclarationError("profile_argv_not_all_strings")
    if not isinstance(profile["cwd"], str) or not profile["cwd"]:
        raise DeclarationError("profile_cwd_not_nonempty_string")
    for key in ("environment", "toolchain", "dependencies"):
        if not isinstance(profile[key], dict):
            raise DeclarationError(f"profile_{key}_not_object")
    if not isinstance(profile["output_roots"], list):
        raise DeclarationError("profile_output_roots_not_list")
    # Hermeticity: only external_services == "none" is reusable. A profile that
    # declares any external service dependency is non-reusable by construction.
    if profile["external_services"] != "none":
        raise DeclarationError("non_hermetic_profile")
    return profile


def _validate_checkout(checkout: Any) -> dict:
    if not isinstance(checkout, dict):
        raise DeclarationError("checkout_not_object")
    for key in _CHECKOUT_REQUIRED:
        if key not in checkout:
            raise DeclarationError(f"checkout_missing_field:{key}")
        if not isinstance(checkout[key], str) or not checkout[key]:
            raise DeclarationError(f"checkout_incomplete_fingerprint:{key}")
    # Shape gate (issue #1243): the four content fields must be git object ids, the
    # shape scripts/checkout-fingerprint.py emits. A non-empty-but-wrong-shape value
    # (the invented "v"/"clean"/"clean-no-untracked" a pre-producer caller wrote) is
    # rejected here instead of silently keying a flight — so a stale flight can no
    # longer masquerade as a fresh one behind a fingerprint that describes no tree.
    for key in _OBJECT_ID_FIELDS:
        if not _OBJECT_ID_RE.match(checkout[key]):
            raise DeclarationError(f"checkout_field_bad_shape:{key}")
    return checkout


def _descriptor_bytes(profile: dict) -> bytes:
    """The immutable command descriptor — the canonical JSON of the profile's
    identity operands only. Byte-distinct argv/cwd/environment/toolchain/
    dependency/profile_version inputs produce distinct descriptors."""
    ident = {
        "profile_version": profile["profile_version"],
        "argv": profile["argv"],
        "cwd": profile["cwd"],
        "environment": profile["environment"],
        "toolchain": profile["toolchain"],
        "dependencies": profile["dependencies"],
    }
    return _canonical(ident)


def _derive(declaration: Any) -> dict:
    """Validate a declaration and derive descriptor digest + flight key.

    Raises DeclarationError on any incomplete/non-hermetic input. The helper
    derives SHA-256 itself; a caller-supplied digest is never trusted.
    """
    if not isinstance(declaration, dict):
        raise DeclarationError("declaration_not_object")
    if declaration.get("schema_version") != SCHEMA_VERSION:
        raise DeclarationError("unknown_schema_version")
    profile = _validate_profile(declaration.get("profile"))
    checkout = _validate_checkout(declaration.get("checkout"))
    descriptor_digest = _sha256(_descriptor_bytes(profile))
    flight_key = _sha256(
        _canonical({"descriptor_digest": descriptor_digest, "checkout": checkout})
    )
    # Optional content-based candidate identity (issue #668). A SIBLING of
    # `checkout`, NEVER a member of it: `_descriptor_bytes` and the flight-key
    # derivation above read only `profile` and `checkout`, so this field leaves
    # `descriptor_digest` and `flight_key` byte-identical and every stored handle
    # valid. An in-`checkout` placement would silently invalidate every stored
    # handle while presence-only tests still passed — the documented gotcha.
    # An ABSENT field records None (that stays legal — the AC); a PRESENT one is
    # validated to the same non-empty-string bar every sibling operand meets, so a
    # dict/list/int/blank can never be persisted into the handle and then compare
    # silently unequal against a freshly re-derived tree id. SCHEMA_VERSION is
    # unchanged, because a bump would reject every existing declaration.
    candidate_identity = declaration.get("candidate_identity")
    if candidate_identity is not None and (
        not isinstance(candidate_identity, str) or not candidate_identity.strip()
    ):
        raise DeclarationError("candidate_identity_not_nonempty_string")
    return {
        "descriptor_digest": descriptor_digest,
        "flight_key": flight_key,
        "profile": profile,
        "checkout": checkout,
        "candidate_identity": candidate_identity,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Ledger IO — atomic, owner-only-permission
# ─────────────────────────────────────────────────────────────────────────────
def _state_dir(root: str | None, logs_dir: str | None = None) -> Path:
    base = Path(root) if root else Path.cwd() / STATE_DIRNAME
    base.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(base, 0o700)
    except OSError as exc:
        # Best-effort by design (a read-only mount or a foreign-uid directory must
        # not break coordination), but NEVER silent: the module's own 0700
        # directory-mode claim is false on this host, and a bare `except: pass`
        # left an operator auditing that discrepancy with nothing to find. Each
        # flight file is still individually 0600; it is the directory listing whose
        # protection is degraded, so record it rather than swallow it.
        recorded = _emit_telemetry(
            logs_dir, "state_dir_chmod_failed",
            {"path": str(base), "error": f"{type(exc).__name__}: {exc}"},
        )
        if not recorded:
            # The host that cannot chmod the state dir is often the same host that
            # cannot write the logs dir, so the breadcrumb meant to replace the old
            # silent `pass` could itself be silently lost. stderr is the floor.
            print(
                f"devflow verification-flight: could not chmod {base} to 0700 "
                f"({type(exc).__name__}: {exc}); directory-listing protection is "
                f"degraded on this host (flight files remain 0600)",
                file=sys.stderr,
            )
    return base


def _flight_path(state_dir: Path, flight_key: str) -> Path:
    return state_dir / f"{flight_key}.json"


def _atomic_replace(path: Path, body: dict) -> None:
    data = _canonical(body)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}.{secrets.token_hex(4)}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _ledger_write(path: Path, flight: dict) -> str | None:
    """Persist a ledger handle, converting a write-path OSError into an
    attributable `write_failed:<errno-class>` reason instead of an uncaught
    traceback. Returns None on success, or the reason string on failure.

    Every other error surface in this module emits the `{"ok": false, "reason": …}`
    JSON shape and one of the documented exit codes; a bare `os.write`/`os.replace`
    OSError on the coordination path (ENOSPC/EACCES on the state dir) would instead
    crash with exit 1 and no attributable record. This keeps an owner-write failure
    auditable. It still fails SAFE for reuse gating: the caller emits a non-zero
    exit, so no attacher ever consumes the half-written handle as a pass.
    """
    try:
        _atomic_replace(path, flight)
        return None
    except OSError as exc:
        return f"write_failed:{exc.__class__.__name__}"


class ReadError(_CodedError):
    """A flight file that is missing, empty, truncated, or malformed — a
    non-pass with an attributable reason, never inferred as terminal."""

    # The closed reason vocabulary — coupled to the raise sites in _read_flight.
    _EXACT_REASONS = frozenset({
        "missing",
        "empty",
        "malformed_json",
        "not_object",
        "unknown_schema_version",
        "missing_or_invalid_state",
    })
    _REASON_PREFIXES = frozenset({
        "unreadable",
        "missing_field",
    })



def _read_flight(path: Path) -> dict:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        raise ReadError("missing")
    except OSError as exc:
        raise ReadError(f"unreadable:{exc.__class__.__name__}")
    if not raw.strip():
        raise ReadError("empty")
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ReadError("malformed_json")
    if not isinstance(obj, dict):
        # array / scalar top-level payloads are not a flight handle.
        raise ReadError("not_object")
    if obj.get("schema_version") != SCHEMA_VERSION:
        raise ReadError("unknown_schema_version")
    state = obj.get("state")
    # `state` must be present and a member of the exact set; a wrong-typed value
    # such as the string "true" or a missing field is a non-pass, never coerced.
    if not isinstance(state, str) or state not in ALL_STATES:
        raise ReadError("missing_or_invalid_state")
    for field in ("flight_key", "descriptor_digest", "token_digest"):
        if not isinstance(obj.get(field), str) or not obj.get(field):
            raise ReadError(f"missing_field:{field}")
    return obj


# ─────────────────────────────────────────────────────────────────────────────
# Telemetry (best-effort, local, hermetic)
# ─────────────────────────────────────────────────────────────────────────────
def _emit_telemetry(logs_dir: str | None, event: str, payload: dict) -> bool:
    """Append a per-event JSON record under .prflow/logs/verification-flight/.

    Best-effort and hermetic: a stale/incomplete handle is never recorded as
    saved work. The honesty property rides on `flight_attached`'s own
    `attached_state` field — a cross-run analyzer counts a suppressed launch
    only for `attached_state == "passed"`, so an attach to a stale/incomplete
    handle is visibly not saved work. (There is no `suppressed_launch` field;
    `attached_state` is the operand.)
    A failure to write telemetry never fails the coordination operation. It does
    RETURN that failure (False) so a caller whose breadcrumb is load-bearing — e.g.
    _state_dir's chmod failure, where the same host condition often breaks both
    writes — can fall back to stderr instead of losing the record entirely.
    """
    try:
        base = Path(logs_dir) if logs_dir else Path.cwd() / LOGS_DIRNAME
        base.mkdir(parents=True, exist_ok=True)
        rec = {"event": event, "recorded_at": _iso(_now()), **payload}
        name = f"{event}-{secrets.token_hex(8)}.json"
        _atomic_replace(base / name, rec)
        return True
    except (OSError, TypeError, ValueError):
        # Best-effort telemetry must never harden into a coordination failure. A
        # non-serializable payload (a value _canonical can't encode) raises
        # TypeError/ValueError, not OSError — catching only OSError would let a bad
        # payload propagate out and fail the enclosing coordination op. Every write
        # failure mode returns False so a caller with a load-bearing breadcrumb can
        # fall back to stderr.
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Read-time transitions (lease expiry -> incomplete; checkout drift -> stale)
# ─────────────────────────────────────────────────────────────────────────────
def _apply_read_transitions(
    path: Path, flight: dict, current_checkout: dict | None,
    logs_dir: str | None = None,
) -> dict:
    """Apply the two non-owner read-transitions, persisting if either fires.

    * A `claimed` handle whose owner-token lease has expired before mark-running
      becomes `incomplete` (owner loss at the claim boundary; the ledger never
      infers the unobserved command ran).
    * An active handle whose stored checkout no longer matches a supplied current
      checkout becomes `stale` (repository/environment drift invalidates reuse).

    Either transition emits a `flight_invalidated` telemetry event. Terminal
    handles are immutable — never re-transitioned.

    Non-CAS write, deliberately (race acknowledged): these read-transitions persist
    without re-checking that the on-disk handle is unchanged, so a concurrent owner
    CAS (`mark-running`/`finish`) landing in the same instant can be clobbered by
    this read-time write. The blast radius is bounded and safe: this path only ever
    moves an ACTIVE handle to a non-pass terminal (`stale`/`incomplete`) — it can
    never overwrite or manufacture a `passed`, so the worst case is a spurious
    invalidation that costs one duplicate launch, never a false reuse.
    """
    state = flight["state"]
    if state not in ACTIVE_STATES:
        return flight

    # Drift first: a mismatched checkout invalidates regardless of lease.
    if current_checkout is not None and flight.get("checkout") != current_checkout:
        flight["state"] = "stale"
        flight["invalidation_reason"] = "checkout_drift"
        flight["finished_at"] = _iso(_now())
        _atomic_replace(path, flight)
        _emit_telemetry(
            logs_dir, "flight_invalidated",
            {"flight_key": flight.get("flight_key"), "invalidation_reason": "checkout_drift"},
        )
        return flight

    if state == "claimed" and _lease_expired(flight):
        _expire_claim(path, flight)
        _emit_telemetry(
            logs_dir, "flight_invalidated",
            {"flight_key": flight.get("flight_key"), "invalidation_reason": "lease_expired_before_running"},
        )
    return flight


def _lease_expired(flight: dict) -> bool:
    """True when a `claimed` handle's owner-token lease has elapsed.

    A missing / non-numeric `lease_expiry_epoch` (only possible via out-of-band
    corruption — `claim` always writes a float) is treated as NOT expired, so such
    a `claimed` handle pins as `claimed` rather than becoming `incomplete`. This is
    a fail-safe, not a false pass: `claimed` never satisfies verification, so the
    cost is a handle that lingers until its own owner finishes (or an attacher's
    `wait` bound elapses) — the fail direction is duplicate work, never reuse.
    """
    expiry = flight.get("lease_expiry_epoch")
    return isinstance(expiry, (int, float)) and _now() > expiry


def _expire_claim(path: Path, flight: dict) -> dict:
    """Transition a lease-expired `claimed` handle to `incomplete` and persist.

    The single writer of this transition — shared by the read-time path
    (`_apply_read_transitions`) and the owner's own `mark-running` guard — so the
    two can never drift on the mutation. The error *responses* stay distinct (a
    read-transition vs. a CAS reject); only the mutation is shared.
    """
    flight["state"] = "incomplete"
    flight["invalidation_reason"] = "lease_expired_before_running"
    flight["finished_at"] = _iso(_now())
    _atomic_replace(path, flight)
    return flight


def _zero_exit_status(summary: Any) -> bool:
    """True iff `summary` is an object carrying a JSON integer `0` `exit_status`.

    The single owner of this repository's zero-exit-status predicate, shared by the
    `finish` write gate and the reuse predicate below so the two can never disagree
    about which recorded evidence is a pass. It mirrors the READER's already-shipped
    condition in `scripts/check-completion-evidence.py` (issue #1087 / PR #1119) in
    intent: a JSON `true` is not a zero even though Python's `bool` subclasses `int`,
    and the string `"0"` is not a zero either. An absent field is unestablished, and
    an unestablished measurement is never collapsed onto a real value — so it is
    false here, which is the fail-closed direction.
    """
    if not isinstance(summary, dict):
        return False
    status = summary.get("exit_status")
    if isinstance(status, bool) or not isinstance(status, int):
        return False
    return status == 0


def _satisfies(flight: dict) -> bool:
    """Only a `passed` terminal handle whose evidence carries a zero exit status.

    The exit-status limb (issue #1053) is what keeps this predicate and the shipped
    completion gate on ONE disposition. `finish` now refuses to mint a `passed`
    handle without that evidence, so the only records the limb can exclude are ones
    written BEFORE this change — a legacy `passed` handle carrying no `exit_status`.
    Such a handle is disposed of as NOT reusable, which is the disposition the
    completion gate already takes: without this limb an attacher would be told to
    consume a pass that `check-completion-evidence.py` refuses at the phase where the
    work is already finished. The cost of the fail-closed direction is one duplicate
    verification run, never a false reuse.
    """
    return flight["state"] == "passed" and _zero_exit_status(flight.get("suite_summary"))


def _effective_pass(flight: dict, checkout_verified: bool, allow_unverified: bool) -> bool:
    """The status/wait pass verdict: state pass AND the checkout was verified.

    The single home of issue #1243's checkout AND, so `cmd_status` and `cmd_wait`
    cannot drift on the security-relevant rule. A `passed` handle whose working tree
    this read did not confirm is not a reusable pass unless the caller explicitly
    opted into the weaker state-only read via `--allow-unverified-checkout`.
    """
    return _satisfies(flight) and (checkout_verified or allow_unverified)


def _public_view(flight: dict) -> dict:
    """A token-redacted view for status/wait/attach output."""
    view = dict(flight)
    view["token_digest"] = "REDACTED"
    # This base view carries only the STATE dimension (passed + zero exit). `claim`
    # attach emits it as-is, and it is deliberately never a reusable pass on its own:
    # attach cannot verify the working tree, so a consume must re-anchor via
    # status/wait with `--current-checkout-file`. `cmd_status`/`cmd_wait` OVERRIDE
    # both fields below with the effective verdict from `_effective_pass`, which folds
    # in the checkout dimension (issue #1243) — so on those paths the AND is already
    # enforced in the value, not left as a caller obligation.
    view["satisfies_verification"] = _satisfies(flight)
    # `reuse_ready` is the explicit, unambiguously-named operand a caller reads to
    # decide reuse (issue #579 review): it mirrors `satisfies_verification` so no
    # caller is tempted to branch on the process exit code — which is deliberately
    # role-only on `claim`/attach (EXIT_OK regardless of the attached state).
    view["reuse_ready"] = _satisfies(flight)
    return view


def _print_public(flight: dict, **extra) -> None:
    """Emit a token-redacted public view with ok=True plus any extra fields."""
    view = _public_view(flight)
    view["ok"] = True
    view.update(extra)
    _print(view)


# ─────────────────────────────────────────────────────────────────────────────
# Subcommand handlers
# ─────────────────────────────────────────────────────────────────────────────
def _load_json_arg(path_str: str) -> Any:
    data = Path(path_str).read_bytes()
    return json.loads(data.decode("utf-8"))


def _print(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, sort_keys=True) + "\n")


def _derive_arg(input_file: str):
    """Load + derive a declaration file. Returns (derived, None) on success or
    (None, (payload, exit_code)) on an unreadable input or invalid declaration —
    the single shared preamble for `descriptor` and `claim`. An incomplete /
    non-hermetic declaration disables reuse (EXIT_INVALID)."""
    try:
        decl = _load_json_arg(input_file)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, ({"ok": False, "result": "invalid",
                       "reason": f"input:{exc.__class__.__name__}",
                       "satisfies_verification": False}, EXIT_INVALID)
    try:
        return _derive(decl), None
    except DeclarationError as exc:
        return None, ({"ok": False, "result": "invalid", "reason": exc.reason,
                       "satisfies_verification": False}, EXIT_INVALID)


def cmd_descriptor(args) -> int:
    derived, err = _derive_arg(args.input_file)
    if err:
        _print(err[0])
        return err[1]
    _print(
        {
            "ok": True,
            "descriptor_digest": derived["descriptor_digest"],
            "flight_key": derived["flight_key"],
        }
    )
    return EXIT_OK


def cmd_claim(args) -> int:
    derived, err = _derive_arg(args.input_file)
    if err:
        _print(err[0])
        return err[1]

    state_dir = _state_dir(args.state_dir, args.logs_dir)
    path = _flight_path(state_dir, derived["flight_key"])
    now = _now()
    lease = args.lease_seconds if args.lease_seconds is not None else DEFAULT_LEASE_SECONDS
    # token_hex (not token_urlsafe): 256 bits of entropy, unguessable, but drawn
    # from [0-9a-f] only — so a minted token can never begin with '-' and be
    # mis-parsed as an option flag when passed as `--token <value>` on the CLI.
    token = secrets.token_hex(32)
    handle = {
        "schema_version": SCHEMA_VERSION,
        "flight_key": derived["flight_key"],
        "descriptor_digest": derived["descriptor_digest"],
        "profile_version": derived["profile"]["profile_version"],
        "checkout": derived["checkout"],
        # Optional candidate identity carried into the handle (issue #668); a
        # declaration omitting it records the field absent (None).
        "candidate_identity": derived["candidate_identity"],
        "state": "claimed",
        "token_digest": _sha256(token.encode("utf-8")),
        "claimed_at": _iso(now),
        "claimed_at_epoch": now,
        "lease_seconds": lease,
        "lease_expiry_epoch": now + lease,
        "lease_expiry": _iso(now + lease),
        "running_at": None,
        "running_at_epoch": None,
        "owner_evidence": None,
        "finished_at": None,
        "result": None,
        "suite_summary": None,
        "skipped_checks": [],
        "invalidation_reason": None,
    }
    data = _canonical(handle)
    # Single-owner guarantee: O_CREAT|O_EXCL means at most one concurrent caller
    # wins the create; every other caller falls through to attach.
    #
    # Single-owner-atomic but NOT content-atomic (accepted, fails closed): between
    # this exclusive create and the os.write below there is a tiny window in which a
    # concurrent attacher can read a zero-byte file → `_read_flight` returns `empty`
    # → the attacher takes the `unreadable` non-pass and launches directly. That is
    # the correct fail-safe direction (a transient duplicate launch, never a false
    # pass), so this deliberately keeps O_CREAT|O_EXCL rather than a temp+os.replace
    # publish: os.replace has no exclusive-create semantics, so switching to it to
    # buy content-atomicity would forfeit the single-owner guarantee this create is
    # here to provide (two racing callers could each replace, minting two owners) —
    # a strictly worse trade than the fail-closed empty-read it would remove.
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        fd = None  # a flight already exists for this key — attach below
    except OSError as exc:
        # Winning-side create failed (ENOSPC/EACCES on the state dir). Emit the same
        # attributable JSON shape every other error path uses instead of an uncaught
        # traceback; non-zero exit fails SAFE (no owner, no attacher reuse).
        _print({"ok": False, "result": "write_failed",
                "reason": f"write_failed:{exc.__class__.__name__}",
                "satisfies_verification": False})
        return EXIT_UNREADABLE
    if fd is not None:
        write_err = None
        try:
            os.write(fd, data)
        except OSError as exc:
            write_err = exc
        finally:
            os.close(fd)
        if write_err is not None:
            # We won the O_EXCL create but the write failed — the handle is a
            # zero-byte file and the owner token was never printed. Surface it as an
            # auditable write_failed rather than a bare traceback with no JSON to
            # parse; a later attacher reads the empty file -> `unreadable` -> its own
            # direct launch, so this is fail-safe (duplicate work, never a false pass).
            _print({"ok": False, "result": "write_failed",
                    "reason": f"write_failed:{write_err.__class__.__name__}",
                    "satisfies_verification": False})
            return EXIT_UNREADABLE
        _emit_telemetry(
            args.logs_dir, "flight_claimed",
            {"flight_key": derived["flight_key"], "descriptor_digest": derived["descriptor_digest"]},
        )
        _print(
            {
                "ok": True,
                "role": "owner",
                "flight_key": derived["flight_key"],
                "descriptor_digest": derived["descriptor_digest"],
                "state": "claimed",
                "token": token,  # printed exactly once, never persisted in cleartext
                "lease_expiry": handle["lease_expiry"],
            }
        )
        return EXIT_OK

    # A flight already exists for this exact key — attach without a second owner.
    #
    # ONE-SHOT PER KEY (deliberate). A terminal handle is never re-owned: a later
    # caller for the same key attaches to it, reads a non-pass, and falls back to its
    # own direct launch. There is intentionally no `reclaim`/`--force`/delete
    # subcommand, because minting a second owner over a terminal record is exactly the
    # unsound move the single-owner guarantee exists to prevent. The cost is bounded
    # and safe: coordination for that key degrades to today's uncoordinated behavior
    # (every caller launches its own suite) until any declared input changes, which
    # mints a fresh key. The fail direction is duplicate work, never a false pass.
    #
    # NO `running` LEASE (deliberate — issue #528 AC). A `claimed` handle carries a
    # bounded lease because a claim made and abandoned before `mark-running` proves
    # nothing was ever launched. A `running` handle deliberately carries NO expiry:
    # the AC requires that "the ledger never infers that an unobserved process ended",
    # and auto-expiring `running` is precisely that inference — it would let a suite
    # still executing be re-declared abandoned. An owner lost mid-run therefore leaves
    # `running` until its own `finish`; attachers bound their exposure with `wait`'s
    # non-mutating `wait_expired` and launch directly. Liveness is traded for the
    # never-a-false-pass invariant, on purpose.
    try:
        flight = _read_flight(path)
    except ReadError as exc:
        _print({"ok": False, "result": "unreadable", "reason": exc.reason, "flight_key": derived["flight_key"]})
        return EXIT_UNREADABLE
    flight = _apply_read_transitions(path, flight, None, args.logs_dir)
    _emit_telemetry(
        args.logs_dir, "flight_attached",
        {"flight_key": derived["flight_key"], "attached_state": flight["state"]},
    )
    # candidate_identity is OUTSIDE the flight key by design (issue #668), so two
    # declarations sharing a `checkout` fingerprint map to one handle even when
    # their declared content identities differ. Before issue #550 the attacher
    # silently received the first claimer's value and could consume its `passed`
    # handle for a DIFFERENT content identity. Now the first consumer that reads the
    # handle's candidate_identity as authoritative (the completion-evidence check)
    # closes that residual here: when the attacher's OWN declared candidate_identity
    # is present and does not PROVABLY equal the handle's recorded one, the attach is
    # not a reusable pass — force `reuse_ready`/`satisfies_verification` False and
    # surface `candidate_identity_match: false` so the attacher launches its own
    # verification rather than consuming a pass bound to other content.
    # ASYMMETRY IS NOT A MATCH (the stored-`None` half of the #681 residual): a handle
    # claimed by a pre-#668 producer that declared NO candidate_identity records None,
    # so a declaring attacher comparing against it can prove nothing about what content
    # that pass covered. Requiring `stored_ci is not None` for a *mismatch* made that
    # unprovable case fall through to reuse — a fail-OPEN admitting a pass bound to
    # unknown content. The predicate is therefore stated affirmatively: a declaring
    # attacher is reusable only on an observed equal pair; declared-present against
    # stored-`None` is non-reusable, the fail-CLOSED direction (cost: one duplicate
    # suite run). descriptor_digest and flight_key are UNCHANGED (this touches only the
    # attach READ path, never _derive or the handle write), so every stored handle
    # stays valid. An attacher that declares no candidate_identity (None) keeps the
    # pre-#550 behaviour and is unaffected by this arm.
    declared_ci = derived["candidate_identity"]
    stored_ci = flight.get("candidate_identity")
    ci_mismatch = declared_ci is not None and declared_ci != stored_ci
    # Attach never supplies a current checkout, so it cannot verify the tree —
    # checkout_verified is always False here; a consume must re-anchor via
    # status/wait with --current-checkout-file (see phase-3-fix-loop.md).
    if ci_mismatch:
        _print_public(
            flight, role="attacher", checkout_verified=False,
            candidate_identity_match=False, reuse_ready=False,
            satisfies_verification=False,
        )
    else:
        _print_public(
            flight, role="attacher", checkout_verified=False,
            candidate_identity_match=(stored_ci is not None and declared_ci is not None),
        )
    # Attach ALWAYS exits EXIT_OK — the exit status here is role-only ("I attached
    # to an existing flight"), NOT a verdict. Whether the attached flight is a
    # consumable pass is carried in the JSON (`role`, `state`,
    # `satisfies_verification`/`reuse_ready`); a caller must read those, never branch
    # on this exit code, to decide reuse. (status/wait DO encode pass/non-pass in the
    # code, and add `checkout_verified` for the tree-match dimension.)
    return EXIT_OK


def _cas_load(path: Path, token: str) -> tuple[dict | None, int, str]:
    """Load a flight and verify owner-token CAS. Returns (flight, exit, reason)."""
    try:
        flight = _read_flight(path)
    except ReadError as exc:
        return None, EXIT_UNREADABLE, exc.reason
    # Constant-time: this is the sole ownership gate for mark-running/finish, so a
    # naive `!=` leaks digest-prefix information through comparison timing.
    if not hmac.compare_digest(
        _sha256(token.encode("utf-8")), str(flight.get("token_digest") or "")
    ):
        # attacher / stale-token / replay-with-wrong-token
        return None, EXIT_CAS_REJECT, "token_mismatch"
    return flight, EXIT_OK, ""


def cmd_mark_running(args) -> int:
    state_dir = _state_dir(args.state_dir, args.logs_dir)
    path = _flight_path(state_dir, args.flight)
    flight, code, reason = _cas_load(path, args.token)
    if flight is None:
        _print({"ok": False, "result": "rejected", "reason": reason})
        return code
    # Lease must still be valid at the transition; an expired lease is owner loss.
    # Shares the single _expire_claim mutation with the read-transition path.
    if flight["state"] == "claimed" and _lease_expired(flight):
        _expire_claim(path, flight)
        _print({"ok": False, "result": "rejected", "reason": "lease_expired", "state": "incomplete"})
        return EXIT_CAS_REJECT
    if flight["state"] != "claimed":
        # replay (already running) or post-terminal transition
        _print({"ok": False, "result": "rejected", "reason": f"not_claimed:{flight['state']}"})
        return EXIT_CAS_REJECT
    now = _now()
    flight["state"] = "running"
    flight["running_at"] = _iso(now)
    flight["running_at_epoch"] = now
    flight["owner_evidence"] = args.evidence or "owner running verification command"
    werr = _ledger_write(path, flight)
    if werr:
        _print({"ok": False, "result": "write_failed", "reason": werr, "satisfies_verification": False})
        return EXIT_UNREADABLE
    _print({"ok": True, "state": "running", "flight_key": args.flight})
    return EXIT_OK


# ─────────────────────────────────────────────────────────────────────────────
# Runner-log derivation (`finish --from-runner-log`)
# ─────────────────────────────────────────────────────────────────────────────
# Derives the terminal evidence from a log a runner RETAINED, so the caller asserts a
# file path instead of a verdict. Every operand it cannot establish refuses the
# derivation with a NAMED reason — never a default, because an unestablished
# measurement collapsed onto a real value is the false green this mode exists to remove.
# What it does NOT establish: that the log describes THIS tree or THIS flight. Only the
# path, size and mtime are recorded as provenance, so a stale or foreign log with a
# clean aggregate is accepted; that residual is stated in the flag help too.

#: `run-parallel: aggregate CLEAN` / `... aggregate FAILED — <detail>`. The
#: coordinator's own verdict, and the ONLY operand that decides a coordinator run:
#: it returns non-zero for a shard that did not complete even when the recombined
#: tally reads clean, so the tally alone is not the result.
_RE_AGGREGATE = re.compile(r"^run-parallel:\s+aggregate\s+(CLEAN|FAILED)\b", re.MULTILINE)
#: `Module <id>: N passed, M failed[, K skipped]` — run-module.sh's terminal line.
#: Keep the third group optional and READ it: dropping it launders a module run's
#: skipped population into a clean pass (issue #742).
_RE_MODULE = re.compile(
    r"^Module\s+(\S+):\s+(\d+)\s+passed,\s+(\d+)\s+failed(?:,\s+(\d+)\s+skipped)?",
    re.MULTILINE,
)
#: `shard-tally combine: required partition covered (<n> shard(s)): <ids>` — the
#: recombination's self-identification. Match ONLY this affirmative line, never the
#: bare `shard-tally combine: <n> shard(s):` roster: cmd_combine emits the covered
#: line only when `--require-shards` was given AND the partition reconciled, which is
#: exactly the reconciled recombination the completion gate accepts (issue #1289).
_RE_RECOMBINE = re.compile(
    r"^shard-tally combine:\s+required partition covered\s+"
    r"\(\d+\s+shard\(s\)\):\s+(\S.*?)\s*$",
    re.MULTILINE,
)
#: `run-shard.sh: retained log: <abs>` — the shard runner's self-identification.
_RE_SHARD = re.compile(r"^run-shard\.sh:\s+retained log:", re.MULTILINE)
#: `run.sh: serial suite complete (skip-suite-modules=<0|1>, skip-python-pool=<0|1>)`.
_RE_RUNSH = re.compile(
    r"^run\.sh:\s+serial suite complete\s+\(skip-suite-modules=([01]),\s*"
    r"skip-python-pool=([01])\)", re.MULTILINE
)
#: Any coordinator line at all, used only to tell "lost stderr" from "not a coordinator
#: log": the `aggregate FAILED` verdict goes to stderr, so a stdout-only capture of a
#: failing coordinator run carries these lines and no aggregate line.
_RE_RUNPARALLEL_ANY = re.compile(r"^run-parallel:\s+", re.MULTILINE)
#: summary.sh's bare tally line. run-module.sh's tally is NOT this shape — it is
#: embedded in its `Module <id>: ...` line — which is why the module arm below reads
#: _RE_MODULE's own groups rather than falling through to this one.
_RE_TALLY = re.compile(
    r"^(\d+)\s+passed,\s+(\d+)\s+failed(?:,\s+(\d+)\s+skipped)?\s*$", re.MULTILINE
)
#: Itemized skip lines (`  SKIP  <name> [<kind>] — <reason>`), the population the tally
#: counts. summary.sh's four parenthesised diagnostic placeholders are NOT members —
#: they announce that the itemization failed, and counting them as skips refuses a
#: clean run over a breadcrumb.
_RE_SKIP_LINE = re.compile(r"^\s*SKIP\s+(?!\s*\()(\S.*?)\s*$", re.MULTILINE)
#: The `[<kind>] — <reason>` tail summary.sh emits in a fixed position. The kind
#: (`blocking-gate` vs `host-capability`) is load-bearing to a skip reader.
_RE_SKIP_TAIL = re.compile(r"^(.*?)\s+\[(blocking-gate|host-capability)\]\s+—\s+(.*)$")
#: `run-parallel: elapsed <N>s`.
_RE_ELAPSED = re.compile(r"^run-parallel:\s+elapsed\s+(\d+)s\b", re.MULTILINE)
#: `run-parallel: retained logs: <dir>` / `run-parallel: retained coordinator log:
#: <file>` / `run-shard.sh: retained log: <file>`.
_RE_RETAINED = re.compile(
    r"^(?:run-parallel:\s+retained (?:logs|coordinator log)"
    r"|run-shard\.sh:\s+retained log):\s+(\S.*?)\s*$",
    re.MULTILINE,
)


class RunnerLogError(_CodedError):
    """A named refusal to derive terminal evidence from a runner log."""

    # The closed reason vocabulary — coupled to every raise site in the derivation
    # path below. A new raise site adds its code here in the same change (a
    # construction-time ValueError otherwise catches the omission at the desk).
    _EXACT_REASONS = frozenset({
        "runner_log_no_aggregate",
        "runner_log_unrecognized",
        "runner_log_no_tally",
        "runner_log_aggregate_contradicts_tally",
    })
    _REASON_PREFIXES = frozenset({
        "runner_log",
    })

    __slots__ = ("_detail",)

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        # object.__setattr__ bypasses the base's post-construction seal, which is
        # exactly what construction needs — and nothing after construction gets to.
        object.__setattr__(self, "_detail", detail)

    @property
    def detail(self) -> str:
        return self._detail


def _read_runner_log(path_str: str) -> str:
    """Read a runner log as text, or raise a named RunnerLogError.

    Decoding is `errors="replace"`: a log carrying a stray non-UTF-8 byte is still a
    log, and refusing it would send the caller straight back to hand-authoring the
    summary. A file that decodes to nothing recognizable is caught by the marker
    scan below, not here.
    """
    try:
        return Path(path_str).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise RunnerLogError(f"runner_log:{exc.__class__.__name__}", str(exc)) from exc


def derive_summary_from_runner_log(path_str: str) -> tuple[dict, list, str]:
    """Derive `(suite_summary, skipped_checks, derived_result)` from a runner log.

    `derived_result` is `"passed"` or `"failed"` — the log's OWN verdict, which the
    caller's `--result` must agree with. Raises RunnerLogError, never returns a
    partial derivation.
    """
    text = _read_runner_log(path_str)

    # 1) Identify the runner from its own terminal marker, OUTERMOST FIRST. A shard log
    #    embeds the driver's markers and a coordinator log does not, so testing the
    #    inner markers first would attribute an outer run to its innermost driver.
    aggregate = _RE_AGGREGATE.search(text)
    recombine = _RE_RECOMBINE.search(text)
    shard = _RE_SHARD.search(text)
    runsh = _RE_RUNSH.search(text)
    module = _RE_MODULE.search(text)
    if aggregate:
        command = "lib/test/run-parallel.sh"
    elif recombine:
        # The shard-decomposition path's own whole-suite result. Test it AFTER the
        # aggregate: the coordinator tees this same line into its log, and the
        # coordinator's verdict — not the recombination's — owns a coordinator run.
        ids = " ".join(t for t in re.split(r"[,\s]+", recombine.group(1)) if t)
        command = (
            f'lib/test/shard-tally.py combine --require-shards "{ids}"'
        )
    elif shard:
        command = "lib/test/run-shard.sh"
    elif runsh:
        # Name the population selectors in the command: a run with both set is the
        # `monolith` shard, which the completion gate must refuse (issue #742).
        prefix = ""
        if runsh.group(1) == "1":
            prefix += "DEVFLOW_SKIP_SUITE_MODULES=1 "
        if runsh.group(2) == "1":
            prefix += "DEVFLOW_SKIP_PYTHON_POOL=1 "
        command = prefix + "lib/test/run.sh"
    elif module:
        command = f"lib/test/run-module.sh {module.group(1)}"
    elif _RE_RUNPARALLEL_ANY.search(text):
        raise RunnerLogError(
            "runner_log_no_aggregate",
            "coordinator lines are present but no `run-parallel: aggregate` line is: "
            "`aggregate FAILED` is written to stderr, so capture the coordinator's "
            "MERGED output, or pass the `retained coordinator log` it names",
        )
    else:
        raise RunnerLogError(
            "runner_log_unrecognized",
            "no run-parallel / shard-tally combine / run-shard / run.sh / run-module "
            "terminal marker found",
        )

    # 2) The tally, read from the identified runner's OWN authoritative line. A module
    #    log's captured output carries many bare `N passed, M failed` lines from the
    #    fixtures it drove; taking the last of those would report a nested sub-suite's
    #    verdict for the module.
    if module and not (aggregate or recombine or shard or runsh):
        passed_s, failed_s, skipped_s = module.group(2), module.group(3), module.group(4)
        tally_end = module.end()
    else:
        tallies = list(_RE_TALLY.finditer(text))
        if not tallies:
            raise RunnerLogError("runner_log_no_tally", f"no tally line in {path_str}")
        # The LAST bare tally is the terminal one: a coordinator log carries each shard's
        # tally before the recombined total, and the recombination is what the aggregate
        # covers.
        last = tallies[-1]
        passed_s, failed_s, skipped_s = last.group(1), last.group(2), last.group(3)
        tally_end = last.end()
    passed, failed = int(passed_s), int(failed_s)
    skipped_count = int(skipped_s) if skipped_s else 0

    # 3) The skip population, itemized POSITIONALLY from after the tally that announced
    #    it. A global scan collects the `  SKIP  ` lines a driven fixture printed earlier
    #    in the same capture, which are not this run's skips.
    skip_items = []
    for name in _RE_SKIP_LINE.findall(text[tally_end:]):
        tail = _RE_SKIP_TAIL.match(name)
        if tail:
            skip_items.append({"name": tail.group(1), "kind": tail.group(2),
                               "reason": tail.group(3)})
        else:
            skip_items.append({"name": name, "kind": "unparsed",
                               "reason": "derived from runner log"})
    if len(skip_items) < skipped_count:
        # The count is established but the itemization is short (a capped or truncated
        # log). Pad rather than drop: dropping would launder a skip into a clean pass.
        for i in range(len(skip_items), skipped_count):
            skip_items.append({"name": f"<unitemized skip {i + 1}>", "kind": "unparsed",
                               "reason": "counted in the runner tally, not itemized "
                                         "in the log"})
    elif len(skip_items) > skipped_count:
        # Itemization and tally disagree. Surface it as a member rather than silently
        # truncating to the count — this run's skip population is unverified.
        skip_items.append({
            "name": f"<tally/itemization disagreement: {len(skip_items)} itemized, "
                    f"{skipped_count} announced>",
            "kind": "unparsed",
            "reason": "the runner log's skip tally and its itemization disagree",
        })

    # 4) The result. For a coordinator the aggregate marker DECIDES it — a clean-looking
    #    tally under `aggregate FAILED` is the documented did-not-complete shard case.
    #    For the other runners the tally is the only verdict available.
    if aggregate:
        derived_result = "passed" if aggregate.group(1) == "CLEAN" else "failed"
        if derived_result == "passed" and failed > 0:
            # Do not let the marker override a failing tally in THIS direction. The
            # marker outranks the tally only to turn a clean-looking tally red (a
            # shard that did not complete); a real coordinator never prints CLEAN
            # beside a failing tally, so this shape is truncation or tampering —
            # the input this mode exists to distrust.
            raise RunnerLogError(
                "runner_log_aggregate_contradicts_tally",
                f"`aggregate CLEAN` beside a terminal tally reporting {failed} "
                f"failed in {path_str}",
            )
    else:
        derived_result = "failed" if failed > 0 else "passed"

    try:
        st = Path(path_str).stat()
        provenance = {"runner_log_size": st.st_size, "runner_log_mtime": int(st.st_mtime)}
    except OSError:
        provenance = {}

    summary = {
        "command": command,
        "exit_status": 0 if derived_result == "passed" else 1,
        "passed": passed,
        "failed": failed,
        "skipped_checks": skip_items,
        # Provenance: the reader can re-derive this summary from the same bytes.
        "runner_log": str(path_str),
        "evidence_source": "runner-log-derivation",
        **provenance,
    }
    elapsed = _RE_ELAPSED.search(text)
    if elapsed:
        summary["elapsed_s"] = int(elapsed.group(1))
    retained = _RE_RETAINED.search(text)
    if retained:
        summary["retained_logs"] = retained.group(1)
    return summary, skip_items, derived_result


def cmd_finish(args) -> int:
    state_dir = _state_dir(args.state_dir, args.logs_dir)
    path = _flight_path(state_dir, args.flight)
    flight, code, reason = _cas_load(path, args.token)
    if flight is None:
        _print({"ok": False, "result": "rejected", "reason": reason})
        return code
    if flight["state"] != "running":
        # A terminal handle is immutable; a claimed handle never skips running.
        _print({"ok": False, "result": "rejected", "reason": f"not_running:{flight['state']}"})
        return EXIT_CAS_REJECT

    summary = None
    skipped: list = []
    from_log = getattr(args, "from_runner_log", None)
    if from_log and args.summary_file:
        # Two evidence sources cannot both be authoritative; picking one silently
        # would hide which the record actually rests on.
        _print({"ok": False, "result": "rejected", "reason": "summary_source_ambiguous"})
        return EXIT_INVALID
    if from_log:
        try:
            summary, skipped, derived = derive_summary_from_runner_log(from_log)
        except RunnerLogError as exc:
            _print({"ok": False, "result": "rejected", "reason": exc.reason,
                    "detail": exc.detail})
            return EXIT_INVALID
        # The log's own verdict is the authority. A caller claiming a result the log
        # contradicts is refused NON-TERMINALLY, exactly like the exit-status
        # backstop: the flight stays running and re-finishable, so the truthful
        # `finish` can still land.
        if args.result not in ("passed", "failed"):
            # The log carries a verdict, so recording `timed_out`/`cancelled` beside a
            # derived `exit_status: 0` would write an internally contradictory record.
            _print({"ok": False, "result": "rejected",
                    "reason": "runner_log_result_not_a_verdict",
                    "declared_result": args.result,
                    "runner_log_result": derived,
                    "detail": "--from-runner-log requires --result passed or failed; "
                              "a run that did not complete has no runner log to derive"})
            return EXIT_INVALID
        if args.result != derived:
            _print({
                "ok": False, "result": "rejected",
                "reason": "runner_log_contradicts_result",
                "declared_result": args.result,
                "runner_log_result": derived,
                "runner_log": str(from_log),
                "state": "running",
                "satisfies_verification": False,
                "remedy": (
                    "retain this flight's owner token; the flight is left `running` "
                    "and re-finishable, so re-issue `finish` with the result the "
                    "runner log establishes"
                ),
            })
            return EXIT_CAS_REJECT
    elif args.summary_file:
        try:
            summary = _load_json_arg(args.summary_file)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            _print({"ok": False, "result": "rejected", "reason": f"summary:{exc.__class__.__name__}"})
            return EXIT_INVALID
        if isinstance(summary, dict) and isinstance(summary.get("skipped_checks"), list):
            skipped = summary["skipped_checks"]

    # Terminal evidence on a `passed`/`failed` result is not inferred as a clean
    # end from mere presence — the evidence gate is the one place the whole helper
    # decides a pass, so an *unusable* summary (a non-dict scalar/array, or an
    # empty object `{}` with no keys) is the same unknown class as an absent one
    # and must NOT be recorded as `passed`: it becomes `incomplete` and blocks any
    # automatic relaunch. THIS arm's gate is non-emptiness only: any object with at
    # least one key clears it. A `passed` result must additionally clear the
    # exit-status backstop below, which is a separate, non-terminal refusal.
    if args.result in ("passed", "failed") and not (isinstance(summary, dict) and summary):
        flight["state"] = "incomplete"
        flight["invalidation_reason"] = "missing_terminal_evidence"
        flight["finished_at"] = _iso(_now())
        werr = _ledger_write(path, flight)
        if werr:
            _print({"ok": False, "result": "write_failed", "reason": werr, "satisfies_verification": False})
            return EXIT_UNREADABLE
        _print({"ok": False, "result": "incomplete", "reason": "missing_terminal_evidence"})
        # Exit-code note: this reuses EXIT_CAS_REJECT rather than minting a code of
        # its own. The owner's transition WAS rejected, so the code is honest at the
        # "did my transition land?" granularity every shell caller gates on; callers
        # needing the finer distinction read the JSON `reason` field, which is
        # `missing_terminal_evidence` here and `token_mismatch` for a real ownership
        # failure. Documented deliberately so the overload is not read as an oversight.
        return EXIT_CAS_REJECT

    # ── #1053 exit-status backstop: the WRITE half of the completion gate's contract ──
    # Ordering is deliberate and load-bearing: the missing/unusable-summary arm above
    # runs FIRST and is unchanged, so this condition only ever sees a summary that is
    # already a non-empty object. It is a NECESSARY condition on the exit-status arm of
    # result establishment — the ledger executes nothing and observes nothing, so every
    # operand here is supplied by the same caller the gate exists to distrust. It
    # therefore NARROWS the false-green path rather than closing it: it catches a caller
    # holding a truthful nonzero status that still claims a pass, and does not catch one
    # that writes a zero it never observed.
    #
    # The refusal is NON-TERMINAL, and that is the whole point: it writes no state at
    # all, so the flight stays `running` and re-finishable and the run can still record
    # the truthful `finish --result failed` afterwards. A terminal write here would
    # permanently strand the very failure the gate exists to surface, because the ledger
    # is one-shot per key with no reclaim path.
    #
    # Accepted consequence, recorded rather than hidden: a `running` handle carries no
    # expiry by design, so an owner that never re-issues `finish` (e.g. its owner token
    # is no longer available) leaves the key `running` rather than terminal, and a
    # same-checkout attacher reaches the existing wait-expiry path instead of a prompt
    # terminal verdict. The exposure is bounded to an unchanged tree: any declared-input
    # change mints a fresh key.
    #
    # `failed`/`timed_out`/`cancelled` are untouched — a nonzero status is exactly what
    # a truthful `failed` carries, and the two owner-recorded outcomes carry no summary.
    if args.result == "passed" and not _zero_exit_status(summary):
        recorded = summary.get("exit_status")
        _print({
            "ok": False,
            "result": "rejected",
            # Two reasons, not one, so the diagnosis is attributable: an unestablished
            # status (absent, boolean, string, float) is a different defect from a
            # truthfully-recorded nonzero one, exactly as the reader distinguishes its
            # missing-evidence token from its not-pass token.
            "reason": (
                "exit_status_nonzero"
                if isinstance(recorded, int) and not isinstance(recorded, bool)
                else "exit_status_unestablished"
            ),
            "recorded_exit_status": recorded,
            "state": "running",
            "satisfies_verification": False,
            # The re-issue needs the SAME owner token this call used: no terminal state
            # was written, so the handle is still owned and still `running`.
            "remedy": (
                "retain this flight's owner token; the flight is left `running` and "
                "re-finishable, so re-issue `finish` with the truthful result"
            ),
        })
        return EXIT_CAS_REJECT

    now = _now()
    flight["state"] = args.result
    flight["result"] = args.result
    flight["finished_at"] = _iso(now)
    flight["finished_at_epoch"] = now
    flight["suite_summary"] = summary
    flight["skipped_checks"] = skipped
    running_epoch = flight.get("running_at_epoch")
    if isinstance(running_epoch, (int, float)):
        flight["command_duration_s"] = max(0.0, now - running_epoch)
    werr = _ledger_write(path, flight)
    if werr:
        _print({"ok": False, "result": "write_failed", "reason": werr, "satisfies_verification": False})
        return EXIT_UNREADABLE
    _emit_telemetry(
        args.logs_dir, "flight_finished",
        {
            "flight_key": args.flight,
            "terminal_state": args.result,
            "command_duration_s": flight.get("command_duration_s"),
            "skipped_checks_count": len(skipped),
        },
    )
    _print({"ok": True, "state": args.result, "flight_key": args.flight})
    return EXIT_OK


def _read_and_report(args) -> tuple[dict | None, int, str, bool]:
    state_dir = _state_dir(args.state_dir, args.logs_dir)
    path = _flight_path(state_dir, args.flight)
    current_checkout = None
    if getattr(args, "current_checkout_file", None):
        try:
            current_checkout = _validate_checkout(
                _load_json_arg(args.current_checkout_file)
            )
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            return None, EXIT_INVALID, f"current_checkout:{exc.__class__.__name__}", False
        except DeclarationError as exc:
            # Share the contract: validate the caller-supplied current checkout with
            # the SAME operation the stored checkout was validated by, so the two
            # accepted sets cannot drift. Without this, a valid-JSON-but-wrong-type
            # payload (array, scalar, missing fingerprint field) reached the drift
            # comparison unvalidated and was reported as `checkout_drift` — an
            # attributable-looking but WRONG cause for a malformed operand.
            return None, EXIT_INVALID, f"current_checkout:{exc.reason}", False
    try:
        flight = _read_flight(path)
    except ReadError as exc:
        return None, EXIT_UNREADABLE, exc.reason, False
    flight = _apply_read_transitions(path, flight, current_checkout, args.logs_dir)
    # checkout_verified: this read actually confirmed the working tree matches the
    # flight's recorded checkout. True only when a current checkout was supplied AND
    # it matched (a drift would already have flipped the handle to `stale`). A bare
    # `status`/`wait` with no `--current-checkout-file` leaves this False, so a
    # caller that requires `reuse_ready and checkout_verified` cannot consume a
    # `passed` handle whose tree it never verified (issue #579 review).
    checkout_verified = current_checkout is not None and flight.get("checkout") == current_checkout
    return flight, EXIT_OK, "", checkout_verified


def cmd_status(args) -> int:
    flight, code, reason, checkout_verified = _read_and_report(args)
    if flight is None:
        # Missing/unreadable/malformed shapes: attributable non-pass, never pass.
        _print({"ok": False, "result": "non_pass", "reason": reason, "satisfies_verification": False})
        # The `else EXIT_UNREADABLE` arm is an unreachable defensive floor, not live
        # logic: _read_and_report pairs a None flight only with EXIT_INVALID or
        # EXIT_UNREADABLE (its EXIT_OK return always carries a flight). It is kept so
        # that a future edit introducing a (None, EXIT_OK) path degrades to a non-pass
        # instead of returning success with no flight. No test can cover it by design.
        return code if code != EXIT_OK else EXIT_UNREADABLE
    # #1243: the checkout AND is enforced HERE (via _effective_pass), not left as a
    # caller obligation. A read that did not verify the working tree never reports a
    # pass or exits 0 unless --allow-unverified-checkout opted into the weaker read.
    effective = _effective_pass(flight, checkout_verified, args.allow_unverified_checkout)
    _print_public(
        flight, checkout_verified=checkout_verified,
        satisfies_verification=effective, reuse_ready=effective,
    )
    return EXIT_OK if effective else EXIT_NON_PASS


def cmd_wait(args) -> int:
    state_dir = _state_dir(args.state_dir, args.logs_dir)
    path = _flight_path(state_dir, args.flight)
    deadline = time.monotonic() + max(0.0, args.timeout)
    poll = max(0.0, args.poll_interval)
    current_checkout = None
    if args.current_checkout_file:
        try:
            current_checkout = _validate_checkout(
                _load_json_arg(args.current_checkout_file)
            )
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            _print({"ok": False, "result": "non_pass", "reason": f"current_checkout:{exc.__class__.__name__}", "satisfies_verification": False})
            return EXIT_INVALID
        except DeclarationError as exc:
            # Same share-the-contract guard as _read_and_report's — see the note there.
            _print({"ok": False, "result": "non_pass", "reason": f"current_checkout:{exc.reason}", "satisfies_verification": False})
            return EXIT_INVALID

    last_reason = "missing"
    while True:
        try:
            flight = _read_flight(path)
            flight = _apply_read_transitions(path, flight, current_checkout, args.logs_dir)
            if flight["state"] in TERMINAL_STATES:
                checkout_verified = (
                    current_checkout is not None
                    and flight.get("checkout") == current_checkout
                )
                # #1243 checkout AND — same enforcement as cmd_status, via the shared
                # _effective_pass: a terminal `passed` handle whose tree this wait could
                # not confirm is not a reusable pass unless --allow-unverified-checkout.
                effective = _effective_pass(
                    flight, checkout_verified, args.allow_unverified_checkout
                )
                _print_public(
                    flight, checkout_verified=checkout_verified,
                    satisfies_verification=effective, reuse_ready=effective,
                )
                _emit_telemetry(
                    args.logs_dir, "flight_wait_completed",
                    {"flight_key": args.flight, "terminal_state": flight["state"]},
                )
                return EXIT_OK if effective else EXIT_NON_PASS
            last_reason = f"active:{flight['state']}"
        except ReadError as exc:
            last_reason = exc.reason
        if time.monotonic() >= deadline:
            break
        # A caller-requested busy poll (--poll-interval 0) is floored to 50ms so the
        # loop never spins hot. Termination is the deadline check guarding this
        # sleep: the bound is tested before every sleep, so the overshoot is at most
        # one EFFECTIVE sleep — the caller's --poll-interval, or the 50ms floor when
        # that value is 0 (the floor can therefore exceed the value the caller asked
        # for, which is the point of flooring it).
        time.sleep(poll if poll > 0 else 0.05)

    # Wait bound elapsed with the flight still active/unreadable: a NON-mutating
    # observation. An active flight is left exactly as it was — the owner alone
    # records a terminal `timed_out` after its command reports a real timeout.
    _print({"ok": False, "result": "wait_expired", "reason": last_reason, "satisfies_verification": False})
    return EXIT_WAIT_EXPIRED


# ─────────────────────────────────────────────────────────────────────────────
# Phase-boundary event append (issue #1853)
# ─────────────────────────────────────────────────────────────────────────────
def cmd_event(args) -> int:
    """Append one clock-authored phase-boundary event to an append-only JSONL log.

    Always returns EXIT_OK: a failed write must never make a phase boundary
    blocking (an observability gap is strictly better than a run an instrumentation
    line can fail). The timestamp originates in this helper's own clock via
    _now()/_iso() — never supplied by the caller — reusing the {"event": …,
    "recorded_at": …} shape _emit_telemetry already writes.
    """
    record = {"event": args.name, "recorded_at": _iso(_now())}
    if args.payload:
        # Never reuse None as the parse-error sentinel: `--payload null` parses to None,
        # so it would skip the non-object breadcrumb this subcommand's contract promises
        # while the already-breadcrumbed parse-error path must not breadcrumb twice.
        unparseable = object()
        try:
            payload = json.loads(args.payload)
        except (json.JSONDecodeError, ValueError) as exc:
            print(
                f"devflow verification-flight event: ignoring unparseable --payload "
                f"for {args.name!r} ({exc.__class__.__name__}); recording the base event",
                file=sys.stderr,
            )
            payload = unparseable
        if isinstance(payload, dict):
            # event/recorded_at are the record's clock-authored identity; a payload
            # key must never shadow them, or the event's name/time would be caller-forged.
            for key, value in payload.items():
                if key not in ("event", "recorded_at"):
                    record[key] = value
        elif payload is not unparseable:
            print(
                f"devflow verification-flight event: ignoring non-object --payload "
                f"for {args.name!r}; recording the base event",
                file=sys.stderr,
            )
    base = Path(args.log_dir) if args.log_dir else Path.cwd() / PHASE_EVENTS_DIRNAME
    line = json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"
    try:
        base.mkdir(parents=True, exist_ok=True)
        # O_APPEND positions each write at EOF atomically, so concurrent runs sharing
        # a checkout append at distinct offsets rather than overwriting one another.
        fd = os.open(base / PHASE_EVENTS_FILENAME, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as exc:
        print(
            f"devflow verification-flight event: could not append phase event "
            f"{args.name!r} to {base} ({type(exc).__name__}: {exc}); the run continues",
            file=sys.stderr,
        )
    return EXIT_OK


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
class _FlightArgumentParser(argparse.ArgumentParser):
    """An ArgumentParser that reports a usage error as EXIT_INVALID, not exit 2.

    argparse's default usage-error status is 2, which is this CLI's documented
    EXIT_NON_PASS ("read succeeded but the flight does NOT satisfy verification").
    A shell caller branching on 2 would read a typo'd flag or an unknown subcommand
    as a successful read of a non-passing flight — the "unknown collapsed onto a
    real value" failure this repo treats as a first-class defect. A usage error is
    an invalid *argument*, so it exits EXIT_INVALID and emits the same JSON shape
    every other invalid path emits, keeping the `reason` field a caller is told to
    read actually present.
    """

    def error(self, message: str):
        _print({"ok": False, "result": "invalid",
                "reason": f"usage_error:{message}", "satisfies_verification": False})
        self.exit(EXIT_INVALID)


def build_parser() -> argparse.ArgumentParser:
    parser = _FlightArgumentParser(
        prog="verification-flight.py",
        description="Single-flight verification coordination ledger (issue #528). "
        "Data-only: launches no subprocess and accepts no executable argv.",
    )
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_FlightArgumentParser)

    def add_common(p):
        p.add_argument("--state-dir", default=None, help="Override the flight state directory (default: <cwd>/.prflow/tmp/verification-flights).")
        p.add_argument("--logs-dir", default=None, help="Override the telemetry logs directory.")

    def add_checkout_read_args(p):
        # Shared by `status` and `wait` so their checkout-read contract cannot drift.
        p.add_argument(
            "--current-checkout-file", default=None,
            help="A fresh checkout fingerprint for the CURRENT tree (produced by "
                 "scripts/checkout-fingerprint.py). Required for a pass: without it "
                 "`checkout_verified` is False and the helper reports non-pass / exits "
                 "non-zero, because a `passed` handle whose tree has since drifted must "
                 "not read as reusable (issues #528/#579/#1243).",
        )
        p.add_argument(
            "--allow-unverified-checkout", action="store_true",
            help="Explicit opt-in weaker read (issue #1243): report the state/exit "
                 "dimension alone (passed + zero exit) WITHOUT requiring the working "
                 "tree to be verified. For a caller that genuinely wants the weaker read; "
                 "a reuse decision must not use it.",
        )

    p_desc = sub.add_parser("descriptor", help="Print the descriptor digest + flight key for a declaration.")
    p_desc.add_argument("--input-file", required=True)
    add_common(p_desc)
    p_desc.set_defaults(func=cmd_descriptor)

    p_claim = sub.add_parser("claim", help="Atomically claim a flight or attach to a matching active one.")
    p_claim.add_argument("--input-file", required=True)
    p_claim.add_argument("--lease-seconds", type=int, default=None)
    add_common(p_claim)
    p_claim.set_defaults(func=cmd_claim)

    p_run = sub.add_parser("mark-running", help="Owner-only CAS: claimed -> running.")
    p_run.add_argument("--flight", required=True)
    p_run.add_argument("--token", required=True)
    p_run.add_argument("--evidence", default=None)
    add_common(p_run)
    p_run.set_defaults(func=cmd_mark_running)

    p_fin = sub.add_parser("finish", help="Owner-only CAS: running -> terminal with evidence.")
    p_fin.add_argument("--flight", required=True)
    p_fin.add_argument("--token", required=True)
    p_fin.add_argument("--result", required=True, choices=("passed", "failed", "timed_out", "cancelled"))
    p_fin.add_argument(
        "--summary-file", default=None,
        help="JSON object of terminal evidence. `--result passed` additionally requires a "
             "JSON integer 0 `exit_status`; anything else is refused non-terminally, "
             "leaving the flight running and re-finishable.",
    )
    p_fin.add_argument(
        "--from-runner-log", default=None,
        help="Derive the terminal evidence from a log a runner retained instead of "
             "hand-authoring a --summary-file. Pass the file each runner names on "
             "exit: run-parallel.sh's `retained coordinator log`, or run-shard.sh / "
             "run-module.sh's `retained log` / `Log:`. A capture you make yourself "
             "must MERGE stderr (2>&1) — the coordinator's `aggregate FAILED` verdict "
             "goes to stderr, and a stdout-only capture loses it. The log's own "
             "verdict decides the result: a --result the log contradicts is refused "
             "non-terminally. The log is not bound to this tree or this flight — only "
             "its path, size and mtime are recorded. Mutually exclusive with "
             "--summary-file.",
    )
    add_common(p_fin)
    p_fin.set_defaults(func=cmd_finish)

    p_stat = sub.add_parser("status", help="Read a flight; report whether it satisfies verification.")
    p_stat.add_argument("--flight", required=True)
    add_checkout_read_args(p_stat)
    add_common(p_stat)
    p_stat.set_defaults(func=cmd_status)

    p_event = sub.add_parser(
        "event",
        help="Append a clock-authored phase-boundary event to an append-only JSONL "
             "log under .prflow/logs/phase-events/; always exits 0.",
    )
    p_event.add_argument("name", help="The event name, e.g. simplify-start.")
    p_event.add_argument(
        "--payload", default=None,
        help="Optional JSON object merged into the record; the reserved keys "
             "'event' and 'recorded_at' are never overwritten.",
    )
    p_event.add_argument(
        "--log-dir", default=None,
        help="Override the phase-events log directory (default "
             "<cwd>/.prflow/logs/phase-events).",
    )
    p_event.set_defaults(func=cmd_event)

    p_wait = sub.add_parser(
        "wait",
        help="Bounded poll for a terminal state; never records a terminal result of "
             "its own (it does apply the read-time stale/incomplete invalidations).",
    )
    p_wait.add_argument("--flight", required=True)
    p_wait.add_argument("--timeout", type=float, required=True)
    p_wait.add_argument("--poll-interval", type=float, default=2.0)
    add_checkout_read_args(p_wait)
    add_common(p_wait)
    p_wait.set_defaults(func=cmd_wait)

    return parser


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
