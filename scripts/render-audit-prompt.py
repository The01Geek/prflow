#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Render the /prflow:spec Step 3.6 fresh-context audit prompt.

This is the spec sibling of ``scripts/render-grounding-block.sh``: the
single deterministic renderer of a load-bearing prompt surface, so the
orchestrator stops hand-emitting the ~2,000-word audit-instruction block into
every dispatch. The canonical prose lives in the committed template file
``skills/spec/references/audit-prompt-template.md`` (resolved relative
to THIS file, never the cwd — the repo layout and the vendored-plugin layout
both place ``scripts/`` and ``skills/`` as siblings under one root).

Contract (issue #600):

- Writes no file and takes no stdin. The reads are the
  committed template file; the consumer extension — for consumer-dimension
  forwarding — ``.prflow/skill-extensions/spec.md`` (falling back to a present
  superseded ``.prflow/skill-extensions/create-issue.md`` for the create-issue ->
  spec skill rename, and to ``.prflow/prompt-extensions/`` during the issue-#170
  directory transition — the issue-#216 four-candidate order), resolved
  from the git repo root per the #295 SHARED REPO-ROOT CONFIG CONTRACT (a native
  ``git`` subprocess, cwd fallback; never a ``.sh`` exec — the #275 constraint).
- Closed argument surface: closed-vocabulary mode/arm tokens, a kebab-case
  slug, and single-line host-absolute paths (either POSIX or Windows spelling — a
  backslash drive-letter path is admitted; a newline and a ``{`` slot token are
  refused). No free-text parameter reaches any rendered block: every slot filled
  from an argument (``<slug>``, ``{DRAFT_PATH}``) is shape-checked at the parse
  boundary. (``{CONSUMER_DIMENSIONS}`` is the one file-content
  slot; it is filled from committed consumer-extension file content,
  never from an argument, and is substituted LAST so it is never re-scanned.) The ``--template-file`` /
  ``--extension-file`` test overrides are read-paths that are never substituted
  into the block, and are deliberately left untyped so an explicit empty value
  still selects the root-anchored default (the #295 shared contract) — they are
  outside this claim. The path check bounds shape, not vocabulary (see
  ``_abs_path``).
- Modes, complete by construction: the dispatch arms ``file`` (a subagent
  auditor) and ``inline`` (the degraded in-context audit), plus ``checklist``
  (the walk and consumer dimensions, for the drafter's self-audit). Both dispatch
  arms fill ``{RETURN_PATH}`` from the working directory (``return_path``); no
  argument check shapes that directory part.
- Output contract: stdout's FIRST line is ``render-status:`` with a value from
  the closed set {appended, absent, unestablished}; stdout's LAST line is the
  fixed terminal marker ``render-end:`` on every full render, so a truncated
  delivery is positionally detectable: any tail cut drops the terminal marker,
  whatever the render's last block happens to be (the consumer section is last
  only in checklist mode — the dispatch arms follow it with the
  verdict block).
- Failure (any ``RenderError`` or argparse refusal — for example unusable
  arguments, or an unreadable or malformed template) exits non-zero with
  EMPTY stdout and a stderr breadcrumb — which, together with out-of-position
  markers, is the no-contract-output signal the skill's degraded arms key on.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# State-directory resolution (issue #1002): canonical .prflow/, with the LOUD
# transitional fallback to a superseded .devflow/ when only that one is present.
# lib/ sits beside scripts/ in both the source repo and a vendored
# .prflow/vendor/prflow/ tree, so this import path holds on every tier.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
# Nested-repository detection (issue #12): a resolved root with no .prflow/ under
# an ancestor that has one reads built-in defaults while looking configured.
from ancestor_config import warn_ancestor_config as _warn_ancestor_config
from path_forms import host_abs_path, posix_path
from state_dir import STATE_DIR_CURRENT
from state_dir import resolve_state_dir as _resolve_state_dir

STATUS_PREFIX = "render-status:"
END_MARKER = "render-end:"

# Closed vocabularies (complete by construction).
_MODES = ("file", "inline", "checklist")
_DISPATCH_ARMS = ("file", "inline")
_AUDIT_DIMENSIONS_HEADING = "## Audit dimensions"
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


class RenderError(Exception):
    """A renderer failure: exit non-zero, empty stdout, stderr breadcrumb."""


def default_template_path() -> Path:
    """The committed audit-prompt template this renderer reads by default."""
    # Resolve the template relative to THIS file's location, never the cwd, so
    # the vendored-plugin layout (scripts/ and skills/ siblings under the
    # vendor root) resolves identically to the repo checkout.
    return (
        Path(__file__).resolve().parent.parent
        / "skills"
        / "spec"
        / "references"
        / "audit-prompt-template.md"
    )


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
            capture_output=True,
            encoding="utf-8",
        )
    except OSError:
        return None
    root = r.stdout.strip() if r.returncode == 0 else ""
    return root or None


def return_path(slug: str) -> str:
    """The auditor's return file, ``.prflow/tmp/spec/<slug>/issue-audit-<slug>.md``
    under the working directory; a slug ``_kebab_slug`` refuses raises ``RenderError``.

    Never resolve the superseded ``.devflow/`` fallback here: the spec run deletes
    and reads this literal ``.prflow/`` path, so a different directory would hide
    the auditor's return."""
    try:
        _kebab_slug(slug)
    except argparse.ArgumentTypeError as exc:
        raise RenderError(str(exc)) from exc
    return str(Path.cwd() / STATE_DIR_CURRENT / "tmp" / "spec" / slug
               / f"issue-audit-{slug}.md")


def _resolve_extension_path(
    state_dir: str, filename: str, superseded_filename: str | None = None
) -> Path:
    """Resolve one extension, first-present-wins over an ordered candidate list.

    Mirrors scripts/load-prompt-extension.sh's candidate order (issue #216). The
    order is: skill-extensions/<filename>, prompt-extensions/<filename>, then —
    when a superseded skill-rename filename is supplied — skill-extensions/
    <superseded>, prompt-extensions/<superseded>. A selection from the superseded
    prompt-extensions/ directory emits the directory read-through breadcrumb, and a
    selection of the superseded FILENAME emits the skill-rename read-through
    breadcrumb naming /prflow:init — both decided with path tests only.
    """
    base = Path(state_dir)
    canonical = base / "skill-extensions" / filename
    candidates = [canonical, base / "prompt-extensions" / filename]
    if superseded_filename is not None:
        candidates += [
            base / "skill-extensions" / superseded_filename,
            base / "prompt-extensions" / superseded_filename,
        ]
    chosen = None
    for cand in candidates:
        if cand.exists() or cand.is_symlink():
            chosen = cand
            break
    if chosen is None or chosen == canonical:
        # No fallback taken: the canonical (present or the absent no-op path).
        return canonical
    if chosen.parent.name == "prompt-extensions":
        sys.stderr.write(
            f"render-audit-prompt.py: reading from the superseded extension directory "
            f"{str(chosen.parent)!r} — run /prflow:init to migrate it to "
            f"{str(canonical.parent)!r} (transitional read-through; removed once no "
            f"consumer still carries a .prflow/prompt-extensions/ directory)\n"
        )
    if superseded_filename is not None and chosen.name == superseded_filename:
        sys.stderr.write(
            f"render-audit-prompt.py: reading the superseded extension {str(chosen)!r} "
            f"for the renamed 'spec' skill — run /prflow:init to migrate it, or rename "
            f"it to {filename!r} (transitional read-through; removed once no consumer "
            f"still carries a {superseded_filename})\n"
        )
    return chosen


def _default_extension_path() -> Path:
    root = _repo_root()
    if root is not None:
        _warn_ancestor_config(root, "render-audit-prompt.py", "pass --extension-file <path>")
        return _resolve_extension_path(_resolve_state_dir(root), "spec.md", "create-issue.md")
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
    return _resolve_extension_path(_resolve_state_dir(str(cwd)), "spec.md", "create-issue.md")


# --------------------------------------------------------------------------
# Consumer extension delivery triage + section extraction.
#
# The triage mirrors scripts/load-prompt-extension.sh (a coupled pair):
#   present regular readable file          -> read text, extract section
#   absent / present-but-empty             -> no section  (status absent)
#   present-but-unreadable / broken symlink
#     / present-but-non-regular file       -> unestablished (never "absent")
# --------------------------------------------------------------------------
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
        # lstripped test would recognize INDENTED fences the loader treats as ordinary
        # text, so a consumer section wrapping a column-0 `## ` heading in an indented
        # fence would make the renderer and the loader forward different bodies at the
        # same `appended` status.
        if line.startswith(("```", "~~~")):
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


def consumer_dimensions(ext_path: Path) -> tuple[str, str]:
    """Return (status, consumer ``## Audit dimensions`` section text)."""
    state, text = _read_extension(ext_path)
    if state == "unestablished":
        return (_STATUS_UNESTABLISHED, "")
    if state == "absent":
        return (_STATUS_ABSENT, "")
    section = extract_section(text, _AUDIT_DIMENSIONS_HEADING)
    if not section:
        return (_STATUS_ABSENT, "")
    return (_STATUS_APPENDED, section)


# --------------------------------------------------------------------------
# Template parsing / block selection.
# --------------------------------------------------------------------------
def _parse_blocks(template_text: str) -> list[tuple[frozenset[str], str]]:
    """Parse the template into (arm/mode set, body) blocks in file order.

    Text outside any block is ignored (it is the human-facing documentation of
    slots and the extraction rule, for the degraded manual arm). A missing
    close marker is a template defect -> RenderError.
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


def _dimensions_block_for_status(status: str, section: str) -> str:
    if status == _STATUS_APPENDED:
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

    Fail-closed on emptiness: a mode that selects no block (or only blank ones)
    would otherwise emit a positionally-valid two-marker render carrying no
    instructions at all, which the delivery check cannot detect.
    """
    parts = [
        _substitute(body, slots).strip("\n")
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
    ext_path: Path,
) -> str:
    """Assemble a full render for a dispatch arm (``mode`` in _DISPATCH_ARMS) or
    the walk and consumer dimensions alone (``mode == "checklist"``). ``mode`` doubles as the
    block-selection token."""
    if mode in _DISPATCH_ARMS and not draft_path:
        raise RenderError(f"--draft-path is required for the {mode} arm")
    blocks = _parse_blocks(_load_template(template_path))
    status, section = consumer_dimensions(ext_path)
    # `{CONSUMER_DIMENSIONS}` is substituted LAST (dict-insertion order): the
    # consumer-extension text spliced in is then never re-scanned for `<slug>` /
    # `{DRAFT_PATH}` / `{RETURN_PATH}` tokens it may legitimately contain. Keep it last.
    slots = {
        "<slug>": slug,
        "{DRAFT_PATH}": posix_path(draft_path) if draft_path else "",
        "{RETURN_PATH}": posix_path(return_path(slug)) if mode in _DISPATCH_ARMS else "",
        "{CONSUMER_DIMENSIONS}": _dimensions_block_for_status(status, section),
    }

    inner = _assemble(blocks, mode, slots, template_path)
    return f"{STATUS_PREFIX} {status}\n{inner}\n{END_MARKER}"


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


def _abs_path(value: str, _pathmod=os.path) -> str:
    # Shape check for the path arguments: host-absolute, single-line, no slot token.
    #
    # Deliberately NOT a closed vocabulary, and the claim it supports is scoped to
    # match: a legitimate checkout path can contain spaces and most punctuation, so
    # constraining further would reject real consumers. What this DOES buy is that
    # {DRAFT_PATH} cannot carry a newline — the shape that would let a second line of
    # prose sit in the rendered block as if it were template instructions. A
    # same-line trailer is still expressible; --draft-path is orchestrator-derived
    # from the run's slug, not consumer-supplied, so that residual is accepted and
    # disclosed rather than papered over. See the module docstring, which states the
    # narrow claim (no free-text parameter reaches the rendered block) and not a
    # broad one this check does not implement.
    #
    # Preserve the accepted spelling (issue #1762) so main() opens the admitted path,
    # not a rewritten path that may name a different file. Keep the `{` test so
    # render_dispatch's substituted-last invariant does not rely on argument provenance.
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
        or not host_abs_path(value, _pathmod)
    ):
        raise argparse.ArgumentTypeError(
            f"path must be a single-line host-absolute path with no "
            f"'{{' slot token (got {value!r})"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="render-audit-prompt.py",
        description="Render the spec Step 3.6 fresh-context audit prompt.",
    )
    parser.add_argument("mode", choices=_MODES)
    parser.add_argument("--slug", type=_kebab_slug)
    parser.add_argument("--draft-path", type=_abs_path)  # absolute path (dispatch arms)
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
        Path(args.template_file) if args.template_file else default_template_path()
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
            out = render_dispatch(
                args.mode,
                template_path,
                args.slug,
                args.draft_path,
                ext_path,
            )
        elif args.mode == "checklist":
            out = render_dispatch(
                "checklist",
                template_path,
                args.slug or "",
                None,
                ext_path,
            )
        else:  # unreachable: choices already constrain mode
            raise RenderError(f"unknown mode {args.mode}")
    except RenderError as exc:
        sys.stderr.write(f"render-audit-prompt.py: {exc}\n")
        return 1

    sys.stdout.write(out + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
