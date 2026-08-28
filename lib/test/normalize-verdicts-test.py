#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Executable unit tests for scripts/normalize-verdicts.py (issue #556, T-1/T-3/T-6).

Drives the REAL helper CLI over the hand-built fixture matrix under
lib/test/fixtures/normalize-verdicts/ and asserts the parsed stored verdict,
raw_verdict/normalized fields, defect classification, needs_retry membership, and
the two counts per arm. Exits non-zero on any failure so lib/test/run.sh can gate
on it. Also drives the T-3 planted-defect positive control (a helper mutation that
drops conjunct 2 must turn the false-authored-comment arm RED)."""
import json
import os
import re as _re
import subprocess
import sys
import tempfile

os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
H = "scripts/normalize-verdicts.py"
D = "lib/test/fixtures/normalize-verdicts"
def run(f):
    r = subprocess.run(["python3", H, os.path.join(D, f)], capture_output=True, text=True)
    return json.loads(r.stdout), r.returncode
def res0(o): return o["results"][0]
fails = []
def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL"), name, detail if not cond else "")
    if not cond:
        fails.append(name)

o,_ = run("norm-basic.json")
r=res0(o)
check("norm-basic normalized", r["normalized"] and r["verdict"]=="PASS" and r["raw_verdict"]=="FAIL")
check("norm-basic count", o["counts"]["normalized_count"]==1)
check("norm-basic evidence prefix", r["evidence"].startswith("NORMALIZED (wording-only): "))

o,_=run("conj1-lite-fail.json")
r=res0(o)
check("conj1 lite not normalized", not r["normalized"] and r["verdict"]=="FAIL")

o,_=run("conj2-source-authored.json")
r=res0(o)
check("conj2 source_authored not normalized", not r["normalized"] and r["verdict"]=="FAIL")
check("conj2 not field-defect-fail", o["counts"]["field_defect_fail_count"]==0)

o,_=run("conj4-string-true.json")
r=res0(o)
check("conj4 string-true not normalized", not r["normalized"] and r["verdict"]=="FAIL")
check("conj4 string-true is field-defect-fail", o["counts"]["field_defect_fail_count"]==1, str(r))

# issue #2099 — the reported consumer shape: a well-typed FAIL asserting the code is
# correct (inaccuracy_scope generated_claim_text) while leaving property_proven false.
# Previously terminal (needs_retry empty); now draws exactly one pinned auxiliary re-ask.
o,_=run("conj4-property-false.json")
r=res0(o)
check("contradiction: not normalized, stays FAIL", not r["normalized"] and r["verdict"]=="FAIL", str(r))
check("contradiction: NOT a field-defect fail", o["counts"]["field_defect_fail_count"]==0, str(o["counts"]))
check("contradiction: fires one auxiliary re-ask naming the contradiction",
      len(o["needs_retry"])==1 and o["needs_retry"][0]["kind"]=="auxiliary"
      and "contradiction" in o["needs_retry"][0]["defect"], str(o["needs_retry"]))
check("contradiction: defect_class auxiliary, ineligible names the contradiction",
      r["defect_class"]=="auxiliary" and "contradiction" in (r["normalization_ineligible"] or ""), str(r))

# A resolving re-ask (pinned FAIL, property true + generated_claim_text) normalizes exactly
# as a first-response wording-only FAIL does.
o,_=run("contradiction-resolved.json")
r=res0(o)
check("contradiction resolved: normalizes wording-only",
      r["normalized"] and r["verdict"]=="PASS" and r["raw_verdict"]=="FAIL"
      and r["evidence"].startswith("NORMALIZED (wording-only): "), str(r))
check("contradiction resolved: counted normalized", o["counts"]["normalized_count"]==1, str(o["counts"]))
check("contradiction resolved: not re-dispatched again", o["needs_retry"]==[], str(o["needs_retry"]))

# A persisting contradiction (pinned FAIL, re-ask STILL property false + generated_claim_text)
# leaves the raw FAIL standing, names the contradiction, and is never re-dispatched again.
o,_=run("contradiction-persisting.json")
r=res0(o)
check("contradiction persisting: stays FAIL",
      r["raw_verdict"]=="FAIL" and r["verdict"]=="FAIL" and r["normalized"] is False, str(r))
check("contradiction persisting: ineligible names the contradiction",
      "contradiction" in (r["normalization_ineligible"] or ""), str(r["normalization_ineligible"]))
check("contradiction persisting: stamps the contradiction defect on the pinned arm",
      "contradiction" in (r["defect"] or "") and r["defect_class"] == "auxiliary", str(r))
check("contradiction persisting: fires at most once (no second dispatch)",
      o["needs_retry"]==[], str(o["needs_retry"]))

# Each of the four OTHER real-value blockers suppresses the contradiction re-ask and keeps
# today's terminal behavior — no auxiliary contradiction re-ask fires.
for _fx,_lbl in [("contradiction-suppressed-not-agent.json", "not-agent"),
                 ("contradiction-suppressed-issue-acceptance.json", "issue_acceptance"),
                 ("contradiction-suppressed-source-authored.json", "source_authored"),
                 ("contradiction-suppressed-trusted-unreadable.json", "trusted-unreadable")]:
    o,_=run(_fx)
    r=res0(o)
    check("contradiction suppressed (" + _lbl + "): not normalized",
          not r["normalized"] and r["verdict"]=="FAIL", str(r))
    check("contradiction suppressed (" + _lbl + "): no auxiliary re-ask at all",
          not any(x["kind"] == "auxiliary" for x in o["needs_retry"]), str(o["needs_retry"]))

o,_=run("conj5-scope-source.json")
r=res0(o)
check("conj5 scope-source not normalized", not r["normalized"])
check("conj5 NOT field-defect-fail", o["counts"]["field_defect_fail_count"]==0)

o,_=run("defect-missing-fence.json")
r=res0(o)
check("missing-fence defect", r["defect"]=="missing_fence" and r["defect_class"]=="verdict")
check("missing-fence needs_retry verdict", o["needs_retry"] and o["needs_retry"][0]["kind"]=="verdict")

o,_=run("tolerance-fenceless-single.json")
r=res0(o)
check("tolerance fenceless single normalized", r["normalized"], str(r))

o,_=run("defect-unparseable-json.json")
r=res0(o)
check("unparseable_json defect", r["defect"]=="unparseable_json")

o,_=run("defect-missing-verdict-field.json")
r=res0(o)
check("missing_verdict_field", r["defect"]=="missing_verdict_field")

o,_=run("defect-non-enum-verdict.json")
r=res0(o)
check("non_enum_verdict", r["defect"]=="non_enum_verdict")

o,_=run("defect-id-mismatch.json")
r=res0(o)
check("id_mismatch", r["defect"]=="id_mismatch")

o,_=run("lastfence.json")
r=res0(o)
check("lastfence uses last (FAIL->normalized)", r["raw_verdict"]=="FAIL" and r["normalized"], str(r))

o,_=run("aux-property-absent.json")
r=res0(o)
check("aux property absent -> auxiliary defect", r["defect_class"]=="auxiliary")
check("aux property absent needs_retry auxiliary", o["needs_retry"] and o["needs_retry"][0]["kind"]=="auxiliary")
check("aux property absent field-defect-fail", o["counts"]["field_defect_fail_count"]==1)

o,_=run("aux-scope-unknown.json")
r=res0(o)
check("aux scope unknown -> auxiliary defect", r["defect_class"]=="auxiliary")

o,_=run("aux-pass-no-retry.json")
r=res0(o)
check("aux PASS defect no retry", not o["needs_retry"], str(o["needs_retry"]))
check("aux PASS stays PASS", r["verdict"]=="PASS")

o,_=run("vfile-channel.json")
r=res0(o)
check("vfile reads file channel", r["source"]=="file", str(r))
check("vfile normalized from file bytes", r["normalized"] and r["file_checked"]=="b.py", str(r))

o,_=run("field-defect-fail.json")
r=res0(o)
check("field-defect-fail not normalized", not r["normalized"])
check("field-defect-fail counted", o["counts"]["field_defect_fail_count"]==1, str(r))
check("field-defect-fail retry auxiliary? no (verdict ok, provenance absent)", not o["needs_retry"], str(o["needs_retry"]))

o,_=run("pinned-verdict.json")
r=res0(o)
check("pinned raw is FAIL not response PASS", r["raw_verdict"]=="FAIL", str(r))
check("pinned stored stays FAIL (property false)", r["verdict"]=="FAIL", str(r))

o,_=run("no-verdict-channel.json")
r=res0(o)
check("no-verdict defect", r["defect"]=="no_verdict", str(r))

o,_=run("empty-pairs.json")
check("empty-pairs results empty", o.get("results")==[] and "bad_input" not in o)

o,_=run("bad-empty.json")
check("bad-empty bad_input", o.get("bad_input") is True and o["error"]=="pairs_file_empty")

o,_=run("bad-unparseable.json")
check("bad-unparseable bad_input", o.get("bad_input") is True and o["error"]=="pairs_file_unparseable")

o,_=run("bad-wrong-shape.json")
check("bad-wrong-shape bad_input", o.get("bad_input") is True and o["error"]=="pairs_file_wrong_shape")

o,_=run("bad-prose-reflection.txt")
check("prose reflection bad_input", o.get("bad_input") is True)

# AC11 — a source_authored item whose authored assertion is false keeps FAIL and
# stays normalization-ineligible (conjunct 2 fails). This isolates conjunct 2 so
# the T-3 mutation control below can prove the guard bites.
o,_=run("ac11-only-conj2.json")
r=res0(o)
check("AC11 source_authored not normalized", not r["normalized"] and r["verdict"]=="FAIL", str(r))

# ── #556 Phase 3 review-finding regressions (code-reviewer / silent-failure / pr-test) ──
# code-reviewer (Important): a compliant pinned field-completion re-ask returning ONLY the
# two aux fields (no verdict) applies the pinned FAIL and completes the fields -> normalizes,
# instead of being mis-classified as a missing_verdict_field verdict defect.
o,rc=run("pinned-aux-only.json")
r=res0(o)
check("pinned aux-only re-ask normalizes (not missing_verdict_field)",
      r["normalized"] and r["verdict"]=="PASS" and r["raw_verdict"]=="FAIL", str(r))
check("pinned aux-only re-ask not re-dispatched", not o["needs_retry"], str(o["needs_retry"]))

# silent-failure (HIGH) / pr-test: a non-dict pair element is an observable malformed_pair
# verdict defect, never a silent drop; the sibling valid pair still processes.
o,rc=run("malformed-pair.json")
check("malformed pair emits a result (not silently dropped)", len(o["results"])==2, str(len(o["results"])))
check("malformed pair -> malformed_pair verdict defect", any(x["defect"]=="malformed_pair" for x in o["results"]))
check("malformed pair enters needs_retry", any(x.get("defect")=="malformed_pair" for x in o["needs_retry"]))
check("sibling valid pair still normalizes", any(x["normalized"] for x in o["results"]))

# pr-test (sev 6): multi-pair aggregation across N>1 pairs.
o,rc=run("multi-pair.json")
check("multi-pair: 3 results", len(o["results"])==3)
check("multi-pair: normalized_count 1", o["counts"]["normalized_count"]==1, str(o["counts"]))
check("multi-pair: field_defect_fail_count 2", o["counts"]["field_defect_fail_count"]==2, str(o["counts"]))
check("multi-pair: one aux needs_retry (VC-C)",
      bool([x for x in o["needs_retry"] if x["kind"]=="auxiliary" and x["id"]=="VC-C"]), str(o["needs_retry"]))

# pr-test (sev 4): file-absent + present response_text reads the fallback channel.
o,rc=run("absent-file-with-response.json")
r=res0(o)
check("absent file falls back to response_text channel", r["source"]=="response_text" and r["normalized"], str(r))

# pr-test/code-reviewer: wire the previously-orphan v2b pre-schema fixture (combined aux defect).
o,rc=run("v2b-preschema-cvc17.json")
r=res0(o)
check("v2b pre-schema: combined aux defect string", r["defect"]=="aux:property_proven,inaccuracy_scope", str(r["defect"]))
check("v2b pre-schema: field_defect_fail_count 1", o["counts"]["field_defect_fail_count"]==1)

# pr-test (sev 3): id_mismatch no-fire when the item carries no id (absent-operand guard).
o,rc=run("id-nofire-item-noid.json")
r=res0(o)
check("id_mismatch no-fire when item has no id", r["defect"] is None and r["normalized"], str(r))

# pr-test (sev 3): rc contract — a normal run exits 0; argv-empty exits rc 2.
o,rc=run("norm-basic.json")
check("normal run exits rc 0", rc==0, str(rc))
_rc = subprocess.run(["python3", H], capture_output=True, text=True).returncode
check("argv-empty exits rc 2", _rc==2, str(_rc))

# T-3 planted-defect positive control: a helper mutation dropping conjunct 2 (the
# claim_provenance == generated_paraphrase check) must turn the AC11 arm RED — i.e.
# the mutant WRONGLY normalizes the source_authored item. Proves the guard, not the
# line's mere presence (recorded as mutation evidence, not attestation).
_src = open("scripts/normalize-verdicts.py", encoding="utf-8").read()
_mut = _re.sub(r'if provenance != "generated_paraphrase":',
               'if False:  # T-3 mutation: drop conjunct 2', _src, count=1)
_ctrl_ok = _mut != _src
with tempfile.TemporaryDirectory() as _td:
    _mp = os.path.join(_td, "mutant.py")
    open(_mp, "w", encoding="utf-8").write(_mut)
    _r = subprocess.run(["python3", _mp, os.path.join(D, "ac11-only-conj2.json")],
                        capture_output=True, text=True)
    _mo = json.loads(_r.stdout)
    _mut_normalizes = _mo["results"][0]["normalized"] is True
check("T-3 mutation control: conjunct-2 drop applied", _ctrl_ok)
check("T-3 mutation control: mutant WRONGLY normalizes AC11 (guard bites)", _mut_normalizes, str(_mo["results"][0]))

# --- PR #607 review rounds: the abandoned-trusted-channel contract ---------------
# The named nonce file EXISTS but cannot be read, so the verdict bytes came off the
# untrusted fallback. Previously recorded ONLY as a soft `source` string that no
# consumer reads. Now stamped into defect/defect_class/needs_retry — the fields Phase
# 2.2 actually consumes — in EVERY verdict direction.
o,rc=run("vfile-unreadable-downgrade.json")
r=res0(o)
check("unreadable trusted file -> observable downgrade source",
      r["source"]=="response_text_file_unreadable", str(r["source"]))
check("unreadable trusted file -> FAIL does NOT normalize (fail-open closed)",
      r["verdict"]=="FAIL" and r["normalized"] is False, str(r))
check("unreadable trusted file -> real-value blocker, not a field defect",
      r["normalization_ineligible"]=="trusted verdict file present but unreadable"
      and o["counts"]["field_defect_fail_count"]==0, str(r["normalization_ineligible"]))
check("unreadable trusted file -> channel defect stamped (FAIL direction)",
      r["defect"]=="trusted_file_unreadable" and r["defect_class"]=="channel", str(r))

# The PASS direction is the one that matters: a forged PASS is the payload the nonce
# binding exists to stop, so gating the signal on a raw FAIL left it silent.
o,rc=run("vfile-unreadable-pass.json")
r=res0(o)
check("unreadable trusted file -> a clean PASS is NOT silent",
      r["defect"]=="trusted_file_unreadable" and r["defect_class"]=="channel"
      and r["normalization_ineligible"]=="trusted verdict file present but unreadable",
      str(r))
check("unreadable trusted file -> PASS direction enters needs_retry",
      [x for x in o["needs_retry"] if x["kind"]=="channel"], str(o["needs_retry"]))

# Unreadable file AND no response_text: the resulting no_verdict must be discriminated
# from "the verifier produced nothing anywhere" — the engine's kind-`verdict` remedy is
# a re-dispatch, which cannot fix a filesystem fault.
o,rc=run("vfile-none-unreadable.json")
r=res0(o)
check("unreadable + no response_text -> discriminated no_verdict",
      r["defect"]=="no_verdict_trusted_file_unreadable", str(r["defect"]))
o,rc=run("vfile-pinned-none-unreadable.json")
r=res0(o)
check("pinned + none_file_unreadable reaches the blocker's second arm",
      r["source"]=="none_file_unreadable" and r["defect"]=="trusted_file_unreadable"
      and r["normalized"] is False, str(r))

# An embedded NUL in the LLM-transcribed verdict_path makes open() raise ValueError —
# NOT an OSError subclass. The read guard absorbs it into the observable downgrade;
# the containment arm in run() is the second line of defence, pinned separately below.
o,rc=run("vfile-nul-path.json")
check("embedded-NUL verdict_path does not abort the batch", rc==0 and len(o["results"])==2, str(rc))
check("embedded-NUL pair degrades to the observable downgrade",
      o["results"][0]["source"]=="response_text_file_unreadable", str(o["results"][0]["source"]))
check("embedded-NUL pair does not cost the sibling its verdict",
      o["results"][1]["id"]=="VC-SIB" and o["results"][1]["normalized"] is True, str(o["results"][1]))

# A pinned pair whose re-ask STILL carries a defective aux field: the defect is stamped,
# but the item is never re-dispatched again. Dropping the `not is_pinned` guard would
# re-introduce an unbounded re-ask loop undetected.
o,rc=run("pinned-aux-persisting.json")
r=res0(o)
check("pinned re-ask with persisting aux defect keeps the raw FAIL",
      r["raw_verdict"]=="FAIL" and r["verdict"]=="FAIL" and r["normalized"] is False, str(r))
check("pinned re-ask stamps the aux defect's own signal",
      r["defect"]=="aux:property_proven,inaccuracy_scope" and r["defect_class"]=="auxiliary",
      str(r["defect"]))
check("pinned re-ask fires at most once (no second dispatch)",
      o["needs_retry"]==[], str(o["needs_retry"]))

# The pairs_file_unreadable bad-input arm. A directory path is the portable
# unreadable-input shape (IsADirectoryError on POSIX, PermissionError on Windows —
# both OSError). rc 0 is part of the contract: the helper RAN.
_r = subprocess.run(["python3", H, D], capture_output=True, text=True)
_o = json.loads(_r.stdout)
check("pairs_file_unreadable bad-input arm", _r.returncode==0 and _o.get("bad_input") is True
      and _o.get("error")=="pairs_file_unreadable", str(_o.get("error")))

# A malformed invocation must never exit with byte-EMPTY stdout: empty stdout is what
# the engine's contract reads as a matcher denial, so the operator would be sent at the
# cloud grant keys for what is actually a bad argv.
_r = subprocess.run(["python3", H], capture_output=True, text=True)
check("argv-empty still prints a bad-input object on stdout (not silence)",
      _r.stdout.strip() != "" and json.loads(_r.stdout).get("error")=="no_pairs_file_argument",
      repr(_r.stdout[:80]))

# Containment-arm mutation control (T-3 idiom). No fixture can reach the arm — every
# operand in _process_pair is isinstance-guarded and open() is fully wrapped — so its
# guarded regression is proven by PLANTING the defect: remove ValueError from the read
# guard and the embedded-NUL pair detonates inside _process_pair. The arm must contain
# it (observable per-item defect + surviving sibling), not abort the batch. This is what
# makes the three embedded-NUL assertions above non-vacuous: each guard now has an
# assertion that goes RED under its own removal alone.
_mut2 = _re.sub(r'except \(OSError, UnicodeDecodeError, ValueError\):',
                'except (OSError, UnicodeDecodeError):', _src, count=1)
check("containment control: ValueError-drop mutation applied", _mut2 != _src)
with tempfile.TemporaryDirectory() as _td:
    _mp2 = os.path.join(_td, "mutant2.py")
    open(_mp2, "w", encoding="utf-8").write(_mut2)
    _r2 = subprocess.run(["python3", _mp2, os.path.join(D, "vfile-nul-path.json")],
                         capture_output=True, text=True)
    _mo2 = json.loads(_r2.stdout) if _r2.stdout.strip() else {}
check("containment control: mutant does not abort the batch",
      _r2.returncode==0 and len(_mo2.get("results", []))==2, str(_r2.returncode))
check("containment control: mutant stamps pair_processing_error as a HELPER defect",
      _mo2["results"][0]["defect"]=="pair_processing_error"
      and _mo2["results"][0]["defect_class"]=="helper_internal",
      str(_mo2.get("results", [{}])[0].get("defect")))
check("containment control: mutant still delivers the sibling's verdict",
      _mo2["results"][1]["id"]=="VC-SIB" and _mo2["results"][1]["normalized"] is True,
      str(_mo2["results"][1]))
check("containment control: helper defect is not routed to the verifier-retry channel",
      all(x["kind"]!="verdict" for x in _mo2["needs_retry"]), str(_mo2["needs_retry"]))
check("containment control: mutant writes a real traceback to stderr",
      "Traceback" in _r2.stderr and "helper defect" in _r2.stderr, repr(_r2.stderr[:120]))

# --- issue_acceptance is never normalization-eligible ----------------------------
o,_=run("category-issue-acceptance.json")
r=res0(o)
check("issue_acceptance FAIL is not normalized",
      not r["normalized"] and r["verdict"]=="FAIL" and r["raw_verdict"]=="FAIL", str(r))
check("issue_acceptance is not a field-defect fail", o["counts"]["field_defect_fail_count"]==0)
check("issue_acceptance normalized_count is 0", o["counts"]["normalized_count"]==0)

o,_=run("category-non-acceptance.json")
r=res0(o)
check("non-acceptance category still normalizes",
      r["normalized"] and r["verdict"]=="PASS" and r["raw_verdict"]=="FAIL", str(r))

# The guard belongs in real_blockers, not field_defect_blockers: an issue_acceptance
# item carrying an aux defect must stay off both the field-defect tally and the
# auxiliary re-ask, which a field_defect_blockers placement would silently restore.
o,_=run("category-issue-acceptance-aux-defect.json")
r=res0(o)
check("issue_acceptance + aux defect not normalized",
      not r["normalized"] and r["verdict"]=="FAIL" and r["raw_verdict"]=="FAIL", str(r))
check("issue_acceptance + aux defect is not a field-defect fail",
      o["counts"]["field_defect_fail_count"]==0, str(o["counts"]))
check("issue_acceptance + aux defect is not re-dispatched",
      not o["needs_retry"], str(o["needs_retry"]))
check("issue_acceptance + aux defect still stamps the auxiliary defect",
      r.get("defect")=="aux:property_proven" and r.get("defect_class")=="auxiliary", str(r))

print("\nFAILURES:", fails if fails else "NONE")
sys.exit(1 if fails else 0)
