#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""PRFlow checklist-verdict helper: Phase 2's dispatch plan, wave barrier and collector.

The checklist-verifier answers one verdict: PASS, FAIL, INVALID or INCONCLUSIVE. This helper owns
the parse contract and maps each answer to a stored verdict (*Stored verdicts* below).
Its own modes use the stdlib and the sibling ``verdict_report.py``'s severity ladder and path spelling, read no config and make no ``gh``/network/``git`` calls; the
``checklist`` route below is not bound by this.

Contract. ``prepare``, ``collect``, ``render`` and ``reverify-add`` each require ``--contract 2``
and refuse a call without it as a usage error (exit 2). The check binds only these CLI calls: an
in-process reader such as ``review-evidence-gate.py`` imports ``verdict_report`` and reads the
stored artifact with no contract check.

Layout. ``prepare`` and ``collect`` also take ``--checklist <run-dir>/checklist-iter-<N>.json`` and
derive the rest from it: ``<run-dir>/verdicts/iter-<N>/`` (verdict files), the item directory
``<run-dir>/checklist-iter-<N>.items/``, ``<run-dir>/verification-iter-<N>.json`` (the stored
artifact), the optional inputs file ``<run-dir>/normalize-inputs-iter-<N>.json``,
``<run-dir>/engine-setup.json`` and ``<run-dir>/criteria.json``. Paths a verifier reads or
writes are host-absolute: ``prepare``'s ``items_dir``, each item file's ``head_view``,
``base_view``, ``diff``, ``criteria_file`` and ``verdict_file``, and a retry's ``item`` and
``verdict_file``. A relative path joins the working directory, the checkout root the engine runs
this helper from. Every other path is printed as given. All use ``/`` separators; source
citations are not rewritten. Each prints one JSON line whose ``status`` is ``ok`` (exit 0), ``error``
(exit 1, with ``error`` and ``detail``) or ``usage`` (exit 2: bad arguments, or a path outside
a ``.prflow/tmp/`` pair or not named as above).

Verdict files are attempt files, ``<id>.a<k>.json`` (k from 1): every dispatch of an item
writes its own, so one entry's re-dispatch, re-verification and late writer never share
a file. An earlier entry's verifier still running at this N can share one; issue #1880 accepts
that.

Prepare — run before an engine entry's first verifier dispatch. It empties the verdict and item
directories (regular files and symlinks only; nothing outside them) and removes the inputs file,
so an earlier entry's replies at this N never answer this entry's ids, then writes one item file
``<items>/<id>.json`` per fresh item (every item but a carried PASS): the checklist item plus
these helper-owned keys, overwriting a generator-supplied value of any of them:

    verdict_file, attempt     the next dispatch's verdict file, and the k collect grades (both 1
                              here; a re-verification moves only verdict_file)
    head_view, base_view      the source views and their revisions, from engine-setup.json
    head_sha, base_sha, diff
    grading_rules             the paragraphs of skills/review/verifier-rules/<name>.md the item
                              needs: issue-acceptance.md for an issue_acceptance item or one a
                              Stricter disclosure reaches, prior-ref.md for an item carrying
                              prior_ref or prior_evidence, rejected-finding.md for an item
                              carrying rejections
    disclosed, criteria_file  the disclosures reaching the item, and the criteria path (an
                              issue_acceptance or disclosed item, and an item carrying prior_ref
                              or prior_evidence when criteria.json is usable, below)
    rejections                the counted rejection lines (*Rejections* below), on every item
                              but an issue_acceptance one

criteria.json is read once and is usable as a non-empty list of ``{criterion: <integer>, text:
<string>}`` objects. With an item carrying prior_ref or prior_evidence, a present file that is not
usable adds a ``warnings`` line naming why; an absent file, Phase 0.4's no-criteria state, adds none.

Disclosures (PR mode): each line of the setup record's PR-body file, CR stripped, that starts at
column 0 with ``Stricter than criterion ``. It counts only when it begins
``Stricter than criterion "<T>": `` with T the ``text`` of a criteria.json entry (each entry's
text matched against the line, never a parsed delimiter) whose ``criterion`` N has an
``issue-acceptance-N`` item; it then reaches that item, with N, and every prior_ref item.

Rejections (PR mode): each distinct line of that file, CR stripped, starting at column 0 with
``Finding rejected "`` and holding ``": `` after it, in body order. They count only when the
setup record's ``pr.author_trust`` is ``trusted``. Otherwise none counts, and ``uncounted`` names
the first case that applies, in ``counted_rejections``' order: ``pr`` null, missing or not an
object; the body unread (a ``pr`` without ``body`` included); no candidate line; then the stored
trust outcome — absent, not a string, ``lookup-failed: <reason>``, ``untrusted``,
``not-looked-up`` (setup saw no candidate line) or any other value. Each case's emitted text is
the string ``counted_rejections`` returns for it.

It prints ``{"status": "ok", "iteration", "items_dir", "verdicts_dir", "agent": [ids],
"reused": [ids], "counts": {"agent", "reused"}, "disclosures": [{"line", "kind", "criterion",
"reached", "ignored"}], "pr_body": "read"|"unread"|"none", "rejections": {"lines",
"uncounted"}, "wiped", "warnings"}``. It refuses
(``error``) an unusable checklist, setup record or rules file, an inputs file it cannot remove
(``inputs_file_unremoved``), and an item file it cannot write.

Wait — ``wait --verdicts-dir <dir> --expect <name>... --deadline <s> [--idle <s>]``: the barrier
of Phase 1's generators and Phase 2's verifiers. It lists ``<dir>`` about once a second until a
regular file named exactly ``<name>.json`` exists for every expected name (``batch-<k>``,
``<id>.a<k>``), ``<s>`` seconds elapse, ``--idle`` seconds pass after the latest arrival (a
verifier that returned without writing never arrives), or ``<dir>`` exists but cannot be listed.
It reads no file's contents. Prints ``{"present", "missing", "waited_s", "deadline_hit",
"idle_hit"}`` (exit 0); ``deadline_hit`` is true whenever a name is missing. A missing
``--verdicts-dir``/``--deadline``, no name, a non-integer deadline or idle, or any other token is
a usage refusal (exit 2).

