# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Phase 4 reads of the stored checklist verdicts, behind ``normalize-verdicts.py``.

``normalize-verdicts.py render <run-dir> <N> --contract 2 --threshold <t> [--capped-file <path>]
[--prior <phase1-work-dir>] [--skipped intentional|failure]``, once its arguments pass the usage
check, first removes the files below and the ``checklist-section-iter-<N>.md`` an earlier version
wrote (it tries each, and one it cannot remove is ``status: error``), then reads ``checklist-iter-<N>.json`` and ``verification-iter-<N>.json``
and writes:

- one report piece per ``PIECES`` key, ``checklist-<key>-iter-<N>.md`` (``run_details`` is spelled
  ``run-details`` in the name), which Phase 4 pastes whole. ``critical``, ``important`` and
  ``suggestion`` each hold the headline and Evidence block of the FAILs of that grade (``_grade``);
  ``informational`` holds those of the INCONCLUSIVE rows; ``run_details`` holds the tally line and
  the Passed list. A piece with nothing to hold is an empty file;
- ``checklist-render-iter-<N>.json``: ``{"capped": {<id>: <cap grade>, ...}}``, which
  ``review-evidence-gate.py`` reads when it grades a posted verdict.

``--capped-file`` names a UTF-8 file the agent wrote, one ``<id> <suggestion|important>: <inertness
evidence>`` line per capped checklist FAIL, so agent text never passes through a shell; a line with no
cap grade or no evidence, or naming no stored FAIL, is ignored with a warning. ``--skipped`` (Phase 1+2
did not run) reads neither artifact above, and its ``run_details`` piece is the one
``Checklist not run:`` line. ``--prior`` adds the ``checklist prior-lines`` output for Phase 1's work
dir (the record in its parent run dir) as ``prior_lines``.

It prints one JSON line, exit 0: ``{"status": "ok", "pieces", "reject_ids", "carried_ids",
"shortfall_ids", "none_verified", "prior_lines", "prior_shortfall", "warnings"}``. ``pieces`` maps
each ``PIECES`` key to ``{"path", "count", "ids"}``: the piece's file, and the number and ids of the
checklist items it lists with a headline and Evidence block. It prints
``{"status": "error", "reason"}`` with exit 1 for an earlier output it cannot remove, an unreadable
capped file, an absent, unreadable or wrong-shaped verification artifact, an absent or unreadable checklist beside one
(without the items a carried FAIL cannot be told apart) or a failed write of
an output; a usage error prints ``{"status": "usage", "reason"}`` with exit 2.

Classification (Phase 4.2): a FAIL whose seed carries the self-contradicting-diff carve-out marker after
its ``(raised by N/M agents)`` suffix and before any HTML comment is in ``carried_ids`` and ``reject_ids``; any other FAIL is weighed at its
stored severity (missing or unknown reads ``critical``), or at its cap grade when it is capped and
that grade is the lower of the two, and is in ``reject_ids`` at or above the threshold. An INCONCLUSIVE is in ``shortfall_ids`` unless its row's
``verification_shortfall`` is JSON null (a row without that key counts); ``none_verified`` is true when there is at least one row and
every row is INCONCLUSIVE.

``normalize-verdicts.py reverify-add <run-dir> <N> <item-id> --contract 2 --threshold <t> --counter-reading-file <path>``
registers a Phase 4.1 dispute, its one-sentence counter-reading read from that UTF-8 file: it checks the
item is verified by an agent, stored FAIL at or above the threshold and not yet disputed in this entry,
points the item file at attempt k through normalize-verdicts.py's ``_redirect``, the rule collect's
re-dispatch uses (``attempt`` stays, so ``collect`` still grades the stored answer
from it), and adds a ``dispute`` entry, the
``Disputed:`` and ``Counter-reading:`` lines the verifier reads; then it adds ``reverify[<id>] =
{"attempt": k, "counter_reading"}`` to the inputs file (creating it). It prints ``{"status": "ok", "id",
"attempt", "item", "verdict_file"}`` (exit 0); ``{"status": "refused", "reason"}`` (exit 1); or
``{"status": "usage", "reason"}`` (exit 2, also for an unreadable or empty counter-reading file).
It takes no lock: when two calls on one inputs file overlap, the later write can drop the other's
registration, and ``collect``, which reads only registered disputes, then keeps that item's stored FAIL.

