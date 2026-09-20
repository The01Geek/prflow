#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Fail a cloud review run whose posted verdict lacks phase-execution evidence (issue #2075).

THE QUESTION IT ANSWERS. The `/prflow:review` engine is the merge-gating judge, but
nothing on the cloud tier checks that a run that posted a verdict actually executed its
phases — every live signal (progress ticks, tally lines, telemetry) is written by the
same agent being checked, so a run that skips its work and still posts a verdict ends
green. This gate compares the posted verdict against the durable work products the
checklist phases leave in the run-scoped directory by doing their work (issue #21): the
final checklist Phase 1 hands to Phase 2 (`checklist-iter-<N>.json`) and the combined
verification results Phase 2 hands to Phase 4 (`verification-iter-<N>.json`), each a JSON
array. This mirrors how the implement/reception tier proves completion — validating a
producer-owned artifact (check-completion-evidence.py's flight record), not a discretionary
bookkeeping line an agent could omit while doing the work correctly. Two legitimate
no-checklist arms produce no such artifact and prove themselves through the phase log
instead: a generator double-failure record and a Phase 0.3.6 hit record.

WHAT IT READS, AND WHY EACH INPUT IS SHAPED THIS WAY.
  --pre-inventory FILE    a pre-engine snapshot {"run_roots": [...], "review_ids": [...]}
                          the workflow step records immediately before the engine step.
                          Run roots and reviews that appear DURING the engine step are
                          attributed to this run by set-difference — no run key from the
                          engine, no clock comparison (the engine cannot expand an env var
                          under the cloud matcher, so it stamps no run identity).
  --post-tree-root DIR    the repo root whose `.prflow/tmp/review/` tree is re-listed now.
  --reviews-payload FILE  the PR's reviews-API JSON array, fetched post-engine. The
                          reviewed head is read from THIS run's verdict marker's own
                          `head=`, so no runner-supplied head is needed or trusted.
  --base-ref REF          the PR base ref for the diff-classification recompute (may be
                          empty; then origin/HEAD is used, as workpad.py does).
  --repo-root DIR         the repo root for the classification recompute.
  --reviewer-login LOGIN  the run's own reviewer identity (`.user.login`); a human's
                          review is never mistaken for the run's own.
  --vendored-engine-root  the checked-out review engine root; if its phase files do not
                          yet carry the durable-artifact write instruction, an older
                          vendored engine is assumed and the check is UNESTABLISHED rather
                          than a false failure.

CLASSIFICATION IS NOT RE-COPIED (AC4). The "does this diff owe the checklist phases?"
decision is `scripts/workpad.py`'s own `_review_coverage_profile_disproof` over
`_recompute_diff_facts`, imported here so the ceilings and config-only extension set live
in one implementation. An unloadable workpad.py routes to the unestablished arm, never a crash.

OUTPUT CONTRACT. One machine-readable verdict token as stdout line 1, from the closed
vocabulary below, followed by human-readable detail lines (the durable-comment body). Once
argument parsing has succeeded it ALWAYS exits 0 — the invoking workflow step decides the
job's pass/fail from the token, so no decision-path fault ends the step before the
comment/dismissal/flip actions run. Argument parsing itself is outside that guarantee:
argparse exits 2 on a malformed or missing required argument, which is a wiring bug in the
caller, and the step's `set -uo pipefail` (no `-e`) leaves the token empty, routing to the
step's unrecognized-output warning rather than a silent green.

  pass <arm>                 a verdict was posted and its required evidence is present, OR
                             no checklist was owed. <arm> is one of legitimate-skip,
                             generator-failure-skip, blocker-recheck-hit, checklist-phases-ran.
  no-verdict                 no marker-bearing verdict was posted by this run for the head.
  fail missing=<tokens> review_id=<id> review_state=<state>
                             a verdict was posted, the checklist was owed, and the run root
                             attributed to this run holds no durable checklist/verification
                             artifact pair (and no special record) proving it ran. The
                             <tokens> are space-free (checklist-artifact, verification-
                             artifact, run-root), joined by commas.
  unestablished <reason>     an evidence state the gate could not settle — reported neither
                             as a pass nor as a failure.

UNKNOWN IS NOT ZERO. A present-but-malformed artifact, a malformed phase log, an unreadable
run root, an unresolvable diff range, an unparseable reviews payload, an ambiguous run-root
delta, or an older vendored engine are each UNESTABLISHED — never a pass and never laundered
into a fail. Only what a hollow run positively leaves behind — a posted verdict, a checklist
owed, and a run root holding neither the durable artifact pair nor a special record (or no
run root at all) — is the fail arm.
"""
import argparse
import glob
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

# The two special records that legitimately stand in for the checklist phases. These are
# still carried on the run-scoped phase log by their producer phases (Phase 1.3's generator
# double-failure arm and Phase 0.3.6's blocker-recheck hit), and are consulted only when the
# durable artifact pair is absent (issue #21).
_GENERATOR_FAILURE_RECORD = 'checklist-skip reason=failure'
_BLOCKER_RECHECK_HIT_RECORD = 'blocker-recheck-hit re-verdict=posted'
# The durable Phase 1 / Phase 2 work-product artifacts (issue #21): the final post-dedup,
# post-cap checklist array Phase 1 hands to Phase 2, and the combined normalized results
# array Phase 2 hands to Phase 4 — each iteration-scoped so /prflow:review-and-fix's
# re-entries write one per iteration and the gate accepts any iteration's pair.
_CHECKLIST_ARTIFACT_RE = re.compile(r'\Achecklist-iter-(?P<n>\d+)\.json\Z')
_VERIFICATION_ARTIFACT_RE = re.compile(r'\Averification-iter-(?P<n>\d+)\.json\Z')
# The literals the artifact-write instructions embed in the phase files that carry them,
# used to detect an engine root that predates this change (an older vendored engine writes
# no durable artifact at all). The old `phase-entry phase=` literal is deliberately NOT the
# sentinel: an older engine still carries it and would be misdetected as current and falsely
# failed.
_PHASE1_ARTIFACT_INSTRUCTION_SENTINEL = 'checklist-iter-'
_PHASE2_ARTIFACT_INSTRUCTION_SENTINEL = 'verification-iter-'

# A valid phase-entry line is `phase-entry phase=<id>` where <id> is a single non-space
# token — so a valid-falsy `phase=`, a truncated line, and an `extra=` field all fail to
# match and grade the log malformed. The id is NOT checked against a fixed vocabulary. A
# transitional log of phase-entry lines is no longer evidence (issue #21), but it stays
# valid grammar so it routes to the artifact-based fail arm rather than unestablished — no
# `_VALID_PHASE_IDS` copy of SKILL.md's routing table.
_PHASE_ENTRY_RE = re.compile(r'\Aphase-entry phase=(?P<id>\S+)\Z')
_VERDICT_MARKER_RE = re.compile(
    r'\A<!-- prflow:review-verdict head=(?P<head>[0-9a-fA-F]{40}) '
    r'verdict=(?P<verdict>APPROVE|REJECT) -->')

_REVIEW_SUBDIR = os.path.join('.prflow', 'tmp', 'review')
# Per-item nonce verifier files, verdicts/iter-<N>/<item-id>-<nonce>.json (issue #193,
# phase-2-verification.md §2.2). The coverage check must never read verification-iter-<N>.json
# instead: its no-file timeout/response fallback would then satisfy the requirement.
_VERDICTS_SUBDIR = 'verdicts'
# The subagent a checklist agent-item is verified by; the transcript backstop counts actual
# dispatch events naming it (issue #193).
_VERIFIER_SUBAGENT = 'prflow:checklist-verifier'
# The tool a harness records a subagent dispatch under: `Agent` on the current cloud harness,
# `Task` on older ones. Dropping either zeroes the count on that harness's transcripts.
_DISPATCH_TOOL_NAMES = frozenset({'Agent', 'Task'})
# Written by Phase 0.3.6 BEFORE Phase 4 posting (issue #193); accepting only the legacy
# post-verdict record would leave the producer's pre-post grade no blocker-recheck evidence.
_BLOCKER_RECHECK_VERIFY_RECORD = 'blocker-recheck-hit verification=complete'


def _detail(*parts):
    """One human-readable detail line assembled from comma-separated fragments — a call,
    not adjacent-literal concatenation, so the long messages below carry no implicit
    string concatenation inside a list literal."""
    return [''.join(parts)]


def _load_sibling(filename, module_name):
    """Import a sibling script from this file's own directory (install-relative, so a
    vendored consumer checkout resolves it with no config or PATH assumption). Returns
    (module, None) or (None, reason) — any import fault routes to the unestablished arm,
    never a crash; the reason names the caught fault so a persistent failure is diagnosable
    in the annotation rather than an opaque, indefinitely-tolerated warning."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return None, f'no import spec for {filename}'
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module, None
    except Exception as e:  # any import fault is the unestablished arm, never a crash
        return None, f'{type(e).__name__}: {e}'


def _load_workpad():
    """Import scripts/workpad.py so its classification lives in one place (AC4)."""
    return _load_sibling('workpad.py', 'review_gate_workpad')


def _read_json(path):
    """(obj, None) on success; (None, reason) when the path is unreadable or unparseable.
    `-` reads stdin."""
    try:
        if path == '-':
            text = sys.stdin.read()
        else:
            with open(path, encoding='utf-8') as fh:
                text = fh.read()
    except OSError:
        return None, 'unreadable'
    try:
        return json.loads(text), None
    except (ValueError, UnicodeError):
        return None, 'unparseable'


def _list_run_roots(post_tree_root):
    """The set of run-root directory names under `<post_tree_root>/.prflow/tmp/review/`,
    one level deep — a run root is `.prflow/tmp/review/<slug>/<run-id>`, so the attributed
    unit is the `<slug>/<run-id>` pair. Returns (set, None) or (None, reason) when the
    tree exists but cannot be read (an I/O or permission failure — distinct from an absent
    tree, which is an empty set, not an error)."""
    base = os.path.join(post_tree_root, _REVIEW_SUBDIR)
    if not os.path.isdir(base):
        return set(), None
    roots = set()
    try:
        for slug in os.listdir(base):
            slug_dir = os.path.join(base, slug)
            if not os.path.isdir(slug_dir):
                continue
            for run_id in os.listdir(slug_dir):
                if os.path.isdir(os.path.join(slug_dir, run_id)):
                    roots.add(slug + '/' + run_id)
    except OSError:
        return None, 'run-root-tree-unreadable'
    return roots, None


def _classify_own_reviews(reviews, reviewer_login):
    """From a reviews-API array, split this-identity reviews into those carrying the
    line-1 producer verdict marker (the rule scripts/classify-head-reviews.sh reads) and
    those without it. A marked review carries the reviewed tree in its own marker `head=`
    (never a runner-supplied head), so the gate reads that as the reviewed head — which is
    what makes a /prflow:review-and-fix verdict identified against the head IT recorded,
    not the PR's current head. Returns {'marked': [(id, state, marker_head), ...],
    'unmarked': [id, ...]}, both scoped to `reviewer_login`; a non-string body is unmarked."""
    marked = []
    unmarked = []
    for review in reviews:
        if not isinstance(review, dict):
            continue
        user = review.get('user')
        login = user.get('login') if isinstance(user, dict) else None
        if login != reviewer_login:
            continue
        rid = review.get('id')
        state = review.get('state')
        body = review.get('body')
        line1 = body.split('\n', 1)[0] if isinstance(body, str) else ''
        m = _VERDICT_MARKER_RE.match(line1)
        if m:
            marked.append((rid, state, m.group('head').lower()))
        else:
            unmarked.append(rid)
    return {'marked': marked, 'unmarked': unmarked}


def _read_phase_log(run_root_dir):
    """Read `<run_root_dir>/phase-log`. Returns one of:
      ('missing', None)        the file does not exist (run root present, no log)
      ('unreadable', None)     the file exists but read raised (I/O/permission)
      ('content', text)        the file's text (possibly empty)."""
    path = os.path.join(run_root_dir, 'phase-log')
    try:
        with open(path, encoding='utf-8') as fh:
            return 'content', fh.read()
    except FileNotFoundError:
        return 'missing', None
    except OSError:
        return 'unreadable', None


def _grade_phase_log(text):
    """Grade a present phase log's text — consulted (issue #21) only for the two special
    no-work-product records, since a checklist-owing run's evidence now lives in its durable
    artifacts. Returns one of:
      ('malformed', None)                 any non-blank line is outside the closed grammar
      ('record', 'blocker-recheck-hit')   the 0.3.6 hit record is present
      ('record', 'generator-failure')     the generator double-failure record is present
      ('none', None)                      well-formed but carrying no special record (an
                                          empty log, or a transitional log of phase-entry
                                          lines only — no longer evidence on its own)
    The grammar is total over any input and never crashes: an unrecognized non-blank line
    (wrong-typed content, a truncated line, a valid-falsy `phase=`, unknown extra text)
    makes the whole log malformed → unestablished. A transitional `phase-entry phase=<id>`
    line stays valid grammar (not malformed) so such a log routes to the artifact-based fail
    arm rather than unestablished. Blank lines (a trailing newline's empty final element) are
    skipped."""
    seen = set()
    for line in text.split('\n'):
        if line == '':
            continue
        if line in (_GENERATOR_FAILURE_RECORD, _BLOCKER_RECHECK_HIT_RECORD,
                    _BLOCKER_RECHECK_VERIFY_RECORD):
            seen.add(line)
            continue
        if _PHASE_ENTRY_RE.match(line):
            continue
        return 'malformed', None
    if _BLOCKER_RECHECK_HIT_RECORD in seen or _BLOCKER_RECHECK_VERIFY_RECORD in seen:
        return 'record', 'blocker-recheck-hit'
    if _GENERATOR_FAILURE_RECORD in seen:
        return 'record', 'generator-failure'
    return 'none', None


def _file_contains(path, sentinel):
    """Whether `path` exists, is readable, and contains `sentinel`. False on any OSError or
    on non-UTF-8 bytes (`fh.read()` raises UnicodeDecodeError, a ValueError not caught by an
    OSError handler), so an absent/unreadable/undecodable file reads as not-carrying it."""
    try:
        with open(path, encoding='utf-8') as fh:
            return sentinel in fh.read()
    except (OSError, UnicodeError):
        return False


def _engine_root_has_instruction(vendored_engine_root):
    """Whether the checked-out engine root carries the durable-artifact write instruction —
    read from the phase files that carry it (`phases/phase-1-checklist.md` and
    `phases/phase-2-verification.md`), NOT SKILL.md, so the sentinel lives beside the
    instruction with no coupled mirror (AC6). True only when BOTH phase files carry their
    own artifact sentinel; an engine whose phase files predate the artifact-writing phases
    (or are absent/unreadable) routes to unestablished rather than a false failure."""
    phases = os.path.join(vendored_engine_root, 'phases')
    return (_file_contains(os.path.join(phases, 'phase-1-checklist.md'),
                           _PHASE1_ARTIFACT_INSTRUCTION_SENTINEL)
            and _file_contains(os.path.join(phases, 'phase-2-verification.md'),
                               _PHASE2_ARTIFACT_INSTRUCTION_SENTINEL))


def _read_json_array_value(path):
    """Grade one durable artifact file, returning (status, value). status is:
      'array'      a parseable JSON array (an empty array is valid); value is the list
      'missing'    the file does not exist; value is None
      'malformed'  present but unreadable, unparseable, or not a JSON array; value is None
    The missing-vs-malformed distinction is why this is not this module's `_read_json`
    (which collapses FileNotFound with other OSErrors): a genuinely absent artifact is the
    fail arm, a present-but-corrupt one the unestablished arm. Non-UTF-8 bytes make
    `fh.read()` raise UnicodeDecodeError (a ValueError, not an OSError), so the read guard
    catches UnicodeError too, and a pathologically deep array makes `json.loads` raise
    RecursionError — every corrupt shape grades malformed rather than crashing the gate into
    the workflow's fail-open green arm. Returning the parsed value lets the nonce-coverage
    check read a qualifying iteration's checklist items without a second file read."""
    try:
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
    except FileNotFoundError:
        return 'missing', None
    except (OSError, UnicodeError):
        return 'malformed', None
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):
        return 'malformed', None
    if isinstance(value, list):
        return 'array', value
    return 'malformed', None


