#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Cloud-writer reachability contract (AC1) + runtime-manifest producer (AC18).

Why this exists (issue #543, deferred half of #533): bundled-helper skill call
sites are authored around the portable ``${CLAUDE_SKILL_DIR:-…}`` anchor while
the cloud permission matcher grants only repo-relative
``.prflow/vendor/prflow/`` leading tokens. There was no machine-auditable
source of truth for *which* skill/phase assets a cloud writer session reaches,
and no runtime manifest a workflow preflight could validate before the agent
boots. This module is that source of truth.

It declares, as checked-in data:

* ``ROOTS`` — the three cloud execution roots (the workflow that dispatches the
  first skill and the entry skill it dispatches).
* ``DISPATCH_EDGES`` — every classified transitive edge out of a root: direct
  dispatch, nested skill invocation, inline engine reuse, and Phase-4 Agent-tool
  subagents (the documentation subagent and the PR-description subagent).
* ``SKILL_ASSETS`` — for every skill in the closure, the repository-owned
  reachable assets a cloud writer session can read: the ``SKILL.md`` plus
  whichever asset family a skill actually uses — ``phases/*.md`` (implement,
  review), ``references/*.md`` (review-and-fix's fix-loop procedure), or
  top-level reviewer prose (``requesting-code-review/code-reviewer.md``).
* ``REQUIRED_HELPER_HEADS`` — per cloud profile, the exact vendored leading
  tokens the profile grants (the executable trust boundary).

``check_closure()`` is the AC1 guard: it fails when a root or a dispatch edge
names a skill that is not classified in ``SKILL_ASSETS``, when a dispatch edge
carries an unknown ``kind``, when a classified asset (or a required helper's
source file) does not exist on disk, when a reachable ``*.md`` asset exists on
disk under a classified skill but is not listed (the reverse-drift check, which
covers ``phases/``, ``references/``, and top-level reviewer prose alike), or
when ``REQUIRED_HELPER_HEADS`` and ``ROOTS`` name different profile sets.
``build_manifest()`` renders the AC18
``devflow-cloud-writer-contract-v1`` manifest from this same data, so the manifest
can never silently drift from the closure it claims to describe.
"""
from __future__ import annotations

import fnmatch
import hashlib
import importlib.util
import json
import re
from pathlib import Path

# Repo root: this file is lib/test/cloud_writer_contract.py.
REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_sibling(module_name, filename):
    """Import a hyphenated sibling helper in lib/test/ by path.

    `lib/test/` carries no package `__init__.py` and its helpers are named with
    hyphens, so a plain import cannot reach them. This copies the dynamic-load
    idiom extract-command-shapes.py uses to reach extract-command-heads.py; no
    loader in this tree is exported for reuse (each caller rolls its own).
    """
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    # `spec_from_file_location` returns None when it can find no loader for the
    # path's SUFFIX — not when the file is merely absent. A missing `.py` sibling
    # still yields a spec and fails at `exec_module` with a FileNotFoundError that
    # already names the path, so that case needs no help. This guard covers the
    # None/loaderless case, where the alternative is `AttributeError: 'NoneType'
    # object has no attribute 'loader'` at IMPORT of this module — which
    # scripts/validate-cloud-writer-contract.py imports in its pre-agent validator.
    # Loud but unactionable; name the path instead.
    if spec is None or spec.loader is None:
        raise ImportError(f"devflow: cannot load sibling helper {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_shapes = _load_sibling("extract_command_shapes", "extract-command-shapes.py")
# Reach extract-command-heads.py through the instance _shapes ALREADY loaded
# rather than exec-ing that module a second time. Beyond the duplicate import
# cost (this module is imported by scripts/validate-cloud-writer-contract.py's
# pre-agent validator), a second exec would produce a DISTINCT module object, so
# the two guards would only agree about what a fenced command, a statement, and
# an allowlist region are by coincidence of identical source. Sharing one
# instance makes that agreement structural.
_heads = _shapes._heads

PROTOCOL = "devflow-cloud-writer-contract-v1"

# The immediately preceding supported workflow profile set (AC18
# `legacy_profile_baseline`). Consumers older than this refresh workflows and
# plugin content together before their next cloud-writer run (see docs/internal/install.md).
#
# Cadence rule (issue #1034): advance this baseline whenever a change alters the
# granted helper-head set of any profile in lib/capability-profiles.json, and
# re-snapshot the frozen legacy grants that move with it
# (`_FROZEN_LEGACY_GRANTS` in lib/test/test_python_scripts.py) in the same change.
# A newly-granted head becomes a REQUIRED_HELPER_HEADS member only once the
# baseline advances past the release that first shipped it — deferring registration
# until then is what keeps the AC19 pairing-2 invariant (an N-1 workflow paired
# with the current plugin still validates cleanly) satisfiable. This is authoring
# guidance at its single source; the mechanical gate is the pairing-2 fixture
# going RED, not a wording pin.
LEGACY_PROFILE_BASELINE = "2.31.16"

# The one repo-relative prefix a cloud-reached bundled helper is granted under.
VENDOR_PREFIX = ".prflow/vendor/prflow/"

# --- AC1: cloud execution roots ------------------------------------------------
# Each root is a cloud writer entry surface: the workflow that dispatches the
# first skill, plus that entry skill. Keyed by the profile id the matcher grants
# under (implement / light-command / review).
ROOTS = {
    "implement": {
        "workflow": ".github/workflows/devflow-implement.yml",
        "entry_skill": "implement",
    },
    "light-command": {
        # devflow.yml is the light command-listener. It fires on a bare
        # /devflow:review, /devflow:review-and-fix, or /devflow:pr-description
        # comment and NEVER on /devflow:implement — every trigger negates it
        # (the partition invariant), and the heavy implement path lives in
        # devflow-implement.yml under the "implement" root. Its writer entry is
        # therefore review-and-fix (the command that pushes fixes); the other two
        # dispatched commands (review, pr-description) are covered by direct edges.
        "workflow": ".github/workflows/devflow.yml",
        "entry_skill": "review-and-fix",
    },
    "review": {
        "workflow": ".github/workflows/devflow-runner.yml",
        "entry_skill": "review",
    },
}

# --- AC1: classified transitive dispatch edges ---------------------------------
# Every edge OUT of a root's closure. `kind` classifies the reach:
#   direct   — a slash-command the light-command listener can dispatch
#   nested   — a Skill-tool invocation from within a skill
#   inline   — the shared review engine executed inline under the caller's profile
#   docs     — a Phase-4 Agent-tool subagent (the documentation subagent, and the
#              PR-description subagent, which share the dispatch-and-by-path-handoff
#              shape and differ from a `nested` Skill-tool invocation)
DISPATCH_KINDS = frozenset({"direct", "nested", "inline", "docs"})
DISPATCH_EDGES = [
    {"from": "implement", "to": "review", "kind": "inline"},
    {"from": "implement", "to": "review-and-fix", "kind": "nested"},
    {"from": "implement", "to": "pr-description", "kind": "docs"},
    {"from": "implement", "to": "docs", "kind": "docs"},
    # The docs Agent-tool subagent (implement Phase 4.1) invokes the docs skill,
    # which in turn invokes docs-sync-internal / docs-sync-external /
    # docs-release-notes via the Skill tool (skills/docs/SKILL.md). Those three
    # sub-skills carry the ${CLAUDE_SKILL_DIR:-…} anchors this manifest exists to
    # pin, so they are part of the reachable closure (they invoke no further
    # skills). Omitting them would leave the "every reached asset" contract false.
    {"from": "docs", "to": "docs-sync-internal", "kind": "nested"},
    {"from": "docs", "to": "docs-sync-external", "kind": "nested"},
    {"from": "docs", "to": "docs-release-notes", "kind": "nested"},
    {"from": "review", "to": "requesting-code-review", "kind": "nested"},
    {"from": "review-and-fix", "to": "review", "kind": "inline"},
    {"from": "review-and-fix", "to": "requesting-code-review", "kind": "nested"},
    {"from": "review-and-fix", "to": "receiving-code-review", "kind": "nested"},
    # The three writer commands the light-command listener (devflow.yml) dispatches.
    {"from": "light-command", "to": "review-and-fix", "kind": "direct"},
    {"from": "light-command", "to": "review", "kind": "direct"},
    {"from": "light-command", "to": "pr-description", "kind": "direct"},
]

# --- AC1: classified skill assets ----------------------------------------------
# Every skill the closure reaches, mapped to its repository-owned reachable
# assets (relative to REPO_ROOT). A root or edge naming a skill absent here is an
# AC1 violation (check_closure).
SKILL_ASSETS = {
    "implement": [
        "skills/implement/SKILL.md",
        "skills/implement/phases/phase-1-setup.md",
        "skills/implement/phases/phase-2-implement.md",
        "skills/implement/phases/phase-2-sweeps-contract.md",
        "skills/implement/phases/phase-2-sweeps-quality.md",
        "skills/implement/phases/phase-3-review.md",
        "skills/implement/phases/phase-3-fix-loop.md",
        "skills/implement/phases/phase-3-ac-gate.md",
        "skills/implement/phases/phase-4-documentation.md",
        # issue #815: Phase 4.0's follow-up-issue procedure is reached through a
        # predicate-gated reference, so it is a reachable asset even though most
        # runs never load it. `unlisted_skill_assets` globs `*.md` under a
        # classified skill recursively, so leaving it out is reported as an
        # unclassified reachable asset rather than silently unpinned.
        "skills/implement/references/deferred-ac-followups.md",
        # issue #1374: Phase 4.0.5's deferred-review-finding filing procedure is
        # reached the same way, through its own presence predicate.
        "skills/implement/references/deferred-review-findings.md",
        # issue #1557: Phase 4.1 Stage 2's self-heal repair procedure is reached the
        # same way, through its own absent-path predicate.
        "skills/implement/references/doc-deliverable-self-heal.md",
        # issue #1581: do not drop a gated sweep reference on the grounds that most
        # runs never load it — an unlisted reachable asset is an AC1 closure violation.
        "skills/implement/references/sweep-2-3-0-changed-contract.md",
        "skills/implement/references/sweep-2-3-0a-peer-checkpoint.md",
        "skills/implement/references/sweep-2-3-0b-enum-enumeration.md",
        "skills/implement/references/sweep-2-3-0c-operand-trace.md",
        "skills/implement/references/sweep-2-3-0d-describing-prose.md",
        "skills/implement/references/sweep-2-3-1-orphaned-setup.md",
        "skills/implement/references/sweep-2-3-2-stranded-dependents.md",
        "skills/implement/references/sweep-2-3-7-collection-cardinality.md",
    ],
    "review": [
        "skills/review/SKILL.md",
        "skills/review/phases/phase-0-setup.md",
        "skills/review/phases/phase-0-3-6-blocker-recheck.md",
        "skills/review/phases/phase-0-6-stale-prose-lint.md",
        "skills/review/phases/phase-1-checklist.md",
        "skills/review/phases/phase-2-verification.md",
        "skills/review/phases/phase-3-agents.md",
        "skills/review/phases/phase-4-verdict.md",
        "skills/review/phases/phase-4-1-7-stale-adjudication.md",
        "skills/review/phases/phase-4-4-github-post.md",
    ],
    # review-and-fix has NO phases/ dir — its fix-loop procedure lives in
    # references/*.md that skills/review-and-fix/SKILL.md reads at runtime (and
    # several carry the ${CLAUDE_SKILL_DIR:-…} anchors this manifest exists to
    # pin), so they are reachable assets and must be classified/pinned.
    "review-and-fix": [
        "skills/review-and-fix/SKILL.md",
        "skills/review-and-fix/references/convergence.md",
        "skills/review-and-fix/references/error-handling.md",
        "skills/review-and-fix/references/fix-delta-gate.md",
        "skills/review-and-fix/references/fixing.md",
        "skills/review-and-fix/references/loop-control.md",
        "skills/review-and-fix/references/loop-exit.md",
        "skills/review-and-fix/references/pre-fix-gates.md",
        "skills/review-and-fix/references/shadow-review.md",
    ],
    # requesting-code-review's SKILL.md dispatches the reviewer persona prose in
    # code-reviewer.md — a reachable top-level (non-phases) asset.
    "requesting-code-review": [
        "skills/requesting-code-review/SKILL.md",
        "skills/requesting-code-review/code-reviewer.md",
    ],
    "receiving-code-review": ["skills/receiving-code-review/SKILL.md"],
    "docs": ["skills/docs/SKILL.md"],
    "docs-sync-internal": ["skills/docs-sync-internal/SKILL.md"],
    "docs-sync-external": ["skills/docs-sync-external/SKILL.md"],
    "docs-release-notes": ["skills/docs-release-notes/SKILL.md"],
    "pr-description": ["skills/pr-description/SKILL.md"],
}

# --- AC18: per-profile required helper heads -----------------------------------
# The vendored leading tokens each cloud profile must grant — a *required subset*
# of the workflow `--allowed-tools` / TOOLS grants (each profile grants a superset
# of infrastructure helpers too). Validator class 17 (HEAD_ABSENT) asserts each of
# these is actually granted. These are the executable trust boundary the runtime
# manifest pins.
REQUIRED_HELPER_HEADS = {
    "implement": [
        ".prflow/vendor/prflow/scripts/run-jq.sh",
        ".prflow/vendor/prflow/scripts/config-get.sh",
        ".prflow/vendor/prflow/scripts/workpad.py",
        ".prflow/vendor/prflow/scripts/parse-acs.py",
        ".prflow/vendor/prflow/scripts/branch-for-issue.py",
        ".prflow/vendor/prflow/scripts/update-branch-checkpoint.sh",
        # Phase 3.1's existing-PR resolver (scripts/resolve-existing-pr.sh, issue #782),
        # registered at the issue-#1034 baseline bump: the baseline now advances past the
        # release that shipped it, so the AC19 pairing-2 invariant (an N-1 workflow paired
        # with the current plugin still validates cleanly) is satisfied by the re-snapshotted
        # frozen legacy grants rather than broken by this head.
        ".prflow/vendor/prflow/scripts/resolve-existing-pr.sh",
        ".prflow/vendor/prflow/scripts/file-deferrals.py",
        # Phase 4.0.5's discovery step, invoked in the SAME fence as
        # file-deferrals.py above (issue #555). Registered alongside it so the
        # deferrals pipeline's two helpers share one trust boundary: pinning the
        # filing half while leaving the discovery half out is the asymmetry a
        # reader would take for a deliberate exclusion rather than an omission.
        ".prflow/vendor/prflow/scripts/discover-deferral-manifests.py",
        ".prflow/vendor/prflow/scripts/match-deferrals.py",
        ".prflow/vendor/prflow/scripts/resolve-review-overrides.py",
        ".prflow/vendor/prflow/scripts/apply-labels.sh",
        ".prflow/vendor/prflow/scripts/ensure-label.sh",
        # Phase 4.0's GitHub-native blocked-by dependency stamp
        # (scripts/apply-issue-dependencies.py, issue #1011), registered at the
        # issue-#1034 baseline bump alongside resolve-existing-pr.sh above: the
        # baseline now advances past the release that shipped it, so the AC19
        # pairing-2 invariant holds via the re-snapshotted frozen legacy grants.
        ".prflow/vendor/prflow/scripts/apply-issue-dependencies.py",
        ".prflow/vendor/prflow/scripts/stale-prose-lint.py",
        ".prflow/vendor/prflow/scripts/dismiss-stale-rejections.sh",
        ".prflow/vendor/prflow/scripts/match-lint-adjudications.py",
        ".prflow/vendor/prflow/scripts/load-prompt-extension.sh",
        # The prompt-extension render wrapper (scripts/render-prompt-extension.sh,
        # issue #1264). PRs #1471 and #1473 removed every render-time `!`…``
        # placeholder, so no entry SKILL.md reaches it today; the grant is retained
        # deliberately rather than narrowed, since removing it is a security-boundary
        # change. Registered at the
        # issue-#1359 baseline bump: it first shipped in 2.31.13, and the baseline now
        # advances past that release, so the AC19 pairing-2 invariant (an N-1 workflow
        # paired with the current plugin still validates cleanly) is satisfied by the
        # re-snapshotted frozen legacy grants rather than broken by this head. Its
        # basename-wildcard companion grant is sanctioned per profile below.
        ".prflow/vendor/prflow/scripts/render-prompt-extension.sh",
        ".prflow/vendor/prflow/scripts/react-to-trigger.sh",
        ".prflow/vendor/prflow/scripts/extract-doc-needed-paths.sh",
        ".prflow/vendor/prflow/lib/efficiency-trace.sh",
    ],
    # Note the absent apply-labels.sh / ensure-label.sh: those are implement-only
    # (Phases 3.1/4.0/4.1). devflow.yml dispatches only review-and-fix /
    # review / pr-description — none applies labels — and grants no label helper,
    # so requiring one here would fail class 17 (HEAD_ABSENT) against a grant the
    # profile correctly does not carry. (Completeness of this per-profile list vs.
    # what the reached skills actually invoke is the deferred grant-sync work, AC9.)
    "light-command": [
        ".prflow/vendor/prflow/scripts/run-jq.sh",
        ".prflow/vendor/prflow/scripts/config-get.sh",
        ".prflow/vendor/prflow/scripts/workpad.py",
        ".prflow/vendor/prflow/scripts/parse-acs.py",
        ".prflow/vendor/prflow/scripts/branch-for-issue.py",
        ".prflow/vendor/prflow/scripts/update-branch-checkpoint.sh",
        ".prflow/vendor/prflow/scripts/file-deferrals.py",
        ".prflow/vendor/prflow/scripts/match-deferrals.py",
        ".prflow/vendor/prflow/scripts/match-lint-adjudications.py",
        ".prflow/vendor/prflow/scripts/resolve-review-overrides.py",
        ".prflow/vendor/prflow/scripts/stale-prose-lint.py",
        ".prflow/vendor/prflow/scripts/dismiss-stale-rejections.sh",
        ".prflow/vendor/prflow/scripts/load-prompt-extension.sh",
        # The prompt-extension render wrapper (issue #1264), registered at the
        # issue-#1359 baseline bump like its implement-profile sibling above. The
        # render-time placeholders that reached it were removed by PRs #1471/#1473;
        # the grant is retained deliberately. Its basename-wildcard companion grant
        # is sanctioned per profile below.
        ".prflow/vendor/prflow/scripts/render-prompt-extension.sh",
        ".prflow/vendor/prflow/lib/efficiency-trace.sh",
    ],
    "review": [
        ".prflow/vendor/prflow/scripts/run-jq.sh",
        ".prflow/vendor/prflow/scripts/match-deferrals.py",
        ".prflow/vendor/prflow/scripts/match-lint-adjudications.py",
        ".prflow/vendor/prflow/scripts/dismiss-stale-rejections.sh",
        ".prflow/vendor/prflow/scripts/workpad.py",
        ".prflow/vendor/prflow/scripts/config-get.sh",
        ".prflow/vendor/prflow/scripts/load-prompt-extension.sh",
        # The prompt-extension render wrapper (issue #1264), registered at the
        # issue-#1359 baseline bump like its siblings above. The render-time
        # placeholder the review engine's entry SKILL.md used was removed by PRs
        # #1471/#1473; the grant is retained deliberately. Its basename-wildcard
        # companion grant is sanctioned per profile below.
        ".prflow/vendor/prflow/scripts/render-prompt-extension.sh",
        ".prflow/vendor/prflow/scripts/resolve-review-overrides.py",
        ".prflow/vendor/prflow/scripts/stale-prose-lint.py",
        ".prflow/vendor/prflow/lib/efficiency-trace.sh",
    ],
}

# ── Protected import-closure sources (issue #1087) ──────────────────────────────
# Repo-relative `scripts/` sources the cloud writer's trust boundary reaches by
# Python IMPORT closure rather than as a granted vendored leading token, so they
# cannot enter through REQUIRED_HELPER_HEADS (whose members must be granted heads,
# and whose additions break the AC19 frozen-baseline pairing invariant). This table
# feeds manifest_file_paths() directly so their bytes are hashed in the runtime
# trust manifest and any mutation is a HASH_MISMATCH:
#   * workpad.py's terminal `--status Complete` evidence gate lazily imports
#     check-completion-evidence.py, which imports reception_identity.py (the
#     candidate-identity producer the gate re-derives against);
#   * workpad.py also imports section_parse.py (a pre-existing, previously unpinned
#     import sibling, pinned in the same pass).
# These are repo-relative (`scripts/...`), not vendored leading tokens: they are
# hashed, never granted.
PROTECTED_IMPORT_SOURCES = (
    "scripts/check-completion-evidence.py",
    "scripts/reception_identity.py",
    "scripts/section_parse.py",
)


def reachable_skills(root=None):
    """Transitive closure of skills reachable via DISPATCH_EDGES.

    An edge's ``from`` is either a root id (a direct dispatch out of a workflow
    root, e.g. the light-command listener) or an already-reached skill.

    With ``root`` omitted the closure spans every root (the AC1 whole-closure
    question). With ``root`` set to one ROOTS profile id the closure is that
    profile's alone — the per-profile reach AC4's shape audit needs, because a
    command's *execution profile* decides which probe-anchored rule table governs
    it, and a shared skill (the review engine) is reached under more than one.
    """
    if root is not None and root not in ROOTS:
        raise ValueError(f"unknown root profile: {root!r}")
    sources = ROOTS if root is None else {root: ROOTS[root]}
    reached = {r["entry_skill"] for r in sources.values()}
    # Seed edges whose source is a root id (roots are not skills). Use .get() so a
    # malformed edge missing `from`/`to` never crashes here — check_closure()
    # reports it as a violation instead (a well-formed edge always has both).
    for edge in DISPATCH_EDGES:
        if edge.get("from") in sources and edge.get("to") is not None:
            reached.add(edge["to"])
    # Fixpoint over skill->skill edges (edges are few; iterate to convergence).
    changed = True
    while changed:
        changed = False
        for edge in DISPATCH_EDGES:
            if edge.get("from") in reached and edge.get("to") not in reached and edge.get("to") is not None:
                reached.add(edge["to"])
                changed = True
    return reached


def check_closure():
    """AC1 guard. Return a list of human-readable violations (empty == OK).

    Fails when a reached skill is unclassified, when an edge/root names an
    unknown skill, when an edge carries an unknown ``kind``, when a classified
    asset or a required helper's source file does not exist on disk, when a
    ``phases/*.md`` file on disk under a classified skill is not listed (the
    reverse-drift check), or when ``REQUIRED_HELPER_HEADS`` and ``ROOTS`` name
    different profile sets.
    """
    errors = []
    classified = set(SKILL_ASSETS)

    # Every dispatch edge must carry from/to/kind, and kind must be a classified
    # reach kind. Missing from/to is reported here (fail-soft) rather than crashing
    # the guard with a KeyError in the subscript loops below.
    for edge in DISPATCH_EDGES:
        for field in ("from", "to"):
            if not edge.get(field):
                errors.append(f"dispatch edge {edge!r} is missing required field '{field}'")
        if edge.get("kind") not in DISPATCH_KINDS:
            errors.append(
                f"dispatch edge {edge.get('from')}->{edge.get('to')} has unknown "
                f"kind {edge.get('kind')!r} (not one of {sorted(DISPATCH_KINDS)})"
            )

    # REQUIRED_HELPER_HEADS must name exactly the ROOTS profile set.
    if set(REQUIRED_HELPER_HEADS) != set(ROOTS):
        errors.append(
            "REQUIRED_HELPER_HEADS profiles "
            f"{sorted(REQUIRED_HELPER_HEADS)} != ROOTS profiles {sorted(ROOTS)}"
        )

    # Every root's entry skill must be classified.
    for rid, root in ROOTS.items():
        if root["entry_skill"] not in classified:
            errors.append(
                f"root '{rid}' entry_skill '{root['entry_skill']}' is not "
                f"classified in SKILL_ASSETS"
            )

    # Every edge's `to` must be a classified skill; its `from` must be a
    # classified skill or a known root id. (A from/to-less edge was already
    # reported above; skip it here so this loop never subscripts a missing key.)
    for edge in DISPATCH_EDGES:
        src, dst = edge.get("from"), edge.get("to")
        if not src or not dst:
            continue
        if src not in classified and src not in ROOTS:
            errors.append(
                f"dispatch edge {src}->{dst} has unknown "
                f"source '{src}' (not a classified skill or root id)"
            )
        if dst not in classified:
            errors.append(
                f"dispatch edge {src}->{dst} names unclassified target skill '{dst}'"
            )

    # Every reached skill must be classified (a root/edge added without
    # classifying the reached asset is the AC1 failure).
    for skill in sorted(reachable_skills()):
        if skill not in classified:
            errors.append(f"reached skill '{skill}' is not classified in SKILL_ASSETS")

    # Every classified asset must exist on disk.
    for skill, assets in SKILL_ASSETS.items():
        for rel in assets:
            if not (REPO_ROOT / rel).is_file():
                errors.append(f"classified asset for '{skill}' missing on disk: {rel}")

    # Every required helper's source file must exist on disk, so `check` reports
    # a rename/removal cleanly instead of `generate`/`verify` crashing with an
    # uncaught FileNotFoundError from sha256_of().
    for profile, heads in REQUIRED_HELPER_HEADS.items():
        for token in heads:
            try:
                rel = _helper_source_path(token)
            except ValueError as exc:
                errors.append(f"profile '{profile}' helper token invalid: {exc}")
                continue
            if not (REPO_ROOT / rel).is_file():
                errors.append(
                    f"profile '{profile}' required helper missing on disk: {rel}"
                )

    # Every reachable .md asset on disk under a classified skill must be listed.
    # The listed-assets-exist check above is one-directional (it never notices a
    # NEW on-disk asset), so a reachable asset added without classifying would
    # otherwise leave the closure green — exactly the AC1 drift this guard exists
    # to catch.
    errors.extend(unlisted_skill_assets())

    return errors


def unlisted_skill_assets():
    """Reachable ``*.md`` assets on disk under a classified skill that are not listed.

    Globs every ``*.md`` under ``skills/<skill>/`` (recursively) other than the
    skill's own ``SKILL.md`` — so ``phases/*.md`` (implement, review),
    ``references/*.md`` (review-and-fix), and top-level reviewer prose
    (``requesting-code-review/code-reviewer.md``) are all covered. Globbing a
    single asset family (the old phases-only check) left every other reachable
    family structurally invisible to the reverse-drift guard.
    """
    missing = []
    for skill, assets in SKILL_ASSETS.items():
        skill_dir = REPO_ROOT / "skills" / skill
        if not skill_dir.is_dir():
            continue
        skill_md = f"skills/{skill}/SKILL.md"
        listed = set(assets)
        for md_file in sorted(skill_dir.rglob("*.md")):  # tree-walk-ok: scoped to one skill directory, never the repository root
            rel = md_file.relative_to(REPO_ROOT).as_posix()
            if rel == skill_md:
                continue
            if rel not in listed:
                missing.append(f"skill '{skill}' has an unclassified reachable asset on disk: {rel}")
    return missing


# --- AC9: grant synchronization ------------------------------------------------
# The AC1-closure per-profile reachable helper literals (REQUIRED_HELPER_HEADS)
# must each be granted in that profile's workflow as the exact vendored leading
# token, and no OTHER grant covering a reachable helper may WIDEN the executable
# trust boundary — by an absolute path, a repo-root path, a basename-wildcard, or
# a directory/blanket glob IN THE GRANT'S COMMAND-POSITION TOKEN.
# check_grant_sync() enforces both directions over the three cloud profiles keyed
# by ROOTS.
#
# KNOWN, DELIBERATE SCOPE LIMITS — three surfaces this guard does not measure.
# Each is disclosed because an undisclosed non-goal reads as a closed hole.
#
# (i) Interpreter and wrapper grants. _ANY_BASH_GRANT_RE reads only the grant's
# leading command-position token, so Bash(python3:*) yields 'python3', which
# neither glob-matches a vendored literal nor shares a reachable basename — yet
# it can execute every reachable helper (`python3 .prflow/vendor/prflow/
# scripts/workpad.py …`). The same blindness covers any wrapper head. This is
# not an oversight detection could simply close: every live profile grants at
# least one interpreter head — `env` in all three, `python3` in implement and
# light-command (the review profile deliberately grants NO python3 head; do not
# "restore" one) — so flagging that class would turn the guard RED on the healthy
# tree. AC9's stated scope is the path classes above; bounding the interpreter
# surface is a separate policy question, tracked in the #650 follow-up. The same
# leading-token truncation also hides a widened path in WRAPPER ARGUMENT
# position: `Bash(python3 /home/x/workpad.py:*)` enumerates as `python3`, so the
# absolute path beside it is never classified.
#
# (ii) RETIRED by issue #678. The on-disk grant read is now scoped to the
# profile's own grant-bearing region (see GRANT_REGION_EXTRACTORS and
# _scope_grant_region below), so a vendored literal named in a `run:` echo or a
# doc string no longer satisfies arm (1) for a helper the profile does not
# actually grant. Do NOT restore the whole-file read believing it is parity with
# the runtime validator's extract_profile_grants: that parity was the fail-open
# direction, not the contract. The residual divergence runs the safe way — this
# guard reads a NARROWER source than the validator (a region of the file, not the
# whole file) and strips inline comments the validator keeps, so its vendored
# grant set can never be a superset of the validator's. It is not a *strict*
# subset: on the healthy tree the two sets are EQUAL for all three profiles
# (re-derive rather than trusting this note — the point is the direction, which
# holds by construction, not the coincidence, which does not).
#
# (iii) Consumer-spliced grants. devflow-implement.yml's --allowed-tools baseline
# is followed by a `${{ needs.config.outputs.allowed_tools_extra }}` splice, so a
# consumer's prflow_implement.allowed_tools entries never appear in the file
# this guard reads. A widened grant added there is outside the measured surface.
#
# (iv) Injected grant sources. check_grant_sync's `profile_grants` parameter is a
# test-injection seam for ALREADY-SCOPED regions and is returned unscoped. A caller
# passing a whole workflow through it is refused (see _looks_like_whole_workflow),
# but that detection is one-sided — a workflow whose leading keys fall outside the
# characteristic set is not detected and its grants pool whole-file. Only the
# on-disk read is region-scoped unconditionally.
#
# Do not read arm (2) as "no grant can reach a helper" — it is "no PATH-SHAPED
# grant IN THE COMMITTED WORKFLOW is broader than the vendored literal".
#
# Why the generated workflow and not lib/capability-profiles.json (the manifest
# those literals are generated FROM): the rendered literal is what the cloud
# runner's matcher actually reads, so it is the surface a widening would have to
# reach to matter. Manifest-vs-literal parity is separately enforced in this same
# suite by `python3 lib/generate-capability-profiles.py --check` (#561), so
# reading the rendered side loses nothing and measures the real boundary. Do not
# "fix" this into a manifest read.
#
# Scoped-home note (deviates from issue #650's AC9 wording "the command-head
# test", which names lib/test/extract-command-heads.py's comment-aware scoper as
# the eventual home; see the workpad AC-rewrite/deviation note). This slice ships
# AC9 alone: it lives here, on the AC1-closure module that OWNS REQUIRED_HELPER_HEADS
# and ROOTS. Re-homing onto extract-command-heads.py's authoritative
# comment-aware parser is coupled with the deferred AC3 leading-token guard
# (which uses that parser) and is tracked in the #650 follow-up, not built
# half-way here.
#
# Arm (1) below (a reachable literal with no explicit vendored grant) is the
# same defect class the runtime validator reports as class 17 (HEAD_ABSENT) in
# scripts/validate-cloud-writer-contract.py. Neither is redundant: the validator
# grades the checked-in manifest at runtime, this guard grades the AC1 closure
# against the live workflows at desk/CI time and additionally owns arm (2)
# (widening), which the validator has no equivalent of. Retire neither believing
# the other is the sole owner.
#
# Grant-shape regexes, mirroring validate-cloud-writer-contract.py's _GRANT_RE for
# the vendored form. Both anchor on `Bash(` so a vendored path that appears only in
# a comment or a shell assignment is never counted as a grant (the same fail-open
# guard the validator's _GRANT_RE documents).
# A properly-scoped vendored grant: the exact tight trust boundary. Its
# `(?:scripts|lib)` alternation is COUPLED to REQUIRED_HELPER_HEADS: a head added
# under any other vendored subdirectory would match neither this regex (so arm (1)
# would fire on a helper that IS correctly granted) nor the vendored-grant skip in
# arm (2) (so the real grant would also be flagged as a widening) — one omission,
# two false positives. The coupling is asserted in lib/test/test_python_scripts.py
# rather than left to a reader, so widening the alternation is forced in lockstep.
_VENDORED_GRANT_RE = re.compile(
    r"Bash\(\s*(\.prflow/vendor/prflow/(?:scripts|lib)/[A-Za-z0-9._-]+)"
)
# Any `Bash(<spec>)` grant's command-position path token (up to the first `:` /
# `)` / whitespace). Used to enumerate every grant so a widened one covering a
# reachable helper can be detected — a vendored-only regex is blind to exactly
# the widened classes AC9 must reject.
_ANY_BASH_GRANT_RE = re.compile(r"Bash\(\s*([^\s:)]+)")

# Deliberately-sanctioned basename-wildcard grants (NOT widening defects),
# **keyed per profile**. Every profile grants Bash(*/load-prompt-extension.sh:*)
# and Bash(*/render-prompt-extension.sh:*) ALONGSIDE the explicit vendored
# literals (lib/capability-profiles.json): both the prompt-extension loader and
# its render wrapper are reached through the portable ${CLAUDE_SKILL_DIR:-…}
# anchor, which can resolve to a non-vendored absolute path on some runners, so
# each wildcard is an intentional companion to its tight grant, not a replacement
# of it. (The implement profile carries only the render-wrapper wildcard, because
# its workflow grants no load-prompt-extension wildcard — the table mirrors each
# profile's actual grants rather than a uniform set.)
#
# The per-profile keying is load-bearing, not tidiness. A profile's sanctioned
# set names exactly the basename wildcards ITS workflow grants and no others: a
# global exemption set would wave a wildcard through on a profile whose workflow
# does not grant it — re-opening, for that profile, exactly the basename-wildcard
# widening arm (2) exists to reject. The implement profile now carries a sanctioned
# render-wrapper wildcard (issue #1359) because devflow-implement.yml grants that
# exact companion; it still grants no load-prompt-extension wildcard, so that one
# stays out of its set. An unknown profile gets an EMPTY exemption set (see the
# `.get(profile, frozenset())` read), so the failure direction of a future profile
# addition is fail-closed.
SANCTIONED_WILDCARD_GRANTS = {
    "implement": frozenset({"*/render-prompt-extension.sh"}),
    "light-command": frozenset({"*/load-prompt-extension.sh", "*/render-prompt-extension.sh"}),
    "review": frozenset({"*/load-prompt-extension.sh", "*/render-prompt-extension.sh"}),
}


