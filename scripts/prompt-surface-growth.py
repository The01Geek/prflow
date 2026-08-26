#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Render the prompt-surface byte delta a PR introduces, plus the running total.

PRFlow's prompt surface — the markdown an agent reads while it works — grows one
review-answering sentence at a time, and no PR ever showed anyone it was happening
(issue #1350). This helper makes that growth a rendered fact in the PR description:
for every covered `*.md` file the branch changed it prints the byte delta between the
merge-base and `HEAD` **and** the file's byte total at `HEAD`, closing with an
aggregate row for the whole covered surface.

Both columns are load-bearing. A delta alone ("+3 KB") normalizes into wallpaper the
third time a reader sees it; the running total beside it is what keeps the number
meaningful as it repeats.

Covered population: tracked files whose path ends in exactly `.md` under `skills/`,
`agents/`, or `.prflow/prompt-extensions/`, enumerated from the committed tree at BOTH
endpoints (the merge-base commit and `HEAD`) so a file the branch deletes still produces
a row (total 0, negative delta). Reading the two *trees* rather than the index is what
makes both endpoints addressable — a merge-base commit has no index — and it means
staged-but-uncommitted edits are deliberately not counted.
The exact-`.md` suffix test is what excludes `*.md.example` templates and every
non-markdown asset — no separate exclusion mechanism exists or is needed.

This is measurement, never a gate. It defines no threshold, ceiling, or budget, and
compares nothing against a limit: every path — including an unresolvable merge-base
and a checkout with nothing to measure — exits 0 with a stated breadcrumb
instead of a table. A table of zeros is deliberately never printed: a reader would
misread it as "this PR added nothing", which is worse than no table at all.

Invoke it as a direct leading token, the vendored literal
(`.prflow/vendor/prflow/scripts/prompt-surface-growth.py`) FIRST, falling back to the
repo-relative `scripts/prompt-surface-growth.py` only where that path does not resolve:
the repo-relative spelling is granted in no cloud profile, so leading with it spends a
denial before the working form is reached. Do not re-add a claim that the interpreter-head
`python3 <path>` form is denied for this helper: cloud implement runs 32957163134 and
32936014504 each ran `python3 scripts/prompt-surface-growth.py` to a result under the
granted `Bash(python3:*)` head, so steering away from it costs a denial for nothing. That
measurement scopes this helper alone and settles nothing about the interpreter head in
general, which only `.github/workflows/matcher-probe.yml` can.

stdlib-only; shells out to `git` alone, honoring a non-probing `DEVFLOW_GIT` override
in the same shape `scripts/checkout-fingerprint.py` uses (`git` is a hard preflight
prerequisite, and there is no `resolve-git.sh`).
"""

import os
import subprocess
import sys


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


# The three covered prefixes. `skills/**` + `agents/**` mirrors the shipped-prompt
# population `lib/test/lint-shipped-pruned-path.py` already audits as one set; the
# prompt extensions are added because they load into the same context budget and
# were the surface nothing measured at all.
COVERED_PREFIXES = ("skills/", "agents/", ".prflow/prompt-extensions/")

# Merge-base candidates, tried in order (issue #1350 AC1): the remote's own recorded
# default branch first, then the two literal fallbacks.
_FALLBACK_REFS = ("origin/main", "main")

# Honor the DEVFLOW_GIT override without probing, mirroring the DEVFLOW_GH escape
# hatch and scripts/checkout-fingerprint.py's sibling GIT resolution.
_GIT = os.environ.get("DEVFLOW_GIT") or "git"


# Degradation notes accumulated during the run. Every one of them qualifies the
# figures, so every one must reach the reader who sees the figures — and that reader
# gets **stdout only**: the consuming prompt extension renders this helper's stdout
# verbatim and reads no stderr. Routing them through one list, emitted by `_emit()`
# alongside whatever the run prints, is what stops the next degradation arm from
# quietly re-inventing the stderr-only mistake at a new site. They are mirrored to
# stderr as well, for an operator watching a terminal.
_NOTES = []


def _note(text):
    """Record a degradation that qualifies this run's output."""
    _NOTES.append(text)
    print(f"prompt-surface growth: {text}", file=sys.stderr)


def _emit(body):
    """Print the run's output plus every degradation note, on stdout.

    Both the table and the no-table breadcrumbs go through here, because a note is
    at least as load-bearing on a breadcrumb as on a table: "no covered path changed"
    is an absolute negative claim, and a run that excluded entries it could not read
    has no business making it unqualified.
    """
    lines = list(body)
    if _NOTES:
        lines.append("")
        lines.extend(f"> Note: {n}" for n in _NOTES)
    print("\n".join(lines))
    return 0


def _repo_root():
    """The repository root, memoized — every git call runs from there.

    Anchoring on the root rather than the process working directory is the repo's
    shared `.prflow/`-reader contract, and here it is load-bearing rather than tidy:
    the `ls-tree` pathspecs below are repo-relative, so from a subdirectory they
    would match nothing and the run would print a confident "no covered path
    changed" — a false statement, rendered into a PR description as a generated
    fact. A root that cannot be resolved falls back to the working directory with a
    breadcrumb, so the degradation is stated rather than silent.
    """
    if _repo_root.cached is None:
        rc, out, err = _git(["rev-parse", "--show-toplevel"], cwd=os.getcwd())
        root = out.strip() if rc == 0 else ""
        if not root:
            # Quote git rather than assert a cause: this one call fails for a
            # not-a-repository, an unrunnable DEVFLOW_GIT, a dubious-ownership
            # refusal and a broken GIT_DIR alike, and naming only the
            # subdirectory case would misdiagnose three of the four.
            _note(
                "the repository root could not be resolved"
                + (f" (git said: {err.strip()})" if err.strip() else "")
                + ", so this run measured from the working directory and may "
                "under-report."
            )
            root = os.getcwd()
        _repo_root.cached = root
    return _repo_root.cached


_repo_root.cached = None


def _git(args, cwd=None):
    """Run git and return (rc, stdout, stderr). Never raises, for any reason.

    `check=False` only covers a git that *runs* and fails. A git that cannot be
    executed at all — absent from `PATH`, a `DEVFLOW_GIT` override naming a moved or
    non-executable path — raises `OSError` before any return code exists, which would
    end this helper in a traceback and defeat its always-exit-0 contract. Converting
    that into an rc sentinel keeps every caller's existing rc check correct.
    """
    try:
        proc = subprocess.run(
            [_GIT, *args],
            cwd=cwd if cwd is not None else _repo_root(),
            capture_output=True,
            check=False,
            # Decode with replacement rather than `text=True`'s strict policy. `-z`
            # is chosen below precisely so git does not quote unusual path bytes,
            # which means those raw bytes reach the decoder — and a strict decode
            # would raise UnicodeDecodeError (a ValueError, so the OSError guard
            # would not catch it), ending the run in the traceback this contract
            # exists to rule out. A mangled path in one row beats no output at all.
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        return 127, "", f"git (`{_GIT}`) could not be executed: {exc}"
    return proc.returncode, proc.stdout, proc.stderr


def _covered(path):
    """A tracked path is covered when it ends in exactly `.md` under a covered prefix.

    `endswith('.md')` is what excludes `*.md.example`: that name ends in `.example`.
    """
    return path.endswith(".md") and path.startswith(COVERED_PREFIXES)


def default_branch_refs():
    """Merge-base candidate refs, most specific first.

    The remote's recorded default branch (already spelled `origin/<name>`) leads;
    `origin/main` and `main` follow it as the AC-stated fallbacks. Duplicates are
    dropped so a repo whose default branch *is* `main` does not probe it twice.
    """
    refs = []
    rc, out, _ = _git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"])
    if rc == 0 and out.strip():
        refs.append(out.strip())
    for ref in _FALLBACK_REFS:
        if ref not in refs:
            refs.append(ref)
    return refs


def resolve_merge_base():
    """(merge_base_sha, ref, tried, last_err) — `tried` is the candidate list.

    The candidates come back even on the failure path so the caller can name them in
    its breadcrumb without re-deriving them, which would re-spawn the `symbolic-ref`
    probe purely to reformat data this call already has. `last_err` carries git's own
    message: `merge-base` also fails on UNRELATED HISTORIES (a `--depth=1` clone, a
    grafted CI checkout), and a breadcrumb naming only the refs it tried sends the
    reader to check branch names when the fix is `fetch --unshallow`.
    """
    tried = default_branch_refs()
    last_err = ""
    for ref in tried:
        rc, out, err = _git(["merge-base", "HEAD", ref])
        if rc == 0 and out.strip():
            return out.strip(), ref, tried, ""
        if err.strip():
            last_err = err.strip()
    return None, None, tried, last_err


def surface_at(ref):
    """({path: (blob_sha, size)}, git_stderr, skipped) for covered `*.md` in `ref`'s tree.

    On a git failure the map is `None` and the second element carries git's own
    message, so the caller's breadcrumb can name a cause rather than only a symptom.
    `skipped` counts records that were not readable blobs, so the caller can disclose
    the omission beside the figures it affects.

    One `ls-tree` call per endpoint carries the sizes with it (`--long`), so no
    per-file `cat-file -s` round trip is needed. `-z` keeps paths raw: without it
    git quotes any path with unusual bytes and the parse would silently mangle it.
    """
    rc, out, err = _git(
        ["ls-tree", "-r", "-z", "--long", ref, "--", *COVERED_PREFIXES]
    )
    if rc != 0:
        return None, err.strip(), 0
    surface = {}
    skipped = 0
    for record in out.split("\0"):
        if not record:
            continue
        meta, _, path = record.partition("\t")
        if not path or not _covered(path):
            continue
        fields = meta.split()
        # `<mode> <type> <sha> <size>` — a `-` size marks a non-blob entry. `-r`
        # does emit these (a submodule gitlink is `160000 commit … -`), but the
        # `.md` suffix test above has already dropped almost all of them, so this
        # guard is reached only by a non-blob whose path ends in `.md` — a gitlink
        # or an unrecognised record shape at such a path. It is excluded from the
        # figures and its exclusion is TALLIED, so the caller can disclose it beside
        # the table: a total that quietly omits a file is a wrong precise number,
        # which is worse than a missing one.
        if len(fields) != 4 or fields[1] != "blob" or not fields[3].isdigit():
            skipped += 1
            continue
        surface[path] = (fields[2], int(fields[3]))
    return surface, "", skipped


def changed_rows(base_surface, head_surface):
    """Sorted (path, delta, head_bytes) for every covered path the branch changed.

    Change is decided by blob identity, not size, so an edit that happens to keep a
    file's byte count still earns a row (with a delta of 0) rather than vanishing.
    """
    rows = []
    for path in sorted(set(base_surface) | set(head_surface)):
        base_sha, base_bytes = base_surface.get(path, (None, 0))
        head_sha, head_bytes = head_surface.get(path, (None, 0))
        if base_sha != head_sha:
            rows.append((path, base_bytes, head_bytes - base_bytes, head_bytes))
    return rows


def _signed(n):
    return f"{n:+,}"


def _pct(delta, base_bytes):
    """Signed percentage of the before-size, or `n/a` when there is no before-size.

    A file added on this branch has a zero denominator, so any percentage would be
    a division by zero or a fabricated 100%; render the absence instead.
    """
    if base_bytes == 0:
        return "n/a"
    return f"{delta / base_bytes * 100:+,.1f}%"


def render(head_sha, base_sha, ref, rows, surface_delta, surface_total):
    """The markdown table, as a list of lines. Degradation notes are `_emit`'s job."""
    lines = [
        "### Prompt-surface size",
        "",
        (f"Derived at `{head_sha}` against merge-base `{base_sha}` (`{ref}`). "
        "Covered: tracked `*.md` under `skills/`, `agents/`, "
        "`.prflow/prompt-extensions/`."),
        "",
        "| Path | Before | After | Δ bytes | Δ % |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for path, base_bytes, delta, head_bytes in rows:
        lines.append(
            f"| `{path}` | {base_bytes:,} | {head_bytes:,} "
            f"| {_signed(delta)} | {_pct(delta, base_bytes)} |"
        )
    surface_before = surface_total - surface_delta
    lines.append(
        f"| **Whole covered surface** | **{surface_before:,}** "
        f"| **{surface_total:,}** | **{_signed(surface_delta)}** "
        f"| **{_pct(surface_delta, surface_before)}** |"
    )
    return lines


def main():
    _force_utf8_streams()
    rc, head_out, head_err = _git(["rev-parse", "HEAD"])
    if rc != 0 or not head_out.strip():
        return _emit([
            "prompt-surface growth: `HEAD` could not be resolved (not a git "
            "checkout, a repository with no commits, or an unrunnable git)"
            + (f" — git said: {head_err.strip()}" if head_err.strip() else "")
            + " — no table rendered."
        ])
    head_sha = head_out.strip()

    base_sha, ref, tried, mb_err = resolve_merge_base()
    if base_sha is None:
        return _emit([
            "prompt-surface growth: the merge-base could not be resolved (tried "
            + ", ".join(f"`{r}`" for r in tried)
            + ")"
            + (f" — git said: {mb_err}" if mb_err else "")
            + " — no table rendered."
        ])

    # AC1a arm (i): a checkout pinned to the default branch has no PR-side commits,
    # so every row would read zero. Say so instead of printing that table.
    if base_sha == head_sha:
        return _emit([
            (f"prompt-surface growth: `HEAD` (`{head_sha}`) is the merge-base with "
            f"`{ref}`, so this checkout carries no branch commits to measure — "
            "no table rendered.")
        ])

    # Name the endpoint that failed, and quote git's own message: "could not be read
    # from A or B" leaves a reader with no starting point, and git already wrote the
    # reason. The message is quoted as data — its only caller-influenced content is a
    # ref name.
    base_surface, base_err, base_skipped = surface_at(base_sha)
    head_surface, head_err, head_skipped = surface_at(head_sha)
    for label, sha, surface, err in (
        ("merge-base", base_sha, base_surface, base_err),
        ("HEAD", head_sha, head_surface, head_err),
    ):
        if surface is None:
            return _emit([
                "prompt-surface growth: the covered file set could not be read from "
                f"{label} `{sha}`"
                + (f" — git said: {err}" if err else "")
                + " — no table rendered."
            ])

    # Report the two endpoints' skips separately rather than folding them into one
    # number: they distort DIFFERENT columns — a base-side skip makes a delta read as
    # a full-size addition, a head-side skip understates the totals — and neither a
    # max nor a sum of two disjoint sets is a true count of anything.
    if base_skipped:
        _note(
            f"{base_skipped} entr(ies) under a covered prefix at the merge-base were "
            "not readable blobs (a submodule gitlink at a `.md` path, or an "
            "unrecognised `ls-tree` record); the Δ column excludes them."
        )
    if head_skipped:
        _note(
            f"{head_skipped} entr(ies) under a covered prefix at `HEAD` were not "
            "readable blobs (a submodule gitlink at a `.md` path, or an unrecognised "
            "`ls-tree` record); the byte totals exclude them."
        )

    rows = changed_rows(base_surface, head_surface)

    # AC1a arm (ii): the branch has commits, but none of them touched the covered
    # surface. This is the common, healthy case and it is reported, not rendered.
    # It routes through `_emit` like every other arm: this is an absolute NEGATIVE
    # claim, so a run that excluded entries it could not read has the least business
    # of any making it unqualified.
    if not rows:
        return _emit([
            ("prompt-surface growth: no tracked `*.md` under `skills/`, `agents/`, "
            f"or `.prflow/prompt-extensions/` changed between `{base_sha}` and "
            f"`{head_sha}` — no table rendered.")
        ])

    # The aggregate delta is the sum of the rows above it — an unchanged file
    # contributes nothing, so summing the rows and differencing the two endpoint
    # totals give the same number, and taking it from the rows makes the identity
    # structural rather than a coincidence a reader has to re-derive. The aggregate
    # TOTAL is deliberately the whole covered surface at HEAD, not the changed rows'
    # subtotal: the running total of the surface is what keeps a repeated delta
    # meaningful, which is this table's entire reason for existing.
    surface_delta = sum(delta for _, _, delta, _ in rows)
    surface_total = sum(size for _, size in head_surface.values())
    return _emit(
        render(head_sha, base_sha, ref, rows, surface_delta, surface_total)
    )


if __name__ == "__main__":
    sys.exit(main())
