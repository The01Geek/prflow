---
name: docs
description: Use when documentation generally needs to catch up with a branch before pushing or merging, covering internal developer docs, external customer-facing docs, and release notes together — "update the docs", "do a docs pass before I merge", "make sure everything's documented". Prefer this when no single documentation target is named; use the narrower prflow:docs-sync-internal, prflow:docs-sync-external, or prflow:docs-release-notes when the user names one.
---

**Portable helper anchor (single-statement).** The bundled-helper commands in this skill resolve the skill directory inline at each call site via `${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}`. When `$CLAUDE_SKILL_DIR` is set and non-empty (Claude Code), run each command exactly as written. Otherwise locate the directory yourself — this text lives in a file inside it, whose sibling `../../scripts/` directory exists — by replacing the placeholder with the skill base directory the runner reports in context (e.g. a `Base directory for this skill:` line) and accepting a candidate only once `ls <candidate>/../../scripts/` succeeds in the same shell the helper commands run in. If a path form is rejected, use the form that shell reports (`pwd` shows it); a Windows-form base directory (`C:\...`) may first be converted with one standalone `wslpath -u '<path>'` then `cygpath -u '<path>'` command in order — no platform branch — using the output only when the command succeeded and printed a non-empty path, else falling through to the filesystem check. Resolve the anchor inline at every call site — never capture it into a shell variable that a later statement reads, because some runners' inline-bash marshaling drops such variables. If no candidate validates — neither `$CLAUDE_SKILL_DIR` nor a runner-reported base directory whose `../../scripts/` exists — stop and report that the helper anchor could not be resolved rather than running a command with a broken path.

Consumer prompt extension (load first). Before doing this skill's work, load any consumer-supplied prompt extension for this skill and honor it. From the repo root, emit the granted vendored-literal leading token first:

```bash
.prflow/vendor/prflow/scripts/load-prompt-extension.sh docs
```

On a `command not found` / `No such file` / exit-127 reading (this repository's own local tier, where `.prflow/vendor/` is materialized only at runtime), re-invoke the same helper with the `.prflow/vendor/prflow/` prefix removed (`scripts/load-prompt-extension.sh docs`) as a single leading-token statement. If that too is not found (a non-Claude-Code runner where neither repo-relative path exists), fall back to the portable anchor form:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh docs
```

If the invocation fails because the helper path does not exist (`No such file`, exit 127, or the platform equivalent) on every form above, that is the anchor-resolution failure described in the *Portable helper anchor* note above — fix the anchor, don't report a missing extension. If instead the harness refuses the command outright — a permission denial rather than a missing file — the extension's state is **unestablished**: report that in the run's output and never treat it as a clean policy pass (*unknown is not zero*). Otherwise, if the helper exits non-zero, a consumer extension exists but could not be loaded — surface its stderr message and do not silently proceed as if none existed. If it exits 0 and prints text, treat that text as additional instructions appended to the end of this skill's own prompt for this run — it is upgrade-safe, consumer-owned customization committed under `.prflow/skill-extensions/`. If it exits 0 and prints nothing, proceed unchanged.

## Objective

You are an AI Documentation Agent for code repositories. You perform up to three sequential documentation tasks in a single session, sharing context between them so that findings from earlier steps inform later steps. Steps 1 and 2 are individually gated by config flags (see below) — a disabled step is skipped, not failed.

This skill is a router: it composes no prose of its own, delegating each step to a docs-family skill that composes and reads the shared writing standard itself. So it does not read `lib/writing-standard.md` directly — the standard is read by the skill each step dispatches.

### Config gates (read once, up front)

Read both toggles before starting (they default to `true` — enabled — when absent). Run each read as a direct leading-token invocation and use its printed output as the value — never capture it into a variable via command substitution, a shape some harnesses (the cloud tier's matcher, a worktree-isolated session) silently refuse, which would leave both gates unread:

```bash
.prflow/vendor/prflow/scripts/config-get.sh .docs.internal_enabled true
```

```bash
.prflow/vendor/prflow/scripts/config-get.sh .docs.external_enabled true
```

On a `command not found` / `No such file` / exit-127 reading, re-invoke each read with the `.prflow/vendor/prflow/` prefix removed (`scripts/config-get.sh` plus the same operands) as a single leading-token statement; if that too is not found, use the portable anchor form from the *Portable helper anchor* note above with the same operands.

- The internal toggle printing `false` → skip Step 1.
- The external toggle printing `false` → skip Step 2.
- A toggle read the harness refuses outright — a permission denial rather than a missing file — leaves that gate **unestablished**: run the step (the toggles default to `true`) and report the gate as `unestablished` in the Final Summary, never as a clean read (*unknown is not zero*).

Step 3 (release notes) is deliberately ungated: the release-notes skill itself no-ops appropriately when the repository's release-notes artifacts are disabled. Note which steps you skipped — the Final Summary must report it.

### Per-step outcomes

Each step ends in exactly one of four outcomes, and the Final Summary names one per step: **completed** (the nested skill ran to its own completion), **skipped** (disabled by config), **failed** (the nested skill errored, or its Skill-tool load returned an error instead of a skill body), or **unestablished** (the gate or load state could not be determined). On a failed or unestablished step, record the outcome and continue to the next step — this router composes no prose of its own, so never improvise the failed step's work in its place.

---

## Step 1: Update Internal Documentation

Skip this step when the internal toggle printed `false` — record "internal docs disabled by config" for the Final Summary and proceed to Step 2.

Invoke the Skill tool with `skill: docs-sync-internal` and follow its instructions exactly.

After completing Step 1, note what you changed — you will need this context for Step 2. As part of that note, record a **public-doc impact list**: one line per user-visible behavior change on the branch (a changed command, output, setting, or workflow a user would notice), or the explicit line "public-doc impact: none" — Step 2's comparison scope depends on this list existing, and an omitted list is indistinguishable from an empty one.

---

## Step 2: Align External Documentation

Skip this step when the external toggle printed `false` — record "external docs disabled by config" for the Final Summary and proceed to Step 3.

Invoke the Skill tool with `skill: docs-sync-external` and follow its instructions exactly.

Use the internal documentation you updated in Step 1 as your primary source of truth when comparing against external docs, and treat Step 1's public-doc impact list plus the branch diff as the comparison scope — every listed item must be aligned or explicitly reported as needing no external change (if Step 1 was skipped, use the branch diff as the source of truth and scope instead).

After completing Step 2, note what you changed — you will need this context for Step 3.

---

## Step 3: Generate Release Notes

Invoke the Skill tool with `skill: docs-release-notes` and follow its instructions exactly.

Use the documentation changes from Steps 1 and 2 as additional context when assessing customer-visible impact.

**Do not commit** — leave committing to the caller.

---

## Final Summary

After the last step, provide a brief summary listing:
- Each step's outcome — completed / skipped / failed / unestablished — with its one-clause reason (e.g. "skipped: disabled by config (`docs.internal_enabled: false`)"), so a failed or unestablished step is never laundered into a clean pass
- Internal doc files added or edited (Step 1)
- Step 1's public-doc impact list, carried forward verbatim (or its explicit "public-doc impact: none")
- External doc files added or edited (Step 2)
- Release note entry added or skipped with reason (Step 3)
- Any config gate whose read was refused, reported as `unestablished`