def _effective_verification_mode(item):
    """The effective Phase 2 verification mode of a checklist item (issue #193), matching
    phase-2-verification.md §2.0/§2.1a: 'agent' unless the item declares
    `verification_mode: "lite"` AND carries a well-formed `lite_probe`. A missing or
    unrecognized mode defaults to agent, and a lite item with a malformed `lite_probe`
    promotes to agent — the fail-closed direction, requiring a nonce file rather than
    waiving one."""
    if not isinstance(item, dict) or item.get('verification_mode') != 'lite':
        return 'agent'
    probe = item.get('lite_probe')
    if (isinstance(probe, dict)
            and probe.get('kind') in ('string_present', 'string_absent')
            and isinstance(probe.get('string'), str)
            and isinstance(probe.get('file'), str)):
        return 'lite'
    return 'agent'


def _nonce_file_present(run_root_dir, n, item_id):
    """Whether a `verdicts/iter-<n>/<item-id>-*.json` verifier file exists (issue #193). The
    existence of the nonce FILE is the requirement — no verification array is read — so a
    no-file timeout/response fallback cannot satisfy it."""
    return _nonce_file_in_dir(
        run_root_dir, os.path.join(_VERDICTS_SUBDIR, f'iter-{n}'), item_id)


def _nonce_items_satisfied(checklist_items, resolve_item):
    """Shared agent-item nonce-coverage skeleton (issue #516 cleanup): walk the effective
    agent-mode checklist items — extracting each id with the `unidentified-agent-item`
    fallback — and mark an item missing when `resolve_item(item_id)` is falsy. `resolve_item`
    is the per-caller verifier-file presence predicate (plain iteration vs entry-scoped +
    reuse), the only axis on which the two nonce checks differ. Returns
    (satisfied, [missing-item-id, ...]); a non-list checklist fails closed."""
    if not isinstance(checklist_items, list):
        return False, ['checklist-not-an-array']
    missing = []
    for item in checklist_items:
        if _effective_verification_mode(item) != 'agent':
            continue
        item_id = item.get('id') if isinstance(item, dict) else None
        if not isinstance(item_id, str) or not item_id:
            missing.append('unidentified-agent-item')
            continue
        if not resolve_item(item_id):
            missing.append(item_id)
    return (not missing), missing


