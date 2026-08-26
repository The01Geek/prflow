---
schema: 1
kind: growth
---
# Issue #711 — tree enumeration growth (historical record)

> Historical record — not current behavior. See the canonical topic pages under `docs/internal/` for the present rules.


## Files

- `CLAUDE.md` — +1,916 bytes (72,592 → 74,508).

Two edits land there. One Conventions bullet is added: the enumeration-source rule requiring a
suite assertion or lint helper that enumerates the repository tree to source its population from
an index-reading `git ls-files`, naming the sibling-worktree false-red as the reason and
`lib/test/lint-tree-enumeration.py` as the enforcing mechanism. That bullet states the guard's
enforcement scope precisely — an *undeclared* walk, with the shell arm firing on a path operand
that textually resolves under the repository root — and points at the helper's own docstring for the closed
residual set rather than restating a scope that would drift. The existing `#664` gotcha bullet
is also reconciled: it enumerates `lib/test/lint-gh-api-repo-path.py`'s exclusion set in prose,
and this change adds `.claude/worktrees/` to that set, so the prose mirror would otherwise have
gone stale in the same diff that moved the code.

No mandatory row is reduced or relocated by this change, and no prose ownership transfers away
from an existing surface, so `growth` is the only audited decision this diff needs. The other
prose this change adds — the guard's module docstring and the `CONTRIBUTING.md` marker-family
paragraph — lands on files outside `SWEEP_PATTERNS` and moves no measured row.

## Justification

The rule cannot be restated as a conditionally-loaded reference, because the moment it must fire
is the moment an author is *writing* an enumeration — before any failure exists to route them to
a rare-path document. A reference load happens on a predicate the author has already failed to
evaluate.

It also cannot be discharged by the guard alone. `lib/test/lint-tree-enumeration.py` reports an
undeclared walk under `lib/test/`, which is a desk-time net over one subtree; the Conventions
bullet states the *source-selection policy* that the net only partially enforces — that a
working-tree enumeration (`--others`, even with `--exclude-standard`) is not worktree-immune
either, because its protection is untracked `.git/info/exclude` state no clone inherits. That
half is unenforceable by any lint the repository has, since it is a property of a helper's
argument list rather than of a token, and `lib/test/lint-gh-api-repo-path.py` is the live proof
that an author reached for the permeable form without a rule to stop them. Policy the mechanism
cannot cover is exactly the retained category the prose-cutover contract keeps on the mandatory
path.

The bullet is one paragraph and carries no measured figure, so an ordinary re-measure never
re-edits it.
