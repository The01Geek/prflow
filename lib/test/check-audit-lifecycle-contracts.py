#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Reconcile the create-issue audit lifecycle's prose against machine-consumed contracts.

Issue #795. Two reconciliations that a `git grep` for a sentence could never perform,
plus the measurement figure derived from the second:

  read-backs   The multi-line read-back enumeration carried by `scripts/issue-audit-state.py`'s
               `TWO-CLASS CLI CONTRACT` docstring is compared against `_MULTILINE_READBACKS`
               — the set the module's own emission machinery dispatches on — and every name
               in that set is required to be a subcommand the parser actually registers.
               So the guard grades the docstring against what the tool DOES, not against
               its own wording, and a name in the prose that no parser choice backs is RED.

  sequence     Every state-owner invocation named in `step-3-6-audit.md`'s ordered
               call-sequence paragraph is required to be a registered subcommand (the prose
               can never name a call the tool would not accept), and the count of
               unconditional calls that paragraph plus `step-4-present-create.md` jointly
               mandate is reported.

  fenced-      The REVERSE of `sequence` (issue #1466): every state-owner subcommand invoked
  completeness inside a ```bash fence of either reference file is required to be named in the
               call sequence, in the declared `_FENCE_EXEMPT` set, or in `_CONDITIONAL` — so a
               call the documents mandate can no longer go missing from the sequence while the
               completeness sentence beneath it still claims otherwise. It NARROWS the gap
               rather than closing it: its reach is the ```bash fences alone, and a sizeable
               minority of the sequence's calls are written in prose backticks instead. See
               the function's own docstring for that disclosed residual.

  figure       The per-round measurement figure the suite pins, derived from `sequence`
               rather than hand-transcribed — so a later addition of an unconditional call
               MOVES the figure instead of leaving a stale literal behind.

FAIL CLOSED, NEVER CLEAN-ZERO. Both prose readers parse a human-editable markdown file, so
each refuses rather than reporting an EMPTY result: no candidate section, more than one
candidate section, or zero invocations extracted is a named RED breadcrumb. A rewrap or a
duplicated heading must not make a check pass vacuously and freeze the figure.

The scope of that guarantee is exactly "not empty", and no more. A DEGENERATE-but-nonzero
paragraph — one that names a single registered subcommand, or repeats one — still extracts
successfully and still reports a figure, so the zero-guard is not a proof that the
paragraph is a meaningful sequence. Distinctness deliberately is NOT required, because the
real sequence legitimately names `query-draft-binding` twice. What catches a degenerate
rewrite is the figure moving, which is why the figure is reported on the success path
rather than only on failure.

Exit 0 with a report on stdout when every reconciliation holds; exit 1 with the failing
reconciliation named on stderr otherwise.
"""

from __future__ import annotations

import argparse
import ast
import builtins
import contextlib
import importlib.util
import inspect
import io
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
IAS = REPO / "scripts" / "issue-audit-state.py"
STEP36 = REPO / "skills" / "create-issue" / "references" / "step-3-6-audit.md"
STEP4 = REPO / "skills" / "create-issue" / "references" / "step-4-present-create.md"

# The paragraph that opens the ordered call sequence. A closed anchor, not a fuzzy match:
# exactly one line must carry it, so a duplicated or renamed heading is RED rather than
# silently selecting the first hit.
_SEQUENCE_ANCHOR = "**The call sequence, in order.** The normal clean run:"

# The docstring section carrying the read-back enumeration.
_DOCSTRING_ANCHOR = "TWO-CLASS CLI CONTRACT"

# Calls the prose marks conditional on the run's shape; excluded from the unconditional
# figure by name, and the prose is required to still mark them so (checked below).
# `record-adjudication-render` belongs here for a reason worth stating: it is not merely
# skippable on a clean run, it is REFUSED there — the state owner fails it `no-records`
# when the round graded no advisory or invalid finding, and `resolve_calibration` answers
# `render=none` with no trigger for exactly that shape. Listing it in the unconditional
# ordered sequence therefore prescribed a call that cannot succeed on the clean path.
_CONDITIONAL = ("record-offer", "query-adjudication-records",
                "record-adjudication-render")

# Fenced state-owner invocations the reference files gate on a run-shape condition, so
# the clean single-round run never makes them and the unconditional sequence must not name
# them. This is the reverse check's declared exemption set — the counterpart of `_CONDITIONAL`
# for calls that DO appear in a ```bash fence. Each member, and why it is here:
#   write-dispatch-scope    written only on `kind=targeted`, which a discovery round is not.
#   record-finding-evidence writes a per-finding record, which a zero-finding round never has.
# A member is required to be a registered subcommand and is required NOT to be named in the
# sequence, so this set and the sequence can never disagree about whether a call is
# conditional. `_CONDITIONAL` members need no entry here: they are a legal home of their own.
_FENCE_EXEMPT = ("write-dispatch-scope", "record-finding-evidence")

# The fence enumeration is REUSED from the repository's existing Markdown scanner rather than
# reimplemented, so what counts as a scanned block is defined in exactly one place.
_ECH = Path(__file__).resolve().parent / "extract-command-heads.py"

# The state owner as a fence writes it: `python3 <anchor>/../../scripts/issue-audit-state.py`.
_STATE_OWNER_SCRIPT = "issue-audit-state.py"

# The extractor helpers the reverse arm composes. Proved present at load (see
# `_load_extractor`) so a rename in that general-purpose scanner is a named refusal here
# rather than an AttributeError traceback.
_EXTRACTOR_API = ("_fenced_bash_blocks", "_join_continuations", "_strip_case_patterns",
                  "_strip_comments_and_heredocs", "_boundary_units", "_tokenize",
                  "_normalize", "_helper_basename")


class Refusal(Exception):
    """A reconciliation could not be established — never reported as a clean result."""


def _load_module(path: Path = IAS, name: str = "_ias795"):
    """Load a bundled helper as a module. Deliberately NOT cached: the planted-defect
    test rows call this for a FRESH object per row and mutate its constants, so a shared
    cached module would leak one row's planted defect into the next."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise Refusal(f"could not load {path.relative_to(REPO)} as a module "
                      "(unloadable spec)")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - ANY load failure is a Refusal, not a traceback
        # The spec guard above does NOT cover a missing file: `spec_from_file_location`
        # returns a fully-populated spec for a path that does not exist, and the failure
        # surfaces here as `FileNotFoundError`. `main()` catches only `Refusal`, so without
        # this arm a moved or renamed helper — and equally a SyntaxError or a raising
        # module-level import in the general-purpose scanner this file now reuses — escapes
        # as a bare traceback: the one shape this file's own "FAIL CLOSED, NEVER CLEAN-ZERO"
        # contract promises never to produce.
        raise Refusal(f"could not load {path.relative_to(REPO)} as a module "
                      f"({type(exc).__name__}: {exc})") from exc
    return module


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise Refusal(f"could not read {path.relative_to(REPO)}: {exc}") from exc


