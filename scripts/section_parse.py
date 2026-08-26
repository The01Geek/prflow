#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Shared markdown section- and checkbox-parsing rules (issue #781).

SINGLE SOURCE for the `## Acceptance Criteria` parsing contract that two
helpers depend on:

  * `scripts/parse-acs.py` — reads an ISSUE BODY at mirror time and renders the
    checkbox block Phase 1.2 splices into the workpad.
  * `scripts/workpad.py` — reads that same section back OUT of the workpad
    comment (and out of an issue body) for the review engine's Phase 0.4.

Before this module the rules lived only in `parse-acs.py`, so the second reader
would have had to re-implement them and the two could silently disagree about
what a section even is. Keeping them here means a rule change lands once.

This module is IMPORTED IN-PROCESS by both callers, never exec'd as a subprocess
and never reached through a `.sh` hop: Windows refuses to exec a shell helper
from Python ([WinError 193], issue #275). Both callers add their own directory to
`sys.path` before importing it — running them as scripts would put `scripts/`
there anyway, but a consumer that loads them through
`importlib.util.spec_from_file_location` (how `lib/test/test_python_scripts.py`
drives this directory) would not.

Stdlib-only and side-effect-free: no `gh`, no `subprocess`, no environment
reads, no stream reconfiguration. I/O and the post-merge TRIGGER-PHRASE
classifier stay with the callers — `parse-acs.py` owns trigger classification
because it is a mirror-time-only rule, while `workpad.py` only ever reads a tag
that is already present in the stored text.

The parsing contract, stated once:

  * A section opens at the first heading whose text equals the requested name
    case-insensitively (no trailing colon, no extra words) at level `##` or
    `###`.
  * It terminates at the next heading whose level is equal to or shallower than
    the opening heading's, so a deeper sub-heading inside the section does not
    end it and end-of-input does.
  * Inside it, `- [ ]`, `- [x]`, `* [ ]` and `* [x]` are checkbox items.
  * An indented, non-blank, non-checkbox line continues the preceding item (a
    criterion hard-wrapped at ~80 columns round-trips as one string); a blank
    line or a non-indented non-checkbox line closes it.

Distinguishing "section absent" from "section present but unreadable" (issue
#1198): only checkbox list items are recognised as items, so a section written
as bold paragraphs (`**AC1 — …**`) or a numbered list (`1. …`) yields zero
items even though it is present and full of content. That is a distinct state
from a body that carries no such section at all, and the two must not be
collapsed (the repo's *unknown is not zero* convention). This module does not
own the signal — it keeps its two primitives orthogonal: `extract_section`
returns `[]` for an absent section and a non-empty line list for a present one,
`parse_checkboxes` returns the items. A caller distinguishes the unreadable case
by combining them — a non-empty section-line list (with at least one non-blank
line) plus zero parsed items — and `scripts/parse-acs.py` does exactly that,
emitting an item-shape stderr diagnostic and an `acceptance_criteria_unreadable`
JSON field for it while still exiting 0.
"""

import re

# The ` (post-merge)` tag `parse-acs.py` synthesizes at mirror time. Exported so
# `workpad.py`'s reviewer-facing filter tests for the SAME literal the mirror
# writes, instead of re-spelling it at the read site where a drift would
# silently stop excluding post-merge criteria.
POST_MERGE_TAG = ' (post-merge)'

CHECKBOX_RE = re.compile(r'^\s*[-*]\s+\[([ xX])\]\s+(.*)$')
HEADING_RE = re.compile(r'^(#{1,6})\s+(.*?)\s*$')

_WS_RE = re.compile(r'\s+')


def extract_section(body: str, name: str) -> list[str]:
    """Return the list of lines inside the named section, or [] if not found.

    Stops at the next heading whose level is equal to or higher than the
    section's heading. The FIRST matching heading opens the section, and
    duplicates of it are not special-cased — they are just headings, so which
    rule applies depends on their level:

      * A second copy at the SAME (or a shallower) level ends the section like
        any other such heading, and its own content is excluded entirely along
        with everything after it. `## AC / one / ## Notes / ## AC / two` yields
        only `one`'s lines — `two` is dropped.
      * A DEEPER duplicate (e.g. `###` under a `##`) does not end the section,
        so its lines are read as part of the first section. `## AC / one /
        ### AC / two` yields both `one` and `two`.
    """
    lines = body.splitlines()
    out: list[str] = []
    section_level = None
    for line in lines:
        m = HEADING_RE.match(line)
        if m:
            level, heading = len(m.group(1)), m.group(2).strip()
            if section_level is None:
                if heading.lower() == name.lower() and level in (2, 3):
                    section_level = level
                continue
            if level <= section_level:
                break
        elif section_level is not None:
            out.append(line)
    return out


def parse_checkboxes(section_lines: list[str]) -> list[dict]:
    """Parse checkbox items, joining hard-wrapped continuation lines.

    Returns `{'text': str, 'ticked': bool}` dicts. Post-merge classification is
    deliberately NOT applied here: `parse-acs.py` adds a `post_merge` key from
    its trigger-phrase list at mirror time, while `workpad.py` reads a tag that
    is already in the text. Splitting them keeps the trigger list out of the
    read path, where re-classifying would re-tag criteria the run had already
    deliberately demoted.
    """
    items: list[dict] = []
    current = None
    for line in section_lines:
        m = CHECKBOX_RE.match(line)
        if m:
            current = {'text': m.group(2).strip(), 'ticked': m.group(1).lower() == 'x'}
            items.append(current)
        elif current is not None and line[:1] in (' ', '\t') and line.strip():
            # Indented, non-blank, non-checkbox line → continuation of `current`.
            current['text'] = f"{current['text']} {line.strip()}".strip()
        else:
            # Blank line or a non-indented non-checkbox line closes the item.
            current = None
    return items


def render_line(item: dict, *, neutralize_box: bool = False) -> str:
    """Render one parsed item back to a checkbox line.

    Renders the text VERBATIM — it never appends a ` (post-merge)` tag.
    Synthesizing that tag is `parse-acs.py`'s mirror-time job
    (`_render_md_line`); doing it here as well would re-tag a criterion on every
    read-back, defeating the orchestrator's per-criterion demote authority.

    `neutralize_box=True` renders every item unticked. Phase 0.4 uses it for the
    reviewer-facing value: a tick is the code author's own assertion that the
    criterion is satisfied, so shipping the box column would hand the
    merge-gating judge a specification pre-annotated by the party it is judging.
    """
    ticked = False if neutralize_box else bool(item.get('ticked'))
    return f"- [{'x' if ticked else ' '}] {item['text']}"


def is_post_merge_tagged(text: str) -> bool:
    """True when `text` already carries the mirror-time ` (post-merge)` tag.

    A plain suffix test against the stored text — never a re-run of
    `parse-acs.py`'s trigger-phrase classifier, which would re-derive the tag
    from wording and so disagree with what the run actually recorded.
    """
    return text.rstrip().endswith(POST_MERGE_TAG)


def normalize_criterion(text: str) -> str:
    """Normalize a criterion for set comparison across the two surfaces.

    Strips the ` (post-merge)` tag and collapses every whitespace run to one
    space. Tick state is not represented here at all (callers compare the
    normalized TEXT, so box state is ignored by construction).

    Without this the two surfaces are structurally unequal on EVERY implement
    PR — the workpad section carries post-merge tags the issue body does not,
    and hard wrapping differs between them — so a raw-text comparison would
    report divergence every time and carry no signal.
    """
    stripped = text.strip()
    stripped = stripped.removesuffix(POST_MERGE_TAG.strip())
    return _WS_RE.sub(' ', stripped).strip()
