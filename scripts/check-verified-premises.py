#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Re-check an issue body's `Verified:` premises against the current tree.

A `Verified:` bullet licenses an implementing run to skip its own
investigation, so a premise that has gone false since drafting is worse than
none. `/prflow:spec` routes on `handle=` and `state=` (a `handle=none` bullet
is a drafting defect); implement Phase 1.6 Pass 6 routes on the adjudication.

Security boundary: the body is third-party text, so a path it cites is read
only when it resolves inside `--repo-root`. The helper never executes a
command from the body, spawns no subprocess and makes no network call; a
command handle is reported, never run.

Governing asymmetry: a refutation can make the run discard the premise and file
issue-accuracy feedback, so only a positively adjudicated miss refutes;
anything guessed at resolves to `unestablished`.

Handles (`handle=`):
  path-quote  a cited path plus a quoted sentence, or (quoting no sentence) a
              backticked code literal; the only handle whose content is graded
  path        a cited path alone; presence is not the premise, so never `holds`
  quote       a quoted sentence naming no path
  command     a backticked command; reported, never executed
  none        no handle at all

States (`state=`): `holds`, `refuted` (a strong cited path is gone or its
quoted sentence no longer occurs), `unestablished` (undecided; investigate).

Usage:
    check-verified-premises.py --body-file PATH --repo-root PATH

Exit codes:
  0  no premise refuted (including no bullets, or only unestablished ones)
  2  at least one premise REFUTED
  3  unestablished measurement: unreadable/empty body, unusable root, bad
     invocation, or internal error. Never 2: not running is not a refutation.

Every terminating path but `--help` prints a `VERIFIED_PREMISES ` line; its
absence means "did not run". On the normal path a non-adjudicating
ungraded-claim pass (issue #1634) follows: `ungraded_claim=<n> region=…
phrase=… detail=…` lines and an `UNGRADED_CLAIMS total=<n>` summary, or
`UNGRADED_CLAIMS unavailable reason=internal-error detail=…` when the pass
raises. None of these lines sets the exit code.
"""

import argparse
import bisect
import re
import sys
import traceback
from pathlib import Path
from typing import NamedTuple

# Imported in-process: a subprocess hop breaks on Windows and this module's
# no-subprocess boundary.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from section_parse import HEADING_RE, extract_section

# Named so a refutation (2) never reads like an unestablished measurement (3).
EXIT_CLEAN = 0
EXIT_REFUTED = 2
EXIT_UNESTABLISHED = 3


class CitedPath(NamedTuple):
    """One cited path; fields are read by name, never by position."""

    strength: str
    bare: str
    suffix: str


# The `Verified` marker, split by position so ordinary bolded prose ("We
# **Verified that** …") mints no phantom bullet:
#   A (anywhere)    the pure label `**Verified**` / `**Verified:**`
#   B (line start)  a line or list item opening with `Verified:`, bolded,
#                   backticked or bare
#   C (item start)  a bolded run opening a list item whose first word is
#                   `Verified`
# The recognised set is a floor in both directions: an unrecognised spelling is
# invisible, and B/C can over-recognise (a fenced or table-cell line, a bolded
# sentence). A phantom, like any bullet, refutes only through a strong cited path.
# Arm B's trailing backtick is conditional on a leading one (group 1), so a bare
# `Verified:` keeps the opening backtick of the path after it.
_MARKER = re.compile(
    r'\*\*[ \t]*Verified[ \t]*:?[ \t]*\*\*[ \t]*:?'
    r'|(?m:^[ \t]*(?:[-*+]|\d+[.)])?[ \t]*(?:\*\*[ \t]*)?(`)?Verified`?[ \t]*:(?(1)`?))'
    r'|(?m:^[ \t]*(?:[-*+]|\d+[.)])[ \t]*\*\*[`\s]*Verified\b[^*\n]*\*\*:?)')

# Paths and commands are mined only from backticked spans, never running prose.
_BACKTICKED = re.compile(r'`([^`\n]+)`')

# A double-quoted sentence (ASCII or typographic). Single quotes are excluded:
# they appear in shell commands far more than as premise delimiters. A quote
# preceded by a backslash neither opens nor closes one.
_QUOTED = re.compile(r'(?<!\\)["“]((?:\\"|[^"“”]){8,})(?<!\\)["”]')

