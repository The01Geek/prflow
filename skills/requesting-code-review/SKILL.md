---
name: requesting-code-review
description: Use when completing a task or major feature, or before merging, to have PRFlow's final-pass reviewer check the work against its requirements.
---

# Requesting Code Review

**Portable helper anchor (single-statement).** The bundled-helper commands in this skill spell the skill directory as `${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}`. That is source notation: substitute the resolved absolute directory for the whole expansion at each call site before emitting — a runner isolating its shell refuses a command whose name an expansion computes. Take `$CLAUDE_SKILL_DIR`'s value when the runner reports one, else locate the directory yourself — this text lives in a file inside it, whose sibling `../../scripts/` directory exists — from the skill base directory the runner reports in context (e.g. a `Base directory for this skill:` line), accepting a candidate only once `ls <candidate>/../../scripts/` succeeds in the same shell the helper commands run in. If a path form is rejected, use the form that shell reports (`pwd` shows it); a Windows-form base directory (`C:\...`) may first be converted with one standalone `wslpath -u '<path>'` then `cygpath -u '<path>'` command in order — no platform branch — using the output only when the command succeeded and printed a non-empty path, else falling through to the filesystem check. Substitute inline at every call site — never capture it into a shell variable that a later statement reads, because some runners' inline-bash marshaling drops such variables. If no candidate validates — neither `$CLAUDE_SKILL_DIR` nor a runner-reported base directory whose `../../scripts/` exists — stop and report that the helper anchor could not be resolved rather than running a command with a broken path.

This skill originates in the MIT-licensed `superpowers` plugin (© 2025 Jesse Vincent) and has been substantially modified by PRFlow.

Invoking it is the user's request to dispatch its reviewer. First load the repository's extension for this review, from the repository root:

```bash
.prflow/vendor/prflow/scripts/load-prompt-extension.sh requesting-code-review
```

On `command not found` / `No such file` / exit 127, use the anchor form:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh requesting-code-review
```

Not-found on both forms is the anchor failure above: fix the anchor; do not report a missing extension. Any other non-zero exit means a consumer extension exists but could not be loaded: surface its stderr. No `PROMPT-EXTENSION-STATUS:` line on stderr, as after a refusal, is an unestablished extension to report, never an empty one.

Then dispatch the `prflow:requesting-code-review` agent with a prompt holding:

- a one-line description of what was built;
- the requirements or plan it must meet;
- the base and head commits (e.g. `origin/main` and `HEAD`);
- on `content-present`, `Consumer review policy:` and the extension's text: the helper's output minus every diagnostic it prints, even one run onto the text's last line.

For test edits, read `../fix/references/fix-discipline.md` from this skill's directory; include its *Tests* evidence. Stop if unreadable.

Fix Critical findings at once and Important ones before moving on; push back with technical reasoning, and the code or tests that prove it, when the reviewer is wrong.
