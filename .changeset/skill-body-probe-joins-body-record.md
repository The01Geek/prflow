---
bump: patch
---

Fix a false-positive in `scripts/skill-body-load-probe-verdict.py`: it measured the `Skill`
tool_result — a ~30-byte `Launching skill: <name>` launch stub — as the delivered skill body, so
every verdict it could ever produce was `short-delivery`. The helper now joins each `Skill`
tool_use to the body-bearing user-role record that follows it, matching that record's
`Base directory for this skill: <dir>` line against the root's own directory. It also tolerates the
leading `#` caveat line that `scripts/scrub-transcript.sh` prepends to the published execution
transcript, which previously made that artifact unparseable. `docs/internal/skill-body-load-delivery.md`
records the corrected reading.