def _sole_paragraph(text: str, anchor: str, where: str) -> str:
    """The single paragraph following `anchor`, or a refusal naming why not."""
    lines = text.splitlines()
    hits = [i for i, line in enumerate(lines) if anchor in line]
    if not hits:
        raise Refusal(f"{where}: no line carries the anchor {anchor!r} — the section was "
                      "renamed, rewrapped, or removed; refusing rather than reporting an "
                      "empty extraction")
    if len(hits) > 1:
        raise Refusal(f"{where}: {len(hits)} lines carry the anchor {anchor!r}; exactly one "
                      "candidate is required, so a duplicated heading cannot make this "
                      "check pass against the wrong paragraph")
    start = hits[0] + 1
    while start < len(lines) and not lines[start].strip():
        start += 1
    end = start
    while end < len(lines) and lines[end].strip():
        end += 1
    body = "\n".join(lines[start:end]).strip()
    if not body:
        raise Refusal(f"{where}: the paragraph after {anchor!r} is empty")
    return body


# The shape a state-owner subcommand name takes. Used to tell "a token that is TRYING to
# be a subcommand and is misspelled" (refuse) from "ordinary backticked prose" (skip).
_SUBCOMMAND_SHAPED = re.compile(r"\A(?:query|record|init|emit|check)-[a-z0-9-]+\Z")


def _backticked(text: str) -> list[str]:
    """Every backtick-quoted token in `text`, in document order."""
    return re.findall(r"`([^`]+)`", text)


def _invocations(text: str, registered: frozenset[str], where: str) -> list[str]:
    """The registered subcommand names a prose passage invokes, in document order.

    A name called twice contributes twice: the count is of invocations, not of distinct
    subcommands.
    """
    found = []
    for token in _backticked(text):
        parts = token.split()
        if not parts:
            continue
        if parts[0] in registered:
            found.append(parts[0])
        elif _SUBCOMMAND_SHAPED.match(parts[0]):
            # REFUSE, do not skip. Selecting only registered names would make the
            # "the prose can never name a call the tool would not accept" guarantee
            # vacuous: a typo (`record-covrage`) would be filtered out silently, the
            # derived figure would drop by one, and the success line would still read
            # "every one a registered subcommand" over prose prescribing a call argparse
            # rejects. Only a token SHAPED like a state-owner subcommand trips this, so
            # ordinary backticked prose (`--round`, `next_call=none`) is unaffected.
            raise Refusal(
                f"{where}: {parts[0]!r} is shaped like a state-owner subcommand but is "
                "not registered by build_parser() — the prose names a call the tool "
                "would refuse (a typo, a rename, or a removed subcommand)")
    if not found:
        raise Refusal(f"{where}: zero state-owner invocations extracted. A clean zero here "
                      "would freeze the derived figure and let the reconciliation pass "
                      "vacuously, so it is a refusal")
    return found



def _subparser_of(parser, name):
    """The subparser registered under `name`, or None."""
    for action in parser._actions:  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            return action.choices.get(name)
    return None


# The builtins a call may name and still be provably unable to reach a module-level
# save_state — every builtin function, type, and exception (`len`, `print`, `sorted`,
# `SystemExit`, `ValueError`, …). `getattr` is safe in its BARE-name value form
# `getattr(x, y)`; the dangerous form `getattr(x, y)()` is a Call-as-callee, caught by the
# indirect-dispatch arm below regardless.
_SAFE_BUILTIN_CALLS = frozenset(dir(builtins))


