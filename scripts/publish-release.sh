#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
#
# Tag the merge-time version bump and publish its GitHub Release (issue #953).
#
# .github/workflows/version-consolidate.yml calls this immediately after it pushes the
# `chore: bump version` commit, so the release tag names the exact tree whose docs the
# same commit repinned — the docs at tag vN say vN. Extracted from the workflow (rather
# than left inline) because it SELECTS branches and COMPOSES user-facing messages, which
# CLAUDE.md requires be drivable by lib/test/run.sh: an inline `if` chain is a selection
# the suite cannot catch defeated.
#
# Usage:
#   scripts/publish-release.sh --version <N.N.N> [--notes-file <path>] [--repo <owner/repo>]
#                              [--remote <name>] [--commit <ref>] [--release <mode>]
#                              [--bump <patch|minor|major>]
#
#   --release always       publish a GitHub Release for every tag (the default — a hand
#                          re-run intends to publish the one it names)
#   --release never        create the annotated tag only
#   --release minor-major  publish only when --bump names a `minor` or `major` bump; a
#                          `patch` bump is tagged and not announced. This is what
#                          .github/workflows/version-consolidate.yml passes.
#
# WHY THE WORKFLOW SELECTS `minor-major` (issue #970). Every merge carrying a changeset
# triggers a bump, and every published Release emails every watcher subscribed to
# "Releases" or "All Activity". Measured on 2026-07-29 that was ten Releases in one day —
# v2.26.7 (05:52) through v2.28.3 (23:50), roughly one every two hours — which is not a
# usable notification stream. A git tag raises no such notification, so tagging EVERY bump
# keeps pinned install URLs resolving and reproducibility unchanged; only the announcement
# becomes conditional.
#
# The coupling that made `always` the original choice is gone: the three install docs used
# to send readers to the `releases/latest` page, which resolves to the newest *Release* and
# would therefore name a version older than the pin those same docs carry. They now name
# the Tags page for the current version and keep the Releases page as the feature-release
# announcement channel, so a patch tag with no Release of its own leaves no documented link
# naming a superseded version. The derived version pins (scripts/version_pins.py) are
# untouched by this: they track the newest TAG, which is still every bump.
#
# The bump kind is not inferred from a version diff — `scripts/consolidate-changesets.py`
# already computes the single highest pending bump and hands it over through its
# `--emit-bump-to` side channel. An UNESTABLISHED bump kind is never collapsed onto
# `patch`: under `minor-major` an empty --bump tags and then fails loud, because guessing
# would silently suppress a release announcement nobody chose to suppress.
#
# Every step is idempotent: an existing remote tag or Release is reported and left alone,
# so a re-run never fails on work already done. The tag-existence VERIFICATION after the
# push is the network-side half of the release-pin drift guard — the offline half
# (`scripts/version_pins.py --check`) runs in the suite, which is network-free by contract.
set -euo pipefail

_SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/resolve-gh.sh
. "$_SELF_DIR/../lib/resolve-gh.sh"
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"

VERSION=""
NOTES_FILE=""
REPO="${GITHUB_REPOSITORY:-}"
REMOTE="origin"
COMMIT="HEAD"
RELEASE_MODE="always"
BUMP_KIND=""

die() { printf 'publish-release.sh: %s\n' "$1" >&2; exit 2; }

while [ "$#" -gt 0 ]; do
  case "$1" in
    --version)      VERSION="${2:-}"; shift 2 ;;
    --notes-file)   NOTES_FILE="${2:-}"; shift 2 ;;
    --repo)         REPO="${2:-}"; shift 2 ;;
    --remote)       REMOTE="${2:-}"; shift 2 ;;
    --commit)       COMMIT="${2:-}"; shift 2 ;;
    --release)      RELEASE_MODE="${2:-}"; shift 2 ;;
    --bump)         BUMP_KIND="${2:-}"; shift 2 ;;
    *)              die "unknown argument '$1'" ;;
  esac
