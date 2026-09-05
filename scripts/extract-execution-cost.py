#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""extract-execution-cost.py — normalize the cost half of claude-code-action's
`execution_file` into one JSON object, for the harness-side cost floor (issue #475).

This is the FIRST floor operand in the efficiency-telemetry pipeline that is NOT
agent-volunteered: claude-code-action writes the execution file harness-side, so its
cost figures survive even a run that dropped every telemetry emit. This reader is the
deterministic, stdlib-only normalizer; `lib/efficiency-trace.sh --persist` (never this
script) attaches the result as a per-run `harness_cost` record field.

Usage:
    extract-execution-cost.py <execution-file>

Prints ONE normalized JSON object to stdout:
    {"cost_usd", "tokens": {"input_tokens", "output_tokens",
     "cache_read_input_tokens", "cache_creation_input_tokens", "total_tokens"},
     "model_usage", "num_turns", "duration_ms",
     "peak_main_thread_context", "phase_file_reads"}

`peak_main_thread_context` (integer tokens, or `null` when no main-thread turn carried a
usage object) and `phase_file_reads` (an object keyed by the shared phase labels
(scripts/context_eval_shared.py) plus `total`, or `null` when the file carried no
main-thread record) are computed by the shared measuring core (issue #120). They are instrument outputs only: no
threshold, ceiling, regression rule or gate reads them.

Contract (issue #475 AC1/AC2):
  - Every figure the file does not carry is JSON `null`, NEVER `0` (the repo's
    unknown-is-not-zero rule). A `"costUSD": 0` present in the file yields
    `"cost_usd": 0`; the key absent yields `"cost_usd": null` — the fixture pair.
  - Slurp-tolerant over the observed shapes (single object, JSON array, JSONL, and the
    scrubbed artifact's leading `#` caveat), via the shared reader in
    scripts/context_eval_shared.py (issue #120) — no local caveat-strip or array-then-JSONL
    ladder here.
  - Survives the full adversarial input matrix {object, array, scalar, valid-falsy,
    missing file, wrong-type field, undecodable bytes}: every abnormal shape exits 0 with a SPECIFIC
    stderr breadcrumb. A file that PARSES but carries no figures prints the object with
    those figures `null`; a file that cannot be parsed AT ALL prints nothing.
  - Best-effort: ALWAYS exits 0 (the ensure-label.sh / describe-denial-count.sh
    contract) so the backstop step that runs it is never aborted by a bad file.

The `execution_file` schema is NOT a public contract (only a dated observation of
one action version), so the key lookups below are tolerant and
preference-ordered rather than a brittle single-shape parse.
"""
import json
import os
import sys

# The transcript-record reader and the main-thread measuring core are single-sourced in
# scripts/context_eval_shared.py (issue #120). This file is loaded by path, so insert its
# directory to reach the sibling module.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from context_eval_shared import (
    PHASE_FILES,
    SWEEP_REFERENCE_PHASE,
    SWEEP_REFERENCE_PREFIX,
    SWEEP_REFERENCE_SUFFIX,
    measure_context,
    read_transcript_records,
)

# The five token figures, in the order the normalized object emits them. The first four
# are per-message figures (summable on the per-message fallback path); `total_tokens` is
# a summary figure and is NOT summed on that path — see _fold_usage.
_TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "total_tokens",
)
# Cost is carried under either key across observed action versions; prefer the
# canonical total, fall back to the per-run costUSD. First PRESENT numeric wins, so
# a present `0` is honored (the valid-falsy row) and only a genuinely-absent pair
# yields null.
_COST_KEYS = ("total_cost_usd", "costUSD")


def _is_number(v):
    # bool is a subclass of int — a JSON `true`/`false` is never a cost/token figure.
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _iter_dicts(node):
    """Yield every dict anywhere in the parsed structure (any nesting depth),
    mirroring surface-execution-diagnostics.sh's `.. | objects` descent."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _iter_dicts(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_dicts(v)


def _ordered_dicts(root):
    """All dicts, with result-summary events FIRST so a run-summary figure wins over
    the same key on a streamed message event. `type == "result"` is the summary event
    surface-execution-diagnostics.sh keys on."""
    everything = list(_iter_dicts(root))
    results = [d for d in everything if d.get("type") == "result"]
    others = [d for d in everything if d.get("type") != "result"]
    return results + others


def _find_numeric(dicts, keys, wrong_type):
    """First PRESENT numeric value for any key in `keys`, scanning `dicts` in order.
    Records a (key -> value) note in `wrong_type` when a key is present but non-numeric
    (so the caller can breadcrumb the wrong-type row) — but a present-elsewhere numeric
    still wins. Returns None when no key is present with a numeric value anywhere."""
    for d in dicts:
        for k in keys:
            if k in d:
                v = d[k]
                if _is_number(v):
                    return v
                wrong_type.setdefault(k, v)
    return None


def _read_usage(usage, wrong_type, accumulate):
    """Fold one `usage` dict's token figures into a fresh {key: None} map. When
    `accumulate` is False each figure is taken as-is (the authoritative result total);
    when True figures are summed (per-message fallback). Shared by both regimes below so
    the per-figure numeric/None/wrong-type handling can never drift between them."""
    sums = {k: None for k in _TOKEN_KEYS}
    _fold_usage(usage, sums, wrong_type, accumulate)
    return sums


def _fold_usage(usage, sums, wrong_type, accumulate):
    for k in _TOKEN_KEYS:
        if k not in usage:
            continue
        v = usage[k]
        if _is_number(v):
            if accumulate and k == "total_tokens":
                # `total_tokens` is a summary figure, not a per-message component. On the
                # per-message fallback path we cannot know whether the file emits it
                # per-message or cumulatively, and summing a cumulative field over-counts.
                # Leave it null here (unknown-is-not-zero) rather than publish a possibly
                # inflated total; the authoritative result-summary path reads it as-is.
                continue
            sums[k] = v if not accumulate else (sums[k] or 0) + v
        else:
            wrong_type.setdefault("usage." + k, v)


def _accumulate_tokens(dicts, wrong_type):
    """Return the five token figures for the run. PREFER the result-summary event's
    cumulative `usage` — the authoritative run total, consistent with how cost_usd /
    num_turns / duration_ms read the result event first (unknown-is-not-zero). Sum
    per-message `usage` blocks (excluding the result event) ONLY when no result event
    carries a `usage`: summing the cumulative result `usage` AND every per-message
    `usage` together double-counts the run's tokens (issue #475 review). A figure never
    seen stays None; a figure seen only as 0 is 0; a non-numeric token value is skipped
    and noted."""
    # Authoritative path: a result event's own cumulative usage (dicts is result-ordered
    # first, but match on type explicitly so a non-result usage never wins here).
    for d in dicts:
        if d.get("type") == "result":
            usage = d.get("usage")
            if isinstance(usage, dict):
                return _read_usage(usage, wrong_type, accumulate=False)
    # Fallback: sum per-message usage across the non-result events.
    sums = {k: None for k in _TOKEN_KEYS}
    for d in dicts:
        if d.get("type") == "result":
            continue
        usage = d.get("usage")
        if isinstance(usage, dict):
            _fold_usage(usage, sums, wrong_type, accumulate=True)
    return sums


def _parse(path):
    """Return (records, breadcrumbs, parsed_ok). `records` is the list of transcript record
    dicts the shared reader yielded (or [] when the file parsed but carried none). parsed_ok
    is False only when the file could not be read or parsed at all (prints nothing)."""
    breadcrumbs = []
    try:
        # errors="replace" (like the four sibling shared-reader consumers): undecodable
        # bytes must not crash the best-effort exit-0 reader — they decode to replacement
        # chars, parse as non-JSON, and print nothing (AC "undecodable bytes" matrix case).
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        return [], [f"execution file could not be read ('{path}': {exc})"], False
    if text.strip() == "":
        return [], [f"execution file is empty ('{path}')"], False
    # The shared reader tolerates the scrubbed artifact's leading `#` caveat, a whole-file
    # array/object, and JSONL, in that preference order (issue #120).
    parsed = read_transcript_records(text)
    if not parsed.parsed:
        return [], [f"execution file could not be parsed as JSON or JSONL ('{path}')"], False
    if not parsed.records:
        breadcrumbs.append(
            f"execution file parsed but carried no transcript record ('{path}'); "
            "no figures to extract")
    return parsed.records, breadcrumbs, True


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv):
    _force_utf8_streams()
    if len(argv) != 2:
        sys.stderr.write(
            "devflow: extract-execution-cost.py: expected exactly one argument "
            f"(the execution-file path); got {len(argv) - 1}\n"
        )
        return 0  # best-effort exit-0
    path = argv[1]
    records, breadcrumbs, parsed_ok = _parse(path)
    for b in breadcrumbs:
        sys.stderr.write(f"devflow: extract-execution-cost.py: {b}\n")
    if not parsed_ok:
        # Cannot be parsed at all (missing/empty/garbage) → print NOTHING (AC2).
        return 0

    dicts = _ordered_dicts(records)
    wrong_type = {}
    cost_usd = _find_numeric(dicts, _COST_KEYS, wrong_type)
    num_turns = _find_numeric(dicts, ("num_turns",), wrong_type)
    duration_ms = _find_numeric(dicts, ("duration_ms",), wrong_type)
    tokens = _accumulate_tokens(dicts, wrong_type)
    model_usage = None
    for d in dicts:
        mu = d.get("modelUsage")
        if isinstance(mu, dict):
            model_usage = mu
            break
        if "modelUsage" in d and mu is not None:
            wrong_type.setdefault("modelUsage", mu)

    for key, val in wrong_type.items():
        sys.stderr.write(
            f"devflow: extract-execution-cost.py: field '{key}' is present but not a "
            f"numeric figure ({val!r}); treated as absent (null)\n"
        )

    # A parsed file can carry useful non-cost figures (turns, duration, or tokens) while
    # cost_usd remains unknown. Name that state here; the glue independently refuses a
    # truly all-null payload so it cannot masquerade as cost coverage.
    if cost_usd is None:
        sys.stderr.write(
            "devflow: extract-execution-cost.py: execution file parsed but carried no "
            "cost figure (cost_usd null); any staged harness_cost records no cost this run\n"
        )

    # Peak main-thread context and per-phase read counts via the shared measuring core
    # (issue #120), run over the whole file (no run-boundary concept here). `null` when no
    # main-thread turn carried a usage object / no main-thread record existed — never a 0.
    peak_main_thread_context, phase_file_reads = measure_context(
        records, PHASE_FILES, SWEEP_REFERENCE_PREFIX, SWEEP_REFERENCE_SUFFIX,
        SWEEP_REFERENCE_PHASE)

    normalized = {
        "cost_usd": cost_usd,
        "tokens": tokens,
        "model_usage": model_usage,
        "num_turns": num_turns,
        "duration_ms": duration_ms,
        "peak_main_thread_context": peak_main_thread_context,
        "phase_file_reads": phase_file_reads,
    }
    sys.stdout.write(json.dumps(normalized) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