def _module_level_names(tree):
    """(functions_by_name, safe_leaf_names) for the module. `functions_by_name` are the
    function defs the walk FOLLOWS — every module-level def PLUS every nested/closure helper
    they define, indexed by name, so a bare-name call to a helper the source statically
    carries is followed (proving whether it reaches save_state) rather than flagged
    unresolvable. `safe_leaf_names` are names a call may reference and still reach no
    followable function by name — imported names and module-level class names (a class
    instantiation cannot BE the `save_state` function, e.g. `StateError(...)`). A name collision across scopes
    over-approximates by keeping one body; that only ever follows MORE, which is the
    fail-closed direction for an unreachability proof.
    """
    functions = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions[node.name] = node
    safe = set(_SAFE_BUILTIN_CALLS)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            safe.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                safe.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                safe.add(alias.asname or alias.name)
    return functions, safe


def check_readonly_complement(module, registered, report):
    """Every read-only-classified subcommand's handler must be UNABLE to reach `save_state`
    through the transitive call graph of module-level functions — not merely have it absent
    from the handler's own source text (issue #1040). A source-text-only check would pass a
    handler that reaches save_state one hop away through a helper, the fail-open shape this
    exists to prevent.

    The walk's closed set is module-level functions; its complement is named and handled,
    never left silent. A call target the walk cannot resolve to a module-level function — a
    bare-name alias/closure/nested helper, or an indirect dispatch through a table or
    getattr — makes the check FAIL CLOSED for that subcommand, reporting the unresolvable
    call site rather than reporting clean. An attribute/method call reaches no module-level
    function by name (module-level functions are called as bare names), so it cannot be
    `save_state` and is safe. A read-only-classified handler is proved safe only when every
    call on its transitive path resolved.
    """
    # Analyze the PASSED module's own source (not IAS directly), so a fixture module drives
    # this check exactly like check_emitting_complement — the positive controls in the test
    # suite load a crafted module and expect a Refusal.
    try:
        source = inspect.getsource(module)
    except (OSError, TypeError) as exc:
        raise Refusal(f"readonly-complement: could not read the module source of "
                      f"{getattr(module, '__name__', module)!r}: {exc}") from exc
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise Refusal(f"readonly-complement: could not parse the module source: "
                      f"{exc}") from exc
    functions, safe = _module_level_names(tree)

    parser = module.build_parser()
    name_to_handler = {}
    for action in parser._actions:  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            for name, sub in action.choices.items():
                fn = sub._defaults.get("func")  # noqa: SLF001
                name_to_handler[name] = getattr(fn, "__name__", None)

    predicate = module._is_read_only  # noqa: SLF001
    readonly = sorted(n for n in registered if predicate(n))
    if not readonly:
        raise Refusal("readonly-complement: the read-only predicate selected NO registered "
                      "subcommand, so the critical section would wrap every command and this "
                      "complement check would be vacuous")

    # Module-level constants (name -> value node), so a read-only handler that dispatches
    # over a module-level TABLE of producers (query-boundary's `for _, produce in
    # _BOUNDARY_PRODUCERS: produce(...)`) is RESOLVED through the constant rather than
    # failed closed: name-reachability propagates through the constant's value into the
    # producer lambdas and the module functions they name.
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    constants[tgt.id] = node.value

    def _targets_name(target, name):
        """True iff an assignment/for target binds `name` (a Name, or a Tuple/List of
        them)."""
        if isinstance(target, ast.Name):
            return target.id == name
        if isinstance(target, (ast.Tuple, ast.List)):
            return any(_targets_name(el, name) for el in target.elts)
        return False

    def _local_call_resolvable(node, name):
        """A bare-name call to a LOCAL `name` is resolvable only when `name` is bound within
        `node` from a source that references a module-level function or constant — then the
        call target is reached through name-propagation over that source (query-boundary's
        `for _, produce in _BOUNDARY_PRODUCERS` binds `produce` from a module constant). A
        name bound only from a getattr()/subscript/opaque source, or not bound at all (a
        parameter or callback), is unresolvable and fails the subcommand closed.
        """
        for sub in ast.walk(node):
            srcs = []
            if isinstance(sub, ast.For) and _targets_name(sub.target, name):
                srcs.append(sub.iter)
            elif isinstance(sub, ast.Assign) and any(
                    _targets_name(t, name) for t in sub.targets):
                srcs.append(sub.value)
            elif isinstance(sub, ast.comprehension) and _targets_name(sub.target, name):
                srcs.append(sub.iter)
            for src in srcs:
                for ref in ast.walk(src):
                    if isinstance(ref, ast.Name) and (
                            ref.id in functions or ref.id in constants):
                        return True
        return False

    def _analyze_node(node):
        """(module-level names referenced in Load context, has-computed-callee,
        [unresolvable local-call names]) in node's whole subtree — nested defs and lambdas
        included, so a helper or a producer lambda is not a blind spot. A computed callee
        (getattr(...)() / table[key]()) and a bare-name call to an unresolvable local
        (a getattr-aliased callable) are the two shapes the name walk cannot resolve.
        """
        names = set()
        has_computed = False
        unresolvable = []
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                if sub.id in functions or sub.id in constants:
                    names.add(sub.id)
            elif isinstance(sub, ast.Call):
                fn = sub.func
                if isinstance(fn, ast.Name):
                    nm = fn.id
                    if (nm != "save_state" and nm not in functions
                            and nm not in constants and nm not in safe
                            and not _local_call_resolvable(node, nm)):
                        unresolvable.append(nm)
                elif not isinstance(fn, ast.Attribute):
                    has_computed = True
        return names, has_computed, unresolvable

    def analyze(subcmd, handler):
        # Transitive name-reachability over module-level functions AND constants. A read-only
        # handler is proved safe only when `save_state` is unreachable by name AND no
        # reachable function contains a computed (unresolvable) callee. This is sound by
        # name — a handler that reaches save_state through any bare-name path (a call, a
        # callback passed by name, a nested def, or a producer table) names it and is
        # caught; the one residue the name walk cannot see, a getattr('save_state')()
        # string dispatch, is caught by the computed-callee arm.
        seen = set()
        queue = [handler]
        while queue:
            nm = queue.pop()
            if nm in seen:
                continue
            seen.add(nm)
            node = functions.get(nm)
            is_func = node is not None
            if node is None:
                node = constants.get(nm)
            if node is None:
                continue
            names, has_computed, unresolvable = _analyze_node(node)
            if is_func and has_computed:
                raise Refusal(
                    f"readonly-complement: read-only subcommand {subcmd!r} reaches an "
                    f"indirect dispatch (a computed callee) in {nm!r}; the walk cannot "
                    "prove that path does not reach save_state — fail closed")
            if is_func and unresolvable:
                raise Refusal(
                    f"readonly-complement: read-only subcommand {subcmd!r} makes an "
                    f"unresolvable call {unresolvable[0]!r}() in {nm!r} (a local bound from "
                    "no module-level function or constant — a getattr alias, a closure, or a "
                    "callback); a read-only handler is proved safe only when every call "
                    "resolves")
            if "save_state" in names:
                raise Refusal(
                    f"readonly-complement: read-only subcommand {subcmd!r} reaches "
                    f"save_state (through {nm}); the read-only predicate has misclassified "
                    "a mutating subcommand as read-only")
            queue.extend(names - seen)

    for name in readonly:
        handler = name_to_handler.get(name)
        if handler is None or handler not in functions:
            raise Refusal(
                f"readonly-complement: read-only subcommand {name!r} maps to handler "
                f"{handler!r}, which is not a module-level function — the walk cannot begin, "
                "so the classification is unproven")
        analyze(name, handler)

    report.append(f"readonly-complement: all {len(readonly)} read-only subcommands proved "
                  "unable to reach save_state through the module-level call graph")


