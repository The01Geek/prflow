#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Cap boundary-gated references and skill roots at 95% of the reader's Read cap (issue #1595).

PRFlow loads its phase and reference files progressively behind a boundary gate: the
file's first line must be its `start` marker and its last line the matching `end`
marker, and the loading agent verifies both before acting on the body. A file larger
than the reader can return in one call yields `start` and no `end` — the `truncated`
shape, which `/prflow:implement`, `/prflow:review`, `/prflow:review-and-fix` and
`/prflow:docs-verify` all treat as fail-closed — on a file that is intact on disk.
Nothing measured these files, so growth past the cap reached an author with no signal
at edit time and none in CI.

Threshold derivation
--------------------
The reader's cap is stated in TOKENS and a check can only measure BYTES, so the
conversion is the calibration. The three constants below are recorded separately, each
carrying its own derivation, and `MAX_BYTES` is their product.

`BYTES_PER_TOKEN_FLOOR` is the FLOOR of the measured densities, never their mean. A
denser file truncates at a smaller byte size, so the mean would set a threshold that
passes files the reader cannot return whole. The mechanism behind the spread: the cap
counts the tokens of the *rendered* read output, which carries a line-number prefix per
line, so bytes-per-token falls as lines get shorter. The floor absorbs that overhead
rather than modelling it.

The residual is stated rather than closed: a file that tokenizes below the density
floor truncates below `MAX_BYTES` and passes here.

The skill-root half rests on an unmeasured premise: a skill root reaches an agent
through the Skill tool rather than the Read tool, and whether that path shares the Read
tool's cap is not established. Skill roots are covered because `skills/implement/SKILL.md`
is the always-resident orchestrator holding the very re-anchor triggers and boundary
contract that tell a run how to recover from truncation — losing it to truncation loses
the rules for recovering from truncation.

The covered population
----------------------
Every **boundary-gated reference** plus every **skill root**, derived by inspecting each
file rather than from a transcribed path list, so a new skill directory and a newly-gated
markdown reference are both covered without a second edit.

**Two limits on that, disclosed rather than closed.** Membership is decided only over
tracked files whose name ends `.md`, so a boundary-gated file with any other extension is
outside the population and nothing reports it; and a skill root is recognised by the
`skills/<name>/SKILL.md` shape at any depth, so a root nested under some other directory
name is not. Neither shape exists in the tree today. Both are the same failure direction
this check exists to prevent, which is why they are stated here rather than implied to be
covered.

Two marker families exist and both are covered; a one-family implementation would report
a clean audit that is wrong.

* **Family A** — an HTML comment pair `<!-- prflow:<namespace>-ref <payload> start -->` /
  `<!-- prflow:<namespace>-ref <payload> end -->`, used by `implement`, `review`,
  `create-issue` and `docs-verify`. A file is gated only when both markers carry the same
  namespace and the same payload.
* **Family B** — a `# Reference: <title>` heading paired with `<!-- END <basename> -->`,
  used by `review-and-fix`. A file is gated only when the END marker names that file's own
  basename.

**The boundary line is the first and last NON-BLANK line, for both families.** The two
families' own contracts define it differently — family A by the literal first and last
lines, family B by the first and last non-blank lines — so one rule had to be chosen
deliberately. The non-blank rule is chosen because it is the more inclusive of the two:
a family-A file with a trailing blank line is still audited here. Choosing the literal
rule would drop such a file from the population, which is the failure direction this
check exists to prevent.

A file carrying a `start` marker with no matching `end` is NOT gated, and its size is
not audited — the size ceiling exists to keep a gated read whole, and an ungated file has
no boundary contract to break.

Exemptions
----------
The files already over the ceiling when this landed are carried as **expiring**
exemptions rather than a permanent allowance, recorded in `EXEMPTIONS_DEFAULT`.

* An exemption is attributable to exactly one file, and applies to no file it does not name.
* An exemption records the condition under which it stops applying, and this check FAILS
  once that condition is met — the file is at or under the ceiling — so the list shrinks
  by the suite noticing rather than by anyone remembering.
* An exemption naming a file outside `recorded_set` is REFUSED, so exempting a file is not
  available as a way to make this check pass.

