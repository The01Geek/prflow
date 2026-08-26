#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Fail the suite when a prompt surface names a subagent under a namespace that does
not dispatch.

Why this exists. A qualified subagent id in prompt prose (`**prflow:code-reviewer**
-- prompt:`, `subagent_type: prflow:silent-failure-hunter`) is a DISPATCH STRING: the
runtime resolves it to an `agents/<leaf>.md` definition, and the namespace half is
the PLUGIN NAME. That makes it categorically different from the `agent_overrides`
config keys, which are a closed allowlist that deliberately accepts every declared
namespace so a consumer's pre-rename config keeps resolving. Dispatch has no such
allowlist: the plugin loads under its canonical name only, so a stale namespace
resolves to nothing.

The failure mode is silent and specific, which is why a build gate is worth its
keep. A review pass whose reviewer subagents cannot be dispatched does not fail
loudly -- it yields a verdict with `coverage: "not_verified"`, a non-clean result
with no diagnosis pointing at the namespace. Renaming the plugin without sweeping
these strings therefore ships a review engine that silently reviews nothing, and no
other check in this suite reads the dispatch namespace.

Scope, and what is deliberately NOT flagged:

* Only ids whose LEAF is in the dispatchable set are considered -- see
  `agent_leaves` for the exact union and why it is a union. A `<ns>:<skill>`
  occurrence naming a plain skill directory (`prflow:review`, `prflow:implement`) is
  a COMMAND/skill reference, not a subagent dispatch; those are governed by
  lint-subagent-extension-handoff.py and are out of scope here.
* The accepted namespace is the CANONICAL one, derived from the same identity source
  every other reader uses. Alias namespaces are accepted for config keys and for
  comment triggers; they are not accepted here, because that is precisely the
  distinction this guard exists to hold.
* `agents/` definitions themselves, and the `.prflow/` machine corpora (frozen
  census snapshots, append-only learnings) are excluded: the corpora quote historical
  ids on purpose and re-keying them would rewrite recorded history.

