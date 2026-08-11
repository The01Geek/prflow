---
bump: patch
type: Changed
---

Review engine: the behavior-inert prose cap no longer demotes a finding that describes a real functional coverage gap. Phase 4.1.5 now states that the cap's "sole observable impact is the prose itself" conjunct means the finding's subject sentence's truth value has no effect on the shipped mechanism's runtime behavior — changing no output, no branch taken, and no set the mechanism covers — and that a finding describing a functional coverage gap is graded on its functional severity whether or not the diff touched it, including a gap in newly added or newly edited code and even when the gap is described inside a comment or docstring. The distinction is a decision question the reviewing agent answers, not a list of exempt file types, so a genuinely cosmetic doc nit stays capped as before. The vendored `receiving-code-review` scope exclusion carries the same narrowing repo-agnostically.
