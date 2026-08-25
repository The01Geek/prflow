#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Cloud-writer trust-closure dependency classification (issue #583, AC5).

Why this exists: the AC1 reachability contract (``cloud_writer_contract.py``)
names *which* bundled helper entry points a cloud writer session reaches, and
pins each to the vendored leading token the matcher grants. But a granted
leading token only vouches for the *first* executable token of a command — it
says nothing about what that helper then reaches when it runs: a sourced
sibling, an exec'd script, an imported module, or an external binary. This
module classifies those static source/exec/import edges out of every AC1-closure
helper entry point, so the executable trust boundary can be audited one hop
deep, not just at the leading token.

The classification is derived-plus-declared, mirroring the AC1 design
(``DISPATCH_EDGES`` is hand-declared data checked by a consistency guard):

* **import edges** (``.py`` entry points) and **source edges** (``.sh`` ``.``/
  ``source`` includes) are **derived** by static scan of the real source, so an
  added import or sourced sibling cannot silently escape the classification: a
  resolvable include/import is derived as its edge, and an include the scan
  cannot resolve (an extensionless operand, an untracked variable) is emitted as
  an ``unresolved-source`` edge the guard rejects — fail closed, never a silent
  drop (reverse-drift is structural).
* **exec edges** (an external binary or a repository-owned script the helper
  runs) are **declared** in ``EXEC_EDGES`` and **forward-verified** in executable
  command context (an external target counts the ``DEVFLOW_<TOOL>`` override
  form as evidence too): an invented, typo'd, comment-only, docstring-only, or
  unrelated-data token goes RED. This liveness check does not give exec edges
  the structural reverse-drift the derived kinds have — a newly-added,
  undeclared exec still escapes — the same disclosed tradeoff AC1's
  hand-declared ``DISPATCH_EDGES`` accepts.

``check_dependencies()`` is the AC5 guard. It fails when, among other checks:

* an AC1-closure entry point is not classified (coverage gap), or a ``.py``
  entry point yields zero import edges (an AST import-scan regression);
* a source include could not be resolved (an ``unresolved-source`` edge —
  rejected unconditionally, fail closed);
* an edge carries an unknown kind or class, or a repo-owned edge carries an
  authorization string;
* a **repository-owned** edge does not resolve beneath
  ``.prflow/vendor/prflow/`` (a repo-root ``../../scripts/…`` form escapes the
  vendored tree and is rejected), resolves outside the repository via a symlink,
  or its target file is absent on disk;
* an **external** runtime edge names no preflight guarantee (``lib/preflight.sh``
  guarantees ``git``/``gh``/``jq``/``python3``/PyYAML) or explicit profile grant;
* a declared exec edge's target token is absent from the helper source.

``classify_all()`` returns the full machine-readable classification (one row per
edge) — the AC5 deliverable — and ``main(["show"])`` prints it as JSON.
"""
from __future__ import annotations

import ast
import functools
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from posixpath import normpath

# Reuse the AC1 closure as the single source of truth for entry points and the
# one granted vendored prefix, so this classification can never name an entry
# point the reachability contract does not.
_LIBTEST = Path(__file__).resolve().parent
sys.path.insert(0, str(_LIBTEST))
import cloud_writer_contract as cwc  # noqa: E402

REPO_ROOT = cwc.REPO_ROOT
VENDOR_PREFIX = cwc.VENDOR_PREFIX  # ".prflow/vendor/prflow/"


def _declared_preflight_guarantees():
    """Read preflight.sh's canonical machine-readable runtime vocabulary."""
    source = (REPO_ROOT / "lib/preflight.sh").read_text(encoding="utf-8")
    matches = re.findall(
        r"^readonly -a _DEVFLOW_PREFLIGHT_GUARANTEES=\(([^)]*)\)\s*$",
        source,
        re.MULTILINE,
    )
    if len(matches) != 1:
        raise RuntimeError(
            "lib/preflight.sh must declare exactly one "
            f"_DEVFLOW_PREFLIGHT_GUARANTEES array (found {len(matches)})"
        )
    tokens = matches[0].split()
    if not tokens:
        raise RuntimeError(
            "lib/preflight.sh has an invalid preflight guarantee declaration: "
            "empty _DEVFLOW_PREFLIGHT_GUARANTEES array"
        )
    if len(tokens) != len(set(tokens)):
        dup = sorted({t for t in tokens if tokens.count(t) > 1})
        raise RuntimeError(
            "lib/preflight.sh has an invalid preflight guarantee declaration: "
            f"duplicate token(s) {dup}"
        )
    bad = [t for t in tokens if not re.fullmatch(r"[A-Za-z0-9_.+-]+", t)]
    if bad:
        raise RuntimeError(
            "lib/preflight.sh has an invalid preflight guarantee declaration: "
            f"malformed token(s) {bad}"
        )
    return frozenset(tokens)


# lib/preflight.sh guarantees exactly these external runtimes on PATH; an
# external edge is authorized only by naming one of them (or, below, an explicit
# profile grant). This is parsed from preflight.sh's own canonical declaration,
# so a prerequisite cannot drift between the enforcer and this classifier.
PREFLIGHT_GUARANTEES = _declared_preflight_guarantees()

EDGE_KINDS = frozenset({"source", "exec", "import", "unresolved-source"})
EDGE_CLASSES = frozenset({"repo-owned", "external"})

# The Python module name PyYAML installs (its import edge maps to the PyYAML
# preflight guarantee, not the stdlib).
_PYYAML_MODULE = "yaml"


def entry_points():
    """Sorted repo-relative source paths of every AC1-closure helper entry point.

    The union of REQUIRED_HELPER_HEADS across all cloud profiles, mapped from the
    vendored leading token back to its repository-owned source path.
    """
    paths = set()
    for heads in cwc.REQUIRED_HELPER_HEADS.values():
        for token in heads:
            paths.add(cwc._helper_source_path(token))
    return sorted(paths)


# --- AC5: declared exec edges (external binaries + repo-owned script execs) -----
# Each entry point maps to the binaries/scripts it *runs* (subprocess/exec), the
# one edge kind a static import/source scan cannot deterministically recover. An
# external target either names a preflight-guaranteed binary or carries the
# `_PROFILE_GRANT` marker: the cloud permission matcher authorizes that runtime
# transitively through the helper's explicit vendored-head grant. A repo-owned
# target is a repo-relative script path (resolved beneath the vendored tree by
# the guard). Every target here is forward-verified present in the helper source,
# so a stale declaration fails closed rather than vouching for an edge that no
# longer exists.
_EXT = "external"
_REPO = "repo-owned"
_PROFILE_GRANT = "profile-grant"


@dataclass(frozen=True, slots=True)
class ExecSpec:
    """Validated declaration for one exec edge.

    Named fields keep the optional authorization marker from being silently
    shifted into the wrong positional tuple slot.
    """

    target: str
    klass: str
    auth_source: str | None = None

    def __post_init__(self):
        if not isinstance(self.target, str) or not self.target:
            raise ValueError("exec target must be a non-empty string")
        if self.klass not in EDGE_CLASSES:
            raise ValueError(f"unknown exec class: {self.klass!r}")
        if self.auth_source not in (None, _PROFILE_GRANT):
            raise ValueError(f"unknown exec authorization source: {self.auth_source!r}")
        if self.klass == _REPO and self.auth_source is not None:
            raise ValueError("repo-owned exec edges cannot carry external authorization")


EXEC_EDGES = {
    "scripts/run-jq.sh": [ExecSpec("jq", _EXT)],
    "scripts/config-get.sh": [ExecSpec("git", _EXT), ExecSpec("python3", _EXT)],
    "scripts/workpad.py": [ExecSpec("gh", _EXT), ExecSpec("git", _EXT)],
    "scripts/parse-acs.py": [ExecSpec("gh", _EXT)],
    "scripts/branch-for-issue.py": [ExecSpec("git", _EXT)],
    "scripts/file-deferrals.py": [ExecSpec("gh", _EXT)],
    "scripts/match-deferrals.py": [
        ExecSpec("gh", _EXT),
        ExecSpec("git", _EXT),
        ExecSpec("scripts/config-get.sh", _REPO),
    ],
    # resolve-review-overrides.py delegates every config read to config-get.sh
    # (never re-parsing config itself) — a repository-owned exec edge.
    "scripts/resolve-review-overrides.py": [ExecSpec("scripts/config-get.sh", _REPO)],
    "scripts/stale-prose-lint.py": [ExecSpec("git", _EXT)],
    "scripts/match-lint-adjudications.py": [
        ExecSpec("git", _EXT),
        ExecSpec("scripts/config-get.sh", _REPO),
    ],
    "scripts/apply-labels.sh": [
        ExecSpec("dirname", _EXT, _PROFILE_GRANT),
        ExecSpec("gh", _EXT),
    ],
    "scripts/ensure-label.sh": [
        ExecSpec("dirname", _EXT, _PROFILE_GRANT),
        ExecSpec("gh", _EXT),
    ],
    "scripts/dismiss-stale-rejections.sh": [
        ExecSpec("dirname", _EXT, _PROFILE_GRANT),
        ExecSpec("gh", _EXT),
    ],
    "scripts/load-prompt-extension.sh": [
        ExecSpec("git", _EXT),
        ExecSpec("cat", _EXT, _PROFILE_GRANT),
    ],
    # render-prompt-extension.sh self-anchors to run the sibling loader
    # (a repo-owned exec edge), and uses mktemp/rm to capture the loader's stderr
    # into a scratch file it quotes into the status line. printf/cd/pwd/test and
    # its `$(<file)` read are bash builtins that start no process, so they are not
    # exec edges. mktemp/rm are not preflight guarantees, so they carry the
    # profile-grant marker (authorized transitively through the wrapper's own
    # vendored-head grant).
    "scripts/render-prompt-extension.sh": [
        ExecSpec("scripts/load-prompt-extension.sh", _REPO),
        ExecSpec("mktemp", _EXT, _PROFILE_GRANT),
        ExecSpec("rm", _EXT, _PROFILE_GRANT),
    ],
    "scripts/react-to-trigger.sh": [
        ExecSpec("dirname", _EXT, _PROFILE_GRANT),
        ExecSpec("gh", _EXT),
    ],
    "scripts/extract-doc-needed-paths.sh": [
        ExecSpec("cat", _EXT, _PROFILE_GRANT),
        ExecSpec("awk", _EXT, _PROFILE_GRANT),
        ExecSpec("grep", _EXT, _PROFILE_GRANT),
        ExecSpec("git", _EXT),
        ExecSpec("sort", _EXT, _PROFILE_GRANT),
    ],
    "scripts/update-branch-checkpoint.sh": [
        ExecSpec("scripts/config-get.sh", _REPO),
        ExecSpec("git", _EXT),
    ],
    # efficiency-trace.sh runs its jq program, a git history walk, and the
    # config_fingerprint.py helper (a repository-owned exec edge).
    "lib/efficiency-trace.sh": [
        ExecSpec("jq", _EXT),
        ExecSpec("git", _EXT),
        ExecSpec("python3", _EXT),
        ExecSpec("dirname", _EXT, _PROFILE_GRANT),
        ExecSpec("sort", _EXT, _PROFILE_GRANT),
        ExecSpec("wc", _EXT, _PROFILE_GRANT),
        ExecSpec("date", _EXT, _PROFILE_GRANT),
        ExecSpec("mkdir", _EXT, _PROFILE_GRANT),
        ExecSpec("rm", _EXT, _PROFILE_GRANT),
        ExecSpec("basename", _EXT, _PROFILE_GRANT),
        ExecSpec("mv", _EXT, _PROFILE_GRANT),
        ExecSpec("cp", _EXT, _PROFILE_GRANT),
        ExecSpec("scripts/config_fingerprint.py", _REPO),
    ],
}


@dataclass(frozen=True, slots=True)
class Edge:
    """One classified dependency edge out of a helper entry point.

    ``target`` is a binary name (external) or a repo-relative path (repo-owned).
    ``auth`` names the authorization for an external edge (a preflight guarantee
    or explicit helper-head profile grant); it is ``None`` for a repo-owned edge
    and for an *unauthorized* external edge (which the guard rejects).
    """

    helper: str
    kind: str
    target: str
    klass: str
    auth: str | None = None

    def __post_init__(self):
        if not isinstance(self.helper, str) or not self.helper:
            raise ValueError("edge helper must be a non-empty string")
        if self.kind not in EDGE_KINDS:
            raise ValueError(f"unknown edge kind: {self.kind!r}")
        if not isinstance(self.target, str) or not self.target:
            raise ValueError("edge target must be a non-empty string")
        if self.klass not in EDGE_CLASSES:
            raise ValueError(f"unknown edge class: {self.klass!r}")
        if self.auth is not None and (not isinstance(self.auth, str) or not self.auth):
            raise ValueError("edge authorization must be a non-empty string or None")
        if self.klass == _REPO and self.auth is not None:
            raise ValueError("repo-owned edges cannot carry external authorization")

    def as_dict(self):
        return {
            "helper": self.helper,
            "kind": self.kind,
            "target": self.target,
            "class": self.klass,
            "auth": self.auth,
        }