Population is an index-reading `git ls-files` with no `--others`, so a sibling git
worktree under `.claude/worktrees/` cannot change the result (issue #711).
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sys
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
#: The plugin root this guard ships inside (lib/test/ -> lib/ -> root).
_PLUGIN_ROOT = Path(os.path.dirname(os.path.dirname(_HERE)))


def _load(name: str, path: str):
    """Import a sibling/parent helper by path, failing at LOAD time and naming it."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(
            f"lint-subagent-dispatch-namespace: {path} is not an importable source "
            "file; refusing to audit"
        )
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise SystemExit(
            f"lint-subagent-dispatch-namespace: {path} could not be loaded "
            f"({exc.__class__.__name__}: {exc}); refusing to audit"
        ) from exc
    return module


_pop = _load("lint_population", os.path.join(_HERE, "lint_population.py"))
_identity = _load(
    "plugin_identity", os.path.join(os.path.dirname(_HERE), "plugin_identity.py")
)

#: Any `<namespace>:<leaf>` occurrence. The namespace set is NOT constrained here on
#: purpose: the guard must SEE a stale namespace in order to report it, so matching is
#: deliberately wider than the accepted set and the verdict is taken below.
_QUALIFIED = re.compile(r"\b([a-z0-9][a-z0-9-]*):([a-z0-9][a-z0-9-]*)\b")

#: Prompt surfaces this guard audits. The shape is bound for the dispatch-namespace
#: question alone; two sibling lints bind it for their own questions and the three
#: share no notion of what a prompt extension is. That adjudication — and why the
#: three are not in conflict — is recorded once, in `lint-issue-body-refetch.py`'s
#: module docstring (issue #1076).
_SKILLS_PREFIX = "skills/"
_EXTENSION_RE = re.compile(r"\.prflow/prompt-extensions/[^/]+\.md")


def is_audited(path: str) -> bool:
    """True when `path` is a tracked prompt surface in the scan population."""
    normalized = path.replace("\\", "/")
    if normalized.startswith(_SKILLS_PREFIX) and normalized.endswith(".md"):
        return True
    return bool(_EXTENSION_RE.fullmatch(normalized))


def agent_leaves(plugin_root: Path) -> frozenset[str]:
    """The set of leaves whose qualified id must carry the canonical namespace.

    This is the UNION of two populations, because two different mechanisms resolve a
    qualified id and both break on a stale namespace:

    * every tracked `agents/<leaf>.md` -- resolved by the Agent tool's
      `subagent_type`; and
    * the review-engine roster leaves published by resolve-review-overrides.py --
      resolved as `agent_overrides` keys and as the telemetry join keys the shadow
      pass compares 1:1.

    The union matters: `requesting-code-review` is a review-engine roster leaf with no
    `agents/` definition (it is a vendored SKILL dispatched through a
    `general-purpose` Task), so an agents-only population would silently leave it
    unswept -- which is exactly what a first pass of this sweep did.

    Sourced from the index, so an agent added but not committed is not treated as
    dispatchable. An empty result is fatal: with no leaves nothing could match and the
    audit would pass vacuously over every prompt surface.
    """
    # Composes the shared INDEX constant — which states the #711 index-read choice and
    # carries `-c core.quotePath=false` (issue #1217), without which a tracked non-ASCII
    # `agents/` path arrives C-quoted, loses its `agents/` prefix, and drops out of the
    # leaf set silently — and appends only the pathspec this call site needs.
    paths = _pop.enumerate_population(
        plugin_root, None, ls_files_argv=(*_pop.LS_FILES_INDEX, "--", "agents/*.md")
    )
    leaves = {
        Path(p).stem for p in paths if p.replace("\\", "/").startswith("agents/")
    }

    overrides = _load(
        "resolve_review_overrides",
        str(plugin_root / "scripts" / "resolve-review-overrides.py"),
    )
    roster = tuple(getattr(overrides, "AGENT_LEAVES", ()))
    if not roster:
        raise _pop.EnumerationError(
            "resolve-review-overrides.py published no AGENT_LEAVES, so the review "
            "roster half of the dispatch population could not be established; "
            "refusing to audit on a partial population"
        )
    leaves.update(roster)

    if not leaves:
        raise _pop.EnumerationError(
            "no tracked agents/<leaf>.md definitions were found, so no dispatch id "
            "could ever be recognized and the audit would pass vacuously"
        )
    return frozenset(leaves)


def canonical_namespace() -> str:
    """The one namespace a dispatch string may carry, derived from plugin identity."""
    namespaces = list(_identity.agent_namespaces())
    if not namespaces or not namespaces[0].endswith(":"):
        raise SystemExit(
            "lint-subagent-dispatch-namespace: the declared plugin-namespace set did "
            f"not resolve to a canonical `<name>:` namespace (got {namespaces!r}); "
            "refusing to audit"
        )
    return namespaces[0]


def audit(root: Path, files_from: Path | None) -> tuple[list[str], int]:
    """Return `(errors, audited_file_count)`."""
    canonical = canonical_namespace()
    canonical_name = canonical.rstrip(":")
    # The dispatchable-leaf set and the canonical namespace are both properties of
    # the PLUGIN this guard ships inside, not of the audited tree, so both resolve
    # against the plugin root. `--root` governs only which surfaces are audited,
    # which is what lets a fixture supply surfaces without standing up a whole
    # plugin (and keeps the leaf enumeration on the real index, per issue #711).
    leaves = agent_leaves(_PLUGIN_ROOT)

    # The shared INDEX constant again: same #711 index read, same issue-#1217 quoting
    # fix, so a tracked non-ASCII prompt surface is audited rather than dropped.
    population = _pop.enumerate_population(
        root, files_from, ls_files_argv=_pop.LS_FILES_INDEX
    )
    errors: list[str] = []
    audited = 0
    for rel in population:
        if not is_audited(rel):
            continue
        text, skip_reason = _pop.read_source(root / rel, skip_nul=True)
        if text is None:
            # An unreadable prompt surface is NOT a pass: it is a file this guard was
            # supposed to check and could not.
            errors.append(f"{rel}: could not be read for audit ({skip_reason})")
            continue
        audited += 1
        for lineno, line in enumerate(text.split("\n"), start=1):
            for namespace, leaf in _QUALIFIED.findall(line):
                if leaf not in leaves or namespace == canonical_name:
                    continue
                errors.append(
                    f"{rel}:{lineno}: subagent dispatch id "
                    f"'{namespace}:{leaf}' names the non-dispatching namespace "
                    f"'{namespace}:' -- the plugin loads under '{canonical}' only, so "
                    f"this resolves to no agent. Use '{canonical}{leaf}'."
                )
    return errors, audited


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail when a prompt surface names a subagent under a namespace that does "
            "not dispatch."
        )
    )
    _pop.add_population_arguments(parser)
    args = parser.parse_args(argv)

    root = _pop.resolve_root(args.root, tool="lint-subagent-dispatch-namespace")
    files_from = Path(args.files_from) if args.files_from else None

    try:
        errors, audited = audit(root, files_from)
    except _pop.EnumerationError as exc:
        print(f"lint-subagent-dispatch-namespace: {exc}", file=sys.stderr)
        return 1

    for error in errors:
        print(error, file=sys.stderr)
    plural = "surface" if audited == 1 else "surfaces"
    print(f"lint-subagent-dispatch-namespace: audited {audited} prompt {plural}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