# How each profile's grant-bearing region is located inside its workflow (issue
# #678, AC9-residual). The two extractors are extract-command-heads.py's — the
# authoritative scopers the #363 head pins already rely on — never a second
# hand-rolled parser here:
#
#   tools-line           the single `TOOLS='…'` allowlist line (devflow.yml's
#                        hoisted Resolve-allowed-tools step, devflow-runner.yml's
#                        review case arm, and — since issue #1170 — devflow-implement.yml's
#                        own hoisted Resolve-allowed-tools step)
#
# A ROOTS profile with no entry here resolves to an UNLOCATABLE region, which
# takes the "grant source unavailable" arm. That is the load-bearing direction: a
# future fourth cloud profile added without declaring its region must not
# silently inherit the retired whole-file read, which is precisely the fail-open
# scope limit (ii) this mapping retires.
GRANT_REGION_EXTRACTORS = {
    "implement": _heads.tools_allowlist_line,
    "light-command": _heads.tools_allowlist_line,
    "review": _heads.tools_allowlist_line,
}


def _scope_grant_region(profile, text):
    """``(region_text_or_None, why_or_None)`` for ``profile`` inside a workflow's ``text``.

    ``region_text`` is ``None`` when the region cannot be located — an undeclared
    profile, or an extractor that refuses the file — and ``why`` then carries the
    reason. Each scoper signals a refusal by raising ``SystemExit`` carrying a
    specific message naming what refused and why (an absent allowlist line, more
    than one, a value that does not begin with a quote, an unterminated one, …);
    those are materially different things to go fix, so the exception text is
    threaded out rather than collapsed, and the caller renders it. Converting the
    refusal to a return value (instead of letting ``SystemExit`` propagate) is what
    keeps it a reported violation rather than an aborted run. Never falls back to
    the whole text: an unlocatable region is unknown, and unknown is not
    "everything".

    ``except SystemExit`` is deliberately broader than the scopers' own refusals —
    any ``SystemExit`` raised beneath the extractor lands here. That is a
    mis-*attribution* risk, not a swallow (the run still fails closed and the
    message names the extractor), and a messageless exit is reported as such rather
    than as a bare "refused", so it can never render a reason the code did not
    observe.
    """
    extractor = GRANT_REGION_EXTRACTORS.get(profile)
    if extractor is None:
        return (None, "no grant-region extractor declared for this profile")
    try:
        return (extractor(text), None)
    except SystemExit as exc:
        detail = str(exc).strip()
        return (None, f"{extractor.__name__} refused the workflow: "
                      + (detail if detail else "refused with no reason given"))
    # SystemExit is the scopers' DECLARED refusal channel; anything else is a
    # scoper bug (a scoper could raise IndexError/ValueError on an unusual shape).
    # Letting that escape would
    # abort check_grant_sync entirely and take the other two profiles' reporting
    # down with it — loud, but it defeats this module's per-profile
    # continue-and-report contract. Route it to the same unavailable arm, naming
    # the exception type so a scoper bug is never mistaken for a refusal.
    except Exception as exc:
        return (None, (f"{extractor.__name__} raised {type(exc).__name__} on this workflow "
                      f"(not its declared SystemExit refusal channel): {exc}"))


