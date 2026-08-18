# Regenerate-artifacts contract module inventory

This inventory records the provenance of the focused regenerate-artifacts contract
module (issue #619). It is a navigation aid, not a second source of behavior:
`regenerate-artifacts.sh` owns the executable assertions, and the complete suite calls
the same module through `module-harness.sh`'s `devflow_run_full_suite_module` boundary.

Provenance: **new module, issue #619** — not an extraction from `lib/test/run.sh`.
The subject under test, `lib/test/regenerate-artifacts.py`, ships in the same PR, so
there is no former `run.sh` location to map back to.

## What the module covers

| Contract group | Representative assertions | Representative contract |
| --- | --- | --- |
| Clean-tree pass | A1 | a pristine fixture exits 0 with a per-row clean line for every registered row (run with `--with-floors`, so the opt-in row is included) |
| Opt-in floors row | the `#optin` arms | the default pass skips the one row whose check runs the real focused module runners, records that omission as its own report line naming the flag, and writes neither coupled floor site; under the flag the measurement is still skipped when an earlier row already reported the tree red (with a positive control that it did), and the reception extension carries no batched-pass section at all — asserted as an empty section extraction at the loader boundary |
| Mechanical row | A2, A2b, A2c | planted manifest drift regenerates and exits 1; a second run is idempotent; a closure error is an exit-1-forcing judgment item naming the closure data; a marker-less exit 1 (a traceback) routes to exit 2 instead of masquerading as a judgment item |
| Judgment rows + write scope | A3, A3b, A5d | planted capability drift is reported by one invocation, and every judgment-gated artifact (the generated workflow literals, `lib/review-profile.tokens`, `lib/test/modules/coverage-map.json`, the four baked plugin-identity regions) is byte-unchanged afterward; A3b plants drift in the identity **source** and asserts the batched pass reports it — the regression the `plugin-identity-regions` row was added for, since before it the pass exited 0 on a tree the full suite's `#927 G2` gate would turn RED; A5d drives the coverage-map ratchet's own judgment arm |
| Registry surface | A4 | `--list` names every registered artifact |
| Exact module floors | issue-1055 integration + issue-1498 monotonic-class arms + `test_reconcile_module_floors.py` | registry metadata selects the exact-tally population; real focused-run summaries can raise the selected registry `minimum_assertions` and matching `run.sh` operand together, while decreases and untrustworthy runs leave those operands unchanged. The issue-1498 arms drive the `exact-module-floors` row's remaining `_monotonic_outcome` classes by their own distinguishing text — a declared output left absent, a mutation despite the refusal contract, and an absent non-writing refusal marker (each exit 2), plus the clean class's own `clean — every measured tally matches both floors` text (exit 0) — each via a planted stand-in reconciler over the stub floor runner rather than eleven real module runs; the focused Python test additionally proves the measurements run through a bounded worker pool whose width honours `DEVFLOW_SUITE_PROCESS_BUDGET` and ignores a non-positive or non-numeric one, that every unclean module is reported rather than only whichever failed first, that `DEVFLOW_TEST_EXPERIMENT_FORCE_FAILURE` is scrubbed from the measurement, drives the reconciler's three `_registry_floor_span`/empty-population refusals, and pins the reconciler's `SUMMARY` contract against the real `run-module.sh` |
| Exit-code contract | A5, A5b, A5c, A5g, A5h, A5j, A5k, A5p, A5q, A5r, A5s | an absent generator (interpreter exit 2, the declared-set branch), an out-of-declared-set exit, a genuine `OSError` launch failure, and an unreadable coverage-map all reach exit 2, attributed to their row rather than only to the summary line; exit 2 takes precedence over a concurrent judgment item (asserted with a positive control that the judgment item — a coverage-map ratchet violation — was actually present, and again while the mechanical row legitimately regenerates); an unreadable artifact snapshot routes to exit 2 via run_row's snapshot-read guard, attributed by that branch's own literal (the exit code alone is not evidence — the same fixture also breaks the generator's write); a usage error exits 2 running no row, proven against planted drift. The helper's top-level exception net is **unexercised by design** — no CLI-reachable input raises past the row-level handlers — and no arm claims to cover it |
| Infra-marker discrimination | A3c, A5g, A5j, A5k, A5o | **every** judgment row's `infra_markers` are exercised by an input failure of that row's own kind — a malformed capability manifest, an unreadable coverage-map (`[arm4] `), an unreadable module registry (`[arm8] ` — A5o), the guard's `[input-error]` git arm, and a corrupted plugin-identity region banner (A3c), which the identity generator reports as exit 1 byte-identically to real drift — each asserted against its row-attributed `INFRASTRUCTURE` line and the **rendered** `matched '...'` discriminator (not the bare payload, which the generator also echoes), so a typo in a marker literal cannot ship green |
| Conflict oracle | the `#655` arms (grep the `#655 ` assertion-name prefix for the live set) | `--list` is the merge-conflict oracle: ordinary executable checks require every registered row to emit an in-set `conflict-class` and a non-empty `conflict-recipe`; verify every class assignment; cover every known generated-artifact path — including workflow literals derived from the capability generator's `REGIONS`; and require exactly one `conflict-sibling` line naming the reviewer lock. The recipe is the row's reused `policy` field, asserted to be the single source for both batched-pass `governing policy:` output and `conflict-recipe`, with a zero-count check forbidding a parallel `conflict_recipe`. Invalid classes and empty recipes fail closed at bind time with attributed breadcrumbs. One disposable copied-tool regression renames the `generate` subcommand and proves the recipe interface check goes RED. Static exact-one checks cover the three byte-identical extension rule copies and the generic pointer in each in-run conflict arm, while a zero-count check keeps the vendored `receiving-code-review` skill free of DevFlow-internal helper references |
| Root resolution | A5f | the `git rev-parse` probe is anchored to this checkout, so an invocation from an unrelated repository still resolves this checkout's root — proven via the capability row's `REGIONS`-derived conflict-path set — rather than regenerating that repository's tree |
| Helper content | header pins | the registration rule and the disclosed non-goals ship as artifact content, and the helper stays stdlib-only |
| Per-row progress + declared bound + timeout (issue #1457) | the `#1457` arms (plus the `timeout_seconds` bind arms under the `#655` fail-closed harness) | the batched pass emits an attributed start/done progress line per row on STDERR while the accumulated `report` keeps its stdout `finally` flush (AC1) and no clean-tree timeout fires (AC3); a `timeout_seconds` int is declared per registry row and validated at import exactly as `preflight_eligible` is — an absent field, a non-int, and a bool (an int subclass) each fail closed to exit 2 named by row (AC2); a bounded-out row is terminated with its whole process group (AC6, checked by the sleeper's recorded child PID, never `pgrep -f`) and its INFRASTRUCTURE report line names the timed-out row and the unrelated rows stay clean (AC4); and the `DEVFLOW_ARTIFACT_ROW_TIMEOUT_SECONDS` override drives the timeout (AC5) while a malformed value is refused loudly (exit 2 naming the var and value). The AC4/5/6 fixture stubs the fast judgment rows to trivial exit-0 scripts so the shared override bound cannot flake them and turns the env-freeze generator into a child-spawning sleeper |
| Read-only preflight (issue #1244) | AP1, AP2, AP3 | `--preflight` runs only the preflight-eligible rows read-only (writing nothing on either the clean or the drift arm), reports drift with a stable summary line and the failing row's governing policy, never touches the ineligible `exact-module-floors` row, and `--list` declares each row's eligibility — with the cloud-writer row's preflight command being the read-only `verify` form, never the writing `generate` form its own `argv` carries |
| Preflight fail-open classification (issue #1244) | AP4, AP5, AP6, AP7 | a non-clean exit becomes a refusal only when it is positively attributable: an uncheckable eligible row exits 2, a positively-detected drift outranks an uncheckable sibling, a crashing judgment row routes to UNCHECKABLE via the preflight's universal traceback marker, and — on the one row carrying a `preflight_positive_marker` — an unmarked exit-1 from its read-only `verify` is classified UNCHECKABLE rather than drift, so a `verify` crash warns and proceeds instead of blocking the suite |
| Preflight judgment-row drift and machine verdict (issue #1244) | AP8, AP9 | a judgment row's own non-crashing content drift — the primary detection path for four of the five eligible rows — is reported `DRIFT` by name with the generator's diagnostic and governing policy, exits 1, never reports uncheckable and writes nothing; a positive control proves the plant carries no infra marker and no traceback, so the judgment fall-through really is the branch under test. Each verdict also emits a machine verdict line (`clean` / `drift` / `uncheckable`), and neither a clean nor an uncheckable run emits the drift verdict |
| Preflight out-of-set exit (issue #1244) | AP11a, AP11b, AP11c | an exit outside the row's declared `exits` set — the branch checked before any clean/marker/traceback classification — routes to `UNCHECKABLE` and never to drift, writes neither the manifest nor the row's own artifact, and emits the uncheckable verdict; the coordinator therefore warns naming the inconclusive exit and launches its shard rather than refusing (the fail-open limb, contrasted with AP10a's refusal on real drift). The `(target absent: …)` sub-clause renders only when the row's preflight target is missing from the tree, and not while it is present. Positive controls establish the declared set from the fixture's own registry — never a transcribed literal — and prove each probe's exit is genuinely outside it and carries no traceback, so neither arm can be measuring a neighbouring branch |
| Preflight ↔ coordinator binding (issue #1244) | AP10a, AP10b | the parallel coordinator is driven end-to-end with **no** `DEVFLOW_ARTIFACT_PREFLIGHT` override, so the default binding to the bundled helper and the cross-file verdict contract are exercised against the real producer rather than a stub: a planted judgment-row drift makes the coordinator refuse by name, launch no shard and echo the real helper's row line, while the reconciled counterpart launches its shard, warns about nothing and exits 0 |

## Fixture discipline

Every assertion that runs a row does so against a temp fixture root — including the
clean-tree arm — never the live checkout. The fixture is a single pristine repository
image copied per assertion: the module reproduces **every tracked blob** the git index
lists (`git ls-files -s -z`, minus the three named skip arms below), file by file at its
own relative path, then `git init`s it
with a synthetic `refs/remotes/origin/main`. It is built once and copied per assertion
because the generators resolve their roots from `__file__` or an argv root, so a partial
tree would exercise the wrong closure.

**Tracked-only is the fixture rule (issue #714).** Completeness is why the module copies
the whole tracked set rather than a hand-picked subset — a subset that missed one entry
would make the pristine image itself drift and silently invalidate every "no other row
drifted" premise. What the image must *not* carry is untracked local state: the previous
builder derived top-level entry **names** from `git ls-files` but copied whole
**directories**, so because `.claude/settings.json` is tracked the entire untracked
`.claude/` tree entered the image and then every per-assertion copy. Nothing untracked
can enter now, so the `__pycache__` / `.ruff_cache` / `.prflow/tmp` prunes that
compensated for it are gone with the loop that needed them.

**Past-time snapshot (macOS, 18 cores, a checkout carrying 1.4 GB under
`.claude/worktrees`, `main` @ `607ec800`, 2026-07-21).** Pristine image 1.4 GB → ~34 MB;
this module 1240.0s → 52.5s; full `lib/test/run.sh` 1850.5s → ~663s. These are recorded
figures from one host, not re-derived on each run: the payload they measure exists only
on a developer checkout that has used `git worktree`, so a lean checkout (CI, a cloud
`/devflow:implement` run) sees no change and must not be cited as evidence either way.

File **modes are set from the index**, not inherited from the working tree, so a
`core.fileMode=false` checkout (git's default on Windows) — where the index records
`100755` while the on-disk bit is absent — builds the same image. Three skip arms are
each taken with their own distinct named stderr breadcrumb and subtracted from the
completeness denominator by name, never failing the build: two non-blob index modes — a
gitlink (`160000`) and a symlink (`120000`) — plus an ordinary blob the working tree
does not carry (tracked-then-deleted), which is a working-tree condition rather than an
index-mode one and so is triaged by its own `[ ! -f ]` guard rather than the mode
`case`. A copy failure and a mode-application failure are each counted on their own
`fail_copy` / `fail_mode` channel — a failure is never a skip, so it can never hide in
the gap between `total` and `copied`; `_ra_summary_balances` asserts that partition.
An unestablished measurement makes *both* the bash builder and the python oracle emit
an `unestablished` sentinel instead of a vacuous zero — a failed `git ls-files` in
either half, or, for the oracle alone, an image directory that is not there — and each
sentinel has a caller that drives it, as do the `fail_copy` channel (a regular file
planted where a nested entry's parent directory must go) and the `fail_mode` channel (a
`chmod` stub exiting 1, shadowed onto `PATH` for the duration of one build only, which
also reproduces the rc-127 absent-`chmod` host). The two structural skip tallies are
additionally pinned to zero against the **live** index, because builder/oracle agreement
alone would let a newly tracked symlink or submodule leave every fixture silently
incomplete while both halves agree about the omission. The symlink index-entry rows are
gated on a runtime `ln -s` capability probe: a `core.symlinks=false` checkout (Windows
without the symlink privilege) omits `link.md` from the fixture and declares the two
gated rows through `module_host_capability_skip` (issue #838; credit 2) so the host
yields a visible, accounted host-capability skip, rather than going RED over a symlink
git was never given. Unmerged
paths contribute once, not once per stage. The `#619 pristine fixture …` / `#619 fixture
builder …` assertions check all of this against an independent oracle that re-reads the
index itself, with the temp-repository arms exercised against a real git index rather
than a stubbed `git ls-files`.

**Coupled mirror:** `_ra_build_image` (bash) and `_ra_image_report` (the embedded
python3 oracle) state the same selection policy — mode triage, unmerged-stage
de-duplication, the working-tree `isfile` check — in two languages. That independence is
what makes the oracle a real check rather than a restatement of the builder's own
bookkeeping, and it is also what makes them a coupled pair: a change to the builder's
skip policy must be made in the oracle in the **same commit**, or the oracle keeps
certifying the old policy.

Each fixture-root assertion additionally asserts the **live** checkout's
`scripts/devflow-cloud-writer-contract.json` is byte-unchanged. Live-tree confinement
is asserted, never assumed from the generators' current `__file__`-based root
resolution: a future generator migrating to `git rev-parse --show-toplevel` root
resolution (the #295 direction) would break that confinement silently, and an
interrupted live-tree mutate-and-restore would leave a self-consistent corrupted
asset+manifest pair on disk that the issue-543 verify gate would then certify green.

The module uses `assert_eq` plus its own `_ra_*` domain-private helpers and the
namespaced pin API from `module-harness.sh` — it references no monolith
`lib/test/run.sh` helper. The
helper set is deliberately not enumerated here: an exact list is a mirror-fact that goes
stale on the next helper added, and the authoritative set is the `_ra_*` definitions in
the module itself.

`lib/test/regenerate-artifacts.py`, `lib/test/reconcile-module-floors.py`, and their
focused Python test sit outside `lib/test/modules/coverage-map.json`'s file-row surface:
`lib/test/` is listed in that map's `exempt_subtrees`, and
`coverage_map_guard.py`'s patterns are depth-1 (`lib/*.py`, `scripts/*.sh`, …), so a
depth-2 path under `lib/test/` is outside the ratchet surface by construction. Those
three files' coverage is this module, registered through the module-registration contract
(module file, this inventory, the flight-recorder registry row, the `lib/test/run.sh`
call-site floor, and the explicit `ci.yml` shellcheck listing).