# The same with each backslash literal, except that a quote mark after a
# backslash still never opens a quotation.
_QUOTED_LITERAL = re.compile(r'(?<!\\)["“]([^"“”]{8,})["”]')

_ESCAPED_QUOTE = '\\"'
_UNESCAPE_NOTE = '; resolved only with \\" unescaped to ": '

# Per-fragment floor for an elided quotation, so short words match nothing.
_MIN_FRAGMENT = 8

# Floor for a backticked code literal graded as a quotation, mirroring `_QUOTED`.
_MIN_CODE_LITERAL = 8

# The quotation-shape rule, single-sourced for the refusals that quote it (#1866).
_QUOTE_RULE = (
    'a premise quotation is a double-quoted sentence that opens and closes in '
    'plain text (a matching pair of ASCII " or typographic “ ” enclosing at least '
    'eight characters); a backtick span inside the quotation is part of the quoted '
    'sentence, and a double-quote inside such a span neither opens nor closes it, '
    'nor does a backslash-escaped \\", '
    'or — in a bullet that cites a repository path and no double-quoted sentence — '
    'a backticked literal of at least eight characters that is not path-shaped')

# A file extension: the path-shaped tail `_path_strength` looks for.
_EXTENSION = re.compile(r'\.[A-Za-z0-9]{1,6}$')

# A glob span names a set of paths, so no single existence check adjudicates it.
_GLOBBY = re.compile(r'[*?\[\]]')

# The next list item: a bullet's span stops here so it never mines the
# following item's citations.
_NEXT_ITEM = re.compile(r'\n[ \t]*(?:[-*+]|\d+[.)])\s')

# An ellipsis: the quotation is elided, so it is matched by fragment and a miss
# never refutes. Detected on the raw quote, since a leading or trailing
# ellipsis yields one fragment.
_ELISION = re.compile(r'\s*(?:…|\.\.\.)\s*')

# A locator suffix (`::test`, `#anchor`, `:42`): stripped for the presence
# check, and its presence downgrades a resolving verdict.
_LOCATOR_SUFFIX = re.compile(r'(::.+|#.+|:\d+(?:-\d+)?)$')

# Why each undecidable handle cannot be adjudicated; the set's single definition.
_UNDECIDABLE_REASONS = {
    'quote': 'quoted sentence names no path to search',
    'command': 'command handle reported, never executed',
    'none': 'no re-derivation handle in the bullet',
}

# --- Ungraded-claim detection (issue #1634) --------------------------------
# Its own tokens must exclude the state tokens (`holds`/`refuted`/
# `unestablished`), or a verdict parser scanning both outputs would mis-tally.

# Deliberately narrow: a missed wording is the low-false-positive floor.
_COLLOCATION_FAMILY = (
    'verified against', 'confirmed against', 'checked against',
    'verified at drafting time')
# Letter lookarounds (not `\b`) exclude `unverified against` and keep
# `group(0)` the bare phrase.
_COLLOCATION_RE = re.compile(
    '(?<![A-Za-z])(?:{})(?![A-Za-z])'.format(
        '|'.join(re.escape(phrase) for phrase in _COLLOCATION_FAMILY)),
    re.IGNORECASE)

# Sections scanned for collocations; `_premise_regions` adds every heading line.
# No other line is scanned for one.
_PREMISE_SECTIONS = ('Current Behavior', 'Technical Context',
                     'Implementation Notes')

# A fenced block is data; also keeps a fenced `##` line from closing a section.
_FENCE_RE = re.compile(r'^[ \t]*(?:`{3,}|~{3,})')

# Inline code is data, so a backticked collocation phrase is not flagged.
_INLINE_CODE_RE = re.compile(r'`[^`\n]+`')

# A blockquoted `Verified:` line, which no `_MARKER` arm grades. `[ \t>]*`
# excludes `*`, so `> **Verified:**` stays with arm A (#1866).
_BLOCKQUOTE_VERIFIED = re.compile(r'(?m)^[ \t]*>[ \t>]*Verified\b[ \t]*:')


