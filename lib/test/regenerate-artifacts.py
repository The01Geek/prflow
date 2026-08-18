#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Daniel Radman
# SPDX-License-Identifier: MIT
"""One batched pass over the suite-owned generated artifacts (issue #619).

A fix or implement loop that edits prompt surfaces, engine files, or the capability
manifest induces drift in checked-in generated records.
Discovering that drift one full-suite run at a time is the dominant cost of a loop
iteration, because the full suite is the slowest verification step in the repo. Run
this helper once after applying edits and before each full-suite re-verify run: it
regenerates any mechanically-safe artifact (none is registered today — see the note above
the ROWS tuple), runs each judgment-gated artifact's
non-writing check, and reports every resulting judgment item together, so the next
suite run verifies a tree whose generated artifacts are already reconciled.

OPT-IN ROWS. A row declaring `opt_in: True` is skipped by the default pass and runs only
under the flag its report line names (`--with-floors` for `exact-module-floors`, the one
row whose check runs the real focused module runners and costs minutes rather than
milliseconds). The skip is always PRINTED as its own row line — never inferred from
silence — so a reader can tell "measured and clean" from "not measured". Under the flag,
the row is still skipped when an earlier row already forced exit 1 or hit the
infrastructure state: measuring a tree this same pass has just reported red spends minutes
judging a tree that is about to change. Neither skip forces an exit code of its own.
Deferring the floor measurement is a real, bounded gap rather than a free one: the module
harness and the `modules-*` shards fail only a tally BELOW the floor, so a floor left
un-raised is caught solely by `test_module_runner.py`'s equality assertion — which
executes the full exact-policy population on CI (and on a direct local run), so a stale
floor surfaces on CI rather than in this agent's own run. Run the flag before a
completion claim to catch it here first. The cheap rows,
including the SHA-256 pinned cloud-writer manifest whose staleness turns a required check
red, run on every pass.

REGISTRATION RULE (shipped as artifact content, not merely convention). Kept on ONE
line deliberately: a sentence wrapped across a line break lives on no single line, so
the suite's line-based pin on it would silently find nothing (the issue-375
wrapped-literal hazard).
A PR that adds a checked-in generated artifact gated by the suite adds a row to this registry in the same PR.

Machine-enforcing that rule for future generators is a disclosed NON-GOAL — it is a
review convention of the same class as the capability manifest's `manifest_version`
bump rule. The suite pins the current rows through `--list`.

INCLUSION CRITERION for a row: a checked-in record whose suite gate goes RED on
loop-induced edits AND whose state this helper can establish without writing it via a
standalone non-writing check command (a regeneration command, for a mechanical row, or a
non-writing checker for a judgment row).

PARTIAL REGISTRATION: `scripts/workflow-flight-recorder-registry.json` remains a
hand-maintained inventory, and the coverage guard's `[arm8]` arm checks that inventory.
The `exact-module-floors` row below additionally owns only its exact-policy modules'
`minimum_assertions` fields, because those values can be measured and raised safely;
the row does not synthesize or rewrite any other registry metadata.

ROW ORDER is a maintenance obligation, not decoration. Rows run in the order listed and
no row re-runs, so a row whose generator READS a file an earlier row WRITES must be
ordered after it. No WRITER consumes another writer's outputs: `exact-module-floors` may
raise only registry floor fields and their coupled `run.sh` call sites, and the identity
generator's four baked regions (`install.sh` and three siblings) are NOT in the manifest
closure. (The former `cloud-writer-manifest` writing row was removed in issue #1445 — the
cloud-writer manifest is now written on `main` alone, not by this batched pass.)

One READER-before-WRITER pair does exist and is deliberately left in this order:
`coverage-map-ratchet` runs `coverage_map_guard.py`, which reads `lib/test/run.sh` — a
file the later `exact-module-floors` row may rewrite — so within one pass the ratchet
judges the pre-raise `run.sh`. That is sound only because of what the raise changes: a
floor reconciliation rewrites a single numeric operand inside an existing
`devflow_run_full_suite_module` call, adding and removing no call site, so the guard's
block enumeration and attribution derivation see an identical structure either way. It
is NOT sound in general — a future row that rewrites `run.sh` STRUCTURALLY must be
ordered above `coverage-map-ratchet`, or the ratchet will judge a stale tree. Adding a
row whose output feeds another row's input means placing it above that row here; nothing
verifies the placement, because rows declare their outputs and not their inputs.

WRITE SCOPE: writing rows declare their complete `writes` set in the registry. The
exact-floor row may raise `scripts/workflow-flight-recorder-registry.json` and
`lib/test/run.sh` together. Every judgment row runs a non-writing check and never writes
its artifact. (No `mechanical` row is registered today; see the note above the ROWS
tuple.)

EXIT CONTRACT (exactly three states). Its `mechanical row` clauses are conditional on such
a row being registered; none is today, so they select nothing in a production run:
  0 — every row resolved in its declared clean state (its command exited in that
      state), the mechanical regeneration changed nothing, and no exit-1-forcing
      judgment item was printed.
  1 — at least one of {a writing row changed its declared output, an exit-1-forcing judgment item
      was printed} holds, and no row hit the infrastructure state.
  2 — infrastructure failure. Exit 2 takes precedence over exit 1. It is reached from
      an exit code OUTSIDE a row's declared set, from paths that occur despite an
      IN-set exit, and from paths where no row exit code was ever established — the
      declared set bounds what the row's generator is expected to return, not what
      counts as an established check:
        * a row's command failed to launch (absent file, interpreter launch failure);
        * a launched command exited outside its row's declared exit set;
        * a judgment row exited inside its declared set but its output matched one of
          the row's `infra_markers` (an input failure reported as an exit code that
          otherwise means drift);
        * the mechanical row exited in its clean state but produced no artifact;
        * the mechanical row exited 1 with no `cloud-writer-contract:` marker (an
          interpreter traceback rather than a reconcilable closure error);
        * an artifact snapshot could not be read;
        * the helper itself raised an unhandled exception (the top-level net at the
          bottom of this file — without it CPython would exit 1, aliasing an unchecked
          run onto the resolvable "action required" state).

These three are the states main() itself selects. argparse also exits 2 on a usage
error (an unknown flag) before any row runs — the same code as the infrastructure
state, and consistent with it (nothing was checked), but it is not one of the three
states above and no row report accompanies it.
"""

import argparse
import importlib.util
import os
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

MECHANICAL_ARTIFACT = "scripts/devflow-cloud-writer-contract.json"

# The preflight's MACHINE-READABLE verdict line (issue #1244). COUPLED CONTRACT, edited
# together with `lib/test/run-parallel.sh`: the parallel coordinator keys its fail-closed
# refusal on the exact line `regenerate-artifacts: preflight-verdict: drift` and on nothing
# else, so the human remedy sentences below it are free prose a reword cannot break. Before
# this line existed the coordinator matched a substring of that prose, which meant a
# rewording in THIS file would silently make the coordinator fail OPEN on real drift.
#
# Emitted for all three verdicts rather than only for drift, so a consumer can distinguish
# "checked and clean" from "could not check" without re-deriving either from an exit code —
# and matched LINE-EXACTLY by the coordinator, so the same text quoted inside a row's own
# diagnostic (which is always indented or row-prefixed) can never be mistaken for a verdict.
PREFLIGHT_VERDICT_PREFIX = "regenerate-artifacts: preflight-verdict: "

# The closed set of conflict-resolution classes (issue #655). A merge conflict in a
# checked-in generated artifact must never be hand-merged: hand-merged bytes match no
# source of truth, and the row's own gate then reports the result as drift with a remedy
# that steers the agent at the wrong file. `conflict_class` states WHICH remedy applies:
#   regenerate       — re-run the row's writer against the merged tree; the artifact is a
#                      pure function of its source, so the merged source is the answer.
#   reconcile-source — merge the SOURCE of truth first, regenerate from it, then
#                      hand-update whatever coupled by-hand sibling the row names.
#   by-hand          — no writer exists; a human re-measures or hand-merges the record.
# Kept a module-level constant so a row's class is validated against one enumeration
# rather than each consumer re-spelling the vocabulary.
CONFLICT_CLASSES = ("regenerate", "reconcile-source", "by-hand")

# The row-kind vocabulary `run_row` dispatches on. Closed and validated at import for the
# same reason `CONFLICT_CLASSES` is: `run_row` routes `mechanical` and `monotonic` through
# their own outcome classifiers and lets every other kind fall through to the generic
# exit-code arm, so a typo'd kind does not fail — it silently downgrades that row to the
# weaker generic classification and reports a clean pass the row's real contract never
# established.
ROW_KINDS = ("mechanical", "monotonic", "judgment")

# Per-row wall-clock bound (issue #1457). `timeout_seconds` is DECLARED DATA a registry row
# must carry, validated at import exactly as `preflight_eligible` is, so an absent or non-int
# value is a registry defect rather than a silent global default. The global override below
# replaces the declared bound for testing and slow hosts; empty behaves as unset (this repo's
# `DEVFLOW_*` rule), and a malformed value is refused loudly rather than silently ignored.
ROW_TIMEOUT_OVERRIDE_ENV = "DEVFLOW_ARTIFACT_ROW_TIMEOUT_SECONDS"

# POSIX-only process-group termination (issue #1457 AC6/AC8): a bare subprocess timeout kills
# only the direct child and orphans the rest, so the bounded launch puts the child in its own
# session and signals the whole group. `os.killpg`/`os.getpgid` and `start_new_session` are
# absent on a non-POSIX host, so every use of them is guarded on this flag.
_POSIX = os.name == "posix"

