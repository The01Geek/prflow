#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# ============================================================================
# provision-lint-tools.sh — install the manifest's bounded lint toolchain BEFORE
# the model runs (issue #1388). Sibling of resolve-node-cache.sh: it travels with
# the setup-project-env composite action and is unit-tested from lib/test/.
# ============================================================================
# The heavy lifting — manifest validation, platform resolution, the
# compatibility-marker readiness gate — lives in the trusted Python helpers
# (scripts/lint_provision.py, scripts/install_state.py). This script is the thin
# orchestrator: it gates on readiness, resolves each tool's artifact, then
# downloads → verifies the pinned digest → extracts → installs run-local (NO
# sudo) → verifies the executable's version, and re-verifies a restored cache
# under the same digest. Every failure fails CLOSED, naming the tool, BEFORE the
# model runs — a missing installer primitive, a checksum mismatch, an archive
# that will not extract, the wrong version, a network failure, an unwritable
# target, or an unsupported platform tuple.
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
#   TOOLS              space-separated tool list (default "shellcheck ruff")
#   LINTPROV_PYTHON    python3 interpreter (default python3)
#   LINTPROV_CURL      downloader; called as "$LINTPROV_CURL" -fsSL -o OUT URL (default curl)
#   LINTPROV_TAR       tar extractor (default tar)
#   LINTPROV_UNZIP     zip extractor (default unzip)
# ============================================================================
set -euo pipefail

PY="${LINTPROV_PYTHON:-python3}"
CURL="${LINTPROV_CURL:-curl}"
TAR="${LINTPROV_TAR:-tar}"
UNZIP="${LINTPROV_UNZIP:-unzip}"
TOOLS="${TOOLS:-shellcheck ruff}"

_die() {
  # $1 = tool (or "-"), $2 = reason. One diagnostic per fail-closed arm so a
  # reader can tell which tool and which condition detonated.
  printf 'provision-lint-tools: %s: %s\n' "$1" "$2" >&2
  exit 1
}

_have() { command -v "$1" >/dev/null 2>&1; }

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

# Readiness gate — refuse the WHOLE provisioning pass before touching any tool
# when the compatibility marker is absent, a component digest disagrees (a
# version skew in either direction, or an interrupted publication), or the
# manifest is missing/invalid.
if ! ready="$("$PY" "$SCRIPTS_DIR/install_state.py" verify --state "$INSTALL_STATE" --manifest "$LINT_MANIFEST" 2>&1)"; then
  _die - "install-state readiness refused: ${ready#NOT-READY }"
fi

# The marker validated above, so its installer_version is present and typed. An
# explicit INSTALLER_VERSION env overrides it (tests); otherwise derive it here.
INSTALLER_VERSION="${INSTALLER_VERSION:-}"
if [ -z "$INSTALLER_VERSION" ]; then
  INSTALLER_VERSION="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["installer_version"])' "$INSTALL_STATE")" \
    || _die - "could not read installer_version from the validated marker"
fi

mkdir -p "$DEST_BIN" 2>/dev/null || _die - "unwritable target: cannot create $DEST_BIN"

_provision_one() {
  local tool="$1"
  local plan rc
  set +e
  plan="$("$PY" "$SCRIPTS_DIR/lint_provision.py" plan \
    --manifest "$LINT_MANIFEST" --tool "$tool" --os "$TARGET_OS" --arch "$TARGET_ARCH" 2>&1)"
  rc=$?
  set -e
  if [ "$rc" -eq 3 ]; then
    _die "$tool" "unsupported-lint-platform ($TARGET_OS/$TARGET_ARCH)"
  elif [ "$rc" -ne 0 ]; then
    _die "$tool" "manifest resolution failed: $plan"
  fi

  local digest archive_type member strategy version url
  IFS=$'\t' read -r digest archive_type member strategy version url <<<"$plan"
  [ -n "$url" ] || _die "$tool" "manifest resolution returned no download URL"

  local cache_key
  cache_key="$("$PY" "$SCRIPTS_DIR/lint_provision.py" cache-key \
    --manifest "$LINT_MANIFEST" --tool "$tool" --os "$TARGET_OS" --arch "$TARGET_ARCH" \
    --installer-version "$INSTALLER_VERSION")" \
    || _die "$tool" "cache-key computation failed"

  local dest="$DEST_BIN/$member"

  # Cache re-verification: a restored executable is trusted only after it
  # re-passes the version check under this run's resolved version. The digest is
  # bound into the cache key {OS, arch, tool, version, digest, installer}, so a
  # restore under a changed tuple lands under a different key and is a miss.
  if [ -x "$dest" ] && "$dest" --version 2>&1 | grep -qF "$version"; then
    printf 'provision-lint-tools: %s: cache hit re-verified (%s, key %s)\n' "$tool" "$version" "$cache_key"
    return 0
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
  # shellcheck disable=SC2064
  trap "rm -rf '$work'" RETURN
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
  found="$(find "$extract_dir" -type f -name "$member" -print -quit 2>/dev/null || true)"
  [ -n "$found" ] || _die "$tool" "archive mismatch: member $member not found in archive"
  install -m 0755 "$found" "$dest" 2>/dev/null || cp "$found" "$dest" 2>/dev/null \
    || _die "$tool" "unwritable target: cannot install into $DEST_BIN"
  chmod 0755 "$dest" 2>/dev/null || _die "$tool" "unwritable target: cannot chmod $dest"

  # Verify the installed executable reports the manifest's exact version.
  "$dest" --version >/dev/null 2>&1 || _die "$tool" "installed executable is not runnable"
  "$dest" --version 2>&1 | grep -qF "$version" \
    || _die "$tool" "wrong version: $dest does not report $version"

  printf 'provision-lint-tools: %s: installed %s (%s), version-verified (key %s)\n' \
    "$tool" "$member" "$version" "$cache_key"
}

for tool in $TOOLS; do
  _provision_one "$tool"
done

# Put the provisioned tools on PATH for later steps (before the model runs).
if [ -n "${GITHUB_PATH:-}" ]; then
  printf '%s\n' "$DEST_BIN" >> "$GITHUB_PATH"
fi
printf 'provision-lint-tools: readiness verified; provisioned: %s\n' "$TOOLS"