done

case "$VERSION" in
  '') die "--version is required (an N.N.N string)" ;;
  *[!0-9.]*|*..*|.*|*.) die "--version '$VERSION' is not an N.N.N string" ;;
esac
# Shape check with builtins only: a value that decides an EMITTED result must not be
# derived through a non-preflight PATH tool (grep/sed/tr are not preflight-guaranteed).
case "$VERSION" in
  *.*.*.*) die "--version '$VERSION' is not an N.N.N string" ;;
  *.*.*)   : ;;
  *)       die "--version '$VERSION' is not an N.N.N string" ;;
esac

case "$RELEASE_MODE" in
  always|never|minor-major) : ;;
  *) die "--release '$RELEASE_MODE' is not one of: always, never, minor-major" ;;
esac

# A MALFORMED --bump is a caller bug and is rejected before anything happens; an ABSENT one
# is a different event (the consolidator's side channel produced nothing) and is handled at
# the release decision below, after the tag exists. Never conflated: one is a typo, the
# other is an unestablished measurement.
case "$BUMP_KIND" in
  ''|patch|minor|major) : ;;
  *) die "--bump '$BUMP_KIND' is not one of: patch, minor, major" ;;
esac

TAG="v$VERSION"

# Three-way remote-tag probe. `git ls-remote --exit-code` distinguishes its own two
# answers: 0 = the ref resolves, 2 = the query succeeded and matched nothing. ANY other
# status is the query itself failing (no network, bad remote, auth), which is NOT
# evidence of absence — folding it into "absent" would route a connectivity blip into
# the create/POST path and misattribute a probe-time problem to the mutation.
# Echoes the status; the callers branch on it.
_tag_probe() {
  local rc=0
  git ls-remote --exit-code --tags "$REMOTE" "refs/tags/$TAG" >/dev/null 2>&1 || rc=$?
  printf '%s\n' "$rc"
}

# ── 1. The annotated tag ────────────────────────────────────────────────────────────
_PROBE="$(_tag_probe)"
case "$_PROBE" in
  2) : ;;  # queried cleanly, no such tag — fall through to create it
  0) : ;;  # already there
  *) printf '::error::Could not determine whether %s exists on %s (git ls-remote exited ' "$TAG" "$REMOTE"
     printf '%s). Refusing to guess: an unreachable remote is not evidence the tag is absent.\n' "$_PROBE"
     exit 1 ;;
esac
if [ "$_PROBE" = "0" ]; then
  printf '::notice::%s already exists on %s — leaving it alone.\n' "$TAG" "$REMOTE"
else
  # Annotated (not lightweight): a release tag carries its own object, date and message,
  # and `git describe` prefers it.
  git tag -a "$TAG" -m "PRFlow $TAG" "$COMMIT"
  if git push "$REMOTE" "refs/tags/$TAG"; then
    printf '::notice::Created and pushed annotated tag %s.\n' "$TAG"
  else
    printf '::error::Pushed the version bump but could not push %s. The docs in that ' "$TAG"
    printf 'commit pin a tag that does not exist; create it by hand.\n'
    exit 1
  fi
fi

# ── 2. Tag-existence verification (the network half of the drift guard) ─────────────
# A `git push` that reports success is not proof the ref landed — verify against the
# remote, because the commit we just pushed documents this tag as installable.
_PROBE="$(_tag_probe)"
if [ "$_PROBE" = "0" ]; then
  printf '::notice::Verified %s resolves on %s.\n' "$TAG" "$REMOTE"
elif [ "$_PROBE" = "2" ]; then
  printf '::error::%s does not resolve on %s after the tag push — the docs in this ' "$TAG" "$REMOTE"
  printf 'bump pin a release tag that does not exist.\n'
  exit 1
