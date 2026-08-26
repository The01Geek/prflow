#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# gh-fresh.sh — a `gh` wrapper that resolves the token at CALL time from the
# refresher-maintained token file, so agent-side `gh` invocations in a
# >60-minute writer-job run ride the fresh refresher-maintained token rather than
# the expiring job-start token whenever the refresher is healthy (issue #487). When
# the refresher was defeated (token file absent/empty), the wrapper DEGRADES to the
# ambient token with a stderr breadcrumb — see main()'s degrade path below; it is a
# disclosed fail-safe, not an unconditional guarantee.
#
# It is wired by the install step (scripts/install-gh-wrapper.sh, issue #533)
# ahead of the real `gh` on PATH via GITHUB_PATH: direct skill-fence `gh` calls,
# PRFlow's own gh-callers (whose lib/resolve-gh.sh PATH probe finds the wrapper
# when DEVFLOW_GH is unset), and every post-claude step all resolve to it. The
# install step deliberately publishes NO process-global DEVFLOW_GH — that env
# value would persist into later job steps and outrank fixture PATH stubs in
# the repo test suite; DEVFLOW_GH stays an explicit caller/test override seam.
#
# Ambient-vs-chosen discrimination (AC "Ambient-vs-chosen credential
# discrimination"): claude-code-action exports the job-start token as BOTH
# GITHUB_TOKEN and GH_TOKEN into its process env, inherited by every agent
# subprocess. A "defer to any preset GH_TOKEN" rule would therefore leave every
# agent call on the expiring ambient token. So the wrapper discriminates by
# FINGERPRINT: the install step records a sha256 of the job-start token, and at
# call time the wrapper
#   * SUBSTITUTES the token-file credential when env GH_TOKEN is absent, OR when
#     its hash matches the recorded job-start fingerprint (the ambient
#     agent-session case — and devflow.yml's #356 flip step, whose GH_TOKEN is
#     that same job-start mint),
#   * DEFERS untouched when env GH_TOKEN's hash DIFFERS from the fingerprint (a
#     deliberately fresh mint: the #287 stall/review backstops), and
#   * also DEFERS — with a breadcrumb, never silently — when the comparison cannot
#     be established (the fingerprint file is unreadable, or no hash method works:
#     python3 first, then sha256sum/shasum), failing toward not clobbering a
#     deliberately-fresh backstop mint.
# It DEGRADES to a plain invocation — with a stderr breadcrumb, never silently —
# when the substitute decision was taken but the token file is absent/empty, and on
# a bad-credential failure (whichever path) appends one distinctive diagnostic line
# to stderr naming the expired-credential cause — a compaction-immune signal the
# fail-fast rule keys on — while preserving the real gh exit code.
#
# Output handling: the real gh's stdout streams through LIVE (via fd 3, teed to a temp
# copy only so the bad-credential signature can be scanned in it too); its stderr is
# CAPTURED for the run and re-emitted verbatim after the call returns (scanned for the
# same signature). For PRFlow's short, non-interactive REST `gh api`/`gh pr` calls this
# is invisible, but note two consequences: a long-running gh call's stderr is not shown
# live until it completes, and a caller that merges streams with `2>&1` sees all stderr
# after all stdout rather than interleaved. Exit code and normal-exit stdout/stderr
# content are always faithfully preserved. (If mktemp is unavailable the wrapper falls
# back to streaming stdout without a copy and scanning stderr only.)
#
# The real gh is invoked by an ABSOLUTE path captured at install time (env
# DEVFLOW_GH_REAL) — a name-based lookup would recurse into this wrapper, which
# the install step prepends to PATH.

set -uo pipefail

TOKEN_FILE="${DEVFLOW_GH_TOKEN_FILE:-${RUNNER_TEMP:-/tmp}/devflow-gh-token}"
FINGERPRINT_FILE="${DEVFLOW_GH_FINGERPRINT_FILE:-${RUNNER_TEMP:-/tmp}/devflow-gh-fingerprint}"
REAL_GH="${DEVFLOW_GH_REAL:-}"

# The distinctive, re-derivable diagnostic the fail-fast prose rule greps for.
DIAG_LINE="devflow-gh-fresh: gh call failed with an expired/bad credential (HTTP 401 / Bad credentials) — the GitHub App installation token has likely expired; stop retrying (issue #487)."