Collect — grades every fresh item and writes the verification artifact (root: the array, in
checklist order). A fresh item's answer is its item file's attempt file; else its
``response_text`` reply from the inputs file when it holds an object whose ``verdict`` is
one of ``VERDICT_ENUM`` and no mismatched id; else the latest usable earlier
attempt file (a late writer); else the reply. The inputs file is
optional: ``response_text`` (``{"<id>": "<reply>"}``), ``reverify`` (``{"<id>": {"attempt":
k, "counter_reading": "<sentence>"}}``) and ``agent_id`` (``{"<id>": "<the agent id its Agent
dispatch returned>"}``); any other key, or an unusable value, is ignored with an
``input_warnings`` line.

``needs_retry`` lists kind ``verdict`` (a verdict defect, or ``verdict_file_absent``: a reply
naming its own unwritten attempt file with no valid verdict) and kind ``delivery`` (an absent
attempt file with an original ``agent_id``;
``defect: verdict_file_absent``), plus ``channel`` and ``helper_internal``, which are never
re-dispatched. Delivery takes precedence over semantic retry, once per Phase 2 attempt.
Its entry carries ``agent_id``, ``item`` and the same
``verdict_file``; the engine sends that verifier the delivery message in
``skills/review/phases/phase-2-verification.md`` §2.2.
Collect marks ``delivery: true`` without changing the attempt or source views. A usable
reply is saved as ``delivery_answer``: it remains the grading source, and the file
must agree on ``_DELIVERY_OPERANDS``. Otherwise the exclusive ``delivery_file_only: true``
mode admits only the assigned file. The explicit flag
distinguishes deliberate file-only recovery from corrupt saved-answer state.
Absent files after a spent delivery draw a warning, no continuation or semantic retry. With
no original id, a valid reply is marked spent immediately; an unusable
reply retains its bounded semantic retry, then marks missing delivery spent.
An unreadable file keeps its channel-error route. Corrupt saved state or changed saved-answer
operands store INCONCLUSIVE without semantic retry.
A readable malformed file in file-only mode can use an unspent semantic retry. A recovery
state write failure stops collection with ``status: error`` and ``delivery_state_write_failed``.
Before printing, collect points each listed ``verdict`` item's file at its next
attempt with no file yet, so the engine
re-dispatches it with the same prompt; the entry carries that ``item`` path and the attempt's ``verdict_file``. An
item file that cannot be rewritten, or a verdict defect that persists after its re-dispatch,
adds one ``input_warnings`` line instead.

Every stored row carries ``verification_shortfall``: ``checklist-element`` (a non-object
checklist element), ``no-usable-verdict`` (no usable verifier verdict), ``verifier-read-failed``
(an INCONCLUSIVE answer whose ``read_failed`` is present and not ``false``/``null``; a value
other than JSON ``true`` adds an ``input_warnings`` line) or ``null``. ``read_failed`` on a PASS,
FAIL or INVALID answer changes nothing and adds an ``input_warnings`` line. ``severity`` stores the
verifier's grade lower-cased, ``critical`` for an invalid or missing one, an unusable answer and
an ``issue_acceptance`` item.

``reverify`` (Phase 4.1) grades attempt k of a fresh item whose stored verdict is FAIL like a
first answer (never from a reply) and replaces the stored row only with a PASS or FAIL, which
keeps the replaced row's ``findings``; each
entry, used or ignored, writes one ``input_warnings`` line beginning ``re-verification <id>: ``; a replacement
adds nothing to ``counts``.

Findings: defects a verifier reports beside its verdict. A row stored from a usable answer
carries ``findings`` when that answer's ``findings`` array holds at least one object with a
non-empty string ``description``; each is stored with ``item_id`` set to the item's id and
``severity`` read as the verdict's is (an untrusted channel included). A missing array stores
none. A non-array value and each other record are dropped with an ``input_warnings`` line,
never a retry. Other fields pass through unchecked: Phase 3 reads them as a reviewer finding's.

Collect prints ``{"status": "ok", "written", "tally": {"pass", "fail", "inconclusive", "agent",
"reused"}, "counts": {"normalized_count"}, "needs_retry",
"non_pass", "findings", "input_warnings"}`` (``findings``: every stored row's, in checklist
order), or ``error`` when the checklist is unusable or the artifact cannot be written.

Grading. Verdict bytes come from exactly the named verdict file, else the reply.
Parse order: a whole text that parses as a JSON object; else line-start ``json`` fences, the
LAST authoritative; else exactly one parseable object; else ``missing_fence``. Verdict defects
(kind ``verdict``): ``missing_fence``, ``unparseable_json``, ``missing_verdict_field``,
``non_enum_verdict``, ``id_mismatch``, ``no_verdict``, and ``no_verdict_trusted_file_unreadable``
(the named file exists but cannot be read and the reply holds no object). A file present but
unreadable is ``defect_class: "channel"`` (``trusted_file_unreadable``) in every verdict
direction; an exception on one pair is ``helper_internal`` (``pair_processing_error``, with a
traceback on stderr) and never aborts the rest.

Stored verdicts: a usable answer is graded on its ``verdict``; no qualifying field
(``read_failed``, ``severity``, ``file_checked``) grades it, but an ``id`` mismatch is a verdict
defect and the delivery-recovery checks above can store INCONCLUSIVE instead. PASS, FAIL and
INCONCLUSIVE are otherwise stored as answered. INVALID (only the generated
claim is wrong) is never stored: it becomes PASS with ``normalized: true``, ``raw_verdict:
"INVALID"`` and the ``NORMALIZED (wording-only): `` evidence prefix when ``_invalid_blockers``
names no blocker and the trusted file was not unreadable, and FAIL otherwise, the reason in
``normalization_ineligible`` and an ``INVALID answer stored FAIL (<reason>): `` evidence prefix.

``checklist <op> …`` routes to the Phase 1 assembly in the sibling ``checklist_finalize.py``, and
``render`` and ``reverify-add`` to Phase 4's reads in the sibling ``verdict_report.py`` (each
documented there). They ride this helper because every cloud profile grants its leading token.

Exit codes: 0 ok; 1 unsupported Python, a ``verdict_report.py`` beside this file that is missing
or raises on import, or a prepare/collect error; 2 bad arguments, or a first word that is not
``prepare``, ``collect``, ``wait``, ``checklist``, ``render`` or ``reverify-add`` (a newer
subcommand included), with a ``status: usage`` line on stdout.
"""

import itertools
import json
import os
import posixpath
import re
import sys
import time
import traceback

if sys.version_info < (3, 11):  # fail fast, before any PEP 604 annotation below
    # Print the bad-input-shaped object on STDOUT too. A non-zero exit with byte-empty
    # stdout lands in the engine's "everything-else" arm, whose prescribed warning names
    # the cloud GRANT keys as the remedy — so a Python-version mismatch would be
    # reported to the operator as a permission problem. Emitting on stdout routes it to
    # the bad-input arm, where the remedy quoted is the real one.
    print(json.dumps({"bad_input": True, "error": "unsupported_python",
                      "detail": "Python 3.11+ required (found {}.{}.{})".format(*sys.version_info[:3])}, indent=2))
    sys.stderr.write(
        "prflow: Python 3.11+ required (found {}.{}.{}).\n".format(*sys.version_info[:3])
    )
    sys.exit(1)

def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


# The severity ladder and artifact-path spelling have one home, the sibling verdict_report.py. A by-path import of this file
# (the tests) does not put scripts/ on sys.path, so put it there first.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from verdict_report import CONTRACT, VERDICTS
    from verdict_report import SEVERITIES as SEVERITY_ENUM
    from verdict_report import artifact_path as _artifact_path
except Exception as _exc:  # a missing sibling, or one that raises on import (a SyntaxError too)
    # On stdout too, for the reason the Python-version arm above gives.
    print(json.dumps({"bad_input": True, "error": "verdict_report_unimportable",
                      "detail": f"verdict_report.py beside this file: {_exc}"[:200]}, indent=2))
    sys.stderr.write(f"prflow: normalize-verdicts.py could not import verdict_report.py beside it ({_exc}).\n")
    sys.exit(1)
NORMALIZED_PREFIX = "NORMALIZED (wording-only): "
# What a verifier may answer: the stored verdicts plus INVALID, which is mapped and never stored.
VERDICT_ENUM = (*VERDICTS, "INVALID")


def _brace_objects(text):
    """Return every top-level balanced ``{...}`` substring of ``text`` that parses
    as a JSON dict, in order. String contents (and escaped quotes/braces inside
    them) are respected so a ``{`` inside a JSON string never opens a candidate."""
    objs = []
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start != -1:
                candidate = text[start:i + 1]
                try:
                    parsed = json.loads(candidate)
                except (ValueError, RecursionError):
                    parsed = None
                if isinstance(parsed, dict):
                    objs.append(parsed)
                start = -1
    return objs


_FENCE_OPEN = re.compile(r"(?:^|\n)[ \t]*```json")
_FENCE_CLOSE = re.compile(r"```[ \t]*(?=\r?\n|$)")


def _json_fences(text):
    """Return the inner text of each ```` ```json ... ``` ```` fence, in order.

    An opener counts only at a line start; a closer is the first ```` ``` ```` that ends
    a line before the next counted opener (a span with none is dropped). A valid JSON
    string holds no raw newline, so neither marker quoted inside one ever counts. The
    scan is not string-aware: a malformed string with raw newlines can still expose a
    quoted fence."""
    openers = list(_FENCE_OPEN.finditer(text))
    fences = []
    for i, opened in enumerate(openers):
        end = openers[i + 1].start() if i + 1 < len(openers) else len(text)
        span = text[opened.end():end]
        closed = _FENCE_CLOSE.search(span)
        if closed is not None:
            fences.append(span[:closed.start()])
    return fences


def extract_verdict_object(text):
    """Parse the verdict object out of verifier bytes (a file's content or a
    transcribed response). Returns ``(obj, defect)`` — exactly one is None.

    Parse contract, in order: a whole text that parses as a JSON object is the
    verdict; else line-start ``json`` fences (LAST authoritative); else exactly one
    parseable JSON object in the body; otherwise ``missing_fence``."""
    if text is None:
        return None, "no_verdict"
    try:
        whole = json.loads(text)
    except (ValueError, RecursionError):
        whole = None
    if isinstance(whole, dict):
        return whole, None
    fences = _json_fences(text)
    if fences:
        chosen = fences[-1].strip()
        try:
            obj = json.loads(chosen)
        except (ValueError, RecursionError):
            return None, "unparseable_json"
        if not isinstance(obj, dict):
            return None, "unparseable_json"
        return obj, None
    objs = _brace_objects(text)
    if len(objs) == 1:
        return objs[0], None
    # zero parseable objects, or an ambiguous multiple — neither is a verdict.
    return None, "missing_fence"


def _severity(obj):
    """Return ``(severity, defect)``: a valid token in any letter case, lower-cased, with
    ``defect`` None; otherwise ``"critical"`` and the cause for the ``input_warnings`` line."""
    val = obj.get("severity")
    if isinstance(val, str) and val.lower() in SEVERITY_ENUM:
        return val.lower(), None
    return "critical", f"{_shape('severity' in obj, val)} is not one of {'|'.join(SEVERITY_ENUM)}"


def _read_verdict_bytes(pair):
    """Return ``(text, source)`` — the verdict bytes and their channel. Reads ONLY
    the exact ``verdict_path`` named in this pair (ignoring every unnamed file);
    falls back to the transcribed ``response_text`` when no readable file exists.

    An ABSENT file is the fallback and yields ``source == "response_text"``; ``collect``
    decides its re-dispatch.
    A file that is PRESENT but unreadable (permission error or invalid UTF-8) is an
    anomaly — the trusted channel was abandoned — so it yields
    ``source == "response_text_file_unreadable"`` (still a response_text read) so the
    downgrade off the verdict file is observable, never silent.

    A spent delivery's readable file only proves delivery: the bytes graded are its
    ``recorded_answer`` (``collect`` checks the file's grading operands against it)."""
    downgraded = False
    path = pair.get("verdict_path")
    if isinstance(path, str) and path:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            recorded = pair.get("recorded_answer")
            return (recorded if isinstance(recorded, str) else text), "file"
        except FileNotFoundError:
            pass  # file absent -> response_text fallback; collect decides re-dispatch
        except (OSError, UnicodeDecodeError, ValueError):
            # ValueError is NOT an OSError subclass: an embedded NUL in the
            # LLM-transcribed path (json.loads accepts it) makes open() raise
            # `ValueError: embedded null byte`. Uncaught it aborts the whole batch
            # with EMPTY stdout — which this helper's own contract reads as a
            # matcher denial, steering a debugger at a non-existent grant problem.
            downgraded = True  # present but unreadable -> surface the downgrade
    rt = pair.get("response_text")
    if isinstance(rt, str):
        return rt, ("response_text_file_unreadable" if downgraded else "response_text")
    return None, ("none_file_unreadable" if downgraded else "none")


def _verdict_defect(result, item_id, defect):
    """Stamp a verdict-defect result; returns it with its full-re-dispatch retry entry."""
    result["defect"] = defect
    result["defect_class"] = "verdict"
    result["severity"] = "critical"
    result["normalization_ineligible"] = f"verdict defect: {defect}"
    return result, {"id": item_id, "kind": "verdict", "defect": defect}


def _verdict_fields_defect(obj, item_id):
    """Mandatory verdict and optional id validation for a parsed answer object."""
    if "verdict" not in obj:
        return "missing_verdict_field"
    raw = obj["verdict"]
    if not isinstance(raw, str) or raw not in VERDICT_ENUM:
        return "non_enum_verdict"
    obj_id = obj.get("id")
    if item_id is not None and obj_id is not None and obj_id != item_id:
        return "id_mismatch"
    return None


def _invalid_blockers(item):
    """Why an INVALID answer on ``item`` is stored FAIL, not the wording-only PASS; empty when
    nothing blocks. A re-check item's claim is helper-written, so its ``generated_paraphrase``
    label does not make it eligible."""
    blockers = []
    provenance = item.get("claim_provenance")
    if item.get("verification_mode") != "agent":
        blockers.append("not agent")
    if item.get("category") == "issue_acceptance":
        blockers.append("issue_acceptance category")
    if provenance != "generated_paraphrase":
        blockers.append(f"claim_provenance {provenance}" if isinstance(provenance, str)
                        else "claim_provenance invalid" if "claim_provenance" in item
                        else "claim_provenance absent")
    if _rechecks(item):
        blockers.append("re-checks a prior finding")
    return blockers


def _process_pair(pair):
    """Return ``(result_dict, retry_entry_or_None)`` for one pair."""
    item = pair.get("item") if isinstance(pair.get("item"), dict) else {}
    item_id = item.get("id")

    text, source = _read_verdict_bytes(pair)
    obj, defect = extract_verdict_object(text)
    # The named verdict file EXISTED but could not be read, so the verdict bytes came off
    # the reply channel. Stamped unconditionally below, in EVERY verdict direction, so a
    # PASS read that way is never silent.
    trusted_channel_lost = source in ("response_text_file_unreadable",
                                      "none_file_unreadable")

    result = {
        "id": item_id,
        "raw_verdict": None,
        "verdict": None,
        "normalized": False,
        "evidence": None,
        "file_checked": None,
        "source": source,
        "defect": None,
        "defect_class": None,
        "normalization_ineligible": None,
    }

    # --- verdict-defect arm: keep no verdict, flag for a full re-dispatch ----
    if defect is not None:
        if trusted_channel_lost:
            # Discriminate "the verifier produced nothing anywhere" from "the named
            # verdict file EXISTS but this process cannot read it" (permission fault,
            # corrupt mount, invalid UTF-8). Collapsing them onto the reply's own parse
            # defect (no_verdict, missing_fence, unparseable_json) sends the engine's kind-`verdict` remedy at a re-dispatch that will
            # re-produce a file it still cannot read — burning a retry on a
            # filesystem fault the verifier cannot fix.
            defect = "no_verdict_trusted_file_unreadable"
        return _verdict_defect(result, item_id, defect)
    defect = _verdict_fields_defect(obj, item_id)
    if defect is not None:
        return _verdict_defect(result, item_id, defect)
    raw = obj["verdict"]

    evidence = obj.get("evidence")
    result["raw_verdict"] = raw
    result["verdict"] = raw  # an INVALID is mapped below; it is never stored
    result["evidence"] = evidence if isinstance(evidence, str) else None
    fc = obj.get("file_checked")
    result["file_checked"] = fc if isinstance(fc, str) else None
    # collect pops _read_failed (the verifier's read_failed operand) and _findings; a result that
    # skips run_pairs would serialize them.
    result["_read_failed"] = ("read_failed" in obj, obj.get("read_failed"))
    result["_findings"] = ("findings" in obj, obj.get("findings"))
    # run_pairs pops _severity_defect; a result that skips run_pairs would serialize it.
    result["severity"], result["_severity_defect"] = _severity(obj)
    if trusted_channel_lost:  # a fallback-channel grade is untrusted, like its verdict
        result["severity"] = "critical"

    if raw == "INVALID":
        blockers = _invalid_blockers(item)
        # A lost trusted channel stores FAIL too; the channel stamp below writes its note.
        if blockers or trusted_channel_lost:
            result["verdict"] = "FAIL"
            result["normalization_ineligible"] = "; ".join(blockers)
            # The report renders evidence, not normalization_ineligible: name the reason there.
            why = "; ".join(["trusted verdict file present but unreadable"] * trusted_channel_lost
                            + blockers)
            result["evidence"] = f"INVALID answer stored FAIL ({why}): " + (result["evidence"] or "")
        else:
            result["verdict"] = "PASS"
            result["normalized"] = True
            result["evidence"] = NORMALIZED_PREFIX + (result["evidence"] or "")

    retry = None
    if trusted_channel_lost:
        # Stamped in every verdict direction, so a PASS read off the reply is never silent.
        result["defect"] = "trusted_file_unreadable"
        result["defect_class"] = "channel"
        result["normalization_ineligible"] = "; ".join(
            ["trusted verdict file present but unreadable"]
            + ([result["normalization_ineligible"]] if result["normalization_ineligible"] else []))
        retry = {"id": item_id, "kind": "channel", "defect": "trusted_file_unreadable"}

    return result, retry


def run_pairs(pairs):
    """Grade the ``{"item", "verdict_path", "response_text"}`` pairs ``collect`` derives."""
    results = []
    needs_retry = []
    severity_defects, read_failed, findings = {}, {}, {}
    for idx, pair in enumerate(pairs):
        try:
            result, retry = _process_pair(pair)
        except Exception as e:
            # One corrupt element must never abort the batch. An uncaught exception
            # here exits non-zero with EMPTY stdout, and empty stdout is exactly what
            # this helper's contract reads as a matcher denial — so every OTHER pair's
            # verdict is lost AND the failure is misattributed to a missing grant.
            # DEFENCE IN DEPTH: no known input reaches this arm (every operand in
            # _process_pair is isinstance-guarded and open() is fully wrapped), so its
            # realistic trigger is a future programming error in THIS file — which is
            # why it writes a real traceback to stderr rather than only a JSON field,
            # and why its defect_class is `helper_internal`, NOT `verdict`: the engine's
            # kind-`verdict` remedy re-dispatches the verifier subagent, which cannot
            # fix a bug in this helper. Proven live by the mutation control in
            # lib/test/python_scripts_part3/normalize_verdicts.py.
            sys.stderr.write(
                "normalize-verdicts.py: internal error processing pair index "
                f"{idx} — this is a helper defect, not a verifier defect:\n"
                + traceback.format_exc()
            )
            results.append({
                "id": (pair.get("item") or {}).get("id")
                      if isinstance(pair.get("item"), dict) else None,
                "raw_verdict": None, "verdict": None, "normalized": False,
                "evidence": None, "file_checked": None, "severity": "critical", "source": "none",
                "defect": "pair_processing_error", "defect_class": "helper_internal",
                # The detail is exception-derived from PR-author-influenced verdict text,
                # so it is bounded and repr-delimited before it can reach a rendered report.
                "normalization_ineligible":
                    "helper internal error: pair_processing_error "
                    f"(detail: {f'{type(e).__name__}: {e}'[:200]!r})",
                "pair_index": idx,
            })
            needs_retry.append({"id": (pair.get("item") or {}).get("id")
                                if isinstance(pair.get("item"), dict) else None,
                                "kind": "helper_internal",
                                "defect": "pair_processing_error",
                                "pair_index": idx})
            continue
        severity_defects[len(results)] = result.pop("_severity_defect", None)
        read_failed[len(results)] = result.pop("_read_failed", (False, None))
        findings[len(results)] = result.pop("_findings", (False, None))
        results.append(result)
        if retry is not None:
            needs_retry.append(retry)

    return {
        "results": results,
        "needs_retry": needs_retry,
        "severity_defects": severity_defects,
        "read_failed": read_failed,
        "findings": findings,
        "counts": {"normalized_count": sum(1 for r in results if r.get("normalized"))},
    }


def _checklist_main(argv):
    try:
        import checklist_finalize
    except ImportError as e:
        # stdout, not only stderr: byte-empty stdout reads as a matcher denial.
        print(json.dumps({"ok": False, "error": "checklist_module_missing",
                          "detail": str(e)[:200]}, indent=2))
        return 0
    return checklist_finalize.main(argv)


# ── citation splitting (checklist_finalize's carry imports _cited_paths) ──────

def _strip_line_anchor(fc):
    """Return ``file_checked`` with its trailing line-anchor list removed.

    The verifier contract emits ``file_checked`` as ``path:anchors`` (agents/checklist-verifier.md)
    while the view inventory records bare paths, so the membership test compares bare paths. The
    anchor list after the last ``:`` is one or more comma-separated ``N`` / ``N-M`` items, spaces
    around items and a trailing ``-`` tolerated (``:188``, ``:259-280``, ``:18,158,318-321``,
    ``:497-512, 682``); only that list is stripped, never a path segment, so a tail that is not
    an anchor list (``:abc``, ``:§4``) is returned unchanged. A non-string is returned unchanged."""
    if not isinstance(fc, str):
        return fc
    idx = fc.rfind(":")
    if idx <= 0:
        return fc
    items = [item.strip() for item in fc[idx + 1:].split(",")]
    items = [item for item in items if item]
    if not items:
        return fc
    for item in items:
        parts = item.split("-")
        if not (1 <= len(parts) <= 2) or not parts[0].isdigit() or (
                len(parts) == 2 and parts[1] and not parts[1].isdigit()):
            return fc
    return fc[:idx].rstrip()


def _bare_key(text, prefixes):
    """One citation reduced to its inventory key: ``\\`` normalized to ``/``, the trailing
    anchor list stripped, a leading bound-view directory removed (an absolute citation is also
    tried symlink-resolved, as the cwd may be). May be ``""``."""
    key = _strip_line_anchor(text.replace("\\", "/").strip())
    forms = [key]
    if prefixes and os.path.isabs(key):
        resolved = _resolved(key)
        if resolved is not None:  # None (a NUL byte): the literal form alone, which misses
            forms.append(resolved)
    for form in forms:
        stripped = _strip_view_prefix(form, prefixes)
        if stripped is not None:
            return _ViewStripped(stripped)
    return key


def _resolved(path):
    """``path`` symlink-resolved with ``/`` separators, or ``None`` when this host cannot resolve
    it (a NUL byte, an unrepresentable name)."""
    try:
        return posixpath.normpath(os.path.realpath(path).replace("\\", "/"))
    except (OSError, ValueError):
        return None


def _strip_view_prefix(form, prefixes):
    """``form`` with its leading bound-view directory removed, or ``None`` when none leads it."""
    for prefix in prefixes:
        if form.startswith(prefix + "/"):
            return form[len(prefix) + 1:]
    return None


def _citation_parts(fc):
    """The citations one ``file_checked`` joins with ``;`` / `` and `` / ``,``, unstripped."""
    return fc.replace(" and ", ";").replace(",", ";").split(";")


class _ViewStripped(str):
    """A key a bound view's directory prefix was stripped from: it may name a file, never a
    directory (issue #1123 accepts only the bare repository form of a directory)."""


def _in_view(key, inventory):
    """Whether one cited key is in the view: an inventory path, or (issue #1123) a tracked
    directory as the inventory's ``has_dir`` answers it. Only a bare, segment-clean relative key
    is tried as a directory — never ``""``, ``.``, ``/``, a trailing ``/``, an absolute or ``..``
    spelling, or a view-prefixed key. ``has_dir`` is asked, never iterated, so carry's
    membership-only object works; an inventory without it (a plain set) holds no directory."""
    if key in inventory:
        return True
    if (not isinstance(key, str) or isinstance(key, _ViewStripped) or not key
            or key.startswith("/") or os.path.isabs(key)
            or any(seg in ("", ".", "..") for seg in key.split("/"))):
        return False
    has_dir = getattr(inventory, "has_dir", None)
    return callable(has_dir) and has_dir(key) is True


def _cited_paths(fc, prefixes, inventory):
    """The inventory keys a ``file_checked`` cites; carry reuses a PASS only when it tracks ALL of them.

    Verifiers were observed citing a comma-separated anchor list, joining two citations with
    ``;``, `` and `` or ``,`` (issues #901, #932), and citing the path they actually Read under
    the view directory. The whole value is reduced first (``_bare_key``) and, when that key is
    in the inventory, it is the one citation — so a real path containing `` and `` or ``,`` is
    never split when cited alone. Otherwise the value is split on ``;`` / `` and `` / ``,`` and
    each part reduced; a part that is only an anchor item (``682``, ``12-40``, ``12-``) belongs to
    the path before it and is dropped. A part missing from the inventory that holds whitespace
    (``a.py:12 b.py:40``, issue #1102) becomes its whitespace pieces, reduced the same way, only
    when every piece is in the inventory; otherwise it stays whole and misses. An anchor-item
    piece is dropped only where it continues an anchor list (leading the part, or after an
    anchored piece), so ``a.py 12`` keeps ``12`` as a piece and misses.
    Membership is ``_in_view`` (a path, or a tracked directory): carry passes a membership-only object. A part that
    reduces to nothing (the view directory alone) keeps its original text, and a value that yields no part at all (anchor items only, a
    separator alone) is returned as itself — both are non-members. Only a non-string or the empty string ``""`` returns ``[]``
    (unchanged: those were never path-checked)."""
    if not isinstance(fc, str) or fc == "":
        return []
    whole = _bare_key(fc, prefixes)
    if _in_view(whole, inventory):
        return [whole]
    keys = []
    for part in _citation_parts(fc):
        raw = part.strip()
        if raw and _strip_line_anchor("x:" + raw) != "x":
            key = _bare_key(raw, prefixes) or raw
            if len(raw.split()) > 1 and not _in_view(key, inventory):
                pieces, anchored = [], True  # a leading anchor item drops, as an anchor-only part does
                for p in raw.split():
                    if anchored and _strip_line_anchor("x:" + p) == "x":
                        continue
                    pieces.append(_bare_key(p, prefixes))
                    anchored = _strip_line_anchor(p) != p
                if pieces and all(p and _in_view(p, inventory) for p in pieces):
                    keys.extend(pieces)
                    continue
            keys.append(key)
    return keys or [fc]


# ── shared helpers ────────────────────────────────────────────────────────────

def _shape(present, val):
    if not present:
        return "missing"
    if isinstance(val, bool):
        return "boolean"
    if isinstance(val, dict):
        return f"object({len(val)})"
    if isinstance(val, list):
        return f"array({len(val)})"
    if val is None:
        return "null"
    return "string" if isinstance(val, str) else "number"


def _path_safe(token):
    """A checklist id usable as a file-name part: non-empty, no separator, no NUL, no
    parent hop — ids are transcribed from PR-author-influenced text."""
    return (isinstance(token, str) and bool(token) and ".." not in token
            and not any(c in token for c in "/\\\x00"))


def _load(path, label, want):
    """Return ``(value, None)`` or ``(None, bad_input_report)``."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return None, {"bad_input": True, "error": f"{label}_unreadable", "detail": str(e)}
    if not raw.strip():
        return None, {"bad_input": True, "error": f"{label}_empty",
                      "detail": f"the {label} file was empty"}
    try:
        val = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        return None, {"bad_input": True, "error": f"{label}_unparseable",
                      "detail": f"not valid JSON: {e}"}
    if not isinstance(val, want):
        return None, {"bad_input": True, "error": f"{label}_wrong_shape",
                      "detail": f"expected a JSON {'object' if want is dict else 'array'}"
                                f" root, got {_shape(True, val)}"}
    return val, None


def _stub(item_id, evidence, **extra):
    return {"id": item_id, "verdict": "INCONCLUSIVE", "evidence": evidence,
            "file_checked": None, "severity": "critical", **extra}


def _force_issue_acceptance(entry, item):
    if item.get("category") == "issue_acceptance":
        entry["severity"] = "critical"


def _drop_tmp(tmp):
    """Remove a temp file the write left behind; ``"; <name> not removed"`` when that fails."""
    if os.path.lexists(tmp):
        try:
            os.unlink(tmp)
        except OSError:
            return f"; {os.path.basename(tmp)} not removed"
    return ""


_ITER_RE = re.compile(r"\Aiter-([1-9][0-9]{0,5})\Z")


def _confined_verdicts_dir(verdicts_dir):
    """``(iteration, None)`` or ``(None, reason)``: the directory must resolve beneath a
    ``.prflow/tmp/`` pair and be named ``iter-<N>`` — checklist_finalize's ``_confined``
    rule, so the wipe can never reach outside the run's scratch."""
    if not isinstance(verdicts_dir, str) or not verdicts_dir:
        return None, "verdicts_dir_empty"
    if os.path.islink(verdicts_dir.rstrip("/\\") or verdicts_dir):
        return None, "verdicts_dir_is_a_symlink"
    parts = os.path.realpath(verdicts_dir).replace("\\", "/").split("/")
    match = _ITER_RE.match(parts[-1] if parts else "")
    if not match:
        return None, "verdicts_dir_name_not_iter_n"
    if not any(a == ".prflow" and b == "tmp" for a, b in itertools.pairwise(parts[:-1])):
        return None, "verdicts_dir_outside_prflow_tmp"
    return int(match.group(1)), None


def _under_prflow_tmp(path):
    """True when ``path`` resolves beneath a ``.prflow/tmp/`` pair."""
    parts = os.path.realpath(path).replace("\\", "/").split("/")
    return any(a == ".prflow" and b == "tmp" for a, b in itertools.pairwise(parts[:-1]))


def _write_item_files(items_dir, agent_items):
    """Write each ``(id, item)`` to ``<items_dir>/<id>.json`` after unlinking every regular
    file and symlink directly inside ``<items_dir>`` (a subdirectory stays). Returns None, or
    the reason prepare refuses (``item_files_unwritten``). After a failed write it tries to
    unlink the files this call wrote, and the reason names any it could not remove."""
    if os.path.islink(items_dir):
        return "items_dir_is_a_symlink -- no item files written"
    if not _under_prflow_tmp(items_dir):
        return "items_dir_outside_prflow_tmp -- no item files written"
    written = []
    try:
        os.makedirs(items_dir, exist_ok=True)
        with os.scandir(items_dir) as entries:
            for entry in entries:
                if entry.is_symlink() or entry.is_file(follow_symlinks=False):
                    os.unlink(entry.path)
        for item_id, item in agent_items:
            # Serialize first: an item json.dumps cannot render fails before its file exists.
            body = json.dumps(item, indent=2, ensure_ascii=False) + "\n"
            path = os.path.join(items_dir, item_id + ".json")
            # "x": a duplicate id (or, on a case-insensitive filesystem, a case-variant twin)
            # fails instead of overwriting.
            with open(path, "x", encoding="utf-8", newline="\n") as fh:
                written.append(path)
                fh.write(body)
    except (OSError, ValueError, TypeError, RecursionError) as e:  # ValueError covers UnicodeError
        kept = []
        for path in written:
            try:
                os.unlink(path)
            except OSError:
                kept.append(os.path.basename(path))
        tail = f"item files not removed: {', '.join(kept)}" if kept else "item files removed"
        return f"items_dir_write_failed ({type(e).__name__}: {e}) -- {tail}"
    return None


def _fresh_agent(item):
    """Every checklist object but a carried PASS is verified by an agent (lite mode is retired)."""
    return (isinstance(item, dict)
            and not (item.get("reused_from_iter_prev") is True and item.get("verdict") == "PASS"))


class _Refusal(Exception):
    """A prepare/collect outcome other than ok: ``usage`` (exit 2) or ``error`` (exit 1)."""

    def __init__(self, status, error, detail):
        super().__init__(detail)
        self.status, self.error, self.detail = status, error, detail


_CHECKLIST_NAME_RE = re.compile(r"\Achecklist-iter-([1-9][0-9]{0,5})\.json\Z")
_ATTEMPT_RE = re.compile(r"\A(?P<id>.+)\.a(?P<k>[1-9][0-9]{0,5})\.json\Z")
_RULES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "skills", "review", "verifier-rules")
_RULES = (("issue_acceptance", "issue-acceptance.md"), ("prior_ref", "prior-ref.md"),
          ("rejection", "rejected-finding.md"))
_STRICTER = "Stricter than criterion "
_REJECTED = 'Finding rejected "'
PR_ABSENT = object()
_ITEM_STATE_KEYS = ("grading_rules", "disclosed", "criteria_file", "retried", "dispute",
                    "delivery", "delivery_answer", "delivery_file_only", "rejections")


def _artifact_fields(value, verdict_file):
    out = dict(value)
    for key in ("head_view", "base_view", "diff", "criteria_file"):
        if isinstance(out.get(key), str) and out[key]:
            out[key] = _artifact_path(out[key])
    out["verdict_file"] = _artifact_path(verdict_file)
    return out


def _layout(checklist_file):
    """The run's fixed layout around ``<run-dir>/checklist-iter-<N>.json`` (module docstring)."""
    if not isinstance(checklist_file, str) or not checklist_file:
        raise _Refusal("usage", "checklist_path", "--checklist needs a path")
    path = checklist_file.replace("\\", "/")
    run_dir, name = posixpath.split(path)
    match = _CHECKLIST_NAME_RE.match(name)
    if not match:
        raise _Refusal("usage", "checklist_path", f"{name!r} is not named checklist-iter-<N>.json")
    if not _under_prflow_tmp(path):
        raise _Refusal("usage", "checklist_path", "the checklist is not beneath a .prflow/tmp/ pair")
    n, run_dir = int(match.group(1)), run_dir or "."
    join = posixpath.join
    return {"n": n, "checklist": path,
            "verdicts": join(run_dir, "verdicts", f"iter-{n}"),
            "items": path[:-len(".json")] + ".items",
            "out": join(run_dir, f"verification-iter-{n}.json"),
            "inputs": join(run_dir, f"normalize-inputs-iter-{n}.json"),
            "setup": join(run_dir, "engine-setup.json"),
            "criteria": join(run_dir, "criteria.json")}


def _attempt_path(verdicts_dir, item_id, k):
    return posixpath.join(verdicts_dir, f"{item_id}.a{k}.json")


def _attempt_of(path):
    match = _ATTEMPT_RE.match(posixpath.basename(path)) if isinstance(path, str) else None
    return int(match.group("k")) if match else None


def _redirect(verdicts_dir, item_id, value):
    """``(k, item file)``: ``value`` without its one-dispatch ``dispute`` and delivery-state keys, its
    ``verdict_file`` the first attempt with no file after both its ``attempt`` and its current
    ``verdict_file``'s, so no dispatch shares a file an earlier one may still write. The rule for
    every item-file rewrite: collect's re-dispatch and reverify-add's."""
    k = max((a for a in (value.get("attempt"), _attempt_of(value.get("verdict_file")))
             if isinstance(a, int) and not isinstance(a, bool) and a >= 1), default=1) + 1
    while os.path.lexists(_attempt_path(verdicts_dir, item_id, k)):
        k += 1
    out = {key: v for key, v in _artifact_fields(value, _attempt_path(verdicts_dir, item_id, k)).items()
           if key not in ("dispute", "delivery", "delivery_answer", "delivery_file_only")}
    return k, out


def _write_json_atomic(path, value, indent=2):
    """Write ``value`` as JSON through a sibling temp file. A failure raises OSError naming its
    cause and any temp file left behind."""
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(value, indent=indent, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except (OSError, ValueError, TypeError, RecursionError) as e:
        raise OSError(f"{type(e).__name__}: {e}{_drop_tmp(tmp)}") from e


# ── prepare ───────────────────────────────────────────────────────────────────

def _rule_paragraphs():
    """``{kind: [paragraph, ...]}`` from the shipped verifier-rules files."""
    rules = {}
    for kind, name in _RULES:
        path = os.path.join(_RULES_DIR, name)
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError) as e:
            raise _Refusal("error", "rules_unreadable", f"{path}: {type(e).__name__}") from e
        paragraphs = [p.strip() for p in re.split(r"\n[ \t]*\n", text.replace("\r", "")) if p.strip()]
        if not paragraphs:
            raise _Refusal("error", "rules_unreadable", f"{path} holds no text")
        rules[kind] = paragraphs
    return rules


def _setup_fields(lay):
    """``(item keys, pr)`` from the engine-setup record; ``pr`` is the record's ``pr`` value, or
    ``PR_ABSENT`` when the key is missing."""
    record, bad = _load(lay["setup"], "setup_record", dict)
    if bad:
        raise _Refusal("error", bad["error"], bad["detail"])
    views = record.get("views") if isinstance(record.get("views"), dict) else {}
    keys = {}
    for slot in ("head", "base"):
        view = views.get(slot) if isinstance(views.get(slot), dict) else {}
        where, rev = view.get("dir"), view.get("revision")
        if not (isinstance(where, str) and where and isinstance(rev, str) and rev):
            raise _Refusal("error", "setup_record_unusable", f"views.{slot} lacks a dir and a revision")
        keys[f"{slot}_view"], keys[f"{slot}_sha"] = where, rev
    diff = record.get("diff_path")
    if not (isinstance(diff, str) and diff):
        raise _Refusal("error", "setup_record_unusable", "diff_path is not a non-empty string")
    keys["diff"] = diff
    return keys, record.get("pr", PR_ABSENT)


def _criteria_entries(lay):
    """``([(N, text)], None)`` from criteria.json, or ``(None, why)`` unless it is a list of
    ``{criterion: <integer>, text: <string>}`` objects."""
    value, bad = _load(lay["criteria"], "criteria", list)
    if bad:
        return None, f"{bad['error']}: {bad['detail']}"
    out = []
    for idx, entry in enumerate(value):
        n = entry.get("criterion") if isinstance(entry, dict) else None
        text = entry.get("text") if isinstance(entry, dict) else None
        if not (isinstance(n, int) and not isinstance(n, bool) and isinstance(text, str)):
            return None, f"criteria_wrong_shape: entry {idx} is not a {{criterion: <integer>, text: <string>}} object"
        out.append((n, text))
    return out, None


def _pr_body_lines(body, warnings, root=None):
    """``(state, lines)``: the PR body's lines, CRs removed (module docstring); a relative path
    resolves against ``root`` when given, else the working directory."""
    if body is None or body == "empty":
        return "none", []
    if not (isinstance(body, str) and body) or body == "unavailable":
        return "unread", []
    try:
        with open(os.path.join(root, body) if root else body, encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError, ValueError) as e:
        warnings.append(f"PR body {body} unreadable ({type(e).__name__}) -- no disclosure or rejection line read")
        return "unread", []
    return "read", [line.replace("\r", "") for line in text.split("\n")]


def is_rejection(line):
    """Whether ``line`` is a candidate rejection line (module docstring, *Rejections*)."""
    return line.startswith(_REJECTED) and '": ' in line[len(_REJECTED):]


def counted_rejections(pr, state, lines):
    """``(lines, None)``: the body's distinct rejection lines, in body order, when the setup record
    trusts the PR author; else ``([], case)``, the first case that counts none (module docstring).
    ``pr`` is the record's ``pr`` value or ``PR_ABSENT``; ``state, lines`` are ``_pr_body_lines``'s
    pair."""
    if pr is None:
        return [], "no pull request"
    if pr is PR_ABSENT:
        return [], "PR record absent"
    if not isinstance(pr, dict):
        return [], f"PR record is a {type(pr).__name__}, not an object"
    if state == "unread":
        return [], "PR body unread"
    found = list(dict.fromkeys(line for line in lines if is_rejection(line)))
    if not found:
        return [], "no Finding rejected line"
    if "author_trust" not in pr:
        return [], "author trust outcome absent"
    trust = pr["author_trust"]
    if not isinstance(trust, str):
        return [], f"author trust outcome is a {type(trust).__name__}, not a string"
    if trust.startswith("lookup-failed: "):
        return [], f"trust lookup failed ({trust[len('lookup-failed: '):]})"
    if trust == "untrusted":
        return [], "author untrusted"
    if trust == "not-looked-up":
        return [], "author trust not looked up beside a Finding rejected line"
    if trust != "trusted":
        return [], f"author trust outcome {trust[:80]!r} is unknown"
    return found, None


def _disclosures(lines, criteria, fresh):
    """``(records, {item id: [disclosed entry, ...]})`` for the disclosure lines; ``criteria`` is
    ``_criteria_entries``'s pair."""
    criteria, unusable = criteria
    prior_ids = [i for i, it in fresh if isinstance(it.get("prior_ref"), str) and it["prior_ref"]]
    by_signature = {}
    for item_id, item in fresh:
        if isinstance(item.get("claim_signature"), str):
            by_signature.setdefault(item["claim_signature"], []).append(item_id)
    records, reach = [], {}
    for line in lines:
        if not line.startswith(_STRICTER):
            continue
        record = {"line": line, "kind": "stricter", "criterion": None}
        targets, why = [], None
        n = None if criteria is None else next(
            (n for n, text in criteria if line.startswith(f'{_STRICTER}"{text}": ')), None)
        owners = by_signature.get(f"issue-acceptance-{n}", []) if n is not None else []
        if criteria is None:
            why = f"criteria unavailable ({unusable})"
        elif n is None:
            why = "quotes no current criterion"
        elif not owners:
            record["criterion"], why = n, f"no issue-acceptance-{n} item"
        else:
            record["criterion"] = n
            targets = [(i, n) for i in owners + prior_ids]
        record["reached"] = sorted({i for i, _ in targets})
        record["ignored"] = why
        records.append(record)
        for item_id, n in targets:
            entry = {"line": line, "criterion": n}
            if entry not in reach.setdefault(item_id, []):
                reach[item_id].append(entry)
    return records, reach


def _rechecks(item):
    """Whether ``item`` re-checks a prior finding (it gets the prior-ref rules)."""
    return "prior_ref" in item or "prior_evidence" in item


def _recheck_criteria(lay, criteria, fresh, warnings):
    """Whether re-check items get ``criteria_file``: ``criteria`` is usable (module docstring)."""
    entries, why = criteria
    if entries:
        return True
    if any(_rechecks(it) for _, it in fresh) and os.path.lexists(lay["criteria"]):
        warnings.append(f"criteria {lay['criteria']} unusable ({why or 'criteria_empty: an empty list'})"
                        " -- re-check items get no criteria_file")
    return False


def _item_file(item, lay, base_keys, rules, disclosed, recheck_criteria, rejections):
    out = {k: v for k, v in item.items() if k not in _ITEM_STATE_KEYS}
    out.update(base_keys, attempt=1)
    acceptance = item.get("category") == "issue_acceptance"
    rechecks = _rechecks(item)
    rejections = [] if acceptance else rejections
    paragraphs = []
    if acceptance or disclosed:
        paragraphs += rules["issue_acceptance"]
    if rechecks:
        paragraphs += rules["prior_ref"]
    if rejections:
        paragraphs += rules["rejection"]
    if paragraphs:
        out["grading_rules"] = paragraphs
    if disclosed:
        out["disclosed"] = disclosed
    if rejections:
        out["rejections"] = rejections
    if acceptance or disclosed or (rechecks and recheck_criteria):
        out["criteria_file"] = lay["criteria"]
    return _artifact_fields(out, _attempt_path(lay["verdicts"], item["id"], 1))


def prepare(checklist_file):
    """Phase 2.0's dispatch plan (module docstring, *Prepare*)."""
    lay = _layout(checklist_file)
    iteration, err = _confined_verdicts_dir(lay["verdicts"])
    if err:
        raise _Refusal("usage", "verdicts_dir", err)
    checklist, bad = _load(lay["checklist"], "checklist", list)
    if bad:
        raise _Refusal("error", bad["error"], bad["detail"])
    base_keys, pr = _setup_fields(lay)
    rules = _rule_paragraphs()
    warnings = []
    os.makedirs(lay["verdicts"], exist_ok=True)
    wiped = 0
    with os.scandir(lay["verdicts"]) as entries:
        for entry in entries:
            # A symlink is unlinked as a link (never followed); a directory stays.
            if entry.is_symlink() or entry.is_file(follow_symlinks=False):
                os.unlink(entry.path)
                wiped += 1
    # An earlier entry's replies at this N must never answer this entry's ids (entry freshness).
    if os.path.lexists(lay["inputs"]):
        try:
            os.unlink(lay["inputs"])
        except OSError as e:
            raise _Refusal("error", "inputs_file_unremoved", f"{lay['inputs']}: {type(e).__name__}") from e
    reused, fresh = [], []
    for idx, item in enumerate(checklist):
        if not isinstance(item, dict):
            warnings.append(f"checklist[{idx}]: not an object -- skipped")
        elif not _path_safe(item.get("id")):
            warnings.append(f"checklist[{idx}]: id {item.get('id')!r} is not a usable file-name part -- skipped")
        elif not _fresh_agent(item):
            reused.append(item["id"])
        else:
            fresh.append((item["id"], item))
    pr_state, lines = _pr_body_lines(pr.get("body", "unavailable") if isinstance(pr, dict) else None, warnings)
    rejections, uncounted = counted_rejections(pr, pr_state, lines)
    criteria = _criteria_entries(lay)
    records, reach = _disclosures(lines, criteria, fresh)
    recheck_criteria = _recheck_criteria(lay, criteria, fresh, warnings)
    files = [(i, _item_file(it, lay, base_keys, rules, reach.get(i, []), recheck_criteria, rejections))
             for i, it in fresh]
    failure = _write_item_files(lay["items"], files)
    if failure:
        raise _Refusal("error", "item_files_unwritten", failure)
    return {"status": "ok", "iteration": iteration, "items_dir": _artifact_path(lay["items"]),
            "verdicts_dir": lay["verdicts"], "agent": [i for i, _ in fresh], "reused": reused,
            "counts": {"agent": len(fresh), "reused": len(reused)},
            "disclosures": records, "pr_body": pr_state,
            "rejections": {"lines": rejections, "uncounted": uncounted}, "wiped": wiped, "warnings": warnings}


# ── collect ───────────────────────────────────────────────────────────────────

def _item_state(lay, item_id, warnings):
    """An item file's attempt state: ``path`` (None for an id no file can carry), ``attempt``,
    ``retried``, ``delivery`` (a spent delivery:
    only JSON ``true``) and the file's ``value``. An unusable file reads as attempt 1 with a
    warning, but cannot establish an original-verifier association for recovery."""
    state = {"path": None, "attempt": 1, "retried": False, "delivery": False,
             "value": None, "usable": False}
    if not _path_safe(item_id):
        return state
    state["path"] = _artifact_path(posixpath.join(lay["items"], f"{item_id}.json"))
    value, bad = _load(state["path"], "item_file", dict)
    if bad:
        warnings.append(f"{item_id}: {bad['error']} -- read as attempt 1")
        return state
    k = value.get("attempt")
    if isinstance(k, int) and not isinstance(k, bool) and k >= 1:
        state["attempt"] = k
        state["usable"] = True
    else:
        warnings.append(f"{item_id}: item file attempt is {_shape('attempt' in value, k)} -- read as attempt 1")
    retried = value.get("retried")
    state["retried"] = retried is True
    if "retried" in value and not isinstance(retried, bool):
        warnings.append(f"{item_id}: item file retried is {_shape(True, retried)} -- read as false")
    delivery = value.get("delivery")
    state["delivery"] = delivery is True
    state["value"] = value
    return state


def _answer_path(lay, item_id, state, has_reply):
    """The attempt file an item is graded from: its current attempt; with
    neither that file nor a reply holding a usable verdict, the latest usable earlier answer.
    A spent delivery stays bound to its assigned attempt."""
    current = _attempt_path(lay["verdicts"], item_id, state["attempt"])
    if os.path.lexists(current) or state["delivery"] or has_reply:
        return current
    for i in range(state["attempt"] - 1, 0, -1):
        earlier = _attempt_path(lay["verdicts"], item_id, i)
        text, source = _read_verdict_bytes({"verdict_path": earlier})
        if source == "none_file_unreadable":
            return earlier  # An existing unreadable file retains its channel-error route.
        obj, defect = extract_verdict_object(text)
        if defect is None and _verdict_fields_defect(obj, item_id) is None:
            return earlier
    return current


def _next_attempt(lay, item_id, state):
    """Point the item file at its next attempt for a verdict defect's one re-dispatch: ``(that
    attempt's verdict file, None)``, or ``(None, why)`` when the item file is not rewritten."""
    if state["path"] is None:
        return None, "the id is not a usable file-name part"
    if state["value"] is None:
        return None, "the item file is unusable"
    k, value = _redirect(lay["verdicts"], item_id, state["value"])
    value["attempt"] = k
    value["retried"] = True
    try:
        _write_json_atomic(state["path"], value)
    except OSError as e:
        return None, str(e)
    return value["verdict_file"], None


def _mark_delivery(state, pair, file_only=False):
    """Mark delivery spent, preserving a usable reply or requiring the assigned file, without
    changing the attempt. Returns ``(its verdict file, None)``, or
    ``(None, why)`` when the item file is not rewritten."""
    if state is None or state["path"] is None:
        return None, "the id is not a usable file-name part"
    if state["value"] is None:
        return None, "the item file is unusable"
    value = dict(_artifact_fields(state["value"], pair["verdict_path"]), delivery=True)
    if file_only:
        value.pop("delivery_answer", None)
        value["delivery_file_only"] = True
    else:
        value.pop("delivery_file_only", None)
        value["delivery_answer"] = extract_verdict_object(pair.get("response_text"))[0]
    try:
        _write_json_atomic(state["path"], value)
    except OSError as e:
        return None, str(e)
    return _artifact_path(pair["verdict_path"]), None


# What a delivered file must repeat from the recorded answer: the fields grading reads.
# Evidence wording may drift.
_DELIVERY_OPERANDS = ("id", "verdict", "severity", "read_failed")


def _operands(obj):
    """The grading operands present in ``obj``, JSON-encoded so ``true`` never equals ``1``."""
    return {k: json.dumps(obj[k], sort_keys=True) for k in _DELIVERY_OPERANDS if k in obj}


def _delivery_mismatch(pair, result, state):
    """Why recovery state or the delivered grading operands are unusable, else None."""
    if state.get("usable") is False:
        if state["path"] is None:
            return "the id is not a usable file-name part"
        return "item file has no usable attempt association"
    value = state["value"] or {}
    if "delivery" in value and not isinstance(value["delivery"], bool):
        return f"item file delivery is {_shape(True, value['delivery'])} -- recovery state is unusable"
    present = "delivery_answer" in value
    if "delivery_file_only" in value:
        if value["delivery_file_only"] is not True or not state["delivery"] or present:
            return "item file delivery_file_only requires true, spent delivery and no delivery_answer"
        return None
    if not state["delivery"]:
        return "item file delivery_answer without spent delivery" if present else None
    answer = value.get("delivery_answer")
    if not isinstance(answer, dict):
        return f"item file delivery_answer is {_shape(present, answer)}"
    defect = _verdict_fields_defect(answer, pair.get("item", {}).get("id"))
    if defect is not None:
        return f"item file delivery_answer has {defect}"
    if result.get("source") != "file":
        return None
    try:
        with open(pair["verdict_path"], encoding="utf-8") as fh:
            delivered = extract_verdict_object(fh.read())[0]
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return f"delivered verdict file unreadable ({type(e).__name__})"
    # Only the operands the recorded answer carries: a delivered file may add one it omitted.
    got_ops = _operands(delivered) if isinstance(delivered, dict) else None
    if got_ops is None or any(got_ops.get(k) != v for k, v in _operands(answer).items()):
        got = delivered.get("verdict") if isinstance(delivered, dict) else None
        return (f"delivered verdict file's grading operands differ from the verifier's reply "
                f"(verdict {got!r}, reply {answer.get('verdict')!r})")
    return None


def _read_inputs(lay, warnings):
    """``(response_text, reverify, agent_id)`` maps from the optional inputs file."""
    if not os.path.lexists(lay["inputs"]):
        return {}, {}, {}
    inputs, bad = _load(lay["inputs"], "inputs_file", dict)
    if bad:
        warnings.append(f"inputs file: {bad['error']} ({bad['detail']}) -- ignored")
        return {}, {}, {}
    maps = {}
    for key in ("response_text", "reverify", "agent_id"):
        value = inputs.get(key, {})
        if not isinstance(value, dict):
            warnings.append(f"{key}: expected object, got {_shape(True, value)} -- ignored")
            value = {}
        maps[key] = value
    for key in inputs:
        if key not in maps:
            warnings.append(f"{key}: not a collect input -- ignored")
    agent_ids = {}
    for item_id, aid in maps["agent_id"].items():
        if isinstance(aid, str) and aid:
            agent_ids[item_id] = aid
        else:
            warnings.append(f"agent_id[{item_id!r}]: expected non-empty string, got {_shape(True, aid)} -- ignored")
    return maps["response_text"], maps["reverify"], agent_ids


def _reverify(lay, reverify, checklist, verification, answered, warnings):
    """Grade each ``reverify`` entry's attempt and let a PASS or FAIL replace the stored FAIL.
    Returns the replaced ids."""
    replaced, where = [], {}
    for idx, item in enumerate(checklist):
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            where.setdefault(item["id"], []).append(idx)
    for rid, spec in reverify.items():
        cr = spec.get("counter_reading") if isinstance(spec, dict) else None
        k = spec.get("attempt") if isinstance(spec, dict) else None
        head = f"re-verification {rid}: " + (f"counter-reading {cr!r}; " if isinstance(cr, str) and cr else "")
        slots = where.get(rid, [])
        stored = verification[slots[0]] if len(slots) == 1 else None
        if not isinstance(spec, dict):
            why = "entry is not an object"
        elif not (isinstance(cr, str) and cr):
            why = "counter_reading is not a non-empty string"
        elif not (_path_safe(rid) and isinstance(k, int) and not isinstance(k, bool) and k >= 1):
            why = "id is not a usable file-name part, or attempt is not a positive integer"
        elif k in answered.get(rid, ()):
            why = "attempt names the item's stored answer, not a re-verification"
        elif not slots:
            why = "no checklist item has this id"
        elif stored is None:
            why = "more than one checklist item has this id"
        elif not _fresh_agent(checklist[slots[0]]):
            why = "item is a carried PASS"
        elif stored["verdict"] != "FAIL":
            why = f"stored verdict is {stored['verdict']}, not FAIL"
        else:
            why = None
        if why is not None:
            warnings.append(head + "ignored: " + why)
            continue
        item = checklist[slots[0]]
        ran = run_pairs([{"item": item, "verdict_path": _attempt_path(lay["verdicts"], rid, k)}])
        graded, sev_defect = ran["results"][0], ran["severity_defects"].get(0)
        _force_issue_acceptance(graded, item)
        before = f"FAIL ({stored['severity']}) -> "
        if graded["verdict"] is None:
            kept = f"{graded['defect_class']} defect ({graded['defect']})"
            if graded["defect_class"] == "verdict":
                kept = {"none": "re-verification file absent",
                        "none_file_unreadable": "re-verification file unreadable"}.get(graded["source"], kept)
        elif graded["verdict"] == "INCONCLUSIVE":
            kept = "graded INCONCLUSIVE"
        else:
            graded["verification_shortfall"] = None
            if "findings" in stored:  # the dispute grades the claim; the first answer's findings stand
                graded["findings"] = stored["findings"]
            verification[slots[0]] = graded
            replaced.append(rid)
            raw = graded.get("raw_verdict")
            tail = f"; raw verdict {raw}" if raw not in (None, graded["verdict"]) else ""
            tail += f"; severity {sev_defect}" if sev_defect else ""
            warnings.append(head + before + f"{graded['verdict']} ({graded['severity']}){tail}")
            continue
        warnings.append(head + before + f"FAIL ({stored['severity']}), kept: {kept}")
    return replaced


def _read_failed_note(item_id, result, present, value, warnings):
    """The shortfall a verifier's ``read_failed`` operand stores (module docstring, *Collect*)."""
    if not present or value is None or value is False:
        return None
    raw = result.get("raw_verdict")
    if raw != "INCONCLUSIVE":
        warnings.append(f"{item_id!r}: read_failed on a {raw} verdict -- ignored")
        return None
    if value is not True:
        warnings.append(f"{item_id!r}: read_failed is {_shape(True, value)}, not a JSON boolean "
                        "-- stored verifier-read-failed")
    return "verifier-read-failed"


def _findings(item_id, result, present, value, warnings):
    """A usable answer's stored ``findings`` records (module docstring, *Findings*)."""
    if not present:
        return []
    if not isinstance(value, list):
        warnings.append(f"{item_id!r}: findings is {_shape(True, value)}, not an array -- dropped")
        return []
    kept = []
    for idx, record in enumerate(value):
        if not (isinstance(record, dict) and isinstance(record.get("description"), str)
                and record["description"].strip()):
            warnings.append(f"{item_id!r}: findings[{idx}] is not an object with a description -- dropped")
            continue
        record = dict(record, item_id=item_id)
        record["severity"], defect = _severity(record)
        if defect is not None:
            warnings.append(f"{item_id!r}: findings[{idx}] severity {defect} -- stored critical")
        if result.get("defect") == "trusted_file_unreadable":  # an untrusted grade, like the verdict's
            record["severity"] = "critical"
        kept.append(record)
    return kept


def collect(checklist_file):
    """Phase 2.2's collector (module docstring, *Collect*)."""
    lay = _layout(checklist_file)
    checklist, bad = _load(lay["checklist"], "checklist", list)
    if bad:
        raise _Refusal("error", bad["error"], bad["detail"])
    warnings = []
    replies, reverify, agent_ids = _read_inputs(lay, warnings)
    verification, pairs, slots, states = [], [], [], []
    reused_count = 0
    for idx, item in enumerate(checklist):
        if not isinstance(item, dict):
            warnings.append(f"checklist[{idx}]: not an object")
            verification.append(_stub(None, f"checklist element {idx} is not an object",
                                      verification_shortfall="checklist-element"))
            continue
        item_id = item.get("id")
        if not _fresh_agent(item):
            reused_count += 1
            entry = {k: item[k] for k in ("id", "verdict", "evidence", "file_checked",
                                          "raw_verdict", "normalized", "reused_from_iter")
                     if k in item}
            entry["severity"], sev_defect = _severity(item)
            if sev_defect is not None:
                warnings.append(f"{item_id!r}: severity {sev_defect} -- stored critical")
            _force_issue_acceptance(entry, item)
            entry["reused_from_iter_prev"] = True
            entry["verification_shortfall"] = None
            verification.append(entry)
            continue
        key = item_id if isinstance(item_id, str) else None
        state = _item_state(lay, key, warnings)
        pair = {"item": item}
        reply = replies.get(key) if key is not None else None
        if key in replies and not (isinstance(reply, str) and reply):
            warnings.append(f"response_text[{key!r}]: " + ("empty string" if reply == "" else
                            f"expected string, got {_shape(True, reply)} -- ignored"))
        if state["delivery"]:
            # Later replies cannot replace a saved answer or stand in for a file-only delivery.
            recorded = state["value"].get("delivery_answer")
            reply = json.dumps(recorded) if isinstance(recorded, dict) else None
            if reply is not None:
                pair["recorded_answer"] = reply
        if isinstance(reply, str):
            pair["response_text"] = reply
        if state["path"] is not None:
            obj = extract_verdict_object(reply)[0] if isinstance(reply, str) else None
            pair["verdict_path"] = _answer_path(
                lay, key, state, isinstance(obj, dict) and _verdict_fields_defect(obj, key) is None)
        pair["delivery_invalid"] = _delivery_mismatch(pair, {"source": "none"}, state)
        slots.append(len(verification))
        verification.append(None)
        pairs.append(pair)
        states.append(state)

    ran = run_pairs(pairs)
    absent_ids, reply_defects, undelivered = [], {}, {}
    for pair, result, state in zip(pairs, ran["results"], states):
        key = result.get("id")
        path, rt = pair.get("verdict_path"), pair.get("response_text")
        names_own_file = isinstance(path, str) and isinstance(rt, str) and posixpath.basename(path) in rt
        if pair.get("delivery_invalid"):
            continue
        missing = result.get("source") in ("none", "response_text")
        if state["delivery"] and result.get("source") != "file" and isinstance(key, str):
            undelivered[key] = (state, pair, result)  # a spent delivery is never re-verified, whatever the reply
        elif missing and isinstance(key, str):
            if (agent_ids.get(key) is not None or result.get("raw_verdict") is not None
                    or state["retried"]):
                undelivered[key] = (state, pair, result)
            elif names_own_file and key not in absent_ids:
                absent_ids.append(key)
                reply_defects[key] = result["defect"]
                result["defect"] = "verdict_file_absent"
    needs_retry = [r for r in ran["needs_retry"]
                   if not ((r.get("id") in absent_ids or r.get("id") in undelivered)
                           and r.get("kind") == "verdict")]
    needs_retry += [{"id": k, "kind": "verdict", "defect": "verdict_file_absent"} for k in absent_ids]
    unrequested = []
    for key, (state, pair, result) in undelivered.items():
        if state["delivery"]:
            unreadable = str(result.get("source")).endswith("_file_unreadable")
            warnings.append(f"{key}: verdict file {'unreadable' if unreadable else 'still absent'}; "
                            "its one delivery was already requested or could not be")
        elif agent_ids.get(key) is None:
            unrequested.append((key, state, pair, result.get("raw_verdict") is None))
        else:
            needs_retry.append({"id": key, "kind": "delivery", "defect": "verdict_file_absent",
                                "agent_id": agent_ids[key]})
    answered, mismatched = {}, set()
    for idx, (slot, pair, result, state) in enumerate(zip(slots, pairs, ran["results"], states)):
        item_id = result.get("id")
        severity_defect = ran["severity_defects"].get(idx)
        present, value = ran["read_failed"].get(idx, (False, None))
        shortfall = None
        mismatch = _delivery_mismatch(pair, result, state)
        if mismatch is not None:
            mismatched.add(item_id)
            warnings.append(f"{item_id}: {mismatch}")
            result["verdict"] = "INCONCLUSIVE"
            result["evidence"] = f"verifier produced no usable verdict (delivery: {mismatch})"
            result["severity"] = "critical"
            severity_defect, shortfall = "absent: no usable verifier verdict", "no-usable-verdict"
        elif item_id in reply_defects:
            result["verdict"] = "INCONCLUSIVE"
            result["evidence"] = ("verifier produced no usable verdict (verdict_file_absent; "
                                  f"reply: {reply_defects[item_id]})")
            result["severity"] = "critical"
            severity_defect, shortfall = "absent: no usable verifier verdict", "no-usable-verdict"
        elif result.get("verdict") is None:
            result["verdict"] = "INCONCLUSIVE"
            result["evidence"] = f"verifier produced no usable verdict ({result.get('defect')})"
            result["severity"] = "critical"
            severity_defect = ("absent: helper failed on this item"
                               if result.get("defect_class") == "helper_internal"
                               else "absent: no usable verifier verdict")
            shortfall = "no-usable-verdict"
        else:
            shortfall = _read_failed_note(item_id, result, present, value, warnings)
            found = _findings(item_id, result, *ran["findings"].get(idx, (False, None)), warnings)
            if found:
                result["findings"] = found
        result["verification_shortfall"] = shortfall
        if severity_defect is not None:
            warnings.append(f"{item_id!r}: severity {severity_defect} -- stored critical")
        _force_issue_acceptance(result, pair["item"])
        verification[slot] = result
        if isinstance(item_id, str):
            k = _attempt_of(pair.get("verdict_path"))
            if k:
                answered.setdefault(item_id, set()).add(k)

    replaced = _reverify(lay, reverify, checklist, verification, answered, warnings)
    tally = {"pass": 0, "fail": 0, "inconclusive": 0, "agent": len(pairs), "reused": reused_count}
    for entry in verification:
        tally[entry["verdict"].lower()] += 1
    try:
        _write_json_atomic(lay["out"], verification, indent=1)
    except OSError as e:
        raise _Refusal("error", "artifact_write_failed", f"{lay['out']}: {e}") from e

    # Point each re-dispatched item at its next attempt only once the artifact is written. An
    # undeliverable item is marked spent so the evidence gate names it a delivery failure.
    for key, state, pair, file_only in unrequested:
        if key in replaced or key in mismatched:
            continue
        warnings.append(f"{key}: verdict file absent and no original verifier agent id -- delivery not requested")
        why = _mark_delivery(state, pair, file_only)[1]
        if why is not None:
            raise _Refusal("error", "delivery_state_write_failed", f"{key}: {state['path']}: {why}")
    by_id = {}
    for pair, state, result in zip(pairs, states, ran["results"]):
        file_only = result.get("raw_verdict") is None
        by_id.setdefault(pair["item"].get("id"), (pair, state, file_only))
    out_retry = []
    for entry in needs_retry:
        key, kind = entry.get("id"), entry.get("kind")
        if key in replaced or key in mismatched:  # a mismatched delivery is a visible failure, never re-dispatched
            continue
        if kind not in ("verdict", "delivery"):
            out_retry.append(entry)
            continue
        pair, state, file_only = by_id.get(key, (None, None, False))
        if kind == "delivery":
            verdict_file, why = _mark_delivery(state, pair, file_only)
            if verdict_file is None:
                raise _Refusal("error", "delivery_state_write_failed", f"{key}: {state['path']}: {why}")
            else:
                out_retry.append(dict(entry, item=state["path"], verdict_file=verdict_file))
        elif state is None:
            warnings.append(f"{key!r}: {entry.get('defect')} -- no item file, not re-dispatched")
        elif state["retried"]:
            warnings.append(f"{key}: verdict defect persists after its re-dispatch ({entry['defect']})")
        else:
            verdict_file, why = _next_attempt(lay, key, state)
            if verdict_file is None:
                warnings.append(f"{key}: item file not rewritten ({why}) -- not re-dispatched ({entry['defect']})")
            else:
                out_retry.append(dict(entry, item=state["path"], verdict_file=verdict_file))
    return {"status": "ok", "written": lay["out"], "tally": tally, "counts": ran["counts"],
            "needs_retry": out_retry,
            "non_pass": [e for e in verification if e["verdict"] != "PASS"],
            "findings": [f for e in verification for f in e.get("findings", ())],
            "input_warnings": warnings}


# ── wait ──────────────────────────────────────────────────────────────────────

def _wait_present(verdicts_dir, ids):
    """``(present names, listing error or None)``: the expected names with a regular file
    ``<name>.json`` (Phase 1's ``batch-<k>``, Phase 2's ``<id>.a<k>``)."""
    try:
        names = {e.name for e in os.scandir(verdicts_dir) if e.is_file(follow_symlinks=False)}
    except (OSError, ValueError) as e:  # ValueError: a path os.scandir rejects before any syscall
        return set(), e
    return {i for i in ids if i + ".json" in names}, None


def wait(verdicts_dir, ids, deadline, idle=None):
    start = time.monotonic()
    present, last, idle_hit = set(), start, False
    wanted = set(ids)
    while True:
        seen, err = _wait_present(verdicts_dir, wanted)
        now = time.monotonic()
        if seen - present:
            last = now
        present |= seen
        elapsed = now - start
        idle_hit = idle is not None and bool(present) and len(present) < len(wanted) and now - last >= idle
        # Keep polling an unlistable dir only while it is absent: it may still be created.
        if (len(present) == len(wanted) or elapsed >= deadline or idle_hit
                or (err is not None and not isinstance(err, FileNotFoundError))):
            break
        time.sleep(min(1.0, deadline - elapsed))
    if err is not None:
        print(f"normalize-verdicts wait: verdicts dir not listable at last poll ({int(elapsed)}s waited): {err}",
              file=sys.stderr)
    return {"present": [i for i in ids if i in present],
            "missing": [i for i in ids if i not in present],
            "waited_s": int(elapsed), "deadline_hit": len(present) < len(wanted), "idle_hit": idle_hit}


def _wait_main(argv):
    flags, ids, bad = {}, [], False
    i = 0
    while i < len(argv):
        if argv[i] == "--expect":
            i += 1
            while i < len(argv) and not argv[i].startswith("--"):
                if argv[i] not in ids:
                    ids.append(argv[i])
                i += 1
        elif argv[i] in ("--verdicts-dir", "--deadline", "--idle") and argv[i] not in flags and i + 1 < len(argv):
            flags[argv[i]] = argv[i + 1]
            i += 2
        else:
            bad = True
            break
    numbers = [flags.get("--deadline", "")] + ([flags["--idle"]] if "--idle" in flags else [])
    if (bad or not ids or "--verdicts-dir" not in flags
            or not all(n.isascii() and n.isdigit() for n in numbers)):
        out, rc = {"ok": False, "error": "usage",
                   "detail": "wait takes --verdicts-dir <dir> --expect <name>... --deadline <seconds> "
                             "[--idle <seconds>]"}, 2
    else:
        try:
            idle = int(flags["--idle"]) if "--idle" in flags else None
            out, rc = wait(flags["--verdicts-dir"], ids, int(flags["--deadline"]), idle), 0
        except Exception as e:
            out, rc = _internal_error(e), 0
    print(json.dumps(out, indent=2))
    return rc


# ── CLI ───────────────────────────────────────────────────────────────────────

def _internal_error(e):
    sys.stderr.write("normalize-verdicts.py: internal error — this is a helper defect:\n"
                     + traceback.format_exc())
    return {"bad_input": True, "error": "helper_internal_error",
            "detail": f"{type(e).__name__}: {e}"[:200]}


def _status_line(out):
    """Print ``out`` as one LF-terminated JSON line."""
    try:
        sys.stdout.reconfigure(newline="\n")
    except (AttributeError, ValueError, OSError):
        pass
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")


def _status_main(name, fn, argv):
    """Run ``prepare``/``collect`` and print one LF-terminated JSON status line."""
    flags = dict(zip(argv[::2], argv[1::2])) if len(argv) == 4 else {}
    if set(flags) != {"--contract", "--checklist"} or flags["--contract"] != CONTRACT:
        out, rc = {"status": "usage", "error": "arguments",
                   "detail": f"{name} takes --contract {CONTRACT} "
                             "--checklist <run-dir>/checklist-iter-<N>.json"}, 2
    else:
        try:
            out, rc = fn(flags["--checklist"]), 0
        except _Refusal as r:
            out, rc = {"status": r.status, "error": r.error, "detail": r.detail}, (2 if r.status == "usage" else 1)
        except Exception as e:
            sys.stderr.write(f"normalize-verdicts.py {name}: internal error — this is a helper defect:\n"
                             + traceback.format_exc())
            out, rc = {"status": "error", "error": "helper_internal_error",
                       "detail": f"{type(e).__name__}: {e}"[:200]}, 1
    _status_line(out)
    return rc


def _report_main(op, argv):
    """Route ``render`` / ``reverify-add`` to the sibling ``verdict_report.py``; one JSON line out."""
    try:
        import verdict_report
        out, rc = verdict_report.main(op, argv, _path_safe, _fresh_agent, _redirect)
    except Exception as e:
        sys.stderr.write("normalize-verdicts.py: internal error:\n" + traceback.format_exc())
        out, rc = {"status": "error", "reason": f"{type(e).__name__}: {e}"[:200]}, 1
    _status_line(out)
    return rc


_SUBCOMMANDS = ("prepare", "collect", "wait", "checklist", "render", "reverify-add")


def main(argv=None):
    _force_utf8_streams()
    argv = list(sys.argv[1:] if argv is None else argv)
    known = bool(argv) and argv[0] in _SUBCOMMANDS + ("--help", "-h")
    if known and ("--help" in argv or "-h" in argv):
        # A help flag after a known subcommand prints usage and does nothing else. rc 0.
        print("usage: normalize-verdicts.py checklist carry|finalize|match|prior|prior-lines <work-dir> ...")
        print(f"       normalize-verdicts.py prepare --contract {CONTRACT} --checklist <run-dir>/checklist-iter-<N>.json")
        print("       normalize-verdicts.py wait --verdicts-dir <dir> --expect <name>... --deadline <seconds> [--idle <seconds>]")
        print(f"       normalize-verdicts.py collect --contract {CONTRACT} --checklist <run-dir>/checklist-iter-<N>.json")
        print(f"       normalize-verdicts.py render <run-dir> <N> --contract {CONTRACT} --threshold <t> [--capped-file <path>] [--prior <work-dir>] [--skipped intentional|failure]")
        print(f"       normalize-verdicts.py reverify-add <run-dir> <N> <item-id> --contract {CONTRACT} --threshold <t> --counter-reading-file <path>")
        return 0
    if argv and argv[0] == "checklist":
        return _checklist_main(argv[1:])
    if argv and argv[0] in ("prepare", "collect"):
        return _status_main(argv[0], prepare if argv[0] == "prepare" else collect, argv[1:])
    if argv and argv[0] == "wait":
        return _wait_main(argv[1:])
    if argv and argv[0] in ("render", "reverify-add"):
        return _report_main(argv[0], argv[1:])
    # Any other first word, a subcommand a newer helper serves included, is a usage refusal, so
    # a caller ahead of this vendored copy never reads a result. stdout as well as stderr:
    # byte-empty stdout reads as a matcher denial.
    detail = ((f"unknown subcommand {argv[0]!r}" if argv else "no subcommand")
              + "; use " + ", ".join(_SUBCOMMANDS))
    sys.stderr.write(f"normalize-verdicts.py: {detail}\n")
    _status_line({"status": "usage", "error": "subcommand", "detail": detail})
    return 2


if __name__ == "__main__":
    sys.exit(main())
