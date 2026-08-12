#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# measure-verdict-post-gap-rate.sh — measure the Phase-4.4 verdict-post-gap rate
# against a PER-REVIEW-RUN denominator (issue #1629 AC5).
#
# The gap comment `<!-- prflow:verdict-post-gap run=<id> -->` (posted by
# scripts/describe-verdict-post-gap.sh) is the numerator. The denominator is the
# number of REVIEW RUNS on pull requests — NOT all devflow.yml runs — established
# from the review engine's own per-run seed comment
# `<!-- prflow:review-progress run=<id>-<attempt> -->` (one per review run, from
# scripts/seed-review-progress.sh). Both markers live in pull-request issue
# comments, so this scans PR comments in a time window and counts distinct run
# keys in each category, bucketed by the day the comment was created.
#
# Both marker families accept the superseded `devflow:` spelling per-record
# (issue #1003), so pre-rename history is not silently dropped.
#
# Run DURATION is used NOWHERE as a signal (issue #1629 AC7): the measurement
# reads only marker presence and comment timestamps. Duration carries no usable
# compliance signal in either direction (a 6m30s run succeeded while a 7m07s run
# failed), so it is deliberately never queried.
#
# Usage:
#   scripts/measure-verdict-post-gap-rate.sh [--days N] [--repo owner/repo]
#     --days N       window size in days ending now (default 14)
#     --repo R       owner/repo (default: resolved by gh from the git remote)
#
# Reads a single environment override:
#   DEVFLOW_GH / DEVFLOW_JQ  gh/jq executables, resolved via lib/resolve-*.sh.
set -uo pipefail

# shellcheck source=../lib/resolve-gh.sh
# Fail closed with a breadcrumb naming resolve-gh.sh: a bare `DEVFLOW_GH:=gh`
# fallback is forbidden repo-wide (the #245 peer-completeness pin), and letting an
# unsourced resolver fall through would misattribute the failure to 'gh pr list'.
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/resolve-gh.sh" \
  || { echo "measure-verdict-post-gap-rate: could not source lib/resolve-gh.sh (broken deployment; set DEVFLOW_GH to override)" >&2; exit 3; }
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"
# shellcheck source=../lib/resolve-jq.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/resolve-jq.sh" \
  || { echo "devflow: resolve-jq.sh could not be sourced — using bare 'jq' (set DEVFLOW_JQ to override)" >&2; : "${DEVFLOW_JQ:=jq}"; }

DAYS=14
REPO=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --days) DAYS="${2:-}"; shift 2 ;;
    --repo) REPO="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "measure-verdict-post-gap-rate: unknown argument '$1'" >&2; exit 2 ;;
  esac
done

case "$DAYS" in
  ''|*[!0-9]*) echo "measure-verdict-post-gap-rate: --days must be a positive integer, got '$DAYS'" >&2; exit 2 ;;
esac

# Window start (UTC), via python3 (a preflight-guaranteed tool) — never `date -d`,
# which is a GNU-only extension this project's portability convention forbids.
SINCE="$(python3 -c 'import sys,datetime; print((datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(days=int(sys.argv[1]))).strftime("%Y-%m-%dT%H:%M:%SZ"))' "$DAYS")" \
  || { echo "measure-verdict-post-gap-rate: could not compute the window start with python3" >&2; exit 3; }
SINCE_DAY="${SINCE%%T*}"

# An explicit --repo sets GH_REPO for BOTH `gh pr list` and the `gh api`
# `{owner}/{repo}` placeholders below; with none, gh fills the repo from the git
# remote (never $GITHUB_REPOSITORY, which is empty off Actions — CLAUDE.md's
# gh-api-repo-path rule).
[ -n "$REPO" ] && export GH_REPO="$REPO"

# PRs touched within the window. A review run posts/updates a PR comment, which
# bumps the PR's updatedAt, so a window-scoped `updated:>=` search reaches every
# PR that saw review activity in the window. --limit is capped high; a scan that
# hits the cap says so on stderr rather than silently truncating.
LIMIT=1000
PR_NUMBERS="$("$DEVFLOW_GH" pr list --state all \
  --search "updated:>=$SINCE_DAY" --limit "$LIMIT" --json number \
  --jq '.[].number')" \
  || { echo "measure-verdict-post-gap-rate: 'gh pr list' failed — cannot establish the PR set" >&2; exit 3; }

# Collect classified marker rows across all scanned PRs into one temp file:
#   <category>\t<yyyy-mm-dd>\t<runkey>
# category is `progress` (denominator) or `gap` (numerator). jq's scan with one
# capture group yields the captured run key per match; comments with neither
# marker emit nothing. Both marker spellings (pr/devflow) are accepted per-record.
ROWS="$(mktemp)"
CMTS="$(mktemp)"
trap 'rm -f "$ROWS" "$CMTS"' EXIT