# Resolve the real gh. It MUST be an absolute path so we never recurse into this
# wrapper (which is ahead of gh on PATH). If DEVFLOW_GH_REAL is unset, fall back
# to a best-effort search that excludes ourselves; if that fails, we cannot run.
resolve_real_gh() {
  if [ -n "$REAL_GH" ] && [ -x "$REAL_GH" ]; then printf '%s' "$REAL_GH"; return 0; fi
  # Best-effort PATH search excluding ourselves. Canonicalize BOTH our own path and each
  # candidate's DIRECTORY with `pwd -P` so a candidate reached via a symlinked (or
  # otherwise differently-spelled) PATH entry that points at THIS wrapper still compares
  # equal and is skipped — a raw string compare would miss it and recurse. Use
  # ${BASH_SOURCE[0]} (the script file, reliable even when $0 was rewritten or is a bare/
  # relative name) as our source. Inert on the shipped path: the install step always
  # exports an absolute DEVFLOW_GH_REAL, so the early return above fires and this walk
  # never runs in production.
  local src self self_dir cand cand_dir
  src="${BASH_SOURCE[0]:-$0}"
  self_dir="$(cd "$(dirname "$src")" 2>/dev/null && pwd -P)" || self_dir=""
  self="${self_dir:+$self_dir/}$(basename "$src")"
  local IFS=:
  for d in $PATH; do
    [ -x "$d/gh" ] || continue
    cand_dir="$(cd "$d" 2>/dev/null && pwd -P)" || continue
    cand="$cand_dir/gh"
    if [ "$cand" != "$self" ]; then printf '%s' "$cand"; return 0; fi
  done
  return 1
}

sha256_of() {
  # python3 first (the preflight-guaranteed hash method — writer/reader symmetry
  # with install-gh-wrapper.sh, issue #544): sha256sum/shasum + awk are not
  # PATH-guaranteed on every runner, and before this convergence a hash-tool-less
  # host silently degraded every fingerprinted call to the defer arm. The value is
  # captured and checked non-empty before printing, so a python3 that is present
  # but crashes mid-write falls through to the tool arms instead of emitting a
  # partial hash. sha256sum (ubuntu runners) and shasum (macOS) stay as fallbacks;
  # only when no method works at all does this return 1 (decide()'s disclosed
  # could-not-establish defer arm — a preserved outcome, not a new one).
  local h
  if command -v python3 >/dev/null 2>&1; then
    if h="$(printf '%s' "$1" | python3 -c 'import hashlib,sys; sys.stdout.write(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())' 2>/dev/null)" \
       && [ -n "$h" ]; then
      printf '%s' "$h"
      return 0
    fi
  fi
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$1" | sha256sum | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    printf '%s' "$1" | shasum -a 256 | awk '{print $1}'
  else
    return 1
  fi
}

# Decide whether to substitute the token-file credential or defer to the ambient
# env GH_TOKEN. Returns 0 to SUBSTITUTE, 1 to DEFER.
decide() {
  # ambient agent session: no explicit token → use the fresh one.
  [ -z "${GH_TOKEN:-}" ] && return 0
  # env GH_TOKEN is present: compare its hash to the recorded job-start fingerprint.
  # A match is the ambient job-start token → substitute (this INCLUDES devflow.yml's #356
  # flip step, whose GH_TOKEN is that same job-start mint — see the header); a mismatch is
  # a deliberately fresh mint (#287 backstops) → defer untouched.
  local fp cur
  fp="$(cat "$FINGERPRINT_FILE" 2>/dev/null || true)"
  cur="$(sha256_of "$GH_TOKEN" 2>/dev/null || true)"
  # Could-not-establish the comparison (fingerprint file unreadable, or no
  # working hash method — python3/sha256sum/shasum) must NOT collapse silently onto the defer
  # path — a buried defer would ride the possibly-expired ambient token, the exact
  # failure this wrapper prevents. Fail toward NOT clobbering a deliberately-fresh
  # #287 backstop mint (defer), but emit a breadcrumb so the state is visible;
  # the two-strikes fail-fast rule then catches a genuinely-expired token.
  if [ -z "$fp" ] || [ -z "$cur" ]; then
    printf 'devflow-gh-fresh: could not establish the job-start fingerprint comparison (fingerprint file unreadable, or no working hash method — python3/sha256sum/shasum); deferring to the ambient GH_TOKEN — if that is the expired job-start token, gh will 401 and the fail-fast rule applies.\n' >&2
    return 1
  fi
  [ "$cur" = "$fp" ]
}

