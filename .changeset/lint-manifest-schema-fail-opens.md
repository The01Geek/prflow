---
bump: patch
type: Fixed
---

- **Close two schema-side fail-opens in the lint-manifest validator
  (`scripts/lint_manifest.py`).** A manifest that selects no files at all —
  `include_globs: []`, or a present-but-empty `exclude_globs` / `exclusions` —
  validated as `established`, so a consumer would enumerate zero files and report
  a clean lint having linted nothing; the glob lists now enforce non-emptiness
  like their `selectors` / `full_profiles` / `artifacts` siblings. Separately, the
  path-shaped fields (`include_globs`, `exclude_globs`, `exclusions`,
  `special_invocations[].path`) accepted `../../../etc/passwd`, `/etc/passwd`,
  `..`, and leading-dash tokens such as `-x` / `--exclude`, the last of which a
  ShellCheck/Ruff argv parses as an *option* rather than a path; they are now
  required to be repo-relative and argv-safe. Both defects were latent — nothing
  consumes the manifest yet. (#1276)
