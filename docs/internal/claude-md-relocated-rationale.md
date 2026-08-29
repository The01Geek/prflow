# Maintainer rationale relocated out of `CLAUDE.md` (issue #1352)

This page holds the maintainer rationale, worked narratives, probe provenance and enumerations that
the issue #1352 placement audit moved out of `CLAUDE.md`'s Architecture, Gotchas and Conventions
sections under AC5's preserve-and-relocate rule. The **instruction** and the **one sentence naming
its consequence** stay in `CLAUDE.md`; everything below is the *why*, the evidence, and the history
a maintainer occasionally needs and an executing agent never does.

Nothing links here from either loaded surface — the move is permitted, the link is not. This record
is discoverable by search, by git history, and by the issue that produced it. It is not a second
statement of any rule: where this page and `CLAUDE.md` appear to disagree, `CLAUDE.md` governs.

## The helper anchor — why the single-statement, inline-resolved shape (issues #241, #275)

`${CLAUDE_SKILL_DIR}` is *empty* (not merely unset) on non-Claude-Code runners — confirmed on
Copilot CLI, expected on Cursor, Codex CLI and Gemini CLI. Those runners instead report a
`Base directory for this skill:` context line that the agent substitutes for the placeholder.

Separately, Copilot CLI's inline `bash -c` marshaling **strips a variable assigned in one statement
and read in a later statement of the same inline command**: `bash -c 'v=hi && echo $v'` yields empty.
That is why the old assign-then-reuse recipe (`SKILL_DIR="…"; … "$SKILL_DIR"/../…`) is banned and the
anchor must be resolved inline in the statement that uses it. On Claude Code the resolved value equals
the bare form, so behavior there is unchanged.