def normalize(text: str) -> str:
    """Collapse text to the form both sides of a quote match compare in.

    Folds whitespace runs, typographic quotes and dashes, and strips markdown
    emphasis (`*`, backticks), so wrapping or editor substitution never
    refutes a true premise.
    """
    folded = (text.replace('“', '"').replace('”', '"')
                  .replace('‘', "'").replace('’', "'")
                  .replace('—', '-').replace('–', '-'))
    stripped = folded.replace('*', '').replace('`', '')
    return ' '.join(stripped.split())


_TERMINAL_PUNCT = '.:;,!?'

_RUN_MARK = '\x01'
_RUN_END = '\x02'

# Do not loosen the lookbehind (a word character other than a standalone `_`):
# a run starting inside a long punctuation or ` _` run makes the pattern
# quadratic.
_LINE_BREAK_RUN = re.compile(
    r'(?<=\w)(?<!(?<!\w)_)([' + re.escape(_TERMINAL_PUNCT) + r']?)'
    r'(?:[^\w\n]|(?<!\w)_(?!\w))*\n'
    r'[^\w\n]*')

_GLUED_PREFIX = '(?:[A-Za-z]{1,2}["\'])?'

_QUOTE_JOIN = re.compile(r'[^\w ]*(?: [^\w ]*)+')


def _find_fragment(haystack: str, fragment: str, cursor: int, last: bool) -> int:
    """Index of `fragment` in `haystack` from `cursor`, or -1.

    The final fragment ignores terminal punctuation, but its core must end at a
    word boundary (`authorization.` never matches `authorizations:`).
    """
    core = fragment.rstrip(_TERMINAL_PUNCT) if last else fragment
    if not core or core == fragment:
        return haystack.find(fragment, cursor)
    found = haystack.find(core, cursor)
    while found != -1:
        end = found + len(core)
        if end == len(haystack) or not haystack[end].isalnum():
            return found
        found = haystack.find(core, found + 1)
    return -1


def _split_locator(span: str) -> tuple:
    """Split a cited span into `(path_part, suffix)`; only the file part is checkable."""
    match = _LOCATOR_SUFFIX.search(span)
    if not match or match.start() == 0:
        return span, ''
    return span[:match.start()], match.group(0)


def _path_strength(span: str) -> str:
    """Classify a backticked span as a `strong` path, a `weak` one, or `no`.

    Only a strong path can refute. Strong needs a `/` plus a path-shaped tail
    (a dotted final segment or a trailing `/`), so git refs like `origin/main`
    stay weak; a dotted identifier like `spec.loader` is weak. Rejected
    outright: an absolute path (pathlib's join would discard the root), a `-`
    or `~` prefix, a glob, and a URL.
    """
    if not span or any(c.isspace() for c in span):
        return 'no'
    if span.startswith(('-', '/', '~')):
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
    """True when `rel` stays inside `root` once `..` is resolved (body text is untrusted)."""
    try:
        candidate = (root / rel).resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    return candidate == root or root in candidate.parents


def _is_command(span: str) -> bool:
    """True for a multi-token span: a path never holds whitespace, a command
    almost always does. Structural, so a consumer repo's own tools count."""
    return bool(span.strip()) and any(c.isspace() for c in span.strip())


def _bullet_bound(rest: str) -> int:
    """Offset where a bullet's span ends: the next marker, list item or blank line.

    Shared with `_graded_spans` so the ungraded pass subtracts exactly the
    adjudicated span.
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

    A soft-wrapped continuation line is absorbed (bounding at `\\n` would sever
    a wrapped bullet from its own citation), so a strong path on a following
    line markdown reads as a continuation can drive this bullet's verdict.
    """
    return [rest[:_bullet_bound(rest)]
            for rest in (body[m.end():] for m in _MARKER.finditer(body))]


