#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""pretooluse-shape-guard.py — the review-tier PreToolUse command-shape guard (issue #805).

A DevFlow cloud review run that emits a command in a shape the harness matcher denies
gets a terse refusal and re-emits variants of the same denied shape instead of
switching (review run 30138268273: five `/tmp`-redirect denials, the last 228 events
after the first). Advisory prompt prose against exactly this has already been measured
failing. This guard is the compensating control that is NOT more prose: run as a
`PreToolUse` hook on the review tier, it reads the Bash tool payload on stdin and, for a
command any of whose statements matches a probe-proven denied shape, returns a `deny`
decision whose `permissionDecisionReason` names the permitted alternative for that shape
— delivered at the moment of the offending call, through the same tool-result channel
the harness's own refusal uses (`permissionDecisionReason` is "shown to Claude in the
tool result", per https://code.claude.com/docs/en/hooks).

REGISTRATION IS SHIPPED BUT UNREACHABLE HERE — not "unwired", and not dead code. One of
the two channels below has since landed: `.github/workflows/devflow-runner.yml` passes a
`settings` input registering a `PreToolUse`/`Bash` hook that execs this guard, alongside
its own step hardening the guard's trusted-source closure. The other has not — the
committed `.claude/settings.json` carries a `Stop` hook and no `PreToolUse` key — which is
what leaves the #458 relevance gate unarmed (see TRUST BOUNDARY below). What stops the
guard executing IN THIS REPOSITORY is therefore an unreachable registration rather than a
missing one: `devflow-runner.yml` declares `workflow_call` as its only trigger and nothing
in the tracked tree calls it, its sole caller having been the auto-review tier withheld
under issue #936. So the runtime behavior described below is read
here as the contract this file implements, not as something a run in this repository
exhibits — but NOT as dead code: the withheld tier and its helpers are deliberately
retained so the tier stays reconstructable and an already-installed consumer keeps working,
and such a consumer still has the caller this tree lacks, so the guard can be live on that
copy. Observed against `origin/main` when this paragraph was written; a caller landing
later falsifies "unreachable" with no edit here, so re-derive it rather than trust it.

