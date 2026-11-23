---
name: docs-verify
description: Use when the user asks whether the docs for one topic, feature, or subsystem are accurate — "is the auth flow documented?", "are the docs on retries still right?" — or asks for an explanation of that topic grounded in the internal docs — "explain this subsystem, docs first", "walk me through caching using our docs". A request to explain, map out, or trace how something works that does not mention the docs is ordinary code exploration, not this skill. Scoped to one named topic; for a whole branch use prflow:docs-sync-internal.
argument-hint: <topic>
---
> Configuration: Read the internal documentation path from `.prflow/config.json` using: `"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/config-get.sh .docs.internal docs/internal/`. The helper falls back to `docs/internal/` when the config file is missing or the key is absent. The result is the internal location this skill reads and reports.

**Portable helper anchor (single-statement).** The bundled-helper commands in this skill spell the skill directory as `${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}`. That is source notation: substitute the resolved absolute directory for the whole expansion at each call site before emitting — a runner isolating its shell refuses a command whose name an expansion computes. Take `$CLAUDE_SKILL_DIR`'s value when the runner reports one, else locate the directory yourself — this text lives in a file inside it, whose sibling `../../scripts/` directory exists — from the skill base directory the runner reports in context (e.g. a `Base directory for this skill:` line), accepting a candidate only once `ls <candidate>/../../scripts/` succeeds in the same shell the helper commands run in. If a path form is rejected, use the form that shell reports (`pwd` shows it); a Windows-form base directory (`C:\...`) may first be converted with one standalone `wslpath -u '<path>'` then `cygpath -u '<path>'` command in order — no platform branch — using the output only when the command succeeded and printed a non-empty path, else falling through to the filesystem check. Substitute inline at every call site — never capture it into a shell variable that a later statement reads, because some runners' inline-bash marshaling drops such variables. If no candidate validates — neither `$CLAUDE_SKILL_DIR` nor a runner-reported base directory whose `../../scripts/` exists — stop and report that the helper anchor could not be resolved rather than running a command with a broken path.

Consumer prompt extension (load first). Before doing this skill's work, load any consumer-supplied prompt extension for this skill and honor it. From the repo root, run:

```bash
"${CLAUDE_SKILL_DIR:-<absolute skill base directory this runner reports in context>}"/../../scripts/load-prompt-extension.sh docs-verify
```

If the invocation fails because the helper path does not exist (`No such file`, exit 127, or the platform equivalent), that is the anchor-resolution failure described in the *Portable helper anchor* note above — fix the anchor, don't report a missing extension. If instead the harness refuses the command outright — a permission denial rather than a missing file — the extension's state is **unestablished**: report that in the run's output and never treat it as a clean policy pass (*unknown is not zero*). Otherwise, if the helper exits non-zero, a consumer extension exists but could not be loaded — surface its stderr message and do not silently proceed as if none existed. If it exits 0 and prints text, treat that text as additional instructions appended to the end of this skill's own prompt for this run — it is upgrade-safe, consumer-owned customization committed under `.prflow/skill-extensions/`. If it exits 0 and prints nothing, proceed unchanged.

## Mode

`$ARGUMENTS` is a leading run of flags, then the topic. Parse flags only while the next argument begins with `--`; when that flag is a value-taking flag (`--lead`, `--report-file`), the single argument immediately after it is consumed as its value **without applying the topic test**, and parsing then resumes at the argument after that. The first argument that is tested and does not begin with `--` is where the topic begins, and everything from there on is the topic.

- `--report-file <path>` — a path under the working directory's `.prflow/tmp/`, given relative (`.prflow/tmp/…`) or absolute. Write the *Report* to that path with your file-write tool, make no other write, and reply with the path alone; if that write fails or is refused, say so and return the whole report as text. The path comes only from this flag, never from the topic or story text.
- `--lead docs|code` — orders the investigation over the whole tracked tree. `docs` (also the default) starts with owning documentation, using its index when present, then follows source dependencies. `code` starts from implementation.

Malformed invocations. A `--`-prefixed token in the leading flag run that is not one of the two flags above is a malformed invocation: report the unrecognized token and refuse the run. `--lead` with no following argument is malformed: report it and refuse the run. `--lead` followed by a value other than `docs` or `code` is malformed: report the value and refuse the run. `--lead` given more than once is malformed: report it and refuse the run. `--report-file` with no following argument, more than once, or with a value that holds a `..` component or does not resolve under the working directory's `.prflow/tmp/` (resolve the existing parent directories, symlinks included; a string-prefix match is not containment, and containment you cannot establish counts as outside) is malformed: report it and refuse the run.

