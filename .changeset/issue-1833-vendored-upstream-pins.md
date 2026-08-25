---
bump: patch
type: Changed
---

- **Record the upstream revision each vendored third-party skill and agent was last reconciled against, and stop the vendored reviewer from spawning sub-reviewers.** `LICENSES/README.md` now carries a per-file "Last reconciled against" column (`superpowers 6.3.0` for the superpowers-derived skills; a `claude-plugins-official` commit SHA for the seven Anthropic-plugin agents), so a future refresh starts from a recorded pin instead of git archaeology. The vendored reviewer prompt (`skills/requesting-code-review/code-reviewer.md`) now directs the reviewer to review the whole diff itself in multiple passes and never dispatch a subagent for part of the diff or a second opinion, since a spawned sub-reviewer duplicates a reviewer seat at full cost while its verdict counts for nothing. (#1952)