def _iteration_nonce_satisfied(run_root_dir, n, checklist_items):
    """Whether iteration `n`'s effective agent-mode items each have a matching
    `verdicts/iter-<n>/<item-id>-*.json` verifier file present (issue #193). Returns
    (satisfied, [missing-item-id, ...]). Lite items are exempt, as is a lite-only or empty
    checklist. A checklist that is not a list, or an agent item with no usable id, fails
    closed."""
    return _nonce_items_satisfied(
        checklist_items,
        lambda item_id: _nonce_file_present(run_root_dir, n, item_id))


def _scan_artifacts(run_root_dir):
    """Grade the iteration-scoped durable work-product artifacts in a run root. Returns
    {'checklist': {n: status, ...}, 'verification': {n: status, ...},
    'checklist_values': {n: [items] | None, ...}} where each status is 'array' or
    'malformed' (an absent iteration simply has no key) and `checklist_values` holds the
    parsed checklist list for the nonce-coverage check (issue #193). An unreadable directory
    yields empty maps — the same as a run root that wrote no artifact."""
    result = {'checklist': {}, 'verification': {}, 'checklist_values': {}}
    try:
        names = os.listdir(run_root_dir)
    except OSError:
        return result
    for name in names:
        m1 = _CHECKLIST_ARTIFACT_RE.match(name)
        if m1:
            status, value = _read_json_array_value(os.path.join(run_root_dir, name))
            result['checklist'][m1.group('n')] = status
            result['checklist_values'][m1.group('n')] = value
            continue
        m2 = _VERIFICATION_ARTIFACT_RE.match(name)
        if m2:
            result['verification'][m2.group('n')] = _read_json_array_value(
                os.path.join(run_root_dir, name))[0]
    return result


def _grade_run_root(run_root_dir):
    """The 2-tuple `(grade, payload)` grade of a run root — the stable contract callers and
    the focused tests read. Delegates to `_grade_run_root_detail`, dropping its third
    element (the qualifying iteration's agent-item count, used only by the transcript
    backstop)."""
    grade, payload, _agent_count = _grade_run_root_detail(run_root_dir)
    return grade, payload


def _grade_run_root_detail(run_root_dir):
    """Grade a checklist-owing run's run root by its durable Phase 1 / Phase 2 work
    products (issue #21) AND per-item nonce verifier files (issue #193). The artifacts and
    their nonce coverage decide first; the phase log is consulted only when no qualifying
    artifact pair exists, for the special no-work-product records. Returns
    `(grade, payload, agent_count)` where `agent_count` is the qualifying iteration's
    effective agent-mode item count on the 'pass' arm and None otherwise:
      ('pass', None, n)                                    a valid checklist+verification
                                                           array pair for at least one
                                                           iteration, each of that
                                                           iteration's agent-mode items
                                                           backed by a nonce verifier file
      ('unestablished', 'review-artifact-malformed', None) a present-but-corrupt artifact
      ('unestablished', 'phase-log-malformed', None)       no pair; malformed phase log
      ('unestablished', 'run-root-unreadable', None)       no pair; unreadable phase log
      ('special', 'blocker-recheck-hit' | 'generator-failure', None)  a no-checklist record
      ('fail', [missing-token, ...], None)                 neither a qualifying pair nor a
                                                           record (a `verdict-file:<id>`
                                                           token names each agent item
                                                           lacking a verifier file)."""
    arts = _scan_artifacts(run_root_dir)
    checklist = arts['checklist']
    verification = arts['verification']
    checklist_values = arts['checklist_values']
    # Pass: some single iteration carries BOTH a parseable-array checklist AND a
    # parseable-array verification artifact, AND every effective agent-mode item in that
    # iteration's checklist has a nonce verifier file (issue #193). Every candidate pair is
    # tried, so an earlier qualifying iteration still passes during later verdict reuse; the
    # last nonce-failing candidate's missing set is kept for the fail arm.
    nonce_missing = []
    for n, status in checklist.items():
        if status == 'array' and verification.get(n) == 'array':
            satisfied, missing = _iteration_nonce_satisfied(
                run_root_dir, n, checklist_values.get(n))
            if satisfied:
                items = checklist_values.get(n) or []
                agent_count = sum(1 for it in items
                                  if _effective_verification_mode(it) == 'agent')
                return 'pass', None, agent_count
            nonce_missing = missing
    # No qualifying pair. A present-but-malformed artifact means the run's outputs cannot be
    # trusted as evidence — unestablished (AC3). An absent iteration has no key, so this
    # fires only on a real corrupt file.
    if any(s == 'malformed' for s in checklist.values()) or \
       any(s == 'malformed' for s in verification.values()):
        return 'unestablished', 'review-artifact-malformed', None
    # No qualifying pair and nothing malformed. Consult the phase log for the special records
    # (AC5) — the only channel those no-work-product arms leave. The phase log is not
    # required to exist (AC3): its absence just means no special record.
    kind, text = _read_phase_log(run_root_dir)
    if kind == 'unreadable':
        return 'unestablished', 'run-root-unreadable', None
    if kind == 'content':
        grade, payload = _grade_phase_log(text)
        if grade == 'malformed':
            return 'unestablished', 'phase-log-malformed', None
        if grade == 'record':
            return 'special', payload, None
    # The fail arm (AC3/AC4). An absent array is named as a missing artifact; when both
    # arrays are present but no iteration's nonce coverage is complete, name the missing
    # verifier files instead (issue #193).
    missing = []
    if not any(s == 'array' for s in checklist.values()):
        missing.append('checklist-artifact')
    if not any(s == 'array' for s in verification.values()):
        missing.append('verification-artifact')
    if not missing and nonce_missing:
        missing = ['verdict-file:' + m for m in nonce_missing]
    if not missing:
        # Both kinds have a valid array, but never at a common iteration — no single
        # iteration's pair, so name both.
        missing = ['checklist-artifact', 'verification-artifact']
    return 'fail', missing, None


