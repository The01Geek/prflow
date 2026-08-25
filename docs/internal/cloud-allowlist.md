# Cloud allowlist & command-shape reference

This is the detailed forensic record for the CLAUDE.md "cloud allowlist" gotchas
(issues #363, #392, #401, #455, #484, #561). The **operative invariants and their enforcing
pins stay in CLAUDE.md** — this doc carries the evidence, the war-stories, the
probe tables, and the reasoning that would otherwise bloat those bullets. When
CLAUDE.md says "see `docs/internal/cloud-allowlist.md`", this is where it points.

Source-of-truth files referenced throughout (bare paths — line numbers rot):

- `lib/capability-profiles.json` — the versioned manifest, single source of truth.
- `lib/generate-capability-profiles.py` — the generator (`--check` gates CI).
- `lib/review-profile.tokens` — the review-tier security-boundary lock.
- `.github/workflows/matcher-probe.yml` — the re-runnable empirical evidence source.
- `.github/workflows/devflow-runner.yml`, `devflow.yml`, `devflow-implement.yml` — the runners whose allowlist literals are generated.
- `lib/test/extract-command-heads.py`, `lib/test/extract-command-shapes.py` — the desk/CI-time guards driven by `lib/test/run.sh`.

---

## The two allowlists (issue #363)

`skills/review/SKILL.md` — the shared review engine — executes under **two
different allowlists**, and a command head that **neither** grants is **silently
denied** (refused before it runs; it does not fail loudly, it burns budget, and a
run can end with **no verdict at all**).

- **Auto-review path**: the `review` profile's `TOOLS='…'` line in
  `.github/workflows/devflow-runner.yml`.
- **Manual `/prflow:review` comment path**: `devflow.yml`'s hoisted `TOOLS='…'`
  (the `Resolve allowed-tools` step, consumed by `claude_args` **and** by the
  injected block alike, so the two cannot drift).

A command the skill invokes but a profile omits is refused. **Evidence: PR #340 —
7 of 14 denials were the engine trying to run the test suite.** The engine ended
runs with no verdict because heads it needed were ungranted on one path.

### The injected allowed-command list — every tier, including implement (issue #1170)

**Standing rule (the maintainer's):** when a command is refused by the cloud
harness, the agent should be able to see that the permission was denied and be
pointed at alternatives — either similar permitted commands, or a resource listing
the complete set of allowed commands so it can pick a permitted one and retry.

The refusal itself happens inside `claude-code-action`'s tool matcher, *before the
command runs*, and **the grounding block does not change the matcher's response** — it
is a prompt-side remedy, not a change to the harness. Whether *anything* can reach the
agent at the moment of refusal is a separate question, and it is **unestablished rather
than settled** — see the limits paragraph below, which scopes it. What this remedy
**does** achieve — and is the maintainer's stated fallback — is to put the complete
allowed-command list in front of the agent **up front**, so a refused shape is a lookup
against a list it already has rather than a guess.

`scripts/render-grounding-block.sh` injects the **exact resolved `--allowed-tools`
string** (section 2 of the review-tier block) plus the command-shape rules (section 3),
the headless-run discipline (section 4) and the independent-tool-call batching
disposition (section 5). Those four section numbers are the review-tier numbering; the
implement tier omits the three review-only sections and renumbers those four survivors
1/2/3/4, as the `MODE=implement` bullet below records. It is rendered **once**, by that one
helper, and prepended to the prompt on **every** tier:

- **`/prflow:review`, `/prflow:review-and-fix`, `/prflow:pr-description`** —
  `devflow.yml`'s `Compose engine grounding block` step, which is unconditional and so
  composes for **every** command that tier dispatches. `/prflow:review` renders in the
  default `review` mode. The other two render in `MODE=generic`, which omits the same
  three sections `MODE=implement` does and adds none of that tier's Phase 3 scope clause:
  `/prflow:pr-description` reviews no commit, and `/prflow:review-and-fix` edits and
  pushes, so the CI section's "cite these conclusions, do not re-derive them by running
  tests" instruction would contradict the in-environment whole-suite gate its own prompt
  extension makes that loop's verification channel.
- **Auto-review** — `devflow-runner.yml`'s `Compose review prompt` step.
- **`/prflow:implement`** — `devflow-implement.yml`'s `Compose implement grounding
  block` step, in `MODE=implement`, which renders the tier-agnostic sections only
  (the review-only CI-results, sole-publisher, and trusted-source-displacement
  sections are omitted, and the survivors renumber 1/2/3/4 — the permitted commands,
  the command shapes, the headless-run discipline, and the independent-tool-call
  batching disposition).

**A missing or empty renderer fails the job — it no longer degrades (issue #1520).**
Two independent controls enforce this on every tier. First, a dedicated guard step
runs *after* vendor-materialization and *before* `Run Claude Code`, failing the job
when the renderer is absent: `Validate vendored grounding renderer` on the two
review-engine tiers (`devflow.yml`, `devflow-runner.yml`), and `Validate vendored
helpers + write handoff record` on the implement tier (`devflow-implement.yml`), which
extends the same check to the two prompt-composition helpers. Second, each tier's
composition step **separately** fails when the renderer is **absent or produces
nothing**: inline in `devflow.yml`'s `Compose engine grounding block` step and
`devflow-runner.yml`'s `Compose review prompt` step, and in
`scripts/compose-implement-prompt.sh` for the implement tier, every **failure** arm of
which emits `::error::` and exits non-zero rather than publishing an ungrounded prompt.

The consumer-visible consequence: **a repository whose vendored tree lacks the renderer
goes from a degraded run to a failed job.** It used to surface as a warning in the
Actions log while the agent launched on a bare prompt; now the job stops with an error
before the agent starts. The diagnostics name the remedy — repair the committed
`.prflow/vendor/prflow` tree, or check the `vendor-plugin` fetch (`prflow_version`).

Every tier consumes the **same** hoisted `TOOLS='…'` step output for both
`claude_args`'s `--allowed-tools` **and** the injected block, so the block quotes the
exact string the run resolved by construction — there is **no second, hand-copied
copy** of the allowed-tools text (the coupled-mirror hazard the block was built to
avoid; `lib/test/run.sh` pins all three workflows to carry no second copy).

**The limits, stated plainly.** This does **not** make a denial visible at the moment
it happens, and it does **not** change the matcher's response — a refused command
still produces no output and burns budget. It only gives the agent the list to check
against, up front.

Read that as a limit of **this** remedy, not as a repository-wide impossibility. The
in-the-moment channel is **unestablished, not ruled out**: `scripts/pretooluse-shape-guard.py`
is an in-tree `PreToolUse` hook built for exactly that purpose — it returns a `deny`
whose `permissionDecisionReason` names the permitted alternative for the denied shape —
and #919 records, on repeated same-repo probe runs, that a hook registered through the
action's `settings:` input **does fire** under `claude-code-action`. The narrower question
that was open here — whether `permissionDecisionReason` survives to the engine transcript
on the **`deny`** path, given that the older observations are all on an `allow` path for
which the reason is specified to be ignored — is now **measured**: a hook emitting a real
`deny` delivered its reason to the transcript (`REASON-DELIVERED`; see *Harness
hook-surface probe evidence (Part 2)* below). What is left is deployment rather than
mechanism — the guard is wired to no runnable tier. See #1047 (residual item 2) and #919,
and the *PreToolUse probe evidence* sections further down for the recorded verdicts. Making
denials visible *after* a run is a third, separate concern — issue #1064 (durable denial
forensics). The three are complementary and none substitutes for the others.

### The head guard

`lib/test/extract-command-heads.py` (driven by `lib/test/run.sh`) extracts every
head from the skill's ```bash fences and asserts **each** allowlist grants it. The
extractor is:

- quote / comment / heredoc-aware,
- `$(…)`-descending,
- wrapper-stripping,
- **case-arm-position-aware** (issue #392): arm patterns are stripped only where
  an arm may legally begin — after `case … in` and after each `;;` — so a command
  in a case **body** (e.g. a bare subshell `(cmd)`) keeps its head instead of
  being swallowed as a bogus arm.

**Scope boundaries:**

- **Inline-backtick prose is deliberately out of reach** — matching it resurrects
  the `git a` / `git failure` / `git said` false positives. A prose-only command
  like Phase 0.3.6's `git cat-file` is pinned by **direct literal** instead.
- The case-arm tracking is a **flag, not a depth counter**, so a **nested** `case`
  block is an accepted limitation — no fence in `skills/review/SKILL.md` nests a
  `case`.
- **`.prflow/prompt-extensions/**` was outside the scanned population until issue
  #1354** — see *Audited population* below, which supersedes this and states the
  scope in force today. Historically both extractors took only the skills bundles
  as their input, while an extension's text is appended to the same agent prompt
  and can invoke the same bundled helpers — so a helper invoked only from an
  extension got **no desk signal** when its grant was missing, and the cloud
  matcher refuses it before it runs: no output, no error. Authoring such a call
  site still means adding its grant (by hand, to the manifest or the matching
  `allowed_tools` array); what changed is that a missing one is now caught at the
  desk. Worked example: `scripts/prompt-surface-growth.py` (issue #1350), granted
  on the `implement` and `command` profiles because its only call site is
  `.prflow/prompt-extensions/pr-description.md`.

**Audited population (issue #1354).** Both scanners take an explicit file list, so
their reach is whatever `lib/test/run.sh` hands them. In addition to the skill
bundles, `run.sh` now audits the repository's live tracked
`.prflow/prompt-extensions/*.md` files (`.md.example` templates excluded — they are
loaded by no run). A prompt extension is appended to the same agent prompt as the
command it names and can invoke the same helpers, so an ungranted head or a
matcher-denied shape authored there would otherwise be silent both at the desk and
in the run (the matcher refuses such a command with no output and no error). Each
extension is checked against the tier(s) that load it via a single explicitly
enumerated extension→tier table, reconciled both ways against the on-disk set (a
file with no row, or a row naming no file, fails). The head allowlist is the
**union** of the tier's baked workflow `TOOLS` grant and the matching
`.prflow/config.json` `allowed_tools` array — load-bearing, because the live fences
invoke `lib/test/regenerate-artifacts.py`, whose grant lives only in the config
array, not in `lib/capability-profiles.json`. The extractors' `_normalize()` anchor
rewrite is a no-op on extension text (extensions do not use the portable anchor
today), so no scanner logic forks for this population.

### Adding a command to a fence

Grant it by adding the token to `lib/capability-profiles.json` (the versioned
manifest) and regenerating with `python3 lib/generate-capability-profiles.py`.
The `--check` mode wired into `lib/test/run.sh` turns any manifest↔literal drift
RED before merge — you **never hand-edit** the `TOOLS='…'` literals. See
[Manifest generation](#manifest-generation-issue-561).

`Bash(cd:*)` is **ungranted on the review profile**: its probe row was
redirect-confounded (unproven), and it is pinned **absent** in `run.sh`. Do not
re-add it without a fresh redirect-free probe row. On the **implement profile** the
grant was **revoked by policy (issue #855), unmeasured** — never recorded as denied
on that tier (a leading `cd` was observed *executing* on the review tier in run
30222310785, so an ungranted `cd` head does not imply a refused statement); the
revocation removes the authoring affordance, and the leading-`cd` ban is enforced
as a desk lint (`IR4`) rather than as a claimed matcher refusal. See
[`docs/internal/working-directory-contract.md`](working-directory-contract.md).

---

## Heads vs shapes (issue #401)

**Heads are not enough.** The matcher denies composite **SHAPES** whose every head
is granted. **Evidence run 29105381021: 22 denials, no verdict.**

Refused shapes in the cloud **review** runner:

- leading `VAR=value` assignments,
- leading `cd`,
- `git -C <path> <subcommand>` (a working-directory-flag shape; see the run-30832631347 note below),
- `>` / `2>` redirects targeting `/tmp`,
- `cat`-heredoc writes,
- interpreter heads (`python3`),
- the unexpanded `"${CLAUDE_SKILL_DIR:-…}"` anchor as the **leading** token.
- the unexpanded `${CLAUDE_SKILL_DIR:-…}` anchor **in argument position under a separately-granted head** — see the dedicated subsection below (issue #1124).

### The `${CLAUDE_SKILL_DIR:-…}` anchor — leading-token AND argument-position denials (issue #1124)

The portable source anchor `"${CLAUDE_SKILL_DIR:-…}"/../../scripts/<helper>` (issues #241/#275) is denied by the cloud matcher in **two** distinct positions:

- **Leading-token position** (long recorded, above and in `CLAUDE.md`): the anchor as a command's leading token is refused. The remedy is the #1256/#1124 **conditional form** — emit the granted vendored literal `.prflow/vendor/prflow/scripts/<helper>` as the leading token first, and keep the anchor line as the fallback arm for the local/editor and non-Claude-Code tiers where `.prflow/vendor/` does not exist (portability preserved). The three review-engine consumer-prompt-extension loads now emit this form; `lib/test/lint-anchor-fallback-arm.py` is the desk-time gate that fails when an **enrolled** cloud-reachable call site emits the anchor leading token with no vendored fallback arm.

- **Argument-position denial — newly recorded.** In run **`30695072336`** (the `command` job of `devflow.yml`, `/prflow:review 1058`, 2026-08-01) the execution-diagnostics denial list contains verbatim:

  ```
  - `Bash`: {"command":"echo \"${CLAUDE_SKILL_DIR:-/home/runner/work/prflow/prflow/skills/review}\"","description":"Resolve review skill dir"}
  ```

  `Bash(echo:*)` was present in that run's resolved allowlist — **the head was granted and the command was still denied.** The distinguishing feature is the unexpanded `${VAR:-default}` expansion in the **argument**. That run recorded 21 denials in total and still completed, so the denial is individually invisible, not individually fatal.

  **Scope of the argument-position denial — MEASURED, run `30956039324` (issue #1152).** Whether the matcher refuses all unexpanded parameter expansions in argument position, only the defaulted `${VAR:-default}` form, or only this variable, was **unestablished** until this run — `matcher-probe.yml` had carried no argument-position corpus row. Issue #1152 adopted issue #1124's orphaned rows and added them to the **`command-probe`** job (rows 8–10), which measures the same `command` tier the denial was recorded on. The verdicts below are from that job (job `92149438683`) of run [`30956039324`](https://github.com/The01Geek/prflow/actions/runs/30956039324), head `85e57ac1c6dcf732a861230f82182191977c6e41`, ref `issue-1152-command-profile-shape-lint`:

  | # | Argument-position shape | Verdict |
  |---|-------------------------|---------|
  | 8 | defaulted anchor expansion `echo "${CLAUDE_SKILL_DIR:-…}" …` (reproduces run `30695072336`) | **DENIED** |
  | 9 | bare anchor expansion `echo "${CLAUDE_SKILL_DIR}" …` | **DENIED** |
  | 10 | bare expansion of a **non-anchor** variable `echo "${GITHUB_ACTIONS}" …` (control — distinguishes "this variable" from "this expansion form") | **DENIED** |

  **Reading, per the cross-reading this table was built to decide: argument-position bare parameter expansion is refused GENERALLY, not specifically for `CLAUDE_SKILL_DIR`.** Row 10's control expands a non-anchor variable (`GITHUB_ACTIONS`) under the same granted `echo` head and was denied too, which is the pre-declared "both denied" arm; row 8 shows the defaulted form is refused on the same terms. The question is now **established and recorded** rather than open. State it no wider than the evidence: this is **one measurement, on the `command` tier, at one `claude-code-action` version** — it establishes nothing for the review or implement tiers, and it is not a platform contract. **A verdict is never written from inference** — matcher semantics are provable only in a real probe run; re-probe after any `claude-code-action` upgrade.

  The practical consequence is unchanged in direction but now evidenced: the leading-token remedy (issue #1124 / PR #1272) addresses only the leading-token position, and an author must additionally keep the unexpanded anchor out of **argument** position on this tier — a granted head does not rescue it.

  **Disposition of the two resolve-once commands (issue #1594).** The denied command above (`Resolve review skill dir`) is one of exactly two value-consuming resolve-once commands — its sibling is `skills/implement/SKILL.md`'s — that fetch `<skill-dir>` as a value by expanding the anchor in **argument** position, the shape this subsection records as denied. Both now carry a **reported-base-directory-first arm**: they resolve `<skill-dir>` from the base directory the runner reports in context first, so the `echo "${CLAUDE_SKILL_DIR:-…}"` command is their **fallback**, no longer their primary channel, and its argument-position denial classifies as a tool-level refusal (`$CLAUDE_SKILL_DIR` channel unestablished) rather than leaving the run undefined. The desk-time lint `lib/test/lint-reported-base-dir-arm.py` enforces that the reported-base-directory-first arm precedes the value-consuming expansion at each enrolled call site (a `<!-- prflow:skill-dir-reported-base-first -->` sentinel). This does not discharge the author obligation above — the fallback still expands the unexpanded anchor in argument position, so it stays denied on this tier when reached — it moves that denied command off the primary path.

**Anchor invocation call-site census (issue #1124 AC2).** Re-derived at the issue's HEAD (index-sourced per issue #711): **118** anchor leading-token helper invocations across **34** `skills/*` files. Disposition:

- The **3 review-engine consumer-prompt-extension loads** — `skills/review/SKILL.md` (`review`) and both loads in `skills/review-and-fix/SKILL.md` (`review-and-fix`, `receiving-code-review`) — were the evidenced denial class on the merge-gating cloud review tier; they are **converted here** to the conditional form and enrolled in `lint-anchor-fallback-arm.py`.
- The remaining **~15** `load-prompt-extension.sh` loads (one per other `skills/*/SKILL.md`, plus the Phase-3 dispatch) and the **~100** other helper invocations (`workpad.py`, `config-get.sh`, `issue-audit-state.py`, …) are the sanctioned **#275/#701 anchor-source form**: `lib/test/extract-command-heads.py`'s `_normalize()` rewrites the anchor into the granted vendored literal before classifying, so these are the single-source form the head guard already accepts. They are **not** the "anchor with no fallback arm" denial class and are left unchanged; each follows the same conditional shape **as it becomes cloud-reachable** (ruling consequence 1), at which point it is enrolled in the lint. This is deliberately not a blanket sweep of the anchor (ruling consequence 2 / #1152/#1153).

Permitted shapes (review tier) — **each with its own evidence status**, because the
four do not rest on the same evidence and a single "probe-proven" heading over all of
them read as though they did (issue #871):

- the **Write tool** into `.prflow/tmp/**` (granted in the review profile) —
  **PERMITTED, run 29111394360** (probe shape 9). This is the *orchestrator* grant; the two
  `PENDING` **dispatched-subagent** `Write` entries further down this file (issue #858,
  review and implement tiers) are a separate measurement and do not qualify it.
- `… | tee` — probe shape 10; **no per-row verdict is transcribed** in this file.
- `tee <<'EOF'` — probe shape 6; **no per-row verdict is transcribed** in this file.
- repo-relative **vendored-literal** helper paths — the **leading-token** form is
  **unrecorded at the review tier**: the review rows that exercise it in leading-token
  position (shapes 5 and 12) carry no annotated verdict. Two rows are evidence *about*
  the form and neither measures that position: review **shape 18** recorded PERMITTED
  (run 30310938175) for a vendored-literal helper path in **command-substitution
  condition** position — confounding evidence that such a path executes on this tier,
  not a measurement of the leading-token form — and **implement-tier row I2** is
  PERMITTED for the leading-token form on the **other** tier. Cite whichever you mean
  with its tier and its position, never as a bare review-tier "probe-proven".

The skill's "Cloud command-shape discipline" section and the grounding block's
command-shapes section carry the recipe. **Rule of thumb: two denials of a shape →
switch to a permitted alternative, never iterate variants.**

`lib/test/extract-command-shapes.py` (driven by `lib/test/run.sh`) turns a
denied-shape fence RED at the desk.

`.github/workflows/matcher-probe.yml` (repo-internal; **not** shipped by
`install.sh`) is the re-runnable evidence source — **re-run it after a
`claude-code-action` upgrade** before changing shape rules or grants (matcher
semantics are version-dependent).

---

## Probe evidence (review tier)

The review-tier `probe` job in `matcher-probe.yml` composes `--allowed-tools =`
the generated review-profile literal **plus candidate grants under test**, runs a
Haiku `claude-code-action` session that attempts each corpus shape once, and
computes a per-shape PERMITTED / DENIED / UNATTEMPTED verdict **deterministically**
from the action's execution file (`permission_denials` + recorded `tool_use`
calls) and on-disk side-effect files. **The model's own text output is never the
measurement.**

The abstract review-tier rule set is R1–R4 (leading-assignment / leading-`cd` /
`/tmp`-redirect / heredoc-write / interpreter-head families), enforced by
`extract-command-shapes.py`. A fifth rule, **R5** — an `if`/`elif`
command-substitution *condition* (issue #857) — shipped as a **discipline-only**
rule (not probe-backed when it landed, the same posture as the implement-tier IR3)
and was **retired in issue #869**: the review engine's old live-progress-comment
seed branched on `elif WP=$(workpad.py id …); then` inside a `case`/`if`/`elif`
compound, and the cloud review matcher refused that compound outright —
**measured 8/8 refusals across 6 PRs** (issue #857), each with the harness string
`Contains shell syntax (string) that cannot be statically analyzed`. The fix moved
that find-or-create decision into the bundled helper
`scripts/seed-review-progress.sh`, invoked as a leading-token
statement (a form granted on the review profile, though its review-tier permitted-ness
is unrecorded per the review-tier entry above; issue #871 appended a `; echo "seed-rc=$?"` trailer
so a refusal of that statement is observable rather than silent), and R5 guarded against reintroducing the *bare* `if VAR=$(…)` /
`elif VAR=$(…)` condition-substitution spelling as a stop-gap until the shape
could be measured in isolation. Four `matcher-probe.yml` review rows added in
PR #864 (a `;`-joined multi-statement command, a multi-line `if`/`else`/`fi`, an
`if VAR=$(granted-helper …)` condition — **Shape 18** — and a `printf` with a
double-quoted expansion) supplied that measurement. Shape 18 recorded
**PERMITTED** (review `probe` job, run **30310938175**, 2026-07-27): the condition
shape is cloud-permitted, so R5 — the finder, its `REVIEW_RULES` membership, its
planted control, and its `run.sh` assertions — was removed (issue #869). The
retirement does **not** re-permit the shape in `skills/review/**`: the seed no
longer uses it (the helper extraction stands on its own merits), and the removed
rule only ever guarded a stop-gap idiom the engine had already abandoned. Notable
recorded verdicts:

| Candidate | Verdict | Note |
| --- | --- | --- |
| `Bash(cd:*)` | DENIED | Row confounded by an independently-denied `>` redirect — **unproven**, kept for a redirect-free re-probe, pinned absent in `run.sh`. |
| `Write(/tmp/**)` | DENIED | Genuine out-of-workspace denial. |
| `Bash(scripts/*.sh:*)` (trailing-extension glob, issue #412) | DENIED — run **29135163829** (PR #413) | Even with the glob granted, `scripts/config-get.sh …` was refused (same DENIED as the ungranted control) → the trailing-extension glob does **not** match a repo-root leading token; the implement profile keeps the enumerated `*/<basename>.sh` helper globs; **no migration to `scripts/*.sh`**. |
| `Write(.prflow/tmp/**)` | PERMITTED | Landed as a grant from the probe's **first run, 29111394360**. |
| Shape 18 — `if VAR=$(granted-helper …)` condition-substitution (issue #857) | PERMITTED — run **30310938175** (review `probe` job, 2026-07-27) | The `if`/`elif` command-substitution condition shape is cloud-permitted → **retired desk-lint rule R5** (issue #869). Does not re-permit the shape in `skills/review/**` (the seed is already helper-extracted). |

Positive-control note (issue #477): the review verdict counts a
`permission_denials` match as DENIED **ahead of** `tool_use`, so an unrelated
`/etc/hosts` read (attempted by the model with a `Bash(grep:*)` grant) can make the
row-11 control read DENIED. The sibling probe jobs score their controls
differently and are unaffected.

### `load-prompt-extension.sh` grant surfaces and the Phase-3 dispatch (issue #802)

`load-prompt-extension.sh` is granted **directory-agnostically** — as
`Bash(*/load-prompt-extension.sh:*)` — on the `review` and `command` profiles, and
**by vendored literal only** — `Bash(.prflow/vendor/prflow/scripts/load-prompt-extension.sh:*)` —
on the `implement` profile (the `implement` profile carries no `*/` wildcard for it).
The Phase-3 final-pass reviewer dispatch (`skills/review/phases/phase-3-agents.md`)
**supplies the reviewer the vendored literal** as an already-resolved leading-token
command, so the dispatched path runs a granted shape on every tier and needs **no**
wildcard on any tier — the change adds **zero** grants.

**The grant's risk framing changed with issue #874 — it is no longer only "the
extension fails to load".** On the review tier the loader's bytes previously came
from the PR-head checkout, so the directory-agnostic grant also admitted a command
whose *output became the merge-gating reviewer's own appended prompt*. That channel
is now closed at the environment rather than at the grant: the review job exports
`DEVFLOW_PROMPT_EXTENSION_ROOT` pointing at a `$RUNNER_TEMP` closure populated from
the trusted base ref, and truncates the workspace copies unconditionally. The grant
itself is **unchanged** — the variable arrives through the step's `env:` rather than
a command prefix (a leading `VAR=value` is a denied matcher shape), and the new
`scripts/materialize-trusted-prompt-extensions.sh` runs as a workflow step rather
than an agent command — so `lib/review-profile.tokens` is byte-identical and
`lib/generate-capability-profiles.py --check` stays green.

### Render-time `` !`…` `` placeholder injection — RETIRED (issues #1264, #1472)

**No skill body carries a placeholder any more.** Issue #1472 removed the last four,
after a forensic audit of run `31287654057` established that a `Skill`-tool load of a
body carrying one **fails outright**: it returns `is_error=true` whose entire content is
a permission-refusal string and no skill body at all (`prflow:implement` 208 chars;
`review-and-fix` and `pr-description` 218 chars each), while the two skills without a
placeholder in the same run loaded clean. Issue #1462 had already made the
`load-prompt-extension.sh` ladder unconditional at all five call sites, so the
placeholder was redundant where it worked and fatal where it did not. The refusal
surfaces as a `Skill` tool result rather than a `permission_denied` event, so it does
**not** increment `permission_denials_count` — the failure class is invisible to a run's
own denial telemetry (issue #1446 carries the machine-observability half).
`scripts/render-prompt-extension.sh` and its `Bash(*/render-prompt-extension.sh:*)`
grants are **retained**: narrowing the read-only `review` profile is a security-boundary
change requiring a same-PR `lib/review-profile.tokens` move, and nothing needs it.

The rest of this section is the **historical measurement record** — the shapes, probe
run IDs and residuals that were established while the channel was live. It is retained
as a past-time snapshot so a future proposal to reintroduce render-time injection starts
from what was measured rather than re-deriving it.

**The accepted shape, and the two constraints it satisfied.** The placeholder was a
single inline command, un-fenced, carrying the bare `${CLAUDE_SKILL_DIR}` anchor and
**no other expansion**:

```
!`${CLAUDE_SKILL_DIR}/../../scripts/render-prompt-extension.sh review`
```

- **No shell expansion in the command text.** Run `31058109064` refused
  `` !`/bin/echo "PHPROBE_ENV ${DEVFLOW_PROMPT_EXTENSION_ROOT:-UNSET}"` `` with
  `Contains expansion`. The probe reached substitution only after moving that read
  **inside** the wrapper's own body, which is where `render-prompt-extension.sh` reads
  `DEVFLOW_PROMPT_EXTENSION_ROOT`. Do not move it back to a call site.
- **The head must be granted.** Rendering **is** matcher-gated under
  `claude-code-action` — run `31058504896` recorded
  `Shell command permission check failed … This command requires approval`, which
  **supersedes** the bare-CLI measurement that reported injection ungated. So the
  wrapper is granted as `Bash(*/render-prompt-extension.sh:*)` **and** the vendored
  literal on `review`, `implement` and `command`. The wildcard is the load-bearing one:
  `${CLAUDE_SKILL_DIR}` resolves to an **absolute** path, which no vendored literal
  matches. Note this is a **widening** of the `review` profile, so
  `lib/review-profile.tokens` moved in the same change.

**Positive substitution evidence:** run `31058740794` (`SUBSTITUTED_ENV_VISIBLE`)
established that a placeholder in a **plugin-sourced** `SKILL.md` is substituted under a
slash-command prompt, and that the injected command inherits `$GITHUB_ENV`-exported
values — so the injected load reads the #874/#1075 trusted base-ref closure rather than
the working tree, inheriting that property rather than rebuilding it.

**Two residuals, stated rather than assumed — the first still unmeasured, the second
since measured.** That probe used a **bare literal** path, so no dispatched run has
exercised an anchor-bearing placeholder at all.

1. **Substitution** of `${CLAUDE_SKILL_DIR}` inside placeholder text is inferred from its
   documented substitution in skill markdown content, not established by a dispatch.
2. **Refusal.** The constraint above is titled *no shell expansion in the command text*
   and rests on a run that refused `${VAR:-UNSET}` with `Contains expansion` — and the
   accepted shape then carries `${CLAUDE_SKILL_DIR}`, which is syntactically an
   expansion. The design assumes the two differ in kind: Claude Code substitutes the
   anchor in skill markdown **before** the command is analyzed, so the analyzer should
   never see `${…}`, whereas `DEVFLOW_PROMPT_EXTENSION_ROOT` is not a template variable
   and survives as literal text. **Residual 2 is now MEASURED, and the hypothesis above
   was wrong.** The refusal is real on the cloud headless tier, but its cause is a
   **phase mismatch**, not a syntactic `${…}` check: `allowed-tools` grants authorize
   the model's tool calls *after* the skill loads, while `` !`cmd` `` runs *during*
   loading as a preprocessor, so no grant can reach it (`CLAUDE.md` records the
   measurement; run `31236010867` / issue #1416 is the observed instance).

**What a refusal costs, and why it is not the abort hazard.** A refused placeholder is
not the zero-turn abort that a *non-zero exit* from a rendered command causes — the
recorded refusals surfaced as errors on runs that continued. The predicted failure mode
of residual 2 was a **silent degrade to the demoted fallback prose**; run `31236010867`
shows **that degrade did not occur** — the fallback arm was reachable and its predicate
satisfied, and the run simply did not execute it, completing with the extension never
loaded. That is why issue #1462 removed the fallback's entry condition entirely: the
ladder is now invoked unconditionally at all five call sites, so there is no conditional
arm left for a run to decline. Nothing in CI, the suite, or the verdict distinguishes a
lost extension from a delivered one; the workpad's per-surface `prompt extension
resolved: …` rows are the run-authored record that narrows — never closes — that gap.
Residual 1 — whether `${CLAUDE_SKILL_DIR}` is substituted inside placeholder text — was
never measured and now never will be: with the channel retired there is no call site to
dispatch it against. The anchor was used rather than a vendored literal because this
repository has no `.prflow/vendor/prflow/` on its own checkout, so a vendored-literal
placeholder would have been `command not found` here — and a non-zero exit from an
injected command aborts the whole skill invocation at zero turns, trading a silent
policy loss for a silent total run failure. Run `31287654057` then showed the outright
`Skill`-load failure above, which is a **third** and worse cost than either.

**The three previously-recorded refused shapes are reachable on every run again (issue
#1462).** The #1258 run's three refused loader invocations
(`<workspace-absolute>/skills/review/../../scripts/load-prompt-extension.sh review` with
and without a trailing `echo`, and the repo-relative `scripts/…` form) were all the
agent reaching for the loader itself. An earlier revision of this page recorded them as
unreachable because the agent only invoked the loader when the placeholder had *not*
rendered; that gating is gone — the ladder now runs unconditionally at all five call
sites — so a grant these shapes need must not be narrowed on the assumption that only a
non-Claude-Code runner exercises them.

### Step-level `env:` propagation — still PENDING, but not on a dispatch (issue #874)

`.github/workflows/matcher-probe.yml` carries an **`env-propagation-probe`** job that
measures whether a step-level `env:` entry on a `claude-code-action` step is visible
to a command the **agent** runs — at two depths, because the two protected extension
loads sit at different ones: the `review` load runs in the orchestrator's own shell
(hop one) and the `requesting-code-review` load runs inside a dispatched
`general-purpose` Task (hop two). Every other `env:` entry on that step is consumed by
the CLI process itself, so no existing evidence covers a value an agent-run command
must read back — and this repository's own comment beside
`CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` records that even the CLI-level effect was
measured rather than assumed.

The job sets the sentinel `DEVFLOW_ENVPROBE_SENTINEL_874`, has the session echo what
each hop read through its own Bash calls, and derives a four-way verdict
(`BOTH_HOPS` / `ORCHESTRATOR_ONLY` / `NEITHER_HOP` / `INCONCLUSIVE`, plus a suspect
`DISPATCHED_TASK_ONLY` inversion) with `scripts/env-propagation-probe-verdict.py`,
whose five verdict arms and four degraded arms `lib/test/run.sh` drives.

**This measurement is PENDING — but a dispatch is not what it is waiting for.** The
framing this entry carried ("PENDING a maintainer-dispatched run") was wrong on its
premise: `matcher-probe.yml` also triggers on a same-repo `pull_request` filtered to its
own path, so the job has in fact been running on every PR that touches that workflow.

**A run has now been observed and it did not produce a verdict.** In run
[`30956039324`](https://github.com/The01Geek/prflow/actions/runs/30956039324), job
`env-propagation-probe` (`92149438747`), head
`85e57ac1c6dcf732a861230f82182191977c6e41`, 2026-08-04, the job returned
**`INCONCLUSIVE`** with `hop1_reported=False, hop2_reported=True` — one hop reported
nothing at all, which `scripts/env-propagation-probe-verdict.py` deliberately routes to
*unestablished* rather than to a negative. Per "Unknown is not zero", **no verdict cell
is filled from this**: the four-way question (`BOTH_HOPS` / `ORCHESTRATOR_ONLY` /
`NEITHER_HOP`) remains open, and `ORCHESTRATOR_ONLY` in particular must not be inferred
from a silent hop one.

What this changes is the remedy. The probe most likely needs a **design fix** before it
can yield a verdict, so a blind re-run would probably return `INCONCLUSIVE` again. What
is established is only that hop one produced **no reading at all** in the execution file
the helper reads.

**Cause diagnosed and fixed (issue #1321).** Hop one's genuine reading is the
shell-EXPANDED value Action 2 prints (`printf 'ENVPROBE_HOP1 %s\n' "${VAR}"`), recorded by
the harness as that Bash call's `tool_result` **output**. The verdict helper's `collect`
read only `tool_use` **inputs**, where the variable is unexpanded by design, so hop one was
reported only if the model-performed Action-3 echo-back copied the value into a later
`tool_use` input. In run `30956039324` that echo-back did not land (hop two's did, which is
why only hop two reported). The owning surface was the helper's hop-one derivation, not the
prompt: `scripts/env-propagation-probe-verdict.py`'s `collect` now also reads Bash
`tool_result` outputs, so hop one is derived from Action 2's recorded output directly,
independent of the echo-back. The `_OBSERVED` guard is unweakened — the unexpanded
instruction text lives only in a `tool_use` input, never in a `tool_result` output. The fix
is helper-only and touches no workflow, so it spends no probe dispatch; the next batched
`matcher-probe.yml` dispatch runs the fixed verdict step and can finally yield a real
verdict.

Until a verdict exists, the claim that a consumer's committed base-ref
extension keeps working is an **expectation, not a guarantee**. The failure direction
is safe either way — an unpropagated variable makes the loader resolve the repo-root
path, find the workflow's truncated file, and print nothing — so a propagation failure
costs the feature, never the boundary; the loader's resolved-root breadcrumb, surfaced
at hop two through the `EXTENSION-STATUS: … resolved-root=…` field, is what makes such
a failure observable rather than silent.

The probe job's **helper-invocation-form rows** exercise a vendored helper as the
leading token in five path/grant forms (the review job uses `config-get.sh` as that
exemplar helper, not `load-prompt-extension.sh`). Three of them — the control row
(shape 11), the repo-relative vendored-literal row (shape 12) and the absolute-path
row (shape 13) — are **unrecorded**: no PERMITTED/DENIED verdict for them appears in
this table or in `run.sh`'s pin block. The remaining two are **not** unrecorded and
are deliberately not folded into that statement, because the source states different
things about them (issue #871):

- **Shape 15** (the repo-root `scripts/…` row under the `Bash(scripts/*.sh:*)` glob)
  is **measured DENIED — run 29135163829, PR #413**, per the `Resolve allowed-tools`
  step comment in `.github/workflows/matcher-probe.yml` and the glob row in the table
  above.
- **Shape 14** (the repo-root `scripts/…` row without that glob) is DENIED **only per
  that note's comparative clause** — it reads "the same DENIED as shape 14's ungranted
  control" — and carries **no independently recorded row verdict of its own**.
  Labelling both with one run id would state more than the source does.

**Every review-tier probe row for which no verdict is recorded ANYWHERE in
`.github/workflows/matcher-probe.yml` — neither annotated on the row itself nor stated
in that workflow's `Resolve allowed-tools` step comment — is likewise unrecorded**, and
takes the same remedy. Both locations count, because verdicts are recorded in both places:
shape 18's PERMITTED is annotated on its own row, while shape 15's DENIED and shape 9's
`Write(.prflow/tmp/**)` PERMITTED live in the step comment. A predicate keyed on the
row annotation alone would classify those latter two as unrecorded and contradict this
file's own evidence table. It is written as a predicate over the rows rather than a transcription of
today's row numbers, precisely so it cannot go stale when a row is added or a dispatch
records a verdict — read the current answer off the workflow itself, checking both
locations. Establish any of them with a post-merge
`workflow_dispatch` run of `.github/workflows/matcher-probe.yml` (its only pre-merge
trigger is a `pull_request` scoped to its own path, and `gh workflow run` is granted
on no profile, so the run is not an acceptance criterion of the change that added
this note). Until then, a refusal of the dispatched vendored-literal command is
handled by the Phase-3 fail-closed refusal path, never assumed impossible.

### Dispatched-subagent `Write` into `.prflow/tmp/**` — review tier — MEASURED PERMITTED (issue #858)

`.github/workflows/matcher-probe.yml` carries a **`subagent-write-review-probe`** job
that measures whether a **dispatched subagent's** `Write` into `.prflow/tmp/**`
succeeds under the review tier's **generated baseline joined with the `probe` job's own
standing candidate extras** — not the shipped review profile alone, which is why the
record reproduces the resolved literal verbatim rather than describing it. `Write(.prflow/tmp/**)` is granted for
the **orchestrator** (the `Write(.prflow/tmp/**)` grant row in the review-tier evidence table above, PERMITTED from run `29111394360`; the probe exercises it as shape 9), but a grant proven
for the dispatcher is `unestablished` for the **dispatchee** — CLAUDE.md's "Unknown is
not zero". The job is **dedicated** (not a shape row in the `probe` job, whose session
already writes to `.prflow/tmp/probe-09.txt`): its prompt instructs **no orchestrator
write at all**, so a `Write` record in its execution file has exactly one *expected*
author. That single-authorship is a **prompt-level** guarantee, not a technical
restriction — the composed allowlist grants `Write(.prflow/tmp/**)` to the whole
session, so the orchestrator retains the capability and simply is not asked to use it.
The helper does not rest on the guarantee alone: where the execution file records parent
chains at all, a parent-less (orchestrator-issued) `Write` naming the same file is
detected and routes the run to `unestablished` rather than to a `DENIED` whose
attribution that record would falsify.

The job **consumes** the resolved review literal from the `probe` job via `needs:`
(never a second `REVIEW=` assignment) and appends **`Task,Agent`** in its own
hand-written `--allowed-tools` — both dispatch heads granted so the allowlist can never
be what prevents the dispatch, keeping a null result attributable to the harness. `Task`
is in no generated region or manifest; this grant enters no shipped profile. The
dispatched `subagent_type` is the built-in `general-purpose` (no `--agents` block). The
subagent makes a granted-head control call **before** the write and one **after** it, and
`scripts/subagent-write-probe-verdict.py` derives a three-outcome verdict
(**PERMITTED / DENIED / `unestablished`**) from the execution file's `permission_denials`,
recorded `tool_use` inputs, and each call's `parent_tool_use_id`, corroborated by the
on-disk side-effect file. It reports the two control facts **independently** —
*recorded-at-all* and *chain-attributable* — never conjoined; the model's prose is never
read. A state outside the measurable pair reports `unestablished` rather than `DENIED`,
with one disclosed residual: a denial entry recording no `tool_name` at all and naming
the side-effect filename is read as the write denial, because the per-entry denial shape
is not yet recorded and no narrower attribution channel exists for it.

Both signals are attributed **per recorded entry**, never over the concatenation of the
run's entries: the write is the `Write` tool's own call naming the tier's side-effect
filename — the payload marker alone is not enough, since a write of that payload to another
path is not the write the probe asked about (a
different tool merely *naming* that path is not the write, and a different tool's refusal
quoting it is not the write's denial), and a parent-less marker call is the orchestrator's
wherever the execution file records parent chains at all. The **denial** side carries the
same filename requirement as its twin: a refused `Write` carrying only the payload and not
the tier's side-effect filename was a write to some *other* path, so it routes to its own
named `unestablished` reason rather than publishing a `DENIED` about a target whose
permission was never attempted — and so does a refused `Write` naming **neither** the
side-effect filename nor the payload, the entry shape the helper records as not yet
observed: its text establishes nothing about what was refused, so the run says exactly that
instead of falling through to a claim that no write was attempted. A multi-entry denial list holding both a dispatch refusal
and a genuine `Write` denial still reports `DENIED` **provided a dispatch is also recorded
in the file** — that conjunct is what the verdict requires, and with no recorded dispatch
there is no dispatchee to attribute the denial to, so such a list reports `unestablished`.

**This measurement is RECORDED.** The section's own prose already named the trigger that
produced it — *"its only pre-merge trigger is a same-repo `pull_request` scoped to the
workflow's own path — so pushing this change to the implementing PR **does** fire it"* —
but the resulting run was never read back, so the row sat at `pending` while the evidence
existed. It is transcribed here from run
[`30956039324`](https://github.com/The01Geek/prflow/actions/runs/30956039324). No
`workflow_dispatch` was involved.

**The trigger mechanism, kept here in full because misreading it is what left this row
and several others stale.** `matcher-probe.yml` fires on
`workflow_dispatch` **and** on a same-repo `pull_request` filtered to its own path, and
**the `paths:` filter does not narrow that to the pushed commit**: on a `pull_request`
event GitHub evaluates `paths:` against the three-dot base…head diff — the files changed
in the *whole PR* — so once a PR touches `matcher-probe.yml` at all, **every subsequent
push re-fires every paid probe job in the workflow**, including the commit that records a verdict. Two
consequences. A recorded head goes stale the moment another push lands, so a verdict is
transcribed from a specific run id and head rather than from "the PR". And a PR that
edits that workflow is expensive by construction — which is why a docs-only change
recording already-produced verdicts costs nothing and a re-dispatch costs a full probe
sweep.

The recording requirements this section set for itself are met as follows. **Ref**,
**run id**, **job id** and **head commit** are in the table below.
`--permission-mode acceptEdits`, model `claude-haiku-4-5-20251001` and `--effort low`
are as specified. The **resolved `--allowed-tools` literal, verbatim**, is committed at
[`docs/internal/subagent-write-probe.observed.md`](subagent-write-probe.observed.md) rather than
inlined here: the two literals are ~1.9 KB and ~7.2 KB and would bury the surrounding
prose. This is the machine-output artifact the section calls for, and it carries
each job's complete emitted step summary unedited, literal included, under the same
expiring-evidence rationale as
`lib/test/fixtures/execution-file-shape.observed.txt`. Nothing required is omitted; it is
relocated to the artifact and pointed at from here. The **`tool_use` /
`parent_tool_use_id` pair** a `PERMITTED` must cite is
`toolu_01SbG9oxWxp5PTNS3bbymzD3` → `toolu_01Cd3LViMMbQw2surtkyDFGL` (review tier), so a
reader can re-verify the chain. The run recorded **zero** `permission_denials` entries,
so this run contributes no reading of the **observed denial-entry shape** — that read,
which would upgrade the *denial* side from by-construction to measured, remains
outstanding and is not discharged by a `PERMITTED`.

The helper's own supporting facts, all `yes` on this run: `dispatch_outcome=recorded`,
`recorded_at_all=yes`, `chain_attributable=yes`, `control_before=yes`,
`control_after=yes`, `write_outcome=recorded`, `write_chain_ok=yes`, and
`side_effect_state=corroborated` — the on-disk `.prflow/tmp/subwrite-review.txt` carried
the probe's payload marker.

This verdict is version-dependent and establishes nothing for a differently-defined
subagent type or a later `claude-code-action` version: **re-probe** after any upgrade
(measured against `claude-code-action@v1` with Claude Code 2.1.221).
**Scope caveat, carried in the emitted record itself:** the run uses
`--permission-mode acceptEdits`, so this `PERMITTED` answers *"did the dispatched
subagent's `Write` land under that permission mode?"* — it does **not** isolate the
allowlist from the permission mode as the sole reason the write was allowed.

| Tier | Verdict | Run id | Job id | Head commit | Ref |
| --- | --- | --- | --- | --- | --- |
| review | **PERMITTED** | `30956039324` | `92149631372` | `85e57ac1c6dcf732a861230f82182191977c6e41` | `issue-1152-command-profile-shape-lint` |

---

## Probe evidence (implement tier) (issue #455)

The read-write `devflow-implement` profile is a **separate allowlist** with its
**own** probed denied shapes — **a shape proven on the review tier is unproven
here** — so the `implement-probe` job in `matcher-probe.yml` covers it
independently. Its abstract rule set is IR1 / IR2 / IR3 / IR4 / IR5 (distinct from
review's R1–R4; IR4 is a leading-`cd` authoring lint (issue #855) and IR5 mirrors
R3's `/tmp` redirect arm (issue #915)), enforced by
`lib/test/extract-command-shapes.py --profile implement`
against `skills/implement/SKILL.md`, `skills/implement/phases/*.md`, and
`skills/implement/references/*.md`.

### Leading `cd` and the working-directory contract (issue #855)

A **repo-relative vendored-literal helper path resolves against the `actions/checkout`
workspace root** — the run begins there and the Bash tool's working directory
persists across calls, so a leading `cd` moves every later helper's resolution base
out from under it. The canonical statement of that contract, tier-scoped, is
[`docs/internal/working-directory-contract.md`](working-directory-contract.md).

`Bash(cd:*)`'s status on the implement tier is **revoked by policy (issue #855),
unmeasured** — **never denied**. The revocation removes an authoring affordance; it
is **not** claimed to produce a matcher refusal, because a leading `cd` was observed
*executing* on the review tier (run 30222310785) where the grant is already absent.
The leading-`cd` ban is enforced instead as the desk lint **`IR4`**
(`find_implement_violations` emits it for a fenced statement whose head is `cd`), so
a `cd` authored into a scanned prompt surface fails at the desk.

`IR1` / `IR2` (label-helper loops) are the only implement-tier rules with a probe
measurement (rows I4/I5). `IR3` is discipline-only (the capture carve-out rests on
an inference, not a measurement — see rows 8/9 below). **`R1`, `R3` and `R4` are not
enforced on the implement profile at all, because their status there is
unmeasured** — the recorded implement rows carry no entry for a leading assignment,
a `/tmp` redirect, or an interpreter head. The contrary evidence that *does* exist
is not a permission: the PR #694 run reported a **blocked stdout redirect even into
the working-directory `.prflow/tmp`**, and the interpreter head is denied per issue
#789. Neither of those forms is stated as permitted on the implement tier; they are
simply not carried as an enforced desk rule there.

### The recorded implement-tier table (rows I1–I6)

The original attribution-split run (issues #450/#455) proved:

| Row | Shape | Verdict |
| --- | --- | --- |
| **I1** | unexpanded `${CLAUDE_SKILL_DIR:-…}` anchor as the leading token | DENIED |
| **I2** | explicit **vendored-literal** grant form, measured on `apply-labels.sh` | **PERMITTED** (real recorded `tool_use`) |
| **I3** | config `*/basename` glob against a vendored-literal leading token, measured on `ensure-label.sh` | DENIED (the glob did not match) |
| **I4** | `for …; do …; done` wrapping a label helper | DENIED |
| **I5** | piped `while read` loop wrapping a label helper | DENIED |
| **I6** | `VAR="$(…)"` capture of a label helper (confounds label-helper + capture + inner `2>&1`) | DENIED |

**I3 is the whole reason the explicit grants had to ship.** Read it as "the glob
form was refused", **not** as "`ensure-label.sh` is unreachable". Stage B (#455)
then shipped both halves — the explicit vendored-literal grants in
`devflow-implement.yml` **and** the call-site rework — so the split is retired and
the job now measures the **real shipped profile end-to-end**.

### The issue #571/#1514 re-measurements (rows 1–20)

Observed 2026-07-18 UTC (issue #571): user-directed `workflow_dispatch` run
**29623046995**, `implement-probe` job **88021801138** (completed success before
the workflow's intentional cancel-probe cancellation), at commit
`f2162d7683bc7a352fce4efce3f092e864aab8b9`. **An autonomous implement run cannot
discharge this evidence gate without explicit human direction.** The execution-file
verdict table:

```
 1 DENIED      2 PERMITTED   3 PERMITTED   4 DENIED
 5 DENIED      6 DENIED      7 PERMITTED   8 PERMITTED
 9 DENIED     10 DENIED     11 PERMITTED  12 PERMITTED
13 PERMITTED  14 DENIED     15 DENIED     16 DENIED
```

Every row recorded `tool_use=yes`; rows with a shape discriminator recorded
`shape=ok` — so none of the #571 rows was REFORMULATED or UNATTEMPTED. In this
re-measurement rows 2/3 are PERMITTED because the shipped profile now carries
**both** the explicit grant and the glob for each label helper, so a PERMITTED
there proves the leading-token call **runs** but attributes to **neither form**
(I3's recorded glob denial remains the standing evidence that the glob does not
match a vendored-literal leading token).

Issue #1514 added exact rows 17–20. User-directed run
[`31733588260`](https://github.com/The01Geek/prflow/actions/runs/31733588260),
`implement-probe` job `94559726777`, at
`8eafa06e605b0f043a1e014acb35fb27e63cc008` recorded:

```
17 PERMITTED  18 DENIED  19 PERMITTED  20 DENIED
```

Rows 19 and 20 use the same `gh issue view 1514 --json body --jq '.body'`
head and differ in target form: the repo-relative target was PERMITTED, while
the `$GITHUB_WORKSPACE` absolute target was DENIED. Both recorded
`tool_use=yes; shape=ok`. This is exact-command evidence only, not a universal
permission for `gh`, redirects, or `.prflow/tmp/**`. Agent-authored scratch
defaults to the Write tool unless current evidence covers the complete
tier/head/target/statement tuple; deterministic helpers may own their output.

### Rows 8/9 — the non-label-capture disambiguators

The `VAR=$(…)` capture carve-out (the phase-4 fences read `deferred.labels` that
way) is exempted on the **reasoning** that the matcher descends into the
substitution — **but this is an INFERENCE, not a measurement.** The only measured
capture row (I6) came back DENIED while confounding three properties (label
helper + capture + inner `2>&1`).

- **Row 8** — `VAR=$(…)` capture of a **non-label** granted helper, bare spelling
  (the disambiguator for descent). A PERMITTED means the matcher descends into a
  non-label substitution and I6's denial is label- or redirect-attributable.
  (Note: the fences actually emit the capture inside an `if !` compound, which
  remains unmeasured — a PERMITTED settles the descent question, not the fences'
  exact statement shape.)
- **Row 9** — redirect-free `VAR="$(…)"` capture of a **label** helper (identical
  to I6 but without the inner `2>&1`). Read with rows 6 and 8, it separates "the
  capture shape is denied" from "the inner redirect is denied" from "a label
  helper inside a substitution is denied".

**Until a dispatch records rows 8/9, do NOT cite the carve-out as probe-proven,
and keep every phase that depends on such a capture fail-closed** — *no output at
all* is a possible denial, never an empty value.

### Re-deriving the I2/I3 per-form attribution

The shipped profile now carries **both** the explicit grant and the `*/basename`
glob for each label helper. If an upgrade ever needs the per-form verdicts
re-measured, **re-split TEMPORARILY in a scratch branch** — grant `apply-labels.sh`
only explicitly and `ensure-label.sh` only via the glob, as the original run did —
dispatch, record, and **revert**. Do not leave the split in: it makes the job
measure a profile the repo does not ship.

Multi-operation statements (`A; B`, `A && B`) are deliberately excluded from the
probe: shipped implement phase fences already exercise them successfully, so
another row would be redundant rather than new evidence.

### Row 17 — an executable `.py` as a direct leading token (issue #789)

Observed on the **implement** tier in run **30129638403** (branch
`worktree-issue-789`), shape row **17** of `matcher-probe.yml`:

| Row | Shape | Verdict |
| --- | --- | --- |
| **17** | an **executable** `.py` file invoked as a direct leading token (`lib/test/coverage_map_guard.py --iprobe17direct`) | **PERMITTED** (`denial=no; tool_use=yes; shape=ok`) |

This is the `run.sh` / `run-module.sh` pattern applied to a Python helper: the file
carries a `#!/usr/bin/env python3` shebang **plus the exec bit**, is granted as
`Bash(lib/test/coverage_map_guard.py:*)`, and is invoked **by path**. The
contrasting fact is the one already recorded under *Heads vs shapes* — `python3
<script>`, the **interpreter-head shape**, is **denied even though `python3` is a
granted head** (#401). So the exec bit plus a direct-token grant is what makes a
Python helper cloud-invocable; adding `python3` in front of it un-does that.

The row deliberately measures only whether the harness **let the command run**, not
what it returned: `--iprobe17direct` is consumed as a repo-root path that does not
exist, so the command exits 1 with an `[input-error] git ls-files failed`
breadcrumb in a fraction of a second.

**Consumer of this evidence.** Issue #789's focused-verification tiers depend on
this shape: a `scripts/*.py` / `lib/*.py` change iterates on the covering
`lib/test/test_*.py` named by its coverage-map `focused_test` field, invoked as a
direct leading token so the *same* command works on the local and cloud tiers. Had
the probe come back DENIED, the cloud tier would have kept the full-suite default
and those tiers would have stayed local-only.

### Dispatched-subagent `Write` into `.prflow/tmp/**` — implement tier — MEASURED PERMITTED (issue #858)

`matcher-probe.yml` also carries a **`subagent-write-implement-probe`** job that measures
the same dispatched-subagent `Write` fact on the **implement** tier — because a shape
proven on the review tier is unproven here (the two are separately-probed allowlists). It
is the structural twin of the review-tier job above: it **consumes** the resolved
implement literal from the `implement-probe` job via `needs:` (never a second `IMPLEMENT=`
assignment), appends `Task,Agent` in its own hand-written `--allowed-tools`, dispatches one
built-in `general-purpose` subagent that writes `.prflow/tmp/subwrite-implement.txt`
(the orchestrator writes nothing), and derives the three-outcome verdict with the same
`scripts/subagent-write-probe-verdict.py --tier implement`.

Note the two tiers' row numberings are independent — both contain rows numbered 8 and 9 —
so the verdict record names its tier as data, and the helper carries a machine-consumed
`tier` field for the same reason.

**This measurement is RECORDED**, on the same terms as the review-tier entry above and
from the same run: fired by the same-repo `pull_request` trigger, never dispatched,
version-dependent, re-probe after any `claude-code-action` upgrade. The `tool_use` /
`parent_tool_use_id` pair for this tier is `toolu_01NmqhQw56kRuoGSXdr3e1Ph` →
`toolu_01CAkuq4wZ4x9M82HazPicfF`; `write_chain_ok=yes` and
`side_effect_state=corroborated` against `.prflow/tmp/subwrite-implement.txt`, with
**zero** `permission_denials` entries (so, as above, the denial-entry-shape read stays
outstanding). The resolved implement `--allowed-tools` literal is committed verbatim in
[`docs/internal/subagent-write-probe.observed.md`](subagent-write-probe.observed.md) alongside the
review one. The same `acceptEdits` scope caveat applies: the run carries
`--permission-mode acceptEdits`, so the `PERMITTED` does not isolate the allowlist as the
sole reason the write was allowed.

| Tier | Verdict | Run id | Job id | Head commit | Ref |
| --- | --- | --- | --- | --- | --- |
| implement | **PERMITTED** | `30956039324` | `92149629323` | `85e57ac1c6dcf732a861230f82182191977c6e41` | `issue-1152-command-profile-shape-lint` |

---

## Probe evidence (command tier) (issue #1152)

The `devflow.yml` **command** tier — the manual `/prflow:review-and-fix` /
`/prflow:pr-description` PR-comment path — is a **third** cloud allowlist alongside the
read-only `review` tier and the read-write `implement` tier. Before issue #1152 its
HEADS were scanned (run.sh's whole-bundle head scan against `devflow.yml`'s `TOOLS`) but
its SHAPES were not: `lib/test/run.sh` linted the `review-and-fix` bundle under the
`implement` profile as the closest **inferred** proxy, and `matcher-probe.yml` carried no
command-tier job. On run `29854795625` (PR #684) a `prflow:review-and-fix` comment run
took six Phase-0 permission denials, produced no verdict / commits / comment, and still
exited `is_error=false` — every denial a *shape* refusal on the unmeasured tier.

Issue #1152 closes both gaps:

- **Desk lint.** `lib/test/extract-command-shapes.py --profile command` (rule set
  `COMMAND_RULES` = `CR1`–`CR5`) applies the read-write `implement` tier's denied shapes
  remapped to `CR*` ids (`command`-tier denied shapes ⊆ `implement`-tier denied shapes,
  the assumption the old proxy already rested on; the `command-probe` job converts it from
  inference to measurement). `lib/test/run.sh` drives it over the whole `review-and-fix`
  bundle (root + every `references/*.md`) plus the shared review-engine files it executes
  inline, and goes RED when any teaches a command-profile-denied shape. The unexpanded
  `${CLAUDE_SKILL_DIR:-…}` anchor is deliberately **not** a rule (issue #275 / #1124 — its
  argument-position denial is measured by the probe rows below, not modelled statically).
- **Probe job.** `matcher-probe.yml`'s `command-probe` job measures the tier that ships:
  its `--allowed-tools` baseline is a **generated region** (`region=probe-command`)
  compiled from the `command` profile, banner-stamped with its sha256 exactly as the
  `probe-review` / `probe-implement` baselines are, so it can never drift from the deployed
  allowlist.

**This measurement is RECORDED** — run
[`30956039324`](https://github.com/The01Geek/prflow/actions/runs/30956039324), job
`command-probe` (`92149438683`), head `85e57ac1c6dcf732a861230f82182191977c6e41`, ref
`issue-1152-command-profile-shape-lint`, 2026-08-04. No `workflow_dispatch` was needed:
`matcher-probe.yml` also triggers on a same-repo `pull_request` filtered to its own path,
so the PR that added these rows fired the job itself. The verdicts below are the job's
deterministic step summary, computed from the execution file's `permission_denials`
(DENIED) and recorded `tool_use` inputs (PERMITTED) — the model's prose is never the
measurement. Version-dependent: re-probe after any `claude-code-action` upgrade
(measured against `claude-code-action@v1` with Claude Code 2.1.221).

| # | Shape | Verdict |
|---|-------|---------|
| 1 | granted vendored-literal helper path as a leading token (`config-get.sh`) | **PERMITTED** |
| 2 | resolved (expanded) skill-dir-anchored helper path as a leading token | **DENIED** |
| 3 | `>` redirect from a granted head into `.prflow/tmp/**` | **PERMITTED** |
| 4 | `.prflow/tmp/**` file authored with the **Write** tool | **PERMITTED** |
| 5 | `if VAR=$(granted-helper …)` command-substitution condition | **PERMITTED** |
| 6 | `;`-joined multi-statement sequence | **PERMITTED** |
| 7 | plainly granted single command (positive control) | **PERMITTED** |
| 8 | argument-position defaulted anchor expansion `${VAR:-default}` (reproduces run `30695072336`) | **DENIED** |
| 9 | argument-position bare anchor expansion `${VAR}` | **DENIED** |
| 10 | argument-position bare expansion of a non-anchor variable (control) | **DENIED** |

Each row also carries a per-row evidence triple, reproduced here verbatim from the job's
own emitted summary (machine output, not a paraphrase) so a reader can tell a genuine
refusal from a shape that was never attempted in the form the row names:

```
| 1 | granted vendored-literal helper path as a leading token (config-get.sh) | **PERMITTED** | denial=no; tool_use=yes; shape=ok |
| 2 | resolved (expanded) skill-dir-anchored helper path as a leading token | **DENIED** | denial=yes; tool_use=yes; shape=ok |
| 3 | `>` redirect from a granted head into `.prflow/tmp/**` | **PERMITTED** | denial=no; tool_use=yes; shape=ok |
| 4 | `.prflow/tmp/**` file authored with the Write tool | **PERMITTED** | denial=no; tool_use=yes; shape=ok |
| 5 | `if VAR=$(granted-helper …)` command-substitution condition | **PERMITTED** | denial=no; tool_use=yes; shape=ok |
| 6 | `;`-joined multi-statement sequence | **PERMITTED** | denial=no; tool_use=yes; shape=ok |
| 7 | plainly granted single command (positive control) | **PERMITTED** | denial=no; tool_use=yes; shape=n/a |
| 8 | argument-position defaulted anchor expansion `${VAR:-default}` | **DENIED** | denial=yes; tool_use=yes; shape=ok |
| 9 | argument-position bare anchor expansion `${VAR}` | **DENIED** | denial=yes; tool_use=yes; shape=ok |
| 10 | argument-position bare expansion of a non-anchor variable (control) | **DENIED** | denial=yes; tool_use=yes; shape=ok |
```

Row 7 is the positive control and it passed, so the four refusals are refusals of their
own shapes and not a dead session. Every row recorded `tool_use=yes` and `shape=ok`, so
none is the `REFORMULATED` case the job warns about — each intended shape was actually
attempted.

**Row 2 is the substantive new finding, and it bears on the #1124/#1256 conditional-call
remedy.** The *resolved* traversal form
`.prflow/vendor/prflow/skills/<skill>/../../scripts/<helper>` — what the portable
`"${CLAUDE_SKILL_DIR:-…}"/../../scripts/<helper>` anchor expands to at runtime on this
tier — is **DENIED as a leading token**, while row 1's plain vendored literal
`.prflow/vendor/prflow/scripts/<helper>` is **PERMITTED**. So the matcher does not
normalize `../..` traversal back onto the granted literal. That is direct support for the
remedy's shape: a cloud-reachable call site emits the **granted vendored literal
directly** and keeps the anchor only as the fallback arm; rewriting the anchor into an
expanded traversal would not have worked. (One measurement, `command` tier, one action
version — see the caveat above.)

Rows 8–10 are the argument-position rows adopted from issue #1124's closure; their
cross-reading is applied in *The `${CLAUDE_SKILL_DIR:-…}` anchor* subsection above, which
is the canonical home for that reading.

---

## The redirect-into-`.prflow/tmp/**` rows are QUALIFIED by field evidence (issue #1721)

**Probe rows in this file record a `>` redirect into `.prflow/tmp/**` as PERMITTED** — among them
command-tier shape 3 (run `30956039324`, 2026-08-04, `claude-code-action@v1` with Claude Code
2.1.221) and implement-tier row 11 (run `29623046995`, 2026-07-18). **Field evidence from a later
consumer run refuses a redirect construct into that same tree**, so no such row may be read as a
current guarantee. Note what the field evidence does *not* say: **no refusal below is attributed to a
stdout redirect into `.prflow/tmp/**`.** Row 1's chain did contain three such redirects, but the
harness named its multiple heads as the parts requiring approval; rows 2 and 3 have other causes
entirely. So none of the three refutes that shape on its own, which is why the shipped lint still
treats it as advisory.

**A LATER cloud run does refute it, and this supersedes the paragraph above.** The
`/prflow:review` run `32081921050` (2026-08-17) reported observing a stdout `>` redirect into
`.prflow/tmp/**` refused — `Output redirection … was blocked` — alongside a variable-expansion
denial and a multi-head denial. That is one reviewer-reported observation rather than a
matcher-probe row, so it does not carry a probe verdict's weight; treat the shape as **refused on
the current action version until a probe row says otherwise**, and re-run
`.github/workflows/matcher-probe.yml` before restoring any redirect-shaped recipe. The shipped
lint's stdout arm is unchanged — narrowing it is a separate change with its own fixtures.

**This section supersedes those rows in time; it does not contradict them.** Each recorded what a
real run measured at the version it names, and stays valid as history. What changed is that a later
measurement refuses the same shape — so where this file says PERMITTED of a redirect and says
denied of one, read the denial as the current rule and the permit as the older measurement.

On a cloud `/prflow:implement` run in an adopter repository (GH run `31989737682`,
2026-08-17) three prescribed fences were each refused, and the three refusals have **three
different causes** — a distinction that matters, because a single "the redirect is denied"
reading prescribes the wrong remedy for two of them:

| Refused fence | Harness response | Cause |
|---|---|---|
| the Phase 0 local-diff staging chain | `The following parts require approval: git diff …, awk …, sed -n 'p' …` | a **compound multi-head** refusal; the redirect is incidental |
| `workpad.py acs-resolve … 2>…/acs.err` | `Output redirection to '…/acs.err' was blocked. For security, Claude Code may only write to files in the allowed working directories: '<workspace root>'` | the **redirect construct** itself |
| `printf '%s\n' "$CLAUDE_CODE_SESSION_ID" > …` | `Contains simple_expansion` | a **variable-expansion** refusal, which survives removing the redirect |

**Read the second row carefully: the refused path was INSIDE the workspace root the message
names as allowed.** The guard is on the construct, not the destination, so "write it under
`.prflow/tmp/`" is not a remedy on its own.

**Reconciliation.** The probe rows are not retracted — they record what a real run measured
at the versions named, and a verdict is never rewritten from inference. They are **superseded
as a forward guarantee**: the shape is version-fragile, and the two shapes shipped fences prescribe
as of issue #1721 are `Write(.prflow/tmp/**)` (PERMITTED on both tiers, and for a dispatched
subagent as well) and `| tee` — the former permitted across every measurement, the latter carrying
no per-row verdict transcribed here and refused in no measurement either. Re-probe before restoring any redirect-shaped recipe; **`| tee` is not a substitute
where a producer's exit status must be observed**, because in `producer | tee f | wc -l` the
pipeline reports the last stage's status and the producer's failure becomes invisible.

### Per-occurrence adjudication of the shipped redirect population (issue #1721 AC1)

Scope: redirects into a scratch path under `skills/`, as enumerated by the search below.
Cloud-reachability is decided by which tier executes the fence's phase, so `skills/review/**`
counts as cloud-reachable four times over — the two review tiers, `/prflow:review-and-fix`,
and `/prflow:implement`'s inline Phase 3.3 fix loop all execute that bundle.

**The enumerating search must allow a quoted target, and even the widened form is not complete.**
`grep -rnE '>\s*\.prflow/tmp' skills/` misses `> ".prflow/tmp/…"` entirely — the `phase-3-agents.md`
occurrences were found only after widening it to `[0-9]?>>?[[:space:]]*"?\.prflow/tmp`. That widened
form is the minimum; the narrow one is what produced the incomplete first pass recorded below.

**A third class evades both: a redirect whose target is a VARIABLE.** `> "${AGG}.tmp"` in
`deferred-review-findings.md` and `> "${GIT_SNAP_BEFORE:-…}"` in `phase-3-agents.md` are
cloud-reachable redirects into `.prflow/tmp/…` that no literal-path pattern matches. Enumerate
those by reading each fence's variable definitions, not by grep alone — a count taken from the
pattern alone under-reports this class by construction, which is why the rows above describe the
population rather than pinning a number to it.

**A fourth class evades them too: a target prefixed by a rendered PLACEHOLDER.**
`> "<main-root>/.prflow/tmp/issue-body-<slug>.md"` in `create-issue/references/issue-template.md`
is a real redirect into the scratch tree, but no pattern anchored at `.prflow/tmp` sees it, because
the literal begins with `<main-root>/`. Enumerate this population by resolving each redirect
token's target and testing for `.prflow/tmp` anywhere within it — never by anchoring the pattern at
the start of the target.

| File | Sites | Reachability | Disposition |
|---|---|---|---|
| `skills/review/SKILL.md` | 4 × `2>` | cloud | rewritten — stderr read from the tool result |
| `skills/review/phases/phase-0-setup.md` | staging chain, plus 2 × `2>` | cloud | rewritten — a bare `git diff --name-status` producer ahead of staged `tee` pipelines with per-stage section counts; `acs.err` removed |
| `skills/review/phases/phase-1-checklist.md` | 1 × `>` | cloud | rewritten — `tee` pipeline with a section count |
| `skills/review/phases/phase-4-verdict.md` | 1 × `>`, 1 × `2>` | cloud | rewritten — Write tool; stderr from the tool result |
| `skills/review-and-fix/references/loop-control.md` | 1 × `2>` | cloud (`/prflow:review-and-fix`) | rewritten |
| `skills/review-and-fix/references/loop-exit.md` | 2 × `2>` | cloud (`/prflow:review-and-fix`) | rewritten |
| `skills/implement/references/deferred-review-findings.md` | 2 × `2>` | cloud (`/prflow:implement`) | rewritten — each invocation guarded on its own inline exit status, with the residual ambiguity read from that call's own stderr in the tool result rather than a captured `.err` file |
| `skills/implement/references/deferred-review-findings.md` | 1 × stdout redirect capturing the deferrals-merge jq's output to the variable target `"${AGG}.tmp"` (then `mv`'d over `$AGG`) | cloud (`/prflow:implement`) | **Recorded — not rewritten (issue #1734).** Cause 1 (`simple_expansion`: the `${AGG}` variable target) **and** the Write tool cannot source a command's stdout; `\| tee` is disqualified because the fence's `else` arm reads jq's exit status. See the per-occurrence adjudication below. |
| `skills/implement/phases/phase-1-setup.md` | 4 × `>` | cloud (`/prflow:implement`) | rewritten — Write tool |
| `skills/retrospective-weekly/SKILL.md` | mixed stdout, append and stderr redirects | **local only** — no workflow dispatches this command | **left unchanged** |
| `skills/review/phases/phase-3-agents.md` | dirty-tree snapshot/restore fences, enumerated by a complete redirect-operator search of the fence: 2 × stdout capture to a defaulted-expansion target (`> "${GIT_SNAP_BEFORE:-…}"` and the `…AFTER…` equivalent), 4 × `printf … >>` append inside a `while read` loop (literal target, expanded `"$rec"`/`"${rec:3}"` in argument position), 2 × input redirect to a defaulted-expansion target (`done < "${GIT_SNAP_BEFORE:-…}"`, `done < "${GIT_SNAP_AFTER:-…}"`), 3 × input redirect to a literal target (2 × `tr '\0' ' ' < ".prflow/tmp/…"`, 1 × `done < ".prflow/tmp/…"`), 4 × literal-target stdout write with no expansion (the `printf '%s\n' disabled > ".prflow/tmp/review-dirty-tree-disabled"` sentinel, and the 3 `printf '%s' '' > ".prflow/tmp/review-dirty-tree-{before,changed,renamed}-paths"` scratch-init writes guarded on exit status) | cloud | **Recorded — not rewritten (issue #1734).** Cause 1 (`simple_expansion`) dominates; the input-redirect sites and the 4 literal-target stdout writes are newly enumerated. See the per-occurrence adjudication below. |
| `skills/implement/phases/phase-3-fix-loop.md` | 2 × `--persist` stderr capture to a `$(mktemp)` target — `2>"$PERSIST_ERR"` and `2>>"$PERSIST_ERR"` (the second an append) — each statement additionally led by the unexpanded `${CLAUDE_SKILL_DIR:-…}` anchor | cloud (`/prflow:implement`) | **Recorded — not rewritten (issue #1734).** Cause 2 (the `/tmp` target) **and** the denied anchor leading token. See the per-occurrence adjudication below. |
| `skills/create-issue/references/issue-template.md` | 1 × stdout redirect to the placeholder-prefixed target `"<main-root>/.prflow/tmp/issue-body-<slug>.md"` | **local only** — no workflow dispatches `/prflow:create-issue` | **left unchanged** |

#### Per-occurrence adjudication of the three deferred populations (issue #1734)

Issue #1734 re-opened the three `DEFERRED — not rewritten` rows above with the mandate that **every
occurrence be enumerated by reading each fence's variable definitions — including the input-redirect
sites a literal-path search misses — and each either rewritten or recorded with the reason it cannot
be.** The adjudication below is that record; population A's site set was established by a complete
redirect-operator search of the fence (not only the variable-definition reading), so it also
surfaces the literal-target stdout writes a variable-target reading skips. **Every occurrence
itemised in the population bullets below resolves to recorded-not-rewritten**, because under this issue's four binding constraints — no new allowlist grant; no degradation of the
local/interactive tier (which here includes the extracted-fence test harness); no confirming cloud
measurement is in reach; and `| tee` is not a substitute where a producer's exit status must be
observed — no constraint-satisfying rewrite exists for any of them. Because **no fence byte changed**,
each fence's fail-closed semantics, its error-handling arms, and its local-tier behaviour are
preserved verbatim by construction, and `lib/capability-profiles.json` and the five generated
literals are untouched.

Each disposition names which of the three recorded causes it addresses (1 = `Contains
simple_expansion`, the variable-expansion refusal that survives removing the redirect; 2 = the `/tmp`
probe-denied target; 3 = the compound multi-head `while read` refusal). Per this issue's own AC, a
disposition that left a variable expanded in the executed command is **not** recorded as addressing
cause 1 — none below is, because none rewrites anything.

- **A. `skills/review/phases/phase-3-agents.md` — the dirty-tree snapshot/restore fences.** Enumerated
  by a complete redirect-operator search of the fence — a variable-definition reading alone skips the
  literal-target writes — over `GIT_SNAP_BEFORE`/`GIT_SNAP_AFTER` (default `.prflow/tmp/review-dirty-tree-{before,after}`):
  the 2 stdout captures (`git status --porcelain -z > "${GIT_SNAP_BEFORE:-…}"` and the AFTER
  equivalent), the 4 `printf … >>` appends inside the `while read` restore loops (`"$rec"` /
  `"${rec:3}"`), the 2 defaulted-expansion **input** redirects (`done < "${GIT_SNAP_*:-…}"`), the
  3 literal-target **input** redirects (2 × `tr '\0' ' ' < ".prflow/tmp/…"`, 1 × `done < ".prflow/tmp/…"`),
  and the 4 literal-target stdout writes with **no** expansion — the `printf '%s\n' disabled >
  ".prflow/tmp/review-dirty-tree-disabled"` snapshot-failure sentinel, and the 3 `printf '%s' '' >
  ".prflow/tmp/review-dirty-tree-{before,changed,renamed}-paths"` scratch-init writes chained in an
  `if ! … || ! … || ! … ; then` compound that fails closed on any write's non-zero status.
  The dominant, irreducible cause is **cause 1**. The capture and both defaulted input redirects
  refuse on the `${GIT_SNAP_*:-…}` expansion; the appends refuse on the `"$rec"`/`"${rec:3}"`
  expansion inside a `while read` loop (**cause 3**). Neither can be de-expanded to a bare literal:
  the `${GIT_SNAP_BEFORE:-…}` / `${GIT_SNAP_AFTER:-…}` seam is **load-bearing for the project's own
  test suite** — `lib/test/run.sh` extracts these fences and runs them with `GIT_SNAP_BEFORE=…` /
  `GIT_SNAP_AFTER=…` set to per-test temp paths (including the symlink-attack security tests that
  `rm`/`ln -s` the exact env-named path), so hardcoding the target degrades the local tier, which the
  constraints forbid. The appends cannot use the Write tool (it cannot participate in a per-record
  NUL loop) and the literal input redirects read the same files the writes stop producing, so a
  disposition for the reads is bound to the writes'. A constraint-satisfying rewrite would require a
  committed helper that owns the whole snapshot/restore loop — and because the snapshot is what
  authorises the Phase 3.2 restore, that redesign changes what the restore is entitled to undo, out
  of scope for a mechanical adjudication. The 4 literal-target stdout writes carry **no** cause-1
  expansion, but a shell `>` that authors a file is refused by the cloud implement tier's sandbox —
  observed this run, where a `git diff … > .prflow/tmp/…` write was blocked by the sandbox (which
  refuses shell `>` file authoring) and the same content succeeded only through `| tee`. Of them, the sentinel write is
  the one site the Write tool could author in isolation (fixed literal content to a fixed path), but
  it lives inside the §3.1 snapshot fence whose `${GIT_SNAP_BEFORE:-…}` capture and validation
  statements are already cause-1 denied, so an isolated rewrite of it leaves the fence non-cloud-runnable
  and it is recorded with the rest of the fence; the 3 scratch-init writes the Write tool cannot reach
  either, because the `if !` compound reads each write's exit status to fail the restore closed on a
  scratch-allocation failure — the same exit-status dependency that disqualifies `| tee` for population C.
  Recorded, not rewritten.
- **B. `skills/implement/phases/phase-3-fix-loop.md` — the `--persist` stderr captures.** The two
  sites are `2>"$PERSIST_ERR"` and `2>>"$PERSIST_ERR"` (append), where `PERSIST_ERR=$(mktemp)` —
  **cause 2** (a `/tmp` target). Crucially, each statement *also* leads with the unexpanded
  `${CLAUDE_SKILL_DIR:-…}` anchor, which the cloud matcher denies as a leading token independently of
  the capture, so removing only the `2>` capture leaves the fence just as unexecutable on the cloud
  tier. Making it cloud-reachable would require *both* re-siting the record-write-failure detector
  (the fence maintains `PERSIST_ERR_IS_DEVNULL` and `grep -qE 'record not written|…' "$PERSIST_ERR"`
  — reading `--persist`'s stderr from the tool result instead, as this same file's *other* `2>`
  captures were already rewritten) *and* enrolling both `efficiency-trace.sh --persist` calls in the
  conditional vendored-literal-first anchor-fallback form (per `lib/test/lint-anchor-fallback-arm.py`).
  That is a coupled redesign touching the fence, the `lib/test/run.sh` pins on this exact text, and
  the anchor-fallback lint's enrolled-site set, with **no cloud measurement in reach to confirm the
  substituted shapes are permitted** — the trap this section's constraints exist to avoid. This fence
  is therefore explicitly recorded as left non-cloud-reachable, not rewritten.
- **C. `skills/implement/references/deferred-review-findings.md` — the jq merge's `> "${AGG}.tmp"`.**
  **Cause 1** (the `${AGG}` variable target) plus the Write tool cannot source a command's stdout: the
  merge captures the deferrals-merge jq's output to a temp and `mv`s it over the aggregate, and the
  write-via-temp+`mv` is exactly what makes a concurrent read of `$AGG` safe. Routing the merged JSON
  through the agent's context to author it with the Write tool would reintroduce the transcription
  hazard the engine deliberately avoids for `diff.patch`; and `| tee "$AGG"` is disqualified because
  the pipeline would report `tee`'s exit status, hiding a jq failure the fence's `else` arm reads and
  routes to a `dropped-failed` reflection. As in population B, the merge statement additionally leads
  with the unexpanded `${CLAUDE_SKILL_DIR:-…}` anchor (`if "${CLAUDE_SKILL_DIR:-…}"/../../scripts/run-jq.sh
  … > "${AGG}.tmp"; then`), the cloud matcher's denied leading token — so the fence is non-cloud-reachable
  on that ground too, independently of the redirect. The other `2>` captures in this same file **were**
  rewritten by #1721; only this variable-target, captures-command-output site is recorded here.
  Recorded, not rewritten.

### Post-change confirmation status of the three measured shapes (issue #1721 AC5)

**None of the three is confirmed by a post-change cloud run, and that is the recorded residual.**
No cloud run was made against this branch: the probe workflow is the only channel that measures a
shape on a cloud tier, `gh workflow run` is granted on no profile, and an implement run cannot
discharge that evidence gate without explicit human direction. So each row below states what the
remedy rests on, not a confirmation it does not have.

| Refused shape | Remedy shipped | Status |
|---|---|---|
| the Phase 0 staging chain (compound multi-head) | staged `tee` pipelines, one head chain per statement | **unconfirmed** — rests on `tee` being refused in no recorded measurement, which is weaker than a transcribed permit |
| `2>…/acs.err` (redirect construct) | redirect removed; stderr read from the tool result | **unconfirmed** — the construct is simply no longer emitted, so nothing remains to refuse |
| `printf … > <scratch-dir>/…` (`Contains simple_expansion`) | Write tool authors the marker; no shell expansion | **unconfirmed** — rests on the `Write(.prflow/tmp/**)` grant, PERMITTED on both tiers |

The second row is the strongest of the three: it removes the refused construct rather than
substituting another shape, so it cannot be refused for the recorded cause. The other two substitute
shapes whose permitted-ness is measured but version-scoped. Re-probe after the next
`claude-code-action` upgrade before treating any row as confirmed.

Two population corrections, so a later audit is driven by the per-occurrence reading rather
than by a raw grep:

- **A `grep -E '>\s*\.prflow/tmp'` count over `skills/` includes at least one non-redirect.**
  In `skills/review/SKILL.md` the `<marker-slot>` placeholder ends in `>` immediately before
  a space and a path; it is rendered to `""` or a quoted literal before execution, so the
  executed command carries no redirect there.
- **That same pattern MISSES four genuine cloud-reachable redirects**, because
  `skills/implement/phases/phase-1-setup.md` targets the runtime-resolved absolute
  `<scratch-dir>` rather than the literal `.prflow/tmp`.

---

## Grants are per-HEAD across the whole pipeline (the `paste` war-story)

A repo rule from #363/#401 (**not** an implement-probe row): **grants are
per-HEAD across the whole pipeline, not just the leading token.** One ungranted
head in a tail refuses the entire statement, and it produces **no output**.

**War-story:** `paste` is granted nowhere. An in-PR draft of the reworked fences
ended the label **normalizer** in `| paste -sd, -`, which would have refused that
normalizer statement outright — leaving the resolved labels non-empty but the
**normalized list empty**, so the applies silently did nothing (caught at the
desk). Use the granted `tr` / `sed` / `grep` instead.

Consequence for the label call sites: `devflow-implement.yml`'s generated
`implement` literal grants `apply-labels.sh` / `ensure-label.sh` explicitly, and
**all four label call sites** — Phase 3.1's `PRFlow` provenance apply, Phase 4.0/4.0.5's
`deferred.labels` applies, and Phase 4.1's `Documented` apply — are reworked to
**agent-level single-leading-token calls that read their inputs from printed tool
output** (a shell variable does not survive into a later separate command).

Row I1 (the unexpanded anchor) is **not lint-pinnable on either tier** — every
legitimate helper call keeps the portable `${CLAUDE_SKILL_DIR:-…}` anchor in
source (#275) and resolves it at runtime — so it stays **prose-discipline**.

---

## Implement-profile head guard + inline-engine surface (issue #484)

Phase 3 of `/prflow:implement` runs the review engine **inline** under
`devflow-implement.yml`'s resolved `--allowed-tools` — the `Resolve allowed-tools`
step's hoisted `TOOLS='…'` output (**not** the review profile) — so
**every helper the normal inline flow can reach needs an implement-profile
grant** — the review engine is shared.

`lib/test/run.sh`'s #484 head guard deliberately **over-approximates** that runtime
surface. It drives `extract-command-heads.py` in the **`tools-line` parse
mode** that reads **ONLY** the workflow's resolved `TOOLS='...'` allowlist line —
never the whole file or `.prflow/config.json`, so a `Bash(...)` cited in a YAML
comment is **not** a grant; it fails **closed** on an absent/duplicated line. (Since
issue #1170 the implement region is hoisted into a `Resolve allowed-tools` step, so
`devflow-implement.yml` carries its allowlist on a `TOOLS='...'` line exactly like
`devflow.yml`/`devflow-runner.yml` — the former bespoke `implement-block` mode is
retired.) It runs over all fenced source in:

- `skills/implement/**`,
- `skills/review*/**`,
- the dispatched `skills/requesting-code-review/**` final pass,
- including standalone-only review **Phase 4.4**.

It fails when an audited fenced head is neither granted nor in the exact withheld
list (`gh pr checkout`, `git rev-list`, `mktemp`). A separate suppression list
covers shell builtins + parse artifacts, and a **removal-proof contract** requires
inline `workpad.py` shorthand to **expand to the portable granted helper path**
before emission.

---

## Manifest generation (issue #561)

The five runner/probe allowlist literals are **GENERATED from one versioned
manifest — never hand-edit them.**

### The manifest

`lib/capability-profiles.json`:

- integer `manifest_version`,
- named token `groups`,
- a `readme`,
- exactly the `review` / `implement` / `command` profiles, each composing group
  refs (`@core_review`, `@unix_text_common`, …) + inline tokens into flat ordered
  lists.

Groups are shared across profiles **only where the contiguous token runs are
genuinely identical**; most runs are per-profile.

### The six generated regions

`python3 lib/generate-capability-profiles.py` compiles the manifest into exactly
**six** regions:

1. `devflow-runner.yml`'s **review** `TOOLS='…'`,
2. `devflow.yml`'s **command** `TOOLS='…'`,
3. `devflow-implement.yml`'s `--allowed-tools` **base list** — up to the
   `${{ needs.config.outputs.allowed_tools_extra }}"` splice, which is preserved
   **verbatim** (consumer-facing surface),
4. `matcher-probe.yml`'s `REVIEW='…'` baseline,
5. `matcher-probe.yml`'s `IMPLEMENT='…'` baseline,
6. `matcher-probe.yml`'s `COMMAND='…'` baseline (the `command-probe` job, issue #1152).

Each region carries a **banner comment** with `manifest_version` + the **sha256**
of that region's resolved token list. The banner is placed where it is
syntactically inert and **never contains the byte sequence `TOOLS='`**.

The generator is **python3 stdlib-only** (no `yaml`), reads **no git history**, and
has **no runtime footprint** (a `run.sh` assertion greps the six workflows for zero
non-comment references to it — desk/CI-time only, mirroring
`extract-command-heads.py`). Every defect (malformed manifest, missing/duplicated
anchor, unreadable/unwritable target, a review list that drifts from the lock)
exits **non-zero with a stderr breadcrumb** and leaves every target byte-unchanged
(fail-closed).

### `--check` gates CI

`python3 lib/generate-capability-profiles.py --check` (wired into
`lib/test/run.sh`, so the required **`lib + python tests`** CI job gates it)
byte-compares every region and turns any drift RED with a token-level
**directional** diff — a hand-added workflow token is named as **workflow-side**
with "add it to the manifest and regenerate" (blind regeneration would silently
revert the grant). It exits 0 with empty stdout when every region matches.

### The review-profile security boundary + the lock

**The review profile is a security boundary:** the generated review literal **IS**
the read-only reviewer allowlist (the deny floor filters only appended consumer
extras, **never the base**). So `lib/review-profile.tokens` **locks its exact
resolved token list** — the generator **never writes** it, and **any** manifest
edit (including to a shared group) that changes the resolved review list **fails
closed** until you update that lock **in the same PR**. Widening the reviewer
therefore always needs a **visible diff**.

An **implement-only** grant leaves the review boundary untouched, so
`lib/review-profile.tokens` and the review-region checksums stay byte-identical and
only `manifest_version` moves.

### The `manifest_version` bump rule

**Increment `manifest_version` exactly once in any PR that changes the manifest.**
This is a **review convention, not machine-enforced** (the generator reads no git
history); the **per-region checksums are the machine truth**.

### What stays hand-maintained

Empirical territory is **NOT** generated — the manifest states **policy**, never
**measurement**. The probe's candidate rows, verdict tables, command-shape
verdicts, and the `EXTRAS` config-mirror row in `matcher-probe.yml` stay
hand-maintained.

**Adding a grant** = edit the manifest (+ the lock if it widens review) →
regenerate → the same `--check` gate covers what the retired #450 token-sync pin
used to, plus the review-tier equality that never had a pin.

---

## Grant flows

### Review / command tier

Add the token to the relevant profile in `lib/capability-profiles.json`,
regenerate, update `lib/review-profile.tokens` in the same PR **if** the resolved
review list changes, bump `manifest_version`. Never hand-edit the workflow
literals.

### Implement-tier bundled-helper grant flow (issue #555)

A bundled helper that a `/prflow:implement` fence invokes — the §4.0.5-class
case, e.g. `scripts/discover-deferral-manifests.py` — is granted by adding its
vendored-literal token
`Bash(.prflow/vendor/prflow/scripts/<helper>:*)` (the **row-I2-proven** explicit
leading-token form) to the `implement` profile in `lib/capability-profiles.json`
and regenerating. Because the token carries a `:*` suffix it is a **prefix**
grant over the helper's whole argument surface, so a *new mode* on an
already-granted helper owes no allowlist edit at all — issue #1374 added
`--presence-for-pr N` to this exact helper and regenerated nothing. That **one
edit** rewrites:

- `devflow-implement.yml`'s generated `implement` region — the `Resolve
  allowed-tools` step's `TOOLS='…'` baseline, which `claude_args`'s
  `--allowed-tools` consumes — **and**
- `matcher-probe.yml`'s `IMPLEMENT` baseline

in lockstep — so the probe's baseline can never drift from the tier it is probing —
and the generator's `--check` (driven by
`lib/test/modules/capability-profiles.sh`) enforces it. **Never hand-edit either
workflow literal** to add such a grant.

### Implement-tier repo-internal test grants (issue #789)

**Superseded by issue #1078 (this describes the #789-era state).** These seven tokens
no longer ship in the `implement` profile: they delivered zero benefit in a consumer
(the `vendor-plugin` slice prunes `lib/test`, so none can ever match a PRFlow file
there) while pre-authorizing any consumer file that collided with a PRFlow-chosen
path. Six moved to `.prflow/config.json`'s `prflow_implement.allowed_tools` — the
self-repo-only grant channel (`config.example.json` ships it empty, so no consumer
inherits it): the five `focused_test` targets, plus `coverage_map_guard.py` (still
invoked as a direct leading token by `matcher-probe.yml`'s executable-`.py`-as-direct-leading-token probe row — the `coverage_map_guard.py --iprobe17direct` shape). `test_module_harness.py`
was **dropped** — it is not a `focused_test` target and `lib/test/run.sh` invokes it
only via the `python3 <path>` interpreter head. The paragraphs below are the #789
record, kept for provenance.

The same one-edit flow covers a **repo-internal** helper the implement tier must
run in-env — no vendored literal, because `lib/test/**` is not shipped to consumers
by `install.sh`. Issue #789 added seven such direct-leading-token tokens to the
`implement` profile only:

```
Bash(lib/test/test_python_scripts.py:*)
Bash(lib/test/test_module_harness.py:*)
Bash(lib/test/test_workflow_flight_recorder.py:*)
Bash(lib/test/test_workflow_analyzer.py:*)
Bash(lib/test/test_verification_baseline.py:*)
Bash(lib/test/test_create_issue_context_eval.py:*)
Bash(lib/test/coverage_map_guard.py:*)
```

`manifest_version` went 8 → 9 and the literals were regenerated with `python3
lib/generate-capability-profiles.py`. Two invariants make this an **implement-only**
widening, both asserted by the suite: `lib/review-profile.tokens` is
**byte-unchanged**, and the generated `review` and `command` literals gained **no**
token — only `devflow-implement.yml`'s baked `--allowed-tools` and
`matcher-probe.yml`'s `IMPLEMENT` baseline moved. Each granted file must also carry
the **exec bit in the git index**, or the direct-token form the grant describes
cannot run; `lib/test/coverage_map_guard.py`'s arm 10 checks exactly that for every
`focused_test` a coverage-map entry records, and reports an unestablished mode set
or an unreadable manifest **as unestablished** rather than collapsing it onto a
verdict.

Grant timing is the usual one (#593): these are baked workflow literals rather than
config keys, but the workflow the run executes is the default branch's, so a grant
a PR ships is **inert for that PR's own implementing run** and live for subsequent
cloud runs.

### Config-supplied helper grants and the repository rename (issue #928, deferred half)

`prflow_implement.allowed_tools` is not a generated literal — the `config` job
extracts it as `allowed_tools_extra` with `jq`, and `devflow-implement.yml`'s
`Resolve allowed-tools` step appends it verbatim to the generated `implement`
region (`${TOOLS}${EXTRA}`), so the one resolved string both `--allowed-tools` and
the grounding block quote carries it. Two path shapes reach it, both **measured
emissions** rather than design choices: cloud implement run **30183387509**
(issue #802) recorded 43
permission denials in which the engine invoked bundled helpers as
`/home/runner/work/<repo>/<repo>/scripts/<helper>` (workspace-absolute) and as
`scripts/<helper>` (repo-root-relative), because `.claude-plugin/marketplace.json`
declares `"source": "./"`, so `$CLAUDE_SKILL_DIR` resolves to `<workspace>/skills/<name>`
and the portable anchor's `/../../scripts/` lands at the repository root, never in the
granted `.prflow/vendor/prflow/scripts/` subtree. Both shapes were granted in
response, for each of the 25 helpers.

**Issue #1049 closed this resolution fidelity gap for the implement tier.** The
observation above — this repo's cloud implement run resolving `$CLAUDE_SKILL_DIR` to
`<workspace>/skills/<name>` while every consumer resolves the same shipped bytes from
`.prflow/vendor/prflow` — meant the shipped `.prflow/vendor/prflow/scripts/` helper-path
shape had **no coverage in this repo** (the #824 fidelity gap): a denial a consumer
would hit was invisible here. `devflow-implement.yml`'s `claude` job now runs an
implement-tier-only `vendor_marketplace` step (`scripts/compose-vendor-marketplace.sh`)
that composes a **job-local** marketplace rooted at `./.prflow/vendor` (plugin `prflow`
sourced at `./prflow`) and swaps the repo-root `./` entry in the composed marketplace
list for it, so this repo's implement run now resolves `$CLAUDE_SKILL_DIR` to
`<workspace>/.prflow/vendor/prflow/skills/<name>` — the **same subtree a consumer
resolves**, so the shipped helper-path shape finally has coverage here and a denial in
this repo is a denial there. The composition is best-effort (always exits 0) and
degrades on an absent/partial vendored tree with a `::warning::` naming `prflow_version`.
The tracked `.claude-plugin/marketplace.json`, the baked marketplace baseline literal,
and the **review/manual tiers** are untouched — those still resolve from the repo-root
`./` and continue to exercise the workspace-absolute / repo-root-relative shapes above.
Per the usual grant timing (#593), the workflow change is **inert for its own PR's
implementing run** and live for subsequent cloud runs (verified post-merge).

**The `./` prefix on the emitted marketplace entry is load-bearing, and it is the one
thing no gate in this repo can check.** `claude-code-action` validates every
`plugin_marketplaces` entry it is handed (`base-action/src/install-plugins.ts`): an entry
is treated as a local path only when it begins with `./`, `../`, `/`, or a Windows drive
prefix, and anything else must match its `^https://….git$` marketplace-URL regex. The
first shipped version of this step emitted the bare relative `.prflow/vendor`, which
matched neither arm, so the action aborted **every** cloud implement run in this
repository with `Invalid marketplace URL format: .prflow/vendor` (PR #1137, reverted
by #1144 forty-six minutes later). That validator executes only inside a real cloud run:
the desk suite, the CI shards, and the review engine all pass a change that breaks it —
#1137 was reviewed clean across four rounds and CI-green with zero skips. This belongs in
the same class as the matcher semantics documented elsewhere on this page: **a runtime
contract with an external action, provable only by a real dispatch.** A change that alters
the inputs handed to `claude-code-action` wants a canary run at merge time. The
normalization now lives in `compose-vendor-marketplace.sh` at the single point that emits
the entry, and `lib/test/run.sh` asserts the emitted value satisfies the action's
local-path predicate — which narrows the gap without closing it, since it re-states the
validator rather than executing it.

**The workspace-absolute literal embeds the repository name twice.** A rename moves
`$GITHUB_WORKSPACE`, every such token stops matching, and — per this tier's defining
property — an ungranted head is **silently denied**. The failure mode is a run that
quietly does less, with no error to read.

The `config` job therefore **re-anchors** that prefix onto the live
`$GITHUB_WORKSPACE` before splicing, the same transform `matcher-probe.yml` applies
to its own baseline. The transform is a **no-op today** (the workspace already equals
the literal the tokens carry), rewrites only GitHub's hosted-workspace shape (a
deliberate `Bash(/usr/local/bin/foo:*)` grant is untouched), and selects an identity
branch on an empty workspace rather than emitting a root-anchored token that would
match nothing. `lib/test/run.sh` drives the jq program **extracted from the workflow
itself**, so the assertions cannot drift from the shipped expression.

**Evidence status of the two shapes — neither grant form is probe-proven.** Read this
before citing them:

| Grant form | Probe status |
| --- | --- |
| `Bash(.prflow/vendor/prflow/scripts/<helper>:*)` — vendored literal | **PERMITTED**, implement-tier **row I2**, leading-token position |
| `Bash(<workspace-absolute>/scripts/<helper>:*)` | **Unmeasured.** No implement-tier row exercises it. The review tier's absolute-path row (shape 13) is **unrecorded**. |
| `Bash(scripts/<helper>:*)` — repo-root-relative, explicit exact path | **Unmeasured.** No row at either tier grants the exact path and exercises it. Review shape 15 measured the *glob* `Bash(scripts/*.sh:*)` as DENIED (run 29135163829); review shape 14 is the *ungranted* control. Neither measures an explicit exact-path repo-root grant. |

Row I2 is about the **vendored-literal** form and must not be cited as evidence for
either of the other two. The two config-supplied families are a hedge placed in
response to a measured denial, not a measured grant — the re-anchoring above keeps
the absolute family alive across a rename precisely because the relative family
cannot be relied on to cover for it. Closing the gap needs two `implement-probe`
rows (an explicit exact-path repo-root grant, and a workspace-absolute grant), each
exercised as a leading token; until such a dispatch is recorded, treat both as
`unestablished`.

### The install.sh-vs-vendor-fetch skew warning

The **workflow grants** ship to consumers via `install.sh` **file-copy**, while the
**skill rework** ships via the `prflow_version` **vendor fetch**. These are **two
independently-updated artifacts** whose skew silently **re-denies the applies**, so
**the two halves must be upgraded together** (docs: `docs/internal/install.md`,
`docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md`).

## PreToolUse shape guard (issue #805)

`lib/test/extract-command-shapes.py` turns a denied-shape review fence RED **at the
desk**; a runtime consumer makes that desk lint *incomplete* — it does not stop the
engine re-emitting a denied shape live. `scripts/pretooluse-shape-guard.py` is that
runtime consumer: a `PreToolUse` hook for the review tier that **denies** a Bash command
whose any statement matches a probe-proven denied **arm** and returns a
`permissionDecisionReason` naming the permitted alternative, at the moment of the
offending call. It resolves through `extract-command-shapes.py`'s arm-level
`classify_arms()` because the deny set is defined over **arms**, not rule ids
(`classify()` collapses R3's two arms onto one token).

**Registration shipped (#908), but the guard is inert because its delivery tier lost its
caller (#936).** What is shipped is the guard body, its unit coverage, its hardening from
the trusted base ref, and — under #908 — the review-tier registration itself:
`devflow-runner.yml`'s "Run Claude Code" step carries a `settings:` input that registers a
`PreToolUse` / `Bash` hook resolving `pretooluse-shape-guard.py` at the vendored path
(with a repo-root fallback) and failing open — exit 0 — when neither copy exists. That
registration is made safe by the **unconditional** `Harden PreToolUse guard closure`
step (`harden_guard`), which materializes a trusted-base copy of the guard so no PR-head
copy of it can execute in the secrets-bearing review job; membership of the guard's path
in the `#458` `HOOK_TARGETS` closure alone is **not** that mechanism, because
`harden_hooks` can skip entirely.

The **second** registration channel — a `PreToolUse` key in the committed
`.claude/settings.json` — is deliberately still absent, and by design rather than
oversight: the harness denies agent writes under `.claude/`, so #908 records it under
"Maintainer prerequisite (NOT an acceptance criterion)" and instructs an implementing run
to neither attempt it nor report Blocked on it. So it is **not** the case that the two
channels must land together; the shipped state is exactly one of them, intentionally.

The guard is nevertheless inert on `main` — but the reason is the delivery tier, not the
registration. `devflow-runner.yml` declares `workflow_call:` as its sole trigger, and its
only caller, `devflow-review.yml`, was deleted under #936 (which withheld the automatic
pull-request-triggered review tier), so no workflow in the tree invokes it; the `settings:`
registration rides on a reusable workflow that nothing calls. Because the tier cannot run,
every runtime behavior described below is the guard's implemented contract, not observed
behavior.

#### Decision (issue #1047): RETAINED-BUT-INERT — the guard is not wired onto a live tier

`#805` registered the guard on the review tier only and called that an explicit *"not
yet"*, deferring the wiring question; `#919` recorded it as outside its own scope, and
`#1795` was closed unimplemented naming `#1047` as its home. This is that decision, and it
selects **option (b)**: the guard stays registered where it is, inert in this repository,
and no live tier (`devflow.yml`, `devflow-implement.yml`) registers it. Four reasons:

1. **The measured problem gained a live control the guard no longer has to provide alone.**
   `#805` existed because an agent re-emitting a denied shape had nothing telling it the
   permitted alternative until the refusal arrived. Since `#1170`, every tier's prompt
   carries the resolved allowed-command list up front, rendered by
   `scripts/render-grounding-block.sh` from the same hoisted `TOOLS` output the run's
   `--allowed-tools` resolves from. That is a weaker control than a deny at the moment of
   the call, and it is not a substitute — but it moves the guard from *the* mitigation to
   *an additional* one, which is what makes the cost below decisive rather than marginal.
2. **Wiring onto the implement tier is new work, not a parameter change.** There is no
   `_IMPLEMENT_ARM_TABLE`: `lib/test/extract-command-shapes.py`'s `classify_arms()`
   iterates `_REVIEW_ARM_TABLE` and nothing else, and `find_implement_violations()` is a
   markdown-fence scanner over a whole file, not the pure statement classifier a hook can
   call on one Bash payload. Reusing the review deny set is refused outright — it would
   police that tier by the wrong rules while leaving its own shapes uncovered.
3. **Two of the five implement arms are deny-INELIGIBLE on their own evidence.** `IR4` (a
   leading `cd`) is an authoring rule and not a claimed matcher refusal — a leading `cd`
   was observed *executing* on the review tier (run 30222310785) — and `IR5` rests on a
   proven-permitted alternative rather than on a measured denial of its own arm. A runtime
   deny is terminal, so denying either would cost the engine a shape the harness permits:
   exactly the cost that excluded `R2` and `R3-heredoc` from the review deny set.
4. **The unknowns that once gated option (a) are answered, and none of them argues the
   guard is needed.** The hook fires through the `settings:` input (`#919`, run
   `30956039324`, replicated 8×) and delivers its `permissionDecisionReason` on a `deny`
   (run `30967680822`, `REASON-DELIVERED`); the input lands at USER scope alongside the
   base-restored project `.claude/settings.json`, so the three `Stop` hooks keep applying
   (source read recorded beside `devflow-implement.yml`'s own `settings:` input). Those
   answers establish that the guard *could* be wired, not that it *should* be.

**Option (a) is closed, not parked.** What would reopen it is evidence, not opinion: a
sustained non-zero `permission_denials_count` on implement runs after `#1170`'s grounding
block, or a repeat of the `#805` failure mode (a run re-emitting one denied shape until it
exhausts its budget) on a tier that runs. Either would be measured through
`scripts/surface-execution-diagnostics.sh`, which publishes that count — or the literal
`unavailable` — on every implement run.

**Deletion was considered and refused.** The guard is downstream of the withheld tier, and
per `CLAUDE.md`'s retention rule the criterion is resolvability from an installed consumer
copy, not reachability from this tree: a consumer that installed before `#937` still has
its own `devflow-review.yml` calling `devflow-runner.yml`, and re-running `install.sh` to
pick up a newer `prflow_version` keeps that workflow while vendoring the plugin it calls
into. Deleting the guard body would leave that copy calling a file the vendored slice no
longer carries.

**Consumer-runner caveat for that retained population (recorded with this decision).** The
registered hook command probes for the guard *script* and exits 0 when it is absent, but
until this decision it did not probe for the *interpreter*: it ended in `exec python3`,
which exits 127 on a host with no `python3` on `PATH` — routine on a self-hosted Windows
runner, which is why this repository ships `scripts/provision-python3-shim.sh` at all. The
guard's own `main()` records that a non-zero `PreToolUse` exit is a block rather than a
fall-through, so on such a host the failure was not a quiet no-op. The hook command now
carries `command -v python3 >/dev/null 2>&1 || exit 0` so a missing interpreter fails open
the same way a missing script already did. Note the asymmetry this closes is in the *hook
command*, which reaches a consumer only through `install.sh`'s workflow copy, not through
the `prflow_version` vendor fetch — so a consumer that upgrades the plugin without
re-running the installer keeps the unguarded command.

### The deny set and each arm's permitted alternative (authoritative)

This table is the **authoritative** record of each denied arm's permitted alternative;
`scripts/pretooluse-shape-guard.py`'s `REMEDIATION` table is its **mirror**, and a
`lib/test/run.sh` assertion pairs each arm's row here with the guard's row for the same
arm, so a change on one side reconciles the other in the same commit (the same
coupled-mirror discipline the closure literals carry, applied to a `scripts/`-to-`docs/`
pair). Both sides are extracted **by arm id** — this document's table row for the arm, and
the guard's `REMEDIATION` entry for the arm — never by a whole-file substring test, which
could not distinguish the row it claims to pin from any other mention of the same literal
and would be inert.

**The join literal differs by arm, and is deliberately not re-quoted in this paragraph**
(a second copy outside the row would defeat the row-scoped extraction). `R1` and `R3-tmp`
each join on a whitespace-free fragment of their own permitted-alternative cell, so
editing either alternative cell alone turns the suite RED. `R4` joins on its
**denied-shape** cell instead, because its alternative is a whitespace-bearing English
phrase that the issue-810 boundary classifies as markdown prose and so may not be pinned;
editing the `R4` **alternative** cell alone does **not** turn the suite RED — reconcile
that one by hand.

| Arm | Denied shape | Permitted alternative (the join key is the arm id) |
| --- | --- | --- |
| `R1` | a leading `VAR=value` assignment or env-prefix (`M=x cmd`) | capture a command's output with `VAR=$(cmd)`, or pass the value as an argument |
| `R3-tmp` | a `>`/`>>` redirect targeting `/tmp` | author the file with the Write tool under `.prflow/tmp/`, or stream through a pipe into `tee` |
| `R4` | an interpreter head (`python3/python/node`) | invoke the helper directly by its granted path as the command's **leading token** |

**Excluded arms (a runtime deny is terminal, so denying a permitted shape costs the
engine a working shape):** `R2` (a leading `cd`, DROPPED as unproven/confounded — probe
row 3) and `R3-heredoc` (an in-workspace `cat`-headed heredoc write, banned as authoring
discipline, not a probe result). The guard reports **no decision** on these — exit 0 with
empty stdout — and emits no `permissionDecision` token at all. It does **not** emit
`defer`: Part 2 below measured that token blocking the tool and ending the process rather
than falling through.

### PreToolUse probe evidence (Part 1)

**The probe arm shipped under #908.** `.github/workflows/matcher-probe.yml` carries a
`pretooluse-probe` job that registers its own ad-hoc `PreToolUse` / `Bash` hook via a
`settings:` input and writes a `pretooluse-probe-fired` marker. It is designed to
establish, by observation, whether a `PreToolUse` hook fires under `claude-code-action`
(`FIRED`/`NOT-FIRED`) and whether its `permissionDecisionReason` reaches the engine
transcript (`REASON-DELIVERED`/`REASON-ABSENT`).

**The arm was never awaiting a dispatch, and the results were already there.**
`matcher-probe.yml` triggers on `workflow_dispatch` **and** on a same-repo
`pull_request` filtered to its own path, so every PR touching that workflow has fired
the job — the results simply had not been read back. The row below is transcribed from
run [`30956039324`](https://github.com/The01Geek/prflow/actions/runs/30956039324), job
`pretooluse-probe` (`92149438739`), head `85e57ac1c6dcf732a861230f82182191977c6e41`,
ref `issue-1152-command-profile-shape-lint`, 2026-08-04.

The fourth column stays `n/a` by **#919's own record**: the once-planned per-arm
review-run denial count against the run-`30138268273` baseline was **dropped** as no
longer achievable — no live tier can produce a review run carrying the guard (the
guard's registration rode on `devflow-runner.yml`, whose sole caller `devflow-review.yml`
was deleted by PR #937 / issue #936) — and that baseline run id is retained as historical
reference only.

**No `workflow_dispatch` was needed for this row, and the premise that one was is false.**
The self-firing trigger above is why observations accumulated with nobody ever dispatching
the arm. **What makes such a row attributable to `main` is the observing run's TREE, not
its event type:** the question to ask is whether that run's head matched `main` for
`.github/workflows/matcher-probe.yml` when the observation was taken. For this row the
check was made on 2026-08-04 against the then-current `origin/main` at head
`85e57ac1c6dcf732a861230f82182191977c6e41` and returned an empty diff. **That check is
itself a past-time observation and does not re-derive** — PR #1308 has since added the
hook-surface arms to the same workflow, so re-running the check today compares against a
later `main` and is expected to differ. A row's provenance is the head sha it records,
never a diff against whatever `main` has become.

Residual, stated rather than hidden: every observation here arrives on a `pull_request`
event, and a `workflow_dispatch` would differ in context (no pull request, no `.claude/`
restore step) — but the hook reaches the session through the `settings:` input written at
**user** scope, so the mechanism being measured is the same either way.

| Probe run id | Firing verdict | Reason-delivery verdict | Per-arm denial counts (review run) |
| --- | --- | --- | --- |
| `30956039324` (job `92149438739`) | **FIRED** | **REASON-ABSENT** | n/a — dropped post-#937 |

**This is the 8th consecutive identical `FIRED` / `REASON-ABSENT` pair.** The six prior
replications — each re-read from its own job log, each triggered by `event=pull_request`,
each concluding `success`, and each returning the same pair — are, newest first:
`30658648601`, `30657675722`, `30652958122`, `30577692232`, `30472371076`, `30421703361`.
The **three oldest** (`30577692232`, `30472371076`, `30421703361`) render the breadcrumb
path as `.devflow/tmp/…` rather than `.prflow/tmp/…` — a pre-#1002 rename spelling of the
same marker, not a different measurement.

**Scope caveat — the `REASON-ABSENT` cell does not mean reason delivery is broken, and
the row misleads without this.** The probe's own hook emits
`permissionDecision: "allow"`, and per the Claude Code hooks decision-control table
`permissionDecisionReason` is shown to Claude on `deny`, shown to the user on `ask`, and
**ignored on `allow` and `defer`**. `REASON-ABSENT` is therefore the *specified*
behavior for the decision this probe emits. This arm therefore cannot speak to the deny
path at all — measuring it needs a hook that emits `deny`. **Arms that do emit one have
since settled it:** see *Harness hook-surface probe evidence (Part 2)* below, which
records `REASON-DELIVERED` on a real `deny` and `DEFER-BLOCKED` on a `defer`.
`REASON-ABSENT` here and `REASON-DELIVERED` there are not in conflict; they measure
different decisions.

**Secondary caveat:** the observation helper searches the **execution file**, which is a
proxy for the transcript rather than a capture of the model's own input; an absent
string there is evidence about the execution file's contents, not a direct reading of
what the model saw. Measured against `claude-code-action@v1` with the CLI version the
run reports (Claude Code 2.1.221) — **re-probe after any upgrade.**

### Harness hook-surface probe evidence (Part 2) — `PermissionRequest`, a hook `deny`, and `defer`

**This subsection is a past-time observation of two specific runs, not a re-derivable
figure.** Each verdict was computed by that arm's own deterministic renderer
(`scripts/describe-permissionrequest-probe.sh`,
`scripts/describe-pretooluse-deny-probe.sh`, `scripts/describe-defer-probe.sh`) from
on-disk markers and the execution file, and read once from the job's step summary — the
model's prose is never the measurement. The run ids, job ids, verdict tokens and observed
CLI version below are frozen history: they are never "corrected" or re-measured, and a
re-probe records a NEW row rather than editing one of these.

PR #1308 added three `matcher-probe.yml` jobs answering three questions the
`pretooluse-probe` arm above structurally cannot: whether the `PermissionRequest` event is
delivered at all under `claude-code-action`, whether a `PreToolUse` **`deny`** is honored
and its `permissionDecisionReason` reaches the transcript, and whether **`defer`** falls
through to the normal permission flow.

Primary run: [`30967680822`](https://github.com/The01Geek/prflow/actions/runs/30967680822),
ref `hook-probe-arms`, head `24976a83320dbe05242870d7c83573dbabe14a5d`, 2026-08-05. Every
verdict below **replicated** on run
[`30971649121`](https://github.com/The01Geek/prflow/actions/runs/30971649121) (head
`e2c9be7ea5f47ae2e00c3347528a6a596a18b8e0`, that branch's final head before #1308 merged),
reporting the same CLI version.

| Arm (job) | Primary run / job id | Verdict | Observed CLI version |
| --- | --- | --- | --- |
| `permissionrequest-probe` | `30967680822` / `92185120595` | **NOT-FIRED** — delivered on neither the granted nor the ungranted call | `2.1.222` |
| `pretooluse-deny-probe` | `30967680822` / `92185120507` | **DENY-HONORED** + **REASON-DELIVERED** | `2.1.222` |
| `defer-probe` | `30967680822` / `92185120496` | **DEFER-BLOCKED** + **STOP-REASON-DEFERRED** | `2.1.222` |

**The `PermissionRequest` verdict is an ESTABLISHED negative, not an inconclusive one, and
these are the facts that establish it.** A hook that did not fire is ordinarily
indistinguishable from a hook nothing was ever offered to, so the arm is built to separate
the two, and every separating fact came back positive:

- **The registration was accepted.** The job log records the action parsing the `settings`
  input as JSON, merging it, and saving the settings file — so the hook was installed, not
  silently dropped for a malformed input.
- **The granted control executed** (`CONTROL-RAN`).
- **The ungranted arm was really issued** (`ATTEMPTED` — a recorded tool-call input carries
  it) and **the harness refused it** (`UNGRANTED-REFUSED` — its side effect is absent),
  with one `permission_denials` entry naming that command. So a call the allowlist did not
  resolve genuinely reached the permission system and was declined.
- **The session continued past the arm** (`AFTER-CONTROL-RAN` — the granted control the
  prompt places *after* the ungranted command also ran), so this is not a session that
  stopped early.
- **The hook wrote no breadcrumb on either call**, and the deny `message` sentinel never
  appeared in the transcript (`SENTINEL-ABSENT`).

The renderer's own inference line states the conclusion: a call the allowlist did not
resolve did reach the permission system and was refused, yet no hook breadcrumb exists —
evidence that the installed CLI does not deliver a `PermissionRequest` event, not merely
that nothing was ever offered to one.

**It did not fire on the granted control either, and that was the specific dangerous
configuration under test.** An unconditional-deny `PermissionRequest` hook is harmless only
if the event sees solely the calls the allowlist did not resolve; if it resolved earlier it
would also see calls the allowlist would have approved, and such a hook would silently
block granted work. The arm therefore attempts a granted control alongside the ungranted
one, and two recorded facts rule that case out together: the granted control **ran**, and
the deny sentinel is **absent** from the transcript. The hook emits its deny after the
breadcrumb write and independently of it — the two are `;`-joined in the job's hook command
— so a hook that fired but could not record would still have denied the granted control,
which did not happen. The breadcrumb write is best-effort, which is exactly why the negative
rests on these facts rather than on the breadcrumb's absence alone.

**A `PreToolUse` `deny` IS honored, and its reason IS delivered.** The
`pretooluse-deny-probe` hook is command-scoped — a `case` over its own stdin payload — and
denies only the sacrificial command. Recorded: `FIRED-AND-DENIED` (both hook breadcrumbs
present, so the hook ran and took its deny arm), `DENY-HONORED` (the sacrificial command's
side effect is absent, so the tool did not execute), `CONTROL-RAN` (the non-matching control
was left alone, so the block is the hook's own scoping rather than a blanket refusal), and
**`REASON-DELIVERED`** — a string carrying the probe's `permissionDecisionReason` sentinel
is present in the execution transcript. That is the delivery mechanism a per-call
remediation depends on, and it works.

**This is the axis the `pretooluse-probe` arm structurally cannot answer**, and its row is
read alongside this one rather than reconciled with it. That arm's hook emits
`permissionDecision: "allow"`, so its `REASON-ABSENT` cell measures the `allow` path only.
The live hooks reference describes the reason field as feedback Claude sees on `"deny"`
("Block the tool call. Claude sees the `permissionDecisionReason` as feedback") — the
decision this arm emits and that one does not.

**A hook-issued deny is visible to a denial count, but its reason text is not.** Two cells
over the same array answer different questions, and only both together are the finding:
**`COMMAND-RECORDED`** — a `permission_denials` entry names the denied command, so a
denial-count measurement does see that the hook fired — while `HOOK-DENY-NOT-RECORDED`
(count 1) records that no entry carries the reason sentinel. The array therefore establishes
*that* a hook denied a command, never *which* rule denied it; reading back the arm needs a
source other than that array.

**`defer` does not fall through — the tool was blocked and the process terminated.**
`DEFER-BLOCKED`: the hook fired and the single command's side effect is absent, so the tool
did not execute. Corroborated by `STOP-REASON-DEFERRED` (the transcript carries
`tool_deferred`), with `permission_denials` entries: 0. The command's head was **granted**,
so under a fall-through the normal permission flow would have permitted it and it would have
run.

**The documentation and the measurement disagree here, and that is recorded rather than
papered over.** The live Claude Code hooks reference (`https://code.claude.com/docs/en/hooks`
— itself a moving page, so this is a past-time reading, 2026-08-05) documents the value as:
*"`"defer"` | Skip this hook's decision and continue to the next hook or the normal
permission flow"*, and describes the silent form the same way: *"Exit code 0 with no output
means the hook has no decision to report, so the tool call continues through the normal
permission flow."* The measurement contradicts that for the emitted-token form.
**For this harness the measurement governs.** The consequence is not cosmetic: a documented
fall-through that in fact blocks the tool and ends the process turns a fail-open path built
on it into a fail-CLOSED one. No claim is made here about `defer` on any other CLI
build or runner — this is a claim about what `claude-code-action@v1` installed on the two
runs above. `scripts/pretooluse-shape-guard.py` already absorbs it: its fall-through emits
nothing at all — exit 0 with empty stdout, the shape the documentation and the measurement
agree on — and it emits no `defer` anywhere.

**All three verdicts expire, and the CLI version beside each one is why.**
`anthropics/claude-code-action@v1` is a **floating** ref: it installs whatever CLI it
currently pins, so each row measures one harness build rather than a standing property.
Both runs reported `2.1.222`. **Re-probe the arms in the table above after any
`claude-code-action` or CLI upgrade** before relying on any of them. Re-probing needs no
new authoring: those jobs are on `main` since PR #1308, and `matcher-probe.yml` triggers on
`workflow_dispatch` as well as on a same-repo `pull_request` filtered to its own path.

## Denial-population audit — the 2026-08-02 implement runs (issue #1135)

**This section is a past-time observation of two specific runs, not a re-derivable
figure.** The counts and command entries below were read once, on 2026-08-02, from the
`claude`-job execution-diagnostics detail blocks of two cloud implement-tier runs. They
are **not** machine-rendered and must not be "corrected" or re-measured later — a run's
diagnostics block is immutable history, and a different run would show a different
population. That immutability covers the **observations** (the counts, the entries, and the
entry indices), not the **classification**: the cause and disposition assigned to an entry
are ordinary claims, correctable on evidence like any other. Probe-based *shape* conclusions
are not made here; they belong to
`matcher-probe.yml` — and where a refusal is shape-level but no already-documented shape
rule covers it, the property is left **unestablished** rather than inferred. This audit
reads the denials, names each entry's cause, and records one disposition per cause.

Source runs (both cloud implement tier, 2026-08-02):

- **Run 30738761826** (issue #1073) — block opened `51 permission denial(s) with detail:`;
  the run recorded `"num_turns": 228` and ended Blocked. The work in flight was a
  `scripts/provision-local-settings.sh` change, and most denials are the agent's
  ad-hoc verification probes of that script (running it in temp dirs, diffing its output).
- **Run 30738987528** (issue #1085) — block opened `9 permission denial(s) with detail:`;
  the run ended with a green pull request.

**How every grant-state claim below was established.** Each "granted" / "not granted"
statement in this section was read from the *run's own* resolved allowlist — the
`--allowed-tools` string in that run's `claude` job log, which is the list the matcher
actually applied (both runs resolved 210 tokens). That is deliberately not a citation of a
commit or of the tree as it stands now: the grant channel is trigger-time-resolved from the
default branch, so today's tree is not what a past run had, and a SHA decorating a grant
rots.

Grant-state context that keeps the dispositions honest: run 30738761826's own resolved
allowlist already carried `Bash(bash:*)` and `Bash(mktemp:*)`, yet `bash -c`- and
`mktemp`-bearing commands still appear in its denial block. That is the load-bearing
observation of this audit: **the population is dominated by deliberately-denied composite
*shapes* (a leading `cd`, a heredoc write, a leading assignment, a `/tmp`/file redirect, an
interpreter head, a background launch), which the matcher refuses regardless of whether
every head in them is granted.** Granting more heads would not have prevented them.

**A granted head is not a permitted command, and the two are separate findings.** The
diagnostics block names the refused command and nothing else — it carries no per-denial
reason string. So an entry is recorded as an **ungranted head** only when a head or leading
literal in it was absent from that run's resolved allowlist. When *every* head and literal
in an entry was present, it is recorded as a **shape refusal**; and when no already-
documented denied shape covers it, the specific property the matcher refused is recorded as
**unestablished** rather than replaced with a plausible guess.

### Named causes and dispositions

Every disposition is drawn from the issue's closed set of three — a prompt-surface
correction, a manifest grant, or a recorded "no change" carrying its reason. **The audit
reaches no new grant and no prompt-surface correction: every cause is dispositioned "no
change."** One of those "no change" rows records that the grant its entries called for
landed independently (issue #1132) — not that the head should stay ungranted. The reasons
follow.

In the *entry indices* column, **A** is run 30738761826 and **B** is run 30738987528, and
each number is the 1-based position of that entry within the run's detail block. The
indices partition every entry of both runs (A: 1–51, B: 1–9); each row groups the entries
by the construct the agent typed, and the two rows where that grouping does not coincide
with the refusal cause say so and split their entries explicitly.

| Cause | Runs / entry indices | Disposition |
| --- | --- | --- |
| **Heredoc write** (`cat > <file> <<'…'`) | A: 1,2,3,4,20,21 | **No change.** A heredoc redirect write is a deliberately-denied shape (#401); the authorized alternative — the Write tool — is already documented. No prompt surface authors a **`cat`-headed heredoc write** — the `R3-heredoc` shape above, which is the one these six entries are. The qualifier is load-bearing: surfaces *do* author heredocs, but they feed command substitution or stdin rather than a file redirect (`BODY=$(cat <<EOF … EOF)` in `skills/implement/phases/phase-3-review.md`; the `--body-file -` and `--ledger-stdin` heredocs in `skills/create-issue/references/`), and the one file-authoring heredoc they sanction is the `tee <file> <<'EOF'` form (`skills/review/SKILL.md` Phase 0.3.5), a different shape from the `cat`-headed redirect these six entries are — note this page transcribes **no** per-row probe verdict for it (shape 6), so it is cited here as the form the surfaces author, not as a measured permission. Granting the `cat`-headed form would defeat the shape ban. |
| **Leading `cd`** | A: 5,6,7,22,23,24,25,26,27 | **No change.** The working-directory contract already bans a leading `cd` (desk lint `IR4`, issue #855); the persistent cwd makes it unnecessary. Agent-improvised; no surface authors it. |
| **Leading `VAR=` assignment / env prefix** | A: 11,12,13,14,15 · B: 3 | **No change.** A leading assignment is the R1/PreToolUse-guard denied arm; the documented alternative is `VAR=$(cmd)` or passing the value as an argument. Agent-improvised. |
| **`bash <path>` / `bash -c` wrapper** | A: 10,17,18 | **No change.** The `bash <path>` wrapper is deny-floored by policy and documented; helpers are invoked as leading tokens. `Bash(bash:*)` was in the run's own resolved allowlist yet these still denied — confirming the refusal is the wrapping shape, not the head. |
| **`nohup … &` background launch** | A: 36,37,38,39 | **No change.** These carry both defects: `nohup` is absent from the run's resolved allowlist (an ungranted head) *and* a background launch is a denied shape. The coordinator `lib/test/run-parallel.sh` is documented to run as a bare leading token "with nothing around it"; backgrounding it is agent improvisation, and the extension already states the correct form. |
| **Interpreter head** (`python3 …`, `python3 -c`) | A: 8,34,35,42,43,44 | **No change — and no grant was missing.** `Bash(python3:*)` *was* in the run's own resolved allowlist, so none of these six is an ungranted head; each additionally carries a caller-side redirect (A: 8 also writes under `/tmp`). They are therefore the cleanest evidence in this population for the head-versus-shape distinction above: the `python3 <path>` interpreter head is refused by shape (#789/#401) with the head granted. The authored form is the executable `.py` as a direct leading token — `scripts/workpad.py`, itself granted in this same run. |
| **stdout/file redirect** (`> <file>`, `> /tmp/…`) | A: 9,46 | **No change.** A caller-side redirect is denied even into `.prflow/tmp` (PR #694); the Write tool is the authorized path and is documented. Agent-improvised. |
| **Ungranted at run time, granted since — `lib/test/run-shard.sh`** | A: 33,50,51 | **No change by this audit — the grant these entries called for has already landed.** The head was absent from run 30738761826's own resolved allowlist, so these three were genuine ungranted-head refusals *at run time*. It does not follow that the absence was correct: `.prflow/prompt-extensions/implement.md` in that run's own checkout already named `lib/test/run-shard.sh --list-shards`, so there was an authored caller and no grant — precisely the grant-timing case that extension itself describes. Issue #1132 subsequently granted `Bash(lib/test/run-shard.sh:*)` in both `prflow_implement.allowed_tools` and `prflow.allowed_tools`, and `CLAUDE.md`'s cloud-implement tier section names its durable caller: decomposing the partition through the shard dispatcher when the tier's per-command execution ceiling terminates the coordinator. So this audit adds no grant because the right grant already exists — not because the head should stay ungranted. |
| **Ungranted head — `git write-tree`** | A: 31,32,41 | **No change.** Absent from the run's own resolved allowlist, so a genuine ungranted head. A one-off introspection of the git tree with no authored caller; the run needs no tree hash. |
| **Granted head, shape refusal — `git diff <sha> <sha> -- …`** | A: 30 | **No change — and not an ungranted head.** `Bash(git diff:*)` was in the run's own resolved allowlist. The fence carried a caller-side `>` redirect into `.prflow/tmp`, a `\|\| true`, and a `\| wc -l` tail — a denied redirect shape inside a compound, so no grant would have permitted it. It is still an ad-hoc historical diff no surface authors. |
| **Granted head, shape refusal — `awk`** | A: 16 | **No change — and not an ungranted head.** `Bash(awk:*)`, `Bash(grep:*)` and `Bash(head:*)` were all in the run's own resolved allowlist. The entry is a `;`-joined compound of a pipeline; which property the matcher refused is **unestablished** (no per-denial reason is recorded). No grant would have changed the outcome, and a granted alternative for a one-off source scan was already available in a permitted shape (the `Grep` tool, or `grep` on its own). |
| **Ungranted head — `gh auth status`** | B: 5,6,9 | **No change.** `gh auth` is absent from run 30738987528's own resolved allowlist. A credential-state debugging probe; no prompt surface calls it, and granting an auth-introspection subcommand serves no durable caller. |
| **Mixed diagnostic probes — two ungranted heads, two shape refusals** (`cat`/`ls` of `/tmp`, `git remote`/`git status` via `echo`/`printf`, `export`) | A: 19,28,29,40 | **No change**, but the entries do not share a cause. A: 28 reaches `git remote` and A: 29 leads with `export`; neither is in the run's resolved allowlist, so those two are ungranted heads. A: 19 and A: 40 use only granted heads (`cat`, `ls`, `head`, `printf`, `git status`), so those two are shape refusals whose **specific** refused property is **unestablished** — both are `;`-joined compounds of pipelines, and A: 19 additionally *reads* under `/tmp`, but the recorded `/tmp` rule (`R3-tmp`) is about a redirect *target*, so applying it to a read would be an inference. Environment/state introspection the agent improvised either way; the authorized diagnostic surfaces (`preflight.py`, `config-get.sh`) already exist and were granted. |
| **Bare `scripts/…` leading path — one ungranted literal, two shape refusals** | A: 47,48,49 | **No change**, but these three do not share a cause either. A: 47 names `scripts/efficiency-trace.sh`, which is neither a granted literal **nor a file** — the helper lives at `lib/efficiency-trace.sh`, which *was* granted in this run; because grants are per-head across the whole pipeline, the fence's own `\|\| lib/efficiency-trace.sh --persist` fallback could not rescue the statement. A: 48 (`scripts/react-to-trigger.sh`) and A: 49 (`scripts/workpad.py`) name literals that **were** in the run's resolved allowlist as bare `scripts/<name>` forms, so neither is an ungranted head: A: 49 carries a `> /tmp/…` redirect, a documented denied shape, and A: 48's refused property is **unestablished** (every head in its `\| tail -2 \|\| echo …` tail was granted too). No grant is warranted — the one non-granted literal names a path that does not exist. |
| **`./scripts/…` dot-slash prefix** | B: 1,2,8 | **No change.** The `./` prefix makes the path a different literal than the granted form — `Bash(scripts/apply-labels.sh:*)` *was* in that run's resolved allowlist, so this is a spelling difference, not a missing grant. The surfaces author no `./` prefix; agent-improvised. |
| **`for … do … done` loop** | B: 4 | **No change — and not an ungranted head.** Every head in the loop body (`echo`, `grep`) was in that run's resolved allowlist, so this is a shape refusal. The **specific** refused property is **unestablished**: the recorded denied-loop evidence (probe rows I4/I5, desk rules `IR1`/`IR2`) is scoped to a loop whose body invokes a *label helper* by name, which this loop does not, so citing it here would be an inference, not a measurement. Dispositioned "no change" regardless: agent-level iteration is the authored alternative and no surface authors this loop. |
| **Multiline `--body` argument** (`gh pr create --body "…\n…"`) | B: 7 | **No change — and not an ungranted head.** `Bash(gh pr create:*)` was in that run's resolved allowlist, so the refusal is the argument shape: a body string spanning lines reads to the matcher as multiple statements and denies. The shipped Phase 3.1 CREATE fence does **not** author that shape, and not by using `--body-file` either — no `--body-file` appears on the PR-create path anywhere in `skills/implement/`. It composes the body into a variable with an unquoted `cat <<EOF` heredoc and passes `--body "$BODY"` (`skills/implement/phases/phase-3-review.md`), which is a single-line `gh pr create` at author time and so is not the denied inline-multiline-literal shape. The agent improvised both the inline multiline literal and the omission of the fence's `--base "$BASE"`, and the run then created the PR successfully. Nothing to correct on the surface: the authored form was already a permitted one. |
| **Surface-authored best-effort `rm` cleanup** (run-marker/cache removal, command-substitution path) | A: 45 | **No change — and not an ungranted head.** Every head in it (`rm`, `git rev-parse`, `echo`) was in the run's own resolved allowlist, so no grant was missing and this is a shape refusal. The **specific** refused property is **unestablished** — the fence carries `$(...)` command substitution in argument position and a `;`-joined tail, and neither is a shape this page records as denied (shape 18 in fact records command substitution PERMITTED in *condition* position at the review tier), so naming one would be an inference. This one *is* authored by `SKILL.md` (the Outcome-reaction run-marker/issue-body-cache removal) and is explicitly best-effort (`2>/dev/null \|\| true`), so its denial is absorbed by design — the local Stop-hook guard self-heals a stale marker and a leftover cache file is inert (reads are hand-off-only). Nothing to grant and nothing to correct. |

**Per-cause coverage is complete by construction:** the entry indices above partition all
51 entries of run 30738761826 and all 9 of run 30738987528 (60 total). Rows are grouped by
the construct the agent typed; two of them are explicitly **mixed** (the diagnostic probes
and the bare `scripts/…` paths) and name which entries fall to which cause, because
grouping by typed construct and grouping by refusal cause do not coincide there. Where an
entry carried more than one denied property (e.g. an interpreter head *and* a redirect),
it is filed under its leading authored construct, which is the property a prompt surface
would be responsible for; the co-occurring property is noted in the cause's reason where it
matters.

### Why the audit ships no new grant and no surface correction

The two runs differ starkly — 51 denials versus 9 — but the difference is *volume of
agent-improvised verification*, not a missing grant. Run 30738761826 spent 228 turns
iterating verification probes on a shell script under classifier friction (the exact
situation the implement extension's "Verification under classifier friction" section
addresses with the authorized `python3 -c "subprocess.run(...)"` wrapper and the Write
tool). Exactly one of the 60 entries was **typed in a form a prompt surface authors** —
A: 45's best-effort `rm` cleanup — and it is authored *correctly*: the fence is explicitly
tolerant of its own failure, so its refusal changes nothing and calls for no edit. The
criterion is the **typed command**, not the helper it names, and four further entries sit
close enough to be worth naming: A: 47, A: 48, A: 49 and B: 7 each reach for a helper or
subcommand some surface does author, yet each was typed in a form no surface authors — a
bare `scripts/…` leading path where the surface anchors the helper path, a `| tail` or
`> /tmp` tail the surface has no equivalent for, or, at B: 7, an inline multiline `--body`
literal in place of the fence's heredoc-composed `--body "$BODY"`. In every one of them the
refused property is the agent-introduced part, so no surface has a shape to correct.
**Exactly one cause was a head with a durable authored caller** — the shard
dispatcher — and that grant has already landed independently through issue #1132, so this
audit has none left to add. Every other ungranted head is one-off introspection
(`git write-tree`, `git remote`, `gh auth status`, `export`) or a path that does not exist
(`scripts/efficiency-trace.sh`); granting those, or defeating the deliberately-denied shape
family, would widen the profile against its own discipline. The correct, principled
disposition for this population is the recorded "no change," which this section is.

## `git -C <path> <subcommand>` is a refused form — run 30832631347 (issue #1221)

**This subsection is a past-time observation of one run, not a re-derivable figure.** The
counts below were read once from the `permission_denials` array of the
`claude-execution-transcript-30832631347-1` artifact published by cloud implement-tier run
`30832631347` (issue #1196). That array carried **42** refusals across the run's `194`
turns. It is immutable history: a different run would show a different population, so these
figures are never "corrected" or re-measured.

`git -C <path> <subcommand>` was the single largest cause in that population — **15 of 42**
refusals, **13** of them emitted by dispatched review subagents rather than the top-level
run. It is refused as a *shape*, like a leading `cd` before it (the working-directory
contract bans a leading `cd` as an authoring rule — see *Leading `cd` and the working-directory
contract* — while `git -C` is matcher-refused): the run begins at the
repository root and the Bash tool's working directory persists across calls, so the path
argument is never needed.

**Why it cannot be granted.** Every git grant in `lib/capability-profiles.json` names a
subcommand — `Bash(git rev-parse:*)`, `Bash(git show:*)`, and so on. In
`git -C /path rev-parse …` the token after `git` is `-C`, so no subcommand token matches;
the only token that would is `Bash(git -C:*)`, which matches **every** git subcommand behind
a `-C`, including the write subcommands the read-only review profile's lock
(`lib/review-profile.tokens`) exists to exclude. So the correct disposition is
documentation, not a grant — consistent with the #1135 audit's model, and with the fact that
no prompt surface authors the `git -C` form (it was agent improvisation).

**The permitted alternative.** Because the cloud tiers begin at the repository root and the
Bash working directory persists across calls, the bare `git <subcommand>` form (`git diff`,
`git show <ref>:<path>`, `git log`) is the one to emit — run from where you already are, with
no `-C` path argument and no leading `cd`. This is the same alternative the grounding block's
denied-shape list (`scripts/render-grounding-block.sh`) and the review-agent definitions
(`agents/*.md`) now name, so an agent told not to `cd` no longer reaches for `git -C` and
lands on an undocumented refusal.