Both subcommands require ``--contract 2`` and refuse a call without it as a usage error.
"""
import json
import os
import posixpath
import re
import secrets
import sys

SEVERITIES = ("critical", "important", "suggestion")
# The grades the behavior-inert prose cap can give a checklist FAIL (Phase 4.1.5).
CAP_GRADES = ("important", "suggestion")
# The report pieces ``render`` writes: one per severity group, one of INCONCLUSIVE rows, one for Run details.
PIECES = (*SEVERITIES, "informational", "run_details")
VERDICTS = ("PASS", "FAIL", "INCONCLUSIVE")
# The verdict contract ``--contract`` must name; normalize-verdicts.py's prepare and collect read it too.
CONTRACT = "2"
_RAISED_BY = re.compile(r"\(raised by \d+/\d+ agents?\)")
# The plain marker, or the older form carrying a `: <file>` field.
_CARVE_OUT = re.compile(r" \[self-contradicting-diff carve-out(?::[^\]\n]*)?\]")
_VC_REF = re.compile(r"VC-\d+")


def _paths(run_dir, n):
    j = posixpath.join
    return {"checklist": j(run_dir, f"checklist-iter-{n}.json"),
            "verification": j(run_dir, f"verification-iter-{n}.json"),
            "inputs": j(run_dir, f"normalize-inputs-iter-{n}.json"),
            "items": j(run_dir, f"checklist-iter-{n}.items"),
            "pieces": {k: j(run_dir, f"checklist-{k.replace('_', '-')}-iter-{n}.md") for k in PIECES},
            "retired": j(run_dir, f"checklist-section-iter-{n}.md"),
            "record": j(run_dir, f"checklist-render-iter-{n}.json"),
            "verdicts": j(run_dir, "verdicts", f"iter-{n}")}


def artifact_path(path):
    """``path`` host-absolute with ``/`` separators, a relative one joined to the working directory:
    the checkout root the engine runs these helpers from."""
    path = os.path.join(os.getcwd(), path.replace("\\", "/"))
    return (path if os.path.isabs(path) else os.path.abspath(path)).replace("\\", "/")


def _read_json(path, want):
    """(value, None) when ``path`` holds JSON of type ``want``; else (None, reason)."""
    try:
        with open(path, encoding="utf-8") as fh:
            value = json.load(fh)
    except FileNotFoundError:
        return None, f"{os.path.basename(path)} absent"
    except (OSError, ValueError) as e:
        return None, f"{os.path.basename(path)} unreadable ({type(e).__name__})"
    if not isinstance(value, want):
        return None, f"{os.path.basename(path)} is not a JSON {'array' if want is list else 'object'}"
    return value, None


def _write_atomic(path, text):
    tmp = f"{path}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _stored_rows(verification):
    """The artifact's rows with each verdict trimmed and upper-cased: ``(rows, None)``, or
    ``(None, reason)`` when a row is not an object, its verdict is not one of ``VERDICTS`` — a
    row read as anything but a FAIL would otherwise drop out of every REJECT operand — or its
    ``id`` is a list or object, which no id set or lookup below can hold."""
    rows = []
    for i, row in enumerate(verification):
        verdict = row.get("verdict") if isinstance(row, dict) else None
        verdict = verdict.strip().upper() if isinstance(verdict, str) else None
        if verdict not in VERDICTS:
            return None, f"verification row {i + 1} is not an object with a {'/'.join(VERDICTS)} verdict"
        if isinstance(row.get("id"), (list, dict)):
            return None, f"verification row {i + 1} has a list or object id"
        rows.append(dict(row, verdict=verdict))
    return rows, None


def _severity(row):
    sev = row.get("severity")
    sev = sev.lower() if isinstance(sev, str) else None
    return sev if sev in SEVERITIES else "critical"


def _at_or_above(sev, threshold):
    return SEVERITIES.index(sev) <= SEVERITIES.index(threshold)


def _grade(row, cap):
    """A FAIL's grade: its stored severity, or cap grade ``cap`` when that is the lower of the two."""
    sev = _severity(row)
    return cap if cap in CAP_GRADES and not _at_or_above(cap, sev) else sev


