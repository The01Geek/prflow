#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""PRFlow follow-up filer for review-and-fix deferrals.

The /implement skill's Phase 4.0.5 merges the run-scoped deferrals manifests
produced by /devflow:review-and-fix (at `.prflow/tmp/review/<slug>/<run-id>/deferrals.json`,
one per run) into a single slug-level aggregate, passes that aggregate as
`--manifest`, files one follow-up GitHub issue per shared deferral reason
(the finding's category + trimmed explanation + kind; an entry that cannot
supply a full reason falls back to per-file grouping), and rewrites
the aggregate with the assigned issue numbers + deterministic deferral IDs. The /devflow:review
verdict engine then matches these entries against the PR-body block to
demote already-acknowledged findings.

Two classes of entry survive the rewrite carrying NO `follow_up`, because no
follow-up issue is owed for them. `settled-by-disclosure` is the foreclosure
(the already-shipped disclosure is the deliverable). `scheduled-in-run` is the
second: the source issue's own `**Documentation Needed**` block already names
the entry's `file`, so the run's own documentation pass is due to edit it
before the run finishes — filing an issue for work this run is already taking
on only creates a ticket a human must read and close. The filer resolves that
deliverable path set once per run by running
`scripts/extract-doc-needed-paths.sh` over the `--source-issue` body; see
EXTRACTOR_PATH below for the one way that set differs from the one the
documentation-deliverable gate enforces. It writes `scheduled-in-run` onto the
rewritten AGGREGATE's `category` field only; the per-run `deferrals.json` the
fix loop writes never carries it. When the body cannot be read or the
extractor fails, the set is
UNKNOWN rather than empty and every entry files as it would without this
partition.

The helper is repo-agnostic — title/body templates contain no project names
or hardcoded paths. The `<area>` token in titles is derived from the longest
leading path prefix the group's files share (its first non-`src/`-equivalent
segment, or the basename if no such segment exists); a single-file group
therefore keeps the same `<area>` it carried before reason-based grouping.

Usage:
    file-deferrals.py --source-issue N --pr M --manifest PATH [--dry-run]
    file-deferrals.py --source-issue N --pr M --units PATH [--dry-run]

