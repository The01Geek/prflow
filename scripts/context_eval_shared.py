#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Shared transcript-walking helpers for the three context-cost instruments.

scripts/create_issue_eval.py, scripts/implement-context-eval.py and
scripts/review-context-eval.py each measure the runtime main-thread context a run
accumulates by walking a Claude Code transcript directory. This module is the single
definition of the five helpers all three share — `_iter_session_files`, `_median`,
`_context_tokens`, `_usage_value`, and the `UNESTABLISHED` sentinel — extracted (issue
#1900) so a fix lands once.

`_usage_value`, `_context_tokens` and `_median` keep issue #1899's strict discipline: an
unmeasured turn, an empty population, and a non-finite number are reported unestablished
(or raise), never collapsed onto a real 0. `RESIDENCY_KEYS` moves too, as the field set the
shared `_context_tokens` ranges over.
"""

import json
import math
import os
import sys
from collections import namedtuple

# The sentinel a per-field / proxy figure carries when the operand it needs could not be
# established. NEVER a number and NEVER 0 — an unestablished measurement collapsed onto a
# real value is the bug this whole axis guards against (issue #1899).
UNESTABLISHED = "unestablished"

# The residency-axis usage sub-fields `_context_tokens` sums (input + cache read + cache
# creation, no output).
RESIDENCY_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")

# The implement phase files whose per-run read count issue #1209 measures, and the
# gated Phase 2.3 sweep-reference shape (issue #1739). These live here rather than in
# scripts/implement-context-eval.py because scripts/extract-execution-cost.py measures the
# same per-phase reads and cannot import the hyphenated instrument by name. The basename
# map is a standalone mirror of skills/implement/phases/*.md (no import from the skill);
# PhaseFileSetCouplingTest reconciles it against that directory, so a phase-file
# rename/add/remove goes RED there rather than silently under-reporting a phase's reads.
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
PHASE_READ_LABELS = tuple(sorted(set(PHASE_FILES.values())))
SWEEP_REFERENCE_PREFIX = "sweep-"
SWEEP_REFERENCE_SUFFIX = ".md"
SWEEP_REFERENCE_PHASE = "phase2"
if SWEEP_REFERENCE_PHASE not in PHASE_READ_LABELS:
    raise AssertionError(
        f"SWEEP_REFERENCE_PHASE {SWEEP_REFERENCE_PHASE!r} must be a PHASE_READ_LABELS member")

# The cloud execution file (scripts/scrub-transcript.sh's uploaded artifact, and the raw
# execution file the harness writes) prepends one `# DEVFLOW SCRUB CAVEAT` line to a
# pretty-printed JSON array. The transcript-record reader below strips those leading
# comment lines, then reads the remainder as a whole-file array, a whole-file object, or
# JSONL — the single reader every context-cost instrument, implement-timeline.py and
# extract-execution-cost.py share (issue #120), generalized from PR #113's private copy.
TranscriptRead = namedtuple(
    "TranscriptRead",
    "records unparseable_lines non_object_elements non_transcript_json caveat_lines parsed",
)


def _strip_caveat_lines(text):
    """(body, caveat_line_count): drop only the LEADING `#`-comment lines the scrub helper
    prepends. A `#` deeper in the file sits inside a JSON string value and must reach the
    parser, so stripping stops at the first line whose first non-blank character is not
    `#` (issue #120 AC2)."""
    lines = text.splitlines(keepends=True)
    count = 0
    while count < len(lines) and lines[count].lstrip().startswith("#"):
        count += 1
    return "".join(lines[count:]), count


def read_transcript_records(text):
    """Parse one transcript file's text into record dicts, tolerating the cloud shape.

    Ladder (issue #120 AC1): drop leading `#` comment lines, then parse the remainder as a
    whole-file JSON array, else a whole-file JSON object, else JSONL — in that order. Only
    dict records are returned. Whole-file JSON is tried first because a line-split of a
    pretty-printed array reports every line as unparseable.

    A whole-file JSON parse (array, object, or scalar) that yields no dict carrying a
    `type` field is a NON-TRANSCRIPT json file — the `custom-title.json` sidecars a local
    corpus root holds by the hundred — so it returns no records and sets
    `non_transcript_json`, never feeding its elements to the per-record `no_type`/
    `not_object` tallies (AC4).

    Returns a `TranscriptRead`:
      records             — list[dict] of record dicts to process
      unparseable_lines   — JSONL lines that failed to parse (caller maps to non_json_line)
      non_object_elements — array elements / JSONL values that were not objects (not_object)
      non_transcript_json — 1 when a whole-file JSON parse carried no type-bearing record
      caveat_lines        — count of leading `#` lines stripped
      parsed              — True when anything parsed (whole-file JSON, or >=1 JSONL line)
    """
    body, caveat_lines = _strip_caveat_lines(text)
    if not body.strip():
        # Keyword construction throughout (issue #120 review): the six fields include four
        # adjacent int/bool operands, so a transposed positional argument would type-check
        # clean and surface only as a wrong tally three files away.
        return TranscriptRead(records=[], unparseable_lines=0, non_object_elements=0,
                              non_transcript_json=0, caveat_lines=caveat_lines, parsed=False)
    # Whole-file JSON first (array, object, or scalar). A multi-line JSONL stream fails
    # this parse on its second value and falls through to the per-line path below. Catch
    # broadly, not only JSONDecodeError: on the recursive-decoder Pythons in the supported
    # range (< 3.14) a deeply-nested document raises RecursionError (a RuntimeError), which
    # must degrade to a skip rather than detonate the walk.
    try:
        root = json.loads(body)
    except Exception:
        root = None
        whole_ok = False
    else:
        whole_ok = True
    if whole_ok:
        if isinstance(root, list):
            dicts = [e for e in root if isinstance(e, dict)]
            if any("type" in d for d in dicts):
                return TranscriptRead(records=dicts, unparseable_lines=0,
                                      non_object_elements=len(root) - len(dicts),
                                      non_transcript_json=0, caveat_lines=caveat_lines,
                                      parsed=True)
            # Parsed whole-file JSON with no `type`-bearing record → non_transcript_json.
            # The dicts stay in `records` for a caller that reads any dict (the cost reader
            # in extract-execution-cost.py); a per-record caller (the context evals) sees
            # non_transcript_json set and skips them, so they feed no no_type/not_object
            # tally (AC4). non_object_elements stays 0 for the same AC4 reason.
            return TranscriptRead(records=dicts, unparseable_lines=0, non_object_elements=0,
                                  non_transcript_json=1, caveat_lines=caveat_lines,
                                  parsed=True)
        if isinstance(root, dict):
            if "type" in root:
                return TranscriptRead(records=[root], unparseable_lines=0,
                                      non_object_elements=0, non_transcript_json=0,
                                      caveat_lines=caveat_lines, parsed=True)
            return TranscriptRead(records=[root], unparseable_lines=0, non_object_elements=0,
                                  non_transcript_json=1, caveat_lines=caveat_lines,
                                  parsed=True)
        # A scalar parsed but carries no transcript record.
        return TranscriptRead(records=[], unparseable_lines=0, non_object_elements=0,
                              non_transcript_json=1, caveat_lines=caveat_lines, parsed=True)
    # JSONL fallback: one JSON value per non-blank line.
    records = []
    unparseable = 0
    non_object = 0
    any_ok = False
    for line in body.splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except Exception:  # incl. RecursionError on a deeply-nested line (< 3.14)
            unparseable += 1
            continue
        any_ok = True
        if not isinstance(rec, dict):
            non_object += 1
            continue
        records.append(rec)
    return TranscriptRead(records=records, unparseable_lines=unparseable,
                          non_object_elements=non_object, non_transcript_json=0,
                          caveat_lines=caveat_lines, parsed=any_ok)


def read_and_tally(text, skipped):
    """Parse a transcript file's text, fold the shared per-shape skip counts into the
    caller's `skipped` tally, and return the transcript records to iterate.

    The three context-cost instruments (implement/review/create_issue eval) share this so
    the tally-mapping contract lives in one place; scripts/extract-execution-cost.py reads
    `read_transcript_records` directly instead, because it consumes even a non-transcript
    JSON file's dicts (a raw execution file whose rows carry usage but no `type`).

    The returned list is EMPTY when the file is a non-transcript JSON file (a
    custom-title.json sidecar): dropping those here is the safe default, so a caller cannot
    accidentally feed them to its per-record `no_type`/`not_object` tally (AC4). The
    caller's `skipped` dict must already carry `non_json_line`, `not_object` and
    `non_transcript_json`.
    """
    parsed = read_transcript_records(text)
    skipped["non_json_line"] += parsed.unparseable_lines
    skipped["not_object"] += parsed.non_object_elements
    skipped["non_transcript_json"] += parsed.non_transcript_json
    return [] if parsed.non_transcript_json else parsed.records


def _is_main_thread_record(record):
    """A record on the orchestrator main thread, not a dispatched subagent's (issue #120
    AC5). Excluded when `isSidechain` is `true` (local transcripts) OR `parent_tool_use_id`
    is a non-empty string (the cloud execution file's subagent marker — the real cloud
    file carries no `isSidechain`, per lib/test/fixtures/execution-file-shape.observed.txt)."""
    if record.get("isSidechain") is True:
        return False
    ptid = record.get("parent_tool_use_id")
    return not (isinstance(ptid, str) and ptid)


def _phase_read_label(file_path, phase_files, sweep_prefix="", sweep_suffix="",
                      sweep_label=None):
    """The phase-read label a Read's `file_path` counts under, or None. Matches on the
    BASENAME because the same file resolves at a repo-relative path locally and a vendored
    path on the cloud tier. Takes the label map as an argument rather than redefining it,
    so PHASE_FILES stays the single test-pinned mirror."""
    basename = os.path.basename(file_path)
    label = phase_files.get(basename)
    if label is not None:
        return label
    if sweep_prefix and basename.startswith(sweep_prefix) and basename.endswith(sweep_suffix):
        return sweep_label
    return None


def measure_context(records, phase_files, sweep_prefix="", sweep_suffix="",
                    sweep_label=None):
    """Peak main-thread residency and per-phase Read counts over transcript records.

    The shared measuring core (issue #120): scripts/extract-execution-cost.py runs it over
    a whole execution file with no run-boundary concept. A record is on the main thread
    unless `_is_main_thread_record` excludes it; no `attributionSkill` filter is applied
    here (scripts/implement-context-eval.py adds its own bounding).

    Returns `(peak, phase_reads)`:
      peak        — max established residency (int), or None when no main-thread record
                    carried a usage object (AC8: `null`, never a real 0).
      phase_reads — {label: count, ..., "total": n} in the sorted label order, or None
                    when no main-thread assistant record existed at all (AC8: `null`).
    """
    labels = tuple(sorted(set(phase_files.values())))
    phase_reads = {label: 0 for label in labels}
    peak = None
    saw_main_thread = False
    for record in records:
        if not isinstance(record, dict) or record.get("type") != "assistant":
            continue
        if not _is_main_thread_record(record):
            continue
        saw_main_thread = True
        message = record.get("message")
        if not isinstance(message, dict):
            message = {}
        tokens = _context_tokens(message.get("usage"))
        if tokens is not None:
            peak = tokens if peak is None else max(peak, tokens)
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            if block.get("name") != "Read":
                continue
            block_input = block.get("input")
            file_path = (block_input.get("file_path")
                         if isinstance(block_input, dict) else None)
            if not isinstance(file_path, str):
                continue
            label = _phase_read_label(file_path, phase_files, sweep_prefix,
                                      sweep_suffix, sweep_label)
            if label is not None:
                phase_reads[label] += 1
    if not saw_main_thread:
        return None, None
    phase_reads["total"] = sum(phase_reads[label] for label in labels)
    return peak, phase_reads


def _median(values):
    """Deterministic median of a NON-EMPTY list of numbers.

    Refuses an empty population rather than returning 0 (issue #1899): an unestablished
    measurement is never collapsed onto a real value. A caller with a possibly-empty
    population wraps this in its own `_median_or_unestablished`.
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


def _usage_value(usage, key):
    """One usage sub-field's ESTABLISHED token count on the RESIDENCY axis, or None.

    None covers absent, null, bool, non-numeric and non-finite values — the residency axis
    reports an unmeasured field as unestablished, never a spurious 0 (issue #1899).
    """
    if not isinstance(usage, dict):
        return None
    val = usage.get(key)
    if isinstance(val, bool):  # bool is an int subclass; never a token count
        return None
    if isinstance(val, (int, float)):
        # json.loads accepts bare Infinity/NaN and int(inf) raises OverflowError, so guard
        # non-finite here rather than at the arithmetic site (issue #1899).
        if isinstance(val, float) and not math.isfinite(val):
            return None
        return int(val)
    return None


def _context_tokens(usage):
    """Main-thread residency = input + cache_read + cache_creation (no output), or None.

    None when NO residency sub-field carried an established count: an empty, all-null, or
    otherwise unusable `usage` object measured nothing, and folding its 0 into the peak
    would report an unmeasured turn as a real-looking 0 (issue #1899).
    """
    established = [v for v in (_usage_value(usage, k) for k in RESIDENCY_KEYS)
                   if v is not None]
    return sum(established) if established else None


def _iter_session_files(corpus_root, skipped):
    """Yield `.jsonl` AND `.json` session file paths under the corpus root, deterministically.

    Skips an entry whose real path escapes the corpus root (a symlink out), so the eval
    never reads outside the supplied directory. Sorted for determinism.

    Every walk-level drop is TALLIED and breadcrumbed, never silent (mirroring the
    per-record and unreadable-file skip discipline): a session file whose real path escapes
    the corpus root is counted under `escaped_path`; a directory-walk error (a
    permission-denied dir, a vanished tree) is counted under `walk_error` via the `os.walk`
    `onerror` callback (default `onerror=None` would swallow it); and every walked-past name
    with an unrecognized suffix is counted under `unrecognized_suffix` and reported as ONE
    aggregate stderr line (count plus the first few paths), never one line per path — a real
    local corpus root holds hundreds of `.txt` sidecars beside its transcripts, so a
    per-path line would flood the instrument's stderr on every ordinary run (issue #120 AC3).

    The caller supplies a `skipped` dict already carrying the `escaped_path`, `walk_error`
    and `unrecognized_suffix` keys. Do NOT `setdefault`/`defaultdict` them here: an
    under-populated dict would then tally into a key the caller never emits, so the drop
    becomes invisible in the output — the KeyError is the fail-closed direction.
    """
    root_real = os.path.realpath(corpus_root)
    collected = []
    unrecognized = []

    def _on_walk_error(exc):
        # A directory os.walk could not descend (permissions, a race deletion): tally and
        # breadcrumb so the aggregate is never silently computed over a corpus the walk
        # under-enumerated. `exc.filename` names the offending directory.
        skipped["walk_error"] += 1
        sys.stderr.write(
            "warning: skipping unwalkable corpus directory {}: {}\n".format(
                getattr(exc, "filename", "?"), exc
            )
        )

    for dirpath, dirnames, filenames in os.walk(corpus_root, onerror=_on_walk_error):
        dirnames.sort()
        for name in sorted(filenames):
            if not name.endswith((".jsonl", ".json")):
                # A non-transcript-suffix name (a `.txt` sidecar, etc.): tally it so the
                # drop is visible, but hold the path for ONE aggregate stderr line below.
                unrecognized.append(os.path.join(dirpath, name))
                continue
            full = os.path.join(dirpath, name)
            real = os.path.realpath(full)
            if real != root_real and not real.startswith(root_real + os.sep):
                # A symlink (or other entry) whose real path escapes the corpus root: never
                # read, but tally + breadcrumb so the drop is visible, not silent.
                skipped["escaped_path"] += 1
                sys.stderr.write(
                    f"warning: skipping session file escaping corpus root {full}\n"
                )
                continue
            collected.append(full)
    if unrecognized:
        skipped["unrecognized_suffix"] += len(unrecognized)
        preview = ", ".join(sorted(unrecognized)[:3])
        extra = "" if len(unrecognized) <= 3 else f" (+{len(unrecognized) - 3} more)"
        sys.stderr.write(
            f"warning: skipping {len(unrecognized)} file(s) with an unrecognized suffix "
            f"(want .jsonl/.json): {preview}{extra}\n"
        )
    collected.sort()
    return collected
