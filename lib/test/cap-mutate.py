#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Test-support mutator for the capability-profile generator suite checks (issue #561).

Applies one NAMED, deterministic defect to a fixture tree (a copy of the repo's lib/
manifest+lock+generator and .github/workflows/*.yml) so lib/test/run.sh can drive the
real generator against the corrupted fixture and observe it fail closed. Centralizing
the fiddly edits here keeps run.sh readable and each mutation itself testable.

Usage: cap-mutate.py <root> <mutation-name> [arg]

Exits 0 on a successful mutation, non-zero (stderr breadcrumb) on an unknown mutation
or a target it cannot locate — so a broken mutation is never a silent no-op that would
green a planted-defect control vacuously.
"""

import json
import re
import sys
from pathlib import Path

WF = "devflow-runner.yml", "devflow.yml", "devflow-implement.yml", "matcher-probe.yml"


def die(msg):
    print(f"cap-mutate: {msg}", file=sys.stderr)
    sys.exit(1)


def wf(root, name):
    return Path(root) / ".github" / "workflows" / name


def manifest_path(root):
    return Path(root) / "lib" / "capability-profiles.json"


def lock_path(root):
    return Path(root) / "lib" / "review-profile.tokens"


def load_manifest(root):
    return json.loads(manifest_path(root).read_text(encoding="utf-8"))


def dump_manifest(root, data):
    manifest_path(root).write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def edit_wf(root, name, transform, *, expect_change=True):
    p = wf(root, name)
    text = p.read_text(encoding="utf-8")
    new = transform(text)
    if expect_change and new == text:
        die(f"mutation left {name} unchanged (target not found)")
    p.write_text(new, encoding="utf-8")


def del_token(root, name, token):
    """Remove one token plus its trailing separator (comma, optional space, optional
    newline+indent) — works across the comma, comma-space, and one-per-line styles."""
    pat = re.compile(re.escape(token) + r",[ \t]*(?:\n[ \t]*)?")

    def t(text):
        return pat.sub("", text, count=1)

    edit_wf(root, name, t)


# Both banner mutators anchor on the CAPABILITY banner prefix, not on a bare
# `sha256=`: a workflow can carry more than one generated-region banner family
# (lib/generate-plugin-identity.py stamps its own), and an unanchored match would
# corrupt the wrong family's banner — leaving the capability generator perfectly
# happy and the planted-defect control silently vacuous.
CAP_BANNER = r"# devflow-capability-manifest:[^\n]*?"


def flip_banner_hex(root, name):
    def t(text):
        m = re.search(CAP_BANNER + r"(sha256=)([0-9a-f])([0-9a-f]{63})", text)
        if not m:
            return text
        flipped = "0" if m.group(2) != "0" else "1"
        return text[: m.start(2)] + flipped + text[m.end(2) :]

    edit_wf(root, name, t)


def truncate_banner_hex(root, name):
    # Drop one hex digit → 63-char sha, so the line keeps the banner prefix+region
    # but is no longer a valid banner (malformed).
    def t(text):
        return re.sub(
            r"(" + CAP_BANNER + r"sha256=[0-9a-f]{63})[0-9a-f]", r"\1", text, count=1
        )

    edit_wf(root, name, t)


def main(argv):
    if len(argv) < 3:
        die("usage: cap-mutate.py <root> <mutation> [arg]")
    root, mut = argv[1], argv[2]

    # ---- manifest matrix ------------------------------------------------
    if mut == "top-array":
        manifest_path(root).write_text("[]\n", encoding="utf-8")
    elif mut == "top-scalar":
        manifest_path(root).write_text("5\n", encoding="utf-8")
    elif mut == "malformed-json":
        manifest_path(root).write_text("{ not json\n", encoding="utf-8")
    elif mut == "manifest-absent":
        manifest_path(root).unlink()
    elif mut == "lock-absent":
        lock_path(root).unlink()
    elif mut == "profiles-missing":
        d = load_manifest(root)
        del d["profiles"]
        dump_manifest(root, d)
    elif mut == "profiles-wrongtype":
        d = load_manifest(root)
        d["profiles"] = "not-an-object"
        dump_manifest(root, d)
    elif mut == "unknown-group":
        d = load_manifest(root)
        d["profiles"]["command"].append("@no_such_group")
        dump_manifest(root, d)
    elif mut == "dup-token":
        d = load_manifest(root)
        d["profiles"]["command"].append("Bash(jq:*)")  # already resolved in command
        dump_manifest(root, d)
    elif mut == "empty-profile":
        d = load_manifest(root)
        d["profiles"]["command"] = []
        dump_manifest(root, d)
    elif mut == "falsy-group":
        d = load_manifest(root)
        d["groups"]["core_review"] = False
        dump_manifest(root, d)
    elif mut == "version-string":
        d = load_manifest(root)
        d["manifest_version"] = "2"
        dump_manifest(root, d)
    elif mut == "version-bool":
        # bool is an int subclass; the generator's explicit isinstance(ver, bool) guard
        # must reject it as a non-integer.
        d = load_manifest(root)
        d["manifest_version"] = True
        dump_manifest(root, d)
    elif mut == "version-bump":
        # Bump manifest_version but regenerate NOTHING — the banners still embed the old
        # version, so --check must flag stale banners even though the token lists match.
        d = load_manifest(root)
        d["manifest_version"] = int(d["manifest_version"]) + 1
        dump_manifest(root, d)
    elif mut == "lock-unreadable":
        # Present-but-unreadable lock (a directory in its place): read_text raises OSError,
        # which the generator must turn into a fail-closed breadcrumb, not a traceback.
        p = lock_path(root)
        p.unlink()
        p.mkdir()
    elif mut == "review-narrow":
        # Drop a NON-leading token from a review-referenced group while the lock keeps it →
        # resolved review NARROWS below the lock (the missing-direction boundary drift).
        d = load_manifest(root)
        d["groups"]["core_review"].pop()
        dump_manifest(root, d)
    elif mut == "review-widen":
        # Add a token to a review-referenced GROUP → resolved review drifts from the
        # lock (the reviewer-boundary planted defect); leading three tokens unchanged.
        d = load_manifest(root)
        d["groups"]["core_review"].append("Bash(WIDEN_REVIEWER:*)")
        dump_manifest(root, d)
    elif mut == "review-leading":
        # Reorder review so its first token is not Read — AND update the lock to match,
        # proving the leading-token contract fires even when the lock agrees.
        d = load_manifest(root)
        d["profiles"]["review"].insert(0, "Bash(LEADVIOLATION:*)")
        dump_manifest(root, d)
        lock = lock_path(root)
        lock.write_text("Bash(LEADVIOLATION:*)\n" + lock.read_text(encoding="utf-8"), encoding="utf-8")

    # ---- region matrix --------------------------------------------------
    elif mut == "anchor-absent":
        # Rename the ASSIGNMENT (line-start after indent), not a REVIEW=' mention in a
        # maintenance comment, so the generator genuinely loses its anchor.
        edit_wf(
            root,
            "matcher-probe.yml",
            lambda s: re.sub(r"(?m)^([ \t]*)REVIEW='", r"\1ZREVIEW='", s, count=1),
        )
    elif mut == "anchor-duplicated":
        def dup(text):
            m = re.search(r"^[ \t]*TOOLS='[^']*'\n", text, re.MULTILINE)
            if not m:
                return text
            return text[: m.end()] + m.group(0) + text[m.end() :]

        edit_wf(root, "devflow-runner.yml", dup)
    elif mut == "implement-anchor-duplicated":
        # The implement region is a plain TOOLS=' assignment since issue #1170 (hoisted
        # into devflow-implement.yml's `Resolve allowed-tools` step). Duplicate that
        # assignment: at action runtime a later duplicate wins, so --check must refuse
        # the ambiguity rather than verify only the first (still-canonical) copy.
        def dup_impl(text):
            m = re.search(r"^[ \t]*TOOLS='[^']*'\n", text, re.MULTILINE)
            if not m:
                return text
            return text[: m.end()] + m.group(0) + text[m.end() :]

        edit_wf(root, "devflow-implement.yml", dup_impl)
    elif mut == "crlf-in-region":
        edit_wf(
            root,
            "devflow-runner.yml",
            lambda s: s.replace("TOOLS='Read,Glob,", "TOOLS='Read,\rGlob,", 1),
        )
    elif mut == "target-file-absent":
        wf(root, "devflow.yml").unlink()
    elif mut == "banner-malformed":
        truncate_banner_hex(root, "devflow-runner.yml")

    # ---- planted-defect positive controls -------------------------------
    elif mut == "del-runner-review":
        del_token(root, "devflow-runner.yml", "Bash(jq:*)")
    elif mut == "del-command":
        del_token(root, "devflow.yml", "Bash(jq:*)")
    elif mut == "del-implement":
        del_token(root, "devflow-implement.yml", "Bash(jq:*)")
    elif mut == "del-probe-review":
        del_token(root, "matcher-probe.yml", "Bash(rm -f:*)")
    elif mut == "del-probe-implement":
        del_token(root, "matcher-probe.yml", "Bash(pytest:*)")
    elif mut == "manifest-add-nonreview":
        d = load_manifest(root)
        d["profiles"]["command"].append("Bash(ADDED_TO_MANIFEST:*)")
        dump_manifest(root, d)
    elif mut == "banner-flip":
        flip_banner_hex(root, "devflow-runner.yml")

    # ---- directional-output + idempotency helpers -----------------------
    elif mut == "region-add-token":
        # Hand-add a token to a generated WORKFLOW region (the drift event the
        # directional --check output steers away from blind regeneration for).
        edit_wf(
            root,
            "devflow.yml",
            lambda s: s.replace(
                "TOOLS='Read, Write,", "TOOLS='Read, Bash(HANDADDED:*), Write,", 1
            ),
        )
    elif mut == "strip-banners":
        for name in WF:
            edit_wf(
                root,
                name,
                lambda s: re.sub(
                    r"^[ \t]*# devflow-capability-manifest:[^\n]*\n", "", s, flags=re.MULTILINE
                ),
                expect_change=False,
            )

    # ---- #561 review follow-up (PR #588) --------------------------------
    elif mut == "anchor-dup-sameline":
        # A SAME-LINE second assignment after `;` — wins at bash runtime (last-assignment-
        # wins) but is NOT line-leading, so a line-anchored dup count misses it. The
        # statement-position dup guard must refuse it on both generate and --check.
        edit_wf(
            root,
            "devflow-runner.yml",
            lambda s: re.sub(
                r"(?m)^([ \t]*TOOLS='[^']*')",
                r"\1; TOOLS='Read,Glob,Grep,Bash(SAMELINE_WIDEN:*)'",
                s,
                count=1,
            ),
        )
    elif mut == "anchor-dup-space":
        # A WHITESPACE-separated second assignment word — bash accepts several assignment
        # words on one simple command (last wins, persists with no command word), so this
        # wins at runtime with NO ;/&&/|| separator at all. The quote/separator-agnostic
        # replacement counter must still refuse it.
        edit_wf(
            root,
            "devflow-runner.yml",
            lambda s: re.sub(
                r"(?m)^([ \t]*TOOLS='[^']*')",
                r"\1 TOOLS='Read,Glob,Grep,Bash(SPACE_WIDEN:*)'",
                s,
                count=1,
            ),
        )
    elif mut == "anchor-dup-dquote":
        # A DOUBLE-QUOTED literal replacement on a fresh statement line — keeps the
        # canonical single-quote line intact (banner sha / lock / single-quote parse all
        # still validate) while winning at runtime by last-assignment-wins. A single-quote-
        # scoped guard misses it; the replacement counter (which excludes only the
        # self-referencing `TOOLS="$TOOLS,…"` append) must count and refuse it.
        def inject_dquote(text):
            m = re.search(r"(?m)^([ \t]*)TOOLS='[^']*'", text)
            if not m:
                return text
            indent = m.group(1)
            inject = "\n" + indent + 'TOOLS="Read,Glob,Grep,Bash(DQUOTE_WIDEN:*)"'
            return text[: m.end()] + inject + text[m.end():]

        edit_wf(root, "devflow-runner.yml", inject_dquote)
    elif mut == "version-missing":
        d = load_manifest(root)
        del d["manifest_version"]
        dump_manifest(root, d)
    elif mut == "groups-missing":
        d = load_manifest(root)
        del d["groups"]
        dump_manifest(root, d)
    elif mut == "group-nonstring-token":
        d = load_manifest(root)
        d["groups"]["core_review"].append(5)
        dump_manifest(root, d)
    elif mut == "profiles-extra-key":
        d = load_manifest(root)
        d["profiles"]["extra_profile"] = ["Read"]
        dump_manifest(root, d)
    elif mut == "profile-spec-nonlist":
        d = load_manifest(root)
        d["profiles"]["command"] = "not-a-list"
        dump_manifest(root, d)
    elif mut == "profile-nonstring-entry":
        d = load_manifest(root)
        d["profiles"]["command"].append(5)
        dump_manifest(root, d)
    elif mut == "manifest-unreadable":
        # Present-but-unreadable manifest (a directory in its place): read_text raises
        # OSError, which the generator must turn into a fail-closed breadcrumb.
        p = manifest_path(root)
        p.unlink()
        p.mkdir()
    elif mut == "workflow-unreadable":
        # Present-but-unreadable target workflow (a directory in its place): read_wf's
        # open() raises OSError, which must fail closed with a named breadcrumb, not a
        # traceback (the discipline load_manifest/load_lock already apply).
        p = wf(root, "devflow.yml")
        p.unlink()
        p.mkdir()
    else:
        die(f"unknown mutation: {mut}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
