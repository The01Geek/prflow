#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# filter-runner-tools.sh — the cloud reviewer's deny-list floor (issues #363, #402).
#
# This is the AUTHORITATIVE deny-list floor that runs at consume-time, on the
# trusted base-ref `prflow_runner.allowed_tools` value, before those freeform
# build/verify commands were appended to the read-only `review` profile in the
# review-runner workflow (devflow-runner.yml, since removed with that tier). It
# strips the categorically-unrecoverable
# tier no matter what /devflow:init's LLM enrichment or a later hand-edit wrote:
# tree-mutation tools (Edit/Write/MultiEdit/NotebookEdit) and any Bash entry that
# can reach a raw shell / eval / privilege binary. The fast-feedback `denylisted`
# jq mirror in scripts/detect-project-tools.sh applies the same rules, but this
# copy ENFORCES — a hand-edit to the CONFIG cannot get past it. A hand-edit to
# THIS FILE is a different threat, and the enforcement point was the workflow,
# not this header: devflow-runner.yml (since removed) executed the floor only from a
# TRUSTED copy — one materialized from the base ref by its baseprovision step, or the
# vendored copy when (and only when) vendor-plugin freshly fetched it at the
# pinned prflow_version — never from the PR-head checkout. A PR that edits
# this file therefore changes nothing about how that PR's own review is
# floored; the edit takes effect only after it lands on the base branch.
#
# Why a helper rather than an inline loop in the workflow YAML: the filter IS a
# security boundary, so a logic regression (a broken command-word split, the
# parameterized file-tool bypass #402 fixes, a guard that stops gating) must fail
# the suite. Inline shell inside YAML cannot be unit-tested; here lib/test/run.sh
# drives the whole adversarial input matrix directly. The workflow calls this
# helper and fails CLOSED (appends nothing, warns) when it cannot be resolved.
#
# I/O contract (both channels are honest and separable):
#   input  : the raw RUNNER_TOOLS value in the environment (may carry newlines/CRs
#            from the heredoc transport; comma-and-newline delimited).
#   stdout : the KEPT entries as one comma-joined line (empty line if none kept) —
#            byte-for-byte the value the workflow appends to the review profile.
#   stderr : one strip-warning line per stripped entry (naming the entry), which
#            the workflow re-emits as a per-entry `::warning::`.
#   exit   : always 0 (best-effort — a typo in one entry must not abort the review).
#
# The file-tool tier (#402) matches the tool NAME — the token before the first
# `(`, compared case-insensitively — so a parameterized entry (Write(**),
# Edit(src/**), notebookedit(x)) is stripped exactly like the bare name. The
# name-match uses `shopt -s nocasematch` (a bash builtin, no `tr`) precisely
# because the file-tool decision is a SELECTION: deriving the lowercased name
# through a non-preflight PATH tool would fail OPEN (empty -> not stripped) if the
# tool were missing. Case-insensitivity is fail-closed hardening — a lowercase
# `write(**)` is inert as a Claude Code rule, so stripping it costs nothing.
#
# The Bash tier is byte-for-byte the pre-#402 behavior: inspect the
# command-position binary (first whitespace token of the spec, before the first
# ':' or ')') by its basename and deny a raw shell / eval / privilege binary or an
# exec-wrapper; deny a leading env-assignment; deny any shell metacharacter in the
# spec; deny an empty or bare command word. Non-leading arg tokens are NOT scanned,
# so legitimate tools whose subcommand/arg is a deny word (Bash(docker exec:*),
# Bash(make CC=gcc:*), Bash(go run ./cmd/sh:*)) are kept.

set -u

DENY_CMDS='bash sh zsh dash ksh fish eval exec source sudo doas su env xargs nice timeout nohup setsid command chroot runuser'

RUNNER_TOOLS="${RUNNER_TOOLS-}"

FILTERED=''

