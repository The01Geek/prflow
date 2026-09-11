#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# detect-spot-runner.sh — decide whether this host is a supported Linux EC2 host
# reachable over IMDSv2, so the Spot-interruption watcher may start (issue #261,
# AC40). Prints `linux-ec2-imdsv2` and exits 0 only on a supported host; otherwise
# prints nothing to stdout and exits 1 with a SPECIFIC no-op reason on stderr (the
# unsupported-host no-op cases get distinct breadcrumbs). Exit 1 is a negative
# determination, never a crash: the caller reads it as "do not start, log and
# continue", leaving the Claude step running.
#
# The IMDSv2 token this mints is NOT printed (the watcher mints its own), so no
# credential ever reaches stdout, a captured variable, argv, or a file — the
# "must not expose credentials" gotcha.
#
# Test seams: IMDS_BASE_URL overrides the metadata endpoint and DEVFLOW_CURL
# overrides the curl binary (a module stubs it deterministically rather than
# relying on PATH order, which leaks to a real EC2 host's live IMDS). Windows and
# macOS are outside the watcher's process-lifecycle support boundary (AC40) — the
# uname gate below is what excludes them.
set -uo pipefail

IMDS_BASE_URL="${IMDS_BASE_URL:-http://169.254.169.254}"
CURL="${DEVFLOW_CURL:-curl}"

os="$(uname -s 2>/dev/null || echo unknown)"
if [ "$os" != "Linux" ]; then
  echo "detect-spot-runner: non-Linux host ('$os') — the Spot-interruption watcher is Linux-only; not started" >&2
  exit 1
fi

# Single IMDSv2 token request IS the EC2 detection: a non-EC2 host cannot reach
# 169.254.169.254 and fails this the same way an EC2 host with IMDS disabled does.
# 1s connect / 2s total timeout per AC42. -s silences the progress meter; -f is
# NOT used so a non-2xx body still returns and the empty-token arm below classifies
# it rather than curl's generic HTTP-error exit.
token="$("$CURL" -sS -X PUT "${IMDS_BASE_URL}/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" \
  --connect-timeout 1 --max-time 2 2>/dev/null)"
rc=$?
if [ "$rc" -ne 0 ]; then
  # curl 7 (connection refused) / 28 (timeout) is the ordinary non-EC2 signature;
  # any other non-zero is a different IMDS failure. Both leave the step running.
  if [ "$rc" -eq 7 ] || [ "$rc" -eq 28 ]; then
    echo "detect-spot-runner: IMDSv2 endpoint unreachable (curl exit $rc) — non-EC2 host or IMDS blocked; watcher not started" >&2
  else
    echo "detect-spot-runner: IMDSv2 token request failed (curl exit $rc); watcher not started" >&2
  fi
  exit 1
fi
if [ -z "$token" ]; then
  echo "detect-spot-runner: IMDSv2 token request returned empty; watcher not started" >&2
  exit 1
fi

echo "linux-ec2-imdsv2"
exit 0
