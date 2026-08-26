#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Guard the lib/test CI-shellcheck lint carve-out (issue #717).

`.github/workflows/ci.yml` lints the repo's shell scripts with shellcheck. The
`git ls-files '*.sh' | grep -v '^lib/test/'` glob deliberately EXCLUDES `lib/test/`
(its gh-stub fixtures are intentionally unlinted), and the excluded shipped files
are then re-added by a hand-maintained explicit list plus a dedicated job for
`lib/test/run.sh`. Nothing guarded that hand-maintained list, so a new
`lib/test/**/*.sh` file that was neither added to the list nor deliberately left a
fixture silently shipped unlinted.

This guard reconciles the two sides. It reads ci.yml, derives the set of
`lib/test/**/*.sh` files CI actually lints (the union of every literal `lib/test/*`
argument to a direct `shellcheck` invocation), and fails naming the offending path
when any tracked `lib/test/**/*.sh` file is neither in that set nor under the single
declared exempt prefix `lib/test/fixtures/`.

It is a BEST-EFFORT reader of a human-maintained YAML file, so it fails CLOSED on
every shape it cannot interpret (unreadable/empty/non-YAML ci.yml; no `jobs:` mapping;
no shellcheck invocation locatable; the `git ls-files '*.sh'` glob's `lib/test/`
exclusion changed from the exact recognized form — whether the pipeline is written
backslash-joined or across POSIX trailing-`|`/`&&`/`||` continuations, both of which
are folded before the glob search) rather than reporting full coverage from the
explicit list alone. A red guard is the safe direction: it forces human attention.

KNOWN LIMITATIONS (best-effort caveats). (1) The glob-exclusion probe only distrusts the
`git ls-files` glob when that glob and the literal `shellcheck` land on ONE
continuation-folded line. A pipeline restructured so they are not co-located (a `> "$list"`
in one statement and `xargs shellcheck < "$list"` in another) leaves the probe with nothing
to inspect, and it returns "trusted" — after which the `grep -v '^lib/test/'` exclusion could
be narrowed or removed unnoticed. Folding more onto one line is the fail-closed direction, so
the recognized shapes are covered; an un-co-located restructure is not. (2) A shellcheck step
gated inactive by a job- or step-level `if:` (e.g. `if: false`) is still read as live
coverage — this reader does
not evaluate `if:` conditions. Disabling a lint step that way would let its files read
as covered though CI lints nothing; it takes an implausible self-sabotaging edit, and
the `if:` surface is not part of the reconciled contract, so it is left uncovered.

Exit 0 = every tracked lib/test file is CI-linted or under the exempt prefix.
Exit 1 = a fail-closed condition, or an offending uncovered non-exempt file.
The verdict line is printed to stdout (`OK` / `FAIL: <reason>`); details go to stderr.
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

# Reuse the shared git-ls-files population reader's index argv (issue #724), loaded by
# path exactly as the sibling #711 lints do. Naming the constant is what states the
# index-read choice, and it is what carries `-c core.quotePath=false` (issue #1217) so a
# tracked non-ASCII `lib/test/` script arrives as its raw bytes.
#
# The failure mode here is a FALSE RED, not a silent drop — this guard's selection is a git
# PATHSPEC (`lib/test/*.sh`), which matches the real path bytes and is unaffected by
# quoting, so the file is still enumerated, C-quoted spelling and all. It then reaches
# `check()`, where the quoted spelling matches neither `EXEMPT_PREFIX` nor any CI-linted
# literal, so a legally-named fixture is reported as an unlinted OFFENDER. (The silent-drop
# mechanism issue #1217 describes belongs to the prefix-FILTERING lints, e.g.
# `lint-subagent-dispatch-namespace.py`'s `startswith("agents/")` — not to this one.)
_POP_PATH = Path(__file__).resolve().parent / "lint_population.py"
try:
    _pop_spec = importlib.util.spec_from_file_location("lint_population", _POP_PATH)
    if _pop_spec is None or _pop_spec.loader is None:
        raise ImportError(f"no loadable spec for {_POP_PATH}")
    _pop = importlib.util.module_from_spec(_pop_spec)
    _pop_spec.loader.exec_module(_pop)