# A grant REGION is one `TOOLS='…'` line or one `--allowed-tools` quoted value;
# neither can contain an unindented top-level YAML key. This is the enumeration —
# a few characteristic keys, not "top-level keys" in general, so a workflow whose
# only leading keys are outside this tuple is not detected. Keyed on the keys
# rather than on size, so a long legitimate region is never flagged.
_WHOLE_WORKFLOW_KEYS = ("on:", "jobs:", "name:", "permissions:")


def _looks_like_whole_workflow(text):
    """True when injected text carries workflow structure a grant REGION never has.

    Leading whitespace is stripped before matching, so an indented copy of a
    workflow is still detected — matching at column 0 only would have made mere
    indentation a second, silent way past the check.

    Detection is still the characteristic-key heuristic above, so it is one-sided:
    a positive is reliable, a negative proves nothing (a workflow whose only
    leading keys fall outside the tuple, or which quotes them as `"on":`, is not
    detected). That asymmetry is why the caller treats a positive as a fail-closed
    refusal rather than as the whole guarantee.
    """
    return any(line.lstrip().startswith(_WHOLE_WORKFLOW_KEYS) for line in text.splitlines())


def _grant_source(profile, profile_grants):
    """``(region_text_or_None, cause)`` for one profile's grant source.

    When ``profile_grants`` is provided it is a ``{profile: text}`` mapping of
    already-scoped grant regions (the injection point unit tests use to drive
    synthetic grants) and is returned verbatim — injected text is NOT re-scoped,
    so a synthetic fixture spelling one grant per line is never refused by a
    scoper's uniqueness check. Otherwise the profile's ROOTS workflow file is read
    from disk and narrowed to its own grant-bearing region (issue #678). An
    injected source that looks like a whole workflow, a missing injected profile,
    an unreadable/undecodable workflow, or an unlocatable region yields ``None``
    so the caller can report a targeted violation rather than silently treating
    the grant set as empty (unknown is not zero).

    ``cause`` is ``None`` on success and otherwise names WHICH of the four
    distinct no-source conditions fired — an injected grant source refused as a
    whole workflow file rather than an already-scoped region, an injected profile
    that is absent or explicitly ``None``, a workflow that could not be read or
    decoded, or a region that could not be located inside a workflow that read
    fine. All four take the same "grant source unavailable" violation class
    (unknown is not zero), but they are four different things to go fix, so each
    carries its own breadcrumb rather than converging on one indistinguishable
    message.
    """
    if profile_grants is not None:
        text = profile_grants.get(profile)
        # The injected branch returns its text UNSCOPED by design (a synthetic
        # one-grant-per-line fixture would trip the scoper's uniqueness check), so
        # a caller that passed real workflow text here would get the retired
        # whole-file pooling back — the very fail-open scope limit (ii) this module
        # closed. REFUSE it rather than merely breadcrumbing: a breadcrumb beside a
        # green result is the silent-failure shape (the guard would report "no
        # violations" about a grant set derived by the method it just declared
        # unsafe), so this takes the same fail-closed grant-source-unavailable arm
        # as every other unusable source. The parameter is a test-injection seam for
        # already-scoped regions, not a general grant-source override. Detection is
        # one-sided (see _looks_like_whole_workflow), so this narrows the fail-open
        # rather than eliminating it — an undetected whole workflow still pools.
        if text is not None and _looks_like_whole_workflow(text):
            return (None, ("injected grant source looks like a whole workflow file, not an "
                          "already-scoped grant region; pass the region, or omit "
                          "profile_grants to read from disk"))
        return (text, None if text is not None else "no injected grant source for this profile")
    workflow = ROOTS[profile]["workflow"]
    try:
        raw = (REPO_ROOT / workflow).read_text(encoding="utf-8")
    # UnicodeDecodeError is a ValueError subclass, NOT an OSError: a workflow carrying a
    # non-UTF-8 byte would otherwise escape this handler as a raw traceback and
    # abort the whole guard, defeating the very unknown-is-not-zero contract this
    # function documents. Catch both so an undecodable source is reported as
    # unavailable exactly like an unreadable one. Named precisely rather than as
    # the broader ValueError so an unrelated future ValueError in this try body
    # surfaces as a traceback instead of being masked as "source unavailable".
    except (OSError, UnicodeDecodeError):
        return (None, "workflow file unreadable or not valid UTF-8")
    region, why = _scope_grant_region(profile, raw)
    if region is None:
        return (None, f"grant-bearing region could not be located in the workflow ({why})")
    return (region, None)


