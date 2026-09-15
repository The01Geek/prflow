#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Resolve per-subagent model/effort overrides for the /devflow:review engine.

The shared review engine (skills/review/SKILL.md) dispatches up to nine
subagents. Operators tune each one's model/effort via the
`prflow_review.agent_overrides` block in .prflow/config.json. This helper
reads that block (through config-get.sh — PRFlow's single config reader) for
the subagents about to be dispatched and prints the resolved model/effort map.

On the in-session dispatch path both tiers use today there is NO per-dispatch
`--agents` injection: a per-agent `model` override is delivered via the Agent
tool's `model` override parameter, while a per-agent `effort` override is NOT
deliverable per-agent (the Agent tool exposes no effort parameter). So this
helper additionally exposes a per-agent effort-application DECISION
(`decide_effort_applications`) and an honest per-resolve fallback report
(`format_effort_reports`) — a `::notice::` summary for a benign in-session
no-seam fallback, and a `::warning::` naming the model/provider for a
capability-restricted one (a Haiku model, an `effort_supported: false`
provider) — so a resolved-but-unapplied effort is reported at resolution time
rather than silently claimed as applied (issue #554).

Resolution rules (mirroring the schema):
  - `iterations` (issue #425): an optional per-entry key whose only valid value is
    "first-only". A valid value is passed through in the resolved map; any other
    value (including an empty string) is dropped with a warning, mirroring the
    invalid-effort path — the run never aborts. Like model/effort it obeys
    entry-level precedence (a `default: {iterations: …}` supplies it only to
    no-entry subagents). The ordinary resolve mode only READS the key and passes a
    valid value through; the `--plan-phase3` roster-planning mode
    (`plan_phase3_roster`) is the executable owner of the fix-loop-iteration>=2
    exclusion the engine formerly applied in Phase-3 prose. `iterations` is NOT a
    dispatch-time model/effort parameter, and the plan strips it from the
    per-agent overrides it returns.
  - Entry-level precedence: a subagent with its own entry uses ONLY that entry;
    the `default` entry does NOT backfill its missing fields. The `default`
    entry supplies model/effort only for subagents with no entry of their own.
  - A subagent with neither its own entry nor a `default` produces no override
    (dispatched exactly as today — global claude_model + session effort).
  - `effort` outside the schema enum is dropped with a warning (falls back to
    the session effort); the run never aborts on a bad effort value.
  - `model` outside the accepted set (sonnet, opus, haiku, fable — the Agent
    tool's per-invocation enum) is dropped with a warning naming the value and the
    set (falls back to the top-level claude_model); an in-set value is forwarded
    unchanged; a present-but-unusable model (empty, whitespace-only, or non-string)
    is dropped with a warning, mirroring the invalid-effort path.
  - An entry that resolves to no model, no valid effort, and no valid
    `iterations` emits no override for that subagent (nothing to apply); an
    entry carrying only a valid `iterations` still produces an override.
  - A non-object entry (e.g. a hand-edited `"agent": "high"` or a list) is
    ignored with a warning rather than crashing — the engine never aborts on
    config shape. Whether `default` then applies is path-dependent: `read_raw`
    drops such an entry before it reaches the raw map, so `default` still
    backfills that subagent; but a direct `resolve_overrides` call handed the
    non-object entry skips it WITHOUT applying `default` (the entry's presence
    in `raw` already counts as "has an entry"). The end-to-end path is
    `read_raw`, so operators see the `default`-applies behavior.

Usage:
    resolve-review-overrides.py AGENT [AGENT ...] [--config FILE] [--config-get PATH]
    resolve-review-overrides.py AGENT [AGENT ...] --plan-phase3 --entry-kind KIND [--iteration N]

`--plan-phase3` (issue #425) prints the Phase-3 roster plan instead of the override
map — see `plan_phase3_roster` and the `--plan-phase3` flag help.

Prints the override map as JSON to stdout, e.g.
    {"devflow:code-reviewer": {"model": "opus", "effort": "high"}}
Prints `{}` when no dispatched subagent has an applicable override (the engine
then emits no --agents block). Warnings go to stderr; `main()` always returns 0
on any config shape. Invalid CLI arguments never reach `main()` — argparse exits
the process itself before `main()` runs — so the engine never aborts on config.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

VALID_EFFORTS = ("low", "medium", "high", "xhigh", "max")

# The Agent tool's per-invocation `model` parameter is a closed enum; a value
# outside it raises InputValidationError at dispatch, so drop an out-of-set model
# (warn, fall back to the top-level claude_model) exactly as an out-of-enum effort.
VALID_MODELS = ("sonnet", "opus", "haiku", "fable")

# The only valid `iterations` value (issue #425). A first-only agent is excluded
# from the Phase-3 roster on primary fix-loop iterations >= 2 — a decision
# `plan_phase3_roster` (the `--plan-phase3` mode) owns, not this read path.
VALID_ITERATIONS = ("first-only",)

# config-get.sh stringifies a non-array config value the way JS String() does (the
# format config-get.sh's python3 coerce() reproduces for parity); a JSON object
# yields this sentinel. (Arrays take config-get.sh's separate join(",")
# branch, so they do NOT stringify to this sentinel — see read_raw's array-leaf
# note.) read_raw uses it to tell a present-but-empty object entry ({}) from a
# scalar/array entry the operator hand-edited in.
_OBJECT_SENTINEL = "[object Object]"

# The nine review-engine subagent LEAF ids — the part after the plugin
# namespace. Byte-identical to the leaf of each schema property key and of each
# dispatch id in skills/review/SKILL.md; the six Phase-3 ids additionally match
# the telemetry strings (phase3_dispatched / finding `agent`) in
# skills/review-and-fix/SKILL.md.
AGENT_LEAVES = (
    "checklist-generator",
    "checklist-deduper",
    "checklist-verifier",
    "code-reviewer",
    "silent-failure-hunter",
    "comment-analyzer",
    "type-design-analyzer",
    "pr-test-analyzer",
    "requesting-code-review",
)

# `agent_overrides` keys are namespaced by the plugin id (`<plugin>:<leaf>`), and
# this allowlist is CLOSED — an unrecognized key is reported as drift. The
# accepted namespace set is therefore derived from the single identity source
# (lib/plugin-identity.json + .claude-plugin/plugin.json) rather than spelled as
# a literal here, so every declared identifier resolves without this file being
# re-edited. lib/ is a sibling of scripts/ in both the source repo and a vendored
# .prflow/vendor/prflow/ tree, so the import path holds on every tier.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
# The one site resolving DEVFLOW_BASH and building a shell-readable script argument
# (issue #430). Imported over the same lib/ path inserted above, so it resolves in a
# vendored consumer tree exactly as plugin_identity does.
try:
    import bash_launch as _bl
except Exception as _bl_exc:  # pragma: no cover - import-time arm
    # Name the dependency rather than letting an ImportError surface as a raw traceback on
    # the consumer-shipped review path, where this file runs under the read-only reviewer.
    raise SystemExit(
        "resolve-review-overrides: the shared launch helper lib/bash_launch.py could not be "
        f"imported ({_bl_exc.__class__.__name__}: {_bl_exc}); refusing to resolve overrides"
    ) from _bl_exc

try:
    import plugin_identity as _plugin_identity

    AGENT_NAMESPACES = tuple(_plugin_identity.agent_namespaces())
    IDENTITY_ERROR = None
except Exception as _exc:  # pragma: no cover - import-time arm; driven by the
    # suite's identity-unestablished control (a plugin root copied without
    # lib/plugin-identity.json), which asserts this warning fires, no per-agent
    # drift warning is fabricated, and the run still exits 0.
    # DEGRADED, and said out loud. This allowlist only produces an advisory
    # drift warning, so the honest degradation is to stop claiming an id is
    # unknown (which would be a fabricated diagnosis) — never to guess a
    # namespace. Every other resolution path is unaffected.
    AGENT_NAMESPACES = ()
    IDENTITY_ERROR = str(_exc)

# The resolved closed allowlist: every accepted namespace crossed with every leaf.
KNOWN_AGENTS = tuple(ns + leaf for ns in AGENT_NAMESPACES for leaf in AGENT_LEAVES)


def override_key_candidates(agent):
    """Accepted `agent_overrides` key spellings for one dispatched agent id.

    Returned in PRECEDENCE order. `agent_overrides` keys are namespaced by the
    plugin id, and the schema accepts EVERY declared namespace for the same
    subagent — the canonical one plus the pre-rename alias, "so an override
    committed before the plugin rename keeps resolving". The engine dispatches
    only the canonical spelling, so a key-equality lookup would read the
    dispatched spelling and silently discard an alias-spelled entry that the
    schema (whose `additionalProperties` stays false, and which enumerates both
    spellings) declares valid. Every accepted spelling of the same leaf
    therefore resolves to the same agent.

    Precedence is positional and deterministic, never dict-order-dependent: the
    dispatched id's own spelling first, then the remaining accepted namespaces
    in lib/plugin-identity.json order (canonical plugin name first, then its
    aliases). A config carrying two spellings for one subagent resolves to the
    dispatched spelling; `read_raw` warns that the other is shadowed.

    An id whose namespace is not an accepted one (or the unnamespaced `default`)
    has exactly one candidate — its own key. An unrecognized namespace is never
    treated as an alias of a known leaf.
    """
    for namespace in AGENT_NAMESPACES:
        if agent.startswith(namespace):
            leaf = agent[len(namespace):]
            break
    else:
        return [agent]
    return [agent] + [ns + leaf for ns in AGENT_NAMESPACES if ns + leaf != agent]


def _entry_for(raw, agent, default_entry=None):
    """Precedence-selected raw entry for `agent`, with its source key.

    The single source of the entry-level precedence rule ("an own entry wins
    outright — even `{}` or a non-dict — and `default` applies only to an agent
    with no entry of its own"), shared by `resolve_overrides` and
    `build_effort_observability` so `requested` can never be sourced through a
    different precedence than `resolved`. "An own entry" means an entry under
    ANY accepted namespace spelling of this agent (see
    `override_key_candidates`), so an alias-keyed entry shadows `default`
    exactly like a canonically-keyed one. `default_entry` lets a caller supply
    a pre-sanitized default (resolve_overrides warns once and blanks a non-dict
    default); when omitted, the raw `default` value is returned as-is.
    """
    for key in override_key_candidates(agent):
        if key in raw:
            return raw[key], key
    if default_entry is None:
        default_entry = raw.get("default")
    return default_entry, "default"


def resolve_overrides(raw, dispatched):
    """Pure resolution: raw config -> (override_map, warnings).

    `raw` maps an agent id (or "default") to a dict that may carry "model",
    "effort", and/or "iterations". `dispatched` is the list of agent ids about
    to be dispatched this phase. Returns the override map (only agents with an
    applicable override) and a list of human-readable warning strings.
    """
    warnings = []
    default_entry = raw.get("default")
    if default_entry is not None and not isinstance(default_entry, dict):
        warnings.append(
            f"agent_overrides[default]={default_entry!r} is not an object; "
            "ignoring it."
        )
        default_entry = None
    default_entry = default_entry or {}
    result = {}
    for agent in dispatched:
        # Entry-level precedence: own entry wins outright; else fall back to
        # `default`. A present-but-empty own entry ({}) still counts as "has an
        # entry", so `default` does NOT apply to it. Selection lives in the
        # shared _entry_for so build_effort_observability reads the same rule.
        entry, source = _entry_for(raw, agent, default_entry)
        # A non-object entry (hand-edited config bypassing schema validation,
        # e.g. `"agent": "high"` or a list) must not crash resolution — the
        # engine never aborts on config shape. Warn and treat it as no override.
        if not isinstance(entry, dict):
            warnings.append(
                f"agent_overrides[{source}]={entry!r} is not an object; "
                f"ignoring it (no override for '{agent}')."
            )
            continue
        resolved = {}
        # A bad value on the shared `default` entry affects every no-entry agent;
        # phrasing the warning per-agent would emit one near-identical line per
        # such agent (up to nine for a single fat-fingered `default`). Phrase
        # default-sourced warnings agent-agnostically so they collapse to one line
        # under main()'s dedup; keep own-entry warnings agent-specific (each names
        # a distinct misconfigured entry).
        own = source != "default"
        scope = f" for '{agent}'" if own else " (affects every agent with no entry of its own)"

        model = entry.get("model")
        if model is not None:
            # A whitespace-only model is as unusable as an empty one; reject both.
            if not (isinstance(model, str) and model.strip()):
                warnings.append(
                    f"agent_overrides[{source}].model={model!r} is not a "
                    f"non-blank string; ignoring it{scope}."
                )
            elif model in VALID_MODELS:
                resolved["model"] = model
            else:
                warnings.append(
                    f"agent_overrides[{source}].model={model!r} is not one of "
                    f"{list(VALID_MODELS)}; falling back to the top-level claude_model{scope}."
                )

        effort = entry.get("effort")
        if effort is not None:
            if effort in VALID_EFFORTS:
                resolved["effort"] = effort
            else:
                warnings.append(
                    f"agent_overrides[{source}].effort={effort!r} is not one of "
                    f"{list(VALID_EFFORTS)}; falling back to session effort{scope}."
                )

        iterations = entry.get("iterations")
        if iterations is not None:
            if iterations in VALID_ITERATIONS:
                resolved["iterations"] = iterations
            else:
                warnings.append(
                    f"agent_overrides[{source}].iterations={iterations!r} is not one of "
                    f"{list(VALID_ITERATIONS)}; dropping it (agent dispatches on every "
                    f"iteration){scope}."
                )

        if resolved:
            result[agent] = resolved
    return result, warnings


# Phase-3 review-entry kinds (issue #425); plan_phase3_roster owns the exclusion semantics.
VALID_ENTRY_KINDS = ("standalone", "primary", "shadow")


def resolve_plan_iteration(raw_iteration):
    """Resolve a caller-supplied fix-loop iteration -> (value, resolved, warning).

    `raw_iteration` is the caller's iteration operand: an int, an int-shaped
    string (the CLI passes a string), or None when the caller holds no iteration
    context. Returns (iteration_value_or_None, resolved_bool, warning_or_None).
    An absent or non-integer operand is recorded as UNRESOLVABLE (resolved False,
    value None), never coerced to a later iteration — so a caller that cannot
    positively establish its iteration never accidentally excludes an agent.
    """
    if raw_iteration is None:
        return None, False, None
    unresolvable = (
        f"iteration {raw_iteration!r} is not an integer; treating the iteration "
        "context as unresolvable (no first-only exclusion applied)"
    )
    # bool is an int subclass; a boolean iteration is a caller bug, never a round.
    if isinstance(raw_iteration, bool):
        return None, False, unresolvable
    if isinstance(raw_iteration, int):
        return raw_iteration, True, None
    try:
        return int(str(raw_iteration).strip()), True, None
    except (TypeError, ValueError):
        return None, False, unresolvable


def plan_phase3_roster(raw, eligible, entry_kind, iteration):
    """Plan the Phase-3 reviewer roster (issue #425) -> (plan, warnings).

    The single executable owner of the `iterations: "first-only"` roster-exclusion
    decision the review engine used to make in Phase-3 prose. `raw` is the config
    map `resolve_overrides` reads; `eligible` is the applicability-selected Phase-3
    roster (the caller's own Phase 3.1 gate output); `entry_kind` is one of
    VALID_ENTRY_KINDS; `iteration` is the (value, resolved) pair from
    `resolve_plan_iteration`.

    Reuses `resolve_overrides` — the same config path, entry-level precedence,
    validation and warn-and-ignore behavior — so it introduces no second config
    loader and leaves the ordinary override-map output format untouched. A
    first-only agent is excluded ONLY on a positively-established primary entry
    with an integer iteration >= 2; iteration 1, standalone, shadow, and an
    unresolvable iteration exclude nobody (shadow even when a numeric iteration is
    present). An invalid `iterations` config value is dropped with a warning by
    `resolve_overrides`, so it never marks an agent first-only and never excludes.

    The returned plan accounts for the WHOLE eligible roster: every eligible agent
    appears in exactly one of `selected` or `exclusions`, so a caller can confirm a
    justified-empty selection (every eligible reviewer configured first-only on a
    later primary iteration) rather than accept a self-narrowed roster as proof the
    exclusion was applied.
    """
    override_map, warnings = resolve_overrides(raw, eligible)
    iteration_value, iteration_resolved = iteration
    exclusion_applies = (
        entry_kind == "primary"
        and iteration_resolved
        and isinstance(iteration_value, int)
        and iteration_value >= 2
    )
    selected = []
    exclusions = []
    for agent in eligible:
        first_only = (override_map.get(agent) or {}).get("iterations") == "first-only"
        if exclusion_applies and first_only:
            exclusions.append({
                "agent": agent,
                "reason": (
                    f"iterations=first-only: excluded on primary fix-loop "
                    f"iteration {iteration_value} (>= 2)"
                ),
            })
        else:
            selected.append(agent)
    # `iterations` governs roster membership only — never an Agent-tool
    # model/effort dispatch parameter — so strip it from each selected agent's
    # resolved override; an entry left empty after the strip emits no override.
    overrides = {}
    for agent in selected:
        resolved = {
            k: v for k, v in (override_map.get(agent) or {}).items()
            if k != "iterations"
        }
        if resolved:
            overrides[agent] = resolved
    plan = {
        "entry_kind": entry_kind,
        "iteration": iteration_value,
        "iteration_resolved": iteration_resolved,
        "exclusion_applies": exclusion_applies,
        "eligible": list(eligible),
        "selected": selected,
        "exclusions": exclusions,
        "overrides": overrides,
    }
    return plan, warnings


# The four effort application-point values (issue #554). Only two are reachable
# in-session — this resolver runs inside an already-running review session, whose
# effort was fixed at its own process start, so a per-agent effort override can
# only ever be a `session-fallback` (a resolved override the tier cannot apply)
# or a `session-inheritance` (a dispatched agent with no per-agent effort). The
# other two — `agent-definition` (a proven per-agent startup seam) and
# `process-start-session` (the section-level session effort composed at launch) —
# are process-start application points a pre-launch component owns, never this
# in-session resolver.
EFFORT_APPLICATION_POINTS = (
    "agent-definition",
    "process-start-session",
    "session-fallback",
    "session-inheritance",
)


def _is_haiku_model(model):
    """True when `model` is a Claude Haiku id (which rejects the `effort` param).

    Case-insensitive substring match on `haiku` — the same model-API fact the
    scaffold-config.sh Haiku-effort strip keys on. A non-string model is never a
    Haiku id.
    """
    return isinstance(model, str) and "haiku" in model.lower()


def _effort_capability_block(model, effort_supported):
    """The capability restriction (if any) that blocks a per-agent effort override.

    Single source of truth for the capability decision, shared by
    `decide_effort_applications` (which picks the fallback_reason) and
    `format_effort_reports` (which routes capability-restricted agents to a
    `::warning::` rather than the benign `::notice::`) — so the two never
    disagree. Returns:
      - "haiku"    — the resolved model is a Claude Haiku id (rejects effort);
      - "provider" — the routed provider's effort_supported is false (#313);
      - None       — no capability restriction (a benign in-session no-seam
                     fallback: the tier simply has no per-agent effort seam).
    """
    if _is_haiku_model(model):
        return "haiku"
    if not effort_supported:
        return "provider"
    return None


def decide_effort_applications(resolved, dispatched, *, effort_supported=True):
    """Per-agent in-session effort-application decision (issue #554).

    Pure: `resolved` is the `resolve_overrides` map (agent id -> {model?, effort?,
    iterations?}); `dispatched` is the list of agent ids about to be dispatched;
    `effort_supported` is the routed provider's capability flag (#313 — false when
    the provider rejects the `effort` parameter). Returns an ordered dict mapping
    every dispatched agent to `{application_point, effective, fallback_reason}`.

    This resolver runs IN-SESSION, so a per-agent effort override is never applied
    here: `effective` is ALWAYS None (unknown is not zero — the in-session engine
    cannot introspect its own session effort, so it never guesses a value). The
    decision is only which fallback:
      - a resolved per-agent effort under a Haiku model, or a provider whose
        `effort_supported` is false -> `session-fallback` with a capability
        fallback_reason naming the model/provider (effort is not emitted);
      - any other resolved per-agent effort -> `session-fallback` with the
        no-in-session-seam fallback_reason (the subagent inherits session effort);
      - no per-agent effort override -> `session-inheritance`, all-null (the agent
        inherits the session effort, and there is nothing to fall back FROM, so
        fallback_reason is None).
    """
    decisions = {}
    for agent in dispatched:
        entry = resolved.get(agent) or {}
        effort = entry.get("effort")
        model = entry.get("model")
        if effort is None:
            # No per-agent effort override — the agent simply inherits the session
            # effort. Nothing was resolved-but-dropped, so no fallback reason.
            decisions[agent] = {
                "application_point": "session-inheritance",
                "effective": None,
                "fallback_reason": None,
            }
            continue
        # A resolved per-agent effort exists. In-session it is never applied; pick
        # the fallback reason, preferring the capability restriction when present
        # (it names the concrete model/provider that would reject the parameter).
        cause = _effort_capability_block(model, effort_supported)
        if cause == "haiku":
            reason = (
                f"per-agent effort {effort!r} not emitted: resolved model {model!r} "
                "is a Claude Haiku model that rejects the effort parameter (HTTP 400); "
                "the agent inherits the session effort"
            )
        elif cause == "provider":
            reason = (
                f"per-agent effort {effort!r} not emitted: the routed provider's "
                "effort_supported is false; the agent inherits the session effort"
            )
        else:
            reason = (
                f"per-agent effort {effort!r} resolved but not applied: an "
                "already-running session's Agent-tool dispatch has no per-agent "
                "effort parameter and no per-dispatch --agents injection exists; "
                "the agent inherits the session effort"
            )
        decisions[agent] = {
            "application_point": "session-fallback",
            "effective": None,
            "fallback_reason": reason,
        }
    return decisions


def build_effort_observability(raw, resolved, dispatched, *, effort_supported=True):
    """Per-agent five-field effort observability block (issue #609).

    Composes, for every DISPATCHED agent, the block the iter workpad's
    `dispatched_effort` entries persist into the per-run efficiency record:
    `requested` (the raw configured effort BEFORE validation — read with the
    same entry-level precedence `resolve_overrides` applies: an own entry wins
    outright and `default` never backfills it, so a dropped-invalid effort stays
    visible as requested != resolved), `resolved` (the validated effort from the
    `resolve_overrides` map, None when dropped or absent), and the
    `decide_effort_applications` trio (`application_point`, `effective`,
    `fallback_reason` — `effective` is ALWAYS None in-session; unknown is not
    zero). Complete by construction: every block carries all five keys.
    """
    decisions = decide_effort_applications(
        resolved, dispatched, effort_supported=effort_supported
    )
    blocks = {}
    for agent in dispatched:
        # Same precedence as resolve_overrides, via the shared _entry_for; a
        # non-dict entry (own or default) yields requested=None, matching the
        # resolver's ignore-with-warning treatment of that shape. The no-entry
        # all-null session-inheritance block below is mirrored by the jq
        # degradation arm in lib/efficiency-trace.jq (an agent with no
        # dispatched_effort entry) — a coupled pair, edit together.
        entry, _ = _entry_for(raw, agent)
        requested = entry.get("effort") if isinstance(entry, dict) else None
        decision = decisions[agent]
        blocks[agent] = {
            "requested": requested,
            "resolved": (resolved.get(agent) or {}).get("effort"),
            "application_point": decision["application_point"],
            "effective": decision["effective"],
            "fallback_reason": decision["fallback_reason"],
        }
    return blocks


def format_effort_reports(decisions, resolved, *, effort_supported=True):
    """Honest per-resolve effort-fallback report lines (issue #554).

    Splits the `session-fallback` agents by CAUSE so a genuine misconfiguration
    is never laundered into a benign "not a failure" notice:

      - **Capability-restricted** (a Haiku model that rejects `effort`, or a
        provider whose `effort_supported` is false) is a genuine
        unusable-model/provider misconfiguration — the project reserves
        `::warning::` for exactly that — so each such agent gets its OWN
        `::warning::` line carrying the concrete `fallback_reason` (which names
        the model/provider). The cause is re-derived from `resolved` +
        `effort_supported` through the SAME `_effort_capability_block` helper
        `decide_effort_applications` used, so the two never disagree (no
        substring matching of the reason string, no split-brain).
      - **Benign in-session no-seam** (a valid override the tier simply has no
        per-agent effort seam for) is steady-state, not a failure — those
        collapse into ONE informational `::notice::` summary (never one line per
        agent), emitted once per resolve (per dispatch phase).

    Returns the ordered list of report lines (warnings first, then the single
    notice), or `[]` when no dispatched agent took the `session-fallback` arm.
    """
    warnings = []
    benign = []
    for agent, d in decisions.items():
        if d.get("application_point") != "session-fallback":
            continue
        model = (resolved.get(agent) or {}).get("model")
        if _effort_capability_block(model, effort_supported) is not None:
            # Capability-restricted: surface the named reason as a warning.
            warnings.append(
                f"::warning::resolve-review-overrides: {agent}: {d.get('fallback_reason')}"
            )
        else:
            benign.append(agent)
    lines = list(warnings)
    if benign:
        names = ", ".join(benign)
        lines.append(
            "::notice::resolve-review-overrides: per-agent effort was NOT applied for "
            f"{len(benign)} agent(s) ({names}) — this tier's in-session Agent-tool "
            "dispatch cannot apply a per-agent effort override, so each inherits the "
            "session effort (a session-fallback, not a failure: whether a per-agent "
            "effort override is applied or falls back depends on the tier's "
            "application point)."
        )
    return lines


def _config_get(config_get, config_file, dotted_key, warnings):
    """Read one scalar via config-get.sh, returning '' on absent/empty.

    We always pass a default ("") to config-get.sh, so an absent key/file is a
    clean exit 0 with empty stdout — NOT an error. A non-zero exit therefore
    signals a genuine failure (malformed config.json → exit 2, missing `python3` →
    exit 2, bad args → exit 2), which we surface as a warning rather than
    silently collapsing to "absent" (a fat-fingered config would otherwise drop
    every override with no diagnostic). Appends to `warnings`; never raises.
    """
    # Run config-get.sh under the selected bash; script_argument spells its path for that
    # interpreter (issues #365/#430 — native Python cannot exec a .sh shebang, and each bash
    # family reads a drive-letter path differently). See bash_launch.py for the path rules.
    # Give the subprocess NO cwd of its own: config-get.sh resolves config from
    # `git rev-parse --show-toplevel` in ITS cwd, so a script-dir cwd would read the plugin's
    # non-repo copy and drop every override silently.
    # The `bash` head stays literal, not the shared helper: cloud_writer_deps.py verifies this
    # file's declared exec edge from static bindings a helper call would leave nothing to read.
    bash = os.environ.get("DEVFLOW_BASH") or "bash"
    here = Path.cwd()
    cmd = [bash, _bl.script_argument(Path(config_get), cwd=here, bash=bash), dotted_key, ""]
    if config_file:
        cmd.append(config_file)
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, check=False
        )
    except OSError as exc:
        # Name the interpreter, not just the script: after #365 the exec target that
        # fails to spawn is `bash` (or $DEVFLOW_BASH), so a bogus DEVFLOW_BASH must not
        # read as "cannot run config-get.sh".
        warnings.append(f"cannot run {bash} {config_get}: {exc}")
        return ""
    if out.returncode != 0:
        # Cause-focused (no per-key detail): a parse error / missing-python3 /
        # bad-args failure is the same root cause for every key we probe, so an
        # identical message dedupes to one actionable line in read_raw rather
        # than one per agent×field.
        warnings.append(
            f"config-get.sh failed (exit {out.returncode}): {out.stderr.strip()}"
        )
        return ""
    return out.stdout.strip()


def read_raw(dispatched, config_get, config_file):
    """Read each dispatched agent's (+ default's) model/effort/iterations via config-get.sh.

    Returns (raw, warnings), with `raw` keyed by the config key each entry was
    actually found under — which, for an alias-spelled override, is NOT the
    dispatched id (`_entry_for` maps it back). Reader warnings are deduplicated
    so a single broken `config_get` path surfaces one actionable line, not one
    per leaf read.

    Each agent is probed under every accepted namespace spelling
    (`override_key_candidates`), in precedence order; the first present entry
    wins and the remaining spellings are probed once each ONLY to warn that a
    duplicate is shadowed. This reader looks up by key and cannot enumerate the
    config's keys, so a key matching no accepted spelling is invisible here —
    the schema's closed `additionalProperties: false` allowlist is what rejects
    one.
    """
    raw = {}
    warnings = []
    for agent in list(dispatched) + ["default"]:
        selected_key = None
        for key in override_key_candidates(agent):
            if selected_key is None:
                selected_key = _read_entry(
                    raw, key, config_get, config_file, warnings)
                continue
            # A higher-precedence spelling already won. Probe this one once
            # (any shape counts as present) purely to report the duplicate
            # rather than dropping it silently.
            duplicate = _config_get(
                config_get, config_file,
                f".prflow_review.agent_overrides.{key}", warnings)
            if duplicate:
                warnings.append(
                    f"agent_overrides[{key}] is shadowed by "
                    f"agent_overrides[{selected_key}] for '{agent}'; the "
                    "higher-precedence key wins and this entry is ignored."
                )
    # Dedupe while preserving first-seen order (a missing/mispathed helper would
    # otherwise emit the same line ~2-3x per agent).
    deduped = list(dict.fromkeys(warnings))
    return raw, deduped


def _read_entry(raw, key, config_get, config_file, warnings):
    """Read one `agent_overrides[<key>]` entry into `raw`; return `key` if present.

    Returns None when the key is absent or holds a non-object (which is warned
    and treated as no-entry, so `default` still applies), so the caller can move
    on to the next accepted spelling.
    """
    base = f".prflow_review.agent_overrides.{key}"
    entry = {}
    for field in ("model", "effort", "iterations"):
        # Agent ids contain ':' but never '.', so they are a single
        # dot-path segment — config-get.sh splits on '.' only.
        value = _config_get(config_get, config_file, f"{base}.{field}", warnings)
        if not value:
            continue
        # config-get.sh stringifies a non-scalar leaf: a JSON object becomes
        # the sentinel. Forwarding that as a model id (or letting it reach the
        # effort enum check as a misleading "not one of …") would launder an
        # invalid shape into a bogus literal — drop it with a clear warning.
        # (An array leaf joins to a comma string and is indistinguishable from
        # a scalar; that narrow case is documented as unhandled.)
        if value == _OBJECT_SENTINEL:
            warnings.append(
                f"agent_overrides[{key}].{field} is an object, not a "
                f"scalar; ignoring it for '{key}'."
            )
            continue
        entry[field] = value
    # A present-but-empty entry ({}) is a real config state that must shadow
    # `default` (entry-level precedence). The leaf reads can't distinguish it
    # from an absent key, so probe the entry object itself. config-get.sh
    # stringifies the value: a JSON object prints the sentinel
    # "[object Object]" (the JS String({}) format coerce() preserves), a scalar/array prints its own
    # stringification, and an absent key prints nothing. So:
    #   - sentinel       → present object, no model/effort/iterations → {} (shadows default)
    #   - other non-empty → a non-object entry (hand-edited config bypassing
    #     schema validation, e.g. `"agent": "high"`) → warn and treat as
    #     no-entry so `default` still applies; never crash.
    #   - empty          → absent key → no entry.
    # Only probe when no field was read — the common path stays at two reads.
    if entry:
        raw[key] = entry
        return key
    probe = _config_get(config_get, config_file, base, warnings)
    if probe == _OBJECT_SENTINEL:
        raw[key] = {}
        return key
    if probe:
        # "default still applies" is meaningful for a real agent (it falls
        # back to the default entry) but nonsensical for the `default` key
        # itself — a malformed `default` just yields no fallback at all.
        consequence = (
            "no fallback default for no-entry agents"
            if key == "default"
            else f"no override for '{key}'; default still applies"
        )
        warnings.append(
            f"agent_overrides[{key}]={probe!r} is not an object; "
            f"ignoring it ({consequence})."
        )
    return None


def _force_utf8_streams():
    """Force stdout/stderr to UTF-8, idempotently and defensively, in the CLI
    entry path only (not at import — so unit-test imports don't mutate the
    importer's global streams). Harmless where this script emits only ASCII, but
    keeps every first-party helper self-defending against a non-UTF-8 ambient
    codec (Windows' cp1252). The guard tolerates a non-`TextIOWrapper` stream."""
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


# The job env var the cloud workflows export from their already-resolved provider
# decision (issue #1772) — the coupled producer a reader could not infer here.
_EFFORT_SUPPORTED_ENV = "PRFLOW_EFFORT_SUPPORTED"


def _resolve_effort_supported(cli_value):
    """Resolve the provider effort capability -> (bool, warning_or_None).

    Precedence: an explicit `--effort-supported` CLI value wins; else the
    PRFLOW_EFFORT_SUPPORTED env var (issue #1772); else the 'true' default (the
    Anthropic path). Fail OPEN, not closed: an absent var preserves today's
    behavior, and an env value that is neither 'true' nor 'false' falls back to
    'true' WITH a warning rather than a silent coercion.

    Failing open is safe only because the actual `--effort` flag is dropped
    independently by each workflow's `cargs` step, which reads
    `steps.provider.outputs.effort_supported` itself; this value governs only the
    in-session per-agent effort reporting/fallback. Folding that flag-drop in here
    would turn this fail-open into a real pass-unsupported-flag path.
    """
    if cli_value is not None:
        return cli_value == "true", None
    raw = os.environ.get(_EFFORT_SUPPORTED_ENV)
    if raw is None or raw.strip() == "":
        return True, None
    normalized = raw.strip().lower()
    if normalized in ("true", "false"):
        return normalized == "true", None
    return True, (
        f"{_EFFORT_SUPPORTED_ENV}={raw!r} is not 'true' or 'false'; assuming the "
        "provider supports effort (true)."
    )


def main(argv=None):
    _force_utf8_streams()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agents", nargs="+", help="subagent ids about to be dispatched")
    parser.add_argument("--config", default=None, help="config file (passed to config-get.sh)")
    parser.add_argument(
        "--config-get",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config-get.sh"),
        help="path to config-get.sh (default: alongside this script)",
    )
    parser.add_argument(
        "--effort-supported",
        choices=("true", "false"),
        default=None,
        help=(
            "the routed provider's effort_supported capability (#313); when "
            "'false', a resolved per-agent effort is reported as a "
            "capability-restricted fallback. When omitted, the PRFLOW_EFFORT_SUPPORTED "
            "environment variable is read instead (the cloud workflows export it from "
            "the already-resolved provider decision — issue #1772); an absent or "
            "unrecognized value falls back to 'true' (the Anthropic path). The "
            "in-session engine cannot itself introspect the routed provider's "
            "capability, so the model-level Haiku restriction (read from the resolved "
            "model) is the capability guard active by default; the workflow-exported "
            "env var (or an explicit flag) carries the provider capability."
        ),
    )
    parser.add_argument(
        "--plan-phase3",
        action="store_true",
        help=(
            "print the Phase-3 roster PLAN (issue #425) as pure JSON on stdout, "
            "INSTEAD of the override map: {entry_kind, iteration, iteration_resolved, "
            "exclusion_applies, eligible, selected, exclusions[{agent,reason}], "
            "overrides}. The positional agents are the applicability-selected Phase-3 "
            "roster. Requires --entry-kind; --iteration supplies the fix-loop "
            "iteration. A first-only agent is excluded only on a primary entry with "
            "an integer iteration >= 2; standalone, shadow, iteration 1, and an "
            "unresolvable iteration exclude nobody. Config-shape warnings still go to "
            "stderr; the #554 effort report lines are not emitted in this mode."
        ),
    )
    parser.add_argument(
        "--entry-kind",
        choices=VALID_ENTRY_KINDS,
        default=None,
        help="the caller's Phase-3 review-entry kind (required with --plan-phase3)",
    )
    parser.add_argument(
        "--iteration",
        default=None,
        help=(
            "the caller-held fix-loop iteration for --plan-phase3 (a positive "
            "integer). Absent or non-integer is recorded as unresolvable, never "
            "coerced to a later iteration."
        ),
    )
    parser.add_argument(
        "--effort-json",
        action="store_true",
        help=(
            "print the per-agent five-field effort observability map (issue "
            "#609: requested/resolved/application_point/effective/"
            "fallback_reason per dispatched agent) as pure JSON on stdout, "
            "INSTEAD of the override map. The #554 effort report lines are not "
            "re-emitted (the phase's normal resolve call already reported "
            "them); config-shape warnings still go to stderr."
        ),
    )
    args = parser.parse_args(argv)

    # A dispatched id not in the known roster is almost always a drift between
    # SKILL.md's hardcoded strings and the canonical roster, or an operator typo
    # in agent_overrides — warn (don't abort) so it isn't a silent no-op.
    # When the identity source could not be read the accepted-namespace set is
    # unestablished, NOT empty — calling every dispatched id "unknown" would be a
    # fabricated diagnosis (unknown is not zero). Report the real defect once and
    # emit no per-agent drift warnings.
    if not KNOWN_AGENTS:
        unknown = []
        sys.stderr.write(
            "::warning::resolve-review-overrides: the accepted plugin-namespace "
            "set could not be established from lib/plugin-identity.json + "
            f".claude-plugin/plugin.json ({IDENTITY_ERROR}); the subagent-id drift "
            "check is skipped this run. Overrides still resolve normally.\n"
        )
    else:
        unknown = list(dict.fromkeys(a for a in args.agents if a not in KNOWN_AGENTS))

    raw, read_warnings = read_raw(args.agents, args.config_get, args.config)

    # Emit the subagent-id drift warnings once, before the output-mode split, so
    # every mode (plan, effort-json, ordinary) reports them identically.
    for a in unknown:
        sys.stderr.write(
            f"::warning::resolve-review-overrides: '{a}' is not a known "
            "review-engine subagent id (KNOWN_AGENTS); any override for it is "
            "resolved but it may indicate a typo or dispatch/roster drift.\n"
        )

    # Roster-planning mode (issue #425): see plan_phase3_roster.
    if args.plan_phase3:
        if args.entry_kind is None:
            parser.error(
                "--plan-phase3 requires --entry-kind {standalone,primary,shadow}")
        iteration_value, iteration_resolved, iteration_warning = \
            resolve_plan_iteration(args.iteration)
        plan, plan_warnings = plan_phase3_roster(
            raw, args.agents, args.entry_kind,
            (iteration_value, iteration_resolved))
        iteration_extra = [iteration_warning] if iteration_warning else []
        for w in dict.fromkeys(read_warnings + plan_warnings + iteration_extra):
            sys.stderr.write(f"::warning::resolve-review-overrides: {w}\n")
        sys.stdout.write(json.dumps(plan) + "\n")
        return 0

    result, resolve_warnings = resolve_overrides(raw, args.agents)
    # Dedupe across BOTH sources, preserving first-seen order: read_raw already
    # dedupes its own, but a malformed `default` makes resolve_overrides emit one
    # (now agent-agnostic) line that would otherwise repeat, and the two sources
    # can also overlap. One actionable line per distinct problem.
    # Fold the resolver's unrecognized-value warning into the same deduped stream,
    # so a fat-fingered env value surfaces one actionable line.
    effort_supported, effort_supported_warning = _resolve_effort_supported(
        args.effort_supported)
    extra_warnings = [effort_supported_warning] if effort_supported_warning else []
    for w in dict.fromkeys(read_warnings + resolve_warnings + extra_warnings):
        sys.stderr.write(f"::warning::resolve-review-overrides: {w}\n")
    # Honest fallback report (issue #554): decide the per-agent effort-application
    # outcome and emit report lines to stderr (stdout stays pure JSON). A benign
    # in-session no-seam fallback is one informational `::notice::` summary; a
    # capability-restricted one (Haiku model / effort_supported=false) is a
    # `::warning::` naming the model/provider. Never claims an unearned success.
    # effort_supported is resolved above; do not re-derive it from args.effort_supported.
    if args.effort_json:
        # Observability mode (issue #609): stdout is the five-field map, and the
        # #554 report lines are deliberately NOT re-emitted — this is a second
        # call in the same dispatch phase, whose normal resolve call already
        # reported the fallback once.
        sys.stdout.write(
            json.dumps(
                build_effort_observability(
                    raw, result, args.agents, effort_supported=effort_supported
                )
            )
            + "\n"
        )
        return 0
    decisions = decide_effort_applications(
        result, args.agents, effort_supported=effort_supported
    )
    for line in format_effort_reports(decisions, result, effort_supported=effort_supported):
        sys.stderr.write(line + "\n")
    sys.stdout.write(json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
