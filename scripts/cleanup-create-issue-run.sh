#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
#
# Single owner of a create-issue run's identity registry and its per-run scratch.
# The run's identity is its run directory, not a session id (issue #198, supersedes
# the session-keyed pointer of issue #153). Modes:
#   --register-slug <slug> --topic <one line> --root <path>  write run-meta.json
#   --resolve-slug --root <path>                              read back the run's slug
#   --adopt-slug <slug> --root <path>                         touch a resolved run
#   --slug <slug> --root <path> ...                           remove the run dir + legacy pointers
# The registry file lives inside the run directory —
# `<root>/.prflow/tmp/create-issue/<slug>/run-meta.json` — so a continued session
# resolves its own run on any harness with only bash, python3 and the filesystem,
# and no mode reads an environment variable. Best-effort: cleanup runs after issue
# creation and never blocks it.
set -u

prog=cleanup-create-issue-run.sh
safe_slug='^[A-Za-z0-9][A-Za-z0-9._-]*$'
# A topic is safe when it is non-empty, at most 120 chars, and uses only letters,
# digits, space and the punctuation `. , : - _ /`. Anything else (a quote, `$`, a
# backtick, `|`, `;`, a newline) is refused so it can never reach a shell or split
# a candidate field.
safe_topic='^[A-Za-z0-9 ._,:/-]+$'

is_safe_topic() {
  local _t="$1"
  # safe_topic's `+` already rejects the empty string — no separate non-empty guard needed.
  [ "${#_t}" -le 120 ] || return 1
  [[ "$_t" =~ $safe_topic ]] || return 1
  return 0
}

mode=cleanup
slug=""
register_slug=""
adopt_slug=""
topic=""
roots=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    # `shift; [ … ] && shift` consumes the value only when one is present. A bare
    # `shift 2` on a trailing valueless flag exceeds $# and fails without moving it,
    # spinning this loop forever — breaking the best-effort/never-blocks contract.
    --slug) slug="${2:-}"; shift; [ "$#" -gt 0 ] && shift ;;
    --register-slug) mode=register; register_slug="${2:-}"; shift; [ "$#" -gt 0 ] && shift ;;
    --adopt-slug) mode=adopt; adopt_slug="${2:-}"; shift; [ "$#" -gt 0 ] && shift ;;
    --topic) topic="${2:-}"; shift; [ "$#" -gt 0 ] && shift ;;
    --resolve-slug) mode=resolve; shift ;;
    --root) roots+=("${2:-}"); shift; [ "$#" -gt 0 ] && shift ;;
    *) printf '%s: warning: ignoring unexpected argument %s\n' "$prog" "$1" >&2; shift ;;
  esac
done