def check_readbacks(module, registered, report):
    """The docstring's read-back enumeration vs. the dispatched `_MULTILINE_READBACKS`."""
    doc = module.__doc__ or ""
    if _DOCSTRING_ANCHOR not in doc:
        raise Refusal("read-backs: the module docstring carries no "
                      f"{_DOCSTRING_ANCHOR!r} section")
    section = doc.split(_DOCSTRING_ANCHOR, 1)[1]
    named = {t for t in _backticked(section) if t in registered and t.startswith("query-")}
    dispatched = set(module._MULTILINE_READBACKS)  # noqa: SLF001
    unbacked = sorted(dispatched - registered)
    if unbacked:
        raise Refusal("read-backs: _MULTILINE_READBACKS names "
                      f"{unbacked} which the parser does not register — the set the "
                      "emission machinery dispatches on must be a subset of the real "
                      "subcommand vocabulary")
    missing = sorted(dispatched - named)
    if missing:
        raise Refusal("read-backs: the TWO-CLASS CLI CONTRACT docstring does not name "
                      f"{missing}, which _MULTILINE_READBACKS dispatches as multi-line. "
                      "The prose enumeration and the dispatched set must agree")
    # The docstring↔dispatched comparison above is a prose reconciliation. Anchor the same
    # guarantee on BEHAVIOR too, so the arm does not rest on documentation presence alone:
    # every excluded subcommand must really be one the emitter refuses to append to, and
    # `_emit_next_call` raises on an excluded name, which is the executable boundary this
    # arm grades against; the complement direction — every NON-excluded subcommand really
    # being one the emitter can serve — is `check_emitting_complement` below.
    excluded = set(module._NEXT_CALL_EXCLUDED)  # noqa: SLF001
    if not dispatched <= excluded:
        raise Refusal("read-backs: a multi-line read-back is missing from "
                      f"_NEXT_CALL_EXCLUDED ({sorted(dispatched - excluded)}) — a "
                      "multi-line answer would gain a trailing next_call= line")
    for name in sorted(excluded):
        try:
            module._emit_next_call(name, None, None)  # noqa: SLF001
        except AssertionError:
            continue
        except Exception:  # noqa: BLE001
            raise Refusal(f"read-backs: _emit_next_call({name!r}) did not refuse the way "
                          "the exclusion predicate requires") from None
        raise Refusal(f"read-backs: _emit_next_call accepted the excluded {name!r}; the "
                      "exclusion set and the emitter's own guard disagree")
    unbacked_exclusions = sorted(excluded - registered)
    if unbacked_exclusions:
        raise Refusal(f"read-backs: _NEXT_CALL_EXCLUDED names {unbacked_exclusions}, which "
                      "the parser does not register")
    report.append(f"read-backs: {len(dispatched)} multi-line read-backs, docstring "
                  "enumeration reconciled against the dispatched set, and every excluded "
                  "subcommand refused by the emitter's own guard")


