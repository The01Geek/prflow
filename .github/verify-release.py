#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Verify a PRFlow public release candidate directory.

This file is the CANONICAL verifier. The exporter copies these exact bytes to the
public tree as `.github/verify-release.py`, and a byte-equality check makes that
public copy a deterministic projection rather than a second implementation. It is
therefore self-contained: it imports nothing from `tools/carry-on/`, because the
public copy ships without that directory.

Two modes:

  --manifest PATH   full verification, including that the candidate's emitted set
                    equals the positive manifest exactly. Private-side only, since
                    `distribution/` is not exported.
  (omitted)         artifact-only verification: everything checkable from the
                    candidate bytes alone. This is what the public
                    distribution-verify workflow runs.

It NEVER imports, sources or executes anything from the candidate. The candidate
is data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

# The BYTE budget is the load-bearing guard: the two payloads that would matter if
# they ever leaked in are lib/test (~14.8 MB) and .prflow/learnings (~7.5 MB), and
# either blows this ceiling on its own. The file budget catches accidental
# structural inclusion; it is set with headroom so ordinary documentation
# authoring cannot trip it, because a budget that fires on intended growth trains
# the reader to raise it without looking.
MAX_FILES = 600
MAX_BYTES = 12 * 1024 * 1024

DIGEST_MANIFEST = ".release/files.sha256"
SOURCE_JSON = ".release/source.json"

# Every member here must exist in a valid candidate. The seven directory members
# are the root-member set that EVERY historical vendor-slice.sh generation
# expects (measured across all 479 public tags): an old installed consumer action
# does `cp -R` over them and aborts before its own prune if one is missing.
REQUIRED_FILES = (
    ".claude-plugin/plugin.json",
    ".claude-plugin/marketplace.json",
    "install.sh",
    "README.md",
    "LICENSE",
    "docs/README.md",
    SOURCE_JSON,
    DIGEST_MANIFEST,
)
REQUIRED_DIRS = (
    ".claude-plugin", "agents", "docs", "lib", "scripts", "skills", "LICENSES",
)

FORBIDDEN_EXACT = frozenset({
    "CLAUDE.md", "AGENTS.md", "GEMINI.md", "CHANGELOG.md",
    "requirements.txt", "ruff.toml",
    ".prflow/config.json",
    ".github/actionlint.yaml",
})
FORBIDDEN_PREFIXES = (
    ".git/", ".claude/", ".codex/", ".changeset/",
    "lib/test/", "docs/internal/", "docs/site/",
    ".prflow/learnings/", ".prflow/logs/",
    ".prflow/skill-extensions/", ".prflow/prompt-extensions/",
)
# Development workflows that must never reach the distribution repo. The two
# consumer workflows (devflow.yml, devflow-implement.yml) are distribution assets
# and are deliberately absent from this list.
FORBIDDEN_WORKFLOWS = frozenset({
    "ci.yml", "matcher-probe.yml", "version-consolidate.yml",
    "mintlify-check.yml", "agents-seam-probe.yml",
    "devflow-runner.yml", "telemetry-push.yml", "devflow-review.yml",
    "internal-larger-runner-canary.yml", "rotate-claude-token.yml",
})

# Windows reserved device names: a checkout carrying one of these cannot be
# created on Windows at all, so it must fail here rather than at a user's clone.
WIN_RESERVED = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)
WIN_BAD_CHARS = set('<>:"|?*\\')

# Home-path segments that are obviously instructional stand-ins rather than a real
# account. Documentation legitimately writes an example home path; a
# specific-looking name is what indicates a leaked local path.
PLACEHOLDER_USERS = frozenset({
    "you", "your-name", "yourname", "user", "username", "me", "example",
})
LEAK_PATTERNS = (
    (re.compile(r"/Users/(?!(?:" + "|".join(sorted(PLACEHOLDER_USERS))
                + r")/)[A-Za-z0-9._-]+/"), "maintainer home path"),
    # A PEM header LITERAL is ordinary key-parsing source. Only a header followed
    # by an actual base64 body is a key, so require the body.
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----\s*\n[A-Za-z0-9+/=]{40,}"),
     "private key block"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"), "GitHub token"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9-]{16,}"), "Anthropic API key"),
    # Assembled from fragments for the same reason the allowlist keys are: spelling
    # the private repository as one literal publishes the very name this pattern
    # exists to keep out of the release.
    (re.compile(r"\b" + "Radman" + "-LLC/prflow" + "-dev" + r"\b"),
     "private repository reference"),
)