def _quotations(span: str, pattern: re.Pattern) -> tuple:
    """`(quotes, ranges)` that `pattern` delimits in `span`."""
    # Same-length mask keeps match offsets aligned, so a backtick span inside a
    # quotation stays quoted (#326).
    masked = _BACKTICKED.sub(lambda m: '\x00' * (m.end() - m.start()), span)
    quotes, ranges = [], []
    for m in pattern.finditer(masked):
        raw = span[m.start(1):m.end(1)]
        # A quotation that is exactly one backtick span opens no quotation.
        if _BACKTICKED.fullmatch(raw.strip()):
            continue
        # A backtick- or `\"`-bearing quotation under the normalized floor is dropped.
        if (('`' in raw or _ESCAPED_QUOTE in raw) and len(normalize(
                raw.replace(_ESCAPED_QUOTE, '"'))) < _MIN_CODE_LITERAL):
            continue
        quotes.append(raw)
        ranges.append((m.start(1), m.end(1)))
    return quotes, ranges


def classify(span: str) -> tuple:
    """Return `(handle, paths, quotes, code_literals)` for one bullet span.

    `paths` holds `CitedPath`s. `code_literals` holds non-path backticked spans
    of at least `_MIN_CODE_LITERAL` chars; kept apart from `quotes` because
    `recheck` grades them only when the bullet quotes no sentence.
    """
    quotes, quote_ranges = _quotations(span, _QUOTED)

    paths, commands, code_literals = [], [], []
    for m in _BACKTICKED.finditer(span):
        # A backtick span inside a quotation is quoted text.
        if any(lo <= m.start() and m.end() <= hi for lo, hi in quote_ranges):
            continue
        backticked = m.group(1)
        strength = _path_strength(backticked)
        if strength != 'no':
            bare, suffix = _split_locator(backticked)
            paths.append(CitedPath(strength, bare, suffix))
            continue
        # A command is never mined for a path: its premise is its result.
        if _is_command(backticked):
            commands.append(backticked)
        if len(backticked) >= _MIN_CODE_LITERAL:
            code_literals.append(backticked)
    if paths and (quotes or code_literals):
        handle = 'path-quote'
    elif paths:
        handle = 'path'
    elif quotes:
        handle = 'quote'
    elif commands:
        handle = 'command'
    else:
        handle = 'none'
    return handle, paths, quotes, code_literals


def _with_absent(detail: str, absent: list) -> str:
    """Append the absent weak spans set aside rather than adjudicated."""
    if absent:
        detail += '; not adjudicated (absent weak span): ' + ','.join(absent)
    return detail


def _read_cited(paths: list, root: Path) -> tuple:
    """Read each cited path. Returns `(readable, sources, skipped, unread)`:
    `readable` maps a path to its normalized text, `sources` to its raw text.

    A directory is collected, not returned early, so the verdict never depends
    on citation order.
    """
    readable, sources, skipped, unread = {}, {}, [], []
    for cited in paths:
        rel = cited.bare
        target = root / rel
        if target.is_dir():
            skipped.append(f'{rel} (directory)')
            continue
        try:
            sources[rel] = target.read_text(encoding='utf-8', errors='replace')
        except OSError as exc:
            unread.append(f'{rel} (unreadable: {exc})')
            continue
        readable[rel] = normalize(sources[rel])
    return readable, sources, skipped, unread


def _fragments(quote: str) -> list:
    """A quotation's normalized, non-empty elision fragments."""
    return [f for f in (normalize(part) for part in _ELISION.split(quote)) if f]


def _short_elided(fragments: list, elided: bool) -> bool:
    """True when an elided quotation has a fragment under `_MIN_FRAGMENT`."""
    return elided and any(len(f) < _MIN_FRAGMENT for f in fragments)


def _fragments_resolve(fragments: list, readable: dict) -> bool:
    """True when the fragments occur in order, non-overlapping, in one file."""
    for haystack in readable.values():
        cursor = 0
        for index, fragment in enumerate(fragments):
            found = _find_fragment(haystack, fragment, cursor,
                                   index == len(fragments) - 1)
            if found == -1:
                break
            cursor = found + len(fragment)
        else:
            return True
    return False


def _quote_resolves(quote: str, readable: dict) -> bool:
    """True when `quote` resolves verbatim, as `recheck` grades a hit."""
    fragments = _fragments(quote)
    return (bool(fragments)
            and not _short_elided(fragments, _ELISION.search(quote) is not None)
            and _fragments_resolve(fragments, readable))


