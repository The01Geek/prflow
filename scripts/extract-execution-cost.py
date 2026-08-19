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
     "model_usage", "num_turns", "duration_ms"}

Contract (issue #475 AC1/AC2):
  - Every figure the file does not carry is JSON `null`, NEVER `0` (the repo's
    unknown-is-not-zero rule). A `"costUSD": 0` present in the file yields
    `"cost_usd": 0`; the key absent yields `"cost_usd": null` — the fixture pair.
  - Slurp-tolerant over the three OBSERVED shapes (single object, JSON array, JSONL),
    mirroring scripts/surface-execution-diagnostics.sh's `-s`/`.. | objects` tolerance.
  - Survives the full adversarial input matrix {object, array, scalar, valid-falsy,
    missing file, wrong-type field}: every abnormal shape exits 0 with a SPECIFIC
    stderr breadcrumb. A file that PARSES but carries no figures prints the object with
    those figures `null`; a file that cannot be parsed AT ALL prints nothing.
  - Best-effort: ALWAYS exits 0 (the ensure-label.sh / describe-denial-count.sh
    contract) so the backstop step that runs it is never aborted by a bad file.

The `execution_file` schema is NOT a public contract (only a dated observation of
one action version), so the key lookups below are tolerant and
preference-ordered rather than a brittle single-shape parse.
"""
import json
import sys

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
    """Return (root, breadcrumbs, parsed_ok). `root` is the parsed structure (or None
    when the file could not be parsed at all). Tolerates a single object, a JSON array,
    or JSONL; a scalar parses (parsed_ok True) but yields no figures."""
    breadcrumbs = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        return None, ["execution file could not be read ('%s': %s)" % (path, exc)], False
    if text.strip() == "":
        return None, ["execution file is empty ('%s')" % path], False
    # Whole-file JSON first (object OR array — the two non-JSONL observed shapes).
    try:
        root = json.loads(text)
        if not isinstance(root, (dict, list)):
            breadcrumbs.append(
                "execution file top-level JSON is a %s scalar, not an object/array; "
                "no figures to extract" % type(root).__name__
            )
        return root, breadcrumbs, True
    except json.JSONDecodeError:
        pass
    # Fall back to JSONL: one JSON value per non-empty line. Any line that parses
    # counts; a file where NO line parses is unparseable-at-all (prints nothing).
    rows = []
    any_ok = False
    for line in text.splitlines():
        if line.strip() == "":
            continue
        try:
            rows.append(json.loads(line))
            any_ok = True
        except json.JSONDecodeError:
            continue
    if any_ok:
        return rows, breadcrumbs, True
    return None, ["execution file could not be parsed as JSON or JSONL ('%s')" % path], False


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8 on the CLI entry path only (not at import, so a
    unit-test import never mutates the importer's streams). A no-op where the ambient
    codec is already UTF-8; self-defends against a non-UTF-8 default codec such as
    Windows cp1252. Tolerates a non-TextIOWrapper stream (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv):
    _force_utf8_streams()
    if len(argv) != 2:
        sys.stderr.write(
            "devflow: extract-execution-cost.py: expected exactly one argument "
            "(the execution-file path); got %d\n" % (len(argv) - 1)
        )
        return 0  # best-effort exit-0
    path = argv[1]
    root, breadcrumbs, parsed_ok = _parse(path)
    for b in breadcrumbs:
        sys.stderr.write("devflow: extract-execution-cost.py: %s\n" % b)
    if not parsed_ok:
        # Cannot be parsed at all (missing/empty/garbage) → print NOTHING (AC2).
        return 0

    dicts = _ordered_dicts(root)
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
            "devflow: extract-execution-cost.py: field '%s' is present but not a "
            "numeric figure (%r); treated as absent (null)\n" % (key, val)
        )

    # A parsed file can carry useful non-cost figures (turns, duration, or tokens) while
    # cost_usd remains unknown. Name that state here; the glue independently refuses a
    # truly all-null payload so it cannot masquerade as cost coverage.
    if cost_usd is None:
        sys.stderr.write(
            "devflow: extract-execution-cost.py: execution file parsed but carried no "
            "cost figure (cost_usd null); any staged harness_cost records no cost this run\n"
        )

    normalized = {
        "cost_usd": cost_usd,
        "tokens": tokens,
        "model_usage": model_usage,
        "num_turns": num_turns,
        "duration_ms": duration_ms,
    }
    sys.stdout.write(json.dumps(normalized) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
