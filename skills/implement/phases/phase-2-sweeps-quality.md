<!-- prflow:implement-ref phase=2 file=skills/implement/phases/phase-2-sweeps-quality.md start -->
<!-- prflow:implement-set phase=2 part=3 of=3 -->

## Phase 2: Implement — quality sweeps, test & commit

#### 2.3.1 Orphaned-setup sweep (mandatory whenever the change deletes code)

Predicate. Fires whenever the change deletes code — a call site, a UI block, a branch, or a whole function.

**Procedure:** `<skill-dir>/references/sweep-2-3-1-orphaned-setup.md`, read under the Gated sweep procedures block in phase-2-sweeps-contract.md.

#### 2.3.2 Stranded-dependents sweep (mandatory whenever the change deletes a method, file, route, or page)

Predicate. Fires whenever the change deletes a public method, class, file, page, route, endpoint, asset, or template. Where 2.3.1 prunes dead lines inside the functions you touched, this sweep handles the inverse blast radius — the callerless surfaces, dead arguments, and surviving inbound links outside your diff that the deletion stranded.

**Procedure:** `<skill-dir>/references/sweep-2-3-2-stranded-dependents.md`, read under the Gated sweep procedures block in phase-2-sweeps-contract.md.

#### 2.3.3 Convention-compliance sweep on touched code (mandatory)

Same principle as 2.3.1, applied to `CLAUDE.md` conventions instead of dead code: any function, method, query, or new file your diff added or modified lines in must conform to the conventions in `CLAUDE.md` when you leave it — even if the violation was already there before you touched it, and even if "everything around it does it the same way." Recurring offenders that reviewers keep flagging as *Important* and that then ship anyway:

- A function signature left non-conforming after you edited it (e.g. argument shape, parameter style, return type) — whatever the project's CLAUDE.md mandates for function definitions in that language.
- A raw query/literal string in code you touched that violates the project's style rules (quoting, casing, identifier escaping) — whatever the project's CLAUDE.md mandates for embedded queries or literals.
- A new variable, method, file, or identifier you introduced that copies a legacy misspelling or non-conforming name from a sibling file — whatever the project's CLAUDE.md mandates for naming. "It matches the established convention across the existing code" is not a valid reason to propagate a misspelled or non-conforming name into new code; name the new thing correctly.

Do this sweep:

1. From the §2.3 sweep operand (defined in the §2.3 preamble in phase-2-sweeps-contract.md), list every function/method/query/new file your diff added or changed lines in.
2. Re-read each one in its post-edit state and check it against the rules in `CLAUDE.md` that apply to the languages and surfaces your diff touched.
3. Fix any violation in code the diff already touches. If fixing it cleanly is genuinely out of scope (it would balloon the diff into an unrelated refactor), say so explicitly in the workpad notes (`--note`) with the reason — do not leave it silent for `/prflow:review` to catch.
4. Do not reformat or rename code the diff didn't otherwise touch — this sweep covers only lines/functions/files your change already modified or introduced, never a repo-wide cleanup.

Treat a known convention violation in touched code as a defect in **this** PR, not a pre-existing-style excuse — if the diff touched it, it leaves `CLAUDE.md`-compliant.

#### 2.3.4 Boundary-assumption verification sweep (mandatory)

This sweep targets a claim your diff *depends on* about something outside the lines you wrote that you asserted from memory instead of verifying against the source of truth. These ship clean — the code reads fine in `git diff` review, and they pass your own tests, because the tests encode the same wrong assumption.

A boundary assumption is any factual claim the diff relies on about something the diff does not own. The recurring kinds:

- Dependency-version behavior — a symbol, export, signature, or runtime behavior of a third-party package. Verify it against the pinned range's actual installed source/changelog, not the latest docs (e.g. importing a symbol that is only public in a version newer than your dependency pin permits, so an in-constraint install breaks at import).
- Supported-runtime behavior — a behavior of the language, standard library, or interpreter. Verify it holds across the project's entire documented supported-runtime range, not just the version in your hands.
- Sibling-producer output — the shape or content of data produced by another module your code consumes. Verify it by reading the production producer, not by assuming a field is populated (e.g. consuming a field that the producer hard-codes empty).
- Real host/runtime environment — a path, base URL, network namespace, or sandbox constraint of where the code actually runs. Verify against the real host, not the local dev shell (e.g. relative asset paths that resolve locally but 404 under the deployed base URL).
- External-tool output — a literal string, message, or exit code the diff matches against, or documents, as the output of an external tool (a `git`/`gh`/CLI error message, a `--help` phrase, an exit-code convention). A matcher keyed on a phrase the tool never emits is dead code, and a phrase attributed to the wrong subcommand is a documented falsehood. Verify against the tool's observed bytes, not its `--help` prose or your memory of the wording.

Do this sweep:

1. From the §2.3 sweep operand (defined in the §2.3 preamble in phase-2-sweeps-contract.md), list every claim the diff depends on that falls into one of the five kinds above. The diff is the *trigger* for finding which boundaries the change now relies on — a boundary's definition site (an unchanged import, a producer module, a version pin) usually sits in context `-U0` doesn't print, so follow each claim to its actual source. Purely-internal claims (a local you just wrote, a function defined in the same diff) are out of scope — this sweep is only about boundaries you don't own. An in-diff guard, predicate, or validator carved out here is not left uncovered: it is routed to §2.3.0c's operand-trace sweep, which owns exactly the diff's own code this carve-out excludes.
2. For each claim, verify it against the actual source of truth — the pinned version's installed source/changelog, the producer module, the documented supported-runtime range across *all* of it, the real host — never from memory.
3. A test assertion about a boundary is itself an unverified claim. A test that asserts a wrong boundary value still passes — it encodes the bug rather than catching it — so a green run at 2.4 is not confirmation. When the diff adds or changes a test that asserts a boundary value, verify that value against the same source of truth here.
4. If the code is wrong, fix it. If a boundary genuinely cannot be verified in-environment, do not assert it as true: always record the gap with `workpad.py update $ISSUE_NUMBER --reflection-kind note --reflection "unverified boundary: {claim} — needs {live env} to confirm"` so it is visible to review and the merger. If — and only if — a specific acceptance criterion's verification depends on that boundary, additionally retag that criterion `(post-merge)` (per Phase 1.2, via the Phase 3.4 `--rewrite-ac` retag pattern) so the 3.4 gate doesn't block on a live-only check. An unverifiable external *boundary* is exactly the genuinely-live runtime-environment case the Phase 3.4 gate permits a `(post-merge)` tag for; it is not the runnable-but-blocked tooling gap, the self-claim confirmation, nor the self-reconfiguration verification (the change's own hook/flag/setting needing an active session — runnable on this host, so run-and-evidence-or-Blocked) that gate refuses (see §3.4). `(post-merge)` covers code that ships correct but can only be *verified* live — it is never a way to wave through a boundary you suspect is wrong (that is a blocker).

External-output reproduction obligation. When the diff matches against, or documents, an external tool's output string, message, or exit code, you must reproduce the command once in a scratch directory and paste the observed bytes into the workpad `--note` — the actual output, captured from a real run, is the only acceptable evidence for the matcher literal or the documented phrase. Doc prose is not acceptable evidence: a tool's `--help` text and its emitted error/output strings routinely diverge (a phrase in `--help` that the error message never prints), so citing the manual, the changelog, or your memory in place of the reproduced bytes does not discharge the obligation.

Companion outcome-verification rule. A precondition check never stands in for verifying the consumed outcome: a guard that confirms a *precondition* (a file exists, a command was found) but then treats the *consumption* it gates (the file parses, the command's output matches, the value is well-formed) as guaranteed is fail-open — verify the outcome the guard actually stands in for, not merely the precondition.

Treat an unverified boundary assumption as a defect in **this** PR, not a review-engine problem to be caught downstream — if the diff depends on it, verify it here or route it to `(post-merge)` with a reflection note.

Workflow-diff addendum (mandatory whenever the diff touches `.github/workflows/`). A workflow job is a boundary the generic sweep above under-covers in two specific ways — the token permissions it runs under and the artifacts its event paths leave on the head. Run both named checks over the diff, each with a workpad `--note` evidence obligation:

- (a) Endpoint↔permission map. Enumerate every API call the diff adds to a workflow job — each inline `gh api <endpoint>`, and each helper the job runs that itself calls `gh api` — and map each endpoint family to the token permission it requires (e.g. `check-runs` → `checks`, `commits/*/status` → `statuses`, `actions/runs` → `actions`, `issues/*/comments` → `issues`). Diff that required set against the job's own `permissions:` block; a call whose permission the job does not declare is a defect in this PR (it 403s at runtime, and a precondition keyed on that call then defers permanently). Record the map (endpoint → permission → present/absent) in a `--note`. This check is backed by a deterministic desk-time endpoint↔permission lint in the project's test suite, but run the map by hand here too so a gap is caught before commit, not only in CI.
- (b) Event-path artifact-lifecycle walkthrough. For each new or changed event path the diff introduces, enumerate the artifacts that path leaves on the head — check runs, commit statuses, comments — with their names and conclusions. Then re-run every reader of those artifacts in the same file against that enumerated set and confirm each reader still resolves correctly for the new artifacts (a new check-run name or conclusion must not wedge an exactly-once counter, a status reader, or a dedupe filter). Record the walkthrough — artifacts produced, readers re-checked — in a `--note`.

#### 2.3.4a Self-authored-claim reconciliation sweep (mandatory)

This sweep is 2.3.4's twin on the output side: it verifies the claims your diff *authors* — the behavioral assertions you wrote in prose — against what the shipped code actually does. 2.3.4 starts from *the boundaries your code reads*; this sweep starts from *the prose your diff wrote*. 2.3.4 explicitly carves out claims about code defined in your own diff ("a function defined in the same diff is out of scope") — those are exactly the claims this sweep owns. A sentence in a doc you edited, or a comment you added, that contradicts the code path it describes ships clean: the prose reads plausibly, the code compiles, and your tests assert the prose's *intent* rather than the code's *actual behavior*.

A self-authored claim is any behavioral assertion the diff introduces about what the shipped code does. The surfaces, all in scope here:

- Internal docs the diff adds or edits (`[[INTERNAL_DOC_LOCATION]]…` and the like) — a described behavior, flow, "it does X then Y", or guarantee.
- External docs the diff adds or edits — the same, in customer-facing prose.
- Code comments the diff adds or changes — an inline claim about what the adjacent or called code does (e.g. "returns the deduped set", "never retries", "matches the reference query exactly").

(The PR-body claims are reconciled separately in Phase 4.2, where the body is authored — the body does not exist at commit time. This sweep covers every claim that *does* exist before commit.)

Do this sweep:

1. From the §2.3 sweep operand (defined in the §2.3 preamble in phase-2-sweeps-contract.md), list every behavioral claim the diff adds or changes in the three surfaces above. A claim is any sentence or clause asserting what the code *does* — not a TODO, a rationale, or a statement of intent that makes no factual behavioral assertion.
2. For each claim, trace the actual shipped code path it describes and confirm the code does what the prose says — following dispatch into pre-existing code the diff calls but did not modify (the claim's truth often resolves only downstream, in a helper your diff doesn't own). Unlike 2.3.4, a claim about code *defined in your own diff* is in scope here, not carved out.
3. On any prose↔code divergence, the code is the fact. Resolve it one of two ways and never commit the unreconciled pair: either fix the code so the claim becomes true, or rewrite the claim so it states what the code actually does. Choosing one is mandatory — "note it and move on" is not an option for a contradiction you authored.
4. If fixing the *code* is genuinely out of scope for this PR (it would balloon the diff into an unrelated refactor), then rewrite the claim to the truth now — never leave false prose standing for `/prflow:review` to catch.
5. Clean-path evidence. For any step the diff adds that claims to *enumerate, verify, or scan* a set of things, confirm the step instructs its producer to log a summary (the count checked, the result) even on the clean path where nothing needs changing. A step worded "if all accurate, make no changes" with no trailing log is flagged.
6. Mirror-fact drift-proofing. Every comment the diff adds or changes that carries an exact count, an enumerated list of sites or values, or a predicate-restating scope word is made drift-proof per the §2.3 treatments — rewritten or removed — before commit, even when the comment is currently accurate. A mirror-fact comment is true when written and rots only once a later change updates the code and not the comment, so this step fires on every diff whether or not the writer applied the §2.3 authoring rule.
7. Prevention. Every comment the diff adds or changes that names no wrong change it prevents is moved to the project's internal documentation ([[INTERNAL_DOC_LOCATION]]) or deleted before commit — including one that is accurate, interesting and true, since an explanation no reader would mis-edit without is not prevention. On the normal path, also apply the §2.3 counting procedure to every comment the change adds or changes and check its length against the cap that procedure defines — restating neither here — so a kept comment that prevents a wrong change but exceeds the cap is caught rather than shipped; a comment covered by one of §2.3's three absolute carve-outs is exempt from the count. Where that location resolves but is unreachable for the run — unwritable, absent, or a resolution that failed — compress the comment to the §2.3 three-line cap or delete it — never silently keep it at length. Log the count of added or changed comments checked and, beside each one's disposition, its line count — including on the clean path where none had to move.
8. Restatement across comments. A fact stated in one comment the change adds or modifies is not restated in another it adds or modifies; where a docstring states it, the docstring is the retained site and the other copies are removed or moved to the project's internal documentation ([[INTERNAL_DOC_LOCATION]]). This step governs a comment mirroring *another comment*, where the mirror-fact step above governs a comment mirroring the *code* beside it — neither subsumes the other, so both apply. Where that location resolves but is unreachable for the run — unwritable, absent, or a resolution that failed — compress the redundant copies to the §2.3 cap or delete them — never silently keep the restatement. Log the count of added or changed comments checked and the restatements found, including on the clean path where there are none.

Scope and discipline mirror the other 2.3.x sweeps: only the claims your diff added or changed are in scope — never a repo-wide doc/comment audit. Treat a self-authored claim that contradicts the shipped code as a defect in **this** PR, not a `doc-accuracy` finding to be caught downstream.

When this run changed direction, the sweep extends past the diff. If you reverted, narrowed scope, removed a marker, or renamed a contract after you or the issue already described the original intent, two surfaces hold a now-false description that the reverting commit's own `git diff` doesn't contain — so steps 1–2 above can't reach them. On a change of direction only, also reconcile:

- The issue workpad — a ticked AC or Plan step whose wording still describes the reverted approach. Rewrite it to the shipped reality via `workpad.py update` (`--rewrite-ac` / `--replace-plan-file` / re-tick).
- Earlier-authored prose naming the changed contract — comments, docstrings, and docs that asserted the old behavior with a contract word ("always", "never retries", "fail-closed", a removed/renamed key) in an earlier commit. Grep the touched files and their callers for those words; fix the ones that now misdescribe the code.

Record the reconciled surfaces — or an intentional verbatim carve-out, with the reason — in a `## Devflow Reflection` bullet.

#### 2.3.4b Coverage-claim enumeration sweep (mandatory whenever the diff adds prose — which is every diff that ships a rule, a doc, a comment, a changeset, or a CHANGELOG entry)

Perform this sweep on every diff that adds prose. It owns a claim type 2.3.4a's code-path trace never reaches: a coverage universal, a sentence asserting a universal about *this change's own coverage* ("every call site is updated", "all four arms are handled", "exactly these files", "complete by construction"). Reading the sentence back and finding it plausible does not discharge the obligation — only a failed attempt to falsify it does. Left unclosed, the claim reaches Phase 3.3 as a `documented_falsehood`, a non-demotable REJECT.

Population. Every coverage universal the diff's added prose asserts, on whatever surface the diff touches — `skills/` and `phases/*.md` rule prose, `docs/`, `CLAUDE.md`, code comments and docstrings, and explicitly **`.changeset/*.md` and `CHANGELOG.md`**, which the helper's own header already declares in scope as *"human-authored prose about the current change, exactly the surface this lint exists to grade."* The operand is the §2.3 sweep operand (defined in the §2.3 preamble in phase-2-sweeps-contract.md — the merge base → working-tree branch delta), so a coverage universal authored in an earlier commit of the same branch is inside it and is graded here; `skills/review-and-fix/references/fixing.md` item 6a remains the fix loop's post-fix backstop for any such universal that a later fix reintroduces.

**Derive the population without staging.** Two legs, and **this sweep never mutates the index** — no `git add -A`, no `git add .`, no intent-to-add. An unscoped stage would land unrelated working-tree state on the branch that the fix loop's explicit-path staging exists to keep off.

```bash
# Leg 1 — the branch delta (committed AND uncommitted tracked edits alike), the §2.3
# sweep operand: <base> is the config-resolved base printed in its own fence per the
# §2.3 preamble, substituted here as a literal.
git diff --merge-base origin/<base> -U0 | "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/stale-prose-lint.py --worktree
# Leg 2 — once per NEW file THIS CHANGE authored, named explicitly. A merge-base diff (like
# git diff HEAD) lists NO untracked file, so this leg is the ONLY channel that reaches one — a
# new docs page or phases/*.md reference needs its own invocation exactly as a changeset does:
git diff --no-index -U0 /dev/null .changeset/issue-<N>-<slug>.md | "${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/stale-prose-lint.py --worktree
```

`"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/stale-prose-lint.py` documents itself — read its module header for the row tokens and the exit codes, and its `--help` output for the flags — so their definitions are not restated here.

The untracked leg is scoped to the change, never to the working tree. Name each new file by path, as leg 2 does; a new file the run does not name here is silently outside the sweep's operand while the `--note` still reads as a clean discharge. Do not substitute a bare `git ls-files --others --exclude-standard`, which returns every untracked non-ignored path a consumer happens to have — its emptiness here rests on an untracked exclude entry no clone inherits. If you do enumerate rather than name, the enumeration states its own path scope and carries its own `.claude/worktrees/` exclusion, per this repository's tree-enumeration convention.

The helper's `CU` and `RT` rows seed this sweep's population. Phase 2 adds no new gate on the helper's gating rows. This invocation is not gated by `prflow_review.stale_prose.enabled`, which is namespaced to the review engine's Phase 0.6; the sweep stands whether or not a consumer disabled the review-side lint.

Three outcomes, never two — an empty row set must not read as clean. Three observables decide it: the helper's exit code (the last command in each pipeline), whether the producing `git diff` actually put hunks into the pipe, and the helper's stderr; capture the diff to a file under `.prflow/tmp/` first when the producer's status is not otherwise observable. The arms are ordered, not disjoint: evaluate arm 3 first and fall through to arms 1 and 2 only when it does not fire, because a degraded run can also produce rows that arm 1 would read as a normal result to ground.

1. Rows produced → ground each, per the treatments below.
2. Zero rows, helper exit `0`, and the producer emitted hunks → a recorded clean pass. All three conjuncts, not the first two. On leg 2 the *producing* `git diff --no-index` exits 1 on every hit — that is its success path, not a failure. A hunk-less `--no-index` shape puts no hunks into the pipe, so it fails this arm's third conjunct and lands in arm 3 whatever its exit status.
3. Anything else → a recorded degraded pass, never a clean one. Stated as a complement so an outcome nobody enumerated cannot fall through to arm 2: helper exit `2`; the branch-delta operand could not be computed — an unfetched or absent `origin/<base>` ref, `git diff --merge-base` unavailable (git < 2.30 with no resolving `git merge-base` fallback), no reachable merge base, or an ambiguous multi-merge-base case (the §2.3 operand degraded arm) — each recorded degraded naming the condition that fired; an empty diff stream, which yields zero rows and exit `0` and is separated from arm 2 by the third conjunct alone; a producing `git diff` that failed and wrote nothing to the pipe; no output at all, which is what a refused invocation looks like; a stderr line saying the repository root could not be resolved, after which paths resolve against the process CWD and a non-root CWD makes every file unresolvable; and any stderr line the helper marks as a coverage drop, which announces lines it did not examine. None of these may be laundered into a clean result. The grounding obligation stands when the detector is unavailable — absent at its expected path, or refused — degrading to the recorded-note arm `skills/review/phases/phase-0-6-stale-prose-lint.md` already ships for its helper-absent case, with the run's own reading as the seed.

The rows are a seed floor, not the population. A coverage universal the detector does not recognize remains in this sweep's population and is grounded the same way.

Ground each one of exactly these three ways — complete by construction:

1. Pinned — by an *executed* enumeration of the set the quantifier ranges over. Run the search, read its result, and scope the sentence to what it returned.
2. Scoped — narrowed to what the change actually covers.
3. Removed.

Carve-out — exempt are exactly these two kinds, complete by construction:

1. Mandated-verbatim boilerplate (an SPDX header, a template line a generator requires verbatim).
2. Text the change quotes verbatim from another artifact — a sentence reproduced from a file, a spec, or an external source.

Prose the change is authoring into a shipped rule surface is outside the carve-out, however rule-shaped it reads. Without that narrowing, a diff whose deliverable is rule prose would exempt itself wholesale while the `--note` read as a clean discharge.

The declared marker does not discharge the obligation. A line carrying `stale-prose-lint: rule-text` controls detector noise only; membership in the carve-out is what exempts. A marked line is exempt only when it is in fact one of the two kinds above, and the `--note` records, per marked line, which kind it is.

Record the result via `workpad.py update $ISSUE_NUMBER --note` on the clean path as well as the dirty one — naming the number of lines examined and the treatment applied to each recognized line.

#### 2.3.5 Simplification & Efficiency sweep (mandatory)

The 2.2.4 gate already settled reuse and altitude at plan time. This sweep handles the two cleanup lenses that only become visible once the code is *assembled*.

After implementing, before running tests, re-read every function your diff added or changed lines in (from the §2.3 sweep operand, defined in the §2.3 preamble in phase-2-sweeps-contract.md) and apply both lenses:

1. Simplification. Flag and remove unnecessary complexity the diff *adds*: redundant or derivable state (a field that's always recomputable from another), copy-paste with slight variation (collapse to one parameterized form), needless deep nesting (flatten with early returns), and dead code the diff leaves behind. For each, write the simpler form that does the same job.
2. Efficiency. Flag and fix wasted work the diff *introduces*: redundant computation or repeated I/O inside a loop or hot path that could be hoisted or cached, independent operations run sequentially that could run together, and blocking work added to startup or a hot path. Reach for the cheaper alternative — but don't trade clarity for a micro-optimization that doesn't sit on a hot path.

Scope and discipline mirror the other 2.3.x sweeps: only touch functions/files the diff already added or changed lines in — never a repo-wide refactor. If a simplification is real but cleanly fixing it is genuinely out of scope (it would balloon the diff into an unrelated refactor), say so explicitly in the workpad notes (`--note`) with the reason rather than leaving it silent. Reuse and altitude are not re-litigated here — they were decided in 2.2.4; this sweep is only simplification and efficiency.

Treat avoidable added complexity or wasted work in touched code as a defect in **this** PR, not a `/simplify` problem to be caught downstream.

#### 2.3.6 Error-handling & silent-failure sweep (mandatory)

This sweep targets the defect class the Phase 3.3 `silent-failure-hunter` review agent keeps surfacing: an error the code *handles* in a way that hides it — swallowed, over-broadly caught, masked by an unexplained fallback, or reported too vaguely to act on. These ship clean because the happy path works and the suite is green — the failure only fires on an input the tests don't exercise.

A silent failure is any error the code can hit that doesn't leave the caller, the user, or a log a true, actionable account of what went wrong. The recurring kinds, in this repo's idiom:

- Swallowed error. A `try/except` that catches and continues, a bash `... || true` / `cmd 2>/dev/null` / `|| echo ""` / unchecked `$?`, or a `jq`/parse step whose failure is discarded — leaving no breadcrumb, or (worse) printing/returning *success* for work that may not have happened. An empty `except:` / `catch {}` is the absolute form and is never acceptable.
- Over-broad catch. `except Exception:` / `except:` (or a bash trap) around more than the one operation whose specific failure you meant to handle, so an *unrelated* error — a typo'd name, a missing dependency, a `KeyboardInterrupt` — hides under the same handler. Catch the narrowest type around the smallest scope.
- Unjustified or wrong-direction fallback. Falling back to a default, the built-in config default, an alternate path, or empty output on failure without recording *that* it fell back and *why* — the reader can't tell a real empty result from a masked failure. A fallback that defaults an *error* to a success-shaped value (an API error read as "passing", a parse error read as "no criteria") is worse: it fails *open*. A fallback is allowed only as documented, intended behavior, it fails toward the safe side, and it still leaves a breadcrumb.
- Misdirected or generic breadcrumb. A best-effort path that *does* emit a message, but a generic one ("error", "failed") that points at the wrong cause — the silent-fail trap CLAUDE.md already calls out for `config-get.sh` / the jq consumers. The breadcrumb must name the *specific* shape that detonated.
- Mock/stub leaking past tests. Production code falling back to a fake/stub/hard-coded value when the real source is unavailable, outside test scaffolding.
- Existence-standing-in-for-outcome. A precondition check standing in for an unverified consumption — a guard that tests a precondition (a file exists, a command was found) and then treats the consumption it gates (the file sources/parses, the value is usable) as guaranteed. The file can exist yet be unreadable or fail to parse, so the precondition passes while the outcome it stands in for never happens. Verify the outcome, not the precondition — assert the consumed result directly (the function is defined after sourcing, the parse produced a usable value) and fail closed with a specific breadcrumb when it isn't.
- Un-guaranteed-tool derivation. A value that decides which thing is selected or what is emitted must not be derived through a tool the project's preflight does not guarantee: a slug, path segment, count, or comparand piped through a `PATH` tool that is not a preflight-guaranteed prerequisite degrades silently where that tool is absent or behaves differently (the pipeline still runs, the value comes out empty/unnormalized/wrong, and the wrong thing is selected or emitted, with no error). Derive such a value with builtins, or prove the tool is preflight-guaranteed and cite it, or check the derived value is well-formed before use and fail closed with a breadcrumb naming the tool. The carve-out: cosmetic sanitization through such a tool remains acceptable **iff** a missing tool fails closed (an emptied value degrades to a safe placeholder, never a raw/injected one).

All-output-channels honesty (breadcrumb honesty is not scoped to stderr). The honesty rule applies to every output channel a failure or condition drives — a stderr breadcrumb, a log line, a machine-readable reason code, and a user-facing title or status string alike. No channel may assert a state the code did not actually observe: if the code could not distinguish two conditions, none of its channels may name one as fact. An unverifiable condition is reported *as unverifiable* on every channel, not resolved to a plausible-but-unobserved cause on one of them. A per-arm stderr breadcrumb passes a stderr-framed sweep while a coarser channel — a reason code driving a user-facing check title — still names a cause the code never observed. Check the reason code and the title/status string with the same rigor as the stderr line: each must name the specific observed cause, or report the condition as unverifiable.

Do this sweep:

1. From the §2.3 sweep operand (defined in the §2.3 preamble in phase-2-sweeps-contract.md), list every error-handling site the diff added or changed: each `try/except` / `catch`, each `|| true` / `|| echo` / `2>/dev/null` / `set +e`, each `$?` check or swallowed exit code, each fallback/default-on-failure, each `jq`/parse step that can fail, each optional-chaining / `// default` that can skip a failing op, and each default-valued read of an absent, empty, or never-measured operand feeding a value the change measures, aggregates, or reports — this one raises no error and skips no failing op, so the entries above miss it, yet an unmeasured operand enters a maximum, a median, and a sum as a real value; the fail-open and report-the-unverifiable rules this section already states govern it. If the diff added none, the sweep is a no-op — record that and move on.
2. For each site, confirm it does not silently fail: the failure is either propagated, or handled with (a) a breadcrumb naming the *specific* cause and (b) — for anything user- or caller-facing — an actionable account of what went wrong. A best-effort exit-0 path still leaves the specific breadcrumb, never a generic or misdirected one, and never prints success for work that didn't happen.
3. Narrow every broad catch to the specific type around the smallest scope. For each catch you keep, enumerate what unexpected errors it could swallow — if that list isn't empty, tighten it.
4. Justify every fallback: it must be documented/intended behavior, it must fail toward the safe side (never default an error to a success-shaped value), and it must leave a breadcrumb distinguishing a masked failure from a real empty result. Remove any production fallback to a mock/stub.
5. Fix any silent failure in touched code. If a handler is *genuinely* a best-effort absorber, make that intent explicit in a comment and keep its breadcrumb — don't leave it reading as an accidental swallow. If a fix is truly out of scope, say so in a `--note` with the reason rather than leaving it silent for `/prflow:review` to catch.
6. Per-branch breadcrumbs on multi-branch no-op paths. For any multi-branch no-op path the diff adds (e.g. "if A, stop; else find B; if B absent, stop"), confirm each branch emits a distinct diagnostic naming which condition fired. Two different no-op or failure modes that converge on one shared breadcrumb is flagged: the reader cannot tell which branch fired, so it is a variant of the misdirected/generic-breadcrumb kind above.

Scope and discipline mirror the other 2.3.x sweeps: only touch error-handling sites the diff already added or changed — never a repo-wide error-handling audit. Treat a silent failure in touched code as a defect in **this** PR, not a `silent-failure-hunter` finding to be caught downstream.

#### 2.3.7 Collection-cardinality sweep (mandatory whenever the change adds a collection output with ordering, dedup, or aggregation logic)

Predicate. Fires whenever the change adds a collection output whose value depends on cardinality — a sorted list, a deduped set, a grouped or counted tally, a tie-broken ranking. A pass-through collection that neither sorts, dedups, nor aggregates is out of scope.

**Procedure:** `<skill-dir>/references/sweep-2-3-7-collection-cardinality.md`, read under the Gated sweep procedures block in phase-2-sweeps-contract.md.

### 2.4 Test

Durability checkpoint (§2.0.5): this boundary follows the largest body of stageable work and the fix loop below can run long — take a checkpoint when you cross it, naming the files produced since the previous one, and take §2.0.5's resolve-before-continuing rule on a non-zero exit.

Run the project's test and lint commands (check `CLAUDE.md` or `README`). Issue both Bash calls in a single assistant turn so they run in parallel.

Run the narrowest covering test before the broadest. When more than one automated test bears on the change, run the test that covers only the changed surface before the whole suite.

- If both pass → proceed to committing.
- If either fails → fix the failing tests/lint errors yourself. Re-run the failing command(s) to verify.

When the deliverable can't be exercised by a test, a green suite is not enough. A change whose deliverable is prose, templates, config, or an embedded DSL (jq or shell inside Markdown, a SKILL.md procedure) is invisible to the test suite — passing tests say nothing about it. Match the verification to the deliverable: for a logic-bearing artifact (config, template, jq/shell-in-prose, or inline jq inside a workflow file — a parser just like a standalone consumer), enumerate an adversarial input-shape matrix — the `{object, array, scalar, valid-falsy (explicit false / 0 / empty string), missing, wrong-type}` shapes, i.e. the corrupt, empty, scalar-where-object-expected, valid-falsy (the `false`/`0`/`""` an `// true`/`// default` extraction silently coerces), and edge shapes — and statically dry-trace the logic against each. The governed surface is broader than config JSON: a parser over agent- or human-mutable markdown (a workpad, a PR body, a `SKILL.md`/`phases/*.md` block a step reads back) or a reader of a new external structured format (a check-run summary, an API response the repo does not itself produce) is a logic-bearing artifact too, governed by the malformed-shape matrix appropriate to *its* input type — for mutable markdown: missing/duplicate sections and markers, non-canonical layout, empty/truncated input; for an external format: that format's own boundary rows — the six-shape set staying the matrix for config-JSON consumers. For pure prose, the deliverable splits by one question — does this text enter a model's context as instruction? Prose a *human* reads (a reworded procedure, a doc paragraph, a comment) keeps the adversarial dry-trace against representative scenarios, unchanged. Prose that becomes an *agent's* prompt (an injected block, a composed prompt, an agent brief, a `SKILL.md`/`phases/*.md` command block) cannot be verified by a dry-trace — the text reads perfectly while steering the model wrong — so it gets a subagent RED/GREEN micro-test with a no-guidance control, per `writing-skills`' discipline: a RED baseline (a subagent without the new text misses the defect the text targets), a GREEN run (the same scenario *with* the text catches it), and a no-guidance control (a subagent given no guidance at all) confirming the failure exists absent the text. The trigger is whether the text enters a model's context as instruction — never where the file lives (a block in a script or a workflow YAML that becomes a prompt still takes the micro-test). Record the traces, or the RED/GREEN/control results, concisely in a workpad `--note`. On parser or best-effort code, run this as your *opening* move rather than after several review iterations.

### 2.5 Commit Implementation

When the recorded classification is bug-report: confirm any temporary proof edits made in 2.1.5 have been reverted. Verify with `git diff HEAD` and `git diff --staged`. The working tree about to be committed must NOT include any stray `console.log`s, hardcoded payloads, or other proof-only edits.

Cloud-tier workflow-edit commit guard (fires the Pass 5 / 2.2.5 backstop here). This is the commit-time firing point for the "re-apply the scope-adjustment before committing" backstop the 2.2.5 rule and its Phase 2.3 re-route describe.

- When it fires: on a run whose credential cannot push `.github/workflows/` — the same condition Pass 5 keys on: cloud tier (`GITHUB_ACTIONS=true`) with `DEVFLOW_APP_ID` empty/unset (the `GITHUB_TOKEN` fallback). Exempt: a local/interactive run, and a cloud run with a workflow-capable App token (`DEVFLOW_APP_ID` set) — its credential *can* push workflows.
- Detect before staging, for any *modified/deleted* or newly-created file under the repo's *own* `.github/workflows/`: check both `git diff HEAD --name-only -- .github/workflows/` (tracked edits) and `git ls-files --others --exclude-standard -- .github/workflows/` (untracked new workflow files, which `git diff HEAD` never lists, and which a checkpoint naming the path would otherwise carry into the commit — a workflow-*adding* AC is exactly the case this covers). Match only the repo's own workflows dir, not a vendored `.prflow/vendor/prflow/.github/workflows/` path, per Pass 5's carve-out.
- If either command reports a path, do not commit it: revert (or delete, for an untracked addition) that file from the working tree — and revert every file coupled to it in the same step. The workflows-scoped commands above list only the workflow file itself, never a coupled test-suite pin (or any test/doc that asserts the reverted workflow's content) (the project's own coupled-pin recognizer lives in the implement prompt extension); a coupled pin left behind asserts content that is no longer present, so the pushable remainder ships CI-red, defeating Pass 5's CI-green-pushable-subset guarantee.
- Enumerate the coupled files by grepping the reverted workflow's distinctive content (a step name, a job id, the exact literal a pin asserts) across the test suite, and revert them together with the workflow. This content-grep catches pins that textually embed the workflow's content, but not one asserting a *structural or derived* property (a line count, a file-exists check, an `awk`-extracted block shape) — a best-effort heuristic, not a complete revert.
- Backstop it: after reverting, if the test suite is runnable on this tier, run it and treat any RED as an additional coupled-file signal (a still-failing pin names a coupled file the grep missed — revert that too); on a tier where the suite cannot run, the required CI test job on push is the final coupled-pin catch.
- Then route the AC the workflow (and its coupled files) served back through the 2.2.5 scope-adjustment — defer it to the workflows-capable follow-up, or take the empty-pushable-subset Blocked path above if deferring it empties the pushable subset — and commit only the pushable remainder. Never `git add`/commit a repo-own `.github/workflows/` add or edit — or a file coupled to one — on a cloud-tier run whose `DEVFLOW_APP_ID` is empty.
- The helper covers the detect-and-do-not-stage half only, and by spelling. That half is owned by the durability helper (§2.0.5), which §2.5's own commit invokes, so a repo-own `.github/workflows/` path you name to it in the relative `.github/workflows/…` spelling is not staged even if this prose's revert is missed. The match is spelling-only: an absolute path, a `../`-reaching form, and the bare directory `.github/workflows` with no trailing slash are not matched and WILL be staged, so never rely on the guard in place of the revert. It is defense-in-depth, not a replacement: the coupled-file enumeration and the 2.2.5 routing above remain yours, and the helper does not revert the workflow file, so an unreverted one still sits in the working tree for the Phase 4.3 clean-tree backstop to catch.

§2.5 is the run's final durability checkpoint: it goes through the same helper (§2.0.5) as every earlier one, so the workflow-edit guard and the push-landing verification apply uniformly. Name every path this run created or modified (the set your earlier §2.0.5 checkpoints have been accumulating); the helper stages exactly those — refusing `git add -A`/`.` — commits, pushes, and confirms the push landed (`git rev-parse HEAD` == `@{u}`). Any path you never name to a checkpoint remains uncommitted for the Phase 4.3 clean-tree backstop to surface, so enumerate comprehensively here:

```bash
.prflow/vendor/prflow/scripts/phase2-durability-checkpoint.sh "feat: implement issue #$ARGUMENTS — {short description from issue title}" {every path this run created or modified}
```

At this durability-checkpoint boundary also append a `phase2-checkpoint` event (best-effort; the helper always exits 0 and never blocks the run):
```bash
.prflow/vendor/prflow/scripts/verification-flight.py event phase2-checkpoint
```

If the change includes test fixes, name those paths in this same final checkpoint (one commit combining implementation and fixes).

Act on a non-zero helper exit — it is not a crash and must not be ignored. The helper exits non-zero when the checkpoint did not land — a rejected non-fast-forward leaves `HEAD` != `@{u}` (exit 3); an `Everything up-to-date` push is likewise exit 3 only when that comparison still shows the checkpoint commit did not reach the tracked branch — or when a git operation failed (exit 4), or a stage-all token / missing message was refused (exit 2). An unlanded checkpoint leaves the branch's tip unpushed, so Phase 3.1's `gh pr create` later refuses. Two documented ways it fails: running in the cloud, when the App token is not seeded pushes run as `github-actions[bot]`, so a push whose commit touches `.github/workflows/` is rejected; running locally, the permission classifier can refuse the command outright — a refusal, not a crash — and the helper produces no output at all. On any non-zero exit — or no output at all (a harness refusal) — read the helper's stderr breadcrumb, record a `dropped-failed` reflection naming the cause, and resolve it (seed the App token, defer the workflow file via the cloud-tier workflow-edit commit guard above, or rebase/re-run) before advancing to Phase 3; do not tick the implementation gate on an unlanded checkpoint. (The helper's plain `git push` resolves to the upstream Phase 1.5 already set with `git push -u origin HEAD`.)

Then tick the implementation gate and its parent phase in the workpad: `workpad.py update $ISSUE_NUMBER --tick-progress "code + sweeps" --tick-progress "**Implement**"`.

⚠ You are NOT done. Code is committed but not reviewed or documented. Proceed to Phase 3.

<!-- prflow:implement-ref phase=2 file=skills/implement/phases/phase-2-sweeps-quality.md end -->