def _sha256_file(path):
    """(hex, None) on success; (None, 'unreadable') when the file cannot be read. Reads bytes,
    so a non-UTF-8 artifact digests without raising."""
    try:
        with open(path, 'rb') as fh:
            return hashlib.sha256(fh.read()).hexdigest(), None
    except OSError:
        return None, 'unreadable'


def _read_active_entry_binding(run_root_dir, entry, iteration):
    """Read and validate the active-entry binding for (entry, iteration) — issue #516. Returns
    (binding_dict, None) or (None, 'missing'|'unreadable'|'malformed'). The binding ties this
    entry's verdict to its own producer artifacts, so a missing or ill-typed binding is never
    evidence: an absent binding routes to the special-record / unestablished arms, and a
    present-but-malformed one is unestablished (never laundered into a pass)."""
    path = os.path.join(run_root_dir, f'active-entry-{entry}-iter-{iteration}.json')
    try:
        with open(path, 'rb') as fh:
            raw = fh.read()
    except FileNotFoundError:
        return None, 'missing'
    except OSError:
        return None, 'unreadable'
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeError):
        return None, 'malformed'
    if not isinstance(obj, dict):
        return None, 'malformed'
    # `schema_version` is the binding-shape version this grader interprets; a value other than
    # the exact int 1 (a future shape, or a corrupt/absent field) is not graded under v1
    # semantics — malformed, so the caller routes to unestablished rather than reading a
    # decorative version field as an implicit v1 (issue #516 hardening). A bool is an int
    # subclass (True == 1), so reject it explicitly — only the literal int 1 is v1.
    schema_version = obj.get('schema_version')
    if (not isinstance(schema_version, int) or isinstance(schema_version, bool)
            or schema_version != 1):
        return None, 'malformed'
    # `iteration` must be a real int (a bool is an int subclass, so reject it explicitly);
    # the string fields must be non-empty; `reuse` defaults to [] but must be a list if given.
    if not isinstance(obj.get('entry'), str):
        return None, 'malformed'
    if not isinstance(obj.get('iteration'), int) or isinstance(obj.get('iteration'), bool):
        return None, 'malformed'
    # Every string field must be non-empty: an empty `reviewed_head` is an unestablished head,
    # and on the `--entry latest` path (which grades the binding's OWN recorded head) the
    # mismatch guard would compare '' against '' and pass — laundering a verdict marker over an
    # unestablished head. Require it non-empty alongside its siblings, closing that fail-open.
    for key in ('reviewed_head', 'checklist_artifact', 'verification_artifact', 'verdicts_subdir'):
        if not isinstance(obj.get(key), str) or not obj.get(key):
            return None, 'malformed'
    if not isinstance(obj.get('reuse', []), list):
        return None, 'malformed'
    return obj, None


def _special_record_grade(run_root_dir):
    """The special no-work-product arm (AC5): consult the phase log for the two records that
    legitimately stand in for the checklist phases. Returns a `_grade_run_root_detail`-shaped
    3-tuple — ('special', 'blocker-recheck-hit'|'generator-failure', None) or an
    ('unestablished', <reason>, None) for an unreadable/malformed log — or None when the log
    carries no special record (an absent log is None, not a fault)."""
    kind, text = _read_phase_log(run_root_dir)
    if kind == 'unreadable':
        return 'unestablished', 'run-root-unreadable', None
    if kind == 'content':
        grade, payload = _grade_phase_log(text)
        if grade == 'malformed':
            return 'unestablished', 'phase-log-malformed', None
        if grade == 'record':
            return 'special', payload, None
    return None


def _nonce_file_in_dir(run_root_dir, subdir, item_id, excluded_names=frozenset()):
    """Whether a `<subdir>/<item-id>-*.json` verifier file exists under the run root — the
    entry-scoped variant of `_nonce_file_present` (issue #516). Existence of the nonce FILE is
    the requirement; no verification array is read. A basename in `excluded_names` does not
    count (issue #621: a shadow file whose name is also step1's is the loop's file, since
    nonces are unique per dispatch)."""
    pattern = os.path.join(run_root_dir, subdir, glob.escape(item_id) + '-*.json')
    return any(os.path.isfile(p) and os.path.basename(p) not in excluded_names
               for p in glob.glob(pattern))


def _snapshot_names(run_root_dir, subdir):
    """The basenames of the `*.json` verifier files in a snapshot directory (issue #621).
    Returns (names, None), or (None, 'unreadable') when the directory exists but cannot be
    listed. An ABSENT directory is the empty set: a producer that copied no verifier file
    leaves none, an observed fact. An unreadable one is not that fact — `glob` reports both
    as no matches, and an empty exclusion set excludes nothing while an empty own-snapshot
    set reports nothing unbound, so each caller would silently claim what it never observed.
    Unknown is not zero here: the callers route the reason to an unestablished arm."""
    path = os.path.join(run_root_dir, subdir)
    try:
        entries = os.listdir(path)
    except FileNotFoundError:
        return set(), None
    except OSError:
        return None, 'unreadable'
    return {name for name in entries
            if name.endswith('.json') and os.path.isfile(os.path.join(path, name))}, None


def _bound_agent_item_ids(checklist_items):
    """The usable ids of the effective agent-mode items in a bound checklist (issue #621)."""
    if not isinstance(checklist_items, list):
        return set()
    ids = set()
    for item in checklist_items:
        if _effective_verification_mode(item) != 'agent':
            continue
        item_id = item.get('id') if isinstance(item, dict) else None
        if isinstance(item_id, str) and item_id:
            ids.add(item_id)
    return ids


def _unbound_snapshot_files(run_root_dir, verdicts_subdir, checklist_items, excluded_names):
    """The entry's own snapshot files that belong to no bound agent item (issue #621), by the
    same `<item-id>-` prefix rule the nonce lookup globs — so a retry's second nonce file for a
    bound id stays valid while a file carried over from a wider claim set does not. Files the
    step1-filename exclusion already dropped are not the entry's, so they are ignored here.
    Returns (sorted basename list, None), or (None, 'unreadable') when the snapshot directory
    could not be listed — an unenumerable snapshot is not an empty one."""
    names, reason = _snapshot_names(run_root_dir, verdicts_subdir)
    if reason is not None:
        return None, reason
    bound = _bound_agent_item_ids(checklist_items)
    return sorted(
        name for name in names
        if name not in excluded_names
        and not any(name.startswith(item_id + '-') for item_id in bound)), None


def _shadow_step1_binding(run_root_dir, iteration):
    """The `step1` binding for the shadow's OWN iteration (issue #621), the reference the
    shadow's independence is measured against. Returns (binding, None), (None, None) when no
    step1 binding exists (both step1-derived checks are then skipped), or (None, fault-tuple)
    for an unreadable or malformed one. The entry/iteration/head mismatch check is deliberately
    not applied: Step 2.6 can follow an early-exit convergence, so step1's reviewed head can
    legitimately differ from the shadow's at the same iteration."""
    binding, reason = _read_active_entry_binding(run_root_dir, 'step1', iteration)
    if reason == 'unreadable':
        return None, ('unestablished', 'active-entry-step1-binding-unreadable', None)
    if reason == 'malformed':
        return None, ('unestablished', 'active-entry-step1-binding-malformed', None)
    return binding, None