THE WIRING QUESTION IS DECIDED: RETAINED-BUT-INERT (issue #1047). This guard is NOT wired
onto a live tier, and `devflow.yml` / `devflow-implement.yml` deliberately register no
`PreToolUse` hook — a property `lib/test/run.sh` pins on both. Do not "finish the wiring"
by adding one; that reverses a recorded decision. The rationale, what would reopen it, and
why deletion was refused are in docs/internal/cloud-allowlist.md under the guard's section
— the single source, of which this paragraph is only a pointer.

DENY SET (arms, not rule ids). The guard denies exactly `R1`, the `/tmp`-target arm of
R3 (`R3-tmp`), and `R4` — every `lib/test/extract-command-shapes.py` `REVIEW_RULES` arm
whose rule-table entry cites a probe row OR an observed run denial. `R2` (a leading
`cd`, DROPPED as unproven/confounded) and `R3-heredoc` (an in-workspace `cat`-heredoc
write, banned as authoring discipline, not a probe result) are EXCLUDED: a runtime deny
is terminal for the call, so denying an arm the harness would have permitted costs the
engine a working shape — the cost this issue exists to remove. Because that arm split
cannot be expressed at rule-id granularity (`classify()` returns the single token `R3`
for both arms), the guard resolves through that module's `classify_arms()` arm-level
classifier.

FAIL-OPEN, AND ITS ONE EXCLUSION. Every failure in the CLASSIFICATION path — an
unparseable payload, a dependency that cannot be loaded, any other internal exception —
resolves to NO DECISION: exit 0 with an EMPTY stdout, which is the documented way for a
`PreToolUse` hook to report nothing and let the normal permission flow decide ("Exit code
0 with no output means the hook has no decision to report, so the tool call continues
through the normal permission flow", https://code.claude.com/docs/en/hooks). A guard that
blocked on an unparsed payload would deny legitimate commands; a guard that exited
non-zero with no heartbeat would read to the workflow as the never-fired case for a guard
that in fact ran, destroying the distinguishability the heartbeat exists to provide.

THE FALL-THROUGH IS NOT `defer` — THAT WAS MEASURED WRONG (run 30967680822). Until this
change every fall-open path emitted `permissionDecision: "defer"`, on the belief that the
token means "fall through". The `defer-probe` arm of `.github/workflows/matcher-probe.yml`
measured the opposite on the CLI the action installs: `DEFER-BLOCKED` — the hook fired,
the granted command's side effect was ABSENT, so the tool did not execute — corroborated
by `STOP-REASON-DEFERRED` (the transcript carries `tool_deferred`). So on that harness
every one of this guard's "fail-open" paths was in fact fail-CLOSED, and a wired run would
have ended on the first command the guard did not recognize. The published decision-control
table calls `defer` equivalent to "exiting with code 0 and printing no JSON"; the
measurement contradicts that for the emitted-token form, and agrees with it for the
empty-stdout form. So the guard emits the shape both the documentation and the measurement
agree on — nothing at all — and never the token.

WHY THAT ALSO STRENGTHENS THE BOUND ON BLOCKING. The superseded prose argued the `defer`
majority path was load-bearing because the harness caps consecutive hook blocks. That
argument was unsound in both halves: `defer` was a block (see above), so the majority path
bounded nothing, and no evidence in this repository establishes such a cap in the first
place. The no-decision fall-through makes the bound REAL rather than assumed, and does so
without depending on the cap existing: a hook that reports no decision has not blocked
anything, so the majority path cannot count toward a consecutive-block cap if the harness
has one. Blocking is now confined to exactly the deny-set arms `_matched_arms` returns —
which is the property the bound was always meant to name.

The BOOKKEEPING writes are deliberately NOT on that fail-open path. A failed heartbeat
write, a failed counter write, an unavailable `fcntl`, or a lock the guard could not
acquire costs only the telemetry and the REPEAT escalation — never the decision: a
command already classified as a denied shape still returns `deny`. Un-excluded, an
unwritable `.prflow/tmp` silently disarmed the guard for a whole run. See the
`BOOKKEEPING NEVER DECIDES` comment in `_run` and the counter-write comment below it;
this exclusion is the contract those two comments implement, so do not "restore" a
uniform fail-open here.

DISARMED-RUN SIGNAL (issue #1077). The fail-open above means an unloadable classifier
resolves to no decision + exit 0 — byte-identical on every PUBLISHED artifact to a run that
fired and matched nothing, because the heartbeat says "fired" for both and stderr is
ephemeral. So when the classifier cannot be loaded (`_load_shapes_module`) OR exercised (a
renamed interface raising inside `_matched_arms`), `_run` writes a `_DISARMED` marker on the
SAME path as the heartbeat (best-effort telemetry, then re-raises so main()'s
fail-open-to-no-decision + stderr breadcrumb are unchanged). The marker's cause line is
keyed on the exception ACTUALLY raised — `FileNotFoundError` from `exec_module`, NOT the
unreachable `ImportError` spec branch — and names the workspace-relative path
`lib/test/extract-command-shapes.py`, giving "this tree has no lib/test" as the cause,
deliberately not the vendor slice's prune.

REPEAT BOUND. The load-bearing assumption (a per-call remediation changes behavior where
generic refusal did not) may fail, so the guard also carries a control: a second denial
of the same arm within one run escalates the remediation to name the abandonment rule
explicitly. The per-arm counts live in a store under `.prflow/tmp/` (each hook
invocation is a separate process) written under an exclusive lock, so parallel subagent
invocations cannot interleave and undercount. The store file is RUN-KEYED whenever the
environment supplies a run identifier (`GITHUB_RUN_ID`, then `GITHUB_RUN_ATTEMPT` — the
cloud review tier always does), which is what makes "within one run" true there even on a
reused workspace. With no run identifier in the environment — the local/interactive tier
— the store degrades to a single workspace-scoped file, so counts accumulate across
sessions on a persistent checkout and the escalation can fire on a later session's first
denial of an arm. That degradation costs an over-eager remediation suffix, never a
decision.

MEASURED: THE HARNESS'S `permissionDecision` VOCABULARY (run 30967680822). This block used
to say the vocabulary was an unresolved ASSUMPTION and point the reader at the
`pretooluse-probe` arm to settle it. That pointer was always wrong — that arm's hook emits
`allow`, so it can observe neither `deny` nor `defer` — and the question is now answered by
two arms purpose-built for it, both in run 30967680822 on branch `hook-probe-arms`:

  * `deny` IS HONORED, AND ITS REASON REACHES THE TRANSCRIPT (`pretooluse-deny-probe`,
    job 92185120507). `DENY-HONORED` — the hook took its deny arm and the sacrificial
    command's side effect was absent — with `CONTROL-RAN` confirming a non-matching command
    was left alone, and `REASON-DELIVERED` confirming the probe's `permissionDecisionReason`
    sentinel appears in the execution transcript. That is the whole delivery mechanism this
    guard's REMEDIATION table depends on, and it works.
  * `defer` BLOCKS THE TOOL AND ENDS THE PROCESS (`defer-probe`, job 92185120496).
    `DEFER-BLOCKED` / `STOP-REASON-DEFERRED`; see the fall-through section above, which is
    why this file emits no `defer` anywhere.
  * A HOOK-ISSUED DENY IS VISIBLE TO THE DENIAL COUNT, BUT WITHOUT ITS REASON TEXT
    (`pretooluse-deny-probe`). `COMMAND-RECORDED`: a `permission_denials` entry names the
    denied command. The reason text is NOT in that entry (the probe's own verdict cell reads
    `HOOK-DENY-NOT-RECORDED` because it searches the array for the reason sentinel, count 1).
    So a denial-count measurement sees that this guard fired; it cannot read back WHICH arm
    fired from that array alone — the per-arm store under `.prflow/tmp/` remains the only
    source for that.

VERDICT PROVENANCE AND EXPIRY. Both arms report `observed CLI version: 2.1.222`, and
`claude-code-action@v1` is a FLOATING tag that installs whatever CLI it currently pins — so
these verdicts are a measurement of one harness build, not a standing property, and an
action or CLI upgrade can expire any of them. Re-running the two arms is how they are
re-established after an upgrade, and since the `hook-probe-arms` branch landed (PR #1308)
that is actionable from this tree: `defer-probe` and `pretooluse-deny-probe` are jobs of
`.github/workflows/matcher-probe.yml`, beside the older `pretooluse-probe` (which emits
`allow` and can observe neither token). Two triggers reach them — a bare
`workflow_dispatch`, and a `pull_request` trigger whose `paths` filter is that workflow's
own file, so any same-repo pull request touching it re-probes automatically. BATCH A
RE-PROBE INTO ONE PUSH: neither trigger selects a job, so either one fires the whole
workflow — fifteen jobs when #1308 landed, fourteen of them starting a paid Claude session.
The workflow's `concurrency` group cancels a superseded run on the same ref, which reclaims
the unfinished remainder of an iterated push sequence but not what the cancelled sessions
already spent, nor the verdicts they never reached.

STILL OPEN. What the harness does with an UNRECOGNIZED `permissionDecision` token is still
unmeasured, and no local test can establish it — the answer lives in the harness, not here.
It no longer gates this file's design (the fall-through emits no token at all, so the only
token the guard ever writes is the measured-honored `deny`), but a future arm that adds a
third token would reopen it.

TRUST BOUNDARY (the contract registration satisfies). This file is inert unless its path is
in the trusted-base HOOK_TARGETS: the hook command the `settings` input registers points at
a path the #458 harden step has already displaced-or-stubbed from the base ref, so a
pull-request-head guard body never executes in the secrets-bearing review job. That half IS
shipped here — the path is in `HOOK_ENTRY_TARGETS` and `HOOK_TARGETS`. So is one of the two
registration channels: the action's `settings` input, the one that makes the guard
EFFECTIVE in a run. The other — a committed `.claude/settings.json` `PreToolUse` entry — is
not, and its job is narrower than making the guard work: it is what would ARM the #458
relevance gate (`--wired-check` substring-matches `HOOK_ENTRY_TARGETS` against the trusted
base settings), which therefore stays unarmed while only the `settings` channel is shipped.
An earlier revision of this paragraph concluded that both channels must land together,
since `settings` alone would run pull-request-editable guard code in a secrets-bearing job.
Issue #908 closed that hole from the other side instead: `devflow-runner.yml` carries a
dedicated `Harden PreToolUse guard closure (unconditional)` step, deliberately
unconditioned by the relevance gate, that always materializes a trusted base copy of the
guard's three-file import closure or stubs it inline, fail-closed. The channels need not
land together any more — but a registration added by any OTHER route still owes its own
hardening. See scripts/harden-stop-hooks.sh.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time

def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


# ── Arm → permitted-alternative remediation (issue #805) ──────────────────────
# This table is the guard's own named table; NO remediation text is composed at runtime,
# and it carries NO entry for an excluded arm (R2, R3-heredoc). The cloud allowlist
# evidence record is the AUTHORITATIVE record of each arm's permitted alternative and this
# table is its mirror — a lib/test/run.sh assertion ties each arm's ROW here to that record's table
# ROW for the same arm (both sides extracted by arm id, never whole-file substring tests:
# a whole-file test cannot distinguish the row it claims to pin from any other mention of
# the same literal, and would be inert). The JOIN LITERAL differs by arm and is NOT
# uniformly the alternative: R1 and R3-tmp each join on a whitespace-free fragment of
# their own permitted alternative, while R4 joins on its DENIED-SHAPE token instead,
# because R4's alternative is a whitespace-bearing English phrase that the issue-810
# boundary classifies as markdown prose on the docs side and so may not be pinned.
# Consequence: editing R4's alternative cell alone does NOT turn the suite RED — reconcile
# that one by hand.
REMEDIATION = {
    "R1": (
        "devflow shape guard (R1): a leading VAR=value assignment or env-prefix "
        "(M=x cmd) is denied by the review-tier matcher. Permitted alternative: "
        "capture a command's output with VAR=$(cmd), or pass the value as an argument "
        "to the command; do not prefix the command with VAR=value."
    ),
    "R3-tmp": (
        "devflow shape guard (R3-tmp): a >/>> redirect targeting /tmp is denied by the "
        "review-tier matcher. Permitted alternative: author the file with the Write tool "
        "under .prflow/tmp/, or stream through a pipe into tee; do not redirect to /tmp."
    ),
    "R4": (
        "devflow shape guard (R4): an interpreter head (python3/python/node) is granted "
        "by no review-tier profile. Permitted alternative: invoke the helper directly by "
        "its granted path as the command's leading token; do not prefix it with an "
        "interpreter."
    ),
}

# The arm identifiers this guard denies, DERIVED from REMEDIATION rather than re-typed:
# `REMEDIATION[arm]` is an unguarded subscript reached AFTER the deny is decided, so a
# deny-set arm with no remediation row would raise a KeyError that main()'s blanket
# handler converts into a no-decision fall-through — silently revoking an established
# deny. Deriving the set makes that disagreement unrepresentable. `sorted` also fixes the
# multi-match tie-break order (a command matching more than one deny-set arm emits the first-sorting
# arm's remediation), so the choice is deterministic across invocations rather than
# dependent on an unstated spelling.
DENY_ARMS = tuple(sorted(REMEDIATION))

# The escalation suffix for a SECOND denial of the same arm within one run: it names the
# abandonment rule explicitly for that arm. Appended to the base remediation above.
_ABANDON = (
    " REPEAT: this shape ({arm}) was already denied once this run. The two-denials rule "
    "applies — abandon this shape now and switch to the permitted alternative above; do "
    "not iterate variants of the denied shape (that is what exhausts the run's budget)."
)

_HEARTBEAT = "pretooluse-guard-fired"
# Written on the SAME path as the heartbeat when the shape classifier cannot be loaded, so
# a disarmed run is no longer byte-identical (on every published artifact) to one that fired
# and matched nothing (issue #1077). The heartbeat says "fired" for both; only this marker
# distinguishes "fired but could not classify" from "fired and classified, matched nothing".
_DISARMED = "pretooluse-guard-disarmed"
_SHAPES_REL = "lib/test/extract-command-shapes.py"
_COUNTS = "pretooluse-guard-counts.json"
_LOCK = "pretooluse-guard-counts.lock"
_LOCK_WAIT_SECONDS = 2.0  # bounded wait; on timeout, emit the decision without incrementing
# Upper bound on the `seen` idempotency map (issue #805 review). Every denied call's key is
# retained, which is bounded in practice on the cloud tier's fresh per-run workspace but
# unbounded on a persistent local checkout — the same asymmetry the counters carry. On
# overflow the OLDEST-inserted keys are dropped (json preserves insertion order), which
# costs at worst a re-count of a long-superseded call, never a decision.
_SEEN_MAX = 512


def _run_key() -> str | None:
    """A per-run identifier from the environment, or None when there is none.

    AC30 specifies a run-keyed store. The cloud review tier always supplies
    `GITHUB_RUN_ID` (plus `GITHUB_RUN_ATTEMPT`, so a re-run of the same workflow run does
    not inherit the prior attempt's counts), which is what makes the REPEAT bound's
    "within one run" true even on a workspace that is reused. The local/interactive tier
    supplies neither, so the store degrades to a single workspace-scoped file — see the
    module docstring's REPEAT BOUND note. Sanitized to a filename-safe alphabet with a
    bash-builtin-equivalent scan (never a PATH tool): a value that sanitizes to nothing is
    treated as absent rather than as an empty key."""
    run_id = os.environ.get("GITHUB_RUN_ID") or ""
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT") or ""
    raw = f"{run_id}-{attempt}" if attempt else run_id
    safe = "".join(ch for ch in raw if ch.isalnum() or ch in "._-")
    return safe or None


def _store_names() -> tuple[str, str]:
    """(counts filename, lock filename) for this run — run-keyed when a run key exists."""
    key = _run_key()
    if not key:
        return (_COUNTS, _LOCK)
    return (f"pretooluse-guard-counts-{key}.json", f"pretooluse-guard-counts-{key}.lock")


def _seen_key(tool_use_id: str | None, arm: str, command: str) -> str:
    """The idempotency key for this denial.

    `tool_use_id` when the payload carried one. When it did NOT, fall back to a
    content-derived key over (arm, command) rather than skipping idempotency entirely:
    without a fallback, a payload with no `tool_use_id` increments on EVERY invocation, so
    a re-fired hook escalates on the engine's FIRST offending command — precisely the
    branch where the escalation control is least trustworthy. The fallback is coarser
    (two genuinely distinct calls emitting the identical command on the same arm count
    once), which errs toward under-counting a repeat rather than inventing one."""
    if tool_use_id:
        return tool_use_id
    digest = hashlib.sha256(f"{arm}\0{command}".encode("utf-8", "replace")).hexdigest()
    return f"cmd:{digest[:32]}"


def _repo_root() -> str:
    """The repository root, NOT the process working directory (a hook's cwd is not
    guaranteed). Mirrors scripts/stop-hook-probe.sh: git toplevel, else cwd."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        root = out.stdout.strip()
        if out.returncode == 0 and root:
            return root
    except Exception:
        pass
    return os.getcwd()


def _tmp_dir(root: str) -> str:
    d = os.path.join(root, ".prflow", "tmp")
    os.makedirs(d, exist_ok=True)
    return d


def _decision_object(permission_decision: str, reason: str | None) -> dict:
    out: dict = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": permission_decision,
        }
    }
    if reason is not None:
        out["hookSpecificOutput"]["permissionDecisionReason"] = reason
    return out


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj))
    sys.stdout.write("\n")


def _emit_no_decision() -> None:
    """The fall-through: report NO decision, so the normal permission flow decides.

    Deliberately writes NOTHING. This is the documented no-decision shape ("Exit code 0
    with no output means the hook has no decision to report") and, per run 30967680822, the
    only one that actually falls through on the CLI `claude-code-action@v1` installs — an
    emitted `permissionDecision: "defer"` was measured BLOCKING the tool and ending the
    process (`DEFER-BLOCKED` / `STOP-REASON-DEFERRED`). See the module docstring.

    It exists as a named function rather than a bare `return` at each site so the
    fall-through is one greppable, single-sourced shape: each fail-open site routes here,
    the calls to it are the guard's whole fail-open surface, and a future edit that
    reintroduces an emitted token at one of them is visible as a call that stopped being
    this one. (Deliberately count-free: an ordinal here would rot on the next edit that
    adds or removes a fail-open site.)"""
    return


def _load_shapes_module():
    """Load lib/test/extract-command-shapes.py by its committed relative position.

    The module's filename carries hyphens, so it is loaded through the
    `importlib.util.spec_from_file_location` idiom its existing consumers use — which is
    the guard's own dependency edge that scripts/detect-hook-closure-edges.py must model
    (both this file and lib/test/extract-command-shapes.py, plus the extract-command-
    heads.py it loads in turn, are in the trusted-base HOOK_TARGETS closure)."""
    root = _repo_root()
    # Keep the quoted basename literal INSIDE os.path.join so scripts/detect-hook-closure-edges.py
    # (the #458/#805 drift-guard) can statically capture this importlib edge — do not refactor it
    # into a variable/split composition (that made the edge invisible and the guard fail closed).
    path = os.path.join(root, "lib", "test", "extract-command-shapes.py")
    spec = importlib.util.spec_from_file_location("devflow_extract_command_shapes", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"devflow: cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _matched_arms(command: str, shapes) -> set[str]:
    """The deny-set arms any statement of `command` matches."""
    matched: set[str] = set()
    for statement in shapes._statements(command):
        for arm in shapes.classify_arms(statement):
            if arm in DENY_ARMS:
                matched.add(arm)
    return matched


def _write_heartbeat(tmp: str) -> None:
    with open(os.path.join(tmp, _HEARTBEAT), "w", encoding="utf-8") as fh:
        fh.write("fired\n")


def _disarm_detail(exc: BaseException) -> str:
    """The cause line for a disarmed run, keyed on the exception ACTUALLY raised.

    When the classifier file is simply not on disk, `spec_from_file_location` still returns a
    valid spec for a `.py` path and `exec_module` raises `FileNotFoundError` — NOT
    `ImportError` (that branch is unreachable for this path shape), which is why the detection
    is keyed on the real exception and this arm names the workspace-relative cause. The
    absence is because the composed path is workspace-relative and the tree has no
    `lib/test/` — deliberately NOT attributed to the vendor slice's prune (issue #1077)."""
    if isinstance(exc, FileNotFoundError):
        # exec_module RUNS the classifier, which imports extract-command-heads.py in turn, so
        # a FileNotFoundError can originate from a transitively-imported sibling rather than
        # the classifier file itself. Only assert the "no lib/test" cause when the missing
        # file IS the classifier path — otherwise name the actual missing file so the marker
        # never steers an operator to the wrong cause.
        missing = getattr(exc, "filename", "") or ""
        if not missing or missing.endswith("extract-command-shapes.py"):
            return (
                f"the shape classifier at the workspace-relative path {_SHAPES_REL} is not on "
                f"disk (FileNotFoundError) — the composed path is workspace-relative and this "
                f"tree has no lib/test"
            )
        return (
            f"the shape classifier {_SHAPES_REL} could not be loaded — a file it imports "
            f"({missing}) is not on disk (FileNotFoundError)"
        )
    return (
        f"the shape classifier at the workspace-relative path {_SHAPES_REL} could not be "
        f"loaded or did not classify ({type(exc).__name__}: {exc})"
    )


def _note_disarm(tmp: str | None, exc: BaseException) -> None:
    """Publish the distinguishing disarmed-run signal on the heartbeat path (best-effort).

    Telemetry, so a failure here never changes the decision — the caller re-raises to main()'s
    fail-open-to-no-decision handler regardless. When the heartbeat itself could not be
    written (`tmp is None`) there is no directory to publish into; stderr (from main()) remains the
    only signal, exactly as before this marker existed."""
    detail = _disarm_detail(exc)
    if tmp is not None:
        try:
            with open(os.path.join(tmp, _DISARMED), "w", encoding="utf-8") as fh:
                fh.write(
                    "pretooluse-shape-guard DISARMED: "
                    f"{detail}; no command was classified this run. This marker sits beside "
                    "the heartbeat so a disarmed run is distinguishable from one that fired "
                    "and matched nothing.\n"
                )
        except Exception:  # noqa: BLE001 - telemetry must never decide
            pass


def _clear_disarm(tmp: str | None) -> None:
    """Remove any stale disarmed-run marker (best-effort), so the signal reflects THIS run
    rather than a prior disarmed one on a persistent checkout. Called up front on every run,
    so every non-disarm exit retracts the marker; a run that disarms re-writes it."""
    if tmp is None:
        return
    try:
        os.remove(os.path.join(tmp, _DISARMED))
    except Exception:  # noqa: BLE001 - telemetry on the decision path must never decide
        # `os.remove(str)` realistically raises only OSError (FileNotFoundError included — the
        # benign "no stale marker" case), but this call sits on the SUCCESS/decision path, so
        # a broad catch keeps it aligned with the file's "BOOKKEEPING NEVER DECIDES" contract:
        # no cleanup failure may propagate into main() and flip a real deny into a
        # fall-through.
        pass


def _read_command(payload) -> str | None:
    """The Bash command string, or None for any shape the guard cannot classify.

    Every None path is a fail-open route to the NO-DECISION fall-through (exit 0, empty
    stdout): valid JSON that is not an object, an object whose `tool_name` is not `Bash`, an
    object with no `tool_input`, a `tool_input` that is not an object, or an object with no
    `command` string. The `tool_name` check is
    defense-in-depth: this guard is registered for `Bash` today, but any non-`Bash` tool
    whose input happens to carry a `command`-shaped string field must not be classified as
    a shell command if the matcher is ever registered more broadly."""
    if not isinstance(payload, dict):
        return None
    if payload.get("tool_name") != "Bash":
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    command = tool_input.get("command")
    if not isinstance(command, str):
        return None
    return command


def _bump_counts(tmp: str, arm: str, seen_key: str) -> tuple[bool, bool]:
    """Under an exclusive lock, record one denial of `arm` in the store (run-keyed where
    the environment supplies a run id — see `_run_key` and the module docstring's REPEAT
    BOUND note) and return `(escalated, incremented)`.

    - Idempotent across duplicate registration: a `seen_key` already recorded returns its
      stored `escalated` verdict WITHOUT incrementing the per-arm counter a second time
      (so a double-fired guard cannot double the counter or fire the escalation on the
      engine's first offending command).
    - `escalated` is True on the SECOND (or later) distinct denial of the same arm.
    - A lock that cannot be acquired within the bounded wait returns `(False, False)` with
      a stderr breadcrumb — the guard emits its (base) decision WITHOUT incrementing
      rather than blocking the tool call.

    THE STORE IS A BEST-EFFORT PARSER over an agent-writable path, so the whole-file shape
    AND every field it reads back are shape-checked, and a shape it cannot trust fails
    toward ESCALATING rather than toward resetting: a corrupt counter that silently
    restarts at 1 disarms the escalation for the rest of the run, while an over-eager
    escalation costs only an extra sentence of remediation text. An ABSENT store is the one
    shape that starts fresh silently — that is the genuine first call of a run, not
    corruption — while an unreadable, non-JSON, non-object, or structurally malformed store
    breadcrumbs and escalates.

    `fcntl` is imported lazily so a platform without it raises HERE — inside the call the
    caller wraps — rather than at module import. Per the module docstring's fail-open
    exclusion, the caller converts that into "no escalation", NOT into a fall-through: a
    command already classified as a denied shape is still denied on a platform with no
    `fcntl`."""
    import fcntl

    counts_name, lock_name = _store_names()
    lock_path = os.path.join(tmp, lock_name)
    store_path = os.path.join(tmp, counts_name)
    lock_fh = open(lock_path, "w", encoding="utf-8")
    try:
        deadline = time.monotonic() + _LOCK_WAIT_SECONDS
        acquired = False
        while True:
            try:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.02)
        if not acquired:
            # Breadcrumb, not silence: under exactly the contention this lock exists for,
            # the escalation control is disarmed for this call, and without a named signal
            # a run whose repeats never escalate is indistinguishable from one with none.
            sys.stderr.write(
                "devflow: pretooluse-shape-guard: denial-counter lock not acquired within "
                f"{_LOCK_WAIT_SECONDS}s ('{store_path}'); emitting the base remediation for "
                f"{arm} without escalation\n"
            )
            return (False, False)
        store: dict = {"arms": {}, "seen": {}}
        # ABSENT is not MALFORMED. An absent store is the genuine first call of a run and
        # starts fresh silently. A store that EXISTS but cannot be read back structurally
        # (unreadable file, non-JSON bytes, a JSON non-object, or an `arms`/`seen` member
        # that is not an object) is corrupt: starting fresh there would silently reset
        # every arm to zero and disarm the repeat-escalation for the rest of the run, which
        # is the less-safe direction the field-level shape checks below deliberately avoid.
        # So corruption takes the SAME posture as a corrupt per-arm count — treat it as at
        # least one prior denial, and say so — rather than the absent case's silent reset.
        store_corrupt = False
        try:
            with open(store_path, encoding="utf-8") as fh:
                loaded = json.load(fh)
        except FileNotFoundError:
            loaded = None  # genuine first call for this run — start fresh, no breadcrumb
        except (OSError, ValueError) as exc:
            loaded = None
            store_corrupt = True
            sys.stderr.write(
                "devflow: pretooluse-shape-guard: denial-counter store "
                f"('{store_path}') exists but could not be read back "
                f"({type(exc).__name__}); treating every arm as having at least one prior "
                "denial rather than resetting the escalation\n"
            )
        if loaded is not None:
            if not isinstance(loaded, dict):
                store_corrupt = True
            else:
                for member in ("arms", "seen"):
                    value = loaded.get(member)
                    if isinstance(value, dict):
                        store[member] = value
                    elif value is not None:
                        store_corrupt = True
            if store_corrupt:
                sys.stderr.write(
                    "devflow: pretooluse-shape-guard: denial-counter store "
                    f"('{store_path}') is structurally malformed; treating every arm as "
                    "having at least one prior denial rather than resetting the escalation\n"
                )
        prior = store["seen"].get(seen_key)
        if prior is not None:
            escalated = bool(prior.get("escalated")) if isinstance(prior, dict) else False
            return (escalated, False)
        raw = store["arms"].get(arm, 0)
        # `bool` is an `int` subclass, so `isinstance(True, int)` is True and an injected
        # `true` would read as the count 1 and escalate on the FIRST denial. Exclude it
        # explicitly, and treat every other non-int (a string "9", a float, a list) as a
        # corrupt count meaning "at least one prior denial" rather than as a reset to 1.
        if store_corrupt or isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            if raw != 0 and not store_corrupt:
                # The corrupt-store breadcrumb was already emitted above; do not repeat it
                # per arm. Only the field-level corruption needs its own named signal here.
                sys.stderr.write(
                    "devflow: pretooluse-shape-guard: denial counter for "
                    f"{arm} is not a non-negative int ({type(raw).__name__}); treating it "
                    "as at least one prior denial rather than resetting the escalation\n"
                )
            current = 2
        else:
            current = raw + 1
        store["arms"][arm] = current
        escalated = current >= 2
        # Only `escalated` is ever read back (see the `prior.get("escalated")` read
        # above) — no other field of a `seen` entry is consumed, so none is stored.
        store["seen"][seen_key] = {"escalated": escalated}
        if len(store["seen"]) > _SEEN_MAX:
            # Drop the oldest-inserted keys (json round-trips insertion order).
            for stale in list(store["seen"])[: len(store["seen"]) - _SEEN_MAX]:
                del store["seen"][stale]
        # PERSISTENCE FAILURE MUST NOT SWALLOW AN ALREADY-COMPUTED ESCALATION. The verdict
        # above was decided from the state actually read back; letting an unwritable store
        # (a read-only mount, a 0o000 store file, a full disk) propagate out would hand the
        # caller "no escalation" — the same silent disarm the corrupt-store arm exists to
        # stop, and reached by exactly the shapes that produce a corrupt store in the first
        # place. So the write failure costs only PERSISTENCE, is named on stderr, and
        # reports `incremented=False` so no caller records a count that was never stored.
        try:
            with open(store_path, "w", encoding="utf-8") as fh:
                json.dump(store, fh)
        except OSError as exc:
            sys.stderr.write(
                "devflow: pretooluse-shape-guard: denial-counter store "
                f"('{store_path}') could not be written back ({type(exc).__name__}); the "
                f"escalation verdict for {arm} still stands but was not persisted\n"
            )
            return (escalated, False)
        return (escalated, True)
    finally:
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        lock_fh.close()


def _run() -> None:
    # BOOKKEEPING NEVER DECIDES. The heartbeat and the counter store are telemetry; a
    # failure in either must not change the decision. Un-guarded, an unwritable
    # .prflow/tmp raised here — BEFORE any classification — and main()'s blanket handler
    # turned it into a fall-through, silently disarming the guard for the whole run. So the
    # store is best-effort and `tmp is None` simply means "classify, do not count".
    root = _repo_root()
    try:
        tmp = _tmp_dir(root)
        # Every invocation, including a fall-through — this is the never-fired signal.
        _write_heartbeat(tmp)
    except Exception as exc:  # noqa: BLE001 - telemetry must never decide
        sys.stderr.write(
            "devflow: pretooluse-shape-guard: heartbeat/store unavailable "
            f"({type(exc).__name__}: {exc}); classifying anyway, denials go uncounted\n"
        )
        tmp = None

    # Clear any stale disarmed-run marker up front, so EVERY non-disarm exit (the benign
    # early fall-through paths below AND a clean armed classify) retracts a prior run's marker on a
    # persistent checkout — a run that actually disarms re-writes it via _note_disarm. (When
    # the heartbeat failed, tmp is None and there is nothing to clear; stderr stays the only
    # signal, as documented.)
    _clear_disarm(tmp)

    raw = sys.stdin.buffer.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        _emit_no_decision()
        return
    if not text.strip():
        _emit_no_decision()
        return
    try:
        payload = json.loads(text)
    except ValueError:
        _emit_no_decision()
        return

    command = _read_command(payload)
    if command is None:
        _emit_no_decision()
        return

    tool_use_id = payload.get("tool_use_id") if isinstance(payload, dict) else None
    if not isinstance(tool_use_id, str) or not tool_use_id:
        tool_use_id = None

    try:
        # Both the load AND the classification are disarm paths: a classifier that is absent
        # or unloadable raises here, and one that loads but no longer exposes the expected
        # interface (a renamed symbol) raises inside _matched_arms — both leave the run unable
        # to classify while the heartbeat still says "fired". Publish the distinguishing signal
        # on the heartbeat path (issue #1077), then re-raise so main() fails OPEN to a
        # no-decision with its stderr breadcrumb, unchanged. The decision is untouched; the
        # only new thing is that the disarm is now visible in a published artifact, not just
        # in ephemeral stderr.
        shapes = _load_shapes_module()
        matched = _matched_arms(command, shapes)
    except BaseException as exc:  # noqa: BLE001 - telemetry write then re-raise; never decides
        _note_disarm(tmp, exc)
        raise
    if not matched:
        _emit_no_decision()
        return

    # Deterministic tie-break: the first-sorting matched deny-set arm.
    arm = sorted(matched)[0]
    # The deny is already decided; counting it is telemetry. A store write that raises
    # must cost the ESCALATION, never the decision — an obstructed counts file used to
    # revoke an established deny and fall through with no signal at all.
    escalated = False
    if tmp is not None:
        try:
            escalated, _incremented = _bump_counts(
                tmp, arm, _seen_key(tool_use_id, arm, command)
            )
        except Exception as exc:  # noqa: BLE001 - telemetry must never decide
            sys.stderr.write(
                "devflow: pretooluse-shape-guard: denial counter write failed "
                f"({type(exc).__name__}: {exc}); emitting the base remediation for "
                f"{arm} without escalation\n"
            )
    reason = REMEDIATION[arm]
    if escalated:
        reason = reason + _ABANDON.format(arm=arm)
    _emit(_decision_object("deny", reason))


def main() -> int:
    # Catch EVERY exception (BaseException, so a stubbed dependency's SystemExit at import
    # cannot escape) and fail open to a NO-DECISION. An uncaught internal error would exit
    # non-zero, and a non-zero PreToolUse exit is a BLOCK, not a fall-through — the exact
    # inversion the emitted-`defer` fall-through turned out to be (run 30967680822). Exit 0
    # is therefore load-bearing here, and the empty stdout is what makes it a no-decision.
    # The heartbeat is best-effort inside _run and is itself covered here.
    _force_utf8_streams()
    try:
        _run()
    except BaseException as exc:
        # Name the failure on stderr. Without it a fully disarmed guard (a bash-stubbed
        # importlib dependency raising SyntaxError, a renamed shapes symbol, a wrong
        # repo root) is byte-identical on stdout to a clean run that matched nothing,
        # and the heartbeat says "fired" for both — so the only signal the operator
        # would have is the denied shapes reappearing.
        try:
            sys.stderr.write(
                "devflow: pretooluse-shape-guard: failed open to no decision "
                f"({type(exc).__name__}: {exc}) — this command was NOT classified\n"
            )
        except Exception:
            pass
        # Emit NOTHING. This arm can also be reached AFTER _run's own `_emit` began writing
        # a deny — appending a second object there would have made stdout unparseable JSON;
        # writing nothing leaves whatever _run managed to write as the only content.
        _emit_no_decision()
    return 0


if __name__ == "__main__":
    sys.exit(main())