@functools.lru_cache(maxsize=None)
def _read(rel):
    # Sources are read-only within a run and each entry point is read by both the
    # scanner and exec-edge forward-verification, so memoize to one read per file.
    # NOTE: the cache is keyed by `rel` only — a test that swaps REPO_ROOT must
    # also replace/patch `_read` (the existing test idiom) or it reads stale bytes.
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _module_paths(parent, module, *, preserve_missing=False):
    """Return the files Python loads for ``module`` beneath ``parent``.

    Every package initializer on a dotted import is a dependency in its own
    right.  Package directories win over same-name flat modules, matching
    Python's path finder.  A relative import may request a deterministic missing
    leaf so the dependency guard reports the broken edge rather than dropping it.
    """
    parts = module.split(".")
    cursor = Path(parent)
    paths = []
    for index, part in enumerate(parts):
        package = cursor / part / "__init__.py"
        flat = Path(str(cursor / part) + ".py")
        if (REPO_ROOT / package).is_file():
            paths.append(package.as_posix())
            cursor /= part
            continue
        if (REPO_ROOT / flat).is_file():
            paths.append(flat.as_posix())
            # A flat module cannot contain the remaining dotted components.
            if index < len(parts) - 1:
                if preserve_missing:
                    paths.append((cursor / part / parts[index + 1]).with_suffix(".py").as_posix())
                else:
                    return []
            return paths
        namespace = cursor / part
        if (REPO_ROOT / namespace).is_dir():
            # PEP 420 namespace packages have no initializer edge; continue to
            # the concrete module/package file that the import actually loads.
            if index == len(parts) - 1:
                return paths
            cursor = namespace
            continue
        if preserve_missing:
            missing = flat if index == len(parts) - 1 else package
            paths.append(missing.as_posix())
            return paths
        return []
    return paths


def _sibling_module_paths(helper, module, *, preserve_broken=True):
    """Files for an absolute import; ``None`` means external.

    PEP 420 namespace portions are accumulated only while searching for a
    regular package/module. A later regular package wins over earlier namespace
    directories, matching ``PathFinder`` rather than resolving each root in
    isolation.
    """
    own_parent = Path(helper).parent
    parents = [own_parent, *(Path(name) for name in ("scripts", "lib"))]
    locations = list(dict.fromkeys(parents))
    paths = []
    local_prefix = False

    for index, part in enumerate(module.split(".")):
        regular = None
        namespaces = []
        for location in locations:
            package_dir = location / part
            package = package_dir / "__init__.py"
            flat = Path(str(package_dir) + ".py")
            if (REPO_ROOT / package).is_file():
                regular = ("package", package, package_dir)
                break
            if (REPO_ROOT / flat).is_file():
                regular = ("module", flat, None)
                break
            if (REPO_ROOT / package_dir).is_dir():
                namespaces.append(package_dir)

        if regular is not None:
            local_prefix = True
            kind, path, next_location = regular
            paths.append(path.as_posix())
            if kind == "module":
                if index < len(module.split(".")) - 1:
                    if not preserve_broken:
                        return None
                    missing = Path(str(path.with_suffix("")) + "/"
                                   + "/".join(module.split(".")[index + 1:]) + ".py")
                    paths.append(missing.as_posix())
                return paths
            locations = [next_location]
            continue

        if namespaces:
            local_prefix = True
            locations = namespaces
            continue

        if not local_prefix:
            return None
        if not preserve_broken:
            return None
        missing_parent = locations[0] if locations else Path(helper).parent
        missing = missing_parent / part
        suffix = module.split(".")[index + 1:]
        if suffix:
            missing = missing.joinpath(*suffix, "__init__.py")
        else:
            missing = missing.with_suffix(".py")
        paths.append(missing.as_posix())
        return paths
    return paths