# Ordered registry. `argv` is resolved under the target root and run with that root as
# the working directory, so a fixture root exercises the fixture's own generators.
# `exits` is the row's declared exit-code set and `clean` its positive arm; an exit
# outside `exits` is the infrastructure state, never a clean pass.
# Every row is command-backed: main() dispatches each through run_row uniformly rather than
# re-deciding per row (run_row still special-cases the mechanical kind internally).
ROWS = (
    # Do NOT re-add a `cloud-writer-manifest` row here (issue #1445) — a batched pass that
    # writes that artifact on a feature branch reintroduces the merge chokepoint and turns
    # lib/test/cloud-writer-retention-check.py RED.
    {
        "name": "capability-profile-literals",
        # Bound = measured 0.064s x500 (issue #1457 AC2a); the ms-scale rows carry a large
        # multiple because their cold-start/contention variance dwarfs their mean.
        "timeout_seconds": 32,
        "kind": "judgment",
        "argv": ("python3", "lib/generate-capability-profiles.py", "--check"),
        "clean": (0,),
        "exits": (0, 1),
        "policy": (
            "merge lib/capability-profiles.json first, regenerate with "
            "`python3 lib/generate-capability-profiles.py`, and hand-"
            "update lib/review-profile.tokens when the resolved review list widens"
        ),
        # reconcile-source, not regenerate: the generated workflow literals are a pure
        # function of the manifest, but the manifest itself is the conflicted source and
        # the reviewer lock is a by-hand sibling the generator NEVER writes. Regenerating
        # before merging the manifest would silently revert whichever grant the
        # concurrent PR added.
        "conflict_class": "reconcile-source",
        # The conflicted SOURCE of truth is the manifest; the generated workflow literals
        # are appended at emit time from the generator's own REGIONS (bound below).
        "conflict_paths": ("lib/capability-profiles.json",),
        "conflict_paths_extra": None,  # bound to _capability_region_targets below.
        "coupled_by_hand": (("lib/review-profile.tokens", "by-hand"),),
        # Same discriminator the other marker-bearing judgment rows carry: the generator raises
        # GenError for an INPUT failure (an absent/unreadable/malformed manifest, an
        # unreadable target workflow, an unreadable reviewer lock) and exits 1 —
        # byte-identically to a real token drift. Without these markers a malformed
        # lib/capability-profiles.json would be reported as a judgment item telling the
        # agent to regenerate from the very file the generator could not read, and the
        # pass would record `run` for a row that was never checked.
        # Deliberately EXCLUDED: the `manifest: …` schema errors, the `region …` anchor
        # errors, and the review-boundary/token-drift outputs — those ARE genuine
        # findings, and matching them would hide a real one (the worse error).
        "infra_markers": (
            "manifest absent:",
            "manifest unreadable:",
            "manifest malformed JSON:",
            "target workflow unreadable:",
            "target workflow file absent:",
            "reviewer security boundary lock unreadable:",
        ),
        # Preflight (issue #1244): `--check` is read-only and sub-second (~0.04 s). The
        # preflight reuses this row's `infra_markers` to keep an input failure out of the
        # drift verdict, exactly as the batched pass does.
        "preflight_eligible": True,
    },
    {
        "name": "plugin-identity-regions",
        # Bound = measured 0.044s x500 (issue #1457 AC2a).
        "timeout_seconds": 22,
        "kind": "judgment",
        "argv": ("python3", "lib/generate-plugin-identity.py", "--check"),
        "clean": (0,),
        # (0, 1) deliberately, though the generator also returns 2: an unreadable or
        # malformed identity SOURCE (`lib/plugin-identity.json` /
        # `.claude-plugin/plugin.json`) exits 2, and leaving 2 outside the declared set
        # is what routes it to the infrastructure state instead of a judgment item
        # telling the agent to regenerate from the very file the generator could not
        # read. Widening this set to (0, 1, 2) would convert that fail-closed into a
        # misdirected remedy.
        "exits": (0, 1),
        "policy": (
            "reconcile lib/plugin-identity.json + .claude-plugin/plugin.json first, then "
            "rewrite the baked regions with `python3 lib/generate-plugin-identity.py`"
        ),
        # regenerate, not reconcile-source: unlike the capability row, this generator has
        # no by-hand sibling lock, and each region is a pure function of the identity
        # source — so re-running the writer against the merged tree IS the answer, and the
        # policy above names a runnable WRITE command as a `regenerate` row must.
        "conflict_class": "regenerate",
        # The three generated regions this row uniquely owns, named statically rather than
        # imported from the generator's own REGIONS table (the technique the capability row
        # uses). REGIONS carries a FOURTH file — `.github/workflows/devflow-runner.yml`,
        # which also holds a capability-profile region — and `emit_list` requires every
        # conflict path to resolve to exactly one row, so sourcing REGIONS wholesale would
        # raise the duplicate-claim error and take the whole listing to exit 2.
        # DISCLOSED RESIDUAL, not an oversight: a conflict landing in the identity region of
        # `devflow-runner.yml` still matches the capability row and is handed that row's
        # `reconcile-source` recipe, which names the capability manifest and not this
        # generator. That recipe is the stricter procedure and does not corrupt the file,
        # but it is silent about re-running this writer. Routing one path to two classes is
        # the fail-open the uniqueness rule exists to close, so the shared file keeps its
        # single existing owner and the residual is recorded here rather than papered over.
        "conflict_paths": (
            ".github/actions/vendor-plugin/vendor-slice.sh",
            "install.sh",
            "scripts/resolve-extra-plugins.sh",
        ),
        # The same discriminator the other judgment rows carry, and every entry is a
        # measured exit-1 emission of THIS generator, not a guess:
        #   * `banner(s); expected exactly 1` — a region file whose begin banner was lost
        #     or duplicated (a bad merge, a hand-edit). `locate()` fails closed and the
        #     generator cannot rewrite a region it cannot find.
        #   * `after its begin banner` — the matching end marker is gone; same cause.
        #   * a traceback — a region FILE is absent entirely, which surfaces as an
        #     uncaught FileNotFoundError from `path.read_text` and so exits 1 with no
        #     diagnostic of the generator's own.
        # None of the three is repaired by running the generator, so reporting them as
        # judgment items would aim the remedy at the wrong file while the real fault
        # (a broken region, a missing file) stayed invisible.
        # Deliberately EXCLUDED: `baked identity region(s) differ from`, which is the
        # genuine drift this row exists to surface — matching it would hide the finding.
        # Also excluded, because they are unreachable from this CLI rather than merely
        # unlikely: the identifier-shape and single-quote SystemExits inside the payload
        # builders. `plugin_identity.load()` applies the same character contract first and
        # exits 2, so those two arms are defense in depth for a hand-built identity dict
        # and no CLI input reaches them at exit 1.
        "infra_markers": (
            "banner(s); expected exactly 1",
            "after its begin banner",
            "Traceback (most recent call last)",
        ),
        # Preflight (issue #1244): `--check` is read-only and sub-second (~0.05 s).
        "preflight_eligible": True,
    },
    {
        "name": "coverage-map-ratchet",
        # Bound = measured 0.623s x50 (issue #1457 AC2a).
        "timeout_seconds": 31,
        "kind": "judgment",
        "argv": ("python3", "lib/test/coverage_map_guard.py", "."),
        "clean": (0,),
        "exits": (0, 1),
        "policy": "add the missing coverage rows per the issue-591 ratchet in lib/test/modules/coverage-map.json (for a run_sh_blocks completeness/attribution item, `python3 lib/test/coverage_map_guard.py . --fix` is the hand-invoked repair). For a MERGE-CONFLICT resolution of this file, do NOT reach for `--fix`: it cannot restore a key a resolution dropped (issue #1194), so keep every key from BOTH sides — let the registered JSON-aware merge driver union them (register with `python3 lib/test/coverage-map-merge-driver.py --register`, verify with `--check`), or take both sides by hand then re-canonicalize; `python3 lib/test/coverage-map-retention-check.py` fails RED on any dropped key/content and backstops the web-editor path the driver cannot reach",
        # by-hand, and it STAYS by-hand: since issue #695 coverage_map_guard.py does have
        # a write path, but only behind the explicit, hand-invoked `--fix` flag. The
        # `argv` above deliberately omits it, so this row still runs a non-writing check
        # and the batched pass leaves the map byte-unchanged — the property the `#619 A3`
        # write-scope assertion pins. Wiring `--fix` into this row would flip that
        # assertion RED. The files half of the map remains hand-merged, row by row.
        "conflict_class": "by-hand",
        "conflict_paths": ("lib/test/modules/coverage-map.json",),
        # Same discriminator: the guard prefixes a genuine input failure (git absent,
        # not a repo) with `[input-error]` and exits 1, identically to a real ratchet
        # violation. That is not a coverage-row problem and must not be reported as one.
        # `[input-error]` covers only the git-ls-files failure. An absent or malformed
        # coverage-map / registry takes a different path (`[arm4]` / `[arm8]`), and arm 4
        # RETURNS before every map-dependent arm — so an unreadable map both suppresses
        # every real violation AND, without these markers, reported as a judgment item
        # telling the agent to add rows to the very file the guard could not read.
        # Matched on the ARM PREFIX, not on each arm's message text. Arm 4 has two
        # early-return legs — `coverage-map unreadable: …` AND `{shape_error}` (a
        # structurally-valid but wrong-shape map: a bad merge, a truncated write, a
        # schema bump landing before the migration) — and both suppress every
        # map-dependent arm identically. Enumerating the unreadable leg alone left the
        # shape leg reported as `add the missing coverage rows`, telling the agent to
        # edit rows in the very file whose schema is broken, while every genuine
        # violation stayed invisible. Enumerating each shape string instead would
        # re-couple this row to a dozen literals in another module with nothing pinning
        # them together; the prefix is stable and cannot drift that way.
        # Safe because EVERY `[arm4]`/`[arm8]` emission in coverage_map_guard.py is an
        # input failure — genuine ratchet violations carry the other arm numbers.
        "infra_markers": (
            "[input-error]",
            "[arm4] ",
            "[arm8] ",
        ),
        # Preflight (issue #1244): `argv` is the non-writing `.` check (the `--fix` write
        # path is deliberately never wired into this row), read-only and sub-second
        # (~0.27 s).
        "preflight_eligible": True,
    },
    {
        "name": "exact-module-floors",
        # Bound = measured 137.44s x4 (issue #1457 AC2a); the minutes-scale row uses a small
        # multiple. Its measurement is under the landed `--heavy-units smoke` bounding of the
        # slowest module, not the superseded ~466 s figure the removed comment cited.
        "timeout_seconds": 550,
        "kind": "monotonic",
        "argv": ("python3", "lib/test/reconcile-module-floors.py"),
        "clean": (0,),
        "exits": (0, 1),
        "writes": (
            "scripts/workflow-flight-recorder-registry.json",
            "lib/test/run.sh",
        ),
        # The recipe names the BATCH entry point, never this row's own argv. `argv` is
        # how the batch runs the reconciler as an internal subprocess; the recipe is what
        # an AGENT is told to run, and on the cloud implement tier the interpreter-head
        # form `python3 lib/test/reconcile-module-floors.py` is an ungranted shape that is
        # silently denied — so a recipe naming it would hand the agent a command that
        # produces no output and no error, and the floors would stay unreconciled.
        "policy": (
            "hand-merge the conflicted region as any normal file, then re-measure by "
            "rerunning the granted direct leading-token form "
            "`lib/test/regenerate-artifacts.py`; its exact-module-floors row measures "
            "the real focused runners, raises both coupled floors together, and "
            "refuses every decrease"
        ),
        # `by-hand`, NOT `reconcile-source`. Neither declared output is a generated
        # artifact: both are hand-authored files in which this row owns a single numeric
        # token per exact module. Classing them `reconcile-source` would tell an agent
        # never to hand-merge conflicted bytes in `lib/test/run.sh` — the repo's largest
        # hand-authored file, whose conflicts are almost never in a floor operand — and
        # send it to regenerate a file no generator produces. `by-hand` carries the
        # correct instruction for a partially-owned record: merge it deliberately, then
        # let the batch re-measure the fields it does own.
        "conflict_class": "by-hand",
        "conflict_paths": (
            "scripts/workflow-flight-recorder-registry.json",
            "lib/test/run.sh",
        ),
        # Do not clear `opt_in`: this row alone runs the real focused module runners,
        # costing minutes where every other row costs milliseconds, which would make the
        # default pass unusable as the after-every-edit reconciler it exists to be.
        "opt_in": True,
        # Preflight (issue #1244): INELIGIBLE. Two independent disqualifiers: this row
        # WRITES its declared outputs, so it can never run in a write-nothing preflight;
        # and its check runs the real focused module runners, measured at ~137 s on issue
        # #1457's host under the landed `--heavy-units smoke` bounding — three-plus orders of
        # magnitude above the eligible rows and far
        # past any pre-suite budget. The preflight skips it and the coordinator still
        # launches; the full suite remains its only detector.
        "preflight_eligible": False,
    },
    {
        "name": "env-freeze-advisory-region",
        # Bound = measured 0.044s x500 (issue #1457 AC2a).
        "timeout_seconds": 22,
        "kind": "judgment",
        "argv": ("python3", "lib/generate-env-freeze-advisory.py", "--check"),
        "clean": (0,),
        # (0, 1) deliberately, matching the plugin-identity row's reasoning: the generator
        # exits 2 for every INPUT failure (an absent/unreadable/malformed rename map, an
        # identifier row missing its failure mode, a lost or duplicated region banner), and
        # leaving 2 outside the declared set is what routes those to the infrastructure
        # state instead of a judgment item telling the agent to regenerate from a file the
        # generator could not read or a region it could not locate.
        "exits": (0, 1),
        "policy": (
            "merge lib/rename-map.json's frozen.env_identifiers block first, then rewrite "
            "the advisory region with `python3 lib/generate-env-freeze-advisory.py`"
        ),
        # regenerate: the region is a pure function of the frozen block and the generator
        # has no by-hand sibling to reconcile, so re-running the writer against the merged
        # tree IS the answer, and the policy above names a runnable WRITE command.
        "conflict_class": "regenerate",
        "conflict_paths": ("docs/internal/cloud-setup.md",),
        # The one exit-1 path that is NOT drift: an unhandled exception exits 1 under
        # CPython, aliasing an unchecked run onto the resolvable "regenerate me" state.
        # Deliberately EXCLUDED: the region-differs diff, which is the genuine finding this
        # row exists to surface — matching it would hide the drift it reports.
        "infra_markers": ("Traceback (most recent call last)",),
        # Preflight (issue #1244): `--check` is read-only and sub-second (~0.04 s).
        "preflight_eligible": True,
    },
)