except Exception as _exc:
    # Print the documented stdout verdict before exiting: this module's contract is
    # `OK` / `FAIL: <reason>` on stdout, and run.sh's driver reads `${out%%:*}` from a
    # capture that discards stderr — a bare SystemExit would leave it with no cause at all.
    print(
        f"FAIL: the shared population reader {_POP_PATH} could not be loaded "
        f"({_exc.__class__.__name__}: {_exc}); refusing to audit"
    )
    raise SystemExit(
        f"lint-carveout-guard: the shared population reader {_POP_PATH} could not be "
        f"loaded ({_exc.__class__.__name__}: {_exc}); refusing to audit"
    ) from _exc
if not hasattr(_pop, "LS_FILES_INDEX"):
    print(f"FAIL: {_POP_PATH} no longer provides `LS_FILES_INDEX`; refusing to audit")
    raise SystemExit(
        f"lint-carveout-guard: {_POP_PATH} no longer provides `LS_FILES_INDEX`; "
        "refusing to audit"
    )

# The single declared exempt prefix. A tracked lib/test file under this prefix is
# deliberately unlinted (adversarial/malformed fixtures live here); anything else
# must be CI-linted. This is EXACTLY one prefix and no other path (AC, issue #717).
EXEMPT_PREFIX = "lib/test/fixtures/"

# The exact `grep -v` exclusion expression the glob invocation must carry for the
# derivation to trust that the `git ls-files '*.sh'` glob contributes ZERO lib/test
# coverage. If the glob feeds shellcheck but this exact expression is absent (removed
# or narrowed), the guard cannot reason about what the glob now lints, so it fails
# closed rather than deriving coverage from the explicit list alone (AC, issue #717).
RECOGNIZED_GLOB_EXCLUSION = "^lib/test/"


class GuardError(Exception):
    """A fail-closed condition: the guard could not establish coverage."""


def _strip_shell_comments(text: str) -> str:
    """Drop shell comments so a lib/test path named ONLY in a comment is not counted
    as covered (AC, issue #717). Removes full-line `#` comments and an inline ` #...`
    tail. Best-effort: a lib/test path is a bare token that never contains ` #`, so a
    naive inline strip cannot swallow a real argument."""
    out = []
    for line in text.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        # inline comment: a ' #' preceded by whitespace starts a comment tail here.
        m = re.search(r"\s#", line)
        if m:
            line = line[: m.start()]
        out.append(line)
    return "\n".join(out)


def _collect_run_blocks(ci_text: str) -> str:
    """Parse ci.yml and return every step `run:` block joined. Fails closed on a
    non-YAML / empty / non-mapping document (AC malformed-shape rows)."""
    try:
        import yaml  # lazy: PyYAML is a preflight prerequisite
    except Exception as exc:  # pragma: no cover - preflight guarantees PyYAML
        raise GuardError(f"PyYAML unavailable to parse .github/workflows/ci.yml: {exc}")
    try:
        doc = yaml.safe_load(ci_text)
    except Exception as exc:
        raise GuardError(f".github/workflows/ci.yml is not valid YAML: {exc}")
    if not isinstance(doc, dict) or not doc:
        raise GuardError(".github/workflows/ci.yml is empty or not a YAML mapping")
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict):
        raise GuardError(".github/workflows/ci.yml has no `jobs:` mapping")
    runs: list[str] = []
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if isinstance(step, dict) and isinstance(step.get("run"), str):
                runs.append(step["run"])
    return "\n".join(runs)


