# PRFlow working-directory contract

Every PRFlow bundled-helper invocation on the cloud tiers is a **repo-relative
literal** — `.prflow/vendor/prflow/scripts/…` (and `.prflow/vendor/prflow/lib/…`),
or the repo-root `scripts/…` / `lib/…` form in a self-repo checkout — because that
is the only form the harness permission matcher grants (see
[`docs/internal/cloud-allowlist.md`](cloud-allowlist.md)). A repo-relative literal only
resolves if the shell's working directory is the repository root. That makes the
working directory a **load-bearing precondition** for the whole engine, and this
page is the single canonical statement of what that precondition is and where it
holds.

The rule this page exists to state, up front: **no PRFlow surface emits a leading
`cd`.** A statement whose first token is `cd` (a "leading `cd`") moves the shell's
working directory, and because the Bash tool's working directory **persists across
calls** (see below), every later repo-relative helper then resolves against the
wrong directory and fails — `rc 127` for a helper path, `rc 2` for an `awk`/`jq`
over a cached file. The permitted alternative is the one the matcher already
grants: **the repo-relative vendored literal as the command's leading token**, with
any absolute path confined to **argument position** (a helper path is never behind
a `cd`, a `VAR=value` prefix, or a `bash <path>` wrapper).

## Cloud tiers — the run starts at the workspace root, and cwd persists

On the cloud tiers (`devflow-runner.yml`, `devflow.yml`, `devflow-implement.yml`):

- `actions/checkout` places the run at the **workspace root**, and no PRFlow job
  overrides it — there is no `working-directory:` on any step and no job `cd`s. So
  the run **begins at the repository root**, which is the directory every
  repo-relative helper literal resolves against.
- The Bash tool's **working directory persists across calls**: a `cd` in one Bash
  call changes the directory seen by the *next* Bash call, not just the current
  one. This is why a single stray leading `cd` corrupts every later helper
  invocation in the run rather than just its own statement, and why the no-`cd`
  rule is absolute rather than advisory.

That pairing — start-at-root plus persistent cwd — is the whole reason every
granted helper literal is repo-relative with **no re-anchored form the matcher
accepts**. There is no cloud-permitted spelling that would let a helper resolve
from some other directory, so the only safe posture is to never leave the root.

The same pairing is why a second working-directory-flag shape, `git -C <path>
<subcommand>`, is **matcher-refused** on the cloud review runner: the path
argument is never needed when the run already begins at the root, and no git
grant in `lib/capability-profiles.json` matches a `-C`-prefixed subcommand. Emit
the bare `git <subcommand>` (`git diff`, `git show <ref>:<path>`, `git log`) from
where you already are — never `git -C` and never behind a leading `cd`. Unlike
the no-`cd` rule, this one is a matcher refusal rather than an authoring lint; the
run-30832631347 evidence and the per-git-subcommand grant reasoning are in
[`docs/internal/cloud-allowlist.md`](cloud-allowlist.md).

## Local and interactive tier — no working-directory guarantee

The local and interactive tier carries **no** such guarantee. A consumer invokes
PRFlow from any directory, on Windows, macOS, or Linux, across several runners
(Claude Code, Copilot CLI, Cursor, Codex CLI, Gemini CLI). Nothing pins the shell
to the repository root. PRFlow therefore does not depend on cwd on this tier; it
**re-anchors** instead, through two mechanisms:

- **`git rev-parse --show-toplevel` resolution used by the `.prflow/` readers.**
  The six `.prflow/` config/prompt-extension readers (`config-get.sh`,
  `workpad.py`'s marker read, `load-prompt-extension.sh`,
  `match-deferrals.py`, `match-lint-adjudications.py`, `render-audit-prompt.py`)
  resolve the default `.prflow/` path anchored to the **git repository root**
  (`git rev-parse --show-toplevel`, falling back to `pwd`/`Path.cwd()`), so a skill
  run from a subdirectory still loads the consumer's root config instead of
  silently missing it.
- **`BASH_SOURCE` self-anchoring used by `scripts/*.sh` helpers.** A shell helper
  that must reach a sibling file resolves its own directory from `${BASH_SOURCE[0]}`
  rather than assuming cwd, so it works regardless of the directory it is invoked
  from.

Because these mechanisms exist, a local/interactive helper does not need the
working directory to be the repository root — but the no-`cd` authoring rule still
holds, so that a surface authored once reads correctly on the cloud tiers it is
vendored to.

## Worktree-isolated local sessions refuse certain shell expansions (issue #1633)