# ── Coupled-site registry (issue #1206) ──────────────────────────────────────
# The question `--list` answers today is "what did a generator write?". This second
# table answers the FORWARD question a person or an automated run asks BEFORE editing:
# "I am about to edit X — what else must change with it?". A coupled site is a value,
# literal, or contract kept in more than one place by hand, where changing one place
# obliges changing the others. Some of these have a standalone checker; some have NONE
# at all and are invisible unless you happen to read the right part of a very large
# script. Recording them here — as data, printable read-only from
# `--list` — makes them findable and greppable before the edit, not one round trip later
# when the suite goes red or a reviewer rejects the change.
#
# This registry deliberately does NOT check whether the coupled files actually agree
# (issue #1206 "out of scope"): each entry keeps whatever checker it already has, or
# none. The table is a MAP, not a net.
#
# REQUIRED FIELDS per entry (enforced at import by `_validate_coupled_sites`):
#   name           — unique short id; the uniqueness rule this table enforces, and the
#                    join key of the two emitted line kinds. A duplicate name raises.
#   original       — the file that is the source/original of the coupled value.
#   partners       — a non-empty sequence of one or more files that must change with it.
#   coupling_class — a short class name saying what KIND of coupling it is.
#   note           — a one-line instruction: what an editor has to do.
# OPTIONAL FIELD:
#   holds_old_paths — bool, default False. When True this entry's PARTNERS are
#                    superseded/old paths (arguments to `git show <old-commit>:<path>`
#                    that only resolve under their old names), so the AC4 path-existence
#                    check in `emit_list` skips the partners. The marker is what exempts
#                    them — never a hardcoded path list inside the checker. The `original`
#                    is the live file an editor opens to change the coupled value, so it is
#                    always current and always checked, marker or not.
#
# EMITTED LINES (issue #1206) — printed by `emit_list` AFTER everything the command
# prints today, so a tree with no entries here leaves the existing `artifact` /
# `conflict-*` / `preflight` output byte-for-byte unchanged and every prefix-anchored
# consumer parses as before. Two tab-separated line kinds, each parseable by its own
# tab-delimited first field (`coupled-site` is a string prefix of `coupled-site-partner`,
# so split on the tab, do not prefix-match; partners are on their own lines so a path is
# individually greppable):
#   coupled-site\t<name>\t<coupling_class>\t<original>\t<note>
#   coupled-site-partner\t<name>\t<partner-path>
COUPLED_SITES = (
    {
        # AC5 — the EXTRAS copy of the tool-grant list (the note names its checker).
        "name": "matcher-probe-extras",
        "original": ".prflow/config.json",
        "partners": (".github/workflows/matcher-probe.yml",),
        "coupling_class": "allowlist-mirror",
        "note": (
            "prflow_implement.allowed_tools in .prflow/config.json is partly copied into "
            "the EXTRAS='…' line in .github/workflows/matcher-probe.yml; keep them in "
            "step. The only checker is the '#480 matcher-probe EXTRAS mirrors "
            "probe-eligible prflow_implement.allowed_tools' check in lib/test/run.sh, and "
            "it runs only as part of the full suite."
        ),
    },
    {
        # AC6 — _WSR_SWEPT_RELPATHS, which holds OLD paths by design (AC4 exemption).
        "name": "wsr-swept-relpaths",
        "original": "lib/test/run.sh",
        "partners": (
            ".devflow/prompt-extensions/implement.md",
            ".devflow/prompt-extensions/review-and-fix.md",
            ".devflow/prompt-extensions/receiving-code-review.md",
            "CLAUDE.md",
            "docs/DEVFLOW_SYSTEM_OVERVIEW.md",
            "CONTRIBUTING.md",
        ),
        "coupling_class": "frozen-old-paths",
        "holds_old_paths": True,
        "note": (
            "_WSR_SWEPT_RELPATHS in lib/test/run.sh holds `git show <old-commit>:<path>` "
            "arguments that resolve only under their OLD names, so a repo-wide rename must "
            "NOT rewrite them. The warning comment above the array stays for a reader at "
            "that spot; this entry is what makes the list findable without reading the file."
        ),
    },
    {
        # AC7 — the files coupled to lib/rename-map.json: four that read it directly, plus
        # the two workflows whose config jobs mirror a shape run.sh reconciles against it.
        "name": "rename-map-readers",
        "original": "lib/rename-map.json",
        "partners": (
            "scripts/scaffold-config.sh",
            "scripts/config-get.sh",
            "scripts/migrate-consumer-tier1.sh",
            "lib/test/pin-corpus-lint.py",
            ".github/workflows/devflow.yml",
            ".github/workflows/devflow-implement.yml",
        ),
        "coupling_class": "single-source-readers",
        "note": (
            "The first four partners open lib/rename-map.json and parse its superseded-name "
            "data at run time, so a change to the map's keys or structure must update each "
            "of them. The two workflows never open the file: their config jobs carry a "
            "hardcoded jq shape (a `^devflow(_|$)` top-level-key match) that lib/test/run.sh "
            "reconciles against the map's config_keys, so the map and that mirrored shape "
            "must move together even though the coupling runs through the suite rather than "
            "through a read. The map's own `_comment` field describes this coupling in "
            "prose and is left untouched."
        ),
    },
    {
        # AC7 — the two files that deliberately keep their OWN copy of paths.state_dir
        # instead of reading the map.
        "name": "rename-map-state-dir-mirror",
        "original": "lib/rename-map.json",
        "partners": (
            "lib/resolve-state-dir.sh",
            "lib/state_dir.py",
        ),
        "coupling_class": "deliberate-mirror",
        "note": (
            "lib/resolve-state-dir.sh and lib/state_dir.py deliberately carry their own "
            "copy of paths.state_dir instead of reading the map (a .sh cannot be sourced by "
            "the Python reader and a .py cannot be sourced into a shell); the "
            "tier1-rename-migration suite module asserts all three agree."
        ),
    },
)