def _carried(item):
    """A seed whose ``prior_ref`` names a finding and whose copied line carries the carve-out marker
    after its last ``(raised by N/M agents)`` suffix and before any HTML comment: the inertness
    annotation's evidence is free text and can quote the marker."""
    ref, line = item.get("prior_ref"), item.get("prior_evidence")
    if not (isinstance(ref, str) and ref and not _VC_REF.fullmatch(ref) and isinstance(line, str)):
        return False
    suffixes = list(_RAISED_BY.finditer(line))
    if not suffixes:
        return False
    return _CARVE_OUT.search(line[suffixes[-1].end():].split("<!--", 1)[0]) is not None


def _shortfall(row):
    return row.get("verification_shortfall", "missing") is not None


def _items_by_id(checklist):
    out = {}
    for item in checklist or []:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            out.setdefault(item["id"], item)
    return out


def classify(verification, checklist, threshold, cap_grades=None):
    """The Phase 4.2 checklist operands (see the module docstring): ``reject_ids``, ``carried_ids``,
    ``shortfall_ids`` and ``none_verified``. ``cap_grades`` maps a capped FAIL's id to its cap grade.
    The rows are read through ``_stored_rows``; one it rejects raises ValueError."""
    rows, why = _stored_rows(verification)
    if rows is None:
        raise ValueError(why)
    items = _items_by_id(checklist)
    cap_grades = cap_grades or {}
    out = {"reject_ids": [], "carried_ids": [], "shortfall_ids": []}
    inconclusive = 0
    for row in rows:
        rid, item = row.get("id"), items.get(row.get("id"), {})
        if row["verdict"] == "FAIL":
            if _carried(item):
                out["carried_ids"].append(rid)
                out["reject_ids"].append(rid)
                continue
            if _at_or_above(_grade(row, cap_grades.get(rid)), threshold):
                out["reject_ids"].append(rid)
        elif row["verdict"] == "INCONCLUSIVE":
            inconclusive += 1
            if _shortfall(row):
                out["shortfall_ids"].append(rid)
    out["none_verified"] = bool(rows) and inconclusive == len(rows)
    return out


def _latest_iteration(run_dir):
    """(highest N with a ``verification-iter-<N>.json``, None) — N is None when there is none — or
    (None, reason) when the run dir cannot be listed."""
    best = None
    try:
        names = os.listdir(run_dir)
    except OSError as e:
        return None, f"run dir unlistable ({type(e).__name__})"
    for name in names:
        m = re.fullmatch(r"verification-iter-(\d+)\.json", name)
        if m and (best is None or int(m.group(1)) > best):
            best = int(m.group(1))
    return best, None


def checklist_reject_ids(run_dir, threshold):
    """IDs of the checklist FAILs that make an approve-family verdict wrong, read from the latest
    iteration: ``(ids, note)``, or ``(None, reason)`` when ``threshold`` is not one of
    ``SEVERITIES`` or the stored rows or their checklist cannot be read. No verification artifact at
    all (a run that owed no checklist) is ``([], None)``. Cap grades come from the render record;
    without a readable one nothing is capped, and ``note`` says why when a record that exists could
    not be used and an id is returned (it is None otherwise)."""
    if threshold not in SEVERITIES:
        return None, f"threshold {threshold!r} is not one of {'/'.join(SEVERITIES)}"
    n, why = _latest_iteration(run_dir)
    if why:
        return None, why
    if n is None:
        return [], None
    p = _paths(run_dir, n)
    verification, why = _read_json(p["verification"], list)
    if verification is not None:
        verification, why = _stored_rows(verification)
    if verification is None:
        return None, why
    checklist, why = _read_json(p["checklist"], list)
    if checklist is None:
        return None, why
    record, why = _read_json(p["record"], dict)
    recorded = record.get("capped") if record is not None else None
    if record is not None and not isinstance(recorded, dict):
        why = f"{os.path.basename(p['record'])} holds no capped object"
    cap_grades = ({k: g for k, g in recorded.items() if isinstance(g, str) and g in CAP_GRADES}
                  if isinstance(recorded, dict) else {})
    ids = classify(verification, checklist, threshold, cap_grades)["reject_ids"]
    unusable = why is not None and os.path.lexists(p["record"])
    return ids, (f"{why}, so no cap was applied" if ids and unusable else None)


