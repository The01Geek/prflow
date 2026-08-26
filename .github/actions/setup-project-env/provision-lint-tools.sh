#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# ============================================================================
# provision-lint-tools.sh — install the manifest's bounded lint toolchain BEFORE
# the model runs (issue #1388).
# ============================================================================
# Manifest validation, platform resolution, and the compatibility-marker
# readiness gate live in the Python helpers (scripts/lint_provision.py,
# scripts/install_state.py); this script orchestrates: gate on readiness,
# resolve each tool's artifact, download → verify the pinned ARCHIVE digest →
# extract → install run-local (NO sudo) → verify the executable reports the
# pinned version. A binary already at the destination, or on PATH, is reused
# only after re-passing that version check. Every INTEGRITY failure fails
# CLOSED naming the tool, before the model runs — missing installer primitive,
# checksum mismatch, archive that will not extract, wrong version, network
# failure, unwritable target, unknown tool. An unsupported platform tuple
# degrades instead: reuse a version-matching PATH tool, else warn and continue.
#
# Required environment:
#   LINT_MANIFEST      path to .prflow/lint-manifest.json
#   INSTALL_STATE      path to .prflow/install-state.json (the compatibility marker)
#   DEST_BIN           directory to install the tool executables into (added to PATH)
#   TARGET_OS          linux | macos | windows
#   TARGET_ARCH        x86_64 | arm64
#   SCRIPTS_DIR        directory holding lint_provision.py + install_state.py
# Optional (overridable so lib/test can drive the fail-closed arms offline):
#   INSTALLER_VERSION  overrides the marker's installer_version (cache-key component);
#                      derived from the marker after the readiness gate when unset
#   TOOLS              space-separated tool list (default: the manifest's own tool set)
#   LINTPROV_PYTHON    python3 interpreter (default python3)
#   LINTPROV_CURL      downloader; called as "$LINTPROV_CURL" -fsSL -o OUT URL (default curl)
#   LINTPROV_TAR       tar extractor (default tar)
#   LINTPROV_UNZIP     zip extractor (default unzip)
#   LINTPROV_SKIP_PATH_REUSE  set to 1 to skip the pre-provisioned-runner PATH
#                      reuse check on an established plan, forcing the download
#                      path (the unsupported-plan PATH check is unaffected)
# ============================================================================
set -euo pipefail

PY="${LINTPROV_PYTHON:-python3}"
CURL="${LINTPROV_CURL:-curl}"
TAR="${LINTPROV_TAR:-tar}"
UNZIP="${LINTPROV_UNZIP:-unzip}"
# TOOLS is derived from the validated manifest below, after the readiness gate. An
# explicit value still wins (the suite drives one tool at a time).

# Set to the in-flight work directory while one exists; _die removes it. `exit` does
# NOT run a RETURN trap, so every fail-closed arm leaked its mktemp -d without this,
# and the suite drives this helper repeatedly in one process.
_WORKDIR=""

_die() {
  # $1 = tool (or "-"), $2 = reason. One diagnostic per fail-closed arm so a
  # reader can tell which tool and which condition detonated.
  [ -n "$_WORKDIR" ] && rm -rf "$_WORKDIR"
  printf 'provision-lint-tools: %s: %s\n' "$1" "$2" >&2
  exit 1
}

_have() { command -v "$1" >/dev/null 2>&1; }

# Match the pinned version as a WHOLE token in the tool's --version output, never a
# substring: pinned "1.2" must NOT match reported "1.24.1". Portable ERE token
# boundary (no GNU \b, which BSD grep silently ignores). $1 = reported text, $2 = version.
_version_token_match() {
  local esc="${2//./\\.}"
  printf '%s' "$1" | grep -Eq "(^|[^0-9.])${esc}([^0-9.]|\$)"
}

# sha256 of a file via the trusted python interpreter (no sha256sum dependency —
# it is not preflight-guaranteed and diverges across BSD/GNU).
_digest() {
  "$PY" - "$1" <<'PY'
import hashlib, sys
with open(sys.argv[1], "rb") as fh:
    print("sha256:" + hashlib.sha256(fh.read()).hexdigest())
PY
}

for v in LINT_MANIFEST INSTALL_STATE DEST_BIN TARGET_OS TARGET_ARCH SCRIPTS_DIR; do
  eval "val=\${$v:-}"
  [ -n "$val" ] || _die - "missing required environment variable $v"
done

_have "$PY" || _die - "installer primitive not found: python3 ($PY)"

# Refuse the WHOLE pass before touching any tool: a component digest that
# disagrees means the readers and the manifest may not understand each other.
if ! ready="$("$PY" "$SCRIPTS_DIR/install_state.py" verify --state "$INSTALL_STATE" --manifest "$LINT_MANIFEST" 2>&1)"; then
  _die - "install-state readiness refused: ${ready#NOT-READY } — remedy: re-run the PRFlow installer (install.sh), which republishes the marker over the components actually installed in this tree"
