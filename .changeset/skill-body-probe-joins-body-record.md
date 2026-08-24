---
bump: patch
---

Fix a false-positive in `scripts/skill-body-load-probe-verdict.py`: it measured the `Skill`
tool_result — a ~30-byte `Launching skill: <name>` launch stub — as the delivered skill body, so
every verdict it could ever produce was `short-delivery`. The helper now joins each `Skill`
tool_use to the body-bearing user-role record that follows it, matching that record's
`Base directory for this skill: <dir>` line against the root's own directory. It also tolerates the
leading `#` caveat line that `scripts/scrub-transcript.sh` prepends to the published execution
transcript, which previously made that artifact unparseable. The now-dead capture of the launch
stub's own content is removed, and the module docstring, the suite block's header comment and
`docs/internal/skill-body-load-delivery.md`'s live re-run procedure no longer describe the
`tool_result` as the measured operand. `docs/internal/skill-body-load-delivery.md` records the
corrected reading. The suite drives the directory match on the shape production actually takes —
an absolute runner base directory against a repo-relative `--root`, which only the suffix branch
resolves — together with its component-boundary guard and the leading-comment stripper's
interior-`#` contract.