def _shadow_artifact_grade(binding, step1_binding, checklist_value, verification_value):
    """Grade a bound shadow artifact against step1's own record of the same iteration (issue
    #621). Returns the unestablished reason, or None when both artifacts are the shadow's own.
    The shadow and the loop write the same `checklist-iter-<N>.json` /
    `verification-iter-<N>.json` filenames, so a digest identical to step1's means the shadow
    never rewrote that artifact and its binding snapshotted step1's work —
    `active-entry-artifact-stale`. An empty `[]` artifact is exempt: two independent empty
    artifacts collide by construction, not by staleness. A step1 record carrying no usable
    digest (its producer could not hash its own artifact) cannot answer the comparison at all,
    so a NON-EMPTY shadow artifact is then `active-entry-step1-digest-unestablished` rather
    than a silent pass that skips the staleness check for that artifact."""
    for value, key in ((checklist_value, 'checklist_sha256'),
                       (verification_value, 'verification_sha256')):
        if not value:
            continue
        theirs = step1_binding.get(key)
        if not (isinstance(theirs, str) and theirs):
            return 'active-entry-step1-digest-unestablished'
        mine = binding.get(key)
        if isinstance(mine, str) and mine and mine.lower() == theirs.lower():
            return 'active-entry-artifact-stale'
    return None


def _active_entry_nonce_satisfied(run_root_dir, entry, verdicts_subdir, checklist_items,
                                  reuse_map, excluded_names=frozenset()):
    """Nonce coverage for an active entry over its OWN entry-scoped verifier snapshot (issue
    #516 AC2/AC3). Every fresh agent item needs a file in `verdicts_subdir` (the binding's
    own iteration-N snapshot); an item named in `reuse_map` is instead satisfied by that
    entry's retained prior-iteration snapshot `verdicts-<entry>/iter-<from_iteration>/`. A
    reuse claim whose `from_iteration` is not a real int, or whose retained file is absent,
    does not satisfy — reuse must point back to actual retained producer evidence. A fresh
    file whose basename is in `excluded_names` does not satisfy either (issue #621). Returns
    (satisfied, [missing-item-id, ...])."""
    def resolve_item(item_id):
        if item_id in reuse_map:
            n = reuse_map[item_id]
            if not isinstance(n, int) or isinstance(n, bool):
                return False
            prior_subdir = os.path.join(f'verdicts-{entry}', f'iter-{n}')
            return _nonce_file_in_dir(run_root_dir, prior_subdir, item_id)
        return _nonce_file_in_dir(run_root_dir, verdicts_subdir, item_id, excluded_names)
    return _nonce_items_satisfied(checklist_items, resolve_item)


def _grade_active_entry_detail(run_root_dir, entry, iteration, reviewed_head):
    """Grade a fix-loop entry's verdict against THAT entry's own producer evidence (issue
    #516): its exact entry/iteration/reviewed-head binding and the checklist, verification
    and verifier-file artifacts the binding names. An earlier iteration's evidence never
    satisfies a later entry, so the run-wide `_grade_run_root_detail` is left untouched for
    the legacy interface (AC7). Returns `(grade, payload, agent_count)` with the run-wide
    grade's arm vocabulary plus these active-entry arms:
      ('unestablished', 'active-entry-binding-missing', None)     no current-entry binding
      ('unestablished', 'active-entry-binding-unreadable', None)
      ('unestablished', 'active-entry-binding-malformed', None)
      ('unestablished', 'active-entry-binding-mismatch', None)    binding entry/iter/head ≠ ask
      ('unestablished', 'active-entry-artifact-digest-mismatch', None)  bound file replaced
      ('unestablished', 'active-entry-artifact-digest-unestablished', None)  present artifact,
                                                                   no usable recorded digest
    and, for the `shadow` entry only, the issue #621 independence arms:
      ('unestablished', 'active-entry-step1-binding-unreadable'|'...-malformed', None)
      ('unestablished', 'active-entry-artifact-stale', None)      loop artifact bound as ours
      ('unestablished', 'active-entry-step1-digest-unestablished', None)  step1 recorded no
                                                                   usable digest to compare
      ('unestablished', 'active-entry-step1-snapshot-unreadable', None)   exclusion set
                                                                   unenumerable
      ('unestablished', 'active-entry-snapshot-unreadable', None)  own snapshot unenumerable
      ('fail', ['verdict-file-unbound:<file>', ...], None)        snapshot file with no item."""
    binding, reason = _read_active_entry_binding(run_root_dir, entry, iteration)
    if reason == 'unreadable':
        return 'unestablished', 'active-entry-binding-unreadable', None
    if reason == 'malformed':
        return 'unestablished', 'active-entry-binding-malformed', None
    if reason == 'missing':
        # No current-entry binding. The special no-checklist records still stand (AC5);
        # otherwise a legacy record lacking an active-entry binding is unestablished for
        # active-entry completion (AC7), routing the caller to bounded recovery.
        special = _special_record_grade(run_root_dir)
        if special is not None:
            return special
        return 'unestablished', 'active-entry-binding-missing', None
    # The binding must describe the caller's exact entry/iteration/reviewed head (AC4) —
    # a primary binding never answers a shadow ask, and a stale-head binding never answers a
    # new head.
    if (binding['entry'] != entry
            or binding['iteration'] != iteration
            or binding['reviewed_head'].lower() != (reviewed_head or '').lower()):
        return 'unestablished', 'active-entry-binding-mismatch', None
    checklist_path = os.path.join(run_root_dir, binding['checklist_artifact'])
    verification_path = os.path.join(run_root_dir, binding['verification_artifact'])
    c_status, c_value = _read_json_array_value(checklist_path)
    v_status, v_value = _read_json_array_value(verification_path)
    if c_status == 'malformed' or v_status == 'malformed':
        return 'unestablished', 'review-artifact-malformed', None
    missing = []
    if c_status == 'missing':
        missing.append('checklist-artifact')
    if v_status == 'missing':
        missing.append('verification-artifact')
    if missing:
        # A binding whose named artifact is absent is a legitimate generator-failure path when
        # the phase log records one (AC5); grading the absent artifact as a fail here would drop
        # that non-fabricated disposition, so the special record stands in as it does run-wide.
        special = _special_record_grade(run_root_dir)
        if special is not None:
            return special
        return 'fail', missing, None
    # A recorded digest that no longer matches the on-disk artifact means the bound file was
    # replaced after the binding was written (another entry overwriting a shared filename),
    # so the binding no longer describes what is on disk — unestablished, never a pass (AC4).
    for art_path, recorded in ((checklist_path, binding.get('checklist_sha256')),
                               (verification_path, binding.get('verification_sha256'))):
        if not (isinstance(recorded, str) and recorded):
            # The producer records a null digest only when it could not hash its own artifact.
            # A present artifact whose binding carries no usable recorded digest cannot be
            # checked for a post-binding overwrite, so it is unestablished rather than a silent
            # pass that skips the overwrite check for that artifact (issue #516 hardening).
            return 'unestablished', 'active-entry-artifact-digest-unestablished', None
        actual, _sha_reason = _sha256_file(art_path)
        if actual is None or actual.lower() != recorded.lower():
            return 'unestablished', 'active-entry-artifact-digest-mismatch', None
    # Shadow independence (issue #621): the shadow engine writes the same iteration-scoped
    # filenames the loop used, so evidence the loop produced must never grade as the shadow's.
    excluded_names = frozenset()
    if entry == 'shadow':
        step1_binding, fault = _shadow_step1_binding(run_root_dir, iteration)
        if fault is not None:
            return fault
        if step1_binding is not None:
            artifact_reason = _shadow_artifact_grade(
                binding, step1_binding, c_value, v_value)
            if artifact_reason is not None:
                return 'unestablished', artifact_reason, None
            step1_names, names_reason = _snapshot_names(
                run_root_dir, step1_binding['verdicts_subdir'])
            if names_reason is not None:
                return 'unestablished', 'active-entry-step1-snapshot-unreadable', None
            excluded_names = frozenset(step1_names)
    reuse_map = {}
    for r in binding.get('reuse', []):
        if isinstance(r, dict) and isinstance(r.get('item_id'), str):
            reuse_map[r['item_id']] = r.get('from_iteration')
    satisfied, nonce_missing = _active_entry_nonce_satisfied(
        run_root_dir, entry, binding['verdicts_subdir'], c_value, reuse_map, excluded_names)
    missing = ['verdict-file:' + m for m in nonce_missing] if not satisfied else []
    if entry == 'shadow':
        unbound, unbound_reason = _unbound_snapshot_files(
            run_root_dir, binding['verdicts_subdir'], c_value, excluded_names)
        if unbound_reason is not None:
            return 'unestablished', 'active-entry-snapshot-unreadable', None
        missing += ['verdict-file-unbound:' + name for name in unbound]
    if missing:
        return 'fail', missing, None
    items = c_value or []
    agent_count = sum(1 for it in items if _effective_verification_mode(it) == 'agent')
    return 'pass', None, agent_count