def _line_break_view(text: str) -> str:
    """Normalized `text` with each line-break run, but its kept
    `_TERMINAL_PUNCT` character, replaced by its non-space characters between
    `_RUN_MARK` and `_RUN_END`."""
    return normalize(_LINE_BREAK_RUN.sub(
        lambda m: (m.group(1) + _RUN_MARK + ''.join(m.group(0)[len(m.group(1)):].split())
                   + _RUN_END), text))


def _line_break_resolves(quote: str, views: list) -> bool:
    """True when `quote` occurs in a line-break view, each `_QUOTE_JOIN` in it
    matching itself or a run and any `_GLUED_PREFIX` after it. A run matches a
    join whose characters other than spaces, `"` and `\\` it all carries, so a
    quotation writing other characters at the break (`>` against `<`) misses;
    a join's leading `_TERMINAL_PUNCT` character must precede the run.

    Mirrors `_find_fragment`'s terminal-punctuation and word-boundary rules.
    """
    fragment = normalize(quote)
    core = fragment.rstrip(_TERMINAL_PUNCT) or fragment
    pieces = _QUOTE_JOIN.split(core)

    def run(join: str) -> str:
        kept = join[0] if join[0] in _TERMINAL_PUNCT else ''
        carried = dict.fromkeys(c for c in join[len(kept):] if c not in ' "\\')
        # One lookahead per distinct character keeps a miss linear; an ordered
        # gap per character backtracks exponentially over a long run.
        return (re.escape(kept + _RUN_MARK)
                + ''.join(f'(?=[^{_RUN_END}]*{re.escape(c)})' for c in carried)
                + f'[^{_RUN_END}]*' + re.escape(_RUN_END) + _GLUED_PREFIX)

    pattern = re.escape(pieces[0]) + ''.join(
        f'(?:{re.escape(join)}|{run(join)}){re.escape(piece)}'
        for join, piece in zip(_QUOTE_JOIN.findall(core), pieces[1:]))
    if core != fragment:
        pattern += r'(?![^\W_])'
    compiled = re.compile(pattern)
    return any(compiled.search(view) for view in views)


def _literal_resolves(literal: str, readable: dict) -> bool:
    """True when a normalized code literal occurs in any readable cited file.

    The floor is re-applied after `normalize`, so `a * b * c` cannot shrink to
    a substring of almost any file.
    """
    norm = normalize(literal)
    return (len(norm) >= _MIN_CODE_LITERAL
            and any(norm in haystack for haystack in readable.values()))


