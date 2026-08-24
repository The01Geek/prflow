#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Behavioral eval for the runtime main-thread context cost of /devflow:create-issue.

This is a maintainer/CI-adjacent instrument, NEVER invoked by the skill's runtime
path (neither the local nor the cloud tier). It walks a supplied Claude Code
transcript directory and measures the *runtime main-thread context* a
`/devflow:create-issue` run accumulates — a distinct quantity from the static
shipped word count of the skill files.

The module also owns the paired A/B evaluation surface built on those measurements:
deterministic rubric grading (`grade_issue`), the fail-closed paired quality gate whose
result gates efficiency credit in `create_issue_benchmark` (`quality_gate`), and the
explicit-manifest evaluation engine (`load_eval_manifest`, `build_manifest_report`).
Nothing in this module withholds credit itself — `aggregate_benchmark` does.

Issue #889 extends the instrument to attribute the **Step 3.6 audit round** cost
that #793 introduced. That cost is spent by the auditor **subagent**, whose turns
the harness emits as `isSidechain` records — records the pre-#889 instrument
dropped with a single line. This module now attributes those sidechain `usage`
records to rounds, deriving the round boundaries from the transcript's own
`issue-audit-state.py record-dispatch --round N` tool-use records and reading the
round->kind labelling (and the per-finding quoted draft line + per-round scope) from
the audit state file **best-effort**: every degraded state-file shape yields
`unestablished` per-kind figures with a stderr breadcrumb, never a number and never
a crash.

The scope-escape proxy needs a `scope.draft_lines` span on a targeted round. As of
issue #1105 `scripts/issue-audit-state.py`'s `record-dispatch` records that key (the
convex-hull draft-line span over the changed sections), so the proxy is now fillable
against a state file carrying a targeted round dispatched under that code — it reports an
integer. Two arms still report `unestablished` rather than a misleading `0`: a targeted
round whose recorded span is absent (a pre-#1105 round), wrong-typed or inverted (see
`_scope_draft_span`), and — orthogonally — a state carrying **no targeted round at all**
reports a genuine, established `0`, since nothing can escape a scope that was never
dispatched. The other two proxies — the `record-reopen` count and the declared
post-filing class — are unaffected.

A "run" is bounded by `attributionSkill` matching any declared `<ns>:create-issue` on
`type == "assistant"` records. A **main-thread** (non-`isSidechain`) attributed
assistant record measures the ORCHESTRATOR's main-thread context — reported as a
**secondary** axis (never the sole basis of a reduction claim). A **sidechain**
attributed assistant record is the auditor's own turn; its total token cost is
attributed to the round the most recent `record-dispatch --round N` marker opened.
One session JSONL file that contains at least one main-thread attributed assistant
record yields one run — so a run that RESUMES into a separate session file is reported
as its own run (cross-session merging is out of scope, a disclosed proxy). That
disclosure matters more since #889 than before it: a resumed run splits its
`round_auditor_cost` across two run records, and `_paired_delta`'s round count sums
`dispatch_rounds` per run, so a resumed before-corpus inflates the round-count delta.

UNVERIFIED ASSUMPTION, disclosed rather than assumed away: that the harness stamps
`attributionSkill` on an `isSidechain` assistant record at all. Nothing in this
repository establishes it — the synthetic fixtures assert the attribution logic, not
the harness's real emit shape. If the harness omits the field on sidechain records,
`_observe_sidechain` returns early for every auditor turn and the whole auditor-cost
axis reads a silent `0` that is indistinguishable from a genuinely free audit. The
first real-corpus run is what settles it: read `total_unrounded_auditor_cost` and the
per-round tallies together, and treat an all-zero auditor axis on a corpus that
demonstrably ran audit rounds (`dispatch_rounds` non-empty) as evidence of this
assumption failing, not as a measurement. Since issue #1751 made every fresh-context
audit round user-elected, an EMPTY `dispatch_rounds` set is the expected default of a
run that declined the audit — not evidence of anything — so the discriminator above is
deliberately conditioned on `dispatch_rounds` non-empty and never reads a zero-round run
as an attribution failure.