def _load_shared_reader():
    """Import scripts/context_eval_shared.py (the tolerant object/array/JSONL transcript
    reader) install-relative (issue #193). Returns (module, None) or (None, reason)."""
    return _load_sibling('context_eval_shared.py', 'review_gate_shared')


def _iter_dicts(node):
    """Yield every dict at any nesting depth, mirroring extract-execution-cost.py's descent —
    so a `tool_use` block nested inside a record's `message.content` array is reached."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _iter_dicts(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter_dicts(v)


def _subagent_of(d):
    """The subagent_type a dispatch record names — top-level (the cloud flattened shape) or
    inside `input` (the message-content tool_use shape). None when neither carries a string."""
    st = d.get('subagent_type')
    if isinstance(st, str):
        return st
    inp = d.get('input')
    if isinstance(inp, dict) and isinstance(inp.get('subagent_type'), str):
        return inp['subagent_type']
    return None


def _is_verifier_dispatch(d):
    """Whether `d` is an actual checklist-verifier DISPATCH event (issue #193): a typed
    tool_use record, or a flattened record carrying a tool identity (the cloud harness's
    `task_started` record), whose dispatched tool — when it names one — is a subagent-dispatch
    tool (`_DISPATCH_TOOL_NAMES`) and whose subagent_type is the checklist verifier. A
    `tool_result` payload and a plain string quote are never dispatches. The schema is not a
    public contract (execution-file-shape.md), so both observed shapes are tolerated."""
    if not isinstance(d, dict) or d.get('type') == 'tool_result':
        return False
    is_dispatch = (d.get('type') == 'tool_use'
                   or isinstance(d.get('tool_name'), str)
                   or 'tool_use_id' in d)
    if not is_dispatch:
        return False
    name = d.get('name') if d.get('type') == 'tool_use' else d.get('tool_name')
    if isinstance(name, str) and name not in _DISPATCH_TOOL_NAMES:
        return False
    return _subagent_of(d) == _VERIFIER_SUBAGENT


def _count_verifier_dispatches(execution_file_path):
    """(count, None) or (None, reason). The number of UNIQUE actual checklist-verifier
    dispatch events in the harness transcript (issue #193 AC6), counted over the tolerant
    object/array/JSONL carriers. A record is counted only when it carries a string
    `tool_use_id`/`id`, deduplicated by that key; a record with no string key is skipped, not
    counted (issue #242) — the fail-closed direction, since with no key there is no dedup and
    counting id-less records could inflate the count. Quoted text and tool_result payloads
    contribute nothing (only typed tool_use records are walked, never a raw substring scan).
    Missing/corrupt/incomplete transcript data → (None, reason), never a false 0."""
    try:
        with open(execution_file_path, encoding='utf-8', errors='replace') as fh:
            text = fh.read()
    except OSError:
        return None, 'missing'
    if text.strip() == '':
        return None, 'empty'
    module, _err = _load_shared_reader()
    if module is None:
        return None, 'reader-unavailable'
    try:
        parsed = module.read_transcript_records(text)
    except Exception:
        return None, 'unparseable'
    if not parsed.parsed:
        return None, 'unparseable'
    seen = set()
    count = 0
    for d in _iter_dicts(parsed.records):
        if not _is_verifier_dispatch(d):
            continue
        key = d.get('tool_use_id') or d.get('id')
        if not isinstance(key, str):
            continue
        if key in seen:
            continue
        seen.add(key)
        count += 1
    return count, None


def _offline_numstat_facts(numstat_z):
    """Build a `_recompute_diff_facts`-shaped facts dict from `git apply --numstat -z` output
    (issue #193). Each NUL-terminated record is `added\\tdeleted\\tpath` (`-` for a binary
    file's counts; the new path for a rename), so the path may itself contain tabs — split at
    most twice. Returns (facts, None) or (None, reason)."""
    files = 0
    lines = 0
    paths = []
    for record in numstat_z.split('\0'):
        if record == '':
            continue
        parts = record.split('\t', 2)
        if len(parts) != 3:
            return None, 'diff-patch-unclassifiable'
        added, deleted, path = parts
        for col in (added, deleted):
            if col != '-':
                try:
                    lines += int(col)
                except ValueError:
                    return None, 'diff-patch-unclassifiable'
        files += 1
        paths.append(path)
    # `resolved`/`reason` are constant on this path (every offline failure returns
    # (None, reason) above instead), so never branch on them; the key set is pinned to
    # workpad._recompute_diff_facts's by the focused test.
    return {'resolved': True, 'reason': '', 'lines': lines,
            'files': files, 'paths': paths}, None


def _offline_diff_facts(run_root_dir):
    """Recompute the reviewed diff's facts from `<run_root_dir>/diff.patch` alone (issue #193
    AC1) — `git apply --numstat -z` reads the patch's statistics WITHOUT applying it, with no
    ref resolution, fetch, or worktree change. Returns (facts, None) or (None, reason). An
    empty patch is a legitimate zero-file diff, not malformed."""
    # Absolute path so `cwd` below cannot re-resolve it, and so `run_root_dir` may be relative.
    patch_path = os.path.abspath(os.path.join(run_root_dir, 'diff.patch'))
    try:
        with open(patch_path, 'rb') as fh:
            raw = fh.read()
    except FileNotFoundError:
        return None, 'diff-patch-missing'
    except OSError:
        return None, 'diff-patch-unreadable'
    # An empty (or whitespace-only) patch is a legitimate zero-file diff, not malformed —
    # `git apply` rejects it (rc 128, "No valid patches"), so short-circuit to a 0-file facts
    # dict before invoking git (portable: no dependency on a newer git's --allow-empty).
    if raw.strip() == b'':
        return _offline_numstat_facts('')
    # Run `git apply --numstat` from a fresh non-repo cwd, never the reviewed repo: inside a work
    # tree git apply consults the index and silently emits empty numstat for unknown blob hashes
    # (a ref consultation AC1 forbids, and a wrong measurement). --numstat applies nothing.
    neutral = tempfile.mkdtemp(prefix='reg-numstat-')
    try:
        proc = subprocess.run(
            ['git', 'apply', '--numstat', '-z', patch_path],
            cwd=neutral, capture_output=True, encoding='utf-8', check=False)
    except OSError:
        return None, 'diff-patch-git-unavailable'
    finally:
        shutil.rmtree(neutral, ignore_errors=True)
    if proc.returncode != 0:
        return None, 'diff-patch-malformed'
    return _offline_numstat_facts(proc.stdout)


def _offline_owed_check(run_root):
    """Shared offline precheck (issue #193 AC1, refactored for #516): read the reviewed diff
    facts from the run root's own `diff.patch` — no GitHub, ref resolution, reviews payload,
    or repo checkout — and decide whether the checklist is owed. Returns
    (short_circuit_token, detail, None) to return directly (an unreadable diff, an unloadable
    workpad, or a legitimate skip), or (None, None, disproof) when the checklist IS owed and
    the caller should grade the run root."""
    facts, reason = _offline_diff_facts(run_root)
    if reason is not None:
        return f'unestablished {reason}', _detail(
            'review-evidence-gate: offline grading could not read a usable diff.patch in ',
            'run root ', run_root, ' (', reason, ').'), None
    workpad, wp_err = _load_workpad()
    if workpad is None:
        return 'unestablished workpad-import-failed', _detail(
            'review-evidence-gate: could not import scripts/workpad.py (', wp_err or '',
            ') — the checklist-owed classification is unavailable.'), None
    disproof = workpad._review_coverage_profile_disproof(facts)
    if disproof is None:
        return 'pass legitimate-skip', _detail(
            'review-evidence-gate: offline grading — the run-root diff authorizes the ',
            'intentional checklist skip; no checklist evidence owed.'), None
    return None, None, disproof


def _format_offline_grade(run_root, grade, payload, disproof=None):
    """Format a `_grade_run_root_detail`/`_grade_active_entry_detail` grade+payload into the
    shared offline (token, [detail...]) shape. `disproof`, when supplied, names the
    checklist-owed reason in the fail detail."""
    if grade == 'unestablished':
        return f'unestablished {payload}', _detail(
            'review-evidence-gate: offline grading of run root ', run_root,
            ' is unestablished (', str(payload), ').')
    if grade == 'special':
        arm = ('blocker-recheck-hit' if payload == 'blocker-recheck-hit'
               else 'generator-failure-skip')
        return f'pass {arm}', _detail(
            'review-evidence-gate: offline grading — the run root carries the ', str(payload),
            ' record, a legitimate no-checklist arm.')
    if grade == 'pass':
        return 'pass checklist-phases-ran', _detail(
            'review-evidence-gate: offline grading — the run root holds the durable ',
            'checklist/verification artifact pair and a nonce verifier file for every ',
            'agent-mode item.')
    owed = f' owes the checklist phases ({disproof}) but' if disproof else ''
    return f'fail missing={",".join(payload)}', _detail(
        'review-evidence-gate: offline grading — the graded run root ', run_root,
        owed, ' is missing: ', ', '.join(payload), '.')


def _decide_offline(run_root):
    """Grade a run root offline through the legacy run-wide `_grade_run_root_detail` (issue
    #193 AC1) — no GitHub, ref resolution, reviews payload, or repo checkout. Returns
    (token, [detail...])."""
    token, detail, disproof = _offline_owed_check(run_root)
    if token is not None:
        return token, detail
    grade, payload, _agent_count = _grade_run_root_detail(run_root)
    return _format_offline_grade(run_root, grade, payload, disproof)


def grade_run_root_offline(run_root_dir):
    """Public offline run-wide grade for the producer helpers (post-review-verdict.sh via
    subprocess, loop-verdict-marker.py via install-relative import) — issue #193 AC3/AC5, and
    the legacy interface issue #516 preserves unchanged. Returns (token, [detail...]); the
    token's first field is `pass`/`fail`/`unestablished` exactly as the CLI emits, so a caller
    admits only an explicit `pass ` result."""
    return _decide_offline(run_root_dir)


def grade_active_entry_offline(run_root_dir, entry, iteration, reviewed_head):
    """Public offline ACTIVE-ENTRY grade (issue #516) for loop-verdict-marker.py: the same
    owed/skip precheck as `grade_run_root_offline`, then grade the named entry against its own
    producer evidence via `_grade_active_entry_detail`. Returns (token, [detail...]); the
    token's first field is `pass`/`fail`/`unestablished` exactly as the run-wide grade emits,
    so a caller admits only an explicit `pass ` result."""
    token, detail, disproof = _offline_owed_check(run_root_dir)
    if token is not None:
        return token, detail
    grade, payload, _agent_count = _grade_active_entry_detail(
        run_root_dir, entry, iteration, reviewed_head)
    return _format_offline_grade(run_root_dir, grade, payload, disproof)


def _decide(args):
    """Compute the verdict token and its human-readable detail lines. Returns
    (token, [detail...])."""
    pre, pre_err = _read_json(args.pre_inventory)
    if pre_err is not None or not isinstance(pre, dict):
        return 'unestablished pre-inventory-unreadable', _detail(
            'review-evidence-gate: the pre-engine inventory at ',
            args.pre_inventory, ' is ', pre_err or 'not an object', '.')
    pre_run_roots = set(pre.get('run_roots') or [])
    pre_review_ids = set(pre.get('review_ids') or [])

    reviews, rev_err = _read_json(args.reviews_payload)
    if rev_err is not None:
        return f'unestablished reviews-payload-{rev_err}', _detail(
            'review-evidence-gate: the reviews payload at ',
            args.reviews_payload, ' is ', rev_err, '.')
    if not isinstance(reviews, list):
        return 'unestablished reviews-payload-not-an-array', _detail(
            'review-evidence-gate: the reviews payload is not a JSON array.')
    if not args.reviewer_login:
        return 'unestablished reviewer-login-absent', _detail(
            'review-evidence-gate: no reviewer login was supplied, so this ',
            "run's own reviews could not be told from a human's.")

    placed = _classify_own_reviews(reviews, args.reviewer_login)
    # This run's verdict: a marker-bearing review whose id is NOT in the pre-engine
    # inventory (a verdict already present before the engine step is a prior run's, not
    # this run's — so it is never dismissed).
    fresh_marked = [(rid, state, mhead) for (rid, state, mhead) in placed['marked']
                    if rid not in pre_review_ids]
    fresh_unmarked = [rid for rid in placed['unmarked'] if rid not in pre_review_ids]

    if not fresh_marked:
        detail = _detail(
            'review-evidence-gate: this run posted no marker-bearing verdict.')
        if fresh_unmarked:
            detail.extend(_detail(
                'review-evidence-gate: unmarked own-identity review(s) present ',
                'and reported as unmarked (not counted as a posted verdict): ',
                ', '.join(str(r) for r in sorted(
                    i for i in fresh_unmarked if isinstance(i, int)))))
        return 'no-verdict', detail

    # The ID-set delta is only trustworthy when the pre-engine review-ID baseline was
    # actually established. When the pre-inventory step could not fetch the head's
    # reviews (recorded `review_ids_established: false`), every id is "fresh" by default,
    # so a PRIOR run's legitimate verdict would be mis-attributed to this run and could be
    # dismissed — so a verdict under an unestablished baseline is unestablished, never a
    # fail or a dismissal. A missing key is the pre-#2075 inventory shape and reads as
    # established (the common success case).
    if not pre.get('review_ids_established', True):
        return 'unestablished pre-inventory-review-ids-unestablished', _detail(
            'review-evidence-gate: the pre-engine review-ID baseline was not ',
            'established (the pre-inventory step could not fetch the reviews), so ',
            'this run cannot be told from a prior run and no verdict is dismissed.')

    # The newest marker-bearing verdict review (largest id) is the run's verdict; the
    # reviewed head is that verdict marker's OWN head, so a /prflow:review-and-fix verdict
    # is graded against the head it recorded rather than the PR's current head.
    verdict_id, verdict_state, reviewed_head = max(
        fresh_marked,
        key=lambda t: t[0] if isinstance(t[0], int) else -1)

    # Does the diff owe the checklist phases? Reuse workpad.py's own classification.
    if not _engine_root_has_instruction(args.vendored_engine_root):
        return 'unestablished engine-root-lacks-artifact-instruction', _detail(
            'review-evidence-gate: the vendored engine root at ',
            args.vendored_engine_root, ' does not carry the durable-artifact ',
            'write instruction in its phase files (an older vendored engine); no ',
            'checklist-phase artifact can be required of it.')

    # The classification lives in scripts/workpad.py — import it now (not at entry), so a
    # no-verdict / older-engine / unestablished-baseline run never pays the import.
    workpad, wp_err = _load_workpad()
    if workpad is None:
        return 'unestablished workpad-import-failed', _detail(
            'review-evidence-gate: could not import scripts/workpad.py (', wp_err or '',
            ') — the classification implementation is unavailable, so no ',
            'checklist-requirement decision could be made.')

    facts = workpad._recompute_diff_facts(
        reviewed_head, args.base_ref or None, args.repo_root)
    if not facts['resolved']:
        return 'unestablished diff-classification-unresolved', _detail(
            'review-evidence-gate: the reviewed diff could not be recomputed: ',
            facts['reason'], '.')
    disproof = workpad._review_coverage_profile_disproof(facts)
    if disproof is None:
        # The diff authorizes the intentional checklist skip — no checklist owed.
        return 'pass legitimate-skip', _detail(
            'review-evidence-gate: the recomputed diff authorizes the ',
            'intentional checklist skip (small config-only diff); no checklist ',
            'evidence owed.')

    # The checklist IS owed. Attribute this run's run root by the inventory delta.
    post_run_roots, roots_err = _list_run_roots(args.post_tree_root)
    if roots_err is not None:
        return f'unestablished {roots_err}', _detail(
            'review-evidence-gate: the .prflow/tmp/review tree could not be read.')
    fresh_roots = sorted(post_run_roots - pre_run_roots)
    if len(fresh_roots) > 1:
        return 'unestablished run-root-delta-unattributable', _detail(
            'review-evidence-gate: more than one run root appeared during the ',
            'engine step (', ', '.join(fresh_roots), '); this run cannot be ',
            'attributed.')

    fail_detail_head = (
        f'review-evidence-gate: this run posted a merge-gating verdict (review '
        f'{verdict_id}, state {verdict_state}) for head {reviewed_head}, its diff requires '
        f'the checklist phases ({disproof}), but ')

    if not fresh_roots:
        # No run root appeared during the engine step — the same missing-record state as a
        # run root that holds neither durable artifact nor a special record (AC3).
        return (f'fail missing=run-root review_id={verdict_id} '
                f'review_state={verdict_state}'), _detail(
            fail_detail_head, 'the engine step created NO run-scoped ',
            'directory at all, so no durable checklist or verification artifact ',
            'records that the checklist phases ran.')

    run_root_dir = os.path.join(args.post_tree_root, _REVIEW_SUBDIR, fresh_roots[0])
    grade, payload, agent_count = _grade_run_root_detail(run_root_dir)
    if grade == 'unestablished' and payload == 'review-artifact-malformed':
        return 'unestablished review-artifact-malformed', _detail(
            'review-evidence-gate: a durable checklist-phase artifact in run root ',
            fresh_roots[0], ' is present but is not a parseable JSON array; its ',
            'contents cannot be trusted as evidence.')
    if grade == 'unestablished' and payload == 'phase-log-malformed':
        return 'unestablished phase-log-malformed', _detail(
            'review-evidence-gate: run root ', fresh_roots[0], ' holds no durable ',
            'artifact pair, and its phase log carries a line outside the closed ',
            'record grammar; its contents cannot be trusted as evidence.')
    if grade == 'unestablished' and payload == 'run-root-unreadable':
        return 'unestablished run-root-unreadable', _detail(
            'review-evidence-gate: the attributed run root ', fresh_roots[0],
            ' holds no durable artifact pair and its phase log could not be read ',
            '(an I/O or permission failure).')
    if grade == 'special' and payload == 'blocker-recheck-hit':
        return 'pass blocker-recheck-hit', _detail(
            'review-evidence-gate: the run root carries the Phase 0.3.6 ',
            'blocker-recheck hit record, the sole evidence its fast-path ',
            're-verdict owes.')
    if grade == 'special' and payload == 'generator-failure':
        return 'pass generator-failure-skip', _detail(
            'review-evidence-gate: the phase log carries the checklist ',
            'generator double-failure record, a legitimate no-checklist arm.')
    if grade == 'pass':
        # Transcript backstop (issue #193 AC6): require the dispatch count to meet the qualifying
        # iteration's agent-item count. A supplied-but-unusable transcript is unestablished, never
        # a silent pass-through; an established shortfall takes the existing fail action.
        if getattr(args, 'execution_file', None):
            required = agent_count or 0
            observed, treason = _count_verifier_dispatches(args.execution_file)
            if observed is None:
                return f'unestablished execution-transcript-{treason}', _detail(
                    'review-evidence-gate: an execution transcript was supplied but its ',
                    'checklist-verifier dispatch count could not be established (', treason,
                    '); the run is neither passed nor failed on the transcript.')
            if observed < required:
                return (f'fail missing=transcript-dispatch-shortfall '
                        f'review_id={verdict_id} review_state={verdict_state}'), _detail(
                    fail_detail_head, 'the harness transcript records only ', str(observed),
                    ' checklist-verifier dispatch event(s), below the ', str(required),
                    ' its agent-mode checklist items require (observed=', str(observed),
                    ' required=', str(required), ').')
            return 'pass checklist-phases-ran', _detail(
                'review-evidence-gate: the attributed run root holds the durable Phase 1 ',
                'checklist and Phase 2 verification artifacts, and the harness transcript ',
                'corroborates the dispatches (observed=', str(observed), ' required=',
                str(required), ').')
        return 'pass checklist-phases-ran', _detail(
            'review-evidence-gate: the attributed run root holds the durable Phase 1 ',
            'checklist and Phase 2 verification artifacts recording that the checklist ',
            'phases ran; no execution transcript was supplied, so the dispatch count ',
            'was not corroborated.')
    # grade == 'fail'
    missing = payload
    return (f'fail missing={",".join(missing)} review_id={verdict_id} '
            f'review_state={verdict_state}'), _detail(
        fail_detail_head, 'the attributed run root ', fresh_roots[0],
        ' is missing these durable checklist-phase artifacts: ', ', '.join(missing), '.')


def _force_utf8_streams():
    """Force stdin/stdout/stderr to UTF-8 on the entry path (issue #1762). The detail lines
    carry em-dashes, so a non-UTF-8 runner would otherwise raise on print. Never called at
    import — that would mutate an importing test's streams. Tolerates a stream with no
    usable reconfigure."""
    for _stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None):
    _force_utf8_streams()
    parser = argparse.ArgumentParser(
        description='Fail a cloud review run whose posted verdict lacks phase-execution '
                    'evidence (issue #2075). Exits 0 for every decision outcome once '
                    'arguments parse; the caller reads stdout line 1 for the verdict '
                    'token.')
    # The six cloud-path flags are required=False so `--grade-run-root` (issue #193 AC1) can
    # run without them; the cloud path re-requires the three it needs by hand below, so its
    # exit-2-on-missing-required contract is unchanged for the workflow caller.
    parser.add_argument('--pre-inventory',
                        help='JSON {"run_roots":[...],"review_ids":[...]} snapshotted '
                             'before the engine step.')
    parser.add_argument('--post-tree-root',
                        help='repo root whose .prflow/tmp/review/ tree is re-listed now.')
    parser.add_argument('--reviews-payload',
                        help='reviews-API JSON array path, or - for stdin.')
    parser.add_argument('--base-ref', default='',
                        help='the PR base ref for the diff recompute (may be empty).')
    parser.add_argument('--repo-root', default='.',
                        help='repo root for the classification recompute.')
    parser.add_argument('--reviewer-login', default='',
                        help='the run\'s own reviewer identity (.user.login).')
    parser.add_argument('--vendored-engine-root', default='',
                        help='the checked-out review engine root (holds SKILL.md).')
    parser.add_argument('--grade-run-root',
                        help='offline mode (issue #193): grade this run root from its own '
                             'diff.patch alone — no GitHub, ref resolution, or fetch.')
    parser.add_argument('--execution-file',
                        help='the harness transcript (issue #193): count actual '
                             'checklist-verifier dispatch events as a cloud-path backstop.')
    args = parser.parse_args(argv)

    if args.grade_run_root is None:
        _missing = [name for name, value in (
            ('--pre-inventory', args.pre_inventory),
            ('--post-tree-root', args.post_tree_root),
            ('--reviews-payload', args.reviews_payload)) if value is None]
        if _missing:
            parser.error('the following arguments are required: ' + ', '.join(_missing))

    # Uphold the exit-0-after-parsing contract at the source: any unexpected fault in the
    # decision routes to an unestablished arm (a warning), never a traceback that would end
    # the step non-zero and fail the job on the gate's own bug.
    try:
        token, detail = (_decide_offline(args.grade_run_root)
                         if args.grade_run_root else _decide(args))
    except Exception as e:  # a decision fault must never crash the step
        token = 'unestablished internal-error'
        detail = _detail('review-evidence-gate: an unexpected internal error occurred (',
                         f'{type(e).__name__}: {e}', '); reported unestablished.')
    print(token)
    for line in detail:
        print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