def _strip_yaml_comment(line):
    """Return ``line`` with any YAML comment removed, quote-aware.

    A `#` starts a YAML comment only at the start of the line or after
    whitespace, and only outside a quoted scalar — so `Bash(x:*)'  # note` is
    stripped while a `#` inside `'...'` (or in a path) is preserved.

    **Deliberately stricter than the runtime validator's extract_profile_grants**
    (which drops full-line comments only, and documents that residual fail-open).
    An inline `# was Bash(.../workpad.py:*)` would otherwise be counted as a live
    grant, letting arm (1) pass for a helper the profile does not actually grant
    — the silent-matcher-denial class (#363/#401).

    **Unbalanced-quote fail-closed arm.** Quote state is per-line, so a line
    carrying an unpaired `'` or `"` before the `#` (an apostrophe in an unquoted
    YAML scalar — `run: echo don't  # Bash(scripts/x.sh:*)`) would leave the
    scanner "inside" a string for the rest of the line and strip nothing. That
    direction counts MORE than the validator, not fewer: the commented text is
    scanned as live, manufacturing a phantom grant (or a phantom widening). So a
    line whose quote is still open at end-of-line is re-scanned quote-blind,
    stripping at the first whitespace-preceded `#`. With that arm in place the
    divergence from the validator is one-way — this function only ever counts
    FEWER things as grants — because every line the validator drops whole is
    also reduced to a grant-free prefix here.
    """
    def _scan(text, quote_aware):
        quote = None
        for i, ch in enumerate(text):
            if quote_aware and quote is not None:
                if ch == quote:
                    quote = None
            elif quote_aware and ch in ("'", '"'):
                quote = ch
            elif ch == "#" and (i == 0 or text[i - 1].isspace()):
                return text[:i], quote
        return text, quote

    stripped, open_quote = _scan(line, quote_aware=True)
    if open_quote is not None:
        # Unterminated quote: the quote state is not trustworthy, so do not let it
        # protect a `#`. Re-scan treating quotes as ordinary characters.
        stripped, _ = _scan(line, quote_aware=False)
    return stripped