Per-record token usage is read from `message.usage.{input_tokens,
cache_read_input_tokens, cache_creation_input_tokens, output_tokens}`. Per-turn
main-thread context (the RESIDENCY axis) is `input_tokens + cache_read_input_tokens +
cache_creation_input_tokens`; a turn establishing none of those residency sub-fields (no
usage object, an empty or all-null one, or a non-finite count) is an unmeasured turn —
tallied in `usage_missing_turns` and excluded from the peak, never folded in as a
real-looking 0 (issue #1899). The auditor's per-round cost is the full token total
(context sub-fields + output) on the SPEND axis, where an unmeasured sub-field stays a
summable 0 so the cost arithmetic is never handed an unestablished value. Compaction is
observed as `type == "system", subtype == "compact_boundary"` and only counted.

Two redundant-addition metrics are also reported (pre-#889, retained): repeated-Read
(a `Read` re-fetching bytes already resident for that path — fail-closed on a
truncated/errored/absent tool_result) and re-emission (a large assistant text block
whose exact bytes were already produced earlier in the run).

Wall-clock is deliberately NOT claimed as a measured axis on this tier: it is
reported `unestablished`, citing the local tier's inability to measure it, rather
than asserted as something the orchestrator observes. No cost figure is sourced
from a value the orchestrator volunteers — the harness emits the same data
deterministically.

The parser streams records line by line (it never buffers an entire session into
memory) and degrades per malformed record without detonating, reporting how many
records it skipped and why. It is deterministic: re-running over the same corpus
yields byte-identical output. It writes NO transcript contents and embeds no
owner-specific identifiers.

Usage:
    create-issue-context-eval.py <transcript-dir> [--state-file F]
                                 [--format {text,json}] [--large-block-chars N]
    create-issue-context-eval.py --before <dir> --after <dir>
                                 [--before-state F] [--after-state F]
                                 [--format {text,json}] [--large-block-chars N]
"""

from __future__ import annotations

import argparse
import collections
import copy
import difflib
import hashlib
import importlib.util
import json
import math
import os
import re
import sys

# A run is bounded by `attributionSkill`, which carries the LIVE plugin namespace. That
# namespace is renameable, and historical census rows keep whatever namespace was live
# when they were written — so this must accept EVERY declared namespace, not one literal.
# A single hardcoded id silently matches nothing after a rename (every new run rejected,
# the eval reporting zero runs with no error), or silently drops the history if simply
# swapped. Derived from the same identity source the rest of the repo single-sources.
_IDENTITY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib", "plugin_identity.py"
)


def _attribution_ids():
    """Every accepted `<namespace>:create-issue` attribution id, canonical first.

    Falls back to the historical id rather than an EMPTY set: an empty set would make
    every record mismatch and report a vacuous zero-run measurement, which is exactly
    the silent failure this function exists to prevent.
    """
    spec = importlib.util.spec_from_file_location("plugin_identity", _IDENTITY_PATH)
    if spec is None or spec.loader is None:
        print(
            f"create-issue-context-eval: identity source {_IDENTITY_PATH} is not "
            "importable; falling back to the historical attribution id only",
            file=sys.stderr,
        )
        return ("devflow:create-issue",)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    ids = tuple(ns + "create-issue" for ns in module.agent_namespaces())
    if not ids:
        print(
            "create-issue-context-eval: the declared namespace set is empty; falling "
            "back to the historical attribution id only",
            file=sys.stderr,
        )
        return ("devflow:create-issue",)
    return ids


ATTRIBUTION = _attribution_ids()
# A run's context growth from re-quotation is dominated by large blocks; small
# restatements (a one-line pointer, a status word) are not the reducible cost this
# eval targets. 500 chars ~ a paragraph, well below any real findings/summary block.
LARGE_BLOCK_MIN_CHARS = 500
# The peak-context bucket thresholds the aggregate summary reports on.
BUCKET_200K = 200_000
BUCKET_400K = 400_000
# The sentinel a per-kind / proxy figure carries when the state file could not
# supply the operand it needs. It is NEVER a number and NEVER 0 — an unestablished
# measurement collapsed onto a real value is the bug the whole axis guards against.
UNESTABLISHED = "unestablished"
# Every stderr breadcrumb this module writes carries one prefix: the module is
# reachable under two script names, and a second literal makes an operator
# grepping by prefix miss a whole degradation class.
BREADCRUMB_PREFIX = "create-issue-context-eval"
MANIFEST_SCHEMA_VERSION = 1
REPORT_SCHEMA_VERSION = 1
BOUNDARY_CONFIDENCE = ("exact", "approximate", "unknown")
RUBRIC_SCHEMA_VERSION = 1
_AUDIT_STATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "issue-audit-state.py"
)
_AUDIT_STATE_OWNER = None
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_LIST_ITEM_RE = re.compile(r"^[ \t]*(?:[-+*]|[0-9]+[.)])[ \t]+\S")
_WORD_RE = re.compile(r"\b[\w'-]+\b", re.UNICODE)
_IMPACT_CLASSES = (
    "implementation-correctness",
    "scope",
    "safety",
    "verifiability",
    "clearly-optional",
)
# Coupled with `_IMPACT_CLASSES` in scripts/issue-audit-state.py, which owns the closed
# vocabulary. A member added there and not mirrored here must NOT reach `_impact_counts`
# as an uncaught KeyError — this module's contract is best-effort, never a crash.
IMPACT_CLASS_COUPLING_ASSERTED_BY = (
    "lib/test/test_create_issue_context_eval.py::RoundKindCouplingTest")
# The closed round-kind vocabulary #793 records on each round.
#
# Coupled with `_ROUND_KINDS` in scripts/issue-audit-state.py — the closed, complete
# round-kind vocabulary that module owns (issue #793). This is a deliberate duplicated
# literal (the eval is a standalone stdlib-only instrument that imports nothing from the
# state owner); a new kind added there must be mirrored here in the same change.
# `ROUND_KINDS_COUPLING_ASSERTED_BY` names the test that reconciles the two tuples, so
# the drift this comment warns about goes RED rather than shipping green.
#
# The degradation it causes, stated exactly: `read_state` returns None for the WHOLE
# state file when any round carries a PRESENT-but-unmirrored kind — collapsing both
# per-kind medians, both scope-escape fields and every other round's labelling, not
# merely the one round. An ABSENT kind is legal in a persisted round (a pre-#793 record)
# and is defaulted to `discovery`, exactly as the state owner's own read boundary does.
ROUND_KINDS = ("discovery", "targeted")
ROUND_KINDS_COUPLING_ASSERTED_BY = (
    "lib/test/test_create_issue_context_eval.py::RoundKindCouplingTest")
# The kind a round record carrying no `kind` field is read as — the same permissive
# default `scripts/issue-audit-state.py`'s readers apply to a pre-#793 round.
_ABSENT_KIND_DEFAULT = "discovery"
# The `record-dispatch --round N` marker the state owner writes on the main thread —
# the sole round-boundary source (the state file carries no clock to join on).
#
# Anchored on the state-owner script name so the marker is a CONTRACT rather than a
# bare substring: a BARE `grep record-dispatch`, a BARE `echo record-reopen`, or a `cat`
# of this skill reference no longer opens a spurious round boundary or inflates the
# reopen tally, because none of them carries the script name adjacent to the subcommand.
# ACCEPTED RESIDUAL, stated so neither claim is read wider than it is: the anchor is the
# script NAME, not command position, so an `echo`/`grep` whose text QUOTES the anchored
# pair (`echo "issue-audit-state.py record-reopen"`, `… record-dispatch --round 2 …`)
# does still match — the recognizer cannot tell a quoted command line from a run one.
# The round value is accepted quoted or bare because the skill's rendered fence
# writes `--round "<round>"` (quoted) while the fixtures write it bare — a regex that
# required a bare digit derived NO round boundary on a faithful real transcript.
# The intervening span may cross neither a further state-owner invocation NOR a shell
# command separator (`;`, `&`, `|`, newline), so a `record-dispatch` carrying no
# `--round` of its own cannot borrow the `--round` of a LATER command on the same line
# — including one that is not itself a state-owner invocation
# (`record-dispatch --kind targeted; echo trailing --round 9`), which the
# state-owner-only lookahead alone still admitted.
_DISPATCH_ROUND_RE = re.compile(
    r"issue-audit-state\.py\s+record-dispatch\b"
    r"(?:(?!issue-audit-state\.py)[^\n;&|])*?--round\s+[\"']?(\d+)")
_REOPEN_RE = re.compile(r"issue-audit-state\.py\s+record-reopen\b")


def _digest(text):
    """Stable, salt-independent content digest for byte-identity comparison."""
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()


def _normalize_analysis_text(text):
    if not isinstance(text, str):
        raise TypeError("draft text must be a string")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _heading_name(raw):
    return " ".join(raw.split()).casefold()


# The shipped issue template decorates and qualifies its headings
# (`## 🚫 Blocked — resolve before implementation`), so an exact-literal match
# against `blocked` recognizes no real issue. Strip leading non-word decoration
# and any trailing qualifier introduced by a dash or colon.
_HEADING_DECORATION_RE = re.compile(r"^\W+", re.UNICODE)
_HEADING_QUALIFIER_RE = re.compile(r"\s+[—–-]\s+|:\s+")


def _heading_aliases(raw):
    """Every spelling under which a heading may be recognized by name."""
    full = _heading_name(raw)
    aliases = {full}
    stripped = _HEADING_DECORATION_RE.sub("", full).strip()
    if stripped:
        aliases.add(stripped)
        core = _HEADING_QUALIFIER_RE.split(stripped, maxsplit=1)[0].strip()
        if core:
            aliases.add(core)
    return aliases


def _heading_records(text):
    records = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = _HEADING_RE.match(line)
        if match:
            records.append((index, len(match.group(1)), _heading_name(match.group(2))))
    return lines, records


def _section_extent(lines, records, position):
    start, level, _name = records[position]
    end = len(lines)
    for next_start, next_level, _next_name in records[position + 1:]:
        if next_level <= level:
            end = next_start
            break
    return start, end


def _section_bodies(lines, records):
    """Section body text keyed by every alias its heading is recognized under."""
    bodies = {}
    for position in range(len(records)):
        start, end = _section_extent(lines, records, position)
        body = "\n".join(lines[start + 1:end])
        for alias in _heading_aliases(records[position][2]):
            bodies.setdefault(alias, []).append(body)
    return {alias: "\n".join(parts) for alias, parts in bodies.items()}


def _word_count(text):
    prose_lines = []
    for line in text.splitlines():
        line = re.sub(r"^[ \t]*#{1,6}[ \t]+", "", line)
        line = re.sub(r"^[ \t]*(?:[-+*]|[0-9]+[.)])[ \t]+", "", line)
        prose_lines.append(line)
    return len(_WORD_RE.findall("\n".join(prose_lines)))


def measure_draft(text):
    """Measure one explicitly supplied issue draft without retaining its body."""
    normalized = _normalize_analysis_text(text)
    lines, headings = _heading_records(normalized)
    sections = {}
    for position, (_start, level, name) in enumerate(headings):
        start, end = _section_extent(lines, headings, position)
        body = "\n".join(lines[start + 1:end])
        metric = sections.setdefault(name, {
            "level": level,
            "occurrences": 0,
            "word_count": 0,
            "character_count": 0,
            "item_count": 0,
        })
        metric["level"] = min(metric["level"], level)
        metric["occurrences"] += 1
        metric["word_count"] += _word_count(body)
        metric["character_count"] += len(body)
        metric["item_count"] += sum(1 for line in lines[start + 1:end]
                                     if _LIST_ITEM_RE.match(line))

    paragraphs = []
    for paragraph in re.split(r"\n[ \t]*\n+", normalized):
        folded = " ".join(paragraph.split()).casefold()
        if folded:
            paragraphs.append(folded)
    duplicate_count = sum(
        count - 1 for count in collections.Counter(paragraphs).values() if count > 1
    )
    density = duplicate_count / len(paragraphs) if paragraphs else UNESTABLISHED
    return {
        "word_count": _word_count(normalized),
        "character_count": len(normalized),
        "sections": sections,
        "acceptance_criteria_count": sections.get(
            "acceptance criteria", {"item_count": 0}
        )["item_count"],
        "testing_strategy_count": sections.get(
            "testing strategy", {"item_count": 0}
        )["item_count"],
        "paragraph_count": len(paragraphs),
        "duplicate_paragraph_count": duplicate_count,
        "duplicate_paragraph_density": density,
    }


def _read_explicit_text(path, label):
    try:
        with open(path, "r", encoding="utf-8", newline="") as handle:
            return handle.read()
    except (OSError, UnicodeError) as exc:
        raise ValueError("invalid_checkpoint: {}: {}".format(label, exc)) from exc


def _line_delta(before, after):
    additions = removals = 0
    matcher = difflib.SequenceMatcher(
        None,
        _normalize_analysis_text(before).splitlines(),
        _normalize_analysis_text(after).splitlines(),
        autojunk=False,
    )
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            removals += old_end - old_start
        if tag in ("replace", "insert"):
            additions += new_end - new_start
    return {"additions": additions, "removals": removals}


def measure_checkpoints(run_manifest):
    """Measure initial, revision, and final artifacts from one manifest run."""
    checkpoints = run_manifest.get("checkpoints") if isinstance(run_manifest, dict) else None
    if not isinstance(checkpoints, dict):
        raise ValueError("invalid_checkpoint: checkpoints is not an object")
    revisions = checkpoints.get("revisions")
    if not isinstance(revisions, list):
        raise ValueError("invalid_checkpoint: revisions is not a list")
    paths = [checkpoints.get("initial")] + revisions + [checkpoints.get("final")]
    if any(not isinstance(path, str) or not path for path in paths):
        raise ValueError("invalid_checkpoint: every checkpoint needs a path")
    labels = ["initial"] + ["revision-{}".format(i) for i in range(1, len(revisions) + 1)]
    labels.append("final")
    texts = [_read_explicit_text(path, label) for path, label in zip(paths, labels)]
    metrics = [measure_draft(text) for text in texts]
    changes = []
    for index in range(len(texts) - 1):
        delta = _line_delta(texts[index], texts[index + 1])
        delta.update({"from": labels[index], "to": labels[index + 1]})
        changes.append(delta)
    total_delta = _line_delta(texts[0], texts[-1])
    return {
        "initial": metrics[0],
        "revisions": metrics[1:-1],
        "final": metrics[-1],
        "changes": changes,
        "initial_to_final": {
            "word_growth": metrics[-1]["word_count"] - metrics[0]["word_count"],
            "character_growth": (
                metrics[-1]["character_count"] - metrics[0]["character_count"]
            ),
            "additions": total_delta["additions"],
            "removals": total_delta["removals"],
        },
    }


def _audit_state_owner():
    global _AUDIT_STATE_OWNER
    if _AUDIT_STATE_OWNER is not None:
        return _AUDIT_STATE_OWNER
    spec = importlib.util.spec_from_file_location(
        "create_issue_eval_audit_state_owner", _AUDIT_STATE_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError("audit-state owner is not importable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _AUDIT_STATE_OWNER = module
    return module


def _unestablished_audit(diagnostic):
    impacts = {key: UNESTABLISHED for key in _IMPACT_CLASSES}
    return {
        "status": UNESTABLISHED,
        "diagnostic": diagnostic,
        "first_round_unresolved": UNESTABLISHED,
        "later_finding_identity": {
            "novel": UNESTABLISHED,
            "recurring": UNESTABLISHED,
            "revision_induced": UNESTABLISHED,
        },
        "settled_status_counts": {
            "resolved": UNESTABLISHED,
            "invalidated": UNESTABLISHED,
            "superseded": UNESTABLISHED,
        },
        "final_unresolved": UNESTABLISHED,
        "advisory_by_impact": dict(impacts),
        "invalid_by_impact": dict(impacts),
        "findings_without_usable_evidence": UNESTABLISHED,
        "findings_without_draft_line": UNESTABLISHED,
        "coverage": UNESTABLISHED,
        "final_byte_coverage": UNESTABLISHED,
        "reopened_findings": UNESTABLISHED,
        "scope_escape": {"count": UNESTABLISHED, "unattributable": UNESTABLISHED},
    }


def _impact_counts(state, record_class):
    counts = {key: 0 for key in _IMPACT_CLASSES}
    for rnd in state["rounds"]:
        expected = rnd.get(record_class + "_count")
        records = rnd.get(record_class + "_records")
        if records is None:
            if expected in (None, 0):
                continue
            return {key: UNESTABLISHED for key in _IMPACT_CLASSES}
        for record in records:
            # Fail CLOSED on a class this mirror does not carry: an owner-accepted
            # member absent here must read unestablished, never raise out of
            # `audit_outcomes`' already-returned result.
            key = record.get("impact_class") if isinstance(record, dict) else None
            if key not in counts:
                return {name: UNESTABLISHED for name in _IMPACT_CLASSES}
            counts[key] += 1
    return counts


def audit_outcomes(validated_state, current_digest=None, digest_failed=False):
    """Derive audit semantics only after the state owner's complete validation."""
    if not isinstance(validated_state, dict):
        return _unestablished_audit("state-unavailable")
    try:
        owner = _audit_state_owner()
        slug = validated_state.get("slug")
        state = owner.validate_state_document(copy.deepcopy(validated_state), slug)
    except Exception as exc:  # noqa: BLE001 - unavailable validation is an honest unknown
        return _unestablished_audit(str(exc) or type(exc).__name__)

    completed = owner.completed_rounds(state)
    first_unresolved = UNESTABLISHED
    if completed:
        value = completed[0].get("unresolved_must_revise")
        if isinstance(value, int) and not isinstance(value, bool):
            first_unresolved = value

    ledgers = []
    ledger_missing = False
    for rnd in state["rounds"]:
        findings = rnd.get("findings")
        if isinstance(findings, list):
            ledgers.extend((rnd["round"], entry) for entry in findings)
        elif isinstance(rnd.get("must_revise_count"), int) and rnd["must_revise_count"] > 0:
            ledger_missing = True
    settled = {key: 0 for key in ("resolved", "invalidated", "superseded")}
    for _round_number, entry in ledgers:
        if entry.get("status") in settled:
            settled[entry["status"]] += 1

    convergence = owner.evaluate_convergence(state)
    final_unresolved = convergence.get("effective")
    if final_unresolved is None:
        final_unresolved = UNESTABLISHED

    if ledger_missing:
        missing_evidence = UNESTABLISHED
        missing_draft_line = UNESTABLISHED
    else:
        evidence = state.get("finding_evidence") or {}
        conflicts = owner.evidence_conflicts(evidence)
        missing_evidence = 0
        missing_draft_line = 0
        for round_number, entry in ledgers:
            key = "{}:{}".format(round_number, entry["id"])
            item = evidence.get(key)
            usable = (
                isinstance(item, dict)
                and owner.evidence_completeness(item)[0] == "complete"
                and not conflicts.get(key)
            )
            if not usable:
                missing_evidence += 1
            if not (isinstance(entry.get("quoted_draft_line"), int)
                    and not isinstance(entry.get("quoted_draft_line"), bool)
                    and entry["quoted_draft_line"] >= 1):
                missing_draft_line += 1

    coverage_result = owner.evaluate_coverage(state)
    coverage_round = coverage_result.get("round")
    coverage = {
        "backing": coverage_result["backing"],
        "render": coverage_result["render"],
        "reason": coverage_result.get("reason"),
        "outcomes": {
            entry["key"]: entry["outcome"]
            for entry in ((coverage_round or {}).get("coverage") or [])
        },
    }
    final_byte = owner.evaluate_final_byte_coverage(
        state, current_digest, digest_failed
    )
    projected = {
        rnd["round"]: {
            "kind": rnd.get("kind", _ABSENT_KIND_DEFAULT),
            "scope": rnd.get("scope"),
            "findings": rnd.get("findings") or [],
        }
        for rnd in state["rounds"]
    }
    return {
        "status": "established",
        "diagnostic": None,
        "first_round_unresolved": first_unresolved,
        "later_finding_identity": {
            "novel": UNESTABLISHED,
            "recurring": UNESTABLISHED,
            "revision_induced": UNESTABLISHED,
        },
        "settled_status_counts": settled,
        "final_unresolved": final_unresolved,
        "advisory_by_impact": _impact_counts(state, "advisory"),
        "invalid_by_impact": _impact_counts(state, "invalid"),
        "findings_without_usable_evidence": missing_evidence,
        "findings_without_draft_line": missing_draft_line,
        "coverage": coverage,
        "final_byte_coverage": final_byte["coverage"],
        "reopened_findings": sum(
            1 for _round_number, entry in ledgers if "reopen_provenance" in entry
        ),
        "scope_escape": scope_escape_proxy(projected),
    }


def _validated_rubric(rubric):
    if not isinstance(rubric, dict):
        raise ValueError("invalid_rubric: top level is not an object")
    version = rubric.get("schema_version")
    if version != RUBRIC_SCHEMA_VERSION or isinstance(version, bool):
        raise ValueError("unsupported_rubric_schema_version: {!r}".format(version))
    result = dict(rubric)
    for key in ("required_concepts", "forbidden_concepts"):
        entries = result.get(key)
        if not isinstance(entries, list):
            raise ValueError("invalid_rubric: {} is not a list".format(key))
        for index, entry in enumerate(entries):
            alternatives = entry.get("any_of") if isinstance(entry, dict) else None
            if (not isinstance(entry, dict)
                    or not isinstance(entry.get("text"), str)
                    or not entry["text"].strip()
                    or not isinstance(alternatives, list)
                    or not alternatives
                    or not all(isinstance(value, str) and value.strip()
                               for value in alternatives)):
                raise ValueError("invalid_rubric: {}[{}]".format(key, index))
    for key in ("required_sections", "forbidden_sections"):
        values = result.get(key)
        if (not isinstance(values, list)
                or not all(isinstance(value, str) and value.strip() for value in values)):
            raise ValueError("invalid_rubric: {} is not a string list".format(key))
    for key in ("blocked_expected", "bug_reproduction_expected"):
        if not isinstance(result.get(key), bool):
            raise ValueError("invalid_rubric: {} is not a boolean".format(key))
    alternatives = result.get("bug_reproduction_any_of")
    if (not isinstance(alternatives, list)
            or not all(isinstance(value, str) and value.strip()
                       for value in alternatives)):
        raise ValueError("invalid_rubric: bug_reproduction_any_of is not a string list")
    # A rubric expecting the contract but naming nothing to match would grade every
    # draft as missing it, so refuse it rather than publish a never-satisfiable axis.
    if result["bug_reproduction_expected"] and not alternatives:
        raise ValueError("invalid_rubric: bug_reproduction_any_of is empty")
    return result


# The shipped create-issue template records the reproduction facts as prose inside
# `### Current Behavior` and ships no reproduction-named heading, so a heading-name
# probe graded every conforming bug report as missing the contract. Recognize the
# contract by its rubric-declared evidence in whichever of these sections carries it.
_REPRODUCTION_SECTIONS = (
    "current behavior",
    "reproduction",
    "reproduction steps",
    "bug reproduction",
)


def _reproduction_match(section_bodies, alternatives):
    """The (section, alternative) the reproduction contract is evidenced by, or None."""
    for section in _REPRODUCTION_SECTIONS:
        body = section_bodies.get(section)
        if body is None:
            continue
        folded = " ".join(body.split()).casefold()
        for alternative in alternatives:
            if " ".join(alternative.split()).casefold() in folded:
                return (section, alternative)
    return None


def _grade_assertion(text, passed, evidence):
    return {"text": text, "passed": bool(passed), "evidence": evidence}


def grade_issue(text, rubric):
    """Grade explicit issue bytes with a deterministic schema-1 rubric."""
    rubric = _validated_rubric(rubric)
    normalized = _normalize_analysis_text(text)
    searchable = " ".join(normalized.split()).casefold()
    lines, heading_records = _heading_records(normalized)
    headings = set()
    for _index, _level, name in heading_records:
        headings |= _heading_aliases(name)
    assertions = []
    forbidden_failures = 0
    forbidden_section_failures = 0

    for entry in rubric["required_concepts"]:
        matched = next((alt for alt in entry["any_of"]
                        if " ".join(alt.split()).casefold() in searchable), None)
        assertions.append(_grade_assertion(
            entry["text"],
            matched is not None,
            "matched alternative: {}".format(matched) if matched else "no alternative matched",
        ))
    for entry in rubric["forbidden_concepts"]:
        matched = next((alt for alt in entry["any_of"]
                        if " ".join(alt.split()).casefold() in searchable), None)
        passed = matched is None
        forbidden_failures += int(not passed)
        assertions.append(_grade_assertion(
            entry["text"],
            passed,
            "absent" if passed else "matched forbidden alternative: {}".format(matched),
        ))
    for section in rubric["required_sections"]:
        normalized_section = _heading_name(section)
        passed = normalized_section in headings
        assertions.append(_grade_assertion(
            "Required section: {}".format(section),
            passed,
            "present" if passed else "absent",
        ))
    for section in rubric["forbidden_sections"]:
        normalized_section = _heading_name(section)
        passed = normalized_section not in headings
        forbidden_section_failures += int(not passed)
        assertions.append(_grade_assertion(
            "Forbidden section absent: {}".format(section),
            passed,
            "absent" if passed else "present",
        ))

    blocked_present = "blocked" in headings
    blocked_passed = blocked_present == rubric["blocked_expected"]
    assertions.append(_grade_assertion(
        "Blocked section {}".format(
            "present" if rubric["blocked_expected"] else "absent"
        ),
        blocked_passed,
        "present" if blocked_present else "absent",
    ))
    reproduction_match = _reproduction_match(
        _section_bodies(lines, heading_records), rubric["bug_reproduction_any_of"]
    )
    reproduction_passed = (
        (reproduction_match is not None) == rubric["bug_reproduction_expected"]
    )
    assertions.append(_grade_assertion(
        "Bug reproduction contract {}".format(
            "present" if rubric["bug_reproduction_expected"] else "absent"
        ),
        reproduction_passed,
        "absent" if reproduction_match is None else
        "matched {!r} in section {!r}".format(
            reproduction_match[1], reproduction_match[0]
        ),
    ))
    passed_count = sum(1 for assertion in assertions if assertion["passed"])
    return {
        "schema_version": RUBRIC_SCHEMA_VERSION,
        "passed": passed_count == len(assertions),
        "pass_rate": passed_count / len(assertions),
        "forbidden_failures": forbidden_failures,
        "forbidden_section_failures": forbidden_section_failures,
        "assertions": assertions,
    }


def quality_gate(baseline_grade, candidate_grade):
    """Compare paired formal grades; size and finding counts are intentionally absent."""
    try:
        baseline_rate = baseline_grade["pass_rate"]
        candidate_rate = candidate_grade["pass_rate"]
        baseline_forbidden = baseline_grade["forbidden_failures"]
        candidate_forbidden = candidate_grade["forbidden_failures"]
        baseline_forbidden_sections = baseline_grade["forbidden_section_failures"]
        candidate_forbidden_sections = candidate_grade["forbidden_section_failures"]
        valid = (
            isinstance(baseline_rate, (int, float))
            and not isinstance(baseline_rate, bool)
            and isinstance(candidate_rate, (int, float))
            and not isinstance(candidate_rate, bool)
            and all(isinstance(count, int) and not isinstance(count, bool)
                    for count in (baseline_forbidden, candidate_forbidden,
                                  baseline_forbidden_sections,
                                  candidate_forbidden_sections))
        )
    except (KeyError, TypeError):
        valid = False
    if not valid:
        return {
            "status": UNESTABLISHED,
            "passed": False,
            "pass_rate_preserved": UNESTABLISHED,
            "new_forbidden_failures": UNESTABLISHED,
            "new_forbidden_sections": UNESTABLISHED,
            "efficiency_eligible": False,
        }
    rate_preserved = candidate_rate >= baseline_rate
    new_forbidden = max(0, candidate_forbidden - baseline_forbidden)
    # Gate forbidden SECTIONS separately from the aggregate pass_rate: a new
    # section failure offset by a newly-satisfied required concept leaves
    # pass_rate flat, so folding it into rate_preserved credits a worse issue.
    new_forbidden_sections = max(
        0, candidate_forbidden_sections - baseline_forbidden_sections)
    passed = rate_preserved and new_forbidden == 0 and new_forbidden_sections == 0
    return {
        "status": "established",
        "passed": passed,
        "pass_rate_preserved": rate_preserved,
        "new_forbidden_failures": new_forbidden,
        "new_forbidden_sections": new_forbidden_sections,
        "efficiency_eligible": passed,
    }


def _median(values):
    """Deterministic median of a NON-EMPTY list of numbers.

    Refuses an empty population rather than returning 0 (issue #1899), matching both
    sibling instruments: an unestablished measurement is never collapsed onto a real
    value. Call `_median_or_unestablished` for a possibly-empty population.
    """
    if not values:
        raise ValueError("median of an empty population")
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    # Even count: mean of the two central values. Keep an int when it divides
    # evenly so the output stays byte-stable across runs.
    lo, hi = ordered[mid - 1], ordered[mid]
    total = lo + hi
    return total // 2 if total % 2 == 0 else total / 2


def _is_numeric(value):
    """True for a real number. Both context guards read this one predicate.

    A separate re-derivation in either caller drifts from the other, which is how one
    arithmetic site ends up guarded and its sibling raises `TypeError` instead of reporting
    `unestablished`. `isinstance(True, int)` is True, so booleans are excluded here.
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _median_or_unestablished(values):
    """The median of a non-empty list, else the UNESTABLISHED sentinel.

    Never 0 for an empty population: an axis with no established operand reports
    `unestablished`, never a real value it did not measure.
    """
    return _median(values) if values else UNESTABLISHED


RESIDENCY_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def _usage_value(usage, key):
    """One usage sub-field's ESTABLISHED token count on the RESIDENCY axis, or None.

    None covers absent, null, bool, non-numeric and non-finite values — the residency
    axis reports an unmeasured field as unestablished, never a spurious 0 (issue #1899).
    The single source of the sub-field validity guard; `_usage_field` reads the SAME fields
    on the spend axis, coalescing this reader's None to a summable 0.
    """
    if not isinstance(usage, dict):
        return None
    val = usage.get(key)
    if isinstance(val, bool):  # bool is an int subclass; never a token count
        return None
    if isinstance(val, (int, float)):
        # json.loads accepts bare Infinity/NaN and int(inf) raises OverflowError, so guard
        # non-finite here rather than in eval_corpus's per-record backstop tuple (#1899).
        if isinstance(val, float) and not math.isfinite(val):
            return None
        return int(val)
    return None


def _usage_field(usage, key):
    """Read one usage sub-field on the SPEND axis: an unmeasured field is a summable 0.

    Always a number: the spend axis (`_auditor_cost`, `total_output_tokens`) sums these,
    so it must never see None. Shares `_usage_value`'s validity guard (issue #1899) — the
    two axes differ only in how they report an unmeasured field (0 here, None there), never
    in which fields they establish.
    """
    val = _usage_value(usage, key)
    return 0 if val is None else val


def _context_tokens(usage):
    """Main-thread residency = input + cache_read + cache_creation (no output), or None.

    None when NO residency sub-field carried an established count: an empty, all-null, or
    otherwise unusable `usage` object measured nothing, and folding its 0 into the peak
    would report an unmeasured turn as a real-looking 0 (issue #1899). This is the
    RESIDENCY axis (`observe_assistant`); the spend axis is `_auditor_cost`.
    """
    established = [v for v in (_usage_value(usage, k) for k in RESIDENCY_KEYS)
                   if v is not None]
    return sum(established) if established else None


def _residency_spend(usage):
    """The three residency sub-fields summed on the SPEND axis (each unmeasured -> 0).

    The inner residency term of `_auditor_cost`. It stays a number even for an unmeasured
    turn, so the spend axis is never handed a None — keeping auditor cost whole while the
    residency axis reports unestablished (issue #1899's file-scoped entanglement).
    """
    return sum(_usage_field(usage, key) for key in RESIDENCY_KEYS)


def _auditor_cost(usage):
    """The auditor's per-turn cost = every token the sidechain turn consumed.

    A SPEND measurement: the auditor's own output is part of the cost #793 buys down, so
    output_tokens is included here (it is excluded from the main-thread residency axis).
    Sums via `_residency_spend`, never `_context_tokens`, because the residency reader can
    return None (issue #1899) and this axis must stay arithmetic.
    """
    return _residency_spend(usage) + _usage_field(usage, "output_tokens")


def _tool_result_text(block):
    """Extract the resident string a tool_result carries, or None when it is
    absent / truncated / errored / not fully resident (fail-closed comparand).

    The redundant-repeated-Read metric must fail CLOSED — an occurrence we are not
    certain carries fully-resident, authoritative bytes is treated as authoritative
    (returns None, counted as a fresh read), never folded into the redundant count.
    We recognize the documented non-authoritative markers `truncated: true` and
    `is_error: true`; the exact shape a Claude Code transcript uses to flag a
    truncated Read result is NOT authoritatively established here, so any OTHER
    truncation encoding is an accepted residual (documented, not silently assumed).
    Because an unrecognized-but-truncated result that happened to repeat byte-for-byte
    could inflate the redundant count, we keep this recognized-marker set conservative
    and additive: a new confirmed marker is added here, never removed.
    """
    if not isinstance(block, dict):
        return None
    # An explicit truncation or error marker makes the content non-authoritative.
    if block.get("truncated") is True or block.get("is_error") is True:
        return None
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                else:
                    return None
            else:
                # A non-text block (image, an unrecognized shape) means we cannot
                # assert byte-identity over the whole result: fail closed.
                return None
        return "".join(parts) if parts else None
    return None


class RunAccumulator:
    """Streams one session file's records and accumulates one run's metrics.

    Holds only bounded per-record state — token tallies, sets of content/large-block
    hashes (not the record bodies themselves), a pending tool_use_id -> file_path
    map, and the per-round auditor-cost tally. It never retains full record bodies
    (the streaming property); the hash/pending structures still grow with the count
    of distinct session content, so this is bounded-per-record, not constant memory.
    """

    def __init__(self, source, large_block_chars):
        self.source = source
        self.large_block_chars = large_block_chars
        self.turn_count = 0
        self.per_turn_context = []
        # Attributed main-thread turns whose residency was never established (no usage
        # object, an empty/all-null one, or a non-finite count). Tallied rather than
        # folded into per_turn_context as a 0, which would drag the peak down (issue #1899).
        self.usage_missing_turns = 0
        self.total_output_tokens = 0
        self.compact_boundary_count = 0
        self.repeated_read_count = 0
        self.reemission_count = 0
        self.attributed = False
        # Round boundaries are derived from the transcript's own record-dispatch
        # markers (issue #889): the most recent `--round N` marker names the round a
        # subsequent sidechain (auditor) turn is attributed to.
        self.current_round = None
        self.dispatch_rounds = set()         # rounds seen (deduped; order is irrelevant)
        self.round_auditor_cost = {}         # round_num -> total auditor token cost
        self.unrounded_auditor_cost = 0      # sidechain cost before any dispatch marker
        # Every sidechain assistant record seen, WHETHER OR NOT it carried the
        # attribution — the operand that makes the module docstring's unverified
        # `attributionSkill`-on-sidechain assumption falsifiable from the emitted
        # report rather than only from a human remembering the docstring.
        self.sidechain_records_seen = 0
        self.sidechain_records_attributed = 0
        self.record_reopen_count = 0         # escaped-defect proxy 1
        # tool_use_id -> file_path for pending Read calls awaiting their result.
        self._pending_reads = {}
        # file_path -> set of content hashes already resident for that path.
        self._read_content = {}
        # hashes of large blocks already produced (assistant output or resident
        # tool_result) — the "already-resident" set the re-emission metric checks.
        self._produced_blocks = set()

    def observe_system(self, record):
        if record.get("subtype") == "compact_boundary":
            self.compact_boundary_count += 1

    def observe_user(self, record):
        """A user record may carry tool_result blocks (a Read's returned bytes)."""
        message = record.get("message")
        if not isinstance(message, dict):
            return
        content = message.get("content")
        if not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            tool_use_id = block.get("tool_use_id")
            path = self._pending_reads.pop(tool_use_id, None)
            if path is None:
                continue
            text = _tool_result_text(block)
            if text is None:
                # Fail closed: content absent/truncated -> authoritative, the
                # repeated-Read metric records nothing for this occurrence.
                continue
            digest = _digest(text)
            seen = self._read_content.setdefault(path, set())
            if digest in seen:
                # A repeat of already-resident, byte-identical content.
                self.repeated_read_count += 1
            else:
                seen.add(digest)
            # A large resident tool_result counts as already-produced content, so a
            # later assistant re-quotation of it is a re-emission.
            if len(text) >= self.large_block_chars:
                self._produced_blocks.add(digest)

    def _observe_sidechain(self, record):
        """Attribute one auditor (sidechain) turn's cost to the current round.

        The sidechain record is NOT a main-thread turn: it never sets `attributed`
        (a session of only sidechain turns yields no run), never increments
        `turn_count`, and never touches the residency (context) axis — it feeds only
        the round-attributed auditor-cost tally.
        """
        self.sidechain_records_seen += 1
        if record.get("attributionSkill") not in ATTRIBUTION:
            return
        self.sidechain_records_attributed += 1
        message = record.get("message")
        if not isinstance(message, dict):
            message = {}
        cost = _auditor_cost(message.get("usage"))
        if self.current_round is None:
            # A sidechain turn before any dispatch marker cannot be keyed to a round;
            # it is held separately, never silently folded into round 1.
            self.unrounded_auditor_cost += cost
        else:
            self.round_auditor_cost[self.current_round] = (
                self.round_auditor_cost.get(self.current_round, 0) + cost
            )

    def _observe_markers(self, block_input):
        """Scan one main-thread Bash tool_use for round-boundary / reopen markers.

        Every occurrence is counted, not just the first: a compound command carrying
        two `record-reopen` invocations spends two reopens, and a `search`-based tally
        would silently under-report escaped-defect proxy 1 by one. Likewise the round
        boundary the command leaves open is its LAST dispatch marker, not its first.
        """
        if not isinstance(block_input, dict):
            return
        command = block_input.get("command")
        if not isinstance(command, str):
            return
        for m in _DISPATCH_ROUND_RE.finditer(command):
            rnd = int(m.group(1))
            self.current_round = rnd
            self.dispatch_rounds.add(rnd)
        self.record_reopen_count += sum(1 for _ in _REOPEN_RE.finditer(command))

    def observe_assistant(self, record):
        if record.get("isSidechain") is True:
            self._observe_sidechain(record)
            return
        if record.get("attributionSkill") not in ATTRIBUTION:
            return
        self.attributed = True
        self.turn_count += 1
        # A truthy non-dict `message` (a JSON array/string) would make `.get()` raise;
        # `(x or {})` only rescues a FALSY value, so guard with isinstance (mirroring
        # observe_user) — a well-typed-but-wrong-shape record degrades cleanly.
        message = record.get("message")
        if not isinstance(message, dict):
            message = {}
        usage = message.get("usage")
        residency = _context_tokens(usage)
        if residency is None:
            # Residency was never established for this turn — tally it rather than folding
            # a 0 into the peak, which would report an unmeasured turn as a real value.
            self.usage_missing_turns += 1
        else:
            self.per_turn_context.append(residency)
        self.total_output_tokens += _usage_field(usage, "output_tokens")

        content = message.get("content")
        if not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "tool_use" and block.get("name") == "Read":
                # A Read block's `input` may be a non-dict (a list/string); `(x or {})`
                # passes a truthy non-dict through to `.get()` and raises. isinstance-guard.
                block_input = block.get("input")
                if not isinstance(block_input, dict):
                    block_input = {}
                file_path = block_input.get("file_path")
                tool_use_id = block.get("id")
                if isinstance(file_path, str) and tool_use_id is not None:
                    self._pending_reads[tool_use_id] = file_path
            elif btype == "tool_use" and block.get("name") == "Bash":
                # The main-thread state-owner invocations that mark round boundaries
                # (record-dispatch) and reopen events (record-reopen) — issue #889.
                self._observe_markers(block.get("input"))
            elif btype == "text":
                text = block.get("text")
                if not isinstance(text, str) or len(text) < self.large_block_chars:
                    continue
                digest = _digest(text)
                if digest in self._produced_blocks:
                    # An assistant re-statement of already-produced large content.
                    self.reemission_count += 1
                else:
                    self._produced_blocks.add(digest)

    def result(self):
        """The run record's own fields.

        NOT the complete field set of a run record as a report consumer sees it:
        `_join_round_kinds` injects two further keys, `round_kinds` and `round_reasons`
        (issue #1103), after `eval_corpus` returns. Every reader of a run record therefore
        reads both defensively (`.get`), because a run record taken straight from this
        method has not been through the join.
        """
        # UNESTABLISHED (never 0) when no turn established residency: a real-looking 0
        # here is the unknown-onto-zero collapse this instrument guards against (#1899).
        peak = max(self.per_turn_context) if self.per_turn_context else UNESTABLISHED
        final = self.per_turn_context[-1] if self.per_turn_context else UNESTABLISHED
        round_cost = {n: self.round_auditor_cost[n]
                      for n in sorted(self.round_auditor_cost)}
        return {
            "source": self.source,
            "turn_count": self.turn_count,
            # Main-thread residency (SECONDARY axis, issue #889 — never the sole
            # basis of the reduction claim).
            "peak_context": peak,
            "final_context": final,
            # Attributed turns whose residency was never established (issue #1899).
            "usage_missing_turns": self.usage_missing_turns,
            "total_output_tokens": self.total_output_tokens,
            "compact_boundary_count": self.compact_boundary_count,
            "repeated_read_count": self.repeated_read_count,
            "reemission_count": self.reemission_count,
            # Round-attributed auditor cost (PRIMARY axis, issue #889).
            "round_auditor_cost": round_cost,
            "unrounded_auditor_cost": self.unrounded_auditor_cost,
            "sidechain_records_seen": self.sidechain_records_seen,
            "sidechain_records_attributed": self.sidechain_records_attributed,
            "attributed_auditor_cost": sum(round_cost.values()) + self.unrounded_auditor_cost,
            "dispatch_rounds": sorted(self.dispatch_rounds),
            "record_reopen_count": self.record_reopen_count,
        }


def _iter_session_files(corpus_root, skipped):
    """Yield JSONL session file paths under the corpus root, deterministically.

    Skips any entry whose real path escapes the corpus root (a symlink out), so the
    eval never reads outside the supplied directory. Sorted for determinism.

    Both walk-level drops are TALLIED and breadcrumbed, never silent (mirroring the
    per-record and unreadable-file skip discipline): a `.jsonl` whose real path
    escapes the corpus root is counted under `escaped_path`, and a directory-walk
    error (a permission-denied dir, a vanished tree) is counted under `walk_error`
    via the `os.walk` `onerror` callback — default `onerror=None` would swallow it.
    """
    root_real = os.path.realpath(corpus_root)
    collected = []

    def _on_walk_error(exc):
        # A directory os.walk could not descend (permissions, a race deletion): tally
        # and breadcrumb so the aggregate is never silently computed over a corpus the
        # walk under-enumerated. `exc.filename` names the offending directory.
        skipped["walk_error"] += 1
        sys.stderr.write(
            "warning: skipping unwalkable corpus directory {}: {}\n".format(
                getattr(exc, "filename", "?"), exc
            )
        )

    for dirpath, dirnames, filenames in os.walk(corpus_root, onerror=_on_walk_error):
        dirnames.sort()
        for name in sorted(filenames):
            if not name.endswith(".jsonl"):
                continue
            full = os.path.join(dirpath, name)
            real = os.path.realpath(full)
            if real != root_real and not real.startswith(root_real + os.sep):
                # A symlink (or other entry) whose real path escapes the corpus root:
                # never read, but tally + breadcrumb so the drop is visible, not silent.
                skipped["escaped_path"] += 1
                sys.stderr.write(
                    "warning: skipping session file escaping corpus root {}\n".format(
                        full
                    )
                )
                continue
            collected.append(full)
    collected.sort()
    return collected


def eval_corpus(corpus_root, large_block_chars=LARGE_BLOCK_MIN_CHARS):
    """Return (runs, skipped) for a corpus directory.

    runs: list of per-run metric dicts (only sessions with attributed turns).
    skipped: dict of {reason: count} of malformed records the parser stepped over.
    """
    runs = []
    skipped = {
        "non_json_line": 0,
        "not_object": 0,
        "no_type": 0,
        "unreadable_file": 0,
        "escaped_path": 0,
        "walk_error": 0,
        "malformed_record": 0,
        # A session file carrying auditor (sidechain) records but NO main-thread
        # attributed turn. `if acc.attributed` drops such a file whole, taking its
        # sidechain cost AND its `sidechain_records_seen` with it — and that counter is
        # the operand the module docstring's unverified "does the harness stamp
        # `attributionSkill` on a sidechain record?" assumption is meant to be
        # falsifiable from. Dropping it silently is exactly the layout where the
        # assumption is most likely wrong, so the drop is tallied and breadcrumbed.
        "sidechain_only_file": 0,
    }
    for session_file in _iter_session_files(corpus_root, skipped):
        acc = RunAccumulator(os.path.basename(session_file), large_block_chars)
        try:
            handle = open(session_file, "r", encoding="utf-8", errors="replace")
        except OSError as exc:
            # A session file we enumerated but cannot open (permissions, a broken
            # symlink, a vanished file) is a dropped run: tally it and breadcrumb so
            # the aggregate is never silently computed over an under-counted corpus,
            # mirroring the per-record skip discipline below.
            skipped["unreadable_file"] += 1
            sys.stderr.write(
                "warning: skipping unreadable session file {}: {}\n".format(
                    session_file, exc
                )
            )
            continue
        with handle:
            for line in handle:  # streaming: one record at a time, never buffered
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                # Do not narrow, here or at the sibling decode sites: on the
                # recursive-decoder Pythons in the supported range (< 3.14) a
                # deeply-nested document raises `RecursionError`, a `RuntimeError`.
                except Exception:  # noqa: BLE001 - skip the record, never detonate
                    skipped["non_json_line"] += 1
                    continue
                if not isinstance(record, dict):
                    skipped["not_object"] += 1
                    continue
                rtype = record.get("type")
                if rtype is None:
                    skipped["no_type"] += 1
                    continue
                # Defensive backstop: the observers isinstance-guard their known field
                # shapes, but a record shape not anticipated here must degrade per-record
                # (tallied + breadcrumbed), never detonate the whole corpus walk. This is
                # what makes the module docstring's "without detonating" guarantee true.
                try:
                    if rtype == "assistant":
                        acc.observe_assistant(record)
                    elif rtype == "user":
                        acc.observe_user(record)
                    elif rtype == "system":
                        acc.observe_system(record)
                except (AttributeError, TypeError, ValueError, KeyError) as exc:
                    skipped["malformed_record"] += 1
                    sys.stderr.write(
                        "warning: skipping malformed record in {}: {}\n".format(
                            session_file, exc
                        )
                    )
                    continue
        if acc.attributed:
            runs.append(acc.result())
        elif acc.sidechain_records_seen:
            # Sidechain records but no main-thread attributed turn: a dropped run whose
            # auditor cost the aggregate will never see. Tally + breadcrumb so an
            # under-counted corpus is visible in `skipped` (and degrades the paired
            # delta) rather than reading as a clean measurement.
            skipped["sidechain_only_file"] += 1
            sys.stderr.write(
                "warning: skipping session file with sidechain records but no "
                "main-thread attributed turn {} ({} sidechain record(s), {} "
                "attributed)\n".format(
                    session_file, acc.sidechain_records_seen,
                    acc.sidechain_records_attributed,
                )
            )
    runs.sort(key=lambda r: r["source"])
    return runs, skipped


# ── State-file reader (issue #889) — best-effort, never a number on a bad shape ──

def _degraded_state(state_path, reason):
    """Emit the degraded-read breadcrumb and return the None sentinel.

    Every degraded arm routes through here so an operator who supplied a path can tell
    "I passed nothing" from "the path I passed could not be used" — without it a
    mistyped `--state-file` is byte-identical in output to omitting the flag, and the
    honest `unestablished` reads as a disclosure about the data rather than about the
    operator's own typo. `state_path` is falsy only on the omitted-flag arm, which is
    not a degradation and emits nothing.
    """
    if state_path:
        sys.stderr.write(
            "create-issue-context-eval: state file {} not usable ({}); "
            "every state-derived figure reads {}\n".format(
                state_path, reason, UNESTABLISHED))
    return None


def read_state(state_path):
    """Read one audit state file's round labelling, best-effort.

    Returns a dict {round_num(int): {"kind": str, "kind_reason": str, "scope": dict|None,
    "findings": list}} on success, or None when the state file is absent, unreadable,
    undecodable, empty, malformed, carries a wrong-typed `rounds` container, or carries
    a round whose PRESENT kind is outside `ROUND_KINDS`. A None return makes every
    per-kind and scope-escape figure read `unestablished` — never a number and never a
    crash (AC8); every degraded arm also writes a stderr breadcrumb naming the path and
    the reason.

    An ABSENT `kind` is NOT a degradation: `scripts/issue-audit-state.py` accepts a
    round record carrying none (a pre-#793 round) and its readers default it to
    `discovery`, so this reader applies the same default rather than collapsing a whole
    otherwise-valid state file over one legacy round.

    The state file supplies ONLY what the transcript cannot: the round→kind
    labelling, the per-round scope, and the per-finding quoted draft line. It carries
    no time or ordering coordinate — round boundaries come from the transcript alone
    (this module imports no time facility), so there is no join to attempt here.

    **CONTRACT for consumers: `None` and `{}` are different answers and truthiness does
    not distinguish them.** `None` means the state was never established (every
    state-derived figure reads `unestablished`); `{}` means it WAS established and
    records no rounds (`state_established: True`, `finding_count: 0`, an established
    scope-escape `0`). Both are falsy, so every consumer here tests `state is None` —
    a `if state:` test would silently reclassify a legitimately-empty state as
    unestablished, republishing the unknown-collapse this reader exists to prevent.
    `StateNoneVsEmptyContractTest` in the test module pins both readings.
    """
    if not state_path:
        return None
    try:
        with open(state_path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    # UnicodeDecodeError is a ValueError, NOT an OSError: a state file carrying any
    # non-UTF-8 byte is squarely inside AC8's "unreadable" shape and must degrade here,
    # never propagate out of the instrument as a traceback.
    except (OSError, ValueError) as exc:
        return _degraded_state(state_path, "unreadable: {}".format(exc))
    if not raw.strip():
        return _degraded_state(state_path, "empty")
    try:
        doc = json.loads(raw)
    # Deliberately broad. `json.loads` does NOT raise only ValueError/TypeError: a
    # deeply-nested document exhausts the decoder's recursion and raises
    # `RecursionError`, which inherits from `RuntimeError` and would escape a
    # (ValueError, TypeError) clause as an uncaught traceback — falsifying AC8's "never
    # a crash" on precisely the hand-corrupted input this reader exists to survive.
    # Enumerating the escape hatches one at a time is how the next unanticipated
    # exception type gets out, so the clause is residual rather than a list.
    except Exception as exc:  # noqa: BLE001 - AC8 fail-closed: degrade, never crash
        return _degraded_state(state_path, "not parseable JSON: {}".format(exc))
    if not isinstance(doc, dict):
        return _degraded_state(state_path, "top level is not an object")
    rounds = doc.get("rounds")
    if not isinstance(rounds, list):
        return _degraded_state(state_path, "`rounds` is not a list")
    by_num = {}
    for rnd in rounds:
        if not isinstance(rnd, dict):
            return _degraded_state(state_path, "a round record is not an object")
        num = rnd.get("round")
        if not isinstance(num, int) or isinstance(num, bool):
            return _degraded_state(
                state_path, "a round carries no integer round number")
        if num in by_num:
            # Last-wins would silently DISCARD a round record. That is not a lossy
            # nicety: the scope-escape proxy keys its whole fail-closed design on "is
            # there any targeted round?", so a duplicated number whose first record is
            # `targeted` and whose second is `discovery` loses the targeted scope and
            # the proxy then reports an established `0` — the value that reads as "no
            # defects escaped scope" about a comparison that never ran.
            return _degraded_state(
                state_path, "round {} is recorded more than once".format(num))
        kind = rnd.get("kind")
        if kind is None:
            kind = _ABSENT_KIND_DEFAULT
        elif kind not in ROUND_KINDS:
            # A PRESENT-but-unmirrored kind collapses the whole labelling to
            # unestablished rather than silently reporting a partial per-kind figure.
            return _degraded_state(
                state_path,
                "round {} names the unrecognized kind {!r}".format(num, kind))
        # issue #1103 — the round-kind selecting reason, read alongside the kind. Unlike
        # `kind` (whose absent default of `discovery` is the truthful one — a pre-#793
        # round genuinely WAS a whole-draft derivation), an absent reason has no truthful
        # default: a round that recorded no reason has an UNESTABLISHED one, never a
        # guessed value. A present-but-non-string reason is likewise unestablished rather
        # than a coerced value. This reader deliberately does NOT mirror the closed reason
        # vocabulary from the state owner (as it must for `kind`, whose membership drives a
        # whole-state collapse): the reason is a disclosure field, so an unrecognized
        # string is surfaced verbatim rather than collapsing the state — the state owner's
        # `_validate` is the boundary that refuses an off-vocabulary reason on load.
        reason = rnd.get("kind_reason")
        if not isinstance(reason, str) or not reason:
            reason = UNESTABLISHED
        scope = rnd.get("scope") if isinstance(rnd.get("scope"), dict) else None
        # A PRESENT-but-non-list `findings` is a corrupt container, not an empty one.
        # Coercing it to `[]` would make `finding_count` publish a real `0` ("the audit
        # recorded no findings") about a ledger that was never read, with
        # `state_established` reporting True and no breadcrumb — the exact
        # unknown-collapsed-onto-zero shape every sibling arm here refuses. An ABSENT
        # `findings` stays legal-and-empty: `scripts/issue-audit-state.py` writes the key
        # only once a round records a ledger, so a round with none genuinely has none.
        findings = rnd.get("findings")
        if findings is None:
            findings = []
        elif not isinstance(findings, list):
            return _degraded_state(
                state_path, "round {} `findings` is not a list".format(num))
        by_num[num] = {"kind": kind, "kind_reason": reason, "scope": scope,
                       "findings": findings}
    return by_num


def _scope_draft_span(scope):
    """The [start, end] draft-line span a round's scope declares, or None.

    Draft-space coordinates (issue #889): the scope-escape proxy compares two
    coordinates in the DRAFT's own space, so the operand is a draft-line span, not a
    repository path:line.

    The producer landed in issue #1105: `scripts/issue-audit-state.py`'s `record-dispatch`
    now composes a targeted round's scope as `{basis_digest, sections, claim_ids,
    draft_lines}`, where `draft_lines` is the convex-hull draft-line span over the changed
    sections. So a targeted round dispatched under that code fills this function with a real
    span and `scope_escape_proxy` reports an integer. This reader is unchanged and stays
    strict: a scope with no `draft_lines` (a pre-#1105 round), a wrong-typed value, a
    non-two-element list, a bool-carrying element, or an inverted span all still return
    `None`, so the proxy stays at its honest `unestablished` rather than reporting the value
    that reads as "nothing escaped".
    """
    if not isinstance(scope, dict):
        return None
    span = scope.get("draft_lines")
    if (isinstance(span, list) and len(span) == 2
            and all(isinstance(x, int) and not isinstance(x, bool) for x in span)
            and span[0] <= span[1]):
        return (span[0], span[1])
    return None


def _finding_draft_line(finding):
    """The draft line a finding quoted as the line it attacks, or None (unattributable).

    Accepts exactly what `scripts/issue-audit-state.py` accepts at BOTH its own
    boundaries for this field — a non-bool int `>= 1`. A re-derived, wider predicate
    (any non-bool int, admitting `0` and negatives) would treat a hand-edited `-5` as
    attributable and silently shrink the honest denominator, the accepted-set-drift the
    repo's share-the-contract rule exists to stop.
    """
    if not isinstance(finding, dict):
        return None
    q = finding.get("quoted_draft_line")
    if isinstance(q, int) and not isinstance(q, bool) and q >= 1:
        return q
    return None


# The ledger status a must-revise finding carries while it is still outstanding. AC9
# scopes the scope-escape proxy to must-revise findings, and every other member of the
# vocabulary is a SETTLED status — counting one would report a scope escape the round
# itself already disposed of, and would also inflate the unattributable denominator.
#
# Mirrors `_LEDGER_STATUSES` in scripts/issue-audit-state.py, and — like `ROUND_KINDS`
# above — the mirror is RECONCILED by the test named in
# `LEDGER_STATUS_COUPLING_ASSERTED_BY`, not merely asserted here: without that, a fifth
# status added to the owner would be read as outstanding by `_is_outstanding_must_revise`
# and would silently inflate both the escape count and its denominator. The settled set
# is derived as the owner's vocabulary MINUS this member, never re-listed here — a
# hand-copied enumeration is the drift this reconciliation exists to stop.
_UNRESOLVED_STATUS = "unresolved"
LEDGER_STATUS_COUPLING_ASSERTED_BY = (
    "lib/test/test_create_issue_context_eval.py::RoundKindCouplingTest")


def _is_outstanding_must_revise(finding):
    """True for a ledger entry that is still an outstanding must-revise finding."""
    return (isinstance(finding, dict)
            and finding.get("status") == _UNRESOLVED_STATUS)


def scope_escape_proxy(state):
    """The scope-escape proxy and its own denominator (AC9 proxy 2 + AC11).

    Returns {"count": int|UNESTABLISHED, "unattributable": int|UNESTABLISHED} where
    `count` is the number of later-round OUTSTANDING must-revise findings whose quoted
    draft line falls inside an earlier `targeted` round's recorded draft-space scope,
    and `unattributable` is the denominator: later-round outstanding must-revise
    findings carrying NO recorded draft line. An unattributable finding is never counted
    as attributable and never counted as zero.

    Both figures read `unestablished` — never `0` — whenever the comparand cannot be
    established: no state at all, or ANY `targeted` round whose scope yields no usable
    draft-line span. As of issue #1105 `record-dispatch` writes `scope.draft_lines` (see
    `_scope_draft_span`), so a targeted round dispatched under that code IS fillable and the
    proxy reports an integer; the second arm still fires for a pre-#1105 round, or a span
    that is wrong-typed or inverted, so a partial comparison never launders into a
    real-looking number. A state carrying NO targeted round at all is a different case —
    nothing could escape a scope that was never dispatched — and that is a genuine,
    established `0`.
    """
    if state is None:
        return {"count": UNESTABLISHED, "unattributable": UNESTABLISHED}
    targeted = []  # (round_num, start, end)
    for num, rnd in state.items():
        if rnd.get("kind") != "targeted":
            continue
        span = _scope_draft_span(rnd.get("scope"))
        if span is None:
            # A targeted round whose span is absent, wrong-typed or inverted makes the
            # whole comparison partial. Fail the WHOLE proxy to unestablished rather
            # than dropping the round silently and emitting a real-looking integer.
            return {"count": UNESTABLISHED, "unattributable": UNESTABLISHED}
        targeted.append((num, span[0], span[1]))
    count = 0
    unattributable = 0
    for num, rnd in state.items():
        earlier_targeted = [(s, e) for t_num, s, e in targeted if t_num < num]
        if not earlier_targeted:
            continue  # not a "later round" relative to any targeted scope
        for finding in rnd.get("findings") or []:
            if not _is_outstanding_must_revise(finding):
                continue
            line = _finding_draft_line(finding)
            if line is None:
                unattributable += 1
                continue
            if any(s <= line <= e for s, e in earlier_targeted):
                count += 1
    return {"count": count, "unattributable": unattributable}


def per_kind_medians(runs, state):
    """Median attributed auditor cost per round kind across the runs (AC6).

    A round contributes its attributed cost to its kind's population only when the
    state file established that kind; with no state (or a degraded one) every per-kind
    figure reads `unestablished`.

    A transcript round the state file does not label makes EVERY per-kind median
    `unestablished` — never a confident median over the labelled subset. Dropping such
    a round silently would publish a real number computed from a knowingly-partial
    population: a state covering only round 1 of a three-round corpus would move the
    discovery median from the true 94500 to 139000, with nothing in the report saying
    the other two rounds were never labelled. `_join_round_kinds` already marks those
    rounds `unestablished` on the per-run breakdown; this is the aggregate acting on
    the same fact instead of averaging past it.
    """
    if state is None:
        return {k: UNESTABLISHED for k in ROUND_KINDS}
    buckets = {k: [] for k in ROUND_KINDS}
    for run in runs:
        for rnum, cost in run["round_auditor_cost"].items():
            rnd = state.get(rnum)
            if rnd is None or rnd.get("kind") not in buckets:
                return {k: UNESTABLISHED for k in ROUND_KINDS}
            buckets[rnd["kind"]].append(cost)
    return {k: _median_or_unestablished(buckets[k]) for k in ROUND_KINDS}


def aggregate(runs, state=None):
    """The exactly-these-fields aggregate summary, complete by construction.

    `state` (issue #889) supplies the round→kind labelling the per-kind medians need;
    absent or degraded state makes those figures `unestablished` (never a number).

    **One convention across every RUN-DERIVED field.** On an empty run population every
    figure computed from `runs` reads `unestablished`, secondary residency axis included
    — a reader must never have to know which run-derived field they are looking at to
    tell "measured zero" from "no population". `run_count` is the one deliberate
    exception: `0` is its measurement, not a collapsed unknown.

    **The state-derived fields are NOT run-derived and do not follow that convention.**
    `state_established`, `finding_count`, `scope_escape_count` and
    `scope_escape_unattributable` answer the STATE file, whose establishment is
    independent of the run population: `aggregate([], <valid state>)` therefore returns
    a real `finding_count`, a real scope-escape pair and `state_established: True`, and
    that is correct — the state WAS read. Their own unknown-collapse guard is the state
    sentinel (`_finding_count` / `scope_escape_proxy` return `UNESTABLISHED` on an
    absent or degraded state), not the run count. They live here rather than beside the
    summary so the canonical-field-order completeness property (and the renderer that
    iterates it) covers them too, and so `state_established` is DERIVED from the
    sentinel rather than re-answered from the same operand a second way.
    """
    # Exclude UNESTABLISHED peaks (unmeasured-residency runs) from the peak population —
    # never coerce them to 0, and never let the sentinel string reach max()/_median()/the
    # over-threshold comparisons, which would raise on a mixed int/str list (issue #1899).
    peaks = [r["peak_context"] for r in runs if r["peak_context"] != UNESTABLISHED]
    medians = per_kind_medians(runs, state)
    escape = scope_escape_proxy(state)
    finding_count = _finding_count(state)
    return {
        "run_count": len(runs),
        # Whether the state file was established at all — derived from the sentinel the
        # one reader already produced, never re-answered from `state` independently.
        "state_established": finding_count is not UNESTABLISHED,
        # Total ledger entries across the state's rounds (state-derived axis).
        "finding_count": finding_count,
        # Attributed turns across the corpus whose residency was never established
        # (issue #1899). UNESTABLISHED on an empty run population, like every run-derived
        # figure here — never a real-looking 0 about a corpus that was never measured.
        "total_usage_missing_turns": (sum(r["usage_missing_turns"] for r in runs)
                                      if runs else UNESTABLISHED),
        # Secondary residency axis.
        "median_peak_context": _median_or_unestablished(peaks),
        "max_peak_context": max(peaks) if peaks else UNESTABLISHED,
        "runs_over_200k": (sum(1 for p in peaks if p > BUCKET_200K)
                           if peaks else UNESTABLISHED),
        "runs_over_400k": (sum(1 for p in peaks if p > BUCKET_400K)
                           if peaks else UNESTABLISHED),
        "median_repeated_read_count": _median_or_unestablished(
            [r["repeated_read_count"] for r in runs]),
        "median_reemission_count": _median_or_unestablished(
            [r["reemission_count"] for r in runs]),
        # Primary round-attributed auditor-cost axis (issue #889). An empty run
        # population reads `unestablished`, never `0` — "the auditor cost nothing" is a
        # real value this instrument must not publish about a corpus it never measured.
        "median_attributed_auditor_cost": _median_or_unestablished(
            [r["attributed_auditor_cost"] for r in runs]),
        # How much of that primary axis is sidechain cost NO round boundary could key.
        # `attributed_auditor_cost` folds it in, so a run whose every dispatch marker
        # failed to match still reports a full, confident "attributed" total that is
        # 100% unattributed. Both a MEDIAN (comparable with the median above) and a
        # corpus-wide TOTAL are published, because the sum alone is not comparable with
        # a median — a reader of an N-run corpus could not recover the unattributed
        # fraction from a median-vs-sum pairing.
        "median_unrounded_auditor_cost": _median_or_unestablished(
            [r["unrounded_auditor_cost"] for r in runs]),
        "total_unrounded_auditor_cost": (sum(
            r["unrounded_auditor_cost"] for r in runs) if runs else UNESTABLISHED),
        "median_auditor_cost_discovery": medians["discovery"],
        "median_auditor_cost_targeted": medians["targeted"],
        # The falsifiability operands for the docstring's unverified assumption that the
        # harness stamps `attributionSkill` on a sidechain record. `0 attributed` beside
        # a non-zero `total_record_reopen` or a non-empty per-run `dispatch_rounds` is
        # evidence the assumption failed, NOT a measurement of a free audit.
        "total_sidechain_records_seen": (sum(
            r["sidechain_records_seen"] for r in runs) if runs else UNESTABLISHED),
        "total_sidechain_records_attributed": (sum(
            r["sidechain_records_attributed"] for r in runs) if runs else UNESTABLISHED),
        # Escaped-defect axis proxies. Flattened into two scalars so every summary field
        # renders as a scalar in the text report rather than one raw dict repr.
        "total_record_reopen": (sum(r["record_reopen_count"] for r in runs)
                                if runs else UNESTABLISHED),
        "scope_escape_count": escape["count"],
        "scope_escape_unattributable": escape["unattributable"],
        # A declared post-filing class the instrument reports unestablished, never a
        # number: escaped defects found AFTER the issue is filed are outside any
        # transcript or state file this instrument reads.
        "post_filing_escapes": UNESTABLISHED,
        # Wall-clock is not a measured axis on this tier (AC4).
        "wall_clock": UNESTABLISHED,
    }


def _join_round_kinds(runs, state):
    """Stamp each run's per-round breakdown with the round's RECORDED kind (AC6).

    AC6 asks for a per-run breakdown carrying each round's recorded kind alongside its
    attributed cost, so the kind must not live only in the aggregate per-kind medians —
    a reader of one run's report has to be able to tell which of ITS rounds were
    targeted. With no state (or a degraded one) each entry reads `unestablished`, never
    a guessed kind.

    KNOWN GAP, disclosed: the state file keys rounds by NUMBER alone, so a corpus of
    several runs joined against a single state file labels every run's round N with that
    one state's round N. The join is correct only when the side holds ONE run — which is
    a property of the committed fixtures under
    `lib/test/fixtures/create-issue-eval/{before,after}-rounds/`, NOT a property of
    paired mode: `--before`/`--after` each take a DIRECTORY, and `eval_corpus` yields one
    run per qualifying session JSONL beneath it, so a multi-run side mislabels. Closing
    it needs a per-run state file, which the state owner does not yet emit a run
    coordinate for.
    """
    for run in runs:
        # issue #1103 — the recorded selecting reason is joined beside the kind, on the
        # same membership test, in one pass so the "state present for this round?" guard is
        # resolved once per round rather than duplicated. A round the state does not label,
        # and a labelled round whose record carries no reason, both read `unestablished`
        # (never a guessed reason): the former because no state row exists, the latter
        # because `read_state` already resolved an absent/non-string `kind_reason` to the
        # sentinel.
        kinds, reasons = {}, {}
        for n in run["round_auditor_cost"]:
            present = state is not None and n in state
            kinds[n] = state[n]["kind"] if present else UNESTABLISHED
            reasons[n] = state[n]["kind_reason"] if present else UNESTABLISHED
        run["round_kinds"] = kinds
        run["round_reasons"] = reasons
    return runs


def build_report(corpus_root, state_path=None, large_block_chars=LARGE_BLOCK_MIN_CHARS):
    """One run-set report: runs, the aggregate, and the skip tally."""
    runs, skipped = eval_corpus(corpus_root, large_block_chars)
    state = read_state(state_path)
    if state is not None and len(runs) > 1:
        state = _degraded_state(state_path, "unsafe_multi_run_state_join")
    _join_round_kinds(runs, state)
    summary = aggregate(runs, state)
    return {
        "runs": runs,
        "summary": summary,
        "skipped": skipped,
        # `state_established` and `finding_count` are READ BACK from the summary, never
        # re-derived from `state` a second way: three parallel encodings of "the state
        # was not established" (a `None` reader return, the `UNESTABLISHED` sentinel,
        # and a boolean) can disagree, and the paired delta then has to defend against
        # whichever one reached it. One producer, two aliases.
        "state_established": summary["state_established"],
        "finding_count": summary["finding_count"],
    }


def _manifest_error(diagnostic, detail):
    raise ValueError("{}: {}".format(diagnostic, detail))


def _required_string(mapping, key, diagnostic="missing_field"):
    value = mapping.get(key) if isinstance(mapping, dict) else None
    if not isinstance(value, str) or not value:
        _manifest_error(diagnostic, "{} must be a non-empty string".format(key))
    return value


def _resolved_artifact(root, value, label):
    if not isinstance(value, str) or not value:
        _manifest_error("missing_artifact", "{} has no path".format(label))
    candidate = value if os.path.isabs(value) else os.path.join(root, value)
    resolved = os.path.realpath(candidate)
    try:
        contained = os.path.commonpath((root, resolved)) == root
    except ValueError:
        contained = False
    if not contained:
        _manifest_error("path_escape", "{} escapes declared root: {}".format(label, value))
    if not os.path.isfile(resolved):
        _manifest_error("missing_artifact", "{} not found: {}".format(label, value))
    return resolved


def load_eval_manifest(path):
    """Load and validate one schema-1 create-issue evaluation manifest."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    # Do not narrow: see the decode-site note in `eval_corpus`.
    except Exception as exc:  # noqa: BLE001 - fail closed on `invalid_manifest`
        _manifest_error("invalid_manifest", "{}: {}".format(path, exc))
    if not isinstance(manifest, dict):
        _manifest_error("invalid_manifest", "top level is not an object")
    version = manifest.get("schema_version")
    if version != MANIFEST_SCHEMA_VERSION or isinstance(version, bool):
        _manifest_error("unsupported_schema_version", repr(version))
    _required_string(manifest, "benchmark_id")
    root_value = _required_string(manifest, "root")
    manifest_dir = os.path.dirname(os.path.abspath(path))
    root = os.path.realpath(
        root_value if os.path.isabs(root_value) else os.path.join(manifest_dir, root_value)
    )
    if not os.path.isdir(root):
        _manifest_error("missing_artifact", "declared root not found: {}".format(root_value))
    runs = manifest.get("runs")
    if not isinstance(runs, list) or not runs:
        _manifest_error("missing_field", "runs must be a non-empty list")

    run_ids = set()
    occurrence_ids = set()
    normalized_runs = []
    for index, source_run in enumerate(runs):
        if not isinstance(source_run, dict):
            _manifest_error("invalid_run", "runs[{}] is not an object".format(index))
        run = dict(source_run)
        run_id = _required_string(run, "run_id", "missing_run_id")
        if run_id in run_ids:
            _manifest_error("duplicate_run_id", run_id)
        run_ids.add(run_id)
        _required_string(run, "configuration")
        _required_string(run, "scenario_id")
        repetition = run.get("repetition")
        if not isinstance(repetition, int) or isinstance(repetition, bool) or repetition < 1:
            _manifest_error("invalid_run_identity", "{} repetition".format(run_id))

        occurrence = run.get("occurrence")
        if not isinstance(occurrence, dict):
            _manifest_error("missing_occurrence_identity", run_id)
        session_id = _required_string(
            occurrence, "session_id", "missing_occurrence_identity"
        )
        occurrence_id = _required_string(
            occurrence, "occurrence_id", "missing_occurrence_identity"
        )
        identity = (session_id, occurrence_id)
        if identity in occurrence_ids:
            _manifest_error("duplicate_occurrence_identity", repr(identity))
        occurrence_ids.add(identity)
        confidence = occurrence.get("boundary_confidence")
        if confidence not in BOUNDARY_CONFIDENCE:
            _manifest_error("invalid_boundary_confidence", "{}: {!r}".format(
                run_id, confidence
            ))
        start = occurrence.get("start_event")
        end = occurrence.get("end_event")
        start_valid = (
            isinstance(start, int) and not isinstance(start, bool) and start >= 0
        )
        end_valid = (
            confidence == "unknown" and end is None
        ) or (
            confidence != "unknown"
            and isinstance(end, int)
            and not isinstance(end, bool)
            and start_valid
            and end >= start
        )
        if not start_valid or not end_valid:
            _manifest_error("invalid_occurrence_boundary", run_id)
        if "duration_ms" not in occurrence:
            _manifest_error("missing_duration_ms", run_id)
        duration = occurrence.get("duration_ms")
        if (
            confidence == "unknown" and duration is not None
        ) or (
            duration is not None
            and (not isinstance(duration, int)
                 or isinstance(duration, bool)
                 or duration < 0)
        ):
            _manifest_error("invalid_occurrence_boundary", "{} duration_ms".format(run_id))

        checkpoints = run.get("checkpoints")
        if not isinstance(checkpoints, dict):
            _manifest_error("missing_artifact", "{} checkpoints".format(run_id))
        revisions = checkpoints.get("revisions")
        if not isinstance(revisions, list):
            _manifest_error("missing_artifact", "{} checkpoint revisions".format(run_id))
        normalized_checkpoints = dict(checkpoints)
        normalized_checkpoints.update({
            "initial": _resolved_artifact(
                root, checkpoints.get("initial"), "{} checkpoints.initial".format(run_id)
            ),
            "revisions": [
                _resolved_artifact(
                    root, revision, "{} checkpoints.revisions[{}]".format(run_id, number)
                )
                for number, revision in enumerate(revisions)
            ],
            "final": _resolved_artifact(
                root, checkpoints.get("final"), "{} checkpoints.final".format(run_id)
            ),
        })

        provenance = run.get("provenance")
        if not isinstance(provenance, dict):
            _manifest_error("missing_provenance", run_id)
        for key in (
            "repo_sha",
            "skill_fingerprint",
            "prompt_fingerprint",
            "model",
            "effort",
            "output_style",
            "provider",
        ):
            _required_string(provenance, key, "missing_provenance")

        run["transcript"] = _resolved_artifact(
            root, run.get("transcript"), "{} transcript".format(run_id)
        )
        run["state_file"] = _resolved_artifact(
            root, run.get("state_file"), "{} state_file".format(run_id)
        )
        if "rubric" in run:
            run["rubric"] = _resolved_artifact(
                root, run.get("rubric"), "{} rubric".format(run_id)
            )
        run["checkpoints"] = normalized_checkpoints
        normalized_runs.append(run)

    result = dict(manifest)
    result["root"] = root
    result["runs"] = normalized_runs
    return result


def _empty_skipped():
    return {
        "non_json_line": 0,
        "not_object": 0,
        "no_type": 0,
        "unreadable_file": 0,
        "escaped_path": 0,
        "walk_error": 0,
        "malformed_record": 0,
        "sidechain_only_file": 0,
    }


def _validate_manifest_event(record, run_id, event_index):
    rtype = record.get("type")
    if rtype not in ("assistant", "user", "system"):
        _manifest_error(
            "invalid_transcript",
            "{} event {} has unsupported type {!r}".format(
                run_id, event_index, rtype
            ),
        )
    if rtype != "assistant" or record.get("attributionSkill") not in ATTRIBUTION:
        return
    message = record.get("message")
    usage = message.get("usage") if isinstance(message, dict) else None
    if not isinstance(usage, dict):
        _manifest_error(
            "invalid_transcript",
            "{} event {} has no usage object".format(run_id, event_index),
        )
    for key in (
        "input_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "output_tokens",
    ):
        value = usage.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            _manifest_error(
                "invalid_transcript",
                "{} event {} has invalid usage.{}".format(run_id, event_index, key),
            )


def _json_artifact(path, label="artifact", consequence="the caller degrades it"):
    """Read a JSON artifact, returning None on any read/decode failure.

    The caller supplies `consequence` because the call sites diverge: an unusable
    state file degrades its figures, while an unusable rubric refuses the whole
    report. A single hardcoded clause would be false at one of them.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    # Match the legacy state's residual decoder boundary: deeply nested JSON raises
    # RecursionError rather than ValueError, and no decoder failure may turn a
    # manifest artifact into a traceback. Exception deliberately excludes process
    # controls such as KeyboardInterrupt and SystemExit.
    except Exception as exc:  # noqa: BLE001 - malformed explicit artifacts fail closed
        sys.stderr.write(
            "{}: {} not usable ({}: {}); {}\n".format(
                BREADCRUMB_PREFIX, label, path, exc, consequence
            )
        )
        return None


def _current_draft_digest(path, state):
    """Return (digest, digest_failed).

    `digest_failed` distinguishes an unreadable draft from a state that recorded no
    digest format; the owner reports those as different reasons, so collapsing them
    onto a bare None mislabels an undigestible draft as no-digest-supplied.
    """
    digests = [
        attempt.get("digest")
        for rnd in (state.get("rounds", []) if isinstance(state, dict) else [])
        for attempt in (rnd.get("attempts", []) if isinstance(rnd, dict) else [])
        if isinstance(attempt, dict)
    ]
    algorithm = None
    for value in reversed(digests):
        if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{40}", value):
            algorithm = "sha1"
            break
        if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value):
            algorithm = "sha256"
            break
    if algorithm is None:
        return None, False
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        sys.stderr.write(
            "{}: final draft not digestible ({}: {}); "
            "final-byte coverage reads draft-undigestible\n".format(
                BREADCRUMB_PREFIX, path, exc
            )
        )
        return None, True
    header = "blob {}\0".format(len(data)).encode("ascii")
    return hashlib.new(algorithm, header + data).hexdigest(), False


def _unestablished_grade(diagnostic):
    return {
        "schema_version": RUBRIC_SCHEMA_VERSION,
        "status": UNESTABLISHED,
        "diagnostic": diagnostic,
        "passed": False,
        "pass_rate": UNESTABLISHED,
        "forbidden_failures": UNESTABLISHED,
        "forbidden_section_failures": UNESTABLISHED,
        "assertions": [],
    }


def _observe_manifest_run(run, large_block_chars):
    occurrence = run["occurrence"]
    start = occurrence["start_event"]
    declared_end = occurrence["end_event"]
    end = start if declared_end is None else declared_end
    acc = RunAccumulator(os.path.basename(run["transcript"]), large_block_chars)
    event_index = 0
    selected = 0
    try:
        handle = open(run["transcript"], "r", encoding="utf-8")
    except (OSError, ValueError) as exc:
        _manifest_error("missing_artifact", "{} transcript: {}".format(run["run_id"], exc))
    with handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            # Do not narrow: see the decode-site note in `eval_corpus`.
            except Exception as exc:  # noqa: BLE001 - fail closed on `invalid_transcript`
                _manifest_error(
                    "invalid_transcript",
                    "{} line {}: {}".format(run["run_id"], line_number, exc),
                )
            if not isinstance(record, dict):
                _manifest_error(
                    "invalid_transcript",
                    "{} line {} is not an object".format(run["run_id"], line_number),
                )
            if start <= event_index <= end:
                selected += 1
                _validate_manifest_event(record, run["run_id"], event_index)
                rtype = record.get("type")
                if rtype == "assistant":
                    acc.observe_assistant(record)
                elif rtype == "user":
                    acc.observe_user(record)
                elif rtype == "system":
                    acc.observe_system(record)
            event_index += 1
    if selected != end - start + 1:
        _manifest_error("occurrence_out_of_range", run["run_id"])
    if not acc.attributed:
        _manifest_error("occurrence_not_analyzable", run["run_id"])
    result = acc.result()
    state = read_state(run["state_file"])
    required_rounds = set(result["dispatch_rounds"])
    if state is not None and (
        required_rounds != set(state)
        or any(state[number]["kind_reason"] == UNESTABLISHED
               for number in required_rounds)
    ):
        state = _degraded_state(run["state_file"], "partial_run_state")
    _join_round_kinds([result], state)
    run_summary = aggregate([result], state)
    for key in ("run_id", "configuration", "scenario_id", "repetition"):
        result[key] = run[key]
    result["occurrence"] = dict(occurrence)
    result["checkpoints"] = {
        "initial": run["checkpoints"]["initial"],
        "revisions": list(run["checkpoints"]["revisions"]),
        "final": run["checkpoints"]["final"],
    }
    result["draft_metrics"] = measure_checkpoints(run)
    state_document = _json_artifact(
        run["state_file"], "state file", "every figure it feeds reads unestablished"
    )
    current_digest, digest_failed = _current_draft_digest(
        run["checkpoints"]["final"], state_document
    )
    result["audit_outcomes"] = audit_outcomes(
        state_document, current_digest, digest_failed
    )
    if "rubric" in run:
        rubric = _json_artifact(
            run["rubric"], "rubric", "the manifest report is refused"
        )
        if rubric is None:
            _manifest_error("invalid_rubric", run["run_id"])
        final_text = _read_explicit_text(run["checkpoints"]["final"], "final")
        try:
            result["grade"] = grade_issue(final_text, rubric)
        except ValueError as exc:
            _manifest_error("invalid_rubric", "{}: {}".format(run["run_id"], exc))
    else:
        result["grade"] = _unestablished_grade("rubric-unavailable")
    result["provenance"] = dict(run["provenance"])
    result["state_established"] = (
        run_summary["state_established"]
        and result["audit_outcomes"]["status"] == "established"
    )
    result["finding_count"] = (
        run_summary["finding_count"]
        if result["state_established"] else UNESTABLISHED
    )
    return result, run_summary, _empty_skipped()


def _manifest_comparison(run_records):
    delta_keys = (
        "total_attributed_auditor_cost",
        "total_peak_context",
        "mean_peak_context_per_run",
        "median_main_thread_context",
        "total_round_count",
        "finding_count",
    )

    def unestablished(reason, pairs=None):
        return {
            "status": UNESTABLISHED,
            "diagnostic": reason,
            "delta": {key: UNESTABLISHED for key in delta_keys},
            "pairs": pairs or [],
        }

    configurations = sorted(
        {run["configuration"] for run in run_records},
        key=lambda value: (value != "baseline", value),
    )
    if len(configurations) != 2:
        return unestablished("no_pairable_configurations")

    # issue #1702 (AC10): verify equal case identities and counts on both sides BEFORE any
    # comparison, failing closed when a case is missing, duplicated, or split by resume. The
    # case identity is (scenario_id, repetition); a resume that split one run into two records
    # surfaces as that identity appearing more than once within a single configuration.
    per_config_cases = {configuration: [] for configuration in configurations}
    for run in run_records:
        per_config_cases[run["configuration"]].append(
            (run["scenario_id"], run["repetition"]))
    for cases in per_config_cases.values():
        if len(cases) != len(set(cases)):
            return unestablished("case_split_by_resume")
    baseline_cases = sorted(set(per_config_cases[configurations[0]]))
    revised_cases = sorted(set(per_config_cases[configurations[1]]))
    if len(baseline_cases) != len(revised_cases):
        return unestablished("case_count_mismatch")
    if baseline_cases != revised_cases:
        return unestablished("case_identity_mismatch")

    grouped = {}
    for run in run_records:
        key = (run["scenario_id"], run["repetition"])
        by_configuration = grouped.setdefault(key, {})
        if run["configuration"] in by_configuration:
            return unestablished("duplicate_pair_member")
        by_configuration[run["configuration"]] = run
    if any(set(group) != set(configurations) for group in grouped.values()):
        return unestablished("unpaired_runs")

    pairs = []
    controlled = (
        "repo_sha",
        "prompt_fingerprint",
        "model",
        "effort",
        "output_style",
        "provider",
    )
    before_runs, after_runs = [], []
    for scenario_repetition in sorted(grouped):
        group = grouped[scenario_repetition]
        before = group[configurations[0]]
        after = group[configurations[1]]
        pairs.append({
            "scenario_id": scenario_repetition[0],
            "repetition": scenario_repetition[1],
            "runs": [
                {"configuration": configurations[0], "run_id": before["run_id"]},
                {"configuration": configurations[1], "run_id": after["run_id"]},
            ],
            "quality": quality_gate(before.get("grade"), after.get("grade")),
        })
        if any(before["provenance"][key] != after["provenance"][key]
               for key in controlled):
            return unestablished("mixed_provenance", pairs)
        before_runs.append(before)
        after_runs.append(after)

    if any(
        run["occurrence"]["boundary_confidence"] != "exact"
        for run in before_runs + after_runs
    ):
        return unestablished("inexact_occurrence_boundary", pairs)
    if any(not run["state_established"] for run in before_runs + after_runs):
        return unestablished("unestablished_run_state", pairs)

    for configuration in configurations:
        members = [run for run in run_records if run["configuration"] == configuration]
        for key in ("repo_sha", "skill_fingerprint"):
            if len({run["provenance"][key] for run in members}) != 1:
                return unestablished("mixed_provenance", pairs)

    def report_for(runs):
        findings = [run["finding_count"] for run in runs]
        finding_count = (
            UNESTABLISHED
            if any(value == UNESTABLISHED for value in findings)
            else sum(findings)
        )
        return {
            "runs": runs,
            "skipped": _empty_skipped(),
            "finding_count": finding_count,
        }

    # issue #1702 (AC10): emit the median runtime main-thread token cost per side and the
    # non-regression verdict, after the identity gate above has passed. UNESTABLISHED when any
    # run's main-thread context could not be measured — never a number collapsed onto unknown.
    before_peaks = [run["peak_context"] for run in before_runs]
    after_peaks = [run["peak_context"] for run in after_runs]
    _all_numeric = all(_is_numeric(value) for value in before_peaks + after_peaks)
    median_before = _median(before_peaks) if _all_numeric else UNESTABLISHED
    median_after = _median(after_peaks) if _all_numeric else UNESTABLISHED
    within_baseline = (
        (median_after <= median_before) if _all_numeric else UNESTABLISHED)

    return {
        "status": "established",
        "diagnostic": None,
        "delta": _paired_delta(report_for(before_runs), report_for(after_runs)),
        "pairs": pairs,
        "case_identity": {
            "baseline_configuration": configurations[0],
            "revised_configuration": configurations[1],
            "case_count": len(baseline_cases),
            "cases": [
                {"scenario_id": scenario_id, "repetition": repetition}
                for scenario_id, repetition in baseline_cases
            ],
        },
        "median_main_thread_context": {
            "baseline": median_before,
            "revised": median_after,
            "corpus_size": {
                configurations[0]: len(before_runs),
                configurations[1]: len(after_runs),
            },
        },
        "revised_median_within_baseline": within_baseline,
    }


def build_manifest_report(path, large_block_chars=LARGE_BLOCK_MIN_CHARS):
    """Build a run-addressable report from a validated schema-1 manifest."""
    manifest = load_eval_manifest(path)
    records = []
    skipped = _empty_skipped()
    for run in manifest["runs"]:
        record, _run_summary, run_skipped = _observe_manifest_run(
            run, large_block_chars
        )
        records.append(record)
        for key, value in run_skipped.items():
            skipped[key] += value
    records.sort(key=lambda item: item["run_id"])
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "benchmark_id": manifest["benchmark_id"],
        "manifest_provenance": {
            "root": manifest["root"],
            "runs": [
                {
                    "run_id": run["run_id"],
                    "provenance": dict(run["provenance"]),
                }
                for run in sorted(manifest["runs"], key=lambda item: item["run_id"])
            ],
        },
        "runs": records,
        "summary": aggregate(records),
        "skipped": skipped,
        "comparison": _manifest_comparison(records),
    }


def _paired_delta(before, after):
    """The after-minus-before paired deltas (AC7).

    Reports the deltas the tier can measure: total attributed auditor cost, total peak
    context (secondary), total round count, and finding count. Latency is NOT here — the
    wall-clock axis reads `unestablished`, so a paired latency delta would present a
    number the tier never measured.

    **Every CORPUS-SUMMED key is named `total_`, and there are exactly three of them:**
    `total_attributed_auditor_cost`, `total_peak_context` and `total_round_count`. Under
    the old `per_run_context` name a 3-run before corpus against a 1-run after corpus
    reported a large "context reduction" that was pure population difference — and the
    other two sums, computed identically one line away, carried the same confound under
    population-neutral-sounding names. Each side's `run_count` is on its own summary for
    the reader to divide by. **`finding_count` is the fourth key and is deliberately NOT
    one of them:** it is a STATE-file axis (`_finding_count` totals the ledger entries
    across one state file's rounds), independent of how many runs either corpus holds,
    so it carries no `total_` marker and the population confound the naming rule guards
    against does not apply to it. It has its own guard instead — the state sentinel, via
    `_findings_delta` below. **`mean_peak_context_per_run` is the fifth key and is
    neither:** it is the per-run NORMALIZATION of the context axis (each side's sum
    divided by its own `run_count`), which is the axis AC7 actually names — the
    corpus-wide `total_peak_context` beside it carries the population confound this
    normalized key exists to remove, and both are published so a reader can see the
    difference rather than being handed one and told to divide.

    **An empty or under-counted run population makes every sum-based delta
    `unestablished`** — `_degraded` consults the run list AND every channel of the skip
    tally. A side with no runs, or one whose walk, file-open or record parse dropped
    anything, sums low, so subtracting would assert a measured saving against a corpus
    that was never fully read.
    """
    def _degraded(report):
        # No runs at all, or a corpus knowingly under-counted on ANY loss channel.
        # Every channel `eval_corpus` tallies drops either a whole session file
        # (`walk_error`, `escaped_path`, `unreadable_file`, `sidechain_only_file`) or a
        # `usage`-bearing record inside a counted run (`non_json_line`, `not_object`,
        # `no_type`, `malformed_record`) — each one directly DEFLATES the sums below,
        # so consulting `unreadable_file` alone would publish a real-looking negative
        # delta as a measured saving about a corpus that was never fully read: the
        # unknown-collapsed-onto-a-real-value shape this module exists to refuse.
        # The test iterates `.values()` rather than a hand-listed key set so a channel
        # added to `eval_corpus` later cannot silently fall outside the guard.
        return (not report["runs"]
                or any(v > 0 for v in report["skipped"].values()))

    degraded = _degraded(before) or _degraded(after)

    def _sum(report, key):
        return sum(r[key] for r in report["runs"])

    def _rounds(report):
        return sum(len(r["dispatch_rounds"]) for r in report["runs"])

    def _delta(fn):
        return UNESTABLISHED if degraded else fn(after) - fn(before)

    def _findings_delta():
        # Finding count is a state-file axis: the total ledger entries across rounds.
        # A side whose state could not be read carries the UNESTABLISHED sentinel, and
        # subtracting against it would publish a measured-looking delta about a side
        # that was never read — so the delta itself reads `unestablished`.
        b, a = before.get("finding_count"), after.get("finding_count")
        if b == UNESTABLISHED or a == UNESTABLISHED or b is None or a is None:
            return UNESTABLISHED
        return a - b

    def _mean_peak_context(report):
        # Population-NORMALIZED: the corpus sum divided by that side's own run count.
        # `_degraded` already guarantees a non-empty run list here.
        return _sum(report, "peak_context") / len(report["runs"])

    # Every `peak_context` delta below does arithmetic on the field, so one non-numeric value
    # would RAISE where this module's contract is to report `unestablished`. Route all three
    # through `_context_delta`, never `_delta` — guarding one and not its siblings is the
    # asymmetry that leaves a latent TypeError beside a guarded call.
    peaks_numeric = all(
        _is_numeric(run["peak_context"])
        for report in (before, after) for run in report["runs"])

    def _context_delta(fn):
        return _delta(fn) if peaks_numeric else UNESTABLISHED

    return {
        "total_attributed_auditor_cost": _delta(
            lambda rep: _sum(rep, "attributed_auditor_cost")),
        "total_peak_context": _context_delta(lambda rep: _sum(rep, "peak_context")),
        # AC7 names *per-run* context as a paired-delta axis, and the corpus-wide sum
        # above does not discharge it: a 3-run before corpus against a 1-run after
        # corpus yields a large negative `total_peak_context` that is pure population
        # difference. This key divides each side by its OWN `run_count` first, so the
        # confound cannot enter. It is a float by construction (a mean, not a token
        # count) — a non-integer delta (as the median below can also be), named as an
        # average so a reader is not invited to read it as a measured total.
        "mean_peak_context_per_run": _context_delta(_mean_peak_context),
        "median_main_thread_context": _context_delta(
            lambda rep: _median([r["peak_context"] for r in rep["runs"]])),
        "total_round_count": _delta(_rounds),
        "finding_count": _findings_delta(),
    }


def _finding_count(state):
    """Total ledger entries across rounds, or UNESTABLISHED when there is no state.

    NEVER `0` on a degraded/absent state: `0` is a real value meaning "the audit
    recorded no findings", and publishing it about a state file that was never read is
    the unknown-collapsed-onto-zero bug the whole axis guards against.
    """
    if state is None:
        return UNESTABLISHED
    return sum(len(rnd.get("findings") or []) for rnd in state.values())


def build_paired_report(before_dir, after_dir, before_state=None, after_state=None,
                        large_block_chars=LARGE_BLOCK_MIN_CHARS):
    """A before/after paired report with the AC7 deltas."""
    before = build_report(before_dir, before_state, large_block_chars)
    after = build_report(after_dir, after_state, large_block_chars)
    return {
        "before": before,
        "after": after,
        "delta": _paired_delta(before, after),
    }


def _render_run_line(r):
    parts = [
        "- {source}: turns={turn_count} peak={peak_context} final={final_context} "
        "output={total_output_tokens} compactions={compact_boundary_count} "
        "repeated_reads={repeated_read_count} reemissions={reemission_count} "
        "auditor_cost={attributed_auditor_cost} reopens={record_reopen_count}".format(**r)
    ]
    if r["round_auditor_cost"]:
        # AC6: each per-round entry carries the round's RECORDED kind beside its cost,
        # so one run's report is readable without the aggregate per-kind medians.
        # issue #1103 adds the selecting reason on its own per-round line (a separate line
        # rather than folded into `r{}={}(kind)` so the kind rendering stays byte-stable
        # for its existing readers). Both lines walk the SAME round order, sorted once.
        order = sorted(r["round_auditor_cost"])
        kinds = r.get("round_kinds") or {}
        reasons = r.get("round_reasons") or {}
        by_round = " ".join(
            "r{}={}({})".format(n, r["round_auditor_cost"][n], kinds.get(n, UNESTABLISHED))
            for n in order)
        parts.append("\n  - per-round auditor cost: {}".format(by_round))
        by_reason = " ".join(
            "r{}={}".format(n, reasons.get(n, UNESTABLISHED)) for n in order)
        parts.append("\n  - per-round selecting reason: {}".format(by_reason))
    return "".join(parts)


def render_text(runs, summary, skipped):
    lines = []
    lines.append("# create-issue runtime main-thread context eval")
    lines.append("")
    lines.append("## Per-run metrics")
    if not runs:
        lines.append("(no create-issue runs found in the supplied corpus)")
    for r in runs:
        lines.append(_render_run_line(r))
    lines.append("")
    lines.append("## Aggregate summary")
    # aggregate() builds this dict in the canonical field order, so iterating it
    # renders every field once with no per-field literal to keep in sync.
    # `state_established` and `finding_count` are summary members, so this one loop
    # renders them too — text and JSON mode are field-equivalent by construction, and
    # the renderer test's "every summary field appears" property covers them without a
    # per-field literal here to keep in sync.
    for key, value in summary.items():
        lines.append("- {}: {}".format(key, value))
    lines.append("")
    total_skipped = sum(skipped.values())
    lines.append("## Skipped records: {}".format(total_skipped))
    for reason in sorted(skipped):
        if skipped[reason]:
            lines.append("- {}: {}".format(reason, skipped[reason]))
    return "\n".join(lines)


def render_paired_text(report):
    lines = ["# create-issue context eval — before/after paired deltas", ""]
    for label in ("before", "after"):
        side = report[label]
        lines.append("## {}".format(label.capitalize()))
        lines.append(render_text(side["runs"], side["summary"], side["skipped"]))
        lines.append("")
    lines.append("## Paired deltas (after - before)")
    for key, value in report["delta"].items():
        lines.append("- {}: {}".format(key, value))
    return "\n".join(lines)


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8. Never call this at import: doing so mutates the
    streams of any process that imports this module for tests. Tolerates a stream that
    has no usable `reconfigure` (issue #1762)."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None):
    _force_utf8_streams()
    parser = argparse.ArgumentParser(
        description="Measure the runtime main-thread context cost of /devflow:create-issue.",
    )
    parser.add_argument(
        "transcript_dir", nargs="?",
        help="Path to a Claude Code transcript directory (single-corpus mode).",
    )
    parser.add_argument("--state-file", default=None,
                        help="Audit state file for the round->kind labelling (single-corpus mode).")
    parser.add_argument("--before", default=None, help="Before transcript dir (paired mode).")
    parser.add_argument("--after", default=None, help="After transcript dir (paired mode).")
    parser.add_argument("--before-state", default=None, help="Before audit state file (paired mode).")
    parser.add_argument("--after-state", default=None, help="After audit state file (paired mode).")
    parser.add_argument(
        "--format", choices=("text", "json"), default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--large-block-chars", type=int, default=LARGE_BLOCK_MIN_CHARS,
        help="Minimum size (chars) of a block counted for the re-emission metric.",
    )
    args = parser.parse_args(argv)

    paired = args.before is not None or args.after is not None
    if paired:
        if args.before is None or args.after is None:
            sys.stderr.write("error: paired mode requires both --before and --after\n")
            return 2
        # A flag the parser accepts and the selected mode then discards is silently
        # dropped input: the operator reads the resulting `unestablished` as an honest
        # disclosure when the real cause is their own mismatched flag. Refuse it.
        if args.state_file is not None:
            sys.stderr.write("error: --state-file is a single-corpus flag; paired mode "
                             "takes --before-state/--after-state\n")
            return 2
        if args.transcript_dir is not None:
            sys.stderr.write("error: a positional transcript directory is a "
                             "single-corpus input; paired mode takes --before/--after\n")
            return 2
        for label, path in (("--before", args.before), ("--after", args.after)):
            if not os.path.isdir(path):
                sys.stderr.write("error: {} directory not found: {}\n".format(label, path))
                return 2
        # Hold the state operands to the same standard as their sibling directory
        # operands: an explicitly-supplied path that does not exist is an operator
        # error, not an occasion to report `unestablished` about it.
        for label, path in (("--before-state", args.before_state),
                            ("--after-state", args.after_state)):
            if path is not None and not os.path.isfile(path):
                sys.stderr.write("error: {} file not found: {}\n".format(label, path))
                return 2
        report = build_paired_report(
            args.before, args.after, args.before_state, args.after_state,
            args.large_block_chars)
        if args.format == "json":
            sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(render_paired_text(report) + "\n")
        return 0

    corpus = args.transcript_dir
    if corpus is None:
        # Returned, not `parser.error`'d: every sibling operand failure in this function
        # returns 2, and a SystemExit here would be the one arm a caller driving main()
        # in-process has to catch differently.
        sys.stderr.write(
            "error: a transcript directory (or --before/--after) is required\n")
        return 2
    for label, path in (("--before-state", args.before_state),
                        ("--after-state", args.after_state)):
        if path is not None:
            sys.stderr.write("error: {} is a paired-mode flag; single-corpus mode "
                             "takes --state-file\n".format(label))
            return 2
    if args.state_file is not None and not os.path.isfile(args.state_file):
        sys.stderr.write(
            "error: --state-file file not found: {}\n".format(args.state_file))
        return 2
    if not os.path.isdir(corpus):
        # No corpus present: exit non-zero naming the missing path — never a
        # silently-empty baseline.
        sys.stderr.write(
            "error: transcript directory not found: {}\n".format(corpus)
        )
        return 2

    report = build_report(corpus, args.state_file, args.large_block_chars)
    runs, summary, skipped = report["runs"], report["summary"], report["skipped"]

    if args.format == "json":
        # Sort keys for byte-stable, deterministic output.
        sys.stdout.write(
            json.dumps(
                {"runs": runs, "summary": summary, "skipped": skipped},
                indent=2, sort_keys=True,
            )
            + "\n"
        )
    else:
        sys.stdout.write(render_text(runs, summary, skipped) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
