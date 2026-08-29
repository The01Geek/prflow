# Installing & updating PRFlow

The [README quick start](../../README.md#quick-start) gets you running in one line. This page is the full reference: every install path, the now-zero companion-plugin dependency set, and how updates work for both tiers.

## Local tier

PRFlow is published as a Claude Code plugin from this repository, which is also its own marketplace.

> [!TIP]
> **Just ask your agent.** Paste this into Claude Code and it performs the whole install for you — the two plugin commands *and* the PATH dependencies `/plugin install` doesn't cover (see [the step people miss](#the-step-people-miss-pyyaml)):
>
> ```text
> Read https://github.com/The01Geek/prflow#quick-start and install PRFlow and its dependencies.
> ```

**In your terminal** (two commands — run them in order; works in any shell, including PowerShell and fish that don't support `&&` chaining):

```bash
claude plugin marketplace add The01Geek/prflow
claude plugin install prflow@devflow-marketplace
```

**Or from inside Claude Code:**

```text
# Add the marketplace
/plugin marketplace add The01Geek/prflow

# Install plugin
/plugin install prflow@devflow-marketplace
```

Then run `/reload-plugins` (or restart) to activate. That's it for the local tier — it needs **zero configuration**.

> [!NOTE]
> **The plugin is `prflow`; the marketplace is still `devflow-marketplace`.** That mismatch is deliberate, not a half-finished rename. Claude Code's `renames` map — which migrates an already-installed `devflow` to `prflow` — lives *in the marketplace manifest* and is scoped **per marketplace**, so renaming the marketplace would move the migration map somewhere existing installs never look and strand every current user. The install identifier is therefore `prflow@devflow-marketplace`, and the marketplace name is frozen. `renames` migrates existing installs only; it is **not** an install-time alias, so `devflow@devflow-marketplace` no longer resolves for a fresh install.

### No companion plugins to add

PRFlow declares **zero companion-plugin dependencies** — every external asset its engine once dispatched is now a first-party PRFlow file: the `pr-review-toolkit` review agents and the `feature-dev` `code-explorer`/`code-architect` discovery/planning subagents live under `agents/`, and the `superpowers` final-pass reviewer (`requesting-code-review`) and fix-loop `receiving-code-review` principles live under `skills/` — all hard-forked with their upstream licenses retained verbatim under `LICENSES/`. So `/plugin install prflow@devflow-marketplace` resolves with **nothing else to add**: no `claude-plugins-official` marketplace prerequisite, and none of the old `/plugin` **Errors**-tab `dependency-unsatisfied` friction that a missing cross-marketplace dependency used to cause. `/simplify` is a built-in Claude Code skill and needs no installation.

### The step people miss: PyYAML

`/plugin install` resolves companion *plugins* only — it **never runs `pip`**. One runtime helper (`match-deferrals.py`) uses **PyYAML**, so install it yourself — by package name, not with `-r requirements.txt` (that path resolves against *your* working directory, not the plugin cache, so in a Python project it would install your project's dependencies instead):

```bash
python3 -m pip install PyYAML
```

On the local tier PyYAML is **advisory**: `bash lib/preflight.sh` reports a missing PyYAML and still exits 0 (with a distinct advisory final line naming the remedy), because that one helper degrades to a logged skip rather than breaking. Installing it only restores the severity demotion of previously-deferred findings. (On the cloud tier the workflows install PyYAML themselves — a `pip install` step in the workflow, not something `install.sh` does — and the test suite and CI still require it.) See [Requirements](../../README.md#requirements) for the full PATH checklist; in a checkout of this repo, `bash lib/preflight.sh` verifies the required tools.

### Windows: resolving `python3`

A stock Windows Python install (python.org / `winget install python`) exposes Python on PATH as `python` and the `py -3` launcher — there is **no `python3`**. Because PRFlow's helpers, the agent-typed `python3 <path>` convention, and the cloud `Bash(python3:*)` allowlist all invoke the literal `python3`, the toolchain otherwise fails with `python3: command not found` even with a perfectly good Python 3.11+ installed.

When `python3` is absent but a `>=3.11` Python is reachable as `python` or `py -3`, run the consent-gated provisioner once — from a checkout of this repo — to install a small `python3` shim onto the first writable directory already on your PATH (falling back to Git-Bash's `~/bin`, with a PATH note, if none is writable):

```bash
bash scripts/provision-python3-shim.sh --apply
```

It selects the first of `python3`/`py -3`/`python` reporting `>=3.11`, writes a `python3` that forwards all arguments and the exit code to it (never recursing), and prints a `devflow-python:` breadcrumb. Without `--apply` it prints exactly what it would do and writes nothing. It is idempotent — a no-op when a real `python3 >=3.11` already resolves — and refuses to write a shim if no `>=3.11` interpreter exists. `install.sh` surfaces this provisioner in plan-only mode on the clone-based install path, and `bash lib/preflight.sh` (which `/prflow:init` relays) points you here when it detects the no-`python3`/has-alternate state. macOS/Linux already ship a real `python3`, so this step is a no-op there.

### Why the environment variables are still called `DEVFLOW_*`

`DEVFLOW_GH`, `DEVFLOW_JQ`, `DEVFLOW_BASH` and the `install.sh` overrides below kept their
names through the DevFlow → PRFlow rename, and they are **frozen** under that spelling:
nothing PRFlow ships reads a `PRFLOW_*` equivalent. Do not rename them. Each one resolves
through a `${NAME:-…}`-style default, so a renamed name is indistinguishable from an unset
one — the override silently stops applying, which on a healthy host looks exactly like
success. The full inventory, with what renaming each one actually does, is in
[Why these settings are still called `DEVFLOW_*`](cloud-setup.md#why-these-settings-are-still-called-devflow_--and-what-happens-if-you-rename-them).

### Windows: resolving `gh`

On Windows (WSL-bash or Git Bash), `PATH` can place a **non-executable `gh`** — for example a Python-provided `gh` script carrying a Windows shebang — ahead of the real GitHub CLI (`gh.exe`). A bare `gh` then resolves to that shim, which fails with `cannot execute: required file not found`, so every PRFlow helper that shells out to `gh` breaks even though `gh` works from PowerShell.

PRFlow resolves this automatically: `lib/resolve-gh.sh` (used by every gh-calling helper and by `lib/preflight.sh`) picks the first of `gh`, `gh.exe` whose `gh --version` **actually runs** (a network- and auth-free probe), so a present-but-unrunnable shim is rejected in favor of a working `gh.exe`. On macOS/Linux/cloud, where bare `gh` runs, it returns `gh` on the first probe — no behavior change.

If your host needs a specific binary (or you want to bypass probing entirely), set the **`DEVFLOW_GH`** environment variable to the working `gh` / `gh.exe` (a name on PATH or an absolute path). When set and non-empty it takes top precedence — the probe runs only when `DEVFLOW_GH` is unset or empty — and it is honored by both the shell helpers and the Python helpers (`workpad.py`, `file-deferrals.py`, `match-deferrals.py`, `parse-acs.py`):

```bash
export DEVFLOW_GH=gh.exe   # or an absolute path to the working GitHub CLI
```

`bash lib/preflight.sh` reports a present-but-unrunnable `gh` with this remedy.

### Windows: resolving `jq`

The same shadowing can hit `jq`: a present-but-unrunnable `jq` earlier on `PATH` (a bad-shebang shim, a cleared exec bit) passes a naive presence check while every jq-dependent PRFlow step breaks.

PRFlow resolves this the same way: the shared resolver `lib/resolve-bin.sh` (which every jq-calling helper and `lib/preflight.sh` route through, and which `lib/resolve-gh.sh` delegates to for `gh`; `install.sh` alone carries an inline adaptation, since it runs before any checkout exists — there a broken `DEVFLOW_JQ` falls back to python3 with a warning) picks the first of `jq`, `jq.exe` whose `jq --version` **actually runs** (a network- and auth-free probe), rejecting an unrunnable shim in favor of a working `jq.exe`. On macOS/Linux/cloud, where bare `jq` runs, it returns `jq` on the first probe — no behavior change.

If your host needs a specific binary (or you want to bypass probing entirely), set the **`DEVFLOW_JQ`** environment variable to the working `jq` / `jq.exe` (a name on PATH or an absolute path). When set and non-empty it takes top precedence — the probe runs only when `DEVFLOW_JQ` is unset or empty:

```bash
export DEVFLOW_JQ=jq.exe   # or an absolute path to the working jq
```

`bash lib/preflight.sh` execution-verifies `jq` through the same resolver and reports a present-but-unrunnable `jq` with this remedy.

Relatedly, PRFlow ships `lib/normalize-path.sh` (`devflow_normalize_path`), a sourced helper that converts a Windows-form path (`C:\...`) to the running shell's POSIX form — `wslpath` when present, else `cygpath`, else an environment-detected translation (`/mnt/c/...` under WSL, `/c/...` under MSYS/Git Bash) — echoing an already-POSIX path through unchanged. A runner-reported Windows-form path (like a skill's base directory on a non-Claude-Code runner) is normalized at prompt time with that helper's `wslpath`/`cygpath` probe only — since issue #1856 the skills no longer restate the tool-less drive-letter tier — and the located directory is then validated against the filesystem.

### Windows: choosing the bash PRFlow runs under (`DEVFLOW_BASH`)

PRFlow's helpers are `.sh` scripts, so they need a **POSIX bash** to run. On Linux/macOS/cloud that is the default shell and there is nothing to do. On Windows the *default* shell may be PowerShell, and the working bash is whichever of **WSL bash**, **Git Bash**, or **MSYS2 bash** you have — **any of them works**; PRFlow does not mandate a specific one.

Unlike `gh`/`jq` (tools a *running* bash calls, resolved by a sourced `resolve-*.sh` helper), the bash that *runs* the scripts is chosen one layer up — at the **invocation boundary**, before any `.sh` executes — so a sourced resolver cannot select it (it would itself need a chosen bash to run). That layer (the agent or runner that shells into bash) honors the **`DEVFLOW_BASH`** environment variable: set it to the POSIX bash you want PRFlow's helpers to run under.

```bash
export DEVFLOW_BASH=/path/to/bash   # e.g. a WSL, Git Bash, or MSYS2 bash
```

`bash lib/preflight.sh` prints a `devflow-bash:` breadcrumb naming the bash it is running under (interpreter path + `$BASH_VERSION`) and surfaces `DEVFLOW_BASH` when set, so you can confirm the intended bash took effect. If preflight finds it is **not** running under a POSIX bash (empty `$BASH_VERSION` — e.g. when the `.sh` is executed by `sh`/`dash` rather than bash), it prints a remedy naming the three supported bashes and the `DEVFLOW_BASH` override, and exits non-zero. On Linux/macOS/cloud the running `bash` is used unchanged and an unset `DEVFLOW_BASH` is a no-op.

**Known non-goal.** A host with **no POSIX bash at all** (PowerShell-only, with no WSL, Git Bash, or MSYS2 installed) cannot run the `.sh` helpers regardless — that irreducible case is out of scope. Install any one of the three supported bashes; that is the fix, not a `DEVFLOW_BASH` value.

### Windows: the standalone-argument path-conversion hazard (MSYS/Git Bash)

Git Bash and MSYS2 rewrite a **standalone slash-leading argument** — one whose whole value looks like a Unix path (e.g. `/simplify`) — into a Windows path such as `C:/Program Files/Git/simplify` **before** a native (non-MSYS) executable like `python3` receives it. This conversion is silent and applies to the argument itself, not to a flag it is attached to; the [MSYS2 filesystem-paths docs](https://www.msys2.org/docs/filesystem-paths/) describe it. A PRFlow argument that reaches native `python3` this way arrives as a Windows path and no longer matches what the step expected.

**Host-safe operand rule.** PRFlow avoids the hazard at the source rather than with an environment prefix: a value passed as a standalone argument to a native tool must not be a static slash-leading literal. The Phase 3 workpad tick is the worked case — it passes the substring `simplify` (which still uniquely matches the displayed `` `/simplify` `` Progress row), not `/simplify`. The derived guard in `lib/test/test_python_scripts.py` fails the suite if a static standalone `--tick-progress` operand under `skills/implement/` begins with `/`.

**Do not add an environment prefix to PRFlow's own call sites.** `MSYS_NO_PATHCONV=1` or `MSYS2_ARG_CONV_EXCL=…` suppress the conversion for your *own* commands, but PRFlow does not prepend either to its invocations — the host-safe-operand rule keeps the argument non-convertible instead, so no per-call environment variable is required.

**Scope: standalone slash-leading literals only — an absolute *path* operand is handled by the accepting check instead.** The host-safe-operand rule covers exactly the class it can: a value the shell would rewrite because its *whole* value looks like a Unix path. An **absolute path argument** is the complementary class and is handled the opposite way. When MSYS rewrites a correct `/c/Users/…` to `C:/Users/…` in transit, or `scripts/resolve-main-root.sh` reports the native-git repository root as `C:/Users/…`, `scripts/render-audit-prompt.py`'s `_abs_path` argument check now **accepts** the host-absolute drive-letter form — in either the forward-slash or backslash spelling — and returns it unchanged, rather than rejecting it as a non-POSIX path. A path operand therefore needs no host-safe rewriting: the check admits a drive-rooted or UNC-rooted Windows path, and a `/`-leading POSIX path, which the interpreter can then open. A Windows-style path rooted at no drive (`\Users\x`) stays refused (issue #1762).

### Non-Claude-Code runners (Copilot CLI, Cursor, Codex CLI, Gemini CLI): the skill anchor

Every local-tier skill locates its bundled helpers through a **portable single-statement anchor**: `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/…`. On Claude Code, `$CLAUDE_SKILL_DIR` is exported and the command runs as written. On other runners the variable expands **empty**; the agent substitutes the placeholder with the skill base directory the runner reports in context (Copilot CLI prints a `Base directory for this skill:` line), normalizing a Windows-form path (`C:\...`) to POSIX form first with a `wslpath -u` / `cygpath -u` probe (since issue #1856 there is no `lib/normalize-path.sh` drive-letter-rules fallback here), then accepting the located directory only once `ls <candidate>/../../scripts/` validates it. Two constraints make the *single-statement* shape load-bearing rather than stylistic:

- **Inline-bash variable stripping (Copilot CLI, verified on 1.0.68; the empty-`$CLAUDE_SKILL_DIR` observation is a separate fact, confirmed earlier on 1.0.67):** a variable assigned in one statement of an inline `bash -c` command reads **empty** in a later statement of the same command (`bash -c 'v=hi && echo $v'` prints nothing; the same lines in a `.sh` file work). So never rework a skill's helper call into an assign-then-use form (`SKILL_DIR=…; "$SKILL_DIR"/../…`) — resolve the anchor inline in the statement that uses it, every time.
- **Reported base directory first, `echo` is a refusable fallback (issue #1594).** For the two skills that resolve `<skill-dir>` as a *value* to base their phase-file reads on — `skills/implement/SKILL.md` and `skills/review/SKILL.md` — the resolution order is now inverted: `<skill-dir>` is taken from the base directory the runner reports in context (e.g. a `Base directory for this skill:` line) with **no shell command emitted on that path**, and the `echo "${CLAUDE_SKILL_DIR:-…}"` command is only the **fallback**, emitted when the runner reports no base directory. This closes a gap where a runner refusing that command left the step with no defined behavior — a refusal is where the command never ran, distinct from running and printing nothing. The fallback command's outcome is therefore classified into **exactly three shapes**: a **tool-level refusal** (the runner declined the command, so it never executed and produced no output — the `$CLAUDE_SKILL_DIR` channel is *unestablished*, `unknown is not zero`, reported distinctly from an empty run), a command that **ran and printed empty**, and a command that **ran and printed the placeholder unsubstituted**.
- **Fail closed:** when neither `$CLAUDE_SKILL_DIR` nor a runner-reported base directory is available — a run with no reported base directory whose fallback command also yields no path — the skills stop before reading any phase file and report the unresolved anchor instead of running a broken `/../../…` path. (One deliberate exception: `/prflow:create-issue` is best-effort throughout — an unresolvable anchor never blocks issue creation; a skipped provenance label or prompt-extension load is reported explicitly instead.)

**Guard recipes are single-statement too (portability wave 3).** The same inline-bash constraint governs the skills' *guard recipes*, not just the anchor: the former `VAR=$(…); VAR_RC=$?` capture-then-discriminate blocks read the captured rc in a later statement, which such a runner leaves empty — so their rc-discriminating branches and `::warning::` breadcrumbs silently never fired, and the highest-blast-radius instance (`/prflow:implement`'s Phase 4.1 documentation gate) had an inert fail-closed check. Every such recipe now discriminates its failure with a single-statement `if !` (or `elif [ "$?" … ]` for a 3-way) that reads the command's **own** exit status inline, so the fail-closed check and the distinct breadcrumbs hold on a stripping runner. What remains is only benign: a raw *value* variable assigned by `VAR=$(…)` and read in a later statement can still come back empty on such a runner, but the migrated guards are written so that path falls through to the **documented default** (e.g. `max_iterations` → 5, a severity threshold → its default) or **fails closed**, never to a fail-open or a misdirected breadcrumb.

### Running a skill from a repo subdirectory

PRFlow's skills now work when invoked from **any subdirectory** of your repository, not just the repo root: the `.prflow/` config and prompt-extension readers (`scripts/config-get.sh`, `scripts/load-prompt-extension.sh`, and the in-process config reads in `scripts/workpad.py`, `scripts/match-deferrals.py`, `scripts/match-lint-adjudications.py`, and `scripts/render-audit-prompt.py`) resolve the **default** `.prflow/` path anchored to the git repo root (`git rev-parse --show-toplevel`, falling back to the current directory when not in a git tree), rather than relative to the current directory. (`load-prompt-extension.sh` takes that repo-root anchor only on its *fallback* branch since issue #874 — when `DEVFLOW_PROMPT_EXTENSION_ROOT` is set and non-empty, as the cloud tiers that run the review engine set it, the path comes from that value instead.) So a `/prflow:*` skill run from a subfolder still loads the consumer's root `.prflow/config.json` and `.prflow/prompt-extensions/<skill>.md` instead of silently reverting to defaults. A **non-empty** explicit config path (`config-get.sh`'s 3rd argument, `match-deferrals.py --config`, `match-lint-adjudications.py --config`) is still honored verbatim; an explicit empty value still selects the root-anchored default.

**Limitation:** `--show-toplevel` returns the *nearest* git root, so a nested git submodule / inner repo, or a monorepo whose `.prflow/` deliberately does not sit at the git root, is not covered — the readers anchor to the nearest git root in those layouts.

### Windows: PowerShell file-write encoding (UTF-16LE pitfall)

PowerShell 5.x's `>` redirection and `Out-File` write **UTF-16LE with a BOM** by default. PRFlow's helpers decode their local input files (issue bodies, workpad body files, AC lists) **explicitly as UTF-8** — `parse-acs.py --body-file`, `workpad.py`'s section-file flags (`--replace-plan-file`/`--replace-acs-file`/`--set-reproduction-file`), and `branch-for-issue.py --title-file` all pass `encoding="utf-8"` rather than trusting the ambient locale codec, which is a separate hardening layer from the stream/`gh`-I/O UTF-8 forcing (issue #222) that governs the helpers' own stdout/stderr and subprocess I/O. Because that decode is UTF-8, a file produced with a PowerShell `>` (UTF-16LE) is not valid UTF-8 and is **rejected cleanly** — the reader exits non-zero with a flag-specific diagnostic and no traceback (and `workpad.py` issues no GitHub PATCH), rather than silently arriving as NUL-interleaved mojibake. When preparing any file a PRFlow helper will read from PowerShell, write UTF-8 **without** BOM explicitly — e.g. `[IO.File]::WriteAllText($path, $text)` or `Set-Content -Encoding utf8NoBOM` (PowerShell 7+) — or simply create the file from inside your POSIX bash instead.

### Windows: quoting `workpad.py` text arguments from PowerShell

PowerShell's double-quote handling can split a `--note`/`--reflection` text argument into extra argv tokens before Python sees it. `workpad.py` fails closed in that case (exit 2, no partial write) — but the fix is on the caller: **single-quote** the text argument in PowerShell (`--note 'my note text'`), or invoke the helper from bash.

## Cloud tier (optional, autonomous)

**The plugin itself needs no installer.** `install.sh` is only for the *optional* cloud tier. If all you want is PRFlow's `/prflow:*` skills in your editor, the local-tier `claude plugin install` above is the whole install — do not run this script.

For autonomous GitHub Actions automation, run the installer from your repo root. It is idempotent, so re-running it at a *newer* release tag is also how you update. It writes into your repository — the workflows and composite actions under `.github/`, a local `marketplace.json`, and `.prflow/` templates (config scaffold, schema, ignore file) — so those changes land in version control. **Download it, read it, then run the downloaded file:**

```bash
curl -fsSL https://raw.githubusercontent.com/The01Geek/prflow/v2.36.16/install.sh -o devflow-install.sh
# review devflow-install.sh, then:
DEVFLOW_REF=v2.36.16 bash devflow-install.sh
```

<a id="pinning-the-installer"></a>
**Why the version appears twice — and how to move it.** The version in both lines above is a **release tag**, so both commands resolve to the same immutable commit every time you run them. Two independent things get pinned, and they are separate on purpose:

- the **URL ref** decides which *installer bytes* you download and read. A `.../main/install.sh` URL would hand you a different script on every fetch, so the thing you reviewed is not guaranteed to be the thing you ran.
- **`DEVFLOW_REF`** (a documented `install.sh` environment variable, default `main`) decides which ref the installer *clones its payload from* — the workflows, composite actions and templates it copies in — and it accepts a tag, a commit SHA, or a branch name. Pinning the URL alone is not enough: an unset `DEVFLOW_REF` still pulls the payload from the moving `main`. Setting both to the same tag makes the whole install reproduce one release.

To install a newer version, substitute a newer tag in both places. **Every version is tagged**, so the newest tag is the newest code — find it on the [Tags page](https://github.com/The01Geek/prflow/tags), or from the shell with `git ls-remote --tags --refs --sort=-v:refname https://github.com/The01Geek/prflow | head -5`. Only feature releases (`minor`/`major` bumps) are additionally published on the [Releases page](https://github.com/The01Geek/prflow/releases) with their changelog entry; patch bumps get a tag and no release announcement. Leave `DEVFLOW_REF` unset only if you deliberately want to track the moving `main` branch.

Independently of either pin, `install.sh` stamps `.prflow/config.json`'s `prflow_version` with the exact commit SHA it resolved, so the plugin your *workflows* fetch at runtime is reproducible even if you left `DEVFLOW_REF` unset. (A `prflow_version` you hand-set to a non-SHA value — a release tag, or `main` to track the branch — is preserved rather than re-stamped; see the `prflow_version` notes in [`cloud-setup.md`](cloud-setup.md).)

<details>
<summary>Piping straight to <code>bash</code> (not recommended)</summary>

`curl … | bash` runs the script without giving you a chance to read it. If you accept that, still pin both refs:

```bash
curl -fsSL https://raw.githubusercontent.com/The01Geek/prflow/v2.36.16/install.sh \
  | DEVFLOW_REF=v2.36.16 bash
```

</details>

See **[`cloud-setup.md`](cloud-setup.md)** for secrets, triggers, and the full guide — including the optional primary PRFlow App (workflow-file pushes + one identity for user-visible posts) and the separate **DevFlow-Reviewer** App that gives the review agent a non-author identity so its formal `--request-changes`/`--approve` is not a forbidden self-review.

**Thin by default.** `install.sh` does **not** commit the plugin tree to your repo — it installs the workflows, composite actions, a local `marketplace.json`, and a `.prflow/config.json` scaffold, and pins a `prflow_version` (the commit it installed from). At runtime the workflows materialize the plugin into `.prflow/vendor/prflow/` via the `vendor-plugin` composite action, so there's no bulky vendored diff to carry. Pass `DEVFLOW_VENDOR=1` to commit the tree instead (self-hosting; `prflow_version` is then ignored).

**Both tiers on one repo?** No conflict — the local marketplace copy is cached centrally; the cloud tier materializes its own copy under `.prflow/vendor/prflow/` at runtime (or commits one with `DEVFLOW_VENDOR=1`). Just don't run `/plugin marketplace add ./` there (it would activate two marketplaces named `devflow-marketplace`).

**Choosing the runner (`DEVFLOW_RUNNER`, optional).** Every consumer-shipped workflow job resolves its `runs-on` from an optional GitHub **repository/organization variable** `DEVFLOW_RUNNER` (Settings → Actions → Variables — it is infrastructure, *not* a `.prflow/config.json` key):

- **unset or empty** → `ubuntu-latest`, byte-for-byte the previous behavior (existing Linux adopters set nothing);
- a **bare single label** (e.g. `windows-latest`) → that single-label runner;
- a **JSON array** (e.g. `["self-hosted","windows","PRFlow"]`) → a runner matching that label set (match it exactly to a registered runner);
- a value that begins with `[` but is not valid JSON → the job fails **loud** at evaluation time (a visible `fromJSON` error), rather than silently degrading to `ubuntu-latest`.

Each workflow also forces `bash` for its `run:` steps, so a self-hosted Windows runner needs Git Bash on its PATH. Setting `DEVFLOW_RUNNER` **dispatch-enables** a self-hosted / Windows runner but does **not** certify that every inline bash body runs correctly on a Windows filesystem — an adopter must run at least one full consumer-shipped workflow end-to-end on the target runner before treating it as production-ready. See [`cloud-setup.md`](cloud-setup.md) for the full self-hosted-runner prerequisites (toolchain, the `python3` shim, `DEVFLOW_GH`/`DEVFLOW_JQ`/`DEVFLOW_BASH`, the `setup.services` Docker caveat) and the smoke-test boundary.

**Windows: pre-install Claude Code and set `setup.claude_code_executable`.** `anthropics/claude-code-action@v1` bundles a **Unix-only** installer, so on a self-hosted Windows runner it aborts before Claude starts (`Windows is not supported by this script`) and every `/prflow:*` cloud job fails. Pre-install the CLI on the runner (`irm https://claude.ai/install.ps1 | iex`) and set the optional `.prflow/config.json` key `setup.claude_code_executable` to the resulting `claude.exe` path; all three workflows forward it to the action's `path_to_claude_code_executable` input, which skips installation and uses that executable. Unset/empty (the default) leaves the Linux auto-install path unchanged. Because this key is resolved at **trigger time** (from the default/base branch), its effect is **post-merge-only** — a PR that adds it cannot exercise it in that PR's own run. Full walkthrough in [`cloud-setup.md`](cloud-setup.md#windows-point-the-action-at-a-pre-installed-claude-code-setupclaude_code_executable).

**Windows: the two opt-in git-env pins (`setup.git_dir_pin`, `setup.git_work_tree_pin`).** Two independent boolean keys, **both defaulting to `false`**, govern whether PRFlow exports `GIT_DIR: <workspace>/.git` and `GIT_WORK_TREE: <workspace>` into the cloud job environment before the `Run Claude Code` (`anthropics/claude-code-action@v1`) step. With both off — the default — neither variable is set and the tiers behave as they did before the pins existed; that default is the configuration that works everywhere. Enabling `git_dir_pin` makes the action's `configureGitAuth` git-identity setup resolve `.git` independent of the inherited working directory, which a self-hosted Windows runner is **inferred** to need in the both-pins-off default (otherwise it aborts `fatal: not in a git directory`, exit 128, before the agent runs) — but ambient `GIT_DIR` also makes PRFlow's repo-root readers resolve a `.prflow/` that does not exist whenever a helper runs from a non-root working directory, and that failure is a **silent miss** rather than an error, so such a run is not config-faithful. `git_dir_pin` is **not honored on the implement tier**, which stages and pushes commits. Enabling `git_work_tree_pin` **breaks remote plugin-marketplace installs** (`fatal: working tree '<path>' already exists.`) and is safe only if your composed marketplace list is local-only. The `configureGitAuth` benefit is **inferred** from the action's upstream source; the one datum on record is a `/prflow:implement` job that completed on a self-hosted Windows runner (maintainer-reported from a consumer's runner, 2026-07-21; not independently reproducible from this repository, and no run identifier committed), establishing only that `configureGitAuth` did not abort on that run — `GIT_DIR` was necessarily absent because the implement tier suppresses it, while `GIT_WORK_TREE` is **inferred** absent from the completed plugin install rather than read, with a pre-existing marketplace checkout on a persistent self-hosted runner as the named falsifier and the run's git-env step output as the evidence that would settle it (full label in [`cloud-setup.md`](cloud-setup.md)). Both keys are resolved at **trigger time** from a trusted tree, so their effect is **post-merge-only**. Note the two-channel upgrade ordering: the workflows ship via `install.sh`'s file-copy while the resolving helper ships via the `prflow_version` vendor fetch, so re-running `install.sh` without advancing `prflow_version` gives you the step without the helper — which is safe, because an absent helper makes the step emit nothing and exit 0 (fail-open to the working default). Full per-combination cost table in [`cloud-setup.md`](cloud-setup.md).

**Windows: the `gh`-wrapper fingerprint-mode gate (resolved, issue #690).** With a GitHub App configured (`DEVFLOW_APP_ID` set), both writer tiers run `scripts/install-gh-wrapper.sh`, whose output 5/7 used to require the token fingerprint file's POSIX mode to be exactly `600`. A native-Windows `python3` (`os.name == 'nt'`) synthesizes `st_mode`'s permission bits from the `FILE_ATTRIBUTE_READONLY` bit alone, so `600` is unreachable there and the step failed on **every** run, aborting the `claude` job before the agent started. The gate is now platform-aware: `posix` hosts are unchanged, and on an `nt` host the mode stops being a failure condition and the installer records on stderr that the owner-only guarantee could not be established, leaving access to the filesystem's ACLs. Only a **native** Windows CPython (python.org, `mingw-w64-*-python`) reports `nt`; the Cygwin-derived `msys/python` build reports `posix` and keeps the strict gate. Consistent with the "dispatch-enabled, not certified" posture above, clearing this blocker does not by itself certify the tier — run the smoke test. This ships through the `prflow_version` vendor fetch alone (no workflow file changes), so on a **thin** install re-running `install.sh` delivers nothing; on a **committed-vendor** install (`DEVFLOW_VENDOR=1`) re-running it from an updated checkout does deliver the fixed script. Full detail in [`cloud-setup.md`](cloud-setup.md#windows-posix-mode-bits-do-not-constrain-the-credential-files).

## Migrating a repository set up before the PRFlow rename

Repositories installed before the rename keep their state in `.devflow/`, with the vendored plugin at `.devflow/vendor/devflow/`, `devflow_*` config keys, workflow bodies naming those paths, and a `.claude-plugin/marketplace.json` `source` pointing at the old vendored directory. `/prflow:init` migrates all of that, and `install.sh` performs the same migration first inside its own apply path — both call the one helper, `scripts/migrate-consumer-tier1.sh`, so the two entry points cannot drift.

**The migration is all-or-nothing, deliberately.** The shipped workflows invoke bundled helpers at the vendored path as repo-relative leading tokens, and the cloud allowlist grants are per-literal-path — so a half-moved tree is not merely broken, it is silently *denied*, and a run ends with no verdict. The helper therefore plans, validates every precondition for all four members, stages every new byte, and only then commits behind a rollback journal:

| Member | What moves |
| --- | --- |
| state-dir-move | `.devflow/` → `.prflow/`, including `vendor/devflow/` → `vendor/prflow/`, every byte preserved |
| workflow-content-rewrite | every `.github/workflows/*.yml` on disk that names a superseded path or config key |
| marketplace-source-rewrite | `.claude-plugin/marketplace.json`'s local plugin `source` |
| version-pin-advance | `devflow_version` → `prflow_version` (plus the other six top-level keys), with the pin advanced to a ref that contains the migration |

A single unsatisfiable member refuses the whole set and leaves the repository **byte-identical**; the report names which member was blocked and why. Run it without `--apply` for a preview that writes nothing:

```bash
.prflow/vendor/prflow/scripts/migrate-consumer-tier1.sh              # preview: plan only, no writes
.prflow/vendor/prflow/scripts/migrate-consumer-tier1.sh --apply --pin-from-plugin
```

Two things the migration does **not** own, and reports instead: a retained workflow `install.sh` does not ship (`devflow-review.yml`, `devflow-runner.yml`, `telemetry-push.yml`) — it is rewritten with the others, but no installer run can keep it current afterwards — and your `DEVFLOW_*` environment variables, CI secrets and organization variables, which live outside the repository entirely.

### The transitional read-through, and when it goes away

`/prflow:init` registers the marketplace with `autoUpdate: true`, so the **plugin** can update ahead of any migration run. To keep that from silently reverting an un-migrated repository to template defaults, every reader resolves `.prflow/` first and falls back to `.devflow/` **only** when the canonical directory is absent and the superseded one is present — writing a stderr breadcrumb naming `/prflow:init` on every such resolution. Nothing is silent: if you see that line, the repository has not been migrated.

**This fallback is removed once no consumer still carries a `.devflow/` directory** — a confirmation, not a timer. It is recorded in `lib/rename-map.json` under `transitional_read_through.end_criterion`, which is the single source for it.

The **config keys** deliberately have no such fallback. A silent key fallback would make the key migration unobservable and therefore permanent, so it is *detected* rather than read through: `scripts/config-get.sh` breadcrumbs when a requested key is absent and its superseded counterpart is present, and the two shipped workflows' `config` jobs fail loud on an absent key family (the trigger-time channel reads config through inline `jq` and never through the resolver, so no breadcrumb could reach it).

### The `devflow` spellings inside your config are renamed too

The key migration above renames **top-level keys**. A second pass, `lib/migrate-config-values.py`, renames the superseded spellings that live in your config's **values and nested keys**, so `.prflow/config.json` reads `prflow` / `PRFlow` throughout:

| What | Becomes |
| --- | --- |
| `agent_overrides` keys under the `devflow:` namespace (see [`review-agent-overrides.md`](review-agent-overrides.md)) | the same leaf under `prflow:` |
| a `workpad_marker` opening `<!-- devflow:` | the same marker opening `<!-- prflow:` |
| a `DevFlow` entry in `docs.labels` / `deferred.labels` | `PRFlow` |

Each is safe because every reader accepts both spellings in both directions — the subagent namespaces, the workpad-marker readers (including the self-trigger guard, which derives the superseded marker from whichever one you configure, so a workpad written before the rename is still recognised), and label selection, whose API-side filter already asks for both in one `label:PRFlow,DevFlow` query. Existing issues and pull requests keep whatever label they carry; only the label *applied to new artifacts* changes, so rename the GitHub label itself (which carries it across every artifact already using it) if you want them to agree.

The pass runs at the end of every scaffold, so it reaches both `install.sh --apply` and `/prflow:init` — both call the one scaffolder. It is idempotent, takes no freshness gate (unlike the key migration, nothing reads these spellings out of your workflow files), preserves a deliberately-falsy value rather than coercing it onto a default, and rewrites nothing else. If you have both spellings of one `agent_overrides` key and the current-spelled entry is a real edit rather than a scaffolded default, that one key is **refused** and reported so you can delete whichever you meant to drop; everything else still migrates.

Three things it deliberately leaves alone, and says so once when your config carries them:

- **`workflows.devflow` / `workflows.devflow-review`** (now `workflows.prflow` / `workflows.prflow-review`) — your workflow files read those key names, and a renamed key reads as *disabled*, so a rename that moved ahead of a stale workflow would silently switch the workflow it toggles off. This value pass therefore leaves them alone; they are migrated instead by the **freshness-gated key migration** (issue #1041), which refuses to move them while any shipped workflow still reads the superseded spelling and names `install.sh --apply` as the remedy — so the config key and the workflow read only ever move together.
- **A `devflow`-spelled `allowed_bots` entry** — that is a real GitHub login, and renaming it breaks authorization unless the account itself was renamed.
- **The `DEVFLOW_*` environment identifiers** — variables, secrets and shell overrides that live outside the repository, where no config migration can reach them. Nothing reads a `PRFLOW_*` equivalent, so renaming one removes the setting rather than moving it, and most fail silently. That inventory is not restated in the notice: `lib/generate-env-freeze-advisory.py` renders it from `lib/rename-map.json`'s `frozen.env_identifiers` (see also [`cloud-setup.md`](cloud-setup.md)).

### The opt-in rename sweep for stale product-name prose

The mechanical migration and the config-values pass rename the forms `lib/rename-map.json` enumerates. Neither classifies ordinary prose, so a migrated repository can still carry `DevFlow` as its written product name in READMEs, comments, and notes. After the migration reports terminal `APPLIED`, `/prflow:init` **offers** a repository-wide **semantic sweep** that finds and repairs those stale mentions. It is model-driven prose classification, kept deliberately separate from the deterministic migration helper (which is unchanged) and from the protected-literal map (which stays the *don't-touch* authority, never widened by the sweep). It is offered on terminal `APPLIED` only — never after a preliminary `PLAN`/`PREVIEW`, and never after `NOTHING TO MIGRATE`, `REFUSED`, a migration exit 2, or unrecognized helper output.

- **Model-access disclosure, then consent.** Consent to the migration's edits is not consent to model access. Before reading anything, init discloses that the sweep reads the **contents** of tracked, untracked, **and git-ignored** files — that ignored files can hold secrets and private material, and that this content enters the model's context — and that you review the diff **after** that access. Candidate enumeration and the first content read begin only on an explicit yes. A **declined** sweep, and an **unavailable interaction** (a non-interactive run), make **no** sweep writes and init continues.
- **Candidate population.** Three NUL-delimited Git queries — `git ls-files --cached -z` (tracked), `git ls-files --others --exclude-standard -z` (untracked, non-ignored), and `git ls-files --others --ignored --exclude-standard -z` (ignored) — merged and de-duplicated as raw path records (never converted to newline-delimited text, so a pathname with a newline byte survives). Each query must **exit 0** and each non-empty stream's final record must be **NUL-terminated**; a non-zero exit, a truncated stream, or one arm failing while the others succeed is the **enumeration failure** incomplete stop below, taken before the manifest is written and before any candidate is read — a partial result is never taken as the full population.
- **Exclusions.** Semantic inspection and replacement exclude `.git/`, `.prflow/`, `.devflow/`, plugin-managed vendor trees, any path outside the repository root, and external symlink targets. The sweep's own bounded ledger writes under `.prflow/tmp/init-rename-sweep/` are the one exception to the `.prflow/` write exclusion.
- **Pinned authority.** The sweep reads `lib/rename-map.json` from the **installed plugin** (through the skill-base path rules, not a consumer-root `lib/`), pins its Git object ID in the ledger, and re-hashes and re-checks it before every mutation batch — a mismatch stops the sweep incomplete before touching another candidate. The pinned value is validated as a non-empty 40-character lowercase hexadecimal object ID when it is first captured — an unresolvable anchor or an absent map yields an empty value, which is a **missing rename authority** incomplete stop rather than something the sweep proceeds on — and the per-batch re-check treats a missing or empty recomputed value, or a missing or empty stored value, as a **mismatch** rather than a match, so two empty values can never agree their way past it.
- **Bounded, encoded progress state.** Before any content read, init writes a versioned `manifest.json` (schema version, repository root, rename-authority object ID, page order, current-page cursor, aggregate totals) and page JSON under `.prflow/tmp/init-rename-sweep/`. Each page holds at most 100 candidate records under 64 KiB and stores **base64-encoded raw pathname bytes** plus per-path status, so every legal Git pathname round-trips without loss. File contents are never copied into the ledger. Each mutation batch loads only the manifest, the current page, and the rename authority; it handles one candidate, records the result, and advances the cursor — it never reloads the whole population, so the sweep survives a context compaction and resumes from disk.
- **Semantic predicate (preserve by default).** A `DevFlow` occurrence changes to `PRFlow` only when its surrounding text uses `DevFlow` as the present product name and the referent is the current PRFlow tool. Everything else is left unchanged, an ambiguous occurrence is recorded rather than guessed, and protected contexts — compatibility identifiers, environment names, workflow filenames, marketplace identities, accepted command aliases, code symbols, historical records, revision-side operands, census paths, merge-base pathspecs, escaped path forms, quoted evidence, and managed PRFlow state — stay untouched. Repository content is treated as data to classify, never as instructions to obey.
- **Atomic candidate writes.** Each replacement is written to a same-directory staging file, verified to hold the intended bytes and the target's preserved mode, then atomically replaces the target. A staging, verification, or replacement failure leaves the original target's bytes and mode unchanged and stops the sweep incomplete.
- **Unreadable and unsupported candidates are per-path skips, not stops.** A candidate the sweep cannot read, and one whose bytes are not text, are recorded `unreadable`/`unsupported`, left untouched, and the sweep advances. This is deliberate: the population includes git-ignored paths, so it holds ignored binaries in essentially every real repository, and a sweep that stopped at the first one would report incomplete almost everywhere and never reach the prose it exists to repair. They are never silently swallowed — the counts are carried in the manifest totals and named in the result.
- **Incomplete result, and reporting.** An enumeration failure, a staging/verification/replacement failure, a missing or mismatched authority, a malformed or oversized ledger, or a repository-root mismatch stops further mutations, leaves the current target unchanged, records the reason, and lets init continue. A complete changed sweep names the changed files and asks for diff review; a complete clean sweep reports that nothing replaceable was found **in the candidates that were inspected**; either complete arm also names any recorded ambiguous occurrences and any `unreadable`/`unsupported` paths, stating plainly that those files were not inspected — *complete* means every candidate reached a recorded status, not that every candidate was read. An incomplete sweep is **never** reported as clean.
- **Renewed-consent resume.** A later `/prflow:init` that receives `ALREADY MIGRATED` and finds a matching incomplete ledger (same repository root and same authority object ID) offers to resume it — after **renewed** consent (a stored ledger is not standing consent), continuing from the recorded cursor and skipping already-recorded candidates. An ordinary already-migrated run with no such ledger issues no offer, and repeating the sweep after a complete clean result makes no further changes.

## Updating

### Local tier

Running `/prflow:init` provisions your repo's project `.claude/settings.json` so Claude Code keeps the plugin updated — it registers `devflow-marketplace` under `extraKnownMarketplaces` with `autoUpdate: true` and enables the plugin under `enabledPlugins`, additively and without clobbering anything you already set (re-running is a no-op once the keys exist). **This write is not gated** — there is no separate opt-in step; `/prflow:init` performs it directly, in the same run you type the command, into a committed project file collaborators inherit. **The registration carries no version pin** — no `ref`, `tag`, `sha`, nor `version` — so the plugin auto-updates from the marketplace repo's default branch (`autoUpdate: true`), which means a change on that branch changes what runs in your editor. Review the change before committing. The provisioned block looks like:

```jsonc
{
  "extraKnownMarketplaces": {
    "devflow-marketplace": {
      "source": { "source": "github", "repo": "The01Geek/prflow" },
      "autoUpdate": true
    }
  },
  "enabledPlugins": { "prflow@devflow-marketplace": true }
}
```

Or update on demand: `/plugin marketplace update devflow-marketplace`.

If you run Claude Code against a **third-party model provider** (Amazon Bedrock, Google Vertex AI, or Microsoft Foundry), `/prflow:init` can also — **only with your explicit consent** — make `auto` permission mode **selectable** in the Shift+Tab cycle by adding `CLAUDE_CODE_ENABLE_AUTO_MODE="1"` to your **user-global** `~/.claude/settings.json` (it must live at user scope; Claude Code ignores it in a project file). This is *selectable, never on*: it writes no `permissions.defaultMode`, so you still choose `auto` yourself and plan/model/admin gates still apply. It asks before touching the user-global file, preserves a deliberately-disabled `"0"` (never flips it to `"1"`), and is idempotent, atomic, and fail-closed; decline and it just prints the one-line setting for you to add yourself. On the **Anthropic API this step is skipped entirely** — `auto` mode is already available there by default, so the env var would do nothing.

### Cloud tier

Bump `prflow_version` in `.prflow/config.json` to a newer tag, branch, or commit SHA (the workflows fetch that ref at runtime), or just re-run the same `install.sh` — now a small diff, since it refreshes the workflows/actions without committing the plugin tree, and keeps your config. Re-running only re-stamps `prflow_version` itself when the existing value is empty or already looks like a commit SHA; a hand-set non-SHA value (a branch name, a tag) is preserved — see [`cloud-setup.md`](cloud-setup.md#install-and-update-the-cloud-tier) for the exact rule. (The plugin must be at the literal workspace path when CI runs because a marketplace install isn't reachable from the Actions sandbox; the `vendor-plugin` action satisfies this at runtime — see [`cloud-setup.md`](cloud-setup.md#why-the-plugin-lives-at-a-workspace-path-not-added-as-a-github-marketplace-in-ci).)

#### An upgrade is dry-run by default, and never overwrites your local edits

Re-running `install.sh` in a repository that already carries a PRFlow installation is an **upgrade**, and an upgrade **writes nothing until you ask it to**. It prints the plan and a unified diff of the bytes it would change, then stops:

```bash
DEVFLOW_REF=<newer-ref> bash devflow-install.sh              # preview: plan + diff, no writes
DEVFLOW_REF=<newer-ref> bash devflow-install.sh --apply      # make the changes
```

A **first-time** install still applies immediately, so the one-liner above is unchanged; `--dry-run` forces the preview there too if you want to see an adoption before any file exists. `DEVFLOW_DRY_RUN=1` / `DEVFLOW_APPLY=1` select the same modes for a `curl | bash` invocation that cannot pass a flag. The preview is not a second implementation of the plan — it runs the real install into a sandbox copy of your own tree and diffs it, so anything `--apply` would do, the preview already did to a copy.

The diff covers `.claude-plugin/`, `.github/`, `.prflow/`, `.claude/plugins/` and your repository-root `.gitignore` — the paths the installer writes, including the recursive removal of a stale pre-relocation `.claude/plugins/devflow` tree. **One documented exclusion:** under `DEVFLOW_VENDOR=1` the vendored plugin tree under `.prflow/vendor/` is thousands of files, so its churn is reported as a single plan line rather than as a diff body. Your own `.claude/` files (settings, skills, hooks) are neither written nor diffed.

The sandbox carries the installer's own subtrees, so the language auto-detection step reads your **real** tree for its marker files (`package.json`, `composer.json`, `docker-compose.yml`, …) and previews the `config.json` merge it would actually perform. The preview reads your repository in several places — to build the sandbox, to render the diff, and now to detect your languages — but it writes only into the throwaway copy.

**Your hand-edits survive.** Every artifact the installer owns — the local `marketplace.json`, the two workflows, the three composite actions — is recorded in `.prflow/install-manifest.json` with the sha256 of the bytes the installer wrote. Commit that file; it is what lets the next upgrade tell an untouched artifact from one you edited:

| What the installer finds | What it does |
| --- | --- |
| bytes match the recorded digest | updates it in place (`update`) |
| already identical to the new version | leaves it alone (`unchanged`) |
| bytes differ from the recorded digest | **preserves your file** and writes the new version to `<path>.prflow-new` for you to merge |
| no recorded digest — an installation predating the manifest, or a skipped-version jump | same: preserves your file and offers `<path>.prflow-new`, because a local edit cannot be ruled out |
| your file's **current** bytes cannot be digested — no working `python3` on this host, an unreadable file, a read error inside a composite-action directory | same: preserves **that file** and offers `<path>.prflow-new`. Reported distinctly (`provenance UNESTABLISHED`), and the message names which of the two causes applied, because they have different remedies. How much else is affected depends on the cause — see the two rows below the table |
| absent (you deleted it) | recreates it |

**Two different situations reach that third row, and they differ in how much they affect.** Both preserve your bytes; only the first is repository-wide.

| Cause | What happens to the rest of the upgrade |
| --- | --- |
| **No working `python3`** — stock Windows / Git-Bash, before you run the shim provisioner. Nothing on the run can be digested. | **Everything** is preserved, each with a `<path>.prflow-new` sidecar, and **no manifest is written** (so the next upgrade preserves everything again until you resolve `python3`). The dry run cannot render its diff either — read the plan lines, which name every artifact that would be preserved. |
| **A read error on one file**, with `python3` working — an unreadable file, or one unreadable file inside a composite-action directory. | **Only that artifact** is preserved. Everything else is classified and written exactly as usual, and **the manifest is still written** — the preserved artifact simply keeps its previous entry instead of being re-recorded. Fix that path's permissions and re-run. |

Whether a file *exists* is decided without `python3` in both cases, so a genuinely absent artifact is still created and a first-time install on such a host still works normally; what an unreadable digest costs you is the *comparison*, never your bytes.

`.prflow/config.json` is outside that mechanism entirely: the shared scaffolder only ever backfills keys the shipped example gained, so your values and tuned arrays are never rewritten. A preserved conflict is reported again on every run until you resolve it — the installer never adopts your edited bytes as its own provenance.

Skipping versions is safe: the classification above depends on the recorded digest, not on how far behind you are.

**Two install-time marker files, different jobs — don't confuse them.** The installer writes two sha256-bearing JSON files under `.prflow/`, and they answer different questions:

- **`.prflow/install-manifest.json`** — the **per-artifact hand-edit provenance** described just above. It records the digest of the bytes the installer wrote for *each* artifact it owns (the local `marketplace.json`, the workflows, the composite actions), so the next upgrade can tell an untouched artifact from one you edited and preserve your edits. It is upgrade-safety bookkeeping and grows an entry per owned artifact.
- **`.prflow/install-state.json`** — the **lint-provisioning compatibility marker** (issue #1388), a single digest-bound *tuple* published **last**, only after the staged `.prflow/lint-manifest.json` validates. It binds the lint manifest, its readers (`scripts/lint_manifest.py`, `scripts/lint_provision.py`, `scripts/install_state.py`), the `setup-project-env` composite action and its `provision-lint-tools.sh` helper, and the implement workflow (`.github/workflows/devflow-implement.yml`) by sha256, recording the **runtime path** each component will occupy. Because the workflows/manifest ship via `install.sh`'s copy loop while the readers ship via the runtime vendor fetch (`.prflow/vendor/prflow/scripts/…`), that install-channel skew is exactly what the tuple exists to reconcile: `setup-project-env`'s lint-provisioning phase refuses to provision when this marker is absent, a component digest disagrees, or the manifest is missing (fail-closed, before the model runs). This repository's own committed copy is regenerated by `lib/generate-install-state.py` (which hardcodes the primary repo root and is not a consumer-facing command — a consumer's marker is republished by re-running `install.sh`), and both it and `.prflow/lint-manifest.json` ship to consumers (re-included past the `/.prflow/*` ignore rule). If the manifest does not validate, the installer does **not** publish the marker, so lint provisioning stays fail-closed until the installer is re-run.

**An installation with no manifest at all heals only partly on its first upgrade, and it is worth knowing which part.** Without a recorded digest there is nothing to compare against, so the table's fourth row applies to every artifact whose bytes differ from the version being installed — whether you edited it or it is simply older. Those are preserved with a `<path>.prflow-new` sidecar and are **not** recorded. Only artifacts already byte-identical to the shipped version take the `unchanged` row, and those are recorded. So on a release that changed a workflow, a pre-manifest installation gets a sidecar for that workflow and a manifest covering everything else.

To finish healing an artifact you never edited, do either of these and re-run — both record its digest:

- **move the sidecar over it** (`mv .github/workflows/devflow.yml.prflow-new .github/workflows/devflow.yml`) — the next run sees `unchanged`;
- **delete it** and let the installer write its own copy — the next run sees `create`.

Merge a sidecar by hand instead and the result still differs from the shipped bytes, so it stays `unverified` and is offered again next run — that is the same deliberate rule as an edit made *with* a manifest: the installer never adopts your bytes as its own provenance. Note also that a healing run does not tidy up: the old `<path>.prflow-new` is left where it is, so delete it yourself once you are done with it. Nothing is at risk either way — what a missing manifest costs you is sidecars to resolve, never overwritten bytes.

**Sidecars are gitignored, so leaving one in place is safe.** A sidecar is an untracked file (or a whole untracked directory, for a preserved composite action) sitting inside your own `.github/`, which a later `git add -A` would otherwise sweep into an unrelated commit. So the installer appends one block to your repository-root `.gitignore`:

```gitignore
# PRFlow install.sh: preserved-artifact sidecars (never commit these)
*.prflow-new
*.devflow-new
```

Your own content is never rewritten — the block is appended once and re-runs are byte-identical no-ops, a rule you already carry is not duplicated, and the superseded `*.devflow-new` spelling is covered because sidecars written before the `.devflow` → `.prflow` rename are still on disk. If your `.gitignore` is a **symlink** — or anything other than a plain file — the installer says so and carries on rather than touching it, because appending follows the link and could write outside your repository altogether; add the two patterns by hand there. This is a standing rule, not a cleanup: keeping your own version of an artifact means leaving its sidecar there indefinitely.

#### Upgrade note: a superseded App slug in `devflow.allowed_bots` is reported, and `/prflow:init` corrects it

The GitHub App that authors PRFlow's PRs was renamed `devflow-autopilot` → `prflow-implementer` (the app id you set as `DEVFLOW_APP_ID` is unchanged). Actor authorization compares bot logins for **equality**, so if you added the old slug to `devflow.allowed_bots` it now authorizes nothing — and the failure is silent, one run later: the implement and review stall-backstops post their resume comment successfully and finish green, then the gate that comment re-enters declines the App as an unknown actor, so the run never resumes.

The config scaffolder is add-only — it backfills newly-added keys and never rewrites a value — so an upgrade cannot fix this on its own. `install.sh` therefore **reports** it and routes you to the one place that owns the correction:

```
devflow-install: NOTICE: .prflow/config.json still names superseded PRFlow identifiers
(devflow.allowed_bots[devflow-autopilot -> prflow-implementer]). …
```

Run `/prflow:init`. It corrects the entry in place, preserves every other value, tells you exactly what it changed so you can review the diff before committing, and is a no-op on a config that is already correct. The installer never rewrites `.prflow/config.json` for this — same detect-and-route split it uses for `.claude/settings.json`.

#### Upgrade note: the withheld automatic-review tier is surfaced, and removable on request

If your repository installed the automatic pull-request-triggered review tier before it was withheld (issue #936), you still have `.github/workflows/devflow-review.yml`, `devflow-runner.yml` and `telemetry-push.yml`, they still run, and they keep you exposed to issues [#930](https://github.com/The01Geek/prflow/issues/930) and [#920](https://github.com/The01Geek/prflow/issues/920). Every upgrade now says so. Nothing is deleted unless you ask:

```bash
DEVFLOW_REF=<newer-ref> bash devflow-install.sh --apply --remove-withheld-review-tier
```

That deletes the three workflow files (only when they carry a PRFlow signature — a same-named file of your own is left alone) and sets `workflows["prflow-review"]` to `false` in `.prflow/config.json`. **It cannot do the third step:** remove the `Devflow Review` context from any branch protection rule or ruleset that requires it, or every later pull request wedges against a required check nothing will report. Do that yourself, in the same change. Full background: [`workflow-triggers.md`](workflow-triggers.md).

#### Upgrade note: re-sync the workflow `TOOLS` grants for the Phase 0.6 stale-prose lint

The shared review engine's **Phase 0.6** (deterministic stale counted-prose lint) runs two vendored helpers: `scripts/stale-prose-lint.py` (the lint itself) and `scripts/match-lint-adjudications.py` (the cross-run false-positive adjudication join added in issue #466 — it demotes a STALE row a prior trusted run already adjudicated a false positive). Both invocations must be granted to the review runner. When upgrading an existing install **past this version**, re-sync your installed workflow `TOOLS='…'` grants — in `.github/workflows/devflow-runner.yml` (auto-review path) and `devflow.yml` (manual `/prflow:review` comment path) — to include both:

```
Bash(.prflow/vendor/prflow/scripts/stale-prose-lint.py:*)
Bash(.prflow/vendor/prflow/scripts/match-lint-adjudications.py:*)
```

Until you do, Phase 0.6 emits the **named-remedy degradation note** (harness-refused arm — it names the missing grant and remedy key) rather than silently skipping: the review still completes, but the affected step (the stale-prose lint, or the adjudication carry-forward) does not run — a missing adjudication grant leaves every STALE row at its configured severity.

**Skew diagnostic — read the region banner.** As of PRFlow's capability-profile manifest (issue #561), each generated allowlist literal in the shipped workflows carries a banner comment immediately above it — `# devflow-capability-manifest: region=<id> manifest_version=<N> sha256=<hex>` (for the `devflow-implement.yml` base list the banner sits above the `claude_args:` key that contains the literal, where it is syntactically inert). When you report or debug a grant mismatch, quote that `manifest_version` + `sha256` from your installed `.github/workflows/*.yml` copy: it identifies exactly which policy version your workflows were generated at, so a skew against the current release is diagnosable at a glance. Consumers do **not** run the generator (their tree carries no runnable copy) — the remedy stays the consumer-executable one above (hand-add the grant to your installed workflow copy, or re-run `install.sh` to refresh the workflow files); the banner is only the diagnostic that tells you a refresh is needed.

**Config bridge — only on a provisioned reviewer.** `devflow-runner.yml` does append `prflow_runner.allowed_tools` to the review profile post-floor (after the reviewer deny-list floor strips tree-mutation tools), so adding the same `Bash(.prflow/vendor/prflow/scripts/stale-prose-lint.py:*)` and `Bash(.prflow/vendor/prflow/scripts/match-lint-adjudications.py:*)` entries to `prflow_runner.allowed_tools` in `.prflow/config.json` grants the helpers — **but that append sits inside the `prflow_runner.provision_env` gate, and `provision_env` defaults to `false`.** On a default (read-only, unprovisioned) reviewer the config entry is therefore never appended, and Phase 0.6 keeps reporting the harness-refused degradation note. So: if you already run the reviewer with `prflow_runner.provision_env: true`, the config entry bridges a lagging installed workflow; otherwise it changes nothing and **re-syncing the workflow `TOOLS` line above is the only remedy** (it is the durable fix either way). Do not turn `provision_env` on merely to bridge this grant — it is a security-sensitive opt-in that runs untrusted PR build code under a write token.

#### Upgrade note: `/prflow:review-and-fix` now auto-loads your `receiving-code-review` extension (audit yours before bumping)

From this version, `/prflow:review-and-fix` loads `.prflow/prompt-extensions/receiving-code-review.md` at skill entry, in addition to its own `review-and-fix` extension — and that covers every path entering through the skill's preamble — including the **implement Phase 3 inline run** and the Step 2.6 shadow entry, both of which are unattended. Previously that file loaded only on a direct `/prflow:receiving-code-review` invocation, so an extension written for a human-in-the-loop pass could safely assume an operator was present. Before bumping `prflow_version`, audit an existing reception extension on two axes:

- **Content.** A directive written for an interactive direct pass — a confirmation step, an operator prompt, a pause for input — now reaches autonomous fix loops. The shipped scoping prose classifies such directives as non-binding context that a loop surfaces in its record rather than executes, but that is a mitigation, not a licence: prose that *reads* as a required interactive step is still the cheapest thing to rewrite before the bump. Same for any rule that makes a mutable third-party text authoritative; the scoping prose weighs such a supersession by its author's repository write permission and routes the rest to the loop's deferral channel.
- **Deliverability.** Confirm `.prflow/vendor/prflow/scripts/load-prompt-extension.sh receiving-code-review` exits 0 in your repo. An **absent** file is the loader's documented silent no-op and needs nothing. But a file that exists and cannot be delivered — a dangling symlink, a non-regular file, an unreadable mode — is refused loudly with a non-zero exit, and after this bump that refusal reaches **every autonomous fix loop that enters through the skill preamble**, where before it could only affect a direct pass. What the skill mandates on that arm is that the run surface the loader's stderr and never proceed silently — so the refusal becomes a visible entry-time failure on those loops, not a silently absent policy surface.

Repos with no `.prflow/prompt-extensions/receiving-code-review.md` are unaffected: the load is the documented no-op.

#### Upgrade note: the review tier reads its prompt extensions from your BASE ref (a TWO-halves upgrade — the window is real)

From this version, neither cloud tier that runs the review engine reads your `.prflow/prompt-extensions/` files from pull-request content. Whatever the loader prints becomes instructions appended to the reviewing agent's own prompt, so a PR author could otherwise write the instructions of the agent that reviews — and, on `/prflow:review-and-fix`, fixes and pushes — their own pull request.

The **automated** runner (`devflow-runner.yml`) checks out the pull request's head, so it materializes `review.md` and `requesting-code-review.md` from your **trusted base ref** into a `$RUNNER_TEMP` closure, points the loader at it with `DEVFLOW_PROMPT_EXTENSION_ROOT`, and — unconditionally, including on a failed base-ref fetch, an empty base ref, and an unresolvable materialization helper — truncates the workspace copies so an older loader finds nothing.

The **shipped comment-driven tier** (`devflow.yml`'s `command` job — `/prflow:review`, `/prflow:review-and-fix`, `/prflow:pr-description`) does the same materialization for all five extensions those commands can load, but reaches the problem differently: its own checkout is your default branch on an `issue_comment` trigger, and it is `/prflow:review-and-fix`'s branch sync that moves the working tree onto the pull-request head part-way through the run. Because that tier commits and pushes, it deliberately does **not** truncate your workspace copies (that would dirty the tree the branch sync requires clean, and the fix loop would commit the truncation); it warns loudly instead when the plugin version you pinned is too old to honor `DEVFLOW_PROMPT_EXTENSION_ROOT`. Consequence to expect on both tiers: a pull request that edits a prompt extension does **not** change its own review run — the change takes effect after merge. Residuals neither tier closes are enumerated in `docs/internal/DEVFLOW_SYSTEM_OVERVIEW.md`'s base-ref-trust-boundary bullet.

This is a **two-halves** upgrade, and unlike most of the ones above the halves ship through *different* channels: the workflow arrives by re-running `install.sh` (a file copy), while the loader that honors the variable arrives by advancing `prflow_version` (the vendor fetch). Both halves are individually safe, but they are not equivalent:

- **Workflow only (you re-ran `install.sh` but did not bump `prflow_version`).** The truncation and the variable export are live, but your pinned loader ignores the variable and resolves the repo root — where it finds the truncated file. **Your committed `review.md` stops loading** until you bump. That is the boundary working as designed (the truncation is what protects a consumer stuck on an older pin), but it is a real functional loss, not a no-op: bump `prflow_version` in the same change if you rely on a review extension.
- **Loader only (you bumped `prflow_version` but did not re-run `install.sh`).** Nothing exports the variable, so the loader takes its repo-root branch and behaves exactly as before — including reading the PR-head copy. You gain the loader's new branch and none of the protection.

Two further consequences worth knowing before you bump. `prflow_version` itself is now read from the base ref on the review tier, which makes it **in-PR-inert there** via the base-ref trust boundary — the same channel `prflow_runner.allowed_tools` uses, not the separate trigger-time-resolved channel (which is `devflow-implement.yml`'s `config` job checking out the *default branch* at trigger time; the two resolve different values for a PR targeting a non-default branch). A PR that bumps `prflow_version` does not change its own review run, only later ones. And a consumer that has never committed a prompt extension is entirely unaffected and sees **no warning** — the base ref simply carrying no such file is the ordinary shape, not a failure.

#### Upgrade note: the cloud implement-tier label grants are a TWO-halves upgrade (take both together)

Issue #455 fixed a cloud `/prflow:implement` defect where the run's best-effort label applies (`PRFlow` provenance, `Documented`, the configured `deferred.labels`) were **silently denied** — the phase-4 label loops emitted command *shapes* the read-write implement matcher refuses (a `for`/piped-`while read` loop or a `VAR="$(…)"` capture wrapping a label helper), and the label helpers were granted only via a config `*/basename` glob the matcher does not match against a vendored-literal leading token. The fix has **two halves that ship on two independently-updated artifacts**, and both must be taken together:

1. **The workflow grants** — `.github/workflows/devflow-implement.yml`'s baked `--allowed-tools` literal now grants `Bash(.prflow/vendor/prflow/scripts/apply-labels.sh:*)` and `Bash(.prflow/vendor/prflow/scripts/ensure-label.sh:*)` in the explicit vendored-literal leading-token form the implement-probe table proved PERMITTED. This half arrives by **re-running `install.sh`** (it refreshes the workflow files).
2. **The skill rework** — all four label call sites (Phase 3.1's `PRFlow` provenance apply, Phase 4.0/4.0.5's `deferred.labels` applies, and Phase 4.1's `Documented` apply) are reworked to permitted single-leading-token agent-level calls. This half arrives by **bumping `prflow_version`** (the workflows fetch the skill from that pinned ref at runtime).

**Skew symptom — silent label-apply denial.** If you take only *one* half, cloud implement runs keep hitting the wall the issue fixed: bump `prflow_version` without re-running `install.sh` and the reworked skill emits the granted-literal calls but the workflow still lacks the grants; re-run `install.sh` without bumping `prflow_version` and the workflow grants the helpers but the vendored skill still emits the denied loop/capture shapes. Either way the applies are refused with no error and the PR/deferred issues silently carry none of the configured labels. Take **both** halves in the same upgrade.

**Issue #555 adds the deferral-discovery helper to the same two-halves shape — and this one fails *loudly*.** Phase 4.0.5 no longer discovers deferrals manifests with a multi-root `find` (whose masked exit status made a failed search read as the clean no-op); it invokes `scripts/discover-deferral-manifests.py`, which classifies each candidate root independently and carries discovery status in its exit code. The **workflow grant** — `Bash(.prflow/vendor/prflow/scripts/discover-deferral-manifests.py:*)` in `devflow-implement.yml`'s baked `--allowed-tools` — arrives by **re-running `install.sh`**; the **fence rework** (the helper capture, `DISCOVERY_STATE`, the `discovery=` sentinel field, and the fail-closed reader-routing arms) arrives by **bumping `prflow_version`**. Skew symptom: a consumer holding only the skill half has the reworked fence but no grant, so the discovery statement is refused, produces no output, and lands in the reader-routing fail-closed `discovery=[]` exit — a recorded `dropped-failed` reflection and nothing filed, **not** the silent loss the old shape produced. Take both halves in the same upgrade to get filing back. Issue #1374 adds a second mode to that same helper (`--presence-for-pr N`, the predicate gating Phase 4.0.5's now-relocated filing procedure); the grant above is a **prefix** grant, so it already covers it and no allowlist change is owed. A consumer holding only the skill half reaches the predicate's fail-closed unestablished arm, which reads the reference anyway.

**Issue #668 adds the receiving-review session-artifact producer on the same two-halves shape.** The `receiving-code-review` skill's Reception Preflight invokes `scripts/reception-record.py` (which imports `scripts/reception_identity.py`) to derive a content-based candidate identity, mint a claim-context nonce, and write session artifacts. The **workflow grant** — `Bash(.prflow/vendor/prflow/scripts/reception-record.py:*)` in the `implement` and `command` capability profiles' generated regions — arrives by **re-running `install.sh`** (it refreshes the workflow files). The **helper plus skill rework** — the two new `scripts/` files and the eleven-fact preflight prose — arrive by **bumping `prflow_version`** (the workflows fetch them from that pinned ref at runtime). Skew symptom: a consumer holding only the skill half has the reworked preflight but no grant, so on cloud autonomous surfaces the helper is silently denied and produces no output — the candidate-identity and claim-context facts render `missing` and the run continues (a **visible** degraded outcome, not a false pass). Take both halves in the same upgrade to record the session identity.

**Issue #550 adds the completion-evidence check on the same two-halves shape.** The `receiving-code-review` Verification Gate and the `review-and-fix` Loop Exit now run `scripts/check-completion-evidence.py` to validate a completion claim against producer-owned evidence and quote its verdict line. The **workflow grant** — `Bash(.prflow/vendor/prflow/scripts/check-completion-evidence.py:*)` in the `implement` and `command` capability profiles' generated regions (`devflow.yml`'s hoisted `TOOLS` and `devflow-implement.yml`'s baked `--allowed-tools`; the read-only review profile in `devflow-runner.yml` is deliberately untouched, as the fix loop does not run under it) — arrives by **re-running `install.sh`** (it refreshes the workflow files). The **validator plus skill/loop rework** — the new `scripts/check-completion-evidence.py` and the fifth Verification-Gate evidence item plus the Loop-Exit integration — arrive by **bumping `prflow_version`** (the workflows fetch the plugin tree at that pinned ref at runtime). Skew symptom: a consumer holding only the skill half has the reworked gate but no grant, so on cloud runs the validator is silently denied and produces no verdict line — which the gate's no-output-is-degraded rule converts into a visible `degraded: unvalidated (<reason>)` outcome, **never a silent pass**. Take both halves in the same upgrade so a completion claim carries a real, quoted verdict.

#### Upgrade note: the #484 implement-profile grant wave arrives by re-running `install.sh`

**Issue #547 adds a second two-half upgrade.** The early Phase 1 dependency
preflight uses `scripts/preflight.py`, while its explicit cloud grant is in
`.github/workflows/devflow-implement.yml`. Re-run `install.sh` for the grant
and update `prflow_version` for the helper and phase procedure.

Issue #484 granted the bundled helpers used by cloud implement runs on the implement profile (`devflow-implement.yml`). Phase 3's inline review engine calls `stale-prose-lint.py`, `match-lint-adjudications.py`, and `load-prompt-extension.sh` (on the implement profile this is the **vendored-literal** `.prflow/vendor/prflow/scripts/load-prompt-extension.sh` grant — the directory-agnostic `Bash(*/load-prompt-extension.sh:*)` wildcard is carried only by the `review` and `command` profiles, not implement); `react-to-trigger.sh` runs in the trigger-reaction fence, and `extract-doc-needed-paths.sh` runs in Phase 4.1. The exact issue-mandated grant set also contains `dismiss-stale-rejections.sh`, but its call is in standalone-only review Phase 4.4 and inline implement review stops after Phase 4.3. The normal inline flow therefore does not invoke it, although the grant makes the capability available to the inline session; the source guard deliberately over-approximates the shared fenced source and requires the grant for parity. The wave also granted `cmp` and `git hash-object` for the inline review engine, plus `gh pr checkout` in `devflow.yml` for the manual `/prflow:review-and-fix` path. **This grant wave arrives by re-running `install.sh`** (it refreshes the workflow files), **not by bumping `prflow_version`** — `install.sh` copies `.github/workflows/devflow-*.yml` into the consumer repo, while `prflow_version` fetches only the plugin tree (`skills/`, `scripts/`, `lib/`). The companion skill reworks (anchored `workpad.py` fences, the leading-token `react-to-trigger.sh` emission, the §4.1 docs-commit fence) DO arrive by bumping `prflow_version`.

**Skew symptom — silent inline-engine denial.** Bump `prflow_version` without re-running `install.sh` and the reworked skills run but the older workflow copy still lacks the grants — the Phase 3 stale-prose gate and the four other runtime helpers stay **silently denied** on every cloud implement run (no error; the steps just don't run). Take the grant wave by re-running `install.sh`. A `lib/test/run.sh` head guard (#484) pins the fenced-command surface — it fails when an emitted head is neither granted nor named in the exact deliberately-withheld list.

**The cloud plugin-parity compose (issue #505) is the same two-halves shape.** The composing steps live in the workflow YAML (`.github/workflows/devflow-implement.yml`, `devflow.yml`, `devflow-runner.yml`) and ship by **re-running `install.sh`** (it refreshes the workflow files); the helpers they invoke (`scripts/resolve-extra-plugins.sh`, `scripts/describe-plugin-compose.sh`) live in the plugin tree and ship by **bumping `prflow_version`** (the `vendor-plugin` action fetches them at the pinned ref at runtime). Take both halves together: bump `prflow_version` without re-running `install.sh` and the vendored helpers exist but the workflows still bake the static baseline; re-run `install.sh` without bumping `prflow_version` and the workflows compose but the helper is absent — the composing step's skew arm emits a `::warning::` and proceeds with the baked plugin baseline (no plugins are silently lost, but the settings-declared extras are not composed until both halves land). On the two write tiers (`devflow-implement.yml`, `devflow.yml`) that warning names `prflow_version` as the remedy; on the read-only review tier (`devflow-runner.yml`) the fail-closed arm instead names the trusted-source rule (`vendor_source` / landing the re-vendor on the base ref), because the review tier resolves the helper only from a trusted source and never from a `prflow_version`-pinned PR-head copy.

#### Upgrade note: the #556 verdict-normalizer is a TWO-halves upgrade (silent on skew — take both together)

Issue #556 added the bundled helper `scripts/normalize-verdicts.py` and granted its vendored-literal invocation in the review/implement/command allowlists. The **workflow grants** ship by **re-running `install.sh`** (it refreshes `.github/workflows/devflow-*.yml`); the **helper and the reworked review-engine phase files** (`agents/checklist-*.md`, `skills/review/phases/phase-2-verification.md`, `phase-4-verdict.md`) ship by **bumping `prflow_version`** (the `vendor-plugin` action fetches the plugin tree at the pinned ref at runtime). A skew degrades **fail-closed** per the engine's three-way degradation split: bump `prflow_version` without re-running `install.sh` and the reworked engine invokes the helper but the older workflow copy lacks the grant — the invocation is silently denied, so Phase 2.2 proceeds with **zero normalization** (raw verdicts) plus one warning line naming the grant remedy; re-run `install.sh` without bumping `prflow_version` and the workflow grants a helper the vendored plugin does not yet carry — the invocation prints an rc-127 `No such file` error and the engine again proceeds with zero normalization and a named remedy. Neither skew stalls or mis-normalizes; apply the `install.sh` workflow refresh and the `prflow_version` plugin bump together in the same upgrade so the wording-only normalization actually engages.

#### Upgrade note: the #533 gh-wrapper installer is a TWO-halves upgrade (loud on skew — take both together)

Issue #533 replaced the two writer workflows' inline gh-fresh install-step bodies with the checked-in `scripts/install-gh-wrapper.sh` (and stopped publishing a process-global `DEVFLOW_GH`). The workflow step ships by **re-running `install.sh`**; the installer script ships by **bumping `prflow_version`** (the `vendor-plugin` action fetches it at the pinned ref at runtime). Unlike the #455 silent-denial class, a skew here fails **loudly**: refresh the workflows while your `prflow_version` pin predates this release and the install step dies before the agent (`bash: .prflow/vendor/prflow/scripts/install-gh-wrapper.sh: No such file or directory`) on every App-configured writer run — it looks like a vendoring fault but is a pin lag. Take both halves in the same upgrade: re-run `install.sh` **and** bump `prflow_version` together.

#### Upgrade note: the #504 displaced-path ground truth is a TWO-halves upgrade (take both together)

Issue #504 surfaces the #458-displaced Stop-hook paths to the review engine as ground truth and routes their HEAD verification through `git show`. The fix ships on **two independently-updated artifacts**, and both must be taken together:

1. **The workflow half** — `.github/workflows/devflow-runner.yml`'s step reorder: a new `Compose CI summary` step before `Harden Stop-hook script sources` (which now publishes `displaced_paths` + `disposition`), then the slimmed `Compose review prompt` step after harden (forwarding `HARDENED_PATHS`). This half arrives by **re-running `install.sh`** (it refreshes the workflow files).
2. **The renderer/skill half** — `scripts/render-grounding-block.sh` renders the displaced-paths section from `HARDENED_PATHS`, and the Review bundle's phase references under `skills/review/phases/` + the `agents/*.md` mirrors carry the `git show` routing rule (issue #529 split the engine into a root plus per-phase references, so the routing rule now sits with each phase that verifies a claim against HEAD, not in the root `skills/review/SKILL.md`). This half arrives by **bumping `prflow_version`** (the workflows fetch the renderer + skill bundle from that pinned ref at runtime).

**Skew symptom — fail-safe to today's behavior, never a wrong claim.** Unlike the #455 silent-denial class, a skew here degrades *fail-safe*: bump `prflow_version` without re-running `install.sh` and the renderer carries the displaced-paths section but the workflow never forwards `HARDENED_PATHS` (no section renders — today's behavior); re-run `install.sh` without bumping `prflow_version` and the workflow forwards `HARDENED_PATHS` but the vendored renderer ignores it (no section — today's behavior). Either way the engine is no worse than before #504 — it just keeps manufacturing the false `documented_falsehood` findings the issue exists to stop. Take **both** halves in the same upgrade to get the protection.

#### Upgrade note: the #644 Documentation Needed span grammar narrows (single-artifact — normalize open issues before bumping)

Issue #644 narrows the `scripts/extract-doc-needed-paths.sh` grammar so command and grant literals quoted inside an issue's `**Documentation Needed**` block are no longer tokenized into phantom doc deliverables. Each deliverable must now be **one bare backticked path per span** (`` `docs/foo.md` ``, or several extension-bearing / in-tree paths in one span); a `:`/`*`/`(`-bearing span (`` `Bash(x.sh:*)` ``), a bare command word (`` `bash lib/test/run.sh` ``), an un-backticked `Word(...)` call group, and a fenced code block are treated as scope markers that contribute no tokens (a suppressed backtick *span* leaves a one-time stderr breadcrumb; `Word(...)` call groups and fenced blocks are removed silently). This is a **single-artifact** change — the extractor ships only via the `prflow_version` vendor fetch, so there is no two-halves workflow skew; **bumping `prflow_version` is sufficient**. Because bodies authored under the older tokenization can have multi-token spans reclassified from deliverables to suppressed literals, **normalize the Documentation Needed blocks of your open DevFlow-labeled issues to one bare backticked path per span before bumping**, so a genuine deliverable authored as part of a larger span is not silently dropped after the upgrade.

#### Upgrade note: the #1554 Documentation-Needed read helper is a TWO-halves upgrade (loud on skew — take both together)

Issue #1554 moved Phase 4.1's Documentation-Needed read — the `gh issue view` fetch, its scratch file, the `extract-doc-needed-paths.sh` invocation and both retries — out of inline shell written twice in the phase file and into the bundled helper `scripts/read-doc-needed-deliverables.sh`, which prints an outcome token (`deliverables`, `no-deliverables`, `body-read-failed`, `extract-failed`) paired with its own exit status (0, 10, 11, 12). The **workflow grant** — `Bash(.prflow/vendor/prflow/scripts/read-doc-needed-deliverables.sh:*)` in the `implement` capability profile's generated region (`devflow-implement.yml`'s baked `--allowed-tools`) — arrives by **re-running `install.sh`** (it refreshes the workflow files). The **helper plus the reworked phase file** arrive by **bumping `prflow_version`** (the workflows fetch the plugin tree at that pinned ref at runtime). The pre-existing `Bash(.prflow/vendor/prflow/scripts/extract-doc-needed-paths.sh:*)` grant is unchanged and does **not** cover the new helper — the grants are per-literal-path, not per-directory.

**Skew symptom — the run stops rather than mis-gating.** Unlike the #455 silent-denial class, a skew here surfaces: bump `prflow_version` without re-running `install.sh` and the reworked phase file invokes a helper the older workflow does not grant, so the invocation is refused with no output; re-run `install.sh` without bumping `prflow_version` and the workflow grants a helper the vendored plugin does not yet carry, so the invocation reports `No such file` at rc 127. Both readings land in Phase 4.1's residual arm, which routes to `Blocked` with a `dropped-failed` reflection, because a deliverable gate that continues on an unestablished read is not a gate — no run silently ticks `Documentation` over a deliverable that never shipped. Take both halves in the same upgrade so the gate runs instead of blocking.

#### Upgrade note: the cloud-writer runtime contract is a TWO-halves upgrade — refresh workflows and vendored plugin content together

PRFlow ships a pre-agent validator (`scripts/validate-cloud-writer-contract.py`) designed to fail closed when the vendored runtime manifest (`scripts/devflow-cloud-writer-contract.json`) does not describe the installed plugin *and* match the grants in your installed workflows. (Its runtime pre-agent wiring is deferred follow-up work — once wired, the cloud-writer tiers boot behind it; today it is a desk/CI-time contract, not a live boot gate.) That check spans **two independently-updated artifacts**: your installed `.github/workflows/` (refreshed by re-running `install.sh`) and the vendored plugin content under `.prflow/vendor/prflow/` (refreshed by bumping `prflow_version`). The manifest declares a `legacy_profile_baseline` — the immediately-preceding supported profile set — and PRFlow supports a **one-version skew window**: an installed workflow one version ahead of, or behind, the vendored plugin.

**Skew symptom.** Within that one-version window the mismatch is benign; a consumer **older than `legacy_profile_baseline`** is outside it, and a new workflow paired with that too-old vendored plugin trips the validator: it emits a `HEAD_ABSENT` diagnostic naming the manifest-required helper head that the installed workflow's grants no longer cover, and the profile it belongs to. (The window itself is emergent — the validator compares required heads against granted heads; it performs no version-distance arithmetic, and `legacy_profile_baseline` is the manifest field naming the boundary, not a value the diagnostic prints.) To stay inside the window, **refresh your installed workflows and vendored plugin content together before your next cloud-writer run** whenever you cross a version boundary — re-run `install.sh` and bump `prflow_version` in the same upgrade rather than one at a time.
