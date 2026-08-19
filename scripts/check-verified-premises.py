#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Re-check a drafted issue's `Verified:` premises against the current tree.

A `Verified:` bullet is the single most load-bearing line in a DevFlow issue: it
is what licenses an implementing run to skip its own investigation. Those
bullets are true *when the issue is drafted*, and nothing re-checks them when
the issue is later implemented — so a premise that has since become false
converts "go and check" into "this was already checked", and the run builds
confidently on it. Issue #857 is the worked case: three of its premises were
false by the time #864 implemented it, and two acceptance criteria were
literally unimplementable.

This helper is the mechanical half of the fix (issue #868). It has two
consumers, both of which read the same output:

  * `/devflow:create-issue` (drafting side) — does every load-bearing bullet
    carry a self-contained *re-derivation handle*, so that re-checking is
    mechanical rather than a re-investigation? A `handle=none` bullet is the
    drafting defect.
  * `/devflow:implement` Phase 1.6 Pass 6 (implement side) — does each premise
    still hold against the tree this run will build on?

WHAT IT DOES NOT DO — the security boundary. The issue body is third-party text
that anyone able to comment can influence. This helper therefore performs
**read-only file reads and nothing else**: it never executes a command drawn
from the body, spawns no subprocess, and makes no network call. A bullet whose
handle is a command is *reported* so the caller can re-run it under its own
judgment; the helper declines to decide it. That is why the module imports no
`subprocess`.

**The asymmetry that governs every arm below.** Refuting a premise is the one
verdict this helper is least entitled to assert cheaply: on a refutation the
implementing run *discards* the premise and records issue-accuracy feedback
against the issue. So a refutation requires a claim the helper positively
adjudicated, and everything it merely guessed at resolves to `unestablished`,
which costs only an investigation the run would have done anyway.

Handle classes (the label printed as `handle=`):

  path-quote  a cited repository path AND a quoted sentence — the strongest
              handle, and the only one whose *content* is adjudicated rather
              than merely the path's presence
  path        a cited path with no quoted sentence — presence is checkable, but
              presence is not the premise, so this never reports `holds`
  quote       a quoted sentence naming no path — no domain to search, so the
              helper reports it rather than guessing
  command     a backticked command — reported, never executed
  none        prose asserting a premise with no handle at all; this is the
              shape #857's three false premises took

States (`state=`):

  holds          the premise re-derives against the tree right now
  refuted        a cited file is gone, or a quoted sentence no longer occurs in
                 it — discard the premise and investigate
  unestablished  the helper could not decide — no handle, a handle it declines
                 to execute, or a claim it can only guess at; fall back to
                 ordinary investigation

`unestablished` is deliberately NOT an error: unknown is not zero, and it is
also not a failure. It downgrades the bullet to "go and check", which is the
state the run would have been in with no bullet at all.

Usage:
    check-verified-premises.py --body-file PATH [--repo-root PATH]

Exit codes:
  0  ran and decided; no premise was refuted (this includes a body with no
     bullets at all, and a body whose bullets are merely unestablished)
  2  at least one premise was REFUTED — one refutation dominates the exit code
     even when other bullets hold
  3  the measurement could not be established at all — the body file could not
     be read, it was empty, the repository root was unusable, the invocation
     itself was bad, or an unexpected internal error occurred. Never conflated
     with a clean pass, and deliberately distinct from 2: a caller who could
     not run the check has not thereby discovered a stale premise.

Every terminating path prints a `VERIFIED_PREMISES ` line, so a caller may
treat that line's ABSENCE as "this did not run" rather than inferring anything
from the exit code alone.

On the normal (non-unavailable) path the adjudicated output is followed by the
non-adjudicating ungraded-claim pass (issue #1634): zero or more
`ungraded_claim=<n> region=… phrase=… detail=…` lines and one
`UNGRADED_CLAIMS total=<n>` summary. These report a verification asserted in a
shape the `Verified:` marker does not grade; they carry no state token, never
move the exit code, and their `detail=` is the opaque trailing sentence text.
When the pass itself fails, the summary is `UNGRADED_CLAIMS unavailable
reason=internal-error detail=…` instead — never `total=0`, which would be
byte-identical to a clean "found none" — and the adjudicated output above it
and the exit code are both unchanged.
"""

import argparse
import bisect
import re
import sys
import traceback
from pathlib import Path
from typing import NamedTuple

# Import `section_parse` IN-PROCESS — never through a `.sh`/subprocess hop,
# which fails on Windows ([WinError 193]) and breaks this module's
# no-subprocess boundary. The path insert is what makes that import resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from section_parse import HEADING_RE, extract_section  # noqa: E402

# The exit codes, named rather than spelled as bare integers at the seven
# terminating sites. The 2-vs-3 distinction is this module's central discipline
# — 2 makes the implementing run discard a premise and file accuracy feedback,
# 3 only sends it to the investigation it would have done anyway — and a bare
# `return 2` reads identically to a bare `return 3` at the call site.
EXIT_CLEAN = 0
EXIT_REFUTED = 2
EXIT_UNESTABLISHED = 3


class CitedPath(NamedTuple):
    """One path citation mined from a bullet.

    A named triple rather than a bare tuple because `strength` is the field the
    refutation gate reads (`== 'strong'`) and `bare` is the one every existence
    check and file read resolves — a positional reorder of two same-typed `str`
    fields would silently adjudicate the strength of a path and the presence of
    a strength label, and no test asserting behaviour on well-formed input
    would catch it. With names, that mistake is an `AttributeError` instead.
    """

    strength: str
    bare: str
    suffix: str


# The `Verified` marker, in the shapes filed DevFlow issues actually carry.
# Matching only `**Verified:**` found zero bullets in bodies using any other
# spelling and reported a vacuous clean pass. But widening it to any bolded run
# beginning with the word `Verified` mints PHANTOM bullets out of ordinary
# prose — "We **Verified that** `x/y.sh` exists" is not a premise bullet, and a
# phantom that cites a missing path reaches `refuted`, writing a false accuracy
# accusation back to the issue. So the alternatives are split by position:
#
#   A (anywhere)     the pure label `**Verified**` / `**Verified:**` — this is
#                    the form that legitimately appears mid-sentence
#   B (line start)   a line or list item OPENING with `Verified:`, bolded,
#                    backticked or bare
#   C (item start)   a bolded run opening a list item, whose first word is
#                    `Verified` — covers `**Verified baseline**` and the
#                    backtick-inside-bold `**`Verified:` …**` form
#
# DISCLOSED RESIDUAL, on both over-recognising arms: arm C cannot distinguish a
# label from a bolded *sentence* that opens a list item with the word Verified,
# and arm B matches any line opening `Verified:` — including one inside a fenced
# code block or a table cell. Either can mint a bullet that is not one. The
# recognised set is a floor, not a closed set, in BOTH directions — an
# unrecognised spelling is invisible, and arms B and C may over-recognise. The
# damage from an over-recognition is bounded by the rest of the module: a
# phantom reaches `refuted` only by citing a strong path genuinely absent from
# the tree.
_MARKER = re.compile(
    r'\*\*[ \t]*Verified[ \t]*:?[ \t]*\*\*[ \t]*:?'
    r'|(?m:^[ \t]*(?:[-*+]|\d+[.)])?[ \t]*(?:\*\*[ \t]*)?`?Verified`?[ \t]*:)'
    r'|(?m:^[ \t]*(?:[-*+]|\d+[.)])[ \t]*\*\*[`\s]*Verified\b[^*\n]*\*\*:?)')

# A backticked span. The template mandates backticks for the *path* handle, and
# a command handle is conventionally backticked too; an unbackticked path
# mentioned in running prose is deliberately not mined, because doing so would
# manufacture handles out of ordinary sentences. The cost is that a bullet whose
# command is written bare classifies as `none` — a drafting nit the consumers
# surface rather than a silent miss.
_BACKTICKED = re.compile(r'`([^`\n]+)`')

# A double-quoted sentence, in either the ASCII or the typographic form. Single
# quotes are excluded on purpose: they occur inside shell commands
# (`grep -c '^tombstone:'`) far more often than they delimit a quoted premise.
# The 8-character floor keeps short quoted words from being adjudicated as
# premises; a bullet whose only quotation is shorter degrades to `handle=path`,
# which no longer reports `holds`.
_QUOTED = re.compile(r'["“]([^"“”]{8,})["”]')

# The minimum length of an ELIDED quotation's fragment. `_QUOTED`'s floor
# applies to the whole quotation; each fragment of an elided one is matched
# independently, so it needs its own floor or short common words would resolve
# against any file.
_MIN_FRAGMENT = 8

# A file extension, used only as the WEAK arm of path detection — see
# `_path_strength`.
_EXTENSION = re.compile(r'\.[A-Za-z0-9]{1,6}$')

# A shell/glob metacharacter. A span carrying one names a SET of paths, not a
# path, so it is not adjudicable by a single existence check — and adjudicating
# it as one produced false refutations against real issue bodies, which cite
# `.prflow/prompt-extensions/*.md`-style patterns routinely.
_GLOBBY = re.compile(r'[*?\[\]]')

# The start of the next markdown list item. A bullet's span must stop here as
# well as at a blank line: filed issues put consecutive `Verified:` bullets on
# adjacent list-item lines with no blank line between them, so a span bounded
# only by the next MARKER runs past its own item and into the following item's
# leading prose — mining that item's cited paths as if this bullet had cited
# them, and then refuting this bullet's quotation against the wrong file.
_NEXT_ITEM = re.compile(r'\n[ \t]*(?:[-*+]|\d+[.)])\s')

# An ellipsis inside a quotation: the author elided text. Such a quotation is
# not verbatim, so it is adjudicated fragment-by-fragment and a miss on it can
# never refute — see `recheck`. Elision is detected from the RAW quote, not from
# the fragment count: a leading or trailing ellipsis yields a single fragment,
# and counting fragments would route that back to the refuting arm.
_ELISION = re.compile(r'\s*(?:…|\.\.\.)\s*')

# A locator suffix appended to a path: a pytest node id (`::test_name`), a
# markdown/URL anchor (`#section`), or a line reference (`:42`). The FILE part
# is adjudicable; the suffix is not, so it is stripped for the presence check
# and its presence downgrades the verdict — see `_split_locator`.
_LOCATOR_SUFFIX = re.compile(r'(::.+|#.+|:\d+(?:-\d+)?)$')

# Why the undecidable handles cannot be adjudicated, keyed by handle. Module
# level so the vocabulary sits beside the patterns that produce it, and so the
# set of undecidable handles has exactly one definition.
_UNDECIDABLE_REASONS = {
    'quote': 'quoted sentence names no path to search',
    'command': 'command handle reported, never executed',
    'none': 'no re-derivation handle in the bullet',
}

# --- Ungraded-claim detection (issue #1634) --------------------------------
# The non-adjudicating pass below must share no STATE token (`holds`,
# `refuted`, `unestablished`) with the adjudicated vocabulary above, or a
# downstream verdict parser scanning both would mis-tally.

# Do not widen this tuple to catch a verification worded outside it ("I checked
# this"): the missed detection is the deliberate low-false-positive floor.
_COLLOCATION_FAMILY = (
    'verified against', 'confirmed against', 'checked against',
    'verified at drafting time')
# The letter guards keep `verified against` from matching inside `unverified
# against`. They are lookarounds, not `\b`, so `match.group(0)` stays the bare
# phrase the report line prints.
_COLLOCATION_RE = re.compile(
    '(?<![A-Za-z])(?:{})(?![A-Za-z])'.format(
        '|'.join(re.escape(phrase) for phrase in _COLLOCATION_FAMILY)),
    re.IGNORECASE)

# `_premise_regions` adds every heading line as a fourth region; everything else
# is the unscanned residual complement, so do not read this tuple as whole-body
# coverage.
_PREMISE_SECTIONS = ('Current Behavior', 'Technical Context',
                     'Implementation Notes')

# A collocation inside a fenced block is data, not a premise. `_FENCE_RE` also
# gates heading detection in `_premise_regions`, so a fenced `##`-shaped line
# does not falsely close a real section.
_FENCE_RE = re.compile(r'^[ \t]*(?:`{3,}|~{3,})')

# An inline code span. The issue that DEFINES the collocation family as data
# would otherwise trip its own detector — this exclusion is load-bearing.
_INLINE_CODE_RE = re.compile(r'`[^`\n]+`')


def normalize(text: str) -> str:
    """Collapse a fragment to the form both sides of a quote match compare in.

    Three normalizations, each closing a way a TRUE premise would otherwise
    read as refuted:

    * whitespace runs collapse to a single space, so a sentence the source file
      wraps across lines still matches the issue's single-line quotation;
    * typographic quotes and dashes fold to ASCII, because GitHub's editor and
      most authoring tools substitute them silently;
    * markdown emphasis (`*` and backticks) is stripped, because a quotation
      lifted out of a prose file keeps the emphasis the source rendered with,
      which the plain source text does not contain.
    """
    folded = (text.replace('“', '"').replace('”', '"')
                  .replace('‘', "'").replace('’', "'")
                  .replace('—', '-').replace('–', '-'))
    stripped = folded.replace('*', '').replace('`', '')
    return ' '.join(stripped.split())


def _split_locator(span: str) -> tuple:
    """Split a cited span into `(path_part, suffix)`.

    A path cited with a pytest node id, an anchor, or a line number names a
    file plus a location *inside* it. The file part is adjudicable by an
    existence check; the location is not — so the suffix is stripped here and
    its presence is carried into the verdict, because a present file whose
    cited symbol may have moved is not evidence the premise drifted.
    """
    match = _LOCATOR_SUFFIX.search(span)
    if not match or match.start() == 0:
        return span, ''
    return span[:match.start()], match.group(0)


def _path_strength(span: str) -> str:
    """Classify a backticked span as a `strong` path, a `weak` one, or `no`.

    The distinction is what stops a *guess* from becoming a *refutation*. A
    span carrying a directory separator is a **strong** path claim: little else
    in an issue body looks like `lib/test/run.sh`. A span that merely ends in a
    dotted tail is **weak**, because so do the identifiers this repo's own
    issues are full of — `spec.loader`, `p.name`, `config.json`. Reporting "no
    such file" about one of those as `refuted` would tell the run to discard a
    true premise and record false issue-accuracy feedback against the issue, so
    a missing *weak* path resolves to `unestablished` instead (see `recheck`).

    Three prefixes are rejected outright rather than adjudicated. An
    **absolute** path (`/`) is the load-bearing one: the span is third-party
    text, and `Path(root) / "/etc/passwd"` discards `root` entirely under
    pathlib's join semantics, so an absolute span would silently point the read
    outside the tree (`_resolves_inside` closes the traversal half of the same
    hole). A `-` prefix is flag-shaped and a `~` prefix is home-relative;
    neither is a repository path. A **glob** span names a set rather than a
    path and so is not adjudicable by an existence check at all. A span
    carrying a **URL scheme** (`https://…`) is likewise not a repository path,
    and its slashes would otherwise read as the strongest possible path claim.

    A slash alone is not enough for `strong`. Issue bodies carry slash-bearing
    NON-path tokens routinely — a git ref (`origin/main`, `feature/x`) most of
    all — and adjudicating one as a strong path sends a premise that still
    holds to the missing-strong-path arm, which **refutes**: the run discards a
    true premise and files inaccuracy feedback against the issue, the exact
    harm this whole asymmetry exists to prevent. So `strong` additionally
    requires the span to look like a path at its tail: a filename-shaped final
    segment (a dotted extension) or an explicit trailing `/` marking a
    directory. Everything else slash-bearing degrades to `weak`, which can
    still be read and adjudicated but can never refute. The cost is that a
    genuinely-deleted extensionless directory cited without a trailing slash
    now resolves `unestablished` rather than `refuted` — the deliberate
    direction of this module's asymmetry, where an unrefuted true premise is
    always preferred to a refuted one that holds.
    """
    if not span or any(c.isspace() for c in span):
        return 'no'
    if span.startswith('-') or span.startswith('/') or span.startswith('~'):
        return 'no'
    if _GLOBBY.search(span) or '://' in span:
        return 'no'
    bare, _ = _split_locator(span)
    if '/' in bare:
        if bare.endswith('/') or _EXTENSION.search(bare.rsplit('/', 1)[-1]):
            return 'strong'
        return 'weak'
    return 'weak' if _EXTENSION.search(bare) else 'no'


def _resolves_inside(root: Path, rel: str) -> bool:
    """True when `rel` stays inside `root` once `..` segments are resolved.

    The cited path comes from the issue body, so `../../../etc/passwd` is an
    input this helper must expect rather than trust. Escaping reads are
    refused outright: a premise about a file outside the repository is not a
    premise about the tree this run builds on.
    """
    try:
        candidate = (root / rel).resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    return candidate == root or root in candidate.parents


def _is_command(span: str) -> bool:
    """True when a backticked span is a command rather than a path.

    Structural, not a name allowlist. An earlier draft matched the span's first
    word against a hardcoded set of tool names, which rotted in two directions
    at once: a consumer repo's own toolchain (`npm test`, `cargo test`,
    `pytest -k x`) fell outside the set and its best-grounded bullets were
    reported as carrying no handle at all, while a bare tool name sitting in
    ordinary prose was reported as a command handle — laundering exactly the
    handle-less shape #857's three false premises took. Multi-token *is* the
    discriminator: a repository path never contains whitespace, and a command
    almost always does.
    """
    return bool(span.strip()) and any(c.isspace() for c in span.strip())


def _bullet_bound(rest: str) -> int:
    """Offset within `rest` where a bullet's span ends.

    The earliest of the next marker, the next list item, or a blank line — the
    three bounds `parse_bullets` documents. Shared with `_graded_spans` so the
    ungraded pass subtracts exactly the span the adjudication mined.
    """
    limit = len(rest)
    for bound in (_MARKER.search(rest), _NEXT_ITEM.search(rest)):
        if bound is not None:
            limit = min(limit, bound.start())
    blank = rest.find('\n\n')
    if blank != -1:
        limit = min(limit, blank)
    return limit


def parse_bullets(body: str) -> list:
    """Return one text span per `Verified:` bullet, in document order.

    A bullet's span runs from its marker to whichever comes first: the next
    marker, a blank line, or the start of the next list item. All three bounds
    are load-bearing, and each closes the same failure — a span that runs past
    its own bullet mines the *following* text's backticked paths as if this
    bullet had cited them, and then refutes this bullet's quotation against a
    file it never named. Several filed issues place the marker mid-sentence
    inside a longer paragraph (the blank-line bound), and place consecutive
    bullets on adjacent list-item lines with no blank line between them (the
    list-item bound, observed on issue #857).

    DISCLOSED RESIDUAL, the converse of those three bounds: a plain
    continuation line — non-blank, not a list item, carrying no marker — is
    absorbed into the span, so its backticked paths and quotations are
    adjudicated as this bullet's. That is deliberate for the shape it was
    chosen for (a soft-wrapped bullet, which markdown itself treats as one
    item, and whose citations therefore genuinely are the bullet's), and it is
    why the bound is not a hard newline: bounding at `\\n` would sever every
    wrapped bullet from its own citation and refute a TRUE premise against a
    file it did cite — a miss in the dangerous direction, which this module
    trades away everywhere else. The cost of the trade is the other shape:
    where a following line is a genuinely separate claim that markdown still
    reads as a continuation, a strong path cited *there* can drive `refuted`
    on a bullet that did not cite it. Bounded — the neighbouring cases
    (adjacent bullets, separated paragraphs, a following marker) each have
    their own bound above — but real, and unpinned by construction: it is not
    decidable from the text which of the two shapes an author meant.
    """
    return [rest[:_bullet_bound(rest)]
            for rest in (body[m.end():] for m in _MARKER.finditer(body))]


def classify(span: str) -> tuple:
    """Return `(handle, paths, quotes)` for one bullet span.

    `paths` carries each cited path as a `CitedPath`, so `recheck` can tell a
    confident path claim from a guess and can tell a whole-file citation from
    one naming a location inside the file.
    """
    paths, commands = [], []
    for backticked in _BACKTICKED.findall(span):
        if _is_command(backticked):
            # A command span is never mined for a path even though it usually
            # contains one — `grep -c '^x' lib/test/f.tsv` names a file, but
            # the premise is the command's *result*, which this helper will
            # not execute to obtain.
            commands.append(backticked)
            continue
        strength = _path_strength(backticked)
        if strength != 'no':
            bare, suffix = _split_locator(backticked)
            paths.append(CitedPath(strength, bare, suffix))
    quotes = _QUOTED.findall(span)
    if paths and quotes:
        handle = 'path-quote'
    elif paths:
        handle = 'path'
    elif quotes:
        handle = 'quote'
    elif commands:
        handle = 'command'
    else:
        handle = 'none'
    return handle, paths, quotes


def recheck(handle: str, paths: list, quotes: list, root: Path) -> tuple:
    """Adjudicate one bullet against the tree. Returns `(state, detail)`."""
    if handle in _UNDECIDABLE_REASONS:
        # No domain to read, or a handle this helper declines to execute. The
        # premise is not refuted — it is simply undecided, which routes the
        # caller to ordinary investigation.
        return 'unestablished', _UNDECIDABLE_REASONS[handle]

    escaping = [p.bare for p in paths if not _resolves_inside(root, p.bare)]
    if escaping:
        # Not refuted — refused. A premise pointing outside the repository is
        # not a premise about the tree this run builds on, and the helper
        # declines to read it rather than answering about a file it should
        # never have opened.
        return 'unestablished', ('cited path resolves outside the repository, '
                                 'refused: ' + ','.join(escaping))

    # Presence, not file-ness. A directory citation (`skills/review/phases/`) is
    # a strong span that exists, and testing `is_file()` reported it absent —
    # a false refutation against a shape this repo's own issue bodies use
    # constantly.
    missing = [p for p in paths if not (root / p.bare).exists()]
    if missing:
        # Only a STRONG path claim earns a refutation. A weak one — a dotted
        # identifier that merely looks filename-shaped — is a guess, and
        # refuting a premise on a guess is worse than declining to decide it:
        # the run would discard a true premise and record false issue-accuracy
        # feedback against the issue.
        strong = [p.bare for p in missing if p.strength == 'strong']
        if strong:
            return 'refuted', 'cited path absent from the tree: ' + ','.join(strong)
        return 'unestablished', (
            'no cited span is a strong path claim (each is filename-shaped '
            'without a directory, or slash-bearing without a path-shaped '
            'tail), so its absence is not evidence of a stale premise: '
            + ','.join(p.bare for p in missing))

    located = [p.bare for p in paths if p.suffix]
    if handle == 'path':
        # Presence is NOT the premise. A bullet citing `lib/scan.sh` is
        # asserting something about that file's contents, and confirming the
        # file still exists re-derives none of it — reporting `holds` here
        # would reproduce the very "this was already checked" reading the pass
        # exists to withdraw. `unestablished` costs only the investigation the
        # run would otherwise have done.
        return 'unestablished', (
            'cited path present but the bullet carries no quotation to '
            're-derive the premise from: ' + ','.join(p.bare for p in paths))

    readable, skipped, unread = {}, [], []
    for cited in paths:
        rel = cited.bare
        target = root / rel
        if target.is_dir():
            # A directory has no text to search. Collect it rather than
            # returning: an early return abandoned every co-cited path after it,
            # so the verdict silently depended on citation ORDER within the
            # bullet and a genuine refutation on a later path was lost.
            skipped.append(f'{rel} (directory)')
            continue
        try:
            readable[rel] = normalize(target.read_text(
                encoding='utf-8', errors='replace'))
        except OSError as exc:
            unread.append(f'{rel} (unreadable: {exc})')

    if unread:
        # A cited file the helper could not OPEN is an unestablished
        # measurement, not evidence the premise drifted. Refuting here would
        # assert the one verdict that makes the run discard the premise and
        # file issue-accuracy feedback, over a citation never adjudicated —
        # the same guess-becomes-refutation class the weak-path and elision
        # arms exist to prevent. (A co-cited DIRECTORY is different and stays
        # benign: a quotation cannot live in one, so it is disclosed rather
        # than fatal.)
        return 'unestablished', (
            'a cited path could not be read, so the citation set was not fully '
            'adjudicated: ' + ','.join(unread))

    if not readable:
        return 'unestablished', (
            'no cited path could be read to re-derive the quotation from: '
            + ','.join(skipped))

    unresolved, elided_unresolved, unadjudicable = [], [], []
    for quote in quotes:
        elided = _ELISION.search(quote) is not None
        fragments = [f for f in (normalize(part)
                                 for part in _ELISION.split(quote)) if f]
        if not fragments:
            # A quotation long enough to clear `_QUOTED`'s floor but composed
            # ONLY of markdown emphasis and whitespace (`"********"`) normalizes
            # to nothing, so there is no text to search for. Skipping it would
            # drop the quote dimension silently and — when it is the bullet's
            # only quotation — let a present path alone mint `holds`: a FALSE
            # CLEAN from a quotation carrying no adjudicable content, the same
            # harm the short-fragment floor below is guarded against. It
            # adjudicates nothing, so it decides nothing.
            unadjudicable.append(quote)
            continue
        if elided and any(len(f) < _MIN_FRAGMENT for f in fragments):
            # An elided quotation is adjudicated fragment by fragment, and a
            # SHORT fragment matches almost any file — `"the … premise"` would
            # otherwise report `holds` on the evidence that the words "the" and
            # "premise" each occur somewhere in it. `holds` is the one verdict
            # this helper can mint, so weak evidence here is a FALSE CLEAN, not
            # a fail-safe. Below the floor it decides nothing.
            elided_unresolved.append(quote)
            continue
        # Fragments must occur IN ORDER and non-overlapping in one file: an
        # elision means "this text, then later that text", not "these words
        # appear somewhere".
        resolved = False
        for haystack in readable.values():
            cursor, ok = 0, True
            for fragment in fragments:
                found = haystack.find(fragment, cursor)
                if found == -1:
                    ok = False
                    break
                cursor = found + len(fragment)
            if ok:
                resolved = True
                break
        if resolved:
            continue
        # An ELIDED quotation is not verbatim — the author cut text out of it
        # with an ellipsis — so a miss is not evidence the premise drifted, and
        # refuting on one is the same guess-becomes-refutation defect the weak
        # path arm exists to prevent. (Both remaining false refutations against
        # issue #857's real body were exactly this: every fragment resolved,
        # only the elided whole did not.)
        (elided_unresolved if elided else unresolved).append(quote)

    if not unresolved and not elided_unresolved and not unadjudicable:
        if located:
            # The file is present and every quotation resolves, but the bullet
            # also cited a location inside the file (a node id, an anchor, a
            # line number) that this helper cannot adjudicate.
            return 'unestablished', (
                'quoted sentence(s) resolve, but the bullet cites a location '
                'inside the file that was not adjudicated: ' + ','.join(located))
        detail = 'every quoted sentence resolves in ' + ','.join(readable)
        if skipped:
            # A `holds` built from only some of the cited paths discloses which
            # ones went unread, rather than reading as a complete adjudication.
            detail += '; not adjudicated: ' + ','.join(skipped)
        return 'holds', detail

    if not unresolved:
        reasons = []
        if elided_unresolved:
            reasons.append(
                'an ELIDED quotation did not resolve as a whole; an elided '
                'quote is not verbatim, so this is not evidence of a stale '
                'premise: ' + ' | '.join(elided_unresolved))
        if unadjudicable:
            reasons.append(
                'a quotation carried no adjudicable text once markdown '
                'emphasis and whitespace were normalized away, so it was '
                'never searched for: ' + ' | '.join(unadjudicable))
        return 'unestablished', '; '.join(reasons)

    # Same asymmetry as the missing-path arm: a quotation that fails to resolve
    # in a STRONG path is a refutation, but in a weak one it is only evidence
    # that the guess was wrong about which file was meant.
    #
    # Refute-eligibility is narrowed to strong paths that were actually READ,
    # exactly as the missing-path arm narrows to the specific missing strong
    # entries. A strong citation the loop above SKIPPED adjudicated nothing —
    # a directory holds no searchable text, so the quotation was only ever
    # searched against the co-cited files — and letting it license a refutation
    # over a miss in a co-cited WEAK file refutes on a guess, the harm the
    # weak-path, unread-file and elision arms all exist to close.
    adjudicated_strong = [p.bare for p in paths
                          if p.strength == 'strong' and p.bare in readable]
    if adjudicated_strong:
        detail = ('quoted sentence no longer occurs in ' + ','.join(readable)
                  + ': ' + ' | '.join(unresolved))
        if unadjudicable:
            # The refutation rests on the quotation that MISSED, not on the one
            # that carried no adjudicable text — disclose the latter rather
            # than letting the verdict read as a complete adjudication.
            detail += ('; not adjudicated (no searchable text): '
                       + ' | '.join(unadjudicable))
        if skipped:
            # Symmetric with the `holds` arm: a verdict reached over only part
            # of the citation set says so, rather than reading as a complete
            # adjudication of everything the bullet cited.
            detail += '; not adjudicated: ' + ','.join(skipped)
        return 'refuted', detail
    if any(p.strength == 'strong' for p in paths):
        # A strong path WAS cited, but none of them reached `readable`, so the
        # miss says nothing about it. Reusing the weak-span wording below would
        # be a documented falsehood here: a directory-bearing span was cited.
        detail = ('quoted sentence does not occur in ' + ','.join(readable)
                  + ', and no strong cited path was searchable, so the miss is '
                    'not evidence of a stale premise: ' + ' | '.join(unresolved))
        if skipped:
            detail += '; not adjudicated: ' + ','.join(skipped)
        return 'unestablished', detail
    return 'unestablished', (
        'quoted sentence does not occur in the cited span(s), none of which is '
        'a strong path claim: ' + ','.join(readable))


def _graded_spans(body: str) -> list:
    """Offset ranges the `_MARKER` recogniser already covers.

    A collocation inside a recognised `Verified:` bullet is already graded, so
    it is not an ungraded claim. Each span runs from the marker to the same
    bound `parse_bullets` uses, via the shared `_bullet_bound`.
    """
    spans = []
    for match in _MARKER.finditer(body):
        rest = body[match.end():]
        spans.append((match.start(), match.end() + _bullet_bound(rest)))
    return spans


def _fenced_line_set(content_lines: list) -> set:
    """Indices of lines inside a fenced code block, delimiters included.

    A fence opens on a line matching `_FENCE_RE` and closes on the next such
    line (the whole `[open, close]` range is fenced); an unclosed fence runs to
    end-of-input. Both consumers share this so heading detection and collocation
    exclusion agree on which lines are code.
    """
    fenced = set()
    open_index = None
    for index, line in enumerate(content_lines):
        if not _FENCE_RE.match(line):
            continue
        if open_index is None:
            open_index = index
        else:
            fenced.update(range(open_index, index + 1))
            open_index = None
    if open_index is not None:
        fenced.update(range(open_index, len(content_lines)))
    return fenced


def _code_spans(content_lines: list, line_offset: list, fenced_lines: set) -> list:
    """Offset ranges inside fenced code blocks or inline code spans.

    A collocation inside either is data, not a premise. A fenced line's whole
    span is excluded; on every other line, inline backtick runs are excluded.
    """
    spans = []
    for index, line in enumerate(content_lines):
        base = line_offset[index]
        if index in fenced_lines:
            spans.append((base, base + len(line)))
            continue
        for inline in _INLINE_CODE_RE.finditer(line):
            spans.append((base + inline.start(), base + inline.end()))
    return spans


def _premise_regions(body: str, content_lines: list, fenced_lines: set) -> dict:
    """Map each premise-bearing line index to its region label.

    Regions are the three named sections — resolved through `section_parse`'s
    extractor, so an absent section contributes nothing and an issue on a
    consumer's own template is scanned by its heading lines alone — plus every
    heading line, labelled `heading`. The section walk mirrors the extractor's
    own first-match-only, level-2/3 open/close rules; it additionally skips
    fenced lines (below), so where a `##`-shaped line sits inside a fence this
    walk keeps the real section open while the fence-blind `extract_section`
    used only for the `present` gate would not — a divergence in the safe
    direction, since `present` gates eligibility and never mints a detection.
    """
    present = {name for name in _PREMISE_SECTIONS if extract_section(body, name)}
    region = {}
    active_name = None
    active_level = None
    opened = set()
    for index, line in enumerate(content_lines):
        if index in fenced_lines:
            continue
        heading_match = HEADING_RE.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            heading = heading_match.group(2).strip()
            region[index] = 'heading'
            if active_name is not None and level <= active_level:
                active_name = None
                active_level = None
            if active_name is None and level in (2, 3):
                for name in _PREMISE_SECTIONS:
                    if (heading.lower() == name.lower()
                            and name in present and name not in opened):
                        active_name, active_level = name, level
                        opened.add(name)
                        break
            continue
        if active_name is not None:
            region[index] = active_name
    return region


def find_ungraded_claims(body: str) -> list:
    """Return one report line per ungraded verification claim, document order.

    An ungraded claim is a collocation-family phrase in a premise-bearing region
    that no recognised marker span already covers and that is not inside code.
    Non-adjudicating by construction: it mints no verdict and moves no exit code.
    """
    content_lines = body.splitlines()
    line_offset = []
    acc = 0
    for raw in body.splitlines(keepends=True):
        line_offset.append(acc)
        acc += len(raw)

    fenced_lines = _fenced_line_set(content_lines)
    region = _premise_regions(body, content_lines, fenced_lines)
    # A collocation is excluded when it falls inside a graded marker span or inside
    # code; both suppress a detection identically, so they are one exclusion set.
    excluded = _graded_spans(body) + _code_spans(content_lines, line_offset, fenced_lines)

    detections = []
    for match in _COLLOCATION_RE.finditer(body):
        start = match.start()
        index = bisect.bisect_right(line_offset, start) - 1
        if index not in region:
            continue
        if any(low <= start < high for low, high in excluded):
            continue
        detections.append((region[index], match.group(0),
                           content_lines[index].strip()))
    return ['ungraded_claim={} region={} phrase={} detail={}'.format(
        number, label, phrase, sentence)
        for number, (label, phrase, sentence) in enumerate(detections, start=1)]


class _ArgParser(argparse.ArgumentParser):
    """An argument parser that fails as UNESTABLISHED, not as a refutation.

    `argparse` exits **2** on a bad invocation, and 2 is this helper's
    "a premise was REFUTED" code — so a caller that mistypes a flag would be
    told the issue contains a stale premise it never looked at. A bad
    invocation is a measurement that never happened, which is exactly what
    exit 3 means here.

    The remap lives in `exit`, not only in `error`, because `error` is not
    argparse's only route to status 2: an argument *action* may call
    `parser.exit(2)` directly, and future arguments (a `type=` callable, a
    mutually-exclusive group) can reach it without passing through `error` at
    all. Overriding only `error` would leave those routes emitting the
    refutation code, which is the one exit this module may never assert without
    having adjudicated a premise. Status 0 (`--help`, `--version`) is left
    alone: it is a successful invocation, not a measurement.
    """

    def exit(self, status=0, message=None):
        super().exit(EXIT_UNESTABLISHED if status == EXIT_REFUTED else status,
                     message)

    def error(self, message):
        self.exit(EXIT_UNESTABLISHED,
                  f'VERIFIED_PREMISES unavailable reason=bad-invocation '
                  f'detail={message}\n')


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None) -> int:
    _force_utf8_streams()
    parser = _ArgParser(
        description='Re-check an issue body\'s Verified: premises against the tree.')
    parser.add_argument('--body-file', required=True,
                        help='path to the issue body (the Phase 1.1 cache)')
    parser.add_argument('--repo-root', default=None,
                        help='tree to adjudicate against (default: the enclosing '
                             'git working tree; unestablished (exit 3) if none '
                             'is found)')
    args = parser.parse_args(argv)

    try:
        return _run(args)
    except Exception as exc:  # noqa: BLE001 — see the comment below.
        # Any unexpected failure is an unestablished measurement, not a
        # refutation. Without this the traceback would exit 1 — a code neither
        # consumer routes — after an arbitrary number of per-bullet lines had
        # already been printed, which reads as a partial clean pass.
        # The traceback goes to STDERR so the stdout contract stays
        # machine-clean while a real defect remains diagnosable — a guard whose
        # own failures are the quietest thing it emits is not a guard.
        traceback.print_exc(file=sys.stderr)
        print(f'VERIFIED_PREMISES unavailable reason=internal-error detail={exc!r}')
        return EXIT_UNESTABLISHED


def _run(args) -> int:
    try:
        body = Path(args.body_file).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        # Unestablished, never a clean pass: a body that could not be read is
        # not a body with no stale premises in it.
        print(f'VERIFIED_PREMISES unavailable reason=body-unreadable detail={exc}')
        return EXIT_UNESTABLISHED

    if not body.strip():
        # An empty body and a body carrying no bullets are NOT the same
        # measurement, and collapsing them is the fail-open this guard exists
        # to stop: `total=0` would read as "this issue asserts no premises"
        # when in fact nothing was ever read.
        print('VERIFIED_PREMISES unavailable reason=body-empty '
              'detail=the body file is empty or whitespace-only')
        return EXIT_UNESTABLISHED

    root = Path(args.repo_root).resolve() if args.repo_root else _default_root()
    if root is None:
        # The default root could not be ESTABLISHED (no `.git` above the cwd).
        # Adjudicating against an arbitrary cwd made every cited path miss and
        # rendered the whole body as a mass REFUTATION — the same unestablished-
        # measurement-dressed-as-a-verdict the explicit --repo-root arm below
        # refuses, reached through the sibling path.
        print('VERIFIED_PREMISES unavailable reason=repo-root-unestablished '
              'detail=no .git was found above the current directory and no '
              '--repo-root was given')
        return EXIT_UNESTABLISHED
    if not root.is_dir():
        # An unusable root makes every cited path miss, which would render as a
        # whole-body mass REFUTATION — an unestablished measurement dressed as
        # a hard verdict, and the mirror image of "unknown is not zero".
        print('VERIFIED_PREMISES unavailable reason=repo-root-unusable '
              f'detail={root} is not an existing directory')
        return EXIT_UNESTABLISHED

    tally = {'holds': 0, 'refuted': 0, 'unestablished': 0}
    for index, span in enumerate(parse_bullets(body), start=1):
        handle, paths, quotes = classify(span)
        state, detail = recheck(handle, paths, quotes, root)
        tally[state] += 1
        print(f'bullet={index} handle={handle} state={state} detail={detail}')

    print('VERIFIED_PREMISES total={} holds={} refuted={} unestablished={}'.format(
        sum(tally.values()), tally['holds'], tally['refuted'],
        tally['unestablished']))

    # Do not let this advisory pass reach main's catch-all (issue #1634): an
    # exception escaping here would turn the clean/refuted adjudication already
    # printed above into an internal-error exit.
    # Emission is inside the fence, not just detection: an error raised while
    # printing would otherwise reach main's catch-all and print a second
    # `VERIFIED_PREMISES unavailable` after a valid adjudicated block.
    try:
        ungraded = find_ungraded_claims(body)
        for line in ungraded:
            print(line)
        print('UNGRADED_CLAIMS total={}'.format(len(ungraded)))
    except Exception as exc:  # noqa: BLE001 — the pass is advisory; never let it move the verdict.
        # Never print `total=0` here: that is byte-identical to "ran, found
        # none", which is the fail-open this pass exists to close.
        traceback.print_exc(file=sys.stderr)
        print(f'check-verified-premises: ungraded-claim pass failed, reported '
              f'none: {exc!r}', file=sys.stderr)
        print('UNGRADED_CLAIMS unavailable reason=internal-error '
              f'detail={exc!r}')
    return EXIT_REFUTED if tally['refuted'] else EXIT_CLEAN


def _default_root():
    """Nearest enclosing git working tree, or `None` when there is none.

    Resolved by walking for a `.git` entry rather than by shelling out to `git
    rev-parse`, so this module keeps its no-subprocess property. `.exists()` is
    deliberate rather than `.is_dir()`: in a linked worktree — this repo's own
    working mode — `.git` is a regular *file* holding a gitdir pointer.

    Returning `None` rather than falling back to the current directory is the
    fail-closed direction: an arbitrary cwd is not the repository, and
    adjudicating against it turns every cited path into a miss and the whole
    body into a mass refutation. A breadcrumb is a diagnostic, not a verdict.
    """
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if (candidate / '.git').exists():
            return candidate
    print('check-verified-premises: no .git found above the current directory; '
          'pass --repo-root to name the tree to adjudicate against',
          file=sys.stderr)
    return None


if __name__ == '__main__':
    sys.exit(main())
