# Cloud-writer helper boundary

This page explains how cloud-reachable commands invoke bundled helpers and why the source anchor and emitted command use different forms.

## Current behavior

Portable helper call sites retain the skill-directory anchor in source so local and non-Claude-Code runners can resolve the helper. Cloud-reachable command emission uses the literal vendored helper path as the leading executable token, with the portable form retained as the fallback for non-vendored execution.

The helper-boundary guards inspect the command's emitted shape and reject an unexpanded anchor, an absolute or repository-root path, a helper hidden behind another prefix, or a broad launcher grant that masks the per-helper grant.

## Why it works this way

The source form and the emitted cloud form serve different consumers. Removing the portable anchor would break local portability, while emitting the anchor literally in the cloud would violate the matcher and helper-grant boundary. Keeping the conversion at emission time satisfies both contracts without adding a second source-of-truth command fence.

## Boundaries and failure paths

- The unexpanded anchor is a valid source convention but not a valid cloud leading token.
- A granted launcher must not hide the helper's per-path grant.
- A command that fails the helper-boundary classifier is not repaired by adding a broader grant.
- The guard's current rejection matrix is authoritative; a new exception requires a measured and tested change.

## Source of truth

- `scripts/render-prompt-extension.sh` and the cloud prompt composition helpers — emitted helper forms.
- `lib/test/extract-command-heads.py` — helper-boundary classification.
- `lib/test/cloud_writer_contract.py` and `scripts/validate-cloud-writer-contract.py` — cloud writer closure and validation.
- `.github/workflows/devflow.yml`, `.github/workflows/devflow-implement.yml`, and `.github/workflows/devflow-runner.yml` — cloud call sites.
- [`docs/internal/cloud-writer-boundary.md`](../cloud-writer-boundary.md) — detailed compatibility decision record.

## Related topics

- [Prompt surfaces](prompt-surfaces.md)
- [Command permissions](../operations/command-permissions.md)
- [Working directory](../operations/working-directory.md)