# ── rendering ───────────────────────────────────────────────────────────────

def _one_line(text):
    return " ".join(str(text).split()) if text is not None else ""


def _uncomment(text):
    """``text`` with each HTML comment opener escaped: an unclosed one hides the rest of the page."""
    return text.replace("<!--", "&lt;!--")


def _unclose(text):
    """``text`` with each ``</details``, in any case, escaped: a raw one can close a
    ``<details>`` block the text sits in."""
    return re.sub(r"</(details)", r"&lt;/\1", text, flags=re.IGNORECASE)


def _where(item, row):
    """The headline's ``[file:line]`` suffix, its generator text escaped the way ``_claim`` is."""
    src = item.get("source_file")
    src = src if isinstance(src, str) and src else row.get("file_checked")
    if not isinstance(src, str) or not src:
        return ""
    line = item.get("source_line")
    if isinstance(line, int) and not isinstance(line, bool):
        where = f" [{src}:{line}]"
    elif isinstance(line, str) and line.strip():
        where = f" [{src}:{line.strip()}]"
    else:
        where = f" [{src}]"
    return _unclose(_uncomment(where))


_FENCE = re.compile(r"(`{3,}|~{3,})(.*)")


def _open_fence(lines):
    """The CommonMark fence (a backtick or tilde run) still open after ``lines``, else None."""
    fence = None
    for ln in lines:
        m = _FENCE.match(ln.lstrip())
        if not m:
            continue
        run, rest = m.groups()
        if fence is None:
            if not (run[0] == "`" and "`" in rest):  # a backtick info string never holds a backtick
                fence = run
        elif run[0] == fence[0] and len(run) >= len(fence) and not rest.strip():
            fence = None
    return fence


def _evidence_block(evidence):
    text = evidence if isinstance(evidence, str) and evidence.strip() else "(no evidence recorded)"
    lines = _unclose(text).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    fence = _open_fence(lines)
    if fence:
        lines.append(fence)
    body = "\n".join(("  " + ln) if ln.strip() else "" for ln in lines)
    return f"\n  <details><summary>Evidence</summary>\n\n{body}\n\n  </details>\n"


def _claim(item):
    """The item's claim on one line. It is generator text, so an HTML comment opener in it is
    escaped: a headline's trailing annotation is then only ever the one this module writes."""
    return _unclose(_uncomment(_one_line(item.get("claim")))) or "(claim unavailable)"


def _shown_id(row):
    """The row's id on one line, escaped the way ``_claim`` is."""
    return _unclose(_uncomment(" ".join(str(row.get("id")).split())))


def _headline(row, item, capped):
    rid, verdict = row.get("id"), row.get("verdict")
    claim = _claim(item)
    head = f"- {_shown_id(row)}: {verdict} ({_severity(row)}) — {claim}{_where(item, row)}"
    if verdict == "FAIL" and item.get("category") == "issue_acceptance":
        head += " — fix the code, or have the issue author amend this criterion"
    if verdict == "FAIL" and rid in capped:
        grade, evidence = capped[rid]
        limb_two = "held" if grade == "suggestion" else "not-held"
        head += (" [behavior-inert prose cap] <!-- inertness: first-conjunct=held limb-one=held "
                 f"limb-two={limb_two}; evidence: {_unclose(_one_line(evidence.replace('--', '—')))} -->")
    return head


