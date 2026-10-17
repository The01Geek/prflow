---
name: create-issue
description: Permanent alias for /prflow:spec, which runs the same issue-drafting pipeline; prefer /prflow:spec. Use when a rough user story, bug report, feature idea, piece of feedback, or an implementation plan should be recorded as a GitHub issue rather than built right now. Kept so existing /prflow:create-issue and /devflow:create-issue invocations keep working.
argument-hint: <user-story>
---

## Forward to spec

Invoke the Skill tool with `skill: prflow:spec` and `args` set to `$ARGUMENTS`, then follow it. This alias loads no prompt extension of its own; spec loads the one extension for both command names.

Without a Skill tool, read spec's `SKILL.md` with your file-read tool from this skill's sibling directory `${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}/../spec/` (when that variable is empty, the `spec` sibling of the skill base directory the runner reports — never a working-directory-relative path), and follow it with the arguments above as the user story. Resolve its reference files, and any path it derives from its own skill directory, against that `spec` directory, not this one.
