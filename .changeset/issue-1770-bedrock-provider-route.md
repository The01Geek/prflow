---
bump: patch
type: Added
---

- **Cloud tier `providers` map gains an AWS Bedrock route.** A provider entry may now set
  `auth: bedrock_api_key` to route that section to Amazon Bedrock with a long-lived Bedrock API
  key stored in the existing `DEVFLOW_PROVIDER_API_KEY` secret. Such an entry needs no `base_url`,
  takes its AWS region from the entry's `env` map (`AWS_REGION`, required), exports the key as
  `AWS_BEARER_TOKEN_BEDROCK`, and passes the action's `use_bedrock` input — no second secret and no
  AWS role setup. The existing `bearer` and `api_key` auth arms and the Anthropic default path keep
  their prior job-environment variables and action inputs, pinned by the existing `#313` regression
  fixtures. (#1778)