# register/resolve/adopt act on the FIRST --root only; a further --root is ignored
# with one stderr warning naming it, so the single stdout line count stays one.
warn_extra_roots() {
  local _i
  for ((_i = 1; _i < ${#roots[@]}; _i++)); do
    printf '%s: warning: ignoring extra --root %s\n' "$prog" "${roots[_i]}" >&2
  done
}

if [ "$mode" != cleanup ]; then
  root="${roots[0]:-}"
  warn_extra_roots
fi

if [ "$mode" = register ]; then
  if [ -z "$root" ]; then printf 'registered=no reason=no-root\n'; exit 0; fi
  if [ -z "$register_slug" ] || ! [[ "$register_slug" =~ $safe_slug ]]; then
    printf 'registered=no reason=unsafe-slug\n'; exit 0
  fi
  if ! is_safe_topic "$topic"; then printf 'registered=no reason=unsafe-topic\n'; exit 0; fi
  # python3 (preflight-guaranteed) writes the JSON registry and the ISO-8601 UTC
  # times. The run directory is created under the literal --root operand; the
  # `root` field records its symlink-resolved absolute path.
  if python3 - "$register_slug" "$topic" "$root" <<'PY'
import datetime, json, os, sys
slug, topic, root_op = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    d = os.path.join(root_op, ".prflow", "tmp", "create-issue", slug)
    os.makedirs(d, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {"slug": slug, "topic": topic, "root": os.path.realpath(root_op),
            "started": now, "touched": now}
    with open(os.path.join(d, "run-meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f)
except Exception as exc:
    print("register: could not write run-meta.json: %r" % exc, file=sys.stderr)
    sys.exit(1)
PY
  then
    printf 'registered=yes slug=%s\n' "$register_slug"
  else
    printf 'registered=no reason=write-failed\n'
  fi
  exit 0
fi

if [ "$mode" = resolve ]; then
  if [ -z "$root" ]; then printf 'slug=unestablished reason=no-root\n'; exit 0; fi
  # Scan the registered run directories and print the one decided line. A run dir
  # with no run-meta.json, an unreadable or non-JSON one, or one whose slug does not
  # equal its directory name is not a candidate. Ambiguous candidates are oldest
  # first (by started), one `<slug>|<topic>|<started>` field per run, joined by ';',
  # with any '|', ';' or newline inside a topic replaced by a space. The `if !`
  # keeps the one-line contract when the interpreter itself fails before printing.
  if ! python3 - "$root" <<'PY'
import json, os, re, sys
root_op = sys.argv[1]
base = os.path.join(root_op, ".prflow", "tmp", "create-issue")
safe = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
cands = []
# An unreadable base directory yields no candidates rather than a traceback with
# no stdout line — resolve must always print exactly one decided line.
try:
    names = os.listdir(base) if os.path.isdir(base) else []
except OSError:
    names = []
for name in names:
    d = os.path.join(base, name)
    mp = os.path.join(d, "run-meta.json")
    if not (os.path.isdir(d) and os.path.isfile(mp)):
        continue
    try:
        with open(mp, encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        continue
    if not isinstance(meta, dict):
        continue
    s = meta.get("slug")
    if s != name or not (isinstance(s, str) and safe.match(s)):
        continue
    cands.append((str(meta.get("started", "")), s, meta.get("topic", "")))
cands.sort(key=lambda c: (c[0], c[1]))
if not cands:
    print("slug=unestablished reason=absent")
elif len(cands) == 1:
    print("slug=%s" % cands[0][1])
else:
    def san(t):
        return re.sub(r"[|;\n]", " ", t if isinstance(t, str) else "")
    parts = ";".join("%s|%s|%s" % (s, san(t), st) for st, s, t in cands)
    print("slug=unestablished reason=ambiguous candidates=%s" % parts)
PY
  then
    printf 'slug=unestablished reason=internal-error\n'
  fi
  exit 0
fi

if [ "$mode" = adopt ]; then
  if [ -z "$root" ]; then printf 'adopted=no reason=no-root\n'; exit 0; fi
  if [ -z "$adopt_slug" ] || ! [[ "$adopt_slug" =~ $safe_slug ]]; then
    printf 'adopted=no reason=unsafe-slug\n'; exit 0
  fi
  if ! python3 - "$adopt_slug" "$root" <<'PY'
import datetime, json, os, sys
slug, root_op = sys.argv[1], sys.argv[2]
mp = os.path.join(root_op, ".prflow", "tmp", "create-issue", slug, "run-meta.json")
if not os.path.isfile(mp):
    print("adopted=no reason=absent")
    sys.exit(0)
try:
    with open(mp, encoding="utf-8") as f:
        meta = json.load(f)
    if not isinstance(meta, dict):
        raise ValueError("run-meta.json is not an object")
    meta["touched"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(meta, f)
    print("adopted=yes slug=%s" % slug)
except Exception as exc:
    print("adopt: could not update run-meta.json: %r" % exc, file=sys.stderr)
    print("adopted=no reason=write-failed")
PY
  then
    printf 'adopted=no reason=write-failed\n'
  fi
  exit 0
fi

# Cleanup mode. An empty or path-unsafe slug would make the run dir collapse to the
# shared `create-issue/` namespace root; refusing it (delete nothing, exit 0) is what
# makes the empty/unset-handle case non-destructive.
if [ -z "$slug" ]; then
  printf '%s: no slug (empty-handle); nothing removed\n' "$prog" >&2
  exit 0
fi
if ! [[ "$slug" =~ $safe_slug ]]; then
  printf '%s: refusing unsafe slug %s; nothing removed\n' "$prog" "$slug" >&2
  exit 0
fi

# Remove this run's directory (and with it its registry entry) under every --root
# given, plus every legacy issue-run-slug.<suffix> pointer whose first line equals the
# slug (the unsuffixed issue-run-slug is excluded by the .* glob). One stderr line per
# removal, and a single not-found line only when no root removed anything.
removed_any=0
for root in "${roots[@]:-}"; do
  [ -n "$root" ] || continue
  base="$root/.prflow/tmp/create-issue"
  target="$base/$slug"
  if [ -d "$target" ]; then
    if rm -rf -- "$target"; then
      printf '%s: removed run dir %s\n' "$prog" "$target" >&2
      removed_any=1
    else
      printf '%s: warning: could not remove %s\n' "$prog" "$target" >&2
    fi
  fi
  # A shell without nullglob returns the literal pattern when nothing matches, so
  # guard each candidate with `[ -f ]` (a directory named issue-run-slug.x is skipped).
  for ptr in "$base"/issue-run-slug.*; do
    [ -f "$ptr" ] || continue
    # First-line read with a bash builtin (never `tr`/`cut`, which are not
    # preflight-guaranteed); `|| :` keeps the value from a newline-less file.
    ptr_slug=""
    IFS= read -r ptr_slug < "$ptr" 2>/dev/null || :
    if [ "$ptr_slug" = "$slug" ]; then
      if rm -f -- "$ptr"; then
        printf '%s: removed slug pointer %s\n' "$prog" "$ptr" >&2
        removed_any=1
      else
        printf '%s: warning: could not remove slug pointer %s\n' "$prog" "$ptr" >&2
      fi
    fi
  done
done

if [ "$removed_any" -eq 0 ]; then
  printf '%s: nothing named %s was found under any given root\n' "$prog" "$slug" >&2
fi

exit 0
