#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# Trigger-time projection, invoked by this action after JSON validation.
# Preserve jq defaults, output ordering, and diagnostic behavior for existing installs.
# The migration freshness scan reads this file, including comments: keep superseded
# config keys in bracket notation and match superseded top-level families by shape.
set -euo pipefail
case "${CONFIG_COMMAND:-}" in
  command) REQUIRED_FAMILIES="prflow prflow_version" ;;
  implement) REQUIRED_FAMILIES="prflow prflow_implement prflow_version" ;;
  *) echo "::error::read-project-config command must be command or implement"; exit 1 ;;
esac
ENABLED=$(echo "$CONFIG_JSON" | jq -r '.workflows.prflow // false')
SUPERSEDED_ENABLE=$(echo "$CONFIG_JSON" | jq -r 'if (type=="object") and ((.workflows|type)=="object") and ((.workflows|has("prflow"))|not) and (.workflows|has("devflow")) then (.workflows["devflow"]|tostring) else "" end')
case "$SUPERSEDED_ENABLE" in
  "") : ;;
  true)
    echo "::error::.prflow/config.json still carries the superseded workflows[\"devflow\"] key and has no workflows.prflow, but this workflow reads workflows.prflow — so it resolves as DISABLED and every trigger silently does nothing. This is a PARTIAL upgrade: a hand-edited shipped workflow was preserved rather than refreshed, so the config-key migration was refused while this file was already refreshed. Merge any .github/workflows/*.prflow-new sidecar left beside a hand-edited workflow, then re-run install.sh --apply so the workflow read and the config key move together."
    exit 1 ;;
  *)
    echo "::warning::.prflow/config.json still carries the superseded workflows[\"devflow\"] key and has no workflows.prflow. This workflow reads workflows.prflow, so it is disabled — which matches the superseded key's own value, but the key is un-migrated. Re-run install.sh --apply to migrate it." ;;
esac
STRAY_FAMILIES=$(echo "$CONFIG_JSON" | jq -r '
  if type != "object" then ""
  else
    (keys) as $k
    | (any($k[]; test("^prflow(_|$)"))) as $has_canon
    | if $has_canon then ($k | map(select(test("^devflow(_|$)"))) | join(" ")) else "" end
  end')
if [ -n "$STRAY_FAMILIES" ]; then
  for fam in $STRAY_FAMILIES; do
    echo "::warning::.prflow/config.json carries the superseded top-level config key '$fam' beside a canonical prflow* family. Its keys are ignored — they resolve to their built-in defaults, so any tool grant, allowlist narrowing, or provider selection written under '$fam' silently does nothing. Run /prflow:init to migrate the Tier 1 config keys, then delete the stray '$fam' object."
  done
fi
ALLOWED_BOTS=$(echo "$CONFIG_JSON" | jq -r '.prflow.allowed_bots // empty')
if [ "$ENABLED" = "true" ] && [ -z "$ALLOWED_BOTS" ]; then
  echo "::error::prflow.allowed_bots is missing from .prflow/config.json (a pre-2.2.5 config may still use the old 'claude.allowed_bots' key — see CHANGELOG 2.2.5 migration)"
  exit 1
fi
if [ "$ENABLED" = "true" ]; then
  MISSING_FAMILIES=$(echo "$CONFIG_JSON" | jq -r --arg fams "$REQUIRED_FAMILIES" '
    if type != "object" then $fams | split(" ") | join(" ")
    else ($fams | split(" ")) - [keys[]] | join(" ") end')
  if [ -n "$MISSING_FAMILIES" ]; then
    echo "::error::.prflow/config.json is missing the config key famil(ies): $MISSING_FAMILIES. If this repository still carries the superseded devflow_* names, run /prflow:init to migrate the whole Tier 1 set atomically; every read below would otherwise silently resolve to its default."
    exit 1
  fi
fi
{
  echo "enabled=$ENABLED"
  echo "base_branch=$(echo "$CONFIG_JSON" | jq -r '.base_branch')"
  echo "claude_model=$(echo "$CONFIG_JSON" | jq -r '.claude_model')"
  echo "allowed_bots=$ALLOWED_BOTS"
  echo "allowed_users=$(echo "$CONFIG_JSON" | jq -r '.prflow.allowed_users // "*"')"
  if [ "$CONFIG_COMMAND" = "implement" ]; then
    echo "effort=$(echo "$CONFIG_JSON" | jq -r '.prflow_implement.effort // "high"')"
  else
    echo "effort=$(echo "$CONFIG_JSON" | jq -r '.prflow.effort // "high"')"
  fi
  if [ "$CONFIG_COMMAND" = "implement" ]; then
    echo "allowed_tools_extra=$(echo "$CONFIG_JSON" | jq -r --arg ws "$GITHUB_WORKSPACE" '.prflow_implement.allowed_tools // [] | (if $ws == "" then . else map(if type == "string" then sub("^Bash\\(/home/runner/work/[^/]+/[^/]+/"; "Bash(" + $ws + "/") else . end) end) | if length > 0 then "," + join(",") else "" end')"
  else
    echo "allowed_tools_extra=$(echo "$CONFIG_JSON" | jq -r '.prflow.allowed_tools // [] | if length > 0 then "," + join(",") else "" end')"
  fi
  echo "prflow_version=$(echo "$CONFIG_JSON" | jq -r '.prflow_version // empty')"
  echo "prflow_repo=$(echo "$CONFIG_JSON" | jq -r 'try (.prflow_repo | strings | select(. != "")) catch empty')"
  if [ "$CONFIG_COMMAND" = "implement" ]; then
    echo "workpad_marker=$(echo "$CONFIG_JSON" | jq -r '.prflow.workpad_marker // "<!-- prflow:workpad -->"')"
  fi
} >> "$GITHUB_OUTPUT"
PRFLOW_REPO_TYPE=$(echo "$CONFIG_JSON" | jq -r 'if (.prflow_repo != null) and ((.prflow_repo | type) != "string") then (.prflow_repo | type) else empty end')
if [ -n "$PRFLOW_REPO_TYPE" ]; then
  echo "::warning::prflow_repo has non-string JSON type '$PRFLOW_REPO_TYPE' in .prflow/config.json; treating it as empty (the public repository)"
fi
CLAUDE_CODE_EXECUTABLE_RAW=$(echo "$CONFIG_JSON" | jq -r 'try (.setup.claude_code_executable | select(. != null) | tostring | select(. != "") | "set") catch "set"')
CLAUDE_CODE_EXECUTABLE=$(echo "$CONFIG_JSON" | jq -r 'try (.setup.claude_code_executable // empty | strings | select(test("[\n\r]") | not) | select(test("^[[:space:]]*$") | not)) catch empty')
if [ -n "$CLAUDE_CODE_EXECUTABLE_RAW" ] && [ -z "$CLAUDE_CODE_EXECUTABLE" ]; then
  echo "::warning::setup.claude_code_executable is set but was rejected (non-string leaf, embedded newline/CR, or whitespace-only); falling back to the action's automatic Claude Code install."
fi
echo "claude_code_executable=$CLAUDE_CODE_EXECUTABLE" >> "$GITHUB_OUTPUT"