# Reviewed, benign matches. Each entry is (path, matched text, reason) and
# suppresses ONLY that exact pair, so a new occurrence anywhere still fails the
# release. Never add an entry without reading the line it excuses.
# Keys are assembled from fragments on purpose: spelling an excused match as one
# literal would make this file match its own pattern and fail every release.
LEAK_ALLOWLIST = {
    ("scripts/issue-audit-state.py", "/User" + "s/jo/"):
        "illustrative example of a path containing a space, in comments about "
        "shell quoting; that name is not a maintainer account",
}
# Binary and large-corpus members are scanned by extension allowlist only; a
# false positive inside a .png would block a release for no reason.
# .svg is TEXT and can carry arbitrary content, so it must be leak-scanned; a
# prior audit found it skipped entirely because it was absent from this set.
TEXT_SUFFIXES = frozenset({
    ".md", ".mdx", ".py", ".sh", ".yml", ".yaml", ".json", ".jq", ".txt",
    ".cff", ".css", ".svg", ".gitattributes", ".gitignore", "",
})


class Failure(Exception):
    pass


def _walk(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if not p.is_dir())


def _rel(root: Path, p: Path) -> str:
    return p.relative_to(root).as_posix()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_structure(root: Path, paths: list[Path], errors: list[str]) -> None:
    rels = {_rel(root, p) for p in paths}

    for member in REQUIRED_FILES:
        if member not in rels:
            errors.append(f"missing required file: {member}")
    for member in REQUIRED_DIRS:
        if not any(r == member or r.startswith(member + "/") for r in rels):
            errors.append(f"missing required root member: {member}/")

    for rel in sorted(rels):
        if rel in FORBIDDEN_EXACT:
            errors.append(f"forbidden path present: {rel}")
        for prefix in FORBIDDEN_PREFIXES:
            if rel.startswith(prefix):
                errors.append(f"forbidden path present: {rel}")
        if rel.endswith(".private.md"):
            errors.append(f"private planning document present: {rel}")
        if rel.startswith(".github/workflows/"):
            name = rel.rsplit("/", 1)[-1]
            if name in FORBIDDEN_WORKFLOWS:
                errors.append(f"development workflow present: {rel}")

    # Symlinks: the first-release policy is zero, because a symlink's Windows
    # checkout behavior is untested and a dangling one silently changes payload.
    for p in paths:
        if p.is_symlink():
            errors.append(f"symlink present (policy is zero): {_rel(root, p)}")

    lowered: dict[str, str] = {}
    for rel in sorted(rels):
        for segment in rel.split("/"):
            stem = segment.split(".", 1)[0].upper()
            if stem in WIN_RESERVED:
                errors.append(f"Windows reserved name: {rel}")
            if WIN_BAD_CHARS & set(segment):
                errors.append(f"Windows-invalid character in path: {rel}")
            if segment.endswith((" ", ".")):
                errors.append(f"Windows-invalid trailing space/dot: {rel}")
        key = rel.lower()
        if key in lowered and lowered[key] != rel:
            errors.append(f"case collision: {rel} vs {lowered[key]}")
        lowered[key] = rel


def check_budget(root: Path, paths: list[Path], errors: list[str]) -> tuple[int, int]:
    total = sum(p.stat().st_size for p in paths)
    if len(paths) > MAX_FILES:
        errors.append(f"file count {len(paths)} exceeds budget {MAX_FILES}")
    if total > MAX_BYTES:
        errors.append(f"byte count {total} exceeds budget {MAX_BYTES}")
    return len(paths), total


def check_modes_and_endings(root: Path, paths: list[Path],
                            errors: list[str]) -> None:
    """Modes must be exactly 0644 or 0755, and text must be LF.

    An odd mode (group-writable, setuid) reaching a consumer checkout is a
    packaging defect that git will faithfully preserve, so reject it here.
    """
    for p in paths:
        rel = _rel(root, p)
        perm = p.stat().st_mode & 0o777
        if perm not in (0o644, 0o755):
            errors.append(f"unexpected mode {perm:04o}: {rel}")
        if rel == "install.sh" and not perm & 0o111:
            errors.append("install.sh is not executable")
        if p.suffix and p.suffix in TEXT_SUFFIXES:
            try:
                data = p.read_bytes()
            except OSError as exc:
                errors.append(f"unreadable: {rel}: {exc}")
                continue
            if b"\r\n" in data:
                errors.append(f"CRLF line endings: {rel}")


