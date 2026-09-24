#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""PRFlow checklist-verdict parse + wording-only normalization helper (Phase 2.2).

The checklist-verifier is a strict measuring instrument: it grades
partially-correct claims FAIL and reports structured operands
(``property_proven``, ``inaccuracy_scope``) without ever self-normalizing. This
helper owns the parse contract and the single normalization decision, so the
review-engine prose only assembles inputs, runs the helper, and renders outputs
(the ``match-lint-adjudications.py`` / ``match-deferrals.py`` helper-owns-the-join
idiom). It is stdlib-only, reads no config, and makes no ``gh``/network/``git``
calls — unit-testable exactly like ``consolidate-changesets.py`` (issue #556).

Input — one pairs file (a JSON object) named as ``argv[1]``. The orchestrator
Writes it into the run-scoped ``.prflow/tmp/`` tree. Shape::

    {
      "pairs": [
        {
          "item": { "id": "VC-3", "verification_mode": "agent",
                    "claim_provenance": "generated_paraphrase",
                    "source_excerpt": "<verbatim authored text, source_authored items only>", ... },
          "verdict_path": ".prflow/tmp/review/<slug>/<run>/verdicts/iter-1/VC-3-<nonce>.json",
          "response_text": "...transcribed verifier response (fallback channel)...",
          "pinned_verdict": "FAIL"   # optional: field-completion re-ask — the raw
                                      # FAIL is pinned to the first response; any
                                      # verdict token the re-ask returns is ignored.
        },
        ...
      ]
    }

The verdict bytes for each pair are read from **exactly** the ``verdict_path``
named in that pair entry (every file the pairs file does not name is ignored, so
a compromised verifier can affect only its own item — the nonce binding). When no
readable file exists at that path, the pair's transcribed ``response_text`` is the
fallback channel; when neither exists the item carries a verdict defect.

Output — one JSON object on stdout, rc 0 whenever the helper ran::

    {
      "results": [ { "id", "raw_verdict", "verdict", "normalized",
                     "evidence", "file_checked", "view_revision", "source",
                     "defect", "defect_class",
                     "normalization_ineligible", "demoted" (source-defect demotions only) }, ... ],
      "needs_retry": [ { "id", "kind": "verdict"|"auxiliary", "defect" }, ... ],
      "counts": { "normalized_count", "field_defect_fail_count" }
    }

``view_revision`` (issue #851) is the 40-hex commit id of the source view the verifier read,
carried through for the build-mode provenance gate below; a non-string is dropped to null.

A malformed pairs file (unparseable / truncated / wrong-shape) instead prints the
structured **bad-input report** — ``{"bad_input": true, "error": ...}`` — to
stdout with rc 0, so a transcription failure is an outcome distinguishable from
results, from error text, and from silence (a matcher denial prints nothing).

Verdict defect shapes (item keeps its raw verdict, is normalization-ineligible,
and enters ``needs_retry`` with kind ``verdict``): ``missing_fence`` (no ``json``
fence and the body does not contain exactly one parseable object),
``unparseable_json``, ``missing_verdict_field``, ``non_enum_verdict``,
``id_mismatch``, ``no_verdict`` (neither file nor response_text),
``no_verdict_trusted_file_unreadable`` (same, but the named nonce file existed
and could not be read — a filesystem fault a verifier re-dispatch cannot fix).
Build mode adds ``verdict_file_absent`` (issue #1144): a fresh, unpinned agent item
whose verdict came off ``response_text`` because its nonce file is absent keeps that
verdict in the tally, and this one kind-``verdict`` entry replaces any auxiliary one —
the fix loop's evidence gate FAILs the missing file, so the engine re-dispatches it.
More than one ``json`` fence reads the LAST fence as authoritative
(final-answer convention).

Two defect classes are NOT verifier defects and are reported under their own
``needs_retry`` kinds so the engine does not re-dispatch a verifier at them:
``defect_class: "channel"`` / kind ``channel`` — ``trusted_file_unreadable``,
stamped in EVERY verdict direction when the named nonce file was present but
unreadable, because a forged PASS is the payload the nonce binding exists to
stop; and ``defect_class: "helper_internal"`` / kind ``helper_internal`` —
``pair_processing_error``, an unexpected exception contained per-pair (with a
real traceback on stderr) so a single corrupt element never aborts the batch.

Auxiliary-field defects (an absent / unknown-token / wrong-typed
``property_proven`` or ``inaccuracy_scope``) never invalidate a well-formed
verdict: the item keeps its raw verdict (or its source-defect demotion) and is
normalization-ineligible. An auxiliary defect enters ``needs_retry`` with kind ``auxiliary`` for a
field-completion re-ask only on an item that is an agent-mode
(``verification_mode == "agent"``), ``claim_provenance: "generated_paraphrase"``
pair whose raw verdict is the byte-exact token ``FAIL`` **and** that is not
itself already a pinned re-ask (the re-ask fires at most once); a PASS or
INCONCLUSIVE with a defective auxiliary field is never re-dispatched.

A raw FAIL whose auxiliary fields are BOTH well-typed can still be a contradiction
(issue #2099): ``inaccuracy_scope == "generated_claim_text"`` asserts the code is
correct while boolean ``property_proven`` is ``false`` leaves the intended property
unproven. When the property-not-proven real blocker is the SOLE normalization blocker
(no field defect, and none of the four other real blockers below), that pair is not a
settled answer — it enters ``needs_retry`` with kind ``auxiliary`` for the same
one-shot pinned re-ask, at most once per item across the field-defect and contradiction
classes together. A re-ask that positively proves the property normalizes through the
unchanged five-conjunct predicate; any other re-ask outcome leaves the raw FAIL
standing. The four other real blockers that instead keep the terminal behavior are:
``mode != "agent"``, ``category == "issue_acceptance"``, ``source_authored``
provenance, and a trusted verdict file present but unreadable.

Reading the verdict bytes off the fallback ``response_text`` channel when the
named nonce file was PRESENT but unreadable is a real-value normalization blocker
(the trusted binding was abandoned). An absent file is not a blocker; see
``verdict_file_absent`` above for when build mode re-dispatches it.

The five-conjunct normalization predicate (raw FAIL -> stored PASS) holds exactly
when ALL hold: (1) ``verification_mode == "agent"``; (2)
``claim_provenance == "generated_paraphrase"``; (3) raw verdict byte-exact
``FAIL``; (4) ``property_proven`` is JSON boolean ``true`` (a JSON string
``"true"`` does not qualify — a real type check); (5)
``inaccuracy_scope == "generated_claim_text"``. No malformed shape of any class
ever resolves to a stored PASS.

Source-defect demotion (issue #1140): a raw ``PASS`` on a
``claim_provenance: "source_authored"`` item whose ``inaccuracy_scope`` is exactly
``source_authored_text`` reports the item's own authored subject false, so it is stored
``FAIL`` with an added ``demoted: true`` key, ``raw_verdict: "PASS"`` and the ``CONFIRMED SOURCE DEFECT
(raw PASS): `` evidence prefix, and draws no auxiliary re-ask. A defective scope field never demotes.
In build mode a non-``ok`` view state still stores ``INCONCLUSIVE`` with the view marker
instead.

An item whose ``category`` is ``issue_acceptance`` is additionally never
normalization-eligible: such items satisfy conjuncts (1) and (2) structurally, so
only the verifier's own self-reported auxiliary fields would stand between a raw
FAIL on an acceptance criterion and a stored PASS.

Build mode — ``<inputs-file> --checklist <checklist-iter-N.json> --verdicts-dir
<dir> --out <verification-iter-N.json>``. The helper derives the pairs itself and
writes the combined verification array, so the orchestrator types only judgment::

    {
      "nonces":         { "VC-3": "<nonce>" },            # one per dispatched item
      "lite":           [ { "id", "verdict", "evidence", "file_checked", "view_revision" } ],
      "response_text":  { "VC-9": "<response of a verifier that wrote no file>" },
      "pinned_verdict": { "VC-4": "FAIL" },               # field-completion re-ask
      "pinned_from":    { "VC-4": "<first answer's nonce>" },   # its provenance source
      "recovered":      { "VC-9": { "verdict", "evidence", "inaccuracy_scope"? } },  # in-context recovery
      "views":          { "head": { "revision": "<40-hex>", "inventory": "<path>" },
                          "base": { "revision": "<40-hex>", "inventory": "<path>" } }
    }

``views`` (issue #851) binds the run's head and base source-view inventories. When present,
the collector runs a provenance gate before the tally: a verdict whose ``view_revision`` is
not the bound head or base, is absent, or whose ``file_checked`` path is absent from that
view's inventory and not recorded there as ``deleted`` (a bare directory holding a present
entry counts as present), is left unestablished and cannot earn
PASS (a raw PASS is forced to INCONCLUSIVE with a ``view_ineligible`` marker; cited evidence
text is never byte-compared). A 12-39 lowercase-hex ``view_revision`` prefixing exactly one bound
revision is first replaced by that revision, with an ``input_warnings`` line. The gate is inert when ``views`` is absent, so a legacy run is
unaffected and the wording-only normalization contract is unchanged. The summary carries a
``view_check`` object ``{bound_revisions, states}``.

``pinned_from`` (issue #1027) names a pinned item's first-answer nonce. The stored ``evidence``,
``file_checked`` and ``view_revision`` then come from ``<verdicts-dir>/<id>-<that nonce>.json``,
and the re-ask's copies of those three fields are ignored. An unusable entry (a non-string or
unsafe nonce, no matching ``pinned_verdict``, or a first file that is absent, unreadable,
unparseable or carries none of the three fields) is ignored with an ``input_warnings`` line; the item grades as it would without it.

Each checklist item is partitioned exactly as the evidence gate partitions it: a
``reused_from_iter_prev: true`` item carrying a prior ``PASS`` keeps the verdict it
arrived with; an effective-lite item takes its ``lite`` entry; every other item is
an agent pair whose ``verdict_path`` is ``<verdicts-dir>/<id>-<nonce>.json`` — the
nonce comes ONLY from ``nonces``, never from a directory listing, so the binding
above holds. No stored verdict is ever null: an item with no usable verdict stores
``INCONCLUSIVE`` naming the defect, and ``recovered`` applies only to a
verdict-defect item. Every optional input is classified in ``inputs_seen`` and a
wrong-typed one is ignored with an ``input_warnings`` line. A wrong-typed
``response_text`` value is ignored and an empty one read, each with a line, as is a
supplied map lacking a file-less item. Stdout is the summary
``{written, tally, counts, needs_retry, non_pass, inputs_seen, input_warnings}``;
when the ``--out`` write fails, ``written`` is null and the array rides along as
``verification`` for the orchestrator to Write.

``checklist <op> …`` as the first argument instead routes to the Phase 1 checklist
assembly in the sibling ``checklist_finalize.py`` (its ops, files and output are
documented there). It rides this helper because a cloud profile grants leading
tokens per helper, and this one is granted wherever the review engine runs.

Prepare mode — ``prepare <checklist-iter-N.json> --verdicts-dir <dir> [--fields <file>]`` —
is Phase 2.0's dispatch plan, run before an engine entry's first verifier dispatch, and again
with ``--fields`` after the pre-dispatch re-ask, still before that dispatch. ``--fields`` names
the re-ask's answer, ``{"<id>": {"claim_provenance", "source_excerpt"}}``: prepare writes into
the checklist file (atomically, only beneath a ``.prflow/tmp/`` pair) each field a fresh agent
item lacks — ``claim_provenance`` one of the two enum values, ``source_excerpt`` a non-empty
string on a ``source_authored`` item — and warns about, then ignores, every other entry; an
unusable fields file or a failed write merges nothing. It loads the checklist (the same ``bad_input`` report as build mode, deleting nothing),
refuses with a ``usage`` object (rc 2, deleting nothing) a ``<dir>`` that does not resolve
beneath a ``.prflow/tmp/`` pair or whose last component is not ``iter-<N>``, then creates
``<dir>``, unlinks every regular file and symlink directly inside it (a subdirectory stays;
nothing outside ``<dir>`` is touched), partitions the items exactly as build mode does, and
prints — to stdout only, never to a file, since a written nonce is one a running verifier
could read::

    { "ok": true, "iteration": N, "verdicts_dir": "<dir>",
      "items_dir": "<checklist path without .json>.items" | null,
      "reused": [ "<id>" ],                                   # carried PASS, not dispatched
      "lite":   [ { "id", "lite_probe" } ],                   # effective-lite items
      "agent":  [ { "id", "nonce" } ],                        # 16 lowercase hex, distinct
      "missing_fields": [ { "id", "claim_signature", "fields": [...] } ],   # agent items only
      "counts": { "reused", "lite", "agent", "missing_fields" },
      "wiped": <files removed>, "warnings": [...] }

``items_dir`` sits beside the checklist and is spelled as the checklist argument was. Prepare
unlinks every regular file and symlink directly inside it (a subdirectory stays), then writes each agent item's checklist object — no
nonce — to ``<items_dir>/<id>.json`` (UTF-8, ``\\n`` newlines), so a verifier reads only its
own item. It is null, with a warning naming the cause, when that directory resolves outside
a ``.prflow/tmp/`` pair, is a symlink, or a write fails; the rest of the plan is unchanged.

An item whose id is not usable as a file-name part is skipped with a warning naming it
and gets no nonce and no item file. A later single-item dispatch inside the same entry
mints its own nonce and never re-runs prepare: a re-run wipes the wave's verdict files.

Exit codes:
    0  Helper ran (results OR bad-input report printed).
    1  Unsupported Python (< 3.11).
    2  Bad arguments (no pairs-file or build-mode inputs-file path given; a build-mode
       flag without its value, or build mode without all of its flags; a prepare-mode
       usage refusal).
"""

import itertools
import json
import os
import posixpath
import re
import secrets
import sys
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


VERDICT_ENUM = ("PASS", "FAIL", "INCONCLUSIVE")
SCOPE_ENUM = ("generated_claim_text", "source_authored_text", "none")
NORMALIZED_PREFIX = "NORMALIZED (wording-only): "
SOURCE_DEFECT_PREFIX = "CONFIRMED SOURCE DEFECT (raw PASS): "
# Single-sourced so the contradiction detection below compares against the SAME literal
# the blocker assembly appends — a renamed string here can never silently stop the
# is_contradiction match firing.
PROPERTY_NOT_PROVEN_BLOCKER = "property not proven"
# issue #2099 — the well-typed contradiction (generated_claim_text + property_proven false);
# see the module docstring. Drives one pinned auxiliary re-ask (see _process_pair).
CONTRADICTION_DEFECT = "contradiction:generated_claim_text_but_property_unproven"
CONTRADICTION_INELIGIBLE = (
    "contradiction: inaccuracy_scope generated_claim_text asserts the code is correct "
    "but property_proven is false"
)


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
                except (json.JSONDecodeError, ValueError):
                    parsed = None
                if isinstance(parsed, dict):
                    objs.append(parsed)
                start = -1
    return objs


def _json_fences(text):
    """Return the inner text of each ```` ```json ... ``` ```` fence, in order."""
    fences = []
    marker = "```json"
    idx = 0
    while True:
        open_at = text.find(marker, idx)
        if open_at == -1:
            break
        body_start = open_at + len(marker)
        close_at = text.find("```", body_start)
        if close_at == -1:
            break
        fences.append(text[body_start:close_at])
        idx = close_at + 3
    return fences


def extract_verdict_object(text):
    """Parse the verdict object out of verifier bytes (a file's content or a
    transcribed response). Returns ``(obj, defect)`` — exactly one is None.

    Parse contract: prefer ``json`` fences (LAST fence authoritative when more
    than one); with no fence, tolerate a body that contains exactly one parseable
    JSON object; otherwise ``missing_fence``."""
    if text is None:
        return None, "no_verdict"
    fences = _json_fences(text)
    if fences:
        chosen = fences[-1].strip()
        try:
            obj = json.loads(chosen)
        except (json.JSONDecodeError, ValueError):
            return None, "unparseable_json"
        if not isinstance(obj, dict):
            return None, "unparseable_json"
        return obj, None
    objs = _brace_objects(text)
    if len(objs) == 1:
        return objs[0], None
    # zero parseable objects, or an ambiguous multiple — neither is a verdict.
    return None, "missing_fence"


def _aux_state(obj, field):
    """Classify an auxiliary field. Returns one of ``"ok"``, ``"real"``
    (present, correct type, a legitimate non-normalizing value), or ``"defect"``
    (absent / wrong type / unknown token — a field-emission miss)."""
    present = field in obj
    val = obj.get(field)
    if field == "property_proven":
        if not present:
            return "defect"
        if not isinstance(val, bool):  # a JSON string "true" is NOT a boolean
            return "defect"
        return "ok" if val is True else "real"
    if field == "inaccuracy_scope":
        if not present or not isinstance(val, str) or val not in SCOPE_ENUM:
            return "defect"
        return "ok" if val == "generated_claim_text" else "real"
    return "defect"


def _read_verdict_bytes(pair):
    """Return ``(text, source)`` — the verdict bytes and their channel. Reads ONLY
    the exact ``verdict_path`` named in this pair (ignoring every unnamed file);
    falls back to the transcribed ``response_text`` when no readable file exists.

    An ABSENT file is the fallback and yields ``source == "response_text"``; ``build()``
    decides its re-dispatch.
    A file that is PRESENT but unreadable (permission error or invalid UTF-8) is an
    anomaly — the trusted channel was abandoned — so it yields
    ``source == "response_text_file_unreadable"`` (still a response_text read) so the
    downgrade off the authoritative nonce file is observable, never silent."""
    downgraded = False
    path = pair.get("verdict_path")
    if isinstance(path, str) and path:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read(), "file"
        except FileNotFoundError:
            pass  # file absent -> response_text fallback; build() decides re-dispatch
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
    """Stamp a verdict-defect result and its full-re-dispatch retry entry.
    Returns ``(result, retry, False)`` — a verdict defect is never a
    field-defect-fail (it has no established raw verdict)."""
    result["defect"] = defect
    result["defect_class"] = "verdict"
    result["normalization_ineligible"] = f"verdict defect: {defect}"
    return result, {"id": item_id, "kind": "verdict", "defect": defect}, False


PROVENANCE_FIELDS = ("evidence", "file_checked", "view_revision")


def _first_provenance(path):
    """Return ``(fields, None)`` or ``(None, reason)``: the three provenance fields of a pinned
    item's first answer (issue #1027), read through the same channel as a verdict file."""
    text, source = _read_verdict_bytes({"verdict_path": path})
    if text is None:
        return None, ("first verdict file unreadable" if source == "none_file_unreadable"
                      else "first verdict file absent")
    obj, defect = extract_verdict_object(text)
    if defect is not None:
        return None, f"first verdict file unparseable ({defect})"
    fields = {k: obj[k] if isinstance(obj.get(k), str) else None for k in PROVENANCE_FIELDS}
    if not any(fields.values()):
        return None, "first verdict file has no evidence, file_checked or view_revision"
    return fields, None


def _process_pair(pair, first=None):
    """Return ``(result_dict, retry_entry_or_None, is_field_defect_fail)`` for one
    pair. ``is_field_defect_fail`` is decided here from the structured blocker
    lists (never re-derived from the rendered ``normalization_ineligible`` string).
    ``first`` (build mode only) is a pinned pair's first-answer provenance, which
    replaces the re-ask's."""
    item = pair.get("item") if isinstance(pair.get("item"), dict) else {}
    item_id = item.get("id")
    mode = item.get("verification_mode")
    provenance = item.get("claim_provenance")
    pinned = pair.get("pinned_verdict")

    text, source = _read_verdict_bytes(pair)
    obj, defect = extract_verdict_object(text)
    is_pinned = isinstance(pinned, str) and pinned in VERDICT_ENUM
    # The named nonce file EXISTED but could not be read, so the verdict bytes came off
    # the untrusted fallback channel — the binding the forgery guard rests on was
    # abandoned. Stamped unconditionally below, in EVERY verdict direction: a forged
    # PASS is the payload the nonce guard exists to stop, so gating the signal on a raw
    # FAIL would leave the direction that actually matters silent.
    trusted_channel_lost = source in ("response_text_file_unreadable",
                                      "none_file_unreadable")

    result = {
        "id": item_id,
        "raw_verdict": None,
        "verdict": None,
        "normalized": False,
        "evidence": None,
        "file_checked": None,
        "view_revision": None,
        "source": source,
        "defect": None,
        "defect_class": None,
        "normalization_ineligible": None,
    }

    if is_pinned:
        # Pinned-first-verdict rule (field-completion re-ask): the raw verdict is
        # PINNED to the first response's FAIL, and the re-ask response is parsed ONLY
        # for the two auxiliary fields — any verdict token it returns, OR its absence
        # (a compliant re-ask returns only the aux fields), is ignored. The re-ask
        # fires at most once, so a verdict-less / unparseable response never
        # re-dispatches: the pinned raw stands and the item resolves through the
        # predicate below. (Ordered before the verdict-defect arms so a compliant
        # aux-only response is never mis-classified as missing_verdict_field.)
        raw = pinned
        obj = obj if isinstance(obj, dict) else {}
    else:
        # --- verdict-defect arm: keep no verdict, flag for a full re-dispatch ----
        if defect is not None:
            if defect == "no_verdict" and trusted_channel_lost:
                # Discriminate "the verifier produced nothing anywhere" from "the named
                # nonce file EXISTS but this process cannot read it" (permission fault,
                # corrupt mount, invalid UTF-8). Collapsing them onto a bare no_verdict
                # sends the engine's kind-`verdict` remedy at a re-dispatch that will
                # re-produce a file it still cannot read — burning a retry on a
                # filesystem fault the verifier cannot fix.
                defect = "no_verdict_trusted_file_unreadable"
            return _verdict_defect(result, item_id, defect)
        # object well-formed enough to inspect; validate the mandatory verdict field
        if "verdict" not in obj:
            return _verdict_defect(result, item_id, "missing_verdict_field")
        raw = obj.get("verdict")
        if not isinstance(raw, str) or raw not in VERDICT_ENUM:
            return _verdict_defect(result, item_id, "non_enum_verdict")
        obj_id = obj.get("id")
        if item_id is not None and obj_id is not None and obj_id != item_id:
            return _verdict_defect(result, item_id, "id_mismatch")

    evidence = obj.get("evidence")
    result["raw_verdict"] = raw
    result["verdict"] = raw  # defaults to raw; normalization or source-defect demotion may flip it
    result["evidence"] = evidence if isinstance(evidence, str) else None
    fc = obj.get("file_checked")
    result["file_checked"] = fc if isinstance(fc, str) else None
    # issue #851: the commit-bound view revision the verifier read, carried through for the
    # collector's provenance check (build mode). Non-string is dropped to None so the check
    # treats it as absent rather than crashing.
    vr = obj.get("view_revision")
    result["view_revision"] = vr if isinstance(vr, str) else None
    if is_pinned and first is not None:
        # issue #1027: a compliant re-ask carries only the two auxiliary fields, so the
        # provenance comes from the first answer; the re-ask's own copies are ignored.
        result.update(first)

    # --- auxiliary-field classification ----------------------------------------
    pp_state = _aux_state(obj, "property_proven")
    scope_state = _aux_state(obj, "inaccuracy_scope")
    aux_defects = []
    if pp_state == "defect":
        aux_defects.append("property_proven")
    if scope_state == "defect":
        aux_defects.append("inaccuracy_scope")

    # --- five-conjunct normalization predicate ---------------------------------
    real_blockers = []
    field_defect_blockers = []
    if mode != "agent":
        real_blockers.append("not agent")
    if item.get("category") == "issue_acceptance":
        real_blockers.append("issue_acceptance category")
    if provenance != "generated_paraphrase":
        if provenance == "source_authored":
            real_blockers.append("source_authored provenance")
        elif provenance is None:
            field_defect_blockers.append("claim_provenance absent")
        else:
            field_defect_blockers.append("claim_provenance invalid")
    if pp_state == "real":
        real_blockers.append(PROPERTY_NOT_PROVEN_BLOCKER)
    elif pp_state == "defect":
        field_defect_blockers.append("property_proven field defect")
    if scope_state == "real":
        real_blockers.append("inaccuracy_scope not generated_claim_text")
    elif scope_state == "defect":
        field_defect_blockers.append("inaccuracy_scope field defect")
    if trusted_channel_lost:
        # A real-value blocker, not a field defect: a raw FAIL read over an abandoned
        # trusted channel must never silently store as PASS. (A genuinely ABSENT file
        # does not reach here.)
        real_blockers.append("trusted verdict file present but unreadable")

    can_normalize = (
        raw == "FAIL"
        and not real_blockers
        and not field_defect_blockers
    )

    if can_normalize:
        result["verdict"] = "PASS"
        result["normalized"] = True
        base = result["evidence"] or ""
        result["evidence"] = NORMALIZED_PREFIX + base
        return result, None, False

    if (raw == "PASS" and provenance == "source_authored"
            and obj.get("inaccuracy_scope") == "source_authored_text"):
        result["verdict"] = "FAIL"
        result["demoted"] = True
        result["evidence"] = _source_defect_evidence(result["evidence"])

    # raw FAIL not normalized: record the ineligibility reason(s)
    if raw == "FAIL":
        blockers = real_blockers + field_defect_blockers
        if blockers:
            result["normalization_ineligible"] = "; ".join(blockers)

    # Exact membership for ``field_defect_fail_count``, decided from the STRUCTURED
    # blocker lists (never re-parsed from the rendered string): a raw byte-exact
    # FAIL whose SOLE normalization blocker is a field defect — a real-value blocker
    # (source_authored provenance, property-not-proven, lite item) disqualifies it.
    is_field_defect_fail = (
        raw == "FAIL"
        and bool(field_defect_blockers)
        and not real_blockers
    )

    # issue #2099 — property-not-proven as the SOLE real blocker with no field defect. Any
    # OTHER real blocker makes real_blockers non-singleton, which is what suppresses the
    # re-ask and keeps the terminal behavior; the singleton also forces agent/generated.
    is_contradiction = (
        raw == "FAIL"
        and real_blockers == [PROPERTY_NOT_PROVEN_BLOCKER]
        and not field_defect_blockers
    )

    # auxiliary re-ask: only for a raw FAIL + generated_paraphrase agent item with a
    # defective auxiliary field (never re-roll a PASS/INCONCLUSIVE — a bookkeeping
    # defect must not re-roll a decided verdict). The common defect stamp is hoisted;
    # only the retry entry is gated on the re-ask population.
    retry = None
    if aux_defects:
        result["defect"] = "aux:" + ",".join(aux_defects)
        result["defect_class"] = "auxiliary"
        # A pinned pair is the re-ask and never re-dispatches again. A real-value blocker
        # other than the property-not-proven contradiction below also disqualifies the
        # re-ask — completing fields cannot normalize what a real blocker already refuses.
        if (not is_pinned and raw == "FAIL" and provenance == "generated_paraphrase"
                and mode == "agent" and not real_blockers):
            retry = {"id": item_id, "kind": "auxiliary", "defect": ",".join(aux_defects)}
    elif is_contradiction:
        # Both fields well-typed, so the field-defect arm did not fire — draw one re-ask
        # through the same auxiliary channel (at most one per item across both classes).
        result["defect"] = CONTRADICTION_DEFECT
        result["defect_class"] = "auxiliary"
        result["normalization_ineligible"] = CONTRADICTION_INELIGIBLE
        # is_contradiction already forces mode==agent and provenance==generated_paraphrase,
        # so the only remaining gate is that this pair is not itself the pinned re-ask.
        if not is_pinned:
            retry = {"id": item_id, "kind": "auxiliary", "defect": CONTRADICTION_DEFECT}

    if trusted_channel_lost:
        # Stamped LAST so it takes precedence over an auxiliary stamp, and stamped in
        # every verdict direction (not only raw FAIL) — a clean PASS read off the
        # abandoned trusted channel was previously recorded ONLY as a soft `source`
        # string that no consumer reads, which is the forged-PASS case the nonce
        # binding exists to stop. `defect`/`defect_class`/`needs_retry` are the fields
        # the engine's Phase 2.2 actually consumes; `source` stays diagnostic-only.
        result["defect"] = "trusted_file_unreadable"
        result["defect_class"] = "channel"
        result["normalization_ineligible"] = "trusted verdict file present but unreadable"
        retry = {"id": item_id, "kind": "channel", "defect": "trusted_file_unreadable"}

    return result, retry, is_field_defect_fail


def run(pairs_file):
    try:
        with open(pairs_file, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except (OSError, UnicodeDecodeError, ValueError) as e:
        # ValueError for symmetry with _read_verdict_bytes' embedded-NUL arm. Not
        # reachable from argv (execve cannot carry a NUL), but this open() is the same
        # shape one level up and the asymmetry would read as an oversight.
        return {"bad_input": True, "error": "pairs_file_unreadable", "detail": str(e)}

    if not raw.strip():
        return {"bad_input": True, "error": "pairs_file_empty",
                "detail": "the pairs file was empty"}
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        return {"bad_input": True, "error": "pairs_file_unparseable",
                "detail": f"not valid JSON (truncated or mis-escaped transcription?): {e}"}
    if not isinstance(payload, dict) or not isinstance(payload.get("pairs"), list):
        return {"bad_input": True, "error": "pairs_file_wrong_shape",
                "detail": "expected a JSON object with a 'pairs' array"}
    return run_pairs(payload["pairs"])


def run_pairs(pairs, firsts=None):
    """Process a pairs list (from a pairs file, or derived by ``build``). ``firsts`` maps a
    pair index to its first-answer provenance (build mode only)."""
    results = []
    needs_retry = []
    field_defect_fail_count = 0
    for idx, pair in enumerate(pairs):
        if not isinstance(pair, dict):
            # A non-dict element (a stray null/string/number/list from a corrupt
            # transcription) is a verdict defect, NOT a silent no-op: emit an
            # observable result + retry so a single-element corruption cannot drop a
            # verdict unnoticed (the pairs file is LLM-transcribed, so this is the
            # per-element analogue of the whole-file bad-input report).
            malformed = {
                "id": None, "raw_verdict": None, "verdict": None, "normalized": False,
                "evidence": None, "file_checked": None, "source": "none",
                "defect": "malformed_pair", "defect_class": "verdict",
                "normalization_ineligible": "verdict defect: malformed_pair",
                "pair_index": idx,
            }
            results.append(malformed)
            needs_retry.append({"id": None, "kind": "verdict",
                                "defect": "malformed_pair", "pair_index": idx})
            continue
        try:
            result, retry, is_field_defect_fail = _process_pair(pair, (firsts or {}).get(idx))
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
                "evidence": None, "file_checked": None, "source": "none",
                "defect": "pair_processing_error", "defect_class": "helper_internal",
                # The detail is exception-derived and the pairs file is LLM-transcribed
                # from PR-author-controlled source, so it is bounded and repr-delimited
                # before it can reach a rendered report.
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
        results.append(result)
        if retry is not None:
            needs_retry.append(retry)
        if is_field_defect_fail:
            field_defect_fail_count += 1

    normalized_count = sum(1 for r in results if r.get("normalized"))

    return {
        "results": results,
        "needs_retry": needs_retry,
        "counts": {
            "normalized_count": normalized_count,
            "field_defect_fail_count": field_defect_fail_count,
        },
    }


def _checklist_main(argv):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import checklist_finalize
    except ImportError as e:
        # stdout, not only stderr: byte-empty stdout reads as a matcher denial.
        print(json.dumps({"ok": False, "error": "checklist_module_missing",
                          "detail": str(e)[:200]}, indent=2))
        return 0
    return checklist_finalize.main(argv)


BUILD_FLAGS = ("--checklist", "--verdicts-dir", "--out")
_INPUT_TYPES = {"nonces": dict, "lite": list, "response_text": dict,
                "pinned_verdict": dict, "recovered": dict, "views": dict, "pinned_from": dict}

# issue #851 collector view-provenance check.
VIEW_INELIGIBLE_PREFIX = "VIEW-UNESTABLISHED: "
_HEX40 = tuple("0123456789abcdef")


def _is_hex40(value):
    # Accept a 40-hex (SHA-1) or 64-hex (SHA-256) commit id, matching the producer's
    # HEX40_RE in review-engine-io.py: a SHA-256 repo emits 64-hex revisions, and a
    # collector that rejected them would demote every PASS on such a repo.
    return isinstance(value, str) and len(value) in (40, 64) and all(c in _HEX40 for c in value)


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


def _view_prefixes(inv_path):
    """The bound view's directory, as the prefixes a cited path may carry: the directory of
    ``views[slot].inventory`` as given plus its absolute and symlink-resolved forms (the
    verifier's Read tool takes absolute paths, so a verifier may cite any of them), ``\\``
    normalized to ``/``, ``.`` segments collapsed, no trailing separator. Empty when the
    inventory path has no directory part."""
    head = posixpath.dirname(inv_path.replace("\\", "/").rstrip("/"))
    if not head:
        return ()
    rel = posixpath.normpath(head).rstrip("/")
    forms = {rel}
    for form in (os.path.abspath(rel), os.path.realpath(rel)):
        forms.add(posixpath.normpath(form.replace("\\", "/")).rstrip("/"))
    return tuple(sorted(forms, key=len, reverse=True))


def _bare_key(text, prefixes):
    """One citation reduced to its inventory key: ``\\`` normalized to ``/``, the trailing
    anchor list stripped, a leading bound-view directory removed (an absolute citation is also
    tried symlink-resolved, as the cwd may be). May be ``""``."""
    key = _strip_line_anchor(text.replace("\\", "/").strip())
    forms = [key]
    if prefixes and os.path.isabs(key):
        forms.append(posixpath.normpath(os.path.realpath(key).replace("\\", "/")))
    for form in forms:
        for prefix in prefixes:
            if form.startswith(prefix + "/"):
                return _ViewStripped(form[len(prefix) + 1:])
    return key


class _ViewStripped(str):
    """A key a bound view's directory prefix was stripped from: it may name a file, never a
    directory (issue #1123 accepts only the bare repository form of a directory)."""


class _ViewInventory(frozenset):
    """One bound view's inventory keys, plus ``has_dir``: whether a key is a directory holding at
    least one present (not ``deleted``) entry."""

    def __new__(cls, paths, dirs=()):
        inv = super().__new__(cls, paths)
        inv._dirs = frozenset(dirs)
        return inv

    def has_dir(self, key):
        return key in self._dirs


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
    """The inventory keys a ``file_checked`` cites, for the gate to require ALL of.

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
    separator alone) is returned as itself — both are non-members, so a citation that names no
    file demotes exactly as before. Only a non-string or the empty string ``""`` returns ``[]``
    (unchanged: those were never path-checked)."""
    if not isinstance(fc, str) or fc == "":
        return []
    whole = _bare_key(fc, prefixes)
    if _in_view(whole, inventory):
        return [whole]
    keys = []
    for part in fc.replace(" and ", ";").replace(",", ";").split(";"):
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


def _load_view_index(views):
    """Parse the build-mode ``views`` input into ``(index, bound_revisions, head_revision, warnings, dirs)``.

    ``index`` maps each bound revision SHA to the set of paths its inventory records (present
    entries AND ``kind: "deleted"`` records alike — a deleted record is legitimate absence, not
    an unread path) as a ``_ViewInventory`` whose ``has_dir`` names each directory holding a
    present entry. ``bound_revisions`` is the set of the run's head/base revisions and
    ``head_revision`` is the head slot's revision (or ``None``); ``dirs`` maps each bound revision
    to its view-directory prefixes (``_view_prefixes``). A malformed ``views`` block, or
    an unreadable/mis-shaped inventory, yields no bound revision for that slot and a warning; when
    the run supplied ``views`` but none are usable the caller fails closed (build()'s gate),
    never standing a raw PASS unchecked. The adversarial
    {object,array,scalar,valid-falsy,missing,wrong-type} matrix is guarded here."""
    index, bound, warnings, head_revision, dirs = {}, set(), [], None, {}
    if not isinstance(views, dict) or not views:
        return index, bound, head_revision, warnings, dirs
    for slot in ("head", "base"):
        spec = views.get(slot)
        if slot not in views:
            continue
        if not isinstance(spec, dict):
            warnings.append(f"views[{slot}]: expected an object, got {_shape(True, spec)} -- ignored")
            continue
        revision = spec.get("revision")
        inv_path = spec.get("inventory")
        if not _is_hex40(revision):
            warnings.append(f"views[{slot}]: revision is not a 40- or 64-hex commit id -- ignored")
            continue
        if not isinstance(inv_path, str) or not inv_path:
            warnings.append(f"views[{slot}]: inventory path missing -- ignored")
            continue
        try:
            with open(inv_path, "r", encoding="utf-8") as fh:
                inv = json.load(fh)
        except (OSError, UnicodeDecodeError, ValueError) as e:
            warnings.append(f"views[{slot}]: inventory unreadable/unparseable ({str(e)[:80]}) -- ignored")
            continue
        entries = inv.get("entries") if isinstance(inv, dict) else None
        if not isinstance(entries, list):
            warnings.append(f"views[{slot}]: inventory has no entries array -- ignored")
            continue
        # An entry's stored_path (a harness-instruction file under its ``.src`` suffix) is the
        # name the verifier Reads, so it is a key of this view alongside the original path.
        paths = {e[k] for e in entries if isinstance(e, dict)
                 for k in ("path", "stored_path") if isinstance(e.get(k), str)}
        present = {e["path"] for e in entries if isinstance(e, dict)
                   and isinstance(e.get("path"), str) and e.get("kind") != "deleted"}
        index[revision] = _ViewInventory(paths, {p.rsplit("/", i)[0] for p in present
                                                 for i in range(1, p.count("/") + 1)})
        dirs[revision] = _view_prefixes(inv_path)
        bound.add(revision)
        if slot == "head":
            head_revision = revision
    return index, bound, head_revision, warnings, dirs


def _expand_view_prefix(vr, bound):
    """Return the one bound revision ``vr`` prefixes when ``vr`` is 12-39 lowercase hex, else ``None``.
    Keep ``_is_hex40`` strict: the ``views`` slot validation shares it."""
    if not (isinstance(vr, str) and 12 <= len(vr) <= 39 and all(c in _HEX40 for c in vr)):
        return None
    matches = [rev for rev in bound if rev.startswith(vr)]
    return matches[0] if len(matches) == 1 else None


def _view_state(entry, index, bound, dirs):
    """Classify a verification entry's view provenance against the bound inventories.
    Returns ``"ok"`` | ``"absent"`` | ``"wrong-revision"`` | ``"path-not-in-inventory"``.
    Cited evidence text is never inspected — only ``view_revision`` and ``file_checked``;
    every path ``file_checked`` cites (``_cited_paths``) must be in that view (``_in_view``)."""
    vr = entry.get("view_revision")
    if not _is_hex40(vr):
        return "absent"
    if vr not in bound:
        return "wrong-revision"
    inventory = index.get(vr, set())
    if any(not _in_view(key, inventory)
           for key in _cited_paths(entry.get("file_checked"), dirs.get(vr, ()), inventory)):
        return "path-not-in-inventory"
    return "ok"


def effective_mode(item):
    """``'lite'`` only for ``verification_mode: "lite"`` with a well-formed
    ``lite_probe``; everything else is ``'agent'`` — the evidence gate's partition
    (scripts/review-evidence-gate.py), so an item the gate demands a nonce file for
    is never settled here by a lite entry."""
    if not isinstance(item, dict) or item.get("verification_mode") != "lite":
        return "agent"
    probe = item.get("lite_probe")
    if (isinstance(probe, dict)
            and probe.get("kind") in ("string_present", "string_absent")
            and isinstance(probe.get("string"), str)
            and isinstance(probe.get("file"), str)):
        return "lite"
    return "agent"


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
    """A checklist id / nonce usable as a filename part: non-empty, no separator,
    no NUL, no parent hop — both are transcribed from PR-author-influenced text."""
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
            "file_checked": None, **extra}


def _source_defect_evidence(evidence):
    """Prefix `evidence` with the source-defect marker once, so _demote_pass's single strip removes it."""
    evidence = evidence or ""
    return evidence if evidence.startswith(SOURCE_DEFECT_PREFIX) else SOURCE_DEFECT_PREFIX + evidence


def _view_gated(entry):
    """True for an entry the view gate must not let stand: a PASS, or a raw PASS the
    source-defect arm demoted (view ineligibility dominates that demotion)."""
    return entry.get("verdict") == "PASS" or entry.get("demoted") is True


def _demote_pass(entry, state):
    """Force a PASS or demoted FAIL to INCONCLUSIVE with the view-ineligibility marker
    for `state`, prefixing the prior evidence. Both build() view-gate arms share this contract.
    Undoes a source-defect demotion first, so its marker never reaches the fixer."""
    evidence = entry.get("evidence") or ""
    if entry.pop("demoted", None) is True:
        evidence = evidence.removeprefix(SOURCE_DEFECT_PREFIX)
    entry["verdict"] = "INCONCLUSIVE"
    entry["view_ineligible"] = state
    entry["evidence"] = VIEW_INELIGIBLE_PREFIX + f"provenance {state}: " + evidence


def build(inputs_file, checklist_file, verdicts_dir, out_file):
    inputs, bad = _load(inputs_file, "inputs_file", dict)
    if bad:
        return bad
    checklist, bad = _load(checklist_file, "checklist", list)
    if bad:
        return bad

    seen, warnings, inp = {}, [], {}
    for key, want in _INPUT_TYPES.items():
        val = inputs.get(key)
        seen[key] = _shape(key in inputs, val)
        if isinstance(val, want):
            inp[key] = val
        else:
            inp[key] = want()
            if key in inputs:
                warnings.append(f"{key}: expected {'object' if want is dict else 'array'}, "
                                f"got {seen[key]} -- ignored")

    lite = {}
    for idx, entry in enumerate(inp["lite"]):
        if (isinstance(entry, dict) and isinstance(entry.get("id"), str)
                and entry.get("verdict") in VERDICT_ENUM):
            lite[entry["id"]] = entry
        else:
            warnings.append(f"lite[{idx}]: needs a string id and a PASS|FAIL|INCONCLUSIVE "
                            "verdict -- ignored")

    pinned_from = {}
    for pid, first_nonce in inp["pinned_from"].items():
        if not isinstance(first_nonce, str):
            why = "nonce is not a string"
        elif not (_path_safe(pid) and _path_safe(first_nonce)):
            why = "id or nonce is not a usable file-name part"
        elif inp["pinned_verdict"].get(pid) not in VERDICT_ENUM:
            why = "no matching pinned_verdict"
        else:
            pinned_from[pid] = first_nonce
            continue
        warnings.append(f"pinned_from[{pid!r}]: {why} -- ignored")

    verification, pairs, slots, firsts = [], [], [], {}
    lite_count = reused_count = 0
    for idx, item in enumerate(checklist):
        if not isinstance(item, dict):
            warnings.append(f"checklist[{idx}]: not an object")
            verification.append(_stub(None, f"checklist element {idx} is not an object"))
            continue
        item_id = item.get("id")
        if item.get("reused_from_iter_prev") is True and item.get("verdict") == "PASS":
            reused_count += 1
            entry = {k: item[k] for k in ("id", "verdict", "evidence", "file_checked",
                                          "raw_verdict", "normalized", "reused_from_iter",
                                          "view_revision")
                     if k in item}
            entry["reused_from_iter_prev"] = True
            verification.append(entry)
        elif effective_mode(item) == "lite":
            lite_count += 1
            got = lite.get(item_id) if isinstance(item_id, str) else None
            if got is None:
                warnings.append(f"lite: no result supplied for {item_id!r}")
                verification.append(_stub(item_id, "no lite-probe result supplied"))
            else:
                ev, fc = got.get("evidence"), got.get("file_checked")
                vr = got.get("view_revision")
                verification.append({"id": item_id, "verdict": got["verdict"],
                                     "evidence": ev if isinstance(ev, str) else None,
                                     "file_checked": fc if isinstance(fc, str) else None,
                                     "view_revision": vr if isinstance(vr, str) else None})
        else:
            key = item_id if isinstance(item_id, str) else None
            pair = {"item": item}
            nonce = inp["nonces"].get(key)
            if _path_safe(key) and _path_safe(nonce):
                pair["verdict_path"] = os.path.join(verdicts_dir, f"{key}-{nonce}.json")
            elif key in inp["nonces"]:
                warnings.append(f"nonces[{key!r}]: id or nonce is not a usable filename "
                                "part -- ignored")
            for field in ("response_text", "pinned_verdict"):
                if isinstance(inp[field].get(key), str):
                    pair[field] = inp[field][key]
            rt = inp["response_text"].get(key)
            if key in inp["response_text"] and not (isinstance(rt, str) and rt):
                warnings.append(f"response_text[{key!r}]: " + ("empty string" if rt == "" else
                                f"expected string, got {_shape(True, rt)} -- ignored"))
            if key in pinned_from:
                first, why = _first_provenance(
                    os.path.join(verdicts_dir, f"{key}-{pinned_from[key]}.json"))
                if first is None:
                    warnings.append(f"pinned_from[{key!r}]: {why} -- re-ask fields kept")
                else:
                    firsts[len(pairs)] = first
            slots.append(len(verification))
            verification.append(None)
            pairs.append(pair)

    ran = run_pairs(pairs, firsts)
    # issue #1144: a fresh, unpinned agent item whose verdict came off the response_text
    # fallback has no nonce file, so the fix loop's evidence gate FAILs it. Keep the verdict, and
    # replace any auxiliary re-ask with one full re-dispatch. Decided from file absence
    # (the source), never from the verdict value.
    absent_ids = []
    for pair, result in zip(pairs, ran["results"]):
        key = result.get("id")
        if (result.get("source") == "response_text" and result.get("defect_class") != "verdict"
                and pair.get("pinned_verdict") not in VERDICT_ENUM and key not in absent_ids):
            absent_ids.append(key)
        elif (result.get("source") == "none" and isinstance(key, str)
                and isinstance(inputs.get("response_text"), dict) and key not in inp["response_text"]):
            warnings.append(f"response_text[{key!r}]: missing and no verdict file")
    needs_retry = [r for r in ran["needs_retry"]
                   if not (r.get("id") in absent_ids and r.get("kind") == "auxiliary")]
    needs_retry += [{"id": k, "kind": "verdict", "defect": "verdict_file_absent"} for k in absent_ids]
    recovered_ids = set()
    for slot, pair, result in zip(slots, pairs, ran["results"]):
        item_id = result.get("id")
        if result.get("verdict") is None:
            rec = inp["recovered"].get(item_id) if isinstance(item_id, str) else None
            if (result.get("defect_class") == "verdict" and isinstance(rec, dict)
                    and rec.get("verdict") in VERDICT_ENUM):
                ev = rec.get("evidence")
                result["verdict"] = result["raw_verdict"] = rec["verdict"]
                result["evidence"] = ev if isinstance(ev, str) else "recovered via in-context parse"
                result["source"] = "recovered"
                recovered_ids.add(item_id)
                # issue #1140: a recovered reply's scope demotes exactly as a parsed one does.
                if (rec["verdict"] == "PASS" and rec.get("inaccuracy_scope") == "source_authored_text"
                        and pair["item"].get("claim_provenance") == "source_authored"):
                    result["verdict"] = "FAIL"
                    result["demoted"] = True
                    result["evidence"] = _source_defect_evidence(result["evidence"])
            else:
                result["verdict"] = "INCONCLUSIVE"
                result["evidence"] = f"verifier produced no usable verdict ({result.get('defect')})"
        verification[slot] = result

    # issue #851 collector view-provenance gate: when the run supplies commit-bound views, a
    # verdict whose provenance the bound inventories cannot confirm (a revision other than the
    # run's head/base, an absent view_revision, or a file_checked path absent from that view's
    # inventory and not recorded deleted) is left unestablished and cannot earn PASS. The gate
    # is inert when no views are supplied (legacy runs), so it never weakens the existing
    # wording-only normalization (AC6). Cited evidence text is never byte-compared (AC3).
    # Read "were views supplied?" from the RAW input, not the coerced inp["views"] (a wrong-typed
    # views is coerced to {} above, so keying on inp["views"] would let a corrupted binding run
    # fail open). A run supplied views when the raw value is a non-empty dict OR the key is present
    # with any non-dict value (a scalar/array/valid-falsy false/0/"" is a corrupted views block,
    # not a legacy omission) — either way the gate fails closed below. A legacy run omits the key
    # or sends an empty dict {}; both stay inert so wording-only normalization is preserved (AC6).
    _raw_views = inputs.get("views")
    views_supplied = ((isinstance(_raw_views, dict) and bool(_raw_views))
                      or ("views" in inputs and not isinstance(_raw_views, dict)))
    view_index, bound_revisions, head_revision, view_warnings, view_dirs = _load_view_index(inp["views"])
    warnings.extend(view_warnings)
    view_states = {"ok": 0, "absent": 0, "wrong-revision": 0, "path-not-in-inventory": 0,
                   "views-unusable": 0}
    if bound_revisions:
        head_paths = view_index.get(head_revision, set()) if head_revision else set()
        for entry in verification:
            # A reused-forward PASS was re-confirmed unchanged at the current head by the engine's
            # variance recovery (Phase 1.0 only carries an item whose source file is byte-identical
            # HEAD-to-HEAD), so its provenance IS the current head. Re-stamp its stale prior
            # view_revision to the head revision when its (anchor-stripped) path is in the head
            # inventory; a reused item whose path is absent from the head view is left to demote.
            if entry.get("reused_from_iter_prev") is True and head_revision is not None:
                keys = _cited_paths(entry.get("file_checked"), view_dirs.get(head_revision, ()),
                                    head_paths)
                if keys and all(key in head_paths for key in keys):
                    entry["view_revision"] = head_revision
            prefix = entry.get("view_revision")
            full = _expand_view_prefix(prefix, bound_revisions)
            if full is not None:
                entry["view_revision"] = full
                warnings.append(f"{entry.get('id')}: view_revision {prefix} expanded to bound revision {full}")
            state = _view_state(entry, view_index, bound_revisions, view_dirs)
            entry["view_state"] = state
            view_states[state] = view_states.get(state, 0) + 1
            if state != "ok" and _view_gated(entry):
                _demote_pass(entry, state)
    elif views_supplied:
        # The run supplied views (it intended commit binding) but none were usable — every slot
        # was malformed or unreadable. Fail closed: provenance cannot be certified, so no raw PASS
        # may stand (issue #851). This is distinct from a legacy run that supplies no views, where
        # the gate is correctly inert and wording-only normalization is preserved (AC6).
        for entry in verification:
            entry["view_state"] = "views-unusable"
            view_states["views-unusable"] += 1
            if _view_gated(entry):
                _demote_pass(entry, "views-unusable")

    tally = {"pass": 0, "fail": 0, "inconclusive": 0, "lite": lite_count,
             "agent": len(pairs), "reused": reused_count}
    for entry in verification:
        tally[entry["verdict"].lower()] += 1

    out = {"written": out_file, "tally": tally, "counts": ran["counts"],
           "needs_retry": [r for r in needs_retry if r.get("id") not in recovered_ids],
           "non_pass": [e for e in verification if e["verdict"] != "PASS"],
           "inputs_seen": seen, "input_warnings": warnings,
           "view_check": {"bound_revisions": sorted(bound_revisions), "states": view_states}}
    try:
        with open(out_file, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(verification, fh, indent=1)
            fh.write("\n")
    except (OSError, ValueError) as e:
        out["written"] = None
        out["write_error"] = str(e)[:200]
        out["verification"] = verification
    return out


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
    the warning naming why prepare prints ``items_dir: null`` — the engine then dispatches
    from the checklist. After a failed write it tries to unlink the files this call wrote,
    and the warning names any it could not remove."""
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


_PROVENANCE = ("generated_paraphrase", "source_authored")


def _fresh_agent(item):
    return (isinstance(item, dict) and effective_mode(item) == "agent"
            and not (item.get("reused_from_iter_prev") is True and item.get("verdict") == "PASS"))


def _complete_field(item, field, value):
    """The reason ``value`` cannot complete ``item[field]``, or None when it can."""
    if isinstance(item.get(field), str):
        return "already set"
    if field == "claim_provenance":
        return None if value in _PROVENANCE else f"{value!r} is not one of {'|'.join(_PROVENANCE)}"
    if item.get("claim_provenance") != "source_authored":
        return "item is not source_authored"
    return None if isinstance(value, str) and value.strip() else f"{value!r} is not a non-empty string"


def _merge_fields(checklist_file, checklist, fields_file, warnings):
    """Write the pre-dispatch re-ask's completed fields (``{"<id>": {"claim_provenance",
    "source_excerpt"}}``) into the checklist file, filling only a field a fresh agent item lacks.
    Returns the checklist to plan from; on any refusal the file is unchanged and a warning
    names why."""
    fields, bad = _load(fields_file, "fields_file", dict)
    if bad:
        warnings.append(f"fields: {bad['error']} ({bad['detail']}) -- nothing merged")
        return checklist
    merged, matched, changed = [], set(), False
    for item in checklist:
        item_id = item.get("id") if _fresh_agent(item) and _path_safe(item.get("id")) else None
        if item_id is None or item_id not in fields:
            merged.append(item)
            continue
        got = fields[item_id]
        matched.add(item_id)
        if not isinstance(got, dict):
            warnings.append(f"fields[{item_id!r}]: expected an object, got {_shape(True, got)} -- ignored")
            merged.append(item)
            continue
        item = dict(item)
        for field in sorted(got, key=lambda f: f != "claim_provenance"):
            why = (_complete_field(item, field, got[field]) if field in ("claim_provenance", "source_excerpt")
                   else "not a completable field")
            if why:
                warnings.append(f"fields[{item_id!r}].{field}: {why} -- ignored")
            else:
                item[field] = got[field]
                changed = True
        merged.append(item)
    for key in fields:
        if key not in matched:
            warnings.append(f"fields[{key!r}]: no fresh agent item has that id -- ignored")
    if not changed:
        return checklist
    if os.path.islink(checklist_file) or not _under_prflow_tmp(checklist_file):
        warnings.append("fields: the checklist is a symlink or outside a .prflow/tmp/ pair -- nothing merged")
        return checklist
    tmp = checklist_file + ".fields-tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, checklist_file)
    except (OSError, UnicodeError) as e:
        left = ""
        if os.path.lexists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                left = f"; {os.path.basename(tmp)} not removed"
        warnings.append(f"fields: checklist write failed ({type(e).__name__}: {e}) -- nothing merged{left}")
        return checklist
    return merged


def prepare(checklist_file, verdicts_dir, fields_file=None):
    """Phase 2.0's dispatch plan (module docstring, *Prepare mode*)."""
    iteration, err = _confined_verdicts_dir(verdicts_dir)
    if err:
        return {"ok": False, "error": "usage", "detail": err}, 2
    checklist, bad = _load(checklist_file, "checklist", list)
    if bad:
        return bad, 0
    warnings = []
    if fields_file is not None:
        checklist = _merge_fields(checklist_file, checklist, fields_file, warnings)
    os.makedirs(verdicts_dir, exist_ok=True)
    wiped = 0
    with os.scandir(verdicts_dir) as entries:
        for entry in entries:
            # A symlink is unlinked as a link (never followed); a directory stays.
            if entry.is_symlink() or entry.is_file(follow_symlinks=False):
                os.unlink(entry.path)
                wiped += 1
    reused, lite, agent, missing, nonces, agent_items = [], [], [], [], set(), []
    for idx, item in enumerate(checklist):
        if not isinstance(item, dict):
            warnings.append(f"checklist[{idx}]: not an object -- skipped")
            continue
        item_id = item.get("id")
        if not _path_safe(item_id):
            warnings.append(f"checklist[{idx}]: id {item_id!r} is not a usable file-name "
                            "part -- skipped, no nonce minted")
            continue
        if item.get("reused_from_iter_prev") is True and item.get("verdict") == "PASS":
            reused.append(item_id)
            continue
        fields = []
        if effective_mode(item) == "lite":
            lite.append({"id": item_id, "lite_probe": item["lite_probe"]})
        else:
            # Only an agent item is re-asked for a normalizer field: a lite item is settled
            # by its probe and never normalizes, so it is never reported here.
            if not isinstance(item.get("claim_provenance"), str):
                fields.append("claim_provenance")
            if item.get("claim_provenance") == "source_authored" and not isinstance(item.get("source_excerpt"), str):
                fields.append("source_excerpt")
            nonce = secrets.token_hex(8)
            while nonce in nonces:
                nonce = secrets.token_hex(8)
            nonces.add(nonce)
            agent.append({"id": item_id, "nonce": nonce})
            agent_items.append((item_id, item))
        if fields:
            missing.append({"id": item_id, "claim_signature": item.get("claim_signature"),
                            "fields": fields})
    items_dir = checklist_file.removesuffix(".json") + ".items"
    items_warning = _write_item_files(items_dir, agent_items)
    if items_warning:
        items_dir = None
        warnings.append(items_warning)
    return {"ok": True, "iteration": iteration, "verdicts_dir": verdicts_dir, "items_dir": items_dir,
            "reused": reused, "lite": lite, "agent": agent, "missing_fields": missing,
            "counts": {"reused": len(reused), "lite": len(lite), "agent": len(agent),
                       "missing_fields": len(missing)},
            "wiped": wiped, "warnings": warnings}, 0


def _prepare_main(argv):
    positional, flags = [], {}
    i = 0
    while i < len(argv):
        if argv[i] in ("--verdicts-dir", "--fields"):
            if i + 1 >= len(argv):
                positional = None
                break
            flags[argv[i]] = argv[i + 1]
            i += 2
        else:
            positional.append(argv[i])
            i += 1
    if positional is None or len(positional) != 1 or "--verdicts-dir" not in flags:
        out, rc = {"ok": False, "error": "usage",
                   "detail": "prepare takes <checklist-iter-N.json> --verdicts-dir <dir> [--fields <file>]"}, 2
    else:
        try:
            out, rc = prepare(positional[0], flags["--verdicts-dir"], flags.get("--fields"))
        except Exception as e:
            sys.stderr.write(
                "normalize-verdicts.py: internal error — this is a helper defect:\n"
                + traceback.format_exc()
            )
            out, rc = {"bad_input": True, "error": "helper_internal_error",
                       "detail": f"{type(e).__name__}: {e}"[:200]}, 0
    print(json.dumps(out, indent=2))
    return rc


def _parse_build_args(argv):
    """Return ``(positional, flags)`` or ``(None, error-text)``."""
    positional, flags = [], {}
    i = 0
    while i < len(argv):
        if argv[i] in BUILD_FLAGS:
            if i + 1 >= len(argv):
                return None, f"{argv[i]} needs a value"
            flags[argv[i]] = argv[i + 1]
            i += 2
        else:
            positional.append(argv[i])
            i += 1
    if flags and len(flags) != len(BUILD_FLAGS):
        return None, "build mode needs all of " + " ".join(BUILD_FLAGS)
    return positional, flags


def main(argv=None):
    _force_utf8_streams()
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--help" in argv or "-h" in argv:
        # A help flag anywhere in argv prints usage and does nothing else — no
        # pairs-file read, no JSON verdict. rc 0.
        print("usage: normalize-verdicts.py <pairs-file>")
        print("       normalize-verdicts.py checklist carry|raw|finalize <work-dir> ...")
        print("       normalize-verdicts.py prepare <checklist-iter-N.json> --verdicts-dir <dir> [--fields <file>]")
        print("       normalize-verdicts.py <inputs-file> " + " ".join(f"{f} <path>" for f in BUILD_FLAGS))
        return 0
    if argv and argv[0] == "checklist":
        return _checklist_main(argv[1:])
    if argv and argv[0] == "prepare":
        return _prepare_main(argv[1:])
    positional, flags = _parse_build_args(argv)
    if positional is None or (flags and not positional):
        # stdout too, for the same reason as the no-argument arm below.
        detail = flags if positional is None else "build mode needs an inputs-file path"
        print(json.dumps({"bad_input": True, "error": "bad_build_arguments",
                          "detail": detail}, indent=2))
        sys.stderr.write(f"normalize-verdicts.py: {detail}\n")
        return 2
    if flags:
        try:
            out = build(positional[0], flags["--checklist"], flags["--verdicts-dir"],
                        flags["--out"])
        except Exception as e:
            sys.stderr.write(
                "normalize-verdicts.py: internal error — this is a helper defect:\n"
                + traceback.format_exc()
            )
            out = {"bad_input": True, "error": "helper_internal_error",
                   "detail": f"{type(e).__name__}: {e}"[:200]}
        print(json.dumps(out, indent=2))
        return 0
    if not argv:
        # Emit on stdout as well as stderr, for the same reason as the version guard
        # above: byte-empty stdout is read as a matcher denial and misattributes a
        # malformed invocation to a missing grant. rc stays 2 (the documented contract).
        print(json.dumps({"bad_input": True, "error": "no_pairs_file_argument",
                          "detail": "a pairs-file path argument is required"}, indent=2))
        sys.stderr.write("normalize-verdicts.py: a pairs-file path argument is required\n")
        return 2
    try:
        out = run(argv[0])
    except Exception as e:
        sys.stderr.write(
            "normalize-verdicts.py: internal error — this is a helper defect:\n"
            + traceback.format_exc()
        )
        out = {"bad_input": True, "error": "helper_internal_error",
               "detail": f"{type(e).__name__}: {e}"[:200]}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
