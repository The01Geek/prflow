#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# terminal-result-class.sh — pure classifier reconciling an autonomous action's
# outcome into a BOUNDED terminal class (issue #1273).
#
# THE QUESTION IT ANSWERS. A headless autonomous action can end with process
# success (`is_error:false`, exit 0, a progress comment) yet never have produced a
# terminal result. This helper reduces the signals that DO decide an outcome — the
# workpad status class, the job status, and the review verdict-post producer outcome
# — into one closed terminal class. It is the decision *core*, deliberately pure so
# the suite can drive every arm deterministically: it does NO I/O (no gh/jq/workpad),
# just maps inputs to a class. It deliberately takes NO `is_error` / exit-status /
# progress-comment input, so no such process signal can ever satisfy the gate by
# itself — the sole route to a satisfying class is a canonical workpad terminal word
# or a genuine verdict-post producer outcome.
#
# The closed input vocabularies are the shared property of the producers this helper
# reconciles, and a generated total table (lib/terminal-result-table.tsv, produced by
# lib/generate-terminal-result-table.py) enumerates the full cross-product against
# this helper so a producer-vocabulary change re-runs its --check:
#   - workpad status class: scripts/workpad.py's status words / glyph classes, the
#     same closed set scripts/stall-backstop-decide.sh consumes
#     (complete/blocked/failed/cancelled/terminal/interim/unreadable/auth-failure).
#   - review producer outcome: the outcome line scripts/post-review-verdict.sh emits
#     (its six `POSTED review|comment REQUEST_CHANGES|APPROVE|COMMENT` literals, plus
#     its SKIP/FAILED forms), read back by scripts/check-verdict-post-reached.sh.
#
# USAGE — prints exactly one class token to stdout; exit 0 on a classified input,
# exit 2 on a usage error:
#
#   implement <WORKPAD_CLASS> <JOB_STATUS>   -> complete | blocked | incomplete
#       JOB_STATUS `cancelled` short-circuits to `incomplete` BEFORE the class switch,
#       so a cancelled job is `incomplete` even over a STALE canonical `complete`
#       workpad token. Then only the canonical `complete`/`blocked` words map to
#       `complete`/`blocked`; every other token — `failed`, `cancelled`, the legacy
#       collapsed `terminal`, `interim`, `unreadable`, `auth-failure`, empty input,
#       and any unknown token — maps to `incomplete` (fail closed).
#
#   review <OUTCOME_LINE>                    -> verdict-posted | incomplete
#       Only the six exact `POSTED review|comment REQUEST_CHANGES|APPROVE|COMMENT`
#       producer literals map to `verdict-posted`. Every other form — each `SKIP`,
#       each `FAILED`, a blank line, an unknown line, the reader's `NOT-REACHED` and
#       `UNESTABLISHED <reason>` tokens, and a `REACHED `-prefixed compatibility
#       wrapper (`REACHED POSTED review APPROVE`) — maps to `incomplete`. The match is
#       EXACT, which is what makes the REACHED-prefixed wrapper and any payload
#       appended after a valid token fall to `incomplete` rather than false-matching.
#
#   conclusion <TERMINAL_CLASS>              -> success | non-success
#       `complete` and `verdict-posted` conclude `success`; `blocked`, every
#       `incomplete`, and any unknown class conclude `non-success` (fail closed).
#
# Every selection value is derived with bash builtins (`case`, parameter expansion),
# never through tr/sed/cut/head, which lib/preflight.sh does not guarantee: a missing
# one does not fail, it yields an empty value and selects the wrong arm.
set -uo pipefail

_trc_usage() {
  echo "usage: terminal-result-class.sh {implement <workpad-class> <job-status>|review <outcome-line>|conclusion <terminal-class>}" >&2
  exit 2
}

mode="${1-}"
case "$mode" in
  implement)
    # Arity-strict: both operands are required (an absent workpad class is not an
    # empty-string workpad class). A missing operand is a usage error, not `incomplete`.
    [ "$#" -eq 3 ] || _trc_usage
    cls="$2"
    job="$3"
    # Job cancellation is a decided non-terminal end regardless of the workpad token
    # (issue #1273: incomplete even over a stale `complete`). Checked before the class
    # switch so a stale terminal token cannot win.
    if [ "$job" = "cancelled" ]; then
      echo incomplete
      exit 0
    fi
    case "$cls" in
      complete) echo complete ;;
      blocked) echo blocked ;;
      *) echo incomplete ;;
    esac
    ;;
  review)
    [ "$#" -eq 2 ] || _trc_usage
    # Trim a trailing carriage return only (a receipt line written on one platform and
    # read on another). Leading whitespace is deliberately NOT trimmed — an indented
    # line is outside every producer path, so accepting one would widen the vocabulary.
    line="${2%$'\r'}"
    case "$line" in
      'POSTED review REQUEST_CHANGES'|'POSTED review APPROVE'|'POSTED review COMMENT'|\
      'POSTED comment REQUEST_CHANGES'|'POSTED comment APPROVE'|'POSTED comment COMMENT')
        echo verdict-posted ;;
      *) echo incomplete ;;
    esac
    ;;
  conclusion)
    [ "$#" -eq 2 ] || _trc_usage
    case "$2" in
      complete|verdict-posted) echo success ;;
      *) echo non-success ;;
    esac
    ;;
  *)
    _trc_usage ;;
esac
exit 0