def render_pieces(verification, checklist, capped):
    """``{key: (text, ids)}`` for each ``PIECES`` key (see the module docstring): the piece's text,
    empty when it holds nothing, and the ids of the items it lists with a headline and Evidence
    block. ``capped`` maps a capped FAIL's id to ``(cap grade, inertness evidence)``. The rows are
    read through ``_stored_rows``, as ``classify`` reads them; one it rejects raises ValueError."""
    rows, why = _stored_rows(verification)
    if rows is None:
        raise ValueError(why)
    items = _items_by_id(checklist)
    fails = [r for r in rows if r.get("verdict") == "FAIL"]
    passes = [r for r in rows if r.get("verdict") == "PASS"]
    unverified = [r for r in rows if r.get("verdict") not in ("PASS", "FAIL")]
    lines, ids = {k: [] for k in PIECES}, {k: [] for k in PIECES}
    # Keep every run_details line a list item: a plain line would join the bullet pasted above it.
    details = lines["run_details"]
    details.append(f"- Checklist: {len(passes)} passed, {len(fails)} failed, {len(unverified)} inconclusive")
    for row in fails + unverified:
        rid, item = row.get("id"), items.get(row.get("id"), {})
        if row.get("verdict") != "FAIL":
            key = "informational"
        else:
            key = _grade(row, capped.get(rid, (None,))[0])
        lines[key] += [_headline(row, item, capped), _evidence_block(row.get("evidence"))]
        ids[key].append(rid)
    if passes:
        # Keep the closer indented: at column 0 it falls outside the list item that opened the block.
        details.append(f"- <details><summary>✅ Passed items ({len(passes)} of {len(rows)})</summary>\n")
        for r in passes:
            item = items.get(r.get("id"), {})
            claim = _claim(item)
            label = "NORMALIZED (wording-only) — " if r.get("normalized") is True else ""
            details.append(f"  - {_shown_id(r)}: {label}{claim}{_where(item, r)}")
        details.append("\n  </details>")
    return {k: (_piece_text(lines[k]), ids[k]) for k in PIECES}


def _piece_text(lines):
    """The lines as one piece: no run of blank lines, one trailing newline, empty for no lines."""
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n")
    return text + "\n" if text else ""


def _prior_lines(work_dir):
    """Phase 1's ``checklist prior-lines`` output, read through its own module."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import checklist_finalize
        # The record sits in the run dir, the work dir's parent, as `checklist prior-lines` reads it.
        _, prior_run_dir, err = checklist_finalize._confined(work_dir)
        if err:
            return [f"prior-report: unavailable ({err})"]
        lines = checklist_finalize.op_prior_lines(prior_run_dir).get("lines")
    except Exception as e:  # an unloadable sibling is a reported shortfall, never a crash
        return [f"prior-report: unavailable (prior-lines failed: {type(e).__name__}: {_one_line(e)})"]
    if not isinstance(lines, list) or not lines:
        return ["prior-report: unavailable (helper did not run)"]
    return [str(x) for x in lines]


_SKIPPED = {"intentional": "small config-only diff (Phase 0.5)", "failure": "checklist generation failed"}


def _read_text(path):
    """(text, None) for a readable UTF-8 file (BOM dropped, newlines universal); else (None, reason)."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return fh.read(), None
    except (OSError, UnicodeDecodeError) as e:
        return None, f"{path} unreadable ({type(e).__name__})"