def check_emitting_complement(module, registered, report):
    """Every NON-excluded subcommand must really be one the emitter can serve.

    The complement direction, and the one whose absence let a reproducible crash ship: the
    exclusion arm above walks `_NEXT_CALL_EXCLUDED` and confirms the emitter refuses each
    member, which says nothing about the ~30 subcommands that are supposed to EMIT. The
    emitter reads namespace fields off `args`, so a subcommand whose parser registers none
    of them — `query-nonce`, which exists to recover the nonce and therefore takes no
    `--nonce` — crashed with an `AttributeError` on the recovery path it exists for.

    Driven off `registered_subcommands()` rather than a hand-list, so a subcommand added
    later without one of those flags fails at the desk instead of in a run. The probe uses
    an empty namespace: it asserts the emitter tolerates every field being ABSENT, which is
    the structural property, not that any particular answer is produced.
    """
    excluded = set(module._NEXT_CALL_EXCLUDED)  # noqa: SLF001
    emitting = sorted(registered - excluded)
    if not emitting:
        raise Refusal("emitting-complement: no subcommand emits next_call= at all — the "
                      "exclusion set covers the whole registered vocabulary, which would "
                      "turn the answer channel off entirely")
    for name in emitting:
        args = argparse.Namespace(slug="_probe795")
        try:
            # The probe's own `next_call=` line is captured, not printed: this guard's
            # stdout IS its report (run.sh parses the figures out of it), so 30 probe
            # lines would corrupt the surface being read.
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                module._emit_next_call(name, args, None)  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            raise Refusal(
                f"emitting-complement: _emit_next_call({name!r}) raised "
                f"{type(exc).__name__}: {exc} on a namespace carrying no optional field. "
                "The emitter must depend on no parser shape it does not itself check — "
                "read each field with getattr(), or add the subcommand to "
                "_NEXT_CALL_EXCLUDED") from None
    report.append(f"emitting-complement: all {len(emitting)} non-excluded subcommands "
                  "tolerate an absent namespace field")


def check_round_defaulted(module, registered, report):
    """`_ROUND_DEFAULTED` must match the subcommands whose `--round` is actually optional.

    The constant is declared as THE closed set and reads as authoritative, but nothing
    consumed it: flipping a `--round` to `required=False` without adding the
    `_require_named_round` call — the exact slip that would silently operate on the wrong
    round — passed every gate. Reconcile it against the parser, a machine-consumed
    contract, exactly as the read-back arm reconciles `_MULTILINE_READBACKS`.

    Two halves, because the parser half ALONE does not close the slip this docstring
    names. Set-vs-parser optionality says the flag may be omitted; it says nothing about
    whether the handler then resolves the round. A member added to both the constant and
    the parser's optional set, with the resolver call forgotten, passes the first half and
    runs with `args.round is None` into round-keyed guards — the very outcome advertised
    as closed. So the second half walks each member's handler source and requires an
    actual `_require_named_round` / `_resolve_named_round` call.
    """
    parser = module.build_parser()
    optional_round = set()
    for action in parser._actions:  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            for name, sub in action.choices.items():
                for a in sub._actions:  # noqa: SLF001
                    if "--round" in a.option_strings and not a.required:
                        optional_round.add(name)
    declared = set(module._ROUND_DEFAULTED)  # noqa: SLF001
    if declared - registered:
        raise Refusal(f"round-defaulted: _ROUND_DEFAULTED names "
                      f"{sorted(declared - registered)}, which the parser does not register")
    if declared != optional_round:
        raise Refusal(
            "round-defaulted: _ROUND_DEFAULTED and the parser disagree about which "
            f"subcommands have an optional --round. Declared-not-optional: "
            f"{sorted(declared - optional_round)}; optional-not-declared: "
            f"{sorted(optional_round - declared)}. A subcommand whose --round became "
            "optional without a _require_named_round call would silently operate on a "
            "round the caller never named")
    # Second half: each member's handler must actually resolve the round.
    missing_resolver = []
    for name in sorted(declared):
        func = getattr(_subparser_of(parser, name), "get_default", lambda _k: None)("func")
        if func is None:
            raise Refusal(f"round-defaulted: {name!r} registers no handler to inspect, so "
                          "the resolver-call half cannot be established")
        try:
            source = inspect.getsource(func)
        except (OSError, TypeError) as exc:
            raise Refusal(f"round-defaulted: could not read {name!r}'s handler source "
                          f"({exc}), so the resolver-call half cannot be established") from exc
        if "_require_named_round" not in source and "_resolve_named_round" not in source:
            missing_resolver.append(name)
    if missing_resolver:
        raise Refusal(
            f"round-defaulted: {missing_resolver} are in _ROUND_DEFAULTED with an optional "
            "--round but their handlers call neither _require_named_round nor "
            "_resolve_named_round, so an omitted --round reaches the round-keyed guards as "
            "None instead of the resolved round")
    report.append(f"round-defaulted: {len(declared)} state-defaulted subcommands, "
                  "reconciled against the parser's own required-ness AND against each "
                  "handler's actual resolver call")


