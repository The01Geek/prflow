---
schema: 1
kind: growth
---
# Issue #745 — run sh ci lint (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

- `CLAUDE.md` — +1296 bytes (baseline row 74508 → 75804).

No other mandatory row moved; no prose was removed or relocated, and no decision changed owner.

## Justification

Issue #745 makes `lib/test/run.sh` ShellCheck-analysed in CI, which is only possible under a
conjunction a maintainer cannot infer from the command line alone: `--extended-analysis=false`
**and** a pinned ShellCheck ≥ 0.10.0. The added bytes are the statement of that conjunction and
of what happens when either half is missing, and they belong on the mandatory path for three
reasons:

1. **The failure mode is silent, so the rule cannot live in a conditional reference.** On
   ShellCheck 0.9.x — the version `ubuntu-latest` ships — `--extended-analysis=false` errors and
   the equivalent `# shellcheck extended-analysis=false` directive is ignored with SC1107. A
   maintainer who runs the documented desk command on a 0.9.x host sees an OOM or a flag error
   and has no way to tell that the *version*, not the command, is wrong. The version floor has
   to be readable at the same moment as the command it gates.
2. **It states a policy and a decision point, which the retained-content rule keeps in the
   mandatory path.** The bytes say which binary CI uses (a pinned one, not the image's), what
   the flag costs (SC2319 only), and where the rest of `lib/test/` is linted from — a policy
   plus the two things a maintainer must decide about when adding a `lib/test` script.
3. **It is the reader-facing half of a machine-enforced contract.** `lib/test/lint-carveout-guard.py`
   turns the suite RED when a tracked `lib/test` script is neither CI-linted nor under
   `lib/test/fixtures/`. The added prose is what tells a maintainer, at the desk, what that RED
   means and which of the two sides to put the new file on. A guard whose remedy is documented
   only in a rare-path reference sends the reader looking after the suite is already red.

The `Commands` block itself grows by one line (the `run.sh` lint invocation); the remainder is
the single paragraph stating the version floor, the flag's cost, and the carve-out guard.