def render(run_dir, n, threshold, capped_file, prior_dir, skipped=None):
    p = _paths(run_dir, n)
    stuck = []
    for earlier in (*p["pieces"].values(), p["retired"], p["record"]):  # each is tried before a failure is reported
        try:
            os.remove(earlier)
        except FileNotFoundError:
            pass
        except OSError as e:
            stuck.append(f"{earlier} ({type(e).__name__})")
    if stuck:
        return {"status": "error", "reason": "could not remove " + ", ".join(stuck)}, 1
    warnings = []
    capped_lines = []
    if capped_file is not None:
        text, why = _read_text(capped_file)
        if text is None:
            return {"status": "error", "reason": f"--capped-file {why}"}, 1
        capped_lines = [ln for ln in text.split("\n") if ln.strip()]
    if skipped:
        verification, checklist = [], []
    else:
        verification, why = _read_json(p["verification"], list)
        if verification is not None:
            verification, why = _stored_rows(verification)
        if verification is None:
            return {"status": "error", "reason": why}, 1
        checklist, why = _read_json(p["checklist"], list)
        if checklist is None:
            return {"status": "error", "reason": why}, 1
    fail_ids = {r.get("id") for r in verification if isinstance(r, dict) and r.get("verdict") == "FAIL"}
    capped = {}
    for line in capped_lines:
        head, _, evidence = (part.strip() for part in line.partition(":"))
        rid, _, grade = head.partition(" ")
        if rid not in fail_ids:
            warnings.append(f"capped {rid!r}: not a stored FAIL — ignored")
        elif grade.strip() not in CAP_GRADES:
            warnings.append(f"capped {rid!r}: no cap grade ({' or '.join(CAP_GRADES)}) — ignored")
        elif not evidence:
            warnings.append(f"capped {rid!r}: no inertness evidence — ignored")
        elif rid in capped and capped[rid][0] != grade.strip():
            warnings.append(f"capped {rid!r}: listed with both cap grades — weighed as important")
            capped[rid] = ("important", capped[rid][1] if capped[rid][0] == "important" else evidence)
        else:
            capped[rid] = (grade.strip(), evidence)
    cap_grades = {rid: grade for rid, (grade, _) in sorted(capped.items())}
    result = classify(verification, checklist, threshold, cap_grades)
    prior = _prior_lines(prior_dir) if prior_dir else []
    record = {"capped": cap_grades}
    pieces = render_pieces(verification, checklist, capped)
    if skipped:
        pieces["run_details"] = (f"- Checklist not run: {_SKIPPED[skipped]}.\n", [])
    try:
        for key, (text, _) in pieces.items():
            _write_atomic(p["pieces"][key], text)
        _write_atomic(p["record"], json.dumps(record, indent=1) + "\n")
    except OSError as e:
        return {"status": "error", "reason": f"could not write a piece or the record ({e})"}, 1
    out = {"status": "ok",
           "pieces": {k: {"path": p["pieces"][k], "count": len(ids), "ids": ids} for k, (_, ids) in pieces.items()},
           **{k: result[k] for k in ("reject_ids", "carried_ids", "shortfall_ids", "none_verified")},
           "prior_lines": prior,
           "prior_shortfall": any(ln.startswith(("prior-report: unavailable", "seed shortfall:"))
                                  for ln in prior),
           "warnings": warnings}
    return out, 0


# ── re-verification registration ────────────────────────────────────────────

def reverify_add(path_safe, fresh_agent, redirect, run_dir, n, item_id, threshold, counter_reading):
    """Register one dispute (see the module docstring). ``path_safe(token)`` says whether a token
    is usable as a file-name part, ``fresh_agent(item)`` whether an agent verifies a checklist
    item and ``redirect(verdicts_dir, id, item file)`` points an item file at its next free
    attempt; normalize-verdicts.py passes its ``_path_safe``, ``_fresh_agent`` and ``_redirect``."""
    p = _paths(run_dir, n)
    loaded = {}
    for key, want in (("checklist", list), ("verification", list)):
        loaded[key], why = _read_json(p[key], want)
        if why:
            return {"status": "refused", "reason": why}, 1
    checklist, verification = loaded["checklist"], loaded["verification"]
    inputs = {}
    if os.path.lexists(p["inputs"]):
        inputs, why = _read_json(p["inputs"], dict)
        if why:
            return {"status": "refused", "reason": why}, 1
    verification, why = _stored_rows(verification)
    if verification is None:
        return {"status": "refused", "reason": why}, 1
    if not path_safe(item_id):
        return {"status": "refused", "reason": "item id is not a usable file-name part"}, 1
    item_path = artifact_path(posixpath.join(p["items"], f"{item_id}.json"))
    slots = [it for it in checklist if isinstance(it, dict) and it.get("id") == item_id]
    rows = [r for r in verification if isinstance(r, dict) and r.get("id") == item_id]
    prior = inputs.get("reverify")
    item_file, item_why = _read_json(item_path, dict)
    if len(slots) != 1 or len(rows) != 1:
        why = "item id is not on exactly one checklist item and verification row"
    elif not fresh_agent(slots[0]):
        why = "item is a carried PASS"
    elif rows[0].get("verdict") != "FAIL":
        why = f"stored verdict is {rows[0].get('verdict')}, not FAIL"
    elif not _at_or_above(_severity(rows[0]), threshold):
        why = f"stored severity {_severity(rows[0])} is below the threshold {threshold}"
    elif prior is not None and not isinstance(prior, dict):
        why = "the inputs file's reverify value is not an object"
    elif isinstance(prior, dict) and item_id in prior:
        why = "this item was already re-verified in this entry"
    else:
        why = item_why
    if why:
        return {"status": "refused", "reason": why}, 1
    k, item_file = redirect(p["verdicts"], item_id, item_file)
    row = rows[0]
    inputs["reverify"] = dict(prior or {}, **{item_id: {"attempt": k, "counter_reading": counter_reading}})
    item_file.update(dispute=[
        f"Disputed: FAIL ({_severity(row)}) — {_one_line(row.get('evidence'))}",
        f"Counter-reading: {counter_reading}"])
    # Register last: a failed write leaves no registration, so a retry is not refused.
    for path, value, label in ((item_path, item_file, "item file"), (p["inputs"], inputs, "inputs file")):
        try:
            _write_atomic(path, json.dumps(value, indent=1, ensure_ascii=False) + "\n")
        except OSError as e:
            return {"status": "refused", "reason": f"{label} not writable ({e})"}, 1
    return {"status": "ok", "id": item_id, "attempt": k, "item": item_path, "verdict_file": item_file["verdict_file"]}, 0


