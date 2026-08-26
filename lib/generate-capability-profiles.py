#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Compile lib/capability-profiles.json into the runner allowlist literals and the
matcher-probe baselines.

This is PRFlow-internal build tooling. The manifest is the single source of truth
for the cloud capability policy; this generator flattens each profile to an ordered
token list and rewrites the generated allowlist regions across the workflow files,
each carrying a banner comment with the manifest version and a per-region sha256.

Usage:
    python3 lib/generate-capability-profiles.py            # rewrite the regions
    python3 lib/generate-capability-profiles.py --check     # verify, write nothing

`--check` exits 0 with empty stdout when every generated region matches the manifest,
and non-zero (printing a per-region, token-level directional diff to stderr) on drift.
The generator reads no git history and imports no third-party module (stdlib only) —
it mirrors the desk-time-guard pattern of lib/test/extract-command-heads.py.

Failure discipline: every defect (a malformed manifest, a missing/duplicated anchor,
a review list that drifts from the lock, ...) exits non-zero with a stderr breadcrumb
naming the defect, and leaves every target file byte-unchanged.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "lib" / "capability-profiles.json"
LOCK_PATH = REPO_ROOT / "lib" / "review-profile.tokens"

WF = REPO_ROOT / ".github" / "workflows"

REVIEW_LEADING = ["Read", "Glob", "Grep"]

BANNER_PREFIX = "# devflow-capability-manifest:"
_BANNER_RE_TMPL = (
    r"# devflow-capability-manifest: region={rid} "
    r"manifest_version=(?P<ver>\d+) sha256=(?P<sha>[0-9a-f]{{64}})"
)


class GenError(Exception):
    """A fail-closed generator defect; the message is the stderr breadcrumb."""


def read_wf(path):
    # newline="" disables universal-newline translation so a CRLF (or lone CR) in a
    # region survives to _check_no_crlf instead of being silently collapsed to LF.
    # A present-but-unreadable target (permission bit, or a directory in its place after
    # a bad checkout) must fail closed with a named breadcrumb, not an uncaught OSError
    # traceback — the same discipline load_manifest/load_lock already apply.
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            return fh.read()
    except OSError as exc:
        die(f"target workflow unreadable: {path}: {exc}")


def write_wf(path, text):
    # newline="" leaves the LF bytes we emit exactly as authored (no os.linesep
    # translation), so generation is deterministic across platforms. An unwritable target
    # fails closed with a named breadcrumb rather than a traceback.
    try:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    except OSError as exc:
        die(f"target workflow unwritable: {path}: {exc}")


def die(msg):
    raise GenError(msg)