def check_leaks(root: Path, paths: list[Path], errors: list[str]) -> None:
    for p in paths:
        rel = _rel(root, p)
        if p.suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern, label in LEAK_PATTERNS:
            for match in pattern.finditer(text):
                found = match.group(0)
                if (rel, found) in LEAK_ALLOWLIST:
                    continue
                errors.append(f"{label} in {rel}: {found[:40]!r}")
                break


MD_LINK = re.compile(r"\]\(\s*([^)\s#]+)")

# Files under this prefix are Mintlify docs-site source, where a leading-slash
# link is a site route rather than a path in the tree.
DOCS_SITE_PREFIX = "docs/external/"


def check_links(root: Path, paths: list[Path], errors: list[str]) -> None:
    """Every relative markdown link and image must resolve inside the candidate.

    A release that ships a link into an excluded internal path renders as a 404
    for the reader the projection exists to serve.
    """
    present = {_rel(root, p) for p in paths}
    for p in paths:
        if p.suffix not in (".md", ".mdx"):
            continue
        rel = _rel(root, p)
        base = rel.rsplit("/", 1)[0] if "/" in rel else ""
        for raw in MD_LINK.findall(p.read_text(encoding="utf-8", errors="ignore")):
            target = raw.strip()
            if not target or ":" in target.split("/")[0] or target.startswith(("#", "<")):
                continue
            # Skill prose carries link-shaped RUNTIME TEMPLATES the agent
            # substitutes ($GITHUB_RUN_ID, {RUN_URL}, an elided path). Treating
            # one as a broken link would fail every release for correct prose.
            if any(ch in target for ch in "${}…"):
                continue
            if target.startswith("/"):
                # Inside the docs-site subtree a leading slash is a SITE route
                # (prflow.ai/docs/...), not a filesystem path. Outside it, an
                # absolute local link is a genuine authoring mistake.
                if rel.startswith(DOCS_SITE_PREFIX):
                    continue
                errors.append(f"{rel}: absolute local link {target}")
                continue
            joined = f"{base}/{target}" if base else target
            parts: list[str] = []
            for seg in joined.split("/"):
                if seg in ("", "."):
                    continue
                if seg == "..":
                    if parts:
                        parts.pop()
                    continue
                parts.append(seg)
            resolved = "/".join(parts)
            if resolved in present:
                continue
            if any(x == resolved or x.startswith(resolved + "/") for x in present):
                continue
            errors.append(f"{rel}: broken local link -> {target}")


DOCS_NAV = "docs/external/docs.json"


def check_docs_nav(root: Path, paths: list[Path], errors: list[str]) -> None:
    """Every page the docs-site navigation names must exist in the candidate.

    The navigation manifest is JSON, so `check_links` — which reads markdown link
    syntax — never sees it. A nav entry pointing at a page the export dropped
    publishes a broken docs site, and the release IS the docs deploy.
    """
    nav = root / DOCS_NAV
    if not nav.is_file():
        return
    try:
        data = json.loads(nav.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{DOCS_NAV} is unreadable or invalid JSON: {exc}")
        return

    def walk(node):
        if isinstance(node, str):
            yield node
        elif isinstance(node, dict):
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)

    present = {_rel(root, p) for p in paths}
    base = DOCS_NAV.rsplit("/", 1)[0]
    for entry in walk(data.get("navigation")):
        if not entry or ":" in entry or entry.startswith(("#", "/")):
            continue
        # Group labels share the string space with page paths, so only an entry
        # that looks like a path is treated as one; otherwise every heading in
        # the navigation would be reported missing.
        candidates = [f"{base}/{entry}{ext}" for ext in (".md", ".mdx", "")]
        if "/" in entry and not any(c in present for c in candidates):
            errors.append(f"{DOCS_NAV}: navigation names a missing page: {entry}")


