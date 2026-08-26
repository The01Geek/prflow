#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Cap boundary-gated references and skill roots at 95% of the reader's Read cap (issue #1595).

PRFlow loads its phase and reference files progressively behind a boundary gate: the
file's first line must be its `start` marker and its last line the matching `end`
marker, and the loading agent verifies both before acting on the body. A file larger
than the reader can return in one call yields `start` and no `end` on a file intact on
disk. The boundary gate recovers that read by paging the file whole, so the size is no
longer misread as damage — but paging costs extra reads, a reader that truncates without
offering a continuation cannot page at all, and a skill root reaches the agent under no
gate, so the ceiling still forces a trim. Nothing else measured these files, so growth
past the cap reached an author with no signal at edit time and none in CI.

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
#: the floor does not EXCEED this set's minimum; a lower constant only tightens the ceiling.
MEASURED_DENSITIES = (
    ("skills/create-issue/references/step-3-6-audit.md", 81869, 28356),
    ("skills/implement/phases/phase-1-setup.md", 68901, 26496),
    ("skills/review-and-fix/references/fixing.md", 73799, 26053),
)

#: Bytes per token, the FLOOR of the measured densities above (2.600, 2.833, 2.887) and
#: never their mean — see the module docstring for why the mean would admit files the
#: reader cannot return.
BYTES_PER_TOKEN_FLOOR = 2.60

#: The reader's full cap expressed in bytes — the quantity MAX_BYTES reserves its safety
#: margin under. Named (rather than inlined at each use) so the near-full band below and the
#: `--print-threshold` text derive it from one source and cannot drift.
READER_CAP_BYTES = int(READER_CAP_TOKENS * BYTES_PER_TOKEN_FLOOR)

#: The ceiling this check enforces, derived from the three constants above.
MAX_BYTES = int(READER_CAP_TOKENS * SAFETY_FACTOR * BYTES_PER_TOKEN_FLOOR)

#: The near-full band, in bytes: the size of the safety margin the ceiling itself reserves
#: under the reader's full cap — the reader cap in bytes (READER_CAP_BYTES) minus MAX_BYTES.
#: A covered file whose headroom under MAX_BYTES has fallen to within this many bytes has
#: consumed everything but that reserved margin, so the next ordinary edit is what tips it
#: over. Reporting it there (advisory only — see `--print-near-full`, which never fails the
#: suite) reaches the author while a trim is still cheap, rather than after the file has
#: already overflowed for the next author (issue #1614). DERIVED from the same constants as
#: MAX_BYTES, never a transcribed byte figure.
NEAR_FULL_HEADROOM = READER_CAP_BYTES - MAX_BYTES

#: The exemption record, relative to the resolved root.
EXEMPTIONS_DEFAULT = "lib/test/reference-size-exemptions.json"

#: The declared Step 3.6 audit reference set (issue #1702), relative to the resolved root.
#: Read through `lib/test/step36_manifest.py`, the shared validated reader — never re-parsed
#: here, or this lint's accepted record shape drifts from its sibling readers'.
STEP36_MANIFEST_DEFAULT = "lib/test/create-issue-step-3-6-members.json"

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


#: Cache for the lazily-imported shared reader, so the two call sites do not re-exec it.
_S36_READER = None