def default_repo_root():
    """The repo root to operate on when `--repo-root` is absent.

    `git rev-parse --show-toplevel` first (mirroring the repo's #295 root-anchoring
    contract), falling back to the checkout containing this script when git cannot
    answer — a fixture root is commonly not a git repository at all.

    The probe runs with `cwd` anchored to THIS SCRIPT's checkout, not the process
    working directory. Unanchored, the helper invoked from inside a different
    repository would resolve that repository as its root and regenerate the manifest
    under the wrong tree — not hypothetical in a repo that runs agents from
    `.claude/worktrees/` checkouts.
    """
    here = Path(__file__).resolve().parents[2]
    try:
        out = subprocess.run(
            ("git", "rev-parse", "--show-toplevel"),
            cwd=str(here),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return here
    if out.returncode == 0 and out.stdout.strip():
        return Path(out.stdout.strip())
    return here


def _capability_region_targets(root):
    """The generated workflow literal files, read from the GENERATOR's own region list.

    Sourced rather than re-enumerated (issue #655): the five workflow paths already live
    in `lib/generate-capability-profiles.py`'s `REGIONS`, and a second copy here would be
    a coupled mirror that goes stale the day a region is added or renamed — the exact
    drift class this repo's coupled-invariant rule exists to stop.

    The generator is stdlib-only with no import side effects (it defines constants and
    functions; every file read happens inside a subcommand), so importing it is safe.
    A failure to import or to read `REGIONS` RAISES rather than returning a partial set:
    a silently short list would leave a real conflict path unmatched, and the conflict
    rule would then send the agent down its hand-merge default for a generated artifact —
    unknown collapsed onto "not a generated artifact", the fail-open this helper's whole
    exit contract is built to avoid. The top-level net routes the raise to exit 2.
    """
    path = root / "lib" / "generate-capability-profiles.py"
    spec = importlib.util.spec_from_file_location("_devflow_capgen", path)
    # Defensive, and deliberately not covered by a test arm (#659 review, Suggestion 3): this is
    # the documented `None` return of the importlib API (an unrecognized suffix / no loader for
    # the location), which a `.py` path cannot reach — an ABSENT file still yields a spec with a
    # loader and surfaces as `exec_module`'s FileNotFoundError, which is the arm `_ra_region_fails_infra`
    # actually drives. Kept rather than removed: it raises into the same exit-2 route as every
    # other arm here, so its cost is two lines and its removal would make an API contract change
    # fail open on a partial region set. There is no fixture that reaches it without mutating
    # importlib itself.
    if spec is None or spec.loader is None:
        raise RuntimeError(f"capability generator not importable: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    targets = {
        Path(region["file"]).resolve().relative_to(Path(module.REPO_ROOT).resolve()).as_posix()
        for region in module.REGIONS
    }
    if not targets:
        raise RuntimeError("capability generator declared no regions")
    return tuple(sorted(targets))


def conflict_paths(row, root):
    """The generated artifact file path(s) a merge conflict in `row` can land in.

    Two sources, both keyed on a DECLARED FIELD — never on the row's name. Keying on a name
    string is a "proxy instead of the real property": a row rename is an ordinary registry
    edit, and under a name check it would silently drop the generator-sourced workflow
    literals with no field anywhere declaring that the name was load-bearing.

    * the row's static `conflict_paths`, defaulting to the `writes` field the mechanical
      row already states, so no row restates a path the registry already carries; plus
    * `conflict_paths_extra`, an optional per-row callable taking the target root and
      returning additional paths derived at emit time. Bound below the function definitions
      because the table is defined above the function it names.
    """
    if "conflict_paths" in row:
        static = tuple(row["conflict_paths"])
    else:
        writes = row["writes"]
        static = (writes,) if isinstance(writes, str) else tuple(writes)
    extra = row.get("conflict_paths_extra")
    return static + (tuple(extra(root)) if extra else ())


def _marker_hit(markers, output):
    """The first marker contained in some single output line, else None.

    Scoped per LINE rather than against the concatenated blob: a marker must appear
    within one emitted diagnostic, so it can never be assembled across a line break
    from two unrelated messages.

    Deliberately NOT anchored to the line start. The markers are not uniformly
    line-leading — the capability row's `manifest unreadable:` and `manifest malformed
    JSON:` appear mid-line in a diagnostic such as `capability profiles: <path>: manifest
    unreadable: …`, while the coverage-map guard's `[arm4] …` and `[input-error]` are
    line-leading. A startswith() rule would silently stop matching every mid-line marker a
    row declares and reopen exactly the fail-open this discriminator exists to close, so
    the residual risk (a marker quoted inside a longer diagnostic on one line) is accepted
    rather than traded for a worse one.
    """
    return next(
        (m for m in markers if any(m in line for line in output.splitlines())),
        None,
    )


def _emit_progress(message):
    """Emit one attributed progress line to STDERR (issue #1457 AC1).

    Progress is a separate stream from the accumulated `report`, which keeps its existing
    stdout `finally` flush byte-for-byte, so the report text's existing consumers are
    unchanged. `flush=True` so a live caller sees a row's start before that row finishes.
    """
    print(message, file=sys.stderr, flush=True)


def _restore_default_signals():
    """Restore the suite signals to their default disposition in a forked child (POSIX).

    The profile-suite.py pattern (issue #1457): used as a `preexec_fn` so a backgrounded
    launch's child can still be signalled/terminated. Runs only on POSIX, where `preexec_fn`
    is supported.
    """
    for _name in ("SIGHUP", "SIGINT", "SIGQUIT", "SIGTERM"):
        _sig = getattr(signal, _name, None)
        if _sig is not None:
            signal.signal(_sig, signal.SIG_DFL)


class _BoundedResult:
    """A subprocess.run-shaped result plus timeout/elapsed, so run_row's downstream
    classification reads `.returncode`/`.stdout`/`.stderr` exactly as before (issue #1457)."""

    __slots__ = ("returncode", "stdout", "stderr", "timed_out", "elapsed")

    def __init__(self, returncode, stdout, stderr, timed_out, elapsed):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out
        self.elapsed = elapsed


def _terminate_tree(proc):
    """Kill the child and, on POSIX, its whole process group (issue #1457 AC6).

    A bare `subprocess.run(timeout=)` kills only the direct child and orphans grandchildren
    (exact-module-floors spawns python3 -> bash run-module.sh -> …). The child leads its own
    session (`start_new_session`), so signalling its process group reaches the whole tree.
    """
    if _POSIX:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            # Group already gone or unavailable — fall back to the direct child rather than
            # leaving the row un-terminated.
            pass
    try:
        proc.kill()
    except ProcessLookupError:
        pass


def _run_bounded(argv, root, timeout_seconds):
    """Run `argv` under a wall-clock bound, terminating the whole process tree on timeout.

    Returns a `_BoundedResult`. Raises OSError if the command cannot launch, exactly as
    subprocess.run does, so run_row's existing launch-failure arm still catches it. On POSIX
    the child leads its own session so a timeout signals the entire group (AC6); the guards on
    `_POSIX` keep the helper runnable on a non-POSIX host (AC8).
    """
    popen_kwargs = {}
    if _POSIX:
        popen_kwargs["start_new_session"] = True
        popen_kwargs["preexec_fn"] = _restore_default_signals
    proc = subprocess.Popen(
        argv,
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **popen_kwargs,
    )
    start = time.monotonic()
    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
        return _BoundedResult(
            proc.returncode, stdout, stderr, False, time.monotonic() - start
        )
    except subprocess.TimeoutExpired:
        _terminate_tree(proc)
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        return _BoundedResult(
            proc.returncode, stdout, stderr, True, time.monotonic() - start
        )


def run_row(row, root, report, timeout_override=None):
    """Execute one command-backed row. Returns (forces_exit_1, infrastructure)."""
    name = row["name"]
    # The script is the first non-flag argv element after the interpreter — NOT slot 1
    # positionally. A future row spelled `("python3", "-m", "pkg")` (or carrying a
    # leading flag) would resolve `root / "-m"`, which never exists, and the
    # declared-set branch below would then assert `(target absent: -m)` about a script
    # that is present — a misdirected diagnosis on an already-failing path. When no
    # script can be identified, claim no absence at all.
    target_rel = next((a for a in row["argv"][1:] if not a.startswith("-")), None)
    # Both command-backed kinds this block heads answer "did anything change?" by
    # bracketing the run with byte snapshots, never by the command's own wording. The
    # mechanical generator writes unconditionally on success, so its snapshot pair alone
    # decides the change; the monotonic reconciler additionally couples that change to an
    # announced `RAISED` marker, so a mutation without the marker is unattributable rather
    # than a successful reconciliation (see `_monotonic_outcome`).
    writes = row.get("writes", ())
    if isinstance(writes, str):
        writes = (writes,)
    written = tuple(root / path for path in writes)
    # The snapshot is an OS read, and it brackets the run OUTSIDE the try below (which
    # covers only subprocess.run). An unreadable/undeletable manifest (PermissionError,
    # IsADirectoryError — what a half-restored worktree or a root-owned fixture
    # produces) would otherwise escape as a traceback, and a traceback exits 1: the
    # infrastructure state aliased onto "action required", which is the exact
    # unknown-collapsed-onto-a-real-value class this helper exists to prevent.
    try:
        before = {
            path: path.read_bytes() if path.is_file() else None for path in written
        }
    except OSError as error:
        failed_path = getattr(error, "filename", None)
        try:
            failed_path = Path(failed_path).resolve().relative_to(root).as_posix()
        except (OSError, TypeError, ValueError):
            failed_path = "a declared output"
        report.append(
            f"[{name}] INFRASTRUCTURE could not read {failed_path} before the run "
            f"({error}) — nothing was compared and nothing was verified."
        )
        return False, True
    # The declared per-row bound, replaced wholesale by the global override when set (AC5).
    timeout_seconds = (
        timeout_override if timeout_override is not None else row["timeout_seconds"]
    )
    _emit_progress(
        f"regenerate-artifacts: row {name}: start (bound {timeout_seconds}s)"
    )
    try:
        proc = _run_bounded(row["argv"], root, timeout_seconds)
    except OSError as error:
        _emit_progress(f"regenerate-artifacts: row {name}: launch failed")
        report.append(
            f"[{name}] INFRASTRUCTURE the command failed to launch: "
            f"{' '.join(row['argv'])} ({error})"
        )
        return False, True
    # A bounded-out row established nothing, so it routes to the infrastructure state (exit 2),
    # never the exit-1 "action required" state (AC4). The report line names the row and its
    # bound and does not blame a different row.
    if proc.timed_out:
        _emit_progress(
            f"regenerate-artifacts: row {name}: TIMED OUT after {timeout_seconds}s"
        )
        report.append(
            f"[{name}] INFRASTRUCTURE `{' '.join(row['argv'])}` exceeded its declared "
            f"bound of {timeout_seconds}s and was terminated with its whole process group "
            "— nothing was compared and nothing was verified."
        )
        return False, True
    _emit_progress(
        f"regenerate-artifacts: row {name}: done "
        f"(exit {proc.returncode}, {proc.elapsed:.1f}s)"
    )
    output = (proc.stdout + proc.stderr).strip()

    # An absent script is reported by the interpreter as exit 2 with a "can't open
    # file" diagnostic rather than an OSError, so the declared-set check below is what
    # actually catches it. Naming the path here keeps that diagnosis attributable.
    declared = row["exits"]
    if proc.returncode not in declared:
        missing = (
            ""
            if target_rel is None or (root / target_rel).exists()
            else f" (target absent: {target_rel})"
        )
        report.append(
            f"[{name}] INFRASTRUCTURE `{' '.join(row['argv'])}` exited "
            f"{proc.returncode}, outside its declared set {declared}{missing}\n"
            f"    output: {output or '(none)'}"
        )
        return False, True

    if row["kind"] == "mechanical":
        try:
            path = written[0]
            after = path.read_bytes() if path.is_file() else None
        except OSError as error:
            report.append(
                f"[{name}] INFRASTRUCTURE could not read {row['writes']} after the run "
                f"({error}) — the change comparison never happened."
            )
            return False, True
        return _mechanical_outcome(
            row, proc, output, before[path] != after, after, report
        )

    if row["kind"] == "monotonic":
        try:
            after = {
                path: path.read_bytes() if path.is_file() else None for path in written
            }
        except OSError as error:
            report.append(
                f"[{name}] INFRASTRUCTURE could not read its declared writes after the run "
                f"({error}) — the change comparison never happened."
            )
            return False, True
        return _monotonic_outcome(row, proc, output, before, after, report)

    if proc.returncode in row["clean"]:
        report.append(
            f"[{name}] clean — `{' '.join(row['argv'])}` exited {proc.returncode}"
        )
        return False, False
    hit = _marker_hit(row.get("infra_markers", ()), output)
    if hit is not None:
        report.append(
            f"[{name}] INFRASTRUCTURE `{' '.join(row['argv'])}` exited "
            f"{proc.returncode} reporting an input failure, not drift "
            f"(matched {hit!r}) — the artifact was NOT checked:\n"
            f"    output: {output or '(none)'}"
        )
        return False, True
    report.append(
        f"[{name}] JUDGMENT `{' '.join(row['argv'])}` exited {proc.returncode}\n"
        f"    output: {output or '(none)'}\n"
        f"    governing policy: {row['policy']}"
    )
    return True, False


def _mechanical_outcome(row, proc, output, changed, after, report):
    """Classify the mechanical row's outcome. Returns (forces_exit_1, infrastructure)."""
    name = row["name"]
    if proc.returncode in row["clean"]:
        if after is None:
            report.append(
                f"[{name}] INFRASTRUCTURE `{' '.join(row['argv'])}` exited 0 but "
                f"{row['writes']} is absent — the generator produced no artifact, so "
                "there is nothing to compare and nothing was verified."
            )
            return False, True
        if not changed:
            report.append(f"[{name}] clean — {row['writes']} already matches the closure")
            return False, False
        report.append(
            f"[{name}] REGENERATED {row['writes']} changed — commit it with your edits."
        )
        return True, False

    # Exit 1. `check_closure()` runs before every subcommand and returns 1 with
    # `cloud-writer-contract:`-prefixed lines when a classified asset is absent, a
    # helper head is missing, and the like — exactly what a loop's rename/delete edits
    # produce. Keying on the generator's own marker is what separates that reconcilable
    # closure error from an interpreter traceback, which must not be dressed up as a
    # judgment item the agent is told to "resolve".
    if _marker_hit(("cloud-writer-contract:",), output) is not None:
        report.append(
            f"[{name}] JUDGMENT the closure is broken (exit 1):\n"
            f"{output}\n"
            f"    governing policy: {row['policy']}\n"
            "    Reconcile the closure — this is a closure error, not an "
            "infrastructure fault."
        )
        return True, False
    report.append(
        f"[{name}] INFRASTRUCTURE exited 1 with no `cloud-writer-contract:` marker "
        "(an interpreter traceback or an unhandled exception):\n"
        f"{output or '(no output)'}"
    )
    return False, True


def _monotonic_outcome(row, proc, output, before, after, report):
    """Classify a raise-only row without collapsing a refused decrease into clean."""
    name = row["name"]
    absent = [path for path, content in after.items() if content is None]
    if absent:
        report.append(
            f"[{name}] INFRASTRUCTURE the row left declared output(s) absent: "
            + ", ".join(str(path) for path in absent)
        )
        return False, True
    changed = [path for path in before if before[path] != after[path]]
    if proc.returncode in row["clean"]:
        if not changed:
            report.append(f"[{name}] clean — every measured tally matches both floors")
            return False, False
        relative = [path.name if path.name == "run.sh" else path.as_posix() for path in changed]
        # A raise-only row's outputs are COUPLED sites that must move together, so a
        # write it did not announce is unattributable: the reconciler prints its own
        # `RAISED` marker naming the modules it staged, and only that marker
        # establishes the change as the reconciliation rather than incidental
        # corruption. Without it, a clean exit code plus a mutated file would be
        # reported as a successful reconciliation and committed — the coupled floors
        # left disagreeing while the batch claims it resolved them.
        if "floor-reconciliation: RAISED" not in output:
            if len(changed) < len(before):
                report.append(
                    f"[{name}] INFRASTRUCTURE the reconciliation exited "
                    f"{proc.returncode} but changed only a subset of its declared "
                    f"outputs ({', '.join(relative)}) and announced no raise — the "
                    "coupled floors cannot be assumed consistent"
                )
            else:
                report.append(
                    f"[{name}] INFRASTRUCTURE the reconciliation exited "
                    f"{proc.returncode} and changed {', '.join(relative)} without "
                    "announcing a raise — the change is unattributable"
                )
            return False, True
        report.append(
            f"[{name}] RECONCILED measured floor raise changed: {', '.join(relative)}"
        )
        return True, False
    if changed:
        # Name the paths AND the reconciler's own output: this arm fires on the most
        # alarming state the classifier models — a row that declares a refusal contract
        # yet mutated files under source control — and the operator needs to know which
        # coupled site is now inconsistent before committing anything.
        relative = [path.name if path.name == "run.sh" else path.as_posix() for path in changed]
        report.append(
            f"[{name}] INFRASTRUCTURE a non-clean reconciliation (exit "
            f"{proc.returncode}) changed declared outputs despite its refusal "
            f"contract: {', '.join(relative)}\n    output: {output or '(none)'}"
        )
        return False, True
    if "floor-reconciliation: DECREASE REFUSED" in output:
        report.append(
            f"[{name}] JUDGMENT {output}\n    governing policy: {row['policy']}"
        )
        return True, False
    report.append(
        f"[{name}] INFRASTRUCTURE the reconciler exited {proc.returncode} without a "
        f"recognized non-writing refusal marker:\n{output or '(no output)'}"
    )
    return False, True


def run_preflight_row(row, root, report):
    """Run ONE eligible row read-only for the preflight. Returns (drift, uncheckable).

    Distinct from `run_row` in two load-bearing ways (issue #1244):
      * it takes NO byte snapshots and runs only the row's `preflight_argv` (defaulting to
        the row's own `argv` when the row's check is already non-writing), so a preflight
        can never be blamed for a write — the coordinator's fail-closed refusal must never
        rest on a check that itself mutated the tree; and
      * a non-clean-but-in-set exit is DRIFT only when it is positively attributable. For a
        row carrying `preflight_positive_marker` (the cloud-writer row, whose read-only
        `verify` prints that marker on a stale/broken closure), an unmarked exit-1 is a
        crash, classified UNCHECKABLE. For a judgment row, the row's own `infra_markers`
        route an input failure to UNCHECKABLE, exactly as the batched pass does; anything
        else is drift.
    """
    name = row["name"]
    argv = row.get("preflight_argv", row["argv"])
    joined = " ".join(argv)
    target_rel = next((a for a in argv[1:] if not a.startswith("-")), None)
    try:
        proc = subprocess.run(
            argv, cwd=str(root), capture_output=True, text=True, check=False
        )
    except OSError as error:
        report.append(f"[{name}] UNCHECKABLE the preflight command failed to launch: {joined} ({error})")
        return False, True
    output = (proc.stdout + proc.stderr).strip()
    declared = row["exits"]
    if proc.returncode not in declared:
        missing = (
            ""
            if target_rel is None or (root / target_rel).exists()
            else f" (target absent: {target_rel})"
        )
        report.append(
            f"[{name}] UNCHECKABLE `{joined}` exited {proc.returncode}, outside its "
            f"declared set {declared}{missing}\n    output: {output or '(none)'}"
        )
        return False, True
    if proc.returncode in row["clean"]:
        report.append(f"[{name}] clean — `{joined}` exited {proc.returncode}")
        return False, False
    marker = row.get("preflight_positive_marker")
    if marker is not None:
        if _marker_hit((marker,), output) is not None:
            report.append(
                f"[{name}] DRIFT `{joined}` exited {proc.returncode} — regenerate needed:\n"
                f"    output: {output or '(none)'}\n"
                f"    governing policy: {row['policy']}"
            )
            return True, False
        report.append(
            f"[{name}] UNCHECKABLE `{joined}` exited {proc.returncode} without its drift "
            f"marker {marker!r} (a crash, not a reconcilable drift):\n"
            f"    output: {output or '(none)'}"
        )
        return False, True
    # A crash (an uncaught traceback) is never a reconcilable drift. The preflight fails
    # OPEN on any unusable check (issue #1244 / AC5 — "a crash warns and proceeds"), so a
    # traceback routes to UNCHECKABLE for EVERY judgment row regardless of that row's own
    # `infra_markers` — which are tuned for the BATCHED pass, where two judgment rows
    # (`capability-profile-literals`, `coverage-map-ratchet`) deliberately omit the traceback
    # marker because there an unmarked exit-1 is a reportable JUDGMENT item, not a suite
    # block. Here it would instead fail CLOSED and block the whole suite with a misleading
    # "regenerate" message, so the universal traceback marker is added to the preflight's
    # classification only. This is preflight-local: `run_row` (the batched pass) is unchanged.
    hit = _marker_hit(
        row.get("infra_markers", ()) + ("Traceback (most recent call last)",), output
    )
    if hit is not None:
        report.append(
            f"[{name}] UNCHECKABLE `{joined}` exited {proc.returncode} reporting a crash or "
            f"input failure, not drift (matched {hit!r}):\n    output: {output or '(none)'}"
        )
        return False, True
    report.append(
        f"[{name}] DRIFT `{joined}` exited {proc.returncode}\n"
        f"    output: {output or '(none)'}\n"
        f"    governing policy: {row['policy']}"
    )
    return True, False


def run_preflight(root):
    """Read-only preflight over the eligible rows only (issue #1244).

    Writes nothing, prints one line per row it ran, then a machine verdict line
    (`PREFLIGHT_VERDICT_PREFIX` + one of `clean` / `drift` / `uncheckable`) followed by
    the human remedy sentence, and exits:
      0 — every eligible row is clean;
      1 — at least one eligible row DRIFTED (a positively-attributed, reconcilable drift);
      2 — no drift, but at least one eligible row could not be checked.
    The verdict line is the contract `lib/test/run-parallel.sh` reads; the sentence beside
    it is for a human and carries no consumer.
    DRIFT takes precedence over UNCHECKABLE: a positively-detected drift must fail closed
    (the coordinator refuses to launch) and must never be masked by an unrelated row that
    happened to be uncheckable. Exit 2 is therefore the purely-unestablished case, which
    the coordinator treats as fail-open (warn and proceed). This precedence is the reverse
    of the batched pass's infra-over-drift ordering, deliberately: the batched pass writes
    and its exit 2 means "nothing was reconciled", whereas the preflight's exit 1 is a
    refusal signal that a caught drift must dominate.
    """
    report = []
    drift = False
    uncheckable = False
    for row in ROWS:
        if not row.get("preflight_eligible"):
            continue
        # A row's classification must never abort the whole preflight: an unexpected raise
        # AFTER an earlier row already set drift would otherwise propagate to the top-level
        # net, exit 2 with no report and no drift summary, and the coordinator would then
        # fail OPEN — losing a positively-detected drift (the fail-closed contract this
        # function documents). Catch per row → that row is UNCHECKABLE, the loop continues,
        # and any already-detected drift survives the drift-precedence check below.
        try:
            row_drift, row_uncheckable = run_preflight_row(row, root, report)
        except Exception as error:  # noqa: BLE001 — defensive per-row net, mirrors main()'s
            report.append(
                f"[{row['name']}] UNCHECKABLE the preflight row raised "
                f"{type(error).__name__}: {error} — nothing was established for it"
            )
            row_drift, row_uncheckable = False, True
        drift = row_drift or drift
        uncheckable = row_uncheckable or uncheckable
    for line in report:
        print(line)
    if drift:
        print(f"{PREFLIGHT_VERDICT_PREFIX}drift")
        print(
            "regenerate-artifacts: preflight detected drift — regenerate the artifact(s) "
            "above under their governing policy and commit before the suite run — exit 1"
        )
        return 1
    if uncheckable:
        print(f"{PREFLIGHT_VERDICT_PREFIX}uncheckable")
        print(
            "regenerate-artifacts: preflight could not check at least one eligible "
            "artifact — exit 2"
        )
        return 2
    print(f"{PREFLIGHT_VERDICT_PREFIX}clean")
    print("regenerate-artifacts: preflight — every eligible artifact reconciled — exit 0")
    return 0


# The capability row's extra paths come from the capability generator's own REGIONS. Bound
# here rather than in the table (which is defined above the function it names), and as a
# FIELD, so `conflict_paths` never keys on a row name.
for _row in ROWS:
    if _row.get("conflict_paths_extra", "unset") is None:
        _row["conflict_paths_extra"] = _capability_region_targets


def _validate_registry():
    """Fail closed on a misregistered conflict class, recipe, or path source (issue #655).

    Run at import (below), so every entry path — main, --list, an importing test — hits it
    and a row that cannot be classified never reaches `--list` to emit an unknown class a
    consumer would have no route for.

    Import-time strictness is kept, but the raise is ROUTED to the exit-2 infrastructure
    state for a script run (see the module-level call below). A bare module-level raise
    would exit **1** — the resolvable "action required" code — because the module body runs
    before the `if __name__ == "__main__"` net at the bottom of this file can catch
    anything. That aliases an unchecked run onto a resolvable one, the precise
    discrimination this module's EXIT CONTRACT says the net exists to preserve.
    """
    for row in ROWS:
        if row.get("kind") not in ROW_KINDS:
            raise ValueError(
                f"registry row {row['name']!r} declares kind "
                f"{row.get('kind')!r}, which is outside {ROW_KINDS}"
            )
        # `run_row` narrows a mechanical row to `written[0]`, so a second declared output
        # would never be compared and the row would report clean while that file drifted.
        # The kind's single-output assumption is enforced here rather than left implicit.
        if row["kind"] == "mechanical":
            # Normalize exactly as run_row does: `writes` is a bare string on this row,
            # so a plain `tuple()` would split it per character.
            declared = row.get("writes", ())
            declared = (declared,) if isinstance(declared, str) else tuple(declared)
            if len(declared) != 1:
                raise ValueError(
                    f"registry row {row['name']!r} is kind 'mechanical' but declares "
                    f"{len(declared)} writes; the mechanical outcome classifier "
                    "compares exactly one output"
                )
        if row.get("conflict_class") not in CONFLICT_CLASSES:
            raise ValueError(
                f"registry row {row['name']!r} declares conflict_class "
                f"{row.get('conflict_class')!r}, which is outside {CONFLICT_CLASSES}"
            )
        if not (row.get("policy") or "").strip():
            raise ValueError(f"registry row {row['name']!r} declares an empty recipe (policy)")
        # Preflight eligibility is DECLARED DATA (issue #1244), so every row must state a
        # boolean — an absent or non-boolean field is a registry defect, never a silent
        # "assume eligible" (which could run a writing row inside the write-nothing
        # preflight) or a silent "assume ineligible" (which would drop a cheap detector).
        # `opt_in` is optional and defaults to False, but a PRESENT value must be a real
        # bool: a truthy string would silently opt a row out of the default pass with no
        # flag able to opt it back in.
        if "opt_in" in row and not isinstance(row["opt_in"], bool):
            raise ValueError(
                f"registry row {row['name']!r} declares opt_in {row['opt_in']!r}, "
                "which is not a bool"
            )
        if not isinstance(row.get("preflight_eligible"), bool):
            raise ValueError(
                f"registry row {row['name']!r} declares preflight_eligible "
                f"{row.get('preflight_eligible')!r}, which is not a bool"
            )
        # The per-row wall-clock bound is DECLARED DATA (issue #1457), so a row must state
        # an int — an absent or non-int value is a registry defect, never a silent default that
        # could leave a hung row unbounded. `bool` is a subclass of `int`, so exclude it: a
        # `True` bound is a mis-typed field, not a 1-second timeout.
        bound = row.get("timeout_seconds")
        if not isinstance(bound, int) or isinstance(bound, bool):
            raise ValueError(
                f"registry row {row['name']!r} declares timeout_seconds "
                f"{bound!r}, which is not an int"
            )
        # Enforce the "preflight writes nothing" invariant in DATA, not prose (issue #1244).
        # The coordinator's fail-closed refusal rests on the preflight being read-only, so a
        # row that is eligible AND declares `writes` (its own `argv` mutates that output) must
        # supply a non-writing `preflight_argv` — otherwise the read-only preflight would run
        # the writing command. A row with no `writes` field declares no mutation, so its `argv`
        # is the read-only check the preflight runs directly. Without this, a future eligible
        # writing row that forgot `preflight_argv` would silently mutate the tree during the
        # "read-only" preflight and no guard would catch it.
        if row["preflight_eligible"] and row.get("writes") and "preflight_argv" not in row:
            raise ValueError(
                f"registry row {row['name']!r} is preflight_eligible and declares writes "
                f"{row.get('writes')!r} but no non-writing preflight_argv; an eligible writing "
                "row must name a read-only preflight command"
            )
        # A row must declare SOME static path source, checked at this same import-time point
        # rather than left to KeyError inside emit_list: a row that reaches `--list` before
        # failing has already been handed to a consumer.
        # Membership is not enough: `"conflict_paths": ()` satisfies `in` and short-circuits the
        # writes fallback, so the row resolves to NO path and the shipped rule routes its
        # artifact to the hand-merge default — the fail-open the rule exists to close, reached
        # through the one invariant #655 states and nothing enforced. Require a non-empty source.
        if "conflict_paths" in row:
            if not tuple(row["conflict_paths"]):
                raise ValueError(
                    f"registry row {row['name']!r} declares an empty conflict_paths; "
                    "a row must resolve to at least one conflict path"
                )
        elif "writes" not in row:
            raise ValueError(
                f"registry row {row['name']!r} declares no conflict-path source "
                "(needs one of conflict_paths / writes)"
            )


_COUPLED_SITE_REQUIRED_STR_FIELDS = ("name", "original", "coupling_class", "note")


def _validate_coupled_sites(sites=None):
    """Fail closed on a malformed coupled-site entry (issue #1206).

    Run at import (below) alongside `_validate_registry`, so every entry path — main,
    `--list`, an importing test — hits it and a malformed entry never reaches `--list`.
    An importing caller sees the raw ValueError (a test asserts the exception itself);
    a script run routes the same failure to the exit-2 infrastructure state via the
    shared import-time try below — never a shortened list called success.

    The default `None` reads the module table; a test passes an explicit `sites` to
    exercise a crafted bad table without editing the shipped one.
    """
    if sites is None:
        sites = COUPLED_SITES
    seen_names = set()
    for index, entry in enumerate(sites):
        # The entry must be a MAPPING before any field lookup: a bare string, tuple, or
        # None would raise AttributeError/TypeError out of `.get` below, and the
        # import-time net catches only ValueError — so the script would exit 1 with a
        # traceback instead of the documented exit-2 INFRASTRUCTURE routing. The index
        # names the offending row, which has no `name` to be reported by.
        if not isinstance(entry, dict):
            raise ValueError(
                f"coupled-site entry at index {index} must be a dict, got {entry!r}"
            )
        name = entry.get("name")
        # Every required string field must be a present, non-empty string, so a row that
        # silently omits the original, class, or note can never reach `--list`.
        for field in _COUPLED_SITE_REQUIRED_STR_FIELDS:
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"coupled-site entry {name!r} field {field!r} must be a non-empty "
                    f"string, got {value!r}"
                )
        # An entry must couple at least one PARTNER file — a coupled site with no partner
        # records no coupling and would print a `coupled-site` header with nothing to
        # change alongside it.
        partners = entry.get("partners")
        if not isinstance(partners, (list, tuple)) or not partners:
            raise ValueError(
                f"coupled-site entry {name!r} must list one or more partner files, "
                f"got partners={partners!r}"
            )
        for partner in partners:
            if not isinstance(partner, str) or not partner.strip():
                raise ValueError(
                    f"coupled-site entry {name!r} declares a partner that is not a "
                    f"non-empty string: {partner!r}"
                )
        # `holds_old_paths` is DECLARED DATA (it exempts an entry from the AC4 path check),
        # so a present value must be a real bool — never a truthy string that silently
        # disables the existence check.
        if "holds_old_paths" in entry and not isinstance(entry["holds_old_paths"], bool):
            raise ValueError(
                f"coupled-site entry {name!r} declares holds_old_paths "
                f"{entry['holds_old_paths']!r}, which is not a bool"
            )
        # The uniqueness rule this table enforces: a name is the join key of the two
        # emitted line kinds, so a duplicate would map one partner line to two entries.
        if name in seen_names:
            raise ValueError(
                f"coupled-site entry name {name!r} is declared more than once; names "
                "must be unique"
            )
        seen_names.add(name)