**Disclosed residual on the frozen roster.** `recorded_set` is a hand-edited list, so
nothing here mechanically prevents a future editor from adding a row to it. Two things
narrow that: a row whose `recorded_bytes` is not above the ceiling is refused, so a
compliant file can never be recorded; and widening the roster is a visible edit to a
checked-in record that a reviewer sees. The control is review, not this check.

The record is hand-editable, so it is read as a best-effort parser and fails CLOSED with
a breadcrumb naming the shape rejected — never silently onto an empty exemption set,
which would turn a malformed record into a stricter-looking clean pass over the wrong
population.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

#: The reader's hard cap, in tokens.
READER_CAP_TOKENS = 25_000

#: Headroom under the cap. A file admitted at exactly the cap has none, and every
#: ordinary sentence added to it truncates the next read.
SAFETY_FACTOR = 0.95

#: The measurements the floor below is derived from, as `(path, bytes, tokens)` triples
#: observed TOGETHER on 2026-08-11 — each file's own byte size beside the token count from
#: the Read-tool truncation notice that measured THAT copy, against `cap 25000`.
#:
#: The byte figures are the sizes of the copies measured, NOT current repository sizes:
#: two of the three have since been trimmed. Recording tokens without the bytes they were
#: paired with is what invites the reader to divide a stale token count by a current file
#: size — a pairing that reports a density no measurement produced. `--self-check` proves
#: the floor is really this set's minimum, so the pairing cannot silently drift.
MEASURED_DENSITIES = (
    ("skills/create-issue/references/step-3-6-audit.md", 81869, 28356),
    ("skills/implement/phases/phase-1-setup.md", 68901, 26496),
    ("skills/review-and-fix/references/fixing.md", 73799, 26053),
)

#: Bytes per token, the FLOOR of the measured densities above (2.600, 2.833, 2.887) and
#: never their mean — see the module docstring for why the mean would admit files the
#: reader cannot return.
BYTES_PER_TOKEN_FLOOR = 2.60

#: The ceiling this check enforces, derived from the three constants above.
MAX_BYTES = int(READER_CAP_TOKENS * SAFETY_FACTOR * BYTES_PER_TOKEN_FLOOR)

#: The exemption record, relative to the resolved root.
EXEMPTIONS_DEFAULT = "lib/test/reference-size-exemptions.json"

#: Schema versions this reader understands. An unrecognized version is refused rather
#: than read under guessed semantics.
KNOWN_SCHEMA_VERSIONS = (1,)

#: Fixture trees carry deliberately-malformed and deliberately-oversized members, so
#: auditing them would report this suite's own fixtures as violations.
EXCLUDED_PREFIXES = ("lib/test/fixtures/",)

#: The kinds `classify` can return, paired with how a coverage refusal names each. The
#: whole-tree completeness guard iterates THIS — adding a marker family to `classify`
#: without adding its row here would ship a family the guard never checks for.
COVERED_KINDS = (
    ("gated-a", "the HTML-comment marker family"),
    ("gated-b", "the Reference-heading marker family"),
    ("skill-root", "the skill-root shape"),
)

# Family B's two marker shapes are also spelled inline in lib/test/run.sh's `#530` block
# (its first-non-blank `# Reference: ` probe and its `<!-- END … -->` sed extraction) — a
# change to either marker contract updates both sites or the two disagree about which
# files are gated.
_FAMILY_A = re.compile(
    r"^<!--\s*prflow:(?P<ns>[a-z][a-z0-9-]*)-ref\s+(?P<payload>.*?)\s+(?P<edge>start|end)\s*-->$"
)
_FAMILY_B_START = re.compile(r"^#\s+Reference:\s*\S")
_FAMILY_B_END = re.compile(r"^<!--\s*END\s+(?P<name>\S+\.md)\s*-->$")
# Match a skill root at ANY depth, not only the repo-root `skills/` tree: a probe or
# vendored plugin keeps its skill roots under a nested `…/skills/<name>/SKILL.md`, and a
# root-anchored pattern would leave them outside the population while the docstring claims
# every skill root is covered.
_SKILL_ROOT = re.compile(r"(^|/)skills/[^/]+/SKILL\.md$")

_TOOL = "lint-reference-size"


