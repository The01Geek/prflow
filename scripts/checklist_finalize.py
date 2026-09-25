#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""PRFlow review Phase 1 checklist assembly — the deterministic half.

The review engine is generation-bound, and every Phase 1 rule below is a
mechanical transform of JSON a subagent already produced. This module owns those
transforms so the engine need not re-type checklist JSON: generators Write their
own batch files, the deduper names merge groups by id, and this module carries,
concatenates, merges, renumbers, caps, tags and writes the durable artifact.

Reached as ``normalize-verdicts.py checklist <op> …`` (that helper's leading
token is the one every cloud profile already grants); importable for tests.

Work directory — ``<run-dir>/phase1-<token>``, the token fresh per engine entry,
so a re-entrant entry sharing ``<run-dir>`` and ``<N>`` (the shadow) names a
different directory and does not read this entry's intermediates. Files inside it:

    batch-<k>.json   one generator's JSON array (written by the generator)
    carried.json     ``carry`` output: the prior items carried forward, tagged
    raw.json         ``raw`` output: every batch item, id ``batch<k>:VC-<i>``
    groups.json      the deduper's merge groups: [{"keep": id, "merged_from": [ids]}]

Ops (each prints ONE JSON object on stdout; rc 0 whenever the op ran, ``ok``
carries the outcome; a usage error prints ``{"ok": false, …}`` and returns 2):

    carry    <work-dir> <N> <prior-head> [--prior FILE]
    raw      <work-dir> <B>
    finalize <work-dir> <N> <B> [--no-groups]
    match    <work-dir> <N> <prior-head> <shadow-head>

``carry`` reads the prior iteration's Step 1.8 snapshot pair at the run root —
``checklist-step1-iter-<N-1>.json`` joined by ``id`` with the verdict rows of
``verification-step1-iter-<N-1>.json`` (the row wins) — or, with ``--prior FILE``,
that file as already-joined items; an unusable snapshot carries nothing.

``finalize`` writes ``<run-dir>/checklist-iter-<N>.json`` (root: the array). It reads
the acceptance criteria from ``<run-dir>/criteria.json`` (written by Phase 0.4's
``acs-resolve --criteria-out``) and creates one ``issue_acceptance`` item per criterion
after the cap, so acceptance items never take a cap slot. Before the cap it drops each new
item that ``same_claim`` finds restating a carried item (``counts.same_claim_dropped``);
the carried item stays as carried. A criteria file present but
malformed sets ``criteria_error`` and writes no acceptance item, still ``ok: true``, and
an absent file creates no acceptance item and no error. It fails closed — ``ok: false``,
no checklist written — on:

    bad_batch                  a batch file missing, unparseable, not an array of objects,
                               or holding an item without a non-empty ``claim``/``category``
    bad_groups                 without ``--no-groups``: groups.json missing or not an array, or
                               raw.json (what the deduper read) absent or no longer equal to
                               the batch files
    bad_carried                carried.json present but not an array of objects with string ids
    merge_invariant_violation  some raw id is not in exactly one merged row's ``merged_from``
    conservation_violation     the array about to be written, plus the capped and same-claim-dropped rows, does not
                               account for every raw id exactly once; or the carried tail is
                               not the carried input; or two final ids collide
    artifact_write_unverified  a written file did not read back as the value written

``match`` joins the ``step1`` and ``shadow`` snapshot pairs of iteration ``<N>`` at the run
root and labels each non-acceptance shadow FAIL ``overlap`` — the same claim as a step1 FAIL
or INCONCLUSIVE, prior lines mapped to ``<shadow-head>`` through ``git diff -U0`` — or ``new``.
An unresolvable head or a failing diff leaves rule 1 only, and a path whose diff prints more
than header lines yet no hunk (a binary diff) leaves rule 1 only for that file. An unusable
step1 snapshot pair labels every shadow FAIL ``new``. An unusable shadow snapshot pair leaves
no FAIL to label: ``ok`` is false with ``shadow_snapshot_unusable``, so the consumer treats
every shadow FAIL as new.

``same_claim`` is a mechanical identity, not a defect judgment: a distinct claim of the same
category in the same file on overlapping lines is dropped as a restatement of the carried
item (an accepted risk).

What it does NOT decide: whether two claims state the same defect. A merge group is
applied only when its members are connected by ``plausible_duplicates`` — the
mechanically checkable part of the deduper's three rules — and is otherwise left
unmerged with a breadcrumb. Inside that envelope a wrong deduper judgment still
merges two distinct claims, exactly as a wrong judgment did when the deduper emitted
the array itself; the merged row's ``merged_from`` records which ids it absorbed.
"""
from __future__ import annotations

import importlib.util
import itertools
import json
import os
import re
import subprocess
import sys

CAP = 100
# The cap ranks non-acceptance items only — issue_acceptance items are built after the cap
# and never enter cap_items. A category outside the list ranks last.
PRIORITY = ["absolute_claim", "dependency_interaction",
            "test_mock_alignment", "api_contract", "data_format_assumption"]
TOKEN_MIN = 8  # the floor the dispatching prose tells the engine to generate
_WORK_RE = re.compile(rf"\Aphase1-[A-Za-z0-9]{{{TOKEN_MIN},64}}\Z")
# An item lacking one of these cannot be verified or prioritized: its batch is refused.
_REQUIRED_FIELDS = ("claim", "category")
# An item lacking one of these is still verifiable: it is kept and flagged.
_EXPECTED_FIELDS = ("source_file", "claim_signature")
# Categories a repo-wide convention check is emitted under (the cross-cutting theme rule).
_THEME_CATEGORIES = ("api_contract", "string_presence")
# The verdict fields a carried PASS keeps, joined from its verification row. Must equal the
# engine-return join's key set (review-engine-io.py VERDICT_KEYS) or a carried item drops a field.
_PRIOR_VERDICT_FIELDS = ("verdict", "raw_verdict", "normalized", "evidence", "file_checked",
                         "normalization_ineligible", "view_revision", "demoted", "severity")


def _shape(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _read_json(path):
    """(status, value): status is ok | missing | unreadable | unparseable."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        return "missing", None
    except (OSError, UnicodeError, ValueError):
        return "unreadable", None
    try:
        return "ok", json.loads(text)
    except ValueError:
        return "unparseable", None


class WriteUnverified(Exception):
    pass