def _scan_python_imports(helper):
    """Derive import edges from a ``.py`` entry point via a full AST walk.

    Walks every ``import``/``from`` node (not just module top level), so a lazy
    in-function import (e.g. match-deferrals.py's ``import yaml``) is classified.
    """
    edges = []
    seen = set()
    tree = ast.parse(_read(helper), filename=helper)
    for node in ast.walk(tree):
        candidates = []
        if isinstance(node, ast.Import):
            candidates = [(alias.name, _sibling_module_paths(helper, alias.name))
                          for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                base_paths = _sibling_module_paths(helper, node.module)
                candidates = [(node.module, base_paths)]
                if base_paths is not None:
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        child = _sibling_module_paths(
                            helper, f"{node.module}.{alias.name}", preserve_broken=False
                        )
                        if child:
                            candidates.append((f"{node.module}.{alias.name}", child))
            elif node.level > 0:
                # One dot means the importing helper's directory; every extra
                # dot ascends one package directory. ``from . import sibling``
                # names aliases, while ``from .pkg import x`` names ``pkg``.
                parent = Path(helper).parent
                for _ in range(node.level - 1):
                    parent = parent.parent
                if node.module:
                    base_paths = _module_paths(parent, node.module, preserve_missing=True)
                    candidates = [(node.module, base_paths)]
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        child = _module_paths(parent, f"{node.module}.{alias.name}")
                        if child:
                            candidates.append((f"{node.module}.{alias.name}", child))
                else:
                    candidates = [
                        (alias.name, _module_paths(
                            parent, alias.name, preserve_missing=True
                        ))
                        for alias in node.names
                        if alias.name != "*"
                    ]
        for module, repo_paths in candidates:
            top = module.split(".", 1)[0]
            if repo_paths is not None:
                for repo in repo_paths:
                    if repo in seen:
                        continue
                    seen.add(repo)
                    edges.append(Edge(helper, "import", repo, "repo-owned"))
                continue
            if top in seen:
                continue
            seen.add(top)
            if top == _PYYAML_MODULE:
                edges.append(Edge(helper, "import", top, "external",
                                  "PyYAML (preflight guarantee)"))
            elif top in sys.stdlib_module_names:
                edges.append(Edge(helper, "import", top, "external",
                                  "python3 standard library (preflight guarantee: python3)"))
            else:
                # An unvetted third-party import names no preflight guarantee —
                # auth stays None and the guard rejects it.
                edges.append(Edge(helper, "import", top, "external", None))
    return edges


# Include detection recognizes a `.`/`source` command at any *command
# position* (line start, or after `&&`/`||`/`;`/`{`/`(`), because closure
# helpers source their resolver siblings inside compounds (`[ -f X ] && . X`,
# run-jq.sh) and `||`-guarded includes (efficiency-trace.sh), not only at line
# start. The recognition is performed by `_shell_commands_with_bindings`' head
# extraction (the `head in {".", "source"}` filter in `_scan_shell_sources`),
# which tokenizes real command positions rather than pattern-matching text.
# The sourced-file operand: a path token ending in `.sh`/`.bash`, allowing the
# `$VAR` / `${VAR}` / `$(…)`-substitution chars the include expressions carry. The
# `$(cd … && pwd)` prefix is stripped naturally (parens/quotes are not in the
# class), leaving the helper-dir-relative tail.
_SH_TOKEN = re.compile(r'[\w./${}\[\]\-]*\.(?:sh|bash)')

# The include target is always expressed relative to the helper's own directory
# — `$HERE/x.sh`, `${VAR}/x.sh`, `$_DIR/../lib/x.sh`, or `$(cd … && pwd)/[../]…/x.sh`
# — so the tail after the leading directory expression resolves against the
# helper dir (see the call sites in run-jq/apply-labels/efficiency-trace).


def _source_tail(raw_target, allowed_dir_vars=frozenset()):
    """Extract the helper-dir-relative include tail from a `.`/`source` operand.

    Strips a leading `$VAR` / `${VAR}` directory expression, leaving e.g.
    `../lib/resolve-gh.sh`, `resolve-jq.sh`, or `config-source.sh` — each
    relative to the sourcing helper's directory.
    """
    # The operand comes from `_SH_TOKEN`, whose character class excludes parens
    # and quotes, so any `$(cd … && pwd)` prefix and surrounding quotes are
    # already gone — only a leading `$VAR` / `${VAR}` directory expression can
    # remain. Drop it, then the leading `/`.
    tok = raw_target.strip()
    if tok.startswith("/"):
        return tok
    if tok.startswith("$"):
        m = re.match(r'\$\{?([A-Za-z_]\w*)\}?', tok)
        if m:
            if m.group(1) not in allowed_dir_vars:
                # An unproved prefix (for example $HOME) is not relative to the
                # helper. Keep it absolute-looking so the trust-boundary check
                # rejects it instead of rebasing it into the vendor directory.
                return "/" + tok[m.end():].lstrip("/")
            rest = tok[m.end():]
            if not rest.startswith("/"):
                # No `/` separator after the proved dir var (`${HERE}x.sh`,
                # `$HERE../x.sh`): the runtime expansion CONCATENATES, so a
                # separator-assuming literal tail would not describe it. Empty
                # tail routes the caller to the fail-closed unresolved edge.
                return ""
            tok = rest
    return tok.lstrip("/")


# The exact self-directory anchor shapes a closure helper may use, matched
# structurally against the whitespace-compacted value with QUOTE-TOLERANT
# optional `"` at the structural positions (never blanket quote-stripping,
# which conflates bash `$"…"` locale strings and stray quotes inside `${…%…}`
# with grouping quotes): `$(cd "$(dirname "<self>")" && pwd)` where <self> is
# `$0` / `${0}` / `$BASH_SOURCE` / `${BASH_SOURCE[0]}`, or
# `$(cd "${<self>%/*}" && pwd)` where <self> is `0` / `BASH_SOURCE[0]`
# (the `%/*` alternative accepts only those two spellings). A whitelist — not a substring
# heuristic — so every equivalent parent-anchor spelling (`/..` inside the cd
# argument, a second `cd ..`, a nested double-`dirname`, a `/..` suffix after
# `pwd)`, prefix junk) and every unmodeled quoting form (`$"`, `'`, `\`, a
# quote inside `${…%…}`) simply fails the match and the value stays unproved.
_HELPER_DIR_ANCHOR = re.compile(
    r'\$\(cd "?(?:'
    r'\$\(dirname "?\$(?:0|\{0\}|BASH_SOURCE|\{BASH_SOURCE\[0\]\})"?\)'
    r'|\$\{(?:0|BASH_SOURCE\[0\])%/\*\}'
    r')"? && pwd\)'
)

# An inline include operand: exactly one anchor followed by a plain-path tail
# ending in .sh/.bash — full-matched, so junk between the anchor and the token
# (a second command substitution, say) can never be laundered into a clean edge.
_ANCHORED_OPERAND = re.compile(
    r"(?:" + _HELPER_DIR_ANCHOR.pattern + r")"
    r'(?:/[\w.\-]+)*/[\w.\-]+\.(?:sh|bash)"?'
)


def _compact(value):
    compact = " ".join(value.split())
    if len(compact) >= 2 and compact[0] == '"' and compact[-1] == '"':
        compact = compact[1:-1]
    return compact


def _helper_dir_value(value):
    """Whether a shell value proves the current helper directory.

    Strict structural whitelist (see ``_HELPER_DIR_ANCHOR``): the entire value
    must be exactly one self-directory anchor. Anything else — in particular any
    parent-directory spelling, which resolves to the helper's *parent* and would
    rebase include tails so a repo-root escape could launder into an in-repo
    path, and any unmodeled quoting form — leaves the variable unproved, so its
    include tails stay absolute-looking and the vendor guard rejects the edge
    instead.
    """
    return _HELPER_DIR_ANCHOR.fullmatch(_compact(value)) is not None


def _helper_dir_anchored_operand(operand):
    """Whether an include operand is exactly one anchor + a plain-path tail."""
    return _ANCHORED_OPERAND.fullmatch(_compact(operand)) is not None


def _source_repo_path(helper_dir, tail):
    """Keep absolute source operands absolute so the vendor guard rejects them."""
    return tail if tail.startswith("/") else normpath(f"{helper_dir}/{tail}")


def _scan_shell_sources(helper):
    """Derive source edges from a `.sh` entry point's `.`/`source` includes.

    Fail closed on an include the scan cannot resolve: an operand with no
    ``.sh``/``.bash``-suffixed token, an operand the resolved token does not
    fully account for (interposed substitutions, globs, junk), or a variable
    operand with no tracked binding (including a ``for``-loop variable), emits
    an ``unresolved-source`` edge that ``check_dependencies()`` rejects
    unconditionally — never a silent drop that would let a sourced sibling
    escape the trust closure.

    Known scoping over-approximation: the binding tracker models flat scope, so
    an assignment made only inside a subshell ``(...)`` or pipeline group is
    treated as a visible binding — a scoped assignment may therefore classify a
    source edge the runtime would not source (the runtime include then fails
    loudly on the unset variable; the misattribution is static-side only).
    Further disclosed boundaries of the same static-side-misattribution class:
    the word tokenizer drops ``\\`` (so an escaped ``\\$VAR`` — a literal,
    non-expanding path at runtime — is scanned as if it expanded); a bare
    relative include (``. x.sh``) is classified helper-dir-relative although
    bash resolves it via ``$PATH`` first; and an ``eval``-mediated rebind of a
    dir variable is out of static reach (a var rebound only inside an ``eval``
    string keeps its provedness).
    """
    edges = []
    seen = set()

    def _unresolved(target):
        # An empty/whitespace operand still emits the edge (Edge requires a
        # non-empty target, and a crash here would detonate classify_all()
        # instead of producing the designed violation).
        target = target.strip() or "<empty operand>"
        key = ("unresolved", target)
        if key not in seen:
            seen.add(key)
            # The class is presumptive (the operand could not be resolved at
            # all); the guard rejects the edge before any class-specific check.
            edges.append(Edge(helper, "unresolved-source", target, "repo-owned"))

    helper_dir = str(Path(helper).parent.as_posix())
    code = _strip_shell_structural_data(_strip_line_comments(_read(helper)))
    variable = re.compile(r"^\$\{?([A-Za-z_]\w*)\}?$")
    commands = list(_shell_commands_with_bindings(code))
    # Expansion-timing fail-closed: the shell expands `$HERE` inside a
    # double-quoted ASSIGNMENT immediately, so an operand value captured while
    # the dir var held a non-anchor binding must never be resolved against the
    # var's later anchor binding. The tracker stores bare value strings (no
    # per-assignment state snapshot), so provedness is computed conservatively
    # over every top-level `NAME=value` assignment event in the file (plus
    # poisoning for the for/read/+= rebind channels, which emit none): one
    # non-anchor binding (other than the accepted `$(pwd)` co-binding — the
    # run-jq.sh case-fallback shape, where the runtime miss is loud) leaves the
    # variable unproved and its include tails absolute-looking for the vendor
    # guard to reject.
    # Collect the raw top-level `NAME=value` assignment-event history (not the
    # per-command states, whose replace-on-assignment semantics forget the
    # earlier binding an intermediate capture may have frozen; and never
    # substitution-body events, which are subshell-scoped). Rebind channels
    # that emit no assignment event — a `for` target, a `read` target, a
    # `NAME+=` append — POISON the name so it can never be proved.
    file_wide_bindings = {}
    for _kind, _first, _second in _shell_events(code, include_substitutions=False):
        if _kind == "assignment":
            file_wide_bindings.setdefault(_first, set()).add(_second)
    # Deliberate OVER-poisoning: every name-shaped token to end-of-segment
    # after read/mapfile/readarray/getopts/unset (option arguments included)
    # is poisoned — a false poison is fail-closed, an escaped rebind target is
    # not. This also means a name inside a quoted string on such a line (or
    # anywhere for `for`/`select`/`+=`/`${NAME=…}`) poisons; disclosed here as
    # the accepted direction. Backslash-newline continuations are joined first
    # so a continuation-line target still poisons. A `declare/local/typeset
    # -n` nameref poisons both the ref and its referent. Only `eval`-mediated
    # rebinds remain out of static reach (see the docstring's disclosed
    # boundaries).
    poison_code = code.replace("\\\n", " ")
    for _m in re.finditer(r"\b(?:for|select)[ \t]+([A-Za-z_]\w*)\b", poison_code):
        file_wide_bindings.setdefault(_m.group(1), set()).add("<rebound>")
    for _m in re.finditer(
        r"\b(?:read|mapfile|readarray|getopts|unset)\b([^\n;|&]*)", poison_code
    ):
        for _name in re.findall(r"[A-Za-z_]\w*", _m.group(1)):
            file_wide_bindings.setdefault(_name, set()).add("<rebound>")
    for _m in re.finditer(r'\bprintf[ \t]+-v[ \t]+"?([A-Za-z_]\w*)', poison_code):
        file_wide_bindings.setdefault(_m.group(1), set()).add("<rebound>")
    for _m in re.finditer(r"\b([A-Za-z_]\w*)\+=", poison_code):
        file_wide_bindings.setdefault(_m.group(1), set()).add("<rebound>")
    # ${NAME:=…} / ${NAME=…} assign-default expansions rebind at expansion time.
    for _m in re.finditer(r"\$\{([A-Za-z_]\w*):?=", poison_code):
        file_wide_bindings.setdefault(_m.group(1), set()).add("<rebound>")
    # A nameref makes the referent writable through the ref — poison both.
    for _m in re.finditer(
        r"\b(?:declare|local|typeset)\b[^\n;|&]*-[A-Za-z]*n[A-Za-z]*[ \t]+"
        r'"?([A-Za-z_]\w*)=([A-Za-z_]\w*)', poison_code
    ):
        file_wide_bindings.setdefault(_m.group(1), set()).add("<rebound>")
        file_wide_bindings.setdefault(_m.group(2), set()).add("<rebound>")
    allowed_dir_vars = {
        name
        for name, values in file_wide_bindings.items()
        if (
            values
            and any(_helper_dir_value(value) for value in values)
            and all(
                _helper_dir_value(value) or value.strip() == "$(pwd)"
                for value in values
            )
        )
    }
    for head, args, states in commands:
        if head not in {".", "source"} or not args:
            continue
        operands = []
        bound = variable.fullmatch(args[0])
        if bound:
            for state in states:
                operands.extend(sorted(state.get(bound.group(1), set())))
            if not operands:
                # A variable include whose binding the tracker cannot resolve
                # (e.g. a `for`-loop variable) — fail closed, never drop.
                _unresolved(args[0])
        else:
            operands.append(args[0])
        for operand in operands:
            tok = _SH_TOKEN.search(operand)
            if not tok:
                _unresolved(operand)
                continue
            raw_target = tok.group()
            # Whole-operand accounting: the resolved token must account for the
            # ENTIRE operand — the token alone, or a full anchor + the token as
            # its tail. Unaccounted bytes (an interposed substitution, a glob
            # star, junk between an anchor and a bare filename) fail closed.
            # Accounting is necessary, not sufficient: the tail checks below
            # additionally reject residual `$`/`[`/`]`/`{`/`}` (embedded
            # expansions, globs, braces) and a separator-less var remnant
            # (`${HERE}x.sh`), the known expansion-differing shapes among
            # byte-accounted operands.
            if raw_target == operand:
                pass
            elif (
                operand.startswith("$(")
                and raw_target.startswith("/")
                and operand.endswith(raw_target)
                and _helper_dir_anchored_operand(operand)
            ):
                raw_target = raw_target.lstrip("/")
            else:
                _unresolved(operand)
                continue
            tail = _source_tail(raw_target, allowed_dir_vars)
            # A residual `$` in the tail is an unexpanded runtime substitution
            # (an embedded `${VAR}` past the leading dir var), and `[`/`]`/
            # `{`/`}` are glob/brace metacharacters in an unquoted include —
            # either way the literal tail does NOT describe the runtime
            # expansion; fail closed.
            if (
                not tail
                or not tail.endswith((".sh", ".bash"))
                or any(ch in tail for ch in "$[]{}")
            ):
                _unresolved(operand)
                continue
            repo_rel = _source_repo_path(helper_dir, tail)
            if repo_rel in seen:
                continue
            seen.add(repo_rel)
            edges.append(Edge(helper, "source", repo_rel, "repo-owned"))
    return edges


def _profile_grant_auth(helper):
    """Authorization provenance for a helper's non-preflight child runtime.

    The Bash matcher grants the vendored helper as one command head and does not
    separately match binaries that helper starts. Name every cloud profile whose
    explicit required-head set contains this helper, so the transitive authority
    is auditable rather than being inferred from a generic host-tool allowlist.
    """
    token = VENDOR_PREFIX + helper
    profiles = sorted(
        profile
        for profile, heads in cwc.REQUIRED_HELPER_HEADS.items()
        if token in heads
    )
    if not profiles:
        return None
    grants = ", ".join(f"{profile}=Bash({token}:*)" for profile in profiles)
    return f"explicit profile grant via helper head: {grants}"


def _declared_exec_edges(helper):
    edges = []
    for spec in EXEC_EDGES.get(helper, []):
        if spec.klass == _EXT:
            if spec.target in PREFLIGHT_GUARANTEES:
                auth = f"{spec.target} (preflight guarantee)"
            elif spec.auth_source == _PROFILE_GRANT:
                auth = _profile_grant_auth(helper)
            else:
                auth = None
            edges.append(Edge(helper, "exec", spec.target, "external", auth))
        else:
            edges.append(Edge(helper, "exec", spec.target, "repo-owned"))
    return edges


def classify_all():
    """Full machine-readable dependency classification over the AC1 closure.

    One ``Edge`` per static source/exec/import edge out of every entry point.
    """
    edges = []
    for helper in entry_points():
        if helper.endswith(".py"):
            edges.extend(_scan_python_imports(helper))
        elif helper.endswith(".sh"):
            edges.extend(_scan_shell_sources(helper))
        edges.extend(_declared_exec_edges(helper))
    return edges


def resolves_beneath_vendor(repo_rel):
    """True iff ``repo_rel`` vendors to a path beneath (or equal to) ``.prflow/vendor/prflow/``.

    A source edge written as ``../../scripts/foo`` from a ``scripts/`` helper
    reaches this predicate already helper-relative-normalized as
    ``../scripts/foo``. Vendoring that value normalizes to
    ``.prflow/vendor/scripts/foo`` — outside the vendored tree — and is rejected.
    This is the executable trust boundary the AC5 guard enforces.
    """
    # An absolute target would reset the join (`.prflow/vendor/prflow/` + `/x`
    # normalizes to `.prflow/vendor/prflow/x`, and `REPO_ROOT / "/x"` resets to
    # `/x`), so reject it up front — no legitimate edge is absolute (derived tails
    # are `lstrip("/")`-ed; declared repo-owned targets are repo-relative).
    if (
        repo_rel.startswith("/")
        or "\\" in repo_rel
        or re.match(r"^[A-Za-z]:", repo_rel)
    ):
        return False
    vendored = normpath(VENDOR_PREFIX + repo_rel)
    root = VENDOR_PREFIX.rstrip("/")
    return vendored == root or vendored.startswith(root + "/")


def _shell_substitution_bodies(text):
    """Return executable ``$(...)``/backtick bodies, respecting shell quotes."""
    bodies = []
    index = 0
    quote = None
    while index < len(text):
        char = text[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        if char == "'":
            quote = None if quote == "'" else ("'" if quote is None else quote)
            index += 1
            continue
        if char == '"':
            quote = None if quote == '"' else ('"' if quote is None else quote)
            index += 1
            continue
        if quote != "'" and text.startswith("$((", index):
            # Arithmetic itself is data, but keep scanning its interior for
            # executable command substitutions.
            index += 3
            continue
        if quote != "'" and any(
            text.startswith(opener, index) for opener in ("$(", "<(", ">(")
        ):
            start = index + 2
            cursor = start
            frames = [{"depth": 1, "quote": None}]
            while cursor < len(text) and frames:
                inner = text[cursor]
                frame = frames[-1]
                if inner == "\\" and frame["quote"] != "'":
                    cursor += 2
                    continue
                if inner in ("'", '"'):
                    if frame["quote"] == inner:
                        frame["quote"] = None
                    elif frame["quote"] is None:
                        frame["quote"] = inner
                    cursor += 1
                    continue
                if frame["quote"] != "'" and any(
                    text.startswith(opener, cursor)
                    for opener in ("$(", "<(", ">(")
                ):
                    frames.append({"depth": 1, "quote": None})
                    cursor += 2
                    continue
                if frame["quote"] is None and inner == "(":
                    frame["depth"] += 1
                elif frame["quote"] is None and inner == ")":
                    frame["depth"] -= 1
                    if frame["depth"] == 0:
                        frames.pop()
                cursor += 1
            if not frames:
                bodies.append(text[start:cursor - 1])
                index = cursor
                continue
        if quote != "'" and char == "`":
            cursor = index + 1
            while cursor < len(text):
                if text[cursor] == "\\":
                    cursor += 2
                    continue
                if text[cursor] == "`":
                    bodies.append(text[index + 1:cursor])
                    index = cursor + 1
                    break
                cursor += 1
            else:
                index = cursor
            continue
        index += 1
    return bodies


def _strip_line_comments(source):
    """Drop the `#`-to-EOL portion of each shell line.

    Quote and parameter-expansion tracking preserves ``#`` data such as
    ``"${key#.}"`` while still removing a real line comment. Python evidence is
    AST-derived instead.
    """
    stripped = []
    # Each command-substitution frame has its own quote context. This matters
    # for constructs such as `value="$(awk 'multiline program')"`: quotes inside
    # the substitution do not close the surrounding double-quoted shell word.
    frames = [{"quote": None, "depth": None, "arithmetic": False}]
    parameter_depth = 0
    heredoc_tags = []
    heredoc_buffers = []
    for line in source.splitlines():
        if heredoc_tags:
            tag, quoted = heredoc_tags[0]
            if line.strip() == tag:
                body = "\n".join(heredoc_buffers.pop(0))
                heredoc_tags.pop(0)
                stripped.append(
                    "" if quoted else "\n".join(_shell_substitution_bodies(body))
                )
            else:
                heredoc_buffers[0].append(line)
                stripped.append("")
            continue

        keep = []
        index = 0
        while index < len(line):
            frame = frames[-1]
            char = line[index]
            if char == "\\" and frame["quote"] != "'":
                keep.append(line[index:index + 2])
                index += 2
                continue
            if frame["quote"]:
                if frame["quote"] == '"' and line.startswith("$(", index):
                    opener = "$((" if line.startswith("$((", index) else "$("
                    keep.append(opener)
                    frames.append({
                        "quote": None,
                        "depth": 2 if opener == "$((" else 1,
                        "arithmetic": opener == "$((",
                    })
                    index += len(opener)
                    continue
                keep.append(char)
                if char == frame["quote"]:
                    frame["quote"] = None
                index += 1
                continue
            if char in ("'", '"'):
                frame["quote"] = char
                keep.append(char)
                index += 1
                continue
            if line.startswith("$(", index):
                opener = "$((" if line.startswith("$((", index) else "$("
                keep.append(opener)
                frames.append({
                    "quote": None,
                    "depth": 2 if opener == "$((" else 1,
                    "arithmetic": opener == "$((",
                })
                index += len(opener)
                continue
            if line.startswith("((", index):
                keep.append("((")
                frames.append({"quote": None, "depth": 2, "arithmetic": True})
                index += 2
                continue
            if frame["depth"] is not None and char in "()":
                keep.append(char)
                frame["depth"] += 1 if char == "(" else -1
                if frame["depth"] == 0:
                    frames.pop()
                index += 1
                continue
            if line.startswith("${", index):
                parameter_depth += 1
                keep.append("${")
                index += 2
                continue
            if char == "}" and parameter_depth:
                parameter_depth -= 1
                keep.append(char)
                index += 1
                continue
            if char == "#" and not parameter_depth and (
                index == 0
                or line[index - 1].isspace()
                or line[index - 1] in ";|&(){}"
            ):
                break
            if (
                not parameter_depth
                and not frame["arithmetic"]
                and line.startswith("<<", index)
                and (index == 0 or line[index - 1] != "<")
            ):
                heredoc = re.match(
                    r"<<-?(?!<)[ \t]*(?P<word>[^\s;&|()]+)", line[index:]
                )
                if heredoc:
                    word = heredoc.group("word")
                    tag = re.sub(r"[\"']", "", re.sub(r"\\(.)", r"\1", word))
                    heredoc_tags.append((tag, bool(re.search(r"[\\\"']", word))))
                    heredoc_buffers.append([])
            keep.append(char)
            index += 1
        stripped.append("".join(keep))
    return "\n".join(stripped)


def _strip_shell_structural_data(code):
    """Mask array values and case patterns while retaining executable bodies."""
    def substitutions(line):
        # Data constructs do not execute their words, but command substitutions
        # (including nested/backtick forms) still execute.
        return "\n".join(_shell_substitution_bodies(line))

    def mask_arithmetic(line):
        def preserve_nested(match):
            nested = substitutions(match.group())
            return f"\n{nested}\n" if nested else ""

        line = re.sub(r"\$\(\(.*?\)\)", preserve_nested, line)
        return re.sub(r"(?<!\$)\(\(.*?\)\)", preserve_nested, line)

    def mask_multiline_arithmetic(text):
        """Mask balanced arithmetic commands/expansions that span lines."""
        output = []
        index = 0
        quote = None
        while index < len(text):
            char = text[index]
            if char == "\\" and quote != "'":
                output.append(text[index:index + 2])
                index += 2
                continue
            if char in ("'", '"'):
                if quote == char:
                    quote = None
                elif quote is None:
                    quote = char
                output.append(char)
                index += 1
                continue
            opener = None
            if quote != "'" and text.startswith("$((", index):
                opener = 3
            elif quote is None and text.startswith("((", index):
                opener = 2
            if opener is None:
                output.append(char)
                index += 1
                continue
            cursor = index + opener
            depth = 2
            inner_quote = None
            while cursor < len(text) and depth:
                inner = text[cursor]
                if inner == "\\" and inner_quote != "'":
                    cursor += 2
                    continue
                if inner in ("'", '"'):
                    if inner_quote == inner:
                        inner_quote = None
                    elif inner_quote is None:
                        inner_quote = inner
                    cursor += 1
                    continue
                if inner_quote is None and inner == "(":
                    depth += 1
                elif inner_quote is None and inner == ")":
                    depth -= 1
                cursor += 1
            if depth:
                output.append(text[index:])
                break
            executable = substitutions(text[index:cursor])
            output.append(f"\n{executable}\n" if executable else "")
            index = cursor
        return "".join(output)

    def pattern_end(line):
        """Index after a case-pattern `)`, ignoring command substitutions."""
        depth = 0
        index = 0
        quote = None
        while index < len(line):
            if line[index] == "\\" and quote != "'":
                index += 2
                continue
            if line[index] in ("'", '"'):
                if quote == line[index]:
                    quote = None
                elif quote is None:
                    quote = line[index]
                index += 1
                continue
            if quote is not None:
                index += 1
                continue
            if line.startswith("$(", index):
                depth += 1
                index += 2
                continue
            if line[index] == "(" and depth:
                depth += 1
            elif line[index] == ")":
                if depth:
                    depth -= 1
                else:
                    return index + 1
            index += 1
        return None

    array_start = re.compile(
        r"(?:(?:declare|local|readonly|typeset)(?:\s+-[A-Za-z]+)*\s+)?"
        r"[A-Za-z_]\w*\s*\+?=\s*\("
    )

    def expose_inline_arrays(line):
        """Put command-position array assignments at a physical line start."""
        output = []
        index = 0
        quote = None
        controls = re.compile(r"(?:then|do|else|elif)\b")

        def array_follows(cursor):
            cursor += len(line[cursor:]) - len(line[cursor:].lstrip())
            return array_start.match(line, cursor) is not None

        while index < len(line):
            char = line[index]
            if char == "\\" and quote != "'":
                output.append(line[index:index + 2])
                index += 2
                continue
            if quote:
                output.append(char)
                if char == quote:
                    quote = None
                index += 1
                continue
            if char in ("'", '"'):
                quote = char
                output.append(char)
                index += 1
                continue
            if line.startswith("${", index) or line.startswith("$(", index):
                opener = "${" if line.startswith("${", index) else "$("
                closer = "}" if opener == "${" else ")"
                depth = 1
                cursor = index + 2
                inner_quote = None
                while cursor < len(line) and depth:
                    if line[cursor] == "\\" and inner_quote != "'":
                        cursor += 2
                        continue
                    if line[cursor] in ("'", '"'):
                        if inner_quote == line[cursor]:
                            inner_quote = None
                        elif inner_quote is None:
                            inner_quote = line[cursor]
                        cursor += 1
                        continue
                    if inner_quote is None and line.startswith(opener, cursor):
                        depth += 1
                        cursor += 2
                        continue
                    if inner_quote is None and line[cursor] == closer:
                        depth -= 1
                    cursor += 1
                output.append(line[index:cursor])
                index = cursor
                continue
            if char in "{;" and not line.startswith(";;", index):
                output.append(char)
                if array_follows(index + 1):
                    output.append("\n")
                index += 1
                continue
            control = controls.match(line, index)
            if control and (index == 0 or not (line[index - 1].isalnum()
                                               or line[index - 1] == "_")):
                output.append(control.group())
                if array_follows(control.end()):
                    output.append("\n")
                index = control.end()
                continue
            output.append(char)
            index += 1
        return "".join(output)

    def active_lines(text):
        """Whether each physical line starts in executable shell syntax."""
        frames = [{"quote": None, "depth": None}]
        active = []
        at_line_start = True
        index = 0
        while index < len(text):
            if at_line_start:
                active.append(frames[-1]["quote"] is None)
                at_line_start = False
            frame = frames[-1]
            char = text[index]
            if char == "\n":
                at_line_start = True
                index += 1
                continue
            if char == "\\" and frame["quote"] != "'":
                if index + 1 < len(text) and text[index + 1] == "\n":
                    at_line_start = True
                index += 2
                continue
            if frame["quote"]:
                if frame["quote"] == '"' and text.startswith("$(", index):
                    frames.append({"quote": None, "depth": 1})
                    index += 2
                    continue
                if char == frame["quote"]:
                    frame["quote"] = None
                index += 1
                continue
            if char in ("'", '"'):
                frame["quote"] = char
                index += 1
                continue
            if text.startswith("$(", index):
                frames.append({"quote": None, "depth": 1})
                index += 2
                continue
            if frame["depth"] is not None:
                if char == "(":
                    frame["depth"] += 1
                elif char == ")":
                    frame["depth"] -= 1
                    if frame["depth"] == 0:
                        frames.pop()
                index += 1
                continue
            index += 1
        if at_line_start and (not text or text.endswith("\n")):
            active.append(frames[-1]["quote"] is None)
        return active

    code = mask_multiline_arithmetic(code)

    # Make inline structural constructs visible to the line state machine, but
    # never reinterpret embedded-language text inside a multiline quoted word.
    expanded = []
    activity = active_lines(code)
    for line, is_active in zip(code.splitlines(), activity):
        if is_active:
            line = expose_inline_arrays(line)
            line = re.sub(
                r";(?=\s*(?:(?:declare|local|readonly|typeset)"
                r"(?:\s+-[A-Za-z]+)*\s+)?[A-Za-z_]\w*\s*\+?=\s*\()",
                ";\n",
                line,
            )
            line = re.sub(r";(?=\s*case\b)", ";\n", line)
        expanded.extend((part, is_active) for part in line.split("\n"))

    output = []
    array_depth = 0
    in_case = False
    arm_expected = False
    for line, is_active in expanded:
        if not is_active:
            output.append(line)
            continue
        if array_depth:
            array_depth += line.count("(") - line.count(")")
            array_depth = max(array_depth, 0)
            output.append(substitutions(line))
            continue

        array = re.match(
            r"^\s*(?:(?:declare|local|readonly|typeset)(?:\s+-[A-Za-z]+)*\s+)?"
            r"[A-Za-z_]\w*\s*\+?=\s*\(",
            line,
        )
        if array:
            array_depth = max(line.count("(") - line.count(")"), 0)
            output.append(substitutions(line[array.end():]))
            continue

        # Arithmetic expansions are data calculations, not command positions.
        line = mask_arithmetic(line)

        if not in_case:
            case = re.match(r"^\s*case\s+(.*?)\s+in(?:\s+(.*))?$", line)
            if not case:
                output.append(line)
                continue
            # Preserve command substitutions in the selector; its other tokens
            # and the arm patterns following `in` are data.
            output.append(substitutions(case.group(1)))
            output.append("if")
            line = case.group(2) or ""
            in_case = True
            arm_expected = True

        while in_case:
            line = line.lstrip()
            if re.match(r"^esac\b", line):
                output.append("fi")
                in_case = False
                arm_expected = False
                break
            if arm_expected:
                end = pattern_end(line)
                if end is None:
                    output.append(substitutions(line))
                    break
                output.append(substitutions(line[:end - 1]))
                line = line[end:]
                arm_expected = False

            terminator = re.search(r";;&|;&|;;", line)
            end_case = re.search(r"\besac\b", line)
            if end_case and (not terminator or end_case.start() < terminator.start()):
                output.append(line[:end_case.start()])
                output.append("fi")
                in_case = False
                arm_expected = False
                break
            if not terminator:
                output.append(line)
                break
            output.append(line[:terminator.start()])
            output.append("elif")
            line = line[terminator.end():]
            arm_expected = True
    return "\n".join(output)


def _shell_tokens(code):
    """Quote-aware shell words/operators for command-head analysis."""
    tokens = []
    word = []
    protected = False
    index = 0
    quote = None

    def finish_word():
        nonlocal protected
        if word:
            tokens.append(("word", "".join(word), protected))
            word.clear()
            protected = False

    while index < len(code):
        char = code[index]
        if char == "\\" and quote != "'":
            protected = True
            if index + 1 < len(code):
                word.append(code[index + 1])
            index += 2
            continue
        if quote != "'" and code.startswith("${", index):
            start = index
            depth = 1
            index += 2
            while index < len(code) and depth:
                if code[index] == "\\":
                    index += 2
                    continue
                if code.startswith("${", index):
                    depth += 1
                    index += 2
                    continue
                if code[index] == "}":
                    depth -= 1
                index += 1
            word.append(code[start:index])
            continue
        if quote != "'" and (code.startswith("$((", index) or code.startswith("$(", index)):
            opener = "$((" if code.startswith("$((", index) else "$("
            start = index
            depth = 2 if opener == "$((" else 1
            inner_quote = None
            index += len(opener)
            while index < len(code) and depth:
                if code[index] == "\\" and inner_quote != "'":
                    index += 2
                    continue
                if code[index] in ("'", '"'):
                    if inner_quote == code[index]:
                        inner_quote = None
                    elif inner_quote is None:
                        inner_quote = code[index]
                    index += 1
                    continue
                if inner_quote is None and code[index] == "(":
                    depth += 1
                elif inner_quote is None and code[index] == ")":
                    depth -= 1
                index += 1
            word.append(code[start:index])
            continue
        if quote != "'" and char == "`":
            start = index
            index += 1
            while index < len(code):
                if code[index] == "\\":
                    index += 2
                    continue
                if code[index] == "`":
                    index += 1
                    break
                index += 1
            word.append(code[start:index])
            continue
        if quote:
            if char == quote:
                quote = None
            else:
                word.append(char)
            index += 1
            continue
        if char in ("'", '"'):
            protected = True
            quote = char
            index += 1
            continue
        if char.isspace():
            finish_word()
            if char == "\n":
                tokens.append(("op", "\n", False))
            index += 1
            continue
        operator = next(
            (op for op in (";;&", "&&", "||", ";;", ";&") if code.startswith(op, index)),
            None,
        )
        if operator is not None:
            finish_word()
            tokens.append(("op", operator, False))
            index += len(operator)
            continue
        if char in ";|&(){}":
            finish_word()
            tokens.append(("op", char, False))
            index += 1
            continue
        word.append(char)
        index += 1
    finish_word()
    return tokens


def _shell_events(code, *, include_substitutions=True):
    """Return assignment/control/command events from preprocessed shell code.

    With ``include_substitutions=False``, events inside ``$( )`` bodies are
    omitted — a binding made only inside a substitution is subshell-scoped and
    must never prove a parent-scope variable (the provedness consumer's mode).
    """
    events = []
    segment = []
    controls = {"if", "then", "elif", "else", "fi", "while", "until",
                "do", "done"}
    wrappers = {"!", "command", "builtin", "exec"}
    assignment = re.compile(r"^([A-Za-z_]\w*)=(.*)$", re.DOTALL)

    def emit():
        if not segment:
            return
        words = list(segment)
        segment.clear()
        while words and not words[0][1] and words[0][0] in controls:
            events.append(("control", words.pop(0)[0], None))
        declarations = False
        if (
            words
            and not words[0][1]
            and words[0][0] in {"export", "readonly", "local", "declare", "typeset"}
        ):
            declarations = True
            words.pop(0)
            while words and words[0][0].startswith("-"):
                words.pop(0)
        assignments = []
        while words:
            match = assignment.match(words[0][0])
            if not match:
                break
            assignments.append((match.group(1), match.group(2)))
            words.pop(0)
        if declarations or not words:
            for name, value in assignments:
                events.append(("assignment", name, value))
        if not words:
            return
        while words and not words[0][1] and words[0][0] in wrappers:
            words.pop(0)
        redirection = re.compile(r"^\d*(?:<<<|<<|>>|<>|>&|<&|>|<)(.*)$", re.DOTALL)
        while words:
            redirect = redirection.fullmatch(words[0][0])
            if not redirect:
                break
            words.pop(0)
            if not redirect.group(1) and words:
                words.pop(0)
        if words:
            events.append(("command", words[0][0], tuple(word for word, _ in words[1:])))

    for kind, token, protected in _shell_tokens(code):
        if kind == "word":
            segment.append((token, protected))
        else:
            emit()
    emit()
    if include_substitutions:
        for body in _shell_substitution_bodies(code):
            events.extend(_shell_events(body))
    return events


def _shell_commands_with_bindings(code):
    """Yield command records with possible variable bindings at that point."""
    state = {}
    branches = []
    loops = []
    commands = []

    def copy_state(value):
        return {name: set(values) for name, values in value.items()}

    def merge_state(*values):
        merged = {}
        for value in values:
            for name, choices in value.items():
                merged.setdefault(name, set()).update(choices)
        return merged

    for kind, first, second in _shell_events(code):
        if kind == "control":
            if first == "if":
                branches.append({
                    "before": copy_state(state),
                    "completed": [],
                    "else": False,
                })
            elif first in {"else", "elif"} and branches:
                branch = branches[-1]
                branch["completed"].append(copy_state(state))
                branch["else"] = first == "else"
                state = copy_state(branch["before"])
            elif first == "fi" and branches:
                branch = branches.pop()
                alternatives = [*branch["completed"], copy_state(state)]
                if not branch["else"]:
                    alternatives.append(branch["before"])
                state = merge_state(*alternatives)
            elif first in {"while", "until"}:
                loops.append(copy_state(state))
            elif first == "done" and loops:
                state = merge_state(loops.pop(), state)
            continue
        if kind == "assignment":
            state[first] = {second}
            continue
        commands.append((first, second, [copy_state(state)]))
    return commands


def _external_evidence_tokens(bin_name):
    """Whole-word tokens that count as a live invocation of an external binary.

    The closure helpers invoke resolvable externals through the documented
    `DEVFLOW_<TOOL>` override (`"${DEVFLOW_GH:=…}"`, `os.environ.get("DEVFLOW_GH")`)
    as well as the bare name / `.exe`, so any of the three counts as evidence.
    """
    return {bin_name, bin_name + ".exe", "DEVFLOW_" + bin_name.upper()}


_PYTHON_SUBPROCESS_CALLS = frozenset({"run", "Popen", "check_call", "check_output"})


def _python_command_evidence(source, filename):
    """String evidence reachable from Python subprocess command heads.

    The small data-flow pass snapshots bindings at each call, unions live
    control-flow branches, and resolves lexical parents after their bodies have
    been analyzed.  Parameter *names* and unrelated expression operands never
    count as executable evidence.
    """
    tree = ast.parse(source, filename=filename)
    evidence = set()
    scopes = []

    def assigned_names(node):
        names = set()

        class LocalNames(ast.NodeVisitor):
            def visit_FunctionDef(self, child):  # noqa: N802
                return

            visit_AsyncFunctionDef = visit_FunctionDef
            visit_Lambda = visit_FunctionDef
            visit_ClassDef = visit_FunctionDef
            visit_ListComp = visit_FunctionDef
            visit_SetComp = visit_FunctionDef
            visit_DictComp = visit_FunctionDef
            visit_GeneratorExp = visit_FunctionDef

            def visit_Name(self, child):  # noqa: N802
                if isinstance(child.ctx, ast.Store):
                    names.add(child.id)

        visitor = LocalNames()
        body = node.body if isinstance(node.body, list) else [node.body]
        for statement in body:
            visitor.visit(statement)
        return names

    def add_scope(node, parent):
        parameters = set()
        body = node.body if isinstance(node, ast.Module) else node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            parameters = {
                argument.arg
                for argument in (
                    *node.args.posonlyargs,
                    *node.args.args,
                    *node.args.kwonlyargs,
                )
            }
        scope = {
            "node": node,
            "parent": parent,
            "parameters": parameters,
            "locals": assigned_names(node) | parameters,
            "calls": [],
            "call_events": [],
            "entry_states": [],
            "final": {},
            "children": [],
        }
        scopes.append(scope)
        if parent is not None:
            parent["children"].append(scope)

        class Discover(ast.NodeVisitor):
            def visit_FunctionDef(self, child):  # noqa: N802
                if child is node:
                    self.generic_visit(child)
                else:
                    add_scope(
                        child,
                        parent if isinstance(node, ast.ClassDef) else scope,
                    )

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Lambda(self, child):  # noqa: N802
                if child is node:
                    self.generic_visit(child)
                else:
                    add_scope(child, scope)

            def visit_ClassDef(self, child):  # noqa: N802
                if child is node:
                    self.generic_visit(child)
                else:
                    add_scope(child, scope)

        discover = Discover()
        if isinstance(body, list):
            for statement in body:
                discover.visit(statement)
        else:
            discover.visit(body)
        return scope

    module_scope = add_scope(tree, None)

    def snapshot(state):
        return {name: list(values) for name, values in state.items()}

    def merge_states(*states):
        merged = {}
        for state in states:
            for name, values in state.items():
                bucket = merged.setdefault(name, [])
                for value in values:
                    if all(value is not prior for prior in bucket):
                        bucket.append(value)
        return merged

    def constant_truth(node):
        try:
            return bool(ast.literal_eval(node))
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            return None

    def bind_target(state, target, binding):
        if isinstance(target, (ast.Tuple, ast.List)):
            for child in target.elts:
                bind_target(state, child, None)
        elif isinstance(target, ast.Name):
            state[target.id] = [] if binding is None else [binding]

    def bind_assignment(state, target, value, scope):
        if (
            isinstance(target, (ast.Tuple, ast.List))
            and isinstance(value, (ast.Tuple, ast.List))
            and len(target.elts) == len(value.elts)
        ):
            for target_part, value_part in zip(target.elts, value.elts):
                bind_assignment(state, target_part, value_part, scope)
            return
        bind_target(state, target, (value, snapshot(state), scope))

    subprocess_module_marker = "__devflow_subprocess_module__"
    os_module_marker = "__devflow_os_module__"

    def subprocess_function_marker(name):
        return f"__devflow_subprocess_function__:{name}"

    def marker_bound(scope, state, name, marker):
        if name in scope["locals"]:
            values = state.get(name, [])
        elif scope["parent"] is not None:
            parent_states = scope["entry_states"] or [scope["parent"]["final"]]
            return any(
                marker_bound(scope["parent"], parent_state, name, marker)
                for parent_state in parent_states
            )
        else:
            return False
        return any(
            isinstance(value, ast.Constant) and value.value == marker
            for value, _bound_state, _bound_scope in values
        )

    def record_calls(node, state, scope):
        def callable_names(name, current_state, resolving=frozenset()):
            if name in resolving:
                return set()
            names = {name}
            for binding, bound_state, _bound_scope in current_state.get(name, []):
                if isinstance(binding, ast.Name):
                    names |= callable_names(
                        binding.id, bound_state, resolving | {name}
                    )
            return names

        class Calls(ast.NodeVisitor):
            def visit_FunctionDef(self, child):  # noqa: N802
                return

            visit_AsyncFunctionDef = visit_FunctionDef
            visit_Lambda = visit_FunctionDef

            def visit_ClassDef(self, child):  # noqa: N802
                return

            def visit_Call(self, call):  # noqa: N802
                scope["call_events"].append((call, snapshot(state)))
                if isinstance(call.func, ast.Name):
                    possible_names = callable_names(call.func.id, state)
                    for child_scope in scope["children"]:
                        child_node = child_scope["node"]
                        if (
                            isinstance(
                                child_node,
                                (ast.FunctionDef, ast.AsyncFunctionDef),
                            )
                            and child_node.name in possible_names
                        ):
                            child_scope["entry_states"].append(snapshot(state))
                command = call.args[0] if call.args else next(
                    (kw.value for kw in call.keywords if kw.arg == "args"), None
                )
                executable = next(
                    (kw.value for kw in call.keywords if kw.arg == "executable"), None
                )
                if executable is not None and not (
                    isinstance(executable, ast.Constant) and executable.value is None
                ):
                    command = executable
                if command is not None:
                    is_module_call = (
                        isinstance(call.func, ast.Attribute)
                        and call.func.attr in _PYTHON_SUBPROCESS_CALLS
                        and isinstance(call.func.value, ast.Name)
                        and marker_bound(
                            scope,
                            state,
                            call.func.value.id,
                            subprocess_module_marker,
                        )
                    )
                    is_imported_call = (
                        isinstance(call.func, ast.Name)
                        and marker_bound(
                            scope,
                            state,
                            call.func.id,
                            subprocess_function_marker(call.func.id),
                        )
                    )
                    if is_module_call or is_imported_call:
                        scope["calls"].append((command, snapshot(state)))
                self.generic_visit(call)

        Calls().visit(node)

    def apply_named_expressions(node, state, scope):
        if isinstance(node, ast.NamedExpr):
            apply_named_expressions(node.value, state, scope)
            bind_assignment(state, node.target, node.value, scope)
            return
        if isinstance(node, ast.BoolOp):
            for value in node.values:
                apply_named_expressions(value, state, scope)
                truth = constant_truth(value)
                if (
                    isinstance(node.op, ast.And) and truth is False
                    or isinstance(node.op, ast.Or) and truth is True
                ):
                    break
            return
        if isinstance(node, ast.IfExp):
            apply_named_expressions(node.test, state, scope)
            truth = constant_truth(node.test)
            if truth is not None:
                apply_named_expressions(
                    node.body if truth else node.orelse, state, scope
                )
            else:
                body_state = snapshot(state)
                else_state = snapshot(state)
                apply_named_expressions(node.body, body_state, scope)
                apply_named_expressions(node.orelse, else_state, scope)
                state.clear()
                state.update(merge_states(body_state, else_state))
            return
        if isinstance(node, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef)):
            return
        for child in ast.iter_child_nodes(node):
            apply_named_expressions(child, state, scope)

    def process_block(statements, incoming, scope):
        state = snapshot(incoming)
        for statement in statements:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                for expression_node in (
                    *getattr(statement, "decorator_list", []),
                    *getattr(getattr(statement, "args", None), "defaults", []),
                    *getattr(getattr(statement, "args", None), "kw_defaults", []),
                    *getattr(statement, "bases", []),
                    *(keyword.value for keyword in getattr(statement, "keywords", [])),
                ):
                    if expression_node is not None:
                        record_calls(expression_node, state, scope)
                        apply_named_expressions(expression_node, state, scope)
                continue
            if isinstance(statement, (ast.Import, ast.ImportFrom)):
                aliases = statement.names
                for alias in aliases:
                    bound_name = alias.asname or alias.name.split(".", 1)[0]
                    scope["locals"].add(bound_name)
                    marker = None
                    if isinstance(statement, ast.Import) and alias.name == "subprocess":
                        marker = subprocess_module_marker
                    elif isinstance(statement, ast.Import) and alias.name == "os":
                        marker = os_module_marker
                    elif (
                        isinstance(statement, ast.ImportFrom)
                        and statement.module == "subprocess"
                        and alias.name in _PYTHON_SUBPROCESS_CALLS
                    ):
                        marker = subprocess_function_marker(bound_name)
                    binding = None
                    if marker is not None:
                        binding = (
                            ast.Constant(marker),
                            snapshot(state),
                            scope,
                        )
                    bind_target(state, ast.Name(id=bound_name), binding)
                continue
            if isinstance(statement, ast.Assign):
                record_calls(statement.value, state, scope)
                apply_named_expressions(statement.value, state, scope)
                for target_node in statement.targets:
                    bind_assignment(state, target_node, statement.value, scope)
                continue
            if isinstance(statement, ast.AnnAssign):
                if statement.value is not None:
                    record_calls(statement.value, state, scope)
                    bind_target(
                        state,
                        statement.target,
                        (statement.value, snapshot(state), scope),
                    )
                continue
            if isinstance(statement, ast.AugAssign):
                record_calls(statement.value, state, scope)
                bind_target(state, statement.target, None)
                continue
            if isinstance(statement, ast.Delete):
                for target_node in statement.targets:
                    bind_target(state, target_node, None)
                continue
            if isinstance(statement, ast.If):
                record_calls(statement.test, state, scope)
                apply_named_expressions(statement.test, state, scope)
                truth = constant_truth(statement.test)
                if truth is True:
                    state = process_block(statement.body, state, scope)
                elif truth is False:
                    state = process_block(statement.orelse, state, scope)
                else:
                    state = merge_states(
                        process_block(statement.body, state, scope),
                        process_block(statement.orelse, state, scope),
                    )
                continue
            if isinstance(statement, (ast.For, ast.AsyncFor)):
                record_calls(statement.iter, state, scope)
                body_state = snapshot(state)
                bind_target(body_state, statement.target, None)
                body_state = process_block(statement.body, body_state, scope)
                state = process_block(
                    statement.orelse, merge_states(state, body_state), scope
                )
                continue
            if isinstance(statement, ast.While):
                record_calls(statement.test, state, scope)
                truth = constant_truth(statement.test)
                if truth is False:
                    state = process_block(statement.orelse, state, scope)
                else:
                    body_state = process_block(statement.body, state, scope)
                    state = process_block(
                        statement.orelse, merge_states(state, body_state), scope
                    )
                continue
            if isinstance(statement, (ast.Try, ast.TryStar)):
                body_state = process_block(statement.body, state, scope)
                normal_state = process_block(statement.orelse, body_state, scope)
                branches = [normal_state]
                for handler in statement.handlers:
                    handler_state = merge_states(state, body_state)
                    if handler.name:
                        handler_state[handler.name] = []
                    branches.append(process_block(handler.body, handler_state, scope))
                state = process_block(
                    statement.finalbody,
                    merge_states(*branches),
                    scope,
                )
                continue
            if isinstance(statement, (ast.With, ast.AsyncWith)):
                for item in statement.items:
                    record_calls(item.context_expr, state, scope)
                    if item.optional_vars is not None:
                        bind_target(state, item.optional_vars, None)
                state = process_block(statement.body, state, scope)
                continue
            if isinstance(statement, ast.Match):
                record_calls(statement.subject, state, scope)
                exhaustive = any(
                    isinstance(case.pattern, ast.MatchAs)
                    and case.pattern.pattern is None
                    and case.guard is None
                    for case in statement.cases
                )
                branches = [] if exhaustive else [state]
                for case in statement.cases:
                    case_state = snapshot(state)
                    for pattern_node in ast.walk(case.pattern):
                        if isinstance(pattern_node, ast.MatchAs) and pattern_node.name:
                            case_state[pattern_node.name] = []
                        elif isinstance(pattern_node, ast.MatchStar) and pattern_node.name:
                            case_state[pattern_node.name] = []
                    if case.guard is not None:
                        record_calls(case.guard, case_state, scope)
                    branches.append(process_block(case.body, case_state, scope))
                state = merge_states(*branches)
                continue
            record_calls(statement, state, scope)
            apply_named_expressions(statement, state, scope)
        return state

    def analyze(scope):
        node = scope["node"]
        if isinstance(node, ast.Lambda):
            record_calls(node.body, {}, scope)
            scope["final"] = {}
        else:
            scope["final"] = process_block(node.body, {}, scope)
        for child in scope["children"]:
            analyze(child)

    analyze(module_scope)

    method_owners = {
        id(statement): class_node.name
        for class_node in ast.walk(tree)
        if isinstance(class_node, ast.ClassDef)
        for statement in class_node.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    valid_wrappers = {}
    for scope in scopes:
        node = scope["node"]
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        key = (
            ("attribute", method_owners[id(node)], node.name)
            if id(node) in method_owners
            else ("name", node.name)
        )
        for head, _state in scope["calls"]:
            if isinstance(head, ast.Name) and head.id in scope["parameters"]:
                valid_wrappers.setdefault(key, []).append((scope, head.id))
    class_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }

    def receiver_classes(node, state, resolving=frozenset()):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in class_names
        ):
            return {node.func.id}
        if isinstance(node, ast.Name) and node.id not in resolving:
            classes = set()
            for value, bound_state, _bound_scope in state.get(node.id, []):
                classes |= receiver_classes(
                    value, bound_state, resolving | {node.id}
                )
            return classes
        return set()

    for scope in scopes:
        for call, state in scope["call_events"]:
            if isinstance(call.func, ast.Name):
                keys = [("name", call.func.id)]
            elif isinstance(call.func, ast.Attribute):
                keys = [
                    ("attribute", owner, call.func.attr)
                    for owner in receiver_classes(call.func.value, state)
                ]
            else:
                continue
            candidates = [
                candidate
                for key in keys
                for candidate in valid_wrappers.get(key, [])
            ]
            for wrapper_scope, sink_parameter in candidates:
                wrapper = wrapper_scope["node"]
                positional = [
                    argument.arg
                    for argument in (*wrapper.args.posonlyargs, *wrapper.args.args)
                ]
                argument = None
                if sink_parameter in positional:
                    index = positional.index(sink_parameter)
                    if keys[0][0] == "attribute" and positional[:1] in (["self"], ["cls"]):
                        index -= 1
                    if 0 <= index < len(call.args):
                        argument = call.args[index]
                if argument is None:
                    argument = next(
                        (kw.value for kw in call.keywords if kw.arg == sink_parameter),
                        None,
                    )
                if argument is not None:
                    scope["calls"].append((argument, state))

    def lookup(scope, state, name):
        if name in scope["locals"]:
            return state.get(name, [])
        parent = scope["parent"]
        if parent is None:
            return []
        parent_states = scope["entry_states"] or [parent["final"]]
        values = []
        for parent_state in parent_states:
            for value in lookup(parent, parent_state, name):
                if all(value is not prior for prior in values):
                    values.append(value)
        return values

    def expression(node, scope, state, resolving=frozenset()):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            evidence.add(node.value)
            evidence.add(Path(node.value).name)
            return
        if isinstance(node, ast.Name):
            key = (id(scope), node.id)
            if key in resolving:
                return
            for value, bound_state, bound_scope in lookup(scope, state, node.id):
                expression(value, bound_scope, bound_state, resolving | {key})
            return
        if isinstance(node, (ast.List, ast.Tuple)):
            if node.elts:
                expression(node.elts[0], scope, state, resolving)
            return
        if isinstance(node, ast.BoolOp):
            for index, value in enumerate(node.values):
                truth = constant_truth(value)
                is_last = index == len(node.values) - 1
                if isinstance(node.op, ast.And):
                    if truth is False or is_last:
                        expression(value, scope, state, resolving)
                        if truth is False:
                            return
                    if truth is None:
                        expression(value, scope, state, resolving)
                else:
                    if truth is True or is_last:
                        expression(value, scope, state, resolving)
                        if truth is True:
                            return
                    if truth is None:
                        expression(value, scope, state, resolving)
            return
        if isinstance(node, ast.IfExp):
            truth = constant_truth(node.test)
            if truth is True:
                expression(node.body, scope, state, resolving)
            elif truth is False:
                expression(node.orelse, scope, state, resolving)
            else:
                expression(node.body, scope, state, resolving)
                expression(node.orelse, scope, state, resolving)
            return
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            # For pathlib composition, the rightmost segment is the executable
            # basename; parent directory segments are never command evidence.
            expression(node.right, scope, state, resolving)
            return
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "str" and node.args:
                expression(node.args[0], scope, state, resolving)
            elif isinstance(node.func, ast.Name) and node.func.id == "Path" and node.args:
                expression(node.args[-1], scope, state, resolving)
            elif (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "environ"
                and isinstance(node.func.value.value, ast.Name)
                and marker_bound(
                    scope,
                    state,
                    node.func.value.value.id,
                    os_module_marker,
                )
            ):
                if (
                    node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                    and node.args[0].value.startswith("DEVFLOW_")
                ):
                    expression(node.args[0], scope, state, resolving)
                if len(node.args) > 1:
                    expression(node.args[1], scope, state, resolving)

    for scope in scopes:
        for head, state in scope["calls"]:
            expression(head, scope, state)
    return evidence