fi

# Derive the tool set from the manifest the gate just validated, so the shipped set
# has ONE source: a hardcoded list that omitted a manifest tool left that tool
# silently never provisioned while the readiness gate still reported READY.
if [ -z "${TOOLS:-}" ]; then
  TOOLS="$("$PY" -c 'import json,sys; print(" ".join(json.load(open(sys.argv[1]))["tools"]))' "$LINT_MANIFEST")" \
    || _die - "could not derive the tool set from the manifest"
  [ -n "$TOOLS" ] || _die - "manifest declares no tools to provision"
fi

# The marker validated above, so its installer_version is present and typed. An
# explicit INSTALLER_VERSION env overrides it (tests); otherwise derive it here.
INSTALLER_VERSION="${INSTALLER_VERSION:-}"
if [ -z "$INSTALLER_VERSION" ]; then
  INSTALLER_VERSION="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["installer_version"])' "$INSTALL_STATE")" \
    || _die - "could not read installer_version from the validated marker"
fi

mkdir -p "$DEST_BIN" 2>/dev/null || _die - "unwritable target: cannot create $DEST_BIN"

PROVISIONED=""
UNPROVISIONED=""

_provision_one() {
  local tool="$1"
  local plan rc plan_err plan_err_file
  # Keep stderr OUT of $plan: the tab-parse below splits $plan into fields, so
  # interpreter noise merged via 2>&1 would corrupt the field split.
  plan_err_file="$(mktemp)"
  set +e
  plan="$("$PY" "$SCRIPTS_DIR/lint_provision.py" plan \
    --manifest "$LINT_MANIFEST" --tool "$tool" --os "$TARGET_OS" --arch "$TARGET_ARCH" 2>"$plan_err_file")"
  rc=$?
  set -e
  plan_err="$(<"$plan_err_file")" || plan_err=""
  rm -f "$plan_err_file"
  if [ "$rc" -eq 3 ]; then
    local unsupported_version sys_unsupported
    unsupported_version="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["tools"][sys.argv[2]]["version"])' \
      "$LINT_MANIFEST" "$tool" 2>/dev/null || true)"
    sys_unsupported="$(command -v "$tool" 2>/dev/null || true)"
    if [ -n "$sys_unsupported" ] && [ -n "$unsupported_version" ] \
       && _version_token_match "$("$sys_unsupported" --version 2>&1 || true)" "$unsupported_version"; then
      printf 'provision-lint-tools: %s: reused pre-provisioned %s (%s) from the runner image\n' \
        "$tool" "$sys_unsupported" "$unsupported_version"
      PROVISIONED="$PROVISIONED $tool"
      return 0
    fi
    printf 'provision-lint-tools: %s: unsupported-lint-platform (%s/%s); continuing without provisioning this tool\n' \
      "$tool" "$TARGET_OS" "$TARGET_ARCH" >&2
    printf '::warning::provision-lint-tools: %s: unsupported-lint-platform (%s/%s) and no pre-provisioned %s at pinned version %s on PATH; continuing without provisioning this tool\n' \
      "$tool" "$TARGET_OS" "$TARGET_ARCH" "$tool" "${unsupported_version:-unknown}" >&2
    UNPROVISIONED="$UNPROVISIONED $tool"
    return 0
  elif [ "$rc" -eq 4 ]; then
    # Unknown tool ≠ unsupported platform: nothing can provision it, so skipping
    # it like a platform gap would silently drop a lint the manifest never covers.
    _die "$tool" "unknown-lint-tool: not in the resolver's known tool set"
  elif [ "$rc" -ne 0 ]; then
    _die "$tool" "manifest resolution failed: ${plan}${plan_err:+ ${plan_err}}"
  fi

  local digest archive_type member strategy version url
  IFS=$'\t' read -r digest archive_type member strategy version url <<<"$plan"
  [ -n "$url" ] || _die "$tool" "manifest resolution returned no download URL"

  # cache_key appears in log lines ONLY — the cross-run cache gate is action.yml's
  # hashFiles key; do not wire this value into cache restore/save logic.
  local cache_key
  cache_key="$("$PY" "$SCRIPTS_DIR/lint_provision.py" cache-key \
    --manifest "$LINT_MANIFEST" --tool "$tool" --os "$TARGET_OS" --arch "$TARGET_ARCH" \
    --installer-version "$INSTALLER_VERSION")" \
    || _die "$tool" "cache-key computation failed"

  local dest="$DEST_BIN/$member"

  # Never reuse a cached executable without re-running the version check: the cache
  # slot is keyed on the tuple, but a restored binary is otherwise unverified bytes.
  if [ -x "$dest" ]; then
    local cached_ver
    cached_ver="$("$dest" --version 2>&1 || true)"
    if _version_token_match "$cached_ver" "$version"; then
      printf 'provision-lint-tools: %s: reused verified install (%s, key %s)\n' "$tool" "$version" "$cache_key"
      PROVISIONED="$PROVISIONED $tool"
      return 0
    fi
  fi

  # PATH, not $dest — this must never substitute for the cache-restore check above.
  # LINTPROV_SKIP_PATH_REUSE=1 keeps the download path exercised in tests.
  if [ "${LINTPROV_SKIP_PATH_REUSE:-}" != "1" ]; then
    local sys
    sys="$(command -v "$tool" 2>/dev/null || true)"
    if [ -n "$sys" ] && [ "$sys" != "$dest" ] \
       && _version_token_match "$("$sys" --version 2>&1 || true)" "$version"; then
      printf 'provision-lint-tools: %s: reused pre-provisioned %s (%s) from the runner image\n' \
        "$tool" "$sys" "$version"
      PROVISIONED="$PROVISIONED $tool"
      return 0
    fi
  fi

  # Installer primitives for this artifact's strategy.
  _have "$CURL" || _die "$tool" "installer primitive not found: downloader ($CURL)"
  case "$strategy" in
    extract-tar) _have "$TAR" || _die "$tool" "installer primitive not found: tar ($TAR)" ;;
    extract-zip) _have "$UNZIP" || _die "$tool" "installer primitive not found: unzip ($UNZIP)" ;;
    *) _die "$tool" "unknown extraction strategy $strategy" ;;
  esac

  local work archive extract_dir
  work="$(mktemp -d)"
  _WORKDIR="$work"
  # shellcheck disable=SC2064
  trap "rm -rf '$work'; _WORKDIR=''" RETURN
  archive="$work/artifact"
  extract_dir="$work/x"
  mkdir -p "$extract_dir"

  # Download — a network failure fails closed naming the tool.
  "$CURL" -fsSL -o "$archive" "$url" || _die "$tool" "network failure downloading $url"
  [ -s "$archive" ] || _die "$tool" "network failure: empty download from $url"

  # Verify the pinned digest BEFORE extracting — a checksum mismatch is a
  # supply-chain refusal, not a warning.
  local got
  got="$(_digest "$archive")" || _die "$tool" "digest computation failed"
  [ "$got" = "$digest" ] || _die "$tool" "checksum mismatch: expected $digest got $got"

  # Extract per the closed strategy — an archive that will not extract is refused.
  case "$strategy" in
    extract-tar) "$TAR" -xf "$archive" -C "$extract_dir" 2>/dev/null || _die "$tool" "archive mismatch: $archive_type archive did not extract" ;;
    extract-zip) "$UNZIP" -q -o "$archive" -d "$extract_dir" 2>/dev/null || _die "$tool" "archive mismatch: $archive_type archive did not extract" ;;
  esac

  # Locate the member anywhere in the extracted tree (upstream archives nest it
  # under a versioned directory) and install it run-local, no sudo.
  local found
  found="$(find "$extract_dir" -type f -name "$member" -print 2>/dev/null | head -n 1 || true)"
  [ -n "$found" ] || _die "$tool" "archive mismatch: member $member not found in archive"
  install -m 0755 "$found" "$dest" 2>/dev/null || cp "$found" "$dest" 2>/dev/null \
    || _die "$tool" "unwritable target: cannot install into $DEST_BIN"
  chmod 0755 "$dest" 2>/dev/null || _die "$tool" "unwritable target: cannot chmod $dest"

  # Verify the installed executable reports the manifest's exact version (one exec).
  local reported
  reported="$("$dest" --version 2>&1)" || _die "$tool" "installed executable is not runnable"
  _version_token_match "$reported" "$version" \
    || _die "$tool" "wrong version: $dest does not report $version"

  printf 'provision-lint-tools: %s: installed %s (%s), version-verified (key %s)\n' \
    "$tool" "$member" "$version" "$cache_key"
  PROVISIONED="$PROVISIONED $tool"
}

for tool in $TOOLS; do
  _provision_one "$tool"
done

# Put the provisioned tools on PATH for later steps (before the model runs).
if [ -n "${GITHUB_PATH:-}" ]; then
  printf '%s\n' "$DEST_BIN" >> "$GITHUB_PATH"
fi
# Report only what actually landed: a tool that took the unsupported-platform
# degrade must not be listed as provisioned beside its own ::warning::.
if [ -n "$UNPROVISIONED" ]; then
  printf 'provision-lint-tools: readiness verified; provisioned:%s; unprovisioned (degraded):%s\n' \
    "${PROVISIONED:- (none)}" "$UNPROVISIONED"
else
  printf 'provision-lint-tools: readiness verified; provisioned:%s\n' "${PROVISIONED:- (none)}"
fi