def recheck(handle: str, paths: list, quotes: list, code_literals: list,
            root: Path, span: str) -> tuple:
    """Adjudicate one bullet against the tree. Returns `(state, detail)`."""
    if handle in _UNDECIDABLE_REASONS:
        return 'unestablished', _UNDECIDABLE_REASONS[handle]

    escaping = [p.bare for p in paths if not _resolves_inside(root, p.bare)]
    if escaping:
        # Refused, not refuted: a path outside the repository is never read.
        return 'unestablished', ('cited path resolves outside the repository, '
                                 'refused: ' + ','.join(escaping))

    # Presence, not file-ness: a cited directory exists.
    missing = [p for p in paths if not (root / p.bare).exists()]
    disclosed_absent = []
    if missing:
        # Only a strong path claim earns a refutation; a weak one is a guess.
        strong = [p.bare for p in missing if p.strength == 'strong']
        if strong:
            return 'refuted', 'cited path absent from the tree: ' + ','.join(strong)
        present = [p for p in paths if p not in missing]
        if not present:
            return 'unestablished', (
                'no cited span is a strong path claim (each is filename-shaped '
                'without a directory, or slash-bearing without a path-shaped '
                'tail), so its absence is not evidence of a stale premise: '
                + ','.join(p.bare for p in missing))
        # Adjudicate the present paths; disclose the absent weak spans.
        disclosed_absent = [p.bare for p in missing]
        paths = present

    located = [p.bare for p in paths if p.suffix]
    if handle == 'path':
        # Presence is not the premise, so a bare path never `holds`.
        return 'unestablished', _with_absent(
            'cited path present but the bullet carries no quotation to '
            're-derive the premise from (' + _QUOTE_RULE + '): '
            + ','.join(p.bare for p in paths), disclosed_absent)

    readable, sources, skipped, unread = _read_cited(paths, root)

    if unread:
        # An unopenable citation was never adjudicated, so it cannot refute.
        return 'unestablished', (
            'a cited path could not be read, so the citation set was not fully '
            'adjudicated: ' + ','.join(unread))

    if not readable:
        return 'unestablished', (
            'no cited path could be read to re-derive the quotation from: '
            + ','.join(skipped))

    if not quotes:
        # Graded on code literals. A miss is `unestablished`, never `refuted`:
        # code is re-spaced and paraphrased too often. A miss is retried with
        # `\"` unescaped (#1194), verbatim first.
        missed, unescaped = [], []
        for lit in code_literals:
            if _literal_resolves(lit, readable):
                continue
            if _ESCAPED_QUOTE in lit and _literal_resolves(
                    lit.replace(_ESCAPED_QUOTE, '"'), readable):
                unescaped.append(lit)
            else:
                missed.append(lit)
        skip_note = ('; not adjudicated: ' + ','.join(skipped)) if skipped else ''
        if unescaped:
            skip_note += _UNESCAPE_NOTE + ' | '.join(unescaped)
        if not missed:
            if located:
                return 'unestablished', _with_absent(
                    'a backticked literal resolves, but the bullet cites a '
                    'location inside the file that was not adjudicated: '
                    + ','.join(located) + skip_note, disclosed_absent)
            return 'holds', _with_absent(
                'every backticked literal resolves in ' + ','.join(readable)
                + skip_note, disclosed_absent)
        return 'unestablished', _with_absent(
            'cited path present but the backticked literal(s) do not occur in '
            + ','.join(readable) + ', and a code literal is not verbatim enough '
            'to refute on a miss: ' + ' | '.join(missed) + skip_note,
            disclosed_absent)

    unresolved, elided_unresolved, unadjudicable = [], [], []
    unescaped, line_broken, views = [], [], None
    for quote in quotes:
        elided = _ELISION.search(quote) is not None
        fragments = _fragments(quote)
        if not fragments:
            # Only emphasis and whitespace: nothing to search, so it decides
            # nothing (else a present path alone would mint `holds`).
            unadjudicable.append(quote)
            continue
        if _short_elided(fragments, elided):
            # A short elided fragment matches almost any file: a false `holds`.
            elided_unresolved.append(quote)
            continue
        if _fragments_resolve(fragments, readable):
            continue
        plain = quote.replace(_ESCAPED_QUOTE, '"')
        if plain != quote:
            # Verbatim first, so a source that really holds `\"` needs no note.
            fragments = _fragments(plain)
            if (fragments and not _short_elided(fragments, elided)
                    and _fragments_resolve(fragments, readable)):
                unescaped.append(quote)
                continue
        if not elided:
            # Never `holds`: a run can hide a character the quotation omits.
            if views is None:
                views = [_line_break_view(text) for text in sources.values()]
            if any(_line_break_resolves(form, views)
                   for form in dict.fromkeys((quote, plain))):
                line_broken.append(quote)
                continue
        # An elided quotation is not verbatim, so its miss never refutes.
        (elided_unresolved if elided else unresolved).append(quote)

    notes = ('; not adjudicated: ' + ','.join(skipped)) if skipped else ''
    if unescaped:
        notes += _UNESCAPE_NOTE + ' | '.join(unescaped)

    if not (unresolved or elided_unresolved or unadjudicable or line_broken):
        if located:
            return 'unestablished', _with_absent(
                'quoted sentence(s) resolve, but the bullet cites a location '
                'inside the file that was not adjudicated: ' + ','.join(located)
                + notes, disclosed_absent)
        return 'holds', _with_absent(
            'every quoted sentence resolves in ' + ','.join(readable) + notes,
            disclosed_absent)

    if not unresolved:
        reasons = []
        if line_broken:
            reasons.append(
                'a quotation occurs only across a line break carrying source '
                'syntax, which can hide characters the quotation omits: '
                + ' | '.join(line_broken))
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
        if located:
            reasons.append('the bullet cites a location inside the file that '
                           'was not adjudicated: ' + ','.join(located))
        return 'unestablished', _with_absent('; '.join(reasons) + notes,
                                             disclosed_absent)

    if line_broken:
        notes = ('; occurs only across a line break: ' + ' | '.join(line_broken)
                 + notes)
    notes = _with_absent(notes, disclosed_absent)
    # Only a strong path that was actually read can license a refutation; a
    # skipped directory adjudicated nothing.
    adjudicated_strong = [p.bare for p in paths
                          if p.strength == 'strong' and p.bare in readable]
    # Extra double-quote delimiters (outside backtick spans) mean a quotation
    # could not be delimited whole, so a miss refuses rather than refutes (#1866).
    stripped = _BACKTICKED.sub(' ', span)
    quote_marks = sum(stripped.count(ch) for ch in ('"', '“', '”'))
    truncated_quote = quote_marks - stripped.count(_ESCAPED_QUOTE) > 2 * len(quotes)
    if adjudicated_strong and truncated_quote:
        return 'unestablished', (
            'a quoted premise could not be delimited whole — the span carries a '
            'double-quote character inside the quotation, so the match is a '
            'fragment, not the premise (' + _QUOTE_RULE + '): '
            + ' | '.join(unresolved) + notes)
    # A sentence ending in a literal backslash reads as an escape and runs on to
    # the next quotation, so re-read with each backslash literal. Only a re-read
    # that pairs every quote mark, so it skips no stale quotation, and resolves
    # every quotation spares the bullet a refutation.
    literal = (_quotations(span, _QUOTED_LITERAL)[0]
               if adjudicated_strong and _ESCAPED_QUOTE in stripped else [])
    if 2 * len(literal) != quote_marks:
        literal = []
    literal_missed = [q for q in literal if not _quote_resolves(q, readable)]
    if literal and not literal_missed:
        return 'unestablished', (
            'a quotation resolves only with each \\" before a closing quote read '
            'as a literal backslash, so the escape is ambiguous: '
            + ' | '.join(literal) + notes)
    if literal_missed:
        notes = ('; read with each backslash literal, still missing: '
                 + ' | '.join(literal_missed) + notes)
    if adjudicated_strong:
        detail = ('quoted sentence no longer occurs in ' + ','.join(readable)
                  + ': ' + ' | '.join(unresolved))
        if unadjudicable:
            detail += ('; not adjudicated (no searchable text): '
                       + ' | '.join(unadjudicable))
        return 'refuted', detail + notes
    if any(p.strength == 'strong' for p in paths):
        # A strong path was cited but none was searchable.
        return 'unestablished', (
            'quoted sentence does not occur in ' + ','.join(readable)
            + ', and no strong cited path was searchable, so the miss is '
              'not evidence of a stale premise: ' + ' | '.join(unresolved) + notes)
    return 'unestablished', (
        'quoted sentence does not occur in the cited span(s), none of which is '
        'a strong path claim: ' + ','.join(readable) + notes)