def _load_step36_reader() -> object:
    """Import the shared Step 3.6 manifest reader by the idiom this directory already uses.

    Called LAZILY, from the two Step 3.6 call sites only — never at module scope. The `#1595`
    self-check runs from a copy of this one file under a temp root, so an import at module
    scope aborts every invocation there, including the ones that never read the manifest.
    """
    global _S36_READER
    if _S36_READER is not None:
        return _S36_READER
    path = Path(__file__).resolve().parent / "step36_manifest.py"
    spec = importlib.util.spec_from_file_location("step36_manifest", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"{_TOOL}: could not load the shared Step 3.6 manifest reader at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for attribute in ("Step36Manifest", "Step36ManifestError", "load"):
        if not hasattr(module, attribute):
            raise SystemExit(
                f"{_TOOL}: the shared Step 3.6 manifest reader has no {attribute} — refusing "
                "to audit against a reader whose contract has drifted"
            )
    _S36_READER = module
    return module


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


class Step36Error(Exception):
    """The Step 3.6 member manifest could not be read as a well-formed record."""


def load_step36_manifest(path: Path):
    """The validated `Step36Manifest`, via the shared reader, or `Step36Error`.

    Every shape decision belongs to `step36_manifest.load` — re-deriving one here is what let
    this lint and `check-audit-lifecycle-contracts.py` accept different manifests.
    """
    reader = _load_step36_reader()
    try:
        return reader.load(path)
    except reader.Step36ManifestError as exc:
        raise Step36Error(str(exc)) from exc


def _resolve_step36_manifest(args, root: Path) -> Path:
    """The Step 3.6 manifest path: the `--step36-manifest` override, else the default under root."""
    return Path(args.step36_manifest) if args.step36_manifest else root / STEP36_MANIFEST_DEFAULT


def check_step36_set(root: Path, manifest_path: Path) -> tuple[list[str], list[str]]:
    """Enforce the Step 3.6 set's per-member ceiling and aggregate source-byte budget.

    Returns `(findings, report_lines)`. `findings` is non-empty when any member exceeds the
    per-member limit or the population's total exceeds the source-recorded pre-refactor
    baseline. Every measurement is `Path.read_bytes()`, and the emitted report names the
    measured population and the baseline commit (issue #1702, AC2/AC3).
    """
    manifest = load_step36_manifest(manifest_path)
    limit = manifest.per_member_limit_bytes
    baseline = manifest.aggregate_baseline_bytes
    commit = manifest.aggregate_baseline_commit
    population = [manifest.entry, *manifest.members]
    findings: list[str] = []
    report: list[str] = []
    total = 0
    for relative in population:
        target = root / relative
        try:
            size = len(target.read_bytes())
        except OSError as exc:
            # An unmeasurable member is unknown, never zero — refuse rather than under-count
            # the aggregate and pass a population it never read.
            findings.append(
                f"step-3-6-set: {relative} could not be measured ({exc.__class__.__name__}: "
                f"{exc}) — the declared member set could not be established")
            continue
        total += size
        report.append(f"step-3-6-set: {relative} {size} bytes (per-member limit {limit})")
        if size > limit:
            findings.append(
                f"step-3-6-set: {relative} is {size} bytes, over the {limit}-byte per-member "
                "authoring limit — split or trim this member")
    report.append(
        f"step-3-6-set: aggregate {total} bytes over {len(population)} files "
        f"(baseline {baseline} bytes @ {commit})")
    if total > baseline:
        findings.append(
            f"step-3-6-set: the population totals {total} bytes, over the source-recorded "
            f"pre-refactor baseline of {baseline} bytes (@ {commit}) — the decomposition must "
            "stay within the pre-refactor total; trim a member")
    return findings, report


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
        "--step36-manifest", default=None,
        help=f"the Step 3.6 member manifest (default: <root>/{STEP36_MANIFEST_DEFAULT})",
    )
    parser.add_argument(
        "--check-step36-set", action="store_true",
        help=("enforce ONLY the Step 3.6 set's per-member ceiling and aggregate source-byte "
              "budget (issue #1702), then exit"),
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
        "--print-near-full", action="store_true",
        help=(
            "print 'path<TAB>headroom' for each covered file within the near-full band "
            "(advisory; never affects the exit code) and exit"
        ),
    )
    parser.add_argument(
        "--self-check", action="store_true",
        help="prove the density floor does not exceed the recorded measurements' minimum, and exit",
    )
    args = parser.parse_args(argv)

    if args.check_step36_set:
        root = _pop.resolve_root(args.root, tool=_TOOL)
        manifest = _resolve_step36_manifest(args, root)
        try:
            s36_findings, s36_report = check_step36_set(root, manifest)
        except Step36Error as exc:
            print(f"{_TOOL}: {exc}", file=sys.stderr)
            return 1
        for line in s36_report:
            print(line)
        for finding in s36_findings:
            print(finding)
        return 1 if s36_findings else 0

    if args.self_check:
        # Without this the floor is a transcribed number, and a reader who re-derives it
        # from the wrong byte counts "corrects" a constant that was right.
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
        # Fail only when the constant EXCEEDS the minimum. That direction raises the ceiling
        # above what the measurements support, admitting files the reader cannot return; a
        # constant below the minimum only lowers the ceiling and is always safe to ship.
        if BYTES_PER_TOKEN_FLOOR > floor + 0.0005:
            print(
                f"{_TOOL}: self-check FAILED: BYTES_PER_TOKEN_FLOOR is "
                f"{BYTES_PER_TOKEN_FLOOR}, above the minimum recorded density {floor:.3f} — "
                f"the {MAX_BYTES}-byte ceiling it derives is more generous than the "
                "measurements support. Re-derive the constant, or record the measurement "
                "that justifies it",
                file=sys.stderr,
            )
            return 1
        print(f"{_TOOL}: self-check: floor {BYTES_PER_TOKEN_FLOOR} does not exceed the "
              f"minimum recorded density {floor:.3f} over {len(densities)} measurement(s); "
              f"ceiling {MAX_BYTES} bytes")
        return 0

    if args.print_threshold:
        print(
            f"{_TOOL}: ceiling {MAX_BYTES} bytes = reader cap {READER_CAP_TOKENS} tokens "
            f"x safety factor {SAFETY_FACTOR} x bytes-per-token floor {BYTES_PER_TOKEN_FLOOR} "
            "(the floor of the measured densities, never their mean)"
        )
        print(
            f"{_TOOL}: near-full band {NEAR_FULL_HEADROOM} bytes = reader cap in bytes "
            f"{READER_CAP_BYTES} minus the {MAX_BYTES}-byte ceiling — a covered file with at "
            "most this much headroom is reported near-full (advisory; never fails the suite)"
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

    if args.print_near_full:
        # A covered file is near-full when its headroom under the ceiling has fallen into
        # the reserved band `[0, NEAR_FULL_HEADROOM]` — headroom 0 (a file exactly at the
        # ceiling) is the most urgent. Over-ceiling files (negative headroom) are excluded:
        # they are already the failing/exemption path, not an advisory. Sorted by headroom
        # ascending, then path, so the file with the least room to spare is reported first
        # and equal-headroom files keep a deterministic order.
        near_full = []
        for relative, (_kind, _detail, size) in covered.items():
            headroom = MAX_BYTES - size
            if 0 <= headroom <= NEAR_FULL_HEADROOM:
                near_full.append((headroom, relative))
        for headroom, relative in sorted(near_full):
            print(f"{relative}\t{headroom}")
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

    if whole_tree:
        for relative in sorted(recorded):
            if relative in exemptions:
                continue
            entry = covered.get(relative)
            if entry is not None and entry[2] <= MAX_BYTES:
                findings.append(
                    f"{relative}: its recorded_set row outlived its exemption — the file is "
                    f"{entry[2]} bytes, at or under the {MAX_BYTES}-byte ceiling. Remove the "
                    f"row from {exemption_path} too; a row left standing re-authorizes a "
                    "future exemption for this file with no visible roster edit"
                )

    if whole_tree:
        manifest = _resolve_step36_manifest(args, root)
        try:
            s36_findings, s36_report = check_step36_set(root, manifest)
        except Step36Error as exc:
            findings.append(f"{_TOOL}: {exc}")
        else:
            for line in s36_report:
                print(line)
            findings.extend(s36_findings)

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
    scope = "whole-tree" if whole_tree else (
        "narrowed (--files-from): the family-completeness and exemption-in-population "
        "guards were NOT applied"
    )
    print(f"{_TOOL}: audited {len(covered)} of {len(candidates)} files [{scope}]")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