def _scan_grants(text):
    """Return ``(vendored_grants, any_grants)`` for a grant-source text.

    YAML comments — full-line *and* inline — are stripped first (see
    ``_strip_yaml_comment``) so a commented-out grant is counted neither as a
    grant nor as a widening. ``vendored_grants`` is the set of properly-scoped
    vendored leading tokens; ``any_grants`` is the set of every ``Bash(...)``
    command-position path token (used for widening detection).
    """
    scanned = "\n".join(_strip_yaml_comment(line) for line in text.splitlines())
    return set(_VENDORED_GRANT_RE.findall(scanned)), set(_ANY_BASH_GRANT_RE.findall(scanned))


def _classify_widening(spec):
    """Label a grant ``spec`` that covers a reachable helper by its widened class.

    Returns ``absolute`` / ``basename-wildcard`` / ``repo-root`` / ``wildcard``
    / ``bare-name`` / ``unclassified``. It **never returns None**: labelling
    only, never the decision of whether a spec is a violation — that decision is
    ``_grant_covers``. An earlier shape returned ``None`` for any spec outside
    three enumerated prefixes and the caller dropped the finding, so genuinely
    widening shapes (``./scripts/x``, ``../scripts/x``, ``~/scripts/x``,
    ``**/x``, ``*x``, a bare ``x``) were silently accepted — a guard that failed
    open exactly where it claimed to fail closed. An unrecognized shape is now
    reported as ``unclassified``, never waved through.
    """
    if spec.startswith("/"):
        return "absolute"
    if spec.startswith("*/"):
        return "basename-wildcard"
    if spec.startswith(("scripts/", "lib/")):
        return "repo-root"
    if "*" in spec or "?" in spec:
        return "wildcard"
    if "/" not in spec:
        # A bare name is resolved through PATH, so it is the BROADEST path-class
        # widening, not an unrecognized one — label it precisely rather than
        # letting the catch-all bucket describe the most dangerous shape.
        return "bare-name"
    return "unclassified"


