---
schema: 1
kind: growth
---
# Issue #672 — retrospective skill redaction note (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

- `skills/retrospective/SKILL.md` — mandatory (skill-roots group), grew +372 bytes
  (20199 → 20571).

## Justification

Issue #672 adds an operator-home-path redaction guard to
`lib/materialize-retrospectives.sh`, which rewrites operator home-directory
prefixes to `~` on the retrospective merge write path before records are
committed to the tracked, published corpus. This skill's prose previously
asserted that the corpus preserves the bot's friction verbatim ("friction
sanitized out of commit messages and PR descriptions survives here"), which now
over-asserts: it would tell an analyzing agent the corpus is fully unredacted,
so the agent could cite a `~`-rewritten path as verbatim or expect operator
paths to appear. The added bytes are a single reconciling clause naming the one
redacted class (operator home-directory prefixes → `~`) and stating that
GitHub-Actions runner paths and every other string are preserved unchanged. This
is load-bearing accuracy on the mandatory read path that the retrospective Stage
A analysis subagent consumes — an agent that trusts the stale claim mis-reads the
corpus — so the bytes belong on the mandatory path rather than a conditional
reference.
