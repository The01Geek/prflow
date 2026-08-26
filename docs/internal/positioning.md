# PRFlow positioning and messaging

<!-- verified-against: 26c9ad96d 2026-08-25 -->

This page is the marketing and positioning source of truth for PRFlow — the pitch, pillars, narrative, and demo script. It is for anyone writing README copy, a landing page, a talk, or a demo video. It describes how to talk about the product, not how the product behaves; coding agents looking for system behavior should skip this page.

**Primary positioning.** *PRFlow is the workflow layer that makes agentic coding work on real codebases*, it doesn't just write code, it ships it: spec → plan → code → test → review → fix → document → review-ready PR, with a self-improving loop on top. Where out-of-the-box agents demo well on pet projects and stall on a real ticket in a large production codebase, PRFlow carries that ticket to the finish line.

**Best-fit user.** A developer or team working in a **large, business-grade codebase** (production/enterprise software) who has tried agentic coding and hit the wall where it works on toy projects but can't complete a real ticket, and who is already on Claude Code + GitHub. The angles below also resonate with adjacent audiences.

**One-liner (StoryBrand elevator pitch, customer is the hero, PRFlow is the guide).** *We help developers drowning in half-finished AI pull requests turn a single request into a complete, review-ready PR, so they ship real features on a real codebase without cleaning up after the agent.*

**Three pillars (use as the deck's spine):**
1. **Works on real codebases, not just pet projects.** A one-line feature request → a codebase-grounded ticket → a complete PR ready for your final review, the full-round implementation out-of-the-box agents can't finish on production code. End-to-end, not just code; the steps a one-shot agent skips (tests, review, docs) are exactly the ones PRFlow won't.
2. **Review that fixes what it finds.** A review-and-fix loop that applies the fixes and re-reviews until it approves, on top of independent verification checklists, a panel of specialized reviewers, mechanical corroboration, and a shadow pass that audits its own approval.
3. **It learns.** A weekly retrospective reads its own track record and proposes the smallest fix that prevents the next mistake, humans approve.

**Differentiators worth naming explicitly:**
- "Ship the PR. Not the cleanup." (the hero tagline)
- "Agentic coding that works on real codebases, not just pet projects."
- "Committing code is the halfway point, not the finish line."
- Shadow review, *it audits its own audit*, with honest calibration (narrows the gap, never closes it).
- Self-improvement loop with an LLM/heuristic split (LLM only at two judgment points; everything else is zero-token deterministic).
- Two tiers: works locally with **zero config**, scales to **autonomous** cloud automation with one secret by default.
- Built on Claude Code's plugin system; ships its full review/discovery/authoring toolchain first-party (hard-forked from Anthropic's `pr-review-toolkit` + `feature-dev` agents and the `superpowers` skills, upstream licenses retained) — **zero companion-plugin dependencies**.
- Security-explicit: base-ref trust boundary, deny-list floor, read-only-by-default reviewer.

**The sales narrative (the argument arc, use it in a pitch, a landing page, or a talk):**

- **Problem.** You've adopted an AI coding agent. It's dazzling on a demo repo, and then you point it at a real ticket in your actual production codebase, and it comes back half-done: wrong patterns, missing tests, stale docs, acceptance criteria unmet. Your engineers now spend *more* time fixing and reviewing the agent's output than the agent saved.
- **The old way.** Babysit the agent prompt-by-prompt, or hand the whole ticket to a senior engineer who does spec → plan → implement → test → review → fix → document by hand, slowly, expensively, and inconsistently, on every ticket.
- **Why now.** AI has made *writing* code cheap. The bottleneck moved to everything around it, planning against real architecture, rigorous review, keeping docs in sync, at scale, on every change. That's precisely where out-of-the-box agents stall.
- **The new way.** PRFlow takes a one-line request, turns it into a codebase-grounded issue through a few sharp clarifying questions, then runs the full `/prflow:implement` lifecycle, plan, architect, implement, auto-generate the test automation it needs, review-and-fix iterations with a shadow pass that audits its own approval, and docs, and hands you a complete PR that meets every acceptance criterion. Then it improves itself every week.
- **Proof.** Independent verification checklists; a panel of specialized reviewers with mechanical corroboration; shadow review (on PR #58 it agreed with full coverage, yet a standalone `/prflow:review` still surfaced hardening items, calibration kept honest); the weekly retrospective that opens its own improvement PRs.
- **The ask.** `claude plugin install devflow`, runs locally with zero config; add one secret (by default) to go fully autonomous in CI.

**Honest-claims guardrails (keep marketing accurate):**
- The in-loop shadow review **narrows** the gap to an independent review; it does **not** replace a standalone `/prflow:review`. Don't claim it "guarantees" completeness.
- A human still does the final review and merge, PRFlow gets the PR *ready*, it doesn't auto-merge.
- The retrospective loop proposes interventions; **humans approve or reject**. It never auto-merges its own changes.
- The local tier needs `git`, `gh`, `jq`, and Python 3.11+ on PATH (PyYAML is advisory on this tier — reported but not gated by preflight); the cloud tier needs `CLAUDE_CODE_OAUTH_TOKEN` by default (an optional third-party model provider adds `DEVFLOW_PROVIDER_API_KEY`).

**Audiences & angles:**
- **Engineering leaders:** consistency, auditability, reduced review burden, telemetry on reviewer effectiveness.
- **Individual developers:** turn a rough idea into a merged PR without context-switching; runs in your editor with zero setup.
- **Security/platform teams:** explicit threat model, base-ref trust boundary, read-only-by-default automation, one secret by default.
- **AI/ML audience:** the evaluator/optimizer architecture, independent verification, structural-independence in self-review.

**Demo beats for a video (in order):** rough idea → `/prflow:create-issue` interview → confirmed issue #42 → comment `/prflow:implement 42` → watch the workpad update live (🚀) → draft PR appears → review-and-fix loop + shadow pass → docs updated → PR flips to ready (🎉) → the review-gate check posts APPROVE → human merges. Optionally close with a `/prflow:retrospective-weekly` run filing an improvement issue for the next cycle, "it just got better."
