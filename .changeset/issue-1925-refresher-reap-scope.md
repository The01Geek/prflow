---
bump: patch
type: Fixed
---

- **The credential-refresher teardown now establishes a reap scope before sweeping, so it no longer kills a live refresher and no longer silently no-ops on a Windows-form temporary directory.** `scripts/stop-refresher.sh` normalizes the temporary directory it derives its reap glob from through `lib/normalize-path.sh` before composing the pattern, and reaps nothing (printing a breadcrumb that names the unusable value) when that value cannot be expressed as a POSIX glob root — a Windows-form path with no `wslpath`/`cygpath` and no WSL/MSYS signal, or a UNC path. An explicitly supplied `DEVFLOW_REFRESH_REAP_GLOB` is used verbatim, with no conversion. The two writer workflows stop publishing the self-test marker path job-wide; the teardown step now derives it from the same handle the start step uses, mirroring the `DEVFLOW_GH` decision. (#1930)
