---
name: docs
description: Use when documentation generally needs to catch up with a branch before pushing or merging, covering internal developer docs, external customer-facing docs, and release notes together — "update the docs", "do a docs pass before I merge", "make sure everything's documented". Prefer this when no single documentation target is named; use the narrower prflow:docs-sync-internal, prflow:docs-sync-external, or prflow:docs-release-notes when the user names one.
---

**Portable helper anchor (single-statement).** The bundled-helper commands in this skill resolve the skill directory inline at each call site via `${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}`. When `$CLAUDE_SKILL_DIR` is set and non-empty (Claude Code), run each command exactly as written. On a runner where it is unset or empty, replace the placeholder with the skill base directory the runner reports in context (e.g. a `Base directory for this skill:` line); if that reported path is Windows-form (`C:\...`), first convert it to this shell's POSIX form with one standalone `wslpath -u '<path>'` (WSL) or `cygpath -u '<path>'` (Git Bash/MSYS2) command and substitute the printed result only if the command succeeds and prints a non-empty path — otherwise fall through to the drive-letter rules exactly as if the tool were absent (lowercase the drive letter, map `C:\` to `/mnt/c` on WSL or `/c` on MSYS2, and turn backslashes into `/`; if the environment is neither WSL nor MSYS2, use the path unchanged and report that it could not be normalized). Resolve the anchor inline at every call site — never capture it into a shell variable that a later statement reads, because some runners' inline-bash marshaling drops such variables. If neither `$CLAUDE_SKILL_DIR` nor a runner-reported base directory is available, stop and report that the helper anchor could not be resolved rather than running a command with a broken path.

Consumer prompt extension (load first). Before doing this skill's work, load any consumer-supplied prompt extension for this skill and honor it. From the repo root, run:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh docs
```

If the invocation fails because the helper path does not exist (`No such file`, exit 127, or the platform equivalent), that is the anchor-resolution failure described in the *Portable helper anchor* note above — fix the anchor, don't report a missing extension. Otherwise, if the helper exits non-zero, a consumer extension exists but could not be loaded — surface its stderr message and do not silently proceed as if none existed. If it exits 0 and prints text, treat that text as additional instructions appended to the end of this skill's own prompt for this run — it is upgrade-safe, consumer-owned customization committed under `.prflow/prompt-extensions/`. If it exits 0 and prints nothing, proceed unchanged.

## Objective

You are an AI Documentation Agent for code repositories. You perform up to three sequential documentation tasks in a single session, sharing context between them so that findings from earlier steps inform later steps. Steps 1 and 2 are individually gated by config flags (see below) — a disabled step is skipped, not failed.

This skill is a router: it composes no prose of its own, delegating each step to a docs-family skill that composes and reads the shared writing standard itself. So it does not read `lib/writing-standard.md` directly — the standard is read by the skill each step dispatches.

### Config gates (read once, up front)

Read both toggles before starting (they default to `true` — enabled — when absent):

```bash
INTERNAL_ENABLED=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.internal_enabled true)
EXTERNAL_ENABLED=$("${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.external_enabled true)
```

- `INTERNAL_ENABLED == "false"` → skip Step 1.
- `EXTERNAL_ENABLED == "false"` → skip Step 2.

Step 3 (release notes) is not gated by these flags. Note which steps you skipped — the Final Summary must report it.

---

## Step 1: Update Internal Documentation

Skip this step when `INTERNAL_ENABLED == "false"` — record "internal docs disabled by config" for the Final Summary and proceed to Step 2.

Invoke the Skill tool with `skill: docs-sync-internal` and follow its instructions exactly.

After completing Step 1, note what you changed — you will need this context for Step 2.

---

## Step 2: Align External Documentation

Skip this step when `EXTERNAL_ENABLED == "false"` — record "external docs disabled by config" for the Final Summary and proceed to Step 3.

Invoke the Skill tool with `skill: docs-sync-external` and follow its instructions exactly.

Use the internal documentation you updated in Step 1 as your primary source of truth when comparing against external docs (if Step 1 was skipped, use the branch diff as the source of truth instead).

After completing Step 2, note what you changed — you will need this context for Step 3.

---

## Step 3: Generate Release Notes

Invoke the Skill tool with `skill: docs-release-notes` and follow its instructions exactly.

Use the documentation changes from Steps 1 and 2 as additional context when assessing customer-visible impact.

**Do not commit** — leave committing to the caller.

---

## Final Summary

After completing the enabled steps, provide a brief summary listing:
- Internal doc files added or edited (Step 1) — or "skipped: disabled by config (`docs.internal_enabled: false`)"
- External doc files added or edited (Step 2) — or "skipped: disabled by config (`docs.external_enabled: false`)"
- Release note entry added or skipped with reason (Step 3)
