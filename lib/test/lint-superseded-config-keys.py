#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Fail RED on a newly introduced superseded config-key leaf (issue #1084).

Issue #1002 Tier 1 renamed the consumer-facing config families ``devflow`` /
``devflow_implement`` / ``devflow_runner`` / ``devflow_review`` / ``devflow_review_and_fix``
/ ``devflow_retrospective`` / ``devflow_version`` -> their ``prflow*`` spellings, and
``lib/rename-map.json``'s ``frozen.config_keys`` is now empty, so *every* ``<family>.<key>``
config-leaf reference under a superseded family is superseded. #1068 and #1084 swept the tree
twice; this guard is the recurrence backstop those sweeps' acceptance criteria demanded, so a
third accidental introduction turns the suite RED at the desk instead of shipping a message
whose live reader reads the ``prflow`` family while the message names the dead spelling.

Vocabulary is DERIVED from ``lib/rename-map.json``'s ``config_keys`` (the single source of
truth for the rename) rather than hand-transcribed, mirroring the issue's own re-derivation
regex ``devflow(_family)?\\.<leaf>`` — so a later family rename recorded in the map is covered
automatically. Three things are intentionally NOT policed here:

* The ``devflow`` FILENAME / ``DEVFLOW_*`` env / ``/devflow:`` alias / ``devflow:<agent>``
  namespace / frozen ``devflow_module_pin_*`` / internal ``devflow_*`` shell-function forms —
  all frozen. The DOT-plus-lowercase-leaf pattern cannot match any of them (none carries a
  superseded family immediately followed by ``.`` and a config-key leaf), and a small
  extension allow-list drops the ``devflow.yml`` filename shape.
* The ``workflows["devflow-review"]`` sub-key, DELIBERATELY dual-named across the tree
  (``install.sh``'s both-spelling pattern, mirrored into the schema by #1084) so an unmigrated
  consumer still recognises their own key — policing it would flag the correct end state.
* The declared-exemption sites below, which must keep the superseded spelling. These come in
  two granularities. **Whole-file** exemptions (``_EXEMPT_EXACT`` / ``_EXEMPT_PREFIXES``) cover
  sites not worth line-by-line scanning — frozen records, fixtures, the rename map, changelog /
  changeset / doc prose, and a few executable files whose superseded references are pervasive
  rather than one-per-line — where scanning would only re-flag content that legitimately keeps
  the old spelling. **Line-scoped** exemptions cover files that are mostly scannable but carry a
  few legitimate both-spelling lines (the migration helpers): a trailing
  ``# superseded-key-ok: <non-empty reason>`` declaration marker (issue #1096, mirroring the
  repo's ``# tree-walk-ok:`` / ``# raw-guard-ok:`` / ``# structural-pin-ok:`` family) exempts
  only that one line, so the rest of the file is still scanned for an **undeclared** regression —
  the highest-blast-radius place for a dead-family read, per CLAUDE.md's half-migrated-tree note.
  Like its sibling markers, ``# superseded-key-ok:`` is honored in **any** scanned file, not only
  the migration helpers, and it exempts the whole **physical line** (a second, undeclared leaf
  piled onto an already-marked line is an accepted, greppable blind spot — the same whole-line
  granularity the sibling markers carry).

Population is sourced from ``lib/test/lint_population.py``'s ``enumerate_population`` with the
index-reading ``git ls-files`` argv (no ``--others``, no recursive tree walk) per issue #711,
so a sibling worktree under ``.claude/worktrees/`` cannot inflate the count and desk vs. CI
stay byte-identical.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RENAME_MAP = _REPO_ROOT / "lib" / "rename-map.json"

# Reuse the shared git-ls-files population + reader the sibling #711 lints use (issue #724),
# loaded by path exactly as lint-gh-api-repo-path.py does.
_POP_PATH = _REPO_ROOT / "lib" / "test" / "lint_population.py"
_pop_spec = importlib.util.spec_from_file_location("lint_population", _POP_PATH)
_pop = importlib.util.module_from_spec(_pop_spec)
_pop_spec.loader.exec_module(_pop)
for _name in ("enumerate_population", "read_source", "LS_FILES_INDEX", "EnumerationError"):
    if not hasattr(_pop, _name):
        raise SystemExit(f"lint_population.py is missing the expected `{_name}` interface")

# Reuse lint-tree-enumeration.py's quote/escape-aware `_comment_split` so the line-scoped
# `# superseded-key-ok:` marker is matched against a line's COMMENT tail alone, never the raw
# line (the same reuse the sibling lint-argjson-transport.py makes). A raw-line search would let
# the literal text `# superseded-key-ok:` sitting inside a string/regex literal exempt a real
# superseded leaf on that same code line — failing open exactly where the guard claims to fail
# closed, and the scanned migration files are precisely where such string/regex literals live.
# The protection is exact for a line whose quotes BALANCE — the case every literal in this
# population takes. `_comment_split` documents its own residual: a line it leaves with an open
# quote (the `\`-continued statement whose opening quote is on an earlier line) is re-scanned with
# quotes inert, and an in-literal marker on such a line can still exempt it. That residual is
# inherited from the audited sibling rather than introduced here, and it fails toward
# under-flagging one already-anomalous line, not toward corrupting a scanned result.
# Loaded by path at LOAD time so a rename in the sibling lint fails here naming the dependency.
_TREE_PATH = _REPO_ROOT / "lib" / "test" / "lint-tree-enumeration.py"
_tree_spec = importlib.util.spec_from_file_location("lint_tree_enumeration", _TREE_PATH)
_tree = importlib.util.module_from_spec(_tree_spec)
_tree_spec.loader.exec_module(_tree)
if not hasattr(_tree, "_comment_split"):
    raise SystemExit(f"lint-superseded-config-keys: {_TREE_PATH} no longer provides `_comment_split`")


def _superseded_families() -> list[str]:
    """The superseded config-family prefixes, derived from rename-map.json's config_keys keys."""
    families = list(json.loads(_RENAME_MAP.read_text(encoding="utf-8"))["config_keys"].keys())
    # Longest first so the regex alternation prefers `devflow_review_and_fix` over `devflow`.
    return sorted(families, key=len, reverse=True)


# A superseded config leaf: a superseded family + `.` + a lowercase config-key identifier,
# preceded by a non-identifier char so `.devflow_review.x` (a jq path) matches while
# `some_devflow.x` does not.
_LEAF_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:" + "|".join(re.escape(f) for f in _superseded_families()) + r")\.([a-z][a-z0-9_]*)"
)

