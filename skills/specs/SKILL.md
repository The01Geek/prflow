---
name: specs
description: Use when a rough user story, bug report, feature idea, piece of feedback, or an implementation plan should be recorded as a GitHub issue — "file a ticket for this", "open an issue", "write this up for the backlog", "we should track this", "log this bug", "spec this out as a ticket so we can pick it up later" — i.e. the user wants it tracked rather than built right now. For exploring or designing the work itself, reach for a brainstorming or planning skill first; this skill records the outcome as a spec'd-out GitHub issue.
argument-hint: <user-story>
---

## Consumer prompt extension (load first)

Before doing this skill's work, load any consumer-supplied prompt extension for this skill and honor it. From the repo root, run:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh specs
```

Exit 0 with text is consumer-owned customization under `.prflow/skill-extensions/` — treat it as instructions appended to the end of this skill's own prompt for this run. Exit 0 with no output: proceed unchanged. On a non-zero exit where the helper ran but failed, a consumer extension exists but could not be loaded: surface its stderr message, never silently proceed as if none existed. A missing helper path (`No such file`, exit 127, or the platform equivalent) is an anchor-resolution failure — resolve the `${CLAUDE_SKILL_DIR}` anchor to this skill's own base directory (the one this runner reports in context) rather than reporting a missing extension.

## Forward to create-issue

`/prflow:specs` is a thin forwarding alias for `/prflow:create-issue`. Open `skills/create-issue/SKILL.md` with your file-read tool and follow it exactly, as if `/prflow:create-issue` had been invoked — but before you resolve any reference file create-issue names, read and apply the reference-base redirect below, because it governs where those references resolve and skipping it silently degrades the run.

Reference-base redirect (load-bearing). The runner leaves the skill base directory (`${CLAUDE_SKILL_DIR}`) pointing at `skills/specs/` even after you open create-issue as a plain file, so create-issue's own reference paths would otherwise resolve to a nonexistent `skills/specs/references/` and silently degrade onto its reference-load-failure arms. Resolve create-issue's reference files from `skills/create-issue/references/`, and resolve any path create-issue derives from its own skill directory against `skills/create-issue/` — never the invoked `skills/specs/`. Helpers reached through the `../../scripts/` suffix, and prompt extensions named by a literal skill name, are unaffected.

Resolve those create-issue targets portably, not as bare working-directory-relative paths — in an installed consumer checkout the working directory is the consumer's own project (which has no `skills/` tree), while the plugin's skills live beside `${CLAUDE_SKILL_DIR}`. Because `${CLAUDE_SKILL_DIR}` is `skills/specs/`, its sibling create-issue directory is `${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}/../create-issue/`; resolve create-issue's `SKILL.md` and every reference path under it relative to that sibling directory (when `${CLAUDE_SKILL_DIR}` is empty, take the create-issue sibling of the skill base directory the runner reports in context — never that base directory itself, which is the invoked specs directory) so both the initial open of create-issue's skill file and its reference loads resolve in a consumer checkout and not only in PRFlow's own dev tree.

## Runner setup

**Portable helper anchor (single-statement).** The bundled-helper commands in this skill resolve the skill directory inline at each call site via `${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}`. When `$CLAUDE_SKILL_DIR` is set and non-empty (Claude Code), run each command exactly as written. Otherwise locate the directory yourself — this text lives in a file inside it, whose sibling `../../scripts/` directory exists — by replacing the placeholder with the skill base directory the runner reports in context (e.g. a `Base directory for this skill:` line) and accepting a candidate only once `ls <candidate>/../../scripts/` succeeds in the same shell the helper commands run in. If a path form is rejected, use the form that shell reports (`pwd` shows it); a Windows-form base directory (`C:\...`) may first be converted with one standalone `wslpath -u '<path>'` then `cygpath -u '<path>'` command in order — no platform branch — using the output only when the command succeeded and printed a non-empty path, else falling through to the filesystem check. Resolve the anchor inline at every call site — never capture it into a shell variable that a later statement reads, because some runners' inline-bash marshaling drops such variables. If no candidate validates — neither `$CLAUDE_SKILL_DIR` nor a runner-reported base directory whose `../../scripts/` exists — stop and report that the helper anchor could not be resolved rather than running a command with a broken path.