def _coupled_site_path_failures(sites, root):
    """List of (name, path) an entry names that does not exist under `root` (issue #1206).

    Confirms every path an entry names exists in the tracked tree (AC4). A pure
    filesystem stat — no subprocess — because `--list` "runs nothing" (its own `--help`
    contract). `is_file()`, not `exists()`, because every coupled site is a file: a
    directory or dangling symlink at the path is not a resolved coupled site.

    `holds_old_paths` exempts only the PARTNERS: they are the superseded paths that
    resolve solely under their old names, and the marker is what exempts them (never a
    hardcoded path list in the checker). The `original` is the live file an editor opens
    to change the coupled value, so it is always current and always checked — a marker
    scoped to the old partner paths must not silently stop guarding the current source
    file the entry points at.
    """
    failures = []
    for entry in sites:
        paths = (
            (entry["original"],)
            if entry.get("holds_old_paths")
            else (entry["original"], *entry["partners"])
        )
        for path in paths:
            if not (root / path).is_file():
                failures.append((entry["name"], path))
    return failures


# Validate at import — but route a script run's failure to exit 2 (INFRASTRUCTURE), never the
# exit 1 a bare module-level raise would produce. An IMPORTING caller still gets the raw
# ValueError, so a test can assert the exception itself.
try:
    _validate_registry()
    _validate_coupled_sites()
