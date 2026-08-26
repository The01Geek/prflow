#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""CI-side assertion-floor retention check (issue #1287).

A test module's assertion floor is carried in two coupled places — `minimum_assertions`
in `scripts/workflow-flight-recorder-registry.json` and the third positional operand at
the `devflow_run_full_suite_module` call site in `lib/test/run.sh`. The suite enforces
that the two AGREE with each other, and that a module's measured tally is not BELOW them.
Only the `exact`-policy modules additionally get a measured equality
(`reconcile-module-floors.py`, `test_module_runner.py`), so for the registered modules
that carry no `assertion_floor_policy` nothing enforces that the floor is not simply
LOWERED: a coordinated edit to both coupled sites, in one diff, is green at the desk and
green in CI. (That population is deliberately named by its defining property rather than
enumerated or counted — it changes as modules are added and re-policed, and a stale list
here would re-rot exactly as the count in issue #1287 did.)
That is coverage loss that leaves no trace in any gate — only in the diff, if someone
reads it.

This check makes a DECREASE a declared act rather than an edit. It runs in CI (so it does
not depend on any local configuration) and at the desk against the same inputs. It compares
each module's `minimum_assertions` in the registry at the merge base against the value in
the working tree (which is HEAD in a fresh CI checkout) and fails when a module present in
BOTH carries a STRICTLY LOWER floor at head — for EVERY registered module, not only the
`exact`-policy subset. The coupled run.sh call-site literal is unchanged by this check; that
half of the coupling already works and stays a separately-enforced pair.

SCOPE — this gate covers a lowered floor, not a removed module. A module present at the
base but absent at head is a module RETIREMENT (its whole coverage story went away with it),
a different act from quietly shrinking a live module's floor, and it is not flagged here.

A legitimate decrease (a module genuinely, deliberately shed assertions — a retired arm, a
merged coverage concern) is declared through the escape hatch
`lib/test/assertion-floor-retention-allow.json`: a JSON array of `{"module", "reason"}`
objects. The escape hatch cannot be satisfied by an empty or absent declaration — a matching
entry must carry a non-empty `reason`.

THREE OUTCOMES, because "I could not establish whether a floor was lowered" is not "no floor
was lowered" (the repository's *unknown is not zero* rule):

  0  clean       — the base comparand WAS established and no floor was lowered.
  1  decrease    — a floor was lowered RELATIVE TO A SOUND COMPARAND (or an input the check
                   needs — the head registry, the allow file — could not be read).
  3  unestablished — the base comparand is degraded, so the comparison proves nothing. This
                   INCLUDES a decrease detected against a SUBSTITUTED comparand (see below).

Exit 3 is deliberately distinct from BOTH 0 and 1 so no caller can read an unestablished
comparand as a clean result, and so a diagnosis never misattributes "the base is missing" as
"a floor was lowered". A degraded base arises on a shallow or partial clone: `git merge-base`
can FAIL outright, or — worse, because it looks healthy — SUCCEED against a truncated commit
graph and hand back a shallow-boundary commit whose tree predates the registry, leaving an
empty base registry and therefore nothing to compare.

A shallow clone is a legitimate desk workflow, so the degraded case is not an unconditional
hard failure: `--allow-degraded-base` is an EXPLICIT, per-invocation acknowledgement that
downgrades exit 3 to exit 0. It is opt-in and never silent — the acknowledged reasons are
printed and the result is reported as an acknowledged degraded run, not a clean pass. The
default direction is what matters: unacknowledged, the check fails closed.

SUBSTITUTED COMPARAND: when `git merge-base` cannot name a commit, `common.merge_base` hands back
BASE_REF's own TIP as the comparand. A decrease found against that tip is NOT an established
loss — BASE_REF may have RAISED a floor after the fork point that this branch legitimately
never had, so the branch's own (lower) value reads as a "decrease" that never happened. So a
decrease detected against a substituted comparand routes through the degraded arm: it is
reported with the substitution named, `--allow-degraded-base` CAN acknowledge it, and the
exit is 3 (or an acknowledged 0), never 1. The invariant that matters is preserved in the
other direction — a decrease found against a SOUND comparand keeps exit 1 and no flag can
acknowledge it away.

CI keeps a real comparand by checking out full history (`fetch-depth: 0`). That coupling
enforces ITSELF: strip `fetch-depth: 0` and this check exits 3 (no merge base / empty base
registry) or 1 (`origin/<base>` unresolvable), so the workflow goes RED instead of silently
losing the protection.

Pure core (`detect_decreases`, `classify_outcome`) so the focused test drives every arm —
including every branch and the arm ORDER of the outcome selection — from in-memory fixtures;
the CLI resolves the base registry through git and reads the head registry from the working
tree.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Import the shared merge-base plumbing whether this file is run as a script from the repo
# root or loaded by path (spec_from_file_location) in the focused test.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import retention_check_common as common

REGISTRY_REL = "scripts/workflow-flight-recorder-registry.json"
ALLOW_REL = "lib/test/assertion-floor-retention-allow.json"
# The three outcomes. `unknown is not zero`: an unestablished base comparand takes a status
# distinct from BOTH the clean pass and the decrease, so no caller can collapse it onto
# either. Kept as named constants because the focused test asserts them by name.
EXIT_CLEAN = 0
EXIT_DECREASE = 1
EXIT_UNESTABLISHED = 3
# The flag that turns exit 3 into an acknowledged exit 0. Named once so the help text, the
# remedy line and the test all quote the same literal.
ACK_FLAG = "--allow-degraded-base"


def _allow_index(allow_value: object) -> tuple[set[str], list[str]]:
    """Return ({module id with a non-empty reason}, [breadcrumbs]).

    A malformed allowlist is fail-closed: it contributes NO permitted decreases and a
    breadcrumb, so a broken escape hatch can never launder a decrease into a pass."""
    permitted: set[str] = set()
    errors: list[str] = []
    if allow_value is None:
        return permitted, errors
    if not isinstance(allow_value, list):
        errors.append(f"{ALLOW_REL} must be a JSON array of {{module, reason}} objects")
        return permitted, errors
    for index, entry in enumerate(allow_value):
        if not isinstance(entry, dict):
            errors.append(f"{ALLOW_REL}[{index}] is not an object")
            continue
        module = entry.get("module")
        reason = entry.get("reason")
        if not isinstance(module, str) or not module:
            errors.append(f"{ALLOW_REL}[{index}] 'module' must be a non-empty string")
            continue
        if not isinstance(reason, str) or not reason.strip():
            # The escape hatch cannot be satisfied by an empty/absent declaration.
            errors.append(
                f"{ALLOW_REL}[{index}] ({module}) carries no non-empty 'reason' — "
                "a legitimate decrease must state why"
            )
            continue
        permitted.add(module)
    return permitted, errors


def _floors(registry: object) -> tuple[dict[str, int] | None, set[str] | None, str | None]:
    """Parse a registry object into (floors, unreadable, error).

    `floors` maps each module id with a readable integer `minimum_assertions` to its value.
    `unreadable` is the set of module ids whose ENTRY is present but whose `minimum_assertions`
    is missing, a bool, or a non-int — the module still exists, but it carries no comparable
    floor. That distinction is load-bearing: a module absent from `floors` for the two reasons
    is NOT the same event (see `detect_decreases`) — an absent ENTRY is a retirement, while a
    present entry with an unreadable floor is the floor's protection being removed while the
    module lives on, the maximal shrink and a loss this gate must catch.

    A registry that is not a well-shaped object, or whose `test_modules` is not an object, is
    an UNESTABLISHED comparand ((None, None, error)) rather than an empty map — reading it as
    'no modules' would launder a decrease into a pass. A module whose entry is not an object is
    ignored entirely (it is not a well-formed module record to reason about)."""
    if not isinstance(registry, dict):
        return None, None, f"{REGISTRY_REL} is not a JSON object — comparand unestablished"
    modules = registry.get("test_modules", {})
    if not isinstance(modules, dict):
        return None, None, f"{REGISTRY_REL} 'test_modules' is not an object — comparand unestablished"
    floors: dict[str, int] = {}
    unreadable: set[str] = set()
    for module_id, mapping in modules.items():
        if not isinstance(mapping, dict):
            continue
        value = mapping.get("minimum_assertions")
        # bool is an int subclass; a JSON true/false is never a valid floor.
        if isinstance(value, bool) or not isinstance(value, int):
            unreadable.add(module_id)
            continue
        floors[module_id] = value
    return floors, unreadable, None


def detect_decreases(
    base_registry: object, head_registry: object, allow_value: object
) -> list[str]:
    """Return floor-decrease violations (empty ⇒ clean). Pure — never raises, never reads a file.

    A base or head registry that is not a well-shaped object contributes a fail-closed
    breadcrumb rather than being read as 'no modules' — an unestablished comparand is never a
    pass. A module present at base but whose ENTRY is entirely absent at head is a RETIREMENT,
    out of scope here, and is not flagged. But a module still present at head whose
    `minimum_assertions` became unreadable (non-int, bool, or removed while the entry lives on)
    is the floor's protection being stripped from a live module — the maximal shrink — and IS
    flagged as a loss."""
    violations: list[str] = []
    permitted, allow_errors = _allow_index(allow_value)
    violations.extend(f"[floor] {e}" for e in allow_errors)

    base_floors, _, base_error = _floors(base_registry)
    if base_error is not None:
        return violations + [f"[floor] base {base_error}"]
    head_floors, head_unreadable, head_error = _floors(head_registry)
    if head_error is not None:
        return violations + [f"[floor] head {head_error}"]

    for module_id in sorted(base_floors):
        if module_id not in head_floors:
            if module_id in head_unreadable:
                # The module still exists at head, but its floor is no longer a readable
                # integer — floor protection removed from a live module (a full shrink).
                if module_id in permitted:
                    continue
                violations.append(
                    f"[floor] module {module_id!r} had assertion floor {base_floors[module_id]} "
                    f"at the merge base but its head `minimum_assertions` is no longer a readable "
                    f"integer (missing, bool, or non-int) while the module entry still exists — "
                    f"floor protection was removed; restore an integer floor, or declare the "
                    f"removal with a reason in {ALLOW_REL}"
                )
                continue
            # Module ENTRY entirely absent at head — a retirement; out of scope, not flagged.
            continue
        base_value = base_floors[module_id]
        head_value = head_floors[module_id]
        if head_value < base_value:
            if module_id in permitted:
                continue
            violations.append(
                f"[floor] module {module_id!r} assertion floor was LOWERED from {base_value} "
                f"to {head_value} in {REGISTRY_REL} (a decrease of {base_value - head_value}) "
                f"— restore the assertions and the floor, or declare the decrease with a "
                f"reason in {ALLOW_REL}"
            )
    return violations


def classify_outcome(
    violations: list[str],
    unestablished: list[str],
    allow_degraded: bool,
    base_ref: str,
    comparand_substituted: bool,
) -> tuple[int, list[str]]:
    """Select the outcome. Pure — the focused test drives every arm and the arm ORDER.

    COMPARAND_SUBSTITUTED says the comparison ran against BASE_REF's own tip rather than a
    computed merge base (see `common.merge_base`). It is what separates arm 1 from arm 2: the same
    violation list is an established decrease against a sound comparand and merely a
    difference against a substituted one.

    Returns (exit status, report lines). Arm order is load-bearing and is asserted:

      1. VIOLATIONS against a SOUND comparand first. The floor really is lower at head
         relative to the true merge base, so the decrease is an ESTABLISHED fact — it
         outranks any degradation that only widens what the comparison might have missed,
         exits 1, and NO flag can acknowledge it away. Any unestablished reasons are appended
         all the same: a decrease is never announced without the context it ran under.
      2. Anything unestablished — INCLUDING violations found against a SUBSTITUTED comparand,
         which are differences rather than established decreases (BASE_REF may have RAISED a
         floor after the fork point that this branch legitimately never had). Nothing here was
         proven, so: exit 3 unless explicitly acknowledged.
      3. Acknowledged degraded run: exit 0, but reported as acknowledged-degraded and never as
         a clean retention pass.
      4. Clean: the comparand was established and no floor was lowered.
    """
    if violations and not comparand_substituted:
        lines = list(violations)
        if unestablished:
            lines.append(
                "[floor] for context, this run ALSO could not establish the following (the "
                "decrease above is measured against the real merge base and stands "
                "regardless):"
            )
            lines.extend(f"[floor]   - {reason}" for reason in unestablished)
        return EXIT_DECREASE, lines
    if violations or unestablished:
        lines = [
            ("[floor] the base comparand could not be established, so this run proves nothing "
            "about assertion-floor retention — it is NOT a clean pass:")
        ]
        lines.extend(f"[floor]   - {reason}" for reason in unestablished)
        if violations:
            lines.append(
                f"[floor] the differences below were detected against a SUBSTITUTE comparand — "
                f"{base_ref}'s own tip, NOT a merge base — so they are NOT established "
                f"decreases: {base_ref} may have RAISED a floor after this branch forked, "
                "which the branch legitimately never had. Treat each as unconfirmed until the "
                "real merge base resolves:"
            )
            lines.extend(violations)
        if not allow_degraded:
            lines.append(
                "[floor] refusing to report a green result from an unestablished comparand "
                "(unknown is not zero). Fetch full history (git fetch --unshallow, or CI's "
                f"fetch-depth: 0) so {base_ref} and the merge base resolve, or re-run with "
                f"{ACK_FLAG} to acknowledge the degraded comparand deliberately."
            )
            return EXIT_UNESTABLISHED, lines
        lines.append(
            f"[floor] {ACK_FLAG} was passed, so the degraded comparand is acknowledged and the "
            "exit status is 0 — this is an acknowledged degraded run, not a verified clean one."
        )
        return EXIT_CLEAN, lines
    return EXIT_CLEAN, [
        f"[floor] no registered module's assertion floor was lowered relative to {base_ref}"
    ]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_root", nargs="?", default=".", help="repository root (default: cwd)")
    parser.add_argument(
        "--base-ref",
        default=None,
        help="the base ref to compare against (default: origin/<base_branch>)",
    )
    parser.add_argument(
        ACK_FLAG,
        dest="allow_degraded",
        action="store_true",
        help=(
            "acknowledge a degraded base comparand (a shallow or partial clone) and exit 0 "
            f"instead of {EXIT_UNESTABLISHED}. The reasons are still printed and the run is "
            "reported as acknowledged-degraded, never as a verified clean pass."
        ),
    )
    args = parser.parse_args(argv[1:])
    repo_root = Path(args.repo_root).resolve()

    base_ref = args.base_ref
    if base_ref is None:
        base_ref = f"origin/{common.read_config_base(repo_root)}"

    # Every reason the base comparand cannot be trusted. Non-empty ⇒ a green result would be a
    # claim the run never established, so it routes to EXIT_UNESTABLISHED.
    unestablished: list[str] = []

    merge_base, mb_error, mb_degraded = common.merge_base(repo_root, base_ref)
    if merge_base is None:
        print(f"[floor] could not establish a merge base against {base_ref}: {mb_error}")
        return EXIT_DECREASE
    if mb_degraded is not None:
        unestablished.append(mb_degraded)

    base_registry, base_error = common.git_show_json(repo_root, merge_base, REGISTRY_REL)
    if base_error is not None:
        print(f"[floor] could not read the base {REGISTRY_REL}: {base_error}")
        return EXIT_DECREASE
    # An empty base comparand inspects nothing and therefore proves nothing. That is the second
    # fail-open shape and the one that looks healthiest: on a shallow clone `git merge-base` can
    # succeed against a truncated graph and name a boundary commit whose tree predates the
    # registry, so the base registry reads as {} and every floor looks retained. It is a
    # degraded comparand, not a pass — even when the registry genuinely did not exist at the
    # base, in which case the acknowledgement flag is the way to say so.
    base_floors, _, _ = _floors(base_registry)
    if base_floors is not None and not base_floors:
        unestablished.append(
            f"the base {REGISTRY_REL} at {merge_base} carried no test-module floors, so there "
            "was nothing to compare against — a degraded comparand, or a base that genuinely "
            "predates the registry"
        )

    head_path = repo_root / REGISTRY_REL
    try:
        head_registry = json.loads(head_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        print(f"[floor] could not read the head {REGISTRY_REL} ({error})")
        return EXIT_DECREASE

    allow_path = repo_root / ALLOW_REL
    allow_value: object = None
    if allow_path.exists():
        try:
            allow_value = json.loads(allow_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            print(f"[floor] {ALLOW_REL} is unreadable ({error}); refusing to treat it as empty")
            return EXIT_DECREASE

    violations = detect_decreases(base_registry, head_registry, allow_value)
    # `mb_degraded` is non-None on exactly the two `common.merge_base` arms that hand back BASE_REF's
    # tip in place of a merge base (rc != 0, and rc 0 naming no commit); the success arm returns
    # None and the OSError arm returns before this line. So this is a direct read of the
    # producer, not an inference: it is true iff the comparison below ran against a substitute.
    comparand_substituted = mb_degraded is not None
    status, lines = classify_outcome(
        violations, unestablished, args.allow_degraded, base_ref, comparand_substituted
    )
    for line in lines:
        print(line)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