# Leaves that are file extensions, not config keys — `devflow.yml` / `devflow.sh` / … are
# filenames (the workflow filenames are frozen), never config-leaf references. (No config key
# collides with a listed extension word today; a `devflow.tokens`-style leaf would be masked as
# a filename — an accepted, documented assumption that config keys never share an extension name.)
_EXTENSIONS = frozenset(
    ["yml", "yaml", "sh", "py", "json", "jq", "md", "tsv", "jsonl", "txt", "toml", "lock", "cfg", "ini", "example", "tokens", "gitignore", "mjs", "js", "ts", "png", "svg", "html"]
)

# Binary path suffixes excluded from the population before reading. A binary file cannot carry a
# text config-leaf reference, so scanning it would only produce a spurious `skip_nul` skip that
# the fail-closed arm below would then treat as an unaudited file. Excluding them upfront (the
# sibling #711 lints' pattern) keeps the skip arm meaningful: a remaining skip is a genuine
# permission/race failure, never an expected image/fixture.
_BINARY_SUFFIXES = frozenset(
    [".png", ".jpg", ".jpeg", ".gif", ".ico", ".bin", ".woff", ".woff2", ".ttf", ".otf", ".pdf", ".zip", ".gz", ".tar", ".webp"]
)

# Line-scoped exemption marker (issue #1096): a live migration file that legitimately names a
# superseded leaf on one line carries a trailing `# superseded-key-ok: <reason>` declaration,
# mirroring the repo's `# tree-walk-ok:` / `# raw-guard-ok:` / `# structural-pin-ok:` family.
# The reason must be non-empty (at least one non-whitespace char after the colon), so a bare
# `# superseded-key-ok:` does not silently exempt a line. Only the marked line is exempted —
# the rest of the file is still scanned for an undeclared regression. The marker is matched
# against the line's COMMENT tail (via the shared `_comment_split` above), never the raw line,
# so the literal text appearing inside a BALANCED string/regex literal cannot spoof an exemption
# (see the `_comment_split` note above for the unbalanced-quote residual it inherits).
_MARKER_RE = re.compile(r"#\s*superseded-key-ok:\s*\S")