# A comment fetch can fail (secondary rate limit, transient 5xx, a per-PR
# permission error, a mid-pagination truncation). Blanket-suppressing it would
# make a failed PR contribute zero markers — byte-identical to a PR with no review
# comments — and silently bias the emitted rate, which is exactly the number AC5's
# baseline rests on. So capture the fetch, check its exit status, and count+surface
# every failure rather than folding it into "no markers".
PR_COUNT=0
FETCH_FAIL=0
for PR in $PR_NUMBERS; do
  [ -n "$PR" ] || continue
  PR_COUNT=$((PR_COUNT + 1))
  if "$DEVFLOW_GH" api \
       "repos/{owner}/{repo}/issues/$PR/comments?per_page=100" --paginate \
       --jq '.[] | [.created_at, .body] | @tsv' > "$CMTS" 2>/dev/null; then
    # Progress runs are keyed by run id ALONE (the `-<attempt>` suffix is stripped
    # by capturing only the id group), so a re-attempted Actions run counts once and
    # the denominator's key namespace matches the gap numerator's run-id key.
    "$DEVFLOW_JQ" -Rr --arg since "$SINCE" '
        split("\t") | { ts: .[0], body: .[1] }
        | select(.ts >= $since)
        | (.ts[0:10]) as $d
        | ( [ .body | scan("<!-- (?:pr|dev)flow:review-progress run=([0-9]+)-[0-9]+") ] ) as $rp
        | ( [ .body | scan("<!-- (?:pr|dev)flow:verdict-post-gap run=([0-9]+)") ] ) as $vg
        | ( $rp[] | "progress\t\($d)\t\(.)" ), ( $vg[] | "gap\t\($d)\t\(.)" )
      ' < "$CMTS" >> "$ROWS" || true
  else
    FETCH_FAIL=$((FETCH_FAIL + 1))
    echo "measure-verdict-post-gap-rate: WARNING — comment fetch failed for PR #$PR; it contributes no markers, so the counts below are incomplete." >&2
  fi
done

if [ "$PR_COUNT" -ge "$LIMIT" ]; then
  echo "measure-verdict-post-gap-rate: WARNING — PR listing hit the --limit of $LIMIT; the window may be undercounted (narrow --days or raise the cap)." >&2
fi

# Aggregate distinct run keys per category (overall and per day) in ONE python3
# pass. python3 is the project's preflight-guaranteed tool, so the emitted counts
# never depend on a non-guaranteed PATH tool (awk/sort/grep) that could be absent
# and silently miscount (CLAUDE.md's un-guaranteed-tool guard). A review run may
# update its own progress comment, so dedup on the runkey.
DAYS="$DAYS" SINCE="$SINCE" PR_COUNT="$PR_COUNT" FETCH_FAIL="$FETCH_FAIL" python3 - "$ROWS" <<'__AGG_PY__'
import os, sys
rows_path = sys.argv[1]
progress, gap = set(), set()
per_day = {}
try:
    with open(rows_path, encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 3:
                continue
            cat, day, key = parts
            if cat == "progress":
                progress.add(key)
                per_day.setdefault(day, [set(), set()])[0].add(key)
            elif cat == "gap":
                gap.add(key)
                per_day.setdefault(day, [set(), set()])[1].add(key)
except OSError as exc:
    print(f"measure-verdict-post-gap-rate: could not read the scan rows: {exc}", file=sys.stderr)
    sys.exit(3)

denom, numer = len(progress), len(gap)
fetch_fail = int(os.environ.get("FETCH_FAIL", "0") or "0")
print(f"verdict-post-gap rate — window: last {os.environ['DAYS']} days (since {os.environ['SINCE']})")
scanned = os.environ['PR_COUNT']
print(f"PRs scanned: {scanned}" + (f" ({fetch_fail} with comment-fetch failures — counts below are incomplete)" if fetch_fail else ""))
print(f"denominator (distinct review runs on PRs): {denom}")
print(f"numerator   (distinct verdict-post-gap runs): {numer}")
print(f"rate (numerator / denominator): {100.0*numer/denom:.1f}%" if denom else
      "rate (numerator / denominator): n/a (no review runs found in window)")
# A numerator above the denominator is a data-integrity signal (a gap run whose
# review-progress seed was not counted — e.g. its PR's fetch failed, or an
# older-spelling seed), never a real >100% rate. Surface it rather than print it silently.
if numer > denom:
    print(f"WARNING: numerator ({numer}) exceeds denominator ({denom}) — some gap runs have no counted review-progress seed; the rate is not meaningful.", file=sys.stderr)
print("note: run duration is used nowhere as a signal (AC7); only marker presence and comment timestamps are read.")
print()
print("per-day (day  review_runs  gap_runs):")
for day in sorted(per_day):
    p, g = per_day[day]
    print(f"  {day}  {len(p)}  {len(g)}")
__AGG_PY__
