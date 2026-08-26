#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Fail the suite when an ENROLLED cloud-reachable prompt-surface call site emits the
unexpanded ``${CLAUDE_SKILL_DIR:-…}`` anchor as a helper's leading token WITHOUT also
carrying the granted repo-relative vendored-literal leading-token form as its fallback
arm (issue #1124).

Why this exists. The cloud permission matcher denies the portable anchor
``"${CLAUDE_SKILL_DIR:-…}"/../../scripts/<helper>`` as a leading token — recorded in
``CLAUDE.md`` (leading-token position) and observed in run ``30695072336`` (argument
position). A call site the cloud tier actually executes must therefore emit the granted
vendored literal ``.prflow/vendor/prflow/scripts/<helper>`` FIRST (the #1256
tier-agnostic procedure), keeping the anchor line as the fallback arm for the
local/editor and non-Claude-Code tiers where the vendored path does not exist. The
remedy is the CONDITIONAL form, NOT a blanket replacement of the anchor.

Deliberately NOT a blanket fence-static rule against the anchor (ruling consequence 2 /
issues #1152/#1153: such a rule "would flag every call site"). The anchor stays
legitimately present in source as the fallback arm, and this lint never flags the
anchor's mere presence. Instead it is INVENTORY-DRIVEN: it audits only the explicitly
enrolled cloud-reachable call sites in ``ENROLLED`` — the review engine's
consumer-prompt-extension loads that the merge-gating cloud review tier executes and
that were the evidenced denial class. Enrolling a site is the deliberate act that
brings it under the "vendored literal to invoke, anchor as fallback" discipline; the
~100 other anchor-source invocations across ``skills/**`` (workpad.py, config-get.sh,
…) are the sanctioned #275/#701 single-source form and are out of scope until a future
change makes each cloud-reachable, at which point it is enrolled here.

MATCHED SHAPE (the thing that FAILS the lint). For an enrolled ``(relpath, suffix)``
pair, the file carries the anchor leading-token form of ``suffix`` — a line whose first
non-whitespace token is ``"${CLAUDE_SKILL_DIR:-…}"/../../scripts/<suffix>`` — but does
NOT carry the granted vendored-literal leading-token form — a line whose first
non-whitespace token is ``.prflow/vendor/prflow/scripts/<suffix>``. That is exactly
"anchor as leading token with no fallback arm".

PASSES (each): a site carrying BOTH forms (the remediated conditional shape); a site
carrying only the vendored literal; a site the anchor form is absent from (nothing to
require a fallback for). A missing enrolled file, an unreadable file, or an enrolled
site carrying NEITHER form fails closed — the enrollment asserts the call site exists.

Exit status is 0 only when every enrolled file was read and every enrolled site either
carries both forms or carries neither the anchor nor the vendored form (vacuous, which
also fails — see below). It is non-zero when an enrolled site emits the anchor with no
vendored fallback, when an enrolled file is missing/unreadable, or when the inventory
is empty.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: The enrolled cloud-reachable call sites. Each is a (repo-relative path, invocation
#: suffix) pair. ``suffix`` is the part after ``scripts/`` — i.e. the helper basename
#: plus its literal argument — so ``load-prompt-extension.sh review`` and
#: ``load-prompt-extension.sh receiving-code-review`` are distinct enrolled sites in the
#: same file. This is the one hand-maintained value: which sites are cloud-reachable is
#: a policy scope, not a fact derivable from the tree.
ENROLLED: tuple[tuple[str, str], ...] = (
    ("skills/review/SKILL.md", "load-prompt-extension.sh review"),
    ("skills/review-and-fix/SKILL.md", "load-prompt-extension.sh review-and-fix"),
    ("skills/review-and-fix/SKILL.md", "load-prompt-extension.sh receiving-code-review"),
    # Enrolled at issue #1264, when the render-time injection change gave this file the
    # vendored-literal fallback arm it previously lacked: its extension load had been the
    # bare anchor alone, relying on that skill's global resolve-at-emission override
    # rather than on a written ladder. The remaining bare-anchor call sites under
    # skills/ stay out of scope per this module's inventory-driven docstring above —
    # enrollment tracks cloud-reachability, which is a policy scope, not a tree fact.
    ("skills/implement/SKILL.md", "load-prompt-extension.sh implement"),
    ("skills/implement/phases/phase-3-review.md", "apply-pr-triggerer.sh <draft-pr-number>"),
    # Enrolled at issue #1655, which added the Phase 3.1 provenance-line render fence.
    # The helper is invoked on the cloud implement tier, so an anchor-only spelling
    # would be refused there; it carries the vendored-literal leading token with the
    # bare anchor as its fallback arm.
    ("skills/implement/phases/phase-3-review.md", "render-pr-provenance-line.py"),
    # Enrolled at issue #1374, which put Phase 4.0.5's filing procedure behind this
    # presence predicate. The predicate runs on the cloud implement tier on every run
    # that reaches Phase 4, so an anchor-only spelling would be refused there, route to
    # the unestablished arm, and read the reference the gate exists to skip.
    ("skills/implement/phases/phase-4-documentation.md",
     "discover-deferral-manifests.py --presence-for-pr <this-run's-PR-number>"),
    # Enrolled at issue #1560, which added the Phase 4.3 fenced verification-flight call
    # site. Both helpers are invoked on the cloud implement tier, so an anchor-only spelling
    # would be refused there; the fence carries the vendored-literal leading token with the
    # portable anchor as its fallback arm. Each suffix is the bare helper basename (not a
    # basename-plus-argument, as the neighbouring rows use) because the fence carries several
    # subcommand lines and the enrollment is about the helper, not one call.
    ("skills/implement/phases/phase-4-documentation.md", "verification-flight.py"),
    ("skills/implement/phases/phase-4-documentation.md", "checkout-fingerprint.py"),
    # Enrolled at issue #1557. Reached on the cloud implement tier whenever a named
    # documentation deliverable is absent, so an anchor-only spelling would be refused
    # there and the repair would go unrecorded.
    ("skills/implement/references/doc-deliverable-self-heal.md",
     "workpad.py update $ISSUE_NUMBER --note"),
    # Enrolled at issue #1432. These four extension loads are reached on the cloud
    # implement tier — pr-description via the /prflow:implement Phase 4.2 PR-description
    # subagent, and the three docs children via the Phase 4.1 docs subagent — yet
    # shipped with the bare anchor alone, so their consumer policy was silently
    # dropped there. The vendored-literal-first conditional arm fixes both the matcher
    # denial and the subagent unresolvable-anchor case (each of these loads now runs
    # inside a subagent that receives no $CLAUDE_SKILL_DIR).
    ("skills/pr-description/SKILL.md", "load-prompt-extension.sh pr-description"),
    ("skills/docs-sync-internal/SKILL.md", "load-prompt-extension.sh docs-sync-internal"),
    ("skills/docs-sync-external/SKILL.md", "load-prompt-extension.sh docs-sync-external"),
    ("skills/docs-release-notes/SKILL.md", "load-prompt-extension.sh docs-release-notes"),
    # Enrolled with the docs-audit bootstrap pass: /prflow:init dispatches this skill as
    # a subagent that receives no $CLAUDE_SKILL_DIR, the same unresolvable-anchor case
    # as the four #1432 rows above, so the vendored-literal-first arm must stay present.
    ("skills/docs-bootstrap-internal/SKILL.md",
     "load-prompt-extension.sh docs-bootstrap-internal"),
    # Enrolled with the docs-router hardening pass: the router runs inside implement
    # Phase 4.1's docs subagent, which receives no $CLAUDE_SKILL_DIR — the same
    # unresolvable-anchor case as the #1432 rows — so its extension load carries the
    # vendored-literal-first arm with the anchor as fallback.
    ("skills/docs/SKILL.md", "load-prompt-extension.sh docs"),
)

#: The portable source anchor prefix (issue #275), byte-identical to the ``lpe-coverage``
#: pin literal in ``lib/test/run.sh`` and to what every enrolled SKILL.md carries.
_ANCHOR_PREFIX = (
    '"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in '
    'context>}"/../../scripts/'
)

#: The granted vendored-literal prefix — the leading token the cloud matcher grants.
_VENDORED_PREFIX = ".prflow/vendor/prflow/scripts/"


def _leading_token_present(lines: list[str], prefix: str, suffix: str) -> bool:
    """True when some line's first non-whitespace token is ``prefix + suffix``.

    Matched as a leading token (the invocation form), never as a substring anywhere in
    the line, so a prose mention of the path inside a sentence never counts.
    """
    needle = prefix + suffix
    for raw in lines:
        stripped = raw.lstrip()
        if stripped.startswith(needle):
            # Confirm it is the invocation, not a longer path that merely shares the
            # prefix: the char after the suffix must end the token (EOL/space) so a
            # different-argument sibling (`… review-and-fix` vs `… review`) is not
            # matched by the shorter suffix.
            rest = stripped[len(needle):]
            if rest == "" or rest[0].isspace():
                return True
    return False


def audit(root: Path) -> list[str]:
    """Return a list of human-readable failure messages (empty when clean)."""
    failures: list[str] = []
    if not ENROLLED:
        return ["inventory is empty — the lint would be vacuous; refusing"]
    # An enrolled path may carry more than one suffix (review-and-fix/SKILL.md holds two
    # loads), so read + split each file at most once and reuse the lines for every suffix.
    lines_by_path: dict[str, list[str] | None] = {}
    for relpath, suffix in ENROLLED:
        if relpath not in lines_by_path:
            try:
                lines_by_path[relpath] = (root / relpath).read_text(
                    encoding="utf-8"
                ).splitlines()
            except FileNotFoundError:
                lines_by_path[relpath] = None
                failures.append(f"{relpath}: enrolled file is missing")
            except (OSError, UnicodeDecodeError) as exc:
                lines_by_path[relpath] = None
                failures.append(f"{relpath}: enrolled file could not be read ({exc})")
        lines = lines_by_path[relpath]
        if lines is None:
            continue
        has_anchor = _leading_token_present(lines, _ANCHOR_PREFIX, suffix)
        has_vendored = _leading_token_present(lines, _VENDORED_PREFIX, suffix)
        if not has_anchor and not has_vendored:
            # The enrollment asserts this call site exists in a recognizable form; if
            # neither form is present the site was renamed/removed out from under the
            # inventory, so fail closed rather than silently pass a vanished site.
            failures.append(
                f"{relpath}: enrolled site '{suffix}' carries NEITHER the anchor nor the "
                "vendored-literal leading-token form — inventory is stale"
            )
            continue
        if has_anchor and not has_vendored:
            failures.append(
                f"{relpath}: '{suffix}' is invoked via the unexpanded "
                "${CLAUDE_SKILL_DIR:-…} anchor as a leading token with NO vendored-literal "
                f"fallback arm — add the granted '.prflow/vendor/prflow/scripts/{suffix}' "
                "leading-token form (issue #1124)"
            )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=str(_REPO_ROOT),
        help="Repository root to audit (default: this file's repo root).",
    )
    parser.add_argument(
        "--print-inventory",
        action="store_true",
        help="Print the enrolled (path, suffix) inventory and exit 0.",
    )
    args = parser.parse_args(argv)

    if args.print_inventory:
        for relpath, suffix in ENROLLED:
            print(f"{relpath}\t{suffix}")
        return 0

    failures = audit(Path(args.root))
    if failures:
        for msg in failures:
            print(f"lint-anchor-fallback-arm: {msg}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
