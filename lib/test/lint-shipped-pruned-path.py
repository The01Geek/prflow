#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Fail the suite when a shipped prompt surface references a path the vendor slice
prunes (issue #1072), cites a PRFlow-internal issue/PR number or acceptance criterion
(issue #1241), names a `.github/workflows/` file the installer never ships (issue
#1402), names a PRFlow-internal development-harness identifier (issue #2114), or —
inside a vendored-skill body — names PRFlow's own `CLAUDE.md` (issue #1401).

Internal-identifier denylist (issue #2114): unlike the derived sets above, the forbidden
identifiers are a hardcoded module constant (`_INTERNAL_IDENTIFIERS`) — there is no
producer file to derive them from, so an empty list is a bug guarded against at import
rather than an unestablished derivation. Each identifier names a PRFlow development-harness
contract (the `structural-pin-ok` pin-corpus marker, the `CEILING_TRIPWIRE_FRACTION`
tripwire constant, the `run-parallel` coordinator log-line stem) that resolves against
nothing in a consumer's checkout. It shares the audited population and the fence-aware
`pruned-path-ok` marker discharge with the other classes.

Every forbidden class below shares one cause: `skills/**` / `agents/**` ships verbatim
into every consumer repo, so a reference that only resolves against THIS repository's
tree, issue tracker, workflow set, or project-memory file points at nothing in a
consumer's checkout. The pruned-path check (below) covers the tree paths; the citation
check covers `#123` / `issue #123` / `PR #123` and `AC5`-style acceptance-criterion
references. The never-shipped-workflow check (issue #1402) covers the `.github/workflows/`
members that reach no consumer. The
CLAUDE.md-token check (issue #1401) is narrower in scope: it fires only inside the
DERIVED vendored-skill directories — every `skills/<name>/` whose `SKILL.md` carries the
vendored-provenance sentence — because every OTHER shipped file may legitimately name
`CLAUDE.md` as the consumer's own project memory. The vendor slice never copies PRFlow's
`CLAUDE.md`, so a pointer to it in a vendored body resolves against a consumer's own,
unrelated project-memory file. The scope is derived, never a transcribed directory list,
and an empty or unestablished derivation refuses non-zero rather than scanning nothing. Each is
exempted by the same per-line declaration marker described below.

Never-shipped workflows (issue #1402) — why the prune set cannot see them
------------------------------------------------------------------------
`devflow_copy_slice()` copies no `.github/` at all, so no `.github/workflows/` member is
a *prune target* and the derivation above is structurally blind to the whole family. Yet
a consumer *does* have `.github/workflows/`: `install.sh` copies some workflows there.
The path family resolves in a consumer's checkout; individual members do not — so a
blanket `.github/` ban would be wrong, and the class is keyed to membership instead.

The never-shipped set is **derived, never transcribed**, by the same principle as the two
sets above: `parse_shipped_workflow_names()` reads the copy loop's literal operand list —
the one `install.sh` declaration that puts a workflow in a consumer's
`.github/workflows/` — and `derive_never_shipped_basenames()` subtracts it from the
tracked `.github/workflows/*.yml` stems under the workflows source. Membership is over
**parsed word lists**, never a substring search over `install.sh`: `ci` occurs as a
substring on dozens of unrelated lines, and a comment or a `--help` block naming a
workflow would read as a declaration of it. An unestablished or ambiguous declaration
refuses non-zero naming `install.sh` and audits nothing.

`DEVFLOW_WITHHELD_TIER` is **not read here at all** (issue #1423). It names workflows only a
repo that installed before the tier was withheld still carries, so counting them as shipped
told a *fresh* consumer that a file they do not have resolves — the very thing this class
exists to report. Its members are therefore forbidden like any other never-shipped name,
and the declaration has one reader again: `install.sh`'s own removal machinery.

A withheld name that has also left the tree needs no carve-out: the derivation intersects
with what is actually **tracked**, so a workflow the tree no longer carries can never enter
the forbidden set however it is declared.

Disclosed residuals, none closed here:

* **The extensionless stem is invisible.** The scan keys on the `<basename>.yml`
  filename, so a bare stem in prose matches nothing. Keying on the stem alone would ban
  the substring `ci` outright, which no marker budget absorbs.
* **A `.yaml`-suffixed workflow is invisible**, to both the derivation's pathspec and the
  scan key. GitHub accepts that suffix; this repository uses `.yml` throughout, and
  widening would double the pathspec and the scan list for a population of zero.
* **A workflow absent from the workflows source is invisible.** The forbidden set is an
  intersection with what is actually tracked, so a pointer to a workflow that was deleted
  from the tree names nothing the derivation can see. The class has no live instance today.
* **A shipped sentence about a CONSUMER's own same-named workflow is reported.** `ci` is in
  the derived set, so telling a consumer to check their own `ci.yml` draws a finding. It is
  a true statement about PRFlow's file and a false one about theirs, and the per-line
  declaration marker absorbs it — over-reporting, in the safe direction.

Why this exists: `.github/actions/vendor-plugin/vendor-slice.sh`'s
`devflow_copy_slice()` deletes subtrees from the vendored plugin before it lands in
a consumer (`lib/test`, `docs/site`, `docs/external`, `docs/internal`,
`.claude-plugin/marketplace.json`). For a *forbidden* prune target — one not exempted
below — a shipped prompt sentence that names it as an instruction to *run*, or even
merely mentions it, resolves against a consumer's own tree, where the path does not
exist. The guards that predated this lint were hand-written per-file negatives over
a closed literal blacklist covering two files out of the shipped prompt surface's
sixty-three. This lint replaces that with a derivation: it parses the prune set out
of the slice itself and audits every `skills/**` / `agents/**` file for a reference
to one of those paths that does not carry an explicit declaration marker.

The forbidden path set is **derived, never transcribed** — a guard whose comparand is
a hardcoded copy of another file's content fails open the moment that file changes,
which is the exact defect this lint exists to prevent recurring one level up. A
qualifying prune target is an argument of an `rm` (any flag set — `rm -f` qualifies
alongside `rm -rf`) inside `devflow_copy_slice()`, written as the staging-directory
variable followed by a non-empty path suffix. The staging variable is itself
**identified from the function** — the target of the single assignment whose
right-hand side composes the function's destination argument (`$2`) — and never
carried as the literal name `stage`, so a rename in the slice is tracked rather than
silently missed. When the prune set cannot be established (the function, the
destination parameter, the composing assignment, or any qualifying target is
missing) the lint **refuses non-zero naming the slice source**, auditing nothing: an
empty or unparseable prune set is never a clean run.

Docs-default exemption (issue #1309): two prune targets — `docs/external` and
`docs/internal` on today's slice — are simultaneously the documented default values
of consumer-facing config keys (`.docs.external`, `.docs.internal`). Those directories
ARE the consumer's own tree, exactly where the docs skills teach a consumer to keep
their docs, so a shipped sentence naming them is documentation, not a dangling path.
The exemption set is **derived, never transcribed** by the same principle as the prune
set: `parse_docs_defaults()` reads the path-shaped string `default` values under
`properties.docs.properties` of `.prflow/config.schema.json` and subtracts, by
trailing-slash-normalized EQUALITY (never prefix containment), any prune target that
equals one — so a future `docs.*` default change moves the exemption with it. It
preserves the fail-closed posture: an unestablished exemption derivation (an absent,
unreadable, unparseable, keyless, or non-object schema) refuses non-zero naming the
schema, and an exemption set that empties the forbidden set refuses on the same terms
as the empty-prune-set refusal one level up. The exemption applies to the derived
prune set only; the issue-#1241 citation scan carries no target list and is unaffected.

Deliberate divergence from the closest structural sibling
(`lib/test/lint-superseded-config-keys.py`, issue #1084): #1084 exempts sites via an
in-checker path list. This lint rejects that in favour of an in-file declaration
marker on the referencing line, because its exceptions are per-*line* prose
judgements a reader must see at the site. The marker joins the existing family
(`# structural-pin-ok:`, `# raw-guard-ok:`, `# tree-walk-ok:`, `# argjson-ok:`),
adapted to markdown as an HTML comment. It has two fence-conditional spellings:
`<!-- pruned-path-ok: <reason> -->` for ordinary prose, and `# pruned-path-ok:
<reason>` for a line inside a fenced block the engine emits verbatim into a
consumer's shell (where an HTML comment would be emitted as shell text). The reason
must be non-empty. Fence tracking mirrors `scripts/load-prompt-extension.sh`'s
header — the in-repo rule of record: both CommonMark fence characters, a fence
closes only on its own kind, an unclosed fence runs to end of file, and an indented
fence is not recognized.

Population is enumerated from the git index over `skills/**` and `agents/**`
(`lib/test/lint_population.py`'s `enumerate_population` with the index-reading argv —
no `--others`, no repository-root-anchored recursive walk, per issue #711).

Usage:
    lint-shipped-pruned-path.py [--root DIR] [--files-from PATH]
                                [--slice-source PATH] [--schema-source PATH]
                                [--install-source PATH] [--workflows-source DIR]
                                [--print-prune-set | --print-exempt-set
                                 | --print-never-shipped-set]

`--print-exempt-set` prints, one per line, the prune targets the docs.* exemption
subtracted from the forbidden set (a path-shaped docs.* default that is not itself a
prune target subtracts nothing and is not printed); it exits 0 even when the exemption
selects nothing, so the derivation is observable on the success path.
`--print-never-shipped-set` prints, one per line, the never-shipped workflow basenames.

On the audit path (no `--print-*` flag), exit status is 0 only when the prune set AND the
docs.* exemption set were established,
the post-exemption forbidden set is non-empty, the never-shipped workflow set (issue
#1402) was derived non-empty, the vendored-skill scope (issue #1401)
was derived non-empty, the enumeration selected at least one audited file, every selected
file was read, and none referenced a prune target, cited a PRFlow-internal reference,
named a never-shipped workflow, or
named PRFlow's own `CLAUDE.md` inside a vendored body without a marker. It is non-zero
when any such reference is found, when the prune set or the exemption set cannot be
established, when the exemption empties the forbidden set, when either `install.sh`
declaration or the workflows listing cannot be established, when the never-shipped set
derives empty, when the vendored-skill scope
derives empty, when the enumeration is unusable, when it selects no audited file at all,
and when any selected path could not be read.
"""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

# The population enumeration, the file reader, the `EnumerationError` fail-closed
# contract, and the `--root` / `--files-from` preamble are shared with the other
# `git ls-files` lints (issue #724), loaded by path exactly as the sibling lints do.
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
        f"lint-shipped-pruned-path: {_POP_PATH} no longer provides "
        f"{', '.join(_pop_missing)}; refusing to audit"
    )

EnumerationError = _pop.EnumerationError

#: The audited population is markdown source; a NUL-carrying decode is reported as a
#: skip (never scanned) and fails the run closed, mirroring the sibling gh-api lint.
_SKIP_NUL = True

#: Path prefixes whose files make up the audited population.
AUDITED_PREFIXES = ("skills/", "agents/")

#: The default slice source, relative to the resolved root.
DEFAULT_SLICE_REL = ".github/actions/vendor-plugin/vendor-slice.sh"

#: The default schema source, relative to the resolved root. The exemption set (issue
#: #1309) is derived from the documented `docs.*` config defaults it declares.
DEFAULT_SCHEMA_REL = ".prflow/config.schema.json"

#: The default installer source, relative to the resolved root. The shipped-workflow name
#: set (issue #1402) is derived from the two declarations it carries.
DEFAULT_INSTALL_REL = "install.sh"

#: The default workflows source, relative to the resolved root. Its `*.yml` children are
#: the population the never-shipped set (issue #1402) is the complement within.
DEFAULT_WORKFLOWS_REL = ".github/workflows"


class PruneParseError(Exception):
    """The prune set could not be established from the slice source. Fails closed."""


class DocsDefaultsParseError(Exception):
    """The `docs.*` default set could not be established from the schema source.

    Mirrors `PruneParseError`: raised on every shape of `.prflow/config.schema.json`
    that cannot yield a real exemption derivation, so the two derivations fail closed
    on identical terms. The caller catches it in `main` and refuses non-zero naming the
    schema source — an unestablished exemption set is never silently an empty one.
    """


class NeverShippedParseError(Exception):
    """The never-shipped workflow set could not be established (issue #1402).

    Refuses non-zero naming the source it read, because an unestablished set read as an
    empty one would leave the whole workflow family unaudited on an exit-0 run.
    """


class VendoredScopeError(Exception):
    """The vendored-skill directory scope could not be established (issue #1401).

    Raised on an unreadable `skills/*/SKILL.md`: skipping one would drop its directory
    from scope while another match keeps the empty-derivation guard quiet, so every file
    in the dropped directory escapes the token ban on an exit-0 run.
    """


def _function_body(slice_text: str) -> str:
    """Return the body lines of `devflow_copy_slice()`, or raise.

    The function's closing brace is a bare `}` at column 0 (the bash style this repo
    uses), so the body runs from the line after the definition to the next such line.
    Braces inside `${…}` / `$(…)` never start a line, so this is robust where a raw
    character-level brace count is not.
    """
    lines = slice_text.split("\n")
    start = None
    for i, line in enumerate(lines):
        if re.match(r"\s*devflow_copy_slice\s*\(\s*\)", line):
            start = i
            break
    if start is None:
        raise PruneParseError("devflow_copy_slice() not found")
    body: list[str] = []
    for line in lines[start + 1:]:
        if re.match(r"}\s*$", line):
            return "\n".join(body)
        body.append(line)
    raise PruneParseError("devflow_copy_slice() closing brace not found")


def _fold_continuations(body: str) -> list[str]:
    """Join `\\`-continued lines so a target wrapped across a continuation is one line."""
    folded: list[str] = []
    pending = ""
    for line in body.split("\n"):
        if pending:
            pending += " " + line.lstrip()
        else:
            pending = line
        if pending.rstrip().endswith("\\"):
            pending = pending.rstrip()[:-1]
            continue
        folded.append(pending)
        pending = ""
    if pending:
        folded.append(pending)
    return folded


def _destination_param(lines: list[str]) -> str | None:
    """The function's destination parameter — the local var assigned exactly `$2`."""
    for line in lines:
        m = re.search(r'\b([A-Za-z_][A-Za-z0-9_]*)="?\$\{?2\}?"?', line)
        if m:
            return m.group(1)
    return None


def _staging_variable(lines: list[str], dest: str) -> str | None:
    """The staging variable — target of the single assignment composing `$dest`."""
    ref = re.compile(r"\$\{?" + re.escape(dest) + r"\}?\b")
    for line in lines:
        m = re.match(r'\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$', line)
        if not m:
            continue
        # An assignment whose target is the destination itself is not the staging var.
        if m.group(1) == dest:
            continue
        if ref.search(m.group(2)):
            return m.group(1)
    return None


def parse_prune_targets(slice_text: str) -> list[str]:
    """Return the sorted, de-duplicated prune-target suffixes derived from the slice.

    Raises `PruneParseError` on every shape that cannot yield a real target set: no
    function, no destination parameter, no composing assignment, or no qualifying
    removal. A bare staging-directory argument, a removal keyed on any other variable,
    and a `find … -exec` `{}` placeholder are all rejected — the first must never
    normalize to an empty suffix that would match every line of every audited file.
    """
    body = _function_body(slice_text)
    lines = _fold_continuations(body)
    dest = _destination_param(lines)
    if dest is None:
        raise PruneParseError("could not identify the destination parameter ($2)")
    stage = _staging_variable(lines, dest)
    if stage is None:
        raise PruneParseError(
            "could not identify the staging variable "
            "(no assignment composes the destination argument)"
        )
    stage_re = re.compile(r"^\$\{?" + re.escape(stage) + r"\}?/(.+)$")
    bare_re = re.compile(r"^\$\{?" + re.escape(stage) + r"\}?/?$")
    targets: list[str] = []
    for line in lines:
        try:
            # `comments=True` so a `#` comment is stripped BEFORE lexing. The real slice
            # carries prose comments inside this function, and an apostrophe in one of
            # them ("DevFlow's own test suite") is an unbalanced quote to a lexer that
            # sees it. shlex itself decides what is a comment, so a `#` inside a quoted
            # token still lexes as data — the accepted set is shlex's, not a re-derived
            # approximation of it.
            tokens = shlex.split(line, comments=True, posix=True)
        except ValueError as exc:
            # No best-effort re-split. `line.split()` accepts a SUPERSET of what shlex
            # accepts, so a quoted target on an unlexable line keeps its quotes, misses
            # `stage_re`, and drops out of the set — and the empty-set refusal below
            # never fires while one other target survives. An unlexable line inside
            # the slice function is an establishment failure, so it refuses here.
            raise PruneParseError(
                f"could not lex a line of devflow_copy_slice(): {line.strip()!r}: {exc}"
            ) from exc
        if "rm" not in tokens:
            continue
        for token in tokens:
            if bare_re.match(token):
                # Bare staging directory — never a target (would be an empty suffix).
                continue
            m = stage_re.match(token)
            if m and m.group(1):
                suffix = m.group(1).rstrip("/")
                if suffix and suffix not in targets:
                    targets.append(suffix)
    if not targets:
        raise PruneParseError("no qualifying rm target found in devflow_copy_slice()")
    return sorted(targets)


def parse_docs_defaults(schema_bytes: bytes) -> set[str]:
    """Return the trailing-slash-normalized set of **path-shaped** `docs.*` string
    defaults declared under `properties.docs.properties` of the config schema (issue
    #1309). A member here is a candidate exemption: a prune target that string-equals
    one of these (after both sides are trailing-slash-stripped) is a documented
    consumer-facing docs path, not a path that vanishes from a consumer's checkout.

    Path-shaped means the string default contains a `/`, which is what keeps the
    block's non-path defaults (`labels` = `Documented`, `changelog_file` =
    `CHANGELOG.md`) from ever contributing an exemption. A non-string default
    contributes nothing and raises nothing.

    Raises `DocsDefaultsParseError` on every shape that cannot yield a real default
    set: bytes that do not parse as JSON, no `properties.docs.properties` key, or a
    `properties.docs.properties` value that is not a JSON object. (An absent or
    unreadable file is an `OSError` at the read in `main`, handled there.) Returning an
    empty set is legitimate — a schema with a `docs.properties` block whose defaults are
    all non-path — and is never itself an error; only an *unestablished* set refuses.
    """
    try:
        data = json.loads(schema_bytes)
    except (ValueError, UnicodeDecodeError) as exc:
        raise DocsDefaultsParseError(f"bytes do not parse as JSON: {exc}") from exc
    props = data.get("properties") if isinstance(data, dict) else None
    docs = props.get("docs") if isinstance(props, dict) else None
    if not (isinstance(docs, dict) and "properties" in docs):
        raise DocsDefaultsParseError(
            "no properties.docs.properties key in the schema"
        )
    docs_props = docs["properties"]
    if not isinstance(docs_props, dict):
        raise DocsDefaultsParseError(
            "properties.docs.properties is not a JSON object"
        )
    defaults: set[str] = set()
    for spec in docs_props.values():
        if not isinstance(spec, dict):
            continue
        default = spec.get("default")
        # A non-string default contributes no exemption (and raises nothing); a
        # path-shaped one (contains '/') is normalized by trailing-slash stripping,
        # mirroring parse_prune_targets' own `suffix.rstrip("/")`.
        if not isinstance(default, str) or "/" not in default:
            continue
        defaults.add(default.rstrip("/"))
    return defaults


#: The copy loop that installs workflow files: `for <var> in <literal names>; do`, whose
#: body installs `.github/workflows/$<var>.yml`. Identified by that body reference rather
#: than by the loop variable's name, so a rename in the installer is tracked rather than
#: silently missed — the same derive-don't-transcribe posture `_staging_variable` takes.
_COPY_LOOP = re.compile(r"^\s*for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\s+(.+?)\s*;\s*do\s*$")

def _literal_words(operands: str) -> list[str]:
    """Tokenize a `for … in <operands>; do` list into the literal words it iterates.

    One token is one loop iteration, which is why there is no whitespace re-split: a
    quoted operand (`for w in "a b"`) iterates the single value `a b`, so the installer
    would look for one absurdly-named workflow and neither `a` nor `b` would reach a
    consumer — splitting it would drop both from the never-shipped set, a fail-open. (The
    re-split existed for `DEVFLOW_WITHHELD_TIER`, a string the installer word-splits at
    use; issue #1423 stopped reading that declaration.) A `$`-carrying word is a variable
    this parser cannot resolve, so it contributes no name rather than its own literal text.
    """
    try:
        tokens = shlex.split(operands, comments=True, posix=True)
    except ValueError:
        return []
    return [token for token in tokens if "$" not in token]


def parse_shipped_workflow_names(install_text: str) -> set[str]:
    """Return the workflow stems `install.sh` copies into a consumer's checkout.

    The set is the copy-loop operand list alone — the one declaration that *puts* a
    workflow in a consumer's `.github/workflows/`. `DEVFLOW_WITHHELD_TIER` is not read; the
    module docstring's never-shipped section states why (issue #1423).

    The copy loop is identified by two properties together, never by the loop variable's
    name: its **body** names `.github/workflows/$<var>.yml`, and its **operand list holds
    a literal word**. Both conjuncts are load-bearing, because `install.sh` carries a
    second loop over workflow paths (`devflow_withheld_tier_present`) whose body satisfies
    the first conjunct alone — it iterates `$DEVFLOW_WITHHELD_TIER`, so only the literal
    operand list tells the two apart.

    `shlex.split` is the shared tokenizer with `parse_prune_targets`; `_literal_words`
    swallows an unlexable line into an empty list where `parse_prune_targets` raises —
    both fail closed.

    The declaration is not read by first match: a second literal-bearing workflow loop
    **refuses** naming both line numbers. The two conjuncts above say nothing about a
    loop's DIRECTION, so a removal loop over literal workflow names satisfies them too and
    selecting it would invert the set silently; refusing on ambiguity keeps that loud.

    A `$`-carrying operand is dropped as unresolvable, so a mixed list (`for w in a $B`)
    yields a PARTIAL set rather than a refusal — over-broad, in the fail-closed direction.

    Raises `NeverShippedParseError` on every shape that cannot yield a real name set: no
    loop naming a workflow path, no such loop declaring a literal word, or more than one
    that does. Each refusal names the declaration that failed.
    """
    lines = install_text.split("\n")

    saw_workflow_loop = False
    literal_candidates: list[tuple[int, list[str]]] = []
    for index, line in enumerate(lines):
        match = _COPY_LOOP.match(line)
        if not match:
            continue
        loop_var, operands = match.group(1), match.group(2)
        refs = (
            f".github/workflows/${loop_var}.yml",
            f".github/workflows/${{{loop_var}}}.yml",
        )
        # `done` at any indentation closes the body; an unclosed loop runs to end of file
        # and simply fails the reference test.
        body = itertools.takewhile(
            lambda body_line: not re.match(r"\s*done\b", body_line), lines[index + 1:]
        )
        if not any(ref in body_line for body_line in body for ref in refs):
            continue
        saw_workflow_loop = True
        # A candidate whose operands are all variable references is the decoy loop, which
        # contributes no literal word and so is not a competitor for selection.
        words = _literal_words(operands)
        if words:
            literal_candidates.append((index + 1, words))
    if not saw_workflow_loop:
        raise NeverShippedParseError(
            "no workflow copy loop found (no `for <var> in …; do` whose body names "
            ".github/workflows/$<var>.yml)"
        )
    if not literal_candidates:
        raise NeverShippedParseError(
            "no workflow copy loop declares a literal workflow name (every candidate "
            "loop iterates a variable reference)"
        )
    # Every candidate is collected before selecting, so a SECOND literal-bearing loop over
    # workflow paths refuses instead of losing to a first-match break. The two conjuncts
    # distinguish the copy loop from a loop iterating a variable, but say nothing about
    # DIRECTION: a removal loop over literal workflow names satisfies both, and selecting it
    # would invert the shipped set silently. Refusing names the ambiguity instead.
    if len(literal_candidates) > 1:
        raise NeverShippedParseError(
            "more than one loop over literal workflow names references "
            ".github/workflows/, at lines "
            + ", ".join(str(number) for number, _ in literal_candidates)
            + " — cannot establish which one installs into a consumer"
        )
    return set(literal_candidates[0][1])


def derive_never_shipped_basenames(
    workflows_source: Path, shipped: set[str]
) -> list[str]:
    """Return the sorted tracked `.github/workflows/*.yml` stems absent from `shipped`.

    The population is an **index read** (`git ls-files` under the workflows source, no
    `--others`), which is what makes it worktree-immune per issue #711's tree-enumeration
    convention; git's `*.yml` pathspec matches `/` too, so the listing is filtered to this
    directory's own children. The index rather than a working-tree glob because the
    driver pins this set by equality: a developer's untracked scratch `.github/workflows/`
    file would otherwise change the derived set locally and turn that pin red on a tree CI
    reports green.

    Raises `NeverShippedParseError` when the listing cannot be established or yields no
    `*.yml` at all, and when every present workflow is shipped — either would audit the
    shipped surface against an empty forbidden set, which is this lint's own fail-open
    class one level up.
    """
    try:
        proc = subprocess.run(
            [*_pop.LS_FILES_INDEX, "--", "*.yml"],
            cwd=str(workflows_source),
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, UnicodeDecodeError) as exc:
        raise NeverShippedParseError(
            f"could not list the workflows source {workflows_source}: {exc}"
        ) from exc
    if proc.returncode != 0:
        raise NeverShippedParseError(
            f"git ls-files under the workflows source {workflows_source} exited "
            f"{proc.returncode}: {proc.stderr.strip() or '(no stderr)'}"
        )
    # git's `*.yml` pathspec matches `/` too, so the listing can reach a nested workflow
    # whose stem would collide with a top-level one. Keep the population to this
    # directory's own children, which is what the index read is scoped to name.
    present = sorted(
        {
            Path(name).stem
            for name in proc.stdout.split("\n")
            if name.strip() and "/" not in name
        }
    )
    if not present:
        raise NeverShippedParseError(
            f"the workflows source {workflows_source} tracks no *.yml file"
        )
    never_shipped = [stem for stem in present if stem not in shipped]
    if not never_shipped:
        raise NeverShippedParseError(
            f"every workflow under {workflows_source} is declared shipped by install.sh, "
            "leaving the never-shipped set empty"
        )
    return never_shipped


#: A recognized declaration marker, by fence context. Each requires a non-empty reason.
_MARKER_HTML = re.compile(r"<!--\s*pruned-path-ok:\s*(\S.*?)\s*-->")
_MARKER_SHELL = re.compile(r"#\s*pruned-path-ok:\s*(\S.*?)\s*$")

#: A line at column 0 opening/closing a fenced block (indented fences are not fences).
_FENCE = re.compile(r"^(`{3,}|~{3,})")


def _fence_states(lines: list[str]) -> list[bool]:
    """Return, per line, whether that content line is inside a fenced block.

    A fence delimiter line itself yields False (it is the boundary, not the interior).
    Mirrors scripts/load-prompt-extension.sh: both fence characters tracked, a fence
    closes only on its own kind, an unclosed fence runs to end of file, an indented
    fence is not recognized.
    """
    states: list[bool] = []
    fence_char: str | None = None
    for line in lines:
        m = _FENCE.match(line)
        if m:
            char = line[0]
            if fence_char is None:
                fence_char = char
                states.append(False)  # opening delimiter
                continue
            if fence_char == char:
                fence_char = None
                states.append(False)  # closing delimiter
                continue
            # A fence delimiter of the other kind is interior content of this fence.
            states.append(True)
            continue
        states.append(fence_char is not None)
    return states


def _scan(text: str, match) -> list[tuple[int, str]]:
    """Return (1-based line number, matched string) for each line whose `match(line)`
    returns a non-None string and that carries no fence-appropriate `pruned-path-ok`
    marker.

    The line-split, the `_fence_states` pass, and the fence-conditional
    `_MARKER_SHELL`/`_MARKER_HTML` exemption are shared by every audited scan (pruned
    paths and internal citations alike), so the exemption semantics cannot drift between
    them — the "same declaration marker" the module docstring promises is structural, not
    a copied loop. The matched string is returned alongside the line so the caller never
    re-splits the file or re-scans to recover what matched.
    """
    lines = text.split("\n")
    states = _fence_states(lines)
    found: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        matched = match(line)
        if matched is None:
            continue
        marker = _MARKER_SHELL if states[idx] else _MARKER_HTML
        if marker.search(line):
            continue
        found.append((idx + 1, matched))
    return found


def scan_text(text: str, targets: list[str]) -> list[tuple[int, str]]:
    """Return (1-based line number, matched target) for each unmarked pruned-path reference."""
    return _scan(text, lambda line: next((t for t in targets if t in line), None))


#: A PRFlow-internal citation forbidden on the shipped prompt surface (issue #1241): a
#: GitHub issue/PR number (`#123`, `issue #123`, `PR #123`) or an acceptance-criterion
#: reference (`AC5`). Both resolve against one of THIS repo's own issues, so a consumer
#: reading one in a vendored skill body cannot look it up — it points at nothing in
#: their checkout. `#\d+` requires a trailing word boundary so a hex colour like
#: `#1D76DB` (whose `#1` is followed by a letter, not a boundary) is never a false
#: match; `AC\d+` requires a leading one so an embedded run like `MAC5` is not a match;
#: a run ID carries no `#` and is excluded by construction.
#:
#: **Stated scope limit — silence here is not coverage.** The recognized set is exactly
#: these two shapes, and two classes sit outside it by construction, neither of which is
#: broadened here because both trade one recognizer defect for a worse one:
#:
#:   * **All-digit `#`-literals** (`#123456` as a hex colour, `#12` as a version) match
#:     and are reported. They are indistinguishable from a real issue reference by shape
#:     alone, so the recognizer takes the fail-CLOSED direction: a false finding is noise
#:     a reader dismisses with a declaration marker, whereas excluding them would let a
#:     genuine `#123` citation ship silently. No such literal exists in the audited tree
#:     today, so the choice costs nothing at present.
#:   * **Adjacent citation spellings** — `AC-5`, `AC 5`, `ac5`, and prose forms like
#:     "issue 441" carrying no `#` — do NOT match and are NOT reported. Broadening to
#:     them would make every bare small integer in the shipped prose a candidate, which
#:     is a false-positive rate no declaration-marker budget absorbs. None exists in the
#:     audited tree today, so the guarantee this lint gives is not vacuous — but it is a
#:     guarantee over the two recognized shapes only, and the review pass remains the
#:     control for the rest.
_CITATION = re.compile(r"#\d+\b|\bAC\d+\b")


def scan_citations(text: str) -> list[tuple[int, str]]:
    """Return (1-based line number, matched citation) for each unmarked internal citation.

    Shares the fence-aware `pruned-path-ok` marker exemption with `scan_text` through the
    common `_scan` primitive, so a line carrying the declaration marker is exempt
    regardless of what it cites — an intentional keep, or a citation that lives inside a
    marker's own reason text, is clean without a second marker family.
    """
    def match(line: str):
        m = _CITATION.search(line)
        return m.group(0) if m else None

    return _scan(text, match)


#: The vendored-provenance sentence (issue #1401). A `skills/<name>/SKILL.md` carrying
#: it is a body vendored from the MIT-licensed superpowers plugin, shipped verbatim into
#: every consumer repo. The scope of the `CLAUDE.md`-token ban below is DERIVED from
#: which SKILL.md bodies carry this sentence — never a transcribed directory list — so a
#: rename or a newly-vendored skill moves the scope with no edit here, and an empty
#: derivation fails the run closed rather than silently scanning nothing.
_PROVENANCE_SENTENCE = "MIT-licensed `superpowers` plugin"

#: The token forbidden inside a vendored-skill body (issue #1401): it names PRFlow's OWN
#: `CLAUDE.md`, which the vendor slice never copies, so in a consumer's checkout it
#: resolves against that repo's own project-memory file — a non-shipping pointer. A plain
#: substring test, never a regex over citation shapes: a shape rule over the whole audited
#: population would report the correct generic `CLAUDE.md` references every other
#: skills/**+agents/** file legitimately carries. `CLAUDE.local.md` does not contain this
#: token as a substring, so it is never a match.
_VENDORED_CLAUDE_MD_TOKEN = "CLAUDE.md"

#: PRFlow-internal identifiers forbidden anywhere on the shipped prompt surface (issue
#: #2114). Each names a PRFlow development-harness contract no consumer's tree carries:
#: `structural-pin-ok` is the pin-corpus declaration marker read by `pin-corpus-lint.py`
#: (which the installer prunes); `CEILING_TRIPWIRE_FRACTION` and `run-parallel` are the
#: retrospective suite-runtime tripwire's own constant and the whole-suite coordinator's
#: log-line stem. A shipped body naming one instructs a consumer's agent about a marker or
#: tool their repository does not have.
#:
#: This is a **module constant**, not a derivation: unlike the four classes above it has no
#: producer file to read, so there is no unestablished state to fail closed on. An empty
#: list would silently audit nothing, so it is guarded non-empty at import. The set is a
#: minimum floor; a future internal identifier is added here. Substring safety comes from
#: the filename-boundary-aware matcher below: an identifier embedded inside a longer
#: alphanumeric word (`xrun-parallelism`) is not a reference and is never reported.
_INTERNAL_IDENTIFIERS = ("structural-pin-ok", "CEILING_TRIPWIRE_FRACTION", "run-parallel")

if not _INTERNAL_IDENTIFIERS:
    raise SystemExit(
        "lint-shipped-pruned-path: _INTERNAL_IDENTIFIERS is empty; refusing to audit the "
        "shipped surface against no internal-identifier denylist"
    )


def derive_vendored_skill_dirs(root: Path) -> set[str]:
    """Return the set of `skills/<name>/` prefixes whose `SKILL.md` carries the
    vendored-provenance sentence (issue #1401).

    Root-anchored and non-recursive (`skills/*/SKILL.md`) so it is independent of the
    `--files-from` narrowing and cannot reach a sibling worktree. Derived, never
    transcribed: a rename or a newly-vendored skill moves the scope with no edit here.
    The SKILL.md read here is a direct lossy read, deliberately NOT the shared
    `_pop.read_source` — the derivation is a property of the on-disk tree, not of the
    audited population a test may narrow or stub. An empty result is the caller's
    fail-closed signal; `main` refuses non-zero rather than scanning nothing, the same
    posture as the empty-prune-set refusal. An unreadable `SKILL.md` raises rather than
    skipping, because a partial derivation drops that directory from scope while the
    remaining match keeps the empty-derivation guard quiet.
    """
    dirs: set[str] = set()
    for skill_md in root.glob("skills/*/SKILL.md"):
        try:
            text = skill_md.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise VendoredScopeError(f"could not read {skill_md}: {exc}") from exc
        if _PROVENANCE_SENTENCE in text:
            dirs.add(f"skills/{skill_md.parent.name}/")
    return dirs


def scan_vendored_claude_md(text: str) -> list[tuple[int, str]]:
    """Return (1-based line, matched token) for each unmarked `CLAUDE.md` reference,
    sharing the fence-aware `pruned-path-ok` marker discharge through `_scan`."""
    return _scan(
        text,
        lambda line: _VENDORED_CLAUDE_MD_TOKEN if _VENDORED_CLAUDE_MD_TOKEN in line else None,
    )


#: A denylisted internal identifier, filename-boundary-aware (issue #2114). The boundary
#: alphabet is `[A-Za-z0-9_]` only — a hyphen, dot, slash, colon, or backtick adjacent to
#: the identifier still matches, so a real reference (`run-parallel.sh`, `run-parallel:`,
#: `.github/.../run-parallel`) is caught while an identifier embedded inside a longer
#: alphanumeric word (`xrun-parallelism`, `astructural-pin-okz`) is not. Built once from
#: the module constant and reused across the audited population, like `_never_shipped_matcher`.
_INTERNAL_IDENT_RE = re.compile(
    r"(?<![A-Za-z0-9_])(" + "|".join(re.escape(i) for i in _INTERNAL_IDENTIFIERS) + r")(?![A-Za-z0-9_])"
)


def scan_internal_identifiers(text: str) -> list[tuple[int, str]]:
    """Return (1-based line, matched identifier) for each unmarked internal-identifier
    reference, sharing the fence-aware `pruned-path-ok` marker discharge through `_scan`."""
    def match(line: str) -> str | None:
        found = _INTERNAL_IDENT_RE.search(line)
        return found.group(0) if found else None

    return _scan(text, match)


def _never_shipped_matcher(basenames: list[str]):
    """Return a `_scan` matcher for `<stem>.yml` references, filename-boundary-aware.

    A plain substring test would report `docs-ci.yml` for the `ci` stem, wrongly telling a
    consumer that a workflow they own is PRFlow's. Requiring the preceding character to be
    outside the filename alphabet keeps `.github/workflows/ci.yml` (preceded by `/`) and a
    bare `` `ci.yml` `` matching while excluding a longer filename that merely ends in one.
    Built once and reused across the audited population.
    """
    pattern = re.compile(
        r"(?<![A-Za-z0-9_.\-])(" + "|".join(re.escape(b) for b in basenames) + r")\.yml"
    )

    def match(line: str) -> str | None:
        found = pattern.search(line)
        return found.group(0) if found else None

    return match


def _establish_never_shipped(
    install_source: Path, workflows_source: Path
) -> list[str] | None:
    """Return the never-shipped basenames, or None having printed the refusal (#1402).

    The two call sites — the print flag and the audit path — must refuse on identical
    terms, so the read, the parse and the diagnostic live here rather than at either.
    """
    try:
        install_text = install_source.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(
            f"lint-shipped-pruned-path: could not read install source {install_source}: "
            f"{exc}; auditing nothing",
            file=sys.stderr,
        )
        return None
    try:
        return derive_never_shipped_basenames(
            workflows_source, parse_shipped_workflow_names(install_text)
        )
    except NeverShippedParseError as exc:
        print(
            f"lint-shipped-pruned-path: could not establish a never-shipped workflow set "
            f"from {install_source} and {workflows_source}: {exc}; auditing nothing",
            file=sys.stderr,
        )
        return None


def is_audited(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return any(normalized.startswith(p) for p in AUDITED_PREFIXES)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail when a shipped prompt surface (skills/**, agents/**) references a "
            "path the vendor slice prunes, or cites a PRFlow-internal issue/PR number "
            "or acceptance criterion, without a declaration marker."
        )
    )
    _pop.add_population_arguments(parser)
    parser.add_argument(
        "--slice-source",
        default=None,
        help=(
            "the vendor-slice.sh to derive the prune set from "
            "(default: <root>/" + DEFAULT_SLICE_REL + ")"
        ),
    )
    parser.add_argument(
        "--schema-source",
        default=None,
        help=(
            "the config schema to derive the docs.* exemption set from "
            "(default: <root>/" + DEFAULT_SCHEMA_REL + ")"
        ),
    )
    parser.add_argument(
        "--install-source",
        default=None,
        help=(
            "the installer to derive the shipped-workflow name set from "
            "(default: <root>/" + DEFAULT_INSTALL_REL + ")"
        ),
    )
    parser.add_argument(
        "--workflows-source",
        default=None,
        help=(
            "the directory whose *.yml children the never-shipped set is the complement "
            "within (default: <root>/" + DEFAULT_WORKFLOWS_REL + ")"
        ),
    )
    print_group = parser.add_mutually_exclusive_group()
    print_group.add_argument(
        "--print-prune-set",
        action="store_true",
        help=(
            "print the post-exemption prune set (one per line) and exit, "
            "auditing nothing"
        ),
    )
    print_group.add_argument(
        "--print-exempt-set",
        action="store_true",
        help=(
            "print the prune targets exempted by a docs.* default (one per line) "
            "and exit, auditing nothing"
        ),
    )
    print_group.add_argument(
        "--print-never-shipped-set",
        action="store_true",
        help=(
            "print the never-shipped workflow stems (one per line) and exit, "
            "auditing nothing"
        ),
    )
    args = parser.parse_args(argv)

    root = _pop.resolve_root(args.root, tool="lint-shipped-pruned-path")
    slice_source = Path(args.slice_source) if args.slice_source else root / DEFAULT_SLICE_REL
    schema_source = (
        Path(args.schema_source) if args.schema_source else root / DEFAULT_SCHEMA_REL
    )
    install_source = (
        Path(args.install_source) if args.install_source else root / DEFAULT_INSTALL_REL
    )
    workflows_source = (
        Path(args.workflows_source)
        if args.workflows_source
        else root / DEFAULT_WORKFLOWS_REL
    )

    # This print flag exits before the slice and schema reads below, so a query about the
    # workflow set can neither be refused by, nor be diagnosed against, a source it never
    # consults. The two older print flags keep their position, so their behaviour is
    # unchanged.
    if args.print_never_shipped_set:
        never_shipped = _establish_never_shipped(install_source, workflows_source)
        if never_shipped is None:
            return 1
        for basename in never_shipped:
            print(basename)
        return 0

    try:
        slice_text = slice_source.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(
            f"lint-shipped-pruned-path: could not read slice source {slice_source}: "
            f"{exc}",
            file=sys.stderr,
        )
        return 1
    try:
        targets = parse_prune_targets(slice_text)
    except PruneParseError as exc:
        print(
            f"lint-shipped-pruned-path: could not establish a prune set from "
            f"{slice_source}: {exc}; auditing nothing",
            file=sys.stderr,
        )
        return 1

    # Derive the docs.* exemption set from the schema and subtract it from the prune
    # set (issue #1309). A prune target that is also a documented docs.* default names
    # the consumer's OWN docs path, which is expected to exist in their checkout — the
    # opposite of the vanishing-path premise this lint guards. The read fails closed:
    # an absent/unreadable file is an OSError, an unparseable/keyless/non-object schema
    # is a DocsDefaultsParseError, and either refuses non-zero naming the schema — an
    # unestablished exemption set is never silently an empty one.
    try:
        schema_bytes = schema_source.read_bytes()
    except OSError as exc:
        print(
            f"lint-shipped-pruned-path: could not read schema source {schema_source}: "
            f"{exc}; auditing nothing",
            file=sys.stderr,
        )
        return 1
    try:
        docs_defaults = parse_docs_defaults(schema_bytes)
    except DocsDefaultsParseError as exc:
        print(
            f"lint-shipped-pruned-path: could not establish a docs.* exemption set "
            f"from {schema_source}: {exc}; auditing nothing",
            file=sys.stderr,
        )
        return 1

    # Membership is EQUALITY after trailing-slash normalization, never prefix
    # containment — a coarse prune target (`docs`) must not be exempted by a finer
    # default (`docs/internal/`), which would silently empty the guard.
    exempt = [t for t in targets if t.rstrip("/") in docs_defaults]
    targets = [t for t in targets if t.rstrip("/") not in docs_defaults]

    # The empty-post-exemption-set refusal is the fail-open shape one level down from
    # parse_prune_targets' own empty-set refusal: an exemption set covering every prune
    # target would leave nothing forbidden and audit the shipped surface against no
    # targets at all. It fires BEFORE either print branch, so --print-prune-set never
    # prints an empty set with exit 0. It is independent of the later `if not audited:`
    # population floor, which covers a different fail-open shape.
    if not targets:
        print(
            "lint-shipped-pruned-path: the docs.* exemption set derived from "
            f"{schema_source} covers every prune target derived from {slice_source}, "
            "leaving the forbidden set empty — refusing to audit the shipped surface "
            "against no targets",
            file=sys.stderr,
        )
        return 1

    if args.print_exempt_set:
        for target in exempt:
            print(target)
        return 0

    if args.print_prune_set:
        for target in targets:
            print(target)
        return 0

    # Derive the never-shipped workflow set (issue #1402), before the enumeration below
    # so an unestablished declaration refuses without auditing a single file.
    never_shipped = _establish_never_shipped(install_source, workflows_source)
    if never_shipped is None:
        return 1
    never_shipped_matcher = _never_shipped_matcher(never_shipped)

    try:
        population = _pop.enumerate_population(
            root,
            Path(args.files_from) if args.files_from else None,
            ls_files_argv=_pop.LS_FILES_INDEX,
        )
    except EnumerationError as exc:
        print(f"lint-shipped-pruned-path: enumeration unusable: {exc}", file=sys.stderr)
        return 1

    audited = [path for path in population if is_audited(path)]
    # The enumeration floors on zero TOTAL index paths, before this narrowing. The
    # audited subset needs its own floor: an empty one reads the loop zero times and
    # would return 0 with `audited 0 of 0` — a clean pass over an unchecked shipped
    # surface, which is this lint's own fail-open class one level up. Reachable by a
    # renamed AUDITED_PREFIXES, a relocated tree, or a --files-from list naming no
    # such path. The driver asserts a positive count over the real tree; that floor
    # is the driver's, so the tool carries this one to hold its stated contract for
    # every caller.
    if not audited:
        print(
            "lint-shipped-pruned-path: the enumeration selected no file under "
            f"{' or '.join(AUDITED_PREFIXES)} — refusing to report clean over an "
            "unaudited shipped surface",
            file=sys.stderr,
        )
        return 1

    # Derive the vendored-skill directory scope for the CLAUDE.md-token ban (issue
    # #1401). An empty derivation is a fail-open shape — no directory would be scanned
    # for the token — so it refuses non-zero naming the empty population, the same
    # posture as the empty-prune-set and empty-audited refusals above.
    try:
        vendored_dirs = derive_vendored_skill_dirs(root)
    except VendoredScopeError as exc:
        print(
            f"lint-shipped-pruned-path: could not establish the vendored-skill scope "
            f"under {root}: {exc}; auditing nothing",
            file=sys.stderr,
        )
        return 1
    if not vendored_dirs:
        print(
            "lint-shipped-pruned-path: no skills/<name>/SKILL.md under "
            f"{root} carries the vendored-provenance sentence "
            f"{_PROVENANCE_SENTENCE!r} — refusing to audit the vendored-skill surface "
            "against an empty derived population",
            file=sys.stderr,
        )
        return 1

    findings: list[str] = []
    skipped: list[tuple[str, str]] = []
    read_ok = 0
    for relative in audited:
        text, skip_reason = _pop.read_source(root / relative, skip_nul=_SKIP_NUL)
        if text is None:
            skipped.append((relative, skip_reason or "unknown"))
            continue
        read_ok += 1
        for number, hit in scan_text(text, targets):
            findings.append(
                f"{relative}:{number}: references pruned path '{hit}' with no "
                "pruned-path-ok marker"
            )
        for number, cite in scan_citations(text):
            findings.append(
                f"{relative}:{number}: cites PRFlow-internal '{cite}' (issue/PR or "
                "acceptance-criterion reference) with no pruned-path-ok marker"
            )
        for number, workflow in _scan(text, never_shipped_matcher):
            findings.append(
                f"{relative}:{number}: references never-shipped workflow '{workflow}' "
                "(PRFlow's own, which the installer copies into no consumer, so this "
                "cannot point at a file the installer put there) with no "
                "pruned-path-ok marker"
            )
        # The internal-identifier ban (issue #2114) applies to the whole audited
        # population, not only the vendored-skill dirs: any shipped body naming a
        # PRFlow development-harness identifier resolves against a marker or tool the
        # consumer's tree does not carry.
        for number, identifier in scan_internal_identifiers(text):
            findings.append(
                f"{relative}:{number}: references PRFlow-internal identifier "
                f"'{identifier}' (a development-harness marker or tool the installer "
                "ships into no consumer, so it names nothing in their tree) with no "
                "pruned-path-ok marker"
            )
        # The CLAUDE.md-token ban applies only inside the derived vendored-skill dirs
        # (issue #1401): every other skills/**+agents/** file may name CLAUDE.md as the
        # consumer's own project memory, which is correct usage and must not be reported.
        normalized = relative.replace("\\", "/")
        if any(normalized.startswith(d) for d in vendored_dirs):
            for number, tok in scan_vendored_claude_md(text):
                findings.append(
                    f"{relative}:{number}: references PRFlow's own '{tok}' (a vendored "
                    "skill body ships verbatim into a consumer, so it names that repo's "
                    "own project memory) with no pruned-path-ok marker"
                )

    for finding in findings:
        print(finding)
    for relative, reason in skipped:
        print(f"lint-shipped-pruned-path: SKIPPED {relative}: {reason}", file=sys.stderr)
    print(
        f"lint-shipped-pruned-path: audited {read_ok} of {len(audited)} files"
        + (f" ({len(skipped)} skipped)" if skipped else "")
        + f"; prune set: {' '.join(targets)}"
    )
    if skipped:
        print(
            f"lint-shipped-pruned-path: {len(skipped)} selected path(s) could not be "
            "audited — refusing to report clean; see the SKIPPED lines above",
            file=sys.stderr,
        )
        return 1
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
