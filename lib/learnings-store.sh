#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# learnings-store.sh — the weekly retrospective's learnings store on the telemetry
# branch. The store is `.prflow/logs/learnings/` on the branch
# devflow_telemetry_branch names; a run works on a copy under `.prflow/learnings/`,
# which the default branch does not track. Sourced by scripts/retro-helper.sh:
#
#   devflow_learnings_hydrate <root>            fetch the store into the working copy
#   devflow_learnings_persist <root> [--report] save the working copy (and the report)
#   devflow_learnings_dismiss <root> <key>      add a key to the store's dismissed map
#   devflow_learnings_migrate <root>            one-time copy of tracked learnings files
#
# A save refuses, pushing nothing, when the remote store's files differ from the base
# this run recorded — before its fetch or between that fetch and the push — except where
# the changed file holds a blob one of this run's saves staged (its own push that landed
# unconfirmed). A save does not read `telemetry.enabled`: the store is the retrospective's
# own state.
# hydrate/persist/dismiss print one diagnostic line on stdout and exit 0 on success,
# 1 on a failure, 3 on a base-check refusal (dismiss: 2 on a missing key).

_DLS_LIB_DIR="$(cd "${BASH_SOURCE[0]%/*}" && pwd)"
# shellcheck source=lib/telemetry-branch.sh
. "$_DLS_LIB_DIR/telemetry-branch.sh"
# shellcheck source=lib/resolve-gh.sh
. "$_DLS_LIB_DIR/resolve-gh.sh"
: "${DEVFLOW_GH:=$(devflow_resolve_gh)}"

_DLS_PREFIX=".prflow/logs/learnings"
_DLS_FILES="retrospectives.jsonl experiment-records.jsonl overrides.json"
_DLS_WORK=".prflow/learnings"
_DLS_STATE=".prflow/tmp/retro-learnings"
_DLS_TAB="$(printf '\t')"

_dls_err() { echo "::error::learnings-store: $1" >&2; }

# Fetch the remote telemetry branch into refs/remotes/origin/<branch>. Sets _DLS_TIP to
# its commit ID, or empty when the remote has no such branch. rc 1 (breadcrumb naming the
# branch) when the branch cannot be queried, fetched or resolved.
_dls_fetch() {  # $1 root, $2 branch
  local rc=0
  _DLS_TIP=""
  GIT_TERMINAL_PROMPT=0 git -C "$1" ls-remote --exit-code origin "refs/heads/$2" >/dev/null || rc=$?
  case "$rc" in
    0) ;;
    2) return 0 ;;
    *) _dls_err "could not query origin for the telemetry branch '$2' (git ls-remote rc=$rc — no origin remote, offline, or auth)"; return 1 ;;
  esac
  if ! GIT_TERMINAL_PROMPT=0 git -C "$1" fetch -q --no-tags origin "+refs/heads/$2:refs/remotes/origin/$2"; then
    _dls_err "could not fetch the telemetry branch '$2' from origin"
    return 1
  fi
  _DLS_TIP="$(devflow_telemetry_commit_id "$1" "refs/remotes/origin/$2")"
  [ -n "$_DLS_TIP" ] || { _dls_err "could not resolve the fetched telemetry branch '$2' to a commit"; return 1; }
}

# Print `<blob><TAB><path>` for every store file on commit $2 (nothing for an empty $2).
_dls_listing() {  # $1 root, $2 commit
  local out meta path
  [ -n "$2" ] || return 0
  out="$(git -c core.quotePath=false -C "$1" ls-tree -r "$2" -- "$_DLS_PREFIX/")" || return 1
  while IFS="$_DLS_TAB" read -r meta path; do
    [ -n "$path" ] && printf '%s\t%s\n' "${meta##* }" "$path"
  done <<EOF
$out
EOF
  return 0
}

# rc 0 when listing $1 holds any of the store files $2 (default: all). A store may hold
# any subset of them, so "a store exists" means any one.
_dls_holds() {  # $1 listing text, [$2 space-separated file names]
  local f
  for f in ${2:-$_DLS_FILES}; do
    case "$1"$'\n' in *"$_DLS_TAB$_DLS_PREFIX/$f"$'\n'*) return 0 ;; esac
  done
  return 1
}

# Print each path whose blob differs between two listings, or that only one holds.
_dls_changed() {  # $1 base listing text, $2 current listing text
  local line p b other found
  [ "$1" = "$2" ] && return 0
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    p="${line#*"$_DLS_TAB"}"; b="${line%%"$_DLS_TAB"*}"; found=""
    while IFS= read -r other; do
      [ "${other#*"$_DLS_TAB"}" = "$p" ] && { found="${other%%"$_DLS_TAB"*}"; break; }
    done <<EOF
$2
EOF
    [ "$found" = "$b" ] || printf '%s\n' "$p"
  done <<EOF
$1
EOF
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    p="${line#*"$_DLS_TAB"}"; found=no
    while IFS= read -r other; do
      [ "${other#*"$_DLS_TAB"}" = "$p" ] && { found=yes; break; }
    done <<EOF
$1
EOF
    [ "$found" = yes ] || printf '%s\n' "$p"
  done <<EOF
$2
EOF
}

# The base check, run by _dls_save before its push and by persist_tree on a tip fetched
# after a rejected push. rc 0 when every store file on tip $2 holds its $_DLS_BASE_FILE
# blob or a blob listed in $_DLS_ATTEMPTS_FILE (this run's own push that landed
# unconfirmed); else rc 1, writing the other changed paths, `(unreadable base)` or
# `(unreadable store)` to $_DLS_REFUSED_FILE.
_dls_guard() {  # $1 root, $2 tip
  local base cur changed attempts foreign="" f line l
  if ! base="$(cat "$_DLS_BASE_FILE")"; then
    printf '%s\n' "(unreadable base)" > "$_DLS_REFUSED_FILE"
    return 1
  fi
  if ! cur="$(_dls_listing "$1" "$2")"; then
    printf '%s\n' "(unreadable store)" > "$_DLS_REFUSED_FILE"
    return 1
  fi
  changed="$(_dls_changed "$base" "$cur")"
  [ -z "$changed" ] && return 0
  attempts="$(cat "$_DLS_ATTEMPTS_FILE" 2>/dev/null)" || attempts=""
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    line=""
    while IFS= read -r l; do [ "${l#*"$_DLS_TAB"}" = "$f" ] && { line="$l"; break; }; done <<EOF
$cur
EOF
    if [ -n "$line" ]; then
      case $'\n'"$attempts"$'\n' in *$'\n'"$line"$'\n'*) continue ;; esac
    fi
    foreign="$foreign$f"$'\n'
  done <<EOF
$changed
EOF
  [ -z "$foreign" ] && return 0
  printf '%s' "$foreign" > "$_DLS_REFUSED_FILE"
  return 1
}

_dls_join() { local out="" l; while IFS= read -r l; do [ -n "$l" ] && out="${out:+$out, }$l"; done; printf '%s' "$out"; }

# Report a _dls_guard refusal: rc 3 `refused:` naming the changed paths; rc 1 `failure:`
# for an unreadable base or store, or a missing or empty refusal record (a local fault).
_dls_refusal() {  # $1 branch, $2 when the store changed
  local changed=""
  [ -s "$_DLS_REFUSED_FILE" ] && changed="$(_dls_join 2>/dev/null < "$_DLS_REFUSED_FILE")"
  case "$changed" in
    "")
      _dls_err "the base check refused the save on '$1' but recorded no changed path — nothing pushed"
      printf 'failure: the base check on %s refused without recording a changed path; nothing pushed\n' "$1"
      return 1 ;;
    "(unreadable base)")
      _dls_err "could not read this run's recorded base $_DLS_BASE_FILE — refusing the save to '$1'; nothing pushed"
      printf 'failure: could not read the recorded base for %s; nothing pushed\n' "$1"
      return 1 ;;
    "(unreadable store)")
      _dls_err "could not read the store on '$1' — refusing the save; nothing pushed"
      printf 'failure: could not read the store on %s; nothing pushed\n' "$1"
      return 1 ;;
  esac
  _dls_err "the store on '$1' changed $2 (${changed}) — refusing to overwrite; nothing pushed"
  printf 'refused: base check — the store on %s changed %s: %s\n' "$1" "$2" "$changed"
  return 3
}

# Save staging root $3 under the base file $4: base check, writer, remote confirmation.
# Prints the diagnostic; rc 0 saved, 1 failure, 3 refused. On success rewrites $4.
_dls_save() {  # $1 root, $2 branch, $3 staging root, $4 base file
  local root="$1" branch="$2" stage="$3" base="$4" local_tip rc rel
  # An empty stage would pass the confirmation below with nothing saved.
  if [ -z "$(_dls_staged_files "$stage")" ]; then
    _dls_err "nothing is staged to save to '$branch' — nothing pushed"
    printf 'failure: nothing staged to save to %s\n' "$branch"
    return 1
  fi
  _dls_fetch "$root" "$branch" || { printf 'failure: could not fetch the telemetry branch %s\n' "$branch"; return 1; }
  _DLS_BASE_FILE="$base"
  _DLS_ATTEMPTS_FILE="$base.attempts"
  _DLS_REFUSED_FILE="$root/$_DLS_STATE/refused.txt"
  rm -f "$_DLS_REFUSED_FILE"
  _dls_guard "$root" "$_DLS_TIP" || { _dls_refusal "$branch" "since this run read it"; return; }
  # Kept for the run, so a later save does not refuse this push if it lands unconfirmed.
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    printf '%s\t%s\n' "$(git -C "$root" hash-object -- "$rel")" "${rel#"$stage"/}"
  done >> "$_DLS_ATTEMPTS_FILE" <<EOF || { _dls_err "could not record this save's blobs in $_DLS_ATTEMPTS_FILE — nothing pushed"; printf 'failure: could not record the save attempt for %s; nothing pushed\n' "$branch"; return 1; }
$(_dls_staged_files "$stage")
EOF
  # Start from the fetched tip when the local ref is absent or behind it; a local ref
  # holding unpushed records is left alone.
  local_tip="$(devflow_telemetry_commit_id "$root" "refs/heads/$branch")"
  if [ -n "$_DLS_TIP" ] && [ "$local_tip" != "$_DLS_TIP" ]; then
    if [ -z "$local_tip" ] || git -C "$root" merge-base --is-ancestor "$local_tip" "$_DLS_TIP"; then
      git -C "$root" update-ref "refs/heads/$branch" "$_DLS_TIP" "$local_tip" \
        || _dls_err "could not fast-forward the local '$branch' ref to the fetched tip; the writer re-parents on push"
    fi
  fi
  rc=0
  devflow_telemetry_persist_tree "$root" "$stage" _dls_guard || rc=$?
  [ "$rc" -eq 6 ] && { _dls_refusal "$branch" "during the save"; return; }
  if [ "$rc" -ne 0 ]; then
    printf 'failure: the telemetry writer returned %s for %s (its warning above names the cause)\n' "$rc" "$branch"
    return 1
  fi
  # rc 0 also covers no origin remote and an idempotent no-op, so it is not evidence of a
  # landed push: confirm every staged blob on a freshly fetched tip.
  _dls_fetch "$root" "$branch" || { printf 'failure: the writer returned 0 but %s could not be re-fetched to confirm the push\n' "$branch"; return 1; }
  if [ -z "$_DLS_TIP" ]; then
    printf 'failure: the writer returned 0 but origin holds no %s branch — the push did not land\n' "$branch"
    return 1
  fi
  if ! rel="$(_dls_tip_lacks "$root" "$stage" "$_DLS_TIP")"; then
    printf 'failure: the writer returned 0 but the %s tip does not hold the staged %s\n' "$branch" "$rel"
    return 1
  fi
  _dls_listing "$root" "$_DLS_TIP" > "$base" \
    || { printf 'failure: saved %s at %s but could not record the new base\n' "$branch" "$_DLS_TIP"; return 1; }
  printf 'saved: %s at %s\n' "$branch" "$_DLS_TIP"
}

# rc 0 when commit $3 holds every staged blob; else rc 1, printing the first staged path it lacks.
_dls_tip_lacks() {  # $1 root, $2 staging root, $3 commit
  local f rel want
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    rel="${f#"$2"/}"
    want="$(git -C "$1" hash-object -- "$f")"
    if [ -z "$want" ] || [ "$want" != "$(git -C "$1" rev-parse --verify --quiet "$3:$rel")" ]; then
      printf '%s\n' "$rel"; return 1
    fi
  done <<EOF
$(_dls_staged_files "$2")
EOF
  return 0
}

_dls_staged_files() {  # $1 dir — every regular file beneath it, one per line
  local e
  for e in "$1"/* "$1"/.[!.]*; do
    [ -e "$e" ] || continue
    if [ -d "$e" ]; then _dls_staged_files "$e"; elif [ -f "$e" ]; then printf '%s\n' "$e"; fi
  done
}

# First open pull request whose head branch is a retired state branch, as `<n> <branch>`;
# rc 1 when the query fails. Both prefixes: lib/rename-map.json `retrospective-state-branch`.
_dls_open_state_pr() {  # $1 root
  local out _l
  out="$(cd "$1" && "$DEVFLOW_GH" api --paginate "repos/{owner}/{repo}/pulls?state=open&per_page=100" \
    --jq '.[] | select((.head.ref | startswith("prflow/learnings-")) or (.head.ref | startswith("devflow/learnings-"))) | "\(.number) \(.head.ref)"')" || return 1
  while IFS= read -r _l; do
    case "${_l%% *}" in ''|*[!0-9]*) continue ;; esac
    printf '%s\n' "$_l"; return 0
  done <<EOF
$out
EOF
}

_dls_now_stamp() {  # $1 = strftime format (UTC)
  python3 -c 'import sys, time; sys.stdout.reconfigure(newline="\n"); print(time.strftime(sys.argv[1], time.gmtime()))' "$1"
}

# Copy the store's files from commit $2 into the working copy; a file the commit lacks
# is removed from the working copy. $3 is the path prefix inside the commit.
_dls_copy_out() {  # $1 root, $2 commit, $3 prefix
  local f
  mkdir -p "$1/$_DLS_WORK" || return 1
  for f in $_DLS_FILES; do
    if git -C "$1" cat-file -e "$2:$3/$f" 2>/dev/null; then
      git -C "$1" cat-file blob "$2:$3/$f" > "$1/$_DLS_WORK/$f.tmp" \
        && mv "$1/$_DLS_WORK/$f.tmp" "$1/$_DLS_WORK/$f" || { rm -f "$1/$_DLS_WORK/$f.tmp"; return 1; }
    else
      rm -f "$1/$_DLS_WORK/$f" || return 1
    fi
  done
}

_dls_stage_working() {  # $1 root, $2 staging root — stage the working copy's store files
  local f
  rm -rf "$2" && mkdir -p "$2/$_DLS_PREFIX" || return 1
  for f in $_DLS_FILES; do
    [ -f "$1/$_DLS_WORK/$f" ] || continue
    cp "$1/$_DLS_WORK/$f" "$2/$_DLS_PREFIX/$f" || return 1
  done
}

# Validate the retrospectives.jsonl at git object $2, named $3 in its diagnostics: rc 1 with a
# stop line when it cannot be read, holds no pr record (the scan reads that as corruption) or
# holds a line that is not a JSON object (blank lines are skipped, as the scan does).
_dls_check_records() {  # $1 root, $2 <commit>:<path>, $3 label
  local bad
  if ! bad="$(git -C "$1" cat-file blob "$2" \
    | "${DEVFLOW_JQ:-jq}" -n -R -r '[inputs] | to_entries | map(select(.value | explode | all(. == 32 or . == 9 or . == 13) | not))
        | (map(select((.value | try fromjson catch null | type) != "object") | .key + 1)) as $bad
        | if ($bad | length) > 0 then $bad[] elif (map(.value | fromjson | select(.pr != null)) | length) == 0 then "empty" else empty end')"; then
    _dls_err "could not read or validate $3 (git cat-file or jq failed) — stopping before the scan"
    echo "stop: $3 could not be read"
    return 1
  fi
  case "$bad" in
    "") return 0 ;;
    empty)
      _dls_err "$3 holds no pr record — stopping before the scan"
      echo "stop: $3 holds no pr record"
      return 1 ;;
  esac
  _dls_err "$3 line ${bad%%$'\n'*} is not a JSON object — stopping before the scan"
  echo "stop: $3 line ${bad%%$'\n'*} is not a JSON object"
  return 1
}

devflow_learnings_hydrate() {  # $1 root
  local root="$1" branch state start commit src default line rc f listing hist=()
  branch="$(devflow_telemetry_branch)"
  state="$root/$_DLS_STATE"
  mkdir -p "$state" "$root/$_DLS_WORK" || { _dls_err "could not create $_DLS_STATE and $_DLS_WORK"; echo "stop: could not create $_DLS_STATE and $_DLS_WORK"; return 1; }
  start="$(_dls_now_stamp '%Y-%m-%dT%H%M%SZ')"
  [ -n "$start" ] || { _dls_err "could not compute the run-start timestamp (python3)"; echo "stop: no run-start timestamp"; return 1; }
  printf '%s\n' "$start" > "$state/run-start.txt" || { _dls_err "could not write $_DLS_STATE/run-start.txt"; echo "stop: could not record the run start"; return 1; }
  if ! _dls_fetch "$root" "$branch"; then
    echo "stop: the telemetry branch $branch cannot be fetched or read"
    return 1
  fi
  { _dls_listing "$root" "$_DLS_TIP" > "$state/base.txt" && listing="$(cat "$state/base.txt")" && rm -f "$state/base.txt.attempts"; } \
    || { _dls_err "could not record the store's base"; echo "stop: could not record the store's base"; return 1; }
  if _dls_holds "$listing"; then
    if _dls_holds "$listing" retrospectives.jsonl; then
      _dls_check_records "$root" "$_DLS_TIP:$_DLS_PREFIX/retrospectives.jsonl" "$_DLS_PREFIX/retrospectives.jsonl on '$branch'" || return 1
    fi
    _dls_copy_out "$root" "$_DLS_TIP" "$_DLS_PREFIX" || { _dls_err "could not copy the store into $_DLS_WORK"; echo "stop: could not copy the store into $_DLS_WORK"; return 1; }
    echo "hydrated: $branch at $_DLS_TIP"
    return 0
  fi
  # A still-open state PR carries a week the default branch never received.
  if ! line="$(_dls_open_state_pr "$root")"; then
    _dls_err "the store is absent and the open pull-request query failed — stopping rather than recovering past an unmerged state PR"
    echo "stop: the open pull-request query failed"
    return 1
  fi
  if [ -n "$line" ]; then
    _dls_err "the store is absent and state pull request #${line%% *} (${line#* }) is still open — merge or close it, then re-run"
    echo "stop: state pull request #${line%% *} (${line#* }) is open"
    return 1
  fi
  rc=0
  line="$(GIT_TERMINAL_PROMPT=0 git -C "$root" ls-remote --symref origin HEAD)" || rc=$?
  line="${line%%"$_DLS_TAB"*}"
  case "$line" in
    "ref: refs/heads/"?*) default="${line#ref: refs/heads/}" ;;
    *) _dls_err "the store is absent and origin's default branch could not be resolved (git ls-remote --symref rc=$rc)"; echo "stop: the default branch could not be resolved"; return 1 ;;
  esac
  if ! GIT_TERMINAL_PROMPT=0 git -C "$root" fetch -q --no-tags origin "+refs/heads/$default:refs/remotes/origin/$default"; then
    _dls_err "the store is absent and the default branch '$default' could not be fetched"
    echo "stop: the default branch $default could not be fetched"
    return 1
  fi
  for f in $_DLS_FILES; do hist+=("$_DLS_WORK/$f"); done
  if ! commit="$(git -C "$root" log -1 --format=%H "refs/remotes/origin/$default" -- "${hist[@]}")"; then
    _dls_err "the store is absent and the history of '$default' could not be read (git log failed)"
    echo "stop: the history of $default could not be read"
    return 1
  fi
  if [ -z "$commit" ]; then
    case "$(git -C "$root" rev-parse --is-shallow-repository)" in
      false) ;;
      true)
        _dls_err "the store is absent and this clone is shallow, so the last commit that tracked a $_DLS_WORK/ store file may be missing — fetch full history (fetch-depth: 0), then re-run"
        echo "stop: shallow clone"
        return 1 ;;
      *)
        _dls_err "the store is absent and git could not tell whether this clone is shallow (rev-parse --is-shallow-repository failed)"
        echo "stop: could not tell whether the clone is shallow"
        return 1 ;;
    esac
    for f in $_DLS_FILES; do
      rm -f "$root/$_DLS_WORK/$f" || { _dls_err "could not clear the stale $_DLS_WORK/$f"; echo "stop: could not clear $_DLS_WORK/$f"; return 1; }
    done
    echo "first-run: no store on $branch and the default branch $default never tracked a $_DLS_WORK/ store file"
    return 0
  fi
  # When the last commit touching the files holds none of them (it deleted them), recover
  # from its first parent.
  src="$commit^"
  for f in $_DLS_FILES; do
    git -C "$root" cat-file -e "$commit:$_DLS_WORK/$f" 2>/dev/null && { src="$commit"; break; }
  done
  _dls_copy_out "$root" "$src" "$_DLS_WORK" || { _dls_err "could not copy the recovered files into $_DLS_WORK"; echo "stop: could not copy the recovered files"; return 1; }
  if [ -f "$root/$_DLS_WORK/retrospectives.jsonl" ]; then
    _dls_check_records "$root" "$src:$_DLS_WORK/retrospectives.jsonl" "$_DLS_WORK/retrospectives.jsonl in $default commit $src" || return 1
  fi
  _dls_stage_working "$root" "$state/stage" || { _dls_err "could not stage the recovered files"; echo "stop: could not stage the recovered files"; return 1; }
  if [ -z "$(_dls_staged_files "$state/stage")" ]; then
    _dls_err "the store is absent and $default commit $src holds no $_DLS_WORK/ store file to recover — stopping before the scan"
    echo "stop: $default commit $src holds no $_DLS_WORK/ store file to recover"
    return 1
  fi
  rc=0
  line="$(_dls_save "$root" "$branch" "$state/stage" "$state/base.txt")" || rc=$?
  if [ "$rc" -ne 0 ]; then
    _dls_err "recovered the store from $default commit $src but could not save it (${line}) — stopping before the scan"
    echo "stop: recovered from $default commit $src but the save did not land (${line})"
    return "$rc"
  fi
  echo "hydrated: recovered from $default commit $src (${line})"
}

devflow_learnings_persist() {  # $1 root, [$2 --report]
  local root="$1" branch state start report base_text
  branch="$(devflow_telemetry_branch)"
  state="$root/$_DLS_STATE"
  [ -s "$state/run-start.txt" ] && [ -f "$state/base.txt" ] || {
    _dls_err "no recorded base in $_DLS_STATE — run retro-helper.sh learnings-hydrate first"
    echo "failure: no recorded base (learnings-hydrate did not run)"
    return 1
  }
  _dls_stage_working "$root" "$state/stage" || { _dls_err "could not stage the working copy"; echo "failure: could not stage the working copy"; return 1; }
  if [ "${2:-}" = --report ]; then
    start="$(cat "$state/run-start.txt")"
    report="$_DLS_PREFIX/reports/$start.md"
    if [ ! -s "$root/.prflow/tmp/report.md" ]; then
      _dls_err "--report given but .prflow/tmp/report.md is missing or empty"
      echo "failure: .prflow/tmp/report.md is missing or empty"
      return 1
    fi
    base_text="$(cat "$state/base.txt")" || { _dls_err "could not read the recorded base in $_DLS_STATE"; echo "failure: could not read the recorded base"; return 1; }
    case "$base_text" in
      *"$_DLS_TAB$report"*) _dls_err "$report already exists on '$branch' — refusing to overwrite another run's report"; echo "failure: $report already exists"; return 1 ;;
    esac
    mkdir -p "$state/stage/$_DLS_PREFIX/reports" && cp "$root/.prflow/tmp/report.md" "$state/stage/$report" \
      || { echo "failure: could not stage the report"; return 1; }
  fi
  _dls_save "$root" "$branch" "$state/stage" "$state/base.txt"
}

devflow_learnings_dismiss() {  # $1 root, $2 pattern key
  local root="$1" key="${2:-}" branch state ov now listing
  if [ -z "$key" ]; then
    _dls_err "dismiss needs a pattern key (retro-helper.sh dismiss <pattern-key>)"
    echo "failure: missing pattern key"
    return 2
  fi
  branch="$(devflow_telemetry_branch)"
  state="$root/$_DLS_STATE/dismiss"
  rm -rf "$state" && mkdir -p "$state/stage/$_DLS_PREFIX" || { echo "failure: could not create $_DLS_STATE/dismiss"; return 1; }
  _dls_fetch "$root" "$branch" || { echo "failure: the telemetry branch $branch cannot be fetched"; return 1; }
  { _dls_listing "$root" "$_DLS_TIP" > "$state/base.txt" && listing="$(cat "$state/base.txt")"; } \
    || { echo "failure: could not read the store on $branch"; return 1; }
  # Writing into an empty store would create one that stops the next hydrate's history recovery.
  if ! _dls_holds "$listing"; then
    _dls_err "'$branch' holds no learnings store under $_DLS_PREFIX/ — nothing to dismiss against; nothing pushed"
    echo "failure: no learnings store on $branch"
    return 1
  fi
  if _dls_holds "$listing" overrides.json; then
    ov="$(git -C "$root" cat-file blob "$_DLS_TIP:$_DLS_PREFIX/overrides.json")" || { echo "failure: could not read $_DLS_PREFIX/overrides.json"; return 1; }
  else
    ov='{}'
  fi
  if ! printf '%s' "$ov" | "${DEVFLOW_JQ:-jq}" -e 'type == "object" and ((has("dismissed") | not) or (.dismissed | type) == "object")' >/dev/null; then
    _dls_err "$_DLS_PREFIX/overrides.json on '$branch' is not a JSON object with an object-typed dismissed map — nothing pushed"
    echo "failure: $_DLS_PREFIX/overrides.json is not a JSON object with an object dismissed map"
    return 1
  fi
  if printf '%s' "$ov" | "${DEVFLOW_JQ:-jq}" -e --arg k "$key" '(.dismissed // {}) | has($k)' >/dev/null; then
    echo "unchanged: $key is already dismissed on $branch"
    return 0
  fi
  now="$(_dls_now_stamp '%Y-%m-%dT%H:%M:%SZ')"
  [ -n "$now" ] || { _dls_err "could not compute the dismissal timestamp (python3)"; echo "failure: no dismissal timestamp"; return 1; }
  printf '%s' "$ov" | "${DEVFLOW_JQ:-jq}" --arg k "$key" --arg at "$now" \
    '.dismissed = ((.dismissed // {}) + {($k): {dismissed_by: "retro-helper dismiss", dismissed_at: $at}})' \
    > "$state/stage/$_DLS_PREFIX/overrides.json" || { echo "failure: could not compose overrides.json"; return 1; }
  _dls_save "$root" "$branch" "$state/stage" "$state/base.txt"
}

# Ensure `.prflow/.gitignore` carries a `/learnings/` line. Prints `added` when it wrote one.
_dls_ensure_ignore() {  # $1 root
  local gi="$1/.prflow/.gitignore" l unterminated=no
  if [ -f "$gi" ]; then
    while IFS= read -r l || { [ -n "$l" ] && unterminated=yes; }; do
      [ "${l%$'\r'}" = "/learnings/" ] && return 0
    done < "$gi"
    [ "$unterminated" = no ] || printf '\n' >> "$gi" || return 1
  else
    mkdir -p "$1/.prflow" || return 1
  fi
  printf '/learnings/\n' >> "$gi" || return 1
  echo added
}

devflow_learnings_migrate() {  # $1 any directory inside the work tree
  local root branch state tracked=() p line f added listing qrc=0
  # install.sh and /prflow:init may run below the root; every path here is root-relative.
  if ! root="$(git -C "$1" rev-parse --show-toplevel)" || [ -z "$root" ]; then
    echo "learnings-migrate: '$1' is not inside a git work tree — nothing copied or staged" >&2
    return 1
  fi
  if ! line="$(git -c core.quotePath=false -C "$root" ls-files -- "$_DLS_WORK/")"; then
    echo "learnings-migrate: could not read the git index (git ls-files failed) — nothing copied or staged" >&2
    return 1
  fi
  while IFS= read -r p; do [ -n "$p" ] && tracked+=("$p"); done <<EOF
$line
EOF
  line="$(_dls_open_state_pr "$root")" || qrc=$?
  if [ -n "$line" ]; then
    echo "learnings-migrate: state pull request #${line%% *} (${line#* }) is still open — merge or close it, then re-run; nothing copied or staged" >&2
    return 1
  fi
  if [ "${#tracked[@]}" -gt 0 ]; then
    # The copy reads the index, and the next hydrate overwrites the untracked working copy.
    if ! line="$(git -c core.quotePath=false -C "$root" diff --name-only -- "${tracked[@]}")"; then
      echo "learnings-migrate: could not compare the tracked learnings files with the index (git diff failed) — nothing copied or staged" >&2
      return 1
    fi
    if [ -n "$line" ]; then
      echo "learnings-migrate: uncommitted changes to $(printf '%s\n' "$line" | _dls_join) — commit or discard them, then re-run; nothing copied or staged" >&2
      return 1
    fi
    branch="$(devflow_telemetry_branch)"
    state="$root/$_DLS_STATE/migrate"
    # With no tracked files a failed query leaves nothing to protect, so only this arm stops on it.
    if [ "$qrc" -ne 0 ]; then
      echo "learnings-migrate: could not query open pull requests — nothing copied or staged; re-run once gh can reach GitHub" >&2
      return 1
    fi
    _dls_fetch "$root" "$branch" || { echo "learnings-migrate: the telemetry branch '$branch' could not be fetched — nothing copied or staged" >&2; return 1; }
    rm -rf "$state" && mkdir -p "$state/stage" \
      || { echo "learnings-migrate: could not create $_DLS_STATE/migrate — nothing copied or staged" >&2; return 1; }
    { _dls_listing "$root" "$_DLS_TIP" > "$state/base.txt" && listing="$(cat "$state/base.txt")"; } \
      || { echo "learnings-migrate: could not read the telemetry branch '$branch' — nothing copied or staged" >&2; return 1; }
    if _dls_holds "$listing"; then
      line=""
      for p in "${tracked[@]}"; do
        f="$(git -C "$root" rev-parse --verify --quiet ":$p")"
        [ -n "$f" ] && [ "$f" = "$(git -C "$root" rev-parse --verify --quiet "$_DLS_TIP:$_DLS_PREFIX/${p#"$_DLS_WORK"/}")" ] \
          || line="${line:+$line, }'$p'"
      done
      # Untracking a differing file would let the next hydrate overwrite its only copy.
      if [ -n "$line" ]; then
        echo "learnings-migrate: '$branch' already holds a learnings store and the tracked $line differ from its copy — reconcile them, then re-run; nothing staged" >&2
        return 1
      fi
      echo "learnings-migrate: '$branch' already holds a learnings store; left unchanged"
    else
      for p in "${tracked[@]}"; do
        f="$state/stage/$_DLS_PREFIX/${p#"$_DLS_WORK"/}"
        mkdir -p "${f%/*}" && git -C "$root" cat-file blob ":$p" > "$f" \
          || { echo "learnings-migrate: could not read the tracked '$p' — nothing copied or staged" >&2; return 1; }
      done
      # rc 0 means a fresh fetch showed every copied blob on the tip.
      if ! line="$(_dls_save "$root" "$branch" "$state/stage" "$state/base.txt")"; then
        echo "learnings-migrate: the copy to the telemetry branch '$branch' was not confirmed on the remote (${line}) — nothing staged" >&2
        return 1
      fi
      echo "learnings-migrate: copied ${#tracked[@]} learnings file(s) to '$branch'"
    fi
    git -C "$root" rm -q --cached -- "${tracked[@]}" || { echo "learnings-migrate: could not stage the removal of the tracked learnings files" >&2; return 1; }
    echo "learnings-migrate: staged the removal of ${#tracked[@]} tracked file(s) under $_DLS_WORK/ from the index — review and commit"
  fi
  added="$(_dls_ensure_ignore "$root")" || { echo "learnings-migrate: could not write .prflow/.gitignore" >&2; return 1; }
  if [ -n "$added" ]; then
    echo "learnings-migrate: added /learnings/ to .prflow/.gitignore"
  fi
  if [ "${#tracked[@]}" -gt 0 ] && ! git -C "$root" check-ignore -q .prflow/.gitignore 2>/dev/null; then
    git -C "$root" add -- .prflow/.gitignore || { echo "learnings-migrate: could not stage .prflow/.gitignore" >&2; return 1; }
  fi
  return 0
}
