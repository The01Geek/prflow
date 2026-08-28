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
                     "evidence", "file_checked", "source",
                     "defect", "defect_class",
                     "normalization_ineligible" }, ... ],
      "needs_retry": [ { "id", "kind": "verdict"|"auxiliary", "defect" }, ... ],
      "counts": { "normalized_count", "field_defect_fail_count" }
    }

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
verdict: the item keeps its raw verdict and is normalization-ineligible. An
auxiliary defect enters ``needs_retry`` with kind ``auxiliary`` for a
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
(the trusted binding was abandoned), distinct from the legitimate absent-file
fallback, which is not.

The five-conjunct normalization predicate (raw FAIL -> stored PASS) holds exactly
when ALL hold: (1) ``verification_mode == "agent"``; (2)
``claim_provenance == "generated_paraphrase"``; (3) raw verdict byte-exact
``FAIL``; (4) ``property_proven`` is JSON boolean ``true`` (a JSON string
``"true"`` does not qualify — a real type check); (5)
``inaccuracy_scope == "generated_claim_text"``. No malformed shape of any class
ever resolves to a stored PASS.

An item whose ``category`` is ``issue_acceptance`` is additionally never
normalization-eligible: such items satisfy conjuncts (1) and (2) structurally, so
only the verifier's own self-reported auxiliary fields would stand between a raw
FAIL on an acceptance criterion and a stored PASS.

Exit codes:
    0  Helper ran (results OR bad-input report printed).
    1  Unsupported Python (< 3.11).
    2  Bad arguments (no pairs-file path given).
"""

import json
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
        "devflow: Python 3.11+ required (found {}.{}.{}).\n".format(*sys.version_info[:3])
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

    An ABSENT file is the legitimate fallback and yields ``source == "response_text"``.
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
            pass  # file genuinely absent -> the legitimate silent fallback
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


def _process_pair(pair):
    """Return ``(result_dict, retry_entry_or_None, is_field_defect_fail)`` for one
    pair. ``is_field_defect_fail`` is decided here from the structured blocker
    lists (never re-derived from the rendered ``normalization_ineligible`` string)."""
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
    result["verdict"] = raw  # stored verdict defaults to raw; normalization may flip it
    result["evidence"] = evidence if isinstance(evidence, str) else None
    fc = obj.get("file_checked")
    result["file_checked"] = fc if isinstance(fc, str) else None

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
        # is the legitimate fallback and does not reach here.)
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

    # not normalized: record the ineligibility reason(s)
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

    results = []
    needs_retry = []
    field_defect_fail_count = 0
    for idx, pair in enumerate(payload["pairs"]):
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
            result, retry, is_field_defect_fail = _process_pair(pair)
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
            # lib/test/normalize-verdicts-test.py.
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


def main(argv=None):
    _force_utf8_streams()
    argv = list(sys.argv[1:] if argv is None else argv)
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