def _shell_variable_form(name):
    """A parameter form whose value is the named command, never an alternate."""
    escaped = re.escape(name)
    return r'(?:\$\{' + escaped + r'(?:(?::?[-=?])[^}]*)?\}|\$' + escaped + r')'


def _shell_external_present(source, target):
    code = _strip_shell_structural_data(_strip_line_comments(source))
    bare = {target, target + ".exe"}
    override = "DEVFLOW_" + target.upper()
    variable = re.compile(r"^" + _shell_variable_form(override) + r"$")
    return any(
        head in bare or variable.fullmatch(head)
        for head, _args, _states in _shell_commands_with_bindings(code)
    )


def _shell_repo_exec_present(source, target):
    """Recognize a repo script on a shell command line or via an executed var."""
    code = _strip_shell_structural_data(_strip_line_comments(source))
    basename = Path(target).name
    python_variable = re.compile(
        r"^" + _shell_variable_form("DEVFLOW_PYTHON3") + r"$"
    )
    variable_head = re.compile(r"^\$\{?([A-Za-z_]\w*)\}?$")
    fallback_head = re.compile(
        r"^\$\{([A-Za-z_]\w*)(?::?[-=])([^}]*)\}$", re.DOTALL
    )

    def target_value(value):
        return re.search(r'(?:^|/)' + re.escape(basename) + r'$', value) is not None

    for head, args, states in _shell_commands_with_bindings(code):
        if target_value(head):
            return True
        if (
            (head in {"python3", "python3.exe"} or python_variable.fullmatch(head))
            and args
            and target_value(args[0])
        ):
            return True
        variable = variable_head.fullmatch(head)
        if variable:
            for state in states:
                if any(
                    target_value(value)
                    for value in state.get(variable.group(1), set())
                ):
                    return True
        fallback = fallback_head.fullmatch(head)
        if fallback:
            if target_value(fallback.group(2)):
                return True
            for state in states:
                if any(
                    target_value(value)
                    for value in state.get(fallback.group(1), set())
                ):
                    return True
    return False


