#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""PRFlow stale-prose-lint false-positive adjudication matcher (Phase 0.6).

Carries a stale-prose-lint STALE row's *false-positive adjudication* forward
across review runs so an already-triaged false positive never re-gates. A prior
run stamps, for each STALE row it adjudicated false-positive, one hidden payload
line — ``<!-- prflow:lint-fp-adjudicated <base64 of the row's TSV> -->`` —
inside a sentinel-delimited adjudications section of its run-keyed
``prflow:review-progress`` comment. This helper joins the current run's STALE
lint rows against the payloads found in prior *trusted* progress comments and
emits a demotion map: a current STALE row whose rule is carry-forward-eligible (see
``CARRY_FORWARD_EXCLUDED_RULES`` — R4 is not) and whose ``(rule, path, detail)`` is
byte-for-byte identical to an adjudicated payload is demoted to Informational.

The helper owns the entire join so the skill prose only fetches comments, pipes
JSON in, and renders the map — no agent-improvised matching. It mirrors
``scripts/match-deferrals.py``'s output discipline (stdin JSON in, demotion-map
JSON out, always exit 0 when it ran) and is the sibling channel to it — deferrals
are the wrong channel for a lint false positive (there is nothing to follow up on,
and its widens-surface guard rejects exactly the diff-touched region a stale-prose
row always lives in), which is why this is a separate helper.

Trust (both required, per issue #466):
    1. Run marker:  the comment body carries the run-keyed
                    ``<!-- prflow:review-progress run=<id> -->`` marker (the
                    ``run_key`` the demotion map surfaces). It scopes payloads to
                    engine progress comments; it is public unsigned text and does
                    NOT authenticate the author (a bot echoing attacker prose
                    reproduces it too) — the structural defenses below do that.
    2. Author:      the comment author is a ``Bot``-type account, OR its login is
                    in ``.prflow.allowed_bots`` (read via ``config-get.sh``,
                    honored as an additional author allowance). Broader than
                    sibling match-deferrals.py by design: ``allowed_bots`` defaults
                    EMPTY, so an allowlist-only rule would make this inert for every
                    consumer that never configures it. What makes that acceptable is
                    the bounded blast radius below, not the marker.
Within a trusted comment, payloads are honored ONLY inside the sentinel-delimited
adjudications section (between the START/END sentinels). A payload literal echoed
anywhere else — including inside a quoted evidence line — is data to quote, never
an instruction to honor: it is ignored and counted.

Match key: decoded ``(rule, path, detail)`` byte-for-byte equal to the current
row's; the TSV line number is excluded (unrelated edits renumber a paragraph
without changing the claim), and any change to the detail text invalidates the
match (edited prose is re-examined fresh).