def _grant_covers(spec, literals, basenames):
    """Return True when grant ``spec`` can execute a reachable helper.

    Two independent coverage tests, unioned, because either alone fails open:

    * **glob coverage** — ``spec`` read as a shell pattern matches a reachable
      vendored literal. This is what catches a *directory* or blanket wildcard
      (``.prflow/vendor/prflow/scripts/*``, ``*``, ``**/workpad.py``), whose
      basename is ``*`` and so never matches a reachable basename.
    * **basename coverage** — ``spec``'s final path segment names a reachable
      helper. This catches a widened *path* to the same helper
      (``scripts/workpad.py``, ``/home/x/workpad.py``, ``./scripts/workpad.py``,
      a bare ``workpad.py``), which does not glob-match the vendored literal.

    A bare granted command name that is not a reachable helper (``awk``, ``jq``,
    ``git`` — every non-vendored grant the live workflows actually carry) matches
    neither test, so the healthy tree stays clean.
    """
    if any(fnmatch.fnmatchcase(literal, spec) for literal in literals):
        return True
    return spec.rsplit("/", 1)[-1] in basenames


def check_grant_sync(profile_grants=None):
    """AC9 guard. Return a list of human-readable violations (empty == OK).

    For each of the three cloud profiles keyed by ROOTS (implement,
    light-command, review), maps every AC1-closure reachable helper literal in
    REQUIRED_HELPER_HEADS to that profile's workflow grants and fails when:

    * a reachable literal lacks an explicit vendored ``Bash(<literal>:*)`` grant, or
    * any other grant *covering* a reachable helper (see ``_grant_covers``)
      widens the executable trust boundary — an absolute-path, repo-root,
      basename-wildcard, directory/blanket glob, PATH-resolved bare name, or
      otherwise unclassified shape (excluding that profile's sanctioned
      wildcards in ``SANCTIONED_WILDCARD_GRANTS``).

    ``profile_grants`` (optional ``{profile: workflow-text}``) injects synthetic
    grant sources for unit tests; when omitted each profile's ROOTS workflow is
    read from disk.
    """
    errors = []

    # "exactly three current cloud profiles, complete by AC1's workflow roots":
    # REQUIRED_HELPER_HEADS must name precisely the ROOTS profile set. (A subset
    # or superset here is the drift this half of the guard exists to catch; the
    # profile parity in check_closure() covers the healthy tree, this restates it
    # so grant-sync is self-standing when driven in isolation.)
    if set(REQUIRED_HELPER_HEADS) != set(ROOTS):
        errors.append(
            "AC9 grant-sync: REQUIRED_HELPER_HEADS profiles "
            f"{sorted(REQUIRED_HELPER_HEADS)} != ROOTS profiles {sorted(ROOTS)}"
        )
        return errors

    for profile in sorted(ROOTS):
        heads = REQUIRED_HELPER_HEADS[profile]
        text, cause = _grant_source(profile, profile_grants)
        if text is None:
            errors.append(
                f"AC9 grant-sync: profile '{profile}' grant source unavailable "
                f"({ROOTS[profile]['workflow']}): {cause}; "
                f"cannot confirm grants (unknown is not zero)"
            )
            continue
        vendored_grants, any_grants = _scan_grants(text)

        # (1) Every reachable literal must be explicitly granted, tight-scoped.
        reachable_basenames = set()
        for literal in heads:
            reachable_basenames.add(literal.rsplit("/", 1)[-1])
            if literal not in vendored_grants:
                errors.append(
                    f"AC9 grant-sync: profile '{profile}' reaches helper "
                    f"'{literal}' but grants no explicit Bash({literal}:*) — "
                    f"add the vendored-literal grant"
                )

        # (2) No grant COVERING a reachable helper may widen the boundary.
        # Fail-closed polarity: any non-vendored, non-sanctioned grant that can
        # execute a reachable helper is a violation, and _classify_widening only
        # LABELS it. Never drop a covering spec because its shape is unfamiliar.
        for spec in sorted(any_grants):
            if spec in vendored_grants:
                continue  # a proper vendored grant is never a widening
            if spec in SANCTIONED_WILDCARD_GRANTS.get(profile, frozenset()):
                continue  # deliberate companion wildcard for THIS profile (documented)
            if not _grant_covers(spec, heads, reachable_basenames):
                continue  # cannot execute any helper this profile reaches
            errors.append(
                f"AC9 grant-sync: profile '{profile}' grants '{spec}' covering "
                f"reachable helper(s) as a {_classify_widening(spec)} class — widens "
                f"the executable trust boundary; grant only the vendored literal"
            )

    return errors


