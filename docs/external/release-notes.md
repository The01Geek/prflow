---
title: "Release Notes"
description: "User-visible PRFlow changes, fixes and upgrade notes."
---

# Release Notes

This page summarizes user-visible PRFlow changes. For a complete change history, see [GitHub Releases](https://github.com/The01Geek/prflow/releases).

**Release cadence:** PRFlow versions continuously and publishes releases periodically, so a published version number skips the intermediate versions developed between two releases. A gap between consecutive tags is expected and does not mean a release is missing.

**Legacy review tier:** Entries about automatic pull-request-triggered review apply only to repositories that installed that tier before July 29, 2026. Fresh installations do not receive it. Use a collaborator comment with `/prflow:review` for the supported cloud review path.

## September 24, 2026

- **Agents no longer open with a failing shell call on local runs.** Each Bash-capable agent now reads `.prflow/tmp/command-shapes.md` once with the `Read` tool instead of probing it with `ls` or `cat`. A missing, refused, errored or empty read is final, so local runs, where the file never exists, skip the shell error each agent used to hit. Cloud runs that have the file still limit their commands to the shapes it permits. (#1129)
- **Padded denial counts read the same on jq 1.8.** `scripts/build-denial-record.sh` and `scripts/extract-execution-shape.sh` now strip surrounding whitespace before parsing a string denial count, so a padded `" 7 "` publishes the count `7` and a padded `" 0 "` publishes `permission_denials: absent` on jq 1.8 hosts (Homebrew, the Windows runner image) exactly as on jq 1.7. (#1082)
- **Reviews stop re-checking a correct PASS whose commit id lost its last characters.** When a checklist verifier records a 12–39-character lowercase hex prefix of exactly one of the run's bound head or base revisions, the review collector now expands it to that full revision and grades the verdict as usual, noting the expansion in its input warnings. A prefix of both revisions, of neither, or shorter than 12 characters is still treated as missing. (#1113)
The shipped workflows now pin `anthropics/claude-code-action` to the tagged release v1.0.233 (commit `8cf3482550831fb35a4fc3fbf7ca139cf8028b4c`, installing Claude Code 2.1.281) instead of an untagged `main` commit.
When a concurrent writer rejects the telemetry push, the re-parent onto the fetched tip now spawns git processes bounded by the number of paths that differ between the two tips instead of by the number of stored paths, so a review-and-fix Loop Exit's `--persist` no longer stalls as the telemetry store grows.
The review engine's view materialization now stops with a `view-path` error naming the refused path when the reviewed commit writes a file or directory at root `inventory.json` or `inventory.json.tmp`. Previously such a file was silently overwritten with the view manifest and a directory failed as an opaque `filesystem` error. Such a repo still cannot be reviewed; the stop now says why.
- **Review no longer approves a pull request whose checklist verifier confirmed a false authored sentence.** When a verifier passes a checklist claim about a comment, doc line or other text a person wrote in the code, but also reports that this text is itself false, the review now records that item as a failure marked `CONFIRMED SOURCE DEFECT (raw PASS)` and rejects the run, the same outcome as when the claim is worded the other way round. On a run that binds commit views, if the verifier's view of the code cannot be confirmed, the item is still reported as inconclusive rather than as a confirmed defect. (#1140)
- **An implement run whose final review REJECT is downgraded to a caveat can now complete.** When the review-and-fix loop's final REJECT qualifies for the downgrade to `APPROVE WITH CAVEAT` (every remaining trigger set aside as out of scope, already tracked, or a disproved claim), the loop now runs its independent shadow review on the final iteration first. The downgrade stands only when that shadow, with full coverage and an attested prompt, returns a non-REJECT verdict with no new Critical or Important finding and re-grades no parked finding; any other shadow result ends the run as REJECT, without starting another iteration. (#1122)
- **Reviews no longer stop on Windows when a tracked file's path is too long.** On Windows, the review's copy of your repository is now written through extended-length paths, so a path of 260 characters or more is copied like any other file, even with Windows long paths turned off, as long as no single file or folder name exceeds 255 characters. On macOS and Linux, a file whose name is too long for the filesystem to store is recorded as unreadable instead of stopping the whole review: claims about that file are graded inconclusive, and the setup summary line reports how many such files there were (`path_too_long=<N>`). (#1190)

## September 23, 2026

- **Every acceptance criterion now gets exactly one review checklist item.** The review builds
  one checklist item per decided acceptance criterion itself, outside the 100-item checklist
  cap, so an issue with many criteria no longer loses some of them to a 25-item limit and no
  longer receives a "Coverage shortfall" REJECT for that reason. The report now shows an
  `Acceptance coverage: <itemized> of <resolved> decided criteria itemized` line, and a review that builds a checklist
  still REJECTs when any criterion could not be itemized. (#973)
- **Review-and-fix reviewers now see findings the loop declined in any earlier iteration.** From iteration 3 on, the prior-findings context handed to each primary-pass reviewer carries the previous iteration's findings plus the pushed-back and deferred findings recorded by earlier iterations, each tagged with its iteration, so a finding declined two or more iterations back reaches reviewers as already considered rather than new. Findings fixed before the previous iteration are not carried. (#1021)
- **Review-and-fix declines findings that would weaken an acceptance criterion.** The review engine's return file now carries the run's resolved acceptance criteria (the return helper rejects a return that omits them), and the fix step declines any finding whose fix would weaken or contradict one, at every severity, recording a `claim-quality` pushback that quotes the criterion. Inside `/prflow:implement`, a finding that persists after pushback ends the loop with its current verdict instead of waiting for input, and a criterion-conflict residual soft-proceeds rather than blocking the run. Runs with no resolved criteria decline nothing new. (#996)
- Review verification: a checklist item re-asked only for its two auxiliary fields now keeps its first answer's evidence, `file_checked` and `view_revision` (the engine names that answer's nonce under a new `pinned_from` inputs key). A re-ask that proves the property can now keep its normalized PASS through the view-provenance gate instead of being demoted to INCONCLUSIVE, and a FAIL that survives the re-ask shows the first answer's evidence (#1027).
- `/prflow:review-and-fix --push-each-iteration`, which `/prflow:implement` runs, now merges the base branch and pushes after each fix iteration's fix-delta gate settles instead of after each fix commit. Inner re-fix commits ride that one push, so a fix iteration starts CI once rather than once per commit, and the fix-delta gate no longer reviews a base-branch merge as part of the iteration's fixes. (#1019)
- `/prflow:spec` issue template: an acceptance criterion that states a policy an agent applies at run time now names the value the agent reads, the step that produces it, and the agent's route when that value is absent, its producing step fails, or the value is unresolvable; a quality-checklist row checks it (#1022).
- **Review-and-fix iterations now try to read the sweep definitions before reporting the fix-delta sweeps as unrunnable.** A fix-applying iteration records the sweeps as unrunnable only after its own Read of a source file fails or leaves the set incomplete — one of the three Phase 2 phase files, or a warranted sweep's gated reference — and its `sweeps: unrunnable` record names that file's path and the failure the Read returned or the missing marker. A later fix-applying iteration re-attempts every read an earlier one recorded as incomplete, so one failed read no longer disables the sweeps for the rest of the run. The breadcrumb no longer offers `not-read` as an outcome. No-fix iterations record the same `not-run` evidence as before. (#1018)
- **Review-and-fix reviewers now see every earlier finding the loop did not fix, not only pushed-back and deferred ones.** From iteration 3 on, findings from iterations before the previous one are carried into reviewers' prior-findings context unless they were fixed, so advisory, parked and severity-re-graded findings reach reviewers as already considered rather than new. An earlier iteration record that holds no findings list is now skipped with the same log line as a missing or unreadable one. (#1041)
- Review-and-fix: a finding the fixer declines because its fix would weaken an acceptance criterion no longer clears a Critical. Inside `/prflow:implement`, a Critical or ungradeable residual takes the Blocked path even when declined, and only a decline that quotes one whole criterion lets a lower-graded residual soft-proceed. The decline also no longer counts toward downgrading a REJECT to `APPROVE WITH CAVEAT` (#1042).
- **Fix loops stop re-verifying unchanged multi-file evidence.** From the second review-and-fix iteration on, a carried checklist PASS whose evidence cites several files keeps its verdict when every cited file is tracked at HEAD and unchanged since the prior iteration's review, instead of costing a fresh verifier dispatch. A citation naming any changed, untracked or missing file, a symlink, or a `./`-style alias of a file still verifies fresh. (#1028)
- **Each checklist verifier reads only its own item.** A review pass now writes every item it sends to a verifier into its own file, in a directory beside the checklist, and the verifier reads that file instead of the whole checklist, so a large checklist costs less to verify and a verifier no longer pages through it to find its entry. When those files cannot be written, verifiers read the checklist as before. Claim details the checklist generator supplies when asked for missing fields before verification are now saved into the checklist, so the item files and verdict normalization use them. The verdict format, nonce binding and evidence gate are unchanged. (#1025)
- **A resumed implement run no longer logs its own edits as issue-accuracy defects.** When the issue-claim audit finds a `Verified:` premise refuted in a file the branch already changed, it records a branch-changed note instead of an `issue-accuracy` reflection, and still discards the premise. When the branch diff cannot be computed, the refutation keeps the `issue-accuracy` reflection and records why. (#979)
- **Checklist verifiers stop wasting turns on the source-view inventory.** A verifier now reads its cited file at the path it derives from the repository path, and checks the view's `inventory.json` only when that file is missing, with a search for the one path rather than a read of the whole file. The inventory now holds one entry per line with non-ASCII paths written literally, so that search returns one short line. The review's dispatch lines name each view as `<view-dir> (revision <sha>)`, so a verifier no longer reads the directory and revision as one path. (#1059)
- **A true "file X unchanged" acceptance criterion no longer grades INCONCLUSIVE and forces a review REJECT.** The checklist verifier now cites the untouched path itself from the head source view (the base view when the path is gone at head), or, for a directory or file class, one tracked file the diffed pathspec matches, instead of the run's diff, which the source-view check cannot accept. (#1092)
- **An implement run's acceptance-criterion rewrite can no longer disagree with its recorded scope decision.** A rewrite that carries its scope-decision record, as the rewrite procedure requires, now lands only when the new criterion matches that record, so a partial criterion is refused instead of silently replacing the full one. The implement instructions now record a rewrite or deferral made after the draft PR opens against that PR, so the review accounts for those criteria instead of reporting them as dropped. (#1067, #1077)
- **`/prflow:implement` no longer hits a refused Complete write on the `review.md` extension row, and posts 🎉 only after Complete lands.** The review-fix worker now ticks that row from its own load of the review extension, not from the review engine subagent's load, which reports nothing back. Any row it cannot tick gets a note in the form the Complete gate accepts, which names the row and says `state not established`. The 🎉 reaction on the triggering comment now waits for the Complete write to land, so a refused or unverified write no longer shows success early. (#1071)
- **A local `/prflow:implement` run no longer fails two calls in its issue-claim audit.** The auditor now runs its record validator and projection gate through the helper directory its dispatch passes, instead of trying the vendored `.prflow/vendor/prflow/…` path first, which does not exist in a repo that does not vendor PRFlow. Cloud runs are unchanged: there the helper directory is still the vendored path. (#1055)
- **A standalone `/prflow:review-and-fix <PR>` shows every reviewer's findings in the live progress comment again.** Claude Code refused the review engine's per-reviewer `findings-<agent>.md` write when the engine ran as a subagent, which dropped that reviewer's block from `## Findings (live)`. The block file is now `p3-<agent>.md` and is written only when the run holds a live progress comment, so implement runs no longer spend a refused write per reviewer. If a block write still fails, the review warns and skips that live append. At the verdict it rebuilds the block from the findings it holds, or names the reviewer whose findings it could not recover. (#1057)
- **The implement review-fix and finalization workers now check their handoffs with the validator's real command.** Both worker bodies give the full flag form of `validate-review-fix-handoff.py` (vendored path first, skill-anchored fallback), so a run no longer spends a refused positional call or a `--help` probe before the worker's self-check. When the check names a fault, the worker fixes it and checks once more, so a malformed handoff is corrected inside the worker instead of blocking the run at the parent. No config change; the validator and the parent's checks are unchanged. (#1096)
- **One malformed deferral no longer drops every deferral in a review.** The review's deferral matcher now shape-checks each entry before any guard runs. It rejects an entry that is not a mapping, or whose `reason`, `reason.category`, `finding`, `finding.file`, `finding.line_range` or `follow_up` holds a present value of the wrong type, as `malformed-entry`; the matcher's JSON record for that rejection carries a `detail` naming the field, while the review report shows the reason only. The other entries are still matched. A null `reason` or `follow_up` is not malformed, and a matching entry carrying one no longer crashes the matcher. Every such entry now reports `malformed-entry`. Here is what each did before:
  - **Honored:** an entry with a non-string `reason.category` (including `0`, `false`, `[]` and `{}`), or a `line_range` holding a float or a boolean.
  - **Rejected for another reason:** the other wrong-typed entries that did not crash were `unmatched`, `widens-surface` or `missing-follow-up-issue`. A malformed entry on a changed line is now `malformed-entry`, not `widens-surface`.
  - **Crashed the matcher:** every remaining shape, including a foreclosure entry whose `follow_up` is not a mapping. The crash dropped every deferral.
  - **Also fixed:** a `deferrals` value that is not a list is ignored with a warning. A foreclosure whose `disclosure.path` cannot be resolved fails with `disclosure-unverified`. An `id` that YAML loads as a date no longer crashes the output. (#974)
- **A cloud review verdict now requires the specialist reviewers to have run.** A cloud
  `/prflow:review` that posts a verdict without dispatching all three always-on specialist reviewers
  (code reviewer, silent-failure hunter, comment analyzer) now fails the review evidence gate:
  the PR gets a comment naming the missing reviewers and the `PRFlow:ReviewStuck` label, and a
  merge-gating verdict is dismissed. The blocker-recheck fast path stays exempt, and a workflow
  that supplies no execution transcript keeps its current behavior. When a run's checklist
  evidence is also missing, its evidence-missing recovery now dispatches any reviewers it
  skipped. (#1051)
The review's criteria resolver (`workpad.py acs-resolve`) now follows chained scope-decision rewrite records. A criterion an implement run rewrote twice (A→B, then B→C) resolves to its current workpad text and reports `CHANGED: A -> C`, instead of routing to `pr-identity-mismatch` and reviewing the PR against the stale issue text.

A criterion that is both deferred and rewritten to a text the workpad does not carry now reports `DEFERRED: A` (previously `CHANGED: A -> B`); the source token is unchanged.
- **`/prflow:spec` no longer drafts a size or limit acceptance criterion that is already false before the change.** When a file the change does not touch already breaks a tree-wide limit such as "every shipped file stays under N bytes", the criterion covers only the files the change adds or edits, and a file or summed budget already over the limit must not grow. A limit every file already meets, or one the change introduces, can still cover every file. (#1066)
- Review verification: a verifier PASS whose `file_checked` separates two cited files with a space (`a.py:12 b.py:40`) now keeps its PASS when both files are in the reviewed commit's inventory, instead of being demoted to INCONCLUSIVE and forcing a REJECT. A citation naming any file outside the inventory still demotes (#1102).
- **Run diagnostics now render under jq 1.8.** On a runner with jq 1.8 (the Windows runner image, Homebrew), the execution-diagnostics block came out empty and the permission-denial count and Claude Code version were reported as `unavailable`. They now report the same values on jq 1.6, 1.7 and 1.8. (#999)
- **A quantified acceptance criterion whose recorded value does not match goes back to the evidence verifier.** When the verifiers call a criterion satisfied but the evidence verifier's recorded stated and observed values differ, are blank, or are missing, `/prflow:implement` now asks that verifier to restate its record instead of escalating the criterion to an orchestrator judgment, which could rewrite it. The values must still match exactly. The evidence verifier now writes the observed value in the same form as the stated one (the bound itself when a measurement meets an "at most" bound), with the measurement and commentary kept in its evidence, and a criterion about a file's presence or content is checked by the evidence verifier alone, even when a lint covers that file. (#1068)
- **Shorter final-pass reviewer prompt.** The review engine no longer writes the findings contract and the prompt-extension status rules into the final-pass reviewer's prompt on every pass. The reviewer now reads them from `skills/review/final-pass-contract.md`, so each review pass spends less time and fewer output tokens composing that prompt. Review output is unchanged, and a direct `/prflow:requesting-code-review` run is unaffected. (#1016)
- **Telemetry persistence no longer waits on a credential prompt.** The end-of-loop telemetry save now closes standard input, turns off git's terminal and Git Credential Manager prompts, and unsets `SSH_ASKPASS` (Git for Windows points it at a GUI prompt); a `GIT_ASKPASS` or `core.askPass` you set still runs. Over HTTPS it abandons a transfer that sends nothing for 30 seconds; SSH and connection setup are not time-bounded. A save that cannot authenticate fails with a warning instead of holding the run. (#997)
`/prflow:init` and `install.sh --apply` now advance the `prflow_version` pin they wrote. Previously the pin stayed on the first release tag it wrote. `/prflow:init` installs from the plugin cache, which is not a git checkout, so it pins a release tag rather than a commit SHA. The installer then treated its own tag as a hand-set pin and never moved it. It now records the pin it owns in `.prflow/install-manifest.json` (`prflow_version_stamp`, so commit that file) and updates a pin that still matches that record. Any other value is kept: the installer re-stamps only a value that is empty, looks like a commit SHA, matches that record, or falls under the upgrade case below.

The installer also no longer moves its own `vX.Y.Z` pin to an older `vX.Y.Z` release. That usually means a Claude Code session is still running the previous plugin after an update. The installer keeps the pin and asks you to restart and run `/prflow:init` again, which also refreshes the workflow files that run wrote from the older release. To downgrade on purpose, set `prflow_version` by hand.

A repository whose manifest predates `prflow_version_stamp` is unstuck on the first run that records one: a release tag older than the one that manifest last recorded is treated as the installer's own and updated. If you pinned an older tag by hand, set it again after upgrading. A tag pin in a repository with no `.prflow/install-manifest.json` at all is kept as hand-set; set `prflow_version` to `""` once and the next run pins it and keeps it current from then on.
- **Local review passes no longer poll for verifier results.** The review engine now waits for its checklist generator, deduper and checklist verifier dispatches to finish before moving on, and `/prflow:implement` does the same for its code explorer and architect. Local runs stop spending turns and tokens checking whether results have arrived; cloud runs are unchanged. (#1112)
- **PRFlow's shell steps now read native Windows `jq` and Python output correctly.** A native Windows `jq.exe` ends each output line with a carriage return, which broke several steps on Windows runs: almost every run with permission denials persisted no denial record; execution diagnostics misreported the denial count and CLI version; review verdicts and green CI could be misread; only the last superseded run was cancelled; the weekly retrospective's selection, reconcile and filing could fail; and settings files, `config.json` and the retrospectives corpus were written with CRLF lines. PRFlow now strips that carriage return and writes LF-only output, and the native-session transcript fallback finds this run's session files on Windows. The denial record's failure message now names the failed step and no longer echoes any fragment of a denied command. (#1050)
- **Review no longer rejects a verified "directory unchanged" criterion over its citation.** When a review checklist verifier proved a claim about a whole directory (for example, "nothing under `.github/workflows` changed") and cited that directory, the review graded the item inconclusive and could post a REJECT that cost an extra fix round. A citation of a tracked directory that still holds files at the reviewed commit is now accepted; a root, trailing-slash, absolute, partial-name or missing directory is still refused. (#1123)
- **Implement runs no longer stop at the issue-claim audit over a misnamed handoff field.** The issue-claim auditor now copies its workpad result under the exact field names the run expects and checks its own handoff with the same reader the run uses, correcting a named problem once before returning. (#1131)
- **The review's final-pass reviewer loads your `requesting-code-review` prompt extension again.** Its dispatch now tells it to run the extension command before any other tool call, exactly as written. Without that instruction the reviewer read its reference files first, then ran the helper by an absolute path the cloud allowlist does not grant, so the load was refused and your extension never reached the review.
- **Documentation files an issue names under `**Documentation Needed:**` are now required.** When an issue wrote the label with the colon inside the bold, `/prflow:implement` found no required documentation files and finished without checking that they were updated. It now reads that form like the other accepted forms, and a `none.` written after it declares that no files are required. (#1125)
- **Deferred review findings are sorted correctly on Windows.** Before filing follow-up issues, `/prflow:implement` checks whether a deferred finding's file is already a required documentation file. On Windows this check always failed, so the result was reported as unavailable. It now runs. (#1124)
- **An implement run whose final `Complete` write is refused now repairs it or ends Blocked within a bounded number of calls.** The prompt-extension row refusal now prints, for each offending row, the exact note it accepts: `Extension resolved: <name>.md — state not established (<cause>)`. Phase 4.3 now routes each refusal cause: an over-budget note is shortened, an over-size workpad is compacted, missing completion evidence or a missing required artifact ends Blocked, and an unrecognised refusal (usually a failed `gh` call) is re-sent once. Each remedy or cause gets at most one follow-up before the run records the failure and ends Blocked with a 👎 reaction. (#1103)
- **An implement run re-sends a refused final `Complete` write only when a GitHub call failed.** A refusal with no recognised cause now ends Blocked, naming the refusal, instead of being re-sent once first. (#1103)
- **A checklist verifier that replies without writing its verdict file is now re-dispatched inside the review.** Before, the reply's verdict was tallied but the missing file failed the review's evidence check, spending the fix loop's one recovery or dismissing a cloud review's approval. The review now re-dispatches that verifier once under a fresh nonce and keeps the reply's verdict meanwhile, and the fix loop's recovery writes to the verdict directory the evidence check reads. (#1144)
- **Implement runs flag acceptance criteria the review disputed.** When the review loop declines a finding because fixing it would contradict an acceptance criterion, the implement workpad now records an Action-required reflection quoting that criterion and the declined finding, even if a later review iteration approves. The maintainer can amend the issue or accept the criterion. If the check cannot read the review records, the workpad says so instead of reporting no disputes. The issue template also asks a criterion that recognizes a case by what a value lacks to name every other output of that value's producer that lacks it, and its route. (#1136)

## September 22, 2026

- **A `{1}` in the implement or review runner variable becomes the issue or pull-request number.** The implement `claude` job and the `command` job now expand `{1}`, in bare labels and JSON arrays, to the target issue or pull-request number. This applies to `DEVFLOW_IMPLEMENT_RUNNER`, `DEVFLOW_REVIEW_RUNNER`, `DEVFLOW_LIGHT_RUNNER` and `DEVFLOW_RUNNER` as those jobs read them. A consumer that launches a runner per job can set a label such as `ci-{0}-issue-{1}` without editing the shipped workflows. When no number resolves, a variable containing `{1}` is skipped for the next one in the chain, so no job waits on a half-formed label. A value without `{1}` resolves exactly as before. **Check existing values:** a literal `{1}` now changes meaning. In a JSON-array value that contains `{1}`, `{0}` and `{{` are now expanded as well. The light and retrospective jobs still expand only `{0}`, and a `{1}` in a variable they read fails their evaluation. (#830)
- **A review that recovers from missing verification evidence now updates its progress comment.** When a review's first verdict post was refused for missing evidence and the review re-ran verification, the progress comment kept the earlier report and completion status while the posted verdict reflected the recovered run. The review now rewrites the comment's report and status from the recovered results before posting the verdict again, so the two agree. (#532)
- **A telemetry branch that kept the old name is accepted again.** If your `telemetry.branch` names a branch that still stores records under `.devflow/logs/` — the old `devflow-telemetry` name kept through config, or a branch you renamed by hand — `/prflow:init` or `install.sh --apply` now moves those records to `.prflow/logs/` in one commit on the same branch, keeping every record's contents and deleting no branch. Writable runs then persist records to it again. A branch holding any other files is left untouched, and ordinary runs never rewrite the branch themselves. (#337)
- **The scheduled retrospective keeps a copy of its learning records.** Every `devflow-retrospective.yml` run now uploads `.prflow/learnings/` as the artifact `retrospective-learnings-<run id>-<attempt>` (kept 7 days), even when the state push fails or the run is cancelled, so a lost push no longer discards the week's analysis — download the artifact and commit its files instead of re-running. Re-run `install.sh` to pick up the updated workflow. (#396)
- **The weekly retrospective now links a pull request to its issue far more often.** It reads
  GitHub's own closing-issue link first, then a `Closes`/`Fixes`/`Resolves` keyword in the PR
  body, then the branch name — including a branch named for your configured
  `implementation_branch_prefix` (previously only `claude/` was recognised, so any other
  configured prefix silently lost its linkage) and, as a last resort, a bare
  `issue-<number>-<slug>` branch. Runs that used to be recorded as `NoIssue` — and audited as
  if they had left no trail — now resolve their issue and its workpad. (#945)
- **Fixed the credential-refresher cleanup misidentifying its own job on Windows runners.** On a self-hosted Windows runner the stop step compared its own pidfile and the swept pidfiles in different path forms, so it reaped its own live refresher and then warned that the refresher had never started. It now compares both in the same normalized form, signals its own refresher, and reaps only other jobs' pidfiles; reading a refresher's process command line no longer logs a spurious "ignored null byte" warning. (#614)
- **`/prflow:implement` no longer stops at Phase 1 on Windows.** The issue-body cache (`preflight.py issue-body --out`) and `parse-acs.py --out` refused every path inside `.prflow/tmp`, because `git` reports the repository root with forward slashes and the containment check compared it against a backslash-normalized path. Both now normalize the scratch root before comparing; paths outside `.prflow/tmp` are still refused.
- **An implement intake that stops early now reports its real cause.** The intake handoff reader rejected a correct `error`/`blocked` handoff from a worker that stopped before classifying the issue or loading the workpad, so the run recorded schema errors instead of the worker's reason. On a stop record, `issue.classification`, `workpad.id` and `workpad.observed_status` may now be null unless `completed_steps` marks their step complete, and a rejected stop record's `blocked_reason` is echoed on stderr. A `proceed` handoff keeps every requirement. (#983)
- **The implement intake worker now checks its own handoff before returning.** It copies the extension loader's digest whole, including its `bytes=` part, and runs the same handoff reader the orchestrator uses, correcting any field the reader names, so a shortened digest is caught when the handoff is written rather than first at the orchestrator's Phase 1 check. (#984)
- **Cloud subagents stop issuing Bash commands the permission matcher refuses.** The cloud workflows now write the grounding block's command-shapes table to `.prflow/tmp/command-shapes.md`, and every Bash-using PRFlow agent reads it before composing a command; the table adds rows for `git -c <key>=<value>` and for an expansion or absolute path as the command name. The base-branch update checkpoint fences now run the granted vendored helper path first, keeping the portable anchor as the fallback, and the implement tier grants `gh pr checkout` and the vendored `pr-note-block.py`. Re-run `install.sh --apply` to pick up the workflow change; with an older installed workflow the file is absent and agents behave as before. (#985)
- **Local implement runs waste fewer calls and read failed CI logs sooner.** An implement run now checks once at start whether `.prflow/vendor/prflow/scripts/` exists; without it, every helper call goes straight to the plugin's own copy instead of failing on the vendored path first. The fresh-session check no longer counts local slash-command output, such as plugin management or reloads, as prior work. `page-job-log.py`, the failed-job recap in `ci-verification-request.py`, and the review's direct log fetch now read a job's log through the jobs-logs API, which serves a finished job's log while the rest of the run is still going. (#989)
- **Cloud workflows can run Claude Opus 5.5.** The shipped workflows pinned a Claude Code
  release (2.1.263) that the API refuses for `claude-opus-5-5`, so every run configured for
  that model failed on its first call. The workflows now run Claude Code 2.1.280. (#995)

## September 21, 2026

- **The review-and-fix loop brackets each review-engine run with two helper calls, and the review-fix worker's post-loop telemetry backstop runs one persist and one self-check.** `review-dirty-tree.sh entry-open` clears the run's diff cache, snapshots the working tree and records the snapshot's object ID before an engine dispatch; `entry-close` runs the branch guard, the compare-and-restore and the entry's evidence grade after it, each printing one JSON line the loop routes on. The same checks run as before with fewer turns; the loop's fallback fences stay in the prose, so a consumer whose vendored helper predates this change keeps working unchanged. Inside `/prflow:implement`, the worker's backstop after the loop no longer repeats the discovery persist the cloud workflow's own backstop step runs, and it gates the dispatch-corroboration self-check on the persist call's own outcome line instead of a separate config read. (#898, #899)
- **The review-and-fix loop's second and later iterations reuse prior PASS verdicts instead of
  re-verifying every checklist item.** `checklist carry` now reads the prior iteration's
  metadata-intact Step 1.8 snapshot pair (`checklist-step1-iter-<N-1>.json` joined by `id` with
  `verification-step1-iter-<N-1>.json`) instead of the verdict-only `checklist` projection in
  `iter-<N-1>.json`, which lacked the `source_file` and `category` the carry rule needs and so
  carried nothing on every multi-iteration run. A carried item reuses its PASS only when its
  verification row's `file_checked`, line anchors removed, is a single path tracked at HEAD and
  outside the changed-file set; every other carried item verifies fresh, and the collector's
  commit-binding gate still demotes a reused PASS whose cited path is absent from the head-view
  inventory. An unusable snapshot carries nothing with a breadcrumb naming the file and the
  cause. About 1.2 minutes saved per second-iteration pass at measured checklist sizes. (#890)
- **Faster review-and-fix loop entry.** The review-and-fix loop now resolves its run key,
  configuration values (iteration cap, fix-severity threshold, below-threshold window and
  telemetry flag) and run directory in one helper call, and proves the PR-head branch check in
  one more, instead of a run of separate shell steps. A `/prflow:review-and-fix` run — and the
  review-and-fix pass inside `/prflow:implement` — reaches its first review in fewer turns, with
  no change to what is reviewed: the same gates, the same iteration count, the same evidence. A
  consumer whose vendored helpers predate this change degrades transparently to the previous
  steps. (#894)
- **The review-and-fix parked-class sweep no longer starts a fix iteration for comment rewordings alone.** A sibling the sweep discovers promotes only when the destination iteration's own fix admission would route it — at or above `fix_severity_threshold`, inside the `fix_below_threshold_iterations` window or beside a Critical/Important sibling — and a sibling whose only impact is behavior-inert prose never drives a promotion by itself (it rides along when another sibling drives). Every sibling not promoted is parked with the existing `parked-sibling: class-sweep` marker and a `parking_evidence.basis` naming the reason. At the default `important` threshold nothing changes. (#857)
- **A clean PR is no longer rejected when a verifier cites two files with a comma or
  checks what the PR changed against a moved base branch.** The review collector now
  resolves a `file_checked` value that joins two repository paths with a comma (each with
  its own line anchors) to both paths, so a proven PASS on a cross-file claim keeps its
  verdict instead of being demoted to INCONCLUSIVE; a path outside the reviewed commit,
  a blank citation, and the view directory alone are still demoted. The checklist verifier
  settles a claim about what the PR changes or leaves untouched against the merge-base
  (three-dot) diff between its base and head revisions, so commits the base branch gained
  after the fork point are no longer recorded as PR changes. (#932)
- **Refusal criteria need an observed refusal before `/prflow:implement` marks them satisfied.** When an acceptance criterion says something is refused, rejected, or blocked, the evidence verifier now marks it satisfied only if a command it ran fed in the input that should be refused and saw the refusal or error message. Routing prose, a by-construction argument, a count of passing assertions, a digest match, or a report that only describes the failure is not enough, and the verifier names which of these was offered. Other criteria are verified as before. (#874)
- **Gate a CI verification request on your own fast checks.** The new opt-in `prflow_implement.ci_verification.pre_request_checks` setting lists commands that must pass before an implementation run dispatches a CI verification run; a failing command refuses the request, so a defect your linters already catch never costs a CI round. A failure the base branch already has does not block the run. `preflight.py lint-changed` gains `--fail-on-findings`, so the changed-file lint can serve as one of those checks. Nothing changes until you list a command. (#870)

## September 20, 2026

- `/prflow:spec` now files issues with `## Technical Context` and `## Implementation Notes` collapsed by default, so the acceptance criteria are visible without scrolling past the implementer reference material. Every other section renders open, and agents read the body text unchanged.
- **A review no longer files a Critical falsehood against a doc line naming a value an agent
  wrote at runtime.** A backticked token now counts as a symbol claim only where your tree
  defines it — a tool emits or parses it, or a shipped skill or agent body mandates it
  verbatim. A token nothing defines refutes nothing and is graded at most a clarity
  suggestion, while a misspelling of a token the tree does define is still a blocking
  falsehood. The rule is stated once, so every review agent reads it once. (#832)
Refresh implementation policy before the documentation worker starts, reusing an unchanged policy only while its complete content remains resident. Changed policy is fully read and its pending obligations reconciled before dispatch. The worker still independently loads policy and refuses a later digest mismatch.
Align review phase routing so checklist generation and independent reviewers are dispatched together, with results collected before the final verdict.
- **Auto-review no longer fires on a draft or conflicting pull request.** When CI
  goes green, the automatic review request now re-checks the pull request's live
  state and is withheld if the PR has been reverted to draft or carries merge
  conflicts — previously only a PR that was already a draft when CI *started* was
  skipped. Mark the PR ready for review, or resolve the conflicts and push a new
  green commit, to request the review again (commenting `/prflow:review` by hand
  always works). (#858)
- **Re-triggering an implement run that already finished a clean review can now reuse that review instead of running it again.** The review-progress rows on the issue workpad are now recorded by the fix loop as each review phase's evidence passes, so a resumed run that stopped right after a clean review finds those rows complete and skips the expensive review phases when its recorded review still matches. Previously the rows were left unticked, which made the resume re-run the whole review. (#856)
- **Review checklist evidence is now bound to the reviewed commit.** The review engine
  materializes a commit-bound source view (a run-scoped file inventory plus blobs from the
  resolved head and base commits) at Phase 0.2 in every mode, including standalone PR mode,
  and checklist generation, verification and lite probes read repository evidence from that
  view instead of the checkout — so a base-checkout that differs from the reviewed head can no
  longer report a head-present file as absent or fabricate a tracked-worker requirement from a
  test fixture. Every verdict carries the `view_revision` it read, and the collector rejects a
  PASS whose provenance the bound inventory cannot confirm. Harness-instruction files
  (`CLAUDE.md`, `AGENTS.md`, `.claude/**`) are stored under a `.src` suffix so a PR-authored
  copy is never loaded as instructions, and the source view fails closed on an unavailable
  commit, failed read, partial materialization or unsafe path. A wording-only contradiction
  now reliably draws its one-shot auxiliary re-ask, and reports distinguish wrong-source
  evidence, unsupported generated requirements and confirmed source defects. (#851)
- **Reshaped the Phase 3.4 acceptance-criteria dispositions record into an exception-shaped, collapsed workpad bullet.** `ac-verifier-artifacts.py` now writes `ac-dispositions.md` as a `<details>` block whose summary states the criterion and tick tallies; a criterion that ticked cleanly carries only four keys, and a criterion that blocked carries the fields that explain it (`reason`, `sides`, `missing_sides`, `undischarged_slots`, `stated_terms`, `observed_value`, and each expected side's reported status and dispositions). The reflection parser in `lib/fetch-pr-context.sh` now recognises a bullet whose own text embeds an inline `<details>…</details>`, so a following friction bullet is no longer silently uncounted. The record shrinks the workpad and points a maintainer at why each criterion blocked. (#681)
- **Review Phase 2 launches every verifier in one wave instead of batches of 8.** The review
  engine now dispatches the verifier of every fresh checklist item from a single message and
  waits only for its slowest verifier rather than for eight-at-a-time batches, so a review, a
  review-and-fix loop, or an implement run reaches its verdict sooner at the same token cost and
  with every launched item verified by its own agent. A launch the harness refuses (`agent thread
  limit reached`) is re-issued with the other refused items once the wave returns, so a harness
  that caps concurrency verifies the pass in ceiling-sized waves and drops no item; an item whose
  re-issue launches nothing ends INCONCLUSIVE. Peak concurrent verifier agents rise from 8 to the
  pass's fresh-item count. (#885)
- **Phase 1 intake writes the issue-body cache and the acceptance-criteria file through the
  bundled helpers instead of retyping them.** `preflight.py` gains an `issue-body` subcommand that
  fetches the body once and writes it byte-exact to `--out`, and `parse-acs.py` gains `--out` that
  writes the rendered criteria to a file; the intake reference now routes both through those helpers
  on both the `IGNORED` and `NOT_IGNORED` arms and reads the files back. A cloud implement run no
  longer spends output tokens re-emitting the body it already fetched, and the cached body is the
  exact bytes `gh` printed rather than a model-authored copy that could pick up the tool-result
  envelope's trailing tags. (#891)
- **A resumed implement run continues its review-and-fix loop at the next iteration instead of
  restarting from iteration 1.** When a cloud implement run is killed mid-loop (a rate cap, a
  runner reclaim, an expired credential) and the stall backstop re-triggers it, the loop now asks
  the new `loop-verdict-marker.py continue-run` subcommand whether a prior attempt of the same
  slug left iteration records bound to the current head — on-disk siblings first, the telemetry
  branch's durable copy second — and, when one binds, restores `iter-1.json` through
  `iter-<N>.json` into its run root (each stamped `restored_from`) and starts at iteration N+1,
  carrying the prior head, checklist and findings forward and running the convergence-time shadow
  as on any later iteration. Every other outcome, including an older vendored helper that lacks the
  subcommand, starts fresh exactly as before; a standalone `/prflow:review-and-fix` run never asks.
  Restored records are excluded from the resumed run's efficiency-record iteration count and cost
  sums so a killed attempt is never double-counted. (#893)
- **Review-engine passes take their batch slices and verifier dispatch plan from the helpers.** In the local-diff modes `review-dirty-tree.sh engine-setup` now mints Phase 1's work directory (`phase1_work_dir`) and, on a diff of more than 10 changed files, writes each batch's slice of the cached diff and reports the batches in its record; a slice it cannot write is `unavailable` and that batch keeps the existing shell fence. `normalize-verdicts.py prepare` wipes the iteration's verdicts directory, partitions the checklist exactly as the collector does and prints one nonce per agent item, so Phase 2 dispatches without reading the checklist artifact into the engine's context. No tool grant, workflow, config key or artifact shape changes; an older vendored helper keeps coverage through the retained fence and the hand partition. (#887)
- **The review's checklist generators now read the pull request's commit.** The checklist-generator dispatch names the run's head source view, the same way the verifier and reviewer dispatches already do, so the checklist is enumerated from the reviewed commit rather than the branch the runner checked out — on the cloud tier, the default branch. (#896)
- **A proven PASS is no longer demoted when the verifier cites several line anchors, two files, or the view-directory path.** The review collector's view-provenance gate now resolves `file_checked` to the bare repository path(s) it cites before the inventory lookup: a comma-separated anchor list (`path:18,158,318-321`), two citations joined by `;` or ` and `, a path under the bound view's own directory (relative, absolute or symlink-resolved), a `\`-separated path, and a harness-instruction file's `.src` stored name all match. Every cited path must still be in that view's inventory, so a path genuinely outside the reviewed commit is demoted exactly as before. The verifier contract states the canonical `file_checked` shape once. Since the gate landed, a clean review whose verifier cited two places was labeled REJECT. (#901)
- **`loop-verdict-marker.py continue-run` reports a resume's prior-run state more precisely.**
  A sibling run directory that holds no iteration record (only `deferrals.json`, say) no longer
  counts as a prior run, so the helper's `none` line reads `no-prior-run` or
  `no-telemetry-branch` instead of `no-well-formed-record`; a restore whose lower records are
  absent or malformed adds one stderr summary naming the iterations it could not restore, while
  the stdout line keeps its closed shape; and the telemetry blob read shares the helper's one
  git environment (`GIT_TERMINAL_PROMPT=0`) with its other git calls. The module docstring now
  states the two origin reaches (`ls-remote`, then `fetch`). (#919)
- **A resumed implement run can reuse a review it already completed at the same head.** On an in-flight resume, the intake worker filed the run's own unfinished work (an unchecked acceptance-criteria gate, an unrecorded final verification) as a review-related correction, and Phase 3 §3.1 read any such correction as a reason to skip its review-reuse check, so a review completed just before the run was killed was always re-run. Intake now files a correction only where there is a claim to correct — a completion claim the workpad makes that later evidence contradicts, or an obligation a comment raises — and leaves a head-bound clean review record to §3.1's `reuse-check`, which verifies head, merge-base, issue digest and Review rows itself. A corrective comment asking for a fresh review still gets one; unreadable resume evidence still yields a sourced unestablished obligation. The handoff schema is unchanged. (#897)
- **Review Phase 2 dispatch plan and setup hardening.** `normalize-verdicts.py prepare` no longer reports a lite checklist item in `missing_fields`, so the field-completion re-ask names agent items only; and `engine-setup` fails closed with a `filesystem` stop, removing its caches, when Phase 1's work directory cannot be created, instead of exiting with a traceback. Follow-up to the #887 helpers. (#928)

## September 19, 2026

- **`/prflow:implement` now reads the CI verdict your branch has already recorded, before it commits the acceptance-criteria gate and the whole documentation phase to that head.** When the review-and-fix phase returns clean, the run lists the branch's completed pull-request and push runs and settles each one from its *jobs*, not its run-level conclusion — so a run whose expensive jobs were skipped (what a repository's own mid-run-push suppression produces, and what makes a check read green in seconds) counts as no verdict at all, and the run keeps walking back to the last result that actually reported. A stale, unfinished, or unrecognised job conclusion counts the same way, so an incomplete run is never read as a pass. Previously that failure was re-discovered only at the final verification step, after every review and documentation dispatch had already run against the rejected head. (#786)
- **A failing verdict never stops a healthy run.** A verdict settled on the current head is treated as a present failure; one settled on an ancestor is decided by re-running only the focused check covering each failed job, never the suite; and anything the run cannot establish — no settling run, a rewritten head, a refused or unparseable read, a covering check this environment cannot run — is recorded as a note and the run continues exactly as before. Only an established, surviving failure is repaired, in one attempt, before the gate runs. (#786)
- **Give a standalone `/prflow:review` its own runner with the new optional `DEVFLOW_REVIEW_RUNNER`
  variable.** The cloud review workflow's `command` job already split its runner two ways —
  `/prflow:review-and-fix` and `/prflow:pr-description` take `DEVFLOW_RUNNER`'s capacity for the test
  suite, while a standalone `/prflow:review` takes `DEVFLOW_LIGHT_RUNNER`. But a standalone review is
  model-API-bound and runs for tens of minutes, and `DEVFLOW_LIGHT_RUNNER` also governs the one-core
  helper jobs that finish in about a minute — so sizing one tier always mis-sized the other. Set
  `DEVFLOW_REVIEW_RUNNER` (a bare label or a JSON label array, the same shapes as the other runner
  variables) and the standalone-review job alone moves to it. Leave it unset and the expression falls
  through to `DEVFLOW_LIGHT_RUNNER`, then `DEVFLOW_RUNNER`, then `ubuntu-latest`, so nothing moves.
- **Verifiers no longer pass a claim on a probe that could not support it.** The acceptance-criteria
  evidence verifier and the checklist verifier now treat a refused or errored probe as establishing
  nothing (never a no-match or absence result), require a probe narrower than the claim's scope to
  say why that scope covers the claim before it can back a pass, and require a claim about logic the
  diff changed to be measured against that artifact's own bytes rather than a re-typed copy. The
  issue-claim auditor's count pass now records the number of distinct items and names the enumeration
  command it counted. A checklist item categorised `absolute_claim` must also trace one named
  adversarial input through the code before it can report the property proven. (#620)
- **A review no longer measures your pull request against a base it never forked from.** On a
  cloud review the job shallow-fetched the base branch, and every later `git merge-base` in
  that job then answered with a far older commit instead of failing — so a one-file change
  sitting behind a busy base was measured as dozens of files and thousands of lines, demanding
  checklist evidence it never owed and ending in a `PRFlow:ReviewStuck` verdict about files the
  pull request never touched. The review job now keeps the full history its checkout fetched,
  and the diff measurement refuses to report a size at all in a shallow clone — reported as an
  unestablished check rather than a failed review. (#802)
- **Warn when a nested repository ignores an ancestor `.prflow/`.** PRFlow resolves its default
  configuration and prompt-extension paths from the nearest Git root. In a submodule, a vendored
  inner repository, or a monorepo whose `.prflow/` does not sit at the Git root, that root carries
  no configuration and every read quietly fell back to a built-in default. Those reads now write
  one line to stderr naming the root they used, the ancestor `.prflow/` they did not read, and the
  explicit option that points them at it. Path resolution is unchanged, so output and exit codes
  are exactly as before, and a repository with its own `.prflow/` stays silent. (#12)
- **The weekly retrospective now fails visibly when its delivery fails.** A scheduled
  retrospective run records each required delivery operation — state-PR push, issue filing,
  and report post — in one run-bound outcome record, and an unconditional workflow step
  classifies that record after the agent finishes: a positively-established delivery failure
  now fails the job instead of concluding success on the agent step alone, while missing or
  incomplete evidence is reported as a warning without failing the job. When the agent stopped
  before recording, a read-only GitHub check fails the job if the learnings branch or report
  comment is absent; a week with no new pull requests stays green. The workflow refuses
  an installed helper that lacks the outcome-record capability before launching, so the
  enforcement activates only when the matching workflow and plugin version are deployed
  together. (#395)
- **Implement's resume no longer re-runs a clean issue-claim audit the workpad already records.** The audit's completing write records an `audit-inputs` row binding it to the live issue body, the resolved acceptance criteria, the run capability, the versioning policy and the merge-base with the base branch; `workpad.py reuse-check <issue> audit` checks all five. Phase 1.6 adopts the recorded audit only when every input matches and the base has moved at most three commits since; any mismatch, drift, or unresolved input re-runs the audit. (#689)
- **A cancelled cloud implement run that recovery cannot attribute now says so instead of
  reporting a clean recovery.** When every evidence read succeeds but finds neither a reclaim
  marker nor a human-cancellation notice, the cause is unknown and may be deterministic, so
  recovery still declines to auto-resume — but the workflow now raises a warning and the
  workpad note names the declined recovery, points at the branch holding the committed work,
  and asks you to investigate the cause before re-running. A failed evidence read keeps the
  plain cancelled note. (#798)
- **PRFlow helpers now explain themselves and fail with a clear message.** `pr-note-block.py` accepts an optional body-file argument (`strip [<file>]`, `add <note> [<file>]`), reading stdin only when no file is given; `--help` prints usage, and a misuse (no subcommand, unknown subcommand, `add` with no note, an extra operand, an empty or non-UTF-8 body, or a missing/unreadable file) prints one usage line on stderr and exits 2 with empty stdout. `discover-deferral-manifests.py`, `normalize-verdicts.py` and `prompt-surface-growth.py` treat `--help` or `-h` anywhere on the command line as a help request, printing usage and doing nothing else; `discover-deferral-manifests.py` lists its three invocation forms. (#636)
- **Human-facing output from shipped `scripts/` and `lib/` helpers now uses the `prflow: ` prefix** instead of `devflow: `. The one exception is the `devflow: posted comment on #` breadcrumb, which several workflow and script consumers match exactly; it stays unchanged and is recorded in `lib/rename-map.json`'s frozen identifiers. Other `devflow`-family prefixes remain as they were, so logs still show both names in places this change did not touch. Nobody has to change a setting. (#636)
- **`/prflow:implement` runs its documentation pass before the acceptance-criteria gate, so an
  awaited completion verification overlaps the rest of the run.** After the review-and-fix loop
  the orchestrator dispatches the finalization worker with `STAGE: documentation`: it runs the
  documentation pass, then — when the consumer's implement extension defines a verification
  that is requested and awaited — requests it for the pushed head without waiting. The
  acceptance-criteria gate, follow-up filing and the PR description run while that
  verification does; final-tree evidence is still established for the `HEAD` finalization
  reads, so a head that moves afterwards needs its own request. A failed stage only loses the
  overlap: finalization runs the documentation pass itself when the workpad `Documentation` row
  is unticked.
- **A resumed run no longer re-waits a CI failure already on record.**
  `ci-verification-request.py request` adopts a prior attempt's completed same-head dispatch
  run that concluded `failure` when no green one exists, so `wait` reports that verdict at once;
  the fix-loop phase's last-real-CI-verdict read now counts `workflow_dispatch` runs, and a
  resumed run takes that read before dispatching the loop.
- **An implement run whose first review iteration is clean no longer runs the fix loop's confirmation passes.** When the review-and-fix loop runs inside `/prflow:implement` and iteration 1 is clean — a non-rejecting engine verdict with no failed or inconclusive check, a complete reviewer roster, no finding that stands at Important or above, a verified fix-delta gate that raised no such finding, and a parked-class sweep that registered nothing to fix — the loop skips the iteration-2 re-review and the shadow pass and reports `shadow skipped, iteration 1 clean`; the pull-request review is the independent pass for that run. A first iteration that fixed, pushed back, deferred or parked an Important finding runs the loop as before, as do standalone `/prflow:review-and-fix`, the bounded re-review after unresolved shadow findings, and a run whose prompt extension declares a shadow trigger that holds. The loop-verdict marker gains a `coverage=skipped` token, read as `CLEAN-SHADOW-SKIPPED`. (#822)
- **Review passes spend less time on checklist verification.** A verifier dispatch now names
  its checklist item and verdict file instead of re-stating the verification rules, a verifier
  that wrote its verdict file replies with one line instead of a full report, and the bundled
  helper assembles the verification results file that the review engine used to write by hand.
  Which items get their own verifier agent is unchanged, and an item whose verifier delivers
  nothing is still recorded as inconclusive. (#823)
- **A cloud run whose runner dies abruptly can now still yield its execution transcript.** A
  host-level runner termination runs none of a job's post-steps, so the transcript upload never
  fired and the run left no transcript. The new opt-in
  `prflow.execution_transcript_job_log_enabled` streams every agent message into the
  `/prflow:implement` job's log as it happens and, when `execution_transcript_artifact_enabled`
  is also on, a downstream recovery job rebuilds the transcript from that log and uploads it
  under the usual artifact name. Default off: the job log is neither scrubbed nor masked, so it
  can carry credentials such as refreshed App tokens. The setting is applied only when GitHub
  reports the repository as private; in a public repository, or when the visibility is not
  reported, streaming stays off and the run logs a warning saying why. The log also grows to the
  transcript's own size. (#799)
- **Review passes spend less time assembling the verification checklist.** The review engine used to paste each checklist batch into the deduper's prompt and then re-type the finished checklist into its artifact file. Now each checklist generator writes its own batch file, the deduper reads that file and returns only the groups of items it judges to be duplicates, and a bundled helper applies the merge, numbering, 100-item cap and carry-forward rules and writes the checklist. Before writing, the helper traces each generated item by id into the items it keeps, merges or caps, and refuses to write a checklist when an id is unaccounted for; the review then reports that the checklist was not generated instead of approving cleanly. The helper also leaves a duplicate group unmerged when its items share no claim signature, no nearby location in the same file and category, and no convention check; deciding whether two items that do share one are the same claim remains the deduper's judgment. The `checklist-generator` agent gains the `Write` tool for that one scratch file under `.prflow/tmp/`; if its write is refused it returns the checklist inline as before.
- **`/prflow:init` can now be invoked by the model, not only explicitly by you.** The
  `disable-model-invocation` guard has been removed so Claude can run the setup command when a
  repo needs its PRFlow config scaffolded or backfilled, instead of waiting for you to type the
  slash command.
- **The test-first gate now runs the changed file itself, never a re-typed copy of its logic.** The RED/GREEN check that guards a fix (and Phase 2's implementation) must invoke the changed artifact as it ships, not a transcribed copy of its rule pasted into a one-off command — a copy establishes nothing and is never recorded as a passing check. When no permitted way to run the file exists, the fix loop records an honest `unrunnable` result and Phase 2 treats the check as unestablished, whether or not a permission denial was seen first, so a `RED-confirmed` record now means the shipped code actually ran. (#682)
- Added `/prflow:challenge` to stress-test ideas, issues, approaches, and approved PRs against evidence, risks, priority, and simpler alternatives.

## September 18, 2026

- **The review's coverage reviewer now flags a new gating branch nothing tests.** When a diff
  adds a branch to a helper whose result decides a fail-open/fail-closed outcome, a verdict, or
  a gate, the reviewer checks that one assertion actually drives that branch instead of reading
  it as covered because its siblings are tested, and reports the gap by name. The check is
  scoped to those helpers, so an ordinary added conditional is unaffected. (#384)
- **PRFlow commands now run their bundled helpers in a worktree-isolated session.** Such a
  session refuses any command whose program name is computed by a shell expansion, and every
  skill's portable helper-anchor rule told the agent to invoke helpers with that expansion left
  in place — so workpad updates, label writes and the consumer prompt-extension load were all
  refused there. The rule now has the agent fill in the resolved directory before it runs the
  command. (#684)
- **A pull request opened by an automatically resumed implement run is now assigned to the
  person who started it.** When a stalled or interrupted cloud run was resumed automatically,
  the resume comment's author was the PRFlow bot, so the run tried to assign the new pull
  request to that bot — which GitHub refuses — and the pull request was left unassigned. Each
  automatic resume now carries the originating person forward, however many resumes intervene,
  and re-posting the trigger yourself makes you the new owner. If that identity ever cannot be
  read, the run records a named reason and leaves the pull request unassigned instead of
  failing the assignment. (#512)
- **A cloud review-and-fix run now clears its cached diff between engine passes instead of
  losing one call to a permission refusal.** The re-entrant cache delete used a shell wildcard
  and a zsh guard, both of which the cloud permission layer refuses, so stale review slices
  from an earlier commit could survive into the next review pass. It now lists the files first
  and deletes them by name. (#564)
- **Neutral wording for non-blocking issue references in the issue template.** The issue
  template now routes advisory or conditional cross-issue references to `Technical Context`
  with neutral `Related work: #N` wording. Because the preflight reads dependency phrasing
  (`depends on`, `blocked by`, a line-leading `After #N`) as a real prerequisite wherever it
  appears — not only inside `## Dependencies` — an advisory reference must use the neutral
  wording so a related ticket mentioned for context no longer accidentally becomes an
  execution prerequisite. (#382)
- **The execution-transcript and denied-command scrubber now redacts more credential shapes.** In addition to GitHub tokens, Anthropic keys and Authorization headers, it now removes AWS access key IDs, npm/Slack/GitLab tokens, connection-string passwords, `Password=`/`Pwd=` values, and PEM private keys before a transcript artifact or denied-command record is stored. The Observability and Privacy page now also states who can download a transcript artifact, the seven-day retention the workflows request, which credential shapes stay unrecognized, and that the scrub only ever replaces matched credential spans. (#638)
- **Review and finalize steps now state their progress-row labels inline instead of reading `scripts/workpad.py` source.** `skills/review/SKILL.md` renders the review-boundary Blueprint rows and states their `--tick-progress` substrings, `skills/review-and-fix/references/loop-exit.md` names the final review row and its substring, and implement's Phase 4.3 finalize states the terminal `PR marked ready` row instead of naming `workpad.py` as its owner. Implement's root skill still points at the row constants for the whole `## Progress` inventory, which this change leaves alone. Phase 4's validation step also drops its pointer to the finalization validator's module header, which the parent never needed. (#671)
- **A finished review is no longer thrown away when the last iteration was a shadow-promoted one.**
  The fix loop's terminal verdict stamp now selects which review to grade instead of always grading
  the primary entry: it grades the primary review at the final iteration when one exists, and
  otherwise — for an iteration the shadow review promoted, where the primary engine never ran —
  grades the shadow review that actually covered the final diff. A run that ends after such an
  iteration is now graded on that review's own evidence and stamps its verdict marker when that
  evidence passes, instead of refusing with `evidence-missing` because the primary entry is
  absent. (#676)
- **The fix loop's review engine now runs as a dedicated `prflow:review-engine` agent** that reads
  one shared engine-entry procedure — the single home of the steps the primary and shadow entries
  both follow — and must write its checklist, verification, per-item verifier and return files
  before returning. The loop no longer hand-composes the engine's instructions into each dispatch
  prompt. A review that skips those evidence files is still not silently accepted: the loop grades
  each entry's own evidence before consuming its verdict, then recovers or blocks rather than
  losing a good, completed run. A runner that cannot dispatch agents still falls back to running
  the engine inline. (#676)
- **The `prflow:review-engine` agent no longer requests an edit-in-place tool.** The engine
  authors its checklist, verification, verifier and return files outright and makes every other
  change through its helpers, so the grant was never exercised. Dropping it keeps the reviewing
  agent to the tools it actually uses. (#676)
- **An implement run no longer stops over an ordinary branch or working-tree problem.** Setup used to
  end the run and wait for a human on about a dozen conditions that say nothing about the issue being
  implemented — history it could not vouch for, a dirty tree, a branch live in another worktree, a
  failed base merge, a rejected push. Each of those now takes a recovery action and continues, with
  what it did recorded on the workpad: setup either carries on with the branch it found or cuts a
  fresh one from the base, leaving the old branch's commits untouched. Setup still stops for two
  reasons only — its worker failed, or no working branch could be established at all. In particular,
  a run interrupted after its work was committed but before its pull request opened now resumes on
  its own instead of stranding. (#687)
- **Installed cloud workflows no longer drift from your setup.** The implement job now installs `ruff` only through the setup action's manifest provisioning — the duplicate `pip install` step is gone — so linting uses the version your lint manifest pins. The three workflows that upload artifacts now use `actions/upload-artifact@v7` (Node 24), which needs a self-hosted Actions Runner of 2.327.1 or later. When the implement tier ignores your `setup.git_dir_pin`, and when a committed vendored plugin copy is a different version than your configured `prflow_version`, the run summary now carries a visible warning or notice instead of a silent log line. (#624)
- **An implementation run now opens its workpad with one read instead of five.** Phase 1 used to
  ask GitHub separately for the workpad's comment id, its live Status, its body and its recorded
  prior status — then fetch the body a second time when resuming. A new `workpad.py intake-triage`
  subcommand returns all of it as one JSON object from a single comment scan, so a one-page
  workpad costs two GitHub requests where it used to cost ten, and the run spends less of its
  context on setup. The intake procedure now spells out that call and its result in full, so a
  normal run no longer loads the helper's `--help` text at all. The new read never writes: status
  updates keep their own live re-fetch, precondition checks and verification, and a workpad that
  is present but unreadable — a duplicated workpad comment, an unrecognized Status, or conflicting
  prior-status markers — stops the run with a clear cause instead of guessing. (#436)
- **`/prflow:implement` no longer loads the combined documentation pass when your configuration has already disabled both of its synchronization steps.** With `docs.internal_enabled` and `docs.external_enabled` both set to `false`, no documentation deliverable named in the issue, no deferred "relocate to docs" note, and no `docs` prompt extension of your own, Phase 4 now dispatches the release-notes step directly instead of the combined router. Release notes and changelog reconciliation still run every time, a documentation file the issue names still reaches its owning step even when that step's toggle is `false`, and anything the run cannot establish — an unreadable toggle, an unplaced relocation, a `docs` extension it cannot read — keeps the full combined pass. (#440)
- **`/prflow:docs-sync-internal` no longer starts an internal documentation tree as a side effect.** When the configured internal root holds no tracked Markdown page — it is missing, or contains only a `.gitkeep` placeholder — the step now changes nothing and reports that the repository needs `/prflow:docs-bootstrap-internal` first; an implement run stops as Blocked with that remedy and the root named. A root that already has a Markdown page but no `index.md` is still repaired in place. (#440)
- **A workpad that hits GitHub's comment size limit can now be shrunk without losing
  anything.** A run whose workpad reached the limit had no supported way to recover, so
  it improvised — and one run cut the tails off over-length progress bullets, destroying
  the record its own completion gate reads. `workpad.py compact <issue>` now moves the
  oldest ordinary progress and notes bullets, whole lines only and never one carrying a
  machine-read marker, byte-for-byte into a single overflow comment on the same issue,
  posting that comment before it rewrites the workpad so no failure can drop the text
  from both places. Every workpad write also reports its remaining headroom, warning and
  naming the new command once the body passes 57,344 bytes. (#755)
- **An implement run no longer files a follow-up issue for a review finding it is about to fix
  itself.** Deferred-review filing runs before the documentation pass, so a parked finding against
  a file the issue's own `**Documentation Needed**` block already names produced a permanent
  `Deferred` ticket minutes before the run edited that very file — leaving a human to read it,
  check it against the branch and close it by hand. `scripts/file-deferrals.py` now resolves the
  run's deliverable path set once, through `scripts/extract-doc-needed-paths.sh` over the source
  issue's body, and partitions out every manifest entry whose `file` matches one exactly: no issue
  is created, the entry stays in the rewritten aggregate under the new category
  `scheduled-in-run` with no `follow_up`, and one `scheduled-in-run id=… file=… deliverable=…`
  record per skip goes to the run's workpad. (#758)
- **A `scheduled-in-run` finding renders nothing in the pull request description.**
  `/prflow:pr-description` treats the category as deliberately non-renderable — no
  Scope-Acknowledged Findings row, no hidden machine-payload entry — and removes a row an earlier
  pass rendered for the same finding rather than carrying it forward, so the table never
  contradicts the branch it describes. A `settled-by-disclosure` foreclosure row is untouched by
  that arm and is still carried forward. (#758)
- **The new partition fails open.** An unreadable issue body or a non-zero extractor leaves the
  deliverable set *unknown* rather than empty: every entry files exactly as it did before, after a
  single `scheduled-in-run result=unavailable cause=…` record naming the failed read. The value is
  written only on the aggregate the filer rewrites; the review-and-fix loop's own `deferrals.json`
  and its `skip_category` set are unchanged. (#758)

## September 17, 2026

- **`/prflow:implement` no longer runs your test suite twice while finalizing.** The PR-description
  step now audits the PR body's test claims by reading the tests in the diff instead of launching a
  run of its own, leaving the final-tree run that follows it as the run's only whole-suite execution.
  Repositories with slow suites see the largest saving. (#618)
- **The independent shadow review can no longer be signed off with the fix loop's own evidence.** The shadow pass and the loop's last iteration write to the same checklist, verification and verifier-file paths, so a shadow that did not finish its own verification could previously be graded against what the loop had already produced. The evidence check now refuses a shadow whose checklist or verification file is still the loop's, ignores verifier files the loop wrote, and refuses leftover verifier files that belong to no checked claim — each of which sends the shadow into its existing one-attempt recovery instead of a clean merge verdict. Where the check cannot read what it needs to compare against, the shadow is likewise sent into recovery rather than passed. Re-running the shadow also replaces its recorded verifier files rather than adding to them. (#621)
- **A switched-off base-update checkpoint and a switched-off Spot watcher now read as disabled.** With `prflow_implement.update_branch_checkpoints` set to false, the final implement workpad row called the skipped checkpoint "clean" even though the branch was never compared with its base; it now says base-update checkpoints are disabled by config, that the branch was not reconciled with its base, and how far behind branch setup measured it. With `prflow_implement.spot_interruption_watcher.enabled` set to false, the run log reported a wrong value type; it now reports the watcher as disabled by config. Every other unaccepted value keeps its existing wrong-type message. (#623)
- **`/prflow:implement` no longer forbids Phase 3 from writing a documentation page an acceptance criterion requires.** The skill told Phase 2 and Phase 3 to leave a `docs/…` criterion for the Phase 4.1 documentation pass, while the shared review engine that Phase 3.3 runs REJECTs an unmet decided criterion — so the fix loop had to author the page the prose forbade it to touch. Phase 3.3 is now a permitted author, Phase 4.1 is the deadline and backstop that writes any page Phase 3.3 did not and then ticks the criterion, and Phase 2 still does not author it. The review engine is unchanged: a standalone `/prflow:review` still REJECTs an unmet documentation criterion. (#571)
- **`/prflow:implement` starts with about 21% less orchestrator prose in context.** The root skill was trimmed to its operative rules — every helper fence, gate, and contract is unchanged — so each run begins with more context headroom before Phase 1. (#570)
- **Reviews no longer spend an extra round recovering verifier evidence they should have produced.** A fanned-out review that checked claims by reading source in its own context left no per-item verifier file, so the loop's evidence gate failed the first grade and burned its one recovery attempt re-running the checks. Phase 2 now confirms every fresh agent-mode checklist item has its verifier file before the results are written, and re-dispatches the real verifier for any that is missing; the recovery attempt stays available for a genuine miss. (#572)
- **An implement run's status labels, resume run-link refresh, stopped-run notes and cost record now reach its PR even when GitHub creates no closing link.** A PR targeting a non-default branch, or an adopted PR with no closing keyword, is found from the run's own `**PR:**` binding on the workpad. On adoption, a failed `closes-issue` check now warns that merging will not close the issue and that a person must link or close it. (#626)
- **PRFlow's helpers now read and write text the same way on Windows as on Linux.** On a
  Windows runner with native Python, helpers decoded text with the locale code page and
  translated newlines, so labels lost their configured fallback, composed plugin and
  marketplace lists carried a stray carriage return, PR body notes came back with garbled
  punctuation, verifier paths mixed `/` and `\`, and the changed-file lint never ran. Every
  helper now states its own UTF-8 codec, writes LF-only machine output, emits forward-slash
  paths, and takes its receipt lock through the Windows locking primitive. (#631)
- **Review fix loops stop re-verifying claims nothing changed, and re-check acceptance criteria at every head.** From the second iteration on, a review-and-fix run now carries forward the checklist claims whose files the previous fix left alone, keeping each claim's identity so a prior PASS is reused instead of dispatching another verifier. Acceptance-criteria items are never carried: they are regenerated and re-checked at every iteration, so a criterion can no longer be approved on a verdict taken before a base merge. When the run cannot establish which files changed — a shallow checkout, for instance — it carries nothing and says so rather than reusing a stale verdict. (#644)
- **A review no longer stalls on `review-artifact-malformed` because the engine wrapped its checklist in an object.** Phase 1.6 and Phase 2.2 now state that `checklist-iter-<N>.json` and `verification-iter-<N>.json` are JSON arrays at the file root, distinct from the object-rooted coverage-shortfall and engine-return artifacts; the evidence gate still rejects an object at those paths, and recovery re-runs the writers instead of reshaping the file. (#579)
- **A workpad checklist item that is already ticked no longer counts as a failure.** Repeating a
  tick — on a resumed run, or twice in the same run — now succeeds quietly instead of reporting an
  error and re-printing the whole workpad comment, so runs spend fewer steps on bookkeeping. A tick
  that matches nothing, or that is ambiguous between several rows, is still reported, and the
  message now says which of the two it was. (#635)
- **Re-planning keeps the plan steps you already completed.** When a run rewrites its `## Plan`, every
  step whose wording is unchanged keeps its tick, so a resumed run sees accurate progress instead of
  an all-unchecked plan. A step whose wording was edited starts unchecked, as before. (#635)
- **`PR marked ready` is ticked only when the pull request is actually published.** A run configured
  to leave its PR as a draft — or whose publish step fails — now finishes with that row unticked
  beside the note explaining why, so a draft delivery is distinguishable from a published one at a
  glance. (#635)
- **Cloud implementation runs no longer stop for a dirty tree before intake.** The run inspects the
  tracked changes, restores those setup produced, keeps its own uncommitted work, notes the decision
  and continues; a local run still never touches your tree. A stop before intake is now recorded as
  👎 Blocked on an existing workpad,
  so the stall backstop no longer spends a resume on a stop that would repeat. A step your implement
  extension requires but the run cannot perform — its tool, MCP server or skill is not loaded, not
  permitted or not authenticated — is recorded once as a reflection and skipped instead of being
  retried. The cloud setup page now lists which project plugins cloud runs load. (#646)
- **The implement workpad reads more cleanly.** Its title is now just `# PRFlow Workpad` — it is
  a comment on the issue, so it no longer repeats the issue number — and the Setup row drops its
  `— branch & workpad` tail. Each extension row now names the file it loaded (`Skill extension
  resolved: implement.md` in place of `prompt extension resolved: implement`), so a glance at the
  row tells you which `.prflow/skill-extensions/` file the run resolved, and the fix-loop gate row
  reads `Review-and-fix loop`. Every row, note and reflection starts with a capital letter unless
  it opens with a literal a reader matches, such as `/prflow:implement run started`. Two Phase 1
  startup rows became one: `agent entered Phase 1 setup; workpad triage passed` is gone — the
  hydration row that follows it already records that triage passed — which also saves a write
  against the GitHub API on every cloud run. The branch-setup agent's fresh-create arm writes the
  branch-qualified resume verdict alone instead of that plus a record line whose fields all read
  `n/a`, and the issue-claim auditor folds every pass that found nothing into one line rather than
  one line per silent pass. A workpad mid-run when you update keeps its existing rows and resumes
  normally; both spellings of the resume verdict are read.
- **`/prflow:implement` records its Phase 2 sweep results in one workpad update instead of one
  per sweep.** The sweep receipts and the operand-ledger entry they accompany now share a single
  call, so a run spends fewer turns and the workpad comment is rewritten once per boundary
  rather than once per sweep. (#692)
- **Implement no longer stalls at branch setup over the handoff operand.** Phase 1.4 listed `HANDOFF` among path operands, so a run could pass the intake handoff file and be blocked with `invalid-handoff-operand`. The operand list now names the accepted provenance words. (#683)

## September 16, 2026

Cloud implement recovery now reports the real cause of a lost runner instead of
calling every loss a Spot reclaim. When the `claude` job of a cloud implement run
dies, the `spot_recovery` job's resume comments, terminalize comments, and
Cancelled workpad notes now carry a cause line naming the job's conclusion, its
capacity token (the runner label's `spot=<value>` segment, verbatim), its runner
name, and GitHub's failure annotation — and only claim a Spot reclaim on the path
that holds a valid reclaim marker. A proven reclaim whose resume is refused at the
cap or for a missing App token now ends the workpad in a terminal 💥 Failed state
instead of leaving it indefinitely in progress, and every terminal flip the
recovery job makes records whether the run's branch is empty.
- **Deferred review findings are now grouped into follow-up issues by their shared deferral reason, not by source file.** When an `/implement` run files follow-up issues for deferred review findings, `scripts/file-deferrals.py` in manifest mode now groups findings that agree on category, explanation (compared after trimming) and kind into one follow-up issue — however many files they span — and titles it from that shared reason (`<area>: deferred review findings — <kind> (<category>) (carried from #<n>)`, with `<area>` derived from the group's longest shared path prefix). A finding that cannot supply all three reason fields falls back to per-file grouping exactly as before. Fewer near-duplicate tickets for one piece of deferred work. (#602)
- **A re-triggered issue resumes on its own** — Re-running `/prflow:implement` on an issue an earlier run left blocked picks the work back up and re-runs the step that stopped, so a fixed blocker clears without any extra prompt. Implement runs stay hands-off from start to finish on both the local and cloud tiers; when a decision the issue does not settle comes up, the run records it as a block to settle by editing the issue and re-triggering. You get this through the normal plugin update. (#596)
- **A failed CI verification round now reports which jobs failed and why.** When
  `ci-verification-request.py wait` sees a failed run, it now prints the name of each failed
  job and every identifier from the `Failure recap` in those jobs' logs, after its existing
  `FAILED` line, so the failure list is in the command's own output without opening the logs
  by hand; the exit status is unchanged. (#603)
- **`preflight.py lint-changed` now flags a ruff version skew.** Each ruff invocation receipt,
  and the command's summary line, now records whether the ruff that ran matches the version
  the lint manifest pins (`match`, `skew`, or `unestablished`). The comparison is advisory and
  changes no exit status. (#603)
- **Cloud `/prflow:implement` runs one agent per issue at a time.** The `claude` job in `devflow-implement.yml` now has a per-issue concurrency group that queues and never cancels. A stall-backstop auto-resume, or a re-trigger that gets past dedupe, waits for the in-progress run for that issue to finish, so two agents can no longer write the same workpad and branch at once. If GitHub cancels a queued job before it starts because a newer one replaced it, the recovery job does nothing, so it cannot flip the live run's workpad to Cancelled. (#471)
- **Branch setup now rejects an invalid provenance value instead of blocking on provenance.** If
  `/prflow:implement` passed anything other than `created-current-run`, `adopted-existing` or
  `unknown` to branch setup, the run used to stop with a misleading "provenance not
  established" decision, and the stop message sent people to the wrong fix. Branch setup now
  refuses the value before doing any work, and the stop reason names the value it got and the
  values it accepts. (#595)
- **An implement run fixing a failed final CI check no longer shows as Stuck.** When the final verification fails and your repository's implement prompt extension sends that failure back to be fixed, the issue keeps its in-progress status (no `PRFlow:Stuck` label, no 👎) while the run makes the fix. It shows Blocked only if the failure can't be fixed. (#562)
- **A resumed cloud implement run now reuses a CI run a prior attempt already passed for the
  same head, instead of re-dispatching.** `ci-verification-request.py request` records live on
  the runner's local disk, so a resume on a fresh runner held no record for an earlier attempt's
  green `workflow_dispatch` CI run and had to re-dispatch and wait a full CI cycle. `request`
  now adopts a completed-successful same-head dispatch run whose run title carries a request-id
  token, reconstructing the request record under that identity; `collect-evidence` still
  re-binds the downloaded shard provenance to the adopted run before building any evidence, so
  adoption grants no new trust. Adoption is best-effort — an ambiguous match, a tokenless run, a
  non-green run, or a run-list transport failure falls through to a normal dispatch. (#545)
- **Cloud runs no longer preinstall the `code-review` and `claude-md-management` plugins.** The
  PRFlow cloud workflows now install only PRFlow itself, plus any plugins your repository enables
  in `.claude/settings.json`. PRFlow never depended on either plugin. If you use their
  `/code-review` or `/revise-claude-md` commands in cloud runs, enable
  `code-review@claude-plugins-official` or `claude-md-management@claude-plugins-official` in your
  committed `.claude/settings.json`, and the cloud runs will install them again.
- **Long cloud runs on self-hosted Windows runners no longer fail with GitHub `401 Bad credentials` after about an hour.** With a GitHub App configured, PRFlow's Python helpers on a native-Windows Python kept using the token minted when the job started, even though the credential refresher was renewing it. Once that token expired, the helpers could no longer write the workpad, and the run looked like a stall until the stall backstop gave up. These helpers now use the refreshed token, as the shell helpers already did.
- **Re-running `/prflow:implement` no longer repeats planning and review that are still valid.** When a run is started again after an earlier attempt failed or finished, it now reuses the earlier plan if the issue text has not changed. It also reuses the earlier review when that review passed with full coverage and the branch, its base and the issue text are all unchanged. Otherwise the run plans and reviews as before. A new commit, a change to the base branch, an edited issue, or a correction asking for a fresh review still triggers a full review. (#616)
- **The implement cleanup review now sees the issue's acceptance criteria.** The `/prflow:implement` cleanup reviewer received only the diff, so it could recommend deleting tests an acceptance criterion required and call them scope creep. It now receives the current criteria and treats the behavior and tests they require as fixed scope, while still flagging genuinely redundant tests and stale references. Its report format now lives in the reviewer's own definition instead of a tool-denial note in the dispatch. The finalization handoff check also rejects an extension-load record with unknown fields, or one that claims the whole extension was read without the digest the full load ends with. (#622)
- **Cloud implementation and command runs can run `git grep`, and agents stop retrying refused commands.** Re-run the PRFlow installer to receive the new grant. (#629)
- **The self-hosted runner docs now state PRFlow's Windows trust boundary.** PRFlow cannot make its job credential files owner-only on Windows. The Windows Runners section now says to run each runner service under its own account and restrict its work directory to that account and administrators, with the `icacls` commands that set and show that access. It also notes that runner services sharing one account share its Claude settings and can read each other's credentials. The documentation page for `/prflow:docs-verify --report-only` now names the report's `Doc verdict and location` field correctly. (#633, #594)

## September 15, 2026

Reconcile fulfilled documentation obligations in the final workpad. A documentation
obligation a run first recorded as friction under **Action required** can now be moved
to the Notes section with its checked completion evidence — `scripts/workpad.py update
--resolve-doc-reflection TARGET EVIDENCE` — so the final workpad no longer shows the
same deliverable as both done and unresolved. The moved bullet keeps its original
failure glyph and kind, so it still contributes to retrospective friction; an absent or
ambiguous target refuses the resolution without changing another reflection, and
replaying the same resolution is idempotent. (#508)
- **Lint-tool provisioning now retries transient download failures.** `provision-lint-tools.sh` downloaded each pinned tool with a single-shot `curl`, so an intermittent HTTP 500 or blip from the release CDN failed the whole provisioning run on the first error. The download now uses curl's bounded retry, riding out the transient before failing closed; the pinned-digest check still refuses any bytes a retry brings back. (#550)
- **Issue premise checks no longer reject a quoted sentence over its final punctuation.** When an issue's `Verified:` bullet quotes a sentence that still exists in the cited file but now ends with different punctuation (for example a colon instead of a period), implement treats the premise as still holding instead of discarding it and recording a false issue-accuracy note. A changed word or a removed sentence is still reported as no longer present. (#523)
- **`/prflow:spec` no longer re-audits an unrevised draft after a `REVISE` round.** When an
  audit returns must-revise findings, the drafting command now applies the confirmed findings
  and re-shows the revised draft before offering another audit round: `record-offer --accepted`
  refuses (leaving the user-round counter untouched) while the last completed `REVISE` round's
  findings are unrevised or their count is unestablished, a new `query-offer` surfaces that
  withhold so the Step 4 approval question omits the audit-round option, and the withhold
  releases once a revision postdates the round that raised the findings. Operators stop
  spending audit rounds and tokens on unchanged bytes. (#548)
Restore same-branch tracked checkout changes left by a review-engine return. The review-and-fix
loop now snapshots the working tree before every engine Step 1 dispatch and every shadow Step 2.6
dispatch and, when the branch name still matches on return, restores previously-clean tracked
paths the return dirtied — so engine and shadow leftovers no longer ship silently into a later fix
commit. Preexisting dirty work, `.prflow/tmp` scratch, and rename/copy records are left untouched;
the helper restores only previously-clean tracked paths to HEAD, so residuals it cannot restore —
untracked files and staged additions not in HEAD — are left in place rather than restored (a path
that becomes a staged addition during the window is flagged), and the implement Phase 3.3
residual-porcelain flush no longer names those helper-unrestorable residuals as review-feedback fixes.
- **The review-and-fix shadow pass now derives its "no prompt additions" attestation from the
  prompts it actually sent.** Before each dispatch a shadow pass issues, it now persists the exact
  prompt to the run root and reads those files back to compute the attestation, so a shadow whose
  launch prompt was steered is reported as not independently verified instead of clean. Previously
  the attestation was written from memory and the launched prompt was recorded nowhere, so a
  steering clause could sit beside a clean attestation with nothing able to show the contradiction.
  (#534)
Stop the `install.sh` dry-run preview from crashing on a file it cannot open. The preview no
longer copies or diffs the `tmp/` scratch directory of either state directory (`.prflow/tmp/` and
the superseded `.devflow/tmp/`), so a scratch file, a dangling symlink, or a path too long to open
under it can no longer abort the upgrade preview. The preview also excludes the `vendor/` tree of
both state directories (`.prflow/vendor/` and the superseded `.devflow/vendor/`), matching what the
sandbox copy omits, so an un-migrated `.devflow/vendor` tree is no longer reported as a page of
false `DELETE` rows. When the diff step cannot open a file inside the
paths it compares, it now prints one `UNREADABLE <path> (<reason>)` row for it, keeps going, does
not count that path as a changed file, and — when at least one path could not be compared — prints
`devflow-install: N file(s) could not be compared (listed above as UNREADABLE).` after the usual
`devflow-install: N file(s) would change.` line, then reports `DRY RUN — nothing in this
repository was written.` and exits 0. A file the diff step cannot open is no longer mislabelled
`binary`.
- **Cloud implement runs now provision lint tools from a fresh, digest-checked download every run instead of trusting a cached binary.** The lint-tool directory is emptied at the start of each `/prflow:implement` run and is no longer backed by the Actions cache, so a file planted in that cache (or written into the directory earlier in the job) can no longer be executed or placed on PATH before the model starts. Each tool is either reused from a version-matching copy already on the runner's PATH or downloaded from its pinned archive and verified against the manifest's sha256. (#575)
- **Upgrades no longer silently apply a stale installer to a newer release.** When you re-run a
  saved `install.sh` against a different release, the installer now compares itself against that
  release's `install.sh` (ignoring line-ending differences) and, in apply mode, stops before
  writing anything — printing the command that downloads the matching installer and the
  `DEVFLOW_ALLOW_INSTALLER_DRIFT=1` escape hatch to install with the old one anyway. A dry run
  prints the same warning and still shows the plan. A `curl … | bash` run, or a release that ships
  no `install.sh`, prints a one-line note that the self-check was skipped and continues. Running
  the scaffolder — via the installer or `/prflow:init` — also warns when a stale installer copy
  (`install.sh`, `devflow-install.sh`, or `prflow-install.sh`) sits committed at your repo root.
  Prompt-extension `.md.example` files are now refreshed when their content is out of date instead
  of kept forever, and a thin upgrade over a repository that commits the plugin tree
  (`.prflow/vendor/prflow/`) now refreshes that committed tree so CI stops running the old plugin. (#576)
Fix the Phase 3.4 acceptance-criteria gate in a repository whose `.prflow/tmp/` is not
gitignored: `ac-verifier-artifacts.py prepare` now writes the attempt root's own `.gitignore`
(holding `*`) and captures the checkout-drift baseline only after it exists, so the helper's
own attempt files no longer read as checkout drift and falsely block the gate. Its untracked
offender list now comes from `git ls-files -o --exclude-standard`, so a stray file inside an
untracked directory is named individually rather than collapsed to the directory.

On a clean checkout `check` now prints one compact routing line of JSON and writes the full
bounded per-criterion dispositions record to `ac-dispositions.md` in the attempt directory,
instead of printing the whole reconciliation record, so the orchestrator carries far fewer
tokens through the gate.
- **Windows Git Bash telemetry-branch migration now migrates every record.** On Windows Git Bash (MSYS), an argument that joined a full ref name to a path (`refs/heads/<branch>:<path>`) was rewritten before git saw it, so the telemetry-branch migration copied zero records while still printing success, and PRFlow's telemetry record lookups treated persisted records as missing. Both the migration helper and the record lookups now resolve each ref to its commit ID before building the lookup argument, so the migration copies every readable record on Windows exactly as it does on Linux and macOS, and the "already persisted" checks find records that exist. The migration also now warns once for each listed record it cannot read and prints how many were unreadable — keeping the source branch for a manual retry — instead of reporting success when nothing could be read. You get this through the normal plugin update. (#578)
- **`/prflow:docs-verify` now takes `--lead docs|code` instead of `--search-space`.** The
  report-only mode drops the `--search-space <pathspec>` flag and adds `--lead docs|code`, which
  chooses whether the agent leads from the documentation or from the code while both search the
  whole repository. A run with no `--lead` keeps today's behaviour — documentation first, then
  code — and returns the documentation verdict. Running the command by hand with `--search-space`
  in the leading flags now reports it as an unrecognized flag and refuses the run. The report-only
  output is a compact set of fields kept under 1,000 words. (#588)

## September 14, 2026

- **The `/prflow:implement` terminal fences now run in a worktree-isolated Claude Code
  session.** The Phase 4.3 finalize call and the outcome-reaction call carried the bare word
  `complete` (`--status Complete`, `--outcome complete`), which such a session refuses as a
  shell builtin — silently dropping the 🎉 reaction on the triggering comment. Both fences
  now pass the value `=`-joined (`--status=Complete`, `--outcome=complete`), and
  `react-to-trigger.sh` accepts the `=`-joined spelling for every value flag (and, under
  `--report-failure`, exits non-zero on an unparseable argument so the fence's fallback note
  fires). A repository whose vendored plugin tree predates this change keeps losing the
  local-tier reaction until it re-runs the installer to re-vendor the updated fences. (#431)
- **The weekly retrospective now names its state branch and pull request after PRFlow.** The
  state branch is `prflow/learnings-<date>` and the state pull request's title and commit
  subjects read `chore(prflow): …` instead of the superseded DevFlow spelling. Both readers of
  the branch prefix — the state-PR guard and the pull-request classifier — accept the old
  `devflow/learnings-*` spelling as well until the superseded prefix is retired, so a repository
  whose plugin auto-updates while last week's `devflow/learnings-*` state pull request is still
  open is still reminded to merge it and does not re-process that week. Because a plugin can
  auto-update ahead of the pinned engine the scheduled workflow vendors, bump `prflow_version`
  (re-run `install.sh`) in the same upgrade as the plugin; a plugin updated well ahead of the
  pin can re-process one week once. (#496)
- **Isolate implementation finalization in a dedicated worker.** The main agent receives compact evidence before publishing the pull request, while documentation and final verification procedures stay in the worker. (#501)
- **Review verdicts and finding counts now read the reviewed commit from the review's own
  verdict marker, not the GitHub reviews-API `commit_id`.** GitHub moves a live review's
  `commit_id` to the current head when a branch is updated, so a pull request updated after
  review could have its review misread — the verdict deriver reported an unhelpful
  "keys disagree" state, and the experiment records showed a blank finding count. Both
  readers now select and join on the marker's `head=`, which records the tree that was
  actually reviewed, so an updated branch reports the real verdict and count.
  (#433)
- **Resumed runs keep unfinished review work.** When `/prflow:implement` resumes an
  interrupted run, intake now reconciles a historical completion claim against later
  corrective evidence and any interrupted review worker before describing review as done,
  carrying an outstanding review-evidence obligation forward through its existing handoff
  fields. A resumed run no longer reduces remaining work to PR-ready when review still
  owes work for the current candidate. (#521)
The documentation gate now recognizes a plain `- Documentation Needed —` bullet under `## Implementation Notes`, alongside the existing bold and `### Documentation Needed` heading forms. An issue that names its documentation deliverables without bold formatting is enforced during `/prflow:implement` instead of being silently treated as naming no documentation. The next same-level plain peer still closes the block, existing section, peer and fence boundaries and the documentation-path allowlist continue to govern extraction, and an out-of-allowlist path remains refused. (#506)
- **A `/prflow:review-and-fix` run no longer loses the fix loop's per-iteration
  continuation record to the review engine's own telemetry.** When efficiency telemetry
  was enabled, an engine invocation driven by the fix loop still ran the standalone
  review Phase 4.5 recipe and overwrote the loop-owned `iter-<N>.json` with a
  `source: "review"` object that dropped the loop's continuation fields, so an
  interrupted run could resume from a clobbered record. The engine's Phase 4.5 write is
  now bound to the caller's requested phase range: a review-and-fix entry requests Phases
  0 through 4.3 and passes `phase_range_max = 4.3` on its primary, shadow, and
  inline-fallback engine entries, so the engine skips Phase 4.5 and the loop stays the
  sole writer of its iteration record. Standalone `/prflow:review` passes no such bound
  and still produces its configured telemetry and trace when the flag is enabled. (#517)
- **A rate-limit or provider failure now resumes instead of terminalizing.** Earlier releases
  classified a failed `claude` step and, for a provider rate limit whose reset was still in the
  future, marked the workpad 💥 Failed rather than resuming — the run then waited for a human to
  re-trigger it. The stall backstop and the Spot recovery job now resume such a failure through
  the normal capped-resume path like any other interim stall, so `max_resume_attempts` alone bounds
  the retries. The `defer_to_runner_retry` opt-in continues to govern whether a failure is deferred
  to your runner's own retry instead of resumed. This reverses the September 12 provider
  rate-limit terminalize behavior.

## September 13, 2026

- Run implementation setup intake in a dedicated agent while preserving requirements, resume decisions, dependency checks and branch ordering. The orchestrator receives a compact evidence-backed handoff instead of the intake transcript. (#463)
- **The implement run's advisory changed-file lint now covers GitHub Actions workflow files and shipped `lib/test` shell scripts.** Editing a workflow file now runs `actionlint` over it in-session, and editing a `lib/test` shell script now runs ShellCheck over it, so a lint problem CI would reject surfaces during the run instead of after a separate fix-up commit. The lint toolchain gains a pinned, digest-verified `actionlint` that is provisioned automatically alongside ShellCheck and Ruff. (#375)
- **Implement runs stop relaunching a long test command just to read a different slice of its output.** When an implement run verifies acceptance criteria, it now runs each test command whose result it reads from a summary line once, keeps that run's full output, and reads every later slice it needs — an assertion line, a failure detail, the summary line — from the kept output instead of running the whole command again. A run against a large test file now spends a single launch where it previously spent several, so verification finishes sooner and costs less. ([#347](https://github.com/<owner>/<repo>/issues/347))
Move deterministic implement branch setup, draft pull-request opening, and deferred follow-up filing behind tested helper modes, reducing prompt overhead while preserving model-owned merge-conflict resolution. (#437)

## September 12, 2026

- **A provider rate-limit failure now terminalizes even with `defer_to_runner_retry` off.** The
  implement stall backstop's provider-failure classification is armed on every failed job, not
  only when `defer_to_runner_retry` is enabled. A run that fails on a provider rate limit whose
  reset is still in the future is now terminalized (💥 Failed, naming the reset time) instead of
  being auto-resumed back into the exhausted limit — so a repository running the default
  (`defer_to_runner_retry: false`) gains the protection it previously only had with the flag on.
  The flag continues to govern only whether an unclassified interim failure is deferred to a
  runner retry or resumed by the backstop. ([#401](https://github.com/The01Geek/prflow/issues/401))
- **The review engine now reads `prflow_review.agent_overrides` on native-Windows Python hosts.** On a Windows runner, `resolve-review-overrides.py` could not run `config-get.sh` (a `.sh` shebang is not directly executable on Windows), so every configured per-agent model/effort override was silently dropped and the review fell back to defaults. It now invokes `config-get.sh` under bash — the `DEVFLOW_BASH` interpreter when set, otherwise `bash` — with a forward-slash path, so overrides resolve on Windows exactly as they do on Linux and macOS. ([#365](https://github.com/radman-llc/prflow-dev/issues/365))
- **The `/prflow:implement` cleanup self-review now runs through a PRFlow-owned `code-reviewer` dispatch instead of the built-in `/simplify`.** Phase 3.2 reviews the branch diff for reuse, simplification, efficiency and altitude cleanups through one first-party review agent whose contract PRFlow ships and versions, applies the findings itself, and records a cleanup agent whose return is unusable as a visible workpad reflection rather than silently reading it as a clean pass. (#358)
- **Point the cloud implement job at its own runner.** The cloud `/prflow:implement` job now resolves a `DEVFLOW_IMPLEMENT_RUNNER` repository variable when you set it, falling back to `DEVFLOW_RUNNER` and then `ubuntu-latest`, so you can give implement runs a distinct runner without touching the runner the review and retrospective tiers use. Repositories that set neither variable, or only `DEVFLOW_RUNNER`, run exactly as before. You get this through the normal plugin update. (#402)
- **The pre-implementation audit now checks unmarked sweeping claims about your code.** When an issue asserts a falsifiable universal or completeness claim about existing code — "no X does Y", "every X is Z", or "a named surface carries none of a thing" — without a verification marker, `/prflow:implement`'s Phase 1.6 audit now reads the source the claim names and either confirms it, corrects the run's understanding when the source refutes it, or records it unverified when no concrete source is named — and when a refuted claim is prescribed word-for-word by an acceptance criterion, it stops the run over that conflict rather than shipping the false wording — so such a claim is adjudicated at planning time, or recorded unverified when it cannot be, rather than taken at face value. (#392)
- **The merge-gating review now rejects a pull request when a finding shows a decided acceptance criterion is unmet.** The shared review engine gains a threshold-independent, non-demotable unmet-decided-criterion carve-out: a Phase-3 review finding that establishes the shipped code does not satisfy a decided (resolved, non-post-merge) acceptance criterion of the linked issue drives REJECT at every threshold and regardless of the severity grade the agent assigned — reaching the same outcome a FAILed `issue_acceptance` checklist item already produces, and closing the agent-path leak that let such findings through as APPROVE-with-notes. A self-disclosed limitation in the shipped artifact that contradicts a decided criterion is recorded as that criterion being unmet, never credited as honest disclosure that clears the finding. When a linked issue's decided-criterion count exceeds the rank-1 `issue_acceptance` sub-cap, the criteria dropped from the checklist are surfaced as a coverage shortfall the verdict rejects on, so a criterion the rank-1 sub-cap drops is never silently lost from the merge gate while the sub-cap keeps its size discipline for the other checklist categories. A general quality or test-coverage finding that establishes no unmet decided criterion is unaffected and stays weighed against the configured threshold. (#389)
- **Issue drafting now rejects acceptance criteria a single implement run cannot satisfy.** When you draft an issue with `/prflow:spec`, drafting checks each acceptance criterion whose subject is an existing file, path, or subsystem against the current tree and refuses one whose target is already gone, while keeping a criterion about a target the change itself will create. ([#388](https://github.com/The01Geek/prflow/issues/388))
Add an opt-in cloud-CI verification mode for PRFlow's own cloud `/prflow:implement` runs (issue #403).

A new `prflow_implement.ci_verification.enabled` config key (default `false`) lets a cloud implement run offload a full-suite verification boundary to the repository's existing CI workflow instead of running the suite on its implementation host. `scripts/ci-verification-request.py` owns the request/wait/collect-evidence lifecycle — persisting a candidate-bound request before dispatch, polling the run inside one bounded foreground call, and building a versioned `cloud_ci_evidence` record from the run's shard tallies and job conclusions — and `scripts/check-completion-evidence.py` validates that record (exact shard population, zero failed/skipped/exit tallies, required-check coverage, and a clean current candidate) before `scripts/workpad.py` accepts it as completion evidence in its own marker family. `ci.yml` gains optional `workflow_dispatch` `request_id`/`expected_head_sha` inputs and a worker-checkout validation step. The mode is fail-closed and default-OFF: an incomplete deployment refuses CI mode with an actionable explanation, and every consumer, local, and standalone review/fix path keeps its existing verification semantics unchanged.

## September 11, 2026

- **When a configured label is turned off, the run's log now names the config key instead of blaming a caller mistake.** With a label channel disabled by a present-but-empty `docs.labels`/`deferred.labels`, `apply-labels.sh` in config mode now warns that the named config key resolved to no labels and that no substitute label is owed, rather than reporting a caller-passed empty list. A maintainer reading a run's log or a filed issue sees that their off-switch was honored, not a phantom helper defect. The positional call form keeps its existing wording. (#339)
Make the `/prflow:implement` Phase 3.4 acceptance-criteria gate refuse a `satisfied`
verdict the evidence verifier reached without running anything. An evidence-side
`satisfied` whose `command-run` disposition is `no` is now reconciled to `unestablished`
(reason `unexecuted`) before the two verifier votes are compared, so a run blocks and
says so rather than shipping a review-ready pull request on evidence nobody observed. A
refused or silent Phase 1.6 audit-record validator is now recorded on the workpad as
unvalidated instead of proceeding silently.
- **Cancelled and signal-terminated cloud runs now preserve their execution transcript.**
  When transcript publication is enabled and a run's Claude step is cancelled or interrupted
  before the action writes its execution file, the workflow now scrubs and uploads the CLI's
  own session transcript for that run instead of losing it, under the usual artifact name and
  retention. A cancelled attempt's artifact holds the CLI's session files, which carry more
  than the action's message stream — treat it as sensitive. (#342)
- **Workpad comments now stay their real size on Windows hosts.** `workpad.py` normalizes a comment body to LF: a run of one or more carriage returns before a newline is collapsed to that newline when it reads a body from GitHub or from a body file, and it writes bodies as bytes, so a native-Windows Python's text-mode newline translation can no longer add a carriage return on each write. A workpad already inflated by earlier Windows runs shrinks back to its clean form on its next update, with no separate compaction step. The 65,536-byte comment-size guard is unchanged, now measured on the canonical body — so a body that was over the limit only because of accumulated carriage returns is written rather than refused. Consumers on other hosts get workpads that stop carrying mixed line endings after a web-UI edit. `workpad.py patch` no longer echoes the returned body to stdout on success (matching `update`), and `workpad.py prior-status` now writes one stderr line on its exit-1 arm so a silent exit is never mistaken for a hang. (#349)
- **Old telemetry history is migrated onto the current telemetry branch automatically after a rename upgrade.** A new bundled helper (`scripts/migrate-telemetry-branch.sh`) moves the cost-and-effectiveness records from a pre-rename `devflow-telemetry` branch onto the branch PRFlow now writes to, restaging each record from its old `.devflow/logs/` path to the current `.prflow/logs/` path and handing the staging root to the writer's own persist function. It runs from `/prflow:init` and `install.sh --apply`, and as a backstop before the first append on the writer's next authorized persist, so a consumer whose plugin auto-updated ahead of init is healed on their next writable run. The retrospective's stranded-record warning now points the maintainer at `/prflow:init` instead of a manual branch-rename push.
Use the configured base branch throughout an implement run, and resume on the workpad's recorded branch.

The branch-setup agent now looks up the configured `base_branch` on every arm (not only when it reuses or creates a branch), prints it, uses it in every base-consuming command and in the `preflight.py branch-state` state file, and returns it as a `base:` line in its record; the orchestrator takes the base from that record wherever a later Phase 1–4 instruction needs it. A resume that adopts no open pull request now checks out and continues the feature branch its workpad recorded — when the recorded name matches the issue's branch shape, the branch exists on the remote, and it never had a pull request — instead of forking a date-suffixed duplicate. `workpad.py`'s `skipped-intentional` review-coverage size check now measures against the configured base (`origin/main` when unset) rather than the repository's default branch, so it records a real verdict on cloud checkouts and for consumers whose base differs from the default branch.
- **Cloud implement recovery no longer defers a provider/API failure to a runner retry that will never happen.** With `prflow_implement.stall_backstop.defer_to_runner_retry` enabled, PRFlow previously deferred *every* failed `claude` step to the runner's retry — even a provider 429 that RunsOn's `retry=when-interrupted` never re-runs — leaving the issue stuck on an interim workpad with no PR. The stall backstop and the Spot recovery job now positively classify the failure from the execution diagnostics (`terminal_reason=api_error` with a numeric `api_error_status`) and, on that classification, converge the run through PRFlow's own bounded path — a capped `/prflow:implement` resume, or a terminal 💥 Failed disposition naming the reset time for a rate-limit rejection whose reset is still in the future — instead of deferring. An unclassifiable or unavailable failure (including an unobservable Spot reclaim) still defers, so the two recovery mechanisms never drive one issue at once. (#362)
- **The weekly retrospective no longer loses its credentials partway through a long run.** `devflow-retrospective.yml` was the only agent-running workflow without the long-run credential refresher, but a weekly run routinely outlives the GitHub App installation token's 60-minute lifetime and does all of its writing at the very end — so the state-PR push and every issue-filing call failed with `401 Bad credentials` while the run still reported success, discarding the whole week's analysis. The `retrospective` job now starts the detached refresher and the fresh-`gh` wrapper after checkout and retires them in an `always()` step, exactly as the implement and command jobs do. Gated on the same `vars.DEVFLOW_APP_ID != ''` condition as the existing token mint, so a repository with no App configured is unaffected. (#374)
- **Cloud runs no longer silently deny the plugin's own helper scripts when your installed workflow predates the plugin.** The `Resolve allowed-tools` step in both cloud workflows now unions every plugin-helper grant the vendored `capability-profiles.json` names into the allowlist your run executes under, so a workflow whose baked list lags a newer plugin (a hand-edited or un-refreshed `.github/workflows/` copy) stops dropping helper-produced work without a trace. When a plugin helper is still refused, the run records the denial and reports the missing artifact instead of fabricating a result. ([#352](https://github.com/The01Geek/prflow/issues/352))

## September 10, 2026

- Add the opt-in `prflow_implement.stall_backstop.defer_to_runner_retry` key (default `false`) for a runner that retries a failed agent job on its own, such as RunsOn `retry=when-interrupted` on EC2 Spot (issue #305). When true, an interim workpad after a `failure` agent step is no longer auto-resumed by PRFlow: the stall backstop and the Spot recovery job leave the workpad in progress, post one short informational comment, and let the runner's retry resume the run, so two recovery mechanisms never drive one issue at once. A `cancelled` job keeps its existing recovery path, since no runner retries a cancel. Without the key every existing behavior is unchanged.
- **The weekly retrospective workflow now ships in the public release.** The installer already
  copied `devflow-retrospective.yml` when present, but the public-release package omitted the
  file, so a repository installed from the public release silently received only two of the three
  consumer workflows. The release package now includes it, so a public-release install gets the
  retrospective workflow the installer promises. (#318)
Add self-install guards so PRFlow's own setup entry points refuse to mutate the engine repository. `install.sh` now refuses an apply request (`--apply` or `DEVFLOW_APPLY=1`, even when a later `--dry-run` wins mode resolution) when the target repo is PRFlow's own checkout, and `/prflow:init` refuses the whole run at the top in the same case — both printing a self-install breadcrumb, writing nothing, and both lifted by setting `DEVFLOW_ALLOW_SELF_INSTALL` to a non-empty value. `scripts/provision-local-settings.sh` now skips writing its `extraKnownMarketplaces` entry (still enabling the plugin, printing a conflict breadcrumb, exiting 0) when the user-scope settings file already registers the marketplace against a different source, so a project-scope write can no longer silently shadow-downgrade it.
- **Long cloud runs on Windows self-hosted runners no longer die with `Bad credentials (HTTP 401)`.** The background credential refresher now locates the git-push config file by reading git's NUL-terminated origin output, so a temporary-directory path containing backslashes (which git otherwise prints quoted) is found and refreshed, and it writes the git-push credential and the `gh` token file as two independent surfaces so a failure of one no longer starves the other. Runs longer than an hour stay authenticated. (#332)
- **Verified-premise checks accept quotations that contain inline code.** The verified-premise checker that runs during issue drafting and during an implementing run's pre-checks treats a backtick span inside a quoted sentence as part of that sentence, so a true premise whose quotation contains a backticked word or path grades as holding and searches the whole quoted sentence in the cited file. Drafters keep the full sentence they quoted, code term included. You get this through the normal plugin update. (#326)

## September 9, 2026

- **The `docs.labels` off-switch now works in cloud implement runs.** Setting `docs.labels` to an empty string suppresses the "Documented" pull-request label on your pull requests; previously a cloud run could still attach it when the config presence probe did not answer definitively. Consumers who have never set `docs.labels` are unaffected and keep the default "Documented" label. (#286)
- **The installed plugin no longer ships PRFlow's own Claude Code hooks or its maintainer-only tooling.** The Stop-hook guard, run-marker writer, Stop-hook probe and PreToolUse guard (with their render and probe helpers) are deleted, and the artifact generators and workflow-flight-recorder analysis tools move out of the shipped slice, so a consumer install carries only files that do something in its own repository. The branch-checkpoint helper now registers git merge drivers from a consumer-generic `prflow_implement.merge_drivers` config map instead of a hardcoded development-tree path. A consumer that had hand-wired the removed stop-guard hook script as a Stop hook should remove that hook entry, which otherwise logs `No such file` at every Stop.
- **`/prflow:spec` now flags over-engineering in drafts.** The audit that shapes a new spec catches
  mechanism, acceptance criteria, or dependencies specified beyond what the stated problem needs —
  including a safeguard against a case an existing check already covers — so a spec ships the smallest
  mechanism that solves the problem instead of accreting unnecessary machinery, with no per-run
  hand-prompting. ([#312](https://github.com/The01Geek/prflow/issues/312))

## September 8, 2026

- **The `PRFlow:Implementing` label now reaches a pull request the moment its implement run links it.** When the status-label mirror is enabled, `scripts/workpad.py update` reconciles the managed status label onto the pull request as soon as the run records the PR link — taking the PR number from the link, not from a lookup GitHub can leave lagging just after creation — so a mid-run pull request is distinguishable from an abandoned one directly in the pull-request list instead of only once the run reaches its next status write. (#252)
Review runs now update the PR progress comment at every phase boundary — the checklist row and the live findings change as Phase 1, Phase 2 and each Phase 3 agent complete, instead of the comment sitting unchanged from run start until the verdict. A new `workpad.py progress` subcommand ticks one `## Blueprint` row and/or appends to `## Findings (live)` by comment id in a single PATCH, and the review's Phase 1, Phase 2 and Phase 3 files each own their own boundary update.
- **Route the implement skill's two Phase 3 commit fences through the durability-checkpoint helper instead of a whole-tree `git add -A`.** The `/simplify` commit (Phase 3.2) and the review-and-fix residual flush (Phase 3.3) previously staged the entire working tree except `.prflow/tmp/`, committing any unrelated leftover file into the pull request and contradicting the explicit-path staging rule the rest of the skill enforces. Each step now captures a `git status --porcelain` listing before and after the step, hands only the paths whose status row changed to `scripts/phase2-durability-checkpoint.sh` (which stages exactly those, commits, pushes, and confirms the push landed), and skips the commit when nothing changed — so a pre-existing unrelated file stays uncommitted for the Phase 4.3 clean-tree check. (#256)
- **Recover `/prflow:implement` runs interrupted by an EC2 Spot reclaim.** With
  `prflow_implement.spot_interruption_watcher.enabled` set to `true` on a supported Linux
  EC2 Spot runner, a watcher detects the interruption while the runner is still alive,
  records a durable reclaim marker, and ends the run cleanly so its cleanup can finish. A
  downstream recovery job then reconciles the outcome: a genuine reclaim is resumed once
  (subject to the existing attempt cap), while an intentional cancellation stays final and
  is never resumed. The watcher is opt-in and off by default. ([#261](https://github.com/The01Geek/prflow/issues/261))
- **Each `/prflow:implement` run now keeps its temporary files in a per-issue folder that clears itself when the run succeeds.** A run working on an issue writes its scratch files under `.prflow/tmp/implement/<issue>/`, clears any folder a killed earlier run on the same issue left behind, sweeps the flat leftovers older versions wrote, and removes its own folder on a successful finish. Your working copy no longer fills up with untraceable scratch leftovers, and a later run on a different issue can no longer inherit or overwrite an earlier run's fixed-name scratch state. (#240)

## September 7, 2026

- **The shipped review engine and retrospective no longer apply rules written for PRFlow's own source tree.** The `engine_self_modifying` review-engine flag — which forced the full checklist, an early shadow pass, and disabled the documentation-only carve-out whenever a changed path started with `skills/`, `agents/` or `lib/`, was a prompt extension under the state directory, or was named `CLAUDE.md` — is removed from the shipped plugin, so a consumer's pull request now gets the review profile its diff size and file types earn. `scripts/workpad.py` grades a `skipped-intentional` review-coverage claim against the line ceiling, file ceiling and config-only extension set in every repository and reads no `.claude-plugin/plugin.json`, so the offline evidence gate and its verdict-marker consumer agree with the shipped prose everywhere. The retrospective and issue-drafting steelman no longer name PRFlow-owned paths as intervention targets: a plugin-caused pattern is recorded for upstream forwarding, and the steelman resolves the running plugin's own root. PRFlow's own repository keeps this behavior through its repo-local review, retrospective and retrospective-audit prompt extensions. (#229)
Vendor the plugin through the fetch branch with a configurable repository and a job credential. The vendor step's `self` branch, which copied the checkout, is removed: an already-committed vendored tree is used as-is, and any other checkout is fetched. A new optional `prflow_repo` config key (`owner/name`, default empty meaning the public repository) names the repository the fetch branch clones, and the `vendor-plugin` action gains a `token` input that supplies a one-shot git credential helper so a fork or private repository can be fetched; a consumer supplies the credential through the `PRFLOW_REPO_TOKEN` repository secret. No workflow or shipped helper falls back to the checkout's `scripts/` directory any more; a missing vendored helper fails the job with the existing incomplete-vendor error, and a desk lint keeps such a fallback line from reappearing. A consumer on the default configuration is unchanged.
- **Renamed the issue-drafting command to `/prflow:spec`.** The command that turns a rough
  user story, bug report, or idea into a spec'd-out GitHub issue is now `/prflow:spec` — one
  canonical name that the code, the tests, the docs, and the run-measurement tools all share.
  `/prflow:create-issue` and `/devflow:create-issue` keep working unchanged as permanent
  aliases. The old plural `/prflow:specs` spelling no longer resolves as a command; a run
  started with it gets the runner's unknown-command response, so retype `/prflow:spec`. A
  consumer who customized the command through `.prflow/skill-extensions/create-issue.md` keeps
  that customization applied (it is read through under the old filename) and is told by a
  breadcrumb to run `/prflow:init` to rename the file. A consumer who set the
  `create_issue.investigation_record_enabled` config key is told the key moved, but the setting
  is **not** read through: until `/prflow:init` migrates it the key resolves as unset (the
  investigation record is published), so `/prflow:init` is the remedy the breadcrumb names. (#216)
- **Shipped skills and agents no longer reference PRFlow-only files, commands, or conventions.** Every `skills/` and `agents/` body now names only files, commands, and conventions a consumer repository actually has: the docs skills resolve the configured base branch instead of a hardcoded `origin/main`, the release-notes reconciliation reads the project's own release convention, the review prohibitions cover the project's own test runners, and the weekly retrospective's suite-profiling steps moved into a repo-local prompt extension. A consumer no longer sees a step silently skip, read a file that is not there, or apply a rule written for PRFlow's own repository. (#230)
- **A `{0}` in `DEVFLOW_RUNNER` or `DEVFLOW_LIGHT_RUNNER` is now replaced with the workflow run id.** Every shipped workflow's bare-label `runs-on` arm goes through `format(vars.<NAME>, github.run_id)`, so a RunsOn-style label (`runs-on={0}/cpu=8/...`) namespaces its runner per run instead of arriving with a literal `{0}`. A placeholder-free value passes through unchanged; a literal `{` in the value must be written `{{`. (#240 probe groundwork)
- **Multi-line workpad Progress notes now render as indented continuation lines.** A note passed with embedded line breaks renders as one Progress bullet whose non-blank continuation lines are indented under it (blank lines dropped), instead of landing verbatim inside the nested list where blank and column-0 lines broke the list and spent the comment's size budget. The failed-write replay recognizes a note by its rendered form. (#246)

## September 6, 2026

- **`/prflow:init` now turns on Claude Code's task-tracking tools for your future sessions.** Since Claude Code v2.1.233 the task tools (`TaskCreate`, `TaskGet`, `TaskUpdate`, `TaskList`, `TodoWrite`) are off by default on newer models unless you opt in, which silently degraded PRFlow's task-tracking skills to a non-persisted checklist. Init now deep-merges `env.CLAUDE_CODE_ENABLE_TODO_TOOLS = "1"` into your user-scope `~/.claude/settings.json` when the opt-in is set in neither the environment nor that file, preserving every value you already set, and prints a notice that the setting takes effect only in a newly launched session. A pre-existing value or an environment override is left untouched. (#207)
- **Clearer review status-label names.** When the config-gated review status-label mirror (`review_status_labels.enabled`, off by default) is on, a completed review whose verdict is reject is now labelled `PRFlow:ReviewRejected`, and a review that did not complete (no verdict, dead run, evidence-gate failure, or finalizer catch) is now labelled `PRFlow:ReviewStuck`. `PRFlow:Reviewing` and `PRFlow:Approved` are unchanged, as are all four labels' colors. The two states remain distinct — this renames the labels for readability, and does not merge them. Any older-named label already applied to an issue or PR is left in place and can be deleted manually. (#214)
- **`/prflow:review-and-fix` now finds the review engine that ships with the running
  plugin.** On a thin install the fix loop's engine lookup previously checked only three
  repository-root-anchored directories — none of which exists on a consumer's own machine —
  and halted before reviewing anything, naming a `/prflow:init` remedy that creates no such
  directory. The lookup now appends one last candidate, the running plugin's own `review`
  sibling of the loop's skill directory, so a thin-install consumer regains the local fix
  loop and the local `/prflow:implement` lifecycle. The three repository-anchored candidates
  keep their order and win when present, so committed-vendor consumers, cloud runs, and this
  repository's own runs are unchanged; a stale leftover vendored tree is now reported with a
  version-mismatch note instead of being run silently. (#213)
- **Code review now flags references a change breaks outside the PR diff.** When a diff removes or
  renames a distinctive string literal or identifier, the `code-reviewer` agent searches the whole
  checked-out repository for surviving references to the old value and reports the ones that live
  outside the diff and stay keyed on it, so a rename that silently breaks an unmodified file is
  caught at review time instead of shipping green. (#212)
- **Acceptance-criteria verifier reports now reach reconciliation directly, guarded against
  unrelated checkout changes.** During an implement run's acceptance-criteria gate, the two
  verifiers now write their JSON reports straight to per-attempt destinations instead of having
  the orchestrator copy them, so criterion statuses, evidence and reasons can no longer be lost
  in transcription. A new checkout-fingerprint guard compares the checkout before and after the
  verifiers run and blocks the gate if anything unrelated changed, naming the drifted fields and
  offending paths so the change can be investigated. (#219)
- **The final documentation pass now refuses Documentation Needed deliverables outside documentation locations.** `/prflow:implement`'s documentation step accepts a deliverable named in an issue's **Documentation Needed** block only when its path sits inside a documentation location — the configured internal or external documentation root, the release-notes file, the changelog file, or `README.md`. A deliverable naming any other path is skipped and recorded, and the run finishes normally, so the pass can no longer commit an unreviewed edit to a non-documentation file it was handed as a deliverable after code review has finished. `/prflow:create-issue` also stops writing such paths into that block. (#222)

## September 5, 2026

Rename the consumer-facing per-skill extension directory from `.prflow/prompt-extensions/` to `.prflow/skill-extensions/`. `/prflow:init` migrates an existing `.prflow/prompt-extensions/` directory in place (renaming nothing when both directories already exist and reporting a conflict to reconcile by hand), and every reader resolves `.prflow/skill-extensions/` first and falls back to a present `.prflow/prompt-extensions/` with a migrate breadcrumb during the transition, so an un-migrated consumer keeps working. The `DEVFLOW_PROMPT_EXTENSION_ROOT` environment variable and the helper filenames are unchanged.
- **Outcome reactions find the latest implement trigger on long-running issues.** PRFlow checks every issue-comment page before choosing the triggering comment, so completion and blocked reactions reach the current request even after an issue has accumulated more than 100 comments. ([#191](https://github.com/The01Geek/prflow/issues/191))
- **Harden the `/prflow:create-issue` (`/prflow:specs`) run helpers.** The run's slug is now
  keyed on a run-directory registry (`run-meta.json`) instead of a session id, so a continued
  session recovers its own run, cleanup no longer leaves orphaned `issue-run-slug.<session-id>`
  pointer files behind, and concurrent runs and linked worktrees are told apart by topic and
  start time. A new `scripts/check-draft-provenance.py` checker, run in the draft bootstrap
  beside the existing two, catches a provenance signature that landed mid-body before the draft
  is presented. (#198)
- **An explicit empty `docs.labels` / `deferred.labels` value now applies no labels instead of falling back to the default.** Previously a present-but-empty value (`""`) was coerced to the caller's fallback, so `/prflow:implement` still labelled its PRs `Documented` (and its deferred follow-up issues `PRFlow,Deferred`) even when the config set the key to `""` to turn labels off; the only working off-switch was the non-obvious `","`. `scripts/apply-labels.sh` config mode now gates the fallback on a new opt-in `config-get.sh --presence` probe, so a key that is present-but-empty means "apply no labels" while the default applies only when the key is genuinely absent (a JSON `null` counts as absent). A whitespace- or separators-only value still applies none, and a non-empty value still applies exactly those labels — both unchanged. The shared `config-get.sh` resolver's default read is untouched for every other key. (#208)
- **`/prflow:specs` now applies the same customization file as `/prflow:create-issue`, and create-issue's helper fences run in a worktree-isolated session.** The create-issue pipeline reads one prompt-extension file, `.prflow/skill-extensions/create-issue.md`, on both command names; the `/prflow:specs` alias no longer loads a separate `specs.md`, and `/prflow:init` no longer scaffolds a `specs.md.example` (removing a stale one on its next run). When a stray `specs.md` sits beside `create-issue.md`, the loader prints one line naming it and pointing at `create-issue.md`, and the create-issue run surfaces that line to you rather than silently ignoring the file. The create-issue skill's per-finding audit ledger now reaches the state owner from a file rather than a stdin heredoc, and the create-issue command fences no longer use the shell shapes a worktree-isolated Claude Code session refuses. (#200)

## September 4, 2026

Fix the implement skill's end-of-run reaction so it posts the correct outcome on both tiers.

`scripts/react-to-trigger.sh` now accepts `--outcome complete|blocked` with `--issue`, choosing the reaction itself (🎉 `hooray` for a completed run, 👎 `-1` for a blocked one) and resolving the triggering comment itself — from the event file, else the newest non-workpad implement-trigger comment. The implement skill's outcome-reaction fence becomes a single leading-token call with a prefix-removed/anchor fallback ladder, so the correct reaction now posts on both the local and cloud tiers instead of re-posting the pickup 🚀.
- **Closed fail-open and security-shaped defects in the implement helper scripts.** The
  checkout-fingerprint helper now hashes untracked files without writing them to the git
  object store, so a verification step no longer copies an untracked secret into
  `.git/objects`. The acceptance-criteria parser tags only unambiguous live-environment
  phrases, so a code-verifiable criterion is no longer dropped from the merge gate on a
  loose phrase match. The verification flight honours its `DEVFLOW_FLIGHT_NOW` clock
  override only behind a companion test-clock gate and marks any handle written under it,
  so the override is inert in production. A `dispatched-but-lost` review-coverage
  disposition is now admitted only over a measured roster with a recorded dispatched
  reviewer, so a run cannot finalize on a lost-dispatch claim with no dispatch on record. (#181)
- **Trimmed every shipped agent `description` to a short trigger line and dropped the unused web
  tools from the discovery agents.** Each `agents/*.md` description is now a single ≤120-byte
  trigger statement, so every enabled session carries several kilobytes less system-prompt text
  on every turn; the worked scenarios and secondary triggers moved into each agent's body, which
  loads only when the agent runs. The `code-explorer` and `code-architect` discovery agents no
  longer grant `WebFetch` or `WebSearch` — an autonomous implement run's discovery agents cannot
  reach the web. A new byte ceiling in the frontmatter validator keeps the descriptions from
  growing back. (#179)
- **`/prflow:implement` Phase 1 now stops with a Blocked status on a failed push or uncommitted tracked changes instead of continuing.** A failed branch push is reported as a Blocked run naming the cause, rather than silently leaving an unpushed branch; uncommitted tracked changes stop the run for you to commit or stash, rather than gaining a stray commit on the base branch; and the setup file's agent-file fallbacks now resolve in a consumer checkout. (#178)
Make the implement Phase 2 sweep prose decidable and consumer-safe (issue #180). Comment
relocation now has one owner: a non-preventing comment is deleted or shortened in Phase 2, and
an explanation worth keeping is recorded through a `relocate to docs:` workpad note that Phase 4.1
hands to the docs pass. The §2.5 workflow-edit guard keys on the durability helper's observable
stderr token rather than a run-facts field that is never produced. The §2.2 complexity assessment
routes by one rule (Path B when any Complex bullet holds or the touched-file count exceeds five;
otherwise Path A). The test-first gate is runner-neutral — it confirms the runner collected and
reported the new test and extracts a branch-selecting snippet into a unit the repository's test
runner can drive, with a no-runner arm for repositories that have none. PRFlow-internal names are
removed from the shipped Phase 2 bodies.
- **`/prflow:implement`'s review phase now stays predictable when a tool is missing or refused, and never commits its own run scratch.** The pull request an implement run opens no longer carries PRFlow's working files, even in a repository whose ignore rules predate them. When the `/simplify` step is unavailable on your runner, the workpad records it as unavailable instead of an empty result that reads like a clean pass. When the review-and-fix step cannot be loaded, the run stops as Blocked and names the refusal, instead of attempting an unbounded review by hand. The review phase's guidance now reads correctly in any repository, not only PRFlow's own. (#182)

## September 3, 2026

Key the create-issue run-slug pointer by session. `scripts/cleanup-create-issue-run.sh` now
owns the pointer through `--record-slug` and `--resolve-slug` modes and writes it to
`.prflow/tmp/create-issue/issue-run-slug.<session-id>`, so concurrent `/prflow:create-issue`
runs in one checkout no longer overwrite each other's slug and no run adopts another session's
identity after context compaction. On a harness that exposes no session identity the helper
reports that plainly and the run takes the existing title-derived fallback.
- **Trust a GitHub App as a configured bot login everywhere by normalizing logins through one shared rule (issue #157).** A new `lib/login_normalize.py` trims whitespace, strips a leading `app/` and a trailing `[bot]`, and lowercases both a login and each configured comparand before comparing, so an `allowed_bots` (or `watched_authors`) entry written as the bare slug, `<slug>[bot]`, `app/<slug>`, or in mixed case all match the same App. The deferral matcher, the lint-adjudication allowlist arm, the workflow authorization gate, the CI review trigger, and the retrospective scanner now decide login trust and identity through this rule instead of their own strip-and-compare, so a GitHub App author's Scope-Acknowledged deferrals are honored rather than rejected as `untrusted-filer`. The `allowed_bots` and `watched_authors` config-schema descriptions now state the accepted entry forms. (#157)
- **Dead cloud runs now name why they died, and their comments are shorter.** When a cloud `/prflow:implement` or `/prflow:review` run ends in error, the run log, the step-summary diagnostics block, and the comment it posts now carry the engine's failure cause — the result subtype and terminal reason, an API-retry error, or a rejected rate-limit event — so a usage-limit rejection reads differently from a genuine stall without downloading the transcript. Each standalone failure comment is trimmed to a headline, the cause, and the run link (plus the trigger line on the auto-resume arms), and the review stall backstop headline now reads PRFlow. ([#158](https://github.com/The01Geek/prflow/issues/158))
- **Renamed the `/prflow:receiving-code-review` skill to `/prflow:fix`.** The skill that
  checks review feedback before applying it is now invoked as `/prflow:fix`; its description
  still contains the text `receiving-code-review` so a search by the old name still finds it.
  The old command name stops resolving in this release — there is no forwarding shim. A
  consumer who customized the extension keeps it working: the extension loader, asked for
  `fix`, reads a still-present `.prflow/prompt-extensions/receiving-code-review.md` when
  `fix.md` is absent and prints a breadcrumb telling you to rename the file, and `/prflow:init`
  (and `install.sh`) rename it to `fix.md` on an existing repository. Rolling the plugin back
  to a pre-rename version after init has renamed the file leaves the old skill reading an empty
  extension until you rename the file back. This release does not migrate consumer-side
  references to the old command that live outside the plugin — permission rules, hooks,
  scheduled commands, and any text in your own `CLAUDE.md` that names `/prflow:receiving-code-review`
  should be updated to `/prflow:fix` by hand. (#152)

## September 2, 2026

- **Warn at install time when a preserved guarded workflow's sidecar merge would strand the cloud implement gate.** When `install.sh --apply` preserves a locally-modified guarded artifact (the lint manifest, the `setup-project-env` action, or `.github/workflows/devflow-implement.yml`), the `PRESERVED` line now states that `.prflow/install-state.json` is bound to the kept bytes and that the installer must be re-run in apply mode after the sidecar is merged or adopted, and the apply prints one summary line naming every such sidecar and the exact re-run command. The cloud provisioning readiness refusal for a guarded `digest-mismatch` now names a merged or adopted `.prflow-new` sidecar as a cause, and the install and cloud-run docs carry the re-run-in-apply-mode step. (#92)
Reconcile the create-issue fresh-context audit's criterion-shape dimension with the issue template, and bring out-of-scope and Quiet Killer observations into the audit ledger.

The audit prompt's criterion-shape dimension no longer flags a qualifier that a drafter correctly wrote inside a criterion: a statement narrowing, bounding, quantifying, defining a term for, or naming a verification route for a criterion is never a finding when it repeats across criteria or when an identical copy also sits in the grounding block, and the dimension's flag toward the block is limited to pure framing whose deletion changes no criterion's truth value. A block statement that disagrees with the inline qualifier stays a finding. The authoring-discipline RESTATEMENT shape excludes those inline copies, the issue template is the single canonical statement of the rule, and the steelman reference points at it rather than restating it.

The auditor now reports every out-of-scope observation on a targeted round, and a qualifying Quiet Killer on any round, as an ordinary numbered finding under the per-finding bar; an out-of-scope finding carries an `out-of-scope` tag and changes no per-claim verdict, and `Quiet Killer: none` stays a non-finding. The per-round `--findings-count` tally is now defined as the number of findings the auditor returned, checked at adjudication to equal must-revise plus advisory plus invalid: `record-return` refuses an accepted return that omits the tally (`findings-count-required`), `record-adjudication` refuses a round whose recorded tally disagrees with the adjudicated class total (`findings-count-mismatch`) and emits a `tally-unrecorded` breadcrumb for a round returned before this change, and the audit summary renders `findings_count` as `none` when any completed round carries no recorded tally rather than presenting a partial sum as the total.
- **Finished the DevFlow→PRFlow rename for the remaining visible names.** The implement
  workpad's reflection section now reads `## PRFlow Reflections` and shows its bullets
  directly, with no collapsed `<details>` control. The shipped command workflows now display
  as `PRFlow` and `PRFlow (implement)` in the Actions tab (the reusable runner workflow's
  display name is likewise renamed to `PRFlow Runner (reusable)`, though it is retained rather
  than shipped). The cloud review check-run's rename to `PRFlow Review` is reader-side: the
  in-tree readers and self-exclusion filters now accept both `PRFlow Review` and the historical
  `Devflow Review`, so telemetry on older pull requests keeps working — the workflow that would
  post the check remains withheld from this release, so no in-tree job emits it today. Records
  written before the rename keep working: the workpad reader and updater accept both the new
  heading and the old `## Devflow Reflection`. Environment variables, workflow filenames, and
  command aliases are unchanged. (#112)
The context-cost instruments now read the cloud execution-transcript shape, and each cloud
implement run records its peak main-thread context and per-phase file-read counts on its
telemetry record. A single shared transcript reader in `scripts/context_eval_shared.py`
strips the scrubbed artifact's leading `# DEVFLOW SCRUB CAVEAT` line and parses a whole-file
JSON array, a whole-file object, or JSONL; the corpus collector now accepts `.json` files
alongside `.jsonl` and tallies every other suffix. `scripts/extract-execution-cost.py` adds
two `harness_cost` fields, `peak_main_thread_context` and `phase_file_reads`, which flow
through the telemetry record into `scripts/implement-run-report.py --retro`, so the weekly
retrospective's "Implement runtime trends" section reports the trailing-window median and
maximum peak context and total phase-file reads. Records written before this change lack the
two fields and are excluded from those aggregates (recorded as unestablished, never zero).
These are instrument outputs only — no threshold, ceiling, regression rule or gate reads them.
- **New opt-in weekly scheduled retrospective workflow.** A new shipped workflow,
  `devflow-retrospective.yml`, runs `/prflow:retrospective-weekly` automatically every
  Sunday at 05:23 UTC and on manual dispatch from the Actions tab, so the
  self-improvement loop keeps running without anyone remembering to start it. It is
  gated by a new per-workflow config key, `workflows["prflow-retrospective"]`, read from
  the default branch's `.prflow/config.json`: only the JSON boolean `true` enables it, so
  repositories are opted out by default and pay no Actions or Claude cost until they opt
  in. When an unmerged `devflow/learnings-*` state PR is still open, the run skips the
  retrospective and files a single reminder issue to merge it first.
  (#93)
- **`/prflow:init` now installs the cloud-tier workflows, not just the config.** After scaffolding `.prflow/config.json`, init runs the installer to place the `.github/workflows/` files whenever the config enables a workflow tier, so a repository whose config says the cloud tier is on no longer ends up with no workflows on disk. When no tier is enabled it asks first, and whenever it installs it points you at the `.github/` diff to review before committing. (#124)
Finish the DevFlow→PRFlow brand rename by sweeping the remaining "DevFlow" brand prose in comments, docs, skill bodies, prompt extensions, and test files to "PRFlow", draining `lib/test/brand-devflow-buckets.json`'s `pending_sweep_baseline` to empty. Occurrences that must stay "DevFlow" — the superseded provenance-label value that selectors still match, and the brand-sweep lint's own fixtures — are recorded in their frozen buckets.
Remove every `$?` from the shipped bash fences under `skills/` and `agents/` — the cloud permission matcher refuses any command carrying a parameter expansion, so a status trailer such as `; echo "seed-rc=$?"` was silently refused and burned a round trip. Each status-trailer site now ends in a constant trailer `; echo "<name>-done"` (a measured-permitted `;`-joined sequence with no expansion) and its prose routes on the tool result; each `VAR=$?` capture becomes the bare command routed on its own output, or an `if`/`then`/`else` block where control flow needs it. The worktree-fence lint (`lib/test/lint-worktree-fence-shapes.py`) now applies its `$?` rule to every tracked `skills/`/`agents/` file, enumerated from `git ls-files` with no baseline of tolerated hits, so a reintroduced `$?` fence turns the suite red. The cloud grounding block gains a refused-shape row naming the argument-position `simple_expansion` refusal and a `2>` stderr-redirect row, and no longer attributes `simple_expansion` to a leading assignment.
- **Route the light cloud jobs onto a cheaper runner with the new optional `DEVFLOW_LIGHT_RUNNER` variable.** The comment-driven workflows previously ran every job — including one-core helpers and the model-API-bound standalone review — on the single runner named by `DEVFLOW_RUNNER`. Set `DEVFLOW_LIGHT_RUNNER` (a bare label or a JSON label array, same shapes as `DEVFLOW_RUNNER`) and the light jobs move to it: `config`, `review_dedupe`, `gate`, `review_finalize`, and the `command` job on a standalone `/prflow:review` in the review workflow, plus `config` and `gate` in the implement workflow. A review-and-fix run and the implement `claude` job keep `DEVFLOW_RUNNER`'s 8-core capacity for the test suite. Leave `DEVFLOW_LIGHT_RUNNER` unset and every job stays exactly where it is today. ([#134](https://github.com/The01Geek/prflow/issues/134))
- **A resumed `/prflow:implement` run now clears a stale `PRFlow:Stuck` label and terminal status at the earliest resume hook.** When a run resumes an issue whose workpad status is terminal (any of `Failed`/`Cancelled`/`Blocked`/`Complete` — the stall backstop writes `Failed`/`Cancelled`), a shared reset routine resets the status to an in-progress word and — through the existing status-to-label mirror — swaps the managed status label (`PRFlow:Stuck`, or `PRFlow:Complete`) for `PRFlow:Implementing` on the issue and its open pull request. On the cloud tier this happens on the config/gate resume branch before the agent job starts; on the local/interactive tier at the start of Phase 1. The resume-kind classification stays correct by reading the prior terminal status from a durable workpad marker. (#137)

## September 1, 2026

- **`/prflow:create-issue` now names the recovery when the post-approval create path refuses on a run with completed audit rounds.** After the user elected *Create it as-is*, the state owner could refuse with no stated remedy: the `unaudited-revision` eligibility answer wrote nothing to stderr, and `record-creation-epoch --round 0` refused without naming which round to pass. Both refusals now name their own recovery — the `unaudited-revision` refusal points at the user's own `record-override --kind user-decline --surface step4-offer` filing election (and a fresh clean audit round as the alternative), and the `--round 0` refusal on a completed-round state names the newest completed round as `--round <M>` for the caller to re-issue. The shipped `create-issue` references state the rules these recoveries follow, so a run that trusts the references files the issue instead of stalling. (#82)
Trust established docs-verify results in `/prflow:create-issue` Step 1, and gate guard claims behind a machine-graded `Verified:` bullet.

The Step 1 shallow→deep escalation predicate no longer escalates on an `ABSENT` doc-reliability verdict: `ABSENT` is an established absence the shallow arm has already produced, so the trigger set is now exactly `UNRELIABLE`, an `unestablished` duty, and a `judged-not-engaged` duty whose bearing observation is anything other than `none-observed`. The `docs-verify` duty-status contract now states that a duty carried out with an empty result is `discharged` (not `judged-not-engaged`, which is reserved for a duty not carried out), and its `Search space surveyed` report field now states the resolved internal-doc location beside the `--search-space` operand so Step 1 can escalate an *exact operand and population identity* duty when the peer surveyed a location differing from the orchestrator's own `.docs.internal` resolution. An acceptance criterion resting on an authorization-guard, permission-key, or gate-condition claim about existing code must now carry a `Verified:` bullet that `scripts/check-verified-premises.py` grades `handle=path-quote state=holds`, so a solo peer's guard claim cannot become a requirement unverified.
- **The `/prflow:create-issue` audit summary now names which round its per-class counts describe.** The audit state tool emits a new `counts_round` token — the round number of the latest completed whole-draft round the class counts (`must_revise`, `advisory`, `invalid`, unresolved-at-close) are read from — on both its `summary-block` and `query-summary` lines, and the Step 4 audit summary line labels those counts with that round and says when a targeted re-check also ran. A two-round run that ran a targeted re-check no longer reads as one that lost its second round. Selection is unchanged: the counts still describe the latest whole-draft round, and a targeted round is still skipped. (#73)
`check-verified-premises.py` now grades the `Verified:`-bullet shapes the issue templates
actually produce. A bullet that cites a repository path and carries a backticked code literal
(with no double-quoted sentence) is graded on that literal — a hit reports `holds`, a miss
`unestablished` and never `refuted`. An absent weak span no longer short-circuits a bullet that
also cites a present path; the resolving quotation is adjudicated and the absent span is disclosed.
A `` `Verified:` `` label (backtick after the colon) is now consumed whole and grades like the bare
label. The premises quality group and the Step 3.5 handle-repair table name a prose form for the
two shapes the checker cannot grade — an externally verified fact (`Per <URL>, checked <YYYY-MM-DD>:
<fact>`) and a documentation-absence claim — so authors write them correctly from the start instead
of demoting a verified fact mid-gate, and the implement-side audit re-fetches those `Per <URL>`
sentences rather than re-litigating them as unverified.
Enforce the title-heading and staged-path contracts of the create-issue staged canonical-draft write (issue #79).

`stage-draft-write.py stage` now refuses stdin whose first two non-blank lines are both `# ` title headings with a `duplicate-title` breadcrumb, so a re-stage that doubles the draft title can no longer reach a created issue, and it resolves a relative `--path` base to an absolute path (refusing a rooted drive-less base on a Windows-style module with `staged-base-driveless`) so the printed `path=` is accepted by `record-staged-write --path` unmodified. The `stage --help`, `emit-body --help`, and the Step 3.6 staged-write procedure and posting-recipe prose now state these contracts.

## August 30, 2026

- **`/prflow:specs` now works as a spelling of the issue-drafting command.** It runs the same
  pipeline as `/prflow:create-issue`, which keeps working unchanged — no existing invocation
  breaks, and nothing needs updating in a repository that already uses the older spelling.
- **An interrupted `/prflow:implement` run resumes from its own pushed work.** A fresh run
  interrupted during implementation — after its checkpoints had pushed, but before the draft pull
  request opened — used to stall when re-triggered, because it could not tell its own branch from
  an unrelated one. It now recognizes that branch and continues where it left off. The guard that
  refuses a branch carrying foreign history is unchanged.
- **`/prflow:implement` works again in an isolated worktree.** Two commands were refused by Claude
  Code's worktree-isolation classifier, which left the run's marker file empty and its session
  guard blocking every session in that checkout. Both now run through bundled helpers that read
  what they need from their own environment rather than from a shell variable.
- **Fix-loop subagents can no longer land a commit on the wrong branch.** They are barred from
  switching the checkout, and the branch is verified after each one returns — a mismatch stops the
  loop instead of committing.
- **A cloud implement run records the branch it is working on.** The workpad's branch line could
  silently stay at its placeholder, because the command that filled it in was refused before it
  ran. It is now resolved directly, and reports a named reason instead of writing nothing when it
  cannot be determined.
- **Reviews finish faster.** Review subagents no longer launch the project's test suite — a
  verifier settles a claim about a test by reading that test's source, and says so explicitly when
  reading cannot settle it, leaving suite evidence to the run itself. Separately, later fix-loop
  iterations reuse the verification checklist from earlier ones instead of re-deriving it. Review
  coverage is unchanged by both.
- **A complete review is no longer reported as "Review failed" over a missing bookkeeping line.**
  The evidence gate now reads the artifacts each review actually writes, so a review that did its
  work keeps its verdict even if the reviewing agent omitted a progress line.
- **Four shipped tools report a clean not-applicable result in a consumer repository.** They each
  detect that a required development-tree input is absent, print one message naming it, and exit
  successfully — instead of a raw traceback or a misreported integrity failure. Behavior inside a
  PRFlow development tree is unchanged.
- **Comment traffic that can never start a command no longer starts a workflow run.** Both shipped
  command-listener workflows now decide this before any job spins up, so unrelated comments on
  issues and pull requests stop consuming Actions minutes.
- **The auto-mode provisioning step was removed from `/prflow:init`.** The optional, consent-gated
  step that made the `auto` permission mode selectable in the Shift+Tab cycle is retired. It only
  ever affected the third-party model providers (Bedrock, Vertex, Foundry) and was already a no-op
  on the Anthropic API. If you previously opted in, your existing `~/.claude/settings.json` value
  is left untouched.

## August 29, 2026

- **`/prflow:create-issue` asks one fixed decision question, and tells you how the last audit
  went before offering another round.** The pre-approval question now has fixed options — run an
  audit round, print the full draft in chat, create it as-is (or *file anyway*, its own option, when
  unresolved audit findings stand against the draft), or change something first — asked through your runner's question
  tool. A re-offered audit round states the previous round's verdict, findings by class and what
  remains unresolved, so the choice is informed. Clarification questions never offer "let the
  implementer choose" as an answer, and the no-options gate no longer flags an "or" inside a
  negation or a list.
- **A pull request from a fork can pass the release verification check.** Artifact
  verification is skipped for an ordinary pull request, because the digest manifest describes
  the published release and any edit is a mismatch. That exemption was gated on the pull
  request coming from the repository itself, so a contribution from a fork was verified
  against the manifest instead and failed on every file it changed — an outside contributor
  saw a red required check they could do nothing about. Origin no longer decides it. A
  release candidate is still verified whatever its origin, and a fork that touches the
  verifier is still refused.
- **A published tree carrying no provenance is refused.** The guard that rejects a missing
  `.release/source.json` keyed on the branch name alone, and a push carries the branch name
  `main` rather than a release branch name — so deleting that one file reported the whole
  check as passing, on the published branch as well as on the pull request that removed it. A
  push without provenance, and a pull request that deletes provenance the branch it targets
  carries, are both refused now.
- **`/prflow:create-issue` now prints the drafted issue in chat only on request, keeping the
  saved-file path as the default presentation.** Step 4 writes the draft file and shows its path,
  the audit summary, the disclosures and the investigation record first — without the body — and
  the combined decision question carries a new *print the full draft in chat* answer that renders
  the title and body verbatim on demand. A write-failed run, an unbound draft, and a
  non-interactive run still print the body as before. Approval stays explicit and about the exact
  saved bytes. (#2122)
- **PRFlow's public repository is now a generated distribution tree.** Development moved to a
  private canonical repository, and every file published here is produced by a deterministic
  exporter and verified before release. Nothing about installing or using PRFlow changes: the
  install commands, marketplace name, plugin name, command names and repository URL are all
  unchanged, and existing installations and version pins keep working. The published tree is
  smaller and easier to review, and each release now carries its own provenance under
  `.release/` — a source-commit record and a SHA-256 for every published file, so any published
  tree can be checked against the digests it ships with.
- **Installer and documentation links now point at the public documentation site.** Messages from
  `install.sh` and `SECURITY.md` that previously referenced maintainer-only documentation paths
  now link to the equivalent pages on the documentation site, so a reader can always reach them.
- **The documentation site deploys again.** The frozen-`DEVFLOW_*` advisory moved into the
  published cloud-setup page, and it carried its generated region's HTML comment delimiters
  with it. The documentation site parses those pages as MDX, which rejects an HTML comment
  outright, so the deployment failed and the site kept serving its previous build. The
  region's markers are now MDX comments and the docs build validates clean.
- **Release verification covers two surfaces it previously skipped.** SVG files are text and
  can carry anything, but were absent from the scanned set, so images shipped unexamined.
  The documentation navigation manifest is JSON, so the markdown link checker never read it
  — a navigation entry pointing at a page that no longer ships would have published a broken
  site. Both are now checked on every release, each proven against a planted defect.
- **The release verification check could be bypassed by a pull request from a fork.** The
  exemption that lets a maintainer change the verifier keyed on the branch name, and a fork
  chooses its own branch names — so a fork branch named `policy-update/…` skipped both the
  judge-comparison and the artifact verification, and reported the required check green on a
  tree that had never been verified. The judge-comparison step's exemptions are now gated on
  the pull request coming from the repository itself, so a fork can never introduce or edit
  the verifier that judges it.
- **The shipped workflows now declare a least-privilege floor.** They carried no top-level
  `permissions:`, so in a repository whose default workflow permission is read-and-write,
  every job received a full read-write token whether it needed one or not. They now default
  to `contents: read`, and the jobs that genuinely need more continue to declare it.
- **The implement workflow's gate job pins its checkout to the default branch**, matching its
  sibling. Without the pin, `actions/checkout` falls back to `GITHUB_REF` silently, leaving
  the trusted-tree property inferred from the trigger rather than stated in the file.

## August 28, 2026

- **Catch vacuous preservation tests and documentation-scope leaks earlier.** Implement runs now require distinguishable preservation fixtures, classify cleanup failures, and stop plain label-and-em-dash issue peers from becoming mandatory documentation. ([#2110](https://github.com/The01Geek/prflow/pull/2110))
- **Mirror the implement run's status onto issue and pull-request labels.** Every
  `/prflow:implement` run now keeps a managed status label in sync on its issue, and on its
  pull request once one exists, so a maintainer sees a stalled or finished run from the issue
  and PR lists without opening the workpad comment. Three labels track the workpad Status:
  `PRFlow:Implementing` (a run is in progress), `PRFlow:Stuck` (a run stopped and needs
  attention), and `PRFlow:Complete` (a run finished). The labels follow the workpad status
  automatically — applied even on the statuses written after the agent has already stopped —
  and a repository turns the whole feature off with the `status_labels.enabled` config key (on
  by default). (#2117)

## August 27, 2026

- **Implement runs author tests in proportion to the change.** On a small change, an `/prflow:implement` run can now skip extra test ceremony that would be out of proportion to the change, while still writing a covering test for each behavior change and recording what it waived on a `Test authoring waived:` line in the pull request's Test Plan. The coverage reviewer honors a recorded waiver — lowering only lesser-severity findings on the named surfaces while keeping its most serious findings at full strength — and a fresh install runs that reviewer only on the first fix-loop iteration. You get this through the normal plugin update. [#2031](https://github.com/The01Geek/prflow/issues/2031)
- **Improvement: `/prflow:implement` runs reach the coding phase sooner.** The pre-coding issue-claim audit now delivers all of its per-pass records to the run's workpad in one batched update at the end of the audit (plus one further call in the uncommon case where the records span more than one reflection kind), instead of a separate network write as each pass completes. Runs spend less time in the pre-coding phase and cloud runs hold their Actions slot for less time, with the recorded workpad content unchanged. You get this through the normal plugin update. [#2018](https://github.com/The01Geek/prflow/issues/2018)
- **Cloud review jobs fail when a review skips its own checks.** A cloud `/prflow:review` or `/prflow:review-and-fix` run that posts a merge-gating verdict without evidence that the review engine ran its verification phases now turns the job red, dismisses the unbacked review, and leaves a comment naming what is missing. A review that legitimately skips the checklist stays green, and a compliant run behaves exactly as before. You get this by re-running the installer to refresh your workflows. [#2075](https://github.com/The01Geek/prflow/issues/2075)

## August 25, 2026

- **Improvement: Issue-implementation runs start with verified lint tools already installed.** The installer now ships a lint manifest and publishes a digest-bound compatibility marker to your repository, and `/prflow:implement` cloud runs install the pinned ShellCheck and Ruff set — run-local and digest- and version-verified — before the agent starts, so runs no longer spend paid turns rediscovering and installing those tools. The change also hardens the cloud review job so it can never execute the environment-setup action edited in the pull request under review. You get this by re-running the installer to refresh your workflows. [#1963](https://github.com/The01Geek/prflow/issues/1963)
- **A completed `/prflow:implement` run can no longer silently leave a prompt-extension record unwritten.** Each run keeps one `prompt extension resolved: …` row per extension it consumes, and an unticked row is meant to be the run's deliberate record that it could not establish that extension's state. But ticking the row was a voluntary bookkeeping step, so a run that resolved an extension and simply forgot to record it produced the exact same unticked row as one that genuinely skipped it — and nothing caught the difference. Finalizing a run as `Complete` is now refused (naming each offending row) while any such row is both unticked and missing its `state not established` note, mirroring the existing refusal on an unticked acceptance criterion. A ticked row, an unticked row with that note, and an older workpad that predates these rows all still finish normally, and `Blocked`/`Failed` outcomes are unchanged. The effect is that an unticked extension row on a completed run is now trustworthy as a deliberate record rather than a possible oversight. You get this through the normal plugin update. [#1943](https://github.com/The01Geek/prflow/issues/1943)
- **Fix: a review no longer runs against a partly loaded review engine.** `/prflow:review-and-fix` — and the review step inside `/prflow:implement`, which drives it — reads PRFlow's review engine from your repository as a file, and it used to accept whatever came back as long as it was readable. A file delivered in part was therefore indistinguishable from a whole one, so a run could assess your pull request against review stages that never arrived and still report a result. The run now confirms it reached the end of that file before acting on it, and where it cannot it stops with `engine-root: incomplete` and the path it read, having applied no fixes and produced no verdict. The shadow pass reads the engine the same way and reports the condition as a coverage gap rather than stopping; a review started with `/prflow:review` loads the engine through your client instead of reading it as a file and is unaffected. You get this through the normal plugin update. [#1603](https://github.com/The01Geek/prflow/issues/1603)

## August 19, 2026

- **Fix: two Windows-only failures in PRFlow's Python helpers are closed.** On a Windows host whose default codec is not UTF-8, a first-party helper that printed an em-dash or emoji used to crash with an encoding error; every tracked helper now forces its output to UTF-8 on startup, so that output prints cleanly. Separately, the issue-audit step rejected a Windows drive-letter path (`C:/Users/…` or `C:\Users\…`), blocking `/prflow:create-issue`'s audit on Windows; the path check now accepts the absolute path forms the host actually uses — a leading `/` on Linux and macOS, or a drive-letter (`C:/…`, `C:\…`) or network-share root on Windows — and uses it unchanged. Linux and macOS are unaffected. You get this through the normal plugin update. [#1762](https://github.com/The01Geek/prflow/issues/1762)

## August 14, 2026

- **`/prflow:create-issue` now writes a minimum-sufficient implementation brief.** The issue body carries the decisions an implementer cannot safely derive on their own and keeps material only when removing it could change what gets built; the investigation behind those decisions — supporting evidence, audit history and detail the repository would rediscover during implementation — is recorded separately instead of being mixed into the body. So an approver reviews the implementation contract rather than the whole investigation, and an implementer spends less effort separating decisions from derivation. A `Verified:` premise stays in the body when the implementation relies on it and moves to the record when it is only confirmatory, and the over-retention audit flags a repeated claim only when no consumer or check needs that copy — it never touches the required projections or machine-read sections. No length, size or criterion-count limit decides what survives, and no load-bearing detail is dropped to make the body shorter. You get this through the normal plugin update. [#1676](https://github.com/The01Geek/prflow/issues/1676)
- **Fix: `/prflow:create-issue` no longer dies when your client lacks its first-choice task-tracking tool.** The workflow tracks its own progress through a seven-step checklist, and it used to reach for one particular tracking tool and stop dead if your client did not offer it — reporting an error such as `No such tool available` after it had already told you the checklist was set up. It now tries the tracking tools it knows in order, moving to the next one whenever the one it tried is unavailable, and asks your client for tools it has not yet offered before giving up. If none of them work, it keeps the same checklist inline in the conversation instead, so the run continues either way. It also announces the checklist only once it genuinely has one, and reports any tool it could not use just after that first line rather than in place of it. Clients that already offered the first tool behave exactly as before. You get this through the normal plugin update. [#1689](https://github.com/The01Geek/prflow/issues/1689)
- **Fix: `/prflow:implement` reliably records its cleanup gate on Windows Git Bash and MSYS2.** During implementation, `/prflow:implement` ticks a Progress row when its code-cleanup gate finishes. On Windows Git Bash and MSYS2 hosts, the value it passed to do that looked like a Unix path, so those shells silently rewrote it into a Windows path before it reached Python — the row stayed unticked and the run reported a spurious miss. The gate now passes a plain, non-path value that those shells leave alone, so the Progress row is ticked as expected. Nothing about the row's familiar label changes, and other platforms were never affected. You get this through the normal plugin update. [#1679](https://github.com/The01Geek/prflow/issues/1679)

## August 13, 2026

- **An issue can now say "no documentation is needed" without turning a page it mentions into required work.** When you write an issue, its `Documentation Needed` block can list files that the change must update, and `/prflow:implement` treats every file named there as a mandatory deliverable. Previously, if you wrote that no documentation was needed and then named a file to explain *why* it was already fine, that mentioned file was still demanded — so the honest, informative phrasing was punished and an otherwise-finished run stalled asking you to edit a page that needed no change. You can now open the block with the standalone word `none` (case-insensitive, optionally followed by a single `,` `.` `;` or `:`), and the block promises nothing — you can still add a sentence and name the page that explains the decision. The word must stand alone as the block's opener: an ordinary sentence such as `None of these pages may be skipped:` still names its files as required. The routine documentation pass runs and updates whatever the change warrants regardless. [#1663](https://github.com/The01Geek/prflow/issues/1663)
- **Fix: Implement review progress stays on the issue workpad** — An inline review-and-fix pass no longer opens a separate progress comment on the draft pull request during `/prflow:implement`; its review stages update the existing issue workpad instead. A standalone pull-request review still maintains its own live progress comment. [#1668](https://github.com/The01Geek/prflow/issues/1668)

## August 12, 2026

- **Improvement: Acceptance Criteria Now Cover Every Desired Outcome** — PRFlow now checks that every independently testable outcome in an issue's Desired Behavior is represented by its acceptance criteria before implementation begins. If an outcome is uncovered, issue creation revises the draft and implementation stops for refinement instead of silently omitting the requirement or inventing a criterion. [#1662](https://github.com/The01Geek/prflow/issues/1662)
- **Weekly retrospectives no longer treat a cancelled CI run as a failure, and no longer miss failures on large CI matrices.** The retrospective decides whether a merged pull request needs a full model analysis partly from how its CI went. A run that was cancelled or superseded — which is what happens to the in-flight run every time you push again — was being counted as a CI failure, so ordinary iteration pushed healthy pull requests into paid analysis. In the other direction, only the first page of check results was being read, so a repository with a large CI matrix could have real failures go uncounted. Cancelled and superseded results are now excluded, all pages are read, and any result the check does not recognize still counts as a failure rather than as a pass. When the check results cannot be read at all, the pull request is still analyzed rather than assumed clean, and the reason is now named in the output. You get this through the normal plugin update. [#1441](https://github.com/The01Geek/prflow/issues/1441)
- **`/prflow:implement` now looks for reusable code by what it does, not by how you were about to write it.** Before writing new code, `/prflow:implement` searches your codebase for something that already does the job, so it can reuse it instead of reinventing it. But once a run had settled on how it was going to write the code, it naturally searched for that exact shape — a search that could only ever confirm the choice it had already made. An existing helper that did the same job in a different style matched none of those terms and stayed invisible, and the run recorded the empty result as if it had proven nothing existed. The reuse search is now keyed on the job itself — the operation it performs, the kind of data it handles, the thing it works on — and before running it the run checks that the search would actually match a different-looking implementation of the same job, re-keying it if it would not. An empty result is now recorded as "nothing matched what I searched for" rather than as a bare claim that nothing exists. The practical effect is fewer near-duplicate helpers introduced by a run. You get this through the normal plugin update. [#1635](https://github.com/The01Geek/prflow/issues/1635)

- **`/prflow:implement` and `/prflow:review` now start reliably on runners that refuse a routine command.** Both commands locate their own skill files at the very start of a run. They did that by running a small shell command that prints a directory path — and on some runners (for example Copilot CLI, and one hosted configuration) the permission layer refuses that exact command shape, even when the command itself is allowed. The old rule only described what to do when the command *ran*, so a flat refusal fell through the cracks: depending on how it was read, the run either stopped at its first step or quietly carried on having skipped it. Both commands now take the skill directory from the location the runner already reports in context first, and only fall back to that shell command when the runner reports no such location. A refusal of the fallback is now handled as its own distinct outcome — the run either finds the directory another way or stops and says the anchor could not be resolved, never skipping the step silently. You get this through the normal plugin update, with no workflow file to re-copy and no permission to add. [#1594](https://github.com/The01Geek/prflow/issues/1594)

## August 11, 2026

- **Your prompt extensions now survive a long run rather than being lost partway through.** PRFlow fetches `.prflow/prompt-extensions/<skill>.md` at the start of a run, but on a long run that fetch is delivered as ordinary command output that can be dropped from the agent's context, leaving the rest of the run applying none of your policy — a run has completed and reported success with the extension absent throughout. The skills that re-enter their own stages now re-fetch your extension at each of those boundaries as well as at run start: `/prflow:implement` at every phase entry and mid-phase re-anchor, `/prflow:review` at every phase and shadow entry, and `/prflow:review-and-fix` once per fix iteration (for both its own extension and `receiving-code-review.md`). A run that loses your policy to context eviction now recovers it instead of continuing without it, and a re-fetch that is refused or fails is reported at that point rather than passed over. `/prflow:pr-description` is a single-pass command and is unchanged. This is a reliability recovery, not a change to how you author extensions. [#1574](https://github.com/The01Geek/prflow/issues/1574)

- **An acceptance criterion is no longer ticked on the word of a check that was never fully carried out.** Before `/prflow:implement` ticks a criterion, two independent checkers look at it in fresh context and their two answers are reconciled — but each one reported only its conclusion, so a checker that skipped part of its own procedure and still answered "satisfied" was indistinguishable from one that did the whole thing, and the criterion was ticked. Each checker now also states, step by step, what it actually did: for every named step of its own procedure it records `yes` or `no` with a one-clause reason. A stated `no` is a perfectly acceptable answer and changes nothing on its own — what is not acceptable is saying nothing. A criterion where either checker left a step unstated is now treated as unverified and blocks, even when both checkers said "satisfied". The statements are recorded on the workpad alongside the verdict, so after the run you can see which steps were performed rather than only what was concluded. The practical effect is that a run is more likely to stop and tell you a criterion was not properly verified, instead of quietly ticking it. [#1580](https://github.com/The01Geek/prflow/issues/1580)

## August 10, 2026

- **A review no longer downgrades a real coverage gap because the gap was described in a comment.** Before a review computes its verdict, it caps a finding whose only effect is on wording that cannot change what the program does, so a cosmetic wording nit never blocks a merge. That test read as if it were about the kind of line the finding pointed at, so a finding that a check audits too small a population, that a guard misses an exception or that a validation misses a type could be capped at Suggestion whenever the gap happened to be described in a comment or docstring — a real defect reported as a minor note. The cap is now decided by what the finding is *about*: if the finding disputes what a mechanism covers, it is graded on that functional gap and never capped, whether or not the change touched the line. A genuinely cosmetic wording nit is still capped exactly as before. [#1455](https://github.com/The01Geek/prflow/issues/1455)
- **A rewritten progress comment no longer loses the hidden lines that identify it.** PRFlow's review progress comment and implementation workpad each begin with hidden marker lines: one identifying which run owns the comment, and, on a review, one recording the verdict and the commit it was issued against. A step that rewrote the whole comment body composed those bytes from what it was holding, so a step that did not retype the markers dropped them — and nothing reported an error, because a later reader looking for a marker found none and read that as "there was no such comment". The visible effect was a review that appeared not to have happened, or a second workpad opened beside the first. A whole-body rewrite now re-inserts any leading marker line it omits, keeping the live comment's order while letting a marker the step does supply win, so a re-stamped verdict still lands. When PRFlow cannot read the live comment to establish which markers it carries, it proceeds only if the new body already carries its own leading marker, and otherwise refuses the write rather than risk dropping one. [#1508](https://github.com/The01Geek/prflow/issues/1508)
- **An issue's `Documentation Needed` files are now actually enforced by `/prflow:implement`.** When an issue names files that must be documented, the run is supposed to name them to its documentation pass and then check each one against the pull request's diff before ticking `Documentation`. Both checks read the file list from a shell variable that does not survive between the run's commands, so the list arrived empty: the documentation pass was never told which files were mandatory, and the diff check compared against nothing. The read is now a single command that prints the file list, so the run reads it from the command's output and both checks see the files the issue named. A read that fails — the issue body could not be fetched, or the list could not be extracted — now stops the run with a recorded reason instead of being treated as "no files were named". Cloud installations should re-run the installer with the new tag rather than bumping `prflow_version` alone; taking only one half stops the documentation gate rather than silently skipping it — see [Cloud Updates](/docs/runs/cloud/updates). [#1554](https://github.com/The01Geek/prflow/issues/1554)

## August 9, 2026

- **Your prompt extensions are now fetched unconditionally, and an implementation run records what it resolved.** The August 5 change delivered `.prflow/prompt-extensions/<skill>.md` as prompt text prepared before the run starts, and demoted the older in-run load to a fallback taken only when that preparation had not delivered. On hosted runs the preparation is refused silently, and a run could then skip the fallback and complete having applied none of your policy — reporting success with nothing to distinguish it from a run that had applied all of it. Both channels now run every time, at all four skills that consume an extension: `/prflow:review`, `/prflow:review-and-fix` (its own extension and `receiving-code-review.md`), `/prflow:implement` and `/prflow:pr-description`. There is no longer a condition a run can decline to evaluate, and where both channels deliver they carry the same content. A `/prflow:implement` workpad's Progress checklist also gains one `prompt extension resolved: …` row per extension the run consumes, written whether or not the run cooperates; an unticked row is that run's own record that it did not establish that extension's state. A workpad created before this change has the rows repaired in on the next run that resumes it. [#1462](https://github.com/The01Geek/prflow/issues/1462)

## August 8, 2026

- **`/prflow:create-issue` no longer stumbles through its pre-filing audit.** The audit step follows a documented order of operations, and that order left out two steps the audit itself requires: reading the round's kind that the dispatch will not accept without, and recording the staged draft write the dispatch depends on. A run following the written order was therefore turned away — twice per round on the file arm a clean run takes — and had to recover before it could continue, which showed up as wasted turns and stray error output during issue creation. The written order now names those steps, and presents the final review-and-create steps in the order they actually run. No behavior of the audit changed — only the instructions the run follows, which now match it. [#1466](https://github.com/The01Geek/prflow/issues/1466)

## August 7, 2026

- **`/prflow:review-and-fix` no longer re-raises a finding the previous pass already recorded.** Before it approves, the fix loop runs one more independent review and compares those findings against the pass before it. A finding that names a whole file rather than a specific line range — the form used when a defect has no single location, such as a missing test file — was compared under a narrower rule than the review engine's own, so it read as brand new even when the previous pass had already recorded it. That spent an extra fix iteration, and at the iteration cap it could reach you as `APPROVE WITH UNRESOLVED SHADOW FINDINGS` on a finding that was not new. The comparison now applies the engine's own matching rule instead of a restatement of it. The same change repairs a pointer in the loop's severity-calibration gate that named the wrong file for the definition it cites. [#1406](https://github.com/The01Geek/prflow/issues/1406)

## August 6, 2026

- **A review's progress checklist now shows whether the run actually delivered its verdict.** The checklist gains a final item, *Run complete — everything this run owed*. On `/prflow:review` it is ticked only after the verdict reaches a durable channel — the formal GitHub review, or a marked comment when the review could not be posted. Previously a run could finish aggregating a verdict, tick its last item, show a finished status, and then deliver nothing, leaving a checklist that read complete either way. Such a run now leaves that item unticked and states why, and it makes one bounded attempt to complete the missing delivery before it ends. On `/prflow:review-and-fix`, which posts no verdict to GitHub, the item is ticked when the fix loop reaches its terminal work. A ticked item means a durable verdict exists; it does not by itself mean the pull request carries an approve or request-changes merge signal. [#1367](https://github.com/The01Geek/prflow/issues/1367)

## August 5, 2026

- **Your prompt extensions now reach review and implementation runs every time.** `.prflow/prompt-extensions/review.md`, `review-and-fix.md`, `receiving-code-review.md` and `implement.md` are delivered to the agent as prompt text prepared before the run starts, instead of depending on the agent choosing to load them mid-run. Previously the extension reached the agent in only 8 of 18 sampled review runs and 1 of 4 sampled implementation runs, and a run that never loaded your policy still posted an ordinary verdict, so nothing distinguished it from one that had. If an extension cannot be delivered, the run now says so explicitly rather than proceeding as though you had configured none. An absent or empty extension is still a silent no-op. Cloud installations should re-run the installer with the new tag rather than bumping `prflow_version` alone — see [Cloud Updates](/docs/runs/cloud/updates). [#1264](https://github.com/The01Geek/prflow/issues/1264)
- **`/prflow:create-issue` now writes a short implementer brief and keeps the investigation detail in a separate comment.** The issue body carries only what an implementer needs to build the change — what is broken, what "done" looks like, which files to start in, which hazards matter. Rejected designs, supporting evidence, deliberation and lower-severity notes are posted as a separate investigation-record comment on the same issue (with any workflow-trigger tokens neutralized so it cannot start a run). Set the new `create_issue.investigation_record_enabled` config key to `false` to skip posting that comment; the brief-versus-record sorting is unchanged either way. [#1331](https://github.com/The01Geek/prflow/issues/1331)
- **Cloud review comments now use a safer event boundary.** Post `/prflow:review` on the pull-request conversation tab. Commands entered in the review-submission box or an inline diff comment no longer start a run. Cloud jobs also check out the repository's default branch before they read trusted configuration. [#1163](https://github.com/The01Geek/prflow/issues/1163)

## August 3, 2026

- **Numerical acceptance criteria now name their measurement.** PRFlow records the exact command or counting rule behind a threshold. If it cannot establish that measurement, it labels the criterion as unestablished instead of presenting an ambiguous number. [#1223](https://github.com/The01Geek/prflow/issues/1223)

## Older Releases

Entries from July 2026 are in the [release notes archive](/docs/reference/release-notes-archive-2026).
