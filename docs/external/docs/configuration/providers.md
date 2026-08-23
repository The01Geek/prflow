---
title: "Model Providers"
description: "Route cloud execution sections through Anthropic-compatible endpoints or Amazon Bedrock."
---

Route a cloud execution section through an Anthropic-compatible gateway or proxy, or through Amazon Bedrock. Provider routing is best effort, and a gateway or non-Anthropic model can behave differently from the Anthropic default.

## Provider Entry Settings

Each key under `providers` is a provider name.

| **Setting** | **Type and accepted values** | **Fallback** | **Tier and security note** | **Example** |
| --- | --- | --- | --- | --- |
| `providers.<name>.base_url` | String URL without a trailing `/v1` API segment. Required for `bearer` and `api_key`; optional and ignored for `bedrock_api_key` | None; a `bearer`/`api_key` job fails if absent. A stray `base_url` on a `bedrock_api_key` entry is ignored with a warning | Cloud only. The endpoint receives model requests and their content. | `"base_url": "https://gateway.example.com"` |
| `providers.<name>.auth` | Required `bearer`, `api_key`, or `bedrock_api_key` | None; a routed job fails if invalid | Cloud only. All three use the fixed `DEVFLOW_PROVIDER_API_KEY` secret. `bedrock_api_key` treats it as an Amazon Bedrock API key (exported as `AWS_BEARER_TOKEN_BEDROCK`, with `use_bedrock`) and requires `AWS_REGION` in `env`. | `"auth": "bearer"` |
| `providers.<name>.timeout_ms` | Optional integer milliseconds | Action or client default | Cloud only. Use a positive value supported by the endpoint. | `"timeout_ms": 3000000` |
| `providers.<name>.effort_supported` | Boolean | `false` | Cloud only. False removes `--effort` to avoid gateway rejection. | `"effort_supported": false` |
| `providers.<name>.env` | Object with environment-variable names and string values | Empty object | Cloud only. Values are exported into the job environment. Some names are refused outright — see *Refused `env` names* below. | `"env": {"CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1"}` |

**Warning:** `.prflow/config.json` is committed repository content. Never place tokens, passwords, private keys or other secret values in `providers.<name>.env`. Store credentials in GitHub Actions secrets and reference only supported secret-backed inputs.

### Refused `env` names

The `env` map is exported into the environment of the whole job, not just the model step, so a
name that means something to the runner does more than add a variable. Before exporting anything,
the job checks every key against a fixed list of names and **fails with an error naming the key**
if it finds one. Nothing is exported on that run. Matching ignores case, so a lowercase spelling
is refused too. Any name not on the list is exported exactly as written.

| Refused because | Names |
| --- | --- |
| It is a credential, and this file is committed to your repository | `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AWS_BEARER_TOKEN_BEDROCK` |
| It would shadow the job's own environment or GitHub's plumbing | `PATH`, `GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_ENV`, `GITHUB_OUTPUT`, `GITHUB_PATH` |
| It is an interpreter or loader hook, so it would run code in every later step | `BASH_ENV`, `ENV`, `LD_PRELOAD`, `LD_LIBRARY_PATH`, `DYLD_INSERT_LIBRARIES`, `NODE_OPTIONS`, `PYTHONPATH` |
| It overrides the model for every subagent, collapsing your review roster to one model | `CLAUDE_CODE_SUBAGENT_MODEL` |

To supply the provider credential, set the `DEVFLOW_PROVIDER_API_KEY` secret instead. To change
only the background model, use `ANTHROPIC_DEFAULT_HAIKU_MODEL`, which is not refused.

## Section Routing Settings

| **Setting** | **Type and accepted values** | **Fallback** | **Tier and security note** | **Example** |
| --- | --- | --- | --- | --- |
| `prflow.provider` | String matching a provider name | Anthropic OAuth route | General cloud command workflow. Requires `DEVFLOW_PROVIDER_API_KEY` when set. | `"provider": "gateway"` |
| `prflow.claude_model` | String model identifier | Top-level `claude_model` | General cloud command workflow. Use the identifier expected by the route. | `"claude_model": "provider/model"` |
| `prflow_implement.provider` | String matching a provider name | Anthropic OAuth route | Shipped implementation path. Requires `DEVFLOW_PROVIDER_API_KEY` when set. | `"provider": "gateway"` |
| `prflow_implement.claude_model` | String model identifier | Top-level `claude_model` | Shipped implementation path. | `"claude_model": "provider/model"` |
| `prflow_runner.provider` | String matching a provider name | Anthropic OAuth route | **Retained legacy setting** for the withheld automatic-review runner. No effect in fresh installs. | `"provider": "gateway"` |
| `prflow_runner.claude_model` | String model identifier | Top-level `claude_model` | **Retained legacy setting** for the withheld runner. | `"claude_model": "provider/model"` |

## Configure a Provider Route

1. Add `DEVFLOW_PROVIDER_API_KEY` as a repository or environment secret.
2. Add the provider entry.
3. Point each desired active section at the entry.
4. Keep `CLAUDE_CODE_OAUTH_TOKEN` until every active section is routed and tested.

```json
{
  "providers": {
    "gateway": {
      "base_url": "https://gateway.example.com",
      "auth": "bearer",
      "timeout_ms": 3000000,
      "effort_supported": false,
      "env": {
        "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1"
      }
    }
  },
  "prflow": {
    "provider": "gateway",
    "claude_model": "provider/model"
  },
  "prflow_implement": {
    "provider": "gateway",
    "claude_model": "provider/model"
  }
}
```

## Route Through Amazon Bedrock

Set `auth` to `bedrock_api_key` to reach Amazon Bedrock instead of an HTTP gateway. Store a long-lived Bedrock API key in the same `DEVFLOW_PROVIDER_API_KEY` secret — no second secret and no AWS role setup. Such an entry needs no `base_url`; instead it **must** set `AWS_REGION` in its `env` map, and its section's `claude_model` must be a Bedrock-form model identifier (the shipped Claude default is not served by Bedrock).

```json
{
  "providers": {
    "bedrock": {
      "auth": "bedrock_api_key",
      "timeout_ms": 3000000,
      "effort_supported": false,
      "env": {
        "AWS_REGION": "us-east-1"
      }
    }
  },
  "prflow_implement": {
    "provider": "bedrock",
    "claude_model": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
  }
}
```

A `bedrock_api_key` job whose `env` map sets no `AWS_REGION` fails before the model action starts, with an error naming the section and provider. A `bedrock_api_key` entry that also carries a `base_url` runs, but the `base_url` is ignored with a warning.

A selected provider with a missing secret, undefined entry, empty URL (on the `bearer`/`api_key` arms), invalid auth value, invalid environment-variable name, or a refused `env` name fails before the model action starts.
