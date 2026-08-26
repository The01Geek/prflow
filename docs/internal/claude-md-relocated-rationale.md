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
