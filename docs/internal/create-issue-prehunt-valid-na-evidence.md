<!--
SPDX-FileCopyrightText: 2026 Daniel Radman
SPDX-License-Identifier: MIT
-->
# Evidence: pre-hunt `valid-N/A` classification (create-issue Step 3.6 audit, issue #1686)

This file is the reproducible before-and-after behavioral evidence for the change that moves
dimension-applicability classification ahead of the finding hunt in the create-issue Step 3.6
fresh-context audit (`skills/create-issue/references/audit-prompt-template.md` and
`skills/create-issue/references/step-3-6-audit-adjudication.md`, the coverage/calibration member
that issue #1702's Step 3.6 decomposition split out of the former `step-3-6-audit.md`).

The change is agent-executed prompt prose whose only reader is the runtime audit reviewer, so per
this repository's recorded position (issues #843/#876) it carries no automated regression coverage;
the compensating control is the review pass, and this record is the reproducible behavioral
evidence the issue's acceptance criteria call for.

## Hypothesis

After the change, a dimension the reviewer classifies as *plainly inapplicable* is routed to the
existing `valid-N/A` coverage outcome **before** the finding hunt and is not hunted for findings,
while every dimension that *applies* or whose applicability is *uncertain* still receives the full
examination it received before the change. Before the change, applicability was recorded only after
the finding hunt, so every dimension — including a plainly-inapplicable one — was hunted.

## Fixed input under audit

A single fixed draft is used for the isolated demonstration below. It plants a portability defect
(`grep -P` and `sed 's/\s\+/-/g'`, both GNU-only — banned by this repo's portability convention)
that the **Host-OS variance** dimension must catch, while **Degraded environments** and
**Adversarial third-party input** plainly do not apply (a deterministic slug transform, no LLM or
semantic judgment over third-party text):

> Title: *Add a slug helper that derives a branch name from an issue title*.
> Desired Behavior: `scripts/derive-slug.sh "<issue title>"` lowercases the title, replaces every
> run of non-alphanumeric characters with a single hyphen, trims leading/trailing hyphens, and
> "uses `grep -P '(?<=-)-'` to collapse doubled hyphens and `sed 's/\s\+/-/g'` to replace
> whitespace." AC: the helper prints `fix-the-login-bug` for `"Fix the Login Bug!"`; every caller
> that previously derived a slug inline calls the helper instead.

## Isolated before/after demonstration (observed)

Three fresh-context audit reviewers were run over the fixed draft:

- **BEFORE (old post-hunt prompt).** The reviewer hunted **every** dimension, including
  `degraded-environments` — a plainly-inapplicable dimension with no internal applicability gate —
  and recorded it `exercised` only after that hunt.
- **AFTER (new classify-before-hunt prompt).** The reviewer produced a pre-hunt classification that
  routed `degraded-environments` and `adversarial-third-party-input` to `valid-N/A` with specific,
  draft-grounded reasons **and performed no finding hunt under them**, while the applicable
  dimensions (`host-os-variance`, `execution-tier-variance`, `load-bearing-assumptions`,
  `second-order-effects`) received the full examination and caught the planted `grep -P` / `sed
  \s\+` portability defect.
- **CONTROL (no dimension guidance).** The reviewer still found the portability defect but emitted
  **no** per-dimension classification or coverage, confirming the pre-hunt classification behavior
  is driven by the shipped prompt prose rather than intrinsic to the model.

The behavioral difference the acceptance criterion asserts — plainly irrelevant dimensions avoid
the finding hunt while applicable and uncertain dimensions retain full scrutiny — is therefore
shown, and the applicable-dimension scrutiny (catching the planted defect) is preserved in both the
BEFORE and AFTER arms.

## Reproduction

The isolated demonstration above is a single-run demonstration and is not a cost measurement; do
not infer a cost or round-count improvement from it. To measure audit-round cost and round counts
across a corpus and report corpus sizes, capture baseline and revised transcript corpora over a
fixed draft set — the issue names four draft types: a prose-only draft with plainly irrelevant
environment dimensions, a draft with a planted portability defect (above), an ambiguous draft that
must receive full scrutiny, and a hostile draft that declares a relevant dimension inapplicable —
and run the existing measurement surface in paired mode:

```bash
scripts/create-issue-context-eval.py <baseline-corpus> <revised-corpus>   # see its --help for the paired-mode flags
```

`scripts/create-issue-context-eval.py` is not part of the runtime create-issue path; it reads
session transcripts and reports audit-round cost and round-count changes. Report the corpus sizes
alongside the paired result and do not infer improvement from a single run.
