#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""CI-side cloud-writer manifest mutation check (issue #1445).

`scripts/devflow-cloud-writer-contract.json` is written on `main` alone: the merge-to-main
job `.github/workflows/version-consolidate.yml` regenerates it immediately before its bump
commit, and no feature branch regenerates it (its `regenerate-artifacts.py` batched-pass row
was removed). A feature branch is therefore expected to leave the artifact byte-for-byte as
it stands at the merge base, with ONE exemption (issue #1606): it may ADD entries for skill
assets it adds, because the closure check and the key-set equality assertion leave such a
branch no other green state. This check enforces that: it compares the manifest at the merge
base against the manifest in the working tree (HEAD in a fresh CI checkout) and fails when
they differ other than by added asset entries — a changed or dropped entry, or any change
outside the asset map, is a divergent pair authored by hand on a branch. That is this check's
whole scope: it does NOT cover the staleness window a changeset-less pinned-file merge leaves
(see docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md, "Known residual").

It runs in CI (so it needs no local git configuration — the chosen mechanism registers no
merge driver) and at the desk against the same inputs. On `main` itself the merge base of
HEAD and origin/<base> is HEAD's own history, so the manifest at the base equals the manifest
in the tree and the check is clean; version-consolidate.yml's legitimate rewrite is never
flagged, because it lands on `main` where there is nothing ahead of the base to compare.

THREE OUTCOMES, because "I could not establish whether the branch mutated it" is not "the
branch did not mutate it" (the repository's *unknown is not zero* rule):

  0  clean         — the base comparand WAS established and the manifest either is unchanged
                     or differs ONLY by asset entries the head adds.
  1  mutated       — the manifest changes or drops an entry the merge base carries, or
                     changes anything outside the asset map, against a SOUND comparand (or
                     an input the check needs could not be read).
  3  unestablished — the base comparand is degraded (a shallow/partial clone substitutes
                     the base ref's own tip), so a difference proves nothing.

Exit 3 is deliberately distinct from BOTH 0 and 1 so no caller reads an unestablished
comparand as clean and no diagnosis misattributes "the base is a substitute tip" as "the
branch mutated the artifact". A shallow clone is a legitimate desk workflow, so
`--allow-degraded-base` is an EXPLICIT, per-invocation acknowledgement that downgrades exit 3
to exit 0; it is never silent (the reasons are printed and the run is reported as
acknowledged-degraded). CI keeps a real comparand with `fetch-depth: 0`, so the default
direction is fail-closed.

Pure core (`detect_mutation`, `classify_outcome`) so the focused test drives every reachable arm — and
the arm ORDER of the outcome selection — from in-memory fixtures; the CLI resolves the base
manifest through git and reads the head manifest from the working tree.
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

MANIFEST_REL = "scripts/devflow-cloud-writer-contract.json"
# The three outcomes. Named constants because the focused test asserts them by name.
EXIT_CLEAN = 0
EXIT_MUTATED = 1
EXIT_UNESTABLISHED = 3
# The flag that turns exit 3 into an acknowledged exit 0. Named once so the help text, the
# remedy line and the test all quote the same literal.
ACK_FLAG = "--allow-degraded-base"


ASSET_KEY = "files"


def _is_asset_addition_only(base_manifest: dict, head_manifest: dict) -> bool:
    """True when the head differs from the base ONLY by asset entries the head adds.

    Do not relax this to permit a changed or dropped fingerprint: that is the overwrite of
    `main`'s record the caller exists to stop, and no other check can see it. An unrecognised
    manifest shape returns False, routing to the violation arm rather than this exemption."""
    def outside_assets(manifest):
        return {k: v for k, v in manifest.items() if k != ASSET_KEY}

    if outside_assets(base_manifest) != outside_assets(head_manifest):
        return False
    base_assets = base_manifest.get(ASSET_KEY)
    head_assets = head_manifest.get(ASSET_KEY)
    if not isinstance(base_assets, dict) or not isinstance(head_assets, dict):
        return False
    # An empty base asset map would make the survival test below vacuously true, letting any
    # head asset map through. A base that records nothing is unestablished, not clean.
    if not base_assets and head_assets:
        return False
    return all(head_assets.get(path) == digest for path, digest in base_assets.items())


def detect_mutation(base_manifest: object, head_manifest: object) -> list[str]:
    """Return violations (empty ⇒ unchanged). Pure — never raises, never reads a file.

    A base or head that is not a well-shaped object contributes a fail-closed breadcrumb
    rather than being read as 'unchanged' — an unestablished comparand is never a pass. The
    comparison is deep JSON equality, so a re-ordered or re-indented but semantically
    identical manifest is NOT flagged; only a genuine content change is.

    One delta shape is permitted (issue #1606): a head that adds asset entries and changes
    nothing else. Every top-level key outside the asset map must be identical, and every
    fingerprint the base carries must survive; only the asset map may gain entries. Do NOT widen this to a delta that
    touches an existing entry: a rewritten fingerprint is the silent overwrite of `main`'s
    record this check exists to stop, and no other check can see it."""
    if not isinstance(base_manifest, dict):
        return [f"[cloud-writer-retain] base {MANIFEST_REL} is not a JSON object — comparand unestablished"]
    if not isinstance(head_manifest, dict):
        return [f"[cloud-writer-retain] head {MANIFEST_REL} is not a JSON object — comparand unestablished"]
    if base_manifest == head_manifest:
        return []
    if _is_asset_addition_only(base_manifest, head_manifest):
        return []
    base_assets = base_manifest.get(ASSET_KEY)
    head_assets = head_manifest.get(ASSET_KEY)
    if not isinstance(base_assets, dict) or not isinstance(head_assets, dict):
        # Distinct from the changed-entry arm below: telling an author to revert an entry
        # change misdirects them when the manifest lost its asset map altogether.
        return [
            (f"[cloud-writer-retain] {MANIFEST_REL} has no readable `{ASSET_KEY}` map on one "
            "side — comparand unestablished, so a difference proves nothing about what the "
            "branch changed. Restore the manifest's shape and re-run.")
        ]
    return [
        (f"[cloud-writer-retain] {MANIFEST_REL} changes or drops an entry the merge-base "
        "manifest already carries — a feature branch may only ADD entries for skill assets it "
        "adds (the artifact is otherwise written on `main` alone, by "
        ".github/workflows/version-consolidate.yml). Revert your change to the existing "
        "entries; their digests are regenerated on `main` from the merged tree.")
    ]


def classify_outcome(
    violations: list[str],
    unestablished: list[str],
    allow_degraded: bool,
    base_ref: str,
    comparand_substituted: bool,
) -> tuple[int, list[str]]:
    """Select the outcome. Pure — the focused test drives every reachable arm and the arm ORDER.

    COMPARAND_SUBSTITUTED says the comparison ran against BASE_REF's own tip rather than a
    computed merge base (see `common.merge_base`). It separates arm 1 from arm 2: the same
    difference is an established mutation against a sound comparand and merely an unconfirmed
    difference against a substituted one.

    Returns (exit status, report lines). Arm order is load-bearing and is asserted:

      1. VIOLATIONS against a SOUND comparand first — an established mutation, exit 1, no
         flag can acknowledge it away. Unestablished reasons are appended for context.
      2. Anything unestablished — INCLUDING a difference found against a SUBSTITUTED
         comparand, which is unconfirmed (BASE_REF may have advanced past the fork point).
         Nothing here was proven: exit 3 unless explicitly acknowledged.
      3. Acknowledged degraded run: exit 0, reported as acknowledged-degraded.
      4. Clean: the comparand was established and the manifest is unchanged.
    """
    if violations and not comparand_substituted:
        lines = list(violations)
        # Not dead code: `main()` cannot reach this append (its only `unestablished` source
        # also sets comparand_substituted), but the focused test drives it directly to pin
        # arm 1's precedence over arm 2. Deleting it would delete that proof.
        if unestablished:
            lines.append(
                "[cloud-writer-retain] for context, this run ALSO could not establish the "
                "following (the mutation above is measured against the real merge base and "
                "stands regardless):"
            )
            lines.extend(f"[cloud-writer-retain]   - {reason}" for reason in unestablished)
        return EXIT_MUTATED, lines
    if violations or unestablished:
        lines = [
            ("[cloud-writer-retain] the base comparand could not be established, so this run "
            "proves nothing about branch-side mutation — it is NOT a clean pass:")
        ]
        lines.extend(f"[cloud-writer-retain]   - {reason}" for reason in unestablished)
        if violations:
            lines.append(
                f"[cloud-writer-retain] the difference below was detected against a "
                f"SUBSTITUTE comparand — {base_ref}'s own tip, NOT a merge base — so it is "
                f"NOT an established mutation: {base_ref} may have regenerated the manifest "
                "after this branch forked. Treat it as unconfirmed until the real merge base "
                "resolves:"
            )
            lines.extend(violations)
        if not allow_degraded:
            lines.append(
                "[cloud-writer-retain] refusing to report a green result from an "
                "unestablished comparand (unknown is not zero). Fetch full history (git fetch "
                f"--unshallow, or CI's fetch-depth: 0) so {base_ref} and the merge base "
                f"resolve, or re-run with {ACK_FLAG} to acknowledge the degraded comparand "
                "deliberately."
            )
            return EXIT_UNESTABLISHED, lines
        lines.append(
            f"[cloud-writer-retain] {ACK_FLAG} was passed, so the degraded comparand is "
            "acknowledged and the exit status is 0 — an acknowledged degraded run, not a "
            "verified clean one."
        )
        return EXIT_CLEAN, lines
    return EXIT_CLEAN, [
        f"[cloud-writer-retain] {MANIFEST_REL} retains every entry {base_ref} carries"
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
            f"instead of {EXIT_UNESTABLISHED}. The reason is still printed and the run is "
            "reported as acknowledged-degraded, never as a verified clean pass."
        ),
    )
    args = parser.parse_args(argv[1:])
    repo_root = Path(args.repo_root).resolve()

    base_ref = args.base_ref
    if base_ref is None:
        base_ref = f"origin/{common.read_config_base(repo_root)}"

    # Every reason the base comparand cannot be trusted. Non-empty ⇒ a green result would be
    # a claim the run never established, so it routes to EXIT_UNESTABLISHED.
    unestablished: list[str] = []

    merge_base, mb_error, mb_degraded = common.merge_base(repo_root, base_ref)
    if merge_base is None:
        print(f"[cloud-writer-retain] could not establish a merge base against {base_ref}: {mb_error}")
        return EXIT_MUTATED
    comparand_substituted = mb_degraded is not None
    if mb_degraded is not None:
        unestablished.append(mb_degraded)

    base_manifest, base_error = common.git_show_json(repo_root, merge_base, MANIFEST_REL)
    if base_error is not None:
        print(f"[cloud-writer-retain] could not read the base {MANIFEST_REL}: {base_error}")
        return EXIT_MUTATED

    head_path = repo_root / MANIFEST_REL
    try:
        head_manifest = json.loads(head_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        print(f"[cloud-writer-retain] could not read the head {MANIFEST_REL} ({error})")
        return EXIT_MUTATED

    violations = detect_mutation(base_manifest, head_manifest)
    status, report = classify_outcome(
        violations, unestablished, args.allow_degraded, base_ref, comparand_substituted
    )
    for line in report:
        print(line)
    return status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
