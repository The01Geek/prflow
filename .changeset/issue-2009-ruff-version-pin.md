---
bump: patch
type: Fixed
---

- **Pin ruff at 0.16.4 in the lint manifest and refuse a whole-suite launch on a ruff version skew.** `.prflow/lint-manifest.json` still pinned `ruff` at `0.6.9` after issue #742 advanced CI to `ruff==0.16.*`, so provisioning installed a 0.6.9 ruff into `prflow-lint-bin` that shadowed PATH and reddened the `#1621` in-suite ruff gate on rule-set skew rather than on real findings. The manifest now pins the newest 0.16.x release (0.16.4) with refreshed per-os/arch sha256 digests, and `lib/test/run-parallel.sh`'s cheap-lint pre-launch gate now refuses a launch — in under a second, before any shard — when the ruff on PATH positively reports a family that skews from the manifest pin, naming the `python3 -m pip install --user --force-reinstall 'ruff==0.16.*'` remedy; it fails open (proceeds) when the probe cannot run (ruff absent or non-executing) and reads its expected version from the manifest at run time. A suite assertion reconciles the manifest pin against CI's `ruff==` family so the two can no longer silently disagree. (#2021)