# --- AC4 (issue #678): profile-specific command shapes over the AC1 closure ----
# extract-command-shapes.py owns three empirically-probed rule tables — the
# read-only review tier (R1-R4), the read-write implement tier (IR1-IR5), and the
# command tier (CR1-CR5, issue #1152, inheriting the implement shapes). What was
# missing is the join to THIS module's reachability closure: the existing
# desk-time scans cover named file globs, so a fenced command in an asset reached
# by a root whose glob does not name it was audited by neither.
#
# The mapping below is per profile and EXPLICIT, because AC4 forbids inferring a
# permitted form from evidence recorded on ANOTHER profile. Each profile maps to
# its OWN probe-anchored table: matcher-probe.yml records a REVIEW, an IMPLEMENT,
# and (issue #1152) a COMMAND baseline, so `light-command` maps to the command
# table rather than borrowing the review or implement one — a None entry would
# still be legal (it means "no probe-anchored table for that profile"), but no
# ROOTS profile is None today. A ROOTS profile with NO entry at all is a reported
# violation rather than a silent skip, so a future profile fails closed.
#
# `rules` is read from extract-command-shapes.py rather than mirrored, so a rule
# added there cannot leave a stale copy here.
# `finder` binds the function OBJECT, matching its sibling `rules` key: a renamed
# finder then fails at import here rather than at call time through a getattr on
# a stale name string.
PROFILE_SHAPE_TABLES = {
    "implement": {"rules": _shapes.IMPLEMENT_RULES, "finder": _shapes.find_implement_violations},
    # issue #1152: the light-command (devflow.yml) tier now HAS a probe-anchored
    # rule table. It was `None` on the stated ground that matcher-probe.yml recorded
    # a REVIEW baseline and an IMPLEMENT baseline and no command one — so there was no
    # probe-anchored table to apply and borrowing the review table would be the
    # cross-profile inference AC4 rejects. This issue adds the `command-probe` job and
    # its generated baseline, so the tier is now measured; its rule set (`CR*`) is the
    # implement tier's denied shapes remapped (see extract-command-shapes.py).
    "light-command": {"rules": _shapes.COMMAND_RULES, "finder": _shapes.find_command_violations},
    "review": {"rules": _shapes.REVIEW_RULES, "finder": _shapes.find_violations},
}


def shape_audited_assets():
    """``{asset_path: {profile, …}}`` for every AC1-reached asset.

    An asset maps to every ROOTS profile whose OWN closure reaches the skill that
    owns it — a shared asset (the review engine, reached inline from implement and
    directly from the review root) is therefore audited under each governing
    profile's table, which is the point: a shape permitted on one tier is unproven
    on the other.
    """
    audited = {}
    for profile in ROOTS:
        for skill in reachable_skills(profile):
            for asset in SKILL_ASSETS.get(skill, ()):
                audited.setdefault(asset, set()).add(profile)
    return audited


def shape_violations_in(profile, text):
    """Denied-shape hits ``(line, rule, statement)`` for one text under one profile.

    Returns an empty list for a profile whose declared table is ``None`` (no
    probe-anchored rules to apply). A profile with no declared entry at all
    raises ``KeyError``; ``check_shape_conformance`` filters those out before
    calling, so only a direct (test) caller can reach that path.
    """
    table = PROFILE_SHAPE_TABLES[profile]
    if table is None:
        return []
    return table["finder"](text)


def shape_unaudited_assets():
    """Reached assets governed by NO profile carrying a probe-anchored rule table.

    An asset every reaching profile declares ``None`` for is audited by nothing —
    a real coverage hole this module must *report*, not leave to be inferred from a
    silent pass. Empty on the current closure because no ROOTS profile is ``None``
    today (issue #1152 gave ``light-command`` its own table); it stays empty even
    were one reintroduced, because every light-command-reached skill is also reached
    under ``implement`` — but a future skill reachable ONLY from a listener whose
    profile declared ``None`` would escape the AC4 audit with the guard still green,
    which is what this function exists to catch.
    """
    tabled = {p for p, table in PROFILE_SHAPE_TABLES.items() if table is not None}
    return sorted(
        asset for asset, profiles in shape_audited_assets().items()
        if not (profiles & tabled)
    )


def check_shape_conformance():
    """AC4 guard. Return a list of human-readable violations (empty == OK)."""
    errors = []
    declared = set(PROFILE_SHAPE_TABLES)
    for asset in shape_unaudited_assets():
        errors.append(
            f"AC4 shapes: reached asset '{asset}' is governed by no profile carrying a "
            f"probe-anchored rule table, so no shape rule audits it — establish a table "
            f"for a reaching profile (probe it first), or record why this asset is exempt"
        )
    for profile in sorted(set(ROOTS) - declared):
        errors.append(
            f"AC4 shapes: profile '{profile}' has no shape rule table declared in "
            f"PROFILE_SHAPE_TABLES — declare its probe-anchored table, or None with "
            f"the reason; an undeclared profile is never silently unaudited"
        )
    for asset, profiles in sorted(shape_audited_assets().items()):
        path = REPO_ROOT / asset
        try:
            text = path.read_text(encoding="utf-8")
        # An asset that cannot be read is unknown, not clean. check_closure()
        # already reports a MISSING asset, so this arm is about an unreadable or
        # undecodable one — it must not pass as zero findings here either.
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"AC4 shapes: reached asset '{asset}' could not be read: {exc}")
            continue
        for profile in sorted(profiles & declared):
            for lineno, rule, statement in shape_violations_in(profile, text):
                oneline = " ".join(statement.split())
                if len(oneline) > 120:
                    oneline = oneline[:117] + "..."
                errors.append(
                    f"AC4 shapes: {asset}:{lineno} emits a {rule}-denied shape under the "
                    f"'{profile}' profile that reaches it: {oneline}"
                )
    return errors


# --- AC2/AC3 (issue #701): helper leading-token boundary over the AC1 closure --
# AC9 (check_grant_sync) grades the GRANT side — every reachable helper literal is
# granted tight, and no grant WIDENS the boundary. Its documented scope limit (i)
# is the launcher/interpreter blind spot: a granted `python3`/`env`/`xargs` head
# executes any helper as an argument, escaping the per-helper vendored grant, and
# a leading-token-only grant read cannot see it. This guard closes that surface on
# the CALL-SITE side: for every cloud-reached fenced command that names a bundled
# helper, the helper's vendored path must be the FIRST executable token.
#
# The #701 policy decision (recorded in docs/internal/cloud-writer-boundary.md): the source
# keeps the portable `${CLAUDE_SKILL_DIR:-…}` anchor (#275), and this guard
# measures the EMISSION-TIME normalized token — extract-command-heads.py's
# `_normalize` reduces the well-formed anchor to the vendored literal, so the
# sanctioned source form passes as its own cloud form with no duplicate fence
# (avoiding a duplicate emitted fence). AC2 ("emitted with a literal vendored
# leading token") and AC3 ("a raw-token guard rejecting unexpanded anchors,
# absolute/repo-root paths, and launcher-prefixed helpers") are both discharged
# against that emission surface.
#
# The launcher table is GENERATED from the profile's parsed grants (∩
# LAUNCHER_HEADS), so it tracks the grants rather than a hand-kept list, and it is
# read BEFORE the wrapper normalization extract-command-heads.py applies — a
# granted wrapper head (which that parser would otherwise strip) still counts.
# env + interpreters: heads that run a following PATH argument as the command.
# This is genuinely new policy this module owns (a grant string cannot reveal
# "executes its path argument", so it is not derivable from the grants).
_INTERPRETER_LAUNCHERS = frozenset(
    {"env", "python", "python3", "bash", "sh", "ruby", "perl", "node"}
)
# The process-wrapper half is NOT re-enumerated: it IS extract-command-heads.py's
# WRAPPERS set (the heads that parser strips), reused directly so a wrapper added
# there (e.g. `flock`, `setsid`) is automatically covered here — otherwise a
# `<new-wrapper> <helper>` escape would pass unseen, a fail-open exactly where the
# boundary claims to fail closed. Union at import; the WRAPPERS↔LAUNCHER_HEADS
# containment is pinned in lib/test/test_python_scripts.py so the reuse cannot
# silently regress to a hand-copy.
LAUNCHER_HEADS = _INTERPRETER_LAUNCHERS | _heads.WRAPPERS


def helper_basenames_for(profile):
    """The bundled-helper basenames that carry a per-helper vendored grant in ``profile``."""
    return frozenset(token.rsplit("/", 1)[-1] for token in REQUIRED_HELPER_HEADS[profile])


