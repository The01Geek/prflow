#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Render the /devflow:create-issue Step 3.6 fresh-context audit prompt.

This is the create-issue sibling of ``scripts/render-grounding-block.sh``: the
single deterministic renderer of a load-bearing prompt surface, so the
orchestrator stops hand-emitting the ~2,000-word audit-instruction block into
every dispatch. The canonical prose lives in the committed template file
``skills/create-issue/references/audit-prompt-template.md`` (resolved relative
to THIS file, never the cwd — the repo layout and the vendored-plugin layout
both place ``scripts/`` and ``skills/`` as siblings under one root).

Contract (issue #600):

- Reads no run *state* and writes no file, and takes no stdin. The reads are the
  committed template file; the consumer extension — for consumer-dimension
  forwarding — ``.prflow/prompt-extensions/create-issue.md``, resolved
  from the git repo root per the #295 SHARED REPO-ROOT CONFIG CONTRACT (a native
  ``git`` subprocess, cwd fallback; never a ``.sh`` exec — the #275 constraint);
  in ``dispatch-instructions`` mode only (issue #709) — the run's canonical
  draft file, read solely to lift its ``# `` title heading; and — when the state
  owner supplies one, which it does only on a ``targeted`` round (issue #793) —
  the round's FROZEN dispatch-scope file, named on this module's command line and
  never discovered. This module has no notion of a round kind: the
  targeted-round-only restriction is enforced by the state owner's own
  ``--kind``/``--scope-file`` cross-checks, not by a check here. That last read is a
  deliberate, disclosed NARROWING of "reads no run state", stated here rather
  than cited as still-intact: the scope file is written by the state owner and
  its path AND content digest are both recorded on the dispatch attempt, so the
  bytes this module reads are frozen at dispatch and cannot move afterwards.
  That is what preserves the property the no-state rule actually protects —
  determinism over a closed recorded tuple — while the literal claim of reading
  no state no longer holds. Reading the LIVE ledger instead would break it twice
  over: post-close status mutations would give the return-time regeneration a
  different ledger than dispatch saw, so every scoped round would diverge. Writing the rendered
  dispatch instructions to disk is the ORCHESTRATOR's job, never this script's:
  the no-write half of this contract is what keeps the module a pure function of
  its inputs, which is in turn what lets ``issue-audit-state.py`` regenerate the
  canonical bytes and compare digests.
- Closed argument surface: closed-vocabulary mode/arm/hook tokens, a kebab-case
  slug, single-line host-absolute paths (either POSIX or Windows spelling — a
  backslash drive-letter path is admitted; a newline and a ``{`` slot token are
  refused), and the machine-generated sentinel pair. No
  free-text parameter reaches any rendered block: every slot filled
  from an argument (``<slug>``, ``{DRAFT_PATH}``, ``{INSTRUCTIONS_PATH}``, and
  the ``{SENTINEL_OPEN}`` /
  ``{SENTINEL_CLOSE}`` pair) is shape-checked at the parse boundary, and the
  draft title never crosses a command line at all — in ``dispatch-instructions``
  mode it is read from the draft file this module was given the path to, and
  substituted LAST (beside ``{CONSUMER_DIMENSIONS}``) so drafter text is never
  re-scanned for slot tokens; the audit-prompt blocks
  (``file``/``embed``/``inline``/``checklist``) never carry it at all.
  (``{CONSUMER_DIMENSIONS}`` is the other file-content
  slot; it is filled from committed consumer-extension file content,
  never from an argument, and is substituted LAST so it is never re-scanned.) The ``--template-file`` /
  ``--extension-file`` test overrides are read-paths that are never substituted
  into the block, and are deliberately left untyped so an explicit empty value
  still selects the root-anchored default (the #295 shared contract) — they are
  outside this claim. The path check bounds shape, not vocabulary (see
  ``_abs_path``).
- Modes, complete by construction: the dispatch arms ``file`` /
  ``embed`` / ``inline`` mirroring ``issue-audit-state.py``'s arm vocabulary,
  plus ``checklist`` (the Step 3.5 self-check), ``extract`` (the generic
  section-extraction hook; the Step 2 ``## Evidence axes`` forwarding consumes
  it as a standalone call, while the Step 3.6 ``## Audit dimensions`` hook
  consumes the same extraction *rule* spliced into a dispatch arm as
  ``{CONSUMER_DIMENSIONS}``, not via a standalone ``extract`` call),
  ``status-only`` (the orchestrator's fail-fast one-line probe),
  ``enumerate-dimensions`` (the issue #708 keyed dimension enumeration the
  Step 3.6 coverage join reads as its authoritative operand), and
  ``dispatch-instructions`` (issue #709 — the canonical, file-arm-only
  audit-DISPATCH instructions the auditor is pointed at and hashes).
- Determinism (issue #709, load-bearing): ``dispatch-instructions`` is a pure
  function of the template file, the draft file's title, and its shape-checked
  path arguments. It carries no timestamp, nonce, or other run-varying token, so
  ``issue-audit-state.py`` regenerating it from a round's recorded closed inputs
  reproduces the dispatched bytes exactly — which is the whole comparand of the
  steering-absence check. Two of the substituted slots (``{RENDERER_PATH}`` and
  the default ``{TEMPLATE_PATH}``) are derived from THIS file's own resolved
  location, so the reproduction is exact *within one installation* — the only
  context a regeneration runs in, since the round's recorded inputs and the
  instruction file it names are both local to that checkout. Never introduce a
  varying token into the ``di`` blocks.
  It deliberately does NOT splice ``{CONSUMER_DIMENSIONS}``: consumer audit
  dimensions are renderer-owned *audit* instructions, out of that check's scope,
  and reading the extension here would make the digest depend on a file the
  dispatch does not carry.
- Output contract: stdout's FIRST line is ``render-status:`` with a value from
  the closed set {appended, absent, unestablished}; stdout's LAST line is the
  fixed terminal marker ``render-end:`` on every full render, so a truncated
  delivery is positionally detectable: any tail cut drops the terminal marker,
  whatever the render's last block happens to be (the consumer section is last
  only in checklist/extract mode — the dispatch arms follow it with the
  verdict block). ``status-only`` prints
  exactly the one status line (it IS one line; no end marker).
  ``dispatch-instructions`` has its OWN positional marker pair — first line
  ``dispatch-instructions:`` with the format version, last line ``render-end:``
  — because it reads no consumer extension and so has no ``render-status:``
  answer to report.
- Failure (unusable arguments, unreadable template file, an unreadable or
  title-less draft file in ``dispatch-instructions`` mode) exits non-zero with
  EMPTY stdout and a stderr breadcrumb — which, together with out-of-position
  markers, is the no-contract-output signal the skill's degraded arms key on.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

# State-directory resolution (issue #1002): canonical .prflow/, with the LOUD
# transitional fallback to a superseded .devflow/ when only that one is present.
# lib/ sits beside scripts/ in both the source repo and a vendored
# .prflow/vendor/prflow/ tree, so this import path holds on every tier. A copy
# missing the sibling degrades to the canonical name with no fallback rather than
# failing the read (the same posture the plugin_identity import takes).
try:
    # `__file__` is absent when this module is read and exec'd rather than imported
    # (the #343 gate exercise does exactly that), so the path insert degrades with the
    # import instead of raising ahead of a gate that must fail fast.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
    from state_dir import resolve_state_dir as _resolve_state_dir
except Exception:  # pragma: no cover - partial-copy / exec'd-source arm
    def _resolve_state_dir(repo_root, stream=None):
        return str(Path(repo_root) / ".prflow")

STATUS_PREFIX = "render-status:"
END_MARKER = "render-end:"
# issue #709: the dispatch-instructions render's own leading positional marker.
# The version suffix is a FIXED literal, not a runtime value — it is part of the
# hashed bytes, so it may only change when the canonical form itself changes.
INSTRUCTIONS_PREFIX = "dispatch-instructions:"
INSTRUCTIONS_VERSION = "1"

# Closed vocabularies (complete by construction).
_MODES = (
    "file", "embed", "inline", "checklist", "extract", "status-only",
    "enumerate-dimensions",
    "dispatch-instructions",
)
_DISPATCH_ARMS = ("file", "embed", "inline")
# The template block-selection token for the issue-#709 dispatch-instruction
# blocks. It is deliberately NOT a member of _DISPATCH_ARMS: those name the audit
# arms the state owner routes, and `di` selects a different artifact entirely.
_INSTRUCTIONS_TOKEN = "di"
# issue #793: the template block-selection token for the `targeted` round-kind block —
# the per-claim verdict contract, the changed-section scope, and the out-of-scope
# observation channel. Like `di` it is deliberately NOT a member of `_DISPATCH_ARMS`: it
# selects an additional span spliced into the dispatch instructions on a scoped round,
# not an audit arm.
_TARGETED_TOKEN = "tg"
# The dispatch-scope file's format marker, written by `issue-audit-state.py`'s
# `render_dispatch_scope`. A coupled literal: this module refuses to parse a file that
# does not open with it, so a payload in some other shape can never be spliced into an
# auditor prompt as though it were the tool's own.
_SCOPE_MARKER = "<!-- prflow:dispatch-scope v1 -->"
# Extraction hooks map to the two consumer section headings they forward.
_HOOKS = {
    "audit-dimensions": "## Audit dimensions",
    "evidence-axes": "## Evidence axes",
}
# Consumer-dimension status values (the render-status: value set).
_STATUS_APPENDED = "appended"
_STATUS_ABSENT = "absent"
_STATUS_UNESTABLISHED = "unestablished"

# Template block markers. A block is bounded by
#   <!-- render-block: <space-separated arm/mode set> -->
#   ... block body ...
#   <!-- render-block-end -->
# and is emitted only when the current arm/mode is in its set. Slots inside a
# block are substituted after selection.
_BLOCK_OPEN_PREFIX = "<!-- render-block:"
_BLOCK_OPEN_SUFFIX = "-->"
_BLOCK_CLOSE = "<!-- render-block-end -->"

# Dimension-key declaration marker (issue #729). A line
#   <!-- dim-key: <lowercase-kebab> -->
# immediately above a `- ` bullet DECLARES that dimension's stable identity. It is
# machine data: `enumerate_dimensions` reads it, and every rendering path strips it,
# so the checklist prose and the enumeration are two projections of ONE declaration
# rather than the enumeration being a regex scrape of the prose (the pre-#729 shape,
# where rewording a bold name silently rekeyed a dimension the state owner had
# already recorded durably).
_DIM_KEY_TOKEN = "dim-key:"
# Built FROM the token, never beside it: the marker spelling lives in exactly one
# place, so renaming it can never leave `_strip_dim_key_markers`' fast path matching
# a token the pattern no longer recognizes (a silently no-op stripper).
_DIM_KEY_RE = re.compile(r"^<!--\s*" + re.escape(_DIM_KEY_TOKEN) + r"\s*(.*?)\s*-->$")
# The declared-key alphabet: lowercase kebab, no leading/trailing/doubled hyphen.
# This is STRICTER than the CLI's `_kebab_slug` alphabet check (which accepts
# `-lead`, `trail-`, `a--b`) and is the canonical shape `_name_slug` produces, so a
# declared key and a derived one never collide by casing. The two are deliberately
# not one check: `_kebab_slug` bounds a caller-supplied CLI argument, while a
# declaration is committed repo content held to the canonical form.
_DIM_KEY_SHAPE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class RenderError(Exception):
    """A renderer failure: exit non-zero, empty stdout, stderr breadcrumb."""


def default_template_path() -> Path:
    """The committed audit-prompt template this renderer reads by default.

    Public because `issue-audit-state.py` calls it across the module boundary when it
    regenerates a round's canonical instructions (issue #709) and a round recorded no
    explicit template input; `_load_generator` asserts this name alongside
    `instructions_bytes`, so a rename fails closed as `regeneration-failed` instead of
    surfacing as an AttributeError traceback out of `record-return`.
    """
    # Resolve the template relative to THIS file's location, never the cwd, so
    # the vendored-plugin layout (scripts/ and skills/ siblings under the
    # vendor root) resolves identically to the repo checkout.
    return (
        Path(__file__).resolve().parent.parent
        / "skills"
        / "create-issue"
        / "references"
        / "audit-prompt-template.md"
    )


# The pre-#709 private name, retained as an alias so an in-flight caller (and the
# renderer's own tests) keep resolving; the public name above is the contract.
_default_template_path = default_template_path


def _repo_root() -> str | None:
    # #295 SHARED REPO-ROOT CONFIG CONTRACT, Python-reader shape: a native git
    # subprocess (Windows-safe, no .sh exec — #275), shallow-clone-safe
    # (--show-toplevel reads no history). git can exit non-zero while genuinely
    # inside a repo (safe.directory) or be absent, so a non-zero/OSError result
    # simply falls back to cwd rather than asserting "not in a repo".
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
        )
    except OSError:
        return None
    root = r.stdout.strip() if r.returncode == 0 else ""
    return root or None


def _default_extension_path() -> Path:
    root = _repo_root()
    if root is not None:
        return Path(_resolve_state_dir(root)) / "prompt-extensions" / "create-issue.md"
    cwd = Path.cwd()
    # Breadcrumb only when NEITHER a git root NOR a .prflow/ dir can be located —
    # the silent-drop class the #295 reader-set contract closes (mirrors
    # match-deferrals.py's _default_config_path). git can exit non-zero while
    # genuinely INSIDE a repo (safe.directory / dubious-ownership), or be absent,
    # so don't assert "not in a git repo" — report that the root could not be
    # resolved.
    if not (cwd / ".prflow").is_dir() and not (cwd / ".devflow").is_dir():
        sys.stderr.write(
            f"render-audit-prompt.py: could not resolve a git repo root and no "
            f".prflow/ at {str(cwd)!r}; falling back to a cwd-anchored default "
            f"prompt-extension path\n"
        )
    return Path(_resolve_state_dir(str(cwd))) / "prompt-extensions" / "create-issue.md"


# --------------------------------------------------------------------------
# Consumer extension delivery triage + section extraction.
#
# The triage mirrors scripts/load-prompt-extension.sh (a coupled pair):
#   present regular readable file          -> read text, extract section
#   absent / present-but-empty             -> no section  (status absent)
#   present-but-unreadable / broken symlink
#     / present-but-non-regular file       -> unestablished (never "absent")
# --------------------------------------------------------------------------
def _strip_dim_key_markers(text: str) -> str:
    """Drop every `<!-- dim-key: … -->` declaration line (issue #729).

    Applied to every RENDERING path, so the auditor-facing prose is byte-identical
    to the pre-#729 render. The *derived text* on the key path is never taken from
    this function's output — `_consumer_section_raw` returns the unstripped section
    and calls this only to decide emptiness.

    `keepends=True` + `"".join` is load-bearing, not style: a `splitlines()`/`"\\n".join`
    round-trip rewrites CRLF to LF and drops a trailing newline, so a consumer section
    would be line-ending-normalized or not depending on whether it happened to declare
    a key. Every non-declaration byte survives verbatim.
    """
    if _DIM_KEY_TOKEN not in text:
        return text
    kept = [
        ln for ln in text.splitlines(keepends=True)
        if not _DIM_KEY_RE.match(ln.strip())
    ]
    return "".join(kept)


def _read_extension(path: Path) -> tuple[str, str]:
    """Return (state, text). state is one of 'ok' / 'absent' / 'unestablished'.

    'ok' text is the file contents (possibly empty -> caller treats as absent).
    """
    # Broken symlink: is a symlink whose target does not exist.
    if path.is_symlink() and not path.exists():
        return ("unestablished", "")
    if not path.exists():
        return ("absent", "")
    # Present-but-non-regular (directory, fifo, device, symlink-to-dir).
    if not path.is_file():
        return ("unestablished", "")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # Present-but-unreadable (permissions) or undecodable payload.
        return ("unestablished", "")
    return ("ok", text)


def extract_section(text: str, heading: str) -> str:
    """Extract every ``## heading`` section, per the four extraction clauses.

    1. A section spans its heading line to the next line beginning ``## ``
       (two hashes + a space) or end of file.
    2. Duplicate same-heading sections concatenate in file order.
    3. An empty section (no non-whitespace body) equals an absent heading.
    4. A heading line inside an HTML comment block or a fenced code block is
       not a heading (an unclosed fence runs to end of file).

    Returns the concatenated section BODIES (heading lines excluded), or the
    empty string when the heading is absent or every match is body-empty.
    """
    target = heading.rstrip()
    in_fence = False
    fence_kind = ""  # '`' or '~'
    in_comment = False
    in_section = False
    collected: list[str] = []
    def _track_comment(current: bool, text_line: str) -> bool:
        # Last-marker-wins comment-block state (mirrors load-prompt-extension.sh).
        if "<!--" not in text_line and "-->" not in text_line:
            return current
        last_open = text_line.rfind("<!--")
        last_close = text_line.rfind("-->")
        if last_open > last_close:
            return True
        if last_close > last_open:
            return False
        return current

    for raw in text.splitlines():
        line = raw.rstrip()

        # Comment-block state is resolved BEFORE fence detection, so a code-fence
        # marker (``` / ~~~) that sits INSIDE an open HTML comment is inert — it
        # neither opens nor closes a fence. Evaluating the fence branch first
        # would toggle `in_fence` on a commented-out fence line and then swallow
        # a later real heading (the load-prompt-extension.sh divergence #600's
        # review caught).
        if in_comment:
            in_comment = _track_comment(in_comment, line)
            if in_section:
                collected.append(raw)
            continue

        # Fence tracking (``` or ~~~) at COLUMN 0 only — `line`, never `line.lstrip()`.
        # load-prompt-extension.sh matches fences with `case "$_line" in '```'*)`, a
        # deliberate column-0 contract, and heading detection here is column-0 too. An
        # lstripped test recognized INDENTED fences the loader treats as ordinary text,
        # so a consumer section wrapping a column-0 `## ` heading in an indented fence
        # made the two hooks forward different bodies at the same `appended` status.
        if line.startswith("```") or line.startswith("~~~"):
            kind = line[0]
            if not in_fence:
                in_fence = True
                fence_kind = kind
            elif kind == fence_kind:
                in_fence = False
                fence_kind = ""
            if in_section:
                collected.append(raw)
            continue
        if in_fence:
            if in_section:
                collected.append(raw)
            continue

        # A line is a heading candidate BEFORE the comment-open check, so a
        # heading carrying a trailing inline comment still matches by its full
        # line (mirrors load-prompt-extension.sh).
        is_heading = line.startswith("## ")
        if is_heading:
            if line == target:
                in_section = True
                # No _track_comment call is needed on this path: `line == target`
                # is an exact match after rstrip, so a matched heading carries no
                # `<!--`/`-->` marker by construction and the call would be a
                # no-op. (A heading WITH a trailing `<!--` is not an exact match,
                # so it reaches neither this arm nor the loader's — both report the
                # section absent, which is the coupled-pair behavior.)
                continue
            # A different '## ' heading terminates the current section.
            if in_section:
                in_section = False
            # fall through to comment tracking for this line too

        # A `## ` heading line is tested for heading-ness above BEFORE this
        # comment-open check, so a heading with a trailing inline comment still
        # matches; a non-heading line here may open a comment for later lines.
        in_comment = _track_comment(in_comment, line)

        if in_section:
            collected.append(raw)

    body = "\n".join(collected).strip("\n")
    if not body.strip():
        return ""
    return body


def _consumer_section_raw(ext_path: Path, heading: str) -> tuple[str, str]:
    """Return (status, RAW section text) — declaration markers retained.

    The key-derivation projection (issue #729). Only `enumerate_dimensions` wants
    this; every rendering path takes `consumer_dimensions` below, which is the same
    section with the markers stripped. Two named accessors rather than one raw
    return the callers must each remember to strip: the projection a caller needs
    is chosen by which function it calls, not by a comment it has to obey.
    """
    state, text = _read_extension(ext_path)
    if state == "unestablished":
        return (_STATUS_UNESTABLISHED, "")
    if state == "absent":
        return (_STATUS_ABSENT, "")
    section = extract_section(text, heading)
    # The emptiness decision is taken on the STRIPPED text: a section carrying only
    # declaration markers declares no dimensions, so it is `absent` — reporting it
    # `appended` would pair a complete status with an instruction-empty splice.
    if not _strip_dim_key_markers(section).strip():
        return (_STATUS_ABSENT, "")
    return (_STATUS_APPENDED, section)


def consumer_dimensions(ext_path: Path, heading: str) -> tuple[str, str]:
    """Return (status, RENDER-READY section text) for a consumer forwarding hook.

    The rendering projection: identical to `_consumer_section_raw` with the #729
    declaration markers stripped, so no rendering caller can leak machine data into
    the auditor-facing prompt by forgetting to strip.

    It is also where a consumer's declarations are **validated on the render path**.
    Every rendering caller funnels through here, so this one call is what stops a
    malformed consumer declaration from rendering happily while `enumerate-dimensions`
    dies — the render/enumeration drift the generic arm's `render_dispatch` check
    closes on the template side. `consumer_entries` is called for its fail-closed
    arms only; its return value is the key-derivation path's business.

    **Two scope limits, both load-bearing.** (1) Validation applies only to the
    `## Audit dimensions` hook: this accessor is heading-parameterized and
    `render_extract` also asks it for `## Evidence axes`, a section that declares no
    dimensions, is never enumerated, and is never joined to anything — validating it
    would fail ordinary consumer prose (two axes sharing a bold lead) with a remedy
    that means nothing there. (2) On this path a **derived**-key collision degrades
    rather than raises: a declared collision is an authoring defect the consumer can
    fix, but two bold leads that happen to slug alike are a renderer-internal
    ambiguity, and escalating that to a hard failure would deny the auditor the whole
    audit prompt over a formatting coincidence in a third-party file. The enumeration
    path stays strict, so the ambiguity still surfaces there as a degraded render.
    """
    status, section = _consumer_section_raw(ext_path, heading)
    if status == _STATUS_APPENDED and heading == _HOOKS["audit-dimensions"]:
        consumer_entries(section, strict_derived=False)
    return (status, _strip_dim_key_markers(section))


# --------------------------------------------------------------------------
# Template parsing / block selection.
# --------------------------------------------------------------------------
def _reject_stray_dim_key_declarations(
    blocks: list[tuple[frozenset[str], str]],
) -> None:
    """Fail closed on a `<!-- dim-key: … -->` declaration outside the checklist block.

    The declaration marker is machine data that `_assemble` strips from *every*
    selected block body, but only the checklist block is *validated* (by
    `_generic_dimensions`, and only on a render that emits it). A declaration
    authored into a `file`/`embed`/`inline`/`di` block is therefore silently
    stripped from the auditor-facing prose AND never enumerated, while the bullet
    it was meant to key still renders as a dimension-shaped instruction — the one
    authoring defect #729's fail-closed arms miss (issue #735). Reject it here,
    naming the block that carries it, so the defect fails closed on every render
    and enumeration path instead of reaching the auditor keyless.

    Scope is what keeps this off the #729 exemptions: it sees only the template's
    OWN parsed block bodies, never the substituted-last `{CONSUMER_DIMENSIONS}`
    value or the consumer `## Evidence axes` section — both reach a render as slot
    values *after* `_parse_blocks` runs and are validated (or deliberately
    exempted) by their own dedicated code (`consumer_dimensions` /
    `_consumer_section_raw`). Running at parse time is what structurally routes
    this check away from those already-handled surfaces (the issue #735
    Implementation-risk constraint), and skipping the checklist block leaves its
    declarations to `_generic_dimensions`, their one legal home. A template with
    no checklist block carries no declaration to reject, so it keeps rendering.
    """
    for arm_set, body in blocks:
        if "checklist" in arm_set:
            continue
        # Fast path keyed on the single-sourced token spelling, mirroring
        # `_strip_dim_key_markers`: the lines rejected here are exactly the lines
        # that strip would have silently removed from this block.
        if _DIM_KEY_TOKEN not in body:
            continue
        for raw in body.splitlines():
            if _DIM_KEY_RE.match(raw.strip()):
                raise RenderError(
                    f"template malformed: a dim-key declaration appears in a "
                    f"non-checklist render-block (arms: "
                    f"{' '.join(sorted(arm_set))}); dimension-key declarations are "
                    f"legal only inside the checklist block — a declaration here "
                    f"is silently stripped from the rendered prose and never "
                    f"enumerated"
                )


def _parse_blocks(template_text: str) -> list[tuple[frozenset[str], str]]:
    """Parse the template into (arm/mode set, body) blocks in file order.

    Text outside any block is ignored (it is the human-facing documentation of
    slots and the extraction rule, for the degraded manual arms). A missing
    close marker is a template defect -> RenderError. A `<!-- dim-key: … -->`
    declaration outside the checklist block is likewise a template defect
    (issue #735) — rejected here so every render and enumeration path that parses
    the template fails closed on it identically.
    """
    blocks: list[tuple[frozenset[str], str]] = []
    current_set: frozenset[str] | None = None
    current_lines: list[str] = []
    for line in template_text.splitlines():
        s = line.strip()
        if s.startswith(_BLOCK_OPEN_PREFIX) and s.endswith(_BLOCK_OPEN_SUFFIX):
            if current_set is not None:
                raise RenderError(
                    "template malformed: nested render-block open marker"
                )
            spec = s[len(_BLOCK_OPEN_PREFIX):-len(_BLOCK_OPEN_SUFFIX)].strip()
            current_set = frozenset(spec.split())
            current_lines = []
            continue
        if s == _BLOCK_CLOSE:
            if current_set is None:
                raise RenderError(
                    "template malformed: render-block-end without an open marker"
                )
            blocks.append((current_set, "\n".join(current_lines)))
            current_set = None
            current_lines = []
            continue
        if current_set is not None:
            current_lines.append(line)
    if current_set is not None:
        raise RenderError("template malformed: unterminated render-block")
    _reject_stray_dim_key_declarations(blocks)
    return blocks


def _load_template(template_path: Path) -> str:
    try:
        return template_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RenderError(
            f"could not read audit-prompt template at {template_path}: {exc}"
        ) from exc


def _substitute(text: str, slots: dict[str, str]) -> str:
    for key, value in slots.items():
        text = text.replace(key, value)
    return text


def _section_placeholder(status: str) -> str:
    # Self-describing body for a non-appended status. Fails CLOSED on a status
    # outside the closed set rather than degrading into the plausible-looking
    # "could not be established" prose: the vocabulary is closed by construction,
    # so an unknown value is a defect in the producer, not an input to render.
    if status == _STATUS_ABSENT:
        return "(no consumer section)"
    if status == _STATUS_UNESTABLISHED:
        return "(consumer section could not be established)"
    raise RenderError(
        f"unknown consumer-extension status {status!r} (expected one of "
        f"{_STATUS_ABSENT}, {_STATUS_UNESTABLISHED}, {_STATUS_APPENDED})"
    )


def _dimensions_block_for_status(status: str, section: str) -> str:
    if status == _STATUS_APPENDED:
        # Already render-ready: `consumer_dimensions` is the stripped projection.
        return section
    if status == _STATUS_ABSENT:
        return "(no consumer audit dimensions)"
    if status == _STATUS_UNESTABLISHED:
        return "(consumer audit dimensions could not be established)"
    raise RenderError(
        f"unknown consumer-extension status {status!r} (expected one of "
        f"{_STATUS_ABSENT}, {_STATUS_UNESTABLISHED}, {_STATUS_APPENDED})"
    )


def _assemble(blocks, token, slots, template_path) -> str:
    """Select the blocks carrying ``token``, substitute, and join — fail-closed.

    Shared by every full render. The fail-closed emptiness rule lives here once
    because it is the load-bearing half: a mode that selects no block (or only blank
    ones) would otherwise emit a positionally-valid two-marker render carrying no
    instructions at all, which the delivery check cannot detect. Two copies of that
    rule could be kept in step only by hand.

    Strips the #729 declaration markers from each selected body BEFORE
    substitution, so a substituted-last value that legitimately contains one —
    ``{CONSUMER_DIMENSIONS}``, already stripped by ``consumer_dimensions`` — is
    never re-scanned. Every full render shares this chokepoint, which is what
    keeps the markers off every auditor-facing prose surface. On a block
    carrying no marker the strip short-circuits, so the canonical instructions
    render (whose digest is verified) is byte-unchanged by it.
    """
    parts = [
        _substitute(_strip_dim_key_markers(body), slots).strip("\n")
        for arm_set, body in blocks
        if token in arm_set
    ]
    inner = "\n\n".join(p for p in parts if p.strip())
    if not inner.strip():
        raise RenderError(
            f"template selected no non-empty block for {token!r} ({template_path})"
        )
    return inner


def render_dispatch(
    mode: str,
    template_path: Path,
    slug: str,
    draft_path: str | None,
    sentinel_open: str | None,
    sentinel_close: str | None,
    ext_path: Path,
) -> str:
    """Assemble a full render for a dispatch arm (``mode`` in _DISPATCH_ARMS) or
    the checklist self-check (``mode == "checklist"``). ``mode`` doubles as the
    block-selection token, so the checklist branch passes ``"checklist"``."""
    template_text = _load_template(template_path)
    blocks = _parse_blocks(template_text)

    # Validate the dimension declarations on the RENDER path too (issue #729), not
    # only in `enumerate-dimensions`: without this a template whose bullet lost its
    # declaration renders the prose happily while the enumeration — the operand
    # coverage totality is checked against — dies, exactly the silent drift between
    # the two projections this design forbids. Validating here is what makes the
    # no-silent-drift property structural rather than merely asserted in prose.
    # (The consumer section's declarations are validated by `consumer_dimensions`
    # below — the rendering projection is the chokepoint every render path shares.)
    #
    # Scoped to renders that actually EMIT the checklist block: a template carrying
    # no checklist block emits no dimension prose, so it has nothing to drift and
    # must keep rendering (a bare file-arm template is a legal fixture). Widening
    # this to every render would turn that absence into a hard failure — a contract
    # change this issue never asked for.
    if any("checklist" in arm_set and mode in arm_set for arm_set, _ in blocks):
        _generic_dimensions(template_text)

    status, section = consumer_dimensions(ext_path, _HOOKS["audit-dimensions"])
    # `{CONSUMER_DIMENSIONS}` is substituted LAST (dict-insertion order): the
    # consumer-extension text spliced in is then never re-scanned for `<slug>` /
    # `{DRAFT_PATH}` tokens it may legitimately contain. Keep it last.
    slots = {
        "<slug>": slug,
        "{DRAFT_PATH}": draft_path or "",
        "{SENTINEL_OPEN}": sentinel_open or "",
        "{SENTINEL_CLOSE}": sentinel_close or "",
        "{CONSUMER_DIMENSIONS}": _dimensions_block_for_status(status, section),
    }

    # `_assemble` strips the #729 declaration markers before substitution, so the
    # already-stripped `{CONSUMER_DIMENSIONS}` value is never re-scanned — the
    # substituted-last invariant above.
    inner = _assemble(blocks, mode, slots, template_path)
    return f"{STATUS_PREFIX} {status}\n{inner}\n{END_MARKER}"


def render_extract(hook: str, ext_path: Path) -> str:
    """Section-extraction mode: forward one consumer section.

    The extraction RULE is shared by both hooks, but this mode is the
    consumption path only for ``--hook evidence-axes`` (Step 2's forwarding);
    Step 3.6's ``## Audit dimensions`` reaches the auditor spliced into a
    dispatch arm via ``{CONSUMER_DIMENSIONS}``, not through a standalone
    ``extract`` call.
    """
    # Guard the hook lookup so the module's documented failure contract (rc≠0,
    # empty stdout, stderr breadcrumb) holds for every entry point, not only the
    # CLI — argparse's `choices` constrains the CLI, but this function is public
    # and a direct caller would otherwise get a bare KeyError.
    if hook not in _HOOKS:
        raise RenderError(
            f"unknown hook {hook!r} (expected one of {', '.join(sorted(_HOOKS))})"
        )
    heading = _HOOKS[hook]
    # consumer_dimensions returns section="" for every non-appended status, so the
    # body carries self-describing placeholder prose instead of a bare blank line —
    # the same treatment the dispatch path gives via _dimensions_block_for_status.
    # An empty body between markers is positionally valid but instruction-empty,
    # the shape render_dispatch fails closed on.
    status, section = consumer_dimensions(ext_path, heading)
    body = section if status == _STATUS_APPENDED else _section_placeholder(status)
    return f"{STATUS_PREFIX} {status}\n{body}\n{END_MARKER}"


def render_status_only(ext_path: Path) -> str:
    status, _ = consumer_dimensions(ext_path, _HOOKS["audit-dimensions"])
    return f"{STATUS_PREFIX} {status}"


def draft_title(text: str) -> str:
    """Lift the draft's ``# `` title heading (issue #709).

    COUPLED MIRROR of ``issue-audit-state.py``'s ``split_body`` title rule — the
    two must agree on WHICH LINE is the title, because that function's body-only
    digest starts after the title line this one reads (it additionally drops the
    ``# `` marker and the blank separator, which neither function returns). The
    decided rule, stated identically at both sites: leading blank lines are
    skipped; the title is the first non-blank line and must be a level-1 ``# ``
    heading (a bare ``#`` is accepted and yields an empty title); a ``##`` there
    means there is no title at all.

    The two DIVERGE, deliberately, on a title-less draft: ``split_body`` returns
    the whole content as body (its caller still needs a digest), while this one
    raises RenderError rather than rendering a silent empty title — the title is
    part of the authorized instruction set, so a draft the run cannot title is an
    unestablished input, not a render that quietly drops a field. The shared rule
    is the detection; the not-found handling is each caller's own.
    """
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == "#":
            return ""
        if line.startswith("# "):
            return line[2:].strip()
        raise RenderError(
            "the draft file's first non-blank line is not a '# ' title heading, "
            "so the draft title could not be established"
        )
    raise RenderError("the draft file is empty, so it carries no title heading")


def parse_scope(scope_text: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Read a frozen dispatch-scope file into ``(sections, claims)`` (issue #793).

    The producer is ``issue-audit-state.py``'s ``render_dispatch_scope``, and the shape is
    machine-written and machine-read, so anything outside it is a tampered or foreign
    artifact rather than a dialect to accommodate — ``RenderError`` on every such shape.

    Note what this function deliberately does NOT do: it applies no identity-data floor.
    The floor lives at the single write site in the state owner, because this module
    imports stdlib only and the module dependency runs state-owner -> renderer, so the
    closed protocol-token vocabulary cannot be shared by import and must not be duplicated
    into a second, unlocked copy here. A summary carrying a forged protocol token is
    refused BEFORE it ever reaches this parser.
    """
    lines = scope_text.splitlines()
    if not lines or lines[0] != _SCOPE_MARKER:
        raise RenderError("the dispatch-scope file does not open with its format marker")
    sections: list[str] = []
    claims: list[tuple[str, str]] = []
    basis = None
    mode = None
    for line in lines[1:]:
        if line.startswith("basis_digest: "):
            # Required, not merely tolerated. Skipping it let this module render a scope
            # file the STATE OWNER's own parser refuses — an asymmetry that would put a
            # prompt in front of an auditor over an artifact the tool would not accept.
            basis = line[len("basis_digest: "):].strip()
            continue
        if line == "sections:":
            mode = "sections"
        elif line == "claims:":
            mode = "claims"
        elif line.startswith("- ") and mode == "sections":
            sections.append(line[2:])
        elif line.startswith("- ") and mode == "claims":
            cid, _, summary = line[2:].partition(" — ")
            claims.append((cid, summary))
        elif line.strip():
            raise RenderError(f"unrecognized dispatch-scope line: {line!r}")
    if not basis:
        raise RenderError(
            "the dispatch-scope file records no basis digest (scope-basis-missing); the "
            "state owner's own parser requires it, so rendering without it would put a "
            "prompt in front of an auditor over an artifact the tool would refuse")
    if not claims:
        # The vacuous-pass refusal. A scoped round over an empty claim set would return
        # "every claim addressed" having checked nothing, and that answer then selects a
        # confirming round and reads as a converging run. Refused here as well as at the
        # write site: this one stops a HAND-MADE scope file from rendering.
        raise RenderError(
            "the dispatch-scope file enumerates no claims; a targeted round over an empty "
            "claim set would pass vacuously (empty-claim-set)")
    if not sections:
        # An empty section set renders a prompt telling the auditor to inspect the changed
        # sections and then listing none. It is unreachable from the writer (an empty delta
        # selects `discovery`), so reaching it means a hand-made or reordered file — the
        # exact shape this parser exists to refuse.
        raise RenderError(
            "the dispatch-scope file enumerates no changed sections (scope-sections-empty); "
            "a scoped prompt with no sections points the auditor at nothing")
    return sections, claims


def _render_scope_slots(sections: list[str], claims: list[tuple[str, str]]) -> dict:
    """The two substituted payloads a `targeted` block carries (issue #793).

    Claims travel as id plus one-line summary and NOTHING else — no status, no severity,
    no disposition, no prior verdict, no rationale, no evidence. The auditor learns what to
    CHECK, never what was CONCLUDED. Because the parser above only ever produces those two
    fields, this renderer is structurally unable to emit a withheld one: there is no
    variable here holding it.
    """
    return {
        "{SCOPE_CLAIMS}": "\n".join(f"- {cid} — {summary}" for cid, summary in claims),
        # No empty-set fallback: `parse_scope` refuses an empty section set outright,
        # so a "(none recorded)" placeholder here would only ever paper over a shape that
        # must not render at all.
        "{SCOPE_SECTIONS}": "\n".join(f"- {s}" for s in sections),
    }


def render_instructions(
    template_path: Path,
    slug: str,
    draft_path: str,
    instructions_path: str,
    draft_text: str,
    scope_text: str | None = None,
) -> str:
    """Render the canonical file-arm audit-DISPATCH instructions (issue #709).

    File arm only, by construction: the mechanism's whole proof is that the
    auditor hashes an on-disk instruction file, and the embed and inline arms are
    entered precisely BECAUSE the canonical draft-file write already failed. Those
    arms therefore record steering-absence as unestablished-by-construction in the
    state owner rather than rendering a file here — a designed consequence, not a
    gap this function should paper over with a second arm.

    Pure: same (template bytes, draft title, paths, installation) -> same output
    bytes, with no consumer-extension read and no run-varying token.
    ``issue-audit-state.py`` re-invokes this exact function over a round's
    recorded closed inputs and compares the digest, so any nondeterminism
    introduced here silently converts every clean audit into a withheld one. The
    installation is part of that tuple because ``{RENDERER_PATH}`` and the default
    ``{TEMPLATE_PATH}`` are derived from this file's resolved location; a
    regeneration always runs in the same checkout that dispatched, so that is a
    scoping of the claim, not a hole in it.
    """
    blocks = _parse_blocks(_load_template(template_path))
    # The renderer's own resolved location and its template's — derived, never
    # taken from an argument, so they cannot carry injected text and so the
    # regeneration reproduces them without needing them recorded as inputs.
    slots = {
        "<slug>": slug,
        "{DRAFT_PATH}": draft_path,
        "{INSTRUCTIONS_PATH}": instructions_path,
        "{RENDERER_PATH}": str(Path(__file__).resolve()),
        "{TEMPLATE_PATH}": str(template_path),
        # Drafter-authored text, substituted LAST for the same reason
        # {CONSUMER_DIMENSIONS} is: a title containing a literal slot token must
        # never be re-scanned as one. Keep it last.
        "{DRAFT_TITLE}": draft_title(draft_text),
    }
    inner = _assemble(blocks, _INSTRUCTIONS_TOKEN, slots, template_path)
    if scope_text is not None:
        # issue #793 — a `targeted` round splices its frozen payload here, so the auditor
        # reads ONE artifact (the instruction file) exactly as it always has. Nothing rides
        # beside it: the scope file's own path is declared out of bounds, so the payload
        # reaches the auditor only through this splice.
        #
        # Purity is preserved over the WIDENED tuple rather than abandoned: `scope_text` is
        # the bytes of a file whose digest the dispatch recorded, so the same recorded
        # inputs still produce the same output bytes. `scope_text is None` renders exactly
        # the pre-#793 string, which is what makes every already-recorded discovery round
        # regenerate byte-identically.
        sections, claims = parse_scope(scope_text)
        inner += "\n\n" + _assemble(
            blocks, _TARGETED_TOKEN,
            {**slots, **_render_scope_slots(sections, claims)}, template_path)
    return (
        f"{INSTRUCTIONS_PREFIX} {INSTRUCTIONS_VERSION}\n{inner}\n{END_MARKER}"
    )


_DISPATCH_POINTER_PREFIX = "dispatch-pointer:"


def _emit_dispatch_pointer(rendered: str) -> None:
    """Echo the `dispatch-pointer:` line to stderr (issue #795).

    The caller used to re-read the just-written instruction file in a standalone
    `python3 -c` process solely to extract this one line — a whole extra spawn and
    Bash round-trip for a line the generator had already rendered. It is emitted
    here from the SAME string just written to stdout, so it is byte-identical to
    the line inside that file by construction rather than by re-derivation.

    This changes NO stdout byte and reads no consumer extension, so
    `dispatch-instructions` keeps its purity and the issue-#709 regeneration
    comparand stays a pure function of the round's recorded inputs.

    The caller selects this line by its `dispatch-pointer:` PREFIX, never as "the
    stderr output": `_default_extension_path()` runs unconditionally before the
    mode branch and emits its own breadcrumb on a fully successful run in a cwd
    with neither a git root nor a `.prflow/`, so stderr can legitimately carry
    two lines and a positional read would take that breadcrumb as the auditor
    prompt.

    An absent pointer line is a template-shape defect, not a mode failure, so nothing
    is raised here and stdout is unaffected either way. What backs that routing is
    structural rather than exhaustive, and is worth stating precisely: the pointer
    line sits inside the single unconditional `render-block: di` span of the template
    with no nested conditional sub-marker around it, so no rendered output of this
    mode can omit it. The generator's executable test SAMPLES that (one invocation,
    one slug, one draft path) — it is a regression guard on the sampled shape, not a
    proof over every input, and the earlier wording here claimed the stronger thing.

    The prefix is matched after `lstrip()`, and the FIRST match wins — byte-for-byte
    the recognition the retired extraction fence performed. Both details are
    load-bearing: the pointer block is indented in the template, so an unstripped
    `startswith` matches nothing at all; and an earlier line of the rendered prose
    *describes* the prefix inline, so a substring search would take that sentence
    instead. The emitted bytes are the WHOLE line, indentation included, exactly as
    the retired fence wrote it.
    """
    for line in rendered.splitlines():
        if line.lstrip().startswith(_DISPATCH_POINTER_PREFIX):
            sys.stderr.write(line + "\n")
            return


def instructions_bytes(*args, **kwargs) -> bytes:
    """The EXACT bytes the CLI writes for a ``dispatch-instructions`` render.

    The producer owns its own on-disk framing (issue #709). ``issue-audit-state.py``
    regenerates these bytes and compares digests, so if it replicated the CLI's
    trailing newline by hand, a change to ``main()``'s framing would silently make
    every clean audit unestablished — the exact false alarm the determinism contract
    above exists to prevent. Both ``main()`` and the state owner go through here, and
    a renderer test asserts this equals the real CLI stdout, so the two cannot drift.

    Arguments are forwarded verbatim to ``render_instructions``.
    """
    return (render_instructions(*args, **kwargs) + "\n").encode("utf-8")


# --------------------------------------------------------------------------
# Effective-dimension enumeration (issue #708).
#
# The Step 3.6 coverage mechanism needs a canonical, keyed, count-stable list of
# every required audit dimension — the *authoritative operand* the orchestrator
# joins the auditor's per-dimension coverage outcomes to, and the comparand for
# the byte-identity floor. Because the renderer is deterministic, the auditor's
# own render (the #600 compact-preamble transport) and the orchestrator's render
# assign the SAME stable key to the same dimension, so the join is by shared key,
# never positional or name inference.
#
# The dimension arms are keyed disjointly, so keys are unique across the whole list.
# Since issue #729 every key is DECLARED or content-derived, never a projection of
# a bullet's position or current wording:
#   - generic-floor dimensions: the bullets in the template's `## Audit dimensions`
#     checklist block, each declaring its key on the line above it. Key
#     `g:<declared-key>`; an undeclared bullet fails closed.
#   - consumer dimensions: the per-bullet split of the consumer
#     `## Audit dimensions` section (present only when appended). Key
#     `c:<declared-key>`, else `c:<bold-name-slug>`, else `c:h<hash>`.
#
# Migration (issue #729). The template's declared keys are exactly the slugs the
# pre-#729 scrape produced, so no generic key changed value; a consumer key that
# was `c:<n>` does change. Neither breaks a recorded run: `issue-audit-state.py`
# treats coverage keys as opaque strings and checks a round's totality against the
# `coverage_expected` keyset persisted IN THAT ROUND, never against a fresh
# enumeration — so a run recorded under the previous derivation stays readable and
# keeps its coverage backing with no rekeying step.
#
# Output shape (positionally delimited like every other full render):
#   render-status: <appended|absent|unestablished>
#   dim key=<key> text=<single-line rendered dimension text>
#   ...
#   render-end:
# --------------------------------------------------------------------------
_DIM_LINE_PREFIX = "dim key="
_DIM_TEXT_SEP = " text="
# A dimension's bold lead: `**Name**` at the start of the bullet's TEXT (the bullet's
# `- ` marker already stripped). Since #729 this drives the CONSUMER fallback key
# only — a generic key is read from its declaration, never matched out of the prose —
# so it is anchored at the text, not at a bullet marker the caller would have to
# re-synthesize.
_BOLD_LEAD_RE = re.compile(r"^\*\*(.+?)\*\*")
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


def _name_slug(name: str) -> str:
    """Deterministic kebab slug of a dimension's bold name (consumer fallback key)."""
    return _SLUG_STRIP_RE.sub("-", name.strip().lower()).strip("-")


def _one_line(text: str) -> str:
    """Collapse a dimension's text to a single line (join wrapped/continued lines).

    A `dim ` output line must never carry an embedded newline (it would forge a
    second record), so continuation lines are joined with a single space and
    interior runs of whitespace are collapsed.
    """
    return re.sub(r"\s+", " ", text).strip()


# Which file a declaration defect is attributable to. The breadcrumb must name the
# file at fault: the generic arm parses THIS repo's committed template, the consumer
# arm parses a third-party `.prflow/prompt-extensions/create-issue.md`, and an
# operator who cannot tell the two apart debugs the wrong file.
_SOURCE_TEMPLATE = "template"
_SOURCE_CONSUMER = "consumer extension"


def _declared_key(line: str, source: str = _SOURCE_TEMPLATE) -> str | None:
    """The key declared by a `<!-- dim-key: … -->` line, or None if not one.

    Raises RenderError on a marker whose key is not lowercase kebab-case: a
    malformed declaration is a defect in the declaring file, never a key to coin.
    `source` names that file's role so the breadcrumb is attributable.
    """
    m = _DIM_KEY_RE.match(line.strip())
    if not m:
        return None
    key = m.group(1)
    if not _DIM_KEY_SHAPE_RE.match(key):
        raise RenderError(
            f"{source} malformed: dim-key declaration {key!r} is not lowercase "
            f"kebab-case (letters, digits, single hyphens)"
        )
    return key


def _generic_dimensions(template_text: str) -> list[tuple[str, str]]:
    """The generic-floor dimensions as (key, single-line-text), template order.

    Selects the one checklist block (the block whose arm set includes
    ``checklist`` — unique in the template) and returns each top-level bullet
    paired with the ``<!-- dim-key: … -->`` declaration on the line above it.

    Keys are ``g:<declared-key>`` — read from the DECLARATION, never slugged from
    the bullet's prose (issue #729), so rewording a bullet leaves its key
    byte-identical. Every fail-closed arm below exists to keep the two projections
    (the human-facing checklist prose and this enumeration) from drifting apart
    silently: an undeclared bullet, an orphan declaration, or a duplicate key is a
    template defect that raises rather than coining or coalescing a key.
    """
    blocks = _parse_blocks(template_text)
    checklist_bodies = [body for arm_set, body in blocks if "checklist" in arm_set]
    if len(checklist_bodies) > 1:
        # The uniqueness this function's docstring states is now ENFORCED, not merely
        # described: two checklist blocks would silently merge two dimension sets into one
        # enumeration, and the merged keyset is what coverage totality is checked against.
        raise RenderError(
            f"template malformed: {len(checklist_bodies)} checklist blocks carry a "
            f"generic audit-dimension list; exactly one is required"
        )
    if not checklist_bodies:
        raise RenderError(
            "template malformed: no checklist block carrying the generic "
            "audit-dimension list"
        )
    dims: list[tuple[str, str]] = []
    seen: set[str] = set()
    for body in checklist_bodies:
        pending: str | None = None
        for raw in body.splitlines():
            line = raw.rstrip()
            declared = _declared_key(line, _SOURCE_TEMPLATE)
            if declared is not None:
                if pending is not None:
                    raise RenderError(
                        f"template malformed: dim-key declaration {pending!r} "
                        f"declares no bullet (another declaration reached before "
                        f"any `- ` dimension bullet)"
                    )
                pending = declared
                continue
            if not line.startswith("- "):
                # Adjacency enforcement: a blank line between a declaration and its
                # bullet is ordinary formatting, but any OTHER intervening line
                # breaks the binding — otherwise a declaration silently binds to a
                # distant bullet and mis-keys it, which no other arm would catch.
                if line.strip() and pending is not None:
                    raise RenderError(
                        f"template malformed: dim-key declaration {pending!r} is not "
                        f"adjacent to its bullet ({line[:60]!r} intervenes); a "
                        f"declaration binds only the `- ` bullet immediately below it"
                    )
                continue
            if pending is None:
                raise RenderError(
                    f"template malformed: generic dimension bullet {line[:60]!r} "
                    f"carries no dim-key declaration on the line above it; every "
                    f"checklist bullet declares its stable key"
                )
            key = f"g:{pending}"
            pending = None
            if key in seen:
                raise RenderError(
                    f"template malformed: duplicate generic dimension key {key!r}"
                )
            seen.add(key)
            # The rendered text is the bullet with its leading `- ` marker stripped.
            dims.append((key, _one_line(line[2:])))
        if pending is not None:
            raise RenderError(
                f"template malformed: dim-key declaration {pending!r} declares no "
                f"bullet (the checklist block ends before the next `- ` bullet)"
            )
    if not dims:
        raise RenderError(
            "template malformed: checklist block carries no generic dimension bullets"
        )
    return dims


def _split_consumer_dimensions(section: str) -> list[tuple[str | None, str]]:
    """Split a consumer ``## Audit dimensions`` section into per-dimension entries.

    Each top-level ``- `` bullet (column 0) starts a new dimension; a non-bullet
    or indented continuation line folds into the current dimension's text. A
    ``<!-- dim-key: … -->`` declaration line binds the bullet **immediately below**
    it and is never folded into any dimension's text. Leading prose before the
    first bullet, and blank lines, are ignored. Returns ``(declared-key-or-None,
    single-line text)`` per dimension in file order.

    **The declaration arms fail closed, symmetrically with the generic arm** — a
    stacked declaration, a trailing declaration that binds no bullet, and a
    declaration separated from its bullet all raise with a *consumer-scoped*
    breadcrumb. Silently discarding one of those is the pre-#729 defect wearing a
    different hat: the consumer believes they pinned a durable key while the
    enumeration quietly used the reword-unstable fallback instead, and the loss is
    invisible until a later round's keyset diverges. An *absent* declaration is a
    different thing entirely and stays legal — that is the documented content-derived
    fallback (see `_consumer_key`), not a malformed declaration.
    """
    dims: list[tuple[str | None, str]] = []
    current: list[str] | None = None
    current_key: str | None = None
    pending: str | None = None

    def _flush() -> None:
        if current is not None:
            text = _one_line(" ".join(current))
            if text:
                dims.append((current_key, text))

    for raw in section.splitlines():
        line = raw.rstrip()
        declared = _declared_key(line, _SOURCE_CONSUMER)
        if declared is not None:
            if pending is not None:
                raise RenderError(
                    f"consumer extension malformed: dim-key declaration {pending!r} "
                    f"declares no bullet (another declaration reached before any "
                    f"`- ` dimension bullet); give each bullet its own declaration "
                    f"on the line immediately above it"
                )
            # A declaration terminates the preceding bullet: it belongs to the NEXT
            # one, and folding it into the previous dimension's text would both
            # corrupt that text and lose the binding.
            _flush()
            current = None
            current_key = None
            pending = declared
            continue
        if line.startswith("- "):
            _flush()
            current = [line[2:]]
            current_key = pending
            pending = None
        elif current is not None:
            if line.strip():
                current.append(line)
        elif line.strip() and pending is not None:
            # Adjacency, consumer side (mirrors the generic arm): a blank line is
            # ordinary formatting, any other intervening line breaks the binding.
            raise RenderError(
                f"consumer extension malformed: dim-key declaration {pending!r} is "
                f"not adjacent to its bullet ({line[:60]!r} intervenes); a "
                f"declaration binds only the `- ` bullet immediately below it"
            )
    if pending is not None:
        raise RenderError(
            f"consumer extension malformed: dim-key declaration {pending!r} declares "
            f"no bullet (the `## Audit dimensions` section ends before the next `- ` "
            f"bullet)"
        )
    _flush()
    return dims


def _consumer_key(declared: str | None, text: str) -> str:
    """The insertion-stable key of one consumer dimension (issue #729).

    Precedence, every arm content-derived rather than positional so inserting a
    bullet mid-section never rekeys its siblings (the pre-#729 ``c:<n>`` defect):

    1. an explicit ``<!-- dim-key: … -->`` declaration, when the consumer supplies
       one — the only arm the consumer controls exactly;
    2. the slug of the bullet's bold lead (``- **Name** — …``), which is how this
       repo's own consumer dimensions are written;
    3. a truncated SHA-256 of the dimension's single-line text, for a bullet with
       no bold lead — stable under insertion, and it changes only when the
       dimension's own text changes (which a consumer can pin by adding a
       declaration).
    """
    if declared:
        return f"c:{declared}"
    m = _BOLD_LEAD_RE.match(text)
    if m:
        slug = _name_slug(m.group(1))
        if slug:
            return f"c:{slug}"
    return "c:h" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def consumer_entries(
    section: str, *, strict_derived: bool = True
) -> list[tuple[str, str]]:
    """The consumer dimensions as validated (key, single-line-text) pairs.

    The single owner of "what dimensions does this consumer section declare, and
    what are their keys" — split, key derivation, and the duplicate check together.
    BOTH the key-derivation path (`enumerate_dimensions`) and the rendering path
    (`consumer_dimensions`, for its fail-closed arms) call it, so no consumer-side
    defect can fail one projection while the other renders happily. Both projections call it, so a
    consumer-side duplicate cannot fail the enumeration while the render succeeds.
    """
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for declared, text in _split_consumer_dimensions(section):
        key = _consumer_key(declared, text)
        if key in seen and not declared and not strict_derived:
            # A DERIVED collision on the render path: disambiguate deterministically
            # instead of denying the auditor the prompt (see `consumer_dimensions`).
            key = "c:h" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        if key in seen:
            # Two consumer dimensions resolving to one key would silently coalesce
            # into a single enumerated dimension, and the merged keyset is what
            # coverage totality is checked against — the same defect the generic
            # duplicate arm refuses. Name the remedy, since the file at fault is
            # the consumer's, not this repo's.
            raise RenderError(
                f"consumer extension malformed: duplicate consumer dimension key "
                f"{key!r}; give each colliding bullet its own explicit "
                f"`<!-- dim-key: <lowercase-kebab> -->` declaration to disambiguate"
            )
        seen.add(key)
        entries.append((key, text))
    return entries


def enumerate_dimensions(
    template_path: Path, ext_path: Path
) -> tuple[str, list[tuple[str, str]]]:
    """Return (consumer-status, [(key, text), ...]) — generic then consumer."""
    generic = _generic_dimensions(_load_template(template_path))
    # The RAW projection: this is the one caller that needs the declaration markers.
    status, section = _consumer_section_raw(ext_path, _HOOKS["audit-dimensions"])
    entries = list(generic)
    if status == _STATUS_APPENDED:
        entries.extend(consumer_entries(section))
    return status, entries


def render_enumerate(template_path: Path, ext_path: Path) -> str:
    status, entries = enumerate_dimensions(template_path, ext_path)
    lines = [f"{STATUS_PREFIX} {status}"]
    for key, text in entries:
        lines.append(f"{_DIM_LINE_PREFIX}{key}{_DIM_TEXT_SEP}{text}")
    lines.append(END_MARKER)
    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI.
# --------------------------------------------------------------------------
_KEBAB_ALPHABET = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")


def _kebab_slug(value: str) -> str:
    # Closed-vocabulary slug: lowercase kebab-case only. Rejects any free text.
    # ASCII-only: c.islower()/c.isdigit() accept non-ASCII ('é', 'ß', Arabic-Indic
    # digits), which the "lowercase kebab" contract does not.
    if not value or not all(c in _KEBAB_ALPHABET for c in value):
        raise argparse.ArgumentTypeError(
            f"slug must be lowercase kebab-case (got {value!r})"
        )
    return value


def _sentinel(value: str) -> str:
    # Closed shape: AUDIT-<hex>-OPEN / AUDIT-<hex>-CLOSE (issue-audit-state.py).
    if not (value.startswith("AUDIT-") and value.endswith(("-OPEN", "-CLOSE"))):
        raise argparse.ArgumentTypeError(
            f"sentinel must be an AUDIT-<tag>-OPEN/CLOSE token (got {value!r})"
        )
    return value


def _host_abs_path(value: str, _pathmod=os.path) -> bool:
    """True iff ``value`` is absolute per the interpreter's OWN path module.

    A leading ``/`` on POSIX; a drive-letter or UNC root on Windows (``C:\\``,
    ``C:/``, ``\\\\host\\share``). A rooted path naming no drive (``\\Users\\x``,
    ``/Users/x`` on Windows) is refused on EVERY supported interpreter: ``ntpath.isabs``
    classified that True before 3.13 and False from 3.13, so on a Windows-style
    module absoluteness additionally requires a non-empty drive — which makes the
    verdict version-stable instead of depending on that changed classification.
    Pure: no environment probe and no filesystem access. Mirrored verbatim by
    ``scripts/issue-audit-state.py``'s ``_host_abs_path`` so both path checks agree
    on every input on every supported host (issue #1762 — edited together).
    """
    if not _pathmod.isabs(value):
        return False
    if _pathmod.sep == "\\":  # a Windows-style path module (ntpath)
        return _pathmod.splitdrive(value)[0] != ""
    return True


def _abs_path(value: str, _pathmod=os.path) -> str:
    # Shape check for the path arguments: host-absolute, single-line, no slot token.
    #
    # Deliberately NOT a closed vocabulary, and the claim it supports is scoped to
    # match: a legitimate checkout path can contain spaces and most punctuation, so
    # constraining further would reject real consumers. What this DOES buy is that
    # {DRAFT_PATH} cannot carry a newline — the shape that would let a second line of
    # prose sit in the rendered block as if it were template instructions. A
    # same-line trailer is still expressible; --draft-path is orchestrator-derived
    # from the bound slug, not consumer-supplied, so that residual is accepted and
    # disclosed rather than papered over. See the module docstring, which states the
    # narrow claim (no free-text parameter reaches the rendered block) and not a
    # broad one this check does not implement.
    #
    # Never normalize or rewrite the accepted value (issue #1762): main() opens exactly
    # what _host_abs_path admitted, and a rewrite would make the dispatch bytes diverge
    # from the record issue-audit-state.py regenerates for its digest comparison.
    # Never drop the `{` test: without it render_dispatch's substituted-last invariant
    # would hold only by argument provenance rather than unconditionally.
    #
    # Single-line-ness is tested with `splitlines()` itself, not an `"\n"`/`"\r"`
    # membership pair, because `splitlines()` is what every downstream consumer of the
    # rendered text uses and it breaks on a strictly LARGER set: \v, \f, \x1c, \x1d,
    # \x1e, \x85,  ,  . A path carrying one of those passed the old pair and
    # still split into two lines downstream — the exact shape this check exists to
    # refuse. `value.splitlines() != [value]` is total over that set and also catches a
    # TRAILING separator, which an `in` test on the split result would miss.
    if (
        value.splitlines() != [value]
        or "{" in value
        or not _host_abs_path(value, _pathmod)
    ):
        raise argparse.ArgumentTypeError(
            f"path must be a single-line host-absolute path with no "
            f"'{{' slot token (got {value!r})"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="render-audit-prompt.py",
        description="Render the create-issue Step 3.6 fresh-context audit prompt.",
    )
    parser.add_argument("mode", choices=_MODES)
    parser.add_argument("--slug", type=_kebab_slug)
    parser.add_argument("--draft-path", type=_abs_path)  # absolute path (file arm)
    # issue #709: where the generated dispatch instructions are written. It is
    # rendered INTO the instructions (the auditor is told which file to hash), so
    # it takes the same shape check as every other substituted path.
    parser.add_argument("--instructions-path", type=_abs_path)
    # issue #793: the round's FROZEN dispatch-scope file, on a `targeted` round only. It is
    # named on the command line and never discovered, and the state owner records both its
    # path and its content digest on the dispatch attempt, so the bytes read here are the
    # bytes that round froze.
    parser.add_argument("--scope-file", type=_abs_path)
    parser.add_argument("--sentinel-open", type=_sentinel)
    parser.add_argument("--sentinel-close", type=_sentinel)
    parser.add_argument("--hook", choices=tuple(_HOOKS))
    # NOT typed with _abs_path: the #295 shared contract says an explicit EMPTY
    # value still selects the root-anchored default, and an argparse type would
    # reject "" at rc 2 before main() could apply that default (and rc 2 is not
    # this module's documented rc-1 failure shape). These are read-paths that are
    # never substituted into the rendered block, so they sit outside the
    # docstring's no-free-text claim.
    parser.add_argument("--template-file")  # absolute path override (tests)
    parser.add_argument("--extension-file")  # absolute path override (tests)
    return parser


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: list[str]) -> int:
    _force_utf8_streams()
    parser = build_parser()
    args = parser.parse_args(argv)

    template_path = (
        Path(args.template_file) if args.template_file else _default_template_path()
    )
    ext_path = (
        Path(args.extension_file)
        if args.extension_file
        else _default_extension_path()
    )

    try:
        if args.mode in _DISPATCH_ARMS:
            if args.slug is None:
                raise RenderError(f"--slug is required for the {args.mode} arm")
            if args.mode == "file" and not args.draft_path:
                raise RenderError("--draft-path is required for the file arm")
            if args.mode == "embed" and not (
                args.sentinel_open and args.sentinel_close
            ):
                raise RenderError(
                    "--sentinel-open and --sentinel-close are required for the "
                    "embed arm"
                )
            out = render_dispatch(
                args.mode,
                template_path,
                args.slug,
                args.draft_path,
                args.sentinel_open,
                args.sentinel_close,
                ext_path,
            )
        elif args.mode == "checklist":
            out = render_dispatch(
                "checklist",
                template_path,
                args.slug or "",
                None,
                None,
                None,
                ext_path,
            )
        elif args.mode == "extract":
            if not args.hook:
                raise RenderError("--hook is required for extract mode")
            out = render_extract(args.hook, ext_path)
        elif args.mode == "status-only":
            out = render_status_only(ext_path)
        elif args.mode == "enumerate-dimensions":
            out = render_enumerate(template_path, ext_path)
        elif args.mode == "dispatch-instructions":
            if args.slug is None:
                raise RenderError("--slug is required for dispatch-instructions")
            if not args.draft_path:
                raise RenderError(
                    "--draft-path is required for dispatch-instructions"
                )
            if not args.instructions_path:
                raise RenderError(
                    "--instructions-path is required for dispatch-instructions"
                )
            try:
                draft_text = Path(args.draft_path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                # Fail closed with the SPECIFIC cause rather than rendering a
                # title-less instruction file: an unreadable draft is an
                # unestablished input, and a rendered-anyway file would hash
                # cleanly while carrying less than the authorized set.
                raise RenderError(
                    f"could not read the draft file at {args.draft_path}: {exc}"
                ) from exc
            # Write the producer-owned canonical bytes directly rather than falling
            # through to the shared `out + "\n"` tail below: `instructions_bytes` IS
            # the on-disk contract the state owner regenerates against, so this mode's
            # framing must come from that one function, never from a second site.
            scope_text = None
            if args.scope_file:
                try:
                    scope_text = Path(args.scope_file).read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    # Same fail-closed reasoning as the draft read above: rendering a
                    # scope-less instruction file for a round the tool selected as
                    # `targeted` would hash cleanly while carrying no claims at all —
                    # a vacuous pass with a valid-looking digest.
                    raise RenderError(
                        f"could not read the dispatch-scope file at "
                        f"{args.scope_file}: {exc}"
                    ) from exc
            rendered = instructions_bytes(
                template_path,
                args.slug,
                args.draft_path,
                args.instructions_path,
                draft_text,
                scope_text,
            ).decode("utf-8")
            sys.stdout.write(rendered)
            _emit_dispatch_pointer(rendered)
            return 0
        else:  # unreachable: choices already constrain mode
            raise RenderError(f"unknown mode {args.mode}")
    except RenderError as exc:
        sys.stderr.write(f"render-audit-prompt.py: {exc}\n")
        return 1

    sys.stdout.write(out + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
