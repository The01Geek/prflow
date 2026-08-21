#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Behavioral eval for what entering the review engine costs, per context (issue #1852).

This is a maintainer/CI-adjacent instrument. No skill, workflow, or suite gate invokes
it for a measurement or a threshold; the only automated execution is its own focused unit
test (lib/test/test_review_context_eval.py), which asserts parser behavior. It walks a
supplied Claude Code transcript directory and measures what entering the *review engine*
cost a run — how many times each engine file was read, in which context each read
happened, and the peak accumulated context of each context that read one. It reads
transcripts and writes a report; it stores nothing and changes no repository state.

It is the third of this repository's transcript-walking context instruments, after
scripts/create-issue-context-eval.py (issue #767) and scripts/implement-context-eval.py
(issue #1209), and reuses their proven streaming / per-record degradation / symlink-escape
/ determinism design. Its ONE substantive difference from the implement sibling is the
attribution axis: the sibling filters sidechain (subagent) records out entirely, because
the implement phase files are read by the orchestrator on the main thread; this instrument
attributes reads PER CONTEXT instead, because after issue #1850 the review engine's entries
are dispatched into subagent contexts, and an instrument that counted only main-thread
reads would report the engine cost went to zero rather than that it moved.

An "engine file" is any file under `skills/review/` or `skills/review-and-fix/`. Matching
is by path SUBTREE, not basename, because both subtrees carry a `SKILL.md` (a basename
match would collapse the two roots into one count), and it is normalized across the
absolute, repo-relative and vendored (`.prflow/vendor/prflow/…`) spellings the same file
resolves at on different tiers.

A "context" is one conversation thread in a transcript. A record's context is:
  * a MAIN-THREAD context (keyed by `sessionId`) when `isSidechain` is not true, or
  * a SUBAGENT context (keyed by `agentId`) when `isSidechain` is true.
Real Claude Code transcripts store each dispatched subagent as its own
`subagents/agent-<id>.jsonl` file carrying `isSidechain: true` and an `agentId`; older
transcripts interleave sidechain records in the main file. Keying on `isSidechain` +
`agentId`/`sessionId` (not the source file) attributes both layouts correctly, and falls
back to the source path when the identifying field is absent. The report distinguishes a
main-thread read from a subagent read (per-file and per-context), and never collapses two
contexts reading the same engine file into one count.

The per-context report is scoped to contexts that read at least one engine file; each such
context reports its peak accumulated context — `max` over its turns of
`input_tokens + cache_read_input_tokens + cache_creation_input_tokens` (output excluded) —
or the UNESTABLISHED sentinel when no turn carried a `usage` object (an unmeasured peak is
never collapsed onto a real-looking 0). Read counts are plain counts, so a genuinely-zero
read count reads as 0; only the residency STATISTICS (median/max peak) carry the
UNESTABLISHED sentinel for an empty population.

The parser streams records line by line (it never buffers an entire session into memory)
and degrades per malformed record without detonating, reporting how many records it
skipped and why. It is deterministic: re-running over the same corpus yields byte-identical
output. It writes NO transcript contents and embeds no owner-specific identifiers.

Usage:
    review-context-eval.py <transcript-dir>
                           [--format {text,json}]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

# The two engine-file subtrees (disjoint — neither prefix contains the other). A subtree
# rename must be mirrored here in the same change or reads under it silently stop counting;
# test_prefixes_map_to_real_on_disk_subtrees reconciles these against the on-disk dirs.
ENGINE_PREFIXES = ("skills/review-and-fix/", "skills/review/")

# The sentinel a residency statistic carries when its population is empty. It is NEVER a
# number and NEVER 0 — an unestablished measurement collapsed onto a real value is the bug
# this instrument (like its two siblings) guards against.
UNESTABLISHED = "unestablished"


def _engine_file_key(file_path):
    """The engine-relative key a Read's `file_path` counts under, or None.

    Normalizes the absolute / repo-relative / vendored spellings of one engine file onto a
    single key (the path from `skills/review…` onward), so a read of the same file on
    different tiers counts as the same file. Matches by subtree, not basename.
    """
    if not isinstance(file_path, str) or not file_path:
        return None
    norm = file_path.replace("\\", "/")
    for prefix in ENGINE_PREFIXES:
        if norm.startswith(prefix):
            return norm
        marker = "/" + prefix
        idx = norm.find(marker)
        if idx != -1:
            return norm[idx + 1:]
    return None


def _context_identity(record, source):
    """The (context key, is_subagent) a record belongs to.

    A sidechain record is a subagent thread, keyed by `agentId`; everything else is a
    main-thread thread, keyed by `sessionId`. Falls back to the source-file path when the
    identifying field is absent, so a transcript missing one still separates contexts
    (each real subagent is its own file). The `main:`/`sub:` prefix keeps a sessionId and
    an agentId from ever colliding on one key.
    """
    if record.get("isSidechain") is True:
        agent = record.get("agentId")
        ident = agent if isinstance(agent, str) and agent else "file:" + source
        return "sub:" + ident, True
    sid = record.get("sessionId")
    ident = sid if isinstance(sid, str) and sid else "file:" + source
    return "main:" + ident, False


def _median(values):
    """Deterministic median of a NON-EMPTY list of numbers.

    Refuses an empty population rather than returning 0: this module's central discipline
    is that an unestablished measurement is never collapsed onto a real value.
    `_median_or_unestablished` is the only sanctioned empty-tolerant entry point.
    """
    if not values:
        raise ValueError("median of an empty population")
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    lo, hi = ordered[mid - 1], ordered[mid]
    total = lo + hi
    # Keep an int when the two central values divide evenly so output stays byte-stable.
    return total // 2 if total % 2 == 0 else total / 2


def _median_or_unestablished(values):
    """The median of a non-empty list, else the UNESTABLISHED sentinel (never 0)."""
    return _median(values) if values else UNESTABLISHED


def _max_or_unestablished(values):
    """The max of a non-empty list, else the UNESTABLISHED sentinel (never 0)."""
    return max(values) if values else UNESTABLISHED


def _usage_field(usage, key):
    """Read one usage sub-field, treating null/missing/non-numeric as 0."""
    if not isinstance(usage, dict):
        return 0
    val = usage.get(key)
    if isinstance(val, bool):  # bool is an int subclass; never a token count
        return 0
    if isinstance(val, (int, float)):
        # A non-finite float (json.loads accepts bare Infinity/-Infinity/NaN) is not a token
        # count: int(inf) raises OverflowError, which is outside eval_corpus's per-record
        # backstop tuple and would detonate the whole walk. Treat it as 0, like any other
        # non-numeric value, so one hostile record degrades per-record instead.
        if isinstance(val, float) and not math.isfinite(val):
            return 0
        return int(val)
    return 0


def _context_tokens(usage):
    """Residency tokens = input + cache_read + cache_creation (no output)."""
    return (
        _usage_field(usage, "input_tokens")
        + _usage_field(usage, "cache_read_input_tokens")
        + _usage_field(usage, "cache_creation_input_tokens")
    )


class ContextAccumulator:
    """Streams one context's records and accumulates its metrics.

    Holds only small scalars — a running residency max, a few counters, and a per-engine
    read tally — never full record bodies, so a corpus of any size streams in bounded
    memory (there is one accumulator per context, and contexts are few).

    `skipped` is the caller's corpus-wide skip tally; the accumulator writes the
    `unresolvable_read_path` key into it so a Read whose `file_path` shape is unusable is
    accounted rather than silently read as "not an engine file".
    """

    def __init__(self, context, is_subagent, skipped):
        self.context = context
        self.is_subagent = is_subagent
        self.skipped = skipped
        self.sources = set()
        self.turn_count = 0
        # Running max of per-turn residency; None until a turn carries a usage object, so
        # an all-usage-less context reports UNESTABLISHED rather than a real-looking 0.
        self.peak = None
        self.usage_missing_turns = 0
        self.compact_boundary_count = 0
        # engine-relative key -> number of Read blocks that read that engine file.
        self.engine_reads = {}

    def note_source(self, source):
        self.sources.add(source)

    def observe_system(self, record):
        if record.get("subtype") == "compact_boundary":
            self.compact_boundary_count += 1

    def observe_assistant(self, record):
        self.turn_count += 1
        # A truthy non-dict `message` would make `.get()` raise; `(x or {})` only rescues a
        # falsy value, so isinstance-guard — a well-typed-but-wrong-shape record degrades.
        message = record.get("message")
        if not isinstance(message, dict):
            message = {}
        usage = message.get("usage")
        if isinstance(usage, dict):
            tokens = _context_tokens(usage)
            self.peak = tokens if self.peak is None else max(self.peak, tokens)
        else:
            # No usage object at all: residency was never recorded for this turn. Tally it
            # rather than folding a 0 into the peak (which would drag it down).
            self.usage_missing_turns += 1

        content = message.get("content")
        if not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use" or block.get("name") != "Read":
                continue
            block_input = block.get("input")
            file_path = (block_input.get("file_path")
                         if isinstance(block_input, dict) else None)
            if not isinstance(file_path, str):
                # The path could not be ESTABLISHED, so it is accounted rather than silently
                # read as "not an engine file". A Read of a NON-engine file is a legitimate
                # non-count and is deliberately NOT tallied here.
                self.skipped["unresolvable_read_path"] += 1
                continue
            key = _engine_file_key(file_path)
            if key is not None:
                self.engine_reads[key] = self.engine_reads.get(key, 0) + 1

    def total_engine_reads(self):
        return sum(self.engine_reads.values())

    def result(self):
        """The context record's own fields, engine reads in canonical sorted key order."""
        peak = self.peak if self.peak is not None else UNESTABLISHED
        engine_reads = {k: self.engine_reads[k] for k in sorted(self.engine_reads)}
        return {
            "context": self.context,
            "is_subagent": self.is_subagent,
            "sources": sorted(self.sources),
            "turn_count": self.turn_count,
            "peak_context": peak,
            "usage_missing_turns": self.usage_missing_turns,
            "compact_boundary_count": self.compact_boundary_count,
            "engine_reads": engine_reads,
            "total_engine_reads": self.total_engine_reads(),
        }


def new_skip_tally():
    """A fresh, fully-seeded skip tally.

    The key vocabulary has ONE home here rather than being seeded across the walk, which
    would make an under-seeded dict a KeyError at the far end.
    """
    return {
        "non_json_line": 0,
        "not_object": 0,
        "no_type": 0,
        "unreadable_file": 0,
        "escaped_path": 0,
        "walk_error": 0,
        "malformed_record": 0,
        # A `Read` tool_use whose `input`/`file_path` shape is unusable: the path could not
        # be established, so it is accounted here rather than read as "not an engine file".
        "unresolvable_read_path": 0,
    }


def _iter_session_files(corpus_root, skipped):
    """Yield JSONL session file paths under the corpus root, deterministically.

    Skips any entry whose real path escapes the corpus root (a symlink out), so the eval
    never reads outside the supplied directory. Sorted for determinism. Both walk-level
    drops are TALLIED and breadcrumbed, never silent.
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
                    "warning: skipping session file escaping corpus root {}\n".format(full)
                )
                continue
            collected.append(full)
    collected.sort()
    return collected


def eval_corpus(corpus_root):
    """Return (contexts, engine_files, skipped) for a corpus directory.

    contexts: list of per-context metric dicts, only for contexts that read at least one
        engine file, sorted (main-thread first, then by context key) for determinism.
    engine_files: dict of {engine-relative key: {total, main_thread, subagent}} read
        counts across all reporting contexts.
    skipped: dict of {reason: count} of records AND session files the walk stepped over —
        malformed records, unreadable files, corpus-escaping symlinks, unwalkable
        directories, and Read blocks with an unusable path. Read the per-reason keys: a
        non-zero total is not necessarily "bad transcript data".
    """
    accumulators = {}
    skipped = new_skip_tally()
    for session_file in _iter_session_files(corpus_root, skipped):
        # The source is the CORPUS-RELATIVE path, normalized to forward slashes so the
        # output is host-independent.
        rel_source = os.path.relpath(session_file, corpus_root).replace(os.sep, "/")
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
                if rtype not in ("assistant", "system"):
                    # A record type the walker does not observe (queue-operation, user,
                    # summary): not an engine read and not a parse failure.
                    continue
                # Defensive backstop: the observers isinstance-guard their known field
                # shapes, but an unanticipated record shape must degrade per-record
                # (tallied + breadcrumbed), never detonate the whole corpus walk.
                try:
                    key, is_sub = _context_identity(record, rel_source)
                    acc = accumulators.get(key)
                    if acc is None:
                        acc = ContextAccumulator(key, is_sub, skipped)
                        accumulators[key] = acc
                    acc.note_source(rel_source)
                    if rtype == "assistant":
                        acc.observe_assistant(record)
                    else:
                        acc.observe_system(record)
                except (AttributeError, TypeError, ValueError, KeyError) as exc:
                    skipped["malformed_record"] += 1
                    sys.stderr.write(
                        "warning: skipping malformed {} record at {}:{}: {}: {}\n".format(
                            rtype, session_file, lineno, type(exc).__name__, exc
                        )
                    )
                    continue

    contexts = [acc.result() for acc in accumulators.values()
                if acc.total_engine_reads() > 0]
    # Main-thread contexts first, then by context key — deterministic and readable.
    contexts.sort(key=lambda c: (c["is_subagent"], c["context"]))

    engine_files = {}
    for c in contexts:
        for engine_key, count in c["engine_reads"].items():
            bucket = engine_files.setdefault(
                engine_key, {"total": 0, "main_thread": 0, "subagent": 0})
            bucket["total"] += count
            bucket["subagent" if c["is_subagent"] else "main_thread"] += count
    return contexts, engine_files, skipped


def aggregate(contexts, engine_files):
    """The aggregate summary over the reporting contexts.

    Read COUNTS are plain sums (a genuinely-zero count reads as 0). Only the residency
    STATISTICS carry the UNESTABLISHED sentinel for an empty population — a median/max
    peak over no measured context must never read as a real-looking 0.
    """
    peaks = [c["peak_context"] for c in contexts if c["peak_context"] != UNESTABLISHED]
    main = [c for c in contexts if not c["is_subagent"]]
    sub = [c for c in contexts if c["is_subagent"]]
    return {
        "context_count": len(contexts),
        "main_thread_context_count": len(main),
        "subagent_context_count": len(sub),
        "engine_file_count": len(engine_files),
        "total_engine_reads": sum(c["total_engine_reads"] for c in contexts),
        "main_thread_engine_reads": sum(c["total_engine_reads"] for c in main),
        "subagent_engine_reads": sum(c["total_engine_reads"] for c in sub),
        "total_usage_missing_turns": sum(c["usage_missing_turns"] for c in contexts),
        "median_peak_context": _median_or_unestablished(peaks),
        "max_peak_context": _max_or_unestablished(peaks),
    }


def build_report(corpus_root):
    """One report: reporting contexts, per-engine-file read counts, aggregate, skip tally."""
    contexts, engine_files, skipped = eval_corpus(corpus_root)
    return {
        "contexts": contexts,
        "engine_files": engine_files,
        "summary": aggregate(contexts, engine_files),
        "skipped": skipped,
    }


def _render_context_line(c):
    reads = " ".join(
        "{}={}".format(k, v) for k, v in c["engine_reads"].items())
    kind = "subagent" if c["is_subagent"] else "main-thread"
    return (
        "- {context} [{kind}]: peak={peak} turns={turns} "
        "usage_missing={usage_missing} compactions={compactions} "
        "total_engine_reads={total} engine_reads=[{reads}] "
        "sources={sources}".format(
            context=c["context"], kind=kind, peak=c["peak_context"],
            turns=c["turn_count"], usage_missing=c["usage_missing_turns"],
            compactions=c["compact_boundary_count"], total=c["total_engine_reads"],
            reads=reads, sources=",".join(c["sources"]))
    )


def render_text(contexts, engine_files, summary, skipped):
    lines = []
    lines.append("# review engine per-context read eval")
    lines.append("")
    lines.append("## Per-context engine reads")
    if not contexts:
        lines.append("(no engine-file read found in the supplied corpus)")
    for c in contexts:
        lines.append(_render_context_line(c))
    lines.append("")
    lines.append("## Engine files (read count across all contexts)")
    if not engine_files:
        lines.append("(none)")
    for key in sorted(engine_files):
        bucket = engine_files[key]
        lines.append("- {}: total={} main_thread={} subagent={}".format(
            key, bucket["total"], bucket["main_thread"], bucket["subagent"]))
    lines.append("")
    lines.append("## Aggregate summary")
    # aggregate() builds this dict in the canonical field order, so iterating it renders
    # every field once with no per-field literal to keep in sync.
    for key, value in summary.items():
        lines.append("- {}: {}".format(key, value))
    lines.append("")
    # The axis exclusion (a Read whose path shape was unusable) is reported under its own
    # heading rather than inflating the skipped headline a maintainer reads as "bad
    # transcript data": it is not a parse failure, it removes a block from ONE axis.
    excluded = {"unresolvable_read_path": skipped.get("unresolvable_read_path", 0)}
    record_skips = {k: v for k, v in skipped.items() if k not in excluded}
    lines.append("## Skipped records and files: {}".format(sum(record_skips.values())))
    for reason in sorted(record_skips):
        if record_skips[reason]:
            lines.append("- {}: {}".format(reason, record_skips[reason]))
    lines.append("")
    lines.append("## Dropped from an axis (not a parse failure)")
    lines.append("- Read blocks dropped from the engine-read axis (unresolvable path): "
                 "{}".format(excluded["unresolvable_read_path"]))
    return "\n".join(lines)


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that has
    no usable `reconfigure`."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None):
    _force_utf8_streams()
    parser = argparse.ArgumentParser(
        description="Measure the per-context review-engine read cost of a run.",
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
        sys.stderr.write("error: transcript directory not found: {}\n".format(corpus))
        return 2

    report = build_report(corpus)
    if args.format == "json":
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(render_text(
            report["contexts"], report["engine_files"],
            report["summary"], report["skipped"]) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
