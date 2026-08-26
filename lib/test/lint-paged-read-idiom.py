#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Reconcile the paged-read recovery idiom's copies against a registered inventory
(issue #1946).

Why this exists. The paged-read recovery idiom — the instruction that a reader
returning a file in pages (a "partial-view notice" carrying an ``offset``/``limit``
continuation) has not damaged it, so page forward and apply the boundary/marker check
to the assembled whole document — is physically copied across many ``skills/**`` bodies.
The only prose declaration that governed it (``skills/review/SKILL.md``'s *Required copy*
note) named only a subset of sites, while the idiom in fact appears in many more skill
bodies. Those other copies were unregistered and unpinned, so a correction to the idiom
had no mechanism telling a maintainer which files still carried the old form — the exact drift
the issue that filed this lint was born from (``skills/review-and-fix/references/loop-control.md``
carries a deliberately corrected variant that contradicts the other copies' termination
rule, and nothing flagged the divergence).

This is the "reconciled mechanically so a drifted copy is detectable rather than found by
reading" branch of that issue's Desired Behavior: the ``INVENTORY`` below is the machine-
checked required-copy declaration for the idiom's full footprint. Each copy is registered
with its disposition and, for a copy that deliberately stands alone, a stated reason —
so the inventory is the AC2 registration surface and ``--print-inventory`` is its auditable
form. ``skills/review/SKILL.md``'s prose *Required copy* note stays a correct, narrower
statement about the review<->implement boundary-contract mirror; this lint does not
duplicate it into prose.

What FAILS the lint (issue #1946 AC3 — drift is detectable by a check):

* An UNREGISTERED carrier — a ``skills/**`` markdown file that carries the ``partial-view``
  fingerprint but is not in ``INVENTORY``. This is a new or moved copy the maintainer must
  register (or collapse) rather than leave unpinned.
* A VANISHED copy — an enrolled file that no longer carries the fingerprint (deleted,
  renamed, or reworded past recognition). Fails closed rather than silently pass a copy
  that left the population out from under the inventory.
* A WORDING drift — an enrolled file that still carries the fingerprint but whose expected
  termination marker is absent. This catches a copy "corrected" from one termination form
  to the other (the disjunction form <-> the confirming-read form) without re-registering.

PASSES: the tree as it stands, with every enrolled file carrying its fingerprint and its
expected termination marker and no other ``skills/**`` markdown file carrying the
fingerprint.

Population source (issue #1946 AC1 — enumerated by an executed search, not from memory):
an index-reading ``git ls-files`` via the shared ``lint_population`` reader (no ``--others``;
worktree-immune on a bare clone, issue #711), scoped to ``skills/**`` markdown. The
``--files-from`` preamble lets the suite drive RED/GREEN scenarios over a scratch root that
is not a git repository.

Fingerprint scope — the disclosed residual. Detection keys on the literal ``partial-view``,
the distinctive term every existing copy shares and the reliable search fingerprint this
issue identified. A hypothetical future copy that phrases the idiom WITHOUT that term would
not be caught — an inherent limit of any fingerprint search, disclosed rather than papered
over. The audited population is ``skills/**`` markdown only; a copy migrated outside
``skills/`` is out of scope by construction (this lint's own source and its RED/GREEN
scratch material live under ``lib/test/``, which is why the scope is not tree-wide).
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

# The population enumeration, file reader, EnumerationError fail-closed contract, and the
# --root / --files-from preamble are shared with the other git ls-files lints (issue #724),
# loaded by path exactly as the sibling lints do.
_POP_PATH = _REPO_ROOT / "lib" / "test" / "lint_population.py"
_pop_spec = importlib.util.spec_from_file_location("lint_population", _POP_PATH)
_pop = importlib.util.module_from_spec(_pop_spec)
_pop_spec.loader.exec_module(_pop)
_REQUIRED_POP_ATTRS = (
    "EnumerationError", "enumerate_population", "read_source",
    "add_population_arguments", "resolve_root", "LS_FILES_INDEX",
)
_pop_missing = [name for name in _REQUIRED_POP_ATTRS if not hasattr(_pop, name)]
if _pop_missing:
    raise SystemExit(
        f"lint-paged-read-idiom: {_POP_PATH} no longer provides "
        f"{', '.join(_pop_missing)}; refusing to audit"
    )

EnumerationError = _pop.EnumerationError

#: The literal every existing copy shares — the reliable search fingerprint for the idiom.
FINGERPRINT = "partial-view"

#: The registered required-copy declaration for the idiom's full footprint. Each row is
#: (repo-relative path, disposition, termination_marker, reason). ``termination_marker`` is
#: the distinctive substring proving the copy still carries ITS expected termination wording;
#: its absence in a file that still carries the fingerprint is a wording drift. ``reason``
#: records why a copy stands where it does — the AC2 "registered / recorded with a stated
#: reason for standing alone" surface. This is the one hand-maintained value: which files
#: carry the idiom and in which form is a policy record, reconciled against the tree below.
INVENTORY: tuple[tuple[str, str, str, str], ...] = (
    # The declared boundary-contract mirror (skills/review/SKILL.md's prose Required-copy
    # note names these two). Disjunction termination form.
    ("skills/review/SKILL.md", "boundary-contract-mirror", "adds nothing new",
     "canonical boundary-contract copy; prose Required-copy note names it and implement/SKILL.md"),
    ("skills/implement/SKILL.md", "boundary-contract-mirror", "adds nothing new",
     "boundary-contract mirror of skills/review/SKILL.md; edited in the same change"),
    # Independent instances of the same paging idiom (disjunction form) in their own
    # reference/marker contexts.
    ("skills/implement/phases/phase-2-sweeps-contract.md", "idiom-instance", "adds nothing new",
     "gated-sweep marker-contract instance of the disjunction form"),
    ("skills/implement/phases/phase-4-documentation.md", "idiom-instance", "adds nothing new",
     "Phase 4 reference-read instances of the disjunction form"),
    ("skills/create-issue/SKILL.md", "idiom-instance", "adds nothing new",
     "create-issue reference-gate instance of the disjunction form"),
    ("skills/docs-verify/SKILL.md", "idiom-instance", "adds nothing new",
     "docs-verify reference-read instance of the disjunction form"),
    ("skills/review-and-fix/SKILL.md", "idiom-instance", "adds nothing new",
     "review-and-fix engine-bundle instance of the disjunction form"),
    # The corrected confirming-read variant, standing alone with a stated reason: it
    # deliberately rejects the disjunction termination as unsound (PR #1922), so it must NOT
    # be collapsed into the disjunction copies.
    ("skills/review-and-fix/references/loop-control.md", "corrected-variant", "terminates the paging",
     "corrected confirming-read form (PR #1922) that rejects the disjunction as unsound; stands alone deliberately"),
    ("skills/review-and-fix/references/fixing.md", "corrected-variant", "forward to EOF",
     "confirming-read form consistent with loop-control.md's correction; stands alone deliberately"),
)

#: The audited population is markdown under this prefix.
_AUDITED_PREFIX = "skills/"


def audit(root: Path, files_from: Path | None) -> list[str]:
    """Return a list of human-readable failure messages (empty when clean)."""
    failures: list[str] = []
    enrolled = {row[0] for row in INVENTORY}

    # 1. Every enrolled copy is read directly and checked for its fingerprint and its
    #    expected termination marker — independent of the population enumeration, so an
    #    enrolled file is verified even if the enumeration is scoped differently.
    for relpath, _disposition, marker, _reason in INVENTORY:
        text, skip_reason = _pop.read_source(root / relpath, skip_nul=True)
        if text is None:
            failures.append(
                f"{relpath}: enrolled copy could not be read ({skip_reason}) — inventory asserts it exists"
            )
            continue
        if FINGERPRINT not in text:
            failures.append(
                f"{relpath}: enrolled copy no longer carries the '{FINGERPRINT}' fingerprint "
                "(deleted, renamed, or reworded past recognition) — reconcile the inventory"
            )
            continue
        if marker not in text:
            failures.append(
                f"{relpath}: the paged-read idiom's termination wording drifted — expected marker "
                f"'{marker}' is absent though the '{FINGERPRINT}' fingerprint is present; re-register "
                "this copy's form or restore its wording"
            )

    # 2. Enumerate the population and flag any carrier that is not enrolled — a new or moved
    #    copy the maintainer must register rather than leave unpinned.
    try:
        population = _pop.enumerate_population(
            root, files_from, ls_files_argv=_pop.LS_FILES_INDEX
        )
    except EnumerationError as exc:
        failures.append(f"population could not be enumerated: {exc}")
        return failures

    for relpath in population:
        if not (relpath.startswith(_AUDITED_PREFIX) and relpath.endswith(".md")):
            continue
        if relpath in enrolled:
            continue
        text, skip_reason = _pop.read_source(root / relpath, skip_nul=True)
        if text is None:
            # A NUL/binary file cannot carry the ASCII idiom, so skip it; a genuinely
            # UNREADABLE file (OSError) could, so fail closed rather than let a new copy
            # hide behind a read error.
            if skip_reason and skip_reason.startswith("unreadable"):
                failures.append(
                    f"{relpath}: could not be read ({skip_reason}) while scanning for "
                    "unregistered paged-read-idiom copies — fails closed"
                )
            continue
        if FINGERPRINT in text:
            failures.append(
                f"{relpath}: carries the paged-read idiom ('{FINGERPRINT}' fingerprint) but is NOT "
                "in INVENTORY — register it (or collapse it into a pointer) so drift stays detectable"
            )

    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _pop.add_population_arguments(parser)
    parser.add_argument(
        "--print-inventory",
        action="store_true",
        help="Print the registered (path, disposition, marker, reason) inventory and exit 0.",
    )
    args = parser.parse_args(argv)

    if args.print_inventory:
        for relpath, disposition, marker, reason in INVENTORY:
            print(f"{relpath}\t{disposition}\t{marker}\t{reason}")
        return 0

    root = _pop.resolve_root(args.root, tool="lint-paged-read-idiom")
    files_from = Path(args.files_from) if args.files_from else None
    failures = audit(root, files_from)
    if failures:
        for msg in failures:
            print(f"lint-paged-read-idiom: {msg}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
