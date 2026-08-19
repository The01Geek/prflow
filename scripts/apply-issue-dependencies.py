#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Best-effort post-creation stamp: register an issue's declared `## Dependencies`
prerequisites as GitHub-native blocked-by dependencies (issue #1011).

This is the third member of the best-effort post-creation REST-stamp family, and
it mirrors `scripts/ensure-label.sh` / `scripts/apply-labels.sh` clause for clause:

  * it ALWAYS exits 0 — a failed body fetch, an unresolvable prerequisite, an API
    rejection, a missing/non-numeric argument, and a failed recognizer import all
    breadcrumb and exit 0, so a registration hiccup can never abort or reverse the
    creation it runs after;
  * it HAS NO SILENT PATH — every path its own code can reach writes a
    `apply-issue-dependencies.py:`-prefixed stderr breadcrumb before returning, so
    a caller reading the tool result can tell "registered", "API failure",
    "arg-slip" and "the harness refused the command" (no output at all) apart;
  * it takes ONLY the created issue's number, fetching that issue's body from
    GitHub itself, so both call sites invoke it operand-free with just the number;
  * it derives prerequisite numbers by importing the section-scoped extraction
    function from `scripts/preflight.py` — it defines no second recognizer, no
    second regex, and no second declaration vocabulary. It imports the
    `(found, skipped)` accessor (`dependency_section_scan`, issue #1268) so a
    number the recognizer dropped for OUTBOUND direction is named under this
    helper's own prefix rather than dropped silently or misdescribed as "no
    prerequisites"; the recognizer's section-only path still writes no stderr of
    its own. The import is guarded so a partial-copy deployment (an
    absent/unreadable sibling) breadcrumbs and exits 0 rather than raising at
    module load, before any handler exists.

The registered set is deliberately NARROWER than the reversible implement gate's:
only prerequisites declared INSIDE the `## Dependencies` section register, because a
blocked-by relationship is a persistent GitHub write this change does not remove,
whereas a false positive in the read-only implement gate costs only a human
override. A declared number that resolves to a pull request, or that equals the
issue's own number, is skipped.

The POST body parameter is `issue_id` (the blocker's database id, NOT its number),
sent through `gh api`'s typed-field flag `-F` because the documented type is
integer. Each declared number is processed independently — a failure on one
breadcrumbs and continues to the next — and the final breadcrumb states how many
linked, how many were already linked, and names each one that failed.
"""

import json
import os
import re
import subprocess
import sys

PREFIX = "apply-issue-dependencies.py"
# The repository's Python gh-caller convention (issue #245): honour an explicit
# DEVFLOW_GH override, else the bare `gh`. Deliberately WITHOUT the resolve-gh.sh
# execution probe — a `.sh` cannot be sourced into Python on Windows, and the
# other Python gh-callers (workpad.py, file-deferrals.py, …) read it this way.
GH = os.environ.get("DEVFLOW_GH") or "gh"

# GitHub's 422 body for an ALREADY-registered blocked_by dependency carries the
# validation message "Target issue has already been taken" (probed against a real
# duplicate registration on this repository, issue #1011). Match on that token
# rather than on a bare HTTP 422 — a 422 for a DIFFERENT validation reason (e.g.
# "Target issue may only be an issue") must route to the failure breadcrumb, not
# be swallowed as benign — mirroring the decided `already_exists` semantics
# `scripts/ensure-label.sh` states.
_DUPLICATE_TOKEN = re.compile(r"already been taken", re.IGNORECASE)
_HTTP_STATUS = re.compile(r'(?:"status"\s*:\s*"(\d{3})"|\(HTTP (\d{3})\))')


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8 on the CLI entry path only (not at import, so a
    unit-test import never mutates the importer's streams). A no-op where the ambient
    codec is already UTF-8; self-defends against a non-UTF-8 default codec such as
    Windows cp1252. Tolerates a non-TextIOWrapper stream (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _err(message: str) -> None:
    """Emit one helper-prefixed stderr breadcrumb — the ONLY output surface."""
    print(f"{PREFIX}: {message}", file=sys.stderr)


def _gh(args: list[str]) -> tuple[int, str, str]:
    """Run `gh <args>`; return (returncode, stdout, stderr). Never raises.

    An OSError launching gh (the binary is absent entirely) is folded into the
    same shape as a non-zero exit — returncode 127 with the launch error on
    stderr — so every caller reads one contract.
    """
    try:
        result = subprocess.run(
            [GH, *args], capture_output=True, encoding="utf-8", errors="replace"
        )
        return result.returncode, result.stdout, result.stderr
    except OSError as exc:
        return 127, "", str(exc)


def _api_message(*streams: str) -> str:
    """The API's own error message from a gh error body, else a trimmed fallback."""
    for stream in streams:
        try:
            payload = json.loads(stream)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("message"), str):
            return payload["message"].strip()
    joined = " ".join(s.strip() for s in streams if s and s.strip())
    return joined.strip()


def _http_status(*streams: str) -> str | None:
    """The HTTP status a gh error carries, from the JSON body or the `(HTTP nnn)`."""
    for stream in streams:
        match = _HTTP_STATUS.search(stream or "")
        if match:
            return match.group(1) or match.group(2)
    return None


def _register(issue: str, numbers: list[str]) -> int:
    linked: list[str] = []
    already: list[str] = []
    failed: list[str] = []
    posts_attempted = 0
    # POST refusals are buffered so a run in which EVERY registration attempt was
    # refused with the SAME status collapses to one breadcrumb naming that status,
    # rather than emitting one warning per declared prerequisite (an environment
    # where the endpoint is uniformly refused would otherwise be very noisy).
    refusals: list[dict[str, str]] = []

    for number in numbers:
        if number == issue:
            _err(f"skipped #{number}: it is issue #{issue}'s own number, not a prerequisite.")
            continue

        rc, out, err = _gh(["api", "repos/{owner}/{repo}/issues/" + number])
        if rc != 0:
            failed.append(number)
            _err(
                f"skipped #{number}: it does not resolve to an issue id "
                f"({_api_message(out, err) or 'gh failed'})."
            )
            continue
        try:
            payload = json.loads(out)
        except (json.JSONDecodeError, TypeError):
            failed.append(number)
            _err(f"skipped #{number}: its resolved payload could not be parsed as JSON.")
            continue
        if isinstance(payload, dict) and "pull_request" in payload:
            _err(f"skipped #{number}: it resolves to a pull request, not an issue.")
            continue
        blocker_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(blocker_id, int):
            failed.append(number)
            _err(f"skipped #{number}: its resolved payload carries no numeric issue id.")
            continue

        posts_attempted += 1
        rc, out, err = _gh([
            "api", "--method", "POST",
            "repos/{owner}/{repo}/issues/" + issue + "/dependencies/blocked_by",
            "-F", f"issue_id={blocker_id}",
        ])
        if rc == 0:
            linked.append(number)
            _err(f"linked #{issue} blocked_by #{number}.")
        elif _DUPLICATE_TOKEN.search(f"{out}\n{err}"):
            already.append(number)
            _err(f"#{issue} was already blocked_by #{number}; nothing to do.")
        else:
            failed.append(number)
            refusals.append({
                "number": number,
                "status": _http_status(out, err) or "",
                "message": _api_message(out, err) or "no message",
            })

    # Collapse a uniformly-refused run; otherwise emit each refusal individually.
    # "Uniform" is keyed on the (status, message) PAIR, not the status alone: two
    # 422s can carry different validation messages, and collapsing on status would
    # print refusals[0]'s message while naming both numbers — misattributing the
    # second's cause. Same status + differing message falls to the per-item branch.
    signatures = {(r["status"], r["message"]) for r in refusals}
    if len(refusals) >= 2 and len(refusals) == posts_attempted and len(signatures) == 1:
        status, message = next(iter(signatures))
        status = status or "unknown"
        names = " ".join(f"#{r['number']}" for r in refusals)
        _err(
            f"every declared prerequisite's registration was refused with the same "
            f"status (HTTP {status}): {message}; registered no "
            f"dependency on #{issue} ({names})."
        )
    else:
        for refusal in refusals:
            status = f"HTTP {refusal['status']}" if refusal["status"] else "no status"
            _err(
                f"could not link #{issue} blocked_by #{refusal['number']} "
                f"(API refused, {status}: {refusal['message']})."
            )

    failed_clause = (
        f"; failed: {' '.join('#' + n for n in failed)}" if failed else ""
    )
    _err(
        f"done for #{issue}: {len(linked)} linked, {len(already)} already linked, "
        f"{len(failed)} failed{failed_clause}."
    )
    return 0


def main(argv: list[str]) -> int:
    _force_utf8_streams()
    # Fail-closed arg guard, mirroring apply-labels.sh: a missing/empty/non-numeric
    # number (including the word-split arg-slip a `$PR_NUM` that did not survive
    # produces) breadcrumbs that it is a caller arg-slip — NOT a harness denial —
    # and exits 0, so a refusal stays the ONLY silent outcome.
    number = argv[0] if len(argv) == 1 else ""
    # isascii()-guarded, matching the repo's hardened numeric idiom
    # (build-experiment-records.py / workpad.py): a bare isdigit() accepts
    # non-ASCII digit codepoints, which are not valid GitHub issue numbers.
    if not number or not (number.isascii() and number.isdigit()):
        _err(
            f"missing or non-numeric issue-number argument (args: {argv}); no "
            f"dependency registered. This is NOT a harness denial — it is a caller "
            f"arg-slip (an empty/absent number, or a shell variable that did not "
            f"survive into this command)."
        )
        return 0

    # Guarded recognizer import — inside a handler, never at module load, so an
    # absent/unreadable sibling in a partial-copy deployment breadcrumbs and exits
    # 0 rather than raising before any handler exists.
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from preflight import dependency_section_scan, malformed_reserved_dependency_heading
    except Exception as exc:  # noqa: BLE001 - best-effort: any import failure exits 0
        _err(
            f"could not import the dependency recognizer from scripts/preflight.py "
            f"({type(exc).__name__}: {exc}); no dependency registered."
        )
        return 0

    rc, body, err = _gh(["api", "repos/{owner}/{repo}/issues/" + number, "--jq", ".body"])
    if rc != 0:
        _err(
            f"could not fetch issue #{number}'s body "
            f"({_api_message(body, err) or 'gh failed'}); no dependency registered."
        )
        return 0

    # Guarded like the import and the _gh calls above: the always-breadcrumb /
    # always-exit-0 contract holds even if the cross-module recognizer ever raises
    # on a fetched body (it does not today — str.splitlines() + regex — but that is
    # an implicit property of a sibling reached across the partial-copy-tolerant
    # import, not a guarantee this file controls).
    try:
        numbers, skipped = dependency_section_scan(body)
        malformed = malformed_reserved_dependency_heading(body)
    except Exception as exc:  # noqa: BLE001 - best-effort: any recognizer failure exits 0
        _err(
            f"the dependency recognizer failed on issue #{number}'s body "
            f"({type(exc).__name__}: {exc}); no dependency registered."
        )
        return 0

    # A malformed reserved heading is unknown, not zero: breadcrumb it rather than
    # falling through to the "declares no prerequisites" summary, which would assert
    # a confirmed empty set the recognizer never established.
    if malformed is not None:
        _err(
            f"issue #{number}'s reserved leading dependency section is spelled "
            f"`{malformed} Dependencies`, not the canonical `## Dependencies` "
            f"(Markdown level two); no dependency registered — restate it as "
            f"`## Dependencies` to register its prerequisites."
        )
        return 0

    # A number dropped for OUTBOUND direction is now visible (issue #1268): the
    # recognizer skipped it silently, so this helper — not the recognizer, whose
    # section-only entry point keeps its no-stderr contract — names each skip under
    # its own prefix on BOTH the every-entry-dropped and some-dropped-some-kept
    # paths, so the "no silent path" docstring contract holds again.
    for dropped in skipped:
        _err(
            f"skipped #{dropped}: its `## Dependencies` line reads as an OUTBOUND "
            f"relation (this issue is the prerequisite, not blocked by #{dropped}); "
            f"no blocked_by registered — if #{dropped} must land first, restate it "
            f"on its own line as `blocked by #{dropped}`."
        )

    if not numbers:
        if skipped:
            # Do NOT claim the issue declared no prerequisites — it declared one (or
            # more) that were skipped for direction. The per-skip breadcrumbs above
            # name the numbers; this summary names the reason.
            _err(
                f"issue #{number} declares its `## Dependencies` prerequisite(s) only "
                f"as OUTBOUND relations (all skipped for direction — see above); no "
                f"dependency registered."
            )
        else:
            _err(
                f"issue #{number} declares no prerequisites in a `## Dependencies` "
                f"section; no dependency registered."
            )
        return 0

    return _register(number, numbers)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