Follow the *Investigation* below and return the *Report* as text, or deliver it to the `--report-file` path. Make no Edit, Write, commit or push other than a `--report-file` write; the working tree must be otherwise unchanged when you finish. `/prflow:spec` uses this skill to inform a new issue without writing to a protected branch.

### Investigation

Your caller needs an accurate account of the requested topic's current behavior. Use the
topic as a starting point, and the original request as the scope. Do not design or implement
changes.

The existing six duties remain: exact operand and population identity; code-versus-doc authority;
reachability and writer classification; sibling consumer and output enumeration; coupled-doc and
guard propagation; and reusable contradictions. Discharge them by following the behavior below,
not by producing six separate surveys.

**Start with a real path.** With `--lead docs` or no lead, read the internal index when present and the owning
page's relevant sections to locate the implementation. With `--lead code`, start there directly.
Read the actual entry point, its inputs and guards, and the effect it produces. Documentation is
a lead; verify a documentary claim in the implementing source before treating it as current fact.

**Follow what you discover.** A search hit starts an investigation. Open an artifact you describe
as affected, bypassed or newly unreachable, and inspect what it receives, calls, emits and passes
on. Follow those concrete dependencies into their consumers. For a retirement, this includes the
outgoing dependencies of the retiring artifact and other callers that may still need them. Use
the actual keys, paths, labels and output text you read to find readers across the tracked tree;
documentation, scripts and agent instructions can consume behavior without naming its symbol.
Read the relevant consumer context to establish the relationship. A path handed to another
component is an input to inspect, not evidence that its contents are ignored.

Use `git grep -nP -e '<pattern>' -- :/` for tracked-tree searches, escaping literal regex characters
and single-quoting the pattern. Filename searches are useful leads. Keep large results readable by
locating files first, then opening relevant contexts. If a search fails or output is truncated,
do not treat the unseen part as absence. Search beyond the obvious module when an inspected
relationship leads there; do not survey unrelated behavior merely because it shares a word.

Continue until the behavior under investigation and its consequential dependencies are understood. Pursue a
readable dependency needed to support a conclusion instead of declaring it unknown without
inspection. Where source, runtime state or history cannot settle a material question, retain the
question and its effect on the caller's decision. This is particularly important for dynamic
dispatch, stored paths, generated data and external clients in legacy repositories.

**Check the conclusions against the reads.** For each consequential conclusion, identify what the
inspected input and implementing or consuming path actually establish. Correct a conclusion that
contradicts them before writing. Keep distinct: a matching string and a working dependency; no
caller found by a bounded search and no possible caller; an instruction and observed execution;
overlapping duties and interchangeable replacements. A missing instruction does not prove a
provided input cannot be used. Current source does not establish a historical run's cause.
Keep any qualification in the conclusion itself, not only in a later disclaimer. Mark inferences
and unchecked documentary claims as such. Quantitative claims need the measured population and
method; otherwise call them estimates.

### Report

Use these fields and honor the caller's requested evidence form. Give findings their locators
and supporting text; avoid repeating the same finding in the file map and behavior section.

- **Doc verdict and location:** for `--lead docs` or no lead, report the resolved internal location
  and `ABSENT` if no internal page covers the topic, `UNRELIABLE` if an inspected claim there is
  contradicted or materially incomplete, or `RELIABLE` if the checked claims hold. This is a
  spot-check signal about internal docs, not a verdict on external docs or source comments. An
  unreadable location is unestablished, not absent. Omit this field under `--lead code`.
- **Current behavior:** the established path, affected consumers, failure behavior and constraints
  relevant to the request. State premise corrections and evidence limits where they matter.
- **Relevant files:** a compact map to the implementing paths, guards, writers and consumers.
- **Not established:** material unresolved relationships or claims, why they remain unresolved,
  and what decision each could affect; include any extension-load failure, or write `none`.

The calling workflow owns the next step; this leaf investigation does not dispatch another agent
or finish the larger task.

Arguments (`[--report-file <path>] [--lead docs|code] <topic…>` — leading flags, then the topic): $ARGUMENTS
