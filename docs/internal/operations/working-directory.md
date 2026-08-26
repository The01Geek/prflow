# Working-directory contract

This page explains where commands run and how path assumptions differ by execution tier.

## Current behavior

Cloud workflows establish the repository workspace and carry the working directory through the job contract. Local and interactive sessions do not provide the same universal cwd guarantee, so a skill or helper must resolve paths from the repository or skill anchor instead of relying on a prior `cd`.

The command-shape policy treats working-directory changes as part of the permission contract. A path-sensitive helper should use the documented repository-root or portable anchor form for the tier in which it runs.

## Why it works this way

The same skill runs through multiple clients and workflow wrappers. A working-directory assumption that is implicit in one client can point a helper at the wrong repository or be denied by the cloud matcher in another, so path resolution is made explicit.

## Boundaries and failure paths

- Do not infer the current repository from the shell prompt.
- Do not add a leading `cd` or `git -C` form to a cloud-reachable command without checking the tier's shape contract.
- A missing repository root or skill anchor is an unestablished path, not permission to guess.

## Source of truth

- `lib/resolve-state-dir.sh` and path-resolution helpers under `lib/` — repository and state paths.
- `skills/*/SKILL.md` — command-specific path invocation conventions.
- `.github/workflows/*.yml` — cloud checkout and workspace setup.
- [`docs/internal/working-directory-contract.md`](../working-directory-contract.md) — detailed tier contract and evidence.
- [Command permissions](command-permissions.md) — shape rules that interact with cwd.

## Related topics

- [Execution model](../architecture/execution-model.md)
- [Installation](installation.md)
