#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# describe-skip-title.sh — render the deferred 'PRFlow Review' check-run TITLE for a
# given precheck skip reason (issue #389).
#
# Why a helper rather than an inline `case` in devflow-review.yml (issue #389, mirroring
# describe-denial-count.sh / PR #367): this title IS the user-facing account of WHY the
# review was deferred, so a silently mis-selected arm (a reordered `case`, a glob typo)
# would misattribute the deferral while the workflow still ran clean. Inline shell inside
# YAML cannot be unit-tested; here lib/test/run.sh drives every arm AND its order.
#
# Honesty rule (load-bearing — carried over from the extraction site): the title must
# never assert a state the precheck did not observe. behind-base / ci-not-green /
# ci-approval-required are POSITIVELY-OBSERVED conditions; `unverifiable` means a
# precondition query failed (so the title names the query failure, not a concrete cause);
# the `*` default is the deliberately generic "precondition not met", which asserts no
# specific cause. A user who rebases in response to a false "branch behind base" fixes
# nothing — so an unobserved cause is never named.
#
# Usage: describe-skip-title.sh [SKIP_REASON]
#   SKIP_REASON  a precheck skip-reason token (see the arms below). A recognized token
#                maps to its title; any other value (incl. empty) -> the generic default,
#                plus a stderr breadcrumb so skip-reason vocabulary drift (a new reason
#                added upstream in derive-review-preconditions.sh without a matching arm
#                here) is loud in the Actions log rather than silently absorbed.
# Prints one title to stdout. Always exits 0.

set -u

case "${1:-}" in
  behind-base)          printf '%s\n' 'PRFlow review waiting: branch behind base' ;;
  ci-not-green)         printf '%s\n' 'PRFlow review waiting: other CI not green' ;;
  ci-approval-required) printf '%s\n' 'PRFlow review waiting: CI approval required' ;;
  unverifiable)         printf '%s\n' 'PRFlow review waiting: preconditions unverifiable (API query failed — see the precheck log)' ;;
  *)                    echo "describe-skip-title: unrecognized skip reason '${1:-}' — using the generic title (add a case arm here when adding a reason to derive-review-preconditions.sh)" >&2
                        printf '%s\n' 'PRFlow review waiting: precondition not met' ;;
esac
exit 0
