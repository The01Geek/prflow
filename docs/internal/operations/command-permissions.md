# Command permissions and shapes

This page explains how PRFlow grants commands to execution tiers and why the exact command shape matters.

## Current behavior

Cloud workflows resolve allowed command heads from the capability profiles and repository configuration. Desk-time guards extract command heads and composite shapes from the executable prompt surfaces and compare them with the tier profile. A command can have a permitted head and still be denied because its wrapper, redirect, interpreter, working-directory form, or helper path has a refused shape.

Bundled helpers use the tier's permitted vendored or portable path convention. Generated workflow literals are derived from the versioned capability manifest rather than hand-maintained independently in every workflow.

## Why it works this way

The permission boundary is both a security control and a runtime contract. Testing only command names misses the matcher behavior that actually refuses composite forms, while hand-copied allowlists drift across jobs. Extracted shape checks and generated profiles keep the authoring surface aligned with the execution surface.

## Boundaries and failure paths

- A denied command produces no useful application result; retry the documented permitted form before diagnosing the code.
- A broad grant that covers a narrower helper path widens the trust boundary and is rejected by the helper-boundary checks.
- Local classifier behavior is not evidence about cloud matcher behavior.
- An unestablished probe result must not be turned into an allow or deny claim.

## Source of truth

- `lib/capability-profiles.json` — versioned capability policy.
- `lib/generate-capability-profiles.py` — workflow literal generation.
- `lib/test/extract-command-heads.py` and `lib/test/extract-command-shapes.py` — command guards.
- `lib/test/run.sh` — profile and prompt-surface checks.
- `.github/workflows/devflow.yml`, `.github/workflows/devflow-implement.yml`, and `.github/workflows/devflow-runner.yml` — tier grants.
- [`docs/internal/cloud-allowlist.md`](../cloud-allowlist.md) — probe tables and detailed rationale.

## Related topics

- [Agent permissions](../agents/agent-permissions.md)
- [Prompt surfaces](../architecture/prompt-surfaces.md)
- [Working directory](working-directory.md)