def _graded_spans(body: str) -> list:
    """Offset ranges the `_MARKER` recogniser already grades."""
    spans = []
    for match in _MARKER.finditer(body):
        rest = body[match.end():]
        spans.append((match.start(), match.end() + _bullet_bound(rest)))
    return spans


def _fenced_line_set(content_lines: list) -> set:
    """Indices of lines inside a fenced block, delimiters included; an unclosed
    fence runs to end of input."""
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
    """Offset ranges of fenced lines and inline code spans."""
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

    Mirrors `extract_section`'s first-match, level-2/3 rules but skips fenced
    lines; `extract_section` only gates which sections are present.
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

    A collocation-family phrase in a premise region, outside graded spans and
    code; plus each blockquoted `Verified:` line outside graded spans and code.
    Mints no verdict.
    """
    content_lines = body.splitlines()
    line_offset = []
    acc = 0
    for raw in body.splitlines(keepends=True):
        line_offset.append(acc)
        acc += len(raw)

    fenced_lines = _fenced_line_set(content_lines)
    region = _premise_regions(body, content_lines, fenced_lines)
    excluded = _graded_spans(body) + _code_spans(content_lines, line_offset, fenced_lines)

    detections = []
    for match in _COLLOCATION_RE.finditer(body):
        start = match.start()
        index = bisect.bisect_right(line_offset, start) - 1
        if index not in region:
            continue
        if any(low <= start < high for low, high in excluded):
            continue
        detections.append((start, region[index], match.group(0),
                           content_lines[index].strip()))
    for match in _BLOCKQUOTE_VERIFIED.finditer(body):
        start = match.start()
        # Reported regardless of section, unless graded or in code (#1866).
        if any(low <= start < high for low, high in excluded):
            continue
        index = bisect.bisect_right(line_offset, start) - 1
        detections.append((start, 'blockquote', 'Verified:',
                           content_lines[index].strip()))
    detections.sort(key=lambda detection: detection[0])
    return [f'ungraded_claim={number} region={label} phrase={phrase} detail={sentence}'
        for number, (_start, label, phrase, sentence)
        in enumerate(detections, start=1)]


class _ArgParser(argparse.ArgumentParser):
    """Remaps argparse's status 2 (this helper's REFUTED code) to 3.

    Overrides `exit`, not only `error`, because an action can call
    `parser.exit(2)` directly. Status 0 (`--help`) is left alone.
    """

    def exit(self, status=0, message=None):
        super().exit(EXIT_UNESTABLISHED if status == EXIT_REFUTED else status,
                     message)

    def error(self, message):
        self.exit(EXIT_UNESTABLISHED,
                  f'VERIFIED_PREMISES unavailable reason=bad-invocation '
                  f'detail={message}\n')


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call at import (it would mutate an
    importing test's streams); tolerates a stream without `reconfigure` (#1762)."""
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
    parser.add_argument('--repo-root', required=True,
                        help='tree to adjudicate against')
    args = parser.parse_args(argv)
    if not args.repo_root:
        # An empty root would resolve to the cwd, a tree nobody named.
        parser.error('--repo-root must not be empty')

    try:
        return _run(args)
    except Exception as exc:
        # Unestablished, never exit 1 after partial per-bullet output; the
        # traceback goes to stderr so stdout stays machine-clean.
        traceback.print_exc(file=sys.stderr)
        print(f'VERIFIED_PREMISES unavailable reason=internal-error detail={exc!r}')
        return EXIT_UNESTABLISHED