else
  # The verification query failed. Unknown is not "verified" — fail closed, but say which
  # of the two it is, so the operator retries the probe rather than hunting a lost ref.
  printf '::error::Could not verify %s on %s (git ls-remote exited %s). The tag push ' "$TAG" "$REMOTE" "$_PROBE"
  printf 'reported success but the verification query itself failed; re-run to re-probe.\n'
  exit 1
fi

# ── 3. The GitHub Release decision ──────────────────────────────────────────────────
# Reached only once the tag exists and is verified, so every arm below leaves the pinned
# install URLs resolving; only the announcement is at stake here.
case "$RELEASE_MODE" in
  never)
    printf '::notice::--release never — tag %s created, no GitHub Release published.\n' "$TAG"
    exit 0 ;;
  minor-major)
    case "$BUMP_KIND" in
      minor|major)
        printf '::notice::%s bump — tag %s created; publishing its GitHub Release.\n' "$BUMP_KIND" "$TAG" ;;
      patch)
        printf '::notice::patch bump — tag %s created, no GitHub Release published. Patch ' "$TAG"
        printf 'bumps are tagged (so pinned install URLs resolve) but not announced.\n'
        exit 0 ;;
      *)
        # Unknown is not "patch". Suppressing an announcement nobody chose to suppress is a
        # silent wrong answer; the tag is already pushed, so failing loud here costs only the
        # Release, which a re-run republishes idempotently.
        printf '::error::--release minor-major was selected but the bump kind is not '
        printf 'established (--bump was empty), so whether to publish %s cannot be decided. ' "$TAG"
        printf 'The tag is pushed; check the consolidator --emit-bump-to side channel and re-run.\n'
        exit 1 ;;
    esac ;;
esac

[ -n "$REPO" ] || die "--repo (or GITHUB_REPOSITORY) is required to publish a Release"

# REST via `gh api`, never `gh release create`: the porcelain resolves the repository
# through org-scoped GraphQL and fails silently under a repo-scoped installation token.
if "$DEVFLOW_GH" api "repos/$REPO/releases/tags/$TAG" >/dev/null 2>&1; then
  printf '::notice::A GitHub Release for %s already exists — leaving it alone.\n' "$TAG"
  exit 0
fi

set -- api --method POST "repos/$REPO/releases" \
  -f "tag_name=$TAG" -f "name=$TAG" \
  -F draft=false -F prerelease=false -f make_latest=true
# Both fallback causes publish the same pointer body — but they are NOT the same event and
# must not read as one. "No --notes-file was passed" is a caller CHOICE (a `--release`-only
# invocation, a hand re-run) and is unremarkable. "A --notes-file was named but is absent or
# empty" is an UPSTREAM ANOMALY: the consolidator's `--emit-entry-to` side channel produced
# nothing, which means the CHANGELOG entry assembly it shares with the bump misbehaved —
# smoothing that into the same normal-looking fallback hides a real defect behind a warning
# that reads like routine configuration.
if [ -z "$NOTES_FILE" ]; then
  printf '::notice::No --notes-file passed for %s; publishing with a CHANGELOG pointer.\n' "$TAG"
  set -- "$@" -f "body=See CHANGELOG.md for the [$VERSION] entry."
elif [ ! -s "$NOTES_FILE" ]; then
  printf '::warning::Release notes file %s is absent or empty, but was requested for %s — ' "$NOTES_FILE" "$TAG"
  printf 'the consolidator emitted no CHANGELOG entry body. Publishing with a CHANGELOG '
  printf 'pointer; investigate the --emit-entry-to side channel.\n'
  set -- "$@" -f "body=See CHANGELOG.md for the [$VERSION] entry."
else
  set -- "$@" -F "body=@$NOTES_FILE"
fi

if "$DEVFLOW_GH" "$@" >/dev/null; then
  printf '::notice::Published GitHub Release %s (marked latest).\n' "$TAG"
else
  printf '::error::Tag %s is pushed, but publishing its GitHub Release failed. ' "$TAG"
  printf 'The Releases page the install docs cite is now missing this release.\n'
  exit 1
fi
