---
title: "Configuration Problems"
description: "Fix a missing, invalid, ignored, dropped or not-yet-effective PRFlow setting."
---

Diagnose `.prflow/config.json` when PRFlow cannot read it, or when a setting does not change what a run does.

<AccordionGroup>

<Accordion title="The workflow reports config.json not found">

**Symptom:** a cloud run stops early and says it could not find the configuration file.

Check that the file exists on the default branch and is committed:

```bash
git ls-files --error-unmatch .prflow/config.json
git check-ignore -v .prflow/config.json
```

The first command fails if the file is untracked. The second names the ignore rule if one is hiding it. Run `/prflow:init`, or the cloud installer, to scaffold the file. If your repository ignores it broadly, add it explicitly and narrow the ignore rule.

</Accordion>

<Accordion title="The workflow reports invalid JSON">

**Symptom:** a cloud run stops with a parse error naming the configuration file.

Validate the syntax locally:

```bash
python3 -m json.tool .prflow/config.json
```

Fix the first parse error it reports, then run the command again. The cloud config reader fails on malformed JSON rather than quietly falling back to a full scaffold, so a trailing comma stops the whole run.

Point your editor at `.prflow/config.schema.json` for validation of types and accepted values. The runtime still applies setting-specific fallbacks for some missing or invalid leaves.

</Accordion>

<Accordion title="A setting is ignored">

**Symptom:** the setting is present and valid, and behavior does not change.

Print the top-level key names to check the exact spelling and nesting:

```bash
jq 'keys' .prflow/config.json
```

Current families begin with `prflow`, such as `prflow_implement` and `prflow_review`. Running `/prflow:init` migrates supported older family names and backfills newly added keys.

Then check the execution path. These are the common mismatches:

- `prflow.allowed_tools` does not apply to implementation.
- `prflow_implement.allowed_tools` does not apply to the light cloud command path.
- `prflow_runner` and `workflows.prflow-review` have no effect in a fresh installation, because the automatic-review files are not shipped.
- Provider selection is set per section, not once for the whole file.

</Accordion>

<Accordion title="A per-agent model or effort override did nothing">

**Symptom:** you set a model or an effort for one review agent, the run completes normally and the agent behaves exactly as before.

Print the overrides block:

```bash
jq '.prflow_review.agent_overrides' .prflow/config.json
```

A malformed override is dropped rather than raising an error. The run continues with the value it would have used anyway, so the only visible trace is a warning. On a cloud run, search the job log for it:

```bash
gh run view <run-id> --log | grep "resolve-review-overrides"
```

Check each value against what is accepted:

| Field | Accepted values | What a bad value does |
| --- | --- | --- |
| `model` | `sonnet`, `opus`, `haiku`, `fable` | Dropped with a warning. The agent falls back to the top-level `claude_model`. |
| `effort` | `low`, `medium`, `high`, `xhigh`, `max` | Dropped with a warning. The agent falls back to the session effort. |
| `iterations` | `first-only` | Dropped with a warning. The agent runs on every iteration. |

An empty string, a whitespace-only string and a nested object are all treated as bad values. A provider-specific model identifier belongs at the top-level `claude_model`, not here.

Resolution is per entry. An agent that has its own entry uses only that entry, and the `default` entry does not fill in its missing fields. `default` supplies a model and effort only for agents that have no entry of their own.

<Warning>
An entry whose key is not one of the nine review agents is refused by the schema, so validate against `.prflow/config.schema.json` before you commit. An entry that is present but is not an object is ignored with a warning, and `default` then applies to that agent instead.
</Warning>

</Accordion>

<Accordion title="A configuration change has not taken effect">

**Symptom:** you changed a setting in a pull request, and that pull request's own run behaves as though you had not.

Confirm what the default branch actually holds:

```bash
git show origin/<default-branch>:.prflow/config.json | jq '<your key path>'
```

Trigger-time security settings are read from the default branch, not from the pull request. Tool grants, provider routing, commit attribution, runner executable paths and git-environment pins added by a pull request are post-merge-only for that pull request's own run.

Merge the configuration change, then start a new run.

<Warning>
Do not use a same-pull-request result as evidence that a new permission took effect. It cannot be, and reading it that way hides the real state of the grant.
</Warning>

</Accordion>

<Accordion title="The installer backfilled unexpected keys">

**Symptom:** re-running the installer or `/prflow:init` adds keys you did not write.

Review the diff before you commit it:

```bash
git diff .prflow/config.json
```

Backfill adds newly scaffolded keys. It does not replace existing values or arrays. A new default can expose a feature for discovery without enabling every execution path. Read [Settings](/docs/configuration/settings) before you change one.

</Accordion>

</AccordionGroup>

## Related Articles

- [Settings](/docs/configuration/settings)
- [Core Settings](/docs/configuration/core-settings)
- [Review Agents](/docs/configuration/review-agents)
- [Tool Permissions](/docs/configuration/tool-permissions)