def _shellcheck_invocations(cleaned: str) -> list[str]:
    """Return each direct `shellcheck ...` invocation as one joined-continuation
    string. `cleaned` is the comment-stripped, continuation-joined run-block text
    (produced once by the caller)."""
    invocations: list[str] = []
    # A shellcheck command begins at a `shellcheck` token that starts a command
    # (line start, after `|`, `;`, `&&`, `||`, or `xargs [-r] `). Capture to the next
    # newline (its arguments are all on the joined line).
    for line in cleaned.split("\n"):
        for m in re.finditer(r"(?:^|\||;|&&|\|\||xargs(?:\s+-\w+)*\s+)\s*shellcheck\b", line):
            invocations.append(line[m.end():])
    return invocations


def _glob_exclusion_ok(cleaned: str) -> bool:
    """True iff a `git ls-files '*.sh'` pipeline that feeds shellcheck carries the
    EXACT recognized `grep -v '^lib/test/'` exclusion. If such a glob pipeline exists
    but its exclusion differs (removed/narrowed), return False → fail closed. `cleaned`
    is the comment-stripped, continuation-joined run-block text (produced once by the
    caller)."""
    # Find a `git ls-files '*.sh'` pipeline that eventually reaches shellcheck.
    glob_lines = [
        ln
        for ln in cleaned.split("\n")
        if re.search(r"git\s+ls-files\s+'\*\.sh'", ln) and "shellcheck" in ln
    ]
    if not glob_lines:
        # No glob feeding shellcheck at all — the derivation does not depend on it,
        # so there is nothing to distrust. (A ci.yml with NO shellcheck anywhere is
        # caught separately as "no invocation locatable".)
        return True
    for ln in glob_lines:
        m = re.search(r"grep\s+-v\s+'([^']*)'", ln)
        if not m or m.group(1) != RECOGNIZED_GLOB_EXCLUSION:
            return False
    return True


def derive_ci_linted(ci_text: str) -> set[str]:
    """Derive the set of lib/test/**/*.sh paths CI lints. Raises GuardError on any
    fail-closed condition."""
    run_text = _collect_run_blocks(ci_text)
    # Comment-strip + join line-continuations ONCE; both derivations below read it.
    cleaned = _strip_shell_comments(run_text).replace("\\\n", " ")
    # Also fold POSIX operator-continuations: a physical line ending in an unquoted
    # trailing `|`, `&&`, or `||` continues onto the next line with NO backslash. Left
    # unjoined, a `git ls-files '*.sh' | grep -v … | xargs … shellcheck` pipeline
    # written across such lines would span several physical lines, so
    # _glob_exclusion_ok's single-line search finds no glob line, returns True, and the
    # lib/test/ exclusion could be narrowed or removed unnoticed — a fail-OPEN gap in a
    # guard whose whole promise is fail-closed (issue #717 review). Preserve the operator
    # (\1) so _shellcheck_invocations still sees its command-start delimiters. Folding
    # more onto one line is the fail-CLOSED direction, consistent with this best-effort
    # parser's contract. `||` is matched before the single `|` by alternation order.
    cleaned = re.sub(r"(\|\||&&|\|)[ \t]*\n[ \t]*", r"\1 ", cleaned)
    invocations = _shellcheck_invocations(cleaned)
    if not invocations:
        raise GuardError(
            "could not locate any shellcheck invocation in "
            ".github/workflows/ci.yml (fail-closed: not reporting coverage)"
        )
    if not _glob_exclusion_ok(cleaned):
        raise GuardError(
            "the `git ls-files '*.sh'` glob's lib/test/ exclusion is not the exact "
            f"recognized form `grep -v '{RECOGNIZED_GLOB_EXCLUSION}'` in "
            ".github/workflows/ci.yml (fail-closed: cannot derive coverage from the "
            "explicit list alone)"
        )
    linted: set[str] = set()
    for seg in invocations:
        for tok in re.findall(r"lib/test/[A-Za-z0-9_./-]+\.sh", seg):
            linted.add(tok)
    return linted