except ValueError as _bind_error:
    if __name__ != "__main__":
        raise
    print(
        f"regenerate-artifacts: INFRASTRUCTURE — registry validation failed: {_bind_error} "
        "— nothing was checked — exit 2",
        file=sys.stderr,
    )
    raise SystemExit(2) from None


def emit_list(root):
    for row in ROWS:
        command = " ".join(row["argv"])
        print(f"artifact\t{row['name']}\t{row['kind']}\t{command}")
    # The conflict-oracle lines (issue #655), emitted AFTER the artifact lines above so
    # that format stays byte-unchanged and every existing prefix-anchored consumer
    # (`artifact\tNAME\t`) parses exactly as before.
    #
    # A conflict rule matches a conflicted path against `conflict-path` and
    # `conflict-sibling`, then reads that row's `conflict-class` and `conflict-recipe`.
    # The recipe is the row's `policy` verbatim — the SAME field the batched pass prints
    # as `governing policy:` — so the two consumers structurally cannot drift.
    #
    # A coupled by-hand sibling is a file the row's gate READS but never writes, and which
    # is not a registry row of its own (it has no independent check, so it fails the
    # registry's inclusion criterion). The oracle must still name it, or a conflict in it
    # matches nothing and takes the hand-merge default.
    #
    # One pass over ROWS rather than one pass per line kind: every consumer lookup is
    # prefix-anchored (`conflict-path\t<row>\t…`), so nothing depends on the kinds being
    # grouped, and a single loop keeps "what one row emits" readable in one place.
    # No path may be claimed by two rows: the conflict rule reads the matched path's class, so a
    # duplicate would yield two contradictory classes with no stated tiebreak. Resolution is
    # root-dependent (the capability row derives its workflow literals), so this cannot move to the
    # import-time bind loop; it raises here and the top-level net routes it to the exit-2
    # infrastructure state — never a listing a consumer could act on.
    # Siblings join the SAME uniqueness namespace as conflict paths (#659 review, Suggestion 1):
    # the shipped rule matches a conflicted path against the `conflict-path` AND
    # `conflict-sibling` lines together, and the two line kinds carry DIFFERENT classes (a
    # sibling's class is its own fourth field, never the owning row's). A path emitted as both
    # would therefore hand the rule two contradictory classes with no stated tiebreak — the same
    # fail-open a two-row duplicate is, one line kind over. Deduping only within the path set
    # leaves exactly that gap unguarded.
    _seen_paths = {}
    for row in ROWS:
        for path in conflict_paths(row, root):
            if path in _seen_paths:
                raise ValueError(
                    f"conflict path {path!r} is claimed by both {_seen_paths[path]!r} and "
                    f"{row['name']!r}; a path must resolve to exactly one conflict class"
                )
            _seen_paths[path] = row["name"]
    for row in ROWS:
        for path, _sibling_class in row.get("coupled_by_hand", ()):
            if path in _seen_paths:
                raise ValueError(
                    f"conflict path {path!r} is claimed by both {_seen_paths[path]!r} and "
                    f"{row['name']!r} (as a coupled by-hand sibling); a path must resolve to "
                    "exactly one conflict class"
                )
            _seen_paths[path] = row["name"]
    for row in ROWS:
        print(f"conflict-class\t{row['name']}\t{row['conflict_class']}")
        for path in conflict_paths(row, root):
            print(f"conflict-path\t{row['name']}\t{path}")
        print(f"conflict-recipe\t{row['name']}\t{row['policy']}")
        for path, sibling_class in row.get("coupled_by_hand", ()):
            print(f"conflict-sibling\t{row['name']}\t{path}\t{sibling_class}")
    # Preflight eligibility (issue #1244), emitted LAST so every existing prefix-anchored
    # consumer (`artifact\t…`, `conflict-…\t…`) parses byte-unchanged. Each line names the
    # read-only command the preflight would run (the row's `preflight_argv`, defaulting to
    # its `argv`), so the eligibility declaration and the command are auditable together.
    for row in ROWS:
        eligible = "eligible" if row.get("preflight_eligible") else "ineligible"
        command = " ".join(row.get("preflight_argv", row["argv"]))
        print(f"preflight\t{row['name']}\t{eligible}\t{command}")
    # Coupled-site registry (issue #1206), emitted LAST so every existing prefix-anchored
    # consumer (`artifact\t…`, `conflict-…\t…`, `preflight\t…`) parses byte-unchanged and a
    # tree with an empty COUPLED_SITES leaves the output above untouched.
    #
    # AC4 path-existence check runs HERE, when the list is printed, because existence is
    # root-dependent (a fixture root differs from the live tree). A named path that does
    # not exist is a LOUD failure naming both the entry and the path — never quietly
    # dropped: the raise routes to the exit-2 infrastructure state via the top-level net,
    # exactly like emit_list's existing duplicate-path raise. The check is collected across
    # ALL entries first so the message can name every offender, and it fires BEFORE any
    # coupled-site line is printed so a consumer never sees a partial list.
    path_failures = _coupled_site_path_failures(COUPLED_SITES, root)
    if path_failures:
        detail = "; ".join(f"{name!r} names missing path {path!r}" for name, path in path_failures)
        raise ValueError(
            f"coupled-site entr{'y' if len(path_failures) == 1 else 'ies'} name a path "
            f"absent from the tree under {root!r}: {detail}"
        )
    for entry in COUPLED_SITES:
        print(
            f"coupled-site\t{entry['name']}\t{entry['coupling_class']}\t"
            f"{entry['original']}\t{entry['note']}"
        )
        for partner in entry["partners"]:
            print(f"coupled-site-partner\t{entry['name']}\t{partner}")
    return 0