def check_next_action_routing_totality(module, report):
    """Every `_NEXT_ACTIONS` member is routed by one of the two `next_call=` tables.

    This is the reconciliation whose ABSENCE shipped the `dispatch-retry-same-arm` defect:
    that token was in neither `_DISPATCH_ROUTE` nor `_ACTION_NOT_A_CALL`, so it fell through
    to the resolver's generic tail and emitted `next-action-unestablished` while two shipped
    sites documented `dispatch-arm-unestablished`. Both lines parsed and the suite stayed
    green. A closed set whose totality is enforced only by comment is not enforced.
    """
    actions = getattr(module, "_NEXT_ACTIONS", None)
    if not actions:
        raise Refusal("next-action-routing: scripts/issue-audit-state.py exposes no "
                      "non-empty _NEXT_ACTIONS to reconcile against")
    routed = set(getattr(module, "_DISPATCH_ROUTE", {})) | \
        set(getattr(module, "_ACTION_NOT_A_CALL", {}))
    if not routed:
        raise Refusal("next-action-routing: neither _DISPATCH_ROUTE nor _ACTION_NOT_A_CALL "
                      "could be read, so totality cannot be established")
    unrouted = sorted(set(actions) - routed)
    if unrouted:
        raise Refusal(
            f"next-action-routing: {unrouted} are _NEXT_ACTIONS members routed by neither "
            "_DISPATCH_ROUTE nor _ACTION_NOT_A_CALL, so query-next-action answers them with "
            "the generic next-action-unestablished tail instead of a decided next call")
    stale = sorted(routed - set(actions))
    if stale:
        raise Refusal(
            f"next-action-routing: {stale} are routed but are not _NEXT_ACTIONS members — "
            "a renamed or removed answer token left a dead routing entry behind")
    report.append(f"next-action-routing: all {len(actions)} _NEXT_ACTIONS members routed, "
                  "with no dead routing entry")


def check_flag_vocabulary(module, parser, registered, report):
    """Every member of the `next_call=` flag vocabularies is a REAL registered option.

    `_CALLER_SUPPLIED_FLAGS` and `_NEXT_CALL_PATH_FLAGS` are matched by literal flag string
    against operands the renderer is about to emit. A member that names no registered
    option is not an error anything notices — it simply never matches, so the protection it
    encodes is silently absent. That fails OPEN in the direction that matters: a
    `_CALLER_SUPPLIED_FLAGS` entry stale after a flag rename stops suppressing the value,
    and the renderer starts filling in an operand whose whole point was that the caller —
    not the state — decides it. Reconciling against the parser is what turns a rename into
    a red check instead of a quiet behavior change (issue #795 shadow review).
    """
    option_strings = set()
    for name in sorted(registered):
        sub = _subparser_of(parser, name)
        if sub is None:
            continue
        for action in sub._actions:  # noqa: SLF001 - argparse exposes no public accessor
            option_strings.update(action.option_strings)
    if not option_strings:
        raise Refusal("flag-vocabulary: no option strings could be read off any subparser, "
                      "so the vocabularies cannot be reconciled")
    checked = 0
    for vocab_name in ("_CALLER_SUPPLIED_FLAGS", "_NEXT_CALL_PATH_FLAGS"):
        vocab = getattr(module, vocab_name, None)
        if not vocab:
            raise Refusal(f"flag-vocabulary: {vocab_name} is absent or empty, so it cannot "
                          "be reconciled against the parser")
        unknown = sorted(f for f in vocab if f not in option_strings)
        if unknown:
            raise Refusal(
                f"flag-vocabulary: {unknown} appear in {vocab_name} but are registered on no "
                "subparser — the entry matches nothing, so the rendering rule it encodes is "
                "silently not in force")
        checked += len(vocab)
    report.append(f"flag-vocabulary: all {checked} members of _CALLER_SUPPLIED_FLAGS and "
                  f"_NEXT_CALL_PATH_FLAGS are registered options")


def check_sequence(registered, report):
    """The ordered call sequence vs. the invocations the helper accepts. Returns the
    invocation list itself — with multiplicity, in document order — so its length is the
    unconditional joint count and `check_fenced_completeness` can grade the same parse
    rather than repeating it."""
    seq_text = _read(STEP36)
    paragraph = _sole_paragraph(seq_text, _SEQUENCE_ANCHOR, "sequence")
    # `_invocations` REFUSES on a subcommand-shaped token that is not registered, so the
    # "the prose can never name a call the tool would not accept" guarantee is genuinely
    # enforced at extraction and a second `set(named) - registered` check here could never
    # fire. (An earlier form merely SKIPPED such a token, which made the same sentence
    # vacuous — a typo dropped the name, lowered the derived figure by one, and left the
    # success line claiming "every one a registered subcommand" over prose prescribing a
    # call argparse rejects. Skipping is selection, not validation.)
    named = _invocations(paragraph, registered, "sequence")
    for cond in _CONDITIONAL:
        if cond in named:
            raise Refusal(f"sequence: {cond!r} is conditional on the run's shape and must "
                          "not sit in the unconditional ordered sequence")
        if f"`{cond}`" not in seq_text:
            raise Refusal(f"sequence: {cond!r} is no longer named anywhere in "
                          "step-3-6-audit.md, so its conditional status is unstated")
    # The joint scope: step-4's own mandated calls that the sequence attributes to it.
    step4 = _read(STEP4)
    if "query-draft-binding" not in step4:
        raise Refusal("sequence: step-4-present-create.md no longer mandates the "
                      "query-draft-binding re-detect the sequence's joint scope counts")
    report.append(f"sequence: {len(named)} unconditional invocations jointly mandated, "
                  "every one a registered subcommand")
    return named