def check_digests(root: Path, paths: list[Path], errors: list[str]) -> str | None:
    manifest = root / DIGEST_MANIFEST
    if not manifest.is_file():
        errors.append(f"missing {DIGEST_MANIFEST}")
        return None
    recorded: dict[str, str] = {}
    for lineno, line in enumerate(
            manifest.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        digest, _, rel = line.partition("  ")
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or not rel:
            errors.append(f"{DIGEST_MANIFEST} line {lineno}: malformed")
            continue
        recorded[rel] = digest

    actual = {
        _rel(root, p): sha256_file(p)
        for p in paths if _rel(root, p) != DIGEST_MANIFEST
    }
    for rel in sorted(set(recorded) - set(actual)):
        errors.append(f"{DIGEST_MANIFEST} lists a file not present: {rel}")
    for rel in sorted(set(actual) - set(recorded)):
        errors.append(f"file not covered by {DIGEST_MANIFEST}: {rel}")
    for rel in sorted(set(recorded) & set(actual)):
        if recorded[rel] != actual[rel]:
            errors.append(f"digest mismatch: {rel}")
    return hashlib.sha256(manifest.read_bytes()).hexdigest()


def check_source_json(root: Path, count: int, total: int,
                      errors: list[str]) -> None:
    path = root / SOURCE_JSON
    if not path.is_file():
        errors.append(f"missing {SOURCE_JSON}")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{SOURCE_JSON} unreadable: {exc}")
        return
    for field in ("schema_version", "plugin_version", "source_commit",
                  "source_commit_time", "exporter_policy_version",
                  "payload_file_count", "payload_byte_count"):
        if field not in data:
            errors.append(f"{SOURCE_JSON} missing field: {field}")
    sha = str(data.get("source_commit", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        errors.append(f"{SOURCE_JSON} source_commit is not a full 40-hex SHA")
    # Counts exclude .release/ so the byte total is not self-referential.
    release_files = [p for p in _walk(root) if _rel(root, p).startswith(".release/")]
    expect_count = count - len(release_files)
    expect_bytes = total - sum(p.stat().st_size for p in release_files)
    if data.get("payload_file_count") != expect_count:
        errors.append(
            f"{SOURCE_JSON} payload_file_count "
            f"{data.get('payload_file_count')} != {expect_count}")
    if data.get("payload_byte_count") != expect_bytes:
        errors.append(
            f"{SOURCE_JSON} payload_byte_count "
            f"{data.get('payload_byte_count')} != {expect_bytes}")
    for banned in ("build_time", "local_path", "token", "private_remote"):
        if banned in data:
            errors.append(f"{SOURCE_JSON} carries banned field: {banned}")


def check_manifest(root: Path, paths: list[Path], manifest_path: Path,
                   errors: list[str]) -> None:
    declared: set[str] = set()
    text = manifest_path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        _category, _, rel = line.partition("\t")
        if not rel:
            errors.append(f"manifest line {lineno}: no tab separator")
            continue
        if rel in declared:
            errors.append(f"manifest line {lineno}: duplicate path {rel}")
        declared.add(rel)
    emitted = {_rel(root, p) for p in paths}
    for rel in sorted(emitted - declared):
        errors.append(f"emitted path is unclassified in the manifest: {rel}")
    for rel in sorted(declared - emitted):
        errors.append(f"manifest declares a path the candidate lacks: {rel}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate", required=True,
                    help="path to the candidate release directory")
    ap.add_argument("--manifest",
                    help="distribution/public-release-paths.txt (private side)")
    ap.add_argument("--expect-digest",
                    help="fail unless ARTIFACT_DIGEST equals this value")
    args = ap.parse_args()

    root = Path(args.candidate).resolve()
    if not root.is_dir():
        print(f"FAIL: candidate is not a directory: {root}", file=sys.stderr)
        return 2
    if (root / ".git").exists():
        print("FAIL: candidate contains .git", file=sys.stderr)
        return 2

    paths = _walk(root)
    errors: list[str] = []
    check_structure(root, paths, errors)
    count, total = check_budget(root, paths, errors)
    check_modes_and_endings(root, paths, errors)
    check_leaks(root, paths, errors)
    check_links(root, paths, errors)
    check_docs_nav(root, paths, errors)
    digest = check_digests(root, paths, errors)
    check_source_json(root, count, total, errors)
    if args.manifest:
        check_manifest(root, paths, Path(args.manifest), errors)
    if args.expect_digest and digest and digest != args.expect_digest:
        errors.append(
            f"ARTIFACT_DIGEST {digest} != expected {args.expect_digest}")

    print(f"candidate: {root}")
    print(f"files: {count}  bytes: {total} ({total / 1048576:.2f} MiB)")
    print(f"ARTIFACT_DIGEST: {digest}")
    print(f"mode: {'manifest+artifact' if args.manifest else 'artifact-only'}")
    if errors:
        print(f"\nFAILED with {len(errors)} error(s):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print("\nOK: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
