# Tiered suite-running — maintainer rationale relocated under issue #1352

This page holds maintainer rationale and deep mechanics relocated out of the two loaded
instruction surfaces under the issue #1352 placement audit's preserve-and-relocate rule (AC5).
The **operative** statement of the suite-running policy is single-sourced in `CLAUDE.md`, whose
Commands section carries it in one copy for every tier and every command; the prompt extensions
carry only the binding their own command adds. Nothing links here from either loaded surface;
this record is discoverable by search and by git history.

Two rounds of relocation are recorded here. The first moved deep coordinator mechanics out of
`CLAUDE.md`'s tiered bullet. The second — the placement-rule consolidation — moved the
tier-scoped operative policy *into* `CLAUDE.md` from the three prompt extensions that had been
carrying near-identical copies of it (`implement.md` 33,760 B, `review-and-fix.md` 26,875 B,
`receiving-code-review.md` 16,420 B, plus `implement.md`'s 1,972 B suite-process section), and
relocated the rationale those copies carried to the sections below. Where the three copies said
the same thing in different words, one relocated copy is recorded rather than three.

## Parallel coordinator internals (`lib/test/run-parallel.sh`, issue #1086)

The whole-suite command is the parallel coordinator `lib/test/run-parallel.sh`. It derives CI's
own shard population from `lib/test/run-shard.sh --list-shards`, runs it concurrently in this
checkout, recombines it through `lib/test/shard-tally.py`, retains every launched shard's
complete log under an ignored run root (so the caller composes no redirect of its own), and
prints one compact aggregate capped per detail class by its own `DETAIL_CAP` constant. The cloud
tiers invoke it as a direct leading token with nothing around it — it owns its own environment
assignments, redirects, background processes and aggregation precisely because the matcher
refuses those shapes caller-side (issues #401/#455), so a bare granted token is the entire
command. The local/interactive tier invokes it through the `DEVFLOW_BASH` invocation boundary,
the same boundary every other `.sh` helper is chosen by here. `lib/test/run.sh` stays the serial
primitive the `monolith` shard runs and the uncovered-surface fallback names.

Full-suite ownership flows through `scripts/verification-flight.py`. That helper requires only a
non-empty terminal-evidence object and mandates no particular field, so recording the coordinator
command identity, the compact aggregate, the exit status, the skip population and the retained-log
root in that evidence is a caller obligation this repository adopts rather than a behavior the
helper enforces — and the retained-log root is what makes a failing flight diagnosable without
relaunching, since the aggregate itself is capped per detail class.

## `monolith`-shard mid-iteration instrument (issue #1253)

Mid-iteration on a tier where the coordinator meaningfully exceeds a single shard, the `monolith`
shard may stand in for the whole suite on a `run.sh`-resident surface via
`lib/test/run-shard.sh monolith`.

**Which tiers, per issue #1253's AC1 measurement.** On the cloud implement tier the saving is real
and measured — the in-run coordinator ran ~10.5 min against ~3.9 min for `monolith` (measured
2026-08-04 in that run's own environment; the coordinator has since drifted to ~15m40s, measured 2026-08-19 in Actions run 32289799442, up from ~10m16s on 2026-08-03 in run 30857543531) — so the instrument applies there. On a local/interactive
host with cores enough to run the five shards concurrently, the whole-suite time sits near the
slowest-shard bound and the saving is small; that tier was not measurable from the cloud run, so
the shard is preferred there only where it is the actual saving, not as a default.

It is a mid-iteration instrument only, saving roughly one whole-suite launch per run given the
first-cycle-only scope of the uncovered-surface fallback case and the issue-#1252 batching rule;
it reduces neither the number of verification rounds nor the obligation to extract a durable
module on a second cycle over the same uncovered surface.

**Why the four limits are load-bearing.** `monolith` is a cheaper whole-file run and not a focused
module — it runs every inline assertion in `run.sh`, not just the changed block, so it never
substitutes where the coverage map's `focused_test` contract applies. It covers one surface only:
a change that also touches a registered module, a `scripts/`/`lib/` Python unit, or a prompt
surface is not checked by it. It never discharges a completion gate: running it leaves that gate's terms exactly as they stand, and since issue #1607 those terms are tier-scoped in `CLAUDE.md`.
And the two selectors blind the shard to their own call sites: under `DEVFLOW_SKIP_SUITE_MODULES=1`
the module-tier invocation `devflow_run_full_suite_module` no-ops, and under
`DEVFLOW_SKIP_PYTHON_POOL=1` both `devflow_python_suite_pool_open` and
`devflow_python_suite_pool_join` (including the join's reconciliation of
`test_python_scripts.py`'s self-tally) no-op — so an edit to those call sites in `run.sh` is
`run.sh`-resident yet not exercised by the shard.

## Shard decomposition at the execution ceiling (issue #1132)

The observable predicate is a coordinator (or serial-primitive) invocation the tier *terminates on
time* rather than one that runs to a verdict. On the cloud implement tier that ceiling is set at
authoring time by `devflow-implement.yml` (the Claude step's `settings` input sets
`BASH_MAX_TIMEOUT_MS`, 20 minutes as of issue #1179, above Claude Code's 600000 ms default), and
while its value is fixed by the workflow it is not escapable in-run: an agent mid-run cannot raise
its own ceiling, because `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` is set and `nohup` is ungranted.

The pre-launch preflight (`lib/test/run-parallel.sh --preflight`) is a read-only, sub-second check
nowhere near the ceiling that carries the same verdict contract the coordinator's own pre-launch
check applies (issue #1288): it launches no shard and exits 0 to proceed (clean, or a fail-open
inconclusive result) or non-zero on a positively-attributed drift, printing the drifted rows and
their governing policy. Running it first is what stops the full sharded suite being paid to
rediscover the same drift as an ordinary shard assertion failure.

Passing `--require-shards "$(lib/test/run-shard.sh --list-shards)"` to `shard-tally.py combine`
reconciles the recombination against the true partition **by name**, so a recombination that omits
a shard fails closed naming it (issue #1289) instead of printing a whole-suite-shaped green
summary — which the bare `--expect` count alone cannot catch. The recombined result is a
whole-suite result on the same terms as the coordinator's: the `#456` skip accounting is
unchanged, and a missing shard, a nonzero failure tally or a nonempty skip tally is not a
completion. Substituting a focused module for the recombined run is the downgrade this path exists
to replace.

**Why silence is ambiguous.** The preflight is fail-open on an inconclusive result exactly as the
coordinator is, so a denied preflight must never read as a pass — and silence alone does not tell
the two apart, because a clean run is silent by design and a matcher denial (the grant-timing
caveat below) is silent too. Resolving it the cheap way — treating an unreadable no-output result
as the denial and falling back to running the recombined partition — costs nothing when the tree
was in fact clean, because those shards are run on either reading, so the ambiguity never needs
deciding.

## Grant-timing caveat on the whole-suite command

`prflow_implement.allowed_tools` / `prflow.allowed_tools` are resolved by the `config` job's
trigger-time checkout of the default branch, while a prompt extension is read at runtime from the
checked-out working tree. On a PR that is itself adding a grant, the instruction naming that
command is live and the grant is not, and the invocation is silently denied. So on the cloud tier,
a whole-suite command that emits no output at all is a denial, not an empty result: fall back to a
whole-suite form whose grant is already on the default branch, and go Blocked naming
`prflow_implement.allowed_tools` as the remedy only when no such form remains.

## Diagnosing a failing full suite

When the full suite fails, read its terminal `Failure recap` (#789) from the stderr-merged capture
rather than relaunching — for the serial primitive that is the list `lib/test/run.sh` prints at the
end of a failing run, and for the coordinator it is the recap `shard-tally.py combine` renders plus
the complete shard logs under the retained-log root where the per-class detail cap elided entries.
A mid-iteration `#434` stale-prose skip on a dirty tree is expected and clears on commit — never
re-run the full suite solely to clear it, because committing is the action the skip calls for and a
fresh run is not. The exec bit is necessary but not sufficient for the leading-token retry: the
leading-token form must also be permitted on the tier.

On the cloud tier, `run-shard.sh` ends by echoing its whole captured log, which for `monolith` is
the entire assertion stream — reading the terminal recap through `| tail -<n>` is a permitted
shape, since grants are per-head and `tail` is granted.

## Wall-clock is not CI's

The coordinator's `real` time is not CI's: CI isolates each shard on its own runner, while the
coordinator's shards share one host's CPU/memory/checkout/process namespace, so its wall-clock is
the slowest shard *under contention*, not the slowest runner.

## Why the local run was once authoritative, and why it no longer is (superseded by issue #1607)

This section formerly read: *"The local run stays the authoritative local signal because its
failure detail is richer than CI's for troubleshooting."* Issue #1607 supersedes that conclusion
for the **completion gate**, and `CLAUDE.md`'s tier ladder carries the operative rule.

The richer-failure-detail premise was never wrong, and it is why a local run is still the right
instrument for *diagnosing* a failure. What it does not establish is authority, and three
measured properties settle that the other way for a gate. The local signal is **not reproducible
under this repository's concurrency** — a tree-enumerating check counts sibling worktrees, so it
varies between runs on the same commit while CI, with one checkout, cannot exhibit the effect.
It is **not the authoritative signal**, since CI gates merge and the two disagree in both
directions. And it is **slower**, sometimes exceeding the tier's foreground execution ceiling
outright. Richer detail about a result that may be an artifact of the host is not a stronger
gate; it is a better debugger.

The `#456` skip accounting is unchanged on either reading: a nonempty skip tally is not clean,
and a focused module may not self-skip (`run-module.sh` makes `skip()` fatal).

### Why the tiers must not be merged, and what the CI reading costs

Keep the two rungs distinct. The reason they differ is mechanical rather than a judgement about how
much evidence each owes: a local run can push, wait and resume, while a headless cloud run cannot
suspend and resume, so it structurally cannot wait on an external workflow. A future edit that
"simplifies" the rungs into one rule silently gives one tier a gate it cannot execute.

The reading is not free. Measured 2026-08-11, verifying by push spends Actions capacity against an account cap of 40
concurrent slots: one push costs several runs, and concurrent implement runs hold their slots for
their whole duration — which is why `CLAUDE.md` tells a run to batch into one consolidated push per
iteration rather than pushing per edit. That cost is the price of the authoritative signal; it is
not a reason to re-adopt the local one.

Measured 2026-08-19 in Actions run 32294218782: CI completed in ~7m38s with five shards on separate runners (slowest shard `python-pool` at 7m23s),
while locally those same shards contend for one host; on 2026-08-11 a local run exceeded the tier's
foreground execution ceiling outright and had to be decomposed shard-by-shard and recombined.

## Tier-2 extraction, and why a second cycle is the trigger

A surface with no covering focused test takes the full suite for its first mid-iteration cycle;
only a second mid-iteration cycle on that same uncovered surface triggers a durable module
extraction — dispatched as an Agent-tool subagent (never a nested interactive skill), written
RED-first, and registered, with its `lib/test/coverage_map_guard.py` repair running in-env on both
tiers. A one-off fix pays one full run; an iteratively-fixed surface extracts once. The
closed-set reflection bullet naming which fallback case applied is what turns a missing-module
signal into the retrospective's next extraction ticket rather than letting it vanish into a
frictionless run.

## Why the focused-selection record has a named sink

The record makes a followed rule and an ignored one leave *distinguishable* traces: a run that
consulted the coverage map records the per-surface entries, and a run that skipped straight to the
full suite records none. It adds no launch counter, no launch ordinal, and no mechanical
changed-file-to-module routing — the caller supplies the touched-surface set and nothing derives
it. The record shape is `scripts/focused_selection.py`'s (`build_record` → a machine-parseable
dict; `encode_marker` → the marker; `decode_markers` reads it back), and a mid-iteration shard run
is recorded as that surface's exemption entry with the shard named in the reason clause, adding no
field to the schema.

## Why the per-launch `Verification evidence:` record exists (issues #719, #1249)

This subsection is about a tier that *launches* a suite — the cloud implement tier, and any local
run launching one as a diagnostic. Since issue #1607 the local/interactive implement tier's gate
launches nothing at all: its recorded event is the CI reading, per `CLAUDE.md`'s local-tier bullet
under *Recording a whole-suite launch*, and the rest of this subsection does not describe it.

Because the parallelized gate launches the full run *concurrently* with the CI-triggering push —
not serialized behind it as the pre-#707 gate was — a launch that is denied, blocked, or never
reached leaves no trace, so "push, nothing to read, claim made" would otherwise be
indistinguishable from "push, ran the suite, read a clean summary, claim made". And a run that
launches the suite more than once — a first launch that fails, a second that comes back clean —
would otherwise record only the launch it happens to mention, leaving the earlier one nowhere in
the repository (issue #1249). A completion claim missing a record for a launch that ran is an
*inspectable* defect rather than an indistinguishable one.

The records are distinguished by the distinct run root the coordinator mints and prints per launch
(`run-<pid>-<n>`), so there is no launch counter and no launch ordinal to maintain: the number of
records is simply the number of launches. Issue #1252 added the launch's own start time to the
record's stated content because the reflection channel timestamps nothing and the run root carries
no clock, so without it the interval between two consecutive records is not derivable.

`note` is the required reflection kind because it is the only kind `lib/cheap-gate.jq` does not
treat as friction: a marker recorded as any other kind would flip an otherwise-clean run and make
the retrospective gate fire on exactly the runs that complied. A `note`-kind bullet under
`### ℹ️ Notes` is exempt from `reflections_friction_count`, and the gate counts friction rather
than bullets, so recording one marker per launch adds no retrospective cost.

`lib/cheap-gate.jq` remains deliberately unwired to the marker: wiring it would change retrospective
sampling for every merged PR, which is a separate decision (see that file's head comment and issue
#1249's out-of-scope note) — not, as an earlier framing had it, because the marker's population
excluded the gate's. The obligation binds every tier that maintains a workpad, cloud
`/prflow:implement` included, so a repeated or failed cloud launch is legible in the repository's
own records rather than recoverable only by downloading a run transcript by hand. This makes a
repeated or failed launch legible, not prevented — per-launch completeness is not machine-checkable,
so the review-engine advisory can only observe that at least one record is present.

## Why the owed-fix set is established rather than assumed (issue #1252)

Launching one whole-suite pass per fix is the waste the batching rule names. The set is established
by reading whichever surfaces the run recorded on — the workpad via the one-call
`scripts/workpad.py body --issue <issue>`, where exit 2 means *no workpad* and routes to
the PR-description surface while its exit 3 means *unestablished* — plus the previous pass's
`Failure recap` from its retained-log root.

A limb with nothing to read is established-and-empty, not unestablished: a run with no previous
whole-suite pass has no `Failure recap` limb to establish, and a surface that reads successfully
carrying no owed-fix record establishes an empty set. Only a limb the run tried to read and could
not is unestablished.

The rule shares the focused-first precondition's refusal to read an unestablished record as
satisfied but diverges on the remedy: that precondition binds mid-iteration only and degrades to
the full suite rather than blocking, whereas the gate arm blocks. It overrides nothing — the
existing relaunch rules stand, and `scripts/verification-flight.py`'s single flight correctly does
*not* suppress a post-edit relaunch, because the checkout has drifted and the second launch is a
legitimately new flight. Batching governs *when* a launch is paid for, never *what* it must report.
A fix that cannot be batched, because a later fix depends on the earlier one's verified result, is
launched separately and the reason recorded on the recording surface.

## Stopping a suite process — why pattern sweeps are banned

This checkout's working mode is sibling git worktrees under `.claude/worktrees/` — dozens of them,
each able to be running its own full or sharded suite at the same time, under the same command
names. A `pgrep -f` / `pkill -f` over `lib/test/run.sh`, `lib/test/run-parallel.sh`,
`lib/test/run-shard.sh` or `lib/test/run-module.sh` therefore matches other branches' live runs,
and nothing in the matched output attributes a PID to a checkout.

The coordinator already records its own PID: it allocates its run root as
`.prflow/tmp/parallel-suite/run-$$-<n>` and prints that path, so the run root's directory name
encodes the coordinator's PID. Shard PIDs are held only in the coordinator's in-memory `RUNNING`
list and are not written to disk; each shard is its own process-group leader and the coordinator's
signal traps tear them all down (forwarding a group-kill, `-$pid`, to each shard's process group on
teardown), so terminating the coordinator you recorded is the whole remedy — no follow-up sweep is
needed, and one is never authorized.

A run root is retained after its run exits and PIDs are recycled, so a run-root name identifies a
*run*, not necessarily a live process of that run. The `ps -o ppid=,lstart=,etime= -p <pid>`
cross-check is what makes the PID attributable; without it you are back to guessing, and if the
cross-check does not resolve the process is left alone.

## Why a backgrounded launch needs `lib/test/launch-detached.py` (issue #1216)

When the suite is launched from a wrapper that backgrounds it (a `subprocess.run(...)` shim, a
`cmd &` from a job-control-off shell), the child inherits an ignored SIGINT that the suite's
signal-trap assertions cannot handle — they fail, or the launch-window case hangs — and a child
left in the launcher's process group is torn down by the group's own signals mid-run. The launcher
restores SIGHUP/SIGINT/SIGQUIT/SIGTERM to their default disposition in the child, places it in a
new session, and reports the child's real exit status.

## Fix-loop caller split — why Phase 4.3 owns the whole-suite pass

Inside `/prflow:implement` (Phase 3.3) the fix loop's terminal is not its own: every Phase 4 commit
— the 4.1 docs/changeset commit, a 4.2 claim-audit commit, the 4.3 clean-tree backstop,
checkpoint 4's merge — makes a Phase 3 flight stale by definition, and Phase 4.3's
completion-evidence flight then re-verifies the final tree, so a whole-suite pass paid at the
loop's terminal is discarded rather than relied on. The whole-suite obligation is owned exactly
once, by that Phase 4.3 flight.

A standalone terminal is narrowed on what else will ever verify the tree. The loop's terminal
verdict is a *findings* verdict, and no line of it asserts that a test suite is green, so gating a
findings verdict on a whole-suite result answers a question that verdict never asks. What the
terminal genuinely owes is the honesty floor, because the loop edits code and emitting an APPROVE
over unverified edits is an unbacked claim. Past that floor the standalone whole-suite obligation
survives only where no external backstop exists — and that is the ordinary standalone shape rather
than an edge case, since the skill reviews the current branch when no PR number is given and
`--push-each-iteration` is off by default, so a standalone run routinely has no PR, no push, and
nothing downstream at all. Declining to *claim* what a run did not verify is the opposite of
resting a verdict on a result it never saw; the backstop is a property of the project the run
evaluates once, never a signal it reads.
