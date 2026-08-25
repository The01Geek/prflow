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

import math
import os
import sys

# The sentinel a per-field / proxy figure carries when the operand it needs could not be
# established. NEVER a number and NEVER 0 — an unestablished measurement collapsed onto a
# real value is the bug this whole axis guards against (issue #1899).
UNESTABLISHED = "unestablished"

# The residency-axis usage sub-fields `_context_tokens` sums (input + cache read + cache
# creation, no output).
RESIDENCY_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


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
    """Yield JSONL session file paths under the corpus root, deterministically.

    Skips an entry whose real path escapes the corpus root (a symlink out), so the eval
    never reads outside the supplied directory. Sorted for determinism.

    Both walk-level drops are TALLIED and breadcrumbed, never silent (mirroring the
    per-record and unreadable-file skip discipline): a `.jsonl` whose real path escapes the
    corpus root is counted under `escaped_path`, and a directory-walk error (a
    permission-denied dir, a vanished tree) is counted under `walk_error` via the `os.walk`
    `onerror` callback — default `onerror=None` would swallow it.

    The caller supplies a `skipped` dict already carrying both keys (every in-tree caller
    pairs this with its own `new_skip_tally()`). Do NOT `setdefault`/`defaultdict` them
    here: an under-populated dict would then tally into a key the caller never emits, so
    the drop becomes invisible in the output — the KeyError is the fail-closed direction.
    """
    root_real = os.path.realpath(corpus_root)
    collected = []

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
            if not name.endswith(".jsonl"):
                continue
            full = os.path.join(dirpath, name)
            real = os.path.realpath(full)
            if real != root_real and not real.startswith(root_real + os.sep):
                # A symlink (or other entry) whose real path escapes the corpus root: never
                # read, but tally + breadcrumb so the drop is visible, not silent.
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
