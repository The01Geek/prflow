#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Behavioral eval for the runtime main-thread context cost of /prflow:implement.

This is a maintainer/CI-adjacent instrument. No skill, workflow, or suite gate invokes
it for a measurement or a threshold; the only automated execution is its own focused
unit test (lib/test/test_implement_context_eval.py), which asserts parser behavior. It
walks a supplied Claude Code transcript directory and measures the *runtime main-thread
context* a `/prflow:implement` run accumulates from its session transcripts — a distinct
quantity from the static shipped byte count of the phase files on disk (see
docs/internal/implement-context.md).

It is the implement-side sibling of scripts/create-issue-context-eval.py (issue #767),
and reuses that instrument's proven streaming / per-record degradation / symlink-escape
/ determinism design. It deliberately drops the create-issue-only machinery (audit-round
attribution, redundant-Read / re-emission metrics, paired before/after mode); the four
axes it measures are the ones the implement skill's cost shape is dominated by
(issue #1209):

  1. **Peak main-thread context per run** — the same per-turn sum the create-issue
     instrument uses: `input_tokens + cache_read_input_tokens +
     cache_creation_input_tokens` over the main-thread (non-`isSidechain`) attributed
     assistant records. This is the residency cost a long implement run pays.

  2. **How many times each of the four phase files was read in a run** — the multiplier
     issue #1209 identifies as the cost shape actually worth measuring. The phase files
     are loaded one per phase ENTRY (not all four at once), and each is re-Read "each
     time you (re-)enter this phase" and after every nested-skill return, so the re-read
     COUNT — not the one-time byte size — is what a run's phase-file cost is driven by.
     This axis is reported SEPARATELY from the peak, because they are different
     quantities (issue #1209 AC2).

  3. **Main-thread tool calls, bucketed by category** — file reads, file edits/writes,
     shell commands, subagent dispatches, skill invocations, and an `other` catch-all so
     the buckets sum to the run's whole tool-call population. A turn count alone
     mis-attributes the work: one assistant turn can carry several tool calls, so a run
     that batches its calls looks cheaper than one that does not while doing the same
     work (issue #1209 AC10).

  4. **The distribution of wall-clock gaps between consecutive main-thread tool calls** —
     median, maximum and total, never a mean alone, because a mean hides the tail that
     dominates a long run. A tool-bearing main-thread turn carrying no usable timestamp
     is counted in the `skipped` accounting under `unusable_timestamp` and NEVER
     contributes a zero gap (issue #1209 AC11; `CLAUDE.md`'s *unknown is not zero* rule).

     **Disclosed proxy — the gaps are measured at TURN granularity, not per call.** A
     transcript record carries ONE `timestamp` however many `tool_use` blocks its turn
     holds, so a per-call gap is not observable from this data at all. What is measured
     is the gap between consecutive main-thread turns that issued at least one tool
     call: a turn batching four calls contributes one point, not four, and the three
     intra-turn intervals are not in the population. Read `total_seconds /
     total_tool_calls` as meaningless for that reason. This is a disclosed proxy in the
     same sense as the cross-session bound below, not an unstated approximation.

Axes 3 and 4 are reported per run AND aggregated across the corpus, on the same footing
as the peak-context aggregate (issue #1209 AC12). None of the four introduces a gate,
ceiling, threshold, or budget — they are instrument outputs.

A "run" is bounded by `attributionSkill` matching any declared `<ns>:implement` on
`type == "assistant"` records. Only a **main-thread** (non-`isSidechain`) attributed
assistant record contributes to the residency axis and to the phase-read count — the
phase files are read by the orchestrator on the main thread, never by a dispatched
subagent. One session JSONL file that contains at least one main-thread attributed
assistant record yields one run; a run that RESUMES into a separate session file is
reported as its own run (cross-session merging is out of scope, a disclosed proxy).

Per-record token usage is read from `message.usage.{input_tokens,
cache_read_input_tokens, cache_creation_input_tokens}`. A turn establishing none of
those (no usage object, or one carrying only absent, null, or non-finite counts) is an
unmeasured turn: it is tallied in `usage_missing_turns` and excluded from the peak, never folded in
as a real-looking 0 (issue #1899). Compaction is observed as `type == "system",
subtype == "compact_boundary"` and only counted.

A phase-file read is a `Read` tool_use block whose `input.file_path` BASENAME is one of
the four phase file names. Matching on the basename (not a full path) is deliberate: the
skill anchors the read at `<skill-dir>/phases/phase-N-<name>.md`, which resolves to a
local `skills/implement/phases/…` path on the interactive tier and a vendored
`.prflow/vendor/prflow/skills/implement/phases/…` path on the cloud tier — the basename
is the one component stable across both.

The parser streams records line by line (it never buffers an entire session into
memory) and degrades per malformed record without detonating, reporting how many
records it skipped and why. It is deterministic: re-running over the same corpus
yields byte-identical output. It writes NO transcript contents and embeds no
owner-specific identifiers.

Usage:
    implement-context-eval.py <transcript-dir>
                              [--format {text,json}]
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import math
import os
import sys

# A run is bounded by `attributionSkill`, which carries the LIVE plugin namespace. That
# namespace is renameable, and historical census rows keep whatever namespace was live
# when they were written — so this must accept EVERY declared namespace, not one literal.
# A single hardcoded id silently matches nothing after a rename (every new run rejected,
# the eval reporting zero runs with no error). Derived from the same identity source the
# rest of the repo single-sources (mirrors scripts/create-issue-context-eval.py).
_IDENTITY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "plugin_identity.py"
)
# The fallback set used when the identity source cannot be resolved. It carries BOTH the
# canonical spelling and its superseded predecessor: a fallback naming only the
# superseded id would match nothing in a corpus of current transcripts and report the
# same vacuous zero-run measurement an EMPTY set would — the failure this fallback
# exists to prevent, reintroduced by the fallback itself.
_FALLBACK_ATTRIBUTION = ("prflow:implement", "devflow:implement")


def _attribution_ids():
    """Every accepted `<namespace>:implement` attribution id, canonical first.

    Falls back to `_FALLBACK_ATTRIBUTION` rather than an EMPTY set: an empty set would
    make every record mismatch and report a vacuous zero-run measurement, which is
    exactly the silent failure this function exists to prevent. The fallback is a
    hardcoded pair and therefore CANNOT cover a namespace introduced after this line was
    written — a corpus recorded under such a namespace still reports zero runs on this
    path, which is why the fallback always breadcrumbs to stderr.
    """
    spec = importlib.util.spec_from_file_location("plugin_identity", _IDENTITY_PATH)
    if spec is None or spec.loader is None:
        print(
            f"implement-context-eval: identity source {_IDENTITY_PATH} is not "
            "importable; falling back to the hardcoded attribution pair "
            f"{_FALLBACK_ATTRIBUTION} — a run recorded under any other namespace will "
            "not be attributed and this corpus may report zero runs",
            file=sys.stderr,
        )
        return _FALLBACK_ATTRIBUTION
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        ids = tuple(ns + "implement" for ns in module.agent_namespaces())
        # The concatenation assumes `agent_namespaces()` returns COLON-TERMINATED
        # namespaces. That is a cross-module shape contract, and the success path is the
        # one path that always executes — if the contract changed, `ids` would be
        # non-empty (so the emptiness guard below never fires), every record would
        # mismatch, and the eval would report zero runs with no error: the exact silent
        # failure this whole apparatus exists to prevent, reached by a different route.
        malformed = [i for i in ids if not i.endswith(":implement")]
        if malformed:
            print(
                "implement-context-eval: the declared namespace set yielded malformed "
                "attribution id(s) {} (expected `<namespace>:implement`); falling back "
                "to the hardcoded attribution pair {}".format(
                    malformed, _FALLBACK_ATTRIBUTION),
                file=sys.stderr,
            )
            return _FALLBACK_ATTRIBUTION
    except Exception as exc:  # noqa: BLE001 - lib/plugin_identity.py is FAIL-CLOSED and
        # raises IdentityError when the identifier set cannot be established (an absent or
        # malformed .claude-plugin/plugin.json or lib/plugin-identity.json — a vendored or
        # partial-slice tree, a mid-migration checkout). Without this arm that exception
        # propagates out of the module-level ATTRIBUTION assignment below, so the fallback
        # this function documents would be unreachable on its likeliest failure and even
        # `--help` would die with a traceback. Catch broadly and breadcrumb the cause: the
        # exception type is the identity module's to choose, not this instrument's.
        print(
            "implement-context-eval: could not resolve the declared namespace set from "
            "{} ({}: {}); falling back to the hardcoded attribution pair {} — a run "
            "recorded under any other namespace will not be attributed and this corpus "
            "may report zero runs".format(
                _IDENTITY_PATH, type(exc).__name__, exc, _FALLBACK_ATTRIBUTION),
            file=sys.stderr,
        )
        return _FALLBACK_ATTRIBUTION
    if not ids:
        print(
            "implement-context-eval: the declared namespace set is empty; falling "
            "back to the hardcoded attribution pair {} — a run recorded under any "
            "other namespace will not be attributed and this corpus may report zero "
            "runs".format(_FALLBACK_ATTRIBUTION),
            file=sys.stderr,
        )
        return _FALLBACK_ATTRIBUTION
    return ids


ATTRIBUTION = _attribution_ids()

# The four phase files whose per-run read count issue #1209 measures. The mapping is
# basename -> the short label the report keys the count on. A phase file renamed on disk
# must be mirrored here in the same change (there is no import from the skill; the eval
# is a standalone instrument). PHASE_READ_LABELS is the report's canonical, sorted key
# order for the per-phase axis — every run reports all four, 0 when a phase was never
# entered.
PHASE_FILES = {
    "phase-1-setup.md": "phase1",
    "phase-2-implement.md": "phase2",
    "phase-2-sweeps-contract.md": "phase2",
    "phase-2-sweeps-quality.md": "phase2",
    "phase-3-review.md": "phase3",
    "phase-3-fix-loop.md": "phase3",
    "phase-3-ac-gate.md": "phase3",
    "phase-4-documentation.md": "phase4",
}
PHASE_READ_LABELS = tuple(sorted(PHASE_FILES.values()))

# Gated Phase 2.3 sweep references (issue #1739): a sweep-*.md reference read on the
# orchestrator main thread counts toward phase2. Kept OUT of PHASE_FILES, which a test
# pins as the exact skills/implement/phases/*.md mirror — widening it here breaks that pin.
SWEEP_REFERENCE_PREFIX = "sweep-"
SWEEP_REFERENCE_SUFFIX = ".md"
SWEEP_REFERENCE_PHASE = "phase2"
# SWEEP_REFERENCE_PHASE must stay a PHASE_READ_LABELS member; a non-member's KeyError on
# increment is swallowed by eval_corpus's defensive except as a mis-blamed malformed_record,
# so enforce it loudly at import (a plain assert is stripped under -O).
if SWEEP_REFERENCE_PHASE not in PHASE_READ_LABELS:
    raise AssertionError(
        "SWEEP_REFERENCE_PHASE {!r} must be a PHASE_READ_LABELS member".format(
            SWEEP_REFERENCE_PHASE))


def _phase_label_for_read(file_path):
    """The phase-read label a Read's `file_path` counts under, or None.

    A phase file matches PHASE_FILES by basename; a gated Phase 2.3 sweep reference
    (skills/implement/references/sweep-*.md) counts toward phase2 by basename shape. Both
    match on the basename because the same file resolves at a repo-relative path locally
    and a vendored path on the cloud tier.
    """
    basename = os.path.basename(file_path)
    label = PHASE_FILES.get(basename)
    if label is not None:
        return label
    if (basename.startswith(SWEEP_REFERENCE_PREFIX)
            and basename.endswith(SWEEP_REFERENCE_SUFFIX)):
        return SWEEP_REFERENCE_PHASE
    return None

# Tool name -> the category bucket its calls are counted under (issue #1209 AC10). The
# five categories the AC names at minimum are file reads, file edits/writes, shell
# commands, subagent dispatches and skill invocations; OTHER_TOOL_CATEGORY is the
# catch-all that makes the buckets sum to the run's WHOLE main-thread tool-call
# population, so `total_tool_calls` is never quietly smaller than the work performed.
# An unmapped name lands in `other` rather than being dropped — a new tool in a later
# harness release is then visible as a rising `other` count instead of vanishing.
# This mapping is a standalone mirror of the harness's tool vocabulary (the eval imports
# nothing from the harness); a renamed tool must be mirrored here in the same change.
TOOL_CATEGORY_BY_NAME = {
    "Read": "file_reads",
    "NotebookRead": "file_reads",
    "Edit": "file_edits_writes",
    "MultiEdit": "file_edits_writes",
    "Write": "file_edits_writes",
    "NotebookEdit": "file_edits_writes",
    "Bash": "shell_commands",
    "BashOutput": "shell_commands",
    "KillShell": "shell_commands",
    "Task": "subagent_dispatches",
    "Agent": "subagent_dispatches",
    "Skill": "skill_invocations",
}
OTHER_TOOL_CATEGORY = "other"
# The report's canonical, sorted key order for the tool-call axis — every run reports
# every category, 0 where that category was never used.
TOOL_CATEGORY_LABELS = tuple(sorted(
    set(TOOL_CATEGORY_BY_NAME.values()) | {OTHER_TOOL_CATEGORY}))

# Wall-clock gaps are rounded to this many decimal places so the rendered output stays
# byte-stable across runs (a float's full repr is not).
GAP_DECIMALS = 3

# The peak-context bucket thresholds the aggregate summary reports on.
BUCKET_200K = 200_000
BUCKET_400K = 400_000
# The sentinel a run-derived figure carries when the run population is empty. It is
# NEVER a number and NEVER 0 — an unestablished measurement collapsed onto a real value
# is the bug this instrument (like its create-issue sibling) guards against.
UNESTABLISHED = "unestablished"


def _median(values):
    """Deterministic median of a NON-EMPTY list of numbers.

    Refuses an empty population rather than returning 0: this module's central
    discipline is that an unestablished measurement is never collapsed onto a real
    value, and a primitive that answers `0` for "nothing was measured" is exactly that
    collapse one call away from every future caller. `_median_or_unestablished` is the
    only sanctioned empty-tolerant entry point.
    """
    if not values:
        raise ValueError("median of an empty population")
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    # Even count: mean of the two central values. Keep an int when it divides evenly so
    # the output stays byte-stable across runs.
    lo, hi = ordered[mid - 1], ordered[mid]
    total = lo + hi
    return total // 2 if total % 2 == 0 else total / 2


def _median_or_unestablished(values):
    """The median of a non-empty list, else the UNESTABLISHED sentinel.

    Never 0 for an empty population: an axis with no established operand reports
    `unestablished`, never a real value it did not measure.
    """
    return _median(values) if values else UNESTABLISHED


def _max_or_unestablished(values):
    """The max of a non-empty list, else the UNESTABLISHED sentinel."""
    return max(values) if values else UNESTABLISHED


def _sum_or_unestablished(values):
    """The sum of a non-empty list, else the UNESTABLISHED sentinel.

    The "empty population -> UNESTABLISHED, never 0" invariant is load-bearing (a
    real `0` and "no runs" must never be the same output), so the SUM fields go through
    this helper rather than an inline `sum(...) if values else UNESTABLISHED` ternary
    repeated per field. The following deliberately do NOT route through it, each for its
    own recorded reason: the `runs_over_*` bucket COUNTS guard on a different population
    (see their definition in `aggregate`), and the gap totals
    (`aggregate`'s `corpus_total_gap_seconds` and `_gap_stats`' `total_seconds`) wrap
    their sum in `round(..., GAP_DECIMALS)`.
    """
    return sum(values) if values else UNESTABLISHED


def _parse_timestamp(value):
    """Epoch seconds for an ISO-8601 record timestamp, or None when unusable.

    None is the *unestablished* answer — the caller tallies it into the skip accounting
    and drops the turn from the gap population rather than contributing a zero gap
    (issue #1209 AC11). A naive (offset-less) stamp is read as UTC so two stamps parsed
    here are always differenced on the same clock.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.timestamp()


def _tool_category(name):
    """The AC10 bucket a tool_use block's `name` counts under (unmapped -> `other`)."""
    if not isinstance(name, str):
        return OTHER_TOOL_CATEGORY
    return TOOL_CATEGORY_BY_NAME.get(name, OTHER_TOOL_CATEGORY)


def _gap_median(values):
    """The median of a seconds population, held to the GAP_DECIMALS contract.

    One home for the rounding, shared by the per-run statistic and both aggregate gap
    medians — rounding only some of them would leave the others rendering the float
    noise the constant exists to keep out.
    """
    median = _median_or_unestablished(values)
    return median if median == UNESTABLISHED else round(median, GAP_DECIMALS)


def _gap_stats(times):
    """Median / max / total of the wall-clock gaps between sorted turn timestamps.

    `times` holds one stamp per tool-bearing main-thread TURN (see the module
    docstring's disclosed proxy), so these are turn-boundary gaps, not per-call ones.

    Fewer than two timestamps yields no gap at all, so the three STATISTIC fields read
    UNESTABLISHED — never 0, which would claim a measured instantaneous run. `count` is
    NOT one of them: zero observed gaps is a real measurement, so it reads a real 0.

    Records are sorted before differencing rather than trusted in file order, so an
    out-of-order transcript cannot yield a negative gap.
    """
    ordered = sorted(times)
    gaps = [round(b - a, GAP_DECIMALS) for a, b in zip(ordered, ordered[1:])]
    # `_median`'s even branch can return an unrounded `total / 2`, which would render
    # float noise into a report GAP_DECIMALS exists to keep clean. Round here rather than
    # in `_median`: GAP_DECIMALS is a gap-axis contract and `_median` is shared with the
    # token-count axes, which have no decimal contract.
    median = _gap_median(gaps)
    return {
        "count": len(gaps),
        "median_seconds": median,
        "max_seconds": _max_or_unestablished(gaps),
        "total_seconds": (round(sum(gaps), GAP_DECIMALS) if gaps else UNESTABLISHED),
    }


RESIDENCY_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def _usage_value(usage, key):
    """One usage sub-field's ESTABLISHED token count, or None when it carries none.

    None covers absent, null, bool (an int subclass, never a token count), non-numeric
    and non-finite values. `json.loads` accepts bare Infinity/NaN and `int(inf)` raises
    OverflowError, so the non-finite guard here (not a caught exception) is what keeps a
    non-finite count from detonating the corpus walk (issue #1899).
    """
    if not isinstance(usage, dict):
        return None
    val = usage.get(key)
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        if isinstance(val, float) and not math.isfinite(val):
            return None
        return int(val)
    return None


def _context_tokens(usage):
    """Residency tokens = input + cache_read + cache_creation (no output), or None.

    None when NO residency sub-field carried an established count: an empty, all-null, or
    otherwise unusable `usage` object measured nothing, and folding its 0 into a peak
    would report an unmeasured turn as a real-looking 0 (issue #1899).
    """
    established = [v for v in (_usage_value(usage, k) for k in RESIDENCY_KEYS)
                   if v is not None]
    return sum(established) if established else None


class RunAccumulator:
    """Streams one session file's records and accumulates one run's metrics.

    Holds only small per-turn scalars — one int per attributed turn that carried a
    `usage` object, one float per timestamped tool-bearing turn, and the fixed
    per-phase / per-category tallies. It never retains full record bodies (the
    streaming property).

    `skipped` is the caller's skip-tally dict (see `new_skip_tally`); the accumulator
    writes the `unusable_timestamp` key into it, so a turn whose timestamp cannot be
    parsed is *accounted*, never silently dropped and never counted as a zero gap.
    """

    def __init__(self, source, skipped=None):
        self.source = source
        self.skipped = new_skip_tally() if skipped is None else skipped
        self.turn_count = 0
        self.per_turn_context = []
        self.compact_boundary_count = 0
        self.attributed = False
        # Attributed main-thread turns that carried NO `usage` object at all. Such a turn
        # has no recorded residency, so it is tallied here rather than folded into
        # per_turn_context as a 0 (which would collapse an unmeasured turn onto a real
        # value and drag the run's peak down — the silent-zero this instrument exists to
        # avoid, one level below the empty-population guard).
        self.usage_missing_turns = 0
        # phase label -> number of Read tool_use blocks that read that phase file.
        self.phase_reads = {label: 0 for label in PHASE_READ_LABELS}
        # AC10: category label -> number of main-thread tool_use blocks in that category.
        self.tool_calls = {label: 0 for label in TOOL_CATEGORY_LABELS}
        # AC11: epoch seconds of each main-thread turn that carried at least one tool
        # call. A turn whose timestamp is unusable is tallied instead of entering this
        # list, so it can never contribute a zero gap.
        self.tool_call_times = []
        # Per-RUN count of those dropped turns. The shared `skipped` tally is
        # corpus-wide, so it can never tell a reader WHICH run's gap distribution is
        # affected — the same reason `usage_missing_turns` is a per-run field beside the
        # peak it qualifies. A dropped turn does not vanish from the timeline: the gap
        # either side of it is computed straight across the hole and reported as ONE
        # interval, so this counter is what marks a run's gaps as spanning dropped turns.
        self.unusable_timestamp_turns = 0

    def observe_system(self, record):
        if record.get("subtype") == "compact_boundary":
            self.compact_boundary_count += 1

    def observe_assistant(self, record):
        # A sidechain (dispatched-subagent) record never touches the main-thread axes:
        # the phase files are read by the orchestrator on the main thread.
        if record.get("isSidechain") is True:
            return
        if record.get("attributionSkill") not in ATTRIBUTION:
            return
        self.attributed = True
        self.turn_count += 1
        # A truthy non-dict `message` (a JSON array/string) would make `.get()` raise;
        # `(x or {})` only rescues a FALSY value, so guard with isinstance — a
        # well-typed-but-wrong-shape record degrades cleanly.
        message = record.get("message")
        if not isinstance(message, dict):
            message = {}
        tokens = _context_tokens(message.get("usage"))
        if tokens is None:
            # Residency was never established for this turn — no usage object, or one
            # carrying only null/non-finite counts. Tally it instead of folding a 0 into the
            # peak, which would report an unmeasured turn as a real value (issue #1899).
            self.usage_missing_turns += 1
        else:
            self.per_turn_context.append(tokens)

        content = message.get("content")
        if not isinstance(content, list):
            return
        saw_tool_call = False
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            saw_tool_call = True
            # AC10: every main-thread tool call lands in exactly one category bucket, so
            # the buckets sum to the run's whole tool-call population.
            self.tool_calls[_tool_category(block.get("name"))] += 1
            if block.get("name") == "Read":
                # A Read block's `input` may be a non-dict (a list/string); `(x or {})`
                # passes a truthy non-dict through to `.get()` and raises. isinstance-guard.
                block_input = block.get("input")
                file_path = (block_input.get("file_path")
                             if isinstance(block_input, dict) else None)
                if not isinstance(file_path, str):
                    # The path could not be ESTABLISHED, so it is accounted rather than
                    # silently read as "not a phase file". Without this tally a harness
                    # release that renamed `input.file_path` would make every phase-read
                    # count in a corpus report a real-looking 0 with a clean skip tally
                    # — the headline axis measuring nothing, indistinguishably from a run
                    # that entered no phase. A Read of a NON-phase file is a legitimate
                    # non-count and is deliberately NOT tallied here.
                    self.skipped["unresolvable_read_path"] += 1
                    continue
                label = _phase_label_for_read(file_path)
                if label is not None:
                    self.phase_reads[label] += 1
        if not saw_tool_call:
            return
        # AC11: a tool-bearing turn joins the gap population only with a usable
        # timestamp. An unusable one is ACCOUNTED in the skip tally — never dropped
        # silently, and never folded in as a zero gap.
        stamp = _parse_timestamp(record.get("timestamp"))
        if stamp is None:
            self.skipped["unusable_timestamp"] += 1
            self.unusable_timestamp_turns += 1
        else:
            self.tool_call_times.append(stamp)

    def result(self):
        """The run record's own fields.

        An attributed run whose every turn lacked a `usage` object has an empty
        `per_turn_context`, so its peak/final read UNESTABLISHED (never 0): the residency
        was never measured, and a real-looking 0 there is exactly the unknown-onto-zero
        collapse this instrument guards against. `usage_missing_turns` surfaces the gap.
        """
        peak = max(self.per_turn_context) if self.per_turn_context else UNESTABLISHED
        final = self.per_turn_context[-1] if self.per_turn_context else UNESTABLISHED
        # Emit the per-phase counts in the canonical sorted label order so the JSON /
        # text output is byte-stable across runs.
        phase_reads = {label: self.phase_reads[label] for label in PHASE_READ_LABELS}
        tool_calls = {label: self.tool_calls[label] for label in TOOL_CATEGORY_LABELS}
        return {
            "source": self.source,
            "turn_count": self.turn_count,
            # Residency axis (issue #1209 axis 1).
            "peak_context": peak,
            "final_context": final,
            "compact_boundary_count": self.compact_boundary_count,
            # Attributed turns whose residency was never recorded (no usage object).
            "usage_missing_turns": self.usage_missing_turns,
            # Phase-file re-read axis (issue #1209 axis 2) — reported SEPARATELY from the
            # peak because they are different quantities (AC2).
            "phase_reads": phase_reads,
            "total_phase_reads": sum(phase_reads.values()),
            # Tool-call axis (issue #1209 axis 3 / AC10) — bucketed by category, because
            # a turn count alone cannot tell "did more work" from "took more turns".
            "tool_calls": tool_calls,
            "total_tool_calls": sum(tool_calls.values()),
            # Inter-tool-call wall-clock gap axis (issue #1209 axis 4 / AC11) — median,
            # max AND total, never a mean alone. Measured at TURN granularity (the
            # module docstring's disclosed proxy). `spans_dropped_turns` marks a
            # distribution whose gaps were computed across a turn dropped for an
            # unusable timestamp, so the contamination travels with the number.
            "unusable_timestamp_turns": self.unusable_timestamp_turns,
            "tool_call_gaps": dict(
                _gap_stats(self.tool_call_times),
                spans_dropped_turns=bool(self.unusable_timestamp_turns)),
        }


def new_skip_tally():
    """A fresh, fully-seeded skip tally.

    The key vocabulary has ONE home here rather than being seeded in `eval_corpus` and
    written by `_iter_session_files` / `RunAccumulator`, which would make an
    under-seeded dict a KeyError at the far end of the walk.
    """
    return {
        "non_json_line": 0,
        "not_object": 0,
        "no_type": 0,
        "unreadable_file": 0,
        "escaped_path": 0,
        "walk_error": 0,
        "malformed_record": 0,
        # A tool-bearing main-thread turn whose timestamp could not be parsed: it leaves
        # the gap population accounted here rather than contributing a zero gap (AC11).
        "unusable_timestamp": 0,
        # A `Read` tool_use whose `input`/`file_path` shape is unusable: the path could
        # not be established, so it leaves the phase-read axis accounted here rather
        # than silently reading as "not a phase file".
        "unresolvable_read_path": 0,
    }


def _iter_session_files(corpus_root, skipped):
    """Yield JSONL session file paths under the corpus root, deterministically.

    Skips any entry whose real path escapes the corpus root (a symlink out), so the
    eval never reads outside the supplied directory. Sorted for determinism. Both
    walk-level drops are TALLIED and breadcrumbed, never silent.
    """
    root_real = os.path.realpath(corpus_root)
    collected = []

    def _on_walk_error(exc):
        skipped["walk_error"] += 1
        sys.stderr.write(
            "warning: skipping unwalkable corpus directory {}: {}\n".format(
                getattr(exc, "filename", "?"), exc
            )
        )

    for dirpath, dirnames, filenames in os.walk(corpus_root, onerror=_on_walk_error):
        dirnames.sort()
        for name in sorted(filenames):
            if not name.endswith(".jsonl"):
                continue
            full = os.path.join(dirpath, name)
            real = os.path.realpath(full)
            if real != root_real and not real.startswith(root_real + os.sep):
                skipped["escaped_path"] += 1
                sys.stderr.write(
                    "warning: skipping session file escaping corpus root {}\n".format(
                        full
                    )
                )
                continue
            collected.append(full)
    collected.sort()
    return collected


def eval_corpus(corpus_root):
    """Return (runs, skipped) for a corpus directory.

    runs: list of per-run metric dicts (only sessions with attributed turns).
    skipped: dict of {reason: count} of records AND session files the walk stepped over —
        malformed records, unreadable files, corpus-escaping symlinks, unwalkable
        directories, and tool-bearing turns with an unusable timestamp. A non-zero total
        is therefore not necessarily "bad transcript data"; read the per-reason keys.
    """
    runs = []
    skipped = new_skip_tally()
    for session_file in _iter_session_files(corpus_root, skipped):
        # The run's identity is the CORPUS-RELATIVE path, not the basename: a corpus with
        # `a/session.jsonl` and `b/session.jsonl` would otherwise emit two run records
        # with the same `source`, which the sort key and every by-source join treat as
        # one. Normalized to forward slashes so the output is host-independent.
        rel_source = os.path.relpath(session_file, corpus_root).replace(os.sep, "/")
        acc = RunAccumulator(rel_source, skipped)
        try:
            handle = open(session_file, "r", encoding="utf-8", errors="replace")
        except OSError as exc:
            skipped["unreadable_file"] += 1
            sys.stderr.write(
                "warning: skipping unreadable session file {}: {}\n".format(
                    session_file, exc
                )
            )
            continue
        with handle:
            for lineno, raw in enumerate(handle, 1):  # streaming: one record at a time
                line = raw.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (ValueError, TypeError):
                    # A truncated final line or a non-JSON line: skip, do not detonate.
                    skipped["non_json_line"] += 1
                    continue
                if not isinstance(record, dict):
                    skipped["not_object"] += 1
                    continue
                rtype = record.get("type")
                if rtype is None:
                    skipped["no_type"] += 1
                    continue
                # Defensive backstop: the observers isinstance-guard their known field
                # shapes, but a record shape not anticipated here must degrade per-record
                # (tallied + breadcrumbed), never detonate the whole corpus walk.
                try:
                    if rtype == "assistant":
                        acc.observe_assistant(record)
                    elif rtype == "system":
                        acc.observe_system(record)
                except (AttributeError, TypeError, ValueError, KeyError) as exc:
                    skipped["malformed_record"] += 1
                    # Name the file, the LINE and the record type: a real session is
                    # tens of thousands of lines, and without them a maintainer cannot
                    # find the record to judge whether the skip was legitimate. Note
                    # this catch cannot distinguish a hostile record shape from a defect
                    # in the observers themselves (the same four exception types), so a
                    # burst of these warnings on one record type is a reason to suspect
                    # the instrument, not only the transcript.
                    sys.stderr.write(
                        "warning: skipping malformed {} record at {}:{}: {}: {}\n".format(
                            rtype, session_file, lineno, type(exc).__name__, exc
                        )
                    )
                    continue
        if acc.attributed:
            runs.append(acc.result())
    runs.sort(key=lambda r: r["source"])
    return runs, skipped


def aggregate(runs):
    """The exactly-these-fields aggregate summary, complete by construction.

    **One convention across every run-derived field.** On an empty run population every
    figure computed from `runs` reads `unestablished` — a reader must never have to know
    which field they are looking at to tell "measured zero" from "no population".
    `run_count` is the one deliberate exception: `0` is its measurement, not a collapsed
    unknown.

    A run whose peak is `UNESTABLISHED` (every attributed turn lacked a usage object) is
    excluded from the peak population — it stays counted in `run_count` and surfaced via
    `total_usage_missing_turns`, but is never averaged in as a real-looking 0.

    **Soundness of the int/`unestablished` union:** it holds only while every reader is a
    pure formatter (`render_text`, `json.dumps` — both treat each value opaquely); a
    future field consumer doing arithmetic must first branch on `UNESTABLISHED`. A median
    can also be a float on an even population (see `_median`), so the median fields are
    `int | float | str`.
    """
    # Exclude UNESTABLISHED peaks (usage-less runs) from the peak population — never
    # coerce them to 0. `peaks` non-empty therefore means "at least one run with a
    # measured peak", which is the population the buckets below guard on.
    peaks = [r["peak_context"] for r in runs if r["peak_context"] != UNESTABLISHED]
    summary = {
        "run_count": len(runs),
        # Attributed turns across the corpus whose residency was never recorded.
        "total_usage_missing_turns": _sum_or_unestablished(
            [r["usage_missing_turns"] for r in runs]),
        # Corpus total of the tool-bearing turns dropped from the gap population for an
        # unusable timestamp — the gap axis's sibling of the field above.
        "total_unusable_timestamp_turns": _sum_or_unestablished(
            [r["unusable_timestamp_turns"] for r in runs]),
        # Residency axis (issue #1209 axis 1) — median AND max, so tail behaviour is
        # visible and not hidden by an average (AC3).
        "median_peak_context": _median_or_unestablished(peaks),
        "max_peak_context": _max_or_unestablished(peaks),
        # These count OVER the measured-peak population, so they guard on `peaks` (the
        # measured-peak population itself) rather than on the over-threshold
        # sub-population `_sum_or_unestablished` would key on: with measured runs
        # present but none over threshold the
        # answer is a real 0, never `unestablished` — so `_sum_or_unestablished` (which
        # keys on its own argument being empty) is deliberately NOT used here.
        "runs_over_200k": (sum(1 for p in peaks if p > BUCKET_200K)
                           if peaks else UNESTABLISHED),
        "runs_over_400k": (sum(1 for p in peaks if p > BUCKET_400K)
                           if peaks else UNESTABLISHED),
    }
    # Phase-file re-read axis (issue #1209 axis 2) — per phase, median + max + corpus
    # total, in the canonical sorted label order. Reported separately from the peak.
    for label in PHASE_READ_LABELS:
        counts = [r["phase_reads"][label] for r in runs]
        summary["median_{}_reads".format(label)] = _median_or_unestablished(counts)
        summary["max_{}_reads".format(label)] = _max_or_unestablished(counts)
        summary["total_{}_reads".format(label)] = _sum_or_unestablished(counts)
    totals = [r["total_phase_reads"] for r in runs]
    summary["median_total_phase_reads"] = _median_or_unestablished(totals)
    summary["max_total_phase_reads"] = _max_or_unestablished(totals)
    # Tool-call axis (issue #1209 axis 3 / AC10), aggregated across the corpus on the
    # same footing as the peak above (AC12) — per category, median + max + corpus total,
    # in the canonical sorted label order.
    for label in TOOL_CATEGORY_LABELS:
        counts = [r["tool_calls"][label] for r in runs]
        summary["median_{}_calls".format(label)] = _median_or_unestablished(counts)
        summary["max_{}_calls".format(label)] = _max_or_unestablished(counts)
        summary["total_{}_calls".format(label)] = _sum_or_unestablished(counts)
    call_totals = [r["total_tool_calls"] for r in runs]
    summary["median_total_tool_calls"] = _median_or_unestablished(call_totals)
    summary["max_total_tool_calls"] = _max_or_unestablished(call_totals)
    # Gap axis (issue #1209 axis 4 / AC11), aggregated (AC12). A run with fewer than two
    # timestamped tool calls has no measured gap, so it is EXCLUDED from these
    # populations rather than entering them as a 0 — the same exclusion the usage-less
    # run gets from the peak population above.
    gap_maxima = [r["tool_call_gaps"]["max_seconds"] for r in runs
                  if r["tool_call_gaps"]["max_seconds"] != UNESTABLISHED]
    gap_totals = [r["tool_call_gaps"]["total_seconds"] for r in runs
                  if r["tool_call_gaps"]["total_seconds"] != UNESTABLISHED]
    summary["median_run_max_gap_seconds"] = _gap_median(gap_maxima)
    summary["max_run_max_gap_seconds"] = _max_or_unestablished(gap_maxima)
    summary["median_run_total_gap_seconds"] = _gap_median(gap_totals)
    summary["max_run_total_gap_seconds"] = _max_or_unestablished(gap_totals)
    summary["corpus_total_gap_seconds"] = (
        round(sum(gap_totals), GAP_DECIMALS) if gap_totals else UNESTABLISHED)
    return summary


def build_report(corpus_root):
    """One run-set report: runs, the aggregate, and the skip tally."""
    runs, skipped = eval_corpus(corpus_root)
    return {
        "runs": runs,
        "summary": aggregate(runs),
        "skipped": skipped,
    }


def _render_run_line(r):
    phase = " ".join(
        "{}={}".format(label, r["phase_reads"][label]) for label in PHASE_READ_LABELS)
    tools = " ".join(
        "{}={}".format(label, r["tool_calls"][label]) for label in TOOL_CATEGORY_LABELS)
    gaps = r["tool_call_gaps"]
    return (
        "- {source}: turns={turn_count} peak={peak_context} final={final_context} "
        "compactions={compact_boundary_count} usage_missing={usage_missing_turns} "
        "phase_reads=[{phase}] total_phase_reads={total_phase_reads} "
        "tool_calls=[{tools}] total_tool_calls={total_tool_calls} "
        # The unit lives in the KEY, never appended to the value: a `{value}s` suffix
        # renders the UNESTABLISHED sentinel as "unestablisheds".
        "turn_gap_seconds=[n={gap_count} median={gap_median} max={gap_max} "
        "total={gap_total} spans_dropped_turns={gap_dropped} "
        # The per-run COUNT, not only the boolean: the flag says WHICH run's
        # distribution is affected, the count says how badly, and the text report is
        # what a maintainer reads.
        "dropped_turns={unusable_timestamp_turns}]".format(
            phase=phase, tools=tools, gap_count=gaps["count"],
            gap_median=gaps["median_seconds"], gap_max=gaps["max_seconds"],
            gap_total=gaps["total_seconds"],
            gap_dropped=gaps["spans_dropped_turns"], **r)
    )


def render_text(runs, summary, skipped):
    lines = []
    lines.append("# implement runtime main-thread context eval")
    lines.append("")
    lines.append("## Per-run metrics")
    if not runs:
        lines.append("(no implement runs found in the supplied corpus)")
    for r in runs:
        lines.append(_render_run_line(r))
    lines.append("")
    lines.append("## Aggregate summary")
    # aggregate() builds this dict in the canonical field order, so iterating it renders
    # every field once with no per-field literal to keep in sync.
    for key, value in summary.items():
        lines.append("- {}: {}".format(key, value))
    lines.append("")
    # The two AXIS EXCLUSIONS are reported under their own heading rather than
    # inflating the skipped headline a maintainer reads as "bad transcript data":
    # neither is a parse failure, and each removes a turn or a block from ONE axis. The
    # remaining tally covers both records and whole session files / directories (see
    # eval_corpus's docstring), which is why the heading names both.
    excluded = {k: skipped.get(k, 0)
                for k in ("unusable_timestamp", "unresolvable_read_path")}
    record_skips = {k: v for k, v in skipped.items() if k not in excluded}
    lines.append("## Skipped records and files: {}".format(sum(record_skips.values())))
    for reason in sorted(record_skips):
        if record_skips[reason]:
            lines.append("- {}: {}".format(reason, record_skips[reason]))
    lines.append("")
    lines.append("## Dropped from an axis (not a parse failure)")
    lines.append("- turns dropped from the gap population (unusable timestamp): "
                 "{}".format(excluded["unusable_timestamp"]))
    lines.append("- Read blocks dropped from the phase-read axis (unresolvable path): "
                 "{}".format(excluded["unresolvable_read_path"]))
    return "\n".join(lines)


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None):
    _force_utf8_streams()
    parser = argparse.ArgumentParser(
        description="Measure the runtime main-thread context cost of /prflow:implement.",
    )
    parser.add_argument(
        "transcript_dir",
        help="Path to a Claude Code transcript directory.",
    )
    parser.add_argument(
        "--format", choices=("text", "json"), default="text",
        help="Output format (default: text).",
    )
    args = parser.parse_args(argv)

    corpus = args.transcript_dir
    if not os.path.isdir(corpus):
        # No corpus present: exit non-zero naming the missing path — never a
        # silently-empty baseline.
        sys.stderr.write(
            "error: transcript directory not found: {}\n".format(corpus)
        )
        return 2

    report = build_report(corpus)
    runs, summary, skipped = report["runs"], report["summary"], report["skipped"]

    if args.format == "json":
        # Sort keys for byte-stable, deterministic output.
        sys.stdout.write(
            json.dumps(
                {"runs": runs, "summary": summary, "skipped": skipped},
                indent=2, sort_keys=True,
            )
            + "\n"
        )
    else:
        sys.stdout.write(render_text(runs, summary, skipped) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