def _run(args) -> int:
    try:
        body = Path(args.body_file).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f'VERIFIED_PREMISES unavailable reason=body-unreadable detail={exc}')
        return EXIT_UNESTABLISHED

    if not body.strip():
        # Not `total=0`: nothing was read, which is not "no premises".
        print('VERIFIED_PREMISES unavailable reason=body-empty '
              'detail=the body file is empty or whitespace-only')
        return EXIT_UNESTABLISHED

    root = Path(args.repo_root).resolve()
    if not root.is_dir():
        # Else every cited path misses and the body reads as a mass refutation.
        print('VERIFIED_PREMISES unavailable reason=repo-root-unusable '
              f'detail={root} is not an existing directory')
        return EXIT_UNESTABLISHED

    tally = {'holds': 0, 'refuted': 0, 'unestablished': 0}
    for index, span in enumerate(parse_bullets(body), start=1):
        handle, paths, quotes, code_literals = classify(span)
        state, detail = recheck(handle, paths, quotes, code_literals, root, span)
        tally[state] += 1
        print(f'bullet={index} handle={handle} state={state} detail={detail}')

    print('VERIFIED_PREMISES total={} holds={} refuted={} unestablished={}'.format(
        sum(tally.values()), tally['holds'], tally['refuted'],
        tally['unestablished']))

    # Detection and emission stay fenced, so an advisory-pass exception is
    # reported here rather than by main's catch-all, which would override the
    # adjudication printed above.
    try:
        ungraded = find_ungraded_claims(body)
        for line in ungraded:
            print(line)
        print(f'UNGRADED_CLAIMS total={len(ungraded)}')
    except Exception as exc:
        # Never `total=0`: that reads as "ran, found none".
        traceback.print_exc(file=sys.stderr)
        print(f'check-verified-premises: ungraded-claim pass failed, reported '
              f'none: {exc!r}', file=sys.stderr)
        print('UNGRADED_CLAIMS unavailable reason=internal-error '
              f'detail={exc!r}')
    return EXIT_REFUTED if tally['refuted'] else EXIT_CLEAN


if __name__ == '__main__':
    sys.exit(main())