def profile_launchers(profile, region_text):
    """The profile's granted launcher heads — its parsed grants ∩ ``LAUNCHER_HEADS``.

    ``region_text`` is the profile's already-scoped grant region (from
    ``_grant_source``). ``_scan_grants`` returns every ``Bash(<spec>)``
    command-position token, so a `Bash(python3 -m:*)` grant enumerates as
    `python3` — the launcher head — before any wrapper normalization.
    """
    _vendored, any_grants = _scan_grants(region_text)
    return frozenset(g for g in any_grants if g in LAUNCHER_HEADS)


def check_helper_boundary(profile_grants=None):
    """AC2/AC3 guard. Return a list of human-readable violations (empty == OK).

    For every AC1-reached asset, under each ROOTS profile whose closure reaches
    it, require every fenced command that names one of that profile's
    per-helper-granted bundled helpers to place the helper's vendored path as its
    leading token. The per-profile launcher table is derived from the profile's
    parsed grants; ``profile_grants`` injects already-scoped grant regions for
    tests exactly as ``check_grant_sync`` does (a whole-workflow injection is
    refused fail-closed by ``_grant_source``).
    """
    errors = []
    # Derive each profile's launcher table once, fail-closed on an unavailable
    # grant source (unknown is not zero — an unreadable region must not silently
    # yield an empty launcher set that waves a launcher-prefixed helper through).
    launchers_by_profile = {}
    basenames_by_profile = {}
    for profile in ROOTS:
        region_text, cause = _grant_source(profile, profile_grants)
        if region_text is None:
            errors.append(
                f"AC3 boundary: profile '{profile}' grant source unavailable "
                f"({cause}); cannot derive the launcher table, so the leading-token "
                f"boundary cannot be enforced for its reached assets"
            )
            continue
        launchers_by_profile[profile] = profile_launchers(profile, region_text)
        basenames_by_profile[profile] = helper_basenames_for(profile)
    for asset, profiles in sorted(shape_audited_assets().items()):
        path = REPO_ROOT / asset
        try:
            text = path.read_text(encoding="utf-8")
        # An unreadable/undecodable reached asset is unknown, not clean (mirrors
        # check_shape_conformance). check_closure() reports a MISSING asset.
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"AC3 boundary: reached asset '{asset}' could not be read: {exc}")
            continue
        for profile in sorted(profiles):
            if profile not in launchers_by_profile:
                continue  # its grant-source error is already reported above
            basenames = basenames_by_profile[profile]
            launchers = launchers_by_profile[profile]
            for lineno, reason, statement in _heads.helper_boundary_violations(
                text, basenames, launchers
            ):
                oneline = " ".join(statement.split())
                if len(oneline) > 120:
                    oneline = oneline[:117] + "..."
                errors.append(
                    f"AC3 boundary: {asset}:{lineno} invokes a bundled helper via a "
                    f"'{reason}' form under the '{profile}' profile that reaches it — the "
                    f"vendored path must be the leading token: {oneline}"
                )
    return errors


def _helper_source_path(vendored_token):
    """Map a vendored leading token to its repository-owned source path.

    `.prflow/vendor/prflow/scripts/workpad.py` -> `scripts/workpad.py`.
    """
    if not vendored_token.startswith(VENDOR_PREFIX):
        raise ValueError(f"helper token not under vendor prefix: {vendored_token}")
    return vendored_token[len(VENDOR_PREFIX):]


def manifest_file_paths():
    """Sorted, de-duplicated repo-relative paths the manifest pins.

    Every AC1-reached skill asset plus every required helper's source file.
    """
    paths = set()
    for assets in SKILL_ASSETS.values():
        paths.update(assets)
    for heads in REQUIRED_HELPER_HEADS.values():
        for token in heads:
            paths.add(_helper_source_path(token))
    # issue #1087: import-closure sources hashed but not granted.
    paths.update(PROTECTED_IMPORT_SOURCES)
    return sorted(paths)


def sha256_of(rel_path):
    """Lowercase hex SHA-256 of a repo-relative file."""
    h = hashlib.sha256()
    with open(REPO_ROOT / rel_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest():
    """Render the AC18 devflow-cloud-writer-contract-v1 manifest dict."""
    return {
        "protocol": PROTOCOL,
        "legacy_profile_baseline": LEGACY_PROFILE_BASELINE,
        "files": {rel: sha256_of(rel) for rel in manifest_file_paths()},
        "required_helper_heads": {
            profile: list(heads) for profile, heads in REQUIRED_HELPER_HEADS.items()
        },
    }


def canonical_json(obj):
    """Canonical JSON: sorted keys, 2-space indent, UTF-8, one trailing newline."""
    return json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


MANIFEST_PATH = "scripts/devflow-cloud-writer-contract.json"


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("check", "generate", "verify", "grant-sync", "shape-conformance",
                 "helper-boundary"),
        help="check: AC1 closure guard; generate: write the manifest; "
        "verify: assert the checked-in manifest matches the closure; "
        "grant-sync: AC9 guard — every reachable helper literal is granted "
        "tight-scoped in its profile and no grant widens the trust boundary; "
        "shape-conformance: AC4 guard — no AC1-reached fenced command emits a "
        "denied shape under a profile that reaches it; "
        "helper-boundary: AC2/AC3 guard — every AC1-reached fenced bundled-helper "
        "command places the vendored helper path as its leading token",
    )
    args = parser.parse_args(argv)

    # grant-sync is a standalone guard over the workflow grants — it does not
    # render the manifest, so it runs before the check_closure()/build path below.
    #
    # This subcommand is an OPERATOR-FACING entry point, not the CI wiring: the
    # guard reaches the required `lib + python tests` job because
    # lib/test/test_python_scripts.py calls check_grant_sync() and
    # main(["grant-sync"]) directly. Do not read the absence of a run.sh
    # invocation as the guard being ungated, and do not add one believing it
    # closes a coverage hole — it would be duplicate coverage.
    if args.command == "grant-sync":
        gs_errors = check_grant_sync()
        if gs_errors:
            for e in gs_errors:
                print(f"cloud-writer-contract: {e}")
            return 1
        print("cloud-writer-contract: grant-sync OK")
        return 0

    # shape-conformance is likewise a standalone guard over the reached fences —
    # it renders no manifest. Same operator-facing status as grant-sync: the CI
    # wiring is lib/test/test_python_scripts.py calling check_shape_conformance()
    # directly, so the absence of a run.sh invocation is not an ungated guard.
    if args.command == "shape-conformance":
        sc_errors = check_shape_conformance()
        if sc_errors:
            for e in sc_errors:
                print(f"cloud-writer-contract: {e}")
            return 1
        print("cloud-writer-contract: shape-conformance OK")
        return 0

    # helper-boundary is likewise a standalone guard over the reached fences (AC2/
    # AC3, issue #701) — it renders no manifest. Same operator-facing status as
    # grant-sync/shape-conformance: the CI wiring is lib/test/test_python_scripts.py
    # calling check_helper_boundary() directly, so the absence of a run.sh
    # invocation is not an ungated guard.
    if args.command == "helper-boundary":
        hb_errors = check_helper_boundary()
        if hb_errors:
            for e in hb_errors:
                print(f"cloud-writer-contract: {e}")
            return 1
        print("cloud-writer-contract: helper-boundary OK")
        return 0

    # generate and verify both render the manifest from the closure, so a closure
    # that `check` would reject (a helper token missing the vendor prefix, a
    # classified asset absent on disk) must fail here with the same clean report
    # rather than crashing later in manifest_file_paths()/sha256_of() with an
    # uncaught ValueError/FileNotFoundError.
    errors = check_closure()
    if errors:
        for e in errors:
            print(f"cloud-writer-contract: {e}")
        return 1

    if args.command == "check":
        print("cloud-writer-contract: closure OK")
        return 0

    manifest = build_manifest()
    rendered = canonical_json(manifest)
    target = REPO_ROOT / MANIFEST_PATH

    if args.command == "generate":
        target.write_text(rendered, encoding="utf-8")
        print(f"cloud-writer-contract: wrote {MANIFEST_PATH}")
        return 0

    # verify
    if not target.is_file():
        print(f"cloud-writer-contract: manifest missing at {MANIFEST_PATH}")
        return 1
    current = target.read_text(encoding="utf-8")
    if current != rendered:
        print(
            "cloud-writer-contract: checked-in manifest is stale — "
            # Repo-root-relative, never the bare basename (issue #1244): the remedy is
            # copy-pasted at the repo root, where `python3 cloud_writer_contract.py` does
            # not resolve. `Path(__file__)` is lib/test/cloud_writer_contract.py and
            # REPO_ROOT is its parents[2], so this renders `lib/test/cloud_writer_contract.py`.
            f"regenerate with `python3 {Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()} generate`"
        )
        return 1
    print("cloud-writer-contract: manifest matches closure")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