The conditional cloud form (#1256/#1124) is deliberately **not** a blanket replacement of the anchor:
ruling consequence 2 of #1152/#1153 recorded that such a rule "would flag every call site". Roughly a
hundred anchor-source invocations under `skills/` remain the sanctioned single-source form, which
`extract-command-heads.py` normalizes to the granted literal, until each becomes cloud-reachable and
is enrolled in the fallback-arm lint.

## Rename tiers — the per-tier detail behind the frozen list (issues #1002–#1004, #1041, #1083)

**Tier 3 (#1004)** shipped without renaming the env vars; it made their freeze explicit and derivable.
`lib/rename-map.json`'s `frozen.env_identifiers` is an inventory of names *not* to rename, each row
carrying its own `failure_visibility`, reconciled against the live tree by
`lib/generate-env-freeze-advisory.py --derive`, and `/prflow:init` reports it to the consumer. No
`PRFLOW_*` read side exists anywhere in the tree, so renaming one of these does not move a setting —
it deletes it, and most delete it silently. A renamed `DEVFLOW_RUNNER`, for instance, relocates every
job to GitHub-hosted `ubuntu-latest` while the App private key and provider API key stay in its env.
Only a later tier shipping an actual dual read can unfreeze a row, and it unfreezes it in that block
in the same change.

**Tier 2 (#1003)** moved three names into the map's `identifiers` block: the provenance label
(token-matched, so `DevFlow-layout` and the several hundred prose occurrences of the product name are
unreachable), the telemetry branch (prefix-matched, so the derived artifact names move with it), and
the comment-marker namespace (prefix-matched and deliberately narrower than the frozen bare
`devflow:`). `pin-corpus-lint.py`'s `_build_rename_substitution` reads that block; its alternation is
ordered **longest literal first, frozen winning ties**, which is what lets `<!-- devflow:` out-compete
the frozen `devflow:` it narrows. The builder now refuses a name that is both frozen and mapped, and
refuses an unrecognised top-level block — the two edits that used to be silent no-ops.

**Tier 4 (#1041)** moved the two `workflows.*` config sub-keys out of the frozen list, into the map's
own `workflows_config_keys` block, leaving `frozen.config_keys` empty. They were the one pair whose
naive rename takes a consumer silently offline, because `.workflows.prflow // false` reads absent as
disabled with the fail-loud guard downstream of it. A deliberate valid-falsy `false` is carried across
verbatim. The `.github/workflows/` filenames stay frozen.

**The #1083 stray-family warning** reads presence from the config's key set rather than a
`//`-coerced value, so a valid-falsy stray survives; it matches the superseded families by the
`^devflow(_|$)` shape rather than any dotted or bare literal, because spelling one — in jq, message
or comment alike — would mark a shipped workflow stale under the freshness gate and wedge the very
migration it protects.

## create-issue — the #529 divergences and the runtime-context axis

The marker-gated reference structure is another instance of the repo's progressive-disclosure pattern,
with three **deliberate divergences from the #529 review bundle**: references live in the existing
`references/` directory rather than a new `phases/`; the gate carries no identity-manifest or hash
layer; and a failed load degrades best-effort rather than stopping.

The canonical description of the Step 3.6 audit lifecycle — the state owner and the round kinds — lives
in `docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md`.

**Runtime main-thread context is a distinct quantity from static shipped size (#767).** The behavioral
instrument `scripts/create-issue-context-eval.py` is maintainer-run and never on the skill's runtime
path; the authoritative-vs-redundant-addition determination and the pointer-not-re-quote reduction live
in `docs/internal/create-issue-context.md`, the single source of truth for that axis.

## Cloud allowlist — probe provenance and the per-tier caveats

The permitted shapes carry uneven evidence, and citing one without its tier and position overstates it:

- A Write into `.prflow/tmp/**` is probe-proven, run 29111394360.
- The repo-relative vendored-literal helper path in **leading-token** form is probe-proven at the
  *implement* tier only (row I2) and **unrecorded at the review tier**.
- Review shape 18 recorded PERMITTED for the same path in *command-substitution condition* position.
  That is confounding evidence rather than a measurement of the leading-token form, so it must never be
  cited as a bare review-tier "probe-proven".

Full probe evidence — run IDs, the review R1–R4 and implement I1–I6 tables, the non-label-capture
INFERENCE-not-measurement gap, and the grant flows including the `install.sh`-vs-vendor-fetch skew
warning — lives in `docs/internal/cloud-allowlist.md`.

The anchor-denial-in-argument-position finding is run `30695072336`.

## The grounding block — what each mode emits

The `review` mode (the default) keeps every section. The `implement` mode emits only the
tier-agnostic ones — the permitted commands, the command shapes, the headless-run discipline and
the independent-tool-call batching disposition — and omits the three review-only sections
(CI-results, sole-publisher, trusted-source displacement). Issue #1064 covers post-hoc denial
forensics, which the grounding block does not provide.

## The reviewer deny-list floor — the PR-#404 REJECT

The floor's trusted-source rule exists because the review job checks out the PR head, so a
checked-out-tree copy — committed vendor dir or `scripts/` — is PR-author-editable, and a floor the PR
controls is no floor. Rank 1 is the copy `baseprovision` materializes from the base ref
(`git show FETCH_HEAD:…` into `RUNNER_TEMP`), taken **inside the fetch-success branch only**, because
`FETCH_HEAD` elsewhere can be the PR head. Rank 2 is the vendored copy gated on the `vendor-plugin`
action's `vendor_source` output being `fetch` — a fresh official-repo clone at the pinned
`prflow_version`; `committed` and `self` never qualify. Otherwise the workflow appends nothing and warns
naming the trusted-source rule.

The Bash tier of the filter is byte-for-byte the pre-#402 command-position-basename check. `lib/test/run.sh`
drives the helper over the full adversarial matrix, and the workflow→helper call stays covered
end-to-end by the `emit_tools` behavioral block.

## The vendored-path rule — the telemetry-relay worked example (#502)

The consequence surfaced as a spurious "deployment fault" `::warning::` on every consumer auto-review.
The producer steps in `devflow-runner.yml` ran, but the trusted consumer `telemetry-push.yml` was never
shipped — it was missing from `install.sh`'s copy loop — and the collect step's repo-relative
`scripts/collect-staged-telemetry.sh` was absent in consumers. That relay is the #936-withheld tier
today, so `telemetry-push.yml` is deliberately not in that loop and the `installer-wiring` module
asserts all three tier files stay uninstalled.

## The withheld tier — why deleting its files would not simplify anything

Do not restate the retention rule as a generator or lock dependency.
`lib/generate-capability-profiles.py` writes a region into `devflow-runner.yml` only *because that file
is listed in its `REGIONS` table*, and `check_review_lock` compares the manifest-resolved `review` token
list against `lib/review-profile.tokens` without ever reading the workflow — so deleting the file and
its region would leave the reviewer security lock fully intact. With the caller gone neither file has a
reachable entry point, and the `review` profile the lock guards is consumed only by `matcher-probe.yml`'s
baseline. `derive-review-verdict.sh` is reached again by `devflow.yml`'s shipped dead-run
verdict-presence gate (via `scripts/dead-run-verdict-present.sh`, issue #1172); the other three helpers
are unreachable and retained anyway. A consumer that already installed the withheld tier keeps it —
`prune_stale_devflow_workflows()` is deliberately unchanged — and keeps its exposure to issues #930/#920.

## The pin corpus — how the standing corpus reached `boundary`-only

Issues #375/#666/#810 stopped the inflow of wording-only pins. Issue #885 ran the re-adjudication the
#843/#876 decision authorized, and the sweep that followed it. Issue #946 then brought the
`review-and-fix-contract.sh` wrapper-routed pins (`_raf_pin_unique`) into the census — ending the arm-0
blind spot — re-adjudicated them, and retired the 28 that nothing reads. So the standing corpus is once
again `boundary`-only, and every one of those rows was adjudicated so on recorded evidence, which is what
re-litigating one needs.

The worked case for the recorded decision is the review engine's Phase 4.1.5 behavior-inert prose cap in
`skills/review/phases/phase-4-verdict.md`, which shows both edges at once. Its **applicability limbs** are
read only by the reviewing agent, so nothing executable changes when a limb is deleted and no test can
drive one. Its **consequence** is genuinely consumed: the `#291` boundaries assert that the cap's operative
sentence survives, that review-and-fix Step 2.6 consumes it, and that it is not re-forked. Deleting a limb
is caught only by the merge gate that reads the prose.

`CONTRIBUTING.md`'s #798 rule states the retirement disposition, the counted-homes test, and the
fail-closed handling of an absent census row.

## The `gh api` repo-path lint — its exclusion set, one reason each

`lib/test/lint-gh-api-repo-path.py` audits the tracked-and-unignored files outside the two exempt
prefixes and outside its own documented exclusion set: `lib/test/`, `docs/`, `.prflow/logs/`,
`.prflow/learnings/`, `.changeset/`, `CHANGELOG.md` and `.claude/worktrees/`. Those are, respectively,
the prose surfaces carrying the rule's own statement text, the machine-appended corpora that quote it,
and — since this scanner's population is a *working-tree* enumeration — the sibling worktrees whose files
belong to another branch's checkout (issue #711). The module docstring carries each one's reason.

The accepted residuals the scanner cannot see are indirections through an assignment hop or a flag value:
`scripts/react-to-trigger.sh` composes `repos/$repo/…` from the `--repo` value the implement fence passes
as `$GITHUB_REPOSITORY`, and fails closed — a warning, exit 0, no POST — when that value is empty.

## `resolve-gh.sh` — the Python caller population

The Python gh-callers (`workpad.py`, `file-deferrals.py`, `match-deferrals.py`, `parse-acs.py`,
`export-workflow-lifecycle-census.py`, `build-experiment-records.py`, `check-completion-evidence.py`,
`preflight.py`, …) read `os.environ.get("DEVFLOW_GH") or "gh"` and deliberately do **not** run the probe.
`lib/preflight.sh` sources the same resolver but does not use the `:=` form — it detects only
(`_GH="$(devflow_resolve_gh)"`, re-probed, never assigned back), consistent with the overview's
"preflight only detects" contract. `DEVFLOW_GH` is the documented Windows/WSL escape hatch, recorded in
`docs/internal/install.md`.

The probe runs only when `DEVFLOW_GH` is unset or empty — `:=` fires on both — so the test suite's
`DEVFLOW_GH` stubs are untouched.

## `lib/preflight.sh` as a bash diagnostic (#248)

PRFlow supports any POSIX bash — WSL bash, Git Bash, MSYS2 bash — none mandated. The preflight emits a
`devflow-bash:` breadcrumb carrying the interpreter path and `$BASH_VERSION`, surfaces `DEVFLOW_BASH` when
set, and prints a remedy naming the three supported bashes plus the override when `$BASH_VERSION` is empty.
`lib/test/run.sh` guards the breadcrumb and remedy through the `#248` source-level recovery contract and
drives the non-bash remedy under a real non-bash shell when one is present (`dash`/`busybox`); after #809 it
carries no wording-only fallback pins for bash-only hosts, and `lib/test/` remains excluded from CI
shellcheck.

## Local-tier classifier friction — provenance

The friction is the recurring driver behind retrospective pattern `convention-violation`, first recorded
across PRs #72, #85, #87 and #98. The structural boundary is documented in
`docs/internal/efficiency-trace.md` under "Note on this repo's `.claude/settings.json`".

## The `#553` ordinal-rot class and the `#312` matrix — worked instances

The self-referential-count rule covers comments citing "the Nth grep call", "N FAIL arms", "three real
sites", or a `file:line` reference. `lib/test/run.sh` does carry tool-read comments —
`# structural-pin-ok:`, `# raw-guard-ok:`, `# tree-walk-ok:`, and the `#456` NOTE scan — which limb one of
the behavior-inertness test excludes.

The extracted-selector reference implementation is `scripts/describe-denial-count.sh` (PR #367): the
three-clause `finalize_check` selector in the then-shipped auto-review workflow was inline and asserted
only by grep-pins on two of its three message literals, so a reordered arm or a glob typo would
misattribute the diagnosis while the suite stayed green. The fix extracted it and drove every arm plus
arm-order from `lib/test/run.sh`.

For the malformed-shape matrix over mutable markdown the boundary rows are missing or duplicate sections
and markers, non-canonical layout, and empty or truncated input; for an external structured format they are
that format's own boundary rows.

## The workpad's per-record dual marker read

One workpad mutated in place across the #1003 rename boundary carries pre-rename records beside
post-rename ones. A per-artifact choice — picking one spelling for the whole comment — would leave a
pre-rename `deferred-filed` record undischarged, so the follow-up issue is filed twice. That is why the
dual read is per RECORD rather than per artifact.

## The shipped-prompt-surface lint — how each forbidden class is derived (#1072, #1309, #1402, #1423, #2114)

`lib/test/lint-shipped-pruned-path.py` audits every `skills/**` and `agents/**` file. The base
forbidden set (prune targets) is **derived from `vendor-slice.sh` itself** rather than a hardcoded
literal, so a new prune target is covered with no second edit. The audited population is `skills/**`
and `agents/**` only — the copied `scripts/`/`lib/` surface is a separate concern — so the coverage
claim is that population, never "the whole shipped surface".

**`docs.*`-default exemption (#1309).** `docs/external` and `docs/internal` are simultaneously the
defaults of `.docs.external` / `.docs.internal`, so the lint derives an exemption set from the
path-shaped `docs.*` defaults in `.prflow/config.schema.json` (by trailing-slash-normalized equality,
never prefix) and subtracts it before scanning — a shipped sentence naming a documented `docs.*`
default needs no marker.

**Never-shipped `.github/workflows/` members (#1402).** `devflow_copy_slice()` copies no `.github/`
at all, so no workflow is a prune target and the base derivation is blind to the family, while a
consumer *does* have `.github/workflows/` — a blanket `.github/` ban would be wrong. The lint derives a
never-shipped set at run time by word-list membership over the parsed `install.sh` workflow copy loop's
literal operand list (the one declaration that puts a workflow in a consumer's checkout), subtracts it
from the `.github/workflows/*.yml` basenames present, and reports an unmarked `<basename>.yml`
reference in the fully-qualified or the bare spelling; an unestablished declaration refuses non-zero
naming `install.sh` rather than auditing against an empty set.

**`DEVFLOW_WITHHELD_TIER` (#1423).** Its members reach no fresh install, so counting them as shipped
told a fresh consumer a file they lack resolves; they are forbidden like any other never-shipped name.
A withheld name that also left the tree (`devflow-review`) needs no carve-out, because the derivation
intersects with what is **tracked**. Residuals enumerated in the lint's docstring: an extensionless
stem, a `.yaml` suffix, a workflow no longer in the tree, a consumer's own same-named workflow.

**Development-harness identifiers (#2114).** Unlike the derived sets above, this denylist
(`structural-pin-ok`, `CEILING_TRIPWIRE_FRACTION`, `run-parallel` at minimum) is a hardcoded module
constant guarded non-empty at import — there is no producer file to derive it from — and a shipped
body naming one, unmarked, instructs a consumer's agent about a pin-corpus marker or suite tool their
tree does not carry.

## The `SKILL.md` `` !`cmd` `` injection refusal — forensics and historical record (2026-08-08)

The refusal is a **phase mismatch**, not pattern matching: `allowed-tools` / `--allowed-tools` grants
authorize the model's tool calls *after* the skill loads, while `` !`cmd` `` runs *during* loading as a
preprocessor (`anthropics/claude-code#39048`; the headless silent-success envelope — `subtype:
success`, `is_error: false`, `num_turns: 0` — is `#80223`). `lib/capability-profiles.json` already
grants **both** `Bash(*/render-prompt-extension.sh:*)` and the exact vendored literal and the refusal
still fires; the only reported-working options (bare `Bash`, `--dangerously-skip-permissions`) are
barred because the review profile is a security boundary.

**The refusal aborts the ENTIRE `Skill`-tool load, and is invisible to denial telemetry** (forensic
audit of run `31287654057`). The load returns an `is_error` result whose whole content is a
permission-refusal string and no skill body at all, so the run loses the skill rather than merely its
extension; and because that surfaces as a `Skill` tool result rather than a `permission_denied` event,
it does not increment `permission_denials_count`, so the no-verdict denial-count check cannot see the
failure class.

**Historical record.** No `skills/**` body carries such a placeholder any more — PRs #1471 and #1473
retired the channel and `lib/test/modules/prompt-extension-reader.sh` pins its absence per site — so
the hazard is no longer live. While placeholders existed, nothing rendered, no
`PROMPT-EXTENSION-STATUS:` line appeared, and every extension-only rule (prompt-surface edit routing,
the `Writing-skills evidence:` producer contract, the Phase 3 review gate) was absent for a whole run
that still reported `Complete` (run 31236010867 / issue #1416 / PR #1433).

## The reference-size ceiling — derivation and exemption mechanics (#1595)

`lib/test/lint-reference-size.py` audits every tracked `.md` file whose first and last **non-blank**
lines are a matching boundary-marker pair — the `<!-- prflow:<command>-ref … start/end -->` family and
`review-and-fix`'s `# Reference: …` / `<!-- END <name>.md -->` family alike — plus every skill root
(`skills/<name>/SKILL.md` at any depth), deriving that population by reading each file rather than from
a path list, so a new skill and a newly-gated reference are covered with no second edit.

The **61,750-byte** ceiling is 95% of the Read tool's 25,000-token cap converted at the **floor** of
the measured bytes-per-token densities (2.60, never their mean — a denser file truncates at a smaller
byte size), because a file over it cannot be returned in one read. Each gated surface's boundary
contract pages such a file whole before its marker checks run, so an over-budget-but-intact reference
loads instead of misreading as damage — but the extra reads still cost and a smaller reader budget may
not complete the paging, so the remedy stays trim-the-file, never exempt-it.

The files already over it carry **expiring** exemptions in `lib/test/reference-size-exemptions.json`:
each names exactly one file, one naming a file outside the record's frozen `recorded_set` is refused,
and an exemption goes RED once its file drops to or under the ceiling — so a landed trim is finished by
deleting that file's rows.

## The prompt-extension ladder — per-surface re-entry timing (#1462, #1574)

The ladder result is a `Bash` tool output with no re-attachment on context compaction, so a surface
that re-enters itself re-invokes its ladder at each existing re-entry boundary in addition to the
run-start load: `implement` at every phase (re-)entry and mid-phase re-anchor, `review` at every phase
and shadow entry, and the fix loop once per iteration for the `review-and-fix` and
`receiving-code-review` ladders alike — treating the returned text as a refresh of already-loaded
policy rather than a fresh directive; `pr-description` is single-pass and re-invokes nowhere. This
re-load timing does not weaken the sole-delivery-channel rule: the ladder stays the only channel that
delivers consumer policy into these bodies.

On an implement run each surface's outcome is recorded on the workpad as a nested `prompt extension
resolved: …` `## Progress` row, whose text and tick substring are single-sourced in `scripts/workpad.py`'s
`_EXTENSION_ROWS` and whose tick is issued only from an implement phase file — the standalone
`/prflow:review`, `/prflow:review-and-fix` and `/prflow:pr-description` paths have no workpad and record
nothing. The row's existence is deterministic; its tick is the run's own report.

## Permanent required-copy exceptions — the mechanics (#1445, #1606, #1076)

**Cloud-writer manifest (`scripts/devflow-cloud-writer-contract.json`, #1445/#1606).** `main` is its sole
writer of digests, so it is not regenerated on a branch: editing an asset it pins drifts nothing on the
branch, and a branch that rewrites or drops an entry turns `lib/test/cloud-writer-retention-check.py` RED.
A branch that ADDS a shipped skill asset is the one permitted delta and must add that asset's entry,
because the closure check fails on an unlisted asset and the key-set equality assertion fails on a manifest
disagreeing with the source list — so forbidding the addition would leave such a branch no green state. Add
the entry **without regenerating**: take the merge-base manifest and add only the new keys, since
`generate` also refreshes the digest of every asset the branch edited, which is the shape the retention
check forbids.

**Review-engine `config_only` set (#1076).** `skills/review/phases/phase-0-setup.md` §0.5 produces the flag
from that set and `skills/review/phases/phase-3-agents.md` §3.1 re-decides against it. Each is a separately
gated phase reference reached by its own read at its own phase entry, so replacing the Phase 3 copy with a
pointer would make a Phase 3 decision depend on Phase 0's text still being resident.

## Pin adjudication for prose no tool reads — the census mechanics (#843, #876)

Each pin's answer is a per-pin adjudication read from `.prflow/logs/pin-corpus-inventory.tsv` — a
single-row lookup, never a whole-file read — and *changed* in `lib/test/pin-corpus-adjudications.tsv`; that
census is a frozen snapshot, so an absent row means unanswered, never "no". The governing question is
whether any tool or consumer reads the content, never where it lives: a pin protecting a machine-consumed
contract stays under the guard-executable-behavior rule, while prose no tool reads is inside the #843 policy
wherever it sits.
