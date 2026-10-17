#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Resolve per-subagent model overrides for the /devflow:review engine.

The shared review engine (skills/review/SKILL.md) dispatches up to eight
subagents. Operators tune each one's model via the
`prflow_review.agent_overrides` block in .prflow/config.json. This helper
reads that block (through config-get.sh — PRFlow's single config reader) for
the subagents about to be dispatched and prints the resolved model map; the
engine passes each `model` as the Agent tool's `model` override parameter.

A per-agent `effort` key is deprecated and ignored: the Agent tool has no effort
parameter and no per-dispatch `--agents` injection exists, so a configured effort
never reached a subagent. Configs carrying it still validate; it resolves to nothing.

Resolution rules (mirroring the schema):
  - `iterations` (issue #425): an optional per-entry key whose only valid value is
    "first-only". A valid value is passed through in the resolved map; any other
    value is dropped with a warning — the run never aborts (through `read_raw` an
    empty value reads as absent). Like model it obeys entry-level precedence (a `default: {iterations: …}`
    supplies it only to no-entry subagents). The ordinary resolve mode only READS
    the key and passes a valid value through; the `--plan-phase3` roster-planning
    mode (`plan_phase3_roster`) is the executable owner of the
    fix-loop-iteration>=2 exclusion. `iterations` is NOT a dispatch-time parameter,
    and the plan strips it from the per-agent overrides it returns.
  - Entry-level precedence: a subagent with its own entry uses ONLY that entry;
    the `default` entry does NOT backfill its missing fields. The `default`
    entry supplies values only for subagents with no entry of their own.
  - A subagent with neither its own entry nor a `default` produces no override
    (dispatched with no override).
  - `model` outside the accepted set (sonnet, opus, haiku, fable — the Agent
    tool's per-invocation enum) is dropped with a warning naming the value and the
    set (falls back to the top-level claude_model); an in-set value is forwarded
    unchanged; a number, boolean or object model is dropped with a warning (through `read_raw` an
    empty or whitespace-only one reads as absent).
  - An entry that resolves to no model and no valid `iterations` emits no
    override for that subagent (nothing to apply); an entry carrying only a
    valid `iterations` still produces an override.
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
    {"devflow:code-reviewer": {"model": "opus"}}
Prints `{}` when no dispatched subagent has an applicable override. Warnings go to
stderr; `main()` returns 0 on any config shape, and argparse exits 2 on invalid CLI
arguments.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# The Agent tool's per-invocation `model` parameter is a closed enum; a value
# outside it raises InputValidationError at dispatch, so drop an out-of-set model
# (warn; the agent is then dispatched with no model override).
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

# The review-engine subagent LEAF ids — the part after the plugin namespace,
# byte-identical to the leaf of each schema property key. `checklist-deduper` is
# retired (nothing dispatches it) and stays listed only so a consumer config
# carrying its override resolves without a drift warning.
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


def _entry_for(raw, agent, default_entry):
    """Precedence-selected raw entry for `agent`, with its source key.

    An own entry wins outright — even `{}` or a non-dict — and `default_entry`
    applies only to an agent with no entry of its own. "An own entry" means an
    entry under ANY accepted namespace spelling of this agent (see
    `override_key_candidates`), so an alias-keyed entry shadows `default`
    exactly like a canonically-keyed one.
    """
    for key in override_key_candidates(agent):
        if key in raw:
            return raw[key], key
    return default_entry, "default"


def resolve_overrides(raw, dispatched):
    """Pure resolution: raw config -> (override_map, warnings).

    `raw` maps an agent id (or "default") to a dict that may carry "model" and/or
    "iterations" (a deprecated "effort" is ignored). `dispatched` is the list of
    agent ids about to be dispatched this phase. Returns the override map (only
    agents with an applicable override) and a list of human-readable warning strings.
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
        # entry", so `default` does NOT apply to it.
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
        # such agent (one per dispatched agent for a single fat-fingered `default`). Phrase
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
    # model dispatch parameter — so strip it from each selected agent's
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
            cmd, capture_output=True, text=True, encoding="utf-8", check=False
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


def read_raw(dispatched, config_get, config_file, fields=("model", "iterations")):
    """Read each dispatched agent's (+ default's) `fields` via config-get.sh.

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
                    raw, key, config_get, config_file, warnings, fields)
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


def _read_entry(raw, key, config_get, config_file, warnings, fields):
    """Read one `agent_overrides[<key>]` entry into `raw`; return `key` if present.

    Returns None when the key is absent or holds a non-object (which is warned
    and treated as no-entry, so `default` still applies), so the caller can move
    on to the next accepted spelling.
    """
    base = f".prflow_review.agent_overrides.{key}"
    entry = {}
    for field in fields:
        # Agent ids contain ':' but never '.', so they are a single
        # dot-path segment — config-get.sh splits on '.' only.
        value = _config_get(config_get, config_file, f"{base}.{field}", warnings)
        if not value:
            continue
        # config-get.sh stringifies a non-scalar leaf: a JSON object becomes
        # the sentinel. Forwarding that as a model id would launder an invalid
        # shape into a bogus literal — drop it with a clear warning. (An array
        # leaf joins to a comma string and is indistinguishable from a scalar;
        # that narrow case is documented as unhandled.)
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
    #   - sentinel       → present object, none of `fields` → {} (shadows default)
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
            "stderr."
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

    raw, read_warnings = read_raw(args.agents, args.config_get, args.config, ("model", "iterations"))

    # Emit the subagent-id drift warnings once, before the output-mode split, so
    # every mode (plan, ordinary) reports them identically.
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
    for w in dict.fromkeys(read_warnings + resolve_warnings):
        sys.stderr.write(f"::warning::resolve-review-overrides: {w}\n")
    sys.stdout.write(json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