def _row_timeout_override():
    """Resolve the global row-bound override (issue #1457 AC5).

    Returns None when unset or empty (empty behaves as unset, this repo's `DEVFLOW_*` rule),
    a positive int when set to one, and raises ValueError on a malformed value so main()
    refuses it loudly rather than silently ignoring it and running unbounded.
    """
    raw = os.environ.get(ROW_TIMEOUT_OVERRIDE_ENV)
    if raw is None or raw.strip() == "":
        return None
    text = raw.strip()
    try:
        value = int(text)
    except ValueError:
        raise ValueError(
            f"{ROW_TIMEOUT_OVERRIDE_ENV}={raw!r} is not an integer; unset it or set a "
            "positive whole number of seconds"
        ) from None
    if value <= 0:
        raise ValueError(
            f"{ROW_TIMEOUT_OVERRIDE_ENV}={raw!r} is not a positive integer; unset it or set "
            "a positive whole number of seconds"
        )
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Run one batched pass over the suite-owned generated artifacts: regenerate "
            "the mechanical row, check every judgment row, and report all judgment "
            "items together. Opt-in rows (today: exact-module-floors) are reported as "
            "not measured unless --with-floors is given."
        )
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help=(
            "Root to operate on. Defaults to `git rev-parse --show-toplevel`, falling "
            "back to the checkout containing this script."
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print the registered artifacts; run no row.",
    )
    parser.add_argument(
        "--with-floors",
        action="store_true",
        help=(
            "Also run the opt-in exact-module-floors row, which measures the real "
            "focused module runners and costs minutes. Omitted by default; the default "
            "pass prints one line saying the row was not measured. Run it once "
            "immediately before the completion-gate whole-suite pass."
        ),
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help=(
            "Read-only preflight: run only the preflight-eligible rows, write nothing, "
            "and exit 0 (all clean) / 1 (drift) / 2 (a row could not be checked)."
        ),
    )
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve() if args.repo_root else default_repo_root()

    if args.list:
        return emit_list(root)

    if args.preflight:
        return run_preflight(root)

    # Resolve the global override once, before the row loop, so a malformed value is refused
    # loudly here rather than silently ignored (issue #1457 AC5). Exit 2 (infrastructure):
    # nothing was checked.
    try:
        timeout_override = _row_timeout_override()
    except ValueError as error:
        print(f"regenerate-artifacts: INFRASTRUCTURE {error} — exit 2", file=sys.stderr)
        return 2

    report = []
    forces_one = False
    infrastructure = False

    # `report` is accumulated and flushed only after every row, so an exception in a
    # late row would discard the earlier rows' findings too — the caller would then see
    # a traceback, exit 1, and NO report lines, and the prompt guard (which keys the
    # never-checked verdict on the literal INFRASTRUCTURE plus exit 2) would fall
    # through to the exit-1 branch over an empty report. `finally` guarantees whatever
    # was established still prints; the top-level net below supplies the exit-2 state.
    try:
        for row in ROWS:
            if row.get("opt_in") and not args.with_floors:
                report.append(
                    f"[{row['name']}] not measured -- pass --with-floors to run this "
                    "row (its measurement runs the real focused module runners); until "
                    "then a floor left un-raised is unchecked here, and is caught on CI "
                    "by test_module_runner.py's equality assertion rather than in this "
                    "run."
                )
                continue
            # Never measure a tree an earlier row has already reported red. The opt-in
            # row's measurement runs the whole focused-module population against the
            # current tree, so on an already-failing pass it spends minutes producing a
            # verdict about a tree that is about to change.
            if row.get("opt_in") and (forces_one or infrastructure):
                report.append(
                    f"[{row['name']}] not measured -- an earlier row already reported "
                    "an unresolved item, so this tree is red before the measurement "
                    "starts; resolve the items above and rerun with --with-floors."
                )
                continue
            forced, infra = run_row(row, root, report, timeout_override)
            forces_one = forced or forces_one
            infrastructure = infra or infrastructure
    finally:
        for line in report:
            print(line)

    if infrastructure:
        print("regenerate-artifacts: INFRASTRUCTURE failure — exit 2")
        return 2
    if forces_one:
        print(
            "regenerate-artifacts: action required — commit any regenerated artifact "
            "and resolve each JUDGMENT item under its named policy before the suite run "
            "— exit 1"
        )
        return 1
    print("regenerate-artifacts: all artifacts reconciled — exit 0")
    return 0


if __name__ == "__main__":
    # An unhandled exception would otherwise exit 1 — the SAME code as "a judgment item
    # was printed" — so the caller could not tell an unchecked run from a resolvable
    # one. Route it to the declared infrastructure state (exit 2) with the same
    # `INFRASTRUCTURE` literal the row reports use, so a consumer keying on that token
    # sees it here too. `SystemExit` is re-raised untouched: main()'s own three states
    # pass through unchanged.
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as _error:  # noqa: BLE001 — deliberate top-level net
        traceback.print_exc()
        print(
            "regenerate-artifacts: INFRASTRUCTURE failure — unhandled "
            f"{type(_error).__name__}: {_error} — no artifact state was established "
            "— exit 2",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