# Newlines/CRs in an entry are normalized to the comma delimiter so a multi-line
# entry can't smuggle a second tool past the per-entry check (the heredoc
# transport forwards newlines verbatim). Then split on comma ONCE (an entry like
# "Bash(go build:*)" keeps its internal space) and restore the default IFS.
# `set -f` disables pathname expansion for the split: every entry contains a
# literal `*` (e.g. Bash(npm:*)), so without noglob the unquoted expansion could
# glob against the checked-out working tree. All per-entry parsing below uses
# parameter expansion / `case` (no word-split of an unquoted var), so no further
# globbing occurs.
RUNNER_TOOLS="${RUNNER_TOOLS//$'\r'/}"
RUNNER_TOOLS="${RUNNER_TOOLS//$'\n'/,}"
OLDIFS=$IFS
IFS=','
set -f
set -- $RUNNER_TOOLS
set +f
IFS=$OLDIFS

for raw in "$@"; do
  # Trim surrounding whitespace from the whole entry.
  entry="${raw#"${raw%%[![:space:]]*}"}"
  entry="${entry%"${entry##*[![:space:]]}"}"
  [ -z "$entry" ] && continue
  denied=false

  # File-tool tier (#402): strip Edit/Write/MultiEdit/NotebookEdit, bare or
  # parameterized, case-insensitively. The tool NAME is the token before the
  # first '(' — so Write, Write(**), Edit(src/**) all match. nocasematch is
  # scoped to THIS case only (unset immediately) so the case-sensitive Bash-tier
  # matching below is unchanged (a lowercase `bash(...)` stays kept, as before).
  # The Bash tier stays case-sensitive purely for REGRESSION-CORPUS STABILITY —
  # #402 preserves the pre-#402 Bash behavior byte-for-byte (a run.sh corpus pins
  # every kept/stripped shape) — NOT because of any security distinction; a
  # lowercase `bash(...)` is just as inert a Claude Code rule as `write(**)`. If a
  # future change wants case-insensitive Bash matching too, widen the corpus first.
  ftname="${entry%%(*}"
  ftname="${ftname%"${ftname##*[![:space:]]}"}"   # trim trailing whitespace
  shopt -s nocasematch
  case "$ftname" in
    Edit|Write|MultiEdit|NotebookEdit) denied=true ;;
  esac
  shopt -u nocasematch

  if [ "$denied" = false ]; then
    case "$entry" in
      Bash) denied=true ;;            # bare Bash = all shell
      Bash\(*)                         # prefix match: no trailing ')' required
        inner="${entry#Bash(}"
        cmd="${inner%%:*}"             # spec: before the first ':'
        cmd="${cmd%%)*}"               # and before the first ')'
        cmd="${cmd#"${cmd%%[![:space:]]*}"}"
        cmd="${cmd%"${cmd##*[![:space:]]}"}"
        binword="${cmd%%[[:space:]]*}" # command-position token (no glob)
        binbase="${binword##*/}"        # strip any path
        if [ -z "$cmd" ]; then
          denied=true                  # empty command word = all shell
        else
          case "$cmd" in
            *[';|&$<>()']*) denied=true ;;   # shell metacharacter in spec
            *'`'*) denied=true ;;            # backtick command-substitution
          esac
          case "$binword" in
            [A-Za-z_]*=*) denied=true ;;     # leading env-assignment (FOO=1 cmd)
          esac
          if [ "$denied" = false ]; then
            for c in $DENY_CMDS; do
              if [ "$binbase" = "$c" ]; then denied=true; break; fi
            done
          fi
        fi
        ;;
    esac
  fi

  if [ "$denied" = true ]; then
    # Per-entry strip warning (#402): the workflow re-emits each as a `::warning::`.
    printf "prflow_runner.allowed_tools: stripped '%s' — never permitted on the reviewer's write-token job (tree mutation / raw shell / privilege escalation)\n" "$entry" >&2
  else
    FILTERED="${FILTERED:+$FILTERED,}$entry"
  fi
done

printf '%s\n' "$FILTERED"
exit 0