def _write_json(path, value):
    """Write, read the bytes back, and publish only when they parse to `value` —
    a short write (quota, ENOSPC) must not become a shorter checklist."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(value, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    status, back = _read_json(tmp)
    if status != "ok" or back != value:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise WriteUnverified(f"{os.path.basename(path)}: read-back {status}, content "
                              f"{'differs' if status == 'ok' else 'unavailable'}")
    os.replace(tmp, path)


def _confined(work_dir):
    """Return (work_dir, run_dir, error). The work dir must resolve to a
    `phase1-<token>` directory beneath a `.prflow/tmp/` tree, so no op reads or
    writes outside the scratch; the returned paths keep the caller's spelling."""
    # Only the leaf is tested for a symlink. A symlinked PARENT is covered by the realpath
    # check below: the resolved path must itself sit under a `.prflow/tmp/` pair.
    if os.path.islink(work_dir.rstrip("/\\") or work_dir):
        return None, None, "work_dir_is_a_symlink"
    real = os.path.realpath(work_dir)
    parts = real.replace("\\", "/").split("/")
    if not _WORK_RE.match(parts[-1] if parts else ""):
        return None, None, "work_dir_name_not_phase1_token"
    if not any(a == ".prflow" and b == "tmp" for a, b in itertools.pairwise(parts[:-1])):
        return None, None, "work_dir_outside_prflow_tmp"
    shown = os.path.normpath(work_dir)
    return shown, os.path.dirname(shown) or ".", None


def _positive_int(text):
    return int(text) if isinstance(text, str) and re.fullmatch(r"[1-9][0-9]{0,5}", text) else None


# ── carry (§1.0) ─────────────────────────────────────────────────────────────

def _diff_paths(diff_text):
    """Every path a `diff --git a/<p> b/<p>` header can name. Over-inclusive on an
    ambiguous header (a path containing ` b/`); a C-quoted header is skipped, so an
    item about that file is simply generated fresh."""
    paths = set()
    for line in diff_text.splitlines():
        if not line.startswith("diff --git a/"):
            continue
        body = line[len("diff --git "):]
        start = 0
        while True:
            cut = body.find(" b/", start)
            if cut < 0:
                break
            paths.add(body[2:cut])
            paths.add(body[cut + 3:])
            start = cut + 1
    return paths


