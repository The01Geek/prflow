#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""Union the vendored plugin's own helper grants into a cloud run's allowlist.

The workflow's `Resolve allowed-tools` step bakes a generated allowlist literal
(`TOOLS='…'`) and appends the consumer's configured extras. That baked literal
reaches a consumer through `install.sh`, while the plugin (skills + helpers +
`lib/capability-profiles.json`) reaches them through the `prflow_version` pin —
two independent channels that drift apart, so a consumer on a stale workflow can
end up running skills that call plugin helpers the older baked list never granted.
Every such invocation is then silently denied at run time (issue #352).

This resolver closes that gap at run time. It reads the baseline allowlist
(`${TOOLS}${EXTRA}`) from **stdin**, the manifest path from the `MANIFEST`
environment variable and the profile name from `PROFILE`, and prints the baseline
with every *plugin-helper* grant the matching profile names and the baseline lacks
appended. A plugin-helper grant is exactly `Bash(.prflow/vendor/prflow/<relative
path with no '..' segment>:*)` — the same vendored tree whose helpers the existing
grants already execute, so the union widens no trust boundary. Tokens that are not
plugin-helper grants (git, gh, unix tools, consumer commands) stay workflow-owned
and are never added.

stdin / env are the MSYS-safe channels: Git Bash rewrites a manifest path passed as
an argument (and a leading-slash or colon-separated env value), but never stdin, so
the baseline travels there. The manifest path handed in is the repo-relative
`.prflow/vendor/prflow/lib/capability-profiles.json`, which MSYS leaves untouched.

The resolver exits 0 on each arm the unit test enumerates — the union arm, the
empty-profile arm, and every degraded arm (manifest absent, unreadable, not JSON,
wrong-typed, a profile it does not define, or an `@group` it does not define) — so no
resolver failure ends a cloud run that would otherwise have started: a degraded arm
prints the baseline unchanged and emits one `::warning::` naming
`prflow_version`/`install.sh` as the remedy, and the union arm emits one `::notice::`
naming each added token. The deciding path uses python3 alone (no `tr`/`sed`/`cut`/`wc`/`head`).
"""

from __future__ import annotations

import json
import os
import re
import sys

# Bash(<vendored path>:*). The path is captured so a '..' segment can be told from a
# well-formed grant: an escaping token is never added AND trips the one-warning degraded
# arm — dropping that check would let a manifest smuggle an out-of-tree grant in silently.
_PLUGIN_HELPER_RE = re.compile(r"^Bash\((\.prflow/vendor/prflow/[^\s:]+):\*\)$")


def _warn(reason: str) -> None:
    # Exactly one ::warning:: line: the manifest could not be read, so the allowlist
    # was not unioned. Naming prflow_version + install.sh gives the consumer the
    # remedy (refresh the workflow, check the pin).
    sys.stderr.write(
        f"::warning::resolve-allowed-tools: {reason}; the vendored plugin manifest "
        "could not be read, so plugin-helper grants were NOT unioned into the "
        "allowlist — re-run install.sh and check prflow_version.\n"
    )


def _baseline_tokens(baseline: str) -> set[str]:
    # The baseline is the baked list (', '-separated) concatenated with the extras
    # (','-separated). A plugin-helper token contains no comma, so splitting on comma
    # and stripping whitespace recovers exactly the present tokens.
    return {piece.strip() for piece in baseline.split(",") if piece.strip()}


def _expand_profile(spec, groups) -> list[str] | None:
    # Mirror generate-capability-profiles.py's resolve_profile: splice each @group, append
    # each non-@group entry. Return None on a degraded input (non-list spec, non-string entry,
    # unknown @group) so the caller warns — the generator DIES on these; this resolver must not.
    if not isinstance(spec, list):
        return None
    tokens: list[str] = []
    for entry in spec:
        if not isinstance(entry, str):
            return None
        if entry.startswith("@"):
            gname = entry[1:]
            if not isinstance(groups, dict) or gname not in groups:
                return None
            gtoks = groups[gname]
            if not isinstance(gtoks, list) or not all(
                isinstance(t, str) for t in gtoks
            ):
                return None
            tokens.extend(gtoks)
        else:
            tokens.append(entry)
    return tokens


def _force_utf8_streams():
    """Force stdin/stdout/stderr to UTF-8, idempotently and defensively, in the CLI
    entry path only (not at import) — so a non-UTF-8 ambient codec (Windows' cp1252)
    cannot mangle the baseline read from stdin or the resolved string written to stdout.
    Tolerates a non-`TextIOWrapper` stream."""
    for _stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def main() -> int:
    _force_utf8_streams()
    baseline = sys.stdin.read()

    manifest_path = os.environ.get("MANIFEST", "")
    profile_name = os.environ.get("PROFILE", "")

    try:
        with open(manifest_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError, UnicodeError) as error:
        _warn(f"manifest {manifest_path!r} is absent or unreadable ({error})")
        sys.stdout.write(baseline)
        return 0

    if not isinstance(data, dict):
        _warn(f"manifest is not a JSON object (got {type(data).__name__})")
        sys.stdout.write(baseline)
        return 0

    profiles = data.get("profiles")
    if not isinstance(profiles, dict) or profile_name not in profiles:
        _warn(f"manifest defines no {profile_name!r} profile")
        sys.stdout.write(baseline)
        return 0

    expanded = _expand_profile(profiles[profile_name], data.get("groups"))
    if expanded is None:
        _warn(f"profile {profile_name!r} could not be resolved (bad shape or unknown @group)")
        sys.stdout.write(baseline)
        return 0

    present = _baseline_tokens(baseline)
    added: list[str] = []
    seen: set[str] = set()
    for token in expanded:
        m = _PLUGIN_HELPER_RE.match(token)
        if not m:
            # Not a vendored-tree token at all (git/gh/unix/consumer command): it is
            # workflow-owned and never unioned from the manifest.
            continue
        if ".." in m.group(1).split("/"):
            # A vendored-prefix token that escapes the tree is malformed: never add it,
            # and take the one-warning degraded arm rather than silently dropping it.
            _warn(f"manifest names a vendored token with a '..' segment: {token!r}")
            sys.stdout.write(baseline)
            return 0
        if token in present or token in seen:
            continue
        seen.add(token)
        added.append(token)

    if added:
        # Preserve the baseline bytes exactly; append each missing grant in the baked
        # ', '-separated style. One ::notice:: names every addition (GitHub caps
        # annotations per step, so one line, not one per token).
        if baseline.strip():
            resolved = baseline + "".join(f", {token}" for token in added)
        else:
            resolved = ", ".join(added)
        sys.stdout.write(resolved)
        sys.stderr.write(
            "::notice::resolve-allowed-tools: added "
            f"{len(added)} plugin-helper grant(s) from the vendored manifest: "
            + ", ".join(added)
            + "\n"
        )
    else:
        # Nothing to add (an empty profile, or every grant already present): print the
        # baseline unchanged with no notice and no warning.
        sys.stdout.write(baseline)

    return 0


if __name__ == "__main__":
    sys.exit(main())