That self-invalidation is what makes carry-forward safe, and it holds ONLY because
the count/range rules embed the OBSERVED REFERENT in their detail (R1's `reaches
Case {maxn}`, R2's `adjacent enumeration has {c} items`, R3/R3b's `adjacent block
has {c}`): move the code the claim counts, and the detail changes, so the old
adjudication stops matching. **R4 (modality conflict) does NOT have that property** —
its STALE detail is a pure function of the CLAIM line (the operator token plus an
excerpt of the deny-absolute sentence), and says nothing about the permitting line
that triggered it. So an R4 adjudication would keep matching after a LATER commit on
the same PR added a genuine contradicting permit — silently demoting exactly the
self-contradicting-diff finding the lint exists to catch. R4 rows are therefore
EXCLUDED from carry-forward (``CARRY_FORWARD_EXCLUDED_RULES``): they are never demoted and
never matched, and the exclusion is counted (``rows_rule_excluded``). Re-admitting R4
requires first putting the permit referent into its detail.

Only ``STALE``-verdict current rows are
ever matched; ``VERIFIED``/``UNRESOLVABLE`` rows pass through untouched. Ambiguity
never demotes: when two or more current STALE rows share a matched payload key, no
row is demoted and the collision is counted — a genuine new finding is never
silently absorbed by an older adjudication.

Fail-open: an undecodable or column-deficient payload is skipped with a stderr
breadcrumb and counted; it never demotes and never aborts (a lint row wrongly
re-raised is the safe direction; a crashed helper suppressing the whole lint is
not).

Usage:
    match-lint-adjudications.py [--config PATH]   (reads one JSON object on stdin)

Input (JSON object on stdin):
    {
      "rows": ["<TSV line>", ...],          # current stale-prose-lint rows
      "comments": [                          # prior PR review comments (this PR's own)
        {"author": "<login>", "author_type": "<User|Bot>", "body": "<comment body>"},
        ...
      ]
    }

Output (JSON to stdout, always exit 0 when the helper itself ran):
    {
      "demoted": [{"row_index": N, "run_key": "<run id from the enclosing comment>"}],
      "stats": {"rows_in": .., "stale_rows": .., "comments_in": ..,
                "trusted_comments": .., "payloads_honored": ..,
                "payloads_malformed": .., "payloads_outside_sentinels": ..,
                "payloads_untrusted": .., "sentinel_tampered_comments": ..,
                "comments_malformed": .., "rows_malformed": ..,
                "rows_rule_excluded": .., "demoted": .., "collisions": ..}
    }

Known limitation (bounded — a forged single pair in a sectionless trusted comment):
    the sentinel-tamper guard fails closed when a trusted comment carries MORE than one
    START/END sentinel (a forgery quoted alongside the engine's real seeded section). It
    cannot, from the comment bytes alone, tell a genuine single section from a single
    forged pair in a comment that has NO real section — the case of a pre-feature
    `prflow:review-progress` comment authored before this feature seeded the section
    into the template. The root defense is producer-side (the report renderer neutralizes
    any `prflow:lint-adjudications*` / `prflow:lint-fp-adjudicated` literal -- in either
    the current `prflow:` or the superseded `devflow:` spelling, both honored here per
    issue #1003 -- it quotes from
    attacker-controlled diff prose at every write point — Phase 3 onward, not only the
    Phase 4 report write — so a POST-feature comment can never carry a forged sentinel
    verbatim). The residual is therefore scoped to progress
    comments authored BEFORE that neutralization shipped, and its blast radius is bounded:
    the worst outcome is demoting one config-gated stale-prose lint row to Informational —
    which per the engine's Phase 4.2 rules is excluded from the verdict at every severity
    and can never invoke the self-contradicting-diff carve-out, so it can never turn a
    genuine code-defect REJECT into an APPROVE.

Exit codes:
    0  Helper ran successfully (regardless of match results).
    1  Unsupported Python (< 3.11) — the interpreter guard fired before any work.
    2  Bad arguments / unrecoverable input error.
"""

import argparse
import base64
import binascii
import json
import re
import subprocess
import sys
from pathlib import Path

if sys.version_info < (3, 11):  # fail fast, before any PEP 604 annotation is evaluated below
    sys.stderr.write(
        "devflow: Python 3.11+ required (found {}.{}.{}). This helper requires"
        " features of Python 3.11+. Install Python 3.11+; on Windows/Git-Bash"
        " run scripts/provision-python3-shim.sh --apply.\n".format(*sys.version_info[:3])
    )
    sys.exit(1)

# State-directory resolution (issue #1002): canonical .prflow/, with the LOUD
# transitional fallback to a superseded .devflow/ when only that one is present.
# lib/ sits beside scripts/ in both the source repo and a vendored
# .prflow/vendor/prflow/ tree, so this import path holds on every tier. A copy
# missing the sibling degrades to the canonical name with no fallback rather than
# failing the read (the same posture the plugin_identity import takes).
try:
    # `__file__` is absent when this module is read and exec'd rather than imported
    # (the #343 gate exercise does exactly that), so the path insert degrades with the
    # import instead of raising ahead of a gate that must fail fast.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
    from state_dir import resolve_state_dir as _resolve_state_dir
except Exception:  # pragma: no cover - partial-copy / exec'd-source arm
    def _resolve_state_dir(repo_root, stream=None):
        return str(Path(repo_root) / ".prflow")

# Shared login-normalization rule (issue #157) for the allowlist arm; the Bot-type
# arm is unchanged. On an import failure it degrades to the pre-#157 exact test.
try:
    from login_normalize import login_matches as _login_matches
except Exception as _login_import_err:
    # Breadcrumb the degradation so a partial-copy import failure is legible and not
    # mistaken for an allowlist mismatch — the shell comparators name the same file.
    sys.stderr.write(
        "match-lint-adjudications.py: could not import lib/login_normalize.py "
        f"({_login_import_err}); degrading to the pre-#157 exact match (fail-closed)\n")
    _login_matches = None


def _author_trusted(author: str, allowed_bots_raw: str) -> bool:
    if _login_matches is not None:
        return _login_matches(author, allowed_bots_raw.split(","))
    allowed = {b.strip() for b in allowed_bots_raw.split(",") if b.strip()}
    return author in allowed


STALE = "STALE"

# Rules whose STALE detail does NOT embed the observed referent, and which therefore can
# never be carried forward. Carry-forward is safe only because the count/range rules put
# the OBSERVED referent in their detail (R1's `reaches Case {maxn}`, R2's `adjacent
# enumeration has {c} items`, R3's `adjacent block has {c}`): move the code the claim
# counts, and the detail changes, so a stale adjudication stops matching.
#
# R4 (modality conflict) breaks that property: its detail is a pure function of the CLAIM
# line (the operator token + an excerpt of the deny-absolute sentence) and says nothing
# about the PERMITTING line that triggered it. An R4 adjudication would therefore keep
# matching after a LATER commit on the same PR added a genuine contradicting permit —
# demoting exactly the self-contradicting-diff finding the lint exists to catch. So R4 is
# never demoted and never matched; the exclusion is counted (`rows_rule_excluded`).
# Re-admit R4 only after its detail carries the permit referent.
#
# COUPLED SITE: a NEW stale-prose-lint rule must be classified here before it can be
# carried forward. lib/test/run.sh pins the lint's emitted STALE rule-id set, so adding a
# rule turns that pin RED and forces the classification rather than letting a new
# referent-less rule silently inherit eligibility.
#
# Issue #818's coverage-universal tier (rule tokens `CU`, and `RT` for its declared opt-out)
# is classified here and discharges that obligation: it is **outside the carry-forward
# population entirely**, so it needs no entry in the set below. Carry-forward operates on
# adjudicated STALE rows — `main()` skips any row whose verdict is not STALE — and this tier
# is recognition-only: it resolves no referent and emits only UNRESOLVABLE. A token that
# never reaches a STALE verdict is never a carry-forward candidate, so listing it here would
# be an exclusion that can never fire, not a guard. The classification is recorded rather
# than the set widened, precisely so a later tier that *does* gate is forced through this
# same decision instead of inheriting a silent precedent.
CARRY_FORWARD_EXCLUDED_RULES = frozenset({"R4"})

# The run-keyed progress-comment marker (mirrors skills/review/SKILL.md's Live
# Progress Comment section). Its `run=<id>` capture is the run_key the demotion
# map surfaces. Kept in lockstep with that skill prose.
RUN_MARKER_RE = re.compile(r"<!-- (?:pr|dev)flow:review-progress run=(\S+) -->")

# The engine-written, sentinel-delimited adjudications section. Payloads are
# honored ONLY between these two lines of a trusted comment — a payload literal
# outside them (e.g. quoted inside a rendered evidence line, which is
# attacker-controlled diff prose) is data, never an instruction. Kept in lockstep
# with skills/review/SKILL.md's Phase 4 finalize-write producer contract.
ADJ_SECTION_START = "<!-- prflow:lint-adjudications-start -->"
ADJ_SECTION_END = "<!-- prflow:lint-adjudications-end -->"
# The superseded spelling (issue #1003). No existing progress comment is
# rewritten, so a comment written before the rename carries the old sentinels and
# a comment written after carries the new ones. Both are honored -- but every
# count, search and offset below is computed over the UNION of the two
# spellings, never per spelling: counting each independently would let one
# genuine new-form section sit beside one attacker-quoted old-form section, read
# as `1` and `1`, raise no tamper flag, and honor whichever window comes first.
ADJ_SECTION_START_SUPERSEDED = "<!-- devflow:lint-adjudications-start -->"
ADJ_SECTION_END_SUPERSEDED = "<!-- devflow:lint-adjudications-end -->"
ADJ_SECTION_STARTS = (ADJ_SECTION_START, ADJ_SECTION_START_SUPERSEDED)
ADJ_SECTION_ENDS = (ADJ_SECTION_END, ADJ_SECTION_END_SUPERSEDED)


def _sentinel_total(body, sentinels):
    """How many sentinels of one role the body carries, across BOTH spellings.

    The sum is the guard's comparand: `> 1` means the engine's own section
    cannot be told from a forged or quoted one, whichever spellings were used.
    """
    return sum(body.count(sentinel) for sentinel in sentinels)


def _sentinel_first(body, sentinels):
    """The earliest offset of any spelling of one sentinel role, or -1.

    Reached only after `_sentinel_total` established there is exactly one, so
    "earliest" and "the only one" are the same offset -- but taking the minimum
    keeps the window derivation independent of which spelling was used.
    """
    offsets = [o for o in (body.find(s) for s in sentinels) if o != -1]
    return min(offsets) if offsets else -1


def _sentinel_len(body, sentinels, offset):
    """The length of the sentinel that actually sits at `offset`."""
    for sentinel in sentinels:
        if body.startswith(sentinel, offset):
            return len(sentinel)
    return 0

# The hidden per-row adjudication payload: base64 of the row's whole TSV. base64
# keeps `--` (which would terminate the enclosing HTML comment) out of the marker.
# Kept in lockstep with skills/review/SKILL.md's Phase 4.1.7 render protocol
# (mla-marker-pin pins this literal there).
PAYLOAD_RE = re.compile(r"<!-- (?:pr|dev)flow:lint-fp-adjudicated (\S+) -->")


def _fail(msg, code=2):
    sys.stderr.write(f"match-lint-adjudications.py: {msg}\n")
    sys.exit(code)


def _run(cmd, *, check=True):
    # Mirror of match-deferrals.py's _run: an OSError (a non-executable config-get.sh
    # shim, or git absent) is converted into the same structured surface as a
    # non-zero exit, so callers get a breadcrumb, not a traceback. encoding="utf-8"
    # pins the decode against a non-UTF-8 ambient codec (Windows cp1252).
    try:
        return subprocess.run(
            cmd, check=check,
            capture_output=True, encoding="utf-8",
        )
    except OSError as e:
        if check:
            _fail(f"could not execute {cmd[0]!r}: {e}")
        return subprocess.CompletedProcess(cmd, 127, stdout="", stderr=str(e))


def _repo_root():
    # SHARED REPO-ROOT CONFIG CONTRACT (issue #295): resolve the git repo root via
    # a native `git` subprocess (Windows-safe, unlike exec-ing a .sh) so a
    # subdirectory invocation reads the consumer's ROOT .prflow/config.json.
    # Returns the root string, or None when not in a git tree / git cannot run.
    r = _run(["git", "rev-parse", "--show-toplevel"], check=False)
    root = r.stdout.strip() if r.returncode == 0 else ""
    return root or None


def _git_root_error_suffix() -> str:
    # Best-effort: surface git's own stderr (safe.directory refusal, git absent) in
    # the no-root breadcrumb instead of discarding it. _run never raises.
    r = _run(["git", "rev-parse", "--show-toplevel"], check=False)
    err = (r.stderr or "").strip() if r.returncode != 0 else ""
    return f" (git: {err})" if err else ""


def _default_config_path() -> str:
    # Anchor the default config path to the repo root (issue #295) so a subdirectory
    # invocation reads the consumer's ROOT config. A non-empty explicit --config is
    # honored verbatim by the caller; this default is only used when --config is None.
    root = _repo_root()
    if root is not None:
        return str(Path(_resolve_state_dir(root)) / "config.json")
    cwd = Path.cwd()
    if not (cwd / ".prflow").is_dir() and not (cwd / ".devflow").is_dir():
        sys.stderr.write(
            f"match-lint-adjudications.py: could not resolve a git repo root"
            f"{_git_root_error_suffix()} and no .prflow/ at {str(cwd)!r}; "
            f"falling back to a cwd-anchored default config path\n"
        )
    return str(Path(_resolve_state_dir(str(cwd))) / "config.json")


def _config_get(key: str, default: str = "", config_path: str | None = None) -> str:
    if config_path is None:
        config_path = _default_config_path()
    here = Path(__file__).resolve().parent
    helper = here / "config-get.sh"
    r = _run([str(helper), key, default, config_path], check=False)
    if r.returncode != 0:
        # ANY non-zero exit means config-get.sh could not return a value — the rc=127
        # OSError sentinel (broken helper: lost exec bit / bad shebang) AND its own rc=2
        # on a malformed/unparseable .prflow/config.json or a missing python3 (whose
        # own diagnostic it already wrote to stderr). Surface that stderr on every arm,
        # not just 127 — otherwise a hand-corrupted config silently empties allowed_bots
        # (which fails trust CLOSED) with the one string naming the real cause discarded.
        detail = (r.stderr or "").strip()
        sys.stderr.write(
            f"match-lint-adjudications.py: config-get.sh exited {r.returncode} for "
            f"{key!r}{f' ({detail})' if detail else ''}; falling back to default "
            f"{default!r}\n"
        )
        return default
    return r.stdout.strip()


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8 in the CLI entry path only (not at import — so
    unit-test imports don't mutate the importer's global streams)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def _row_key(tsv: str):
    """Return the 4-tuple (verdict, rule, path, detail) for a TSV line, or None if the
    line is column-deficient (< 5 fields). The (rule, path, detail) slice is the match
    key; `verdict` is returned too so the caller can keep only STALE rows. detail is the
    field(s) after `line`;
    stale-prose-lint's detail is whitespace-collapsed (no embedded tab), so a
    well-formed row splits into exactly 5, but joining any tail is defensive and
    keeps rows and payloads parsed by the identical rule (byte-identity relies on
    that symmetry)."""
    parts = tsv.split("\t")
    if len(parts) < 5:
        return None
    verdict = parts[0]
    rule, path = parts[1], parts[2]
    detail = "\t".join(parts[4:])
    return verdict, rule, path, detail


def _collect_payload_keys(comments, allowed_bots_raw, stats):
    """Scan comments for trusted, in-sentinel adjudication payloads. Returns a dict
    mapping (rule, path, detail) -> run_key (first trusted comment wins). Mutates
    stats with the counted-but-ignored classes."""
    payload_key_to_runkey: dict[tuple, str] = {}
    for c in comments:
        if not isinstance(c, dict):
            stats["comments_malformed"] += 1
            continue
        body = c.get("body")
        if not isinstance(body, str):
            # A truthy non-string body (a JSON list/dict/number a partial-shape input could
            # leak) would raise on RUN_MARKER_RE.search below — skip-and-count it like every
            # other malformed input this helper tolerates (an undecodable payload, a non-dict
            # comment), rather than aborting the WHOLE join with an uncaught TypeError and
            # losing every valid adjudication in the other comments of the run.
            stats["comments_malformed"] += 1
            continue
        author = c.get("author") if isinstance(c.get("author"), str) else ""
        author_type = c.get("author_type") if isinstance(c.get("author_type"), str) else ""
        m = RUN_MARKER_RE.search(body)
        # The run_key VALUE is annotation-only — it becomes the demoted row's "(run <key>)"
        # label and is never a comparand in WHICH row demotes, so first-occurrence selection
        # is safe for the label. Its PRESENCE, however, is a trust comparand (see `trusted`
        # below) — do not read this as "the marker is decorative".
        run_key = m.group(1) if m else None
        # Author trust is intentionally BROADER than sibling match-deferrals.py (which trusts
        # only allowed_bots membership): a Bot-type account is trusted here too, so the feature
        # works out of the box (allowed_bots defaults EMPTY, so an allowlist-only rule would
        # make this inert for every consumer that never configures it).
        #
        # Be precise about what the marker conjunction does and does not buy: the marker is
        # public, unsigned text, so a Bot that ECHOES attacker-authored prose reproduces it
        # too — the marker does NOT independently authenticate the author, and the real
        # defenses against a forged adjudication are structural: the sentinel window (a
        # payload is honored only BETWEEN the engine's own START/END sentinels), the
        # count>1 tamper guard, and the producer-side neutralization rule that keeps a
        # quoted sentinel from ever rendering live. What makes admitting any Bot acceptable
        # is the BLAST RADIUS, not the marker: the worst case is one config-gated stale-prose
        # row demoted to Informational, which Phase 4.2 excludes from the verdict at every
        # severity and which can never flip a genuine code-defect REJECT to APPROVE.
        # A consumer wanting the narrow posture pins its reviewer login in allowed_bots.
        author_ok = (author_type == "Bot") or _author_trusted(author, allowed_bots_raw)
        trusted = (run_key is not None) and author_ok

        payload_matches = list(PAYLOAD_RE.finditer(body))
        if not trusted:
            # A marker-less comment, a User-type non-allowlisted comment, or both:
            # every payload it carries is ignored and counted (never a crash).
            stats["payloads_untrusted"] += len(payload_matches)
            continue

        stats["trusted_comments"] += 1
        # Fail closed on a tampered sentinel count. The engine writes EXACTLY ONE
        # adjudications section per progress comment (the Phase 4 finalize write, and
        # the empty pair is always present in the comment template). A review report
        # routinely quotes attacker-controlled diff prose verbatim and uncapped, so an
        # earlier finding could forge a `-start … -fp-adjudicated … -end` triple that
        # appears BEFORE the engine's real section — and a first-occurrence find()
        # would then honor the forged window, demoting a genuine STALE finding whose
        # (rule,path,detail) the attacker predicted. More than one START or END means
        # we cannot tell the engine's own section from a forged/quoted one, so honor
        # no payload from this comment (the fail-closed direction the sentinel prose
        # promises). One each is the only trusted shape.
        # The comparand is the UNION across both marker spellings (issue #1003):
        # one genuine new-form section plus one attacker-quoted old-form section is
        # `1` and `1` when counted per spelling, which would raise no flag and
        # honor the earlier window -- the exact forgery this guard exists to stop.
        if (_sentinel_total(body, ADJ_SECTION_STARTS) > 1
                or _sentinel_total(body, ADJ_SECTION_ENDS) > 1):
            stats["sentinel_tampered_comments"] += 1
            sys.stderr.write(
                "match-lint-adjudications.py: refusing a trusted comment carrying "
                "more than one adjudications-section sentinel (forged/quoted section "
                "suspected) — honoring no payload from it\n"
            )
            continue
        start = _sentinel_first(body, ADJ_SECTION_STARTS)
        end = _sentinel_first(body, ADJ_SECTION_ENDS)
        # A well-formed section has a START before an END; anything else means "no
        # honored section", so every payload falls outside it. The window opens
        # past whichever spelling actually sits at `start`, so a mixed-spelling
        # pair (a pre-rename comment whose section the current engine re-wrote)
        # still yields the correct interior offsets.
        if start != -1 and end != -1 and end > start:
            section_lo = start + _sentinel_len(body, ADJ_SECTION_STARTS, start)
            section_hi = end
        else:
            section_lo = section_hi = None

        for pm in payload_matches:
            in_section = (
                section_lo is not None and section_lo <= pm.start() < section_hi
            )
            if not in_section:
                stats["payloads_outside_sentinels"] += 1
                continue
            b64 = pm.group(1)
            try:
                decoded = base64.b64decode(b64, validate=True).decode("utf-8")
            except (binascii.Error, ValueError, UnicodeDecodeError):
                stats["payloads_malformed"] += 1
                sys.stderr.write(
                    "match-lint-adjudications.py: skipping undecodable adjudication "
                    f"payload (not valid base64/utf-8): {b64!r}\n"
                )
                continue
            key = _row_key(decoded)
            if key is None:
                stats["payloads_malformed"] += 1
                sys.stderr.write(
                    "match-lint-adjudications.py: skipping column-deficient "
                    f"adjudication payload (< 5 TSV fields): {decoded!r}\n"
                )
                continue
            _verdict, rule, path, detail = key
            stats["payloads_honored"] += 1
            match_key = (rule, path, detail)
            # First trusted comment carrying the key owns the surfaced run_key.
            payload_key_to_runkey.setdefault(match_key, run_key)
    return payload_key_to_runkey


def main(argv=None):
    _force_utf8_streams()
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--config", default=None,
                   help="Path to config.json (default: the repo-root "
                        ".prflow/config.json, resolved via git rev-parse "
                        "--show-toplevel with a cwd fallback; issue #295). A "
                        "non-empty explicit value is honored verbatim.")
    args = p.parse_args(argv)

    raw = sys.stdin.read()
    if not raw.strip():
        _fail("stdin was empty (expected one JSON object with 'rows' and 'comments')")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        _fail(f"stdin input is not valid JSON: {e}")
    if not isinstance(payload, dict):
        _fail("stdin input must be a JSON object with 'rows' and 'comments'")

    rows = payload.get("rows")
    comments = payload.get("comments")
    if rows is None:
        rows = []
    if comments is None:
        comments = []
    if not isinstance(rows, list):
        _fail("'rows' must be a JSON array of TSV strings")
    if not isinstance(comments, list):
        _fail("'comments' must be a JSON array of comment objects")

    stats = {
        "rows_in": len(rows),
        "stale_rows": 0,
        "comments_in": len(comments),
        "trusted_comments": 0,
        "payloads_honored": 0,
        "payloads_malformed": 0,
        "payloads_outside_sentinels": 0,
        "payloads_untrusted": 0,
        "sentinel_tampered_comments": 0,
        "comments_malformed": 0,
        "rows_malformed": 0,
        "rows_rule_excluded": 0,
        "demoted": 0,
        "collisions": 0,
    }

    # Index the current STALE rows by match key. VERIFIED/UNRESOLVABLE rows are
    # never candidates, so they can never be demoted regardless of payloads.
    stale_by_key: dict[tuple, list[int]] = {}
    for i, row in enumerate(rows):
        if not isinstance(row, str):
            # Skip-and-count a non-string row element (a partial-shape leak) rather than
            # letting _row_key(row) raise — keeps the "every drop is accounted for" property.
            stats["rows_malformed"] += 1
            continue
        parsed = _row_key(row)
        if parsed is None:
            # A column-deficient row (fewer than the 5 TSV fields) is dropped — but it is
            # COUNTED and breadcrumbed like the payload side does, so "every drop is
            # accounted for" holds for rows too (a silent drop left rows_in - stale_rows
            # unexplained).
            stats["rows_malformed"] += 1
            sys.stderr.write(
                "match-lint-adjudications.py: skipping malformed row "
                "(expected 5 TAB-separated fields)\n"
            )
            continue
        verdict, rule, path, detail = parsed
        if verdict != STALE:
            continue
        stats["stale_rows"] += 1
        if rule in CARRY_FORWARD_EXCLUDED_RULES:
            # A rule whose detail does not embed the observed referent (today: R4) can
            # never be safely carried forward — see CARRY_FORWARD_EXCLUDED_RULES. It stays
            # a finding at its severity; the exclusion is counted, never silent.
            stats["rows_rule_excluded"] += 1
            continue
        stale_by_key.setdefault((rule, path, detail), []).append(i)

    allowed_bots_raw = _config_get(".prflow.allowed_bots", "", args.config)

    payload_key_to_runkey = _collect_payload_keys(comments, allowed_bots_raw, stats)

    demoted: list[dict] = []
    for key, run_key in payload_key_to_runkey.items():
        matches = stale_by_key.get(key, [])
        if len(matches) == 1:
            demoted.append({"row_index": matches[0], "run_key": run_key})
        elif len(matches) >= 2:
            # Ambiguity never demotes: the lint's 120-char truncated detail can let
            # two distinct claims in one boilerplate-heavy file collide, so absorbing
            # a genuine new finding into an older adjudication is the unsafe direction.
            stats["collisions"] += 1
        # 0 matches: the adjudicated claim is not in this run's rows — nothing to do.

    demoted.sort(key=lambda d: d["row_index"])
    stats["demoted"] = len(demoted)

    print(json.dumps({"demoted": demoted, "stats": stats}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