def _resolve_commit(head):
    """(commit id, None), or (None, cause): ``not-id``, ``unresolved``, or ``git unavailable (<exception class>)``."""
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-fA-F]{7,64}", head):
        return None, "not-id"
    try:
        probe = subprocess.run(["git", "rev-parse", "--verify", "--quiet", head + "^{commit}"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, f"git unavailable ({type(exc).__name__})"
    return (probe.stdout.strip(), None) if probe.returncode == 0 else (None, "unresolved")


def _changed_since(prior_head):
    """(set | None, cause). None means the changed set could not be established."""
    _, cause = _resolve_commit(prior_head)
    if cause:
        return None, {"not-id": "prior_diff_head is not a commit id",
                      "unresolved": "prior_diff_head does not resolve"}.get(cause, cause)
    try:
        diff = subprocess.run(["git", "diff", "--name-only", "--no-renames", "-z", prior_head, "HEAD"],
                              capture_output=True)
    except OSError as exc:
        return None, f"git unavailable ({type(exc).__name__})"
    if diff.returncode != 0:
        return None, f"git diff exited {diff.returncode}"
    names = diff.stdout.decode("utf-8", "surrogateescape").split("\0")
    return {n for n in names if n}, None


_CITED = []  # memo: [(normalize-verdicts.py's _cited_paths or None, cause)]


def _collector_cited_paths():
    """(fn, cause): the collector's ``_cited_paths``, loaded from the sibling
    normalize-verdicts.py rather than copied, so carry splits a citation the way the collector
    does. ``fn`` is None, with its cause, when it cannot load."""
    if not _CITED:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "normalize-verdicts.py")
        try:
            spec = importlib.util.spec_from_file_location("prflow_normalize_verdicts", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            fn = module._cited_paths
            _CITED.append((fn, None) if callable(fn) else (None, "_cited_paths is not callable"))
        # SystemExit too: normalize-verdicts.py's Python-version guard calls sys.exit at import.
        except (Exception, SystemExit) as exc:  # any load failure turns reuse off; carry still runs
            _CITED.append((None, f"normalize-verdicts.py _cited_paths unavailable: {type(exc).__name__}"))
    return _CITED[0]


class _Tracked:
    """``_cited_paths``' inventory, answered by the HEAD probe (and its ``has_dir``, when set)."""

    def __init__(self, probe):
        self._probe = probe

    def __contains__(self, path):
        return isinstance(path, str) and self._probe(path)

    def has_dir(self, path):
        fn = getattr(self._probe, "has_dir", None)
        return isinstance(path, str) and callable(fn) and fn(path) is True


def _carry_cited_paths(fc, tracked, errors=None):
    """The paths ``file_checked`` cites, split as the collector splits them with no view
    prefixes and the tracked set as its inventory; None when the collector cannot load or
    raises on this value (the exception's name is appended to ``errors``), so only this
    item verifies fresh."""
    fn, _ = _collector_cited_paths()
    if fn is None:
        return None
    try:
        return fn(fc, (), _Tracked(tracked))
    except (Exception, SystemExit) as exc:
        if errors is not None:
            errors.append(type(exc).__name__)
        return None


_REGULAR_MODES = (b"100644", b"100755")


def _head_entry(path):
    """``(mode, type)`` of the one `git ls-tree` entry (literal pathspec, full tree) HEAD records
    named exactly `path`, else None — so a non-canonical spelling (`./x`, `a/../x`, absolute) or
    a path git cannot take (a NUL byte) is None."""
    if not isinstance(path, str) or not path or "\0" in path:
        return None
    try:
        run = subprocess.run(["git", "--literal-pathspecs", "ls-tree", "-z", "--full-tree", "HEAD",
                              "--", path], capture_output=True)
        want = path.encode("utf-8", "surrogateescape")
    except (OSError, ValueError):
        return None
    entries = [e for e in run.stdout.split(b"\0") if e]
    if run.returncode != 0 or len(entries) != 1:
        return None
    meta, _, name = entries[0].partition(b"\t")
    fields = meta.split(b" ")
    return (fields[0], fields[1]) if len(fields) == 3 and name == want else None


def _regular_file_at_head(path):
    """Whether HEAD records `path`, spelled exactly as git records it, as a regular file (mode
    100644/100755). A tree, a submodule, and a symlink (whose target may have changed) are refused."""
    entry = _head_entry(path)
    return entry is not None and entry[0] in _REGULAR_MODES and entry[1] == b"blob"


def tracked_at_head():
    """A memoized ``_regular_file_at_head`` probe whose ``has_dir`` answers whether HEAD records
    the path as a tree (the collector's directory test). Anything either cannot establish —
    including a probe that cannot run — reads as not tracked, so that item alone verifies fresh."""
    seen, trees = {}, {}

    def probe(path):
        if path not in seen:
            seen[path] = _regular_file_at_head(path)
        return seen[path]

    def has_dir(path):
        if path not in trees:
            entry = _head_entry(path)
            trees[path] = entry is not None and entry[1] == b"tree"
        return trees[path]
    probe.has_dir = has_dir
    return probe


def _reusable(item, changed, tracked, errors=None):
    """Whether a carried PASS is reused: every path its ``file_checked`` cites is a regular
    file HEAD records under that exact spelling (``tracked``) and outside the changed-file set.
    The collector's head view is materialized from that same HEAD, so its gate admits every
    path carry reuses. A non-string, ``""``, free text, a ``./``, ``..`` or absolute spelling, a symlink, a
    directory (the collector admits one, but a fix may have changed a file under it), or any
    changed or untracked path verifies fresh."""
    if item.get("verdict") != "PASS":
        return False
    paths = _carry_cited_paths(item.get("file_checked"), tracked, errors)
    return bool(paths) and all(p not in changed and tracked(p) for p in paths)


def carry_items(prior_items, diff_paths, changed, iteration, tracked, split_errors=None):
    """Apply the carry rule and the tag table. Returns (carried, skipped_malformed); each item
    whose citation split raised is appended to ``split_errors`` as ``"<id>: <exception>"``."""
    carried, malformed = [], 0
    for item in prior_items:
        if not isinstance(item, dict):
            malformed += 1
            continue
        ident, src = item.get("id"), item.get("source_file")
        cat, sig = item.get("category"), item.get("claim_signature")
        if not all(isinstance(v, str) and v for v in (ident, src, cat, sig)):
            malformed += 1
            continue
        if cat == "issue_acceptance" or src not in diff_paths or src in changed:
            continue
        out = dict(item, carried=True)
        raised = []
        reuse = _reusable(item, changed, tracked, raised)
        if raised and split_errors is not None:
            split_errors.append(f"{ident}: _cited_paths raised {raised[0]}")
        if reuse:
            origin = item.get("reused_from_iter")
            if isinstance(origin, bool) or not isinstance(origin, int) or origin < 1:
                origin = iteration - 1
            out["reused_from_iter_prev"] = True
            out["reused_from_iter"] = origin
        else:
            for key in _PRIOR_VERDICT_FIELDS + ("reused_from_iter",):
                out.pop(key, None)
            out["reused_from_iter_prev"] = False
        carried.append(out)
    return carried, malformed


def _read_items(path, label):
    """(items, cause): the checklist array at `path` — the root, or an object's `checklist`."""
    status, doc = _read_json(path)
    if status != "ok":
        return None, f"{label} {status}"
    items = doc.get("checklist") if isinstance(doc, dict) else doc
    if not isinstance(items, list):
        where = "checklist key" if isinstance(doc, dict) else "root"
        return None, f"{label} {where} is {_shape(items)}, not an array"
    return items, None


def _join_snapshot_pair(run_dir, entry, n, labels=("checklist snapshot", "verification snapshot"),
                        rowless=None):
    """(items, cause): the ``entry`` Step 1.8 snapshot pair of iteration ``n`` joined by id.
    Every verdict field comes from the item's verification row (a field the row lacks is
    dropped) — the row may carry a demotion the item's copied ``verdict: "PASS"`` predates —
    and an item with no row keeps no verdict field; its id is added to ``rowless`` when given."""
    items, cause = _read_items(os.path.join(run_dir, f"checklist-{entry}-iter-{n}.json"), labels[0])
    if cause:
        return None, cause
    status, rows = _read_json(os.path.join(run_dir, f"verification-{entry}-iter-{n}.json"))
    if status != "ok":
        return None, f"{labels[1]} {status}"
    if not isinstance(rows, list):
        return None, f"{labels[1]} root is {_shape(rows)}, not an array"
    by_id = {r["id"]: r for r in rows if isinstance(r, dict) and isinstance(r.get("id"), str)}
    joined = []
    for item in items:
        if isinstance(item, dict):
            ident = item.get("id")
            row = by_id.get(ident, {}) if isinstance(ident, str) else {}
            if isinstance(ident, str) and ident not in by_id and rowless is not None:
                rowless.add(ident)
            item = dict(item)
            for key in _PRIOR_VERDICT_FIELDS:
                if key in row:
                    item[key] = row[key]
                else:
                    item.pop(key, None)
        joined.append(item)
    return joined, None


def op_carry(work, run_dir, iteration, prior_head, prior_path):
    out_path = os.path.join(work, "carried.json")
    result = {"op": "carry", "ok": True, "out": out_path, "carried": 0, "prior": 0,
              "reused_pass": 0, "skipped_malformed": 0, "breadcrumb": None}

    def announce():
        return (f"Carried {result['carried']} of {result['prior']} prior items forward "
                f"({result['reused_pass']} reusing a prior PASS); generating the rest fresh.")

    def none(cause):
        os.makedirs(work, exist_ok=True)
        _write_json(out_path, [])
        result["breadcrumb"] = f"carry-forward: none ({cause})"
        result["announce"] = announce()
        return result

    if iteration < 2:
        return none("iteration 1 has no predecessor")
    source = "prior checklist file" if prior_path else "checklist snapshot"
    if prior_path:
        items, cause = _read_items(prior_path, source)
    else:
        items, cause = _join_snapshot_pair(run_dir, "step1", iteration - 1)
    if cause:
        return none(cause)
    result["prior"] = len(items)
    if not items:
        return none(f"{source} is empty")
    try:
        with open(os.path.join(run_dir, "diff.patch"), encoding="utf-8", errors="surrogateescape") as fh:
            diff_paths = _diff_paths(fh.read())
    except (OSError, ValueError):
        return none("cached diff.patch unreadable")
    changed, cause = _changed_since(prior_head)
    if changed is None:
        return none(cause)
    split_errors = []
    carried, malformed = carry_items(items, diff_paths, changed, iteration, tracked_at_head(), split_errors)
    os.makedirs(work, exist_ok=True)
    _write_json(out_path, carried)
    result["carried"] = len(carried)
    result["reused_pass"] = sum(1 for c in carried if c["reused_from_iter_prev"])
    result["skipped_malformed"] = malformed
    _, cause = _collector_cited_paths()
    if cause:
        result["breadcrumb"] = f"carry-forward: reuse off ({cause})"
    elif split_errors:
        shown = "; ".join(split_errors[:5]) + ("; …" if len(split_errors) > 5 else "")
        result["breadcrumb"] = f"carry-forward: reuse skipped for {len(split_errors)} item(s) ({shown})"
    result["announce"] = announce()
    return result


# ── raw (§1.5 input) ─────────────────────────────────────────────────────────

def load_batches(work, batches):
    """(items, per_batch_counts, bad, flagged). Every item gets the
    unique-by-construction raw id `batch<k>:VC-<i>` (its 1-based position), identical
    to a well-behaved generator's own numbering. No item is silently discarded: one lacking a
    `_REQUIRED_FIELDS` string refuses its whole batch (the generator is retried); one
    lacking an `_EXPECTED_FIELDS` string or a known `verification_mode` is kept and
    listed in `flagged`."""
    items, counts, bad, flagged = [], [], [], []
    for k in range(1, batches + 1):
        status, doc = _read_json(os.path.join(work, f"batch-{k}.json"))
        if status != "ok":
            bad.append({"batch": k, "error": f"batch file {status}"})
            continue
        if not isinstance(doc, list):
            bad.append({"batch": k, "error": f"batch root is {_shape(doc)}, not an array"})
            continue
        wrong = [i + 1 for i, it in enumerate(doc) if not isinstance(it, dict)]
        if wrong:
            bad.append({"batch": k, "error": f"item {wrong[0]} is {_shape(doc[wrong[0] - 1])}, not an object"})
            continue
        unusable = [(i + 1, f) for i, it in enumerate(doc) for f in _REQUIRED_FIELDS
                    if not (isinstance(it.get(f), str) and it.get(f))]
        if unusable:
            pos, field = unusable[0]
            bad.append({"batch": k, "error": f"item {pos} lacks a non-empty string `{field}` "
                                             f"({_shape(doc[pos - 1].get(field))})"})
            continue
        counts.append(len(doc))
        for i, it in enumerate(doc):
            row = dict(it)
            row["id"] = f"batch{k}:VC-{i + 1}"
            items.append(row)
            fields = [f for f in _EXPECTED_FIELDS if not (isinstance(it.get(f), str) and it.get(f))]
            if it.get("verification_mode") not in ("lite", "agent"):
                fields.append("verification_mode")
            if fields:
                flagged.append({"id": row["id"], "fields": fields})
    return items, counts, bad, flagged


def op_raw(work, batches):
    items, counts, bad, flagged = load_batches(work, batches)
    if bad:
        return {"op": "raw", "ok": False, "error": "bad_batch", "bad_batches": bad}
    out_path = os.path.join(work, "raw.json")
    _write_json(out_path, items)
    return {"op": "raw", "ok": True, "out": out_path, "batches": counts, "items": len(items),
            "flagged_items": flagged}


# ── finalize (§1.5 merge, §1.1.5 cap, §1.0 merge-back, §1.6 write) ───────────

def _has_line(item):
    line = item.get("source_line")
    return isinstance(line, int) and not isinstance(line, bool)


def _pick_representative(members, keep):
    """The deduper's `keep` when it names a member; otherwise the documented order:
    line-anchored, longer claim, populated lite_probe, lowest input index. A group
    holding an `agent` item never resolves to a `lite` representative."""
    pool = members
    agents = [m for m in members if m[1].get("verification_mode") == "agent"]
    if agents and len(agents) != len(members):
        pool = agents
    for idx, item in pool:
        if item["id"] == keep:
            return idx, item
    return min(pool, key=lambda m: (not _has_line(m[1]),
                                    -len(m[1].get("claim") if isinstance(m[1].get("claim"), str) else ""),
                                    not isinstance(m[1].get("lite_probe"), dict),
                                    m[0]))


def _effective_range(item):
    probe = item.get("lite_probe")
    rng = probe.get("line_range") if isinstance(probe, dict) else None
    if (isinstance(rng, list) and len(rng) == 2
            and all(isinstance(v, int) and not isinstance(v, bool) for v in rng)):
        return min(rng), max(rng)
    if not _has_line(item):
        return None
    end = item.get("source_line_end")
    if isinstance(end, bool) or not isinstance(end, int):
        end = item["source_line"]
    return min(item["source_line"], end), max(item["source_line"], end)


def _signature_slug(item):
    sig = item.get("claim_signature")
    parts = sig.split(":") if isinstance(sig, str) else []
    return parts[2] if len(parts) >= 3 and parts[2] else None


def plausible_duplicates(a, b):
    """The mechanically checkable part of the deduper's three merge rules. It cannot
    tell whether two claims state the same defect — that stays the deduper's judgment —
    but it refuses a pair no rule could have matched."""
    sig_a, sig_b = a.get("claim_signature"), b.get("claim_signature")
    if isinstance(sig_a, str) and sig_a and sig_a == sig_b:
        return True                                   # rule 1: same claim_signature
    cat = a.get("category")
    if not isinstance(cat, str) or cat != b.get("category"):
        return False
    src = a.get("source_file")
    if isinstance(src, str) and src and src == b.get("source_file"):
        ra, rb = _effective_range(a), _effective_range(b)
        if ra is None or rb is None:                  # rule 2: same file and category, and
            return ra is None and rb is None          # neither anchored, or ranges within 3 lines
        return ra[0] - 3 <= rb[1] and rb[0] - 3 <= ra[1]
    slug = _signature_slug(a)                         # rule 3: the same repo-wide convention check
    return cat in _THEME_CATEGORIES and slug is not None and slug == _signature_slug(b)


def _connected(members):
    """Whether every member is reachable from the first through plausible-duplicate pairs."""
    seen, stack = {0}, [0]
    while stack:
        at = stack.pop()
        for j in range(len(members)):
            if j not in seen and plausible_duplicates(members[at], members[j]):
                seen.add(j)
                stack.append(j)
    return len(seen) == len(members)


def merge_groups(raw_items, groups, crumbs, hint_ids=frozenset()):
    """Collapse raw items by the deduper's groups. `groups` None means the
    deterministic fallback: merge identical (claim_signature, source_file) only."""
    by_id = {it["id"]: (i, it) for i, it in enumerate(raw_items)}
    assigned, plan = set(), []
    if groups is None:
        sig_groups = {}
        for i, it in enumerate(raw_items):
            sig, src = it.get("claim_signature"), it.get("source_file")
            if isinstance(sig, str) and sig and isinstance(src, str):
                sig_groups.setdefault((sig, src), []).append(it["id"])
        groups = [{"merged_from": ids} for ids in sig_groups.values() if len(ids) > 1]
    for n, group in enumerate(groups):
        if not isinstance(group, dict) or not isinstance(group.get("merged_from"), list):
            crumbs.append(f"dedup group {n + 1} ignored: {_shape(group)} without a merged_from array")
            continue
        ids = []
        for ident in group["merged_from"]:
            if isinstance(ident, str) and ident in hint_ids:
                crumbs.append(f"dedup group {n + 1}: acceptance hint {ident} never merges, ignored")
            elif not isinstance(ident, str) or ident not in by_id:
                crumbs.append(f"dedup group {n + 1}: unknown id {ident!r} ignored")
            elif ident in assigned or ident in ids:
                crumbs.append(f"dedup group {n + 1}: id {ident} already merged, ignored")
            else:
                ids.append(ident)
        if len(ids) < 2:
            continue
        if not _connected([by_id[i][1] for i in ids]):
            # Keeping a duplicate costs one verifier; dropping a distinct claim costs a missed defect.
            crumbs.append(f"dedup group {n + 1} not merged: {', '.join(ids)} are not plausible "
                          "duplicates (no shared claim_signature, same-file same-category nearby "
                          "range, or shared convention slug) — all kept")
            continue
        assigned.update(ids)
        plan.append((ids, group.get("keep")))
    rep_of, merged_from = {}, {}
    for ids, keep in plan:
        members = sorted(by_id[i] for i in ids)
        _, rep = _pick_representative(members, keep)
        if isinstance(keep, str) and keep != rep["id"]:
            crumbs.append(f"dedup keep {keep!r} not usable; kept {rep['id']}")
        rep_of[rep["id"]] = (rep, [m[1] for m in members])
        merged_from[rep["id"]] = [m[1]["id"] for m in members]
    out = []
    for it in raw_items:
        ident = it["id"]
        if ident in assigned and ident not in rep_of:
            continue
        if ident in rep_of:
            rep, members = rep_of[ident]
            row = dict(rep)
            provs = {m.get("claim_provenance") for m in members}
            if len(provs) > 1 and "source_authored" in provs:
                authored = next(m for m in members if m.get("claim_provenance") == "source_authored")
                row["claim_provenance"] = "source_authored"
                row.pop("source_excerpt", None)  # never a paraphrase member's text as the authored excerpt
                if "source_excerpt" in authored:
                    row["source_excerpt"] = authored["source_excerpt"]
            row["merged_from"] = merged_from[ident]
        else:
            row = dict(it)
            row["merged_from"] = [ident]
        out.append(row)
    return out


def _id_ledger(rows):
    """Every raw id the rows account for, sorted; a row with no usable merged_from accounts for none."""
    return sorted(x for row in rows for x in (row.get("merged_from") if isinstance(row.get("merged_from"), list) else [])
                  if isinstance(x, str))


def _ledger_diff(expected, actual):
    exp, act = list(expected), list(actual)
    return {"missing_ids": sorted(set(exp) - set(act)),
            "unknown_ids": sorted(set(act) - set(exp)),
            "duplicated_ids": sorted({x for x in act if act.count(x) > 1})}


def cap_items(items):
    """Keep the top CAP by PRIORITY, preserving input order. Returns (kept, dropped).
    issue_acceptance items never reach here — they are built after the cap."""
    if len(items) <= CAP:
        return list(items), []
    rank = {c: i for i, c in enumerate(PRIORITY)}
    order = sorted(range(len(items)), key=lambda i: (rank.get(items[i].get("category"), len(PRIORITY)), i))
    keep = set(order[:CAP])
    return ([it for i, it in enumerate(items) if i in keep],
            [it for i, it in enumerate(items) if i not in keep])


def _read_criteria(run_dir):
    """(criteria, error): criteria is a list of ``{"criterion": N, "text": T}`` in order
    1..K, or None; error is None or a short string. A MISSING file is not an error (a run
    with no acceptance criteria — no items, no error); every other malformed shape is an
    error and yields None criteria, so the checklist still writes every non-acceptance item."""
    status, doc = _read_json(os.path.join(run_dir, "criteria.json"))
    if status == "missing":
        return None, None
    if status != "ok":
        return None, f"criteria file {status}"
    if not isinstance(doc, list):
        return None, f"criteria root is {_shape(doc)}, not an array"
    if not doc:
        return None, "criteria file is an empty array"
    criteria = []
    for i, entry in enumerate(doc):
        if not isinstance(entry, dict):
            return None, f"criteria entry {i + 1} is {_shape(entry)}, not an object"
        crit = entry.get("criterion")
        if isinstance(crit, bool) or not isinstance(crit, int):
            return None, f"criteria entry {i + 1} criterion is {_shape(crit)}, not an integer"
        text = entry.get("text")
        if not (isinstance(text, str) and text):
            return None, f"criteria entry {i + 1} text is {_shape(text)}, not a non-empty string"
        criteria.append({"criterion": crit, "text": text})
    if [c["criterion"] for c in criteria] != list(range(1, len(criteria) + 1)):
        return None, "criteria numbering is not 1..K in order"
    return criteria, None


def _generic_hint(diff_path, text):
    """The verify_hint for a criterion no valid generator hint located: it names the
    run-scoped diff and tells the verifier to cite the head-view file the diff meets."""
    return (f"No generator hint located this criterion. Read {diff_path} to find where the diff "
            f"meets the criterion, then cite that head-view file. Criterion: {text}")


def _build_acceptance_items(criteria, hints, run_dir, crumbs):
    """One issue_acceptance item per criterion, criteria in 1..K order, ids assigned later
    in the fresh pass. The FIRST hint in list (batch) order whose integer non-boolean
    ``criterion`` matches supplies each of source_file/source_line/verify_hint it validly carries; a criterion with no
    valid hint gets a generic diff-citing verify_hint. With criteria present, every hint not
    selected for a criterion gets a breadcrumb."""
    by_criterion = {}
    k = len(criteria) if criteria else 0
    for h in hints if criteria else []:
        c = h.get("criterion")
        if isinstance(c, bool) or not isinstance(c, int):
            crumbs.append(f"hint {h['id']} unused: criterion is {_shape(c)}, not an integer")
        elif not 1 <= c <= k:
            crumbs.append(f"hint {h['id']} unused: criterion {c} is outside 1..{k}")
        elif c in by_criterion:
            crumbs.append(f"hint {h['id']} unused: criterion {c} already located by an earlier hint")
        else:
            by_criterion[c] = [h]
    diff_path = os.path.join(run_dir, "diff.patch")
    items = []
    for spec in criteria or []:
        n = spec["criterion"]
        row = {"category": "issue_acceptance", "verification_mode": "agent",
               "claim_provenance": "generated_paraphrase", "claim": spec["text"],
               "claim_signature": f"issue-acceptance-{n}"}
        hint = (by_criterion.get(n) or [None])[0]
        if hint is not None:
            if isinstance(hint.get("source_file"), str) and hint["source_file"]:
                row["source_file"] = hint["source_file"]
            if _has_line(hint):
                row["source_line"] = hint["source_line"]
        vh = hint.get("verify_hint") if hint is not None else None
        row["verify_hint"] = vh if (isinstance(vh, str) and vh) else _generic_hint(diff_path, spec["text"])
        items.append(row)
    return items


def op_finalize(work, run_dir, iteration, batches, no_groups):
    crumbs = []
    raw_items, counts, bad, flagged = load_batches(work, batches)
    if bad:
        return {"op": "finalize", "ok": False, "error": "bad_batch", "bad_batches": bad}
    # Hints never merge, take a cap slot or ship; acceptance items come from criteria.json.
    hint_items = [it for it in raw_items if it.get("category") == "issue_acceptance"]
    other_items = [it for it in raw_items if it.get("category") != "issue_acceptance"]
    hint_id_set = {it["id"] for it in hint_items}
    generated = len(raw_items)
    raw_ids = sorted(it["id"] for it in raw_items)
    other_ids = sorted(it["id"] for it in other_items)
    hint_ids = sorted(hint_id_set)
    if batches > 1:
        groups = None
        if not no_groups:
            status, groups = _read_json(os.path.join(work, "groups.json"))
            if status != "ok" or not isinstance(groups, list):
                detail = f"groups file {status}" if status != "ok" else f"groups root is {_shape(groups)}, not an array"
                return {"op": "finalize", "ok": False, "error": "bad_groups", "detail": detail}
            # The groups name ids of the raw.json the deduper read. `raw` and this op each derive
            # those ids from the batch files, so a batch rewritten in between (a generator retry)
            # would point a group at a different item: require the two derivations to agree.
            status, seen = _read_json(os.path.join(work, "raw.json"))
            if status != "ok" or seen != raw_items:
                return {"op": "finalize", "ok": False, "error": "bad_groups",
                        "detail": f"raw.json {status if status != 'ok' else 'no longer matches the batch files'}"
                                  " — re-run `raw` and the deduper"}
        merged = merge_groups(other_items, groups, crumbs, hint_id_set)
    else:
        merged = [dict(it, merged_from=[it["id"]]) for it in other_items]

    # Merge invariant over the non-acceptance items: each sits in exactly one merged_from.
    ledger = _id_ledger(merged)
    if ledger != other_ids:
        return {"op": "finalize", "ok": False, "error": "merge_invariant_violation",
                "detail": _ledger_diff(other_ids, ledger)}

    carried = []
    carried_path = os.path.join(work, "carried.json")
    status, doc = _read_json(carried_path)
    if status == "ok" and isinstance(doc, list):
        carried = [c for c in doc if isinstance(c, dict) and isinstance(c.get("id"), str)]
        if len(carried) != len(doc):
            return {"op": "finalize", "ok": False, "error": "bad_carried",
                    "detail": "carried.json holds an entry that is not an object with a string id"}
    elif status != "missing":
        return {"op": "finalize", "ok": False, "error": "bad_carried",
                "detail": f"carried.json {status}" if status != "ok" else f"carried.json root is {_shape(doc)}"}

    # The identity line map holds only because carry keeps items whose file is unchanged since the
    # prior head; carrying an item from a changed file needs a real line map here.
    restates = [any(same_claim(c, it, _same_lines) for c in carried) for it in merged]
    restated = [it for it, dup in zip(merged, restates) if dup]
    kept, dropped = cap_items([it for it, dup in zip(merged, restates) if not dup])

    criteria, criteria_error = _read_criteria(run_dir)
    acceptance_items = _build_acceptance_items(criteria, hint_items, run_dir, crumbs)

    taken = {c["id"] for c in carried}
    final, n = [], 0
    for it in itertools.chain(kept, acceptance_items):
        n += 1
        while f"VC-{n}" in taken:
            n += 1
        row = dict(it)
        row["id"] = f"VC-{n}"
        row.pop("reused_from_iter", None)
        row.pop("carried", None)
        row["reused_from_iter_prev"] = False
        final.append(row)
    fresh = len(final)
    final.extend(carried)

    # Every raw id is traced: kept, capped and same-claim-dropped rows by merged_from, hints by the hint-id term.
    merged_away = sum(len(row["merged_from"]) - 1 for row in final[:fresh] if "merged_from" in row)
    ids = [it["id"] for it in final]
    traced = sorted(_id_ledger(final[:fresh]) + _id_ledger(dropped) + _id_ledger(restated) + hint_ids)
    if traced != raw_ids or final[fresh:] != carried or len(set(ids)) != len(ids):
        return {"op": "finalize", "ok": False, "error": "conservation_violation",
                "detail": dict(_ledger_diff(raw_ids, traced), generated=generated, fresh=fresh,
                               capped=len(dropped), same_claim_dropped=len(restated),
                               carried=len(carried), final=len(final),
                               acceptance=len(acceptance_items), unique_ids=len(set(ids)))}
    if batches == 1:
        for row in final[:fresh]:
            row.pop("merged_from", None)

    by_category = {}
    for it in dropped:
        cat = it.get("category") if isinstance(it.get("category"), str) else "uncategorized"
        by_category[cat] = by_category.get(cat, 0) + 1

    # A hint, same-claim-dropped or cap-dropped item is not flagged; a hint's problems are its
    # "hint ... unused" breadcrumbs.
    unshipped = hint_id_set | set(_id_ledger(restated)) | set(_id_ledger(dropped))
    flagged = [f for f in flagged if f["id"] not in unshipped]
    restated_items = [{"merged_from": it["merged_from"], "claim_signature": it.get("claim_signature"),
                       "carried_id": next(c["id"] for c in carried if same_claim(c, it, _same_lines))}
                      for it in restated]

    checklist_path = os.path.join(run_dir, f"checklist-iter-{iteration}.json")
    _write_json(checklist_path, final)

    announce = [f"Generated {generated} verification checklist items."]
    if batches > 1:
        announce.append(f"Deduped to {len(merged)} of {len(other_items)} items.")
    crumbs.extend(f"item {f['id']} kept but lacks a usable {', '.join(f['fields'])}" for f in flagged)
    if restated:
        announce.append(f"Dropped {len(restated)} new item(s) restating a carried item.")
    if dropped:
        cats = ", ".join(f"{c}: {k}" for c, k in sorted(by_category.items()))
        announce.append(f"Capped checklist at {CAP} of {len(kept) + len(dropped)} items (dropped {len(dropped)} items by "
                        f"category: {cats}; priority kept: {', '.join(PRIORITY)}).")
    if criteria is not None:
        announce.append(f"Itemized {len(acceptance_items)} acceptance criteria (no cap).")
    elif criteria_error:
        announce.append(f"Acceptance criteria not itemized: {criteria_error}.")
    return {
        "op": "finalize", "ok": True, "checklist": checklist_path,
        "criteria_error": criteria_error, "issue_acceptance_count": len(acceptance_items),
        "counts": {"generated": generated, "batches": counts, "merged_away": merged_away,
                   "groups_refused": sum(1 for c in crumbs if " not merged: " in c),
                   "capped": len(dropped), "same_claim_dropped": len(restated),
                   "new": len(kept), "carried": len(carried),
                   "acceptance": len(acceptance_items),
                   "reused_pass": sum(1 for c in carried if c.get("reused_from_iter_prev") is True),
                   "final": len(final),
                   "lite": sum(1 for it in final if it.get("verification_mode") == "lite"),
                   "agent": sum(1 for it in final if it.get("verification_mode") != "lite")},
        "cap_drops": {"count": len(dropped), "by_category": by_category},
        "same_claim_dropped_items": restated_items,
        "flagged_items": flagged, "announce": announce, "breadcrumbs": crumbs,
    }


# ── same claim (§1.6 carried-duplicate drop, shadow comparison) ──────────────

_HUNK_RE = re.compile(r"@@ -(\d+)(?:,(\d+))? \+\d+(?:,(\d+))? @@")
_VERDICTS = ("PASS", "FAIL", "INCONCLUSIVE")


def _valid_line(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _claim_range(item):
    """(category, source_file, lo, hi) when rule 2 can apply, else None. Not ``_effective_range``
    or ``_has_line``: unifying them would read ``lite_probe`` and accept ``source_line`` 0."""
    cat, src, line = item.get("category"), item.get("source_file"), item.get("source_line")
    if not (isinstance(cat, str) and cat and isinstance(src, str) and src and _valid_line(line)):
        return None
    end = item.get("source_line_end")
    return cat, src, line, end if _valid_line(end) and end >= line else line


def same_claim(prior, current, line_map):
    """Whether two checklist items state the same claim. Rule 1: equal non-empty
    ``claim_signature``. Rule 2: equal ``category`` and ``source_file``, and line ranges that
    overlap once ``line_map(source_file, lo, hi)`` maps the prior range to the current head
    (None: unmappable, so rule 1 alone applies). An ``issue_acceptance`` item never matches."""
    if "issue_acceptance" in (prior.get("category"), current.get("category")):
        return False
    sig = prior.get("claim_signature")
    if isinstance(sig, str) and sig and sig == current.get("claim_signature"):
        return True
    a, b = _claim_range(prior), _claim_range(current)
    if a is None or b is None or a[:2] != b[:2]:
        return False
    mapped = line_map(a[1], a[2], a[3])
    return mapped is not None and mapped[0] <= b[3] and b[2] <= mapped[1]


def _same_lines(_path, lo, hi):
    return lo, hi


def _no_lines(_path, _lo, _hi):
    return None


def _hunks(diff_text):
    """[(old_start, old_count, new_count)] from `-U0` hunk headers; an omitted count is 1."""
    out = []
    for line in diff_text.splitlines():
        m = _HUNK_RE.match(line)
        if m:
            out.append((int(m.group(1)), 1 if m.group(2) is None else int(m.group(2)),
                        1 if m.group(3) is None else int(m.group(3))))
    return out


def _map_range(hunks, lo, hi):
    """The prior range at the new head, or None when a hunk's old range overlaps it. A pure
    insertion (old count 0) follows old line ``start`` and removes no line."""
    if any(old and start <= hi and lo <= start + old - 1 for start, old, _ in hunks):
        return None

    def at(line):
        return line + sum(new - old for start, old, new in hunks if line > (start + old - 1 if old else start))
    return at(lo), at(hi)


_HEADER_ONLY = ("diff --git ", "index ", "old mode ", "new mode ", "new file mode ", "deleted file mode ")


def _git_line_map(prior, current, paths, crumbs):
    """(line_map, cause): each path's prior→current line map from its `-U0` hunk headers, or
    (None, cause) when a diff cannot be read. A diff printing more than headers yet no hunk (a
    binary diff) leaves that path unmappable, never read as unchanged."""
    if prior == current:
        return _same_lines, None
    hunks = {}
    for path in sorted(paths):
        try:
            diff = subprocess.run(["git", "--literal-pathspecs", "diff", "--no-color", "-U0",
                                   "--inter-hunk-context=0", "--no-renames",
                                   "--no-ext-diff", "--no-textconv", prior, current, "--", path],
                                  capture_output=True)
        except OSError as exc:
            return None, f"git unavailable ({type(exc).__name__})"
        except ValueError:  # a NUL byte in the path
            return None, f"source_file {path!r} cannot be passed to git diff"
        if diff.returncode != 0:
            return None, f"git diff exited {diff.returncode} for {path}"
        text = diff.stdout.decode("utf-8", "surrogateescape")
        parsed = _hunks(text)
        if not parsed and any(not line.startswith(_HEADER_ONLY) for line in text.splitlines()):
            crumbs.append(f"git diff for {path} has no hunk header; rule 1 only for that file")
            continue
        hunks[path] = parsed
    return (lambda path, lo, hi: _map_range(hunks[path], lo, hi) if path in hunks else None), None


def _state(item, key):
    if key not in item:
        return "absent"
    value = item[key]
    if isinstance(value, bool):
        return f"boolean {'true' if value else 'false'}"
    if isinstance(value, (int, float)):
        return f"number {value}"
    if value == "":
        return "empty string"
    return _shape(value)


def _rule_crumbs(entry, item, crumbs):
    """One breadcrumb per field shape that turns a rule off for ``item`` (an absent line is by design)."""
    def say(key, effect):
        crumbs.append(f"{entry} {item['id']}: {key} is {_state(item, key)}, {effect}")
    if not (isinstance(item.get("claim_signature"), str) and item["claim_signature"]):
        say("claim_signature", "rule 1 off")
    for key in ("category", "source_file"):
        if not (isinstance(item.get(key), str) and item[key]):
            say(key, "rule 2 off")
    line = item.get("source_line")
    if "source_line" in item and not _valid_line(line):
        say("source_line", "rule 2 off")
    elif _valid_line(line) and "source_line_end" in item:
        end = item["source_line_end"]
        if not (_valid_line(end) and end >= line):
            say("source_line_end", "range is source_line alone")


def _entry_items(run_dir, entry, n, crumbs):
    """(items, rowless ids) from the ``entry`` snapshot pair — objects with a string id, never
    ``issue_acceptance`` — or (None, None) when the pair is unusable."""
    names = (f"checklist-{entry}-iter-{n}.json", f"verification-{entry}-iter-{n}.json")
    rowless = set()
    joined, cause = _join_snapshot_pair(run_dir, entry, n, names, rowless)
    if cause:
        crumbs.append(f"{entry} snapshot pair unusable ({cause}); every shadow FAIL is new")
        return None, None
    items = []
    for i, it in enumerate(joined, 1):
        if not isinstance(it, dict):
            crumbs.append(f"{names[0]} item {i} is {_shape(it)}, skipped")
        elif not isinstance(it.get("id"), str):
            crumbs.append(f"{names[0]} item {i} id is {'absent' if 'id' not in it else _shape(it['id'])}, skipped")
        elif it.get("category") != "issue_acceptance":
            items.append(it)
    return items, rowless


def op_match(run_dir, n, prior_head, shadow_head):
    """Label each non-acceptance shadow checklist FAIL ``overlap`` (the same claim as a last-iteration FAIL or
    INCONCLUSIVE) or ``new``. An unusable step1 input only narrows what can overlap (an unusable step1 pair
    leaves none); an unusable shadow pair returns ``ok`` false, since its FAILs cannot be read to label."""
    crumbs, labels = [], {}
    prior_items, rowless = _entry_items(run_dir, "step1", n, crumbs)
    shadow_items, _ = _entry_items(run_dir, "shadow", n, crumbs)
    if shadow_items is None:
        return {"op": "match", "ok": False, "error": "shadow_snapshot_unusable", "detail": crumbs[-1],
                "labels": {}, "counts": {"overlap": 0, "new": 0}, "breadcrumbs": crumbs}
    candidates = []
    for it in prior_items or []:
        verdict = it.get("verdict")
        if it["id"] in rowless:
            crumbs.append(f"step1 {it['id']}: no verification row, cannot make an overlap")
        elif verdict in ("FAIL", "INCONCLUSIVE"):
            _rule_crumbs("step1", it, crumbs)
            candidates.append(it)
        elif verdict not in _VERDICTS:
            shown = f"string {verdict!r}" if isinstance(verdict, str) and verdict else _state(it, "verdict")
            crumbs.append(f"step1 {it['id']}: verdict is {shown}, cannot make an overlap")
    if prior_items is not None and not candidates:
        crumbs.append("no prior FAIL or INCONCLUSIVE item")
    fails = [it for it in shadow_items or [] if it.get("verdict") == "FAIL"]
    for it in fails:
        _rule_crumbs("shadow", it, crumbs)

    heads = [_resolve_commit(prior_head), _resolve_commit(shadow_head)]
    cause = next(({"not-id": f"{label} {head!r} is not a commit id",
                   "unresolved": f"{label} {head} does not resolve to a commit"}.get(c, c)
                  for (_, c), label, head in zip(heads, ("prior-head", "shadow-head"), (prior_head, shadow_head))
                  if c), None)
    line_map = None
    if cause is None:
        ranges = [[r[1] for r in map(_claim_range, group) if r] for group in (candidates, fails)]
        line_map, cause = _git_line_map(heads[0][0], heads[1][0], set(ranges[0]) & set(ranges[1]), crumbs)
    if cause:
        crumbs.append(f"{cause}; rule 2 off, rule 1 only for every item")
    for it in fails:
        labels[it["id"]] = ("overlap" if any(same_claim(c, it, line_map or _no_lines) for c in candidates)
                            else "new")
    return {"op": "match", "ok": True, "labels": labels,
            "counts": {"overlap": sum(v == "overlap" for v in labels.values()),
                       "new": sum(v == "new" for v in labels.values())},
            "breadcrumbs": crumbs}


# ── CLI ──────────────────────────────────────────────────────────────────────

_USAGE = ("usage: checklist carry <work-dir> <N> <prior-head> [--prior FILE] | "
          "checklist raw <work-dir> <B> | checklist finalize <work-dir> <N> <B> [--no-groups] | "
          "checklist match <work-dir> <N> <prior-head> <shadow-head>")


def main(argv):
    def usage(detail):
        print(json.dumps({"ok": False, "error": "usage", "detail": detail, "usage": _USAGE}, indent=2))
        return 2

    if len(argv) < 2:
        return usage("an op and a work directory are required")
    op, work_arg, rest = argv[0], argv[1], list(argv[2:])
    work, run_dir, err = _confined(work_arg)
    if err:
        return usage(err)
    try:
        if op == "carry":
            prior = None
            if "--prior" in rest:
                at = rest.index("--prior")
                if at + 1 >= len(rest):
                    return usage("--prior needs a file path")
                prior = rest[at + 1]
                del rest[at:at + 2]
            if len(rest) != 2 or _positive_int(rest[0]) is None:
                return usage("carry takes <N> <prior-head>")
            out = op_carry(work, run_dir, _positive_int(rest[0]), rest[1], prior)
        elif op == "raw":
            if len(rest) != 1 or _positive_int(rest[0]) is None:
                return usage("raw takes <B>")
            out = op_raw(work, _positive_int(rest[0]))
        elif op == "finalize":
            no_groups = "--no-groups" in rest
            rest = [r for r in rest if r != "--no-groups"]
            if len(rest) != 2 or None in (_positive_int(rest[0]), _positive_int(rest[1])):
                return usage("finalize takes <N> <B>")
            out = op_finalize(work, run_dir, _positive_int(rest[0]), _positive_int(rest[1]), no_groups)
        elif op == "match":
            if len(rest) != 3 or _positive_int(rest[0]) is None:
                return usage("match takes <N> <prior-head> <shadow-head>")
            out = op_match(run_dir, _positive_int(rest[0]), rest[1], rest[2])
        else:
            return usage(f"unknown op {op!r}")
    except WriteUnverified as exc:
        out = {"op": op, "ok": False, "error": "artifact_write_unverified", "detail": str(exc)[:200]}
    except Exception as exc:  # a helper defect must still print a readable outcome
        import traceback
        sys.stderr.write("checklist_finalize.py: internal error — this is a helper defect:\n"
                         + traceback.format_exc())
        out = {"op": op, "ok": False, "error": "helper_internal_error",
               "detail": f"{type(exc).__name__}: {exc}"[:200]}
    print(json.dumps(out, indent=2))
    return 0

