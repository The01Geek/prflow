#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Coverage-map ratchet guard (issue #591).

Fails RED — never a skip, never a silent pass — when the module coverage map
(`lib/test/modules/coverage-map.json`) falls out of sync with the git-tracked
`lib/` / `scripts/` surface or the module registry, so a new code unit cannot
ship without a recorded coverage decision.

Selection path derives every decision through `git` and `python3` ONLY (both
preflight-guaranteed; CLAUDE.md guard-class 2 forbids a non-preflight PATH tool
deciding a selection): git-tracked paths come from `git ls-files` (an index read,
shallow-clone-safe, reads no history), and all shape/membership logic is Python.

The guard is importable — `evaluate(...)` is a pure function over
(tracked_files, map value, registry value) so `test_coverage_map_guard.py` can
drive every one of its arms with synthetic fixtures — and runnable as a CLI:
`python3 lib/test/coverage_map_guard.py [repo_root]` prints one violation per
line to stdout and exits non-zero on any violation (or a fail-closed input
error), 0 when clean.
"""
from __future__ import annotations

import functools
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

# The `-c core.quotePath=false` option pair, imported from the shared population reader
# (issue #1217) rather than re-spelled here, so the literal keeps one home in the tree.
# This module builds its own `git -C <root> …` argvs, so it cannot use that module's
# ready-made argvs — only the option pair they are built from. Without it, git's default
# C-quoting returns a tracked non-ASCII path as a string that names no real file, and a
# coverage-map entry for that path would read as untracked.
_POP_PATH = Path(__file__).resolve().parent / "lint_population.py"
try:
    _pop_spec = importlib.util.spec_from_file_location("lint_population", _POP_PATH)
    if _pop_spec is None or _pop_spec.loader is None:
        raise ImportError(f"no loadable spec for {_POP_PATH}")
    _pop = importlib.util.module_from_spec(_pop_spec)
    _pop_spec.loader.exec_module(_pop)
except Exception as _exc:
    raise SystemExit(
        f"coverage_map_guard: the shared population reader {_POP_PATH} could not be "
        f"loaded ({_exc.__class__.__name__}: {_exc}); refusing to audit"
    ) from _exc
# Validate the SHAPE, not just presence: `hasattr` is satisfied by an emptied
# `QUOTE_PATH_OFF = ()`, which splices nothing and silently reinstates the defect, and by a
# bare string, which `tuple()` would explode into one argv element per character. Comparing
# against the expected pair makes either failure name the constant rather than surfacing as
# a green run or an unrecognised-git-option error.
_qp = getattr(_pop, "QUOTE_PATH_OFF", None)
if _qp != ("-c", "core.quotePath=false"):
    raise SystemExit(
        f"coverage_map_guard: {_POP_PATH}'s `QUOTE_PATH_OFF` is not the expected "
        f"`-c core.quotePath=false` option pair (got {_qp!r}); refusing to audit"
    )
QUOTE_PATH_OFF = tuple(_qp)

MAP_REL = "lib/test/modules/coverage-map.json"
REGISTRY_REL = "scripts/workflow-flight-recorder-registry.json"
RUN_SH_REL = "lib/test/run.sh"
GUARD_REL = "lib/test/coverage_map_guard.py"
MODULES_GLOB = "lib/test/modules/*.sh"
PROFILES_REL = "lib/capability-profiles.json"
CONFIG_REL = ".prflow/config.json"

# The synthetic aggregate key: no mechanical derivation ever produces it, so both
# halves of arm 9 exempt it rather than reporting it as a stale entry.
UNLABELED_KEY = "unlabeled"

# The depth-1 patterns, as (top-level dir, extension) pairs. Complete by
# construction at seeding time (issue #591 AC). Note scripts/*.jq is deliberately
# NOT a pattern — a depth-1 scripts/*.jq is a code unit outside the set, caught by
# arm 5 (absent from non_code_exempt) so the pattern set itself is ratcheted.
PATTERNS = frozenset(
    {("lib", ".sh"), ("lib", ".jq"), ("lib", ".py"), ("scripts", ".sh"), ("scripts", ".py")}
)
CODE_EXTS = frozenset({".sh", ".jq", ".py"})
TOP_DIRS = frozenset({"lib", "scripts"})
UNMODULARIZED = "unmodularized"

MAP_REMEDY = (
    f"repair or regenerate {MAP_REL} per CONTRIBUTING.md's module-authoring "
    "checklist (schema_version 1; files/run_sh_blocks objects; "
    "non_code_exempt/exempt_subtrees arrays; generated_by string)"
)
REGISTRY_REMEDY = (
    f"repair {REGISTRY_REL} so test_modules is a JSON object of module entries"
)


# ── Shared label derivation (issue #695) ──────────────────────────────────────
# ONE implementation, used for lib/test/run.sh and for every lib/test/modules/*.sh,
# so the monolith half and the module half of arm 9 can never disagree about what a
# "label" is. It anchors on ASSERTION-NAME POSITION — the first quoted argument of an
# assertion call — so `# see issue #533` in a comment, or a `#533` inside a later
# argument, derives nothing. That positional anchor is the whole point: a label set
# derived by scanning for `#\d+` anywhere would attribute a module's *history notes*
# as coverage it does not carry.

# Assertion heads recognized everywhere: the monolith's helpers plus the namespaced
# harness API a module uses instead of them. This set is a SUPERSET of
# `lib/test/pin-corpus-lint.py`'s `HELPERS` table, which keys the same helpers over the
# same two corpora — a coupling `test_coverage_map_guard.py` asserts, so a helper added
# there can never leave this derivation silently under-reporting. The two counters
# (`pin_count` / `devflow_module_pin_count`) take a pinned literal in first position
# rather than a name; they are listed for whole-API coverage, and measured against the
# shipped tree they derive no label the assertion heads do not already derive.
_BASE_ASSERTION_HEADS = (
    "assert_eq",
    "assert_true",
    "assert_pin_unique",
    "assert_pin_red_on_removal",
    "check",
    "pin_count",
    "devflow_module_pin_unique",
    "devflow_module_pin_present",
    "devflow_module_pin_count",
)

_FUNCTION_DEF_RE = re.compile(r"([ \t]*)([A-Za-z_][A-Za-z0-9_]*)\(\)[ \t]*\{")
_LABEL_RE = re.compile(r"#(\d{2,5})")


def _function_bodies(lines: list[str]) -> dict[str, str]:
    """Map each `name() {` definition in LINES to its body text.

    A ONE-LINE definition (`mktemp() { return 1; }` — the fixture-stub shape
    `lib/test/run.sh` uses to shadow a command inside a subshell) yields only the text
    between its own braces. Otherwise the body runs to the first line that closes the
    definition at the SAME indentation — the shape every multi-line helper in this
    repo's shell sources uses. Handling the one-liner separately is load-bearing: its
    closer never appears on a line of its own, so a shared fallback would hand a stub
    named `sed`/`mktemp` a "body" made of the surrounding real assertions and promote
    it to an assertion head. A definition whose closer is genuinely never found yields
    the remainder of the file, which can only over-approximate.

    Takes the already-split LINES rather than the raw text: a `finditer` over the whole
    file would need each match's line number, and deriving that with `text.count("\n",
    0, start)` rescans the prefix per match — hundreds of megabytes of scanning on the
    50,000-line monolith, for a fact a single ordered pass already has."""
    bodies: dict[str, str] = {}
    for line_index, line in enumerate(lines):
        match = _FUNCTION_DEF_RE.match(line)
        if match is None:
            continue
        name, indent, brace_offset = match.group(2), match.group(1), match.end()
        if "}" in line[brace_offset:]:
            bodies[name] = line[brace_offset : line.rindex("}")]
            continue
        closer = indent + "}"
        end = len(lines)
        for offset in range(line_index + 1, len(lines)):
            if lines[offset] == closer or lines[offset].startswith(closer + " "):
                end = offset
                break
        bodies[name] = "\n".join(lines[line_index + 1 : end])
    return bodies


def _assertion_heads(lines: list[str]) -> set[str]:
    """The base heads plus every module-private assertion wrapper defined in LINES.

    A wrapper is a function that FORWARDS ITS OWN FIRST POSITIONAL into a recognized
    head's name slot — `assert_eq "$1" …`, `devflow_module_pin_unique "$1" …`, `"$@"` —
    the shape of `_cap_fail`, `_ra_has`, `_raf_pin_unique`, `drp` and friends — including
    the local-variable hop `local name="$1"; assert_eq "$name" …` that `_cap_fail` uses.
    Discovery iterates to a fixpoint so a wrapper around a wrapper is also covered; each
    pass tests only the heads the previous pass added, since a body already checked
    against an older head cannot newly match it.

    The forwarding requirement is what keeps the over-approximation safe. Merely
    *containing* a head is far too loose: `lib/test/run.sh` writes fixture stub scripts
    inside heredocs, so a `sed() {` / `mktemp() {` line inside one is picked up as a
    definition whose apparent body bleeds into surrounding real assertions. Treating
    those as heads would make every ordinary `sed 's/#604/#609/'` derive a spurious
    label from a fixture argument — a name the tree never asserts."""
    heads = set(_BASE_ASSERTION_HEADS)
    pending = {
        name: body
        for name, body in _function_bodies(lines).items()
        if name not in heads
    }
    frontier = list(heads)
    while frontier:
        current, frontier = frontier, []
        for name in list(pending):
            if any(_forwards_first_positional(head, pending[name]) for head in current):
                heads.add(name)
                frontier.append(name)
                del pending[name]
    return heads


def _forwarding_aliases(body: str) -> set[str]:
    """Names inside BODY bound to the caller's own first positional.

    A wrapper does not always pass `"$1"` straight through: the repo's own
    `_cap_fail` opens `local name="$1" mut="$2" …` and then calls
    `assert_eq "$name" …`. Matching only the literal `"$1"` misses that
    local-variable hop, which would leave every label a module asserts *solely*
    through such a wrapper underived — a vacuous completeness guarantee in the arm
    whose entire job is completeness."""
    aliases = {"1", "@", "{1}"}
    # Match a pure forward of the first positional only: bare `$1` or the balanced
    # `${1}`. An unbalanced `\{?1\}?` also swallowed default/alternate-expansion forms
    # such as `name="${1:-default}"`, binding `name` as a forwarding alias when it is not
    # a straight pass-through of "$1"; the balanced `\$(?:1|\{1\})` rejects those.
    for name in re.findall(r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)=\"?\$(?:1|\{1\})\"?", body):
        aliases.add(name)
        aliases.add("{" + name + "}")
    return aliases


def _forwards_first_positional(head: str, body: str) -> bool:
    """True when BODY invokes HEAD with the caller's own first positional as the name."""
    alternation = "|".join(
        sorted((re.escape(alias) for alias in _forwarding_aliases(body)), key=len, reverse=True)
    )
    return re.search(
        rf"(?<![A-Za-z0-9_]){re.escape(head)}[ \t]+\"\$(?:{alternation})\"",
        body,
    ) is not None


def derive_labels(text: str) -> set[str]:
    """Return the issue labels TEXT asserts, as bare digit strings.

    A label is derived only from the first quoted argument of an assertion call — the
    assertion NAME. Comment lines are excluded two ways that agree: an explicit pre-scan
    drops every line whose first non-blank character is `#` (below), and, independently, a
    `#` comment carries no assertion head in command position followed by a quoted name,
    so it would underive on the positional anchor even without that drop."""
    lines = text.split("\n")
    call_re = _call_pattern(frozenset(_assertion_heads(lines)))
    # An assertion head can never be invoked from inside a `#` comment line, so the
    # comment lines are dropped before the scan — this is what makes a label token
    # that appears only in a comment underive, per the arm's positional contract.
    code = "\n".join(line for line in lines if not line.lstrip().startswith("#"))
    labels: set[str] = set()
    for match in call_re.finditer(code):
        labels.update(_LABEL_RE.findall(match.group(1)))
    return labels


@functools.cache
def _call_pattern(heads: frozenset[str]):
    """Compiled `<head> <quoted-name>` matcher for a head set.

    Cached because modules that define no wrapper all resolve to the same base head
    set and share one compile. The separator admits a
    `\\`-continuation, so a call whose name argument wraps to the next line is still
    anchored at name position rather than silently missed."""
    alternation = "|".join(sorted((re.escape(head) for head in heads), key=len, reverse=True))
    return re.compile(
        rf"(?<![A-Za-z0-9_])(?:{alternation})[ \t\\\n]+(\"(?:[^\"\\]|\\.)*\"|'[^']*')"
    )


def _depth1(path: str) -> bool:
    parts = path.split("/")
    return len(parts) == 2 and parts[0] in TOP_DIRS


def _ext(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    dot = name.rfind(".")
    return name[dot:] if dot > 0 else ""


def _matches_pattern(path: str) -> bool:
    return _depth1(path) and (path.split("/")[0], _ext(path)) in PATTERNS


def _under_lib_or_scripts(path: str) -> bool:
    return path.split("/")[0] in TOP_DIRS and "/" in path


def _valid_owner(owner: object, valid_ids: set[str] | None) -> bool:
    if owner == UNMODULARIZED:
        return True
    if valid_ids is None:
        # Registry unreadable/wrong-shape: the comparand set is unavailable, so
        # owner validity cannot be established. Arm 8 already recorded the
        # registry failure; do not double-report every owner here.
        return True
    return isinstance(owner, str) and owner in valid_ids


def _registry_module_ids(registry_value: object) -> set[str] | None:
    """Return the set of registered test_modules ids, or None if the registry is
    absent/unreadable/wrong-shape (including a non-object test_modules section)."""
    if not isinstance(registry_value, dict):
        return None
    modules = registry_value.get("test_modules")
    if not isinstance(modules, dict):
        return None
    return set(modules.keys())


def _map_shape_error(map_value: object) -> str | None:
    """Return a specific breadcrumb if the map is not a well-shaped object, else None.

    Structural types only — arm 4. Owner *values* are checked by arm 3, and an
    empty-but-legal `files: {}` is a valid shape (it makes every unit unlisted,
    caught non-vacuously by arm 1), so it is NOT a shape error here."""
    if not isinstance(map_value, dict):
        return f"coverage-map is not a JSON object; {MAP_REMEDY}"
    # bool is an int subclass, so `isinstance(True, int)` is True and `True == 1`; reject
    # bool explicitly (mirrors the sibling generator's T13e manifest_version guard) so a
    # `"schema_version": true` is not accepted as integer 1.
    schema_version = map_value.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version != 1:
        return f"coverage-map schema_version must be integer 1; {MAP_REMEDY}"
    if not isinstance(map_value.get("files"), dict):
        return f"coverage-map 'files' must be a JSON object; {MAP_REMEDY}"
    if not isinstance(map_value.get("run_sh_blocks"), dict):
        return f"coverage-map 'run_sh_blocks' must be a JSON object; {MAP_REMEDY}"
    if not isinstance(map_value.get("non_code_exempt"), list):
        return f"coverage-map 'non_code_exempt' must be a JSON array; {MAP_REMEDY}"
    if not isinstance(map_value.get("exempt_subtrees"), list):
        return f"coverage-map 'exempt_subtrees' must be a JSON array; {MAP_REMEDY}"
    if not isinstance(map_value.get("generated_by"), str):
        return f"coverage-map 'generated_by' must be a string; {MAP_REMEDY}"
    for key, entry in map_value["files"].items():
        if not isinstance(entry, dict) or not isinstance(entry.get("owner"), str):
            return f"coverage-map files entry {key!r} must be an object with a string 'owner'; {MAP_REMEDY}"
        # `focused_test` (issue #789) is OPTIONAL — its absence is the ordinary case
        # (no recorded focused Python test), so only a PRESENT-but-non-string value is a
        # shape error. The semantic checks (tracked, test_*.py, executable) are arm 10's.
        if "focused_test" in entry and not isinstance(entry["focused_test"], str):
            return f"coverage-map files entry {key!r} 'focused_test' must be a string when present; {MAP_REMEDY}"
    for key, entry in map_value["run_sh_blocks"].items():
        if not isinstance(entry, dict) or not isinstance(entry.get("owner"), str):
            return f"coverage-map run_sh_blocks entry {key!r} must be an object with a string 'owner'; {MAP_REMEDY}"
    for item in map_value["non_code_exempt"]:
        if not isinstance(item, str):
            return f"coverage-map non_code_exempt entries must be strings; {MAP_REMEDY}"
    for item in map_value["exempt_subtrees"]:
        if not isinstance(item, str):
            return f"coverage-map exempt_subtrees entries must be strings; {MAP_REMEDY}"
    return None


def evaluate(
    tracked_files,
    map_value,
    registry_value,
    *,
    map_read_error: str | None = None,
    registry_read_error: str | None = None,
    run_sh_labels: set[str] | None = None,
    module_labels: dict[str, set[str]] | None = None,
    scan_read_errors: list[str] | None = None,
    executable_files: set[str] | None = None,
    implement_tokens: set[str] | None = None,
    map_raw_text: str | None = None,
    map_raw_error: str | None = None,
):
    """Return a list of violation breadcrumbs (empty ⇒ clean). Never raises.

    Each arm records a FAIL line. `map_read_error` / `registry_read_error`
    carry a read/parse failure the CLI already hit (arms 4 / 8 fail closed on an
    absent/unreadable file too, not only a wrong shape).

    `run_sh_labels` / `module_labels` / `scan_read_errors` carry arm 9's derived
    inputs, produced by `main()` and injected here exactly like the read-error
    keywords, so this function performs no file access and its positional call
    contract is unchanged. Omitting them (every pre-existing caller) leaves arm 9
    stood down — it has no derivation to compare against, and inventing an empty one
    would report every mapped label as stale.

    `executable_files` carries arm 10's input — the set of git-tracked paths whose
    INDEX mode is executable (100755), produced by `main()` and injected the same way,
    so this function still performs no file access. `None` means the mode set could not
    be established; arm 10 then reports that unestablished measurement once and makes no
    per-entry executability claim (unknown is not "executable" and not "absent").

    `map_raw_text` / `map_raw_error` carry arm 11's input — the map file's raw bytes and
    a read failure — produced by `main()` and injected the same way, so this function
    still performs no file access. Both omitted (every pre-existing caller) leaves arm 11
    stood down: it has no on-disk bytes to compare against, and inventing an empty
    comparand would report the map as non-canonical on every pure-`evaluate` call."""
    violations = []

    # ── Arm 8: registry absent/unreadable/wrong-shape (incl. non-object test_modules)
    if registry_read_error is not None:
        violations.append(f"[arm8] registry unreadable: {registry_read_error}; {REGISTRY_REMEDY}")
        valid_ids = None
    else:
        valid_ids = _registry_module_ids(registry_value)
        if valid_ids is None:
            violations.append(
                f"[arm8] registry {REGISTRY_REL} is wrong-shape (test_modules is not a JSON object); {REGISTRY_REMEDY}"
            )

    # ── Arm 4: map absent/unreadable/wrong-shape → fail closed, skip map-dependent arms
    if map_read_error is not None:
        violations.append(f"[arm4] coverage-map unreadable: {map_read_error}; {MAP_REMEDY}")
        return violations
    shape_error = _map_shape_error(map_value)
    if shape_error is not None:
        violations.append(f"[arm4] {shape_error}")
        return violations

    files = map_value["files"]
    non_code_exempt = list(map_value["non_code_exempt"])
    exempt_subtrees = list(map_value["exempt_subtrees"])
    run_sh_blocks = map_value["run_sh_blocks"]
    tracked = set(tracked_files)
    non_code_set = set(non_code_exempt)

    # ── Arm 1: a git-tracked depth-1 pattern unit absent from `files`
    for path in sorted(tracked):
        if _matches_pattern(path) and path not in files:
            violations.append(
                f"[arm1] git-tracked depth-1 unit {path!r} matches a coverage pattern but is absent from coverage-map 'files' — add it with an owner"
            )

    # ── Arm 5: a git-tracked depth-1 file matching NO pattern, absent from non_code_exempt
    for path in sorted(tracked):
        if _depth1(path) and not _matches_pattern(path) and path not in non_code_set:
            hint = (
                " (it carries a code extension — extend the pattern set in map+guard+convention, never list a code file in non_code_exempt)"
                if _ext(path) in CODE_EXTS
                else ""
            )
            violations.append(
                f"[arm5] git-tracked depth-1 file {path!r} matches none of the coverage patterns and is absent from non_code_exempt{hint}"
            )

    # ── Arm 6: a git-tracked code file deeper than depth-1, outside every exempt subtree
    # Compare against a slash-terminated subtree prefix so an entry `lib/test` (no trailing
    # slash) matches `lib/test/x.sh` but NOT a sibling like `lib/testfoo/x.sh`.
    exempt_prefixes = [sub if sub.endswith("/") else sub + "/" for sub in exempt_subtrees]
    for path in sorted(tracked):
        if (
            _under_lib_or_scripts(path)
            and not _depth1(path)
            and _ext(path) in CODE_EXTS
            and not any(path.startswith(pref) for pref in exempt_prefixes)
        ):
            violations.append(
                    f"[arm6] git-tracked code file {path!r} is deeper than depth-1 and outside every exempt_subtrees entry — cover it or add its subtree to exempt_subtrees"
                )

    # ── Arm 2: a files or non_code_exempt entry naming a non-git-tracked path
    for path in sorted(files):
        if path not in tracked:
            violations.append(f"[arm2] coverage-map files entry {path!r} is not a git-tracked file")
    for path in non_code_exempt:
        if path not in tracked:
            violations.append(f"[arm2] coverage-map non_code_exempt entry {path!r} is not a git-tracked file")

    # ── Arm 7: a non_code_exempt entry whose path carries a code extension
    for path in non_code_exempt:
        if _ext(path) in CODE_EXTS:
            violations.append(
                f"[arm7] coverage-map non_code_exempt entry {path!r} carries a code extension — a code unit misfiled as non-code; move it to 'files' with an owner"
            )

    # ── Arm 3: an owner value that is neither a registered module id nor `unmodularized`
    for path in sorted(files):
        owner = files[path].get("owner")
        if not _valid_owner(owner, valid_ids):
            violations.append(
                f"[arm3] coverage-map files entry {path!r} owner {owner!r} is neither a registered test_modules id nor {UNMODULARIZED!r}"
            )
    for label in sorted(run_sh_blocks):
        owner = run_sh_blocks[label].get("owner")
        if not _valid_owner(owner, valid_ids):
            violations.append(
                f"[arm3] coverage-map run_sh_blocks entry {label!r} owner {owner!r} is neither a registered test_modules id nor {UNMODULARIZED!r}"
            )

    # ── Arm 9: run_sh_blocks completeness + fully-extracted attribution (issue #695)
    violations.extend(
        _arm9(run_sh_blocks, valid_ids, run_sh_labels, module_labels, scan_read_errors)
    )

    # ── Arm 10: the recorded focused Python test of a `files` entry (issue #789)
    violations.extend(_arm10(files, tracked, executable_files, implement_tokens))

    # ── Arm 11: the map on disk is byte-identical to its canonical serialization (#1065)
    violations.extend(_arm11(map_value, map_raw_text, map_raw_error))

    return violations


ARM9_REMEDY = f"run `python3 {GUARD_REL} . --fix` to repair {MAP_REL}"

# ── Arm 10: focused-test credit for the Python layer (issue #789) ─────────────
# The coverage map's `owner` field answers "which registered lib/test/run-module.sh
# module carries this unit", so a `scripts/*.py` helper whose coverage lives in a
# `lib/test/test_*.py` file has no shell module and is correctly `unmodularized` — which
# used to leave the focused-verification policy with no focused target and route every
# Python change to the ~10-minute full suite. `focused_test` is the ORTHOGONAL field that
# records that Python target explicitly (never inferred from a filename heuristic, per the
# repo's "changed files never auto-route" discipline), leaving `owner` semantics and arms
# 3/8/9 untouched.
#
# A recorded target must be *usable as a focused run on both tiers*, which is what this arm
# checks: git-tracked (it ships), named `test_*.py` (it is a test, not an arbitrary script),
# and EXECUTABLE IN THE INDEX. The exec bit is load-bearing rather than cosmetic — the cloud
# matcher denies the interpreter-head shape `python3 <script>` (issue #401) while granting a
# direct leading token, so a non-executable target is a map entry promising a focused run the
# cloud tier cannot make. The index mode (`git ls-files -s`) is the comparand, not the
# working-tree mode, because the index mode is the one that ships.
ARM10_REMEDY = (
    "record a git-tracked, executable lib/test/test_*.py path (chmod +x it and stage the "
    "mode change), or drop the 'focused_test' key"
)


def _focused_test_target(value: str) -> str:
    """The file path of a `focused_test` value, dropping an optional `::selector` suffix.

    A recorded value may narrow to a single test (`lib/test/test_module_harness.py::Cls.test`).
    The `::` is this FIELD's own separator, deliberately not the space-separated form a
    unittest selector takes on the command line (`lib/test/test_module_harness.py Cls.test`) —
    a space would make the value ambiguous with a path containing one. Only the part before
    `::` names a file, so that is what the tracked/naming/mode checks read; a consumer turning
    the value into a command splits on `::` and passes the selector as a separate argv word."""
    return value.split("::", 1)[0]


def _implement_profile_tokens(manifest_value: object) -> set[str] | None:
    """The `implement` profile's literal Bash(...) grant tokens, or None if unestablished.

    Group references (`@name`) are expanded one level — the manifest's own shape — so a token
    granted through a group is seen. A malformed/absent manifest returns None so arm 10 can
    report the measurement as unestablished rather than as an absent grant."""
    if not isinstance(manifest_value, dict):
        return None
    profiles = manifest_value.get("profiles")
    groups = manifest_value.get("groups")
    if not isinstance(profiles, dict) or not isinstance(groups, dict):
        return None
    implement = profiles.get("implement")
    if not isinstance(implement, list):
        return None
    tokens = set()
    for entry in implement:
        if not isinstance(entry, str):
            continue
        if entry.startswith("@"):
            member = groups.get(entry[1:])
            if isinstance(member, list):
                tokens.update(t for t in member if isinstance(t, str))
            continue
        tokens.add(entry)
    return tokens


def _config_implement_tokens(config_value: object) -> set[str] | None:
    """`.prflow/config.json`'s `prflow_implement.allowed_tools` grant tokens, or None if
    unestablished. This is the self-repo-only grant channel (issue #1078): a token moved
    here is added to the effective cloud implement allowlist at trigger time (issue #593)
    without shipping in the manifest, so arm 10 must honor it alongside the `implement`
    profile. A malformed/absent config returns None (the caller unions it with the
    manifest, so an absent config never turns a manifest-granted token into a violation)."""
    if not isinstance(config_value, dict):
        return None
    # Distinguish a legitimately-ABSENT key (silent None — a consumer ships the channel
    # empty) from a PRESENT-but-wrong-typed one (a maintainer misconfiguration that would
    # otherwise vanish silently and misdirect arm 10's "add the token to the config
    # channel" remedy at a channel that is in fact unusable). The best-effort-parser
    # convention wants a specific breadcrumb per non-absent bad shape; a valid-JSON
    # wrong-type is invisible to _load_json, so it is surfaced here.
    if "prflow_implement" not in config_value:
        return None
    section = config_value.get("prflow_implement")
    if not isinstance(section, dict):
        print(
            f"[input-error] {CONFIG_REL}: 'prflow_implement' is present but not a JSON "
            f"object ({type(section).__name__}); its self-repo grant channel is unusable "
            "so no 'focused_test' cloud grant was read from it",
            file=sys.stderr,
        )
        return None
    if "allowed_tools" not in section:
        return None
    allowed = section.get("allowed_tools")
    if not isinstance(allowed, list):
        print(
            f"[input-error] {CONFIG_REL}: 'prflow_implement.allowed_tools' is present but "
            f"not a JSON array ({type(allowed).__name__}); its self-repo grant channel is "
            "unusable so no 'focused_test' cloud grant was read from it",
            file=sys.stderr,
        )
        return None
    return {t for t in allowed if isinstance(t, str)}


def _resolve_implement_grant_tokens(
    manifest_value: object, config_value: object
) -> set[str] | None:
    """Union of the two cloud implement grant channels (issue #1078): the manifest's
    `implement` profile (the baked baseline) and `.prflow/config.json`'s
    `prflow_implement.allowed_tools` (the self-repo channel). None ONLY when NEITHER
    channel can be established — so a token granted through either is honored, while a
    total read failure is still reported by arm 10 as unestablished rather than laundered
    into an absent grant on every entry."""
    manifest_tokens = _implement_profile_tokens(manifest_value)
    config_tokens = _config_implement_tokens(config_value)
    if manifest_tokens is None and config_tokens is None:
        return None
    return (manifest_tokens or set()) | (config_tokens or set())


def _arm10(files, tracked, executable_files, implement_tokens=None):
    """Validate every recorded `focused_test`. Pure — all inputs are injected."""
    violations = []
    # Keyed on PRESENCE, not truthiness: a present-but-empty `"focused_test": ""` passes
    # the shape check (it IS a string) and would be skipped as "absent" by a truthiness
    # test, shipping a map entry the docs describe as naming a runnable test while it
    # names nothing. Present-and-blank is a violation, not an omission.
    recorded = [path for path in sorted(files) if "focused_test" in files[path]]
    if not recorded:
        return violations
    if implement_tokens is None:
        violations.append(
            f"[arm10] the cloud implement grant token list could not be established from "
            f"either {PROFILES_REL} (the `implement` profile) or {CONFIG_REL} "
            f"(`prflow_implement.allowed_tools`), so no 'focused_test' entry's cloud grant "
            "was checked; repair the manifest and/or config"
        )
    if executable_files is None:
        # An unestablished mode set is reported ONCE and never collapsed onto either
        # answer: claiming "executable" would launder the failed measurement into a pass,
        # and claiming "not executable" would report every recorded entry as broken on the
        # strength of a measurement that never ran. The tracked/naming checks below do not
        # read this set, so they still run.
        violations.append(
            "[arm10] the git index executable-mode set could not be established, so no "
            f"'focused_test' entry's executability was checked; {ARM10_REMEDY}"
        )
    for path in recorded:
        value = files[path]["focused_test"]
        if not value.strip():
            violations.append(
                f"[arm10] coverage-map files entry {path!r} carries a present-but-empty "
                f"'focused_test' — record a target or drop the key; {ARM10_REMEDY}"
            )
            continue
        target = _focused_test_target(value)
        if target not in tracked:
            violations.append(
                f"[arm10] coverage-map files entry {path!r} focused_test {value!r} is not a "
                f"git-tracked file; {ARM10_REMEDY}"
            )
            continue
        name = target.rsplit("/", 1)[-1]
        if not (name.startswith("test_") and _ext(target) == ".py"):
            violations.append(
                f"[arm10] coverage-map files entry {path!r} focused_test {value!r} does not "
                f"name a lib/test/test_*.py file; {ARM10_REMEDY}"
            )
            continue
        if executable_files is not None and target not in executable_files:
            violations.append(
                f"[arm10] coverage-map files entry {path!r} focused_test {value!r} is not "
                "executable in the git index — the cloud matcher denies the `python3 "
                f"<script>` interpreter-head shape, so it is not focus-runnable there; {ARM10_REMEDY}"
            )
            continue
        # The exec bit is only HALF of cloud-runnability, and asserting the whole on the half
        # is the fail-open this check exists to avoid: an executable, tracked target the
        # `implement` profile does not grant is refused by the matcher SILENTLY (issue #363),
        # so the map would promise a focused run that never happens and produces no signal.
        # Verify the grant too, from the same manifest the workflow literals are generated
        # from, and report an unestablished manifest as unestablished.
        if implement_tokens is not None and f"Bash({target}:*)" not in implement_tokens:
            violations.append(
                f"[arm10] coverage-map files entry {path!r} focused_test {value!r} carries no "
                f"`Bash({target}:*)` grant in the cloud implement allowlist (neither the "
                f"`implement` profile of {PROFILES_REL} nor `prflow_implement.allowed_tools` "
                f"in {CONFIG_REL}) — the cloud matcher silently refuses an ungranted leading "
                "token, so the recorded focused run would produce no signal there; add the "
                "token to the config channel (self-repo) or the manifest and regenerate")
    return violations


def _fully_extracted(run_sh_labels, module_labels):
    """Return {label: sorted module ids} for labels a module carries and run.sh does not.

    A label a module carries while assertions REMAIN in run.sh is *partially*
    extracted and is deliberately absent from this mapping: a single `owner` string
    cannot truthfully describe split coverage, so such a label keeps `unmodularized`
    and is never an attribution violation."""
    carriers: dict[str, list[str]] = {}
    for module_id, labels in sorted(module_labels.items()):
        for label in _reportable(labels) - run_sh_labels:
            carriers.setdefault(label, []).append(module_id)
    return {label: sorted(ids) for label, ids in carriers.items()}


def _reportable(labels):
    """LABELS minus the synthetic aggregate key.

    Filtered once, here, at every boundary where a derived or mapped label set enters
    the arm — so no downstream loop needs its own exemption arm, and a loop added later
    cannot silently report or repair the synthetic key."""
    return set(labels) - {UNLABELED_KEY}


def _arm9(run_sh_blocks, valid_ids, run_sh_labels, module_labels, scan_read_errors):
    violations = []
    scan_read_errors = scan_read_errors or []
    for error in scan_read_errors:
        violations.append(
            f"[arm9] label-derivation source unreadable: {error}; an unreadable source is "
            f"NOT an empty label set — restore the file, then {ARM9_REMEDY}"
        )
    if run_sh_labels is None or module_labels is None:
        # No derivation was injected (a pure-`evaluate` caller, or a scan that could
        # not establish the monolith's label set). Stand down rather than report every
        # mapped label as unmatched — the read failure above is the recorded signal.
        return violations

    for label in sorted(_reportable(run_sh_labels) - set(run_sh_blocks), key=_label_sort_key):
        violations.append(
            f"[arm9] label {label!r} is asserted in {RUN_SH_REL} but has no "
            f"coverage-map run_sh_blocks entry — {ARM9_REMEDY}"
        )

    if valid_ids is None:
        # The registered-id set is unavailable, so "owner names a module carrying the
        # label" cannot be established. Arm 8 already recorded the registry failure;
        # stand down here exactly as _valid_owner does, rather than double-reporting.
        return violations
    if scan_read_errors:
        # A module file could not be read, so `module_labels` is knowingly INCOMPLETE and
        # "fully extracted" cannot be established: a label the unreadable module carries
        # would read as run.sh-only and its entry as correctly `unmodularized`, or a label
        # it alone carries would vanish from the carrier set. The run.sh-completeness half
        # above is unaffected (it reads only the monolith's own set), so it still runs; the
        # attribution half stands down and the named read error above is the signal.
        return violations

    for label, carriers in sorted(
        _fully_extracted(run_sh_labels, module_labels).items(), key=lambda kv: _label_sort_key(kv[0])
    ):
        named = ", ".join(carriers)
        entry = run_sh_blocks.get(label)
        if entry is None:
            violations.append(
                f"[arm9] label {label!r} is carried wholly by module(s) {named} and asserted "
                f"nowhere in {RUN_SH_REL}, but has no coverage-map run_sh_blocks entry — "
                f"{ARM9_REMEDY}"
            )
            continue
        owner = entry.get("owner")
        if owner not in carriers:
            violations.append(
                f"[arm9] label {label!r} is fully extracted into module(s) {named} but its "
                f"coverage-map run_sh_blocks owner is {owner!r} — attribute it to a module "
                f"that carries it; {ARM9_REMEDY}"
            )
    return violations


def _label_sort_key(label: str):
    """Numeric-first ordering so violation lists are stable and human-readable."""
    return (0, int(label)) if label.isdigit() else (1, label)


# ── Arm 11: the on-disk map is in canonical serialized form (issue #1065) ─────
ARM11_REMEDY = f"run `python3 {GUARD_REL} . --fix` to re-canonicalize {MAP_REL}"


def _serialize_map(map_value) -> str:
    """The ONE canonical serialization of the coverage map (issue #1065).

    Two-space indent, recursively sorted keys, `ensure_ascii=False` (non-ASCII kept as
    UTF-8), one trailing newline. `_write_map` WRITES this and arm 11 CHECKS against it,
    so the writer and the checker cannot disagree about what "canonical" means — the
    pinned shape has a single definition. `sort_keys=True` sorts object keys RECURSIVELY,
    so it constrains both the `files` and `run_sh_blocks` object key order; it does NOT
    reorder JSON ARRAY elements, so `non_code_exempt` / `exempt_subtrees` keep their given
    order and this arm makes no claim about array order."""
    return json.dumps(map_value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _is_canonical(raw_text: str, map_value) -> bool:
    """True when RAW_TEXT is already the canonical serialization of MAP_VALUE.

    The single definition of "already canonical" that both the checker (`_arm11`) and the
    fixer (`_run_fix`) consume, so the two cannot disagree about when a write is a no-op."""
    return raw_text == _serialize_map(map_value)


def _arm11(map_value, map_raw_text, map_raw_error):
    """The map on disk must be byte-identical to its canonical serialization.

    Ordering drift — a merge-conflict resolution reordering `run_sh_blocks`, or a hand
    edit — leaves the parsed VALUE unchanged while the serialized bytes differ, so every
    presence/ownership arm passes and the non-canonical file ships. It is then silently
    rewritten later, in an unrelated author's change, by the first `--fix` that makes any
    real repair. This arm fails at the point the drift is introduced instead.

    Pure — every input is injected. `map_raw_error` is a read failure (an UNESTABLISHED
    measurement, never a pass — CLAUDE.md's "unknown is not zero"). Both inputs `None`
    means a pure-`evaluate` caller supplied no raw bytes; the arm stands down (like arm 9)
    rather than inventing a comparand. Runs only after the arm-4 shape check has passed —
    `evaluate` early-returns on a shape error before reaching here — so the serialization
    is never attempted on a malformed map."""
    if map_raw_error is not None:
        return [
            (f"[arm11] {MAP_REL} raw bytes could not be read ({map_raw_error}); its canonical "
            f"form is an unestablished measurement, not a pass — {ARM11_REMEDY}")
        ]
    if map_raw_text is None:
        return []
    if not _is_canonical(map_raw_text, map_value):
        return [
            (f"[arm11] {MAP_REL} on disk is not in canonical serialized form — its key order or "
            "formatting differs from what `--fix` writes (the parsed JSON value may be "
            "unchanged; only the serialized bytes drifted, e.g. from a merge-conflict "
            f"resolution) — {ARM11_REMEDY}")
        ]
    return []


def _git_tracked(repo_root: Path):
    """git-tracked repo-relative paths (index read; reads no history).

    `QUOTE_PATH_OFF` (issue #1217) keeps a tracked non-ASCII path raw; see its
    definition above for why."""
    result = subprocess.run(
        ["git", "-C", str(repo_root), *QUOTE_PATH_OFF, "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.split("\n") if line]


def _git_executable(repo_root: Path):
    """git-tracked repo-relative paths whose INDEX mode is executable, or None.

    `git ls-files -s` prints `<mode> <object> <stage>\\tpath`; mode 100755 is the
    executable regular-file mode. `QUOTE_PATH_OFF` (issue #1217) keeps a tracked
    non-ASCII path raw, so its mode row still joins against `_git_tracked`'s path.
    Returning None on any failure (rather than an empty
    set) keeps the unestablished case distinguishable from "nothing is executable" —
    arm 10 reports the former once and makes no per-entry claim. Index mode, not the
    working-tree mode, is the comparand: the index is what ships."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *QUOTE_PATH_OFF, "ls-files", "-s"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    executable = set()
    for line in result.stdout.split("\n"):
        if not line:
            continue
        meta, tab, path = line.partition("\t")
        if not tab or not meta.startswith("100755 "):
            continue
        executable.add(path)
    return executable


def _load_json(path: Path):
    """Return (value, error). A read/parse failure returns (None, breadcrumb)."""
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, f"{path} not found"
    except (OSError, UnicodeError) as error:
        return None, f"{path} unreadable ({error})"
    except json.JSONDecodeError as error:
        return None, f"{path} is malformed JSON ({error})"


def _scan_labels(repo_root: Path):
    """Read lib/test/run.sh and lib/test/modules/*.sh and derive their label sets.

    Returns (run_sh_labels, module_labels, read_errors). A source that cannot be read
    yields `None` (monolith) / an omitted module entry PLUS a named read error — never
    an empty label set, which would silently read as "this file asserts nothing" and
    turn a real completeness violation into a clean pass. All file access lives here,
    in main()'s call path; `evaluate` stays pure."""
    read_errors: list[str] = []
    try:
        run_sh_labels = derive_labels(
            (repo_root / RUN_SH_REL).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError) as error:
        run_sh_labels = None
        read_errors.append(f"{RUN_SH_REL} ({error})")
    module_labels: dict[str, set[str]] = {}
    for module_path in sorted((repo_root / "lib/test/modules").glob("*.sh")):
        module_id = module_path.stem
        try:
            module_labels[module_id] = derive_labels(
                module_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError) as error:
            read_errors.append(f"lib/test/modules/{module_path.name} ({error})")
    return run_sh_labels, module_labels, read_errors


def _apply_fix(map_value, run_sh_labels, module_labels):
    """Mutate MAP_VALUE's run_sh_blocks so arm 9 reports nothing. Returns True if changed.

    A missing run.sh label is added as `unmodularized` (its coverage is still in the
    monolith); a fully-extracted label's owner is set to a module that carries it. The
    repair never removes an entry — a map key with no derivation behind it is a curated
    historical record arm 9 deliberately does not report, so `--fix` does not delete it."""
    blocks = map_value["run_sh_blocks"]
    changed = False
    for label in sorted(_reportable(run_sh_labels) - set(blocks), key=_label_sort_key):
        blocks[label] = {"note": "", "owner": UNMODULARIZED}
        changed = True
    for label, carriers in _fully_extracted(run_sh_labels, module_labels).items():
        owner = carriers[0]
        entry = blocks.get(label)
        if entry is None:
            blocks[label] = {"note": "", "owner": owner}
            changed = True
        elif entry.get("owner") not in carriers:
            entry["owner"] = owner
            changed = True
    return changed


def _write_map(path: Path, map_value) -> str | None:
    """Write the map in its canonical serialized form via `_serialize_map` — the single
    definition of the pinned shape that arm 11 also checks against (issue #1065), so a
    `--fix` write and the canonical-form check can never disagree. Byte-identical to the
    checked-in file when nothing changed, which is what makes a second `--fix` run a no-op.

    Returns None on success, or a breadcrumb when the write fails. The write is the one
    remaining path that could leave `--fix` raising a raw traceback instead of this
    file's fail-closed-with-a-named-breadcrumb posture (a read-only map, a full disk)."""
    try:
        # write_bytes, NOT write_text: write_text translates `\n` to os.linesep, so on Windows
        # it would emit CRLF and make the "canonical form" the checker asserts platform-
        # dependent. Writing the encoded bytes pins the canonical serialization to LF on every
        # platform, so `--fix` output is byte-identical everywhere and arm 11 accepts it.
        path.write_bytes(_serialize_map(map_value).encode("utf-8"))
    except (OSError, UnicodeError, TypeError, ValueError) as error:
        return f"{path} could not be written ({error})"
    return None


def _run_fix(repo_root: Path) -> int:
    map_path = repo_root / MAP_REL
    map_value, map_error = _load_json(map_path)
    if map_error is not None:
        print(f"[fix-refused] coverage-map unreadable: {map_error}; {MAP_REMEDY}")
        return 1
    shape_error = _map_shape_error(map_value)
    if shape_error is not None:
        # Refuse to write rather than corrupt a malformed map: the repair assumes the
        # arm-4 shape, and a partial rewrite of a hand-corrupted file is worse than
        # leaving it exactly as the operator left it.
        print(f"[fix-refused] {shape_error}")
        return 1
    run_sh_labels, module_labels, read_errors = _scan_labels(repo_root)
    if read_errors or run_sh_labels is None:
        for error in read_errors:
            print(f"[fix-refused] label-derivation source unreadable: {error}")
        return 1
    changed = _apply_fix(map_value, run_sh_labels, module_labels)
    # Order-only drift (issue #1065): even with NO presence/ownership repair pending, a
    # non-canonical on-disk serialization (e.g. a merge-conflict resolution that reordered
    # run_sh_blocks) is re-canonicalized here, so `--fix` is the single canonicalizer arm
    # 11's remedy names. RECORDED SCOPE DECISION (the issue's "Prerequisite fact to
    # establish"): this deliberately widens `--fix` to write on order-only drift — the
    # minimal resolution that lets the violation's remedy name an action that actually
    # repairs it. The two MEASURED `--fix` paths are unchanged: a canonical file with no
    # repair still no-ops, and a real repair is still additive-only (the write serializes
    # canonically as it always did, inserting only the new blocks). The canonical-equality
    # test is the SAME `_is_canonical` predicate arm 11 checks against, so the fixer and the
    # checker cannot disagree about when a write is a no-op. A re-read failure (`current is
    # None`) is treated as non-canonical so `--fix` attempts the write and `_write_map`
    # surfaces any real write failure as a breadcrumb.
    try:
        # read_bytes().decode() for the same reason arm 11's read does: a CRLF on-disk map is
        # non-canonical and must be re-canonicalized, which read_text would mask.
        current = map_path.read_bytes().decode("utf-8")
    except (OSError, UnicodeError):
        current = None
    if changed or current is None or not _is_canonical(current, map_value):
        write_error = _write_map(map_path, map_value)
        if write_error is not None:
            print(f"[fix-refused] {write_error}; {MAP_REMEDY}")
            return 1
        print(f"[fix] repaired {MAP_REL}")
    else:
        print(f"[fix] {MAP_REL} already satisfies canonical form and the block-ownership arm")
    return 0


def main(argv):
    # `--fix` is a HAND-INVOKED repair, never wired into the batched generated-artifact
    # pass: lib/test/regenerate-artifacts.py keeps the coverage map a `by-hand` judgment
    # row whose `#619 A3` assertion proves the pass leaves it byte-unchanged. The
    # positional repo-root argument is unchanged, so lib/test/run.sh's existing
    # invocation needs no edit.
    positional = [argument for argument in argv[1:] if argument != "--fix"]
    repo_root = Path(positional[0]).resolve() if positional else Path.cwd()
    if "--fix" in argv[1:]:
        return _run_fix(repo_root)
    # git is preflight-guaranteed, but honor the file's fail-closed-with-a-named-breadcrumb
    # posture (the JSON reads do the same via _load_json) rather than letting a git failure
    # surface as a raw traceback.
    try:
        tracked = _git_tracked(repo_root)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as error:
        print(
            f"[input-error] git ls-files failed under {repo_root} ({error}); cannot "
            "enumerate the tracked lib/scripts surface — run from a git repo with git on PATH"
        )
        return 1
    map_value, map_error = _load_json(repo_root / MAP_REL)
    # Arm 11 (issue #1065) compares the map's raw on-disk bytes against their canonical
    # serialization, so read them here and inject them like every other arm's input
    # (evaluate stays pure). Only meaningful when the map parsed (map_error is None); a
    # re-read failure is an unestablished measurement arm 11 reports rather than a pass.
    map_raw_text, map_raw_error = None, None
    if map_error is None:
        try:
            # read_bytes().decode(), NOT read_text(): read_text opens with universal-newline
            # translation, so a CRLF-encoded file would decode to `\n` and compare EQUAL to the
            # `\n` canonical form — defeating arm 11's byte-identity claim exactly on the
            # Windows/merge-tool line-ending drift it exists to catch. Decoding the raw bytes
            # preserves the on-disk characters (an invalid-UTF-8 payload raises and is reported).
            map_raw_text = (repo_root / MAP_REL).read_bytes().decode("utf-8")
        except (OSError, UnicodeError) as error:
            map_raw_error = f"{repo_root / MAP_REL} unreadable ({error})"
    registry_value, registry_error = _load_json(repo_root / REGISTRY_REL)
    # Surface the two grant-channel read errors rather than discarding the tuple's error
    # half — a malformed .prflow/config.json (or capability-profiles.json) is otherwise
    # invisible, and arm 10 then tells the maintainer to "add the token to the config
    # channel" when the real cause is that the channel is unparseable. Print the breadcrumb
    # (never fail on it: the union already fails closed on an unestablished channel).
    profiles_value, profiles_error = _load_json(repo_root / PROFILES_REL)
    config_value, config_error = _load_json(repo_root / CONFIG_REL)
    # Surface an error only for a file that EXISTS (present-but-unreadable/malformed — the
    # maintainer misconfiguration worth a breadcrumb). A legitimately-absent optional file
    # is not surfaced: the union already fails closed on an unestablished channel, and a
    # fixture/consumer tree may lack either file without that being an error.
    for _path, _err in ((PROFILES_REL, profiles_error), (CONFIG_REL, config_error)):
        if _err and (repo_root / _path).exists():
            print(f"[input-error] {_err}; its cloud implement grant tokens were not read")
    run_sh_labels, module_labels, scan_read_errors = _scan_labels(repo_root)
    violations = evaluate(
        tracked,
        map_value,
        registry_value,
        map_read_error=map_error,
        registry_read_error=registry_error,
        run_sh_labels=run_sh_labels,
        module_labels=module_labels,
        scan_read_errors=scan_read_errors,
        executable_files=_git_executable(repo_root),
        implement_tokens=_resolve_implement_grant_tokens(profiles_value, config_value),
        map_raw_text=map_raw_text,
        map_raw_error=map_raw_error,
    )
    for line in violations:
        print(line)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