def _load_population_reader() -> object:
    """Import the shared population reader by the idiom this directory already uses."""
    path = Path(__file__).resolve().parent / "lint_population.py"
    spec = importlib.util.spec_from_file_location("lint_population", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"{_TOOL}: could not load the shared population reader at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for attribute in (
        "LS_FILES_INDEX", "EnumerationError", "enumerate_population",
        "read_source", "add_population_arguments", "resolve_root",
    ):
        if not hasattr(module, attribute):
            raise SystemExit(
                f"{_TOOL}: the shared population reader has no {attribute} — refusing to "
                "audit against a reader whose contract has drifted"
            )
    return module


_pop = _load_population_reader()


class RecordError(Exception):
    """The exemption record could not be read as a well-formed record."""


def classify(relative: str, text: str) -> tuple[str, str] | None:
    """Return `(kind, detail)` when `relative` is in the covered population, else None.

    `kind` is `gated-a`, `gated-b`, or `skill-root`; `detail` is the family-A namespace,
    the family-B END-marker name, or the skill directory. Membership is decided by
    reading the file, which is why an unreadable file is a failure rather than a drop.
    """
    # `search`, not `match`: the pattern's `(^|/)` alternation is what reaches a nested
    # skill root, and `match` anchors at position 0 so the `/` alternative could never fire.
    if _SKILL_ROOT.search(relative):
        return "skill-root", relative.rsplit("/", 2)[-2]

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return None
    first, last = lines[0], lines[-1]

    head, tail = _FAMILY_A.match(first), _FAMILY_A.match(last)
    if head is not None and tail is not None:
        matched = (
            head.group("edge") == "start"
            and tail.group("edge") == "end"
            and head.group("ns") == tail.group("ns")
            and head.group("payload") == tail.group("payload")
        )
        if matched:
            return "gated-a", head.group("ns")
        return None

    if _FAMILY_B_START.match(first):
        end = _FAMILY_B_END.match(last)
        if end is not None and end.group("name") == relative.rsplit("/", 1)[-1]:
            return "gated-b", end.group("name")
    return None


def _list_of(data: dict, key: str) -> list:
    if key not in data:
        raise RecordError(f"the exemption record is missing the {key} key")
    value = data[key]
    if not isinstance(value, list):
        raise RecordError(f"{key} must be a list, found {type(value).__name__}")
    return value


def _entry(raw: object, where: str, required: tuple[str, ...]) -> dict:
    if not isinstance(raw, dict):
        raise RecordError(f"each {where} entry must be an object, found {type(raw).__name__}")
    unknown = sorted(set(raw) - set(required))
    if unknown:
        raise RecordError(f"unknown key(s) in a {where} entry: {', '.join(unknown)}")
    missing = sorted(set(required) - set(raw))
    if missing:
        raise RecordError(f"a {where} entry is missing key(s): {', '.join(missing)}")
    return raw


def _path_of(entry: dict, where: str) -> str:
    value = entry["path"]
    if not isinstance(value, str) or not value.strip():
        raise RecordError(f"a {where} entry's path must be a non-empty string")
    return value


