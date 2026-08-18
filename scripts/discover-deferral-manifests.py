#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""DevFlow deferrals-manifest discovery for /implement Phase 4.0.5.

Phase 4.0.5 of `/devflow:implement` files follow-up GitHub issues for review
findings deferred during the Phase 3.3 fix loop. Its first step discovers the
run-scoped deferrals manifests written by /devflow:review-and-fix at
`.prflow/tmp/review/<slug>/<run-id>/deferrals.json` (one per run). The old
inline `find $SEARCH_DIRS … | sort` capture collapsed a *failed* search and a
*clean no-match* search onto the same empty output — a degraded search then read
as the clean no-op and acknowledged deferrals were silently stranded (issue #555,
observed live in #533). This helper searches each candidate root INDEPENDENTLY,
classifies each root's outcome, and preserves discovery status through the exit
code so output production can never mask a failed search.

Each supplied root is classified into exactly one of three outcomes:
    ok      searched cleanly (zero matches allowed)
    absent  the root path does not exist (benign — contributes nothing)
    failed  the root exists but could not be fully traversed (an OSError at the
            root OR anywhere the walk actually visits — a non-directory root, a
            permission or I/O error, an unreadable subtree at depth <= 2). The
            walk is pruned below depth 2 (nothing deeper can match), so a
            subtree at depth >= 3 is never visited and cannot classify a root
            `failed`; that is out of the matching contract's reach by
            construction, not a swallowed error. This does NOT rely on os.walk's
            default error-swallowing (`onerror=None` silently skips an unreadable
            subtree and would classify the root `ok` with the manifest inside it
            missing — the exact silent-loss shape this helper exists to remove,
            re-created one level down). We pass a raising `onerror`.

stdout: the de-duplicated, lexicographically sorted list of matching manifest
paths, one per line, in POSIX separator form (forward slashes) so the list is
stable across native-Windows python3 hosts (#275's documented host shape).
A match is a file named `deferrals.json`, size > 0 bytes, located EXACTLY two
directory levels below a supplied root (`<root>/<run-id>/deferrals.json`) —
mirroring the retired `find -mindepth 2 -maxdepth 2 -name deferrals.json -size +0c`
(narrowed: this helper matches regular files only, where the retired `find` had no
`-type f` and would have matched a directory named `deferrals.json`).

stderr carries a roots-echo line naming every root's absolute path (os.path.abspath
— normalized, NOT symlink-resolved) and classification on every *discovery* run,
i.e. whenever at least one root argument was supplied, so an `absent` root is
observable rather than silent. The zero-argument usage error (exit 2) returns
before any root is classified and therefore emits only the usage message.
Failed roots additionally emit a per-root breadcrumb, and a discovery run emits
at most one aggregate discrimination marker naming the cause. That marker's
exclusivity holds for a caller passing path-safe roots: the per-root breadcrumb
interpolates the root path and the OSError text, so a caller passing a root that
itself contains a marker substring can defeat it. The §4.0.5 fence cannot — both
its roots are `pr-<N>` and an `[a-z0-9._-]`-sanitized branch slug — but this
helper does not sanitize argv, so the guarantee rests on that input discipline.

Exit codes (discovery mode):
    0  no root classified `failed` (all ok/absent, including zero total matches)
    2  invoked with zero root arguments (usage message; NO discovery marker)
    3  partial — at least one `failed` AND at least one `ok`/`absent`
       (discovered paths are still printed); stderr carries `devflow: discovery partial:`
    4  every root classified `failed` (empty stdout); stderr carries `devflow: discovery failed:`
An uncaught exception exits non-zero (interpreter default) with neither marker on
stderr, which the §4.0.5 reader's unrecognised-shape arm records as a failure.

PRESENCE MODE (issue #1374). `--presence-for-pr N` answers a different question:
is any deferred review finding present for PR N? Phase 4.0.5's filing procedure now
lives in a gated reference the phase file reads only when this predicate says so, and
this mode is that predicate. It derives BOTH candidate search directories itself —
including the branch slug, in Python rather than through the fence's `tr` chain, so a
host without `tr` resolves the same directories as a host with it — and answers over
BOTH presence sources: the run-scoped manifests (which a re-entry after filing has
already consumed) and the slug-level aggregate (which has no producer on a first
entry). Reading either alone fails open.

Exit codes (presence mode) — three states, complete by construction because
`_run_presence` catches every escaping exception. That wrapper is load-bearing rather
than defensive: CPython exits 1 on an uncaught exception and 1 is `absent` here, so
without it a crash would read as "nothing was deferred" and strand acknowledged findings.
    0  present       stdout `present: <n>` (run-scoped matches plus the aggregate)
    1  absent        stdout `absent: 0`
    2  unestablished stdout `unestablished: reason=<token>` (+ an optional `root:` line)
Discovery mode's `3` and `4` are unreachable here: an unreadable candidate collapses
into `2` regardless of how many others were readable. That flattening is deliberate,
so both gated Phase 4 sub-steps document one identical three-state contract; the cost
is that presence mode cannot tell a partial failure from a total one. A malformed
invocation reports `2` as well — the same fail-closed convention `workpad.py
deferred-presence` adopts, so a bad call loads the reference rather than silently
skipping it. The exit status carries every state, and the one place a caller reads stdout
is the shipped stub's skip arm: it requires the literal `absent: 0` line ALONGSIDE exit 1,
because a crashing interpreter also exits 1 and would otherwise route to the skip.

Usage:
    discover-deferral-manifests.py ROOT [ROOT ...]
    discover-deferral-manifests.py --presence-for-pr N
"""

import os
import subprocess
import sys

MANIFEST_NAME = "deferrals.json"

# The presence-mode dispatch token. It is recognized ONLY as argv[0], so a root path
# in any later position stays a root path: the filing fence passes `$SEARCH_DIRS`
# unquoted for word-splitting, and a positional-anywhere flag would let a root that
# happened to match it switch modes mid-list.
PRESENCE_FLAG = "--presence-for-pr"

# The review scratch root, cwd-relative — the identical literal the §4.0.5 filing
# fence composes SLUG_DIR and BRANCH_DIR from. Anchoring this to the git toplevel
# instead would search directories the fence never writes to.
REVIEW_ROOT = ".prflow/tmp/review"

# The character set the fence's `tr -cd 'a-z0-9._-'` keeps, spelled out so the port
# and the shell chain cannot drift through an interpretation of a range expression.
_SLUG_KEEP = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._-")

# The presence mode's `reason=` vocabulary. It is a CROSS-FILE contract — the §4.0.5 stub
# quotes the token into the reflection it records — so the set is named here rather than
# left as literals at each call site, where a drifted token would be invisible until a
# reader met an unfamiliar word in a workpad.
REASON_MALFORMED_INVOCATION = "malformed-invocation"
REASON_UNREADABLE_REVIEW_ROOT = "unreadable-review-root"
REASON_BRANCH_UNRESOLVABLE = "branch-unresolvable"
REASON_BRANCH_SLUG_EMPTY = "branch-slug-empty"
REASON_BRANCH_SLUG_ESCAPES = "branch-slug-escapes-review-root"
REASON_UNREADABLE_DIRECTORY = "unreadable-directory"
REASON_UNREADABLE_AGGREGATE = "unreadable-aggregate"
REASON_INTERNAL_ERROR = "internal-error"

# Aggregate discrimination markers. The §4.0.5 fence routes ok-vs-degraded on this helper's exit
# code and then classifies partial-vs-failed from these strings, so keep the per-root failed
# breadcrumb's fixed text free of both substrings or a per-root line misclassifies the run.
MARKER_PARTIAL = "devflow: discovery partial:"
MARKER_FAILED = "devflow: discovery failed:"


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8, idempotently and defensively. Called from
    the CLI entry path only (not at import) so importing this module for unit
    tests never mutates the importer's global streams. The guard tolerates a
    stream replaced with a non-`TextIOWrapper` (e.g. a test's `io.StringIO`),
    which has no `reconfigure` (issue #222)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _raise(err):
    # os.walk's onerror: re-raise so an unreadable subtree surfaces as a `failed`
    # classification instead of being silently skipped (the #555 silent-loss shape).
    raise err


def _posix(path):
    """Render a filesystem path in POSIX separator form.

    Extracted so the suite can drive it directly: on a POSIX host `os.sep` is
    already "/", so exercising this through the walk is an identity and any
    assertion over it passes for the wrong reason. The contract exists for the
    native-Windows python3 host (#275), so the only non-vacuous test is one that
    drives the separator — which needs this as a callable, not an inline expression.
    """
    return path.replace(os.sep, "/")


def _depth_below(root, dirpath):
    # Number of path segments `dirpath` lies below `root`. The root itself is 0.
    rel = os.path.relpath(dirpath, root)
    if rel == os.curdir:
        return 0
    return rel.count(os.sep) + 1


def classify_root(root):
    """Classify one candidate root. Returns (status, matches) where status is
    one of 'ok' / 'absent' / 'failed' and matches is a list of POSIX-form paths
    to non-empty deferrals.json files exactly two levels below the root."""
    if not os.path.exists(root):
        return "absent", []
    # A non-directory root (a regular file supplied where a directory was
    # expected — the deterministic ENOTDIR shape) is a traversal failure, not an
    # empty `ok`: os.walk over a regular file yields nothing silently, which would
    # misclassify it `ok`. Catch it explicitly.
    if not os.path.isdir(root):
        # EVERY `failed` classification breadcrumbs the root and the reason — this arm
        # raises no OSError, so without its own write it would be the one failure the
        # operator cannot attribute to a root.
        sys.stderr.write(
            "devflow: discovery: root %s failed traversal (not a directory)\n"
            % os.path.abspath(root)
        )
        return "failed", []
    matches = []
    try:
        for dirpath, dirnames, filenames in os.walk(root, onerror=_raise):
            # Files exactly two levels below root live in directories exactly one
            # level below root (`<root>/<run-id>/`). Prune deeper descent for speed
            # and to keep the depth-2 contract exact.
            depth = _depth_below(root, dirpath)
            if depth >= 2:
                dirnames[:] = []
                continue
            if depth != 1:
                continue
            if MANIFEST_NAME in filenames:
                candidate = os.path.join(dirpath, MANIFEST_NAME)
                # getsize can itself raise OSError (a file vanishing mid-walk) —
                # that is a traversal failure of this root, handled by the except.
                if os.path.getsize(candidate) > 0:
                    matches.append(_posix(candidate))
    except OSError as exc:
        sys.stderr.write(
            "devflow: discovery: root %s failed traversal (%s)\n"
            % (os.path.abspath(root), exc)
        )
        return "failed", []
    return "ok", matches


def _derive_branch_slug(branch):
    """Port the §4.0.5 fence's `tr '/' '-' | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9._-'`
    chain into Python, so this mode's search directories do not depend on `tr` — a tool
    the project's preflight does not guarantee, whose absence empties the slug and drops
    the branch-slug candidate. The fence tolerates that with a breadcrumb because filing
    is best-effort; a gate cannot, because the dropped candidate is the sole source on a
    first entry (guard-class 2).

    The case fold is an explicit ASCII A–Z shift rather than str.lower(), and the two do
    NOT agree: str.lower() maps some non-ASCII characters INTO the keep-set, so a branch
    named with U+212A KELVIN SIGN slugs to `k` under str.lower() and to nothing under the
    fence's `tr` in the C locale — a non-empty slug pointing at a directory no producer
    writes. The explicit shift is what keeps the port byte-equivalent to the chain.
    """
    out = []
    for ch in branch.replace("/", "-"):
        if "A" <= ch <= "Z":
            ch = chr(ord(ch) + 32)
        if ch in _SLUG_KEEP:
            out.append(ch)
    return "".join(out)


def _slug_escapes_review_root(review_root, slug):
    """True when joining `slug` onto `review_root` resolves outside it.

    The keep-filter above passes `.` and `-`, so a slug of `..` would point the branch
    candidate at the review root's parent and a slug of `.` at the root itself; both are
    rejected. Git will not create a branch named `..`, so this is defence in depth over a
    `_resolve_current_branch` return value nothing else in this file constrains — not a
    shape reachable from an ordinary checkout.

    `scripts/issue-audit-state.py` guards the same hazard for its own slugs with a
    `[A-Za-z0-9][A-Za-z0-9._-]*` full-match; the two are separate stdlib-only CLIs with no
    shared module, so this is a sibling to find when hardening, not a call to make.
    """
    base = os.path.normpath(review_root)
    candidate = os.path.normpath(os.path.join(base, slug))
    return not candidate.startswith(base + os.sep)


# Sentinel distinguishing "git answered, and the answer is no branch" from "git could
# not be asked". They must not collapse: on a FIRST entry there is no aggregate yet, so
# a branch-mode /prflow:review-and-fix run's manifest lives ONLY under the branch slug —
# the branch candidate is the sole evidence there, not a redundant second look. Reading a
# git failure as a detached HEAD would search the PR slug alone and report `absent`,
# stranding exactly the findings this predicate exists to protect.
BRANCH_UNRESOLVABLE = object()


def _resolve_current_branch():
    """The checked-out branch name, "" for a detached HEAD, or BRANCH_UNRESOLVABLE.

    Only git answering successfully with empty output is the benign detached-HEAD case.
    Every failure — a non-zero git (a corrupt repository, a `dubious ownership`
    safe.directory refusal, an unreadable HEAD), git absent from PATH, a matcher refusal,
    a timeout — returns the sentinel, which the caller routes to `unestablished`. git's
    own stderr is breadcrumbed rather than discarded, so an operator can attribute the
    stop instead of reading a clean `absent`.
    """
    try:
        proc = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        sys.stderr.write(
            "devflow: presence: could not run git to resolve the current branch (%s)\n"
            % exc
        )
        return BRANCH_UNRESOLVABLE
    if proc.returncode != 0:
        sys.stderr.write(
            "devflow: presence: git branch --show-current exited %d: %s\n"
            % (proc.returncode, (proc.stderr or "").strip())
        )
        return BRANCH_UNRESOLVABLE
    return proc.stdout.strip()


def _probe_review_root():
    """Classify REVIEW_ROOT as 'missing' / 'ok' / 'failed'.

    `os.path.isdir` swallows every OSError, so a mode-000 ancestor, a stale mount, or an
    EIO all read False — identical to a genuinely missing root. Reading those as missing
    would classify an unreadable tree `absent`, which is the issue-#555 silent-loss shape
    reintroduced one level above the guard that closed it. One guarded `stat` separates
    the three, and only a genuinely missing root takes the cheap skip.
    """
    try:
        st = os.stat(REVIEW_ROOT)
    except FileNotFoundError:
        return "missing"
    except OSError as exc:
        sys.stderr.write(
            "devflow: presence: review root %s could not be inspected (%s)\n"
            % (os.path.abspath(REVIEW_ROOT), exc)
        )
        return "failed"
    import stat as _stat
    if not _stat.S_ISDIR(st.st_mode):
        sys.stderr.write(
            "devflow: presence: review root %s exists but is not a directory\n"
            % os.path.abspath(REVIEW_ROOT)
        )
        return "failed"
    return "ok"


def _probe_aggregate(agg_path):
    """Classify the slug-level aggregate as 'absent' / 'ok' / 'failed'.

    One guarded `stat`, not an `exists`/`isfile`/`getsize` chain: `os.path.exists`
    suppresses EACCES, ELOOP and EIO alike, so a hydrated aggregate under a
    tightened-mode directory would read `absent` on the very re-entry where it is the
    only surviving source. A zero-byte file classifies `absent` — the discovery mode
    matches only files of non-zero size, so an empty aggregate holds nothing either.
    """
    try:
        st = os.stat(agg_path)
    except FileNotFoundError:
        return "absent"
    except NotADirectoryError:
        # The slug directory is not a directory, so no file can exist at this path. The
        # fault is real but it is the DIRECTORY's, and `classify_root` already reports it
        # as `failed`; attributing it to the aggregate here would route the run to a
        # reason token naming the wrong operand. Both still exit 2 — only which operand
        # the stub's reflection names changes.
        return "absent"
    except OSError as exc:
        sys.stderr.write(
            "devflow: presence: aggregate %s could not be inspected (%s)\n"
            % (os.path.abspath(agg_path), exc)
        )
        return "failed"
    import stat as _stat
    if not _stat.S_ISREG(st.st_mode):
        # Breadcrumbed like every other `failed` classification in this file (the
        # convention classify_root states), so the operator sees the reason and not only
        # the path the `root:` line names.
        sys.stderr.write(
            "devflow: presence: aggregate %s exists but is not a regular file\n"
            % os.path.abspath(agg_path)
        )
        return "failed"
    return "ok" if st.st_size > 0 else "absent"


def _print_presence_unestablished(reason, root=None):
    """The single owner of presence mode's `unestablished` line's format.

    Every fail-closed exit routes through here, mirroring `workpad.py`'s
    `_print_unestablished`, so the token the phase-file stub quotes back into its
    reflection cannot drift between call sites. Returns the exit code rather than
    exiting, so `main` keeps one return path and the suite can drive it in-process.
    """
    sys.stdout.write("unestablished: reason=%s\n" % reason)
    if root is not None:
        sys.stdout.write("root: %s\n" % os.path.abspath(root))
    return 2


def cmd_presence(rest):
    """Answer whether a deferred review finding is present for the PR named in `rest`.

    Wrapped by `_run_presence` so no exit path can escape the three-state contract.
    """
    # Arity and type first, before any filesystem or git work: a malformed call must
    # not be able to produce a partial roots-echo that reads like a real search.
    # `isascii()` is load-bearing: `str.isdigit()` is Unicode-aware, so a superscript or
    # Devanagari digit would pass arity/type validation, compose a search directory no
    # producer ever writes, and report `absent` — the one answer this mode must never
    # reach by accident.
    if len(rest) != 1 or not (rest[0].isascii() and rest[0].isdigit()):
        sys.stderr.write(
            "devflow: presence: usage: discover-deferral-manifests.py %s N\n"
            % PRESENCE_FLAG
        )
        return _print_presence_unestablished(REASON_MALFORMED_INVOCATION)
    pr_number = rest[0]

    slug_dir = "%s/pr-%s" % (REVIEW_ROOT, pr_number)
    agg_path = "%s/%s" % (slug_dir, MANIFEST_NAME)
    candidates = [slug_dir]

    # A genuinely missing review root can hold nothing, so the branch derivation — and
    # the git subprocess it costs — is skipped on that path, which is the common shape on
    # the runs this predicate exists to make cheap. A root that exists but cannot be
    # inspected is NOT that case and stops here rather than reading as absent.
    root_state = _probe_review_root()
    if root_state == "failed":
        return _print_presence_unestablished(REASON_UNREADABLE_REVIEW_ROOT, REVIEW_ROOT)
    if root_state not in ("ok", "missing"):
        # Every arm is enumerated, so a value that is neither is a defect in this file
        # rather than a state of the tree. Falling through would silently take the
        # PR-slug-only search — the shape that strands a first entry's findings — so the
        # unrecognized value fails closed instead.
        return _print_presence_unestablished(REASON_INTERNAL_ERROR)
    if root_state == "ok":
        branch = _resolve_current_branch()
        if branch is BRANCH_UNRESOLVABLE:
            # The branch candidate is the sole source on a first entry, so a branch that
            # could not be resolved leaves the answer unestablished rather than absent.
            return _print_presence_unestablished(REASON_BRANCH_UNRESOLVABLE)
        branch_slug = _derive_branch_slug(branch)
        if branch and not branch_slug:
            # A branch that exists but whose every character the keep-filter drops leaves
            # the branch candidate unformable. The filing fence falls back to pr-<N>-only
            # with a breadcrumb because it is best-effort; this predicate is a GATE, and
            # an unsearchable sole-source candidate is an answer it could not establish,
            # not an absence.
            sys.stderr.write(
                "devflow: presence: branch %r derives an empty slug (every character is "
                "outside [a-z0-9._-]); the branch candidate cannot be formed\n" % branch
            )
            return _print_presence_unestablished(REASON_BRANCH_SLUG_EMPTY)
        if branch_slug:
            if _slug_escapes_review_root(REVIEW_ROOT, branch_slug):
                # A branch name whose slug leaves the review root is a broken input, not
                # a normal one; dropping its evidence silently would be the absent-shaped
                # answer this mode must not reach by accident.
                sys.stderr.write(
                    "devflow: presence: branch slug %r would resolve outside %s\n"
                    % (branch_slug, os.path.abspath(REVIEW_ROOT))
                )
                return _print_presence_unestablished(
                    REASON_BRANCH_SLUG_ESCAPES, REVIEW_ROOT
                )
            branch_dir = "%s/%s" % (REVIEW_ROOT, branch_slug)
            if branch_dir != slug_dir:
                candidates.append(branch_dir)

    # Reuse the discovery mode's own traversal, so the depth-2 and non-zero-size rules
    # this predicate answers on are the same rules the filing fence then files from.
    results = []
    present = 0
    for root in candidates:
        # Pre-probe with a guarded stat. `classify_root` is shared with discovery mode —
        # whose per-root classification this change holds fixed — and reaches its verdict
        # through `os.path.exists`/`os.path.isdir`, both of which suppress every OSError:
        # an ELOOP, EIO or stale mount on a candidate would classify `absent` and route
        # this gate to "skip the procedure" over a tree it could not read at all.
        try:
            os.stat(root)
        except FileNotFoundError:
            pass
        except OSError as exc:
            sys.stderr.write(
                "devflow: presence: candidate %s could not be inspected (%s)\n"
                % (os.path.abspath(root), exc)
            )
            return _print_presence_unestablished(REASON_UNREADABLE_DIRECTORY, root)
        status, matches = classify_root(root)
        results.append((root, status))
        present += len(matches)

    # The slug-level aggregate is a single file one level above the run-scoped
    # manifests, so the walk above never sees it. It is checked independently because
    # it is the ONLY surviving source once a prior entry has filed and consumed the
    # run-scoped manifests.
    agg_state = _probe_aggregate(agg_path)

    sys.stderr.write(
        "devflow: presence roots: %s aggregate %s=%s\n"
        % (" ".join("%s=%s" % (os.path.abspath(r), s) for r, s in results),
           os.path.abspath(agg_path), agg_state)
    )

    # The aggregate counts toward the reported total. Reporting it as `present: 0` on the
    # aggregate-only path would put the present line one glyph from the `absent: 0` line
    # that means the opposite — the present arm carries no line a caller matches on, but a
    # human reading the tool result would take the wrong signal.
    if agg_state == "ok":
        present += 1
    # Present wins over an unreadable sibling: a finding this mode positively saw is
    # not made less present by a directory it could not read, and both answers route
    # the caller to the same place.
    if present:
        sys.stdout.write("present: %d\n" % present)
        return 0
    if agg_state == "failed":
        return _print_presence_unestablished(REASON_UNREADABLE_AGGREGATE, agg_path)
    first_failed = next((r for r, s in results if s == "failed"), None)
    if first_failed is not None:
        return _print_presence_unestablished(REASON_UNREADABLE_DIRECTORY, first_failed)
    sys.stdout.write("absent: 0\n")
    return 1


def _run_presence(rest):
    """Run `cmd_presence` so that NO outcome can escape the three-state contract.

    CPython exits 1 on an uncaught exception, and 1 is this mode's `absent` — the one
    answer that means "skip the procedure". Without this wrapper a crash anywhere in the
    traversal would be read by the phase-file stub as "nothing was deferred", strand
    every acknowledged finding, and write no reflection, because the stub records one
    only on exit 2. `BaseException` rather than `Exception` so an interrupt lands on
    unestablished too; the traceback still reaches stderr for the operator.
    """
    try:
        return cmd_presence(rest)
    except BaseException:  # noqa: BLE001 - deliberate: see docstring
        # The recovery itself must not be able to re-raise: it writes, and if the original
        # fault WAS a stdout error the write raises again, escapes, and CPython exits 1 —
        # `absent`, the one answer this wrapper exists to make unreachable. Whatever the
        # writes do, the return value is 2.
        try:
            import traceback
            traceback.print_exc(file=sys.stderr)
        except BaseException:  # noqa: BLE001 - the return below is the contract
            pass
        try:
            _print_presence_unestablished(REASON_INTERNAL_ERROR)
        except BaseException:  # noqa: BLE001 - the return below is the contract
            pass
        return 2


def main(argv=None):
    _force_utf8_streams()
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == PRESENCE_FLAG:
        return _run_presence(args[1:])
    if not args:
        # Emit NO discovery marker here: a usage error is not a discovery outcome, and a marker
        # would make the fence's after-fence classification read it as a real partial run.
        sys.stderr.write(
            "devflow: discovery: usage: discover-deferral-manifests.py ROOT [ROOT ...]\n"
        )
        return 2

    results = []          # (root, status)
    all_matches = set()
    for root in args:
        status, matches = classify_root(root)
        results.append((root, status))
        all_matches.update(matches)

    # Roots-echo: name every root's ABSOLUTE path (os.path.abspath — normalized,
    # NOT symlink-resolved) and classification on every run that reaches here, so
    # an `absent`-classified root is observable in the fence's own tool result, which the
    # caller reads directly, rather than silent. The zero-arg
    # usage error returns above, before any root exists to echo.
    echo = " ".join(
        "%s=%s" % (os.path.abspath(root), status) for root, status in results
    )
    sys.stderr.write("devflow: discovery roots: %s\n" % echo)

    # stdout: sorted, de-duplicated, POSIX-form. Printed even on a partial run —
    # output production must NOT be able to alter the exit status below.
    for path in sorted(all_matches):
        sys.stdout.write(path + "\n")

    failed = sum(1 for _, s in results if s == "failed")
    total = len(results)
    if failed == 0:
        return 0
    if failed == total:
        sys.stderr.write(
            "%s all %d candidate root(s) failed traversal.\n" % (MARKER_FAILED, total)
        )
        return 4
    sys.stderr.write(
        "%s %d of %d candidate root(s) failed traversal; discovered manifests printed "
        "from the rest.\n" % (MARKER_PARTIAL, failed, total)
    )
    return 3


if __name__ == "__main__":
    sys.exit(main())
