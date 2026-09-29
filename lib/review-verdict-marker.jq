# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
# Marker grammar only; each reader owns placement, ambiguity and verdict policy.
def verdict_marker_scan($n):
    (if type == "string" then . else "" end
     | split("\n") | .[0:$n] | map(rtrimstr("\r"))) as $lines
    | {loose: ([$lines[] | select(test("^<!-- prflow:review-verdict[ >]"))] | length),
       markers: [$lines[]
         | capture("^<!-- prflow:review-verdict head=(?<head>[0-9a-fA-F]{40}) verdict=(?<verdict>APPROVE|REJECT) -->$")
         | .head |= ascii_downcase]};