def load_record(path: Path) -> tuple[dict[str, int], dict[str, str]]:
    """Return `(recorded_set, exemptions)` from the record, failing closed on any shape.

    A malformed record must never degrade to an empty exemption set: that reads as a
    stricter check while in fact auditing against a record nobody could parse.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RecordError(f"the exemption record could not be read ({path}): {exc}") from exc
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RecordError(f"the exemption record is not valid JSON ({path}): {exc}") from exc
    if not isinstance(data, dict):
        raise RecordError(
            f"the exemption record's top-level value must be an object, found {type(data).__name__}"
        )

    version = data.get("schema_version")
    if version not in KNOWN_SCHEMA_VERSIONS or isinstance(version, bool):
        raise RecordError(
            f"unrecognized schema_version {version!r} — known: {', '.join(map(str, KNOWN_SCHEMA_VERSIONS))}"
        )
    unknown_top = sorted(set(data) - {"schema_version", "recorded_set", "exemptions"})
    if unknown_top:
        raise RecordError(f"unknown top-level key(s): {', '.join(unknown_top)}")

    recorded: dict[str, int] = {}
    for item in _list_of(data, "recorded_set"):
        entry = _entry(item, "recorded_set", ("path", "recorded_bytes"))
        relative = _path_of(entry, "recorded_set")
        size = entry["recorded_bytes"]
        if not isinstance(size, int) or isinstance(size, bool):
            raise RecordError(f"recorded_bytes for {relative} must be an integer")
        if size <= MAX_BYTES:
            raise RecordError(
                f"recorded_bytes for {relative} is {size}, which is not above the ceiling "
                f"of {MAX_BYTES} — a file that already complies is never recorded"
            )
        if relative in recorded:
            raise RecordError(f"duplicate recorded_set path: {relative}")
        recorded[relative] = size

    exemptions: dict[str, str] = {}
    for item in _list_of(data, "exemptions"):
        entry = _entry(item, "exemptions", ("path", "expires_when"))
        relative = _path_of(entry, "exemptions")
        condition = entry["expires_when"]
        if not isinstance(condition, str) or not condition.strip():
            raise RecordError(f"expires_when for {relative} must be a non-empty string")
        if relative in exemptions:
            raise RecordError(f"duplicate exemption path: {relative}")
        if relative not in recorded:
            raise RecordError(
                f"the exemption for {relative} names a file outside the recorded set — "
                "exempting a file is not available as a way to pass this check"
            )
        exemptions[relative] = condition

    return recorded, exemptions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail when a boundary-gated reference or a skill root exceeds "
            f"{MAX_BYTES} bytes and holds no live exemption (issue #1595)."
        )
    )
    _pop.add_population_arguments(parser)
    parser.add_argument(
        "--exemptions", default=None,
        help=f"the exemption record to read (default: <root>/{EXEMPTIONS_DEFAULT})",
    )
    parser.add_argument(
        "--print-population", action="store_true",
        help="print one 'kind detail path' line per covered file and exit",
    )
    parser.add_argument(
        "--print-threshold", action="store_true",
        help="print the ceiling and the constants it is derived from, and exit",
    )
    parser.add_argument(
        "--self-check", action="store_true",
        help="prove the density floor is the minimum of the recorded measurements, and exit",
    )
    args = parser.parse_args(argv)

    if args.self_check:
        # Without this the floor is a transcribed number: a reader who re-derives it from
        # the wrong byte counts concludes the ceiling is miscalibrated and "corrects" a
        # constant that was right, which is a real review round this repo has already spent.
        densities = []
        for relative, measured_bytes, tokens in MEASURED_DENSITIES:
            if tokens <= 0:
                print(f"{_TOOL}: self-check: {relative} records a non-positive token count",
                      file=sys.stderr)
                return 1
            densities.append((measured_bytes / tokens, relative, measured_bytes, tokens))
        for density, relative, measured_bytes, tokens in sorted(densities):
            print(f"{_TOOL}: self-check: {relative} {measured_bytes}B / {tokens} tok "
                  f"= {density:.3f} bytes/token")
        floor = min(density for density, _r, _b, _t in densities)
        if abs(floor - BYTES_PER_TOKEN_FLOOR) > 0.0005:
            print(
                f"{_TOOL}: self-check FAILED: BYTES_PER_TOKEN_FLOOR is "
                f"{BYTES_PER_TOKEN_FLOOR}, but the minimum recorded density is {floor:.3f} "
                "— re-derive the constant from the measurements, or record the measurement "
                "that justifies it",
                file=sys.stderr,
            )
            return 1
        print(f"{_TOOL}: self-check: floor {BYTES_PER_TOKEN_FLOOR} is the minimum of "
              f"{len(densities)} recorded measurement(s); ceiling {MAX_BYTES} bytes")
        return 0

    if args.print_threshold:
        print(
            f"{_TOOL}: ceiling {MAX_BYTES} bytes = reader cap {READER_CAP_TOKENS} tokens "
            f"x safety factor {SAFETY_FACTOR} x bytes-per-token floor {BYTES_PER_TOKEN_FLOOR} "
            "(the floor of the measured densities, never their mean)"
        )
        return 0

    root = _pop.resolve_root(args.root, tool=_TOOL)
    whole_tree = args.files_from is None

    try:
        population = _pop.enumerate_population(
            root,
            Path(args.files_from) if args.files_from else None,
            ls_files_argv=_pop.LS_FILES_INDEX,
        )
    except _pop.EnumerationError as exc:
        print(f"{_TOOL}: enumeration unusable: {exc}", file=sys.stderr)
        return 1

    candidates = [
        relative for relative in population
        if relative.endswith(".md")
        and not any(relative.startswith(prefix) for prefix in EXCLUDED_PREFIXES)
    ]

    covered: dict[str, tuple[str, str, int]] = {}
    skipped: list[tuple[str, str]] = []
    for relative in candidates:
        target = root / relative
        text, skip_reason = _pop.read_source(target, skip_nul=True)
        if text is None:
            skipped.append((relative, skip_reason or "unknown"))
            continue
        verdict = classify(relative, text)
        if verdict is None:
            continue
        # Measure the RAW bytes: `read_source` normalizes CRLF to LF, so the decoded text's
        # length is not the file's size. Guard this read rather than bare-reading a file
        # already read above — a path that vanishes between the two would otherwise raise an
        # uncaught traceback instead of routing to the skip arm below.
        try:
            size = len(target.read_bytes())
        except OSError as exc:
            skipped.append((relative, f"size unreadable ({exc.__class__.__name__}: {exc})"))
            continue
        kind, detail = verdict
        covered[relative] = (kind, detail, size)

    for relative, reason in skipped:
        print(f"{_TOOL}: SKIPPED {relative}: {reason}", file=sys.stderr)
    if skipped:
        print(
            f"{_TOOL}: {len(skipped)} enumerated path(s) could not be read, so their "
            "membership was never established — refusing to report clean; see the "
            "SKIPPED lines above",
            file=sys.stderr,
        )
        return 1

    if args.print_population:
        for relative in sorted(covered):
            kind, detail, _size = covered[relative]
            print(f"{kind}\t{detail}\t{relative}")
        return 0

    findings: list[str] = []

    # Load the record BEFORE accumulating any finding. A malformed record returns early,
    # so a finding appended above this point would be computed and then discarded unprinted
    # on exactly the run that has two problems at once.
    try:
        exemption_path = (
            Path(args.exemptions) if args.exemptions else root / EXEMPTIONS_DEFAULT
        )
        recorded, exemptions = load_record(exemption_path)
    except RecordError as exc:
        print(f"{_TOOL}: {exc}", file=sys.stderr)
        return 1

    # A whole-tree audit that selected nothing for a family or for the skill-root shape
    # has audited nothing while reading as "audited everything, found nothing" — the exact
    # failure this check exists to prevent, one level up. A run given an explicit narrower
    # population is not required to see every family.
    if whole_tree:
        for kind, what in COVERED_KINDS:
            if not any(entry[0] == kind for entry in covered.values()):
                findings.append(
                    f"{_TOOL}: the whole-tree audit selected nothing for {what} — the "
                    "population could not be established, so this is not a clean pass"
                )

    if whole_tree:
        for relative in sorted(exemptions):
            if relative not in covered:
                findings.append(
                    f"{_TOOL}: the exemption for {relative} names a file that is not in "
                    "the covered population — remove it, or restore the file's boundary "
                    "markers if it was meant to be gated"
                )

    for relative in sorted(covered):
        _kind, _detail, size = covered[relative]
        if size <= MAX_BYTES:
            if relative in exemptions:
                findings.append(
                    f"{relative}: exemption expired — the file is {size} bytes, at or "
                    f"under the {MAX_BYTES}-byte ceiling, which is the condition it "
                    f"recorded ({exemptions[relative]}). Remove its rows from "
                    f"{exemption_path}"
                )
            continue
        if relative in exemptions:
            continue
        findings.append(
            f"{relative}: {size} bytes exceeds the {MAX_BYTES}-byte ceiling — trim the "
            f"file to at most {MAX_BYTES} bytes"
        )

    for finding in findings:
        print(finding)
    print(f"{_TOOL}: audited {len(covered)} of {len(candidates)} files")
    if recorded and not exemptions and whole_tree:
        print(
            f"{_TOOL}: note: the recorded set holds {len(recorded)} file(s) and no "
            "exemption is live",
            file=sys.stderr,
        )
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