def _python_repo_exec_present(source, target, evidence):
    """Require a repo command head or a concretely bound CLI executable option."""
    basename = Path(target).name
    if basename in evidence:
        return True
    symbolic = re.sub(r"\W+", "_", Path(target).stem)

    tree = ast.parse(source)
    named_defaults = {}
    for assignment_node in ast.walk(tree):
        if isinstance(assignment_node, ast.Assign):
            for target_node in assignment_node.targets:
                if isinstance(target_node, ast.Name):
                    named_defaults.setdefault(target_node.id, []).append(
                        (
                            (assignment_node.lineno, assignment_node.col_offset),
                            assignment_node.value,
                        )
                    )
    option = "--" + symbolic.replace("_", "-")
    cli_options = []

    def default_targets(node, position=(float("inf"), float("inf")), resolving=frozenset()):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return {Path(node.value).name}
        if isinstance(node, ast.Name) and node.id not in resolving:
            candidates = [
                (at, value)
                for at, value in named_defaults.get(node.id, [])
                if at < position
            ]
            if candidates:
                at, value = max(candidates, key=lambda item: item[0])
                return default_targets(value, at, resolving | {node.id})
            return set()
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = default_targets(node.left, position, resolving)
            right = default_targets(node.right, position, resolving)
            return {
                Path(left_part + right_part).name
                for left_part in left
                for right_part in right
            }
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return default_targets(node.right, position, resolving)
        if isinstance(node, ast.IfExp):
            truth = None
            try:
                truth = bool(ast.literal_eval(node.test))
            except (ValueError, TypeError, SyntaxError):
                pass
            if truth is True:
                return default_targets(node.body, position, resolving)
            if truth is False:
                return default_targets(node.orelse, position, resolving)
            return default_targets(node.body, position, resolving) | default_targets(
                node.orelse, position, resolving
            )
        if isinstance(node, ast.BoolOp):
            targets = set()
            for index, value in enumerate(node.values):
                try:
                    truth = bool(ast.literal_eval(value))
                except (ValueError, TypeError, SyntaxError):
                    truth = None
                current = default_targets(value, position, resolving)
                is_last = index == len(node.values) - 1
                if isinstance(node.op, ast.And):
                    if truth is False or is_last:
                        targets |= current
                        if truth is False:
                            return targets
                    elif truth is None:
                        targets |= current
                else:
                    if truth is True or is_last:
                        targets |= current
                        if truth is True:
                            return targets
                    elif truth is None:
                        targets |= current
            return targets
        if isinstance(node, ast.Call) and node.args:
            if isinstance(node.func, ast.Name) and node.func.id in {"str", "Path"}:
                return default_targets(node.args[-1], position, resolving)
            if isinstance(node.func, ast.Attribute) and node.func.attr == "join":
                return default_targets(node.args[-1], position, resolving)
        return set()

    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            and any(
                isinstance(argument, ast.Constant) and argument.value == option
                for argument in node.args
            )
        ):
            continue
        default = next((kw.value for kw in node.keywords if kw.arg == "default"), None)
        target_is_default = default is not None and basename in default_targets(
            default, (node.lineno, node.col_offset)
        )
        if target_is_default:
            dest = next((kw.value for kw in node.keywords if kw.arg == "dest"), None)
            dest_name = (
                dest.value
                if isinstance(dest, ast.Constant) and isinstance(dest.value, str)
                else symbolic
            )
            cli_options.append((dest_name, node))
    if not cli_options:
        return False

    method_owners = {
        id(statement): class_node.name
        for class_node in ast.walk(tree)
        if isinstance(class_node, ast.ClassDef)
        for statement in class_node.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    functions = {"<module>": tree}
    function_targets = {}
    method_targets = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if id(node) in method_owners:
            owner = method_owners[id(node)]
            key = f"{owner}.{node.name}@{node.lineno}"
            method_targets[(owner, node.name)] = key
        else:
            key = node.name
            if key in functions:
                key = f"{node.name}@{node.lineno}"
            function_targets.setdefault(node.name, key)
        functions[key] = node

    class LocalFlow(ast.NodeVisitor):
        """Assignments and calls in one function, excluding nested scopes."""

        def __init__(self, root):
            self.root = root
            self.assignments = {}
            self.calls = []
            self.binding_position = None

        def visit_FunctionDef(self, node):  # noqa: N802
            if node is self.root:
                for statement in node.body:
                    self.visit(statement)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Module(self, node):  # noqa: N802
            if node is self.root:
                for statement in node.body:
                    self.visit(statement)

        def visit_Lambda(self, node):  # noqa: N802
            return

        def visit_ClassDef(self, node):  # noqa: N802
            return

        def _bind_symbol(self, name, value, node):
            self.assignments.setdefault(name, []).append(
                (
                    self.binding_position or (node.lineno, node.col_offset),
                    ast.Constant(value),
                )
            )

        def visit_Import(self, node):  # noqa: N802
            for alias in node.names:
                if alias.name == "subprocess":
                    self._bind_symbol(
                        alias.asname or "subprocess", "subprocess:module", node
                    )

        def visit_ImportFrom(self, node):  # noqa: N802
            if node.module != "subprocess":
                return
            for alias in node.names:
                if alias.name in _PYTHON_SUBPROCESS_CALLS:
                    self._bind_symbol(
                        alias.asname or alias.name,
                        f"subprocess:function:{alias.name}",
                        node,
                    )

        def visit_Assign(self, node):  # noqa: N802
            for target_node in node.targets:
                if isinstance(target_node, ast.Name):
                    self.assignments.setdefault(target_node.id, []).append(
                        (
                            self.binding_position or (node.lineno, node.col_offset),
                            node.value,
                        )
                    )
            self.visit(node.value)

        def visit_AnnAssign(self, node):  # noqa: N802
            if isinstance(node.target, ast.Name) and node.value is not None:
                self.assignments.setdefault(node.target.id, []).append(
                    (
                        self.binding_position or (node.lineno, node.col_offset),
                        node.value,
                    )
                )
                self.visit(node.value)

        def visit_Call(self, node):  # noqa: N802
            self.calls.append(node)
            self.generic_visit(node)

        def visit_If(self, node):  # noqa: N802
            try:
                truth = bool(ast.literal_eval(node.test))
            except (ValueError, TypeError, SyntaxError):
                truth = None
            if truth is not None:
                for statement in node.body if truth else node.orelse:
                    self.visit(statement)
                return
            previous = self.binding_position
            self.binding_position = (node.lineno, node.col_offset)
            before = {
                name: list(values) for name, values in self.assignments.items()
            }
            for statement in (*node.body, *node.orelse):
                self.visit(statement)
            if not node.orelse:
                for name, values in self.assignments.items():
                    prior_values = before.get(name, [])
                    if len(values) > len(prior_values) and prior_values:
                        prior_position = max(at for at, _value in prior_values)
                        for _at, value in prior_values:
                            if _at == prior_position:
                                values.append((self.binding_position, value))
            self.binding_position = previous

    flows = {}
    parameters = {}
    positional = {}
    for name, function in functions.items():
        flow = LocalFlow(function)
        flow.visit(function)
        flows[name] = flow
        if isinstance(function, ast.Module):
            positional[name] = []
            parameters[name] = set()
        else:
            positional[name] = [
                argument.arg
                for argument in (*function.args.posonlyargs, *function.args.args)
            ]
            parameters[name] = {
                argument.arg
                for argument in (
                    *function.args.posonlyargs,
                    *function.args.args,
                    *function.args.kwonlyargs,
                )
            }

    def latest_bindings(flow, name, position):
        candidates = [
            (at, value)
            for at, value in flow.assignments.get(name, [])
            if at < position
        ]
        if not candidates:
            return []
        latest_position = max(at for at, _value in candidates)
        return [item for item in candidates if item[0] == latest_position]

    call_owner = {
        id(call): name
        for name, flow in flows.items()
        for call in flow.calls
    }
    def receiver_class(node, caller, position):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node, ast.Name):
            bindings = latest_bindings(flows[caller], node.id, position)
            classes = {
                value.func.id
                for _at, value in bindings
                if isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
            }
            if len(classes) == 1:
                return next(iter(classes))
        return None

    def callee_identity(call, caller):
        if isinstance(call.func, ast.Name):
            return function_targets.get(call.func.id)
        if isinstance(call.func, ast.Attribute):
            owner = receiver_class(
                call.func.value, caller, (call.lineno, call.col_offset)
            )
            return method_targets.get((owner, call.func.attr))
        return None

    function_entry_positions = {}
    for caller, flow in flows.items():
        for call in flow.calls:
            callee = callee_identity(call, caller)
            if callee is not None:
                function_entry_positions.setdefault(callee, []).append(
                    (caller, (call.lineno, call.col_offset))
                )

    def parser_identities(node, function_name, position, resolving=frozenset()):
        if isinstance(node, ast.Name):
            key = (function_name, node.id)
            if key in resolving:
                return set()
            bindings = latest_bindings(flows[function_name], node.id, position)
            if not bindings:
                if node.id in parameters[function_name]:
                    return {("parameter", function_name, node.id)}
                if function_name != "<module>":
                    entries = function_entry_positions.get(function_name, [])
                    module_positions = [
                        at for caller, at in entries if caller == "<module>"
                    ] or [(float("inf"), float("inf"))]
                    identities = set()
                    for module_position in module_positions:
                        identities |= parser_identities(
                            node, "<module>", module_position, resolving
                        )
                    return identities
                return {("unbound", function_name, node.id)}
            identities = set()
            for at, value in bindings:
                identities |= parser_identities(
                    value, function_name, at, resolving | {key}
                )
            return identities
        if isinstance(node, ast.Attribute):
            return {("attribute", function_name, ast.dump(node))}
        return {("expression", id(node))}

    cli_parsers = {}
    cli_declarations = {}
    for dest, declaration in cli_options:
        owner = call_owner.get(id(declaration))
        if owner is None:
            continue
        identities = parser_identities(
            declaration.func.value,
            owner,
            (declaration.lineno, declaration.col_offset),
        )
        shared = cli_parsers.setdefault(dest, set())
        shared.update(identities)
        cli_declarations.setdefault(dest, []).append((owner, declaration, shared))
    if not cli_parsers:
        return False

    changed = True
    while changed:
        changed = False
        for caller, flow in flows.items():
            for call in flow.calls:
                callee = callee_identity(call, caller)
                if callee is None:
                    continue
                for dest, identities in cli_parsers.items():
                    for identity in list(identities):
                        if identity[:2] != ("parameter", callee):
                            continue
                        parameter = identity[2]
                        argument = None
                        if parameter in positional[callee]:
                            index = positional[callee].index(parameter)
                            if (
                                isinstance(call.func, ast.Attribute)
                                and positional[callee]
                                and positional[callee][0] in {"self", "cls"}
                            ):
                                index -= 1
                            if index < len(call.args):
                                argument = call.args[index]
                        if argument is None:
                            argument = next(
                                (kw.value for kw in call.keywords if kw.arg == parameter),
                                None,
                            )
                        if argument is None:
                            continue
                        concrete = parser_identities(
                            argument,
                            caller,
                            (call.lineno, call.col_offset),
                        )
                        parsed_before = any(
                            isinstance(prior.func, ast.Attribute)
                            and prior.func.attr == "parse_args"
                            and (prior.lineno, prior.col_offset)
                            < (call.lineno, call.col_offset)
                            and bool(
                                parser_identities(
                                    prior.func.value,
                                    caller,
                                    (prior.lineno, prior.col_offset),
                                )
                                & concrete
                            )
                            for prior in flow.calls
                        )
                        if parsed_before:
                            # Configuration after parsing the *same parser*
                            # cannot authorize that earlier Namespace. Parsing
                            # an unrelated parser is immaterial.
                            continue
                        new_identities = concrete - identities
                        if new_identities:
                            identities.update(new_identities)
                            changed = True

    def module_execution_positions(function_name, position, resolving=frozenset()):
        """Module positions whose execution can reach this function point."""
        if function_name == "<module>":
            return {position}
        if function_name in resolving:
            return set()
        positions = set()
        for caller, call_position in function_entry_positions.get(function_name, []):
            positions |= module_execution_positions(
                caller, call_position, resolving | {function_name}
            )
        # An uncalled helper is still a statically possible entry point for this
        # forward-verification pass; model it after module initialization. A
        # concretely called helper instead keeps its exact invocation timing.
        return positions or {(float("inf"), float("inf"))}

    def parser_configured_before(dest, identities, function_name, position):
        sink_positions = module_execution_positions(function_name, position)
        for owner, declaration, declaration_identities in cli_declarations[dest]:
            if not (identities & declaration_identities):
                continue
            declaration_position = (declaration.lineno, declaration.col_offset)
            if owner == function_name and declaration_position < position:
                return True
            configured_positions = module_execution_positions(
                owner, declaration_position
            )
            if any(
                configured < sink
                for configured in configured_positions
                for sink in sink_positions
            ):
                return True
        return False

    def is_parse_args(
        node, dest, function_name, position, resolving=frozenset()
    ):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "parse_args"
        ):
            identities = parser_identities(
                node.func.value, function_name, position
            )
            return bool(identities & cli_parsers[dest]) and parser_configured_before(
                dest, identities, function_name, position
            )
        if isinstance(node, ast.Name) and node.id not in resolving:
            bindings = latest_bindings(
                flows[function_name], node.id, position
            )
            if any(
                is_parse_args(
                    value, dest, function_name, at, resolving | {node.id}
                )
                for at, value in bindings
            ):
                return True
            if not bindings and function_name != "<module>":
                return any(
                    is_parse_args(
                        value,
                        dest,
                        "<module>",
                        at,
                        resolving | {(function_name, node.id)},
                    )
                    for module_position in module_execution_positions(
                        function_name, position
                    )
                    for at, value in latest_bindings(
                        flows["<module>"], node.id, module_position
                    )
                )
            return False
        return False

    def origins(node, function_name, position, resolving=frozenset()):
        """Return caller parameters/CLI values that can supply an argv head."""
        flow = flows[function_name]
        if isinstance(node, (ast.List, ast.Tuple)):
            return (
                origins(node.elts[0], function_name, position, resolving)
                if node.elts
                else set()
            )
        if isinstance(node, ast.Name):
            if node.id in parameters[function_name]:
                return {("param", node.id)}
            if node.id in resolving:
                return set()
            found = set()
            bindings = latest_bindings(flow, node.id, position)
            for at, value in bindings:
                found |= origins(
                    value, function_name, at, resolving | {node.id}
                )
            if not bindings and function_name != "<module>":
                for module_position in module_execution_positions(
                    function_name, position
                ):
                    for at, value in latest_bindings(
                        flows["<module>"], node.id, module_position
                    ):
                        found |= origins(
                            value,
                            "<module>",
                            at,
                            resolving | {(function_name, node.id)},
                        )
            return found
        if isinstance(node, ast.Attribute) and node.attr in cli_parsers:
            if is_parse_args(
                node.value, node.attr, function_name, position
            ):
                return {("cli", node.attr)}
            return set()
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            return origins(node.right, function_name, position, resolving)
        if isinstance(node, ast.BoolOp):
            found = set()
            for index, value in enumerate(node.values):
                try:
                    truth = bool(ast.literal_eval(value))
                except (ValueError, TypeError, SyntaxError):
                    truth = None
                if (
                    truth is None
                    and isinstance(value, ast.Attribute)
                    and value.attr in cli_parsers
                    and is_parse_args(
                        value.value, value.attr, function_name, position
                    )
                ):
                    # The declared target-bearing CLI default is a non-empty
                    # path, so it is truthy in value-selection expressions.
                    truth = True
                current = origins(value, function_name, position, resolving)
                is_last = index == len(node.values) - 1
                if isinstance(node.op, ast.And):
                    if truth is False or is_last:
                        found |= current
                        if truth is False:
                            return found
                    elif truth is None:
                        found |= current
                else:
                    if truth is True or is_last:
                        found |= current
                        if truth is True:
                            return found
                    elif truth is None:
                        found |= current
            return found
        if isinstance(node, ast.IfExp):
            try:
                truth = bool(ast.literal_eval(node.test))
            except (ValueError, TypeError, SyntaxError):
                truth = None
            if truth is True:
                return origins(node.body, function_name, position, resolving)
            if truth is False:
                return origins(node.orelse, function_name, position, resolving)
            return origins(node.body, function_name, position, resolving) | origins(
                node.orelse, function_name, position, resolving
            )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "str"
        ):
            return (
                origins(node.args[0], function_name, position, resolving)
                if node.args
                else set()
            )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Path"
        ):
            return (
                origins(node.args[-1], function_name, position, resolving)
                if node.args
                else set()
            )
        return set()

    sink_parameters = {name: set() for name in functions}

    def symbol_markers(function_name, bound_name, position):
        bindings = latest_bindings(flows[function_name], bound_name, position)
        if not bindings and function_name != "<module>":
            bindings = [
                binding
                for module_position in module_execution_positions(
                    function_name, position
                )
                for binding in latest_bindings(
                    flows["<module>"], bound_name, module_position
                )
            ]
        return {
            value.value
            for _at, value in bindings
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        }

    def official_subprocess_call(call, function_name):
        position = (call.lineno, call.col_offset)
        if isinstance(call.func, ast.Attribute):
            if not isinstance(call.func.value, ast.Name):
                return False
            bound_name = call.func.value.id
            if call.func.attr not in _PYTHON_SUBPROCESS_CALLS:
                return False
            expected_marker = "subprocess:module"
        elif isinstance(call.func, ast.Name):
            bound_name = call.func.id
            expected_marker = f"subprocess:function:{call.func.id}"
        else:
            return False
        markers = symbol_markers(function_name, bound_name, position)
        if expected_marker in markers:
            return True
        # An imported function may be renamed; the marker retains its original
        # subprocess API name while the bound name is the alias.
        return (
            isinstance(call.func, ast.Name)
            and any(
                marker.startswith("subprocess:function:") for marker in markers
            )
        )

    for name, flow in flows.items():
        for call in flow.calls:
            command = call.args[0] if call.args else next(
                (kw.value for kw in call.keywords if kw.arg == "args"), None
            )
            executable = next(
                (kw.value for kw in call.keywords if kw.arg == "executable"), None
            )
            if executable is not None and not (
                isinstance(executable, ast.Constant) and executable.value is None
            ):
                command = executable
            if not (
                command is not None
                and official_subprocess_call(call, name)
            ):
                continue
            for kind, value in origins(
                command, name, (call.lineno, call.col_offset)
            ):
                if kind == "cli":
                    return True
                sink_parameters[name].add(value)

    changed = True
    while changed:
        changed = False
        for caller, flow in flows.items():
            for call in flow.calls:
                callee = callee_identity(call, caller)
                if callee is None:
                    continue
                for sink_name in sink_parameters[callee]:
                    argument = None
                    if sink_name in positional[callee]:
                        index = positional[callee].index(sink_name)
                        if (
                            isinstance(call.func, ast.Attribute)
                            and positional[callee]
                            and positional[callee][0] in {"self", "cls"}
                        ):
                            index -= 1
                        if index < len(call.args):
                            argument = call.args[index]
                    if argument is None:
                        argument = next(
                            (kw.value for kw in call.keywords if kw.arg == sink_name), None
                        )
                    if argument is None:
                        continue
                    for kind, value in origins(
                        argument, caller, (call.lineno, call.col_offset)
                    ):
                        if kind == "cli":
                            return True
                        if value not in sink_parameters[caller]:
                            sink_parameters[caller].add(value)
                            changed = True
    return False