def tracked_lib_test_scripts(repo_root: Path) -> list[str]:
    """Enumerate tracked lib/test/**/*.sh via index-reading `git ls-files` (issue
    #711: never a recursive filesystem walk, which would descend into sibling
    worktrees under .claude/worktrees/ and count their copies). The argv composes the
    shared `LS_FILES_INDEX` constant; see its import above."""
    out = subprocess.run(
        [*_pop.LS_FILES_INDEX, "lib/test/*.sh", "lib/test/**/*.sh"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        raise GuardError(f"git ls-files failed enumerating lib/test scripts: {out.stderr.strip()}")
    seen: list[str] = []
    for line in out.stdout.splitlines():
        p = line.strip()
        if p and p not in seen:
            seen.append(p)
    if not seen:
        # Zero rows is an UNESTABLISHED population, not an empty one: git pathspecs are
        # resolved relative to the invocation, so a --repo-root pointing at a subdirectory, a
        # sparse checkout, or a rename of lib/test/ all yield zero rows with rc 0. Reporting
        # OK there is the fail-OPEN direction in the one helper whose contract is to fail
        # closed. (--files-file callers bypass this path entirely, so the synthetic fixtures
        # may still legitimately supply an empty list.)
        raise GuardError(
            f"git ls-files enumerated ZERO lib/test/**/*.sh files under {repo_root} — the "
            "population is unestablished, not empty (fail-closed: not reporting coverage)"
        )
    return seen


def check(ci_text: str, files: list[str]) -> tuple[bool, str]:
    """Return (ok, message). ok=False on the first offending file. Fail-closed
    conditions propagate as GuardError to the caller."""
    linted = derive_ci_linted(ci_text)
    # Collect EVERY offender, not just the first: reporting one at a time makes a human fix
    # them one red CI run at a time.
    offenders = [
        f for f in files
        if not f.startswith(EXEMPT_PREFIX)  # deliberately-unlinted fixture side
        and f not in linted                 # CI-linted side
    ]
    if offenders:
        return (
            False,
            (f"FAIL: {', '.join(offenders)} "
            f"{'is a tracked' if len(offenders) == 1 else 'are tracked'} lib/test/**/*.sh "
            f"{'file' if len(offenders) == 1 else 'files'} that CI does not lint and "
            f"that {'is' if len(offenders) == 1 else 'are'} NOT under the exempt prefix "
            f"`{EXEMPT_PREFIX}` — landed on the not-CI-linted, not-exempt side of the "
            "partition. Add to a shellcheck invocation in .github/workflows/ci.yml, or (if "
            f"deliberately unlintable fixtures) move under {EXEMPT_PREFIX}."),
        )
    return (True, "OK")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", default=".", help="repository root (default: cwd)")
    ap.add_argument(
        "--ci-file",
        default=None,
        help="workflow file to analyse (default: <repo-root>/.github/workflows/ci.yml)",
    )
    ap.add_argument(
        "--files-file",
        default=None,
        help="newline-separated list of lib/test paths to check "
        "(default: derived via `git ls-files` at --repo-root). Used by synthetic tests.",
    )
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root)
    ci_path = Path(args.ci_file) if args.ci_file else repo_root / ".github/workflows/ci.yml"

    try:
        try:
            ci_text = ci_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise GuardError(f"could not read {ci_path}: {exc}")

        if args.files_file:
            try:
                files_text = Path(args.files_file).read_text(encoding="utf-8")
            except OSError as exc:
                # Mirror the ci_path read above: an unreadable path must reach the GuardError
                # handler so the documented `FAIL: <reason>` stdout verdict is still emitted.
                raise GuardError(f"could not read --files-file {args.files_file}: {exc}")
            files = [ln.strip() for ln in files_text.splitlines() if ln.strip()]
        else:
            files = tracked_lib_test_scripts(repo_root)

        ok, message = check(ci_text, files)
    except GuardError as exc:
        print(f"FAIL: {exc}")
        print(f"lint-carveout-guard: {exc}", file=sys.stderr)
        return 1

    print(message)
    if not ok:
        print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