main() {
  local real
  real="$(resolve_real_gh)" || {
    printf 'devflow-gh-fresh: could not resolve the real gh binary (set DEVFLOW_GH_REAL)\n' >&2
    return 127
  }

  local token=""
  if decide; then
    if [ -f "$TOKEN_FILE" ]; then
      token="$(cat "$TOKEN_FILE" 2>/dev/null || true)"
    fi
    # The SUBSTITUTE decision was taken but the refresher-maintained token file is
    # absent, unreadable, or empty (e.g. the refresher was defeated at startup and
    # never wrote it). Degrading to the plain invocation is right, but never
    # silently — every call from here rides the ambient (possibly expiring
    # job-start) token, the exact state this wrapper exists to prevent. Mirrors
    # decide()'s could-not-establish breadcrumb.
    if [ -z "$token" ]; then
      printf 'devflow-gh-fresh: token file %s is absent or empty (was the refresher defeated at startup?); degrading to the plain invocation on the ambient token — if that is the expired job-start token, gh will 401 and the fail-fast rule applies.\n' "$TOKEN_FILE" >&2
    fi
  fi

  # Run the real gh. fd 3 carries the child's stdout to our real stdout LIVE; the
  # command substitution captures stderr. We ALSO tee stdout into a temp copy so the
  # bad-credential signature can be scanned in stdout as well as stderr (gh surfaces
  # 401s on stderr, but a subcommand that ever emitted the signature on stdout would
  # otherwise slip the compaction-immune signal). If mktemp is unavailable, fall back
  # to the stderr-only scan (stdout still streams live via fd 3).
  # `set -o pipefail` (top of file) makes the `gh | tee` pipeline's status the real gh's,
  # so a failing gh keeps its exit code through the tee. The reverse coupling is
  # deliberate and fail-CLOSED: if `tee` itself fails (e.g. the temp copy becomes
  # unwritable mid-call), pipefail flips an otherwise-successful gh into a non-zero
  # wrapper exit — the caller sees a (spurious) failure and retries, which is the SAFE
  # direction. It never masks a real gh failure as success (capturing gh's rc separately
  # to dodge this would fail OPEN — an unwritable rc-sink would default a failed call to
  # rc 0 — the wrong trade for a credential wrapper), so the coupling stands as-is.
  local err rc outcap="" SIG='HTTP 401|Bad credentials|fatal: Authentication failed for'
  outcap="$(mktemp "${TMPDIR:-/tmp}/devflow-gh-fresh-out.XXXXXX" 2>/dev/null)" || outcap=""
  exec 3>&1
  if [ -n "$outcap" ]; then
    if [ -n "$token" ]; then
      err="$( { GH_TOKEN="$token" "$real" "$@" | tee "$outcap" >&3; } 2>&1 )"; rc=$?
    else
      # defer path, or substitute-but-token-file-absent degrade path: plain invocation.
      err="$( { "$real" "$@" | tee "$outcap" >&3; } 2>&1 )"; rc=$?
    fi
  else
    if [ -n "$token" ]; then
      err="$( { GH_TOKEN="$token" "$real" "$@"; } 2>&1 1>&3 )"; rc=$?
    else
      err="$( { "$real" "$@"; } 2>&1 1>&3 )"; rc=$?
    fi
  fi
  exec 3>&-

  # Re-emit the captured stderr verbatim.
  [ -n "$err" ] && printf '%s\n' "$err" >&2

  # On a bad-credential failure, append the distinctive diagnostic (both paths), scanning
  # the COMBINED stream (captured stderr AND the captured stdout copy). The
  # `Authentication failed` alternative is ANCHORED to `fatal: Authentication failed for`
  # (git's exact message), not a bare `Authentication failed`: gh subcommands that shell
  # out to git (e.g. `gh repo sync`, `gh pr checkout`) surface an expired-token failure as
  # git's `fatal: Authentication failed for '<url>'`, NOT an `HTTP 401` — the anchor keeps
  # that git-shelling coverage (pinned by arm26) while shrinking the collateral surface so
  # an unrelated failure whose text merely contains the two words does not trip the
  # two-strikes abort.
  if [ "$rc" -ne 0 ] \
     && { printf '%s' "$err" | grep -qiE "$SIG" \
          || { [ -n "$outcap" ] && grep -qiE "$SIG" "$outcap" 2>/dev/null; }; }; then
    printf '%s\n' "$DIAG_LINE" >&2
  fi
  [ -n "$outcap" ] && rm -f "$outcap" 2>/dev/null
  return "$rc"
}

main "$@"