# Whole-file declared exemptions — genuinely non-scannable sites that must keep the superseded
# spelling (frozen records, fixtures, the rename map, changelog / changeset / doc prose). Live
# migration files that are mostly scannable use the line-scoped `# superseded-key-ok:` marker
# above instead (issue #1096). Path prefixes (dirs) and exact paths. Edited together with the
# do-not-sweep list in issue #1084 / CLAUDE.md.
_EXEMPT_PREFIXES = (
    ".changeset/",                 # changelog prose describing a fix legitimately names the old key
    ".prflow/learnings/",          # frozen append-only retrospective records (rewriting falsifies them)
    ".prflow/logs/",               # frozen census snapshots / TSV logs
    "lib/test/fixtures/",          # test fixtures that assert on the superseded spelling
    "lib/test/modules/tier1-rename-migration",  # the migration test drives the rename itself
)
_EXEMPT_EXACT = frozenset(
    {
        "install.sh",                       # config scan probes BOTH blocks; names both spellings deliberately
        "docs/internal/install.md",                  # sample installer output names both spellings deliberately
        "docs/external/release-notes.md",   # past-dated historical record (past-time snapshot exemption)
        "CHANGELOG.md",                     # historical changelog entries
        "lib/rename-map.json",              # the single source of truth for the rename itself
        # Live migration files (lib/migrate-config-values.py, scripts/scaffold-config.sh,
        # scripts/migrate-consumer-tier1.sh, scripts/config-get.sh) moved to LINE-scoped
        # `# superseded-key-ok:` markers (issue #1096) — they are scannable, so a whole-file
        # exemption would hide an undeclared dead-family read in exactly the highest-risk place.
        "lib/test/modules/installer-wiring.sh",   # migration-semantics comment + workflow-filename fixtures
        "lib/test/pin-corpus-lint.py",      # builds the rename substitution from the map
        "lib/test/test_pin_corpus_lint.py",       # its fixtures carry the superseded spelling
        "lib/test/mutation-pin-corpus-adjudications.tsv",  # frozen pin-corpus census snapshot
        "lib/test/lint-superseded-config-keys.py",  # this guard states the pattern in prose
    }
)


def _exempt(path: str) -> bool:
    if path in _EXEMPT_EXACT:
        return True
    return any(path.startswith(pfx) for pfx in _EXEMPT_PREFIXES)


def main() -> int:
    try:
        population = _pop.enumerate_population(
            _REPO_ROOT, None, ls_files_argv=_pop.LS_FILES_INDEX
        )
    except _pop.EnumerationError as exc:
        sys.stderr.write(f"lint-superseded-config-keys: {exc}\n")
        return 2

    offenders: list[str] = []
    skipped: list[str] = []
    for path in population:
        if _exempt(path):
            continue
        if Path(path).suffix.lower() in _BINARY_SUFFIXES:
            continue  # binary by extension: no text config-leaf reference possible
        text, skip_reason = _pop.read_source(_REPO_ROOT / path, skip_nul=True)
        if text is None:
            # A selected file that could not be audited is NEVER a clean pass — "audited
            # nothing" must not read as "audited everything, found nothing" (the shared
            # reader's own contract, and the sibling #711 lints' convention). Fail closed.
            skipped.append(f"{path}: {skip_reason or 'unknown'}")
            continue
        for lineno, line in enumerate(text.split("\n"), 1):
            if _MARKER_RE.search(_tree._comment_split(line)[1]):
                # Line-scoped exemption (issue #1096): a live migration file legitimately names
                # a superseded leaf on this line and declares it. Only THIS line is exempt. The
                # marker is tested against the COMMENT tail (quote/escape-aware via the shared
                # `_comment_split`), so the literal text inside a BALANCED string/regex cannot
                # spoof it (unbalanced-quote residual noted at the `_comment_split` import above).
                continue
            for m in _LEAF_RE.finditer(line):
                if m.group(1) in _EXTENSIONS:
                    continue
                offenders.append(f"{path}:{lineno}: {m.group(0)}")

    if offenders:
        sys.stderr.write(
            "lint-superseded-config-keys: superseded config-key leaf found "
            "(the family was renamed by issue #1002; rename to the `prflow*` family, or add a "
            "declared exemption if this site must keep the superseded spelling):\n"
        )
        for o in offenders:
            sys.stderr.write(f"  {o}\n")
    if skipped:
        sys.stderr.write(
            f"lint-superseded-config-keys: {len(skipped)} selected path(s) could not be audited "
            "(a partial audit is not a clean pass — permission blip, worktree race, or an "
            "unexpected non-UTF-8/binary file that no _BINARY_SUFFIXES entry covers):\n"
        )
        for s in skipped:
            sys.stderr.write(f"  {s}\n")
    return 1 if (offenders or skipped) else 0


if __name__ == "__main__":
    raise SystemExit(main())