# ---------------------------------------------------------------------------
# Manifest loading + validation + resolution
# ---------------------------------------------------------------------------
def load_manifest():
    if not MANIFEST_PATH.exists():
        die(f"manifest absent: {MANIFEST_PATH} does not exist")
    try:
        raw = MANIFEST_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        die(f"manifest unreadable: {MANIFEST_PATH}: {exc}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        die(f"manifest malformed JSON: {MANIFEST_PATH}: {exc}")
    if not isinstance(data, dict):
        die(
            "manifest top-level must be a JSON object, got "
            f"{type(data).__name__}"
        )

    ver = data.get("manifest_version")
    if ver is None:
        die("manifest: 'manifest_version' is missing")
    if isinstance(ver, bool) or not isinstance(ver, int):
        die(
            "manifest: 'manifest_version' must be an integer, got "
            f"{type(ver).__name__} ({ver!r})"
        )

    groups = data.get("groups")
    if not isinstance(groups, dict):
        die(
            "manifest: 'groups' must be a JSON object, got "
            f"{type(groups).__name__}"
        )
    for gname, gtoks in groups.items():
        if not isinstance(gtoks, list):
            die(
                f"manifest: group {gname!r} must be a list of token strings, got "
                f"{type(gtoks).__name__} ({gtoks!r})"
            )
        for t in gtoks:
            if not isinstance(t, str):
                die(f"manifest: group {gname!r} contains a non-string token {t!r}")

    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        die(
            "manifest: 'profiles' must be a JSON object, got "
            f"{type(profiles).__name__}"
        )
    expected = {"review", "implement", "command"}
    if set(profiles.keys()) != expected:
        die(
            "manifest: 'profiles' must contain exactly review/implement/command, got "
            f"{sorted(profiles.keys())}"
        )

    resolved = {name: resolve_profile(name, profiles[name], groups) for name in expected}
    return ver, resolved


def resolve_profile(name, spec, groups):
    if not isinstance(spec, list):
        die(f"manifest: profile {name!r} must be a list, got {type(spec).__name__}")
    tokens = []
    for entry in spec:
        if not isinstance(entry, str):
            die(f"manifest: profile {name!r} contains a non-string entry {entry!r}")
        if entry.startswith("@"):
            gname = entry[1:]
            if gname not in groups:
                die(
                    f"manifest: profile {name!r} references unknown group @{gname}"
                )
            tokens.extend(groups[gname])
        else:
            tokens.append(entry)
    if not tokens:
        die(f"manifest: profile {name!r} resolves to an empty token list")
    seen = set()
    dups = []
    for t in tokens:
        if t in seen and t not in dups:
            dups.append(t)
        seen.add(t)
    if dups:
        die(
            f"manifest: profile {name!r} has duplicate resolved token(s): "
            + ", ".join(dups)
        )
    return tokens


def load_lock():
    if not LOCK_PATH.exists():
        die(
            f"reviewer security boundary lock absent: {LOCK_PATH} does not exist "
            "(the review profile's resolved token list, one per line)"
        )
    try:
        text = LOCK_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        die(f"reviewer security boundary lock unreadable: {LOCK_PATH}: {exc}")
    return [ln for ln in text.split("\n") if ln != ""]


def check_review_boundary(review_tokens):
    if review_tokens[:3] != REVIEW_LEADING:
        die(
            "review profile leading-token contract violated: first three resolved "
            f"tokens are {review_tokens[:3]} but must be {REVIEW_LEADING} "
            "(lib/test/run.sh prefix-anchored selectors depend on TOOLS='Read,Glob,Grep)"
        )
    lock = load_lock()
    if review_tokens != lock:
        extra = [t for t in review_tokens if t not in lock]
        missing = [t for t in lock if t not in review_tokens]
        lines = [
            "review profile drift from the reviewer security boundary lock "
            f"({LOCK_PATH}):",
        ]
        if extra:
            lines.append(
                "  resolved-review tokens NOT in the lock (would WIDEN the reviewer): "
                + ", ".join(extra)
            )
        if missing:
            lines.append(
                "  lock tokens NOT in resolved-review (would NARROW the reviewer): "
                + ", ".join(missing)
            )
        lines.append(
            "  remedy: widening the read-only reviewer requires a deliberate, visible "
            "diff to lib/review-profile.tokens in the same PR — update the lock to the "
            "resolved list only if the change is intended."
        )
        die("\n".join(lines))


# ---------------------------------------------------------------------------
# Region rendering
# ---------------------------------------------------------------------------
def region_sha(tokens):
    return hashlib.sha256("\n".join(tokens).encode("utf-8")).hexdigest()


def banner_text(rid, version, tokens):
    return (
        f"{BANNER_PREFIX} region={rid} "
        f"manifest_version={version} sha256={region_sha(tokens)}"
    )


def serialize(tokens, style):
    if style == "comma":
        return ",".join(tokens)
    if style == "comma_space":
        return ", ".join(tokens)
    die(f"internal: unknown serialization style {style!r}")


# Each region: id, file, profile, kind, and the anchor variable (for assign kind).
REGIONS = [
    {
        "id": "runner-review",
        "file": WF / "devflow-runner.yml",
        "profile": "review",
        "kind": "assign",
        "var": "TOOLS",
        "style": "comma",
    },
    {
        "id": "command",
        "file": WF / "devflow.yml",
        "profile": "command",
        "kind": "assign",
        "var": "TOOLS",
        "style": "comma_space",
    },
    {
        # Hoisted from the `claude_args` inline `--allowed-tools` literal into a
        # `Resolve allowed-tools` step output (issue #1170), so the implement tier's
        # grounding block can quote the exact resolved list by construction — the same
        # single-source shape the `command`/`runner-review` regions already use. The
        # step appends `allowed_tools_extra` in shell (`${TOOLS}${EXTRA}`) and both the
        # `claude_args` `--allowed-tools` and the grounding block consume that one output.
        "id": "implement",
        "file": WF / "devflow-implement.yml",
        "profile": "implement",
        "kind": "assign",
        "var": "TOOLS",
        "style": "comma_space",
    },
    {
        "id": "probe-review",
        "file": WF / "matcher-probe.yml",
        "profile": "review",
        "kind": "assign",
        "var": "REVIEW",
        "style": "comma",
    },
    {
        "id": "probe-implement",
        "file": WF / "matcher-probe.yml",
        "profile": "implement",
        "kind": "assign",
        "var": "IMPLEMENT",
        "style": "comma",
    },
    {
        # issue #1152: the command-probe job's allowlist baseline, compiled from the
        # existing `command` profile so it measures the tier that actually ships
        # (devflow.yml's TOOLS is the same profile) and can never drift from it.
        "id": "probe-command",
        "file": WF / "matcher-probe.yml",
        "profile": "command",
        "kind": "assign",
        "var": "COMMAND",
        "style": "comma",
    },
]


# The `VAR='…'` assignment anchor and the `--allowed-tools`-then-quote marker are the
# single source of each region's uniqueness contract. Defining them once and sharing them
# across the write path (process_*) and the verification path (do_check) keeps the two
# from drifting — a duplicate anchor must be refused identically on both.
def _assign_anchor_re(var):
    # Locates the CANONICAL region assignment for replacement positioning: a
    # single-quoted assignment that BEGINS a line (after indent). The generated banner +
    # assignment are spliced at this match, so it must stay line-anchored.
    return re.compile(r"^([ \t]*)" + re.escape(var) + r"='[^']*'", re.M)


def _count_replacement_assignments(text, var):
    # Count statement-position value-REPLACEMENT assignments to `var` on non-comment lines
    # — the duplicate/injection guard. bash's last-assignment-wins means the LAST
    # statement-position assignment word is what the reviewer runs with, and a
    # statement-position assignment wins REGARDLESS of how it is separated (whitespace, ;,
    # &, &&, ||, |, newline — a simple command accepts several assignment words, and with
    # no command word they persist in the current shell) and REGARDLESS of quote style. So
    # a separator- or quote-scoped count fails open on the vectors it does not enumerate.
    # Instead count every `var=` in assignment-word position (`var=` not preceded by a word
    # char, so RUNNER_TOOLS= is not a TOOLS= match), and EXCLUDE only a self-referencing
    # derivation (`var=$var…` / `var="$var…"` / `var="${var}…"`) — the one legitimate such
    # shape is devflow-runner.yml's `TOOLS="$TOOLS,$FILTERED"` provisioning append, which
    # derives from (does not replace) the canonical value. Comment lines are stripped so a
    # `# … var='…'` mention is never counted. On the canonical tree every region has
    # exactly one replacement (its single-quoted generated literal); any injected second
    # assignment — however separated, single- or double-quoted — makes it > 1 and is
    # refused, so an injected widening cannot pass --check while winning at runtime.
    noncomment = "\n".join(
        ln for ln in text.split("\n") if not re.match(r"^[ \t]*#", ln)
    )
    self_deriv = re.compile(r'"?\$\{?' + re.escape(var) + r"\b")
    count = 0
    for m in re.finditer(r"(?<![\w])" + re.escape(var) + r"=", noncomment):
        if self_deriv.match(noncomment[m.end():]):
            continue  # a derivation of the existing value, not a replacement
        count += 1
    return count


def _strip_banner_line(text, span):
    """Remove the banner line covering `span`, including its trailing newline."""
    b0, b1 = span
    nl = text.find("\n", b1)
    return text[:b0] + text[b1 if nl == -1 else nl + 1:]


def _check_no_crlf(segment, rid):
    if "\r" in segment:
        die(
            f"region {rid}: CRLF line ending found inside the generated region "
            "(a CRLF checkout must surface as an error, never a whole-file rewrite); "
            "normalize to LF"
        )


def _existing_banner(text, indent, rid):
    """Find an existing banner line for `rid`. Returns (span_or_None). Raises on a
    line that carries the banner prefix + this region but is malformed."""
    valid_re = re.compile(
        r"^" + re.escape(indent) + _BANNER_RE_TMPL.format(rid=re.escape(rid)) + r"$",
        re.M,
    )
    m = valid_re.search(text)
    if m:
        return m.span()
    # Prefix present for this region but not a valid banner → malformed.
    malformed_re = re.compile(
        r"^[ \t]*" + re.escape(BANNER_PREFIX) + r" region=" + re.escape(rid) + r"\b.*$",
        re.M,
    )
    if malformed_re.search(text):
        die(
            f"region {rid}: a banner line for this region is present but malformed "
            "(expected: manifest_version=<int> sha256=<64 hex>)"
        )
    return None


def process_assign(text, region, tokens, version):
    rid = region["id"]
    var = region["var"]
    anchor_re = _assign_anchor_re(var)
    # Duplicate/injection refusal counts every statement-position value-REPLACEMENT
    # assignment (any separator, any quote style; the legitimate self-referencing append
    # is excluded), so an injected second assignment — which wins at bash runtime however
    # it is separated or quoted — cannot slip past. Positioning still uses the line-leading
    # canonical single-quote match below.
    ndup = _count_replacement_assignments(text, var)
    matches = list(anchor_re.finditer(text))
    if not matches:
        die(f"region {rid}: anchor {var}=' not found in {region['file'].name}")
    if ndup > 1:
        die(
            f"region {rid}: anchor {var}= is duplicated "
            f"({ndup} replacement assignments, incl. any whitespace/;/&/&&/||-separated "
            f"or double-quoted second assignment) in {region['file'].name} — "
            "refusing to guess"
        )
    m = matches[0]
    indent = m.group(1)
    line_start = m.start()
    line_end = m.end()
    _check_no_crlf(text[line_start:line_end], rid)

    banner = indent + banner_text(rid, version, tokens)
    new_assign = indent + var + "='" + serialize(tokens, region["style"]) + "'"

    # Remove any existing (valid) banner for this region, then re-insert above anchor.
    ban_span = _existing_banner(text, indent, rid)
    new_lines = banner + "\n" + new_assign
    if ban_span is not None:
        # Splice any existing banner out (it may sit anywhere in the file), then
        # re-locate the anchor before inserting the fresh banner + assignment.
        without = _strip_banner_line(text, ban_span)
        m2 = anchor_re.search(without)
        a0, a1 = m2.start(), m2.end()
        return without[:a0] + new_lines + without[a1:]
    return text[:line_start] + new_lines + text[line_end:]


def parse_assign_tokens(text, region):
    var = region["var"]
    m = re.search(r"^[ \t]*" + re.escape(var) + r"='([^']*)'", text, re.M)
    if not m:
        return None
    body = m.group(1)
    if region["style"] == "comma_space":
        return [t.strip() for t in body.split(",")]
    return body.split(",")


def parse_banner(text, rid):
    valid_re = re.compile(
        r"^[ \t]*" + _BANNER_RE_TMPL.format(rid=re.escape(rid)) + r"$", re.M
    )
    m = valid_re.search(text)
    if not m:
        return None
    return int(m.group("ver")), m.group("sha")


# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------
def compute_new_texts(version, resolved):
    """Return {file_path: new_text} for every target file (grouping regions by file)."""
    originals = {}
    for region in REGIONS:
        fp = region["file"]
        if fp not in originals:
            if not fp.exists():
                die(f"target workflow file absent: {fp}")
            originals[fp] = read_wf(fp)
    new = dict(originals)
    for region in REGIONS:
        fp = region["file"]
        tokens = resolved[region["profile"]]
        new[fp] = process_assign(new[fp], region, tokens, version)
    return originals, new


def do_generate(version, resolved):
    originals, new = compute_new_texts(version, resolved)
    written = []
    for fp, text in new.items():
        if text != originals[fp]:
            write_wf(fp, text)
            written.append(fp)
    for fp in written:
        print(f"regenerated {fp.relative_to(REPO_ROOT)}")
    if not written:
        print("all generated regions already up to date")
    return 0


def do_check(version, resolved):
    drift = []
    for region in REGIONS:
        fp = region["file"]
        if not fp.exists():
            die(f"target workflow file absent: {fp}")
        text = read_wf(fp)
        tokens = resolved[region["profile"]]
        expected_sha = region_sha(tokens)
        rid = region["id"]

        # Mirror generate's fail-closed duplicate-anchor refusal on the verification
        # side. A second injected `VAR='…widened…'` assignment (or `--allowed-tools`
        # marker) WINS at bash runtime — the last assignment in the step is what the
        # reviewer actually runs with — while a first-match parse here would inspect only
        # the still-canonical leading copy and pass clean. Refuse to verify an ambiguous
        # region exactly as generate refuses to write one, so an injected duplicate cannot
        # silently widen the reviewer boundary past the --check gate.
        ndup = _count_replacement_assignments(text, region["var"])
        if ndup > 1:
            die(
                f"region {rid}: anchor is duplicated ({ndup} matches) in {fp.name} during "
                "--check — refusing to verify against an ambiguous region (a later "
                "duplicate assignment would win at bash runtime)"
            )

        found_tokens = parse_assign_tokens(text, region)
        found_banner = parse_banner(text, rid)

        if found_tokens is None:
            die(
                f"region {rid}: could not locate the generated region in "
                f"{fp.name} during --check (anchor absent or unparseable)"
            )

        found_sha = found_banner[1] if found_banner else None
        found_ver = found_banner[0] if found_banner else None
        if found_tokens == tokens and found_sha == expected_sha and found_ver == version:
            continue

        lines = [
            f"DRIFT region={rid} file={fp.relative_to(REPO_ROOT)}",
            f"  expected sha256={expected_sha} manifest_version={version}",
            f"  found    sha256={found_sha} manifest_version={found_ver}",
        ]
        workflow_side = [t for t in found_tokens if t not in tokens]
        compiled_side = [t for t in tokens if t not in found_tokens]
        if workflow_side:
            lines.append(
                "  tokens in the workflow region but NOT in the manifest-compiled list: "
                + ", ".join(workflow_side)
            )
            lines.append(
                "    remedy: if intended policy, add it to lib/capability-profiles.json "
                "and regenerate (blind regeneration would silently REVERT this grant)"
            )
        if compiled_side:
            lines.append(
                "  tokens in the manifest-compiled list but NOT in the workflow region: "
                + ", ".join(compiled_side)
            )
            lines.append(
                "    remedy: run `python3 lib/generate-capability-profiles.py` to "
                "regenerate"
            )
        if not workflow_side and not compiled_side:
            lines.append(
                "    remedy: token lists match but the banner is stale — regenerate"
            )
        drift.append("\n".join(lines))

    if drift:
        die("\n".join(drift))
    return 0


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv):
    _force_utf8_streams()
    check = False
    for a in argv[1:]:
        if a == "--check":
            check = True
        else:
            print(f"unknown argument: {a}", file=sys.stderr)
            return 2
    try:
        version, resolved = load_manifest()
        check_review_boundary(resolved["review"])
        if check:
            return do_check(version, resolved)
        return do_generate(version, resolved)
    except GenError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