def _load_extractor():
    """The Markdown scanner, with the `_EXTRACTOR_API` names proved present before use.

    The reuse is of private helpers of a general-purpose scanner whose internals are
    expected to change. This check covers a renamed or removed HELPER NAME: without it a
    missing attribute would surface as a bare `AttributeError` traceback rather than the
    named RED breadcrumb this file's "FAIL CLOSED, NEVER CLEAN-ZERO" contract promises. A
    renamed or removed FILE is a different failure and is caught upstream, by
    `_load_module`'s own load guard.
    """
    module = _load_module(_ECH, "_ech1466")
    missing = sorted(name for name in _EXTRACTOR_API if not hasattr(module, name))
    if missing:
        raise Refusal(
            f"fenced-completeness: {_ECH.relative_to(REPO)} no longer exposes {missing} — the "
            "reused fence enumeration cannot be composed, so the scanned population would be "
            "unestablished rather than empty; refusing instead of reporting a clean pass")
    return module


def _fenced_state_owner_calls(extractor, text: str,
                              registered: frozenset[str]) -> list[str]:
    """The state-owner subcommands invoked inside `text`'s ```bash fences, in order.

    The fence enumeration, the block cleaning and the split into leaf statements are the
    extractor's own — the same `_fenced_bash_blocks` → clean → `_boundary_units` shape its
    other consumers use, so its stated limitations (the `bash`-only info string, the bare
    subshell the splitter does not descend) are inherited with their documentation rather
    than re-derived here.

    Only the SUBCOMMAND ATTRIBUTION is local, and deliberately so: the extractor's own head
    extraction returns at most `_MAX_HEAD_WORDS` argv words, so a fence placing an
    interpreter flag ahead of the script path yields the interpreter, the flag and the path
    and drops the subcommand entirely — the check would then pass green over exactly the
    drift it exists to catch. Attribution therefore scans the whole token list for the
    helper and takes the first non-flag operand after it. The helper itself is recognised
    through the extractor's `_helper_basename`, the repository's one definition of "this
    token names bundled helper X", rather than a looser suffix test.

    That first non-flag operand is where the subcommand must sit, so an operand the parser
    does not register REFUSES — it is never skipped. Skipping is selection, not validation:
    a typo, or a subcommand renamed in the state owner without updating the fence, would
    otherwise contribute nothing, leave the orphan list empty, and let the success line
    report a population the drift had silently shrunk — the identical fail-open
    `_invocations` was hardened against on the sequence side. A `<`- or `$`-shaped operand
    is a documented placeholder rather than a call, and is the one declared allowance.
    """
    found: list[str] = []
    for block in extractor._fenced_bash_blocks(text):                     # noqa: SLF001
        cleaned = extractor._join_continuations(                          # noqa: SLF001
            extractor._strip_case_patterns(                               # noqa: SLF001
                extractor._strip_comments_and_heredocs(block)))           # noqa: SLF001
        for statement in extractor._boundary_units(cleaned):              # noqa: SLF001
            tokens = [extractor._normalize(t)                             # noqa: SLF001
                      for t in extractor._tokenize(statement)]            # noqa: SLF001
            for index, token in enumerate(tokens):
                if extractor._helper_basename(token) != _STATE_OWNER_SCRIPT:  # noqa: SLF001
                    continue
                for candidate in tokens[index + 1:]:
                    if candidate.startswith("-"):
                        continue
                    if candidate in registered:
                        found.append(candidate)
                    elif candidate.startswith("<"):
                        # The reference files' own placeholder convention (`<subcommand>`),
                        # which is documentation rather than a call. A `$`-shaped operand is
                        # NOT this: in command position it is a shell variable, i.e. a real
                        # invocation whose subcommand this scanner cannot name — unknown, not
                        # absent — so it refuses below rather than being waved through.
                        pass
                    else:
                        raise Refusal(
                            f"fenced-completeness: a ```bash fence invokes the state owner "
                            f"with the operand {candidate!r}, which the parser registers as "
                            "no subcommand — a typo, a subcommand renamed without updating "
                            "the fence, or a parameterized subcommand this scanner cannot "
                            "resolve; refusing rather than dropping the invocation, which "
                            "would shrink the scanned population silently")
                    break
                else:
                    # The operand list was exhausted without a non-flag token, so no
                    # subcommand could be attributed at all. Dropping it here would be the
                    # same silent shrink the arm above refuses, reached by a different path.
                    raise Refusal(
                        "fenced-completeness: a ```bash fence invokes the state owner with "
                        f"no non-flag operand ({statement.strip()!r}) — no subcommand could "
                        "be attributed, so the scanned population would silently shrink; "
                        "refusing instead of reporting a short population as complete")
    return found