Manifest-mode exit codes:
    0  At least one group of findings was filed successfully (or --dry-run),
       OR there were NO fileable groups at all and the only surviving entries
       are settled-by-disclosure foreclosures (issue #621) and scheduled-in-run
       entries (issue #758), which file NO follow-up issue by design yet still
       survive into the rewritten manifest — a manifest whose entries are ALL
       of those two classes rewrites and exits 0 with zero issue-create calls.
    1  Nothing was filed: either nothing survived at all, or every fileable
       group failed. A surviving foreclosure or scheduled-in-run entry does NOT
       mask a complete filing failure (issue #660 review) — neither needs a
       `gh` call, so neither can evidence that filing worked. Also 1 on
       invalid input.
    2  Bad arguments / unusable manifest.

Units-mode exit codes:
    0  Every validated unit was filed successfully (or --dry-run).
    1  Some validated units were filed and some failed.
    2  Input was invalid, no units were present, or every create attempt failed.
"""

import argparse
import datetime
import hashlib
import json
import os
import shlex
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gh_fresh_env import fresh_gh_env

# lib/ is a sibling of scripts/ in the source repo and in a vendored
# .prflow/vendor/prflow/ tree alike, so this import path holds on every tier.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
try:
    import bash_launch as _bl
except Exception:  # pragma: no cover - import-time arm
    # Unlike resolve-review-overrides.py, a missing launch helper must NOT abort
    # this process: filing follow-up issues is this helper's job and needs no
    # bash. Only the deliverable lookup below degrades, and it degrades to
    # "unknown", which files every entry exactly as it did before issue #758.
    _bl = None

# The gh binary to shell out to. `DEVFLOW_GH` (the documented override the shell
# helpers resolve via lib/resolve-gh.sh) wins when set and non-empty; else `gh`.
GH = os.environ.get("DEVFLOW_GH") or "gh"

SCHEMA_VERSION = 1
ID_PREFIX = "dfr-"
ID_HEX_LEN = 6

# issue #621: a settled-by-disclosure foreclosure files NO follow-up issue —
# the already-shipped disclosure is the deliverable. The manifest this helper
# reads is the FLAT shape (review-and-fix loop-exit deferrals.json → implement
# Phase 4.0.5 slug aggregate), so the discriminator is the top-level `category`
# field; a nested `reason.category` is accepted defensively too.
FORECLOSURE_CATEGORY = "settled-by-disclosure"

# issue #758: the second file-nothing class. An entry whose `file` the source
# issue's **Documentation Needed** block already names is discharged by the
# run's own documentation pass, which cannot be skipped, so filing a follow-up
# issue for it only manufactures hand cleanup. Written ONLY here, onto the
# rewritten aggregate's `category`; the fix loop's skip_category set is
# unchanged. The same top-level-or-nested discriminator as above makes a re-run
# over an already-rewritten aggregate idempotent even if the deliverable lookup
# then fails.
SCHEDULED_CATEGORY = "scheduled-in-run"

# The deterministic reader of an issue body's **Documentation Needed** block,
# anchored beside this script rather than resolved from PATH or the cwd. Calling
# it (instead of re-deriving the path list by hand) gives this filer the SAME
# scope, tokenization and suppression rules the documentation-deliverable gate
# reads the block with. One difference remains, and it is deliberate: the gate's
# reader (scripts/read-doc-needed-deliverables.sh) resolves the configured
# documentation-location allowlist from config and exports it as
# DEVFLOW_DOC_NEEDED_ALLOWLIST before running the extractor; this caller does
# not resolve it, and only passes one through when the surrounding environment
# already exports it. Unset leaves the extractor's location test inactive, so
# this set is a SUPERSET of the gate's — a path named in the block but outside
# the allowlist matches here and is refused there. That direction only ever
# suppresses a filing, never creates a spurious one, which is why the allowlist
# resolution (four config reads with their own fail-closed arms) is not
# duplicated here. `DEVFLOW_DOC_NEEDED_EXTRACTOR` overrides the path below, the
# same test seam scripts/read-doc-needed-deliverables.sh honours.
EXTRACTOR_PATH = Path(__file__).resolve().parent / "extract-doc-needed-paths.sh"


def _entry_category(entry: dict) -> tuple[object, object]:
    """The flat and nested category slots of a manifest entry, read safely.

    The aggregate is agent-mutable JSON this helper does not produce, so
    `reason` can arrive as a list/scalar/None; a bare `(entry.get("reason") or
    {}).get(...)` raises on the non-dict shapes. Both slots degrade to None.
    """
    reason = entry.get("reason")
    nested = reason.get("category") if isinstance(reason, dict) else None
    return (entry.get("category"), nested)


def _is_foreclosure(entry: dict) -> bool:
    return FORECLOSURE_CATEGORY in _entry_category(entry)


def _is_scheduled(entry: dict) -> bool:
    return SCHEDULED_CATEGORY in _entry_category(entry)


def _deliverable_paths(source_issue: int) -> tuple[frozenset[str], str | None]:
    """The `**Documentation Needed**` paths of `source_issue`'s body.

    Returns `(paths, cause)`. A non-None `cause` means the set is UNKNOWN — the
    caller then partitions nothing and every entry files as it did before issue
    #758. Only a clean read that named no path returns an empty set with no
    cause, so "could not read" is never collapsed onto "named nothing".

    Every arm catches `Exception`, not a curated tuple. The contract this
    function offers its caller is that ANY lookup failure degrades to unknown;
    a narrower catch would let one unanticipated exception class escape and
    abort a filing run whose real work — creating the follow-up issues — does
    not depend on this lookup at all. `BaseException` is deliberately NOT
    caught: a KeyboardInterrupt or SystemExit is not a degraded read.
    """
    try:
        read = _run([GH, "issue", "view", str(source_issue), "--json", "body"],
                    check=False)
    except Exception as exc:
        return (frozenset(), f"body-read-failed:{type(exc).__name__}: {exc}"[:160])
    if read.returncode != 0:
        first = ((read.stderr or "").strip().splitlines() or [""])[0][:120]
        return (frozenset(), f"body-read-failed:rc={read.returncode} {first}".strip())
    try:
        body = json.loads(read.stdout)["body"]
    except Exception as exc:
        return (frozenset(), f"body-read-failed:{type(exc).__name__}")
    if not isinstance(body, str):
        return (frozenset(), f"body-read-failed:body-is-{type(body).__name__}")

    extractor = os.environ.get("DEVFLOW_DOC_NEEDED_EXTRACTOR") or str(EXTRACTOR_PATH)
    if _bl is None:
        return (frozenset(), "extractor-failed:launch-helper-unimportable")
    # `bash` stays a literal here, not a shared resolver call: cloud_writer_deps.py
    # verifies this file's declared exec edge from a statically resolvable binding.
    bash = os.environ.get("DEVFLOW_BASH") or "bash"
    try:
        argument = _bl.script_argument(Path(extractor), cwd=Path.cwd(), bash=bash)
        out = subprocess.run(
            [bash, argument], input=body, check=False,
            capture_output=True, encoding="utf-8",
        )
    except Exception as exc:
        return (frozenset(), f"extractor-failed:{type(exc).__name__}: {exc}"[:160])
    if out.returncode != 0:
        first = ((out.stderr or "").strip().splitlines() or [""])[0][:120]
        return (frozenset(), f"extractor-failed:rc={out.returncode} {first}".strip())
    return (frozenset(
        line.strip() for line in out.stdout.splitlines() if line.strip()
    ), None)


def _scheduled_deliverable(entry: dict, deliverables: frozenset[str]) -> str | None:
    """The deliverable path discharging `entry`, or None if none does.

    EXACT equality against the extractor's own output, which is a set of bare
    repo-relative POSIX paths. So `./docs/a.md`, `docs/a.md/` and a bare
    `a.md` are all non-matches by construction — this decides whether a
    follow-up issue is created, and a fuzzy match would silently drop one. A
    `file` that is an object, array, number, None, absent or empty never
    matches.
    """
    value = entry.get("file")
    if not isinstance(value, str) or not value:
        return None
    return value if value in deliverables else None


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8, idempotently and defensively. Called from
    the CLI entry path only (not at import) so importing this module for unit
    tests never mutates the importer's global streams. The em-dash/ellipsis this
    script emits (issue-body lines, the dry-run preview) would otherwise raise
    `UnicodeEncodeError` under a non-UTF-8 ambient codec (Windows' cp1252).
    Reconfigure overrides even a hostile `PYTHONIOENCODING`; the guard tolerates
    a non-`TextIOWrapper` stream (e.g. a test's `io.StringIO`)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def _run(cmd, *, stdin=None, check=True):
    # `encoding="utf-8"` pins both directions of the gh pipe (decode of output,
    # encode of stdin) so neither raises under a non-UTF-8 ambient codec. Implies
    # text mode, so `text=True` is dropped (passing both is redundant).
    return subprocess.run(
        cmd, check=check, stdin=stdin,
        capture_output=True, encoding="utf-8", env=fresh_gh_env(),
    )


def _fail(msg, code=1):
    sys.stderr.write(f"file-deferrals.py: {msg}\n")
    sys.exit(code)


def _now_iso():
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gh_login():
    """Whoever is actually filing — for the manifest's follow_up.filed_by.

    Tries gh api user first (works for personal access tokens). Falls back
    to GITHUB_ACTOR, then "(unknown)", on ANY gh failure mode — not just the
    canonical 403 "Resource not accessible by integration" you get when
    GITHUB_TOKEN in Actions lacks user:read. That covers any non-zero gh
    exit or empty stdout (403, expired tokens, 5xx, DNS errors,
    rate-limiting) as well as any OS-level spawn failure: these all
    surface as an OSError subclass and are handled uniformly (the
    breadcrumb records only the exception class name) — e.g. gh missing
    from PATH, not executable, wrong arch, or fd/memory exhaustion.
    filed_by is informational only —
    never gate logic — so we degrade rather than fail the run, but we
    leave a stderr breadcrumb so operators can see when the primary lookup
    didn't work. (A non-OSError like UnicodeDecodeError from exotic gh
    output is out of scope by design — the `.login` field is ASCII.)
    """
    rc_info = "no-binary"
    stderr_info = ""
    try:
        r = _run([GH, "api", "user", "--jq", ".login"], check=False)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
        rc_info = str(r.returncode)
        _err_lines = (r.stderr or "").strip().splitlines()
        stderr_info = _err_lines[0][:120] if _err_lines else ""
    except OSError as e:
        rc_info = f"spawn-error ({type(e).__name__})"
        stderr_info = f"{type(e).__name__}: {e}"[:120]
    sys.stderr.write(
        f"file-deferrals.py: gh api user unavailable "
        f"(rc={rc_info}, stderr={stderr_info!r}), falling back to GITHUB_ACTOR\n"
    )
    actor = os.environ.get("GITHUB_ACTOR", "").strip()
    if actor:
        return actor
    sys.stderr.write(
        "file-deferrals.py: GITHUB_ACTOR unset, filed_by will be '(unknown)'\n"
    )
    return "(unknown)"


def _derive_area(file_path: str) -> str:
    """First non-`src/`-equivalent segment, or basename without extension.

    Examples:
        src/example/transport/http.py -> example
        src/transport/http.py         -> transport
        pyproject.toml                -> pyproject
        scripts/foo/bar.sh            -> scripts
    """
    parts = Path(file_path).parts
    src_like = {"src", "lib", "pkg", "app", "source", "sources"}
    for i, part in enumerate(parts):
        if part.lower() in src_like and i + 1 < len(parts):
            return parts[i + 1]
    if len(parts) > 1:
        return parts[0]
    return Path(file_path).stem or "general"


def _coerce_str(value: object) -> str:
    """Coerce a possibly-non-string manifest field to a string.

    The review agents' manifest is external input this helper does not produce,
    so a field may arrive as an int/list/None; a bare .strip()/join over one
    raises (the fail-open shape #437 hardened for manifest shape). This degrades
    it instead, and is identical for the string corpus. A falsy non-string
    (0, False, []) coerces to its own string form ("0", "False", "[]"), not "",
    so distinct values keep distinct identity payloads in _compute_id.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        sys.stderr.write(
            f"file-deferrals.py: coerced non-string manifest field "
            f"({type(value).__name__}) to its string form\n"
        )
        return str(value)
    return value


def _compute_id(entry: dict) -> str:
    """Deterministic ID from the finding's stable identity fields.

    Re-running on the same manifest produces the same ID — important so the
    verdict engine's signature match is stable across regenerations.

    Known, accepted collision (raised as a #660 review Suggestion, DECLINED):
    two distinct entries on the same file with empty symbol/kind/summary hash
    identically. No observable effect today — nothing de-dupes by id, and both
    entries survive independently into the manifest and the PR-body payload.
    Widening the payload (e.g. with `line_range`) would change every existing
    id, breaking the cross-regeneration stability this docstring promises and
    the verdict engine relies on — a real contract change to fix a defect with
    no current symptom. Revisit if and when a consumer de-dupes by id; that
    consumer's introduction is the trigger to re-key, all sites at once.
    """
    payload = "|".join([
        _coerce_str(entry.get("file")),
        _coerce_str(entry.get("symbol")),
        _coerce_str(entry.get("kind")),
        _coerce_str(entry.get("summary")).strip(),
    ])
    h = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:ID_HEX_LEN]
    return f"{ID_PREFIX}{h}"


def _format_line_range(line_range) -> str:
    if not isinstance(line_range, (list, tuple)) or len(line_range) != 2:
        return "(unspecified)"
    start, end = line_range
    if start == end:
        return str(start)
    return f"{start}-{end}"


def _render_issue_body(group_findings, source_issue: int, pr_number: int) -> str:
    """Issue body — repo-agnostic, contains the mutual-cross-link substring.

    The 'PR #<n>' substring on the first line is what the verdict engine's
    cross-link guard validates against. Do not reformat it without updating
    the matcher.
    """
    lines = [
        (f"Carried forward from the /implement run on #{source_issue} "
        f"(PR #{pr_number})."),
        "",
        ("The following review-agent findings were surfaced during PR review "
        "but deferred under the Scope-Acknowledged Findings contract. They are "
        "tracked here for follow-up resolution. Closing this issue invalidates "
        "the related deferral and forces re-verification on the next "
        "/devflow:review run."),
        "",
        "## Findings",
        "",
    ]
    for f in group_findings:
        severity = f.get("severity", "Unknown")
        agent = f.get("agent", "unknown-agent")
        file_ = f.get("file", "(unknown)")
        line_str = _format_line_range(f.get("line_range"))
        symbol = f.get("symbol", "") or "(unspecified)"
        kind = f.get("kind", "(unspecified)")
        summary = _coerce_str(f.get("summary")).strip()
        category = f.get("category", "(unspecified)")
        explanation = _coerce_str(f.get("explanation")).strip()
        lines.extend([
            f"### {severity} — {agent}",
            f"**File**: {file_}:{line_str}",
            f"**Symbol**: {symbol}",
            f"**Kind**: {kind}",
            "",
            summary,
            "",
            f"**Why deferred**: {category} — {explanation}",
            "",
        ])
    lines.extend([
        "---",
        "Filed automatically by devflow-implement.",
    ])
    return "\n".join(lines)


def _reason_key(entry: dict) -> tuple[str, str, str, str] | None:
    """Reason-based grouping key for an entry, or None if it cannot supply one.

    Two findings share a follow-up issue when they agree on category,
    explanation, and kind, each compared after leading/trailing whitespace is
    stripped, so a value differing only in surrounding whitespace does not
    over-split into two issues. All three must be non-empty strings; an entry
    missing any one, holding an empty/whitespace-only value, or a non-string
    falls back to file grouping. The stripped category and kind also become the
    title's, so the title carries no surrounding whitespace either. The leading
    "reason" tag keeps this key from ever colliding with the ("file", …)
    fallback key in the same bucket map.
    """
    cat = entry.get("category")
    exp = entry.get("explanation")
    kind = entry.get("kind")
    if not (isinstance(cat, str) and isinstance(exp, str) and isinstance(kind, str)):
        return None
    if not (cat.strip() and exp.strip() and kind.strip()):
        return None
    return ("reason", cat.strip(), exp.strip(), kind.strip())


def _shared_area(file_values: list[str]) -> str:
    """`_derive_area` applied to the longest leading path prefix the group's
    files share. Files are POSIX repository-relative paths, so the prefix is
    computed with PurePosixPath rather than the native Path (which would split a
    forward-slash path differently on Windows). A single-file group yields the
    same `<area>` its per-file title carried before issue #602.
    """
    if not file_values:
        return _derive_area("(unknown)")
    # _coerce_str prevents a non-string `file` from raising in PurePosixPath.
    part_lists = [PurePosixPath(_coerce_str(fv)).parts for fv in file_values]
    common: list[str] = []
    for column in zip(*part_lists):
        if all(part == column[0] for part in column):
            common.append(column[0])
        else:
            break
    return _derive_area("/".join(common))


def _issue_title(area: str, kind: str, category: str, source_issue: int) -> str:
    return (
        f"{area}: deferred review findings — {kind} ({category}) "
        f"(carried from #{source_issue})"
    )


def _create_issue(title: str, body: str, dry_run: bool) -> tuple[int, str]:
    """Returns (issue_number, issue_url). Raises on failure."""
    if dry_run:
        sys.stderr.write(
            f"[dry-run] would file issue: {title}\n"
            f"[dry-run] body preview ({len(body)} chars):\n"
            f"{body[:300]}{'…' if len(body) > 300 else ''}\n"
        )
        return (0, "https://example.invalid/dry-run")

    # `encoding="utf-8"` pins the stdin pipe so a non-ASCII issue body (em-dash,
    # ellipsis) is encoded as UTF-8 rather than through the locale codec. Implies
    # text mode, so `text=True` is dropped.
    # An OSError (ENOEXEC from a non-executable `gh` shim, or gh absent) is
    # routed through the caller's existing RuntimeError surface rather than
    # escaping as a raw traceback.
    try:
        r = subprocess.run(
            [GH, "issue", "create", "--title", title, "--body-file", "-"],
            input=body, check=False, encoding="utf-8",
            capture_output=True, env=fresh_gh_env(),
        )
    except OSError as e:
        raise RuntimeError(
            f"could not execute {GH!r}: {e} "
            f"(set DEVFLOW_GH to a working GitHub CLI)"
        ) from e
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    # Empty stdout on a zero exit must raise the same RuntimeError both callers
    # already catch; a bare `.splitlines()[-1]` would raise IndexError, which the
    # manifest loop's `except RuntimeError` lets escape as a traceback.
    lines = r.stdout.strip().splitlines()
    if not lines:
        raise RuntimeError(f"gh reported success but printed no issue URL: {r.stdout!r}")
    url = lines[-1].strip()
    if "/issues/" not in url:
        raise RuntimeError(f"unexpected gh output: {r.stdout!r}")
    number = int(url.rsplit("/", 1)[-1])
    return (number, url)


def _write_manifest_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _record_value(value: object) -> str:
    """Encode one value for the helper's shell-token record lines."""
    text = str(value).translate(str.maketrans({
        "\n": r"\n", "\r": r"\r", "\v": r"\v", "\f": r"\f",
        "\x1c": r"\x1c", "\x1d": r"\x1d", "\x1e": r"\x1e",
        "\x85": r"\x85", "\u2028": r"\u2028", "\u2029": r"\u2029",
    }))
    return shlex.quote(text)


def _print_filing(result: str, *, cause: str | None = None) -> None:
    fields = ["filing", f"result={result}"]
    if cause:
        fields.append(f"cause={_record_value(cause)}")
    print(" ".join(fields))


def _load_units(path: Path) -> tuple[list[tuple[str, str, str]], str | None]:
    """Validate and decode every unit before the first GitHub write."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return ([], f"units-unreadable:{exc}")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        return ([], f"units-invalid-json:{exc}")
    if not isinstance(document, list):
        return ([], "units-not-array")

    units: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for index, unit in enumerate(document):
        if not isinstance(unit, dict):
            return ([], f"unit-{index}-not-object")
        values: dict[str, str] = {}
        for field in ("key", "title", "body_file"):
            value = unit.get(field)
            if not isinstance(value, str) or not value.strip():
                return ([], f"unit-{index}-{field}-invalid")
            values[field] = value.strip() if field != "body_file" else value
        key = values["key"]
        if key in seen:
            # A bare `continue` would drop the later copy with no record, hiding
            # a real duplicate-key manifest from the run's own output.
            print(f"unit key={_record_value(key)} skipped=duplicate")
            continue
        try:
            body = Path(values["body_file"]).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return ([], f"unit-{index}-body-unreadable:{exc}")
        seen.add(key)
        units.append((key, values["title"], body))
    if not units:
        return ([], "units-empty")
    return (units, None)


def _run_units(path: Path, *, dry_run: bool) -> int:
    units, cause = _load_units(path)
    if cause:
        _print_filing("none", cause=cause)
        return 2

    succeeded = 0
    failed = 0
    for key, title, body in units:
        try:
            number, url = _create_issue(title, body, dry_run)
        except Exception as exc:
            failed += 1
            print(f"unit key={_record_value(key)} cause={_record_value(exc)}")
            continue
        succeeded += 1
        print(f"unit key={_record_value(key)} number={number} url={_record_value(url)}")

    if failed == 0:
        _print_filing("all")
        return 0
    if succeeded:
        _print_filing("partial")
        return 1
    _print_filing("none", cause="all-units-failed")
    return 2


def main(argv=None):
    _force_utf8_streams()
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--source-issue", type=int, required=True,
                   help="Issue number that triggered the /implement run.")
    p.add_argument("--pr", type=int, required=True,
                   help="PR number created by /implement Phase 3.1.")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest",
                        help="Path to deferrals.json from review-and-fix.")
    source.add_argument("--units",
                        help="JSON array of independently fileable units.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print actions; do not file issues or modify manifest.")
    args = p.parse_args(argv)

    if args.units is not None:
        return _run_units(Path(args.units), dry_run=args.dry_run)

    manifest_path = Path(args.manifest)
    if not manifest_path.is_file():
        _fail(f"manifest not found: {manifest_path}", code=2)

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        _fail(f"manifest is not valid JSON: {e}", code=2)

    # A valid-JSON-but-non-object manifest would make manifest.get(...) below raise an
    # uncaught AttributeError (traceback, exit 1) instead of the documented exit-2 fail;
    # the --units sibling hardens the same shape via _load_units.
    if not isinstance(manifest, dict):
        _fail(
            f"manifest is not a JSON object (got {type(manifest).__name__}) — "
            "cannot read schema_version or deferrals", code=2,
        )

    if manifest.get("schema_version") != SCHEMA_VERSION:
        _fail(
            f"manifest schema_version={manifest.get('schema_version')!r} "
            f"unsupported (expected {SCHEMA_VERSION})", code=2,
        )

    deferrals = manifest.get("deferrals") or []
    if not deferrals:
        _fail("manifest contains no deferrals — nothing to file", code=2)

    # A non-array `deferrals`, or a non-object entry, would raise an uncaught AttributeError
    # in the `.get`/iteration below instead of the documented exit-2 fail.
    if not isinstance(deferrals, list):
        _fail(
            f"manifest 'deferrals' is not a JSON array (got {type(deferrals).__name__})",
            code=2,
        )
    for _index, _entry in enumerate(deferrals):
        if not isinstance(_entry, dict):
            _fail(
                f"manifest deferrals[{_index}] is not a JSON object "
                f"(got {type(_entry).__name__})", code=2,
            )

    if any(d.get("follow_up") for d in deferrals):
        _fail(
            "manifest already has follow_up entries — refusing to re-file. "
            "Delete the manifest and re-run review-and-fix to regenerate.",
            code=2,
        )

    filed_by = _gh_login() if not args.dry_run else "(dry-run-user)"
    filed_at = _now_iso()

    # issue #758: resolve the run's documentation-deliverable path set ONCE,
    # before partitioning. An unreadable body or a failed extractor leaves the
    # set unknown, which is recorded and files everything — never silently
    # read as "the issue named no deliverable".
    deliverables, deliverables_cause = _deliverable_paths(args.source_issue)
    if deliverables_cause:
        print(f"{SCHEDULED_CATEGORY} result=unavailable "
              f"cause={_record_value(deliverables_cause)}")

    # issue #621: partition foreclosures out of the fileable groups. A
    # foreclosure files no issue but still survives into the rewritten manifest
    # unchanged (with an `id` assigned for the dfr- match), so /pr-description
    # and /devflow:review can carry and honor it. issue #758 adds the second
    # such partition, keyed on the deliverable set resolved above.
    # issue #602: group by the shared deferral reason (category + trimmed
    # explanation + kind), not by source file, so findings deferred for one
    # reason across several files file ONE follow-up issue. An entry that cannot
    # supply a full reason falls back to its own `file` value — the ("reason",…)
    # and ("file",…) key tags keep the two kinds from colliding in one map.
    groups: OrderedDict[tuple[str, ...], list[dict]] = OrderedDict()
    foreclosures: list[dict] = []
    scheduled: list[tuple[dict, str]] = []
    for d in deferrals:
        if _is_foreclosure(d):
            # A foreclosure wins over the scheduled partition: it already
            # carries a disclosure citation and renders in the PR body.
            foreclosures.append(d)
            continue
        discharged_by = _scheduled_deliverable(d, deliverables)
        if discharged_by is None and _is_scheduled(d):
            discharged_by = "(already-marked)"
        if discharged_by is not None:
            scheduled.append((d, discharged_by))
            continue
        key = _reason_key(d) or ("file", d.get("file", "(unknown)"))
        groups.setdefault(key, []).append(d)

    succeeded_numbers: list[int] = []
    failed_groups: list[str] = []
    surviving: list[dict] = []

    for key, findings in groups.items():
        files = [f.get("file", "(unknown)") for f in findings]
        area = _shared_area(files)
        if key[0] == "reason":
            kind, category = key[3], key[1]
        else:
            kind = category = "(unspecified)"
        title = _issue_title(area, kind, category, args.source_issue)
        # A single group no longer maps to one file, so name it by an
        # identifying label rather than a bare filename in the failure report.
        label = f"{area} — {kind} ({category}) [{', '.join(_coerce_str(fv) for fv in files)}]"
        body = _render_issue_body(findings, args.source_issue, args.pr)
        try:
            number, url = _create_issue(title, body, args.dry_run)
        except RuntimeError as e:
            sys.stderr.write(
                f"file-deferrals.py: failed to file issue for "
                f"{label}: {e}\n"
            )
            failed_groups.append(label)
            continue

        for f in findings:
            entry = dict(f)
            entry["id"] = _compute_id(f)
            entry["follow_up"] = {
                "issue": number,
                "url": url,
                "filed_at": filed_at,
                "filed_by": filed_by,
            }
            surviving.append(entry)
        succeeded_numbers.append(number)

    # issue #621: pass foreclosure entries through unchanged (no follow_up),
    # assigning the deterministic dfr- id so the PR-body payload and the
    # verdict matcher can key on it. `setdefault` keeps a prior id on a re-run.
    for d in foreclosures:
        entry = dict(d)
        entry.setdefault("id", _compute_id(d))
        surviving.append(entry)

    # issue #758: a scheduled-in-run entry files no issue either — the run's own
    # documentation pass is already obliged to edit its file before the run can
    # finish. It keeps its place in the rewritten aggregate under the new
    # category so nothing downstream renders it as outstanding, and its record
    # names the finding id and the deliverable that discharges it.
    for d, discharged_by in scheduled:
        entry = dict(d)
        entry.setdefault("id", _compute_id(d))
        entry["category"] = SCHEDULED_CATEGORY
        if isinstance(entry.get("reason"), dict):
            entry["reason"] = dict(entry["reason"], category=SCHEDULED_CATEGORY)
        surviving.append(entry)
        print(f"{SCHEDULED_CATEGORY} id={_record_value(entry['id'])} "
              f"file={_record_value(d.get('file'))} "
              f"deliverable={_record_value(discharged_by)}")

    if not surviving:
        # Nothing filed AND no foreclosure or scheduled-in-run entry survived.
        # (A manifest of only those classes reaches here with `surviving`
        # non-empty and exits 0 — zero issue-create calls, but the aggregate is
        # still rewritten.)
        _fail("no follow-up issues filed and no entries survived — "
              "every fileable group failed", code=1)

    if failed_groups and not succeeded_numbers:
        # issue #660 review: a COMPLETE filing failure is a hard signal even
        # when a foreclosure survives to make `surviving` non-empty. Without
        # this arm a manifest mixing one `settled-by-disclosure` entry with
        # fileable groups that ALL failed would exit 0, silently dropping every
        # failed real deferral from the rewritten manifest. Neither a
        # foreclosure nor a scheduled-in-run entry needs a `gh` call, so
        # neither can evidence that filing worked.
        _fail(f"no follow-up issues filed — every fileable group failed "
              f"({len(failed_groups)} group(s)); "
              f"{len(foreclosures)} foreclosure(s) and {len(scheduled)} "
              f"scheduled-in-run entry(ies) survived but do not "
              f"constitute a successful filing", code=1)

    new_manifest = dict(manifest)
    new_manifest["deferrals"] = surviving
    new_manifest["generated_at"] = manifest.get("generated_at", filed_at)
    new_manifest["filed_at"] = filed_at

    if args.dry_run:
        sys.stderr.write(
            f"[dry-run] would rewrite manifest with {len(surviving)} entries, "
            f"dropping {len(failed_groups)} failed group(s)\n"
        )
    else:
        _write_manifest_atomic(manifest_path, new_manifest)

    for n in succeeded_numbers:
        print(n)

    if failed_groups:
        sys.stderr.write(
            f"file-deferrals.py: {len(failed_groups)} group(s) failed and "
            f"were dropped from manifest: {', '.join(failed_groups)}\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