A local/interactive tier that is **also** a Claude Code worktree-isolated session
adds a constraint the mechanisms above do not cover: it refuses to *execute* a bash
fence carrying any of three shell constructs, returning a hard tool error rather
than a permission prompt. The verbatim refusal string observed is:

> This agent is isolated in the worktree \<path\>, but this command is too complex
> to verify that it stays inside the worktree; break it into plain, separate
> commands. Refusing to run it — a worktree-isolated agent's git operations must
> target its own worktree. Run the equivalent from \<path\> without the redirect.

**The three-construct discriminator.** The refused constructs are exactly:

1. Command substitution — `$(…)` or the backtick form `` `…` ``.
2. The exit-status parameter `$?`.
3. A reference to a shell variable **bound within the same command** — by
   assignment, by a `for`/`select` header, by `read`, or by `export`.

**The constructs measured to run** (so the refusal is *not* "multi-statement
compound commands as a class", which the measurement refutes): plain sequences
(`echo a; echo b`), `&&` chains, `if`/`then`/`else`, `for … do … done` loops that
never reference their bound variable, in-workspace redirects (`echo hi > file`),
`mkdir -p … && echo x > …`, pipes into `tee`, `cd`, an interpreter head
(`python3 -c`), a bare assignment with no later reference (`FOO=bar; echo done`),
and a granted helper path invoked with only ambient variables. The report's own two
data points fit the expansion reading: `cmd > /dev/null` ran, and the same command
with `; echo rc=$?` appended did not.

**Provenance (an observation, not a documented contract).** This discriminator was
inferred from **24 probe commands in one session**, on macOS, on one Claude Code
version, **without reading harness source**. Treat it as a flagged assumption, not a
proven harness contract — confirm before relying on it, and treat the
three-construct set as the observed discriminator rather than a documented one. The
enrolled implement-bundle fences are kept free of these three constructs, and
`lib/test/lint-worktree-fence-shapes.py` is the regression backstop; the shipped
fences route on the exit code and printed token the runner reports for the command
(the `skills/implement/phases/phase-4-documentation.md` §4.0 form), treating a
refused or no-output invocation as an **unestablished measurement** that reaches the
stop path — never a decided answer.

**Deployment skew.** The rewritten fences reach a consumer through the plugin vendor
fetch, while the capability grants that make a newly-granted head resolve reach them
through `install.sh`'s workflow copy loop — two independent schedules. A consumer who
takes only the plugin update runs the rewritten fences under their previous
allowlist; because an ungranted head produces no output and the fences route
no-output to the stop path, that skew window surfaces as a stated stop rather than a
silent denial.

**Unmigrated residual fences (named so the bundle is not mistaken for fully
migrated).** Some implement-bundle fences carry a refused construct that no existing
bundled helper can absorb, so they stay unmigrated and unenrolled:

- `skills/implement/phases/phase-3-fix-loop.md` — the pre-loop snapshot fence and the
  post-return change-detector fence capture a `git` result into a variable read later
  in the same fence (construct 3) and use command substitution (construct 1); their
  value is a diff/SHA the loop compares across iterations, which no `--repo-relative`
  helper mode replaces.

These are **not** in `lint-worktree-fence-shapes.py`'s enrollment inventory, so they
remain legal; the inventory is the single place the migrated set is written down.

## Why the rule is an authoring rule, not a matcher claim

The no-`cd` rule is stated as an **authoring rule** — "no PRFlow surface emits a
leading `cd`" — and **not** as a claim that a matcher refuses one. The PR #847
review incident (run 30222310785) recorded a leading `cd` **executing** on the
review tier, where `Bash(cd:*)` is already ungranted, so an ungranted `cd` head
does not imply a refused statement. The affordance is instead removed at the
authoring layer: `Bash(cd:*)` is not granted in any profile, and
`lib/test/extract-command-shapes.py`'s implement-profile finder emits an **`IR4`**
hit for a fenced statement whose head is `cd`, so a `cd` authored into a scanned
prompt surface fails at the desk. That desk lint scans only authored ` ```bash `
fences, so it governs what a future author writes into a prompt surface — it does
**not** catch a `cd` a model composes at runtime (issue #805 owns that mechanism).

## Pointers

- [`docs/internal/cloud-allowlist.md`](cloud-allowlist.md) — the matcher-shape evidence,
  the granted-literal forms, and the `cd` status per tier.
- `CLAUDE.md` carries a short non-authoritative summary paired with a pointer to
  this page.