def check_fenced_completeness(registered, report, named):
    """The REVERSE of `check_sequence`: a call the documents FENCE must be accounted for.

    `check_sequence` grades one direction — every name the sequence prints is a registered
    subcommand. Nothing required a call the reference documents mandate to appear IN the
    sequence, so the sequence could omit an enforced call while the suite stayed green over
    a completeness sentence asserting the opposite (issue #1466). This arm closes that
    direction over the reach a fence scan has: every state-owner subcommand invoked inside a
    ```bash fence of either reference file must be named in the call sequence, in
    `_FENCE_EXEMPT`, or in `_CONDITIONAL`.

    DISCLOSED RESIDUAL — this NARROWS the completeness gap, it does not close it. The reused
    enumeration reaches only fences whose info string is exactly ``bash``, so an invocation
    written in inline prose backticks, or in a fence with any other info string, is invisible
    here — and a sizeable minority of the sequence's distinct calls are written exactly that
    way. A call mandated in prose without a fence therefore escapes this check entirely;
    re-deriving the unconditional set still requires reading both documents' prose, which no
    scanner does. A third escape route is inherited from `_boundary_units`: an invocation
    nested in a bare `(…)` subshell keeps a trailing `)` that `_helper_basename`'s
    end-anchored match drops, so such a fence is invisible here — and a partial loss of that
    shape is not caught by the empty-population guard, whose trigger is a reference file
    contributing nothing at all.

    `named` is the sequence's invocation list, produced ONCE by `check_sequence` and passed
    on rather than re-parsed here — two parses of the same paragraph are two things that can
    drift, and only one of them would be the figure the suite pins. The reference files are
    read from `STEP36`/`STEP4`, the same module-level source `check_sequence` reads, so a
    crafted document drives this arm by rebinding those and grades under identical rules.
    """
    seq_text = _read(STEP36)
    step4 = _read(STEP4)
    named = frozenset(named)

    unregistered = sorted(c for c in _FENCE_EXEMPT if c not in registered)
    if unregistered:
        raise Refusal(
            f"fenced-completeness: {unregistered} appear in _FENCE_EXEMPT but the parser "
            "registers no such subcommand — an exemption naming no real call exempts "
            "nothing, so the reverse check it was meant to relax is silently absent")
    contradicted = sorted(c for c in _FENCE_EXEMPT if c in named)
    if contradicted:
        raise Refusal(
            f"fenced-completeness: {contradicted} are named in BOTH _FENCE_EXEMPT and the "
            "unconditional call sequence, so the two disagree about whether the call is "
            "conditional; remove it from whichever is wrong")

    extractor = _load_extractor()
    accounted = named | frozenset(_FENCE_EXEMPT) | frozenset(_CONDITIONAL)
    scanned = 0
    empty: list[str] = []
    orphans: list[str] = []
    for label, text in (("step-3-6-audit.md", seq_text),
                        ("step-4-present-create.md", step4)):
        calls = _fenced_state_owner_calls(extractor, text, registered)
        if not calls:
            empty.append(label)
        scanned += len(calls)
        for call in calls:
            if call not in accounted and f"{label}: {call}" not in orphans:
                orphans.append(f"{label}: {call}")
    if empty:
        # FAIL CLOSED PER FILE, not per pair — and unconditionally, so a crafted document
        # grades under the same rule the shipped one does. The scanned population is an
        # operand this arm READS but does not own (it comes from the reused fence
        # enumeration), so a change that stopped yielding blocks would leave every call in
        # that file trivially accounted for. Summing across the scanned files would let a
        # larger one keep the total non-zero while a smaller one went dark, under a success
        # line still claiming both.
        raise Refusal(
            f"fenced-completeness: {empty} contributed no state-owner invocation from any "
            "```bash fence — that file's fences were removed, or the reused fence "
            "enumeration stopped reaching them; refusing rather than reporting an empty "
            "population as a clean pass")
    if orphans:
        raise Refusal(
            f"fenced-completeness: {orphans} are invoked in a ```bash fence of the reference "
            "files but named in neither the call sequence, _FENCE_EXEMPT, nor _CONDITIONAL — "
            "either the sequence is missing a call the run makes, or the call is conditional "
            "and belongs in _FENCE_EXEMPT with its condition recorded")
    report.append(f"fenced-completeness: all {scanned} fenced state-owner invocations across "
                  "both reference files are named in the call sequence, the declared "
                  "exemption set, or the conditional set")


def main():
    report: list[str] = []
    try:
        module = _load_module()
        registered = module.registered_subcommands()
        check_readbacks(module, registered, report)
        check_readonly_complement(module, registered, report)
        check_emitting_complement(module, registered, report)
        check_round_defaulted(module, registered, report)
        check_next_action_routing_totality(module, report)
        check_flag_vocabulary(module, module.build_parser(), registered, report)
        sequence = check_sequence(registered, report)
        unconditional = len(sequence)
        check_fenced_completeness(registered, report, sequence)
    except Refusal as exc:
        sys.stderr.write(f"check-audit-lifecycle-contracts: {exc}\n")
        return 1
    # The measurement figure, DERIVED — never hand-transcribed. Reported on the SUCCESS
    # path so a passing suite carries the evidence rather than only a failure message.
    report.append(f"unconditional_call_count={unconditional}")
    report.append(f"registered_subcommand_count={len(registered)}")
    for line in report:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