# ── CLI (routed from normalize-verdicts.py) ─────────────────────────────────

def _flags(argv, names):
    positional, flags = [], {}
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok in names:
            if i + 1 >= len(argv):
                return None, None, f"{tok} needs a value"
            if tok in flags:
                return None, None, f"{tok} given twice"
            else:
                flags[tok] = argv[i + 1]
            i += 2
        elif tok.startswith("--"):
            return None, None, f"unknown flag {tok}"
        else:
            positional.append(tok)
            i += 1
    return positional, flags, None


def main(op, argv, path_safe, fresh_agent, redirect):
    """Run ``render`` or ``reverify-add``; returns ``(output dict, exit code)``. ``path_safe``,
    ``fresh_agent`` and ``redirect`` are ``reverify_add``'s."""
    if op == "render":
        pos, flags, err = _flags(argv, ("--contract", "--threshold", "--capped-file", "--prior", "--skipped"))
        usage = (f"render <run-dir> <N> --contract {CONTRACT} --threshold {'|'.join(SEVERITIES)} "
                 "[--capped-file <path>] [--prior <phase1-work-dir>] [--skipped intentional|failure]")
    else:
        pos, flags, err = _flags(argv, ("--contract", "--threshold", "--counter-reading-file"))
        usage = (f"reverify-add <run-dir> <N> <item-id> --contract {CONTRACT} "
                 f"--threshold {'|'.join(SEVERITIES)} --counter-reading-file <path>")
    want = 2 if op == "render" else 3
    if err is None and flags.get("--contract") != CONTRACT:
        err = f"--contract {CONTRACT} is required"
    if err is None and (len(pos) != want or not pos[1].isascii() or not pos[1].isdigit() or int(pos[1]) < 1):
        err = "wrong positional arguments"
    if err is None and flags.get("--threshold") not in SEVERITIES:
        err = f"--threshold must be one of {'|'.join(SEVERITIES)}"
    if err is None and op == "render" and flags.get("--skipped") not in (None, *_SKIPPED):
        err = "--skipped must be intentional or failure"
    if err is None and op != "render":
        path = flags.get("--counter-reading-file")
        reading, why = _read_text(path) if path is not None else (None, "is required")
        reading = _one_line(reading)
        if not reading:
            err = f"--counter-reading-file {why or 'holds no sentence'}"
    if err is not None:
        return {"status": "usage", "reason": f"{err}; usage: {usage}"}, 2
    if op == "render":
        return render(pos[0], int(pos[1]), flags["--threshold"], flags.get("--capped-file"),
                      flags.get("--prior"), flags.get("--skipped"))
    return reverify_add(path_safe, fresh_agent, redirect, pos[0], int(pos[1]), pos[2],
                        flags["--threshold"], reading)