def _exec_target_present(helper, target, klass):
    """Forward-verification: a declared exec target actually appears in code.

    Python evidence is restricted to a ``subprocess``/``_run`` command head and
    its statically resolvable bindings. Shell evidence is restricted to command
    position (or a repo-script variable subsequently used there), so prose and
    unrelated string data cannot vouch for a stale declaration.
    """
    source = _read(helper)
    if helper.endswith(".py"):
        evidence = _python_command_evidence(source, helper)
        if klass == _REPO:
            return _python_repo_exec_present(source, target, evidence)
        return bool(_external_evidence_tokens(target) & evidence)
    if helper.endswith(".sh"):
        if klass == _REPO:
            return _shell_repo_exec_present(source, target)
        return _shell_external_present(source, target)
    return False


def check_dependencies(edges=None):
    """AC5 guard. Return a list of human-readable violations (empty == OK).

    When ``edges`` is None, classifies the live closure; a caller may pass a
    synthetic edge list to drive a single invariant (the guard's non-vacuity
    proofs inject one crafted edge at a time).
    """
    live = edges is None
    if live:
        edges = classify_all()
    errors = []

    if live:
        # Coverage, per derived-scan kind — not merely per-helper. Checking only
        # "the helper appears in some edge" is defeated by its declared exec edges:
        # a silent import/source-scan regression that drops every derived edge
        # still leaves the helper present via its exec edge, masking the exact scan
        # gap this check exists to catch. So require the derived scanner's output
        # where a helper must have one: a `.py` entry point always imports at least
        # argparse/sys, so zero import edges means the AST import scan regressed.
        # A `.sh` helper may legitimately source no sibling (config-get.sh sources
        # nothing), so its floor stays "at least one edge of any kind"; a dropped
        # source edge on a helper that does source (run-jq.sh) is caught by that
        # helper's positive fixture instead.
        kinds_by_helper = {}
        for e in edges:
            kinds_by_helper.setdefault(e.helper, set()).add(e.kind)
        for helper in entry_points():
            kinds = kinds_by_helper.get(helper, set())
            if not kinds:
                errors.append(f"entry point not classified (no edges scanned): {helper}")
            elif helper.endswith(".py") and "import" not in kinds:
                errors.append(
                    f"entry point produced no import edges (AST import scan gap?): {helper}"
                )

    for e in edges:
        if e.kind not in EDGE_KINDS:
            errors.append(f"{e.helper}: edge to {e.target!r} has unknown kind {e.kind!r}")
        if e.klass not in EDGE_CLASSES:
            errors.append(f"{e.helper}: edge to {e.target!r} has unknown class {e.klass!r}")
        if e.kind == "unresolved-source":
            # A source include the scanner could not resolve — rejected
            # unconditionally, before any class-specific check (fail closed).
            errors.append(
                f"{e.helper}: unresolvable source include {e.target!r} — the "
                f"operand could not be resolved to a .sh/.bash include (fail closed)"
            )
        elif e.klass == "repo-owned":
            if getattr(e, "auth", None):
                # Duck-typed edges bypass Edge.__post_init__, so re-assert its
                # repo-owned-carries-no-authorization invariant here too.
                errors.append(
                    f"{e.helper}: repo-owned {e.kind} edge {e.target!r} "
                    f"carries external authorization"
                )
            if not resolves_beneath_vendor(e.target):
                errors.append(
                    f"{e.helper}: repo-owned {e.kind} edge {e.target!r} does not "
                    f"resolve beneath {VENDOR_PREFIX} (repo-root escape)"
                )
            else:
                disk_target = REPO_ROOT / e.target
                resolve_error = None
                try:
                    resolved_inside_repo = disk_target.resolve().is_relative_to(
                        REPO_ROOT.resolve()
                    )
                except (OSError, RuntimeError) as exc:
                    # Fail closed, but never assert the symlink-escape diagnosis
                    # for a condition that was not established (unknown is not
                    # a diagnosis): the exception arm gets its own message.
                    resolved_inside_repo = False
                    resolve_error = exc
                if not resolved_inside_repo:
                    if resolve_error is not None:
                        errors.append(
                            f"{e.helper}: repo-owned {e.kind} edge {e.target!r} could "
                            f"not be resolved ({resolve_error}); treating as outside "
                            "the repository (fail closed)"
                        )
                    else:
                        errors.append(
                            f"{e.helper}: repo-owned {e.kind} edge {e.target!r} resolves "
                            "outside the repository (symlink escape)"
                        )
                elif not disk_target.is_file():
                    errors.append(
                        f"{e.helper}: repo-owned {e.kind} edge target missing on disk: "
                        f"{e.target}"
                    )
        elif e.klass == "external":
            # getattr for duck-typed symmetry with the repo-owned arm: a
            # synthetic edge without the attribute draws the designed
            # violation, never an AttributeError.
            if not getattr(e, "auth", None):
                errors.append(
                    f"{e.helper}: external {e.kind} edge {e.target!r} names no "
                    f"preflight guarantee or explicit profile grant"
                )
        # Forward-verify a declared exec edge is real (skip synthetic-injection
        # runs, which reference helpers/targets that need not co-exist on disk).
        if live and e.kind == "exec" and not _exec_target_present(e.helper, e.target, e.klass):
            errors.append(
                f"{e.helper}: declared exec edge target {e.target!r} not found in source"
            )

    return errors


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("check", "show"),
        help="check: AC5 trust-closure guard; show: print the classification as JSON",
    )
    args = parser.parse_args(argv)

    if args.command == "show":
        print(json.dumps([e.as_dict() for e in classify_all()], indent=2))
        return 0

    errors = check_dependencies()
    if errors:
        for e in errors:
            print(f"cloud-writer-deps: {e}")
        return 1
    print("cloud-writer-deps: trust closure OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
